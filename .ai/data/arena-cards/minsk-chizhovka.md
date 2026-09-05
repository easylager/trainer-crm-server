# Card: Чижовка-арена
- arena_id: 6
- slug: chizhovka
- verified_at: 2026-09-06
- verified_by: CONTENT TASK-073 (web only, без звонка)

Имя и адрес в прод-CSV: «Чижовка-арена», ул. Ташкентская 19, Минск (lat 53.844534, lon 27.628657). Юр./почта на сайте: 220077, ул. Ташкентская, 19-2.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Заводской район | Nominatim reverse `lat=53.844534&lon=27.628657` → `city_district=Заводской район` (suburb Чижовка) https://nominatim.openstreetmap.org/reverse?lat=53.844534&lon=27.628657&format=json&addressdetails=1 ; новость о стоянке ссылается на администрацию Заводского района | 2026-09-06 |
| phone | +375 (29) 33 00 749 (+ Telegram) | https://chizhovka-arena.by/kontakty и https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah («единый номер» / инфоцентр) | 2026-09-06 |
| website_url | https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah | страница катания; корень комплекса https://chizhovka-arena.by/ | 2026-09-06 |
| opening_hours | комплекс: ежедневно 7:00–23:00. Кассы катания — см. Conflicts (не склеивать) | «Часы работы» https://chizhovka-arena.by/kontakty | 2026-09-06 |
| season | unknown | крытый комплекс, но явных месяцев сезона МК на сайте нет | 2026-09-06 |
| amenities | skate_rental: true; skate_sharpening: true; parking: true; locker_rooms: unknown; cafe: unknown; accessibility: unknown | прокат и заточка (вход 50) — https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah ; парковка — https://chizhovka-arena.by/novosti/stoyanka-vozle-chizhovka-areny-stanet-platnoj.html (с 01.09.2026 платная 08:00–18:00). Кафе для посетителей МК и раздевалки на страницах катания не названы (банкетная служба ≠ кафе катка; номера для МГН — у гостиницы «Арена», не у катка) | 2026-09-06 |
| short_description | Многофункциональный спорткомплекс (открыт 2013). Массовое катание на большой и малой аренах; билет и прокат — касса вход № 59 или онлайн. | https://chizhovka-arena.by/ob-uchrezhdenii ; https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah | 2026-09-06 |
| socials | Instagram https://www.instagram.com/chizhovka__arena/ ; Facebook https://web.facebook.com/chizhovkarena ; VK https://vk.com/chizhovkarena ; YouTube https://youtube.com/channel/UCMMHmQXb8ruMohdQ6n_Uuzw | футер https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah | 2026-09-06 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://chizhovka-arena.by/wp-content/uploads/2021/02/disko11.jpg | operator | ГУ «Чижовка-Арена» | og:image / thumbnail страницы катания; дискотека на льду. **нужно разрешение**. Локально не копировали. |
| https://chizhovka-arena.by/wp-content/uploads/2020/10/st_block_row_settings_125741_bg_xwext2oh-scaled-e1602184961320.jpg | operator | ГУ «Чижовка-Арена» | фон/og главной. Уточнить, что на кадре, перед hero. **нужно разрешение**. |
| https://chizhovka-arena.by/wp-content/uploads/2026/08/parkovka-1-300x225.jpg | operator | ГУ «Чижовка-Арена» | превью новости о парковке; не лёд. **нужно разрешение**. |

Портреты сотрудников с `/kontakty` в галерею катка не брать. Папка `photos/chizhovka/` пустая: лицензия не явная.

## Conflicts
- Часы касс: страница катания — касса вход № 59 **9:00–21:00**; блок «Касса» на https://chizhovka-arena.by/kontakty — **8:00–22:00**; «Часы работы» комплекса — **7:00–23:00**. В `opening_hours` профиля — часы комплекса; кассы не угадывать.
- Телефон на minsksport.by для учреждения: +375 (17) 330-07-10 (приёмная гендиректора). Для карточки посетителя — единый **+375 (29) 33 00 749**, не приёмная.
