# Post A — "Four functools tools" (primary)

**Format:** text + 4 code screenshots (multi-image post, 4:5 portrait) from `snippets-simple/`
**Best slot:** Tuesday or Wednesday, 09:00–10:30
**Audience:** juniors and mid-level first; deliberately skips `lru_cache` / `cache` — everyone knows those already
**Goal:** saves + comments; pairs naturally with the contextlib series a week or two later

---

## Post copy (copy-paste as is)

```text
I see "from functools import lru_cache" in almost every Python project.

I almost never see the rest of the module. 🐍

Most of us reach for it once — memoize a function — and stop there. The rest is a small toolkit for the patterns you write every week: expensive properties, callbacks, decorators, and growing isinstance chains.

Four functools tools worth knowing beyond caching:

🔹 cached_property — when @property is too eager

A plain @property runs its body on every access.

Fine for a cheap getter. Painful when the body hits the database, parses a file, or walks a graph.

cached_property computes once per instance, stores the result on self, and hands it back on every later read — same ergonomics as @property, without the repeat work.

🔹 partial — when you need a callable with some arguments already filled in

Schedulers, retry hooks, CLI callbacks — they all want "call this later with these args fixed".

A lambda works until you debug it, pickle it, or read it in a stack trace.

partial(fn, arg, kw=value) is the same idea, spelled out: a real function object with a readable repr.

🔹 wraps — when your decorator should not become the function

Every decorator that defines an inner wrapper creates a new function object.

Without @wraps(fn) on that wrapper, __name__, __doc__ and __module__ all belong to "wrapper" — which is what shows up in logs, OpenAPI schemas, and help().

One line. The difference between a decorator that plays nicely with the ecosystem and one that silently breaks introspection.

🔹 singledispatch — when isinstance is turning into a ladder

One function, many types, and the body grows a new if isinstance(...) branch every sprint.

@singledispatch gives you a default implementation plus @fn.register handlers per type — open for extension, closed for modification, and no central chain to edit when a new type arrives.

The thing I like most about functools:

It does not ask you to learn a new paradigm.

It takes a pattern you already write — cache this, bind that, preserve metadata, branch on type — and gives you the version that will still read clearly in six months.

Small utilities.

Quietly deleting whole categories of boilerplate. 👌

Which functools tool do you reach for most — and if you had to add a fifth to this list, what would it be? 👇

#Python #SoftwareEngineering #BackendDevelopment #LearnPython #Programming
```

---

## First comment (post within 60 seconds)

```text
Deliberately left out lru_cache and cache — if you are reading this you probably already know them.

Two more that almost made the cut:

— total_ordering: implement __eq__ and __lt__, get the other four comparison methods for free. Handy before you reach for a heavier tool.
— reduce: fold a sequence with a function. Less fashionable since sum()/any()/all() exist, but still the right shape when you are combining values left-to-right with custom logic.

Happy to turn either into a follow-up post if there is interest.
```

---

## Image plan and alt text

| # | Source file | Alt text |
|---|---|---|
| 1 | `snippets-simple/01_cached_property.py` | Python @property vs functools.cached_property — compute once per instance instead of on every access. |
| 2 | `snippets-simple/02_partial.py` | Python callback registered with lambda vs functools.partial — same bound arguments, clearer in debuggers. |
| 3 | `snippets-simple/03_wraps.py` | Python decorator with and without functools.wraps — preserving __name__ and __doc__ on the wrapper. |
| 4 | `snippets-simple/04_singledispatch.py` | Python isinstance ladder vs functools.singledispatch — one handler per type, registered separately. |

---

## Reply bank

- **"Why not lru_cache?"** → "Everyone knows it — this post is for the rest of the module. lru_cache is the front door; these four are the rooms behind it."
- **"cached_property vs lru_cache on a method?"** → "lru_cache on a method caches across all instances unless you use a key that includes self — easy to get wrong. cached_property is scoped to one instance by design."
- **"partial vs lambda — does it really matter?"** → "For a one-off in a list comp, probably not. For anything stored, logged, pickled, or passed across a boundary, partial gives you a name and a repr you can actually read."
- **"singledispatch vs Protocol/ABC?"** → "Different trade-off. singledispatch is for functions that already exist and gain types over time. ABC/Protocol is when the type hierarchy is the design. Many codebases need the first before they earn the second."
- **Someone suggests reduce, cmp_to_key, total_ordering, cached_property from dataclasses** → thank them, one concrete sentence on when to use it, ask what their use case was.

---

## Hook variants (if you want to A/B the opening line)

**A1 — recommended**

> I see "from functools import lru_cache" in almost every Python project.
>
> I almost never see the rest of the module. 🐍

**A2 — confession**

> I imported functools for @lru_cache years before I noticed the rest of the module.

**A3 — concrete**

> Your @property hits the database on every access. functools has had the fix since 3.8.
