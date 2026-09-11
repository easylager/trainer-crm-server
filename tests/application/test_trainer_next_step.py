"""
Хаб показывает ровно одну подсказку — и правильную.

Это тесты продуктового контракта онбординга v2, а не форматирования: порядок срочности,
момент каталога, порог каталога и — важнее всего — то, что работающий кабинет
молчит.
"""
from src.application.trainer_next_step import (
    ACTION_DISMISS,
    ACTION_OPEN_ONBOARDING,
    ACTION_ENABLE_CATALOG,
    ACTION_OPEN_CATALOG_PROFILE,
    ACTION_SHARE_LINK,
    CATALOG_INVITE_MIN_BOOKINGS,
    STEP_CATALOG_INVITE,
    STEP_SET_ARENA,
    STEP_REFRESH_WEEK,
    STEP_SETUP_WEEK,
    STEP_SHARE_LINK,
    resolve_trainer_next_step,
)


def _checklist(**over) -> dict:
    """Тренер сразу после /start: ничего не заполнено, но всё открыто."""
    base = {
        "schedule_unlocked": True,
        "weekly_template_count": 0,
        "has_future_slots": False,
        "has_any_booking": False,
        "has_real_booking": False,
        "real_bookings_count": 0,
        "arena_count": 0,
        "arena_work_format": None,
        "is_active": False,
        # Каталог по заявке (0182): новый тренер в него не просился.
        "is_catalog_visible": False,
    }
    base.update(over)
    # TASK-027: resolve_trainer_next_step reads has_real_booking, not has_any_booking
    # (a sandbox demo intentionally still flips the latter — activation parity). Every
    # test written before that distinction existed sets has_any_booking to mean «есть
    # реальная запись» — mirror it here unless a test explicitly cares about the split.
    if "has_real_booking" not in over and "has_any_booking" in over:
        base["has_real_booking"] = over["has_any_booking"]
    return base


def test_brand_new_trainer_is_asked_only_to_set_up_a_week() -> None:
    step = resolve_trainer_next_step(_checklist())
    assert step["key"] == STEP_SETUP_WEEK
    assert step["cta"]["action"] == ACTION_OPEN_ONBOARDING
    assert step["secondary"] is None, "первый шаг не предлагает альтернатив"


def test_no_mention_of_catalog_or_moderation_on_the_first_step() -> None:
    """Каталог — награда за поток, а не задание на старте."""
    step = resolve_trainer_next_step(_checklist())
    blob = (step["title"] + step["body"] + step["cta"]["label"]).lower()
    for forbidden in ("каталог", "провер", "анкет", "модер"):
        assert forbidden not in blob


def test_after_the_week_the_only_task_is_to_share_the_link() -> None:
    step = resolve_trainer_next_step(_checklist(weekly_template_count=5, has_future_slots=True))
    assert step["key"] == STEP_SHARE_LINK
    assert step["cta"]["action"] == ACTION_SHARE_LINK
    assert step["secondary"] is None, "в момент неуверенности — ровно одна кнопка"


def test_hub_does_not_nag_arena_or_profile_after_first_booking() -> None:
    """После первой записи хаб молчит — площадку и профиль не выносим отдельной карточкой."""
    before = resolve_trainer_next_step(
        _checklist(weekly_template_count=5, has_future_slots=True)
    )
    assert before["key"] != STEP_SET_ARENA

    after = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=1,
        )
    )
    assert after is None


def test_mobile_work_format_counts_as_an_answered_arena() -> None:
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=1,
            arena_work_format="mobile",
        )
    )
    assert step is None


def test_first_booking_hides_the_share_card() -> None:
    """Первая запись — и блок про ссылку пропадает. Без запасной карточки."""
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=1,
            arena_count=1,
        )
    )
    assert step is None


def test_first_booking_without_arena_still_gets_no_hub_card() -> None:
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=1,
            arena_count=0,
        )
    )
    assert step is None


def test_catalog_is_offered_only_after_a_real_stream_of_bookings() -> None:
    just_below = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=CATALOG_INVITE_MIN_BOOKINGS - 1,
            arena_count=1,
        )
    )
    assert just_below is None

    at_threshold = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=CATALOG_INVITE_MIN_BOOKINGS,
            arena_count=1,
        )
    )
    assert at_threshold["key"] == STEP_CATALOG_INVITE
    assert str(CATALOG_INVITE_MIN_BOOKINGS) in at_threshold["body"]
    assert at_threshold["secondary"]["action"] == ACTION_DISMISS


def test_catalog_invite_respects_not_now() -> None:
    args = dict(
        weekly_template_count=5,
        has_future_slots=True,
        has_any_booking=True,
        real_bookings_count=9,
        arena_count=1,
    )
    assert resolve_trainer_next_step(_checklist(**args), catalog_invite_dismissed=True) is None


def test_working_practice_gets_no_card_at_all() -> None:
    """Пустое состояние — норма. Продукт не обязан всё время что-то предлагать."""
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=20,
            arena_count=1,
            is_active=True,
            is_catalog_visible=True,
        )
    )
    assert step is None


def test_catalog_same_card_and_carousel_when_opted_in_with_phone_gap() -> None:
    """Одна карточка catalog_invite → та же карусель; фамилия не в списке пробелов."""
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=CATALOG_INVITE_MIN_BOOKINGS,
            is_active=False,
            is_catalog_visible=True,
            catalog_missing_fields=["phone"],
        )
    )
    assert step is not None
    assert step["key"] == STEP_CATALOG_INVITE
    assert step["cta"]["action"] == ACTION_OPEN_CATALOG_PROFILE
    assert step["cta"]["label"] == "Продолжить"
    assert "телефон" in step["body"]
    assert "фамилия" not in step["body"]


def test_catalog_invite_gone_after_opt_in_when_profile_ready() -> None:
    """Opt-in + пустые catalog_missing — ждать модерацию / heal, без повторного приглашения."""
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=CATALOG_INVITE_MIN_BOOKINGS,
            is_active=False,
            is_catalog_visible=True,
            catalog_missing_fields=[],
        )
    )
    assert step is None


def test_deactivated_and_studio_trainers_are_left_alone() -> None:
    assert resolve_trainer_next_step(_checklist(schedule_unlocked=False)) is None
    assert resolve_trainer_next_step(_checklist(studio_access_mode="admin_only")) is None
    assert resolve_trainer_next_step(None) is None


def test_plural_agreement_in_the_catalog_invite() -> None:
    def body_for(n: int) -> str:
        return resolve_trainer_next_step(
            _checklist(
                weekly_template_count=1,
                has_future_slots=True,
                has_any_booking=True,
                real_bookings_count=n,
                arena_count=1,
            )
        )["body"]

    assert "21 занятие" in body_for(21)
    assert "22 занятия" in body_for(22)
    assert "25 занятий" in body_for(25)
    assert "11 занятий" in body_for(11)


def test_expired_schedule_is_caught_before_sharing_an_empty_link() -> None:
    """
    Шаблон недели есть, но будущих слотов нет — ссылка привела бы ученика на пустой экран.
    Обещание ссылки и реальность расписания обязаны совпадать.
    """
    step = resolve_trainer_next_step(
        _checklist(weekly_template_count=5, has_future_slots=False)
    )
    assert step["key"] == STEP_REFRESH_WEEK
    assert step["cta"]["action"] == ACTION_OPEN_ONBOARDING


def test_fully_booked_week_is_not_mistaken_for_an_empty_one() -> None:
    """has_future_slots считает и занятые слоты — у загруженного тренера паники быть не должно."""
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=2,
            arena_count=1,
        )
    )
    assert step is None


def test_catalog_invite_names_the_fields_the_profile_will_actually_ask_for() -> None:
    """
    Карточка обещала «фото и пара слов о себе», а submission tier требует восемь пунктов —
    тренер жал кнопку и попадал на список, которого не ждал. Теперь список один и тот же.
    """
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=CATALOG_INVITE_MIN_BOOKINGS,
            catalog_missing_fields=["phone", "city", "arenas"],
        )
    )
    assert step["key"] == STEP_CATALOG_INVITE
    assert "не хватает: телефон, город и площадка." in step["body"]
    assert "пара слов о себе" not in step["body"]


def test_catalog_invite_says_the_card_is_ready_when_nothing_is_missing() -> None:
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=CATALOG_INVITE_MIN_BOOKINGS,
            catalog_missing_fields=[],
        )
    )
    assert "Карточка уже готова." in step["body"]
    assert "не хватает" not in step["body"]


def test_catalog_invite_cta_is_the_opt_in_itself() -> None:
    """
    Кнопка включает показ в каталоге, а не просто открывает профиль: согласие на публикацию
    живёт в «Настройках», и раньше «Заполнить профиль» вело на экран, который отправлял
    тренера искать тумблер где-то ещё.
    """
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=CATALOG_INVITE_MIN_BOOKINGS,
            catalog_missing_fields=["phone"],
        )
    )
    assert step["cta"]["action"] == ACTION_ENABLE_CATALOG
    assert step["secondary"]["action"] == ACTION_DISMISS
