# Card: Гомельский ледовый дворец спорта
- arena_id: 33
- slug: gomel-lds
- verified_at: 2026-09-07
- verified_by: batch-D ice parser task (web only, без звонка)

Имя по заданию: «Гомельский ледовый дворец спорта», ул. Мазурова, 110, Гомель — домашняя арена ХК «Гомель». Не путать с id=34 «Ледовый каток Солнечный» (другой адрес). Расписание МК публикуется еженедельным новостным постом на https://gomel.hockey.by/news/ (пример: news445332.html, 31 авг – 6 сен 2026).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | адрес текстовый, обратное геокодирование не делали | 2026-09-07 |
| phone | касса 8 0232 51 25 23 ; администратор +375 29 153 00 22 | сам пост https://gomel.hockey.by/news/sobytie/news445332.html («Справки по телефонам») | 2026-09-07 |
| website_url | https://gomel.hockey.by/news/ | лента новостей клуба, откуда еженедельно берётся расписание МК | 2026-09-07 |
| opening_hours | unknown | явного общего графика (не сеансов МК) на сайте не нашли | 2026-09-07 |
| season | unknown | крытый дворец, месяцы сезона не указаны | 2026-09-07 |
| amenities | skate_rental: true; skate_sharpening: unknown; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | «Прокат коньков: 5 рублей» — тот же еженедельный пост | 2026-09-07 |
| short_description | Ледовый дворец спорта, домашняя арена ХК «Гомель» (ул. Мазурова, 110). Еженедельное расписание массовых катаний публикуется отдельным новостным постом на gomel.hockey.by; будни/выходные тарифы (сайт считает пятницу выходным днём по цене). | https://gomel.hockey.by/news/sobytie/news445332.html | 2026-09-07 |
| socials | VK https://vk.com/ihcgomel ; Instagram https://www.instagram.com/ihcgomel | ссылки на https://gomel.hockey.by/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| unknown | — | — | og:image главной https://gomel.hockey.by/upload/uf/cde/cdec29896c44b4d3d7608e62a4b3c46e.png — проверили визуально: это логотип/маскот клуба (132×165), не фото арены. В самом посте про расписание есть фото (`/upload/images/7-08/New Folder/234235.jpg`), но без подписи и уверенности, что это именно этот дворец, а не общая иллюстрация — не берём. Чистого фото льда/арены с понятной атрибуцией за отведённое время не нашли — не блокер, оставляем `unknown`. |

## Conflicts
- Ценовое деление «пн-чт» / «пт-вс» на сайте — пятница тарифицируется как выходной день (12 руб.), а не как будний; это не ошибка парсера, так буквально написано в посте.
