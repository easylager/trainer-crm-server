"""TASK-361: API лиг «Кто кого» — картинка, строка «на что играем», жалоба и очистка админом."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text

from src.api.app import app
from src.application import hockey_league_images as images
from tests.api.test_admin_hockey import patch_admin_principal
from tests.api.test_webapp_client_hockey_leagues import ME, OTHER, STRANGER, _code, patch_client_principal

LEAGUES = "/api/webapp/client/hockey/leagues"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "GlideTestBot")
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.test")
    monkeypatch.setattr("src.infrastructure.s3._use_local", lambda: True)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list:
    """Сообщения админам: вместо Telegram — список; ответ доставки можно подменить в ``alerts.result``."""

    class Sent(list):
        result: bool | None = True

    sent = Sent()

    async def fake(report) -> bool | None:
        sent.append(report)
        return sent.result

    monkeypatch.setattr("src.application.hockey_league_reports.notify_admins", fake)
    return sent


def _png(size=(900, 600), color=(30, 100, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def _file(data: bytes, name: str = "photo.png", ctype: str = "image/png") -> dict:
    return {"file": (name, data, ctype)}


async def _make(client: AsyncClient, **body) -> dict:
    """Лига ME + участник OTHER. Возвращает ответ создания."""
    with patch_client_principal(ME):
        created = await client.post(LEAGUES, json={"name": "Двор", "display_name": "Саша", **body})
        assert created.status_code == 200, created.text
        league = created.json()
    with patch_client_principal(OTHER):
        joined = await client.post(
            f"{LEAGUES}/join", json={"code": _code(league["invite_url"]), "display_name": "Катя"}
        )
        assert joined.status_code == 200, joined.text
    return league


def _stored(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in (root / "kk-leagues").rglob("*") if p.is_file())


@pytest.mark.asyncio
async def test_create_without_identity_is_as_before(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client)
        assert league["stake_text"] is None and league["image_url"] is None and league["image_thumb_url"] is None
        with patch_client_principal(ME):
            listed = (await client.get(LEAGUES)).json()["items"][0]
            detail = (await client.get(f"{LEAGUES}/{league['id']}")).json()
    for payload in (listed, detail):
        assert payload["stake_text"] is None and payload["image_url"] is None and payload["image_thumb_url"] is None


@pytest.mark.asyncio
async def test_create_with_stake_shows_everywhere(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client, stake_text="  Обед   по пятницам ")
        assert league["stake_text"] == "Обед по пятницам"
        with patch_client_principal(OTHER):
            member_view = (await client.get(f"{LEAGUES}/{league['id']}")).json()
            member_list = (await client.get(LEAGUES)).json()["items"][0]
        preview = await client.get(f"/api/public/hockey/leagues/{_code(league['invite_url'])}")
    assert member_view["stake_text"] == "Обед по пятницам" == member_list["stake_text"]
    assert preview.status_code == 200 and preview.json()["stake_text"] == "Обед по пятницам"


@pytest.mark.asyncio
async def test_overlong_stake_is_refused_and_league_is_not_created(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            refused = await client.post(LEAGUES, json={"name": "Двор", "stake_text": "я" * 81})
            assert refused.status_code == 400 and "80" in refused.json()["detail"]
            assert (await client.get(LEAGUES)).json()["items"] == []
            ok = await client.post(LEAGUES, json={"name": "Двор", "stake_text": "я" * 80})
            assert ok.status_code == 200 and ok.json()["stake_text"] == "я" * 80


@pytest.mark.asyncio
async def test_patch_owner_changes_and_clears_stake_members_and_strangers_cannot(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client, stake_text="Кофе")
        url = f"{LEAGUES}/{league['id']}"
        for who, code in ((OTHER, 403), (STRANGER, 403)):
            with patch_client_principal(who):
                denied = await client.patch(url, json={"stake_text": "Моё"})
                assert denied.status_code == code, denied.text
        with patch_client_principal(ME):
            only_stake = await client.patch(url, json={"stake_text": "Пицца   на всех"})
            assert only_stake.status_code == 200 and only_stake.json()["stake_text"] == "Пицца на всех"
            assert only_stake.json()["name"] == "Двор"  # название не тронуто
            only_name = await client.patch(url, json={"name": "Наш двор"})
            assert only_name.json()["name"] == "Наш двор" and only_name.json()["stake_text"] == "Пицца на всех"
            both = await client.patch(url, json={"name": "Двор 2", "stake_text": "Кофе"})
            assert (both.json()["name"], both.json()["stake_text"]) == ("Двор 2", "Кофе")
            cleared = await client.patch(url, json={"stake_text": ""})
            assert cleared.status_code == 200 and cleared.json()["stake_text"] is None
            nulled = await client.patch(url, json={"stake_text": None})
            assert nulled.status_code == 200 and nulled.json()["stake_text"] is None
            empty = await client.patch(url, json={})
            assert empty.status_code == 400
            blank_name = await client.patch(url, json={"name": None})
            assert blank_name.status_code == 400 and blank_name.json()["detail"] == "Назови лигу"
            long_stake = await client.patch(url, json={"stake_text": "я" * 81})
            assert long_stake.status_code == 400
            missing = await client.patch(f"{LEAGUES}/{league['id'] + 999}", json={"stake_text": "x"})
            assert missing.status_code == 404


@pytest.mark.asyncio
async def test_owner_uploads_replaces_and_removes_image(app_use_test_db, _env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client)
        url = f"{LEAGUES}/{league['id']}/image"
        with patch_client_principal(ME):
            first = await client.post(url, files=_file(_png()))
            assert first.status_code == 200, first.text
            body = first.json()
        assert body["image_url"].startswith(f"/api/public/photos/kk-leagues/{league['id']}/")
        assert body["image_thumb_url"].endswith("_thumb.jpg")
        assert len(_stored(_env)) == 2

        # Публичный адрес отдаёт перекодированный JPEG (не исходный PNG), миниатюра — маленький.
        shown = await client.get(body["image_url"])
        assert shown.status_code == 200 and shown.headers["content-type"] == "image/jpeg"
        assert Image.open(io.BytesIO(shown.content)).size == (900, 600)
        thumb = await client.get(body["image_thumb_url"])
        assert max(Image.open(io.BytesIO(thumb.content)).size) == 320

        # Участник и приглашённый видят картинку; ключ хранилища наружу не уходит.
        with patch_client_principal(OTHER):
            member_view = (await client.get(f"{LEAGUES}/{league['id']}")).json()
            member_list = (await client.get(LEAGUES)).json()["items"][0]
        assert member_view["image_url"] == body["image_url"] == member_list["image_url"]
        assert member_list["image_thumb_url"] == body["image_thumb_url"]
        preview = (await client.get(f"/api/public/hockey/leagues/{_code(league['invite_url'])}")).json()
        assert preview["image_url"] == body["image_url"] and "image_key" not in preview and "kk-leagues/" not in str(
            {k: v for k, v in preview.items() if k not in ("image_url", "image_thumb_url")}
        )

        with patch_client_principal(ME):
            second = await client.post(url, files=_file(_png((300, 300), (200, 0, 0))))
            assert second.status_code == 200 and second.json()["image_url"] != body["image_url"]
            new_url = second.json()["image_url"]
        assert (await client.get(body["image_url"])).status_code == 404  # прежняя ушла, из кэша процесса — тоже
        assert (await client.get(new_url)).status_code == 200
        assert len(_stored(_env)) == 2

        with patch_client_principal(ME):
            removed = await client.delete(url)
            assert removed.status_code == 200 and removed.json()["image_url"] is None
            again = await client.delete(url)  # повтор безвреден
            assert again.status_code == 200 and again.json()["image_url"] is None
        assert (await client.get(new_url)).status_code == 404
        assert _stored(_env) == []


@pytest.mark.asyncio
async def test_member_and_stranger_cannot_touch_the_image(app_use_test_db, _env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client)
        url = f"{LEAGUES}/{league['id']}/image"
        with patch_client_principal(ME):
            assert (await client.post(url, files=_file(_png()))).status_code == 200
            kept = (await client.get(f"{LEAGUES}/{league['id']}")).json()["image_url"]
        for who in (OTHER, STRANGER):
            with patch_client_principal(who):
                up = await client.post(url, files=_file(_png((50, 50))))
                assert up.status_code == 403, up.text
                down = await client.delete(url)
                assert down.status_code == 403, down.text
        with patch_client_principal(ME):
            assert (await client.get(f"{LEAGUES}/{league['id']}")).json()["image_url"] == kept
            nowhere = await client.post(f"{LEAGUES}/{league['id'] + 999}/image", files=_file(_png()))
            assert nowhere.status_code == 404
            assert (await client.delete(f"{LEAGUES}/{league['id'] + 999}/image")).status_code == 404
        assert len(_stored(_env)) == 2  # чужие попытки файлов не добавили


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "name", "status"),
    [
        (b"", "empty.png", 400),
        (b"%PDF-1.4 hello", "doc.png", 400),  # расширение и заголовок врут — смотрим на содержимое
        (b"<html><script>alert(1)</script></html>", "page.jpg", 400),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 40, "broken.jpg", 400),
        (b"\xff\xd8" + b"\x00" * (images.MAX_UPLOAD_BYTES + 1), "huge.jpg", 413),
    ],
)
async def test_bad_upload_gives_a_clear_4xx_and_changes_nothing(app_use_test_db, _env: Path, data, name, status) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client)
        with patch_client_principal(ME):
            bad = await client.post(f"{LEAGUES}/{league['id']}/image", files=_file(data, name, "image/jpeg"))
            assert bad.status_code == status, bad.text
            assert isinstance(bad.json()["detail"], str) and bad.json()["detail"]
            assert (await client.get(f"{LEAGUES}/{league['id']}")).json()["image_url"] is None
    assert _stored(_env) == []


@pytest.mark.asyncio
async def test_gif_and_missing_file_field(app_use_test_db) -> None:
    gif = io.BytesIO()
    Image.new("RGB", (20, 20), (1, 2, 3)).save(gif, "GIF")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client)
        with patch_client_principal(ME):
            refused = await client.post(f"{LEAGUES}/{league['id']}/image", files=_file(gif.getvalue(), "a.gif", "image/gif"))
            assert refused.status_code == 415 and "JPEG" in refused.json()["detail"]
            no_file = await client.post(f"{LEAGUES}/{league['id']}/image", data={"x": "y"})
            assert no_file.status_code == 422


@pytest.mark.asyncio
async def test_join_screen_and_response_carry_the_identity(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            created = (await client.post(LEAGUES, json={"name": "Двор", "stake_text": "Кофе"})).json()
            await client.post(f"{LEAGUES}/{created['id']}/image", files=_file(_png()))
        code = _code(created["invite_url"])
        preview = (await client.get(f"/api/public/hockey/leagues/{code}")).json()
        assert preview["stake_text"] == "Кофе" and preview["image_url"] and preview["image_thumb_url"]
        with patch_client_principal(STRANGER):
            joined = (await client.post(f"{LEAGUES}/join", json={"code": code})).json()
        assert joined["stake_text"] == "Кофе" and joined["image_url"] == preview["image_url"]


@pytest.mark.asyncio
async def test_last_member_leaving_deletes_the_league_and_its_files(app_use_test_db, _env: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            created = (await client.post(LEAGUES, json={"name": "Один"})).json()
            await client.post(f"{LEAGUES}/{created['id']}/image", files=_file(_png()))
            assert len(_stored(_env)) == 2
            left = await client.delete(f"{LEAGUES}/{created['id']}/membership")
            assert left.json() == {"result": "deleted"}
    assert _stored(_env) == []


# ---------- жалоба ----------


@pytest.mark.asyncio
async def test_report_member_only_one_alert_a_day(app_use_test_db, db_session, alerts) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client, stake_text="Кофе")
        url = f"{LEAGUES}/{league['id']}/report"
        with patch_client_principal(ME):
            own = await client.post(url)
            assert own.status_code == 403 and "твоя" in own.json()["detail"]
        with patch_client_principal(STRANGER):
            assert (await client.post(url)).status_code == 403
        with patch_client_principal(OTHER):
            assert (await client.post(f"{LEAGUES}/{league['id'] + 999}/report")).status_code == 404
            first = await client.post(url)
            assert first.status_code == 200 and first.json() == {"ok": True}
            second = await client.post(url)
            assert second.status_code == 200
        assert len(alerts) == 1  # повтор в те же сутки сообщения не плодит
        assert alerts[0].league.id == league["id"] and alerts[0].league.stake_text == "Кофе"
    rows = (await db_session.execute(text("SELECT COUNT(*) FROM hockey_league_reports WHERE league_id = :i"), {"i": league["id"]})).scalar_one()
    assert rows == 2  # а строки пишутся


@pytest.mark.asyncio
async def test_report_retries_the_alert_when_delivery_failed(app_use_test_db, alerts) -> None:
    alerts.result = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client)
        with patch_client_principal(OTHER):
            assert (await client.post(f"{LEAGUES}/{league['id']}/report")).status_code == 200
            assert (await client.post(f"{LEAGUES}/{league['id']}/report")).status_code == 200  # игроку ошибки нет
            assert len(alerts) == 2  # не дошло — пробуем снова
            alerts.result = True
            await client.post(f"{LEAGUES}/{league['id']}/report")
            await client.post(f"{LEAGUES}/{league['id']}/report")
    assert len(alerts) == 3


@pytest.mark.asyncio
async def test_report_survives_a_crashing_admin_bot(app_use_test_db, monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("telegram is down")

    monkeypatch.setattr("src.ingestion.alerts.send_ice_health_to_admins", boom)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client)
        with patch_client_principal(OTHER):
            done = await client.post(f"{LEAGUES}/{league['id']}/report")
            assert done.status_code == 200, done.text


# ---------- очистка админом ----------


@pytest.mark.asyncio
async def test_admin_clears_image_and_stake(app_use_test_db, _env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    logged: list[tuple] = []
    monkeypatch.setattr("src.api.routes.admin_hockey.audit_log", lambda *a, **k: logged.append((a, k)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        league = await _make(client, stake_text="Кофе")
        with patch_client_principal(ME):
            body = (await client.post(f"{LEAGUES}/{league['id']}/image", files=_file(_png()))).json()
        clear = f"/api/webapp/admin/hockey/leagues/{league['id']}/clear-identity"
        denied = await client.post(clear)
        assert denied.status_code in (401, 403)
        with patch_client_principal(OTHER):  # обычный игрок — не админ
            assert (await client.post(clear)).status_code in (401, 403)
        with patch_admin_principal(777):
            cleared = await client.post(clear)
            assert cleared.status_code == 200, cleared.text
            assert cleared.json() == {
                "id": league["id"],
                "name": "Двор",
                "had_image": True,
                "had_stake": True,
                "leagues_cleared": 1,
            }
            missing = await client.post(f"/api/webapp/admin/hockey/leagues/{league['id'] + 999}/clear-identity")
            assert missing.status_code == 404
        assert (await client.get(body["image_url"])).status_code == 404
        assert _stored(_env) == []
        with patch_client_principal(OTHER):
            view = (await client.get(f"{LEAGUES}/{league['id']}")).json()
        assert view["image_url"] is None and view["stake_text"] is None and view["name"] == "Двор"
        # Владелец может поставить новое: очистка не блокирует лигу.
        with patch_client_principal(ME):
            again = await client.patch(f"{LEAGUES}/{league['id']}", json={"stake_text": "Чай"})
            assert again.status_code == 200 and again.json()["stake_text"] == "Чай"
    assert logged and logged[0][0][0] == "hockey.league_identity_cleared" and logged[0][0][2] == 777


# ---------- карточка приглашения ----------


@pytest.mark.asyncio
async def test_invite_card_uses_the_league_photo_and_stake(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch_client_principal(ME):
            plain = (await client.post(LEAGUES, json={"name": "Двор"})).json()
            face = (await client.post(LEAGUES, json={"name": "Двор", "stake_text": "Кофе"})).json()
            await client.post(f"{LEAGUES}/{face['id']}/image", files=_file(_png((1200, 630), (220, 40, 40))))
        before = await client.get(f"/kk/l/{_code(plain['invite_url'])}.png")
        after = await client.get(f"/kk/l/{_code(face['invite_url'])}.png")
    assert before.status_code == 200 and after.status_code == 200
    assert before.content[:8] == after.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert before.content != after.content
    card = Image.open(io.BytesIO(after.content)).convert("RGB")
    assert card.size == (1200, 630)
    # Красная картинка под затемнением: в шапке справа (где нет текста) красноватый, а не тёмно-синий фон.
    r, g, b = card.getpixel((1150, 30))
    assert r > b
