# Card: Горки Ледовый дворец
- arena_id: 32
- slug: gorki-lds
- verified_at: 2026-09-07
- verified_by: TASK ice-regional-parsers-batch-c (web only, без звонка)

Адрес в проде: Вокзальная улица, 23, Горки. Оператор — ГУСУ «Горецкая детско-юношеская спортивная школа» (сайт gorkiled.by).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | не проверялся | 2026-09-07 |
| phone | (+375 2233) 79995 — приёмная/факс; (+375 2233) 79993 — бухгалтерия | http://gorkiled.by/kontakty | 2026-09-07 |
| website_url | https://gorkiled.by/ (блок «МАССОВОЕ КАТАНИЕ» на главной) | прейскурант http://gorkiled.by/ru/uslugi | 2026-09-07 |
| opening_hours | Пн–Пт 8:00–22:00, Сб–Вс 8:00–20:00 (общий режим физкультурно-спортивного объекта, не отдельно для МК) | https://gorkiled.by/ (страница, содержащая блок МК) | 2026-09-07 |
| season | unknown | блок МК переписывается вручную понедельно, явных месяцев сезона нет | 2026-09-07 |
| amenities | skate_rental: true («Предоставление коньков», прейскурант); skate_sharpening: true («Заточка коньков сложная»); parking: unknown; locker_rooms: true (раздевалка в прейскуранте, п.12); cafe: unknown; accessibility: unknown | http://gorkiled.by/ru/uslugi | 2026-09-07 |
| short_description | Ледовый дворец при ДЮСШ; массовое катание анонсируется вручную на главной странице сайта (не в разделе услуг), может отменяться из-за турниров. | https://gorkiled.by/ | 2026-09-07 |
| socials | unknown | не найдены на главной/контактах | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| unknown | — | — | Ссылка `ledovaya-arena` в навигации главной страницы ведёт на 404 (мёртвая страница). На главной — только слайдер-мокапы темы сайта и фото социальных акций, к катку не относятся. |

## Conflicts
- Раньше расписание МК ошибочно искали только на `/ru/uslugi` (там только прайс, без времени сеансов) — сетка на **главной** странице (см. `.ai/parsers/gorki-lds.md`).
- Пункт меню «Ледовая арена» (`http://gorkiled.by/ledovaya-arena`) отдаёт 404 на дату проверки 2026-09-07 — не использовать как источник.
