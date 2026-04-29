"""
Single source of truth: trainer profile completeness for moderation submit vs full dossier.

Two tiers (same aggregate shape as get_trainer() / TrainerRepository.get_by_id):

**A — Submission readiness (queue / submit-for-moderation):** 8 checks — all full-profile rules
except optional-for-submit fields: age, description, education, experience_years.

**B — Full profile (catalog trust / dossier):** 12 checks — strict «about the trainer» bar:
full name, age > 0, phone, bio length >= MIN_DESCRIPTION_CHARS, photo, city, education
(text or structured entries), experience_years >= 0, session length [15,240],
booking window [0,168], at least one service and one arena.

**C — TTV minimal (time-to-value):** 5 checks — identity + contacts + city + services + arenas;
enough to open schedule + trial booking in Mini App while status is still pending_profile
(no photo/bio/education/age/experience required). Session length and booking window stay in
«Настройки» with product defaults in API until the trainer adjusts them (full tier still validates).
Progressive profiling fills the rest toward tier A/B later.

Partial PATCH is allowed; submit stays blocked until tier A is satisfied.

Computed from the aggregate dict — no DB flag for completeness.
"""
from __future__ import annotations

from typing import Any

from src.infrastructure.db.models import TRAINER_STATUS_PENDING_PROFILE

# Minimum visible "about me" text for full-profile tier (characters after strip).
MIN_DESCRIPTION_CHARS = 25

# Distinct checks in analyze_moderation_profile_completeness (full dossier / catalog bar).
MODERATION_CRITERIA_TOTAL = 12

# Submission tier: full checks minus these keys (still validated in full tier).
SUBMIT_OPTIONAL_PROFILE_FIELD_KEYS: frozenset[str] = frozenset(
    {"age", "description", "education", "experience_years"}
)

MODERATION_SUBMISSION_CRITERIA_TOTAL = MODERATION_CRITERIA_TOTAL - len(SUBMIT_OPTIONAL_PROFILE_FIELD_KEYS)

# TTV gate: schedule + first booking before moderation (pending_profile only on access layer).
TT_MINIMAL_CRITERIA_TOTAL = 5

# Stable keys for API, tests, and i18n.
MISSING_FIELD_LABELS_RU: dict[str, str] = {
    "full_name": "имя и фамилия",
    "age": "возраст",
    "phone": "телефон",
    "description": f"краткое описание (не менее {MIN_DESCRIPTION_CHARS} символов)",
    "photo": "фотография профиля",
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
    Full-profile tier (12 criteria): dossier / catalog trust bar.

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


def analyze_tt_minimal_profile_readiness(trainer: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Minimal profile to unlock trainer Mini App schedule + bookings while pending_profile.

    Intentionally excludes: photo, long description, education text/entries, age, experience_years,
    session_duration_minutes, min_hours_before_booking (use defaults / settings; full tier still checks).
    """
    missing: list[str] = []
    profile = trainer.get("profile")
    if not isinstance(profile, dict):
        profile = {}

    fn = (profile.get("first_name") or "").strip()
    ln = (profile.get("last_name") or "").strip()
    if not fn or not ln:
        missing.append("full_name")

    phone = (profile.get("phone") or "").strip()
    if not phone:
        missing.append("phone")

    if profile.get("city_id") is None:
        missing.append("city")

    sids = trainer.get("service_ids")
    if not sids:
        missing.append("services")

    aids = trainer.get("arena_ids")
    if not aids:
        missing.append("arenas")

    return len(missing) == 0, missing


def is_tt_minimal_profile_complete(trainer: dict[str, Any]) -> bool:
    ok, _ = analyze_tt_minimal_profile_readiness(trainer)
    return ok


def analyze_moderation_submission_readiness(trainer: dict[str, Any]) -> tuple[bool, list[str]]:
    """Submission tier (8 criteria): enough to enter moderation queue, relaxed bio block."""
    _, full_missing = analyze_moderation_profile_completeness(trainer)
    submit_missing = [k for k in full_missing if k not in SUBMIT_OPTIONAL_PROFILE_FIELD_KEYS]
    return len(submit_missing) == 0, submit_missing


def is_ready_for_moderation_submission(trainer: dict[str, Any]) -> bool:
    ok, _ = analyze_moderation_submission_readiness(trainer)
    return ok


# Legacy name: same as submission tier (8 criteria). Keeps imports/bot reloads from breaking.
is_profile_complete_for_moderation = is_ready_for_moderation_submission


def missing_labels_ru(missing_keys: list[str]) -> list[str]:
    """Ordered human-readable list for UI (Russian, short)."""
    return [MISSING_FIELD_LABELS_RU[k] for k in missing_keys if k in MISSING_FIELD_LABELS_RU]


def moderation_readiness_dict(trainer: dict[str, Any], *, trainer_status: str | None = None) -> dict[str, Any]:
    """API / Mini App: submission tier in legacy keys; full tier in full_profile_* keys."""
    full_ok, full_missing = analyze_moderation_profile_completeness(trainer)
    submit_ok, submit_missing = analyze_moderation_submission_readiness(trainer)
    tt_ok, tt_missing = analyze_tt_minimal_profile_readiness(trainer)
    out: dict[str, Any] = {
        "complete": submit_ok,
        "missing_fields": submit_missing,
        "missing_labels_ru": missing_labels_ru(submit_missing),
        "moderation_criteria_total": MODERATION_SUBMISSION_CRITERIA_TOTAL,
        "full_profile_complete": full_ok,
        "full_profile_missing_fields": full_missing,
        "full_profile_missing_labels_ru": missing_labels_ru(full_missing),
        "full_profile_criteria_total": MODERATION_CRITERIA_TOTAL,
        "tt_minimal_complete": tt_ok,
        "tt_minimal_missing_fields": tt_missing,
        "tt_minimal_missing_labels_ru": missing_labels_ru(tt_missing),
        "tt_minimal_criteria_total": TT_MINIMAL_CRITERIA_TOTAL,
    }
    if trainer_status is not None:
        out["trainer_status"] = trainer_status
    st = (trainer_status or "").strip()
    fb = trainer.get("moderation_feedback")
    fb_empty = fb is None or (isinstance(fb, str) and not str(fb).strip())
    sub_at = trainer.get("moderation_submitted_at")
    out["already_submitted_for_moderation"] = bool(
        st == TRAINER_STATUS_PENDING_PROFILE and submit_ok and fb_empty and sub_at is not None
    )
    return out
