# Glide Landing — Creative Direction Re-evaluation

**Date:** 2026-08-24
**Status:** DECISION DOCUMENT — no prototype, no implementation
**Supersedes:** DEC-009 / DEC-010 ("The Infinite Edge") as the active direction
**Preserves:** all product discovery, real-copy inventory, and constraints from TASK-001

---

## 0. What we keep from the failed experiment

Infinite Edge is retired as a direction. These findings survive it and constrain everything below:

1. **Care Pulse is the real differentiator** and is still absent from the live landing (`static/landing/index.html` goes hero → arc → bento → steps → CTA). Real copy exists at `src/bot/messages.py:598-630`.
2. **Real product UI must be the primary visual object**, not decoration (DEC-010). This was right; Infinite Edge just couldn't honour it, for a structural reason diagnosed in §1.
3. **The audience is mobile-first inside Telegram** — a solo trainer, phone in hand, between sessions, in a cold arena. This kills anything that only works at 1440px.
4. **Copy policy: real copy verbatim.** `static/landing/verticals/ice.by.json` + `messages.py` are the vocabulary. New copy only where the narrative demonstrably needs it.
5. **No spectacle-first ordering.** PRODUCT → STORY → BRAND MOTION.

---

## 1. Why Infinite Edge failed — the structural diagnosis

The critique in the brief is correct, but the root cause is more specific and more useful than "the metaphor got too big":

**The real product UI is light.** `static/webapp/theme.css` is an explicit, documented, well-argued system:

| Token | Value | Role |
|---|---|---|
| `--glide-paper` | `#FBFAF7` | canvas — warm paper, not grey |
| `--glide-surface` / `--glide-card` | `#FFFFFF` | cards |
| `--glide-line` | `#ECEBE6` | hairline rules |
| `--glide-text` | `#16292A` | ink — deliberately *not* black |
| `--glide-500` | `#34C6C4` | fill accent only |
| `--glide-ink-teal` | `#0C6F6C` | teal for text/icons |

And it carries a stated philosophy in the comments:

> «Крупные плоскости держим на почти нейтральных тонах… цвет читается, но не "звенит" на всю площадь экрана.»
> «--glide-text намеренно НЕ чёрный: максимальный контраст на просвет мобильного экрана даёт ореол вокруг букв.»
> Reference brands cited in-code: Perplexity, Deliveroo, Tiffany.

Infinite Edge put this light, paper-toned, hairline-drawn product **on a black cinematic stage**. That guarantees the failure mode the brief describes: every real screen becomes a bright rectangle floating in a void, which is *definitionally* the "premium tech / AI SaaS" trope. It is not a polish problem. Making the ribbon subtler cannot fix it — the ground itself was wrong.

**Corollary that should govern all three directions:** the landing's default ground is paper/white, matching the product. Darkness, if used, is an *event*, not the environment.

Second structural note: the theme file already prohibits teal on large planes. Honouring that rule is what mechanically prevents the "generic green SaaS" outcome the brief fears — the discipline is already written down, we just have to obey it.

---

## 2. Product evidence inventory (source of truth for all three)

**Real trainer-side screens available as material** (`static/webapp/`):

| Screen | File | What it shows |
|---|---|---|
| Trainer hub | `trainer-home.html`, `mini-app-trainer-hub.css` | «Доброе утро», week pulse, «Ближайшие занятия», «Подтвердить все», «Первый клиент», «Пригласительная ссылка» |
| Schedule | `schedule.html`, `schedule-editor.html` | «Моё расписание», slot rows, «Свободно», «Заняты», «Редактор расписания», «Отклонить запись» |
| Clients | `trainer-clients.html` | «Мои клиенты», «Постоянные», «С абонементом», «Быстрая запись», «Добавить клиента», «Скопировать ссылку» |
| Requests | `trainer-requests.html` | «Заявки клиентов», «Для вас», «Готов взять», «В работе», «Свободные слоты по дням», «Отправить отклик» |
| Analytics | `trainer-stats.html` | «Статистика и выручка», «Сводка и бухгалтерия — без лишних вкладок» |
| Client booking | `book.html` | «Выберите услугу», «Выберите время», «Вы записаны», «Поделитесь ссылкой одним касанием» |
| Catalogue | `catalog.html` | «Найдите тренера», «Свободные слоты на 14 дней», «Открыть карточку — запись, заявка, абонементы» |
| Client home | `client-home.html` | «Записаться», «Все записи», «Чудесного дня на льду 🐧» |

**Real bot copy** (`messages.py`) — voice note in the source: *"calm, specific, one fact, no guilt."*

- `CARE_PULSE_TRAINER_QUIET`: «🌿 **Сегодня без тренировок.** Расписание на месте. Если появится запись или отмена — напишем сразу. Ничего не потеряется.»
- `CARE_PULSE_TRAINER_OPEN_SLOTS`: «🌿 **Клиенты могут записаться сами.** На ближайшую неделю свободно: N окон. Ссылка у них уже есть — писать тебе в личку не нужно.»
- `CARE_PULSE_CLIENT_CONFIRMED`: «🌿 **Запись на месте.** … Напоминание придёт накануне.»
- `TRAINER_REQUEST_NOTIFICATION`: «📩 **Новая заявка**»
- Weekly digest + drought ladder: «На неделе тихо…», «Неделя собрана. Воскресенье — твоё.»

**Real landing copy** (`ice.by.json`) — hero, 4 value pillars, activation arc (Telegram → Ссылка → Подтверждение → Рост), 6 bento items, 3 steps, CTA band.

---

## 3. Blockers and unresolved brand facts (must be settled before build)

**B-1 — No transparent logo asset exists.** Verified: all files in `static/logos/` report `format: jpeg`, `hasAlpha: no`, including `glide-horizontal-teal-icon-black-text-on-white.png`. The brief asks to use "the actual transparent logo asset" — it is not in the repo. Options: (a) request SVG/transparent PNG from the designer — strongly preferred; (b) vector-trace the mark ourselves; (c) restrict logo placement to flat white or flat black grounds where the existing rasters composite cleanly. Every direction below assumes (a).

**B-2 — Three different teals are in play.**

| Source | Value |
|---|---|
| `theme.css --glide-500` (pixel-sampled from the mark) | `#34C6C4` |
| `static/logos/README.md` ("приблизительно") | `#47B6B9` |
| Human-supplied in DEC-006 | `#45B9BB` |

`#34C6C4` is the greenest of the three and is the one currently shipping in the product. `#45B9BB`/`#47B6B9` are cooler and closer to "icy teal". Needs one authoritative token. My recommendation: `#45B9BB` as the *brand* teal, keep `#34C6C4` inside product screenshots so they stay UI-accurate, and never put either on a large plane.

**B-3 — "Ice Pro" vs "Glide" is still Q-001.** `ice.by.json` says `"name": "Ice Pro"`, `"eyebrow": "Ice Pro · solo-тренеры · Беларусь"`. `static/logos/README.md` says the brand is Glide. All three directions assume **Glide**, which means `ice.by.json` needs a copy revision — flagged, not silently assumed. (Separately: «solo-тренеры» is an anglicism; «тренерам на льду» reads native.)

**B-4 — Typography.** DEC-006 declared an Avenir-first stack with no webfont in the repo; the live landing loads Playfair Display + DM Sans. Playfair is the weakest link — it is the single most over-used "premium" serif on the web and it fights the product's precise, hairline, engineered feel. All three directions below drop it.

---

## 4. The narrative spine (shared by all three)

The brief asks that every major section answer at least one business question. Here is the spine, mapped. Note it deliberately does **not** open with the problem — a trainer who lands here already lives the problem; spending the first viewport describing it wastes the 5-second window.

| # | Beat | Real UI | Question answered | Real copy source |
|---|---|---|---|---|
| 1 | Who this is for + what it is | Trainer hub | What does Glide do? | `hero.title`, `hero.subtitle`, `value_pillars` |
| 2 | The link does the asking | `book.html` + `schedule.html` | Reduces admin work | `activation_arc.link`, `bento.slots` |
| 3 | One tap confirms | Hub inbox → confirm → reminder | Saves time | `activation_arc.confirm` |
| 4 | Clients find you | `catalog.html`, `trainer-requests.html` | Brings clients | `bento.catalog`, `bento.stats` |
| 5 | You remember everything | `trainer-clients.html` dossier | Manages clients | `bento.notes` |
| 6 | You can see the business | `trainer-stats.html` + weekly digest | Business visibility | `bento.analytics`, digest copy |
| 7 | It speaks only when it matters | Care Pulse message | Why not a generic CRM | `CARE_PULSE_*` verbatim |
| 8 | Start | — | Conversion | `cta.band_title/subtitle` |

Beat 7 sits **late and short** — it is the closing character note, not a philosophy essay. This is the direct correction to "Care Pulse became disproportionately philosophical."

---

# DIRECTION A — «Рабочий день»
### *The Working Day* — restrained / editorial

**1. Name.** «Рабочий день» (The Working Day).

**2. Core visual concept.** The page's information architecture *is* a timetable. A hairline time rail runs down the left margin — `07:40 · 09:15 · 13:00 · 16:20 · 20:30 · Воскресенье` — set in tabular mono numerals. Each section is a moment in one trainer's real day, and at each moment a real product screen is doing the work. There is no metaphor imposed on the product: the page borrows the product's own primary object, a schedule, as its layout grammar. Editorial magazine treatment — paper ground, wide margins, confident type scale, hairline rules, teal only as a marker.

**3. First viewport.** Paper `#FBFAF7`. Top-left: horizontal Glide lockup at modest size. Left column (~46%): eyebrow «Glide · тренерам на льду · Беларусь», H1 «CRM для тренера на льду» set very large and tight, `hero.subtitle` verbatim, four `value_pillars` as a plain hairline-ruled list (not chips, not cards), one primary CTA «Начать в Telegram». Right column: the real trainer hub screen at true device scale, **top-aligned and bleeding off the bottom of the viewport** like a magazine page — not a floating phone with a glow, not a shrunken card. The time rail's first mark, `07:40`, sits at the left margin. No hero photograph, no particles, no gradient.

**4. Scroll narrative.**
- **07:40 — «Ещё до катка».** Care Pulse morning message at real scale. → *Why not a generic CRM* (moved early here because it is literally what happens first in the day; if it reads as too philosophical this beat moves to the end per §4).
- **09:15 — «Пока вы на льду».** Two real screens side by side at equal scale: `book.html` slot picker (client) and `schedule.html` with the «Свободно · Онлайн-запись» row. One line of copy between them. → *Reduces admin work.*
- **13:00 — «Между тренировками».** Hub inbox: «Сейчас важно · Анна · 18:00 · Minsk Arena — подтвердить» → tap → confirmed → reminder queued for both. → *Saves time.*
- **16:20 — «Пока вы не смотрите».** Catalogue card and «Заявки клиентов · Готов взять». → *Brings clients.*
- **20:30 — «После льда».** Client dossier: заметка после занятия, цель сезона. → *Manages clients.*
- **Воскресенье.** Weekly digest, real numbers, real recommendation line. → *Business visibility.*
- **Close.** CTA band on paper; a single restrained brand moment — full-width, the mark, nothing else.

**5. Where real UI appears.** Every section. Real UI is the *only* imagery on the page apart from at most one rink photograph used once as a breath. Screens appear at device scale or larger, never cropped to an unreadable fragment.

**6. How motion communicates product behaviour.** Motion is exclusively state change inside real UI: a schedule list scrolls one row; a request row flips «ожидает» → «подтверждено»; a counter ticks 12 → 13; a reminder toast enters. The time-rail marker travels with scroll and doubles as section nav. Nothing flies, nothing parallaxes, nothing glows. Reduced-motion: every state is legible as a static frame, because each is a real product state.

**7. Ice/brand without literalism.** Expressed as *material*, not imagery: warm paper canvas, frost-toned hairlines (`#ECEBE6`), cold precise geometry, and a single teal that appears only where the product itself puts teal — active state, confirmation, the rail marker. One controlled ice gesture: section rules draw left-to-right on entry at constant velocity with a long decelerate — a blade edge, implied, never illustrated.

**8. Colour and typography.** Ground `--glide-paper`; cards white; ink `#16292A`; teal `#45B9BB` in micro-doses. Display: a contemporary grotesk with real character at large size and tight tracking (Neue Haas / Söhne class — **not** Playfair). Time rail and all numerals: a tabular mono. Body: the product's own sans, so landing copy and product copy read as one voice. The mono time column is the device that makes it feel like a real timetable rather than a design flourish.

**9. Mobile.** The strongest of the three on mobile. The rail collapses to a small sticky time chip; sections stack; real screens render at ~full viewport width — which is their **native scale**, so they look correct rather than shrunken. On a phone the landing is effectively a guided walk through the product.

**10. Why this is specifically Glide.** The page's structure is one trainer's day, taken from the product's own primary object. A horizontal SaaS cannot use this layout — it only means something for a product whose unit of value is a day on the ice. It also extends the *already excellent, already documented* design system in `theme.css` instead of inventing a second visual language that then has to be reconciled with the app.

**11. Main risk.** Ambition perception. The human already rejected Quiet Rink for being "technically competent, not ambitious enough," and this direction spends its ambition on typography, crop confidence, and restraint — qualities that read as premium in print and can read as *plain* in a browser to someone expecting a wow moment. Honest assessment: this is the direction most likely to draw the same rejection.

**12. Why better than Infinite Edge.** It puts the product on its own ground instead of a borrowed cinematic stage; the metaphor cannot outgrow the product because the metaphor *is* the product; every second of motion carries product meaning; and the 5-second test is passed by the first viewport, not deferred to scene 3.

---

# DIRECTION B — «От касания до сезона»
### *Tap to Season* — highly visual / cinematic

**1. Name.** «От касания до сезона» (From one tap to a season).

**2. Core visual concept.** A single continuous camera pull-back. The page opens in extreme macro *inside* the product — one real UI element rendered at architectural scale — and every scroll step pulls the camera back one level of context, until the final frame contains the whole business. The cinema comes entirely from **scale and framing of real UI**, not from any invented 3D object. There is no ribbon, no particle field, no logo-derived geometry. The only thing that moves is the camera, and what it reveals is always the product.

**3. First viewport.** Not a page — a surface. One real schedule row fills the screen edge to edge: `18:00 · Свободно · Онлайн-запись`, hairline border razor-sharp at 200×, teal dot at true brand value, paper ground. The Glide mark small in the corner. H1 overlaid at the left margin in large tight grotesk: «CRM для тренера на льду», with `hero.subtitle` and the CTA. The composition reads as industrial design — a close-up of a well-made object. A quiet scroll cue at the bottom.

**4. Scroll narrative** (each step is a discrete, snapped pull-back, not free-scrubbing):
- **×200 — one slot.** «Свободно» → *what the client sees.* `activation_arc.link`.
- **×40 — the schedule screen.** The row is one of a day. «Моё расписание». → *Reduces admin work.*
- **×10 — the hub.** The schedule is one surface among several; week pulse, «Ближайшие занятия», the inbox. A request arrives; one tap confirms; the reminder fires. → *Saves time.*
- **×3 — two phones.** The trainer's hub and the client's `book.html`, connected by the link. Telegram-native, no install. → *What Glide does.*
- **×1 — the catalogue.** The two phones become two of many: trainers, arenas, cities, «Заявки клиентов». → *Brings clients.*
- **The season.** Camera stops pulling back and pulls *forward in time* instead: dossier, season goal, notes, then the weekly digest and analytics. → *Manages clients / business visibility.*
- **Full stop.** Everything drops away to paper. Care Pulse, one message, one line. Then the mark and the CTA. → *Why not a generic CRM / conversion.*

**5. Where real UI appears.** It is the *only* material on the page. There is literally nothing else to look at — the entire visual budget is spent on rendering real screens at extreme fidelity.

**6. How motion communicates product behaviour.** The pull-back is itself the argument: *this product scales from one tap to a whole practice*. Inside each stop, motion is real state change (request arrives, confirm, counter ticks). The transitions carry a "glide" easing — long, low-friction, zero bounce, decelerating like a skater carrying speed off an edge. That easing curve is the brand's only motion signature and it is used everywhere, which makes it read as intentional rather than decorative.

**7. Ice/brand without literalism.** Three channels: the glide easing curve; the cold hairline geometry of the real UI seen at macro (frost-thin lines, precise corners, huge negative space); and an inversion — the surround only becomes visible as the camera pulls back, and it is `--glide-950` `#04262A`, the product's own deepest token, not a generic black. We start *inside* the product on paper and end *outside* it in the cold. The mark appears twice: small at the top, full-scale at the end.

**8. Colour and typography.** Paper and white at the near scales; `#04262A` surround at the far scales; teal only on live states. Display grotesk at very large sizes, tight, left-aligned to a hard margin — captions set small in the product's own UI font so the copy feels contiguous with the screens rather than floating over them. Tabular numerals throughout.

**9. Mobile.** The weakest of the three, and it needs an explicit redesign rather than a scale-down: continuous scroll-linked transforms become **discrete scroll-snap stages** with cross-fades, no scrubbing. Reduced-motion and low-end devices fall back to a stacked sequence of static frames with captions — which is essentially Direction A, so the fallback is at least coherent.

**10. Why this is specifically Glide.** The subject of every frame is a trainer's real day at a real arena, and the zoom levels correspond to real product boundaries (slot → day → hub → link → catalogue → season). It is not a generic "zoom into the future of work."

**11. Main risk — stated plainly.** *This is the direction most at risk of reading as a generic award-site.* Continuous-zoom scrollytelling is one of the most recognisable Awwwards/Apple-product-page tropes of the last decade; executed at 80% it looks like a template. It is also the weakest on the 5–10 second test — a macro shot of a slot row does not, on its own, tell a visitor who this is for. It leans hard on the H1 to carry qualification, which is exactly the fragility that sank Infinite Edge. Secondary risks: real performance exposure on mid-range Android inside Telegram's webview; and it needs real UI assets at 3–4× fidelity, which means genuine high-res captures, not upscaled screenshots.

**12. Why better than Infinite Edge.** The camera has a reason to move that is a product argument rather than a brand flourish; there is no invented geometry that can grow to outshine the product; the ground is the product's own paper rather than a borrowed cinematic void; and the logo is never turned into scenery.

---

# DIRECTION C — «Живая ссылка»
### *The Live Link* — different interaction model, not scrollytelling

**1. Name.** «Живая ссылка» (The Live Link).

**2. Core visual concept.** The landing is not a story about the product. **It is the product.** The hero is a working booking flow: the visitor is handed a demo trainer and books a slot themselves, in real product UI — and watches the trainer's side of Glide react in real time. The single most important artifact in this business is `Ссылка → клиент записался сам`. Every other landing *describes* that link. This one *hands it to you*. Below the demo, a short editorial run covers what the demo can't show.

**3. First viewport.** Split desk on paper ground.
- **Left, «Вы — клиент»:** a real `book.html` flow — «Выберите услугу» → «Выберите время» → slot grid, live and clickable. Above it: eyebrow «Glide · тренерам на льду · Беларусь», H1 «CRM для тренера на льду», `hero.subtitle` verbatim, and one invitation line.
- **Right, «Тренер — в Telegram»:** the real trainer hub, quiet, waiting. Week pulse, «Ближайшие занятия», empty inbox.
- The visitor taps a slot. The right pane comes alive: «📩 Новая заявка» arrives → «Сейчас важно» populates → «Подтвердить» → the slot flips «Свободно» → booked → «Напоминание придёт накануне» → the week counter ticks.
- **Idle state matters as much as the interactive one:** after ~4 seconds of no input the demo runs itself, once, slowly, so a visitor who never touches anything still receives the whole argument.
- Primary CTA «Начать в Telegram» sits under the left pane, present from the first pixel.

**4. Scroll narrative.** Deliberately short after the demo — the demo has already done the heavy lifting.
- **The demo** (above the fold, self-contained). → *What Glide does / saves time / reduces admin work.*
- **«Вас находят в каталоге».** Real catalogue card, real `bento.stats` numbers, «Заявки клиентов · Готов взять». → *Brings clients.*
- **«Клиент — не строчка в таблице».** Real dossier: чипы, цель сезона, лента заметок. → *Manages clients.*
- **«Неделя — одним экраном».** Real analytics + the weekly digest message. → *Business visibility.*
- **«Пишем, только когда есть что сказать».** One Care Pulse message verbatim, two lines of frame, nothing more. → *Why not a generic CRM.*
- **Three steps + CTA band.** Existing `steps` and `cta` copy, largely unchanged. → *Conversion.*

**5. Where real UI appears.** Hero (interactive, both sides) and every section below. The hero uses real components, not screenshots — which is the whole point.

**6. How motion communicates product behaviour.** 100% of motion on this page is literal product behaviour: a slot changing state, a request arriving, a confirm animation, a counter incrementing, a reminder queued. There is not one frame of decorative motion anywhere. This is the most complete answer possible to "animation exists but does not communicate product value."

**7. Ice/brand without literalism.** Through restraint and material — paper ground, hairline structure, teal reserved for live/active states, which here means teal appears *exactly when the product does something*. Colour becomes a signal, not a decoration. One deliberate brand breath: at the seam between the demo and the story, a single full-bleed rink photograph with the mark and the tagline «Расписание, которое не тает» — one image, once, earned by contrast with everything around it.

**8. Colour and typography.** Same system as A: paper `#FBFAF7`, white surfaces, ink `#16292A`, teal `#45B9BB` in micro-doses (product screens keep `#34C6C4` for accuracy). Display grotesk, tight, moderate scale — the type does not need to shout because the demo is the spectacle. Body and all in-demo text in the product's own UI font, because it *is* the product's UI.

**9. Mobile.** The split does not stack — it re-forms into something truer to reality. The visitor holds the client side full-screen (which is exactly how a real client experiences it), and the trainer's side arrives as a **Telegram-style notification sliding down from the top** — «📩 Новая заявка» — which you can tap to flip to the trainer view. That is not a compromise for small screens; it is more accurate than the desktop split, because in real life these two people are never looking at one screen together. This solves the exact problem that killed "Two Rinks" (DEC-005).

**10. Why this is specifically Glide.** Because Glide's core promise is a *link that does the asking for you* — and this is the only landing structure where the visitor experiences that promise instead of reading it. It also proves the product exists and works, which for a small unknown product in a small market is worth more than any amount of production value. A generic CRM cannot copy this: most CRMs have no single self-contained flow short enough to demo in fifteen seconds.

**11. Main risks.**
- **Execution bar is unforgiving.** If the demo feels janky, fake, or toy-like, credibility inverts and the page is *worse* than a static one. Real UI at half-quality is more damaging than an honest screenshot.
- **Engagement is unproven.** Some visitors won't touch it. The idle auto-play is the mitigation and it is not optional.
- **Lowest raw "wow" on first frame.** Given two prior rejections on visual ambition, this is the real political risk. The counter-argument is in §5.
- **Scope discipline.** The demo must stay one flow. The moment it grows a second flow it becomes a product tour and loses its edge.

**12. Why better than Infinite Edge.** Infinite Edge had a metaphor that grew larger than the product; this has no metaphor at all. Infinite Edge's motion communicated brand; this one's motion *is* the product. Infinite Edge asked the visitor to watch; this asks them to use. And it passes the 5–10 second test in the strongest possible way — not by explaining, but by working.

---

# 5. Recommendation

## **Direction C — «Живая ссылка»**, built on Direction A's editorial visual system.

To be precise about what that means, because it is one recommendation and not a hedge: **C defines the page's interaction model and hero; A defines the typographic and material system for the whole page.** They are compatible by construction — both sit on the product's own paper ground, both use real UI as the only imagery, both reserve teal for live states. A is the visual language; C is what the page *does*. Direction B is rejected.

### Why C wins, criterion by criterion

**Product clarity.** Nothing on this list comes close. Every other direction — including A, and including anything Infinite Edge could have become — asks the visitor to read an explanation of "клиент записался сам." C makes them do it. The 5–10 second test is passed by demonstration, which is the only form of clarity that cannot be misread.

**Visual quality.** Real product UI at full scale on paper ground, hairline-drawn, with a single teal signal and one earned photograph — this is the same visual system that `theme.css` argues for at length and that the app already ships. Extending a coherent existing system produces a more finished page than inventing a second one. The demo's live state changes give the composition motion and life that a static editorial page has to work hard for.

**Differentiation.** Highest of the three, and differentiated in a way competitors structurally cannot copy — it depends on the product having one short self-contained flow, which is Glide's actual architecture. B's differentiation is aesthetic and therefore borrowable; C's is architectural.

**Credibility.** This is the decisive one and it is under-weighted in the brief. Glide is a small product in a small market selling to individuals who have been burned by software that promised to save them time. A working demo answers "is this real, and does it actually work?" before the visitor has to trust a single marketing claim. No cinematic treatment can do this — in fact, high production value on an unknown product *increases* suspicion.

**Use of real UI.** Maximal, and qualitatively different from the others: A and B use real UI as *imagery*; C uses it as *itself*. This is the only direction where DEC-010's "real UI is the primary visual object" is not a discipline we have to maintain against pressure — it is the load-bearing structure.

**Brand fit.** Glide's documented voice is «calm, specific, one fact, no guilt». Its design system's stated principle is that colour lives only in accents and large planes stay quiet. Care Pulse's entire premise is *speaking only when there is something to say*. A landing that shows rather than declaims is the same personality expressed at page scale. Infinite Edge — a 3D ribbon flying through a black void — was, in retrospect, brand-incoherent: it was loud on behalf of a product whose whole thesis is quiet.

**Premium without visual noise.** The noise problem is solved structurally, not by taste. There is no decorative layer to get noisy, because there is no decorative layer at all. Premium comes from the three things that actually signal it — material honesty, typographic confidence, and interaction that feels engineered rather than animated.

### On the ambition question, directly

Two directions have now been rejected as insufficiently ambitious, so this needs answering rather than avoiding.

C's wow moment is not visual. It is: *«подождите — я только что записался к тренеру прямо на лендинге, и увидел, как тренер это подтвердил.»* That is a more durable memory than any camera move, and it is a much harder thing to build than a 3D ribbon — a ribbon is a weekend of CSS transforms; a landing page that is a working slice of the product is a genuine engineering flex. If the ambition bar is "premium," C clears it through craft. If the bar is specifically "cinematic spectacle," then C does not clear it and we should have that conversation explicitly rather than discover it after a prototype — because the honest finding of this pass is that **cinematic spectacle is the wrong instrument for this product**, and Direction B is where that argument would have to be won.

### Self-criticism, stated plainly

- **B is a generic-award-site risk and I am saying so unprompted.** Continuous zoom-out scrollytelling is a trope. It would photograph beautifully in a case study and would probably underperform as a landing page for a Belarusian solo trainer deciding whether to trust an unknown bot.
- **A is the safest and might well get rejected for exactly that.** It is a genuinely good page and it is the right fallback if C's demo proves too risky to build well — but it is Quiet Rink's temperament with a better structure, and temperament is what was rejected.
- **C's largest risk is not conceptual, it is quality of execution**, and that risk is real. A half-built demo is worse than no demo. This should be prototyped hero-only and killed early if it doesn't feel right within the first iteration.
- **The Care Pulse placement is still an open judgement call.** Direction A puts it first (07:40, chronologically honest); C puts it near the end (character note after the case is made). C's placement is the one that directly fixes "disproportionately philosophical." Worth deciding explicitly.

---

# 6. Copy — what stays, what must change

**Stays verbatim:** `hero.title`, `hero.subtitle`, all four `value_pillars`, the entire `activation_arc`, all six `bento` items including the community quote, all three `steps`, `cta.band_title` / `band_subtitle`, `brand.tagline` («Расписание, которое не тает»), and every `CARE_PULSE_*` / digest / notification string used on the page.

**Must change, with reasons:**

| Current | Problem | Proposed |
|---|---|---|
| `brand.name`: «Ice Pro» | Contradicts the confirmed brand (Q-001 / B-3) | «Glide» — pending the Ice Pro / Glide decision |
| `brand.eyebrow`: «Ice Pro · solo-тренеры · Беларусь» | «solo-» is an anglicism | «Glide · тренерам на льду · Беларусь» |
| — (new, required by C) | The demo needs orientation labels | «Вы — клиент» / «Тренер видит это в Telegram» |
| — (new, required by C) | The demo needs an invitation | «Выберите время — как это сделал бы ваш ученик.» |
| Care Pulse section framing | Previous version was over-written and philosophical | Heading «Пишем, только когда есть что сказать» + the real `CARE_PULSE_TRAINER_QUIET` message verbatim. Nothing else. |
| «Одно сообщение…» block | Not a convincing marketing message | **Cut entirely.** No replacement. |

Every proposed line above is deliberately functional rather than lyrical, and reuses the product's own register — «на месте», «ничего не потеряется», «писать тебе в личку не нужно». No new capability and no new claim is introduced anywhere.

---

# 7. What is needed before a prototype

1. **Decision: Ice Pro or Glide** (Q-001 / B-3) — blocks all copy.
2. **Decision: authoritative teal token** (B-2) — `#45B9BB` recommended for brand, `#34C6C4` retained inside product screens.
3. **Asset: transparent SVG logo from the designer** (B-1) — currently blocked; no transparent asset exists in the repo.
4. **Decision: direction** — C recommended, A as fallback, B rejected.
5. **Decision: Care Pulse placement** — early (chronological) or late (closing character note).
6. **Scope for the first prototype if C is chosen:** hero only — the interactive booking demo plus its idle auto-play, desktop and mobile. That single artifact answers the only question that matters about this direction, and it is cheap to abandon if the answer is no.

---

**Status:** DRAFT — awaiting direction decision. No code changed, no prototype built.
