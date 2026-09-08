"""TASK-084: trainer-less catalog browse opens Ice, not the old funnel."""
from src.shared.catalog_entry import catalog_browse_redirect, client_discovery_webapp_url


def test_bare_catalog_redirects_to_ice_coaches() -> None:
    assert catalog_browse_redirect({}) == "/webapp/ice?intent=coach"
    assert catalog_browse_redirect({"tab": "catalog"}) == "/webapp/ice?intent=coach"


def test_catalog_with_trainer_stays_on_catalog() -> None:
    assert catalog_browse_redirect({"trainer_id": "77"}) is None
    assert catalog_browse_redirect({"tab": "catalog", "trainer_id": "77"}) is None


def test_catalog_keeps_city_on_ice_redirect() -> None:
    assert catalog_browse_redirect({"city_id": "2", "tab": "catalog"}) == (
        "/webapp/ice?intent=coach&city_id=2"
    )


def test_collective_landing_stays_on_catalog() -> None:
    assert catalog_browse_redirect({"collective": "ice-yoga", "tab": "catalog"}) is None


def test_client_discovery_url_browse_vs_trainer() -> None:
    assert (
        client_discovery_webapp_url("https://app.example")
        == "https://app.example/webapp/ice?intent=coach"
    )
    assert (
        client_discovery_webapp_url("https://app.example", trainer_id=12)
        == "https://app.example/webapp/catalog?trainer_id=12"
    )
