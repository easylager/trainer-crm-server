"""Tests for release comms message parsing."""
from pathlib import Path

from src.application.release_comms_use_cases import parse_release_comms_file


def test_parse_release_comms_file_clients(tmp_path: Path) -> None:
    path = tmp_path / "msg.clients.md"
    path.write_text(
        """---
release_id: test-release
audience: clients
button_text: Открыть
webapp_path: /webapp/client-home
---

<b>Hello</b> world
""",
        encoding="utf-8",
    )
    spec = parse_release_comms_file(path)
    assert spec.release_id == "test-release"
    assert spec.audience == "clients"
    assert spec.button_text == "Открыть"
    assert spec.webapp_path == "/webapp/client-home"
    assert spec.html_body == "<b>Hello</b> world"


def test_parse_release_comms_file_no_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "plain.md"
    path.write_text("<b>Only body</b>", encoding="utf-8")
    spec = parse_release_comms_file(path)
    assert spec.release_id == "plain"
    assert spec.audience == "clients"
    assert spec.html_body == "<b>Only body</b>"
