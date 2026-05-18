# Локальный стек с Cloudflare Tunnel

Выполни в этом репозитории **полный подъём или перезапуск** локальной разработки: туннель → патч `.env` → API и все боты.

## Обязательный порядок

1. **Корень репозитория** — все команды из `${workspaceFolder}` (где лежит `pyproject.toml` / `src/`).

2. **Останови предыдущий туннель** (игнорируй ошибки):
   - `bash scripts/dev_stop_cloudflared.sh || true`

3. **Подними tunnel и пропиши URL в `.env`** (`API_BASE_URL` и `WEBAPP_BASE_URL`):
   - `bash scripts/dev_prepare_tunnel.sh`
   - Дождись строки с базовым URL; если таймаут — сообщи пользователю (cloudflared / сеть).

4. **Освободи порт 8000 и старые процессы ботов этого проекта**, чтобы не было дубликатов:
   - Для API на порту 8000 (macOS): `lsof -ti :8000 | xargs kill -9 2>/dev/null || true`
   - Также: `pkill -f "uvicorn src.api.app:app" 2>/dev/null || true`
   - На macOS процесс может называться `Python`, не `python` — паттерны по **модулю**:  
     `pkill -f "src.bot.client_app" 2>/dev/null || true`  
     `pkill -f "src.bot.trainer_app" 2>/dev/null || true`  
     `pkill -f "src.bot.notification_service" 2>/dev/null || true`  
     `pkill -f "src.bot.admin_app" 2>/dev/null || true`

5. **Интерпретатор**:  
   `PY=$(test -x .venv/bin/python && echo .venv/bin/python || echo python3)`  
   (или `venv/bin/python`, если так заведено.)

6. **Запуск процессов — предпочти `nohup` в логи**, иначе фоновые вызовы из агента Cursor часто **убивают дочерние процессы** после выхода оболочки:
   - `nohup "$PY" -m uvicorn src.api.app:app --reload --port 8000 >> /tmp/trainer-crm-uvicorn.log 2>&1 &`
   - `nohup "$PY" -m src.bot.client_app >> /tmp/trainer-crm-client-bot.log 2>&1 &`
   - `nohup "$PY" -m src.bot.trainer_app >> /tmp/trainer-crm-trainer-bot.log 2>&1 &`
   - `nohup "$PY" -m src.bot.notification_service >> /tmp/trainer-crm-notify.log 2>&1 &`
   - `nohup "$PY" -m src.bot.admin_app >> /tmp/trainer-crm-admin-bot.log 2>&1 &`  
   Альтернатива для ручной работы: отдельная вкладка терминала на каждый процесс (**Tasks** в `.vscode/tasks.json`).

7. **Проверка**: после паузы ~3 с —  
   `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/docs` — ожидай **200**.

## Альтернатива без агента

В Cursor: **Tasks: Run Task** → **`CRM: Tunnel → then all servers`** (см. `.vscode/tasks.json`).

## Замечания

- `.env` не коммитится; скрипт туннеля его перезаписывает только для `API_BASE_URL` / `WEBAPP_BASE_URL`.
- После смены URL процессы нужно перезапускать — это делают шаги 4–7.
