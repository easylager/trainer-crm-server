# Компания на лёд

Сбор на один сеанс: общий порог, одна запись на все карточки и ссылки, ответы «Иду / Может / Не могу». Зов (`/zovi`, `ice_invites`) это не заменяет.

Флаг: `ICE_COMPANY_CITY_IDS` — список `city_id` через запятую. Пусто — фича выключена, кнопка на карточке не рисуется, создать компанию нельзя. Уже созданные ссылки `/k/{code}` открываются.

`max_people` хранится и никого не отсекает: порог `min_people` — цель, не потолок.

Срок хранения строк: `ICE_COMPANY_RETENTION_DAYS` (по умолчанию 30) после конца сеанса. Согласовать с юристом.

Организаторские действия требуют `initData` клиентского бота (HMAC-SHA256, `hmac.compare_digest`, возраст `auth_date` — `TELEGRAM_WEBAPP_INIT_DATA_MAX_AGE_SEC`, по умолчанию 24 часа). Веб и Viber отвечают анонимным токеном. Повтор того же ключа меняет статус.

## Создание

`POST /api/public/ice-companies`

Заголовок `X-Telegram-Init-Data`.

```json
{
  "session_id": 123,
  "min_people": 3,
  "max_people": null,
  "display_name": "Аня",
  "name": "",
  "surface": "miniapp"
}
```

`201`:

```json
{
  "public_code": "k7m2pqwx",
  "name": "",
  "status": "open",
  "min_people": 3,
  "max_people": null,
  "going_count": 1,
  "maybe_count": 0,
  "cant_count": 0,
  "going": [{"display_name": "Аня"}],
  "maybe": [],
  "needs_reconfirm": false,
  "card_text": "Катаемся в субботу\nЧижовка-Арена, сб 19:00\nИдут 1 из 3: Аня\nНе хватает 2",
  "together_line": "",
  "event": {
    "kind": "public_skate",
    "starts_at": "2026-10-17T16:00:00+00:00",
    "ends_at": "2026-10-17T17:00:00+00:00",
    "venue_label": "Чижовка-Арена",
    "venue_ref": "arena:12",
    "version": 1,
    "cancelled": false
  },
  "page_url": "https://glideclub.by/k/k7m2pqwx",
  "calendar_url": "https://glideclub.by/k/k7m2pqwx/event.ics"
}
```

`404` — город выключен или сеанса нет. `401` — нет initData. `429` — больше 5 активных компаний.

## Чтение

`GET /api/public/ice-companies/{public_code}` — то же тело, без ключей участников.

## Ответ

`POST /api/public/ice-companies/{public_code}/responses`

Идемпотентно по паре компания + участник.

```json
{
  "status": "going",
  "display_name": "Саша",
  "participant_token": "",
  "consent": true,
  "source": "web",
  "website": ""
}
```

`website` — honeypot, непустое поле ответ не записывает. `source`: `web` или `viber`. Из Telegram достаточно initData, `source` станет `tg`.

Ответ — то же публичное тело плюс `participant_token`, если токен выпущен сейчас. Его хранит устройство. Повтор с тем же токеном меняет статус.

`422` — нет согласия, ссылка в имени, плохое имя. `429` — чаще лимита в минуту (IP и токен) или больше 50 ответов.

## Остальные действия

| Метод | Путь | Кто |
|---|---|---|
| POST | `/api/public/ice-companies/{code}/cancel` | организатор |
| POST | `/api/public/ice-companies/{code}/weekly` `{"enabled": true}` | организатор, повтор в чат через неделю |
| POST | `/api/public/ice-companies/{code}/repeat` `{"session_id": null}` | организатор. Точный сеанс — новая компания. Иначе `{"candidates":[...]}` |
| DELETE | `/api/public/ice-companies/{code}/me` | initData или `{"participant_token":"..."}` |
| POST | `/api/public/ice-companies/{code}/telegram-prepare` | initData. `prepared_message_id` или пусто и `inline_query` `k:{code}` |
| GET | `/k/{code}` | страница, `noindex` |
| GET | `/k/{code}/og.png` | 1200×630, кэш 15 минут |
| GET | `/k/{code}/event.ics` | календарь |

Кнопка в мини-аппе: `startapp=company_{session_id}` открывает `/webapp/ice-company?s=`.
