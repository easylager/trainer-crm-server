"""Skip OCR fixture tests when the system tesseract binary (rus) is missing.

``pytest.importorskip("pytesseract")`` is not enough: the Python wrapper is in
requirements.txt, but extract() shells out to the ``tesseract`` binary.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest


def skip_unless_tesseract_rus() -> None:
    pytest.importorskip("pytesseract")
    if shutil.which("tesseract") is None:
        pytest.skip("system tesseract binary is not on PATH")
    listed = subprocess.run(
        ["tesseract", "--list-langs"],
        capture_output=True,
        text=True,
        check=False,
    )
    langs = f"{listed.stdout}\n{listed.stderr}".split()
    if "rus" not in langs:
        pytest.skip("tesseract rus language pack is not installed")
