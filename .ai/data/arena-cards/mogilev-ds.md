# Card: Дворец спорта «Могилёв»
- arena_id: 43
- slug: mogilev-ds
- verified_at: 2026-09-07
- verified_by: TASK ice-regional-parsers-batch-c (web only, без звонка)

Адрес в проде: ул. Гагарина, 1, Могилёв (адрес взят из прод-таблицы арен задачи; на сайте клуба явного текстового адреса не найдено — см. Conflicts). Домашняя арена ХК «Могилёв».

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | не проверялся (нет явного адреса на сайте клуба) | 2026-09-07 |
| phone | unknown | https://mogilev.hockey.by/ и https://mogilev.hockey.by/clubs/arena/ — телефон не найден; выделенной страницы контактов (`/kontakty/`) нет (404) | 2026-09-07 |
| website_url | https://mogilev.hockey.by/raspisanie/ | расписание льда; прайс https://mogilev.hockey.by/uslugi/ | 2026-09-07 |
| opening_hours | unknown | не указан общий режим работы объекта | 2026-09-07 |
| season | unknown | явных месяцев сезона МК на сайте нет | 2026-09-07 |
| amenities | skate_rental: true (прокат коньков, пара/45 мин — прайс `/uslugi/`); skate_sharpening: true (услуга заточки, прайс `/uslugi/`); parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | https://mogilev.hockey.by/uslugi/?clear_cache=Y | 2026-09-07 |
| short_description | Ледовый дворец, домашняя арена ХК «Могилёв» и школы СДЮШОР; лёд делят хоккейные тренировки/матчи и вечернее массовое катание (см. `raspisanie/`). | https://mogilev.hockey.by/raspisanie/ | 2026-09-07 |
| socials | VK https://vk.com/hcmogilev ; Facebook https://www.facebook.com/hcmogilev ; Instagram https://www.instagram.com/hcmogilev/ ; YouTube https://www.youtube.com/user/hcmogilev | https://mogilev.hockey.by/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| unknown | — | — | На `/raspisanie/`, `/uslugi/`, `/clubs/arena/` найдены только логотипы клуба и партнёров (og:image — логотип-лев, `/upload/iblock/...` — спонсорские лого); ни одного явного фото арены/льда не найдено за разумное время поиска. Не подставлять логотип как фото. |

## Conflicts
- Задача указывает адрес «ул. Гагарина 1»; сайт клуба (`mogilev.hockey.by`) не публикует текстовый адрес арены на проверенных страницах (`/`, `/raspisanie/`, `/clubs/arena/`) — адрес в профиле взят из прод-данных задачи, не переподтверждён третьим источником.
- `/kontakty/`, `/contacts/`, `/about/kontakty/`, `/club/kontakty/` — все 404 на дату проверки.
