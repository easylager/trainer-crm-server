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

      /** From GET /client/hub/bootstrap `client_session` — выбранный в каталоге/боте тренер. */
      var clientHubSession = { selected_trainer_id: null };

      var HUB_UPCOMING_MAX = 6;

      /* Same icon set / sizing as trainer-home hub tiles */
      var ICONS = {
        search: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>',
        cal: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
        inbox: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
        ticket: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2"/><path d="M13 11v2"/><path d="M13 17v2"/></svg>',
      };

      var TILES = [
        { path: 'catalog', label: 'Тренеры и запись', hint: 'Каталог, фильтры, запись', icon: 'search', badge: null },
        { path: 'client-bookings', label: 'Мои записи', hint: 'Все занятия на одной странице', icon: 'cal', badge: null },
        { path: 'client-requests', label: 'Заявки и отклики', hint: 'Подбор тренера', icon: 'inbox', badge: 'NEW' },
        { path: 'client-passes-certificates', label: 'Абонементы', hint: 'Остаток, сроки, покупка', icon: 'ticket', badge: null },
      ];

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
        var url = webappBasePath() + pathWithQuery;
        window.location.href = withInit(url);
      }

      function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;');
      }

      function formatDateShort(iso) {
        if (!iso) return '';
        var d = iso.slice(0, 10).split('-');
        if (d.length !== 3) return iso;
        return d[2] + '.' + d[1] + '.' + d[0];
      }

      function dayHeaderLine(day) {
        var dateStr = formatDateShort(day.date);
        var lab = (day.day_label || '').trim();
        if (dateStr && lab) return dateStr + ' (' + lab + ')';
        return dateStr || lab || '';
      }

      function parseDateTime(dateStr, timeStr) {
        var d = (dateStr || '').slice(0, 10).split('-');
        var t = (timeStr || '00:00').slice(0, 5).split(':');
        if (d.length !== 3) return new Date(0);
        return new Date(
          parseInt(d[0], 10),
          parseInt(d[1], 10) - 1,
          parseInt(d[2], 10),
          parseInt(t[0], 10) || 0,
          parseInt(t[1], 10) || 0
        );
      }

      /** Flatten grouped days into chronological list of { b, day, start }. */
      function flattenBookings(days) {
        var out = [];
        (days || []).forEach(function(day) {
          (day.bookings || []).forEach(function(b) {
            out.push({
              b: b,
              day: day,
              start: parseDateTime(day.date, b.start_time),
            });
          });
        });
        out.sort(function(a, b) { return a.start - b.start; });
        return out;
      }

      function clearClientHubStatsSkeleton() {
        var wrap = document.getElementById('hubStats');
        if (!wrap) return;
        wrap.classList.remove('hub-stats--loading', 'hub-stats--reveal');
        ['statTodayValue', 'statWeekValue', 'statRequestsValue'].forEach(function(id) {
          var el = document.getElementById(id);
          if (el) el.classList.remove('hub-skel-shimmer', 'hub-stat-skel');
        });
      }

      function showClientHubStatsSkeleton() {
        var wrap = document.getElementById('hubStats');
        if (!wrap || !initData) return;
        wrap.classList.remove('hub-stats--reveal');
        wrap.style.display = 'grid';
        wrap.setAttribute('aria-hidden', 'true');
        wrap.classList.add('hub-stats--loading');
        ['statTodayValue', 'statWeekValue', 'statRequestsValue'].forEach(function(id) {
          var el = document.getElementById(id);
          if (el) {
            el.textContent = '\u00a0';
            el.classList.add('hub-skel-shimmer', 'hub-stat-skel');
          }
        });
      }

      function setStats(todayCount, weekCount, requestCount) {
        var wrap = document.getElementById('hubStats');
        if (!wrap || !initData) {
          if (wrap) wrap.style.display = 'none';
          return;
        }
        clearClientHubStatsSkeleton();
        wrap.style.display = 'grid';
        wrap.setAttribute('aria-hidden', 'false');
        document.getElementById('statTodayValue').textContent = String(todayCount);
        document.getElementById('statWeekValue').textContent = String(weekCount);
        document.getElementById('statRequestsValue').textContent = String(requestCount);
        requestAnimationFrame(function() {
          requestAnimationFrame(function() {
            wrap.classList.add('hub-stats--reveal');
          });
        });
      }

      /** Fade + slight lift when replacing skeleton with bookings / empty state (perceived smoothness). */
      function revealBookingsBlock(innerHtml) {
        var block = document.getElementById('bookingsBlock');
        if (!block) return;
        block.innerHTML = '<div class="hub-bookings-mount">' + innerHtml + '</div>';
        var mount = block.firstElementChild;
        if (!mount) return;
        requestAnimationFrame(function() {
          requestAnimationFrame(function() {
            mount.classList.add('hub-bookings-mount--visible');
          });
        });
      }

      function addDaysToYmd(ymd, deltaDays) {
        var p = ymd.split('-');
        var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
        d.setDate(d.getDate() + deltaDays);
        return d.getFullYear() + '-' +
          String(d.getMonth() + 1).padStart(2, '0') + '-' +
          String(d.getDate()).padStart(2, '0');
      }

      function computeStats(days, requestItems) {
        var now = new Date();
        var todayStr = now.getFullYear() + '-' +
          String(now.getMonth() + 1).padStart(2, '0') + '-' +
          String(now.getDate()).padStart(2, '0');
        /* «На неделе» = записи на датах от сегодня до +7 календарных дней включительно (8 дней).
           Раньше было today…today+6 (7 дней) — запись на восьмой день (напр. вс vs сб недели) не попадала в счётчик. */
        var weekLastStr = addDaysToYmd(todayStr, 7);
        var todayCount = 0;
        var weekCount = 0;
        (days || []).forEach(function(day) {
          var ds = (day.date || '').slice(0, 10);
          if (!ds) return;
          var n = (day.bookings || []).length;
          if (ds === todayStr) todayCount += n;
          if (ds >= todayStr && ds <= weekLastStr) weekCount += n;
        });
        var reqCount = (requestItems || []).filter(function(r) {
          return String(r.status || '').toLowerCase() !== 'archived';
        }).length;
        return { todayCount: todayCount, weekCount: weekCount, requestCount: reqCount };
      }

      function openTelegramDmMiniApp(username, telegramId) {
        if (window.openTelegramChatFromMiniApp) {
          return window.openTelegramChatFromMiniApp({
            username: username,
            telegramId: telegramId,
          });
        }
        return false;
      }

      function hubClientCanWriteTrainer(b) {
        var tid = b.trainer_telegram_id;
        var un = (b.trainer_telegram_username || '').replace(/^@/, '').trim();
        return (tid != null && tid !== '') || !!un;
      }

      function renderBookingsStrip(days) {
        var block = document.getElementById('bookingsBlock');
        if (!block) return;
        var flat = flattenBookings(days);
        var count = 0;
        var parts = [];
        (days || []).forEach(function(day) {
          if (count >= HUB_UPCOMING_MAX) return;
          var bs = day.bookings || [];
          if (!bs.length) return;
          parts.push('<div class="hub-day-label">' + escapeHtml(dayHeaderLine(day)) + '</div>');
          parts.push('<div class="hub-bookings-stack">');
          bs.forEach(function(b) {
            if (count >= HUB_UPCOMING_MAX) return;
            var st = String(b.status || '').toLowerCase();
            var pending = st === 'pending';
            var statusClass = pending ? 'booked booked-pending' : 'booked booked-confirmed';
            var rowMod = pending ? 'slot-booking-pending' : 'slot-booking-confirmed';
            var statusLabel = pending ? 'ожидает' : 'подтверждено';
            var place = ((b.arena_name || b.place_display || '') + '').trim() || 'Место уточните у тренера';
            var msgBtn = '';
            if (hubClientCanWriteTrainer(b)) {
              msgBtn =
                '<button type="button" class="hub-slot-msg" data-hub-dm="client"' +
                ' data-dm-un="' + escapeHtml((b.trainer_telegram_username || '').replace(/^@/, '')) + '"' +
                ' data-dm-tid="' + escapeHtml(b.trainer_telegram_id != null ? String(b.trainer_telegram_id) : '') + '"' +
                ' aria-label="Написать тренеру в Telegram" title="Написать в Telegram">' +
                '<svg class="hub-slot-msg-icon" viewBox="0 0 24 24" aria-hidden="true">' +
                '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>' +
                '</svg>' +
                '</button>';
            }
            parts.push(
              '<div class="slot-row slot-booked-click ' + rowMod + '" data-bid="' + escapeHtml(String(b.id)) + '">' +
                '<div class="slot-row-main">' +
                  '<div class="slot-time">' + escapeHtml((b.start_time || '') + ' · ' + (b.duration_minutes || 45) + ' мин') + '</div>' +
                  '<div class="slot-trainer">' + escapeHtml(b.trainer_name || 'Тренер') + '</div>' +
                  '<div class="slot-place">' + escapeHtml(place) + '</div>' +
                '</div>' +
                '<div class="slot-meta-col">' +
                  '<span class="slot-status ' + statusClass + '">' + statusLabel + '</span>' +
                  msgBtn +
                '</div>' +
              '</div>'
            );
            count++;
          });
          parts.push('</div>');
        });
        if (!count) {
          var hasSelTrainer = clientHubSession.selected_trainer_id != null && clientHubSession.selected_trainer_id !== '';
          var ctaFindTrainer = hasSelTrainer ? 'Мой тренер' : 'Найти тренера';
          revealBookingsBlock(
            '<div class="hub-empty">Нет предстоящих записей.<br><button type="button" class="bd-btn bd-btn--primary" id="btnHubToCatalog" style="margin-top:14px">' +
              escapeHtml(ctaFindTrainer) +
              '</button></div>'
          );
          block.onclick = null;
          var bc = document.getElementById('btnHubToCatalog');
          if (bc) bc.onclick = function() { navigateTo('catalog'); };
          return;
        }
        var total = flat.length;
        var cap = '';
        if (total > HUB_UPCOMING_MAX) {
          cap = '<div class="hub-bookings-cap">Показаны ' + HUB_UPCOMING_MAX + ' из ' + total + ' записей</div>';
        }
        revealBookingsBlock(parts.join('') + cap);
        var bblock = document.getElementById('bookingsBlock');
        if (bblock && window.wireHubSlotMessageButtons) {
          try {
            window.wireHubSlotMessageButtons(bblock);
          } catch (e) { /* noop */ }
        }
        block.onclick = function(ev) {
          var msgBtn = ev.target && ev.target.closest && ev.target.closest('button.hub-slot-msg[data-hub-dm]');
          if (msgBtn) {
            ev.preventDefault();
            ev.stopPropagation();
            openTelegramDmMiniApp(msgBtn.getAttribute('data-dm-un'), msgBtn.getAttribute('data-dm-tid'));
            return;
          }
          var row = ev.target && ev.target.closest && ev.target.closest('.slot-row[data-bid]');
          if (!row) return;
          var bid = row.getAttribute('data-bid');
          if (bid) navigateTo('client-bookings?open_booking=' + encodeURIComponent(bid));
        };
      }

      function renderTiles() {
        var grid = document.getElementById('hubGrid');
        grid.innerHTML = TILES.map(function(t) {
          var ic = ICONS[t.icon] || ICONS.cal;
          var badgeHtml = t.badge ? '<div class="hub-tile-badge">' + escapeHtml(t.badge) + '</div>' : '';
          return (
            '<button type="button" class="hub-tile" data-path="' + escapeHtml(t.path) + '">' +
              '<div class="hub-tile-inner">' +
                '<div class="hub-tile-top">' + ic + badgeHtml + '</div>' +
                '<div class="hub-tile-content">' +
                  '<div class="hub-tile-label">' + escapeHtml(t.label) + '</div>' +
                  '<div class="hub-tile-hint">' + escapeHtml(t.hint) + '</div>' +
                '</div>' +
              '</div>' +
            '</button>'
          );
        }).join('');
        grid.querySelectorAll('.hub-tile').forEach(function(btn) {
          btn.onclick = function() { navigateTo(btn.getAttribute('data-path')); };
        });
      }

      function setupQuickGrid() {
        document.getElementById('hubQuickGrid').querySelectorAll('.hub-quick-action').forEach(function(btn) {
          btn.onclick = function() {
            var a = btn.getAttribute('data-action');
            if (a === 'catalog') navigateTo('catalog');
            else if (a === 'bookings') navigateTo('client-bookings');
          };
        });
      }

      function setStateMessage(text, kind) {
        var el = document.getElementById('stateMessage');
        if (!text) {
          el.style.display = 'none';
          el.textContent = '';
          return;
        }
        el.textContent = text;
        el.className = 'state-panel ' + (kind === 'error' ? 'error' : 'loading');
        el.style.display = 'block';
      }

      /** Skeleton rows while client bookings + requests load (same pattern as trainer-home hub). */
      function buildClientHubBookingsSkeletonHtml() {
        var parts = [
          '<div class="hub-bookings-skel" role="status" aria-busy="true" aria-label="Загрузка записей">',
        ];
        for (var i = 0; i < 3; i++) {
          parts.push(
            '<div class="hub-skel-row">' +
              '<div class="hub-skel-line hub-skel-line--time hub-skel-shimmer" aria-hidden="true"></div>' +
              '<div style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;">' +
                '<div class="hub-skel-line hub-skel-line--primary hub-skel-shimmer" aria-hidden="true"></div>' +
                '<div class="hub-skel-line hub-skel-line--secondary hub-skel-shimmer" aria-hidden="true"></div>' +
              '</div>' +
            '</div>'
          );
        }
        parts.push('</div>');
        return parts.join('');
      }

      function loadAll() {
        if (!initData) {
          setStateMessage('', '');
          clearClientHubStatsSkeleton();
          document.getElementById('hubStats').style.display = 'none';
          document.getElementById('bookingsBlock').innerHTML = '<div class="hub-empty">Авторизация Telegram недоступна в этом режиме.</div>';
          renderTiles();
          setupQuickGrid();
          return;
        }
        setStateMessage('', '');
        document.getElementById('bookingsBlock').innerHTML = buildClientHubBookingsSkeletonHtml();
        showClientHubStatsSkeleton();

        function jsonOrThrow(r) {
          return r.json().then(function(d) {
            if (!r.ok) throw new Error(d.detail || r.statusText);
            return d;
          });
        }

        function applyHubPayload(bookingsData, reqData, hubMeta) {
          var cs = (hubMeta && hubMeta.client_session) || {};
          clientHubSession.selected_trainer_id =
            cs.selected_trainer_id != null && cs.selected_trainer_id !== '' ? cs.selected_trainer_id : null;
          var days = bookingsData.days || [];
          var requestItems = reqData.items || [];
          setStateMessage('', '');
          var st = computeStats(days, requestItems);
          setStats(st.todayCount, st.weekCount, st.requestCount);
          renderBookingsStrip(days);
          renderTiles();
          setupQuickGrid();
        }

        fetch(apiUrl('/client/hub/bootstrap'), { headers: headersJson() })
          .then(jsonOrThrow)
          .then(function(hub) {
            applyHubPayload(hub.bookings || {}, hub.requests || {}, hub);
          })
          .catch(function() {
            return Promise.all([
              fetch(apiUrl('/client/bookings'), { headers: headersJson() }).then(jsonOrThrow),
              fetch(apiUrl('/client/requests'), { headers: headersJson() }).then(jsonOrThrow),
              fetch(apiUrl('/client/session'), { headers: headersJson() })
                .then(jsonOrThrow)
                .catch(function() {
                  return {};
                }),
            ]).then(function(results) {
              var sess = results[2] || {};
              applyHubPayload(results[0], results[1], {
                client_session: { selected_trainer_id: sess.trainer_id != null ? sess.trainer_id : null },
              });
            });
          })
          .catch(function() {
            setStateMessage('Не удалось загрузить данные. Проверьте сеть и откройте страницу из клиентского бота.', 'error');
            document.getElementById('bookingsBlock').innerHTML = '';
            var hs = document.getElementById('hubStats');
            clearClientHubStatsSkeleton();
            hs.style.display = 'none';
            hs.setAttribute('aria-hidden', 'true');
          });
      }

      renderTiles();
      setupQuickGrid();
      loadAll();
    })();
