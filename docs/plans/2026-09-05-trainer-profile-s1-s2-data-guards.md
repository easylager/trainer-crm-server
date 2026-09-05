# Trainer profile S1+S2 — data guards and on-request prices

> **For Claude:** Implement S1+S2 only. Do not start S3–S7 (arena picker UI, profile IA, onboarding city, overlay).

**Goal:** Stop profile Save from unlinking a just-created arena, and stop missing service prices from blocking every other profile edit.

**Architecture:** Server PATCH already treats omitted `arena_ids` as “leave links alone”. The client currently always sends `arena_ids` collected from checkboxes; after create the list is stale so it sends `[]`. Canonical `state.trainer.arena_ids` plus omit-if-unchanged closes that. Empty service prices are already valid on the server (“по запросу”); only client validation treats them as an error.

**Tech Stack:** FastAPI + pytest (httpx ASGI), vanilla JS Mini App (`trainer-profile-main.js`).

---

### Task 1: PATCH omit keeps arena links (AC-001, AC-002)

**Files:**
- Modify: `tests/api/test_webapp_trainer_profile.py`
- Existing helpers: `_trainer_with_city`, arena-setup tests in the same file

**Step 1: Write the failing / characterizing tests**

Add after the TASK-046 block:

1. `test_patch_profile_without_arena_ids_keeps_created_arena` — create via `arena-setup`, then PATCH `{profile: {contacts: "x"}}` with **no** `arena_ids`. Assert GET profile still lists the arena.
2. `test_patch_profile_empty_arena_ids_unlinks` — after create, PATCH `{arena_ids: []}`. Assert arena gone from trainer.
3. `test_patch_services_without_prices_keeps_on_request_service` — PATCH `services: [{service_id, price_tiers: []}]`. Assert `trainer_services` row exists with NULL `price_cents`.

**Step 2: Run tests**

```
PYTHONPATH=. pytest tests/api/test_webapp_trainer_profile.py -k "arena_ids or on_request" -q
```

Omit-arena test should already PASS (server contract). Empty-list unlink should PASS. On-request services should PASS if `_normalize_trainer_services_payload` already keeps empty tiers. If any FAIL, fix `update_trainer_profile` / route — do not change the omit semantics.

**Step 3: Commit later with the JS changes** (user did not ask for a commit until the slice is green).

---

### Task 2: Canonical arena_ids in the Mini App (AC-001, AC-002, city-change)

**Files:**
- Modify: `static/webapp/trainer-profile-main.js` (`readFormSnapshot` ~1723, `afterArenaSetupSuccess` ~4703, `citySel.onchange` ~5123, `save` ~5352, checkbox change in `renderArenas`)

**Behavior:**

1. `readFormSnapshot` takes `arena_ids` from `state.trainer.arena_ids`, not from checkboxes.
2. Checkbox change writes back into `state.trainer.arena_ids` (and primary).
3. `afterArenaSetupSuccess`: `loadArenasForCity(cityId).then(renderArenas)` after applying `data.trainer`.
4. `save()`: if snapshot `arena_ids` (sorted) equal current, **omit** `arena_ids` and `primary_arena_id` from the body.
5. City change: if current `arena_ids.length > 0`, `confirm('Сменить город? Выбранные площадки другого города будут сняты.')`. Cancel → revert select. OK → clear `arena_ids`, load list, `setDirty`. Never send empty `arena_ids` without this confirm.

---

### Task 3: On-request prices (AC-003, AC-004)

**Files:**
- Modify: `static/webapp/trainer-profile-main.js` (`serviceEntryPricesOk`, `domServicesPricesCoherent`, `syncServicesValidationUi`, `readFormSnapshot` services loop, tour Next at ~2711, `syncSaveBarHint`, `renderServices`)
- Modify: `static/webapp/mini-app-trainer-profile.css`
- Modify: `static/webapp/trainer-profile.html` cache bump `?v=202609051`

**Behavior:**

1. Checked service with no filled prices is valid. Invalid = filled field that is not a number ≥ 0.
2. `readFormSnapshot` includes checked services even with `price_tiers: []`.
3. Row shows `клиент видит: по запросу` when checked and no valid price; not an error, not a required-dot.
4. Tour Next on `services` no longer blocks on missing prices.
5. Save-bar hint no longer nags about missing BYN when the form is clean.

**Copy:** `SERVICES_PRICE_HINT_RU` only for invalid numbers, e.g. «Цена — неотрицательное число. Пустое поле значит „по запросу“.»

---

### Task 4: Verify

```
PYTHONPATH=. pytest tests/api/test_webapp_trainer_profile.py tests/application/test_trainer_profile_completeness.py -q
```

TTV tests must stay green (AC-009). No production JS syntax errors (`node --check static/webapp/trainer-profile-main.js`).
