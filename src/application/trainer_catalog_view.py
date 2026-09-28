"""
Everything the «Каталог» screen shows, assembled in one place (TASK-140).

The screen answers four questions and nothing else: am I in the catalog, why not, what do
clients see, and what happened to my card. So this module returns one payload with

* ``state`` — one of six, plus the reason code and the human sentence from the journal;
* ``preview`` — the card as a client sees it, so «опубликуется что-то кривое» stops being a fear;
* ``revision`` — both versions when a text/photo edit is waiting for a moderator; before this,
  a trainer uploaded a photo and had no way to tell clients were still seeing the old one;
* ``readiness`` — what is still missing, in the same words the profile carousel uses;
* ``warnings`` — things that hurt discoverability without unpublishing the card (a card with no
  public arenas stays in the list but falls out of every arena filter — the old UI insisted
  everything was fine);
* ``metrics`` — the counters that already exist, not new ones;
* ``events`` — the history, which is what makes the whole thing auditable by the trainer.

Read-only: every state change goes through ``trainer_catalog_state.set_catalog_state``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.collective_use_cases import (
    STUDIO_ACCESS_MODE_ADMIN_ONLY,
    get_effective_studio_access_mode,
    list_active_collective_memberships,
)
from src.application.demand_signals_use_cases import get_signals_since
from src.application.trainer_catalog_state import (
    CATALOG_ACTOR_MODERATOR,
    CATALOG_ACTOR_STUDIO,
    CATALOG_ACTOR_SYSTEM,
    CATALOG_ACTOR_TRAINER,
    REASON_BACKFILL_0206,
    list_catalog_events,
)
from src.application.trainer_profile_completeness import (
    analyze_moderation_profile_completeness,
    analyze_moderation_submission_readiness,
    missing_labels_ru,
)
from src.application.trainer_profile_pending import (
    trainer_has_photo_pending_revision,
    trainer_has_pending_text_revision,
)
from src.shared.notification_hours import NOTIFICATION_TZ
from src.shared.catalog_visibility import (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_NEEDS_REVISION,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
)

logger = logging.getLogger(__name__)

METRICS_WINDOW_DAYS = 7
EVENTS_LIMIT = 20

# One sentence per state. Kept server-side so the push, the digest and the screen cannot drift
# into describing the same state three different ways.
STATE_HEADLINE_RU: dict[str, str] = {
    CATALOG_STATE_DRAFT: "Вас пока нет в каталоге",
    CATALOG_STATE_PENDING_REVIEW: "На проверке",
    CATALOG_STATE_PUBLISHED: "В каталоге",
    CATALOG_STATE_HIDDEN: "Снято вами",
    CATALOG_STATE_PAUSED: "Приостановлено",
    CATALOG_STATE_NEEDS_REVISION: "Модератор попросил поправить",
}

STATE_BODY_RU: dict[str, str] = {
    # Draft-фраза — единственное место, где мы объясняем ценность каталога, и объяснять
    # надо трафик, а не устройство раздела. «Список тренеров» описывал таблицу; тренера
    # интересует, откуда в ней берутся люди.
    CATALOG_STATE_DRAFT: (
        "Каталог — витрина сервиса: новых учеников на неё приводим мы. Сейчас к вам "
        "попадают только те, кому вы сами дали ссылку."
    ),
    CATALOG_STATE_PENDING_REVIEW: (
        "Обычно отвечаем в течение рабочего дня — пуш придёт сразу."
    ),
    CATALOG_STATE_PUBLISHED: "Клиенты находят вас в общем списке.",
    CATALOG_STATE_HIDDEN: (
        "Запись по вашей ссылке работает как обычно. Вернём сразу, без повторной проверки."
    ),
    CATALOG_STATE_PAUSED: (
        "Это не связано с подпиской и не влияет на ваши записи. Заполните — и карточка "
        "вернётся сама, без проверки."
    ),
    CATALOG_STATE_NEEDS_REVISION: "Исправьте и отправьте снова — проверим ещё раз.",
}

# История — это лента событий, а не лента состояний. Раньше строка собиралась как
# «<название состояния> · <автор>», и «На проверке · вами» читалось так, будто тренер проверяет
# сам себя. Событие называется глаголом и само говорит, кто его совершил, поэтому отдельный
# суффикс с автором не нужен.
#
# Ключ — (состояние, кто), потому что одно и то же состояние наступает по разным причинам:
# `published` от модератора — это «опубликовали», а от системы — «вернулась сама».
_EVENT_HEADLINE_RU: dict[tuple[str, str], str] = {
    (CATALOG_STATE_PENDING_REVIEW, CATALOG_ACTOR_TRAINER): "Вы отправили карточку на проверку",
    (CATALOG_STATE_PENDING_REVIEW, CATALOG_ACTOR_STUDIO): "Студия отправила карточку на проверку",
    (CATALOG_STATE_PENDING_REVIEW, CATALOG_ACTOR_SYSTEM): "Карточка вернулась на проверку",
    (CATALOG_STATE_PUBLISHED, CATALOG_ACTOR_MODERATOR): "Модератор опубликовал карточку",
    (CATALOG_STATE_PUBLISHED, CATALOG_ACTOR_TRAINER): "Вы вернули карточку в каталог",
    (CATALOG_STATE_PUBLISHED, CATALOG_ACTOR_STUDIO): "Студия вернула карточку в каталог",
    (CATALOG_STATE_PUBLISHED, CATALOG_ACTOR_SYSTEM): "Карточка вернулась в каталог",
    (CATALOG_STATE_HIDDEN, CATALOG_ACTOR_TRAINER): "Вы сняли карточку с публикации",
    (CATALOG_STATE_HIDDEN, CATALOG_ACTOR_STUDIO): "Студия сняла карточку с публикации",
    (CATALOG_STATE_PAUSED, CATALOG_ACTOR_SYSTEM): "Карточка приостановлена",
    (CATALOG_STATE_NEEDS_REVISION, CATALOG_ACTOR_MODERATOR): "Модератор попросил поправить",
    (CATALOG_STATE_DRAFT, CATALOG_ACTOR_TRAINER): "Вы отозвали заявку",
    (CATALOG_STATE_DRAFT, CATALOG_ACTOR_STUDIO): "Студия отозвала заявку",
}

# Когда пары нет (редкая комбинация, чужой actor, служебный backfill) — нейтральная фраза про
# само состояние, но по-прежнему без «· вами».
_EVENT_HEADLINE_FALLBACK_RU: dict[str, str] = {
    CATALOG_STATE_DRAFT: "Карточка не размещена",
    CATALOG_STATE_PENDING_REVIEW: "Карточка на проверке",
    CATALOG_STATE_PUBLISHED: "Карточка в каталоге",
    CATALOG_STATE_HIDDEN: "Карточка снята с публикации",
    CATALOG_STATE_PAUSED: "Карточка приостановлена",
    CATALOG_STATE_NEEDS_REVISION: "Нужны правки",
}


def event_headline_ru(to_state: str | None, actor_type: str | None) -> str:
    """Одна строка журнала: что произошло. Без отдельного суффикса с автором."""
    state = (to_state or "").strip()
    actor = (actor_type or "").strip()
    return _EVENT_HEADLINE_RU.get((state, actor)) or _EVENT_HEADLINE_FALLBACK_RU.get(state, state)


# Shown in every state: the fear of «не заплатил — пропал» costs more than the sentence does.
SUBSCRIPTION_NOTE_RU = (
    "Подписка на каталог не влияет: если она закончится, карточка останется — отключится "
    "только самозапись."
)


def _state_body_ru(state: str, trainer: dict[str, Any]) -> str:
    """
    Фраза состояния. Для ``pending_review`` зависит от того, цела ли отметка в очереди.

    Здесь стояло «Карточку можно дополнять, заявка не сбросится», и это была неправда: любая
    реальная правка снимает ``moderation_submitted_at`` (``clear_moderation_submitted_at``), а
    заново модератора никто не зовёт. Тренер правил карточку, читал, что всё в порядке, и ждал
    ответа на заявку, которой у модератора уже не было.
    """
    if state == CATALOG_STATE_PENDING_REVIEW and trainer.get("moderation_submitted_at") is None:
        return (
            "Вы изменили карточку после отправки — модератор ещё не видел новую версию. "
            "Отправьте её, когда закончите править."
        )
    return STATE_BODY_RU.get(state, "")


def _state_actions(
    state: str, *, can_act: bool, submit_ready: bool, queue_stamp_held: bool = True
) -> list[str]:
    """Which buttons the screen may offer. The trainer's own state, not a permission model."""
    if not can_act:
        return []
    if state == CATALOG_STATE_PUBLISHED:
        return ["hide"]
    if state in (CATALOG_STATE_HIDDEN, CATALOG_STATE_PAUSED):
        return ["restore"]
    if state == CATALOG_STATE_PENDING_REVIEW:
        # Правка карточки снимает отметку в очереди (``clear_moderation_submitted_at``): модератор
        # держит ссылку на карточку, которой уже нет. Тренер при этом видел единственную кнопку
        # «Отменить заявку» — позвать на проверку заново было нечем, и ждать он мог бесконечно.
        if not queue_stamp_held and submit_ready:
            return ["resubmit", "withdraw"]
        return ["withdraw"]
    if state == CATALOG_STATE_NEEDS_REVISION:
        # Правки — это работа в анкете, а экран каталога её не содержит. Без явной двери
        # тренер читал комментарий модератора и закрывал раздел, чтобы искать анкету руками.
        return ["edit", "submit"] if submit_ready else ["fill"]
    # draft: publishing is the one deliberate act, and only when ready.
    return ["submit"] if submit_ready else ["fill"]


def _service_line_ru(services: list[Any]) -> str | None:
    """
    «Спортивная мотивация: 33 BYN» — ровно то, что рисует карточка списка у клиента
    (``catalog-main.js``: первая услуга + её цена, не «от N BYN» по всем услугам).

    До этого превью показывало минимальную цену без названия услуги, и тренер видел карточку,
    какой она в каталоге не бывает: «от 33 BYN» без единого намёка, за что именно эта цена.
    """
    first = next((s for s in (services or []) if isinstance(s, dict)), None)
    if first is None:
        return None
    name = (first.get("service_name") or "Услуга").strip()
    lo = first.get("price_byn_min")
    hi = first.get("price_byn_max")
    if lo is None and hi is None:
        cents = first.get("price_cents")
        lo = hi = (cents / 100) if cents is not None else None
    if lo is None:
        return f"{name}: по запросу"
    if hi is not None and hi != lo:
        return f"{name}: от {_money_ru(lo)}"
    return f"{name}: {_money_ru(lo)}"


def _money_ru(value: float) -> str:
    return (f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}") + " BYN"


async def _free_slots_14d(session: AsyncSession, trainer_id: int) -> int:
    """Тот же счёт, что и в списке каталога (``TrainerRepository.list_active_for_client``)."""
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM slots
            WHERE trainer_id = :tid
              AND status = 'available'
              AND slot_date >= CURRENT_DATE
              AND slot_date <= CURRENT_DATE + INTERVAL '14 days'
              AND ((slot_date + start_time) AT TIME ZONE :tz) > NOW()
            """
        ),
        {"tid": trainer_id, "tz": NOTIFICATION_TZ},
    )
    row = r.fetchone()
    return int(row[0]) if row else 0


async def _preview(session: AsyncSession, trainer: dict[str, Any]) -> dict[str, Any]:
    """
    Карточка ровно в том наборе фактов, который рисует клиентский список — не «похожая».

    Раньше превью жило своей жизнью: показывало город (которого на карточке нет, он фильтр) и
    «от N BYN» вместо «Услуга: цена». Тренер смотрел на карточку, которой в каталоге не
    существует, и справедливо не верил тому, что видит.

    Пустые факты не подставляются заглушками: клиентская карточка не пишет ни «цена по
    запросу», ни «стаж не указан» — пустой факт ничего не сообщает, но занимает строку.
    """
    profile = trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {}
    arena_public = trainer.get("arena_is_public") or {}
    public_arena_ids = [aid for aid, is_pub in arena_public.items() if is_pub]
    photos = trainer.get("photos") or []
    rating_count = int(profile.get("rating_count") or 0)
    return {
        "first_name": profile.get("first_name"),
        "last_name": profile.get("last_name"),
        "photo_file_key": (photos[0] or {}).get("file_key") if photos else None,
        "rating_avg": profile.get("rating_avg") if rating_count > 0 else None,
        "rating_count": rating_count,
        "experience_years": profile.get("experience_years"),
        "free_slots_14d": await _free_slots_14d(session, int(trainer["id"])),
        "service_line": _service_line_ru(trainer.get("services") or []),
        "arena_names": [a for a in (trainer.get("arena_names") or []) if a][:2],
        "public_arena_count": len(public_arena_ids),
        # Клиентская карточка ставит «Онлайн» вместо площадки (``ice-tab-model.trainerCardView``).
        "arena_work_format": (trainer.get("arena_work_format") or "").strip() or None,
    }


def _revision(trainer: dict[str, Any]) -> dict[str, Any] | None:
    """
    Both versions of the card while a moderated edit waits.

    ``profile_pending`` / ``photo_pending`` already existed; what was missing was ever telling
    the trainer that clients are still looking at the previous values.
    """
    has_text = trainer_has_pending_text_revision(trainer)
    has_photo = trainer_has_photo_pending_revision(trainer)
    if not has_text and not has_photo:
        return None
    published = trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {}
    pending = trainer.get("profile_pending") if isinstance(trainer.get("profile_pending"), dict) else {}
    photo_pending = trainer.get("photo_pending") if isinstance(trainer.get("photo_pending"), dict) else {}
    photos = trainer.get("photos") or []
    return {
        "has_text": has_text,
        "has_photo": has_photo,
        "current": {
            "first_name": published.get("first_name"),
            "last_name": published.get("last_name"),
            "description": published.get("description"),
            "photo_file_key": (photos[0] or {}).get("file_key") if photos else None,
        },
        "next": {
            "first_name": pending.get("first_name", published.get("first_name")),
            "last_name": pending.get("last_name", published.get("last_name")),
            "description": pending.get("description", published.get("description")),
            "photo_file_key": photo_pending.get("file_key")
            or ((photos[0] or {}).get("file_key") if photos else None),
        },
    }


def _warnings(trainer: dict[str, Any], state: str) -> list[dict[str, str]]:
    """
    Soft problems: they cost discoverability but must not take the card down.

    Hiding every arena is the one that used to lie outright — the profile toggle said «клиенты
    находят вас в общем списке» at the exact moment the trainer dropped out of every arena
    filter and of the arena-derived city rows in ``trainer_cities``.

    Only discoverability problems belong here. Optional-but-nice fields are the readiness block's
    job; listing them in both places made «предупреждение» mean nothing.
    """
    if state != CATALOG_STATE_PUBLISHED:
        return []
    out: list[dict[str, str]] = []
    arena_public = trainer.get("arena_is_public") or {}
    if arena_public and not any(arena_public.values()):
        out.append(
            {
                "code": "no_public_arenas",
                "text": "Ни одной открытой площадки — вас не найдут по фильтру «арена».",
                "action": "arenas",
            }
        )
    # Необязательные поля сюда НЕ попадают: они живут в блоке готовности («можно усилить»).
    # Пока попадали — экран показывал один и тот же список дважды, и «предупреждение» переставало
    # означать «это мешает вас находить».
    return out


async def build_catalog_screen_payload(
    session: AsyncSession, trainer: dict[str, Any]
) -> dict[str, Any]:
    """One GET for the whole screen. ``trainer`` is a ``get_trainer`` aggregate."""
    trainer_id = int(trainer["id"])
    state = (trainer.get("catalog_state") or CATALOG_STATE_DRAFT).strip()
    submit_ready, missing = analyze_moderation_submission_readiness(trainer)

    studio_mode = await get_effective_studio_access_mode(session, trainer_id)
    managed_by_studio = studio_mode == STUDIO_ACCESS_MODE_ADMIN_ONLY
    studio_name = None
    if managed_by_studio:
        memberships = await list_active_collective_memberships(session, trainer_id)
        if memberships:
            studio_name = getattr(memberships[0], "display_name", None)

    events = await list_catalog_events(session, trainer_id, limit=EVENTS_LIMIT)
    # The sentence for the current state comes from the event that produced it, not from a
    # separate copy that could describe a different state than the column holds.
    #
    # Except the migration backfill: every trainer alive before 0206 carries one, its
    # ``reason_detail`` is engineering shorthand («восстановлено из status + is_catalog_visible»),
    # and read back as the current explanation it made the screen open with a line that reads
    # like a crash report. The screen used to filter it client-side on ``state_reason``, but the
    # backfill never wrote that column — only the event — so the filter never fired.
    latest = events[0] if events else None
    latest_reason = (latest or {}).get("reason")
    reason_detail = (
        None if latest is None or latest_reason == REASON_BACKFILL_0206 else latest["reason_detail"]
    )

    since = datetime.now(timezone.utc) - timedelta(days=METRICS_WINDOW_DAYS)
    try:
        recap = await get_signals_since(session, trainer_id=trainer_id, since=since)
        metrics = {
            "window_days": METRICS_WINDOW_DAYS,
            "profile_views": recap.profile_views,
            "contact_clicks": recap.contact_clicks,
            "catalog_favorites": recap.catalog_favorites,
        }
    except Exception:  # noqa: BLE001 — metrics are decoration; the state is the point
        logger.exception("catalog screen metrics failed trainer_id=%s", trainer_id)
        metrics = None

    _, full_missing = analyze_moderation_profile_completeness(trainer)
    # «Можно усилить» — то, что не блокирует публикацию, но меняет карточку в выдаче. Цены сюда
    # попадают отдельным ключом: ни один tier их не проверяет, поэтому до сих пор тренер узнавал
    # про них только из строки «цена не указана» в карточке модератора — которую он не видит.
    optional_keys = [k for k in full_missing if k in ("description", "education", "experience_years")]
    if not any(
        isinstance(svc, dict) and svc.get("price_cents") is not None
        for svc in (trainer.get("services") or [])
    ):
        optional_keys.append("prices")
    return {
        # Нужен экрану, чтобы открыть публичную карточку глазами клиента.
        "trainer_id": trainer_id,
        "state": state,
        "state_reason": trainer.get("catalog_state_reason") or latest_reason,
        "state_detail": reason_detail,
        "state_changed_at": trainer.get("catalog_state_changed_at"),
        "headline": STATE_HEADLINE_RU.get(state, ""),
        "body": _state_body_ru(state, trainer),
        "subscription_note": SUBSCRIPTION_NOTE_RU,
        "can_act": not managed_by_studio,
        "managed_by_studio": managed_by_studio,
        "studio_name": studio_name,
        "actions": _state_actions(
            state,
            can_act=not managed_by_studio,
            submit_ready=submit_ready,
            queue_stamp_held=trainer.get("moderation_submitted_at") is not None,
        ),
        "readiness": {
            "submit_ready": submit_ready,
            "missing_fields": missing,
            "missing_labels_ru": missing_labels_ru(missing, first_name_only=True),
            "optional_missing_labels_ru": missing_labels_ru(optional_keys),
        },
        "preview": await _preview(session, trainer),
        "revision": _revision(trainer),
        "warnings": _warnings(trainer, state),
        "metrics": metrics,
        "events": [
            {
                "from_state": e["from_state"],
                "to_state": e["to_state"],
                "reason": e["reason"],
                # Same rule as the current-state sentence above: the backfill's note is ours,
                # not the trainer's, so it never leaves the server — not even inside history.
                "reason_detail": (
                    None if e["reason"] == REASON_BACKFILL_0206 else e["reason_detail"]
                ),
                "actor_type": e["actor_type"],
                "created_at": e["created_at"],
                "headline": event_headline_ru(e["to_state"], e["actor_type"]),
            }
            for e in events
        ],
    }
