"""Trainer rating notification copy."""
from __future__ import annotations

from src.bot import messages as msg


def test_format_trainer_client_rating_received_without_review():
    text = msg.format_trainer_client_rating_received_html(
        client_name="Мария Иванова",
        date="12.05",
        day="Пн",
        time="10:00",
        duration_minutes=45,
        service_name="Персональная тренировка",
        arena_display="Ice Arena",
        rating=5,
        review_text=None,
    )
    assert "Мария Иванова" in text
    assert "Персональная тренировка" in text
    assert "Ice Arena" in text
    assert "⭐⭐⭐⭐⭐" in text
    assert "5 из 5" in text
    assert "Текста отзыва нет" in text
    assert "💬" not in text or "Отзыв клиента" not in text


def test_format_trainer_client_rating_received_with_review():
    text = msg.format_trainer_client_rating_received_html(
        client_name="Иван",
        date="01.06",
        day="Вт",
        time="18:30",
        duration_minutes=None,
        service_name=None,
        arena_display=None,
        rating=4,
        review_text="Всё понравилось",
    )
    assert "⭐⭐⭐⭐" in text
    assert "4 из 5" in text
    assert "Всё понравилось" in text
    assert "Текста отзыва нет" not in text


def test_format_trainer_client_rating_review_added_followup():
    text = msg.format_trainer_client_rating_review_added_html(
        client_name="Пётр",
        date="03.06",
        day="Ср",
        time="09:00",
        rating=3,
        review_text="Можно лучше",
    )
    assert "дополнил отзыв" in text.lower()
    assert "Пётр" in text
    assert "Можно лучше" in text
    assert "3 из 5" in text
