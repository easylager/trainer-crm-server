---
task_id: TASK-118
title: Junost (Minsk) ice parser adapter
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: []
execution_mode: SUPERVISED
lane: INGEST
created_at: 2026-09-17
updated_at: 2026-09-17
---

# Task

## Objective

Write the missing `IceParser` adapter for `junost_origin_html_v1` (arena_id=8, «Каток ХК Юность»), register it, and confirm the `ice_parser_jobs` row for this arena stays disabled and BY-egress-gated — the same terminal V1 state as `ledlife` (arena_id=4, TASK-083). Of the ~43 Belarus arenas, this and `ledlife` are the only two mass-skating targets without a working adapter; `ledlife` is blocked purely on a human buying a BY VPS (out of scope here). `junost` was missing the adapter class entirely.

## Business Context

`.ai/parsers/minsk-junost.md` (reverse-engineered spec, already merged via TASK-065/PR #33) documents that junost.by 403s any non-BY egress, and even a BY-egress Globalping probe comes back truncated (~10 KB) before it ever reaches the schedule grid. No BY-egress fetch has ever reached the real weekend grid, so the terminal V1 golden is `sessions: []` + `blocked_without_by_egress: true`. Fixtures already exist at `.ai/data/fixtures/minsk-junost/` (`expected.json`, `junost-origin.html` [403 body], `globalping-by-truncated.html` [200, cut before the grid], `hockey-skating.html` [price mirror, explicitly not a schedule fallback]).

**Premise correction found during research:** the task brief referenced `.ai/data/ice-parser-status.json` with a `spec_ready`/`spec_blocked` status vocabulary — that file does not exist. The real census is `.ai/data/minsk-parser-registry.yaml`, whose actual enum is `ready|partial|blocked|unknown|skipped`. This task updates that file instead, reusing `blocked` (the value already used for `ledlife`'s row), not inventing `spec_blocked`.

**Second premise correction:** `src/ingestion/seed_jobs.py::build_minsk_job_seeds()` derives one `ice_parser_jobs` seed per `.ai/parsers/minsk-*.md` spec file automatically (TASK-065, already merged) — it does not require a registered adapter. Since `minsk-junost.md` already existed before this task, the job-seeding behavior for arena_id=8 (`is_enabled=false`, `requires_by_egress=true`) was **already implemented and already covered** by `tests/ingestion/test_seed_jobs.py::test_real_minsk_registry_seeds_spec_jobs` (asserts `junost.is_enabled is False` and `junost.config["requires_by_egress"] is True`). This task's actual net-new work is the adapter class + registration + adapter-specific tests + the census row update — not the seeding pipeline itself.

## Scope

### In Scope
- `JunostHtmlParser` in `src/ingestion/adapters.py`: extract-only `IceParser`, recognizes the two known-blocked HTML shapes (`is_junost_blocked_snapshot`) and always returns an empty `Extraction` for V1 — no fabricated schedule, never reads the `junost.hockey.by` price mirror as a schedule source.
- Register `JunostHtmlParser` in `default_registry()` (`src/ingestion/parsers.py`).
- Unit tests against the fixtures (`tests/ingestion/test_junost_adapter.py`), TDD per AC.
- `.ai/data/minsk-parser-registry.yaml` arena_id=8 row updated: `parser_status`/`schedule_status` → `blocked` (mirrors `ledlife`'s row), `extractor` → `junost_origin_html_v1`, `sessions_extracted` → 0, `next_actions` records the adapter/job state and points at TASK-083 for the actual BY egress.

### Out of Scope
- `ledlife` (arena_id=4) and its BY-egress config — untouched.
- Enabling the junost job or provisioning any VPS/proxy — owner's money/account, not this task (TASK-083).
- Client-facing UI (`static/webapp/*`).
- PR to `master`.
- Rewriting `src/ingestion/seed_jobs.py` or the seeding pipeline — already generic and already tested; not touched.

## Acceptance Criteria

### AC-001
`JunostHtmlParser` exists, is registered in `default_registry()` under `junost_origin_html_v1`, and extracting the 403 fixture (`junost-origin.html`) and the truncated Globalping fixture (`globalping-by-truncated.html`) both produce the documented blocked/empty behavior — `slots == []`, matching `.ai/data/fixtures/minsk-junost/expected.json` (`sessions: []`, `blocked_without_by_egress: true`). The adapter never reads the `hockey-skating.html` price mirror as a schedule source.
Status: VERIFIED
Verification: `pytest tests/ingestion/test_junost_adapter.py -q` — `test_junost_adapter_registered_in_default_registry`, `test_junost_403_fixture_matches_expected_empty_golden`, `test_junost_403_body_detected_as_blocked`, `test_junost_truncated_globalping_snapshot_detected_as_blocked`, `test_junost_adapter_never_reads_the_hockey_by_price_mirror`, `test_junost_adapter_never_persists_to_ice_sessions` — 8 passed.

### AC-002
`ice_parser_jobs` seeds a row for arena_id=8 with `parser_key=junost_origin_html_v1`, `requires_by_egress=true`, `is_enabled=false` — mirrors the `ledlife` job row exactly, not enabled.
Status: VERIFIED
Verification: already generically implemented and covered pre-existing by `tests/ingestion/test_seed_jobs.py::test_real_minsk_registry_seeds_spec_jobs` (asserts `by_key["junost_origin_html_v1"].is_enabled is False` and `.config["requires_by_egress"] is True`) — this task did not need to add seeding code; confirmed still green (`pytest tests/ingestion/test_seed_jobs.py -q` → 8 passed) after this task's census-row edit.

### AC-003
Without BY-egress configured on the worker, the scheduler blocks the junost job before ever invoking the parser (`status=blocked`, `error_code=requires_by_egress`) — same guarantee as TASK-083's ledlife AC-003. Once BY egress is configured, the parser runs but still yields zero sessions against the fixture (never fabricates a grid).
Status: VERIFIED
Verification: `tests/ingestion/test_junost_adapter.py::test_junost_job_still_blocked_without_by_egress_configured` and `::test_junost_job_extracts_empty_when_by_egress_is_configured`, reusing the generic `IceIngestScheduler(by_egress_configured=...)` gate already proven by TASK-083's `tests/ingestion/test_scheduler.py::test_requires_by_egress_job_still_blocked_without_worker_config` / `::test_requires_by_egress_job_runs_when_worker_has_by_egress_configured`.

## Technical Notes
- `IceParser` ABC / registry: `src/ingestion/parsers.py`. Adapter style modeled on the existing Minsk adapters in `src/ingestion/adapters.py` (single file — no `adapters_regional_batch_*.py` files exist in this repo; that was a stale assumption in the task brief).
- Blocked-shape detection (`is_junost_blocked_snapshot`): literal `403 Forbidden` nginx body, or absence of a closing `</html>` tag (the Globalping truncation signature — confirmed no `</html>` present in `globalping-by-truncated.html`). Defensive default: anything not demonstrably a complete page is treated as blocked.
- Scheduler-level BY-egress gating (`src/ingestion/scheduler.py:77-88`, `config_requires_by_egress`) is fully generic on `job.config["requires_by_egress"]` — it was not modified and needed no change for this task; TASK-083 already wired the worker-level `by_egress_configured` fallback.
- One-shot runner allowlist `scripts/run_ice_ingest_once.py::MINSK_MK_PARSER_KEYS` intentionally still excludes `junost_origin_html_v1` (and `ledlife_origin_html_v1`) — confirmed unaffected by registering the parser in `default_registry()`, since the allowlist is a separate gate (`tests/ingestion/test_run_ice_ingest_once.py::test_one_shot_only_bumps_merged_minsk_mk_keys` still green).

## Execution History
- **TASK_CREATED** (2026-09-17) — agent: read `.ai/parsers/minsk-junost.md` + fixtures + existing `ledlife`/regional adapter code; found no adapter class existed for junost (confirmed `ledlife` also has none — expected, out of scope). Found the job-seeding pipeline (`build_minsk_job_seeds`) is spec-file-driven and already produces the correct disabled junost row pre-existing (TASK-065, PR #33) — narrowed scope to adapter code + tests + census update.
