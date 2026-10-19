"""Короткий код компании и ключи участников. В лог их не пишем."""

from __future__ import annotations

import hashlib
import secrets

ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
CODE_LENGTH = 8


def new_public_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def tg_participant_key(user_id: int) -> str:
    return f"tg:{int(user_id)}"


def new_web_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(24)
    return raw, web_participant_key(raw)


def web_participant_key(raw_token: str) -> str:
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return f"web:{digest}"
