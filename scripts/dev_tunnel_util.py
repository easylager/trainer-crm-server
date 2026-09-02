#!/usr/bin/env python3
"""
Local dev tunnel helpers: patch .env URLs, wait for tunnel logs, health-check public HTTPS.

Used by dev_tunnel_loop.sh, dev_repair_stack.sh, and dev_prepare_tunnel.sh.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_CF_URL_RE = re.compile(r"https://[\w.-]+\.trycloudflare\.com/?")
_CF_BANNER_URL_RE = re.compile(r"\|\s+(https://[\w.-]+\.trycloudflare\.com)\s+\|")
_CF_REGISTERED_RE = re.compile(r"Registered tunnel connection")
_LR_URL_RE = re.compile(r"https://[\w-]+\.lhr\.life/?")
_DEAD_TUNNEL_MARKERS = ("no tunnel here", "503 service unavailable")


def normalize_base(url: str) -> str:
    return url.strip().rstrip("/")


def patch_env_urls(env_path: Path, base_url: str) -> None:
    base = normalize_base(base_url)
    keys = {"API_BASE_URL": base, "WEBAPP_BASE_URL": base}
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


def read_env_url(env_path: Path, key: str = "WEBAPP_BASE_URL") -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            val = v.strip().strip('"').strip("'")
            return normalize_base(val) if val else None
    return None


def tunnel_health(base_url: str, *, timeout: float = 12.0) -> bool:
    base = normalize_base(base_url)
    if not base.lower().startswith("https://"):
        return False
    probe = f"{base}/webapp/catalog"
    req = urllib.request.Request(probe, method="GET", headers={"User-Agent": "trainer-crm-dev-health/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = resp.read(8192).decode("utf-8", errors="ignore").lower()
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
    return not any(marker in body for marker in _DEAD_TUNNEL_MARKERS)


def _tail_read(path: Path, pos: int, buf: str) -> tuple[int, str]:
    if not path.exists():
        return pos, buf
    try:
        data = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return pos, buf
    if len(data) > pos:
        buf += data[pos:]
        pos = len(data)
    return pos, buf


def wait_cloudflare_log(log_file: Path, env_file: Path, *, timeout: float, poll: float) -> str | None:
    deadline = time.monotonic() + timeout
    buf = ""
    pos = 0
    while time.monotonic() < deadline:
        pos, buf = _tail_read(log_file, pos, buf)
        banner_matches = list(_CF_BANNER_URL_RE.finditer(buf))
        if banner_matches and _CF_REGISTERED_RE.search(buf):
            url = normalize_base(banner_matches[-1].group(1))
            patch_env_urls(env_file, url)
            return url
        matches = list(_CF_URL_RE.finditer(buf))
        if matches and _CF_REGISTERED_RE.search(buf):
            url = normalize_base(matches[-1].group(0))
            patch_env_urls(env_file, url)
            return url
        time.sleep(poll)
    return None


def wait_localhostrun_log(log_file: Path, env_file: Path, *, timeout: float, poll: float) -> str | None:
    deadline = time.monotonic() + timeout
    buf = ""
    pos = 0
    while time.monotonic() < deadline:
        pos, buf = _tail_read(log_file, pos, buf)
        matches = list(_LR_URL_RE.finditer(buf))
        if matches and "tunneled with tls" in buf.lower():
            url = normalize_base(matches[-1].group(0))
            patch_env_urls(env_file, url)
            return url
        time.sleep(poll)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_patch = sub.add_parser("patch-env")
    p_patch.add_argument("env_file", type=Path)
    p_patch.add_argument("base_url")

    p_health = sub.add_parser("health")
    p_health.add_argument("base_url")

    p_read = sub.add_parser("read-env-url")
    p_read.add_argument("env_file", type=Path)
    p_read.add_argument("--key", default="WEBAPP_BASE_URL")

    p_cf = sub.add_parser("wait-cloudflare")
    p_cf.add_argument("log_file", type=Path)
    p_cf.add_argument("env_file", type=Path)
    p_cf.add_argument("--timeout", type=float, default=45.0)
    p_cf.add_argument("--poll", type=float, default=0.35)

    p_lr = sub.add_parser("wait-localhostrun")
    p_lr.add_argument("log_file", type=Path)
    p_lr.add_argument("env_file", type=Path)
    p_lr.add_argument("--timeout", type=float, default=45.0)
    p_lr.add_argument("--poll", type=float, default=0.5)

    args = ap.parse_args()

    if args.cmd == "patch-env":
        patch_env_urls(args.env_file, args.base_url)
        print(normalize_base(args.base_url))
        return 0

    if args.cmd == "health":
        ok = tunnel_health(args.base_url)
        print("ok" if ok else "fail")
        return 0 if ok else 1

    if args.cmd == "read-env-url":
        url = read_env_url(args.env_file, args.key)
        if not url:
            return 1
        print(url)
        return 0

    if args.cmd == "wait-cloudflare":
        url = wait_cloudflare_log(args.log_file, args.env_file, timeout=args.timeout, poll=args.poll)
        if not url:
            print("timeout", file=sys.stderr)
            return 1
        print(url)
        return 0

    if args.cmd == "wait-localhostrun":
        url = wait_localhostrun_log(args.log_file, args.env_file, timeout=args.timeout, poll=args.poll)
        if not url:
            print("timeout", file=sys.stderr)
            return 1
        print(url)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
