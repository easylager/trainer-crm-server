# Card: Ледовый дворец «Сокольники»
- arena_id: 58
- slug: msk-sokolniki
- city: Москва
- country: RU
- verified_at: 2026-09-17
- verified_by: CONTENT (feat/ru-pilot-arena-content) — content-curation pass for PR #92's two live RU parsers, per `data/parsers/msk-sokolniki.md`

Не подхватывается `scripts/load_minsk_arena_cards.py` (глоб не рекурсивный, файл лежит в `data/arena-cards/ru/`) —
этот загрузчик работает только с фиксированным BY-набором `TARGET_ARENA_IDS`; расширение его набора — вне scope этой задачи.
Адрес/координаты/таймзона применены отдельным one-off скриптом напрямую в `arenas`/`arena_profiles`, фото — тем же
upload-путём, что использует загрузчик (`upload_arena_media_from_bytes`, license=own).

## Profile (→ arenas / arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| address (arenas.address) | улица Сокольнический Вал, 1Б | https://ld-sokolniki.ru/ (футер) и https://ld-sokolniki.ru/kontakty/ — оба совпадают; Nominatim нашёл POI «Ледовый дворец Сокольники» ровно по этому адресу (см. Geocoding) | 2026-09-17 |
| latitude/longitude | 55.7928941, 37.6714915 | Nominatim `search?q=Сокольнический Вал 1Б, Москва` → первый результат `class=leisure type=sports_centre name="Ледовый дворец Сокольники"`, `city=Москва` — совпадает с городом арены в БД | 2026-09-17 |
| timezone | Europe/Moscow | явно физически Москва; применено через `apply_admin_arena_profile_patch` | 2026-09-17 |
| phone | +7 (925) 239-55-50 (администрация); +7 (968) 685-51-23 (прокат, 10:00–20:00) | https://ld-sokolniki.ru/ футер / https://ld-sokolniki.ru/kontakty/ | 2026-09-17 |
| website_url | https://ld-sokolniki.ru/ | официальный сайт (тот же домен, что source страницы парсера `massovye-kataniya/`) | 2026-09-17 |
| opening_hours | 09:00–23:00 (аренда льда — «24/7, 365 дней в году») | https://ld-sokolniki.ru/ (главная, блок режима работы) | 2026-09-17 |
| district | unknown | Nominatim вернул только `suburb=район Сокольники`, без `city_district` — не выдумываем район (см. Conflicts) | 2026-09-17 |
| season | unknown | на открытых страницах нет явной формулировки месяцев сезона | 2026-09-17 |
| amenities | unknown | не подтверждено по открытым страницам в рамках этого прохода (не в scope — только адрес/фото/координаты/таймзона) | 2026-09-17 |
| short_description | Ледовый дворец «Сокольники» — спортивный комплекс в парке Сокольники (Москва), открыт в 1956 году, реконструирован к Универсиаде-1973. Два ледовых поля (60×26 и 58×26 м), 1300 мест. Массовые катания — расписание на /massovye-kataniya/. | https://ld-sokolniki.ru/o-dvorce/ | 2026-09-17 |
| socials | VK https://vk.com/ld_sokolniki ; Telegram https://t.me/sokolniki_icepalace | футер https://ld-sokolniki.ru/ | 2026-09-17 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| https://ld-sokolniki.ru/upload/iblock/9a8/m5c81towri1x0yokkrw01x5gy6b0vvkj.jpg | own | Ледовый дворец «Сокольники», официальный сайт, раздел «Галерея» (`/o-dvorce/galereya/`) | Загружено (arena_id=58, media id=101). Фойе с настенным логотипом «ЛЕДОВЫЙ ДВОРЕЦ СОКОЛЬНИКИ» — однозначно узнаваемый кадр, без сторонних людей крупным планом. 1280×960, JPEG, скачан напрямую с `ld-sokolniki.ru`. |

Другие кадры из той же галереи (`.../034/...`, `.../065/...` — трибуны с болельщиками; `.../560/...`, `.../9b3/...` — раздевалка, тренажёрный зал) отсмотрены и отклонены как менее показательные, не как проблема лицензии — тот же own-домен, просто не hero.

## Conflicts
- **Geocode-скрипт репозитория (`scripts/geocode_arena_addresses.py`) не мультистрановой**, вопреки описанию задачи и `docs/research/arenas-scale-2026-09-02.md` (раздел T-3, «СКРИПТ ГОТОВ»): в файле по-прежнему жёстко `countrycodes=by` (последний коммит по файлу — `de0e35e`, PR #59, не 2026-09-02), нет проверки границ города, нет `--city-id`/CSV-отчёта. T-3 в исследовательском документе — это план, который не приземлился в код. Геокодинг для arena_id=58/97 сделан здесь **напрямую через Nominatim** (см. Profile) с ручной проверкой `address.city == "Москва"`/`"Санкт-Петербург"` в ответе — тот же принцип, который T-3 предлагал автоматизировать. Общий скрипт не трогали (вне scope: только эти 2 арены).
- Район: Nominatim для этой точки не дал `city_district`, только `suburb=район Сокольники` (тот же паттерн, что у Минск-Арены — suburb не берём в `district`).
- Часы работы взяты с главной страницы (сводный блок), не с отдельной `/o-dvorce/rezhim-raboty/` — не открывали отдельно в этом проходе; при расхождении перепроверить оригинал.
- Старый адрес в БД до этого прохода был плейсхолдером `г. Москва` (без улицы) — заменён на точный адрес выше.
