# Spec Kit (GitHub) и Cursor

В репозитории можно использовать [GitHub Spec Kit](https://github.com/github/spec-kit): цикл constitution → specify → plan → tasks → implement.

**Где лежат шаблоны:** каталоги `.cursor/` и `.specify/` добавлены в `.gitignore` — они остаются у разработчика локально (IDE, MCP, slash-команды). После клона при необходимости переустановите Spec Kit по документации upstream или скопируйте конфиг с коллеги.

**Фичи в репо:** папки `specs/<feature-id>/` (spec, plan, tasks) остаются в Git.

Связанные документы: [CI_CD.md](CI_CD.md), [TRAINER_MINI_APP_VISUAL_CONSTITUTION.md](TRAINER_MINI_APP_VISUAL_CONSTITUTION.md).
