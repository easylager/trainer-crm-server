from src.shared.logging_redact import redact_phone, sanitize_validation_errors_for_log


def test_redact_phone_masks_middle():
    assert redact_phone("+375291234567") == "********4567"
    assert redact_phone("12") == "****"


def test_sanitize_validation_errors_strips_input():
    errs = [
        {"type": "missing", "loc": ("body", "x"), "msg": "Field required", "input": {"secret": "x"}},
        "other",
    ]
    clean = sanitize_validation_errors_for_log(errs)
    assert clean[0] == {"type": "missing", "loc": ("body", "x"), "msg": "Field required"}
    assert clean[1] == "other"
