# Cursor MCP (Model Context Protocol)

Production-ready конфигурация для AI-ассистента в Cursor: локальная разработка, API, PostgreSQL (read-only), GitHub, E2E.

Файл: [`.cursor/mcp.json`](../.cursor/mcp.json) (можно продублировать в `~/.cursor/mcp.json` для глобальных настроек).

## Подключённые серверы

| Имя | Назначение |
|-----|------------|
| `filesystem` | Чтение файлов репозитория в пределах `${workspaceFolder}` |
| `fetch` | Загрузка URL (GET), в т.ч. `http://localhost:...` — health, документация |
| `postgres` | **Только read-only** SQL и схемы таблиц (`@modelcontextprotocol/server-postgres`) |
| `github` | Issues, PR, содержимое файлов в GitHub (нужен PAT) |
| `playwright` | Браузерная автоматизация / E2E (`@playwright/mcp`) |

## Зависимости на машине

- **Node.js** + `npx` — для `filesystem`, `postgres`, `github`, `playwright`
- **`uv`** — для `fetch` (`uvx mcp-server-fetch`). Установка: [astral.sh/uv](https://docs.astral.sh/uv/getting-started/).  
  Альтернатива: свой venv и `python -m mcp_server_fetch` — тогда замените блок `fetch` в `mcp.json` на соответствующий `command`/`args`.

## Переменные окружения (секреты не коммитить)

Задайте в окружении ОС или в настройках Cursor (Environment), чтобы подстановка `${env:...}` из `mcp.json` сработала при старте MCP:

| Переменная | Описание |
|------------|----------|
| `POSTGRES_MCP_URL` | Обычный URL PostgreSQL **без** префикса драйвера SQLAlchemy: `postgresql://user:pass@host:5432/dbname`. Должен совпадать с локальной БД из [`.env.example`](../.env.example). |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | Fine-grained или classic PAT GitHub с нужными scope (repo, pull requests, issues — по задачам). Пакет читает `process.env.GITHUB_PERSONAL_ACCESS_TOKEN`. |

Скопируйте значения в `.env` и экспортируйте в shell перед запуском Cursor **или** пропишите переменные в системных настройках / в UI Cursor, если поддерживается.

## Ограничения (важно)

- **Postgres MCP** выполняет только запросы в режиме read-only. INSERT/UPDATE — через миграции, приложение или `psql` в терминале.
- **Fetch** удобен для GET и просмотра ответов. Сложные POST/PATCH с JSON и заголовками — через **`curl` / `httpie` в терминале** или **pytest** (`tests/integration/`).
- Произвольный shell не вынесен в отдельный MCP: используйте встроенный терминал агента Cursor (`docker compose`, `alembic`, тесты).

## После изменения `mcp.json` (чеклист проверки)

1. Экспортируйте `POSTGRES_MCP_URL` (и при необходимости `GITHUB_PERSONAL_ACCESS_TOKEN`) из `.env` в окружение **до** запуска Cursor, либо задайте их в настройках Cursor, если клиент подхватывает переменные для MCP.
2. Полностью **перезапустите Cursor** — без рестарта список MCP не обновится.
3. **Settings → MCP**: у каждого сервера статус «подключён» / без ошибок в логе старта.
4. Для **Playwright** при первом запуске может понадобиться: `npx playwright install` в терминале.

Автоматически проверить подключение MCP из CI нельзя — только вручную в IDE после шагов выше.

## Миграция на официальный GitHub MCP

Пакет `@modelcontextprotocol/server-github` помечен как перенесённый в [github/github-mcp-server](https://github.com/github/github-mcp-server). Когда стабилизируете сценарий, можно заменить блок `github` в `mcp.json` по документации того репозитория.

## Рекомендуемый процесс

1. Поднять стек: `docker compose up -d postgres` (и остальное по необходимости).
2. Миграции: `alembic upgrade head`.
3. Проверка API: GET через MCP `fetch` или `curl`; сценарии с телом — тесты/терминал.
4. Отладка БД: MCP `postgres` для SELECT; логи — файлы в репо + `docker compose logs` в терминале.
5. PR: MCP `github`; локальные коммиты — git / Cursor Source Control.

## Примеры промптов

- «Подними postgres из docker-compose, выполни миграции, проверь `GET` к локальному API и покажи ответ.»
- «Через Postgres MCP покажи схему таблицы X и последние 5 строк.»
- «Найди traceback в выводе терминала / логах и предложи исправление.»
- «Открой PR N в репозитории org/repo и кратко опиши риски.»
