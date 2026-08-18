"""Simple snippet 1 of 4 — crop everything below the STUBS banner."""

from functools import cached_property

# 1. cached_property — compute once per instance, not on every access

# Before
class User:
    @property
    def permissions(self):
        return fetch_permissions(self.id)  # hits the DB on every access


# After
class User:
    @cached_property
    def permissions(self):
        return fetch_permissions(self.id)  # once per instance, then cached on self


# Same idea as @property, but the result is stored on the object after the first read.


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":
    calls = 0

    def fetch_permissions(user_id):
        global calls
        calls += 1
        return ["read", "write"]

    u = User()
    u.id = 42

    print(u.permissions, u.permissions, calls)
    # → ['read', 'write'] ['read', 'write'] 1
