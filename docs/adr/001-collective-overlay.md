# ADR 001: Collective overlay (white-label foundation)

**Status:** Accepted (Wave P0 foundation)  
**Date:** 2026-06-12

## Context

Mini-studios (2–5 trainers) need a shared client landing, pooled subscription, and studio brand — without a second CRM product or forked UI.

Solo trainers must behave exactly as today when they are not in a collective.

## Decision

Introduce **Collective** as an optional overlay on the existing `Trainer` atom:

| Layer | Responsibility |
|-------|----------------|
| `Trainer` | Bookings, clients, schedule, solo catalog card |
| `Collective` | Brand, client deep link, seat pool billing (later), member roster |
| `Platform` | Ice Studio default brand, legal operator, core CRM |

### Invariants (must not break)

1. `bookings.trainer_id` is always the booking owner.
2. Client rosters are per-trainer, never shared across collective members.
3. `get_effective_entitlements(trainer_id)` with no active membership **equals** `get_trainer_entitlements(trainer_id)`.
4. At most **one active collective** per trainer (MVP).
5. White-label client surfaces show studio brand + small «powered by Ice Studio» footer.

### Entitlements merge

```
effective = union(own_subscription, collective_subscription_for_member)
own modules win for display priority; union for access checks.
```

### Deep links (trainer bot)

| Prefix | Purpose |
|--------|---------|
| `link_` | Existing trainer welcome link |
| `ref_` | Referral |
| `col_claim_` | Activate studio draft → owner |
| `col_inv_` | Join studio as member (Wave P1) |
| `col_` | Client studio catalog entry (Wave P1) |

### UI strategy

One trainer mini-app. Collective admin is a capability-gated section in «Ещё», not a separate shell.

## Consequences

- Additive DB tables only; no changes to solo flows until membership exists.
- Feature gates should call `get_effective_entitlements`, not raw `get_trainer_entitlements`.
- Bootstrap returns `collective: null` until member/owner resolution is implemented in UI.

## Wave plan

- **P0 (this ADR):** schema, resolvers, admin draft + claim token, effective entitlements stub, bootstrap field.
- **P1:** claim/invite consumption, catalog `?collective=`, trainer «Студия» screen.
- **P2:** collective subscription billing, brand on certificates, boost.
