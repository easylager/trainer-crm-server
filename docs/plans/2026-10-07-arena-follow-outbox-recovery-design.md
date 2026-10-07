# Arena follow outbox: concurrency and recovery

## Goal

Prevent notification delivery from becoming stuck when a publish races with a
Telegram send, while preserving every schedule/reopen change and avoiding sends
from stale claims.

## Design

Use the `arena_follows` row as the serialization point. Every transaction that
changes an outbox row first locks its follow row, then locks or updates
notifications. Publishers lock active follows in stable `id` order. The
dispatcher recovers claims in a separate transaction, rechecks each claim
after acquiring the follow lock, and claims work with a timestamped lease.

Requeueing is centralized. If no pending notification of the same follow and
kind exists, the sending row returns to pending. Otherwise the pending row
absorbs the sending row: schedule slots are combined with `net_slots`, the
newer event supplies `hhmm`, `created_at`, and rendered text, and `attempts`
keeps the maximum. Reopen payloads preserve `keep` by logical OR. An empty
schedule diff removes the pending row. In all merge cases the old row closes as
`merged`.

Pending inserts use the partial unique index with `ON CONFLICT ... DO NOTHING
RETURNING id`; a conflict is resolved by rereading and merging the pending row.
The existing `0225_arena_follows` migration remains the sole head and gains
`claimed_at` and the `merged` status. Sent/failed/muted transitions require
`sending`; lost claims produce a warning and metric rather than aborting a
dispatch. Reopen sends still mute the follow even if the notification claim
was taken over.

## Delivery and recovery

Each dispatch unit is one follow and is isolated with error handling. Before a
send, refresh the claim timestamp and apply a local lock timeout. Bound sends
to about 60 seconds. Retry delays above 30 seconds are requeued instead of
sleeping in the dispatcher. Recovery considers null or older-than-ten-minute
claims independently of quiet hours; outside follow hours it only requeues and
returns without sending.

## Verification

Use real PostgreSQL with independent `NullPool` connections and explicit
commits for concurrency tests. Prove the race cases first against the current
implementation, then prove the fixed behavior. Run migration downgrade to
`0224_hockey_practice_kind` and upgrade to the single head, the full Python
suite, JavaScript tests under `TZ=UTC`, and Ruff on a disposable local test
database. Never use `trainer_crm`, `trainer_crm_test`, or production; drop the
temporary database after verification. Do not push.
