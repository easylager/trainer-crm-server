"""
Каталог как один механизм: полный жизненный цикл карточки через реальные входы (TASK-140).

Отдельные тесты уже проверяют куски: публичный гейт (``test_public_catalog_state_gate``),
экран (``test_webapp_trainer_catalog``), переходы (``test_trainer_catalog_state``). Чего не
было — прохода по всему пути целиком, и именно на стыках ломалось: модерация ветвилась по
статусу аккаунта, а не по состоянию карточки, и тренер застревал с экраном, который врал.

Поэтому здесь на каждой остановке проверяются четыре вещи разом, потому что расходиться они
могут только попарно:

1. **состояние** — что в колонке;
2. **экран** — что тренер читает и какие кнопки ему доступны;
3. **журнал** — появилась ли запись с автором (ни один переход не молчит);
4. **выдача** — видят ли тренера клиенты.

Плюс пятое, сквозное: за переход, которого тренер не просил, ему должен прийти пуш.
"""
from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.trainer_catalog_state import (
    CATALOG_ACTOR_MODERATOR,
    REASON_MODERATOR_APPROVED,
    set_catalog_state,
)
from src.application.trainer_use_cases import (
    apply_moderator_revision_request,
    create_trainer,
    update_trainer_profile,
    update_trainer_status,
)
from src.infrastructure.db.models import TRAINER_STATUS_ACTIVE, TRAINER_STATUS_DEACTIVATED
from src.shared.catalog_visibility import (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_NEEDS_REVISION,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
)
from tests.api.test_webapp_client_miniapp_integration import _require_seed_ids
from tests.api.test_webapp_trainer_miniapp_profile_integration import (
    _fresh_trainer_telegram_id,
    patch_trainer_init_auth,
)

HEADERS = {"X-Telegram-Init-Data": "mock"}


@pytest.fixture
def pushes(monkeypatch) -> list[str]:
    """Собирает тексты пушей вместо отправки в Telegram."""
    sent: list[str] = []

    async def fake_send(session, trainer_id: int, html_body: str) -> bool:
        sent.append(html_body)
        return True

    monkeypatch.setattr("src.application.trainer_catalog_notify._send", fake_send)
    return sent


@pytest.fixture
def admin_pings(monkeypatch) -> list[int]:
    """Пинги админам об очереди модерации — без реального бота."""
    pinged: list[int] = []

    async def fake_notify(trainer_id: int) -> None:
        pinged.append(int(trainer_id))

    monkeypatch.setattr(
        "src.application.trainer_use_cases.notify_admins_trainer_queued_for_moderation",
        fake_notify,
    )
    return pinged


async def _new_trainer(db_session) -> tuple[int, int, int]:
    """Тренер с картой, проходящей submission-планку. Возвращает (trainer_id, telegram_id, arena_id)."""
    sid, cid, aid = await _require_seed_ids(db_session)
    if aid is None:
        pytest.skip("need a seeded arena")
    tid = await create_trainer(
        db_session,
        profile={
            "first_name": "Цикл",
            "last_name": "Проверкин",
            "phone": "+375291230011",
            "city_id": cid,
            "description": "d" * 40,
            "education": "Высшее",
            "experience_years": 5,
            "session_duration_minutes": 60,
            "min_hours_before_booking": 3,
        },
        service_ids=[sid],
        arena_ids=[aid],
    )
    await db_session.execute(
        text("INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:t, :fk, 0)"),
        {"t": tid, "fk": f"trainers/{tid}/a.jpg"},
    )
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :t"), {"tg": tg, "t": tid}
    )
    await db_session.commit()
    return tid, tg, int(aid)


async def _screen(tg: int) -> dict[str, Any]:
    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/webapp/trainer/catalog", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _act(tg: int, path: str) -> tuple[int, dict]:
    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/api/webapp/trainer/catalog/{path}", headers=HEADERS)
    try:
        return resp.status_code, resp.json()
    except Exception:  # noqa: BLE001
        return resp.status_code, {}


async def _listed_publicly(trainer_id: int) -> bool:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/public/trainers/{trainer_id}")
    return resp.status_code == 200


async def _assert_stop(
    tid: int,
    tg: int,
    *,
    state: str,
    actions: list[str],
    public: bool,
    journal_actor: str | None,
) -> dict[str, Any]:
    """Одна остановка маршрута: колонка, экран, журнал и выдача обязаны говорить одно и то же."""
    screen = await _screen(tg)
    assert screen["state"] == state, f"состояние: ждали {state}, получили {screen['state']}"
    assert screen["actions"] == actions, f"кнопки в {state}: {screen['actions']}"
    # Экран никогда не молчит: у каждого состояния есть заголовок и фраза.
    assert screen["headline"], f"нет заголовка в состоянии {state}"
    assert screen["body"], f"нет объяснения в состоянии {state}"
    assert await _listed_publicly(tid) is public, f"публичная выдача разошлась в {state}"
    if journal_actor is not None:
        latest = screen["events"][0]
        assert latest["to_state"] == state, f"журнал отстал: {latest}"
        assert latest["actor_type"] == journal_actor, f"автор перехода: {latest['actor_type']}"
        assert latest["headline"], "строка журнала без текста"
    return screen


async def _approve_as_moderator(db_session, tid: int) -> None:
    """То, что делает админ-бот кнопкой «Одобрить»."""
    await update_trainer_status(db_session, tid, TRAINER_STATUS_ACTIVE)
    await set_catalog_state(
        db_session,
        tid,
        CATALOG_STATE_PUBLISHED,
        reason=REASON_MODERATOR_APPROVED,
        actor_type=CATALOG_ACTOR_MODERATOR,
        actor_id=1,
        notify=False,
    )


@pytest.mark.asyncio
async def test_the_happy_path_end_to_end(app_use_test_db, db_session, admin_pings) -> None:
    """draft → опубликован в один тап (publish-first) → снят → возвращён. Каждый шаг виден и обратим."""
    tid, tg, _ = await _new_trainer(db_session)

    await _assert_stop(
        tid, tg, state=CATALOG_STATE_DRAFT, actions=["submit"], public=False, journal_actor=None
    )

    assert (await _act(tg, "submit"))[0] == 200
    # Publish-first: очереди перед публикацией нет — карточка сразу в каталоге,
    # админы получают её на пост-проверку тем же одним пингом.
    await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_PUBLISHED,
        actions=["hide"],
        public=True,
        journal_actor="trainer",
    )
    assert admin_pings == [tid], "админов обязаны позвать ровно один раз"

    assert (await _act(tg, "hide"))[0] == 200
    await _assert_stop(
        tid, tg, state=CATALOG_STATE_HIDDEN, actions=["restore"], public=False, journal_actor="trainer"
    )

    # Обещание диалога снятия: вернуть можно в один тап, без повторной проверки.
    assert (await _act(tg, "restore"))[0] == 200
    await _assert_stop(
        tid, tg, state=CATALOG_STATE_PUBLISHED, actions=["hide"], public=True, journal_actor="trainer"
    )


@pytest.mark.asyncio
async def test_withdrawing_a_request_returns_to_draft_and_can_be_repeated(
    app_use_test_db, db_session, admin_pings
) -> None:
    """Отозвал заявку — вернулся в draft, и отправить снова можно: отметка в очереди снята.

    pending_review — легаси-состояние (там остались подавшие до publish-first); в очередь
    карточку ставим напрямую, потому что submit теперь публикует сразу.
    """
    tid, tg, _ = await _new_trainer(db_session)
    await db_session.execute(
        text(
            "UPDATE trainers SET catalog_state = 'pending_review', "
            "moderation_submitted_at = now() WHERE id = :t"
        ),
        {"t": tid},
    )
    await db_session.commit()
    assert (await _act(tg, "withdraw"))[0] == 200
    await _assert_stop(
        tid, tg, state=CATALOG_STATE_DRAFT, actions=["submit"], public=False, journal_actor="trainer"
    )

    admin_pings.clear()
    assert (await _act(tg, "submit"))[0] == 200
    assert admin_pings == [tid], "новая отправка обязана снова позвать админов (пост-проверка)"


@pytest.mark.asyncio
async def test_a_broken_profile_pauses_the_card_and_fixing_it_brings_the_card_back(
    app_use_test_db, db_session, pushes
) -> None:
    """
    Задача ради этого и писалась: стёртый телефон уводил из выдачи молча, с одной строкой в логе.
    """
    tid, tg, _ = await _new_trainer(db_session)
    assert (await _act(tg, "submit"))[0] == 200
    await _approve_as_moderator(db_session, tid)
    pushes.clear()

    # Телефон каталогу не нужен (см. отдельный тест ниже): дыру делает город.
    city_id = (
        await db_session.execute(
            text("SELECT city_id FROM trainer_profiles WHERE trainer_id = :t"), {"t": tid}
        )
    ).scalar_one()
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = NULL WHERE trainer_id = :t"), {"t": tid}
    )
    await db_session.commit()
    await update_trainer_profile(db_session, tid, profile={"contacts": "@coach"})
    screen = await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_PAUSED,
        actions=["restore"],
        public=False,
        journal_actor="system",
    )
    # Причина названа полем, а не кодом, и теми же словами, что и в анкете.
    assert "город" in (screen["state_detail"] or "").lower()
    assert pushes, "выпадение из каталога обязано прийти пушем"
    assert "каталог" in pushes[-1].lower()

    # Пока дыра открыта, «вернуть» — не отказ, а следующий шаг: 422 с полями для карусели.
    status, body = await _act(tg, "restore")
    assert status == 422
    assert "city" in (body["detail"].get("missing_fields") or [])

    pushes.clear()
    await update_trainer_profile(db_session, tid, profile={"city_id": city_id})
    await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_PUBLISHED,
        actions=["hide"],
        public=True,
        journal_actor="system",
    )
    assert pushes, "автовозврат в каталог обязан прийти пушем"


@pytest.mark.asyncio
async def test_moderator_revision_round_trip_from_any_account_status(
    app_use_test_db, db_session, admin_pings
) -> None:
    """
    «Нужны правки» → исправил → отправил снова. Проверяется для уже активного аккаунта — именно
    там ветка по ``status`` оставляла карточку в ``pending_review`` навсегда.
    """
    tid, tg, _ = await _new_trainer(db_session)
    assert (await _act(tg, "submit"))[0] == 200
    await _approve_as_moderator(db_session, tid)
    assert (await _act(tg, "hide"))[0] == 200
    assert (await _act(tg, "restore"))[0] == 200
    # Аккаунт активен, карточка стоит в очереди — легаси-комбинация из жизни.
    await db_session.execute(
        text("UPDATE trainers SET catalog_state = 'pending_review' WHERE id = :t"), {"t": tid}
    )
    await db_session.commit()

    state = await apply_moderator_revision_request(
        db_session, tid, feedback="Добавьте цены", moderator_id=7
    )
    assert state == CATALOG_STATE_NEEDS_REVISION
    screen = await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_NEEDS_REVISION,
        # До реальной правки «отправить снова» нет: иначе один тап переиздал бы ту же карточку
        # и стёр бы комментарий модератора.
        actions=["edit"],
        public=False,
        journal_actor="moderator",
    )
    assert screen["state_detail"] == "Добавьте цены"
    # Активацию правки по витрине не отменяют.
    status_row = await db_session.execute(
        text("SELECT status FROM trainers WHERE id = :t"), {"t": tid}
    )
    assert status_row.scalar() == TRAINER_STATUS_ACTIVE

    # Переотправка без правок — отказ, и комментарий модератора на месте.
    admin_pings.clear()
    status_code, body = await _act(tg, "submit")
    assert status_code == 409, body
    fb = await db_session.execute(
        text("SELECT moderation_feedback FROM trainers WHERE id = :t"), {"t": tid}
    )
    assert fb.scalar() == "Добавьте цены"
    assert admin_pings == []

    # Реальная правка (у активного тренера текст уходит в profile_pending и перештамповывает
    # отметку) — и «отправить снова» возвращается.
    await update_trainer_profile(
        db_session, tid, profile={"description": "Исправленное описание " + "d" * 20}
    )
    await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_NEEDS_REVISION,
        actions=["edit", "submit"],
        public=False,
        journal_actor="moderator",
    )

    admin_pings.clear()
    assert (await _act(tg, "submit"))[0] == 200
    # Publish-first: исправленная карточка публикуется сразу, админы зовутся на пост-проверку.
    await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_PUBLISHED,
        actions=["hide"],
        public=True,
        journal_actor="trainer",
    )
    assert admin_pings == [tid]
    # Отработанный комментарий снят — иначе хаб продолжал бы просить правки.
    fb = await db_session.execute(
        text("SELECT moderation_feedback FROM trainers WHERE id = :t"), {"t": tid}
    )
    assert (fb.scalar() or "") == ""


@pytest.mark.asyncio
async def test_deactivating_the_account_takes_the_card_with_it(
    app_use_test_db, db_session
) -> None:
    """Карточка не переживает аккаунт, которому принадлежит."""
    tid, tg, _ = await _new_trainer(db_session)
    assert (await _act(tg, "submit"))[0] == 200
    await _approve_as_moderator(db_session, tid)
    assert await _listed_publicly(tid) is True

    await update_trainer_status(db_session, tid, TRAINER_STATUS_DEACTIVATED)
    screen = await _screen(tg)
    assert screen["state"] == CATALOG_STATE_DRAFT
    assert await _listed_publicly(tid) is False
    assert screen["events"][0]["actor_type"] == "system"


@pytest.mark.asyncio
async def test_every_state_the_trainer_can_reach_says_what_to_do_next(
    app_use_test_db, db_session
) -> None:
    """
    Сквозное свойство: ни в одном состоянии экран не оставляет тренера без ответа «что дальше».

    ``pending_review`` тоже даёт действие: publish-first сделал очередь легаси-состоянием, и
    тап по «Отправить себя в каталог» публикует застрявшую в ней карточку сразу.
    """
    tid, tg, _ = await _new_trainer(db_session)
    for state in (
        CATALOG_STATE_DRAFT,
        CATALOG_STATE_PENDING_REVIEW,
        CATALOG_STATE_PUBLISHED,
        CATALOG_STATE_HIDDEN,
        CATALOG_STATE_PAUSED,
        CATALOG_STATE_NEEDS_REVISION,
    ):
        await db_session.execute(
            text("UPDATE trainers SET catalog_state = :s WHERE id = :t"), {"s": state, "t": tid}
        )
        await db_session.commit()
        screen = await _screen(tg)
        assert screen["headline"], state
        assert screen["body"], state
        assert screen["actions"], f"{state}: тренеру нечего нажать"
        assert screen["preview"]["first_name"], state


@pytest.mark.asyncio
async def test_a_card_can_break_while_it_waits_in_the_queue(
    app_use_test_db, db_session, admin_pings, pushes
) -> None:
    """
    Тренер правит анкету, пока карточка стоит в очереди, и ломает обязательное поле.

    Ребра ``pending_review → paused`` в машине не было, хотя ``reconcile_catalog_state_for_card``
    делает именно его: сохранение профиля падало с CatalogStateTransitionError. Одобрять карточку
    с дырой нельзя, так что состояние правильное — не хватало только разрешения.
    """
    tid, tg, _ = await _new_trainer(db_session)
    assert (await _act(tg, "submit"))[0] == 200
    pushes.clear()

    # Телефон каталогу не нужен (см. отдельный тест ниже): дыру делает город.
    city_id = (
        await db_session.execute(
            text("SELECT city_id FROM trainer_profiles WHERE trainer_id = :t"), {"t": tid}
        )
    ).scalar_one()
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = NULL WHERE trainer_id = :t"), {"t": tid}
    )
    await db_session.commit()
    await update_trainer_profile(db_session, tid, profile={"contacts": "@coach"})
    screen = await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_PAUSED,
        actions=["restore"],
        public=False,
        journal_actor="system",
    )
    assert "город" in (screen["state_detail"] or "").lower()
    assert pushes, "выпадение из очереди обязано прийти пушем"

    # Дорога назад та же, что у любой приостановленной карточки: починил дыру — вернулась сама.
    admin_pings.clear()
    await update_trainer_profile(db_session, tid, profile={"city_id": city_id})
    await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_PUBLISHED,
        actions=["hide"],
        public=True,
        journal_actor="system",
    )


@pytest.mark.asyncio
async def test_moderator_feedback_never_overrides_a_state_it_does_not_own(
    app_use_test_db, db_session
) -> None:
    """
    «Нужны правки» по карточке, которой нет в очереди: комментарий сохраняется, состояние — нет.

    Условие было «тренер вообще просился в каталог», а под него подходят и ``hidden``, и
    ``paused``: оба перехода машина запрещает, так что модератор ронял обработчик вместо того,
    чтобы оставить комментарий. По смыслу тоже неверно — ``hidden`` это решение тренера снять
    карточку, а у ``paused`` уже есть своя причина, которую «нужны правки» затёрли бы.
    """
    for state in (CATALOG_STATE_HIDDEN, CATALOG_STATE_PAUSED, CATALOG_STATE_DRAFT):
        tid, tg, _ = await _new_trainer(db_session)
        await db_session.execute(
            text("UPDATE trainers SET catalog_state = :s WHERE id = :t"), {"s": state, "t": tid}
        )
        await db_session.commit()

        result = await apply_moderator_revision_request(
            db_session, tid, feedback="Поправьте фото", moderator_id=7
        )
        assert result == state, f"{state}: состояние не должно было меняться, стало {result}"

        row = await db_session.execute(
            text("SELECT catalog_state, moderation_feedback FROM trainers WHERE id = :t"),
            {"t": tid},
        )
        got_state, got_feedback = row.fetchone()
        assert got_state == state, state
        assert got_feedback == "Поправьте фото", state


@pytest.mark.asyncio
async def test_no_caller_can_attempt_an_edge_the_machine_forbids(
    app_use_test_db, db_session
) -> None:
    """
    Сторож на будущее: каждое ребро, которое продуктовый код реально делает, обязано быть в
    таблице. Список ниже — не гипотезы, а переходы из ``reconcile_catalog_state_for_card``,
    ``apply_moderator_revision_request``, ``try_submit…``, ``set_trainer_catalog_visibility``
    и роутов раздела.
    """
    from src.application.trainer_catalog_state import _ALLOWED_TRANSITIONS

    edges = [
        (CATALOG_STATE_DRAFT, CATALOG_STATE_PENDING_REVIEW),
        (CATALOG_STATE_DRAFT, CATALOG_STATE_PUBLISHED),
        (CATALOG_STATE_PENDING_REVIEW, CATALOG_STATE_PUBLISHED),
        (CATALOG_STATE_PENDING_REVIEW, CATALOG_STATE_NEEDS_REVISION),
        (CATALOG_STATE_PENDING_REVIEW, CATALOG_STATE_PAUSED),
        (CATALOG_STATE_PUBLISHED, CATALOG_STATE_HIDDEN),
        (CATALOG_STATE_PUBLISHED, CATALOG_STATE_PAUSED),
        (CATALOG_STATE_PUBLISHED, CATALOG_STATE_PENDING_REVIEW),
        # «Нужны правки» по опубликованной карточке ещё не активированного аккаунта.
        (CATALOG_STATE_PUBLISHED, CATALOG_STATE_NEEDS_REVISION),
        (CATALOG_STATE_HIDDEN, CATALOG_STATE_PUBLISHED),
        (CATALOG_STATE_PAUSED, CATALOG_STATE_PUBLISHED),
        (CATALOG_STATE_PAUSED, CATALOG_STATE_PENDING_REVIEW),
        (CATALOG_STATE_NEEDS_REVISION, CATALOG_STATE_PENDING_REVIEW),
        # Publish-first: исправленная карточка возвращается сразу.
        (CATALOG_STATE_NEEDS_REVISION, CATALOG_STATE_PUBLISHED),
    ]
    for src, dst in edges:
        assert dst in _ALLOWED_TRANSITIONS.get(src, frozenset()), f"{src} → {dst} вне машины"

    # `→ draft` разрешён из любого состояния (деактивация аккаунта, отзыв заявки) — отдельным
    # правилом в set_catalog_state, поэтому в таблице его нет и быть не должно.
    for src in _ALLOWED_TRANSITIONS:
        assert CATALOG_STATE_DRAFT not in _ALLOWED_TRANSITIONS[src], src


@pytest.mark.asyncio
async def test_erasing_the_phone_does_not_pause_a_published_card(
    app_use_test_db, db_session, pushes
) -> None:
    """Телефон необязателен: стёртый номер не выводит карточку из каталога и не шлёт пуш."""
    tid, tg, _ = await _new_trainer(db_session)
    assert (await _act(tg, "submit"))[0] == 200
    await _approve_as_moderator(db_session, tid)
    pushes.clear()

    await update_trainer_profile(db_session, tid, profile={"phone": ""})
    await _assert_stop(
        tid, tg, state=CATALOG_STATE_PUBLISHED, actions=["hide"], public=True, journal_actor="moderator"
    )
    assert not pushes


@pytest.mark.asyncio
async def test_a_card_stuck_in_the_legacy_queue_publishes_on_one_tap(
    app_use_test_db, db_session, admin_pings
) -> None:
    """
    Прод-тренер из ``pending_review``: очередь до publish-first больше никто не разбирает,
    поэтому тот же один тап «Отправить себя в каталог» публикует застрявшую заявку сразу.
    """
    tid, tg, _ = await _new_trainer(db_session)
    await db_session.execute(
        text(
            "UPDATE trainers SET catalog_state = 'pending_review', "
            "moderation_submitted_at = now() WHERE id = :t"
        ),
        {"t": tid},
    )
    await db_session.commit()

    await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_PENDING_REVIEW,
        actions=["submit", "withdraw"],
        public=False,
        journal_actor=None,
    )

    assert (await _act(tg, "submit"))[0] == 200
    await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_PUBLISHED,
        actions=["hide"],
        public=True,
        journal_actor="trainer",
    )
    assert admin_pings == [tid], "пост-проверка опубликованной карточки обязана позвать админов"


@pytest.mark.asyncio
async def test_revision_on_a_published_card_of_a_not_yet_active_account_unpublishes_it(
    app_use_test_db, db_session, admin_pings
) -> None:
    """
    «Нужны правки» по опубликованной карточке тренера, который ещё не был ``active``
    (publish-first: статус остаётся ``pending_profile``) — карточка уходит в
    ``needs_revision``. Иначе у пост-модерации против такой карточки была бы только
    деактивация аккаунта.
    """
    tid, tg, _ = await _new_trainer(db_session)
    assert (await _act(tg, "submit"))[0] == 200
    screen = await _assert_stop(
        tid, tg, state=CATALOG_STATE_PUBLISHED, actions=["hide"], public=True, journal_actor="trainer"
    )
    assert screen["readiness"]["submit_ready"]

    state = await apply_moderator_revision_request(
        db_session, tid, feedback="Уберите чужой логотип", moderator_id=7
    )
    assert state == CATALOG_STATE_NEEDS_REVISION
    screen = await _assert_stop(
        tid,
        tg,
        state=CATALOG_STATE_NEEDS_REVISION,
        actions=["edit"],
        public=False,
        journal_actor="moderator",
    )
    assert screen["state_detail"] == "Уберите чужой логотип"


@pytest.mark.asyncio
async def test_the_legacy_rest_submit_cannot_override_the_trainers_own_decision(
    app_use_test_db, db_session, admin_pings
) -> None:
    """
    POST /trainers/{id}/submit-for-moderation идёт без ``requested_by_trainer``: он не имеет
    права публиковать из состояний, где лежит решение самого тренера — ``hidden`` (снял сам),
    ``paused`` (дыру чинит reconcile), ``needs_revision`` (ждёт правку).
    """
    from src.application.trainer_use_cases import try_submit_trainer_for_moderation_review

    for state in (
        CATALOG_STATE_HIDDEN,
        CATALOG_STATE_PAUSED,
        CATALOG_STATE_NEEDS_REVISION,
    ):
        tid, _, _ = await _new_trainer(db_session)
        await db_session.execute(
            text("UPDATE trainers SET catalog_state = :s WHERE id = :t"), {"s": state, "t": tid}
        )
        await db_session.commit()

        result = await try_submit_trainer_for_moderation_review(db_session, tid)
        assert result["ok"] is True, state
        assert result["noop"] is True, state
        assert result["reason"] == "requires_trainer_action", state

        row = (
            await db_session.execute(
                text("SELECT catalog_state, is_catalog_visible FROM trainers WHERE id = :t"),
                {"t": tid},
            )
        ).fetchone()
        assert row[0] == state, f"{state}: сторонний submit не должен был опубликовать карточку"
        assert row[1] is False, state
        assert admin_pings == [], f"{state}: админов не должны звать"
