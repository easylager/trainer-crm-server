# ADR 003: Studio schedule modes, center commerce, multi-collective

**Status:** Accepted  
**Date:** 2026-06-12  
**Decisions locked:** 2026-06-12 (Q1–Q4 below)
**Supersedes / amends:** [ADR 001](./001-collective-overlay.md) (invariants §4, partial §1)  
**Depends on:** ADR 001 (Collective overlay foundation)

## Context

Two pilot businesses require different operating models on the same platform:

| Pilot | Model | Schedule | Passes / prices |
|-------|--------|----------|-----------------|
| **Ice skating studio** | White-label collective | Each member sets own slots | Per-trainer (today) |
| **Throwing center** | Operator-led facility | Admin sets center grid; coaches keep personal slots | **Center** sets tariffs and sells passes |

Additionally, a coach may work in **both** collectives (and solo personal practice). They need **one merged calendar** and the ability to book clients into either context. Admins must coordinate bookings across contexts.

**Product decisions confirmed:**

- Guest surcharge on lane visit: **+15 BYN on top** (not included in pass visit; does not consume an extra visit).
- Client may visit center: alone, with guest, with own external coach, or with an **assigned** center coach (not any roster coach).
- Center coach assignment is done by admin on upcoming sessions.
- Coaches retain independent personal schedules in parallel with center grid.

**Non-goal:** a separate Telegram bot or second CRM product. Client bot + trainer bot stay; behavior adapts by `collective.schedule_mode` and membership context.

---

## Decision

### 1. Schedule modes (per collective)

Add `collectives.schedule_mode`:

| Value | Use case | Who creates bookable time |
|-------|----------|---------------------------|
| `member_autonomous` | Ice skating white-label | Each member → own `slots.trainer_id` |
| `studio_central` | Throwing center | Admin → `collective_sessions`; members may also own personal `slots` |

Default for new collectives without explicit mode: `member_autonomous` (preserves ADR 001 behavior).

Client landing (`?collective=` / `col_*`) branches on `schedule_mode`:

- **member_autonomous:** trainer roster → trainer slots (current catalog path).
- **studio_central:** center schedule first; optional «Coaches» tab for personal coach slots.

---

### 2. Center grid (`studio_central`)

New entity **`collective_sessions`** (name may be `collective_session_occurrences` in schema):

| Field | Purpose |
|-------|---------|
| `collective_id` | Owning center |
| `slot_date`, `start_time`, `end_time` | Bookable window |
| `capacity` | Parallel lane / bay capacity |
| `service_id` | Center service (lane hour, etc.) |
| `arena_id` | Venue (optional) |

**Coach assignment (admin):** join table `collective_session_coaches(session_id, trainer_id)` — coaches **on duty** for that window. Clients choosing «our coach» may pick **only** from this set, not the full roster.

**Attendance mode** on booking (client or staff):

| Mode | `center_coach_id` | Billing |
|------|-------------------|---------|
| `lane_self` | NULL | Lane tariff / lane pass |
| `lane_with_guest` | NULL | Lane + **15 BYN × guest_count** (cash/add-on; see §4) |
| `lane_own_coach` | NULL | Lane only (external coach; policy/waiver out of scope) |
| `center_coach_individual` | assigned coach | Coach individual tariff / coach pass |
| `center_coach_pair` | assigned coach | Coach pair tariff / coach pass (2 coach-credits or fixed rule) |

If the client does not select a center coach → session is **without** center coach (`center_coach_id = NULL`).

---

### 3. Commerce: center vs trainer passes

**Unchanged for ice / personal practice:** `trainer_pass_products` + `pass_instances` scoped to `trainer_id`.

**New for throwing center:** `collective_pass_products` + `pass_instances.collective_id` (or equivalent scope column):

| Product line | Redeems on | Expiry |
|--------------|------------|--------|
| Lane visits (4 / 8 / 16) | `lane_self`, optionally `lane_with_guest` **base visit only** | Per product (8→2mo, 16→3mo) |
| Coach sessions (4 / 8 / 16 with coach) | `center_coach_individual`, `center_coach_pair` per product rules | Per product |

**Prices are set only by center admin**, not by individual coaches.

#### Throwing center tariff card (MVP reference)

**Pay-as-you-go (BYN):**

| Code | Label | Price |
|------|-------|------:|
| `lane_hour` | Бросковая зона, 1 ч | 20 |
| `guest_surcharge` | Доп. человек | +15 each |
| `coach_individual` | Индив. с тренером центра | 70 |
| `coach_pair` | Парная с тренером центра | 100 |

**Lane passes:**

| Visits | Price (BYN) | Validity |
|--------|------------:|----------|
| 4 | 75 | — |
| 8 | 145 | 2 months |
| 16 | 275 | 3 months |

**Coach passes:**

| Sessions | Price (BYN) | Validity |
|----------|------------:|----------|
| 4 | 255 | 2 months |
| 8 | 490 | 3 months |
| 16 | 960 | 5 months |

#### Redeem rules (normative)

1. **Lane pass:** consumes **1 visit** for the lane portion of the booking.
2. **Guest surcharge (+15 BYN):** always **cash/add-on on top**, never included in pass visit count and never consumes an extra visit.
3. **Coach pass:** **1** coach-credit for `center_coach_individual`; **2** coach-credits for `center_coach_pair` (confirmed).
4. **Pass validity:** starts at **purchase date** (`issued_at`), not first visit (confirmed).
5. **Lane pass cannot pay for coach portion; coach pass cannot pay for lane-only visit.**

---

### 4. Booking model (amends ADR 001 §1)

ADR 001 stated `bookings.trainer_id` is always the booking owner. **Amendment:**

| Booking kind | Primary anchor | `trainer_id` role |
|--------------|----------------|-------------------|
| Classic (solo / ice member slot) | `slot_id` → member | Coach who owns the slot (unchanged) |
| Center session (with center coach) | `collective_session_id` | Assigned / fulfillment coach |
| Center session (lane-only, no coach) | `collective_session_id` | **Center admin** for notifications (see §4.1); CRM `trainer_id` = technical routing TBD in implementation |
| Personal coach slot inside center org | `slot_id` | Coach (unchanged) |

Add columns (exact names in implementation plan):

- `collective_session_id` (nullable FK)
- `attendance_mode` (enum above)
- `center_coach_id` (nullable FK → trainers)
- `guest_count` (default 0)
- `collective_id` (nullable, denormalized for passes & reporting)
- `lane_pass_instance_id` / `coach_pass_instance_id` or generic pass redemption link (reuse existing redemption audit pattern)

#### 4.1 Notifications (lane-only without center coach)

When `attendance_mode` is `lane_self`, `lane_with_guest`, or `lane_own_coach` and **no** `center_coach_id`:

- **Push / booking alerts go to center admin(s)** (owner + studio `admin` role when implemented).
- **Duty coaches on the session do not** receive client booking pushes for lane-only visits (confirmed).

Coach-assigned modes (`center_coach_*`) notify the selected fulfillment coach as today.

**Invariants (retained):**

- Client rosters remain per-trainer (ADR 001 §2).
- Solo trainers without collective membership behave exactly as today.
- Ice white-label does not require center sessions or collective passes.

---

### 5. Multi-collective membership (supersedes ADR 001 §4)

**Remove:** «At most one active collective per trainer (MVP).»

**Replace with:**

- A trainer may hold **multiple active `collective_members` rows** (different `collective_id`).
- `consume_collective_invite` must not reject solely because another membership exists; enforce business rules per collective (seat limits, status).
- Entitlements merge: `effective = union(own_subscription, ∪ collective_pool for each active membership)` — same union rule, applied per membership.

**UI:**

- Trainer hub «Студия» becomes **context switcher** when `memberships.length > 1`.
- Bootstrap API returns `collectives: [...]` (array), not a single object.

---

### 6. Merged schedule (one coach, many contexts)

Single trainer mini-app calendar = **union view**:

```
merged_slots(trainer_id) =
  personal & member_autonomous slots (slots.trainer_id)
∪ assignments (collective_session_coaches.trainer_id)
```

**Requirements:**

- Overlap detection across both sources before confirm.
- Visual distinction: lane duty vs personal vs ice-studio slot (labels by `collective_id` / mode).
- Coach booking client: **context picker** — «Throwing center session» vs «Ice studio / personal slot».

Admin with `schedule:delegate` (see §7) uses the same APIs with explicit `target_trainer_id` and `collective_id`.

---

### 7. Roles (studio governance — cross-reference)

Not fully specified here; minimum for throwing center MVP:

| Role | Billing | Center schedule | Assign coaches | Book clients | Brand |
|------|---------|-----------------|----------------|--------------|-------|
| `owner` | yes | yes | yes | yes | yes |
| `admin` | optional | yes | yes | yes | yes |
| `member` | no | own slots only | no | own clients | no |

Optional `studio_access_mode` on trainer: `full_trainer` | `studio_admin_only` (skip trainer onboarding gates; studio screens only).

Detailed role matrix → future **ADR 004** or section in this ADR when implementing governance wave.

---

### 8. Bots and apps

| Surface | Change |
|---------|--------|
| Client bot / catalog mini-app | Mode-aware landing; center passes checkout; attendance mode form |
| Trainer bot / mini-app | Merged schedule; multi-studio switcher; context booking |
| Platform admin bot | Unchanged pattern; center pass products optional manual grant |

**No third bot.**

---

## Consequences

### Positive

- One platform serves ice white-label and operator-led centers.
- Tariff logic centralized for throwing center; coaches not pricing lane visits.
- Coaches working multiple studios avoid duplicate Telegram accounts.

### Costs / complexity

- New tables: `collective_sessions`, assignments, `collective_pass_products`, booking extensions.
- Catalog and booking flows split by `schedule_mode` (two client UX paths, one codebase).
- Pass redemption engine needs **add-on** line items (guest surcharge) separate from visit debit.
- Multi-collective touches hub bootstrap, shell, entitlements, invite consumption.

### Migration

- Existing collectives default `schedule_mode = member_autonomous`.
- ADR 001 pilots (e.g. ice-yoga-lane) require **no** schedule migration.
- Throwing center onboarded as new collective with `studio_central`.

---

## Out of scope (explicit)

- Room-first resource locking across unrelated sessions (beyond `capacity` integer).
- Payroll / revenue share to coaches from center tariffs.
- Platform payment capture for lane/guest surcharges (MVP may remain external payment + staff confirm, like current pass issue flow).
- Client roster shared across center members.
- Separate admin Telegram bot.

---

## Implementation waves (recommended)

| Wave | Scope | Pilot |
|------|--------|-------|
| **W1** | ADR 001 + `member_autonomous` polish | Ice skating |
| **W2** | `studio_central`: sessions, admin grid, attendance modes, PAYG tariffs | Throwing center booking |
| **W3** | `collective_pass_products` + redeem + guest +15 add-on | Throwing center passes |
| **W4** | Multi-collective + merged schedule + admin delegate booking | Coach in ice + center |
| **W5** | `admin` role + `studio_admin_only` | Non-trainer manager |

Do not start W4 before W2–W3 acceptance criteria pass for throwing center.

---

## Resolved product decisions

| # | Decision |
|---|----------|
| Q1 | **Pair with center coach** debits **2** coach-pass credits. |
| Q2 | Guest +15 BYN on lane visit: **add-on on top** (not included in lane pass visit). |
| Q3 | Pass validity starts at **purchase date** (`issued_at`). |
| Q4 | **Lane-only** booking (no center coach): push to **center admin** only, not duty coaches. |

**Still default (unchanged unless center says otherwise):** `lane_own_coach` + friend → guest +15 BYN per extra person applies.

---

## Success criteria

1. Ice pilot: no regression; members self-schedule; no center sessions required.
2. Throwing center: admin publishes grid; client books lane-only and coach modes; guest +15 charged as add-on, not pass visit.
3. Coach in two collectives: one calendar shows both; no double-book overlap allowed.
4. Coach pass and lane pass cannot cross-redeem.
5. All flows work in existing client + trainer bots.

---

## References

- [ADR 001: Collective overlay](./001-collective-overlay.md)
- **[Appendix: Organization format → UX contract](./003-appendix-organization-format-ux.md)** — pilot onboarding table (O0.4)
- Implemented: collective brand, roster, pool billing (P2.1), governance API (P1.8)
- This ADR: accepted product contract for W2+
