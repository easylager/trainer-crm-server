"""Screenshot 4 of 6 — crop everything below the STUBS banner."""

import time
from contextlib import contextmanager

# ── 4. @contextmanager hands you a decorator at no extra cost ───────────────


@contextmanager
def timed(label: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        print(f"{label}: {(time.perf_counter() - start) * 1e3:.1f} ms")


with timed("import batch"):  # as a block
    ...


@timed("nightly rebuild")  # and as a decorator, same object
def rebuild() -> None:
    ...


# Why it works: @contextmanager returns a _GeneratorContextManager, which
# inherits ContextDecorator and rebuilds itself on every call.
# The catch that follows from that: the decorator is safe for repeated calls,
# whilst one instance reused in two `with` blocks raises on the second.


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":
    rebuild()
    rebuild()  # fine — the decorator recreates the manager per call

    once = timed("single use")
    with once:
        ...
    try:
        with once:  # the same instance a second time
            ...
    except AttributeError as exc:
        print(f"{type(exc).__name__}: {exc}")
        # → AttributeError: '_GeneratorContextManager' object has no attribute 'args'
        #   CPython's way of saying the manager is spent
