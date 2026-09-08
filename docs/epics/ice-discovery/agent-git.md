# Ice Discovery — Git & task lifecycle for agents

**Entrypoint for new chats:** [`ICE-DISCOVERY-AGENT-START.md`](./ICE-DISCOVERY-AGENT-START.md) (read that first).  
This file is the git/lifecycle detail that START points to.

## Hard rule — train only

**Every Ice Discovery PR has base `release/ice-discovery`.**

```text
FORBIDDEN:  gh pr create --base master
FORBIDDEN:  merge release/ice-discovery → master
FORBIDDEN:  branch feat/TASK-* from master
FORBIDDEN:  “release cut”, “ship to prod”, “open PR to master”
            unless the product owner typed that exact order in this chat.
```

Owner lock **2026-09-06:** релиз **не скоро**. Вся работа живёт на `release/ice-discovery`.  
`master` — не цель агента. Не предлагать PR в `master`. Не «на всякий случай открыть cut». Не считать G-R* разрешением выкатить.

**ai-toolkit-max phases (`clarify` → `plan` → `estimate` → `execute` → `verify`) are not the end of a task.**

They only prove the work is correct **on a feature branch**.  
**A TASK is finished only when its PR is merged into the release train:**

```text
release/ice-discovery
```

Until that merge: status stays `IN_PROGRESS` (or `VERIFY`), never claim initiative progress as shipped to the train.

| Milestone | Toolkit / local | Git reality | TASK `status` |
|---|---|---|---|
| Spec ready | phase `plan`/`estimate` done | no branch yet or branch empty | `READY` |
| Coding | `execute` | commits on `feat/TASK-NNN-…` | `IN_PROGRESS` |
| AC green locally | `verify` PASS | still **only** feature branch | `VERIFY` — **not done** |
| PR open → train | — | PR **base = `release/ice-discovery`** | `IN_PROGRESS` + `pr_url` |
| **Merged to train** | — | merge commit on `release/ice-discovery` | **`MERGED`** ← task complete for agents |
| Production / `master` | — | **out of scope for agents** | do not write this row |

**Forbidden:** PR base `master`. **Forbidden:** marking `DONE`/`MERGED` after `/verify` without merge into `release/ice-discovery`.  
**Forbidden:** any PR, merge, rebase-onto, or cherry-pick whose destination is `master`.

---

## Branches to create

| Branch | Who creates | From | Purpose |
|---|---|---|---|
| `release/ice-discovery` | once (R0, already exists) | — | **Release train** — only integration line for this initiative |
| `feat/TASK-NNN-…` | agent per TASK | **`release/ice-discovery`** (never master) | One TASK’s work |

**Naming:** `feat/TASK-<nnn>-<short-kebab>` (nnn = zero-padded id).

**One TASK = one branch = one PR into `release/ice-discovery`.**

After merge: delete the feature branch.

---

## Lifecycle (agent checklist)

```
1. Sync:   git fetch && git checkout release/ice-discovery && git pull
2. Branch: git checkout -b feat/TASK-NNN-short-name
3. Toolkit: clarify/plan/estimate as needed → execute (TDD) → verify AC
4. Push:   git push -u origin HEAD
5. PR:     gh pr create --base release/ice-discovery --title "TASK-NNN: …"
6. CI green + human/spec review if required
7. Merge PR into release/ice-discovery (squash or merge per repo norm)
8. TASK frontmatter: status: MERGED ; record merge SHA + pr_url in Execution History
9. Delete feat/TASK-NNN-…
10. STOP. Do not open a second PR to master.
```

Depends_on peers: treat as ready for *your* start when they are **`MERGED`** into `release/ice-discovery`, not merely locally verified.

If `gh pr create` would default to `master` (repo default branch): **pass `--base release/ice-discovery` explicitly**. If the base is wrong, close the PR and reopen. Do not merge it.

---

## `master` is not this initiative’s delivery line

There is **no** agent step «release train → master».

A future production cut is a **human** decision, later, in a separate conversation, with an explicit sentence from the owner. Until then:

- Do not create `release/ice-discovery` → `master` PRs.
- Do not sync/merge `master` into the train «to prepare a cut».
- G-R1 / G-R2 / G-R3 / G-R4 are product questions on the **train**, not ship-to-prod triggers.
