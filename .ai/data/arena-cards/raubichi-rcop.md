# Card: РЦОП по зимним видам спорта «Раубичи»
- arena_id: 15
- slug: raubichi-rcop
- verified_at: 2026-09-07
- verified_by: photo-research-batch-1

Оператор — Республиканский центр олимпийской подготовки по зимним видам спорта «Раубичи» (аг. Раубичи, Минский р-н), структура при Минспорта. Официальный сайт `rau.by` (домен, на который в задаче намекали `raubichi.by`, не используется — сайт реально живёт на `rau.by`/`www.rau.by`). Массовые катания на дату проверки не проводятся (см. `.ai/parsers/raubichi-rcop.md`).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | Раубичи — агрогородок в Минском районе, формального деления на городские districts нет | 2026-09-07 |
| phone | +375 (29) 129 06 79 ; +375 (17) 516 61 09 (администратор ледовой арены, раздел «ЛЕДОВАЯ АРЕНА») | https://www.rau.by/Katok/ | 2026-09-07 |
| website_url | https://www.rau.by/Katok/ | раздел «ЛЕДОВАЯ АРЕНА»; общий сайт https://www.rau.by/ , прайс/расписание https://www.rau.by/skates/ | 2026-09-07 |
| opening_hours | unknown | На странице `/Katok/` в шапке напечатано «Пн-Чт 8.00–17.00, Пт 8.00–15.45, обед 12:00–12:45» — похоже на общий режим работы приёмной РЦОП, а не публикуемый график ледовой арены (которая сейчас без МК); не подставляем как opening_hours объекта | 2026-09-07 |
| season | unknown | По состоянию на 2026-09-05 «Массовые катания не проводятся» — см. `.ai/parsers/raubichi-rcop.md` | 2026-09-07 |
| amenities | skate_rental: true («Прокат коньков» в описании ледовой арены); locker_rooms: true («10 оборудованных раздевалок»); parking: true, платная по выходным/праздникам 5,00 руб (страница /skates/); skate_sharpening: unknown; cafe: unknown; accessibility: unknown | https://www.rau.by/Katok/ ; https://www.rau.by/skates/ | 2026-09-07 |
| short_description | Крытая ледовая арена РЦОП «Раубичи» — хоккейная площадка с трибунами стандарта ИИХФ, бросковый зал с искусственным покрытием «сухой лёд», тренажёрный зал, прокат коньков. На дату проверки массовые катания не проводятся. | https://www.rau.by/Katok/ | 2026-09-07 |
| socials | VK https://vk.com/raubichiolympics ; Facebook https://www.facebook.com/raubichi.by ; Instagram https://www.instagram.com/rau.by/ ; Telegram https://t.me/raubichi_relax_by , https://t.me/rtsop_rau | https://www.rau.by/Katok/ (шапка сайта) | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://www.rau.by/gallery_gen/15b5b9c98888e4f09331dfe39a987b69_fit.jpg?ts=1788350407 | operator | rau.by, раздел «ЛЕДОВАЯ АРЕНА» на странице /Katok/ | Проверено визуально — интерьер крытой ледовой арены (хоккейная площадка, трибуны, освещение), 3774×2500, отдаёт `image/jpeg`. На той же странице есть галерея ещё из 7 похожих фото ледовой арены (тот же `gallery_gen/*_fit.jpg` паттерн, разные хэши в JSON галереи страницы) — можно взять любое как запасное. |

## Conflicts
- Задание предполагало домен `raubichi.by` — фактический официальный сайт живёт на `rau.by`; `raubichi.by` не проверялся отдельно (не встретился в поиске как рабочий домен).
- Часы «Пн-Чт 8.00–17.00, Пт 8.00–15.45» на странице `/Katok/` неоднозначны (см. Profile.opening_hours) — не публикуем как расписание объекта без дополнительного подтверждения.
