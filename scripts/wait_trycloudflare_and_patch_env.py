#!/usr/bin/env python3
"""
Poll a cloudflared quick-tunnel log until a *.trycloudflare.com URL appears, then set
API_BASE_URL and WEBAPP_BASE_URL in .env (same origin for API + Mini App).

Heavy paths: inline English only (repo convention for tooling).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

_URL_RE = re.compile(r"https://[\w.-]+\.trycloudflare\.com/?")
# cloudflared prints the public URL inside a boxed log line:
# |  https://foo.trycloudflare.com                                  |
_TUNNEL_BANNER_URL_RE = re.compile(
    r"\|\s+(https://[\w.-]+\.trycloudflare\.com)\s+\|"
)
_REGISTERED_RE = re.compile(r"Registered tunnel connection")


def _normalize_base(url: str) -> str:
    u = url.strip().rstrip("/")
    return u


def _patch_env(env_path: Path, api_base: str, webapp_base: str) -> None:
    keys = {"API_BASE_URL": api_base, "WEBAPP_BASE_URL": webapp_base}
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in keys:
            out.append(f"{key}={keys[key]}")
            seen.add(key)
        else:
            out.append(line)
    for k, v in keys.items():
        if k not in seen:
            out.append(f"{k}={v}")
    trailing = "\n" if text.endswith("\n") or not text else ""
    env_path.write_text("\n".join(out) + trailing, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log_file", type=Path, help="cloudflared stdout/stderr log path")
    ap.add_argument("env_file", type=Path, help=".env file to patch")
    ap.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for tunnel URL (default: 120)",
    )
    ap.add_argument(
        "--poll",
        type=float,
        default=0.35,
        help="Poll interval seconds (default: 0.35)",
    )
    args = ap.parse_args()

    log_file: Path = args.log_file
    env_file: Path = args.env_file
    deadline = time.monotonic() + float(args.timeout)

    url: str | None = None
    buf = ""
    pos = 0
    while time.monotonic() < deadline:
        if log_file.exists():
            try:
                data = log_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                data = ""
            if len(data) > pos:
                buf += data[pos:]
                pos = len(data)
            banner_matches = list(_TUNNEL_BANNER_URL_RE.finditer(buf))
            if banner_matches and _REGISTERED_RE.search(buf):
                url = _normalize_base(banner_matches[-1].group(1))
                break
            # Fallback for older cloudflared log shapes.
            matches = list(_URL_RE.finditer(buf))
            if matches and _REGISTERED_RE.search(buf):
                url = _normalize_base(matches[-1].group(0))
                break
        time.sleep(float(args.poll))

    if not url:
        print(
            "Timeout: no https://*.trycloudflare.com URL found in log.",
            file=sys.stderr,
        )
        return 1

    base = url
    env_file.parent.mkdir(parents=True, exist_ok=True)
    _patch_env(env_file, base, base)
    print(base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
