# Места от людей, этап 1 — план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (или executing-plans) to implement this plan task-by-task.

**Goal:** человек на сайте или в Mini App предлагает место (каток, открытый каток, магазин, школа) в любом городе, в том числе новом; владелец разбирает заявку в админском Mini App, переписывается с автором через клиентского бота и одобряет — место и город появляются в каталоге без ручного ввода.

**Architecture:** сырая заявка живёт в `place_suggestions` и не трогает каталог до одобрения. Одобрение — одна транзакция поверх существующих хелперов (`ensure_arena_profile`, логика городов из `trainer_city_create_use_cases`). Публичный API без логина (honeypot + отдельный rate-limit бакет), Mini App — тот же use case с автором из initData. Админка — отдельный роутер и отдельная страница `admin-*.html`, как `admin_ice_inbox`. Форма одна: общий JS-модуль для сайта и Mini App.

**Tech Stack:** FastAPI, SQLAlchemy async + raw `text()` SQL, Alembic, aiogram 3, статические HTML-шаблоны с `__PLACEHOLDER__`, vanilla JS, pytest + httpx `AsyncClient`.

**Дизайн:** `docs/plans/2026-10-28-place-suggestions-design.md`, PDEC-028. Макет (холст): https://claude.ai/artifact/NC8eGQYKUPPm6d2mntbc7i

**Ветка:** всё коммитится в `release/29.10.26` (папка `/Users/maksimvasilenko/Projects/trainer-crm-batch`). Не пушить без явного «мержи». В индекс добавлять только явные пути.

**Правила проверки:**
- После каждой задачи — только затронутые тесты (`pytest <файл> -q`). Полный `pytest tests/ -m "not collective" -q` — один раз перед пушем.
- Миграции — только на тестовой БД. `DATABASE_URL_SYNC` из `.env` смотрит на общую dev-БД других сессий: переопределять при `alembic upgrade`.

---

## Контракты (общие для всех задач)

**Типы места (`kind`)** = значения `venue_type`: `ice` · `outdoor` · `shop` · `school`.

**Статусы:** `new` → `needs_info` → `approved` | `rejected` | `duplicate`. Закрытые = последние три.

**`details` (JSONB), все поля необязательны, строки обрезаны:**

| ключ | тип | лимит | для kind |
|---|---|---|---|
| `price_adult`, `price_child`, `price_rental` | str | 20 | ice, outdoor |
| `hours` | str | 300 | все |
| `services` | list ⊂ {`sharpening`,`rental`,`sale`} | — | shop |
| `disciplines` | list ⊂ {`figure`,`hockey`} | — | school |
| `age` | str | 100 | school |
| `link` | str | 300 | все |
| `more` | str | 1000 | все |

**Контакт:** свободная строка ≤120 → `contact_kind` = `email` | `telegram` | `other`.

**Новый город в заявке:** `city_id` NULL, заполнены `new_city_name`, `new_city_country` (ISO2), опционально `new_city_region`, `new_city_lat/lon`.

---

### Task 1: Тип места `school`

**Files:**
- Modify: `src/shared/venue_types.py`
- Test: `tests/unit/test_venue_types_school.py` (create)

**Step 1: Write the failing test**

```python
from src.shared.venue_types import (
    DEFAULT_HIDDEN_VENUE_TYPES, TRAINER_VENUE_TYPE_KEYS, VENUE_TYPE_KEYS,
    normalize_venue_type, venue_type_noun,
)


def test_school_is_a_known_venue_type():
    assert "school" in VENUE_TYPE_KEYS
    assert normalize_venue_type("school") == "school"
    assert venue_type_noun("school")


def test_school_is_not_offered_to_trainers_and_not_hidden_by_default():
    assert "school" not in TRAINER_VENUE_TYPE_KEYS
    assert "school" not in DEFAULT_HIDDEN_VENUE_TYPES
```

**Step 2:** `pytest tests/unit/test_venue_types_school.py -q` → FAIL (`school` нет).

**Step 3:** в `VENUE_TYPES` добавить запись по образцу `shop`: `{"key": "school", "chip": "Школы", "noun": "школа", "genitive": "школы", "icon": "<имя иконки>"}`. Иконку «школа» (шапочка, линия 1.6, viewBox 24) добавить в `src/application/catalog_icons.py` рядом с `_SHARPEN` — путь из макета: `M2.5 9L12 4.5 21.5 9 12 13.5z`, `M6.5 11v4.5c1.6 1.6 3.4 2.3 5.5 2.3s3.9-.7 5.5-2.3V11`, `M21.5 9v5`. Исключить `school` из `TRAINER_VENUE_TYPE_KEYS` так же, как исключён `shop`. Проверить грепом, нет ли `CHECK`-ограничения на `arenas.venue_type` в миграциях (`grep -rn "venue_type IN" migrations/`); если есть — расширить его в миграции Task 2.

**Step 4:** тест → PASS; плюс `pytest tests -q -k venue_type` (существующие тесты типов).

**Step 5:** `git add src/shared/venue_types.py src/application/catalog_icons.py tests/unit/test_venue_types_school.py && git commit -m "feat(catalog): school venue type"`

---

### Task 2: Миграция и модели

**Files:**
- Create: `migrations/versions/0279_place_suggestions.py`
- Modify: `src/infrastructure/db/models.py` (рядом с `IceCityInterest`, ~:704; `City` ~:196; `ArenaProfile` ~:278)
- Test: `tests/integration/test_migration_0279_place_suggestions.py` (create)

**Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_place_suggestions_tables_exist(db_session):
    cols = {
        r[0] for r in (await db_session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='place_suggestions'"
        ))).fetchall()
    }
    assert {"id", "kind", "status", "city_id", "new_city_name", "name", "details",
            "contact", "contact_kind", "author_telegram_id", "bind_token",
            "target_arena_id", "result_arena_id", "source", "created_at"} <= cols
    msg_cols = {
        r[0] for r in (await db_session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='place_suggestion_messages'"
        ))).fetchall()
    }
    assert {"suggestion_id", "direction", "body", "created_at"} <= msg_cols
    city_cols = {
        r[0] for r in (await db_session.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='cities'"
        ))).fetchall()
    }
    assert {"latitude", "longitude", "region"} <= city_cols
```

**Step 2:** прогнать на тестовой БД → FAIL.

**Step 3: Migration** (стиль `0277_arena_schedule_inbox.py`):

```python
"""place_suggestions: user-submitted places + moderation thread; city coords.

Revision ID: 0279_place_suggestions
Revises: 0278_ice_session_events
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0279_place_suggestions"
down_revision = "0278_ice_session_events"
branch_labels = None
depends_on = None

_KINDS = ("ice", "outdoor", "shop", "school")
_STATUSES = ("new", "needs_info", "approved", "rejected", "duplicate")
_SOURCES = ("site", "miniapp")
_CONTACT_KINDS = ("email", "telegram", "other")
_DIRECTIONS = ("to_author", "from_author", "note")


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "place_suggestions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("new_city_name", sa.String(120), nullable=True),
        sa.Column("new_city_country", sa.String(2), nullable=True),
        sa.Column("new_city_region", sa.String(160), nullable=True),
        sa.Column("new_city_lat", sa.Float(), nullable=True),
        sa.Column("new_city_lon", sa.Float(), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(300), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("contact", sa.String(120), nullable=True),
        sa.Column("contact_kind", sa.String(16), nullable=True),
        sa.Column("author_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("bind_token", sa.String(32), nullable=True, unique=True),
        sa.Column("target_arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("result_arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reject_reason", sa.String(32), nullable=True),
        sa.Column("client_ip_hash", sa.String(64), nullable=True),
        sa.CheckConstraint(_in("kind", _KINDS), name="ck_place_suggestions_kind"),
        sa.CheckConstraint(_in("status", _STATUSES), name="ck_place_suggestions_status"),
        sa.CheckConstraint(_in("source", _SOURCES), name="ck_place_suggestions_source"),
        sa.CheckConstraint(f"contact_kind IS NULL OR {_in('contact_kind', _CONTACT_KINDS)}",
                           name="ck_place_suggestions_contact_kind"),
        sa.CheckConstraint("city_id IS NOT NULL OR new_city_name IS NOT NULL",
                           name="ck_place_suggestions_city"),
    )
    op.create_index("ix_place_suggestions_status", "place_suggestions", ["status", "created_at"])
    op.create_index("ix_place_suggestions_author", "place_suggestions", ["author_telegram_id"])

    op.create_table(
        "place_suggestion_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("suggestion_id", sa.BigInteger(),
                  sa.ForeignKey("place_suggestions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.CheckConstraint(_in("direction", _DIRECTIONS), name="ck_place_suggestion_messages_direction"),
    )
    op.create_index("ix_place_suggestion_messages_sid", "place_suggestion_messages", ["suggestion_id", "created_at"])

    op.add_column("cities", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("cities", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("cities", sa.Column("region", sa.String(160), nullable=True))
    op.add_column("arena_profiles", sa.Column(
        "visitor_prices", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("arena_profiles", "visitor_prices")
    op.drop_column("cities", "region")
    op.drop_column("cities", "longitude")
    op.drop_column("cities", "latitude")
    op.drop_index("ix_place_suggestion_messages_sid", table_name="place_suggestion_messages")
    op.drop_table("place_suggestion_messages")
    op.drop_index("ix_place_suggestions_author", table_name="place_suggestions")
    op.drop_index("ix_place_suggestions_status", table_name="place_suggestions")
    op.drop_table("place_suggestions")
```

Перед написанием проверить: `ls migrations/versions | sort | tail -3` — head всё ещё `0278_ice_session_events`. Если кто-то добавил 0279, взять следующий номер.

**Models:** `PlaceSuggestion` и `PlaceSuggestionMessage` в стиле `IceCityInterest` (`Mapped[...] = mapped_column(...)`, JSONB для `details`); в `City` — `latitude`, `longitude`, `region`; в `ArenaProfile` — `visitor_prices: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)`.

**Step 4:** `alembic upgrade head` на тестовой БД, тест → PASS. Проверить `alembic downgrade -1 && alembic upgrade head`.

**Step 5:** commit миграции, models.py и теста.

---

### Task 3: Нормализация заявки (чистые функции)

**Files:**
- Create: `src/shared/place_suggestion.py`
- Test: `tests/unit/test_place_suggestion_normalize.py`

**Step 1: Write the failing test**

```python
import pytest

from src.shared.place_suggestion import classify_contact, normalize_details, PlaceSuggestionError, validate_core


def test_contact_kinds():
    assert classify_contact("anna@mail.ru") == ("anna@mail.ru", "email")
    assert classify_contact("@anna_skate") == ("@anna_skate", "telegram")
    assert classify_contact("anna_skate") == ("@anna_skate", "telegram")
    assert classify_contact("+7 900 000-00-00") == ("+7 900 000-00-00", "other")
    assert classify_contact("   ") == (None, None)


def test_details_keep_only_fields_of_kind_and_trim():
    d = normalize_details("shop", {
        "services": ["sharpening", "rental", "hack"], "price_adult": "10",
        "hours": "  пн–сб 10–20  ", "more": "x" * 2000, "disciplines": ["figure"],
    })
    assert d == {"services": ["sharpening", "rental"], "hours": "пн–сб 10–20", "more": "x" * 1000}


def test_details_rink_prices():
    d = normalize_details("ice", {"price_adult": " 500 ₽ ", "price_child": "", "services": ["sale"]})
    assert d == {"price_adult": "500 ₽"}


def test_core_requires_kind_city_and_name():
    with pytest.raises(PlaceSuggestionError):
        validate_core(kind="bar", city_id=1, new_city_name=None, name="X")
    with pytest.raises(PlaceSuggestionError):
        validate_core(kind="ice", city_id=None, new_city_name="  ", name="X")
    with pytest.raises(PlaceSuggestionError):
        validate_core(kind="ice", city_id=1, new_city_name=None, name="  ")
    assert validate_core(kind="ice", city_id=None, new_city_name=" Уфа ", name=" Арена ") == ("Уфа", "Арена")
```

**Step 2:** → FAIL (модуля нет).

**Step 3: Implementation**

```python
"""Validation and normalization of a user-submitted place (PDEC-028). Pure, no I/O."""
from __future__ import annotations

import re
from typing import Any

KINDS = ("ice", "outdoor", "shop", "school")
RINK_KINDS = frozenset({"ice", "outdoor"})
SHOP_SERVICES = ("sharpening", "rental", "sale")
SCHOOL_DISCIPLINES = ("figure", "hockey")

_COMMON_TEXT = {"hours": 300, "link": 300, "more": 1000}
_KIND_TEXT = {
    "ice": {"price_adult": 20, "price_child": 20, "price_rental": 20},
    "outdoor": {"price_adult": 20, "price_child": 20, "price_rental": 20},
    "shop": {},
    "school": {"age": 100},
}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TG_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")


class PlaceSuggestionError(ValueError):
    """User-facing validation error; message is Russian and safe to show."""


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def classify_contact(raw: str | None) -> tuple[str | None, str | None]:
    s = _clean(raw, 120)
    if not s:
        return None, None
    if _EMAIL_RE.match(s):
        return s, "email"
    m = _TG_RE.match(s)
    if m:
        return f"@{m.group(1)}", "telegram"
    return s, "other"


def normalize_details(kind: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    out: dict[str, Any] = {}
    for key, limit in {**_KIND_TEXT.get(kind, {}), **_COMMON_TEXT}.items():
        v = _clean(raw.get(key), limit)
        if v:
            out[key] = v
    if kind == "shop":
        picked = [s for s in SHOP_SERVICES if s in (raw.get("services") or [])]
        if picked:
            out["services"] = picked
    if kind == "school":
        picked = [s for s in SCHOOL_DISCIPLINES if s in (raw.get("disciplines") or [])]
        if picked:
            out["disciplines"] = picked
    return out


def validate_core(*, kind: str, city_id: int | None, new_city_name: str | None, name: str) -> tuple[str | None, str]:
    if kind not in KINDS:
        raise PlaceSuggestionError("Выберите, что это за место.")
    city = _clean(new_city_name, 120) or None
    if city_id is None and not city:
        raise PlaceSuggestionError("Укажите город.")
    nm = _clean(name, 200)
    if not nm:
        raise PlaceSuggestionError("Напишите название или пару слов о месте.")
    return city, nm
```

**Step 4:** → PASS. **Step 5:** commit.

---

### Task 4: Создание заявки и уведомление админу

**Files:**
- Create: `src/application/place_suggestion_use_cases.py`
- Create: `src/application/place_suggestion_notify.py`
- Test: `tests/application/test_place_suggestion_create.py`

**Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import text

from src.application.place_suggestion_use_cases import create_place_suggestion
from src.shared.place_suggestion import PlaceSuggestionError


@pytest.mark.asyncio
async def test_create_for_new_city_stores_raw_and_token(db_session):
    res = await create_place_suggestion(
        db_session, source="site", kind="ice", city_id=None,
        new_city={"name": "Уфа", "country": "ru", "region": "Башкортостан", "lat": 54.73, "lon": 55.96},
        name="Ледовая арена", address=None, details={"price_adult": "500"},
        contact="@anna_skate", author_telegram_id=None, client_ip="1.2.3.4",
    )
    row = (await db_session.execute(text(
        "SELECT status, new_city_name, new_city_country, contact_kind, details->>'price_adult', bind_token "
        "FROM place_suggestions WHERE id=:id"), {"id": res["id"]})).one()
    assert row[0] == "new" and row[1] == "Уфа" and row[2] == "RU" and row[3] == "telegram"
    assert row[4] == "500" and row[5] and res["bind_token"] == row[5]


@pytest.mark.asyncio
async def test_create_rejects_unknown_city_id(db_session):
    with pytest.raises(PlaceSuggestionError):
        await create_place_suggestion(
            db_session, source="site", kind="ice", city_id=999999, new_city=None,
            name="X", address=None, details={}, contact=None, author_telegram_id=None, client_ip=None,
        )


@pytest.mark.asyncio
async def test_create_from_miniapp_has_author_and_no_token(db_session, monkeypatch):
    sent = []
    monkeypatch.setattr("src.application.place_suggestion_use_cases.notify_admins_new_place_suggestion",
                        lambda sid: sent.append(sid) or _noop())
    city_id = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar_one()
    res = await create_place_suggestion(
        db_session, source="miniapp", kind="shop", city_id=city_id, new_city=None,
        name="Заточка у арены", address=None, details={"services": ["sharpening"]},
        contact=None, author_telegram_id=1304982166, client_ip=None,
    )
    assert res["bind_token"] is None
    assert sent == [res["id"]]


async def _noop():
    return None
```

(Если в тестовой БД нет городов — вставить город в тесте: `INSERT INTO cities (name, sort_order, is_active, country) VALUES ('Тестград', 1, true, 'BY') RETURNING id`.)

**Step 2:** → FAIL.

**Step 3: Implementation** — `create_place_suggestion(session, *, source, kind, city_id, new_city, name, address, details, contact, author_telegram_id, client_ip) -> dict`:
1. `validate_core(...)`, `normalize_details(kind, details)`, `classify_contact(contact)`.
2. Если `city_id` задан — проверить `SELECT 1 FROM cities WHERE id=:id` (любой `is_active`), иначе `PlaceSuggestionError("Город не найден.")`. Если `new_city` задан — сначала поискать город по имени без учёта регистра (переиспользовать `_find_city_by_name_insensitive` из `trainer_city_create_use_cases.py:28`; вынести его в публичное имя `find_city_by_name_insensitive`, старое оставить алиасом) и, если нашёлся, записать `city_id` вместо нового города.
3. `bind_token = secrets.token_urlsafe(12)` только если `author_telegram_id is None` (сайт); иначе `None`.
4. `client_ip_hash = sha256(ip + settings.secret_key)` — для лимитов/аналитики, сам IP не храним (взять существующий секрет из `src/shared/config.py`; если нет подходящего — хэшировать без соли, отметить в коммите).
5. `INSERT ... RETURNING id`, `await session.commit()`.
6. После коммита: `try: await notify_admins_new_place_suggestion(sid) except Exception: logger.exception(...)` — как в `trainer_arena_create_use_cases.py:266-271`.
7. Вернуть `{"id": sid, "bind_token": bind_token}`.

`place_suggestion_notify.py` — по образцу `src/application/admin_arena_notify.py:47`:
- текст: `Новая заявка №{id} · {kind_label} · {город}{" (новый город)" если new_city} · {"есть цены, " если price_*}{"есть контакт" если contact или author}`; всё через `html.escape`;
- кнопки: `[Открыть]` = `WebAppInfo(url=f"{base}/webapp/admin-place-suggestions?id={id}")` (base — как в `admin_handlers.py:619-636`), и `[Одобрить как есть]` с `callback_data=f"{PLACE_SUGGEST_APPROVE_PREFIX}{id}"` — только если `find_possible_duplicate_arenas` пуст (или город новый) и `name` не пуст.
- префикс `PLACE_SUGGEST_APPROVE_PREFIX = "psa:"` положить в `src/shared/place_suggestion.py`, чтобы не дублировать константу (в отличие от `ADMIN_ARENA_APPROVE_PREFIX`).

**Step 4:** → PASS. **Step 5:** commit.

---

### Task 5: Поиск города (наши + геокодер)

**Files:**
- Create: `src/application/place_suggestion_city_search.py`
- Test: `tests/application/test_place_suggestion_city_search.py`

**Контракт:** `search_cities(session, q, *, geocode=nominatim_cities) -> list[dict]`, элемент: `{"city_id": int|None, "name", "region", "country", "lat", "lon", "is_new": bool}`. Сначала наши (`cities.is_active` и `country = ANY(:ice_countries)`, `name ILIKE :q || '%'`, до 5), затем геокодер, исключая совпавшие по имени+стране с нашими; всего ≤6. `q` короче 2 символов → только наши.

**Step 1: tests** — (а) наш город находится по префиксу без геокодера; (б) результат геокодера с тем же именем, что наш город, отбрасывается; (в) сбой геокодера (исключение) → только наши, без ошибки. Геокодер подменяется параметром `geocode=`.

**Step 3: `nominatim_cities(q)`** — `httpx.AsyncClient(timeout=4)`, `NOMINATIM_SEARCH` из `trainer_arena_create_use_cases.py:28`, params `{"q": q, "format": "jsonv2", "limit": "6", "addressdetails": "1", "featureType": "city", "accept-language": "ru"}`, тот же `User-Agent` (вынести сборку UA в общую функцию рядом с `NOMINATIM_SEARCH`). Из `address` взять `city|town|village`, `state` → region, `country_code.upper()` → country. In-memory кэш `{q_lower: (ts, result)}` на 1 час и не более 1 запроса в секунду на процесс (политика Nominatim): если лимит исчерпан — вернуть `[]`.

**Step 4:** → PASS. **Step 5:** commit.

---

### Task 6: Публичный API

**Files:**
- Create: `src/api/routes/public_place_suggestions.py`
- Modify: `src/api/app.py` (include_router рядом с `public_arenas`), `src/api/middleware/http_limits.py:67-102` (бакет `suggest`), `src/shared/config.py:118-150` (`api_rate_limit_suggest_*`)
- Test: `tests/api/test_public_place_suggestions.py`

**Endpoints:**
- `GET /api/public/place-suggestions/cities?q=` → `{"items": [...]}` (Task 5).
- `POST /api/public/place-suggestions` body:

```python
class NewCityBody(BaseModel):
    name: str = Field(max_length=120)
    country: str = Field(min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=160)
    lat: float | None = None
    lon: float | None = None


class PlaceSuggestionBody(BaseModel):
    kind: str = Field(max_length=16)
    city_id: int | None = None
    new_city: NewCityBody | None = None
    name: str = Field(max_length=200)
    address: str | None = Field(default=None, max_length=300)
    details: dict[str, Any] = Field(default_factory=dict)
    contact: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=200)  # honeypot — must stay empty
```

  Ответ `200 {"ok": true, "id": N, "telegram_link": "https://t.me/<client_bot_username>?start=sg_<token>" | null}` (ссылка — если `settings.client_bot_username` задан). Honeypot непустой → `400` (как `public.py:403`). `PlaceSuggestionError` → `422 {"detail": str(e)}`. `Cache-Control: no-store`.

- Rate limit: в `rate_limit_bucket_for_path` — `if path.startswith("/api/public/place-suggestions"): return "suggest"`; лимит по умолчанию 10 POST/час и 60 GET/мин на IP (два бакета, если GET и POST нельзя различить по пути — тогда один бакет 60/мин, а 10/час для POST — через `RateLimiter` внутри хендлера, как `public.py:75`).

**Tests** (образец `tests/api/test_public_arenas.py:742-787`, `AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`, фикстуры `app_use_test_db, db_session`): 200 и строка в БД; honeypot → 400; пустое имя → 422 с русским текстом; 11-й POST с одного `X-Forwarded-For` → 429; `telegram_link` содержит `start=sg_`.

**Step 5:** commit.

---

### Task 7: Заявка из Mini App

**Files:**
- Modify: `src/api/routes/webapp.py` — нет: новый модуль `src/api/routes/webapp_place_suggestions.py` с `router = APIRouter(tags=["webapp-place-suggestions"])`, подключить через `router.include_router(...)` там же, где `_admin_ice_inbox_router` (`webapp.py:11265`).
- Test: `tests/api/test_webapp_place_suggestions.py`

`POST /api/webapp/place-suggestions`, тело — `PlaceSuggestionBody` без `website`, `principal = Depends(get_optional_client_miniapp_principal)` (`miniapp_auth/deps.py:145`); `author_telegram_id = principal.user_id` если `principal.platform == "telegram"`; `source="miniapp"`. Ответ `{"ok": true, "id": N}`.

Tests: с подписанным initData (`_build_signed_init_data` из `tests/shared/test_telegram_webapp.py:16`, monkeypatch `Settings` как в `tests/api/test_ice_invites.py:487-500`) → `author_telegram_id` записан; без initData → 200, автор NULL.

**Step 5:** commit.

---

### Task 8: Привязка автора с сайта к Telegram (`start=sg_<token>`)

**Files:**
- Modify: `src/bot/handlers/client_handlers.py` — обработчик `/start` с payload (найти существующий разбор deep-link payload: `grep -n "CommandStart\|start_param\|command.args" src/bot/handlers/client_handlers.py`)
- Modify: `src/application/place_suggestion_use_cases.py` — `bind_suggestion_author(session, token, telegram_id) -> dict | None`
- Test: `tests/application/test_place_suggestion_bind.py`

`bind_suggestion_author`: `UPDATE place_suggestions SET author_telegram_id=:tid, bind_token=NULL, updated_at=now() WHERE bind_token=:t AND author_telegram_id IS NULL RETURNING id, name, status`. Повторное использование токена → `None`.

Бот на успех: «Спасибо! Заявка №{id} «{name}» у нас. Если будут вопросы — напишем здесь, и сообщим, когда место появится в Glide.» На `None`: «Эта ссылка уже использована или устарела.» Payload `sg_` обработать до остальных веток `/start`.

Tests: привязка один раз; второй вызов → None; заявка с автором из Mini App не перепривязывается.

**Step 5:** commit.

---

### Task 9: Админские use cases

**Files:**
- Modify: `src/application/place_suggestion_use_cases.py`
- Test: `tests/application/test_place_suggestion_admin.py`

Функции:
- `list_place_suggestions(session, *, tab: Literal["new","waiting","closed"], limit=50)` — `new`→`status='new'`, `waiting`→`needs_info`, `closed`→остальные; сорт `created_at DESC`; в строке: `id, kind, status, name, city_label, is_new_city, has_contact, created_at`.
- `get_place_suggestion(session, sid)` — всё + `messages` (ASC) + `similar`: если `city_id` — `find_possible_duplicate_arenas(session, city_id, name=..., latitude=..., longitude=...)` (`trainer_arena_create_use_cases.py:119`), иначе `[]`.
- `patch_place_suggestion(session, sid, fields)` — разрешённые ключи: `name, address, latitude, longitude, details, city_id, new_city_name, new_city_country, new_city_region, new_city_lat, new_city_lon`; только для открытых статусов.
- `approve_place_suggestion(session, sid) -> {"arena_id", "city_id", "slug"}`, одна транзакция:
  1. Город: `city_id` или создать `INSERT INTO cities (name, sort_order, is_active, country, latitude, longitude, region) VALUES (..., 9999, true, ...)`; если город с таким именем уже есть (`find_city_by_name_insensitive`) — использовать его и включить `is_active=true`. **Исключение: Москву не включать** (PDEC-018) — если найденный город неактивен и это не новый город, не трогать `is_active` и вернуть предупреждение `"city_kept_inactive": true`.
  2. Арена: `INSERT INTO arenas (city_id, name, address, latitude, longitude, venue_type, is_active, is_confirmed, confirmed_at) VALUES (..., true, true, now()) RETURNING id` (сверить обязательные колонки `arenas` в `models.py:221-258`; `confirmed_by_admin_id` — id админа из principal).
  3. `slug = await ensure_arena_profile(session, arena_id, city_id=..., name=...)` (`arena_profile.py:388`).
  4. Если в `details` есть цены → `UPDATE arena_profiles SET visitor_prices = :json` (`{"adult","child","rental","currency": "RUB"|"BYN", "source": "visitors"}`, валюта — через `src/shared/currency.resolve_currency` по стране города); если есть `hours` → `opening_hours`, если `link` похож на URL → `website_url`, если похож на телефон → `phone` (проверить форматы этих колонок в `models.py:278-341` и в `admin-arena-form-overwrites` — часы только в daily-формате: если формат не совпадает, класть `hours` в `price_note`/заметку, а не в `opening_hours`). Для `kind="shop"` — услуги в существующее поле услуг магазина (см. `src/application/catalog_shops_import.py`).
  5. Для городов без расписания: `schedule_mode='phone'`.
  6. `UPDATE place_suggestions SET status='approved', result_arena_id=..., city_id=..., closed_at=now()`; commit.
  7. После коммита — уведомить автора (Task 11), ошибки только логировать.
- `reject_place_suggestion(session, sid, reason)` — `reason ∈ {"spam","not_ice","closed","other"}`.
- `mark_duplicate(session, sid, target_arena_id, copy_fields: list[str])` — `copy_fields ⊂ {"phone","website_url","visitor_prices","opening_hours"}`; копировать только в пустые поля профиля цели; статус `duplicate`.

Tests: approve нового города создаёт активный город с координатами, арену `is_confirmed`, профиль со `slug` и `visitor_prices`; approve в существующем неактивном городе не включает его; reject/duplicate закрывают заявку; patch закрытой → ошибка; duplicate не перезаписывает заполненный телефон.

**Step 5:** commit (можно двумя коммитами: approve отдельно).

---

### Task 10: Админский API

**Files:**
- Create: `src/api/routes/admin_place_suggestions.py` (образец — `src/api/routes/admin_ice_inbox.py`), подключить в `webapp.py` рядом с `_admin_ice_inbox_router`
- Test: `tests/api/test_admin_place_suggestions.py` (`patch_admin_principal()` из `tests/api/test_city_picks_api.py:29`)

Все под `Depends(get_admin_miniapp_principal)`, префикс `/api/webapp/admin/place-suggestions`:
- `GET ?tab=new|waiting|closed` → `{"items": [...]}`
- `GET /{id}` → деталь
- `PATCH /{id}` → деталь
- `POST /{id}/approve` → `{"arena_id","city_id","slug","url"}` (`url` = `/p/{city_slug}/{slug}`)
- `POST /{id}/reject` `{"reason"}`
- `POST /{id}/duplicate` `{"target_arena_id","copy_fields"}`
- `POST /{id}/messages` `{"body"}` → Task 11; ставит `needs_info`

Tests: 403 без админа; полный цикл new → message → approve.

**Step 5:** commit.

---

### Task 11: Переписка с автором

**Files:**
- Modify: `src/application/place_suggestion_use_cases.py` — `send_message_to_author`, `capture_author_reply`, `notify_author_approved`
- Modify: `src/bot/handlers/client_handlers.py:3519` (`fallback`)
- Test: `tests/application/test_place_suggestion_thread.py`

- `send_message_to_author(session, sid, body)`: если `author_telegram_id` есть → `send_client_plain_notification(telegram_chat_id=..., html_text=f"Glide · заявка №{sid} «{escape(name)}»\n\n{escape(body)}\n\nОтветьте прямо здесь.")` (`trainer_relay_delivery.py:88`); записать `to_author`; статус → `needs_info`. Если автора нет, но `contact_kind='telegram'` или `email` → `{"delivered": false, "contact": ...}` (админка показывает «Скопировать контакт»: бот не может первым написать по нику). Сбой отправки → `delivered: false`, сообщение всё равно сохраняется как `note`.
- `capture_author_reply(session, telegram_id, text) -> int | None`: последняя заявка автора в `needs_info`, у которой последнее сообщение `to_author` не старше 14 дней → записать `from_author`, уведомить админа в админ-бот: «Ответ по заявке №{id}: …» с кнопкой «Открыть».
- В `fallback`: вызвать `capture_author_reply` **после** `maybe_route_client_relay_text_reply` и **до** `_client_support_awaiting`; если вернул id — ответить «Передали, спасибо!» и `return`.
- `notify_author_approved`: «Ваше место «{name}» появилось в Glide: {url}». Только Telegram (email — когда появится исходящая почта).

Tests: отправка пишет `to_author` и меняет статус (send подменён); ответ привязывается к нужной заявке; старше 14 дней — не привязывается (уходит в обычную поддержку).

**Step 5:** commit.

---

### Task 12: Админ-бот — «Одобрить как есть» и команда `/suggestions`

**Files:**
- Modify: `src/bot/handlers/admin_handlers.py` (по образцу `on_arena_approve`, `:2554`; команда — по образцу `/ice_inbox`, `:619-636`)
- Modify: `src/bot/admin_bot_commands.py`
- Test: `tests/bot/test_admin_place_suggestion_callbacks.py` (найти существующий тест callback-ов админ-бота и повторить его способ мока `CallbackQuery`)

Callback `psa:{id}` → `_is_admin` → `approve_place_suggestion` → `edit_reply_markup(None)` + ответ «Опубликовано: {url}». Заявка уже закрыта → `callback.answer("Заявка уже разобрана", show_alert=True)`. `/suggestions` — кнопка `WebAppInfo` на `/webapp/admin-place-suggestions` и счётчик новых.

**Step 5:** commit.

---

### Task 13: Экран «Заявки» в админском Mini App

**Делает владелец-менеджер сам (вёрстка по макету), не агент.**

**Files:**
- Create: `static/webapp/admin-place-suggestions.html` (образец `static/webapp/admin-ice-inbox.html`: inline-скрипт, `window.AdmAnalytics` — `initData`, `getJson`, `apiUrl`, `escapeHtml`, заголовок `X-Telegram-Init-Data`)
- Modify: `src/api/app.py:515` — `@app.get("/webapp/admin-place-suggestions")` по образцу `webapp_admin_ice_inbox_page`

Состав — артборд «Модерация · карточка заявки» холста: вкладки «Новые / Ждём ответа / Закрытые» (новые города подсвечены) → карточка: карта (статичный тайл OSM или SVG-схема с булавкой; перетаскивание булавки — PATCH lat/lon), «Похоже на» с «Это дубль» и галочками полей, редактируемые поля (сохранение по blur → PATCH), переписка с полем ввода (или «Скопировать контакт», если `delivered: false`), кнопки «Одобрить и опубликовать» / «Нужно уточнить» / «Отклонить» (причина — выпадающий список). `?id=` в URL открывает карточку сразу.

Проверка: вручную в Telegram на тестовой БД; скриншот — один, на итоговом состоянии.

**Step 5:** commit.

---

### Task 14: Общая форма + страница сайта `/suggest`

**Вёрстка — владелец сам по макету «Форма заявки · телефон».** Агенту можно отдать только JS-логику шагов и тесты маршрута.

**Files:**
- Create: `static/shared/place-suggest-form.js` — вся логика шагов (типы, поиск города с debounce 250 мс → `GET /api/public/place-suggestions/cities`, поля по типу, валюта по стране, контакт, экран «Спасибо»). Транспорт отправки передаётся снаружи: `PlaceSuggestForm.mount(root, { submit(payload) => Promise<{id, telegram_link?}> })`.
- Create: `static/shared/place-suggest-form.css` — только на токенах `glide-tokens.css` (`--g-*`), иконки — инлайн SVG из макета / `catalog_icons.py`, без emoji.
- Create: `static/share/suggest-page.html` (шаблон с `__PUBLIC_FONTS_HEAD__`, `__TOKENS_V__`, `__STYLE_V__`, `__COMPONENTS_V__`, `__SITE_FOOTER__` — как `static/share/legal-page.html`)
- Create: `src/application/public_suggest_page.py` — `render_suggest_page(*, trainers_href, prefill_city_id=None)` по образцу `render_legal_page` (`public_legal_page.py:47`)
- Modify: `src/api/routes/public_place_page.py` — `@router.get("/suggest")`, параметр `?city=<id>` для предзаполнения; `src/api/middleware/http_limits.py:64` — `/suggest` в `_PAGE_PREFIXES`
- Modify: точки входа — шапка сайта и футер (`src/application/public_site_footer.py:49`: заменить «Нашли ошибку… напишите нам» на ссылку «Предложить место или поправку»), страница города `/c/{город}` — ссылка «Знаете место, которого здесь нет?» с `?city=<id>`.
- Test: `tests/api/test_public_suggest_page.py` — 200, `noindex` не нужен (страница полезна в выдаче — решение владельца при вёрстке), есть `place-suggest-form.js`, `?city=` прокидывается в data-атрибут.

На экране «Спасибо» с сайта: если в ответе есть `telegram_link` — кнопка «Следить за заявкой в Telegram» (Task 8). Сроков не обещать.

**Step 5:** commit.

---

### Task 15: Форма в клиентском Mini App

**Files:**
- Create: `static/webapp/suggest.html` — подключает `static/shared/place-suggest-form.js`/`.css`, `submit` = `fetch('/api/webapp/place-suggestions', {headers: {'X-Telegram-Init-Data': initData}})`
- Modify: `src/api/app.py` — маршрут `/webapp/suggest`
- Modify: точка входа в каталоге Mini App (экран списка мест города / пустое состояние города — найти файл: `grep -rn "Сообщить об ошибке\|empty" static/webapp/*.html | head`). Место кнопки — решение владельца при вёрстке; «Сообщить об ошибке» на карточке места в этом этапе **не трогаем** (перевод на заявки — этап 4).

В Mini App шаг «Связь» скрыт: автор известен. Экран «Спасибо»: «Напишем вам здесь, когда место появится».

**Step 5:** commit.

---

### Task 16: Стирание контактов

**Files:**
- Modify: `src/application/place_suggestion_use_cases.py` — `purge_closed_contacts(session, *, older_than_days=30) -> int`
- Modify: существующий периодический цикл (найти: `grep -rn "async def .*loop\|create_task(" src/application/*sweep* src/bot/*app.py | head` — подойдёт цикл, уже крутящийся в процессе ботов `all_bots`)
- Test: `tests/application/test_place_suggestion_purge.py`

`UPDATE place_suggestions SET contact=NULL, contact_kind=NULL, bind_token=NULL WHERE closed_at < now() - interval ':d days' AND (contact IS NOT NULL OR bind_token IS NOT NULL)`. `author_telegram_id` не стираем: это id в нашем же боте, без него не дойдёт «место появилось» при повторном открытии. Раз в сутки.

**Step 5:** commit.

---

### Task 17: Сквозная проверка

1. Тестовая БД, `alembic upgrade head`.
2. Сайт: `/suggest` → крытый каток, «Уфа» (новый город из геокодера), название, цена → «Спасибо» с ссылкой на Telegram → `/start sg_…` в тестовом клиентском боте привязывает.
3. Админ-бот получил уведомление; «Открыть» → экран заявки; «Написать» → сообщение пришло в клиентский бот; ответ автора появился в ленте.
4. «Одобрить» → автору пришло «появилось в Glide»; **`/c/ufa` открывается и показывает место** при `ICE_DISCOVERY_COUNTRIES=BY,RU`. Если город без сеансов не рендерится или место скрыто правилом `PUBLIC_ARENA_VISIBLE_SQL` (`src/shared/ice_discovery_scope.py:46`) — это не баг этапа 1, а работа этапа 2 («город без расписания»): зафиксировать, что именно скрывает, и сообщить владельцу, не чинить на месте.
5. Mini App: заявка магазина в существующем городе → «Похоже на» показывает соседей → «Это дубль» с переносом телефона.
6. Полный `pytest tests/ -m "not collective" -q` — с выводом количества упавших; предсуществующие красные тесты (см. память `hub-bootstrap-invisible-in-tests`) отделить от новых.

---

## Не входит в этап 1

Страницы стран `/by/` `/ru/`, перенос `_BY_CITY_ROWS` в БД, уровень «город без расписания», показ `visitor_prices` на карточке, «Дополнить» на карточках, перевод «Сообщить об ошибке» на заявки, исходящая почта, роль модератора по городу.
