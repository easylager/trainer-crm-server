# PRD: Trainer Hub — session visibility, “Client problem” presets, accounting & notifications

**Status:** Draft  
**Owner:** Product  
**Related areas:** Trainer Mini App (`trainer-home` hub), schedule/bookings, passes/certificates, client risk flags, notifications.

---

## 1. Executive summary

Trainers need to **see and open the “current” booking in the Hub for the entire duration of the slot** (and until the slot **ends**, not when it merely “starts”). From that context (and later from post-session surfaces), they need a **“Client problem”** action with **clear presets** and **explicit system consequences** (accounting, pass/certificate write-off, client risk state, blacklist path). If the trainer **does not** report a problem, the existing lifecycle (e.g. auto-complete, standard end-of-session messaging) applies; if they **do** report, notifications and back-office treatment **diverge**. Trainers must still be able to **escalate a problem after the slot ends** if they missed it during the session.

---

## 2. Problem statement

1. **Hub UX:** Bookings can feel “gone” too early; the trainer loses one tap to the live booking during the lesson window.
2. **Operational reality:** No-shows and payment issues are common; the product currently collapses many outcomes into a single “completed” path (see existing auto-complete / pass redemption rules).
3. **Trust & clarity:** The trainer must **always know what the system will do** before confirming a preset (toast + confirmation where needed).
4. **Compliance:** “Problematic client” vs **blacklist**, accounting inclusion/exclusion, and pass/certificate policies must be explicit and auditable.

---

## 3. Goals

| ID | Goal |
|----|------|
| G1 | In Trainer Hub, the **active booking** for the **current time window** (and until **slot end**) remains **reachable and prioritized** (first in “nearest” list, or clearly labeled “current” in a later iteration). |
| G2 | From **Hub → slot detail** (and from **post-session entry points**), provide a **“Client problem”** flow with **presets** determined by **payment instrument** (none vs pass/certificate vs other). |
| G3 | For each preset, show **plain-language consequences** to the trainer (what is recorded, what is **not** sent to accounting, what happens to the client, follow-up promises). |
| G4 | Support **trainer-configurable policy** where relevant (e.g. abonement/certificate: auto write-off on no-show vs not — **per trainer**). |
| G5 | **Different notification paths** when a problem is reported vs when the session ends “normally”; allow **late reporting** after slot end without blocking the standard reminder path upfront. |

## 4. Non-goals (this PRD)

- Full legal/compliance sign-off text (only product placeholders + need for legal review).
- Automated chargeback or payment capture integrations (unless already in stack).
- Client-facing self-service dispute resolution portal (unless explicitly added later).

---

## 5. Definitions

| Term | Meaning |
|------|---------|
| **Slot** | Calendar row (date, start, end, capacity, etc.). |
| **Booking** | Client’s reservation on a slot (`bookings` row). |
| **Session window** | `[start_time, end_time)` on `slot_date` (product should use the same TZ as schedule). |
| **Slot ended** | `now > slot_date + end_time` (policy for inclusive end can be specified in tasks). |
| **Payment instrument** | None / one-off / pass / certificate / mixed — resolved from existing booking + client instruments. |
| **Problem report** | Structured trainer action with preset + optional note, stored immutably for audit. |
| **Problematic client** | Internal risk flag (not yet full **blocklist**); visible in CRM, affects automation copy. |
| **Blacklist** | Stronger enforcement (e.g. block new bookings / flag for admin); only where product policy allows. |

---

## 6. Current product context (as-is, for implementers)

- Bookings in `pending` / `confirmed` past **slot end** are auto-completed; completion triggers pass/certificate redemption per existing rules (`mark_booking_completed_and_notify` / related).
- No first-class **no-show** or **payment dispute** outcome in accounting terms today.

**Implication:** This feature will introduce **explicit outcomes** that must **override or branch** auto-complete, redemption, and notifications. Migration and idempotency are critical.

---

## 7. Functional requirements

### 7.1 Trainer Hub — visibility and ordering

**FR-1** For a trainer, a booking whose **session window overlaps “now”** OR **has started but not ended** must remain **visible** in the Hub’s “nearest / upcoming” area and must **not disappear** merely because the clock passed `start_time`.

**FR-2** Until **slot end**, this booking should appear **first** among “nearest” items, OR (later phase) show a distinct **“Current session”** affordance. Minimum for MVP: **sort key** so current window booking is **ranked above** future bookings.

**FR-3** After **slot end**, standard rules apply (e.g. eventual removal from “upcoming”; alignment with existing completed/cancelled lists — **exact UX to match `trainer-home` data sources** in implementation tasks).

### 7.2 Entry points — “Client problem”

**FR-4** **Hub → open slot / booking** → primary action row includes **“Client problem”**.

**FR-5** **Post-session:** After the recording ends, the trainer still has **“Client problem”** on that booking (same booking id), plus any existing “session ended” / feedback surfaces already planned in product.

**FR-6** (Optional parity) Push / in-app message after session end includes **the same** CTA if product already sends a trainer message for completed sessions.

### 7.3 Presets — branching logic

Let the backend classify the booking into:

- **A. No active pass/certificate covers this lesson** (one-off / unpaid / external cash — **precise detection in tasks** from existing schema).
- **B. Pass or certificate **can** cover this lesson** (active instrument + rules already used at booking time).

#### A — No pass/certificate (two presets, MVP)

| Preset ID | Trainer label (copy TBD) | System intent (high level) |
|-----------|----------------------------|----------------------------|
| A1 | **Client didn’t come** (no-show) | Do **not** treat as successful revenue session for accounting; do **not** push “completed” money event; mark client **problematic** (non-blocking); **no** auto-blacklist. |
| A2 | **Didn’t pay** | Stronger path: communicate **blacklist** risk + **we will try to resolve**; mark client for collections / admin pipeline; **no** positive accounting completion for this session. |

**FR-7** Before confirmation, show **explicit consequence copy** (toast/modal): what is stored, what accounting sees, what happens to client state.

#### B — Pass / certificate

**FR-8** Trainer sees presets appropriate to **paid-instrument** cases (labels TBD), but the critical branch is **policy**:

| Policy (per trainer, configurable) | Behavior |
|-------------------------------------|----------|
| **P1 — Auto write-off on no-show** (default TBD) | If preset = no-show / equivalent, **redeem** one session / certificate slice as per rules. |
| **P2 — Do not write off on no-show** | Booking closed as problem outcome **without** redemption; client sees policy copy about **late cancellation** / automatic charge windows (exact wording + timers in follow-up PRD if not in schema today). |

**FR-9** Client-facing policy text: if they **do not cancel** before **cutoff**, the system may **auto-apply** abonement charge (trainer-configured). **Where this cutoff is stored** is an implementation task (trainer profile / platform settings).

### 7.4 Client state & admin

**FR-10** **Problematic** = visible flag, filters in client list, optional badge in booking detail — **not** full block.

**FR-11** **Blacklist** path only for presets where product promises it (e.g. non-payment), with **audit log** (who/when/which booking).

### 7.5 Notifications matrix

| Situation | Trainer | Client | Notes |
|-----------|---------|--------|------|
| No problem; slot ends | Existing “session ended” / feedback flows | Existing client completion flows | Baseline. |
| Problem reported **during** session | Acknowledgment + summary of outcome | **Different** template: session **not** successfully completed / policy / next steps | FR-12 |
| Problem reported **after** slot end (trainer was late) | Same as above | Same | Must **reverse** or **stop** any auto-complete that already ran — **hard edge case**; task to define reconciliation. |
| No problem reported; slot ends | Baseline | Baseline | |
| Trainer silent | Baseline still fires at slot end | Baseline | Trainer can still open **Client problem** later (FR-5). |

**FR-12** Content of **problem** notifications must differ from **happy-path** completion (no fake “great job” if it was a no-show).

**FR-13** Timing: optionally **at slot end** or **immediately** on submit — product default: **immediate** on submit + **optional** reminder at slot end if unresolved (configurable).

---

## 8. Data & audit

- Immutable **ProblemReport** entity: `booking_id`, `trainer_id`, `preset`, `payment_class`, `policy_snapshot_id`, `note`, `created_at`, `source` (hub / notification deep link).
- Link to **client risk** table or flags on `clients` / join table (implementation task).
- **Idempotency:** One active resolution per booking (or explicit supersession rules).

---

## 9. Edge cases (must be in tasks)

1. **Auto-complete already ran** before trainer reports no-show → financial reversal or **credit** adjustment (product + engineering spike).
2. Group slots / multiple bookings on same slot — problem applies per **booking**, not whole slot unless specified.
3. Trainer changes device mid-session — Hub still shows current booking (stateless URL `/trainer-home` + booking id).
4. Offline / flaky network — queue submit, show pending state.

---

## 10. Phasing suggestion

| Phase | Scope |
|-------|--------|
| **MVP-1** | Hub sorting + slot visible until end; **Client problem** on booking detail; presets A1/A2; problematic flag; accounting hooks as **events** (even if manual export first); trainer-facing consequence copy. |
| **MVP-2** | Pass/certificate branch + per-trainer policy P1/P2; adjusted notifications for B-path. |
| **MVP-3** | Blacklist automation + admin queue; client policy copy + cancellation cutoff configuration. |
| **Later** | Dedicated “Current session” card, analytics dashboard for no-shows. |

---

## 11. Task breakdown (for engineering / PM)

### Epic E1 — Hub & schedule data

- **T1.1** Audit `trainer-home` / hub API: which bookings are returned, filters, sort order.  
- **T1.2** Define rule: **include** booking if `now < end_time` and status in `pending|confirmed` (and not cancelled?) even if `now > start_time`.  
- **T1.3** Sort: **current window** booking first; tie-breaker by `start_time`.  
- **T1.4** QA: booking visible entire session; disappears only after end per spec.

### Epic E2 — “Client problem” UI (Mini App)

- **T2.1** Add button on Hub booking / slot detail screen.  
- **T2.2** Modal/bottom sheet: load preset options from API (`GET .../booking/:id/problem-options`).  
- **T2.3** Confirmation step with **fixed consequence strings** from API (trainer cannot misunderstand).  
- **T2.4** POST submit, toast success/error.  
- **T2.5** Same entry from post-session card / notification deep link (deeplink `booking_id`).

### Epic E3 — Backend: classification & policies

- **T3.1** Service: classify booking → `NONE` | `PASS` | `CERT` | `ONE_OFF` (exact mapping to schema).  
- **T3.2** Store **trainer policy** P1/P2 (new table or `trainer_profiles` JSON — spike).  
- **T3.3** Implement `POST /trainer/bookings/:id/problem` with validation (slot not cancelled, trainer owns booking, etc.).

### Epic E4 — Business outcomes

- **T4.1** A1: set booking outcome **no_show** (or equivalent); **skip** accounting completion event; set client **problematic**.  
- **T4.2** A2: initiate **blacklist** pipeline flag + trainer copy; block rules (define).  
- **T4.3** B + P1: redeem pass/cert on no-show per policy.  
- **T4.4** B + P2: no redemption; store policy breach reason for client notification.  
- **T4.5** Interaction with **auto-complete** job: exclude bookings with terminal problem outcome; **reconciliation** task if job ran first.

### Epic E5 — Notifications

- **T5.1** Templates: problem vs normal completion (trainer + client).  
- **T5.2** Schedule: immediate vs slot-end (config).  
- **T5.3** Push deep link opens **Client problem** if still allowed.

### Epic E6 — Compliance & audit

- **T6.1** Immutable audit log for all submissions.  
- **T6.2** Admin view: list problem reports, blacklist candidates.

### Epic E7 — QA & rollout

- **T7.1** Test matrix: all preset × policy × timing (before/after slot end).  
- **T7.2** Feature flag / pilot trainers.

---

## 12. Open questions

1. Exact **accounting** integration: event bus, export CSV, or third-party?  
2. **Blacklist**: automatic booking block or manual admin only?  
3. **Group lessons**: one no-show affects only that client’s booking — confirm.  
4. Default for **P1 vs P2** for new trainers.  
5. Legal review for **A2** and blacklist messaging.

---

## 13. Success metrics (suggested)

- % sessions with problem reported where **accounting matches** trainer intent (sample audit).  
- Time-to-report (during vs after session).  
- Trainer CSAT on clarity of consequence copy.  
- Reduction in support tickets “wrong charge / wrong completion”.

---

*This PRD consolidates the user’s voice transcript and the agreed branches (Hub visibility, presets by payment type, problematic vs blacklist, trainer policy for pass/certificate, notification divergence, post-hoc problem reporting). Implementation should not change scope without updating this document.*
