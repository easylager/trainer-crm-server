"""TASK-416: «Отзывы» и «На занятиях» в выдаче витрины — только при включённом флаге единой карточки.

Источник и отбор те же, что у ``/t/`` (``site_trainer_page._load_reviews``, ``REVIEWS_MIN_SHOWN``):
подтверждённые тексты, от трёх; фото — после героя. Флаг выключен — ключей нет.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.miniapp_trainer_showcase import class_photo_urls, showcase_reviews
from src.application.trainer_use_cases import add_trainer_rating
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on


def _rev(n: int) -> list[dict]:
    return [
        {"name": f"Марк М{i}.", "rating": 5 - i % 2, "text": f"Текст {i}", "date": date(2026, 11, 2 + i)}
        for i in range(n)
    ]


@pytest.mark.parametrize("n", [0, 1, 2])
def test_fewer_than_three_texts_give_no_block(n: int) -> None:
    assert showcase_reviews(_rev(n)) is None


@pytest.mark.parametrize("n", [3, 4, 12])
def test_three_and_more_texts_go_out_as_is(n: int) -> None:
    out = showcase_reviews(_rev(n))
    assert out is not None and len(out) == n
    assert out[0] == {"name": "Марк М0.", "rating": 5, "text": "Текст 0", "date": "2026-11-02"}
    assert out[1]["rating"] == 4


def test_review_without_date_keeps_the_rest() -> None:
    rows = _rev(3)
    rows[2]["date"] = None
    assert showcase_reviews(rows)[2]["date"] is None


def _ph(*keys: str | None) -> dict:
    return {"photos": [{"file_key": k} for k in keys]}


def test_class_photos_are_photos_after_the_hero() -> None:
    assert class_photo_urls({"photos": []}) == []
    assert class_photo_urls({}) == []
    assert class_photo_urls(_ph("trainers/1/a.jpg")) == []
    assert class_photo_urls(_ph("trainers/1/a.jpg", "trainers/1/b.jpg", "trainers/1/c.jpg")) == [
        "/api/public/photos/trainers/1/b.jpg",
        "/api/public/photos/trainers/1/c.jpg",
    ]


def test_class_photos_skip_hero_repeats_duplicates_and_empty_keys() -> None:
    got = class_photo_urls(_ph("trainers/1/a.jpg", "trainers/1/a.jpg", None, "trainers/1/b.jpg", "trainers/1/b.jpg"))
    assert got == ["/api/public/photos/trainers/1/b.jpg"]


def test_class_photos_use_the_list_key_like_the_hero() -> None:
    trainer = {
        "photos": [
            {"file_key": "trainers/1/a.jpg"},
            {"file_key": "trainers/1/b.jpg", "file_key_list": "trainers/1/b_list.jpg"},
        ]
    }
    assert class_photo_urls(trainer) == ["/api/public/photos/trainers/1/b_list.jpg"]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _item(db_session, monkeypatch, *, flag: bool, reviews: list[tuple[str, str]], photos: int) -> dict:
    if flag:
        monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    else:
        monkeypatch.delenv("UNIFIED_TRAINER_CARD_ENABLED", raising=False)
    async with _client() as client:
        place = await _place(db_session)
        tid = await _trainer_on(db_session, client, place, first_name=f"Отз{uuid.uuid4().hex[:4]}")
        await db_session.execute(text("DELETE FROM trainer_photos WHERE trainer_id = :t"), {"t": tid})
        for i in range(photos):
            await db_session.execute(
                text("INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:t, :k, :i)"),
                {"t": tid, "k": f"trainers/{tid}/p{i}.jpg", "i": i},
            )
        for k, (status, body) in enumerate(reviews):
            tg = 8_200_000_000 + tid * 100 + k
            await add_trainer_rating(db_session, tid, tg, 5, review_text=body)
            await db_session.execute(
                text("UPDATE trainer_ratings SET review_status = :s WHERE trainer_id = :t AND client_telegram_id = :c"),
                {"s": status, "t": tid, "c": tg},
            )
        await db_session.commit()
        body = (await client.get(f"/api/public/trainer-showcase?city_id={place['city_id']}")).json()
    return next(t for t in body["items"] if t["id"] == tid)


THREE_AND_HIDDEN = [
    ("approved", "Первый отзыв про занятия"),
    ("approved", "Второй отзыв про занятия"),
    ("approved", "Третий отзыв про занятия"),
    ("pending", "Ещё не проверен"),
    ("rejected", "Отклонённый текст"),
]


@pytest.mark.asyncio
async def test_flag_on_three_approved_texts_and_photos_after_hero(app_use_test_db, db_session, monkeypatch) -> None:
    item = await _item(db_session, monkeypatch, flag=True, reviews=THREE_AND_HIDDEN, photos=3)
    texts = [r["text"] for r in item["reviews"]]
    # Как на /t/: только подтверждённые, новые сверху; непроверенный и отклонённый не уходят.
    assert sorted(texts) == sorted(t for s, t in THREE_AND_HIDDEN if s == "approved")
    assert "Ещё не проверен" not in texts and "Отклонённый текст" not in texts
    assert set(item["reviews"][0]) == {"name", "rating", "text", "date"}
    assert item["reviews"][0]["date"] == date.fromisoformat(item["reviews"][0]["date"]).isoformat()
    # Имя — «Марк М.»/«Ученик», без telegram id.
    assert all("8200" not in r["name"] for r in item["reviews"])
    # Первое фото — герой, «На занятиях» — остальные два.
    assert item["photo_url"].endswith("/p0.jpg")
    assert [u.rsplit("/", 1)[1] for u in item["class_photos"]] == ["p1.jpg", "p2.jpg"]


@pytest.mark.asyncio
async def test_flag_on_two_approved_texts_no_block_one_photo_no_gallery(
    app_use_test_db, db_session, monkeypatch
) -> None:
    item = await _item(
        db_session,
        monkeypatch,
        flag=True,
        reviews=[("approved", "Хороший тренер"), ("approved", "Придём ещё"), ("pending", "Третий, но не проверен")],
        photos=1,
    )
    assert item["reviews"] is None
    assert item["class_photos"] == []


@pytest.mark.asyncio
async def test_flag_on_approved_rating_without_text_does_not_count(app_use_test_db, db_session, monkeypatch) -> None:
    item = await _item(
        db_session,
        monkeypatch,
        flag=True,
        reviews=[("approved", "Раз"), ("approved", "Два"), ("approved", "   ")],
        photos=0,
    )
    assert item["reviews"] is None
    assert item["class_photos"] == []


@pytest.mark.asyncio
async def test_flag_off_showcase_has_no_reviews_nor_class_photos(app_use_test_db, db_session, monkeypatch) -> None:
    item = await _item(db_session, monkeypatch, flag=False, reviews=THREE_AND_HIDDEN, photos=3)
    assert "reviews" not in item
    assert "class_photos" not in item


async def _two_trainers(db_session, client) -> tuple[dict, int, int]:
    place = await _place(db_session)
    a = await _trainer_on(db_session, client, place, first_name=f"А{uuid.uuid4().hex[:4]}")
    b = await _trainer_on(db_session, client, place, first_name=f"Б{uuid.uuid4().hex[:4]}")
    return place, a, b


async def _rate(db_session, tid: int, n: int, *, status: str, body: str) -> None:
    tg = 8_300_000_000 + tid * 100 + n
    await add_trainer_rating(db_session, tid, tg, 5, review_text=body)
    await db_session.execute(
        text("UPDATE trainer_ratings SET review_status = :s WHERE trainer_id = :t AND client_telegram_id = :c"),
        {"s": status, "t": tid, "c": tg},
    )


def _spy_review_sql(monkeypatch, session):
    hits: list[str] = []
    original = session.execute

    async def execute(statement, *args, **kwargs):
        sql = str(statement)
        if "review_status" in sql:
            hits.append(sql)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute)
    return hits


@pytest.mark.asyncio
async def test_batch_reviews_match_per_trainer_loader(app_use_test_db, db_session) -> None:
    """Один ANY(:ids) даёт то же, что _load_reviews по каждому тренеру: отбор, порядок, потолок 12."""
    from src.application.miniapp_trainer_showcase import load_showcase_reviews
    from src.application.site_trainer_page import _load_reviews

    async with _client() as client:
        _place_row, tid_a, tid_b = await _two_trainers(db_session, client)
    for i in range(13):
        await _rate(db_session, tid_a, i, status="approved", body=f"Текст {i:02d}")
    await _rate(db_session, tid_a, 20, status="pending", body="Ещё не проверен")
    await _rate(db_session, tid_a, 21, status="approved", body="   ")
    for i in range(3):
        await _rate(db_session, tid_b, i, status="approved", body=f"У второго {i}")
    await db_session.commit()

    batch = await load_showcase_reviews(db_session, [tid_a, tid_b])
    assert batch[tid_a] == await _load_reviews(db_session, tid_a)
    assert batch[tid_b] == await _load_reviews(db_session, tid_b)
    assert len(batch[tid_a]) == 12
    assert all("Ещё не проверен" not in row["text"] for row in batch[tid_a])
    assert batch[tid_a][0]["text"] == "Текст 12"
    assert batch == await load_showcase_reviews(db_session, [tid_b, tid_a])


@pytest.mark.asyncio
async def test_flag_on_loads_reviews_once_flag_off_loads_none(app_use_test_db, db_session, monkeypatch) -> None:
    async with _client() as client:
        place, tid_a, tid_b = await _two_trainers(db_session, client)
        for tid in (tid_a, tid_b):
            for i in range(3):
                await _rate(db_session, tid, i, status="approved", body=f"Отзыв {tid}-{i}")
        await db_session.commit()

        monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
        on_hits = _spy_review_sql(monkeypatch, db_session)
        body = (await client.get(f"/api/public/trainer-showcase?city_id={place['city_id']}")).json()
        by_id = {t["id"]: t for t in body["items"]}
        assert len(by_id[tid_a]["reviews"]) == 3
        assert len(by_id[tid_b]["reviews"]) == 3
        assert len(on_hits) == 1
        assert "ANY" in on_hits[0]

        monkeypatch.delenv("UNIFIED_TRAINER_CARD_ENABLED", raising=False)
        off_hits = _spy_review_sql(monkeypatch, db_session)
        body_off = (await client.get(f"/api/public/trainer-showcase?city_id={place['city_id']}")).json()
        off_item = next(t for t in body_off["items"] if t["id"] == tid_a)
        assert "reviews" not in off_item
        assert off_hits == []
