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

      /** See trainer-home-main.js — same production cache issue; self-contained polyfill. */
      (function ensureScheduleTelegramDmPolyfill() {
        if (typeof window.openTelegramChatFromMiniApp === 'function') return;
        window.openTelegramChatFromMiniApp = function (opts) {
          opts = opts || {};
          var un = String(opts.username || '').replace(/^@/, '').trim();
          var tid = opts.telegramId;
          var url;
          if (un) url = 'https://t.me/' + encodeURIComponent(un);
          else if (tid != null && tid !== '') url = 'tg://user?id=' + encodeURIComponent(String(tid));
          else return false;
          var w = window.Telegram && window.Telegram.WebApp;
          var isTgUser = url.indexOf('tg://') === 0;
          var isTme = url.indexOf('https://t.me/') === 0;
          if (isTgUser) {
            if (w && w.platform === 'web') {
              if (typeof w.showAlert === 'function') {
                try {
                  w.showAlert(
                    'В браузерной версии Telegram нельзя открыть чат только по внутреннему ID. Обновите данные — подтянется @username, или откройте мини-апп в приложении Telegram на телефоне.'
                  );
                } catch (e0) { /* noop */ }
              }
              return false;
            }
            try {
              window.location.assign(url);
            } catch (e1) { /* noop */ }
            return true;
          }
          if (isTme && w) {
            if (typeof w.openTelegramLink === 'function') {
              try {
                w.openTelegramLink(url);
                return true;
              } catch (e) { /* continue */ }
            }
            if (typeof w.openLink === 'function') {
              try {
                w.openLink(url, { try_instant_view: false });
                return true;
              } catch (e2) {
                try {
                  w.openLink(url);
                  return true;
                } catch (e3) { /* continue */ }
              }
            }
          }
          try {
            var a = document.createElement('a');
            a.href = url;
            a.rel = 'noopener noreferrer';
            a.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;pointer-events:auto;';
            a.target = '_blank';
            (document.body || document.documentElement).appendChild(a);
            a.click();
            setTimeout(function () {
              try {
                if (a && a.parentNode) a.parentNode.removeChild(a);
              } catch (x) { /* noop */ }
            }, 0);
          } catch (e4) { /* noop */ }
          try {
            window.location.href = url;
          } catch (e5) { /* noop */ }
          return true;
        };
      })();

      const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
      /** Uppercase two-letter labels for the fixed bottom week strip (Mon=0 … Sun=6). */
      const SCHEDULE_STRIP_DOW = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'];

      /** Same key as trainer-home-main.js — localStorage; при каждом сохранении слотов снимаем ×-mute рассылки. */
      const SCHEDULE_EDITOR_HUB_FILL_SLOTS_BOOST_KEY = 'trainer_hub_fill_slots_rhythm_boost_v1';
      function clearTrainerHubRhythmDismissForFillSlotsHints(optTrainerId) {
        try {
          var tid = '';
          if (optTrainerId != null && optTrainerId !== '' && !isNaN(Number(optTrainerId))) {
            tid = String(parseInt(String(optTrainerId), 10));
          } else if (
            typeof state !== 'undefined' &&
            state &&
            state.trainerId != null &&
            !isNaN(Number(state.trainerId))
          ) {
            tid = String(parseInt(String(state.trainerId), 10));
          }
          if (!tid) return;
          localStorage.removeItem('trainer_hub_rhythm_dismiss_v1_' + tid + '_open_loop_free_next');
          localStorage.removeItem('trainer_hub_rhythm_dismiss_v1_' + tid + '_open_loop_free_next_growth');
        } catch (e) {}
      }
      function markScheduleEditorHubFillSlotsRhythmBoost(optTrainerId) {
        try {
          var now = String(Date.now());
          localStorage.setItem(SCHEDULE_EDITOR_HUB_FILL_SLOTS_BOOST_KEY, now);
          try {
            sessionStorage.removeItem(SCHEDULE_EDITOR_HUB_FILL_SLOTS_BOOST_KEY);
          } catch (e1) {}
          clearTrainerHubRhythmDismissForFillSlotsHints(optTrainerId);
        } catch (e) {}
      }

      /**
       * Booking detail from a multi-client group slot (`state.bookingDetailReturn` is `group` or `hub_group`):
       * omit reschedule and cancel (ambiguous UX / wrong slot scope). «Постоянный клиент» stays available — API is the same.
       */
      const SCHEDULE_EDITOR_HIDE_GROUP_CONTEXT_BOOKING_ACTIONS = true;
      const SCHEDULE_SERVICE_UI_ACCENT_SLUGS = ['sky', 'amber', 'emerald', 'violet', 'rose', 'slate'];
      const SCHEDULE_SERVICE_SHORT_ALIASES = {
        'персональная тренировка': 'Персоналка',
        'персональная': 'Персоналка',
        'индивидуальная тренировка': 'Индив',
        'групповая тренировка': 'Группа',
        'силовая тренировка': 'Силовая',
        'реабилитационная тренировка': 'Реабил',
        'растяжка': 'Растяжка',
      };

      const BD_ICONS = {
        service: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><path d="M3.27 6.96L12 12.01l8.73-5.05"/></svg>',
        session: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>',
        tariff: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2H2v10l9.29 9.29a1 1 0 001.41 0l6.59-6.59a1 1 0 000-1.41L12 2z"/><circle cx="7.5" cy="7.5" r="1.5"/></svg>',
        venue: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>',
        price: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/></svg>',
        comment: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>',
        send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>',
        check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
        xCircle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        cancelOutline: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>',
        userPlus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>',
        linkOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M10 13a5 5 0 0 1 7.54.54 3 3 0 0 0 1.3 1.38"/><path d="M14 11a5 5 0 0 1 4.95 5.47"/><path d="M16 16a5 5 0 0 1-4.95 5"/><path d="M2 2l20 20"/><path d="M7.7 7.7A4 4 0 0 0 6 11c0 1.22.52 2.33 1.36 3.11"/><path d="M8.6 8.6A4 4 0 0 1 12 8a4 4 0 0 1 3.17 6.27"/></svg>',
        alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
      };

      function scheduleEditorServiceAccentSlug(serviceId) {
        var sid = serviceId != null ? parseInt(String(serviceId), 10) : NaN;
        if (isNaN(sid)) return '';
        var list = state.trainerServices || [];
        for (var i = 0; i < list.length; i++) {
          if (Number(list[i].id) === sid) {
            var a = list[i].ui_accent;
            if (a == null || !String(a).trim()) return '';
            var slug = String(a).trim().toLowerCase();
            if (SCHEDULE_SERVICE_UI_ACCENT_SLUGS.indexOf(slug) < 0) return '';
            return slug;
          }
        }
        return '';
      }

      function scheduleEditorServiceShortLabel(serviceName) {
        var raw = serviceName == null ? '' : String(serviceName).trim();
        if (!raw) return '';
        var normalized = raw
          .toLowerCase()
          .replace(/[ё]/g, 'е')
          .replace(/[^a-zA-Zа-яА-Я0-9\s-]/g, ' ')
          .replace(/\s+/g, ' ')
          .trim();
        if (!normalized) return '';
        if (SCHEDULE_SERVICE_SHORT_ALIASES[normalized]) return SCHEDULE_SERVICE_SHORT_ALIASES[normalized];
        var words = normalized.split(/\s+/).filter(Boolean);
        var base = words.slice(0, 2).join(' ');
        if (!base) return '';
        base = base.charAt(0).toUpperCase() + base.slice(1);
        if (base.length <= 14) return base;
        return base.slice(0, 13).trimEnd() + '…';
      }

      function scheduleEditorServiceBadgeHtml(serviceId, serviceName) {
        var label = scheduleEditorServiceShortLabel(serviceName);
        if (!label) return '';
        var slug = scheduleEditorServiceAccentSlug(serviceId);
        var slugCls = slug ? ' svc-badge--' + slug : '';
        return (
          '<span class="svc-badge' + slugCls + '" role="status">' +
            '<span class="svc-badge-dot" aria-hidden="true"></span>' +
            '<span class="svc-badge-label">' + escapeHtml(label) + '</span>' +
          '</span>'
        );
      }

      function scheduleEditorPrimaryArenaId() {
        var ars = state.trainerScheduleArenas || [];
        var prim = ars.filter(function(a) { return a.is_primary; })[0];
        if (prim) return Number(prim.id);
        return ars.length ? Number(ars[0].id) : null;
      }

      function scheduleEditorArenaNameById(aid) {
        if (aid == null || isNaN(Number(aid))) return '';
        var hit = (state.trainerScheduleArenas || []).filter(function(a) {
          return Number(a.id) === Number(aid);
        })[0];
        return hit ? String(hit.name || '').trim() : '';
      }

      /** Compact arena label for chips — keeps mini-cards tidy when venue name is long. */
      function scheduleEditorTruncateArenaLabel(name, maxLen) {
        var base = String(name || '').trim();
        if (!base) return '';
        var lim = maxLen != null ? maxLen : 12;
        if (base.length <= lim) return base;
        return base.slice(0, lim - 1).trimEnd() + '…';
      }

      /** Pill for non-primary venue — same chip model as service badges on booking rows. */
      function scheduleEditorArenaChipHtml(arenaId, arenaLabel) {
        var primaryId = scheduleEditorPrimaryArenaId();
        var aid = arenaId != null && !isNaN(Number(arenaId)) ? Number(arenaId) : null;
        if (aid == null || primaryId == null || aid === primaryId) return '';
        var full = String(arenaLabel || scheduleEditorArenaNameById(aid) || '').trim();
        if (!full) return '';
        var short = scheduleEditorTruncateArenaLabel(full, 13);
        return (
          '<span class="svc-badge svc-badge--slate schedule-arena-chip" role="status" title="' + escapeHtml(full) + '">' +
            '<span class="svc-badge-dot" aria-hidden="true"></span>' +
            '<span class="svc-badge-label">' + escapeHtml(short) + '</span>' +
          '</span>'
        );
      }

      function scheduleEditorGridArenaSelectId() {
        return state.editMode === 'template' ? 'templateGridArenaSelect' : 'calendarGridArenaSelect';
      }

      function scheduleEditorGridArenaPickHostId() {
        return state.editMode === 'template' ? 'templateGridArenaPick' : 'calendarGridArenaPick';
      }

      function syncScheduleEditorGridArenaPickHighlight() {
        var host = document.getElementById(scheduleEditorGridArenaPickHostId());
        if (!host) return;
        var aid = state.scheduleGridArenaPickId != null ? String(state.scheduleGridArenaPickId) : '';
        host.querySelectorAll('.schedule-grid-arena-chip').forEach(function(b) {
          var id = b.getAttribute('data-arena-id') || '';
          var on = !!aid && id === aid;
          b.setAttribute('aria-selected', on ? 'true' : 'false');
          b.classList.toggle('is-selected', on);
        });
      }

      function scheduleEditorSetGridArenaPick(aid) {
        var n = aid != null && !isNaN(Number(aid)) ? Number(aid) : null;
        state.scheduleGridArenaPickId = n;
        var sel = document.getElementById(scheduleEditorGridArenaSelectId());
        if (sel && n != null) sel.value = String(n);
        syncScheduleEditorGridArenaPickHighlight();
      }

      /** Chip picklist + hidden select for grid «Быстро» arena (calendar + template). */
      function fillScheduleEditorGridArenaPick(preferredId) {
        var selectId = scheduleEditorGridArenaSelectId();
        var pickId = scheduleEditorGridArenaPickHostId();
        var sel = document.getElementById(selectId);
        var host = document.getElementById(pickId);
        if (!sel || !host) return;
        var ars = state.trainerScheduleArenas || [];
        sel.innerHTML = '';
        host.innerHTML = '';
        ars.forEach(function(a) {
          var o = document.createElement('option');
          o.value = String(a.id);
          o.textContent = (a.name || '—') + (a.is_primary ? ' · основная' : '');
          sel.appendChild(o);
          var chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'schedule-grid-arena-chip';
          chip.setAttribute('role', 'option');
          chip.setAttribute('data-arena-id', String(a.id));
          chip.textContent = String(a.name || '—');
          if (a.is_primary) chip.setAttribute('data-primary', '1');
          chip.onclick = function() {
            scheduleEditorSetGridArenaPick(a.id);
          };
          host.appendChild(chip);
        });
        var pick = preferredId != null && !isNaN(Number(preferredId)) ? Number(preferredId) : null;
        if (pick == null && state.scheduleGridArenaPickId != null) pick = state.scheduleGridArenaPickId;
        if (pick == null || !ars.some(function(x) { return Number(x.id) === pick; })) {
          var prim = ars.filter(function(x) { return x.is_primary; })[0];
          pick = prim ? Number(prim.id) : (ars.length ? Number(ars[0].id) : null);
        }
        if (pick != null) scheduleEditorSetGridArenaPick(pick);
        else syncScheduleEditorGridArenaPickHighlight();
      }

      function fillScheduleEditorArenaSelect(selectId, preferredId) {
        var sel = document.getElementById(selectId);
        if (!sel) return;
        var ars = state.trainerScheduleArenas || [];
        var prev = sel.value;
        sel.innerHTML = '';
        ars.forEach(function(a) {
          var o = document.createElement('option');
          o.value = String(a.id);
          o.textContent = (a.name || '—') + (a.is_primary ? ' · основная' : '');
          sel.appendChild(o);
        });
        var pick = preferredId != null && !isNaN(Number(preferredId)) ? Number(preferredId) : null;
        if (pick != null && ars.some(function(x) { return Number(x.id) === pick; })) {
          sel.value = String(pick);
        } else if (prev && ars.some(function(x) { return String(x.id) === prev; })) {
          sel.value = prev;
        } else {
          var prim = ars.filter(function(x) { return x.is_primary; })[0];
          sel.value = String((prim || ars[0]).id);
        }
      }

      /** When all grid-aligned rows share one explicit arena — prefill grid picker on editor open. */
      function inferGridArenaIdFromSlotRows(rows, allowedStarts, gridDefaultDur) {
        var aids = [];
        (rows || []).forEach(function(row) {
          var sm = parseStartToMinutes(row.start_time);
          var dur = slotDurationFromRow(row);
          if (!allowedStarts.has(sm) || dur !== gridDefaultDur) return;
          var aidRaw = row.arena_id != null ? parseInt(String(row.arena_id), 10) : NaN;
          if (!isNaN(aidRaw)) aids.push(aidRaw);
        });
        if (!aids.length) return null;
        var unique = aids.filter(function(v, i, a) { return a.indexOf(v) === i; });
        return unique.length === 1 ? unique[0] : null;
      }

      function readGridArenaPickForSave() {
        var ars = state.trainerScheduleArenas || [];
        if (ars.length <= 1) return null;
        var aid = state.scheduleGridArenaPickId;
        if (aid == null || isNaN(Number(aid))) {
          var sel = document.getElementById(scheduleEditorGridArenaSelectId());
          aid = sel ? parseInt(sel.value, 10) : NaN;
        } else {
          aid = Number(aid);
        }
        if (isNaN(aid)) return null;
        var primaryId = scheduleEditorPrimaryArenaId();
        if (primaryId != null && aid === primaryId) return null;
        return aid;
      }

      function readPreciseArenaPickForSave() {
        var ars = state.trainerScheduleArenas || [];
        if (ars.length <= 1) return null;
        var selectId = state.editMode === 'template' ? 'templatePreciseArenaSelect' : 'calendarPreciseArenaSelect';
        var sel = document.getElementById(selectId);
        var aid = sel ? parseInt(sel.value, 10) : NaN;
        if (isNaN(aid)) return null;
        var primaryId = scheduleEditorPrimaryArenaId();
        if (primaryId != null && aid === primaryId) return null;
        return aid;
      }

      /** «Написать клиенту» — same data-* contract as hub (wireHubSlotMessageButtons + TrainerRelayHelpers). */
      function scheduleEditorSlotMessageButtonHtml(s, cap) {
        var Sed = window.TrainerRelayHelpers;
        if (!Sed || typeof Sed.contextFromScheduleBooking !== 'function') return '';
        var capN = parseInt(String(cap != null ? cap : '1'), 10);
        if (isNaN(capN) || capN < 1) capN = 1;
        var syn = {
          client_id: s.client_id,
          client_telegram_id: s.client_telegram_id,
          client_telegram_username: s.client_telegram_username,
          is_sandbox: !!s.has_sandbox_booking,
          slot_capacity: capN,
          client_phone: String(s.client_phone || '').trim(),
        };
        var ctx = Sed.contextFromScheduleBooking(syn);
        if (!Sed.canShowTrainerMessageButton(ctx)) return '';
        var useRelay = Sed.shouldUseRelayModal(ctx);
        var bid = s.booking_id != null ? String(s.booking_id) : '';
        var label = (s.client_preview && String(s.client_preview).trim()) ? String(s.client_preview).trim() : 'Клиент';
        var tip = useRelay
          ? 'Сообщение через бота клиента (ответ — в бот тренера)'
          : 'Написать клиенту в Telegram';
        var clientRelayDataAttrs =
          ' data-client-id="' +
          escapeHtml(String(syn.client_id)) +
          '" data-client-label="' +
          escapeHtml(label) +
          '" data-client-phone="' +
          escapeHtml(syn.client_phone) +
          '"';
        var relayAttr = useRelay ? ' data-hub-relay="1"' + clientRelayDataAttrs : clientRelayDataAttrs;
        var un = String(syn.client_telegram_username || '').replace(/^@/, '').trim();
        var tid = syn.client_telegram_id;
        return (
          '<button type="button" class="hub-slot-msg' +
          (useRelay ? ' hub-slot-msg--relay' : '') +
          '" data-hub-dm="trainer"' +
          (bid ? ' data-booking-id="' + escapeHtml(bid) + '"' : '') +
          relayAttr +
          ' data-dm-un="' + escapeHtml(un) + '"' +
          ' data-dm-tid="' + escapeHtml(tid != null ? String(tid) : '') + '"' +
          ' aria-label="' + escapeHtml(tip) + '" title="' + escapeHtml(tip) + '">' +
          '<svg class="hub-slot-msg-icon" viewBox="0 0 24 24" aria-hidden="true">' +
            '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>' +
          '</svg>' +
          '</button>'
        );
      }

      function bookingInitials(displayName) {
        var s = (displayName || '').trim();
        if (!s) return '?';
        var parts = s.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        if (parts[0].length >= 2) return parts[0].slice(0, 2).toUpperCase();
        return parts[0][0].toUpperCase();
      }

      /** Effective booking price from API (kopecks); HTML fragment with NBRB SVG suffix. */
      function formatTrainerDetailPriceFromCents(cents) {
        if (cents == null || cents === '') return '';
        var n = parseInt(String(cents), 10);
        if (isNaN(n)) return '';
        var v = n / 100;
        var numStr = v.toFixed(v % 1 === 0 ? 0 : 2).replace('.', ',');
        return escapeHtml(numStr) + ' BYN';
      }

      function formatTrainerBookingPaymentDisplay(booking) {
        var pc = String((booking && (booking.problem_payment_class || booking.expected_payment_class)) || '').toUpperCase();
        if (pc === 'PASS') return 'Абонемент покрывает';
        if (pc === 'CERT') return 'Сертификат покрывает';
        return formatTrainerDetailPriceFromCents(booking && booking.booking_price_cents);
      }

      function trainerBookingPaymentRowLabel(booking) {
        var pc = String((booking && (booking.problem_payment_class || booking.expected_payment_class)) || '').toUpperCase();
        return (pc === 'PASS' || pc === 'CERT') ? 'Оплата' : 'Стоимость';
      }

      var BD_ROW_EDIT_CHEVRON =
        '<svg class="bd-row-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>';

      /** Clickable detail row when service/tariff can be edited. */
      function bookingDetailEditableRow(iconHtml, label, valueText, editKind) {
        return (
          '<button type="button" class="bd-row bd-row--editable" data-bd-edit="' +
          escapeHtml(editKind) +
          '">' +
          iconHtml +
          '<div class="bd-row-text">' +
          '<div class="bd-row-label">' +
          escapeHtml(label) +
          ' <span class="bd-row-edit-hint">изменить</span></div>' +
          '<div class="bd-row-value">' +
          escapeHtml(valueText || '—') +
          '</div></div>' +
          BD_ROW_EDIT_CHEVRON +
          '</button>'
        );
      }

      /** Map detail-row edit kind to modal focus (`tariff` label in UI → `tier` step). */
      function normalizeBookingEditFocus(raw) {
        var k = String(raw || 'service').toLowerCase();
        if (k === 'tier' || k === 'tariff') return 'tier';
        if (k === 'arena' || k === 'venue') return 'arena';
        return 'service';
      }

      function bindBookingDetailEditableRows(booking) {
        var root = document.getElementById('detailBookingContent');
        if (!root || !booking) return;
        root.querySelectorAll('[data-bd-edit]').forEach(function(btn) {
          btn.onclick = function() {
            openBookingEditServiceModal(booking, normalizeBookingEditFocus(btn.getAttribute('data-bd-edit')));
          };
        });
      }

      function bookingEditTiersForServiceId(serviceId) {
        var svc = (state.bookServices || []).filter(function(x) {
          return Number(x.id) === Number(serviceId);
        })[0];
        return (svc && svc.price_tiers) ? svc.price_tiers : [];
      }

      /** Show only service or only tariff block in edit modal (no prices in controls). */
      function applyBookingEditModalLayout(booking, focusStep) {
        var se = (booking && booking.service_edit) || {};
        var stackSvc = document.getElementById('bookEditServiceStack');
        var stackArena = document.getElementById('bookEditArenaStack');
        var wrapTier = document.getElementById('bookEditPriceTierWrap');
        var titleEl = document.getElementById('bookingEditModalTitle');
        var leadEl = document.getElementById('bookingEditServiceLead');
        var showSvc = !!(se.can_edit_service && focusStep === 'service');
        var showArena = !!(se.can_edit_arena && focusStep === 'arena');
        var sid =
          state.bookingEditLockedServiceId != null
            ? state.bookingEditLockedServiceId
            : state.bookServiceId;
        var tiers = bookingEditTiersForServiceId(sid);
        var showTier = !!(se.can_edit_tier && focusStep === 'tier' && tiers.length > 1);
        if (stackSvc) stackSvc.style.display = showSvc ? '' : 'none';
        if (stackArena) stackArena.style.display = showArena ? '' : 'none';
        if (wrapTier) wrapTier.style.display = showTier ? 'block' : 'none';
        if (titleEl) {
          if (showArena && !showSvc && !showTier) titleEl.textContent = 'Площадка';
          else if (showTier && !showSvc && !showArena) titleEl.textContent = 'Тариф';
          else if (showSvc && !showTier && !showArena) titleEl.textContent = 'Услуга';
          else titleEl.textContent = 'Услуга и тариф';
        }
        if (leadEl) {
          if (showArena && !showSvc && !showTier) {
            leadEl.textContent = 'Выберите площадку для этой записи.';
          } else if (showTier && !showSvc && !showArena) {
            leadEl.textContent = 'Выберите тариф для этой записи.';
          } else if (showSvc && !showTier && !showArena) {
            leadEl.textContent = 'Выберите услугу для этой записи.';
          } else {
            leadEl.textContent = 'Выберите вариант для этой записи.';
          }
        }
      }

      const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
      const MONTHS_GENITIVE = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

      function bookPhoneFromField(el) {
        if (window.CrmPhoneField && el) return CrmPhoneField.validate(el);
        return { ok: false, e164: '', error: 'Укажите номер телефона.' };
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

      var _seCrmBannerCtaWired = false;

      function applyScheduleCrmLockUI() {
        var allowed = !!state.scheduleCrmWriteAllowed;
        var ban = document.getElementById('seCrmLockBanner');
        if (ban) {
          ban.hidden = allowed;
          ban.setAttribute('aria-hidden', allowed ? 'true' : 'false');
        }
        ['btnApplyTemplate'].forEach(function(id) {
          var el = document.getElementById(id);
          if (el) el.disabled = !allowed;
        });
        syncAddSlotsButtonEligibility();
        if (!_seCrmBannerCtaWired) {
          _seCrmBannerCtaWired = true;
          var cta = document.getElementById('seCrmLockBannerCta');
          if (cta) {
            cta.onclick = function() {
              try {
                window.location.assign('/webapp/trainer-subscription?v=20260450');
              } catch (e) { /* noop */ }
            };
          }
        }
      }

      function runAfterScheduleCrmGate(done) {
        if (!tg || !tg.initData) {
          state.scheduleCrmWriteAllowed = true;
          applyScheduleCrmLockUI();
          done();
          return;
        }
        getJsonTrainer('/trainer/subscription/status')
          .then(function(st) {
            var caps = st && st.unlocked_features;
            state.scheduleCrmWriteAllowed = Array.isArray(caps) && caps.indexOf('crm') !== -1;
            applyScheduleCrmLockUI();
            done();
          })
          .catch(function() {
            state.scheduleCrmWriteAllowed = true;
            applyScheduleCrmLockUI();
            done();
          });
      }

      /**
       * Hydrates TrainerMiniAppGate + window.TRAINER_WEBAPP_FORCE_CLIENT_CHAT_RELAY from GET /trainer/access.
       * open_booking= deep link used runAfterScheduleCrmGate-only and skipped this, so relay force never applied before detail UI.
       */
      function withTrainerMiniAppAccessThen(done) {
        if (
          tg &&
          tg.initData &&
          window.TrainerMiniAppGate &&
          typeof window.TrainerMiniAppGate.fetchAccess === 'function'
        ) {
          window.TrainerMiniAppGate.fetchAccess(tg.initData)
            .then(function(a) {
              if (a && !window.TrainerMiniAppGate.isActive(a)) {
                window.TrainerMiniAppGate.showBlockingOverlay(a);
                return;
              }
              done();
            })
            .catch(function() {
              done();
            });
          return;
        }
        done();
      }

      function assertScheduleCrmWriteAllowed() {
        if (state.scheduleCrmWriteAllowed) return true;
        var msg =
          'Нужна активная подписка с CRM, чтобы создавать слоты и записи. Откройте «Тарифы и оплата».';
        if (tg && typeof tg.showAlert === 'function') {
          try {
            tg.showAlert(msg);
          } catch (e) {
            alert(msg);
          }
        } else {
          alert(msg);
        }
        return false;
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

      function refreshScheduleEditorInboxCounts() {
        if (window.TrainerPendingInbox) TrainerPendingInbox.refreshInboxCounts();
      }

      function initScheduleEditorPendingInbox() {
        if (!window.TrainerPendingInbox || initScheduleEditorPendingInbox._done) return;
        initScheduleEditorPendingInbox._done = true;
        TrainerPendingInbox.init({
          surface: 'schedule_editor',
          getInitData: function() {
            return tg && tg.initData;
          },
          apiUrlWithQuery: apiUrlWithQuery,
          headersJson: headers,
          escapeHtml: escapeHtml,
          toast: showToast,
          postJsonTrainer: postJsonTrainer,
          chipEl: document.getElementById('sePendingInboxChip'),
          onAfterConfirm: function() {
            loadSlots();
          },
        });
      }

      function patchJsonTrainer(path, body) {
        return fetch(apiUrlWithQuery(path), {
          method: 'PATCH',
          headers: headers(),
          body: JSON.stringify(body || {}),
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
      function renderCalendarLoadFailure(err) {
        var el = document.getElementById('calendarContent');
        if (!el) return;
        var detail = '';
        if (err != null && err !== 'retry-init') {
          var raw = typeof err === 'string' ? err : (err && err.message) ? String(err.message) : '';
          if (raw && window.MiniAppErrorUi && typeof MiniAppErrorUi.humanizeDetail === 'function') {
            detail = MiniAppErrorUi.humanizeDetail(raw) || raw;
          } else if (raw) {
            detail = raw;
          }
        }
        var detailHtml = detail
          ? '<p class="schedule-reload-panel__detail">' + escapeHtml(detail) + '</p>'
          : '';
        el.innerHTML =
          '<div class="schedule-reload-panel">' +
          '<p class="schedule-reload-panel__msg">Не удалось загрузить расписание. Проверьте соединение и попробуйте снова.</p>' +
          detailHtml +
          '<p class="schedule-reload-panel__hint">Если не помогло — закройте мини-приложение и снова нажмите синюю кнопку «Обзор» слева от поля ввода в боте (или /home).</p>' +
          '<button type="button" class="btn-secondary schedule-reload-panel__btn" id="btnScheduleCalendarReload">Обновить</button>' +
          '</div>';
        var btn = document.getElementById('btnScheduleCalendarReload');
        if (btn) {
          btn.onclick = function() {
            loadSlots();
          };
        }
        renderScheduleWeekDayStrip();
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
        syncScheduleWeekDayStripVisibility();
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
        var mCenterSession =
          document.getElementById('modalCenterSession') &&
          document.getElementById('modalCenterSession').style.display === 'flex';
        var mBookConf = document.getElementById('modalBookConfirm').style.display === 'flex';
        var mCancelB = document.getElementById('modalBookingCancel').style.display === 'flex';
        var mEditSvc =
          document.getElementById('modalBookingEditService') &&
          document.getElementById('modalBookingEditService').style.display === 'flex';
        var mClientProb = document.getElementById('modalClientProblem') && document.getElementById('modalClientProblem').style.display === 'flex';
        var mTpl = document.getElementById('modalConfirm').style.display === 'flex';
        var mTemplateApply =
          document.getElementById('modalTemplateApply') &&
          document.getElementById('modalTemplateApply').style.display === 'flex';
        var mIntent = document.getElementById('modalSlotIntent') && document.getElementById('modalSlotIntent').style.display === 'flex';
        btn.hidden = !(
          booking ||
          decline ||
          edit ||
          dayPick ||
          mQuick ||
          mQuickSvc ||
          mBook ||
          mGroup ||
          mCenterSession ||
          mBookConf ||
          mCancelB ||
          mEditSvc ||
          mClientProb ||
          mTpl ||
          mTemplateApply ||
          mIntent
        );
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
        var mcs = document.getElementById('modalCenterSession');
        if (mcs && mcs.style.display === 'flex') {
          closeCenterSessionModal();
          return;
        }
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
          var centerBtnBack = document.getElementById('btnSlotIntentCenter');
          if (ind) ind.classList.remove('is-suggested');
          if (grp) grp.classList.remove('is-suggested');
          if (centerBtnBack) centerBtnBack.classList.remove('is-suggested');
          updateTelegramBack();
          return;
        }
        var mbc = document.getElementById('modalBookingCancel');
        if (mbc && mbc.style.display === 'flex') {
          mbc.style.display = 'none';
          updateTelegramBack();
          return;
        }
        var mbes = document.getElementById('modalBookingEditService');
        if (mbes && mbes.style.display === 'flex') {
          closeBookingEditServiceModal();
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
        var mta = document.getElementById('modalTemplateApply');
        if (mta && mta.style.display === 'flex') {
          closeTemplateApplySheet();
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
          if (state.editMode === 'calendar') {
            returnToCalendarDayPickFromEdit({ reloadSlots: false });
            return;
          }
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

      function bookingDetailPhoneHtml(phone, extraClass) {
        var Pf = window.CrmPhoneField;
        if (Pf && typeof Pf.phoneTelLinkHtml === 'function') {
          var cls = 'bd-tel' + (extraClass ? ' ' + extraClass : '');
          return Pf.phoneTelLinkHtml(phone, cls, escapeHtml);
        }
        var p = String(phone || '').trim();
        if (!p) return '';
        var telRaw = p.replace(/[^\d+]/g, '');
        if (!telRaw) return escapeHtml(p);
        var clsFallback = 'bd-tel' + (extraClass ? ' ' + extraClass : '');
        return (
          '<button type="button" class="' +
          clsFallback +
          '" data-call-phone="' +
          escapeHtml(telRaw) +
          '" aria-label="Позвонить ' +
          escapeHtml(p) +
          '">' +
          escapeHtml(p) +
          '</button>'
        );
      }

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
        hideFlowBookBootOverlay();
        getJsonTrainer('/trainer/bookings/' + bookingId).then(function(b) {
          state.selectedBooking = b;
          var client = [b.client_first_name, b.client_last_name].filter(Boolean).join(' ') || b.client_phone || 'Клиент';
          var dateStr = formatBookingDate(b.slot_date);
          var initials = bookingInitials(client);
          var html = '';
          html += '<div class="booking-detail">';
          if (b.is_sandbox) {
            html +=
              '<div class="bd-test-booking-banner" role="status">' +
              '<span class="schedule-sandbox-pill schedule-sandbox-pill--inline">тест</span>' +
              '<span class="bd-test-booking-banner__text">Тестовая запись — для знакомства с системой, без напоминаний клиенту.</span>' +
              '</div>';
          }
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
            html += '<div class="bd-client-name">' + escapeHtml(client) + (b.client_has_telegram === false && !b.is_sandbox ? ' <span class="no-bot">Без бота</span>' : '') + '</div>';
            html += '<span class="bd-client-profile-hint">Профиль и заметки</span>';
            html += '</div>';
            html += '<svg class="bd-client-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>';
            html += '</a>';
            if (b.client_phone) {
              html += bookingDetailPhoneHtml(b.client_phone, 'bd-tel--block');
            }
            html += '</div>';
          } else {
            html += '<div class="bd-client">';
            html += '<div class="bd-avatar" aria-hidden="true">' + escapeHtml(initials) + '</div>';
            html += '<div class="bd-client-body">';
            html += '<div class="bd-client-name">' + escapeHtml(client) + (b.client_has_telegram === false && !b.is_sandbox ? ' <span class="no-bot">Без бота</span>' : '') + '</div>';
            html += bookingDetailPhoneHtml(b.client_phone);
            html += '</div></div>';
          }
          html += '<div class="bd-section-label">Подробности</div>';
          html += '<div class="bd-rows">';
          var serviceEditPolicy = b.service_edit || {};
          var canEditServiceRow = !!(serviceEditPolicy.allowed && serviceEditPolicy.can_edit_service);
          var canEditTierRow = !!(serviceEditPolicy.allowed && serviceEditPolicy.can_edit_tier);
          var canEditArenaRow = !!(serviceEditPolicy.allowed && serviceEditPolicy.can_edit_arena);
          if (canEditServiceRow) {
            html += bookingDetailEditableRow(BD_ICONS.service, 'Услуга', b.services_str || '—', 'service');
          } else if (!canEditArenaRow) {
            html +=
              '<div class="bd-row">' +
              BD_ICONS.service +
              '<div class="bd-row-text"><div class="bd-row-label">Услуга · арена</div><div class="bd-row-value">' +
              escapeHtml(b.services_str || '—') +
              ' · ' +
              escapeHtml(b.arenas_str || '—') +
              '</div></div></div>';
          } else {
            html +=
              '<div class="bd-row">' +
              BD_ICONS.service +
              '<div class="bd-row-text"><div class="bd-row-label">Услуга</div><div class="bd-row-value">' +
              escapeHtml(b.services_str || '—') +
              '</div></div></div>';
          }
          if (canEditArenaRow) {
            html += bookingDetailEditableRow(BD_ICONS.venue, 'Площадка', b.arenas_str || '—', 'arena');
          } else if (canEditServiceRow) {
            html +=
              '<div class="bd-row">' +
              BD_ICONS.venue +
              '<div class="bd-row-text"><div class="bd-row-label">Площадка</div><div class="bd-row-value">' +
              escapeHtml(b.arenas_str || '—') +
              '</div></div></div>';
          }
          html += '<div class="bd-row">' + BD_ICONS.session + '<div class="bd-row-text"><div class="bd-row-label">Занятие</div><div class="bd-row-value">' + (b.session_num || 1) + '-е занятие</div></div></div>';
          var tierLab = (b.price_tier_label || '').trim();
          if (canEditTierRow) {
            html += bookingDetailEditableRow(BD_ICONS.tariff, 'Тариф', tierLab || '—', 'tier');
          } else if (tierLab) {
            html +=
              '<div class="bd-row">' +
              BD_ICONS.tariff +
              '<div class="bd-row-text"><div class="bd-row-label">Тариф</div><div class="bd-row-value">' +
              escapeHtml(tierLab) +
              '</div></div></div>';
          }
          var payPc = String((b.problem_payment_class || b.expected_payment_class || '')).toUpperCase();
          var payValueHtml = '';
          if (payPc === 'PASS') payValueHtml = escapeHtml('Абонемент покрывает');
          else if (payPc === 'CERT') payValueHtml = escapeHtml('Сертификат покрывает');
          else payValueHtml = formatTrainerDetailPriceFromCents(b.booking_price_cents);
          if (payValueHtml) {
            html +=
              '<div class="bd-row" id="bdDetailPriceRow">' +
              BD_ICONS.price +
              '<div class="bd-row-text"><div class="bd-row-label">' +
              escapeHtml(trainerBookingPaymentRowLabel(b)) +
              '</div><div class="bd-row-value" id="bdDetailPriceValue">' +
              payValueHtml +
              '</div></div></div>';
          }
          if (b.client_comment) {
            html += '<div class="bd-row bd-comment">' + BD_ICONS.comment + '<div class="bd-row-text"><div class="bd-row-label">Комментарий</div><div class="bd-row-value">' + escapeHtml(b.client_comment) + '</div></div></div>';
          }
          html += '</div></div>';
          document.getElementById('detailBookingContent').innerHTML = html;
          if (window.CrmPhoneField && typeof window.CrmPhoneField.wirePhoneCallButtons === 'function') {
            window.CrmPhoneField.wirePhoneCallButtons(document.getElementById('detailBookingContent'));
          } else if (window.CrmPhoneField && typeof window.CrmPhoneField.wirePhoneTelLinks === 'function') {
            window.CrmPhoneField.wirePhoneTelLinks(document.getElementById('detailBookingContent'));
          }
          bindBookingDetailEditableRows(b);

          var actions = document.getElementById('detailBookingActions');
          actions.innerHTML = '';
          var pending = (b.status || '') === 'pending';
          var completed = (b.status || '') === 'completed';
          var stRaw = (b.status || '').toLowerCase();
          var bookingEnded = isSlotEndedInPast(b);
          var canCancelBooking = stRaw === 'confirmed' && !bookingEnded;
          var bookingDetailFromGroupSlot =
            state.bookingDetailReturn === 'group' || state.bookingDetailReturn === 'hub_group';
          var suppressGroupSlotBookingActions =
            SCHEDULE_EDITOR_HIDE_GROUP_CONTEXT_BOOKING_ACTIONS && bookingDetailFromGroupSlot;

          var primaryActions = [];
          var extraActions = [];
          if (pending) {
            primaryActions.push({ cls: 'bd-btn--confirm', action: 'confirm', icon: BD_ICONS.check, label: 'Подтвердить' });
            primaryActions.push({ cls: 'bd-btn--decline', action: 'decline', icon: BD_ICONS.xCircle, label: 'Отклонить' });
          } else if (canCancelBooking && !suppressGroupSlotBookingActions) {
            primaryActions.push({ cls: 'bd-btn--secondary', action: 'reschedule', icon: BD_ICONS.session, label: 'Перенести запись' });
            primaryActions.push({ cls: 'bd-btn--outline-danger', action: 'cancel', icon: BD_ICONS.cancelOutline, label: 'Отменить запись' });
          }
          if (window.TrainerRelayHelpers) {
            var Wctx = window.TrainerRelayHelpers.contextFromScheduleBooking(b);
            if (window.TrainerRelayHelpers.canShowTrainerMessageButton(Wctx)) {
              var writeBtnLabel = window.TrainerRelayHelpers.shouldUseRelayModal(Wctx)
                ? 'Написать клиенту в чат'
                : 'Написать клиенту';
              extraActions.push({ cls: 'bd-btn--surface', action: 'write_client', icon: BD_ICONS.send, label: writeBtnLabel });
            }
          }
          var canReportProblem = stRaw !== 'cancelled' && stRaw !== 'declined';
          // E7: false when rollout=off or pilot excludes this trainer (API sets problem_flow_enabled).
          var problemFlowOk = (b.problem_flow_enabled !== false);
          var serviceEdit = b.service_edit || {};
          if (!serviceEdit.allowed && serviceEdit.reason) {
            actions.innerHTML +=
              '<p class="bd-service-edit-hint">' + escapeHtml(serviceEdit.reason) + '</p>';
          }
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
          // Recurring: not tied to «which slot tile opened detail» — show even from group / hub_group (see flag comment above).
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
          hideFlowBookBootOverlay();
          alert('Ошибка загрузки');
          showBookingStack('main');
          loadSlots();
        });
      }

      function confirmTrainerBooking(bookingId) {
        postJsonTrainer('/trainer/bookings/' + bookingId + '/confirm', null).then(function() {
          showToast('Запись подтверждена');
          if (window.TrainerPendingInbox) {
            TrainerPendingInbox.trackEvent('batch_confirm_success', {
              confirmed_count: 1,
              requested_count: 1,
              item_id: 'single_booking_detail',
            });
            refreshScheduleEditorInboxCounts();
          }
          leaveDetailAfterMutation();
        }).catch(function() { alert('Ошибка'); });
      }

      function makeRegularFromBooking(bookingId) {
        postJsonTrainer('/trainer/bookings/' + bookingId + '/make_regular', null).then(function(res) {
          var n = res && typeof res.materialized_bookings === 'number' ? res.materialized_bookings : 0;
          if (n > 0) {
            showToast('Добавлено записей по регулярности: ' + n);
          } else {
            showToast('Регулярное время сохранено');
          }
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
        var id = state.selectedBooking && state.selectedBooking.id;
        if (!id) return;
        postJsonTrainer('/trainer/bookings/' + id + '/decline', { comment: comment || null }).then(function() {
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

      function scheduleWeekSwipeNavHintLsKey(trainerId) {
        if (trainerId == null || trainerId === '' || isNaN(Number(trainerId))) return null;
        return 'schedule_editor_week_swipe_nav_hint_v1_' + String(trainerId);
      }

      /** Heuristic only: show swipe-related copy/toasts — avoids bothering pure mouse/trackpad desktops. */
      function deviceLikelySupportsTouchSwipeNavigation() {
        try {
          if (typeof window.matchMedia === 'function') {
            var mqCoarse = window.matchMedia('(any-pointer: coarse)');
            if (mqCoarse && mqCoarse.matches) return true;
          }
        } catch (eMq) { /* ignore */ }
        var mtp = Number(navigator.maxTouchPoints || 0) || 0;
        return mtp > 0;
      }

      /** One toast per trainer — discoverability without hiding arrows (arrows stay for all screens). */
      function maybeShowScheduleWeekSwipeNavHintOnce() {
        if (!deviceLikelySupportsTouchSwipeNavigation()) return;
        var tid = state.trainerId;
        var tidNum = tid != null ? parseInt(String(tid), 10) : NaN;
        if (isNaN(tidNum) || tidNum < 1) return;
        var key = scheduleWeekSwipeNavHintLsKey(tidNum);
        if (!key) return;
        try {
          if (localStorage.getItem(key) === '1') return;
        } catch (eR) { /* ignore */ }
        try {
          localStorage.setItem(key, '1');
        } catch (eW) { /* quota / private mode */ }
        showToast(
          'Неделю можно листать свайпом влево/вправо по расписанию. Стрелки над датой тоже работают.',
          4400
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
        /** Center duty windows (studio_central) — empty for solo trainers; merged in calendar when non-empty. */
        centerDuties: [],
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
        /** Precise (off-grid) slots added manually: [{startMinutes, durationMinutes}] */
        preciseSlots: [],
        /** 'grid' | 'precise' */
        slotAddMode: 'grid',
        preciseDraftDuration: 45,
        applyWeekStart: null,
        /** Ordered Mondays (YYYY-MM-DD) for template apply confirm — one or many weeks. */
        applyWeekStarts: null,
        /** When true, current/partial week lists Mon… + ended slots (backfill). */
        showPastThisWeek: false,
        /** `YYYY-MM-DD` within current `weekStart` week — bottom strip highlight + scroll target. */
        scheduleStripSelectedDate: null,
        /** From hub Week Pulse / deep link: scroll strip + calendar after first loadSlots. */
        pendingScheduleStripAnchorDate: null,
        /** Prevents stacked week navigations while /schedule fetch is in flight (buttons + swipe). */
        scheduleLoadInFlight: false,
        /** After horizontal week swipe on day-pick rows (buttons), block synthetic clicks opening a day editor. */
        scheduleDayPickSwipeSuppressUntil: 0,
        /** After horizontal week swipe on the bottom Mon–Sun strip, block synthetic clicks (day pick / week arrows). */
        scheduleStripSwipeSuppressUntil: 0,
        /** While programmatic scroll-to-day runs, ignore scroll-spy updates (avoid strip flicker). */
        scheduleStripScrollSyncSuppressUntil: 0,
        bookSlotId: null,
        bookModalStep: 'choice',
        /** Slot / quick-book opens straight to client search + «Новый клиент» (hub parity); back closes modal. */
        bookModalClientSearchFirst: false,
        /** Service step opened after «Далее» on new-client form (hub «Записать клиента» parity). */
        bookServiceStepFromNewClient: false,
        pendingBookClientId: null,
        pendingBookClientName: null,
        bookServices: [],
        bookServiceId: null,
        bookPriceVariantId: null,
        trainerArenas: [],
        bookArenaId: null,
        /** From CRM / Telegram «Записать снова»: GET booking-defaults?from_booking_id= — presets from that session. */
        presetBookingDefaultsId: null,
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
        /** Booking id while modalBookingEditService is open (PATCH /trainer/bookings/:id/service). */
        bookingEditTargetId: null,
        /** 'service' | 'tier' — which row opened the edit modal. */
        bookingEditFocus: null,
        bookingEditLockedServiceId: null,
        bookingEditModalBooking: null,
        /** False after /trainer/subscription/status when `crm` not in unlocked_features (Lead Mode / no sub). */
        scheduleCrmWriteAllowed: true,
        /** Slots for selected quick-book day (from GET /schedule); used to mark busy hours. */
        quickBookSlotsForDay: null,
        quickBookSlotDate: null,
        /** Minutes from midnight for quick book (15 min grid, 06:00–23:00 default window). */
        quickBookStartMinutes: null,
        quickBookDurationMinutes: 45,
        bookContexts: null,
        bookContextsPrefetch: null,
        bookContextsPrefetchPromise: null,
        centerScheduleAdmin: null,
        centerEditCoachIds: null,
        /** After center day edit: 'daypick' | 'template' | 'calendar'. */
        centerEditReturn: null,
        centerGridWeekLoadInFlight: false,
        bookContextKind: 'personal_slot',
        bookSessionContextId: null,
        bookCollectiveSlug: null,
        bookCenterSession: null,
        bookCenterSessions: null,
        bookCenterClientId: null,
        bookDelegateTargetId: null,
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
        /** Grid «Быстро» arena pick (calendar + template editor). */
        scheduleGridArenaPickId: null,
        /** Calendar day editor: start minutes that already had slots when the screen opened (cannot deselect). */
        calendarBaselineStarts: null,
        /** Calendar individual: precise-slot keys at editor open — for toast counts (omit already-existing intervals). */
        calendarBaselinePreciseKeys: null,
        /** Group slot (capacity &gt; 1) — fixed service, no price tier UI. */
        bookSlotIsGroup: false,
        bookSlotGroupServiceId: null,
        /** «Выбрать из списка»: клиент выбран на шаге 1, услуга/тариф на шаге 2 (как в хабе). */
        bookSelectedExistingClientId: null,
        bookSelectedExistingClientName: '',
        bookExistingServiceStepActive: false,
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
        var Sed = window.TrainerRelayHelpers;
        if (!Sed) return;
        var sdCtx = Sed.contextFromScheduleBooking(booking);
        if (!Sed.canShowTrainerMessageButton(sdCtx)) return;
        if (Sed.shouldUseRelayModal(sdCtx)) {
          Sed.openRelaySendModalForContext(sdCtx, {
            subtitle: Sed.scheduleBookingSubtitle(booking),
          });
          return;
        }
        var un = String(booking.client_telegram_username || '').replace(/^@/, '').trim();
        var tid = booking.client_telegram_id;
        if (typeof window.openTelegramChatFromMiniApp === 'function') {
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

      /** Prefer last booking / slot hint when linked; else primary / first arena. */
      function pickDefaultBookArenaId(arenas, preferredId) {
        var list = arenas || [];
        if (!list.length) return null;
        if (preferredId != null) {
          var want = parseInt(String(preferredId), 10);
          if (!isNaN(want) && list.some(function(a) { return a.id === want; })) return want;
        }
        var prim = list.filter(function(a) { return a.is_primary; })[0];
        if (prim) return prim.id;
        return list[0].id;
      }

      function fillTrainerArenasUI(preferredArenaId) {
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
        var pref = preferredArenaId != null ? preferredArenaId : state.bookArenaId;
        if (pref == null && state.bookSlotId && !state.bookFlowQuick) {
          var slotHint = state.slots.find(function(s) { return s.id === state.bookSlotId; });
          if (slotHint && slotHint.arena_id != null) pref = slotHint.arena_id;
        }
        state.bookArenaId = pickDefaultBookArenaId(arenas, pref);
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

      /** Две кнопки выбора клиента: общая высота до ответа API, затем одновременное появление. */
      function primeBookChoicePairLayout() {
        var exBtn = document.getElementById('bookOptExisting');
        var newBtn = document.getElementById('bookOptNew');
        if (exBtn) {
          exBtn.style.display = '';
          exBtn.setAttribute('aria-hidden', 'false');
        }
        if (newBtn) {
          newBtn.style.display = '';
          newBtn.setAttribute('aria-hidden', 'false');
        }
      }

      function setBookChoicePairPending(on) {
        var w = document.getElementById('bookChoiceActions');
        if (!w) return;
        w.classList.toggle('book-choice-actions--pending', !!on);
      }

      function scheduleRevealBookChoicePairIfNeeded() {
        var ch = document.getElementById('bookStepChoice');
        if (!ch || ch.style.display === 'none') return;
        requestAnimationFrame(function() {
          setBookChoicePairPending(false);
        });
      }

      function trainerBookingPayload(clientId, serviceId) {
        var o = { slot_id: state.bookSlotId, client_id: clientId, service_id: serviceId };
        if (state.bookDelegateTargetId) o.target_trainer_id = state.bookDelegateTargetId;
        if (state.bookCollectiveSlug) o.collective_slug = state.bookCollectiveSlug;
        if (!state.bookSlotIsGroup && state.bookPriceVariantId != null) {
          o.service_price_variant_id = state.bookPriceVariantId;
        }
        /* Group slots stay on the slot venue; individual trainer booking uses chosen arena (defaults + override). */
        if (state.bookSlotIsGroup && state.bookSlotId) {
          var slotG = state.slots.find(function(s) { return s.id === state.bookSlotId; });
          var aidG = slotG && slotG.arena_id != null ? parseInt(String(slotG.arena_id), 10) : NaN;
          if (!isNaN(aidG)) o.arena_id = aidG;
        } else if (state.trainerArenas && state.trainerArenas.length > 1 && state.bookArenaId != null) {
          o.arena_id = state.bookArenaId;
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
        state.presetBookingDefaultsId = null;
        state.bookSelectedExistingClientId = null;
        state.bookSelectedExistingClientName = '';
        state.bookExistingServiceStepActive = false;
        state.bookServiceStepFromNewClient = false;
        state.bookModalClientSearchFirst = false;
        state.bookContextKind = 'personal_slot';
        state.bookSessionContextId = null;
        state.bookCollectiveSlug = null;
        state.bookDelegateTargetId = null;
        state.bookCenterSession = null;
        state.bookCenterClientId = null;
        state.bookContexts = null;
        var bookFlowOv = document.getElementById('modalBookClient');
        if (bookFlowOv) bookFlowOv.classList.remove('book-flow-overlay--new-client');
      }

      function showBookExistingClientStep() {
        var cEl = document.getElementById('bookExistingStepClient');
        var sEl = document.getElementById('bookExistingStepService');
        if (cEl) cEl.style.display = 'block';
        if (sEl) {
          sEl.style.display = 'none';
          sEl.setAttribute('aria-hidden', 'true');
        }
        state.bookExistingServiceStepActive = false;
      }

      function showBookExistingServiceStep() {
        var cEl = document.getElementById('bookExistingStepClient');
        var sEl = document.getElementById('bookExistingStepService');
        if (cEl) cEl.style.display = 'none';
        if (sEl) {
          sEl.style.display = 'block';
          sEl.setAttribute('aria-hidden', 'false');
        }
        state.bookExistingServiceStepActive = true;
      }

      function showBookStep(stepId) {
        document.querySelectorAll('.book-step').forEach(function(step) {
          var on = step.id === stepId;
          step.style.display = on ? 'block' : 'none';
          step.classList.toggle('active', on);
        });
        state.bookModalStep = stepId.replace('bookStep', '').toLowerCase();
        updateTelegramBack();
      }

      function fetchBookingContexts() {
        if (window.TrainerBookingContext) {
          return TrainerBookingContext.fetchContexts(function(path) {
            return getJsonTrainer(path);
          });
        }
        return getJsonTrainer('/trainer/booking-contexts').catch(function() {
          return { contexts: [{ kind: 'personal_slot', context_id: 'personal', label: 'Личное расписание' }], needs_context_picker: false };
        });
      }

      function scheduleBookContextsNeedPicker(payload) {
        if (window.TrainerBookingContext) {
          return TrainerBookingContext.needsContextPicker(TrainerBookingContext.normalizePayload(payload));
        }
        return !!(payload && payload.needs_context_picker && (payload.contexts || []).length > 1);
      }

      function scheduleResolveBookShellKind(prefilledClient) {
        if (prefilledClient) return 'profile';
        var prefetch = state.bookContextsPrefetch;
        if (prefetch && scheduleBookContextsNeedPicker(prefetch)) return 'context';
        if (prefetch) return 'clients';
        return 'prepare';
      }

      function prefetchScheduleBookingContexts() {
        if (state.bookContextsPrefetch) return Promise.resolve(state.bookContextsPrefetch);
        if (state.bookContextsPrefetchPromise) return state.bookContextsPrefetchPromise;
        state.bookContextsPrefetchPromise = fetchBookingContexts()
          .then(function(payload) {
            state.bookContextsPrefetch = payload;
            return payload;
          })
          .catch(function() {
            state.bookContextsPrefetchPromise = null;
            return null;
          });
        return state.bookContextsPrefetchPromise;
      }

      function applyBookContextSelection(ctx, clientId) {
        var applied = window.TrainerBookingContext
          ? TrainerBookingContext.applyContext(ctx)
          : { kind: ctx.kind, collective_slug: ctx.collective_slug || null, context_id: ctx.context_id };
        state.bookContextKind = applied.kind;
        state.bookCollectiveSlug = applied.collective_slug;
        state.bookSessionContextId = applied.context_id || (ctx && ctx.context_id) || null;
        if (clientId != null && window.TrainerBookingContext) {
          TrainerBookingContext.rememberContextForClient(clientId, applied.context_id);
        }
      }

      function maybeApplyBookContextForClient(clientId, onContinue) {
        var payload = state.bookContexts;
        if (!payload) {
          onContinue();
          return;
        }
        if (state.bookSessionContextId) {
          var locked = (payload.contexts || []).filter(function(c) {
            return c.context_id === state.bookSessionContextId;
          })[0];
          if (locked) {
            applyBookContextSelection(locked, clientId);
            onContinue();
            return;
          }
        }
        if (window.TrainerBookingContext) {
          var normalized = TrainerBookingContext.normalizePayload(payload);
          if (!TrainerBookingContext.needsContextPicker(normalized)) {
            applyBookContextSelection(normalized.contexts[0], clientId);
            onContinue();
            return;
          }
          var resolved = TrainerBookingContext.resolveInitialContext(normalized, clientId);
          if (resolved) {
            applyBookContextSelection(resolved, clientId);
            onContinue();
            return;
          }
        } else if (!payload.needs_context_picker) {
          onContinue();
          return;
        }
        renderBookContextStep(payload, clientId, onContinue);
        showBookStep('bookStepContext');
      }

      function renderBookContextStep(payload, clientId, onContinue) {
        var wrap = document.getElementById('bookContextActions');
        if (!wrap) return;
        if (window.TrainerBookingContext) {
          TrainerBookingContext.renderPicker(wrap, payload, {
            escapeHtml: escapeHtml,
            attrPrefix: 'data-book',
            clientId: clientId,
            onSelect: function(ctx) {
              applyBookContextSelection(ctx, clientId);
              if (state.bookContextKind === 'center_session') {
                state.bookSlotId = null;
                state.bookFlowQuick = false;
                showBookStep('bookStepExisting');
                setBookClientSearchSectionVisible(true);
                if (clientId) {
                  enterBookCenterFlowForClient(clientId, null);
                } else {
                  loadBookClients('');
                }
                return;
              }
              if (typeof onContinue === 'function') {
                onContinue();
                return;
              }
              showBookStep('bookStepExisting');
              setBookClientSearchSectionVisible(true);
              loadBookClients('');
            },
          });
          return;
        }
        var contexts = (payload && payload.contexts) || [];
        wrap.innerHTML = contexts.map(function(ctx) {
          return (
            '<button type="button" class="btn-book-option" data-book-context="' + escapeHtml(ctx.context_id) + '" data-book-kind="' + escapeHtml(ctx.kind) + '" data-collective-slug="' + escapeHtml(ctx.collective_slug || '') + '">' +
              '<span class="btn-book-option-body"><span class="btn-book-option-text">' + escapeHtml(ctx.label) + '</span></span>' +
              '<span class="btn-book-option-arrow" aria-hidden="true">›</span>' +
            '</button>'
          );
        }).join('');
        wrap.querySelectorAll('[data-book-context]').forEach(function(btn) {
          btn.onclick = function() {
            applyBookContextSelection({
              kind: btn.getAttribute('data-book-kind') || 'personal_slot',
              context_id: btn.getAttribute('data-book-context') || 'personal',
              collective_slug: btn.getAttribute('data-collective-slug') || null,
            }, clientId);
            if (state.bookContextKind === 'center_session') {
              state.bookSlotId = null;
              state.bookFlowQuick = false;
              showBookStep('bookStepExisting');
              setBookClientSearchSectionVisible(true);
              if (clientId) {
                enterBookCenterFlowForClient(clientId, null);
              } else {
                loadBookClients('');
              }
              return;
            }
            if (typeof onContinue === 'function') {
              onContinue();
              return;
            }
            showBookStep('bookStepExisting');
            setBookClientSearchSectionVisible(true);
            loadBookClients('');
          };
        });
      }

      function enterBookCenterFlowForClient(clientId, displayNameOrNull) {
        state.bookCenterClientId = clientId;
        var slug = state.bookCollectiveSlug;
        if (!slug) {
          alert('Не выбран контекст центра');
          return;
        }
        if (state.bookCenterSession && state.bookCenterSession.id != null) {
          showBookStep('bookStepCenter');
          var leadPreset = document.getElementById('bookCenterLead');
          if (leadPreset) {
            var sess = state.bookCenterSession;
            leadPreset.textContent =
              (displayNameOrNull || 'Клиент') +
              ' — ' +
              (sess.start_time || '') +
              '–' +
              (sess.end_time || '');
          }
          renderBookCenterModePickers();
          return;
        }
        showBookStep('bookStepCenter');
        var lead = document.getElementById('bookCenterLead');
        if (lead) lead.textContent = (displayNameOrNull || 'Клиент') + ' — выберите окно центра';
        var list = document.getElementById('bookCenterSessionList');
        if (list) list.innerHTML = '<p class="book-choice-lead">Загрузка окон…</p>';
        getJsonTrainer('/trainer/collective/staff-booking-sessions?collective_slug=' + encodeURIComponent(slug))
          .then(function(data) {
            state.bookCenterSessions = data.sessions || [];
            if (!state.bookCenterSessions.length) {
              if (list) list.innerHTML = '<p class="error">Нет доступных окон</p>';
              return;
            }
            if (list) {
              list.innerHTML = state.bookCenterSessions.map(function(s) {
                return (
                  '<button type="button" class="client-row" data-session-id="' + s.id + '">' +
                    escapeHtml((s.slot_date || '') + ' ' + (s.start_time || '') + '–' + (s.end_time || '')) +
                  '</button>'
                );
              }).join('');
              list.querySelectorAll('[data-session-id]').forEach(function(row) {
                row.onclick = function() {
                  var sid = parseInt(row.getAttribute('data-session-id'), 10);
                  state.bookCenterSession = state.bookCenterSessions.filter(function(x) { return Number(x.id) === sid; })[0] || null;
                  renderBookCenterModePickers();
                };
              });
            }
          })
          .catch(function(e) {
            if (list) list.innerHTML = '<p class="error">' + escapeHtml(e.message || 'Ошибка') + '</p>';
          });
      }

      function syncBookDelegateCoachUi() {
        var wrap = document.getElementById('bookDelegateCoachWrap');
        var sel = document.getElementById('bookDelegateCoachSelect');
        if (!wrap || !sel) return;
        var delegate = state.bookContexts && state.bookContexts.delegate;
        var coaches = (delegate && delegate.coaches) || [];
        var show = !!(delegate && coaches.length && state.bookContextKind === 'personal_slot' && state.bookSlotId);
        wrap.style.display = show ? '' : 'none';
        if (!show) return;
        if (!state.bookCollectiveSlug && delegate.collective_slug) {
          state.bookCollectiveSlug = delegate.collective_slug;
        }
        sel.innerHTML = coaches.map(function(c) {
          return (
            '<option value="' + c.trainer_id + '">' +
            escapeHtml(c.display_name || ('Тренер #' + c.trainer_id)) +
            '</option>'
          );
        }).join('');
        var preferred = state.bookDelegateTargetId || state.trainerId || coaches[0].trainer_id;
        sel.value = String(preferred);
        state.bookDelegateTargetId = parseInt(sel.value, 10) || null;
        sel.onchange = function() {
          state.bookDelegateTargetId = parseInt(sel.value, 10) || null;
        };
      }

      function renderBookCenterModePickers() {
        var modeWrap = document.getElementById('bookCenterModeWrap');
        var coachWrap = document.getElementById('bookCenterCoachWrap');
        var modeSel = document.getElementById('bookCenterModeSelect');
        var coachSel = document.getElementById('bookCenterCoachSelect');
        var confirmBtn = document.getElementById('btnBookCenterConfirm');
        var session = state.bookCenterSession;
        if (!session || !modeSel) return;
        var modes = ['lane_self', 'center_coach_individual'];
        modeSel.innerHTML = modes.map(function(m) {
          return '<option value="' + m + '">' + (m === 'lane_self' ? 'Дорожка' : 'С тренером центра') + '</option>';
        }).join('');
        modeWrap.style.display = '';
        if (coachWrap && coachSel) {
          var delegate = state.bookContexts && state.bookContexts.delegate;
          var delegateCoaches = (delegate && delegate.coaches) || [];
          var coaches =
            delegateCoaches.length > 1
              ? delegateCoaches.map(function(c) {
                  if (state.trainerId != null && parseInt(String(c.trainer_id), 10) === parseInt(String(state.trainerId), 10)) {
                    return { trainer_id: c.trainer_id, display_name: 'Я' };
                  }
                  return c;
                })
              : window.TrainerBookingContext
                ? TrainerBookingContext.centerCoachesForStaffBooking(session, state.trainerId)
                : session.assigned_coaches || session.coaches || [];
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

      function submitBookCenterStaffBooking() {
        var clientId = state.bookCenterClientId;
        var session = state.bookCenterSession;
        var modeSel = document.getElementById('bookCenterModeSelect');
        var coachSel = document.getElementById('bookCenterCoachSelect');
        if (!clientId || !session || !modeSel || !state.bookCollectiveSlug) return;
        var payload = {
          collective_slug: state.bookCollectiveSlug,
          session_id: session.id,
          client_id: clientId,
          attendance_mode: modeSel.value,
          guest_count: 0,
        };
        if (modeSel.value.indexOf('coach') >= 0 && coachSel && coachSel.value) {
          var selectedCoachId = parseInt(coachSel.value, 10);
          var actorId = state.trainerId != null ? parseInt(String(state.trainerId), 10) : NaN;
          if (
            state.bookContexts &&
            state.bookContexts.delegate &&
            !isNaN(selectedCoachId) &&
            !isNaN(actorId) &&
            selectedCoachId !== actorId
          ) {
            payload.target_trainer_id = selectedCoachId;
          } else {
            payload.center_coach_id = selectedCoachId;
          }
        }
        fetch(apiUrlWithQuery('/trainer/collective/staff-session-booking'), {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify(payload),
        })
          .then(function(r) {
            return r.json().then(function(d) {
              if (!r.ok) throw new Error((d && d.detail) || 'Ошибка');
              document.getElementById('modalBookClient').style.display = 'none';
              clearBookSlotModalState();
              showToast('Запись в центр создана');
              loadSlots();
            });
          })
          .catch(function(e) { alert(e.message || 'Ошибка'); });
      }

      /**
       * After client picked from roster: load per-client defaults (GET booking-defaults), then show service/tariff/arena.
       * Slot booking: время из слота; площадка — из последней записи клиента (можно сменить), как в hub.
       */
      function proceedBookExistingClient(clientId, clientName) {
        maybeApplyBookContextForClient(clientId, function() {
          if (state.bookContextKind === 'center_session') {
            enterBookCenterFlowForClient(clientId, clientName);
            return;
          }
          enterBookExistingServiceStepFromClient(clientId, clientName);
        });
      }

      function enterBookExistingServiceStepFromClient(clientId, displayNameOrNull, options) {
        options = options || {};
        if (state.bookContextKind === 'center_session') {
          enterBookCenterFlowForClient(clientId, displayNameOrNull);
          return;
        }
        syncBookDelegateCoachUi();
        if (options.fromNewClient !== true) state.bookServiceStepFromNewClient = false;
        state.bookSelectedExistingClientId = clientId;
        state.bookSelectedExistingClientName = (displayNameOrNull || '').trim() || '';

        function applyDefaultsAndShow(defaults) {
          defaults = defaults || {};
          if (!state.bookSelectedExistingClientName) {
            var fn = (defaults.client_first_name || '').trim();
            var ln = (defaults.client_last_name || '').trim();
            state.bookSelectedExistingClientName = (fn + ' ' + ln).trim() || 'Клиент';
          }
          var lead = document.getElementById('bookExistingClientLead');
          if (lead) {
            lead.textContent = options.leadHint
              ? options.leadHint
              : state.bookSelectedExistingClientName +
                ' — услуга, тариф и площадка как в последней записи (можно изменить).';
          }

          var sel = document.getElementById('bookServiceSelect');
          if (state.bookSlotIsGroup && state.bookSlotGroupServiceId != null) {
            state.bookServiceId = state.bookSlotGroupServiceId;
            if (sel) sel.value = String(state.bookServiceId);
          } else {
            var defSid = defaults.service_id != null ? parseInt(defaults.service_id, 10) : NaN;
            var picked = state.bookServiceId;
            if (!isNaN(defSid) && state.bookServices.some(function(s) { return Number(s.id) === defSid; })) {
              picked = defSid;
            }
            state.bookServiceId = picked;
            if (sel && state.bookServiceId != null) sel.value = String(state.bookServiceId);
          }
          if (sel) {
            sel.onchange = function() {
              state.bookServiceId = this.value ? parseInt(this.value, 10) : null;
              syncBookPriceTierRadios('existing', null, null);
            };
          }
          syncBookPriceTierRadios(
            'existing',
            defaults.service_price_variant_id,
            defaults.price_tier_kind
          );
          var arenaPref = defaults.arena_id;
          if (arenaPref == null && state.bookSlotId && !state.bookSlotIsGroup) {
            var slotRow = state.slots.find(function(s) { return s.id === state.bookSlotId; });
            if (slotRow && slotRow.arena_id != null) arenaPref = slotRow.arena_id;
          }
          fillTrainerArenasUI(arenaPref);
          applyBookModalGroupUi();
          showBookExistingServiceStep();
          var modal = document.getElementById('modalBookClient');
          if (modal) modal.scrollTop = 0;
        }

        fetch(
          apiUrlWithQuery('/trainer/clients/' + encodeURIComponent(String(clientId)) + '/booking-defaults'),
          { headers: headers(), cache: 'no-store' }
        )
          .then(function(r) {
            return r.ok ? r.json() : {};
          })
          .then(applyDefaultsAndShow)
          .catch(function() {
            applyDefaultsAndShow({});
          });
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

      /** Match GET booking-defaults tier when variant id is missing or stale (else UI often picks adult first). */
      function resolveQuickBookPriceTierIdFromDefaults(tiers, preferredVariantId, priceTierKind) {
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

      function syncBookPriceTierRadios(which, preferredVariantId, priceTierKind) {
        var wrapE = document.getElementById('bookPriceTierWrapExisting');
        var wrapN = document.getElementById('bookPriceTierWrapNew');
        if (state.bookSlotIsGroup) {
          if (wrapE) wrapE.style.display = 'none';
          if (wrapN) wrapN.style.display = 'none';
          state.bookPriceVariantId = null;
          return;
        }
        var sid = state.bookServiceId;
        var svc = (state.bookServices || []).filter(function(x) { return Number(x.id) === Number(sid); })[0];
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
          var pb = Number(tier.price_byn);
          if (!isFinite(pb)) pb = 0;
          var numStr = pb === Math.floor(pb) ? String(Math.floor(pb)) : pb.toFixed(2);
          var priceFrag = document.createElement('span');
          priceFrag.textContent = numStr + ' BYN';
          lab.appendChild(inp);
          lab.appendChild(document.createTextNode(priceTierLabelRuSe(tier) + ' — '));
          lab.appendChild(priceFrag);
          inp.addEventListener('change', function() {
            state.bookPriceVariantId = parseInt(inp.value, 10);
          });
          host.appendChild(lab);
        });
        var resolved = resolveQuickBookPriceTierIdFromDefaults(tiers, preferredVariantId, priceTierKind);
        var preferredId = resolved != null ? resolved : pickDefaultBookPriceTierId(tiers);
        var pickInp = preferredId != null ? host.querySelector('input[value="' + String(preferredId) + '"]') : null;
        if (pickInp) {
          pickInp.checked = true;
          state.bookPriceVariantId = parseInt(pickInp.value, 10);
        }
      }

      function syncAllBookPriceTierRadios() {
        syncBookPriceTierRadios('existing', null, null);
        syncBookPriceTierRadios('new', null, null);
      }

      /** Price tiers for profile quick-book service modal (same rules as book modal). */
      function syncQuickBookProfilePriceTierRadios(preferredVariantId, priceTierKind) {
        var wrap = document.getElementById('quickBookProfilePriceTierWrap');
        var host = document.getElementById('quickBookProfilePriceTierRadios');
        if (!wrap || !host) return;
        var sid = state.bookServiceId;
        var svc = (state.bookServices || []).filter(function(x) { return Number(x.id) === Number(sid); })[0];
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
          var pb = Number(tier.price_byn);
          if (!isFinite(pb)) pb = 0;
          var numStr = pb === Math.floor(pb) ? String(Math.floor(pb)) : pb.toFixed(2);
          var priceFrag = document.createElement('span');
          priceFrag.textContent = numStr + ' BYN';
          lab.appendChild(inp);
          lab.appendChild(document.createTextNode(priceTierLabelRuSe(tier) + ' — '));
          lab.appendChild(priceFrag);
          inp.addEventListener('change', function() {
            state.bookPriceVariantId = parseInt(inp.value, 10);
          });
          host.appendChild(lab);
        });
        var resolved = resolveQuickBookPriceTierIdFromDefaults(tiers, preferredVariantId, priceTierKind);
        var matched = resolved != null ? host.querySelector('input[value="' + String(resolved) + '"]') : null;
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

      function closeBookingEditServiceModal() {
        var m = document.getElementById('modalBookingEditService');
        if (m) {
          m.style.display = 'none';
          m.setAttribute('aria-hidden', 'true');
        }
        state.bookingEditTargetId = null;
        state.bookingEditFocus = null;
        state.bookingEditLockedServiceId = null;
        state.bookingEditModalBooking = null;
        updateTelegramBack();
      }

      function syncBookingEditPriceTierRadios(preferredVariantId) {
        var wrap = document.getElementById('bookEditPriceTierWrap');
        var host = document.getElementById('bookEditPriceTierRadios');
        if (!wrap || !host) return;
        var sid =
          state.bookingEditLockedServiceId != null
            ? state.bookingEditLockedServiceId
            : state.bookServiceId;
        var tiers = bookingEditTiersForServiceId(sid);
        if (tiers.length <= 1) {
          state.bookPriceVariantId = tiers.length === 1 ? tiers[0].id : null;
          host.innerHTML = '';
          return;
        }
        host.innerHTML = '';
        var gname = 'book_edit_tier_' + String(sid || 0);
        tiers.forEach(function(tier) {
          var lab = document.createElement('label');
          var inp = document.createElement('input');
          inp.type = 'radio';
          inp.name = gname;
          inp.value = String(tier.id);
          lab.appendChild(inp);
          lab.appendChild(document.createTextNode(priceTierLabelRuSe(tier)));
          inp.addEventListener('change', function() {
            state.bookPriceVariantId = parseInt(inp.value, 10);
          });
          host.appendChild(lab);
        });
        var resolved = resolveQuickBookPriceTierIdFromDefaults(tiers, preferredVariantId, null);
        var preferredId = resolved != null ? resolved : pickDefaultBookPriceTierId(tiers);
        var pickInp = preferredId != null ? host.querySelector('input[value="' + String(preferredId) + '"]') : null;
        if (pickInp) {
          pickInp.checked = true;
          state.bookPriceVariantId = parseInt(pickInp.value, 10);
        }
      }

      function openBookingEditServiceModal(booking, focusStep) {
        if (!booking || booking.id == null) return;
        var se = booking.service_edit || {};
        focusStep = normalizeBookingEditFocus(focusStep);
        if (focusStep === 'service' && !se.can_edit_service) return;
        if (focusStep === 'tier' && !se.can_edit_tier) return;
        if (focusStep === 'arena' && !se.can_edit_arena) return;
        if (!se.allowed) {
          showToast(se.reason || 'Запись нельзя изменить');
          return;
        }
        state.bookingEditTargetId = booking.id;
        state.bookingEditFocus = focusStep;
        state.bookingEditModalBooking = booking;
        state.bookingEditLockedServiceId =
          focusStep === 'tier' && booking.service_id != null ? Number(booking.service_id) : null;
        var modal = document.getElementById('modalBookingEditService');
        var sel = document.getElementById('bookEditServiceSelect');
        var arenaSel = document.getElementById('bookEditArenaSelect');
        var saveBtn = document.getElementById('btnBookingEditServiceSave');
        if (!modal) return;
        if (saveBtn) saveBtn.disabled = true;
        if (sel) sel.innerHTML = '';
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
        updateTelegramBack();

        if (focusStep === 'arena') {
          getJsonTrainer('/trainer/my-services')
            .then(function(data) {
              var arenas = data.arenas || [];
              if (arenas.length <= 1) {
                showToast('Добавьте вторую площадку в профиле');
                closeBookingEditServiceModal();
                return;
              }
              if (!arenaSel) {
                closeBookingEditServiceModal();
                return;
              }
              state.trainerArenas = arenas;
              var currentAid =
                booking.arena_id != null
                  ? Number(booking.arena_id)
                  : arenas.filter(function(a) { return a.is_primary; })[0]
                    ? Number(arenas.filter(function(a) { return a.is_primary; })[0].id)
                    : Number(arenas[0].id);
              state.bookingEditArenaId = currentAid;
              arenaSel.innerHTML = '';
              arenas.forEach(function(a) {
                var opt = document.createElement('option');
                opt.value = String(a.id);
                opt.textContent = a.name || '—';
                arenaSel.appendChild(opt);
              });
              arenaSel.value = String(currentAid);
              arenaSel.onchange = function() {
                state.bookingEditArenaId = this.value ? parseInt(this.value, 10) : null;
              };
              applyBookingEditModalLayout(booking, focusStep);
              if (saveBtn) saveBtn.disabled = false;
            })
            .catch(function(e) {
              showToast(e.message || 'Не удалось загрузить площадки');
              closeBookingEditServiceModal();
            });
          return;
        }

        if (!sel) return;
        getJsonTrainer('/trainer/my-services')
          .then(function(data) {
            state.bookServices = data.services || [];
            if (!state.bookServices.length) {
              showToast('Добавьте услугу в профиле');
              closeBookingEditServiceModal();
              return;
            }
            var lockedSid = state.bookingEditLockedServiceId;
            state.bookServiceId =
              lockedSid != null
                ? lockedSid
                : booking.service_id != null &&
                    state.bookServices.some(function(s) { return Number(s.id) === Number(booking.service_id); })
                  ? booking.service_id
                  : state.bookServices[0].id;
            sel.innerHTML = '';
            state.bookServices.forEach(function(s) {
              var opt = document.createElement('option');
              opt.value = String(s.id);
              opt.textContent = s.name || '—';
              sel.appendChild(opt);
            });
            sel.value = String(state.bookServiceId);
            sel.onchange = function() {
              state.bookServiceId = this.value ? parseInt(this.value, 10) : null;
            };
            applyBookingEditModalLayout(booking, focusStep);
            if (focusStep === 'tier') {
              syncBookingEditPriceTierRadios(booking.service_price_variant_id);
            } else {
              state.bookPriceVariantId = null;
            }
            if (saveBtn) saveBtn.disabled = false;
          })
          .catch(function(e) {
            showToast(e.message || 'Не удалось загрузить услуги');
            closeBookingEditServiceModal();
          });
      }

      function saveBookingEditArena() {
        var bid = state.bookingEditTargetId;
        if (bid == null) return;
        var arenaId = state.bookingEditArenaId;
        if (arenaId == null) {
          showToast('Выберите площадку');
          return;
        }
        var saveBtn = document.getElementById('btnBookingEditServiceSave');
        if (saveBtn) saveBtn.disabled = true;
        patchJsonTrainer('/trainer/bookings/' + encodeURIComponent(String(bid)) + '/arena', {
          arena_id: arenaId,
        })
          .then(function(updated) {
            state.selectedBooking = updated;
            closeBookingEditServiceModal();
            showToast('Площадка обновлена');
            openBookingDetail(bid);
          })
          .catch(function(e) {
            showToast(e.message || 'Не удалось сохранить');
          })
          .finally(function() {
            if (saveBtn) saveBtn.disabled = false;
          });
      }

      function saveBookingEditService() {
        if (state.bookingEditFocus === 'arena') {
          saveBookingEditArena();
          return;
        }
        var bid = state.bookingEditTargetId;
        var booking = state.bookingEditModalBooking;
        if (bid == null) return;
        var serviceId =
          state.bookingEditLockedServiceId != null
            ? state.bookingEditLockedServiceId
            : state.bookServiceId != null
              ? state.bookServiceId
              : booking && booking.service_id != null
                ? booking.service_id
                : state.bookServices.length
                  ? state.bookServices[0].id
                  : null;
        if (serviceId == null) {
          showToast('Выберите услугу');
          return;
        }
        var tiers = bookingEditTiersForServiceId(serviceId);
        var variantId = state.bookPriceVariantId;
        if (variantId == null && tiers.length === 1) variantId = tiers[0].id;
        if (state.bookingEditFocus === 'tier' && tiers.length > 1 && variantId == null) {
          showToast('Выберите тариф');
          return;
        }
        if (state.bookingEditFocus === 'service' && tiers.length > 1 && variantId == null) {
          variantId = pickDefaultBookPriceTierId(tiers);
        }
        var payload = { service_id: serviceId };
        if (variantId != null) payload.service_price_variant_id = variantId;
        var saveBtn = document.getElementById('btnBookingEditServiceSave');
        if (saveBtn) saveBtn.disabled = true;
        var toastOk =
          state.bookingEditFocus === 'tier'
            ? 'Тариф обновлён'
            : state.bookingEditFocus === 'service'
              ? 'Услуга обновлена'
              : 'Услуга и тариф обновлены';
        patchJsonTrainer('/trainer/bookings/' + encodeURIComponent(String(bid)) + '/service', payload)
          .then(function(updated) {
            state.selectedBooking = updated;
            closeBookingEditServiceModal();
            showToast(toastOk);
            openBookingDetail(bid);
          })
          .catch(function(e) {
            showToast(e.message || 'Не удалось сохранить');
          })
          .finally(function() {
            if (saveBtn) saveBtn.disabled = false;
          });
      }

      function getMonday(d) {
        const date = new Date(d);
        const day = date.getDay();
        const diff = date.getDate() - day + (day === 0 ? -6 : 1);
        return new Date(date.setDate(diff));
      }

      /** Calendar-anchored Monday (0 = current week, 1 = next) — not the week open in calendar nav. */
      function calendarWeekMonday(offsetWeeks) {
        var mon = getMonday(new Date());
        var off = Number(offsetWeeks) || 0;
        if (off) mon.setDate(mon.getDate() + off * 7);
        return mon;
      }

      function buildCalendarWeekStarts(offsetWeeks, count) {
        var n = Math.max(1, Math.min(Number(count) || 1, 8));
        var startOff = Number(offsetWeeks) || 0;
        var out = [];
        for (var i = 0; i < n; i++) {
          out.push(dateToStr(calendarWeekMonday(startOff + i)));
        }
        return out;
      }

      function formatTemplatePeriodRange(weekStarts) {
        if (!weekStarts || !weekStarts.length) return '—';
        if (weekStarts.length === 1) {
          return formatWeekLabel(new Date(weekStarts[0] + 'T12:00:00'));
        }
        var first = new Date(weekStarts[0] + 'T12:00:00');
        var lastMon = new Date(weekStarts[weekStarts.length - 1] + 'T12:00:00');
        var lastSun = new Date(lastMon);
        lastSun.setDate(lastSun.getDate() + 6);
        var today = new Date();
        today.setHours(0, 0, 0, 0);
        var fmt = function(d) { return d.getDate() + ' ' + MONTHS[d.getMonth()]; };
        var effectiveStart = first < today ? today : first;
        if (effectiveStart > lastSun) return fmt(first) + ' – ' + fmt(lastSun);
        return fmt(effectiveStart) + ' – ' + fmt(lastSun);
      }

      function buildTemplateApplyPeriodOptions() {
        return [
          { label: 'Эта неделя', weeks: buildCalendarWeekStarts(0, 1) },
          { label: 'Следующая', weeks: buildCalendarWeekStarts(1, 1) },
          { label: '2 недели', weeks: buildCalendarWeekStarts(1, 2) },
          { label: '3 недели', weeks: buildCalendarWeekStarts(1, 3) },
          { label: '4 недели', weeks: buildCalendarWeekStarts(1, 4) },
        ];
      }

      function renderTemplateApplySheetOptions() {
        var host = document.getElementById('templateApplyOptions');
        if (!host) return;
        var options = buildTemplateApplyPeriodOptions();
        var html = '';
        options.forEach(function(opt, idx) {
          if (idx === 2) {
            html += '<div class="template-apply-options__divider" role="separator" aria-hidden="true"></div>';
          }
          var range = formatTemplatePeriodRange(opt.weeks);
          html +=
            '<button type="button" class="template-apply-option" data-week-idx="' +
            idx +
            '" role="option">' +
            '<span class="template-apply-option__label">' +
            escapeHtml(opt.label) +
            '</span>' +
            '<span class="template-apply-option__range">' +
            escapeHtml(range) +
            '</span>' +
            '<span class="template-apply-option__chev" aria-hidden="true">›</span>' +
            '</button>';
        });
        host.innerHTML = html;
        host.querySelectorAll('.template-apply-option').forEach(function(btn) {
          btn.onclick = function() {
            var idx = parseInt(btn.getAttribute('data-week-idx'), 10);
            if (!options[idx] || !options[idx].weeks) return;
            onTemplateApplyPeriodPick(options[idx].weeks);
          };
        });
      }

      function closeTemplateApplySheet() {
        var modal = document.getElementById('modalTemplateApply');
        if (modal) {
          modal.style.display = 'none';
          modal.setAttribute('aria-hidden', 'true');
        }
        updateTelegramBack();
      }

      function openTemplateApplySheet() {
        renderTemplateApplySheetOptions();
        var modal = document.getElementById('modalTemplateApply');
        if (!modal) return;
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
        updateTelegramBack();
      }

      function onTemplateApplyPeriodPick(weekStarts) {
        if (!assertScheduleCrmWriteAllowed()) return;
        closeTemplateApplySheet();
        if (!weekStarts || !weekStarts.length) return;
        showToast('Применяем…', 1400);
        applyTemplateToWeeks(weekStarts);
      }

      function applyTemplateToWeeks(weekStarts) {
        var weeks = Array.isArray(weekStarts) ? weekStarts.slice() : [];
        if (!weeks.length) return;
        var idx = 0;
        var totalSlots = 0;
        var trainerId = null;
        function finishOk() {
          if (totalSlots > 0 && trainerId) markScheduleEditorHubFillSlotsRhythmBoost(trainerId);
          var toastMsg = weeks.length > 1
            ? 'Шаблон применён на ' + weeks.length + ' нед. Создано слотов: ' + totalSlots
            : 'Шаблон применён. Создано слотов: ' + totalSlots;
          showToast(toastMsg, weeks.length > 1 ? 3400 : 2800);
          if (weeks.length === 1) {
            setTimeout(function() {
              showFirstApplyWeekShareToastIfNeeded(trainerId);
            }, 2600);
          }
          loadSlots();
          state.applyWeekStarts = null;
          state.applyWeekStart = null;
        }
        function step() {
          if (idx >= weeks.length) {
            finishOk();
            return;
          }
          fetch(apiUrlWithQuery('/schedule/apply-week'), {
            method: 'POST',
            headers: headers(),
            body: JSON.stringify({ week_start: weeks[idx] }),
          })
            .then(function(r) { return r.json().then(function(data) { return { ok: r.ok, data: data }; }); })
            .then(function(res) {
              if (!res.ok || !res.data.ok) {
                var err = (res.data && res.data.detail) || 'Ошибка';
                showToast(typeof err === 'string' ? err : 'Не удалось применить шаблон');
                state.applyWeekStarts = null;
                state.applyWeekStart = null;
                if (idx > 0) loadSlots();
                return;
              }
              totalSlots += res.data.slots_created != null ? res.data.slots_created : 0;
              trainerId = res.data.trainer_id || trainerId;
              idx += 1;
              step();
            })
            .catch(function() {
              showToast('Ошибка сети');
              state.applyWeekStarts = null;
              state.applyWeekStart = null;
              if (idx > 0) loadSlots();
            });
        }
        step();
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

      /** Same as formatDateKey but without weekday — when day name is shown separately (e.g. day-pick list). */
      function formatDateKeyNoWeekday(dateStr) {
        const d = new Date(dateStr + 'T12:00:00');
        return d.getDate() + '.' + String(d.getMonth() + 1).padStart(2, '0');
      }

      /** Russian plural for «N слот(а/ов)» — used in day-pick rows. */
      function ruSlotCountLabel(n) {
        n = Math.max(0, parseInt(String(n), 10) || 0);
        var mod100 = n % 100;
        var mod10 = n % 10;
        var w = 'слотов';
        if (mod100 < 11 || mod100 > 14) {
          if (mod10 === 1) w = 'слот';
          else if (mod10 >= 2 && mod10 <= 4) w = 'слота';
        }
        return String(n) + ' ' + w;
      }

      /**
       * Slots already on the calendar for this date, matching current add-slots intent (individual vs group).
       * Mirrors openEditCalendarDay filters: no training_group rows, not cancelled.
       */
      function countExistingSlotsForDayPick(dateStr) {
        if (slotIntentUseCenterUi()) {
          var sessions = (state.centerScheduleAdmin && state.centerScheduleAdmin.sessions) || [];
          var nCenter = 0;
          for (var ci = 0; ci < sessions.length; ci++) {
            if (String(sessions[ci].slot_date) === String(dateStr)) nCenter++;
          }
          return nCenter;
        }
        var useGroup = slotIntentUseGroupUi();
        var rows = state.slots || [];
        var n = 0;
        for (var i = 0; i < rows.length; i++) {
          var s = rows[i];
          if (s.slot_date !== dateStr) continue;
          if (s.training_group_id) continue;
          if (String(s.status || '').toLowerCase() === 'cancelled') continue;
          var c = s.capacity != null ? parseInt(String(s.capacity), 10) : 1;
          if (isNaN(c)) c = 1;
          if (useGroup) {
            if (c > 1) n++;
          } else {
            if (c <= 1) n++;
          }
        }
        return n;
      }

      /** Hide grid starts already before now — «Добавить слоты» is future-facing only (local clock). */
      function isCalendarSlotStartInPast(slotDateStr, minuteOfDay) {
        if (!slotDateStr) return false;
        var parts = String(slotDateStr).slice(0, 10).split('-');
        if (parts.length !== 3) return false;
        var y = parseInt(parts[0], 10);
        var mo = parseInt(parts[1], 10) - 1;
        var d = parseInt(parts[2], 10);
        if (isNaN(y) || isNaN(mo) || isNaN(d)) return false;
        var mm = parseInt(minuteOfDay, 10);
        if (isNaN(mm)) return false;
        var hh = Math.floor(mm / 60);
        var min = mm % 60;
        return new Date(y, mo, d, hh, min, 0, 0).getTime() < Date.now();
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
        if (!isNaN(d) && d >= 15) return d;
        if (row && row.start_time != null && row.end_time != null) {
          var sm = parseStartToMinutes(row.start_time);
          var em = parseStartToMinutes(row.end_time);
          if (!isNaN(sm) && !isNaN(em) && em > sm) return em - sm;
        }
        return 45;
      }

      /** Most frequent integer in list (tie-break: first among max count); empty → null. */
      function mostFrequentInt(values) {
        if (!values || !values.length) return null;
        var freq = {};
        values.forEach(function(v) {
          var k = String(v);
          freq[k] = (freq[k] || 0) + 1;
        });
        var bestKey = String(values[0]);
        var bestC = 0;
        Object.keys(freq).forEach(function(k) {
          if (freq[k] > bestC) {
            bestC = freq[k];
            bestKey = k;
          }
        });
        return parseInt(bestKey, 10);
      }

      /** Calendar slot row at this day's start minute (individual flow excludes group-generated rows). */
      function calendarSlotRowByStartMinute(sm) {
        if (state.editMode !== 'calendar' || !state.editDate) return null;
        var rows = state.slots || [];
        for (var i = 0; i < rows.length; i++) {
          var s = rows[i];
          if (s.slot_date !== state.editDate || s.training_group_id) continue;
          if (parseStartToMinutes(s.start_time) === sm) return s;
        }
        return null;
      }

      function templateSlotRowByStartMinute(sm) {
        if (state.editMode !== 'template' || state.editDay == null) return null;
        var tpl = state.templates || [];
        for (var j = 0; j < tpl.length; j++) {
          var t = tpl[j];
          if (t.day_of_week !== state.editDay) continue;
          if (parseStartToMinutes(t.start_time) === sm) return t;
        }
        return null;
      }

      /** Wall duration for an anchor already on screen: prefer stored row, else current editor duration. */
      function durationMinutesForSelectedStart(sm) {
        var cal = calendarSlotRowByStartMinute(sm);
        if (cal != null) return slotDurationFromRow(cal);
        var te = templateSlotRowByStartMinute(sm);
        if (te != null) return slotDurationFromRow(te);
        return getEditDurationMinutes();
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
          hour_start: 6,
          hour_end: 23,
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
          if (isNaN(sm) || sm < 10) sm = 15;
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
          for (var h = h0; h <= h1; h++) {
            out.push(h * 60 + mo);
          }
        } else if (kind === 'uniform_step') {
          var step = parseInt(preset.step_minutes, 10);
          if (isNaN(step) || step < 10) step = 15;
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
          if (isNaN(sm) || sm < 10) sm = 15;
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

      /** Calendar baseline slot without booking — tap again on chip to remove from day (bookings stay locked). */
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
      function pruneSelectedStartsForOverlap(_unusedEditorDurationHint) {
        var sorted = Array.from(state.selectedStarts).sort(function(a, b) {
          return a - b;
        });
        var kept = new Set();
        sorted.forEach(function(m) {
          if (state.lockedStarts.has(m) || isMinutePinnedBaseline(m)) {
            kept.add(m);
            return;
          }
          var dNew = durationMinutesForSelectedStart(m);
          var conflict = false;
          kept.forEach(function(s) {
            var dKept = durationMinutesForSelectedStart(s);
            if (intervalsOverlapMin(s, dKept, m, dNew)) conflict = true;
          });
          if (!conflict) kept.add(m);
        });
        state.selectedStarts = kept;
      }

      /**
       * Start minute overlaps another anchored slot's wall span — not usable as another start for candidateDur.
       * Also checks precise off-grid slots so grid chips are visually blocked by them.
       */
      function classifyIntervalConsumptionBlock(candidateSm, candidateDur) {
        var hasBookingOverlap = false;
        var hasSelectionOverlap = false;
        state.selectedStarts.forEach(function(anchor) {
          var anchorDur = durationMinutesForSelectedStart(anchor);
          if (candidateSm === anchor) return;
          if (!intervalsOverlapMin(anchor, anchorDur, candidateSm, candidateDur)) return;
          if (state.lockedStarts.has(anchor)) hasBookingOverlap = true;
          else hasSelectionOverlap = true;
        });
        // Precise slots also block grid chips
        (state.preciseSlots || []).forEach(function(ps) {
          if (!intervalsOverlapMin(ps.startMinutes, ps.durationMinutes, candidateSm, candidateDur)) return;
          hasSelectionOverlap = true;
        });
        if (hasBookingOverlap) return 'booking';
        if (hasSelectionOverlap) return 'selection';
        return null;
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
        else {
          teardownScheduleCalendarScrollSpy();
          loadTemplates();
        }
        syncScheduleEditorFormatChrome();
        updateTelegramBack();
        syncScheduleWeekDayStripVisibility();
      }

      document.querySelectorAll('.tab').forEach(function(t) {
        t.onclick = function() {
          if (t.dataset.tab === state.tab) return;
          setActiveTab(t.dataset.tab);
        };
      });

      function showMain(opts) {
        opts = opts || {};
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
        else if (!opts.skipTemplateReload) loadTemplates(opts.templateLoadOpts || {});
        state.slotEditIntent = null;
        state.pendingIntentFlow = null;
        state.pendingTemplateDay = null;
        state.calendarBaselineStarts = null;
        state.calendarBaselinePreciseKeys = null;
        state.scheduleGridArenaPickId = null;
        updateTelegramBack();
        syncScheduleWeekDayStripVisibility();
        syncScheduleEditorFormatChrome();
      }

      function isGroupClassesFeatureEnabled() {
        return !!state.groupClassesEnabled;
      }

      /** Group-only editor controls are visible only for explicit "group" intent. */
      function slotIntentUseGroupUi() {
        return isGroupClassesFeatureEnabled() && state.slotEditIntent === 'group';
      }

      function hasCenterScheduleAdmin() {
        var admin = state.centerScheduleAdmin;
        return !!(admin && admin.collective_slug && (admin.coaches || []).length);
      }

      function scheduleEditorOrgCaps() {
        var admin = state.centerScheduleAdmin;
        if (admin && admin.capabilities) return admin.capabilities;
        if (
          window.TrainerMiniAppShell &&
          typeof window.TrainerMiniAppShell.organizationCapabilities === 'function'
        ) {
          return window.TrainerMiniAppShell.organizationCapabilities() || null;
        }
        return null;
      }

      /** Owner/admin with both personal CRM and center grid (center_hybrid or center owner who coaches). */
      function scheduleEditorDualContour() {
        var caps = scheduleEditorOrgCaps();
        if (caps) return !!(caps.show_personal_crm && caps.show_center_grid);
        return hasCenterScheduleAdmin();
      }

      /** Facility operator: center grid only, no personal schedule UX in this editor. */
      function scheduleEditorCenterOperatorOnly() {
        var caps = scheduleEditorOrgCaps();
        if (caps) return !!(caps.show_center_grid && !caps.show_personal_crm);
        return false;
      }

      function scheduleEditorPersonalOverlapEnabled() {
        return scheduleEditorDualContour();
      }

      function syncScheduleEditorFormatChrome() {
        var personal = document.getElementById('personalTemplateSection');
        var tabTpl = document.getElementById('tabTemplateNav');
        var addBtn = document.getElementById('btnAddSlots');
        var centerOnly = scheduleEditorCenterOperatorOnly();
        var dual = scheduleEditorDualContour();
        if (personal) personal.hidden = centerOnly;
        if (tabTpl) {
          tabTpl.textContent = centerOnly && hasCenterScheduleAdmin() ? 'Сетка центра' : 'Шаблон недели';
        }
        if (addBtn) {
          addBtn.textContent = centerOnly
            ? '➕ Добавить окна центра'
            : dual
              ? '➕ Добавить слоты'
              : '➕ Добавить слоты на неделю';
        }
      }

      function shouldOpenSlotIntentModal() {
        if (scheduleEditorCenterOperatorOnly()) return false;
        if (scheduleEditorDualContour()) return isGroupClassesFeatureEnabled() || hasCenterScheduleAdmin();
        return isGroupClassesFeatureEnabled();
      }

      function startAddSlotsFlow() {
        if (scheduleEditorCenterOperatorOnly()) {
          state.slotEditIntent = 'center';
          showDayPickScreen();
          return;
        }
        if (shouldOpenSlotIntentModal()) {
          openSlotIntentModal('calendar', null, 'individual');
          return;
        }
        state.slotEditIntent = 'individual';
        showDayPickScreen();
      }

      function slotIntentUseCenterUi() {
        return hasCenterScheduleAdmin() && state.slotEditIntent === 'center';
      }

      function centerSessionsForEditDate() {
        var admin = state.centerScheduleAdmin;
        if (!admin || !state.editDate) return [];
        return (admin.sessions || []).filter(function(s) {
          return String(s.slot_date) === String(state.editDate);
        });
      }

      function centerSessionByStartMinute(minute) {
        var sessions = centerSessionsForEditDate();
        for (var i = 0; i < sessions.length; i++) {
          if (parseStartToMinutes(sessions[i].start_time) === minute) return sessions[i];
        }
        return null;
      }

      /** Owner's personal slots on the day being edited (center grid context overlay). */
      function ownerPersonalSlotIntervalsForCenterEdit() {
        if (!state.editDate) return [];
        var dateStr = String(state.editDate);
        return (state.slots || [])
          .filter(function(s) {
            if (String(s.slot_date) !== dateStr) return false;
            if (s.training_group_id) return false;
            if (String(s.status || '').toLowerCase() === 'cancelled') return false;
            var cap = s.capacity != null ? parseInt(String(s.capacity), 10) : 1;
            return !isNaN(cap) && cap <= 1;
          })
          .map(function(s) {
            var sm = parseStartToMinutes(s.start_time);
            var em = parseStartToMinutes(s.end_time);
            return {
              startMin: sm,
              endMin: em > sm ? em : sm + (state.defaultSlotDurationMinutes || 45),
              start_time: s.start_time,
              end_time: s.end_time,
            };
          });
      }

      function centerPersonalOverlapAtMinute(candidateSm, candidateDur) {
        var intervals = ownerPersonalSlotIntervalsForCenterEdit();
        for (var i = 0; i < intervals.length; i++) {
          var iv = intervals[i];
          var ivDur = Math.max(15, iv.endMin - iv.startMin);
          if (intervalsOverlapMin(iv.startMin, ivDur, candidateSm, candidateDur)) return iv;
        }
        return null;
      }

      function centerEditSelfOnShift() {
        var picked = ensureCenterEditCoachIds();
        var selfId = state.trainerId != null ? parseInt(String(state.trainerId), 10) : null;
        return selfId != null && !isNaN(selfId) && picked.has(selfId);
      }

      function centerEditSelfOnlyOnShift() {
        var picked = ensureCenterEditCoachIds();
        return picked.size === 1 && centerEditSelfOnShift();
      }

      /** Selected center windows that overlap owner's personal slots while «Я» is on shift. */
      function centerEditSelfPersonalOverlapIssues() {
        if (!scheduleEditorPersonalOverlapEnabled()) return [];
        if (!slotIntentUseCenterUi() || !centerEditSelfOnShift()) return [];
        var dur = getEditDurationMinutes();
        var issues = [];
        state.selectedStarts.forEach(function(m) {
          var ov = centerPersonalOverlapAtMinute(m, dur);
          if (ov) {
            issues.push({ centerMinute: m, personal: ov });
          }
        });
        return issues.sort(function(a, b) {
          return a.centerMinute - b.centerMinute;
        });
      }

      function syncCenterEditOverlapWarn() {
        var el = document.getElementById('centerEditOverlapWarn');
        if (!el) return;
        if (!slotIntentUseCenterUi() || !scheduleEditorPersonalOverlapEnabled()) {
          el.hidden = true;
          el.textContent = '';
          return;
        }
        var issues = centerEditSelfPersonalOverlapIssues();
        if (!issues.length) {
          el.hidden = true;
          el.textContent = '';
          return;
        }
        el.hidden = false;
        if (centerEditSelfOnlyOnShift()) {
          el.className = 'center-edit-overlap-warn center-edit-overlap-warn--block';
          el.textContent =
            'На смене только вы, но выбранные часы пересекаются с личными слотами. Добавьте другого тренера на смену, снимите «Я» или уберите личное время.';
        } else {
          el.className = 'center-edit-overlap-warn center-edit-overlap-warn--info';
          el.textContent =
            'Есть пересечение с вашими личными слотами — клиенты центра в эти часы пойдут на других тренеров смены.';
        }
      }

      function centerEditSaveBlockedByPersonalOverlap() {
        return centerEditSelfOnlyOnShift() && centerEditSelfPersonalOverlapIssues().length > 0;
      }

      function resetCenterEditCoachIds() {
        state.centerEditCoachIds = null;
      }

      function ensureCenterEditCoachIds() {
        if (state.centerEditCoachIds instanceof Set) return state.centerEditCoachIds;
        var picked = new Set();
        centerSessionsForEditDate().forEach(function(s) {
          (s.assigned_coaches || []).forEach(function(c) {
            var id = parseInt(String(c.trainer_id), 10);
            if (!isNaN(id)) picked.add(id);
          });
        });
        state.centerEditCoachIds = picked;
        return picked;
      }

      function renderCenterEditCoachChips() {
        var host = document.getElementById('centerEditCoachChips');
        var admin = state.centerScheduleAdmin;
        if (!host || !admin) return;
        var coaches = admin.coaches || [];
        var picked = ensureCenterEditCoachIds();
        if (host.childElementCount !== coaches.length) {
          host.innerHTML = '';
        }
        if (!host.childElementCount) {
          host.innerHTML = coaches
            .map(function(c) {
              var id = parseInt(String(c.trainer_id), 10);
              var on = picked.has(id);
              var isSelf = state.trainerId != null && id === parseInt(String(state.trainerId), 10);
              return (
                '<button type="button" class="center-coach-chip' +
                (on ? ' is-selected' : '') +
                '" data-coach-id="' +
                id +
                '">' +
                escapeHtml(isSelf ? 'Я' : c.display_name || 'Тренер #' + id) +
                '</button>'
              );
            })
            .join('');
          host.querySelectorAll('.center-coach-chip').forEach(function(btn) {
            btn.onclick = function() {
              var id = parseInt(btn.getAttribute('data-coach-id'), 10);
              if (picked.has(id)) {
                picked.delete(id);
              } else {
                picked.add(id);
              }
              host.querySelectorAll('.center-coach-chip').forEach(function(chip) {
                var cid = parseInt(chip.getAttribute('data-coach-id'), 10);
                chip.classList.toggle('is-selected', picked.has(cid));
              });
              renderHourGrid();
              syncCenterEditOverlapWarn();
              updateEditDoneButton();
            };
          });
          return;
        }
        host.querySelectorAll('.center-coach-chip').forEach(function(chip) {
          var cid = parseInt(chip.getAttribute('data-coach-id'), 10);
          chip.classList.toggle('is-selected', picked.has(cid));
        });
      }

      function syncCenterEditChrome() {
        var useCenter = slotIntentUseCenterUi();
        var coachWrap = document.getElementById('centerEditCoachWrap');
        var capWrap = document.getElementById('slotCapacityWrap');
        var capInput = document.getElementById('slotCapacityInput');
        var capLabel = capWrap ? capWrap.querySelector('.slot-flow-label') : null;
        var switcher = document.getElementById('slotAddModeSwitcher');
        var preciseForm = document.getElementById('preciseSlotForm');
        var preciseAdded = document.getElementById('preciseSlotsAdded');
        var cgw = document.getElementById('calendarGroupServiceWrap');
        var caw = document.getElementById('calendarGroupArenaWrap');
        var gridLabel = document.getElementById('scheduleTimeGridLabel');
        var gridHint = document.getElementById('scheduleTimeGridHint');
        var centerTitle = document.getElementById('slotIntentCenterTitle');
        var admin = state.centerScheduleAdmin;
        if (centerTitle && admin && admin.collective_name) {
          centerTitle.textContent = admin.collective_name + ' · смена';
        }
        if (coachWrap) coachWrap.hidden = !useCenter;
        if (gridLabel) gridLabel.textContent = useCenter ? 'Начало окна' : 'Начало слота';
        if (gridHint) {
          gridHint.textContent = useCenter
            ? scheduleEditorPersonalOverlapEnabled()
              ? 'Тренеры на смене — опционально: без них окно для дорожки. Оранжевый контур — ваши личные слоты.'
              : 'Тренеры на смене — опционально. Без них — запись на дорожку.'
            : 'Слева — час, справа четверти (:00 … :45)';
        }
        if (capLabel) capLabel.textContent = useCenter ? 'Мест в окне' : 'Мест в слоте';
        if (useCenter) {
          if (capWrap) capWrap.style.display = 'block';
          if (capInput) {
            capInput.setAttribute('min', '1');
            if (!capInput.value || parseInt(capInput.value, 10) < 1) capInput.value = '1';
          }
          if (switcher) switcher.style.display = 'none';
          if (preciseForm) preciseForm.style.display = 'none';
          if (preciseAdded) preciseAdded.style.display = 'none';
          if (cgw) cgw.style.display = 'none';
          if (caw) caw.style.display = 'none';
          renderCenterEditCoachChips();
          syncCenterEditOverlapWarn();
        } else {
          var warnEl = document.getElementById('centerEditOverlapWarn');
          if (warnEl) {
            warnEl.hidden = true;
            warnEl.textContent = '';
          }
        }
      }

      function saveCenterCalendarDay(startsSorted, durationMinutes) {
        var admin = state.centerScheduleAdmin;
        if (!admin || !admin.collective_slug || !state.editDate) {
          showToast('Нет данных центра');
          return;
        }
        var coachIds = Array.from(ensureCenterEditCoachIds()).filter(function(id) {
          return !isNaN(id);
        });
        if (centerEditSaveBlockedByPersonalOverlap()) {
          showToast('На смене только вы — уберите пересечение с личными слотами');
          return;
        }
        var capRaw = parseInt(document.getElementById('slotCapacityInput').value, 10);
        var capacity = isNaN(capRaw) || capRaw < 1 ? 1 : Math.min(500, capRaw);
        var baseline = state.calendarBaselineStarts || new Set();
        var selected = new Set(startsSorted);
        var newStarts = startsSorted.filter(function(m) {
          return !baseline.has(m);
        });
        var removed = [];
        baseline.forEach(function(m) {
          if (!selected.has(m) && !state.lockedStarts.has(m)) removed.push(m);
        });
        if (!newStarts.length && !removed.length) return;
        var postUrl =
          apiUrlWithQuery('/trainer/collective/sessions?collective_slug=' + encodeURIComponent(admin.collective_slug));
        var tasks = [];
        newStarts.forEach(function(m) {
          tasks.push(
            fetch(postUrl, {
              method: 'POST',
              headers: headers(),
              body: JSON.stringify({
                slot_date: state.editDate,
                start_time: formatMinuteClock(m),
                end_time: formatMinuteClock(m + durationMinutes),
                capacity: capacity,
                coach_trainer_ids: coachIds,
              }),
            }).then(function(r) {
              return r.json().then(function(d) {
                if (!r.ok) throw new Error((d && d.detail) || 'create_failed');
              });
            })
          );
        });
        removed.forEach(function(m) {
          var sess = centerSessionByStartMinute(m);
          if (!sess || !sess.id) return;
          tasks.push(
            fetch(
              apiUrlWithQuery(
                '/trainer/collective/sessions/' +
                  encodeURIComponent(String(sess.id)) +
                  '?collective_slug=' +
                  encodeURIComponent(admin.collective_slug)
              ),
              { method: 'DELETE', headers: headers() }
            ).then(function(r) {
              return r.json().then(function(d) {
                if (!r.ok) throw new Error((d && d.detail) || 'delete_failed');
              });
            })
          );
        });
        Promise.all(tasks)
          .then(function() {
            var msg =
              newStarts.length && removed.length
                ? 'Смена центра обновлена'
                : newStarts.length === 1
                  ? 'Добавлено окно центра'
                  : newStarts.length > 1
                    ? 'Добавлено окон: ' + newStarts.length
                    : 'Окно центра снято';
            showToast(msg);
            finishCenterCalendarEdit({ refreshCenterGrid: true });
          })
          .catch(function(e) {
            showToast(e.message || 'Не удалось сохранить смену');
            loadSlots();
          });
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
        if (!assertScheduleCrmWriteAllowed()) return;
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
        var centerBtn = document.getElementById('btnSlotIntentCenter');
        var indTitle = document.getElementById('slotIntentIndividualTitle');
        var showCenter = hasCenterScheduleAdmin() && flow !== 'template' && scheduleEditorDualContour();
        if (grp) {
          grp.style.display = isGroupClassesFeatureEnabled() ? '' : 'none';
        }
        if (centerBtn) centerBtn.hidden = !showCenter;
        if (indTitle) indTitle.textContent = showCenter ? 'Мои часы' : 'Индивидуальные';
        var centerTitle = document.getElementById('slotIntentCenterTitle');
        var admin = state.centerScheduleAdmin;
        if (centerTitle && admin && admin.collective_name) {
          centerTitle.textContent = admin.collective_name + ' · смена';
        }
        if (ind) ind.classList.remove('is-suggested');
        if (grp) grp.classList.remove('is-suggested');
        if (centerBtn) centerBtn.classList.remove('is-suggested');
        var centerHint = document.getElementById('slotIntentCenterHint');
        if (centerHint) {
          centerHint.textContent = 'Окно для клиентов центра. Личные слоты остаются отдельно.';
        }
        if (suggestedIntent === 'group') {
          if (grp) grp.classList.add('is-suggested');
        } else if (ind) {
          ind.classList.add('is-suggested');
        }
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
        updateTelegramBack();
      }

      /** True when calendar day edit has something to save: new starts, removed free baseline slots, or precise slots. */
      function hasCalendarNewSlotSelection() {
        if (state.editMode !== 'calendar' || !state.calendarBaselineStarts) return true;
        if ((state.preciseSlots || []).length > 0) return true;
        var base = state.calendarBaselineStarts;
        var hasNew = false;
        state.selectedStarts.forEach(function(m) {
          if (!base.has(m)) hasNew = true;
        });
        var removedFreeBaseline = false;
        base.forEach(function(m) {
          if (!state.lockedStarts.has(m) && !state.selectedStarts.has(m)) removedFreeBaseline = true;
        });
        return hasNew || removedFreeBaseline;
      }

      function updateEditDoneButton() {
        var btn = document.getElementById('editDone');
        if (!btn) return;
        if (state.editMode === 'calendar' && state.calendarBaselineStarts) {
          var ok = hasCalendarNewSlotSelection();
          if (slotIntentUseCenterUi() && centerEditSaveBlockedByPersonalOverlap()) {
            ok = false;
          }
          btn.disabled = !ok;
          btn.title = ok
            ? ''
            : slotIntentUseCenterUi() && centerEditSaveBlockedByPersonalOverlap()
              ? 'На смене только вы — уберите пересечение с личными слотами'
              : 'Добавьте время, уберите свободный слот или сохраните точное время';
        } else {
          btn.disabled = false;
          btn.title = '';
        }
      }

      // ─── Precise slot mode ────────────────────────────────────────────────────
      // Stepper-driven time picker + day-glance timeline + free-gap suggestions
      // + live conflict-aware preview. Designed for single-tap creation of
      // off-grid slots when the 15-minute «Быстро» grid is too coarse.

      /** Stable identity for calendar precise rows when diffing editor-open baseline vs current (toast counts). */
      function calendarPreciseSlotStableKey(ps) {
        if (!ps) return '';
        var aid = ps.arenaId != null && !isNaN(Number(ps.arenaId)) ? String(Number(ps.arenaId)) : '';
        return String(ps.startMinutes) + '|' + String(ps.durationMinutes) + '|' + aid;
      }

      /**
       * Returns total interval minutes for all grid-selected + precise slots as [start, end] pairs.
       * Used for cross-mode overlap detection.
       */
      function allEditIntervals() {
        var pairs = [];
        var gridDur = getEditDurationMinutes();
        state.selectedStarts.forEach(function(m) {
          pairs.push([m, m + gridDur]);
        });
        (state.preciseSlots || []).forEach(function(ps) {
          pairs.push([ps.startMinutes, ps.startMinutes + ps.durationMinutes]);
        });
        return pairs;
      }

      /** Check whether a proposed [startM, endM) interval overlaps any existing edit interval. */
      function preciseIntervalOverlapsAny(startM, endM, skipPreciseIdx) {
        var gridDur = getEditDurationMinutes();
        var conflict = null;
        // Check grid-selected starts
        state.selectedStarts.forEach(function(m) {
          if (conflict) return;
          if (intervalsOverlapMin(m, gridDur, startM, endM - startM)) {
            conflict = state.lockedStarts.has(m) ? 'booking' : 'grid';
          }
        });
        if (conflict) return conflict;
        // Check already-added precise slots
        (state.preciseSlots || []).forEach(function(ps, idx) {
          if (conflict || idx === skipPreciseIdx) return;
          if (intervalsOverlapMin(ps.startMinutes, ps.durationMinutes, startM, endM - startM)) {
            conflict = 'precise';
          }
        });
        // Check booked/locked baseline slots from the day that are not in the grid
        state.lockedStarts.forEach(function(m) {
          if (conflict || state.selectedStarts.has(m)) return;
          if (intervalsOverlapMin(m, gridDur, startM, endM - startM)) conflict = 'booking';
        });
        return conflict;
      }

      function parsePreciseDraftMinutes() {
        var h = parseInt(document.getElementById('preciseStartH').value, 10);
        var m = parseInt(document.getElementById('preciseStartM').value, 10);
        if (isNaN(h) || isNaN(m) || h < 0 || h > 23 || m < 0 || m > 59) return null;
        return h * 60 + m;
      }

      function getPreciseDraftDuration() {
        var chips = document.getElementById('preciseDurChips');
        if (!chips) return state.preciseDraftDuration || 45;
        var active = chips.querySelector('.precise-dur-chip.selected');
        if (!active) return state.preciseDraftDuration || 45;
        var v = active.dataset.dur;
        if (v === 'custom') {
          var ci = parseInt(document.getElementById('preciseDurCustom').value, 10);
          return (isNaN(ci) || ci < 15) ? 45 : Math.min(480, ci);
        }
        return parseInt(v, 10) || 45;
      }

      /** Visible day window from arena schedule preset (e.g. 06:00–24:00 — endHour exclusive). */
      function getPreciseDayWindow() {
        var preset = state.scheduleGridPreset || defaultScheduleGridPreset();
        var h0 = Math.max(0, Math.min(23, parseInt(preset.hour_start, 10)));
        if (isNaN(h0)) h0 = 6;
        var h1 = Math.max(0, Math.min(23, parseInt(preset.hour_end, 10)));
        if (isNaN(h1)) h1 = 23;
        if (h1 < h0) { var x = h0; h0 = h1; h1 = x; }
        var startMin = h0 * 60;
        var endMin = (h1 + 1) * 60; /* inclusive last hour */
        if (endMin > 24 * 60) endMin = 24 * 60;
        return { startMin: startMin, endMin: endMin, hourStart: h0, hourEndIncl: h1 };
      }

      /**
       * Collects every "busy" interval that should be visible on the day timeline:
       * existing booked slots, currently-selected grid slots (will become slots after save),
       * already-added precise slots. Sorted by start.
       * kind: 'booked' | 'slot' | 'precise'
       */
      function collectPreciseDayBusyIntervals() {
        if (state.editMode === 'calendar' && state.editDate) {
          var gridDur = getEditDurationMinutes();
          var rows = (state.slots || []).filter(function(s) {
            return s.slot_date === state.editDate && !s.training_group_id;
          });
          var byStart = new Map();
          rows.forEach(function(s) {
            var sm = parseStartToMinutes(s.start_time);
            var dur = slotDurationFromRow(s);
            var occ = (s.active_bookings != null) ? parseInt(s.active_bookings, 10) : 0;
            var booked = (s.status || '') === 'booked' || occ > 0;
            byStart.set(sm, { startMin: sm, endMin: sm + dur, kind: booked ? 'booked' : 'slot' });
          });
          state.selectedStarts.forEach(function(m) {
            if (!byStart.has(m)) {
              byStart.set(m, { startMin: m, endMin: m + gridDur, kind: 'slot' });
            }
          });
          state.lockedStarts.forEach(function(m) {
            if (!byStart.has(m)) {
              byStart.set(m, { startMin: m, endMin: m + gridDur, kind: 'booked' });
            }
          });
          var out = Array.from(byStart.values());
          (state.preciseSlots || []).forEach(function(ps) {
            var dup = rows.some(function(s) {
              var capR = (s.capacity != null) ? parseInt(s.capacity, 10) : 1;
              if (isNaN(capR) || capR > 1) return false;
              return (
                parseStartToMinutes(s.start_time) === ps.startMinutes &&
                slotDurationFromRow(s) === ps.durationMinutes
              );
            });
            if (!dup) {
              out.push({
                startMin: ps.startMinutes,
                endMin: ps.startMinutes + ps.durationMinutes,
                kind: 'precise',
              });
            }
          });
          out.sort(function(a, b) { return a.startMin - b.startMin || a.endMin - b.endMin; });
          return out;
        }
        if (state.editMode === 'template' && state.editDay != null && !slotIntentUseGroupUi()) {
          var gridDurT = getEditDurationMinutes();
          var outT = [];
          state.selectedStarts.forEach(function(m) {
            outT.push({ startMin: m, endMin: m + gridDurT, kind: 'slot' });
          });
          (state.preciseSlots || []).forEach(function(ps) {
            outT.push({ startMin: ps.startMinutes, endMin: ps.startMinutes + ps.durationMinutes, kind: 'precise' });
          });
          outT.sort(function(a, b) { return a.startMin - b.startMin || a.endMin - b.endMin; });
          return outT;
        }
        return [];
      }

      /** Merges overlapping busy intervals into a single coverage list — used for free-gap math. */
      function mergeBusyCoverage(busy) {
        if (!busy.length) return [];
        var sorted = busy.slice().sort(function(a, b) { return a.startMin - b.startMin; });
        var merged = [{ startMin: sorted[0].startMin, endMin: sorted[0].endMin }];
        for (var i = 1; i < sorted.length; i++) {
          var last = merged[merged.length - 1];
          if (sorted[i].startMin <= last.endMin) {
            if (sorted[i].endMin > last.endMin) last.endMin = sorted[i].endMin;
          } else {
            merged.push({ startMin: sorted[i].startMin, endMin: sorted[i].endMin });
          }
        }
        return merged;
      }

      /**
       * Free gaps inside the day window: gaps where a 15+ min slot can fit AND not in the past.
       * Returns sorted list of { startMin, endMin, length }.
       */
      function computePreciseFreeGaps(busy, win) {
        var minLen = 15;
        var nowGate = state.editDate ? null : 0;
        var coverage = mergeBusyCoverage(busy);
        var gaps = [];
        var cursor = win.startMin;
        for (var i = 0; i < coverage.length; i++) {
          var b = coverage[i];
          if (b.startMin > cursor) gaps.push({ startMin: cursor, endMin: Math.min(b.startMin, win.endMin) });
          cursor = Math.max(cursor, b.endMin);
          if (cursor >= win.endMin) break;
        }
        if (cursor < win.endMin) gaps.push({ startMin: cursor, endMin: win.endMin });
        // Drop past-only gaps & enforce min length
        var out = [];
        for (var j = 0; j < gaps.length; j++) {
          var g = gaps[j];
          if (state.editDate) {
            // Push start forward to first non-past 5-minute mark
            var startM = g.startMin;
            while (startM < g.endMin && isCalendarSlotStartInPast(state.editDate, startM)) startM += 5;
            if (startM >= g.endMin) continue;
            g = { startMin: startM, endMin: g.endMin };
          }
          var len = g.endMin - g.startMin;
          if (len < minLen) continue;
          g.length = len;
          out.push(g);
        }
        return out;
      }

      /**
       * After confirming a precise slot: jump draft clock to earliest valid position for the **current duration**
       * that fits merged free gaps (same math as timeline). Prefers positions >= end of the slot just appended.
       */
      function snapPreciseDraftStartAfterSuccessfulAdd(lastAddedEv) {
        var win = getPreciseDayWindow();
        var dur = getPreciseDraftDuration();
        if (isNaN(dur) || dur < 15) {
          dur = Math.max(15, Math.min((lastAddedEv && lastAddedEv.dur) || 45, 480));
        }
        if (dur > 480) dur = 480;
        var step = 5;
        function firstLoInGap(g, prefFloor) {
          var lo = Math.max(g.startMin, prefFloor || 0);
          lo = Math.ceil(lo / step) * step;
          if (lo < g.startMin) lo = g.startMin;
          for (; lo + dur <= g.endMin; lo += step) {
            if (state.editMode === 'calendar' && state.editDate && isCalendarSlotStartInPast(state.editDate, lo)) {
              continue;
            }
            /** Safety net besides gap envelope (keeps parity with classifyPreview). */
            if (preciseIntervalOverlapsAny(lo, lo + dur, -1)) continue;
            return lo;
          }
          return null;
        }
        function pickWithGaps(prefFloor, gaps) {
          var chosen = null;
          for (var gi = 0; gi < gaps.length; gi++) {
            var g = gaps[gi];
            if (g.endMin - g.startMin < dur) continue;
            var s = firstLoInGap(g, prefFloor);
            if (s != null && (chosen == null || s < chosen)) chosen = s;
          }
          return chosen;
        }
        var gapsOnce = computePreciseFreeGaps(collectPreciseDayBusyIntervals(), win);
        var pref = typeof lastAddedEv.endMin === 'number' ? lastAddedEv.endMin : win.startMin;
        pref = Math.max(pref, win.startMin);
        var nextStart = pickWithGaps(pref, gapsOnce);
        if (nextStart == null) {
          /** Prefer any legal start still **at or after** the block we just chained off — never snap backward earlier in the day. */
          var cand = pickWithGaps(win.startMin, gapsOnce);
          if (cand != null && cand >= pref) nextStart = cand;
        }
        if (nextStart == null) {
          /** Nothing ahead fits this duration — stay at preference; preview stays honest (trainer knows add succeeded). */
          nextStart = Math.min(Math.max(pref, win.startMin), 24 * 60 - dur);
        }
        var sh = document.getElementById('preciseStartH');
        var smEl = document.getElementById('preciseStartM');
        if (sh) sh.value = String(Math.floor(nextStart / 60) % 24);
        if (smEl) smEl.value = String(nextStart % 60);
      }

      /** Renders existing slots/bookings/precise as colored bands on a normalized rail. */
      function renderPreciseTimelineRail(busy, win) {
        var rail = document.getElementById('preciseTimelineRail');
        if (!rail) return;
        var totalMin = win.endMin - win.startMin;
        rail.style.setProperty('--precise-rail-hours', String(Math.max(1, Math.round(totalMin / 60))));
        rail.innerHTML = '';
        if (totalMin <= 0) return;
        // Render free gaps as soft green bands first (visual reassurance + tappable)
        var gaps = computePreciseFreeGaps(busy, win);
        gaps.forEach(function(g) {
          var leftPct = ((g.startMin - win.startMin) / totalMin) * 100;
          var widthPct = ((g.endMin - g.startMin) / totalMin) * 100;
          if (widthPct < 0.6) return; /* too thin to render meaningfully */
          var band = document.createElement('button');
          band.type = 'button';
          band.className = 'precise-day-glance__band precise-day-glance__band--free';
          band.style.left = leftPct + '%';
          band.style.width = widthPct + '%';
          band.setAttribute('aria-label', 'Свободно с ' + formatMinuteClock(g.startMin) + ' до ' + formatMinuteClock(g.endMin));
          band.onclick = function() { applyPreciseFreeGapToDraft(g); };
          rail.appendChild(band);
        });
        // Render busy bands on top
        busy.forEach(function(b) {
          if (b.endMin <= win.startMin || b.startMin >= win.endMin) return;
          var s = Math.max(b.startMin, win.startMin);
          var e = Math.min(b.endMin, win.endMin);
          var leftPct = ((s - win.startMin) / totalMin) * 100;
          var widthPct = ((e - s) / totalMin) * 100;
          if (widthPct < 0.6) return;
          var band = document.createElement('div');
          band.className = 'precise-day-glance__band precise-day-glance__band--' +
            (b.kind === 'booked' ? 'booked' : (b.kind === 'precise' ? 'slot' : 'slot'));
          band.style.left = leftPct + '%';
          band.style.width = widthPct + '%';
          band.title = formatMinuteClock(b.startMin) + '–' + formatMinuteClock(b.endMin);
          if (widthPct > 9) {
            var lab = document.createElement('span');
            lab.className = 'precise-day-glance__band-label';
            lab.textContent = formatMinuteClock(b.startMin);
            band.appendChild(lab);
          }
          rail.appendChild(band);
        });
        // Hour ticks
        var ticks = document.getElementById('preciseTimelineTicks');
        if (ticks) {
          ticks.innerHTML = '';
          var hourCount = Math.max(2, Math.round(totalMin / 60));
          var stride = hourCount > 8 ? 3 : (hourCount > 4 ? 2 : 1);
          var first = Math.ceil(win.startMin / 60);
          var last = Math.floor(win.endMin / 60);
          for (var h = first; h <= last; h += stride) {
            var tick = document.createElement('span');
            tick.className = 'precise-day-glance__tick';
            tick.textContent = String(h).padStart(2, '0');
            ticks.appendChild(tick);
          }
        }
      }

      /** Quick-fill chips for trainer: tap "Свободно с 09:00 (75 мин)" to prefill the form. */
      function renderPreciseFreeGapChips(gaps) {
        var wrap = document.getElementById('preciseFreeGapsWrap');
        var list = document.getElementById('preciseFreeGapsList');
        if (!wrap || !list) return;
        list.innerHTML = '';
        if (!gaps.length) {
          wrap.hidden = true;
          return;
        }
        var topGaps = gaps.slice(0, 4); /* keep UI tight on phones */
        topGaps.forEach(function(g) {
          var chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'precise-day-glance__chip';
          var lenLabel = g.length >= 120
            ? 'до ' + formatMinuteClock(g.endMin)
            : g.length + ' мин';
          chip.innerHTML =
            '<span>с ' + formatMinuteClock(g.startMin) + '</span>' +
            '<span class="precise-day-glance__chip-len">' + lenLabel + '</span>';
          chip.onclick = function() { applyPreciseFreeGapToDraft(g); };
          list.appendChild(chip);
        });
        wrap.hidden = false;
      }

      /** Choose a duration that fits the gap, preferring trainer's last selection. */
      function pickFittingDuration(gapLen) {
        var preferred = state.preciseDraftDuration || 45;
        if (gapLen >= preferred) return preferred;
        var presets = [60, 45, 30, 90, 75, 120];
        for (var i = 0; i < presets.length; i++) {
          if (presets[i] <= gapLen) return presets[i];
        }
        return Math.max(15, gapLen);
      }

      function applyPreciseFreeGapToDraft(gap) {
        var sh = document.getElementById('preciseStartH');
        var sm = document.getElementById('preciseStartM');
        if (sh) sh.value = String(Math.floor(gap.startMin / 60));
        if (sm) sm.value = String(gap.startMin % 60);
        var dur = pickFittingDuration(gap.length);
        applyPreciseDuration(dur);
        updatePrecisePreview();
      }

      /** Programmatically pick a duration: highlight matching chip, or set custom input. */
      function applyPreciseDuration(durMin) {
        var chips = document.getElementById('preciseDurChips');
        var custInp = document.getElementById('preciseDurCustom');
        if (!chips) return;
        var matched = null;
        chips.querySelectorAll('.precise-dur-chip').forEach(function(b) { b.classList.remove('selected'); });
        chips.querySelectorAll('.precise-dur-chip[data-dur]').forEach(function(b) {
          if (matched) return;
          var v = b.dataset.dur;
          if (v !== 'custom' && parseInt(v, 10) === durMin) {
            b.classList.add('selected');
            matched = b;
          }
        });
        if (!matched) {
          var customBtn = chips.querySelector('.precise-dur-chip[data-dur="custom"]');
          if (customBtn) customBtn.classList.add('selected');
          if (custInp) {
            custInp.style.display = 'block';
            custInp.value = String(Math.max(15, Math.min(480, durMin)));
          }
        } else if (custInp) {
          custInp.style.display = 'none';
        }
        state.preciseDraftDuration = durMin;
      }

      /** Centralized validation: returns { status, startMin, endMin, dur, message }. */
      function evaluatePreciseDraft() {
        var startM = parsePreciseDraftMinutes();
        var dur = getPreciseDraftDuration();
        if (startM == null) {
          return { status: 'invalid', message: 'Укажите время', dur: dur };
        }
        if (isNaN(dur) || dur < 15) {
          return { status: 'invalid', startMin: startM, message: 'Минимум 15 минут', dur: dur };
        }
        if (dur > 480) {
          return { status: 'invalid', startMin: startM, message: 'Максимум 8 часов', dur: dur };
        }
        var endM = startM + dur;
        if (endM > 24 * 60) {
          return { status: 'invalid', startMin: startM, endMin: endM, dur: dur, message: 'Выходит за полночь' };
        }
        if (state.editMode === 'calendar' && state.editDate && isCalendarSlotStartInPast(state.editDate, startM)) {
          return { status: 'invalid', startMin: startM, endMin: endM, dur: dur, message: 'Время уже прошло' };
        }
        var overlap = preciseIntervalOverlapsAny(startM, endM, -1);
        if (overlap === 'booking') {
          return { status: 'conflict', startMin: startM, endMin: endM, dur: dur, message: 'Пересекается с записью' };
        }
        if (overlap) {
          return { status: 'conflict', startMin: startM, endMin: endM, dur: dur, message: 'Пересекается со слотом' };
        }
        return { status: 'ok', startMin: startM, endMin: endM, dur: dur, message: 'Можно добавить' };
      }

      /** Updates preview pill, draft band on the timeline, and disables Add button when invalid. */
      function updatePrecisePreview() {
        var ev = evaluatePreciseDraft();
        var preview = document.getElementById('precisePreview');
        var startEl = document.getElementById('precisePreviewStart');
        var endEl = document.getElementById('precisePreviewEnd');
        var durEl = document.getElementById('precisePreviewDur');
        var statusEl = document.getElementById('precisePreviewStatus');
        var addBtn = document.getElementById('btnAddPreciseSlot');
        if (preview) preview.setAttribute('data-status', ev.status);
        if (startEl) startEl.textContent = ev.startMin != null ? formatMinuteClock(ev.startMin) : '—:—';
        if (endEl) endEl.textContent = ev.endMin != null ? formatMinuteClock(ev.endMin) : '—:—';
        if (durEl) durEl.textContent = (ev.dur && !isNaN(ev.dur)) ? (ev.dur + ' мин') : '—';
        if (statusEl) statusEl.textContent = ev.message || '';
        if (addBtn) addBtn.disabled = ev.status !== 'ok';
        // Inline error stays empty during real-time editing — only on tap of Add (validateAndAddPreciseSlot).
        setPreciseError('');
        renderPreciseDraftBand(ev);
      }

      /** Pulsing band on the timeline for the current draft (red when conflict). */
      function renderPreciseDraftBand(ev) {
        var rail = document.getElementById('preciseTimelineRail');
        if (!rail) return;
        var existing = rail.querySelector('.precise-day-glance__band--draft');
        if (existing) existing.remove();
        if (ev.startMin == null || ev.endMin == null) return;
        var win = getPreciseDayWindow();
        if (ev.endMin <= win.startMin || ev.startMin >= win.endMin) return;
        var totalMin = win.endMin - win.startMin;
        var s = Math.max(ev.startMin, win.startMin);
        var e = Math.min(ev.endMin, win.endMin);
        var leftPct = ((s - win.startMin) / totalMin) * 100;
        var widthPct = Math.max(1.2, ((e - s) / totalMin) * 100);
        var band = document.createElement('div');
        band.className = 'precise-day-glance__band precise-day-glance__band--draft' +
          (ev.status === 'conflict' ? ' precise-day-glance__band--draft-conflict' : '');
        band.style.left = leftPct + '%';
        band.style.width = widthPct + '%';
        rail.appendChild(band);
      }

      /** Re-renders whole layout: timeline + chips. Call after busy intervals change. */
      function renderPreciseLayout() {
        if (state.slotAddMode !== 'precise') return;
        if (state.editMode === 'template' && slotIntentUseGroupUi()) return;
        var win = getPreciseDayWindow();
        var busy = collectPreciseDayBusyIntervals();
        renderPreciseTimelineRail(busy, win);
        var gaps = computePreciseFreeGaps(busy, win);
        renderPreciseFreeGapChips(gaps);
        updatePrecisePreview();
      }

      function syncPreciseManualSlotsPanelDisplay() {
        var wrap = document.getElementById('preciseSlotsAdded');
        var hint = document.getElementById('preciseSlotsSaveHint');
        if (!wrap) return;
        var n = (state.preciseSlots || []).length;
        var showManual = n > 0 && state.slotAddMode === 'precise';
        wrap.style.display = showManual ? 'block' : 'none';
        if (hint) hint.style.display = showManual ? 'block' : 'none';
      }

      function renderPreciseSlotsAdded() {
        var wrap = document.getElementById('preciseSlotsAdded');
        var list = document.getElementById('preciseSlotsAddedList');
        if (!wrap || !list) return;
        var slots = state.preciseSlots || [];
        list.innerHTML = '';
        var baseline = state.calendarBaselinePreciseKeys;
        slots.forEach(function(ps, idx) {
          var endM = ps.startMinutes + ps.durationMinutes;
          var tag = document.createElement('div');
          var stableKey = calendarPreciseSlotStableKey(ps);
          var isPersistedPrecise =
            ps.locked || (baseline instanceof Set && baseline.has(stableKey));
          var tagClass = 'precise-slot-tag' + (ps.locked ? ' precise-slot-tag--locked' : '');
          if (!isPersistedPrecise) tagClass += ' precise-slot-tag--new';
          tag.className = tagClass;
          var removeBtnHtml = ps.locked
            ? ''
            : '<button type="button" class="precise-slot-tag__remove" data-idx="' +
              idx +
              '" aria-label="Удалить слот ' +
              formatMinuteClock(ps.startMinutes) +
              '">' +
              '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
              '</button>';
          tag.innerHTML =
            '<span class="precise-slot-tag__time">' +
            formatMinuteClock(ps.startMinutes) +
            '–' +
            formatMinuteClock(endM) +
            '</span>' +
            scheduleEditorArenaChipHtml(
              ps.arenaId,
              scheduleEditorArenaNameById(ps.arenaId)
            ) +
            '<span class="precise-slot-tag__dur">' +
            ps.durationMinutes +
            ' мин' +
            (ps.locked ? ' · запись' : '') +
            '</span>' +
            removeBtnHtml;
          if (!ps.locked) {
            tag.querySelector('.precise-slot-tag__remove').onclick = function() {
              state.preciseSlots.splice(parseInt(this.dataset.idx, 10), 1);
              renderPreciseSlotsAdded();
              renderHourGrid();
              renderPreciseLayout();
              updateEditDoneButton();
            };
          }
          list.appendChild(tag);
        });
        syncPreciseManualSlotsPanelDisplay();
        syncPreciseArenaWrapsAfterSlotsChanged();
      }

      /** Calendar individual: arena for «Быстро» grid tab. */
      function syncCalendarGridArenaWrapVisibility() {
        var wrap = document.getElementById('calendarGridArenaWrap');
        if (!wrap) return;
        var useCalGroup =
          state.editMode === 'calendar' && typeof slotIntentUseGroupUi === 'function' && slotIntentUseGroupUi();
        var ars = state.trainerScheduleArenas || [];
        var show =
          state.editMode === 'calendar' &&
          !useCalGroup &&
          !(typeof slotIntentUseCenterUi === 'function' && slotIntentUseCenterUi()) &&
          state.slotAddMode === 'grid' &&
          ars.length > 1;
        wrap.style.display = show ? 'block' : 'none';
        if (!show) return;
        var sel = document.getElementById('calendarGridArenaSelect');
        if (!sel || !sel.options.length) {
          fillScheduleEditorGridArenaPick(state.scheduleGridArenaPickId);
        } else {
          syncScheduleEditorGridArenaPickHighlight();
        }
      }

      /** Template individual: arena for «Быстро» grid tab. */
      function syncTemplateGridArenaWrapVisibility() {
        var wrap = document.getElementById('templateGridArenaWrap');
        if (!wrap) return;
        var useTplGroup =
          state.editMode === 'template' && typeof slotIntentUseGroupUi === 'function' && slotIntentUseGroupUi();
        var ars = state.trainerScheduleArenas || [];
        var show =
          state.editMode === 'template' &&
          !useTplGroup &&
          state.slotAddMode === 'grid' &&
          ars.length > 1;
        wrap.style.display = show ? 'block' : 'none';
        if (!show) return;
        var sel = document.getElementById('templateGridArenaSelect');
        if (!sel || !sel.options.length) {
          fillScheduleEditorGridArenaPick(state.scheduleGridArenaPickId);
        } else {
          syncScheduleEditorGridArenaPickHighlight();
        }
      }

      /** Calendar individual: arena for «Точное время» only (hidden on Быстро tab). */
      function syncCalendarPreciseArenaWrapVisibility() {
        var wrap = document.getElementById('calendarPreciseArenaWrap');
        if (!wrap) return;
        var useCalGroup =
          state.editMode === 'calendar' && typeof slotIntentUseGroupUi === 'function' && slotIntentUseGroupUi();
        var ars = state.trainerScheduleArenas || [];
        var show =
          state.editMode === 'calendar' &&
          !useCalGroup &&
          state.slotAddMode === 'precise' &&
          ars.length > 1;
        wrap.style.display = show ? 'block' : 'none';
        if (!show) return;
        fillScheduleEditorArenaSelect('calendarPreciseArenaSelect', null);
      }

      /** Template individual: arena for «Точное время» tab only. */
      function syncTemplatePreciseArenaWrapVisibility() {
        var wrap = document.getElementById('templatePreciseArenaWrap');
        if (!wrap) return;
        var useTplGroup =
          state.editMode === 'template' && typeof slotIntentUseGroupUi === 'function' && slotIntentUseGroupUi();
        var ars = state.trainerScheduleArenas || [];
        var show =
          state.editMode === 'template' &&
          !useTplGroup &&
          state.slotAddMode === 'precise' &&
          ars.length > 1;
        wrap.style.display = show ? 'block' : 'none';
        if (!show) return;
        fillScheduleEditorArenaSelect('templatePreciseArenaSelect', null);
      }

      function syncPreciseArenaWrapsAfterSlotsChanged() {
        syncCalendarGridArenaWrapVisibility();
        syncTemplateGridArenaWrapVisibility();
        syncCalendarPreciseArenaWrapVisibility();
        syncTemplatePreciseArenaWrapVisibility();
      }

      function setPreciseError(msg) {
        var el = document.getElementById('preciseSlotError');
        if (!el) return;
        if (msg) { el.textContent = msg; el.hidden = false; }
        else { el.textContent = ''; el.hidden = true; }
      }

      function validateAndAddPreciseSlot() {
        var ev = evaluatePreciseDraft();
        if (ev.status !== 'ok') {
          setPreciseError(ev.message || 'Проверьте время и длительность');
          return;
        }
        if (!state.preciseSlots) state.preciseSlots = [];
        var psRow = { startMinutes: ev.startMin, durationMinutes: ev.dur };
        var precArenaPick = readPreciseArenaPickForSave();
        if (precArenaPick != null) psRow.arenaId = precArenaPick;
        state.preciseSlots.push(psRow);
        setPreciseError('');
        renderPreciseSlotsAdded();
        renderHourGrid();
        updateEditDoneButton();
        snapPreciseDraftStartAfterSuccessfulAdd(ev);
        renderPreciseLayout();
      }

      /** Hour ±1 wraps 0–23; Minute ±5 wraps with hour carry — ergonomic for one-thumb use. */
      function stepPreciseField(target, dir) {
        var sh = document.getElementById('preciseStartH');
        var sm = document.getElementById('preciseStartM');
        if (!sh || !sm) return;
        var h = parseInt(sh.value, 10);
        var m = parseInt(sm.value, 10);
        if (isNaN(h)) h = 8;
        if (isNaN(m)) m = 0;
        if (target === 'hour') {
          h = (h + (dir === 'up' ? 1 : -1) + 24) % 24;
        } else {
          var step = 5;
          var totalMin = h * 60 + m;
          totalMin = (totalMin + (dir === 'up' ? step : -step) + 24 * 60) % (24 * 60);
          h = Math.floor(totalMin / 60);
          m = totalMin % 60;
        }
        sh.value = String(h);
        sm.value = String(m);
        updatePrecisePreview();
      }

      function setSlotAddMode(mode) {
        state.slotAddMode = mode;
        var btnGrid = document.getElementById('btnSlotModeGrid');
        var btnPrec = document.getElementById('btnSlotModePrecise');
        var durationWrap = document.getElementById('slotDurationWrap');
        var gridSection = document.querySelector('.schedule-time-grid-section');
        var preciseForm = document.getElementById('preciseSlotForm');
        if (btnGrid) btnGrid.classList.toggle('slot-add-mode-btn--active', mode === 'grid');
        if (btnPrec) btnPrec.classList.toggle('slot-add-mode-btn--active', mode === 'precise');
        var isPrecise = mode === 'precise';
        if (durationWrap) durationWrap.style.display = isPrecise ? 'none' : '';
        if (gridSection) gridSection.style.display = isPrecise ? 'none' : '';
        if (preciseForm) preciseForm.style.display = isPrecise ? 'block' : 'none';
        setPreciseError('');
        if (isPrecise) {
          // Seed start time near the first free gap if available so trainer lands on a sensible default.
          var win = getPreciseDayWindow();
          var busy = collectPreciseDayBusyIntervals();
          var gaps = computePreciseFreeGaps(busy, win);
          if (gaps.length) {
            var sh = document.getElementById('preciseStartH');
            var smEl = document.getElementById('preciseStartM');
            // Honor any value the trainer already typed; otherwise prefill.
            var typedStart = parsePreciseDraftMinutes();
            if (typedStart == null || typedStart < win.startMin) {
              if (sh) sh.value = String(Math.floor(gaps[0].startMin / 60));
              if (smEl) smEl.value = String(gaps[0].startMin % 60);
            }
          }
          renderPreciseLayout();
        }
        syncPreciseArenaWrapsAfterSlotsChanged();
        syncPreciseManualSlotsPanelDisplay();
      }

      function initPreciseFormEvents() {
        var btnGrid = document.getElementById('btnSlotModeGrid');
        var btnPrec = document.getElementById('btnSlotModePrecise');
        if (btnGrid) btnGrid.onclick = function() { setSlotAddMode('grid'); };
        if (btnPrec) btnPrec.onclick = function() { setSlotAddMode('precise'); };

        var sh = document.getElementById('preciseStartH');
        var sm = document.getElementById('preciseStartM');
        var custInp = document.getElementById('preciseDurCustom');
        if (sh) sh.addEventListener('input', updatePrecisePreview);
        if (sm) sm.addEventListener('input', updatePrecisePreview);
        if (custInp) custInp.addEventListener('input', updatePrecisePreview);

        // Stepper buttons: hour ±1 / minute ±5
        document.querySelectorAll('.precise-stepper').forEach(function(stp) {
          var target = stp.dataset.stepTarget;
          stp.querySelectorAll('.precise-stepper__btn').forEach(function(btn) {
            btn.onclick = function(ev) {
              ev.preventDefault();
              stepPreciseField(target, btn.dataset.stepDir);
            };
          });
        });

        var chips = document.getElementById('preciseDurChips');
        if (chips) {
          chips.querySelectorAll('.precise-dur-chip').forEach(function(btn) {
            btn.onclick = function() {
              chips.querySelectorAll('.precise-dur-chip').forEach(function(b) { b.classList.remove('selected'); });
              btn.classList.add('selected');
              if (btn.dataset.dur === 'custom') {
                if (custInp) custInp.style.display = 'block';
                var ci = parseInt(custInp ? custInp.value : '', 10);
                if (!isNaN(ci) && ci >= 15) state.preciseDraftDuration = Math.min(480, ci);
              } else {
                if (custInp) custInp.style.display = 'none';
                state.preciseDraftDuration = parseInt(btn.dataset.dur, 10) || 45;
              }
              updatePrecisePreview();
            };
          });
        }

        var addBtn = document.getElementById('btnAddPreciseSlot');
        if (addBtn) addBtn.onclick = validateAndAddPreciseSlot;
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

      /** Week range label above day list («Добавить слоты») — same copy as календарь. */
      function syncDayPickWeekNav() {
        var el = document.getElementById('dayPickWeekLabel');
        if (!el || !state.weekStart) return;
        el.textContent = formatWeekLabel(state.weekStart);
      }

      function showDayPickScreen() {
        if (!assertScheduleCrmWriteAllowed()) return;
        if (!state.weekStart) return;
        var dayPickTitle = document.getElementById('dayPickTitle');
        if (dayPickTitle) {
          dayPickTitle.textContent = slotIntentUseCenterUi()
            ? 'Добавить окна центра на какой день?'
            : slotIntentUseGroupUi()
              ? 'Добавить групповые слоты на какой день?'
              : 'Добавить индивидуальные слоты на какой день?';
        }
        syncDayPickWeekNav();
        const list = document.getElementById('dayPickList');
        let html = '';
        const todayStr = dateToStr(new Date());
        for (let i = 0; i < 7; i++) {
          const d = new Date(state.weekStart);
          d.setDate(d.getDate() + i);
          const dateStr = dateToStr(d);
          if (dateStr < todayStr) continue;
          var slotCount = countExistingSlotsForDayPick(dateStr);
          var countLabel = ruSlotCountLabel(slotCount);
          html +=
            '<button type="button" class="template-day-card template-day-card--day-pick" data-date="' +
            escapeHtml(dateStr) +
            '" aria-label="' +
            escapeHtml(DAYS[i] + ', ' + formatDateKeyNoWeekday(dateStr) + ', ' + countLabel) +
            '">';
          html += '<span class="day-pick-slot-count"><span class="day-pick-slot-count__text">' + escapeHtml(countLabel) + '</span></span>';
          html += '<span class="day-pick-date-block">';
          html += '<span class="day-name">' + DAYS[i] + '</span>';
          html += '<span class="day-slots">' + formatDateKeyNoWeekday(dateStr) + '</span>';
          html += '</span>';
          html += '<span class="arrow">→</span></button>';
        }
        if (!html) {
          list.innerHTML =
            '<div class="empty">В этой неделе нельзя добавить слоты — здесь только прошлые дни. Переключитесь на актуальную неделю.</div>';
        } else {
          list.innerHTML = html;
          document.querySelector('.tabs').style.display = 'none';
          document.getElementById('tabCalendar').style.display = 'none';
          document.getElementById('tabTemplate').style.display = 'none';
          document.getElementById('screenDayPick').style.display = 'block';
          updateTelegramBack();
          syncScheduleWeekDayStripVisibility();
          window.scrollTo(0, 0);
          document.querySelectorAll('#dayPickList .template-day-card').forEach(function(btn) {
            btn.onclick = function(ev) {
              var sup = Number(state.scheduleDayPickSwipeSuppressUntil) || 0;
              if (sup && Date.now() < sup) {
                if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
                if (ev && typeof ev.stopPropagation === 'function') ev.stopPropagation();
                return;
              }
              document.getElementById('screenDayPick').style.display = 'none';
              state.centerEditReturn = 'daypick';
              openEditCalendarDay(btn.dataset.date);
            };
          });
        }
      }

      /**
       * Leave calendar time-grid editor without closing the multi-day "add slots" flow:
       * back to weekday list (same intent individual/group preserved).
       */
      function returnToCalendarDayPickFromEdit(opts) {
        opts = opts || {};
        var se = document.getElementById('screenEdit');
        if (se) se.style.display = 'none';
        state.editMode = null;
        state.editDate = null;
        state.editDay = null;
        state.calendarBaselineStarts = null;
        state.calendarBaselinePreciseKeys = null;
        state.selectedStarts = new Set();
        state.lockedStarts = new Set();
        state.preciseSlots = [];
        state.slotAddMode = 'grid';
        resetCenterEditCoachIds();
        state.centerEditReturn = null;
        var coachWrapReset = document.getElementById('centerEditCoachWrap');
        if (coachWrapReset) coachWrapReset.hidden = true;
        if (opts.reloadSlots) {
          loadSlots({
            onComplete: function() {
              showDayPickScreen();
            },
          });
        } else {
          showDayPickScreen();
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
        var centerBtn = document.getElementById('btnSlotIntentCenter');
        if (ind) ind.classList.remove('is-suggested');
        if (grp) grp.classList.remove('is-suggested');
        if (centerBtn) centerBtn.classList.remove('is-suggested');
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
        var centerBtn = document.getElementById('btnSlotIntentCenter');
        if (ind) ind.classList.remove('is-suggested');
        if (grp) grp.classList.remove('is-suggested');
        if (centerBtn) centerBtn.classList.remove('is-suggested');
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

      /** «Добавить слоты на неделю» — только когда неделя календаря не целиком в прошлом (и есть CRM). */
      function syncAddSlotsButtonEligibility() {
        var el = document.getElementById('btnAddSlots');
        if (!el) return;
        var crmOk = !!state.scheduleCrmWriteAllowed;
        var pastWeek = !!(state.weekStart && isEntireWeekInPast(state.weekStart));
        el.disabled = !crmOk || pastWeek;
        el.classList.toggle('btn-add-slots--past-week', pastWeek && crmOk);
        if (pastWeek && crmOk) {
          el.setAttribute('title', 'На прошедшей неделе слоты не добавляем — перелистните календарь «›».');
        } else {
          el.removeAttribute('title');
        }
      }

      /**
       * Bottom strip: day needs showPastThisWeek before its section exists in the list
       * (past weekdays, or today's sessions that already ended).
       */
      function scheduleStripDayNeedsPastReveal(dateStr) {
        if (isEntireWeekInPast(state.weekStart)) return false;
        if (state.showPastThisWeek) return false;
        var todayStr = dateToStr(new Date());
        if (dateStr > todayStr) return false;
        if (dateStr < todayStr) {
          return (state.slots || []).some(function(s) {
            return s.slot_date === dateStr;
          });
        }
        return (state.slots || []).some(function(s) {
          return s.slot_date === todayStr && isSlotEndedInPast(s);
        });
      }

      /**
       * Empty calendar: lead with what to do next (past history via bottom day strip).
       */
      function buildCalendarEmptyStateHtml(slotFilter, entirePast) {
        var title = 'Запланируйте окна на эту неделю';
        var hint =
          'Добавьте слоты кнопкой выше или задайте повтор во вкладке «Шаблон недели» — так неделя заполняется быстрее.';
        if (entirePast) {
          title = 'Эта неделя в прошлом';
          hint = deviceLikelySupportsTouchSwipeNavigation()
            ? 'Выберите текущую или будущую неделю стрелками над датой или свайпом влево/вправо по расписанию — там можно добавить слоты.'
            : 'Выберите текущую или будущую неделю стрелками у дат выше — там можно добавить слоты.';
        } else if (slotFilter === 'available') {
          title = 'Нет свободных слотов';
          hint = 'Попробуйте фильтр «Все» или добавьте новые окна на день.';
        } else if (slotFilter === 'booked') {
          title = 'Нет занятых слотов';
          hint = deviceLikelySupportsTouchSwipeNavigation()
            ? 'Попробуйте фильтр «Все», перелистайте неделю стрелками или свайпом влево/вправо по расписанию.'
            : 'Попробуйте фильтр «Все» или перелистайте неделю стрелками.';
        }
        var html =
          '<div class="calendar-empty-state">' +
          '<p class="calendar-empty-state__title">' +
          escapeHtml(title) +
          '</p>' +
          '<p class="calendar-empty-state__hint">' +
          escapeHtml(hint) +
          '</p>';
        html += '</div>';
        return html;
      }

      /** ISO date for Mon+dayIndex within the trainer's current calendar week. */
      function weekDateStrFromMonday(weekStart, dayIndex) {
        var d = new Date(weekStart);
        d.setHours(0, 0, 0, 0);
        d.setDate(d.getDate() + dayIndex);
        return dateToStr(d);
      }

      /**
       * Week strip edges: coarse primary pointer (phones) ⇒ <span>, not <button>, so horizontal week swipe can
       * still start from the strip (wireScheduleWeekSwipeGestures excludes touch targets that match button).
       * Fine pointers (mouse) get native <button> chevrons.
       */
      function scheduleStripUseNativeNavButtons() {
        try {
          return !!(window.matchMedia && window.matchMedia('(pointer: fine)').matches);
        } catch (eMq) {
          return false;
        }
      }

      function scheduleStripWeekNavMarkup(delta) {
        var useBtn = scheduleStripUseNativeNavButtons();
        var label = delta < 0 ? 'Предыдущая неделя' : 'Следующая неделя';
        var svgChevLeft =
          '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>';
        var svgChevRight =
          '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>';
        var inner = delta < 0 ? svgChevLeft : svgChevRight;
        var cls =
          'schedule-week-day-strip__wkNav' +
          (useBtn ? ' schedule-week-day-strip__wkNav--btn' : ' schedule-week-day-strip__wkNav--touch');
        var attrs =
          ' class="' +
          cls +
          '" data-strip-week-delta="' +
          String(delta) +
          '" aria-label="' +
          escapeHtml(label) +
          '"';
        if (useBtn) {
          return '<button type="button"' + attrs + '>' + inner + '</button>';
        }
        return '<span role="button" tabindex="0"' + attrs + '>' + inner + '</span>';
      }

      function syncScheduleWeekDayStripVisibility() {
        var el = document.getElementById('scheduleWeekDayStrip');
        if (!el) return;
        var main = document.getElementById('screenMain');
        var mainOn = main && main.classList.contains('active');
        var dayPickEl = document.getElementById('screenDayPick');
        var dayPickOpen = dayPickEl && dayPickEl.style.display === 'block';
        var editEl = document.getElementById('screenEdit');
        var editOpen = editEl && editEl.style.display === 'block';
        /* Strip only for the main week calendar list — not day-pick overlay or per-day slot editor. */
        var show = mainOn && state.tab === 'calendar' && !dayPickOpen && !editOpen;
        el.hidden = !show;
        try {
          document.documentElement.classList.toggle('se-week-day-strip-visible', show);
        } catch (eDoc) { /* ignore */ }
        if (!show) teardownScheduleCalendarScrollSpy();
      }

      var scheduleCalendarScrollSpyTeardown = null;

      function scheduleCalendarScrollSpyActive() {
        var main = document.getElementById('screenMain');
        if (!main || !main.classList.contains('active')) return false;
        if (state.tab !== 'calendar') return false;
        var dayPickEl = document.getElementById('screenDayPick');
        if (dayPickEl && dayPickEl.style.display === 'block') return false;
        var editEl = document.getElementById('screenEdit');
        if (editEl && editEl.style.display === 'block') return false;
        var strip = document.getElementById('scheduleWeekDayStrip');
        if (!strip || strip.hidden) return false;
        return true;
      }

      /** Y-offset from viewport top: day block intersecting this line is «active» in the strip. */
      function scheduleCalendarScrollProbeY() {
        var vh = window.innerHeight || 640;
        var chrome = document.getElementById('seScheduleTopChrome');
        var chromeH = chrome ? chrome.getBoundingClientRect().height : 0;
        // Below fixed tabs/header, but not the top edge — matches «какой день сейчас читаю».
        var belowChrome = chromeH + Math.max(40, Math.round((vh - chromeH) * 0.22));
        return Math.min(belowChrome, Math.round(vh * 0.42));
      }

      function scheduleCalendarScrollAtBottom() {
        var scrollEl = document.documentElement;
        var scrollTop = window.scrollY || scrollEl.scrollTop || 0;
        var viewportH = window.innerHeight || 0;
        var scrollH = scrollEl.scrollHeight || 0;
        var bottomSlack = Math.max(64, Math.round(viewportH * 0.1));
        return scrollTop + viewportH >= scrollH - bottomSlack;
      }

      function updateScheduleWeekDayStripSelectionOnly() {
        var root = document.getElementById('scheduleWeekDayStrip');
        if (!root) return;
        var sel = state.scheduleStripSelectedDate;
        root.querySelectorAll('[data-strip-date]').forEach(function(btn) {
          var on = !!(sel && btn.getAttribute('data-strip-date') === sel);
          btn.classList.toggle('schedule-week-day-strip__btn--selected', on);
        });
      }

      function syncScheduleStripFromCalendarScroll() {
        var sup = Number(state.scheduleStripScrollSyncSuppressUntil) || 0;
        if (sup && Date.now() < sup) return;
        if (!scheduleCalendarScrollSpyActive()) return;
        var content = document.getElementById('calendarContent');
        if (!content) return;
        var anchors = content.querySelectorAll('.cal-day-anchor');
        if (!anchors.length) return;

        var activeEl = anchors[anchors.length - 1];
        if (!scheduleCalendarScrollAtBottom()) {
          var probeY = scheduleCalendarScrollProbeY();
          var contained = null;
          var passed = anchors[0];
          for (var i = 0; i < anchors.length; i++) {
            var rect = anchors[i].getBoundingClientRect();
            if (rect.top <= probeY && rect.bottom > probeY) {
              contained = anchors[i];
              break;
            }
            if (rect.top <= probeY) passed = anchors[i];
          }
          activeEl = contained || passed;
        }

        var dateStr = String(activeEl.id || '').replace(/^cal-day-/, '');
        if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return;
        if (state.scheduleStripSelectedDate === dateStr) return;
        state.scheduleStripSelectedDate = dateStr;
        updateScheduleWeekDayStripSelectionOnly();
      }

      function teardownScheduleCalendarScrollSpy() {
        if (scheduleCalendarScrollSpyTeardown) {
          scheduleCalendarScrollSpyTeardown();
          scheduleCalendarScrollSpyTeardown = null;
        }
      }

      /** Keep bottom Mon–Sun strip highlight in sync while the trainer scrolls the week list. */
      function installScheduleCalendarScrollSpy() {
        teardownScheduleCalendarScrollSpy();
        if (!scheduleCalendarScrollSpyActive()) return;
        var content = document.getElementById('calendarContent');
        if (!content || !content.querySelector('.cal-day-anchor')) return;
        var ticking = false;
        function onScrollOrResize() {
          if (ticking) return;
          ticking = true;
          requestAnimationFrame(function() {
            ticking = false;
            syncScheduleStripFromCalendarScroll();
          });
        }
        window.addEventListener('scroll', onScrollOrResize, { passive: true });
        window.addEventListener('resize', onScrollOrResize, { passive: true });
        scheduleCalendarScrollSpyTeardown = function() {
          window.removeEventListener('scroll', onScrollOrResize);
          window.removeEventListener('resize', onScrollOrResize);
        };
        syncScheduleStripFromCalendarScroll();
      }

      function renderScheduleWeekDayStrip() {
        var root = document.getElementById('scheduleWeekDayStrip');
        if (!root) return;
        if (!state.weekStart) state.weekStart = getMonday(new Date());
        var todayStr = dateToStr(new Date());
        var html = '';
        html += scheduleStripWeekNavMarkup(-1);
        html += '<div class="schedule-week-day-strip__days">';
        for (var i = 0; i < 7; i++) {
          var dateStr = weekDateStrFromMonday(state.weekStart, i);
          var isWeekend = i >= 5;
          var isToday = dateStr === todayStr;
          var isSel = !!(state.scheduleStripSelectedDate && state.scheduleStripSelectedDate === dateStr);
          var cls = 'schedule-week-day-strip__btn';
          if (isWeekend) cls += ' schedule-week-day-strip__btn--weekend';
          if (isToday) cls += ' schedule-week-day-strip__btn--today';
          if (isSel) cls += ' schedule-week-day-strip__btn--selected';
          var domNum = parseInt(dateStr.slice(8, 10), 10);
          html +=
            '<button type="button" class="' +
            cls +
            '" data-strip-date="' +
            dateStr +
            '" aria-label="' +
            SCHEDULE_STRIP_DOW[i] +
            ', ' +
            domNum +
            '">' +
            '<span class="schedule-week-day-strip__dow" aria-hidden="true">' +
            SCHEDULE_STRIP_DOW[i] +
            '</span>' +
            '<span class="schedule-week-day-strip__dom" aria-hidden="true">' +
            domNum +
            '</span>' +
            '</button>';
        }
        html += '</div>';
        html += scheduleStripWeekNavMarkup(1);
        root.innerHTML = html;
        syncScheduleWeekDayStripVisibility();
      }

      function scrollCalendarToDaySection(dateStr) {
        state.scheduleStripScrollSyncSuppressUntil = Date.now() + 900;
        var n = 0;
        function tryScroll() {
          var el = document.getElementById('cal-day-' + dateStr);
          if (el) {
            try {
              el.scrollIntoView({ behavior: 'smooth', block: 'start' });
            } catch (eScroll) {
              try {
                el.scrollIntoView(true);
              } catch (e2) { /* ignore */ }
            }
            return;
          }
          n++;
          if (n > 10) {
            var filterHint =
              state.slotFilter !== 'all'
                ? ' С фильтром «' +
                  (state.slotFilter === 'available' ? 'Свободны' : 'Заняты') +
                  '» этот день может быть скрыт.'
                : '';
            showToast('На этот день нет записей и слотов.' + filterHint);
            return;
          }
          requestAnimationFrame(tryScroll);
        }
        requestAnimationFrame(tryScroll);
      }

      /**
       * Bottom strip: pick a day — reveal past sessions when needed, scroll to that day.
       * Past weekdays and today's ended sessions stay hidden until the day is tapped.
       */
      function onScheduleStripPickDay(dateStr) {
        if (!dateStr || !/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return;
        var todayStr = dateToStr(new Date());
        var entirePast = isEntireWeekInPast(state.weekStart);
        state.scheduleStripSelectedDate = dateStr;
        if (!entirePast && dateStr > todayStr && state.showPastThisWeek) {
          state.showPastThisWeek = false;
          renderCalendar();
          scrollCalendarToDaySection(dateStr);
          return;
        }
        if (scheduleStripDayNeedsPastReveal(dateStr)) {
          state.showPastThisWeek = true;
          renderCalendar();
          scrollCalendarToDaySection(dateStr);
          return;
        }
        renderScheduleWeekDayStrip();
        scrollCalendarToDaySection(dateStr);
      }

      function applyPendingScheduleStripAnchorDate() {
        if (!state.pendingScheduleStripAnchorDate) return;
        var dateStr = state.pendingScheduleStripAnchorDate;
        state.pendingScheduleStripAnchorDate = null;
        requestAnimationFrame(function() {
          onScheduleStripPickDay(dateStr);
        });
      }

      /**
       * opts.onComplete — fired after successful fetch + render (e.g. return to day-pick only when slots are fresh).
       * opts.onLoadError — fired on fetch failure before error UI (e.g. still show day-pick after POST succeeded).
       */
      function loadSlots(opts) {
        opts = opts || {};
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        if (tg && !tg.initData) {
          loadSlots._waitInit = (loadSlots._waitInit || 0) + 1;
          if (loadSlots._waitInit < 200) {
            document.getElementById('calendarContent').innerHTML = buildCalendarSkeletonHtml();
            setTimeout(function() {
              callReadyWhenInitDataReady();
              loadSlots(opts);
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
        syncAddSlotsButtonEligibility();
        document.getElementById('calendarContent').innerHTML = buildCalendarSkeletonHtml();
        state.scheduleLoadInFlight = true;
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
            state.centerDuties = (data && data.center_duties && data.center_duties.length)
              ? data.center_duties
              : [];
            state.centerScheduleAdmin =
              data && data.center_schedule_admin && data.center_schedule_admin.collective_slug
                ? data.center_schedule_admin
                : null;
            prefetchScheduleBookingContexts();
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
            return loadTrainerServicesIfNeeded().then(function() {
              if (fromHubQuickBook) {
                requestAnimationFrame(function() {
                  renderCalendar();
                  applyPendingScheduleStripAnchorDate();
                });
              } else {
                renderCalendar();
                requestAnimationFrame(function() {
                  maybeShowScheduleWeekSwipeNavHintOnce();
                });
                applyPendingScheduleStripAnchorDate();
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
              if (typeof opts.onComplete === 'function') {
                try {
                  opts.onComplete();
                } catch (eCb) { /* ignore */ }
              }
              refreshScheduleEditorInboxCounts();
              syncScheduleEditorFormatChrome();
            });
          })
          .catch(function(err) {
            if (err === 'retry-init') {
              setTimeout(function() {
                loadSlots(opts);
              }, 100);
              return;
            }
            if (typeof opts.onLoadError === 'function') {
              try {
                opts.onLoadError(err);
              } catch (eLe) { /* ignore */ }
            }
            hideFlowBookBootOverlay();
            renderCalendarLoadFailure(err);
          })
          .finally(function() {
            state.scheduleLoadInFlight = false;
          });
      }

      function loadTemplates(opts) {
        opts = opts || {};
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        var templateList = document.getElementById('templateList');
        var softPersonalRefresh =
          opts.softPersonalRefresh && templateList && templateList.querySelector('.template-day-card');
        if (!softPersonalRefresh && templateList) {
          templateList.innerHTML = buildTemplateListSkeletonHtml();
        }
        var centerList = document.getElementById('centerGridTemplateList');
        var centerSection = document.getElementById('centerGridTemplateSection');
        var softCenterRefresh =
          opts.softCenterRefresh &&
          centerList &&
          centerList.querySelector('.template-day-card--center-grid');
        if (centerList && !softCenterRefresh) {
          centerList.innerHTML = buildTemplateListSkeletonHtml();
        }
        if (centerSection && !softCenterRefresh) {
          centerSection.hidden = true;
        }
        if (!state.weekStart) state.weekStart = getMonday(new Date());
        var weekEnd = new Date(state.weekStart);
        weekEnd.setDate(weekEnd.getDate() + 6);
        var from = dateToStr(state.weekStart);
        var to = dateToStr(weekEnd);
        Promise.all([
          fetch(apiUrlWithQuery('/schedule/templates'), { headers: headers() }).then(function(r) {
            return r.json();
          }),
          fetch(apiUrlWithQuery('/schedule?from_date=' + encodeURIComponent(from) + '&to_date=' + encodeURIComponent(to)), {
            headers: headers(),
          })
            .then(function(r) {
              if (!r.ok) return null;
              return r.json();
            })
            .catch(function() {
              return null;
            }),
        ])
          .then(function(results) {
            var data = results[0] || {};
            state.templates = data.templates || [];
            applyScheduleGridFromApi(data);
            var sched = results[1];
            if (sched) {
              state.slots = sched.slots || state.slots || [];
              state.centerScheduleAdmin =
                sched.center_schedule_admin && sched.center_schedule_admin.collective_slug
                  ? sched.center_schedule_admin
                  : null;
              if (sched.trainer_id != null && !isNaN(parseInt(String(sched.trainer_id), 10))) {
                state.trainerId = parseInt(String(sched.trainer_id), 10);
              }
            }
            renderTemplate();
          })
          .catch(function() {
            renderTemplateLoadFailure();
          });
      }

      function setCenterGridWeekNavBusy(busy) {
        var prevBtn = document.getElementById('centerGridWeekPrev');
        var nextBtn = document.getElementById('centerGridWeekNext');
        if (prevBtn) prevBtn.disabled = !!busy;
        if (nextBtn) nextBtn.disabled = !!busy;
      }

      /** Refresh only center grid block (week nav / duplicate) — no personal-template skeleton flash. */
      function loadCenterGridWeekData(opts) {
        opts = opts || {};
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        if (state.centerGridWeekLoadInFlight) return;
        if (!state.weekStart) state.weekStart = getMonday(new Date());
        var list = document.getElementById('centerGridTemplateList');
        if (list) list.classList.add('center-grid-template-list--loading');
        state.centerGridWeekLoadInFlight = true;
        setCenterGridWeekNavBusy(true);
        var weekEnd = new Date(state.weekStart);
        weekEnd.setDate(weekEnd.getDate() + 6);
        fetch(
          apiUrlWithQuery(
            '/schedule?from_date=' +
              encodeURIComponent(dateToStr(state.weekStart)) +
              '&to_date=' +
              encodeURIComponent(dateToStr(weekEnd))
          ),
          { headers: headers() }
        )
          .then(function(r) {
            if (!r.ok) return null;
            return r.json();
          })
          .then(function(sched) {
            if (sched) {
              state.slots = sched.slots || state.slots || [];
              state.centerScheduleAdmin =
                sched.center_schedule_admin && sched.center_schedule_admin.collective_slug
                  ? sched.center_schedule_admin
                  : null;
            }
            renderCenterGridTemplate();
            if (opts.syncCalendarWeekLabel) {
              var wl = document.getElementById('weekLabel');
              if (wl && state.weekStart) wl.textContent = formatWeekLabel(state.weekStart);
            }
          })
          .catch(function() {
            showToast('Не удалось обновить сетку центра');
          })
          .finally(function() {
            state.centerGridWeekLoadInFlight = false;
            setCenterGridWeekNavBusy(false);
            if (list) list.classList.remove('center-grid-template-list--loading');
          });
      }

      function formatQuickBookSlotLabel() {
        if (!state.quickBookSlotDate || state.quickBookStartMinutes == null) return '';
        var dsl = formatDateKey(state.quickBookSlotDate);
        return dsl + ' ' + formatMinuteClock(state.quickBookStartMinutes);
      }

      function quickBookCenterDutyConflict(startMinutes, durationMinutes, isoDate) {
        if (!scheduleEditorHasCenterDuties()) return null;
        var duties = scheduleCenterDutiesForDate(isoDate);
        var newEnd = startMinutes + durationMinutes;
        var startLabel = formatMinuteClock(startMinutes);
        var endLabel = formatMinuteClock(newEnd);
        for (var i = 0; i < duties.length; i++) {
          var d = duties[i];
          if (scheduleRangesOverlap(startLabel, endLabel, d.start_time, d.end_time)) {
            return d;
          }
        }
        return null;
      }

      /**
       * free — можно создать/использовать слот; busy — занято; group — группа;
       * past — уже прошло; overlap — пересечение с другим слотом при этой длительности; invalid — не влезает в сутки.
       * center_duty — пересечение со сменой в центре (ADR §6).
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
        if (quickBookCenterDutyConflict(startMinutes, dm, isoDate)) return 'center_duty';
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
          document.documentElement.classList.remove('se-flow-book-boot', 'se-open-booking-boot');
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
              } else if (av === 'center_duty') {
                opt.disabled = true;
                opt.textContent = label + ' — смена в центре';
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
        if (!assertScheduleCrmWriteAllowed()) return;
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
       * After datetime, when client_id is in URL: load services + booking defaults
       * (post-session: ?from_booking_id= → that row; else latest by created_at),
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
        var defPath = '/trainer/clients/' + encodeURIComponent(cid) + '/booking-defaults';
        if (state.presetBookingDefaultsId) {
          defPath += '?from_booking_id=' + encodeURIComponent(String(state.presetBookingDefaultsId));
        }
        Promise.all([
          fetch(apiUrlWithQuery('/trainer/my-services'), { headers: headers() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('svc'));
          }),
          fetch(apiUrlWithQuery(defPath), { headers: headers() }).then(function(r) {
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
              state.presetBookingDefaultsId = null;
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
            var srcBooking =
              state.rescheduleSourceBookingId &&
              state.selectedBooking &&
              Number(state.selectedBooking.id) === Number(state.rescheduleSourceBookingId)
                ? state.selectedBooking
                : null;
            if (srcBooking && srcBooking.arena_id != null) {
              var ra = parseInt(srcBooking.arena_id, 10);
              if (!isNaN(ra) && arenas.some(function(a) { return Number(a.id) === ra; })) {
                state.bookArenaId = ra;
              }
            } else if (defaults.arena_id != null) {
              var da = parseInt(defaults.arena_id, 10);
              if (!isNaN(da) && arenas.some(function(a) { return Number(a.id) === da; })) {
                state.bookArenaId = da;
              }
            }
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
            if (srcBooking && srcBooking.service_id != null) {
              var osid = parseInt(srcBooking.service_id, 10);
              if (!isNaN(osid) && state.bookServices.some(function(s) { return Number(s.id) === osid; })) {
                defSid = osid;
              }
            }
            var picked = state.bookServices.length ? Number(state.bookServices[0].id) : null;
            if (!isNaN(defSid) && state.bookServices.some(function(s) { return Number(s.id) === defSid; })) {
              picked = defSid;
            }
            state.bookServiceId = picked;
            sel.value = picked != null ? String(picked) : '';
            sel.onchange = function() {
              state.bookServiceId = this.value ? parseInt(this.value, 10) : null;
              syncQuickBookProfilePriceTierRadios(null, null);
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
            if (srcBooking && srcBooking.service_price_variant_id != null) {
              var ov = parseInt(srcBooking.service_price_variant_id, 10);
              if (!isNaN(ov)) defVid = ov;
            }
            syncQuickBookProfilePriceTierRadios(defVid, defaults.price_tier_kind);
            state.presetBookingDefaultsId = null;

            updateTelegramBack();
            if (finishBtn) finishBtn();
          })
          .catch(function() {
            setQuickBookProfileServiceLoading(false);
            state.bookFlowQuick = false;
            state.quickBookProfileServiceStep = false;
            state.quickBookLockedClientId = null;
            state.presetBookingDefaultsId = null;
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

      /** Calendar book modal: same landing as hub — search roster + chip (hide legacy two-button step). */
      function scheduleBookModalShowClientSearchFirstLayout() {
        document.getElementById('bookStepChoice').style.display = 'none';
        document.getElementById('bookStepChoice').classList.remove('active');
        document.getElementById('bookStepExisting').style.display = 'block';
        document.getElementById('bookStepExisting').classList.add('active');
        document.getElementById('bookStepNew').style.display = 'none';
        document.getElementById('bookStepNew').classList.remove('active');
        setBookClientSearchSectionVisible(true);
        showBookExistingClientStep();
      }

      /** Keep #bookStepNew above cancel inside modal (hub parity — full-screen new-client step). */
      function dockBookStepNewUnderModalChrome() {
        var slotOv = document.getElementById('modalBookClient');
        if (!slotOv) return;
        var modal = slotOv.querySelector('.modal.book-flow-modal');
        var nw = document.getElementById('bookStepNew');
        var cancelBtn = document.getElementById('modalBookCancel');
        var backNew = document.getElementById('bookBackFromNew');
        if (!modal || !nw || !cancelBtn) return;
        if (nw.parentNode !== modal) {
          modal.insertBefore(nw, cancelBtn);
        }
        if (backNew) backNew.style.display = '';
      }

      /** Hide service/tariff/arena on new-client-only overlay (hub «Записать клиента» parity). */
      function setBookNewClientOnlyFieldsVisible(clientOnly) {
        ['bookServiceStackNew', 'bookPriceTierWrapNew', 'bookArenaWrapNew'].forEach(function(id) {
          var el = document.getElementById(id);
          if (el) el.style.display = clientOnly ? 'none' : '';
        });
      }

      function applyBookNewSubmitButtonLabel() {
        var btn = document.getElementById('bookNewSubmit');
        if (!btn) return;
        btn.textContent = state.bookSlotId || state.bookFlowQuick ? 'Далее' : 'Добавить и записать';
      }

      /** After POST /trainer/clients: service/tariff step inside bookStepExisting (same as roster pick). */
      function scheduleTransitionToServiceStepAfterNewClient(clientId, displayName) {
        var bookOv = document.getElementById('modalBookClient');
        if (bookOv) bookOv.classList.remove('book-flow-overlay--new-client');
        var nw = document.getElementById('bookStepNew');
        if (nw) {
          nw.style.display = 'none';
          nw.classList.remove('active');
        }
        var ex = document.getElementById('bookStepExisting');
        if (ex) {
          ex.style.display = 'block';
          ex.classList.add('active');
        }
        state.bookModalStep = 'existing';
        state.bookServiceStepFromNewClient = true;
        var leadHint =
          ((displayName || '').trim() || 'Клиент') + ' — выберите услугу и тариф.';
        enterBookExistingServiceStepFromClient(clientId, displayName, {
          fromNewClient: true,
          leadHint: leadHint,
        });
        updateTelegramBack();
      }

      /** Hub parity: swap client list for dedicated new-client step (not inline under search). */
      function scheduleGoBookNewClientFlow() {
        dockBookStepNewUnderModalChrome();
        var bookOvNew = document.getElementById('modalBookClient');
        if (bookOvNew) bookOvNew.classList.add('book-flow-overlay--new-client');
        var ch = document.getElementById('bookStepChoice');
        var ex = document.getElementById('bookStepExisting');
        var nw = document.getElementById('bookStepNew');
        if (ch) {
          ch.style.display = 'none';
          ch.classList.remove('active');
        }
        if (ex) {
          ex.style.display = 'none';
          ex.classList.remove('active');
        }
        if (nw) {
          nw.style.display = 'block';
          nw.classList.add('active');
        }
        state.bookModalStep = 'new';
        setBookNewClientOnlyFieldsVisible(true);
        applyBookNewSubmitButtonLabel();
        updateTelegramBack();
      }

      function scheduleReturnFromNewClientToQuickSearch() {
        state.bookServiceStepFromNewClient = false;
        setBookNewClientOnlyFieldsVisible(false);
        var bookOv = document.getElementById('modalBookClient');
        if (bookOv) bookOv.classList.remove('book-flow-overlay--new-client');
        var nw = document.getElementById('bookStepNew');
        if (nw) {
          nw.style.display = 'none';
          nw.classList.remove('active');
        }
        if (state.bookModalClientSearchFirst) {
          scheduleBookModalShowClientSearchFirstLayout();
          var qinp = document.getElementById('bookClientSearch');
          loadBookClients(qinp ? qinp.value.trim() : '');
          state.bookModalStep = 'existing';
          updateTelegramBack();
          return;
        }
        var ch = document.getElementById('bookStepChoice');
        if (ch) {
          ch.style.display = 'block';
          ch.classList.add('active');
        }
        state.bookModalStep = 'choice';
        updateTelegramBack();
      }

      /** Loads services/clients and wires book modal (shared by slot-based and quick book). */
      function runBookModalShellAndFetch() {
        var prefilledClient = !!state.deepLinkClientId;
        var shellKind = scheduleResolveBookShellKind(prefilledClient);
        state.bookModalClientSearchFirst = !prefilledClient && shellKind === 'clients';
        state.bookModalStep = shellKind === 'context' ? 'context' : 'existing';
        var bookModalOv = document.getElementById('modalBookClient');
        if (bookModalOv) bookModalOv.classList.remove('book-flow-overlay--new-client');
        document.getElementById('bookClientSearch').value = '';
        document.getElementById('bookNewPhone').value = '';
        document.getElementById('bookNewFirstName').value = '';
        document.getElementById('bookNewLastName').value = '';
        state.bookContextKind = 'personal_slot';
        state.bookSessionContextId = null;
        state.bookCollectiveSlug = null;
        state.bookCenterSession = null;
        state.bookCenterClientId = null;
        document.querySelectorAll('.book-step').forEach(function(step) { step.classList.remove('active'); step.style.display = 'none'; });
        if (shellKind === 'profile') {
          document.getElementById('bookStepExisting').style.display = 'block';
          document.getElementById('bookStepExisting').classList.add('active');
          document.getElementById('bookStepNew').style.display = 'none';
          document.getElementById('bookClientList').innerHTML = buildBookClientListSkeletonHtml();
          setBookClientSearchSectionVisible(false);
          showBookExistingClientStep();
          state.bookModalClientSearchFirst = false;
        } else if (shellKind === 'context') {
          state.bookContexts = state.bookContextsPrefetch;
          showBookStep('bookStepContext');
          if (state.bookContextsPrefetch) {
            renderBookContextStep(state.bookContextsPrefetch, null, function() {
              scheduleBookModalShowClientSearchFirstLayout();
              loadBookClients('');
            });
          } else {
            var ctxWrap = document.getElementById('bookContextActions');
            if (ctxWrap) ctxWrap.innerHTML = '<p class="book-choice-lead">Загрузка…</p>';
          }
        } else if (shellKind === 'prepare') {
          document.getElementById('bookStepExisting').style.display = 'block';
          document.getElementById('bookStepExisting').classList.add('active');
          setBookClientSearchSectionVisible(false);
          document.getElementById('bookClientList').innerHTML = buildBookClientListSkeletonHtml();
        } else {
          if (state.bookContextsPrefetch) {
            state.bookContexts = state.bookContextsPrefetch;
            var firstCtx = (window.TrainerBookingContext
              ? TrainerBookingContext.normalizePayload(state.bookContextsPrefetch)
              : state.bookContextsPrefetch).contexts;
            applyBookContextSelection((firstCtx || [])[0] || null, null);
          }
          scheduleBookModalShowClientSearchFirstLayout();
          document.getElementById('bookClientList').innerHTML = buildBookClientListSkeletonHtml();
        }
        setBookChoicePairPending(false);
        document.getElementById('modalBookClient').style.display = 'flex';
        applyBookModalGroupUi();
        updateTelegramBack();
        Promise.all([
          fetch(apiUrlWithQuery('/trainer/my-services'), { headers: headers() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('Ошибка'));
          }),
          fetch(apiUrlWithQuery('/trainer/clients'), { headers: headers() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('Ошибка'));
          }),
          fetchBookingContexts(),
        ])
          .then(function(results) {
            var data = results[0];
            var clientsPayload = results[1];
            var ctxPayload = results[2];
            state.bookContexts = ctxPayload;
            state.bookContextsPrefetch = ctxPayload;
            if (!prefilledClient && ctxPayload) {
              var ctxStepEl = document.getElementById('bookStepContext');
              var contextStepOpen =
                ctxStepEl &&
                ctxStepEl.style.display !== 'none' &&
                String(ctxStepEl.style.display || '').toLowerCase() !== '';
              if (contextStepOpen && scheduleBookContextsNeedPicker(ctxPayload)) {
                renderBookContextStep(ctxPayload, null, function() {
                  scheduleBookModalShowClientSearchFirstLayout();
                  loadBookClients('');
                });
              } else if (!contextStepOpen) {
                var normalizedCtx = window.TrainerBookingContext
                  ? TrainerBookingContext.normalizePayload(ctxPayload)
                  : ctxPayload;
                if (scheduleBookContextsNeedPicker(normalizedCtx)) {
                  renderBookContextStep(ctxPayload, null, function() {
                    scheduleBookModalShowClientSearchFirstLayout();
                    loadBookClients('');
                  });
                  showBookStep('bookStepContext');
                } else {
                  applyBookContextSelection((normalizedCtx.contexts || [])[0] || null, null);
                  if (shellKind === 'prepare') {
                    scheduleBookModalShowClientSearchFirstLayout();
                    setBookClientSearchSectionVisible(true);
                    loadBookClients('');
                  }
                }
              }
            }
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
              state.bookModalClientSearchFirst = true;
              scheduleBookModalShowClientSearchFirstLayout();
              document.getElementById('bookClientList').innerHTML = buildBookClientListSkeletonHtml();
              state.bookModalStep = 'existing';
              loadBookClients('');
            } else if (state.bookModalClientSearchFirst) {
              var ctxStepEl = document.getElementById('bookStepContext');
              var waitingForContext =
                ctxStepEl &&
                ctxStepEl.style.display !== 'none' &&
                String(ctxStepEl.style.display || '').toLowerCase() !== '';
              if (!waitingForContext) {
                loadBookClients('');
              }
            }
            scheduleRevealBookChoicePairIfNeeded();
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
            }
            state.bookModalClientSearchFirst = true;
            scheduleBookModalShowClientSearchFirstLayout();
            document.getElementById('bookClientList').innerHTML = buildBookClientListSkeletonHtml();
            state.bookModalStep = 'existing';
            setBookChoicePairPending(false);
            loadBookClients('');
            scheduleRevealBookChoicePairIfNeeded();
          });
      }

      /** Quick book from hub: date/time chosen — no slot row in state yet. */
      function openBookModalForQuickFlow() {
        if (!assertScheduleCrmWriteAllowed()) return;
        state.bookSlotId = null;
        state.bookFlowQuick = true;
        state.bookPriceVariantId = null;
        state.bookSlotIsGroup = false;
        state.bookSlotGroupServiceId = null;
        runBookModalShellAndFetch();
      }

      /** Opens the book-client flow for a slot id (used by calendar row and group hub). */
      function openBookModalForSlot(slotId) {
        if (!assertScheduleCrmWriteAllowed()) return;
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
            var sandboxPill = b.is_sandbox
              ? ' <span class="schedule-sandbox-pill schedule-sandbox-pill--inline" role="status">тест</span>'
              : '';
            var bid = parseInt(b.booking_id, 10);
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'group-slot-row';
            btn.innerHTML =
              '<span><span class="g-name">' + escapeHtml(String(b.client_preview || 'Клиент')) + sandboxPill +
              '</span><br><span class="g-st">' + stLabel + '</span></span><span aria-hidden="true" style="color:var(--tg-theme-hint-color);font-size:18px;">›</span>';
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

      function findCenterDutyBySessionId(sessionId, dateKey) {
        var rows = scheduleCenterOverlayRowsForDate(dateKey);
        for (var i = 0; i < rows.length; i++) {
          if (Number(rows[i].collective_session_id) === Number(sessionId)) return rows[i];
        }
        return null;
      }

      function resolveCenterSessionFromDuty(duty) {
        if (!duty) return null;
        var sid = duty.collective_session_id;
        var admin = state.centerScheduleAdmin;
        if (admin && admin.sessions) {
          for (var i = 0; i < admin.sessions.length; i++) {
            if (Number(admin.sessions[i].id) === Number(sid)) return admin.sessions[i];
          }
        }
        return {
          id: sid,
          slot_date: duty.slot_date,
          start_time: duty.start_time,
          end_time: duty.end_time,
          capacity: duty.capacity != null ? duty.capacity : 1,
          booked_count: duty.booked_count || 0,
          assigned_coaches: [],
        };
      }

      function centerDutyCollectiveSlug(duty) {
        if (duty && duty.collective_slug) return duty.collective_slug;
        var admin = state.centerScheduleAdmin;
        return admin && admin.collective_slug ? admin.collective_slug : null;
      }

      function isCenterDutyEndedInPast(duty) {
        if (!duty || !duty.slot_date) return false;
        var today = dateToStr(new Date());
        if (String(duty.slot_date).slice(0, 10) < today) return true;
        if (String(duty.slot_date).slice(0, 10) > today) return false;
        var endM = parseStartToMinutes(duty.end_time || duty.start_time || '23:59');
        var now = new Date();
        return now.getHours() * 60 + now.getMinutes() >= endM;
      }

      function closeCenterSessionModal() {
        var mgr = document.getElementById('modalCenterSession');
        if (!mgr) return;
        mgr.style.display = 'none';
        mgr.setAttribute('aria-hidden', 'true');
        state.centerSessionModalDuty = null;
        updateTelegramBack();
      }

      function openCenterDayEditFromCalendar(slotDate, returnTo) {
        if (!assertScheduleCrmWriteAllowed()) return;
        if (!hasCenterScheduleAdmin()) return;
        closeCenterSessionModal();
        state.slotEditIntent = 'center';
        state.centerEditReturn = returnTo || 'calendar';
        openEditCalendarDay(slotDate);
        window.scrollTo(0, 0);
      }

      function openCenterDayEditFromTemplate(slotDate) {
        openCenterDayEditFromCalendar(slotDate, 'template');
      }

      /** Leave center day editor back to day-pick, template tab, or calendar. */
      function finishCenterCalendarEdit(opts) {
        opts = opts || {};
        document.getElementById('screenEdit').style.display = 'none';
        state.editMode = null;
        state.editDate = null;
        resetCenterEditCoachIds();
        state.calendarBaselineStarts = null;
        state.selectedStarts = new Set();
        state.lockedStarts = new Set();
        var ret = state.centerEditReturn || 'daypick';
        state.centerEditReturn = null;
        if (ret === 'template') {
          var scrollY = window.scrollY || 0;
          showMain({ skipTemplateReload: true });
          if (opts.refreshCenterGrid) loadCenterGridWeekData();
          requestAnimationFrame(function() {
            window.scrollTo(0, scrollY);
          });
          return;
        }
        if (ret === 'calendar') {
          loadSlots();
          showMain({ skipTemplateReload: true });
          return;
        }
        loadSlots({
          onComplete: function() {
            showDayPickScreen();
          },
          onLoadError: function() {
            showDayPickScreen();
          },
        });
      }

      function centerSessionsForWeekStart(weekStart) {
        var admin = state.centerScheduleAdmin;
        if (!admin || !weekStart) return [];
        var mon = dateToStr(weekStart);
        var end = new Date(weekStart);
        end.setDate(end.getDate() + 6);
        var sun = dateToStr(end);
        return (admin.sessions || []).filter(function(s) {
          var d = String(s.slot_date || '');
          return d >= mon && d <= sun;
        });
      }

      function renderCenterGridTemplate() {
        var section = document.getElementById('centerGridTemplateSection');
        if (!section) return;
        var show = hasCenterScheduleAdmin();
        section.hidden = !show;
        if (!show) return;
        var admin = state.centerScheduleAdmin;
        var titleEl = document.getElementById('centerGridTemplateTitle');
        if (titleEl && admin && admin.collective_name) {
          titleEl.textContent = admin.collective_name + ' · сетка';
        }
        var weekLabel = document.getElementById('centerGridWeekLabel');
        if (weekLabel && state.weekStart) {
          weekLabel.textContent = formatWeekLabel(state.weekStart);
        }
        var list = document.getElementById('centerGridTemplateList');
        if (!list || !state.weekStart) return;
        var byDate = {};
        centerSessionsForWeekStart(state.weekStart).forEach(function(s) {
          var key = String(s.slot_date || '');
          if (!byDate[key]) byDate[key] = [];
          var cap = s.capacity != null ? parseInt(String(s.capacity), 10) : 1;
          var timeShort = (s.start_time || '').toString().substring(0, 5);
          byDate[key].push(cap > 1 ? timeShort + ' ×' + cap : timeShort);
        });
        var html = '';
        var todayStr = dateToStr(new Date());
        for (var i = 0; i < 7; i++) {
          var d = new Date(state.weekStart);
          d.setDate(d.getDate() + i);
          var dateStr = dateToStr(d);
          var times = (byDate[dateStr] || []).sort(function(a, b) {
            return String(a).localeCompare(String(b));
          });
          var slotsText = times.length ? times.join(', ') : 'Нет окон';
          var past = dateStr < todayStr;
          html +=
            '<button type="button" class="template-day-card template-day-card--center-grid' +
            (past ? ' template-day-card--past' : '') +
            '" data-center-date="' +
            escapeHtml(dateStr) +
            '"' +
            (past ? ' disabled' : '') +
            ' aria-label="' +
            escapeHtml(DAYS[i] + ', ' + formatDateKey(dateStr) + ', ' + slotsText) +
            '">';
          html += '<span class="center-grid-day-block">';
          html += '<span class="day-name">' + DAYS[i] + '</span>';
          html += '<span class="day-date">' + escapeHtml(formatDateKeyNoWeekday(dateStr)) + '</span>';
          html += '</span>';
          html +=
            '<span class="day-slots ' +
            (times.length ? '' : 'empty') +
            '">' +
            escapeHtml(slotsText) +
            '</span>';
          html += '<span class="arrow" aria-hidden="true">' + (past ? '—' : '›') + '</span></button>';
        }
        list.innerHTML = html;
        list.querySelectorAll('.template-day-card--center-grid:not([disabled])').forEach(function(btn) {
          btn.onclick = function() {
            openCenterDayEditFromTemplate(btn.getAttribute('data-center-date'));
          };
        });
        syncScheduleEditorFormatChrome();
      }

      function postCenterDuplicateWeek(sourceWeekStart, weeksAhead) {
        var admin = state.centerScheduleAdmin;
        if (!admin || !admin.collective_slug) {
          return Promise.reject(new Error('Нет данных центра'));
        }
        return fetch(
          apiUrlWithQuery(
            '/trainer/collective/sessions/duplicate-week?collective_slug=' +
              encodeURIComponent(admin.collective_slug)
          ),
          {
            method: 'POST',
            headers: headers(),
            body: JSON.stringify({
              source_week_start: sourceWeekStart,
              weeks_ahead: weeksAhead,
            }),
          }
        ).then(function(r) {
          return r.json().then(function(d) {
            if (!r.ok) throw new Error((d && d.detail) || 'duplicate_failed');
            return d;
          });
        });
      }

      function runCenterGridDuplicate(sourceWeekStart, weeksAhead, confirmText) {
        if (!assertScheduleCrmWriteAllowed()) return;
        if (!hasCenterScheduleAdmin() || !sourceWeekStart) return;
        showAppConfirm(confirmText, { okText: 'Скопировать', cancelText: 'Отмена' }).then(function(ok) {
          if (!ok) return;
          var copyBtns = [
            document.getElementById('btnCenterGridCopyPrev'),
            document.getElementById('btnCenterGridCopyNext'),
            document.getElementById('btnCenterGridCopyAhead'),
          ];
          copyBtns.forEach(function(b) {
            if (b) b.disabled = true;
          });
          postCenterDuplicateWeek(sourceWeekStart, weeksAhead)
            .then(function(d) {
              var msg = 'Добавлено окон: ' + (d.created_count || 0);
              if (d.skipped_count) msg += ', пропущено: ' + d.skipped_count;
              showToast(msg, 2800);
              loadCenterGridWeekData();
            })
            .catch(function(e) {
              showToast(e.message || 'Не удалось скопировать');
            })
            .finally(function() {
              copyBtns.forEach(function(b) {
                if (b) b.disabled = false;
              });
            });
        });
      }

      function openBookModalForCenterSession(session, collectiveSlug) {
        if (!assertScheduleCrmWriteAllowed()) return;
        if (!session || session.id == null || !collectiveSlug) return;
        closeCenterSessionModal();
        state.bookFlowQuick = false;
        state.bookSlotId = null;
        state.bookCenterSession = session;
        state.bookCenterSessions = [session];
        state.bookCollectiveSlug = collectiveSlug;
        state.bookContextKind = 'center_session';
        state.bookCenterClientId = null;
        state.bookModalClientSearchFirst = true;
        state.bookModalStep = 'existing';
        var bookModalOv = document.getElementById('modalBookClient');
        if (bookModalOv) bookModalOv.classList.remove('book-flow-overlay--new-client');
        var searchEl = document.getElementById('bookClientSearch');
        if (searchEl) searchEl.value = '';
        document.querySelectorAll('.book-step').forEach(function(step) {
          step.classList.remove('active');
          step.style.display = 'none';
        });
        scheduleBookModalShowClientSearchFirstLayout();
        var listEl = document.getElementById('bookClientList');
        if (listEl) listEl.innerHTML = buildBookClientListSkeletonHtml();
        if (bookModalOv) bookModalOv.style.display = 'flex';
        applyBookModalGroupUi();
        updateTelegramBack();
        Promise.all([
          fetch(apiUrlWithQuery('/trainer/my-services'), { headers: headers() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('Ошибка'));
          }),
          fetch(clientsRequestUrl(''), { headers: headers() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('Ошибка'));
          }),
        ])
          .then(function(results) {
            state.bookServices = (results[0] && results[0].services) || [];
            state.trainerHasBookClients = !!(results[1].clients && results[1].clients.length);
            loadBookClients('');
          })
          .catch(function() {
            loadBookClients('');
          });
      }

      function cancelCenterSessionWindow(session, collectiveSlug) {
        if (!assertScheduleCrmWriteAllowed()) return;
        if (!session || session.id == null || !collectiveSlug) return;
        if ((session.booked_count || 0) > 0) {
          showToast('Нельзя снять окно с записями');
          return;
        }
        showAppConfirm('Снять это окно центра?', { okText: 'Снять', cancelText: 'Отмена' }).then(function(ok) {
          if (!ok) return;
          fetch(
            apiUrlWithQuery(
              '/trainer/collective/sessions/' +
                encodeURIComponent(String(session.id)) +
                '?collective_slug=' +
                encodeURIComponent(collectiveSlug)
            ),
            { method: 'DELETE', headers: headers() }
          )
            .then(function(r) {
              return r.json().then(function(d) {
                if (!r.ok) throw new Error((d && d.detail) || 'delete_failed');
              });
            })
            .then(function() {
              closeCenterSessionModal();
              showToast('Окно центра снято');
              loadSlots();
            })
            .catch(function(e) {
              showToast(e.message || 'Не удалось снять окно');
            });
        });
      }

      function openCenterSessionModal(duty) {
        if (!duty) return;
        var session = resolveCenterSessionFromDuty(duty);
        if (!session) return;
        var mgr = document.getElementById('modalCenterSession');
        if (!mgr) return;
        state.centerSessionModalDuty = duty;
        mgr.style.display = 'flex';
        mgr.setAttribute('aria-hidden', 'false');
        var cap = parseInt(String(session.capacity != null ? session.capacity : 1), 10);
        if (isNaN(cap) || cap < 1) cap = 1;
        var booked = parseInt(String(session.booked_count || 0), 10) || 0;
        var spotsLeft = Math.max(0, cap - booked);
        var slug = centerDutyCollectiveSlug(duty);
        var centerName = duty.collective_name || (state.centerScheduleAdmin && state.centerScheduleAdmin.collective_name) || 'Центр';
        var kicker = document.getElementById('centerSessionKicker');
        if (kicker) kicker.textContent = centerName;
        var titleEl = document.getElementById('centerSessionTitle');
        if (titleEl) {
          titleEl.textContent = (session.start_time || '') + '–' + (session.end_time || '');
        }
        var subEl = document.getElementById('centerSessionSub');
        if (subEl) {
          var sub =
            formatDateKey(session.slot_date || duty.slot_date) +
            ' · ' +
            booked +
            '/' +
            cap +
            ' записей';
          if (spotsLeft > 0) sub += ' · свободно мест: ' + spotsLeft;
          else sub += ' · окно заполнено';
          subEl.textContent = sub;
        }
        var coachesEl = document.getElementById('centerSessionCoaches');
        var coaches = session.assigned_coaches || [];
        if (coachesEl) {
          if (coaches.length) {
            coachesEl.hidden = false;
            coachesEl.innerHTML = coaches
              .map(function(c) {
                var isSelf =
                  state.trainerId != null &&
                  parseInt(String(c.trainer_id), 10) === parseInt(String(state.trainerId), 10);
                return (
                  '<span class="center-session-coach-pill">' +
                  escapeHtml(isSelf ? 'Я' : c.display_name || 'Тренер #' + c.trainer_id) +
                  '</span>'
                );
              })
              .join('');
          } else {
            coachesEl.hidden = true;
            coachesEl.innerHTML = '';
          }
        }
        var metaEl = document.getElementById('centerSessionMeta');
        if (metaEl) {
          if (duty.admin_overlay && hasCenterScheduleAdmin()) {
            metaEl.textContent = 'Окно сетки центра — можно редактировать часы дня или записать клиента.';
          } else if (booked > 0) {
            metaEl.textContent = 'Активные записи учитываются в загрузке окна. Детали — в заявках центра.';
          } else {
            metaEl.textContent = 'Смена центра — запишите клиента в это окно.';
          }
        }
        var past = isCenterDutyEndedInPast(duty);
        var canWrite = !!state.scheduleCrmWriteAllowed;
        var isAdmin = hasCenterScheduleAdmin();
        var bookBtn = document.getElementById('centerSessionBookBtn');
        var editBtn = document.getElementById('centerSessionEditBtn');
        var cancelBtn = document.getElementById('centerSessionCancelBtn');
        if (bookBtn) {
          bookBtn.hidden = true;
          bookBtn.onclick = null;
        }
        if (editBtn) {
          editBtn.hidden = true;
          editBtn.onclick = null;
        }
        if (cancelBtn) {
          cancelBtn.hidden = true;
          cancelBtn.onclick = null;
        }
        if (bookBtn && !past && spotsLeft > 0 && canWrite && slug) {
          bookBtn.hidden = false;
          bookBtn.onclick = function() {
            openBookModalForCenterSession(session, slug);
          };
        }
        if (editBtn && isAdmin && canWrite && !past) {
          editBtn.hidden = false;
          editBtn.onclick = function() {
            openCenterDayEditFromCalendar(session.slot_date || duty.slot_date);
          };
        }
        if (cancelBtn && isAdmin && canWrite && !past && booked === 0 && slug) {
          cancelBtn.hidden = false;
          cancelBtn.onclick = function() {
            cancelCenterSessionWindow(session, slug);
          };
        }
        updateTelegramBack();
      }

      function scheduleEditorHasCenterDuties() {
        if (state.centerDuties && state.centerDuties.length) return true;
        return !!(state.centerScheduleAdmin && state.centerScheduleAdmin.sessions && state.centerScheduleAdmin.sessions.length);
      }

      function scheduleTimeToMinutes(hhmm) {
        if (!hhmm) return 0;
        var parts = String(hhmm).split(':');
        return parseInt(parts[0], 10) * 60 + parseInt(parts[1] || '0', 10);
      }

      function scheduleRangesOverlap(aStart, aEnd, bStart, bEnd) {
        return scheduleTimeToMinutes(aStart) < scheduleTimeToMinutes(bEnd)
          && scheduleTimeToMinutes(bStart) < scheduleTimeToMinutes(aEnd);
      }

      function scheduleCenterOverlayRowsForDate(dateKey) {
        var rows = scheduleCenterDutiesForDate(dateKey).slice();
        var admin = state.centerScheduleAdmin;
        if (!admin || !admin.sessions || !admin.sessions.length) return rows;
        var seen = {};
        rows.forEach(function(r) {
          seen[r.collective_session_id] = true;
        });
        admin.sessions.forEach(function(s) {
          if (s.slot_date !== dateKey || seen[s.id]) return;
          rows.push({
            kind: 'center_duty',
            collective_session_id: s.id,
            collective_id: s.collective_id,
            collective_name: admin.collective_name || 'Центр',
            collective_slug: admin.collective_slug,
            slot_date: s.slot_date,
            start_time: s.start_time,
            end_time: s.end_time,
            capacity: s.capacity,
            booked_count: s.booked_count || 0,
            status: s.status,
            admin_overlay: true,
          });
        });
        return rows.sort(function(a, b) {
          return (a.start_time || '').localeCompare(b.start_time || '');
        });
      }

      function scheduleCenterDutiesForDate(dateKey) {
        if (!scheduleEditorHasCenterDuties()) return [];
        return (state.centerDuties || []).filter(function(d) { return d.slot_date === dateKey; });
      }

      function renderScheduleCenterDutyRowHtml(duty, daySlots) {
        var overlap = (daySlots || []).some(function(s) {
          return scheduleRangesOverlap(s.start_time, s.end_time, duty.start_time, duty.end_time);
        });
        var title = 'Смена · ' + escapeHtml(duty.collective_name || 'Центр');
        var meta = (duty.booked_count || 0) + '/' + (duty.capacity || 1) + ' записей';
        var sid = duty.collective_session_id;
        return (
          '<div class="slot-row slot-row-center-duty slot-row-center-duty--clickable' +
          (overlap ? ' slot-row-center-duty--overlap' : '') +
          '" role="button" tabindex="0" data-center-session-id="' +
          escapeHtml(String(sid)) +
          '" data-center-slot-date="' +
          escapeHtml(String(duty.slot_date || '')) +
          '">'
          + '<div class="slot-row-left">'
          + '<div class="slot-time-row"><span class="slot-time">' + escapeHtml(duty.start_time || '') + '–' + escapeHtml(duty.end_time || '') + '</span></div>'
          + '<div class="slot-cohort-hint">' + title + '</div>'
          + '<div class="slot-client-hint">' + escapeHtml(meta) + '</div>'
          + '</div>'
          + '<div class="slot-meta"><span class="slot-status slot-status-center-duty">центр</span><span aria-hidden="true" class="slot-row-chevron">›</span></div>'
          + '</div>'
        );
      }

      /** Personal/group slot row — extracted so center duties can merge into the day timeline. */
      function renderCalendarDaySlotRowHtml(s) {
        const status = s.status || 'available';
        const cap = (s.capacity != null) ? parseInt(s.capacity, 10) : 1;
        const occ = (s.active_bookings != null) ? parseInt(s.active_bookings, 10) : 0;
        const spotsLeft = (s.spots_left != null) ? parseInt(s.spots_left, 10) : Math.max(0, cap - occ);
        const cohortSlot = !!(s.training_group_id);
        const available = status === 'available' && spotsLeft > 0;
        const bookableAvailable = available && !cohortSlot;
        const slotPast = isSlotEndedInPast(s);
        const groupHub = cap > 1 && occ > 1 && !cohortSlot;
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
        var serviceBadge = '';
        if (groupHub || bookedClick) {
          serviceBadge = scheduleEditorServiceBadgeHtml(s.service_id, s.service_label);
        }
        var html = '<div class="slot-row' + (slotPast ? ' slot-past' : '')
          + (cohortSlot ? ' slot-cohort' : '')
          + (groupHub ? ' slot-group-hub' : '')
          + (!groupHub && bookableAvailable ? ' slot-available' : '')
          + (!groupHub && bookedClick ? ' slot-booked-click' : '')
          + (bookingPending ? ' slot-booking-pending' : '')
          + (bookingConfirmed ? ' slot-booking-confirmed' : '')
          + (bookingCompleted ? ' slot-booking-completed' : '')
          + '"'
          + (!groupHub && bookableAvailable ? ' data-slot-id="' + s.id + '" role="button" tabindex="0"' : '')
          + (groupHub ? ' data-slot-id="' + s.id + '" data-group-hub="1" role="button" tabindex="0"' : '')
          + (cohortSlot ? ' data-training-group-id="' + String(s.training_group_id) + '" role="button" tabindex="0"' : '')
          + (!groupHub && bookedClick ? ' data-booking-id="' + s.booking_id + '" role="button" tabindex="0"' : '')
          + (!groupHub && bookedClick ? ' data-booking-status="' + escapeHtml(bst) + '"' : '')
          + '>';
        html += '<div class="slot-row-left">';
        html += '<div class="slot-time-row">';
        html += '<span class="slot-time">' + escapeHtml(s.start_time || '') + '–' + escapeHtml(s.end_time || '') + '</span>';
        if (s.has_sandbox_booking && !groupHub) {
          html += '<span class="schedule-sandbox-pill" role="status" aria-label="Тестовая запись">тест</span>';
        }
        if (!bookedClick && !groupHub && !cohortSlot) {
          html += scheduleEditorArenaChipHtml(s.arena_id, s.arena_label);
        }
        html += '</div>';
        if (serviceBadge) {
          html += '<div class="slot-service-badge-row">' + serviceBadge + '</div>';
        }
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
          if (s.has_sandbox_booking) {
            html += '<span class="schedule-sandbox-pill schedule-sandbox-pill--inline" role="status">тест</span>';
          }
          if (spotsLeft > 0) {
            html += '<span class="slot-status available" style="font-size:11px;padding:4px 8px;">ещё места</span>';
          } else {
            html += '<span class="slot-status booked" style="font-size:11px;padding:4px 8px;">полная</span>';
          }
        } else {
          html += '<span class="slot-status ' + statusClass + '">' + statusLabel + '</span>';
          if (bookedClick && !cohortSlot) {
            html += scheduleEditorSlotMessageButtonHtml(s, cap);
          }
        }
        if (status === 'available' && occ === 0 && !cohortSlot) {
          html += '<button type="button" class="btn-slot-del" data-slot-id="' + s.id + '" aria-label="Удалить">×</button>';
        } else if (bookedClick && slotPast && !groupHub && !cohortSlot) {
          html += '<button type="button" class="btn-slot-del btn-booking-purge" data-booking-id="' + s.booking_id + '" aria-label="Убрать запись">×</button>';
        }
        html += '</div></div>';
        return html;
      }

      function mergeDayCalendarTimelineHtml(daySlots, dayDuties) {
        var si = 0;
        var di = 0;
        var out = '';
        while (si < daySlots.length || di < dayDuties.length) {
          var slot = daySlots[si];
          var duty = dayDuties[di];
          var takeSlot =
            di >= dayDuties.length ||
            (si < daySlots.length &&
              String(slot.start_time || '').localeCompare(String(duty.start_time || '')) <= 0);
          if (takeSlot) {
            out += renderCalendarDaySlotRowHtml(daySlots[si++]);
          } else {
            out += renderScheduleCenterDutyRowHtml(dayDuties[di++], daySlots);
          }
        }
        return out;
      }

      function renderCalendar() {
        teardownScheduleCalendarScrollSpy();
        syncAddSlotsButtonEligibility();
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
        if (scheduleEditorHasCenterDuties()) {
          (state.centerDuties || []).forEach(function(d) {
            if (!byDay[d.slot_date]) byDay[d.slot_date] = [];
          });
        }
        const days = Object.keys(byDay).sort();
        const content = document.getElementById('calendarContent');
        if (days.length === 0) {
          content.innerHTML = buildCalendarEmptyStateHtml(state.slotFilter, entirePast);
          renderScheduleWeekDayStrip();
          return;
        }
        let html = '';
        days.forEach(function(dateKey) {
          const daySlots = byDay[dateKey]
            .filter(function(s) { return !s.training_group_id; })
            .sort(function(a, b) { return (a.start_time || '').localeCompare(b.start_time || ''); });
          var dayDuties = scheduleCenterOverlayRowsForDate(dateKey)
            .sort(function(a, b) { return (a.start_time || '').localeCompare(b.start_time || ''); });
          if (!daySlots.length && !dayDuties.length) return;
          html += '<div class="day-block cal-day-anchor" id="cal-day-' + dateKey + '"><div class="day-title">' + escapeHtml(formatDateKey(dateKey)) + '</div>';
          html += mergeDayCalendarTimelineHtml(daySlots, dayDuties);
          html += '</div>';
        });
        if (!html) {
          content.innerHTML = buildCalendarEmptyStateHtml(state.slotFilter, entirePast);
          renderScheduleWeekDayStrip();
          return;
        }
        content.innerHTML = html;
        if (window.wireHubSlotMessageButtons) {
          try {
            window.wireHubSlotMessageButtons(content);
          } catch (eWire) { /* noop */ }
        }
        content.querySelectorAll('.btn-slot-del:not(.btn-booking-purge)').forEach(function(btn) {
          btn.onclick = function(e) {
            e.stopPropagation();
            const id = parseInt(btn.dataset.slotId, 10);
            showAppConfirm('Удалить этот слот?', { okText: 'Удалить', cancelText: 'Отмена' }).then(function (ok) {
              if (!ok) return;
              if (!assertScheduleCrmWriteAllowed()) return;
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
        content.querySelectorAll('.btn-booking-purge').forEach(function(btn) {
          btn.onclick = function(e) {
            e.stopPropagation();
            var bid = parseInt(btn.dataset.bookingId, 10);
            if (!bid) return;
            showAppConfirm(
              'Убрать запись из расписания и статистики? Если занятие было по абонементу или сертификату, списание будет отменено.',
              { okText: 'Убрать', cancelText: 'Отмена' }
            ).then(function(ok) {
              if (!ok) return;
              if (!assertScheduleCrmWriteAllowed()) return;
              fetch(apiUrlWithQuery('/trainer/bookings/' + bid + '/schedule-history'), { method: 'DELETE', headers: headers() })
                .then(function(r) {
                  if (r.ok) {
                    showToast('Запись убрана');
                    loadSlots();
                  } else {
                    r.json().then(function(o) {
                      showToast(_detailMessageFromBody(o, 'Не удалось убрать запись'));
                    }).catch(function() { showToast('Не удалось убрать запись'); });
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
          row.onclick = function(e) {
            if (e.target.closest('.btn-booking-purge')) return;
            if (e.target.closest('button.hub-slot-msg')) return;
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
        content.querySelectorAll('.slot-row-center-duty--clickable').forEach(function(row) {
          row.onclick = function() {
            var sid = parseInt(row.getAttribute('data-center-session-id'), 10);
            var dateKey = row.getAttribute('data-center-slot-date');
            if (!sid || !dateKey) return;
            var duty = findCenterDutyBySessionId(sid, dateKey);
            if (duty) openCenterSessionModal(duty);
          };
          row.onkeydown = function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              row.click();
            }
          };
        });
        renderScheduleWeekDayStrip();
        installScheduleCalendarScrollSpy();
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
                proceedBookExistingClient(found.id, autoName);
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
                proceedBookExistingClient(clientId, clientName);
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
        /* Two-step «из списка»: вернуть к выбору услуги/тарифа, не к списку клиентов. */
        if (state.bookExistingServiceStepActive && state.bookSelectedExistingClientId != null) {
          var mbc = document.getElementById('modalBookClient');
          if (mbc) {
            mbc.style.display = 'flex';
            showBookExistingServiceStep();
            mbc.scrollTop = 0;
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
            if (av === 'center_duty') {
              var duty = quickBookCenterDutyConflict(startMinutes, dm, sd);
              var dutyName = (duty && duty.collective_name) || 'центр';
              showToast(
                'Это время пересекается со сменой в «' + dutyName + '». Выберите другое окно или отмените смену в сетке центра.'
              );
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
        var bookOvExisting = document.getElementById('modalBookClient');
        if (bookOvExisting) bookOvExisting.classList.remove('book-flow-overlay--new-client');
        document.getElementById('bookStepChoice').classList.remove('active');
        document.getElementById('bookStepChoice').style.display = 'none';
        document.getElementById('bookStepExisting').style.display = 'block';
        document.getElementById('bookStepExisting').classList.add('active');
        state.bookSelectedExistingClientId = null;
        state.bookSelectedExistingClientName = '';
        showBookExistingClientStep();
        setBookClientSearchSectionVisible(true);
        var sel = document.getElementById('bookServiceSelect');
        if (sel && state.bookServiceId != null) sel.value = String(state.bookServiceId);
        document.getElementById('bookClientList').innerHTML = buildBookClientListSkeletonHtml();
        loadBookClients();
      };
      document.getElementById('bookOptNew').onclick = function() {
        scheduleGoBookNewClientFlow();
      };
      var bookExistingNewChipEl = document.getElementById('bookExistingNewChip');
      if (bookExistingNewChipEl) {
        bookExistingNewChipEl.onclick = function() {
          scheduleGoBookNewClientFlow();
        };
      }
      document.getElementById('bookBackFromExisting').onclick = function() {
        if (state.bookModalClientSearchFirst) {
          document.getElementById('modalBookClient').style.display = 'none';
          clearBookSlotModalState();
          state.bookModalStep = 'choice';
          updateTelegramBack();
          return;
        }
        state.bookSelectedExistingClientId = null;
        state.bookSelectedExistingClientName = '';
        if (state.bookModalClientSearchFirst) {
          showBookExistingClientStep();
          showBookStep('bookStepExisting');
          loadBookClients(document.getElementById('bookClientSearch') ? document.getElementById('bookClientSearch').value.trim() : '');
          return;
        }
        showBookExistingClientStep();
        document.getElementById('bookStepExisting').style.display = 'none';
        document.getElementById('bookStepExisting').classList.remove('active');
        document.getElementById('bookStepChoice').style.display = 'block';
        document.getElementById('bookStepChoice').classList.add('active');
      };
      var bookBackFromCenterEl = document.getElementById('bookBackFromCenter');
      if (bookBackFromCenterEl) {
        bookBackFromCenterEl.onclick = function() {
          state.bookCenterSession = null;
          state.bookCenterClientId = null;
          showBookExistingClientStep();
          showBookStep('bookStepExisting');
        };
      }
      var btnBookCenterConfirmEl = document.getElementById('btnBookCenterConfirm');
      if (btnBookCenterConfirmEl) {
        btnBookCenterConfirmEl.onclick = submitBookCenterStaffBooking;
      }
      document.getElementById('bookBackFromNew').onclick = function() {
        scheduleReturnFromNewClientToQuickSearch();
      };
      (function wireBookExistingServiceSubstep() {
        var backSvc = document.getElementById('bookBackFromServiceExisting');
        var btnNext = document.getElementById('btnBookExistingServiceNext');
        if (backSvc) {
          backSvc.onclick = function() {
            if (state.bookServiceStepFromNewClient) {
              scheduleGoBookNewClientFlow();
              return;
            }
            showBookExistingClientStep();
            var q = document.getElementById('bookClientSearch');
            loadBookClients(q ? q.value.trim() : '');
          };
        }
        if (btnNext) {
          btnNext.onclick = function() {
            var cid = state.bookSelectedExistingClientId;
            if (cid == null) {
              showToast('Выберите клиента');
              return;
            }
            var serviceId = state.bookServiceId != null ? state.bookServiceId : (state.bookServices.length ? state.bookServices[0].id : null);
            if (serviceId == null) {
              showToast('Выберите услугу');
              return;
            }
            if (!state.bookSlotIsGroup) {
              var svc = (state.bookServices || []).filter(function(x) { return Number(x.id) === Number(serviceId); })[0];
              var tiers = (svc && svc.price_tiers) ? svc.price_tiers : [];
              if (tiers.length > 1 && state.bookPriceVariantId == null) {
                showToast('Выберите тариф');
                return;
              }
            }
            var name = state.bookSelectedExistingClientName || 'Клиент';
            openBookConfirmForClient(cid, name);
          };
        }
      })();
      // Tap overlay to dismiss keyboard (skip when blur-only phone masking applies — overlay blur fights iOS paste/callout)
      (function bindModalOverlayDismissKeyboard() {
        var skipBlur =
          typeof window.miniAppIsTouchPrimary === 'function' && window.miniAppIsTouchPrimary();
        document.querySelectorAll('.modal-overlay').forEach(function(overlay) {
          overlay.addEventListener('click', function(e) {
            if (e.target !== overlay) return;
            if (skipBlur) return;
            var el = document.activeElement;
            if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) {
              el.blur();
            }
          });
        });
      })();
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

      (function wireBookNewPhoneMask() {
        if (window.CrmPhoneField) CrmPhoneField.initAll(document.getElementById('modalBookClient') || document);
      })();

      (function wireBookingEditServiceModal() {
        var btnSave = document.getElementById('btnBookingEditServiceSave');
        var btnCancel = document.getElementById('btnBookingEditServiceCancel');
        var overlay = document.getElementById('modalBookingEditService');
        if (btnSave) btnSave.onclick = saveBookingEditService;
        if (btnCancel) btnCancel.onclick = closeBookingEditServiceModal;
        if (overlay) {
          overlay.onclick = function(ev) {
            if (ev.target === overlay) closeBookingEditServiceModal();
          };
        }
      })();

      document.getElementById('bookNewSubmit').onclick = function() {
        var phoneEl = document.getElementById('bookNewPhone');
        var firstEl = document.getElementById('bookNewFirstName');
        var lastEl = document.getElementById('bookNewLastName');
        var first = (firstEl.value || '').trim() || null;
        var last = (lastEl.value || '').trim() || null;
        var phCheck = bookPhoneFromField(phoneEl);
        if (!phCheck.ok) {
          showToast(phCheck.error || 'Укажите номер телефона.');
          phoneEl.focus();
          return;
        }
        var phone = phCheck.e164;
        first = (first || '').trim();
        last = (last || '').trim();
        if (!first) {
          showToast('Укажите имя клиента.');
          firstEl.focus();
          return;
        }
        if (!state.bookSlotId && !state.bookFlowQuick) return;
        var displayName = (first + (last ? ' ' + last : '')).trim();
        var btn = document.getElementById('bookNewSubmit');

        /* Hub parity: client created first, then service/tariff/arena, then confirm booking. */
        if (state.bookServiceStepFromNewClient && state.bookSelectedExistingClientId != null) {
          scheduleTransitionToServiceStepAfterNewClient(
            state.bookSelectedExistingClientId,
            displayName || state.bookSelectedExistingClientName
          );
          return;
        }

        btn.disabled = true;
        fetch(apiUrlWithQuery('/trainer/clients'), {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({ phone: phone, first_name: first, last_name: last || '' }),
        })
          .then(function(r) {
            if (!r.ok) return r.json().then(function(o) { throw new Error(o.detail || 'Ошибка'); });
            return r.json();
          })
          .then(function(data) {
            scheduleTransitionToServiceStepAfterNewClient(data.client_id, displayName);
          })
          .catch(function(e) {
            showToast(e.message || 'Ошибка сети');
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
        renderCenterGridTemplate();
        syncScheduleEditorFormatChrome();
      }

      function openEditTemplateDay(day) {
        if (!assertScheduleCrmWriteAllowed()) return;
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
        var useTplGroup = slotIntentUseGroupUi();
        state.preciseSlots = [];
        state.slotAddMode = 'grid';
        var gridArenaPrefTpl = null;
        var durTpl = document.getElementById('slotDurationSelect');
        if (useTplGroup) {
          state.selectedStarts = new Set(
            existing
              .map(function(t) { return parseStartToMinutes(t.start_time); })
              .filter(function(m) { return allowedTemplateStarts.has(m); })
          );
          if (durTpl) {
            var dms = existing.map(function(t) { return parseInt(t.duration_minutes, 10); }).filter(function(x) { return !isNaN(x); });
            var fallbackDur = state.defaultSlotDurationMinutes || 45;
            var dval = dms.length && dms.every(function(x) { return x === dms[0]; }) ? dms[0] : fallbackDur;
            durTpl.value = String(normalizeDurationToScheduleSelect(Math.min(480, Math.max(15, dval))));
          }
        } else {
          var existingIndiv = existing.filter(function(t) {
            var c = (t.capacity != null) ? parseInt(t.capacity, 10) : 1;
            return !isNaN(c) && c <= 1;
          });
          var gridAlignedRows = existingIndiv.filter(function(t) {
            return allowedTemplateStarts.has(parseStartToMinutes(t.start_time));
          });
          var gridDurs = gridAlignedRows.map(slotDurationFromRow);
          var gridDefaultDur =
            gridDurs.length ? mostFrequentInt(gridDurs) : (state.defaultSlotDurationMinutes || 45);
          gridDefaultDur = Math.min(480, Math.max(15, gridDefaultDur));
          state.selectedStarts = new Set();
          existingIndiv.forEach(function(t) {
            var sm = parseStartToMinutes(t.start_time);
            var dur = slotDurationFromRow(t);
            var onGrid = allowedTemplateStarts.has(sm);
            if (onGrid && dur === gridDefaultDur) {
              state.selectedStarts.add(sm);
              return;
            }
            var psTpl = { startMinutes: sm, durationMinutes: dur };
            var arenaFromTpl =
              t.arena_id != null && !isNaN(parseInt(String(t.arena_id), 10))
                ? parseInt(String(t.arena_id), 10)
                : null;
            if (arenaFromTpl != null) psTpl.arenaId = arenaFromTpl;
            state.preciseSlots.push(psTpl);
          });
          gridArenaPrefTpl = inferGridArenaIdFromSlotRows(
            existingIndiv,
            allowedTemplateStarts,
            gridDefaultDur
          );
          if (durTpl) {
            durTpl.value = String(normalizeDurationToScheduleSelect(gridDefaultDur));
          }
        }
        state.calendarBaselinePreciseKeys = useTplGroup
          ? new Set()
          : new Set((state.preciseSlots || []).map(calendarPreciseSlotStableKey));
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
        document.getElementById('editHint').textContent = useTplGroup
          ? 'Групповые слоты: места, услуга и площадка задаются один раз — для всех отмеченных начал.'
          : scheduleGridFixedDurationMinutes() != null
            ? 'Индивидуально: вкладка «Быстро» по сетке или «Точное время» вне сетки. ' + scheduleGridHintSuffix() + ' «Готово» сохранит шаблон.'
            : 'Индивидуально: «Быстро» или «Точное время» с нужной длительностью. ' + scheduleGridHintSuffix() + ' «Готово» сохранит шаблон.';
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
        var tplSwitcher = document.getElementById('slotAddModeSwitcher');
        if (tplSwitcher) tplSwitcher.style.display = useTplGroup ? 'none' : 'flex';
        setSlotAddMode('grid');
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
            renderPreciseSlotsAdded();
          });
        } else {
          loadTrainerServicesIfNeeded().then(function() {
            state.scheduleGridArenaPickId = gridArenaPrefTpl;
            fillScheduleEditorGridArenaPick(gridArenaPrefTpl);
            syncPreciseArenaWrapsAfterSlotsChanged();
            pruneSelectedStartsForOverlap(getEditDurationMinutes());
            renderHourGrid();
            renderPreciseSlotsAdded();
          });
        }
        updateTelegramBack();
      }

      function openEditCalendarDay(slotDate) {
        if (!assertScheduleCrmWriteAllowed()) return;
        var todayGate = dateToStr(new Date());
        if (slotDate && String(slotDate).slice(0, 10) < todayGate) {
          showToast('Слоты в прошлом не добавляем — только сегодня и будущие даты.');
          showDayPickScreen();
          return;
        }
        state.editMode = 'calendar';
        state.editDay = null;
        state.editDate = slotDate;
        // Group-generated slots belong to the Groups flow and must not affect manual day editing.
        const daySlots = (state.slots || []).filter(function(s) {
          return s.slot_date === slotDate && !s.training_group_id;
        });
        if (!isGroupClassesFeatureEnabled() && !(state.slotEditIntent === 'center' && hasCenterScheduleAdmin())) {
          state.slotEditIntent = 'individual';
        } else if (
          state.slotEditIntent !== 'group' &&
          state.slotEditIntent !== 'individual' &&
          state.slotEditIntent !== 'center'
        ) {
          state.slotEditIntent = detectSlotIntentFromRows(daySlots);
        }
        var gridDefaultDurForCalUi = Math.min(
          480,
          Math.max(15, state.defaultSlotDurationMinutes || 45)
        );
        var useCalCenter = slotIntentUseCenterUi();
        var useCalGroup = slotIntentUseGroupUi();
        var calendarGridArenaPref = null;
        var allowedCalendarStarts = new Set(
          allowedStartMinutesFromScheduleGridPreset(state.scheduleGridPreset || defaultScheduleGridPreset())
        );
        state.selectedStarts = new Set();
        state.lockedStarts = new Set();
        if (useCalCenter) {
          state.preciseSlots = [];
          resetCenterEditCoachIds();
          var coachHostReset = document.getElementById('centerEditCoachChips');
          if (coachHostReset) coachHostReset.innerHTML = '';
          var centerDay = centerSessionsForEditDate();
          centerDay.forEach(function(s) {
            var m = parseStartToMinutes(s.start_time);
            if (!allowedCalendarStarts.has(m)) return;
            state.selectedStarts.add(m);
            if ((s.booked_count || 0) > 0) state.lockedStarts.add(m);
          });
          state.calendarBaselineStarts = new Set(state.selectedStarts);
          state.calendarBaselinePreciseKeys = new Set();
          if (centerDay.length) {
            var centerDurs = centerDay.map(function(s) {
              return parseStartToMinutes(s.end_time) - parseStartToMinutes(s.start_time);
            });
            if (centerDurs.length && centerDurs.every(function(x) { return x === centerDurs[0]; })) {
              gridDefaultDurForCalUi = centerDurs[0];
            }
          }
        } else if (useCalGroup) {
          state.preciseSlots = [];
          daySlots.forEach(function(s) {
            var m = parseStartToMinutes(s.start_time);
            if (!allowedCalendarStarts.has(m)) return;
            state.selectedStarts.add(m);
            var occ = (s.active_bookings != null) ? parseInt(s.active_bookings, 10) : 0;
            if ((s.status || '') === 'booked' || occ > 0) state.lockedStarts.add(m);
          });
          state.calendarBaselineStarts = new Set(state.selectedStarts);
          state.calendarBaselinePreciseKeys = new Set();
        } else {
          /** Match template UX: splits grid-aligned vs off-grid («точное время») so сохранить день не удаляет уже созданные интервалы. */
          var individualRows = daySlots.filter(function(s) {
            if (String(s.status || '').toLowerCase() === 'cancelled') return false;
            var c = (s.capacity != null) ? parseInt(s.capacity, 10) : 1;
            return !isNaN(c) && c <= 1;
          });
          var gridDursHydr = individualRows
            .filter(function(t) {
              return allowedCalendarStarts.has(parseStartToMinutes(t.start_time));
            })
            .map(slotDurationFromRow);
          var gridDefaultDurHydr =
            gridDursHydr.length ? mostFrequentInt(gridDursHydr) : state.defaultSlotDurationMinutes || 45;
          gridDefaultDurHydr = Math.min(480, Math.max(15, gridDefaultDurHydr));
          gridDefaultDurForCalUi = gridDefaultDurHydr;
          state.preciseSlots = [];
          individualRows.forEach(function(s) {
            var m = parseStartToMinutes(s.start_time);
            var dur = slotDurationFromRow(s);
            var occ = (s.active_bookings != null) ? parseInt(s.active_bookings, 10) : 0;
            var booked = String(s.status || '').toLowerCase() === 'booked' || occ > 0;
            var onGrid = allowedCalendarStarts.has(m);
            if (onGrid && dur === gridDefaultDurHydr) {
              state.selectedStarts.add(m);
              if (booked) state.lockedStarts.add(m);
            } else {
              var psHydr = { startMinutes: m, durationMinutes: dur };
              if (booked || occ > 0) psHydr.locked = true;
              var aidRaw = s.arena_id != null ? parseInt(String(s.arena_id), 10) : NaN;
              if (!isNaN(aidRaw)) psHydr.arenaId = aidRaw;
              state.preciseSlots.push(psHydr);
            }
          });
          state.calendarBaselineStarts = new Set(state.selectedStarts);
          state.calendarBaselinePreciseKeys = new Set(
            (state.preciseSlots || []).map(function(ps) {
              return calendarPreciseSlotStableKey(ps);
            })
          );
          calendarGridArenaPref = inferGridArenaIdFromSlotRows(
            individualRows,
            allowedCalendarStarts,
            gridDefaultDurHydr
          );
        }
        var durElCal = document.getElementById('slotDurationSelect');
        if (durElCal) {
          if (useCalGroup && daySlots.length) {
            var durs = daySlots.map(slotDurationFromRow);
            var dcal = durs.length && durs.every(function(x) { return x === durs[0]; }) ? durs[0] : 45;
            durElCal.value = String(Math.min(480, Math.max(15, dcal)));
          } else if (useCalCenter || daySlots.length) {
            durElCal.value = String(normalizeDurationToScheduleSelect(gridDefaultDurForCalUi));
          } else {
            durElCal.value = String(normalizeDurationToScheduleSelect(state.defaultSlotDurationMinutes || 45));
          }
        }
        syncDurationUIFromScheduleGrid();
        document.querySelector('.tabs').style.display = 'none';
        document.getElementById('tabCalendar').style.display = 'none';
        document.getElementById('tabTemplate').style.display = 'none';
        document.getElementById('editTitle').textContent = useCalCenter
          ? 'Смена · ' + formatDateKey(slotDate)
          : 'Слоты на ' + formatDateKey(slotDate);
        document.getElementById('editHint').textContent = useCalCenter
          ? 'Смена центра: нажмите на время — добавить или убрать свободное окно. С записью снять нельзя. «Готово» — когда есть изменения.'
          : useCalGroup
            ? 'Групповые слоты: параметры для новых начал. Свободное окно снимите повторным нажатием на время; со записью — нельзя. «Готово» — когда есть изменения.'
            : 'Индивидуальные слоты: нажмите на время — добавить или убрать свободное окно. Запись на слот снять нельзя. «Готово» — когда есть изменения.';
        var capWrap = document.getElementById('slotCapacityWrap');
        var capInput = document.getElementById('slotCapacityInput');
        if (capInput) capInput.setAttribute('min', useCalGroup ? '2' : '1');
        if (capWrap) {
          if (useCalCenter) {
            capWrap.style.display = 'block';
            var centerCaps = centerSessionsForEditDate().map(function(s) {
              return s.capacity != null ? parseInt(s.capacity, 10) : 1;
            });
            var centerCapVal = 1;
            if (centerCaps.length && centerCaps.every(function(c) { return c === centerCaps[0]; })) {
              centerCapVal = centerCaps[0];
            }
            if (centerCapVal < 1) centerCapVal = 1;
            if (capInput) capInput.value = String(Math.min(500, Math.max(1, centerCapVal)));
          } else if (useCalGroup) {
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
        /** Default to chip grid UX; queued precise rows were hydrated above when editing calendar individual slots. */
        state.slotAddMode = 'grid';
        // Show mode switcher only for individual calendar slots
        var switcher = document.getElementById('slotAddModeSwitcher');
        if (switcher) switcher.style.display = useCalGroup || useCalCenter ? 'none' : 'flex';
        // Must sync DOM (duration + grid vs precise) — after «Точное время» a raw display:none on
        // preciseSlotForm leaves stale hidden grid + wrong active tab until user re-taps a mode.
        setSlotAddMode('grid');
        syncCenterEditChrome();
        document.getElementById('screenEdit').style.display = 'block';
        window.scrollTo(0, 0);
        pruneSelectedStartsForOverlap(getEditDurationMinutes());
        renderHourGrid();
        renderPreciseSlotsAdded();
        updateTelegramBack();
        syncScheduleWeekDayStripVisibility();
        loadTrainerServicesIfNeeded().then(function() {
          state.scheduleGridArenaPickId = calendarGridArenaPref;
          fillScheduleEditorGridArenaPick(calendarGridArenaPref);
          syncPreciseArenaWrapsAfterSlotsChanged();
        });
      }

      function renderHourGrid() {
        const grid = document.getElementById('hourGrid');
        if (!grid) return;
        const durationMinutes = getEditDurationMinutes();
        const preset = state.scheduleGridPreset || defaultScheduleGridPreset();
        const calEditDate = state.editMode === 'calendar' ? state.editDate : null;
        var useCenterGrid = slotIntentUseCenterUi();
        var h0 = Math.max(0, Math.min(23, parseInt(preset.hour_start, 10)));
        if (isNaN(h0)) h0 = 6;
        var h1 = Math.max(0, Math.min(23, parseInt(preset.hour_end, 10)));
        if (isNaN(h1)) h1 = 23;
        if (h1 < h0) {
          var hx = h0;
          h0 = h1;
          h1 = hx;
        }
        const list = allowedStartMinutesFromScheduleGridPreset(preset);
        let html = '';
        for (let h = h0; h <= h1; h++) {
          const chips = list.filter(function(m) {
            if (Math.floor(m / 60) !== h) return false;
            if (calEditDate && isCalendarSlotStartInPast(calEditDate, m)) return false;
            return true;
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
            const candDur = durationMinutes;
            var intervalBlockKind =
              selected || locked || pinned ? null : classifyIntervalConsumptionBlock(m, candDur);
            const blockedByOverlap = intervalBlockKind != null;
            var personalOverlap =
              useCenterGrid &&
              scheduleEditorPersonalOverlapEnabled() &&
              ownerPersonalSlotIntervalsForCenterEdit().length
                ? centerPersonalOverlapAtMinute(m, candDur)
                : null;
            var personalGhost = !!personalOverlap;
            var personalSelfOnlyBlock =
              personalGhost && centerEditSelfOnlyOnShift() && !selected && !locked;
            const labelFull = formatMinuteClock(m);
            const labelShort = ':' + String(m % 60).padStart(2, '0');
            /** Short aria only (no hover titles): grid reads as «tap where allowed». */
            var ariaBits = [labelFull];
            if (personalGhost) {
              ariaBits.push(
                'пересекается с личным ' +
                  (personalOverlap.start_time || '') +
                  '–' +
                  (personalOverlap.end_time || '')
              );
            }
            if (blockedByOverlap) {
              ariaBits.push('занято, начало недоступно');
            } else if (locked) {
              ariaBits.push('нельзя убрать');
            } else if (pinned) {
              ariaBits.push('открытый слот, нажмите чтобы убрать');
            } else if (personalSelfOnlyBlock) {
              ariaBits.push('на смене только вы — личный слот');
            }
            var btnAttrs = ' aria-label="' + escapeHtml(ariaBits.join(' · ')) + '"';
            if (blockedByOverlap || locked || personalSelfOnlyBlock) {
              btnAttrs += ' disabled';
            }
            html +=
              '<button type="button" class="hour-chip' +
              (useCenterGrid ? ' hour-chip--center' : '') +
              (personalGhost ? ' hour-chip--personal-ghost' : '') +
              (personalGhost && centerEditSelfOnlyOnShift() ? ' hour-chip--personal-conflict' : '') +
              (selected ? ' selected' : '') +
              (locked ? ' locked' : '') +
              (pinned ? ' pinned' : '') +
              (blockedByOverlap ? ' duration-blocked duration-blocked--' + intervalBlockKind : '') +
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
        if (!html && calEditDate) {
          grid.innerHTML =
            '<div class="empty schedule-hour-grid-empty" role="status">Для добавления времени здесь уже нет ни одной ячейки&nbsp;— день мог уйти в прошлое по сетке площадки.</div>';
          grid.setAttribute('aria-describedby', 'scheduleTimeGridHint');
          updateEditDoneButton();
          return;
        }
        grid.innerHTML = html;
        grid.setAttribute('aria-describedby', 'scheduleTimeGridHint');
        grid.querySelectorAll('.hour-chip:not(.locked):not(.duration-blocked):not(:disabled)').forEach(function(btn) {
          btn.onclick = function() {
            const m = parseInt(btn.dataset.minute, 10);
            if (slotIntentUseCenterUi() && !state.selectedStarts.has(m)) {
              var dur = getEditDurationMinutes();
              if (
                scheduleEditorPersonalOverlapEnabled() &&
                centerPersonalOverlapAtMinute(m, dur) &&
                centerEditSelfOnlyOnShift()
              ) {
                showToast('На смене только вы — это время занято личным слотом');
                return;
              }
            }
            if (state.selectedStarts.has(m)) state.selectedStarts.delete(m);
            else state.selectedStarts.add(m);
            renderHourGrid();
          };
        });
        if (!(state.editMode === 'template' && slotIntentUseGroupUi())) {
          var tpanHide = document.getElementById('templateCapacityPanel');
          if (tpanHide) tpanHide.style.display = 'none';
        }
        syncCenterEditOverlapWarn();
        updateEditDoneButton();
      }

      initPreciseFormEvents();

      (function wireSlotDurationOverlap() {
        var sel = document.getElementById('slotDurationSelect');
        if (!sel) return;
        sel.addEventListener('change', function() {
          var d = getEditDurationMinutes();
          pruneSelectedStartsForOverlap(d);
          renderHourGrid();
          renderPreciseLayout();
        });
      })();

      document.getElementById('editDone').onclick = function() {
        if (!assertScheduleCrmWriteAllowed()) return;
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
            var precTpl = state.preciseSlots || [];
            var arsTpl = state.trainerScheduleArenas || [];
            var multiArenaTpl = arsTpl.length > 1;
            var tplPrecArenaPick = null;
            var tplGridArenaPick = readGridArenaPickForSave();
            var tplNeedArena =
              multiArenaTpl && precTpl.some(function(ps) { return ps.arenaId == null; });
            if (tplNeedArena) {
              var paTplEl = document.getElementById('templatePreciseArenaSelect');
              if (!paTplEl) {
                alert('Выберите площадку для слотов «Точное время» в шаблоне.');
                return;
              }
              tplPrecArenaPick = readPreciseArenaPickForSave();
            }
            slotsPayload = [];
            startsSorted.forEach(function(m0) {
              var rowGrid = {
                hour: Math.floor(m0 / 60),
                minute: m0 % 60,
                capacity: 1,
                duration_minutes: durationMinutes,
              };
              if (multiArenaTpl && tplGridArenaPick != null) rowGrid.arena_id = tplGridArenaPick;
              slotsPayload.push(rowGrid);
            });
            precTpl.forEach(function(ps) {
              var rowTpl = {
                hour: Math.floor(ps.startMinutes / 60),
                minute: ps.startMinutes % 60,
                capacity: 1,
                duration_minutes: ps.durationMinutes,
              };
              if (multiArenaTpl) {
                var aeTpl = ps.arenaId != null ? ps.arenaId : tplPrecArenaPick;
                if (aeTpl != null) rowTpl.arena_id = aeTpl;
              }
              slotsPayload.push(rowTpl);
            });
            slotsPayload.sort(function(a, b) {
              return (a.hour * 60 + a.minute) - (b.hour * 60 + b.minute);
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
          if (slotIntentUseCenterUi()) {
            saveCenterCalendarDay(startsSorted, durationMinutes);
            return;
          }
          var capRaw = parseInt(document.getElementById('slotCapacityInput').value, 10);
          var capacity = (isNaN(capRaw) || capRaw < 1) ? 1 : Math.min(500, capRaw);
          if (slotIntentUseGroupUi()) {
            if (capacity < 2) capacity = 2;
          } else {
            capacity = 1;
          }
          var precSlots = state.preciseSlots || [];
          var postBody;
          var gridArenaPickCal = readGridArenaPickForSave();
          if (precSlots.length > 0) {
            // Mixed mode: build slot_entries combining grid starts + precise slots
            var slotEntries = [];
            var arsPrec = state.trainerScheduleArenas || [];
            var multiArenaPrec = arsPrec.length > 1;
            var precArenaPayload = null;
            var needArenaPick = multiArenaPrec && precSlots.some(function(ps) { return ps.arenaId == null; });
            if (needArenaPick) {
              var pasPickEl = document.getElementById('calendarPreciseArenaSelect');
              if (!pasPickEl) {
                alert('Выберите площадку для слотов «Точное время».');
                return;
              }
              precArenaPayload = readPreciseArenaPickForSave();
            }
            startsSorted.forEach(function(m0) {
              var entGrid = { start_time: formatMinuteClock(m0), duration_minutes: durationMinutes };
              if (multiArenaPrec && gridArenaPickCal != null) entGrid.arena_id = gridArenaPickCal;
              slotEntries.push(entGrid);
            });
            precSlots.forEach(function(ps) {
              var entPrec = {
                start_time: formatMinuteClock(ps.startMinutes),
                duration_minutes: ps.durationMinutes,
              };
              if (multiArenaPrec) {
                var aidEnt = ps.arenaId != null ? ps.arenaId : precArenaPayload;
                if (aidEnt != null) entPrec.arena_id = aidEnt;
              }
              slotEntries.push(entPrec);
            });
            postBody = { slot_date: state.editDate, slot_entries: slotEntries, capacity: capacity };
            if (multiArenaPrec && gridArenaPickCal != null && !slotEntries.some(function(e) { return e.arena_id != null; })) {
              postBody.arena_id = gridArenaPickCal;
            }
          } else {
            postBody = {
              slot_date: state.editDate,
              start_times: startsSorted.map(function(m0) { return formatMinuteClock(m0); }),
              duration_minutes: durationMinutes,
              capacity: capacity,
            };
            if (gridArenaPickCal != null) postBody.arena_id = gridArenaPickCal;
          }
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
              return r.json().then(function(data) {
                if (!r.ok) {
                  var d = data.detail || 'Ошибка';
                  showToast(typeof d === 'string' ? d : 'Ошибка сохранения');
                  return;
                }
                // Net additions vs editor-open snapshot (full POST replaces the day — toast should reflect real delta).
                var nNew = 0;
                if (state.calendarBaselineStarts) {
                  startsSorted.forEach(function(m) {
                    if (!state.calendarBaselineStarts.has(m)) nNew++;
                  });
                } else {
                  nNew += startsSorted.length;
                }
                var precBaseSet = state.calendarBaselinePreciseKeys;
                if (precBaseSet instanceof Set) {
                  (precSlots || []).forEach(function(ps) {
                    if (!precBaseSet.has(calendarPreciseSlotStableKey(ps))) nNew++;
                  });
                } else {
                  nNew += (precSlots || []).length;
                }
                if (nNew > 0) {
                  var tidMark =
                    data && data.trainer_id != null && !isNaN(parseInt(String(data.trainer_id), 10))
                      ? parseInt(String(data.trainer_id), 10)
                      : state.trainerId;
                  markScheduleEditorHubFillSlotsRhythmBoost(tidMark);
                }
                var msg =
                  nNew === 0
                    ? 'Расписание на день обновлено'
                    : nNew === 1
                      ? 'Добавлен новый слот'
                      : 'Добавлено новых слотов: ' + nNew;
                showToast(msg);
                document.getElementById('screenEdit').style.display = 'none';
                state.editMode = null;
                state.editDate = null;
                state.editDay = null;
                state.calendarBaselineStarts = null;
                state.calendarBaselinePreciseKeys = null;
                state.selectedStarts = new Set();
                state.lockedStarts = new Set();
                state.preciseSlots = [];
                state.slotAddMode = 'grid';
                /* Counts use state.slots — refresh before redrawing day-pick (was: showDayPick then loadSlots → stale numbers). */
                loadSlots({
                  onComplete: function() {
                    showDayPickScreen();
                  },
                  onLoadError: function() {
                    showDayPickScreen();
                  },
                });
              });
            })
            .catch(function() { showToast('Ошибка сети'); });
        }
      };

      document.getElementById('editCancel').onclick = function() {
        if (state.editMode === 'calendar') {
          if (slotIntentUseCenterUi() && (state.centerEditReturn === 'template' || state.centerEditReturn === 'calendar')) {
            finishCenterCalendarEdit();
            return;
          }
          returnToCalendarDayPickFromEdit({ reloadSlots: false });
          return;
        }
        showMain();
      };

      document.getElementById('btnApplyTemplate').onclick = function() {
        if (!assertScheduleCrmWriteAllowed()) return;
        openTemplateApplySheet();
      };

      var btnTemplateApplyCancel = document.getElementById('btnTemplateApplyCancel');
      if (btnTemplateApplyCancel) {
        btnTemplateApplyCancel.onclick = function() {
          closeTemplateApplySheet();
        };
      }
      var modalTemplateApply = document.getElementById('modalTemplateApply');
      if (modalTemplateApply) {
        modalTemplateApply.addEventListener('click', function(ev) {
          if (ev.target === modalTemplateApply) closeTemplateApplySheet();
        });
      }

      (function wireCenterGridTemplateActions() {
        function shiftCenterGridTemplateWeek(delta) {
          if (!state.weekStart) state.weekStart = getMonday(new Date());
          if (state.centerGridWeekLoadInFlight) return;
          var next = new Date(state.weekStart);
          next.setDate(next.getDate() + delta * 7);
          state.weekStart = getMonday(next);
          loadCenterGridWeekData({ syncCalendarWeekLabel: true });
        }
        var prevBtn = document.getElementById('centerGridWeekPrev');
        var nextBtn = document.getElementById('centerGridWeekNext');
        if (prevBtn) prevBtn.onclick = function() { shiftCenterGridTemplateWeek(-1); };
        if (nextBtn) nextBtn.onclick = function() { shiftCenterGridTemplateWeek(1); };
        var copyPrev = document.getElementById('btnCenterGridCopyPrev');
        if (copyPrev) {
          copyPrev.onclick = function() {
            if (!state.weekStart) return;
            var prev = new Date(state.weekStart);
            prev.setDate(prev.getDate() - 7);
            var source = dateToStr(prev);
            runCenterGridDuplicate(
              source,
              1,
              'Скопировать окна с прошлой недели (' +
                formatWeekLabel(prev) +
                ') на текущую (' +
                formatWeekLabel(state.weekStart) +
                ')?'
            );
          };
        }
        var copyNext = document.getElementById('btnCenterGridCopyNext');
        if (copyNext) {
          copyNext.onclick = function() {
            if (!state.weekStart) return;
            var nxt = new Date(state.weekStart);
            nxt.setDate(nxt.getDate() + 7);
            runCenterGridDuplicate(
              dateToStr(state.weekStart),
              1,
              'Скопировать все окна с ' +
                formatWeekLabel(state.weekStart) +
                ' на следующую (' +
                formatWeekLabel(nxt) +
                ')?'
            );
          };
        }
        var copyAhead = document.getElementById('btnCenterGridCopyAhead');
        if (copyAhead) {
          copyAhead.onclick = function() {
            if (!state.weekStart) return;
            var aheadEl = document.getElementById('centerGridWeeksAhead');
            var weeks = aheadEl ? parseInt(aheadEl.value, 10) || 2 : 2;
            runCenterGridDuplicate(
              dateToStr(state.weekStart),
              weeks,
              'Скопировать окна с ' +
                formatWeekLabel(state.weekStart) +
                ' на ' +
                weeks +
                ' нед. вперёд? Уже существующие окна пропускаются.'
            );
          };
        }
      })();

      document.getElementById('modalConfirmNo').onclick = function() {
        document.getElementById('modalConfirm').style.display = 'none';
        state.applyWeekStarts = null;
        state.applyWeekStart = null;
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

      var centerSessionCloseBtn = document.getElementById('centerSessionCloseBtn');
      if (centerSessionCloseBtn) centerSessionCloseBtn.onclick = closeCenterSessionModal;
      var modalCenterSession = document.getElementById('modalCenterSession');
      if (modalCenterSession) {
        modalCenterSession.addEventListener('click', function(ev) {
          if (ev.target === modalCenterSession) closeCenterSessionModal();
        });
      }

      document.getElementById('modalConfirmYes').onclick = function() {
        var weeks = state.applyWeekStarts && state.applyWeekStarts.length
          ? state.applyWeekStarts.slice()
          : (state.applyWeekStart ? [state.applyWeekStart] : []);
        if (!weeks.length) return;
        if (!assertScheduleCrmWriteAllowed()) return;
        document.getElementById('modalConfirm').style.display = 'none';
        updateTelegramBack();
        applyTemplateToWeeks(weeks);
      };

      document.getElementById('btnAddSlots').onclick = function() {
        if (!assertScheduleCrmWriteAllowed()) return;
        if (state.weekStart && isEntireWeekInPast(state.weekStart)) {
          showToast('На прошедшей неделе слоты не добавляем — перелистните календарь.');
          return;
        }
        if (!state.weekStart) return;
        startAddSlotsFlow();
      };

      document.getElementById('btnSlotIntentIndividual').onclick = function() {
        applySlotIntentChoice('individual');
      };
      document.getElementById('btnSlotIntentGroup').onclick = function() {
        applySlotIntentChoice('group');
      };
      var btnSlotIntentCenter = document.getElementById('btnSlotIntentCenter');
      if (btnSlotIntentCenter) {
        btnSlotIntentCenter.onclick = function() {
          applySlotIntentChoice('center');
        };
      }
      document.getElementById('btnSlotIntentCancel').onclick = function() {
        cancelSlotIntentModal();
      };

      /** deltaWeeks: -1 prev, +1 next — shared by week buttons and horizontal swipe on mobile/Telegram WebView. */
      function shiftTrainerScheduleWeek(deltaWeeks, loadOpts) {
        if (state.scheduleLoadInFlight) return;
        loadOpts = loadOpts || {};
        state.showPastThisWeek = false;
        state.scheduleStripSelectedDate = null;
        if (!state.weekStart) state.weekStart = getMonday(new Date());
        state.weekStart.setDate(state.weekStart.getDate() + 7 * deltaWeeks);
        syncAddSlotsButtonEligibility();
        loadSlots(loadOpts);
      }

      document.getElementById('weekPrev').onclick = function() {
        shiftTrainerScheduleWeek(-1);
      };
      document.getElementById('weekNext').onclick = function() {
        shiftTrainerScheduleWeek(1);
      };

      function rescheduleDayPickAfterWeekChangeIfVisible() {
        var dp = document.getElementById('screenDayPick');
        if (dp && dp.style.display === 'block') {
          showDayPickScreen();
        }
      }

      document.getElementById('dayPickWeekPrev').onclick = function() {
        shiftTrainerScheduleWeek(-1, { onComplete: rescheduleDayPickAfterWeekChangeIfVisible });
      };
      document.getElementById('dayPickWeekNext').onclick = function() {
        shiftTrainerScheduleWeek(1, { onComplete: rescheduleDayPickAfterWeekChangeIfVisible });
      };

      (function wireScheduleWeekSwipeGestures() {
        var MIN_DX = 52;
        var HORIZ_RATIO = 1.15;
        /** Before this slop we do not commit horizontal vs vertical (avoids fighting scroll). */
        var LOCK_SLOP_PX = 14;
        /** If still ambiguous after this travel, assume vertical scroll (safe default). */
        var AMBIGUOUS_FALLBACK_PX = 26;

        /** Day-pick rows are <button>; must still allow swipe to start there (otherwise only margins/title swipe). */
        function targetStartsOnExcludedControl(tgt, swipeRootEl) {
          if (!tgt || !tgt.closest) return true;
          if (tgt.closest('input, textarea, select, label, a[href]')) return true;
          /* Bottom strip: day buttons = tap-to-scroll; week swipe via ‹ › and calendar body — not day pills. */
          if (swipeRootEl && swipeRootEl.id === 'scheduleWeekDayStrip') {
            return !!tgt.closest('[data-strip-date]');
          }
          if (swipeRootEl && swipeRootEl.id === 'screenDayPick') {
            return !!tgt.closest('#dayPickWeekPrev, #dayPickWeekNext');
          }
          return !!tgt.closest('button');
        }

        function resetSwipeChrome(rootEl) {
          rootEl.classList.remove('schedule-calendar-swipe--horizontal');
        }

        /**
         * Once the gesture locks as horizontal, non-passive touchmove + preventDefault stops
         * WebView vertical scroll jitter (Telegram tab / elastic scroll) during week swipe.
         * Swipe left (dx < 0) → next week; swipe right → previous.
         */
        function attach(rootEl, getLoadOpts) {
          if (!rootEl || !rootEl.addEventListener) return;
          rootEl.classList.add('schedule-calendar-swipe-root');
          var track = null;

          function findTouch(ev, touchId) {
            var touches = ev.touches;
            var j;
            if (!touches || !touchId) return null;
            for (j = 0; j < touches.length; j++) {
              if (touches[j].identifier === touchId) return touches[j];
            }
            return null;
          }

          rootEl.addEventListener('touchstart', function(ev) {
            track = null;
            if (state.scheduleLoadInFlight) return;
            if (ev.touches.length !== 1) return;
            if (targetStartsOnExcludedControl(ev.target, rootEl)) return;
            var t = ev.touches[0];
            track = {
              x: t.clientX,
              y: t.clientY,
              id: t.identifier,
              /** null = undecided, 'v' = user is scrolling vertically, 'h' = horizontal week swipe */
              mode: null,
            };
          }, { passive: true });

          rootEl.addEventListener('touchmove', function(ev) {
            if (!track || state.scheduleLoadInFlight) return;
            var tMove = findTouch(ev, track.id);
            if (!tMove) return;

            var dx = tMove.clientX - track.x;
            var dy = tMove.clientY - track.y;
            var adx = Math.abs(dx);
            var ady = Math.abs(dy);

            if (track.mode === null) {
              if (adx < LOCK_SLOP_PX && ady < LOCK_SLOP_PX) return;

              var wantH = adx >= LOCK_SLOP_PX && adx > ady * HORIZ_RATIO;
              var wantV = ady >= LOCK_SLOP_PX && ady > adx * HORIZ_RATIO;

              if (wantH && !wantV) {
                track.mode = 'h';
                rootEl.classList.add('schedule-calendar-swipe--horizontal');
              } else if (wantV && !wantH) {
                track.mode = 'v';
                return;
              } else if (Math.max(adx, ady) >= AMBIGUOUS_FALLBACK_PX) {
                if (rootEl && (rootEl.id === 'screenDayPick' || rootEl.id === 'scheduleWeekDayStrip') && adx >= ady) {
                  track.mode = 'h';
                  rootEl.classList.add('schedule-calendar-swipe--horizontal');
                } else {
                  track.mode = 'v';
                  return;
                }
              } else {
                return;
              }
            }

            if (track.mode === 'h') {
              try {
                ev.preventDefault();
              } catch (ePe) { /* ignore */ }
            }
          }, { passive: false });

          rootEl.addEventListener('touchcancel', function() {
            if (track) resetSwipeChrome(rootEl);
            track = null;
          }, { passive: true });

          rootEl.addEventListener('touchend', function(ev) {
            if (!track || state.scheduleLoadInFlight) {
              resetSwipeChrome(rootEl);
              track = null;
              return;
            }
            var tEnd = null;
            var i;
            for (i = 0; i < ev.changedTouches.length; i++) {
              if (ev.changedTouches[i].identifier === track.id) {
                tEnd = ev.changedTouches[i];
                break;
              }
            }
            if (!tEnd) {
              resetSwipeChrome(rootEl);
              track = null;
              return;
            }

            var wasVerticalIntent = track.mode === 'v';
            var dxEnd = tEnd.clientX - track.x;
            var dyEnd = tEnd.clientY - track.y;
            resetSwipeChrome(rootEl);
            track = null;

            if (wasVerticalIntent) return;

            var adx = Math.abs(dxEnd);
            var ady = Math.abs(dyEnd);
            if (adx < MIN_DX || adx < ady * HORIZ_RATIO) return;

            var deltaWeeks = dxEnd < 0 ? 1 : -1;
            var tgApp = window.Telegram && window.Telegram.WebApp;
            if (tgApp && tgApp.HapticFeedback && typeof tgApp.HapticFeedback.selectionChanged === 'function') {
              try {
                tgApp.HapticFeedback.selectionChanged();
              } catch (eH) { /* ignore */ }
            }
            shiftTrainerScheduleWeek(deltaWeeks, typeof getLoadOpts === 'function' ? getLoadOpts() : {});
            if (rootEl && rootEl.id === 'screenDayPick') {
              state.scheduleDayPickSwipeSuppressUntil = Date.now() + 420;
            }
            if (rootEl && rootEl.id === 'scheduleWeekDayStrip') {
              state.scheduleStripSwipeSuppressUntil = Date.now() + 420;
            }
          }, { passive: true });
        }

        attach(document.getElementById('tabCalendar'), function() {
          return {};
        });
        attach(document.getElementById('scheduleWeekDayStrip'), function() {
          return {};
        });
        attach(document.getElementById('screenDayPick'), function() {
          return { onComplete: rescheduleDayPickAfterWeekChangeIfVisible };
        });
      })();

      (function wireScheduleStickyTopChrome() {
        var sentinel = document.getElementById('seScheduleStickySentinel');
        var chrome = document.getElementById('seScheduleTopChrome');
        if (!sentinel || !chrome || !('IntersectionObserver' in window)) return;
        var io = new IntersectionObserver(
          function (entries) {
            var entry = entries[0];
            if (!entry) return;
            chrome.classList.toggle('is-pinned', entry.intersectionRatio < 1);
          },
          { threshold: [1] }
        );
        io.observe(sentinel);
      })();

      (function wireScheduleWeekDayStripNav() {
        var root = document.getElementById('scheduleWeekDayStrip');
        if (!root) return;
        root.addEventListener('click', function(ev) {
          var sup = Number(state.scheduleStripSwipeSuppressUntil) || 0;
          if (sup && Date.now() < sup) {
            if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
            if (ev && typeof ev.stopPropagation === 'function') ev.stopPropagation();
            return;
          }
          var wkNav = ev.target && ev.target.closest && ev.target.closest('[data-strip-week-delta]');
          if (wkNav) {
            var d = parseInt(wkNav.getAttribute('data-strip-week-delta'), 10);
            if (!isNaN(d) && d !== 0) shiftTrainerScheduleWeek(d);
            return;
          }
          var btn = ev.target && ev.target.closest && ev.target.closest('[data-strip-date]');
          if (!btn) return;
          var ds = btn.getAttribute('data-strip-date');
          if (ds) onScheduleStripPickDay(ds);
        });
        root.addEventListener('keydown', function(ev) {
          if (ev.key !== 'Enter' && ev.key !== ' ') return;
          var wkNav = ev.target && ev.target.closest && ev.target.closest('[data-strip-week-delta]');
          if (!wkNav) return;
          ev.preventDefault();
          var d2 = parseInt(wkNav.getAttribute('data-strip-week-delta'), 10);
          if (!isNaN(d2) && d2 !== 0) shiftTrainerScheduleWeek(d2);
        });
      })();

      state.weekStart = getMonday(new Date());
      (function primeScheduleCalendarShell() {
        var cc = document.getElementById('calendarContent');
        if (cc && !String(cc.innerHTML || '').trim()) {
          cc.innerHTML = buildCalendarSkeletonHtml();
        }
        renderScheduleWeekDayStrip();
      })();
      initScheduleEditorPendingInbox();

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
        var fromBookingRaw = p.get('from_booking_id');
        var fromBookingIdForPresets = fromBookingRaw ? parseInt(fromBookingRaw, 10) : null;
        if (fromBookingIdForPresets != null && (isNaN(fromBookingIdForPresets) || fromBookingIdForPresets <= 0)) {
          fromBookingIdForPresets = null;
        }
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
            state.pendingScheduleStripAnchorDate = anchorDate;
          }
        }
        if (bgsRaw) {
          var sidBg = parseInt(bgsRaw, 10);
          if (sidBg) state.pendingBookGroupSlotId = sidBg;
        }
        if (clientIdFromUrl || ob) {
          try { history.replaceState({}, '', window.location.pathname); } catch (e) {}
        } else if (flowBook || bgsRaw || anchorDate) {
          try { history.replaceState({}, '', window.location.pathname); } catch (e) {}
        }
        if (flowBook && !ob) {
          state.pendingBookFlowFromHub = true;
        }
        if (clientIdFromUrl) {
          state.deepLinkClientId = clientIdFromUrl;
          if (fromBookingIdForPresets != null) {
            state.presetBookingDefaultsId = fromBookingIdForPresets;
          }
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
            runAfterScheduleCrmGate(function() {
              withTrainerMiniAppAccessThen(function() {
                openBookingDetail(bid);
                prefetchSlotsInBackground();
              });
            });
            return;
          }
        }
        function startScheduleLoads() {
          /* Subscription/status must not block first paint — tab switch already called loadSlots() without this gate. */
          runAfterScheduleCrmGate(function() {
            syncAddSlotsButtonEligibility();
          });
          if (state.pendingOpenTemplateTab) {
            state.pendingOpenTemplateTab = false;
            setActiveTab('template');
            return;
          }
          loadSlots();
        }
        withTrainerMiniAppAccessThen(startScheduleLoads);
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
