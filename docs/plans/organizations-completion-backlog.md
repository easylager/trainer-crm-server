# Organizations completion backlog

**Цель:** довести `studio` / `center` / `center_hybrid` до production-ready: каждая роль видит только нужное, управление организацией понятно, каталог корректно представляет бренд.

**Принципы (не negotiable):**
- Один trainer mini-app, один client catalog — без второго продукта.
- Навигация **progressive disclosure**: базовый tab bar не меняется; организационные экраны — в «Студия» / контекстных шагах.
- Копирайт и иерархия зависят от `organization_format`, не от внутренних enum-имён.
- Премиум 2026: `theme.css`, `mini-app-components.css`, visual constitution — без новых «CRM-2018» панелей.
- Нативность Telegram: sheet, haptic, короткие заголовки, один primary CTA на экран.

**Канонические форматы:**

| format | schedule_mode | owner access | Клиентский UX |
|--------|---------------|--------------|---------------|
| `studio` | member_autonomous | full_trainer | Рoster тренеров → слоты |
| `center` | studio_central | studio_admin_only | Сетка центра → формат визита |
| `center_hybrid` | studio_central | full_trainer | Сетка + опционально «Тренеры» |

---

## Personas × surfaces (target matrix)

| Persona | Studio | Center | Center hybrid |
|---------|--------|--------|---------------|
| Owner (full) | Бренд, команда, invite, client link, подписка pool | + сетка, passes, inbox записей, delegate | Всё center + личный CRM (home, clients, schedule) |
| Admin | Бренд (если can_edit), команда read-only? | Сетка, passes, delegate, inbox | Как center admin |
| Member-coach | Client link, roster peers | Client link, duty в календаре, без admin tabs | Client link + personal slots + duty |
| studio_admin_only | N/A | Только home + «Студия» | N/A |

---

## Baseline (уже есть)

- [x] Presets `studio` / `center` / `center_hybrid` + migration 0172
- [x] `organization_format` в bootstrap / studio payload
- [x] Multi-membership, merged schedule (W4), admin role + delegate API (W5)
- [x] trainer-collective: tabs brand/page/schedule/passes/team (schedule/passes — studio_central admin)
- [x] Catalog collective hero + center sessions booking (W2 path)
- [x] Context picker API `/trainer/booking-contexts` + UI в schedule-editor, trainer-clients, hub (частично)

---

## Epic O0 — Product contract & capability flags

Единый контракт для UI/backend — чтобы не размазывать `if schedule_mode` по 20 файлам.

| ID | Задача | Acceptance |
|----|--------|------------|
| O0.1 | **`OrganizationCapabilities` resolver** (Python): из `(organization_format, schedule_mode, role, studio_access_mode)` → flags: `show_personal_crm`, `show_center_grid`, `show_center_passes`, `show_team_invite`, `show_brand_edit`, `catalog_mode`, `shell_nav_profile` | Unit-тесты на все 9 комбинаций role×format; один источник правды | ✅ `organization_capabilities.py` |
| O0.2 | Прокинуть `capabilities` в hub bootstrap, studio payload, onboarding checklist | Frontend читает flags, не дублирует логику | ✅ API готово; UI — Epic O1 |
| O0.3 | Public catalog API: `organization_format`, `catalog_mode`, `hero_variant` в `/api/public/collectives/{slug}` | Client catalog не гадает по schedule_mode | ✅ API + catalog-main.js |
| O0.4 | ADR-003 appendix: таблица format → UX (1 страница, ссылка из admin help) | Onboarding новых пилотов без чтения кода | ✅ 003-appendix-organization-format-ux.md |

---

## Epic O1 — Shell & first-run (native, не перегружать)

| ID | Задача | Acceptance |
|----|--------|------------|
| O1.1 | **Format-aware copy** в shell: eyebrow «Студия» / «Центр», hints в More sheet | `organization_format` меняет текст, не структуру tab bar | ✅ shell.js |
| O1.2 | **studio_admin_only** nav audit: home + collective только; скрыть pass-products/subscription из More где не applies | Locked items с понятным sheet «Режим администратора центра» | ✅ tab bar + sheet locks |
| O1.3 | **center_hybrid** onboarding: после claim owner видит 2-line hint на home | dismissible once | ✅ hubOrganizationHint |
| O1.4 | **Multi-collective switcher** в hub header | chip + sessionStorage | ✅ hubCollectiveSwitcher |
| O1.5 | Sync switcher между hub, collective, booking-contexts | `trainer_collective_slug` + bootstrap `collective_slug` | ✅ |

---

## Epic O2 — Studio format (`studio`)

White-label: каждый тренер автономен, организация = бренд + pool + roster.

### Owner / admin

| ID | Задача | Acceptance |
|----|--------|------------|
| O2.1 | Rename UI copy: «Студия» везде, не «центр»; role eyebrow `Owner · студия` | trainer-collective, hub hints |
| O2.2 | **Preview «Как видят клиенты»** для studio: mock catalog hero + trainer list (read-only) | Preview использует public brand API | ✅ + кнопка «Открыть каталог» |
| O2.3 | Team tab: invite flow + seat limit UX (progress bar мест) | Owner видит pending invites count | ✅ seats meter |
| O2.4 | Admin (не owner): явные limits — что может / не может (brand read-only или edit per ADR) | Badge + disabled actions с hint | ✅ admin scope hint |
| O2.5 | Subscription pool block: copy «Подписка покрывает команду» + link checkout | Owner only | ✅ |

### Member-coach

| ID | Задача | Acceptance |
|----|--------|------------|
| O2.6 | Member view: один экран «Ваша ссылка для клиентов» + compact team list | Без brand editor, без tabs owner | ✅ |
| O2.7 | Member checklist on home (optional chip): «Добавьте слоты» если schedule empty | Не дублирует полный onboarding solo | ✅ hubMemberSlotsChip |
| O2.8 | Booking clients: context «Студия {name}» vs «Личная практика» когда 2+ memberships | Hub quick book + trainer-clients parity | ✅ TrainerBookingContext |

---

## Epic O3 — Center format (`center`)

Facility manager, без личного CRM у owner.

### Owner-admin (studio_admin_only or owner+admin_only)

| ID | Задача | Acceptance |
|----|--------|------------|
| O3.1 | Rename UI: «Центр» / «Управление центром»; eyebrow `Admin · центр` | trainer-collective title, shell | ✅ syncCollectiveNavLabels |
| O3.2 | **Default landing** studio_admin_only → `trainer-collective` tab schedule (если grid empty → CTA «Создать первое окно») | После claim попадает в actionable state | ✅ tab=schedule + empty CTA |
| O3.3 | Schedule tab polish: create session sheet (date, time, capacity, service), list cards premium spacing | Matches catalog session card visual language | ✅ col-session-sheet + cards |
| O3.4 | **Recurring grid template** (weekly pattern → generate 4–8 weeks) | Admin не создаёт окна по одному; MVP: duplicate week | ✅ duplicate-week |
| O3.5 | Assign coaches on session: picker из active members, multi-select, empty state | Sync с catalog `assigned_coaches` | ✅ coach picker + PATCH |
| O3.6 | **Center inbox** на schedule tab: pending session-bookings, confirm/decline inline | Push lane-only → admin (backend verify) | ✅ colCenterInbox + API tests |
| O3.7 | Passes tab: CRUD collective_pass_products, seed reference tariffs, issue to client | Prices read-only for coaches |
| O3.8 | service_id на session create/edit (lane hour default) | Booking price correct in catalog |
| O3.9 | Staff booking UI: book client into center session (delegate) from collective or hub | Uses existing staff-session-booking API |
| O3.10 | Team: invite coaches, promote admin, remove member | owner-only promote; admin can assign coaches |
| O3.11 | Brand tab: address-first (city hidden), cover/about tuned for facility | Already partial — finish copy + preview |

### Member-coach (center)

| ID | Задача | Acceptance |
|----|--------|------------|
| O3.12 | Member view: «Вы в центре {name}» + link for clients + **«Мои смены»** (read-only list of assigned sessions) | No admin tabs | ✅ my_center_duties |
| O3.13 | Calendar: duty blocks labeled «Смена · {center}» distinct from personal | schedule-editor visual tier |
| O3.14 | Member cannot open schedule/pass tabs even via URL | API 403 + UI hidden |

---

## Epic O4 — Center hybrid (`center_hybrid`)

Owner тренирует сам + управляет центром.

| ID | Задача | Acceptance |
|----|--------|------------|
| O4.1 | Shell: full tab bar + collective; home shows **dual summary** (today personal bookings + center inbox count) | One glance, two numbers max | ✅ hubDualSummary |
| O4.2 | Context picker default: remember last used context per client | sessionStorage | ✅ trainer-booking-context.js |
| O4.3 | Owner can assign **self** on duty sessions | promote-admin not required for self-assign |
| O4.4 | Pass products: clarify coach passes vs lane passes in UI labels | Matches ADR tariff card |
| O4.5 | Personal pass-products tab remains for owner; collective passes separate | No merge of SKUs |

---

## Epic O5 — Schedule & booking (cross-format)

| ID | Задача | Acceptance |
|----|--------|------------|
| O5.1 | Merged calendar legend component (personal / studio slot / center duty) | Single compact legend, collapsible |
| O5.2 | Overlap detection UX: block confirm with human message | W4 backend + frontend surfacing |
| O5.3 | Hub quick book: context step always when `contexts.length > 1` | Commit hub picker changes | ✅ |
| O5.4 | Center staff book: pick member coach + session + attendance mode | Form ≤ 1 screen scroll |
| O5.5 | trainer-clients book flow parity with hub | Same context picker component (shared JS module) | ✅ trainer-booking-context.js |
| O5.6 | Notifications audit: lane-only → admin only; coach modes → assigned coach | Integration test |

---

## Epic O6 — Client catalog representation

Организация в каталоге = первое впечатление бренда.

### Studio catalog

| ID | Задача | Acceptance |
|----|--------|------------|
| O6.1 | Collective hero: logo, cover, tagline, about, gallery, accent — **studio variant** | `catalog_mode=studio_roster` | ✅ catalog-main.js |
| O6.2 | Trainer list filtered by collective membership; card shows studio badge | `collective_slug` filter verified | ✅ |
| O6.3 | Footer «Powered by Ice Studio» per ADR-001 | Visible on collective pages | ✅ |
| O6.4 | Default city from brand_tokens pre-applied | Deep link `col_*` + catalog URL | ✅ |
| O6.5 | Empty roster state: «Скоро откроемся» + contacts | Not broken catalog | ✅ |

### Center catalog

| ID | Задача | Acceptance |
|----|--------|------------|
| O6.6 | Hero variant **center**: address pin, hours/contacts prominent | `catalog_mode=center_grid` | ✅ catalog-main.js |
| O6.7 | Primary tab: center sessions (existing); sticky CTA | Sessions load ≤28 days | ✅ |
| O6.8 | **Secondary tab «Тренеры»** (optional): personal coach slots of members | ADR §1 studio_central coaches tab | ✅ center_hybrid |
| O6.9 | Attendance mode sheet: lane / guest / own coach / center coach; guest +15 copy | Matches ADR redeem rules display | ✅ CENTER_ATTENDANCE_MODES |
| O6.10 | Center passes purchase UI in catalog (W3) | Lane + coach products | ✅ catalog-main.js + collective-pass-order API |
| O6.11 | Pass redemption at booking: lane pass cannot pay coach portion | Error messages RU, clear |
| O6.12 | Preview in trainer-collective opens **real catalog URL** in Telegram webapp | Owner sees what clients see | ✅ |

### Client bot landing

| ID | Задача | Acceptance |
|----|--------|------------|
| O6.13 | `col_{slug}` message format-aware: studio → «Выберите тренера»; center → «Расписание центра» | Inline button to correct catalog tab | ✅ client_handlers |
| O6.14 | Tagline + cover thumbnail in bot message when set | Rich landing | ✅ answer_photo |

---

## Epic O7 — Governance & team

| ID | Задача | Acceptance |
|----|--------|------------|
| O7.1 | Role matrix doc → enforce in API (admin cannot transfer ownership, etc.) | Matches ADR §7 table |
| O7.2 | Promote admin UI confirmation + audit log event | owner-only |
| O7.3 | Remove member: warn active bookings / future duties | Soft validation message |
| O7.4 | Transfer ownership: center requires new owner active member | Existing flow + center copy |
| O7.5 | Seat limit: block invite with upgrade CTA | Owner sees pool checkout |

---

## Epic O8 — Admin bot & ops

| ID | Задача | Acceptance |
|----|--------|------------|
| O8.1 | `/collective_draft formats` shows 3 canonical + alias note | Done — verify after deploy |
| O8.2 | `/collective_draft status slug` — format, seats, owner mode, claim state | Done — admin bot + `get_collective_ops_status` |
| O8.3 | Runbook: onboard ice studio vs throwing center (copy-paste commands) | Done — `docs/ops/onboard-collective-formats.md` |
| O8.4 | Suspended collective: catalog 404, trainer banner | Done — public API 404 + shell banner + hub bootstrap |

---

## Epic O9 — QA & rollout

| ID | Задача | Acceptance |
|----|--------|------------|
| O9.1 | **Persona test matrix** (manual UAT checklist): 6 personas × 3 formats | Checklist in docs |
| O9.2 | Automated: `@pytest.mark.collective` + catalog API snapshots per format | CI green |
| O9.3 | Visual regression: trainer-collective tabs, catalog hero (light/dark) | Per visual constitution |
| O9.4 | Pilot ice-yoga-lane regression pass | No center tabs leaked |
| O9.5 | Pilot throwing center UAT | Grid → book → pass redeem → guest +15 |
| O9.6 | Migrate existing collectives post-0172 smoke | organization_format correct |

---

## Recommended execution waves

Не параллелить всё — иначе перегрузим UI и QA.

| Wave | Epics | Outcome |
|------|-------|---------|
| **A** (1–2 нед) | O0, O1, O2.1–O2.6 | Capability flags + studio polish + shell copy |
| **B** (2–3 нед) | O3.1–O3.11, O6.6–O6.12 | Center admin complete + catalog center |
| **C** (1–2 нед) | O4, O5 | Hybrid owner + booking parity |
| **D** (1 нед) | O6.1–O6.5, O6.13–O6.14, O7 | Studio catalog + bot landing + governance |
| **E** | O8, O9 | Ops + pilots |

---

## Explicit non-goals (держим scope)

- Отдельный admin bot или second mini-app shell
- Shared client roster across members
- Payroll / revenue share UI
- Room-level resource locking beyond capacity integer
- Более 5 visible tabs в trainer-collective (использовать sub-sheets)

---

## Definition of Done (organization phase)

1. Owner каждого формата за 5 минут понимает «что делать дальше» без support.
2. Member-coach не видит admin controls; admin не видит лишний personal CRM (center).
3. Каталог `?collective=` визуально неотличим от premium standalone brand (studio или center).
4. Context booking работает одинаково в hub, clients, schedule-editor.
5. Все capabilities покрыты тестами или UAT checklist item.
