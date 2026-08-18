# LinkedIn: functools series

Four `functools` tools beyond `lru_cache` / `cache`: `cached_property`, `partial`, `wraps`, and `singledispatch`.

Post format matches the contextlib series — beginner-friendly before/after screenshots, main post styled for LinkedIn (emoji bullets, engagement question at the end).

## Contents

| File | What it is |
|---|---|
| `POST-A-four-tools.md` | Primary post — copy-paste ready |
| `snippets-simple/01…04_*.py` | Screenshot sources: familiar pattern on top, functools underneath |

## Snippets

```bash
cd snippets-simple && for f in 0*.py; do python3 "$f"; done
```

Crop at the `STUBS` banner unless the docstring says otherwise.

## Publishing

1. Post A from `POST-A-four-tools.md`
2. Four screenshots from `snippets-simple/` in order
3. First comment within a minute
4. Leave at least 10 days between this and the contextlib post — same audience, different module

## Fifth-tool candidates for comments / follow-up

`total_ordering`, `reduce`, `cmp_to_key`, `singledispatchmethod` (3.8+)
