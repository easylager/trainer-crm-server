"""
Импорт ледовых магазинов и мастерских из файла партнёра (TASK-146).

Источник — ``data/catalog/shops-<город>.json`` (перенос документа партнёра как есть).
Скрипт-обёртка: ``scripts/load_catalog_shops.py`` (по умолчанию dry-run).

Правила, которые важнее скорости:

* **Только названное.** Услуга попадает в карточку, только если источник её назвал.
  Не названное — «неизвестно» (ключа нет), а не «нет» (``False``): в карточке не
  появится ложное «заточки нет» у мастерской, про которую мы просто не знаем.
* **Повторный запуск не плодит дубли.** Магазин ищется по имени в городе; найден —
  обновляется, нет — создаётся. Имя — ключ, поэтому переименование в файле создаст
  новую карточку: это видно в плане (``create``) до ``--apply``.
* **Каток с заточкой — только при однозначном совпадении.** «Чижовка» может найти и
  большую, и малую арену — тогда ничего не пишем и говорим об этом в отчёте.
* **Не только магазины.** ``venue_type`` в записи (``shop`` по умолчанию, ``ice``,
  ``outdoor``) заводит и пропущенные катки: их ищем по имени и по ``match`` среди
  всех мест города, чтобы «Олимпик Арена» из файла не задвоила «Олимпик-арену» в базе.
* **Фото — из файла партнёра и только одно, если у места фото ещё нет.** Повторный
  запуск не плодит копии; фото, загруженное админом руками, не трогаем. Лицензия —
  ``permitted`` с атрибуцией «материалы партнёра».
* **Координаты не выдумываем.** Геокодер — снаружи (Nominatim в скрипте); нет ответа —
  место есть в списке и на своей странице, но не на карте.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_profile import (
    amenity_keys_for_venue,
    WEEKDAY_KEYS,
    apply_admin_arena_profile_patch,
    ensure_arena_profile,
    normalize_hhmm,
)

#: Что можно завести из файла. Зал и прочее — руками в админке: там нет общих полей.
IMPORT_VENUE_TYPES = frozenset({"shop", "ice", "outdoor"})

DISCIPLINE_KEYS = {"hockey": "discipline_hockey", "figure": "discipline_figure", "roller": "discipline_roller"}

Geocoder = Callable[[str, str], Awaitable[tuple[float, float] | None]]


class ShopImportError(ValueError):
    """Файл партнёра не проходит проверку — ничего не пишем."""


@dataclass
class ShopRecord:
    key: str
    name: str
    address: str | None
    address_note: str | None
    phones: list[str]
    website: str | None
    instagram: str | None
    description: str | None
    amenities: dict[str, bool]
    hours: dict[str, list[str]] | None
    venue_type: str = "shop"
    match: list[str] = field(default_factory=list)
    season: tuple[int, int] | None = None
    tickets_url: str | None = None
    photo: Path | None = None

    @property
    def display_address(self) -> str | None:
        if not self.address:
            return None
        note = self.address_note
        if not note:
            return self.address
        # «(здание Дворца спорта…)», но «(ТЦ «Тивали»…)» — аббревиатуру не ломаем.
        if len(note) > 1 and note[0].isupper() and note[1].islower():
            note = note[0].lower() + note[1:]
        return f"{self.address} ({note})"

    @property
    def short_description(self) -> str | None:
        bits = [self.description or ""]
        if len(self.phones) > 1:
            bits.append("Ещё телефоны: " + ", ".join(self.phones[1:]) + ".")
        text_value = " ".join(b for b in bits if b).strip()
        return text_value or None


@dataclass
class ImportPlan:
    city_id: int
    city_name: str
    creates: list[ShopRecord] = field(default_factory=list)
    updates: list[tuple[int, ShopRecord]] = field(default_factory=list)
    rink_updates: list[tuple[int, str]] = field(default_factory=list)
    rink_problems: list[str] = field(default_factory=list)


def parse_shops_file(path: Path) -> tuple[str, list[ShopRecord], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    photo_root = path.resolve().parent
    city = str(data.get("city") or "").strip()
    if not city:
        raise ShopImportError("city is required")
    records: list[ShopRecord] = []
    seen: set[str] = set()
    for raw in data.get("shops") or []:
        records.append(_parse_record(raw, photo_root=photo_root))
        name_key = records[-1].name.lower()
        if name_key in seen:
            raise ShopImportError(f"duplicate shop name: {records[-1].name}")
        seen.add(name_key)
    return city, records, list(data.get("rink_sharpening") or [])


def _parse_record(raw: Mapping[str, Any], *, photo_root: Path | None = None) -> ShopRecord:
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ShopImportError(f"shop without name: {raw.get('key')}")
    venue_type = str(raw.get("venue_type") or "shop").strip()
    if venue_type not in IMPORT_VENUE_TYPES:
        raise ShopImportError(f"{name}: venue_type must be one of {sorted(IMPORT_VENUE_TYPES)}")
    allowed = amenity_keys_for_venue(venue_type)
    amenities: dict[str, bool] = {}
    for service in raw.get("services") or []:
        if service not in allowed:
            raise ShopImportError(f"{name}: unknown service {service!r}")
        amenities[service] = True
    for discipline in raw.get("disciplines") or []:
        key = DISCIPLINE_KEYS.get(discipline)
        if key is None or key not in allowed:
            raise ShopImportError(f"{name}: unknown discipline {discipline!r}")
        amenities[key] = True
    hours = raw.get("hours")
    if hours is not None:
        for day, pair in hours.items():
            if day not in WEEKDAY_KEYS:
                raise ShopImportError(f"{name}: unknown weekday {day!r}")
            if pair is not None and (len(pair) != 2 or not all(normalize_hhmm(p) for p in pair)):
                raise ShopImportError(f"{name}: bad hours for {day}: {pair!r}")
    website = (raw.get("website") or "").strip() or None
    if website and not website.lower().startswith(("https://", "http://")):
        raise ShopImportError(f"{name}: website must be http(s): {website}")
    instagram = (raw.get("instagram") or "").strip().lstrip("@") or None
    season = raw.get("season")
    if season is not None:
        if not (isinstance(season, list) and len(season) == 2 and all(isinstance(m, int) and 1 <= m <= 12 for m in season)):
            raise ShopImportError(f"{name}: season must be [start_month, end_month]")
        season = (season[0], season[1])
    photo: Path | None = None
    if raw.get("photo"):
        photo = ((photo_root or Path.cwd()) / str(raw["photo"])).resolve()
        if not photo.is_file():
            raise ShopImportError(f"{name}: photo not found: {raw['photo']}")
    tickets = (raw.get("tickets_url") or "").strip() or None
    if tickets and not tickets.lower().startswith(("https://", "http://")):
        raise ShopImportError(f"{name}: tickets_url must be http(s): {tickets}")
    return ShopRecord(
        key=str(raw.get("key") or name),
        name=name,
        address=(raw.get("address") or "").strip() or None,
        address_note=(raw.get("address_note") or "").strip() or None,
        phones=[str(p).strip() for p in raw.get("phones") or [] if str(p).strip()],
        website=website,
        instagram=instagram,
        description=(raw.get("description") or "").strip() or None,
        amenities=amenities,
        hours=hours,
        venue_type=venue_type,
        match=[str(m).strip().lower() for m in raw.get("match") or [] if str(m).strip()],
        season=season,
        tickets_url=tickets,
        photo=photo,
    )


async def build_plan(
    session: AsyncSession,
    *,
    city_name: str,
    records: list[ShopRecord],
    rink_rules: list[Mapping[str, Any]],
    speed_oval_arena_id: int | None = None,
) -> ImportPlan:
    city = (
        await session.execute(
            text("SELECT id, name FROM cities WHERE lower(name) = lower(:n) ORDER BY id LIMIT 1"),
            {"n": city_name},
        )
    ).first()
    if city is None:
        raise ShopImportError(f"city not found: {city_name}")
    plan = ImportPlan(city_id=int(city[0]), city_name=str(city[1]))

    city_rows = (
        await session.execute(
            text("SELECT id, name, venue_type FROM arenas WHERE city_id = :c ORDER BY id"),
            {"c": plan.city_id},
        )
    ).fetchall()
    for rec in records:
        same_kind = [r for r in city_rows if (r[2] == "shop") == (rec.venue_type == "shop")]
        exact = [r for r in same_kind if str(r[1]).strip().lower() == rec.name.lower()]
        hits = exact or [r for r in same_kind if rec.match and any(m in str(r[1]).lower() for m in rec.match)]
        if len(hits) == 1:
            plan.updates.append((int(hits[0][0]), rec))
        elif not hits:
            plan.creates.append(rec)
        else:
            names = ", ".join(f"#{r[0]} {r[1]}" for r in hits)
            plan.rink_problems.append(f"{rec.name}: несколько совпадений ({names}) — уточните match в файле")

    rinks = (
        await session.execute(
            text(
                "SELECT id, name FROM arenas WHERE city_id = :c AND is_active "
                "AND venue_type IN ('ice', 'outdoor') ORDER BY id"
            ),
            {"c": plan.city_id},
        )
    ).fetchall()
    for rule in rink_rules:
        needles = [str(n).lower() for n in rule.get("match") or []]
        note = str(rule.get("note") or needles)
        if "speed_oval" in needles and speed_oval_arena_id is not None:
            if any(int(r[0]) == int(speed_oval_arena_id) for r in rinks):
                plan.rink_updates.append((int(speed_oval_arena_id), note))
                continue
        hits = [r for r in rinks if any(n != "speed_oval" and n in str(r[1]).lower() for n in needles)]
        if len(hits) == 1:
            plan.rink_updates.append((int(hits[0][0]), note))
        elif not hits:
            plan.rink_problems.append(f"{note}: каток не найден — поставьте заточку в админке")
        else:
            names = ", ".join(f"#{r[0]} {r[1]}" for r in hits)
            plan.rink_problems.append(f"{note}: несколько совпадений ({names}) — поставьте вручную")
    return plan


def _profile_fields(rec: ShopRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "phone": rec.phones[0] if rec.phones else None,
        "website_url": rec.website,
        "short_description": rec.short_description,
        "social_urls": {"instagram": f"https://instagram.com/{rec.instagram}"} if rec.instagram else {},
        "amenities": rec.amenities,
        "status": "published",
    }
    if rec.tickets_url:
        fields["tickets_url"] = rec.tickets_url
    if rec.season is not None:
        fields["season_start_month"], fields["season_end_month"] = rec.season
    if rec.hours is not None:
        fields["opening_hours"] = {"weekly": {d: rec.hours.get(d) for d in WEEKDAY_KEYS}}
    return fields


PARTNER_PHOTO_ATTRIBUTION = "Материалы партнёра: «Магазины и Мастерские — Минск»"


async def _attach_photo(session: AsyncSession, arena_id: int, rec: ShopRecord) -> str | None:
    """Одно фото из файла, если у места ещё нет ни одного. Возвращает причину пропуска."""
    if rec.photo is None:
        return None
    has_media = (
        await session.execute(
            text("SELECT 1 FROM media WHERE owner_type = 'arena' AND owner_id = :id LIMIT 1"), {"id": arena_id}
        )
    ).first()
    if has_media:
        return None
    from src.application.arena_media import upload_arena_media_from_bytes

    try:
        await upload_arena_media_from_bytes(
            session,
            arena_id,
            rec.photo.read_bytes(),
            "image/jpeg" if rec.photo.suffix.lower() in (".jpg", ".jpeg") else "image/png",
            license_key="permitted",
            attribution=PARTNER_PHOTO_ATTRIBUTION,
        )
    except RuntimeError as exc:
        if "S3 not configured" not in str(exc):
            raise
        return "фото не загружены: нет ни S3, ни LOCAL_STORAGE_PATH"
    return None


async def _enrich_existing_place(session: AsyncSession, arena_id: int, rec: ShopRecord) -> None:
    city_id = (await session.execute(text("SELECT city_id FROM arenas WHERE id = :id"), {"id": arena_id})).scalar()
    await ensure_arena_profile(session, arena_id, city_id=int(city_id), name=rec.name)
    current = (
        await session.execute(
            text("SELECT phone, website_url, short_description, amenities, opening_hours, tickets_url, social_urls "
                 "FROM arena_profiles WHERE arena_id = :id"),
            {"id": arena_id},
        )
    ).mappings().first() or {}
    wanted = _profile_fields(rec)
    patch: dict[str, Any] = {}
    for key in ("phone", "website_url", "short_description", "opening_hours", "tickets_url"):
        if wanted.get(key) and not current.get(key):
            patch[key] = wanted[key]
    if rec.season is not None:
        patch["season_start_month"], patch["season_end_month"] = rec.season
    merged = dict(current.get("amenities") or {})
    for key, value in rec.amenities.items():
        merged.setdefault(key, value)
    if merged != dict(current.get("amenities") or {}):
        patch["amenities"] = merged
    socials = dict(current.get("social_urls") or {})
    for key, value in (wanted.get("social_urls") or {}).items():
        socials.setdefault(key, value)
    if socials != dict(current.get("social_urls") or {}):
        patch["social_urls"] = socials
    if patch:
        await apply_admin_arena_profile_patch(session, arena_id, patch)


async def apply_plan(
    session: AsyncSession,
    plan: ImportPlan,
    *,
    geocode: Geocoder | None = None,
) -> dict[str, Any]:
    """Пишет план в одной транзакции вызывающего. Возвращает отчёт для человека."""
    report: dict[str, Any] = {"created": [], "updated": [], "rinks": [], "not_on_map": [], "photos": []}

    async def photo(arena_id: int, rec: ShopRecord) -> None:
        problem = await _attach_photo(session, arena_id, rec)
        if problem and problem not in report["photos"]:
            report["photos"].append(problem)

    async def coords(rec: ShopRecord) -> tuple[float, float] | None:
        if geocode is None or not rec.address:
            return None
        return await geocode(rec.address, plan.city_name)

    for rec in plan.creates:
        point = await coords(rec)
        row = (
            await session.execute(
                text("""
                    INSERT INTO arenas (city_id, name, address, latitude, longitude, is_active,
                                        is_confirmed, venue_type)
                    VALUES (:c, :n, :a, :lat, :lon, true, true, :vt)
                    RETURNING id
                    """),
                {
                    "c": plan.city_id,
                    "n": rec.name,
                    "a": rec.display_address,
                    "lat": point[0] if point else None,
                    "lon": point[1] if point else None,
                    "vt": rec.venue_type,
                },
            )
        ).scalar_one()
        arena_id = int(row)
        await ensure_arena_profile(session, arena_id, city_id=plan.city_id, name=rec.name)
        await apply_admin_arena_profile_patch(session, arena_id, _profile_fields(rec))
        await photo(arena_id, rec)
        report["created"].append(f"#{arena_id} {rec.name}")
        if point is None:
            report["not_on_map"].append(rec.name)

    for arena_id, rec in plan.updates:
        if rec.venue_type != "shop":
            # Каток уже есть (досье, админка): дополняем тем, что есть в файле, и ничего
            # не стираем — пустое поле в файле значит «не знаем», а не «удалить».
            await _enrich_existing_place(session, arena_id, rec)
            await photo(arena_id, rec)
            report["updated"].append(f"#{arena_id} {rec.name} (дополнено)")
            continue
        point = await coords(rec)
        sets = ["address = :a", "is_active = true"]
        params: dict[str, Any] = {"id": arena_id, "a": rec.display_address}
        if point:
            sets += ["latitude = :lat", "longitude = :lon"]
            params.update(lat=point[0], lon=point[1])
        await session.execute(text("UPDATE arenas SET " + ", ".join(sets) + " WHERE id = :id"), params)
        await apply_admin_arena_profile_patch(session, arena_id, _profile_fields(rec))
        await photo(arena_id, rec)
        report["updated"].append(f"#{arena_id} {rec.name}")

    for arena_id, note in plan.rink_updates:
        current = (
            await session.execute(text("SELECT amenities FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
        ).scalar()
        amenities = dict(current or {})
        amenities["skate_sharpening"] = True
        await apply_admin_arena_profile_patch(session, arena_id, {"amenities": amenities})
        report["rinks"].append(f"#{arena_id} {note}: заточка")
    report["rink_problems"] = list(plan.rink_problems)
    return report
