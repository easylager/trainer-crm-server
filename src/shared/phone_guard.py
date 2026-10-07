"""Phone validation and sanitization for public surfaces (TASK-207).

Public pages and APIs must never expose phone values without at least 7 digits.
Apply sanitization at the data layer (row → card/item), not in each render.
"""


def is_valid_public_phone(phone: str | None) -> bool:
    """Check if phone string contains at least 7 digits (minimal valid phone number).
    
    Examples:
        >>> is_valid_public_phone("+375291234567")
        True
        >>> is_valid_public_phone("8-029-123-45-67")
        True
        >>> is_valid_public_phone("123-45")  # only 4 digits
        False
        >>> is_valid_public_phone("unknown (только email/соцсети)")
        False
        >>> is_valid_public_phone(None)
        False
    """
    if not phone:
        return False
    raw = str(phone).strip()
    if not raw:
        return False
    digits = "".join(ch for ch in raw if ch.isdigit())
    return len(digits) >= 7


def sanitize_public_phone(phone: str | None) -> str | None:
    """Return phone only if it contains at least 7 digits, else None.
    
    Use this at the data layer when building public API responses or SSR view models.
    """
    return str(phone).strip() if phone and is_valid_public_phone(phone) else None
