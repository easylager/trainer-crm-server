# Parser spec: Жлобин Ледовый дворец «Металлург»

- arena_id: 35
- city: Жлобин
- parser_key: null
- cadence: null
- requires_by_egress: false

## Sources

- клуб: https://metallurg.hockey.by/clubs/arena/ — описание арены, **без сетки МК**. `/raspisanie/` → 404.
- ЦОР: https://zorzhlobin.by/uslugi/ — карточка «Массовое катание» 45 мин: билет 7,00 без коньков, прокат пары 5,00. Телефоны. **Дат и HH:MM нет.**
- https://zorzhlobin.by/obekty/ledovyj-dvorec/ — про МК одной фразой, без расписания.

## How to extract (reverse)

Нет. Прейскурант без слотов не публиковать.

## Canonical example (expected after validate)

Нет.

## Fixture

Нет.

## Blockers / notes

- **skip.** Цены известны, расписания нет. Не выдумывать вечерний слот.
