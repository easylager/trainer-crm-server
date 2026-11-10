"""Короткая рекламная ссылка «Кто кого»: /kk?s=<метка> — превью для соцсетей и вход в Telegram.

Без базы: метка только вшивается в ссылку на бота (start_param ``kks_<метка>``), считает её сама игра.
"""

from __future__ import annotations

import html
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from src.application.hockey_promo import clean_src
from src.application.place_links import public_telegram_entry_link
from src.shared.config import Settings

router = APIRouter(tags=["public-kk-promo"])

DEFAULT_SRC = "site"
_TITLE = "Кто кого — угадай, кто победит в матче Динамо-Минск"
_DESCRIPTION = "Тапни за команду, набирай очки и сравнивайся с друзьями. Бесплатно, в Telegram."
_LOGO = "/logos/01-icon/glide-icon-teal-square-512.png"
# Краулеры превью на t.me не уводим: иначе картинка и заголовок возьмутся с чужой страницы.
_PREVIEW_BOTS = ("telegrambot", "twitterbot", "facebookexternalhit", "slackbot", "vkshare", "discordbot", "whatsapp")


def _is_preview_bot(request: Request) -> bool:
    agent = (request.headers.get("user-agent") or "").lower()
    return any(bot in agent for bot in _PREVIEW_BOTS)


@router.get("/kk", include_in_schema=False)
async def get_kk_promo_page(request: Request, s: str = Query("", max_length=64)) -> HTMLResponse:
    src = clean_src(s) or DEFAULT_SRC
    cfg = Settings()  # type: ignore[call-arg]
    base = (cfg.webapp_base_url or "").strip().rstrip("/")
    go = (
        public_telegram_entry_link(cfg, start_param=f"kks_{src}")
        or f"{base}/webapp/kto-kogo?src={src}"
    )
    e = html.escape
    image = f"{base}{_LOGO}"
    hop = ""
    if not _is_preview_bot(request):
        hop = (
            "<script>if(/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)){"
            f"location.replace({json.dumps(go)});}}</script>"
        )
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(_TITLE)}</title>
<meta name="description" content="{e(_DESCRIPTION)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{e(_TITLE)}">
<meta property="og:description" content="{e(_DESCRIPTION)}">
<meta property="og:image" content="{e(image)}">
<meta name="twitter:card" content="summary">
<meta name="robots" content="noindex">
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#1747b5;color:#fff;font:600 18px/1.4 system-ui,sans-serif;text-align:center}}main{{padding:24px;max-width:420px}}h1{{font-size:26px;margin:0 0 8px}}p{{margin:0 0 20px;font-weight:500;opacity:.9}}a.go{{display:inline-block;background:#ffd23f;color:#10265e;padding:14px 26px;border-radius:14px;text-decoration:none}}</style>
</head><body><main><h1>Кто кого</h1><p>{e(_DESCRIPTION)}</p>
<a class="go" href="{e(go)}">Открыть в Telegram</a></main>{hop}
</body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=300"})
