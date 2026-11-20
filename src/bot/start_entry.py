"""
Универсальный ответ на ``/start <параметр>``: кнопка на тот же экран Mini App.

Публичные входы (сайт, /kk, /go, открытки) при ``public_entry_via_start`` ведут в чат бота
через ``t.me/<бот>?start=…``, чтобы чат с Glide появился. Особые параметры (``welcome_…``,
``cert_…``, ``watch_…``, ``mbell_…``, ``arena_…``, ``catalog…`` и т. д.) разбирают свои ветки
``cmd_start``. Всё остальное, что прошло ``is_valid_start_param``, приходит сюда: бот отвечает
одной фразой и одной кнопкой, а экран выбирает само приложение по ``?startapp=`` в адресе —
так же, как по ``start_param`` от Telegram (``glide-deeplink.js``, ``mini-app-client-shell.js``,
``kto-kogo.js``). Незнакомый приложению параметр открывает главную.

Модуль без aiogram: ответ проверяется тестом.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from src.application.place_links import is_valid_start_param, parse_trainer_start_param, trainer_webapp_url
from src.bot import messages as msg

#: Параметры, которые страница игры читает сама (``kto-kogo.js``): ``kks_<метка>`` — рекламный
#: вход (метка уходит в ``POST /client/hockey/entry`` и в первый ход), ``kk_<КОД>`` — приглашение
#: в лигу, ``kkl``/``kkr`` — кнопки карточек, ``kkv_<лига>_<ГГГГММДД>`` — «Вечер в лиге» из сводки,
#: ``kkg_<метка>`` — «Собрать лигу» из еженедельного приглашения (экран «Лига готова», метка входа).
_GAME_PAGE_RE = re.compile(
    r"^(?:kks_[A-Za-z0-9_-]*|kk_[A-Za-z0-9]{4,16}|kk[lr](?:_[A-Za-z0-9]{4,16})?|kkv_[1-9][0-9]*_[0-9]{8}"
    r"|kkg_[A-Za-z0-9]{2,16})$"
)
#: Остальные параметры игры (ход, итоги месяца, напоминания): их переводит в адрес игры
#: ``glide-deeplink.js`` на главной, поэтому кнопка ведёт на главную с тем же ``startapp``.
_GAME_VIA_HOME_RE = re.compile(
    r"^(?:kkn(?:_[1-9][0-9]*(?:_[ha](?:_[A-Za-z0-9]{2,16})?)?)?|kkmo_[1-9][0-9]*|kkoff|kkml|kktb)$"
)


#: Параметры, которые разбирает сам бот (особые ветки ``cmd_start``), а не Mini App. Если такая
#: ветка не ответила (кривая ссылка, нет коллектива, сертификат погашен…), остаётся прежнее
#: общее приветствие: кнопка на Mini App с таким параметром никуда бы не привела.
BOT_ONLY_PREFIXES = (
    "welcome_",  # welcome_t_<uuid>, welcome_ref_<тренер>
    "share_ref_",
    "preview_",
    "pass_",
    "client_",
    "cert_",
    "col_",
    "sg_",
    "mbell_",
    "watch_",
    "wbell_",
    "wphoto_",
    "wgone_",
    "wnear",
)


def is_game_start_param(payload: str) -> bool:
    return bool(_GAME_PAGE_RE.match(payload) or _GAME_VIA_HOME_RE.match(payload))


def start_entry_reply(payload: str | None, *, webapp_base_url: str | None) -> dict[str, Any] | None:
    """``{"text", "button_text", "url"}`` или ``None`` — невалидный параметр или база не HTTPS.

    ``None`` значит «как раньше»: вызывающий отвечает общим приветствием.
    """
    value = (payload or "").strip()
    if not value or not is_valid_start_param(value) or value.startswith(BOT_ONLY_PREFIXES):
        return None
    base = (webapp_base_url or "").strip().rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    parsed_trainer = parse_trainer_start_param(value)
    if parsed_trainer is not None:
        from src.shared.config import Settings

        if Settings().unified_trainer_card_enabled:
            url = trainer_webapp_url(
                base,
                int(parsed_trainer["trainer_id"]),
                arena_id=parsed_trainer["arena_id"],
                slot_id=parsed_trainer["slot_id"],
                via=parsed_trainer["via"],
                intent=parsed_trainer["intent"],
                legacy="catalog",
            )
            return {
                "text": msg.CLIENT_START_ENTRY_APP,
                "button_text": msg.CLIENT_BUTTON_START_ENTRY_APP,
                "url": url,
            }
    query = urlencode({"startapp": value})
    if _GAME_PAGE_RE.match(value):
        url = f"{base}/webapp/kto-kogo?{query}"
    else:
        url = f"{base}/webapp/client-home?{query}"
    if is_game_start_param(value):
        return {"text": msg.CLIENT_START_ENTRY_GAME, "button_text": msg.CLIENT_BUTTON_START_ENTRY_GAME, "url": url}
    return {"text": msg.CLIENT_START_ENTRY_APP, "button_text": msg.CLIENT_BUTTON_START_ENTRY_APP, "url": url}
