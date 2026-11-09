"""Сниппет и индекс каталога /trenery: число, живые направления, свой запрос направления."""

from __future__ import annotations

from src.application.catalog_directions import ALL, direction_by_slug
from src.application.site_trainer_catalog import (
    DESCRIPTION_LIMIT,
    catalog_description,
    fit_meta,
    indexable,
    sitemap_paths,
)


def _trainer(tid: int, keys: list[str]) -> dict:
    return {
        "id": tid,
        "order": tid,
        "arenas": [{"id": 1}],
        "services_by_dir": {key: [{"price_cents": 1000}] for key in keys},
        "passes": [],
        "windows": [],
    }


def _data(city: str, trainers: list[dict]) -> dict:
    return {"city": {"id": 1, "name": city}, "trainers": trainers, "arenas": {}}


def test_one_trainer_teaches_in_the_singular() -> None:
    data = _data("Минск", [_trainer(1, ["zero"])])
    assert catalog_description(data, ALL) == ("В Минске 1 тренер по катанию на коньках: с нуля. Запись в Telegram.")


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


def test_direction_page_with_the_same_trainers_stays_in_the_index() -> None:
    data = _data("Минск", [_trainer(1, ["zero"]), _trainer(2, ["zero"])])
    zero = direction_by_slug("s-nulya")
    assert zero is not None
    assert indexable(data, ALL)
    assert indexable(data, zero)
    assert not indexable(data, direction_by_slug("figurnoe"))
    assert catalog_description(data, zero) == (
        "Научиться кататься на коньках с нуля в Минске. 2 тренера учат. Запись в Telegram."
    )


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
