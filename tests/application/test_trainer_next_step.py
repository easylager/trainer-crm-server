"""
Хаб показывает ровно одну подсказку — и правильную.

Это тесты продуктового контракта онбординга v2, а не форматирования: порядок срочности,
и — важнее всего — то, что работающий кабинет молчит.

Приглашения в каталог здесь больше нет: оно переехало строкой в action inbox
(``catalog_publication``, см. ``trainer_hub_action_inbox.py``), потому что продавало раздел,
который тренер и так видит вкладкой бара, а занимало главный экран целиком.
"""
from src.application.trainer_next_step import (
    ACTION_OPEN_ONBOARDING,
    ACTION_OPEN_CATALOG,
    ACTION_SHARE_LINK,
    STEP_CATALOG_NEEDS_REVISION,
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
    # Ни площадка, ни профиль, ни каталог: после первой записи карточке нечего сказать.
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
    assert step is None or step["key"] != STEP_SET_ARENA


def test_first_booking_hides_the_share_card() -> None:
    """Первая запись — и блок про ссылку пропадает."""
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=1,
            arena_count=1,
        )
    )
    assert step is None or step["key"] != STEP_SHARE_LINK


def test_first_booking_without_arena_does_not_bring_back_the_arena_card() -> None:
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=1,
            arena_count=0,
        )
    )
    assert step is None or step["key"] != STEP_SET_ARENA


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


def test_deactivated_and_studio_trainers_are_left_alone() -> None:
    assert resolve_trainer_next_step(_checklist(schedule_unlocked=False)) is None
    assert resolve_trainer_next_step(_checklist(studio_access_mode="admin_only")) is None
    assert resolve_trainer_next_step(None) is None


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
    assert step is None or step["key"] not in (STEP_REFRESH_WEEK, STEP_SETUP_WEEK)


def test_the_catalog_invite_is_gone_from_the_hub_card_for_good() -> None:
    """
    «Вас уже записывают» занимало главный экран целиком, чтобы продать раздел, до которого
    теперь один тап по вкладке бара. Ни одна комбинация фактов не должна возвращать его назад.
    """
    for real_bookings in (1, 5, 20):
        for opted_in in (False, True):
            step = resolve_trainer_next_step(
                _checklist(
                    weekly_template_count=5,
                    has_future_slots=True,
                    has_any_booking=True,
                    real_bookings_count=real_bookings,
                    is_catalog_visible=opted_in,
                    catalog_missing_fields=["phone", "city"],
                    arena_count=1,
                )
            )
            assert step is None, f"вернулось приглашение: {step}"


def test_moderator_feedback_is_still_a_card_because_it_is_work_not_an_invitation() -> None:
    """Единственная карточка про каталог, которая осталась: без правок карточка не опубликуется."""
    step = resolve_trainer_next_step(
        _checklist(
            weekly_template_count=5,
            has_future_slots=True,
            has_any_booking=True,
            real_bookings_count=3,
            catalog_needs_revision=True,
            moderation_feedback="Фото не по правилам",
        )
    )
    assert step["key"] == STEP_CATALOG_NEEDS_REVISION
    assert step["cta"]["action"] == ACTION_OPEN_CATALOG
    assert step["secondary"] is None


class TestScheduleIsOptional:
    """Расписание перестало быть обязательным — хаб обязан это уважать.

    Пустая неделя сама по себе ничего не значит: её могли не дойти заполнить,
    а могли сознательно пропустить. Раньше хаб читал оба случая одинаково и
    требовал расписание — в том числе у того, кому экран онбординга только что
    сказал, что оно необязательно. Первое, что специалист видел в продукте,
    спорило с тем, что мы ему пообещали минуту назад.
    """

    def test_untouched_onboarding_still_leads_to_setup(self):
        """Кто ещё не настраивался — ведём в настройку, это по-прежнему первый шаг."""
        card = resolve_trainer_next_step(_checklist(onboarding_completed=False))
        assert card["key"] == STEP_SETUP_WEEK
        assert card["cta"]["action"] == ACTION_OPEN_ONBOARDING

    def test_finished_without_schedule_is_led_to_the_first_client(self):
        """Прошёл онбординг и оставил неделю пустой — это выбор, а не недоделка."""
        card = resolve_trainer_next_step(_checklist(onboarding_completed=True))
        assert card["key"] == STEP_SHARE_LINK
        assert card["cta"]["action"] == ACTION_SHARE_LINK

    def test_schedule_stays_reachable_as_a_secondary_action(self):
        """Не отняли, а перестали навязывать: вторая кнопка ведёт туда же."""
        card = resolve_trainer_next_step(_checklist(onboarding_completed=True))
        assert card["secondary"]["action"] == ACTION_OPEN_ONBOARDING

    def test_card_does_not_demand_a_schedule_in_words(self):
        """Копирайт тоже не должен требовать расписание — иначе смысл потерян."""
        card = resolve_trainer_next_step(_checklist(onboarding_completed=True))
        text = (card["title"] + " " + card["body"]).lower()
        assert "настройте расписание" not in text
        assert "расписание не нужно" in text
