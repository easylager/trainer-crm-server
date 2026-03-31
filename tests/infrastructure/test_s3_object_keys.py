"""Tests for S3 key normalization (public /api/public/photos and presigned GET)."""
import pytest

from src.infrastructure.s3 import resolve_object_key_under_prefixes


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("trainers/1/abc.jpg", "trainers/1/abc.jpg"),
        ("trainers//1//abc.jpg", "trainers/1/abc.jpg"),
        ("trainers/1/abc_list.jpg", "trainers/1/abc_list.jpg"),
    ],
)
def test_trainers_prefix_ok(raw: str, expected: str) -> None:
    assert resolve_object_key_under_prefixes(raw, ("trainers/",)) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "legal/doc.html",
        "certificates/1/1.pdf",
        "../trainers/1/x.jpg",
        "trainers/../legal/doc.html",
        "trainers/../certificates/1/1.pdf",
        "certificates/../trainers/1/x.jpg",
        "/trainers/1/x.jpg",
        "",
        "\x00trainers/1/x.jpg",
    ],
)
def test_trainers_prefix_rejected(raw: str) -> None:
    assert resolve_object_key_under_prefixes(raw, ("trainers/",)) is None


def test_certificates_prefix_ok() -> None:
    assert (
        resolve_object_key_under_prefixes("certificates/42/7.pdf", ("certificates/",))
        == "certificates/42/7.pdf"
    )


def test_certificates_escape_rejected() -> None:
    assert (
        resolve_object_key_under_prefixes(
            "certificates/../trainers/1/x.jpg",
            ("certificates/",),
        )
        is None
    )
