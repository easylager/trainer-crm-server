# BY regional ice sources (SPEC probe, 2026-09-05)

Prod dump: `.ai/data/by-arenas-prod.csv` (191 active arenas, **READ ONLY** SELECT). Ice Discovery V1 remains Minsk-first; this file is the next-city queue.

Москва/МО (102) и СПб (49) — не очередь парсеров МК, пока продукт не снимет CITY_LOCK.

## BY outside Minsk (29 arenas)

Parse-ready this pass:

| city | arena_id | name | source | spec |
|---|---|---|---|---|
| Гродно | 10 | ТЦ «Тринити» | JSON `ice.triniti-grodno.by/api/ice.php` | [grodno-triniti.md](../parsers/grodno-triniti.md) |
| Гомель | 33 | Гомельский ЛДС | weekly news gomel.hockey.by | [gomel-lds.md](../parsers/gomel-lds.md) |

Probed, not a spec yet:

| city | arena_id | name | finding |
|---|---|---|---|
| Гродно | 11 | Ледовый дворец (Коммунальная 3а) | `hcneman.by/schedule/scheduleMK.html` UTF-16; на 2026-09-05 висит **05 апреля 2026** — протухший виджет. `icepalace.by` → 404. Не публиковать stale. |
| Брест | 22 | Брестский ЛДС | Цены HTML на [СВ кат](https://brest.hockey.by/raspisanie-svobodnogo-kataniya/). Сетка — фото на [расписании арены](https://brest.hockey.by/raspisanie-svobodnogo-kataniya/raspisanie-ledovoy-areny/): [`IMG_8523.JPG`](https://brest.hockey.by/IMG_8523.JPG). OCR «СВ кат»; неделя 31.08–06.09: **21:15–22:15 каждый день**. `kind=open_ice`. |
| Витебск | 29 | Дворец спорта | [HTML МК](https://vitebsk.hockey.by/clubs/arena/massovoe-katanie/) — блоки дней, 7.00 / льгота 6.00, сеанс 60 мин. Прокат ИП без суммы. На снимке 5 сен даты ещё 30 апр–3 мая. Онлайн: 24afisha.by. |
| Могилев | 43 | Дворец спорта «Могилёв» | `mogilev.hockey.by/raspisanie/` — общий лёд СДЮШОР/ХК; строки «массовое катание» есть, нужно фильтровать kind и не тащить школу. |
| Гомель | 34 | «Солнечный» | отдельный каток; источник МК не искали в этом прогоне. |

Остальные 1-arena города (Барановичи, Бобруйск, Лида, Пинск, Солигорск, …) — следующий круг SPEC, по одному файлу на каток.

Дашборд: [`../design/ice-parser-status.html`](../design/ice-parser-status.html) · JSON [`ice-parser-status.json`](./ice-parser-status.json).

## Yunost (Minsk) egress

Origin `junost.by` с не-BY IP = 403. С BY Globalping (Beltelecom/Minsk) = **200**. Парсить **только** с BY IP, без шаблона сетки. См. [minsk-junost.md](../parsers/minsk-junost.md).
