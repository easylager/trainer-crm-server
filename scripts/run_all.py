#!/usr/bin/env python3
"""
Run API server + 3 bots (client, trainer, admin) in one terminal.
Output is prefixed: [api], [client], [trainer], [admin]. Ctrl+C kills all.

Usage (from repo root):
  python -m scripts.run_all

Or:
  python scripts/run_all.py
"""
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORT = os.environ.get("PORT", "8000")

# Admin bot is optional (only if telegram_bot_token_admin is set in .env)
def _procs() -> list[tuple[str, list]]:
    from src.shared.config import Settings
    settings = Settings()
    procs = [
        ("api", ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", PORT]),
        ("client", [sys.executable, "-m", "src.bot.client_app"]),
        ("trainer", [sys.executable, "-m", "src.bot.trainer_app"]),
    ]
    if getattr(settings, "telegram_bot_token_admin", None):
        procs.append(("admin", [sys.executable, "-m", "src.bot.admin_app"]))
    else:
        print("[run_all] telegram_bot_token_admin not set, skipping admin bot.", flush=True)
    return procs


def read_stream(prefix: str, stream, stream_name: str) -> None:
    for line in iter(stream.readline, ""):
        if line:
            print(f"[{prefix}] {line.rstrip()}", flush=True)
    stream.close()


def main() -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT))

    processes = []
    for name, cmd in _procs():
        try:
            p = subprocess.Popen(
                cmd,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            if name == "api" and cmd[0] == "uvicorn":
                print(f"[run_all] uvicorn not found. Install: pip install uvicorn", file=sys.stderr)
            raise
        processes.append((name, p))
        t = threading.Thread(target=read_stream, args=(name, p.stdout, "stdout"), daemon=True)
        t.start()

    def kill_all() -> None:
        for name, p in processes:
            if p.poll() is None:
                p.terminate()
        for name, p in processes:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    def on_sig(signum, frame) -> None:
        print("\n[run_all] Shutting down...", flush=True)
        kill_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sig)
    signal.signal(signal.SIGTERM, on_sig)

    while True:
        for name, p in processes:
            if p.poll() is not None:
                print(f"[run_all] {name} exited (code {p.returncode}), stopping all.", flush=True)
                kill_all()
                sys.exit(p.returncode or 1)
        time.sleep(0.5)


if __name__ == "__main__":
    main()
