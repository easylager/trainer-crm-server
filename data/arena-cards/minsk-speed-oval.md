# Card: Конькобежный стадион
- arena_id: 115
- slug: konkobezhnaya-arena
- verified_at: 2026-09-07
- verified_by: CONTENT oval ABWS object id=4 + saleframe/139 (без звонка)

Локальный CRM-ряд: id=115, slug `konkobezhnaya-arena` (не переименовывать slug). Официальное имя оператора — «Конькобежный стадион», не «Конкобежная арена». Адрес и точка: пр-т Победителей 111 / ABWS `lat=53.935930` `lon=27.481638` (отдельный объект от главной арены).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Центральный район | тот же комплекс, что Минск Арена (пр-т Победителей 111); Nominatim reverse главной арены `lat=53.9394&lon=27.4685` → `city_district=Центральный район` | 2026-09-07 |
| phone | +375 44 780-85-01 | ABWS init `settings.supportPhone` для seid=139: «Конькобежный стадион: +375(44)7808501» | 2026-09-07 |
| website_url | https://minskarena.by/ | официальный сайт МКСК; билеты МК oval: https://saleframe.minskarena.by/service/139 | 2026-09-07 |
| opening_hours | unknown | сетка МК только в кассе ABWS calendar, не как часы объекта | 2026-09-07 |
| season | unknown | на object.html нет месяцев сезона | 2026-09-07 |
| amenities | skate_rental: true; skate_sharpening: unknown; parking: true; locker_rooms: unknown; cafe: true; accessibility: true | skate_rental: ABWS service/138 «Прокат коньков на конькобежном стадионе». parking/cafe: ABWS `GET /api/v3/arena/home` objects id=7 «Паркинг», id=12 «Кафе, ресторан» того же комплекса. accessibility: описание object id=4 — физкультурно-оздоровительные услуги людям с инвалидностью | 2026-09-07 |
| short_description | Крытый конькобежный стадион МКСК «Минск-арена»: 400-метровая дорожка и массовое катание на овале. Билеты — saleframe service 139, прокат коньков — service 138. | ABWS object id=4 `shortDescription` + init performance «Массовое катание на конькобежной дорожке» | 2026-09-07 |
| socials | Facebook https://www.facebook.com/arenaminsk/ ; Instagram https://www.instagram.com/minskarenaby/ | JSON-LD `sameAs` на https://minskarena.by/ (тот же оператор) | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://abws.minskarena.by/uploads/objects/5D75EknaB.jpg | operator | МКСК «Минск-арена», объект «Конькобежный стадион»; ABWS home objects id=4 | фасад конькобежного стадиона (hero) |
| https://minskarena.by/img/object-bg.jpg | operator | https://minskarena.by/object.html | аэрофото комплекса (арена + конькобежный стадион) со страницы «Объекты» |

Не hero: графический баннер постов МК, концертный слайдер главной арены, SVG-логотип.

## Conflicts
- Имя в локальной CRM было с опечаткой «Конкобежная арена». Канон оператора — «Конькобежный стадион» (ABWS object.id=4).
- Телефон овальной кассы `+375 44 780-85-01` ≠ футер комплекса `+375 17 279-04-11` (карточка Минск Арены). Сюда — номер стадиона из `supportPhone`.
- Координаты овального объекта (53.935930, 27.481638) смещены относительно точки главной арены (53.9394, 27.4685). Не копировать lat/lon с arena 2.
- Слоты MK hockey/55 не принадлежат этой карточке.
