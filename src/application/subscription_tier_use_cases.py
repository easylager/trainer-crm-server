"""
Subscription: CRM base + independent modules (online, analytics, groups).

Legacy helpers tier_satisfies / get_effective_subscription_tier remain for display
and coarse checks; feature gates use trainer_has_*_access and get_trainer_entitlements.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import (
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_TRIAL,
    SUBSCRIPTION_TIER_ANALYTICS,
    SUBSCRIPTION_TIER_CRM,
    SUBSCRIPTION_TIER_LEVELS,
    SUBSCRIPTION_TIER_NONE,
    SUBSCRIPTION_TIER_ONLINE,
    SUBSCRIPTION_TIERS,
)


SubscriptionTier = Literal["none", "crm", "online", "analytics"]

# Billing periods (months) — must match DB CHECK and subscription_tier_period_pricing seed.
SUBSCRIPTION_BILLING_PERIOD_MONTHS: tuple[int, ...] = (1, 3, 12)

SUBSCRIPTION_MODULE_ONLINE = "online"
SUBSCRIPTION_MODULE_ANALYTICS = "analytics"
SUBSCRIPTION_MODULE_GROUPS = "groups"
SUBSCRIPTION_MODULES: tuple[str, ...] = (
    SUBSCRIPTION_MODULE_ONLINE,
    SUBSCRIPTION_MODULE_ANALYTICS,
    SUBSCRIPTION_MODULE_GROUPS,
)

# Human-readable Russian names for the CRM base + modules.
# Single source of truth — used by API status, bot messages, admin views.
SUBSCRIPTION_BASE_NAME_RU = "CRM"
SUBSCRIPTION_MODULE_NAMES_RU: dict[str, str] = {
    SUBSCRIPTION_MODULE_ONLINE: "Онлайн-запись",
    SUBSCRIPTION_MODULE_ANALYTICS: "Аналитика",
    SUBSCRIPTION_MODULE_GROUPS: "Группы",
}
SUBSCRIPTION_FULL_ACCESS_NAME_RU = "Полный доступ"


def default_modules_dict() -> dict[str, bool]:
    return {k: False for k in SUBSCRIPTION_MODULES}


async def ensure_trainer_profile_group_classes_when_groups_module(
    session: AsyncSession,
    trainer_id: int,
    modules: dict[str, bool] | None,
) -> None:
    """
    When entitlements include the groups add-on, turn on profile group_classes_enabled.
    Keeps UI/API aligned with paid modules (admin activation, checkout, mock payment, trial).
    """
    if not modules or not bool(modules.get(SUBSCRIPTION_MODULE_GROUPS)):
        return
    from src.infrastructure.repositories.trainer_repository import TrainerRepository

    repo = TrainerRepository(session)
    tid = int(trainer_id)
    await repo.ensure_trainer_profile_row(tid)
    await repo.update_profile(tid, group_classes_enabled=True)


def format_subscription_label(
    modules: Any,
    *,
    has_base_crm: bool = True,
    is_trial: bool = False,
) -> str:
    """
    Return one human-readable Russian name for any subscription state.

    Rules:
        - Trial → "Полный доступ" (trial always grants every module).
        - All three modules on → "Полный доступ".
        - No base / no access → "Без подписки".
        - CRM only (no modules on) → "CRM".
        - Otherwise → "CRM + …" composed from module display names.

    Used everywhere we show a tier label so trainers always see what they actually have.
    """
    if is_trial:
        return SUBSCRIPTION_FULL_ACCESS_NAME_RU
    if not has_base_crm:
        return "Без подписки"
    mods = normalize_modules_dict(modules) if modules is not None else default_modules_dict()
    on_modules = [k for k in SUBSCRIPTION_MODULES if mods.get(k)]
    if len(on_modules) == len(SUBSCRIPTION_MODULES):
        return SUBSCRIPTION_FULL_ACCESS_NAME_RU
    if not on_modules:
        return SUBSCRIPTION_BASE_NAME_RU
    parts = [SUBSCRIPTION_BASE_NAME_RU]
    for k in on_modules:
        parts.append(SUBSCRIPTION_MODULE_NAMES_RU.get(k, k))
    return " + ".join(parts)


def normalize_modules_dict(raw: Any) -> dict[str, bool]:
    """Merge JSON modules with defaults; unknown keys ignored."""
    out = default_modules_dict()
    if isinstance(raw, dict):
        for k in SUBSCRIPTION_MODULES:
            if k in raw and raw[k] is not None:
                out[k] = bool(raw[k])
    return out


def infer_modules_from_legacy_tier(tier: str | None) -> dict[str, bool]:
    """Pre-migration tier column → module flags (fallback)."""
    if tier == SUBSCRIPTION_TIER_ONLINE:
        d = default_modules_dict()
        d[SUBSCRIPTION_MODULE_ONLINE] = True
        return d
    if tier == SUBSCRIPTION_TIER_ANALYTICS:
        d = default_modules_dict()
        d[SUBSCRIPTION_MODULE_ONLINE] = True
        d[SUBSCRIPTION_MODULE_ANALYTICS] = True
        return d
    return default_modules_dict()


@dataclass
class TrainerEntitlements:
    """Resolved access for one trainer (active subscription row)."""

    has_base_crm: bool
    modules: dict[str, bool]
    raw_tier: str | None  # DB tier column (canonical crm after migration)


def unlocked_capability_codes(ent: TrainerEntitlements) -> list[str]:
    """Human-readable capability codes for API / menu (crm + enabled modules)."""
    if not ent.has_base_crm:
        return []
    codes: list[str] = ["crm"]
    for k in SUBSCRIPTION_MODULES:
        if ent.modules.get(k):
            codes.append(k)
    return codes


def tier_satisfies(current: SubscriptionTier, required: SubscriptionTier) -> bool:
    """
    Legacy linear comparison on synthetic effective tier (for tests / coarse UI).

    Prefer trainer_has_tier_access for real checks.
    """
    return SUBSCRIPTION_TIER_LEVELS.get(current, 0) >= SUBSCRIPTION_TIER_LEVELS.get(required, 0)


def tier_includes(tier: SubscriptionTier) -> list[str]:
    """Synthetic tier labels for backward-compatible display."""
    if tier == SUBSCRIPTION_TIER_ANALYTICS:
        return [SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS]
    if tier == SUBSCRIPTION_TIER_ONLINE:
        return [SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE]
    if tier == SUBSCRIPTION_TIER_CRM:
        return [SUBSCRIPTION_TIER_CRM]
    return []


async def get_trainer_entitlements(session: AsyncSession, trainer_id: int) -> TrainerEntitlements:
    """
    Resolve what the trainer has access to RIGHT NOW.

    Correctness rules (protect customer value):
        1. A row only grants access while started_at <= now < expires_at — future-dated paid
           rows queued after a trial must NOT activate early, and they must NOT mask trial
           entitlements.
        2. If multiple rows cover now (overlap), union their modules. We never downgrade
           access when a paid plan with fewer modules overlaps with a more generous one
           (e.g. trial with full access stacked with queued CRM-only paid plan).
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        text("""
            SELECT tier, modules
            FROM trainer_subscriptions
            WHERE trainer_id = :tid
              AND started_at <= :now
              AND expires_at > :now
              AND status IN (:s1, :s2)
              AND tier IS NOT NULL
        """),
        {
            "tid": trainer_id,
            "now": now,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    rows = result.fetchall()
    if not rows:
        return TrainerEntitlements(has_base_crm=False, modules=default_modules_dict(), raw_tier=None)
    union = default_modules_dict()
    any_raw_tier: str | None = None
    for row in rows:
        raw_tier = row[0]
        mods = normalize_modules_dict(row[1])
        if raw_tier in (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS) and not any(mods.values()):
            mods = infer_modules_from_legacy_tier(raw_tier)
        for k in SUBSCRIPTION_MODULES:
            if mods.get(k):
                union[k] = True
        any_raw_tier = any_raw_tier or raw_tier
    return TrainerEntitlements(has_base_crm=True, modules=union, raw_tier=any_raw_tier)


async def get_effective_subscription_tier(session: AsyncSession, trainer_id: int) -> SubscriptionTier:
    """
    Synthetic tier for menus / legacy code: analytics if analytics module, elif online, elif crm.
    """
    ent = await get_trainer_entitlements(session, trainer_id)
    if not ent.has_base_crm:
        return SUBSCRIPTION_TIER_NONE
    if ent.modules.get(SUBSCRIPTION_MODULE_ANALYTICS):
        return SUBSCRIPTION_TIER_ANALYTICS
    if ent.modules.get(SUBSCRIPTION_MODULE_ONLINE):
        return SUBSCRIPTION_TIER_ONLINE
    return SUBSCRIPTION_TIER_CRM


async def get_subscription_constructor_catalog(session: AsyncSession) -> dict[str, Any]:
    """
    CRM base (subscription_tier_pricing.crm) + module surcharges (subscription_module_period_pricing).
    """
    result = await session.execute(
        text("""
            SELECT tier, currency, name_ru, short_description_ru, bullets_json, display_order
            FROM subscription_tier_pricing
            WHERE is_active = true AND tier = :crm
        """),
        {"crm": SUBSCRIPTION_TIER_CRM},
    )
    base_row = result.fetchone()
    if not base_row:
        return {"base": None, "modules": []}

    result = await session.execute(
        text("""
            SELECT stpp.period_months, stpp.price_cents, stpp.period_days
            FROM subscription_tier_period_pricing stpp
            INNER JOIN subscription_tier_pricing stp ON stp.tier = stpp.tier
            WHERE stpp.tier = :crm AND stp.is_active = true
            ORDER BY stpp.period_months
        """),
        {"crm": SUBSCRIPTION_TIER_CRM},
    )
    base_prices: dict[str, int] = {}
    base_days: dict[str, int] = {}
    for pm, cents, days in result.fetchall():
        k = str(int(pm))
        base_prices[k] = cents
        base_days[k] = days

    base = {
        "tier": SUBSCRIPTION_TIER_CRM,
        "currency": base_row[1],
        "name_ru": base_row[2],
        "short_description_ru": base_row[3],
        "bullets": base_row[4] or [],
        "display_order": base_row[5],
        "prices_by_period": base_prices,
        "period_days_by_period": base_days,
    }

    result = await session.execute(
        text("""
            SELECT module, period_months, price_cents, period_days, currency, name_ru
            FROM subscription_module_period_pricing
            ORDER BY module, period_months
        """)
    )
    by_mod: dict[str, dict[str, Any]] = {}
    for mod, pm, cents, days, cur, name_ru in result.fetchall():
        m = by_mod.setdefault(
            mod,
            {
                "code": mod,
                "currency": cur,
                "name_ru": name_ru,
                "prices_by_period": {},
                "period_days_by_period": {},
            },
        )
        m["prices_by_period"][str(int(pm))] = cents
        m["period_days_by_period"][str(int(pm))] = days

    # Constructor UI order: online → analytics → groups (not alphabetical from SQL).
    order_index = {code: i for i, code in enumerate(SUBSCRIPTION_MODULES)}
    modules_sorted = sorted(
        by_mod.values(),
        key=lambda item: order_index.get(str(item.get("code") or ""), len(SUBSCRIPTION_MODULES)),
    )
    return {"base": base, "modules": modules_sorted}


async def get_subscription_tier_catalog(session: AsyncSession) -> list[dict]:
    """
    Backward-compatible: three legacy tier cards built from constructor (crm-only, crm+online, crm+online+analytics).
    """
    ctor = await get_subscription_constructor_catalog(session)
    base = ctor.get("base")
    mod_list = ctor.get("modules") or []
    if not base:
        return []

    def _mod_prices(code: str) -> dict[str, int]:
        for m in mod_list:
            if m.get("code") == code:
                return dict(m.get("prices_by_period") or {})
        return {}

    def _sum_periods(*price_maps: dict[str, int]) -> dict[str, int]:
        keys = set()
        for pm in price_maps:
            keys |= set(pm.keys())
        out: dict[str, int] = {}
        for k in keys:
            out[k] = sum(int(pm.get(k, 0)) for pm in price_maps)
        return out

    base_p = base.get("prices_by_period") or {}
    on_p = _mod_prices(SUBSCRIPTION_MODULE_ONLINE)
    an_p = _mod_prices(SUBSCRIPTION_MODULE_ANALYTICS)
    base_days = base.get("period_days_by_period") or {}

    crm_only = {
        "tier": SUBSCRIPTION_TIER_CRM,
        "currency": base["currency"],
        "name_ru": base["name_ru"],
        "short_description_ru": base["short_description_ru"],
        "bullets": base["bullets"],
        "display_order": 1,
        "includes_tiers": [SUBSCRIPTION_TIER_CRM],
        "prices_by_period": dict(base_p),
        "period_days_by_period": dict(base_days),
        "modules": default_modules_dict(),
    }
    online_bundle = {
        "tier": SUBSCRIPTION_TIER_ONLINE,
        "currency": base["currency"],
        "name_ru": "CRM + онлайн-запись",
        "short_description_ru": "База и самозапись клиентов в каталоге",
        "bullets": base["bullets"] + ["Онлайн-запись в каталоге"],
        "display_order": 2,
        "includes_tiers": [SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE],
        "prices_by_period": _sum_periods(base_p, on_p),
        "period_days_by_period": dict(base_days),
        "modules": {**default_modules_dict(), SUBSCRIPTION_MODULE_ONLINE: True},
    }
    analytics_bundle = {
        "tier": SUBSCRIPTION_TIER_ANALYTICS,
        "currency": base["currency"],
        "name_ru": "CRM + онлайн + аналитика",
        "short_description_ru": "Как прежний тариф «Аналитика» (онлайн + отчёты)",
        "bullets": (base["bullets"] or []) + ["Онлайн-запись", "Аналитика и отчёты"],
        "display_order": 3,
        "includes_tiers": [SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS],
        "prices_by_period": _sum_periods(base_p, on_p, an_p),
        "period_days_by_period": dict(base_days),
        "modules": {
            **default_modules_dict(),
            SUBSCRIPTION_MODULE_ONLINE: True,
            SUBSCRIPTION_MODULE_ANALYTICS: True,
        },
    }
    return [crm_only, online_bundle, analytics_bundle]


async def _infer_billing_period_months(
    session: AsyncSession,
    tier: str,
    started_at: datetime,
    expires_at: datetime,
) -> int | None:
    """Map segment length to catalog period_months when legacy rows lack billing_period_months."""
    if tier not in SUBSCRIPTION_TIERS:
        return None
    days = max(0, int((expires_at - started_at).total_seconds() // 86400))
    result = await session.execute(
        text("""
            SELECT period_months
            FROM subscription_tier_period_pricing
            WHERE tier = :tier AND ABS(period_days - :days) <= 2
            ORDER BY ABS(period_days - :days) ASC
            LIMIT 1
        """),
        {"tier": tier, "days": days},
    )
    r = result.fetchone()
    return int(r[0]) if r else None


async def get_trainer_subscription_status(session: AsyncSession, trainer_id: int) -> dict:
    """
    Trainer's current subscription status for UI.

    Contract — protects customer value by reporting:
        - The row that actually covers NOW (trial preferred if multiple rows overlap).
        - `modules` / `unlocked_features` as the UNION across all rows covering NOW
          (so a remaining trial day always shows full access even when a queued
          CRM-only paid plan is already persisted).
        - `next_plan` describing the queued paid subscription that will kick in after
          the current window, so the UI can tell the trainer "trial until X, then
          your CRM plan until Y" in one glance.
    """
    tier = await get_effective_subscription_tier(session, trainer_id)
    ent = await get_trainer_entitlements(session, trainer_id)
    now = datetime.now(timezone.utc)

    # All currently-active rows (row covers now: started_at <= now < expires_at).
    current_rows_result = await session.execute(
        text("""
            SELECT ts.id, ts.tier, ts.modules, ts.expires_at, ts.status, ts.started_at,
                   ts.billing_period_months
            FROM trainer_subscriptions ts
            WHERE ts.trainer_id = :tid
              AND ts.started_at <= :now
              AND ts.expires_at > :now
              AND ts.status IN (:s1, :s2)
            ORDER BY
                CASE WHEN ts.status = :s1 THEN 0 ELSE 1 END,  -- trial first (most generous)
                ts.expires_at DESC
        """),
        {
            "tid": trainer_id,
            "now": now,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    current_rows = current_rows_result.fetchall()

    # Queued rows: already persisted but start in the future (e.g. paid plan that kicks
    # in after the current trial ends). Used for UI hints, not for entitlements.
    next_row_result = await session.execute(
        text("""
            SELECT ts.id, ts.tier, ts.modules, ts.expires_at, ts.status, ts.started_at,
                   ts.billing_period_months
            FROM trainer_subscriptions ts
            WHERE ts.trainer_id = :tid
              AND ts.started_at > :now
              AND ts.status IN (:s1, :s2)
            ORDER BY ts.started_at ASC
            LIMIT 1
        """),
        {
            "tid": trainer_id,
            "now": now,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    next_row = next_row_result.fetchone()

    next_plan: dict | None = None
    if next_row:
        nx_tier = next_row[1] or SUBSCRIPTION_TIER_CRM
        nx_mods = normalize_modules_dict(next_row[2])
        if nx_tier in (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS) and not any(nx_mods.values()):
            nx_mods = infer_modules_from_legacy_tier(nx_tier)
        next_plan = {
            "subscription_id": next_row[0],
            "tier": nx_tier,
            "modules": nx_mods,
            "started_at": next_row[5].isoformat() if next_row[5] else None,
            "expires_at": next_row[3].isoformat() if next_row[3] else None,
            "status": next_row[4],
            "is_trial": next_row[4] == SUBSCRIPTION_STATUS_TRIAL,
            "tier_name_ru": format_subscription_label(
                nx_mods,
                has_base_crm=True,
                is_trial=next_row[4] == SUBSCRIPTION_STATUS_TRIAL,
            ),
            "billing_period_months": int(next_row[6]) if next_row[6] is not None else None,
        }

    if current_rows:
        # Primary row for display (trial preferred, then latest expiry).
        primary = current_rows[0]
        row_tier = primary[1] or tier
        primary_mods = normalize_modules_dict(primary[2])
        if row_tier in (SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS) and not any(primary_mods.values()):
            primary_mods = infer_modules_from_legacy_tier(row_tier)
        expires_at = primary[3]
        sub_status = primary[4]
        started_at = primary[5]
        stored_pm = primary[6]
        billing_pm: int | None = int(stored_pm) if stored_pm is not None else None
        if billing_pm is None and row_tier and expires_at and started_at:
            billing_pm = await _infer_billing_period_months(session, row_tier, started_at, expires_at)
        is_trial = sub_status == SUBSCRIPTION_STATUS_TRIAL
        # Unified entitlements across ALL rows covering now — the trainer's effective access.
        # Label is composed from this union so we never downgrade during an overlap.
        tier_name_ru: str = format_subscription_label(
            ent.modules,
            has_base_crm=ent.has_base_crm,
            is_trial=is_trial,
        )
        caps = unlocked_capability_codes(ent)
        return {
            "subscription_id": primary[0],
            "tier": row_tier,
            "effective_tier": tier,
            # Modules reported to clients are the UNION — the trainer's real access today.
            "modules": ent.modules,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "status": sub_status,
            "is_trial": is_trial,
            "tier_name_ru": tier_name_ru,
            "started_at": started_at.isoformat() if started_at else None,
            "billing_period_months": billing_pm,
            "is_active": True,
            "unlocked_features": caps,
            "next_plan": next_plan,
        }

    return {
        "subscription_id": None,
        "tier": SUBSCRIPTION_TIER_NONE,
        "effective_tier": SUBSCRIPTION_TIER_NONE,
        "modules": default_modules_dict(),
        "expires_at": None,
        "status": None,
        "is_trial": False,
        "tier_name_ru": None,
        "started_at": None,
        "billing_period_months": None,
        "is_active": False,
        "unlocked_features": [],
        "next_plan": next_plan,
    }


async def get_tier_period_pricing(
    session: AsyncSession,
    tier: SubscriptionTier,
    period_months: int,
) -> dict | None:
    """Return price and renewal length for (tier, billing period). Server is source of truth for checkout."""
    if period_months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        return None
    result = await session.execute(
        text("""
            SELECT stpp.price_cents, stp.currency, stpp.period_days, stp.name_ru
            FROM subscription_tier_period_pricing stpp
            INNER JOIN subscription_tier_pricing stp ON stp.tier = stpp.tier
            WHERE stpp.tier = :tier
              AND stpp.period_months = :pm
              AND stp.is_active = true
        """),
        {"tier": tier, "pm": period_months},
    )
    row = result.fetchone()
    if not row:
        return None
    return {
        "price_cents": row[0],
        "currency": row[1],
        "period_days": row[2],
        "name_ru": row[3],
    }


async def get_module_period_pricing(
    session: AsyncSession,
    module: str,
    period_months: int,
) -> dict | None:
    """Surcharge for one module (online / analytics / groups)."""
    if module not in SUBSCRIPTION_MODULES or period_months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        return None
    result = await session.execute(
        text("""
            SELECT price_cents, period_days, currency, name_ru
            FROM subscription_module_period_pricing
            WHERE module = :m AND period_months = :pm
        """),
        {"m": module, "pm": period_months},
    )
    row = result.fetchone()
    if not row:
        return None
    return {
        "price_cents": row[0],
        "period_days": row[1],
        "currency": row[2],
        "name_ru": row[3],
    }


async def set_subscription_constructor_after_mock_payment(
    session: AsyncSession,
    trainer_id: int,
    modules: dict[str, bool],
    period_months: int,
) -> dict | None:
    """
    Activate CRM + selected modules after mock payment.

    Canonical row: tier='crm', modules JSONB. Total price = CRM base + enabled module surcharges.
    """
    if period_months not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
        return None
    mods = normalize_modules_dict(modules)
    base = await get_tier_period_pricing(session, SUBSCRIPTION_TIER_CRM, period_months)
    if not base:
        return None
    total_cents = int(base["price_cents"])
    period_days = int(base["period_days"])
    currency = base["currency"]
    for key in SUBSCRIPTION_MODULES:
        if not mods.get(key):
            continue
        mp = await get_module_period_pricing(session, key, period_months)
        if not mp:
            return None
        total_cents += int(mp["price_cents"])

    now = datetime.now(timezone.utc)
    result = await session.execute(
        text("""
            SELECT expires_at FROM trainer_subscriptions
            WHERE trainer_id = :tid
              AND expires_at > :now
              AND status IN (:s1, :s2)
            ORDER BY expires_at DESC
            LIMIT 1
        """),
        {
            "tid": trainer_id,
            "now": now,
            "s1": SUBSCRIPTION_STATUS_TRIAL,
            "s2": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    row = result.fetchone()
    started_at = row[0] if row and row[0] > now else now
    expires_at = started_at + timedelta(days=period_days)

    plan_result = await session.execute(
        text("SELECT id FROM subscription_plans WHERE is_trial = false ORDER BY sort_order LIMIT 1")
    )
    plan_row = plan_result.fetchone()
    plan_id = plan_row[0] if plan_row else 1

    mods_json = json.dumps(mods, ensure_ascii=False)
    result = await session.execute(
        text("""
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, tier, modules, billing_period_months, started_at, expires_at, status)
            VALUES
                (:tid, :pid, :tier, CAST(:mods AS jsonb), :bpm, :started_at, :expires_at, :status)
            RETURNING id, started_at, expires_at
        """),
        {
            "tid": trainer_id,
            "pid": plan_id,
            "tier": SUBSCRIPTION_TIER_CRM,
            "mods": mods_json,
            "bpm": period_months,
            "started_at": started_at,
            "expires_at": expires_at,
            "status": SUBSCRIPTION_STATUS_ACTIVE,
        },
    )
    row = result.fetchone()
    await ensure_trainer_profile_group_classes_when_groups_module(session, trainer_id, mods)
    await session.commit()

    return {
        "subscription_id": row[0],
        "tier": SUBSCRIPTION_TIER_CRM,
        "modules": mods,
        "started_at": row[1].isoformat(),
        "expires_at": row[2].isoformat(),
        "price_cents": total_cents,
        "currency": currency,
        "period_days": period_days,
        "period_months": period_months,
    }


async def set_subscription_after_mock_payment(
    session: AsyncSession,
    trainer_id: int,
    tier: SubscriptionTier,
    period_months: int,
) -> dict | None:
    """Legacy: map old tier bundles to module flags."""
    if tier not in (SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE, SUBSCRIPTION_TIER_ANALYTICS):
        return None
    mods = default_modules_dict()
    if tier == SUBSCRIPTION_TIER_ONLINE:
        mods[SUBSCRIPTION_MODULE_ONLINE] = True
    elif tier == SUBSCRIPTION_TIER_ANALYTICS:
        mods[SUBSCRIPTION_MODULE_ONLINE] = True
        mods[SUBSCRIPTION_MODULE_ANALYTICS] = True
    return await set_subscription_constructor_after_mock_payment(session, trainer_id, mods, period_months)


async def trainer_has_tier_access(
    session: AsyncSession,
    trainer_id: int,
    required_tier: SubscriptionTier,
) -> bool:
    """
    Feature gate aligned with modules: 'crm' = base; 'online'/'analytics' = module flags
    (analytics does not imply online).
    """
    if required_tier == SUBSCRIPTION_TIER_NONE:
        return True
    ent = await get_trainer_entitlements(session, trainer_id)
    if not ent.has_base_crm:
        return False
    if required_tier == SUBSCRIPTION_TIER_CRM:
        return True
    if required_tier == SUBSCRIPTION_TIER_ONLINE:
        return bool(ent.modules.get(SUBSCRIPTION_MODULE_ONLINE))
    if required_tier == SUBSCRIPTION_TIER_ANALYTICS:
        return bool(ent.modules.get(SUBSCRIPTION_MODULE_ANALYTICS))
    return False


async def trainer_allows_online_booking(session: AsyncSession, trainer_id: int) -> bool:
    """Catalog self-booking requires CRM base + online module."""
    ent = await get_trainer_entitlements(session, trainer_id)
    return ent.has_base_crm and bool(ent.modules.get(SUBSCRIPTION_MODULE_ONLINE))


async def trainer_has_crm_access(session: AsyncSession, trainer_id: int) -> bool:
    """Active subscription with CRM base (any paid/trial row)."""
    ent = await get_trainer_entitlements(session, trainer_id)
    return ent.has_base_crm


async def trainer_has_analytics_access(session: AsyncSession, trainer_id: int) -> bool:
    ent = await get_trainer_entitlements(session, trainer_id)
    return ent.has_base_crm and bool(ent.modules.get(SUBSCRIPTION_MODULE_ANALYTICS))


async def trainer_has_groups_access(session: AsyncSession, trainer_id: int) -> bool:
    ent = await get_trainer_entitlements(session, trainer_id)
    return ent.has_base_crm and bool(ent.modules.get(SUBSCRIPTION_MODULE_GROUPS))


async def get_trainer_booking_availability(session: AsyncSession, trainer_id: int) -> dict:
    """
    Get trainer's booking availability info for catalog display.

    Returns:
        - can_book: True if CRM + online module
        - tier: synthetic effective tier (legacy display)
        - reason: explanation if can_book is False
    """
    tier = await get_effective_subscription_tier(session, trainer_id)
    can_book = await trainer_allows_online_booking(session, trainer_id)

    if can_book:
        return {"can_book": True, "tier": tier, "reason": None}

    if tier == SUBSCRIPTION_TIER_NONE:
        reason = "no_subscription"
    elif not await trainer_has_crm_access(session, trainer_id):
        reason = "no_subscription"
    else:
        reason = "crm_only"

    return {"can_book": False, "tier": tier, "reason": reason}


# --- Admin functions for tier pricing management ---


async def _fetch_period_prices_for_tier(session: AsyncSession, tier: str) -> list[dict]:
    """Rows from subscription_tier_period_pricing for one tier."""
    result = await session.execute(
        text("""
            SELECT id, period_months, price_cents, period_days
            FROM subscription_tier_period_pricing
            WHERE tier = :tier
            ORDER BY period_months
        """),
        {"tier": tier},
    )
    return [
        {"id": r[0], "period_months": r[1], "price_cents": r[2], "period_days": r[3]}
        for r in result.fetchall()
    ]


def _tier_pricing_row_to_admin_dict(row, period_prices: list[dict]) -> dict:
    """Map DB row + period matrix to admin API dict (includes inactive tiers)."""
    p1 = next((p["price_cents"] for p in period_prices if p["period_months"] == 1), row[2])
    return {
        "id": row[0],
        "tier": row[1],
        "price_cents": p1,
        "currency": row[3],
        "period_days": row[4],
        "name_ru": row[5],
        "short_description_ru": row[6],
        "bullets": row[7] or [],
        "display_order": row[8],
        "is_active": row[9],
        "created_at": row[10].isoformat() if row[10] else None,
        "updated_at": row[11].isoformat() if row[11] else None,
        "period_prices": period_prices,
    }


async def fetch_tier_pricing_for_admin(session: AsyncSession, tier: str) -> dict | None:
    """Single tier row for admin, including when is_active is false."""
    result = await session.execute(
        text("""
            SELECT
                id, tier, price_cents, currency, period_days,
                name_ru, short_description_ru, bullets_json,
                display_order, is_active, created_at, updated_at
            FROM subscription_tier_pricing
            WHERE tier = :tier
        """),
        {"tier": tier},
    )
    row = result.fetchone()
    if not row:
        return None
    period_prices = await _fetch_period_prices_for_tier(session, tier)
    return _tier_pricing_row_to_admin_dict(row, period_prices)


async def list_subscription_tier_pricing_for_admin(session: AsyncSession) -> list[dict]:
    """Get all tier pricing records for admin editing (including inactive)."""
    result = await session.execute(
        text("""
            SELECT
                id, tier, price_cents, currency, period_days,
                name_ru, short_description_ru, bullets_json,
                display_order, is_active, created_at, updated_at
            FROM subscription_tier_pricing
            ORDER BY display_order ASC
        """)
    )
    rows = result.fetchall()
    out: list[dict] = []
    for row in rows:
        tier = row[1]
        period_prices = await _fetch_period_prices_for_tier(session, tier)
        out.append(_tier_pricing_row_to_admin_dict(row, period_prices))
    return out


async def update_subscription_tier_pricing(
    session: AsyncSession,
    tier: str,
    admin_telegram_id: int | None,
    *,
    period_prices: dict[str, int] | None = None,
    name_ru: str | None = None,
    short_description_ru: str | None = None,
    bullets: list[str] | None = None,
    display_order: int | None = None,
    is_active: bool | None = None,
) -> dict | None:
    """
    Update tier metadata and/or per-period prices. Changes are logged to audit tables.

    Returns updated record or None if tier not found.
    """
    result = await session.execute(
        text("""
            SELECT id, price_cents, period_days, name_ru, short_description_ru,
                   bullets_json, display_order, is_active
            FROM subscription_tier_pricing
            WHERE tier = :tier
        """),
        {"tier": tier},
    )
    row = result.fetchone()
    if not row:
        return None

    tier_pricing_id = row[0]
    old_values = {
        "price_cents": row[1],
        "period_days": row[2],
        "name_ru": row[3],
        "short_description_ru": row[4],
        "bullets": row[5],
        "display_order": row[6],
        "is_active": row[7],
    }

    updates = []
    params: dict = {"tier": tier}
    changed_fields: dict = {}

    if name_ru is not None and name_ru != old_values["name_ru"]:
        updates.append("name_ru = :name_ru")
        params["name_ru"] = name_ru
        changed_fields["name_ru"] = {"old": old_values["name_ru"], "new": name_ru}

    if short_description_ru is not None and short_description_ru != old_values["short_description_ru"]:
        updates.append("short_description_ru = :short_description_ru")
        params["short_description_ru"] = short_description_ru
        changed_fields["short_description_ru"] = {
            "old": old_values["short_description_ru"],
            "new": short_description_ru,
        }

    if bullets is not None and bullets != old_values["bullets"]:
        updates.append("bullets_json = :bullets_json")
        params["bullets_json"] = bullets
        changed_fields["bullets"] = {"old": old_values["bullets"], "new": bullets}

    if display_order is not None and display_order != old_values["display_order"]:
        updates.append("display_order = :display_order")
        params["display_order"] = display_order
        changed_fields["display_order"] = {"old": old_values["display_order"], "new": display_order}

    if is_active is not None and is_active != old_values["is_active"]:
        updates.append("is_active = :is_active")
        params["is_active"] = is_active
        changed_fields["is_active"] = {"old": old_values["is_active"], "new": is_active}

    period_changed = False
    if period_prices:
        for key, new_cents in period_prices.items():
            try:
                pm = int(key)
            except (TypeError, ValueError):
                continue
            if pm not in SUBSCRIPTION_BILLING_PERIOD_MONTHS:
                continue
            if new_cents < 0:
                continue
            cur = await session.execute(
                text("""
                    SELECT id, price_cents FROM subscription_tier_period_pricing
                    WHERE tier = :tier AND period_months = :pm
                """),
                {"tier": tier, "pm": pm},
            )
            crow = cur.fetchone()
            if not crow or crow[1] == new_cents:
                continue
            row_id = crow[0]
            old_cents = crow[1]
            await session.execute(
                text("""
                    UPDATE subscription_tier_period_pricing
                    SET price_cents = :pc, updated_at = NOW()
                    WHERE id = :id
                """),
                {"pc": new_cents, "id": row_id},
            )
            period_changed = True
            audit_payload = {
                "tier": tier,
                "period_months": pm,
                "price_cents": {"old": old_cents, "new": new_cents},
            }
            await session.execute(
                text("""
                    INSERT INTO subscription_tier_period_pricing_audit
                        (tier_period_pricing_id, admin_telegram_id, changed_fields)
                    VALUES (:tid, :admin_tid, CAST(:changed AS jsonb))
                """),
                {
                    "tid": row_id,
                    "admin_tid": admin_telegram_id,
                    "changed": json.dumps(audit_payload),
                },
            )

    if not updates and not period_changed:
        return await fetch_tier_pricing_for_admin(session, tier)

    if updates:
        updates.append("updated_at = NOW()")
        await session.execute(
            text(f"UPDATE subscription_tier_pricing SET {', '.join(updates)} WHERE tier = :tier"),
            params,
        )
        if changed_fields:
            await session.execute(
                text("""
                    INSERT INTO subscription_tier_pricing_audit
                        (tier_pricing_id, admin_telegram_id, changed_fields)
                    VALUES (:tid, :admin_tid, CAST(:changed AS jsonb))
                """),
                {
                    "tid": tier_pricing_id,
                    "admin_tid": admin_telegram_id,
                    "changed": json.dumps(changed_fields),
                },
            )

    await session.commit()
    return await fetch_tier_pricing_for_admin(session, tier)
