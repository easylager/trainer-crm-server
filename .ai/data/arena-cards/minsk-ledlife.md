# Card: СДЮШОР по фигурному катанию
- arena_id: 4
- slug: minsk-ledlife
- verified_at: 2026-09-06
- verified_by: CONTENT TASK-073

CSV name: `СДЮШОР по фигурному катанию`. Сайт оператора `ledlife.by`. Origin с этого IP — **403** (nginx/1.10.3). Часы, телефон и amenities **не** взяты из сниппетов поиска и **не** выдуманы.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Московский район | Nominatim reverse по CSV coords 53.85639,27.4907 (`city_district`; suburb Петровщина) | 2026-09-06 |
| phone | unknown | GET https://ledlife.by/kontakty/ и /massovye_kataniya/ → 403 nginx/1.10.3 | 2026-09-06 |
| website_url | https://ledlife.by/ | официальный origin; 2026-09-06 HTTP 403, хост резолвится (178.172.172.91) | 2026-09-06 |
| opening_hours | unknown | origin 403; часы из поисковых сниппетов в профиль не писать | 2026-09-06 |
| season | unknown | нет открываемого источника с месяцами сезона | 2026-09-06 |
| amenities | skate_rental=unknown; skate_sharpening=unknown; parking=unknown; locker_rooms=unknown; cafe=unknown; accessibility=unknown | origin 403 | 2026-09-06 |
| short_description | СДЮШОР по фигурному катанию, крытый каток (ledlife.by), адрес в CSV: Минск, пр-т Каролинский, 5. Карточка без часов и телефона, пока origin не открыть с BY IP. | CSV `.ai/data/minsk-arenas-prod.csv` id=4; блокер: GET https://ledlife.by/massovye_kataniya/ → 403 | 2026-09-06 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://ledlife.by/foto/ | operator | СДЮШОР / ledlife.by | Раздел фото на origin. GET 403 — не скачивали. Нужно разрешение + BY-egress, чтобы выбрать кадр. |
| https://www.instagram.com/led_life.by/ | operator | ledlife.by | URL из шапки origin (усечённый BY-снимок). Посты IG не скачивать — нужно разрешение. |
| — | — | — | Локальных файлов нет. Поиск картинок не использовался. |

## Conflicts
- **403 / BY-blocker:** `https://ledlife.by/massovye_kataniya/`, `https://ledlife.by/kontakty/`, `https://ledlife.by/` — 403 nginx/1.10.3 с не-BY IP (2026-09-06). Сетку МК и «режим 7:00–23:00» из выдачи поиска в профиль не переносить.
- Адрес: CSV `пр-т Каролинский, 5`; Nominatim `Каролинский проезд` + suburb Петровщина. Индексаторы часто дают `проезд Каролинский, 5-4`. Не склеивать, пока origin не подтвердит.
- Усечённый BY-HTML шапки (не SoT на сегодня с этого IP) показывал: `8 (017) 396-62-74; 8 (017) 396-62-81` (ледовый каток) / `8 (017) 369-17-57` (УСК); Instagram / Telegram / Viber. Это **не** verified факты профиля 2026-09-06.
- Не путать с катком Юность (`junost.by`, arena_id 8): тот же класс 403, другая арена.
