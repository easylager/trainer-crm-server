"""Единый подвал публичного сайта Glide (TASK-279, TASK-277)."""

from __future__ import annotations

import html as html_lib
from datetime import datetime, timezone
from urllib.parse import quote

from src.application.trainer_invite_links import normalize_client_bot_username
from src.shared.config import Settings
from src.shared.copy_ru import t

SUPPORT_EMAIL = "info.glideclub@gmail.com"
INSTAGRAM_URL = "https://www.instagram.com/glide.club/"


def _esc(value: object) -> str:
    return html_lib.escape(str(value), quote=True)


def public_telegram_href() -> str | None:
    """Публичная ссылка на клиентского бота (расписание в Telegram)."""
    u = normalize_client_bot_username(Settings().client_bot_username)
    return f"https://t.me/{u}" if u else None


def schedule_error_mailto() -> str:
    subject = quote("Ошибка в расписании Glide")
    return f"mailto:{SUPPORT_EMAIL}?subject={subject}"


def render_site_footer_html(
    *,
    trainers_href: str = "/trainers",
    context_html: str = "",
    telegram_href: str | None = None,
    show_telegram_button: bool = True,
    show_app_button: bool = True,
) -> str:
    """HTML футера для подстановки в ``__SITE_FOOTER__``.

    ``show_telegram_button=False`` — на лендинге тренера: кнопка ведёт в клиентского бота,
    а у тренера свой вход (CTA страницы).

    Кнопка «Приложение» закреплена внизу экрана на каждой странице с подвалом и ссылкой
    в Telegram. ``show_app_button=False`` — когда у страницы своя нижняя панель (каток
    с «Позвать»): кнопка тогда живёт в ней.
    """
    year = datetime.now(timezone.utc).year
    profile = public_telegram_href()
    mail = SUPPORT_EMAIL
    about = t("site.footer.about")
    disclaimer = t("site.footer.disclaimer")
    report_label = t("site.footer.report_schedule")
    open_label = t("tg.open")
    button_href = (telegram_href or "").strip() or profile

    contacts: list[str] = [
        f'<a class="b-site-foot__link" href="mailto:{_esc(mail)}">{_esc(mail)}</a>',
    ]
    if profile:
        contacts.append(
            f'<a class="b-site-foot__link" href="{_esc(profile)}" rel="noopener noreferrer" target="_blank">Telegram</a>'
        )
    contacts.append(
        f'<a class="b-site-foot__link" href="{_esc(INSTAGRAM_URL)}" rel="noopener noreferrer" target="_blank">'
        f"Instagram</a>"
    )

    nav = [
        f'<a class="b-site-foot__link" href="{_esc(trainers_href)}">Для тренеров</a>',
        f'<a class="b-site-foot__link" href="{_esc(schedule_error_mailto())}">{_esc(report_label)}</a>',
    ]

    app = ""
    if button_href and show_telegram_button and show_app_button:
        from src.application.style_b import app_button_html, app_button_script_html

        app = app_button_html(button_href) + app_button_script_html()

    ctx = ""
    if context_html.strip():
        ctx = f'<div class="b-site-foot__context">{context_html}</div>'

    button = ""
    if button_href and show_telegram_button:
        button = (
            f'<a class="b-site-foot__tg tg-out" href="{_esc(button_href)}">{_esc(open_label)}</a>'
        )

    return (
        f'<footer class="b-site-foot" aria-label="О сайте Glide">'
        f'<svg class="b-site-foot__blade" viewBox="0 0 1200 56" preserveAspectRatio="none" aria-hidden="true">'
        f'<path fill="currentColor" d="M0 46C280 34 620 16 1200 6V56H0Z"/>'
        f'<path class="b-site-foot__scratch" d="M40 52C300 44 620 32 900 26"/>'
        f'<path class="b-site-foot__scratch b-site-foot__scratch--mid" d="M180 51C500 40 820 30 1080 24"/>'
        f'<path class="b-site-foot__scratch b-site-foot__scratch--short" d="M420 46C720 36 980 28 1160 24"/>'
        f"</svg>"
        f'<div class="b-site-foot__slab">'
        f'<svg class="b-site-foot__mark" viewBox="0 0 160 72" aria-hidden="true">'
        f'<path d="M8 58C36 18 92 8 152 22" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round"/>'
        f'<path d="M28 62C52 36 96 30 132 40" fill="none" stroke="currentColor" stroke-width="0.75" stroke-linecap="round"/>'
        f"</svg>"
        f'<div class="b-site-foot__inner">'
        f'<div class="b-site-foot__top">'
        f'<div class="b-site-foot__brand">'
        f'<a class="b-site-foot__logo" href="/">Glide</a>'
        f'<p class="b-site-foot__about">{_esc(about)}</p>'
        f"{ctx}"
        f"{button}"
        f"</div>"
        f'<div class="b-site-foot__col">'
        f'<p class="b-site-foot__label">Контакты</p>'
        f'<div class="b-site-foot__links">{"".join(contacts)}</div>'
        f"</div>"
        f'<div class="b-site-foot__col">'
        f'<p class="b-site-foot__label">Информация</p>'
        f'<div class="b-site-foot__links">{"".join(nav)}</div>'
        f"</div>"
        f"</div>"
        f'<hr class="b-site-foot__rule" />'
        f'<div class="b-site-foot__meta">'
        f'<p class="b-site-foot__copy">© Glide {_esc(year)}</p>'
        f'<p class="b-site-foot__disclaimer">{_esc(disclaimer)}</p>'
        f"</div>"
        f"</div>"
        f"</div>"
        f"</footer>"
        f"{app}"
    )
