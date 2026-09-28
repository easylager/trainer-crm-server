"""Тип площадки на создании арены и свои услуги тренера (нужна тестовая БД)."""

import pytest
from sqlalchemy import text

from src.application.arena_public_use_cases import (
    IcePublicQueryError,
    _venue_type_facets,
    parse_venue_type_filter,
)
from src.application.trainer_arena_create_use_cases import create_trainer_arena
from src.application.trainer_custom_service_use_cases import (
    MAX_CUSTOM_SERVICES_PER_TRAINER,
    CustomServiceError,
    add_trainer_custom_service,
)
from src.application.trainer_use_cases import create_trainer


async def _seed_trainer(db_session, monkeypatch) -> tuple[int, int]:
    sid = (await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))).scalar()
    cid = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if sid is None or cid is None:
        pytest.skip("need seed services and cities")

    async def _fake_geocode(address, city_name):
        return None

    monkeypatch.setattr(
        "src.application.trainer_arena_create_use_cases._geocode_address", _fake_geocode
    )
    trainer_id = await create_trainer(
        db_session,
        profile={
            "first_name": "Евгений",
            "last_name": "Залов",
            "phone": "+375291119912",
            "city_id": cid,
        },
        service_ids=[sid],
        arena_ids=[],
    )
    return trainer_id, cid


class TestArenaVenueType:
    @pytest.mark.asyncio
    async def test_gym_is_stored_as_gym(self, db_session, monkeypatch):
        """Ровно кейс арены #201: тренер по ОФП заводит зал, а не каток."""
        trainer_id, _ = await _seed_trainer(db_session, monkeypatch)
        result = await create_trainer_arena(
            db_session,
            trainer_id,
            name="Lifestyle",
            address="Машерова 76А",
            venue_type="gym",
        )
        assert result["status"] == "created"
        stored = (
            await db_session.execute(
                text("SELECT venue_type FROM arenas WHERE id = :id"),
                {"id": result["arena_id"]},
            )
        ).scalar()
        assert stored == "gym"

    @pytest.mark.asyncio
    async def test_missing_type_defaults_to_ice(self, db_session, monkeypatch):
        """Старые клиенты Mini App поля не шлют — они должны и дальше заводить катки."""
        trainer_id, _ = await _seed_trainer(db_session, monkeypatch)
        result = await create_trainer_arena(
            db_session, trainer_id, name="Каток без типа", address="ул. Ледовая, 2"
        )
        stored = (
            await db_session.execute(
                text("SELECT venue_type FROM arenas WHERE id = :id"),
                {"id": result["arena_id"]},
            )
        ).scalar()
        assert stored == "ice"

    @pytest.mark.asyncio
    async def test_garbage_type_does_not_block_creation(self, db_session, monkeypatch):
        """Тренер уже заполнил форму — ронять её из-за ключа типа дороже, чем поправить."""
        trainer_id, _ = await _seed_trainer(db_session, monkeypatch)
        result = await create_trainer_arena(
            db_session,
            trainer_id,
            name="Площадка с мусорным типом",
            address="ул. Неизвестная, 3",
            venue_type="trampoline_park",
        )
        assert result["status"] == "created"

    @pytest.mark.asyncio
    async def test_wrapping_quotes_are_stripped_on_create(self, db_session, monkeypatch):
        trainer_id, _ = await _seed_trainer(db_session, monkeypatch)
        result = await create_trainer_arena(
            db_session,
            trainer_id,
            name='"Lifestyle Минск"',
            address="Машерова 76А, корп. 2",
            venue_type="gym",
        )
        stored = (
            await db_session.execute(
                text("SELECT name FROM arenas WHERE id = :id"), {"id": result["arena_id"]}
            )
        ).scalar()
        assert stored == "Lifestyle Минск"


class TestVenueTypeFilter:
    def test_empty_means_no_filter(self):
        assert parse_venue_type_filter(None) == set()
        assert parse_venue_type_filter("  ") == set()

    def test_comma_separated(self):
        assert parse_venue_type_filter("ice,gym") == {"ice", "gym"}

    def test_unknown_key_is_an_error_not_a_silent_pass(self):
        """Молча отдать все площадки — значит показать каток тому, кто просил зал."""
        with pytest.raises(IcePublicQueryError):
            parse_venue_type_filter("sauna")

    def test_facets_skip_absent_types(self):
        """Город без бассейнов не должен рисовать чип, за которым пусто."""
        rows = [{"venue_type": "ice"}, {"venue_type": "ice"}, {"venue_type": "gym"}]
        facets = _venue_type_facets(rows)
        assert [f["key"] for f in facets] == ["ice", "gym"]
        assert [f["count"] for f in facets] == [2, 1]

    def test_facets_treat_legacy_null_as_ice(self):
        assert _venue_type_facets([{"venue_type": None}]) == [
            {"key": "ice", "chip": "Лёд", "count": 1}
        ]


class TestCustomServices:
    @pytest.mark.asyncio
    async def test_new_service_is_created_private_and_attached(self, db_session, monkeypatch):
        trainer_id, _ = await _seed_trainer(db_session, monkeypatch)
        monkeypatch.setattr(
            "src.application.admin_custom_service_notify.notify_admins_new_custom_service",
            _noop_notify,
        )
        result = await add_trainer_custom_service(
            db_session, trainer_id, "Спортивная психология"
        )
        assert result["created"] is True
        assert result["is_public"] is False

        row = (
            await db_session.execute(
                text("SELECT name, is_public, created_by_trainer_id FROM services WHERE id = :id"),
                {"id": result["service_id"]},
            )
        ).fetchone()
        assert row[0] == "Спортивная психология"
        assert bool(row[1]) is False
        assert int(row[2]) == trainer_id

        linked = (
            await db_session.execute(
                text(
                    "SELECT COUNT(*) FROM trainer_services "
                    "WHERE trainer_id = :tid AND service_id = :sid"
                ),
                {"tid": trainer_id, "sid": result["service_id"]},
            )
        ).scalar()
        assert int(linked) == 1

    @pytest.mark.asyncio
    async def test_same_name_twice_does_not_duplicate(self, db_session, monkeypatch):
        """Иначе фильтр каталога расползётся на синонимы за месяц."""
        trainer_id, _ = await _seed_trainer(db_session, monkeypatch)
        monkeypatch.setattr(
            "src.application.admin_custom_service_notify.notify_admins_new_custom_service",
            _noop_notify,
        )
        first = await add_trainer_custom_service(db_session, trainer_id, "Хатха-йога")
        second = await add_trainer_custom_service(db_session, trainer_id, "  хатха йога ")
        assert second["created"] is False
        assert second["service_id"] == first["service_id"]

    @pytest.mark.asyncio
    async def test_existing_public_service_is_reused_not_shadowed(
        self, db_session, monkeypatch
    ):
        """Вписал руками то, что у нас уже есть — попадает в общий фильтр, а не мимо."""
        trainer_id, _ = await _seed_trainer(db_session, monkeypatch)
        public = (
            await db_session.execute(
                text("SELECT id, name FROM services WHERE is_public ORDER BY id LIMIT 1")
            )
        ).fetchone()
        if public is None:
            pytest.skip("need at least one public service")
        result = await add_trainer_custom_service(db_session, trainer_id, str(public[1]).upper())
        assert result["created"] is False
        assert result["service_id"] == int(public[0])
        assert result["is_public"] is True

    @pytest.mark.asyncio
    async def test_cap_is_enforced(self, db_session, monkeypatch):
        trainer_id, _ = await _seed_trainer(db_session, monkeypatch)
        monkeypatch.setattr(
            "src.application.admin_custom_service_notify.notify_admins_new_custom_service",
            _noop_notify,
        )
        for i in range(MAX_CUSTOM_SERVICES_PER_TRAINER):
            await add_trainer_custom_service(db_session, trainer_id, f"Своя услуга {i}")
        with pytest.raises(CustomServiceError):
            await add_trainer_custom_service(db_session, trainer_id, "Ещё одна лишняя")


async def _noop_notify(**kwargs):
    """Админ-бот в тестах не дёргаем — токена нет, и сеть тут не при чём."""
    return None
