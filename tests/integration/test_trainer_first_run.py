"""
Онбординг v2, первый вход: что продукт делает за тренера, ничего не спрашивая.

Два обещания под тестом:
  * имя берётся из Telegram — тренер его не печатает;
  * «первый запуск» определяется наличием недели в расписании, а не статусом модерации.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.application.trainer_quick_setup_use_cases import (
    seed_trainer_identity_from_telegram,
    trainer_has_weekly_template,
)


async def _new_trainer(db_session) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
    )
    tid = int(r.fetchone()[0])
    await db_session.commit()
    return tid


async def _profile_name(db_session, trainer_id: int) -> tuple[str | None, str | None]:
    r = await db_session.execute(
        text("SELECT first_name, last_name FROM trainer_profiles WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    row = r.fetchone()
    return (row[0], row[1]) if row else (None, None)


@pytest.mark.asyncio
async def test_name_comes_from_telegram_without_asking(app_use_test_db, db_session) -> None:
    tid = await _new_trainer(db_session)

    wrote = await seed_trainer_identity_from_telegram(
        db_session, tid, first_name="Максим", last_name="Тренер"
    )

    assert wrote is True
    assert await _profile_name(db_session, tid) == ("Максим", "Тренер")


@pytest.mark.asyncio
async def test_a_name_the_trainer_typed_is_never_replaced(app_use_test_db, db_session) -> None:
    """Telegram-имя — заготовка, а не источник правды: своё написанное имя главнее."""
    tid = await _new_trainer(db_session)
    await db_session.execute(
        text("INSERT INTO trainer_profiles (trainer_id, first_name, last_name) VALUES (:t, 'Анна', 'Петрова')"),
        {"t": tid},
    )
    await db_session.commit()

    await seed_trainer_identity_from_telegram(
        db_session, tid, first_name="Максим", last_name="Тренер"
    )

    assert await _profile_name(db_session, tid) == ("Анна", "Петрова")


@pytest.mark.asyncio
async def test_missing_last_name_is_filled_without_touching_the_first(app_use_test_db, db_session) -> None:
    """В Telegram фамилии может не быть вовсе — заполняем то, что есть, и не портим остальное."""
    tid = await _new_trainer(db_session)
    await db_session.execute(
        text("INSERT INTO trainer_profiles (trainer_id, first_name) VALUES (:t, 'Анна')"),
        {"t": tid},
    )
    await db_session.commit()

    await seed_trainer_identity_from_telegram(
        db_session, tid, first_name="Максим", last_name="Тренер"
    )

    assert await _profile_name(db_session, tid) == ("Анна", "Тренер")


@pytest.mark.asyncio
async def test_empty_telegram_name_writes_nothing(app_use_test_db, db_session) -> None:
    tid = await _new_trainer(db_session)

    wrote = await seed_trainer_identity_from_telegram(db_session, tid, first_name="  ", last_name=None)

    assert wrote is False
    assert await _profile_name(db_session, tid) == (None, None)


@pytest.mark.asyncio
async def test_first_run_is_decided_by_the_schedule_not_by_moderation(
    app_use_test_db, db_session
) -> None:
    """
    Онбординг v2 заменил пять статусов и три уровня полноты профиля одним фактом:
    есть ли у тренера неделя в расписании.
    """
    tid = await _new_trainer(db_session)
    assert await trainer_has_weekly_template(db_session, tid) is False

    # Статус «active» (прошёл модерацию) сам по себе первый запуск не закрывает.
    await db_session.execute(text("UPDATE trainers SET status='active' WHERE id = :t"), {"t": tid})
    await db_session.commit()
    assert await trainer_has_weekly_template(db_session, tid) is False

    await db_session.execute(
        text(
            "INSERT INTO trainer_schedule_templates (trainer_id, day_of_week, start_time, duration_minutes) "
            "VALUES (:t, 1, '07:00', 60)"
        ),
        {"t": tid},
    )
    await db_session.commit()
    assert await trainer_has_weekly_template(db_session, tid) is True


class _FakeSize:
    def __init__(self, file_id: str) -> None:
        self.file_id = file_id


class _FakePhotos:
    def __init__(self, photos) -> None:
        self.photos = photos


class _FakeFile:
    file_path = "photos/file_1.jpg"


class _FakeBot:
    """Минимальный аиограм-подобный бот: три вызова, которые делает сид аватара."""

    def __init__(self, photos, body: bytes = b"") -> None:
        self._photos = photos
        self._body = body

    async def get_user_profile_photos(self, user_id: int, limit: int = 1):
        return _FakePhotos(self._photos)

    async def get_file(self, file_id: str):
        return _FakeFile()

    async def download_file(self, path: str):
        import io

        return io.BytesIO(self._body)


class _ExplodingBot:
    async def get_user_profile_photos(self, user_id: int, limit: int = 1):
        raise RuntimeError("telegram is down")


@pytest.mark.asyncio
async def test_avatar_seed_is_silent_when_trainer_has_no_telegram_photo(
    app_use_test_db, db_session
) -> None:
    from src.application.trainer_quick_setup_use_cases import seed_trainer_photo_from_telegram

    tid = await _new_trainer(db_session)
    assert await seed_trainer_photo_from_telegram(_FakeBot([]), db_session, tid, 12345) is False


@pytest.mark.asyncio
async def test_avatar_seed_never_breaks_start_when_telegram_fails(
    app_use_test_db, db_session
) -> None:
    """
    Главное свойство: этот код выполняется внутри /start. Любая ошибка Telegram, S3 или сети
    должна остаться в логе, а не превратиться в сломанное первое сообщение тренеру.
    """
    from src.application.trainer_quick_setup_use_cases import seed_trainer_photo_from_telegram

    tid = await _new_trainer(db_session)
    assert await seed_trainer_photo_from_telegram(_ExplodingBot(), db_session, tid, 12345) is False


@pytest.mark.asyncio
async def test_avatar_seed_skips_when_a_photo_already_exists(app_use_test_db, db_session) -> None:
    """Загруженное тренером фото главнее аватара из Telegram и не перезаписывается."""
    from src.application.trainer_quick_setup_use_cases import seed_trainer_photo_from_telegram

    tid = await _new_trainer(db_session)
    await db_session.execute(
        text("INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:t, 'own.jpg', 0)"),
        {"t": tid},
    )
    await db_session.commit()

    called = {"n": 0}

    class _CountingBot(_FakeBot):
        async def get_user_profile_photos(self, user_id: int, limit: int = 1):
            called["n"] += 1
            return _FakePhotos([[_FakeSize("f1")]])

    assert await seed_trainer_photo_from_telegram(_CountingBot([]), db_session, tid, 12345) is False
    assert called["n"] == 0, "не должны даже спрашивать Telegram, если фото уже есть"
