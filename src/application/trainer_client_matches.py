"""
«Похоже, это Анна из вашего списка»: who came by themselves and shares a phone with
a client the trainer added.

A typed phone binds nothing on its own (anyone can type any number), so the decision
belongs to the trainer, who knows their students:

* ``same`` — one person: the trainer's row is merged into the account (``merge_clients``),
  history and passes land on the profile that has Telegram;
* ``parent`` — the account is the parent: the trainer's row becomes one more profile in the
  parent's app (``link_guardian_profile``), Anna keeps her own history;
* ``different`` — never offer this pair again (``trainer_client_match_dismissals``).
"""
from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_use_cases import TRAINER_CLIENT_IDS_SQL

MatchDecision = Literal["same", "parent", "different"]
MATCH_DECISIONS: frozenset[str] = frozenset({"same", "parent", "different"})

_PAIRS_SQL = (
    """
    WITH mine AS ("""
    + TRAINER_CLIENT_IDS_SQL
    + """)
    SELECT c.id, c.first_name, c.last_name, c.telegram_id,
           o.id, o.first_name, o.last_name, c.phone
    FROM clients c
    JOIN clients o ON o.phone_normalized = c.phone_normalized AND o.id <> c.id
    WHERE c.id IN (SELECT client_id FROM mine)
      AND o.id IN (SELECT client_id FROM mine)
      AND c.telegram_id IS NOT NULL
      AND NOT COALESCE(c.is_sandbox, false)
      AND c.phone_normalized IS NOT NULL AND c.phone_normalized <> ''
      AND o.telegram_id IS NULL AND o.vk_user_id IS NULL
      AND NOT COALESCE(o.is_sandbox, false)
      AND NOT EXISTS (SELECT 1 FROM client_profile_links l WHERE l.profile_client_id = o.id)
      AND NOT EXISTS (
          SELECT 1 FROM trainer_client_match_dismissals d
          WHERE d.trainer_id = :tid AND d.client_id = c.id AND d.other_client_id = o.id
      )
"""
)


def _full_name(first: Any, last: Any) -> str:
    return " ".join(p for p in ((first or "").strip(), (last or "").strip()) if p)


async def list_client_matches(session: AsyncSession, trainer_id: int) -> list[dict[str, Any]]:
    """Open pairs for this trainer, newest self-registered client first."""
    r = await session.execute(text(_PAIRS_SQL + " ORDER BY c.id DESC, o.id"), {"tid": int(trainer_id)})
    return [
        {
            "client_id": int(row[0]),
            "client_name": _full_name(row[1], row[2]),
            "other_client_id": int(row[4]),
            "other_name": _full_name(row[5], row[6]),
            "phone": (row[7] or "").strip(),
        }
        for row in r.fetchall()
    ]


async def _pair_account_tid(
    session: AsyncSession, trainer_id: int, client_id: int, other_client_id: int
) -> int | None:
    r = await session.execute(
        text(_PAIRS_SQL + " AND c.id = :cid AND o.id = :oid LIMIT 1"),
        {"tid": int(trainer_id), "cid": int(client_id), "oid": int(other_client_id)},
    )
    row = r.fetchone()
    return int(row[3]) if row else None


async def resolve_client_match(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    other_client_id: int,
    decision: str,
) -> dict[str, Any]:
    """
    Apply the trainer's answer. Raises ``LookupError`` when the pair is not open for this
    trainer (already resolved, foreign client) and ``ValueError`` for an unknown decision or
    a full profile switcher. Caller must commit.
    """
    from src.application.client_profile_use_cases import link_guardian_profile
    from src.application.client_use_cases import merge_clients

    if decision not in MATCH_DECISIONS:
        raise ValueError("unknown_decision")
    account_tid = await _pair_account_tid(session, trainer_id, client_id, other_client_id)
    if account_tid is None:
        raise LookupError("match_not_found")

    if decision == "same":
        await merge_clients(
            session,
            int(other_client_id),
            int(client_id),
            merged_by_trainer_id=int(trainer_id),
            do_commit=False,
        )
        return {"decision": decision, "client_id": int(client_id)}

    if decision == "parent":
        if not await link_guardian_profile(session, account_tid, int(other_client_id)):
            raise ValueError("guardian_profile_limit_reached")
        return {"decision": decision, "client_id": int(other_client_id)}

    await session.execute(
        text(
            """
            INSERT INTO trainer_client_match_dismissals (trainer_id, client_id, other_client_id)
            VALUES (:tid, :cid, :oid)
            ON CONFLICT ON CONSTRAINT ux_client_match_dismissals_pair DO NOTHING
            """
        ),
        {"tid": int(trainer_id), "cid": int(client_id), "oid": int(other_client_id)},
    )
    return {"decision": decision, "client_id": int(client_id)}
