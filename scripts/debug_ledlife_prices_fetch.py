"""Which ledlife.by price page parses (BY egress + proxy). No DB writes."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingestion.adapters_minsk_by_egress import (
    _ledlife_discover_price_page_urls,
    _ledlife_prices_candidate_urls,
    _ledlife_prices_from_stoimost,
    _ledlife_skip_price_url,
    is_by_origin_blocked_snapshot,
)
from src.ingestion.types import ParserJob
from src.ingestion.source_io import egress_proxy, fetch_http_text_optional
from src.shared.config import Settings


async def main() -> None:
    proxy = Settings().by_egress_proxy_url
    if not proxy:
        print("Set BY_EGRESS_PROXY_URL in .env (local_by_egress_proxy.sh setup + start)")
        sys.exit(1)
    stoimost = await fetch_http_text_optional("https://ledlife.by/stoimost_uslug/")
    if not stoimost:
        print("stoimost_uslug: fetch failed")
        sys.exit(1)
    print(f"stoimost_uslug: {len(stoimost)} bytes, blocked={is_by_origin_blocked_snapshot(stoimost)}")
    print(f"stoimost book: {_ledlife_prices_from_stoimost(stoimost)}")
    job_config = {
        "url": "https://ledlife.by/massovye_kataniya/",
        "prices_detail_url": "https://ledlife.by/krytyi_katok434451/",
        "mk_price_bands": {
            "day_45": {"adult": 1000, "child": 800},
            "evening_45": {"adult": 1100, "child": 900},
        },
        "prices_fallback_urls": [
            "https://ledlife.by/krytyi_ledovyi_katok/",
            "https://ledlife.by/massovoe_katanie/",
        ],
    }
    job = ParserJob(
        id=0,
        arena_id=4,
        parser_key="ledlife_origin_html_v1",
        is_enabled=True,
        cadence="weekly",
        next_run_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        last_run_at=None,
        config=job_config,
    )

    dump_dir = ROOT / ".local" / "ledlife-debug"
    dump_dir.mkdir(parents=True, exist_ok=True)

    with egress_proxy(proxy):
        queue = list(_ledlife_prices_candidate_urls(job, stoimost))
        seen: set[str] = set()
        while queue and len(seen) < 18:
            url = queue.pop(0)
            if url in seen or _ledlife_skip_price_url(job, url):
                continue
            seen.add(url)
            html = (
                stoimost
                if url.rstrip("/") == "https://ledlife.by/stoimost_uslug"
                else await fetch_http_text_optional(url)
            )
            if not html:
                print(f"{url}: fetch failed / HTTP error")
                continue
            slug = url.rstrip("/").split("/")[-1] or "root"
            (dump_dir / f"{slug}.html").write_text(html, encoding="utf-8")
            blocked = is_by_origin_blocked_snapshot(html)
            book = _ledlife_prices_from_stoimost(html, job) if not blocked else {}
            kids = _ledlife_discover_price_page_urls(html) if not book else []
            print(f"{url}: {len(html)} bytes blocked={blocked} book={book} links={len(kids)}")
            if book:
                print(f"OK — prices from {url}")
                break
            for child in kids:
                if child not in seen and child not in queue:
                    queue.append(child)
        else:
            print(f"no price book — HTML dumps in {dump_dir}")


if __name__ == "__main__":
    asyncio.run(main())
