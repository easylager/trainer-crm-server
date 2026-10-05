"""Контакты на публичной странице места — несколько телефонов в одном поле."""

from src.application.place_page import _contacts_html, split_contact_phones


def test_split_contact_phones_by_comma_and_plus_prefix() -> None:
    raw = "+375 17 203-33-33, +375 29 111-22-33"
    assert split_contact_phones(raw) == ["+375 17 203-33-33", "+375 29 111-22-33"]


def test_split_contact_phones_glued_with_plus() -> None:
    raw = "+375 17 203-33-33 +375 29 111-22-33"
    assert len(split_contact_phones(raw)) == 2


def test_contacts_html_separate_tel_links() -> None:
    html = _contacts_html(
        {
            "phone": "+375 17 203-33-33, +375 29 111-22-33",
            "address": "",
            "social_urls": {},
        }
    )
    assert html.count('href="tel:') == 2
    assert "+375 17 203-33-33" in html
    assert "+375 29 111-22-33" in html
    assert "contact-phones" in html
