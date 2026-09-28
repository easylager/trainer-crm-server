"""Словарь типов площадок и ролей специалистов — чистая логика, без БД."""

import pytest

from src.application.trainer_arena_create_use_cases import _strip_wrapping_quotes
from src.application.trainer_custom_service_use_cases import (
    CustomServiceError,
    _dedupe_key,
    normalize_service_name,
)
from src.shared.specialist_roles import (
    DEFAULT_SPECIALIST_ROLE,
    InvalidSpecialistRoleError,
    normalize_specialist_role,
    specialist_role_display,
)
from src.shared.venue_types import (
    DEFAULT_VENUE_TYPE,
    VENUE_TYPE_KEYS,
    normalize_venue_type,
    venue_card_cta,
    venue_site_label,
    venue_type_chip,
    venue_type_noun,
)


class TestVenueTypes:
    @pytest.mark.parametrize("key", VENUE_TYPE_KEYS)
    def test_every_key_has_all_labels(self, key):
        """Пропущенная подпись превращается в KeyError на рендере карточки."""
        assert venue_type_noun(key)
        assert venue_type_chip(key)
        assert venue_card_cta(key).startswith("Открыть карточку ")

    @pytest.mark.parametrize("raw", [None, "", "   ", "rink", "ЛЁД", "gym\n"])
    def test_unknown_or_blank_never_raises(self, raw):
        """Тип приходит и из формы, и из строк, созданных до появления колонки."""
        assert normalize_venue_type(raw) in VENUE_TYPE_KEYS

    def test_blank_falls_back_to_ice(self):
        """200+ существующих арен — катки; дефолт обязан сохранять их поведение."""
        assert normalize_venue_type(None) == DEFAULT_VENUE_TYPE == "ice"

    def test_case_and_whitespace_are_tolerated(self):
        assert normalize_venue_type("  GyM  ") == "gym"

    def test_gym_never_reads_as_a_rink(self):
        """Ровно тот баг, из-за которого всё затевалось: зал, названный катком."""
        assert venue_card_cta("gym") == "Открыть карточку зала"
        assert venue_site_label("gym") == "Сайт зала"
        assert "катк" not in venue_card_cta("gym")
        assert "катк" not in venue_site_label("gym")

    def test_ice_copy_is_unchanged(self):
        """Для льда формулировки должны остаться ровно прежними."""
        assert venue_card_cta("ice") == "Открыть карточку катка"
        assert venue_site_label("ice") == "Сайт катка"


class TestSpecialistRole:
    def test_blank_is_none_not_trainer(self):
        """None = «не спрашивали», его можно переспросить; «Тренер» — уже ответ."""
        assert normalize_specialist_role("") is None
        assert normalize_specialist_role(None) is None

    def test_display_falls_back_for_old_profiles(self):
        assert specialist_role_display(None) == DEFAULT_SPECIALIST_ROLE

    def test_free_text_survives_verbatim(self):
        """Смысл поля — что угодно, чего нет в наших подсказках."""
        assert normalize_specialist_role("Спортивный психолог") == "Спортивный психолог"
        assert normalize_specialist_role("Тренер по скандинавской ходьбе") == (
            "Тренер по скандинавской ходьбе"
        )

    def test_whitespace_is_collapsed(self):
        assert normalize_specialist_role("  Спортивный   психолог \n") == "Спортивный психолог"

    def test_too_long_is_rejected(self):
        with pytest.raises(InvalidSpecialistRoleError):
            normalize_specialist_role("а" * 65)

    def test_punctuation_only_is_rejected(self):
        with pytest.raises(InvalidSpecialistRoleError):
            normalize_specialist_role("!!! ???")

    def test_display_never_raises_on_bad_stored_value(self):
        """Карточка каталога не должна падать из-за мусора в старой строке."""
        assert specialist_role_display("а" * 200) == DEFAULT_SPECIALIST_ROLE


class TestArenaNameQuotes:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('"Lifestyle"', "Lifestyle"),
            ("«Lifestyle»", "Lifestyle"),
            ("  “Lifestyle”  ", "Lifestyle"),
            ("Lifestyle", "Lifestyle"),
        ],
    )
    def test_wrapping_quotes_are_stripped(self, raw, expected):
        """Арена #201 приехала как «Lifestyle» — в карточке это читалось цитатой."""
        assert _strip_wrapping_quotes(raw) == expected

    def test_inner_quotes_are_preserved(self):
        """«Ледовый дворец "Юность"» — законное имя, обрезать нечего."""
        assert _strip_wrapping_quotes('Ледовый дворец "Юность"') == 'Ледовый дворец "Юность"'

    def test_empty_stays_empty(self):
        assert _strip_wrapping_quotes("") == ""
        assert _strip_wrapping_quotes('""') == ""


class TestCustomServiceName:
    def test_dedupe_ignores_case_punctuation_and_yo(self):
        """Без этого «ОФП», «офп» и «ОФП/СФП» станут тремя услугами в фильтре."""
        assert _dedupe_key("ОФП/СФП") == _dedupe_key("офп сфп")
        assert _dedupe_key("Хатха-йога") == _dedupe_key("хатха йога")
        assert _dedupe_key("Всё тело") == _dedupe_key("все тело")

    def test_different_services_stay_different(self):
        assert _dedupe_key("Хореография") != _dedupe_key("Хоккей")

    def test_case_is_preserved_in_stored_name(self):
        """Автоматический Title Case ломал бы аббревиатуры вроде ОФП."""
        assert normalize_service_name("  ОФП/СФП  ") == "ОФП/СФП"

    @pytest.mark.parametrize("raw", ["", "   ", "---", None])
    def test_junk_is_rejected(self, raw):
        with pytest.raises(CustomServiceError):
            normalize_service_name(raw)

    def test_too_long_is_rejected(self):
        with pytest.raises(CustomServiceError):
            normalize_service_name("й" * 129)
