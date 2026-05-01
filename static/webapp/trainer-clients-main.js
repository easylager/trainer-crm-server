    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        if (typeof tg.ready === 'function') tg.ready();
        if (typeof tg.expand === 'function') tg.expand();
        if (typeof window.__applyTrainerClientsTheme === 'function') {
          window.__applyTrainerClientsTheme();
        }
        try {
          var darkUi = tg.colorScheme === 'dark' ||
            (tg.colorScheme !== 'light' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
          var bgHex = darkUi ? '#1a1a1a' : '#fffbeb';
          if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
          if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
        } catch (e) { /* older clients */ }
        if (tg.onEvent) {
          tg.onEvent('themeChanged', function () {
            if (typeof window.__applyTrainerClientsTheme === 'function') {
              window.__applyTrainerClientsTheme();
            }
            try {
              var du = tg.colorScheme === 'dark' ||
                (tg.colorScheme !== 'light' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
              var bg = du ? '#1a1a1a' : '#fffbeb';
              if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bg);
              if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bg);
            } catch (err) { /* ignore */ }
          });
        }
      }
      var initData = tg && tg.initData ? tg.initData : '';
      var headerTitleEl = document.querySelector('.header-title');
      var defaultHeaderTitle = headerTitleEl ? headerTitleEl.textContent : '';

      function withInit(url) {
        if (!initData) return url;
        return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(initData);
      }

      function postClientInviteLinkFirstCopyRecorded() {
        if (!initData) return;
        fetch(withInit('/api/webapp/trainer/welcome-link/first-copy'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }).catch(function() {});
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
        /** Cached GET /trainer/welcome-link/eligibility for invite link flow. */
        inviteWelcomeMeta: null,
        /** Deep link ?focus=invite_bot — list only clients without telegram_id + banner (from hub rhythm hint). */
        focusInviteBot: false,
      };

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
        } catch (e) { /* noop */ }
      }

      function navigateToScheduleBooking() {
        if (!state.returnBookingId) return;
        var path = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
        var u = path + 'schedule-editor?open_booking=' + encodeURIComponent(String(state.returnBookingId));
        if (state.returnFromHub) u += '&from=hub';
        if (initData) u += (u.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
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
        document.querySelector('.search-box').style.display = 'block';
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
        if (initData) u += (u.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
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
              if (initData) uR += (uR.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
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
          el.style.display = 'none';
          if (inner) inner.textContent = '';
          el.className = 'loading state-panel';
          return;
        }
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
        fetch(withInit('/api/webapp/trainer/clients/' + encodeURIComponent(clientId) + '/next-booking'))
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

        function syncTcQuickBookDurationFromGrid() {
          var stack = document.getElementById('tcQuickBookDurationStack');
          var hint = document.getElementById('tcQuickBookDurationFixedHint');
          var durEl = document.getElementById('tcQuickBookDuration');
          if (!durEl) return;
          var fixed = tcFixedSlotDurationMinutes();
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
            if (!isNaN(s) && s >= 5) step = s;
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
            if (iv.start === startMinutes && iv.end === newEnd) {
              if (occ >= 1) return 'busy';
              return 'free';
            }
            if (occ >= 1) return 'busy';
            return 'overlap';
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
            return Promise.resolve();
          }
          var fetchGen = ++qb.fetchGen;
          sel.disabled = true;
          if (btnGo) btnGo.disabled = true;
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
          if (qb.refreshTimer) {
            clearTimeout(qb.refreshTimer);
            qb.refreshTimer = null;
          }
          qb.fetchGen += 1;
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
          closeDatetimeModal();
          qb.lockedClientId = null;
          qb.clientDisplayName = '';
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
      
        function syncPriceTierRadios(preferredVariantId) {
          var wrap = document.getElementById('tcQbProfilePriceTierWrap');
          var host = document.getElementById('tcQbProfilePriceTierRadios');
          if (!wrap || !host) return;
          var sid = qb.bookServiceId;
          var svc = (qb.bookServices || []).filter(function(x) {
            return x.id === sid;
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
            var pb = tier.price_byn;
            var priceStr = (pb === Math.floor(pb) ? pb : Number(pb).toFixed(2)) + ' BYN';
            lab.appendChild(inp);
            lab.appendChild(document.createTextNode(priceTierLabelRu(tier) + ' — ' + priceStr));
            inp.addEventListener('change', function() {
              qb.bookPriceVariantId = parseInt(inp.value, 10);
            });
            host.appendChild(lab);
          });
          var pref = preferredVariantId != null ? parseInt(preferredVariantId, 10) : NaN;
          var matched = !isNaN(pref) ? host.querySelector('input[value="' + String(pref) + '"]') : null;
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
      
        function openServiceStepAfterDatetime() {
          var cid = qb.lockedClientId;
          if (!cid) return;
          Promise.all([
            fetch(api('/trainer/my-services'), { headers: {} }).then(function(r) {
              return r.ok ? r.json() : Promise.reject(new Error('svc'));
            }),
            fetch(api('/trainer/clients/' + encodeURIComponent(cid) + '/booking-defaults'), { headers: {} }).then(function(r) {
              return r.ok ? r.json() : Promise.reject(new Error('def'));
            }),
          ])
            .then(function(results) {
              var servicesPayload = results[0];
              var defaults = results[1];
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
              var picked = qb.bookServices.length ? qb.bookServices[0].id : null;
              if (!isNaN(defSid) && qb.bookServices.some(function(s) {
                return s.id === defSid;
              })) {
                picked = defSid;
              }
              qb.bookServiceId = picked;
              sel.value = picked != null ? String(picked) : '';
              sel.onchange = function() {
                qb.bookServiceId = this.value ? parseInt(this.value, 10) : null;
                syncPriceTierRadios(null);
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
              syncPriceTierRadios(defVid);
      
              var ms = document.getElementById('tcModalQuickBookService');
              if (ms) {
                ms.style.display = 'flex';
                ms.setAttribute('aria-hidden', 'false');
              }
              closeDatetimeModal();
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
                  closeAll();
                  showTcToast('Запись создана');
                  refreshClientNextBookingBlock(cid);
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
      
          var modal = document.getElementById('tcModalQuickBookDatetime');
          var dateEl = document.getElementById('tcQuickBookDate');
          var durEl = document.getElementById('tcQuickBookDuration');
          if (!modal || !dateEl || !durEl) {
            alert('Не удалось открыть форму записи. Обновите страницу.');
            return;
          }
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

      function applyFilter() {
        var q = (document.getElementById('searchInput').value || '').trim();
        var pool = state.allClients;
        if (state.focusInviteBot) {
          pool = state.allClients.filter(function(c) {
            return c.telegram_id == null || c.telegram_id === '';
          });
        }
        if (!q) {
          state.filteredClients = pool.slice();
        } else {
          var qLower = q.toLowerCase();
          var digits = q.replace(/\\D/g, '');
          state.filteredClients = pool.filter(function(c) {
            var name = trainerClientDisplayName(c).toLowerCase();
            var phone = (c.phone || '').toLowerCase();
            var phoneDigits = (c.phone || '').replace(/\\D/g, '');
            return name.indexOf(qLower) !== -1
              || phone.indexOf(qLower) !== -1
              || (digits && phoneDigits.indexOf(digits) !== -1);
          });
        }
        renderList();
      }

      function hideInviteBotBanner() {
        var b = document.getElementById('tcListFocusBanner');
        if (b) b.hidden = true;
      }

      function pluralRuClients(n) {
        var n10 = n % 10;
        var n100 = n % 100;
        if (n10 === 1 && n100 !== 11) return 'клиент';
        if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return 'клиента';
        return 'клиентов';
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
            ' без Telegram в боте. Откройте карточку и отправьте персональную ссылку — кнопка «Ссылка в клиентский бот (привязка профиля)».';
        }
      }

      function wireInviteBotBannerActions() {
        var btnAll = document.getElementById('tcListFocusShowAll');
        if (btnAll && !btnAll.dataset.wiredInviteFocus) {
          btnAll.dataset.wiredInviteFocus = '1';
          btnAll.onclick = function() {
            state.focusInviteBot = false;
            hideInviteBotBanner();
            var si = document.getElementById('searchInput');
            if (si) si.value = '';
            applyFilter();
          };
        }
      }

      function applyInviteBotFocusAfterLoad() {
        var noTg = state.allClients.filter(function(c) {
          return c.telegram_id == null || c.telegram_id === '';
        });
        if (!noTg.length) {
          state.focusInviteBot = false;
          hideInviteBotBanner();
          state.filteredClients = state.allClients.slice();
          renderList();
          showTcToast('Все клиенты уже в боте.');
          return;
        }
        showInviteBotBannerUi(noTg.length);
        wireInviteBotBannerActions();
        applyFilter();
      }

      function afterClientsLoaded() {
        if (state.focusInviteBot) {
          applyInviteBotFocusAfterLoad();
        } else {
          hideInviteBotBanner();
          state.filteredClients = state.allClients.slice();
          renderList();
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

      /** Placeholder layout for client card history block (replaced when GET /history returns). */
      function buildClientHistorySkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        return (
          '<div class="tc-history-wrap tc-history-wrap--skel" role="status" aria-busy="true" aria-label="Загрузка истории">' +
          '<div class="history-section-title">История занятий</div>' +
          '<div class="tc-history-skel-lines">' +
          '<div class="tc-history-skel-line ' + sk + '" aria-hidden="true"></div>' +
          '<div class="tc-history-skel-line tc-history-skel-line--short ' + sk + '" aria-hidden="true"></div>' +
          '<div class="tc-history-skel-line ' + sk + '" aria-hidden="true"></div>' +
          '<div class="tc-history-skel-line tc-history-skel-line--mid ' + sk + '" aria-hidden="true"></div>' +
          '</div></div>'
        );
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
          var qEmp = (document.getElementById('searchInput').value || '').trim();
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
            '<div class="empty"><div class="empty-inner"><div class="empty-title">Пока пусто</div>Пока нет клиентов с записями. Как только клиенты начнут записываться, они появятся здесь.</div></div>';
          return;
        }
        var html = state.filteredClients.map(function(c) {
          var name = trainerClientDisplayName(c).trim() || 'Клиент';
          var initials = clientInitials(name);
          var phone = c.phone || 'Телефон не указан';
          var lastLabel = c.last_date
            ? ('Последнее занятие: ' + formatDate(c.last_date) + (c.last_start ? ' ' + formatTime(c.last_start) : ''))
            : 'Был(а) на занятии ранее';
          var needsInvite = c.telegram_id == null || c.telegram_id === '';
          var badge =
            needsInvite
              ? '<span class="client-badge client-badge--no-tg">Нет в боте</span>'
              : '';
          return (
            '<button type=\"button\" class=\"client-card\" data-id=\"' + c.id + '\">' +
              '<div class=\"client-avatar\" aria-hidden=\"true\">' + escapeHtml(initials) + '</div>' +
              '<div class=\"client-main\">' +
                '<div class=\"client-name-row\">' +
                  '<span class=\"client-name\">' + escapeHtml(name) + '</span>' +
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
        var host = document.getElementById('clientHistoryHost');
        var url = '/api/webapp/trainer/clients/' + encodeURIComponent(id) + '/history?limit=10';
        url = withInit(url);
        fetch(url).then(function(r) {
          return r.json().then(function(data) {
            if (!r.ok) throw new Error(data.detail || r.statusText);
            return data;
          });
        }).then(function(data) {
          var items = data.items || [];
          var total = typeof data.total === 'number' ? data.total : items.length;
          var totalWrap = document.getElementById('clientTotalWrap');
          var totalCount = document.getElementById('clientTotalCount');
          if (totalWrap && totalCount) {
            totalCount.textContent = String(total);
            totalCount.classList.remove('is-loading');
          }
          var html = '';
          html += '<div class="tc-history-wrap tc-reveal-once"><div class="history-section-title">История занятий' + (total > 0 ? ' (' + total + ')' : '') + '</div>';
          if (!items.length) {
            html += '<div class="history-list">Пока нет занятий с этим клиентом.</div></div>';
          } else {
            var first = items.slice(0, 5);
            var rest = items.slice(5);
            var renderItem = function(it) {
              var dateStr = formatDate(it.slot_date);
              var timeStr = it.start_time ? formatTime(it.start_time) : '';
              var place = it.arena_name ? it.arena_name : '—';
              var status = (it.status || '').toLowerCase();
              var statusLabel = status === 'completed' ? 'прошло' : status === 'pending' ? 'ожидает' : status === 'confirmed' ? 'подтверждено' : status || '—';
              var serviceName = (it.service_name || '').trim() || '—';
              var line1 = dateStr + (timeStr ? ' ' + timeStr : '') + ' · ' + place + ' · ' + statusLabel;
              return '<div class="history-item">' + escapeHtml(line1) + '<div class="history-item-service">' + escapeHtml(serviceName) + '</div></div>';
            };
            html += '<div class="history-list">';
            first.forEach(function(it) { html += renderItem(it); });
            if (rest.length) {
              html += '<div id="historyMore" style="display:none;">';
              rest.forEach(function(it) { html += renderItem(it); });
              html += '</div>';
            }
            html += '</div>';
            if (rest.length) {
              html += '<div class="history-toggle"><button type="button" class="history-toggle-button" id="btnHistoryToggle">Показать все (' + items.length + ')</button></div>';
            }
            html += '</div>';
          }
          if (host) {
            host.innerHTML = html;
          } else {
            document.getElementById('clientDetail').insertAdjacentHTML('beforeend', html);
          }
          var toggle = document.getElementById('btnHistoryToggle');
          if (toggle) {
            toggle.onclick = function() {
              var more = document.getElementById('historyMore');
              if (!more) return;
              var isHidden = more.style.display === 'none';
              more.style.display = isHidden ? 'block' : 'none';
              toggle.textContent = isHidden ? 'Свернуть' : 'Показать все занятия';
            };
          }
        }).catch(function() {
          var totalCount = document.getElementById('clientTotalCount');
          if (totalCount) {
            totalCount.textContent = '—';
            totalCount.classList.remove('is-loading');
          }
          var errHtml =
            '<div class="tc-history-wrap tc-reveal-once"><div class="detail-label">История занятий</div><div class="detail-value">Не удалось загрузить историю.</div></div>';
          if (host) {
            host.innerHTML = errHtml;
          } else {
            document.getElementById('clientDetail').insertAdjacentHTML('beforeend', errHtml);
          }
        });
      }

      /* --- Dossier state and helpers --- */
      var dossierState = {
        profile: { note: '', goals: '', limitations: '', level: '', season_goal: '' },
        tags: [],
        entries: [],
        suggestedTags: [],
        suggestedSeasonGoals: [],
        editingField: null,
        showNewEntry: false,
        /** User-toggled accordion; reset on client change — profile starts collapsed even when fields are filled. */
        profileSectionExpanded: false,
      };

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
          html += '<span class="dossier-tag" data-id="' + t.id + '">' + escapeHtml(t.tag) +
            '<button type="button" class="dossier-tag-remove" data-id="' + t.id + '">' + ICO_X + '</button></span>';
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
        var profileExpanded =
          !!dossierState.editingField || !!dossierState.profileSectionExpanded;
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
          dossierState.editingField = null;
          dossierState.showNewEntry = false;
          dossierState.profileSectionExpanded = false;
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

      /** @see mini-app-telegram-chrome.js openTelegramChatFromMiniApp (t.me vs tg://, platform=web). */
      function trainerClientCanWriteTelegram(c) {
        if (!c) return false;
        var un = (c.telegram_username || '').replace(/^@/, '').trim();
        var tid = c.telegram_id;
        return !!un || (tid != null && tid !== '');
      }

      function openTrainerClientTelegramDm(c) {
        if (!c) return;
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
          applyFilter();
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
        var displayNameRaw = trainerClientDisplayName(client);
        var name = displayNameRaw.trim() || 'Клиент';
        var fn0 = (client.first_name || '').trim();
        var ln0 = (client.last_name || '').trim();
        var mn0 = (client.middle_name || '').trim();
        var phone = client.phone || '—';
        var lastLabel = client.last_date
          ? (formatDate(client.last_date) + (client.last_start ? ' ' + formatTime(client.last_start) : ''))
          : '—';
        var firstDateLabel = client.first_date ? ('Клиент с ' + formatDate(client.first_date)) : '';
        var initials = clientInitials(name);
        var phoneDisplay = phone !== '—'
          ? '<a class=\"tc-tel\" href=\"tel:' + escapeHtml(String(phone).replace(/\\s+/g, '')) + '\">' + escapeHtml(phone) + '</a>'
          : escapeHtml(phone);
        var ICO_CAL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>';
        /* Ticket/coupon silhouette (readability vs generic “card” rectangle) */
        var ICO_TICKET = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2"/><path d="M13 11v2"/><path d="M13 17v2"/></svg>';
        var ICO_PHONE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>';
        var ICO_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
        var ICO_MSG_BUBBLE =
          '<svg class="tc-hero-dm-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>';
        var ICO_PENCIL =
          '<svg class="tc-name-edit-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z"/></svg>';
        var canDm = trainerClientCanWriteTelegram(client);
        var heroDmBtn = '';
        if (canDm) {
          heroDmBtn =
            '<button type=\"button\" class=\"tc-hero-dm\" id=\"tcClientHeroDm\" aria-label=\"Написать в Telegram\" title=\"Написать в Telegram\">' +
            ICO_MSG_BUBBLE +
            '</button>';
        }
        var heroActionsBar =
          '<div class=\"tc-hero-actions\" role=\"toolbar\" aria-label=\"Действия\">' +
          '<button type=\"button\" class=\"tc-name-edit-btn\" id=\"tcIdentityEditToggle\" aria-label=\"Редактировать ФИО\" title=\"Редактировать ФИО\" aria-expanded=\"false\">' +
          ICO_PENCIL +
          '</button>' +
          heroDmBtn +
          '</div>';
        var detail = '' +
          '<div class=\"tc-detail\">' +
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
          '<div class=\"tc-stats\">' +
            '<span class=\"tc-stat\"><span class=\"tc-stat-label\">Последнее</span><strong id=\"clientLastLabel\">' + escapeHtml(lastLabel) + '</strong></span>' +
            '<span class=\"tc-stat\"><span class=\"tc-stat-label\">Следующее</span><strong id=\"clientNextBooking\" class=\"is-loading\"><span class=\"tc-stat-skel-block ma-skel-shimmer\" aria-hidden=\"true\"></span></strong></span>' +
            '<span class=\"tc-stat\" id=\"clientTotalWrap\"><span class=\"tc-stat-label\">Всего занятий</span><strong id=\"clientTotalCount\" class=\"is-loading\"><span class=\"tc-stat-skel-narrow ma-skel-shimmer\" aria-hidden=\"true\"></span></strong></span>' +
          '</div>' +
          '<div class=\"tc-section-label\">Контакты и абонементы</div>' +
          '<div class=\"tc-rows\">' +
            '<div class=\"tc-row\"><div class=\"detail-label\">Телефон</div><div class=\"detail-value\">' + phoneDisplay + '</div></div>' +
            '<div class=\"tc-row\" id=\"clientPassesCertsBlock\">' +
              '<div class=\"detail-label\">Абонементы и сертификаты</div>' +
              '<div class=\"detail-value is-loading\" id=\"clientPassesCertsContent\">' + buildClientPassesSkeletonHtml() + '</div>' +
            '</div>' +
          '</div>' +
          '<div id=\"dossierContainer\">' + buildClientDossierSkeletonHtml() + '</div>' +
          '<div class=\"tc-actions\">' +
            '<button type=\"button\" class=\"bd-btn bd-btn--primary\" id=\"btnBookClient\">' +
            '<span class=\"tc-action-btn__icon\" aria-hidden=\"true\">' + ICO_CAL + '</span>' +
            '<span class=\"tc-action-btn__label\">Записать на занятие</span></button>' +
            '<button type=\"button\" class=\"bd-btn bd-btn--secondary\" id=\"btnIssuePass\">' + ICO_TICKET + ' Выдать абонемент</button>';
        if (phone && phone !== '—') {
          detail += '<button type=\"button\" class=\"bd-btn bd-btn--surface\" id=\"btnCopyPhone\">' + ICO_PHONE + ' Скопировать телефон</button>';
        }
        if (canDm) {
          detail += '<button type=\"button\" class=\"bd-btn bd-btn--surface\" id=\"btnWriteClient\">' + ICO_SEND + ' Написать в TG</button>';
        }
        var showBindWelcome = client.telegram_id == null;
        if (showBindWelcome) {
          detail +=
            '<button type=\"button\" class=\"bd-btn bd-btn--surface\" id=\"btnClientBindWelcome\">Ссылка в клиентский бот (привязка профиля)</button>' +
            '<div id=\"clientPersonalWelcomeBlock\" class=\"tc-client-bind-welcome\" style=\"display:none;\">' +
            '<div class=\"detail-label tc-client-bind-welcome__label\">Одноразовая ссылка для этого клиента</div>' +
            '<div id=\"clientPersonalWelcomeUrl\" class=\"invite-link-url\"></div>' +
            '<button type=\"button\" class=\"bd-btn bd-btn--surface\" id=\"btnCopyClientPersonalWelcome\">Скопировать ссылку</button>' +
            '</div>';
        }
        detail +=
          '</div><div id=\"clientHistoryHost\" class=\"tc-history-host\">' +
          buildClientHistorySkeletonHtml() +
          '</div></div>';
        document.getElementById('clientDetail').innerHTML = detail;
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
        fetch(withInit('/api/webapp/trainer/clients/' + encodeURIComponent(id) + '/card'))
          .then(function(r) {
            return r.json().then(function(d) {
              if (!r.ok) throw new Error((d && d.detail) || r.statusText || '');
              return d;
            });
          })
          .then(function(data) {
            var cc = data && data.client;
            if (!cc) return;
            mergeTrainerClientRowFromCard(cc);
            applyTrainerClientDetailHero(cc);
          })
          .catch(function() {
            /* list snapshot already rendered */
          });
        if (showBindWelcome) {
          var bindBtn = document.getElementById('btnClientBindWelcome');
          if (bindBtn) {
            bindBtn.onclick = function() {
              var cid = state.selectedClientId;
              if (!cid) return;
              bindBtn.disabled = true;
              setStateMessage('');
              loadInviteWelcomeMeta()
                .then(function(meta) {
                  return resolveWelcomeServiceIdFromMeta(meta);
                })
                .then(function(sid) {
                  var u =
                    withInit('/api/webapp/trainer/clients/' + encodeURIComponent(cid) + '/welcome-link') +
                    '&service_id=' +
                    encodeURIComponent(sid);
                  return fetch(u, { headers: { 'Content-Type': 'application/json' } }).then(function(r) {
                    return r.json().then(function(o) {
                      if (!r.ok) throw new Error((o && o.detail) || r.statusText || 'Ошибка');
                      return o;
                    });
                  });
                })
                .then(function(o) {
                  var link = o.welcome_link;
                  var block = document.getElementById('clientPersonalWelcomeBlock');
                  var urlEl = document.getElementById('clientPersonalWelcomeUrl');
                  if (link && block && urlEl) {
                    urlEl.textContent = link;
                    block.style.display = 'block';
                    setStateMessage(
                      'Ссылка одноразовая: пусть клиент откроет её в Telegram с своего аккаунта.',
                      'hint'
                    );
                  } else {
                    setStateMessage('Ссылка недоступна. Откройте мини-приложение из бота тренера.', 'error');
                  }
                })
                .catch(function(err) {
                  if (err && err.message === 'Отменено') return;
                  setStateMessage(err.message || 'Ошибка', 'error');
                })
                .finally(function() {
                  bindBtn.disabled = false;
                });
            };
          }
          var copyBindBtn = document.getElementById('btnCopyClientPersonalWelcome');
          if (copyBindBtn) {
            copyBindBtn.onclick = function() {
              var el = document.getElementById('clientPersonalWelcomeUrl');
              var link = el && el.textContent;
              if (!link) return;
              if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard
                  .writeText(link)
                  .then(function() {
                    postClientInviteLinkFirstCopyRecorded();
                    alert('Ссылка скопирована');
                  })
                  .catch(function() {
                    alert(link);
                  });
              } else {
                alert(link);
              }
            };
          }
        }
        // Load dossier (replaces old note loading)
        loadDossier(id);
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
            var parts = [];
            if (activePasses.length) {
              var lines = activePasses.map(function(p) {
                var total = typeof p.sessions_total === 'number' ? p.sessions_total : 0;
                var left = typeof p.sessions_remaining === 'number' ? p.sessions_remaining : 0;
                var name = (p.product_name || '').trim() || 'Абонемент';
                return name + ': ' + left + ' из ' + total;
              });
              parts.push('Абонементы: ' + lines.join('; '));
            } else if (passes.length) {
              parts.push('Абонементы: нет активных');
            }
            if (activeCerts.length) {
              var certLines = activeCerts.map(function(c) {
                var amount = typeof c.amount_cents === 'number' ? (c.amount_cents / 100) + ' BYN' : '—';
                return amount;
              });
              parts.push('Сертификаты: ' + activeCerts.length + ' активных (' + certLines.join(', ') + ')');
            } else if (certs.length) {
              parts.push('Сертификаты: нет активных');
            }
            if (!parts.length) parts.push('Нет активных абонементов и сертификатов');
            contentEl.classList.remove('is-loading');
            contentEl.textContent = parts.join(' · ');
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
              applyFilter();
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
        if (state.focusInviteBot) {
          applyInviteBotFocusAfterLoad();
        } else {
          state.filteredClients = state.allClients.slice();
          renderList();
        }
      }

      function loadClientsInternal() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        state.clientsListLoading = true;
        setStateMessage('');
        renderList();
        var base = '/api/webapp/trainer/clients';
        var url = withInit(base);
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
            if (initData) hdrs['X-Telegram-Init-Data'] = initData;
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
                  applyFilter();
                } else {
                  state.filteredClients = state.allClients.slice();
                }
                renderList();
                openClientDetail(idFromUrl);
                setStateMessage('');
                var base = '/api/webapp/trainer/clients';
                fetch(withInit(base), { headers: {} })
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

      function loadInviteWelcomeMeta() {
        if (state.inviteWelcomeMeta) {
          return Promise.resolve(state.inviteWelcomeMeta);
        }
        return fetch(withInit('/api/webapp/trainer/welcome-link/eligibility'), {
          headers: { 'Content-Type': 'application/json' },
        })
          .then(function(r) {
            return r.json().then(function(data) {
              if (!r.ok) throw new Error((data && data.detail) || r.statusText || 'Ошибка');
              return data;
            });
          })
          .then(function(meta) {
            state.inviteWelcomeMeta = meta;
            return meta;
          });
      }

      /**
       * Resolve service_id for welcome-style links (generic or per-client bind).
       * When trainer has multiple services, opens a lightweight overlay to pick one.
       */
      function resolveWelcomeServiceIdFromMeta(meta) {
        return new Promise(function(resolve, reject) {
          var services = (meta && meta.services) || [];
          if (!services.length) {
            reject(new Error('В профиле нет услуг — добавьте услугу в профиле.'));
            return;
          }
          if (!meta.require_service_choice) {
            resolve(services[0].id);
            return;
          }
          var overlay = document.createElement('div');
          overlay.className = 'tag-picker-overlay';
          overlay.id = 'welcomeSvcPickerOverlay';
          overlay.setAttribute('role', 'dialog');
          overlay.innerHTML =
            '<div class="tag-picker" onclick="event.stopPropagation()">' +
            '<div class="tag-picker-title">Услуга для ссылки</div>' +
            '<select id="welcomeSvcPickerSelect" class="invite-service-select" aria-label="Услуга"></select>' +
            '<div class="tag-picker-actions">' +
            '<button type="button" class="tag-picker-close" id="welcomeSvcPickerCancel">Отмена</button>' +
            '<button type="button" class="tag-picker-add" id="welcomeSvcPickerOk">Далее</button>' +
            '</div></div>';
          document.body.appendChild(overlay);
          var sel = document.getElementById('welcomeSvcPickerSelect');
          var ph = document.createElement('option');
          ph.value = '';
          ph.textContent = '— Выберите услугу —';
          sel.appendChild(ph);
          services.forEach(function(s) {
            var opt = document.createElement('option');
            opt.value = String(s.id);
            opt.textContent = s.name || ('Услуга #' + s.id);
            sel.appendChild(opt);
          });
          function cleanup() {
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
          }
          overlay.onclick = function(e) {
            if (e.target !== overlay) return;
            cleanup();
            reject(new Error('Отменено'));
          };
          document.getElementById('welcomeSvcPickerCancel').onclick = function(e) {
            e.stopPropagation();
            cleanup();
            reject(new Error('Отменено'));
          };
          document.getElementById('welcomeSvcPickerOk').onclick = function(e) {
            e.stopPropagation();
            var sid = parseInt(sel.value, 10);
            if (!sid) {
              alert('Выберите услугу');
              return;
            }
            cleanup();
            resolve(sid);
          };
        });
      }

      function fetchGenericWelcomeLink(serviceId) {
        var base = withInit('/api/webapp/trainer/welcome-link');
        var url = base + '&service_id=' + encodeURIComponent(serviceId);
        return fetch(url, { headers: { 'Content-Type': 'application/json' } }).then(function(r) {
          return r.json().then(function(o) {
            if (!r.ok) throw new Error((o && o.detail) || r.statusText || 'Ошибка');
            return o;
          });
        });
      }

      document.getElementById('btnShowInviteLink').onclick = function() {
        var block = document.getElementById('inviteLinkBlock');
        var urlEl = document.getElementById('inviteLinkUrl');
        if (block.style.display === 'block' && urlEl.textContent) return;
        var btn = this;
        var row = document.getElementById('inviteServiceRow');
        var sel = document.getElementById('inviteServiceSelect');
        btn.disabled = true;
        loadInviteWelcomeMeta()
          .then(function(meta) {
            var services = (meta && meta.services) || [];
            if (!services.length) {
              throw new Error('В профиле нет услуг — добавьте услугу в профиле.');
            }
            if (meta.require_service_choice) {
              row.hidden = false;
              if (!sel.options.length) {
                var ph = document.createElement('option');
                ph.value = '';
                ph.textContent = '— Выберите услугу —';
                sel.appendChild(ph);
                services.forEach(function(s) {
                  var opt = document.createElement('option');
                  opt.value = String(s.id);
                  opt.textContent = s.name || ('Услуга #' + s.id);
                  sel.appendChild(opt);
                });
              }
              var sid = parseInt(sel.value, 10);
              if (!sid) {
                setStateMessage('Выберите услугу и нажмите кнопку ещё раз.', 'hint');
                return null;
              }
              return fetchGenericWelcomeLink(sid);
            }
            return fetchGenericWelcomeLink(services[0].id);
          })
          .then(function(o) {
            if (!o) return;
            var link = o.welcome_link;
            if (link) {
              setStateMessage('');
              urlEl.textContent = link;
              block.style.display = 'block';
            } else {
              setStateMessage('Пригласительная ссылка недоступна. Откройте из бота тренера.', 'error');
            }
          })
          .catch(function(err) {
            setStateMessage(err.message || 'Ошибка загрузки ссылки.', 'error');
          })
          .finally(function() {
            btn.disabled = false;
          });
      };
      document.getElementById('btnCopyInviteLink').onclick = function() {
        var link = document.getElementById('inviteLinkUrl').textContent;
        if (!link) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(link).then(function() {
            postClientInviteLinkFirstCopyRecorded();
            alert('Ссылка скопирована');
          }).catch(function() { alert(link); });
        } else { alert(link); }
      };

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

      initReturnContextFromQuery();
      initListFocusFromQuery();
      syncTrainerClientsHeaderBack();
      if (initData && window.TrainerMiniAppGate) {
        window.TrainerMiniAppGate.fetchAccess(initData)
          .then(function (a) {
            if (a && !window.TrainerMiniAppGate.isActive(a)) {
              window.TrainerMiniAppGate.showBlockingOverlay(a);
              return;
            }
            loadClients();
          })
          .catch(function () {
            loadClients();
          });
      } else {
        loadClients();
      }
    })();
