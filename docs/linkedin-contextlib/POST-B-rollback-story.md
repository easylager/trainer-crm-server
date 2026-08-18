# Post B — "The rollback that never ran" (single idea, story-led)

**Format:** text + 1 code screenshot (`snippets/02_exitstack_rollback.py`)
**Best slot:** Thursday, 09:00–10:00 — good day for narrative posts, less competition from listicles
**Length:** 1 550 characters
**Goal:** comments from people telling their own version of the story → the cheapest reach LinkedIn gives you

Use this one if Post A performed well: same module, different shape, no repetition of content. Leave at least five days between them.

---

## Hook variants

**B1 — the war story (recommended)**

> Half-finished writes are not caused by missing rollbacks. They are caused by rollbacks written three screens away from the thing that needs undoing.

**B2 — the review comment**

> The worst bug I find in code review is invisible: an operation that half-succeeds, and a cleanup path that only runs when someone remembered to write it.

**B3 — the number**

> Two lines. That is the distance between "we created the bucket" and "we deleted it again because the next call failed" — if you register the undo in the right place.

---

## Post copy

```text
Half-finished writes are rarely caused by missing rollbacks. They are caused by rollbacks written three screens away from the thing that needs undoing.

The shape is always the same. Create a resource. Call the next service. That call raises, the handler logs it, and the resource stays behind — orphaned, invisible, and billed monthly.

The usual fix is a try/except per step, each one undoing what came before it. By the fourth step nobody can prove it is correct any more.

contextlib.ExitStack gives you a better ordering: do the thing, then register its undo on the very next line.

1 — create the bucket
2 — stack.callback(api.delete_bucket, bucket) — the undo is now armed
3 — attach the policy, register its detach the same way
4 — stack.pop_all() at the end of the happy path, which disarms everything

Anything that raises before pop_all() unwinds the callbacks in reverse: policy detached, bucket deleted, original traceback intact. Nothing is caught, so your error handling and your metrics see exactly what they saw before.

Three properties I care about here:

— the undo lives next to the do, so review can verify it by reading two lines
— the order is guaranteed to be the reverse of creation
— forgetting pop_all() rolls back a successful operation, which fails loudly in tests rather than quietly in production

Screenshot below, with both paths and the resulting call log.

Where do you keep your compensating actions today — a framework, a try/except ladder, or hope?

#Python #SoftwareEngineering #Backend #Reliability #Programming
```

---

## First comment

```text
The subtle bit is why the undo is registered rather than written in a finally block: a finally block runs after the whole body, so it cannot know how far the body got. ExitStack knows, because each callback was pushed at the moment its resource came into existence.

If your steps are idempotent you can go further and make the callbacks retryable — but that is a different post.
```

---

## Alt text

Python function that provisions a bucket inside an ExitStack, registering delete_bucket and detach_policy as rollback callbacks and calling pop_all on success, with the printed call log for both the happy and failing paths.

---

## Reply bank

- **"Use a transaction."** → "Whenever you can, yes. This is for the part of the world that has no transactions: object storage, payment providers, DNS, third-party CRMs."
- **"Isn't this the saga pattern?"** → "It is, minus the framework and the message broker. Sagas earn their infrastructure across services and time; within one request handler ExitStack is enough."
- **"What about failures during rollback?"** → "ExitStack keeps unwinding and chains the exceptions, so you see both. If a compensating call must not fail, that one belongs in a queue with retries — worth saying explicitly."
