    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        if (typeof tg.ready === 'function') tg.ready();
        if (typeof tg.expand === 'function') tg.expand();
        if (typeof window.__applyClientHubTheme === 'function') window.__applyClientHubTheme();
        try {
          var darkUi = document.documentElement.classList.contains('hub-is-dark');
          var bgHex = darkUi ? '#1c1c1c' : '#fffbec';
          if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
          if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
        } catch (e) {}
      }
      var initData = tg && tg.initData ? tg.initData : '';

      /** Max upcoming bookings shown below the hero card. */
      var HUB_UPCOMING_MAX = 5;

      /* ── SVG icon library ─────────────────────────────────────────── */
      var ICONS = {
        search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>',
        cal:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
        inbox:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
        ticket: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2M13 11v2M13 17v2"/></svg>',
        user:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
        msg:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>',
        share:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>',
        pin:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>',
        bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m19 21-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/></svg>',
        repeat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
        plus:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
        chart:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-6"/><path d="M22 20V14"/></svg>',
      };

      /** Explore tiles removed — secondary nav lives in bottom tab «Ещё». */

      /* ── State ──────────────────────────────────────────────────────── */
      /** selected_trainer_id from catalog/bot session */
      var selectedTrainerId = null;
      /** From hub bootstrap — service aligned with primary-trainer tier (booking / save / session). */
      var primaryCatalogServiceId = null;
      /** Authoritative last booking (by slot start) from bootstrap — «Записаться снова» must not depend on catalog session. */
      var lastBookingTrainerId = null;
      var lastBookingServiceId = null;
      /** Up to 3 trainers with recent bookings each — multi «Снова к …» pills (bootstrap). */
      var rebookTargets = [];
      /** Primary trainer accepts online booking — drives sticky «Записаться» FAB. */
      var hubPrimaryTrainerCanBook = false;
      /** Nearest upcoming booking on hub — rebook strip replaces bottom FAB. */
      var hubHasUpcomingBooking = false;
      var clientHubBookFabWired = false;

      /* ── Utils ─────────────────────────────────────────────────────── */
      function headersJson() {
        var h = { 'Content-Type': 'application/json' };
        if (initData) h['X-Telegram-Init-Data'] = initData;
        return h;
      }

      function apiUrl(path) {
        var url = '/api/webapp' + path;
        if (initData) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
        return url;
      }

      function webappBasePath() {
        var p = window.location.pathname || '';
        return p.replace(/[^/]+$/, '') || '/webapp/';
      }

      function withInit(url) {
        if (!initData) return url;
        return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(initData);
      }

      function navigateTo(pathWithQuery) {
        if (window.ClientShell && typeof window.ClientShell.navigate === 'function') {
          window.ClientShell.navigate(pathWithQuery);
          return;
        }
        window.location.href = withInit(webappBasePath() + pathWithQuery);
      }

      function esc(s) {
        if (s == null) return '';
        return String(s)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      function pluralWeeksHub(n) {
        n = Number(n) || 0;
        var abs100 = n % 100;
        var abs10 = n % 10;
        if (abs100 >= 11 && abs100 <= 14) return 'недель';
        if (abs10 === 1) return 'неделя';
        if (abs10 >= 2 && abs10 <= 4) return 'недели';
        return 'недель';
      }

      /** Duolingo-style streak line on hub; tap opens full «Ваша активность». */
      function renderStreakRibbon(activity) {
        var el = document.getElementById('hubStreakRibbon');
        if (!el) return;
        var sw = activity && activity.streak_weeks != null ? Number(activity.streak_weeks) : 0;
        if (sw < 1) {
          el.style.display = 'none';
          el.innerHTML = '';
          el.onclick = null;
          return;
        }
        var line =
          sw === 1
            ? '🔥 Вы на льду уже неделю — так держать!'
            : '🔥 Вы супер! Уже ' + sw + ' ' + pluralWeeksHub(sw) + ' на льду подряд!';
        el.style.display = 'flex';
        el.innerHTML =
          '<span>' +
          esc(line) +
          '</span><span class="hub-streak-ribbon__cta">Вся активность</span>';
        el.onclick = function () {
          navigateTo('client-stats');
        };
      }

      /** PRD E1 parity with trainer hub: server sets hub_in_session inside [start, end) in Minsk wall time. */
      function hubSessionNowPillHtml(b) {
        if (!b || !b.hub_in_session) return '';
        return (
          '<span class="hub-session-now-pill" role="status" aria-label="Текущее занятие">сейчас</span>'
        );
      }

      function initials(name) {
        if (!name) return '?';
        var parts = String(name).trim().split(/\s+/);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        return parts[0].slice(0, 2).toUpperCase();
      }

      function trainerHubThumb(fileKey) {
        if (!fileKey) return '';
        return '/api/public/photos/' + encodeURIComponent(fileKey);
      }

      function parseDateTime(dateStr, timeStr) {
        var d = (dateStr || '').slice(0, 10).split('-');
        var t = (timeStr || '00:00').slice(0, 5).split(':');
        if (d.length !== 3) return new Date(0);
        return new Date(
          parseInt(d[0], 10), parseInt(d[1], 10) - 1, parseInt(d[2], 10),
          parseInt(t[0], 10) || 0, parseInt(t[1], 10) || 0
        );
      }

      /** Flatten grouped days → sorted flat list. */
      function flattenBookings(days) {
        var out = [];
        (days || []).forEach(function(day) {
          (day.bookings || []).forEach(function(b) {
            out.push({ b: b, day: day, start: parseDateTime(day.date, b.start_time) });
          });
        });
        out.sort(function(a, b) { return a.start - b.start; });
        return out;
      }

      /** Find the next upcoming booking across all days. */
      function findNextBooking(days) {
        var now = new Date();
        var flat = flattenBookings(days);
        for (var i = 0; i < flat.length; i++) {
          if (flat[i].start >= now) return flat[i];
        }
        return flat.length ? flat[0] : null;
      }

      /** Human-readable relative date: 'Сегодня', 'Завтра', or 'DD.MM (день)'. */
      function relativeDate(dateStr, dayLabel) {
        var now = new Date();
        var todayStr = now.getFullYear() + '-' +
          String(now.getMonth() + 1).padStart(2, '0') + '-' +
          String(now.getDate()).padStart(2, '0');
        var tomorrow = new Date(now);
        tomorrow.setDate(tomorrow.getDate() + 1);
        var tomorrowStr = tomorrow.getFullYear() + '-' +
          String(tomorrow.getMonth() + 1).padStart(2, '0') + '-' +
          String(tomorrow.getDate()).padStart(2, '0');

        var d = (dateStr || '').slice(0, 10);
        if (d === todayStr) return 'Сегодня';
        if (d === tomorrowStr) return 'Завтра';
        var parts = d.split('-');
        var base = parts.length === 3 ? parts[2] + '.' + parts[1] : d;
        return dayLabel ? base + ' (' + dayLabel + ')' : base;
      }

      function canWriteTrainer(b) {
        var tid = b.trainer_telegram_id;
        var un = (b.trainer_telegram_username || '').replace(/^@/, '').trim();
        return (tid != null && tid !== '') || !!un;
      }

      function openTelegramDm(username, telegramId, trainerId) {
        if (typeof window.openTelegramChatFromMiniApp === 'function') {
          if (window.openTelegramChatFromMiniApp({ username: username, telegramId: telegramId })) {
            return true;
          }
        }
        var un = String(username || '').replace(/^@/, '').trim();
        if (trainerId != null && String(trainerId).trim() !== '' && un) {
          var path = '/r/tg/' + encodeURIComponent(String(trainerId)) + '?src=client_app';
          var url = (window.location.origin || '') + path;
          if (tg && typeof tg.openLink === 'function') {
            try {
              tg.openLink(url, { try_instant_view: false });
              return true;
            } catch (e1) {
              try {
                tg.openLink(url);
                return true;
              } catch (e2) { /* fall through */ }
            }
          }
        }
        return false;
      }

      /* ── Error / status ─────────────────────────────────────────────── */
      function setStateMessage(text, kind) {
        var el = document.getElementById('stateMessage');
        if (!text) { el.style.display = 'none'; el.textContent = ''; return; }
        el.textContent = text;
        el.className = 'state-panel ' + (kind === 'error' ? 'error' : 'loading');
        el.style.display = 'block';
      }

      /* ── Hero text ──────────────────────────────────────────────────── */
      function getTelegramFirstName() {
        var w = window.Telegram && window.Telegram.WebApp;
        var u = w && w.initDataUnsafe && w.initDataUnsafe.user;
        if (!u || u.first_name == null) return null;
        var name = String(u.first_name).trim();
        return name || null;
      }

      function defaultHubGreeting() {
        var name = getTelegramFirstName();
        return name ? 'Рады видеть вас, ' + name : 'Рады вас видеть';
      }

      function setHubGreeting(text) {
        var el = document.getElementById('hubGreeting');
        if (el) el.textContent = text;
      }

      function setHeroLayout(mode) {
        var hero = document.getElementById('hubHero');
        if (hero) hero.classList.toggle('hub-hero--booking-led', mode === 'booking-led');
        document.body.classList.toggle('hub-body--booking-led', mode === 'booking-led');
      }

      function resetHubHeroLayout() {
        setHeroLayout('full');
        setHubGreeting(defaultHubGreeting());
        var t = document.getElementById('hubHeroTitle');
        if (t) t.hidden = false;
      }

      /** Upcoming booking: greeting is the headline; the amber card holds the facts. */
      function configureHeroForUpcomingBooking() {
        setHubGreeting(defaultHubGreeting());
        setHeroText(null, null);
        setHeroLayout('booking-led');
      }

      function setHeroText(title, sub) {
        var t = document.getElementById('hubHeroTitle');
        var s = document.getElementById('hubHeroSub');
        if (t) {
          if (title == null || title === '') {
            t.textContent = '';
            t.hidden = true;
          } else {
            t.textContent = title;
            t.hidden = false;
          }
        }
        if (s) {
          if (sub != null) { s.textContent = sub; s.style.display = ''; }
          else { s.style.display = 'none'; }
        }
      }

      /* ── Next booking hero card ─────────────────────────────────────── */

      /**
       * Renders the amber hero card for the nearest upcoming booking.
       * This is the primary content for Scenario 3.
       */
      function renderNextBookingCard(item) {
        var b = item.b;
        var day = item.day;
        var st = String(b.status || '').toLowerCase();
        var isPending = st === 'pending';
        var statusLabel = isPending ? 'Ожидает подтверждения ⏳' : 'Подтверждено ✅';
        var statusClass = isPending ? 'hub-next-card-status-line--pending' : 'hub-next-card-status-line--confirmed';
        var time = (b.start_time || '').slice(0, 5);
        var dateLabel = relativeDate(day.date, day.day_label);
        var trainerName = b.trainer_name || 'Тренер';
        var place = ((b.arena_name || b.place_display || '') + '').trim();
        var dur = b.duration_minutes || 45;

        var placeHtml = place
          ? '<div class="hub-next-card-place-line">' + ICONS.pin + '<span>' + esc(place) + '</span></div>'
          : '';

        var toolbarParts = [];
        if (canWriteTrainer(b)) {
          toolbarParts.push(
            '<button type="button" class="hub-next-card-tool" data-hub-dm="next"' +
            ' data-dm-un="' + esc((b.trainer_telegram_username || '').replace(/^@/, '')) + '"' +
            ' data-dm-tid="' + esc(b.trainer_telegram_id != null ? String(b.trainer_telegram_id) : '') + '">' +
            ICONS.msg + '<span>Написать</span></button>'
          );
        }
        if (b.trainer_id != null && String(b.trainer_id).trim() !== '') {
          toolbarParts.push(
            '<button type="button" class="hub-next-card-tool" data-hub-action="share-trainer"' +
            ' data-share-tid="' + esc(String(b.trainer_id)) + '"' +
            ' data-share-context="next_booking">' +
            ICONS.share + '<span>Поделиться</span></button>'
          );
        }
        var toolbarHtml = toolbarParts.length
          ? '<div class="hub-next-card-toolbar" role="group" aria-label="Действия с записью">' +
            toolbarParts.join('') +
            '</div>'
          : '';

        var cardMod = isPending ? 'hub-next-card--pending' : 'hub-next-card--confirmed';
        var html =
          '<div class="hub-next-card ' + cardMod + '" id="nextCard" data-bid="' + esc(String(b.id)) + '" tabindex="0" role="button"' +
          ' aria-label="Ближайшая запись, ' + esc(dateLabel) + ' в ' + esc(time) + '">' +
            '<span class="hub-next-card-go" aria-hidden="true">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M9 6l6 6-6 6"/></svg>' +
            '</span>' +
            '<div class="hub-next-card-inner">' +
              '<div class="hub-next-card-kicker">' +
                '<span class="hub-next-card-status-line ' + statusClass + '">' +
                  '<span class="hub-next-card-status-dot" aria-hidden="true"></span>' +
                  esc(statusLabel) +
                '</span>' +
              '</div>' +
              '<div class="hub-next-card-time-row">' +
                '<div class="hub-next-card-time">' + esc(time) + '</div>' +
                hubSessionNowPillHtml(b) +
              '</div>' +
              '<div class="hub-next-card-date">' + esc(dateLabel) + ' · ' + esc(String(dur)) + ' мин</div>' +
              '<div class="hub-next-card-who">' +
                '<div class="hub-next-card-trainer-avatar" aria-hidden="true">' + esc(initials(trainerName)) + '</div>' +
                '<div class="hub-next-card-who-text">' +
                  '<div class="hub-next-card-trainer-name">' + esc(trainerName) + '</div>' +
                  placeHtml +
                '</div>' +
              '</div>' +
              toolbarHtml +
            '</div>' +
          '</div>';

        var block = document.getElementById('nextBookingBlock');
        block.innerHTML = html;

        /* Wire interactions */
        var card = document.getElementById('nextCard');
        if (!card) return;
        card.addEventListener('click', function(ev) {
          var dmBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-dm="next"]');
          if (dmBtn) {
            ev.stopPropagation();
            if (window.ClientShell && typeof window.ClientShell.hapticSelection === 'function') {
              window.ClientShell.hapticSelection();
            }
            openTelegramDm(dmBtn.getAttribute('data-dm-un'), dmBtn.getAttribute('data-dm-tid'), b.trainer_id);
            return;
          }
          var shareNext = ev.target && ev.target.closest && ev.target.closest('[data-hub-action="share-trainer"]');
          if (shareNext) {
            ev.stopPropagation();
            if (window.ClientShell && typeof window.ClientShell.hapticSelection === 'function') {
              window.ClientShell.hapticSelection();
            }
            shareTrainer(
              shareNext.getAttribute('data-share-tid'),
              shareNext.getAttribute('data-share-context') || 'next_booking'
            );
            return;
          }
          var bid = card.getAttribute('data-bid');
          if (bid) navigateTo('client-bookings?open_booking=' + encodeURIComponent(bid) + '&from=hub');
        });
      }

      function catalogPrimaryServiceQuery() {
        if (primaryCatalogServiceId == null || primaryCatalogServiceId === '') return '';
        var n = Number(primaryCatalogServiceId);
        if (!isFinite(n) || n <= 0) return '';
        return '&service_id=' + encodeURIComponent(String(n));
      }

      /** Hub → booking: slot chip → catalog form; repeat book → catalog slot pick (action=book). */
      function buildBookPathFromHubContext(trainerId, opts) {
        opts = opts || {};
        var slotRaw = opts.slotId;
        if (slotRaw != null && String(slotRaw).trim() !== '') {
          var parts = ['catalog?trainer_id=' + encodeURIComponent(String(trainerId))];
          parts.push('slot_id=' + encodeURIComponent(String(slotRaw).trim()));
          var svcRaw = opts.serviceId;
          if (svcRaw != null && String(svcRaw).trim() !== '') {
            parts.push('service_id=' + encodeURIComponent(String(svcRaw).trim()));
          } else if (opts.fallbackServiceQuery) {
            parts.push(opts.fallbackServiceQuery.replace(/^&/, ''));
          }
          var arenaRaw = opts.arenaId;
          if (arenaRaw != null && String(arenaRaw).trim() !== '') {
            parts.push('arena_id=' + encodeURIComponent(String(arenaRaw).trim()));
          }
          parts.push('from=hub');
          return parts.join('&');
        }
        var parts = [
          'catalog?trainer_id=' + encodeURIComponent(String(trainerId)),
          'action=book',
          'from=hub',
        ];
        var svcRaw2 = opts.serviceId;
        if (svcRaw2 != null && String(svcRaw2).trim() !== '') {
          parts.push('service_id=' + encodeURIComponent(String(svcRaw2).trim()));
        } else if (opts.fallbackServiceQuery) {
          parts.push(opts.fallbackServiceQuery.replace(/^&/, ''));
        }
        var arenaRaw2 = opts.arenaId;
        if (arenaRaw2 != null && String(arenaRaw2).trim() !== '') {
          parts.push('arena_id=' + encodeURIComponent(String(arenaRaw2).trim()));
        }
        return parts.join('&');
      }

      /** Prefer last booking service with this trainer; else hub primary catalog hint. */
      function hubRepeatBookServiceId(trainerId) {
        var tid = trainerId != null ? Number(trainerId) : NaN;
        if (!isNaN(tid) && tid > 0 && lastBookingTrainerId != null) {
          var lt = Number(lastBookingTrainerId);
          if (!isNaN(lt) && lt === tid && lastBookingServiceId != null) {
            var ls = Number(lastBookingServiceId);
            if (!isNaN(ls) && ls > 0) return ls;
          }
        }
        if (primaryCatalogServiceId == null || primaryCatalogServiceId === '') return null;
        var pn = Number(primaryCatalogServiceId);
        return !isNaN(pn) && pn > 0 ? pn : null;
      }

      /** Hub → book slots (or form) without catalog / trainer-card flash. */
      function navigateToBookAgain(trainerId, serviceId) {
        var svc = serviceId != null && serviceId !== '' ? serviceId : hubRepeatBookServiceId(trainerId);
        navigateTo(buildBookPathFromHubContext(trainerId, {
          serviceId: svc,
          fallbackServiceQuery: catalogPrimaryServiceQuery(),
        }));
      }

      function navigateToPrimaryTrainerBook() {
        if (selectedTrainerId == null || String(selectedTrainerId).trim() === '') return;
        navigateToBookAgain(selectedTrainerId, hubRepeatBookServiceId(selectedTrainerId));
      }

      /** Same path as bottom FAB; fallback when primary trainer cannot book online. */
      function navigateToHubBookLikePrimaryFab(nextBooking) {
        if (hubPrimaryTrainerCanBook && selectedTrainerId != null && String(selectedTrainerId).trim() !== '') {
          navigateToPrimaryTrainerBook();
          return;
        }
        navigateToCatalogBookAgain(nextBooking);
      }

      /** Sticky FAB: primary trainer + online booking; hidden when «Записаться снова» strip is shown. */
      function shouldShowClientHubBookFab() {
        if (!initData) return false;
        if (hubHasUpcomingBooking) return false;
        if (selectedTrainerId == null || String(selectedTrainerId).trim() === '') return false;
        return hubPrimaryTrainerCanBook === true;
      }

      function syncClientHubBookFab() {
        var fab = document.getElementById('hubBookFab');
        if (!fab) return;
        var show = shouldShowClientHubBookFab();
        if (show) fab.removeAttribute('hidden');
        else fab.setAttribute('hidden', '');
        try {
          document.body.classList.toggle('hub-body--book-fab-visible', show);
        } catch (eBody) { /* ignore */ }
        if (clientHubBookFabWired) return;
        clientHubBookFabWired = true;
        fab.addEventListener('click', function() {
          if (window.ClientShell && typeof window.ClientShell.hapticSelection === 'function') {
            window.ClientShell.hapticSelection();
          }
          navigateToPrimaryTrainerBook();
        });
      }

      /**
       * «Записаться снова»: слоты тренера с ближайшей записи, иначе последняя запись (bootstrap),
       * без selected_trainer_id из сессии каталога.
       */
      function navigateToCatalogBookAgain(nextBooking) {
        var nb = nextBooking && nextBooking.b;
        var tid = nb && nb.trainer_id != null ? Number(nb.trainer_id) : NaN;
        if (!isNaN(tid) && tid > 0) {
          var sid = nb.service_id != null ? Number(nb.service_id) : null;
          navigateToBookAgain(tid, sid);
          return;
        }
        var lt = lastBookingTrainerId;
        if (lt != null && lt > 0) {
          navigateToBookAgain(lt, lastBookingServiceId);
          return;
        }
        navigateTo('catalog?tab=catalog');
      }

      /** First word of display name for compact pill label. */
      function trainerFirstNameForPill(displayName) {
        var s = ((displayName || '') + '').trim();
        if (!s) return 'Тренер';
        var parts = s.split(/\s+/);
        return parts[0] || s;
      }

      /** Deep link to book for one rebook row from bootstrap (trainer + last service per trainer). */
      function navigateToRebookTarget(t) {
        var tid = t && t.trainer_id != null ? Number(t.trainer_id) : NaN;
        if (isNaN(tid) || tid <= 0) return;
        var sid = t.service_id != null ? Number(t.service_id) : null;
        navigateToBookAgain(tid, sid);
      }

      /**
       * Order rebook pill targets: when showing upcoming booking, surface matching trainer first.
       * Caps at 3 — further trainers via каталог.
       */
      function orderedRebookPills(nextBooking, targets) {
        var list = (targets || []).filter(function(t) {
          return t && t.trainer_id != null && Number(t.trainer_id) > 0;
        }).map(function(t) { return t; });
        var nb = nextBooking && nextBooking.b;
        var nextTid = nb && nb.trainer_id != null ? Number(nb.trainer_id) : NaN;
        if (!isNaN(nextTid) && nextTid > 0 && list.length >= 2) {
          var idx = -1;
          for (var i = 0; i < list.length; i++) {
            if (Number(list[i].trainer_id) === nextTid) { idx = i; break; }
          }
          if (idx > 0) {
            var copy = list.slice();
            var item = copy.splice(idx, 1)[0];
            copy.unshift(item);
            list = copy;
          }
        }
        return list.slice(0, 3);
      }

      function hideNextBookingSkeleton() {
        var skel = document.getElementById('nextBookingSkel');
        if (skel) skel.remove();
      }

      /** When bootstrap started — used for minimum skeleton display time. */
      var hubLoadStartedAt = Date.now();
      var HUB_SKELETON_MIN_MS = 220;

      /**
       * Drop skeleton only after bootstrap AND scenario-specific async work
       * (primary panel slots, discovery carousel) are done. Idempotent.
       */
      function finishHubInitialLoading() {
        if (document.body.classList.contains('hub-body--revealed')) return;
        var wait = Math.max(0, HUB_SKELETON_MIN_MS - (Date.now() - hubLoadStartedAt));
        setTimeout(function() {
          if (document.body.classList.contains('hub-body--revealed')) return;
          document.body.classList.remove('hub-body--loading');
          document.body.classList.add('hub-body--revealed');
          var skel = document.getElementById('hubInitialSkel');
          if (skel) {
            skel.setAttribute('aria-hidden', 'true');
            skel.removeAttribute('aria-busy');
          }
          syncClientHubBookFab();
        }, wait);
      }

      function clearNextBookingBlock() {
        var block = document.getElementById('nextBookingBlock');
        if (block) block.innerHTML = '';
      }

      /* ── My trainer card ─────────────────────────────────────────────── */

      /**
       * Full recommendation text (opener → имя → услуги → город · арена → CTA → ссылка) — не голый URL.
       */
      function shareTrainer(trainerId, shareCtx) {
        var ctx = shareCtx || 'catalog';
        var path =
          '/client/share-trainer/' +
          encodeURIComponent(String(trainerId)) +
          '?share_context=' +
          encodeURIComponent(ctx);
        fetch(apiUrl(path))
          .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function(data) {
            var shareUrl = (data.share_url || '').trim();
            var shareBody = (data.share_body || '').trim();
            var shareText = (data.share_text || '').trim();
            if (!shareUrl && !shareText) return;
            if (typeof window.openTelegramShareUrlFromMiniApp === 'function') {
              window.openTelegramShareUrlFromMiniApp({
                shareUrl: shareUrl,
                shareBody: shareBody,
                fullMessage: shareText,
              });
              return;
            }
            var href;
            if (shareUrl) {
              href = 'https://t.me/share/url?url=' + encodeURIComponent(shareUrl);
              if (shareBody) href += '&text=' + encodeURIComponent(shareBody);
            } else {
              href = 'https://t.me/share/url?text=' + encodeURIComponent(shareText);
            }
            if (tg && typeof tg.openTelegramLink === 'function') {
              tg.openTelegramLink(href);
            }
          })
          .catch(function() {});
      }

      /**
       * Primary-relationship card: uppercase label «ОСНОВНОЙ», main line — trainer name from hub.
       * Opens catalog deep-linked to this trainer_id so we never reuse stale session.trainer_id from browsing.
       * Share action added: 1-tap trainer recommendation via Telegram native share dialog.
       */
      function renderMyTrainerCard(trainerId, trainerName, trainerUsername, trainerTelegramId, listPhotoKey, canBook) {
        var block = document.getElementById('myTrainerBlock');
        if (!block) return;
        var un = (trainerUsername || '').replace(/^@/, '').trim();
        var tid = trainerTelegramId != null ? String(trainerTelegramId) : '';
        var hasDm = !!(un || tid);
        var displayName = ((trainerName || '').trim()) || 'Тренер';
        var onlineBook = canBook !== false;

        var actionBtns = '';
        if (trainerId != null) {
          actionBtns +=
            '<button type="button" class="hub-trainer-share-btn" data-hub-action="share-trainer"' +
            ' data-share-tid="' + esc(String(trainerId)) + '"' +
            ' data-share-context="my_trainer"' +
            ' aria-label="Поделиться тренером">' + ICONS.share + '</button>';
        }
        var actionsHtml = actionBtns
          ? '<div class="hub-trainer-actions">' + actionBtns + '</div>'
          : '';

        var subText = onlineBook
          ? 'Нажмите, чтобы выбрать время'
          : (hasDm ? 'Онлайн-запись недоступна — напишите тренеру' : 'Открыть профиль в каталоге');

        var contactRowHtml = '';
        if (hasDm) {
          contactRowHtml =
            '<button type="button" class="hub-trainer-contact-btn" data-hub-dm="trainer"' +
            ' data-dm-un="' + esc(un) + '" data-dm-tid="' + esc(tid) + '">' +
            ICONS.msg + '<span>Написать тренеру</span>' +
            '</button>';
        }

        var src = trainerHubThumb(listPhotoKey || '');
        var avatarHtml = src
          ? '<div class="hub-trainer-avatar hub-trainer-avatar--photo"><img src="' + esc(src) + '" alt="" loading="lazy"/></div>'
          : '<div class="hub-trainer-avatar">' + esc(initials(displayName)) + '</div>';

        block.innerHTML =
          '<div class="hub-trainer-card" id="trainerCard">' +
            '<div class="hub-trainer-card-main">' +
              avatarHtml +
              '<div class="hub-trainer-info">' +
                '<div class="hub-trainer-label">Основной</div>' +
                '<div class="hub-trainer-name">' + esc(displayName) + '</div>' +
                '<div class="hub-trainer-sub">' + esc(subText) + '</div>' +
              '</div>' +
              actionsHtml +
            '</div>' +
            contactRowHtml +
          '</div>';
        block.style.display = '';

        var card = document.getElementById('trainerCard');
        if (!card) return;
        card.addEventListener('click', function(ev) {
          var dmBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-dm="trainer"]');
          if (dmBtn) {
            ev.stopPropagation();
            openTelegramDm(dmBtn.getAttribute('data-dm-un'), dmBtn.getAttribute('data-dm-tid'), trainerId);
            return;
          }
          var shareBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-action="share-trainer"]');
          if (shareBtn) {
            ev.stopPropagation();
            shareTrainer(
              shareBtn.getAttribute('data-share-tid'),
              shareBtn.getAttribute('data-share-context') || 'my_trainer'
            );
            return;
          }
          if (!onlineBook && hasDm) {
            openTelegramDm(un, tid, trainerId);
            return;
          }
          navigateTo(
            trainerId != null && String(trainerId).trim() !== ''
              ? 'catalog?trainer_id=' + encodeURIComponent(String(trainerId)) + catalogPrimaryServiceQuery()
              : 'catalog'
          );
        });
      }

      /* ── Hero primary actions + contextual pills (no tab duplicates) ─── */

      function clearHubHeroActions() {
        var el = document.getElementById('hubHeroActions');
        if (!el) return;
        el.innerHTML = '';
        el.setAttribute('hidden', 'hidden');
      }

      function renderNewClientHeroActions() {
        var el = document.getElementById('hubHeroActions');
        if (!el) return;
        var searchIcon = (ICONS.search || '').replace('<svg ', '<svg class="hub-hero-actions__icon" ');
        el.innerHTML =
          '<button type="button" class="btn-block btn-primary hub-hero-actions__primary" id="hubBtnFindTrainer">' +
            searchIcon + 'Найти тренера' +
          '</button>';
        el.removeAttribute('hidden');
        var findBtn = document.getElementById('hubBtnFindTrainer');
        if (findBtn) findBtn.addEventListener('click', function() { navigateTo('catalog?tab=catalog'); });
      }

      function hideQuickStrip() {
        var strip = document.getElementById('quickStrip');
        if (!strip) return;
        strip.innerHTML = '';
        strip.setAttribute('hidden', 'hidden');
      }

      function mountQuickStripPills(pills) {
        var strip = document.getElementById('quickStrip');
        if (!strip) return;
        if (!pills || !pills.length) {
          hideQuickStrip();
          return;
        }
        strip.removeAttribute('hidden');
        strip.innerHTML = pills.map(function(p, i) {
          var primaryClass = p.primary ? ' hub-quick-pill--primary' : '';
          return '<button type="button" class="hub-quick-pill' + primaryClass + '" data-pill-idx="' + i + '">' +
            (ICONS[p.icon] || '') + esc(p.label) +
            '</button>';
        }).join('');
        strip.querySelectorAll('.hub-quick-pill').forEach(function(btn) {
          var idx = parseInt(btn.getAttribute('data-pill-idx'), 10);
          btn.addEventListener('click', function() { pills[idx].action(); });
        });
      }

      function rebookPillItems(nextBooking, targets, maxCount) {
        maxCount = maxCount || 2;
        var multi = orderedRebookPills(nextBooking, targets);
        if (multi.length >= 2) {
          return multi.slice(0, maxCount).map(function(t, ix) {
            return {
              label: 'Снова к ' + trainerFirstNameForPill(t.trainer_display_name),
              icon: 'repeat',
              primary: ix === 0,
              action: function() { navigateToRebookTarget(t); },
            };
          });
        }
        return [{
          label: 'Записаться снова',
          icon: 'repeat',
          primary: true,
          action: function() { navigateToHubBookLikePrimaryFab(nextBooking); },
        }];
      }

      /** Rebook-only pills — bottom tabs cover catalog, bookings, and «Ещё». */
      function renderQuickStrip(scenario, nextBooking) {
        var pills = [];
        if (scenario === 'has-booking') {
          pills = rebookPillItems(nextBooking, rebookTargets, 2);
        } else if (scenario === 'has-past') {
          pills = rebookPillItems(null, rebookTargets, 2);
        }
        mountQuickStripPills(pills);
      }

      function wireAllBookingsLink() {
        var btn = document.getElementById('btnAllBookings');
        if (btn) btn.addEventListener('click', function() { navigateTo('client-bookings'); });
      }

      function resetHubChromeForState(opts) {
        opts = opts || {};
        clearHubHeroActions();
        hideQuickStrip();
        hidePrimaryPanel();
        hideDiscovery();
        if (!opts.keepHeroLayout) resetHubHeroLayout();
      }

      /* ── Primary trainer living panel: slots + pass + history ────────── */

      var RU_MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
      var RU_WEEKDAYS_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

      function hidePrimaryPanel() {
        var el = document.getElementById('hubPrimaryPanel');
        if (!el) return;
        el.innerHTML = '';
        el.setAttribute('hidden', 'hidden');
      }

      function hideDiscovery() {
        var el = document.getElementById('hubDiscovery');
        if (!el) return;
        el.innerHTML = '';
        el.setAttribute('hidden', 'hidden');
      }

      function pluralRuHub(n, one, few, many) {
        n = Math.abs(Number(n) || 0);
        var mod100 = n % 100;
        var mod10 = n % 10;
        if (mod100 >= 11 && mod100 <= 14) return many;
        if (mod10 === 1) return one;
        if (mod10 >= 2 && mod10 <= 4) return few;
        return many;
      }

      /** Parses ISO date (YYYY-MM-DD) as local; ISO datetime works too. */
      function parseIsoDateLocal(s) {
        if (!s) return null;
        var raw = String(s).slice(0, 10).split('-');
        if (raw.length !== 3) return null;
        var y = parseInt(raw[0], 10);
        var m = parseInt(raw[1], 10);
        var d = parseInt(raw[2], 10);
        if (!y || !m || !d) return null;
        return new Date(y, m - 1, d);
      }

      /** Compact slot-chip caption: «Сб, 7 июн». */
      function formatSlotDayLabel(dateStr) {
        var d = parseIsoDateLocal(dateStr);
        if (!d) return '';
        var wd = RU_WEEKDAYS_SHORT[d.getDay()] || '';
        var mn = RU_MONTHS_SHORT[d.getMonth()] || '';
        return (wd ? wd.charAt(0).toUpperCase() + wd.slice(1) + ', ' : '') + d.getDate() + ' ' + mn;
      }

      /** Compact long date for history/expiry: «18 мая 2026» or «18 мая» when current year. */
      function formatHistoryDate(dateStr) {
        var d = parseIsoDateLocal(dateStr);
        if (!d) return '';
        var mn = RU_MONTHS_SHORT[d.getMonth()] || '';
        var now = new Date();
        if (d.getFullYear() === now.getFullYear()) return d.getDate() + ' ' + mn;
        return d.getDate() + ' ' + mn + ' ' + d.getFullYear();
      }

      function buildPrimarySlotsHtml(slots) {
        if (!slots || !slots.length) return '';
        var items = slots.slice(0, 4).map(function(s) {
          var t = (s && s.start_time ? String(s.start_time) : '').slice(0, 5);
          var dayLabel = formatSlotDayLabel(s && s.slot_date);
          var place = ((s && (s.arena_name || s.arena_city_name)) || '').toString().trim();
          var placeHtml = place
            ? '<span class="hub-primary-panel__slot-place">' + ICONS.pin + esc(place) + '</span>'
            : '';
          return (
            '<button type="button" class="hub-primary-panel__slot" data-slot-id="' + esc(String(s.id || '')) + '"' +
            (s && s.arena_id != null ? ' data-arena-id="' + esc(String(s.arena_id)) + '"' : '') +
            (s && s.service_id != null ? ' data-service-id="' + esc(String(s.service_id)) + '"' : '') + '>' +
              '<span class="hub-primary-panel__slot-day">' + esc(dayLabel) + '</span>' +
              '<span class="hub-primary-panel__slot-time">' + esc(t) + '</span>' +
              placeHtml +
            '</button>'
          );
        }).join('');
        return (
          '<div class="hub-primary-panel__row hub-primary-panel__row--slots">' +
            '<div class="hub-primary-panel__row-head">Ближайшие окна</div>' +
            '<div class="hub-primary-panel__slots-scroller">' + items + '</div>' +
          '</div>'
        );
      }

      function buildPrimaryPassHtml(passInfo, opts) {
        opts = opts || {};
        if (!passInfo) return '';
        var remaining = Number(passInfo.sessions_remaining || 0);
        if (!remaining || remaining <= 0) return '';
        var word = pluralRuHub(remaining, 'занятие', 'занятия', 'занятий');
        var expiry = passInfo.expires_at ? formatHistoryDate(passInfo.expires_at) : '';
        var subParts = [];
        if (passInfo.product_name) subParts.push(esc(String(passInfo.product_name)));
        if (expiry) subParts.push('до ' + esc(expiry));
        var subHtml = subParts.length
          ? '<span class="hub-primary-panel__pass-sub">' + subParts.join(' · ') + '</span>'
          : '';
        var autoNoteHtml = opts.autoDebitNote
          ? '<span class="hub-primary-panel__pass-note">Спишется автоматически после занятия</span>'
          : '';
        var passMod = opts.autoDebitNote ? ' hub-primary-panel__pass--auto-debit' : '';
        return (
          '<button type="button" class="hub-primary-panel__pass' + passMod + '" data-hub-action="open-pass">' +
            '<span class="hub-primary-panel__pass-num">' + esc(String(remaining)) + '</span>' +
            '<span class="hub-primary-panel__pass-body">' +
              '<span class="hub-primary-panel__pass-title">' + word + ' по абонементу</span>' +
              subHtml +
              autoNoteHtml +
            '</span>' +
            '<span class="hub-primary-panel__pass-chevron" aria-hidden="true">›</span>' +
          '</button>'
        );
      }

      function buildPrimaryHistoryHtml(history) {
        if (!history) return '';
        var count = Number(history.completed_count || 0);
        if (count <= 0) return '';
        var word = pluralRuHub(count, 'раз', 'раза', 'раз');
        var lastStr = history.last_completed_at ? formatHistoryDate(history.last_completed_at) : '';
        var line = 'Вы тренировались ' + count + ' ' + word;
        if (lastStr) line += ' · последний раз ' + lastStr;
        return '<div class="hub-primary-panel__history">' + esc(line) + '</div>';
      }

      function selectPrimaryPassForTrainer(items, trainerId) {
        if (!Array.isArray(items) || !items.length) return null;
        var tidNum = Number(trainerId);
        // First active pass tied to this trainer with sessions remaining
        for (var i = 0; i < items.length; i++) {
          var it = items[i] || {};
          var st = String(it.status || '').toLowerCase();
          if (st !== 'active') continue;
          var rem = Number(it.sessions_remaining || 0);
          if (rem <= 0) continue;
          if (Number(it.trainer_id) === tidNum) return it;
        }
        return null;
      }

      /** Any active pass with remaining sessions — for hub states without a pinned trainer. */
      function selectAnyActivePass(items) {
        if (!Array.isArray(items) || !items.length) return null;
        for (var i = 0; i < items.length; i++) {
          var it = items[i] || {};
          if (String(it.status || '').toLowerCase() !== 'active') continue;
          if (Number(it.sessions_remaining || 0) <= 0) continue;
          return it;
        }
        return null;
      }

      function hubBootstrapPasses(hubMeta) {
        return Array.isArray(hubMeta && hubMeta.passes) ? hubMeta.passes : [];
      }

      /**
       * Pass-only panel (no slots fetch) — upcoming booking, saved/past fill, etc.
       */
      function renderPrimaryPassPanel(trainerId, bootstrapPasses, opts) {
        opts = opts || {};
        var el = document.getElementById('hubPrimaryPanel');
        if (!el) return false;
        var passes = Array.isArray(bootstrapPasses) ? bootstrapPasses : [];
        var passInfo = trainerId != null && String(trainerId).trim() !== ''
          ? selectPrimaryPassForTrainer(passes, trainerId)
          : selectAnyActivePass(passes);
        var passHtml = buildPrimaryPassHtml(passInfo, opts);
        if (!passHtml) {
          hidePrimaryPanel();
          return false;
        }
        var rowHead = opts.rowHead ? String(opts.rowHead).trim() : '';
        var inner =
          (rowHead
            ? '<div class="hub-primary-panel__row hub-primary-panel__row--pass">' +
              '<div class="hub-primary-panel__row-head">' + esc(rowHead) + '</div>' +
              passHtml +
              '</div>'
            : passHtml);
        el.innerHTML = inner;
        el.removeAttribute('hidden');
        var wireTid = trainerId != null ? trainerId : (passInfo && passInfo.trainer_id);
        wirePrimaryPanelClicks(el, wireTid);
        return true;
      }

      /**
       * Secondary content so sparse hub states still feel alive: active pass + optional discovery.
       */
      function renderHubSecondaryFill(hubMeta, opts) {
        opts = opts || {};
        var passes = hubBootstrapPasses(hubMeta);
        renderPrimaryPassPanel(opts.trainerId != null ? opts.trainerId : null, passes, {
          autoDebitNote: !!opts.autoDebitNote,
          rowHead: opts.passRowHead || '',
        });
        if (opts.showDiscovery) return loadAndRenderDiscovery();
        return Promise.resolve();
      }

      /* Cancels any in-flight /client/slots request when user navigates away */
      var _primaryPanelAbort = null;

      function loadAndRenderPrimaryPanel(trainerId, history, bootstrapPasses) {
        var el = document.getElementById('hubPrimaryPanel');
        if (!el) return Promise.resolve();
        if (trainerId == null || trainerId === '') {
          hidePrimaryPanel();
          return Promise.resolve();
        }
        if (!initData) {
          hidePrimaryPanel();
          return Promise.resolve();
        }

        // Cancel any previous in-flight slots request to free server resources immediately
        if (_primaryPanelAbort) { _primaryPanelAbort.abort(); }
        var ctl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        _primaryPanelAbort = ctl;

        var tidStr = encodeURIComponent(String(trainerId));
        var slotsUrl = apiUrl('/client/slots?trainer_id=' + tidStr);
        var slotsPromise = fetch(slotsUrl, { headers: headersJson(), signal: ctl ? ctl.signal : undefined })
          .then(function(r) { return r.ok ? r.json() : { slots: [] }; })
          .catch(function(e) { return (e && e.name === 'AbortError') ? null : { slots: [] }; });

        // Passes come from bootstrap — no extra round-trip needed
        var passes = Array.isArray(bootstrapPasses) ? bootstrapPasses : [];

        return slotsPromise.then(function(slotsData) {
          if (!slotsData) return; // aborted navigation
          _primaryPanelAbort = null;
          var slots = slotsData.slots || [];
          var passInfo = selectPrimaryPassForTrainer(passes, trainerId);
          var slotsHtml = buildPrimarySlotsHtml(slots);
          var passHtml = buildPrimaryPassHtml(passInfo, {});
          var histHtml = buildPrimaryHistoryHtml(history);
          var inner = slotsHtml + passHtml + histHtml;
          if (!inner) {
            hidePrimaryPanel();
            return;
          }
          el.innerHTML = inner;
          el.removeAttribute('hidden');
          wirePrimaryPanelClicks(el, trainerId);
        });
      }

      function wirePrimaryPanelClicks(el, trainerId) {
        var serviceQuery = catalogPrimaryServiceQuery();
        var trainerBookPath = 'catalog?trainer_id=' + encodeURIComponent(String(trainerId)) + serviceQuery;
        el.addEventListener('click', function(ev) {
          var slotBtn = ev.target && ev.target.closest && ev.target.closest('.hub-primary-panel__slot');
          if (slotBtn) {
            ev.stopPropagation();
            navigateTo(buildBookPathFromHubContext(trainerId, {
              serviceId: slotBtn.getAttribute('data-service-id'),
              slotId: slotBtn.getAttribute('data-slot-id'),
              arenaId: slotBtn.getAttribute('data-arena-id'),
              fallbackServiceQuery: serviceQuery,
            }));
            return;
          }
          var passBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-action="open-pass"]');
          if (passBtn) {
            ev.stopPropagation();
            navigateTo('client-passes-certificates');
            return;
          }
        });
      }

      /* ── Discovery: real trainers carousel for new clients ───────────── */

      /** Same-origin proxy first — CDN often 404 in Telegram WebView and may not fire img.onerror. */
      function hubDiscoveryPhotoListSrc(photo) {
        if (!photo) return '';
        var fk = photo.file_key_list || photo.file_key;
        if (fk) return trainerHubThumb(fk);
        if (photo.list_url) return photo.list_url;
        if (photo.url) return photo.url;
        return '';
      }

      function hubDiscoveryPhotoCdnFallback(photo) {
        if (!photo) return '';
        if (photo.list_url) return photo.list_url;
        if (photo.url) return photo.url;
        return '';
      }

      function wireDiscoveryCardPhotos(root) {
        if (!root) return;
        root.querySelectorAll('.hub-discovery__avatar--photo img').forEach(function(img) {
          function showInitialsFallback() {
            var card = img.closest('.hub-discovery__card');
            var avatar = img.closest('.hub-discovery__avatar');
            if (!avatar) return;
            var nameEl = card && card.querySelector('.hub-discovery__name');
            var name = nameEl ? nameEl.textContent : '?';
            avatar.classList.remove('hub-discovery__avatar--photo');
            avatar.innerHTML = initials(name);
          }
          img.onerror = function() {
            var fb = img.getAttribute('data-fallback') || '';
            if (fb && img.src !== fb) {
              img.onerror = showInitialsFallback;
              img.src = fb;
              return;
            }
            showInitialsFallback();
          };
        });
      }

      function hubDiscoveryServicesLine(services) {
        var labels = (services || []).slice(0, 2).map(function(s) {
          return String((s && (s.service_name || s.name)) || '').trim();
        }).filter(Boolean);
        return labels.join(' · ');
      }

      function buildDiscoveryCardHtml(t) {
        var p = t && t.profile;
        var name = (p ? (((p.first_name || '') + ' ' + (p.last_name || '')).trim()) : '') || 'Тренер';
        var photo = t && t.photos && t.photos[0];
        var src = hubDiscoveryPhotoListSrc(photo);
        var cdnFallback = hubDiscoveryPhotoCdnFallback(photo);
        var avatarHtml = src
          ? '<div class="hub-discovery__avatar hub-discovery__avatar--photo">' +
              '<img src="' + esc(src) + '" alt="" loading="eager" decoding="async"' +
              (cdnFallback && cdnFallback !== src
                ? ' data-fallback="' + esc(cdnFallback) + '"'
                : '') +
              '/></div>'
          : '<div class="hub-discovery__avatar">' + esc(initials(name)) + '</div>';
        var arena = ((t && t.primary_arena_name) || '').toString().trim();
        var arenaHtml = arena ? '<div class="hub-discovery__city">' + ICONS.pin + esc(arena) + '</div>' : '';
        var ratingHtml = '';
        if (p && p.rating_avg != null && (p.rating_count || 0) > 0) {
          ratingHtml =
            '<div class="hub-discovery__rating">⭐ ' +
            esc(Number(p.rating_avg).toFixed(1)) +
            ' <span class="hub-discovery__rating-count">(' + esc(String(p.rating_count)) + ')</span></div>';
        }
        var services = (t && Array.isArray(t.services)) ? t.services : [];
        var svcLine = hubDiscoveryServicesLine(services);
        var svcHtml = svcLine
          ? '<div class="hub-discovery__services">' + esc(svcLine) + '</div>'
          : '';
        var tidStr = esc(String((t && t.id) || ''));
        return (
          '<button type="button" class="hub-discovery__card" data-tid="' + tidStr + '">' +
            avatarHtml +
            '<div class="hub-discovery__body">' +
              '<div class="hub-discovery__name">' + esc(name) + '</div>' +
              ratingHtml +
              arenaHtml +
              svcHtml +
            '</div>' +
          '</button>'
        );
      }

      function loadAndRenderDiscovery() {
        var el = document.getElementById('hubDiscovery');
        if (!el) return Promise.resolve();
        var url = '/api/public/trainers?limit=6';
        return fetch(url, { headers: { 'Content-Type': 'application/json' } })
          .then(function(r) { return r.ok ? r.json() : { items: [] }; })
          .catch(function() { return { items: [] }; })
          .then(function(payload) {
            var items = (payload && (payload.items || payload.trainers)) || [];
            items = items.filter(function(t) { return t && t.id != null; }).slice(0, 6);
            if (!items.length) {
              hideDiscovery();
              return;
            }
            var cards = items.map(buildDiscoveryCardHtml).join('');
            el.innerHTML =
              '<div class="hub-discovery__head">' +
                '<span class="hub-discovery__title">Тренеры на платформе</span>' +
                '<button type="button" class="hub-discovery__link" id="hubDiscoveryAll">Все</button>' +
              '</div>' +
              '<div class="hub-discovery__row">' + cards + '</div>';
            el.removeAttribute('hidden');
            wireDiscoveryCardPhotos(el);
            var allBtn = document.getElementById('hubDiscoveryAll');
            if (allBtn) allBtn.addEventListener('click', function() { navigateTo('catalog?tab=catalog'); });
            el.querySelectorAll('.hub-discovery__card').forEach(function(btn) {
              btn.addEventListener('click', function() {
                var tid = btn.getAttribute('data-tid');
                if (tid) navigateTo('catalog?trainer_id=' + encodeURIComponent(tid));
              });
            });
          });
      }

      /* ── Upcoming bookings list ──────────────────────────────────────── */

      function revealBookingsBlock(innerHtml) {
        var block = document.getElementById('bookingsBlock');
        if (!block) return;
        block.innerHTML = '<div class="hub-bookings-mount">' + innerHtml + '</div>';
        var mount = block.firstElementChild;
        if (!mount) return;
        requestAnimationFrame(function() {
          requestAnimationFrame(function() { mount.classList.add('hub-bookings-mount--visible'); });
        });
      }

      function wireUpcomingBookingsBlock() {
        var bblock = document.getElementById('bookingsBlock');
        if (!bblock || bblock.getAttribute('data-hub-list-wired') === '1') return;
        bblock.setAttribute('data-hub-list-wired', '1');
        bblock.addEventListener(
          'click',
          function(ev) {
            var dmBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-dm="list"]');
            if (dmBtn) {
              ev.preventDefault();
              ev.stopPropagation();
              if (window.ClientShell && typeof window.ClientShell.hapticSelection === 'function') {
                window.ClientShell.hapticSelection();
              }
              openTelegramDm(
                dmBtn.getAttribute('data-dm-un'),
                dmBtn.getAttribute('data-dm-tid'),
                dmBtn.getAttribute('data-trainer-id')
              );
              return;
            }
            var row = ev.target && ev.target.closest && ev.target.closest('.hub-booking-row[data-bid]');
            if (!row) return;
            var bid = row.getAttribute('data-bid');
            if (bid) navigateTo('client-bookings?open_booking=' + encodeURIComponent(bid) + '&from=hub');
          },
          true
        );
      }

      /**
       * Renders the secondary bookings list (up to HUB_UPCOMING_MAX items)
       * shown below the hero card. Skips the first booking if it's already
       * shown in the hero card.
       */
      function renderUpcomingList(days, heroBookingId) {
        var section = document.getElementById('upcomingSection');
        var flat = flattenBookings(days);
        /* Skip the booking already featured in the hero card */
        var items = flat.filter(function(item) {
          return String(item.b.id) !== String(heroBookingId);
        }).slice(0, HUB_UPCOMING_MAX);

        if (!items.length) {
          if (section) section.style.display = 'none';
          return;
        }
        if (section) section.style.display = '';

        /* Group by date for day chips */
        var byDate = {};
        var dateOrder = [];
        items.forEach(function(item) {
          var ds = item.day.date || '';
          if (!byDate[ds]) { byDate[ds] = { day: item.day, bookings: [] }; dateOrder.push(ds); }
          byDate[ds].bookings.push(item.b);
        });

        var parts = [];
        dateOrder.forEach(function(ds) {
          var group = byDate[ds];
          var chipLabel = relativeDate(ds, group.day.day_label);
          parts.push('<div class="hub-day-chip">' + esc(chipLabel) + '</div>');
          parts.push('<div class="hub-bookings-stack">');
          group.bookings.forEach(function(b) {
            var st = String(b.status || '').toLowerCase();
            var isPending = st === 'pending';
            var rowClass = isPending ? 'hub-booking-row--pending' : 'hub-booking-row--confirmed';
            var statusClass = isPending ? 'hub-booking-status--pending' : 'hub-booking-status--confirmed';
            var statusLabel = isPending ? 'Ожидает ⏳' : 'Подтверждено ✅';
            var time = (b.start_time || '').slice(0, 5);
            var dur = b.duration_minutes || 45;
            var trainerName = b.trainer_name || 'Тренер';
            var place = ((b.arena_name || b.place_display || '') + '').trim() || '';

            var msgBtnHtml = '';
            if (canWriteTrainer(b)) {
              msgBtnHtml =
                '<button type="button" class="hub-booking-msg-btn" data-hub-dm="list"' +
                ' data-dm-un="' + esc((b.trainer_telegram_username || '').replace(/^@/, '')) + '"' +
                ' data-dm-tid="' + esc(b.trainer_telegram_id != null ? String(b.trainer_telegram_id) : '') + '"' +
                ' data-trainer-id="' + esc(b.trainer_id != null ? String(b.trainer_id) : '') + '"' +
                ' aria-label="Написать тренеру">' + ICONS.msg + '</button>';
            }

            parts.push(
              '<div class="hub-booking-row ' + rowClass + '" data-bid="' + esc(String(b.id)) + '">' +
                '<div class="hub-booking-time-col">' +
                  '<div class="hub-booking-time-block">' +
                    '<div class="hub-booking-time">' + esc(time) + '</div>' +
                    hubSessionNowPillHtml(b) +
                  '</div>' +
                  '<div class="hub-booking-dur">' + esc(String(dur)) + ' мин</div>' +
                '</div>' +
                '<div class="hub-booking-divider"></div>' +
                '<div class="hub-booking-info">' +
                  '<div class="hub-booking-trainer">' + esc(trainerName) + '</div>' +
                  (place ? '<div class="hub-booking-place">' + esc(place) + '</div>' : '') +
                  '<span class="hub-booking-status hub-booking-status--inline ' + statusClass + '">' + statusLabel + '</span>' +
                '</div>' +
                (msgBtnHtml ? '<div class="hub-booking-row-end">' + msgBtnHtml + '</div>' : '') +
              '</div>'
            );
          });
          parts.push('</div>');
        });

        revealBookingsBlock(parts.join(''));
        wireUpcomingBookingsBlock();
      }

      /* ── New client: hero CTA only — no marketing block in nextBookingBlock ── */
      function renderAcquisitionHero() {
        clearNextBookingBlock();
        renderNewClientHeroActions();
      }

      /* ── Saved trainers strip ───────────────────────────────────────── */

      function thumbForHubPhoto(key) {
        if (!key) return '';
        return '/api/public/photos/' + encodeURIComponent(key);
      }

      /**
       * Renders a horizontal scroll strip of saved (bookmarked) trainers.
       * Uses `client_session.saved_trainers` from hub bootstrap when present (names + photo keys).
       */
      function renderSavedTrainersStrip(cs) {
        var block = document.getElementById('myTrainerBlock');
        if (!block) return;
        var list = [];
        if (cs && Array.isArray(cs.saved_trainers) && cs.saved_trainers.length) {
          list = cs.saved_trainers;
        } else if (cs && Array.isArray(cs.saved_trainer_ids) && cs.saved_trainer_ids.length) {
          cs.saved_trainer_ids.forEach(function (id) {
            list.push({
              trainer_id: id,
              trainer_display_name: 'Тренер',
              trainer_list_photo_key: null
            });
          });
        }
        if (!list.length) return;
        var chips = list.map(function (row) {
          var tid = row.trainer_id;
          var label = (row.trainer_display_name || 'Тренер').trim() || 'Тренер';
          var src = thumbForHubPhoto(row.trainer_list_photo_key || null);
          var photoPart = src
            ? '<span class="hub-saved-chip-avatar"><img src="' + esc(src) + '" alt=""/></span>'
            : '<span class="hub-saved-chip-icon" aria-hidden="true">🤍</span>';
          return '<button type="button" class="hub-saved-chip" data-tid="' + esc(String(tid)) + '">' +
            photoPart +
            '<span class="hub-saved-chip-label">' + esc(label) + '</span>' +
            '</button>';
        }).join('');
        block.innerHTML =
          '<div class="hub-saved-section">' +
            '<div class="hub-saved-section-head">' +
              '<span class="hub-saved-section-title">Сохранённые тренеры</span>' +
              '<button type="button" class="hub-saved-section-link" id="btnViewSaved">Все</button>' +
            '</div>' +
            '<div class="hub-saved-strip">' + chips + '</div>' +
          '</div>';
        block.style.display = '';
        var viewBtn = document.getElementById('btnViewSaved');
        if (viewBtn) viewBtn.addEventListener('click', function() { navigateTo('client-saved-trainers'); });
        block.querySelectorAll('.hub-saved-chip').forEach(function(btn) {
          btn.addEventListener('click', function() {
            navigateTo('catalog?trainer_id=' + encodeURIComponent(btn.getAttribute('data-tid')));
          });
        });
      }

      /* ── Main state machine — Intent Engine ─────────────────────────── */

      /**
       * Home intent priority (strict order — first matching level wins):
       *   1. Upcoming booking  → booking hero card + pass (auto-debit note) + rebook pills + list
       *   2. Primary trainer   → "Мой тренер" card + slots / pass / history panel
       *   3. Saved trainers    → saved strip + pass (if any) + discovery carousel
       *   4. Has past sessions → rebook pills + pass (if any) + discovery carousel
       *   5. Clean state       → acquisition hero + discovery carousel
       *
       * This is a decision engine, not a dashboard.
       * It answers: "what is the most important thing for the client right now?"
       */
      function applyHubState(bookingDays, requestItems, hubMeta) {
        if (window.ClientShell && typeof window.ClientShell.writeBookingsWarmCache === 'function') {
          window.ClientShell.writeBookingsWarmCache({ days: bookingDays || [] });
        }
        var platformUi = (hubMeta && hubMeta.platform && hubMeta.platform.ui) || {};
        var wordmarkEl = document.getElementById('hubIceWordmark');
        if (wordmarkEl && platformUi.hero_wordmark) {
          wordmarkEl.textContent = platformUi.hero_wordmark;
        }
        var cs = (hubMeta && hubMeta.client_session) || {};
        // Support both legacy (selected_trainer_id) and new edge-based fields
        var primaryTrainerId = cs.primary_trainer_id != null ? cs.primary_trainer_id
          : (cs.selected_trainer_id != null && cs.selected_trainer_id !== '' ? cs.selected_trainer_id : null);
        var savedTrainersRich = Array.isArray(cs.saved_trainers) ? cs.saved_trainers : [];
        var savedIds = Array.isArray(cs.saved_trainer_ids) ? cs.saved_trainer_ids : [];
        var hasSavedBookmarks = savedTrainersRich.length > 0 || savedIds.length > 0;
        var hasPastSessions = !!cs.has_past_sessions;
        selectedTrainerId = primaryTrainerId;
        var rawPcs = cs.primary_catalog_service_id;
        if (rawPcs != null && rawPcs !== '') {
          var ppn = Number(rawPcs);
          primaryCatalogServiceId = !isNaN(ppn) && ppn > 0 ? ppn : null;
        } else {
          primaryCatalogServiceId = null;
        }

        var rawLt = cs.last_booking_trainer_id;
        if (rawLt != null && String(rawLt).trim() !== '') {
          var nlt = Number(rawLt);
          lastBookingTrainerId = !isNaN(nlt) && nlt > 0 ? nlt : null;
        } else {
          lastBookingTrainerId = null;
        }
        var rawLs = cs.last_booking_service_id;
        if (rawLs != null && String(rawLs).trim() !== '') {
          var nls = Number(rawLs);
          lastBookingServiceId = !isNaN(nls) && nls > 0 ? nls : null;
        } else {
          lastBookingServiceId = null;
        }

        rebookTargets = Array.isArray(cs.rebook_targets) ? cs.rebook_targets : [];
        hubPrimaryTrainerCanBook = cs.primary_trainer_can_book === true;

        function finishHubApply(promise) {
          syncClientHubBookFab();
          return promise;
        }

        var nextItem = findNextBooking(bookingDays);
        hubHasUpcomingBooking = !!nextItem;

        /* ── Priority 1: Has upcoming booking ── */
        if (nextItem) {
          resetHubChromeForState({ keepHeroLayout: true });
          configureHeroForUpcomingBooking();
          renderNextBookingCard(nextItem);
          hideMyTrainerBlock();
          renderQuickStrip('has-booking', nextItem);
          renderUpcomingList(bookingDays, nextItem.b.id);
          var bookingTrainerId = nextItem.b && nextItem.b.trainer_id;
          renderPrimaryPassPanel(bookingTrainerId, hubBootstrapPasses(hubMeta), {
            autoDebitNote: true,
            rowHead: 'Абонемент',
          });
          return finishHubApply(Promise.resolve());
        }

        clearNextBookingBlock();
        hideUpcomingSection();
        resetHubChromeForState();

        /* ── Priority 2: Has primary trainer ── */
        if (primaryTrainerId != null) {
          resetHubHeroLayout();
          setHeroText('Время для тренировки', 'Выберите удобный слот у вашего тренера');
          var pname = (cs.primary_trainer_name || '').trim();
          var pphoto = cs.primary_trainer_list_photo_key || null;
          var ptgUn = cs.primary_trainer_telegram_username || null;
          var ptgId = cs.primary_trainer_telegram_id != null ? cs.primary_trainer_telegram_id : null;
          var pCanBook = cs.primary_trainer_can_book === true;
          renderMyTrainerCard(primaryTrainerId, pname || null, ptgUn, ptgId, pphoto, pCanBook);
          return finishHubApply(
            loadAndRenderPrimaryPanel(primaryTrainerId, cs.primary_history || null, hubBootstrapPasses(hubMeta))
          );
        }

        /* ── Priority 3: Has saved trainers (no primary yet) ── */
        if (hasSavedBookmarks && primaryTrainerId == null) {
          resetHubHeroLayout();
          setHeroText('Ваши любимые тренеры 💛', 'Выберите, с кем хотите позаниматься');
          renderSavedTrainersStrip(cs);
          return finishHubApply(renderHubSecondaryFill(hubMeta, { showDiscovery: true, passRowHead: 'Абонемент' }));
        }

        /* ── Priority 4: Has past sessions (churned / dormant) ── */
        if (hasPastSessions) {
          resetHubHeroLayout();
          setHeroText('Возвращаемся на лёд! ⛸️', 'Ваши тренеры очень ждут вас');
          hideMyTrainerBlock();
          renderQuickStrip('has-past', null);
          return finishHubApply(renderHubSecondaryFill(hubMeta, { showDiscovery: true, passRowHead: 'Абонемент' }));
        }

        /* ── Priority 5: Clean state — find trainer and book ── */
        resetHubHeroLayout();
        setHeroText('Добро пожаловать!', 'Выберите, чем хотите заняться, а мы найдём лучшего тренера');
        renderAcquisitionHero();
        hideMyTrainerBlock();
        return finishHubApply(loadAndRenderDiscovery());
      }

      function hideMyTrainerBlock() {
        var b = document.getElementById('myTrainerBlock');
        if (b) b.style.display = 'none';
      }

      function hideUpcomingSection() {
        var s = document.getElementById('upcomingSection');
        if (s) s.style.display = 'none';
      }

      /* ── Data loading ────────────────────────────────────────────────── */
      function jsonOrThrow(r) {
        return r.json().then(function(d) {
          if (!r.ok) throw new Error(d.detail || r.statusText);
          return d;
        });
      }

      function loadAll() {
        hubLoadStartedAt = Date.now();
        wireAllBookingsLink();
        if (!initData) {
          setStateMessage('', '');
          hideNextBookingSkeleton();
          renderAcquisitionHero();
          renderStreakRibbon(null);
          return loadAndRenderDiscovery().then(finishHubInitialLoading, finishHubInitialLoading);
        }

        /* Bootstrap API: single round-trip, then wait for scenario async work */
        return fetch(apiUrl('/client/hub/bootstrap'), { headers: headersJson() })
          .then(jsonOrThrow)
          .then(function(hub) {
            var days = (hub.bookings || {}).days || [];
            var reqs = (hub.requests || {}).items || [];
            renderStreakRibbon(hub.activity || {});
            if (window.ClientShell && typeof window.ClientShell.scheduleCatalogNavigationPrefetch === 'function') {
              window.ClientShell.scheduleCatalogNavigationPrefetch();
            }
            return applyHubState(days, reqs, hub);
          })
          .catch(function() {
            /* Fallback: parallel individual calls */
            return Promise.all([
              fetch(apiUrl('/client/bookings'), { headers: headersJson() }).then(jsonOrThrow),
              fetch(apiUrl('/client/requests'), { headers: headersJson() }).then(jsonOrThrow),
              fetch(apiUrl('/client/session'), { headers: headersJson() }).then(jsonOrThrow).catch(function() { return {}; }),
            ]).then(function(results) {
              var sess = results[2] || {};
              renderStreakRibbon(null);
              return applyHubState(
                results[0].days || [],
                results[1].items || [],
                { client_session: { selected_trainer_id: sess.trainer_id != null ? sess.trainer_id : null } }
              );
            });
          })
          .catch(function() {
            setStateMessage('Не удалось загрузить данные. Откройте страницу из клиентского бота.', 'error');
            hideNextBookingSkeleton();
            clearNextBookingBlock();
            hideMyTrainerBlock();
            hideUpcomingSection();
            renderStreakRibbon(null);
            hubPrimaryTrainerCanBook = false;
            syncClientHubBookFab();
          })
          .then(finishHubInitialLoading, finishHubInitialLoading);
      }

      (function wireHubFootnoteCollapse() {
        var root = document.getElementById('hubFootnote');
        var btn = document.getElementById('hubFootnoteToggle');
        var panel = document.getElementById('hubFootnoteExpand');
        if (!root || !btn) return;
        btn.addEventListener('click', function() {
          var open = root.classList.toggle('hub-footnote--open');
          btn.setAttribute('aria-expanded', open ? 'true' : 'false');
          if (panel) panel.setAttribute('aria-hidden', open ? 'false' : 'true');
          if (open && typeof root.scrollIntoView === 'function') {
            try {
              root.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            } catch (eScroll) {
              /* noop */
            }
          }
        });
      })();

      (function wireHubSupportForm() {
        var form = document.getElementById('hubSupportForm');
        var ta = document.getElementById('hubSupportMessage');
        var btn = document.getElementById('hubSupportSubmit');
        var statusEl = document.getElementById('hubSupportStatus');
        if (!form || !ta || !btn) return;
        form.addEventListener('submit', function(ev) {
          ev.preventDefault();
          var text = (ta.value || '').trim();
          if (!text) {
            if (statusEl) {
              statusEl.textContent = 'Напишите пару слов — что случилось или что хотите улучшить.';
              statusEl.className = 'hub-support-status hub-support-status--err';
            }
            return;
          }
          if (!initData) {
            if (statusEl) {
              statusEl.textContent =
                'Откройте страницу из клиентского бота или отправьте сообщение через /guide.';
              statusEl.className = 'hub-support-status hub-support-status--err';
            }
            return;
          }
          btn.disabled = true;
          if (statusEl) {
            statusEl.textContent = 'Отправляем…';
            statusEl.className = 'hub-support-status';
          }
          fetch(apiUrl('/support'), {
            method: 'POST',
            headers: headersJson(),
            body: JSON.stringify({ message: text, role: 'client' }),
          })
            .then(function(r) {
              return r.json().then(function(data) {
                return { ok: r.ok, data: data };
              });
            })
            .then(function(o) {
              btn.disabled = false;
              var sid = o.data && o.data.id;
              var okSend = o.ok && o.data && o.data.ok !== false && sid != null;
              if (okSend) {
                ta.value = '';
                if (statusEl) {
                  statusEl.textContent =
                    'Спасибо за ваше сообщение! 💛 Мы обязательно прочитаем и ответим в боте.';
                  statusEl.className = 'hub-support-status hub-support-status--ok';
                }
                var wg = window.Telegram && window.Telegram.WebApp;
                if (wg && wg.HapticFeedback && wg.HapticFeedback.notificationOccurred) {
                  try {
                    wg.HapticFeedback.notificationOccurred('success');
                  } catch (eh) {
                    /* noop */
                  }
                }
              } else {
                var detail =
                  o.data && (o.data.detail || o.data.message)
                    ? String(o.data.detail || o.data.message)
                    : 'Не удалось отправить.';
                if (statusEl) {
                  statusEl.textContent = detail + ' Попробуйте через /guide в боте.';
                  statusEl.className = 'hub-support-status hub-support-status--err';
                }
              }
            })
            .catch(function() {
              btn.disabled = false;
              if (statusEl) {
                statusEl.textContent =
                  'Сеть недоступна. Повторите позже или напишите через /guide в боте.';
                statusEl.className = 'hub-support-status hub-support-status--err';
              }
            });
        });
      })();

      (function wireIceLaneVisibilityPause() {
        var lane = document.getElementById('hubIceLane');
        if (!lane) return;
        function sync() {
          var paused = document.hidden;
          lane.classList.toggle('ice-lane--paused', paused);
        }
        document.addEventListener('visibilitychange', sync);
        sync();
      })();

      loadAll();
    })();
