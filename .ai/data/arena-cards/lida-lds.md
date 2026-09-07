# Card: Ледовый дворец (Лида)
- arena_id: 37
- slug: lida-lds
- verified_at: 2026-09-07
- verified_by: TASK ice-regional-parsers-batch-b (web only, без звонка)

Прод-CSV: «Ледовый дворец», Качана 31 (lat 53.8954462, lon 25.3237632). Оператор — ГУ «Клуб по хоккею с шайбой «Лида», сайт hc-lida.by.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | Nominatim reverse `lat=53.8954462&lon=25.3237632` → `name=Лядовы палац`, без `city_district` (только `county=Лідскі раён`, сельский район) https://nominatim.openstreetmap.org/reverse?lat=53.8954462&lon=25.3237632&format=json&addressdetails=1 — Лида не делится на внутригородские районы | 2026-09-07 |
| phone | +375 15 464-41-32 (кассы), +375 15 464-41-36 (приёмная) | https://hc-lida.by/услуги/массовое-катание (кассы) и футер сайта (приёмная) | 2026-09-07 |
| website_url | https://hc-lida.by/услуги/массовое-катание | страница МК; корень hc-lida.by | 2026-09-07 |
| opening_hours | Кассы: ежедневно 12:30–21:00 в день проведения МК | https://hc-lida.by/услуги/массовое-катание | 2026-09-07 |
| season | unknown | явных месяцев сезона на странице нет | 2026-09-07 |
| amenities | skate_rental: true; skate_sharpening: true; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | прокат коньков и заточка — отдельные строки прайса на той же странице | 2026-09-07 |
| short_description | Ледовый дворец ГУ «Клуб по хоккею с шайбой «Лида», ул. Качана, 31. Расписание МК публикуется еженедельно (по понедельникам) фотографией на странице услуги, не HTML-таблицей. | https://hc-lida.by/услуги/массовое-катание | 2026-09-07 |
| socials | unknown | футер страницы — только generic-иконки share (telegram.org, facebook.com/ и т.п. без конкретного handle клуба), реальных аккаунтов не нашли | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://hc-lida.by/files/25059/obj/110/35683/img/346346345.jpg | operator | ГУ «Клуб по хоккею с шайбой «Лида» | Фото в теле страницы МК, ниже блока цен; `alt` пустой, конкретное содержимое кадра не подписано на странице — вероятно общий кадр льда/дворца, не проверено визуально. **нужно разрешение**. Локально не копировали. |
| https://hc-lida.by/files/25059/obj/110/35683/img/изображение_viber_2026-09-01_17-34-29-793%20(1).jpg | operator | ГУ «Клуб по хоккею с шайбой «Лида» | Это недельное расписание-фото (не портретный кадр арены) — источник для `weekday_schedule` в LIDA_LDS_CONFIG, не для витрины. |

## Conflicts
- Расписание: `/осп-сдюшор/расписание-работы-ледовой-арены` пустое (без сетки) — не SoT; SoT — еженедельное фото на `/услуги/массовое-катание`, см. .ai/parsers/lida-lds.md.
- Прайс: комбо «посещение с прокатом коньков» 15/12 руб. на фото ≠ каноническим `price_adult_minor`/`price_rental_minor` (9/7 + 6/5 раздельно) — не путать при обновлении карточки.
