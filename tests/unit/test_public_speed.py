"""Повторное фото не читает хранилище, герой предзагружается из head."""

from src.infrastructure.photo_bytes_cache import PhotoBytesCache
from src.shared.html_template import inject_lcp_preload


def test_photo_cache_returns_the_stored_bytes_and_drops_the_oldest() -> None:
    cache = PhotoBytesCache(max_bytes=5, max_item_bytes=5)
    cache.put("a", b"12", "image/jpeg")
    cache.put("b", b"34", "image/jpeg")
    assert cache.get("a") == (b"12", "image/jpeg")
    cache.put("c", b"567", "image/jpeg")
    assert cache.get("b") is None
    assert cache.get("a") == (b"12", "image/jpeg")
    assert cache.get("c") == (b"567", "image/jpeg")


def test_photo_cache_skips_a_frame_larger_than_the_item_cap() -> None:
    cache = PhotoBytesCache(max_bytes=10, max_item_bytes=4)
    cache.put("big", b"12345", "image/jpeg")
    assert cache.get("big") is None


def test_lcp_preload_is_the_first_thing_in_head() -> None:
    html = (
        '<html><head><link rel="stylesheet" href="/static/share/style-b.css" /></head>'
        '<body><img fetchpriority="high" src="/api/public/photos/arenas/2/hero.jpg" '
        'srcset="/api/public/photos/arenas/2/thumb.jpg 320w" sizes="100vw" /></body></html>'
    )
    out = inject_lcp_preload(html)
    link = out.split("<head>", 1)[1].split("\n", 2)[1]
    assert link.startswith('  <link rel="preload" as="image" href="/api/public/photos/arenas/2/hero.jpg"')
    assert 'imagesrcset="/api/public/photos/arenas/2/thumb.jpg 320w"' in link
    assert 'imagesizes="100vw"' in link
    assert out.index("preload") < out.index("stylesheet")


def test_lcp_preload_leaves_a_page_without_a_hero_alone() -> None:
    html = "<html><head></head><body><p>нет фото</p></body></html>"
    assert inject_lcp_preload(html) == html
