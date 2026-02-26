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
        city_id: int | None = None,
        experience_years: int | None = None,
        description: str | None = None,
        phone: str | None = None,
        contacts: str | None = None,
        education: str | None = None,
    ) -> None:
        """Insert trainer profile (one per trainer)."""
        await self._session.execute(
            text("""
                INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id, experience_years, description, phone, contacts, education)
                VALUES (:tid, :fn, :ln, :age, :city_id, :exp, :desc, :phone, :contacts, :edu)
            """),
            {
                "tid": trainer_id,
                "fn": first_name,
                "ln": last_name,
                "age": age,
                "city_id": city_id,
                "exp": experience_years,
                "desc": description,
                "phone": phone,
                "contacts": contacts,
                "edu": education,
            },
        )

    async def set_trainer_services(
        self,
        trainer_id: int,
        services: list[tuple[int, int | None]],
    ) -> None:
        """Replace trainer's services; each item is (service_id, price_cents or None)."""
        await self._session.execute(text("DELETE FROM trainer_services WHERE trainer_id = :tid"), {"tid": trainer_id})
        for sid, price_cents in services:
            await self._session.execute(
                text("""
                    INSERT INTO trainer_services (trainer_id, service_id, price_cents)
                    VALUES (:tid, :sid, :price_cents)
                    ON CONFLICT (trainer_id, service_id) DO UPDATE SET price_cents = EXCLUDED.price_cents
                """),
                {"tid": trainer_id, "sid": sid, "price_cents": price_cents},
            )

    async def set_trainer_arenas(self, trainer_id: int, arena_ids: list[int]) -> None:
        """Replace trainer's arenas with given ids."""
        await self._session.execute(text("DELETE FROM trainer_arenas WHERE trainer_id = :tid"), {"tid": trainer_id})
        for aid in arena_ids:
            await self._session.execute(
                text("""
                    INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)
                    ON CONFLICT (trainer_id, arena_id) DO NOTHING
                """),
                {"tid": trainer_id, "aid": aid},
            )

    async def get_by_id(self, trainer_id: int) -> dict[str, Any] | None:
        """Load trainer with profile, photos, service_ids; None if not found."""
        r = await self._session.execute(
            text("SELECT id, telegram_id, status, created_at, moderation_feedback FROM trainers WHERE id = :id"),
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
            "moderation_feedback": row[4],
        }
        rp = await self._session.execute(
            text("SELECT first_name, last_name, age, city_id, experience_years, description, phone, contacts, education, rating_avg, rating_count FROM trainer_profiles WHERE trainer_id = :id"),
            {"id": trainer_id},
        )
        prof = rp.fetchone()
        out["profile"] = (
            {
                "first_name": prof[0], "last_name": prof[1], "age": prof[2], "city_id": prof[3],
                "experience_years": prof[4], "description": prof[5], "phone": prof[6], "contacts": prof[7], "education": prof[8],
                "rating_avg": float(prof[9]) if prof[9] is not None else None,
                "rating_count": prof[10] or 0,
            }
            if prof
            else None
        )
        rph = await self._session.execute(
            text("SELECT file_key, file_key_list, sort_order FROM trainer_photos WHERE trainer_id = :id ORDER BY sort_order"),
            {"id": trainer_id},
        )
        out["photos"] = [{"file_key": r[0], "file_key_list": r[1], "sort_order": r[2]} for r in rph.fetchall()]
        rsv = await self._session.execute(
            text("SELECT service_id, price_cents FROM trainer_services WHERE trainer_id = :id ORDER BY service_id"),
            {"id": trainer_id},
        )
        service_rows = rsv.fetchall()
        out["service_ids"] = [r[0] for r in service_rows]
        if service_rows:
            s_placeholders = ", ".join(f":s{i}" for i in range(len(out["service_ids"])))
            s_params = {f"s{i}": r[0] for i, r in enumerate(service_rows)}
            r_sn = await self._session.execute(
                text(f"SELECT id, name FROM services WHERE id IN ({s_placeholders})"),
                s_params,
            )
            name_by_sid = {r[0]: (r[1] or "") for r in r_sn.fetchall()}
            out["services"] = [
                {
                    "service_id": r[0],
                    "service_name": name_by_sid.get(r[0], "—"),
                    "price_cents": r[1],
                    "price_byn": round(r[1] / 100, 2) if r[1] is not None else None,
                }
                for r in service_rows
            ]
        else:
            out["services"] = []
        rar = await self._session.execute(text("SELECT arena_id FROM trainer_arenas WHERE trainer_id = :id ORDER BY arena_id"), {"id": trainer_id})
        out["arena_ids"] = [r[0] for r in rar.fetchall()]
        if out["arena_ids"]:
            placeholders_ar = ", ".join(f":a{i}" for i in range(len(out["arena_ids"])))
            params_ar = {f"a{i}": aid for i, aid in enumerate(out["arena_ids"])}
            r_an = await self._session.execute(
                text(f"SELECT id, name FROM arenas WHERE id IN ({placeholders_ar})"),
                params_ar,
            )
            name_by_id = {r[0]: (r[1] or "") for r in r_an.fetchall()}
            out["arena_names"] = [name_by_id.get(aid, "—") for aid in out["arena_ids"]]
        else:
            out["arena_names"] = []
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
        city_id: int | None = None,
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
        if city_id is not None: updates.append("city_id = :city_id"); params["city_id"] = city_id
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

    async def set_moderation_feedback(self, trainer_id: int, feedback: str | None) -> bool:
        """Set or clear moderation_feedback (e.g. for 'needs edit'). Returns True if trainer exists."""
        r = await self._session.execute(
            text("UPDATE trainers SET moderation_feedback = :fb WHERE id = :id"),
            {"id": trainer_id, "fb": feedback},
        )
        return r.rowcount > 0

    async def add_photo(
        self, trainer_id: int, file_key: str, sort_order: int = 0, file_key_list: str | None = None
    ) -> None:
        """Append photo record for trainer. file_key_list = optional thumb for catalog list."""
        await self._session.execute(
            text("""
                INSERT INTO trainer_photos (trainer_id, file_key, file_key_list, sort_order)
                VALUES (:tid, :key, :key_list, :ord)
            """),
            {"tid": trainer_id, "key": file_key, "key_list": file_key_list, "ord": sort_order},
        )

    async def clear_photos(self, trainer_id: int) -> None:
        """Delete all photo records for trainer (DB-level only, storage cleanup is separate)."""
        await self._session.execute(
            text("DELETE FROM trainer_photos WHERE trainer_id = :tid"),
            {"tid": trainer_id},
        )

    # Bayesian prior for rating sort: score = (v/(v+m))*R + (m/(v+m))*C (m=10, C=4.0)
    _RATING_PRIOR_M = 10
    _RATING_PRIOR_C = 4.0

    async def list_active_with_details(
        self,
        limit: int = 50,
        offset: int = 0,
        city_id: int | None = None,
        service_id: int | None = None,
        arena_id: int | None = None,
        order_by: str = "rating",
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Active trainers with profile, photos, service_ids; paginated.
        arena_id: only trainers that have at least one slot in this arena.
        Returns (items, total_count).
        """
        base = """
            FROM trainers t
            LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
        """
        where = " WHERE t.status = 'active'"
        params: dict[str, Any] = {"lim": limit, "off": offset}
        if service_id is not None:
            base += " INNER JOIN trainer_services ts ON ts.trainer_id = t.id AND ts.service_id = :service_id"
            params["service_id"] = service_id
        if city_id is not None:
            where += " AND p.city_id = :city_id"
            params["city_id"] = city_id
        if arena_id is not None:
            base += " INNER JOIN trainer_arenas ta ON ta.trainer_id = t.id AND ta.arena_id = :arena_id"
            params["arena_id"] = arena_id

        # Total count with same filters
        count_q = "SELECT COUNT(DISTINCT t.id) " + base + where
        r_count = await self._session.execute(text(count_q), params)
        total = r_count.scalar() or 0

        sel = """
            SELECT DISTINCT t.id, t.telegram_id,
                   p.first_name, p.last_name, p.age, p.city_id, p.experience_years,
                   p.description, p.phone, p.contacts, p.education,
                   p.rating_avg, p.rating_count
        """
        if order_by == "rating":
            # Bayesian: (v/(v+m))*R + (m/(v+m))*C. Must be in SELECT when using DISTINCT (PG rule).
            # _has_rating: trainers with at least one vote go before those with zero (same rule for ORDER BY).
            score_expr = (
                "(COALESCE(p.rating_count, 0)::float / (COALESCE(p.rating_count, 0) + :m))"
                " * COALESCE(p.rating_avg, :c)"
                " + (CAST(:m AS double precision) / (COALESCE(p.rating_count, 0) + :m)) * :c"
            )
            has_rating_expr = "CASE WHEN COALESCE(p.rating_count, 0) > 0 THEN 1 ELSE 0 END"
            sel = f"""
            SELECT DISTINCT t.id, t.telegram_id,
                   p.first_name, p.last_name, p.age, p.city_id, p.experience_years,
                   p.description, p.phone, p.contacts, p.education,
                   p.rating_avg, p.rating_count,
                   ({has_rating_expr}) AS _has_rating,
                   ({score_expr}) AS _score
        """
            order = " ORDER BY _has_rating DESC, _score DESC NULLS LAST, t.id"
            params["m"] = self._RATING_PRIOR_M
            params["c"] = self._RATING_PRIOR_C
        else:
            order = " ORDER BY t.id"
        q = sel + base + where + order + " LIMIT :lim OFFSET :off"
        r = await self._session.execute(text(q), params)
        rows = r.fetchall()
        if not rows:
            return [], total
        ids = [row[0] for row in rows]
        placeholders = ", ".join(f":id{i}" for i in range(len(ids)))
        id_params = {f"id{i}": v for i, v in enumerate(ids)}
        rph = await self._session.execute(
            text(f"SELECT trainer_id, file_key, file_key_list, sort_order FROM trainer_photos WHERE trainer_id IN ({placeholders}) ORDER BY trainer_id, sort_order"),
            id_params,
        )
        photos_by_id: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
        for row in rph.fetchall():
            photos_by_id.setdefault(row[0], []).append({
                "file_key": row[1],
                "file_key_list": row[2],
                "sort_order": row[3],
            })
        rsv = await self._session.execute(
            text(f"SELECT trainer_id, service_id, price_cents FROM trainer_services WHERE trainer_id IN ({placeholders}) ORDER BY trainer_id, service_id"),
            id_params,
        )
        service_rows = rsv.fetchall()
        services_by_id: dict[int, list[int]] = {i: [] for i in ids}
        services_detail_by_id: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
        all_sids: set[int] = set()
        for row in service_rows:
            tid, sid, price_cents = row[0], row[1], row[2]
            services_by_id[tid].append(sid)
            all_sids.add(sid)
        service_names_by_id: dict[int, str] = {}
        if all_sids:
            s_placeholders = ", ".join(f":s{i}" for i in range(len(all_sids)))
            s_params = {f"s{i}": v for i, v in enumerate(all_sids)}
            r_sn = await self._session.execute(
                text(f"SELECT id, name FROM services WHERE id IN ({s_placeholders})"),
                s_params,
            )
            service_names_by_id = {r[0]: (r[1] or "") for r in r_sn.fetchall()}
        for row in service_rows:
            price_cents = row[2]
            services_detail_by_id[row[0]].append({
                "service_id": row[1],
                "service_name": service_names_by_id.get(row[1], "—"),
                "price_cents": price_cents,
                "price_byn": round(price_cents / 100, 2) if price_cents is not None else None,
            })
        rar = await self._session.execute(
            text(f"SELECT trainer_id, arena_id FROM trainer_arenas WHERE trainer_id IN ({placeholders}) ORDER BY trainer_id, arena_id"),
            id_params,
        )
        arenas_by_id: dict[int, list[int]] = {i: [] for i in ids}
        for row in rar.fetchall():
            arenas_by_id[row[0]].append(row[1])
        # Load arena names for all arena_ids on this page
        all_aids = list({aid for aids in arenas_by_id.values() for aid in aids})
        arena_names_by_id: dict[int, str] = {}
        if all_aids:
            a_placeholders = ", ".join(f":a{i}" for i in range(len(all_aids)))
            a_params = {f"a{i}": v for i, v in enumerate(all_aids)}
            r_an = await self._session.execute(
                text(f"SELECT id, name FROM arenas WHERE id IN ({a_placeholders})"),
                a_params,
            )
            for arow in r_an.fetchall():
                arena_names_by_id[arow[0]] = arow[1] or ""
        out = []
        for row in rows:
            tid = row[0]
            arena_ids = arenas_by_id.get(tid, [])
            arena_names = [arena_names_by_id.get(aid, "—") for aid in arena_ids]
            out.append({
                "id": tid,
                "telegram_id": row[1],
                "profile": {
                    "first_name": row[2], "last_name": row[3], "age": row[4], "city_id": row[5],
                    "experience_years": row[6], "description": row[7],
                    "phone": row[8], "contacts": row[9], "education": row[10],
                    "rating_avg": float(row[11]) if row[11] is not None else None,
                    "rating_count": row[12] or 0,
                } if row[2] is not None else None,
                "photos": photos_by_id.get(tid, []),
                "service_ids": services_by_id.get(tid, []),
                "services": services_detail_by_id.get(tid, []),
                "arena_ids": arena_ids,
                "arena_names": arena_names,
            })
        return out, total

    async def add_rating(
        self,
        trainer_id: int,
        client_telegram_id: int,
        rating: int,
        review_text: str | None = None,
    ) -> bool:
        """Upsert rating 1–5 and optional review text; update profile aggregates. Returns True if trainer exists."""
        if not await self.exists(trainer_id):
            return False
        rating_val = max(1, min(5, rating))
        await self._session.execute(
            text("""
                INSERT INTO trainer_ratings (trainer_id, client_telegram_id, rating, review_text)
                VALUES (:tid, :ctid, :rating, :review_text)
                ON CONFLICT (trainer_id, client_telegram_id)
                DO UPDATE SET rating = EXCLUDED.rating,
                  review_text = COALESCE(EXCLUDED.review_text, trainer_ratings.review_text)
            """),
            {"tid": trainer_id, "ctid": client_telegram_id, "rating": rating_val, "review_text": review_text},
        )
        r = await self._session.execute(
            text("SELECT AVG(rating)::float, COUNT(*)::int FROM trainer_ratings WHERE trainer_id = :tid"),
            {"tid": trainer_id},
        )
        row = r.fetchone()
        avg_val = row[0] if row and row[0] is not None else None
        count_val = (row[1] or 0) if row else 0
        await self._session.execute(
            text("""
                UPDATE trainer_profiles SET rating_avg = :avg, rating_count = :cnt, updated_at = now()
                WHERE trainer_id = :tid
            """),
            {"tid": trainer_id, "avg": avg_val, "cnt": count_val},
        )
        return True
