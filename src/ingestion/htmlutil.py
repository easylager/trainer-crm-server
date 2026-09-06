"""Shared HTML helpers for Minsk extract adapters. Extract only — no DB writes."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from src.ingestion.normalize import parse_price_to_minor

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = _TAG.sub(" ", text)
    return _WS.sub(" ", text).replace("&nbsp;", " ").replace("&#8212;", "—").strip()


def html_unescape_cell(html: str) -> str:
    text = html.replace("&nbsp;", " ").replace("&#8212;", "—").replace("&mdash;", "—")
    text = _TAG.sub(" ", text)
    return _WS.sub(" ", text).strip()


class HtmlTableParser(HTMLParser):
    """Collects tables as lists of row cell texts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._in_cell = True
        elif tag == "br" and self._in_cell and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(_WS.sub(" ", "".join(self._cell)).strip())
            self._cell = None
            self._in_cell = False
        elif tag == "tr" and self._table is not None and self._row is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._cell is not None:
            self._cell.append(data)


def parse_tables(html: str) -> list[list[list[str]]]:
    parser = HtmlTableParser()
    parser.feed(html)
    parser.close()
    return parser.tables


def price_from_label(html: str, *needles: str, already_minor: bool = False) -> int | None:
    blob = html_unescape_cell(html)
    lower = blob.lower()
    for needle in needles:
        idx = lower.find(needle.lower())
        if idx < 0:
            continue
        window = blob[idx : idx + 180]
        return parse_price_to_minor(window, already_minor=already_minor)
    return None
