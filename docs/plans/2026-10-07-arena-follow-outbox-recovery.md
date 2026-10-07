# Arena follow outbox recovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make arena-follow notification delivery safe under publish/send races, stale claims, and dispatcher retries.

**Architecture:** Serialize outbox changes on `arena_follows` rows, always locking the follow before notification rows. Centralize requeue/merge, lease claims with `claimed_at`, and guard terminal transitions by `status='sending'`. Keep the existing `0225_arena_follows` revision and extend its schema/check constraints in place.

**Tech Stack:** Python 3, SQLAlchemy async sessions, PostgreSQL, Alembic, pytest/pytest-asyncio, Node test runner, Ruff.

---

### Task 1: Establish disposable PostgreSQL verification target

**Files:**
- No repository files.

**Step 1: Resolve local connection settings without printing credentials**

Use the local PostgreSQL connection settings only as a source for host/user
configuration; override both database names to a unique temporary name such as
`trainer_crm_test_arena_outbox_20261007`. Never connect tests or Alembic to
`trainer_crm`, `trainer_crm_test`, or a managed host.

**Step 2: Create the temporary database and export explicit URLs**

Set both `DATABASE_URL` (async driver) and `DATABASE_URL_SYNC` (psycopg) to the
temporary database for every Python/Alembic invocation. Verify the parsed host
and database name before running commands.

### Task 2: Add real-connection regression tests and prove they fail first

**Files:**
- Modify: `tests/application/test_arena_follows.py`

**Step 1: Add a `NullPool` engine helper and independent committed sessions**

Build test sessions from explicit test URLs, use two independent connections,
and commit from each connection. Keep these concurrency tests independent of
the rollback-scoped `db_session` fixture.

**Step 2: Add the race/recovery cases from the acceptance list**

Cover same-pair stale sending merge, enqueue during a failing send, reopened
success with an extra schedule row, publisher lock wait, publish/admin reopen
race, real partial-index conflict fallback, null/one-minute/eleven-minute
leases, lost claim during send, quiet-hours recovery, and unsubscribe during
publish. Assert merged payloads, notification counts, sends to unrelated
subscribers, and no uncaught database errors.

**Step 3: Run each new test against the unmodified application implementation**

Because the baseline schema lacks `claimed_at`, add that column only to the
disposable test database for this red run; do not change repository migration
or application code until the tests demonstrate the old behavior. Run each
targeted test by node id and record its expected failing assertion/exception.

### Task 3: Extend migration and ORM model in place

**Files:**
- Modify: `migrations/versions/0225_arena_follows.py`
- Modify: `src/infrastructure/db/models.py`
- Test: `tests/application/test_arena_follows.py`

**Step 1: Add `claimed_at` and permit `merged`**

Keep revision `0225_arena_follows`; update the migration and model status check,
and add a nullable timezone-aware `claimed_at` column. Make downgrade map
`merged` to an existing terminal status before restoring the old check.

**Step 2: Verify migration round trip**

Run Alembic downgrade to `0224_hockey_practice_kind`, then upgrade to head;
assert exactly one head and verify the merged constraint and claimed_at column.

### Task 4: Serialize enqueue and centralize pending conflict/merge

**Files:**
- Modify: `src/application/arena_follow_notify.py`
- Test: `tests/application/test_arena_follows.py`

**Step 1: Lock follows in stable order**

Add `FOR UPDATE` to `_active_follows` after `ORDER BY id`; ensure publish,
admin reopen, and unsubscribe coordination all use the follow row as the first
lock in the transaction.

**Step 2: Make `_upsert_pending` conflict-safe**

Use exactly `ON CONFLICT (follow_id, kind) WHERE status = 'pending' DO NOTHING
RETURNING id`. If insertion loses the race, reread the pending row under lock
and merge rather than raising or overwriting concurrent schedule slots.

**Step 3: Implement shared payload merge and `_requeue_or_merge`**

Lock the follow first, then reread sending and pending rows. Merge schedule
slots through `net_slots`; use max attempts and take `hhmm`/`created_at` from
the newer row, rebuild text, and compute `not_before` with
`push_out_of_quiet`. Merge reopened `keep` with OR. If a schedule merge is
empty, delete its pending row. Close the old notification as `merged`.

**Step 4: Route every requeue through the helper**

Replace `_release_sending`, extra-row returns, and unconditional recovery with
the common helper. Recheck status and claim timestamp after obtaining locks.

### Task 5: Lease claims and harden dispatch transitions

**Files:**
- Modify: `src/application/arena_follow_notify.py`
- Test: `tests/application/test_arena_follows.py`

**Step 1: Recover claims in their own transaction**

Select `claimed_at IS NULL OR claimed_at < now() - interval '10 minutes'`;
recover outside the row-claim transaction. Recovery runs even outside follow
hours, but at night only updates the queue and returns without sending.

**Step 2: Claim per follow with bounded locks**

Set a local `lock_timeout`, lock the follow before notification rows, and
refresh `claimed_at` immediately before each send (or claim one follow at a
time). After the follow lock, verify status and lease again.

**Step 3: Bound send and retry behavior**

Wrap each send in `asyncio.wait_for` around 60 seconds. If Telegram
`retry_after` exceeds 30 seconds, requeue instead of sleeping. Isolate every
follow's dispatch in `try/except`, allowing later follows to continue.

**Step 4: Guard terminal state changes**

Only transition `sending` rows to `sent`, `failed`, or `muted`. Check update
rowcount; on zero log a warning and emit the metric without raising. For
reopened messages, still mute the follow after successful send even if the
notification claim was lost. Make `_mark_sent` lock the follow before the
notification row.

### Task 6: Prove behavior and clean up

**Files:**
- Test: `tests/application/test_arena_follows.py`
- Verify: migration graph, complete Python suite, JavaScript suite, Ruff.

**Step 1: Run all new race tests and the arena-follow test module**

Run the concurrency tests on PostgreSQL with independent `NullPool` sessions,
then `pytest tests/application/test_arena_follows.py`.

**Step 2: Run migration round trip and full verification**

On the disposable database, run downgrade to 0224 and upgrade head, then full
pytest with both explicit database URLs. Also run `TZ=UTC node --test
tests/js/*.test.js` and Ruff on changed Python files.

**Step 3: Verify database isolation and remove the temporary database**

Confirm no command used the dev/test/production database, drop only the unique
temporary database, and verify the worktree contains no generated artifacts.

**Step 4: Commit changes without pushing**

Commit the approved design/plan separately and implementation in reviewable
commits. Do not push or force-push.
