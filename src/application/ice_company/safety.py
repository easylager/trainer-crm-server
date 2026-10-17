"""Имена и свободный текст: без ссылок, экранирование под HTML и MarkdownV2."""

from __future__ import annotations

import re

_LINK_RE = re.compile(
    r"(https?://|www\.|t\.me/|viber://|tg://)",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"^[\w\s\-'.’]+$", re.UNICODE)
_MD_V2 = set(r"_*[]()~`>#+-=|{}.!")


class TextRejected(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def escape_markdown_v2(value: str) -> str:
    return "".join("\\" + ch if ch in _MD_V2 else ch for ch in value)


def clean_free_text(raw: str | None, *, max_len: int, required: bool, field: str) -> str:
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if not text:
        if required:
            raise TextRejected(f"{field}: укажите текст.")
        return ""
    if len(text) > max_len:
        raise TextRejected(f"{field}: не длиннее {max_len} символов.")
    if _LINK_RE.search(text):
        raise TextRejected(f"{field}: ссылки здесь не ставим.")
    if _NAME_RE.fullmatch(text) is None:
        raise TextRejected(f"{field}: только буквы, пробел, дефис и апостроф.")
    return text


def callback_data(code: str, action: str) -> str:
    data = f"ic:{code}:{action}"
    if len(data.encode("utf-8")) > 64:
        raise TextRejected("callback_data длиннее 64 байт.")
    return data
