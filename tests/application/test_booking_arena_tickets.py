import pytest

from src.application.booking_arena_tickets import enrich_booking_notification_with_arena_tickets


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Session:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    async def execute(self, *_args, **_kwargs):
        self.calls += 1
        return _Result(self.value)


@pytest.mark.asyncio
async def test_enrich_sets_https_ticket_url() -> None:
    info = {"resolved_arena_id": 6, "service_is_online": False}
    await enrich_booking_notification_with_arena_tickets(_Session("https://chizhovka-arena.by/x"), info)
    assert info["arena_tickets_url"] == "https://chizhovka-arena.by/x"


@pytest.mark.asyncio
async def test_enrich_rejects_unsafe_url() -> None:
    info = {"resolved_arena_id": 6, "service_is_online": False}
    await enrich_booking_notification_with_arena_tickets(_Session("javascript:alert(1)"), info)
    assert info["arena_tickets_url"] is None


@pytest.mark.asyncio
async def test_enrich_online_service_and_no_arena_skip_db() -> None:
    db = _Session("https://koronaticket.by/rink")
    online = {"resolved_arena_id": 6, "service_is_online": True}
    no_arena = {"resolved_arena_id": None, "service_is_online": False}
    await enrich_booking_notification_with_arena_tickets(db, online)
    await enrich_booking_notification_with_arena_tickets(db, no_arena)
    assert online["arena_tickets_url"] is None
    assert no_arena["arena_tickets_url"] is None
    assert db.calls == 0
