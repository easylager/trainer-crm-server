    logger.warning("arena follow lost sending claim before send id=%s", primary.notification_id)
    await _requeue_or_merge(
        session,
        primary.notification_id,
        not_before=moment,
        expected_claimed_at=primary.claimed_at,
        expected_attempts=primary.attempts,
        check_claim=True,
    )
    for extra in rest:
        await _requeue_or_merge(
            session,
            extra.notification_id,
            not_before=moment,
            expected_claimed_at=extra.claimed_at,
            expected_attempts=extra.attempts,
            check_claim=True,
        )
    await session.commit()
    continue
