"""Доверенный IP клиента за прокси (TASK-190).

Раньше брался **левый** адрес ``X-Forwarded-For`` — а его целиком задаёт клиент
(``curl -H 'X-Forwarded-For: 1.2.3.4'``), поэтому и «уникальные», и rate limit обходились
одной строкой. Прокси платформы (Railway edge) **дописывает** адрес реального соединения
справа, поэтому доверять можно только хвосту списка: ``TRUSTED_PROXY_HOPS`` (по умолчанию 1)
крайних записей справа добавили наши прокси, и клиентом считается запись ``-hops``.

* ``hops = 1`` — один прокси (Railway edge): берём самый правый адрес.
* ``hops = 0`` — прокси нет (локально/тесты): заголовок игнорируется, берём адрес сокета.
* Короче списка нет смысла: если записей меньше ``hops``, берём самую левую из присланных.
* Мусор в записи (не IP) — откат на адрес сокета, а не на строку от клиента.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Mapping

TRUSTED_PROXY_HOPS_DEFAULT = 1


def _valid_ip(raw: str) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def trusted_client_ip(
    headers: Mapping[str, str],
    peer_host: str | None,
    *,
    hops: int = TRUSTED_PROXY_HOPS_DEFAULT,
) -> str | None:
    """IP клиента по правилу выше; ``None`` — определить нечем."""
    peer = _valid_ip(peer_host or "") or ((peer_host or "").strip() or None)
    if hops <= 0:
        return peer
    forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For") or ""
    entries = [e.strip() for e in forwarded.split(",") if e.strip()]
    if not entries:
        return peer
    chosen = entries[-hops] if len(entries) >= hops else entries[0]
    return _valid_ip(chosen) or peer
