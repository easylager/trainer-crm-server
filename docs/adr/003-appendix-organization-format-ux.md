# ADR 003 — Appendix: Organization format → UX contract

**Status:** Accepted (product contract)  
**Parent:** [ADR 003](./003-studio-schedule-modes-and-center-commerce.md)  
**Audience:** ops onboarding, pilots, frontend/backend without reading implementation  
**Source of truth in code:** `organization_capabilities.py` → `resolve_public_collective_capabilities()` / `resolve_organization_capabilities()`

---

## Canonical formats (3)

| `organization_format` | `schedule_mode` | Owner `studio_access_mode` | Trainer shell | Client catalog |
|----------------------|-----------------|------------------------------|---------------|----------------|
| **`studio`** | `member_autonomous` | `full_trainer` | Full tab bar + «Студия»: бренд, команда, invite, client link | `catalog_mode=studio_roster`, `hero_variant=studio` — roster тренеров → слоты |
| **`center`** | `studio_central` | `studio_admin_only` | Home + «Центр» only; без личного CRM | `catalog_mode=center_grid`, `hero_variant=center` — сетка центра → формат визита |
| **`center_hybrid`** | `studio_central` | `full_trainer` | Full tab bar + «Центр»; dual summary на home | `center_grid` + optional tab «Тренеры» (`show_coaches_catalog_tab=true`) |

**Aliases at draft time** (admin bot): `ice`, `white-label` → `studio`; `manager` → `center`. Stored value is always one of the three canonical keys.

---

## Public API contract (`GET /api/public/collectives/{slug}`)

Client catalog and bot landing **must not branch on `schedule_mode`**. Use capability fields:

| Field | Studio | Center | Center hybrid |
|-------|--------|--------|-----------------|
| `organization_format` | `studio` | `center` | `center_hybrid` |
| `catalog_mode` | `studio_roster` | `center_grid` | `center_grid` |
| `hero_variant` | `studio` | `center` | `center` |
| `show_coaches_catalog_tab` | `false` | `false` | `true` |

Legacy field `schedule_mode` remains in payload for migrations and admin tools only.

---

## Trainer mini-app by persona

| Persona | Studio | Center | Center hybrid |
|---------|--------|--------|---------------|
| **Owner (full)** | Бренд, команда, invite, client link, pool billing | + сетка, passes, inbox, delegate | Всё center + личный CRM (home, clients, schedule) |
| **Admin** | Бренд (per policy), команда | Сетка, passes, delegate, inbox | Как center admin |
| **Member-coach** | Client link + peers; свои слоты | Client link + «Мои смены»; без admin tabs | Client link + personal slots + duty |
| **`studio_admin_only` owner** | N/A | Только home + «Центр» | N/A |

Capability flags (hub bootstrap / studio payload): `show_personal_crm`, `show_center_grid`, `show_center_passes`, `show_team_invite`, `show_brand_edit`, `shell_nav_profile`, `collective_screen_title`, `organization_label`.

---

## Client surfaces

| Entry | Studio | Center / hybrid |
|-------|--------|-----------------|
| Bot `col_{slug}` | «Выберите тренера» → catalog roster | «Расписание центра» → center grid |
| Catalog `?collective=` | Hero studio; tab «Тренеры» | Hero center; primary tab «Расписание»; hybrid + tab «Тренеры» |
| Booking path | Trainer card → member slot | Session → attendance mode sheet |

---

## Admin onboarding (quick)

```text
/collective_draft ice-yoga|Ice Yoga Lane|studio
/collective_draft broski|Broski Center|center_hybrid|8
/collective_draft ops-desk|Ops Desk|center|8|manager
/collective_draft formats
/collective_draft help
```

After claim: owner opens trainer mini-app → format-specific first screen (studio brand vs center schedule tab).

---

## Related

- [ADR 001 — Collective overlay](./001-collective-overlay.md)
- [Organizations completion backlog](../../plans/organizations-completion-backlog.md) — execution checklist
- Implementation: `src/application/organization_capabilities.py`, `static/webapp/catalog-main.js`
