"""TASK-401: страница регистрации получает тот же флаг, что витрина."""

from pathlib import Path

from src.api.asset_stamp import stamp_html


def test_client_register_html_has_no_flag_when_off(monkeypatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "false")
    from src.api.app import webapp_client_register_page

    path = Path(__file__).resolve().parents[2] / "static" / "webapp" / "client-register.html"
    body = webapp_client_register_page(trainer_id=7).body.decode()
    stamped = stamp_html(path.read_text(encoding="utf-8"))
    meta = '  <meta name="trainer-crm-register-trainer-id" content="7">\n'
    assert body == stamped.replace("</head>", meta + "</head>", 1)
    assert "__UNIFIED_TRAINER_CARD__" not in body


def test_client_register_html_carries_flag_when_on(monkeypatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    from src.api.app import _UNIFIED_TRAINER_CARD_BOOT, webapp_client_register_page

    path = Path(__file__).resolve().parents[2] / "static" / "webapp" / "client-register.html"
    stamped = stamp_html(path.read_text(encoding="utf-8"))
    meta = '  <meta name="trainer-crm-register-trainer-id" content="7">\n'
    body = webapp_client_register_page(trainer_id=7).body.decode()
    assert body == stamped.replace("</head>", meta + _UNIFIED_TRAINER_CARD_BOOT + "</head>", 1)
    assert body.count("__UNIFIED_TRAINER_CARD__") == 1
