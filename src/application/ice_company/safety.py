"""Имена и свободный текст: без ссылок, экранирование под HTML и MarkdownV2.

Названия команд и ники на льду — с широким алфавитом (эмодзи, пунктуация):
это чат друзей, не CRM. Режем только ссылки и управляющие символы.
"""

from __future__ import annotations

import re

_LINK_RE = re.compile(
    r"(https?://|www\.|t\.me/|viber://|tg://)",
    re.IGNORECASE,
)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# PNG-плакат печатается Inter без цветных emoji — в подписи под аватаром оставляем буквы.
_EMOJI_FOR_POSTER_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0000200D"
    "\U0000FE0F"
    "]+",
    flags=re.UNICODE,
)
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
    text = _CTRL_RE.sub("", text)
    if not text:
        if required:
            raise TextRejected(f"{field}: укажите текст.")
        return ""
    if len(text) > max_len:
        raise TextRejected(f"{field}: не длиннее {max_len} символов.")
    if _LINK_RE.search(text):
        raise TextRejected(f"{field}: ссылки здесь не ставим.")
    if "<" in text or ">" in text:
        raise TextRejected(f"{field}: угловые скобки здесь не ставим.")
    return text


def clean_team_title(raw: str | None, *, max_len: int, required: bool = False, field: str = "Название команды") -> str:
    return clean_free_text(raw, max_len=max_len, required=required, field=field)


def strip_emoji_for_poster(text: str) -> str:
    """Текст для Inter на PNG: emoji и ZWJ не рисуются, убираем, пробелы схлопываем."""
    cleaned = _EMOJI_FOR_POSTER_RE.sub("", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def callback_data(code: str, action: str) -> str:
    data = f"ic:{code}:{action}"
    if len(data.encode("utf-8")) > 64:
        raise TextRejected("callback_data длиннее 64 байт.")
    return data
