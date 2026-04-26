"""
Infrastructure: trainer persistence. All SQL here; no business rules.
"""
import json
from typing import Any
from datetime import date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.price_tier_kind import (
    PRICE_TIER_ADULT,
    normalize_price_tier_kind,
    price_tier_label_ru,
    price_tier_sort_key,
    sql_order_case_tier_kind,
)
from src.shared.trainer_status import normalize_trainer_status_value

# Legacy display; DB column `label` kept for compatibility; tier_kind is source of truth.
TRAINER_SERVICE_DEFAULT_TIER_LABEL = "Основной"

# set_trainer_services: (service_id, tiers) | +description | +group_price_cents | +client_notice (optional).
TrainerServiceWriteEntry = (
    tuple[int, list[tuple[str, int]]]
    | tuple[int, list[tuple[str, int]], str | None]
    | tuple[int, list[tuple[str, int]], str | None, int | None]
    | tuple[int, list[tuple[str, int]], str | None, int | None, str | None]
)


def _normalize_trainer_service_write_entry(
    entry: TrainerServiceWriteEntry,
) -> tuple[int, list[tuple[str, int]], str | None, int | None, str | None]:
    if len(entry) == 2:
        sid, tiers = entry
        return sid, tiers, None, None, None
    if len(entry) == 3:
        sid, tiers, desc = entry
        return sid, tiers, desc, None, None
    if len(entry) == 4:
        sid, tiers, desc, gpc = entry
        return sid, tiers, desc, gpc, None
    sid, tiers, desc, gpc, notice = entry
    return sid, tiers, desc, gpc, notice


def _sql_public_catalog_education_predicate(table_alias: str = "e") -> str:
    """
    Which trainer_education rows appear in the public catalog / client APIs.

    Includes pending_moderation (trainer already active in catalog; details matter before admin
    ticks education). Includes approved snapshots unless a pending revision supersedes that row.
    """
    t = table_alias
    return f"""(
  {t}.moderation_status = 'pending_moderation'
  OR (
    {t}.moderation_status = 'approved'
    AND {t}.approved_snapshot = true
    AND NOT EXISTS (
      SELECT 1 FROM trainer_education n
      WHERE n.supersedes_id = {t}.id
        AND n.trainer_id = {t}.trainer_id
        AND n.moderation_status = 'pending_moderation'
    )
  )
)"""


def _normalize_education_document_photos(raw: Any) -> list[dict[str, str | None]]:
    """Parse/clean JSONB education photos payload to stable API list."""
    if raw is None:
        return []
    payload = raw
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(payload, list):
        return []
    out: list[dict[str, str | None]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        file_key = (item.get("file_key") or "").strip()
        file_key_list = (item.get("file_key_list") or "").strip() or None
        if not file_key:
            continue
        out.append({"file_key": file_key, "file_key_list": file_key_list})
    return out


class TrainerRepository:
    """Trainer aggregate persistence: trainers, profiles, photos, services. Raw SQL only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_trainer(self) -> int:
        """Insert trainer row; returns new id."""
        r = await self._session.execute(text("INSERT INTO trainers (created_at) VALUES (now()) RETURNING id"))
        (tid,) = r.fetchone()
        return tid

    async def create_profile(
        self,
        trainer_id: int,
        *,
        first_name: str,
        last_name: str,
        age: int,
        city_id: int | None = None,
        experience_years: int | None = None,
        description: str | None = None,
        phone: str | None = None,
        contacts: str | None = None,
        education: str | None = None,
        session_duration_minutes: int | None = None,
    ) -> None:
        """Insert trainer profile (one per trainer)."""
        dur = 45 if session_duration_minutes is None else session_duration_minutes
        await self._session.execute(
            text("""
                INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id, experience_years, description, phone, contacts, education, session_duration_minutes)
                VALUES (:tid, :fn, :ln, :age, :city_id, :exp, :desc, :phone, :contacts, :edu, :dur)
            """),
            {
                "tid": trainer_id,
                "fn": first_name,
                "ln": last_name,
                "age": age,
                "city_id": city_id,
                "exp": experience_years,
                "desc": description,
                "phone": phone,
                "contacts": contacts,
                "edu": education,
                "dur": dur,
            },
        )

    async def set_trainer_services(
        self,
        trainer_id: int,
        entries: list[TrainerServiceWriteEntry],
    ) -> None:
        """
        Replace trainer's services. Each entry is (service_id, tiers) or (service_id, tiers, description) with tiers
        (tier_kind, price_cents) — up to one row per fixed tariff code (see price_tier_kind.py).
        Empty tiers => trainer_services with price_cents NULL.
        Anchor price on trainer_services: adult tier if present, else cheapest tier by display order.
        group_price_cents: optional per-seat override for capacity>1 slots; NULL => use anchor (price_cents).
        """
        await self._session.execute(text("DELETE FROM trainer_services WHERE trainer_id = :tid"), {"tid": trainer_id})

        def _anchor_cents(sorted_tiers: list[tuple[str, int]]) -> int | None:
            if not sorted_tiers:
                return None
            by_k = dict(sorted_tiers)
            if PRICE_TIER_ADULT in by_k:
                return by_k[PRICE_TIER_ADULT]
            return sorted_tiers[0][1]

        for raw in entries:
            sid, tiers, svc_description, group_price_cents, client_notice = _normalize_trainer_service_write_entry(raw)
            merged: dict[str, int] = {}
            for tier_kind, pc in tiers:
                tk = normalize_price_tier_kind(tier_kind)
                if tk is None:
                    continue
                merged[tk] = int(pc)
            clean_tiers = sorted(merged.items(), key=lambda x: price_tier_sort_key(x[0]))
            anchor = _anchor_cents(clean_tiers)
            await self._session.execute(
                text("""
                    INSERT INTO trainer_services (trainer_id, service_id, price_cents, description, group_price_cents, client_notice)
                    VALUES (:tid, :sid, :price_cents, :descr, :group_pc, :client_notice)
                """),
                {
                    "tid": trainer_id,
                    "sid": sid,
                    "price_cents": anchor,
                    "descr": svc_description,
                    "group_pc": group_price_cents,
                    "client_notice": client_notice,
                },
            )
            for order, (tk, pc) in enumerate(clean_tiers):
                lbl = (price_tier_label_ru(tk) or TRAINER_SERVICE_DEFAULT_TIER_LABEL)[:64]
                await self._session.execute(
                    text("""
                        INSERT INTO trainer_service_price_variants (
                            trainer_id, service_id, label, price_cents, sort_order, tier_kind
                        )
                        VALUES (:tid, :sid, :lbl, :pc, :ord, :tk)
                    """),
                    {"tid": trainer_id, "sid": sid, "lbl": lbl, "pc": pc, "ord": order, "tk": tk},
                )

    async def set_trainer_arenas(self, trainer_id: int, arena_ids: list[int]) -> None:
        """Replace trainer's arenas with given ids."""
        await self._session.execute(text("DELETE FROM trainer_arenas WHERE trainer_id = :tid"), {"tid": trainer_id})
        for aid in arena_ids:
            await self._session.execute(
                text("""
                    INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)
                    ON CONFLICT (trainer_id, arena_id) DO NOTHING
                """),
                {"tid": trainer_id, "aid": aid},
            )

    async def list_trainer_arena_ids(self, trainer_id: int) -> list[int]:
        r = await self._session.execute(
            text("SELECT arena_id FROM trainer_arenas WHERE trainer_id = :id ORDER BY arena_id"),
            {"id": trainer_id},
        )
        return [row[0] for row in r.fetchall()]

    async def set_trainer_primary_arena(self, trainer_id: int, arena_id: int | None) -> None:
        await self._session.execute(
            text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
            {"tid": trainer_id, "aid": arena_id},
        )

    async def set_schedule_grid_step_minutes(self, trainer_id: int, step_minutes: int) -> None:
        await self._session.execute(
            text("UPDATE trainers SET schedule_grid_step_minutes = :step WHERE id = :tid"),
            {"tid": trainer_id, "step": step_minutes},
        )

    async def set_push_notification_window(self, trainer_id: int, start_h: int, end_h: int) -> None:
        await self._session.execute(
            text(
                "UPDATE trainers SET push_notification_start_hour = :s, push_notification_end_hour = :e "
                "WHERE id = :tid"
            ),
            {"tid": trainer_id, "s": start_h, "e": end_h},
        )

    async def clear_push_notification_window(self, trainer_id: int) -> None:
        await self._session.execute(
            text(
                "UPDATE trainers SET push_notification_start_hour = NULL, push_notification_end_hour = NULL "
                "WHERE id = :tid"
            ),
            {"tid": trainer_id},
        )

    async def set_digest_settings(
        self, trainer_id: int, *, digest_enabled: bool, digest_send_time: time | None
    ) -> None:
        """Morning/weekly digest toggle + fixed Europe/Minsk send time; NULL = auto morning slot (~8:00), not tied to evening sessions."""
        await self._session.execute(
            text(
                "UPDATE trainers SET digest_enabled = :en, digest_send_time = :st WHERE id = :tid"
            ),
            {"tid": trainer_id, "en": digest_enabled, "st": digest_send_time},
        )

    async def reconcile_primary_arena(self, trainer_id: int) -> None:
        """If primary is missing or not in trainer_arenas, set to MIN(arena_id). Clears primary if no arenas."""
        r = await self._session.execute(
            text("SELECT primary_arena_id FROM trainers WHERE id = :id"),
            {"id": trainer_id},
        )
        row = r.fetchone()
        current = row[0] if row else None
        aids = await self.list_trainer_arena_ids(trainer_id)
        if not aids:
            if current is not None:
                await self.set_trainer_primary_arena(trainer_id, None)
            return
        if current is None or current not in aids:
            await self.set_trainer_primary_arena(trainer_id, min(aids))

    async def get_by_id(self, trainer_id: int) -> dict[str, Any] | None:
        """Load trainer with profile, photos, service_ids; None if not found."""
        r = await self._session.execute(
            text(
                "SELECT id, telegram_id, status, created_at, moderation_feedback, moderation_submitted_at, "
                "profile_pending, photo_pending, primary_arena_id, schedule_grid_step_minutes, is_catalog_visible, "
                "push_notification_start_hour, push_notification_end_hour, "
                "digest_enabled, digest_send_time "
                "FROM trainers WHERE id = :id"
            ),
            {"id": trainer_id},
        )
        row = r.fetchone()
        if not row:
            return None
        raw_pending = row[6]
        if raw_pending is not None and not isinstance(raw_pending, dict):
            try:
                raw_pending = json.loads(raw_pending) if isinstance(raw_pending, str) else raw_pending
            except (json.JSONDecodeError, TypeError):
                raw_pending = None
        raw_photo_pend = row[7]
        if raw_photo_pend is not None and not isinstance(raw_photo_pend, dict):
            try:
                raw_photo_pend = json.loads(raw_photo_pend) if isinstance(raw_photo_pend, str) else raw_photo_pend
            except (json.JSONDecodeError, TypeError):
                raw_photo_pend = None
        def _time_to_api_hhmm(t: object | None) -> str | None:
            if t is None:
                return None
            if isinstance(t, time):
                return t.strftime("%H:%M")
            return None

        out: dict[str, Any] = {
            "id": row[0],
            "telegram_id": row[1],
            "status": normalize_trainer_status_value(row[2]),
            "created_at": str(row[3]) if row[3] else None,
            "moderation_feedback": row[4],
            "moderation_submitted_at": row[5],
            "profile_pending": raw_pending if isinstance(raw_pending, dict) else None,
            "photo_pending": raw_photo_pend if isinstance(raw_photo_pend, dict) else None,
            "primary_arena_id": row[8] if len(row) > 8 else None,
            "schedule_grid_step_minutes": int(row[9]) if len(row) > 9 and row[9] is not None else 15,
            "is_catalog_visible": bool(row[10]) if len(row) > 10 and row[10] is not None else True,
            "push_notification_start_hour": int(row[11]) if len(row) > 11 and row[11] is not None else None,
            "push_notification_end_hour": int(row[12]) if len(row) > 12 and row[12] is not None else None,
            "digest_enabled": bool(row[13]) if len(row) > 13 and row[13] is not None else True,
            "digest_send_time": _time_to_api_hhmm(row[14]) if len(row) > 14 else None,
        }
        rp = await self._session.execute(
            text(
                "SELECT first_name, last_name, age, city_id, experience_years, description, phone, contacts, education, rating_avg, rating_count, session_duration_minutes, min_hours_before_booking, COALESCE(group_classes_enabled, false) FROM trainer_profiles WHERE trainer_id = :id"
            ),
            {"id": trainer_id},
        )
        prof = rp.fetchone()
        out["profile"] = (
            {
                "first_name": prof[0], "last_name": prof[1], "age": prof[2], "city_id": prof[3],
                "experience_years": prof[4], "description": prof[5], "phone": prof[6], "contacts": prof[7], "education": prof[8],
                "rating_avg": float(prof[9]) if prof[9] is not None else None,
                "rating_count": prof[10] or 0,
                # Raw DB values so moderation completeness can require explicit session/hours (no silent 45/3).
                "session_duration_minutes": prof[11],
                "min_hours_before_booking": int(prof[12]) if prof[12] is not None else None,
                "group_classes_enabled": bool(prof[13]) if len(prof) > 13 and prof[13] is not None else False,
            }
            if prof
            else None
        )
        rph = await self._session.execute(
            text("SELECT file_key, file_key_list, sort_order FROM trainer_photos WHERE trainer_id = :id ORDER BY sort_order"),
            {"id": trainer_id},
        )
        out["photos"] = [{"file_key": r[0], "file_key_list": r[1], "sort_order": r[2]} for r in rph.fetchall()]
        rsv = await self._session.execute(
            text(
                "SELECT service_id, price_cents, description, group_price_cents, client_notice FROM trainer_services WHERE trainer_id = :id ORDER BY service_id"
            ),
            {"id": trainer_id},
        )
        service_rows = rsv.fetchall()
        out["service_ids"] = [r[0] for r in service_rows]
        tiers_by_sid: dict[int, list[dict[str, Any]]] = {}
        if service_rows:
            rv = await self._session.execute(
                text(
                    f"""
                    SELECT service_id, id, label, price_cents, sort_order, tier_kind
                    FROM trainer_service_price_variants
                    WHERE trainer_id = :tid
                    ORDER BY service_id,
                      {sql_order_case_tier_kind("tier_kind")},
                      sort_order
                    """
                ),
                {"tid": trainer_id},
            )
            for row in rv.fetchall():
                sid_v = int(row[0])
                vid = int(row[1])
                lab = row[2]
                pc = int(row[3])
                so = int(row[4])
                tk = normalize_price_tier_kind(row[5]) or PRICE_TIER_ADULT
                tiers_by_sid.setdefault(sid_v, []).append(
                    {
                        "id": vid,
                        "tier_kind": tk,
                        "label": lab or price_tier_label_ru(tk) or TRAINER_SERVICE_DEFAULT_TIER_LABEL,
                        "price_cents": pc,
                        "price_byn": round(pc / 100, 2),
                        "sort_order": so,
                    }
                )
        if service_rows:
            s_placeholders = ", ".join(f":s{i}" for i in range(len(out["service_ids"])))
            s_params = {f"s{i}": r[0] for i, r in enumerate(service_rows)}
            r_sn = await self._session.execute(
                text(f"SELECT id, name FROM services WHERE id IN ({s_placeholders})"),
                s_params,
            )
            name_by_sid = {r[0]: (r[1] or "") for r in r_sn.fetchall()}
            out["services"] = []
            for r in service_rows:
                sid = r[0]
                tiers = tiers_by_sid.get(sid, [])
                pc_row = r[1]
                svc_desc: str | None = None
                if len(r) > 2 and r[2] is not None:
                    s = str(r[2]).strip()
                    if s:
                        svc_desc = s
                gpc_row = int(r[3]) if len(r) > 3 and r[3] is not None else None
                notice_out: str | None = None
                if len(r) > 4 and r[4] is not None:
                    ns = str(r[4]).strip()
                    if ns:
                        notice_out = ns
                if tiers:
                    prices = [t["price_cents"] for t in tiers]
                    p_min, p_max = min(prices), max(prices)
                    price_byn_min = round(p_min / 100, 2)
                    price_byn_max = round(p_max / 100, 2)
                else:
                    price_byn_min = price_byn_max = (round(pc_row / 100, 2) if pc_row is not None else None)
                svc_dict: dict[str, Any] = {
                    "service_id": sid,
                    "service_name": name_by_sid.get(sid, "—"),
                    "price_cents": pc_row,
                    "price_byn": round(pc_row / 100, 2) if pc_row is not None else None,
                    "price_byn_min": price_byn_min,
                    "price_byn_max": price_byn_max,
                    "price_tiers": tiers,
                    "description": svc_desc,
                    "group_price_cents": gpc_row,
                    "group_price_byn": round(gpc_row / 100, 2) if gpc_row is not None else None,
                    "client_notice": notice_out,
                }
                out["services"].append(svc_dict)
        else:
            out["services"] = []
        rec = await self._session.execute(
            text("SELECT COUNT(*) FROM trainer_education WHERE trainer_id = :id"),
            {"id": trainer_id},
        )
        out["education_entries_count"] = int(rec.scalar() or 0)

        rar = await self._session.execute(text("SELECT arena_id FROM trainer_arenas WHERE trainer_id = :id ORDER BY arena_id"), {"id": trainer_id})
        out["arena_ids"] = [r[0] for r in rar.fetchall()]
        if out["arena_ids"]:
            placeholders_ar = ", ".join(f":a{i}" for i in range(len(out["arena_ids"])))
            params_ar = {f"a{i}": aid for i, aid in enumerate(out["arena_ids"])}
            r_an = await self._session.execute(
                text(f"SELECT id, name FROM arenas WHERE id IN ({placeholders_ar})"),
                params_ar,
            )
            name_by_id = {r[0]: (r[1] or "") for r in r_an.fetchall()}
            out["arena_names"] = [name_by_id.get(aid, "—") for aid in out["arena_ids"]]
        else:
            out["arena_names"] = []
        r_has_pass = await self._session.execute(
            text("SELECT 1 FROM trainer_pass_products WHERE trainer_id = :id AND is_active = true LIMIT 1"),
            {"id": trainer_id},
        )
        r_has_cert = await self._session.execute(
            text("SELECT 1 FROM trainer_certificate_products WHERE trainer_id = :id AND is_active = true LIMIT 1"),
            {"id": trainer_id},
        )
        out["has_pass_products"] = r_has_pass.fetchone() is not None
        out["has_certificate_products"] = r_has_cert.fetchone() is not None
        return out

    async def list_trainer_ids_for_moderation_queue(self) -> list[int]:
        """pending_profile trainers + active trainers with text or photo pending revision."""
        r = await self._session.execute(
            text(
                """
                SELECT id FROM trainers
                WHERE status = 'pending_profile'
                   OR (
                        status = 'active'
                        AND (
                            (
                                profile_pending IS NOT NULL
                                AND jsonb_typeof(profile_pending) = 'object'
                                AND profile_pending <> '{}'::jsonb
                            )
                            OR (
                                photo_pending IS NOT NULL
                                AND jsonb_typeof(photo_pending) = 'object'
                                AND COALESCE(photo_pending->>'file_key', '') <> ''
                            )
                        )
                   )
                ORDER BY id
                """
            )
        )
        return [int(row[0]) for row in r.fetchall()]

    async def exists(self, trainer_id: int) -> bool:
        """True if trainer exists."""
        r = await self._session.execute(text("SELECT 1 FROM trainers WHERE id = :id"), {"id": trainer_id})
        return r.fetchone() is not None

    async def ensure_trainer_profile_row(self, trainer_id: int) -> None:
        """
        Guarantee a trainer_profiles row (PK = trainer_id). Trainers created only via trainers INSERT
        (e.g. admin welcome link) have no profile row until first PATCH — plain UPDATE would affect 0 rows.
        """
        await self._session.execute(
            text("""
                INSERT INTO trainer_profiles (trainer_id)
                VALUES (:tid)
                ON CONFLICT (trainer_id) DO NOTHING
            """),
            {"tid": trainer_id},
        )

    async def update_profile(
        self,
        trainer_id: int,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        age: int | None = None,
        city_id: int | None = None,
        experience_years: int | None = None,
        description: str | None = None,
        phone: str | None = None,
        contacts: str | None = None,
        education: str | None = None,
        session_duration_minutes: int | None = None,
        min_hours_before_booking: int | None = None,
        group_classes_enabled: bool | None = None,
    ) -> None:
        """Partial update of profile; only non-None fields are set."""
        updates: list[str] = []
        params: dict[str, Any] = {"id": trainer_id}
        if first_name is not None: updates.append("first_name = :fn"); params["fn"] = first_name
        if last_name is not None: updates.append("last_name = :ln"); params["ln"] = last_name
        if age is not None: updates.append("age = :age"); params["age"] = age
        if city_id is not None: updates.append("city_id = :city_id"); params["city_id"] = city_id
        if experience_years is not None: updates.append("experience_years = :exp"); params["exp"] = experience_years
        if description is not None: updates.append("description = :desc"); params["desc"] = description
        if phone is not None: updates.append("phone = :phone"); params["phone"] = phone
        if contacts is not None: updates.append("contacts = :contacts"); params["contacts"] = contacts
        if education is not None: updates.append("education = :edu"); params["edu"] = education
        if session_duration_minutes is not None: updates.append("session_duration_minutes = :dur"); params["dur"] = session_duration_minutes
        if min_hours_before_booking is not None: updates.append("min_hours_before_booking = :mhb"); params["mhb"] = min_hours_before_booking
        if group_classes_enabled is not None:
            updates.append("group_classes_enabled = :gce")
            params["gce"] = bool(group_classes_enabled)
        if not updates:
            return
        await self._session.execute(
            text("UPDATE trainer_profiles SET " + ", ".join(updates) + ", updated_at = now() WHERE trainer_id = :id"),
            params,
        )

    async def list_education_entries(
        self,
        trainer_id: int,
        *,
        public_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List trainer education entries; public_only returns catalog-visible rows (see _sql_public_catalog_education_predicate)."""
        params: dict[str, Any] = {"tid": trainer_id}
        if public_only:
            vis = _sql_public_catalog_education_predicate("e")
            q = f"""
                SELECT e.id, e.education_type, e.institution_name, e.program_or_title, e.degree_level,
                       e.country, e.city, e.start_year, e.end_year, e.is_in_progress, e.document_url,
                       e.document_photos,
                       e.approved_at, e.updated_at
                FROM trainer_education e
                WHERE e.trainer_id = :tid
                  AND {vis}
                ORDER BY e.updated_at DESC, e.id DESC
            """
        else:
            q = """
                SELECT id, education_type, institution_name, program_or_title, degree_level,
                       country, city, start_year, end_year, is_in_progress, document_url,
                       document_photos,
                       moderation_status, moderation_comment, approved_at, updated_at
                FROM trainer_education
                WHERE trainer_id = :tid
                ORDER BY updated_at DESC, id DESC
            """
        r = await self._session.execute(text(q), params)
        out: list[dict[str, Any]] = []
        for row in r.fetchall():
            if public_only:
                out.append(
                    {
                        "id": row[0],
                        "education_type": row[1],
                        "institution_name": row[2],
                        "program_or_title": row[3],
                        "degree_level": row[4],
                        "country": row[5],
                        "city": row[6],
                        "start_year": row[7],
                        "end_year": row[8],
                        "is_in_progress": bool(row[9]),
                        "document_url": row[10],
                        "document_photos": _normalize_education_document_photos(row[11]),
                        "approved_at": row[12].isoformat() if row[12] else None,
                        "updated_at": row[13].isoformat() if row[13] else None,
                    }
                )
            else:
                out.append(
                    {
                        "id": row[0],
                        "education_type": row[1],
                        "institution_name": row[2],
                        "program_or_title": row[3],
                        "degree_level": row[4],
                        "country": row[5],
                        "city": row[6],
                        "start_year": row[7],
                        "end_year": row[8],
                        "is_in_progress": bool(row[9]),
                        "document_url": row[10],
                        "document_photos": _normalize_education_document_photos(row[11]),
                        "moderation_status": row[12],
                        "moderation_comment": row[13],
                        "approved_at": row[14].isoformat() if row[14] else None,
                        "updated_at": row[15].isoformat() if row[15] else None,
                    }
                )
        return out

    async def batch_public_education_entries(
        self,
        trainer_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        """
        Catalog-visible education rows for many trainers (same rules as list_education_entries public_only).
        """
        if not trainer_ids:
            return {}
        placeholders = ", ".join(f":be{i}" for i in range(len(trainer_ids)))
        params: dict[str, Any] = {f"be{i}": v for i, v in enumerate(trainer_ids)}
        vis = _sql_public_catalog_education_predicate("e")
        r = await self._session.execute(
            text(
                f"""
                SELECT e.trainer_id, e.id, e.education_type, e.institution_name, e.program_or_title, e.degree_level,
                       e.country, e.city, e.start_year, e.end_year, e.is_in_progress, e.document_url,
                       e.document_photos,
                       e.approved_at, e.updated_at
                FROM trainer_education e
                WHERE e.trainer_id IN ({placeholders})
                  AND {vis}
                ORDER BY e.trainer_id, e.updated_at DESC, e.id DESC
                """
            ),
            params,
        )
        out: dict[int, list[dict[str, Any]]] = {int(tid): [] for tid in trainer_ids}
        for row in r.fetchall():
            tid = int(row[0])
            if tid not in out:
                continue
            out[tid].append(
                {
                    "id": row[1],
                    "education_type": row[2],
                    "institution_name": row[3],
                    "program_or_title": row[4],
                    "degree_level": row[5],
                    "country": row[6],
                    "city": row[7],
                    "start_year": row[8],
                    "end_year": row[9],
                    "is_in_progress": bool(row[10]),
                    "document_url": row[11],
                    "document_photos": _normalize_education_document_photos(row[12]),
                    "approved_at": row[13].isoformat() if row[13] else None,
                    "updated_at": row[14].isoformat() if row[14] else None,
                }
            )
        return out

    async def create_education_entry(
        self,
        trainer_id: int,
        *,
        education_type: str,
        institution_name: str,
        program_or_title: str,
        degree_level: str | None = None,
        country: str | None = None,
        city: str | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
        is_in_progress: bool = False,
        document_url: str | None = None,
        document_photos: list[dict[str, Any]] | None = None,
    ) -> int:
        """Create pending education entry and return id."""
        r = await self._session.execute(
            text(
                """
                INSERT INTO trainer_education (
                    trainer_id, education_type, institution_name, program_or_title,
                    degree_level, country, city, start_year, end_year, is_in_progress,
                    document_url, document_photos, moderation_status, approved_snapshot, created_at, updated_at
                ) VALUES (
                    :trainer_id, :education_type, :institution_name, :program_or_title,
                    :degree_level, :country, :city, :start_year, :end_year, :is_in_progress,
                    :document_url, CAST(:document_photos_js AS jsonb), 'pending_moderation', false, now(), now()
                )
                RETURNING id
                """
            ),
            {
                "trainer_id": trainer_id,
                "education_type": education_type,
                "institution_name": institution_name,
                "program_or_title": program_or_title,
                "degree_level": degree_level,
                "country": country,
                "city": city,
                "start_year": start_year,
                "end_year": end_year,
                "is_in_progress": is_in_progress,
                "document_url": document_url,
                "document_photos_js": json.dumps(document_photos if isinstance(document_photos, list) else []),
            },
        )
        row = r.fetchone()
        return int(row[0])

    async def get_education_entry(self, trainer_id: int, education_id: int) -> dict[str, Any] | None:
        """Get education entry by trainer/id."""
        r = await self._session.execute(
            text(
                """
                SELECT id, moderation_status, institution_name, program_or_title, education_type,
                       degree_level, country, city, start_year, end_year, is_in_progress, document_url,
                       document_photos
                FROM trainer_education
                WHERE trainer_id = :tid AND id = :eid
                """
            ),
            {"tid": trainer_id, "eid": education_id},
        )
        row = r.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "moderation_status": row[1],
            "institution_name": row[2],
            "program_or_title": row[3],
            "education_type": row[4],
            "degree_level": row[5],
            "country": row[6],
            "city": row[7],
            "start_year": row[8],
            "end_year": row[9],
            "is_in_progress": bool(row[10]),
            "document_url": row[11],
            "document_photos": _normalize_education_document_photos(row[12]),
        }

    async def update_education_entry_in_place(
        self,
        trainer_id: int,
        education_id: int,
        *,
        updates: dict[str, Any],
    ) -> bool:
        """Update non-approved entry in place and keep pending moderation."""
        if not updates:
            return True
        allowed = {
            "education_type",
            "institution_name",
            "program_or_title",
            "degree_level",
            "country",
            "city",
            "start_year",
            "end_year",
            "is_in_progress",
            "document_url",
            "document_photos",
        }
        sets: list[str] = []
        params: dict[str, Any] = {"tid": trainer_id, "eid": education_id}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "document_photos":
                sets.append("document_photos = CAST(:document_photos_js AS jsonb)")
                params["document_photos_js"] = json.dumps(value if isinstance(value, list) else [])
            else:
                sets.append(f"{key} = :{key}")
                params[key] = value
        if not sets:
            return True
        sets.append("moderation_status = 'pending_moderation'")
        sets.append("approved_snapshot = false")
        q = (
            "UPDATE trainer_education SET "
            + ", ".join(sets)
            + ", updated_at = now() WHERE trainer_id = :tid AND id = :eid"
        )
        r = await self._session.execute(text(q), params)
        return r.rowcount > 0

    async def delete_education_entry(self, trainer_id: int, education_id: int) -> bool:
        """Delete one education row owned by trainer. Returns True if a row was removed."""
        r = await self._session.execute(
            text("DELETE FROM trainer_education WHERE trainer_id = :tid AND id = :eid"),
            {"tid": trainer_id, "eid": education_id},
        )
        return r.rowcount > 0

    async def create_education_revision(
        self,
        trainer_id: int,
        education_id: int,
        *,
        payload: dict[str, Any],
    ) -> int:
        """Create pending revision row for approved entry and return new id."""
        r = await self._session.execute(
            text(
                """
                INSERT INTO trainer_education (
                    trainer_id, education_type, institution_name, program_or_title,
                    degree_level, country, city, start_year, end_year, is_in_progress,
                    document_url, document_photos, moderation_status, moderation_comment, approved_snapshot,
                    approved_at, approved_by_admin_id, supersedes_id, created_at, updated_at
                ) VALUES (
                    :trainer_id, :education_type, :institution_name, :program_or_title,
                    :degree_level, :country, :city, :start_year, :end_year, :is_in_progress,
                    :document_url, CAST(:document_photos_js AS jsonb), 'pending_moderation', NULL, false,
                    NULL, NULL, :supersedes_id, now(), now()
                )
                RETURNING id
                """
            ),
            {
                "trainer_id": trainer_id,
                "education_type": payload.get("education_type"),
                "institution_name": payload.get("institution_name"),
                "program_or_title": payload.get("program_or_title"),
                "degree_level": payload.get("degree_level"),
                "country": payload.get("country"),
                "city": payload.get("city"),
                "start_year": payload.get("start_year"),
                "end_year": payload.get("end_year"),
                "is_in_progress": payload.get("is_in_progress", False),
                "document_url": payload.get("document_url"),
                "document_photos_js": json.dumps(
                    payload.get("document_photos") if isinstance(payload.get("document_photos"), list) else []
                ),
                "supersedes_id": education_id,
            },
        )
        row = r.fetchone()
        return int(row[0])

    async def moderate_pending_education_entries(
        self,
        trainer_id: int,
        *,
        decision: str,
        admin_id: int,
        reason: str | None = None,
    ) -> int:
        """
        Apply moderation decision to all pending education entries for trainer.
        Returns number of affected rows.
        """
        rows = await self._session.execute(
            text(
                """
                SELECT id
                FROM trainer_education
                WHERE trainer_id = :tid
                  AND moderation_status = 'pending_moderation'
                """
            ),
            {"tid": trainer_id},
        )
        pending_ids = [int(r[0]) for r in rows.fetchall()]
        if not pending_ids:
            return 0

        status = "approved" if decision == "approved" else "rejected"
        approved_snapshot = status == "approved"
        approved_at_expr = "now()" if status == "approved" else "NULL"
        approved_by_expr = ":admin_id" if status == "approved" else "NULL"
        reason_value = None if status == "approved" else (reason or "").strip()

        placeholders = ", ".join(f":eid{i}" for i in range(len(pending_ids)))
        params: dict[str, Any] = {"tid": trainer_id, "admin_id": admin_id, "reason": reason_value}
        params.update({f"eid{i}": eid for i, eid in enumerate(pending_ids)})

        await self._session.execute(
            text(
                f"""
                UPDATE trainer_education
                SET moderation_status = :status,
                    moderation_comment = :reason,
                    approved_snapshot = :approved_snapshot,
                    approved_at = {approved_at_expr},
                    approved_by_admin_id = {approved_by_expr},
                    updated_at = now()
                WHERE trainer_id = :tid
                  AND id IN ({placeholders})
                """
            ),
            {
                **params,
                "status": status,
                "approved_snapshot": approved_snapshot,
            },
        )

        for education_id in pending_ids:
            await self._session.execute(
                text(
                    """
                    INSERT INTO trainer_education_moderation_events (
                        trainer_education_id, admin_id, decision, reason, created_at
                    ) VALUES (
                        :education_id, :admin_id, :decision, :reason, now()
                    )
                    """
                ),
                {
                    "education_id": education_id,
                    "admin_id": admin_id,
                    "decision": status,
                    "reason": reason_value,
                },
            )
        return len(pending_ids)

    async def list_trainers(
        self,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List trainers with optional status filter; returns id, telegram_id, status, first_name, last_name, age."""
        q = """
            SELECT t.id, t.telegram_id, t.status, p.first_name, p.last_name, p.age
            FROM trainers t
            LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
        """
        params: dict[str, Any] = {"lim": limit, "off": offset}
        if status is not None:
            q += " WHERE t.status = :status"
            params["status"] = status
        q += " ORDER BY t.id LIMIT :lim OFFSET :off"
        r = await self._session.execute(text(q), params)
        return [
            {
                "id": row[0],
                "telegram_id": row[1],
                "status": row[2],
                "first_name": row[3],
                "last_name": row[4],
                "age": row[5],
            }
            for row in r.fetchall()
        ]

    async def update_status(self, trainer_id: int, status: str) -> bool:
        """Set trainer status; returns True if row updated."""
        r = await self._session.execute(
            text("UPDATE trainers SET status = :status WHERE id = :id"),
            {"id": trainer_id, "status": status},
        )
        return r.rowcount > 0

    async def set_is_catalog_visible(self, trainer_id: int, visible: bool) -> bool:
        """Show or hide trainer in /api/public catalog while status may stay active."""
        r = await self._session.execute(
            text("UPDATE trainers SET is_catalog_visible = :vis WHERE id = :id"),
            {"id": trainer_id, "vis": visible},
        )
        return r.rowcount > 0

    async def set_moderation_feedback(self, trainer_id: int, feedback: str | None) -> bool:
        """Set or clear moderation_feedback (e.g. for 'needs edit'). Returns True if trainer exists."""
        r = await self._session.execute(
            text("UPDATE trainers SET moderation_feedback = :fb WHERE id = :id"),
            {"id": trainer_id, "fb": feedback},
        )
        return r.rowcount > 0

    async def clear_moderation_submitted_at(self, trainer_id: int) -> None:
        """Profile/photo/services/education changed — require a new submit to ping admins again."""
        await self._session.execute(
            text("UPDATE trainers SET moderation_submitted_at = NULL WHERE id = :id"),
            {"id": trainer_id},
        )

    async def clear_moderation_feedback_and_submitted_at(self, trainer_id: int) -> None:
        """Drop queue state when profile is no longer eligible for moderation (incomplete aggregate)."""
        await self._session.execute(
            text(
                """
                UPDATE trainers
                SET moderation_feedback = NULL, moderation_submitted_at = NULL
                WHERE id = :id
                """
            ),
            {"id": trainer_id},
        )

    async def mark_queued_for_moderation_review(self, trainer_id: int) -> bool:
        """Clear feedback and stamp submit time (idempotent duplicate detection). Returns True if row exists."""
        r = await self._session.execute(
            text(
                """
                UPDATE trainers
                SET moderation_feedback = NULL, moderation_submitted_at = now()
                WHERE id = :id
                """
            ),
            {"id": trainer_id},
        )
        return r.rowcount > 0

    async def set_profile_pending(self, trainer_id: int, pending: dict[str, Any] | None) -> bool:
        """Store JSONB profile revision for active trainers; None clears."""
        if pending is None:
            r = await self._session.execute(
                text("UPDATE trainers SET profile_pending = NULL WHERE id = :id"),
                {"id": trainer_id},
            )
        else:
            r = await self._session.execute(
                text("UPDATE trainers SET profile_pending = CAST(:js AS jsonb) WHERE id = :id"),
                {"id": trainer_id, "js": json.dumps(pending)},
            )
        return r.rowcount > 0

    async def set_photo_pending(self, trainer_id: int, pending: dict[str, Any] | None) -> bool:
        """Active trainer: staged photo keys until moderation; None clears."""
        if pending is None:
            r = await self._session.execute(
                text("UPDATE trainers SET photo_pending = NULL WHERE id = :id"),
                {"id": trainer_id},
            )
        else:
            r = await self._session.execute(
                text("UPDATE trainers SET photo_pending = CAST(:js AS jsonb) WHERE id = :id"),
                {"id": trainer_id, "js": json.dumps(pending)},
            )
        return r.rowcount > 0

    async def add_photo(
        self, trainer_id: int, file_key: str, sort_order: int = 0, file_key_list: str | None = None
    ) -> None:
        """Append photo record for trainer. file_key_list = optional thumb for catalog list."""
        await self._session.execute(
            text("""
                INSERT INTO trainer_photos (trainer_id, file_key, file_key_list, sort_order)
                VALUES (:tid, :key, :key_list, :ord)
            """),
            {"tid": trainer_id, "key": file_key, "key_list": file_key_list, "ord": sort_order},
        )

    async def clear_photos(self, trainer_id: int) -> None:
        """Delete all photo records for trainer (DB-level only, storage cleanup is separate)."""
        await self._session.execute(
            text("DELETE FROM trainer_photos WHERE trainer_id = :tid"),
            {"tid": trainer_id},
        )

    # Bayesian prior for rating sort: score = (v/(v+m))*R + (m/(v+m))*C (m=10, C=4.0)
    _RATING_PRIOR_M = 10
    _RATING_PRIOR_C = 4.0

    async def list_active_with_details(
        self,
        limit: int = 50,
        offset: int = 0,
        city_id: int | None = None,
        service_id: int | None = None,
        arena_id: int | None = None,
        order_by: str = "rating",
        # Time-based filters
        filter_days: list[int] | None = None,  # [1,2,3] for Mon,Tue,Wed (0=Sunday)
        filter_time_slots: list[str] | None = None,  # ["09:00-12:00", "18:00-21:00"]
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Active trainers with profile, photos, service_ids; paginated.
        arena_id: only trainers that have at least one slot in this arena.
        Returns (items, total_count).

        Each trainer dict also contains:
        - free_slots_14d: count of available slots in the next 14 days (inclusive of today).
        """
        base = """
            FROM trainers t
            LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
        """
        where = " WHERE t.status = 'active' AND t.is_catalog_visible = true"
        where += """ AND EXISTS (
            SELECT 1 FROM trainer_subscriptions ts
            WHERE ts.trainer_id = t.id
              AND ts.expires_at > NOW()
              AND ts.status IN ('trial', 'active')
        )"""
        params: dict[str, Any] = {"lim": limit, "off": offset}
        if service_id is not None:
            base += " INNER JOIN trainer_services ts ON ts.trainer_id = t.id AND ts.service_id = :service_id"
            params["service_id"] = service_id
        if city_id is not None:
            where += " AND p.city_id = :city_id"
            params["city_id"] = city_id
        if arena_id is not None:
            base += " INNER JOIN trainer_arenas ta ON ta.trainer_id = t.id AND ta.arena_id = :arena_id"
            params["arena_id"] = arena_id

        # Time filters: match real `slots` rows (available, next 14 days).
        # Day chips: 0=Sun .. 6=Sat (same as PostgreSQL EXTRACT(DOW FROM date)).
        # Time windows: interval overlap — slot [start,end) vs window [a,b): end > a AND start < b.
        has_day = bool(filter_days)
        time_overlaps: list[str] = []
        if filter_time_slots:
            tw_i = 0
            for time_slot in filter_time_slots:
                parts = time_slot.split("-", 1)
                if len(parts) != 2:
                    continue
                w_start, w_end = parts[0].strip(), parts[1].strip()
                if not w_start or not w_end:
                    continue
                try:
                    t_a = datetime.strptime(w_start, "%H:%M").time()
                    t_b = datetime.strptime(w_end, "%H:%M").time()
                except ValueError:
                    continue
                # asyncpg expects Python time for TIME binds; strings raise DataError.
                time_overlaps.append(
                    f"(s.end_time > CAST(:slot_tw{tw_i}_a AS TIME) AND s.start_time < CAST(:slot_tw{tw_i}_b AS TIME))"
                )
                params[f"slot_tw{tw_i}_a"] = t_a
                params[f"slot_tw{tw_i}_b"] = t_b
                tw_i += 1
        has_time = bool(time_overlaps)
        if has_day or has_time:
            slot_where: list[str] = [
                "s.status = 'available'",
                "s.slot_date >= CURRENT_DATE",
                "s.slot_date <= CURRENT_DATE + INTERVAL '14 days'",
            ]
            if has_day:
                d_ph = ", ".join(f":slot_dow{i}" for i in range(len(filter_days)))
                for i, d in enumerate(filter_days):
                    params[f"slot_dow{i}"] = d
                slot_where.append(f"EXTRACT(DOW FROM s.slot_date) IN ({d_ph})")
            if has_time:
                slot_where.append("(" + " OR ".join(time_overlaps) + ")")
            base += f""" INNER JOIN (
                SELECT DISTINCT s.trainer_id
                FROM slots s
                WHERE {' AND '.join(slot_where)}
            ) available_slots ON available_slots.trainer_id = t.id"""

        # Total count with same filters
        count_q = "SELECT COUNT(DISTINCT t.id) " + base + where
        r_count = await self._session.execute(text(count_q), params)
        total = r_count.scalar() or 0

        sel = """
            SELECT DISTINCT t.id, t.telegram_id,
                   p.first_name, p.last_name, p.age, p.city_id, p.experience_years,
                   p.description, p.phone, p.contacts, p.education,
                   p.rating_avg, p.rating_count,
                   COALESCE(p.session_duration_minutes, 45) AS session_duration_minutes,
                   COALESCE(p.min_hours_before_booking, 3) AS min_hours_before_booking,
                   t.primary_arena_id
        """
        if order_by == "rating":
            # Bayesian: (v/(v+m))*R + (m/(v+m))*C. Must be in SELECT when using DISTINCT (PG rule).
            # _has_rating: trainers with at least one vote go before those with zero (same rule for ORDER BY).
            score_expr = (
                "(COALESCE(p.rating_count, 0)::float / (COALESCE(p.rating_count, 0) + :m))"
                " * COALESCE(p.rating_avg, :c)"
                " + (CAST(:m AS double precision) / (COALESCE(p.rating_count, 0) + :m)) * :c"
            )
            has_rating_expr = "CASE WHEN COALESCE(p.rating_count, 0) > 0 THEN 1 ELSE 0 END"
            sel = f"""
            SELECT DISTINCT t.id, t.telegram_id,
                   p.first_name, p.last_name, p.age, p.city_id, p.experience_years,
                   p.description, p.phone, p.contacts, p.education,
                   p.rating_avg, p.rating_count,
                   COALESCE(p.session_duration_minutes, 45) AS session_duration_minutes,
                   COALESCE(p.min_hours_before_booking, 3) AS min_hours_before_booking,
                   t.primary_arena_id,
                   ({has_rating_expr}) AS _has_rating,
                   ({score_expr}) AS _score
        """
            order = " ORDER BY _has_rating DESC, _score DESC NULLS LAST, t.id"
            params["m"] = self._RATING_PRIOR_M
            params["c"] = self._RATING_PRIOR_C
        else:
            order = " ORDER BY t.id"
        q = sel + base + where + order + " LIMIT :lim OFFSET :off"
        r = await self._session.execute(text(q), params)
        rows = r.fetchall()
        if not rows:
            return [], total
        ids = [row[0] for row in rows]
        placeholders = ", ".join(f":id{i}" for i in range(len(ids)))
        id_params = {f"id{i}": v for i, v in enumerate(ids)}
        edu_by_tid = await self.batch_public_education_entries(ids)
        rph = await self._session.execute(
            text(f"SELECT trainer_id, file_key, file_key_list, sort_order FROM trainer_photos WHERE trainer_id IN ({placeholders}) ORDER BY trainer_id, sort_order"),
            id_params,
        )
        photos_by_id: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
        for row in rph.fetchall():
            photos_by_id.setdefault(row[0], []).append({
                "file_key": row[1],
                "file_key_list": row[2],
                "sort_order": row[3],
            })
        rsv = await self._session.execute(
            text(
                f"SELECT trainer_id, service_id, price_cents, description, group_price_cents, client_notice FROM trainer_services WHERE trainer_id IN ({placeholders}) ORDER BY trainer_id, service_id"
            ),
            id_params,
        )
        service_rows = rsv.fetchall()
        services_by_id: dict[int, list[int]] = {i: [] for i in ids}
        services_detail_by_id: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
        all_sids: set[int] = set()
        for row in service_rows:
            tid, sid = row[0], row[1]
            services_by_id[tid].append(sid)
            all_sids.add(sid)
        service_names_by_id: dict[int, str] = {}
        if all_sids:
            s_placeholders = ", ".join(f":s{i}" for i in range(len(all_sids)))
            s_params = {f"s{i}": v for i, v in enumerate(all_sids)}
            r_sn = await self._session.execute(
                text(f"SELECT id, name FROM services WHERE id IN ({s_placeholders})"),
                s_params,
            )
            service_names_by_id = {r[0]: (r[1] or "") for r in r_sn.fetchall()}
        tiers_by_tid_sid: dict[tuple[int, int], list[dict[str, Any]]] = {}
        rv = await self._session.execute(
            text(
                f"""
                SELECT trainer_id, service_id, id, label, price_cents, sort_order, tier_kind
                FROM trainer_service_price_variants
                WHERE trainer_id IN ({placeholders})
                ORDER BY trainer_id, service_id,
                  {sql_order_case_tier_kind("tier_kind")},
                  sort_order
                """
            ),
            id_params,
        )
        for row in rv.fetchall():
            t_id, s_id, vid = int(row[0]), int(row[1]), int(row[2])
            lab, pc, so = row[3], int(row[4]), int(row[5])
            tk = normalize_price_tier_kind(row[6]) or PRICE_TIER_ADULT
            key = (t_id, s_id)
            tiers_by_tid_sid.setdefault(key, []).append(
                {
                    "id": vid,
                    "tier_kind": tk,
                    "label": lab or price_tier_label_ru(tk) or TRAINER_SERVICE_DEFAULT_TIER_LABEL,
                    "price_cents": pc,
                    "price_byn": round(pc / 100, 2),
                    "sort_order": so,
                }
            )
        for row in service_rows:
            tid, sid = row[0], row[1]
            price_cents = row[2]
            svc_desc_row: str | None = None
            if len(row) > 3 and row[3] is not None:
                s = str(row[3]).strip()
                if s:
                    svc_desc_row = s
            gpc_row = int(row[4]) if len(row) > 4 and row[4] is not None else None
            notice_row: str | None = None
            if len(row) > 5 and row[5] is not None:
                ns = str(row[5]).strip()
                if ns:
                    notice_row = ns
            tiers = tiers_by_tid_sid.get((tid, sid), [])
            if tiers:
                prices = [t["price_cents"] for t in tiers]
                p_min, p_max = min(prices), max(prices)
                price_byn_min = round(p_min / 100, 2)
                price_byn_max = round(p_max / 100, 2)
            else:
                price_byn_min = price_byn_max = (round(price_cents / 100, 2) if price_cents is not None else None)
            services_detail_by_id[tid].append(
                {
                    "service_id": sid,
                    "service_name": service_names_by_id.get(sid, "—"),
                    "price_cents": price_cents,
                    "price_byn": round(price_cents / 100, 2) if price_cents is not None else None,
                    "price_byn_min": price_byn_min,
                    "price_byn_max": price_byn_max,
                    "price_tiers": tiers,
                    "description": svc_desc_row,
                    "group_price_cents": gpc_row,
                    "group_price_byn": round(gpc_row / 100, 2) if gpc_row is not None else None,
                    "client_notice": notice_row,
                }
            )
        rar = await self._session.execute(
            text(f"SELECT trainer_id, arena_id FROM trainer_arenas WHERE trainer_id IN ({placeholders}) ORDER BY trainer_id, arena_id"),
            id_params,
        )
        arenas_by_id: dict[int, list[int]] = {i: [] for i in ids}
        for row in rar.fetchall():
            arenas_by_id[row[0]].append(row[1])
        # Load arena names for all arena_ids on this page
        all_aids = list({aid for aids in arenas_by_id.values() for aid in aids})
        arena_names_by_id: dict[int, str] = {}
        if all_aids:
            a_placeholders = ", ".join(f":a{i}" for i in range(len(all_aids)))
            a_params = {f"a{i}": v for i, v in enumerate(all_aids)}
            r_an = await self._session.execute(
                text(f"SELECT id, name FROM arenas WHERE id IN ({a_placeholders})"),
                a_params,
            )
            for arow in r_an.fetchall():
                arena_names_by_id[arow[0]] = arow[1] or ""

        # Count available slots for each trainer in the next 14 days (client-side signal).
        today = date.today()
        horizon_end = today + timedelta(days=13)
        r_slots = await self._session.execute(
            text(
                f"""
                SELECT trainer_id, COUNT(*) AS free_slots
                FROM slots
                WHERE trainer_id IN ({placeholders})
                  AND status = 'available'
                  AND slot_date >= :from_d AND slot_date <= :to_d
                GROUP BY trainer_id
                """
            ),
            {**id_params, "from_d": today, "to_d": horizon_end},
        )
        free_slots_by_id: dict[int, int] = {row[0]: row[1] or 0 for row in r_slots.fetchall()}
        # Catalog: show "Абонементы/Сертификаты" button only when trainer has at least one
        r_pass = await self._session.execute(
            text(f"SELECT DISTINCT trainer_id FROM trainer_pass_products WHERE trainer_id IN ({placeholders}) AND is_active = true"),
            id_params,
        )
        pass_trainer_ids: set[int] = {row[0] for row in r_pass.fetchall()}
        r_cert = await self._session.execute(
            text(f"SELECT DISTINCT trainer_id FROM trainer_certificate_products WHERE trainer_id IN ({placeholders}) AND is_active = true"),
            id_params,
        )
        cert_trainer_ids: set[int] = {row[0] for row in r_cert.fetchall()}
        
        out = []
        for row in rows:
            tid = row[0]
            arena_ids = arenas_by_id.get(tid, [])
            arena_names = [arena_names_by_id.get(aid, "—") for aid in arena_ids]
            # session_duration_minutes=13, min_hours_before_booking=14, primary_arena_id=15; rating: _has_rating=16, _score=17
            duration = row[13] if len(row) > 13 and row[13] is not None else 45
            min_hours = int(row[14]) if len(row) > 14 and row[14] is not None else 3
            primary_arena_id = row[15] if len(row) > 15 else None
            primary_arena_name = (
                (arena_names_by_id.get(primary_arena_id) or "").strip() or None
                if primary_arena_id is not None
                else None
            )
            out.append(
                {
                    "id": tid,
                    "telegram_id": row[1],
                    "profile": {
                        "first_name": row[2],
                        "last_name": row[3],
                        "age": row[4],
                        "city_id": row[5],
                        "experience_years": row[6],
                        "description": row[7],
                        "phone": row[8],
                        "contacts": row[9],
                        "education": row[10],
                        "rating_avg": float(row[11]) if row[11] is not None else None,
                        "rating_count": row[12] or 0,
                        "session_duration_minutes": duration,
                        "min_hours_before_booking": min_hours,
                    }
                    if row[2] is not None
                    else None,
                    "photos": photos_by_id.get(tid, []),
                    "service_ids": services_by_id.get(tid, []),
                    "services": services_detail_by_id.get(tid, []),
                    "arena_ids": arena_ids,
                    "arena_names": arena_names,
                    "primary_arena_id": primary_arena_id,
                    "primary_arena_name": primary_arena_name,
                    "free_slots_14d": free_slots_by_id.get(tid, 0),
                    "has_pass_products": tid in pass_trainer_ids,
                    "has_certificate_products": tid in cert_trainer_ids,
                    "education_entries": edu_by_tid.get(tid, []),
                }
            )
        return out, total

    async def add_rating(
        self,
        trainer_id: int,
        client_telegram_id: int,
        rating: int,
        review_text: str | None = None,
    ) -> bool:
        """Upsert rating 1–5 and optional review text; update profile aggregates. Returns True if trainer exists."""
        if not await self.exists(trainer_id):
            return False
        rating_val = max(1, min(5, rating))
        await self._session.execute(
            text("""
                INSERT INTO trainer_ratings (trainer_id, client_telegram_id, rating, review_text)
                VALUES (:tid, :ctid, :rating, :review_text)
                ON CONFLICT (trainer_id, client_telegram_id)
                DO UPDATE SET rating = EXCLUDED.rating,
                  review_text = COALESCE(EXCLUDED.review_text, trainer_ratings.review_text)
            """),
            {"tid": trainer_id, "ctid": client_telegram_id, "rating": rating_val, "review_text": review_text},
        )
        r = await self._session.execute(
            text("SELECT AVG(rating)::float, COUNT(*)::int FROM trainer_ratings WHERE trainer_id = :tid"),
            {"tid": trainer_id},
        )
        row = r.fetchone()
        avg_val = row[0] if row and row[0] is not None else None
        count_val = (row[1] or 0) if row else 0
        await self._session.execute(
            text("""
                UPDATE trainer_profiles SET rating_avg = :avg, rating_count = :cnt, updated_at = now()
                WHERE trainer_id = :tid
            """),
            {"tid": trainer_id, "avg": avg_val, "cnt": count_val},
        )
        return True

    async def list_public_ratings_for_trainer(
        self,
        trainer_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Public review list: rating, optional text, date. No client identifiers (privacy).
        """
        r = await self._session.execute(
            text("SELECT COUNT(*)::int FROM trainer_ratings WHERE trainer_id = :tid"),
            {"tid": trainer_id},
        )
        total = int(r.scalar() or 0)
        r2 = await self._session.execute(
            text("""
                SELECT rating, review_text, created_at
                FROM trainer_ratings
                WHERE trainer_id = :tid
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            {"tid": trainer_id, "lim": limit, "off": offset},
        )
        rows = r2.fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            rt = row[1]
            text_clean = (rt or "").strip() if rt else ""
            created = row[2]
            items.append(
                {
                    "rating": int(row[0]),
                    "review_text": text_clean or None,
                    "created_at": created.isoformat() if created else None,
                }
            )
        return items, total
