# Card: Минск Арена
- arena_id: 2
- slug: minskarena
- verified_at: 2026-09-06
- verified_by: CONTENT TASK-073 (web only, без звонка)

Имя и адрес в прод-CSV: «Минск Арена», пр-т. Победителей 111, Минск (lat 53.9394, lon 27.4685).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Центральный район | Nominatim reverse `lat=53.9394&lon=27.4685` → `city_district=Центральный район` (suburb Ржавец не берём — TASK-048 предпочитает district) https://nominatim.openstreetmap.org/reverse?lat=53.9394&lon=27.4685&format=json&addressdetails=1 | 2026-09-06 |
| phone | +375 17 279-04-11 | футер https://minskarena.by/ («КОНТАКТЫ»); совпадает с https://minsksport.by/sports-base/obekty-fizkulturno-sportivnogo-naznacheniya/ | 2026-09-06 |
| website_url | https://minskarena.by/ | официальный сайт; билеты МК: https://saleframe.minskarena.by/service/55 | 2026-09-06 |
| opening_hours | администрация / справочная: Пн–Чт 9:00–18:00, Пт 9:00–16:45. Часы катка и билетных касс для массового катания — unknown | футер https://minskarena.by/. Виджет на https://minskarena.by/services.html с датой «13 декабря 2021» не используем | 2026-09-06 |
| season | unknown | на сайте нет явной формулировки «круглый год» / месяцев сезона | 2026-09-06 |
| amenities | skate_rental: unknown; skate_sharpening: unknown; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | https://minskarena.by/ и https://minskarena.by/services.html — страницы «лёд»/услуги SPA без текста проката/заточки/парковки. Не угадываем | 2026-09-06 |
| short_description | Многопрофильный культурно-спортивный комплекс «Минск-арена». Массовое катание — отдельная услуга, билеты через saleframe. | JSON-LD на https://minskarena.by/ (`SportsOrganization`); пункт меню «МАССОВЫЕ КАТАНИЯ»; https://saleframe.minskarena.by/service/55 | 2026-09-06 |
| socials | Facebook https://www.facebook.com/arenaminsk/ ; Instagram https://www.instagram.com/minskarenaby/ | JSON-LD `sameAs` на https://minskarena.by/. Иконки в шапке ведут на `#` — см. Conflicts | 2026-09-06 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| — | — | — | На 2026-09-06 на minskarena.by нет опубликованного кадра льда/фасада (главная и `/services.html` / `page.html?slug=ice` — оболочка без галереи). Логотип JSON-LD `https://abws.minskarena.by/uploads/settings/layout.logoUrl.svg` — не hero карточки. **фото нет / ждём разрешение или свою съёмку.** Локальных файлов нет. |

## Conflicts
- Телефон: футер и minsksport дают **+375 17 279-04-11**; JSON-LD `contactPoint.telephone` на той же главной — **+375 (17) 279-09-81**. В профиль кладём номер из футера; 279-09-81 не публиковать, пока не подтверждён звонком.
- Соцсети: JSON-LD `sameAs` заполнен, кликабельные иконки шапки — `href="#"`.
- Часы МК: блок «время работы билетных касс / расписание сеансов» на https://minskarena.by/services.html содержит «13 декабря 2021» — протухший виджет, не факт 2026.
- Прокат: в карточке **unknown**. Не переносить в amenities догадку со слотов saleframe (другой лёд / отдельный виджет).
