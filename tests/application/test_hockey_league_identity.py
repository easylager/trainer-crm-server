"""TASK-361: лицо лиги «Кто кого» — строка «на что играем», картинка, жалоба и очистка (с базой)."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import text

from src.application import hockey_league_images as images
from src.application import hockey_league_reports as reports
from src.application.hockey_leagues import (
    STAKE_MAX,
    clean_stake,
    create_league,
    extend_league,
    join_by_code,
    player_leagues,
    update_league,
)
from src.application.hockey_leagues import league_preview, set_league_image

OWNER = 880_361_001
MEMBER = 880_361_002
STRANGER = 880_361_003
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr("src.infrastructure.s3._use_local", lambda: True)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))
    return tmp_path


def _jpeg(color=(20, 120, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(out, "JPEG")
    return out.getvalue()


async def _league(db_session, **kwargs):
    league = await create_league(db_session, owner_key=OWNER, owner_name="Саша", name="Двор", now=NOW, **kwargs)
    await join_by_code(db_session, player_key=MEMBER, display_name="Катя", code=league.invite_code)
    return league


# ---------- строка «на что играем» ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   \n\t ", None),
        ("  Пицца   на   всех ", "Пицца на всех"),
        ("Кофе\nи булочка", "Кофе и булочка"),
        ("Кофе​ и‮ булочка", "Кофе и булочка"),  # нулевая ширина и смена направления письма
        ("<b>жирный</b> & \"кавычки\"", "<b>жирный</b> & \"кавычки\""),  # экранирует вывод, а не ввод
    ],
)
def test_clean_stake(raw, expected) -> None:
    assert clean_stake(raw) == expected


def test_clean_stake_limit_is_80_characters_after_whitespace_collapse() -> None:
    assert clean_stake("а" * STAKE_MAX) == "а" * STAKE_MAX
    assert clean_stake("а" * 40 + "      " + "б" * 39) == "а" * 40 + " " + "б" * 39  # пробелы не считаются лишними
    with pytest.raises(ValueError, match="80"):
        clean_stake("а" * (STAKE_MAX + 1))


@pytest.mark.asyncio
async def test_create_with_and_without_stake(db_session) -> None:
    plain = await create_league(db_session, owner_key=OWNER, owner_name="Саша", name="Раньше", now=NOW)
    assert plain.stake_text is None and plain.image_key is None
    with_stake = await create_league(
        db_session, owner_key=OWNER, owner_name="Саша", name="Теперь", now=NOW, stake_text="  Обед   в пятницу "
    )
    assert with_stake.stake_text == "Обед в пятницу"
    mine = {x.name: x for x in await player_leagues(db_session, player_key=OWNER, now=NOW, with_rank=False)}
    assert mine["Теперь"].stake_text == "Обед в пятницу" and mine["Раньше"].stake_text is None


@pytest.mark.asyncio
async def test_update_league_owner_only_and_partial(db_session) -> None:
    league = await _league(db_session, stake_text="Кофе")
    renamed = await update_league(db_session, league_id=league.id, player_key=OWNER, name="Наш двор")
    assert renamed.name == "Наш двор" and renamed.stake_text == "Кофе"  # строка не тронута
    changed = await update_league(db_session, league_id=league.id, player_key=OWNER, stake_text="Пицца")
    assert changed.name == "Наш двор" and changed.stake_text == "Пицца"
    cleared = await update_league(db_session, league_id=league.id, player_key=OWNER, stake_text="   ")
    assert cleared.stake_text is None
    with pytest.raises(ValueError):
        await update_league(db_session, league_id=league.id, player_key=OWNER)
    with pytest.raises(ValueError, match="80"):
        await update_league(db_session, league_id=league.id, player_key=OWNER, stake_text="я" * 81)
    with pytest.raises(PermissionError):
        await update_league(db_session, league_id=league.id, player_key=MEMBER, stake_text="Моё")
    with pytest.raises(PermissionError):
        await update_league(db_session, league_id=league.id, player_key=STRANGER, name="Чужая")
    with pytest.raises(LookupError):
        await update_league(db_session, league_id=league.id + 999, player_key=OWNER, stake_text="x")
    row = (await db_session.execute(text("SELECT name, stake_text FROM hockey_leagues WHERE id = :i"), {"i": league.id})).one()
    assert (row.name, row.stake_text) == ("Наш двор", None)


@pytest.mark.asyncio
async def test_database_refuses_blank_or_overlong_stake(db_session) -> None:
    league = await _league(db_session)
    for bad in ("   ", "я" * 81):
        with pytest.raises(Exception):  # noqa: B017 — CHECK-ограничение или длина столбца
            async with db_session.begin_nested():
                await db_session.execute(
                    text("UPDATE hockey_leagues SET stake_text = :s WHERE id = :i"), {"s": bad, "i": league.id}
                )


# ---------- картинка ----------


@pytest.mark.asyncio
async def test_store_set_replace_and_release(db_session, _local_storage: Path) -> None:
    league = await _league(db_session)
    first = await images.store_league_image(league.id, _jpeg())
    assert first.startswith(f"kk-leagues/{league.id}/") and first.endswith(".jpg")
    assert (_local_storage / first).is_file() and (_local_storage / images.thumb_key(first)).is_file()

    updated, previous = await set_league_image(db_session, league_id=league.id, player_key=OWNER, image_key=first)
    assert updated.image_key == first and previous is None
    preview = await league_preview(db_session, league.invite_code)
    assert preview is not None and preview["image_key"] == first

    second = await images.store_league_image(league.id, _jpeg((200, 0, 0)))
    _, previous = await set_league_image(db_session, league_id=league.id, player_key=OWNER, image_key=second)
    assert previous == first
    assert await images.release_image(db_session, previous) is True  # ссылок не осталось — файлы ушли
    assert not (_local_storage / first).exists() and not (_local_storage / images.thumb_key(first)).exists()
    assert (_local_storage / second).is_file()

    _, previous = await set_league_image(db_session, league_id=league.id, player_key=OWNER, image_key=None)
    assert previous == second


@pytest.mark.asyncio
async def test_only_owner_sets_image(db_session) -> None:
    league = await _league(db_session)
    for who, error in ((MEMBER, PermissionError), (STRANGER, PermissionError)):
        with pytest.raises(error):
            await set_league_image(db_session, league_id=league.id, player_key=who, image_key="kk-leagues/1/x.jpg")
    with pytest.raises(LookupError):
        await set_league_image(db_session, league_id=league.id + 999, player_key=OWNER, image_key=None)


@pytest.mark.asyncio
async def test_release_keeps_file_while_another_league_uses_it(db_session, _local_storage: Path) -> None:
    league = await _league(db_session)
    key = await images.store_league_image(league.id, _jpeg())
    await set_league_image(db_session, league_id=league.id, player_key=OWNER, image_key=key)
    await db_session.execute(text("UPDATE hockey_leagues SET starts_at = :s, ends_at = :e WHERE id = :i"), {
        "s": NOW - timedelta(days=60), "e": NOW - timedelta(days=1), "i": league.id,
    })
    fresh, created = await extend_league(db_session, league_id=league.id, player_key=OWNER, now=NOW)
    assert created and fresh.image_key == key  # продолжение несёт то же лицо
    assert await images.release_image(db_session, key) is False
    assert (_local_storage / key).is_file()
    await set_league_image(db_session, league_id=league.id, player_key=OWNER, image_key=None)
    assert await images.release_image(db_session, key) is False  # у продолжения она всё ещё есть
    await set_league_image(db_session, league_id=fresh.id, player_key=OWNER, image_key=None)
    assert await images.release_image(db_session, key) is True
    assert not (_local_storage / key).exists()


@pytest.mark.asyncio
async def test_release_never_touches_foreign_prefixes(db_session, _local_storage: Path) -> None:
    other = _local_storage / "trainers" / "1" / "face.jpg"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"keep")
    assert await images.release_image(db_session, "trainers/1/face.jpg") is False
    assert await images.release_image(db_session, "kk-leagues/../trainers/1/face.jpg") is False
    assert other.read_bytes() == b"keep"


@pytest.mark.asyncio
async def test_storage_failure_becomes_a_human_error(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    league = await _league(db_session)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("src.infrastructure.s3.put_bytes", boom)
    with pytest.raises(images.LeagueImageError) as err:
        await images.store_league_image(league.id, _jpeg())
    assert err.value.code == "storage" and err.value.status == 503


# ---------- жалоба ----------


async def _count(db_session, league_id: int) -> int:
    return int(
        (
            await db_session.execute(
                text("SELECT COUNT(*) FROM hockey_league_reports WHERE league_id = :i"), {"i": league_id}
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_report_rights(db_session) -> None:
    league = await _league(db_session)
    with pytest.raises(reports.OwnLeagueReport):
        await reports.report_league(db_session, league_id=league.id, reporter_key=OWNER, now=NOW)
    with pytest.raises(PermissionError):
        await reports.report_league(db_session, league_id=league.id, reporter_key=STRANGER, now=NOW)
    with pytest.raises(LookupError):
        await reports.report_league(db_session, league_id=league.id + 999, reporter_key=MEMBER, now=NOW)
    assert await _count(db_session, league.id) == 0
    done = await reports.report_league(db_session, league_id=league.id, reporter_key=MEMBER, now=NOW)
    assert done.alert is True and done.reports_24h == 1 and done.members == 2


@pytest.mark.asyncio
async def test_repeat_reports_within_a_day_write_rows_but_do_not_repeat_the_alert(db_session) -> None:
    league = await _league(db_session)
    third = 880_361_004
    await join_by_code(db_session, player_key=third, display_name="Игорь", code=league.invite_code)
    first = await reports.report_league(db_session, league_id=league.id, reporter_key=MEMBER, now=NOW)
    again = await reports.report_league(db_session, league_id=league.id, reporter_key=MEMBER, now=NOW + timedelta(hours=1))
    other = await reports.report_league(db_session, league_id=league.id, reporter_key=third, now=NOW + timedelta(hours=23))
    assert (first.alert, again.alert, other.alert) == (True, False, False)
    assert other.reports_24h == 3 and await _count(db_session, league.id) == 3
    later = await reports.report_league(db_session, league_id=league.id, reporter_key=MEMBER, now=NOW + timedelta(hours=25))
    assert later.alert is True  # прошли сутки с последнего сообщения


@pytest.mark.asyncio
async def test_failed_delivery_is_retried_by_the_next_report(db_session) -> None:
    league = await _league(db_session)
    first = await reports.report_league(db_session, league_id=league.id, reporter_key=MEMBER, now=NOW)
    await reports.unmark_alerted(db_session, first.id)  # сообщение админам не дошло
    again = await reports.report_league(db_session, league_id=league.id, reporter_key=MEMBER, now=NOW + timedelta(minutes=5))
    assert again.alert is True


@pytest.mark.asyncio
async def test_alert_text_escapes_user_text_and_names_the_league(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.test")
    league = await _league(db_session, stake_text="<script>x</script> & кофе")
    await db_session.execute(text("UPDATE hockey_leagues SET name = :n WHERE id = :i"), {"n": "<i>Двор</i>", "i": league.id})
    report = await reports.report_league(db_session, league_id=league.id, reporter_key=MEMBER, now=NOW)
    body = reports.format_report_alert(report)
    assert f"#{league.id}" in body
    assert "<script>" not in body and "&lt;script&gt;" in body and "&lt;i&gt;Двор&lt;/i&gt;" in body
    assert "Картинка: нет" in body
    key = await images.store_league_image(league.id, _jpeg())
    await set_league_image(db_session, league_id=league.id, player_key=OWNER, image_key=key)
    with_image = await reports.report_league(db_session, league_id=league.id, reporter_key=MEMBER, now=NOW)
    assert f"Картинка: https://glide.test/api/public/photos/{key}" in reports.format_report_alert(with_image)


@pytest.mark.asyncio
async def test_notify_admins_sends_one_message_with_a_clear_button(db_session) -> None:
    league = await _league(db_session, stake_text="Кофе")
    report = await reports.report_league(db_session, league_id=league.id, reporter_key=MEMBER, now=NOW)

    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[dict] = []
            self.session = self

        async def send_message(self, **kwargs) -> None:
            self.sent.append(kwargs)

        async def close(self) -> None:
            return None

    class FakeSettings:
        telegram_bot_token_admin = "t"
        ice_alert_chat_ids = [111]
        admin_telegram_ids = [222]

    bot = FakeBot()
    from src.ingestion.alerts import send_ice_health_to_admins

    delivered = await send_ice_health_to_admins(
        reports.format_report_alert(report),
        event="kk league report",
        settings=FakeSettings(),
        bot_factory=lambda token: bot,
        reply_markup=reports.report_markup(league.id),
    )
    assert delivered is True and len(bot.sent) == 1
    message = bot.sent[0]
    assert message["chat_id"] == 111 and "Кофе" in message["text"]
    button = message["reply_markup"].inline_keyboard[0][0]
    assert button.callback_data == f"hk:lclr:{league.id}"
    assert len(button.callback_data.encode()) <= 64


# ---------- очистка ----------


@pytest.mark.asyncio
async def test_clear_identity_empties_image_and_stake_and_removes_the_file(db_session, _local_storage: Path) -> None:
    league = await _league(db_session, stake_text="Кофе")
    key = await images.store_league_image(league.id, _jpeg())
    await set_league_image(db_session, league_id=league.id, player_key=OWNER, image_key=key)

    cleared = await reports.clear_identity_now(db_session, league_id=league.id)
    assert cleared == {
        "id": league.id,
        "name": "Двор",
        "had_image": True,
        "had_stake": True,
        "leagues_cleared": 1,
    }
    row = (await db_session.execute(text("SELECT name, image_key, stake_text FROM hockey_leagues WHERE id = :i"), {"i": league.id})).one()
    assert (row.name, row.image_key, row.stake_text) == ("Двор", None, None)
    assert not (_local_storage / key).exists()
    again = await reports.clear_identity_now(db_session, league_id=league.id)
    assert again is not None and again["had_image"] is False and again["had_stake"] is False
    assert await reports.clear_identity_now(db_session, league_id=league.id + 999) is None


@pytest.mark.asyncio
async def test_clear_identity_also_clears_the_continuation_sharing_the_file(db_session, _local_storage: Path) -> None:
    league = await _league(db_session)
    key = await images.store_league_image(league.id, _jpeg())
    await set_league_image(db_session, league_id=league.id, player_key=OWNER, image_key=key)
    await db_session.execute(text("UPDATE hockey_leagues SET starts_at = :s, ends_at = :e WHERE id = :i"), {
        "s": NOW - timedelta(days=60), "e": NOW - timedelta(days=1), "i": league.id,
    })
    fresh, _ = await extend_league(db_session, league_id=league.id, player_key=OWNER, now=NOW)
    cleared = await reports.clear_identity_now(db_session, league_id=league.id)
    assert cleared is not None and cleared["leagues_cleared"] == 2
    left = (await db_session.execute(text("SELECT image_key FROM hockey_leagues WHERE id = :i"), {"i": fresh.id})).scalar_one()
    assert left is None and not (_local_storage / key).exists()
