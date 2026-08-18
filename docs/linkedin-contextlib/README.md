# LinkedIn: contextlib series

A ready-to-publish set of posts about the parts of Python's `contextlib` that most codebases never touch: `ExitStack`, `stack.callback` + `pop_all`, `nullcontext`, `ContextDecorator`, `AsyncExitStack` and the sharp edges of `suppress`.

Why this module rather than `functools` or `itertools`: both of those are posted to death, and their popular members (`lru_cache`, `chain`, `groupby`) are common knowledge. `contextlib` past `@contextmanager` is genuinely under-used, and it maps onto problems every backend engineer has met — leaked handles, half-finished writes, async teardown.

The series is deliberately levelled. Post A is written so a junior can act on it the same afternoon: four tools, and every screenshot shows the familiar way beside the contextlib way. Reach comes from the wide audience, not from impressing seniors. The rollback and async material sits in Post B and the PDF carousel, where the reader has already opted in.

## Contents

| File | What it is |
|---|---|
| `POST-A-four-tools-simple.md` | **Start here.** Beginner-friendly primary post: four tools, four before/after screenshots |
| `POST-C-short-opinion.md` | Short opinionated post on `nullcontext`, built for comment volume |
| `POST-B-rollback-story.md` | Single-idea, story-led post on rollbacks with `ExitStack` — the first properly senior one |
| `CAROUSEL-SLIDES.md` | Nine-slide script for the PDF document version, the deep pass over all six tools |
| `ENGAGEMENT-PLAYBOOK.md` | Reach and SSI mechanics: hooks, timing, first ninety minutes, cadence, metrics |
| `snippets-simple/01…04_*.py` | Screenshot sources for Post A: familiar way on top, contextlib underneath |
| `snippets/01…06_*.py` | Fuller sources for Posts B and C and the carousel |

Each post file carries its own hook variants, first comment, alt text and a bank of prepared replies.

## The snippets

Every file runs on its own and prints the output quoted in its comments, failure paths included:

```bash
cd snippets-simple && for f in 0*.py; do python3 "$f"; done
cd ../snippets && for f in 0*.py; do python3 "$f"; done
```

Each file is split by a banner into the part that goes into the screenshot and throwaway stubs that make it runnable. Crop at the banner — the docstring on line 1 tells you which side to keep.

`snippets-simple/` is intentionally plain: no type annotations, no production-shaped abstractions, one short comment per block. Anything a junior would have to look up before understanding the point has been removed.

Version floors, in case someone asks in the comments: `ExitStack` and `pop_all` are 3.3, `suppress` is 3.4, `nullcontext` and `AsyncExitStack` are 3.7, async `nullcontext` is 3.10. The files as written need 3.9+ only because of the built-in generic annotations (`list[str]`).

## Screenshot recipe

- **Ratio 4:5 portrait** (1080×1350). It occupies the most vertical space in the mobile feed, which is the whole point.
- **10–16 lines of code per image.** If a snippet does not fit, cut a comment rather than shrinking the type.
- **Font 18–22 px**, a mono face with clear zeroes — JetBrains Mono, Berkeley Mono, SF Mono. Test at 400 px wide, the size a phone thumbnail actually renders.
- **One theme throughout the series**, dark or light consistently. Dark reads better in-feed; light reads better in a PDF.
- **No window chrome, no traffic-light buttons, no watermark.** A small handle in the corner is fine.
- Keep the numbered heading comment (`# 1. …`) visible in the frame: it is what ties the image to the numbered paragraph in the post.
- Export PNG, not JPEG — text stays crisp.

Tools that work: Carbon, ray.so, CodeSnap in VS Code, or a screenshot of the editor with a large font and the gutter hidden.

## Publishing checklist

1. Pick one post file and one hook variant.
2. Capture the screenshots in order; image 1 must be legible as a thumbnail.
3. Paste the copy from the `text` block — check no markdown or backticks survived.
4. Attach images in order, fill in the alt text from the table in the post file.
5. Publish in the slot named at the top of the post file.
6. Post the prepared first comment within a minute.
7. Stay on for an hour and reply to everything with a question attached.
8. Log impressions, comments and saves after 48 hours.
