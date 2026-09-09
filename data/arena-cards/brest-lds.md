# Card: Ледовый дворец спорта (Брест)
- arena_id: 22
- slug: brest-lds
- verified_at: 2026-09-07
- verified_by: ICE-REGIONAL-PARSERS batch A

Домашняя арена ХК «Брест», ул. Московская, 151 (в профиле хоккейного клуба — 151А). Введена в эксплуатацию 30.06.2000. Не путать с id=39 «Озерный / Крытый каток» (дубль адреса, см. `.ai/parsers/ozerny-rink.md`).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Брест | город без официального деления на профильные districts в наших источниках; district = город | 2026-09-07 |
| phone | unknown | контактная страница https://brest.hockey.by/kontaktnaya-informatsiya/?clear_cache=Y даёт только административные телефоны сотрудников клуба (например «Приёмная» 53-92-55) — не номер именно ледовой арены/свободного катания; e-mail есть: info@brest-hockey.by | 2026-09-07 |
| website_url | https://brest.hockey.by/raspisanie-svobodnogo-kataniya/ | официальная страница расписания и цен свободного катания ХК «Брест» | 2026-09-07 |
| opening_hours | unknown | нет общего режима работы арены; публично доступно только окно свободного катания по расписанию (см. parser: ежедневно 21:15–22:15 на неделе снимка) | 2026-09-07 |
| amenities | skate_rental=true; skate_sharpening=unknown; parking=unknown; locker_rooms=unknown; cafe=unknown; accessibility=unknown | прайс страницы: «с арендой коньков» (630/530 без — 1310/1110 с прокатом) подтверждает прокат; заточка не упомянута на этой странице | 2026-09-07 |
| short_description | Ледовый дворец спорта в Бресте (домашняя арена ХК «Брест»), ул. Московская, 151. Свободное катание («СВ кат») по расписанию, прокат коньков на месте. | https://brest.hockey.by/raspisanie-svobodnogo-kataniya/ , https://brest.hockey.by/clubs/arena/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://brest.hockey.by/IMG_6644.JPG | operator | фото с официального сайта ХК «Брест» (страница «Арена») | HTTP 200, image/jpeg, 2026-09-07. Показывает ледовый дворец/арену, встроено в текст страницы `/clubs/arena/`. **Нужно разрешение** на использование в продукте. |

## Conflicts
- Адрес: сайт расписания и футер сайта дают «ул. Московская, 151» / «151А» (footer: «224023, г. Брест, ул. Московская, 151А») — расхождение на литеру, не критично, не выдумывать точное написание без сверки.
- Расписание свободного катания опубликовано только фото (`IMG_8523.JPG`), не HTML-таблицей — см. `.ai/parsers/brest-lds.md` и докстринг `BrestLdsParser`. Фиксированное окно 21:15–22:15 — константа в job.config, требует ручной сверки при смене графика оператором (нет автоматического сигнала об изменении).
