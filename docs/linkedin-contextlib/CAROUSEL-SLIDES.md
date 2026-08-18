# Document carousel script (PDF post)

LinkedIn treats a PDF as a native document and measures how far people swipe, so dwell time is high and the post keeps surfacing for days. Use this when you want the longest tail from the same material as Post A.

**Build:** 9 slides, 1080×1350 px (4:5), exported as a single PDF. Upload via *Add a document*, title it `Six contextlib tools most Python code never uses`.
**Caption:** short, because the slides carry the content:

```text
Six things in contextlib that quietly delete try/finally boilerplate.

Most of us stop at @contextmanager. The rest are where resource handling stops being manual: a number of files known only at runtime, rollbacks registered where the risk is, optional resources without a duplicated block, decorators for free, and async teardown that stays flat.

One tool per slide, with the code. Swipe.

Number 2 is the one I almost never see in review, and the one that saves the most weekends.

Which of the six is already in your codebase?

#Python #SoftwareEngineering #Backend #CleanCode #Programming
```

This is the deep version of the series — it uses the fuller snippets in `snippets/`, not the beginner pair-by-pair ones. Publish it after Post A has introduced the topic.

---

## Slide 1 — cover (no code)

> **contextlib**
> Six tools most Python code never uses
>
> Resource handling without the try/finally sprawl
> — swipe →
>
> *(small, bottom-left: your name and handle)*

Design note: this slide is the thumbnail. Six words maximum in the largest type, nothing below 32 px.

## Slide 2 — the problem (no code)

> Three symptoms of hand-rolled cleanup:
>
> 1. with-blocks nested until the indentation wins
> 2. a finally that swallows the original traceback
> 3. a rollback that was going to be written "later"
>
> All three have had standard-library answers since Python 3.3.

## Slide 3 — ExitStack, N resources

Screenshot: `snippets/01_exitstack_dynamic.py`

> **1 — ExitStack**
> You cannot nest with-blocks you cannot count.
> enter_context() registers each resource as it opens and unwinds them in reverse — including when the third open() fails.

## Slide 4 — callback + pop_all

Screenshot: `snippets/02_exitstack_rollback.py`

> **2 — stack.callback + pop_all**
> Do the thing, arm its undo on the next line.
> Raise before pop_all() and the compensating calls run in reverse, with the original exception untouched.

## Slide 5 — nullcontext

Screenshot: `snippets/03_nullcontext.py`

> **3 — nullcontext**
> Borrow the caller's resource or own one, without writing the block twice.
> Bare nullcontext() makes an optional lock or span a no-op.

## Slide 6 — @contextmanager as a decorator

Screenshot: `snippets/04_contextmanager_as_decorator.py`

> **4 — ContextDecorator, for free**
> The object @contextmanager returns is both a with-block and a decorator.
> It rebuilds itself per call — hence safe to decorate, unsafe to reuse.

## Slide 7 — AsyncExitStack

Screenshot: `snippets/05_async_exit_stack.py`

> **5 — AsyncExitStack**
> enter_async_context(), push_async_callback(), sync callbacks — one stack, reverse order.
> Async teardown stops being try/finally four levels deep.

## Slide 8 — suppress and its trap

Screenshot: `snippets/06_suppress_trap.py`

> **6 — suppress**
> Narrow and typed, it documents an expected failure.
> Widened, it abandons the rest of the block in silence. One statement, no more.

## Slide 9 — close (no code)

> Which of the six is missing from your codebase?
>
> Number 2 is the one I almost never see in review.
>
> Tell me in the comments — I reply to all of them.
>
> *(your name, one line on what you do, no link)*

---

## Production notes

- Same font, same accent colour, same code theme on every slide; inconsistency reads as low effort at thumbnail size.
- Code screenshots on slides need to survive a 400 px-wide render: 10–14 lines each, nothing narrower than 18 px.
- Number every slide (`3/9` in a corner). Swipe-through rate rises when people can see how much is left.
- Keep the PDF under 100 MB and export as text-selectable — LinkedIn indexes it, and "contextlib" being searchable is free reach.
