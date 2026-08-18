"""Simple snippet 2 of 4 — crop everything below the STUBS banner."""

from contextlib import nullcontext

# 2. When the session is optional

# Before
def process_users(session=None):
    if session is None:
        with Session() as session:
            return _process(session)

    return _process(session)

# Same business logic in two places


# After
def process_users(session=None):
    context = (
        Session()
        if session is None
        else nullcontext(session)
    )

    with context as session:
        return _process(session)

# 1. Caller owns the session → we don't close it
# 2. We create our own session → cleanup is automatic
# 3. Business logic exists only once


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":
    from contextlib import contextmanager

    class Session:
        def __enter__(self):
            self.label = "own session"
            return self

        def __exit__(self, *exc):
            self.closed = True

    class CallerSession:
        def __init__(self):
            self.label = "caller's session"
            self.closed = False

    def _process(session):
        return session.label

    print(process_users())
    # → own session

    caller = CallerSession()
    print(process_users(caller), caller.closed)
    # → caller's session False
