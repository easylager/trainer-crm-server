# Card: Ледовая площадка (Островец)
- arena_id: 41
- slug: ostrovets-lds
- verified_at: 2026-09-07
- verified_by: TASK ice-regional-parsers-batch-c (web only, без звонка)

Адрес в проде: Октябрьская улица, 39, Островец. Оператор — ГУ «Островецкая специализированная детско-юношеская школа олимпийского резерва» (sdushor-ostrovets.by).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | не проверялся | 2026-09-07 |
| phone | +375 (29) 896-62-34, +375 (1591) 3-46-50 (администратор ледовой площадки, также Viber/WhatsApp/Telegram) | https://sdushor-ostrovets.by/o-nas/ | 2026-09-07 |
| website_url | https://sdushor-ostrovets.by/katanie-na-konkah/ | прейскурант https://sdushor-ostrovets.by/prejskurant-cen/ | 2026-09-07 |
| opening_hours | unknown | явный общий график не найден; расписание МК — по недельным таблицам на странице катания | 2026-09-07 |
| season | unknown | явных месяцев сезона МК на сайте нет | 2026-09-07 |
| amenities | skate_rental: true («Услуга предоставления коньков», Перечень №8 п.1.8); skate_sharpening: true (п.1.9 прейскуранта); parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | https://sdushor-ostrovets.by/prejskurant-cen/ | 2026-09-07 |
| short_description | Ледовая площадка при СДЮШОР; расписание массового катания — две еженедельные HTML-таблицы, «нет катаний» = сеанса нет в этот день. | https://sdushor-ostrovets.by/katanie-na-konkah/ | 2026-09-07 |
| socials | Instagram https://www.instagram.com/ostrovets_arena/ (и школьный https://www.instagram.com/sdushor_ostrovets/) ; VK https://vk.com/public221636126 | https://sdushor-ostrovets.by/katanie-na-konkah/ ; https://sdushor-ostrovets.by/o-nas/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://sdushor-ostrovets.by/wp-content/uploads/2026/06/photo_2026-06-25_13-39-33-e1782384412823.jpg | operator | ГУ «Островецкая СДЮШОР» | og:image страницы https://sdushor-ostrovets.by/katanie-na-konkah/ — реальное фото массового катания на этом льду (посетители на коньках). Локально не копировали, **нужно разрешение**. |

## Conflicts
- `/ceny-na-uslugi/` (зал бокса, ул. Набережная 13) — не источник цен МК; цены МК только с `/prejskurant-cen/` (Перечень № 8).
- Меню-пункт `/kontakty/` на сайте отдаёт 404; контакты и адрес фактически на `/o-nas/`.
