"""
LINKEDIN POST — copy below
──────────────────────────

Python's datetime is proof that time travel exists — though only, it seems, in production.
Here are five mistakes we keep shipping whenever we touch timestamps.
What are the most common time-related bugs you've hit in Python — what do you think?

(Snippets illustrate the idea — not copy-paste production code.)

#Python #SoftwareEngineering #Backend #Datetime #UTC #TechTips #Programming
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


# ── 1. datetime.now() vs now(UTC) — a naive "now" is a fiction ─────────────
# Why it bites: datetime.now() is "wall clock on this box". Your laptop in
# Tbilisi, a CI runner in Frankfurt, and a prod pod in us-east-1 all answer
# differently — and none of them say which zone they meant.
# Rule of thumb: store and compare in UTC; convert only when a human looks.


# BAD: naive local time of whichever machine happened to run the code
# tzinfo is None — you cannot tell UTC from local, ever

t =  datetime.now()

# → 2026-08-01 15:00:00   (no zone attached)

# GOOD: one shared instant every service can agree on
t = datetime.now(timezone.utc)
# → 2026-08-01 12:00:00+00:00


# ── 2. .replace(tzinfo=…) vs .astimezone(…) — labelling ≠ converting ──────
# Why it bites: .replace(tzinfo=…) keeps the same wall-clock digits but
# changes which instant those digits mean. .astimezone(…) keeps the instant
# and recalculates the wall clock for the target zone.
# Classic failure mode: "we shifted to local" — you didn't; you relabelled.


utc = datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc)

# BAD: same digits, new sticker — 12:00 UTC pretending to be 12:00 in Tbilisi
fake = utc.replace(tzinfo=ZoneInfo("Asia/Tbilisi"))
# → 2026-03-29 12:00:00+04:00   (wrong instant: four hours early)

# GOOD: same moment on the timeline; local clock updated for the city
local = utc.astimezone(ZoneInfo("Asia/Tbilisi"))
# → 2026-03-29 16:00:00+04:00   (correct: UTC+4 that day)


# ── 3. "date time" vs "dateTtimeZ" — the format is the contract ────────────
# Why it bites: the real hazard is a missing offset, not the missing T.
# Without Z / ±HH:MM the value is naïve — local? UTC? already shifted?
# Every client invents an answer. T + Z (or +00:00) pins one instant.
# Z = UTC. +00:00 is the same idea, spelled out.


# BAD: no offset → fromisoformat yields naïve (tzinfo is None)
NAIVE_STAMP = "2026-08-01 12:00:00"
# datetime.fromisoformat(NAIVE_STAMP) → 2026-08-01 12:00:00  (no zone)

# GOOD: offset present — one unambiguous instant
ISO_STAMP = "2026-08-01T12:00:00Z"
# replace() keeps this portable; on 3.11+ fromisoformat accepts Z directly
PARSED = datetime.fromisoformat(ISO_STAMP.replace("Z", "+00:00"))
# → 2026-08-01 12:00:00+00:00
# Tip: serialise with timezone.utc; .isoformat() emits +00:00 (not Z) by default


# ── 4. "-3.0" vs "Asia/Tbilisi" — an offset is not a timezone ──────────────
# Why it bites: an offset answers "how many hours from UTC right now?"
# A timezone answers "what are the rules for this place over time?"
# Cities change offsets (DST, politics). Hard-coding UTC−3 freezes yesterday's
# weather as tomorrow's law — invoices, reminders, and reports drift quietly.
# Still store/compare in UTC (tip 1). Use a named zone only when you need
# that city's wall clock — display, "business hours", local midnights.


# BAD: fixed offset — no DST, no history, no "what did this city do in 2015?"
offset = timezone(timedelta(hours=-3))
local = datetime.now(offset)
# Fine for "show as UTC−3 today"; fatal for "user lives in that city"

# GOOD: UTC as the source of truth, then convert with an IANA zone name
now_utc = datetime.now(timezone.utc)
local = now_utc.astimezone(ZoneInfo("Asia/Tbilisi"))
# Same instant; wall clock follows city rules (DST, history, politics)
# Asia/Tbilisi is UTC+4 year-round today; many other cities still spring/fall


# ── 5. Mixing naive and aware — two clocks, one subtraction ────────────────
# Why it bites: an "aware" datetime knows its zone (tzinfo set). A "naive"
# one does not (tzinfo is None). Python 3 refuses to subtract or compare them
# (TypeError) — the kind outcome. The unkind one is "fixing" it by stamping
# timezone.utc onto a local naïve value (or stripping tzinfo from the aware
# side) so API-UTC and worker-local get treated as the same clock.
# Symptom in prod: tokens expire early/late; jobs fire an hour off after DST.


created_at = datetime.now(timezone.utc)  # aware — from API / database (UTC)
expires_at = datetime.now()              # naive — "now" on the worker's local clock

# BAD: different kinds of datetime in one expression
delta = expires_at - created_at
# → TypeError: can't subtract offset-naive and offset-aware datetimes
# Tempting "fix": expires_at.replace(tzinfo=timezone.utc) — labels local as UTC

# GOOD: same awareness everywhere; UTC in the core, local only at the edges
expires_at = datetime.now(timezone.utc)  # also aware, also UTC
delta = expires_at - created_at          # both speak the same language
