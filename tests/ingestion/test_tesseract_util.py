from __future__ import annotations

import pytest

from tests.ingestion.tesseract_util import skip_unless_tesseract_rus


def test_skip_unless_tesseract_rus_skips_when_binary_missing(monkeypatch) -> None:
    pytest.importorskip("pytesseract")
    monkeypatch.setattr("tests.ingestion.tesseract_util.shutil.which", lambda _name: None)
    with pytest.raises(pytest.skip.Exception, match="tesseract binary"):
        skip_unless_tesseract_rus()


def test_skip_unless_tesseract_rus_skips_when_rus_pack_missing(monkeypatch) -> None:
    pytest.importorskip("pytesseract")
    monkeypatch.setattr("tests.ingestion.tesseract_util.shutil.which", lambda _name: "/usr/bin/tesseract")

    class _Fake:
        stdout = "List of available languages\neng\n"
        stderr = ""

    monkeypatch.setattr(
        "tests.ingestion.tesseract_util.subprocess.run",
        lambda *args, **kwargs: _Fake(),
    )
    with pytest.raises(pytest.skip.Exception, match="rus language"):
        skip_unless_tesseract_rus()
