from src.shared.dossier_public_text import (
    public_payload_contains_dossier_leak,
    sanitize_opening_hours_for_public,
    scrub_dossier_leaks_from_public_text,
    text_contains_dossier_leak,
)


def test_scrub_drops_the_whole_clause_with_a_marker() -> None:
    raw = "комплекс: ежедневно 7:00–23:00. Кассы катания — см. Conflicts (не склеивать)"
    assert scrub_dossier_leaks_from_public_text(raw) == "комплекс: ежедневно 7:00–23:00"


def test_scrub_drops_parser_ops_notes_from_short_description() -> None:
    # Лида: внутренняя заметка про фото/HTML уехала в «О катке».
    raw = (
        "Ледовый дворец ГУ «Клуб по хоккею с шайбой «Лида», ул. Качана, 31. "
        "Расписание МК публикуется еженедельно (по понедельникам) фотографией "
        "на странице услуги, не HTML-таблицей."
    )
    assert scrub_dossier_leaks_from_public_text(raw) == (
        "Ледовый дворец ГУ «Клуб по хоккею с шайбой «Лида», ул. Качана, 31"
    )
    assert text_contains_dossier_leak(raw)
    assert not text_contains_dossier_leak(scrub_dossier_leaks_from_public_text(raw))


def test_sanitize_opening_hours_scrubs_note_but_keeps_structure() -> None:
    hours = {
        "complex": {"open": "07:00", "close": "23:00"},
        "note": "см. Conflicts (не склеивать)",
    }
    out = sanitize_opening_hours_for_public(hours)
    assert out == {"complex": {"open": "07:00", "close": "23:00"}}
    assert public_payload_contains_dossier_leak(out or {}) == []
