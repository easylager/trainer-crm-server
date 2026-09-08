"""Shared HTTP fetch for Minsk ice spike scripts."""

import subprocess
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Sample Belarus residential/datacenter ranges — header spoof rarely works; we still try.
BY_IP_CANDIDATES = ("178.120.12.34", "93.125.84.10", "37.17.48.1")


@dataclass
class FetchResult:
    url: str
    http_status: int | None
    body: str | None
    bytes: int
    error: str | None = None
    fetch_mode: str = "urllib"
    geo_bypass_attempted: bool = False
    geo_bypass_worked: bool = False

    @property
    def ok(self) -> bool:
        return self.http_status is not None and 200 <= self.http_status < 400 and self.body is not None

    @property
    def blocked(self) -> bool:
        return self.http_status == 403


def _urllib_fetch(url: str, headers: dict[str, str], timeout: float) -> FetchResult:
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            raw = resp.read(800_000)
            return FetchResult(
                url=url,
                http_status=status,
                body=raw.decode("utf-8", errors="replace"),
                bytes=len(raw),
                fetch_mode="urllib",
            )
    except HTTPError as e:
        body = e.read(2000).decode("utf-8", errors="replace") if e.fp else None
        return FetchResult(url=url, http_status=e.code, body=body, bytes=len(body or ""), error=str(e))
    except (URLError, OSError) as e:
        return FetchResult(url=url, http_status=None, body=None, bytes=0, error=str(e))


def _curl_fetch(url: str, headers: dict[str, str], timeout: float) -> FetchResult:
    cmd = ["curl", "-sL", "-A", UA, "--max-time", str(int(timeout)), "-w", "\n__HTTP__%{http_code}"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out = proc.stdout
    if "__HTTP__" not in out:
        return FetchResult(url=url, http_status=None, body=None, bytes=0, error=proc.stderr or "curl failed")
    body, code_s = out.rsplit("__HTTP__", 1)
    code = int(code_s.strip())
    return FetchResult(url=url, http_status=code, body=body, bytes=len(body.encode()), fetch_mode="curl")


def fetch_html(
    url: str,
    *,
    timeout: float = 25.0,
    try_geo_bypass: bool = False,
    retries: int = 2,
) -> FetchResult:
    last: FetchResult | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(0.8)
        result = _fetch_once(url, timeout=timeout, try_geo_bypass=try_geo_bypass)
        last = result
        if result.ok:
            return result
        if result.http_status == 403:
            return result
    return last or FetchResult(url=url, http_status=None, body=None, bytes=0, error="no attempt")


def _fetch_once(url: str, *, timeout: float, try_geo_bypass: bool) -> FetchResult:
    base_headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru-BY,ru;q=0.9,be;q=0.8",
    }

    # curl is more reliable for several BY sites (SSL / connection resets on urllib).
    result = _curl_fetch(url, base_headers, timeout)
    if result.ok:
        return result
    if result.http_status == 403:
        pass
    elif result.http_status is not None:
        return result

    result = _urllib_fetch(url, base_headers, timeout)
    if result.ok or not try_geo_bypass:
        return result

    for ip in BY_IP_CANDIDATES:
        bypass_headers = {
            **base_headers,
            "X-Forwarded-For": ip,
            "X-Real-IP": ip,
            "CF-IPCountry": "BY",
            "Referer": "https://www.google.by/",
        }
        attempt = _curl_fetch(url, bypass_headers, timeout)
        attempt.geo_bypass_attempted = True
        if attempt.ok:
            attempt.geo_bypass_worked = True
            return attempt

    result.geo_bypass_attempted = True
    return result


def classify_block(result: FetchResult) -> str | None:
    if not result.blocked:
        return None
    if result.geo_bypass_attempted and not result.geo_bypass_worked:
        return "geo_ip_nginx (X-Forwarded-For BY IPs did not help; needs BY egress IP or browser snapshot)"
    return "http_403"
