"""TASK-271: srcset на герое и плитках стиля B."""

from src.application.style_b import hero_html, tile_html


def test_hero_srcset_when_two_variants() -> None:
    html = hero_html(
        title="Тест",
        photo_url="https://cdn.example/card.jpg",
        photo_variants={
            "thumb": "https://cdn.example/thumb.jpg",
            "card": "https://cdn.example/card.jpg",
        },
        photo_alt="",
    )
    assert 'srcset="' in html
    assert "320w" in html and "800w" in html
    assert 'sizes="100vw"' in html
    assert 'src="https://cdn.example/card.jpg"' in html


def test_hero_single_variant_no_srcset() -> None:
    html = hero_html(
        title="Тест",
        photo_url="https://cdn.example/only.jpg",
        photo_variants={"card": "https://cdn.example/only.jpg"},
        photo_alt="",
    )
    assert "srcset=" not in html
    assert 'src="https://cdn.example/only.jpg"' in html


def test_hero_without_photo_variants_uses_photo_url() -> None:
    html = hero_html(title="Тест", photo_url="https://cdn.example/x.jpg", photo_alt="")
    assert "srcset=" not in html
    assert 'src="https://cdn.example/x.jpg"' in html


def test_tile_srcset_with_thumb_and_card() -> None:
    html = tile_html(
        href="/c/minsk",
        name="Минск",
        line="1 каток",
        photo_url="https://cdn.example/card.jpg",
        photo_variants={
            "thumb": "https://cdn.example/thumb.jpg",
            "card": "https://cdn.example/card.jpg",
        },
    )
    assert 'srcset="' in html
    assert "320w" in html and "800w" in html
