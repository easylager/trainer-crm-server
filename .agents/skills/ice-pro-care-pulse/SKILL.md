---
name: ice-pro-care-pulse
description: >-
  Writes copy and cadence for Ice Pro care pulses (silence-aware Telegram check-ins).
  Use when adding, editing, or reviewing trainer/client presence notifications, care pulses,
  retention pings, «чтобы бот не терялся», or calm/trust-building push copy.
---

# Care pulses

## What this is

Care pulses fill the **quiet gap** when Ice Pro would otherwise go silent in Telegram.
They are not a second digest and not marketing spam.

Operational pushes already exist (booking, reminder, morning/Sunday digest, inactive 10/30).
A care pulse fires **only if those would not**.

## Cadence

- Window: **12:00–14:00 Europe/Minsk** (after morning digest, before evening reminders).
- Trainers: cooldown **48h**; skip if a digest already went today; skip Sunday (weekly digest); quiet check-in **Wednesday only** (72h).
- Clients: cooldown **72h**; skip if an inactive 10/30 went in the last 14 days.
- Claim-then-send (`care_pulses` unique on audience+recipient+kind+context). Failed send keeps the claim (no duplicate).

## Ladder (first honest fact wins)

Trainer: tomorrow plan → open slots (≥3 in 7 days) → one dormant client (≥14 days) → Wednesday quiet check-in.
Client: confirmed booking in 2–5 days → invite-back 4–9 days after last session (before inactive-10).

If nothing true to say — **silence**.

## Voice

- Calm, specific, one fact, one button.
- Trainer: «ты». Client: «Вы».
- Never «не забудьте про нас», fake urgency, guilt, or CRM jargon.
- Reliability: «всё на месте», «напишем сразу», «ничего не потеряется».
- Names, times, arenas — not slogans.

Templates: `src/bot/messages.py` (`CARE_PULSE_*`).
Picker: `src/application/care_pulse_use_cases.py`.
Renderer: `src/bot/care_pulse_format.py`.
Loop: `run_care_pulse_loop` in `src/bot/notification_loops.py`.
