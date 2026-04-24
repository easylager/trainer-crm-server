"""
Application layer: trainer use cases. Orchestrates repository; no HTTP, no SQL.
"""
import logging
from io import BytesIO
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure import s3

from src.application.admin_moderation_notify import notify_admins_trainer_queued_for_moderation
from src.application.arena_schedule_preset import (
    get_schedule_grid_preset_for_trainer,
    normalize_trainer_schedule_grid_step,
)
from src.application.subscription_use_cases import create_trial_subscription
from src.application.trainer_profile_pending import (
    PROFILE_KEYS_FOR_PUBLISHED_UPDATE,
    active_trainer_revision_diff,
    merge_pending_dict,
    merge_profile_pending_for_editor,
    split_active_trainer_profile_patch,
)
from src.application.trainer_profile_completeness import (
    analyze_moderation_submission_readiness,
    is_ready_for_moderation_submission,
    missing_labels_ru,
    moderation_readiness_dict,
)
from src.infrastructure.db.models import (
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_PENDING_CONTRACT,
    TRAINER_STATUS_PENDING_PAYMENT,
    TRAINER_STATUS_PENDING_PROFILE,
)
from src.infrastructure.repositories import TrainerRepository
from src.shared.audit import ACTOR_API, audit_log

logger = logging.getLogger(__name__)

# Below Telegram Bot API ~20MB file limit; keeps memory bounded in bot handlers.
MAX_TRAINER_PHOTO_BYTES = 15 * 1024 * 1024
MAX_TRAINER_EDUCATION_DOCUMENT_PHOTOS = 12


class TrainerPhotoFileKeyError(ValueError):
    """Raised when file_key / file_key_list are not under trainers/{trainer_id}/ in storage."""


def photo_storage_keys_allowed_for_trainer(
    trainer_id: int, file_key: str, file_key_list: str | None = None
) -> bool:
    """True if keys are non-empty, path-safe, and scoped to the trainer's namespace."""
    if not file_key or ".." in file_key:
        return False
    prefix = f"trainers/{trainer_id}/"
    if not file_key.startswith(prefix):
        return False
    if file_key_list:
        if ".." in file_key_list or not file_key_list.startswith(prefix):
            return False
    return True


def trainer_photo_bytes_look_like_image(body: bytes) -> bool:
    """True if PIL can load raster image bytes (sync; used before S3 put)."""
    if not body:
        return False
    try:
        from PIL import Image
    except ImportError:
        # Without Pillow, s3.upload_photo cannot resize; let storage layer fail closed on garbage.
        return True
    try:
        with Image.open(BytesIO(body)) as img:
            img.load()
        return True
    except Exception:
        return False


def _profile_to_kwargs(profile: dict[str, Any]) -> dict[str, Any]:
    """Map profile dict to repository create_profile kwargs."""
    return {
        "first_name": profile.get("first_name") or "",
        "last_name": profile.get("last_name") or "",
        "age": profile.get("age", 0),
        "city_id": profile.get("city_id"),
        "experience_years": profile.get("experience_years"),
        "description": profile.get("description"),
        "phone": profile.get("phone"),
        "contacts": profile.get("contacts"),
        "education": profile.get("education"),
        "session_duration_minutes": profile.get("session_duration_minutes"),
    }


def _service_description_from_payload(s: dict[str, Any]) -> str | None:
    raw = s.get("description")
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    t = raw.strip()
    return t if t else None


def _service_client_notice_from_payload(s: dict[str, Any]) -> str | None:
    raw = s.get("client_notice")
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    t = raw.strip()
    return t if t else None


def _group_price_cents_from_service_payload(s: dict[str, Any]) -> int | None:
    raw = s.get("group_price_byn")
    if raw is None:
        return None
    return int(round(float(raw) * 100))


def _services_to_entries(
    services: list[dict[str, Any]],
) -> list[tuple[int, list[tuple[str, int]], str | None, int | None, str | None]]:
    """
    Convert API services to repo entries:
    (service_id, [(tier_kind, price_cents), ...], description, group_price_cents|None, client_notice|None).
    """
    from src.shared.price_tier_kind import (
        PRICE_TIER_ADULT,
        PRICE_TIER_CHILD,
        normalize_price_tier_kind,
        price_tier_sort_key,
    )

    result: list[tuple[int, list[tuple[str, int]], str | None, int | None, str | None]] = []
    for s in services:
        sid = int(s["service_id"])
        desc = _service_description_from_payload(s)
        group_pc = _group_price_cents_from_service_payload(s)
        notice = _service_client_notice_from_payload(s)
        tiers_raw = s.get("price_tiers")
        if isinstance(tiers_raw, list) and len(tiers_raw) > 0:
            merged: dict[str, int] = {}
            for t in tiers_raw:
                if not isinstance(t, dict):
                    continue
                pb = t.get("price_byn")
                if pb is None:
                    continue
                cents = int(round(float(pb) * 100))
                tk = normalize_price_tier_kind(t.get("tier_kind"))
                if tk is None:
                    continue
                merged[tk] = cents
            ordered = sorted(merged.items(), key=lambda x: price_tier_sort_key(x[0]))
            result.append((sid, ordered, desc, group_pc, notice))
            continue
        price_byn = s.get("price_byn")
        child_byn = s.get("price_child_byn")
        tiers: list[tuple[str, int]] = []
        if price_byn is not None:
            tiers.append((PRICE_TIER_ADULT, int(round(float(price_byn) * 100))))
        if child_byn is not None:
            tiers.append((PRICE_TIER_CHILD, int(round(float(child_byn) * 100))))
        tiers.sort(key=lambda x: price_tier_sort_key(x[0]))
        result.append((sid, tiers, desc, group_pc, notice))
    return result


async def _demote_status_if_profile_incomplete(session: AsyncSession, trainer_id: int) -> bool:
    """
    Demote to pending_profile if submission readiness (8 criteria) fails while status is
    active / pending_contract / pending_payment. Returns True if status was demoted.
    """
    repo = TrainerRepository(session)
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        return False
    st = (trainer.get("status") or "").strip()
    submit_ok, _ = analyze_moderation_submission_readiness(trainer)
    if not submit_ok and st in (
        TRAINER_STATUS_ACTIVE,
        TRAINER_STATUS_PENDING_CONTRACT,
        TRAINER_STATUS_PENDING_PAYMENT,
    ):
        await repo.update_status(trainer_id, TRAINER_STATUS_PENDING_PROFILE)
        await session.commit()
        logger.info("Trainer %d demoted to pending_profile (profile incomplete)", trainer_id)
        return True
    return False


async def ensure_trainer_services_replace_allowed(
    session: AsyncSession,
    trainer_id: int,
    new_service_ids: set[int],
) -> None:
    """
    Block removing a service from the trainer catalog while it is still referenced by
    schedule slots, active bookings, weekly templates, or training groups — avoids orphan slots / broken booking flow.
    """
    r = await session.execute(
        text("SELECT service_id FROM trainer_services WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    old_ids = {int(row[0]) for row in r.fetchall()}
    removed = old_ids - set(new_service_ids)
    if not removed:
        return
    ids_sql = ",".join(str(int(x)) for x in removed)

    async def _has_row(sql: str) -> bool:
        rr = await session.execute(text(sql), {"tid": trainer_id})
        return rr.fetchone() is not None

    if await _has_row(
        f"SELECT 1 FROM slots WHERE trainer_id = :tid AND status != 'cancelled' "
        f"AND service_id IS NOT NULL AND service_id IN ({ids_sql}) LIMIT 1"
    ):
        raise ValueError(
            "Нельзя убрать услугу: есть слоты в расписании, привязанные к ней. "
            "Сначала удалите слоты или смените у них услугу."
        )
    if await _has_row(
        f"SELECT 1 FROM bookings WHERE trainer_id = :tid AND status IN ('pending', 'confirmed') "
        f"AND service_id IN ({ids_sql}) LIMIT 1"
    ):
        raise ValueError(
            "Нельзя убрать услугу: есть активные записи (ожидают подтверждения или подтверждены). "
            "Сначала отмените или перенесите их."
        )
    if await _has_row(
        f"SELECT 1 FROM trainer_schedule_templates WHERE trainer_id = :tid AND service_id IS NOT NULL "
        f"AND service_id IN ({ids_sql}) LIMIT 1"
    ):
        raise ValueError(
            "Нельзя убрать услугу: она указана в шаблоне расписания. Сначала измените или удалите шаблон."
        )
    if await _has_row(
        f"SELECT 1 FROM training_groups WHERE trainer_id = :tid AND service_id IN ({ids_sql}) LIMIT 1"
    ):
        raise ValueError(
            "Нельзя убрать услугу: она привязана к группе в разделе «Группы». Сначала смените услугу у группы."
        )


async def _apply_trainer_services_update(
    repo: TrainerRepository,
    session: AsyncSession,
    trainer_id: int,
    services: list[dict[str, Any]] | None,
    service_ids: list[int] | None,
) -> None:
    if services is not None:
        new_set = {int(s["service_id"]) for s in services}
        await ensure_trainer_services_replace_allowed(session, trainer_id, new_set)
        await repo.set_trainer_services(trainer_id, _services_to_entries(services))
    elif service_ids is not None:
        new_set = {int(x) for x in service_ids}
        await ensure_trainer_services_replace_allowed(session, trainer_id, new_set)
        await repo.set_trainer_services(trainer_id, [(sid, []) for sid in service_ids])


async def create_trainer(
    session: AsyncSession,
    *,
    profile: dict[str, Any] | None = None,
    service_ids: list[int] | None = None,
    services: list[dict[str, Any]] | None = None,
    arena_ids: list[int] | None = None,
) -> int:
    """Create trainer; optionally with profile, services (with prices), arena_ids. Returns new trainer id."""
    repo = TrainerRepository(session)
    trainer_id = await repo.create_trainer()
    if profile:
        await repo.create_profile(trainer_id, **_profile_to_kwargs(profile))
    if services is not None:
        await repo.set_trainer_services(trainer_id, _services_to_entries(services))
    elif service_ids:
        await repo.set_trainer_services(trainer_id, [(sid, []) for sid in service_ids])
    if arena_ids:
        await repo.set_trainer_arenas(trainer_id, arena_ids)
        await repo.reconcile_primary_arena(trainer_id)
    await session.commit()
    return trainer_id


async def get_trainer(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """Load trainer by id with profile, photos, service_ids; None if not found."""
    return await TrainerRepository(session).get_by_id(trainer_id)


async def ensure_trainer_profile_row(session: AsyncSession, trainer_id: int) -> bool:
    """Insert empty trainer_profiles row if missing so PATCH/update_profile works (e.g. bot wizard)."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    row = await repo.get_by_id(trainer_id)
    if row and row.get("profile") is not None:
        return True
    await repo.create_profile(trainer_id, first_name="", last_name="", age=0)
    await session.commit()
    return True


async def reconcile_trainer_moderation_queue_if_incomplete(session: AsyncSession, trainer_id: int) -> None:
    """
    Invariant: moderation_feedback + moderation_submitted_at only apply when the aggregate meets
    submission readiness (8 criteria). If submission is incomplete and status is pending_profile,
    clear both so partial drafts never look «in moderation» or retain stale moderator comments.
    """
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        return
    if is_ready_for_moderation_submission(trainer):
        return
    st = (trainer.get("status") or "").strip()
    if st != TRAINER_STATUS_PENDING_PROFILE:
        return
    fb = trainer.get("moderation_feedback")
    sub_at = trainer.get("moderation_submitted_at")
    fb_empty = fb is None or (isinstance(fb, str) and not str(fb).strip())
    if fb_empty and sub_at is None:
        return
    repo = TrainerRepository(session)
    await repo.clear_moderation_feedback_and_submitted_at(trainer_id)
    await session.commit()


async def apply_trainer_profile_pending_to_published(session: AsyncSession, trainer_id: int) -> bool:
    """Merge profile_pending into trainer_profiles and clear pending + queue stamp. No-op if no pending."""
    repo = TrainerRepository(session)
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        return False
    pending = trainer.get("profile_pending")
    if not isinstance(pending, dict) or not pending:
        return True
    await repo.ensure_trainer_profile_row(trainer_id)
    kw = {
        k: v
        for k, v in pending.items()
        if v is not None and k in PROFILE_KEYS_FOR_PUBLISHED_UPDATE
    }
    unknown = set(pending.keys()) - PROFILE_KEYS_FOR_PUBLISHED_UPDATE
    if unknown:
        logger.warning(
            "profile_pending had unknown keys (ignored on publish) trainer_id=%s keys=%s",
            trainer_id,
            sorted(unknown),
        )
    if kw:
        await repo.update_profile(trainer_id, **kw)
        logger.info("published profile_pending fields trainer_id=%s keys=%s", trainer_id, sorted(kw.keys()))
    elif pending:
        logger.warning(
            "profile_pending non-empty but no publishable keys after filter trainer_id=%s", trainer_id
        )
    await repo.set_profile_pending(trainer_id, None)
    await session.flush()
    return True


async def apply_photo_pending_to_published(session: AsyncSession, trainer_id: int) -> bool:
    """Promote photo_pending into trainer_photos; clear staging. No-op if no pending photo."""
    repo = TrainerRepository(session)
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        return False
    pp = trainer.get("photo_pending")
    if not isinstance(pp, dict):
        return True
    file_key = (pp.get("file_key") or "").strip()
    if not file_key:
        await repo.set_photo_pending(trainer_id, None)
        await session.flush()
        return True
    file_key_list = (pp.get("file_key_list") or "").strip() or None
    await repo.clear_photos(trainer_id)
    await repo.add_photo(trainer_id, file_key, 0, file_key_list=file_key_list)
    await repo.set_photo_pending(trainer_id, None)
    await session.flush()
    logger.info("published photo_pending trainer_id=%s", trainer_id)
    return True


async def discard_active_trainer_text_revision_with_feedback(
    session: AsyncSession, trainer_id: int, feedback: str | None
) -> bool:
    """
    Active trainer: drop queued text revision (profile_pending), clear submit stamp, set moderator comment.
    Catalog keeps published trainer_profiles; trainer stays active.
    """
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    await repo.set_profile_pending(trainer_id, None)
    await repo.set_photo_pending(trainer_id, None)
    await repo.clear_moderation_submitted_at(trainer_id)
    await repo.set_moderation_feedback(trainer_id, feedback)
    await session.commit()
    return True


async def update_trainer_profile(
    session: AsyncSession,
    trainer_id: int,
    *,
    profile: dict[str, Any],
    service_ids: list[int] | None = None,
    services: list[dict[str, Any]] | None = None,
    arena_ids: list[int] | None = None,
    primary_arena_id: int | None = None,
    primary_arena_id_set: bool = False,
    schedule_grid_step_minutes: int | None = None,
    schedule_grid_step_minutes_set: bool = False,
) -> bool:
    """
    Patch profile and/or services (with prices) and/or arena_ids. Returns False if trainer not found.

    Active trainers: only first_name, last_name, description, experience_years queue into
    ``profile_pending`` (catalog keeps prior values until approved). Other profile columns
    (age, phone, city, session rules, etc.) update ``trainer_profiles`` immediately.
    Services/arenas update immediately and do not affect the moderation queue.
    Revision fields are ignored for moderation if unchanged vs current published+pending (same save as services).
    """
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    trainer = await get_trainer(session, trainer_id)
    st = (trainer.get("status") or "").strip()
    updates = {k: v for k, v in profile.items() if v is not None}
    revision_patch, direct_patch = split_active_trainer_profile_patch(updates)
    services_dirty = services is not None or service_ids is not None or arena_ids is not None

    if st == TRAINER_STATUS_ACTIVE:
        revision_patch = active_trainer_revision_diff(trainer, revision_patch)
        if direct_patch:
            await repo.ensure_trainer_profile_row(trainer_id)
            await repo.update_profile(trainer_id, **direct_patch)
        if revision_patch:
            await repo.ensure_trainer_profile_row(trainer_id)
            new_pending = merge_pending_dict(
                trainer.get("profile_pending") if isinstance(trainer.get("profile_pending"), dict) else None,
                revision_patch,
            )
            await repo.set_profile_pending(trainer_id, new_pending)
            await repo.mark_queued_for_moderation_review(trainer_id)
        if services is not None:
            await _apply_trainer_services_update(repo, session, trainer_id, services, None)
        elif service_ids is not None:
            await _apply_trainer_services_update(repo, session, trainer_id, None, service_ids)
        if arena_ids is not None:
            await repo.set_trainer_arenas(trainer_id, arena_ids)
            await repo.reconcile_primary_arena(trainer_id)
        if primary_arena_id_set:
            if primary_arena_id is None:
                await repo.reconcile_primary_arena(trainer_id)
            else:
                aids = await repo.list_trainer_arena_ids(trainer_id)
                if primary_arena_id not in aids:
                    raise ValueError("primary_arena_id must be among trainer arenas")
                await repo.set_trainer_primary_arena(trainer_id, primary_arena_id)
        if schedule_grid_step_minutes_set:
            await session.flush()
            preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
            if preset.get("arena_id") is not None:
                raise ValueError(
                    "Сетка расписания для этой арены задаётся правилами площадки. Изменить её в профиле нельзя."
                )
            await repo.set_schedule_grid_step_minutes(
                trainer_id, normalize_trainer_schedule_grid_step(schedule_grid_step_minutes)
            )
        await session.commit()
        if revision_patch:
            try:
                await notify_admins_trainer_queued_for_moderation(trainer_id)
            except Exception:  # noqa: BLE001
                logger.exception("notify admins after active profile pending failed trainer_id=%s", trainer_id)
        await _demote_status_if_profile_incomplete(session, trainer_id)
        await reconcile_trainer_moderation_queue_if_incomplete(session, trainer_id)
        from src.application.referral_use_cases import maybe_grant_referral_onboarding_bonus

        await maybe_grant_referral_onboarding_bonus(trainer_id)
        return True

    if updates:
        await repo.ensure_trainer_profile_row(trainer_id)
        await repo.update_profile(trainer_id, **updates)
    if services is not None:
        await _apply_trainer_services_update(repo, session, trainer_id, services, None)
    elif service_ids is not None:
        await _apply_trainer_services_update(repo, session, trainer_id, None, service_ids)
    if arena_ids is not None:
        await repo.set_trainer_arenas(trainer_id, arena_ids)
        await repo.reconcile_primary_arena(trainer_id)
    if primary_arena_id_set:
        if primary_arena_id is None:
            await repo.reconcile_primary_arena(trainer_id)
        else:
            aids = await repo.list_trainer_arena_ids(trainer_id)
            if primary_arena_id not in aids:
                raise ValueError("primary_arena_id must be among trainer arenas")
            await repo.set_trainer_primary_arena(trainer_id, primary_arena_id)
    if schedule_grid_step_minutes_set:
        await session.flush()
        preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
        if preset.get("arena_id") is not None:
            raise ValueError(
                "Сетка расписания для этой арены задаётся правилами площадки. Изменить её в профиле нельзя."
            )
        await repo.set_schedule_grid_step_minutes(
            trainer_id, normalize_trainer_schedule_grid_step(schedule_grid_step_minutes)
        )
    dirty = bool(updates) or services is not None or service_ids is not None or arena_ids is not None or primary_arena_id_set
    if dirty:
        await repo.clear_moderation_submitted_at(trainer_id)
    await session.commit()
    await _demote_status_if_profile_incomplete(session, trainer_id)
    await reconcile_trainer_moderation_queue_if_incomplete(session, trainer_id)
    from src.application.referral_use_cases import maybe_grant_referral_onboarding_bonus

    await maybe_grant_referral_onboarding_bonus(trainer_id)
    return True


async def list_trainers(
    session: AsyncSession,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List trainers with optional status filter (e.g. status=active for catalog)."""
    return await TrainerRepository(session).list_trainers(limit=limit, offset=offset, status=status)


async def update_trainer_status(session: AsyncSession, trainer_id: int, status: str) -> bool:
    """Set trainer status. Returns False if trainer not found.
    When status is set to active, creates trial subscription if trainer has not used trial yet.
    """
    repo = TrainerRepository(session)
    if not await repo.update_status(trainer_id, status):
        return False
    await session.commit()
    if status == TRAINER_STATUS_ACTIVE:
        await create_trial_subscription(session, trainer_id)
    return True


async def set_trainer_catalog_visibility(session: AsyncSession, trainer_id: int, *, visible: bool) -> bool:
    """Toggle public catalog listing; trainer may remain status=active."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    if not await repo.set_is_catalog_visible(trainer_id, visible):
        return False
    await session.commit()
    return True


async def set_trainer_moderation_feedback(
    session: AsyncSession, trainer_id: int, feedback: str | None
) -> bool:
    """Set or clear moderation feedback (shown on site). Returns False if trainer not found."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    await repo.set_moderation_feedback(trainer_id, feedback)
    await session.commit()
    return True


async def try_submit_trainer_for_moderation_review(
    session: AsyncSession,
    trainer_id: int,
    *,
    audit_actor_type: str = ACTOR_API,
    audit_actor_id: str | int = "api",
) -> dict[str, Any]:
    """
    Queue trainer for admin profile moderation (submission tier: 8 criteria, same as Mini App / REST).

    Trainer row stays status=pending_profile (admin /pending lists this). We stamp
    moderation_submitted_at to avoid duplicate admin pings until the trainer changes
    profile/photo/services/education again.

    Returns dict for HTTP/bot. noop reasons: wrong_status | already_submitted
    """
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        return {"ok": False, "error": "not_found"}
    complete, missing = analyze_moderation_submission_readiness(trainer)
    if not complete:
        return {
            "ok": False,
            "missing_fields": missing,
            "missing_labels_ru": missing_labels_ru(missing),
        }
    st = (trainer.get("status") or "").strip()
    if st == TRAINER_STATUS_ACTIVE:
        # Revisions are auto-queued on PATCH; manual submit is a no-op if nothing pending.
        pending = trainer.get("profile_pending")
        if not isinstance(pending, dict) or not pending:
            return {"ok": True, "noop": True, "reason": "no_pending_text_revision", "trainer_status": st}
        return {"ok": True, "noop": True, "reason": "active_revision_auto_queued", "trainer_status": st}

    if st != TRAINER_STATUS_PENDING_PROFILE:
        return {"ok": True, "noop": True, "reason": "wrong_status", "trainer_status": st}

    fb = trainer.get("moderation_feedback")
    fb_empty = fb is None or (isinstance(fb, str) and not str(fb).strip())
    sub_at = trainer.get("moderation_submitted_at")
    if fb_empty and sub_at is not None:
        return {"ok": True, "noop": True, "reason": "already_submitted", "trainer_status": st}

    repo = TrainerRepository(session)
    if not await repo.mark_queued_for_moderation_review(trainer_id):
        return {"ok": False, "error": "not_found"}
    await session.commit()
    audit_log(
        "trainer.submitted_for_moderation",
        audit_actor_type,
        audit_actor_id,
        {"trainer_id": trainer_id},
    )
    try:
        await notify_admins_trainer_queued_for_moderation(trainer_id)
    except Exception:  # noqa: BLE001
        logger.exception("notify admins after moderation submit failed trainer_id=%s", trainer_id)
    return {"ok": True, "submitted": True}


async def get_trainer_moderation_readiness(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """moderation_readiness_dict for GET endpoints (submission + full_profile_*); None if trainer missing."""
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        return None
    for_editor = dict(trainer)
    merged = merge_profile_pending_for_editor(
        trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {},
        trainer.get("profile_pending") if isinstance(trainer.get("profile_pending"), dict) else None,
    )
    if merged is not None:
        for_editor["profile"] = merged
    return moderation_readiness_dict(for_editor, trainer_status=(trainer.get("status") or "").strip() or None)


async def list_active_trainers_for_client(
    session: AsyncSession,
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
    """Active trainers; optional arena filter (trainers with slot in that arena). Returns (items, total)."""
    return await TrainerRepository(session).list_active_with_details(
        limit=limit,
        offset=offset,
        city_id=city_id,
        service_id=service_id,
        arena_id=arena_id,
        order_by=order_by,
        filter_days=filter_days,
        filter_time_slots=filter_time_slots,
    )


async def add_trainer_rating(
    session: AsyncSession,
    trainer_id: int,
    client_telegram_id: int,
    rating: int,
    review_text: str | None = None,
) -> bool:
    """Set or update client's rating 1–5 and optional review for trainer; updates profile aggregates."""
    ok = await TrainerRepository(session).add_rating(
        trainer_id, client_telegram_id, rating, review_text=review_text
    )
    if ok:
        await session.commit()
    return ok


async def list_public_trainer_reviews(
    session: AsyncSession,
    trainer_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int] | None:
    """
    Public reviews for catalog (no client ids). None if trainer not visible in catalog (same rules as GET /trainers/{id}).
    """
    trainer = await get_trainer(session, trainer_id)
    if not trainer or (trainer.get("status") or "").strip().lower() != "active":
        return None
    if not bool(trainer.get("is_catalog_visible", True)):
        return None
    return await TrainerRepository(session).list_public_ratings_for_trainer(
        trainer_id, limit=limit, offset=offset
    )


def _validate_education_payload(payload: dict[str, Any]) -> None:
    """Validate trainer education payload for create/update flows."""
    institution = (payload.get("institution_name") or "").strip()
    program = (payload.get("program_or_title") or "").strip()
    if not institution or len(institution) < 2:
        raise ValueError("institution_name is required")
    if not program or len(program) < 2:
        raise ValueError("program_or_title is required")
    start_year = payload.get("start_year")
    end_year = payload.get("end_year")
    if start_year is not None and end_year is not None and start_year > end_year:
        raise ValueError("start_year must be <= end_year")


def _normalize_education_document_photos_for_trainer(
    trainer_id: int,
    raw_photos: Any,
) -> list[dict[str, str | None]]:
    """
    Normalize education document photos and enforce trainer-owned storage namespace.

    The UI may send an empty list or omit the field; both are treated as "no files".
    """
    if raw_photos is None:
        return []
    if not isinstance(raw_photos, list):
        raise ValueError("document_photos must be an array")
    if len(raw_photos) > MAX_TRAINER_EDUCATION_DOCUMENT_PHOTOS:
        raise ValueError(f"document_photos supports up to {MAX_TRAINER_EDUCATION_DOCUMENT_PHOTOS} files")
    out: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_photos):
        if not isinstance(raw, dict):
            raise ValueError(f"document_photos[{i}] must be an object")
        file_key = (raw.get("file_key") or "").strip()
        file_key_list = (raw.get("file_key_list") or "").strip() or None
        if not file_key:
            raise ValueError(f"document_photos[{i}].file_key is required")
        if not photo_storage_keys_allowed_for_trainer(trainer_id, file_key, file_key_list):
            raise ValueError("document_photos file_key must be under trainers/{trainer_id}/")
        if file_key in seen:
            continue
        seen.add(file_key)
        out.append({"file_key": file_key, "file_key_list": file_key_list})
    return out


async def list_trainer_education(
    session: AsyncSession,
    trainer_id: int,
    *,
    public_only: bool = False,
) -> list[dict[str, Any]] | None:
    """List trainer education entries, None when trainer missing."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return None
    return await repo.list_education_entries(trainer_id, public_only=public_only)


async def create_trainer_education(
    session: AsyncSession,
    trainer_id: int,
    *,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Create new pending trainer education entry."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return None
    _validate_education_payload(payload)
    document_photos = _normalize_education_document_photos_for_trainer(
        trainer_id,
        payload.get("document_photos"),
    )
    entry_id = await repo.create_education_entry(
        trainer_id,
        education_type=payload["education_type"],
        institution_name=(payload["institution_name"] or "").strip(),
        program_or_title=(payload["program_or_title"] or "").strip(),
        degree_level=payload.get("degree_level"),
        country=payload.get("country"),
        city=payload.get("city"),
        start_year=payload.get("start_year"),
        end_year=payload.get("end_year"),
        is_in_progress=bool(payload.get("is_in_progress", False)),
        document_url=payload.get("document_url"),
        document_photos=document_photos,
    )
    await repo.clear_moderation_submitted_at(trainer_id)
    await session.commit()
    await reconcile_trainer_moderation_queue_if_incomplete(session, trainer_id)
    return {"id": entry_id, "moderation_status": "pending_moderation"}


async def update_trainer_education(
    session: AsyncSession,
    trainer_id: int,
    education_id: int,
    *,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Update education entry; approved entries create pending revision."""
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return None
    current = await repo.get_education_entry(trainer_id, education_id)
    if not current:
        return None
    merged = {**current, **payload}
    merged["document_photos"] = _normalize_education_document_photos_for_trainer(
        trainer_id,
        merged.get("document_photos"),
    )
    _validate_education_payload(merged)
    if current.get("moderation_status") == "approved":
        new_id = await repo.create_education_revision(trainer_id, education_id, payload=merged)
        await repo.clear_moderation_submitted_at(trainer_id)
        await session.commit()
        await reconcile_trainer_moderation_queue_if_incomplete(session, trainer_id)
        return {"id": new_id, "moderation_status": "pending_moderation", "revision_created": True}
    ok = await repo.update_education_entry_in_place(trainer_id, education_id, updates=merged)
    if not ok:
        return None
    await repo.clear_moderation_submitted_at(trainer_id)
    await session.commit()
    await reconcile_trainer_moderation_queue_if_incomplete(session, trainer_id)
    return {"id": education_id, "moderation_status": "pending_moderation", "revision_created": False}


async def delete_trainer_education(
    session: AsyncSession,
    trainer_id: int,
    education_id: int,
) -> bool | None:
    """
    Remove one education entry for the trainer.

    Returns None if trainer does not exist, False if no matching row, True after delete.
    """
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return None
    ok = await repo.delete_education_entry(trainer_id, education_id)
    if not ok:
        return False
    await repo.clear_moderation_submitted_at(trainer_id)
    await session.commit()
    await _demote_status_if_profile_incomplete(session, trainer_id)
    await reconcile_trainer_moderation_queue_if_incomplete(session, trainer_id)
    return True


async def moderate_trainer_education_for_profile(
    session: AsyncSession,
    trainer_id: int,
    *,
    decision: str,
    admin_id: int,
    reason: str | None = None,
) -> int:
    """
    Apply profile-level moderation decision to pending education entries.
    """
    normalized = (decision or "").strip().lower()
    if normalized not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    if normalized == "rejected" and not (reason or "").strip():
        raise ValueError("reason is required for rejected decision")
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return 0
    affected = await repo.moderate_pending_education_entries(
        trainer_id,
        decision=normalized,
        admin_id=admin_id,
        reason=reason,
    )
    await session.commit()
    return affected


async def upload_trainer_photo_from_bytes(
    session: AsyncSession,
    trainer_id: int,
    body: bytes,
    content_type: str,
) -> tuple[bool, str, str | None, str | None]:
    """
    Resize + S3/local (same as HTTP /api/upload/photo) + register_photo (single-photo policy).

    Returns (success, error_code, file_key, file_key_list). error_code is empty on success.
    On failure file_key and file_key_list are None. error_code: too_large | not_image | storage | not_found.
    """
    if len(body) > MAX_TRAINER_PHOTO_BYTES:
        return False, "too_large", None, None
    if not trainer_photo_bytes_look_like_image(body):
        return False, "not_image", None, None
    try:
        file_key, file_key_list = s3.upload_photo(trainer_id, body, content_type)
    except Exception:
        logger.exception("trainer photo storage upload failed trainer_id=%s", trainer_id)
        return False, "storage", None, None
    ok = await register_photo(session, trainer_id, file_key, 0, file_key_list=file_key_list)
    if not ok:
        return False, "not_found", None, None
    return True, "", file_key, file_key_list


async def upload_trainer_education_document_photo_from_bytes(
    session: AsyncSession,
    trainer_id: int,
    body: bytes,
    content_type: str,
) -> tuple[bool, str, str | None, str | None]:
    """
    Upload one education proof image to trainer storage namespace.

    Returns (success, error_code, file_key, file_key_list). error_code:
    too_large | not_image | storage | not_found.
    """
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False, "not_found", None, None
    if len(body) > MAX_TRAINER_PHOTO_BYTES:
        return False, "too_large", None, None
    if not trainer_photo_bytes_look_like_image(body):
        return False, "not_image", None, None
    try:
        file_key, file_key_list = s3.upload_photo(trainer_id, body, content_type)
    except Exception:
        logger.exception("education document storage upload failed trainer_id=%s", trainer_id)
        return False, "storage", None, None
    return True, "", file_key, file_key_list


async def register_photo(
    session: AsyncSession, trainer_id: int, file_key: str, sort_order: int = 0, file_key_list: str | None = None
) -> bool:
    """
    Attach photo to trainer (and optional list thumb).
    Active trainers: stage new keys in photo_pending; catalog keeps trainer_photos until moderation approves.
    Other statuses: single-photo policy replaces trainer_photos immediately.
    Returns False if trainer not found.
    Raises TrainerPhotoFileKeyError if storage keys do not belong to this trainer (IDOR guard).
    """
    if not photo_storage_keys_allowed_for_trainer(trainer_id, file_key, file_key_list):
        raise TrainerPhotoFileKeyError("file_key must be under trainers/{trainer_id}/")
    repo = TrainerRepository(session)
    if not await repo.exists(trainer_id):
        return False
    trainer = await get_trainer(session, trainer_id)
    st = (trainer.get("status") or "").strip() if trainer else ""
    if st == TRAINER_STATUS_ACTIVE:
        await repo.set_photo_pending(
            trainer_id,
            {"file_key": file_key, "file_key_list": file_key_list},
        )
        await repo.mark_queued_for_moderation_review(trainer_id)
        await session.commit()
        await reconcile_trainer_moderation_queue_if_incomplete(session, trainer_id)
        try:
            await notify_admins_trainer_queued_for_moderation(trainer_id)
        except Exception:  # noqa: BLE001
            logger.exception("notify admins after active photo pending failed trainer_id=%s", trainer_id)
        return True
    await repo.clear_photos(trainer_id)
    await repo.clear_moderation_submitted_at(trainer_id)
    await repo.add_photo(trainer_id, file_key, sort_order, file_key_list=file_key_list)
    await session.commit()
    await reconcile_trainer_moderation_queue_if_incomplete(session, trainer_id)
    return True
