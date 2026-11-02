"""Админ-бот «Зимой»: экран, пачки, отмена, сверка по файлу (TASK-343)."""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.bot import winter_admin_bot as wab
from src.bot import winter_bot
from tests.application.winter_helpers import make_city, make_point


class _Same:
    def __init__(self, s):
        self.s = s

    async def __aenter__(self):
        return self.s

    async def __aexit__(self, *a):
        return False


class FakeMsg:
    def __init__(self):
        self.shown = []
        self.chat = SimpleNamespace(id=1)

    async def edit_text(self, body, reply_markup=None):
        self.shown.append((body, reply_markup))

    async def answer(self, body, reply_markup=None):
        self.shown.append((body, reply_markup))


class FakeQuery:
    def __init__(self, data, uid=1):
        self.data, self.from_user, self.message, self.alerts = data, SimpleNamespace(id=uid), FakeMsg(), []

    async def answer(self, text_=None, show_alert=False):
        self.alerts.append(text_)


@pytest.fixture
def bot_env(db_session, monkeypatch):
    monkeypatch.setattr(wab, "async_session_factory", lambda: _Same(db_session))
    monkeypatch.setattr(winter_bot, "_is_admin", lambda uid: uid == 1)

    async def _noop():  # тестовая сессия общая: настоящий rollback стёр бы подготовленные данные
        return None

    monkeypatch.setattr(db_session, "rollback", _noop)


def _datas(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.asyncio
async def test_non_admin_is_refused(bot_env):
    q = FakeQuery("wa:cities", uid=2)
    await wab.on_cities(q)
    assert q.alerts == ["Нет доступа"] and not q.message.shown


@pytest.mark.asyncio
async def test_confirm_flow_preview_apply_undo(bot_env, db_session):
    await make_point(db_session, name="A", city="Минск")
    await make_point(db_session, name="B", city="Минск", kind="hockey_box")
    city = await make_city(db_session, "Минск")
    q = FakeQuery(f"wa:c:{city}")
    await wab.on_city(q)
    body, kb = q.message.shown[-1]
    assert "Минск" in body and "Ждут подтверждения: 2" in body
    preview = next(d for d in _datas(kb) if d.startswith("wa:p:ok:"))
    q = FakeQuery(preview)
    await wab.on_preview(q)
    body, kb = q.message.shown[-1]
    assert "<b>2</b>" in body
    go = next(d for d in _datas(kb) if d.startswith("wa:g:"))
    assert go.endswith(":2")
    # список изменился между предпросмотром и кнопкой
    stale = FakeQuery(go.rsplit(":", 1)[0] + ":5")
    await wab.on_apply(stale)
    assert "изменился" in stale.alerts[-1] and not stale.message.shown
    q = FakeQuery(go)
    await wab.on_apply(q)
    body, kb = q.message.shown[-1]
    assert "подтверждено на сезон 2" in body
    undo = next(d for d in _datas(kb) if d.startswith("wa:u:"))
    q = FakeQuery(undo)
    await wab.on_undo(q)
    assert "возвращено 2" in q.message.shown[-1][0]
    again = FakeQuery(undo)
    await wab.on_undo(again)
    assert again.alerts[-1] == "Уже отменено"


@pytest.mark.asyncio
async def test_selection_code_roundtrip_and_callback_limit():
    from src.application.winter_admin import Selection

    sel = Selection(city_id=123456, kind="hockey_box", precision="nomap", scope="candidates")
    assert wab.sel_from_code(wab.sel_to_code(sel)) == sel
    assert len(f"wa:g:hide:{wab.sel_to_code(sel)}:9999".encode()) <= 64


@pytest.mark.asyncio
async def test_import_file_shows_diff_and_applies_only_on_button(bot_env, db_session):
    csv = "city,name,address,type,hours\nНовоград,,ул. Мира 5,каток,9.00-20.00\n".encode()

    class Doc:
        file_id, file_size, file_name = "f", len(csv), "t.csv"

    class Bot:
        async def download(self, fid):
            return io.BytesIO(csv)

    replies = []

    class Msg:
        from_user = SimpleNamespace(id=1)
        document = Doc()
        caption = "/winter_import"

        async def answer(self, body, reply_markup=None):
            replies.append((body, reply_markup))

    assert wab._import_file(Msg())
    await wab.on_import_file(Msg(), Bot())
    body, kb = replies[-1]
    assert "Новые" in body and "Новоград" in body
    assert (await db_session.execute(text("SELECT count(*) FROM seasonal_rinks"))).scalar_one() == 0
    apply = next(d for d in _datas(kb) if d.startswith("wa:ra:") and d.endswith(":new"))
    q = FakeQuery(apply)
    await wab.on_run_apply(q)
    assert "Создано новых точек: 1" in q.message.shown[-1][0]
    assert (await db_session.execute(text("SELECT count(*) FROM seasonal_rinks"))).scalar_one() == 1
