from src.shared.winter_text import (
    generated_name,
    is_indoor_name,
    is_school_name,
    normalize_address,
    normalize_phones,
    phone_field,
)


def test_phone_formats_become_e164():
    assert normalize_phones("+375 (17) 371-04-53") == ["+375173710453"]
    assert normalize_phones("8 017 379-55-31") == ["+375173795531"]
    assert normalize_phones("8 0152 68 98 06") == ["+375152689806"]
    assert normalize_phones("8 01592 4 18 27") == ["+375159241827"]
    assert normalize_phones("8 029 253 90 24") == ["+375292539024"]


def test_two_numbers_and_empty():
    assert normalize_phones("8 029 253 90 24; +375 (17) 371-04-53") == ["+375292539024", "+375173710453"]
    assert normalize_phones("") == [] and phone_field(None) is None


def test_phone_garbage_kept_not_invented():
    assert normalize_phones("через администрацию") == []  # без цифр — пусто
    assert normalize_phones("12-34") == ["12-34"]


def test_address_normalisation_equates_variants():
    a = normalize_address("г. Волковыск, ул. Мицкевича, 9", "Волковыск")
    b = normalize_address("улица Мицкевича 9", "Волковыск")
    assert a == b
    assert normalize_address("пр. Победителей, 4а") == normalize_address("проспект Победителей 4а")
    assert normalize_address("пер. Козлова") == "переулок козлова"


def test_school_and_indoor_names():
    assert is_school_name("ГУО «Средняя школа № 144 г.Минска»")
    assert not is_school_name("Каток Приорбанк | Visa")
    assert is_indoor_name("Чижовка-Арена (закрытые х/к)") and is_indoor_name("МКСК «Минск-арена» (3 коробки)")
    assert is_indoor_name("Крыты каток") is True
    assert not is_indoor_name("Гарадскі лядовы каток")


def test_generated_names():
    assert generated_name("hockey_box", "г. Гродно, ул. Доватора, 21", None, "Гродно") == "Коробка, ул. Доватора, 21"
    assert generated_name("rink", "", "Заводской", "Минск") == "Каток, Заводской район"
    assert generated_name("rink", None, None, "Миоры") == "Каток, Миоры"
