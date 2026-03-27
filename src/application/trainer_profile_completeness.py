"""
Single source of truth: when a trainer profile is complete enough to enter the admin moderation queue.

Product rules (strict — submit-for-moderation only when all of the below hold):
- Full name: non-empty first_name and last_name (trimmed).
- Age: present and > 0.
- Phone: non-empty (trimmed). Extra «contacts» (messengers, etc.) is optional.
- Short bio: description length >= MIN_DESCRIPTION_CHARS.
- Photo: at least one trainer_photos row with a non-empty file_key.
- City: city_id set.
- Education: non-empty profile.education text OR at least one trainer_education row
  (education_entries_count > 0 on the aggregate).
- Experience: experience_years set and >= 0.
- Session length: session_duration_minutes in [15, 240] (must be set in DB — no implicit default for gate).
- Booking window: min_hours_before_booking in [0, 168].
- At least one service and at least one arena (trainer_arenas).

Partial PATCH is allowed: profile may stay incomplete; moderation submission stays blocked until complete.

Computed from the same aggregate dict as get_trainer() / TrainerRepository.get_by_id — no DB flag.
"""
from __future__ import annotations

from typing import Any

from src.infrastructure.db.models import TRAINER_STATUS_PENDING_PROFILE

# Minimum visible "about me" text for moderation (characters after strip).
MIN_DESCRIPTION_CHARS = 25

# Stable keys for API, tests, and i18n.
MISSING_FIELD_LABELS_RU: dict[str, str] = {
    "full_name": "имя и фамилия",
    "age": "возраст",
    "phone": "телефон",
    "description": f"краткое описание (не менее {MIN_DESCRIPTION_CHARS} символов)",
    "photo": "фотография профиля (минимум одна)",
    "city": "город",
    "education": "образование (кратко в анкете или запись об образовании)",
    "experience_years": "опыт (лет)",
    "session_duration_minutes": "длительность занятия (мин)",
    "min_hours_before_booking": "за сколько часов до занятия клиент может записаться (8:00–22:00, Минск)",
    "services": "хотя бы одна услуга",
    "arenas": "хотя бы одна арена",
}


def analyze_moderation_profile_completeness(trainer: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Return (is_complete, missing_field_keys).
    `trainer` must match get_trainer shape: profile, photos, service_ids, arena_ids,
    and optional education_entries_count.
    """
    missing: list[str] = []
    profile = trainer.get("profile")
    if not isinstance(profile, dict):
        profile = {}

    fn = (profile.get("first_name") or "").strip()
    ln = (profile.get("last_name") or "").strip()
    if not fn or not ln:
        missing.append("full_name")

    age = profile.get("age")
    try:
        age_ok = age is not None and int(age) > 0
    except (TypeError, ValueError):
        age_ok = False
    if not age_ok:
        missing.append("age")

    phone = (profile.get("phone") or "").strip()
    if not phone:
        missing.append("phone")

    desc = (profile.get("description") or "").strip()
    if len(desc) < MIN_DESCRIPTION_CHARS:
        missing.append("description")

    photos = trainer.get("photos") or []
    valid = 0
    for p in photos:
        if isinstance(p, dict) and (p.get("file_key") or "").strip():
            valid += 1
    if valid < 1:
        missing.append("photo")

    if profile.get("city_id") is None:
        missing.append("city")

    edu_text = (profile.get("education") or "").strip()
    try:
        edu_cnt = int(trainer.get("education_entries_count") or 0)
    except (TypeError, ValueError):
        edu_cnt = 0
    if not edu_text and edu_cnt < 1:
        missing.append("education")

    exp = profile.get("experience_years")
    try:
        exp_ok = exp is not None and int(exp) >= 0
    except (TypeError, ValueError):
        exp_ok = False
    if not exp_ok:
        missing.append("experience_years")

    sd = profile.get("session_duration_minutes")
    try:
        sd_ok = sd is not None and 15 <= int(sd) <= 240
    except (TypeError, ValueError):
        sd_ok = False
    if not sd_ok:
        missing.append("session_duration_minutes")

    mh = profile.get("min_hours_before_booking")
    try:
        mh_ok = mh is not None and 0 <= int(mh) <= 168
    except (TypeError, ValueError):
        mh_ok = False
    if not mh_ok:
        missing.append("min_hours_before_booking")

    sids = trainer.get("service_ids")
    if not sids:
        missing.append("services")

    aids = trainer.get("arena_ids")
    if not aids:
        missing.append("arenas")

    return len(missing) == 0, missing


def is_profile_complete_for_moderation(trainer: dict[str, Any]) -> bool:
    ok, _ = analyze_moderation_profile_completeness(trainer)
    return ok


def missing_labels_ru(missing_keys: list[str]) -> list[str]:
    """Ordered human-readable list for UI (Russian, short)."""
    return [MISSING_FIELD_LABELS_RU[k] for k in missing_keys if k in MISSING_FIELD_LABELS_RU]


def moderation_readiness_dict(trainer: dict[str, Any], *, trainer_status: str | None = None) -> dict[str, Any]:
    """API / Mini App payload: completeness + optional status echo."""
    complete, missing = analyze_moderation_profile_completeness(trainer)
    out: dict[str, Any] = {
        "complete": complete,
        "missing_fields": missing,
        "missing_labels_ru": missing_labels_ru(missing),
    }
    if trainer_status is not None:
        out["trainer_status"] = trainer_status
    st = (trainer_status or "").strip()
    fb = trainer.get("moderation_feedback")
    fb_empty = fb is None or (isinstance(fb, str) and not str(fb).strip())
    sub_at = trainer.get("moderation_submitted_at")
    out["already_submitted_for_moderation"] = bool(
        st == TRAINER_STATUS_PENDING_PROFILE and complete and fb_empty and sub_at is not None
    )
    return out
