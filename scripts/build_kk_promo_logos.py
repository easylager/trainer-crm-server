"""Лёгкие копии логотипов клубов для ленты на странице /kk (static/landing/kk/logos/*.webp).

Игра берёт PNG 200×200 из static/webapp/hockey-logos — их не трогаем. Для ленты хватает 96 px:
диск 56 px, логотип в нём 40 px, запас под экраны 2–2,5×. Запуск после добавления клуба в реестр:

    python scripts/build_kk_promo_logos.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.application.hockey_teams import TEAMS, logo_path  # noqa: E402

OUT = ROOT / "static" / "landing" / "kk" / "logos"
SIZE = 96


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for team in TEAMS.values():
        src = logo_path(team.slug)
        if not src.is_file():
            continue
        img = Image.open(src).convert("RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
        img.save(OUT / f"{team.slug}.webp", "WEBP", quality=82, alpha_quality=90, method=6)
    print(sum(p.stat().st_size for p in OUT.glob("*.webp")), "bytes in", OUT)


if __name__ == "__main__":
    main()
