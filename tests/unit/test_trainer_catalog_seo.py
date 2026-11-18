"""Сниппет и индекс каталога /trenery: число, живые направления, свой запрос направления."""

from __future__ import annotations

from src.application.catalog_directions import ALL, direction_by_slug
from src.application.site_trainer_catalog import (
    DESCRIPTION_LIMIT,
    TITLE_LIMIT,
    _catalog_all_lead,
    catalog_description,
    catalog_title,
    fit_meta,
    indexable,
    render_catalog_page,
    sitemap_paths,
)


def _trainer(tid: int, keys: list[str]) -> dict:
    return {
        "id": tid,
        "order": tid,
        "name": f"Тренер {tid}",
        "initial": "Т",
        "path": f"/t/{tid}-trener",
        "arenas": [{"id": 1, "name": "Каток"}],
        "services_by_dir": {key: [{"price_cents": 1000}] for key in keys},
        "passes": [],
        "windows": [],
    }


def _data(city: str, trainers: list[dict]) -> dict:
    arena = {"id": 1, "name": "Каток", "city_name": city, "slug": None, "rental_minor": None}
    return {"city": {"id": 1, "name": city}, "trainers": trainers, "arenas": {1: arena}}


def test_one_trainer_teaches_in_the_singular() -> None:
    data = _data("Минск", [_trainer(1, ["zero"])])
    assert catalog_description(data, ALL) == ("В Минске 1 тренер по катанию на коньках: с нуля. Запись в Telegram.")


def test_catalog_all_lead_without_trainers_is_honest() -> None:
    # Нет тренеров — не обещаем запись, зовём тренера на сайт.
    lead = _catalog_all_lead(_data("Минск", []))
    assert lead == "Тренируете в Минске? Создайте страницу бесплатно."
    assert "Запись" not in lead and "хоккей" not in lead


def test_catalog_all_lead_without_trainers_and_without_locative_is_empty() -> None:
    assert _catalog_all_lead(_data("Несуществующий город", [])) == ""


def test_catalog_all_lead_verb_follows_the_number_of_trainers() -> None:
    one = _data("Минск", [_trainer(1, ["zero"]), _trainer(2, ["better"]), _trainer(3, ["better"])])
    assert _catalog_all_lead(one) == "Учит кататься с нуля и ставят технику."
    single = _data("Минск", [_trainer(1, ["zero", "better"])])
    assert _catalog_all_lead(single) == "Учит кататься с нуля и ставит технику."
    many = _data("Минск", [_trainer(1, ["zero"]), _trainer(2, ["zero"])])
    assert _catalog_all_lead(many) == "Учат кататься с нуля."


def test_catalog_all_lead_mentions_only_present_directions() -> None:
    spb = _data("Санкт-Петербург/ЛО", [_trainer(1, ["fig"]), _trainer(2, ["fig"])])
    assert _catalog_all_lead(spb) == "Есть фигурное катание."
    assert "хоккей" not in _catalog_all_lead(spb)


def test_catalog_names_only_directions_that_exist() -> None:
    data = _data(
        "Минск",
        [
            _trainer(1, ["zero", "better"]),
            _trainer(2, ["zero"]),
            _trainer(3, ["hock"]),
            _trainer(4, ["zero"]),
            _trainer(5, ["better"]),
        ],
    )
    text = catalog_description(data, ALL)
    assert text == (
        "В Минске 5 тренеров по катанию на коньках: "
        "с нуля, для уже катающихся и хоккейное катание. Запись в Telegram."
    )
    assert "фигурное" not in text
    assert "учат" not in text
    assert len(text) <= DESCRIPTION_LIMIT


def test_spb_catalog_uses_the_public_locative() -> None:
    data = _data("Санкт-Петербург/ЛО", [_trainer(1, ["fig"]), _trainer(2, ["fig"])])
    text = catalog_description(data, ALL)
    assert text == "В Санкт-Петербурге 2 тренера по катанию на коньках: фигурное катание. Запись в Telegram."
    assert "Санкт-Петербург/ЛО" not in text


def test_direction_page_with_the_same_trainers_goes_to_noindex() -> None:
    """Состав направления совпал со «Всеми» и тренеров меньше трёх — копия «Всех»: не в индекс."""
    data = _data("Минск", [_trainer(1, ["zero"]), _trainer(2, ["zero"])])
    zero = direction_by_slug("s-nulya")
    assert zero is not None
    assert indexable(data, ALL)
    assert not indexable(data, zero)
    assert not indexable(data, direction_by_slug("figurnoe"))
    assert "/c/minsk/trenery/s-nulya" not in sitemap_paths(data)
    assert "/c/minsk/trenery" in sitemap_paths(data)

    html = render_catalog_page(data, zero, base_url="https://glideclub.by")
    assert '<meta name="robots" content="noindex, follow"' in html
    assert '<link rel="canonical" href="https://glideclub.by/c/minsk/trenery/s-nulya"' in html
    # «Все» с теми же двумя тренерами остаётся в индексе.
    all_html = render_catalog_page(data, ALL, base_url="https://glideclub.by")
    assert '<meta name="robots" content="index, follow"' in all_html


def test_direction_with_its_own_roster_or_three_trainers_stays_in_the_index() -> None:
    zero = direction_by_slug("s-nulya")
    hock = direction_by_slug("s-klyushkoy")
    # Другой состав: «С нуля» — двое из трёх, «С клюшкой» — один.
    mixed = _data("Минск", [_trainer(1, ["zero"]), _trainer(2, ["zero"]), _trainer(3, ["hock"])])
    assert indexable(mixed, zero) and indexable(mixed, hock)
    paths = sitemap_paths(mixed)
    assert "/c/minsk/trenery/s-nulya" in paths and "/c/minsk/trenery/s-klyushkoy" in paths
    html = render_catalog_page(mixed, zero, base_url="https://glideclub.by")
    assert '<meta name="robots" content="index, follow"' in html
    # Тот же состав, что во «Всех», но тренеров трое — в индексе.
    three = _data("Минск", [_trainer(i, ["zero"]) for i in (1, 2, 3)])
    assert indexable(three, zero)
    assert "/c/minsk/trenery/s-nulya" in sitemap_paths(three)
    # Двое — нет, один — нет.
    assert not indexable(_data("Минск", [_trainer(i, ["zero"]) for i in (1, 2)]), zero)
    assert not indexable(_data("Минск", [_trainer(1, ["zero"])]), zero)


def test_direction_description_for_two_trainers_keeps_the_snippet_wording() -> None:
    data = _data("Минск", [_trainer(1, ["zero"]), _trainer(2, ["zero"])])
    zero = direction_by_slug("s-nulya")
    assert catalog_description(data, zero) == (
        "Научиться кататься на коньках с нуля в Минске: 2 тренера, от 10 BYN за занятие. Запись в Telegram."
    )


def test_direction_description_counts_and_skips_a_missing_price() -> None:
    zero = direction_by_slug("s-nulya")
    priced = _data("Минск", [_trainer(i, ["zero"]) for i in range(1, 6)])
    assert catalog_description(priced, zero) == (
        "Научиться кататься на коньках с нуля в Минске: 5 тренеров, от 10 BYN за занятие. Запись в Telegram."
    )
    one = _data("Санкт-Петербург/ЛО", [_trainer(1, ["zero"])])
    assert catalog_description(one, zero) == (
        "Научиться кататься на коньках с нуля в Санкт-Петербурге: 1 тренер, от 10 BYN за занятие. Запись в Telegram."
    )
    free = _trainer(1, ["fig"])
    free["services_by_dir"] = {"fig": [{}]}
    bare = _data("Минск", [free])
    fig = direction_by_slug("figurnoe")
    assert catalog_description(bare, fig) == (
        "Фигурное катание с тренером в Минске: 1 тренер. Запись в Telegram."
    )
    assert "учат" not in catalog_description(priced, zero)


def test_catalog_title_adds_brand_only_when_it_fits() -> None:
    short = catalog_title("Хоккейное катание", "в Минске")
    assert short == "Хоккейное катание в Минске · Glide"
    assert len(short) <= TITLE_LIMIT
    long = catalog_title("Уроки катания для тех, кто уже стоит на коньках", "в Санкт-Петербурге")
    assert long == "Уроки катания для тех, кто уже стоит на коньках в Санкт-Петербурге"
    assert "Glide" not in long
    assert len(long) > TITLE_LIMIT


def test_both_skating_directions_share_one_word() -> None:
    data = _data("Минск", [_trainer(i, ["zero", "better", "fig", "hock"]) for i in range(1, 6)])
    assert catalog_description(data, ALL) == (
        "В Минске 5 тренеров по катанию на коньках: "
        "с нуля, для уже катающихся, фигурное и хоккейное катание. Запись в Telegram."
    )


def test_empty_direction_stays_out_of_the_sitemap() -> None:
    data = _data("Минск", [_trainer(1, ["zero"]), _trainer(2, ["hock"])])
    paths = sitemap_paths(data)
    assert "/c/minsk/trenery" in paths
    assert "/c/minsk/trenery/s-nulya" in paths
    assert "/c/minsk/trenery/s-klyushkoy" in paths
    assert "/c/minsk/trenery/figurnoe" not in paths
    assert "/c/minsk/trenery/uzhe-katayus" not in paths
    assert not indexable(data, direction_by_slug("figurnoe"))


def test_meta_cut_stops_on_a_word_and_keeps_telegram() -> None:
    raw = "В Минске 5 тренеров учат кататься на коньках: " + " ".join(["оченьдлинное"] * 30) + ". Запись в Telegram."
    out = fit_meta(raw, 160)
    assert len(out) <= 160
    assert "…" not in out
    assert out.endswith("Запись в Telegram.")
    assert "оченьдлинное" in out
    tail = out[: -len(" Запись в Telegram.")]
    assert not tail.endswith("оченьдлин")


def test_breadcrumb_and_jsonld_use_the_public_city_name() -> None:
    data = {"city": {"id": 31, "name": "Санкт-Петербург/ЛО"}, "trainers": [], "arenas": {}}
    html = render_catalog_page(data, ALL, base_url="https://glideclub.by")
    assert "Санкт-Петербург/ЛО" not in html
    assert ">Санкт-Петербург<" in html
    assert '"name": "Санкт-Петербург"' in html


def _offer_trainer(tid: int, *, price=None, group=None, per_session=None) -> dict:
    svc: dict = {"service_id": 1, "currency_code": "BYN"}
    if price:
        svc["price_cents"] = price
    if group:
        svc["group_price_cents"] = group
    passes = [{"per_session_cents": per_session, "service_ids": None}] if per_session else []
    return {
        "id": tid,
        "order": tid,
        "name": f"Тренер {tid}",
        "initial": "Т",
        "path": f"/t/{tid}-trener",
        "arenas": [{"id": 1, "name": "Каток"}],
        "services_by_dir": {"zero": [svc]},
        "passes": passes,
        "windows": [],
    }


def test_direction_snippet_says_group_when_the_minimum_is_a_group_price() -> None:
    zero = direction_by_slug("s-nulya")
    data = _data("Минск", [_offer_trainer(1, price=5000, group=2500)])
    text = catalog_description(data, zero)
    assert "от 25 BYN в группе" in text
    assert "за занятие" not in text


def test_direction_snippet_says_pass_when_the_minimum_is_a_pass_session() -> None:
    zero = direction_by_slug("s-nulya")
    data = _data("Минск", [_offer_trainer(1, price=5000, per_session=4000)])
    text = catalog_description(data, zero)
    assert "от 40 BYN по абонементу" in text
    assert "за занятие" not in text


def test_direction_snippet_keeps_the_single_session_when_it_is_the_cheapest() -> None:
    zero = direction_by_slug("s-nulya")
    # Групповая и абонемент дороже обычного занятия: «от 30 BYN за занятие».
    data = _data("Минск", [_offer_trainer(1, price=3000, group=3500, per_session=4000)])
    assert "от 30 BYN за занятие" in catalog_description(data, zero)
    # Цена одна и та же в группе и у обычного занятия — честнее обычное.
    tie = _data("Минск", [_offer_trainer(1, price=3000, group=3000)])
    assert "от 30 BYN за занятие" in catalog_description(tie, zero)


def test_direction_snippet_takes_the_basis_of_the_cheapest_trainer() -> None:
    zero = direction_by_slug("s-nulya")
    data = _data("Минск", [_offer_trainer(1, price=3000), _offer_trainer(2, price=5000, group=2500)])
    assert "от 25 BYN в группе" in catalog_description(data, zero)


def test_card_and_hero_say_the_same_as_the_snippet() -> None:
    zero = direction_by_slug("s-nulya")
    data = _data("Минск", [_offer_trainer(1, price=5000, group=2500)])
    html = render_catalog_page(data, zero, base_url="https://glideclub.by")
    assert "от <b>25\u00a0BYN</b> в группе" in html
    assert "<small>в группе</small>" in html


def test_lastmod_is_the_freshest_of_profile_and_rinks_of_the_page_trainers() -> None:
    from datetime import datetime, timezone

    from src.application.site_trainer_catalog import page_lastmod

    def at(day: int) -> datetime:
        return datetime(2026, 11, day, tzinfo=timezone.utc)

    t1 = {**_trainer(1, ["zero"]), "arenas": [{"id": 10}]}
    t2 = {**_trainer(2, ["hock"]), "arenas": [{"id": 20}]}
    t3 = {**_trainer(3, ["zero", "hock"]), "arenas": [{"id": 10}]}
    data = _data("Минск", [t1, t2, t3])
    trainer_stamps = {1: at(2), 2: at(9), 3: at(3)}
    arena_stamps = {10: at(5), 20: at(1)}
    # «Все» — самая свежая дата всех: профиль тренера 2.
    assert page_lastmod(data, ALL, trainer_stamps, arena_stamps) == at(9)
    # «С нуля» — тренеры 1 и 3 и каток 10: каток свежее обоих профилей.
    assert page_lastmod(data, direction_by_slug("s-nulya"), trainer_stamps, arena_stamps) == at(5)
    # «С клюшкой» — тренеры 2 и 3.
    assert page_lastmod(data, direction_by_slug("s-klyushkoy"), trainer_stamps, arena_stamps) == at(9)
    # Каток другого тренера в свежесть направления не входит.
    assert page_lastmod(data, direction_by_slug("s-nulya"), {1: at(2), 3: at(3)}, {20: at(30)}) == at(3)
    assert page_lastmod(data, ALL, {}, {}) is None


def test_missing_locative_logs_a_warning_once(caplog) -> None:
    import logging

    from src.shared import city_locative as cl

    cl._WARNED.discard("Заславль")
    with caplog.at_level(logging.WARNING, logger="src.shared.city_locative"):
        cl.warn_if_no_locative("Заславль", where="test")
        cl.warn_if_no_locative("Заславль", where="test")
        cl.warn_if_no_locative("Минск", where="test")
        cl.warn_if_no_locative("Санкт-Петербург/ЛО", where="test")
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert "Заславль" in messages[0] and "no prepositional case" in messages[0]


def test_catalog_page_of_a_city_without_locative_warns(caplog) -> None:
    import logging

    from src.shared import city_locative as cl

    cl._WARNED.discard("Заславль")
    data = _data("Заславль", [_trainer(1, ["zero"])])
    with caplog.at_level(logging.WARNING, logger="src.shared.city_locative"):
        render_catalog_page(data, ALL, base_url="https://glideclub.by")
    assert any("Заславль" in r.getMessage() for r in caplog.records)
    cl._WARNED.discard("Заславль")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="src.shared.city_locative"):
        render_catalog_page(_data("Заславль", []), ALL, base_url="https://glideclub.by")
    assert not caplog.records


def test_new_cities_have_a_locative() -> None:
    from src.shared.city_locative import city_locative

    assert city_locative("Новолукомль") == "Новолукомле"
    # Сельсоветы и города без каталога в таблице не нужны: нет падежа — нет «в …».
    assert city_locative("Озёрский сельский Совет") is None
