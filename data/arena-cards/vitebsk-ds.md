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
| website_url | https://vitebsk.hockey.by/clubs/arena/massovoe-katanie/ | страница массового катания; корень клуба https://vitebsk.hockey.by/ | 2026-09-07 |
| opening_hours | unknown (общий режим объекта); касса МК — 11:00–21:00 без выходных | https://vitebsk.hockey.by/clubs/arena/massovoe-katanie/?clear_cache=Y | 2026-09-07 |
| season | unknown | крытая арена, явных месяцев сезона МК на странице нет | 2026-09-07 |
| amenities | skate_rental: unknown (в описании 24afisha упомянут прокат «на месте», цена не на сайте клуба); parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | https://vitebsk.hockey.by/clubs/arena/massovoe-katanie/ | 2026-09-07 |
| short_description | «Дворец спорта», построен ~1999, лёд 61×30 м, вместимость ок. 2000 зрителей; домашняя арена ХК «Витебск», массовое катание по будням/выходным. | https://vitebsk.hockey.by/clubs/arena/ | 2026-09-07 |
| socials | VK https://vk.com/hcvitebsk ; Instagram https://www.instagram.com/hc.vitebsk/ ; Telegram https://t.me/hc_vitebsk ; YouTube https://www.youtube.com/channel/UCUilvkw1lAA9_hA22fZqeYg ; TikTok https://www.tiktok.com/@vitebskhockey | https://vitebsk.hockey.by/clubs/arena/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://vitebsk.hockey.by/bilety/s1200.jpg | operator | ХК «Витебск» / Витебский дворец спорта | Фасад дворца спорта, встроено на https://vitebsk.hockey.by/clubs/arena/ . Локально не копировали, **нужно разрешение**. |

## Conflicts
- Расписание МК (`massovoe-katanie.html`) на 2026-09-06 и повторно на 2026-09-07 (сегодня) показывает один и тот же диапазон 30 апреля – 3 мая 2026 — сайт клуба, похоже, не обновляет блок МК; см. `.ai/parsers/vitebsk-ds.md` и парсер `VitebskDsParser` (`vitebsk_ds_v1`). Живой продукт не должен публиковать эти даты (drop_past); ожидать 0 будущих слотов до обновления сайтом.
- og:image страницы (`/upload/uf/ad1/....png`) — это логотип клуба, не фото арены; использован отдельно найденный `bilety/s1200.jpg`.
