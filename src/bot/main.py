"""
Legacy entry: runs client bot. Prefer explicit entry points:
  python -m src.bot.client_app   — client bot (public)
  python -m src.bot.trainer_app  — trainer bot (entry via link from site)
"""
import asyncio

from src.bot.client_app import main

if __name__ == "__main__":
    asyncio.run(main())
