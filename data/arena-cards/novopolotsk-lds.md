# Card: Ледовый дворец (Новополоцк, ХК «Химик»)
- arena_id: 30
- slug: novopolotsk-lds
- verified_at: 2026-09-07
- verified_by: TASK ice-regional-parsers-batch-b (web only, без звонка)

Прод-CSV: «Ледовый дворец», ул. Молодёжная, 94Б (lat 55.5069684, lon 28.7024495). Оператор — ХК «Химик» (hchimik.hockey.by).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | Nominatim reverse `lat=55.5069684&lon=28.7024495` → `class=building`, `suburb=Усход`, без `city_district` https://nominatim.openstreetmap.org/reverse?lat=55.5069684&lon=28.7024495&format=json&addressdetails=1 — точка попала на соседний жилой дом (`house_number=235`), не на сам дворец; Новополоцк без внутригородских районов | 2026-09-07 |
| phone | 8 (0214) 50-65-22 | https://hchimik.hockey.by/mass-skating/ («для справок») | 2026-09-07 |
| website_url | https://hchimik.hockey.by/mass-skating/ | страница МК; корень hchimik.hockey.by | 2026-09-07 |
| opening_hours | unknown | явного блока часов работы дворца на сайте нет, только сетка сеансов МК | 2026-09-07 |
| season | unknown | явных месяцев сезона на странице нет | 2026-09-07 |
| amenities | skate_rental: true; skate_sharpening: true; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | «Стоимость проката коньков» и «заточки коньков» — строки Прейскуранта на той же странице | 2026-09-07 |
| short_description | Ледовый дворец ХК «Химик», ул. Молодёжная, 94Б. Основная арена — светодиодное освещение, два электронных табло; отдельно крытая тренировочная площадка. | https://hchimik.hockey.by/clubs/arena/ | 2026-09-07 |
| socials | Instagram https://instagram.com/hchimik ; VK https://vk.com/hchimik ; Telegram https://t.me/hchimik | футер https://hchimik.hockey.by/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://hchimik.hockey.by/clubs/arena/1.jpg | operator | ХК «Химик» | Подписано на странице «Арена хоккейного клуба "Химик" (Новополоцк)»: https://hchimik.hockey.by/clubs/arena/ — фото основной ледовой арены. **нужно разрешение**. Локально не копировали. |

## Conflicts
- Nominatim reverse на точке из CSV попал на жилой дом по соседству (`building`, house_number 235), не на сам дворец — адрес брать из CSV/сайта, координатную точку не считать точным пином дворца.
- Детской цены на «Прейскуранте» нет — есть льготный (8 руб.) и «сопровождающий» (1 руб.) тарифы, это НЕ `price_child_minor` (см. .ai/parsers/novopolotsk-lds.md); в профиль/парсер не подставлять.
