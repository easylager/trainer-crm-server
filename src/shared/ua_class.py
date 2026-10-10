"""Грубый класс User-Agent (TASK-190). Хранится класс, а не сам UA.

Классы: ``human`` | ``preview`` (превью ссылок в мессенджерах) | ``search`` (поисковые боты) |
``crawler`` (прочие боты, скрипты, headless, пустой UA). Всё, кроме ``human``, не входит в
WAU/уникальные/спрос по аренам.
"""
from __future__ import annotations

UA_HUMAN = "human"
UA_PREVIEW = "preview"
UA_SEARCH = "search"
UA_CRAWLER = "crawler"

UA_CLASSES = (UA_HUMAN, UA_PREVIEW, UA_SEARCH, UA_CRAWLER)

_PREVIEW_TOKENS = (
    "telegrambot",
    "twitterbot",
    "facebookexternalhit",
    "facebot",
    "whatsapp",
    "viber",
    "vkshare",
    "slackbot",
    "discordbot",
    "skypeuripreview",
    "linkedinbot",
    "pinterestbot",
    "okhttp-preview",
    "mail.ru",
    "applebot-extended",
)
_SEARCH_TOKENS = (
    "googlebot",
    "google-inspectiontool",
    "storebot-google",
    "adsbot-google",
    "mediapartners-google",
    "yandex",
    "bingbot",
    "bingpreview",
    "msnbot",
    "duckduckbot",
    "baiduspider",
    "applebot",
    "petalbot",
    "sogou",
    "seznambot",
    "mj12bot",
    "ahrefsbot",
    "semrushbot",
    "dotbot",
)
_CRAWLER_TOKENS = (
    "bot/",
    "bot;",
    "bot)",
    "crawler",
    "spider",
    "scrapy",
    "headlesschrome",
    "phantomjs",
    "puppeteer",
    "playwright",
    "selenium",
    "python-requests",
    "python-urllib",
    "aiohttp",
    "httpx",
    "go-http-client",
    "java/",
    "curl/",
    "wget/",
    "libwww",
    "okhttp",
    "node-fetch",
    "axios",
    "postman",
    "monitor",
    "uptime",
    "pingdom",
    "lighthouse",
    "slurp",
)


def classify_user_agent(user_agent: str | None) -> str:
    ua = (user_agent or "").strip().lower()
    if not ua:
        return UA_CRAWLER
    if any(t in ua for t in _PREVIEW_TOKENS):
        return UA_PREVIEW
    if any(t in ua for t in _SEARCH_TOKENS):
        return UA_SEARCH
    if any(t in ua for t in _CRAWLER_TOKENS) or ua.endswith("bot") or " bot" in ua:
        return UA_CRAWLER
    return UA_HUMAN


def is_bot_user_agent(user_agent: str | None) -> bool:
    return classify_user_agent(user_agent) != UA_HUMAN
