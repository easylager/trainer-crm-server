"""Admin moderation card HTML: no per-education moderation status, rich profile fields."""
from src.bot.admin_moderation_card import format_admin_education_block, format_admin_trainer_moderation_caption
from src.shared.byr_currency_display import BYR_SIGN


def test_education_block_has_no_moderation_status():
    items = [
        {
            "institution_name": "БГУ",
            "program_or_title": "ФК",
            "moderation_status": "approved",
        }
    ]
    block = format_admin_education_block({}, items)
    assert "approved" not in block.lower()
    assert "БГУ" in block


def test_moderation_caption_includes_services_and_arenas():
    trainer = {
        "id": 7,
        "telegram_id": 123,
        "profile": {
            "first_name": "A",
            "last_name": "B",
            "age": 30,
            "city_id": 1,
            "experience_years": 5,
            "description": "Hello",
            "phone": "+375",
            "session_duration_minutes": 60,
            "min_hours_before_booking": 2,
        },
        "services": [
            {"service_id": 1, "service_name": "Тренировка", "price_byn": 10.5, "price_cents": 1050},
        ],
        "arena_names": ["Лёд-1"],
        "photos": [],
    }
    text = format_admin_trainer_moderation_caption(trainer, [], city_name="Минск")
    assert "Тренер #7" in text
    assert "Минск" in text
    assert "+375" in text
    assert "60 мин" in text
    assert "2 ч" in text
    assert "Тренировка" in text
    assert f"10.5 {BYR_SIGN}" in text
    assert "Лёд-1" in text
