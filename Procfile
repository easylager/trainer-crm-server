# Railway: first service uses "web" (gets public URL). Other services add in dashboard with custom start commands.
# API: migrations + uvicorn (PORT set by Railway)
web: sh -c 'alembic upgrade head && uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-8000}'
