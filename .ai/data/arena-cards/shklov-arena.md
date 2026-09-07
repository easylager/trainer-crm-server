# Card: Шклов Ледовая арена
- arena_id: 42
- slug: shklov-arena
- verified_at: 2026-09-07
- verified_by: batch-D ice parser task (web only, без звонка)

Имя по заданию: «Шклов Ледовая арена», ул. Почтовая 2, Шклов. Сайт ГУ «СДЮШОР Шкловского района» http://sportshklov.by/ — **только HTTP**: HTTPS падает на несовпадении имени TLS-сертификата, это не означает «сайта нет».

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | адрес текстовый, обратное геокодирование не делали | 2026-09-07 |
| phone | касса 77-871, охрана 77-803 (внутренние номера с еженедельной афиши; код города +375 2239 предполагается, но отдельно на сайте не подтверждён) | http://sportshklov.by/wp-content/uploads/2026/09/31.08-06.09.2026.jpg (OCR нижней строки афиши) | 2026-09-07 |
| website_url | http://sportshklov.by/ (категория расписаний: http://sportshklov.by/category/raspisania/) | — | 2026-09-07 |
| opening_hours | unknown | явного графика на сайте не нашли | 2026-09-07 |
| season | unknown | крытая арена, месяцы сезона не указаны | 2026-09-07 |
| amenities | skate_rental: true; skate_sharpening: unknown; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | «Прокат коньков: для взрослых 4,20р / для детей до 14 лет» — таблица http://sportshklov.by/uslugi/ | 2026-09-07 |
| short_description | Ледовая арена ГУ «СДЮШОР Шкловского района» (ул. Почтовая, 2). Расписание массового катания публикуется еженедельно афишей (JPG-фото) на sportshklov.by; в будни по 2 сеанса, в выходные по 4. | http://sportshklov.by/category/raspisania/ ; http://sportshklov.by/uslugi/ | 2026-09-07 |
| socials | unknown | на главной странице встроен только виджет VK-группы по числовому id (139412605), публичный адрес группы (vk.com/...) на сайте отдельно не указан — не подтверждён | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| unknown | — | — | Единственное найденное фото сайта — сама еженедельная афиша расписания (JPG), это график, а не фото арены/льда. Отдельного фото площадки на сайте за отведённое время не нашли — не блокер, оставляем `unknown`. |

## Conflicts
- Нет — цены (5,10/4,20 взрослый/детский, прокат 4,20 взрослый) берутся с отдельной страницы `/uslugi/`, а не с самой афиши (на афише цен нет).
