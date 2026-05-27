# Client booking URL contract

Frozen entry points for client Mini App booking. **Do not break** without bot + integration test updates.

## API (unchanged)

| Method | Path | Auth |
|--------|------|------|
| `GET` | `/api/webapp/client/session` | `X-Telegram-Init-Data` or `?init_data=` |
| `GET` | `/api/webapp/client/slots` | same |
| `POST` | `/api/webapp/client/booking` | same + optional `Idempotency-Key` header |

### POST `/client/booking` body

```json
{
  "slot_id": 123,
  "phone": "+375291112233",
  "service_id": 1,
  "service_price_variant_id": 5,
  "request_id": null,
  "first_name": "Имя",
  "last_name": "Фамилия",
  "comment": "optional"
}
```

### Success response (200)

```json
{
  "success": true,
  "booking_id": 456,
  "used_primary_venue_for_online_booking": false
}
```

`used_primary_venue_for_online_booking` is present only when the client filtered a non-primary arena but the slot landed on the trainer's primary venue.

---

## Static pages (booking hosts)

| Route | File | Role |
|-------|------|------|
| `/webapp/book` | `book.html` | Legacy / bot deep link; week picker; shim → catalog when `slot_id` or trainer-only |
| `/webapp/catalog` | `catalog.html` | Primary discovery + inline booking funnel |

Shared module: `booking-client.js`, `booking-deeplink.js`.

---

## Query parameters

| Param | Hosts | Meaning |
|-------|-------|---------|
| `trainer_id` | book, catalog | Required trainer |
| `slot_id` | book, catalog | Pre-select slot → booking form |
| `service_id` | book, catalog | Service filter / form default |
| `arena_id` | book, catalog | Arena filter for slots |
| `city_id` | catalog | Catalog city filter |
| `request_id` | book | Book from trainer response to client request |
| `force_service_choice` | book | Bot: open service picker (`1`) |
| `from` | book, catalog | Back-navigation origin (see below) |
| `init_data` | all | Telegram WebApp credential (also sent as header) |
| `tab` | catalog | `catalog` \| `my_trainer` |
| `v` | book (bot) | Cache buster in bot URLs (`20260420d`) |

### `from=` back targets

| Value | Back / success CTA target |
|-------|---------------------------|
| `hub` | `/webapp/client-home` |
| `requests` | `/webapp/client-requests` |
| `saved-trainers` | `/webapp/client-saved-trainers` |
| *(absent)* | Catalog trainer card (book) or in-app back (catalog) |

Resolved by `BookingClient.resolveBookingReturn(from)`.

---

## Bot handlers (`client_handlers.py`)

| Function | URL pattern |
|----------|-------------|
| `_trainer_book_rows` | `{base}/webapp/book?trainer_id={id}&v=20260420d[&service_id=…][&force_service_choice=1]` |
| `_trainer_catalog_card_rows` | `{base}/webapp/catalog?trainer_id={id}[&city_id=…][&service_id=…][&arena_id=…]` |

Bot URLs **must stay** on `/webapp/book`; the page shim redirects to catalog when appropriate.

---

## Hub intent engine

Hub slot chip → `catalog?trainer_id&slot_id&from=hub` (strangler; book URL still valid for bot).

`buildBookPathFromHubContext` in `client-home-main.js` builds catalog path when `slot_id` is set.

---

## Deep-link normalizer (`booking-deeplink.js`)

Parses query → canonical state:

```javascript
{
  trainerId, slotId, serviceId, arenaId, requestId, from,
  forceServiceChoice, host: 'book' | 'catalog'
}
```

Shim rules on `book.html` load:

1. `slot_id` present → redirect to `catalog?…` (preserve query)
2. Only `trainer_id` (no slot, no week flow yet) → redirect to `catalog?trainer_id=…`
3. Otherwise → stay on `book.html` (week picker)

---

## Hub bootstrap

`GET /api/webapp/client/hub/bootstrap` includes `passes[]` in the same round-trip (no separate `/client/passes` fetch from hub primary panel).

---

## Regression checklist (manual)

- [ ] Bot «Записаться» → book shim → catalog or week picker
- [ ] Hub nearest slot → catalog form → «Назад» → hub
- [ ] Requests «Записаться» → form → success → «Записи» tab
- [ ] Saved trainers → book → back → saved list
- [ ] Catalog trainer card → slot pick → submit → full-screen success
- [ ] POST booking idempotency: repeat same `Idempotency-Key` returns same `booking_id`
