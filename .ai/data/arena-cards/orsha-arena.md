# Card: Ледовая арена (Орша)
- arena_id: 31
- slug: orsha-arena
- verified_at: 2026-09-07
- verified_by: TASK ice-regional-parsers-batch-c (web only, без звонка)

Адрес в проде: ул. Владимира Ленина, 79, Орша. Часть спорткомплекса ГСУ «Хоккейный клуб «Локомотив-Орша»» (в комплексе также универсальный зал «Олимпиец» — не лёд). `http://arena-orsha.by/` → 404, реальный сайт клуба `lokomotiv-orsha.by`.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | unknown | не проверялся | 2026-09-07 |
| phone | 8(0216)55-08-32 ; 8(0216)53-45-49 | страница контактов https://lokomotiv-orsha.by/контакты/ | 2026-09-07 |
| website_url | https://lokomotiv-orsha.by/расписание/ | прейскурант https://lokomotiv-orsha.by/прейскурант/ | 2026-09-07 |
| opening_hours | unknown | явный общий график на проверенных страницах не найден | 2026-09-07 |
| season | unknown | расписание публикуется понедельно (см. `.ai/parsers/orsha-arena.md`), явных месяцев сезона нет | 2026-09-07 |
| amenities | skate_rental: true («Предоставление коньков», 1 час/1 человек — прейскурант); skate_sharpening: true («Заточка коньков», прейскурант); parking: unknown; locker_rooms: true (раздевалка/судейская упомянуты в прейскуранте, но это про аренду арены, не про посетителя МК); cafe: true (ресторан «Атмосфера» упомянут в прейскуранте комплекса); accessibility: true (ответственная за работу с инвалидами указана на странице контактов) | https://lokomotiv-orsha.by/прейскурант/ ; https://lokomotiv-orsha.by/контакты/ | 2026-09-07 |
| short_description | Ледовая арена в составе спорткомплекса ХК «Локомотив-Орша» (наряду с залом «Олимпиец»); расписание массового катания публикуется фотографией листа на неделю, не HTML-таблицей. | https://lokomotiv-orsha.by/расписание/ | 2026-09-07 |
| socials | unknown | Instagram/VK/Facebook/Telegram не найдены на проверенных страницах | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| unknown | — | — | Найденные `<img>` на `lokomotiv-orsha.by/` — ресторан, бильярд, сауна, тренажёрный зал, спонсорские лого; ни один явно не лёд/арена. `Ld-*.jpg` в фикстуре — это сфотографированный лист расписания (OCR-источник), не витринное фото зала — не годится как карточка «фото арены». |

## Conflicts
- Парсер `OrshaArenaParser` (`orsha_arena_v1`) требует OCR (`pytesseract` + системный `tesseract` с языком `rus`) — эти зависимости пока не в `requirements.txt`; см. финальный отчёт задачи и комментарий в `src/ingestion/seed_config_regional_batch_c.py` (`ORSHA_ARENA_CONFIG`).
- Живой GET `https://lokomotiv-orsha.by/расписание/` на 2026-09-07 показывает те же два файла `Ld-31-06.jpg` и `Ld-07-13.jpg`, что и в фикстуре 2026-09-06 — сайт ещё не выложил неделю 14–20 сентября.
