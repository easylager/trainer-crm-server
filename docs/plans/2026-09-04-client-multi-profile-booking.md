# Client multi-profile booking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make hub profile switcher + booking form actually book the selected family profile (child), with per-profile history/stats, while all Telegram pushes stay on the parent account.

**Architecture:** Keep `client_profile_links` + `resolve_acting_client_id`. Fix the client fetch patch so `X-Profile-Id` is always sent for the acting profile. Add an on-form “Кого записываем?” selector (override without changing hub default). Finish remaining list/hub endpoints that still key off `telegram_id`. Trainer UI already keys bookings by `client_id` — ensure display name/contact are correct for guardian profiles.

**Tech Stack:** FastAPI + SQLAlchemy async, vanilla JS Mini Apps (`static/webapp/`), pytest + httpx ASGITransport.

**Design:** `docs/plans/2026-09-04-client-multi-profile-booking-design.md`  
**Prior art:** `.ai/EPIC1-client-multi-profile.md`, `static/webapp/client-profile-switcher.js`, `src/application/client_profile_use_cases.py`

---

### Task 1: Always send `X-Profile-Id` from the fetch patch

**Files:**
- Modify: `static/webapp/client-profile-switcher.js` (fetch patch ~lines 50–70; `selectProfile` / `activeProfile` helpers)
- Test: manual + later API tests; optionally a small node-less comment/assert in existing slice4 docs

**Step 1: Change the header condition**

Today the patch only attaches the header when:

```js
state.activeProfileId != null && state.activeProfileId !== state.defaultProfileId
```

That skips the header when the child is both active and default → server resolves self.

Replace with: resolve acting id = `activeProfileId ?? defaultProfileId`; if non-null, **always** set `headers['X-Profile-Id'] = String(actingId)` on `/api/webapp/client/*` requests (including self). Server already accepts it via `resolve_acting_client_id`.

Also keep `selectProfile` behavior: choosing the default profile may clear `localStorage` override (`null`), but after `loadProfiles` the fetch patch must still send `defaultProfileId`.

**Step 2: Bump cache-buster query on script tags**

Update `?v=...` on every `client-profile-switcher.js` include under `static/webapp/*.html` so Telegram WebView picks up the fix.

**Step 3: Commit**

```bash
git add static/webapp/client-profile-switcher.js static/webapp/*.html
git commit -m "$(cat <<'EOF'
fix: always send X-Profile-Id for the acting client profile

Default child profiles were booked as self because the fetch patch omitted the header when active === default.
EOF
)"
```

---

### Task 2: API test — default child profile booking uses child `client_id`

**Files:**
- Create/extend: `tests/api/test_client_profile_switching_slice4.py` (or new `tests/api/test_client_profile_booking_attribution.py`)
- Rely on: `app_use_test_db`, `db_session`, `patch_trainer_webapp_init` / client init helpers used elsewhere

**Step 1: Write failing test**

Scenario:
1. Create parent client + self link; create guardian child via `create_guardian_profile`; `set_default_profile` → child.
2. `POST /api/webapp/client/booking` with `X-Profile-Id: <child_id>` (and without header once Task 3 makes “no header = default” if you choose that path — see Task 3 note).
3. Assert `bookings.client_id == child_id`, not parent.

Also assert: with header = child while default = child, booking still lands on child (regression for Task 1).

**Step 2: Run test — expect FAIL** only if booking path still wrong; if header path already works, test should PASS after Task 1 for the “with header” case.

**Step 3: Commit test**

```bash
git add tests/api/test_client_profile_booking_attribution.py
git commit -m "test: booking with X-Profile-Id attributes to guardian profile"
```

---

### Task 3 (optional hardening): server default = `is_default` when header absent

**Files:**
- Modify: `src/application/client_profile_use_cases.py` — `resolve_acting_client_id`
- Modify tests in `tests/application/test_client_profile_use_cases.py`

**Decision in plan:** Prefer **always sending the header from the client** (Task 1). Only change server fallback if product wants deep links / old clients without the script to honor `is_default`.

If implementing: when `requested_profile_id is None`, after ensuring self link, if account has a default link row, return that `profile_client_id` instead of raw `legacy_id` **only when** the default row is accessible. Keep bot/legacy callers safe: bots that never set default stay on self.

**Skip this task** unless Task 1 alone is insufficient for a concrete caller.

---

### Task 4: Book form — “Кого записываем?” selector

**Files:**
- Modify: `static/webapp/book.html` (markup above phone block ~792)
- Modify: `static/webapp/book.html` inline JS and/or `static/webapp/booking-client.js`
- Reuse: `ClientProfileSwitcher` API (`getActiveProfileId`, `init`, profiles from `GET /client/profiles`)

**Step 1: Markup**

Add a `form-block` before phone:

```html
<div id="bookForProfileBlock" class="form-block" style="display:none;">
  <label for="bookForProfileSelect">Кого записываем?</label>
  <select id="bookForProfileSelect" aria-label="Кого записываем"></select>
  <button type="button" id="bookAddChildBtn" class="btn-secondary" style="margin-top:8px;display:none;">Добавить ребёнка</button>
</div>
```

Show the block when `profiles.length >= 1` after profiles load (always show if ≥2, or always show once profiles exist so “add child” is reachable).

**Step 2: Populate select**

On load: `ClientProfileSwitcher.init()` then `GET /client/profiles` (or read from switcher state if exposed). Preselect `getActiveProfileId()`. Changing the select updates a page-local `bookActingProfileId` used only for this booking — **do not** call `PATCH .../default` and **do not** rewrite hub `localStorage` unless product later asks.

Ensure submit path sets `X-Profile-Id` on the booking fetch to `bookActingProfileId` even if the global patch races (explicit header on `BookingClient.submitBooking` / book.html fetch).

**Step 3: Button label**

Update `#btnSubmit` text: if selected role is `guardian` → `Записаться за {first_name}`; else `Записаться`.

**Step 4: Add child from form**

Minimal: open the existing switcher sheet if mounted, or inline POST `/client/profiles` then append option and select it (override only; optional PATCH default — **do not** auto-default from book form to avoid surprising hub). Prefer no PATCH default from book form.

**Step 5: Hide name fields when booking for existing guardian/self with name**

Existing `bookNameBlock` logic stays for first-time self; for guardian profiles name already exists on server — do not ask to re-enter parent name as if it were the child.

**Step 6: Commit**

```bash
git add static/webapp/book.html static/webapp/booking-client.js
git commit -m "feat: book form shows who is being booked (profile selector)"
```

---

### Task 5: Client bookings list + history honor profile

**Files:**
- Modify: `src/api/routes/webapp_client_payloads.py` — `client_bookings_days_payload(session, telegram_id)` → accept `client_id` or resolve via profile
- Modify: `src/api/routes/webapp.py` — `GET /client/bookings`, `GET /client/bookings/history` (~2407–2430) add `x_profile_id`, resolve acting client, pass `client_id` into payload helpers
- Modify: any history helper that filters by telegram join — filter `bookings.client_id = :cid`

**Step 1: Failing API test**

Parent has booking A; child has booking B. With `X-Profile-Id: child`, `GET /client/bookings` returns only B.

**Step 2: Implement resolution + query by `client_id`**

**Step 3: Commit**

```bash
git add src/api/routes/webapp.py src/api/routes/webapp_client_payloads.py tests/api/...
git commit -m "feat: client bookings list/history scoped to acting profile"
```

---

### Task 6: Hub bootstrap bookings/requests scoped to profile

**Files:**
- Modify: `src/api/routes/webapp.py` — `get_client_hub_bootstrap` (~2582+): `_bookings` / `_requests` currently call payloads with `telegram_id` only; pass resolved `client_id` / `requested_profile_id`
- Update docstring that says bookings stay account-scoped

**Step 1: Failing test** — hub bootstrap with child header does not include parent-only bookings.

**Step 2: Implement**

**Step 3: Commit**

```bash
git commit -m "feat: hub bootstrap bookings/requests use acting profile"
```

---

### Task 7: Requests list GET honors profile

**Files:**
- Modify: `src/api/routes/webapp.py` — `GET /client/requests` (~2172) currently no `x_profile_id`
- Modify: `_client_requests_list_payload` / `list_my_requests_with_responses` to take `acting_client_id` (PATCH path already has this pattern)

**Step 1: Test + implement + commit**

```bash
git commit -m "feat: GET /client/requests respects X-Profile-Id"
```

---

### Task 8: Activity-stats already profile-aware — verify + hub ribbon

**Files:**
- Verify: `GET /client/activity-stats` already uses `resolve_acting_client_id` (~2567)
- Verify hub `activity` / `passes` branches in bootstrap (~2728+)
- Add regression test: completed bookings on child do not inflate parent `completed_total` when header = parent, and vice versa

**Step 1: Test + fix any remaining telegram-scoped count queries**

**Step 2: Commit if fixes needed**

---

### Task 9: Trainer-facing identity for guardian bookings

**Files:**
- Inspect: `get_trainer_booking_detail_payload`, schedule booking cards, confirm notifications (`booking_confirm_client_notify.py`, trainer schedule payloads)
- Ensure display name = `clients.first_name/last_name` of booking’s `client_id` (child), not account self
- Contact/Telegram actions: resolve notify target via account link (`client_profile_links` → parent `telegram_id`) when `clients.telegram_id` is NULL
- Optional UI hint: `booked_via_guardian: true` or subtitle “через родителя” if easy in existing payload

**Step 1: Find one code path that incorrectly uses parent name**

**Step 2: Failing test on booking detail / list payload name**

**Step 3: Fix notify target for telegram_id NULL clients** (search existing helpers — may already exist for trainer-added offline clients)

**Step 4: Commit**

```bash
git commit -m "feat: trainer sees child profile name; notify parent Telegram"
```

---

### Task 10: End-to-end API coverage + cache bump

**Files:**
- `tests/api/test_client_profile_booking_attribution.py` (full flow)
- Confirm all client HTML pages include updated switcher `?v=`

**Acceptance checklist (manual in Telegram):**
1. Add child on hub → child selected → book slot → trainer card shows child name; DB `bookings.client_id` = child.
2. Switch to self → book → separate client_id = parent.
3. Hub stats/history while on child show only child data.
4. Push for child’s booking arrives in parent Telegram with child’s name in text (if notify path touched).

**Final commit** if only test/docs leftovers.

---

## Out of scope (do not do in this plan)

- `companion_client_id` / multi-participant single booking
- Changing `client_family_access_members`
- Full hub visual redesign
- Auto-changing hub default from the book-form selector
