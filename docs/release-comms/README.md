# Release comms — сообщения пользователям перед/во время релиза

## Отправка (2026-08-26 — Glide rebrand)

```bash
# 1. Превью себе
python -m scripts.broadcast_release_comms \
  --message docs/release-comms/2026-08-26-glide-rebrand.clients.md \
  --chat-id YOUR_TELEGRAM_ID

# 2. Dry-run
python -m scripts.broadcast_release_comms \
  --message docs/release-comms/2026-08-26-glide-rebrand.clients.md --dry-run

# 3. Рассылка (клиенты, затем тренеры) — до смены имени бота
python -m scripts.broadcast_release_comms \
  --message docs/release-comms/2026-08-26-glide-rebrand.clients.md
python -m scripts.broadcast_release_comms \
  --message docs/release-comms/2026-08-26-glide-rebrand.trainers.md
```

- [ ] clients sent: ___
- [ ] trainers sent: ___
- [ ] bot name/avatar updated: ___


Любое обновление с **видимыми** изменениями (имя бота, дизайн, UX, оплата, даунтайм) требует подготовленного сообщения **до** деплоя.

Шаблон: `TEMPLATE.md`. Пример точечной рассылки (только тренеры без профиля): `2026-09-01-simpler-onboarding.trainers.md` — в frontmatter `segment: pending_profile`.

## Чеклист релиза

1. **Draft** — скопировать `TEMPLATE.md` → `YYYY-MM-DD-<slug>.clients.md` и/или `.trainers.md`
2. **Review** — текст читается за 10 секунд; явно сказано «данные на месте»
3. **Preview** — отправить себе:
   ```bash
   python -m scripts.broadcast_release_comms --message docs/release-comms/....clients.md --chat-id YOUR_ID
   ```
4. **Dry-run** — посмотреть охват:
   ```bash
   python -m scripts.broadcast_release_comms --message docs/release-comms/....clients.md --dry-run
   ```
5. **Send** — за 5–15 мин **до** смены имени/аватарки бота:
   ```bash
   python -m scripts.broadcast_release_comms --message docs/release-comms/....clients.md
   python -m scripts.broadcast_release_comms --message docs/release-comms/....trainers.md
   ```
6. **Deploy** — код + смена профиля бота в BotFather
7. **Log** — отметить в файле релиза дату/время отправки и `--dry-run` counts

## Когда слать

| Нужно | Не нужно |
|-------|----------|
| Ребрендинг, новое имя бота | Внутренний рефакторинг |
| Новый экран / убрали кнопку | Багфикс без смены UX |
| Изменение оплаты / записей | Правка текста на второстепенном экране |
| Плановый даунтайм | |

## Порядок при смене бота

**Сначала** рассылка → **через 5–15 мин** новое имя и аватар в Telegram. Иначе пользователи видят незнакомого бота и не читают текст.

## Файлы доставки

Скрипт пишет журнал в `var/release-comms/<release_id>.<audience>.json` (не в git). Повторная отправка тем же `release_id` пропускает уже доставленных, если не указан `--force`.
