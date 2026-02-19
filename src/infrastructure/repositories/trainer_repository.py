"""
Infrastructure: trainer persistence. All SQL here; no business rules.
"""
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class TrainerRepository:
    """Trainer aggregate persistence: trainers, profiles, photos, services. Raw SQL only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_trainer(self) -> int:
        """Insert trainer row; returns new id."""
        r = await self._session.execute(text("INSERT INTO trainers (created_at) VALUES (now()) RETURNING id"))
        (tid,) = r.fetchone()
        return tid

    async def create_profile(
        self,
        trainer_id: int,
        *,
        first_name: str,
        last_name: str,
        age: int,
        experience_years: int | None = None,
        description: str | None = None,
        phone: str | None = None,
        contacts: str | None = None,
        education: str | None = None,
    ) -> None:
        """Insert trainer profile (one per trainer)."""
        await self._session.execute(
            text("""
                INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, experience_years, description, phone, contacts, education)
                VALUES (:tid, :fn, :ln, :age, :exp, :desc, :phone, :contacts, :edu)
            """),
            {
                "tid": trainer_id,
                "fn": first_name,
                "ln": last_name,
                "age": age,
                "exp": experience_years,
                "desc": description,
                "phone": phone,
                "contacts": contacts,
                "edu": education,
            },
        )

    async def set_trainer_services(self, trainer_id: int, service_ids: list[int]) -> None:
        """Replace trainer's services with given ids."""
        await self._session.execute(text("DELETE FROM trainer_services WHERE trainer_id = :tid"), {"tid": trainer_id})
        for sid in service_ids:
            await self._session.execute(
                text("INSERT INTO trainer_services (trainer_id, service_id) VALUES (:tid, :sid) ON CONFLICT DO NOTHING"),
                {"tid": trainer_id, "sid": sid},
            )

    async def get_by_id(self, trainer_id: int) -> dict[str, Any] | None:
        """Load trainer with profile, photos, service_ids; None if not found."""
        r = await self._session.execute(
            text("SELECT id, telegram_id, status, created_at FROM trainers WHERE id = :id"),
            {"id": trainer_id},
        )
        row = r.fetchone()
        if not row:
            return None
        out: dict[str, Any] = {
            "id": row[0],
            "telegram_id": row[1],
            "status": row[2],
            "created_at": str(row[3]) if row[3] else None,
        }
        rp = await self._session.execute(
            text("SELECT first_name, last_name, age, experience_years, description, phone, contacts, education FROM trainer_profiles WHERE trainer_id = :id"),
            {"id": trainer_id},
        )
        prof = rp.fetchone()
        out["profile"] = (
            {
                "first_name": prof[0], "last_name": prof[1], "age": prof[2], "experience_years": prof[3],
                "description": prof[4], "phone": prof[5], "contacts": prof[6], "education": prof[7],
            }
            if prof
            else None
        )
        rph = await self._session.execute(
            text("SELECT file_key, sort_order FROM trainer_photos WHERE trainer_id = :id ORDER BY sort_order"),
            {"id": trainer_id},
        )
        out["photos"] = [{"file_key": r[0], "sort_order": r[1]} for r in rph.fetchall()]
        rsv = await self._session.execute(text("SELECT service_id FROM trainer_services WHERE trainer_id = :id"), {"id": trainer_id})
        out["service_ids"] = [r[0] for r in rsv.fetchall()]
        return out

    async def exists(self, trainer_id: int) -> bool:
        """True if trainer exists."""
        r = await self._session.execute(text("SELECT 1 FROM trainers WHERE id = :id"), {"id": trainer_id})
        return r.fetchone() is not None

    async def update_profile(
        self,
        trainer_id: int,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        age: int | None = None,
        experience_years: int | None = None,
        description: str | None = None,
        phone: str | None = None,
        contacts: str | None = None,
        education: str | None = None,
    ) -> None:
        """Partial update of profile; only non-None fields are set."""
        updates: list[str] = []
        params: dict[str, Any] = {"id": trainer_id}
        if first_name is not None: updates.append("first_name = :fn"); params["fn"] = first_name
        if last_name is not None: updates.append("last_name = :ln"); params["ln"] = last_name
        if age is not None: updates.append("age = :age"); params["age"] = age
        if experience_years is not None: updates.append("experience_years = :exp"); params["exp"] = experience_years
        if description is not None: updates.append("description = :desc"); params["desc"] = description
        if phone is not None: updates.append("phone = :phone"); params["phone"] = phone
        if contacts is not None: updates.append("contacts = :contacts"); params["contacts"] = contacts
        if education is not None: updates.append("education = :edu"); params["edu"] = education
        if not updates:
            return
        await self._session.execute(
            text("UPDATE trainer_profiles SET " + ", ".join(updates) + ", updated_at = now() WHERE trainer_id = :id"),
            params,
        )

    async def list_trainers(
        self,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List trainers with optional status filter; returns id, telegram_id, status, first_name, last_name, age."""
        q = """
            SELECT t.id, t.telegram_id, t.status, p.first_name, p.last_name, p.age
            FROM trainers t
            LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
        """
        params: dict[str, Any] = {"lim": limit, "off": offset}
        if status is not None:
            q += " WHERE t.status = :status"
            params["status"] = status
        q += " ORDER BY t.id LIMIT :lim OFFSET :off"
        r = await self._session.execute(text(q), params)
        return [
            {
                "id": row[0],
                "telegram_id": row[1],
                "status": row[2],
                "first_name": row[3],
                "last_name": row[4],
                "age": row[5],
            }
            for row in r.fetchall()
        ]

    async def update_status(self, trainer_id: int, status: str) -> bool:
        """Set trainer status; returns True if row updated."""
        r = await self._session.execute(
            text("UPDATE trainers SET status = :status WHERE id = :id"),
            {"id": trainer_id, "status": status},
        )
        return r.rowcount > 0

    async def add_photo(self, trainer_id: int, file_key: str, sort_order: int = 0) -> None:
        """Append photo record for trainer."""
        await self._session.execute(
            text("INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:tid, :key, :ord)"),
            {"tid": trainer_id, "key": file_key, "ord": sort_order},
        )

    async def list_active_with_details(self, limit: int = 50) -> list[dict[str, Any]]:
        """Active trainers only, with profile, photos, service_ids. For client catalog."""
        r = await self._session.execute(
            text("""
                SELECT t.id, t.telegram_id,
                       p.first_name, p.last_name, p.age, p.experience_years,
                       p.description, p.phone, p.contacts, p.education
                FROM trainers t
                LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
                WHERE t.status = 'active'
                ORDER BY t.id
                LIMIT :lim
            """),
            {"lim": limit},
        )
        rows = r.fetchall()
        if not rows:
            return []
        ids = [row[0] for row in rows]
        if not ids:
            return []
        # Photos and services: IN clause (ids from our query, safe)
        placeholders = ", ".join(f":id{i}" for i in range(len(ids)))
        id_params = {f"id{i}": v for i, v in enumerate(ids)}
        rph = await self._session.execute(
            text(f"SELECT trainer_id, file_key, sort_order FROM trainer_photos WHERE trainer_id IN ({placeholders}) ORDER BY trainer_id, sort_order"),
            id_params,
        )
        photos_by_id: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
        for row in rph.fetchall():
            photos_by_id.setdefault(row[0], []).append({"file_key": row[1], "sort_order": row[2]})
        rsv = await self._session.execute(
            text(f"SELECT trainer_id, service_id FROM trainer_services WHERE trainer_id IN ({placeholders}) ORDER BY trainer_id"),
            id_params,
        )
        services_by_id: dict[int, list[int]] = {i: [] for i in ids}
        for row in rsv.fetchall():
            services_by_id[row[0]].append(row[1])
        out = []
        for row in rows:
            tid = row[0]
            out.append({
                "id": tid,
                "telegram_id": row[1],
                "profile": {
                    "first_name": row[2], "last_name": row[3], "age": row[4],
                    "experience_years": row[5], "description": row[6],
                    "phone": row[7], "contacts": row[8], "education": row[9],
                } if row[2] is not None else None,
                "photos": photos_by_id.get(tid, []),
                "service_ids": services_by_id.get(tid, []),
            })
        return out
