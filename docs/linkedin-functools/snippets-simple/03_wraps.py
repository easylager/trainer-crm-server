"""Simple snippet 3 of 4 — crop everything below the STUBS banner."""

from functools import wraps

# 3. wraps — decorators should not erase the original function

# Before
def logged(fn):
    def wrapper(*args, **kwargs):
        print(f"calling {fn.__name__}")
        return fn(*args, **kwargs)
    return wrapper


# After
def logged(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        print(f"calling {fn.__name__}")
        return fn(*args, **kwargs)
    return wrapper

# Without wraps: wrapper.__name__ is "wrapper" and help() shows the wrong docstring.
# With wraps: logs, stack traces and FastAPI/OpenAPI see the real function.


# ── STUBS — not part of the screenshot ──────────────────────────────────────

if __name__ == "__main__":

    @logged
    def create_order(order_id: int) -> str:
        """Create an order in the billing service."""
        return f"order {order_id}"

    print(create_order.__name__, create_order.__doc__)
    # → create_order Create an order in the billing service.
