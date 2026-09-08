# Arena card dossiers (CONTENT lane)

Одна арена — `minsk-<slug>.md`. Это вход для TASK-063 (загрузка), не код и не слоты МК.

Спека: [`../tasks/TASK-073.md`](../tasks/TASK-073.md).  
Парсеры слотов: [`../parsers/`](../parsers/README.md) — **другая** папка.

Не класть сюда расписание сеансов. Не скачивать фото из поиска.

**Презентация (2026-09-06):** фото с официального сайта/соцсети катка грузим в продукт для демо (`license=operator`, attribution). «Ждём grant» в досье — не блокер загрузки; письменное согласование — после презентации. Google/стоки — по-прежнему запрещены.

## Шаблон

```markdown
# Card: <Arena name>
- arena_id:
- slug:
- verified_at:
- verified_by:

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district |  |  |  |
| phone |  |  |  |
| website_url |  |  |  |
| opening_hours |  |  |  |
| season |  |  |  |
| amenities | skate_rental / … |  |  |
| short_description |  |  |  |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
|  |  |  |  |

## Conflicts
-
```
