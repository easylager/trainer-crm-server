    (function() {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        tg.expand();
        // Reply-keyboard Web App: initData may appear after first tick; call ready() again once it does (see callReadyWhenInitDataReady).
        try { tg.ready(); } catch (e) {}
      }
      if (typeof window.__applyScheduleEditorTheme === 'function') window.__applyScheduleEditorTheme();
      if (tg && typeof tg.onEvent === 'function') {
        try { tg.onEvent('themeChanged', window.__applyScheduleEditorTheme); } catch (e) { /* older clients */ }
      }

      const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

      const BD_ICONS = {
        service: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><path d="M3.27 6.96L12 12.01l8.73-5.05"/></svg>',
        session: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>',
        comment: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>',
        send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>',
        check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
        xCircle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        cancelOutline: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>',
        userPlus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>',
        linkOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M10 13a5 5 0 0 1 7.54.54 3 3 0 0 0 1.3 1.38"/><path d="M14 11a5 5 0 0 1 4.95 5.47"/><path d="M16 16a5 5 0 0 1-4.95 5"/><path d="M2 2l20 20"/><path d="M7.7 7.7A4 4 0 0 0 6 11c0 1.22.52 2.33 1.36 3.11"/><path d="M8.6 8.6A4 4 0 0 1 12 8a4 4 0 0 1 3.17 6.27"/></svg>',
        alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
      };

      function bookingInitials(displayName) {
        var s = (displayName || '').trim();
        if (!s) return '?';
        var parts = s.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        if (parts[0].length >= 2) return parts[0].slice(0, 2).toUpperCase();
        return parts[0][0].toUpperCase();
      }
      const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
      const MONTHS_GENITIVE = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

      /** Belarus E.164; aligned with `src.shared.profile_phone` and trainer-profile.html */
      var PHONE_MAX_LEN = 32;
      var PHONE_BY_RE = /^\+375\d{9}$/;
      var PHONE_BY_ERR = 'Укажите корректный номер телефона.';
      function normalizePhoneClient(s) {
        var raw = String(s || '').trim();
        if (!raw) return '';
        var d = raw.replace(/\D/g, '');
        if (!d) return raw.slice(0, PHONE_MAX_LEN);
        if (d.length === 12 && d.indexOf('375') === 0) return '+' + d;
        if (d.length === 11 && d.indexOf('80') === 0) return '+375' + d.slice(2);
        if (d.length === 9) return '+375' + d;
        return raw.replace(/\s+/g, '').replace(/-/g, '').replace(/\(/g, '').replace(/\)/g, '').replace(/\./g, '').slice(0, PHONE_MAX_LEN);
      }
      function validatePhoneMessage(normalized) {
        var t = normalized;
        if (!t) return 'Укажите номер телефона.';
        if (t.length > PHONE_MAX_LEN) return 'Телефон: не длиннее 32 символов.';
        if (!PHONE_BY_RE.test(t)) return PHONE_BY_ERR;
        return null;
      }

      function apiUrl(path) { return '/api/webapp' + path; }
      function headers() {
        const h = { 'Content-Type': 'application/json' };
        if (tg && tg.initData) h['X-Telegram-Init-Data'] = tg.initData;
        return h;
      }

      /** Always append init_data to URL when present: edge/CDN often strips custom headers on fetch. */
      function apiUrlWithQuery(path) {
        var url = apiUrl(path);
        if (tg && tg.initData) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(tg.initData);
        return url;
      }

      /** Some clients (reply keyboard → Web App) fill initData late; notify Telegram again when it appears. */
      var _readyAfterInitDone = false;
      function callReadyWhenInitDataReady() {
        if (!tg || !tg.initData || _readyAfterInitDone) return;
        _readyAfterInitDone = true;
        try { tg.ready(); } catch (e) {}
      }

      function _detailMessageFromBody(j, fallback) {
        var msg = fallback || 'Ошибка запроса';
        if (!j) return msg;
        if (typeof j.detail === 'string') return j.detail;
        if (Array.isArray(j.detail)) {
          var parts = j.detail.map(function(x) { return (x && x.msg) ? String(x.msg) : ''; }).filter(Boolean);
          if (parts.length) return parts.join('; ');
        }
        return msg;
      }

      function getJsonTrainer(path) {
        return fetch(apiUrlWithQuery(path), { headers: headers() }).then(function(r) {
          return r.json().catch(function() { return {}; }).then(function(j) {
            if (r.ok) return j;
            throw new Error(_detailMessageFromBody(j, r.statusText || 'Ошибка загрузки'));
          });
        });
      }

      function postJsonTrainer(path, body) {
        return fetch(apiUrlWithQuery(path), {
          method: 'POST',
          headers: headers(),
          body: body ? JSON.stringify(body) : undefined,
        }).then(function(r) {
          return r.json().catch(function() { return {}; }).then(function(j) {
            if (r.ok) return j;
            throw new Error(_detailMessageFromBody(j, r.statusText || 'Ошибка'));
          });
        });
      }

      function formatBookingDate(slotDate) {
        if (!slotDate) return '—';
        var s = String(slotDate);
        var parts = s.split('-');
        if (parts.length >= 3) return parts[2] + '.' + parts[1] + '.' + parts[0];
        return s;
      }

      /** Network / 5xx / parse failure: short copy + retry (tunnel drops show as fetch errors). */
      function renderCalendarLoadFailure() {
        var el = document.getElementById('calendarContent');
        if (!el) return;
        el.innerHTML =
          '<div class="schedule-reload-panel">' +
          '<p class="schedule-reload-panel__msg">Не удалось загрузить расписание. Проверьте соединение и попробуйте снова.</p>' +
          '<button type="button" class="btn-secondary schedule-reload-panel__btn" id="btnScheduleCalendarReload">Обновить</button>' +
          '</div>';
        var btn = document.getElementById('btnScheduleCalendarReload');
        if (btn) {
          btn.onclick = function() {
            loadSlots();
          };
        }
      }

      function renderTemplateLoadFailure() {
        var el = document.getElementById('templateList');
        if (!el) return;
        el.innerHTML =
          '<div class="schedule-reload-panel">' +
          '<p class="schedule-reload-panel__msg">Не удалось загрузить шаблон недели. Проверьте соединение и попробуйте снова.</p>' +
          '<button type="button" class="btn-secondary schedule-reload-panel__btn" id="btnScheduleTemplatesReload">Обновить</button>' +
          '</div>';
        var btn = document.getElementById('btnScheduleTemplatesReload');
        if (btn) {
          btn.onclick = function() {
            loadTemplates();
          };
        }
      }

      /** Skeleton HTML for calendar column — mirrors day-block + slot-row density. */
      function buildCalendarSkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        function slotRow() {
          return (
            '<div class="ma-cal-skel-slot" aria-hidden="true">' +
              '<div class="ma-cal-skel-slot-left">' +
                '<div class="ma-schedule-skel-line--time ' + sk + '"></div>' +
                '<div class="ma-schedule-skel-line--sub ' + sk + '" style="margin-top:8px;width:78%"></div>' +
              '</div>' +
              '<div class="ma-cal-skel-pill ' + sk + '"></div>' +
            '</div>'
          );
        }
        function dayBlock() {
          return (
            '<div class="day-block ma-cal-skel-day">' +
              '<div class="day-title"><span class="ma-schedule-skel-day-title ' + sk + '"></span></div>' +
              slotRow() + slotRow() + slotRow() +
            '</div>'
          );
        }
        return (
          '<div class="ma-schedule-skel" role="status" aria-busy="true" aria-label="Загрузка расписания">' +
            dayBlock() + dayBlock() +
          '</div>'
        );
      }

      function buildTemplateListSkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        var rows = '';
        for (var d = 0; d < 7; d++) {
          rows +=
            '<div class="template-day-card template-skel-card" aria-hidden="true">' +
            '<span class="day-name">' +
            DAYS[d] +
            '</span>' +
            '<span class="day-slots empty"><span class="template-skel-text ' +
            sk +
            '"></span></span>' +
            '<span class="arrow" style="visibility:hidden">→</span></div>';
        }
        return '<div role="status" aria-busy="true" aria-label="Загрузка шаблона">' + rows + '</div>';
      }

      function buildBookingDetailSkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        return (
          '<div class="bd-skel-booking" role="status" aria-busy="true" aria-label="Загрузка записи">' +
            '<div class="bd-skel-hero-placeholder ' +
            sk +
            '"></div>' +
            '<div class="bd-skel-client-row">' +
            '<div class="bd-skel-av ' +
            sk +
            '"></div>' +
            '<div class="bd-skel-client-lines">' +
            '<div class="bd-skel-line bd-skel-line--name ' +
            sk +
            '"></div>' +
            '<div class="bd-skel-line bd-skel-line--tel ' +
            sk +
            '"></div>' +
            '</div>' +
            '</div>' +
            '<div class="bd-skel-section-label ' +
            sk +
            '"></div>' +
            '<div class="bd-skel-rows">' +
            '<div class="bd-skel-row-pad">' +
            '<div class="bd-skel-row-line bd-skel-row-line--w1 ' +
            sk +
            '"></div>' +
            '<div class="bd-skel-row-line bd-skel-row-line--w2 ' +
            sk +
            '"></div>' +
            '</div>' +
            '<div class="bd-skel-row-pad">' +
            '<div class="bd-skel-row-line ' +
            sk +
            '" style="width:52%;height:14px;border-radius:7px;"></div>' +
            '</div>' +
            '</div>' +
            '</div>'
        );
      }

      function buildBookClientListSkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        var rows = '';
        for (var i = 0; i < 5; i++) {
          rows +=
            '<div class="book-client-skel-row" aria-hidden="true">' +
            '<div class="book-client-skel-line ' +
            sk +
            '"></div>' +
            '<div class="book-client-skel-line book-client-skel-line--sm ' +
            sk +
            '"></div>' +
            '</div>';
        }
        return (
          '<div class="book-client-skel" role="status" aria-busy="true" aria-label="Загрузка клиентов">' + rows + '</div>'
        );
      }

      function buildModalProblemBodySkeletonHtml() {
        var sk = 'ma-skel-shimmer';
        return (
          '<div class="modal-problem-skel" role="status" aria-busy="true">' +
            '<div class="modal-problem-skel-line ' +
            sk +
            '" style="width:92%;height:18px;border-radius:9px;"></div>' +
            '<div class="modal-problem-skel-line ' +
            sk +
            '" style="width:76%;"></div>' +
            '<div class="modal-problem-skel-line ' +
            sk +
            '" style="width:58%;"></div>' +
          '</div>'
        );
      }

      function showBookingStack(view) {
        var main = document.getElementById('screenMain');
        var det = document.getElementById('screenBookingDetail');
        var dec = document.getElementById('screenBookingDecline');
        if (main) main.classList.toggle('active', view === 'main');
        if (det) det.classList.toggle('active', view === 'detail');
        if (dec) dec.classList.toggle('active', view === 'decline');
        updateTelegramBack();
      }

      function updateTelegramBack() {
        var btn = document.getElementById('btnBack');
        if (!btn) return;
        var booking = document.getElementById('screenBookingDetail') && document.getElementById('screenBookingDetail').classList.contains('active');
        var decline = document.getElementById('screenBookingDecline') && document.getElementById('screenBookingDecline').classList.contains('active');
        var edit = document.getElementById('screenEdit').style.display === 'block';
        var dayPick = document.getElementById('screenDayPick').style.display === 'block';
        var mQuick = document.getElementById('modalQuickBookDatetime') && document.getElementById('modalQuickBookDatetime').style.display === 'flex';
        var mQuickSvc = document.getElementById('modalQuickBookService') && document.getElementById('modalQuickBookService').style.display === 'flex';
        var mBook = document.getElementById('modalBookClient').style.display === 'flex';
        var mGroup = document.getElementById('modalGroupSlot') && document.getElementById('modalGroupSlot').style.display === 'flex';
        var mBookConf = document.getElementById('modalBookConfirm').style.display === 'flex';
        var mCancelB = document.getElementById('modalBookingCancel').style.display === 'flex';
        var mClientProb = document.getElementById('modalClientProblem') && document.getElementById('modalClientProblem').style.display === 'flex';
        var mTpl = document.getElementById('modalConfirm').style.display === 'flex';
        var mIntent = document.getElementById('modalSlotIntent') && document.getElementById('modalSlotIntent').style.display === 'flex';
        btn.hidden = !(booking || decline || edit || dayPick || mQuick || mQuickSvc || mBook || mGroup || mBookConf || mCancelB || mClientProb || mTpl || mIntent);
      }

      function refreshCalendarChrome() {
        if (!state.weekStart) state.weekStart = getMonday(new Date());
        const start = state.weekStart;
        document.getElementById('weekLabel').textContent = formatWeekLabel(start);
      }

      function flushPendingGroupHubModal() {
        if (state.pendingOpenGroupSlotId) {
          var gid = state.pendingOpenGroupSlotId;
          state.pendingOpenGroupSlotId = null;
          setTimeout(function() { openGroupSlotModal(gid); }, 0);
        }
      }

      function syncAfterBookingPop() {
        showBookingStack('main');
        window.scrollTo(0, 0);
        if (state.pendingReloadAfterPop) {
          state.pendingReloadAfterPop = false;
          loadSlots();
          return;
        }
        if (state.scheduleDataLoaded && state.tab === 'calendar') {
          refreshCalendarChrome();
          renderCalendar();
          flushPendingGroupHubModal();
          return;
        }
        loadSlots();
      }

      function navigateToTrainerHomeSafe() {
        if (typeof window.navigateTrainerHome === 'function') {
          window.navigateTrainerHome();
          return;
        }
        var pth = window.location.pathname || '';
        var base = pth.replace(/[^/]+$/, '') || '/webapp/';
        var u = base + 'trainer-home';
        if (tg && tg.initData) u += (u.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(tg.initData);
        window.location.href = u;
      }

      function navigateToTrainerHomeWithReopenGroup(slotId) {
        var sid = parseInt(String(slotId), 10);
        if (isNaN(sid) || sid <= 0) {
          navigateToTrainerHomeSafe();
          return;
        }
        if (typeof window.navigateTrainerHome === 'function') {
          window.navigateTrainerHome({ reopenGroupSlot: sid });
          return;
        }
        var pth = window.location.pathname || '';
        var base = pth.replace(/[^/]+$/, '') || '/webapp/';
        var u = base + 'trainer-home?reopen_group_slot=' + encodeURIComponent(String(sid));
        if (tg && tg.initData) u += '&init_data=' + encodeURIComponent(tg.initData);
        window.location.href = u;
      }

      function goBackFromBookingDetail() {
        if (state.bookingDetailReturn === 'hub_group') {
          var hsid = state.hubGroupSlotReturnId;
          state.bookingDetailReturn = null;
          state.hubGroupSlotReturnId = null;
          if (hsid != null && !isNaN(parseInt(String(hsid), 10))) {
            navigateToTrainerHomeWithReopenGroup(hsid);
          } else {
            navigateToTrainerHomeSafe();
          }
          return;
        }
        if (state.bookingDetailReturn === 'hub') {
          state.bookingDetailReturn = null;
          navigateToTrainerHomeSafe();
          return;
        }
        if (state.bookingDetailReturn === 'group' && state.groupHubSlotId != null) {
          state.pendingOpenGroupSlotId = state.groupHubSlotId;
          state.bookingDetailReturn = null;
          state.groupHubSlotId = null;
          if (history.state && history.state.ui === 'sched-detail') {
            history.back();
            return;
          }
          syncAfterBookingPop();
          return;
        }
        if (history.state && history.state.ui === 'sched-detail') {
          history.back();
        } else {
          syncAfterBookingPop();
        }
      }

      /** After confirm/decline/cancel: same return target as «Назад» (hub vs schedule). */
      function leaveDetailAfterMutation() {
        if (state.bookingDetailReturn === 'hub_group') {
          var hgid = state.hubGroupSlotReturnId;
          state.bookingDetailReturn = null;
          state.hubGroupSlotReturnId = null;
          state.pendingReloadAfterPop = false;
          if (hgid != null && !isNaN(parseInt(String(hgid), 10))) {
            navigateToTrainerHomeWithReopenGroup(hgid);
          } else {
            navigateToTrainerHomeSafe();
          }
          return;
        }
        if (state.bookingDetailReturn === 'hub') {
          state.bookingDetailReturn = null;
          state.pendingReloadAfterPop = false;
          navigateToTrainerHomeSafe();
          return;
        }
        if (state.bookingDetailReturn === 'group' && state.groupHubSlotId != null) {
          var sid = state.groupHubSlotId;
          state.bookingDetailReturn = null;
          state.groupHubSlotId = null;
          state.pendingOpenGroupSlotId = sid;
          if (history.state && history.state.ui === 'sched-detail') {
            state.pendingReloadAfterPop = true;
            history.back();
            return;
          }
          showBookingStack('main');
          loadSlots();
          return;
        }
        if (history.state && history.state.ui === 'sched-detail') {
          state.pendingReloadAfterPop = true;
          history.back();
        } else {
          showBookingStack('main');
          loadSlots();
        }
      }

      function handleTelegramBackUnified() {
        var mgr = document.getElementById('modalGroupSlot');
        if (mgr && mgr.style.display === 'flex') {
          mgr.style.display = 'none';
          updateTelegramBack();
          return;
        }
        var msi = document.getElementById('modalSlotIntent');
        if (msi && msi.style.display === 'flex') {
          msi.style.display = 'none';
          msi.setAttribute('aria-hidden', 'true');
          state.pendingIntentFlow = null;
          state.pendingTemplateDay = null;
          var ind = document.getElementById('btnSlotIntentIndividual');
          var grp = document.getElementById('btnSlotIntentGroup');
          if (ind) ind.classList.remove('is-suggested');
          if (grp) grp.classList.remove('is-suggested');
          updateTelegramBack();
          return;
        }
        var mbc = document.getElementById('modalBookingCancel');
        if (mbc && mbc.style.display === 'flex') {
          mbc.style.display = 'none';
          updateTelegramBack();
          return;
        }
        var mcp = document.getElementById('modalClientProblem');
        if (mcp && mcp.style.display === 'flex') {
          closeClientProblemModal();
          return;
        }
        var mc = document.getElementById('modalConfirm');
        if (mc && mc.style.display === 'flex') {
          mc.style.display = 'none';
          updateTelegramBack();
          return;
        }
        var mbf = document.getElementById('modalBookConfirm');
        if (mbf && mbf.style.display === 'flex') {
          mbf.style.display = 'none';
          state.pendingBookClientId = null;
          state.pendingBookClientName = null;
          if (state.quickBookProfileAwaitingConfirm) {
            state.quickBookProfileAwaitingConfirm = false;
            setQuickBookProfileServiceLoading(false);
            var ms = document.getElementById('modalQuickBookService');
            if (ms) {
              ms.style.display = 'flex';
              ms.setAttribute('aria-hidden', 'false');
            }
          }
          updateTelegramBack();
          return;
        }
        var mqs = document.getElementById('modalQuickBookService');
        if (mqs && mqs.style.display === 'flex') {
          setQuickBookProfileServiceLoading(false);
          setQuickBookDatetimeLoading(false);
          mqs.style.display = 'none';
          mqs.setAttribute('aria-hidden', 'true');
          state.quickBookProfileServiceStep = false;
          var mqBack = document.getElementById('modalQuickBookDatetime');
          if (mqBack) {
            mqBack.style.display = 'flex';
            mqBack.setAttribute('aria-hidden', 'false');
          }
          updateTelegramBack();
          return;
        }
        var mq = document.getElementById('modalQuickBookDatetime');
        if (mq && mq.style.display === 'flex') {
          setQuickBookDatetimeLoading(false);
          mq.style.display = 'none';
          mq.setAttribute('aria-hidden', 'true');
          state.pendingBookFlowFromHub = false;
          state.quickBookLockedClientId = null;
          state.quickBookProfileServiceStep = false;
          updateTelegramBack();
          return;
        }
        var mb = document.getElementById('modalBookClient');
        if (mb && mb.style.display === 'flex') {
          mb.style.display = 'none';
          clearBookSlotModalState();
          state.bookModalStep = 'choice';
          updateTelegramBack();
          return;
        }
        if (document.getElementById('screenBookingDecline').classList.contains('active')) {
          showBookingStack('detail');
          return;
        }
        if (document.getElementById('screenBookingDetail').classList.contains('active')) {
          goBackFromBookingDetail();
          return;
        }
        if (document.getElementById('screenDayPick').style.display === 'block') {
          document.getElementById('screenDayPick').style.display = 'none';
          showMain();
          return;
        }
        if (document.getElementById('screenEdit').style.display === 'block') {
          showMain();
        }
      }

      window.addEventListener('popstate', function() {
        var mbc = document.getElementById('modalBookingCancel');
        if (mbc && mbc.style.display === 'flex') mbc.style.display = 'none';
        var mcp = document.getElementById('modalClientProblem');
        if (mcp && mcp.style.display === 'flex') {
          mcp.style.display = 'none';
          mcp.setAttribute('aria-hidden', 'true');
          _clientProblemSubmitting = false;
          _clientProblemWizard = {
            bookingId: null,
            step: 'pick',
            options: null,
            selected: null,
            passCertDeduct: null,
            isPassCertFlow: false,
            skipPassCertPick: false,
            client_action: null,
          };
        }
        if (document.getElementById('screenBookingDecline').classList.contains('active')) {
          showBookingStack('detail');
          return;
        }
        syncAfterBookingPop();
      });

      function prefetchSlotsInBackground() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        if (tg && !tg.initData) return;
        if (!state.weekStart) state.weekStart = getMonday(new Date());
        var end = new Date(state.weekStart);
        end.setDate(end.getDate() + 6);
        fetch(apiUrlWithQuery('/schedule?from_date=' + encodeURIComponent(dateToStr(state.weekStart)) + '&to_date=' + encodeURIComponent(dateToStr(end))), { headers: headers() })
          .then(function(r) { return r.ok ? r.json() : Promise.resolve(null); })
          .then(function(data) {
            if (!data) return;
            state.slots = data.slots || [];
            state.groupClassesEnabled = !!data.group_classes_enabled;
            state.scheduleDataLoaded = true;
          })
          .catch(function() {});
      }

      var _clientProblemWizard = {
        bookingId: null,
        step: 'pick',
        options: null,
        selected: null,
        passCertDeduct: null,
        isPassCertFlow: false,
        skipPassCertPick: false,
        client_action: null,
      };
      var _clientProblemSubmitting = false;

      function _clientProblemModalCardEl() {
        return document.querySelector('#modalClientProblem .modal.modal-client-problem');
      }
      function _setClientProblemConfirmModal(on) {
        var card = _clientProblemModalCardEl();
        if (!card) return;
        card.classList.toggle('client-problem-modal--confirm', !!on);
      }
      function _detachClientProblemViewportScroll() {}
      function _hideClientProblemCommentWrap() {
        var cw = document.getElementById('modalClientProblemCommentWrap');
        if (cw) {
          cw.innerHTML = '';
          cw.setAttribute('hidden', '');
        }
      }

      function setClientProblemModalTitle(text) {
        var h = document.getElementById('modalClientProblemTitle');
        if (h) h.textContent = text || 'Проблема с клиентом';
      }

      function closeClientProblemModal() {
        _detachClientProblemViewportScroll();
        _hideClientProblemCommentWrap();
        _setClientProblemConfirmModal(false);
        setClientProblemModalTitle('Проблема с клиентом');
        var m = document.getElementById('modalClientProblem');
        if (m) {
          m.style.display = 'none';
          m.setAttribute('aria-hidden', 'true');
        }
        _clientProblemSubmitting = false;
        _clientProblemWizard = {
          bookingId: null,
          step: 'pick',
          options: null,
          selected: null,
          passCertDeduct: null,
          isPassCertFlow: false,
          skipPassCertPick: false,
          client_action: null,
        };
        updateTelegramBack();
      }

      function submitClientNoShow(bookingId, choice, btns) {
        if (_clientProblemSubmitting) return;
        _clientProblemSubmitting = true;
        var p = btns && btns.primary;
        var s = btns && btns.secondary;
        if (p) p.disabled = true;
        if (s) s.disabled = true;
        postJsonTrainer('/trainer/bookings/' + bookingId + '/client-no-show', {
          choice: choice,
          source: 'schedule_editor',
        }).then(function() {
          showToast('Сохранено');
          closeClientProblemModal();
          if (state.selectedBooking && state.selectedBooking.id === bookingId) {
            openBookingDetail(bookingId);
          }
        }).catch(function(e) {
          showToast((e && e.message) ? e.message : 'Не удалось сохранить');
          _clientProblemSubmitting = false;
          if (p) p.disabled = false;
          if (s) s.disabled = false;
        });
      }

      function _htmlClientNoShowOptionsBody(o) {
        var lead = o.lead || '';
        var parts = lead.split(/\n\s*\n/).map(function(s) { return String(s || '').trim(); }).filter(Boolean);
        var leadHtml = parts.length
          ? parts.map(function(p) {
              return '<p class="client-problem-lead">' + escapeHtml(p) + '</p>';
            }).join('')
          : '<p class="client-problem-lead">' + escapeHtml(lead) + '</p>';
        var note = (o.reporting_note && String(o.reporting_note).trim()) ? String(o.reporting_note).trim() : '';
        var noteHtml = note
          ? '<div class="bd-section-label client-problem-reporting-kicker">Для себя</div>' +
            '<p class="client-problem-reporting-note">' + escapeHtml(note) + '</p>'
          : '';
        return '<div class="client-problem-body-inner">' + leadHtml + noteHtml + '</div>';
      }

      function openClientNoShowModal(bookingId) {
        _detachClientProblemViewportScroll();
        _hideClientProblemCommentWrap();
        _setClientProblemConfirmModal(false);
        _clientProblemSubmitting = false;
        var m = document.getElementById('modalClientProblem');
        var body = document.getElementById('modalClientProblemBody');
        var foot = document.getElementById('modalClientProblemFooter');
        if (!m || !body || !foot) return;
        m.style.display = 'flex';
        m.setAttribute('aria-hidden', 'false');
        updateTelegramBack();
        body.innerHTML = buildModalProblemBodySkeletonHtml();
        foot.innerHTML = '';
        getJsonTrainer('/trainer/bookings/' + bookingId + '/client-no-show-options').then(function(o) {
          if (!o) return;
          setClientProblemModalTitle(o.title || 'Клиент не пришёл');
          if (o.already_recorded) {
            body.innerHTML = '<div class="client-problem-body-inner"><p class="client-problem-lead">' + escapeHtml(o.lead || '') + '</p></div>';
            foot.innerHTML = '<button type="button" class="btn-primary" id="btnNoShowClose">Закрыть</button>';
            var cl = document.getElementById('btnNoShowClose');
            if (cl) cl.onclick = closeClientProblemModal;
            return;
          }
          body.innerHTML = _htmlClientNoShowOptionsBody(o);
          var pl = o.primary_label || 'Оставить списание';
          var sl = o.secondary_label || 'Не списывать';
          foot.innerHTML =
            '<button type="button" class="btn-secondary" id="btnNoShowSecondary">' + escapeHtml(sl) + '</button>' +
            '<button type="button" class="btn-primary" id="btnNoShowPrimary">' + escapeHtml(pl) + '</button>';
          var bp = document.getElementById('btnNoShowPrimary');
          var bs = document.getElementById('btnNoShowSecondary');
          var pk = o.primary_choice || 'keep_redeem';
          var sk = o.secondary_choice || 'skip_redeem';
          if (bp) {
            bp.onclick = function() {
              submitClientNoShow(bookingId, pk, { primary: bp, secondary: bs });
            };
          }
          if (bs) {
            bs.onclick = function() {
              submitClientNoShow(bookingId, sk, { primary: bp, secondary: bs });
            };
          }
        }).catch(function(err) {
          body.innerHTML = '<p class="screen-hint">' + escapeHtml((err && err.message) ? String(err.message) : 'Не удалось загрузить.') + '</p>';
          foot.innerHTML = '<button type="button" class="btn-primary" id="btnNoShowErr">Закрыть</button>';
          var eb = document.getElementById('btnNoShowErr');
          if (eb) eb.onclick = closeClientProblemModal;
        });
      }

      function renderClientProblemPick() {
        _detachClientProblemViewportScroll();
        _hideClientProblemCommentWrap();
        _setClientProblemConfirmModal(false);
        setClientProblemModalTitle('Проблема с клиентом');
        var o = _clientProblemWizard.options;
        _clientProblemWizard.isPassCertFlow = false;
        var presets = (o && o.presets) || [];
        var body = document.getElementById('modalClientProblemBody');
        var foot = document.getElementById('modalClientProblemFooter');
        var html = '<p class="client-problem-lead">Что случилось?</p>';
        html += '<div class="client-problem-preset-list">';
        presets.forEach(function(p) {
          html += '<button type="button" class="btn-block btn-outline client-problem-preset" data-preset-id="' + escapeHtml(p.id) + '">' + escapeHtml(p.label) + '</button>';
        });
        html += '</div>';
        body.innerHTML = html;
        foot.innerHTML = '<button type="button" class="btn-secondary" id="btnClientProblemCancelPick">Отмена</button>';
        var cancelBtn = document.getElementById('btnClientProblemCancelPick');
        if (cancelBtn) cancelBtn.onclick = closeClientProblemModal;
        body.querySelectorAll('.client-problem-preset').forEach(function(btn) {
          btn.onclick = function() {
            var pid = btn.getAttribute('data-preset-id');
            var preset = presets.find(function(x) { return String(x.id) === String(pid); });
            if (!preset) return;
            _clientProblemWizard.selected = preset;
            _clientProblemWizard.step = 'warn';
            renderClientProblemShortWarn();
          };
        });
      }

      /** A1: choose mark / blacklist / absence only. A2: explicit blacklist consent. */
      function renderClientProblemShortWarn() {
        var p = _clientProblemWizard.selected;
        var body = document.getElementById('modalClientProblemBody');
        var foot = document.getElementById('modalClientProblemFooter');
        if (!p || !body || !foot) return;
        _detachClientProblemViewportScroll();
        _hideClientProblemCommentWrap();
        _setClientProblemConfirmModal(false);
        _clientProblemWizard.step = 'warn';
        setClientProblemModalTitle(p.label || 'Проблема с клиентом');
        var pid = String(p.id || '');
        var inner;
        if (pid === 'A1') {
          _clientProblemWizard.client_action = 'absence_only';
          inner = '<div class="client-problem-outcome-list" id="clientProblemOutcomeList" role="listbox" aria-label="Как отметить отсутствие клиента">';
          inner += '<button type="button" class="client-problem-outcome client-problem-outcome--hero is-selected" data-action="absence_only" role="option" aria-selected="true">';
          inner += '<span>Просто отсутствие</span>';
          inner += '<span class="client-problem-outcome-sub">В записи будет видно, что клиента не было.</span>';
          inner += '</button>';
          inner += '<div class="client-problem-outcome-secondary-block">';
          inner += '<div class="client-problem-outcome-secondary-row">';
          inner += '<button type="button" class="client-problem-outcome client-problem-outcome--muted" data-action="attention" role="option" aria-selected="false"><span class="client-problem-outcome-muted-title">Пометка «требует внимания»</span></button>';
          inner += '<button type="button" class="client-problem-outcome client-problem-outcome--muted" data-action="blacklist" role="option" aria-selected="false"><span class="client-problem-outcome-muted-title">Чёрный список</span></button>';
          inner += '</div></div></div>';
        } else if (pid === 'A2') {
          inner = '<p class="client-problem-warn-lead">Клиента <b>занесём в чёрный список</b>. Отменить одной кнопкой нельзя.</p>';
        } else {
          inner = '<p class="client-problem-warn-lead">Подтвердить действие?</p>';
        }
        body.innerHTML = '<div class="client-problem-body-inner client-problem-warn">' + inner + '</div>';
        var confirmLabel = pid === 'A2' ? 'Занести в чёрный список' : 'Подтвердить';
        foot.innerHTML =
          '<button type="button" class="btn-secondary" id="btnClientProblemBackWarn">Назад</button>' +
          '<button type="button" class="btn-primary" id="btnClientProblemConfirm">' + escapeHtml(confirmLabel) + '</button>';
        var backBtn = document.getElementById('btnClientProblemBackWarn');
        var okBtn = document.getElementById('btnClientProblemConfirm');
        if (backBtn) {
          backBtn.onclick = function() {
            _clientProblemWizard.step = 'pick';
            _clientProblemWizard.selected = null;
            _clientProblemWizard.client_action = null;
            renderClientProblemPick();
          };
        }
        if (okBtn) okBtn.onclick = submitClientProblemReport;
        if (pid === 'A1') {
          var list = document.getElementById('clientProblemOutcomeList');
          if (list) {
            list.querySelectorAll('.client-problem-outcome').forEach(function(ob) {
              ob.onclick = function() {
                list.querySelectorAll('.client-problem-outcome').forEach(function(x) {
                  x.classList.remove('is-selected');
                  x.setAttribute('aria-selected', 'false');
                });
                ob.classList.add('is-selected');
                ob.setAttribute('aria-selected', 'true');
                _clientProblemWizard.client_action = ob.getAttribute('data-action') || 'absence_only';
              };
            });
          }
        }
      }

      function submitClientProblemReport() {
        var bid = _clientProblemWizard.bookingId;
        var pr = _clientProblemWizard.selected;
        if (!bid || !pr || _clientProblemSubmitting) return;
        var btn = document.getElementById('btnClientProblemConfirm');
        var back = document.getElementById('btnClientProblemBackWarn');
        _clientProblemSubmitting = true;
        if (btn) btn.disabled = true;
        if (back) back.disabled = true;
        var payload = {
          preset_id: pr.id,
          note: null,
          source: 'schedule_editor',
        };
        if (String(pr.id) === 'A1') {
          payload.client_action = _clientProblemWizard.client_action || 'absence_only';
        }
        postJsonTrainer('/trainer/bookings/' + bid + '/problem', payload).then(function() {
          showToast('Готово');
          closeClientProblemModal();
          if (state.selectedBooking && state.selectedBooking.id === bid) {
            openBookingDetail(bid);
          }
        }).catch(function(e) {
          showToast((e && e.message) ? e.message : 'Не удалось отправить');
          _clientProblemSubmitting = false;
          if (btn) btn.disabled = false;
          if (back) back.disabled = false;
        });
      }

      function openClientProblemWizard(bookingId) {
        _detachClientProblemViewportScroll();
        _hideClientProblemCommentWrap();
        _setClientProblemConfirmModal(false);
        _clientProblemWizard = {
          bookingId: bookingId,
          step: 'pick',
          options: null,
          selected: null,
          passCertDeduct: null,
          isPassCertFlow: false,
          skipPassCertPick: false,
          client_action: null,
        };
        var m = document.getElementById('modalClientProblem');
        var body = document.getElementById('modalClientProblemBody');
        var foot = document.getElementById('modalClientProblemFooter');
        if (!m || !body || !foot) return;
        m.style.display = 'flex';
        m.setAttribute('aria-hidden', 'false');
        updateTelegramBack();
        body.innerHTML = buildModalProblemBodySkeletonHtml();
        foot.innerHTML = '';
        getJsonTrainer('/trainer/bookings/' + bookingId + '/problem-options').then(function(o) {
          _clientProblemWizard.options = o;
          if (o && o.already_reported) {
            _hideClientProblemCommentWrap();
            body.innerHTML = '<p class="screen-hint">По этой записи отчёт уже отправлен.</p>';
            foot.innerHTML = '<button type="button" class="btn-primary" id="btnClientProblemCloseDup">Закрыть</button>';
            var cb = document.getElementById('btnClientProblemCloseDup');
            if (cb) cb.onclick = closeClientProblemModal;
            return;
          }
          renderClientProblemPick();
        }).catch(function(err) {
          _hideClientProblemCommentWrap();
          var msg = (err && err.message) ? String(err.message) : 'Не удалось загрузить варианты.';
          body.innerHTML = '<p class="screen-hint">' + escapeHtml(msg) + '</p>';
          foot.innerHTML = '<button type="button" class="btn-primary" id="btnClientProblemCloseErr">Закрыть</button>';
          var ce = document.getElementById('btnClientProblemCloseErr');
          if (ce) ce.onclick = closeClientProblemModal;
        });
      }

      (function wireClientProblemModalBackdrop() {
        var el = document.getElementById('modalClientProblem');
        if (!el) return;
        el.addEventListener('click', function(ev) {
          if (ev.target === el && !_clientProblemSubmitting) closeClientProblemModal();
        });
      })();

      function openBookingDetail(bookingId) {
        if (state.bookingDetailReturn !== 'hub' && state.bookingDetailReturn !== 'group' && state.bookingDetailReturn !== 'hub_group') {
          state.bookingDetailReturn = 'schedule';
        }
        state.selectedBooking = null;
        var _openProblemAfter = !!state.openClientProblemAfterDetail;
        state.openClientProblemAfterDetail = false;
        document.getElementById('detailBookingContent').innerHTML = buildBookingDetailSkeletonHtml();
        document.getElementById('detailBookingActions').innerHTML = '';
        showBookingStack('detail');
        getJsonTrainer('/trainer/bookings/' + bookingId).then(function(b) {
          state.selectedBooking = b;
          var client = [b.client_first_name, b.client_last_name].filter(Boolean).join(' ') || b.client_phone || 'Клиент';
          var dateStr = formatBookingDate(b.slot_date);
          var initials = bookingInitials(client);
          var html = '';
          html += '<div class="booking-detail">';
          html += '<div class="bd-hero"><div class="bd-hero-inner">';
          html += '<div class="bd-hero-kicker">Дата и время</div>';
          html += '<div class="bd-hero-time">' + escapeHtml(b.start_time || '—') + ' – ' + escapeHtml(b.end_time || '—') + '</div>';
          html += '<div class="bd-hero-date">' + escapeHtml(dateStr) + ' · ' + escapeHtml(b.day_label || '') + '</div>';
          html += '</div></div>';
          if (b.client_id != null) {
            var pathBase = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
            var profileUrl = pathBase + 'trainer-clients?client_id=' + encodeURIComponent(String(b.client_id));
            profileUrl += '&return_booking=' + encodeURIComponent(String(b.id));
            var retFrom = (state.bookingDetailReturn === 'hub' || state.bookingDetailReturn === 'hub_group') ? 'hub' : 'schedule';
            profileUrl += '&return_from=' + encodeURIComponent(retFrom);
            if (tg && tg.initData) profileUrl += (profileUrl.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(tg.initData);
            html += '<div class="bd-client bd-client--profile">';
            html += '<a class="bd-client-profile-hit" href="' + escapeHtml(profileUrl) + '" aria-label="Профиль клиента: заметки и история">';
            html += '<div class="bd-avatar" aria-hidden="true">' + escapeHtml(initials) + '</div>';
            html += '<div class="bd-client-body">';
            html += '<div class="bd-client-name">' + escapeHtml(client) + (b.client_has_telegram === false ? ' <span class="no-bot">Без бота</span>' : '') + '</div>';
            html += '<span class="bd-client-profile-hint">Профиль и заметки</span>';
            html += '</div>';
            html += '<svg class="bd-client-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>';
            html += '</a>';
            if (b.client_phone) {
              var telRawP = String(b.client_phone).replace(/\s+/g, '');
              html += '<a class="bd-tel bd-tel--block" href="tel:' + escapeHtml(telRawP) + '">' + escapeHtml(b.client_phone) + '</a>';
            }
            html += '</div>';
          } else {
            html += '<div class="bd-client">';
            html += '<div class="bd-avatar" aria-hidden="true">' + escapeHtml(initials) + '</div>';
            html += '<div class="bd-client-body">';
            html += '<div class="bd-client-name">' + escapeHtml(client) + (b.client_has_telegram === false ? ' <span class="no-bot">Без бота</span>' : '') + '</div>';
            if (b.client_phone) {
              var telRaw = String(b.client_phone).replace(/\s+/g, '');
              html += '<a class="bd-tel" href="tel:' + escapeHtml(telRaw) + '">' + escapeHtml(b.client_phone) + '</a>';
            }
            html += '</div></div>';
          }
          html += '<div class="bd-section-label">Подробности</div>';
          html += '<div class="bd-rows">';
          html += '<div class="bd-row">' + BD_ICONS.service + '<div class="bd-row-text"><div class="bd-row-label">Услуга · арена</div><div class="bd-row-value">' + escapeHtml(b.services_str || '—') + ' · ' + escapeHtml(b.arenas_str || '—') + '</div></div></div>';
          html += '<div class="bd-row">' + BD_ICONS.session + '<div class="bd-row-text"><div class="bd-row-label">Занятие</div><div class="bd-row-value">' + (b.session_num || 1) + '-е занятие</div></div></div>';
          if (b.client_comment) {
            html += '<div class="bd-row bd-comment">' + BD_ICONS.comment + '<div class="bd-row-text"><div class="bd-row-label">Комментарий</div><div class="bd-row-value">' + escapeHtml(b.client_comment) + '</div></div></div>';
          }
          html += '</div></div>';
          document.getElementById('detailBookingContent').innerHTML = html;

          var actions = document.getElementById('detailBookingActions');
          actions.innerHTML = '';
          var pending = (b.status || '') === 'pending';
          var completed = (b.status || '') === 'completed';
          var stRaw = (b.status || '').toLowerCase();
          var bookingEnded = isSlotEndedInPast(b);
          var canCancelBooking = stRaw === 'confirmed' && !bookingEnded;
          var tid = b.client_telegram_id;

          var primaryActions = [];
          var extraActions = [];
          if (pending) {
            primaryActions.push({ cls: 'bd-btn--confirm', action: 'confirm', icon: BD_ICONS.check, label: 'Подтвердить' });
            primaryActions.push({ cls: 'bd-btn--decline', action: 'decline', icon: BD_ICONS.xCircle, label: 'Отклонить' });
          } else if (canCancelBooking) {
            primaryActions.push({ cls: 'bd-btn--secondary', action: 'reschedule', icon: BD_ICONS.session, label: 'Перенести запись' });
            primaryActions.push({ cls: 'bd-btn--outline-danger', action: 'cancel', icon: BD_ICONS.cancelOutline, label: 'Отменить запись' });
          }
          if (tid && b.client_has_telegram !== false) {
            extraActions.push({ cls: 'bd-btn--surface', action: 'write_client', icon: BD_ICONS.send, label: 'Написать клиенту' });
          }
          var canReportProblem = stRaw !== 'cancelled' && stRaw !== 'declined';
          // E7: false when rollout=off or pilot excludes this trainer (API sets problem_flow_enabled).
          var problemFlowOk = (b.problem_flow_enabled !== false);
          if (canReportProblem && problemFlowOk) {
            var ppc = b.problem_payment_class || '';
            var isPassCert = (ppc === 'PASS' || ppc === 'CERT');
            if (b.problem_reported) {
              actions.innerHTML += '<p class="bd-problem-sent-hint">Отчёт о проблеме с клиентом уже отправлен.</p>';
            } else if (b.client_no_show_recorded && isPassCert) {
              actions.innerHTML += '<p class="bd-problem-sent-hint">Отметка «Клиент не пришёл» сохранена.</p>';
            } else {
              var probBtnLabel = isPassCert ? 'Клиент не пришёл' : 'Проблема с клиентом';
              extraActions.push({ cls: 'bd-btn--surface', action: 'client_problem', icon: BD_ICONS.alert, label: probBtnLabel });
            }
          }
          if (!completed) {
            if (b.recurring_id) {
              extraActions.push({
                cls: 'bd-btn--soft',
                action: 'remove_recurring',
                icon: BD_ICONS.linkOff,
                label: 'Снять регулярность',
                recurringId: b.recurring_id,
              });
            } else {
              extraActions.push({ cls: 'bd-btn--soft', action: 'make_regular', icon: BD_ICONS.userPlus, label: 'Сделать постоянным клиентом' });
            }
          }

          function renderActionBtn(a) {
            var rid = a.recurringId ? ' data-recurring-id="' + String(a.recurringId) + '"' : '';
            return '<button type="button" class="bd-btn ' + a.cls + '" data-baction="' + a.action + '"' + rid + '>' + a.icon + ' ' + escapeHtml(a.label) + '</button>';
          }
          primaryActions.forEach(function(a) { actions.innerHTML += renderActionBtn(a); });
          if (extraActions.length) {
            actions.innerHTML += '<div class="bd-actions-separator" role="separator" aria-hidden="true"></div>';
            actions.innerHTML += '<div class="bd-actions-extra" id="detailBookingExtraActions"></div>';
            var extraWrap = document.getElementById('detailBookingExtraActions');
            if (extraWrap) extraWrap.innerHTML = extraActions.map(renderActionBtn).join('');
          }

          actions.querySelectorAll('button[data-baction]').forEach(function(btn) {
            btn.onclick = function() {
              var act = btn.getAttribute('data-baction');
              if (act === 'write_client') return;
              if (act === 'client_problem') {
                var ppc2 = b.problem_payment_class || '';
                if (ppc2 === 'PASS' || ppc2 === 'CERT') openClientNoShowModal(b.id);
                else openClientProblemWizard(b.id);
                return;
              }
              if (act === 'reschedule') {
                startRescheduleFromBooking(b);
                return;
              }
              if (act === 'confirm') confirmTrainerBooking(b.id);
              else if (act === 'decline') {
                showBookingStack('decline');
                document.getElementById('declineCommentBooking').value = '';
              } else if (act === 'cancel') {
                document.getElementById('modalBookingCancel').style.display = 'flex';
                updateTelegramBack();
              } else if (act === 'make_regular') makeRegularFromBooking(b.id);
              else if (act === 'remove_recurring') {
                var rid = parseInt(btn.getAttribute('data-recurring-id') || '0', 10);
                removeRecurringFromBooking(rid);
              }
            };
          });

          try {
            history.pushState({ ui: 'sched-detail' }, '', window.location.pathname);
          } catch (e) { /* ignore */ }
          if (_openProblemAfter) {
            setTimeout(function() {
              var sb = state.selectedBooking;
              var oppc = sb && sb.problem_payment_class;
              if (oppc === 'PASS' || oppc === 'CERT') openClientNoShowModal(bookingId);
              else openClientProblemWizard(bookingId);
            }, 0);
          }
        }).catch(function() {
          alert('Ошибка загрузки');
          showBookingStack('main');
          loadSlots();
        });
      }

      function confirmTrainerBooking(bookingId) {
        postJsonTrainer('/trainer/bookings/' + bookingId + '/confirm', null).then(function() {
          showToast('Запись подтверждена');
          leaveDetailAfterMutation();
        }).catch(function() { alert('Ошибка'); });
      }

      function makeRegularFromBooking(bookingId) {
        postJsonTrainer('/trainer/bookings/' + bookingId + '/make_regular', null).then(function(res) {
          openBookingDetail(bookingId);
        }).catch(function() { alert('Ошибка'); });
      }

      function removeRecurringFromBooking(recurringId) {
        if (!recurringId) return;
        postJsonTrainer('/trainer/recurring/' + recurringId + '/remove', null).then(function() {
          var id = state.selectedBooking && state.selectedBooking.id;
          if (id) openBookingDetail(id);
        }).catch(function() { alert('Ошибка'); });
      }

      document.getElementById('backFromDeclineBooking').onclick = function() { showBookingStack('detail'); };

      document.getElementById('btnDeclineSubmitBooking').onclick = function() {
        var comment = (document.getElementById('declineCommentBooking').value || '').trim();
        if (!comment) { alert('Напишите причину отклонения для клиента.'); return; }
        var id = state.selectedBooking && state.selectedBooking.id;
        if (!id) return;
        postJsonTrainer('/trainer/bookings/' + id + '/decline', { comment: comment }).then(function() {
          leaveDetailAfterMutation();
        }).catch(function() { alert('Ошибка'); });
      };

      document.getElementById('modalBookingCancelYes').onclick = function() {
        document.getElementById('modalBookingCancel').style.display = 'none';
        updateTelegramBack();
        var id = state.selectedBooking && state.selectedBooking.id;
        if (!id) return;
        postJsonTrainer('/trainer/bookings/' + id + '/cancel', null).then(function() {
          leaveDetailAfterMutation();
        }).catch(function() { alert('Ошибка'); });
      };

      document.getElementById('modalBookingCancelNo').onclick = function() {
        document.getElementById('modalBookingCancel').style.display = 'none';
        updateTelegramBack();
      };

      document.querySelectorAll('.filter-btn[data-slot-filter]').forEach(function(btn) {
        btn.onclick = function() {
          document.querySelectorAll('.filter-btn[data-slot-filter]').forEach(function(b) { b.classList.remove('active'); });
          btn.classList.add('active');
          state.slotFilter = btn.getAttribute('data-slot-filter') || 'all';
          renderCalendar();
        };
      });
      function showToast(message, durationMs) {
        var el = document.getElementById('toast');
        if (!el) return;
        el.textContent = message;
        el.classList.remove('toast-visible');
        void el.offsetHeight;
        el.classList.add('toast-visible');
        clearTimeout(el._toastTimer);
        var ms = durationMs != null && !isNaN(durationMs) ? Math.max(1200, durationMs) : 2800;
        el._toastTimer = setTimeout(function() {
          el.classList.remove('toast-visible');
        }, ms);
      }

      function scheduleFirstApplyWeekShareToastKey(trainerId) {
        if (trainerId == null || trainerId === '' || isNaN(Number(trainerId))) return null;
        return 'schedule_editor_first_apply_week_share_toast_v1_' + String(trainerId);
      }

      /** One-time nudge after first successful «apply template to week» (localStorage per trainer). */
      function showFirstApplyWeekShareToastIfNeeded(trainerIdFromApi) {
        var tidRaw = trainerIdFromApi != null ? trainerIdFromApi : state.trainerId;
        var tid = parseInt(String(tidRaw), 10);
        if (isNaN(tid) || tid < 1) return;
        if (state.trainerId == null) state.trainerId = tid;
        var key = scheduleFirstApplyWeekShareToastKey(tid);
        if (!key) return;
        var already = false;
        try {
          already = localStorage.getItem(key) === '1';
        } catch (e) {
          already = false;
        }
        if (already) return;
        try {
          localStorage.setItem(key, '1');
        } catch (e) {
          /* quota / private mode: toast still shown this once */
        }
        showToast(
          'Слоты на месте — можно поделиться ссылкой на запись: в боте тренера откройте «Пригласить клиента».',
          4500
        );
      }

      /** When opened in trainer-clients iframe (?embed=1), tell parent to close overlay and show UX there. */
      function notifyTrainerClientsEmbed(payload) {
        if (!state.scheduleEditorEmbed) return false;
        try {
          if (window.parent && window.parent !== window) {
            window.parent.postMessage(Object.assign({ __tcEmbed: true }, payload), window.location.origin);
            return true;
          }
        } catch (e) { /* cross-origin / older WebView */ }
        return false;
      }

      function applyTrainerBookingCreateSuccess(_apiData, toastMsg) {
        document.getElementById('modalBookClient').style.display = 'none';
        clearBookSlotModalState();
        var msg = toastMsg || 'Запись создана';
        var oldBookingIdToCancel = state.rescheduleSourceBookingId;
        state.rescheduleSourceBookingId = null;
        if (notifyTrainerClientsEmbed({ type: 'quickbook_success', message: msg })) {
          updateTelegramBack();
          return;
        }
        if (oldBookingIdToCancel) {
          postJsonTrainer('/trainer/bookings/' + oldBookingIdToCancel + '/cancel', null)
            .then(function() {
              loadSlots();
              showToast('Запись перенесена');
            })
            .catch(function() {
              loadSlots();
              showToast('Новая запись создана, но старую не удалось отменить. Проверьте запись вручную.');
            });
          updateTelegramBack();
          return;
        }
        loadSlots();
        showToast(msg);
        updateTelegramBack();
      }

      let state = {
        tab: 'calendar',
        /** From GET /schedule or POST /schedule/apply-week — for one-time toasts keyed in localStorage. */
        trainerId: null,
        /** Opened from hub hint `?tab=template` — applied on first schedule load after access. */
        pendingOpenTemplateTab: false,
        weekStart: null,
        slots: [],
        /** True after successful fetch (or prefetch) for current UI; avoids full refetch on back from booking detail. */
        scheduleDataLoaded: false,
        templates: [],
        slotFilter: 'all',
        selectedBooking: null,
        pendingReloadAfterPop: false,
        editMode: null,
        editDay: null,
        editDate: null,
        /** Minutes from midnight (0–1439) for selected slot starts */
        selectedStarts: new Set(),
        lockedStarts: new Set(),
        applyWeekStart: null,
        /** When true, current/partial week lists Mon… + ended slots (backfill). */
        showPastThisWeek: false,
        bookSlotId: null,
        bookModalStep: 'choice',
        pendingBookClientId: null,
        pendingBookClientName: null,
        bookServices: [],
        bookServiceId: null,
        bookPriceVariantId: null,
        trainerArenas: [],
        bookArenaId: null,
        /** From CRM: /schedule-editor?client_id= — preselect client when booking a slot. */
        deepLinkClientId: null,
        /** Open «Проблема с клиентом» after load (schedule-editor?open_booking=&open_client_problem=1). */
        openClientProblemAfterDetail: false,
        /** 'hub' when opened via /schedule-editor?open_booking=&from=hub (return to trainer-home). */
        bookingDetailReturn: null,
        /** When opened from hub group modal: reopen that modal on back (see hub_group_slot URL param). */
        hubGroupSlotReturnId: null,
        /** When opening booking detail from group hub: reopen hub on back. */
        groupHubSlotId: null,
        /** After history.back / loadSlots: reopen group modal. */
        pendingOpenGroupSlotId: null,
        /** schedule-editor?flow=book from trainer hub — quick datetime modal, then book client. */
        pendingBookFlowFromHub: false,
        /** After datetime when booking from client profile: service/tariff modal (no modalBookClient flash). */
        quickBookProfileServiceStep: false,
        quickBookProfileAwaitingConfirm: false,
        quickBookProfileClientName: null,
        /** Client id for profile quick-book until POST (survives deepLinkClientId clear after confirm). */
        quickBookLockedClientId: null,
        /** schedule-editor?book_group_slot=&anchor_date= from hub — open book-client for that slot after load. */
        pendingBookGroupSlotId: null,
        /** True while booking via POST /trainer/booking/quick (no pre-existing slot). */
        bookFlowQuick: false,
        /** When quick-book starts from booking detail transfer CTA, cancel this old booking after success. */
        rescheduleSourceBookingId: null,
        /** schedule-editor?embed=1 — loaded inside trainer-clients iframe; parent handles success / dismiss. */
        scheduleEditorEmbed: false,
        /** Slots for selected quick-book day (from GET /schedule); used to mark busy hours. */
        quickBookSlotsForDay: null,
        quickBookSlotDate: null,
        /** Minutes from midnight for quick book (15 min grid, 08:00–21:00). */
        quickBookStartMinutes: null,
        quickBookDurationMinutes: 45,
        /** From GET /schedule + /schedule/templates: arena-based grid (kind, hour window, optional :MM offset). */
        scheduleGridPreset: null,
        /** From GET /schedule: profile session_duration_minutes → default duration select when adding slots. */
        defaultSlotDurationMinutes: 45,
        /** From GET /schedule: allow capacity > 1 in POST /schedule/slots (profile opt-in). */
        groupClassesEnabled: false,
        /** 'individual' | 'group' — set before opening calendar/template editor when group classes are enabled. */
        slotEditIntent: null,
        pendingIntentFlow: null,
        pendingTemplateDay: null,
        trainerServices: [],
        /** From GET /trainer/my-services: arenas for group slot venue picker. */
        trainerScheduleArenas: [],
        /** Calendar day editor: start minutes that already had slots when the screen opened (cannot deselect). */
        calendarBaselineStarts: null,
        /** Book-client modal: group slot (capacity &gt; 1) — fixed service, no price tier UI. */
        bookSlotIsGroup: false,
        bookSlotGroupServiceId: null,
        /** At least one client with booking history (GET /trainer/clients non-empty). */
        trainerHasBookClients: false,
      };

      // «Написать клиенту»: delegation — Mini App WebView часто игнорирует per-button onclick на динамически вставленных кнопках; tg из замыкания надёжнее window.*.
      document.getElementById('detailBookingActions').addEventListener('click', function(ev) {
        var btn = ev.target && ev.target.closest && ev.target.closest('button[data-baction="write_client"]');
        if (!btn) return;
        ev.preventDefault();
        var booking = state.selectedBooking;
        if (!booking) return;
        var un = String(booking.client_telegram_username || '').replace(/^@/, '').trim();
        var tid = booking.client_telegram_id;
        if (!un && (tid == null || tid === '')) return;
        if (window.openTelegramChatFromMiniApp) {
          window.openTelegramChatFromMiniApp({ username: un, telegramId: tid });
        }
      });

      function syncBookArenaSelects() {
        var v = state.bookArenaId != null ? String(state.bookArenaId) : '';
        var s1 = document.getElementById('bookArenaSelect');
        var s2 = document.getElementById('bookArenaSelectNew');
        if (s1 && s1.value !== v) s1.value = v;
        if (s2 && s2.value !== v) s2.value = v;
      }

      function fillTrainerArenasUI() {
        if (state.bookSlotIsGroup) {
          var w1 = document.getElementById('bookArenaWrap');
          var w2 = document.getElementById('bookArenaWrapNew');
          if (w1) w1.style.display = 'none';
          if (w2) w2.style.display = 'none';
          return;
        }
        var arenas = state.trainerArenas || [];
        var show = arenas.length > 1;
        var wrap = document.getElementById('bookArenaWrap');
        var wrapNew = document.getElementById('bookArenaWrapNew');
        if (wrap) wrap.style.display = show ? 'block' : 'none';
        if (wrapNew) wrapNew.style.display = show ? 'block' : 'none';
        var primary = arenas.filter(function(a) { return a.is_primary; })[0];
        state.bookArenaId = primary ? primary.id : (arenas.length ? arenas[0].id : null);
        function fill(sel) {
          if (!sel) return;
          sel.innerHTML = '';
          arenas.forEach(function(a) {
            var o = document.createElement('option');
            o.value = String(a.id);
            o.textContent = (a.name || '—') + (a.is_primary ? ' · основная' : '');
            sel.appendChild(o);
          });
          if (state.bookArenaId != null) sel.value = String(state.bookArenaId);
        }
        fill(document.getElementById('bookArenaSelect'));
        fill(document.getElementById('bookArenaSelectNew'));
        function onArenaChange() {
          state.bookArenaId = this.value ? parseInt(this.value, 10) : null;
          syncBookArenaSelects();
        }
        var s1 = document.getElementById('bookArenaSelect');
        var s2 = document.getElementById('bookArenaSelectNew');
        if (s1) s1.onchange = onArenaChange;
        if (s2) s2.onchange = onArenaChange;
        syncBookArenaSelects();
      }

      function setBookOptExistingVisible(show) {
        var btn = document.getElementById('bookOptExisting');
        if (!btn) return;
        btn.style.display = show ? '' : 'none';
        btn.setAttribute('aria-hidden', show ? 'false' : 'true');
        btn.tabIndex = show ? 0 : -1;
      }

      function trainerBookingPayload(clientId, serviceId) {
        var o = { slot_id: state.bookSlotId, client_id: clientId, service_id: serviceId };
        if (!state.bookSlotIsGroup && state.trainerArenas && state.trainerArenas.length > 1 && state.bookArenaId != null) {
          o.arena_id = state.bookArenaId;
        }
        if (!state.bookSlotIsGroup && state.bookPriceVariantId != null) {
          o.service_price_variant_id = state.bookPriceVariantId;
        }
        return o;
      }

      function trainerQuickBookingPayload(clientId, serviceId) {
        var o = {
          slot_date: state.quickBookSlotDate,
          start_time: formatMinuteClock(state.quickBookStartMinutes),
          duration_minutes: state.quickBookDurationMinutes || 45,
          client_id: clientId,
          service_id: serviceId
        };
        if (state.trainerArenas && state.trainerArenas.length > 1 && state.bookArenaId != null) {
          o.arena_id = state.bookArenaId;
        }
        if (state.bookPriceVariantId != null) {
          o.service_price_variant_id = state.bookPriceVariantId;
        }
        return o;
      }

      function applyBookModalGroupUi() {
        var hideSvc = !!(state.bookSlotIsGroup && state.bookSlotGroupServiceId != null);
        ['bookServiceSelect', 'bookServiceSelectNew'].forEach(function(id) {
          var el = document.getElementById(id);
          if (el) el.disabled = hideSvc;
        });
        var se = document.getElementById('bookServiceStackExisting');
        var sn = document.getElementById('bookServiceStackNew');
        if (se) se.style.display = hideSvc ? 'none' : '';
        if (sn) sn.style.display = hideSvc ? 'none' : '';
      }

      function clearBookSlotModalState() {
        state.bookSlotId = null;
        state.bookFlowQuick = false;
        state.quickBookSlotDate = null;
        state.quickBookStartMinutes = null;
        state.quickBookSlotsForDay = null;
        state.quickBookDurationMinutes = state.defaultSlotDurationMinutes || 45;
        state.bookSlotIsGroup = false;
        state.bookSlotGroupServiceId = null;
        ['bookServiceSelect', 'bookServiceSelectNew'].forEach(function(id) {
          var el = document.getElementById(id);
          if (el) el.disabled = false;
        });
        var se = document.getElementById('bookServiceStackExisting');
        var sn = document.getElementById('bookServiceStackNew');
        if (se) se.style.display = '';
        if (sn) sn.style.display = '';
        setBookClientSearchSectionVisible(true);
        state.quickBookProfileServiceStep = false;
        state.quickBookProfileAwaitingConfirm = false;
        state.quickBookProfileClientName = null;
        state.quickBookLockedClientId = null;
      }

      function setBookClientSearchSectionVisible(visible) {
        var w = document.getElementById('bookClientSearchWrap');
        if (w) w.style.display = visible ? '' : 'none';
      }

      var QUICK_BOOK_CONTINUE_LABEL_DEFAULT = 'Далее — выбрать клиента';
      var QUICK_BOOK_CONTINUE_LABEL_DEEPLINK = 'Продолжить';

      /** Hub «Записать клиента» vs профиль клиента (?client_id=): другой текст на первом шаге. */
      function syncQuickBookContinueButtonLabel() {
        var btn = document.getElementById('btnQuickBookContinue');
        if (!btn) return;
        btn.textContent = state.deepLinkClientId ? QUICK_BOOK_CONTINUE_LABEL_DEEPLINK : QUICK_BOOK_CONTINUE_LABEL_DEFAULT;
      }

      var PRICE_TIER_LABEL_RU = {
        child: 'Детский',
        adult: 'Взрослый',
        two_children: '2 ребенка',
        two_adults: '2 взрослых',
        adult_and_child: 'Взрослый + ребенок',
      };
      function priceTierLabelRuSe(tier) {
        var k = (tier.tier_kind || '').toLowerCase();
        return PRICE_TIER_LABEL_RU[k] || tier.label || 'Тариф';
      }

      /** When several tiers exist, prefer single adult over API/display order (often child first). */
      function pickDefaultBookPriceTierId(tiers) {
        if (!tiers || !tiers.length) return null;
        if (tiers.length === 1) return tiers[0].id;
        var adult = tiers.filter(function(t) { return (t.tier_kind || '').toLowerCase() === 'adult'; })[0];
        return adult ? adult.id : tiers[0].id;
      }

      function syncBookPriceTierRadios(which) {
        var wrapE = document.getElementById('bookPriceTierWrapExisting');
        var wrapN = document.getElementById('bookPriceTierWrapNew');
        if (state.bookSlotIsGroup) {
          if (wrapE) wrapE.style.display = 'none';
          if (wrapN) wrapN.style.display = 'none';
          state.bookPriceVariantId = null;
          return;
        }
        var sid = state.bookServiceId;
        var svc = (state.bookServices || []).filter(function(x) { return x.id === sid; })[0];
        var tiers = (svc && svc.price_tiers) ? svc.price_tiers : [];
        var wrap = document.getElementById(which === 'existing' ? 'bookPriceTierWrapExisting' : 'bookPriceTierWrapNew');
        var host = document.getElementById(which === 'existing' ? 'bookPriceTierRadiosExisting' : 'bookPriceTierRadiosNew');
        if (!wrap || !host) return;
        if (tiers.length <= 1) {
          wrap.style.display = 'none';
          state.bookPriceVariantId = tiers.length === 1 ? tiers[0].id : null;
          return;
        }
        wrap.style.display = 'block';
        host.innerHTML = '';
        var gname = 'bpt_' + which + '_' + String(state.bookSlotId || 0);
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
          lab.appendChild(document.createTextNode(priceTierLabelRuSe(tier) + ' — ' + priceStr));
          inp.addEventListener('change', function() {
            state.bookPriceVariantId = parseInt(inp.value, 10);
          });
          host.appendChild(lab);
        });
        var preferredId = pickDefaultBookPriceTierId(tiers);
        var pickInp = preferredId != null ? host.querySelector('input[value="' + String(preferredId) + '"]') : null;
        if (pickInp) {
          pickInp.checked = true;
          state.bookPriceVariantId = parseInt(pickInp.value, 10);
        }
      }

      function syncAllBookPriceTierRadios() {
        syncBookPriceTierRadios('existing');
        syncBookPriceTierRadios('new');
      }

      /** Price tiers for profile quick-book service modal (same rules as book modal). */
      function syncQuickBookProfilePriceTierRadios(preferredVariantId) {
        var wrap = document.getElementById('quickBookProfilePriceTierWrap');
        var host = document.getElementById('quickBookProfilePriceTierRadios');
        if (!wrap || !host) return;
        var sid = state.bookServiceId;
        var svc = (state.bookServices || []).filter(function(x) { return x.id === sid; })[0];
        var tiers = (svc && svc.price_tiers) ? svc.price_tiers : [];
        if (tiers.length <= 1) {
          wrap.style.display = 'none';
          state.bookPriceVariantId = tiers.length === 1 ? tiers[0].id : null;
          return;
        }
        wrap.style.display = 'block';
        host.innerHTML = '';
        var gname = 'qb_prof_' + String(sid || 0);
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
          lab.appendChild(document.createTextNode(priceTierLabelRuSe(tier) + ' — ' + priceStr));
          inp.addEventListener('change', function() {
            state.bookPriceVariantId = parseInt(inp.value, 10);
          });
          host.appendChild(lab);
        });
        var pref = preferredVariantId != null ? parseInt(preferredVariantId, 10) : NaN;
        var matched = !isNaN(pref) ? host.querySelector('input[value="' + String(pref) + '"]') : null;
        if (matched) {
          matched.checked = true;
          state.bookPriceVariantId = parseInt(matched.value, 10);
        } else {
          var pid = pickDefaultBookPriceTierId(tiers);
          var pickInp = pid != null ? host.querySelector('input[value="' + String(pid) + '"]') : null;
          if (pickInp) {
            pickInp.checked = true;
            state.bookPriceVariantId = parseInt(pickInp.value, 10);
          }
        }
      }

      function getMonday(d) {
        const date = new Date(d);
        const day = date.getDay();
        const diff = date.getDate() - day + (day === 0 ? -6 : 1);
        return new Date(date.setDate(diff));
      }

      function formatWeekLabel(start) {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const weekEnd = new Date(start);
        weekEnd.setDate(weekEnd.getDate() + 6);
        weekEnd.setHours(0, 0, 0, 0);
        const startCopy = new Date(start);
        startCopy.setHours(0, 0, 0, 0);
        const fmt = function(d) { return d.getDate() + ' ' + MONTHS[d.getMonth()]; };
        if (weekEnd < today) {
          return fmt(startCopy) + ' – ' + fmt(weekEnd);
        }
        const effectiveStart = startCopy < today ? today : startCopy;
        if (effectiveStart > weekEnd) return 'Прошедшая неделя';
        if (effectiveStart.getTime() === weekEnd.getTime()) {
          return effectiveStart.getDate() + ' ' + MONTHS_GENITIVE[effectiveStart.getMonth()];
        }
        return fmt(effectiveStart) + ' – ' + fmt(weekEnd);
      }

      function dateToStr(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return y + '-' + m + '-' + day;
      }

      function formatDateKey(dateStr) {
        const d = new Date(dateStr + 'T12:00:00');
        const wd = d.getDay();
        return d.getDate() + '.' + String(d.getMonth() + 1).padStart(2, '0') + ' (' + DAYS[wd === 0 ? 6 : wd - 1] + ')';
      }

      /** Minutes from midnight; API sends "HH:MM" for slot/template starts. */
      function parseStartToMinutes(startTime) {
        var s = (startTime == null ? '' : String(startTime)).trim();
        var parts = s.split(':');
        var h = parseInt(parts[0], 10);
        var min = parts.length > 1 ? parseInt(parts[1], 10) : 0;
        if (isNaN(h)) h = 0;
        if (isNaN(min)) min = 0;
        return h * 60 + min;
      }

      /** "HH:MM" for minutes-from-midnight (POST /schedule/slots start_times). */
      function formatMinuteClock(totalMinutes) {
        var m = Math.max(0, Math.floor(totalMinutes));
        var h = Math.floor(m / 60);
        var rem = m % 60;
        return String(h).padStart(2, '0') + ':' + String(rem).padStart(2, '0');
      }

      function slotDurationFromRow(row) {
        var d = row && row.duration_minutes != null ? parseInt(row.duration_minutes, 10) : NaN;
        return !isNaN(d) ? d : 45;
      }

      var SCHEDULE_DURATION_OPTIONS = [45, 50, 60, 70, 75, 90, 105, 120, 180];

      /** Map profile minutes to nearest option in #slotDurationSelect / quick-book. */
      function normalizeDurationToScheduleSelect(minutes) {
        var allowed = SCHEDULE_DURATION_OPTIONS;
        var n = parseInt(minutes, 10);
        if (isNaN(n) || n < 15) return 45;
        n = Math.min(480, Math.max(15, n));
        if (allowed.indexOf(n) >= 0) return n;
        var best = 45;
        var bestD = 999;
        for (var i = 0; i < allowed.length; i++) {
          var d = Math.abs(allowed[i] - n);
          if (d < bestD) {
            bestD = d;
            best = allowed[i];
          }
        }
        return best;
      }

      /** Called when GET /schedule returns session_duration_minutes (trainer profile). */
      function applyScheduleDefaultDurationFromProfile(rawMinutes) {
        var n = rawMinutes != null && rawMinutes !== '' ? parseInt(rawMinutes, 10) : NaN;
        state.defaultSlotDurationMinutes = !isNaN(n) ? normalizeDurationToScheduleSelect(n) : 45;
        state.quickBookDurationMinutes = state.defaultSlotDurationMinutes;
        var qbd = document.getElementById('quickBookDurationSelect');
        if (qbd) qbd.value = String(state.defaultSlotDurationMinutes);
      }

      /** Half-open [a, a+da) vs [b, b+db) */
      function intervalsOverlapMin(a, da, b, db) {
        return a < b + db && b < a + da;
      }

      /** Half-open intervals as absolute minutes [a0,a1) vs [b0,b1). */
      function intervalsOverlapAbsolute(a0, a1, b0, b1) {
        return a0 < b1 && b0 < a1;
      }

      function slotIntervalMinutesFromRow(s) {
        var sm = parseStartToMinutes(s.start_time);
        var em = parseStartToMinutes(s.end_time);
        if (em <= sm) em = sm + 60;
        return { start: sm, end: em };
      }

      function defaultScheduleGridPreset() {
        return {
          kind: 'uniform_step',
          minute_offset: 0,
          hour_start: 8,
          hour_end: 21,
          arena_id: null,
          slot_duration_minutes: null,
          step_minutes: 15,
        };
      }

      /** When set, editor and quick book use this duration only (matches arena_schedule_presets.slot_duration_minutes). */
      function scheduleGridFixedDurationMinutes() {
        var p = state.scheduleGridPreset || defaultScheduleGridPreset();
        if (p.slot_duration_minutes == null || p.slot_duration_minutes === '') return null;
        var n = parseInt(p.slot_duration_minutes, 10);
        if (isNaN(n) || n < 15) return null;
        return Math.min(480, n);
      }

      function updateScheduleTimeGridHintFromPreset() {
        var sub = document.getElementById('scheduleTimeGridHint');
        if (!sub) return;
        var p = state.scheduleGridPreset || defaultScheduleGridPreset();
        var k = (p.kind || 'uniform_step').toString().trim();
        if (k === 'hourly_minute') {
          sub.textContent = 'Допустимые начала задаёт площадка';
        } else if (k === 'uniform_step') {
          var sm = parseInt(p.step_minutes, 10);
          if (isNaN(sm) || sm < 5) sm = 15;
          sub.textContent = 'Слева — час, справа слоты с шагом ' + sm + ' мин';
        } else {
          sub.textContent = 'Слева — час, справа четверти (:00 … :45)';
        }
      }

      /** Hide duration selects when preset fixes length; show explanatory line instead. */
      function syncDurationUIFromScheduleGrid() {
        var fixed = scheduleGridFixedDurationMinutes();
        var wrap = document.getElementById('slotDurationWrap');
        var note = document.getElementById('slotDurationFixedNote');
        var durSel = document.getElementById('slotDurationSelect');
        var qbWrap = document.getElementById('quickBookDurationWrap');
        var qbDur = document.getElementById('quickBookDurationSelect');
        var qbHint = document.getElementById('quickBookDurationFixedHint');
        updateScheduleTimeGridHintFromPreset();
        if (fixed != null) {
          if (wrap) wrap.style.display = 'none';
          if (durSel) durSel.value = String(fixed);
          if (note) {
            note.style.display = 'block';
            note.textContent = 'Длительность: ' + fixed + ' мин (зафиксировано правилами площадки).';
          }
          if (qbWrap) qbWrap.style.display = 'none';
          if (qbDur) qbDur.value = String(fixed);
          if (qbHint) {
            qbHint.removeAttribute('hidden');
            qbHint.textContent = 'Длительность: ' + fixed + ' мин (площадка).';
          }
          state.quickBookDurationMinutes = fixed;
        } else {
          if (wrap) wrap.style.display = '';
          if (note) {
            note.style.display = 'none';
            note.textContent = '';
          }
          if (qbWrap) qbWrap.style.display = '';
          if (qbHint) {
            qbHint.setAttribute('hidden', 'hidden');
            qbHint.textContent = '';
          }
        }
        var qbDtLoad = document.getElementById('quickBookDatetimeLoadingWrap');
        if (qbDtLoad) qbDtLoad.classList.toggle('quick-book-datetime-wrap--duration-custom', fixed == null);
      }

      /** Merge schedule_grid from GET /schedule or /schedule/templates into state. */
      function applyScheduleGridFromApi(data) {
        if (data && data.schedule_grid) {
          state.scheduleGridPreset = data.schedule_grid;
        } else if (!state.scheduleGridPreset) {
          state.scheduleGridPreset = defaultScheduleGridPreset();
        }
        syncDurationUIFromScheduleGrid();
      }

      /** Mirrors backend allowed_start_minutes_from_preset (arena_schedule_preset.py). */
      function allowedStartMinutesFromScheduleGridPreset(preset) {
        preset = preset || defaultScheduleGridPreset();
        var kind = (preset.kind || 'uniform_step').toString().trim();
        var h0 = Math.max(0, Math.min(23, parseInt(preset.hour_start, 10)));
        if (isNaN(h0)) h0 = 8;
        var h1 = Math.max(0, Math.min(23, parseInt(preset.hour_end, 10)));
        if (isNaN(h1)) h1 = 21;
        if (h1 < h0) {
          var swap = h0;
          h0 = h1;
          h1 = swap;
        }
        var out = [];
        if (kind === 'hourly_minute') {
          var mo = Math.max(0, Math.min(59, parseInt(preset.minute_offset, 10) || 0));
          for (var h = h0; h <= h1; h++) {
            out.push(h * 60 + mo);
          }
        } else if (kind === 'uniform_step') {
          var step = parseInt(preset.step_minutes, 10);
          if (isNaN(step) || step < 5) step = 15;
          if ([10, 15, 30, 60].indexOf(step) < 0) step = 15;
          for (var m = h0 * 60; m <= h1 * 60; m += step) {
            out.push(m);
          }
        } else {
          for (var m2 = h0 * 60; m2 <= h1 * 60; m2 += 15) {
            out.push(m2);
          }
        }
        return out;
      }

      function scheduleGridHintSuffix() {
        var p = state.scheduleGridPreset || defaultScheduleGridPreset();
        var k = (p.kind || 'uniform_step').toString().trim();
        var base;
        if (k === 'hourly_minute') {
          var mo = Math.max(0, Math.min(59, parseInt(p.minute_offset, 10) || 0));
          base = 'Сетка: :' + String(mo).padStart(2, '0') + ' каждый час';
        } else if (k === 'uniform_step') {
          var sm = parseInt(p.step_minutes, 10);
          if (isNaN(sm) || sm < 5) sm = 15;
          base = 'Отметьте начала (шаг ' + sm + ' мин)';
        } else {
          base = 'Отметьте начала (шаг 15 мин)';
        }
        var fxd = scheduleGridFixedDurationMinutes();
        if (fxd != null) {
          return base + ', длительность ' + fxd + ' мин';
        }
        return base;
      }

      function getEditDurationMinutes() {
        var fixed = scheduleGridFixedDurationMinutes();
        if (fixed != null) return fixed;
        var durSel = document.getElementById('slotDurationSelect');
        var d = durSel ? parseInt(durSel.value, 10) : 45;
        if (isNaN(d) || d < 15) d = 45;
        return Math.min(480, Math.max(15, d));
      }

      /** Calendar baseline slot without booking — cannot deselect (same as pinned chip). */
      function isMinutePinnedBaseline(m) {
        return (
          state.editMode === 'calendar' &&
          state.calendarBaselineStarts &&
          state.calendarBaselineStarts.has(m) &&
          state.selectedStarts.has(m) &&
          !state.lockedStarts.has(m)
        );
      }

      /**
       * Drop optional starts that overlap after duration change; keep locked + baseline-pinned.
       * English note: greedy by sorted time — first kept wins; later conflicts are removed.
       */
      function pruneSelectedStartsForOverlap(durationMinutes) {
        var sorted = Array.from(state.selectedStarts).sort(function(a, b) {
          return a - b;
        });
        var kept = new Set();
        sorted.forEach(function(m) {
          if (state.lockedStarts.has(m) || isMinutePinnedBaseline(m)) {
            kept.add(m);
            return;
          }
          var conflict = false;
          kept.forEach(function(s) {
            if (intervalsOverlapMin(s, durationMinutes, m, durationMinutes)) conflict = true;
          });
          if (!conflict) kept.add(m);
        });
        state.selectedStarts = kept;
      }

      /** True if choosing m as a start would overlap any already selected slot span. */
      function isStartMinuteBlockedByOthers(m, durationMinutes, selectedStarts) {
        if (selectedStarts.has(m)) return false;
        var blocked = false;
        selectedStarts.forEach(function(s) {
          if (intervalsOverlapMin(s, durationMinutes, m, durationMinutes)) blocked = true;
        });
        return blocked;
      }

      function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      function setActiveTab(tabName) {
        state.tab = tabName;
        document.querySelectorAll('.tab').forEach(function(x) { x.classList.toggle('active', x.dataset.tab === tabName); });
        var cal = document.getElementById('tabCalendar');
        var tpl = document.getElementById('tabTemplate');
        cal.style.display = '';
        tpl.style.display = '';
        cal.classList.toggle('active', tabName === 'calendar');
        tpl.classList.toggle('active', tabName === 'template');
        if (tabName === 'calendar') loadSlots();
        else loadTemplates();
        updateTelegramBack();
      }

      document.querySelectorAll('.tab').forEach(function(t) {
        t.onclick = function() {
          if (t.dataset.tab === state.tab) return;
          setActiveTab(t.dataset.tab);
        };
      });

      function showMain() {
        showBookingStack('main');
        document.getElementById('screenEdit').style.display = 'none';
        document.getElementById('screenDayPick').style.display = 'none';
        document.querySelector('.tabs').style.display = 'flex';
        var cal = document.getElementById('tabCalendar');
        var tpl = document.getElementById('tabTemplate');
        cal.style.display = '';
        tpl.style.display = '';
        cal.classList.toggle('active', state.tab === 'calendar');
        tpl.classList.toggle('active', state.tab === 'template');
        document.querySelectorAll('.tab').forEach(function(x) {
          x.classList.toggle('active', x.dataset.tab === state.tab);
        });
        if (state.tab === 'calendar') loadSlots();
        else loadTemplates();
        state.slotEditIntent = null;
        state.pendingIntentFlow = null;
        state.pendingTemplateDay = null;
        state.calendarBaselineStarts = null;
        updateTelegramBack();
      }

      function isGroupClassesFeatureEnabled() {
        return !!state.groupClassesEnabled;
      }

      /** Group-only editor controls are visible only for explicit "group" intent. */
      function slotIntentUseGroupUi() {
        return isGroupClassesFeatureEnabled() && state.slotEditIntent === 'group';
      }

      function detectSlotIntentFromRows(rows) {
        var list = Array.isArray(rows) ? rows : [];
        for (var i = 0; i < list.length; i++) {
          var cap = (list[i] && list[i].capacity != null) ? parseInt(list[i].capacity, 10) : 1;
          if (!isNaN(cap) && cap > 1) return 'group';
        }
        return 'individual';
      }

      // English note: one modal entry point keeps the flow explicit before trainer picks a day/hours.
      function openSlotIntentModal(flow, templateDay, suggestedIntent) {
        var modal = document.getElementById('modalSlotIntent');
        if (!modal) return;
        state.pendingIntentFlow = flow || null;
        state.pendingTemplateDay = (templateDay == null ? null : templateDay);
        var hint = suggestedIntent === 'group'
          ? 'В этом дне уже есть групповые часы, поэтому рекомендуем групповой режим.'
          : 'Индивидуальный режим быстрее, если нужен один клиент на каждый час.';
        var titleEl = document.getElementById('slotIntentTitle');
        var textEl = document.getElementById('slotIntentText');
        if (titleEl) {
          titleEl.textContent = flow === 'template' ? 'Шаблон: тип часов' : 'Какие слоты добавить?';
        }
        if (textEl) {
          textEl.textContent = flow === 'template'
            ? ('Выберите формат для выбранного дня шаблона. ' + hint)
            : ('Сначала выберите формат, затем день и часы. ' + hint);
        }
        var ind = document.getElementById('btnSlotIntentIndividual');
        var grp = document.getElementById('btnSlotIntentGroup');
        if (grp) {
          grp.style.display = isGroupClassesFeatureEnabled() ? '' : 'none';
        }
        if (ind) ind.classList.remove('is-suggested');
        if (grp) grp.classList.remove('is-suggested');
        if (suggestedIntent === 'group') {
          if (grp) grp.classList.add('is-suggested');
        } else if (ind) {
          ind.classList.add('is-suggested');
        }
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
        updateTelegramBack();
      }

      /** True if at least one start time was added beyond the slots that existed when opening the day editor. */
      function hasCalendarNewSlotSelection() {
        if (state.editMode !== 'calendar' || !state.calendarBaselineStarts) return true;
        var base = state.calendarBaselineStarts;
        var hasNew = false;
        state.selectedStarts.forEach(function(m) {
          if (!base.has(m)) hasNew = true;
        });
        return hasNew;
      }

      function updateEditDoneButton() {
        var btn = document.getElementById('editDone');
        if (!btn) return;
        if (state.editMode === 'calendar' && state.calendarBaselineStarts) {
          var ok = hasCalendarNewSlotSelection();
          btn.disabled = !ok;
          btn.title = ok ? '' : 'Добавьте хотя бы одно новое время';
        } else {
          btn.disabled = false;
          btn.title = '';
        }
      }

      function buildServiceOptionsHtml(selectedId) {
        var o = '<option value="">— выберите —</option>';
        (state.trainerServices || []).forEach(function(s) {
          var sid = parseInt(s.id, 10);
          var sel = selectedId != null && parseInt(selectedId, 10) === sid ? ' selected' : '';
          o += '<option value="' + sid + '"' + sel + '>' + escapeHtml(s.name || '') + '</option>';
        });
        return o;
      }

      function fillTrainerServiceSelects() {
        var opts = buildServiceOptionsHtml(null);
        var cal = document.getElementById('calendarGroupServiceSelect');
        var td = document.getElementById('templateDefaultServiceSelect');
        if (cal) cal.innerHTML = opts;
        if (td) td.innerHTML = opts;
      }

      /** Template group mode: arena dropdown (same options as calendar group slots). */
      function fillTemplateGroupArenaSelect() {
        var ars = state.trainerScheduleArenas || [];
        var sel = document.getElementById('templateGroupArenaSelect');
        if (!sel) return;
        sel.innerHTML = '';
        ars.forEach(function(a) {
          var o = document.createElement('option');
          o.value = String(a.id);
          o.textContent = (a.name || '—') + (a.is_primary ? ' · основная' : '');
          sel.appendChild(o);
        });
      }

      function applyTemplateGroupPrefillFromExisting(existing, useTplGroup) {
        var tdef = document.getElementById('templateDefaultCapacityInput');
        var tsvc = document.getElementById('templateDefaultServiceSelect');
        if (!useTplGroup) {
          if (tdef) tdef.value = '1';
          return;
        }
        var caps = (existing || []).map(function(t) { return (t.capacity != null) ? parseInt(t.capacity, 10) : 1; });
        var capVal = 2;
        if (caps.length && caps.every(function(c) { return c === caps[0]; })) capVal = Math.max(2, caps[0]);
        if (tdef) tdef.value = String(Math.min(500, capVal));
        var svcPick = null;
        (existing || []).forEach(function(t) {
          var c = (t.capacity != null) ? parseInt(t.capacity, 10) : 1;
          if (c > 1 && t.service_id != null) svcPick = parseInt(t.service_id, 10);
        });
        if (tsvc && svcPick != null && !isNaN(svcPick)) tsvc.value = String(svcPick);
      }

      function loadTrainerServicesIfNeeded() {
        if (state.trainerServices && state.trainerServices.length) {
          fillTrainerServiceSelects();
          return Promise.resolve();
        }
        return fetch(apiUrlWithQuery('/trainer/my-services'), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            state.trainerServices = (data && data.services) ? data.services : [];
            state.trainerScheduleArenas = (data && data.arenas) ? data.arenas : [];
            fillTrainerServiceSelects();
          });
      }

      function showDayPickScreen() {
        if (!state.weekStart) return;
        var dayPickTitle = document.getElementById('dayPickTitle');
        if (dayPickTitle) {
          dayPickTitle.textContent = slotIntentUseGroupUi()
            ? 'Добавить групповые слоты на какой день?'
            : 'Добавить индивидуальные слоты на какой день?';
        }
        const list = document.getElementById('dayPickList');
        let html = '';
        for (let i = 0; i < 7; i++) {
          const d = new Date(state.weekStart);
          d.setDate(d.getDate() + i);
          const dateStr = dateToStr(d);
          html += '<button type="button" class="template-day-card" data-date="' + escapeHtml(dateStr) + '">';
          html += '<span class="day-name">' + DAYS[i] + '</span>';
          html += '<span class="day-slots">' + formatDateKey(dateStr) + '</span>';
          html += '<span class="arrow">→</span></button>';
        }
        if (!html) {
          list.innerHTML = '<div class="empty">Нет дней для выбора.</div>';
        } else {
          list.innerHTML = html;
          document.querySelector('.tabs').style.display = 'none';
          document.getElementById('tabCalendar').style.display = 'none';
          document.getElementById('tabTemplate').style.display = 'none';
          document.getElementById('screenDayPick').style.display = 'block';
          updateTelegramBack();
          document.querySelectorAll('#dayPickList .template-day-card').forEach(function(btn) {
            btn.onclick = function() {
              document.getElementById('screenDayPick').style.display = 'none';
              openEditCalendarDay(btn.dataset.date);
            };
          });
        }
      }

      function applySlotIntentChoice(intent) {
        state.slotEditIntent = intent;
        var flow = state.pendingIntentFlow;
        var dayNum = state.pendingTemplateDay;
        state.pendingIntentFlow = null;
        state.pendingTemplateDay = null;
        var modal = document.getElementById('modalSlotIntent');
        if (modal) {
          modal.style.display = 'none';
          modal.setAttribute('aria-hidden', 'true');
        }
        var ind = document.getElementById('btnSlotIntentIndividual');
        var grp = document.getElementById('btnSlotIntentGroup');
        if (ind) ind.classList.remove('is-suggested');
        if (grp) grp.classList.remove('is-suggested');
        if (flow === 'calendar') {
          showDayPickScreen();
        } else if (flow === 'template' && dayNum != null) {
          openEditTemplateDay(dayNum);
        }
        updateTelegramBack();
      }

      function cancelSlotIntentModal() {
        state.pendingIntentFlow = null;
        state.pendingTemplateDay = null;
        var modal = document.getElementById('modalSlotIntent');
        if (modal) {
          modal.style.display = 'none';
          modal.setAttribute('aria-hidden', 'true');
        }
        var ind = document.getElementById('btnSlotIntentIndividual');
        var grp = document.getElementById('btnSlotIntentGroup');
        if (ind) ind.classList.remove('is-suggested');
        if (grp) grp.classList.remove('is-suggested');
        updateTelegramBack();
      }

      function filterSlotsForUi(slots) {
        if (state.slotFilter === 'all') return slots;
        return slots.filter(function(s) { return (s.status || '') === state.slotFilter; });
      }

      /** Local end Date for a slot (browser TZ), or null if unparsable. */
      function slotLocalEndTime(s) {
        if (!s || !s.slot_date || s.end_time == null || s.end_time === '') return null;
        var parts = String(s.slot_date).split('-');
        if (parts.length !== 3) return null;
        var y = parseInt(parts[0], 10), m = parseInt(parts[1], 10) - 1, day = parseInt(parts[2], 10);
        var tp = String(s.end_time).split(':');
        var hh = parseInt(tp[0], 10) || 0, mm = parseInt(tp[1], 10) || 0;
        var sec = tp.length > 2 ? parseInt(tp[2], 10) : 0;
        return new Date(y, m, day, hh, mm, isNaN(sec) ? 0 : sec, 0);
      }

      function isSlotEndedInPast(s) {
        var end = slotLocalEndTime(s);
        if (!end) return false;
        return end.getTime() < Date.now();
      }

      /** Hide past calendar days and today's slots that already ended (local time). */
      function filterOutPastSlots(slots) {
        var todayStr = dateToStr(new Date());
        return slots.filter(function(s) {
          if (s.slot_date < todayStr) return false;
          if (s.slot_date > todayStr) return true;
          return !isSlotEndedInPast(s);
        });
      }

      /** Monday-based week fully before today (00:00 local) — show full history without hiding past days. */
      function isEntireWeekInPast(weekStart) {
        var end = new Date(weekStart);
        end.setDate(end.getDate() + 6);
        end.setHours(0, 0, 0, 0);
        var t = new Date();
        t.setHours(0, 0, 0, 0);
        return end < t;
      }

      function countPastHiddenSlots(slots) {
        if (!slots || !slots.length) return 0;
        return slots.length - filterOutPastSlots(slots).length;
      }

      function pastSlotsToggleLabel(n) {
        var nv = n % 100;
        var nl = n % 10;
        var word = (nv >= 11 && nv <= 14) ? 'слотов' : (nl === 1 ? 'слот' : (nl >= 2 && nl <= 4 ? 'слота' : 'слотов'));
        return 'Показать прошлые · ' + n + ' ' + word;
      }

      function updatePastRevealChrome() {
        var wrap = document.getElementById('calendarPastRevealWrap');
        var btn = document.getElementById('btnTogglePastThisWeek');
        if (!wrap || !btn) return;
        var entirePast = isEntireWeekInPast(state.weekStart);
        var n = countPastHiddenSlots(state.slots);
        if (entirePast || n === 0) {
          wrap.hidden = true;
          state.showPastThisWeek = false;
          return;
        }
        wrap.hidden = false;
        var label = btn.querySelector('.calendar-past-reveal-label');
        if (state.showPastThisWeek) {
          btn.setAttribute('aria-expanded', 'true');
          if (label) label.textContent = 'Скрыть прошлые';
        } else {
          btn.setAttribute('aria-expanded', 'false');
          if (label) label.textContent = pastSlotsToggleLabel(n);
        }
      }

      function loadSlots() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        if (tg && !tg.initData) {
          loadSlots._waitInit = (loadSlots._waitInit || 0) + 1;
          if (loadSlots._waitInit < 200) {
            document.getElementById('calendarContent').innerHTML = buildCalendarSkeletonHtml();
            setTimeout(function() {
              callReadyWhenInitDataReady();
              loadSlots();
            }, 50);
            return;
          }
          loadSlots._waitInit = 0;
          document.getElementById('calendarContent').innerHTML = '<div class="error">Нет данных авторизации Telegram. Закройте мини-приложение и откройте «Расписание» через меню бота (кнопка слева от поля ввода) или через кнопку под сообщением в чате.</div>';
          hideFlowBookBootOverlay();
          return;
        }
        loadSlots._waitInit = 0;
        callReadyWhenInitDataReady();

        if (!state.weekStart) state.weekStart = getMonday(new Date());
        const start = state.weekStart;
        const end = new Date(start);
        end.setDate(end.getDate() + 6);
        const from = dateToStr(start);
        const to = dateToStr(end);
        document.getElementById('weekLabel').textContent = formatWeekLabel(start);
        var pastWrap = document.getElementById('calendarPastRevealWrap');
        if (pastWrap) pastWrap.hidden = true;
        document.getElementById('calendarContent').innerHTML = buildCalendarSkeletonHtml();
        fetch(apiUrlWithQuery('/schedule?from_date=' + encodeURIComponent(from) + '&to_date=' + encodeURIComponent(to)), { headers: headers() })
          .then(function(r) {
            if (!r.ok) {
              return r.json().then(function(body) {
                var msg = (body && body.detail) ? String(body.detail) : '';
                if (r.status === 401 && msg.indexOf('init') >= 0 && tg && !tg.initData) {
                  return Promise.reject('retry-init');
                }
                throw new Error(msg || 'Ошибка загрузки');
              });
            }
            return r.json();
          })
          .then(function(data) {
            state.slots = (data && data.slots) ? data.slots : [];
            if (data && data.trainer_id != null && !isNaN(parseInt(String(data.trainer_id), 10))) {
              state.trainerId = parseInt(String(data.trainer_id), 10);
            }
            state.groupClassesEnabled = !!(data && data.group_classes_enabled);
            applyScheduleDefaultDurationFromProfile(data && data.session_duration_minutes);
            applyScheduleGridFromApi(data);
            state.scheduleDataLoaded = true;
            var fromHubQuickBook = state.pendingBookFlowFromHub;
            if (fromHubQuickBook) {
              state.pendingBookFlowFromHub = false;
              openQuickBookModalFromHub();
            }
            if (fromHubQuickBook) {
              requestAnimationFrame(function() {
                renderCalendar();
              });
            } else {
              renderCalendar();
            }
            flushPendingGroupHubModal();
            if (state.pendingBookGroupSlotId) {
              var sidPb = state.pendingBookGroupSlotId;
              state.pendingBookGroupSlotId = null;
              var slotRowPb = (state.slots || []).find(function(x) { return x.id === sidPb; });
              if (slotRowPb) {
                setTimeout(function() { openBookModalForSlot(sidPb); }, 60);
              } else {
                showToast('Слот на другой неделе — перелистните календарь или откройте запись из расписания.');
              }
            }
          })
          .catch(function(err) {
            if (err === 'retry-init') {
              setTimeout(loadSlots, 100);
              return;
            }
            hideFlowBookBootOverlay();
            renderCalendarLoadFailure();
          });
      }

      function loadTemplates() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        document.getElementById('templateList').innerHTML = buildTemplateListSkeletonHtml();
        fetch(apiUrlWithQuery('/schedule/templates'), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            state.templates = data.templates || [];
            applyScheduleGridFromApi(data);
            renderTemplate();
          })
          .catch(function() {
            renderTemplateLoadFailure();
          });
      }

      function formatQuickBookSlotLabel() {
        if (!state.quickBookSlotDate || state.quickBookStartMinutes == null) return '';
        var dsl = formatDateKey(state.quickBookSlotDate);
        return dsl + ' ' + formatMinuteClock(state.quickBookStartMinutes);
      }

      /**
       * free — можно создать/использовать слот; busy — занято; group — группа;
       * past — уже прошло; overlap — пересечение с другим слотом при этой длительности; invalid — не влезает в сутки.
       */
      function quickBookSlotAvailability(slotsForDay, startMinutes, durationMinutes, isoDate) {
        var dm = durationMinutes || 45;
        var newEnd = startMinutes + dm;
        if (newEnd > 24 * 60) return 'invalid';
        var todayStr = dateToStr(new Date());
        if (isoDate === todayStr) {
          var now = new Date();
          var nowM = now.getHours() * 60 + now.getMinutes();
          if (startMinutes < nowM) return 'past';
        }
        var rows = (slotsForDay || []).filter(function(s) {
          return (s.status || '').toLowerCase() !== 'cancelled';
        });
        for (var i = 0; i < rows.length; i++) {
          var s = rows[i];
          var iv = slotIntervalMinutesFromRow(s);
          if (!intervalsOverlapAbsolute(startMinutes, newEnd, iv.start, iv.end)) continue;
          var cap = (s.capacity != null) ? parseInt(s.capacity, 10) : 1;
          if (isNaN(cap) || cap < 1) cap = 1;
          var occ = (s.active_bookings != null) ? parseInt(s.active_bookings, 10) : 0;
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

      function setQuickBookHourHint(text, show) {
        var el = document.getElementById('quickBookHourHint');
        if (!el) return;
        if (!show || !text) {
          el.setAttribute('hidden', 'hidden');
          el.textContent = '';
          return;
        }
        el.removeAttribute('hidden');
        el.textContent = text;
      }

      function hideFlowBookBootOverlay() {
        try {
          document.documentElement.classList.remove('se-flow-book-boot');
          var el = document.getElementById('seFlowBookBootOverlay');
          if (el) {
            el.hidden = true;
            el.setAttribute('aria-hidden', 'true');
          }
        } catch (e) { /* ignore */ }
      }

      function setQuickBookDatetimeLoading(on) {
        var wrap = document.getElementById('quickBookDatetimeLoadingWrap');
        var modal = document.getElementById('modalQuickBookDatetime');
        if (wrap) wrap.classList.toggle('quick-book-datetime-loading-wrap--loading', !!on);
        if (modal) modal.setAttribute('aria-busy', on ? 'true' : 'false');
      }

      function setQuickBookProfileServiceLoading(on) {
        var wrap = document.getElementById('quickBookServiceLoadingWrap');
        var modal = document.getElementById('modalQuickBookService');
        if (wrap) wrap.classList.toggle('quick-book-service-loading-wrap--loading', !!on);
        if (modal) modal.setAttribute('aria-busy', on ? 'true' : 'false');
      }

      /** Rebuild start-time &lt;select&gt; from arena grid (GET /schedule) + chosen duration. */
      function refreshQuickBookHourOptions(isoDate) {
        var hourSel = document.getElementById('quickBookHourSelect');
        var durEl = document.getElementById('quickBookDurationSelect');
        if (!hourSel || !isoDate) return Promise.resolve();
        var dm = durEl ? parseInt(durEl.value, 10) : 45;
        if (isNaN(dm) || dm < 15) dm = 45;
        hourSel.disabled = true;
        hourSel.innerHTML = '';
        var btnGo = document.getElementById('btnQuickBookContinue');
        if (btnGo) btnGo.disabled = true;
        setQuickBookDatetimeLoading(true);
        setQuickBookHourHint('', false);
        return fetch(
          apiUrlWithQuery('/schedule?from_date=' + encodeURIComponent(isoDate) + '&to_date=' + encodeURIComponent(isoDate)),
          { headers: headers() }
        )
          .then(function(r) {
            if (!r.ok) return Promise.reject(new Error('schedule'));
            return r.json();
          })
          .then(function(data) {
            applyScheduleGridFromApi(data);
            var slots = (data && data.slots) ? data.slots : [];
            var slotsForDay = slots.filter(function(s) {
              var d = s.slot_date;
              return d === isoDate || String(d) === isoDate;
            });
            state.quickBookSlotsForDay = slotsForDay;
            var prev = hourSel.value;
            hourSel.innerHTML = '';
            var anyFree = false;
            var gridMins = allowedStartMinutesFromScheduleGridPreset(state.scheduleGridPreset);
            for (var gi = 0; gi < gridMins.length; gi++) {
              var m = gridMins[gi];
              var opt = document.createElement('option');
              opt.value = String(m);
              var label = formatMinuteClock(m);
              var av = quickBookSlotAvailability(slotsForDay, m, dm, isoDate);
              if (av === 'past') {
                opt.disabled = true;
                opt.textContent = label + ' — прошло';
              } else if (av === 'busy') {
                opt.disabled = true;
                opt.textContent = label + ' — занято';
              } else if (av === 'group') {
                opt.disabled = true;
                opt.textContent = label + ' — группа';
              } else if (av === 'overlap') {
                opt.disabled = true;
                opt.textContent = label + ' — пересечение';
              } else if (av === 'invalid') {
                opt.disabled = true;
                opt.textContent = label + ' — не влезает';
              } else {
                opt.textContent = label;
                anyFree = true;
              }
              hourSel.appendChild(opt);
            }
            var tryPrev = hourSel.querySelector('option[value="' + prev + '"]:not([disabled])');
            if (tryPrev) {
              hourSel.value = prev;
            } else {
              var firstOk = hourSel.querySelector('option:not([disabled])');
              if (firstOk) hourSel.value = firstOk.value;
              else if (hourSel.options.length) hourSel.value = hourSel.options[0].value;
            }
            hourSel.disabled = false;
            if (!anyFree) {
              setQuickBookHourHint(
                'Нет свободного времени в сетке на выбранную длительность — смените дату, длительность или откройте расписание.',
                true
              );
            } else {
              setQuickBookHourHint('', false);
            }
            var btnGo2 = document.getElementById('btnQuickBookContinue');
            if (btnGo2) btnGo2.disabled = !anyFree;
            setQuickBookDatetimeLoading(false);
          })
          .catch(function() {
            hourSel.disabled = false;
            var btnGo3 = document.getElementById('btnQuickBookContinue');
            if (btnGo3) btnGo3.disabled = false;
            hourSel.innerHTML = '';
            var fallbackMins = allowedStartMinutesFromScheduleGridPreset(state.scheduleGridPreset);
            for (var fi = 0; fi < fallbackMins.length; fi++) {
              var m2 = fallbackMins[fi];
              var o = document.createElement('option');
              o.value = String(m2);
              o.textContent = formatMinuteClock(m2);
              hourSel.appendChild(o);
            }
            setQuickBookHourHint('Не удалось проверить занятость — выберите время вручную.', true);
            showToast('Не удалось загрузить расписание');
            setQuickBookDatetimeLoading(false);
          });
      }

      var quickBookDateDebounce = null;
      function scheduleQuickBookHourRefresh() {
        if (quickBookDateDebounce) clearTimeout(quickBookDateDebounce);
        quickBookDateDebounce = setTimeout(function() {
          quickBookDateDebounce = null;
          var inp = document.getElementById('quickBookDateInput');
          if (inp && inp.value) refreshQuickBookHourOptions(inp.value);
        }, 300);
      }

      function openQuickBookModalFromHub(prefill) {
        var mq = document.getElementById('modalQuickBookDatetime');
        if (!mq) return;
        prefill = prefill || {};
        var minD = dateToStr(new Date());
        var inp = document.getElementById('quickBookDateInput');
        if (inp) {
          inp.min = minD;
          var pDate = (prefill.date || '').trim();
          inp.value = pDate && pDate >= minD ? pDate : minD;
        }
        var dur = document.getElementById('quickBookDurationSelect');
        if (dur) {
          var pDur = parseInt(prefill.durationMinutes, 10);
          dur.value = String(!isNaN(pDur) && pDur >= 15 ? pDur : (state.defaultSlotDurationMinutes || 45));
        }
        syncDurationUIFromScheduleGrid();
        setQuickBookDatetimeLoading(true);
        mq.style.display = 'flex';
        mq.setAttribute('aria-hidden', 'false');
        hideFlowBookBootOverlay();
        updateTelegramBack();
        syncQuickBookContinueButtonLabel();
        var dateToLoad = inp ? inp.value : minD;
        var preStart = parseInt(prefill.startMinutes, 10);
        refreshQuickBookHourOptions(dateToLoad).then(function() {
          if (isNaN(preStart)) return;
          var hourSel = document.getElementById('quickBookHourSelect');
          if (!hourSel) return;
          var wanted = String(preStart);
          var opt = hourSel.querySelector('option[value="' + wanted + '"]:not([disabled])');
          if (opt) hourSel.value = wanted;
        });
      }

      function bookingDurationMinutes(b) {
        var sm = parseStartToMinutes(b && b.start_time);
        var em = parseStartToMinutes(b && b.end_time);
        var dm = em - sm;
        return dm >= 15 ? dm : 45;
      }

      function startRescheduleFromBooking(b) {
        if (!b || !b.client_id) {
          showToast('Нельзя перенести: клиент не найден.');
          return;
        }
        state.rescheduleSourceBookingId = b.id;
        state.deepLinkClientId = b.client_id;
        state.quickBookProfileClientName = (b.client_name || '').trim() || 'Клиент';
        var slotDate = (b.slot_date || '').toString().slice(0, 10);
        var dm = bookingDurationMinutes(b);
        var startM = parseStartToMinutes(b.start_time);
        state.quickBookDurationMinutes = dm;
        openQuickBookModalFromHub({
          date: slotDate,
          durationMinutes: dm,
          startMinutes: startM
        });
      }

      /**
       * After datetime, when client_id is in URL: load services + last completed defaults,
       * show service/tariff modal only (no modalBookClient), then final confirm.
       */
      function openQuickBookProfileServiceStep(mqDatetime, finishBtn) {
        var cid = state.deepLinkClientId;
        if (!cid) {
          setQuickBookHourHint('', false);
          openBookModalForQuickFlow();
          if (finishBtn) finishBtn();
          return;
        }
        state.bookFlowQuick = true;
        state.quickBookProfileServiceStep = true;
        state.quickBookLockedClientId = cid;
        hideFlowBookBootOverlay();
        var ms = document.getElementById('modalQuickBookService');
        setQuickBookProfileServiceLoading(true);
        if (ms) {
          ms.style.display = 'flex';
          ms.setAttribute('aria-hidden', 'false');
        }
        if (mqDatetime) {
          mqDatetime.style.display = 'none';
          mqDatetime.setAttribute('aria-hidden', 'true');
        }
        setQuickBookDatetimeLoading(false);
        updateTelegramBack();
        Promise.all([
          fetch(apiUrlWithQuery('/trainer/my-services'), { headers: headers() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('svc'));
          }),
          fetch(apiUrlWithQuery('/trainer/clients/' + encodeURIComponent(cid) + '/booking-defaults'), { headers: headers() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('def'));
          }),
        ])
          .then(function(results) {
            setQuickBookProfileServiceLoading(false);
            var servicesPayload = results[0];
            var defaults = results[1];
            state.bookServices = servicesPayload.services || [];
            if (!state.bookServices.length) {
              state.bookFlowQuick = false;
              state.quickBookProfileServiceStep = false;
              state.quickBookLockedClientId = null;
              showToast('Добавьте услугу в профиле');
              if (ms) {
                ms.style.display = 'none';
                ms.setAttribute('aria-hidden', 'true');
              }
              if (mqDatetime) {
                mqDatetime.style.display = 'flex';
                mqDatetime.setAttribute('aria-hidden', 'false');
              }
              updateTelegramBack();
              if (finishBtn) finishBtn();
              return;
            }
            state.trainerArenas = servicesPayload.arenas || [];
            var arenas = state.trainerArenas || [];
            var primary = arenas.filter(function(a) { return a.is_primary; })[0];
            state.bookArenaId = primary ? primary.id : (arenas.length ? arenas[0].id : null);
            var fn = (defaults.client_first_name || '').trim();
            var ln = (defaults.client_last_name || '').trim();
            state.quickBookProfileClientName = (fn + ' ' + ln).trim() || 'Клиент';

            var sel = document.getElementById('quickBookProfileServiceSelect');
            if (!sel) {
              if (finishBtn) finishBtn();
              return;
            }
            sel.innerHTML = '';
            state.bookServices.forEach(function(s) {
              var opt = document.createElement('option');
              opt.value = String(s.id);
              opt.textContent = s.name || '—';
              sel.appendChild(opt);
            });
            var defSid = defaults.service_id != null ? parseInt(defaults.service_id, 10) : NaN;
            var picked = state.bookServices.length ? state.bookServices[0].id : null;
            if (!isNaN(defSid) && state.bookServices.some(function(s) { return s.id === defSid; })) {
              picked = defSid;
            }
            state.bookServiceId = picked;
            sel.value = picked != null ? String(picked) : '';
            sel.onchange = function() {
              state.bookServiceId = this.value ? parseInt(this.value, 10) : null;
              syncQuickBookProfilePriceTierRadios(null);
            };

            var wrapA = document.getElementById('quickBookProfileArenaWrap');
            var selA = document.getElementById('quickBookProfileArenaSelect');
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
                selA.value = state.bookArenaId != null ? String(state.bookArenaId) : '';
                selA.onchange = function() {
                  state.bookArenaId = this.value ? parseInt(this.value, 10) : null;
                };
              }
            }

            var defVid = defaults.service_price_variant_id != null ? parseInt(defaults.service_price_variant_id, 10) : null;
            syncQuickBookProfilePriceTierRadios(defVid);

            updateTelegramBack();
            if (finishBtn) finishBtn();
          })
          .catch(function() {
            setQuickBookProfileServiceLoading(false);
            state.bookFlowQuick = false;
            state.quickBookProfileServiceStep = false;
            state.quickBookLockedClientId = null;
            showToast('Не удалось загрузить услуги');
            if (ms) {
              ms.style.display = 'none';
              ms.setAttribute('aria-hidden', 'true');
            }
            if (mqDatetime) {
              mqDatetime.style.display = 'flex';
              mqDatetime.setAttribute('aria-hidden', 'false');
            }
            updateTelegramBack();
            if (finishBtn) finishBtn();
          });
      }

      function scrollToFirstFreeSlotRow() {
        state.slotFilter = 'available';
        document.querySelectorAll('.filter-btn[data-slot-filter]').forEach(function(b) {
          b.classList.toggle('active', (b.getAttribute('data-slot-filter') || '') === 'available');
        });
        renderCalendar();
        setTimeout(function() {
          var el = document.querySelector('#calendarContent .slot-available');
          if (el) {
            try {
              el.scrollIntoView({ block: 'center', behavior: 'smooth' });
            } catch (e) {
              el.scrollIntoView(true);
            }
          } else {
            showToast('На этой неделе нет свободных слотов — смените неделю или добавьте слоты.');
          }
        }, 80);
      }

      /** Opens confirm overlay for chosen client (slot or quick-book). */
      function openBookConfirmForClient(clientId, clientName) {
        if (!state.bookSlotId && !state.bookFlowQuick) return;
        var slotLabel = '';
        if (state.bookFlowQuick) {
          slotLabel = formatQuickBookSlotLabel();
        } else {
          var slot = state.slots.find(function(s) { return s.id === state.bookSlotId; });
          slotLabel = slot ? (formatDateKey(slot.slot_date) + ' ' + (slot.start_time || '').toString().slice(0, 5)) : '';
        }
        state.pendingBookClientId = clientId;
        state.pendingBookClientName = clientName;
        document.getElementById('modalBookConfirmText').textContent = 'Записать ' + clientName + ' на ' + slotLabel + '?';
        document.getElementById('modalBookConfirm').style.display = 'flex';
        updateTelegramBack();
        state.deepLinkClientId = null;
      }

      /** Loads services/clients and wires book modal (shared by slot-based and quick book). */
      function runBookModalShellAndFetch() {
        var prefilledClient = !!state.deepLinkClientId;
        state.bookModalStep = prefilledClient ? 'existing' : 'choice';
        document.getElementById('bookClientSearch').value = '';
        document.getElementById('bookNewPhone').value = '';
        document.getElementById('bookNewFirstName').value = '';
        document.getElementById('bookNewLastName').value = '';
        document.querySelectorAll('.book-step').forEach(function(step) { step.classList.remove('active'); step.style.display = ''; });
        if (prefilledClient) {
          document.getElementById('bookStepChoice').style.display = 'none';
          document.getElementById('bookStepChoice').classList.remove('active');
          document.getElementById('bookStepExisting').style.display = 'block';
          document.getElementById('bookStepExisting').classList.add('active');
          document.getElementById('bookStepNew').style.display = 'none';
          document.getElementById('bookClientList').innerHTML = buildBookClientListSkeletonHtml();
          setBookClientSearchSectionVisible(false);
        } else {
          setBookClientSearchSectionVisible(true);
          document.getElementById('bookStepChoice').style.display = 'block';
          document.getElementById('bookStepChoice').classList.add('active');
          document.getElementById('bookStepExisting').style.display = 'none';
          document.getElementById('bookStepNew').style.display = 'none';
        }
        document.getElementById('modalBookClient').style.display = 'flex';
        applyBookModalGroupUi();
        updateTelegramBack();
        setBookOptExistingVisible(false);
        Promise.all([
          fetch(apiUrlWithQuery('/trainer/my-services'), { headers: headers() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('Ошибка'));
          }),
          fetch(apiUrlWithQuery('/trainer/clients'), { headers: headers() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('Ошибка'));
          }),
        ])
          .then(function(results) {
            var data = results[0];
            var clientsPayload = results[1];
            var hasClients = !!(clientsPayload.clients && clientsPayload.clients.length);
            state.trainerHasBookClients = hasClients;
            setBookOptExistingVisible(hasClients);
            state.bookServices = data.services || [];
            state.bookServiceId = state.bookSlotIsGroup && state.bookSlotGroupServiceId != null
              ? state.bookSlotGroupServiceId
              : (state.bookServices.length ? state.bookServices[0].id : null);
            state.trainerArenas = data.arenas || [];
            function fillServiceSelect(selEl) {
              if (!selEl) return;
              selEl.innerHTML = '';
              state.bookServices.forEach(function(s) {
                var opt = document.createElement('option');
                opt.value = s.id;
                opt.textContent = s.name || '—';
                selEl.appendChild(opt);
              });
              if (
                state.bookSlotIsGroup &&
                state.bookSlotGroupServiceId != null &&
                !state.bookServices.some(function(s) { return s.id === state.bookSlotGroupServiceId; })
              ) {
                var optG = document.createElement('option');
                optG.value = String(state.bookSlotGroupServiceId);
                optG.textContent = 'Услуга слота';
                selEl.appendChild(optG);
              }
              selEl.value = state.bookServiceId != null ? String(state.bookServiceId) : '';
            }
            fillServiceSelect(document.getElementById('bookServiceSelect'));
            fillServiceSelect(document.getElementById('bookServiceSelectNew'));
            applyBookModalGroupUi();
            document.getElementById('bookServiceSelect').onchange = function() {
              state.bookServiceId = this.value ? parseInt(this.value, 10) : null;
              syncAllBookPriceTierRadios();
            };
            document.getElementById('bookServiceSelectNew').onchange = function() {
              state.bookServiceId = this.value ? parseInt(this.value, 10) : null;
              syncAllBookPriceTierRadios();
            };
            syncAllBookPriceTierRadios();
            applyBookModalGroupUi();
            fillTrainerArenasUI();
            if (state.deepLinkClientId && hasClients) {
              var selPre = document.getElementById('bookServiceSelect');
              if (selPre && state.bookServiceId != null) selPre.value = String(state.bookServiceId);
              document.getElementById('bookClientSearch').value = '';
              document.getElementById('bookClientList').innerHTML = buildBookClientListSkeletonHtml();
              loadBookClients('', state.deepLinkClientId);
            } else if (prefilledClient && !hasClients) {
              showToast('Нет клиентов для записи из профиля.');
              state.deepLinkClientId = null;
              document.getElementById('bookStepExisting').style.display = 'none';
              document.getElementById('bookStepExisting').classList.remove('active');
              document.getElementById('bookStepChoice').style.display = 'block';
              document.getElementById('bookStepChoice').classList.add('active');
              state.bookModalStep = 'choice';
              setBookClientSearchSectionVisible(true);
            }
          })
          .catch(function() {
            state.trainerHasBookClients = false;
            setBookOptExistingVisible(false);
            state.bookServices = [];
            state.bookServiceId = null;
            state.trainerArenas = [];
            state.bookArenaId = null;
            document.getElementById('bookServiceSelect').innerHTML = '<option value="">Нет услуг</option>';
            document.getElementById('bookServiceSelectNew').innerHTML = '<option value="">Нет услуг</option>';
            applyBookModalGroupUi();
            fillTrainerArenasUI();
            if (prefilledClient) {
              state.deepLinkClientId = null;
              document.getElementById('bookStepExisting').style.display = 'none';
              document.getElementById('bookStepExisting').classList.remove('active');
              document.getElementById('bookStepChoice').style.display = 'block';
              document.getElementById('bookStepChoice').classList.add('active');
              state.bookModalStep = 'choice';
            }
            setBookClientSearchSectionVisible(true);
          });
      }

      /** Quick book from hub: date/time chosen — no slot row in state yet. */
      function openBookModalForQuickFlow() {
        state.bookSlotId = null;
        state.bookFlowQuick = true;
        state.bookPriceVariantId = null;
        state.bookSlotIsGroup = false;
        state.bookSlotGroupServiceId = null;
        runBookModalShellAndFetch();
      }

      /** Opens the book-client flow for a slot id (used by calendar row and group hub). */
      function openBookModalForSlot(slotId) {
        state.bookFlowQuick = false;
        state.bookSlotId = slotId;
        state.bookPriceVariantId = null;
        state.bookSlotIsGroup = false;
        state.bookSlotGroupServiceId = null;
        var slotRow = (state.slots || []).find(function(x) { return x.id === slotId; });
        if (slotRow) {
          var cap = (slotRow.capacity != null) ? parseInt(slotRow.capacity, 10) : 1;
          if (isNaN(cap) || cap < 1) cap = 1;
          state.bookSlotIsGroup = cap > 1;
          var svcRaw = slotRow.service_id;
          if (svcRaw != null && !isNaN(parseInt(svcRaw, 10))) {
            state.bookSlotGroupServiceId = parseInt(svcRaw, 10);
          }
        }
        if (state.bookSlotIsGroup && state.bookSlotGroupServiceId == null) {
          showToast('У группового слота не задана услуга. Обновите слот в расписании.');
          clearBookSlotModalState();
          return;
        }
        runBookModalShellAndFetch();
      }

      function openGroupSlotModal(slotId) {
        var s = (state.slots || []).find(function(x) { return x.id === slotId; });
        if (!s) return;
        var mgr = document.getElementById('modalGroupSlot');
        if (!mgr) return;
        mgr.style.display = 'flex';
        mgr.setAttribute('aria-hidden', 'false');
        var cap = (s.capacity != null) ? parseInt(s.capacity, 10) : 1;
        var occ = (s.active_bookings != null) ? parseInt(s.active_bookings, 10) : 0;
        var spotsLeft = (s.spots_left != null) ? parseInt(s.spots_left, 10) : Math.max(0, cap - occ);
        document.getElementById('groupSlotTitle').textContent = (s.start_time || '') + '–' + (s.end_time || '');
        var sub = 'Занято ' + occ + ' из ' + cap;
        if (spotsLeft > 0) sub += ' · свободно мест: ' + spotsLeft;
        else sub += ' · группа набрана';
        document.getElementById('groupSlotSub').textContent = sub;
        var listEl = document.getElementById('groupSlotList');
        listEl.innerHTML = '';
        var bookings = s.bookings || [];
        if (bookings.length === 0 && s.client_preview) {
          listEl.innerHTML = '<p class="group-slot-sub">' + escapeHtml(String(s.client_preview)) + '</p>';
        } else {
          bookings.forEach(function(b) {
            var st = (b.status || '').toLowerCase();
            var stLabel = st === 'pending' ? 'Ожидает подтверждения' : 'Подтверждено';
            var bid = parseInt(b.booking_id, 10);
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'group-slot-row';
            btn.innerHTML = '<span><span class="g-name">' + escapeHtml(String(b.client_preview || 'Клиент')) + '</span><br><span class="g-st">' + stLabel + '</span></span><span aria-hidden="true" style="color:var(--tg-theme-hint-color);font-size:18px;">›</span>';
            btn.onclick = function() {
              state.groupHubSlotId = slotId;
              state.bookingDetailReturn = 'group';
              mgr.style.display = 'none';
              mgr.setAttribute('aria-hidden', 'true');
              updateTelegramBack();
              openBookingDetail(bid);
            };
            listEl.appendChild(btn);
          });
        }
        var addBtn = document.getElementById('groupSlotAddBtn');
        if (spotsLeft > 0) {
          addBtn.style.display = 'block';
          addBtn.onclick = function() {
            mgr.style.display = 'none';
            mgr.setAttribute('aria-hidden', 'true');
            updateTelegramBack();
            openBookModalForSlot(slotId);
          };
        } else {
          addBtn.style.display = 'none';
          addBtn.onclick = null;
        }
        updateTelegramBack();
      }

      function renderCalendar() {
        const byDay = {};
        var entirePast = isEntireWeekInPast(state.weekStart);
        var baseSlots = entirePast || state.showPastThisWeek
          ? state.slots
          : filterOutPastSlots(state.slots);
        filterSlotsForUi(baseSlots).forEach(function(s) {
          const key = s.slot_date;
          if (!byDay[key]) byDay[key] = [];
          byDay[key].push(s);
        });
        const days = Object.keys(byDay).sort();
        const content = document.getElementById('calendarContent');
        var hiddenPastN = (!entirePast && !state.showPastThisWeek) ? countPastHiddenSlots(state.slots) : 0;
        if (days.length === 0) {
          if (state.slotFilter === 'all' && hiddenPastN > 0 && !state.showPastThisWeek) {
            content.innerHTML = '<div class="empty calendar-past-nudge">Слоты прошедших дней на этой неделе скрыты. Откройте список кнопкой выше — можно записать клиента задним числом или поправить слоты.</div>';
          } else {
            content.innerHTML = '<div class="empty">На эту неделю слотов нет. Добавьте слоты или примените шаблон.</div>';
          }
          updatePastRevealChrome();
          return;
        }
        let html = '';
        days.forEach(function(dateKey) {
          const daySlots = byDay[dateKey]
            .filter(function(s) { return !s.training_group_id; })
            .sort(function(a, b) { return (a.start_time || '').localeCompare(b.start_time || ''); });
          if (!daySlots.length) return;
          html += '<div class="day-block"><div class="day-title">' + escapeHtml(formatDateKey(dateKey)) + '</div>';
          daySlots.forEach(function(s) {
            const status = s.status || 'available';
            const cap = (s.capacity != null) ? parseInt(s.capacity, 10) : 1;
            const occ = (s.active_bookings != null) ? parseInt(s.active_bookings, 10) : 0;
            const spotsLeft = (s.spots_left != null) ? parseInt(s.spots_left, 10) : Math.max(0, cap - occ);
            const cohortSlot = !!(s.training_group_id);
            const available = status === 'available' && spotsLeft > 0;
            const bookableAvailable = available && !cohortSlot;
            const slotPast = isSlotEndedInPast(s);
            const groupHub = cap > 1 && occ > 0 && !cohortSlot;
            const bookedClick = !!(s.booking_id) && !available && !groupHub && !cohortSlot;
            const bst = bookedClick ? String(s.booking_status || 'confirmed').toLowerCase() : '';
            const bookingPending = bookedClick && bst === 'pending';
            const bookingCompleted = bookedClick && bst === 'completed';
            const bookingConfirmed = bookedClick && bst === 'confirmed';
            let statusLabel = status === 'available' ? 'свободен' : status === 'booked' ? 'занят' : 'отменён';
            if (cap > 1 && !groupHub) {
              statusLabel = occ + '/' + cap;
              if (spotsLeft > 0) statusLabel += ' · есть места';
              else statusLabel += ' · полная группа';
            }
            let statusClass = status;
            if (bookedClick) {
              if (bookingPending) {
                statusLabel = 'к подтверждению';
                statusClass = 'booked booked-pending';
              } else if (bookingCompleted) {
                statusLabel = 'проведено';
                statusClass = 'booked booked-completed';
              } else {
                statusLabel = 'подтверждено';
                statusClass = 'booked booked-confirmed';
              }
            }
            const pct = cap > 0 ? Math.min(100, Math.round((occ / cap) * 100)) : 0;
            html += '<div class="slot-row' + (slotPast ? ' slot-past' : '')
              + (cohortSlot ? ' slot-cohort' : '')
              + (groupHub ? ' slot-group-hub' : '')
              + (!groupHub && bookableAvailable ? ' slot-available' : '')
              + (!groupHub && bookedClick ? ' slot-booked-click' : '')
              + (bookingPending ? ' slot-booking-pending' : '')
              + (bookingConfirmed ? ' slot-booking-confirmed' : '')
              + (bookingCompleted ? ' slot-booking-completed' : '') + '"'
              + (!groupHub && bookableAvailable ? ' data-slot-id="' + s.id + '" role="button" tabindex="0"' : '')
              + (groupHub ? ' data-slot-id="' + s.id + '" data-group-hub="1" role="button" tabindex="0"' : '')
              + (cohortSlot ? ' data-training-group-id="' + String(s.training_group_id) + '" role="button" tabindex="0"' : '')
              + (!groupHub && bookedClick ? ' data-booking-id="' + s.booking_id + '" role="button" tabindex="0"' : '')
              + (!groupHub && bookedClick ? ' data-booking-status="' + escapeHtml(bst) + '"' : '')
              + '>';
            html += '<div class="slot-row-left">';
            html += '<span class="slot-time">' + escapeHtml(s.start_time || '') + '–' + escapeHtml(s.end_time || '') + '</span>';
            if (s.training_group_id && s.training_group_name) {
              html += '<div class="slot-cohort-hint">Группа: ' + escapeHtml(s.training_group_name) + '</div>';
            }
            if (cap > 1) {
              var svcL = (s.service_label && String(s.service_label).trim()) || '';
              var arL = (s.arena_label && String(s.arena_label).trim()) || '';
              if (svcL || arL) {
                html += '<div class="slot-group-catalog-meta">';
                if (svcL) html += '<div class="slot-group-meta-line">' + escapeHtml(svcL) + '</div>';
                if (arL) html += '<div class="slot-group-meta-line">' + escapeHtml(arL) + '</div>';
                html += '</div>';
              }
            }
            if (groupHub) {
              html += '<div class="slot-group-meter-wrap" aria-hidden="true"><div class="slot-group-meter-fill" style="width:' + pct + '%"></div></div>';
            }
            if (bookedClick) {
              const v = s.venue_label;
              const vt = (v && String(v).trim()) ? escapeHtml(String(v).trim()) : '<span class="venue-muted">не указано</span>';
              html += '<div class="slot-venue">📍 ' + vt + '</div>';
              // Group cohort slots: keep card compact — roster lives in «Группы», not on every slot row
              if (s.client_preview && !cohortSlot) html += '<div class="slot-client-hint">' + escapeHtml(s.client_preview) + '</div>';
            } else if (occ > 0 && s.client_preview && !groupHub && !cohortSlot) {
              html += '<div class="slot-client-hint">' + escapeHtml(s.client_preview) + '</div>';
            } else if (groupHub && s.client_preview) {
              html += '<div class="slot-client-hint">' + escapeHtml(s.client_preview) + '</div>';
            }
            html += '</div>';
            html += '<div class="slot-meta">';
            if (groupHub) {
              html += '<span class="slot-group-chip">' + occ + '/' + cap + '</span>';
              if (spotsLeft > 0) {
                html += '<span class="slot-status available" style="font-size:11px;padding:4px 8px;">ещё места</span>';
              } else {
                html += '<span class="slot-status booked" style="font-size:11px;padding:4px 8px;">полная</span>';
              }
            } else {
              html += '<span class="slot-status ' + statusClass + '">' + statusLabel + '</span>';
            }
            if (status === 'available' && occ === 0 && !cohortSlot) {
              html += '<button type="button" class="btn-slot-del" data-slot-id="' + s.id + '" aria-label="Удалить">×</button>';
            }
            html += '</div></div>';
          });
          html += '</div>';
        });
        if (!html) {
          if (state.slotFilter === 'all' && hiddenPastN > 0 && !state.showPastThisWeek) {
            content.innerHTML = '<div class="empty calendar-past-nudge">Слоты прошедших дней на этой неделе скрыты. Откройте список кнопкой выше — можно записать клиента задним числом или поправить слоты.</div>';
          } else {
            content.innerHTML = '<div class="empty">На эту неделю слотов нет. Добавьте слоты или примените шаблон.</div>';
          }
          updatePastRevealChrome();
          return;
        }
        content.innerHTML = html;
        content.querySelectorAll('.btn-slot-del').forEach(function(btn) {
          btn.onclick = function(e) {
            e.stopPropagation();
            const id = parseInt(btn.dataset.slotId, 10);
            showAppConfirm('Удалить этот слот?', { okText: 'Удалить', cancelText: 'Отмена' }).then(function (ok) {
              if (!ok) return;
              fetch(apiUrlWithQuery('/schedule/slots/' + id), { method: 'DELETE', headers: headers() })
                .then(function(r) {
                  if (r.ok) {
                    showToast('Слот удалён');
                    loadSlots();
                  } else {
                    r.json().then(function(o) {
                      var d = o.detail || 'Ошибка';
                      showToast(typeof d === 'string' ? d : 'Не удалось удалить');
                    });
                  }
                })
                .catch(function() { showToast('Ошибка сети'); });
            });
          };
        });
        content.querySelectorAll('.slot-cohort').forEach(function(row) {
          row.onclick = function(e) {
            if (e.target.closest('.btn-slot-del')) return;
            var gid = row.getAttribute('data-training-group-id');
            if (gid) {
              var u = '/webapp/trainer-groups?id=' + encodeURIComponent(gid);
              if (tg && tg.initData) u += '&init_data=' + encodeURIComponent(tg.initData);
              window.location.href = u;
            }
          };
          row.onkeydown = function(e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); }
          };
        });
        content.querySelectorAll('.slot-group-hub').forEach(function(row) {
          row.onclick = function(e) {
            if (e.target.closest('.btn-slot-del')) return;
            var sid = row.getAttribute('data-slot-id');
            if (sid) openGroupSlotModal(parseInt(sid, 10));
          };
          row.onkeydown = function(e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); }
          };
        });
        content.querySelectorAll('.slot-booked-click').forEach(function(row) {
          row.onclick = function() {
            var bid = row.getAttribute('data-booking-id');
            if (bid) openBookingDetail(parseInt(bid, 10));
          };
          row.onkeydown = function(e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); }
          };
        });
        content.querySelectorAll('.slot-available:not(.slot-group-hub)').forEach(function(row) {
          row.onclick = function(e) { if (!e.target.closest('.btn-slot-del')) openBookModalForSlot(parseInt(row.dataset.slotId, 10)); };
          row.onkeydown = function(e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openBookModalForSlot(parseInt(row.dataset.slotId, 10)); } };
        });
        updatePastRevealChrome();
      }

      function clientsRequestUrl(q) {
        var path = '/trainer/clients';
        if (q && String(q).trim()) path += '?q=' + encodeURIComponent(String(q).trim());
        return apiUrlWithQuery(path);
      }
      function loadBookClients(q, autoSelectClientId) {
        fetch(clientsRequestUrl(q), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            var list = document.getElementById('bookClientList');
            var clients = data.clients || [];
            if (clients.length === 0) {
              list.innerHTML = '<p class="screen-hint" style="padding:8px 0;">Нет клиентов по поиску. Добавьте нового ниже.</p>';
              if (autoSelectClientId) {
                showToast('Клиент из ссылки не найден в списке.');
                state.deepLinkClientId = null;
              }
              setBookClientSearchSectionVisible(true);
              return;
            }
            if (autoSelectClientId) {
              var found = clients.filter(function(c) { return c.id === autoSelectClientId; })[0];
              if (found) {
                var autoName = ((found.first_name || '') + ' ' + (found.last_name || '')).trim() || 'Клиент';
                list.innerHTML = '';
                openBookConfirmForClient(found.id, autoName);
                return;
              }
              showToast('Клиент из ссылки не найден в списке.');
              state.deepLinkClientId = null;
              setBookClientSearchSectionVisible(true);
            }
            var html = '';
            clients.forEach(function(c) {
              var name = ((c.first_name || '') + ' ' + (c.last_name || '')).trim() || 'Клиент';
              var phone = (c.phone || '').trim();
              var noBot = !c.telegram_id;
              html += '<button type="button" class="client-row" data-client-id="' + c.id + '" data-client-name="' + escapeHtml(name).replace(/"/g, '&quot;') + '">' + escapeHtml(name) + (phone ? '<br><span class="phone">' + escapeHtml(phone) + '</span>' : '') + (noBot ? '<br><span class="client-no-bot">Без бота</span>' : '') + '</button>';
            });
            list.innerHTML = html;
            list.querySelectorAll('.client-row').forEach(function(row) {
              row.onclick = function() {
                var clientId = parseInt(row.dataset.clientId, 10);
                var clientName = (row.dataset.clientName || 'Клиент').replace(/&quot;/g, '"');
                openBookConfirmForClient(clientId, clientName);
              };
            });
          })
          .catch(function() {
            document.getElementById('bookClientList').innerHTML = '<p class="error">Ошибка загрузки</p>';
            setBookClientSearchSectionVisible(true);
          });
      }
      function doConfirmBookClient() {
        var clientId = state.pendingBookClientId;
        if (clientId == null || (!state.bookSlotId && !state.bookFlowQuick)) return;
        var serviceId = state.bookServiceId != null ? state.bookServiceId : (state.bookServices.length ? state.bookServices[0].id : null);
        if (serviceId == null) {
          alert('Выберите услугу. Если услуг нет — добавьте услугу в профиле.');
          return;
        }
        document.getElementById('modalBookConfirm').style.display = 'none';
        updateTelegramBack();
        state.pendingBookClientId = null;
        state.pendingBookClientName = null;
        var url = state.bookFlowQuick ? '/trainer/booking/quick' : '/trainer/booking';
        var payload = state.bookFlowQuick ? trainerQuickBookingPayload(clientId, serviceId) : trainerBookingPayload(clientId, serviceId);
        var wasQuick = state.bookFlowQuick;
        fetch(apiUrlWithQuery(url), {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify(payload),
        })
          .then(function(r) {
            if (r.ok) {
              return r.json().then(function(data) {
                applyTrainerBookingCreateSuccess(data, wasQuick ? 'Запись создана' : null);
              });
            }
            return r.json().then(function(o) {
              var d = o.detail;
              var msg = Array.isArray(d) ? (d[0] && d[0].msg) || 'Ошибка' : (d || 'Ошибка');
              throw new Error(typeof msg === 'string' ? msg : 'Ошибка');
            });
          })
          .catch(function(e) { alert(e.message || 'Ошибка сети'); });
      }
      document.getElementById('modalBookConfirmNo').onclick = function() {
        document.getElementById('modalBookConfirm').style.display = 'none';
        state.pendingBookClientId = null;
        state.pendingBookClientName = null;
        if (state.quickBookProfileAwaitingConfirm) {
          state.quickBookProfileAwaitingConfirm = false;
          setQuickBookProfileServiceLoading(false);
          var ms = document.getElementById('modalQuickBookService');
          if (ms) {
            ms.style.display = 'flex';
            ms.setAttribute('aria-hidden', 'false');
          }
          updateTelegramBack();
          return;
        }
        if (state.scheduleEditorEmbed && state.bookFlowQuick) {
          notifyTrainerClientsEmbed({ type: 'quickbook_dismiss' });
          updateTelegramBack();
          return;
        }
        setBookClientSearchSectionVisible(true);
        var list = document.getElementById('bookClientList');
        if (list && !list.querySelector('.client-row')) {
          loadBookClients('');
        }
        updateTelegramBack();
      };
      document.getElementById('modalBookConfirmYes').onclick = doConfirmBookClient;

      document.getElementById('modalBookCancel').onclick = function() {
        document.getElementById('modalBookClient').style.display = 'none';
        clearBookSlotModalState();
        state.bookModalStep = 'choice';
        updateTelegramBack();
      };

      function runQuickBookContinue(sd, startMinutes, dm, mq) {
        var hourSel = document.getElementById('quickBookHourSelect');
        var opt = hourSel && hourSel.options[hourSel.selectedIndex];
        if (opt && opt.disabled) {
          showToast('Выберите свободное время');
          return;
        }
        var btn = document.getElementById('btnQuickBookContinue');
        function finishBtn() {
          if (btn) btn.disabled = false;
          setQuickBookDatetimeLoading(false);
        }
        if (btn) btn.disabled = true;
        setQuickBookDatetimeLoading(true);
        fetch(
          apiUrlWithQuery('/schedule?from_date=' + encodeURIComponent(sd) + '&to_date=' + encodeURIComponent(sd)),
          { headers: headers() }
        )
          .then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('schedule'));
          })
          .then(function(data) {
            var slots = (data && data.slots) ? data.slots : [];
            var slotsForDay = slots.filter(function(s) {
              var d = s.slot_date;
              return d === sd || String(d) === sd;
            });
            var av = quickBookSlotAvailability(slotsForDay, startMinutes, dm, sd);
            if (av === 'past') {
              showToast('Это время уже прошло');
              refreshQuickBookHourOptions(sd).finally(finishBtn);
              return;
            }
            if (av === 'busy') {
              showToast('Это время уже занято. Выберите другое время.');
              refreshQuickBookHourOptions(sd).finally(finishBtn);
              return;
            }
            if (av === 'group') {
              showToast('На это время есть групповой слот — откройте расписание.');
              finishBtn();
              return;
            }
            if (av === 'overlap') {
              showToast('Пересекается с другим слотом — смените время или длительность.');
              refreshQuickBookHourOptions(sd).finally(finishBtn);
              return;
            }
            if (av === 'invalid') {
              showToast('Слишком длинно для выбранного начала.');
              refreshQuickBookHourOptions(sd).finally(finishBtn);
              return;
            }
            state.quickBookSlotDate = sd;
            state.quickBookStartMinutes = startMinutes;
            state.quickBookDurationMinutes = dm;
            setQuickBookHourHint('', false);
            if (state.deepLinkClientId) {
              openQuickBookProfileServiceStep(mq, finishBtn);
            } else {
              if (mq) {
                mq.style.display = 'none';
                mq.setAttribute('aria-hidden', 'true');
              }
              openBookModalForQuickFlow();
              finishBtn();
            }
          })
          .catch(function() {
            showToast('Не удалось проверить время. Повторите попытку.');
            finishBtn();
          });
      }

      (function wireQuickBookDatetimeModal() {
        var mq = document.getElementById('modalQuickBookDatetime');
        var inpDate = document.getElementById('quickBookDateInput');
        if (inpDate) {
          inpDate.addEventListener('change', function() {
            var v = (inpDate.value || '').trim();
            if (!v) return;
            if (inpDate.min && v < inpDate.min) return;
            scheduleQuickBookHourRefresh();
          });
        }
        var durQuick = document.getElementById('quickBookDurationSelect');
        if (durQuick) {
          durQuick.addEventListener('change', function() {
            state.quickBookDurationMinutes = parseInt(durQuick.value, 10) || 45;
            var v = inpDate && (inpDate.value || '').trim();
            if (v) refreshQuickBookHourOptions(v);
          });
        }
        var btnCont = document.getElementById('btnQuickBookContinue');
        var btnCancel = document.getElementById('btnQuickBookCancel');
        if (btnCont) {
          btnCont.onclick = function() {
            var inp = document.getElementById('quickBookDateInput');
            var hourSel = document.getElementById('quickBookHourSelect');
            var dur = document.getElementById('quickBookDurationSelect');
            if (!inp || !hourSel) return;
            var sd = (inp.value || '').trim();
            if (!sd) {
              showToast('Выберите дату');
              return;
            }
            if (inp.min && sd < inp.min) {
              showToast('Дата не может быть в прошлом');
              return;
            }
            var startM = parseInt(hourSel.value, 10);
            if (isNaN(startM)) {
              showToast('Выберите время');
              return;
            }
            var dm = dur ? parseInt(dur.value, 10) : 45;
            if (isNaN(dm) || dm < 15) dm = 45;
            runQuickBookContinue(sd, startM, dm, mq);
          };
        }
        if (btnCancel) {
          btnCancel.onclick = function() {
            setQuickBookDatetimeLoading(false);
            if (mq) {
              mq.style.display = 'none';
              mq.setAttribute('aria-hidden', 'true');
            }
            state.pendingBookFlowFromHub = false;
            state.rescheduleSourceBookingId = null;
            state.quickBookLockedClientId = null;
            state.quickBookProfileServiceStep = false;
            if (state.scheduleEditorEmbed) {
              notifyTrainerClientsEmbed({ type: 'quickbook_dismiss' });
            }
            updateTelegramBack();
          };
        }
      })();

      (function wireQuickBookProfileServiceModal() {
        var btnGo = document.getElementById('btnQuickBookProfileContinue');
        var btnBack = document.getElementById('btnQuickBookProfileBack');
        if (btnGo) {
          btnGo.onclick = function() {
            var sel = document.getElementById('quickBookProfileServiceSelect');
            state.bookServiceId = sel && sel.value ? parseInt(sel.value, 10) : null;
            if (state.bookServiceId == null) {
              showToast('Выберите услугу');
              return;
            }
            var cid = state.quickBookLockedClientId;
            if (!cid) {
              showToast('Клиент не выбран');
              return;
            }
            var name = state.quickBookProfileClientName || 'Клиент';
            var ms = document.getElementById('modalQuickBookService');
            if (ms) {
              ms.style.display = 'none';
              ms.setAttribute('aria-hidden', 'true');
            }
            state.quickBookProfileAwaitingConfirm = true;
            openBookConfirmForClient(cid, name);
          };
        }
        if (btnBack) {
          btnBack.onclick = function() {
            setQuickBookProfileServiceLoading(false);
            var ms = document.getElementById('modalQuickBookService');
            if (ms) {
              ms.style.display = 'none';
              ms.setAttribute('aria-hidden', 'true');
            }
            state.quickBookProfileServiceStep = false;
            state.bookFlowQuick = false;
            state.quickBookLockedClientId = null;
            var mq = document.getElementById('modalQuickBookDatetime');
            if (mq) {
              mq.style.display = 'flex';
              mq.setAttribute('aria-hidden', 'false');
            }
            updateTelegramBack();
          };
        }
      })();

      document.getElementById('bookOptExisting').onclick = function() {
        if (!state.trainerHasBookClients) return;
        document.getElementById('bookStepChoice').classList.remove('active');
        document.getElementById('bookStepChoice').style.display = 'none';
        document.getElementById('bookStepExisting').style.display = 'block';
        document.getElementById('bookStepExisting').classList.add('active');
        setBookClientSearchSectionVisible(true);
        var sel = document.getElementById('bookServiceSelect');
        if (sel && state.bookServiceId != null) sel.value = String(state.bookServiceId);
        document.getElementById('bookClientList').innerHTML = buildBookClientListSkeletonHtml();
        loadBookClients();
      };
      document.getElementById('bookOptNew').onclick = function() {
        document.getElementById('bookStepChoice').classList.remove('active');
        document.getElementById('bookStepChoice').style.display = 'none';
        document.getElementById('bookStepNew').style.display = 'block';
        document.getElementById('bookStepNew').classList.add('active');
        var sel = document.getElementById('bookServiceSelectNew');
        if (sel && state.bookServiceId != null) sel.value = String(state.bookServiceId);
      };
      document.getElementById('bookBackFromExisting').onclick = function() {
        document.getElementById('bookStepExisting').style.display = 'none';
        document.getElementById('bookStepExisting').classList.remove('active');
        document.getElementById('bookStepChoice').style.display = 'block';
        document.getElementById('bookStepChoice').classList.add('active');
      };
      document.getElementById('bookBackFromNew').onclick = function() {
        document.getElementById('bookStepNew').style.display = 'none';
        document.getElementById('bookStepNew').classList.remove('active');
        document.getElementById('bookStepChoice').style.display = 'block';
        document.getElementById('bookStepChoice').classList.add('active');
      };
      // Tap overlay to close keyboard (don't close modal)
      document.querySelectorAll('.modal-overlay').forEach(function(overlay) {
        overlay.addEventListener('click', function(e) {
          if (e.target !== overlay) return;
          var el = document.activeElement;
          if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) {
            el.blur();
          }
        });
      });
      // screenEdit (групповые слоты, «Мест в слоте» и т.д.): тап вне полей — blur в Mini App WebView
      (function bindScreenEditBlurOnOutsidePointer() {
        var screen = document.getElementById('screenEdit');
        if (!screen) return;
        screen.addEventListener(
          'pointerdown',
          function (e) {
            var t = e.target;
            if (t && t.nodeType === 3) t = t.parentElement;
            if (!t || t.nodeType !== 1) return;
            var tag = (t.tagName || '').toUpperCase();
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            if (t.closest && t.closest('button')) return;
            if (t.closest && t.closest('a')) return;
            if (t.closest && t.closest('textarea, input, select')) return;
            var ae = document.activeElement;
            if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT')) {
              ae.blur();
            }
          },
          false
        );
      })();
      var bookSearchEl = document.getElementById('bookClientSearch');
      var bookSearchTimer = null;
      bookSearchEl.oninput = function() {
        var q = bookSearchEl.value.trim();
        if (bookSearchTimer) clearTimeout(bookSearchTimer);
        bookSearchTimer = setTimeout(function() { loadBookClients(q); }, 300);
      };
      bookSearchEl.onkeydown = function(e) {
        if (e.key === 'Enter') { e.preventDefault(); loadBookClients(bookSearchEl.value.trim()); }
      };

      document.getElementById('bookNewSubmit').onclick = function() {
        var phoneEl = document.getElementById('bookNewPhone');
        var firstEl = document.getElementById('bookNewFirstName');
        var lastEl = document.getElementById('bookNewLastName');
        var phoneRaw = (phoneEl.value || '').trim();
        var first = (firstEl.value || '').trim() || null;
        var last = (lastEl.value || '').trim() || null;
        if (!/[\d]/.test(phoneRaw)) {
          showToast('Введите номер телефона (цифры).');
          phoneEl.focus();
          return;
        }
        var phone = phoneRaw;
        if (phone.indexOf(' ') >= 0 && !first && !last) {
          var parts = phone.split(/\s+/);
          var digitParts = [];
          var nameParts = [];
          parts.forEach(function(p) {
            if (/^[\d+\-()]+$/.test(p)) digitParts.push(p);
            else nameParts.push(p);
          });
          if (nameParts.length) {
            first = nameParts[0] || null;
            last = nameParts.slice(1).join(' ') || null;
          }
          if (digitParts.length) phone = digitParts.join('').replace(/\D/g, function(c) { return c === '+' ? '+' : ''; });
        }
        phone = normalizePhoneClient((phone || '').trim());
        var phoneErr = validatePhoneMessage(phone);
        if (phoneErr) {
          showToast(phoneErr);
          phoneEl.focus();
          return;
        }
        first = (first || '').trim();
        last = (last || '').trim();
        if (!first) {
          showToast('Укажите имя клиента.');
          firstEl.focus();
          return;
        }
        if (!state.bookSlotId && !state.bookFlowQuick) return;
        var btn = document.getElementById('bookNewSubmit');
        btn.disabled = true;
        fetch(apiUrlWithQuery('/trainer/clients'), {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({ phone: phone, first_name: first, last_name: last }),
        })
          .then(function(r) {
            if (!r.ok) return r.json().then(function(o) { throw new Error(o.detail || 'Ошибка'); });
            return r.json();
          })
          .then(function(data) {
            var clientId = data.client_id;
            var serviceId = state.bookServiceId != null ? state.bookServiceId : (state.bookServices.length ? state.bookServices[0].id : null);
            if (serviceId == null) throw new Error('Выберите услугу. Добавьте услугу в профиле, если списка нет.');
            var url = state.bookFlowQuick ? '/trainer/booking/quick' : '/trainer/booking';
            var payload = state.bookFlowQuick ? trainerQuickBookingPayload(clientId, serviceId) : trainerBookingPayload(clientId, serviceId);
            return fetch(apiUrlWithQuery(url), {
              method: 'POST',
              headers: headers(),
              body: JSON.stringify(payload),
            });
          })
          .then(function(r) {
            if (r.ok) {
              return r.json().then(function(data) {
                applyTrainerBookingCreateSuccess(data, 'Клиент добавлен и записан на занятие.');
              });
            }
            return r.json().then(function(o) {
              var d = o.detail;
              var msg = Array.isArray(d) ? (d[0] && d[0].msg) || 'Ошибка' : (d || 'Ошибка');
              throw new Error(typeof msg === 'string' ? msg : 'Ошибка');
            });
          })
          .catch(function(e) {
            alert(e.message || 'Ошибка сети');
          })
          .finally(function() { btn.disabled = false; });
      };

      function renderTemplate() {
        const byDay = {};
        state.templates.forEach(function(t) {
          const d = t.day_of_week;
          if (!byDay[d]) byDay[d] = [];
          const cap = (t.capacity != null) ? parseInt(t.capacity, 10) : 1;
          const timeShort = (t.start_time || '').toString().substring(0, 5);
          const label = (cap > 1) ? (timeShort + ' ×' + cap) : timeShort;
          byDay[d].push(label);
        });
        let html = '';
        for (let d = 0; d < 7; d++) {
          const times = (byDay[d] || []).sort(function(a, b) { return String(a).localeCompare(String(b)); });
          const text = times.length ? times.join(', ') : 'Нет слотов';
          html += '<button type="button" class="template-day-card" data-day="' + d + '">';
          html += '<span class="day-name">' + DAYS[d] + '</span>';
          html += '<span class="day-slots ' + (times.length ? '' : 'empty') + '">' + escapeHtml(text) + '</span>';
          html += '<span class="arrow">→</span></button>';
        }
        document.getElementById('templateList').innerHTML = html;
        document.querySelectorAll('#templateList .template-day-card').forEach(function(btn) {
          btn.onclick = function() {
            const day = parseInt(btn.dataset.day, 10);
            if (isGroupClassesFeatureEnabled()) {
              var existing = (state.templates || []).filter(function(t) { return t.day_of_week === day; });
              openSlotIntentModal('template', day, detectSlotIntentFromRows(existing));
              return;
            }
            state.slotEditIntent = 'individual';
            openEditTemplateDay(day);
          };
        });
      }

      function openEditTemplateDay(day) {
        state.editMode = 'template';
        state.editDay = day;
        state.editDate = null;
        state.lockedStarts = new Set();
        state.calendarBaselineStarts = null;
        const existing = (state.templates || []).filter(function(t) { return t.day_of_week === day; });
        if (!isGroupClassesFeatureEnabled()) {
          state.slotEditIntent = 'individual';
        } else if (state.slotEditIntent !== 'group' && state.slotEditIntent !== 'individual') {
          state.slotEditIntent = detectSlotIntentFromRows(existing);
        }
        var allowedTemplateStarts = new Set(
          allowedStartMinutesFromScheduleGridPreset(state.scheduleGridPreset || defaultScheduleGridPreset())
        );
        state.selectedStarts = new Set(
          existing
            .map(function(t) { return parseStartToMinutes(t.start_time); })
            .filter(function(m) { return allowedTemplateStarts.has(m); })
        );
        var durTpl = document.getElementById('slotDurationSelect');
        if (durTpl) {
          var dms = existing.map(function(t) { return parseInt(t.duration_minutes, 10); }).filter(function(x) { return !isNaN(x); });
          var fallbackDur = state.defaultSlotDurationMinutes || 45;
          var dval = dms.length && dms.every(function(x) { return x === dms[0]; }) ? dms[0] : fallbackDur;
          durTpl.value = String(normalizeDurationToScheduleSelect(Math.min(480, Math.max(15, dval))));
        }
        syncDurationUIFromScheduleGrid();
        var cgw = document.getElementById('calendarGroupServiceWrap');
        var cawCal = document.getElementById('calendarGroupArenaWrap');
        var tgar = document.getElementById('templateGroupArenaWrap');
        if (cgw) cgw.style.display = 'none';
        if (cawCal) cawCal.style.display = 'none';
        document.querySelector('.tabs').style.display = 'none';
        document.getElementById('tabCalendar').style.display = 'none';
        document.getElementById('tabTemplate').style.display = 'none';
        document.getElementById('editTitle').textContent = DAYS[day] + ': время в шаблоне';
        var useTplGroup = slotIntentUseGroupUi();
        document.getElementById('editHint').textContent = useTplGroup
          ? 'Групповые слоты: места, услуга и площадка задаются один раз — для всех отмеченных начал.'
          : scheduleGridFixedDurationMinutes() != null
            ? 'Индивидуальные слоты. ' + scheduleGridHintSuffix() + ' — «Готово» сохранит шаблон на этот день.'
            : 'Индивидуальные слоты. ' + scheduleGridHintSuffix() + ' и длительность — «Готово» сохранит шаблон на этот день.';
        var capWrap = document.getElementById('slotCapacityWrap');
        if (capWrap) capWrap.style.display = 'none';
        var tdef = document.getElementById('templateDefaultCapacityInput');
        if (tdef) {
          tdef.setAttribute('min', useTplGroup ? '2' : '1');
          if (!useTplGroup) tdef.value = '1';
          else if (!existing.length) tdef.value = '2';
        }
        var trow = document.getElementById('templateDefaultCapRow');
        if (trow) {
          var narrow = !!(window.matchMedia && window.matchMedia('(max-width: 380px)').matches);
          trow.style.gridTemplateColumns = (useTplGroup && !narrow) ? 'repeat(2, minmax(0, 1fr))' : 'minmax(0, 1fr)';
        }
        var tdsr = document.getElementById('templateDefaultServiceRow');
        if (tdsr) tdsr.style.display = useTplGroup ? 'block' : 'none';
        var tpan = document.getElementById('templateCapacityPanel');
        if (tpan) tpan.style.display = useTplGroup ? 'block' : 'none';
        if (tgar) tgar.style.display = 'none';
        document.getElementById('screenEdit').style.display = 'block';
        if (useTplGroup) {
          loadTrainerServicesIfNeeded().then(function() {
            applyTemplateGroupPrefillFromExisting(existing, true);
            fillTemplateGroupArenaSelect();
            var ars = state.trainerScheduleArenas || [];
            if (tgar) {
              if (ars.length > 1) {
                tgar.style.display = 'block';
                var gArena = null;
                existing.forEach(function(t) {
                  var c = (t.capacity != null) ? parseInt(t.capacity, 10) : 1;
                  if (c > 1 && t.arena_id != null && !isNaN(parseInt(t.arena_id, 10))) gArena = parseInt(t.arena_id, 10);
                });
                var asel = document.getElementById('templateGroupArenaSelect');
                if (asel) {
                  if (gArena != null && !isNaN(gArena)) asel.value = String(gArena);
                  else if (ars.length) {
                    var prim = ars.filter(function(x) { return x.is_primary; })[0];
                    asel.value = String((prim || ars[0]).id);
                  }
                }
              } else {
                tgar.style.display = 'none';
              }
            }
            pruneSelectedStartsForOverlap(getEditDurationMinutes());
            renderHourGrid();
          });
        } else {
          pruneSelectedStartsForOverlap(getEditDurationMinutes());
          renderHourGrid();
        }
        updateTelegramBack();
      }

      function openEditCalendarDay(slotDate) {
        state.editMode = 'calendar';
        state.editDay = null;
        state.editDate = slotDate;
        // Group-generated slots belong to the Groups flow and must not affect manual day editing.
        const daySlots = (state.slots || []).filter(function(s) {
          return s.slot_date === slotDate && !s.training_group_id;
        });
        if (!isGroupClassesFeatureEnabled()) {
          state.slotEditIntent = 'individual';
        } else if (state.slotEditIntent !== 'group' && state.slotEditIntent !== 'individual') {
          state.slotEditIntent = detectSlotIntentFromRows(daySlots);
        }
        var allowedCalendarStarts = new Set(
          allowedStartMinutesFromScheduleGridPreset(state.scheduleGridPreset || defaultScheduleGridPreset())
        );
        state.selectedStarts = new Set();
        state.lockedStarts = new Set();
        daySlots.forEach(function(s) {
          var m = parseStartToMinutes(s.start_time);
          if (!allowedCalendarStarts.has(m)) return;
          state.selectedStarts.add(m);
          var occ = (s.active_bookings != null) ? parseInt(s.active_bookings, 10) : 0;
          if ((s.status || '') === 'booked' || occ > 0) state.lockedStarts.add(m);
        });
        state.calendarBaselineStarts = new Set(state.selectedStarts);
        var durElCal = document.getElementById('slotDurationSelect');
        if (durElCal && daySlots.length) {
          var durs = daySlots.map(slotDurationFromRow);
          var dcal = durs.length && durs.every(function(x) { return x === durs[0]; }) ? durs[0] : 45;
          durElCal.value = String(Math.min(480, Math.max(15, dcal)));
        } else if (durElCal) {
          durElCal.value = String(normalizeDurationToScheduleSelect(state.defaultSlotDurationMinutes || 45));
        }
        syncDurationUIFromScheduleGrid();
        document.querySelector('.tabs').style.display = 'none';
        document.getElementById('tabCalendar').style.display = 'none';
        document.getElementById('tabTemplate').style.display = 'none';
        document.getElementById('editTitle').textContent = 'Слоты на ' + formatDateKey(slotDate);
        var useCalGroup = slotIntentUseGroupUi();
        document.getElementById('editHint').textContent = useCalGroup
          ? 'Групповые слоты: «Мест в слоте» и услуга — для новых начал. Уже открытые слоты снять нельзя. «Готово» — после выбора хотя бы одного нового времени.'
          : 'Индивидуальные слоты. Уже открытые и занятые слоты снять нельзя. «Готово» — после выбора хотя бы одного нового времени.';
        var capWrap = document.getElementById('slotCapacityWrap');
        var capInput = document.getElementById('slotCapacityInput');
        if (capInput) capInput.setAttribute('min', useCalGroup ? '2' : '1');
        if (capWrap) {
          if (useCalGroup) {
            capWrap.style.display = 'block';
            var caps = daySlots.map(function(s) { return (s.capacity != null) ? parseInt(s.capacity, 10) : 1; });
            var capVal = 2;
            if (caps.length && caps.every(function(c) { return c === caps[0]; })) capVal = caps[0];
            if (capVal < 2) capVal = 2;
            if (capInput) capInput.value = String(Math.min(500, Math.max(2, capVal)));
          } else {
            capWrap.style.display = 'none';
            if (capInput) capInput.value = '1';
          }
        }
        var tpan = document.getElementById('templateCapacityPanel');
        if (tpan) tpan.style.display = 'none';
        var tdsr = document.getElementById('templateDefaultServiceRow');
        if (tdsr) tdsr.style.display = 'none';
        var tgar = document.getElementById('templateGroupArenaWrap');
        if (tgar) tgar.style.display = 'none';
        var cgw = document.getElementById('calendarGroupServiceWrap');
        var caw = document.getElementById('calendarGroupArenaWrap');
        if (cgw) {
          if (useCalGroup) {
            cgw.style.display = 'block';
            loadTrainerServicesIfNeeded().then(function() {
              var sel = document.getElementById('calendarGroupServiceSelect');
              var gs = null;
              var gArena = null;
              daySlots.forEach(function(s) {
                var c = (s.capacity != null) ? parseInt(s.capacity, 10) : 1;
                if (c > 1 && s.service_id != null) gs = parseInt(s.service_id, 10);
                if (c > 1 && s.arena_id != null && !isNaN(parseInt(s.arena_id, 10))) gArena = parseInt(s.arena_id, 10);
              });
              if (sel && gs != null && !isNaN(gs)) sel.value = String(gs);
              var ars = state.trainerScheduleArenas || [];
              if (caw) {
                if (ars.length > 1) {
                  caw.style.display = 'block';
                  var asel = document.getElementById('calendarGroupArenaSelect');
                  if (asel) {
                    asel.innerHTML = '';
                    ars.forEach(function(a) {
                      var o = document.createElement('option');
                      o.value = String(a.id);
                      o.textContent = (a.name || '—') + (a.is_primary ? ' · основная' : '');
                      asel.appendChild(o);
                    });
                    if (gArena != null && !isNaN(gArena)) asel.value = String(gArena);
                    else if (ars.length) {
                      var prim = ars.filter(function(x) { return x.is_primary; })[0];
                      asel.value = String((prim || ars[0]).id);
                    }
                  }
                } else {
                  caw.style.display = 'none';
                }
              }
            });
          } else {
            cgw.style.display = 'none';
            if (caw) caw.style.display = 'none';
          }
        }
        document.getElementById('screenEdit').style.display = 'block';
        pruneSelectedStartsForOverlap(getEditDurationMinutes());
        renderHourGrid();
        updateTelegramBack();
      }

      function renderHourGrid() {
        const grid = document.getElementById('hourGrid');
        if (!grid) return;
        const durationMinutes = getEditDurationMinutes();
        const preset = state.scheduleGridPreset || defaultScheduleGridPreset();
        var h0 = Math.max(0, Math.min(23, parseInt(preset.hour_start, 10)));
        if (isNaN(h0)) h0 = 8;
        var h1 = Math.max(0, Math.min(23, parseInt(preset.hour_end, 10)));
        if (isNaN(h1)) h1 = 21;
        if (h1 < h0) {
          var hx = h0;
          h0 = h1;
          h1 = hx;
        }
        const list = allowedStartMinutesFromScheduleGridPreset(preset);
        let html = '';
        for (let h = h0; h <= h1; h++) {
          const chips = list.filter(function(m) {
            return Math.floor(m / 60) === h;
          });
          if (!chips.length) continue;
          html += '<div class="schedule-hour-row" role="row">';
          html +=
            '<div class="schedule-hour-row__rail" aria-hidden="true"><span class="schedule-hour-row__label">' +
            String(h).padStart(2, '0') +
            '</span></div>';
          html += '<div class="schedule-hour-row__chips" role="group">';
          for (let ci = 0; ci < chips.length; ci++) {
            const m = chips[ci];
            const selected = state.selectedStarts.has(m);
            const locked = state.lockedStarts.has(m);
            const pinned =
              state.editMode === 'calendar' &&
              state.calendarBaselineStarts &&
              state.calendarBaselineStarts.has(m) &&
              selected &&
              !locked;
            const blockedByOverlap =
              !selected && isStartMinuteBlockedByOthers(m, durationMinutes, state.selectedStarts);
            const labelFull = formatMinuteClock(m);
            const labelShort = ':' + String(m % 60).padStart(2, '0');
            var btnAttrs = ' aria-label="' + escapeHtml(labelFull) + '"';
            if (blockedByOverlap) {
              btnAttrs +=
                ' disabled title="Пересекается с уже выбранным слотом при этой длительности"';
            } else if (locked) {
              btnAttrs += ' disabled title="Есть записи — убрать нельзя"';
            } else if (pinned) {
              btnAttrs += ' title="Уже в расписании — убрать нельзя"';
            }
            html +=
              '<button type="button" class="hour-chip' +
              (selected ? ' selected' : '') +
              (locked ? ' locked' : '') +
              (pinned ? ' pinned' : '') +
              (blockedByOverlap ? ' duration-blocked' : '') +
              '" data-minute="' +
              m +
              '"' +
              btnAttrs +
              '>' +
              labelShort +
              '</button>';
          }
          html += '</div></div>';
        }
        grid.innerHTML = html;
        grid.querySelectorAll('.hour-chip:not(.locked):not(.pinned):not(.duration-blocked)').forEach(function(btn) {
          btn.onclick = function() {
            const m = parseInt(btn.dataset.minute, 10);
            if (state.selectedStarts.has(m)) state.selectedStarts.delete(m);
            else state.selectedStarts.add(m);
            renderHourGrid();
          };
        });
        if (!(state.editMode === 'template' && slotIntentUseGroupUi())) {
          var tpanHide = document.getElementById('templateCapacityPanel');
          if (tpanHide) tpanHide.style.display = 'none';
        }
        updateEditDoneButton();
      }

      (function wireSlotDurationOverlap() {
        var sel = document.getElementById('slotDurationSelect');
        if (!sel) return;
        sel.addEventListener('change', function() {
          var d = getEditDurationMinutes();
          pruneSelectedStartsForOverlap(d);
          renderHourGrid();
        });
      })();

      document.getElementById('editDone').onclick = function() {
        if (state.editMode === 'calendar' && state.calendarBaselineStarts && !hasCalendarNewSlotSelection()) {
          return;
        }
        var durationMinutes = getEditDurationMinutes();
        const startsSorted = Array.from(state.selectedStarts).sort(function(a, b) { return a - b; });
        if (state.editMode === 'template') {
          var slotsPayload;
          var templateBody;
          if (slotIntentUseGroupUi()) {
            var capRaw = parseInt(document.getElementById('templateDefaultCapacityInput').value, 10);
            var c = (isNaN(capRaw) || capRaw < 2) ? 2 : Math.min(500, capRaw);
            var gid = parseInt(document.getElementById('templateDefaultServiceSelect').value, 10);
            if (isNaN(gid)) {
              alert('Выберите услугу для групповых слотов в шаблоне.');
              return;
            }
            var ars = state.trainerScheduleArenas || [];
            if (!ars.length) {
              alert('Добавьте хотя бы одну площадку в профиле, чтобы задавать групповые слоты в шаблоне.');
              return;
            }
            var groupArenaPayload = null;
            if (ars.length > 1) {
              var tas = document.getElementById('templateGroupArenaSelect');
              var aid = tas ? parseInt(tas.value, 10) : NaN;
              if (isNaN(aid)) {
                alert('Выберите площадку для групповых слотов в шаблоне.');
                return;
              }
              groupArenaPayload = aid;
            }
            slotsPayload = startsSorted.map(function(m0) {
              return { hour: Math.floor(m0 / 60), minute: m0 % 60, capacity: c, service_id: gid };
            });
            templateBody = {
              day_of_week: state.editDay,
              slots: slotsPayload,
              duration_minutes: durationMinutes,
              group_arena_id: groupArenaPayload,
            };
          } else {
            slotsPayload = startsSorted.map(function(m0) {
              return { hour: Math.floor(m0 / 60), minute: m0 % 60, capacity: 1 };
            });
            templateBody = {
              day_of_week: state.editDay,
              slots: slotsPayload,
              duration_minutes: durationMinutes,
              group_arena_id: null,
            };
          }
          fetch(apiUrlWithQuery('/schedule/templates/day'), {
            method: 'PUT',
            headers: headers(),
            body: JSON.stringify(templateBody),
          })
            .then(function(r) {
              if (r.ok) {
                showToast('Шаблон сохранён');
                showMain();
              } else {
                r.json().then(function(o) {
                  var d = o.detail || 'Ошибка';
                  showToast(typeof d === 'string' ? d : 'Ошибка сохранения');
                });
              }
            })
            .catch(function() { showToast('Ошибка сети'); });
        } else {
          var capRaw = parseInt(document.getElementById('slotCapacityInput').value, 10);
          var capacity = (isNaN(capRaw) || capRaw < 1) ? 1 : Math.min(500, capRaw);
          if (slotIntentUseGroupUi()) {
            if (capacity < 2) capacity = 2;
          } else {
            capacity = 1;
          }
          var postBody = {
            slot_date: state.editDate,
            start_times: startsSorted.map(function(m0) { return formatMinuteClock(m0); }),
            duration_minutes: durationMinutes,
            capacity: capacity,
          };
          if (slotIntentUseGroupUi() && capacity > 1) {
            var gsel = document.getElementById('calendarGroupServiceSelect');
            var gid = gsel ? parseInt(gsel.value, 10) : NaN;
            if (isNaN(gid)) {
              alert('Выберите услугу для групповых слотов.');
              return;
            }
            postBody.group_service_id = gid;
            var ars = state.trainerScheduleArenas || [];
            if (!ars.length) {
              alert('Добавьте хотя бы одну площадку в профиле, чтобы создавать групповые слоты.');
              return;
            }
            if (ars.length === 1) {
              postBody.arena_id = ars[0].id;
            } else {
              var asel = document.getElementById('calendarGroupArenaSelect');
              var aid = asel ? parseInt(asel.value, 10) : NaN;
              if (isNaN(aid)) {
                alert('Выберите площадку для групповых слотов.');
                return;
              }
              postBody.arena_id = aid;
            }
          }
          fetch(apiUrlWithQuery('/schedule/slots'), {
            method: 'POST',
            headers: headers(),
            body: JSON.stringify(postBody),
          })
            .then(function(r) {
              if (r.ok) {
                // Only count starts added in this session (not slots that were already on the day).
                var nNew = 0;
                if (state.calendarBaselineStarts) {
                  startsSorted.forEach(function(m) {
                    if (!state.calendarBaselineStarts.has(m)) nNew++;
                  });
                } else {
                  nNew = startsSorted.length;
                }
                var msg =
                  nNew === 0
                    ? 'Расписание на день обновлено'
                    : nNew === 1
                      ? 'Добавлен новый слот'
                      : 'Добавлено новых слотов: ' + nNew;
                var todayStr = dateToStr(new Date());
                if (state.editDate && state.editDate < todayStr) {
                  // After saving on a past day, reveal past rows immediately so the new slot is visible.
                  state.showPastThisWeek = true;
                }
                showToast(msg);
                showMain();
              } else {
                r.json().then(function(o) {
                  var d = o.detail || 'Ошибка';
                  showToast(typeof d === 'string' ? d : 'Ошибка сохранения');
                });
              }
            })
            .catch(function() { showToast('Ошибка сети'); });
        }
      };

      document.getElementById('editCancel').onclick = function() {
        showMain();
      };

      document.getElementById('btnApplyThis').onclick = function() {
        if (!state.weekStart) return;
        state.applyWeekStart = dateToStr(state.weekStart);
        document.getElementById('modalConfirmTitle').textContent = 'Применить шаблон на эту неделю?';
        document.getElementById('modalConfirmText').textContent = 'Свободные слоты будут заменены шаблоном. Занятые не трогаем.';
        document.getElementById('modalConfirm').style.display = 'flex';
        updateTelegramBack();
      };

      document.getElementById('btnApplyNext').onclick = function() {
        if (!state.weekStart) return;
        const next = new Date(state.weekStart);
        next.setDate(next.getDate() + 7);
        state.applyWeekStart = dateToStr(next);
        document.getElementById('modalConfirmTitle').textContent = 'Применить шаблон на следующую неделю?';
        document.getElementById('modalConfirmText').textContent = 'Свободные слоты будут заменены шаблоном. Занятые не трогаем.';
        document.getElementById('modalConfirm').style.display = 'flex';
        updateTelegramBack();
      };

      document.getElementById('modalConfirmNo').onclick = function() {
        document.getElementById('modalConfirm').style.display = 'none';
        updateTelegramBack();
      };

      document.getElementById('groupSlotCloseBtn').onclick = function() {
        var mgr = document.getElementById('modalGroupSlot');
        if (mgr) {
          mgr.style.display = 'none';
          mgr.setAttribute('aria-hidden', 'true');
        }
        updateTelegramBack();
      };

      document.getElementById('modalConfirmYes').onclick = function() {
        if (!state.applyWeekStart) return;
        document.getElementById('modalConfirm').style.display = 'none';
        updateTelegramBack();
        fetch(apiUrlWithQuery('/schedule/apply-week'), {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({ week_start: state.applyWeekStart }),
        })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            if (data.ok) {
              const n = data.slots_created != null ? data.slots_created : 0;
              showToast('Шаблон применён. Создано слотов: ' + n, 2800);
              setTimeout(function() {
                showFirstApplyWeekShareToastIfNeeded(data.trainer_id);
              }, 2600);
              loadSlots();
            } else {
              var err = data.detail || 'Ошибка';
              showToast(typeof err === 'string' ? err : 'Не удалось применить шаблон');
            }
          })
          .catch(function() { showToast('Ошибка сети'); });
      };

      document.getElementById('btnAddSlots').onclick = function() {
        if (!state.weekStart) return;
        if (isGroupClassesFeatureEnabled()) {
          openSlotIntentModal('calendar', null, 'individual');
          return;
        }
        state.slotEditIntent = 'individual';
        showDayPickScreen();
      };

      document.getElementById('btnSlotIntentIndividual').onclick = function() {
        applySlotIntentChoice('individual');
      };
      document.getElementById('btnSlotIntentGroup').onclick = function() {
        applySlotIntentChoice('group');
      };
      document.getElementById('btnSlotIntentCancel').onclick = function() {
        cancelSlotIntentModal();
      };

      document.getElementById('weekPrev').onclick = function() {
        state.showPastThisWeek = false;
        state.weekStart.setDate(state.weekStart.getDate() - 7);
        loadSlots();
      };
      document.getElementById('weekNext').onclick = function() {
        state.showPastThisWeek = false;
        state.weekStart.setDate(state.weekStart.getDate() + 7);
        loadSlots();
      };

      document.getElementById('btnTogglePastThisWeek').onclick = function() {
        state.showPastThisWeek = !state.showPastThisWeek;
        renderCalendar();
      };

      state.weekStart = getMonday(new Date());

      (function () {
        var bb = document.getElementById('btnBack');
        if (bb) bb.onclick = handleTelegramBackUnified;
        function goTrainerHome() {
          navigateToTrainerHomeSafe();
        }
        var hbd = document.getElementById('btnHomeBookingDetail');
        var bbd = document.getElementById('btnBackBookingDetail');
        var hdecl = document.getElementById('btnHomeBookingDecline');
        var bdecl = document.getElementById('btnBackBookingDecline');
        if (hbd) hbd.onclick = goTrainerHome;
        if (bbd) bbd.onclick = handleTelegramBackUnified;
        if (hdecl) hdecl.onclick = goTrainerHome;
        if (bdecl) bdecl.onclick = handleTelegramBackUnified;
      })();

      function initFromUrl() {
        var p = new URLSearchParams(window.location.search || '');
        var cidRaw = p.get('client_id');
        var clientIdFromUrl = cidRaw ? parseInt(cidRaw, 10) : null;
        var ob = p.get('open_booking');
        var fromHub = (p.get('from') || '') === 'hub';
        var hubGroupSlotRaw = p.get('hub_group_slot');
        var flowBook = (p.get('flow') || '') === 'book';
        if (p.get('embed') === '1' && (flowBook || !!cidRaw)) {
          state.scheduleEditorEmbed = true;
        }
        var tabParam = (p.get('tab') || '').trim().toLowerCase();
        var openClientProblem = (p.get('open_client_problem') || '') === '1';
        var anchorDate = (p.get('anchor_date') || '').trim();
        var bgsRaw = p.get('book_group_slot');
        if (tabParam === 'template') {
          state.pendingOpenTemplateTab = true;
          try {
            history.replaceState({}, '', window.location.pathname);
          } catch (e) { /* ignore */ }
        }
        if (anchorDate && /^\d{4}-\d{2}-\d{2}$/.test(anchorDate)) {
          var ad = new Date(anchorDate + 'T12:00:00');
          if (!isNaN(ad.getTime())) {
            state.weekStart = getMonday(ad);
          }
        }
        if (bgsRaw) {
          var sidBg = parseInt(bgsRaw, 10);
          if (sidBg) state.pendingBookGroupSlotId = sidBg;
        }
        if (clientIdFromUrl || ob) {
          try { history.replaceState({}, '', window.location.pathname); } catch (e) {}
        } else if (flowBook || bgsRaw) {
          try { history.replaceState({}, '', window.location.pathname); } catch (e) {}
        }
        if (flowBook && !ob) {
          state.pendingBookFlowFromHub = true;
        }
        if (clientIdFromUrl) {
          state.deepLinkClientId = clientIdFromUrl;
        }
        if (ob) {
          state.pendingBookGroupSlotId = null;
          var bid = parseInt(ob, 10);
          if (bid) {
            if (openClientProblem) state.openClientProblemAfterDetail = true;
            if (fromHub && hubGroupSlotRaw) {
              var hg = parseInt(hubGroupSlotRaw, 10);
              if (!isNaN(hg) && hg > 0) {
                state.bookingDetailReturn = 'hub_group';
                state.hubGroupSlotReturnId = hg;
              } else {
                state.bookingDetailReturn = fromHub ? 'hub' : 'schedule';
                state.hubGroupSlotReturnId = null;
              }
            } else {
              state.bookingDetailReturn = fromHub ? 'hub' : 'schedule';
              state.hubGroupSlotReturnId = null;
            }
            openBookingDetail(bid);
            prefetchSlotsInBackground();
            return;
          }
        }
        function startScheduleLoads() {
          if (state.pendingOpenTemplateTab) {
            state.pendingOpenTemplateTab = false;
            setActiveTab('template');
            return;
          }
          loadSlots();
        }
        if (tg && tg.initData && window.TrainerMiniAppGate) {
          window.TrainerMiniAppGate.fetchAccess(tg.initData)
            .then(function (a) {
              if (a && !window.TrainerMiniAppGate.isActive(a)) {
                window.TrainerMiniAppGate.showBlockingOverlay(a);
                return;
              }
              startScheduleLoads();
            })
            .catch(function () {
              startScheduleLoads();
            });
        } else {
          startScheduleLoads();
        }
      }

      /** Telegram often fills initData later when Web App opens from reply keyboard (not inline); wait up to ~15s. */
      (function startWhenInitDataReady() {
        if (!tg) {
          initFromUrl();
          return;
        }
        if (tg.initData) {
          callReadyWhenInitDataReady();
          initFromUrl();
          return;
        }
        var n = 0;
        var iv = setInterval(function() {
          n++;
          if (tg.initData) {
            callReadyWhenInitDataReady();
            clearInterval(iv);
            initFromUrl();
            return;
          }
          if (n >= 300) {
            clearInterval(iv);
            initFromUrl();
          }
        }, 50);
      })();
    })();
