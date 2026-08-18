# Post C — "One code path" (short, opinionated, high comment rate)

**Format:** text + 2 code screenshots (`snippets/03_nullcontext.py`, `snippets/01_exitstack_dynamic.py`)
**Best slot:** Monday or Friday, 08:30–09:30 — short posts win on days when nobody reads long ones
**Length:** 1 065 characters — short enough to read in half a minute, which is the point
**Goal:** volume of comments, not depth. Opinions get answered; explanations get scrolled.

---

## Hook variants

**C1 — the flat statement (recommended)**

> If your function has an optional resource, you probably wrote the same block twice.

**C2 — the confession**

> I duplicated a with-block for years before noticing that the standard library had already solved it in six characters: nullcontext.

**C3 — the challenge**

> Show me a Python codebase with an "optional session" argument and I'll show you two copies of the same body, already drifting apart.

---

## Post copy

```text
If your function takes an optional resource, you have probably written the same block twice.

"Use the caller's session if there is one, otherwise open our own" turns into an if/else where both branches contain the real work. They start identical. They stay identical until the third bug fix.

contextlib.nullcontext ends it:

1 — nullcontext(session) returns the object you pass in and closes nothing on exit
2 — bare nullcontext() is a context manager that does nothing at all, which is what an optional lock, span or profiler wants to be
3 — so the with-block is written once, and ownership becomes a single expression above it

The same instinct scales up. When the number of resources is only known at runtime, ExitStack.enter_context() replaces the nesting you cannot write, and still unwinds in reverse.

Two screenshots below: the optional case, then the N-resources case.

Every language has a feature like this — cheap, ten years old, and quietly missing from most codebases. Which one is it in yours?

#Python #CleanCode #SoftwareEngineering #Programming
```

---

## First comment

```text
Worth adding: since 3.10 nullcontext also implements the async protocol, so "async with nullcontext(conn)" works when the alternative branch is an async context manager. Handy when the optional resource is a connection pool.

Typing is the one rough edge — nullcontext(value) and nullcontext() give you different return types, so the annotation on the variable above the with-block is worth writing out.
```

---

## Alt text

1. Python function using contextlib.nullcontext so an optional session and an optional lock keep one code path.
2. Python code using ExitStack.enter_context to open a runtime-determined number of files in one with-block.

---

## Reply bank

- **"Just require the session."** → "Cleanest option when you control every caller. Libraries rarely do, and that is where this pays."
- **"An if/else is more readable."** → "It is, right up to the moment both branches contain the work. Duplicating the body is the part I object to, not the branch."
- **Someone names their language's equivalent** → engage with it properly, name the trade-off, ask a follow-up. Cross-language threads pull in audiences beyond your own network, which is exactly what you want from this post.
