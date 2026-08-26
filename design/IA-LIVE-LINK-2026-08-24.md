# Glide Landing — «Живая ссылка»
## Information architecture & interaction concept — first viewport + sections 2–4

**Date:** 2026-08-24
**Direction:** C — «Живая ссылка», on Direction A's visual/material system
**Status:** DRAFT — for approval. Nothing built, no code changed.
**Supersedes:** DEC-009 / DEC-010 («The Infinite Edge») — retired, not iterated on.

---

## 0. Governing rules for this direction

1. **The product is the impressive thing.** No treatment on this page may be more interesting than the screen it contains.
2. **Paper is the ground.** `--glide-paper #FBFAF7` canvas, `#FFFFFF` cards, `--glide-line #ECEBE6` hairlines, `--glide-text #16292A` ink. No black stage. No large teal plane. Teal appears only where the product itself puts teal — live, active, confirmed.
3. **All motion is product state change.** If an animation does not correspond to something the real product actually does, it does not ship.
4. **No loop, ribbon, arc or infinity-shaped device anywhere on the page.** The Glide mark is itself a bold angular infinity (verified — see §6). Any secondary curved/looping graphic reads as a stray fragment of the logo. This is the precise lesson of Infinite Edge, stated as a rule.
5. **No invented claims.** Copy comes from `ice.by.json` and `messages.py`. New strings only where the interaction physically requires a label, listed in §7.
6. **The demo must be honestly marked.** A live-looking booking flow that isn't real is a credibility risk, not an asset. See §1.6.

---

## 1. First viewport — the working booking loop

### 1.1 What the visitor sees

A pure-white header band (~72px), then paper ground. Three vertical zones, read left to right, which is also the product's causal order: *what it is → what you do → what happens.*

```
┌──────────────────────────────────────────────────────────────────────┐
│  [Glide lockup]                          [Начать в Telegram]         │  ← white band
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Glide · тренерам      ┌─ Вы — клиент ──┐   ┌─ Тренер — в Telegram ┐ │
│  на льду · Беларусь    │ [демо]         │   │                      │ │
│                        │                │   │                      │ │
│  CRM для тренера       │ СРЕДА, 18 ИЮНЯ │   │  (at rest)           │ │
│  на льду               │                │   │                      │ │
│                        │ 16:00–17:00 ▸  │   │  Ближайшие занятия   │ │
│  Telegram вместо       │ Minsk Arena    │   │  ─────────────       │ │
│  отдельного CRM…       │                │   │  16:00  Максим       │ │
│                        │ 18:00–19:00 ▸  │   │  19:00  Дарья        │ │
│  [Начать в Telegram]   │ Minsk Arena    │   │                      │ │
│                        │                │   │                      │ │
│  Выберите время —      │ 19:00–20:00 ▸  │   │                      │ │
│  как это сделал бы     │ Minsk Arena    │   │                      │ │
│  ваш ученик.           │                │   │                      │ │
│                        └────────────────┘   └──────────────────────┘ │
│   ●○○○○                                                              │
└──────────────────────────────────────────────────────────────────────┘
```

Zone widths at 1440px: copy ≈ 38%, client surface ≈ 30%, trainer surface ≈ 32%. Both product surfaces render at true device width (~360px) inside their columns — never shrunk, never tilted, never in a phone bezel, never glowing. They are white cards with a hairline border and a very shallow shadow, cropped hard at the bottom edge like a page, not faded out.

The five dots at lower-left are the loop's beat indicator — the only piece of non-product chrome in the viewport.

### 1.2 What is interactive

**Exactly two taps.** This is a hard constraint: a third tap turns the hero into a product tour and destroys its edge.

| # | Element | Real component |
|---|---|---|
| 1 | A free slot card | `book.html` `.slot-card` — real hover (`border-color` → accent, `translateY(-1px)`) and `:active` (`scale(0.98)`) states already exist in the file |
| 2 | «Подтвердить» | `trainer-home-main.js` `.hub-action-inbox__btn--primary` |

Everything else in the viewport is inert. The visitor cannot break it, cannot get lost, cannot reach a dead end.

### 1.3 The loop, beat by beat — all copy verbatim from the product

This is the actual chain the product runs today. Nothing here is written for the landing.

**Beat 0 — At rest.**
Client surface shows the real slot list: `.day-title` «СРЕДА, 18 ИЮНЯ», three `.slot-card` rows with `.slot-time` «18:00–19:00» and `.slot-venue-pill` «Minsk Arena». Trainer surface shows the hub at rest — «Ближайшие занятия», week pulse, no «Сейчас важно» card.
→ *Establishes: this is a real trainer's schedule, and it is publicly bookable.*

**Beat 1 — The client picks.** *(visitor's tap #1)*
The slot card fires its real interaction states. The client surface resolves to the real success state:

> ✅ **Вы записаны**.
> Ожидайте подтверждения от тренера в боте.

`booking-client.js:217`, `book.html:2053` — verbatim.
→ *No call. No «когда можно?». No trainer involved yet.*

**Beat 2 — The trainer receives.**
Two things happen at once on the trainer side. A real Telegram bot message:

> 🔔 **Новая запись** — нужно ваше решение
> 👤 **ФИО:** Анна К.
> 📅 **18 июня (ср) 18:00** — 60 мин.
> 🎯 Фигурное катание
> 📍 Минск · 🏟 Minsk Arena
> **Действия:** подтвердите, отклоните или напишите клиенту — кнопки ниже.
> *Слот занят; клиент получит напоминания автоматически.*

`messages.py:2815` `TRAINER_BOOKING_NOTIFICATION` — verbatim.

And in the hub, the «Сейчас важно» card appears:

> **1 запись ждёт подтверждения**
> До подтверждения клиент не увидит занятие как согласованное
> `[Подтвердить]`

`trainer-home-main.js:2354-2364` — verbatim.

→ *This single beat carries the whole administrative argument, in the product's own words: the slot is **already** blocked and reminders are **already** automatic, before the trainer has done anything.* That italic line is the most valuable sentence on the page and we did not write it.

**Beat 3 — One tap.** *(visitor's tap #2)*
«Подтвердить». The inbox card empties.

**Beat 4 — Both sides settle.**
Client surface: «✅ **Ваша запись подтверждена!**» (`messages.py:1119`).
Trainer surface, simultaneously: the 18:00 schedule row flips «Свободно» → «Анна»; the Wednesday load bar in the week pulse thickens one notch; «Ближайшие занятия» gains a row.
→ *One tap updated four places. The trainer did not type anything.*

**Beat 5 — Later, on its own.**
A small time marker — «накануне» — then:

> ⏰ **Напоминание о занятии**
> 📅 **18 июня** (ср) · 18:00
> ⏱ Длительность: 60 мин.

`messages.py:1372` `CLIENT_REMINDER_24H` — verbatim.

The surfaces return to rest.
→ *The work continues after the trainer stops looking. This is the beat that earns the word «автопилот» without our having to use it.*

Total: ~7 seconds on autoplay, or self-paced with two taps.

### 1.4 Idle autoplay — not optional

After ~4 seconds without input, the loop runs itself once, slowly (≈1.4s per beat), then rests in the completed state with a «Показать ещё раз» control. A visitor who never touches anything still receives the entire argument. Autoplay stops permanently the moment the visitor interacts, and never restarts on its own.

### 1.5 Mobile

The split does **not** stack. It re-forms into something more truthful than the desktop version — because in reality these two people are never looking at one screen.

- Full-width: eyebrow, H1, subtitle, CTA, invitation line.
- Below it, the client surface at full viewport width — which is its **native scale**, so it looks correct rather than shrunk.
- The visitor taps a slot. The trainer's side arrives as a **Telegram-style notification sliding down from the top** — «🔔 Новая запись — нужно ваше решение» — which is exactly what a trainer's phone does.
- Tapping the notification flips the surface to the trainer view, where «Подтвердить» sits. Tapping confirm flips back to the client view for the confirmation and, after a beat, the reminder.
- The five beat-dots persist as a thin fixed row so the visitor always knows where they are in the loop.
- The header CTA becomes a sticky bottom bar after the loop completes.

This directly resolves the mobile problem that killed the earlier "Two Rinks" concept (DEC-005): the constraint is answered by being *more* accurate, not by degrading.

**Reduced motion / low-end:** the loop becomes five stacked static frames with their captions, in order. Every beat is a real product state, so each frame is independently legible. Nothing is lost except the timing.

### 1.6 The honesty marker

A small «демо» pill sits in the client surface's corner throughout. Non-negotiable. A booking flow that looks real but isn't is a credibility liability the moment anyone notices — and the entire strategic argument for this direction is credibility. The pill costs nothing and inoculates the page.

The demo trainer is «Алексей · фигурное · Minsk Arena» and the demo client «Анна К.» — both already used as sample data in the existing landing's bento visualisation, so no new persona is invented.

### 1.7 Summary

| | |
|---|---|
| **Capability demonstrated** | Self-serve booking by link; one-tap confirmation; automatic reminders; Telegram-native, no install |
| **Business message** | «Ссылка — вместо переписки "когда можно?"» — proven by doing, not asserted |
| **Questions answered** | What does Glide do? · How does it save time? · How does it reduce admin work? |
| **Real UI** | `book.html` slot list + success state; `TRAINER_BOOKING_NOTIFICATION`; hub `«Сейчас важно»` card; `schedule.html` row; week pulse; `CLIENT_REMINDER_24H` |
| **New copy** | 4 short functional strings (§7) |

### 1.8 What is deliberately *not* in the first viewport, and why

- **The four `value_pillars` as chips.** Cut from the hero. They compete with the demo for the same attention and say what the demo shows. Each pillar is instead *answered* by a section: Telegram + ссылка → hero; Каталог Ice Studio → §2; заметки/слоты/аналитика → §3 and §4. This is a placement change, not a copy change — the strings survive intact elsewhere.
- **Ice photography.** None above the fold. The product surfaces are the imagery.
- **Care Pulse.** Moved late, deliberately. It is the closing character note, not the opening thesis — this is the direct correction to "disproportionately philosophical."
- **Any scroll cue beyond the beat dots.** The loop's completion is the cue.

---

## 2. Section 2 — «Публичная карточка»

**Eyebrow:** «Ice Studio» · **Heading:** «Публичная карточка» — both verbatim `bento.catalog`.

### The question this section exists to answer

The hero proved that a client *who already has your link* can book without bothering you. The immediate objection from a trainer reading this is: *"fine, but I don't have enough clients."* Section 2 exists solely to answer where new ones come from. If it did not answer that, it would be cut.

### What the visitor sees

Two real surfaces on paper, side by side, at device scale.

**Left — the client's view of the catalogue.** Real `catalog.html`: «Найдите тренера», the search parameters row, «Популярное» chips, and a trainer card carrying «Свободные слоты на 14 дней» and «Открыть карточку — запись, заявка, абонементы».

**Right — the trainer's view of demand.** Real `trainer-requests.html`: «Заявки клиентов», the «Для вас» / «В работе» tabs, a request row with «Готов взять» and «Отправить отклик».

Between them, set in the page's own type at body scale, `bento.catalog` verbatim: «Вас находят в каталоге — город, арена, специализация и кнопка записи.» Beneath, the real `bento.stats` figures with `stats_labels` («тренеров в каталоге», «арен подключено», «городов»).

### What is interactive

**One light interaction.** The «Популярное» / city chips on the catalogue surface are tappable; the card list re-filters. That is all. The visitor performs the search a real client performs, and sees the trainer surface appear in the results.

Interaction weight is deliberately much lower than the hero. The page must not become a carnival of demos — see §5.

### Why this is not a feature card

Because the visitor operates the client's search and watches a trainer become findable. The `bento.community` quote — «Сделано людьми из ледового комьюнити — не обезличенный SaaS для букинга салонов.» — sits as the section's closing line, verbatim, in its own quiet measure. It pre-empts the "generic corporate SaaS" objection in the product's own voice, immediately after the section that could most easily read as marketplace-speak.

| | |
|---|---|
| **Capability** | Ice Studio catalogue / discovery; inbound заявки with responses |
| **Business message** | Glide brings clients you did not already have — not just administers the ones you do |
| **Questions answered** | How does it help the trainer get clients? · Why is Glide different from a generic CRM? |
| **Real UI** | `catalog.html`, `trainer-requests.html` |
| **New copy** | None |

---

## 3. Section 3 — «Заметки, цели и история»

**Eyebrow:** «Досье клиента» · **Heading:** «Заметки, цели и история» — both verbatim `bento.notes`.

### The question this section exists to answer

*"I'll still end up keeping a notebook."* This is the objection that decides whether Glide replaces the trainer's existing system or merely sits beside it — which is the difference between adoption and churn.

### What the visitor sees

A master–detail pair, which is the product's own real navigation.

**Left — `trainer-clients.html`:** «Мои клиенты», the real filter chips «Все» / «Постоянные» / «С абонементом» / «В боте», and a list of client rows.

**Right — the dossier for whichever client is selected:** the real profile surface — чипы, «Фигурное · Minsk Arena», the season goal, and the note feed after each session.

`bento.notes` verbatim underneath: «Чипы, профиль с целями сезона и лента заметок после каждого занятия — вместо блокнота и хаоса в чатах.»

### What is interactive

**One interaction, and it is the real one.** Tapping a client in the left list opens their dossier on the right. Nothing else. Two or three clients are populated with genuinely different histories so that switching between them is informative rather than decorative — a long-standing client with a season goal and a dense note feed, and a newer one with two entries.

This is the same master–detail gesture the trainer performs in the actual app, which is the point: the section teaches a real interaction rather than illustrating one.

### Mobile

The list occupies the viewport; tapping a client pushes the dossier in from the right with a back affordance — again, the product's real navigation, not a landing-page approximation.

| | |
|---|---|
| **Capability** | Client profiles, notes, season goals, history |
| **Business message** | Glide replaces the notebook and the chat chaos, rather than adding a fourth place to look |
| **Questions answered** | How does it help the trainer manage clients? |
| **Real UI** | `trainer-clients.html` list + dossier |
| **New copy** | None |

---

## 4. Section 4 — «Аналитика практики»

**Eyebrow:** «Без Excel» · **Heading:** «Аналитика практики» — both verbatim `bento.analytics`.

### The question this section exists to answer

*"Do I actually know how my business is doing?"* — the one thing a solo trainer with a notebook genuinely cannot answer.

### What the visitor sees

**Left — real `trainer-stats.html`:** «Статистика и выручка», the real subtitle «Сводка и бухгалтерия — без лишних вкладок», and the week's figures: 12 записей · 840 BYN · +3 новых.

**Right — the weekly digest as it actually arrives**, rendered as a real Telegram message, closing with its real recommendation line: «👉 Неделя собрана. Воскресенье — твоё.» (`messages.py:569`).

`bento.analytics` verbatim between them: «Записи, выручка и новые клиенты — сводка за неделю в одном экране.»

### What is interactive

**Nothing.** This is deliberate, and it is a design decision rather than an omission.

By section 4 the interaction budget is spent. The page needs to come to rest before the closing beats, and a still, confident data screen is the correct rhythm — it reads as a summary rather than another thing to poke. It also demonstrates something the earlier sections cannot: that Glide produces a result **without the trainer doing anything at all.** Making this section interactive would contradict its own message.

The pairing carries the argument on its own: the numbers exist in the app *and* they come to you on Sunday. Together they say the product works while the trainer is on the ice — which is the exact claim `activation_arc.grow` makes in the existing copy («Новые клиенты из каталога Ice Studio — пока вы на льду»).

| | |
|---|---|
| **Capability** | Weekly analytics — bookings, revenue, new clients; automatic weekly digest |
| **Business message** | You can see the business without keeping the books yourself |
| **Questions answered** | How does it give the trainer visibility into the business? · How does it save time? |
| **Real UI** | `trainer-stats.html`; weekly digest message |
| **New copy** | None |

---

## 5. Interaction rhythm across the page

Stated explicitly, because it is the thing most likely to be lost in execution:

| Section | Interaction weight | Why |
|---|---|---|
| Hero | **Heavy** — 2 taps, full loop | This is the argument. It earns everything after it. |
| §2 Каталог | **Light** — filter chips | Enough to make the visitor a participant, not enough to compete |
| §3 Досье | **Light** — pick a client | One real gesture, genuinely informative |
| §4 Аналитика | **Still** | The page comes to rest; the message *is* "you did nothing" |

A landing page where every section demands interaction is exhausting and reads as a demo reel. The descending curve is what makes the hero feel important.

---

## 6. Logo — resolved

The brief's constraint is satisfiable without inventing anything.

**Verified:** all 21 assets in `static/logos/` are JPEG-encoded rasters with `hasAlpha: no`. There is no transparent asset. But `02-horizontal-full/glide-horizontal-teal-icon-black-text-on-white.png` (1024×558) is a lockup **on white** — teal angular infinity mark, black GLIDE wordmark, «DIGITAL SKATING ECOSYSTEM» in a rule-separated block. It is exactly what `static/logos/README.md` recommends for light/landing use.

**Resolution:** the header band is **pure `#FFFFFF`**, not paper — and the on-white asset sits on it directly. No compositing, no blend mode, no invented treatment, no black-ground asset on a coloured field. Trimming the asset's generous padding to its bounding box is a crop, not a recreation of the mark.

Two conditions:
1. Verify the asset's ground is true `#FFFFFF`; if it is off-white, the header band matches the asset rather than the reverse.
2. The white header band must read as an intentional element of the composition — a masthead rule above the paper page — not as a stray white rectangle.

If neither condition can be met cleanly, the fallback is the brief's own: **leave the area neutral.** The header carries the CTA alone and the logo waits for an SVG from the designer. That is a better outcome than a compromised mark.

**Standing rule (repeat of §0.4):** because the mark is a bold angular infinity, no looping, ribboned or arc-shaped graphic device may appear anywhere else on the page.

---

## 7. New copy — the complete list

Four strings, all functional labels. Everything else on these four sections is verbatim from `ice.by.json` and `messages.py`.

| String | Where | Why it cannot be avoided |
|---|---|---|
| «Вы — клиент» | Client surface label | The visitor must know whose screen they are looking at |
| «Тренер — в Telegram» | Trainer surface label | Same |
| «Демо» | Honesty pill | §1.6 |
| «Показать ещё раз» | Replay control after autoplay | §1.4 |

Plus **one** line of actual copy, the invitation under the hero CTA:

> «Выберите время — как это сделал бы ваш ученик.»

It uses the product's own register («ученик» appears in `activation_arc.link`: «Кидаете в чат родителю или ученику»), makes no claim, and is the single sentence that turns a static hero into a working one. If it is judged unnecessary, the demo still functions via autoplay.

**One required copy correction, unchanged from the prior document:** `brand.eyebrow` currently reads «Ice Pro · solo-тренеры · Беларусь». «solo-» is an anglicism and «Ice Pro» contradicts the brand. Proposed: «Glide · тренерам на льду · Беларусь» — pending the decision below.

---

## 8. Below section 4 — not in scope for this pass

Sequenced for completeness, to be specified after these four are approved: **Care Pulse** (eyebrow «Пишем, только когда есть что сказать», the real `CARE_PULSE_TRAINER_QUIET` message verbatim, two lines of frame, nothing more) → **«Три шага до первой записи»** (existing `steps`, unchanged) → **CTA band** (existing `cta` copy) → footer.

---

## 9. Open decisions — blocking

1. **Ice Pro or Glide** (Q-001). `ice.by.json` still says «Ice Pro»; the logo README says Glide. Blocks all copy.
2. **Authoritative teal.** `#34C6C4` (theme.css, shipping, greenest), `#47B6B9` (logos README), `#45B9BB` (DEC-006). Recommendation unchanged: `#45B9BB` as the brand teal, `#34C6C4` retained *inside* product surfaces so they stay UI-accurate, neither on a large plane.
3. **Typography.** Recommendation: use the product's own `--app-font-sans` (DM Sans) for the entire page and get editorial quality from scale, tracking and rhythm rather than a second typeface. This is the choice that most directly serves "should feel like a real Glide product," and it removes the Playfair Display problem entirely. The alternative — one display face for the H1 only — is available if DM Sans proves too soft at large display sizes. Either way, Playfair is dropped.
4. **Demo persona.** «Алексей · фигурное · Minsk Arena» / «Анна К.» — reused from existing landing sample data. Confirm acceptable.

---

## 10. Proposed first build, when approved

**The hero only** — the full five-beat loop with its two taps and idle autoplay, at desktop and mobile.

That single artifact answers the only question that matters about this direction: *does a working slice of the product, sitting on a landing page, feel impressive?* If the answer is no, we find out in one iteration and nothing else has been built on top of it. Sections 2–4 are structurally simpler and carry far less risk; they should not be built until the hero has proven itself.

---

**Status:** DRAFT — awaiting approval. No implementation started.
