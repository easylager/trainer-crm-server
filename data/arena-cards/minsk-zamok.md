# Card: ТЦ Замок
- arena_id: 3
- slug: zamok
- verified_at: 2026-09-06
- verified_by: CONTENT TASK-073 (web only, без звонка)

Имя и адрес в прод-CSV: «ТЦ Замок», пр-т. Победителей 65, Минск (lat 53.92635, lon 27.51738). Сайт катка уточняет: 4 этаж.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Центральный район | Nominatim reverse `lat=53.92635&lon=27.51738` → `city_district=Центральный район` (suburb Веснянка / neighbourhood Веселовка не берём) https://nominatim.openstreetmap.org/reverse?lat=53.92635&lon=27.51738&format=json&addressdetails=1 | 2026-09-06 |
| phone | +375 (44) 783-85-18; +375 (17) 309-54-76 | блок «Телефон» на https://tczamok.by/entertainments/ice-rink | 2026-09-06 |
| website_url | https://tczamok.by/entertainments/ice-rink | официальная страница катка ТЦ «Замок» | 2026-09-06 |
| opening_hours | каток: ежедневно 10:00–23:00 | https://tczamok.by/entertainments/ice-rink («Время работы» и попап часов ТЦ: «Ледовый каток с 10:00 до 23:00») | 2026-09-06 |
| season | круглый год (season_start_month=1, season_end_month=12) | https://tczamok.by/entertainments/ice-rink — «Сезон катаний круглый год!», «ледовая площадка работает без выходных» | 2026-09-06 |
| amenities | skate_rental: true; skate_sharpening: true; locker_rooms: true; cafe: true; parking: unknown; accessibility: unknown | прокат, заточка, раздевалки и камеры хранения — текст страницы катка; кафе/рестораны ТЦ — попап «Время работы» на том же сайте. Парковка и доступность на странице катка не названы | 2026-09-06 |
| short_description | Крытый каток в ТЦ «Замок» (4 этаж), площадь более 1000 м². Прокат хоккейных и фигурных коньков, раздевалки, заточка; сезон круглый год. | https://tczamok.by/entertainments/ice-rink | 2026-09-06 |
| socials | VK https://vk.com/tczamok ; Facebook https://www.facebook.com/tczamok/ ; Instagram https://www.instagram.com/tc_zamok/ | футер https://tczamok.by/entertainments/ice-rink (соцсети ТЦ, не отдельный аккаунт катка) | 2026-09-06 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://tczamok.by/files/entertainments/entertainment/2/katok-meta.jpg | operator | ТЦ «Замок», страница катка | og:image; лёд/атмосфера. **нужно разрешение** на загрузку в продукт. Локально не копировали. |
| https://tczamok.by/files/resized/entertainment-2/1920x665-katok-new-main.png | operator | ТЦ «Замок» | баннер катка. **нужно разрешение**. |
| https://tczamok.by/files/resized/entertainment/536x320-katok-katok-v2.png | operator | ТЦ «Замок» | лёд. **нужно разрешение**. |
| https://tczamok.by/files/resized/entertainment/536x320-katok-konki.png | operator | ТЦ «Замок» | прокат/коньки. **нужно разрешение**. |
| https://tczamok.by/files/resized/entertainment-2/x520-kassi-katok.png | operator | ТЦ «Замок» | кассы. **нужно разрешение**. |
| https://tczamok.by/files/resized/entertainment-2/x520-rasdevalki.png | operator | ТЦ «Замок» | раздевалки. **нужно разрешение**. |
| https://tczamok.by/files/resized/entertainment-2/x520-katok-gellary-3.jpg | operator | ТЦ «Замок» | галерея льда. **нужно разрешение**. |
| https://tczamok.by/files/resized/entertainment-2/x520-katok-gellary-4.jpg | operator | ТЦ «Замок» | галерея. **нужно разрешение**. |
| https://tczamok.by/files/resized/entertainment-2/x520-katok-gellary-5.jpg | operator | ТЦ «Замок» | галерея. **нужно разрешение**. |

Кадры опубликованы оператором на своём сайте. Лицензия для `media.license` пока не явная (нет текста передачи прав) → в TASK-049 не грузить, пока нет `permitted`/`operator` от площадки. Папка `photos/zamok/` пустая специально.

## Conflicts
- Часы заточки: на странице катка «ежедневно с 12:00 до 20:00»; в попапе часов ТЦ «Заточка коньков с 18:00 до 21:00». В профиль часов катка заточку не пишем; факт `skate_sharpening: true` без графика, пока не сверка звонком.
- Телефон инфоцентра 4 этажа +375 (17) 309-54-75 в попапе «Контакты» — не номер катка (у катка два своих). Не подменять.
