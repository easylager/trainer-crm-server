# Spec Kit (Spec-Driven Development) в этом репозитории

В проект добавлен **[GitHub Spec Kit](https://github.com/github/spec-kit)** — набор шаблонов и slash-команд для работы «сначала спека и план, потом код».

## Что уже установлено

| Путь | Назначение |
|------|------------|
| [`.cursor/commands/`](../.cursor/commands/) | Команды Cursor: `/speckit.*` |
| [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) | Конституция проекта (принципы разработки) |
| [`.specify/templates/`](../.specify/templates/) | Шаблоны spec / plan / tasks / checklist |
| [`.specify/scripts/bash/`](../.specify/scripts/bash/) | Вспомогательные скрипты (ветки фич, проверки) |

Инициализация: `specify init --here --force --ai cursor-agent --no-git --ignore-agent-tools` (шаблон **cursor-agent** + **sh**).

## Как пользоваться в Cursor

1. Открой чат агента и вызывай команды через **`/`** — должны появиться **`speckit.*`** (или вводи имя, например `speckit.constitution`).
2. Типичный порядок (как в [официальном README](https://github.com/github/spec-kit?tab=readme-ov-file#-get-started)):
   - **`/speckit.constitution`** — уточнить/обновить принципы в `.specify/memory/constitution.md`
   - **`/speckit.specify`** — что строим (требования, сценарии), без привязки к стеку
   - **`/speckit.clarify`** *(опционально)* — закрыть пробелы в формулировках до плана
   - **`/speckit.plan`** — стек, архитектура, как внедрять в *этом* репо
   - **`/speckit.checklist`** *(опционально)* — чеклист качества требований
   - **`/speckit.tasks`** — разбивка на задачи
   - **`/speckit.analyze`** *(опционально)* — согласованность артефактов перед реализацией
   - **`/speckit.implement`** — пошаговая реализация по `tasks`

Артефакты фич обычно живут в `specs/<номер-ветки>-<slug>/` (создаётся скриптами при работе с веткой фичи).

### Одна ветка git (например `develop`): без привязки к имени ветки

Скрипты Spec Kit по умолчанию ожидают **ветку** вида `001-feature-slug`, совпадающую с папкой в `specs/`. Если весь код ведёшь в **`develop`** (или `main`), имя ветки **не обязано** совпадать с папкой спеки. Достаточно указать, **какая папка `specs/...` сейчас «активна»**:

1. **Переменная окружения** (приоритетнее всего):  
   `export SPECIFY_FEATURE=002-mini-app-client-refactor`  
   Удобно в сессии терминала или в оболочке перед запуском `check-prerequisites.sh` и slash-командам, которые его вызывают.

2. **Файл** [`.specify/active-feature.example`](../.specify/active-feature.example) → скопируй в **`.specify/active-feature`** одну строку — basename каталога фичи, например `002-mini-app-client-refactor`. Файл **в `.gitignore`**: у каждого разработчика свой, без конфликтов в merge. Скрипт [`common.sh`](../.specify/scripts/bash/common.sh) читает его, если `SPECIFY_FEATURE` не задан.

3. **`crew_kit`**: путь к фиче задаётся явно:  
   `PYTHONPATH=. python3 -m tools.crew_kit --feature-dir specs/002-mini-app-client-refactor`  
   (ветка git не важна.)

Папки в `specs/` по-прежнему удобно называть `NNN-slug`, чтобы не путать фичи — это **не** требование git-ветки, а порядок в репозитории.

## Прокачка: не «дописывание руками», а цикл spec → prompt → code → refactor

Это **не отдельная npm-библиотека**, а дисциплина + инструменты Cursor/агента. Ниже — как добиться **multi-file reasoning** (рассуждение по нескольким файлам), **«ask codebase» вместо устаревшей доки** и **архитектуры из spec**.

### 1. Multi-file reasoning (не автокомплит)

- В **Agent / Composer** давай контекст пачкой: **`@файл`**, **`@папка`**, или выделение области.
- Для широкого охвата: **`@Codebase`** (или поиск по репо в чате) + явный вопрос: «где делается X и какие контракты затрагивает изменение».
- Делай запрос **с ограничением**: файлы/слои (`src/application/`, `src/api/`, `src/bot/`) — так меньше галлюцинаций и быстрее ответ.

### 2. «Ask codebase» как замена документации

- **Живая правда** — код и `specs/…/spec.md`, а не один большой README.
- Перед фичей: «прочитай `constitution.md` + `specs/…/plan.md` + затронутые модули».
- После мержа при необходимости обновляй только **узкие** доки (например Railway/deploy), а не дублируй архитектуру вручную везде.

### 3. Автогенерация «архитектуры по spec»

В этом репо это уже закрывает **`/speckit.plan`** (и при необходимости clarify/analyze):

- **`plan.md`** — технический контекст, структура каталогов, Constitution Check.
- **`data-model.md`**, **`contracts/`**, **`research.md`** — появляются из фазы плана, а не «из головы».

То есть **архитектурный артефакт привязан к spec**, а не отдельный вечно устаревающий док.

### 4. Цикл, который стоит закрепить привычкой

| Шаг | Действие |
|-----|----------|
| **Spec** | `/speckit.specify` → `specs/…/spec.md` (сценарии, FR, границы) |
| **Prompt** | Один чёткий запрос агенту: цель + не трогать X + сослаться на spec/конституцию |
| **Code** | Маленькими коммитами по `tasks.md` или `/speckit.implement` |
| **Refactor** | После зелёных тестов: упростить, вынести дубли, выровнять слои (см. constitution) |

Повторяй цикл, пока spec не закрыт тестами и ревью — **не** «дописали страницу и забыли».

## Мультиагентный прогон (CrewAI, локально)

Опциональный **dev-only** слой: оркестратор ролей (архитектор → реализация → ревью) с **внешним циклом** и записью артефактов в каталог фичи. Не входит в runtime FastAPI/ботов.

### Практический порядок (вместе со Spec Kit)

1. В ветке фичи уже есть папка `specs/<номер>-<slug>/` с `spec.md`, `plan.md`, `tasks.md` (через `/speckit.*` или вручную).
2. Установи зависимости crew (один раз на машину/venv):

```bash
pip install -r requirements-crew.txt
```

3. Положи ключи и опции в **корневой `.env`** в репозитории (как для остального проекта). CLI **подхватывает `.env` сам** при запуске `python -m tools.crew_kit` (через `python-dotenv` из основного `requirements.txt`).

   - **OpenAI:** `OPENAI_API_KEY`, опционально `CREW_MODEL=gpt-4o-mini`.
   - **OpenRouter:** `OPENROUTER_API_KEY`, обязательно `CREW_MODEL` с префиксом провайдера, например `openai/gpt-4o-mini`.
   - Опционально: `CREW_PYTEST_TIMEOUT` (секунды для `pytest` при `--run-pytest`, по умолчанию `300`).

4. Проверка без LLM — что контекст собирается:

```bash
cd /path/to/trainer-crm-belarus
PYTHONPATH=. python3 -m tools.crew_kit --dry-run --feature-dir specs/001-mini-app-theme-css
```

5. Полный прогон — результат в `<feature-dir>/crew_artifacts/` (`01_architect.md`, `iteration_01.md`, `iteration_01_proposed.diff`, при необходимости `final_summary.md`):

```bash
PYTHONPATH=. python3 -m tools.crew_kit --feature-dir specs/001-mini-app-theme-css --max-iters 3 --verbose
```

6. С регрессией через тесты после каждой итерации (фиксированная команда `pytest -q tests/`):

```bash
PYTHONPATH=. python3 -m tools.crew_kit --feature-dir specs/001-mini-app-theme-css --run-pytest
```

7. В Cursor открой `crew_artifacts/`, перенеси нужные изменения в код вручную или через **`/speckit.implement`**, прогони тесты и закоммить.

Агенты используют только **read-only** инструменты с allowlist путей (`src/`, `specs/`, `static/webapp/`, `migrations/`, `tests/`, `docs/`). Содержимое `.env` в промпты **не подставляется**. Код в репозиторий **не пишется** автоматически: только артефакты в `crew_artifacts/`.

## CLI (опционально)

Установка/обновление **Specify** (менеджер пакетов `uv`):

```bash
uv tool install specify-cli --force --from git+https://github.com/github/spec-kit.git@v0.4.0
specify check
```

Повторная инициализация в этом каталоге обычно **не нужна**; при необходимости см. `specify init --help`.

## Доступы

Для работы Spec Kit **отдельные токены не нужны**. Если `specify` при скачивании шаблона упирается в лимиты GitHub API, можно выставить `GITHUB_TOKEN` / `GH_TOKEN` (см. [документацию spec-kit](https://github.com/github/spec-kit)).
