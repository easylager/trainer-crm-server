"""IP клиента за прокси (TASK-190).

Эмпирика (прод, 2026-10-06, Railway): 160 параллельных запросов, каждый со своим подделанным
``X-Forwarded-For: 198.51.100.N``, дали ровно 120 x 200 и 40 x 429 при лимите 120/60 с — то есть
edge Railway **срезает/перезаписывает** присланный клиентом XFF, а **левая** запись — реальный
IP соединения (так же отвечает поддержка Railway). Исходная посылка аудита (M5: «левый XFF
задаёт клиент») на Railway неверна. Поэтому стратегия по умолчанию — ``leftmost``:

1. левая **публичная** запись ``X-Forwarded-For`` (внутренние 10/172.16/192.168, CGNAT
   100.64/10 и вся 100.0.0.0/8, loopback, link-local, ULA и мусор пропускаются);
2. иначе ``X-Real-IP`` (если валиден и публичен);
3. иначе адрес сокета.

``CLIENT_IP_STRATEGY=rightmost_hops`` + ``TRUSTED_PROXY_HOPS=N`` — запасной режим для платформы,
которая **дописывает** адрес справа и не режет клиентский заголовок: берётся запись ``-N``
справа (``N=0`` — игнорировать заголовок). На Railway его включать не нужно: правая запись там
может оказаться внутренним хопом, и все посетители схлопнутся в одного.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Mapping

STRATEGY_LEFTMOST = "leftmost"
STRATEGY_RIGHTMOST_HOPS = "rightmost_hops"
TRUSTED_PROXY_HOPS_DEFAULT = 1

_INTERNAL_NETS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.0.0.0/8",  # CGNAT 100.64/10 и внутренние хопы Railway
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "224.0.0.0/3",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)


def _parse(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(raw.strip())
    except ValueError:
        return None


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not any(ip.version == n.version and ip in n for n in _INTERNAL_NETS)


def _header(headers: Mapping[str, str], name: str) -> str:
    return headers.get(name) or headers.get(name.title()) or ""


def trusted_client_ip(
    headers: Mapping[str, str],
    peer_host: str | None,
    *,
    strategy: str = STRATEGY_LEFTMOST,
    hops: int = TRUSTED_PROXY_HOPS_DEFAULT,
) -> str | None:
    """IP клиента по правилам модуля; ``None`` — определить нечем."""
    peer_ip = _parse(peer_host or "")
    peer = str(peer_ip) if peer_ip else ((peer_host or "").strip() or None)
    entries = [e.strip() for e in _header(headers, "x-forwarded-for").split(",") if e.strip()]

    if strategy == STRATEGY_RIGHTMOST_HOPS:
        if hops <= 0 or not entries:
            return peer
        chosen = _parse(entries[-hops] if len(entries) >= hops else entries[0])
        return str(chosen) if chosen else peer

    for entry in entries:
        ip = _parse(entry)
        if ip is not None and _is_public(ip):
            return str(ip)
    real = _parse(_header(headers, "x-real-ip"))
    if real is not None and _is_public(real):
        return str(real)
    return peer
