# Client Mini App — visual constitution

Companion to trainer CRM mini-app rules. Applies to **client-facing** Telegram Mini Apps under `/webapp/client-*` and `/webapp/catalog`.

## Source of truth

| Layer | File |
|---|---|
| Tokens | [`static/webapp/theme.css`](../static/webapp/theme.css) |
| Shared components | [`static/webapp/mini-app-components.css`](../static/webapp/mini-app-components.css) |
| App shell (tabs, empty, skeleton) | [`static/webapp/mini-app-client-shell.css`](../static/webapp/mini-app-client-shell.css) |
| Shell behaviour | [`static/webapp/mini-app-client-shell.js`](../static/webapp/mini-app-client-shell.js) |

Do not add arbitrary `#hex` on body/cards; use `var(--tg-theme-*)` and `var(--app-*)`.

## Screen tiers

### Tier A — tab bar + shell

Primary client journey. Must include:

```html
<body data-client-shell="tabs">
<link rel="stylesheet" href="mini-app-client-shell.css?v=…" />
<script src="mini-app-client-shell.js?v=…"></script>
```

| Screen | Route |
|---|---|
| Hub | `/webapp/client-home` |
| Catalog | `/webapp/catalog` |
| Bookings | `/webapp/client-bookings` |
| Requests | `/webapp/client-requests` |

### Tier B — secondary (via «Ещё» sheet or hub grid)

`client-saved-trainers`, `client-stats`, `client-passes-certificates`, `client-family-access`, etc. Shell optional; keep `theme.css` + header back/home as today.

### Out of shell

`client-register`, `book.html` — onboarding / legacy deep links.

## Bottom tab bar

Four tabs: **Главная** | **Тренеры** | **Записи** | **Ещё**.

- **Hide** tab bar on drill-down: catalog flow past summary, booking detail, request detail/edit.
- Use `ClientShell.setTabBarVisible(false)` when leaving list/summary roots.
- **Do not** show header «Главная» on Tier A when tab bar is visible (CSS in shell).

## Header

Use `.client-app-header` + `.client-app-header__title` for page title.

Keep `.client-mini-nav` with **«Назад»** only on drill-down screens.

## Loading & empty states

- Loading lists: `ClientShell.renderSkeletonList(el, count)` or page-specific skeleton (catalog trainer list).
- Empty lists: `ClientShell.renderEmptyState(el, { title, hint, ctaLabel, ctaPath })` — one primary CTA.
- Avoid bare «Загрузка...» on Tier A.

## Navigation

- Cross-page: `ClientShell.navigate('catalog?tab=catalog')` (preserves `init_data`, optional view transition).
- Legacy: `navigateClientHome()` still works (delegates to shell).

## Micro-interactions

- Tab tap / sheet item: `ClientShell.hapticSelection()`
- Booking success: `ClientShell.hapticSuccess()`
- Telegram chrome: `client-mini-app-theme.js` + `setHeaderColor` / `setBackgroundColor` on hub

## Booking motion contract

Shared module: [`booking-client.js`](../static/webapp/booking-client.js) + [`booking-client.css`](../static/webapp/booking-client.css).

| Moment | Rule |
|--------|------|
| List / form mount | `.booking-mount` → `.booking-mount--visible` fade (~220ms); no layout shift |
| Form loading | `.booking-form-skeleton` min ~280ms visible before swap to fields |
| Success | Full-screen `.booking-screen-state--success`; `scrollTo(0,0)`; hide form with state class (never fight `!important` deeplink locks inline) |
| Slot pick → form | Catalog: `activateCatalogBookingDeepLinkShell`; book: `book-slot-deeplink` until success |
| Trainer card CTA | Sticky `.catalog-trainer-sticky-cta` above tab bar when slots exist |

### Haptic matrix

| Action | Feedback |
|--------|----------|
| Tab / chip tap | `ClientShell.hapticSelection()` |
| Slot selected | `ClientShell.hapticSelection()` |
| Submit tap | none (avoid double) |
| Booking success | `ClientShell.hapticSuccess()` or `Telegram.WebApp.HapticFeedback.notificationOccurred('success')` |
| Error alert | none |

### Success screen (both hosts)

- Primary copy: «Вы записаны» + trainer confirmation hint
- Secondary: venue mismatch note when slot/API returns `place_mismatch` (before confirm)
- CTAs: «Мои записи» (bookings tab) + «Главная» / return origin via `BookingClient.resolveBookingReturn(from)`
- book.html: tab bar appears **only on success** (`data-client-shell="tabs"`, forced tab «Записи»)

## Pre-merge checklist

- [ ] Tier A page has `data-client-shell="tabs"` and shell assets with bumped `?v=`
- [ ] Tab bar hidden on detail / booking / catalog drill-down
- [ ] No duplicate «Главная» in header when tabs visible
- [ ] `theme.css` tokens only (no new body background hex)
- [ ] Dark mode checked in Telegram
- [ ] `app.py` routes added if new split CSS/JS files
