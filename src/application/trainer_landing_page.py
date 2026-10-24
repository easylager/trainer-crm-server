"""Лендинг тренера «Ученики с катка» (TASK-321/322, позиционирование TASK-320, цена PDEC-025).

Одна страница на два адреса: ``/trainers`` показывает на первом экране самый
просматриваемый каток, ``/trainers/{город}/{каток}`` — каток из адреса. Каток — живые
данные карточки места (``load_place_view``): фото, ближайший сеанс массового катания и
опубликованные тренеры этого катка. Тренер, которому прислали ссылку, видит свой лёд.

Макет утверждён владельцем 2026-10-23: https://claude.ai/artifact/FrgcxSoWgBr24pJNKYdwqN
"""
from __future__ import annotations

import html as html_lib
import json
import time
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.place_links import place_path
from src.application.place_page import load_place_view, slot_price, slot_when
from src.application.style_b import APP_MARK_SRC, media_url
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.public_display import format_public_name

# PDEC-025: одна цена, скидка за период; первым 10 тренерам — год по цене сезона.
PRICE_MONTH_BYN = 39
PRICE_QUARTER_BYN = 105
PRICE_YEAR_BYN = 375
PRICE_FOUNDING_YEAR_BYN = 299

# Отзыв: разрешение тренера на имя, катки и цифру — 2026-10-23 (TASK-320).
# Цитата и фото появятся, когда тренер их пришлёт; до этого блок без них.
PROOF_TRAINER_NAME = "Александр Гаевский"
PROOF_TRAINER_ROLE = "учит кататься с нуля, Минск"
PROOF_BOOKINGS = 208
PROOF_PERIOD = "за 2 месяца"
PROOF_QUOTE: str | None = None
PROOF_PHOTO_URL: str | None = None

RINK_PICKER_LIMIT = 10
_RINKS_CACHE_SECONDS = 3600
_rinks_cache: tuple[float, list[dict[str, Any]]] | None = None

# Предложение тренерам — белорусское: цены в BYN, отзыв и тексты про катки РБ. Катки России
# (каталог Питера открыт) лендинга под каток не получают и в «Где вы тренируете?» не попадают.
TRAINER_OFFER_COUNTRY = "BY"

# Порядок катков — по людям, открывшим их страницу за 30 дней (боты отфильтрованы),
# как в срезе спроса 2026-10-23: тренеру первым показываем каток, где больше всего глаз.
_RINKS_SQL = text(f"""
    SELECT a.id, c.name AS city_name, p.slug, a.name, COALESCE(v.people, 0) AS people
    FROM arenas a
    JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    LEFT JOIN (
        SELECT arena_id, COUNT(DISTINCT actor_hash) AS people
        FROM catalog_consumer_events
        WHERE occurred_at > now() - interval '30 days'
          AND arena_id IS NOT NULL
          AND kind IN ('public_page_view', 'miniapp_catalog_entry')
          AND COALESCE(payload->>'ua_class', 'human') = 'human'
        GROUP BY arena_id
    ) v ON v.arena_id = a.id
    WHERE {PUBLIC_ARENA_VISIBLE_SQL}
      AND p.status = 'published' AND p.slug IS NOT NULL
      AND a.venue_type = 'ice'
      AND c.country = :offer_country
    ORDER BY people DESC, c.sort_order, a.id
    LIMIT :limit
    """)


def _esc(value: Any) -> str:
    return html_lib.escape(str(value or ""), quote=True)


def trainer_rink_path(*, city_name: str, slug: str) -> str:
    """``/trainers/minsk/zamok`` — тот же город и slug, что у ``/p/minsk/zamok``."""
    return "/trainers" + place_path(city_name=city_name, slug=slug)[len("/p"):]


async def load_rink_picker(session: AsyncSession) -> list[dict[str, Any]]:
    """Катки для «Где вы тренируете?» и первого экрана ``/trainers``. Кэш на час."""
    global _rinks_cache
    now = time.monotonic()
    if _rinks_cache is not None and now - _rinks_cache[0] < _RINKS_CACHE_SECONDS:
        return _rinks_cache[1]
    params = {**public_scope_params(), "limit": RINK_PICKER_LIMIT, "offer_country": TRAINER_OFFER_COUNTRY}
    rows = (await session.execute(_RINKS_SQL, params)).mappings().all()
    rinks = [
        {
            "id": int(r["id"]),
            "name": format_public_name(str(r["name"] or "")),
            "city_name": str(r["city_name"] or ""),
            "slug": str(r["slug"]),
            "href": trainer_rink_path(city_name=str(r["city_name"] or ""), slug=str(r["slug"])),
        }
        for r in rows
    ]
    _rinks_cache = (now, rinks)
    return rinks


def clear_rink_picker_cache_for_tests() -> None:
    global _rinks_cache
    _rinks_cache = None


async def load_landing_rink(session: AsyncSession, arena_id: int) -> dict[str, Any] | None:
    """Каток для первого экрана: фото, ближайший сеанс, до двух опубликованных тренеров."""
    view = await load_place_view(session, str(arena_id))
    if view is None:
        return None
    card = view["card"]
    hero = card.get("hero") if isinstance(card.get("hero"), Mapping) else None
    city_name = str(card.get("city_name") or "")
    slug = str(card.get("slug") or "")
    slot = view.get("next_slot")
    slot_view = None
    if slot:
        when = slot_when(slot, today=view["today"])
        day, _, clock = when.rpartition(", ")
        slot_view = {"day": day or when, "time": clock if day else "", "price": slot_price(slot)}
    return {
        "id": int(card["id"]),
        "name": format_public_name(str(card.get("name") or "")),
        "city_name": city_name,
        "slug": slug,
        "place_url": place_path(city_name=city_name, slug=slug) if slug else None,
        "photo_url": media_url(hero, size="hero") or media_url(hero, size="card"),
        "slot": slot_view,
        "trainers": list(view.get("trainers") or [])[:2],
        "trainer_count": len(view.get("trainers") or []),
    }


# ─── Разметка ────────────────────────────────────────────────────────────────


def _mark() -> str:
    # Знак бренда — тот же файл, что у кнопки приложения на сайте (style_b.APP_MARK_SRC).
    return f'<img class="tl-brand__mark" src="{APP_MARK_SRC}" width="40" height="40" alt="">'


def _coach_card(trainer: Mapping[str, Any]) -> str:
    photo = trainer.get("photo_url")
    ph = (
        f'<img src="{_esc(photo)}" alt="" loading="lazy">'
        if photo
        else f'<i aria-hidden="true">{_esc(trainer.get("initial") or "Т")}</i>'
    )
    return (
        '<div class="tl-coach">'
        f'<span class="tl-coach__ph">{ph}</span>'
        f'<span class="tl-coach__body"><b>{_esc(trainer.get("name"))}</b>'
        f'<span>{_esc(trainer.get("line"))}</span></span>'
        "</div>"
    )


def _you_card(first: bool) -> str:
    sub = "Станьте первым тренером здесь" if first else "Учите кататься здесь же"
    return (
        '<div class="tl-coach tl-coach--you">'
        '<span class="tl-coach__ph"><i aria-hidden="true">+</i>'
        '<em>окно сразу после катания</em></span>'
        f'<span class="tl-coach__body"><b>Здесь можете быть вы</b><span>{_esc(sub)}</span></span>'
        "</div>"
    )


def _phone(rink: Mapping[str, Any] | None) -> str:
    if rink is None:
        return ""
    slot = rink.get("slot")
    slot_html = ""
    if slot:
        price = f'<span>Взрослый {_esc(slot["price"])}</span>' if slot.get("price") else ""
        slot_html = (
            '<div class="tl-phone__slot">'
            f'<span><small>{_esc(slot["day"])} · массовое катание</small><b>{_esc(slot["time"] or slot["day"])}</b></span>{price}'
            "</div>"
        )
    trainers = list(rink.get("trainers") or [])
    count = int(rink.get("trainer_count") or 0)
    cards = "".join(_coach_card(t) for t in trainers[:1]) + _you_card(first=count == 0)
    kicker = f"Тренеры этого катка · {count}" if count else "Тренеры этого катка"
    return (
        '<div class="tl-phone" aria-label="Так выглядит страница катка в Glide">'
        f'<span class="tl-phone__where">{_esc(rink.get("city_name"))} · {_esc(rink.get("name"))}</span>'
        f"{slot_html}"
        f'<span class="tl-phone__kick">{_esc(kicker)}</span>'
        '<b class="tl-phone__title">Научат здесь же</b>'
        f'<div class="tl-phone__row">{cards}</div>'
        "</div>"
    )


def _hero(rink: Mapping[str, Any] | None, *, rink_page: bool, join_href: str) -> str:
    photo = rink.get("photo_url") if rink else None
    style = f' style="--tl-photo:url(&quot;{_esc(photo)}&quot;)"' if photo else ""
    if rink_page and rink:
        kicker = f"Тренерам катка «{rink['name']}»"
    else:
        kicker = "Для тренеров, которые учат кататься"
    cta = "Попасть на страницу катка" if rink else "Начать в Telegram"
    return (
        f'<section class="tl-hero{" tl-hero--photo" if photo else ""}"{style}>'
        '<div class="tl-wrap tl-hero__in">'
        '<header class="tl-top">'
        f'<a class="tl-brand" href="/" aria-label="Glide — расписание катков">{_mark()}<span>Glide</span></a>'
        '<nav class="tl-nav" aria-label="Разделы">'
        '<a href="#how">Как это работает</a><a href="#price">Цены</a><a href="#rinks">Катки</a>'
        f'<a class="tl-btn tl-btn--light js-tl-join" href="{_esc(join_href)}">Начать в Telegram</a>'
        "</nav></header>"
        '<div class="tl-hero__grid">'
        '<div class="tl-hero__copy">'
        f'<span class="tl-kicker">{_esc(kicker)}</span>'
        '<h1>Ваши ученики<br>уже катаются.<br><em>Рядом с вами.</em></h1>'
        "<p>Люди открывают Glide, чтобы узнать, когда массовое катание. Рядом с сеансом — "
        "тренеры этого катка и их свободное окно сразу после катания. А свои ученики записываются "
        "по вашей ссылке — без переписки «а когда можно?».</p>"
        '<div class="tl-hero__cta">'
        f'<a class="tl-btn tl-btn--accent js-tl-join" href="{_esc(join_href)}">{cta}</a>'
        "<span>Бесплатно. Настроим<br>вместе за 15 минут</span></div>"
        '<span class="tl-hero__note">Тренируете на нескольких катках? Вы появитесь на странице каждого.</span>'
        "</div>"
        f"{_phone(rink)}"
        "</div></div></section>"
    )


def _how() -> str:
    steps = (
        ("Человек ищет, когда покататься",
         "Открывает Glide — сайт или Mini App в Telegram — и смотрит расписание массового катания на своём катке."),
        ("Видит вас рядом с сеансом",
         "«Научат здесь же» — ваша карточка и свободное окно сразу после его катания."),
        ("Записывается в один тап",
         "Запись приходит вам в Telegram. Дальше Glide ведёт её сам: напоминания, абонемент, перенос."),
    )
    items = "".join(
        f'<li class="tl-step{" tl-step--dark" if i == 2 else ""}"><i>{i + 1}</i><b>{_esc(t)}</b><span>{_esc(d)}</span></li>'
        for i, (t, d) in enumerate(steps)
    )
    return (
        '<section id="how" class="tl-wrap tl-sec">'
        '<h2 class="tl-h2">От «когда каток?»&nbsp;—<br>до записи к вам</h2>'
        f'<ol class="tl-steps">{items}</ol>'
        '<div class="tl-flow">'
        + _shot("06-parent-booking", "Мама записывает Софию", "Сама выбирает окно после катания — без «а когда можно?»")
        + '<span class="tl-flow__arrow" aria-hidden="true">→</span>'
        + _shot("05-new-booking-push", "Вам приходит запись", "В Telegram, с комментарием и кнопкой «Подтвердить»")
        + "</div></section>"
    )


# Высота кадра в CSS px при ширине 390: сообщения бота обрезаны по сообщению.
_SHOT_HEIGHTS = {"05-new-booking-push": 480, "07-parent-reminder": 604, "08-weekly-digest": 629}


def _shot(name: str, title: str, caption: str) -> str:
    """Экран продукта на демо-данных (TASK-325) в рамке телефона с подписью."""
    height = _SHOT_HEIGHTS.get(name, 844)
    return (
        '<figure class="tl-shot">'
        f'<img src="/landing/shots/{name}.webp" width="390" height="{height}" loading="lazy" alt="{_esc(title)}">'
        f"<figcaption><b>{_esc(title)}</b><span>{_esc(caption)}</span></figcaption>"
        "</figure>"
    )


def _versus() -> str:
    before = (
        "«А на четверг вечером есть окошко?» — десять раз в неделю",
        "Напомнить о занятии — самому, каждому",
        "Сколько осталось по абонементу — в голове или заметках",
        "Перенос — ещё одна переписка",
    )
    after = (
        "Родители сами видят свободные окна и записываются",
        "Напоминания уходят сами — ученику и родителям",
        "Абонемент списывается сам, остаток виден обоим",
        "Перенос — в приложении, без переписки",
    )
    li = lambda xs: "".join(f"<li>{_esc(x)}</li>" for x in xs)  # noqa: E731
    return (
        '<section class="tl-wrap tl-sec">'
        '<h2 class="tl-h2">Ваши ученики — тоже по ссылке</h2>'
        '<div class="tl-versus">'
        f'<div class="tl-card"><b class="tl-versus__t">Сейчас — чат с родителями</b><ul>{li(before)}</ul></div>'
        f'<div class="tl-card tl-card--dark"><b class="tl-versus__t tl-versus__t--accent">С Glide — одна ссылка</b><ul>{li(after)}</ul></div>'
        "</div></section>"
    )


def _proof() -> str:
    initial = PROOF_TRAINER_NAME[:1]
    photo = (
        f'<img class="tl-proof__ph" src="{_esc(PROOF_PHOTO_URL)}" alt="{_esc(PROOF_TRAINER_NAME)}">'
        if PROOF_PHOTO_URL
        else f'<span class="tl-proof__ph" aria-hidden="true">{_esc(initial)}</span>'
    )
    quote = f"<blockquote>«{_esc(PROOF_QUOTE)}»</blockquote>" if PROOF_QUOTE else ""
    return (
        '<section class="tl-wrap tl-sec"><figure class="tl-proof">'
        f"{photo}"
        f'<div class="tl-proof__text">{quote}'
        f"<figcaption><b>{_esc(PROOF_TRAINER_NAME)}</b>, {_esc(PROOF_TRAINER_ROLE)}</figcaption></div>"
        f'<div class="tl-proof__num"><b>{PROOF_BOOKINGS}</b>'
        f"<span>записей {_esc(PROOF_PERIOD)} — без переписки «когда можно»</span></div>"
        "</figure></section>"
    )


def _features() -> str:
    shots = (
        ("01-week", "Неделя на трёх катках", "Чижовка, Ледовый дворец, «Замок» — одним списком, окна по каждому."),
        ("02-student-card", "Карточка ученика", "Контакты родителя, история занятий, абонемент — в одном месте."),
        ("03-notes-goals", "Заметки и цели", "«Держит внешнее ребро», «к декабрю — сальхов». Вместо блокнота."),
        ("04-pass-5-of-8", "Абонемент «5 из 8»", "Занятия списываются сами, остаток видят и вы, и родители."),
        ("07-parent-reminder", "Напоминание родителю", "Накануне — время, каток, адрес. Уходит само."),
        ("08-weekly-digest", "Сводка за неделю", "Занятия, деньги, новые ученики — каждое воскресенье."),
    )
    items = "".join(_shot(n, t, d) for n, t, d in shots)
    return (
        '<section class="tl-wrap tl-sec">'
        '<h2 class="tl-h2">И всё, чтобы вести учеников</h2>'
        '<p class="tl-lede">Так это выглядит в Telegram. Группы «с нуля» и индивидуальные — в том же календаре.</p>'
        f'<div class="tl-shots">{items}</div></section>'
    )


def _price() -> str:
    return (
        '<section id="price" class="tl-wrap tl-sec">'
        '<h2 class="tl-h2">Место на катке — бесплатно.<br>Запись без переписки — по подписке.</h2>'
        '<div class="tl-versus">'
        '<div class="tl-card tl-plan">'
        '<div class="tl-plan__head"><b>Карточка на катке</b><strong>0 BYN</strong></div>'
        "<p>Вы в «Научат здесь же» на странице своих катков. Вам пишут в Telegram.</p>"
        "<ul><li>Фото, цена, катки</li><li>«Написать в Telegram»</li><li>Навсегда, без условий</li></ul>"
        "</div>"
        '<div class="tl-card tl-card--dark tl-plan">'
        f'<div class="tl-plan__head"><b>Подписка</b><strong>{PRICE_MONTH_BYN} BYN<small> / мес</small></strong></div>'
        '<span class="tl-plan__anchor">Обычно это меньше одного занятия в месяц</span>'
        "<p>Ученики сами записываются в ваши окна — с катка и по вашей ссылке. Сколько бы их ни было.</p>"
        "<ul><li>«Записаться» на карточке</li><li>Напоминания, абонементы, группы, переносы</li>"
        f"<li>{PRICE_QUARTER_BYN} BYN за 3 месяца · {PRICE_YEAR_BYN} BYN за год</li></ul>"
        "</div></div>"
        '<p class="tl-fine">Подписка бесплатна до первого проведённого занятия и ещё 14 дней после. '
        "Не продлили — карточка остаётся на катке. "
        f"Первым десяти тренерам — год за {PRICE_FOUNDING_YEAR_BYN} BYN.</p>"
        "</section>"
    )


def _setup(join_href: str) -> str:
    steps = (
        ("1. Окна", "Ваша неделя на каждом катке — один раз, дальше само."),
        ("2. Ученики", "Постоянные ученики — в список, даже если их ещё нет в боте."),
        ("3. Текст для родителей", "Готовое сообщение со ссылкой — отправите в чат, и запись пошла."),
    )
    items = "".join(f"<li><b>{_esc(t)}</b><span>{_esc(d)}</span></li>" for t, d in steps)
    return (
        '<section class="tl-wrap tl-sec"><div class="tl-setup">'
        '<h2 class="tl-h2">Настроим вместе за 15 минут</h2>'
        f"<ol>{items}</ol>"
        f'<a class="tl-btn tl-btn--dark js-tl-join" href="{_esc(join_href)}">Начать в Telegram</a>'
        "</div></section>"
    )


def _rinks(rinks: list[dict[str, Any]], current_id: int | None) -> str:
    if not rinks:
        return ""
    chips = "".join(
        f'<a class="tl-chip{" is-on" if r["id"] == current_id else ""}" href="{_esc(r["href"])}">'
        f'{_esc(r["name"])}{", " + _esc(r["city_name"]) if r["city_name"] != "Минск" else ""}</a>'
        for r in rinks
    )
    return (
        '<section id="rinks" class="tl-wrap tl-sec">'
        '<h2 class="tl-h2">Где вы тренируете?</h2>'
        '<p class="tl-lede">Откройте страницу своего катка — увидите, где появится ваша карточка.</p>'
        f'<nav class="tl-chips" aria-label="Катки">{chips}<a class="tl-chip tl-chip--more" href="/">Все катки →</a></nav>'
        "</section>"
    )


def _faq() -> str:
    qa = (
        ("Ученикам нужно ставить приложение?", "Нет. Запись — в Telegram, который у всех уже есть."),
        ("Я тренирую на нескольких катках",
         "Укажите все — карточка появится на странице каждого, окна видны по каждому катку."),
        ("Что будет после пробного периода?",
         "Карточка на катке остаётся бесплатно. Без подписки на ней кнопка «Написать» вместо «Записаться»."),
        ("Часть учеников привыкла писать в личку",
         "Пусть пишут — запишите их сами из карточки клиента. Ссылка не отменяет переписку, а убирает лишнюю."),
        ("Кто видит моих учеников?",
         "В каталоге — только ваша карточка: имя, фото, цена, катки. Ученики, их телефоны и заметки "
         "туда не попадают и другим тренерам не видны."),
        ("Сколько стоит?",
         f"Карточка — бесплатно. Подписка — {PRICE_MONTH_BYN} BYN в месяц, {PRICE_QUARTER_BYN} BYN за 3 месяца, "
         f"{PRICE_YEAR_BYN} BYN за год."),
    )
    items = "".join(f"<details><summary>{_esc(q)}</summary><p>{_esc(a)}</p></details>" for q, a in qa)
    return f'<section class="tl-wrap tl-sec"><h2 class="tl-h2">Вопросы</h2><div class="tl-faq">{items}</div></section>'


def _final(rink: Mapping[str, Any] | None, join_href: str) -> str:
    title = f"«{_esc(rink['name'])}» уже в Glide." if rink else "Ваш каток уже в Glide."
    return (
        '<section class="tl-wrap tl-final">'
        f'<h2 class="tl-h2">{title}<br><em>А вы?</em></h2>'
        f'<a class="tl-btn tl-btn--accent js-tl-join" href="{_esc(join_href)}">Начать в Telegram</a>'
        "<span>Бесплатно · настроим вместе за 15 минут</span>"
        "</section>"
    )


def faq_jsonld(canonical_url: str) -> dict[str, Any]:
    """FAQPage для поисковика — те же вопросы, что на странице."""
    return {
        "@type": "FAQPage",
        "url": canonical_url,
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Сколько стоит Glide для тренера?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        f"Карточка на странице катка — бесплатно. Подписка — {PRICE_MONTH_BYN} BYN в месяц, "
                        f"{PRICE_QUARTER_BYN} BYN за 3 месяца, {PRICE_YEAR_BYN} BYN за год."
                    ),
                },
            },
            {
                "@type": "Question",
                "name": "Ученикам нужно ставить приложение?",
                "acceptedAnswer": {"@type": "Answer", "text": "Нет. Запись — в Telegram."},
            },
        ],
    }


def render_trainer_landing_body(
    *,
    rink: Mapping[str, Any] | None,
    rinks: list[dict[str, Any]],
    rink_page: bool,
    join_href: str,
) -> str:
    """Всё содержимое ``<main>``: от первого экрана до финального призыва."""
    return (
        _hero(rink, rink_page=rink_page, join_href=join_href)
        + _how()
        + _versus()
        + _proof()
        + _features()
        + _price()
        + _setup(join_href)
        + _rinks(rinks, int(rink["id"]) if rink else None)
        + _faq()
        + _final(rink if rink_page else None, join_href)
    )


def join_href_for(rink: Mapping[str, Any] | None, *, rink_page: bool) -> str:
    """``/join`` с катком для аудита; UTM и ``from`` скрипт дописывает из адреса страницы."""
    if rink and rink_page:
        return f"/join?arena={int(rink['id'])}"
    return "/join"


def config_json(*, ym_counter_id: int | None) -> str:
    data: dict[str, Any] = {}
    if ym_counter_id:
        data["ym_counter_id"] = int(ym_counter_id)
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def render_trainer_landing_page(
    *,
    rink: Mapping[str, Any] | None,
    rinks: list[dict[str, Any]],
    rink_page: bool,
    settings: Any = None,
) -> str:
    """Полная страница. ``rink_page`` — адрес ``/trainers/{город}/{каток}``: noindex, канон на
    ``/trainers``, превью — картинка этого катка."""
    from src.application.landing_manifest import (
        _landing_jsonld_script,
        _landing_public_base,
        _landing_seo_urls,
        _landing_site_footer_html,
        _landing_site_head_html,
        load_landing_manifest,
    )
    from src.application.public_analytics import public_analytics_head_html
    from src.shared.config import Settings
    from src.application.style_b import _file_version as static_file_version

    s = settings or Settings()
    manifest = load_landing_manifest(s)
    seo = manifest.get("seo") or {}
    canonical_url, og_image = _landing_seo_urls(s, manifest)
    base = _landing_public_base(s)
    title = str(seo.get("title") or "Glide для тренеров")
    description = str(seo.get("description") or "")
    robots = "index, follow"
    og_w, og_h, og_alt = 1200, 630, "Glide: запись к тренеру по ссылке — расписание с выбором свободного времени"
    page_url = canonical_url
    # Страница катка — noindex; canonical на другую страницу рядом с noindex — противоречивый сигнал.
    canonical_link = "" if (rink_page and rink) else f'  <link rel="canonical" href="{_esc(canonical_url)}">\n'
    if rink_page and rink:
        title = f"Тренерам катка «{rink['name']}» — Glide"
        description = (
            f"Покажитесь рядом с массовым катанием на катке «{rink['name']}»: ученики видят ваше "
            "свободное окно сразу после катания и записываются в Telegram. Карточка — бесплатно."
        )
        robots = "noindex, follow"
        page_url = f"{base}{trainer_rink_path(city_name=rink['city_name'], slug=rink['slug'])}"
        if rink.get("place_url"):
            og_image = f"{base}{rink['place_url']}/og.png"
            og_alt = f"Расписание катка «{rink['name']}» в Glide"
    jsonld = _landing_jsonld_script(s, manifest, canonical_url)
    if not rink_page:
        faq = json.dumps(
            {"@context": "https://schema.org", **faq_jsonld(canonical_url)}, ensure_ascii=False
        ).replace("</", "<\\/")
        jsonld += f'  <script type="application/ld+json">{faq}</script>\n'
    analytics = public_analytics_head_html(
        yandex_metrika_counter_id=s.yandex_metrika_counter_id,
        google_analytics_measurement_id=s.google_analytics_measurement_id,
    )
    css_v = static_file_version("static/landing/trainer-landing.css")
    js_v = static_file_version("static/landing/trainer-landing.js")
    join_href = join_href_for(rink, rink_page=rink_page)
    body = render_trainer_landing_body(rink=rink, rinks=rinks, rink_page=rink_page, join_href=join_href)
    t, d = _esc(title), _esc(description)
    return f"""<!DOCTYPE html>
<html lang="ru-BY">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{t}</title>
  <meta name="description" content="{d}">
  <meta name="robots" content="{robots}">
  <meta name="theme-color" content="#101617">
{canonical_link}  <meta property="og:type" content="website">
  <meta property="og:locale" content="ru_RU">
  <meta property="og:site_name" content="Glide">
  <meta property="og:title" content="{t}">
  <meta property="og:description" content="{d}">
  <meta property="og:url" content="{_esc(page_url)}">
  <meta property="og:image" content="{_esc(og_image)}">
  <meta property="og:image:width" content="{og_w}">
  <meta property="og:image:height" content="{og_h}">
  <meta property="og:image:alt" content="{_esc(og_alt)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{t}">
  <meta name="twitter:description" content="{d}">
  <meta name="twitter:image" content="{_esc(og_image)}">
  <link rel="icon" href="/favicon.ico" type="image/png">
  <link rel="apple-touch-icon" href="/logos/01-icon/glide-icon-teal-square-512.png">
{_landing_site_head_html()}
  <link rel="stylesheet" href="/landing/trainer-landing.css?v={css_v}">
  {analytics}
  <script id="tl-config" type="application/json">{config_json(ym_counter_id=s.yandex_metrika_counter_id)}</script>
{jsonld}</head>
<body class="tl">
<a class="tl-skip" href="#how">К содержимому</a>
<main>
{body}
</main>
{_landing_site_footer_html()}
<script src="/landing/trainer-landing.js?v={js_v}" defer></script>
</body>
</html>
"""
