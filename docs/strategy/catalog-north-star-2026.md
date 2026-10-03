# Catalog North Star — 2026

**Date:** 2026-10-03
**Status:** draft, adoption tracked as PDEC-018
**Relationship to other docs:** feeds the go/no-go gate ([ADR-005](../adr/005-go-no-go-90d.md), [business-plan-2026](business-plan-2026.md) §8–9); does not replace it. Supersedes nothing; narrows priorities.

**One sentence for the consumer:** «Открой ICING — увидишь, где сегодня лёд.»

---

## Strategic thesis

The catalog is not the final business. It is the **consumer demand layer for skating in BY/RU** (CIS is the export horizon per PDEC-013, not today's scope).

Our immediate goal is to build the best free, independent catalog for discovering where and when to skate. Consumers use it for free:

* ice arenas and skating sessions
* places and schedules
* shops and services
* trainers and schools

The catalog generates measurable demand. That demand becomes valuable to the supply side: trainers, schools, studios and arenas.

The long-term strategic asset is **the demand dataset around skating infrastructure**, not the catalog UI. A dataset that cannot be queried is not an asset — so the event-capture layer (per-arena demand events: views, coach clicks, share opens) is a first-class workstream with the same priority as the catalog surface itself.

## Business flywheel

```
Consumer demand
→ catalog usage
→ demand events captured per city / arena / service
→ measurable value for supply ("340 skaters viewed your ice this month")
→ trainers / schools / arenas join
→ supply contributes first-party data (arenas publish their own sessions,
  coaches fill profiles, groups post openings)
→ fresher, fuller catalog than parsers alone could achieve
→ more consumer demand
```

The escape from the parser treadmill is the **arena first-party step**: arenas publish their own mass-skating schedules because being on the platform earns them customers. Today the code cannot do this (business-plan §5.3) — it is a known gap, not an assumption.

## Strategic role of channels

* **Telegram / sharing** = acquisition and coordination channel.
* **SEO / public web** = acquisition and discovery channel; public arena pages double as sales artifacts for supply.
* **Catalog** = consumer demand layer.
* **Trainer CRM / B2B** = supply-side monetization.
* **Bookings / lead generation / subscriptions** = monetization layers.

SEO and virality are channels, not the business thesis. Neither gets strategy-level investment until its threshold below is passed.

## Current priority — two axes, not one stack

**Build priority (code):**

> catalog demand layer > demand-event capture > everything else.

No new B2B or CRM features beyond what the first supply sale requires. EPIC6 stays behind GATE-0 (TASK-122); the school-cabinet line (TASK-140–145) is justified only as far as school sale #1 needs it.

**Sell priority (conversations, in parallel, starting now):**

> the already-built supply side — R2a school billing (built, tested, flag-off), arena schedule-confirmation conversations, the five existing trainers.

Selling what exists is **validation, not expansion**. Deferring it until "the catalog is validated" makes validation item 4 below unreachable at the gate.

**Decision filter for every major product decision:**

> Does this help generate, capture, measure, or monetize real skating demand?

If not, it is not a priority now. Do not build features merely because they may be useful for a future SaaS or marketplace.

## North Star metric

> **Weekly unique consumers with ≥1 logged demand event, per city.**

This is literally "the demand layer," measured. One number, per city, weekly. It is countable only after ice-discovery is merged to prod and the event log ships — those two items are the non-negotiable engineering prerequisites of this document.

## Validation before expansion

The strategy remains a hypothesis. Each item is bound to an instrument and a threshold; all are measured at the **go/no-go gate** (ADR-005, 2 of 4 required, per business-plan §9.1). Interpretation without pre-named numbers is forbidden; the owner's personal revenue bar is named in writing before the gate measurement.

| # | Validate | Instrument | Threshold |
|---|---|---|---|
| 1 | Real consumer demand | Unique clients in Ice tab, Minsk | 300/mo |
| 2 | Demand measurable per arena | Per-arena demand events | Logged & reportable for ≥8 Minsk arenas |
| 3 | Supply sees value | 4 conversations (school, arena, sharpening, trainers) | ≥2 supply actors ask for this data monthly |
| 4 | Someone pays | R2a via TASK-078 + allowlist | ≥1 school paying, or LOI + explicit price objection |
| C-A | SEO channel viable | Wordstat volumes, BY + 5 RF cities | RF geo-query volume ≥ tens of thousands/mo |
| C-B | Virality channel viable | Share→open, shares/WAU (TASK-146) | ≥20% open, ≥0.1 shares/WAU |

C-A is a desk study (keyword volumes) and is checked before any SEO investment, not at the gate.

**Pre-committed branches at the gate:**

* ≥2 gate items pass → double down: supply sales + RF planning, catalog keeps build priority.
* Consumer demand passes but supply declines → repitch to arenas (R2b) and lead-fee (R5) with the demand data as the product.
* Neither fires → invoke ADR-005 honestly: fix mode (≤10 h/week income source), change market (RF earlier or second vertical), or stop. Not more catalog.

**Seasonality clause:** validation is only meaningful inside the ice season. A measurement taken off-season measures nothing and does not count toward the gate.

## What we consciously do not do under this document

* Strategy-level SEO investment before C-A passes; arena pages ship as sales artifacts, not as a media bet.
* New virality mechanics beyond session sharing before C-B passes.
* Any new B2B/CRM/monetization feature not required by an in-flight supply conversation.
* Product-surface expansion (new verticals, new entity types) until items 1–4 are demonstrated.
