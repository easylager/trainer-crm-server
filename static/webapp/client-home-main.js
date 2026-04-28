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
        pin:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>',
        repeat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
        plus:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
      };

      /** Explore tiles shown at bottom — same in all scenarios. */
      var EXPLORE_TILES = [
        { path: 'catalog',                label: 'Тренеры и запись',     hint: 'Каталог, фильтры, слоты', icon: 'search', badge: null },
        { path: 'client-bookings',        label: 'Мои записи',           hint: 'Все занятия',             icon: 'cal',    badge: null },
        { path: 'client-requests',        label: 'Заявки',               hint: 'Подбор тренера',          icon: 'inbox',  badge: 'NEW' },
        { path: 'client-passes-certificates', label: 'Абонементы',       hint: 'Остаток, сроки, покупка', icon: 'ticket', badge: null },
      ];

      /* ── State ──────────────────────────────────────────────────────── */
      /** selected_trainer_id from catalog/bot session */
      var selectedTrainerId = null;

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
        window.location.href = withInit(webappBasePath() + pathWithQuery);
      }

      function esc(s) {
        if (s == null) return '';
        return String(s)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      function initials(name) {
        if (!name) return '?';
        var parts = String(name).trim().split(/\s+/);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        return parts[0].slice(0, 2).toUpperCase();
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

      function openTelegramDm(username, telegramId) {
        if (window.openTelegramChatFromMiniApp) {
          return window.openTelegramChatFromMiniApp({ username: username, telegramId: telegramId });
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
      function setHeroText(title, sub) {
        var t = document.getElementById('hubHeroTitle');
        var s = document.getElementById('hubHeroSub');
        if (t) t.textContent = title;
        if (s) {
          if (sub) { s.textContent = sub; s.style.display = ''; }
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
        var statusLabel = isPending ? 'ожидает' : 'подтверждено';
        var statusClass = isPending ? 'hub-next-card-status--pending' : 'hub-next-card-status--confirmed';
        var time = (b.start_time || '').slice(0, 5);
        var dateLabel = relativeDate(day.date, day.day_label);
        var trainerName = b.trainer_name || 'Тренер';
        var place = ((b.arena_name || b.place_display || '') + '').trim();
        var dur = b.duration_minutes || 45;

        var placeHtml = place
          ? '<span class="hub-next-card-place">' + ICONS.pin + esc(place) + '</span>'
          : '';

        var msgBtnHtml = '';
        if (canWriteTrainer(b)) {
          msgBtnHtml =
            '<button type="button" class="hub-next-card-btn" data-hub-dm="next"' +
            ' data-dm-un="' + esc((b.trainer_telegram_username || '').replace(/^@/, '')) + '"' +
            ' data-dm-tid="' + esc(b.trainer_telegram_id != null ? String(b.trainer_telegram_id) : '') + '">' +
            'Написать тренеру' +
            '</button>';
        }

        var html =
          '<div class="hub-next-card" id="nextCard" data-bid="' + esc(String(b.id)) + '">' +
            '<span class="hub-next-card-status ' + statusClass + '">' + statusLabel + '</span>' +
            '<div class="hub-next-card-inner">' +
              '<div class="hub-next-card-eyebrow">' +
                '<span class="hub-next-card-eyebrow-dot"></span>' +
                'Ближайшая тренировка' +
              '</div>' +
              '<div class="hub-next-card-time">' + esc(time) + '</div>' +
              '<div class="hub-next-card-date">' + esc(dateLabel) + ' · ' + esc(String(dur)) + ' мин</div>' +
              '<div class="hub-next-card-meta">' +
                '<span class="hub-next-card-trainer">' +
                  '<span class="hub-next-card-trainer-avatar">' + esc(initials(trainerName)) + '</span>' +
                  esc(trainerName) +
                '</span>' +
                placeHtml +
              '</div>' +
              '<div class="hub-next-card-actions">' +
                '<button type="button" class="hub-next-card-btn" data-hub-action="open-booking"' +
                ' data-bid="' + esc(String(b.id)) + '">Открыть запись</button>' +
                msgBtnHtml +
              '</div>' +
            '</div>' +
          '</div>';

        var block = document.getElementById('nextBookingBlock');
        block.innerHTML = html;

        /* Wire interactions */
        var card = document.getElementById('nextCard');
        if (!card) return;
        card.addEventListener('click', function(ev) {
          /* Message button — open Telegram DM */
          var dmBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-dm="next"]');
          if (dmBtn) {
            ev.stopPropagation();
            openTelegramDm(dmBtn.getAttribute('data-dm-un'), dmBtn.getAttribute('data-dm-tid'));
            return;
          }
          /* Open booking detail */
          var openBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-action="open-booking"]');
          var bid = (openBtn || card).getAttribute('data-bid');
          if (bid) navigateTo('client-bookings?open_booking=' + encodeURIComponent(bid));
        });
      }

      function hideNextBookingSkeleton() {
        var skel = document.getElementById('nextBookingSkel');
        if (skel) skel.remove();
      }

      function clearNextBookingBlock() {
        var block = document.getElementById('nextBookingBlock');
        if (block) block.innerHTML = '';
      }

      /* ── My trainer card ─────────────────────────────────────────────── */

      /**
       * Renders the "Мой тренер" card when client has a known trainer
       * but no upcoming booking exists (or as secondary info in Scenario 1).
       */
      function renderMyTrainerCard(trainerName, trainerUsername, trainerTelegramId) {
        var block = document.getElementById('myTrainerBlock');
        if (!block) return;
        var un = (trainerUsername || '').replace(/^@/, '').trim();
        var tid = trainerTelegramId != null ? String(trainerTelegramId) : '';
        var hasDm = un || tid;

        var msgBtnHtml = hasDm
          ? '<div class="hub-trainer-actions">' +
              '<button type="button" class="hub-trainer-msg-btn" data-hub-dm="trainer"' +
              ' data-dm-un="' + esc(un) + '" data-dm-tid="' + esc(tid) + '"' +
              ' aria-label="Написать тренеру">' + ICONS.msg + '</button>' +
            '</div>'
          : '';

        block.innerHTML =
          '<div class="hub-trainer-card" id="trainerCard">' +
            '<div class="hub-trainer-avatar">' + esc(initials(trainerName)) + '</div>' +
            '<div class="hub-trainer-info">' +
              '<div class="hub-trainer-label">Мой тренер</div>' +
              '<div class="hub-trainer-name">' + esc(trainerName || 'Тренер') + '</div>' +
              '<div class="hub-trainer-sub">Перейти в каталог → Записаться</div>' +
            '</div>' +
            msgBtnHtml +
          '</div>';
        block.style.display = '';

        var card = document.getElementById('trainerCard');
        if (!card) return;
        card.addEventListener('click', function(ev) {
          var dmBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-dm="trainer"]');
          if (dmBtn) {
            ev.stopPropagation();
            openTelegramDm(dmBtn.getAttribute('data-dm-un'), dmBtn.getAttribute('data-dm-tid'));
            return;
          }
          navigateTo('catalog');
        });
      }

      /* ── Quick action pills ──────────────────────────────────────────── */

      /**
       * Pill strip adapts to scenario:
       *   - has booking  → "Перенести", "Записаться снова", "Все записи"
       *   - has trainer  → "Записаться", "Все записи", "Абонемент"
       *   - new client   → "Найти тренера" (primary), "Группы", "Как это работает"
       */
      function renderQuickStrip(scenario, nextBooking) {
        var pills = [];

        if (scenario === 'has-booking') {
          pills = [
            { label: 'Записаться снова', icon: 'repeat', action: function() { navigateTo('catalog'); } },
            { label: 'Все записи',       icon: 'cal',    action: function() { navigateTo('client-bookings'); } },
            { label: 'Абонемент',        icon: 'ticket', action: function() { navigateTo('client-passes-certificates'); } },
          ];
        } else if (scenario === 'has-trainer') {
          pills = [
            { label: 'Записаться',    icon: 'plus',   primary: true, action: function() { navigateTo('catalog'); } },
            { label: 'Мои записи',    icon: 'cal',               action: function() { navigateTo('client-bookings'); } },
            { label: 'Абонемент',     icon: 'ticket',            action: function() { navigateTo('client-passes-certificates'); } },
          ];
        } else {
          /* acquisition state */
          pills = [
            { label: 'Найти тренера', icon: 'search', primary: true, action: function() { navigateTo('catalog'); } },
            { label: 'Заявка',        icon: 'inbox',               action: function() { navigateTo('client-requests'); } },
            { label: 'Мои записи',    icon: 'cal',                 action: function() { navigateTo('client-bookings'); } },
          ];
        }

        var strip = document.getElementById('quickStrip');
        if (!strip) return;
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
            var statusLabel = isPending ? 'ожидает' : 'подтверждено';
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
                ' aria-label="Написать тренеру">' + ICONS.msg + '</button>';
            }

            parts.push(
              '<div class="hub-booking-row ' + rowClass + '" data-bid="' + esc(String(b.id)) + '">' +
                '<div class="hub-booking-time-col">' +
                  '<div class="hub-booking-time">' + esc(time) + '</div>' +
                  '<div class="hub-booking-dur">' + esc(String(dur)) + ' мин</div>' +
                '</div>' +
                '<div class="hub-booking-divider"></div>' +
                '<div class="hub-booking-info">' +
                  '<div class="hub-booking-trainer">' + esc(trainerName) + '</div>' +
                  (place ? '<div class="hub-booking-place">' + esc(place) + '</div>' : '') +
                '</div>' +
                '<div class="hub-booking-row-end">' +
                  '<span class="hub-booking-status ' + statusClass + '">' + statusLabel + '</span>' +
                  msgBtnHtml +
                '</div>' +
              '</div>'
            );
          });
          parts.push('</div>');
        });

        revealBookingsBlock(parts.join(''));

        /* Wire clicks on the newly rendered block */
        var bblock = document.getElementById('bookingsBlock');
        if (bblock) {
          if (window.wireHubSlotMessageButtons) {
            try { window.wireHubSlotMessageButtons(bblock); } catch (e) {}
          }
          bblock.addEventListener('click', function(ev) {
            var dmBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-dm="list"]');
            if (dmBtn) {
              ev.stopPropagation();
              openTelegramDm(dmBtn.getAttribute('data-dm-un'), dmBtn.getAttribute('data-dm-tid'));
              return;
            }
            var row = ev.target && ev.target.closest && ev.target.closest('.hub-booking-row[data-bid]');
            if (!row) return;
            var bid = row.getAttribute('data-bid');
            if (bid) navigateTo('client-bookings?open_booking=' + encodeURIComponent(bid));
          });
        }
      }

      /* ── Explore tiles ───────────────────────────────────────────────── */
      function renderExploreTiles() {
        var grid = document.getElementById('hubGrid');
        if (!grid) return;
        grid.innerHTML = EXPLORE_TILES.map(function(t) {
          var badgeHtml = t.badge ? '<div class="hub-explore-badge">' + esc(t.badge) + '</div>' : '';
          var icon = ICONS[t.icon] || ICONS.cal;
          /* Reuse the shared icon but swap in the tile-specific class */
          var svgWrapped = icon.replace('<svg ', '<svg class="hub-explore-icon" ');
          return (
            '<button type="button" class="hub-explore-tile" data-path="' + esc(t.path) + '">' +
              badgeHtml +
              svgWrapped +
              '<div class="hub-explore-label">' + esc(t.label) + '</div>' +
              '<div class="hub-explore-hint">' + esc(t.hint) + '</div>' +
            '</button>'
          );
        }).join('');
        grid.querySelectorAll('.hub-explore-tile').forEach(function(btn) {
          btn.addEventListener('click', function() { navigateTo(btn.getAttribute('data-path')); });
        });
      }

      /* ── "All bookings" link ────────────────────────────────────────── */
      function wireAllBookingsLink() {
        var btn = document.getElementById('btnAllBookings');
        if (btn) btn.addEventListener('click', function() { navigateTo('client-bookings'); });
      }

      /* ── Acquisition state (no trainer, no bookings) ─────────────────── */
      function renderAcquisitionHero() {
        var block = document.getElementById('nextBookingBlock');
        if (!block) return;
        block.innerHTML =
          '<div class="hub-acq-hero">' +
            '<div class="hub-hero-greeting" style="margin-bottom:6px;">С чего начать?</div>' +
            '<div style="font-size:17px;font-weight:700;letter-spacing:-0.02em;line-height:1.2;margin-bottom:4px;">Найдите тренера под вашу задачу</div>' +
            '<div style="font-size:13px;color:var(--tg-theme-hint-color);line-height:1.5;margin-bottom:0;">Выберите специалиста, забронируйте удобное время и начните тренироваться.</div>' +
            '<div class="hub-acq-steps">' +
              '<div class="hub-acq-step"><span class="hub-acq-step-num">1</span>Выберите тренера из каталога</div>' +
              '<div class="hub-acq-step"><span class="hub-acq-step-num">2</span>Запишитесь на удобное время</div>' +
              '<div class="hub-acq-step"><span class="hub-acq-step-num">3</span>Получите подтверждение</div>' +
            '</div>' +
          '</div>';
      }

      /* ── Main state machine ─────────────────────────────────────────── */

      /**
       * Determines scenario and orchestrates all render functions.
       *   Scenario 3: next booking exists → hero card + compact list + pills(has-booking)
       *   Scenario 1: no booking but has trainer → trainer card + pills(has-trainer)
       *   Scenario 2: no trainer, no booking → acquisition hero + pills(new-client)
       */
      function applyHubState(bookingDays, requestItems, hubMeta) {
        var cs = (hubMeta && hubMeta.client_session) || {};
        selectedTrainerId = cs.selected_trainer_id != null && cs.selected_trainer_id !== '' ? cs.selected_trainer_id : null;

        var flat = flattenBookings(bookingDays);
        var nextItem = findNextBooking(bookingDays);
        var hasBookings = flat.length > 0;

        /* --- Scenario 3: has upcoming booking --- */
        if (nextItem) {
          setHeroText('Ваша следующая тренировка', null);
          renderNextBookingCard(nextItem);
          /* Show trainer card additionally if we know the trainer context */
          hideMyTrainerBlock();
          renderQuickStrip('has-booking', nextItem);
          renderUpcomingList(bookingDays, nextItem.b.id);
          return;
        }

        /* --- Scenario 1: knows trainer, no upcoming booking --- */
        if (selectedTrainerId != null) {
          setHeroText('Готовы к следующей тренировке?', 'Запишитесь к своему тренеру');
          clearNextBookingBlock();
          /* We don't have trainer name in session — use generic card */
          renderMyTrainerCard('Мой тренер', null, null);
          renderQuickStrip('has-trainer', null);
          hideUpcomingSection();
          return;
        }

        /* --- Scenario 2: acquisition state --- */
        setHeroText('Ваш следующий шаг', 'Выберите тренера и запишитесь на первую тренировку');
        renderAcquisitionHero();
        hideMyTrainerBlock();
        renderQuickStrip('new-client', null);
        hideUpcomingSection();
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
        if (!initData) {
          setStateMessage('', '');
          hideNextBookingSkeleton();
          renderAcquisitionHero();
          renderQuickStrip('new-client', null);
          renderExploreTiles();
          wireAllBookingsLink();
          return;
        }

        /* Render static tiles immediately — they don't need auth data */
        renderExploreTiles();
        wireAllBookingsLink();

        /* Bootstrap API: single round-trip */
        fetch(apiUrl('/client/hub/bootstrap'), { headers: headersJson() })
          .then(jsonOrThrow)
          .then(function(hub) {
            var days = (hub.bookings || {}).days || [];
            var reqs = (hub.requests || {}).items || [];
            applyHubState(days, reqs, hub);
          })
          .catch(function() {
            /* Fallback: parallel individual calls */
            return Promise.all([
              fetch(apiUrl('/client/bookings'), { headers: headersJson() }).then(jsonOrThrow),
              fetch(apiUrl('/client/requests'), { headers: headersJson() }).then(jsonOrThrow),
              fetch(apiUrl('/client/session'), { headers: headersJson() }).then(jsonOrThrow).catch(function() { return {}; }),
            ]).then(function(results) {
              var sess = results[2] || {};
              applyHubState(
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
          });
      }

      loadAll();
    })();
