# Card: ТЦ DiaMond city
- arena_id: 7
- slug: minsk-diamond
- verified_at: 2026-09-06
- verified_by: CONTENT TASK-073

CSV name: `ТЦ DiaMond city`. На сайте оператора каток подписан **DiaMond ice** / «Ледовая арена», 3 этаж ТЦ.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Московский район | Nominatim reverse по CSV coords 53.84966,27.433552 (`city_district`; suburb Малиновка) | 2026-09-06 |
| phone | +375 29 198 74 30 | https://diamondcity.by/ledovaya-arena («Телефон для справок» / администратор) | 2026-09-06 |
| website_url | https://diamondcity.by/ledovaya-arena | та же страница, HTTP 200 | 2026-09-06 |
| opening_hours | 10:00–22:00 (дни недели на блоке арены не указаны) | https://diamondcity.by/ledovaya-arena («Работаем для Вас») | 2026-09-06 |
| season | unknown | на странице арены нет месяцев сезона; слоты МК сюда не копировать | 2026-09-06 |
| amenities | skate_rental=true; locker_rooms=true; skate_sharpening=unknown; parking=unknown; cafe=unknown; accessibility=unknown | https://diamondcity.by/ledovaya-arena: «пункт проката»; «прокат коньков, раздевалка» | 2026-09-06 |
| short_description | Крытый каток DiaMond ice в ТЦ DiaMond city (3 этаж). Семейное катание, свой прокат коньков и амуниции. Массовые сеансы — по сетке на сайте арены, не по часам ТЦ. | https://diamondcity.by/ledovaya-arena | 2026-09-06 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| `photos/minsk-diamond/bannerled.png` | operator | ТЦ DiaMond city, https://diamondcity.by/d/bannerled.png | Баннер «Ледовая арена!» на https://diamondcity.by/ceny (alt «баннерлед»). Скачан с origin оператора 2026-09-06. Кадр: лёд / промо арены. |
| https://diamondcity.by/d/photo_5386312898617402150_y_1.jpg | operator | ТЦ DiaMond city | Промо «карты лояльности diamond ice» на /ceny. Не скачивали: графика акции, не фото фасада/льда для героя. |
| https://www.instagram.com/diamondcity.by/ | operator | ТЦ DiaMond city | Соцсеть всего ТЦ, не отдельная галерея катка. Посты IG не скачивать — нужно разрешение на конкретный кадр. |

## Conflicts
- Телефон катка `+375 29 198 74 30` vs справочная ТЦ `+375 44 5 222 333` на той же вёрстке (хедер/футер). В профиль — телефон арены.
- Адрес: CSV `Щомыслицкий с/с 32/4`; сайт «пересечение ул. Громова и МКАД» / «Громова и 28 км МКАД»; Nominatim привязал точку к «МКАД, 28-й километр» (shop Gloria Jeans внутри ТЦ). Кадастр vs вывеска — не сливать в одну строку.
- Этаж катка: на блоке арены «3 этаж»; соседние карточки тенантов в той же HTML — шаблон «2 этаж». Для карточки катка брать «3 этаж».
- Часы: блок арены «10:00–22:00»; футер ТЦ «с 10:00-22:00, без выходных». Дни работы льда отдельно не написаны. Это часы объекта, не сетка МК.
