# EPIC3 Arenas — Spec-Driven Development & Release Plan (Agents)

> **For Claude / Cursor agents:** **Entrypoint:** [`docs/epics/ice-discovery/agent-start.md`](../../docs/epics/ice-discovery/agent-start.md) — read first.  
> Git lifecycle: [`docs/epics/ice-discovery/agent-git.md`](../../docs/epics/ice-discovery/agent-git.md) — **toolkit verify ≠ done; done = merge into `release/ice-discovery`.**  
> This file is the **release + operating system** for Ice Discovery. Specs: `.ai/tasks/TASK-*.md`. Do **not** invent scope.  
> Per-task execution: wave plan or one TASK after `/plan` — never implement this whole file at once.  
> REQUIRED before code: TASK Objective, Scope, AC, Out of Scope, Technical Notes, Tests.

**Goal:** Ship arena-as-screen (ice + trainers) for **Minsk** in gated releases, with agents implementing from locked specs and humans only clearing product gates.

**Architecture:** Three data streams (static / ice schedule / internal slots) meet on one arena card. Levels A/B/C on read. Ingestion never writes canonical tables directly (`observations` → resolve). Client IA: tab «Лёд» replaces «Тренеры» as lens.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic; Telegram Mini App (`static/webapp/`); pytest; Leaflet+OSM (existing catalog map).

**City lock:** Минск (2026-09-04).

**Integration branch:** `release/ice-discovery` (never open TASK PRs to `master`).

---

## 0. Spec stack (source of truth)

| Priority | Artifact | Role |
|---|---|---|
| 0 | `docs/epics/ice-discovery/agent-git.md` | **Branches + lifecycle** — where work ends |
| 1 | `.ai/tasks/TASK-*.md` | **Executable spec** — AC, scope, tests, file hints |
| 2 | `design/prototypes/2026-09-arenas-client-app.html` | Visual SoT for client UI |
| 3 | `design/arenas-client-app.md` | Product IA & rules |
| 4 | `design/ingestion-system.md` | Data pipeline & admin budget |
| 5 | `docs/epics/ice-discovery/epic.md` | Map, metrics, estimate |
| 6 | This file | Release trains, agent protocol, parallelism |

**Conflict rule:** TASK AC wins over prose in designs. Prototype wins over ad-hoc UI taste. If TASK contradicts prototype → **stop and ask human**, do not “improve”.

**Out of initiative (never implement in these releases):** ticket sales, rink operator panel, SEO public pages, arena reviews, non-ice verticals.

---

## 1. Agent operating protocol (every TASK)

### 1.0 Toolkit is middle, not end

```
ai-toolkit-max:  READY → … → execute → verify(AC)
                              │
                              ▼  NOT FINISHED
git:             feat/TASK-NNN-*  ──PR──►  release/ice-discovery
                              │
                              ▼  TASK status: MERGED  ← finished for agents
release slice:   release/ice-discovery ──PR──► master   (after G-R*, separate act)
```

`/verify` PASS means “safe to open/merge PR”. It does **not** authorize completion without train merge. Prefer `status: MERGED` after the train merge (see git doc). Legacy `DONE` only if Execution History also records `merged_into: release/ice-discovery` + SHA.

### 1.1 Start

1. `git fetch` → checkout **`release/ice-discovery`** → pull (create it in R0 if missing; **do not** branch from stale `master` for initiative work).  
2. `git checkout -b feat/TASK-NNN-short-kebab` from that tip.  
3. Read: `docs/epics/ice-discovery/agent-git.md`, current R* section below, the TASK file, linked design slices.  
4. Confirm `depends_on` tasks are **`MERGED`** (on the train), not only locally verified.  
5. Set TASK frontmatter: `status: IN_PROGRESS`, `phase: execute`, `branch: feat/TASK-NNN-…`, append `PHASE_STARTED | execute`.  
6. If plan/slices empty and TASK ≥8 SP: `/plan` first → `docs/plans/2026-09-04-epic3-TASK-NNN.md`.

### 1.2 Spec-driven loop (TDD) — on the feature branch only

For each AC (or slice):

1. Failing test (when AC says `automated/*`).  
2. Minimal implementation.  
3. Pass tests.  
4. Atomic commit on `feat/TASK-NNN-…`.

Ops tasks (063, 064): same branch/PR rules; commit data artifacts to the train via PR.

### 1.3 After verify — finish on the release train

Agent **must** still:

1. Push `feat/TASK-NNN-…`.  
2. Open PR with **`--base release/ice-discovery`** (title `TASK-NNN: …`, body: TASK path + AC list + test commands).  
3. Wait for CI green.  
4. Merge into `release/ice-discovery`.  
5. Set `status: MERGED`, write `pr_url`, merge SHA, `PHASE_COMPLETED | merged-to-release-train` in Execution History.  
6. Delete feature branch.  
7. One line in EPIC3 Execution History: `TASK-NNN MERGED → release/ice-discovery`.

**Do not** merge `release/ice-discovery` → `master` as part of a TASK unless the human explicitly starts a release cut.

### 1.4 Definition of “task complete” (all required)

- [ ] Every AC PASS or WAIVED with human quote  
- [ ] Out of Scope untouched  
- [ ] TASK tests green  
- [ ] Mini App cache-busters bumped if needed  
- [ ] PR merged into **`release/ice-discovery`**  
- [ ] `status: MERGED` (+ SHA / pr_url)

### 1.5 Forbidden

- PR into `master` for initiative TASK work  
- Declaring task done after toolkit `/verify` without train merge  
- Branching feature work from `master` while the train exists  
- Expanding scope “while we’re here”  
- Scraping third-party photos  
- Parsers writing canonical tables (bypass observations)  
- Shipping R3b navigation before R2 gate  
- Auto-publishing zero-session extractions  

### 1.6 Human gates (agent must stop)

| Gate | When | Question |
|---|---|---|
| G-R1 | End R1 on train | Booking filter → correct arena; slug/district; 064 ceiling? |
| G-R2 | End R2 | Arena card → trainer? **No → halt heavy ingestion.** |
| G-R3a | After 064 | Need OCR (068)? |
| G-R3 | End R3a | Level A ↑ without admin minutes ↑? |
| G-R4 | End R3b | Reach to arena card; time-to-value? |

After G-R*: human (or instructed agent) opens PR **`release/ice-discovery` → `master`** for that slice.

---

## 2. Branch & PR strategy

```
master
  └── release/ice-discovery              ← RELEASE TRAIN (long-lived)
        ├── feat/TASK-048-arena-entity   ← PR into release/ice-discovery
        ├── feat/TASK-056-booking-place
        └── feat/TASK-064-minsk-census
```

| Rule | Detail |
|---|---|
| Train | `release/ice-discovery` from `master` (R0); keep synced: merge/rebase `master` → train regularly |
| Task branch | always from **current train tip** |
| PR base | **only** `release/ice-discovery` |
| Parallelism | different TASK ids; serialize if same hot files (`models.py`, `catalog-main.js`, `public.py`) |
| Cleanup | delete `feat/TASK-*` after merge |

**Release cut (slice → prod):** PR `release/ice-discovery` → `master` + deploy + gate checklist in EPIC3. Not the same as merging a TASK.

---

## 3. Release trains

Aligned with ingestion order: **foundation → first screen → data pipeline → navigation**.

| Release | Ship to prod? | Tasks | ~SP | Theme |
|---|---|---|---|---|
| **R0** | no (tooling) | — | 0 | Create `release/ice-discovery`, git doc, stubs 067…070 |
| **R1** | yes after G-R1 | 048, 056, 057, 058, **064** | 31 | Entity + booking truth + Minsk census |
| **R2** | yes after G-R2 | 049, 050, 063, 051, 052 | 42 | First arena card + seeded Minsk ice |
| **R3a** | yes after G-R3 | 059, 065, 060, 061*, 066, 062 | ~60 | Ingestion without full nav |
| **R3b** | yes after G-R4 | 053, 054, 055 | 24 | Tab «Лёд» + map + hub links |
| **R4** | yes | 067–070 as approved | ~21–34 | Confidence gate, OCR if needed, enrich, photos |

\*061 may shrink/grow after G-R3a (064 results).

```
R0 ──► R1 ──► R2 ──G-R2──► R3a ──► R3b ──► R4
              │              ▲
              └── 064 ───────┘ (feeds 061/068)
```

All R1–R4 **code** lands on `release/ice-discovery` first; `master` only via release-cut PRs.

---

## 4. Release details (agent entry)

### R0 — Bootstrap (human or agent, &lt;1h)

**Steps:**
1. Create **`release/ice-discovery`** from `master` and push.  
2. Ensure this plan + `docs/epics/ice-discovery/agent-git.md` are on the train (commit there or merge via PR).  
3. File TASK-067…070 stubs if missing.  
4. Commit message: `chore: ice-discovery release train + agent git lifecycle`.

**Done when:** agents can `checkout release/ice-discovery` and open TASK branches from it.

---

### R1 — Foundation & truth (parallel lanes)

**Specs:**  
- [TASK-048](../../.ai/tasks/TASK-048.md) — arena entity  
- [TASK-056](../../.ai/tasks/TASK-056.md) — place = event arena  
- [TASK-057](../../.ai/tasks/TASK-057.md) — `is_public`  
- [TASK-058](../../.ai/tasks/TASK-058.md) — `trainer_cities`  
- [TASK-064](../../.ai/tasks/TASK-064.md) — Minsk source census (ops)

**Parallelism:**

| Lane | Tasks | Shared files risk |
|---|---|---|
| A | 048 | `models.py`, migrations, admin-dicts |
| B | 056 → then 057 | booking use cases, `trainer_arenas` |
| B2 | 058 | trainer repo / catalog filters — **after or carefully beside 057** |
| D | 064 | no code conflict — spreadsheet/import |

**Suggested agent order if single agent:** 048 ∥ 056 → 057 → 058; 064 anytime.  
Each lane ends with **PR → `release/ice-discovery`**, not local verify alone.

**Key code anchors (048):**
- Model: `src/infrastructure/db/models.py` (`Arena` ~171)  
- Migration: next after `0191_by_small_city_discount.py`  
- Geocode: `scripts/geocode_arena_addresses.py`  
- Admin: `static/webapp/admin-dicts.html`

**R1 Definition of Done:**
- 048, 056, 057, 058, 064 all **`MERGED`** into `release/ice-discovery`  
- 064 ceiling recorded in TASK + EPIC3  
- **G-R1** signed → then PR train → `master`

**Wave plan:** `docs/plans/2026-09-04-epic3-r1-foundation.md`

---

### R2 — First screen (product gate)

**Specs:** 049 → 050 → 063 (manual) → 051 → 052  

**Order (hard):**
1. 049 media (needs 048 **MERGED**)  
2. 050 ice_sessions + admin CRUD  
3. 063 seed **10–15 Minsk** arenas deep  
4. 051 public read API (levels A/B/C on read)  
5. 052 arena card UI  

Each step: feature branch → merge to train. **G-R2** before R3a scale-up.

**Ship note:** soft entry to card OK before tab rename (053).

---

### R3a — Data without empty navigation

**Specs:** 059 → 065 → 060 → 066 → 061 → 062 — each **MERGED** to train.  
**G-R3a** after 064 before locking 061/068.

---

### R3b — Navigation

**Specs:** 053 → 054 → 055 — after R2 gate; merge to train; **G-R4**; release cut.

---

### R4 — Hardening

| TASK | When |
|---|---|
| 067 Confidence gate / autopublish | After 066 metrics acceptable |
| 068 Image/PDF extract | Only if 064 shows material share |
| 069 Static enrich from directories | After 065 spike |
| 070 Photo placeholders + policy | With/after 049 |

Same git lifecycle: `feat/TASK-*` → `release/ice-discovery`.

---

## 5. How to spawn a wave implementation plan (agents)

```text
Read docs/epics/ice-discovery/agent-git.md first.
Use writing-plans + executing-plans.
Initiative: Ice Discovery. Train: release/ice-discovery. Release: R1. City: Минск.
Specs: .ai/tasks/TASK-048.md (…).
Rules: docs/plans/2026-09-04-epic3-arenas-sdd-release-plan.md
Every task ends with PR base=release/ice-discovery and status MERGED — not toolkit verify alone.
```

```text
Use subagent-driven-development on docs/plans/2026-09-04-epic3-r1-foundation.md
One subagent per TASK; after verify, open/merge PR into release/ice-discovery; stop at G-R1.
```

---

## 6. Test & verify matrix (minimum)

| Layer | Command / check |
|---|---|
| Unit/integration | `pytest` as named in TASK |
| Migration | upgrade/downgrade smoke |
| Mini App | bump `?v=` |
| Ingestion | replay snapshot; hash no-op |
| Ops | 063/064 results in TASK files |
| Git | PR base is `release/ice-discovery`; CI green before merge |

CI must stay green; do not `--no-verify`.

---

## 7. Metrics to instrument by release

| Metric | From release |
|---|---|
| Arena card opens | R2 |
| Arena → trainer CTR | R2 (G-R2) |
| % arenas level A (Minsk) | R2 seed; R3a automation |
| Admin minutes / week | R3a |
| Sessions reaching arena card | R3b |

---

## 8. Risk register (agent-visible)

| Risk | Mitigation |
|---|---|
| Agents stop at `/verify` | Hard rule §1.0 + `MERGED` status |
| PR into master | Forbidden; review base branch |
| Empty cards before data | R3a before R3b; R2 seed |
| LLM silent wrong schedule | 066 + confidence gate |
| Parallel clash | one TASK/PR; hot-file serialize |

---

## 9. Checklist to start

1. [ ] Create/push `release/ice-discovery`  
2. [ ] Land this plan + `docs/epics/ice-discovery/agent-git.md` on the train  
3. [ ] Agent A: branch `feat/TASK-048-…` from train → … → PR → **MERGED**  
4. [ ] Agent B: same for TASK-056  
5. [ ] Ops: TASK-064 on its branch → PR to train  
6. [ ] G-R1 → release cut train → `master`  

---

## References

- Git lifecycle: `docs/epics/ice-discovery/agent-git.md`  
- Epic map: `docs/epics/ice-discovery/epic.md`  
- Ingestion: `design/ingestion-system.md`  
- Client design: `design/arenas-client-app.md`  
- Prototype: `design/prototypes/2026-09-arenas-client-app.html`  
- System diagram: `design/prototypes/2026-09-arenas-system-design.html`
