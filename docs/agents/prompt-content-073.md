# Агент CONTENT — досье карточек Минска

Вставь в новый Agent-чат. Не код, не парсер слотов.

```text
Lane: CONTENT. TASK-073. Entrypoint: docs/epics/ice-discovery/agent-start.md then .ai/tasks/TASK-073.md then data/arena-cards/README.md.

Собери и сверь факты для карточки катка (телефон, сайт, часы, сезон, amenities, описание, район) и легальные фото.
Пиши только data/arena-cards/minsk-<slug>.md и photos/ при явной лицензии.

Не пиши src/, data/parsers/, слоты МК, цены сеансов.
Не скачивай картинки из Google/Яндекс. Только сайт/соцсеть катка, свои, разрешение оператора.
Прод-БД: только SELECT + SET default_transaction_read_only = on. Список арен: data/minsk-arenas-prod.csv.

Порядок: Замок, Минск-Арена, Чижовка, led.by. unknown лучше выдумки.
```
