# Card: Минск Арена
- arena_id: 2
- slug: minskarena
- verified_at: 2026-09-06
- verified_by: CONTENT TASK-079 (ABWS objects + object.html; без звонка)

Имя и адрес в прод-CSV: «Минск Арена», пр-т. Победителей 111, Минск (lat 53.9394, lon 27.4685).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Центральный район | Nominatim reverse `lat=53.9394&lon=27.4685` → `city_district=Центральный район` (suburb Ржавец не берём — TASK-048 предпочитает district) https://nominatim.openstreetmap.org/reverse?lat=53.9394&lon=27.4685&format=json&addressdetails=1 | 2026-09-06 |
| phone | +375 17 279-04-11 | футер https://minskarena.by/ («КОНТАКТЫ»); совпадает с https://minsksport.by/sports-base/obekty-fizkulturno-sportivnogo-naznacheniya/ | 2026-09-06 |
| website_url | https://minskarena.by/ | официальный сайт; билеты МК: https://saleframe.minskarena.by/service/55 | 2026-09-06 |
| opening_hours | администрация / справочная: Пн–Чт 9:00–18:00, Пт 9:00–16:45. Часы катка и билетных касс для массового катания — unknown | футер https://minskarena.by/. Виджет на https://minskarena.by/services.html с датой «13 декабря 2021» не используем | 2026-09-06 |
| season | unknown | на сайте нет явной формулировки «круглый год» / месяцев сезона | 2026-09-06 |
| amenities | skate_rental: unknown; skate_sharpening: unknown; parking: true; locker_rooms: unknown; cafe: true; accessibility: unknown | parking: ABWS `GET /api/v3/arena/home` → `data.objects` id=7 «Паркинг» + кадр со знаками P1/P2. cafe: тот же список id=12 «Кафе, ресторан». Прокат/заточка/раздевалки по-прежнему unknown — не гадаем со слотов saleframe. | 2026-09-06 |
| short_description | Многопрофильный культурно-спортивный комплекс «Минск-арена». Массовое катание — отдельная услуга, билеты через saleframe. | JSON-LD на https://minskarena.by/ (`SportsOrganization`); пункт меню «МАССОВЫЕ КАТАНИЯ»; https://saleframe.minskarena.by/service/55 | 2026-09-06 |
| socials | Facebook https://www.facebook.com/arenaminsk/ ; Instagram https://www.instagram.com/minskarenaby/ | JSON-LD `sameAs` на https://minskarena.by/. Иконки в шапке ведут на `#` — см. Conflicts | 2026-09-06 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://abws.minskarena.by/uploads/objects/1UcVhaw8J.jpg | operator | МКСК «Минск-арена», объект «Арена»; https://abws.minskarena.by/api/v3/arena/home | ночной фасад главной арены (hero). Nikon D3100, официальный ABWS object id=1 |
| https://minskarena.by/img/object-bg.jpg | operator | https://minskarena.by/object.html | аэрофото комплекса (арена + конькобежный стадион) со страницы «Объекты» |
| https://abws.minskarena.by/uploads/objects/5D75EknaB.jpg | operator | МКСК «Минск-арена», объект «Конькобежный стадион»; ABWS home objects id=4 | фасад конькобежного стадиона; МК также там — новость https://minskarena.by/new.html?id=83-massovoe-katanie-na-glavnoj-arene-i-konkobezhnom-stadione |

Не hero (оставлено в Conflicts, не грузить): концертный `slider_pic.jpg`, шоу `pic_event_3.jpg`, SVG-логотип, графический баннер поста «Массовое катание» (`uploads/posts/7U22tJK3E.png` — макет, не фото льда), набор в школу фигурного катания.

## Conflicts
- Телефон: футер и minsksport дают **+375 17 279-04-11**; JSON-LD `contactPoint.telephone` на той же главной — **+375 (17) 279-09-81**. В профиль кладём номер из футера; 279-09-81 не публиковать, пока не подтверждён звонком.
- Соцсети: JSON-LD `sameAs` заполнен, кликабельные иконки шапки — `href="#"`.
- Часы МК: блок «время работы билетных касс / расписание сеансов» на https://minskarena.by/services.html содержит «13 декабря 2021» — протухший виджет, не факт 2026.
- Прокат: в карточке **unknown**. Не переносить в amenities догадку со слотов saleframe (другой лёд / отдельный виджет).
- TASK-077 skip «нет кадра льда/фасада на главной/services» — верно для тех URL. Кадры фасада есть в ABWS `objects` и на `/object.html` (найдено 2026-09-06).
- Live slug профиля на стенде = `manezh` (бэкфилл 048). Досье slug `minskarena` лоадер в slug не пишет — не менять здесь.
