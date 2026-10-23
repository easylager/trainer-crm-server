from src.shared.service_ui_accent import with_default_service_ui_accents


def test_unset_services_get_distinct_colors_by_id():
    assert with_default_service_ui_accents({2: None, 1: None}) == {1: "sky", 2: "amber"}


def test_chosen_color_is_kept_and_not_reused():
    assert with_default_service_ui_accents({1: None, 2: "sky", 3: ""}) == {1: "amber", 2: "sky", 3: "emerald"}


def test_slate_is_never_a_default_but_is_kept_when_chosen():
    out = with_default_service_ui_accents({i: None for i in range(1, 8)} | {9: "slate"})
    assert out[9] == "slate"
    assert "slate" not in {v for k, v in out.items() if k != 9}
