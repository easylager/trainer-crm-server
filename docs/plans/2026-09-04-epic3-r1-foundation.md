# EPIC3 R1 — Foundation Implementation Plan (Agents)

> **For Claude:** **Entrypoint:** [`docs/epics/ice-discovery/agent-start.md`](../../docs/epics/ice-discovery/agent-start.md).  
> REQUIRED SUB-SKILL: executing-plans / subagent-driven-development **task-by-task**.  
> **Git:** [`docs/epics/ice-discovery/agent-git.md`](../../docs/epics/ice-discovery/agent-git.md) — done = **MERGED** into `release/ice-discovery`, not toolkit `/verify`.  
> Parent OS: `docs/plans/2026-09-04-epic3-arenas-sdd-release-plan.md`  
> Specs: `.ai/tasks/TASK-048.md`, `TASK-056.md`, `TASK-057.md`, `TASK-058.md`, `TASK-064.md`

**Goal:** Land arena entity + booking place truth + multi-city trainer visibility + Minsk source census — all **merged into `release/ice-discovery`** (Release 1).

**Architecture:** Parallel lanes A (048) and B (056→057→058); ops lane D (064). No client «Лёд» UI in R1.

**Tech Stack:** Alembic, SQLAlchemy models, booking use cases, trainer catalog filters, admin-dicts Mini App.

**City:** Минск.  
**Train:** `release/ice-discovery`.  
**Task branches:** `feat/TASK-NNN-short-kebab` from train tip → PR `--base release/ice-discovery`.

---

### Task 0 (every TASK below): branch + merge ritual

1. `git checkout release/ice-discovery && git pull`  
2. `git checkout -b feat/TASK-NNN-…`  
3. Toolkit execute/verify on that branch only  
4. `gh pr create --base release/ice-discovery …`  
5. Merge → set TASK `status: MERGED` + SHA — **only then** the TASK is complete  
6. Delete feature branch  

Depends_on = peer is **MERGED**, not merely verified locally.

---

### Task 1: TASK-048 — Arena as entity

**Spec:** `.ai/tasks/TASK-048.md` (AC-001…005, EDGE-001…003)  
**Branch:** `feat/TASK-048-arena-entity`  
**Files (from spec):**
- Modify: `src/infrastructure/db/models.py` (`Arena` ~171)
- Create: `migrations/versions/0192_arena_profile_fields.py` (number = next free after 0191)
- Modify: `scripts/geocode_arena_addresses.py` (reverse district backfill)
- Modify: `static/webapp/admin-dicts.html` + admin PATCH arenas
- Test: `tests/` per TASK Tests section

**Step 1:** Read full TASK-048; copy AC ids into commit messages.  
**Step 2:** Migration + model for slug, district, amenities jsonb, status, hours, season, contacts — per In Scope.  
**Step 3:** TDD AC-001 (slug unique per city, idempotent backfill), AC-004 (amenities dictionary), EDGE-001, EDGE-003.  
**Step 4:** Admin PATCH/GET round-trip (AC-003); draft status hidden from public read path if it exists, else stub filter used by future 051 (AC-005).  
**Step 5:** Run reverse geocode dry-run for Minsk; document district coverage toward 90% (AC-002).  
**Step 6:** Push → PR → **merge into `release/ice-discovery`** → `status: MERGED`.

```bash
pytest tests/ -k "arena_slug or arena_amenities or arena_status" -v
```

---

### Task 2: TASK-056 — Place = event arena

**Spec:** `.ai/tasks/TASK-056.md`  
**Branch:** `feat/TASK-056-booking-place`  
**Depends:** none (parallel with 048)  
**Focus:** `resolve_arena_for_client_self_booking` and related booking paths — filter arena X must book on X.

**Step 1:** Write failing API/integration test: catalog filter arena X → booking.arena_id == X (not primary).  
**Step 2:** Implement minimal fix per TASK Technical Notes.  
**Step 3:** Regression: no filter → still primary default.  
**Step 4:** PR → merge to train → `MERGED`.

---

### Task 3: TASK-057 — `trainer_arenas.is_public`

**Spec:** `.ai/tasks/TASK-057.md`  
**Branch:** `feat/TASK-057-arena-is-public`  
**Depends:** prefer after 056 **MERGED** if same files  
**Step 1:** Migration `is_public` + defaults.  
**Step 2:** Tests: showcase vs schedule eligibility split.  
**Step 3:** PR → merge to train → `MERGED`.

---

### Task 4: TASK-058 — `trainer_cities`

**Spec:** `.ai/tasks/TASK-058.md`  
**Branch:** `feat/TASK-058-trainer-cities`  
**Depends:** 057 **MERGED** if catalog overlap  
**Step 1:** Migration + backfill from `city_id`.  
**Step 2:** Test: trainer with Minsk+Moscow arenas visible in both catalogs.  
**Step 3:** PR → merge to train → `MERGED`.

---

### Task 5: TASK-064 — Minsk source census (ops)

**Spec:** `.ai/tasks/TASK-064.md`  
**Branch:** `feat/TASK-064-minsk-census`  
**Mode:** MANUAL / SUPERVISED — spreadsheet OK; still PR data file into the train  

**Deliverables:**
1. Table: arena_id, name, schedule_url(s), format (site|post|image|pdf|none), price_present, update_cadence  
2. ≥90% active Minsk arenas classified (AC-001)  
3. Distribution % (AC-002)  
4. Ceiling for auto level-A (AC-003) written into TASK + EPIC3  
5. Importable CSV/JSON for TASK-065 (AC-004)

**Commit path example:** `data/minsk-arena-sources-2026-09.csv` + TASK results → PR → **MERGED**.

---

### Task 6: R1 gate (human)

**Stop feature agents.** Confirm all five TASK statuses are **`MERGED`**. Fill G-R1 in EPIC3. Then release cut: PR `release/ice-discovery` → `master` (not a TASK agent default).

---

## Execution notes

- Prefer **one subagent per Task 1–5**.  
- Spec review against TASK AC before quality review.  
- Subagent exit criteria: **merged to `release/ice-discovery`**, not “tests pass”.  
- Do not start TASK-049/050 in this plan.
