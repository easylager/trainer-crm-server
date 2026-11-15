"""Release comms: parse message files, resolve audiences, broadcast via client/trainer bots."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select, text, union
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import (
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_PROFILE,
    Client,
    ClientFamilyAccessMember,
    Trainer,
)
from src.shared.audit import ACTOR_ADMIN_BOT, audit_log
from src.shared.config import Settings

logger = logging.getLogger(__name__)

Audience = Literal["clients", "trainers"]
TrainerSegment = Literal["all", "pending_profile"]
DELIVERY_LOG_DIR = Path("var/release-comms")
DEFAULT_SEND_DELAY_SEC = 0.05
TRAINER_SEGMENTS: frozenset[str] = frozenset({"all", "pending_profile"})
# Клиенты Беларуси: рассылка про игру «Кто кого». Журнал доставки — в БД, есть отписка и волны.
SEGMENT_BY_CLIENTS = "by_clients"
CLIENT_SEGMENTS: frozenset[str] = frozenset({"all", SEGMENT_BY_CLIENTS})
KK_PROMO_OPTOUT_KIND = "kk_promo"
KK_PROMO_OPTOUT_CALLBACK = "kk_promo:optout"
KK_PROMO_OPTOUT_LABEL = "🔕 Не присылать такое"
KK_PROMO_OPTOUT_TOAST = "Больше не пришлём"


@dataclass(frozen=True)
class ReleaseCommsSpec:
    release_id: str
    audience: Audience
    button_text: str | None
    webapp_path: str | None
    html_body: str
    source_path: Path | None = None
    segment: str | None = None
    # Черновик (draft: true во frontmatter): боевая рассылка отказывается, предпросмотр и dry-run работают.
    draft: bool = False
    # Только by_clients: города аудитории (как в шапке) и кампании, чьих получателей не трогаем.
    cities: tuple[str, ...] | None = None
    exclude_campaigns: tuple[str, ...] | None = None
    # by_clients: не слать тем, у кого уже был chat not found и нет успешной доставки / write-access.
    require_reachable: bool = False


@dataclass
class BroadcastResult:
    release_id: str
    audience: Audience
    dry_run: bool
    total: int
    sent: int
    skipped: int
    failed: int
    errors: list[dict[str, Any]]
    # Только для by_clients: сколько ушло бы в этом запуске и несколько адресатов для проверки.
    would_send: int = 0
    sample_ids: list[int] | None = None
    # Только когда в шапке есть cities/exclude_campaigns: что сделали фильтры (без telegram_id).
    filters: dict[str, Any] | None = None


def parse_release_comms_file(path: Path) -> ReleaseCommsSpec:
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    release_id = (meta.get("release_id") or path.stem).strip()
    audience_raw = (meta.get("audience") or "clients").strip().lower()
    if audience_raw not in ("clients", "trainers"):
        raise ValueError(f"Invalid audience {audience_raw!r} in {path}")
    audience: Audience = audience_raw  # type: ignore[assignment]
    button_text = (meta.get("button_text") or "").strip() or None
    webapp_path = (meta.get("webapp_path") or "").strip() or None
    segment_raw = (meta.get("segment") or "all").strip().lower()
    if audience == "trainers":
        if segment_raw not in TRAINER_SEGMENTS:
            raise ValueError(f"Invalid trainer segment {segment_raw!r} in {path}")
        segment = segment_raw
    else:
        if segment_raw not in CLIENT_SEGMENTS and segment_raw != "":
            raise ValueError(f"Invalid client segment {segment_raw!r} in {path}")
        segment = segment_raw or "all"
    cities = _parse_list_field(meta, "cities", path)
    exclude_campaigns = _parse_list_field(meta, "exclude_campaigns", path)
    by_clients = audience == "clients" and segment == SEGMENT_BY_CLIENTS
    if (cities is not None or exclude_campaigns is not None) and not by_clients:
        raise ValueError(f"cities/exclude_campaigns work only with segment: {SEGMENT_BY_CLIENTS} in {path}")
    rr_raw = (meta.get("require_reachable") or "").strip().lower()
    if rr_raw in ("1", "true", "yes"):
        require_reachable = True
    elif rr_raw in ("0", "false", "no"):
        require_reachable = False
    else:
        # Промо by_clients по умолчанию не жжёт chat not found повторно.
        require_reachable = by_clients
    if require_reachable and not by_clients:
        raise ValueError(f"require_reachable works only with segment: {SEGMENT_BY_CLIENTS} in {path}")
    html_body = body.strip()
    if not html_body:
        raise ValueError(f"Empty message body in {path}")
    return ReleaseCommsSpec(
        release_id=release_id,
        audience=audience,
        button_text=button_text,
        webapp_path=webapp_path,
        html_body=html_body,
        source_path=path,
        segment=segment,
        draft=(meta.get("draft") or "").strip().lower() in ("1", "true", "yes"),
        cities=cities,
        exclude_campaigns=exclude_campaigns,
        require_reachable=require_reachable,
    )


def _parse_list_field(meta: dict[str, str], key: str, path: Path) -> tuple[str, ...] | None:
    """``ключ: a, b, c``. Нет ключа — None (фильтра нет); ключ без значений — ошибка, а не «все»."""
    if key not in meta:
        return None
    items = tuple(dict.fromkeys(" ".join(part.split()) for part in meta[key].split(",") if part.strip()))
    if not items:
        raise ValueError(f"Empty {key!r} in {path}")
    return items


def normalize_city_name(name: str) -> str:
    """Сравнение названий городов: без регистра, «ё» = «е», лишние пробелы не важны."""
    return " ".join(name.split()).casefold().replace("ё", "е")


def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    if not content.startswith("---"):
        return {}, content.strip()
    end = content.find("---", 3)
    if end == -1:
        return {}, content.strip()
    block = content[3:end].strip()
    body = content[end + 3 :].strip()
    meta: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def delivery_log_path(release_id: str, audience: Audience) -> Path:
    safe_id = release_id.replace("/", "_")
    return DELIVERY_LOG_DIR / f"{safe_id}.{audience}.json"


def load_delivery_log(release_id: str, audience: Audience) -> set[int]:
    path = delivery_log_path(release_id, audience)
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {int(x) for x in data.get("sent_telegram_ids", [])}
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Corrupt delivery log %s — treating as empty", path)
        return set()


def save_delivery_log(
    release_id: str,
    audience: Audience,
    sent_ids: set[int],
    failed: list[dict[str, Any]],
) -> None:
    path = delivery_log_path(release_id, audience)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "release_id": release_id,
        "audience": audience,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sent_telegram_ids": sorted(sent_ids),
        "failed": failed,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def fetch_audience_telegram_ids(
    session: AsyncSession,
    audience: Audience,
    *,
    segment: str | None = None,
) -> list[int]:
    if audience == "trainers":
        q = select(Trainer.telegram_id).where(
            Trainer.telegram_id.is_not(None),
            Trainer.status != TRAINER_STATUS_DEACTIVATED,
        )
        if (segment or "all") == "pending_profile":
            q = q.where(Trainer.status == TRAINER_STATUS_PENDING_PROFILE)
        rows = await session.scalars(q)
        return sorted({int(tid) for tid in rows if tid is not None})

    if segment == SEGMENT_BY_CLIENTS:
        return await fetch_by_clients_telegram_ids(session)

    primary = select(Client.telegram_id).where(
        Client.telegram_id.is_not(None),
        Client.is_sandbox.is_(False),
    )
    family = select(ClientFamilyAccessMember.member_telegram_id)
    rows = await session.scalars(union(primary, family))
    return sorted({int(tid) for tid in rows if tid is not None})


# Страна клиента по данным проекта (как в ice_forecast): город из client_sessions, а без него — арена
# последней по смыслу записи; страна города — cities.country. Пул — не-sandbox клиенты, семейный
# доступ и все, кто открывал клиентский бот. Не знаем страну — не рассылаем.
_BY_CLIENTS_SQL = text(
    """
    WITH pool AS (
        SELECT telegram_id FROM clients WHERE telegram_id IS NOT NULL AND is_sandbox = false
        UNION
        SELECT member_telegram_id FROM client_family_access_members
        UNION
        SELECT telegram_id FROM client_sessions
    )
    SELECT p.telegram_id
    FROM pool p
    LEFT JOIN client_sessions cs ON cs.telegram_id = p.telegram_id
    LEFT JOIN cities sc ON sc.id = cs.city_id
    WHERE (
        sc.country = 'BY'
        OR (
            cs.city_id IS NULL
            AND EXISTS (
                SELECT 1
                FROM clients c
                JOIN bookings b ON b.client_id = c.id
                JOIN arenas a ON a.id = b.arena_id
                JOIN cities bc ON bc.id = a.city_id
                WHERE c.telegram_id = p.telegram_id
                  AND c.is_sandbox = false
                  AND bc.country = 'BY'
            )
        )
    )
    -- Демо-клиент тренера (sandbox) рассылку не получает, даже если открывал бот.
    AND NOT (
        EXISTS (SELECT 1 FROM clients sc2 WHERE sc2.telegram_id = p.telegram_id AND sc2.is_sandbox)
        AND NOT EXISTS (SELECT 1 FROM clients rc WHERE rc.telegram_id = p.telegram_id AND NOT rc.is_sandbox)
    )
    AND NOT EXISTS (
        SELECT 1 FROM client_broadcast_optouts o
        WHERE o.telegram_id = p.telegram_id AND o.kind = :kind
    )
    ORDER BY p.telegram_id
    """
)


async def fetch_by_clients_telegram_ids(session: AsyncSession) -> list[int]:
    rows = (await session.execute(_BY_CLIENTS_SQL, {"kind": KK_PROMO_OPTOUT_KIND})).scalars().all()
    return [int(tid) for tid in rows]


# Город человека — тот же вывод, что в _BY_CLIENTS_SQL: город сессии, а без него — город арены записи
# (не-sandbox клиент). Из записей берём самую позднюю в выбранных городах — для счёта по городам.
_CLIENTS_CITY_SQL = text(
    """
    SELECT cs.telegram_id, cs.city_id
    FROM client_sessions cs
    WHERE cs.city_id = ANY(:city_ids)
    UNION ALL
    SELECT telegram_id, city_id FROM (
        SELECT DISTINCT ON (c.telegram_id) c.telegram_id, a.city_id
        FROM clients c
        JOIN bookings b ON b.client_id = c.id
        JOIN arenas a ON a.id = b.arena_id
        WHERE c.telegram_id IS NOT NULL
          AND c.is_sandbox = false
          AND a.city_id = ANY(:city_ids)
          AND NOT EXISTS (
              SELECT 1 FROM client_sessions cs2
              WHERE cs2.telegram_id = c.telegram_id AND cs2.city_id IS NOT NULL
          )
        ORDER BY c.telegram_id, b.id DESC
    ) by_booking
    """
)


async def _resolve_by_city_ids(session: AsyncSession, spec: ReleaseCommsSpec) -> dict[int, str]:
    """Названия из шапки → id белорусских городов. Неизвестное название — ошибка, не тихий пропуск."""
    rows = (await session.execute(text("SELECT id, name FROM cities WHERE country = 'BY'"))).all()
    by_name: dict[str, list[tuple[int, str]]] = {}
    for city_id, name in rows:
        by_name.setdefault(normalize_city_name(name), []).append((int(city_id), name))
    resolved: dict[int, str] = {}
    unknown: list[str] = []
    for wanted in spec.cities or ():
        found = by_name.get(normalize_city_name(wanted))
        if not found:
            unknown.append(wanted)
            continue
        for city_id, _name in found:
            resolved[city_id] = wanted
    if unknown:
        where = spec.source_path or spec.release_id
        raise ValueError(f"Unknown BY city in cities: {', '.join(unknown)} ({where})")
    return resolved


async def _filter_reachable_clients(
    session: AsyncSession, audience: list[int]
) -> tuple[list[int], int]:
    """Оставляем тех, кому бот уже доставлял, или есть write-access, или ещё не было chat not found."""
    if not audience:
        return [], 0
    sent = {
        int(tid)
        for tid in await session.scalars(
            text(
                "SELECT DISTINCT telegram_id FROM client_broadcast_log "
                "WHERE status = 'sent' AND telegram_id = ANY(:ids)"
            ),
            {"ids": audience},
        )
    }
    cnf = {
        int(tid)
        for tid in await session.scalars(
            text(
                "SELECT DISTINCT telegram_id FROM client_broadcast_log "
                "WHERE status = 'failed' AND telegram_id = ANY(:ids) "
                "AND error ILIKE '%chat not found%'"
            ),
            {"ids": audience},
        )
    }
    from src.application.catalog_consumer_events import telegram_actor_hash

    hash_of = {tid: telegram_actor_hash(tid) for tid in audience}
    hashes = [h for h in hash_of.values() if h]
    wa_hashes: set[str] = set()
    if hashes:
        wa_hashes = {
            str(h)
            for h in await session.scalars(
                text(
                    "SELECT DISTINCT actor_id FROM platform_audit_events "
                    "WHERE event_type IN ('write_access_granted', 'write_access_already') "
                    "AND actor_id = ANY(:hashes)"
                ),
                {"hashes": hashes},
            )
            if h
        }
    wa_ok = {tid for tid, h in hash_of.items() if h and h in wa_hashes}
    kept = [tid for tid in audience if tid in sent or tid in wa_ok or tid not in cnf]
    return kept, len(audience) - len(kept)


async def fetch_filtered_by_clients(
    session: AsyncSession, spec: ReleaseCommsSpec
) -> tuple[list[int], dict[str, Any] | None]:
    """Аудитория by_clients с фильтрами шапки. Без фильтров — прежний список и None stats."""
    has_filters = (
        spec.cities is not None or spec.exclude_campaigns is not None or spec.require_reachable
    )
    if not has_filters:
        return await fetch_by_clients_telegram_ids(session), None
    city_names = await _resolve_by_city_ids(session, spec) if spec.cities is not None else None
    base = await fetch_by_clients_telegram_ids(session)
    stats: dict[str, Any] = {"by_clients_total": len(base)}
    audience = base
    if city_names is not None:
        rows = (await session.execute(_CLIENTS_CITY_SQL, {"city_ids": list(city_names)})).all()
        city_of = {int(tid): city_names[int(cid)] for tid, cid in rows}
        audience = [tid for tid in audience if tid in city_of]
        per_city = dict.fromkeys(spec.cities or (), 0)
        for tid in audience:
            per_city[city_of[tid]] += 1
        stats["cities"] = per_city
    if spec.exclude_campaigns is not None:
        rows = await session.scalars(
            text("SELECT DISTINCT telegram_id FROM client_broadcast_log WHERE campaign_key = ANY(:keys)"),
            {"keys": list(spec.exclude_campaigns)},
        )
        excluded = {int(tid) for tid in rows}
        kept = [tid for tid in audience if tid not in excluded]
        stats["excluded_by_campaigns"] = len(audience) - len(kept)
        audience = kept
    if spec.require_reachable:
        audience, dropped = await _filter_reachable_clients(session, audience)
        stats["excluded_unreachable"] = dropped
    stats["after_filters"] = len(audience)
    return audience, stats


async def record_kk_promo_optout(session: AsyncSession, telegram_id: int) -> None:
    await session.execute(
        text(
            """
            INSERT INTO client_broadcast_optouts (telegram_id, kind)
            VALUES (:tid, :kind)
            ON CONFLICT (telegram_id, kind) DO NOTHING
            """
        ),
        {"tid": telegram_id, "kind": KK_PROMO_OPTOUT_KIND},
    )


def markup_without_kk_optout(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """Сообщение после отписки: кнопка «Не присылать такое» уходит, остальные остаются."""
    if markup is None:
        return None
    rows = [
        row
        for row in markup.inline_keyboard
        if not any(button.callback_data == KK_PROMO_OPTOUT_CALLBACK for button in row)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def build_webapp_markup(settings: Settings, spec: ReleaseCommsSpec) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    base = (settings.webapp_base_url or "").rstrip("/")
    if spec.button_text and spec.webapp_path and base.lower().startswith("https://"):
        path = spec.webapp_path if spec.webapp_path.startswith("/") else f"/{spec.webapp_path}"
        rows.append([InlineKeyboardButton(text=spec.button_text, web_app=WebAppInfo(url=f"{base}{path}"))])
    if spec.audience == "clients" and spec.segment == SEGMENT_BY_CLIENTS:
        rows.append([InlineKeyboardButton(text=KK_PROMO_OPTOUT_LABEL, callback_data=KK_PROMO_OPTOUT_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def wave_targets(
    release_id: str,
    audience: list[int],
    already: set[int],
    *,
    percent: float | None = None,
    limit: int | None = None,
) -> list[int]:
    """Кому слать в этом запуске. Волна — доля аудитории в стабильном «случайном» порядке этой рассылки:
    ``--percent 10`` берёт первые 10%, потом ``--percent 50`` — первые 50% (досылает ещё 40%), журнал не даёт
    повторов. ``limit`` режет число новых отправок за запуск."""
    ordered = sorted(audience, key=lambda tid: hashlib.md5(f"{release_id}:{tid}".encode()).hexdigest())  # noqa: S324
    if percent is not None:
        ordered = ordered[: math.ceil(len(ordered) * percent / 100)]
    pending = [tid for tid in ordered if tid not in already]
    return pending[: max(0, limit)] if limit is not None else pending


async def _logged_ids(session: AsyncSession, campaign_key: str) -> set[int]:
    rows = await session.scalars(
        text("SELECT telegram_id FROM client_broadcast_log WHERE campaign_key = :key"), {"key": campaign_key}
    )
    return {int(tid) for tid in rows}


async def _write_log(
    session: AsyncSession, *, telegram_id: int, campaign_key: str, status: str, error: str | None
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO client_broadcast_log (telegram_id, campaign_key, status, error)
            VALUES (:tid, :key, :status, :error)
            ON CONFLICT (telegram_id, campaign_key) DO NOTHING
            """
        ),
        {"tid": telegram_id, "key": campaign_key, "status": status, "error": error[:500] if error else None},
    )
    # Сразу в журнал: упавший на середине запуск не пришлёт второе сообщение тем, кто уже получил.
    await session.commit()


async def _broadcast_by_clients(
    session: AsyncSession,
    spec: ReleaseCommsSpec,
    *,
    settings: Settings,
    bot: Any | None,
    dry_run: bool,
    chat_id: int | None,
    force: bool,
    percent: float | None,
    limit: int | None,
    send_delay_sec: float,
    markup: InlineKeyboardMarkup | None,
) -> BroadcastResult:
    """Рассылка клиентам Беларуси: журнал доставки в client_broadcast_log (campaign_key = release_id)."""
    filters: dict[str, Any] | None = None
    if chat_id is not None:
        # Предпросмотр одному человеку: журнал не трогаем, аудиторию не считаем.
        audience, already, to_send = [chat_id], set(), [chat_id]
    else:
        audience, filters = await fetch_filtered_by_clients(session, spec)
        already = set() if force else await _logged_ids(session, spec.release_id)
        to_send = wave_targets(spec.release_id, audience, already, percent=percent, limit=limit)
    result = BroadcastResult(
        release_id=spec.release_id,
        audience=spec.audience,
        dry_run=dry_run,
        total=len(audience),
        sent=0,
        skipped=len(already & set(audience)),
        failed=0,
        errors=[],
        would_send=len(to_send),
        sample_ids=to_send[:5],
        filters=filters,
    )
    if dry_run:
        return result

    own_bot = bot is None
    bot = bot or _bot_for_audience(settings, spec.audience)

    async def deliver(tid: int) -> None:
        await bot.send_message(chat_id=tid, text=spec.html_body, reply_markup=markup)

    try:
        for tid in to_send:
            status, error = "sent", None
            try:
                try:
                    await deliver(tid)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(float(exc.retry_after or 1) + 0.5)
                    await deliver(tid)
                result.sent += 1
            except TelegramForbiddenError:
                status, error = "failed", "forbidden"
            except Exception as exc:  # noqa: BLE001
                status, error = "failed", str(exc)[:200]
                logger.exception("release_comms send failed telegram_id=%s", tid)
            if status == "failed":
                result.failed += 1
                result.errors.append({"telegram_id": tid, "error": error})
            if chat_id is None:
                await _write_log(
                    session, telegram_id=tid, campaign_key=spec.release_id, status=status, error=error
                )
            if send_delay_sec > 0:
                await asyncio.sleep(send_delay_sec)
    finally:
        if own_bot:
            await bot.session.close()

    audit_log(
        "release_comms.batch_done",
        ACTOR_ADMIN_BOT,
        "broadcast_script",
        {
            "release_id": spec.release_id,
            "audience": spec.audience,
            "segment": spec.segment,
            "sent": result.sent,
            "failed": result.failed,
            "skipped": result.skipped,
        },
    )
    return result


def _bot_for_audience(settings: Settings, audience: Audience) -> Bot:
    token = (
        settings.telegram_bot_token_client
        if audience == "clients"
        else settings.telegram_bot_token_trainer
    )
    if not token:
        raise RuntimeError(f"Missing bot token for audience={audience}")
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def broadcast_release_comms(
    session: AsyncSession,
    spec: ReleaseCommsSpec,
    *,
    settings: Settings | None = None,
    dry_run: bool = False,
    chat_id: int | None = None,
    force: bool = False,
    limit: int | None = None,
    send_delay_sec: float = DEFAULT_SEND_DELAY_SEC,
    percent: float | None = None,
    bot: Any | None = None,
) -> BroadcastResult:
    settings = settings or Settings()
    by_clients = spec.audience == "clients" and spec.segment == SEGMENT_BY_CLIENTS
    if spec.draft and not dry_run and chat_id is None:
        raise ValueError(f"{spec.release_id}: draft: true — рассылка не отправляется без апрува (уберите draft)")
    if percent is not None and not by_clients:
        raise ValueError("percent is only supported for segment by_clients")
    if percent is not None and not 0 < percent <= 100:
        raise ValueError("percent must be in (0, 100]")
    if by_clients:
        return await _broadcast_by_clients(
            session,
            spec,
            settings=settings,
            bot=bot,
            dry_run=dry_run,
            chat_id=chat_id,
            force=force,
            percent=percent,
            limit=limit,
            send_delay_sec=send_delay_sec,
            markup=build_webapp_markup(settings, spec),
        )
    already_sent = set() if (force or chat_id is not None) else load_delivery_log(spec.release_id, spec.audience)
    markup = build_webapp_markup(settings, spec)

    if chat_id is not None:
        targets = [chat_id]
    else:
        targets = await fetch_audience_telegram_ids(
            session, spec.audience, segment=spec.segment
        )
        if limit is not None:
            targets = targets[: max(0, limit)]

    to_send = [tid for tid in targets if tid not in already_sent]
    skipped = len(targets) - len(to_send)

    result = BroadcastResult(
        release_id=spec.release_id,
        audience=spec.audience,
        dry_run=dry_run,
        total=len(targets),
        sent=0,
        skipped=skipped,
        failed=0,
        errors=[],
    )

    if dry_run:
        logger.info(
            "release_comms dry-run release_id=%s audience=%s total=%s would_send=%s skipped=%s",
            spec.release_id,
            spec.audience,
            result.total,
            len(to_send),
            skipped,
        )
        if to_send[:5]:
            logger.info("sample telegram_ids: %s", to_send[:5])
        return result

    bot = _bot_for_audience(settings, spec.audience)
    sent_ids = set(already_sent)
    try:
        for tid in to_send:
            try:
                await bot.send_message(
                    chat_id=tid,
                    text=spec.html_body,
                    reply_markup=markup,
                )
                sent_ids.add(tid)
                result.sent += 1
                audit_log(
                    "release_comms.sent",
                    ACTOR_ADMIN_BOT,
                    "broadcast_script",
                    {
                        "release_id": spec.release_id,
                        "audience": spec.audience,
                        "telegram_id": tid,
                    },
                )
            except TelegramRetryAfter as exc:
                wait = float(exc.retry_after or 1) + 0.5
                logger.warning("rate limited, sleeping %.1fs", wait)
                await asyncio.sleep(wait)
                await bot.send_message(
                    chat_id=tid,
                    text=spec.html_body,
                    reply_markup=markup,
                )
                sent_ids.add(tid)
                result.sent += 1
            except TelegramForbiddenError:
                result.failed += 1
                result.errors.append({"telegram_id": tid, "error": "forbidden"})
            except Exception as exc:
                result.failed += 1
                result.errors.append({"telegram_id": tid, "error": str(exc)[:200]})
                logger.exception("release_comms send failed telegram_id=%s", tid)
            if send_delay_sec > 0:
                await asyncio.sleep(send_delay_sec)
    finally:
        await bot.session.close()

    if chat_id is None:
        save_delivery_log(spec.release_id, spec.audience, sent_ids, result.errors)

    audit_log(
        "release_comms.batch_done",
        ACTOR_ADMIN_BOT,
        "broadcast_script",
        {
            "release_id": spec.release_id,
            "audience": spec.audience,
            "sent": result.sent,
            "failed": result.failed,
            "skipped": result.skipped,
        },
    )
    return result
