# Card: Бобруйск-Арена
- arena_id: 38
- slug: bobruisk-arena
- verified_at: 2026-09-07
- verified_by: batch-D ice parser task (web only, без звонка)

Имя по заданию: «Бобруйск-Арена», Карбышева 11, Бобруйск. Официальный сайт — ГУ «Хоккейный клуб Бобруйск», https://bobruiskarena.by/ (площадка одна и та же, отдельного сайта арены нет).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | адрес текстовый, lat/lon в проде не проверялись — обратное геокодирование не делали | 2026-09-07 |
| phone | +375 (25) 501-20-89 | https://bobruiskarena.by/raspisanie — «Уточнить время массового катания можно по тел.» (тот же номер продублирован на /kontact) | 2026-09-07 |
| website_url | https://bobruiskarena.by/raspisanie | расписание МК; корень клуба https://bobruiskarena.by/ | 2026-09-07 |
| opening_hours | unknown | явного графика работы кассы/арены на сайте не нашли | 2026-09-07 |
| season | unknown | крытая арена, месяцы сезона МК на сайте не указаны | 2026-09-07 |
| amenities | skate_rental: true; skate_sharpening: true; parking: unknown; locker_rooms: unknown; cafe: unknown; accessibility: unknown | прокат коньков и заточка — строки прайса https://www.bobruiskarena.by/service/sport/massovye-kataniya | 2026-09-07 |
| short_description | Ледовая арена ГУ «Хоккейный клуб Бобруйск» (Карбышева 11). Несколько сеансов массового катания в неделю по расписанию хоккейной площадки; будние/выходные тарифы, прокат и заточка коньков. | https://bobruiskarena.by/raspisanie ; https://www.bobruiskarena.by/service/sport/massovye-kataniya | 2026-09-07 |
| socials | Instagram https://www.instagram.com/hockey_club_bobruisk/ ; VK https://vk.com/hockey_club_bobruisk | ссылки в шапке https://bobruiskarena.by/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| unknown | — | — | Галерея `/history-club` на cloudinary (домен `keystone-demo`) — непрозрачные хеш-имена файлов, содержимое не проверено (похоже на командные/игровые фото, не сама арена); один пробный URL вернул пустой ответ (сломанная/устаревшая ссылка). Чистого фото льда/арены с уверенной атрибуцией не нашли за отведённое время — не блокер, оставляем `unknown`. |

## Conflicts
- Телефонов на /kontact много (разные внутренние линии клуба); для карточки посетителя МК взят тот, что явно указан на самой странице расписания катания, а не общий администраторский.
