"""Screenshot 1 of 6 — crop everything below the STUBS banner."""

from contextlib import ExitStack

# ── 1. ExitStack — one block, a number of resources you cannot know upfront ──


def merge(paths: list[str], destination: str) -> int:
    with ExitStack() as stack:
        # Each file is registered as it opens, and closed in reverse order on
        # the way out — including when the third open() raises and the first
        # two are already live.
        sources = [stack.enter_context(open(p, encoding="utf-8")) for p in paths]
        target = stack.enter_context(open(destination, "w", encoding="utf-8"))

        written = 0
        for source in sources:
            for line in source:
                target.write(line)
                written += 1
        return written


# The alternative is nesting `with` blocks you cannot count in advance,
# or hand-rolling try/finally that leaks the moment step two fails.


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        parts = []
        for index, text in enumerate(["alpha\n", "beta\n", "gamma\ndelta\n"]):
            part = root / f"part{index}.txt"
            part.write_text(text, encoding="utf-8")
            parts.append(str(part))

        out = root / "merged.txt"
        total = merge(parts, str(out))
        print(total, out.read_text(encoding="utf-8").split())
        # → 4 ['alpha', 'beta', 'gamma', 'delta']
