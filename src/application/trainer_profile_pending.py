"""
Published vs pending profile text for active trainers.

Catalog and public API use trainer_profiles (published). Edits from active trainers
merge into trainers.profile_pending until admin approves.
"""
from __future__ import annotations

from typing import Any

from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE

# Active trainers: only these edits queue a text revision (profile_pending + admin notify).
# Age, phone, city, session rules, etc. apply to the published row immediately (no moderation).
ACTIVE_TRAINER_REVISION_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "first_name",
        "last_name",
        "description",
        "experience_years",
    }
)

# Keys allowed when merging profile_pending JSON into trainer_profiles (apply on admin approve).
PROFILE_KEYS_FOR_PUBLISHED_UPDATE: frozenset[str] = frozenset(
    {
        "first_name",
        "last_name",
        "age",
        "city_id",
        "experience_years",
        "description",
        "phone",
        "contacts",
        "education",
        "session_duration_minutes",
        "min_hours_before_booking",
    }
)

_TRAINER_PROFILE_REPO_KEYS: frozenset[str] = frozenset(
    {
        "first_name",
        "last_name",
        "age",
        "city_id",
        "experience_years",
        "description",
        "phone",
        "contacts",
        "education",
        "session_duration_minutes",
        "min_hours_before_booking",
    }
)


def merge_profile_pending_for_editor(published: dict | None, pending: dict | None) -> dict | None:
    """Editor view: published row + pending overrides."""
    if not published:
        return None
    if not pending:
        return dict(published)
    out = dict(published)
    for k, v in pending.items():
        if v is not None:
            out[k] = v
    return out


def split_active_trainer_profile_patch(
    profile_patch: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    For status=active: (revision_pending_patch, immediate_published_patch).
    Revision fields wait for admin approval; other profile columns update catalog immediately.
    """
    rev: dict[str, Any] = {}
    direct: dict[str, Any] = {}
    for k, v in profile_patch.items():
        if v is None:
            continue
        if k in ACTIVE_TRAINER_REVISION_FIELD_KEYS:
            rev[k] = v
        elif k in _TRAINER_PROFILE_REPO_KEYS:
            direct[k] = v
    return rev, direct


def _revision_field_unchanged(cur: Any, new: Any) -> bool:
    if cur == new:
        return True
    if isinstance(cur, str) and isinstance(new, str):
        return cur.strip() == new.strip()
    return False


def active_trainer_revision_diff(
    trainer: dict[str, Any],
    revision_patch: dict[str, Any],
) -> dict[str, Any]:
    """
    Drop revision keys that match the current editor view (published + profile_pending).
    Stops re-queuing moderation when the client resends unchanged name/description on services-only saves.
    """
    if not revision_patch:
        return {}
    pub = trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {}
    pen = trainer.get("profile_pending") if isinstance(trainer.get("profile_pending"), dict) else None
    merged = merge_profile_pending_for_editor(pub, pen) or {}
    out: dict[str, Any] = {}
    for k, v in revision_patch.items():
        if _revision_field_unchanged(merged.get(k), v):
            continue
        out[k] = v
    return out


def merge_pending_dict(existing: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge patch into existing pending snapshot."""
    base = dict(existing) if existing else {}
    base.update(patch)
    return base


def trainer_has_pending_text_revision(trainer: dict[str, Any]) -> bool:
    pp = trainer.get("profile_pending")
    return isinstance(pp, dict) and len(pp) > 0


def trainer_has_photo_pending_revision(trainer: dict[str, Any]) -> bool:
    pp = trainer.get("photo_pending")
    if not isinstance(pp, dict):
        return False
    fk = (pp.get("file_key") or "").strip()
    return bool(fk)


def trainer_photo_file_key_for_moderation_ui(trainer: dict[str, Any]) -> str | None:
    """Prefer staged photo for admin card / notify; else published trainer_photos."""
    pp = trainer.get("photo_pending")
    if isinstance(pp, dict):
        fk = (pp.get("file_key") or "").strip() or (pp.get("file_key_list") or "").strip()
        if fk:
            return fk
    photos = trainer.get("photos") or []
    if photos and isinstance(photos[0], dict):
        return ((photos[0].get("file_key") or "").strip() or (photos[0].get("file_key_list") or "").strip()) or None
    return None


def should_show_merged_profile_in_moderation_card(trainer: dict[str, Any]) -> bool:
    st = (trainer.get("status") or "").strip()
    return st == TRAINER_STATUS_ACTIVE and trainer_has_pending_text_revision(trainer)


def build_trainer_profile_for_moderation_card(trainer: dict[str, Any]) -> dict[str, Any]:
    """Trainer dict with profile = merged when active + profile_pending (for admin caption)."""
    if not should_show_merged_profile_in_moderation_card(trainer):
        return trainer
    out = dict(trainer)
    pub = trainer.get("profile") or {}
    pen = trainer.get("profile_pending") or {}
    out["profile"] = merge_profile_pending_for_editor(pub if isinstance(pub, dict) else {}, pen)
    return out
