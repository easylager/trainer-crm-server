#!/usr/bin/env python3
"""Regenerate static/templates/certificate_template.pdf (decor + labels only, no dynamic text)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.application.certificate_pdf import write_default_certificate_template_file  # noqa: E402


def main() -> None:
    p = write_default_certificate_template_file()
    print(f"Wrote {p}")


if __name__ == "__main__":
    main()
