"""
8 скриншотов демо-тренера для лендинга ``/trainers`` (TASK-325) → ``static/landing/shots/``.

Снимает настоящие экраны Mini App с локального сервера на демо-данных
(``scripts/seed_demo_trainer.py``) и сообщения ботов (``scripts/render_demo_bot_messages.py``).

Телефон: 390×844 CSS px, deviceScaleFactor 3 (PNG 1170×2532), мобильная эмуляция, светлая тема,
системный шрифт. Часы браузера фиксируются на «сегодня 07:00» по Минску — тот же момент,
от которого сид отсчитывает «проведено/подтверждено».

Авторизация — как в Telegram: валидный ``initData``, подписанный локальным токеном бота
(тот же HMAC, что проверяет ``src/shared/telegram_webapp.py``), передаётся через
``#tgWebAppData`` в настоящий telegram-web-app.js. Обходов в коде приложения нет.

Нужен Python с ``playwright`` (``pip install playwright && playwright install chromium``)::

    python scripts/shoot_landing_screens.py \\
        --base http://127.0.0.1:8325 --env /path/to/.env --messages tmp/demo-bot-messages
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.request
from datetime import datetime, time as dtime
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "landing" / "shots"
MINSK = ZoneInfo("Europe/Minsk")
AS_OF = dtime(7, 0)  # = AS_OF_TIME в seed_demo_trainer.py

DEMO_TRAINER_TG = 990_000_325
PARENT_TG = 990_000_401  # мама Софии (первый клиент сида)

THEME = {"bg_color": "#ffffff", "text_color": "#000000", "hint_color": "#999999", "link_color": "#2481cc",
         "button_color": "#2481cc", "button_text_color": "#ffffff", "secondary_bg_color": "#efeff4"}


def env_value(env_file: Path, name: str) -> str:
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{name} нет в {env_file}")


def init_data(uid: int, first_name: str, token: str) -> str:
    user = json.dumps({"id": uid, "first_name": first_name, "language_code": "ru"},
                      ensure_ascii=False, separators=(",", ":"))
    vals = {"auth_date": str(int(time.time())), "query_id": f"AAdemo{uid}", "user": user}
    dcs = "\n".join(f"{k}={vals[k]}" for k in sorted(vals))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    vals["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(vals, quote_via=quote)


class Shooter:
    def __init__(self, base: str, env_file: Path):
        self.base = base.rstrip("/")
        self.tokens = {"trainer": env_value(env_file, "TELEGRAM_BOT_TOKEN_TRAINER"),
                       "client": env_value(env_file, "TELEGRAM_BOT_TOKEN_CLIENT")}

    def idata(self, bot: str) -> str:
        uid, name = (DEMO_TRAINER_TG, "Алина") if bot == "trainer" else (PARENT_TG, "Ирина")
        return init_data(uid, name, self.tokens[bot])

    def url(self, path: str, bot: str) -> str:
        frag = urlencode({"tgWebAppData": self.idata(bot), "tgWebAppVersion": "8.0", "tgWebAppPlatform": "ios",
                          "tgWebAppThemeParams": json.dumps(THEME)}, quote_via=quote)
        return f"{self.base}{path}#{frag}"

    def api(self, path: str, bot: str = "trainer"):
        req = urllib.request.Request(self.base + path, headers={"X-Telegram-Init-Data": self.idata(bot)})
        with urllib.request.urlopen(req) as r:
            return json.load(r)


def settle(page: Page, ms: int = 4500) -> None:
    page.wait_for_load_state("load")
    page.wait_for_timeout(ms)


def check_page(page: Page, name: str) -> None:
    """AC-проверки кадра: ширина мобильная, нет undefined/null/NaN/ошибок загрузки."""
    width = page.evaluate("document.documentElement.clientWidth")
    assert width == 390, f"{name}: layout width {width}, ожидали 390"
    body = page.evaluate("document.body.innerText")
    for bad in ("undefined", "NaN", "null", "Не удалось загрузить", "Что-то пошло не так"):
        assert bad not in body, f"{name}: на экране «{bad}»"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8325")
    ap.add_argument("--env", type=Path, default=Path.home() / "Projects/trainer-crm-server/.env")
    ap.add_argument("--messages", type=Path, default=ROOT / "tmp" / "demo-bot-messages",
                    help="каталог со страницами из render_demo_bot_messages.py")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sh = Shooter(args.base, args.env)

    clients = sh.api("/api/webapp/trainer/clients")["clients"]
    sofia = next(c for c in clients if c.get("first_name") == "София")
    passes = sh.api(f"/api/webapp/trainer/clients/{sofia['id']}/passes")["items"]
    pass_id = next(p["id"] for p in passes if p.get("status") == "active")
    trainer_id = sh.api("/api/webapp/schedule?from_date=2000-01-01&to_date=2000-01-01")["trainer_id"]

    as_of = datetime.combine(datetime.now(MINSK).date(), AS_OF, tzinfo=MINSK)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
                                  has_touch=True, color_scheme="light", locale="ru-RU", timezone_id="Europe/Minsk")
        page = ctx.new_page()
        page.clock.install(time=as_of)

        def shot(name: str) -> None:
            check_page(page, name)
            page.screenshot(path=str(args.out / name))
            print("saved", name)

        def chat_shot(name: str, html: str) -> None:
            # Сообщение бота: окно по высоте сообщения, без пустого фона чата над ним.
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto((args.messages / html).resolve().as_uri()); settle(page, 500)
            gap = page.evaluate("""() => {
                const top = document.querySelector('header').getBoundingClientRect().bottom;
                return document.querySelector('.day').getBoundingClientRect().top - top;
            }""")
            page.set_viewport_size({"width": 390, "height": max(480, 844 - int(gap) + 28)})
            page.wait_for_timeout(300)
            shot(name)
            page.set_viewport_size({"width": 390, "height": 844})

        def visit(path: str, bot: str = "trainer", warm: bool = True) -> None:
            if warm:  # первый заход гасит одноразовые подсказки (как у тренера со второго дня)
                page.goto(sh.url(path, bot)); settle(page, 6000)
            page.goto(sh.url(path, bot)); settle(page)

        # 1. Неделя на трёх катках
        visit("/webapp/schedule-editor")
        shot("01-week.png")

        # 2. Карточка ученика
        card = f"/webapp/trainer-clients?client_id={sofia['id']}"
        visit(card)
        shot("02-student-card.png")

        # 3. Заметки и цели: раскрыть «Профиль клиента», показать его и заметки по занятиям
        page.click("#dossierProfileSection .dossier-section-header")
        page.wait_for_timeout(800)
        page.evaluate("""() => {
            const el = document.getElementById('dossierProfileSection');
            window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 12);
        }""")
        page.wait_for_timeout(800)
        shot("03-notes-goals.png")

        # 4. Абонемент «5 из 8»
        visit(f"/webapp/trainer-pass-products?pass_instance_id={pass_id}&client_id={sofia['id']}&tab=issued")
        shot("04-pass-5-of-8.png")

        # 5. Уведомление тренеру о новой записи (сообщение бота)
        chat_shot("05-new-booking-push.png", "trainer-new-booking.html")

        # 6. Запись глазами родителя: ссылка тренера → «Записаться» → первое окно → форма
        visit(f"/webapp/book?trainer_id={trainer_id}", bot="client")
        page.locator("button:visible, a:visible", has_text="Записаться").last.click()
        page.wait_for_timeout(2500)
        page.locator(".slot-card:visible, [data-slot-id]:visible").first.click()
        page.wait_for_timeout(2500)
        comment = page.locator("textarea:visible").first
        comment.fill("Коньки свои, придём сразу после массового катания")
        comment.blur()
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
        shot("06-parent-booking.png")

        # 7. Напоминание родителю
        chat_shot("07-parent-reminder.png", "client-reminder.html")

        # 8. Воскресная сводка тренеру
        chat_shot("08-weekly-digest.png", "trainer-weekly-digest.html")

        browser.close()


if __name__ == "__main__":
    main()
