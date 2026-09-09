# Card: ТЦ «Тринити» (Гродно)
- arena_id: 10
- slug: grodno-triniti
- verified_at: 2026-09-07
- verified_by: TASK ice-regional-parsers-batch-b (web only, без звонка)

Прод-CSV: `ТЦ "Тринити"`, «проспект Янки Купалы 87, Hrodna, Hrodna Region 230026» (lat 53.649866, lon 23.854538). Каток — часть ТРК TRINITI, отдельный сайт ice.triniti-grodno.by.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Октябрьский район (Кастрычніцкі раён) | Nominatim reverse `lat=53.649866&lon=23.854538` → `class=leisure,type=ice_rink`, `city_district=Кастрычніцкі раён` https://nominatim.openstreetmap.org/reverse?lat=53.649866&lon=23.854538&format=json&addressdetails=1 | 2026-09-07 |
| phone | +375 (29) 311-23-23 | https://ice.triniti-grodno.by/ (шапка + meta description) | 2026-09-07 |
| website_url | https://ice.triniti-grodno.by/ | сайт катка (не общий сайт ТРК TRINITI) | 2026-09-07 |
| opening_hours | unknown | на сайте нет отдельного блока часов работы; расписание сеансов 11:00–22:45 (`api/ice.php`) — это сетка МК, не opening_hours | 2026-09-07 |
| season | unknown | «круглый год» в meta description, явных месяцев не указано | 2026-09-07 |
| amenities | skate_rental: true; skate_sharpening: unknown; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | прокат коньков — отдельная строка прайса https://ice.triniti-grodno.by/prajs.html; остальное на сайте не названо | 2026-09-07 |
| short_description | Ледовый каток в ТРК TRINITI — круглогодичная зона отдыха, массовое катание с сеансами каждый час; билет и прокат через кассу или онлайн. | https://ice.triniti-grodno.by/ (meta description + раздел «Ледовая арена») | 2026-09-07 |
| socials | VK https://vk.com/triniti_grodno ; Facebook https://facebook.com/trk.triniti | футер https://ice.triniti-grodno.by/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://ice.triniti-grodno.by/assets/cache_image/slider/main-page-photo_540x298_b70.jpg | operator | ТЦ «Тринити» | Раздел «ЛЕДОВАЯ АРЕНА» на главной странице https://ice.triniti-grodno.by/ — фото самого катка. **нужно разрешение**. Локально не копировали. |

## Conflicts
- Нет конфликтов адреса/названия — прод-CSV, `api/ice.php` (JSON-фид сеансов) и главная страница согласуются.
