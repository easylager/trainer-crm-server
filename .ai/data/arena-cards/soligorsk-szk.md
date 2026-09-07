# Card: СЗК Солигорск
- arena_id: 19
- slug: soligorsk-szk
- verified_at: 2026-09-07
- verified_by: batch-D ice parser task (web only, без звонка)

Имя по заданию: «СЗК Солигорск» (Спортивно-зрелищный комплекс), ул. К. Заслонова, 25, Солигорск. Сайт http://www.szk.by/ (на HTTP).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | адрес текстовый, обратное геокодирование не делали | 2026-09-07 |
| phone | unknown | страница http://www.szk.by/kontakty открылась, но телефон в тексте страницы не найден за отведённое время (возможно, в виде изображения) | 2026-09-07 |
| website_url | http://www.szk.by/uslugi/massovoe-katanie | страница массового катания; корень http://www.szk.by/ | 2026-09-07 |
| opening_hours | unknown | явного графика на странице услуги не нашли | 2026-09-07 |
| season | unknown | крытый комплекс, месяцы сезона не указаны | 2026-09-07 |
| amenities | skate_rental: true; skate_sharpening: true; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | «Прокат коньков (1 пара) — 4,40р», «Заточка коньков — 5,50р» — http://www.szk.by/uslugi/massovoe-katanie | 2026-09-07 |
| short_description | Ледовая арена спортивно-зрелищного комплекса Солигорска (ул. К. Заслонова, 25). Расписание массового катания на неделю, включая ночной сеанс «Рок-хиты» (23:00–00:00) по субботам. | http://www.szk.by/uslugi/massovoe-katanie | 2026-09-07 |
| socials | Facebook https://www.facebook.com/LedoviDvorez ; Instagram https://www.instagram.com/szk_soligorsk/?hl=ru | ссылки на http://www.szk.by/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| http://www.szk.by/uploads/b1/s/2/870/image/118/147/medium_SZK.jpg?t=1539300399 | operator | www.szk.by, страница «О комплексе» (/o-komplekse) | Найдено 2026-09-07 (batch-1 photo research). Проверено визуально — реальное фото здания СЗК Солигорск снаружи (характерная волнистая крыша), водяной знак «SZK.BY» в углу. Fetchable `image/jpeg`, ~148 КБ, на собственном домене оператора (сайт на HTTP, см. Conflicts ниже в исходной карточке). |
| ~~unknown~~ (см. предыдущую попытку) | — | — | Ранее (2026-09-07, до photo research) было зафиксировано: og:image на http://www.szk.by/ ссылается на `medium_pixabay.jpg` — стоковое фото с Pixabay; по правилу «никогда Google Images/сток» не использовать даже раз оно висит на официальном сайте. Оставлено для истории — заменено найденным выше operator-фото. Также на странице `/foto` есть фото со страницы «Схема трибуны» (`medium_Zal.jpg`) — это схема-план, а не фото, не используется. |

## Conflicts
- Нет расхождений расписания/цен — прайс на массовое катание один и явный на той же странице, откуда парсится расписание.
