# Global ICE Мозырь — projected weekly grid

- arena_id: 44
- slug: mozyr-global-ice
- parser_key: weekly_grid_v1
- city: Мозырь (BY, Europe/Minsk)

## Source

Нет машиночитаемой сетки сеансов. Факты — Instagram [@global_ice_](https://www.instagram.com/global_ice_/), подтверждены владельцем 2026-10-07 (см. `.ai/tasks/TASK-205.md`).

## job.config

См. `src/ingestion/seed_config_mozyr_global_ice.py` (`MOZYR_GLOBAL_ICE_CONFIG`).

- `schedule_basis`: `projected`
- Горизонт 14 дней от `minsk_today()` (или `run_date` в тестах)
- Шаг стартов 60 мин, сеанс 45 мин; последний старт = `close` − 1 ч
- Исключённые окна Пн/Вт/Ср/Пт 17:45–18:45 (сеанс 18:00 не публикуется)
- Цены (minor): будни 900/600, выходные 1000/700, прокат 700

## Fixtures

Нет HTTP-фикстур — адаптер не ходит в сеть.
