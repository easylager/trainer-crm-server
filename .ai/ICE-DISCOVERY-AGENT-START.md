# Ice Discovery — START HERE (agent entrypoint)

**You are working on the Ice Discovery initiative** (arenas + ice schedule + trainers on one client surface; first city **Минск**).  
In the tracker it may still say «EPIC3» — same initiative.

If you were given only a TASK id or «continue epic3» — **this file is your first read.** Do not invent scope.

## Git lock (read before anything else)

**PR base is always `release/ice-discovery`. Never `master`.**

Owner 2026-09-06: релиз не скоро. Агент **не** открывает PR в `master`, **не** мержит train → `master`, **не** предлагает «release cut». Конец задачи = merge в `release/ice-discovery`. Подробности: [`ICE-DISCOVERY-AGENT-GIT.md`](./ICE-DISCOVERY-AGENT-GIT.md).

---

## 30-second map

| What | Where |
|---|---|
| **This entrypoint** | `.ai/ICE-DISCOVERY-AGENT-START.md` ← you are here |
| Git + when a TASK is finished | `.ai/ICE-DISCOVERY-AGENT-GIT.md` |
| Parallel agents / lanes | `.ai/ICE-DISCOVERY-AGENT-LANES.md` |
| Your job (AC / scope) | `.ai/tasks/TASK-NNN.md` |
| Visual UI SoT | `.ai/design/arenas-client-app-prototype.html` |
| Product / data designs | `.ai/DESIGN-ARENAS-CLIENT-APP.md`, `.ai/DESIGN-INGESTION-PARSERS-V1.md` |
| Initiative map | `.ai/EPIC3-arenas-ice-discovery.md` |

**Load order (mandatory):**

1. This file  
2. `.ai/ICE-DISCOVERY-AGENT-GIT.md`  
3. If several agents: `.ai/ICE-DISCOVERY-AGENT-LANES.md` (your lane only)  
4. Your `.ai/tasks/TASK-NNN.md` (full)  
5. Only the design sections the TASK links  

Do **not** read the whole epic / all TASK files unless asked.

---

## Workflow (end-to-end)

```
1. Confirm TASK-NNN and that depends_on are status MERGED on release/ice-discovery
2. git fetch && checkout release/ice-discovery && pull
3. git checkout -b feat/TASK-NNN-short-kebab
4. ai-toolkit as needed: plan/estimate → execute (TDD per AC) → verify
5. Push + gh pr create --base release/ice-discovery
6. CI green → merge into release/ice-discovery
7. TASK status: MERGED (+ pr_url, merge SHA in Execution History)
8. Delete feature branch → STOP (do not PR to master)
```

**Hard rule:** toolkit `/verify` PASS ≠ done.  
**Done** = merged into **`release/ice-discovery`**, status **`MERGED`**.

**Ingest rule:** a rink parser only **extracts**. Slots reach the DB through shared **transform + validate** into `ice_sessions` (same columns for every arena). Never persist widget/HTML shape. Scheduler loop lives in **`notification_service`** (same image, second process) — never inside uvicorn. Empty/error runs must not delete future slots; never show past `valid_until`. Do not enable `requires_by_egress` jobs without real BY IP. Do not scrape Instagram in V1. Reliability contract: `DESIGN-INGESTION-PARSERS-V1.md` §6.

**Booking rule (hard):** `ice_sessions` (МК / `public_skate` / `open_ice`) are **read-only in the client** — show time and prices; CTA «Билет на месте» is informational, not our booking flow. **Only** trainer slots, groups, and trainer cards on the arena page may call the existing book/apply path. Never add «Записаться» on an MK row or a booking API for arena ice sessions in this initiative.

**Not your job:** `master`, production deploy, release cut, unrelated TASK.

---

## Branches

| Branch | Role |
|---|---|
| `release/ice-discovery` | release train — **only** PR target for every TASK |
| `feat/TASK-NNN-…` | your work; created **from the train**, never from `master` |

**Forbidden:** `--base master`. **Forbidden:** merging the train to `master`.

---

## What “good” looks like when you finish

- [ ] All AC in TASK verified (or WAIVED with human quote)  
- [ ] Out of Scope untouched  
- [ ] PR merged into `release/ice-discovery`  
- [ ] TASK frontmatter `status: MERGED`  
- [ ] No silent scope expansion  
- [ ] No PR / merge involving `master`  

---

## Paste prompt for humans (copy into a new agent chat)

```text
Ice Discovery initiative. Entrypoint: read .ai/ICE-DISCOVERY-AGENT-START.md then .ai/ICE-DISCOVERY-AGENT-GIT.md.

Your TASK: TASK-NNN
Spec: .ai/tasks/TASK-NNN.md

Rules:
- Use ai-toolkit-max on that TASK: /research → /plan → /estimate → /execute TASK-NNN supervised → /verify
- Lane (if named): SCHEMA | PLACE | INGEST | API | UI | SPEC — see .ai/ICE-DISCOVERY-AGENT-LANES.md
- Branch from release/ice-discovery as feat/TASK-NNN-<kebab>
- TDD against TASK acceptance criteria
- PR base MUST be release/ice-discovery
- NEVER --base master. NEVER merge train → master. Release is not soon.
- You are NOT done after /verify — done = MERGED into release/ice-discovery
- Do not expand scope; stop and ask if TASK conflicts with prototype

Execute that TASK end-to-end through merge into release/ice-discovery.
```
