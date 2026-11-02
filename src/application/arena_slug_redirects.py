"""301 со старых slug точки (TASK-343): переименование и слияние дублей не ломают ссылки.

``/p/<город>/<старый slug>`` ищет запись здесь, когда в ``arena_profiles`` такого slug уже нет.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_HOPS = 5


class SlugError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def record_redirect(session: AsyncSession, *, city_id: int, old_slug: str, arena_id: int, reason: str) -> None:
    """Запомнить, куда вёл ``old_slug``. Повтор перенаправляет запись на новую точку."""
    old = (old_slug or "").strip().lower()
    if not old:
        return
    await session.execute(
        text(
            """INSERT INTO arena_slug_redirects (city_id, old_slug, arena_id, reason)
               VALUES (:c, :s, :a, :r)
               ON CONFLICT (city_id, old_slug) DO UPDATE SET arena_id = EXCLUDED.arena_id, reason = EXCLUDED.reason"""
        ),
        {"c": city_id, "s": old, "a": arena_id, "r": reason},
    )


async def repoint_redirects(session: AsyncSession, *, from_arena_id: int, to_arena_id: int) -> int:
    """Старые адреса слитой точки теперь ведут на ту, в которую её влили."""
    res = await session.execute(
        text("UPDATE arena_slug_redirects SET arena_id = :t WHERE arena_id = :f"),
        {"t": to_arena_id, "f": from_arena_id},
    )
    return int(res.rowcount or 0)


async def lookup_redirect(session: AsyncSession, city_id: int, slug: str) -> int | None:
    """Точка, на которую указывал ``slug`` (цепочка слияний разворачивается вызывающим)."""
    row = (
        await session.execute(
            text("SELECT arena_id FROM arena_slug_redirects WHERE city_id = :c AND old_slug = :s"),
            {"c": city_id, "s": (slug or "").strip().lower()},
        )
    ).first()
    return int(row[0]) if row else None


async def change_slug(session: AsyncSession, arena_id: int, new_slug: str) -> str | None:
    """Сменить slug профиля точки; старый уходит в редиректы. Возвращает старый slug или None, если не менялся."""
    new = (new_slug or "").strip().lower()
    if not new:
        raise SlugError("empty")
    row = (
        await session.execute(
            text("SELECT city_id, slug FROM arena_profiles WHERE arena_id = :a FOR UPDATE"), {"a": arena_id}
        )
    ).first()
    if row is None:
        raise SlugError("no_profile")
    city_id, old = int(row[0]), str(row[1])
    if old == new:
        return None
    taken = (
        await session.execute(
            text("SELECT arena_id FROM arena_profiles WHERE city_id = :c AND slug = :s"), {"c": city_id, "s": new}
        )
    ).first()
    if taken and int(taken[0]) != arena_id:
        raise SlugError("taken")
    await session.execute(text("UPDATE arena_profiles SET slug = :s WHERE arena_id = :a"), {"s": new, "a": arena_id})
    # Вернули себе старый адрес — редирект с него больше не нужен.
    await session.execute(
        text("DELETE FROM arena_slug_redirects WHERE city_id = :c AND old_slug = :s"), {"c": city_id, "s": new}
    )
    await record_redirect(session, city_id=city_id, old_slug=old, arena_id=arena_id, reason="rename")
    return old
