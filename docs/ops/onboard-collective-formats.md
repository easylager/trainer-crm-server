# Runbook: onboard collective (studio / center / hybrid)

Ops checklist for pilot studios and throwing centers. Commands run in **admin bot** unless noted.

## Prerequisites

- Owner trainer exists in DB (`/trainer_welcome` or moderation approve).
- `TRAINER_BOT_USERNAME` and `WEBAPP_BASE_URL` set in env.
- ADR UX table: [003-appendix-organization-format-ux.md](../adr/003-appendix-organization-format-ux.md)

## 1. Ice studio (white-label roster)

**Product:** autonomous coaches, shared brand, no center grid.

```text
/collective_draft ice-yoga-lane|Ice Yoga Lane|studio
```

Optional seats (default 5):

```text
/collective_draft fit-hub|Fit Hub|studio|12
```

**Verify:**

```text
/collective_draft status ice-yoga-lane
```

Expect: `format studio`, `schedule member_autonomous`, owner mode `trainer`, status `draft`, claim link outstanding.

Send owner the claim deep link from bot reply → owner opens trainer bot → lands in «Студия».

**After claim:**

```text
/collective_sub grant ice-yoga-lane 1 online analytics groups
/collective_sub status ice-yoga-lane
```

Owner: brand tab, team invites, client link `col_<slug>`. Catalog: roster of trainers (`?collective=slug`).

## 2. Throwing center (facility manager)

**Product:** center grid, lane + coach tariffs, owner without personal CRM.

```text
/collective_draft throwing-minsk|Throwing Minsk|center|8|manager
```

Alias `manager` = `studio_admin_only` owner (no personal schedule tab focus).

**Verify:**

```text
/collective_draft status throwing-minsk
```

Expect: `format center`, `schedule studio_central`, owner mode `manager`.

After claim: default tab **Расписание**, seed passes, create sessions, assign coaches.

**Pool subscription:**

```text
/collective_sub grant throwing-minsk 3 online analytics groups
```

## 3. Center hybrid (owner trains + runs center)

**Product:** Broski-style — owner keeps personal CRM + center admin.

```text
/collective_draft broski|Broski Center|center_hybrid|8|trainer
```

Legacy shorthand (still supported):

```text
/collective_draft broski|Broski Center|center|8|trainer
```

→ stored as `center_hybrid`.

**Verify:** hub dual summary (personal bookings + center inbox), context picker on quick book.

## 4. Ops commands reference

| Command | Purpose |
|---------|---------|
| `/collective_draft formats` | Canonical formats + aliases |
| `/collective_draft status <slug>` | Format, seats, owner mode, claim state |
| `/collective_sub status <slug>` | Pool subscription period |
| `/collective_sub grant <slug> <months> [modules]` | Pilot grant |

## 5. Suspend / reactivate (O8.4)

When billing or compliance requires taking brand offline:

```sql
UPDATE collectives SET status = 'suspended', updated_at = NOW() WHERE slug = 'throwing-minsk';
```

**Expected behavior:**

- Public catalog `GET /api/public/collectives/{slug}` → **404**
- Client bot landing still works but catalog link shows empty/404
- Trainers see **amber banner** in mini-app: organization suspended, personal CRM OK

Reactivate:

```sql
UPDATE collectives SET status = 'active', updated_at = NOW() WHERE slug = 'throwing-minsk';
```

## 6. Smoke after onboard

1. `/collective_draft status <slug>` — claimed, seats OK
2. Owner opens `trainer-collective` → correct tabs for format
3. Catalog `?collective=<slug>` — hero matches format (studio roster vs center grid)
4. One test booking: personal slot (studio/hybrid) or center session (center/hybrid)
5. `@pytest.mark.collective` green in CI

## 7. Common mistakes

| Mistake | Fix |
|---------|-----|
| `studio` + owner `manager` | Rejected — studio requires `trainer` |
| Slug with underscore | Use hyphens only (`ice-yoga`, not `ice_yoga`) |
| Seats full on invite | `/collective_sub grant` or revoke pending invites |
| Center tabs on studio member | Check `organization_format` in status output |
