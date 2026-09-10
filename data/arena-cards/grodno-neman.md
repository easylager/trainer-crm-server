# Card: ЛДС «Неман» (Гродно)
- arena_id: 11
- slug: grodno-neman
- verified_at: 2026-09-07
- verified_by: TASK ice-regional-parsers-batch-b (web only, без звонка)

Прод-CSV: «Ледовый дворец спорта», ул. Коммунальная 3а (lat 53.68819, lon 23.824166). Оперирует ХК «Неман»; клуб также использует ФОК ур. Пышки, 13 — на снимках МК проходят там (`session_label`: «лёд Пышки»), это тот же прод arena_id=11, не отдельная арена. Не путать с id=10 ТЦ «Тринити».

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Ленинский район (Ленінскі раён) | Nominatim reverse `lat=53.68819&lon=23.824166` → `name=Лядовы палац спорту`, `city_district=Ленінскі раён` https://nominatim.openstreetmap.org/reverse?lat=53.68819&lon=23.824166&format=json&addressdetails=1 (точка совпадает с адресом Коммунальная, 3а) | 2026-09-07 |
| phone | 8 (0152) 74 22 85 | https://neman.hockey.by/ (футер, почтовый адрес клуба) | 2026-09-07 |
| website_url | https://neman.hockey.by/ | официальный клубный сайт (ФХРБ hockey.by); НЕ https://hcneman.by/ (виджет расписания там протух, см. .ai/parsers/grodno-neman.md) | 2026-09-07 |
| opening_hours | unknown | на сайте нет блока часов работы дворца; есть только даты/время конкретных сеансов МК из новостей | 2026-09-07 |
| season | unknown | сайт публикует «сезон 2026/2027» (хоккейный, не МК) — на явные месяцы работы дворца это не указывает | 2026-09-07 |
| amenities | skate_rental: true; skate_sharpening: unknown; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | «Прокат коньков — 5р.» в анонсах МК (напр. https://neman.hockey.by/news/sobytie/news446875.html); остальное не названо | 2026-09-07 |
| short_description | Ледовый дворец спорта ХК «Неман», ул. Коммунальная, 3а. Массовые катания анонсируются постами в новостной ленте клуба, не отдельной страницей расписания. | https://neman.hockey.by/news/sobytie/news446875.html + футер сайта | 2026-09-07 |
| socials | Instagram https://instagram.com/hcneman ; VK https://vk.com/hcneman ; Telegram https://t.me/hcnemangrodno | футер https://neman.hockey.by/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://neman.hockey.by/cache/upload/iblock/f0d/1xz8xaq6g12uoqkto7fdtrsrbdp4qu26/mass_sm-307x205.jpg | operator | ХК «Неман» | Превью-фото у самого поста «СТАРТ МАССОВЫХ КАТАНИЙ» https://neman.hockey.by/news/sobytie/news446875.html — фото льда/сеанса МК. **нужно разрешение**. Локально не копировали. |

## Conflicts
- Два ХК «Неман»-льда: ЛДС Коммунальная 3а (прод arena_id=11, эта карточка) и ФОК ур. Пышки, 13, где физически проходит МК по снимку 2026-09-06 — не заводить как вторую арену, писать `session_label`.
- `hcneman.by` (отдельный домен) — виджет расписания там стоит на 05.04.2026 (см. .ai/parsers/grodno-neman.md); карточка и live-парсер используют `neman.hockey.by`, не `hcneman.by`.
