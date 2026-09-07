# Card: Ледовая арена (Кобрин)
- arena_id: 25
- slug: kobrin-lds
- verified_at: 2026-09-07
- verified_by: ICE-REGIONAL-PARSERS batch A

Оператор — ГУ «ДЮСШ по зимним видам спорта г. Кобрина», Замковая площадь 11А. Официальный домен `arena.kobrin.edu.by` не отвечает (SSL handshake timeout) и 2026-09-06, и повторно 2026-09-07 — см. `.ai/parsers/kobrin-lds.md`. Расписание/цены в этой карточке идут со сторонних порталов `kobrininform.by` / `kobrincity.by` (не сайт оператора), это единственные рабочие источники сейчас.

## Profile (→ arena_profiles)
| field | value | source | verified_at |
|---|---|---|---|
| district | Кобрин | город без официального деления на districts в наших источниках; district = город | 2026-09-07 |
| phone | +375 (1642) 3-65-45 (администратор); +375 (1642) 3-66-57 (приёмная) | https://kobrininform.by/afisha/ledovaya-arena/ | 2026-09-07 |
| website_url | unknown | официальный домен `arena.kobrin.edu.by` не открывается (SSL handshake timeout, повторно проверено 2026-09-07); `kobrininform.by`/`kobrincity.by` — сторонние порталы, не сайт оператора, в `website_url` не подставляем | 2026-09-07 |
| opening_hours | unknown | нет общего режима работы; посещение только по недельному расписанию сеансов | 2026-09-07 |
| amenities | skate_rental=true; skate_sharpening=true; parking=unknown; locker_rooms=unknown; cafe=unknown; accessibility=unknown | прайс: «с прокатом коньков» / «без проката» подтверждает прокат; отдельная строка «Заточка коньков: 5 руб. 15 коп.» подтверждает заточку | https://www.kobrincity.by/katalog/sport-i-fitnes/sportkompleksy/ledovaya-arena-g-kobrina.html — 2026-09-07 |
| short_description | Ледовая арена ГУ «ДЮСШ по зимним видам спорта г. Кобрина», Замковая площадь 11А. Есть публичное физкультурно-оздоровительное катание (не только школьные группы) по недельному расписанию, прокат и заточка коньков. | https://kobrininform.by/afisha/ledovaya-arena/ | 2026-09-07 |

unknown явно писать `unknown`, не выдумывать.

## Photos
| file or URL | license (own\|operator\|permitted) | attribution | note |
|---|---|---|---|
| — | unknown | — | Официальный домен оператора недоступен (timeout), у арены нет собственного (не портального) соцаккаунта в найденных источниках. Фото на `kobrininform.by` (`ledovaya-arena.jpg`) — сторонний новостной портал, не официальный сайт/соцсеть оператора, поэтому не берём (правило: только operator-owned источник). Не искали в Google/сток. |

## Conflicts
- `kbr.by` держит **старую** неделю расписания — не источник (см. SPEC-досье), приоритет за `kobrininform.by`, если там свежее.
- `price_rental_minor` не публикуется отдельной строкой: вычислена как пакет «с прокатом» (взр. 7,60) минус «без проката» (взр. 3,30) = 4,30 руб. Детский инкремент (3,75) в спеке упомянут, в слот не дублируется (одно поле `price_rental_minor` на сеанс).
- Сеанс отменяется при <5 посетителей — на extract не влияет (это операционное правило кассы, не меняет опубликованное расписание).
