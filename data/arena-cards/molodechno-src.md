# Card: Спортивно-развлекательный центр «Олимпик-2011» (Молодечно)
- arena_id: 18
- slug: molodechno-src
- verified_at: 2026-09-07
- verified_by: photo-research-batch-1

Оператор — СРЦ «Олимпик-2011», ул. В. Гостинца, 102, Молодечно. Официальный сайт `src.by` (раздел `/WDKL/`). Многофункциональный комплекс (лёд, бассейн/аквапарк, боулинг, бильярд). На дату проверки — «остановочный период ледовой арены с 1 мая 2026 г.» (см. `.ai/parsers/molodechno-src.md`); аквапарк/бассейн также временно закрыты на ремонт (по состоянию на 10.08.2026).

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | адрес текстовый, обратное геокодирование не делали | 2026-09-07 |
| phone | +375 (17) 670-7778 ; +375 (17) 670-7706 (администрация) ; +375 (44) 711-17-13 (моб.) | https://src.by/WDKL/ | 2026-09-07 |
| website_url | https://src.by/WDKL/%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%B0%D1%8F-%D0%B0%D1%80%D0%B5%D0%BD%D0%B0 (ледовая-арена) | job.config парсера; корень https://src.by/WDKL/ | 2026-09-07 |
| opening_hours | unknown | Общий режим работы объекта на сайте не найден; расписание сеансов МК публикуется отдельно на странице ледовой арены, но сейчас «остановочный период» | 2026-09-07 |
| season | остановочный период с 1 мая 2026 г. (дата снятия факта: 2026-09-05) | .ai/parsers/molodechno-src.md | 2026-09-07 |
| amenities | skate_rental: true (прокат коньков, оплата на стойке проката); locker_rooms: true (гардероб для верхней одежды и обуви); parking: unknown; skate_sharpening: unknown; cafe: unknown; accessibility: unknown | https://src.by/WDKL/%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%B0%D1%8F-%D0%B0%D1%80%D0%B5%D0%BD%D0%B0 | 2026-09-07 |
| short_description | Ледовая арена в составе спортивно-развлекательного центра «Олимпик-2011» (ул. В. Гостинца, 102, Молодечно) — часть многофункционального комплекса с бассейном/аквапарком, боулингом и бильярдом. Вместимость сеанса — 180 чел., сеанс 45 мин. На дату проверки — остановочный период ледовой арены с 1 мая 2026 г. | https://src.by/WDKL/%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%B0%D1%8F-%D0%B0%D1%80%D0%B5%D0%BD%D0%B0 | 2026-09-07 |
| socials | Instagram https://www.instagram.com/src.olimpik2011 ; Telegram https://t.me/LedovijDVOREC | https://src.by/WDKL/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://src.by/WDKL/wp-content/uploads/2025/01/2.jpg | operator | src.by, страница «ледовая-арена» (WordPress-загрузка на собственном домене) | Проверено визуально — интерьер ледовой арены: хоккеисты на льду, флаги федераций на стене, надпись «БЕЛАРУСЬ», трибуны. Fetchable `image/jpeg`, ~116 КБ. |
| https://src.by/WDKL/wp-content/uploads/2025/01/1-8.jpg | operator | src.by, страница «ледовая-арена» | Запасной вариант с той же страницы, ~892 КБ, не просматривался визуально, но URL с того же официального `wp-content/uploads` пути. |

## Conflicts
- Нет расхождений расписания/цен — объект в статусе skip (остановочный период), сетка не материализуется.
