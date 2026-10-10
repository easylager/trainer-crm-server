"""Catalog search ranks a name, a street, a service and a typo without pg_trgm."""

from src.application.catalog_search import rank_cities, rank_places, similarity


def _place(**kwargs):
    base = {
        "id": 1,
        "slug": "place",
        "name": "Чижовка-арена",
        "address": "ул. Ташкентская, 19",
        "city_id": 2,
        "district": "Заводской район",
        "city_name": "Минск",
        "venue_type": "ice",
        "amenities": {},
        "blurb": "",
    }
    base.update(kwargs)
    return base


def _ids(query, rows, **kwargs):
    return [hit["id"] for hit in rank_places(query, rows, **kwargs)]


def test_name_inflection_and_typo_find_chizhovka():
    rows = [_place(), _place(id=2, name="Барановичи арена", city_id=8, city_name="Барановичи")]
    assert _ids("чижовка", rows) == [1]
    assert _ids("чижовки", rows) == [1]
    assert _ids("чижофка", rows) == [1]
    assert similarity("чижофка", "чижовка") >= 0.4
    # «чи» is a prefix of Чижовка, not an infix of Барановичи.
    assert _ids("чи", rows) == [1]


def test_address_hint_keeps_the_word_when_it_sits_at_the_end():
    rows = [
        _place(
            id=6,
            name="Sport-Ice — парк Горького",
            venue_type="shop",
            address="ул. Первомайская, 3 (административное здание ХК «Юность-Минск» / крытый каток)",
        )
    ]
    hint = rank_places("каток", rows)[0]["hint"]
    assert "каток" in hint.lower()


def test_service_line_wins_over_a_blurb_that_contains_a_phone():
    shop = _place(
        id=3,
        name="Мастерская",
        venue_type="shop",
        amenities={"skate_rental": True},
        blurb="Прокат коньков. Ещё телефоны: +375 29 699-12-15.",
    )
    hint = rank_places("коньки", [shop])[0]["hint"]
    assert hint.startswith("Прокат")
    assert "+375" not in hint


def test_street_finds_the_place_and_says_so():
    rows = [
        _place(
            id=5,
            name="Минск Арена",
            address="Минск, пр-т Победителей, 111",
            district="",
        )
    ]
    hit = rank_places("победителей", rows)[0]
    assert hit["id"] == 5
    assert "Победителей" in hit["hint"]
    assert not hit["hint"].startswith("Минск")


def test_service_word_skips_an_explicit_false():
    shop = _place(
        id=3,
        name="Лезвие",
        venue_type="shop",
        address="ул. Карла Маркса, 15",
        amenities={"retail": True, "skate_sharpening": True, "repair": False},
    )
    assert _ids("заточка коньков", [shop]) == [3]
    assert _ids("ремонт", [shop]) == []
    assert "Заточка" in rank_places("заточка", [shop])[0]["hint"]


def test_open_city_ranks_above_the_same_service_elsewhere():
    rows = [
        _place(
            id=1,
            name="Бобруйск-арена",
            city_id=9,
            city_name="Бобруйск",
            amenities={"skate_sharpening": True},
        ),
        _place(
            id=2,
            name="HotIce",
            city_id=2,
            city_name="Минск",
            venue_type="shop",
            amenities={"skate_sharpening": True},
        ),
    ]
    assert _ids("заточка", rows, city_id=2) == [2, 1]


def test_katok_stays_inside_the_open_city():
    rows = [
        _place(id=1, name="Чижовка-арена", city_id=2),
        _place(id=2, name="Ледовый дворец спорта", city_id=4, city_name="Гродно", address="ул. Коммунальная, 3а"),
    ]
    assert _ids("каток", rows, city_id=2) == [1]


def test_gym_word_reaches_a_hall_in_another_city():
    rows = [_place(id=7, name="Lifestyle", venue_type="gym", city_id=2, city_name="Минск")]
    assert _ids("зал", rows, city_id=4) == [7]


def test_blurb_finds_the_club_name_missing_from_the_title():
    rows = [
        _place(
            id=11,
            name="Ледовый дворец спорта",
            city_id=4,
            city_name="Гродно",
            address="ул. Коммунальная, 3а",
            blurb="Ледовый дворец спорта ХК «Неман», ул. Коммунальная, 3а.",
        )
    ]
    hit = rank_places("неман", rows)[0]
    assert hit["id"] == 11
    assert "Неман" in hit["hint"]


def test_ohm_word_finds_only_rinks_with_a_practice():
    rows = [
        _place(id=1, name="Чижовка-арена"),
        _place(id=2, name="Каток на Немиге", venue_type="outdoor"),
    ]
    assert _ids("охм", rows, ohm_ids={1}) == [1]
    assert "ОХМ" in rank_places("охм", rows, ohm_ids={1})[0]["hint"]


def test_city_name_still_resolves_to_the_city():
    hits = rank_cities("минск", [{"id": 2, "name": "Минск"}, {"id": 4, "name": "Гродно"}])
    assert [hit["id"] for hit in hits] == [2]
