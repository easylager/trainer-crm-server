"""Screenshot 3 of 6 — crop everything below the STUBS banner."""

from contextlib import nullcontext

# ── 3. nullcontext — one code path when the resource is optional ─────────────


def report(rows, session=None, *, lock=None) -> int:
    # Borrow the caller's session, or own one for the length of this call.
    # nullcontext(session) returns it untouched and closes nothing on exit.
    scope = nullcontext(session) if session is not None else open_session()

    # Same trick with no value at all: an optional lock, span or profiler
    # becomes a no-op instead of a second copy of the block below.
    guard = lock if lock is not None else nullcontext()

    with scope as active, guard:
        return active.write(rows)


# Without it, "optional resource" quietly turns into two duplicated bodies
# that drift apart at the third bug fix.


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":
    import threading
    from contextlib import contextmanager

    class Session:
        def __init__(self, label: str) -> None:
            self.label = label
            self.closed = False

        def write(self, rows) -> int:
            return len(rows)

    owned = Session("owned")

    @contextmanager
    def open_session():
        try:
            yield owned
        finally:
            owned.closed = True

    borrowed = Session("borrowed")
    print(report([1, 2, 3], borrowed), borrowed.closed)
    # → 3 False   (the caller still owns it)

    print(report([1, 2], lock=threading.Lock()), owned.closed)
    # → 2 True    (we opened it, so we closed it)
