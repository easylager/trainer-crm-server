@pytest.mark.asyncio
async def test_lost_claim_before_send_requeues_primary_notification(committed_db, monkeypatch) -> None:
    _city_id, _arena_id, (follow_id,) = await _committed_arena(
        committed_db, telegram_ids=(_unique_telegram_id(),)
    )
    now = _NOW + timedelta(minutes=30)
    slot = _slot(_FRIDAY, time(20, 30), time(21, 30))
    async with committed_db() as session:
        notification_id = await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([], [slot]),
            now=now,
            not_before=now - timedelta(minutes=1),
        )
        await session.commit()

    async def fake_refresh(*args, **kwargs):
        return None

    monkeypatch.setattr("src.application.arena_follow_notify._refresh_claim", fake_refresh)

    async with committed_db() as session:
        assert await dispatch_due_follow_notifications(
            session,
            now=now,
            webapp_base_url=_BASE,
            send=lambda *_args, **_kwargs: None,
        ) == 0

    async with committed_db() as session:
        status = (
            await session.execute(
                text("SELECT status FROM arena_follow_notifications WHERE id = :id"),
                {"id": notification_id},
            )
        ).scalar_one()
    assert status == "pending"
