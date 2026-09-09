# Card: Каток хк "Юность"
- arena_id: 8
- slug: minsk-junost
- verified_at: 2026-09-06
- verified_by: CONTENT TASK-073

CSV name: `Каток хк "Юность"`. Origin `junost.by` с этого IP — **403** (nginx/1.10.3). Часы и сетка origin **не выдуманы**. Профиль, который можно открыть сегодня, — страница клуба на hockey.by.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Комаровка | Nominatim reverse по CSV coords 53.90141,27.57375 (`suburb`; `city_district` нет) | 2026-09-06 |
| phone | +375 17 393-90-14 | https://junost.hockey.by/clubs/skating/ («Администратор»), HTTP 200 | 2026-09-06 |
| website_url | https://junost.by/ | официальный origin; HEAD/GET 2026-09-06 = 403 Forbidden (nginx/1.10.3), хост жив | 2026-09-06 |
| opening_hours | unknown | origin 403; на hockey.by нет часов объекта, только приглашение «в эти выходные» — это не opening_hours | 2026-09-06 |
| season | unknown | нет месяцев сезона на открываемых страницах | 2026-09-06 |
| amenities | skate_rental=true; skate_sharpening=true; cafe=true; locker_rooms=unknown; parking=unknown; accessibility=unknown | https://junost.hockey.by/clubs/skating/: прокат коньков, заточка «на постоянной основе», кафе | 2026-09-06 |
| short_description | Крытый каток ХК «Юность-Минск», ул. Первомайская, 3. Массовое катание — только по origin junost.by (с не-BY IP страница 403). | адрес: https://junost.hockey.by/clubs/skating/ + CSV; блокер: GET https://junost.by/ → 403 | 2026-09-06 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://junost.by/foto/ | operator | ХК / СДЮШОР «Юность-Минск» | Раздел фото на origin. GET 403 с этого IP — файл не скачивали. Нужно разрешение + BY-egress, чтобы выбрать кадр льда/фасада. |
| https://www.instagram.com/junost.by/ | operator | junost.by | Ссылка в шапке origin (BY-снимок шапки). Посты IG не скачивать — нужно разрешение. |
| — | — | — | Локальных файлов нет. На https://junost.hockey.by/clubs/skating/ нет фото катка (логотипы клубов / новости), в `photos/` ничего не клали. |

## Conflicts
- **403 / BY-blocker:** `https://junost.by/`, `/seansy_massovogo_kataniya_na_vyhodnyh/`, `/kontakty/` — все 403 nginx/1.10.3 с не-BY IP (проверено 2026-09-06). Не подставлять шаблон сб/вс 17:00 / 18:15.
- Телефоны: hockey.by (сегодня) администратор `+375 17 393-90-14`, охрана `+375 17 356-42-64`. Усечённый BY-HTML шапки origin ранее показывал офис `+375 17 357 85 79` — origin сегодня не перепроверить. В профиль — администратор с hockey.by.
- Адрес катка: CSV и hockey.by — `ул. Первомайская, 3`. Футер hockey.by (почтовый адрес клуба) — `ул. Ташкентская, 19-2` (Чижовка, офис). Не путать каток и офис.
- Район: Nominatim дал suburb **Комаровка**, без `city_district`. Справочники в выдаче расходятся (Партизанский / Комаровка). Административный район в профиль не выдуман.
- Amenities с hockey.by, не с origin. Если origin после BY-egress скажет иначе — править досье, не угадывать.
