# Card: Ледовый дворец спорта Минской области (led.by)
- arena_id: 5
- slug: ledby
- verified_at: 2026-09-06
- verified_by: CONTENT TASK-073 (web only, без звонка)

Имя и адрес в прод-CSV: «Ледовый дворец спорта Минской области», ул. Притыцкого 27, Минск (lat 53.90757, lon 27.48631). Сайт: 220092, г. Минск, ул. Притыцкого, 27.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Фрунзенский район | Nominatim reverse `lat=53.90757&lon=27.48631` → `city_district=Фрунзенский район` (suburb «Раковское шоссе» / neighbourhood Тивали не берём) https://nominatim.openstreetmap.org/reverse?lat=53.90757&lon=27.48631&format=json&addressdetails=1 | 2026-09-06 |
| phone | администратор +375 29 323-22-09 (A1); городской администратора +375 17 397-88-37; автоинформатор +375 17 348-26-87 | https://led.by/about-us/ и https://led.by/mass_skating/ («Справки по телефонам»). Сайт помечает 17-е номера: не мобильные | 2026-09-06 |
| website_url | http://led.by/ | официальный сайт (http; https://led.by/ открывается). Страница МК: http://led.by/mass_skating/ | 2026-09-06 |
| opening_hours | касса: ежедневно 10:00–22:00. Администрация: Пн–Чт 8:45–18:00, Пт 8:45–16:45 (обед 13:00–14:00). Часы льда = сеансы по расписанию, не фиксированная сетка карточки | касса — http://led.by/mass_skating/ ; администрация — http://led.by/about-us/ | 2026-09-06 |
| season | unknown | безлимитный абонемент «включая месяцы ремонтно-профилактических работ» (http://led.by/mass_skating/) — месяцы закрытия не названы. Не ставить 1–12 | 2026-09-06 |
| amenities | skate_rental: true; skate_sharpening: true; parking: true; locker_rooms: true; cafe: unknown; accessibility: unknown | прокат и заточка — http://led.by/mass_skating/ ; гардероб + камера хранения там же; раздевалки — в определении «специализированных зон» тех же правил. Парковка: новость на http://led.by/ «въезд на территорию только для клиентов учреждения» (с 02.09.2019) — стоянка есть, въезд ограничен. Кафе и МГН не найдены | 2026-09-06 |
| short_description | ГУ «Ледовый дворец спорта Минской области» (с 1999). В свободное от спорта время — массовые катания; прокат, заточка, гардероб. | http://led.by/about-us/ ; http://led.by/mass_skating/ | 2026-09-06 |
| socials | Instagram https://www.instagram.com/ledovyj/ ; VK https://vk.com/ldsmo | сайдбар «Мы в соцсетях» на http://led.by/mass_skating/ | 2026-09-06 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| http://led.by/wp-content/gallery/panorama/ice-rink.jpg | operator | ГУ «Ледовый дворец спорта Минской области» | галерея «О нас», лёд. **нужно разрешение**. Правила МК: исключительное право на публикацию фото — у дворца; коммерческое использование без согласования запрещено. Локально не копировали. |
| http://led.by/wp-content/gallery/panorama/img_2409.jpg | operator | ГУ ЛДС МО | панорама. **нужно разрешение**. |
| http://led.by/wp-content/gallery/panorama/img_2407.jpg | operator | ГУ ЛДС МО | панорама. **нужно разрешение**. |
| http://led.by/wp-content/uploads/2011/10/MK.jpg | operator | ГУ ЛДС МО | страница «О нас». **нужно разрешение**. |
| http://led.by/wp-content/uploads/2012/12/mass_sm.jpg | operator | ГУ ЛДС МО | страница массовых катаний. **нужно разрешение**. |
| http://led.by/wp-content/gallery/mass/00039.jpg | operator | ГУ ЛДС МО | галерея mass. **нужно разрешение**. |

Папка `photos/ledby/` пустая: явной лицензии на перенос в наш CDN нет.

## Conflicts
- Онлайн-касса: на http://led.by/mass_skating/ «по техническим причинам онлайн-продажа билетов временно не работает» vs в соседнем абзаце «в кассе или онлайн». Для карточки не обещать онлайн-покупку, пока касса снова не живая.
- Телефон приёмной директора (017) 397-01-00 на about-us — не номер катка для посетителя МК.
- В правилах МК переодевание «на скамейках в фойе», при этом в зонах учреждения перечислены раздевалки. `locker_rooms: true` про объект; не утверждать, что МК пускают именно в раздевалки.
