"""
Helpers to avoid logging secrets and PII (Epic A — logging policy).
Use when formatting log messages or sanitizing structured error details.
"""


def redact_phone(phone: str | None, *, visible_tail: int = 4) -> str:
    """Mask phone for logs; keeps last ``visible_tail`` digits when possible."""
    if not phone:
        return ""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) <= visible_tail:
        return "****"
    return "*" * (len(digits) - visible_tail) + digits[-visible_tail:]


def sanitize_validation_errors_for_log(errors: list) -> list:
    """
    Strip ``input`` from Pydantic/FastAPI validation error dicts so request bodies
    (passwords, tokens, initData fragments) are not written to application logs.
    """
    out: list = []
    for item in errors:
        if isinstance(item, dict):
            out.append({k: v for k, v in item.items() if k != "input"})
        else:
            out.append(item)
    return out
