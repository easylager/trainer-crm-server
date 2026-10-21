# Card: Витебский дворец спорта
- arena_id: 29
- slug: vitebsk-ds
- verified_at: 2026-09-07
- verified_by: TASK ice-regional-parsers-batch-c (web only, без звонка)

Адрес в проде: просп. Строителей, 23, Витебск. Домашняя арена «Витебского хоккейного клуба» (ХК «Витебск»). Не путать с Новополоцком (ХК «Химик»).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | не найден явный район на сайте клуба | 2026-09-07 |
| phone | unknown (только email/соцсети) | https://vitebsk.hockey.by/clubs/arena/ — телефон на странице арены не указан | 2026-09-07 |
| website_url | https://hc-vitebsk.by/ | сайт Витебского ледового дворца спорта | 2026-10-21 |
| tickets_url | https://24afisha.by/ru/vitebsk/event/massovoe-katanie-v-vitebskom-dvortse-sporta | касса массового катания, сеансы с ценой | 2026-10-21 |
| rental_title | Прокат коньков | описание сеанса на 24afisha и афиша на hc-vitebsk.by | 2026-10-21 |
| rental_catalog | до 34 размера — 5,00 BYN; от 35 размера — 10,00 BYN | описание сеанса на 24afisha | 2026-10-21 |
| rental_note | Выдача коньков открывается за 1 час до начала сеанса. | описание сеанса на 24afisha | 2026-10-21 |
| opening_hours | unknown (общий режим объекта); касса МК — 11:00–21:00 без выходных | https://vitebsk.hockey.by/clubs/arena/massovoe-katanie/?clear_cache=Y | 2026-09-07 |
| season | unknown | крытая арена, явных месяцев сезона МК на странице нет | 2026-09-07 |
| amenities | skate_rental: true; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | прокат на месте: 5,00 BYN до 34 размера, 10,00 BYN от 35 | 2026-10-21 |
| short_description | «Дворец спорта», построен ~1999, лёд 61×30 м, вместимость ок. 2000 зрителей; домашняя арена ХК «Витебск», массовое катание по будням/выходным. | https://vitebsk.hockey.by/clubs/arena/ | 2026-09-07 |
| socials | VK https://vk.com/hcvitebsk ; Instagram https://www.instagram.com/hc.vitebsk/ ; Telegram https://t.me/hc_vitebsk ; YouTube https://www.youtube.com/channel/UCUilvkw1lAA9_hA22fZqeYg ; TikTok https://www.tiktok.com/@vitebskhockey | https://vitebsk.hockey.by/clubs/arena/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://vitebsk.hockey.by/bilety/s1200.jpg | operator | ХК «Витебск» / Витебский дворец спорта | Фасад дворца спорта, встроено на https://vitebsk.hockey.by/clubs/arena/ . Локально не копировали, **нужно разрешение**. |

## Conflicts
- Старая страница vitebsk.hockey.by держит сетку 30 апреля – 3 мая. Живое расписание — 24afisha, парсер `vitebsk_ds_v1`. Сайт дворца — https://hc-vitebsk.by/.
- og:image страницы (`/upload/uf/ad1/....png`) — это логотип клуба, не фото арены; использован отдельно найденный `bilety/s1200.jpg`.
