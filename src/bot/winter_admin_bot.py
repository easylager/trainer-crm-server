"""Админ-бот «Зимой»: сезон одной кнопкой (TASK-343, волна 2).

``/winter`` — экран «Зимние точки»: подтвердить на сезон / скрыть пачкой по городу, очередь по
приоритету, дубли и слияние, сверка с таблицей нового сезона. ``/winter_import`` (или файл с
подписью ``/winter_import``) — загрузка CSV 2026/27: бот показывает дифф и ждёт кнопок.

Правила:
* каждая пачка сначала показывает число («Подтвердить 25 точек?»), применяется с этим же числом:
  если список за это время изменился, бот просит открыть экран заново;
* подтверждение и скрытие отменяются 10 минут; слияние необратимо и просит второе «да»;
* все колбэки проверяют ``admin_telegram_ids``, повторное нажатие безопасно;
* молчание админа ничего не публикует: бот только напоминает (ежедневная сводка).
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.application import winter_admin as wa
from src.application import winter_diff as wd
from src.application import winter_queue as wq
from src.bot import winter_bot
from src.infrastructure.db import async_session_factory
from src.shared import winter_status as ws

logger = logging.getLogger(__name__)

ops_router = Router(name="winter_admin_ops")

_awaiting_import: set[int] = set()
MAX_CITY_BUTTONS = 24
MAX_FILE_BYTES = 2 * 1024 * 1024
KIND_CODE = {"a": None, "r": "rink", "b": "hockey_box"}
PREC_CODE = {"a": None, "m": "map", "n": "nomap"}
SCOPE_CODE = {"u": "unconfirmed", "c": "candidates"}
_ALERT_MAX = 190


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _btn(text: str, data: str) -> InlineKeyboardButton:
    assert len(data.encode()) <= 64, data
    return InlineKeyboardButton(text=text, callback_data=data)


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


# --- выбор для пачки: кодирование в callback_data -----------------------------------
def sel_to_code(sel: wa.Selection) -> str:
    kind = next(k for k, v in KIND_CODE.items() if v == sel.kind)
    prec = next(k for k, v in PREC_CODE.items() if v == sel.precision)
    scope = next(k for k, v in SCOPE_CODE.items() if v == sel.scope)
    return f"{sel.city_id or 0}:{kind}:{prec}:{scope}"


def sel_from_code(code: str) -> wa.Selection:
    city, kind, prec, scope = code.split(":")
    return wa.Selection(
        city_id=int(city) or None, kind=KIND_CODE[kind], precision=PREC_CODE[prec], scope=SCOPE_CODE[scope]
    )


def describe_selection(sel: wa.Selection, city_name: str | None) -> str:
    bits = [city_name or "все города"]
    bits.append({"rink": "только катки", "hockey_box": "только коробки"}.get(sel.kind or "", "катки и коробки"))
    if sel.precision == "map":
        bits.append("с точным адресом")
    elif sel.precision == "nomap":
        bits.append("адрес уточняется")
    if sel.scope == "candidates":
        bits.append("кандидаты из OSM")
    return ", ".join(bits)


# --- тексты экранов ------------------------------------------------------------------
def home_text(ov: dict[str, Any], q: dict[str, Any]) -> str:
    lines = [f"<b>Зимние точки, сезон {_esc(ov['season_label'])}</b>"]
    lines.append(f"Не подтверждено на сезон: <b>{ov['unconfirmed']}</b>"
                 + (f" · кандидатов из OSM: {ov['candidates']}" if ov["candidates"] else ""))
    if q["total"]:
        lines.append("Очередь: " + ", ".join(f"{label} {q['by_kind'][k]}" for k, label in wq.PRIORITY if q["by_kind"].get(k)))
        lines.append(f"Старейшая запись: {q['oldest_hours']} ч назад")
    else:
        lines.append("Очередь пуста.")
    if q["import_runs"]:
        lines.append(f"Сверка с таблицей: ждёт решения {q['import_runs']}")
    lines.append("Статус льда подтверждение не меняет. Пока вы молчите, ничего не публикуется.")
    return "\n".join(lines)


def home_keyboard(ov: dict[str, Any], q: dict[str, Any]) -> InlineKeyboardMarkup:
    rows = []
    if ov["unconfirmed"] or ov["candidates"]:
        rows.append([_btn(f"Подтвердить по городам ({ov['unconfirmed'] + ov['candidates']})", "wa:cities")])
    if q["total"]:
        rows.append([_btn(f"Очередь ({q['total']})", "wa:q")])
    rows.append([_btn("Дубли", "wa:dups:0")])
    if q["import_runs"]:
        rows.append([_btn(f"Сверка с таблицей ({q['import_runs']})", "wa:runs")])
    return _kb(*rows)


def run_text(run: dict[str, Any]) -> str:
    diff, c = run["diff"], run["diff"]["counts"]
    head = f"<b>Сверка: {_esc(run.get('label') or 'таблица')}</b> (сезон {_esc(ws.season_label(int(run['season'])))})"
    if run["status"] == "failed":
        return f"{head}\nНе применяю: {_esc(run.get('error'))}.\nПроверьте файл: если структура поменялась, пришлите его разработчику."
    lines = [head, f"В файле {c['file_rows']} точек, у нас по этим городам {c['base']}."]
    sample = lambda items, fmt: "\n".join("  " + fmt(i) for i in items[:5])  # noqa: E731
    if c["new"]:
        lines.append(f"\nНовые: <b>{c['new']}</b>\n" + sample(diff["new"], lambda i: f"{_esc(i['city'])}, {_esc(i['name'])}"))
    if c["changed"]:
        lines.append(f"\nИзменились часы или телефон: <b>{c['changed']}</b>")
        for i in diff["changed"][:5]:
            what = []
            if "hours" in i["fields"]:
                what.append(f"часы {_esc(i['hours_old'] or 'нет')} → {_esc(i['hours_new'])}")
            if "phone" in i["fields"]:
                what.append(f"тел. {_esc(i['phone_old'] or 'нет')} → {_esc(i['phone_new'])}")
            lines.append(f"  {_esc(i['city'])}, {_esc(i['name'])}: " + "; ".join(what))
    if c["verified"]:
        lines.append(f"Часы совпали (получат подпись «часы {_esc(ws.season_label(int(run['season'])))}»): {c['verified']}")
    if c["missing"]:
        lines.append(f"\nНет в новой таблице: <b>{c['missing']}</b>\n"
                     + sample(diff["missing"], lambda i: f"{_esc(i['city'])}, {_esc(i['name'])}")
                     + "\nТочки с живым «залит» и подтверждённые за 30 дней не скрою.")
    if c["same"]:
        lines.append(f"\nПохоже на ту же точку (другое название или адрес): <b>{c['same']}</b>\n"
                     + sample(diff["same"], lambda i: f"{_esc(i['address_old'] or i['name'])} → {_esc(i['address_new'])}"))
    if c["skipped_catalog"]:
        lines.append(f"\nУже есть в каталоге как арены (пропущены): {c['skipped_catalog']}")
    if not wd.available_parts(diff):
        lines.append("\nРазличий нет.")
    return "\n".join(lines)


def run_keyboard(run: dict[str, Any]) -> InlineKeyboardMarkup:
    if run["status"] != "pending":
        return _kb()
    rid, c, done = run["id"], run["diff"]["counts"], set(run.get("applied_parts") or [])
    rows = []
    if "new" in wd.available_parts(run["diff"]) and "new" not in done:
        rows.append([_btn(f"Создать новые ({c['new']})", f"wa:ra:{rid}:new")])
    if "changed" in wd.available_parts(run["diff"]) and "changed" not in done:
        rows.append([_btn(f"Обновить часы и телефоны ({c['changed'] + c['verified']})", f"wa:ra:{rid}:changed")])
    if "same" in wd.available_parts(run["diff"]) and "same" not in done:
        rows.append([_btn(f"Это те же точки ({c['same']})", f"wa:ra:{rid}:same")])
    if "missing" in wd.available_parts(run["diff"]) and "missing" not in done:
        rows.append([_btn(f"Скрыть пропавшие ({c['missing']})", f"wa:ra:{rid}:missing")])
    rows.append([_btn("Отклонить сверку", f"wa:rr:{rid}")])
    return _kb(*rows)


def dup_text(group: wa.DupGroup, index: int, total: int) -> str:
    keep = group.keep_candidate()
    why = ", ".join({"address": "один адрес", "name": "одно название", "geo": "рядом на карте"}[r] for r in sorted(group.reasons))
    lines = [f"<b>Дубли {index + 1} из {total}</b> ({_esc(why)})"]
    for m in group.members:
        mark = " ← оставить" if m.arena_id == keep.arena_id else ""
        lines.append(
            f"#{m.arena_id} {_esc(m.name)}, {_esc(m.address or 'без адреса')} · {_esc(m.state)} · "
            f"отметок {m.marks}, колокольчиков {m.subs}, фото {m.photos}{mark}"
        )
    return "\n".join(lines)


def dup_keyboard(group: wa.DupGroup, index: int, total: int) -> InlineKeyboardMarkup:
    keep = group.keep_candidate()
    rows = [[_btn(f"Влить #{m.arena_id} в #{keep.arena_id}", f"wa:m:{m.arena_id}:{keep.arena_id}")]
            for m in group.members if m.arena_id != keep.arena_id]
    nav = []
    if index + 1 < total:
        nav.append(_btn("Не дубли, дальше", f"wa:dups:{index + 1}"))
    return _kb(*rows, nav)


# --- вспомогательное ------------------------------------------------------------------
async def _is_admin_query(query: CallbackQuery) -> bool:
    if not winter_bot._is_admin(query.from_user.id):
        await query.answer("Нет доступа", show_alert=True)
        return False
    return True


async def _show(query: CallbackQuery, body: str, markup: InlineKeyboardMarkup | None) -> None:
    """Заменить экран; если сообщение нельзя править (фото, старое) — отправить новое."""
    msg = query.message
    if msg is None:
        return
    try:
        await msg.edit_text(body, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        await msg.answer(body, reply_markup=markup)


async def _home(session) -> tuple[str, InlineKeyboardMarkup]:
    ov = await wa.season_overview(session, _now())
    q = await wq.queue_overview(session, _now())
    return home_text(ov, q), home_keyboard(ov, q)


@ops_router.message(Command("winter"))
async def cmd_winter(message: Message) -> None:
    if not message.from_user or not winter_bot._is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    async with async_session_factory() as session:
        body, kb = await _home(session)
    await message.answer(body, reply_markup=kb)


@ops_router.callback_query(F.data == "wa:home")
async def on_home(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    async with async_session_factory() as session:
        body, kb = await _home(session)
    await _show(query, body, kb)
    await query.answer()


# --- города и пачки ---------------------------------------------------------------------
@ops_router.callback_query(F.data == "wa:cities")
async def on_cities(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    async with async_session_factory() as session:
        ov = await wa.season_overview(session, _now())
    buttons = [_btn(f"{c['city']} · {c['unconfirmed'] + c['candidates']}", f"wa:c:{c['city_id']}") for c in ov["cities"][:MAX_CITY_BUTTONS]]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.insert(0, [_btn(f"Все города: подтвердить {ov['unconfirmed']}", "wa:p:ok:" + sel_to_code(wa.Selection()))])
    rows.append([_btn("Назад", "wa:home")])
    more = len(ov["cities"]) - MAX_CITY_BUTTONS
    await _show(query, "<b>Города</b>: сколько точек ждёт подтверждения на сезон." + (f"\nЕщё городов: {more}." if more > 0 else ""), _kb(*rows))
    await query.answer()


async def _city_name(session, city_id: int | None) -> str | None:
    if not city_id:
        return None
    from sqlalchemy import text

    return (await session.execute(text("SELECT name FROM cities WHERE id=:i"), {"i": city_id})).scalar_one_or_none()


@ops_router.callback_query(F.data.startswith("wa:c:"))
async def on_city(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    city_id = int((query.data or "").split(":")[2])
    season = ws.current_season(_now())
    async with async_session_factory() as session:
        name = await _city_name(session, city_id)
        count = lambda **kw: wa.select_ids(session, wa.Selection(city_id=city_id, **kw), season)  # noqa: E731
        total, rinks, boxes = len(await count()), len(await count(kind="rink")), len(await count(kind="hockey_box"))
        exact, cands = len(await count(precision="map")), len(await count(scope="candidates"))
    mk = lambda act, **kw: f"wa:p:{act}:" + sel_to_code(wa.Selection(city_id=city_id, **kw))  # noqa: E731
    rows = []
    if total:
        rows.append([_btn(f"Подтвердить все ({total})", mk("ok"))])
        sub = []
        if rinks and boxes:
            sub += [_btn(f"Катки ({rinks})", mk("ok", kind="rink")), _btn(f"Коробки ({boxes})", mk("ok", kind="hockey_box"))]
        if exact and exact != total:
            sub.append(_btn(f"С точным адресом ({exact})", mk("ok", precision="map")))
        if sub:
            rows.append(sub)
        rows.append([_btn(f"Скрыть все ({total})", mk("hide"))])
    if cands:
        rows.append([_btn(f"Кандидаты из OSM ({cands}): подтвердить", mk("ok", scope="candidates")),
                     _btn("Скрыть", mk("hide", scope="candidates"))])
    rows.append([_btn("К городам", "wa:cities")])
    body = (f"<b>{_esc(name)}</b>\nЖдут подтверждения: {total} (катков {rinks}, коробок {boxes}).\n"
            + (f"Кандидатов из OSM без названия: {cands}.\n" if cands else "")
            + "«Подтвердить» оставляет точку в сезоне и статус льда не трогает.")
    await _show(query, body, _kb(*rows))
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:p:"))
async def on_preview(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    _, _, act, code = (query.data or "").split(":", 3)
    if act not in ("ok", "hide"):
        await query.answer()
        return
    sel = sel_from_code(code)
    async with async_session_factory() as session:
        ids = await wa.select_ids(session, sel, ws.current_season(_now()))
        name = await _city_name(session, sel.city_id)
    if not ids:
        await query.answer("Тут уже всё разобрано", show_alert=True)
        return
    verb = "Подтвердить на сезон" if act == "ok" else "Скрыть"
    tail = ("Статус льда не меняется." if act == "ok"
            else "Скрытые пропадут из списка и карты. Подписки останутся. Можно отменить 10 минут.")
    body = f"<b>{verb}?</b>\n{_esc(describe_selection(sel, name))}: <b>{len(ids)}</b> точек.\n{tail}"
    kb = _kb(
        [_btn(f"Да, {verb.lower()} ({len(ids)})", f"wa:g:{act}:{code}:{len(ids)}")],
        [_btn("Назад", f"wa:c:{sel.city_id}" if sel.city_id else "wa:cities")],
    )
    await _show(query, body, kb)
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:g:"))
async def on_apply(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    _, _, act, code = (query.data or "").split(":", 3)
    code, _, n = code.rpartition(":")
    sel = sel_from_code(code)
    async with async_session_factory() as session:
        try:
            res = await wa.apply_batch(
                session, wa.CONFIRM if act == "ok" else wa.HIDE, sel, admin_id=query.from_user.id, now=_now(),
                expect_count=int(n),
            )
        except wa.AdminOpError as exc:
            await session.rollback()
            if exc.code == "stale":
                await query.answer(f"Список изменился (теперь {exc.detail}). Откройте экран заново.", show_alert=True)
                return
            raise
        await session.commit()
    if not res.count:
        await query.answer("Уже разобрано", show_alert=True)
        return
    done = "подтверждено на сезон" if act == "ok" else "скрыто"
    await _show(
        query, f"Готово: {done} {res.count}.",
        _kb([_btn("Отменить (10 минут)", f"wa:u:{res.batch_id}")], [_btn("Дальше", "wa:home")]),
    )
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:u:"))
async def on_undo(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    batch_id = int((query.data or "").split(":")[2])
    async with async_session_factory() as session:
        out = await wa.undo_batch(session, batch_id, now=_now())
        await session.commit()
    status = out["status"]
    if status == "ok":
        extra = f" Не вернул {out['skipped']}: их уже меняли." if out.get("skipped") else ""
        await _show(query, f"Отменено: возвращено {out['restored']}.{extra}", _kb([_btn("Дальше", "wa:home")]))
        await query.answer()
        return
    await query.answer({"already": "Уже отменено", "expired": "Прошло больше 10 минут",
                        "not_undoable": "Это действие не отменяется", "not_found": "Не нашёл пачку"}.get(status, status), show_alert=True)


# --- очередь по приоритету -----------------------------------------------------------------
async def _send_photo_card(query: CallbackQuery, photo_id: int) -> None:
    chat = query.message.chat.id if query.message else query.from_user.id
    await winter_bot.notify_admins_photo(photo_id, chats=[chat])


@ops_router.callback_query(F.data == "wa:q")
async def on_queue(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    from sqlalchemy import text

    async with async_session_factory() as session:
        items = await wq.next_items(session, 1)
        if not items:
            body, kb = await _home(session)
            await _show(query, "Очередь пуста.\n\n" + body, kb)
            await query.answer()
            return
        it = items[0]
        total = int((await session.execute(text("SELECT count(*) FROM seasonal_moderation_items WHERE status='open'"))).scalar_one())
        season = ws.current_season(_now())
        row = (await session.execute(
            text("""SELECT a.address, sr.geocode_precision AS prec, s.dispute FROM arenas a
                    LEFT JOIN seasonal_rinks sr ON sr.arena_id=a.id
                    LEFT JOIN seasonal_rink_seasons s ON s.arena_id=a.id AND s.season=:s WHERE a.id=:a"""),
            {"s": season, "a": it["arena_id"] or 0})).first()
    nxt = [_btn(f"Следующая (осталось {total - 1})", "wa:q")] if total > 1 else []
    where = f"{_esc(it['city'])}, {_esc(it['name'])}" + (f"\n{_esc(row.address)}" if row and row.address else "")
    aid = it["arena_id"]
    if it["kind"] == "dispute" and row is not None and row.dispute:
        body = f"<b>Спор по льду</b>\n{where}\nЛюди отмечают по-разному. Статус пока не менял. Что ставим?"
        kb = _kb([_btn("Залит", f"wa:d:{aid}:f"), _btn("Ждём заливку", f"wa:d:{aid}:w")], nxt)
    elif it["kind"] in ("dispute", "gone"):
        title = "Спор: «точки нет» при живом льде" if it["kind"] == "dispute" else "Возможно, точки больше нет"
        body = f"<b>{title}</b>\n{where}\nТри человека написали, что точки нет. Точка сейчас показана серой."
        kb = _kb(*winter_bot.gone_keyboard(aid).inline_keyboard, nxt)
    elif it["kind"] == "photo_first":
        await _send_photo_card(query, int(it["ref_id"]))
        await query.answer("Фото выше. Кнопки под ним.")
        if nxt:
            await query.message.answer("Когда решите — следующая запись.", reply_markup=_kb(nxt))  # type: ignore[union-attr]
        return
    else:
        body = (f"<b>Новая точка</b>\n{where}\nТочность адреса: {_esc(row.prec if row else '—')}. "
                "Скрыта, пока вы не подтвердите.")
        kb = _kb([_btn("Подтвердить", f"wa:n:ok:{aid}"), _btn("Скрыть", f"wa:n:hide:{aid}")], nxt)
    await _show(query, body, kb)
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:d:"))
async def on_dispute(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    _, _, aid, code = (query.data or "").split(":")
    state = {"f": "flooded", "w": "waiting"}.get(code)
    if state is None:
        await query.answer()
        return
    async with async_session_factory() as session:
        ok = await wa.resolve_dispute(session, int(aid), state, admin_id=query.from_user.id, now=_now())
        await session.commit()
    await _show(query, "Готово. Статус поставлен вами и держится 7 суток." if ok else "Точки уже нет в сезоне.", _kb([_btn("Следующая", "wa:q")]))
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:n:"))
async def on_new_point(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    _, _, act, aid = (query.data or "").split(":")
    season = ws.current_season(_now())
    async with async_session_factory() as session:
        res = await wa.set_visibility(
            session, wa.CONFIRM if act == "ok" else wa.HIDE, [int(aid)], season, admin_id=query.from_user.id, now=_now(),
            selection={"arena_id": int(aid), "source": "queue"},
        )
        await session.commit()
    await _show(query, "Подтверждена." if act == "ok" else "Скрыта.",
                _kb([_btn("Отменить", f"wa:u:{res.batch_id}"), _btn("Следующая", "wa:q")]))
    await query.answer()


# --- дубли и слияние -----------------------------------------------------------------------
@ops_router.callback_query(F.data.startswith("wa:dups:"))
async def on_dups(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    index = int((query.data or "").split(":")[2])
    async with async_session_factory() as session:
        groups = await wa.find_duplicate_groups(session, _now())
    if not groups:
        await _show(query, "Дублей не нашёл: адреса, названия и точки на карте не совпадают.", _kb([_btn("Назад", "wa:home")]))
        await query.answer()
        return
    index = min(index, len(groups) - 1)
    g = groups[index]
    await _show(query, dup_text(g, index, len(groups)), dup_keyboard(g, index, len(groups)))
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:m:"))
async def on_merge_ask(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    _, _, src, dst = (query.data or "").split(":")
    async with async_session_factory() as session:
        pv = await wa.merge_preview(session, int(src), int(dst))
    body = (f"<b>Влить дубль?</b>\n#{src} {_esc(pv['s_name'])} → #{dst} {_esc(pv['t_name'])}\n"
            f"Переедут: отметок {pv['marks']}, фото {pv['photos']}, колокольчиков {pv['subs']}, снимков галереи {pv['media']}.\n"
            "Старый адрес страницы будет вести на оставшуюся точку (301). <b>Отменить нельзя.</b>")
    await _show(query, body, _kb([_btn("Да, влить", f"wa:my:{src}:{dst}")], [_btn("Нет", "wa:dups:0")]))
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:my:"))
async def on_merge_do(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    _, _, src, dst = (query.data or "").split(":")
    async with async_session_factory() as session:
        try:
            stats = await wa.merge_points(session, int(src), int(dst), admin_id=query.from_user.id, now=_now())
        except wa.AdminOpError as exc:
            await session.rollback()
            msg = {"already_merged": "Эта точка уже влита", "other_city": "Точки из разных городов не сливаю",
                   "target_inactive": "Оставляемая точка уже неактивна", "not_found": "Не нашёл точку"}.get(exc.code, exc.code)
            await query.answer(msg, show_alert=True)
            return
        await session.commit()
    await _show(
        query,
        f"Влито. Переехало: отметок {stats['marks']}, фото {stats['photos']}, колокольчиков {stats['subs']}"
        f" (повторных убрано {stats['subs_deduped']}). Старый адрес отвечает 301.",
        _kb([_btn("Другие дубли", "wa:dups:0")], [_btn("Назад", "wa:home")]),
    )
    await query.answer()


# --- сверка с таблицей нового сезона ------------------------------------------------------------
async def _load_run(session, run_id: int) -> dict[str, Any] | None:
    from sqlalchemy import text

    row = (await session.execute(
        text("SELECT id, season, label, status, error, diff, applied_parts FROM winter_import_runs WHERE id=:i"), {"i": run_id})).mappings().first()
    return dict(row) if row else None


@ops_router.callback_query(F.data == "wa:runs")
async def on_runs(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    async with async_session_factory() as session:
        runs = await wd.pending_runs(session)
    if not runs:
        await _show(query, "Сверок в ожидании нет. Пришлите CSV с подписью /winter_import.", _kb([_btn("Назад", "wa:home")]))
    else:
        rows = [[_btn(f"#{r['id']} {r['label'] or 'таблица'}", f"wa:r:{r['id']}")] for r in runs[:10]]
        await _show(query, "<b>Сверки в ожидании</b>", _kb(*rows, [_btn("Назад", "wa:home")]))
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:r:"))
async def on_run(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    async with async_session_factory() as session:
        run = await _load_run(session, int((query.data or "").split(":")[2]))
    if run is None:
        await query.answer("Не нашёл сверку", show_alert=True)
        return
    await _show(query, run_text(run), run_keyboard(run))
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:ra:"))
async def on_run_apply(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    _, _, rid, part = (query.data or "").split(":")
    async with async_session_factory() as session:
        try:
            out = await wd.apply_run(session, int(rid), [part], admin_id=query.from_user.id, now=_now())
        except wd.DiffError as exc:
            await session.rollback()
            await query.answer("Эта часть уже применена или сверка закрыта" if exc.code in ("nothing_to_apply", "not_pending") else exc.code, show_alert=True)
            return
        await session.commit()
        run = await _load_run(session, int(rid))
    res = out.get(part) or {}
    summary = {
        "new": f"Создано новых точек: {res.get('created', 0)} (ждут подтверждения на сезон).",
        "changed": f"Обновлено точек: {res.get('count', 0)}.",
        "missing": f"Скрыто: {res.get('hidden', 0)}, оставлено (живой лёд или недавно подтверждены): {res.get('kept', 0)}.",
        "same": f"Объединено с прошлой таблицей: {res.get('count', 0)}.",
    }[part]
    batch = res.get("batch_id")
    undo = [_btn("Отменить (10 минут)", f"wa:u:{batch}")] if batch else []
    nav = [_btn("К сверке", f"wa:r:{rid}")] if run and run["status"] == "pending" else [_btn("Назад", "wa:home")]
    await _show(query, summary, _kb(undo, nav))
    await query.answer()


@ops_router.callback_query(F.data.startswith("wa:rr:"))
async def on_run_reject(query: CallbackQuery) -> None:
    if not await _is_admin_query(query):
        return
    async with async_session_factory() as session:
        ok = await wd.reject_run(session, int((query.data or "").split(":")[2]), now=_now())
        await session.commit()
    await _show(query, "Сверка отклонена, ничего не изменено." if ok else "Сверка уже закрыта.", _kb([_btn("Назад", "wa:home")]))
    await query.answer()


@ops_router.message(Command("winter_import"))
async def cmd_import(message: Message) -> None:
    if not message.from_user or not winter_bot._is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    _awaiting_import.add(message.from_user.id)
    await message.answer("Пришлите CSV с таблицей нового сезона (те же колонки, что у seed). Я покажу дифф и ничего не применю без вашей кнопки.")


def _import_file(message: Message) -> bool:
    if not message.from_user or not message.document or not winter_bot._is_admin(message.from_user.id):
        return False
    caption = (message.caption or "").strip().lower()
    return message.from_user.id in _awaiting_import or caption.startswith("/winter_import")


@ops_router.message(F.document, _import_file)
async def on_import_file(message: Message, bot: Bot) -> None:
    assert message.from_user and message.document
    _awaiting_import.discard(message.from_user.id)
    if (message.document.file_size or 0) > MAX_FILE_BYTES:
        await message.answer("Файл больше 2 МБ, это не похоже на таблицу точек.")
        return
    buf = await bot.download(message.document.file_id)
    data = buf.read() if buf else b""
    try:
        rows = wd.parse_csv(data)
    except wd.DiffError as exc:
        await message.answer(
            "Не разобрал файл: " + ("нет колонок city и address/name." if exc.code == "no_columns" else "нужен CSV в UTF-8.")
            + " Ничего не изменено."
        )
        return
    now = _now()
    async with async_session_factory() as session:
        res = await wd.create_run(
            session, rows, season=ws.current_season(now), label=(message.document.file_name or "таблица")[:128],
            admin_id=message.from_user.id, now=now, file_bytes=data,
        )
        await session.commit()
        run = await _load_run(session, res.run_id)
    assert run is not None
    prefix = "Этот файл уже загружали.\n\n" if res.duplicate else ""
    await message.answer(prefix + run_text(run), reply_markup=run_keyboard(run))
