"""Simple snippet 4 of 4 — crop everything below the STUBS banner."""

import time
from contextlib import contextmanager

# 4. Write it once, use it as a block or as a decorator

@contextmanager
def timed(label):
    start = time.perf_counter()
    try:
        yield
    finally:
        print(f"{label}: {time.perf_counter() - start:.2f}s")


with timed("loading data"):  # as a with-block
    time.sleep(0.2)
# → loading data: 0.20s


@timed("nightly job")  # or as a decorator, for free
def run():
    time.sleep(0.3)


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":
    run()
    # → nightly job: 0.30s
