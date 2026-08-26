    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        if (typeof tg.ready === 'function') tg.ready();
        if (typeof tg.expand === 'function') tg.expand();
        if (typeof window.__applyTrainerClientsTheme === 'function') {
          window.__applyTrainerClientsTheme();
        }
        try {
          var darkUi = tg.colorScheme === 'dark';
          var bgHex = darkUi ? '#0d1515' : '#F4F2EC';
          if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
          if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
        } catch (e) { /* older clients */ }
        if (tg.onEvent) {
          tg.onEvent('themeChanged', function () {
            if (typeof window.__applyTrainerClientsTheme === 'function') {
              window.__applyTrainerClientsTheme();
            }
            try {
              var du = tg.colorScheme === 'dark';
              var bg = du ? '#0d1515' : '#F4F2EC';
              if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bg);
              if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bg);
            } catch (err) { /* ignore */ }
          });
        }
      }
      /** Telegram can populate WebApp.initData after our deferred script runs — read fresh each time (see schedule-editor). */
      function getTrainerWebAppInitData() {
        var wtg = window.Telegram && window.Telegram.WebApp;
        return wtg && wtg.initData ? wtg.initData : '';
      }
      var headerTitleEl = document.querySelector('.header-title');
      var defaultHeaderTitle = headerTitleEl ? headerTitleEl.textContent : '';

      function withInit(url) {
        var id = getTrainerWebAppInitData();
        if (!id) return url;
        return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(id);
      }

      function phoneFromTcAddClientNationalField() {
        var el = document.getElementById('tcAddClientPhone');
        if (window.CrmPhoneField && el) return CrmPhoneField.getE164(el) || '';
        return '';
      }
      function validatePhoneTrainerClientFromField() {
        var el = document.getElementById('tcAddClientPhone');
        if (window.CrmPhoneField && el) return CrmPhoneField.validate(el);
        return { ok: false, e164: '', error: 'Укажите номер телефона.' };
      }
      (function wireTcAddClientPhoneMask() {
        if (window.CrmPhoneField) CrmPhoneField.initAll(document.getElementById('tcModalAddClient') || document);
      })();
      function setAddClientErr(msg) {
        var el = document.getElementById('tcAddClientErr');
        if (!el) return;
        if (msg) {
          el.textContent = msg;
          el.hidden = false;
        } else {
          el.textContent = '';
          el.hidden = true;
        }
      }
      function closeAddClientModal() {
        var m = document.getElementById('tcModalAddClient');
        if (!m) return;
        m.style.display = 'none';
        m.setAttribute('aria-hidden', 'true');
        setAddClientErr('');
      }
      function openAddClientModal() {
        var m = document.getElementById('tcModalAddClient');
        if (!m) return;
        var pe = document.getElementById('tcAddClientPhone');
        var fe = document.getElementById('tcAddClientFirst');
        var le = document.getElementById('tcAddClientLast');
        var me = document.getElementById('tcAddClientMiddle');
        if (pe && window.CrmPhoneField) CrmPhoneField.setE164(pe, '');
        else if (pe) pe.value = '';
        if (fe) fe.value = '';
        if (le) le.value = '';
        if (me) me.value = '';
        setAddClientErr('');
        m.style.display = 'flex';
        m.setAttribute('aria-hidden', 'false');
        setTimeout(function() {
          if (pe) pe.focus();
        }, 120);
      }

      var state = {
        allClients: [],
        filteredClients: [],
        selectedClientId: null,
        /** True after we handled ?client_id= via /card prefetch (avoid waiting for full list). */
        deepLinkPrefetchDone: false,
        /** From schedule-editor: reopen same booking after visiting profile. */
        returnBookingId: null,
        returnFromHub: false,
        /** From trainer-groups: reopen group detail after visiting client card. */
        returnGroupId: null,
        /** While GET /trainer/clients is in flight — list shows skeleton (stable layout). */
        clientsListLoading: false,
        /** Deep link ?focus=invite_bot — list clients without telegram_id + banner (e.g. saved link). */
        focusInviteBot: false,
        /** List API segment filters (combined server-side). */
        filterRecurringOnly: false,
        filterInBot: null,
        filterMinBookings2: false,
        filterHasPass: false,
        filterTier: null,
        clientsSearchDebounce: null,
        /** Incremented on each history fetch — stale responses after quick-book must not repaint UI. */
        clientHistoryLoadGen: 0,
        /** ``?client_id=&open_write=1`` → open relay/DM after card merge (trainer bot CRM write). */
        pendingOpenWriteForClientId: null,
      };

      /** Consume deep-link flag; prefers merged /card row for relay-ready fields. */
      function finalizePendingOpenWriteModal(clientId, preferredSnapshot) {
        if (state.pendingOpenWriteForClientId !== clientId) return;
        state.pendingOpenWriteForClientId = null;
        setTimeout(function() {
          var c = state.allClients.find(function(x) { return x.id === clientId; }) || preferredSnapshot;
          if (c) openTrainerClientTelegramDm(c);
        }, 160);
      }
      function initReturnContextFromQuery() {
        try {
          var p = new URLSearchParams(window.location.search || '');
          var rb = p.get('return_booking');
          var rf = p.get('return_from');
          state.returnFromHub = rf === 'hub';
          state.returnBookingId = null;
          state.returnGroupId = null;
          if (rb) {
            var bid = parseInt(rb, 10);
            if (!isNaN(bid) && bid > 0) state.returnBookingId = bid;
          }
          if (rf === 'groups') {
            var gid = p.get('group_id');
            if (gid) {
              var gidi = parseInt(gid, 10);
              if (!isNaN(gidi) && gidi > 0) state.returnGroupId = gidi;
            }
          }
          var ow = p.get('open_write');
          var cidOw = p.get('client_id');
          if (ow === '1' && cidOw) {
            var idOw = parseInt(cidOw, 10);
            if (!isNaN(idOw) && idOw > 0) state.pendingOpenWriteForClientId = idOw;
          }
        } catch (e) { /* noop */ }
      }

      function navigateToScheduleBooking() {
        if (!state.returnBookingId) return;
        var path = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
        var u = path + 'schedule-editor?open_booking=' + encodeURIComponent(String(state.returnBookingId));
        if (state.returnFromHub) u += '&from=hub';
        var idNav = getTrainerWebAppInitData();
        if (idNav) u += (u.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(idNav);
        window.location.href = u;
      }

      function canBrowserGoBack() {
        try {
          if (window.navigation && typeof window.navigation.canGoBack === 'function') {
            return window.navigation.canGoBack();
          }
        } catch (e) {}
        return window.history && window.history.length > 1;
      }

      function backToListFromDetail() {
        document.getElementById('clientsSection').style.display = 'block';
        setInviteBotCompactListUi(!!state.focusInviteBot);
        document.getElementById('detailSection').style.display = 'none';
        state.selectedClientId = null;
        document.body.classList.remove('client-detail-mode');
        if (typeof renderList === 'function' && !state.clientsListLoading) {
          renderList();
        }
        if (headerTitleEl) headerTitleEl.textContent = defaultHeaderTitle || 'Мои клиенты';
        syncTrainerClientsHeaderBack();
      }

      function navigateToTrainerGroupDetail() {
        if (!state.returnGroupId) return;
        var path = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
        var u = path + 'trainer-groups?id=' + encodeURIComponent(String(state.returnGroupId));
        var idNav2 = getTrainerWebAppInitData();
        if (idNav2) u += (u.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(idNav2);
        window.location.href = u;
      }

      function syncTrainerClientsHeaderBack() {
        var btn = document.getElementById('btnBack');
        if (!btn) return;
        var detailVisible = document.getElementById('detailSection').style.display !== 'none';
        if (detailVisible && state.returnBookingId) {
          btn.hidden = false;
          btn.onclick = function() { navigateToScheduleBooking(); };
          return;
        }
        if (detailVisible && state.returnGroupId) {
          btn.hidden = false;
          btn.onclick = function() { navigateToTrainerGroupDetail(); };
          return;
        }
        if (detailVisible) {
          var retReqId = null;
          try {
            var rawR = sessionStorage.getItem('miniapp_return_trainer_requests_detail');
            if (rawR) {
              var parsed = JSON.parse(rawR);
              if (typeof parsed === 'number' && !isNaN(parsed) && parsed > 0) {
                retReqId = parsed;
              } else if (
                parsed &&
                typeof parsed.request_id === 'number' &&
                parsed.request_id > 0 &&
                typeof parsed.client_id === 'number' &&
                parsed.client_id > 0 &&
                state.selectedClientId === parsed.client_id
              ) {
                retReqId = parsed.request_id;
              }
            }
          } catch (eR) { /* noop */ }
          if (retReqId != null) {
            btn.hidden = false;
            btn.onclick = function() {
              try {
                sessionStorage.removeItem('miniapp_return_trainer_requests_detail');
              } catch (eRm) { /* noop */ }
              var pathR = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
              var uR = pathR + 'trainer-requests?request_id=' + encodeURIComponent(String(retReqId));
              var idR = getTrainerWebAppInitData();
              if (idR) uR += (uR.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(idR);
              window.location.href = uR;
            };
            return;
          }
          btn.hidden = false;
          btn.onclick = function() { backToListFromDetail(); };
          return;
        }
        btn.hidden = !canBrowserGoBack();
        btn.onclick = function() { window.history.back(); };
      }

      function updateReturnBookingBackUi() {
        syncTrainerClientsHeaderBack();
      }

      function setStateMessage(text, kind) {
        var el = document.getElementById('stateMessage');
        var inner = el && el.querySelector('.state-panel-inner');
        if (!text) {
          if (el) {
            el.style.display = 'none';
            el.className = 'loading state-panel';
          }
          if (inner) inner.textContent = '';
          return;
        }
        if (!el) return;
        if (inner) inner.textContent = text;
        el.className = (kind === 'error' ? 'error' : 'loading') + ' state-panel';
        el.style.display = 'block';
      }

      var tcToastHideTimer = null;
      function showTcToast(text) {
        var t = (text || '').trim();
        if (!t) return;
        var el = document.getElementById('tcToast');
        if (!el) {
          el = document.createElement('div');
          el.id = 'tcToast';
          el.className = 'tc-toast';
          el.setAttribute('role', 'status');
          el.setAttribute('aria-live', 'polite');
          document.body.appendChild(el);
        }
        el.textContent = t;
        el.hidden = false;
        if (tcToastHideTimer) clearTimeout(tcToastHideTimer);
        tcToastHideTimer = setTimeout(function() {
          el.hidden = true;
          tcToastHideTimer = null;
        }, 4000);
        try {
          if (tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred) {
            tg.HapticFeedback.notificationOccurred('success');
          }
        } catch (e) { /* older clients */ }
      }

      /** After quick-book, refresh «Следующее» on the open client card without full reload. */
      function refreshClientNextBookingBlock(clientId) {
        if (clientId == null || clientId === '') return;
        fetch(withInit('/api/webapp/trainer/clients/' + encodeURIComponent(clientId) + '/next-booking'), {
          cache: 'no-store',
        })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            var nextEl = document.getElementById('clientNextBooking');
            if (!nextEl) return;
            var nb = data.next_booking;
            var upcomingCount = typeof data.upcoming_count === 'number' ? data.upcoming_count : 0;
            if (nb && nb.slot_date) {
              var t = formatDate(nb.slot_date) + (nb.start_time ? ' ' + formatTime(nb.start_time) : '');
              if (nb.arena_name) t += ' · ' + nb.arena_name;
              if (upcomingCount > 1) t += ' (+' + (upcomingCount - 1) + ' ещё)';
              nextEl.classList.remove('is-loading');
              nextEl.textContent = t;
            } else {
              nextEl.classList.remove('is-loading');
              nextEl.textContent = '—';
            }
          })
          .catch(function() {
            var nextEl = document.getElementById('clientNextBooking');
            if (nextEl) {
              nextEl.classList.remove('is-loading');
              nextEl.textContent = '—';
            }
          });
      }

      /** History + next booking on open card (after quick-book; avoids duplicate fetch logic). */
      function refreshClientCardBookingsUi(clientId) {
        if (clientId == null || clientId === '') return;
        loadClientHistory(clientId);
        refreshClientNextBookingBlock(clientId);
      }

      (function tcClientQuickBookModule() {
        /* In-page quick booking from client card (same idea as hub; no schedule-editor). */
        var PRICE_TIER_LABEL_RU = {
          child: 'Детский',
          adult: 'Взрослый',
          two_children: '2 ребенка',
          two_adults: '2 взрослых',
          adult_and_child: 'Взрослый + ребенок',
        };
      
        function api(path) {
          return withInit('/api/webapp' + path);
        }
      
        var qb = {
          lockedClientId: null,
          clientDisplayName: '',
          slotsForDay: [],
          slotsIsoDate: null,
          scheduleGrid: null,
          fetchGen: 0,
          refreshTimer: null,
          slotDate: null,
          startMinutes: null,
          durationM: 45,
          bookServices: [],
          bookServiceId: null,
          bookPriceVariantId: null,
          bookArenaId: null,
          trainerArenas: [],
          awaitingConfirm: false,
          /** Background fetch when opening «Записать» — same defaults as step 2 (latest booking by created_at). */
          bookingDefaultsPrefetch: null,
          bookingDefaultsPrefetchGen: 0,
          bookContexts: null,
          bookContextKind: 'personal_slot',
          bookCollectiveSlug: null,
          centerSession: null,
          centerSessions: [],
        };
      
        function todayIsoLocal() {
          var d = new Date();
          var m = String(d.getMonth() + 1);
          var day = String(d.getDate());
          if (m.length < 2) m = '0' + m;
          if (day.length < 2) day = '0' + day;
          return String(d.getFullYear()) + '-' + m + '-' + day;
        }
      
        function parseStartToMinutes(startTime) {
          var s = (startTime == null ? '' : String(startTime)).trim();
          var parts = s.split(':');
          var h = parseInt(parts[0], 10);
          var min = parts.length > 1 ? parseInt(parts[1], 10) : 0;
          if (isNaN(h)) h = 0;
          if (isNaN(min)) min = 0;
          return h * 60 + min;
        }
      
        function formatMinuteClock(totalMinutes) {
          var m = Math.max(0, Math.floor(totalMinutes));
          var h = Math.floor(m / 60);
          var rem = m % 60;
          return String(h).padStart(2, '0') + ':' + String(rem).padStart(2, '0');
        }
      
        function intervalsOverlapAbsolute(a0, a1, b0, b1) {
          return a0 < b1 && b0 < a1;
        }
      
        function slotIntervalMinutesFromRow(s) {
          var sm = parseStartToMinutes(s.start_time);
          var em = parseStartToMinutes(s.end_time);
          if (em <= sm) em = sm + 60;
          return { start: sm, end: em };
        }
      
        function defaultScheduleGrid() {
          return {
            kind: 'uniform_step',
            minute_offset: 0,
            hour_start: 6,
            hour_end: 23,
            step_minutes: 15,
            slot_duration_minutes: null,
          };
        }

        function tcFixedSlotDurationMinutes() {
          var p = qb.scheduleGrid || defaultScheduleGrid();
          if (p.slot_duration_minutes == null || p.slot_duration_minutes === '') return null;
          var n = parseInt(p.slot_duration_minutes, 10);
          if (isNaN(n) || n < 15) return null;
          return Math.min(24 * 60, n);
        }

        function tcEnsureDurationSelectOption(selectEl, minutes) {
          if (!selectEl || minutes == null) return;
          var v = String(minutes);
          if (selectEl.querySelector('option[value="' + v + '"]')) return;
          var o = document.createElement('option');
          o.value = v;
          o.textContent = minutes + ' минут';
          selectEl.appendChild(o);
        }

        function setTcQuickBookDatetimeLoading(on) {
          var wrap = document.getElementById('tcQuickBookDatetimeLoadingWrap');
          var modal = document.getElementById('tcModalQuickBookDatetime');
          if (wrap) wrap.classList.toggle('tc-qb-datetime-loading-wrap--loading', !!on);
          if (modal) modal.setAttribute('aria-busy', on ? 'true' : 'false');
        }

        function syncTcQuickBookDurationFromGrid() {
          var stack = document.getElementById('tcQuickBookDurationStack');
          var hint = document.getElementById('tcQuickBookDurationFixedHint');
          var durEl = document.getElementById('tcQuickBookDuration');
          var loadWrap = document.getElementById('tcQuickBookDatetimeLoadingWrap');
          if (!durEl) return;
          var fixed = tcFixedSlotDurationMinutes();
          if (loadWrap) loadWrap.classList.toggle('tc-qb-datetime-wrap--duration-custom', fixed == null);
          if (fixed != null) {
            tcEnsureDurationSelectOption(durEl, fixed);
            durEl.value = String(fixed);
            durEl.disabled = true;
            if (stack) stack.style.display = 'none';
            if (hint) {
              hint.removeAttribute('hidden');
              hint.textContent = 'Длительность: ' + fixed + ' мин (зафиксировано для площадки).';
              hint.setAttribute('aria-hidden', 'false');
            }
          } else {
            durEl.disabled = false;
            if (stack) stack.style.display = '';
            if (hint) {
              hint.setAttribute('hidden', 'hidden');
              hint.textContent = '';
              hint.setAttribute('aria-hidden', 'true');
            }
          }
        }
      
        function applyScheduleGrid(data) {
          if (data && data.schedule_grid) qb.scheduleGrid = data.schedule_grid;
          else if (!qb.scheduleGrid) qb.scheduleGrid = defaultScheduleGrid();
          syncTcQuickBookDurationFromGrid();
        }
      
        function allowedStartMinutesFromGrid() {
          var preset = qb.scheduleGrid || defaultScheduleGrid();
          var kind = (preset.kind || 'uniform_step').toString().trim();
          var h0 = Math.max(0, Math.min(23, parseInt(preset.hour_start, 10)));
          if (isNaN(h0)) h0 = 6;
          var h1 = Math.max(0, Math.min(23, parseInt(preset.hour_end, 10)));
          if (isNaN(h1)) h1 = 23;
          if (h1 < h0) {
            var swap = h0;
            h0 = h1;
            h1 = swap;
          }
          var out = [];
          if (kind === 'hourly_minute') {
            var mo = Math.max(0, Math.min(59, parseInt(preset.minute_offset, 10) || 0));
            for (var h = h0; h <= h1; h++) out.push(h * 60 + mo);
            return out;
          }
          var step = 15;
          if (kind === 'uniform_step') {
            var s = parseInt(preset.step_minutes, 10);
            if (!isNaN(s) && [10, 15, 30, 60].indexOf(s) >= 0) step = s;
          }
          for (var mm = h0 * 60; mm <= h1 * 60; mm += step) out.push(mm);
          return out;
        }
      
        function setHint(text, visible) {
          var el = document.getElementById('tcQuickBookHint');
          if (!el) return;
          var on = !!(visible && text);
          el.textContent = on ? String(text) : '';
          el.classList.toggle('is-on', on);
          el.setAttribute('aria-hidden', on ? 'false' : 'true');
        }
      
        function quickBookSlotAvailability(slotsForDay, startMinutes, durationMinutes, isoDate) {
          var dm = durationMinutes || 45;
          var newEnd = startMinutes + dm;
          if (newEnd > 24 * 60) return 'invalid';
          var todayStr = todayIsoLocal();
          if (isoDate === todayStr) {
            var now = new Date();
            var nowM = now.getHours() * 60 + now.getMinutes();
            if (startMinutes < nowM) return 'past';
          }
          var rows = (slotsForDay || []).filter(function(s) {
            return (s.status || '').toLowerCase() !== 'cancelled';
          });
          for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var iv = slotIntervalMinutesFromRow(row);
            if (!intervalsOverlapAbsolute(startMinutes, newEnd, iv.start, iv.end)) continue;
            var cap = row.capacity != null ? parseInt(row.capacity, 10) : 1;
            if (isNaN(cap) || cap < 1) cap = 1;
            var occ = row.active_bookings != null ? parseInt(row.active_bookings, 10) : 0;
            if (cap > 1) return 'group';
            if (occ >= 1) return 'busy';
            // Empty individual slot — quick-book replaces/removes overlaps on save; do not block UI.
            continue;
          }
          return 'free';
        }
      
        function rebuildTimeSelect(isoDate, dm) {
          var sel = document.getElementById('tcQuickBookTime');
          var btnGo = document.getElementById('tcQuickBookContinue');
          if (!sel || !isoDate) return false;
          var prev = sel.value;
          sel.innerHTML = '';
          var anyFree = false;
          var mins = allowedStartMinutesFromGrid();
          mins.forEach(function(m) {
            var opt = document.createElement('option');
            var availability = quickBookSlotAvailability(qb.slotsForDay, m, dm, isoDate);
            opt.value = String(m);
            if (availability === 'free') {
              opt.textContent = formatMinuteClock(m);
              anyFree = true;
            } else if (availability === 'past') {
              opt.textContent = formatMinuteClock(m) + ' — прошло';
              opt.disabled = true;
            } else if (availability === 'busy') {
              opt.textContent = formatMinuteClock(m) + ' — занято';
              opt.disabled = true;
            } else if (availability === 'group') {
              opt.textContent = formatMinuteClock(m) + ' — группа';
              opt.disabled = true;
            } else if (availability === 'overlap') {
              opt.textContent = formatMinuteClock(m) + ' — пересечение';
              opt.disabled = true;
            } else {
              opt.textContent = formatMinuteClock(m) + ' — не влезает';
              opt.disabled = true;
            }
            sel.appendChild(opt);
          });
          var prevOpt = sel.querySelector('option[value="' + prev + '"]:not([disabled])');
          if (prevOpt) sel.value = prev;
          else {
            var firstOk = sel.querySelector('option:not([disabled])');
            if (firstOk) sel.value = firstOk.value;
          }
          if (btnGo) btnGo.disabled = !anyFree;
          if (!anyFree) {
            setHint('Нет доступного времени для выбранной длительности.', true);
          } else {
            setHint('', false);
          }
          return anyFree;
        }
      
        function refreshTimeOptions(isoDate, opts) {
          opts = opts || {};
          var silentLoadingHint = !!opts.silentLoadingHint;
          var sel = document.getElementById('tcQuickBookTime');
          var durEl = document.getElementById('tcQuickBookDuration');
          var btnGo = document.getElementById('tcQuickBookContinue');
          if (!sel || !isoDate) return Promise.resolve();
          var fixedDm = tcFixedSlotDurationMinutes();
          var dm =
            fixedDm != null
              ? fixedDm
              : durEl
                ? parseInt(durEl.value, 10)
                : 45;
          if (fixedDm == null && (isNaN(dm) || dm < 15)) dm = 45;
          if (qb.slotsIsoDate === isoDate) {
            rebuildTimeSelect(isoDate, dm);
            setTcQuickBookDatetimeLoading(false);
            return Promise.resolve();
          }
          var fetchGen = ++qb.fetchGen;
          sel.disabled = true;
          if (btnGo) btnGo.disabled = true;
          setTcQuickBookDatetimeLoading(true);
          if (!silentLoadingHint) {
            setHint('Загрузка сетки расписания…', true);
          }
          return fetch(
            api('/schedule?from_date=' + encodeURIComponent(isoDate) + '&to_date=' + encodeURIComponent(isoDate)),
            { headers: {} }
          )
            .then(function(r) {
              if (!r.ok) return Promise.reject(new Error('schedule'));
              return r.json();
            })
            .then(function(data) {
              if (fetchGen !== qb.fetchGen) return;
              applyScheduleGrid(data);
              var slots = (data && data.slots) ? data.slots : [];
              qb.slotsForDay = slots.filter(function(s) {
                var d = s.slot_date;
                return d === isoDate || String(d) === isoDate;
              });
              qb.slotsIsoDate = isoDate;
              rebuildTimeSelect(isoDate, dm);
              sel.disabled = false;
              setTcQuickBookDatetimeLoading(false);
            })
            .catch(function() {
              if (fetchGen !== qb.fetchGen) return;
              applyScheduleGrid(null);
              qb.slotsForDay = [];
              qb.slotsIsoDate = null;
              sel.disabled = false;
              sel.innerHTML = '';
              allowedStartMinutesFromGrid().forEach(function(m) {
                var opt = document.createElement('option');
                opt.value = String(m);
                opt.textContent = formatMinuteClock(m);
                sel.appendChild(opt);
              });
              if (btnGo) btnGo.disabled = false;
              setHint('Не удалось проверить занятость. Время можно выбрать вручную.', true);
              setTcQuickBookDatetimeLoading(false);
            });
        }
      
        function scheduleRefresh() {
          if (qb.refreshTimer) clearTimeout(qb.refreshTimer);
          qb.refreshTimer = setTimeout(function() {
            qb.refreshTimer = null;
            var dateEl = document.getElementById('tcQuickBookDate');
            var iso = dateEl ? String(dateEl.value || '').trim() : '';
            if (iso) refreshTimeOptions(iso);
          }, 250);
        }
      
        function closeDatetimeModal() {
          var m = document.getElementById('tcModalQuickBookDatetime');
          if (!m) return;
          setTcQuickBookDatetimeLoading(false);
          if (qb.refreshTimer) {
            clearTimeout(qb.refreshTimer);
            qb.refreshTimer = null;
          }
          qb.fetchGen += 1;
          m.style.display = 'none';
          m.setAttribute('aria-hidden', 'true');
        }

        function closeContextModal() {
          var m = document.getElementById('tcModalQuickBookContext');
          if (!m) return;
          m.style.display = 'none';
          m.setAttribute('aria-hidden', 'true');
        }

        function closeCenterModal() {
          var m = document.getElementById('tcModalQuickBookCenter');
          if (!m) return;
          m.style.display = 'none';
          m.setAttribute('aria-hidden', 'true');
        }
      
        function closeServiceModal() {
          var m = document.getElementById('tcModalQuickBookService');
          if (!m) return;
          m.style.display = 'none';
          m.setAttribute('aria-hidden', 'true');
        }
      
        function closeConfirmModal() {
          var m = document.getElementById('tcModalBookConfirm');
          if (!m) return;
          m.style.display = 'none';
          m.setAttribute('aria-hidden', 'true');
          qb.awaitingConfirm = false;
        }
      
        function closeAll() {
          closeConfirmModal();
          closeServiceModal();
          closeCenterModal();
          closeContextModal();
          closeDatetimeModal();
          qb.bookingDefaultsPrefetchGen += 1;
          qb.bookingDefaultsPrefetch = null;
          qb.lockedClientId = null;
          qb.clientDisplayName = '';
          qb.bookContextKind = 'personal_slot';
          qb.bookCollectiveSlug = null;
          qb.centerSession = null;
          qb.centerSessions = [];
        }
      
        function priceTierLabelRu(tier) {
          var k = (tier.tier_kind || '').toLowerCase();
          return PRICE_TIER_LABEL_RU[k] || tier.label || 'Тариф';
        }
      
        function pickDefaultBookPriceTierId(tiers) {
          if (!tiers || !tiers.length) return null;
          if (tiers.length === 1) return tiers[0].id;
          var adult = tiers.filter(function(t) {
            return (t.tier_kind || '').toLowerCase() === 'adult';
          })[0];
          return adult ? adult.id : tiers[0].id;
        }

        function resolveTcPriceTierIdFromDefaults(tiers, preferredVariantId, priceTierKind) {
          if (!tiers || !tiers.length) return null;
          if (tiers.length === 1) return tiers[0].id;
          var pref = preferredVariantId != null ? parseInt(String(preferredVariantId), 10) : NaN;
          if (!isNaN(pref) && tiers.some(function(t) { return Number(t.id) === pref; })) return pref;
          var tk = (priceTierKind || '').toString().trim().toLowerCase();
          if (tk) {
            var hit = tiers.filter(function(t) {
              return (t.tier_kind || '').toString().trim().toLowerCase() === tk;
            })[0];
            if (hit) return hit.id;
          }
          return null;
        }

        function syncPriceTierRadios(preferredVariantId, priceTierKind) {
          var wrap = document.getElementById('tcQbProfilePriceTierWrap');
          var host = document.getElementById('tcQbProfilePriceTierRadios');
          if (!wrap || !host) return;
          var sid = qb.bookServiceId;
          var svc = (qb.bookServices || []).filter(function(x) {
            return Number(x.id) === Number(sid);
          })[0];
          var tiers = svc && svc.price_tiers ? svc.price_tiers : [];
          if (tiers.length <= 1) {
            wrap.style.display = 'none';
            qb.bookPriceVariantId = tiers.length === 1 ? tiers[0].id : null;
            return;
          }
          wrap.style.display = 'block';
          host.innerHTML = '';
          var gname = 'tc_qb_prof_' + String(sid || 0);
          tiers.forEach(function(tier) {
            var lab = document.createElement('label');
            lab.style.display = 'flex';
            lab.style.alignItems = 'center';
            lab.style.gap = '10px';
            lab.style.marginBottom = '8px';
            var inp = document.createElement('input');
            inp.type = 'radio';
            inp.name = gname;
            inp.value = String(tier.id);
            var pb = Number(tier.price_byn);
            if (!isFinite(pb)) pb = 0;
            var numStr = pb === Math.floor(pb) ? String(Math.floor(pb)) : pb.toFixed(2);
            var priceFrag = document.createElement('span');
            priceFrag.textContent = numStr + ' BYN';
            lab.appendChild(inp);
            lab.appendChild(document.createTextNode(priceTierLabelRu(tier) + ' — '));
            lab.appendChild(priceFrag);
            inp.addEventListener('change', function() {
              qb.bookPriceVariantId = parseInt(inp.value, 10);
            });
            host.appendChild(lab);
          });
          var resolved = resolveTcPriceTierIdFromDefaults(tiers, preferredVariantId, priceTierKind);
          var matched = resolved != null ? host.querySelector('input[value="' + String(resolved) + '"]') : null;
          if (matched) {
            matched.checked = true;
            qb.bookPriceVariantId = parseInt(matched.value, 10);
          } else {
            var pid = pickDefaultBookPriceTierId(tiers);
            var pickInp = pid != null ? host.querySelector('input[value="' + String(pid) + '"]') : null;
            if (pickInp) {
              pickInp.checked = true;
              qb.bookPriceVariantId = parseInt(pickInp.value, 10);
            }
          }
        }
      
        function formatSlotWhenLabel() {
          if (!qb.slotDate || qb.startMinutes == null) return '';
          var p = (qb.slotDate || '').split('-');
          var ru = p.length === 3 ? p[2] + '.' + p[1] + '.' + p[0] : qb.slotDate;
          return ru + ' ' + formatMinuteClock(qb.startMinutes);
        }
      
        function applyTcQuickBookServiceStep(servicesPayload, defaults) {
          qb.bookServices = servicesPayload.services || [];
          if (!qb.bookServices.length) {
            showTcToast('Добавьте услугу в профиле');
            closeDatetimeModal();
            return;
          }
          qb.trainerArenas = servicesPayload.arenas || [];
          var arenas = qb.trainerArenas || [];
          var primary = arenas.filter(function(a) {
            return a.is_primary;
          })[0];
          qb.bookArenaId = primary ? primary.id : arenas.length ? arenas[0].id : null;
          if (defaults.arena_id != null) {
            var da = parseInt(defaults.arena_id, 10);
            if (!isNaN(da) && arenas.some(function(a) { return Number(a.id) === da; })) {
              qb.bookArenaId = da;
            }
          }

          var sel = document.getElementById('tcQbProfileServiceSelect');
          if (!sel) return;
          sel.innerHTML = '';
          qb.bookServices.forEach(function(s) {
            var opt = document.createElement('option');
            opt.value = String(s.id);
            opt.textContent = s.name || '—';
            sel.appendChild(opt);
          });
          var defSid = defaults.service_id != null ? parseInt(defaults.service_id, 10) : NaN;
          var picked = qb.bookServices.length ? Number(qb.bookServices[0].id) : null;
          if (!isNaN(defSid) && qb.bookServices.some(function(s) {
            return Number(s.id) === defSid;
          })) {
            picked = defSid;
          }
          qb.bookServiceId = picked;
          sel.value = picked != null ? String(picked) : '';
          sel.onchange = function() {
            qb.bookServiceId = this.value ? parseInt(this.value, 10) : null;
            syncPriceTierRadios(null, null);
          };

          var wrapA = document.getElementById('tcQbProfileArenaWrap');
          var selA = document.getElementById('tcQbProfileArenaSelect');
          if (wrapA && selA) {
            var showA = arenas.length > 1;
            wrapA.style.display = showA ? 'block' : 'none';
            if (showA) {
              selA.innerHTML = '';
              arenas.forEach(function(a) {
                var o = document.createElement('option');
                o.value = String(a.id);
                o.textContent = (a.name || '—') + (a.is_primary ? ' · основная' : '');
                selA.appendChild(o);
              });
              selA.value = qb.bookArenaId != null ? String(qb.bookArenaId) : '';
              selA.onchange = function() {
                qb.bookArenaId = this.value ? parseInt(this.value, 10) : null;
              };
            }
          }

          var defVid = defaults.service_price_variant_id != null ? parseInt(defaults.service_price_variant_id, 10) : null;
          syncPriceTierRadios(defVid, defaults.price_tier_kind);

          var ms = document.getElementById('tcModalQuickBookService');
          if (ms) {
            ms.style.display = 'flex';
            ms.setAttribute('aria-hidden', 'false');
          }
          closeDatetimeModal();
        }

        function openServiceStepAfterDatetime() {
          var cid = qb.lockedClientId;
          if (!cid) return;

          var pf = qb.bookingDefaultsPrefetch;
          if (pf && pf.clientId === cid && pf.servicesPayload && pf.defaults) {
            qb.bookingDefaultsPrefetch = null;
            applyTcQuickBookServiceStep(pf.servicesPayload, pf.defaults);
            return;
          }

          Promise.all([
            fetch(api('/trainer/my-services'), { headers: {}, cache: 'no-store' }).then(function(r) {
              return r.ok ? r.json() : Promise.reject(new Error('svc'));
            }),
            fetch(api('/trainer/clients/' + encodeURIComponent(cid) + '/booking-defaults'), {
              headers: {},
              cache: 'no-store',
            }).then(function(r) {
              return r.ok ? r.json() : Promise.reject(new Error('def'));
            }),
          ])
            .then(function(results) {
              applyTcQuickBookServiceStep(results[0], results[1]);
            })
            .catch(function() {
              showTcToast('Не удалось загрузить услуги');
            });
        }
      
        function openConfirm() {
          var name = qb.clientDisplayName || 'Клиент';
          var slotLabel = formatSlotWhenLabel();
          var txt = document.getElementById('tcBookConfirmText');
          if (txt) txt.textContent = 'Записать ' + name + ' на ' + slotLabel + '?';
          var m = document.getElementById('tcModalBookConfirm');
          if (m) {
            m.style.display = 'flex';
            m.setAttribute('aria-hidden', 'false');
          }
          qb.awaitingConfirm = true;
        }
      
        function postQuickBooking() {
          var clientId = qb.lockedClientId;
          var serviceId = qb.bookServiceId;
          if (clientId == null || serviceId == null) return Promise.reject(new Error('Нет данных'));
          var payload = {
            slot_date: qb.slotDate,
            start_time: formatMinuteClock(qb.startMinutes),
            duration_minutes: qb.durationM || 45,
            client_id: clientId,
            service_id: serviceId,
          };
          if (qb.trainerArenas && qb.trainerArenas.length > 1 && qb.bookArenaId != null) {
            payload.arena_id = qb.bookArenaId;
          }
          if (qb.bookPriceVariantId != null) {
            payload.service_price_variant_id = qb.bookPriceVariantId;
          }
          return fetch(api('/trainer/booking/quick'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          }).then(function(r) {
            return r.json().then(function(o) {
              if (r.ok) return o;
              var d = o.detail;
              var msg = Array.isArray(d) ? (d[0] && d[0].msg) || 'Ошибка' : (d || 'Ошибка');
              throw new Error(typeof msg === 'string' ? msg : 'Ошибка');
            });
          });
        }
      
        function openDatetimeStep() {
          var modal = document.getElementById('tcModalQuickBookDatetime');
          var dateEl = document.getElementById('tcQuickBookDate');
          var durEl = document.getElementById('tcQuickBookDuration');
          if (!modal || !dateEl || !durEl) {
            alert('Не удалось открыть форму записи. Обновите страницу.');
            return;
          }
          closeContextModal();
          closeCenterModal();
          setTcQuickBookDatetimeLoading(true);
          var today = todayIsoLocal();
          dateEl.min = today;
          if (!dateEl.value || dateEl.value < today) dateEl.value = today;
          if (!durEl.value) durEl.value = '45';
          syncTcQuickBookDurationFromGrid();
          setHint('', false);
          closeServiceModal();
          closeConfirmModal();
          modal.style.display = 'flex';
          modal.setAttribute('aria-hidden', 'false');
          refreshTimeOptions(dateEl.value || today, { silentLoadingHint: true });
        }

        function tcContinueAfterContext() {
          if (qb.bookContextKind === 'center_session') {
            openCenterBookingStep();
            return;
          }
          openDatetimeStep();
        }

        function tcApplyContextSelection(ctx, clientId) {
          if (window.TrainerBookingContext) {
            var applied = TrainerBookingContext.applyContext(ctx);
            qb.bookContextKind = applied.kind;
            qb.bookCollectiveSlug = applied.collective_slug;
            if (clientId != null) {
              TrainerBookingContext.rememberContextForClient(clientId, applied.context_id);
            }
            return;
          }
          qb.bookContextKind = (ctx && ctx.kind) || 'personal_slot';
          qb.bookCollectiveSlug = (ctx && ctx.collective_slug) || null;
        }

        function tcApplyContextAndContinue(ctxPayload, clientId, forcePicker) {
          qb.bookContexts = ctxPayload;
          if (window.TrainerBookingContext) {
            var normalized = TrainerBookingContext.normalizePayload(ctxPayload);
            if (!forcePicker && !TrainerBookingContext.needsContextPicker(normalized)) {
              tcApplyContextSelection(normalized.contexts[0], clientId);
              tcContinueAfterContext();
              return;
            }
            if (!forcePicker) {
              var resolved = TrainerBookingContext.resolveInitialContext(normalized, clientId);
              if (resolved) {
                tcApplyContextSelection(resolved, clientId);
                tcContinueAfterContext();
                return;
              }
            }
            openContextStep(normalized, clientId);
            return;
          }
          if (ctxPayload && ctxPayload.needs_context_picker) {
            openContextStep(ctxPayload, clientId);
            return;
          }
          tcContinueAfterContext();
        }

        function renderTcQuickBookContextStep(payload, clientId) {
          var wrap = document.getElementById('tcQuickBookContextActions');
          if (!wrap) return;
          if (window.TrainerBookingContext) {
            TrainerBookingContext.renderPicker(wrap, payload, {
              escapeHtml: escapeHtml,
              attrPrefix: 'data-tc-book',
              slugAttr: 'data-collective-slug',
              clientId: clientId,
              onSelect: function(ctx) {
                tcApplyContextSelection(ctx, clientId);
                closeContextModal();
                tcContinueAfterContext();
              },
            });
            return;
          }
          var contexts = (payload && payload.contexts) || [];
          wrap.innerHTML = contexts.map(function(ctx) {
            return (
              '<button type="button" class="btn-book-option" data-tc-book-kind="' + escapeHtml(ctx.kind) + '" data-collective-slug="' + escapeHtml(ctx.collective_slug || '') + '">' +
                '<span class="btn-book-option-body"><span class="btn-book-option-text">' + escapeHtml(ctx.label) + '</span></span>' +
                '<span class="btn-book-option-arrow" aria-hidden="true">›</span>' +
              '</button>'
            );
          }).join('');
          wrap.querySelectorAll('[data-tc-book-kind]').forEach(function(btn) {
            btn.onclick = function() {
              tcApplyContextSelection({
                kind: btn.getAttribute('data-tc-book-kind') || 'personal_slot',
                context_id: 'manual',
                collective_slug: btn.getAttribute('data-collective-slug') || null,
              }, clientId);
              closeContextModal();
              tcContinueAfterContext();
            };
          });
        }

        function openContextStep(payload, clientId) {
          var modal = document.getElementById('tcModalQuickBookContext');
          if (!modal) {
            tcContinueAfterContext();
            return;
          }
          renderTcQuickBookContextStep(payload, clientId);
          modal.style.display = 'flex';
          modal.setAttribute('aria-hidden', 'false');
        }

        function renderTcCenterModePickers() {
          var session = qb.centerSession;
          var modeWrap = document.getElementById('tcQuickBookCenterModeWrap');
          var coachWrap = document.getElementById('tcQuickBookCenterCoachWrap');
          var modeSel = document.getElementById('tcQuickBookCenterMode');
          var coachSel = document.getElementById('tcQuickBookCenterCoach');
          var confirmBtn = document.getElementById('tcQuickBookCenterConfirm');
          if (!session || !modeSel) return;
          modeSel.innerHTML = ['lane_self', 'center_coach_individual'].map(function(m) {
            return '<option value="' + m + '">' + (m === 'lane_self' ? 'Дорожка' : 'С тренером центра') + '</option>';
          }).join('');
          if (modeWrap) modeWrap.style.display = '';
          if (coachWrap && coachSel) {
            var coaches = session.coaches || [];
            coachSel.innerHTML = coaches.map(function(c) {
              return '<option value="' + c.trainer_id + '">' + escapeHtml(c.display_name || ('Тренер #' + c.trainer_id)) + '</option>';
            }).join('');
            coachWrap.style.display = modeSel.value.indexOf('coach') >= 0 && coaches.length ? '' : 'none';
            modeSel.onchange = function() {
              coachWrap.style.display = modeSel.value.indexOf('coach') >= 0 && coaches.length ? '' : 'none';
            };
          }
          if (confirmBtn) confirmBtn.style.display = '';
        }

        function openCenterBookingStep() {
          closeContextModal();
          var modal = document.getElementById('tcModalQuickBookCenter');
          var list = document.getElementById('tcQuickBookCenterSessions');
          var lead = document.getElementById('tcQuickBookCenterLead');
          var slug = qb.bookCollectiveSlug;
          if (!modal || !slug) {
            showTcToast('Не выбран контекст центра');
            return;
          }
          if (lead) lead.textContent = (qb.clientDisplayName || 'Клиент') + ' — выберите окно центра';
          if (list) list.innerHTML = '<p class="book-choice-lead">Загрузка окон…</p>';
          modal.style.display = 'flex';
          modal.setAttribute('aria-hidden', 'false');
          fetch(api('/trainer/collective/staff-booking-sessions?collective_slug=' + encodeURIComponent(slug)), {
            headers: {},
            cache: 'no-store',
          })
            .then(function(r) {
              return r.json().then(function(d) {
                if (!r.ok) throw new Error((d && d.detail) || 'Ошибка');
                return d;
              });
            })
            .then(function(data) {
              qb.centerSessions = data.sessions || [];
              if (!qb.centerSessions.length) {
                if (list) list.innerHTML = '<p class="error">Нет доступных окон</p>';
                return;
              }
              if (list) {
                list.innerHTML = qb.centerSessions.map(function(s) {
                  return (
                    '<button type="button" class="client-row" data-session-id="' + s.id + '">' +
                      escapeHtml((s.slot_date || '') + ' ' + (s.start_time || '') + '–' + (s.end_time || '')) +
                    '</button>'
                  );
                }).join('');
                list.querySelectorAll('[data-session-id]').forEach(function(row) {
                  row.onclick = function() {
                    var sid = parseInt(row.getAttribute('data-session-id'), 10);
                    qb.centerSession = qb.centerSessions.filter(function(x) { return Number(x.id) === sid; })[0] || null;
                    renderTcCenterModePickers();
                  };
                });
              }
            })
            .catch(function(e) {
              if (list) list.innerHTML = '<p class="error">' + escapeHtml(e.message || 'Ошибка') + '</p>';
            });
        }

        function submitTcCenterStaffBooking() {
          var clientId = qb.lockedClientId;
          var session = qb.centerSession;
          var modeSel = document.getElementById('tcQuickBookCenterMode');
          var coachSel = document.getElementById('tcQuickBookCenterCoach');
          if (!clientId || !session || !modeSel || !qb.bookCollectiveSlug) return;
          var payload = {
            collective_slug: qb.bookCollectiveSlug,
            session_id: session.id,
            client_id: clientId,
            attendance_mode: modeSel.value,
            guest_count: 0,
          };
          if (modeSel.value.indexOf('coach') >= 0 && coachSel && coachSel.value) {
            payload.center_coach_id = parseInt(coachSel.value, 10);
          }
          fetch(api('/trainer/collective/staff-session-booking'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          })
            .then(function(r) {
              return r.json().then(function(d) {
                if (!r.ok) throw new Error((d && d.detail) || 'Ошибка');
                return d;
              });
            })
            .then(function() {
              closeAll();
              showTcToast('Запись в центр создана');
              if (typeof refreshClientCardBookingsUi === 'function') {
                refreshClientCardBookingsUi(clientId);
              }
            })
            .catch(function(e) {
              showTcToast(e.message || 'Ошибка');
            });
        }

        var wired = false;
        function wireOnce() {
          if (wired) return;
          wired = true;
      
          var qCancel = document.getElementById('tcQuickBookCancel');
          if (qCancel) {
            qCancel.onclick = function() {
              closeAll();
            };
          }
          var ctxCancel = document.getElementById('tcQuickBookContextCancel');
          if (ctxCancel) ctxCancel.onclick = function() { closeAll(); };
          var centerBack = document.getElementById('tcQuickBookCenterBack');
          if (centerBack) {
            centerBack.onclick = function() {
              closeCenterModal();
              if (qb.bookContexts && qb.bookContexts.needs_context_picker) {
                openContextStep(qb.bookContexts, qb.lockedClientId);
              } else {
                closeAll();
              }
            };
          }
          var centerConfirm = document.getElementById('tcQuickBookCenterConfirm');
          if (centerConfirm) centerConfirm.onclick = submitTcCenterStaffBooking;
          var qContinue = document.getElementById('tcQuickBookContinue');
          if (qContinue) {
            qContinue.onclick = function() {
              var dateEl = document.getElementById('tcQuickBookDate');
              var timeEl = document.getElementById('tcQuickBookTime');
              var durEl = document.getElementById('tcQuickBookDuration');
              if (!dateEl || !timeEl || !durEl) return;
              var slotDate = String(dateEl.value || '').trim();
              var startMinutes = parseInt(String(timeEl.value || ''), 10);
              var fixedDur = tcFixedSlotDurationMinutes();
              var duration =
                fixedDur != null ? fixedDur : parseInt(String(durEl.value || '45'), 10);
              if (!slotDate) {
                showTcToast('Выберите дату.');
                return;
              }
              if (isNaN(startMinutes)) {
                showTcToast('Выберите время начала.');
                return;
              }
              if (fixedDur == null && (isNaN(duration) || duration < 15)) duration = 45;
              var availability = quickBookSlotAvailability(qb.slotsForDay || [], startMinutes, duration, slotDate);
              if (availability !== 'free') {
                if (availability === 'past') showTcToast('Это время уже прошло.');
                else if (availability === 'busy') showTcToast('Это время занято. Выберите другое.');
                else if (availability === 'group') showTcToast('На это время есть групповой слот.');
                else if (availability === 'overlap') showTcToast('Время пересекается со слотом.');
                else showTcToast('Слот не подходит по длительности.');
                scheduleRefresh();
                return;
              }
              qb.slotDate = slotDate;
              qb.startMinutes = startMinutes;
              qb.durationM = duration;
              openServiceStepAfterDatetime();
            };
          }
          var qDate = document.getElementById('tcQuickBookDate');
          if (qDate) {
            qDate.onchange = function() {
              scheduleRefresh();
            };
          }
          var qDuration = document.getElementById('tcQuickBookDuration');
          if (qDuration) {
            qDuration.onchange = function() {
              scheduleRefresh();
            };
          }
          var qOverlay = document.getElementById('tcModalQuickBookDatetime');
          if (qOverlay) {
            qOverlay.onclick = function(ev) {
              if (ev.target === qOverlay) closeAll();
            };
          }
      
          var btnSvcGo = document.getElementById('tcQbProfileContinue');
          if (btnSvcGo) {
            btnSvcGo.onclick = function() {
              var sel = document.getElementById('tcQbProfileServiceSelect');
              qb.bookServiceId = sel && sel.value ? parseInt(sel.value, 10) : null;
              if (qb.bookServiceId == null) {
                showTcToast('Выберите услугу');
                return;
              }
              closeServiceModal();
              openConfirm();
            };
          }
          var btnSvcBack = document.getElementById('tcQbProfileBack');
          if (btnSvcBack) {
            btnSvcBack.onclick = function() {
              closeServiceModal();
              var mq = document.getElementById('tcModalQuickBookDatetime');
              if (mq) {
                mq.style.display = 'flex';
                mq.setAttribute('aria-hidden', 'false');
              }
              var iso = qb.slotDate || todayIsoLocal();
              var dateEl = document.getElementById('tcQuickBookDate');
              if (dateEl && qb.slotDate) dateEl.value = qb.slotDate;
              refreshTimeOptions(iso, { silentLoadingHint: true });
            };
          }
          var svcOverlay = document.getElementById('tcModalQuickBookService');
          if (svcOverlay) {
            svcOverlay.onclick = function(ev) {
              if (ev.target === svcOverlay) closeAll();
            };
          }
      
          var cNo = document.getElementById('tcBookConfirmNo');
          if (cNo) {
            cNo.onclick = function() {
              if (qb.awaitingConfirm) {
                closeConfirmModal();
                var ms = document.getElementById('tcModalQuickBookService');
                if (ms) {
                  ms.style.display = 'flex';
                  ms.setAttribute('aria-hidden', 'false');
                }
                return;
              }
              closeAll();
            };
          }
          var cYes = document.getElementById('tcBookConfirmYes');
          if (cYes) {
            cYes.onclick = function() {
              var btn = cYes;
              var cid = qb.lockedClientId;
              btn.disabled = true;
              postQuickBooking()
                .then(function() {
                  var rid = cid != null && cid !== '' ? cid : state.selectedClientId;
                  closeAll();
                  showTcToast('Запись создана');
                  if (rid != null && rid !== '') {
                    refreshClientCardBookingsUi(rid);
                  }
                })
                .catch(function(e) {
                  alert(e.message || 'Ошибка сети');
                })
                .finally(function() {
                  btn.disabled = false;
                });
            };
          }
          var cOverlay = document.getElementById('tcModalBookConfirm');
          if (cOverlay) {
            cOverlay.onclick = function(ev) {
              if (ev.target !== cOverlay) return;
              if (qb.awaitingConfirm) {
                closeConfirmModal();
                var ms = document.getElementById('tcModalQuickBookService');
                if (ms) {
                  ms.style.display = 'flex';
                  ms.setAttribute('aria-hidden', 'false');
                }
                return;
              }
              closeAll();
            };
          }
        }
      
        function open(clientId, displayName) {
          wireOnce();
          qb.lockedClientId = clientId;
          qb.clientDisplayName = (displayName || '').trim() || 'Клиент';
          qb.slotsForDay = [];
          qb.slotsIsoDate = null;
          qb.scheduleGrid = null;
          qb.fetchGen += 1;
          qb.slotDate = null;
          qb.startMinutes = null;
          qb.durationM = 45;
          qb.bookServices = [];
          qb.bookServiceId = null;
          qb.bookPriceVariantId = null;
          qb.bookArenaId = null;
          qb.trainerArenas = [];
          qb.awaitingConfirm = false;
          qb.bookingDefaultsPrefetch = null;
          qb.bookingDefaultsPrefetchGen += 1;
          var prefetchSnap = qb.bookingDefaultsPrefetchGen;
          var prefetchCid = clientId;
          qb.bookContextKind = 'personal_slot';
          qb.bookCollectiveSlug = null;
          qb.centerSession = null;
          qb.centerSessions = [];
          qb.bookContexts = null;
          Promise.all([
            fetch(api('/trainer/my-services'), { headers: {}, cache: 'no-store' }),
            fetch(api('/trainer/clients/' + encodeURIComponent(prefetchCid) + '/booking-defaults'), {
              headers: {},
              cache: 'no-store',
            }),
            fetch(api('/trainer/booking-contexts'), { headers: {}, cache: 'no-store' }),
          ])
            .then(function(rs) {
              return Promise.all(
                rs.map(function(r, idx) {
                  if (idx === 2 && !r.ok) return { contexts: [{ kind: 'personal_slot', label: 'Личное расписание' }], needs_context_picker: false };
                  return r.ok ? r.json() : Promise.reject(new Error('prefetch'));
                })
              );
            })
            .then(function(results) {
              if (prefetchSnap !== qb.bookingDefaultsPrefetchGen) return;
              if (qb.lockedClientId !== prefetchCid) return;
              qb.bookingDefaultsPrefetch = {
                clientId: prefetchCid,
                servicesPayload: results[0],
                defaults: results[1],
              };
              qb.bookContexts = results[2];
            })
            .catch(function() {
              /* Step 2 will fetch if prefetch fails or initData was late. */
            });

          fetch(api('/trainer/booking-contexts'), { headers: {}, cache: 'no-store' })
            .then(function(r) {
              return r.ok ? r.json() : { contexts: [{ kind: 'personal_slot', label: 'Личное расписание' }], needs_context_picker: false };
            })
            .then(function(ctxPayload) {
              if (qb.lockedClientId !== clientId) return;
              tcApplyContextAndContinue(ctxPayload, clientId, false);
            })
            .catch(function() {
              openDatetimeStep();
            });
        }
      
        window.TcClientQuickBook = { open: open };
      })();

      function formatDate(d) {
        if (!d) return '—';
        var dt = new Date(d);
        if (isNaN(dt.getTime())) return d.toString().slice(0, 10);
        var day = String(dt.getDate()).padStart(2, '0');
        var month = String(dt.getMonth() + 1).padStart(2, '0');
        var year = dt.getFullYear();
        return day + '.' + month + '.' + year;
      }

      function formatTime(t) {
        if (!t) return '';
        // backend likely returns \"HH:MM:SS\" or \"HH:MM\"
        return t.toString().slice(0, 5);
      }

      function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/\"/g, '&quot;')
          .replace(/'/g, '&#39;');
      }

      var CLIENT_TIER_BADGE_LABELS = {
        child: 'Детский',
        adult: 'Взрослый',
        two_children: '2 детей',
        two_adults: '2 взрослых',
        adult_and_child: 'Парное',
      };

      function hasActiveClientListFilters() {
        return !!(
          state.filterRecurringOnly ||
          state.filterInBot !== null ||
          state.filterMinBookings2 ||
          state.filterHasPass ||
          state.filterTier
        );
      }

      function buildClientsListQueryString() {
        var parts = [];
        if (state.filterRecurringOnly) parts.push('recurring_only=true');
        if (state.filterInBot === true) parts.push('in_bot=true');
        if (state.filterInBot === false) parts.push('in_bot=false');
        if (state.filterMinBookings2) parts.push('min_bookings=2');
        if (state.filterHasPass) parts.push('has_pass=true');
        if (state.filterTier) parts.push('tier=' + encodeURIComponent(state.filterTier));
        var q = (document.getElementById('searchInput') && document.getElementById('searchInput').value || '').trim();
        if (q) parts.push('q=' + encodeURIComponent(q));
        return parts.join('&');
      }

      function syncClientFilterChipsUi() {
        var root = document.getElementById('tcClientFilters');
        if (!root) return;
        root.querySelectorAll('.tc-chip-filter[data-filter]').forEach(function(btn) {
          var kind = btn.getAttribute('data-filter');
          var val = btn.getAttribute('data-value');
          var active = false;
          if (kind === 'in_bot') active = state.filterInBot === (val === 'true');
          else if (kind === 'min_bookings') active = state.filterMinBookings2;
          else if (kind === 'recurring') active = state.filterRecurringOnly;
          else if (kind === 'has_pass') active = state.filterHasPass;
          else if (kind === 'tier') active = state.filterTier === val;
          btn.classList.toggle('is-active', active);
          btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
      }

      function onClientFilterChipClick(btn) {
        var kind = btn.getAttribute('data-filter');
        var val = btn.getAttribute('data-value');
        if (kind === 'in_bot') {
          var want = val === 'true';
          state.filterInBot = state.filterInBot === want ? null : want;
        } else if (kind === 'min_bookings') {
          state.filterMinBookings2 = !state.filterMinBookings2;
        } else if (kind === 'recurring') {
          state.filterRecurringOnly = !state.filterRecurringOnly;
        } else if (kind === 'has_pass') {
          state.filterHasPass = !state.filterHasPass;
        } else if (kind === 'tier' && val) {
          state.filterTier = state.filterTier === val ? null : val;
        }
        syncClientFilterChipsUi();
        loadClientsInternal();
      }

      function applyFilter() {
        if (state.clientsSearchDebounce) clearTimeout(state.clientsSearchDebounce);
        state.clientsSearchDebounce = setTimeout(function() {
          loadClientsInternal();
        }, 280);
      }

      function refreshClientListView() {
        state.filteredClients = state.allClients.slice();
        renderList();
      }

      function hideInviteBotBanner() {
        var b = document.getElementById('tcListFocusBanner');
        if (b) b.hidden = true;
      }

      /** Invite-bot focus: list-only screen (no search / add client). Mirrors html.tc-invite-bot-compact from inline boot script. */
      function setInviteBotCompactListUi(on) {
        var root = document.documentElement;
        if (on) root.classList.add('tc-invite-bot-compact');
        else root.classList.remove('tc-invite-bot-compact');
        var sb = document.querySelector('.search-box');
        var bar = document.querySelector('.tc-add-client-bar');
        if (sb) sb.style.display = on ? 'none' : '';
        if (bar) bar.style.display = on ? 'none' : '';
      }

      function postClientInviteLinkFirstCopyRecorded() {
        if (!getTrainerWebAppInitData()) return;
        fetch(withInit('/api/webapp/trainer/welcome-link/first-copy'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }).catch(function() {});
      }

      /** Same permanent link as hub paperclip (GET /trainer/hub/universal-invite-link → welcome_ref_{id}). */
      function fetchTrainerUniversalInviteLink() {
        return fetch(withInit('/api/webapp/trainer/hub/universal-invite-link'), {
          headers: { 'Content-Type': 'application/json' },
        }).then(function(r) {
          return r.json().then(function(o) {
            if (!r.ok) throw new Error((o && o.detail) || r.statusText || 'Ошибка');
            var link = o && o.link ? String(o.link).trim() : '';
            return { link: link || null };
          });
        });
      }

      function pluralRuClients(n) {
        var n10 = n % 10;
        var n100 = n % 100;
        if (n10 === 1 && n100 !== 11) return 'клиент';
        if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return 'клиента';
        return 'клиентов';
      }

      /** Prefetched welcome_ref link — copy on click without async gap (Telegram WebView clipboard policy). */
      var tcWelcomeInviteLinkPrefetch = null;

      function copyTextForTrainerMiniApp(text) {
        var rt = window.MiniAppRuntime;
        if (rt && typeof rt.copyTextToClipboard === 'function') {
          return rt.copyTextToClipboard(text);
        }
        return Promise.resolve(false);
      }

      function prefetchTcWelcomeInviteLink() {
        return fetchTrainerUniversalInviteLink()
          .then(function (o) {
            var link = o && o.link;
            if (link) tcWelcomeInviteLinkPrefetch = String(link);
            return link || null;
          })
          .catch(function () {
            return null;
          });
      }

      function showInviteBotBannerUi(count) {
        var b = document.getElementById('tcListFocusBanner');
        if (!b) return;
        b.hidden = false;
        var text = b.querySelector('.tc-list-focus-banner__text');
        if (text) {
          text.textContent =
            'Показаны ' +
            count +
            ' ' +
            pluralRuClients(count) +
            ' без Telegram в боте. «Скопировать ссылку» — та же пригласительная ссылка, что по кнопке со скрепкой на «Главной». Отправьте её каждому в чат; после перехода пришлём уведомление в бот тренера.';
        }
      }

      function wireInviteBotBannerActions() {
        var btnAll = document.getElementById('tcListFocusShowAll');
        if (btnAll && !btnAll.dataset.wiredInviteFocus) {
          btnAll.dataset.wiredInviteFocus = '1';
          btnAll.onclick = function() {
            state.focusInviteBot = false;
            state.filterInBot = null;
            hideInviteBotBanner();
            var ds = document.getElementById('detailSection');
            var onDetail = ds && ds.style.display !== 'none';
            if (onDetail) {
              backToListFromDetail();
            } else {
              setInviteBotCompactListUi(false);
            }
            var si = document.getElementById('searchInput');
            if (si) si.value = '';
            syncClientFilterChipsUi();
            loadClientsInternal();
          };
        }
        var btnCopy = document.getElementById('tcListFocusCopyInvite');
        if (btnCopy && !btnCopy.dataset.wiredInviteCopy) {
          btnCopy.dataset.wiredInviteCopy = '1';
          btnCopy.onclick = function() {
            if (btnCopy.disabled) return;
            btnCopy.disabled = true;
            setStateMessage('');

            function finishCopyFail() {
              setStateMessage(
                'Не удалось скопировать автоматически. Откройте «Главная» и скопируйте ссылку по кнопке со скрепкой.',
                'error'
              );
            }

            function runCopy(link) {
              if (!link) {
                setStateMessage('Ссылка недоступна. Откройте мини-приложение из бота тренера.', 'error');
                return Promise.resolve();
              }
              return copyTextForTrainerMiniApp(link).then(function (ok) {
                if (ok) {
                  postClientInviteLinkFirstCopyRecorded();
                  showTcToast('Ссылка скопирована — отправьте её клиентам');
                  return;
                }
                finishCopyFail();
              });
            }

            var cached = tcWelcomeInviteLinkPrefetch;
            if (cached) {
              runCopy(cached).finally(function () {
                btnCopy.disabled = false;
              });
              return;
            }
            fetchTrainerUniversalInviteLink()
              .then(function (o) {
                var link = o && o.link;
                if (link) tcWelcomeInviteLinkPrefetch = String(link);
                return runCopy(link);
              })
              .catch(function (err) {
                setStateMessage((err && err.message) || 'Не удалось получить ссылку.', 'error');
              })
              .finally(function () {
                btnCopy.disabled = false;
              });
          };
        }
      }

      function applyInviteBotFocusAfterLoad() {
        if (!state.allClients.length) {
          state.focusInviteBot = false;
          hideInviteBotBanner();
          setInviteBotCompactListUi(false);
          refreshClientListView();
          showTcToast('Все клиенты уже в боте.');
          return;
        }
        setInviteBotCompactListUi(true);
        showInviteBotBannerUi(state.allClients.length);
        wireInviteBotBannerActions();
        prefetchTcWelcomeInviteLink();
        refreshClientListView();
      }

      function afterClientsLoaded() {
        syncClientFilterChipsUi();
        if (state.focusInviteBot) {
          applyInviteBotFocusAfterLoad();
        } else {
          hideInviteBotBanner();
          setInviteBotCompactListUi(false);
          refreshClientListView();
        }
      }

      function initListFocusFromQuery() {
        try {
          var p = new URLSearchParams(window.location.search || '');
          if (p.get('client_id')) {
            state.focusInviteBot = false;
            return;
          }
          var f = (p.get('focus') || '').trim().toLowerCase();
          state.focusInviteBot = f === 'invite_bot';
          if (state.focusInviteBot) {
            state.filterInBot = false;
            p.delete('focus');
            var qs = p.toString();
            history.replaceState({}, '', window.location.pathname + (qs ? '?' + qs : ''));
          }
        } catch (e) {
          state.focusInviteBot = false;
        }
      }

      function clientInitials(displayName) {
        var s = (displayName || '').trim();
        if (!s) return '?';
        var parts = s.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) {
          var a = parts[0][0];
          var b = parts[parts.length - 1][0];
          return (a + b).toUpperCase();
        }
        if (parts[0].length >= 2) return parts[0].slice(0, 2).toUpperCase();
        return parts[0][0].toUpperCase();
      }

      function trainerClientDisplayName(c) {
        if (!c) return '';
        var parts = [c.first_name, c.middle_name, c.last_name]
          .map(function(x) {
            return (x || '').trim();
          })
          .filter(Boolean);
        return parts.join(' ');
      }

      function buildClientsListSkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        var parts = ['<div class="tc-clients-skel" role="status" aria-busy="true" aria-label="Загрузка клиентов">'];
        for (var i = 0; i < 5; i++) {
          parts.push(
            '<div class="tc-client-skel-card">' +
              '<div class="tc-client-skel-av ' + sk + '" aria-hidden="true"></div>' +
              '<div class="tc-client-skel-main">' +
                '<div class="tc-client-skel-line tc-client-skel-line--name ' + sk + '" aria-hidden="true"></div>' +
                '<div class="tc-client-skel-line tc-client-skel-line--meta ' + sk + '" aria-hidden="true"></div>' +
                '<div class="tc-client-skel-line tc-client-skel-line--meta2 ' + sk + '" aria-hidden="true"></div>' +
              '</div>' +
              '<div class="tc-client-skel-arrow ' + sk + '" aria-hidden="true"></div>' +
            '</div>'
          );
        }
        parts.push('</div>');
        return parts.join('');
      }

      var TC_HISTORY_CHEVRON =
        '<svg class="tc-history-summary__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

      /** Russian plural for booking count in history summary. */
      function formatHistoryCountLabel(n) {
        var abs = Math.abs(parseInt(String(n), 10) || 0);
        var mod10 = abs % 10;
        var mod100 = abs % 100;
        if (mod10 === 1 && mod100 !== 11) return abs + ' занятие';
        if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return abs + ' занятия';
        return abs + ' занятий';
      }

      /** One-line teaser for collapsed history accordion (count + latest visit). */
      function buildHistorySummaryValue(total, items) {
        if (!total) return 'Пока нет прошедших';
        var label = formatHistoryCountLabel(total);
        var latest = items && items[0];
        if (!latest) return label;
        var dateStr = formatDate(latest.slot_date);
        var timeStr = latest.start_time ? formatTime(latest.start_time) : '';
        return label + ' · последнее ' + dateStr + (timeStr ? ' ' + timeStr : '');
      }

      function buildHistoryDetailsShell(summaryValue, bodyHtml, opts) {
        opts = opts || {};
        var openAttr = opts.open ? ' open' : '';
        var loadingCls = opts.loading ? ' tc-history-details--loading' : '';
        var valueCls = 'tc-history-summary__value' + (opts.loading ? ' ma-skel-shimmer' : '');
        var valueInner = opts.loading ? '' : escapeHtml(summaryValue || 'Загрузка…');
        return (
          '<details class="tc-history-details' + loadingCls + '" id="tcClientHistoryDetails"' + openAttr + '>' +
          '<summary class="tc-history-summary">' +
          '<span class="tc-history-summary__title">Прошедшие занятия</span>' +
          '<span class="' + valueCls + '" id="tcHistorySummaryValue">' +
          valueInner +
          '</span>' +
          TC_HISTORY_CHEVRON +
          '</summary>' +
          (bodyHtml
            ? '<div class="tc-history-body">' + bodyHtml + '</div>'
            : '') +
          '</details>'
        );
      }

      /** Placeholder inside activity panel (replaced when GET /history returns). */
      function buildClientHistorySkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        var body =
          '<div class="tc-history-wrap tc-history-wrap--skel" role="status" aria-busy="true" aria-label="Загрузка истории">' +
          '<div class="tc-history-skel-lines">' +
          '<div class="tc-history-skel-line ' + sk + '" aria-hidden="true"></div>' +
          '<div class="tc-history-skel-line tc-history-skel-line--short ' + sk + '" aria-hidden="true"></div>' +
          '<div class="tc-history-skel-line ' + sk + '" aria-hidden="true"></div>' +
          '</div></div>';
        return buildHistoryDetailsShell('', body, { loading: true });
      }

      /** Stats «Последнее» / «Всего» open the history accordion — same block, no extra chrome. */
      function wireClientHistoryDiscoverability() {
        var details = document.getElementById('tcClientHistoryDetails');
        if (!details) return;
        function openHistoryFromStats(ev) {
          if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
          }
          details.open = true;
          details.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          details.classList.remove('tc-history-details--pulse');
          void details.offsetWidth;
          details.classList.add('tc-history-details--pulse');
          window.setTimeout(function() {
            details.classList.remove('tc-history-details--pulse');
          }, 900);
        }
        function bindStat(el, enabled) {
          if (!el) return;
          el.classList.toggle('tc-stat--history-link', !!enabled);
          if (enabled) {
            el.setAttribute('role', 'button');
            el.setAttribute('tabindex', '0');
            el.setAttribute('aria-label', 'Открыть историю занятий');
            el.onclick = openHistoryFromStats;
            el.onkeydown = function(e) {
              if (e.key === 'Enter' || e.key === ' ') openHistoryFromStats(e);
            };
          } else {
            el.removeAttribute('role');
            el.removeAttribute('tabindex');
            el.removeAttribute('aria-label');
            el.onclick = null;
            el.onkeydown = null;
          }
        }
        var totalWrap = document.getElementById('clientTotalWrap');
        var totalCount = document.getElementById('clientTotalCount');
        var totalReady = !!(totalCount && !totalCount.classList.contains('is-loading'));
        var totalNum = totalReady ? parseInt(String(totalCount.textContent || ''), 10) : NaN;
        bindStat(totalWrap, totalReady && !isNaN(totalNum) && totalNum > 0);
        var lastLabel = document.getElementById('clientLastLabel');
        var lastStat = lastLabel ? lastLabel.closest('.tc-stat') : null;
        var lastText = lastLabel ? String(lastLabel.textContent || '').trim() : '';
        bindStat(lastStat, !!lastText && lastText !== '—');
      }

      /** Mirrors dossier stack height (tags + profile bar + notes) to avoid layout jump before GET /dossier. */
      function buildClientDossierSkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        return (
          '<div class="tc-dossier-skel" role="status" aria-busy="true" aria-label="Загрузка досье">' +
          '<div class="tc-dossier-skel-tags">' +
          '<span class="tc-dossier-skel-chip ' + sk + '" aria-hidden="true"></span>' +
          '<span class="tc-dossier-skel-chip ' + sk + '" aria-hidden="true"></span>' +
          '<span class="tc-dossier-skel-chip-dashed" aria-hidden="true"></span>' +
          '</div>' +
          '<div class="tc-dossier-skel-section" aria-hidden="true">' +
          '<span class="tc-dossier-skel-section-title ' + sk + '"></span>' +
          '<span class="tc-dossier-skel-chevron ' + sk + '"></span>' +
          '</div>' +
          '<div class="tc-dossier-skel-timeline">' +
          '<div class="tc-dossier-skel-tl-top">' +
          '<span class="tc-dossier-skel-tl-title ' + sk + '" aria-hidden="true"></span>' +
          '<span class="tc-dossier-skel-pill ' + sk + '" aria-hidden="true"></span>' +
          '</div>' +
          '<div class="tc-dossier-skel-line ' + sk + '" aria-hidden="true"></div>' +
          '<div class="tc-dossier-skel-line tc-dossier-skel-line--short ' + sk + '" aria-hidden="true"></div>' +
          '</div></div>'
        );
      }

      function buildClientPassesSkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        return (
          '<div class="tc-pass-skel" aria-hidden="true">' +
          '<div class="tc-pass-skel-line ' + sk + '"></div>' +
          '<div class="tc-pass-skel-line tc-pass-skel-line--85 ' + sk + '"></div>' +
          '</div>'
        );
      }

      function renderList() {
        var listEl = document.getElementById('clientsList');
        if (state.clientsListLoading) {
          listEl.innerHTML = buildClientsListSkeletonHtml();
          return;
        }
        listEl.innerHTML = '';
          if (!state.filteredClients.length) {
          var stateMsgEl = document.getElementById('stateMessage');
          if (
            stateMsgEl &&
            stateMsgEl.style.display !== 'none' &&
            stateMsgEl.classList.contains('error')
          ) {
            return;
          }
          var qEmp = (document.getElementById('searchInput').value || '').trim();
          if (hasActiveClientListFilters() || state.filterRecurringOnly) {
            listEl.innerHTML =
              '<div class="empty"><div class="empty-inner"><div class="empty-title">Никого не нашли</div>' +
              'С такими фильтрами клиентов нет. Снимите часть фильтров или измените поиск.</div></div>';
            return;
          }
          if (qEmp && state.allClients.length > 0) {
            var sub =
              state.focusInviteBot
                ? 'По запросу никого не нашли среди клиентов без привязки к боту. Измените поиск или нажмите «Все клиенты».'
                : 'По запросу никого не нашли. Измените поиск или очистите поле.';
            listEl.innerHTML =
              '<div class="empty"><div class="empty-inner"><div class="empty-title">Никого не нашли</div>' +
              sub +
              '</div></div>';
            return;
          }
          listEl.innerHTML =
            '<div class="empty"><div class="empty-inner"><div class="empty-title">Пока пусто</div>Добавьте клиента кнопкой ниже или дождитесь первой записи — тогда список пополнится автоматически.</div></div>';
          return;
        }
        var html = state.filteredClients.map(function(c) {
          var name = trainerClientDisplayName(c).trim() || 'Клиент';
          var initials = clientInitials(name);
          var isSandbox = !!c.is_sandbox;
          var phone = isSandbox ? 'Тестовый клиент' : (c.phone || 'Телефон не указан');
          var lastLabel = c.last_date
            ? ('Последнее проведённое: ' + formatDate(c.last_date) + (c.last_start ? ' ' + formatTime(c.last_start) : ''))
            : (isSandbox ? 'Демо-запись для знакомства с системой' : 'Проведённых занятий ещё не было');
          var needsInvite = !isSandbox && (c.telegram_id == null || c.telegram_id === '');
          var recCount = Number(c.recurring_slots_count) || 0;
          var recurringPill =
            !isSandbox && recCount > 0
              ? '<span class="client-badge client-badge--recurring">Постоянный</span>'
              : '';
          var tierKind = (c.last_price_tier_kind || '').toLowerCase();
          var tierLabel = CLIENT_TIER_BADGE_LABELS[tierKind] || '';
          var tierPill =
            !isSandbox && tierLabel
              ? '<span class="client-badge client-badge--tier">' + escapeHtml(tierLabel) + '</span>'
              : '';
          var passPill =
            !isSandbox && c.has_active_pass
              ? '<span class="client-badge client-badge--pass">Абонемент</span>'
              : '';
          // Sandbox pill replaces the «нет в боте» badge — for a demo identity that label is noise.
          var badge =
            isSandbox
              ? '<span class="client-badge client-badge--sandbox" role="status">Пример</span>'
              : (needsInvite
                  ? '<span class="client-badge client-badge--no-tg">Нет в боте</span>'
                  : '');
          var cardCls = 'client-card' + (isSandbox ? ' client-card--sandbox' : '');
          return (
            '<button type=\"button\" class=\"' + cardCls + '\" data-id=\"' + c.id + '\">' +
              '<div class=\"client-avatar\" aria-hidden=\"true\">' + escapeHtml(initials) + '</div>' +
              '<div class=\"client-main\">' +
                '<div class=\"client-name-row\">' +
                  '<span class=\"client-name\">' + escapeHtml(name) + '</span>' +
                  recurringPill +
                  tierPill +
                  passPill +
                  badge +
                '</div>' +
                '<div class=\"client-meta\">' + escapeHtml(phone) + '</div>' +
                '<div class=\"client-meta\">' + escapeHtml(lastLabel) + '</div>' +
              '</div>' +
              '<span class=\"client-arrow\">→</span>' +
            '</button>'
          );
        }).join('');
        listEl.innerHTML = html;
        listEl.querySelectorAll('.client-card').forEach(function(btn) {
          btn.onclick = function() {
            var id = parseInt(btn.dataset.id, 10);
            openClientDetail(id);
          };
        });
      }

      function loadClientHistory(id) {
        if (id == null || id === '') return;
        var gen = ++state.clientHistoryLoadGen;
        var host = document.getElementById('clientHistoryHost');
        var url = '/api/webapp/trainer/clients/' + encodeURIComponent(id) + '/history?limit=10';
        url = withInit(url);
        fetch(url, { cache: 'no-store' })
          .then(function(r) {
          return r.json().then(function(data) {
            if (!r.ok) throw new Error(data.detail || r.statusText);
            return data;
          });
        }).then(function(data) {
          if (gen !== state.clientHistoryLoadGen) return;
          var items = data.items || [];
          var total = typeof data.total === 'number' ? data.total : items.length;
          var totalWrap = document.getElementById('clientTotalWrap');
          var totalCount = document.getElementById('clientTotalCount');
          if (totalWrap && totalCount) {
            totalCount.textContent = String(total);
            totalCount.classList.remove('is-loading');
          }
          var renderItem = function(it) {
            var dateStr = formatDate(it.slot_date);
            var timeStr = it.start_time ? formatTime(it.start_time) : '';
            var place = it.arena_name ? it.arena_name : '—';
            var status = (it.status || '').toLowerCase();
            var statusLabel = status === 'completed' ? 'прошло' : status === 'pending' ? 'ожидает' : status === 'confirmed' ? 'подтверждено' : status || '—';
            var serviceName = (it.service_name || '').trim() || '—';
            var tierLab = (it.price_tier_label || '').trim();
            var serviceHtml = escapeHtml(serviceName) + (tierLab ? ' · ' + escapeHtml(tierLab) : '');
            var line1 = dateStr + (timeStr ? ' ' + timeStr : '') + ' · ' + place + ' · ' + statusLabel;
            var recId = it.recurring_client_slot_id;
            var recurringBadge =
              recId != null && recId !== ''
                ? '<span class="client-badge client-badge--history-recurring">Постоянная</span>'
                : '';
            return (
              '<div class="history-item">' +
              '<div class="history-item-top">' +
              '<span class="history-item-line">' +
              escapeHtml(line1) +
              '</span>' +
              recurringBadge +
              '</div>' +
              '<div class="history-item-service">' +
              serviceHtml +
              '</div></div>'
            );
          };
          var bodyHtml = '';
          if (!items.length) {
            bodyHtml = '<div class="history-list history-list--empty">Пока нет прошедших занятий с этим клиентом.</div>';
          } else {
            var first = items.slice(0, 5);
            var rest = items.slice(5);
            bodyHtml += '<div class="history-list tc-reveal-once">';
            first.forEach(function(it) { bodyHtml += renderItem(it); });
            if (rest.length) {
              bodyHtml += '<div id="historyMore" style="display:none;">';
              rest.forEach(function(it) { bodyHtml += renderItem(it); });
              bodyHtml += '</div>';
            }
            bodyHtml += '</div>';
            if (rest.length) {
              bodyHtml +=
                '<div class="history-toggle"><button type="button" class="history-toggle-button" id="btnHistoryToggle">Показать все (' +
                items.length +
                ')</button></div>';
            }
          }
          var summaryValue = buildHistorySummaryValue(total, items);
          var keepOpen = false;
          var prevDetails = document.getElementById('tcClientHistoryDetails');
          if (prevDetails) keepOpen = !!prevDetails.open;
          var defaultOpen = total > 0 && total <= 2;
          var html = buildHistoryDetailsShell(summaryValue, bodyHtml, { open: keepOpen || defaultOpen });
          if (host) {
            host.innerHTML = html;
          } else {
            document.getElementById('clientDetail').insertAdjacentHTML('beforeend', html);
          }
          wireClientHistoryDiscoverability();
          var toggle = document.getElementById('btnHistoryToggle');
          if (toggle) {
            toggle.onclick = function() {
              var more = document.getElementById('historyMore');
              if (!more) return;
              var isHidden = more.style.display === 'none';
              more.style.display = isHidden ? 'block' : 'none';
              toggle.textContent = isHidden ? 'Свернуть' : 'Показать все (' + items.length + ')';
            };
          }
        }).catch(function() {
          if (gen !== state.clientHistoryLoadGen) return;
          var totalCount = document.getElementById('clientTotalCount');
          if (totalCount) {
            totalCount.textContent = '—';
            totalCount.classList.remove('is-loading');
          }
          var errBody =
            '<div class="history-list history-list--empty tc-reveal-once">Не удалось загрузить историю.</div>';
          var errHtml = buildHistoryDetailsShell('—', errBody, { open: true });
          if (host) {
            host.innerHTML = errHtml;
          } else {
            document.getElementById('clientDetail').insertAdjacentHTML('beforeend', errHtml);
          }
          wireClientHistoryDiscoverability();
        });
      }

      /* --- Dossier state and helpers --- */
      var dossierState = {
        profile: { note: '', goals: '', limitations: '', level: '', season_goal: '' },
        tags: [],
        entries: [],
        suggestedTags: [],
        suggestedSeasonGoals: [],
        selfBookWindow: null,
        editingField: null,
        showNewEntry: false,
        /** User-toggled accordion; reset on client change — profile starts collapsed even when fields are filled. */
        profileSectionExpanded: false,
      };

      var TC_SELF_BOOK_CHEVRON =
        '<svg class="tc-self-book-summary__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

      /** Collapsible «Самозапись» — collapsed by default; per-client filter on /client/slots. */
      function renderSelfBookWindow() {
        var host = document.getElementById('tcSelfBookWindowHost');
        if (!host || state.selectedClientId == null) return;
        var prevDetails = document.getElementById('tcSelfBookDetails');
        var keepOpen = !!(prevDetails && prevDetails.open);
        var win = dossierState.selfBookWindow || {};
        var options = win.options || [
          { value: null, label: 'Любое время' },
          { value: 'morning', label: 'Утро' },
          { value: 'afternoon', label: 'День' },
          { value: 'evening', label: 'Вечер' },
        ];
        var current = win.value != null ? win.value : null;
        var currentLabel = win.label || 'Любое время';
        var rangesHint = win.ranges_hint || 'Утро 8:00–12:00 · День 13:00–16:00 · Вечер 17:00–00:00';
        var html =
          '<details class="tc-self-book-details" id="tcSelfBookDetails">' +
          '<summary class="tc-self-book-summary">' +
          '<span class="tc-self-book-summary__title">Самозапись</span>' +
          '<span class="tc-self-book-summary__value" id="tcSelfBookSummaryValue">' +
          escapeHtml(currentLabel) +
          '</span>' +
          TC_SELF_BOOK_CHEVRON +
          '</summary>' +
          '<div class="tc-self-book-window__body">' +
          '<p class="tc-self-book-window__lead">При самозаписи к вам клиент увидит только свободное время в выбранном интервале. Запись из вашего расписания не ограничивается.</p>' +
          '<div class="tc-daypart-seg" role="group" aria-label="Окно для самозаписи">';
        options.forEach(function(opt) {
          var v = opt.value;
          var isActive = (v == null && current == null) || (v != null && v === current);
          var dataVal = v == null ? '' : String(v);
          html +=
            '<button type="button" class="tc-daypart-seg__btn' +
            (isActive ? ' is-active' : '') +
            '" data-daypart="' +
            escapeHtml(dataVal) +
            '">' +
            escapeHtml(opt.label || '—') +
            '</button>';
        });
        html +=
          '</div>' +
          '<p class="tc-self-book-window__ranges">' +
          escapeHtml(rangesHint) +
          '</p></div></details>';
        host.innerHTML = html;
        host.removeAttribute('aria-busy');
        host.classList.add('tc-reveal-once');
        var detailsEl = document.getElementById('tcSelfBookDetails');
        if (detailsEl && keepOpen) detailsEl.open = true;
        host.querySelectorAll('.tc-daypart-seg__btn').forEach(function(btn) {
          btn.addEventListener('click', function() {
            var raw = btn.getAttribute('data-daypart');
            var next = raw === '' || raw == null ? null : raw;
            if ((next == null && current == null) || next === current) return;
            patchSelfBookWindow(state.selectedClientId, next);
          });
        });
      }

      function patchSelfBookWindow(clientId, daypart) {
        var host = document.getElementById('tcSelfBookWindowHost');
        if (host) {
          host.setAttribute('aria-busy', 'true');
          var root = document.getElementById('tcSelfBookDetails');
          if (root) {
            root.querySelectorAll('.tc-daypart-seg__btn').forEach(function(b) {
              b.disabled = true;
            });
          }
        }
        fetch(
          withInit('/api/webapp/trainer/clients/' + encodeURIComponent(String(clientId)) + '/self-book-window'),
          {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ daypart: daypart }),
          }
        )
          .then(function(r) {
            return r.json().then(function(d) {
              if (!r.ok) throw new Error((d && d.detail) || r.statusText || 'Ошибка');
              return d;
            });
          })
          .then(function(data) {
            dossierState.selfBookWindow = (data && data.self_book_window) || dossierState.selfBookWindow;
            renderSelfBookWindow();
            showTcToast(
              daypart
                ? 'Окно для самозаписи: ' + (dossierState.selfBookWindow.label || daypart)
                : 'Самозапись без ограничения по времени'
            );
          })
          .catch(function(err) {
            if (host) host.removeAttribute('aria-busy');
            alert(err.message || 'Не удалось сохранить');
            renderSelfBookWindow();
          });
      }

      function formatEntryDate(isoStr) {
        if (!isoStr) return '';
        var d = new Date(isoStr);
        if (isNaN(d.getTime())) return isoStr.slice(0, 10);
        var day = String(d.getDate()).padStart(2, '0');
        var month = String(d.getMonth() + 1).padStart(2, '0');
        var year = d.getFullYear();
        return day + '.' + month + '.' + year;
      }

      function renderDossierTags() {
        var ICO_X = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        var html = '<div class="dossier-tags" id="dossierTags">';
        dossierState.tags.forEach(function(t) {
          var isSys = (t.category || '') === 'system';
          var rm = isSys
            ? ''
            : '<button type="button" class="dossier-tag-remove" data-id="' + t.id + '">' + ICO_X + '</button>';
          html +=
            '<span class="dossier-tag' +
            (isSys ? ' dossier-tag--system' : '') +
            '" data-id="' +
            t.id +
            '">' +
            escapeHtml(t.tag) +
            rm +
            '</span>';
        });
        html += '<button type="button" class="dossier-tag-add" id="btnAddTag">+ Добавить</button>';
        html += '</div>';
        return html;
      }

      function renderDossierProfile() {
        var ICO_CHEVRON = '<svg class="dossier-section-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>';
        var fields = [
          { key: 'goals', label: 'Цели', placeholder: 'Чего хочет достичь клиент?' },
          { key: 'limitations', label: 'Ограничения / Травмы', placeholder: 'Травмы, противопоказания, на что обратить внимание' },
          { key: 'level', label: 'Уровень', placeholder: 'Текущий уровень, опыт, стаж' },
          {
            key: 'season_goal',
            label: 'Цель сезона',
            placeholder:
              'Фокус сезона: соревнования, программа, возврат после перерыва, тесты, техника…',
          },
          { key: 'note', label: 'Общая заметка', placeholder: 'Любая другая информация о клиенте' },
        ];
        var profileExpanded = !!dossierState.profileSectionExpanded;
        var html = '<div class="dossier-section' + (profileExpanded ? ' is-open' : '') + '" id="dossierProfileSection">';
        html += '<div class="dossier-section-header"><span class="dossier-section-title">Профиль клиента</span>' + ICO_CHEVRON + '</div>';
        html += '<div class="dossier-section-body" id="dossierProfileBody">';
        fields.forEach(function(f) {
          var val = dossierState.profile[f.key] || '';
          html += '<div class="dossier-field" data-field="' + f.key + '">';
          html += '<div class="dossier-field-label">' + escapeHtml(f.label) + '</div>';
          if (dossierState.editingField === f.key) {
            html += '<textarea class="dossier-field-edit" data-field="' + f.key + '" placeholder="' + escapeHtml(f.placeholder) + '">' + escapeHtml(val) + '</textarea>';
            html += '<div class="dossier-field-actions"><button type="button" class="dossier-btn-save" data-field="' + f.key + '">Сохранить</button><button type="button" class="dossier-btn-cancel" data-field="' + f.key + '">Отмена</button></div>';
          } else {
            html += '<div class="dossier-field-value' + (!val ? ' empty' : '') + '" data-field="' + f.key + '">' + (val ? escapeHtml(val) : 'Нажмите, чтобы добавить') + '</div>';
          }
          html += '</div>';
          if (f.key === 'season_goal' && dossierState.suggestedSeasonGoals.length) {
            var cur = (dossierState.profile.season_goal || '').trim().toLowerCase();
            var chipHtml = '';
            dossierState.suggestedSeasonGoals.forEach(function(lbl) {
              if (cur && cur === String(lbl).trim().toLowerCase()) return;
              chipHtml +=
                '<button type="button" class="dossier-season-chip" data-season-text="' +
                escapeHtml(lbl) +
                '">' +
                escapeHtml(lbl) +
                '</button>';
            });
            if (chipHtml) {
              html +=
                '<div class="dossier-season-goal-chips" role="group" aria-label="Быстрый выбор цели сезона">' +
                chipHtml +
                '</div>';
            }
          }
        });
        html += '</div></div>';
        return html;
      }

      function renderDossierTimeline() {
        var html = '<div class="dossier-timeline" id="dossierTimeline">';
        html += '<div class="dossier-timeline-header"><span class="dossier-timeline-title">Заметки по занятиям</span>';
        html += '<button type="button" class="dossier-timeline-add" id="btnAddEntry">+ Добавить</button></div>';
        if (dossierState.showNewEntry) {
          html += '<div class="dossier-new-entry" id="dossierNewEntry">';
          html += '<textarea id="newEntryContent" placeholder="Что было на занятии? Прогресс, над чем работали..."></textarea>';
          html += '<div class="dossier-new-entry-actions"><button type="button" class="dossier-btn-save" id="btnSaveNewEntry">Сохранить</button><button type="button" class="dossier-btn-cancel" id="btnCancelNewEntry">Отмена</button></div>';
          html += '</div>';
        }
        if (!dossierState.entries.length && !dossierState.showNewEntry) {
          html += '<div class="dossier-empty">Пока нет заметок. Добавьте первую после занятия.</div>';
        } else {
          var ICO_TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
          dossierState.entries.forEach(function(e) {
            html += '<div class="dossier-entry" data-id="' + e.id + '">';
            html += '<button type="button" class="dossier-entry-delete" data-id="' + e.id + '">' + ICO_TRASH + '</button>';
            html += '<div class="dossier-entry-date">' + formatEntryDate(e.created_at) + '</div>';
            html += '<div class="dossier-entry-content">' + escapeHtml(e.content) + '</div>';
            html += '</div>';
          });
        }
        html += '</div>';
        return html;
      }

      function renderDossier() {
        var container = document.getElementById('dossierContainer');
        if (!container) return;
        container.innerHTML = renderDossierTags() + renderDossierProfile() + renderDossierTimeline();
        wireDossierEvents();
      }

      function wireDossierEvents() {
        document.querySelectorAll('.dossier-tag-remove').forEach(function(btn) {
          btn.onclick = function(e) {
            e.stopPropagation();
            var tagId = parseInt(btn.dataset.id, 10);
            removeTag(tagId);
          };
        });
        var addTagBtn = document.getElementById('btnAddTag');
        if (addTagBtn) addTagBtn.onclick = function() { openTagPicker(); };
        var profileHeader = document.querySelector('#dossierProfileSection .dossier-section-header');
        if (profileHeader) {
          profileHeader.onclick = function() {
            if (dossierState.profileSectionExpanded) {
              // Collapsing the accordion cancels in-progress field edit (same as «Отмена»).
              dossierState.editingField = null;
            }
            dossierState.profileSectionExpanded = !dossierState.profileSectionExpanded;
            renderDossier();
          };
        }
        document.querySelectorAll('.dossier-field-value').forEach(function(el) {
          el.onclick = function() {
            dossierState.profileSectionExpanded = true;
            dossierState.editingField = el.dataset.field;
            renderDossier();
            var textarea = document.querySelector('.dossier-field-edit[data-field="' + el.dataset.field + '"]');
            if (textarea) textarea.focus();
          };
        });
        document.querySelectorAll('.dossier-btn-save[data-field]').forEach(function(btn) {
          btn.onclick = function() { saveProfileField(btn.dataset.field); };
        });
        document.querySelectorAll('.dossier-btn-cancel[data-field]').forEach(function(btn) {
          btn.onclick = function() {
            dossierState.editingField = null;
            renderDossier();
          };
        });
        var addEntryBtn = document.getElementById('btnAddEntry');
        if (addEntryBtn) addEntryBtn.onclick = function() {
          dossierState.showNewEntry = true;
          renderDossier();
          var textarea = document.getElementById('newEntryContent');
          if (textarea) textarea.focus();
        };
        var saveNewEntryBtn = document.getElementById('btnSaveNewEntry');
        if (saveNewEntryBtn) saveNewEntryBtn.onclick = function() { saveNewEntry(); };
        var cancelNewEntryBtn = document.getElementById('btnCancelNewEntry');
        if (cancelNewEntryBtn) cancelNewEntryBtn.onclick = function() {
          dossierState.showNewEntry = false;
          renderDossier();
        };
        document.querySelectorAll('.dossier-entry-delete').forEach(function(btn) {
          btn.onclick = function() {
            var entryId = parseInt(btn.dataset.id, 10);
            deleteEntry(entryId);
          };
        });
        document.querySelectorAll('.dossier-season-chip').forEach(function(btn) {
          btn.onclick = function(e) {
            if (e) {
              e.preventDefault();
              e.stopPropagation();
            }
            var t = btn.getAttribute('data-season-text');
            if (t) saveProfileField('season_goal', t);
          };
        });
      }

      function patchClientRecurringSlotsCount(clientId, n) {
        var v = Math.max(0, parseInt(String(n), 10) || 0);
        function patchArr(arr) {
          if (!arr) return;
          var c = arr.find(function(x) { return x.id === clientId; });
          if (c) c.recurring_slots_count = v;
        }
        patchArr(state.allClients);
        patchArr(state.filteredClients);
      }

      /** Python weekday: 0=Monday .. 6=Sunday (same as recurring API). */
      function trainerRecurringWeekdayRu(dow) {
        var names = ['Понедельник', 'Вторник', 'Среда', 'Четвер', 'Пятница', 'Суббота', 'Воскресенье'];
        var i = parseInt(String(dow), 10);
        if (isNaN(i) || i < 0 || i > 6) return '—';
        return names[i];
      }

      function buildRecurringSuggestionCard(s) {
        var bid = s.booking_id;
        var arena = (s.arena_name && String(s.arena_name).trim()) ? escapeHtml(String(s.arena_name).trim()) : '—';
        var svc = escapeHtml((s.service_name || '—').trim() || '—');
        var tier = (s.price_tier_label && String(s.price_tier_label).trim())
          ? escapeHtml(String(s.price_tier_label).trim())
          : '';
        var when =
          escapeHtml(trainerRecurringWeekdayRu(s.day_of_week)) +
          ' · ' +
          escapeHtml(s.start_time || '') +
          '–' +
          escapeHtml(s.end_time || '');
        var recId = s.recurring_slot_id;
        var act = recId
          ? (
            '<button type="button" class="tc-rec-sugg-card__btn tc-rec-sugg-card__btn--cancel bd-btn bd-btn--surface" ' +
            'data-rec-action="cancel" data-recurring-id="' +
            String(recId) +
            '" data-booking-id="' +
            String(bid) +
            '">Отменить</button>'
          )
          : (
            '<button type="button" class="tc-rec-sugg-card__btn tc-rec-sugg-card__btn--apply bd-btn bd-btn--primary" ' +
            'data-rec-action="apply" data-booking-id="' +
            String(bid) +
            '" data-apply-choice="' +
            (s.apply_first_week_choice ? '1' : '0') +
            '">Применить</button>'
          );
        return (
          '<div class="tc-rec-sugg-card">' +
          '<div class="tc-rec-sugg-card__body">' +
          '<div class="tc-rec-sugg-card__when">' +
          when +
          '</div>' +
          '<div class="tc-rec-sugg-card__service">' +
          svc +
          '</div>' +
          '<div class="tc-rec-sugg-card__meta">' +
          arena +
          (tier ? '<span class="tc-rec-sugg-card__dot"> · </span>' + tier : '') +
          '</div>' +
          '</div>' +
          '<div class="tc-rec-sugg-card__actions">' +
          act +
          '</div>' +
          '</div>'
        );
      }

      function openRecurringFirstWeekModal(onChoose) {
        var modal = document.getElementById('tcModalRecurringFirstWeek');
        var lead = document.getElementById('tcRecurringFirstWeekLead');
        var bThis = document.getElementById('tcRecurringFwThis');
        var bNext = document.getElementById('tcRecurringFwNext');
        var bCancel = document.getElementById('tcRecurringFwCancel');
        if (!modal || !lead || !bThis || !bNext || !bCancel) {
          onChoose('this_week');
          return;
        }
        function close() {
          modal.style.display = 'none';
          modal.setAttribute('aria-hidden', 'true');
          modal.onclick = null;
          bThis.onclick = bNext.onclick = bCancel.onclick = null;
        }
        lead.textContent =
          'Ближайший такой слот на этой неделе ещё впереди. Включить её в автозаписи или начать со следующей?';
        bThis.onclick = function(e) {
          e.preventDefault();
          close();
          onChoose('this_week');
        };
        bNext.onclick = function(e) {
          e.preventDefault();
          close();
          onChoose('next_week');
        };
        bCancel.onclick = function(e) {
          e.preventDefault();
          close();
          onChoose(null);
        };
        modal.onclick = function(ev) {
          if (ev.target === modal) {
            close();
            onChoose(null);
          }
        };
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
      }

      function postRecurringFromBooking(clientId, bookingId, firstWeekOpt) {
        var body = { booking_id: bookingId };
        if (firstWeekOpt) body.first_week = firstWeekOpt;
        return fetch(
          withInit(
            '/api/webapp/trainer/clients/' + encodeURIComponent(clientId) + '/recurring/from-booking'
          ),
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          }
        ).then(function(r) {
          return r.json().then(function(d) {
            if (!r.ok) throw new Error((d && d.detail) || r.statusText || 'Ошибка');
            return d;
          });
        });
      }

      function loadRecurringSection(clientId, opts) {
        opts = opts || {};
        var silentRefresh = !!opts.silentRefresh;
        var preserveUi = !!opts.preserveUi;

        var host = document.getElementById('tcRecurringHost');
        if (!host) return;
        var snap = state.allClients.find(function(x) { return x.id === clientId; });
        if (snap && snap.is_sandbox) {
          host.innerHTML = '';
          host.hidden = true;
          return;
        }

        if (silentRefresh && !host.querySelector('details.tc-recurring-details')) {
          silentRefresh = false;
        }

        var detailsWasOpen = false;
        var extraListExpanded = false;
        if (preserveUi) {
          var detPrev = host.querySelector('details.tc-recurring-details');
          if (detPrev) detailsWasOpen = !!detPrev.open;
          var exWp = host.querySelector('#tcRecSuggExtra');
          if (exWp && !exWp.hidden) extraListExpanded = true;
        }

        if (!silentRefresh) {
          host.hidden = false;
          host.innerHTML =
            '<div class="tc-recurring-skel" aria-busy="true"><span class="ma-skel-shimmer">Загрузка…</span></div>';
        }

        var url = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(clientId) + '/recurring');
        fetch(url)
          .then(function(r) {
            return r.json().then(function(d) {
              if (!r.ok) throw new Error((d && d.detail) || r.statusText || 'Ошибка');
              return d;
            });
          })
          .then(function(data) {
            var slots = data.slots || [];
            var upcoming = data.upcoming_bookings || [];
            var sugg = data.booking_suggestions || [];
            var hw = Number(data.materialization_horizon_weeks) || 3;
            patchClientRecurringSlotsCount(clientId, slots.length);

            var suggestedRec = {};
            sugg.forEach(function(x) {
              if (x.recurring_slot_id) suggestedRec[String(x.recurring_slot_id)] = true;
            });
            var orphanSlots = slots.filter(function(s) {
              return !suggestedRec[String(s.id)];
            });

            if (!sugg.length && !orphanSlots.length) {
              host.innerHTML = '';
              host.hidden = true;
              patchClientRecurringSlotsCount(clientId, 0);
              if (typeof renderList === 'function' && !state.clientsListLoading) renderList();
              return;
            }

            var nAct = slots.length;
            var sumHint = (function(n) {
              if (!n) return 'Нет закреплений';
              var n10 = n % 10;
              var n100 = n % 100;
              var w = 'закреплений';
              if (n10 === 1 && n100 !== 11) w = 'закрепление';
              else if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) w = 'закрепления';
              return String(n) + ' ' + w;
            })(nAct);
            var orphanHtml = orphanSlots.length
              ? (
                '<div class="tc-recurring-subtitle">Другие закрепления</div>' +
                '<div class="tc-recurring-slots">' +
                orphanSlots
                  .map(function(s) {
                    return (
                      '<div class="tc-recurring-slot-row">' +
                      '<span class="tc-recurring-slot-label">' +
                      escapeHtml(s.label || '') +
                      '</span>' +
                      '<button type="button" class="tc-recurring-remove bd-btn bd-btn--surface" data-rec-id="' +
                      String(s.id) +
                      '">Снять</button>' +
                      '</div>'
                    );
                  })
                  .join('') +
                '</div>'
              )
              : '';
            var upHtml = upcoming.length
              ? (
                '<div class="tc-recurring-upcoming"><div class="tc-recurring-subtitle">Ближайшие занятия</div><ul class="tc-recurring-up-list">' +
                upcoming
                  .slice(0, 12)
                  .map(function(u) {
                    var kind = (u.kind || 'real');
                    var hint = '';
                    if (kind === 'virtual') {
                      hint =
                        ' <span class="tc-recurring-virt">' +
                        escapeHtml(u.label_hint || 'по правилу') +
                        '</span>';
                    }
                    return (
                      '<li class="tc-recurring-up-item' +
                      (kind === 'virtual' ? ' tc-recurring-up-item--virtual' : '') +
                      '">' +
                      escapeHtml(formatDate(u.slot_date)) +
                      ' · ' +
                      escapeHtml(formatTime(u.start_time)) +
                      hint +
                      '</li>'
                    );
                  })
                  .join('') +
                '</ul></div>'
              )
              : '';
            var first = sugg.slice(0, 3);
            var rest = sugg.slice(3);
            var suggMain = first.map(buildRecurringSuggestionCard).join('');
            var suggExtra = rest.map(buildRecurringSuggestionCard).join('');
            var expandRow =
              rest.length
                ? (
                  '<div class="tc-rec-sugg-expand-row">' +
                  '<button type="button" class="tc-rec-sugg-expand bd-btn bd-btn--surface" id="tcRecSuggExpand" aria-expanded="false" data-rest-count="' +
                  String(rest.length) +
                  '">' +
                  'Показать ещё (' +
                  String(rest.length) +
                  ')</button>' +
                  '</div>' +
                  '<div class="tc-rec-sugg-extra" id="tcRecSuggExtra" hidden>' +
                  suggExtra +
                  '</div>'
                )
                : '';
            var suggBlock = sugg.length
              ? (
                '<div class="tc-recurring-subtitle">По прошлым занятиям</div>' +
                '<p class="tc-rec-sugg-lead">Подсказки из истории — до 10 вариантов. «Применить» закрепляет день недели и время.</p>' +
                '<div class="tc-rec-sugg-list">' +
                suggMain +
                '</div>' +
                expandRow
              )
              : '';

            host.innerHTML =
              '<details class="tc-recurring-details tc-reveal-once">' +
              '<summary class="tc-recurring-summary">' +
              '<span class="tc-recurring-summary-title">Постоянные слоты</span>' +
              '<span class="tc-recurring-summary-hint">' +
              escapeHtml(sumHint) +
              '</span>' +
              '</summary>' +
              '<div class="tc-recurring-body">' +
              '<p class="tc-recurring-help">' +
              'В расписании держим реальные записи на ближайшие <strong>' +
              String(hw) +
              '</strong> ' +
              (hw % 10 === 1 && hw % 100 !== 11
                ? 'неделю'
                : hw % 10 >= 2 && hw % 10 <= 4 && (hw % 100 < 10 || hw % 100 >= 20)
                  ? 'недели'
                  : 'недель') +
              '. Дальше в списке — даты <em>по правилу</em> без лишних строк в базе; они появятся сами, когда подойдёт неделя. Шаблон сами не накатываем. Если ближайший раз ещё впереди, при «Применить» выберите: с этой недели или со следующей.' +
              suggBlock +
              orphanHtml +
              upHtml +
              '</div></details>';

            function wireRemoveButtons() {
              host.querySelectorAll('.tc-recurring-remove').forEach(function(btn) {
                btn.onclick = function(e) {
                  e.preventDefault();
                  var rid = parseInt(btn.getAttribute('data-rec-id'), 10);
                  if (!rid) return;
                  if (!window.confirm('Снять закрепление? Предстоящие автозаписи по нему исчезнут из расписания — отдельного уведомления об отмене клиенту не будет.')) return;
                  fetch(withInit('/api/webapp/trainer/recurring/' + encodeURIComponent(rid) + '/remove'), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                  })
                    .then(function(r) {
                      return r.json().then(function(d) {
                        if (!r.ok) throw new Error((d && d.detail) || r.statusText || 'Ошибка');
                        return d;
                      });
                    })
                    .then(function(d) {
                      var raw = d && d.removed_forward_bookings;
                      var rm =
                        typeof raw === 'number'
                          ? raw
                          : parseInt(String(raw), 10);
                      if (!isNaN(rm) && rm > 0) {
                        showTcToast('Закрепление снято. Убрано предстоящих автозаписей: ' + rm + '.');
                      } else {
                        showTcToast('Закрепление снято.');
                      }
                      loadRecurringSection(clientId, { silentRefresh: true, preserveUi: true });
                      if (typeof renderList === 'function' && !state.clientsListLoading) renderList();
                    })
                    .catch(function(ex) {
                      alert(ex.message || String(ex));
                    });
                };
              });
            }
            wireRemoveButtons();

            var exBtn = document.getElementById('tcRecSuggExpand');
            var exWrap = document.getElementById('tcRecSuggExtra');
            if (exBtn && exWrap && rest.length) {
              exBtn.onclick = function() {
                var willShow = exWrap.hidden;
                var rc = parseInt(exBtn.getAttribute('data-rest-count') || '0', 10) || rest.length;
                exWrap.hidden = !willShow;
                exBtn.setAttribute('aria-expanded', willShow ? 'true' : 'false');
                exBtn.textContent = willShow
                  ? 'Свернуть'
                  : 'Показать ещё (' + String(rc) + ')';
              };
            }

            host.querySelectorAll('[data-rec-action="apply"]').forEach(function(btn) {
              btn.onclick = function() {
                var bid = parseInt(btn.getAttribute('data-booking-id'), 10);
                if (!bid) return;
                var needChoice = btn.getAttribute('data-apply-choice') === '1';
                function runPost(firstWeekOpt) {
                  btn.disabled = true;
                  postRecurringFromBooking(clientId, bid, firstWeekOpt)
                    .then(function(d) {
                      var mat = d && d.materialized_bookings;
                      var n = typeof mat === 'number' ? mat : parseInt(String(mat), 10);
                      if (isNaN(n)) n = 0;
                      if (n > 0) {
                        showTcToast('Постоянное время закреплено. Создано автозаписей: ' + n + '.');
                      } else {
                        showTcToast(
                          'Закреплено, автозаписей пока 0: нет места на это время впереди (занято или нет подходящего слота). Откройте слот в расписании вручную или измените правило.'
                        );
                      }
                      loadRecurringSection(clientId, { silentRefresh: true, preserveUi: true });
                      if (typeof renderList === 'function' && !state.clientsListLoading) renderList();
                    })
                    .catch(function(ex) {
                      alert(ex.message || String(ex));
                    })
                    .finally(function() {
                      btn.disabled = false;
                    });
                }
                if (needChoice) {
                  openRecurringFirstWeekModal(function(choice) {
                    if (!choice) return;
                    runPost(choice);
                  });
                  return;
                }
                runPost(null);
              };
            });
            host.querySelectorAll('[data-rec-action="cancel"]').forEach(function(btn) {
              btn.onclick = function() {
                var rid = parseInt(btn.getAttribute('data-recurring-id'), 10);
                if (!rid) return;
                if (!window.confirm('Снять закрепление? Предстоящие автозаписи по нему исчезнут из расписания — отдельного уведомления об отмене клиенту не будет.')) return;
                btn.disabled = true;
                fetch(withInit('/api/webapp/trainer/recurring/' + encodeURIComponent(rid) + '/remove'), {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                })
                  .then(function(r) {
                    return r.json().then(function(d) {
                      if (!r.ok) throw new Error((d && d.detail) || r.statusText || 'Ошибка');
                      return d;
                    });
                  })
                  .then(function(d) {
                    var raw = d && d.removed_forward_bookings;
                    var rm =
                      typeof raw === 'number'
                        ? raw
                        : parseInt(String(raw), 10);
                    if (!isNaN(rm) && rm > 0) {
                      showTcToast('Закрепление снято. Убрано предстоящих автозаписей: ' + rm + '.');
                    } else {
                      showTcToast('Закрепление снято.');
                    }
                    loadRecurringSection(clientId, { silentRefresh: true, preserveUi: true });
                    if (typeof renderList === 'function' && !state.clientsListLoading) renderList();
                  })
                  .catch(function(ex) {
                    alert(ex.message || String(ex));
                  })
                  .finally(function() {
                    btn.disabled = false;
                  });
              };
            });

            if (preserveUi && detailsWasOpen) {
              var detNew = host.querySelector('details.tc-recurring-details');
              if (detNew) detNew.open = true;
            }
            if (preserveUi && extraListExpanded) {
              var exR = document.getElementById('tcRecSuggExtra');
              var ebR = document.getElementById('tcRecSuggExpand');
              var rcR = parseInt((ebR && ebR.getAttribute('data-rest-count')) || '0', 10);
              if (exR && ebR && rcR > 0) {
                exR.hidden = false;
                ebR.setAttribute('aria-expanded', 'true');
                ebR.textContent = 'Свернуть';
              }
            }
          })
          .catch(function() {
            host.innerHTML =
              '<details class="tc-recurring-details tc-reveal-once"><summary class="tc-recurring-summary"><span class="tc-recurring-summary-title">Постоянные слоты</span></summary><div class="tc-recurring-body dossier-empty">Не удалось загрузить</div></details>';
            host.hidden = false;
          });
      }

      function loadDossier(clientId) {
        var url = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(clientId) + '/dossier');
        fetch(url).then(function(r) { return r.json(); }).then(function(data) {
          dossierState.profile = data.profile || {
            note: '',
            goals: '',
            limitations: '',
            level: '',
            season_goal: '',
          };
          dossierState.tags = data.tags || [];
          dossierState.entries = data.entries || [];
          dossierState.suggestedTags = data.suggested_tags || [];
          dossierState.suggestedSeasonGoals = data.suggested_season_goals || [];
          dossierState.selfBookWindow = data.self_book_window || null;
          dossierState.editingField = null;
          dossierState.showNewEntry = false;
          dossierState.profileSectionExpanded = false;
          renderSelfBookWindow();
          renderDossier();
          var dc = document.getElementById('dossierContainer');
          if (dc) dc.classList.add('tc-reveal-once');
        }).catch(function() {
          var container = document.getElementById('dossierContainer');
          if (container) {
            container.innerHTML = '<div class="dossier-empty tc-reveal-once">Не удалось загрузить досье</div>';
          }
        });
      }

      function saveProfileField(fieldKey, optValue) {
        var value;
        if (typeof optValue === 'string') {
          value = optValue;
        } else {
          var textarea = document.querySelector('.dossier-field-edit[data-field="' + fieldKey + '"]');
          if (!textarea) return;
          value = textarea.value || '';
        }
        var body = {};
        body[fieldKey] = value;
        var url = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(state.selectedClientId) + '/dossier/profile');
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
          .then(function(r) {
            return r.json().then(function(data) {
              if (!r.ok) throw new Error((data && data.detail) || r.statusText || 'save');
              return data;
            });
          })
          .then(function(data) {
            dossierState.profile = Object.assign({}, dossierState.profile, data);
            dossierState.editingField = null;
            renderDossier();
          })
          .catch(function() {
            alert('Ошибка сохранения');
          });
      }

      function saveNewEntry() {
        var textarea = document.getElementById('newEntryContent');
        if (!textarea || !textarea.value.trim()) return;
        var url = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(state.selectedClientId) + '/dossier/entries');
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: textarea.value }),
        }).then(function(r) { return r.json(); }).then(function(data) {
          if (data.entry) {
            dossierState.entries.unshift(data.entry);
          }
          dossierState.showNewEntry = false;
          renderDossier();
        }).catch(function() {
          alert('Ошибка сохранения');
        });
      }

      function deleteEntry(entryId) {
        if (!confirm('Удалить эту заметку?')) return;
        var url = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(state.selectedClientId) + '/dossier/entries/' + entryId);
        fetch(url, { method: 'DELETE' }).then(function(r) {
          if (r.ok) {
            dossierState.entries = dossierState.entries.filter(function(e) { return e.id !== entryId; });
            renderDossier();
          }
        });
      }

      function removeTag(tagId) {
        var url = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(state.selectedClientId) + '/dossier/tags/' + tagId);
        fetch(url, { method: 'DELETE' }).then(function(r) {
          if (r.ok) {
            dossierState.tags = dossierState.tags.filter(function(t) { return t.id !== tagId; });
            renderDossier();
          }
        });
      }

      function addTag(tag, category) {
        var url = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(state.selectedClientId) + '/dossier/tags');
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tag: tag, category: category || 'custom' }),
        }).then(function(r) { return r.json(); }).then(function(data) {
          if (data.tag) {
            dossierState.tags.push(data.tag);
            renderDossier();
          }
          closeTagPicker();
        }).catch(function() {
          alert('Ошибка добавления тега');
        });
      }

      function openTagPicker() {
        var existingTags = dossierState.tags.map(function(t) { return t.tag.toLowerCase(); });
        var categories = {
          injury: { title: 'Травмы', tags: [] },
          level: { title: 'Уровень', tags: [] },
          goal: { title: 'Цели', tags: [] },
          schedule: { title: 'Расписание', tags: [] },
          skills: { title: 'Навыки', tags: [] },
        };
        dossierState.suggestedTags.forEach(function(s) {
          if (existingTags.indexOf(s.tag.toLowerCase()) === -1 && categories[s.category]) {
            categories[s.category].tags.push(s);
          }
        });
        var html = '<div class="tag-picker-overlay" id="tagPickerOverlay">';
        html += '<div class="tag-picker">';
        html += '<div class="tag-picker-title">Добавить метку</div>';
        Object.keys(categories).forEach(function(cat) {
          var c = categories[cat];
          if (c.tags.length) {
            html += '<div class="tag-picker-section"><div class="tag-picker-section-title">' + escapeHtml(c.title) + '</div>';
            html += '<div class="tag-picker-options">';
            c.tags.forEach(function(t) {
              html += '<button type="button" class="tag-picker-option" data-tag="' + escapeHtml(t.tag) + '" data-cat="' + escapeHtml(t.category) + '">' + escapeHtml(t.tag) + '</button>';
            });
            html += '</div></div>';
          }
        });
        html += '<div class="tag-picker-custom"><input type="text" id="customTagInput" placeholder="Или введите свою метку..."></div>';
        html += '<div class="tag-picker-actions"><button type="button" class="tag-picker-close" id="btnCloseTagPicker">Отмена</button><button type="button" class="tag-picker-add" id="btnAddCustomTag">Добавить</button></div>';
        html += '</div></div>';
        document.body.insertAdjacentHTML('beforeend', html);
        document.querySelectorAll('.tag-picker-option').forEach(function(btn) {
          btn.onclick = function() {
            addTag(btn.dataset.tag, btn.dataset.cat);
          };
        });
        document.getElementById('btnCloseTagPicker').onclick = closeTagPicker;
        document.getElementById('btnAddCustomTag').onclick = function() {
          var input = document.getElementById('customTagInput');
          if (input && input.value.trim()) {
            addTag(input.value.trim(), 'custom');
          }
        };
        document.getElementById('tagPickerOverlay').onclick = function(e) {
          if (e.target.id === 'tagPickerOverlay') closeTagPicker();
        };
      }

      function closeTagPicker() {
        var overlay = document.getElementById('tagPickerOverlay');
        if (overlay) overlay.remove();
      }

      /**
       * Client card «Написать»: prefer native Telegram DM when Mini App allows (public @username);
       * relay modal only when DM is unreliable — mirrors hub / schedule-editor (TrainerRelayHelpers).
       */
      function openTrainerClientTelegramDm(c) {
        if (!c) return;
        var H = window.TrainerRelayHelpers;
        var ctx = H ? H.contextFromTrainerClient(c) : null;
        if (ctx && H.shouldUseRelayModal(ctx)) {
          if (H.openRelaySendModalForContext(ctx, { subtitle: trainerClientDisplayName(c) })) {
            return;
          }
        }
        var un = String(c.telegram_username || '').replace(/^@/, '').trim();
        var tid = c.telegram_id;
        if (typeof window.openTelegramChatFromMiniApp === 'function') {
          window.openTelegramChatFromMiniApp({
            username: un || undefined,
            telegramId: tid != null && tid !== '' ? tid : undefined,
          });
          return;
        }
        if (un) {
          var u2 = 'https://t.me/' + encodeURIComponent(un);
          if (tg && typeof tg.openTelegramLink === 'function') {
            try {
              tg.openTelegramLink(u2);
              return;
            } catch (e) { /* continue */ }
          }
          if (tg && typeof tg.openLink === 'function') {
            try {
              tg.openLink(u2, { try_instant_view: false });
              return;
            } catch (e2) { /* continue */ }
          }
          window.location.href = u2;
        }
      }

      function mergeTrainerClientRowFromCard(cardClient) {
        var cid = cardClient && cardClient.id;
        if (cid == null) return null;
        var ix = state.allClients.findIndex(function(c) {
          return c.id === cid;
        });
        if (ix >= 0) {
          Object.assign(state.allClients[ix], cardClient);
          refreshClientListView();
          return state.allClients[ix];
        }
        return cardClient;
      }

      function applyTrainerClientDetailHero(c) {
        if (!c) return;
        var raw = trainerClientDisplayName(c).trim();
        var shown = raw || 'Клиент';
        var h = document.getElementById('tcClientHeroName');
        var av = document.querySelector('.tc-detail .tc-avatar');
        if (h) h.textContent = shown;
        if (av) av.textContent = clientInitials(shown === 'Клиент' && !raw ? '' : shown);
        var fn = document.getElementById('tcIdFirstName');
        var ln = document.getElementById('tcIdLastName');
        var mn = document.getElementById('tcIdMiddleName');
        if (fn) fn.value = (c.first_name || '').trim();
        if (ln) ln.value = (c.last_name || '').trim();
        if (mn) mn.value = (c.middle_name || '').trim();
      }

      function wireTrainerClientDetach(clientId) {
        var modal = document.getElementById('tcModalDetachClient');
        var btnOpen = document.getElementById('tcDetachClientBtn');
        var btnCancel = document.getElementById('tcDetachCancel');
        var btnOk = document.getElementById('tcDetachConfirm');
        if (!modal || !btnOpen || !btnCancel || !btnOk) return;
        function closeM() {
          modal.style.display = 'none';
          modal.setAttribute('aria-hidden', 'true');
          btnOk.disabled = false;
        }
        btnOpen.onclick = function(ev) {
          ev.preventDefault();
          modal.style.display = 'flex';
          modal.setAttribute('aria-hidden', 'false');
        };
        btnCancel.onclick = function(ev) {
          ev.preventDefault();
          closeM();
        };
        modal.onclick = function(ev) {
          if (ev.target === modal) closeM();
        };
        btnOk.onclick = function(ev) {
          ev.preventDefault();
          btnOk.disabled = true;
          fetch(withInit('/api/webapp/trainer/clients/' + encodeURIComponent(clientId) + '/detach'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
          })
            .then(function(r) {
              return r.json().then(function(d) {
                var msg =
                  typeof (d && d.detail) === 'string'
                    ? d.detail
                    : r.statusText || 'Ошибка';
                if (!r.ok) throw new Error(msg);
                return d;
              });
            })
            .then(function(d) {
              closeM();
              var n =
                typeof d.cancelled_upcoming_bookings === 'number'
                  ? d.cancelled_upcoming_bookings
                  : 0;
              var roster = !!d.roster_removed;
              var parts = [];
              if (n > 0) parts.push('Отменено предстоящих записей: ' + n + '.');
              if (roster) parts.push('Клиент убран из быстрого списка.');
              if (!parts.length) parts.push('Готово.');
              showTcToast(parts.join(' '));
              state.allClients = state.allClients.filter(function(c) {
                return c.id !== clientId;
              });
              refreshClientListView();
              backToListFromDetail();
            })
            .catch(function(err) {
              alert(err.message || 'Ошибка');
            })
            .finally(function() {
              btnOk.disabled = false;
            });
        };
      }

      function wireTrainerClientIdentityEditor(clientId) {
        var toggle = document.getElementById('tcIdentityEditToggle');
        var panel = document.getElementById('tcIdentityPanel');
        var cancel = document.getElementById('tcIdentityCancel');
        var save = document.getElementById('tcIdentitySave');
        if (!toggle || !panel) return;
        function closePanel() {
          panel.hidden = true;
          toggle.setAttribute('aria-expanded', 'false');
        }
        function openPanel() {
          panel.hidden = false;
          toggle.setAttribute('aria-expanded', 'true');
          var fn = document.getElementById('tcIdFirstName');
          if (fn) fn.focus();
        }
        toggle.addEventListener('click', function(ev) {
          ev.preventDefault();
          if (panel.hidden) openPanel();
          else closePanel();
        });
        if (cancel) {
          cancel.addEventListener('click', function(ev) {
            ev.preventDefault();
            var row = state.allClients.find(function(x) {
              return x.id === clientId;
            });
            if (row) applyTrainerClientDetailHero(row);
            closePanel();
          });
        }
        if (save) {
          save.addEventListener('click', function(ev) {
            ev.preventDefault();
            var fnEl = document.getElementById('tcIdFirstName');
            var lnEl = document.getElementById('tcIdLastName');
            var mnEl = document.getElementById('tcIdMiddleName');
            var body = {
              first_name: fnEl ? fnEl.value.trim() : '',
              last_name: lnEl ? lnEl.value.trim() : '',
              middle_name: mnEl ? mnEl.value.trim() : '',
            };
            save.disabled = true;
            fetch(withInit('/api/webapp/trainer/clients/' + encodeURIComponent(clientId) + '/identity'), {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(body),
            })
              .then(function(r) {
                return r.json().then(function(d) {
                  if (!r.ok) throw new Error((d && d.detail) || r.statusText || 'Ошибка');
                  return d;
                });
              })
              .then(function(data) {
                var cc = data.client;
                mergeTrainerClientRowFromCard(cc);
                applyTrainerClientDetailHero(cc);
                closePanel();
                showTcToast('ФИО сохранены');
              })
              .catch(function(err) {
                alert(err.message || 'Ошибка');
              })
              .finally(function() {
                save.disabled = false;
              });
          });
        }
      }

      function openClientDetail(id) {
        var client = state.allClients.find(function(c) {
          return c.id === id;
        });
        if (!client) return;
        state.selectedClientId = id;
        var isSandbox = !!client.is_sandbox;
        var displayNameRaw = trainerClientDisplayName(client);
        var name = displayNameRaw.trim() || 'Клиент';
        var fn0 = (client.first_name || '').trim();
        var ln0 = (client.last_name || '').trim();
        var mn0 = (client.middle_name || '').trim();
        var phone = isSandbox ? '—' : (client.phone || '—');
        var lastLabel = client.last_date
          ? (formatDate(client.last_date) + (client.last_start ? ' ' + formatTime(client.last_start) : ''))
          : '—';
        var firstDateLabel = isSandbox
          ? ''
          : (client.first_date ? ('Клиент с ' + formatDate(client.first_date)) : '');
        var initials = clientInitials(name);
        var phoneDisplay = escapeHtml(phone);
        if (phone !== '—') {
          var PfTel = window.CrmPhoneField;
          phoneDisplay =
            PfTel && typeof PfTel.phoneTelLinkHtml === 'function'
              ? PfTel.phoneTelLinkHtml(phone, 'tc-tel', escapeHtml)
              : phoneDisplay;
        }
        var ICO_CAL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>';
        /* Ticket/coupon silhouette (readability vs generic “card” rectangle) */
        var ICO_TICKET = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2"/><path d="M13 11v2"/><path d="M13 17v2"/></svg>';
        var ICO_PHONE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>';
        var ICO_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
        var ICO_MSG_BUBBLE =
          '<svg class="tc-hero-dm-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>';
        var ICO_PENCIL =
          '<svg class="tc-name-edit-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z"/></svg>';
        var ICO_TRASH =
          '<svg class="tc-remove-client-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>';
        var Htc = window.TrainerRelayHelpers;
        var tcRelayCtx = Htc ? Htc.contextFromTrainerClient(client) : null;
        var canDm = !isSandbox && !!(tcRelayCtx && Htc.canShowTrainerMessageButton(tcRelayCtx));
        var useRelayModalUi =
          !isSandbox && !!(tcRelayCtx && Htc.shouldUseRelayModal(tcRelayCtx));
        var heroRelayCls = useRelayModalUi ? ' tc-hero-dm--relay' : '';
        var dmHeroTip =
          heroRelayCls
            ? 'Сообщение через бота клиента — ответ в бот тренера'
            : 'Написать в Telegram';
        var heroDmBtn = '';
        if (canDm) {
          heroDmBtn =
            '<button type=\"button\" class=\"tc-hero-dm' +
            heroRelayCls +
            '\" id=\"tcClientHeroDm\" aria-label=\"' +
            escapeHtml(dmHeroTip) +
            '\" title=\"' +
            escapeHtml(dmHeroTip) +
            '\">' +
            ICO_MSG_BUBBLE +
            '</button>';
        }
        // Sandbox: no hero toolbar; demo removal is «Удалить пример» in actions. Real clients: edit + message only.
        var heroActionsBar = isSandbox
          ? ''
          : (
            '<div class=\"tc-hero-actions\" role=\"toolbar\" aria-label=\"Действия\">' +
            '<button type=\"button\" class=\"tc-name-edit-btn\" id=\"tcIdentityEditToggle\" aria-label=\"Редактировать ФИО\" title=\"Редактировать ФИО\" aria-expanded=\"false\">' +
            ICO_PENCIL +
            '</button>' +
            heroDmBtn +
            '</div>'
          );
        var sandboxBanner = isSandbox
          ? (
            '<div class=\"tc-sandbox-banner\" role=\"note\">' +
            '<span class=\"tc-sandbox-banner__pill\">Пример</span>' +
            '<p class=\"tc-sandbox-banner__text\">Тестовый клиент — нужен, чтобы посмотреть, как работают записи и карточка. ' +
            'Не учитывается в статистике, рассылках и подсказках. Можно удалить в любой момент.</p>' +
            '</div>'
          )
          : '';
        var detail = '' +
          '<div class=\"tc-detail' + (isSandbox ? ' tc-detail--sandbox' : '') + '\">' +
          sandboxBanner +
          '<div class=\"tc-hero\">' +
            '<div class=\"tc-avatar\" aria-hidden=\"true\">' + escapeHtml(initials) + '</div>' +
            '<div class=\"tc-hero-text\">' +
              '<h1 class=\"tc-name\" id=\"tcClientHeroName\">' + escapeHtml(name) + '</h1>' +
              '<div class=\"tc-identity-panel\" id=\"tcIdentityPanel\" hidden>' +
                '<div class=\"tc-identity-fields\">' +
                  '<label class=\"tc-identity-field\"><span class=\"tc-identity-label\">Имя</span>' +
                  '<input type=\"text\" class=\"tc-identity-input\" id=\"tcIdFirstName\" maxlength=\"64\" autocomplete=\"given-name\" value=\"' +
                  escapeHtml(fn0) +
                  '\"></label>' +
                  '<label class=\"tc-identity-field\"><span class=\"tc-identity-label\">Фамилия</span>' +
                  '<input type=\"text\" class=\"tc-identity-input\" id=\"tcIdLastName\" maxlength=\"64\" autocomplete=\"family-name\" value=\"' +
                  escapeHtml(ln0) +
                  '\"></label>' +
                  '<label class=\"tc-identity-field\"><span class=\"tc-identity-label\">Отчество</span>' +
                  '<input type=\"text\" class=\"tc-identity-input\" id=\"tcIdMiddleName\" maxlength=\"64\" autocomplete=\"additional-name\" placeholder=\"Необязательно\" value=\"' +
                  escapeHtml(mn0) +
                  '\"></label>' +
                '</div>' +
                '<div class=\"tc-identity-actions\">' +
                  '<button type=\"button\" class=\"bd-btn bd-btn--primary\" id=\"tcIdentitySave\">Сохранить</button>' +
                  '<button type=\"button\" class=\"bd-btn bd-btn--surface\" id=\"tcIdentityCancel\">Отмена</button>' +
                '</div>' +
              '</div>' +
              (firstDateLabel ? '<p class=\"tc-since\">' + escapeHtml(firstDateLabel) + '</p>' : '') +
            '</div>' +
            heroActionsBar +
          '</div>' +
          '<div class=\"tc-activity-panel\">' +
            '<div class=\"tc-stats\">' +
              '<span class=\"tc-stat\"><span class=\"tc-stat-label\">Последнее</span><strong id=\"clientLastLabel\">' + escapeHtml(lastLabel) + '</strong></span>' +
              '<span class=\"tc-stat\"><span class=\"tc-stat-label\">Следующее</span><strong id=\"clientNextBooking\" class=\"is-loading\"><span class=\"tc-stat-skel-block ma-skel-shimmer\" aria-hidden=\"true\"></span></strong></span>' +
              '<span class=\"tc-stat\" id=\"clientTotalWrap\"><span class=\"tc-stat-label\">Всего занятий</span><strong id=\"clientTotalCount\" class=\"is-loading\"><span class=\"tc-stat-skel-narrow ma-skel-shimmer\" aria-hidden=\"true\"></span></strong></span>' +
            '</div>' +
            (isSandbox
              ? ''
              : '<div id=\"clientHistoryHost\" class=\"tc-history-host\">' + buildClientHistorySkeletonHtml() + '</div>') +
          '</div>' +
          (isSandbox
            ? ''
            : '<div class=\"tc-self-book-host\" id=\"tcSelfBookWindowHost\" aria-busy=\"true\" aria-label=\"Самозапись\">' +
              '<details class=\"tc-self-book-details tc-self-book-details--loading\">' +
              '<summary class=\"tc-self-book-summary\">' +
              '<span class=\"tc-self-book-summary__title\">Самозапись</span>' +
              '<span class=\"tc-self-book-summary__value ma-skel-shimmer\" aria-hidden=\"true\"></span>' +
              '</summary></details></div>') +
          '<div class=\"tc-section-label\">Контакты и абонементы</div>' +
          '<div class=\"tc-rows\">' +
            '<div class=\"tc-row\"><div class=\"detail-label\">Телефон</div><div class=\"detail-value\">' + phoneDisplay + '</div></div>' +
            '<div class=\"tc-row\" id=\"clientPassesCertsBlock\">' +
              '<div class=\"detail-label\">Абонементы и сертификаты</div>' +
              '<div class=\"detail-value is-loading\" id=\"clientPassesCertsContent\">' + buildClientPassesSkeletonHtml() + '</div>' +
            '</div>' +
          '</div>' +
          (isSandbox
            ? ''
            : '<div id=\"tcRecurringHost\" class=\"tc-recurring-host\"></div>' +
              '<div id=\"dossierContainer\">' +
              buildClientDossierSkeletonHtml() +
              '</div>') +
          '<div class=\"tc-actions\">' +
            '<button type=\"button\" class=\"bd-btn bd-btn--primary\" id=\"btnBookClient\">' +
            '<span class=\"tc-action-btn__icon\" aria-hidden=\"true\">' + ICO_CAL + '</span>' +
            '<span class=\"tc-action-btn__label\">Записать на занятие</span></button>';
        if (!isSandbox) {
          detail += '<button type=\"button\" class=\"bd-btn bd-btn--secondary\" id=\"btnIssuePass\">' + ICO_TICKET + ' Выдать абонемент</button>';
          if (phone && phone !== '—') {
            detail += '<button type=\"button\" class=\"bd-btn bd-btn--surface\" id=\"btnCopyPhone\">' + ICO_PHONE + ' Скопировать телефон</button>';
          }
          if (canDm) {
            var dmBtnRelay = !!useRelayModalUi;
            var dmBtnTip = dmBtnRelay ? ' через бота' : '';
            detail +=
              '<button type=\"button\" class=\"bd-btn bd-btn--surface\" id=\"btnWriteClient\">' +
              ICO_SEND +
              ' Написать клиенту' +
              dmBtnTip +
              '</button>';
          }
          var showBindWelcome = client.telegram_id == null;
          if (showBindWelcome) {
            detail +=
              '<div class=\"tc-client-bind-welcome\" role=\"status\">' +
              '<div class=\"detail-label tc-client-bind-welcome__label\">Клиент ещё не в Telegram-боте</div>' +
              '<p class=\"tc-client-bind-welcome__hint\">Чтобы привязать профиль и получать напоминания, отправьте ту же общую пригласительную ссылку, что на главной странице кабинета — кнопка со значком связи справа вверху. Одна ссылка для всех клиентов.</p>' +
              '</div>';
          }
        } else {
          // Sandbox: scoped destructive action — deletes phantom client + every demo booking, no
          // confirm dialog from the trainer's side besides a single confirm() prompt below.
          detail +=
            '<button type=\"button\" class=\"bd-btn bd-btn--danger tc-sandbox-delete-btn\" id=\"btnDeleteSandbox\">' +
            ICO_TRASH + ' Удалить пример</button>';
        }
        detail += '</div></div>';
        document.getElementById('clientDetail').innerHTML = detail;
        if (window.CrmPhoneField && typeof window.CrmPhoneField.wirePhoneCallButtons === 'function') {
          window.CrmPhoneField.wirePhoneCallButtons(document.getElementById('clientDetail'));
        } else if (window.CrmPhoneField && typeof window.CrmPhoneField.wirePhoneTelLinks === 'function') {
          window.CrmPhoneField.wirePhoneTelLinks(document.getElementById('clientDetail'));
        }
        wireClientHistoryDiscoverability();
        document.getElementById('clientsSection').style.display = 'none';
        document.querySelector('.search-box').style.display = 'none';
        document.getElementById('detailSection').style.display = 'block';
        document.body.classList.add('client-detail-mode');
        var copyBtn = document.getElementById('btnCopyPhone');
        if (copyBtn && phone && phone !== '—') {
          copyBtn.onclick = async function() {
            try {
              if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(phone);
                alert('Телефон скопирован');
              }
            } catch (err) {
              alert('Скопируйте телефон вручную: ' + phone);
            }
          };
        }
        var heroDm = document.getElementById('tcClientHeroDm');
        function wireTrainerClientTelegramDms() {
          function go() {
            openTrainerClientTelegramDm(client);
          }
          if (heroDm) {
            heroDm.addEventListener('click', function(ev) {
              ev.preventDefault();
              ev.stopPropagation();
              go();
            }, true);
          }
          var writeBtn = document.getElementById('btnWriteClient');
          if (writeBtn) {
            writeBtn.onclick = go;
          }
        }
        wireTrainerClientTelegramDms();
        wireTrainerClientIdentityEditor(id);
        wireTrainerClientDetach(id);
        fetch(withInit('/api/webapp/trainer/clients/' + encodeURIComponent(id) + '/card'))
          .then(function(r) {
            return r.json().then(function(d) {
              if (!r.ok) throw new Error((d && d.detail) || r.statusText || '');
              return d;
            });
          })
          .then(function(data) {
            var cc = data && data.client;
            if (!cc) {
              finalizePendingOpenWriteModal(id, client);
              return;
            }
            mergeTrainerClientRowFromCard(cc);
            applyTrainerClientDetailHero(cc);
            finalizePendingOpenWriteModal(id, cc);
          })
          .catch(function() {
            finalizePendingOpenWriteModal(id, client);
            /* list snapshot already rendered */
          });
        // Load dossier (replaces old note loading)
        loadDossier(id);
        loadRecurringSection(id);
        loadClientHistory(id);
        (function loadPassesAndCerts() {
          var contentEl = document.getElementById('clientPassesCertsContent');
          if (!contentEl) return;
          var passesUrl = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(id) + '/passes');
          var certsUrl = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(id) + '/certificates');
          Promise.all([
            fetch(passesUrl).then(function(r) { return r.json().then(function(d) { if (!r.ok) throw new Error(d.detail || r.statusText); return d; }); }),
            fetch(certsUrl).then(function(r) { return r.json().then(function(d) { if (!r.ok) throw new Error(d.detail || r.statusText); return d; }); }),
          ]).then(function(results) {
            var passes = (results[0] && results[0].items) ? results[0].items : [];
            var certs = (results[1] && results[1].items) ? results[1].items : [];
            var activePasses = passes.filter(function(p) { return (p.status || '') === 'active'; });
            var activeCerts = certs.filter(function(c) { return (c.status || '') === 'active'; });
            var pathBase = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
            if (activePasses.length) {
              var passHtml = activePasses.map(function(p) {
                var total = typeof p.sessions_total === 'number' ? p.sessions_total : 0;
                var left = typeof p.sessions_remaining === 'number' ? p.sessions_remaining : 0;
                var name = (p.product_name || '').trim() || 'Абонемент';
                var canRedeem = left > 0;
                var label = name + ': ' + left + ' из ' + total;
                if (canRedeem) {
                  var href = pathBase + 'trainer-pass-products?pass_instance_id=' + encodeURIComponent(String(p.id)) +
                    '&client_id=' + encodeURIComponent(String(id)) + '&tab=issued';
                  return '<a class="tc-pass-link" href="' + href + '">' +
                    '<span>' + escapeHtml(label) + '</span>' +
                    '<span class="tc-pass-link__arrow" aria-hidden="true">→</span></a>';
                }
                return escapeHtml(label);
              }).join('');
              contentEl.innerHTML = '<div class="tc-passes-stack">' + passHtml + '</div>';
              if (activeCerts.length) {
                var certLines = activeCerts.map(function(c) {
                  var amount = typeof c.amount_cents === 'number' ? c.amount_cents / 100 + ' BYN' : '—';
                  return amount;
                });
                contentEl.innerHTML += '<div class="tc-pass-cert-extra">Сертификаты: ' + activeCerts.length +
                  ' активных (' + escapeHtml(certLines.join(', ')) + ')</div>';
              }
            } else {
              var parts = [];
              if (passes.length) parts.push('Абонементы: нет активных');
              if (activeCerts.length) {
                var certLines2 = activeCerts.map(function(c) {
                  var amount = typeof c.amount_cents === 'number' ? c.amount_cents / 100 + ' BYN' : '—';
                  return amount;
                });
                parts.push('Сертификаты: ' + activeCerts.length + ' активных (' + certLines2.join(', ') + ')');
              } else if (certs.length) {
                parts.push('Сертификаты: нет активных');
              }
              if (!parts.length) parts.push('Нет активных абонементов и сертификатов');
              contentEl.textContent = parts.join(' · ');
            }
            contentEl.classList.remove('is-loading');
            contentEl.classList.add('tc-reveal-once');
          }).catch(function() {
            contentEl.classList.remove('is-loading');
            contentEl.textContent = 'Не удалось загрузить';
            contentEl.classList.add('tc-reveal-once');
          });
        })();
        refreshClientNextBookingBlock(id);
        var bookBtn = document.getElementById('btnBookClient');
        if (bookBtn) {
          bookBtn.onclick = function() {
            if (window.TcClientQuickBook && typeof window.TcClientQuickBook.open === 'function') {
              window.TcClientQuickBook.open(id, name);
            } else {
              alert('Обновите страницу и попробуйте снова.');
            }
          };
        }
        var issuePassBtn = document.getElementById('btnIssuePass');
        if (issuePassBtn) {
          issuePassBtn.onclick = function() {
            var path = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
            var passUrl = path + 'trainer-pass-products?client_id=' + encodeURIComponent(id);
            window.location.href = passUrl;
          };
        }
        var deleteSandboxBtn = document.getElementById('btnDeleteSandbox');
        if (deleteSandboxBtn) {
          deleteSandboxBtn.onclick = function() {
            if (deleteSandboxBtn.disabled) return;
            if (!window.confirm('Удалить тестового клиента и все связанные с ним пробные записи? Это действие нельзя отменить.')) return;
            deleteSandboxBtn.disabled = true;
            var url = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(id) + '/sandbox');
            fetch(url, { method: 'DELETE', headers: { 'Content-Type': 'application/json' } })
              .then(function(r) {
                if (!r.ok) {
                  return r.json().then(function(data) {
                    throw new Error((data && data.detail) || r.statusText || 'Ошибка удаления');
                  }, function() {
                    throw new Error(r.statusText || 'Ошибка удаления');
                  });
                }
                return r.json().catch(function() { return {}; });
              })
              .then(function() {
                state.allClients = state.allClients.filter(function(x) { return x.id !== id; });
                refreshClientListView();
                document.getElementById('detailSection').style.display = 'none';
                document.getElementById('clientsSection').style.display = '';
                var sb = document.querySelector('.search-box');
                if (sb) sb.style.display = '';
                document.body.classList.remove('client-detail-mode');
              })
              .catch(function(err) {
                deleteSandboxBtn.disabled = false;
                alert((err && err.message) || 'Не удалось удалить пример');
              });
          };
        }
        updateReturnBookingBackUi();
      }

      /** Deep link: /webapp/trainer-clients?client_id=123 (initData comes from Telegram WebApp, not required in URL). */
      function tryOpenClientFromQuery() {
        var p = new URLSearchParams(window.location.search || '');
        var cid = p.get('client_id');
        if (!cid) return;
        var id = parseInt(cid, 10);
        if (!id) return;
        try {
          history.replaceState({}, '', window.location.pathname);
        } catch (e) { /* ignore */ }
        var client = state.allClients.find(function(c) { return c.id === id; });
        if (client) {
          openClientDetail(id);
          return;
        }
        var cardUrl = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(id) + '/card');
        fetch(cardUrl, { headers: { 'Content-Type': 'application/json' } })
          .then(function(r) {
            return r.json().then(function(data) {
              if (!r.ok) throw new Error((data && data.detail) || r.statusText || 'Ошибка');
              return data;
            });
          })
          .then(function(data) {
            var c = data && data.client;
            if (!c || c.id == null) throw new Error('Нет данных клиента');
            state.allClients = state.allClients.filter(function(x) { return x.id !== c.id; });
            state.allClients.unshift(c);
            if (state.focusInviteBot) {
              refreshClientListView();
            } else {
              state.filteredClients = state.allClients.slice();
            }
            renderList();
            openClientDetail(id);
          })
          .catch(function(err) {
            setStateMessage(err.message || 'Клиент недоступен', 'error');
          });
      }

      function mergeFullClientList(data) {
        state.allClients = data.clients || [];
        refreshClientListView();
      }

      function loadClientsInternal() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        state.clientsListLoading = true;
        setStateMessage('');
        renderList();
        var url = withInit('/api/webapp/trainer/clients');
        var qs = buildClientsListQueryString();
        if (qs) url += (url.indexOf('?') >= 0 ? '&' : '?') + qs;
        fetch(url, { headers: {} })
          .then(function(r) {
            return r.json().then(function(data) {
              if (!r.ok) throw new Error(data.detail || r.statusText);
              return data;
            });
          })
          .then(function(data) {
            state.allClients = data.clients || [];
            state.clientsListLoading = false;
            setStateMessage('');
            afterClientsLoaded();
            tryOpenClientFromQuery();
          })
          .catch(function(err) {
            console.error(err);
            state.clientsListLoading = false;
            renderList();
            setStateMessage('Не удалось загрузить клиентов. Попробуйте ещё раз.', 'error');
          });
      }

      /**
       * If URL has ?client_id=, load that card first (fast path). Otherwise full list first.
       * Fixes long "Загрузка…" and flaky deep link when the list API is slow.
       */
      function loadClients() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        var p = new URLSearchParams(window.location.search || '');
        var cidRaw = p.get('client_id');
        if (cidRaw && !state.deepLinkPrefetchDone) {
          var idFromUrl = parseInt(cidRaw, 10);
          if (idFromUrl && !isNaN(idFromUrl)) {
            state.deepLinkPrefetchDone = true;
            state.clientsListLoading = true;
            setStateMessage('');
            renderList();
            var cardUrl = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(idFromUrl) + '/card');
            var hdrs = { Accept: 'application/json', 'Content-Type': 'application/json' };
            var idDeep = getTrainerWebAppInitData();
            if (idDeep) hdrs['X-Telegram-Init-Data'] = idDeep;
            fetch(cardUrl, { headers: hdrs })
              .then(function(r) {
                return r.json().then(function(data) {
                  if (!r.ok) throw new Error((data && data.detail) || r.statusText || 'Ошибка');
                  return data;
                });
              })
              .then(function(data) {
                var c = data && data.client;
                if (!c || c.id == null) throw new Error('Нет данных клиента');
                try {
                  history.replaceState({}, '', window.location.pathname);
                } catch (e) {}
                state.allClients = state.allClients.filter(function(x) { return x.id !== c.id; });
                state.allClients.unshift(c);
                state.clientsListLoading = false;
                if (state.focusInviteBot) {
                  refreshClientListView();
                } else {
                  state.filteredClients = state.allClients.slice();
                }
                renderList();
                openClientDetail(idFromUrl);
                setStateMessage('');
                var listUrl = withInit('/api/webapp/trainer/clients');
                var listQs = buildClientsListQueryString();
                if (listQs) listUrl += (listUrl.indexOf('?') >= 0 ? '&' : '?') + listQs;
                fetch(listUrl, { headers: {} })
                  .then(function(r2) {
                    return r2.json().then(function(d2) {
                      if (!r2.ok) throw new Error(d2.detail || r2.statusText);
                      return d2;
                    });
                  })
                  .then(function(d2) {
                    mergeFullClientList(d2);
                  })
                  .catch(function() { /* keep partial list from card */ });
              })
              .catch(function(err) {
                try {
                  history.replaceState({}, '', window.location.pathname);
                } catch (e2) {}
                state.deepLinkPrefetchDone = false;
                setStateMessage(err.message || 'Клиент недоступен', 'error');
                loadClientsInternal();
              });
            return;
          }
        }
        loadClientsInternal();
      }

      window.addEventListener('popstate', syncTrainerClientsHeaderBack);

      document.getElementById('searchInput').addEventListener('input', function() {
        applyFilter();
      });

      var clientFiltersEl = document.getElementById('tcClientFilters');
      if (clientFiltersEl) {
        clientFiltersEl.addEventListener('click', function(ev) {
          var btn = ev.target && ev.target.closest && ev.target.closest('.tc-chip-filter[data-filter]');
          if (!btn) return;
          if (window.Telegram && window.Telegram.WebApp && typeof window.Telegram.WebApp.HapticFeedback.selectionChanged === 'function') {
            window.Telegram.WebApp.HapticFeedback.selectionChanged();
          }
          onClientFilterChipClick(btn);
        });
      }
      syncClientFilterChipsUi();

      // Tap outside "Заметка тренера" → blur and dismiss keyboard (important in Telegram WebView)
      var detailSectionEl = document.getElementById('detailSection');
      if (detailSectionEl) {
        detailSectionEl.addEventListener('click', function(e) {
          var noteInput = document.getElementById('clientNoteInput');
          if (!noteInput) return;
          if (e.target !== noteInput && !noteInput.contains(e.target)) {
            noteInput.blur();
          }
        });
      }

      var modalAddClient = document.getElementById('tcModalAddClient');
      var btnOpenAddClient = document.getElementById('btnOpenAddClient');
      if (btnOpenAddClient) {
        btnOpenAddClient.onclick = function() {
          openAddClientModal();
        };
      }
      if (modalAddClient) {
        modalAddClient.addEventListener('click', function(ev) {
          if (ev.target === modalAddClient) closeAddClientModal();
        });
      }
      var btnAddClientCancel = document.getElementById('tcAddClientCancel');
      if (btnAddClientCancel) btnAddClientCancel.onclick = function() { closeAddClientModal(); };
      var btnAddClientSubmit = document.getElementById('tcAddClientSubmit');
      if (btnAddClientSubmit) {
        btnAddClientSubmit.onclick = function() {
          setAddClientErr('');
          var phCheck = validatePhoneTrainerClientFromField();
          if (!phCheck.ok) {
            setAddClientErr(phCheck.error || 'Укажите номер телефона.');
            return;
          }
          var phone = phCheck.e164;
          var first = (document.getElementById('tcAddClientFirst').value || '').trim();
          if (!first) {
            setAddClientErr('Укажите имя.');
            return;
          }
          var last = (document.getElementById('tcAddClientLast').value || '').trim();
          var middle = (document.getElementById('tcAddClientMiddle').value || '').trim();
          btnAddClientSubmit.disabled = true;
          var hdrs = { Accept: 'application/json', 'Content-Type': 'application/json' };
          var idPost = getTrainerWebAppInitData();
          if (idPost) hdrs['X-Telegram-Init-Data'] = idPost;
          fetch(withInit('/api/webapp/trainer/clients'), {
            method: 'POST',
            headers: hdrs,
            body: JSON.stringify({
              phone: phone,
              first_name: first,
              last_name: last,
              middle_name: middle,
            }),
          })
            .then(function(r) {
              return r.json().then(function(data) {
                if (!r.ok) {
                  var d = data.detail;
                  var msg = Array.isArray(d) ? (d[0] && d[0].msg) || 'Ошибка' : d || 'Ошибка';
                  throw new Error(typeof msg === 'string' ? msg : 'Ошибка');
                }
                return data;
              });
            })
            .then(function(data) {
              var cid = parseInt(String(data.client_id), 10);
              if (isNaN(cid) || cid <= 0) throw new Error('Некорректный ответ сервера');
              var cardUrl = withInit('/api/webapp/trainer/clients/' + encodeURIComponent(cid) + '/card');
              return fetch(cardUrl, { headers: hdrs }).then(function(r2) {
                return r2.json().then(function(d2) {
                  if (!r2.ok) throw new Error((d2 && d2.detail) || r2.statusText);
                  return d2;
                });
              });
            })
            .then(function(d2) {
              var c = d2.client;
              if (!c || c.id == null) throw new Error('Нет данных');
              closeAddClientModal();
              state.allClients = state.allClients.filter(function(x) { return x.id !== c.id; });
              state.allClients.unshift(c);
              if (state.focusInviteBot) refreshClientListView();
              else state.filteredClients = state.allClients.slice();
              renderList();
              openClientDetail(c.id);
            })
            .catch(function(err) {
              setAddClientErr(err.message || 'Не удалось сохранить');
            })
            .finally(function() {
              btnAddClientSubmit.disabled = false;
            });
        };
      }

      initReturnContextFromQuery();
      initListFocusFromQuery();
      syncTrainerClientsHeaderBack();
      /* Back-forward cache: returning from schedule-editor can restore stale client HTML. */
      window.addEventListener('pageshow', function(ev) {
        if (!ev.persisted) return;
        try {
          var ds = document.getElementById('detailSection');
          if (!ds || ds.style.display === 'none') return;
          var sid = state.selectedClientId;
          if (sid == null || sid === '') return;
          refreshClientCardBookingsUi(sid);
        } catch (eP) { /* noop */ }
      });
      /**
       * Access check then list load. If GET /access never settles (tunnel drop), still load list after timeout.
       * When initData appears late, wait like schedule-editor (~15s) so gate + fetches see real init_data.
       */
      function runTrainerClientsBootAfterGate() {
        var id = getTrainerWebAppInitData();
        if (id && window.TrainerMiniAppGate) {
          var accessDone = false;
          var tAccess = setTimeout(function () {
            if (accessDone) return;
            accessDone = true;
            loadClients();
          }, 12000);
          window.TrainerMiniAppGate.fetchAccess(id)
            .then(function (a) {
              if (accessDone) {
                /* List may have loaded on timeout; still enforce gate if account is not active. */
                if (a && !window.TrainerMiniAppGate.isActive(a)) {
                  window.TrainerMiniAppGate.showBlockingOverlay(a);
                }
                return;
              }
              accessDone = true;
              clearTimeout(tAccess);
              if (a && !window.TrainerMiniAppGate.isActive(a)) {
                window.TrainerMiniAppGate.showBlockingOverlay(a);
                return;
              }
              loadClients();
            })
            .catch(function () {
              if (accessDone) return;
              accessDone = true;
              clearTimeout(tAccess);
              loadClients();
            });
        } else {
          loadClients();
        }
      }

      if (tg && !getTrainerWebAppInitData()) {
        var _nInit = 0;
        var _ivInit = setInterval(function () {
          _nInit++;
          if (getTrainerWebAppInitData()) {
            clearInterval(_ivInit);
            runTrainerClientsBootAfterGate();
            return;
          }
          if (_nInit >= 300) {
            clearInterval(_ivInit);
            runTrainerClientsBootAfterGate();
          }
        }, 50);
      } else {
        runTrainerClientsBootAfterGate();
      }
    })();
