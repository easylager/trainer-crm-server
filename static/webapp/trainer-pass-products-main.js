    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        tg.ready();
        tg.expand();
        if (typeof window.__applyTrainerPassProductsTheme === 'function') {
          window.__applyTrainerPassProductsTheme();
        }
        try {
          var darkUi = tg.colorScheme === 'dark';
          var bgHex = darkUi ? '#0d1515' : '#F4F2EC';
          if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
          if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
        } catch (e) { /* ignore older clients */ }
        if (tg.onEvent) {
          tg.onEvent('themeChanged', function () {
            if (typeof window.__applyTrainerPassProductsTheme === 'function') {
              window.__applyTrainerPassProductsTheme();
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
      var initData = tg ? tg.initData : '';
      var ISSUED_PAGE_SIZE = 20;
      function initDataParam() {
        return initData ? '?init_data=' + encodeURIComponent(initData) : '';
      }
      /** Append init_data with correct ? or & when path already has query params. */
      function apiFetchUrl(path) {
        var url = apiUrl(path);
        if (initData) {
          url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
        }
        return url;
      }
      function headers() {
        var h = { 'Content-Type': 'application/json' };
        if (initData) h['X-Telegram-Init-Data'] = initData;
        return h;
      }
      function apiUrl(path) { return '/api/webapp' + path; }

      function trainerClientCardUrl(clientId) {
        var path = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
        return path + 'trainer-clients?client_id=' + encodeURIComponent(String(clientId));
      }

      function syncPassIssueBackLabels() {
        var returnCid = state.returnClientId;
        var backBtn = document.getElementById('btnPassIssueSuccessBack');
        var cancelBtn = document.getElementById('btnCancelPassIssue');
        if (backBtn) backBtn.textContent = returnCid ? 'К карточке клиента' : 'К списку';
        if (cancelBtn) cancelBtn.textContent = returnCid ? 'Назад' : 'Отмена';
      }

      function leavePassIssueScreen() {
        if (state.returnClientId) {
          window.location.href = trainerClientCardUrl(state.returnClientId);
          return;
        }
        leavePassIssueToCatalog();
      }

      var state = {
        items: [],
        editingId: null,
        certItems: [],
        editingCertId: null,
        editingCert: null,
        activeTab: 'passes',
        clients: [],
        services: [],
        prefillClientIdForPassIssue: null,
        prefillPassProductIdForPassIssue: null,
        returnClientId: null,
        prefillCertProductIdForIssue: null,
        prefillCertRecipientEmail: null,
        prefillCertRecipientName: null,
        prefillCertPurchasedByName: null,
        prefillClientIdForCertIssue: null,
        passIssueFilteredClients: [],
        passIssueSelectedClientId: null,
        passIssueSelectedClient: null,
        certIssueSubmitting: false,
        certIssueIdempotencyKey: null,
        certIssuePurchasedByName: null,
        issuedItems: [],
        issuedLoaded: false,
        issuedSearchTimer: null,
        issuedKind: 'all',
        issuedStatus: 'all',
        issuedPage: 0,
        issuedTotal: 0,
        issuedHasMore: false,
        issuedActiveCount: 0,
        passDetailId: null,
        passDetail: null,
        passDetailRedemptions: [],
        passDetailRedeemable: [],
        passDetailReturnTab: 'issued',
        passDetailReturnClientId: null,
      };

      function postClientInviteLinkFirstCopyRecorded() {
        if (!initData) return;
        fetch(apiUrl('/trainer/welcome-link/first-copy') + initDataParam(), {
          method: 'POST',
          headers: headers(),
        }).catch(function() {});
      }

      function showScreen(id) {
        document.querySelectorAll('[data-screen]').forEach(function(el) { el.classList.remove('active'); });
        var el = document.getElementById(id);
        if (el) el.classList.add('active');
        document.documentElement.classList.remove('pp-boot-pass-issue');
        var backBtn = document.getElementById('btnBack');
        if (backBtn) {
          var needsAppBack = id === 'screenPassDetail' || id === 'screenPassIssue' ||
            id === 'screenForm' || id === 'screenCertForm' || id === 'screenCertIssue' ||
            id === 'screenPassWelcomeLink';
          backBtn.hidden = !needsAppBack;
          backBtn.onclick = needsAppBack ? function() {
            if (id === 'screenPassDetail') leavePassDetailScreen();
            else if (id === 'screenPassIssue') leavePassIssueScreen();
            else if (id === 'screenForm') { showScreen('screenList'); setTab('passes'); loadList(); }
            else if (id === 'screenCertForm') { showScreen('screenList'); setTab('certs'); loadCertList(); }
            else if (id === 'screenCertIssue') { showScreen('screenList'); setTab('certs'); }
            else if (id === 'screenPassWelcomeLink') { showScreen('screenList'); setTab('passes'); }
          } : null;
        }
        if (id === 'screenPassDetail' || id === 'screenList') {
          try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) { window.scrollTo(0, 0); }
        }
      }

      function tgHaptic(kind) {
        try {
          var tg = window.Telegram && window.Telegram.WebApp;
          if (tg && tg.HapticFeedback) {
            if (kind === 'success' && typeof tg.HapticFeedback.notificationOccurred === 'function') {
              tg.HapticFeedback.notificationOccurred('success');
            } else if (typeof tg.HapticFeedback.impactOccurred === 'function') {
              tg.HapticFeedback.impactOccurred('light');
            }
          }
        } catch (e) { /* ignore */ }
      }

      function passDetailLoadingSkeletonHtml() {
        return '<div class="pp-pass-detail-skeleton" aria-hidden="true">' +
          '<div class="pp-pass-detail-skeleton-row"></div>' +
          '<div class="pp-pass-detail-skeleton-row"></div>' +
          '<div class="pp-pass-detail-skeleton-row"></div>' +
          '</div>';
      }

      /** Deep-link from client card / pass order: ?client_id=… [&pass_product_id=…] */
      function parsePassIssueDeepLink() {
        var params = new URLSearchParams(window.location.search || '');
        if (params.get('certificate_product_id')) return null;
        if (params.get('pass_instance_id')) return null;
        var tab = (params.get('tab') || '').toLowerCase();
        if (tab === 'certs' || tab === 'cert' || tab === 'certificates') return null;
        var clientId = parseInt(params.get('client_id') || '', 10);
        if (!clientId) return null;
        var passProductId = parseInt(params.get('pass_product_id') || '', 10);
        return {
          clientId: clientId,
          passProductId: passProductId > 0 ? passProductId : null,
        };
      }

      function setPassIssueBootLoading(on) {
        var boot = document.getElementById('passIssueBootLoading');
        var body = document.getElementById('passIssueBody');
        if (boot) boot.hidden = !on;
        if (body) body.hidden = on;
        document.documentElement.classList.toggle('pp-boot-pass-issue', on);
      }

      function showPassIssueBootError(title, text) {
        var boot = document.getElementById('passIssueBootLoading');
        if (!boot) return;
        boot.innerHTML =
          '<div class="pp-state pp-state--error"><div class="pp-state-icon" aria-hidden="true">⚠️</div>' +
          '<p class="pp-state-title">' + escapeHtml(title) + '</p>' +
          (text ? '<p class="pp-state-text">' + escapeHtml(text) + '</p>' : '') +
          '</div>';
        boot.hidden = false;
        var body = document.getElementById('passIssueBody');
        if (body) body.hidden = true;
      }

      function fetchPassIssuePrerequisites() {
        var itemsP = state.items.length > 0
          ? Promise.resolve()
          : fetch(apiUrl('/trainer/pass-products') + initDataParam(), { headers: headers() })
              .then(function(r) { return r.json(); })
              .then(function(data) { state.items = data.items || []; });
        var clientsP = state.clients.length > 0
          ? Promise.resolve()
          : fetch(apiUrl('/trainer/clients') + initDataParam(), { headers: headers() })
              .then(function(r) { return r.json(); })
              .then(function(data) { state.clients = data.clients || []; })
              .catch(function() { state.clients = []; });
        return Promise.all([itemsP, clientsP]);
      }

      function runPassIssueDeepLink(deepLink) {
        state.returnClientId = deepLink.clientId;
        state.prefillClientIdForPassIssue = deepLink.clientId;
        if (deepLink.passProductId) state.prefillPassProductIdForPassIssue = deepLink.passProductId;
        setTab('passes');
        showScreen('screenPassIssue');
        setPassIssueBootLoading(true);
        fetchPassIssuePrerequisites()
          .then(function() {
            var activePasses = (state.items || []).filter(function(p) { return p.is_active; });
            if (!activePasses.length) {
              showPassIssueBootError('Нет активных абонементов', 'Сначала добавьте абонемент в каталоге.');
              return;
            }
            if (!(state.clients || []).length) {
              showPassIssueBootError('Нет клиентов', 'Клиенты появятся после записей на занятия.');
              return;
            }
            if (!(state.clients || []).some(function(c) { return c.id === deepLink.clientId; })) {
              showPassIssueBootError('Клиент не найден', 'Обновите список клиентов и попробуйте снова.');
              return;
            }
            setPassIssueBootLoading(false);
            openPassIssueScreen();
            var heroSub = document.getElementById('passIssueHeroSub');
            if (heroSub) heroSub.textContent = 'Выберите абонемент для выдачи.';
          })
          .catch(function() {
            showPassIssueBootError('Не удалось загрузить', 'Откройте мини-приложение из бота и попробуйте снова.');
          });
      }
      function setTab(tab) {
        state.activeTab = tab;
        document.querySelectorAll('.tab').forEach(function(t) { t.classList.toggle('active', t.dataset.tab === tab); });
        var panelPasses = document.getElementById('panelPasses');
        var panelCerts = document.getElementById('panelCerts');
        var panelIssued = document.getElementById('panelIssued');
        if (panelPasses) panelPasses.classList.toggle('active', tab === 'passes');
        if (panelCerts) panelCerts.classList.toggle('active', tab === 'certs');
        if (panelIssued) panelIssued.classList.toggle('active', tab === 'issued');
      }
      (function applyUrlTabFromQuery() {
        var params = new URLSearchParams(window.location.search || '');
        var tab = (params.get('tab') || '').toLowerCase();
        if (tab === 'certs' || tab === 'cert' || tab === 'certificates') {
          setTab('certs');
        } else if (tab === 'issued' || tab === 'issued-items') {
          setTab('issued');
        }
      })();

      function formatIssuedDate(iso) {
        if (!iso) return '—';
        try {
          var d = new Date(iso);
          return ('0' + d.getDate()).slice(-2) + '.' + ('0' + (d.getMonth() + 1)).slice(-2) + '.' + d.getFullYear();
        } catch (e) { return iso; }
      }

      function issuedKindLabel(kind) {
        return kind === 'certificate' ? 'Сертификат' : 'Абонемент';
      }

      function renderIssuedPagination() {
        var pagEl = document.getElementById('issuedPagination');
        if (!pagEl) return;
        var total = state.issuedTotal || 0;
        if (total <= ISSUED_PAGE_SIZE) {
          pagEl.hidden = true;
          pagEl.innerHTML = '';
          return;
        }
        var totalPages = Math.max(1, Math.ceil(total / ISSUED_PAGE_SIZE));
        var page = state.issuedPage + 1;
        var from = state.issuedPage * ISSUED_PAGE_SIZE + 1;
        var to = Math.min(total, (state.issuedPage + 1) * ISSUED_PAGE_SIZE);
        var html = '';
        html += '<button type="button" class="pp-issued-page-btn" id="issuedPagePrev"' +
          (state.issuedPage <= 0 ? ' disabled' : '') + '>◀ Назад</button>';
        html += '<span>' + from + '–' + to + ' из ' + total + ' · стр. ' + page + '/' + totalPages + '</span>';
        html += '<button type="button" class="pp-issued-page-btn" id="issuedPageNext"' +
          (!state.issuedHasMore ? ' disabled' : '') + '>Вперёд ▶</button>';
        pagEl.innerHTML = html;
        pagEl.hidden = false;
        var prevBtn = document.getElementById('issuedPagePrev');
        if (prevBtn && !prevBtn.disabled) {
          prevBtn.onclick = function() {
            if (state.issuedPage <= 0) return;
            state.issuedPage -= 1;
            loadIssuedList();
          };
        }
        var nextBtn = document.getElementById('issuedPageNext');
        if (nextBtn && !nextBtn.disabled) {
          nextBtn.onclick = function() {
            if (!state.issuedHasMore) return;
            state.issuedPage += 1;
            loadIssuedList();
          };
        }
      }

      function issuedStatusBucket(it) {
        if (it.status_bucket === 'active' || it.status_bucket === 'closed') return it.status_bucket;
        if (it.kind === 'pass') return it.status === 'active' ? 'active' : 'closed';
        if (it.kind === 'certificate') {
          var st = it.status || '';
          return (st === 'active' || st === 'issued' || st === 'activated') ? 'active' : 'closed';
        }
        return 'closed';
      }

      function renderIssuedSummary() {
        var statusEl = document.getElementById('issuedStatusFilter');
        var statusVal = statusEl ? statusEl.value : 'all';
        if (statusVal !== 'all' || !state.issuedTotal) return '';
        var active = state.issuedActiveCount != null ? state.issuedActiveCount : 0;
        var closed = Math.max(0, state.issuedTotal - active);
        return '<div class="pp-issued-summary" role="note">' +
          '<span class="pp-issued-summary-dot pp-issued-summary-dot--live">' +
          escapeHtml(String(active)) + ' активных</span>' +
          '<span class="pp-issued-summary-dot pp-issued-summary-dot--closed">' +
          escapeHtml(String(closed)) + ' закрытых</span>' +
          '</div>';
      }

      function formatBookingSlotLabel(item) {
        if (!item) return '—';
        var d = item.slot_date || '';
        if (d && d.indexOf('T') >= 0) d = d.split('T')[0];
        var parts = d ? d.split('-') : [];
        var dateRu = parts.length === 3 ? parts[2] + '.' + parts[1] + '.' + parts[0] : d;
        var weekday = '';
        if (parts.length === 3) {
          try {
            var dt = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
            var wd = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'][dt.getDay()];
            if (wd) weekday = wd + ', ';
          } catch (e) { /* ignore */ }
        }
        var st = (item.start_time || '').slice(0, 5);
        var et = (item.end_time || '').slice(0, 5);
        var timePart = st && et ? (st + '–' + et) : (st || '');
        var head = (weekday + dateRu).trim();
        return (head + (timePart ? ' · ' + timePart : '')).trim() || '—';
      }

      function formatBookingPriceHint(cents) {
        if (cents == null || cents <= 0) return 'Без абонемента';
        return 'Оплачено разово · ' + formatPricePlain(cents);
      }

      function passStatusLabelRu(status) {
        var map = { active: 'Активен', used_up: 'Использован', cancelled: 'Отменён' };
        return map[status] || status || '—';
      }

      function passDetailPhoneHtml(phone) {
        var p = String(phone || '').trim();
        if (!p) return '—';
        var Pf = window.CrmPhoneField;
        if (Pf && typeof Pf.phoneTelLinkHtml === 'function') {
          return Pf.phoneTelLinkHtml(p, 'bd-tel', escapeHtml);
        }
        return escapeHtml(p);
      }

      function renderPassDetailMetaRows(p) {
        var host = document.getElementById('passDetailMetaRows');
        if (!host || !p) return;
        var rows = [];
        rows.push({ label: 'Клиент', value: p.client_name || '—' });
        if (p.client_phone) rows.push({ label: 'Телефон', value: p.client_phone, isPhone: true });
        rows.push({ label: 'Услуги', value: p.service_scope || 'На все услуги' });
        if (p.issued_at) rows.push({ label: 'Выдан', value: formatIssuedDate(p.issued_at) });
        if (p.expires_at) rows.push({ label: 'Срок', value: 'до ' + formatIssuedDate(p.expires_at) });
        var html = '';
        rows.forEach(function(row) {
          html += '<div class="bd-row"><div class="bd-row-text">';
          html += '<div class="bd-row-label">' + escapeHtml(row.label) + '</div>';
          html += '<div class="bd-row-value">' + (row.isPhone ? passDetailPhoneHtml(row.value) : escapeHtml(row.value)) + '</div>';
          html += '</div></div>';
        });
        host.innerHTML = html;
        if (window.CrmPhoneField && typeof window.CrmPhoneField.wirePhoneCallButtons === 'function') {
          window.CrmPhoneField.wirePhoneCallButtons(host);
        }
      }

      function openPassDetail(passInstanceId, opts) {
        opts = opts || {};
        state.passDetailId = passInstanceId;
        state.passDetailReturnTab = opts.returnTab || 'issued';
        state.passDetailReturnClientId = opts.returnClientId || null;
        showScreen('screenPassDetail');
        document.getElementById('passDetailProduct').textContent = '…';
        document.getElementById('passDetailClient').textContent = 'Загрузка…';
        var statusEl = document.getElementById('passDetailStatus');
        if (statusEl) statusEl.hidden = true;
        document.getElementById('passDetailMetaRows').innerHTML = passDetailLoadingSkeletonHtml();
        document.getElementById('passDetailRedeemableList').innerHTML = passDetailLoadingSkeletonHtml();
        document.getElementById('passDetailHistorySection').hidden = true;
        document.getElementById('passDetailRedeemSection').hidden = true;
        document.getElementById('passDetailFootnote').hidden = true;
        fetch(apiFetchUrl('/trainer/pass-instances/' + encodeURIComponent(String(passInstanceId))), { headers: headers() })
          .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
          .then(function(o) {
            if (!o.ok) {
              var detail = o.data && o.data.detail;
              throw new Error(typeof detail === 'string' ? detail : 'Не удалось загрузить абонемент');
            }
            state.passDetail = o.data.pass || null;
            state.passDetailRedemptions = o.data.redemptions || [];
            state.passDetailRedeemable = o.data.redeemable_bookings || [];
            renderPassDetailScreen();
          })
          .catch(function(err) {
            document.getElementById('passDetailRedeemableList').innerHTML =
              '<div class="pp-state pp-state--error"><p class="pp-state-title">' +
              escapeHtml(err.message || 'Ошибка загрузки') + '</p></div>';
          });
      }

      function renderPassDetailScreen(opts) {
        opts = opts || {};
        var p = state.passDetail;
        if (!p) return;
        document.getElementById('passDetailProduct').textContent = p.product_name || 'Абонемент';
        document.getElementById('passDetailClient').textContent = p.client_name || 'Клиент';
        var statusEl = document.getElementById('passDetailStatus');
        if (statusEl) {
          var st = (p.status || '').trim();
          statusEl.hidden = !st;
          statusEl.textContent = passStatusLabelRu(st);
          statusEl.className = 'pp-pass-detail-status ' +
            (st === 'active' ? 'pp-pass-detail-status--live' : 'pp-pass-detail-status--closed');
        }
        var rem = typeof p.sessions_remaining === 'number' ? p.sessions_remaining : 0;
        var total = typeof p.sessions_total === 'number' ? p.sessions_total : 0;
        document.getElementById('passDetailRem').textContent = String(rem);
        document.getElementById('passDetailTotal').textContent = String(total);
        var pct = total > 0 ? Math.round(100 * rem / total) : 0;
        document.getElementById('passDetailProgress').style.width = pct + '%';
        var statCard = document.getElementById('passDetailStatCard');
        if (statCard && opts.pulseStat) {
          statCard.classList.remove('is-updated');
          void statCard.offsetWidth;
          statCard.classList.add('is-updated');
        }
        renderPassDetailMetaRows(p);

        var footnote = document.getElementById('passDetailFootnote');
        if (footnote) footnote.hidden = !p.can_redeem;

        var redeemSection = document.getElementById('passDetailRedeemSection');
        var redeemList = document.getElementById('passDetailRedeemableList');
        if (!p.can_redeem) {
          redeemSection.hidden = true;
        } else {
          redeemSection.hidden = false;
          if (!state.passDetailRedeemable.length) {
            redeemList.innerHTML =
              '<div class="pp-state pp-state--empty"><div class="pp-state-icon" aria-hidden="true">✓</div>' +
              '<p class="pp-state-title">Нечего списать</p>' +
              '<p class="pp-state-text">Нет подходящих занятий: либо всё уже учтено, либо запись ещё не завершилась, ' +
              'либо абонемент не покрывает услугу/тариф этой записи. Проверьте карточку клиента и расписание.</p></div>';
          } else {
            var html = '<div class="bd-rows">';
            state.passDetailRedeemable.forEach(function(b) {
              html += '<button type="button" class="pp-redeem-booking-row" data-booking-id="' + b.booking_id + '">';
              html += '<span class="pp-redeem-booking-row__icon" aria-hidden="true">🏋</span>';
              html += '<span class="pp-redeem-booking-row__main">';
              html += '<div class="pp-redeem-booking-row__date">' + escapeHtml(formatBookingSlotLabel(b)) + '</div>';
              html += '<div class="pp-redeem-booking-row__meta">' +
                escapeHtml(b.service_name || 'Занятие') + ' · ' +
                escapeHtml(formatBookingPriceHint(b.price_cents));
              if (b.needs_complete) {
                html += ' · спишется и отметит проведённым';
              }
              html += '</div>';
              html += '</span>';
              html += '<span class="pp-redeem-booking-row__chip">−1</span>';
              html += '</button>';
            });
            html += '</div>';
            redeemList.innerHTML = html;
            redeemList.querySelectorAll('.pp-redeem-booking-row').forEach(function(btn) {
              btn.onclick = function() {
                var bid = parseInt(btn.dataset.bookingId, 10);
                if (!bid || !state.passDetailId || btn.disabled) return;
                var booking = state.passDetailRedeemable.find(function(x) { return x.booking_id === bid; }) || {};
                var label = formatBookingSlotLabel(booking);
                var confirmExtra = booking.needs_complete
                  ? '\n\nЗапись ещё не отмечена проведённой — при списании отметим её как проведённую.'
                  : '';
                showAppConfirm(
                  'Списать 1 занятие с абонемента?\n\n' + label + confirmExtra +
                    '\n\nВ статистике визит будет учтён как оплаченный абонементом.',
                  { okText: 'Списать', cancelText: 'Отмена' }
                ).then(function(ok) {
                  if (!ok) return;
                  redeemList.querySelectorAll('.pp-redeem-booking-row').forEach(function(b) { b.disabled = true; });
                  btn.querySelector('.pp-redeem-booking-row__chip').textContent = '…';
                  fetch(apiFetchUrl('/trainer/pass-instances/' + encodeURIComponent(String(state.passDetailId)) + '/redeem'), {
                    method: 'POST',
                    headers: headers(),
                    body: JSON.stringify({ booking_id: bid }),
                  })
                    .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
                    .then(function(o) {
                      if (!o.ok) {
                        var detail = o.data && o.data.detail;
                        throw new Error(typeof detail === 'string' ? detail : 'Не удалось списать');
                      }
                      state.passDetail = o.data.pass || state.passDetail;
                      state.passDetailRedemptions = o.data.redemptions || [];
                      state.passDetailRedeemable = o.data.redeemable_bookings || [];
                      state.issuedLoaded = false;
                      tgHaptic('success');
                      renderPassDetailScreen({ pulseStat: true });
                      if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.showPopup) {
                        window.Telegram.WebApp.showPopup({
                          message: 'Занятие списано · осталось ' + (state.passDetail.sessions_remaining || 0) + ' из ' + (state.passDetail.sessions_total || 0),
                          buttons: [{ type: 'ok' }],
                        });
                      }
                    })
                    .catch(function(err) {
                      redeemList.querySelectorAll('.pp-redeem-booking-row').forEach(function(b) { b.disabled = false; });
                      if (btn.querySelector('.pp-redeem-booking-row__chip')) {
                        btn.querySelector('.pp-redeem-booking-row__chip').textContent = '−1';
                      }
                      alert(err.message || 'Ошибка списания');
                    });
                });
              };
            });
          }
        }

        var histSection = document.getElementById('passDetailHistorySection');
        var histList = document.getElementById('passDetailRedemptionList');
        if (!state.passDetailRedemptions.length) {
          histSection.hidden = true;
        } else {
          histSection.hidden = false;
          var histHtml = '';
          state.passDetailRedemptions.forEach(function(r) {
            histHtml += '<div class="bd-row pp-redemption-row">';
            histHtml += '<span class="pp-redemption-row__dot" aria-hidden="true"></span>';
            histHtml += '<div class="pp-redemption-row__text">';
            histHtml += '<div class="pp-redemption-row__date">' + escapeHtml(formatBookingSlotLabel(r)) + '</div>';
            histHtml += '<div class="pp-redemption-row__service">' + escapeHtml(r.service_name || 'Занятие') + '</div>';
            histHtml += '</div></div>';
          });
          histList.innerHTML = histHtml;
        }
      }

      function leavePassDetailScreen() {
        if (state.passDetailReturnClientId) {
          window.location.href = trainerClientCardUrl(state.passDetailReturnClientId);
          return;
        }
        showScreen('screenList');
        setTab(state.passDetailReturnTab || 'issued');
        if (state.passDetailReturnTab === 'issued') loadIssuedList();
      }

      function renderIssuedList() {
        var wrap = document.getElementById('issuedListContent');
        var hintEl = document.getElementById('issuedHint');
        if (!wrap) return;
        if (hintEl) hintEl.style.display = state.issuedTotal > 0 ? 'block' : 'none';
        if (!state.issuedItems.length) {
          var kindEl = document.getElementById('issuedKindFilter');
          var statusEl = document.getElementById('issuedStatusFilter');
          var searchEl = document.getElementById('issuedSearch');
          var kindVal = kindEl ? kindEl.value : 'all';
          var statusVal = statusEl ? statusEl.value : 'all';
          var emptyText = (kindVal !== 'all' || statusVal !== 'all' ||
            (searchEl && (searchEl.value || '').trim()))
            ? 'По выбранным фильтрам ничего не найдено'
            : 'Выданные абонементы и сертификаты появятся здесь после первой выдачи.';
          wrap.innerHTML = '<div class="pp-state pp-state--empty"><div class="pp-state-icon" aria-hidden="true">📋</div><p class="pp-state-title">Пока ничего не выдано</p><p class="pp-state-text">' + escapeHtml(emptyText) + '</p></div>';
          renderIssuedPagination();
          return;
        }
        var html = renderIssuedSummary();
        state.issuedItems.forEach(function(it) {
          var kindCls = it.kind === 'certificate' ? 'pp-issued-card--cert' : 'pp-issued-card--pass';
          var bucket = issuedStatusBucket(it);
          var lifeCls = bucket === 'active' ? 'pp-issued-card--live' : 'pp-issued-card--closed';
          var statusCls = bucket === 'active' ? 'pp-issued-status--live' : 'pp-issued-status--closed';
          var clickable = it.kind === 'pass' && bucket === 'active' && (it.sessions_remaining || 0) > 0;
          var cardTag = clickable ? 'button' : 'div';
          var cardExtra = clickable ? ' pp-issued-card--clickable' : '';
          var cardAttrs = clickable
            ? ' type="button" class="pp-issued-card ' + kindCls + ' ' + lifeCls + cardExtra + '" data-pass-id="' + it.id + '"'
            : ' class="pp-issued-card ' + kindCls + ' ' + lifeCls + '"';
          html += '<' + cardTag + cardAttrs + '>';
          html += '<div class="pp-issued-card-head">';
          html += '<span class="pp-issued-kind">' + escapeHtml(issuedKindLabel(it.kind)) + '</span>';
          html += '<span class="pp-issued-status ' + statusCls + '">' + escapeHtml(it.status_label_ru || it.status || '—') + '</span>';
          html += '</div>';
          html += '<div class="pp-issued-date">' + escapeHtml(formatIssuedDate(it.issued_at)) + '</div>';
          html += '<div class="pp-issued-title">' + escapeHtml(it.product_name || '—') + '</div>';
          html += '<div class="pp-issued-meta">Клиент: ' + escapeHtml(it.client_label_ru || '—') + '</div>';
          if (it.client_phone) {
            html += '<div class="pp-issued-meta">' + escapeHtml(it.client_phone) + '</div>';
          }
          if (it.kind === 'pass') {
            html += '<div class="pp-issued-balance"><strong>' + (it.sessions_remaining != null ? it.sessions_remaining : 0) + '</strong> из ' + (it.sessions_total != null ? it.sessions_total : 0) + ' занятий</div>';
            if (it.service_scope) {
              html += '<div class="pp-issued-meta">Услуги: ' + escapeHtml(it.service_scope) + '</div>';
            } else {
              html += '<div class="pp-issued-meta">На все услуги</div>';
            }
            if (clickable) {
              html += '<div class="pp-issued-redeem-cta">Списать прошедшее занятие</div>';
            }
          } else {
            if (it.recipient_name && it.recipient_name !== (it.client_label_ru || '')) {
              html += '<div class="pp-issued-meta">Получатель: ' + escapeHtml(it.recipient_name) + '</div>';
            }
            if (it.amount_remaining_cents != null) {
              html += '<div class="pp-issued-balance">Остаток: <strong>' + escapeHtml(formatPricePlain(it.amount_remaining_cents)) + '</strong></div>';
            } else if (it.amount_cents != null) {
              html += '<div class="pp-issued-balance">Номинал: <strong>' + escapeHtml(formatPricePlain(it.amount_cents)) + '</strong></div>';
            }
            if (it.code) {
              html += '<div class="pp-issued-meta pp-issued-code">Код: ' + escapeHtml(it.code) + '</div>';
            }
          }
          if (it.expires_at) {
            html += '<div class="pp-issued-meta">Срок: до ' + escapeHtml(formatIssuedDate(it.expires_at)) + '</div>';
          }
          html += '</' + cardTag + '>';
        });
        wrap.innerHTML = html;
        wrap.querySelectorAll('[data-pass-id]').forEach(function(btn) {
          btn.onclick = function() {
            var pid = parseInt(btn.dataset.passId, 10);
            if (pid) {
              tgHaptic('light');
              openPassDetail(pid, { returnTab: 'issued' });
            }
          };
        });
        renderIssuedPagination();
      }

      function loadIssuedList() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        var host = document.getElementById('issuedListContent');
        if (!host) return;
        host.innerHTML = '<div class="pp-state pp-state--loading"><div class="pp-state-icon" aria-hidden="true">⏳</div><p class="pp-state-title">Загрузка</p><div class="pp-loading-dots" aria-hidden="true"><span></span><span></span><span></span></div></div>';
        var pagEl = document.getElementById('issuedPagination');
        if (pagEl) {
          pagEl.hidden = true;
          pagEl.innerHTML = '';
        }
        var searchEl = document.getElementById('issuedSearch');
        var kindEl = document.getElementById('issuedKindFilter');
        var statusEl = document.getElementById('issuedStatusFilter');
        var kind = kindEl ? kindEl.value : 'all';
        var status = statusEl ? statusEl.value : 'all';
        state.issuedKind = kind;
        state.issuedStatus = status;
        var q = searchEl ? (searchEl.value || '').trim() : '';
        var offset = state.issuedPage * ISSUED_PAGE_SIZE;
        var path = '/trainer/issued-items?kind=' + encodeURIComponent(kind) +
          '&status=' + encodeURIComponent(status) +
          '&limit=' + ISSUED_PAGE_SIZE +
          '&offset=' + offset;
        if (q) path += '&q=' + encodeURIComponent(q);
        fetch(apiFetchUrl(path), { headers: headers() })
          .then(function(r) { return r.json().then(function(data) { return { ok: r.ok, data: data }; }); })
          .then(function(o) {
            if (!o.ok) {
              var detail = o.data && o.data.detail;
              var msg = typeof detail === 'string' ? detail : 'Не удалось загрузить список';
              throw new Error(msg);
            }
            state.issuedItems = (o.data && o.data.items) ? o.data.items : [];
            state.issuedTotal = (o.data && typeof o.data.total === 'number') ? o.data.total : state.issuedItems.length;
            state.issuedActiveCount = (o.data && typeof o.data.active_count === 'number') ? o.data.active_count : 0;
            state.issuedHasMore = !!(o.data && o.data.has_more);
            state.issuedLoaded = true;
            renderIssuedList();
          })
          .catch(function() {
            host.innerHTML = '<div class="pp-state pp-state--error"><div class="pp-state-icon" aria-hidden="true">⚠️</div><p class="pp-state-title">Не удалось загрузить</p><p class="pp-state-text">Проверьте соединение и попробуйте снова.</p></div>';
            if (pagEl) {
              pagEl.hidden = true;
              pagEl.innerHTML = '';
            }
          });
      }

      function scheduleIssuedReload() {
        if (state.issuedSearchTimer) clearTimeout(state.issuedSearchTimer);
        state.issuedSearchTimer = setTimeout(function() {
          if (state.activeTab === 'issued') {
            state.issuedPage = 0;
            loadIssuedList();
          }
        }, 320);
      }

      function formatPricePlain(cents) {
        if (cents == null) return '—';
        return (cents / 100).toFixed(2).replace(/\.?0+$/, '') + ' BYN';
      }

      function formatPrice(cents) {
        if (cents == null) return '—';
        return (cents / 100).toFixed(2).replace(/\.?0+$/, '') + ' BYN';
      }

      function escapeHtml(s) {
        if (s == null) return '';
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
      }

      function renderList() {
        var wrap = document.getElementById('listContent');
        var hintEl = document.getElementById('productsHint');
        if (hintEl) hintEl.style.display = state.items.length > 0 ? 'block' : 'none';
        if (state.items.length === 0) {
          wrap.innerHTML = '<div class="pp-state pp-state--empty"><div class="pp-state-icon" aria-hidden="true">📦</div><p class="pp-state-title">Пока нет абонементов</p><p class="pp-state-text">Добавьте первый — клиенты смогут покупать их у вас через платформу.</p></div>';
          return;
        }
        var html = '';
        state.items.forEach(function(p) {
          var serviceLabel = (p.service_name && p.service_name.trim()) ? p.service_name.trim() : 'любая услуга';
          var scopeParts = [serviceLabel];
          if (p.tiers_label && p.tiers_label.trim()) scopeParts.push(p.tiers_label.trim());
          var meta = p.sessions_total + ' занятий · ' + formatPrice(p.price_cents) + ' · ' + scopeParts.join(', тарифы: ');
          var cardClass = 'product-card';
          if (!p.is_active) cardClass += ' inactive';
          if (p.scope_valid === false) cardClass += ' product-card--scope-warn';
          html += '<button type="button" class="' + cardClass + '" data-id="' + p.id + '">';
          html += '<div class="main">';
          html += '<div class="title">' + escapeHtml(p.name) + '</div>';
          html += '<div class="meta">' + meta + '</div>';
          if (p.scope_valid === false && p.scope_warning) {
            html += '<div class="product-card-scope-warn">' + escapeHtml(p.scope_warning) + '</div>';
          }
          html += '</div>';
          html += '<span class="arrow">→</span></button>';
        });
        wrap.innerHTML = html;
        wrap.querySelectorAll('.product-card').forEach(function(btn) {
          btn.onclick = function() {
            var id = parseInt(btn.dataset.id, 10);
            var p = state.items.find(function(x) { return x.id === id; });
            if (p) { state.editingId = p.id; showScreen('screenForm'); openForm(p); }
          };
        });
      }

      function updateActiveLabel() {
        var checked = document.getElementById('inputActive').checked;
        document.getElementById('labelActive').textContent = checked
          ? 'Активен (клиенты видят в каталоге)'
          : 'Неактивен (скрыт из каталога)';
      }

      function getPassProductSelectedServiceIds() {
        var host = document.getElementById('passProductServicesHost');
        if (!host) return [];
        var ids = [];
        host.querySelectorAll('input.pp-svc-cb:checked').forEach(function(cb) {
          var v = parseInt(cb.value, 10);
          if (!isNaN(v)) ids.push(v);
        });
        return ids;
      }

      function renderPassProductServiceCheckboxes(selectedIds) {
        var host = document.getElementById('passProductServicesHost');
        if (!host) return;
        var sel = {};
        (selectedIds || []).forEach(function(id) { sel[String(id)] = true; });
        host.innerHTML = '';
        if (!(state.services || []).length) {
          host.innerHTML = '<div class="cert-issued-empty">Нет услуг — добавьте услуги в профиле тренера.</div>';
          return;
        }
        (state.services || []).forEach(function(s) {
          var row = document.createElement('label');
          row.className = 'pp-svc-row';
          var cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.className = 'pp-svc-cb';
          cb.value = String(s.id);
          if (sel[String(s.id)]) cb.checked = true;
          cb.addEventListener('change', onPassProductScopeChanged);
          row.appendChild(cb);
          var span = document.createElement('span');
          span.textContent = s.name || ('Услуга #' + s.id);
          row.appendChild(span);
          host.appendChild(row);
        });
      }

      /** Tier kinds bookable for current service selection (intersection when services picked). */
      function getPassProductAvailableTierKinds(serviceIds) {
        var services = state.services || [];
        if (!services.length) {
          return TIER_KINDS.map(function(t) { return t.kind; });
        }
        if (!serviceIds || !serviceIds.length) {
          var union = {};
          services.forEach(function(s) {
            (s.price_tiers || []).forEach(function(pt) {
              if (pt.tier_kind) union[pt.tier_kind] = true;
            });
          });
          return TIER_KINDS.map(function(t) { return t.kind; }).filter(function(k) { return union[k]; });
        }
        var pool = services.filter(function(s) {
          return serviceIds.indexOf(s.id) >= 0 || serviceIds.indexOf(String(s.id)) >= 0;
        });
        if (!pool.length) return [];
        return TIER_KINDS.map(function(t) { return t.kind; }).filter(function(kind) {
          return pool.every(function(s) {
            return (s.price_tiers || []).some(function(pt) { return pt.tier_kind === kind; });
          });
        });
      }

      function updatePassTiersHint(serviceIds, availableKinds) {
        var hint = document.getElementById('passTiersHint');
        if (!hint) return;
        if (!availableKinds.length) {
          hint.innerHTML = serviceIds && serviceIds.length
            ? 'Для выбранных услуг нет общих тарифов в профиле — добавьте тарифы в «Профиль» или снимите услуги.'
            : 'Не отмечайте ни одного — абонемент подходит ко <b>всем</b> тарифам.';
          return;
        }
        if (serviceIds && serviceIds.length) {
          hint.innerHTML = 'Показаны тарифы, которые настроены для <b>всех</b> выбранных услуг.';
          return;
        }
        hint.innerHTML = 'Не отмечайте ни одного — абонемент подходит ко <b>всем</b> тарифам. Иначе — только отмеченные тарифы из профиля.';
      }

      function onPassProductScopeChanged() {
        var selectedSvc = getPassProductSelectedServiceIds();
        var selectedTiers = getPassProductSelectedTierKinds();
        var available = getPassProductAvailableTierKinds(selectedSvc);
        selectedTiers = selectedTiers.filter(function(k) { return available.indexOf(k) >= 0; });
        renderPassProductTierCheckboxes(selectedTiers, available);
        updatePassTiersHint(selectedSvc, available);
      }

      var TIER_KINDS = [
        { kind: 'child',           label: 'Детский' },
        { kind: 'adult',           label: 'Взрослый' },
        { kind: 'two_children',    label: '2 ребенка' },
        { kind: 'two_adults',      label: '2 взрослых' },
        { kind: 'adult_and_child', label: 'Взрослый + ребенок' },
      ];

      function getPassProductSelectedTierKinds() {
        var host = document.getElementById('passProductTiersHost');
        if (!host) return [];
        var kinds = [];
        host.querySelectorAll('input.pp-tier-cb:checked').forEach(function(cb) {
          if (cb.value) kinds.push(cb.value);
        });
        return kinds;
      }

      function renderPassProductTierCheckboxes(selectedKinds, availableKinds) {
        var host = document.getElementById('passProductTiersHost');
        if (!host) return;
        var selectedSvc = getPassProductSelectedServiceIds();
        if (!availableKinds) availableKinds = getPassProductAvailableTierKinds(selectedSvc);
        var availableSet = {};
        (availableKinds || []).forEach(function(k) { availableSet[k] = true; });
        var sel = {};
        (selectedKinds || []).forEach(function(k) { sel[k] = true; });
        host.innerHTML = '';
        if (!availableKinds.length && !(selectedKinds || []).length) {
          host.innerHTML = '<div class="cert-issued-empty">Нет доступных тарифов для текущего выбора услуг.</div>';
          updatePassTiersHint(selectedSvc, availableKinds);
          return;
        }
        TIER_KINDS.forEach(function(t) {
          var show = !!availableSet[t.kind] || !!sel[t.kind];
          if (!show) return;
          var row = document.createElement('label');
          row.className = 'pp-svc-row' + (availableSet[t.kind] ? '' : ' pp-tier-row--invalid');
          var cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.className = 'pp-tier-cb';
          cb.value = t.kind;
          cb.disabled = !availableSet[t.kind];
          if (sel[t.kind] && availableSet[t.kind]) cb.checked = true;
          row.appendChild(cb);
          var span = document.createElement('span');
          span.textContent = t.label + (availableSet[t.kind] ? '' : ' · не в профиле');
          row.appendChild(span);
          host.appendChild(row);
        });
        updatePassTiersHint(selectedSvc, availableKinds);
      }

      /** Paint service/tier multiselects; iOS Telegram WebView skips nodes built under display:none. */
      function repaintPassProductScopeFields(preSelectedSvc, preSelectedTiers) {
        renderPassProductServiceCheckboxes(preSelectedSvc);
        var available = getPassProductAvailableTierKinds(preSelectedSvc);
        var tiers = (preSelectedTiers || []).filter(function(k) { return available.indexOf(k) >= 0; });
        renderPassProductTierCheckboxes(tiers, available);
      }

      function schedulePassProductScopeRepaint(preSelectedSvc, preSelectedTiers) {
        if (typeof requestAnimationFrame !== 'function') return;
        requestAnimationFrame(function() {
          requestAnimationFrame(function() {
            repaintPassProductScopeFields(preSelectedSvc, preSelectedTiers);
          });
        });
      }

      function openForm(product) {
        document.getElementById('formTitle').textContent = product ? 'Редактировать абонемент' : 'Новый абонемент';
        document.getElementById('inputName').value = product ? product.name : '';
        document.getElementById('inputSessions').value = product ? String(product.sessions_total) : '';
        document.getElementById('inputPrice').value = product ? String(Math.round(product.price_cents / 100)) : '';
        document.getElementById('inputActive').checked = product ? product.is_active : true;
        updateActiveLabel();
        document.getElementById('groupActive').style.display = product ? 'block' : 'none';
        document.getElementById('btnDeleteProduct').style.display = product ? 'block' : 'none';
        state.editingId = product ? product.id : null;
        var preSelectedSvc = product && Array.isArray(product.service_ids) ? product.service_ids.slice() : [];
        var preSelectedTiers = product && Array.isArray(product.tier_kinds) ? product.tier_kinds.slice() : [];
        function applyScopeFields() {
          repaintPassProductScopeFields(preSelectedSvc, preSelectedTiers);
          schedulePassProductScopeRepaint(preSelectedSvc, preSelectedTiers);
        }
        if (state.services.length === 0) {
          fetch(apiUrl('/trainer/my-services') + initDataParam(), { headers: headers() })
            .then(function(r) { return r.json(); })
            .then(function(data) { state.services = data.services || []; applyScopeFields(); })
            .catch(function() { applyScopeFields(); });
        } else {
          applyScopeFields();
        }
      }

      function loadList() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        document.getElementById('listContent').innerHTML = '<div class="pp-state pp-state--loading"><div class="pp-state-icon" aria-hidden="true">⏳</div><p class="pp-state-title">Загрузка</p><div class="pp-loading-dots" aria-hidden="true"><span></span><span></span><span></span></div></div>';
        fetch(apiUrl('/trainer/pass-products') + initDataParam(), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            state.items = data.items || [];
            renderList();
          })
          .catch(function() {
            document.getElementById('listContent').innerHTML = '<div class="pp-state pp-state--error"><div class="pp-state-icon" aria-hidden="true">⚠️</div><p class="pp-state-title">Не удалось загрузить</p><p class="pp-state-text">Откройте мини-приложение из бота и попробуйте снова.</p></div>';
          });
      }

      document.getElementById('inputActive').onchange = function() {
        updateActiveLabel();
      };

      function applyPassIssueClientFilter() {
        var q = (document.getElementById('passIssueClientSearch').value || '').trim();
        if (!q) {
          state.passIssueFilteredClients = (state.clients || []).slice();
        } else {
          var qLower = q.toLowerCase();
          var digits = q.replace(/\D/g, '');
          state.passIssueFilteredClients = (state.clients || []).filter(function(c) {
            var name = ((c.first_name || '') + ' ' + (c.last_name || '')).trim().toLowerCase();
            var phone = (c.phone || '').toLowerCase();
            var phoneDigits = (c.phone || '').replace(/\D/g, '');
            return name.indexOf(qLower) !== -1
              || phone.indexOf(qLower) !== -1
              || (digits && phoneDigits.indexOf(digits) !== -1);
          });
        }
        renderPassIssueClientList();
      }
      function renderPassIssueClientList() {
        var wrap = document.getElementById('passIssueClientList');
        var list = state.passIssueSelectedClientId ? [] : state.passIssueFilteredClients;
        if (list.length === 0) {
          wrap.innerHTML = '<div class="cert-issued-empty">' + (state.passIssueFilteredClients.length === 0 && (document.getElementById('passIssueClientSearch').value || '').trim() ? 'Никого не найдено' : 'Введите имя или телефон') + '</div>';
          return;
        }
        var html = '';
        list.forEach(function(cl) {
          var name = [cl.first_name, cl.last_name].filter(Boolean).join(' ').trim() || cl.phone || 'Клиент #' + cl.id;
          var phone = (cl.phone || '').trim() || '—';
          var selected = state.passIssueSelectedClientId === cl.id ? ' selected' : '';
          html += '<button type="button" class="pass-issue-client-card' + selected + '" data-id="' + cl.id + '">';
          html += '<span class="pass-issue-client-name">' + escapeHtml(name) + '</span>';
          html += '<span class="pass-issue-client-phone">' + escapeHtml(phone) + '</span>';
          html += '</button>';
        });
        wrap.innerHTML = html;
        wrap.querySelectorAll('.pass-issue-client-card').forEach(function(btn) {
          btn.onclick = function() {
            var id = parseInt(btn.dataset.id, 10);
            var cl = state.clients.find(function(c) { return c.id === id; });
            if (!cl) return;
            state.passIssueSelectedClientId = id;
            state.passIssueSelectedClient = cl;
            document.getElementById('passIssueSelectedName').textContent = [cl.first_name, cl.last_name].filter(Boolean).join(' ').trim() || cl.phone || 'Клиент #' + cl.id;
            document.getElementById('passIssueSelectedPhone').textContent = (cl.phone || '').trim() ? (cl.phone || '') : '';
            document.getElementById('passIssueSelectedPhone').style.display = (cl.phone || '').trim() ? '' : 'none';
            document.getElementById('passIssueClientSearchGroup').style.display = 'none';
            document.getElementById('passIssueSelectedGroup').style.display = 'block';
          };
        });
      }
      function openPassIssueScreen() {
        state.passIssueSelectedClientId = null;
        state.passIssueSelectedClient = null;
        document.getElementById('passIssueFormActions').style.display = '';
        document.getElementById('passIssueProductGroup').style.display = '';
        document.getElementById('passIssueSuccess').style.display = 'none';
        var searchEl = document.getElementById('passIssueClientSearch');
        searchEl.value = '';
        document.getElementById('passIssueClientSearchGroup').style.display = 'block';
        document.getElementById('passIssueSelectedGroup').style.display = 'none';
        state.passIssueFilteredClients = (state.clients || []).slice();
        renderPassIssueClientList();
        var productSelect = document.getElementById('passIssueProductSelect');
        productSelect.innerHTML = '<option value="">— Выберите абонемент —</option>';
        var activePasses = (state.items || []).filter(function(p) { return p.is_active; });
        activePasses.forEach(function(p) {
          var opt = document.createElement('option');
          opt.value = p.id;
          var serviceLabel = (p.service_name && p.service_name.trim()) ? p.service_name.trim() : 'любая услуга';
          var scopeStr = (p.tiers_label && p.tiers_label.trim()) ? serviceLabel + ', тарифы: ' + p.tiers_label.trim() : serviceLabel;
          opt.textContent = (p.name || '') + ' · ' + (p.sessions_total || 0) + ' занятий · ' + scopeStr;
          productSelect.appendChild(opt);
        });
        if (state.prefillClientIdForPassIssue) {
          var prefillId = state.prefillClientIdForPassIssue;
          state.prefillClientIdForPassIssue = null;
          var cl = state.clients.find(function(c) { return c.id === prefillId; });
          if (cl) {
            state.passIssueSelectedClientId = cl.id;
            state.passIssueSelectedClient = cl;
            document.getElementById('passIssueSelectedName').textContent = [cl.first_name, cl.last_name].filter(Boolean).join(' ').trim() || cl.phone || 'Клиент #' + cl.id;
            document.getElementById('passIssueSelectedPhone').textContent = (cl.phone || '').trim() || '';
            document.getElementById('passIssueSelectedPhone').style.display = (cl.phone || '').trim() ? '' : 'none';
            document.getElementById('passIssueClientSearchGroup').style.display = 'none';
            document.getElementById('passIssueSelectedGroup').style.display = 'block';
          }
        }
        if (state.prefillPassProductIdForPassIssue) {
          var wantPid = state.prefillPassProductIdForPassIssue;
          state.prefillPassProductIdForPassIssue = null;
          var optMatch = Array.from(productSelect.options).some(function(o) {
            return parseInt(o.value, 10) === wantPid;
          });
          if (optMatch) productSelect.value = String(wantPid);
        }
        syncPassIssueBackLabels();
        showScreen('screenPassIssue');
      }
      document.getElementById('passIssueClientSearch').oninput = function() {
        applyPassIssueClientFilter();
      };
      document.getElementById('passIssueChangeClient').onclick = function() {
        state.passIssueSelectedClientId = null;
        state.passIssueSelectedClient = null;
        document.getElementById('passIssueClientSearch').value = '';
        document.getElementById('passIssueClientSearchGroup').style.display = 'block';
        document.getElementById('passIssueSelectedGroup').style.display = 'none';
        state.passIssueFilteredClients = (state.clients || []).slice();
        renderPassIssueClientList();
      };
      document.getElementById('btnIssuePass').onclick = function() {
        function openWhenReady() {
          state.returnClientId = null;
          openPassIssueScreen();
        }
        Promise.resolve().then(function() {
          return fetchPassIssuePrerequisites();
        }).then(function() {
          if (state.items.filter(function(p) { return p.is_active; }).length === 0) {
            alert('Сначала добавьте хотя бы один активный абонемент.');
            return;
          }
          if (!state.clients.length) {
            alert('Нет клиентов. Клиенты появятся после записей на занятия.');
            return;
          }
          openWhenReady();
        });
      };
      function leavePassIssueToCatalog() {
        showScreen('screenList');
        setTab('passes');
        if (!state.items.length) loadList();
        if (!state.certItems.length) loadCertList();
      }
      document.getElementById('btnCancelPassIssue').onclick = leavePassIssueScreen;
      document.getElementById('btnPassIssueSuccessBack').onclick = leavePassIssueScreen;
      document.getElementById('btnSubmitPassIssue').onclick = function() {
        var clientId = state.passIssueSelectedClientId;
        var productId = parseInt(document.getElementById('passIssueProductSelect').value, 10);
        if (!clientId) { alert('Выберите клиента'); return; }
        if (!productId) { alert('Выберите абонемент'); return; }
        var btn = document.getElementById('btnSubmitPassIssue');
        btn.disabled = true;
        fetch(apiUrl('/trainer/clients/' + clientId + '/pass-issue'), {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({ pass_product_id: productId })
        })
          .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
          .then(function(o) {
            btn.disabled = false;
            if (o.ok && o.data.id) {
              document.getElementById('passIssueFormActions').style.display = 'none';
              document.getElementById('passIssueClientSearchGroup').style.display = 'none';
              document.getElementById('passIssueSelectedGroup').style.display = 'none';
              document.getElementById('passIssueProductGroup').style.display = 'none';
              document.getElementById('passIssueSuccess').style.display = 'block';
              state.issuedLoaded = false;
              state.issuedPage = 0;
            } else {
              alert(o.data.detail || 'Ошибка выдачи');
            }
          })
          .catch(function() {
            btn.disabled = false;
            alert('Ошибка сети');
          });
      };

      var tabPassesBtn = document.getElementById('tabPasses');
      if (tabPassesBtn) tabPassesBtn.onclick = function() { setTab('passes'); };
      var tabCertsBtn = document.getElementById('tabCerts');
      if (tabCertsBtn) {
        tabCertsBtn.onclick = function() {
          setTab('certs');
          if (state.certItems.length === 0) loadCertList();
        };
      }
      var tabIssuedBtn = document.getElementById('tabIssued');
      if (tabIssuedBtn) {
        tabIssuedBtn.onclick = function() {
          setTab('issued');
          loadIssuedList();
        };
      }
      var issuedSearchEl = document.getElementById('issuedSearch');
      if (issuedSearchEl) {
        issuedSearchEl.addEventListener('input', scheduleIssuedReload);
      }
      var issuedKindEl = document.getElementById('issuedKindFilter');
      if (issuedKindEl) {
        issuedKindEl.addEventListener('change', function() {
          state.issuedPage = 0;
          if (state.activeTab === 'issued') loadIssuedList();
        });
      }
      var issuedStatusEl = document.getElementById('issuedStatusFilter');
      if (issuedStatusEl) {
        issuedStatusEl.addEventListener('change', function() {
          state.issuedPage = 0;
          if (state.activeTab === 'issued') loadIssuedList();
        });
      }

      document.getElementById('certAnyAmount').onchange = function() {
        document.getElementById('certAmountGroup').style.display = document.getElementById('certAnyAmount').checked ? 'none' : 'block';
      };

      function formatCertAmountPlain(c) {
        if (c.amount_cents == null) return 'Любая сумма';
        return (c.amount_cents / 100) + ' BYN';
      }

      function formatCertAmountHtml(c) {
        if (c.amount_cents == null) return escapeHtml('Любая сумма');
        return escapeHtml(String(c.amount_cents / 100)) + ' BYN';
      }
      function certProductAmountLine(c) {
        var amount = formatCertAmountPlain(c);
        var name = (c.name || '').trim();
        if (!name) return amount;
        if (name.indexOf('BYN') !== -1 || name.indexOf('Любая сумма') !== -1) return '';
        return amount;
      }

      function renderCertList() {
        var wrap = document.getElementById('certListContent');
        if (!wrap) return;
        var hintEl = document.getElementById('certsHint');
        if (hintEl) hintEl.style.display = state.certItems.length > 0 ? 'block' : 'none';
        if (state.certItems.length === 0) {
          wrap.innerHTML = '<div class="pp-state pp-state--empty"><div class="pp-state-icon" aria-hidden="true">🎁</div><p class="pp-state-title">Пока нет сертификатов</p><p class="pp-state-text">Номинал на сумму или «любая сумма» — клиенты увидят это в вашей карточке.</p></div>';
          return;
        }
        var html = '';
        state.certItems.forEach(function(c) {
          var cardClass = 'cert-product-card';
          if (!c.is_active) cardClass += ' inactive';
          var title = escapeHtml((c.name || '').trim() || 'Подарочный сертификат');
          var amountLine = certProductAmountLine(c);
          var desc = (c.description || '').trim();
          html += '<button type="button" class="' + cardClass + '" data-id="' + c.id + '">';
          html += '<div class="main"><div class="title">' + title + '</div>';
          if (amountLine) {
            html += '<div class="cert-product-card__amount">' + escapeHtml(amountLine) + '</div>';
          }
          if (desc) {
            html += '<div class="cert-product-card__desc">' + escapeHtml(desc.length > 120 ? desc.slice(0, 117) + '…' : desc) + '</div>';
          }
          html += '</div>';
          html += '<span class="arrow">→</span></button>';
        });
        wrap.innerHTML = html;
        wrap.querySelectorAll('.cert-product-card').forEach(function(btn) {
          btn.onclick = function() {
            var id = parseInt(btn.dataset.id, 10);
            var c = state.certItems.find(function(x) { return x.id === id; });
            if (c) { state.editingCertId = c.id; openCertForm(c); showScreen('screenCertForm'); }
          };
        });
      }
      function loadCertList() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        var host = document.getElementById('certListContent');
        if (!host) return;
        host.innerHTML = '<div class="pp-state pp-state--loading"><div class="pp-state-icon" aria-hidden="true">⏳</div><p class="pp-state-title">Загрузка</p><div class="pp-loading-dots" aria-hidden="true"><span></span><span></span><span></span></div></div>';
        fetch(apiUrl('/trainer/certificate-products') + initDataParam(), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            state.certItems = data.items || [];
            renderCertList();
          })
          .catch(function() {
            host.innerHTML = '<div class="pp-state pp-state--error"><div class="pp-state-icon" aria-hidden="true">⚠️</div><p class="pp-state-title">Не удалось загрузить</p><p class="pp-state-text">Проверьте соединение и откройте экран из бота.</p></div>';
          });
      }
      function openCertForm(cert) {
        document.getElementById('certFormTitle').textContent = cert ? 'Редактировать сертификат' : 'Новый сертификат';
        var titleEl = document.getElementById('certTitle');
        var descEl = document.getElementById('certDescription');
        if (titleEl) titleEl.value = cert ? (cert.name || '') : '';
        if (descEl) descEl.value = cert ? (cert.description || '') : '';
        var anyAmount = cert ? cert.amount_cents == null : false;
        document.getElementById('certAnyAmount').checked = anyAmount;
        document.getElementById('certAmountGroup').style.display = anyAmount ? 'none' : 'block';
        document.getElementById('certAmountByn').value = cert && cert.amount_cents != null ? String(Math.round(cert.amount_cents / 100)) : '';
        document.getElementById('certActive').checked = cert ? cert.is_active : true;
        document.getElementById('certActiveGroup').style.display = cert ? 'block' : 'none';
        document.getElementById('btnDeleteCert').style.display = cert ? 'block' : 'none';
        state.editingCertId = cert ? cert.id : null;
        state.editingCert = cert || null;
      }
      var btnAddCertEl = document.getElementById('btnAddCert');
      if (btnAddCertEl) {
        btnAddCertEl.onclick = function() {
          state.editingCertId = null;
          openCertForm(null);
          showScreen('screenCertForm');
        };
      }

      function filterCertIssueClients() {
        var q = (document.getElementById('certIssueClientSearch').value || '').trim();
        if (!q) {
          state.certIssueFilteredClients = (state.clients || []).slice();
        } else {
          var qLower = q.toLowerCase();
          var digits = q.replace(/\D/g, '');
          state.certIssueFilteredClients = (state.clients || []).filter(function(c) {
            var name = ((c.first_name || '') + ' ' + (c.last_name || '')).trim().toLowerCase();
            var phone = (c.phone || '').toLowerCase();
            var phoneDigits = (c.phone || '').replace(/\D/g, '');
            return name.indexOf(qLower) !== -1
              || phone.indexOf(qLower) !== -1
              || (digits && phoneDigits.indexOf(digits) !== -1);
          });
        }
        renderCertIssueClientList();
      }
      function renderCertIssueClientList() {
        var wrap = document.getElementById('certIssueClientList');
        var list = state.certIssueSelectedClientId ? [] : (state.certIssueFilteredClients || []);
        if (list.length === 0) {
          var q = (document.getElementById('certIssueClientSearch').value || '').trim();
          wrap.innerHTML = '<div class="cert-issued-empty">' + (q ? 'Никого не найдено' : 'Введите имя или телефон или оставьте пусто') + '</div>';
          return;
        }
        var html = '';
        list.forEach(function(cl) {
          var name = [cl.first_name, cl.last_name].filter(Boolean).join(' ').trim() || cl.phone || 'Клиент #' + cl.id;
          var phone = (cl.phone || '').trim() || '—';
          var selected = state.certIssueSelectedClientId === cl.id ? ' selected' : '';
          html += '<button type="button" class="pass-issue-client-card' + selected + '" data-id="' + cl.id + '">';
          html += '<span class="pass-issue-client-name">' + escapeHtml(name) + '</span>';
          html += '<span class="pass-issue-client-phone">' + escapeHtml(phone) + '</span>';
          html += '</button>';
        });
        wrap.innerHTML = html;
        wrap.querySelectorAll('.pass-issue-client-card').forEach(function(btn) {
          btn.onclick = function() {
            var id = parseInt(btn.dataset.id, 10);
            var cl = state.clients.find(function(c) { return c.id === id; });
            if (!cl) return;
            state.certIssueSelectedClientId = id;
            state.certIssueSelectedClient = cl;
            document.getElementById('certIssueSelectedName').textContent = [cl.first_name, cl.last_name].filter(Boolean).join(' ').trim() || cl.phone || 'Клиент #' + cl.id;
            document.getElementById('certIssueSelectedPhone').textContent = (cl.phone || '').trim() ? (cl.phone || '') : '';
            document.getElementById('certIssueSelectedPhone').style.display = (cl.phone || '').trim() ? '' : 'none';
            document.getElementById('certIssueClientSearchGroup').style.display = 'none';
            document.getElementById('certIssueSelectedGroup').style.display = 'block';
          };
        });
      }
      function applyCertIssuePrefillFromState() {
        if (state.prefillCertProductIdForIssue) {
          var sel = document.getElementById('issueProductSelect');
          if (sel) sel.value = String(state.prefillCertProductIdForIssue);
        }
        var rn = document.getElementById('issueRecipientName');
        var re = document.getElementById('issueRecipientEmail');
        if (rn && state.prefillCertRecipientName) rn.value = state.prefillCertRecipientName;
        if (re && state.prefillCertRecipientEmail) re.value = state.prefillCertRecipientEmail;
        if (state.prefillCertPurchasedByName) {
          state.certIssuePurchasedByName = state.prefillCertPurchasedByName;
        }
        var cid = state.prefillClientIdForCertIssue;
        if (cid && (state.clients || []).length) {
          var cl = state.clients.find(function(c) { return c.id === cid; });
          if (cl) {
            state.certIssueSelectedClientId = cid;
            state.certIssueSelectedClient = cl;
            document.getElementById('certIssueClientSearchGroup').style.display = 'none';
            document.getElementById('certIssueSelectedGroup').style.display = 'block';
            document.getElementById('certIssueSelectedName').textContent = [cl.first_name, cl.last_name].filter(Boolean).join(' ').trim() || cl.phone || 'Клиент #' + cl.id;
            var ph = (cl.phone || '').trim();
            var pEl = document.getElementById('certIssueSelectedPhone');
            if (pEl) {
              pEl.textContent = ph || '';
              pEl.style.display = ph ? '' : 'none';
            }
          }
        }
      }
      function openCertIssueScreen() {
        state.certIssueSelectedClientId = null;
        state.certIssueSelectedClient = null;
        state.certIssueFilteredClients = (state.clients || []).slice();
        var productSelect = document.getElementById('issueProductSelect');
        productSelect.innerHTML = '<option value="">— Выберите —</option>';
        var activeCerts = (state.certItems || []).filter(function(c) { return c.is_active; });
        activeCerts.forEach(function(c) {
          var opt = document.createElement('option');
          opt.value = c.id;
          opt.textContent = formatCertAmountPlain(c);
          productSelect.appendChild(opt);
        });
        document.getElementById('certIssueClientSearch').value = '';
        document.getElementById('certIssueClientSearchGroup').style.display = 'block';
        document.getElementById('certIssueSelectedGroup').style.display = 'none';
        renderCertIssueClientList();
        document.getElementById('issueRecipientName').value = '';
        document.getElementById('issueRecipientEmail').value = '';
        state.certIssuePurchasedByName = null;
        document.getElementById('certIssueResult').style.display = 'none';
        document.getElementById('certIssueEmailSent').style.display = 'none';
        document.getElementById('certIssueDownloadLink').style.display = 'none';
        applyCertIssuePrefillFromState();
        showScreen('screenCertIssue');
      }
      var btnIssueCertEl = document.getElementById('btnIssueCert');
      if (btnIssueCertEl) {
        btnIssueCertEl.onclick = function() {
          state.prefillCertProductIdForIssue = null;
          state.prefillCertRecipientEmail = null;
          state.prefillCertRecipientName = null;
          state.prefillCertPurchasedByName = null;
          state.prefillClientIdForCertIssue = null;
          function openWhenReady() {
            openCertIssueScreen();
          }
          var certsPromise = state.certItems.length > 0
            ? Promise.resolve()
            : fetch(apiUrl('/trainer/certificate-products') + initDataParam(), { headers: headers() })
                .then(function(r) { return r.json(); })
                .then(function(data) { state.certItems = data.items || []; });
          var clientsPromise = fetch(apiUrl('/trainer/clients') + initDataParam(), { headers: headers() })
              .then(function(r) { return r.json(); })
              .then(function(data) { state.clients = data.clients || []; })
              .catch(function() { state.clients = []; });
          Promise.all([certsPromise, clientsPromise]).then(openWhenReady);
        };
      }
      document.getElementById('certIssueClientSearch').addEventListener('input', filterCertIssueClients);
      document.getElementById('certIssueChangeClient').onclick = function() {
        state.certIssueSelectedClientId = null;
        state.certIssueSelectedClient = null;
        document.getElementById('certIssueClientSearch').value = '';
        document.getElementById('certIssueClientSearchGroup').style.display = 'block';
        document.getElementById('certIssueSelectedGroup').style.display = 'none';
        state.certIssueFilteredClients = (state.clients || []).slice();
        renderCertIssueClientList();
      };
      document.getElementById('btnCancelCertIssue').onclick = function() {
        showScreen('screenList');
        setTab('certs');
      };
      document.getElementById('btnSubmitCertIssue').onclick = function() {
        if (state.certIssueSubmitting) return;
        var productId = parseInt(document.getElementById('issueProductSelect').value, 10);
        var recipientName = (document.getElementById('issueRecipientName').value || '').trim();
        var recipientEmail = (document.getElementById('issueRecipientEmail').value || '').trim() || null;
        if (!productId) { alert('Выберите сертификат (номинал)'); return; }
        if (!recipientName) { alert('Укажите имя получателя — оно будет указано в сертификате'); return; }
        var body = { certificate_product_id: productId, recipient_name: recipientName };
        if (recipientEmail) body.recipient_email = recipientEmail;
        if (state.certIssuePurchasedByName) body.purchased_by_name = state.certIssuePurchasedByName;

        var btn = document.getElementById('btnSubmitCertIssue');
        var btnText = btn.textContent;
        state.certIssueSubmitting = true;
        btn.disabled = true;
        btn.textContent = 'Отправляем…';
        state.certIssueIdempotencyKey = state.certIssueIdempotencyKey || (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : 'key-' + Date.now());

        var reqHeaders = headers();
        reqHeaders['Idempotency-Key'] = state.certIssueIdempotencyKey;
        fetch(apiUrl('/trainer/certificate-issue'), {
          method: 'POST',
          headers: reqHeaders,
          body: JSON.stringify(body)
        })
          .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
          .then(function(o) {
            if (o.ok && o.data.code) {
              document.getElementById('certIssueCode').textContent = o.data.code;
              document.getElementById('certIssueResult').style.display = 'block';
              state.lastIssuedCode = o.data.code;
              var downloadLink = document.getElementById('certIssueDownloadLink');
              if (o.data.id && o.data.file_url) {
                downloadLink.href = apiUrl('/trainer/certificates/' + o.data.id + '/file') + initDataParam();
                downloadLink.style.display = 'inline';
              } else {
                downloadLink.style.display = 'none';
              }
              var emailSentEl = document.getElementById('certIssueEmailSent');
              if (recipientEmail) {
                emailSentEl.style.display = 'block';
                if (o.data.email_sent) {
                  emailSentEl.textContent = 'Сертификат отправлен на ' + recipientEmail;
                  emailSentEl.style.color = '';
                } else if (o.data.email_pending) {
                  emailSentEl.textContent = 'Письмо будет отправлено в ближайшее время (при сбое — повторная отправка по очереди).';
                  emailSentEl.style.color = 'var(--tg-theme-hint-color, #666)';
                } else {
                  emailSentEl.textContent = 'Письмо не удалось отправить на ' + recipientEmail + '. Проверьте настройки SMTP в .env и логи сервера.';
                  emailSentEl.style.color = 'var(--tg-theme-destructive-text-color, #e53935)';
                }
              } else {
                emailSentEl.style.display = 'none';
              }
              state.issuedLoaded = false;
              state.issuedPage = 0;
            } else {
              alert(o.data.detail || 'Ошибка выдачи');
            }
          })
          .catch(function() { alert('Ошибка сети'); })
          .finally(function() {
            state.certIssueSubmitting = false;
            state.certIssueIdempotencyKey = null;
            btn.disabled = false;
            btn.textContent = btnText;
          });
      };
      document.getElementById('btnCopyCertCode').onclick = function() {
        var code = document.getElementById('certIssueCode').textContent;
        if (!code) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code).then(function() {
            alert('Код скопирован');
          }).catch(function() { alert('Код: ' + code); });
        } else {
          alert('Код: ' + code);
        }
      };

      function openPassWelcomeLinkScreen() {
        var sel = document.getElementById('passWelcomeProductSelect');
        sel.innerHTML = '<option value="">— Выберите —</option>';
        var activePasses = (state.items || []).filter(function(p) { return p.is_active !== false; });
        activePasses.forEach(function(p) {
          var opt = document.createElement('option');
          opt.value = p.id;
          opt.textContent = (p.name || '').trim() || (p.sessions_total + ' занятий · ' + formatPricePlain(p.price_cents));
          sel.appendChild(opt);
        });
        document.getElementById('passWelcomeLinkResult').style.display = 'none';
        showScreen('screenPassWelcomeLink');
      }
      var btnPassWelcomeLinkEl = document.getElementById('btnPassWelcomeLink');
      if (btnPassWelcomeLinkEl) {
        btnPassWelcomeLinkEl.onclick = function() {
          var promise = state.items.length > 0
            ? Promise.resolve()
            : fetch(apiUrl('/trainer/pass-products') + initDataParam(), { headers: headers() })
                .then(function(r) { return r.json(); })
                .then(function(data) { state.items = data.items || []; })
                .catch(function() { state.items = []; });
          promise.then(openPassWelcomeLinkScreen).catch(function() { state.items = []; openPassWelcomeLinkScreen(); });
        };
      }
      document.getElementById('btnCancelPassWelcomeLink').onclick = function() {
        showScreen('screenList');
        setTab('passes');
      };
      document.getElementById('btnGetPassWelcomeLink').onclick = function() {
        var productId = parseInt(document.getElementById('passWelcomeProductSelect').value, 10);
        if (!productId) { alert('Выберите абонемент'); return; }
        var url = apiUrl('/trainer/welcome-link/pass') + (initDataParam() ? initDataParam() + '&' : '?') + 'pass_product_id=' + productId;
        fetch(url, { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(o) {
            var link = o.welcome_link;
            if (link) {
              document.getElementById('passWelcomeLinkUrl').textContent = link;
              document.getElementById('passWelcomeLinkResult').style.display = 'block';
            } else {
              alert('Ссылка недоступна. Проверьте настройки бота.');
            }
          })
          .catch(function() { alert('Ошибка сети'); });
      };
      document.getElementById('btnCopyPassWelcomeLinkUrl').onclick = function() {
        var link = document.getElementById('passWelcomeLinkUrl').textContent;
        if (!link) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(link).then(function() {
            postClientInviteLinkFirstCopyRecorded();
            alert('Ссылка скопирована');
          }).catch(function() { alert(link); });
        } else { alert(link); }
      };

      document.getElementById('btnCancelCertForm').onclick = function() {
        showScreen('screenList');
        setTab('certs');
        loadCertList();
      };
      /** Display name for catalog (no separate title field on this screen — was reading missing #certName and crashed). */
      function buildCertProductName(anyAmount, amountCents) {
        if (anyAmount) return 'Подарочный сертификат';
        var byn = amountCents != null ? Math.round(amountCents / 100) : 0;
        return byn > 0 ? ('Сертификат ' + byn + ' BYN') : 'Подарочный сертификат';
      }
      document.getElementById('btnSaveCertForm').onclick = function() {
        var anyAmount = document.getElementById('certAnyAmount').checked;
        var amountCents = null;
        if (!anyAmount) {
          var byn = parseInt(document.getElementById('certAmountByn').value, 10);
          if (isNaN(byn) || byn < 1) { alert('Укажите сумму в BYN'); return; }
          amountCents = byn * 100;
        }
        var titleRaw = (document.getElementById('certTitle').value || '').trim();
        var descRaw = (document.getElementById('certDescription').value || '').trim();
        var name = titleRaw || buildCertProductName(anyAmount, amountCents);
        var description = descRaw || null;
        var expiresDaysInput = document.getElementById('certExpiresDays');
        var expiresInDays = null;
        if (expiresDaysInput && expiresDaysInput.value) {
          var d = parseInt(expiresDaysInput.value, 10);
          if (!isNaN(d) && d > 0) { expiresInDays = d; }
        }
        if (state.editingCertId) {
          var body = {
            name: name,
            description: description,
            amount_cents: amountCents,
            expires_in_days: expiresInDays,
            is_active: document.getElementById('certActive').checked
          };
          fetch(apiUrl('/trainer/certificate-products/' + state.editingCertId), {
            method: 'PATCH',
            headers: headers(),
            body: JSON.stringify(body)
          })
            .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
            .then(function(o) {
              if (o.ok) { showScreen('screenList'); setTab('certs'); loadCertList(); }
              else { alert(o.data.detail || 'Ошибка сохранения'); }
            })
            .catch(function() { alert('Ошибка сети'); });
        } else {
          fetch(apiUrl('/trainer/certificate-products'), {
            method: 'POST',
            headers: headers(),
            body: JSON.stringify({
              name: name,
              description: description,
              amount_cents: amountCents,
              expires_in_days: expiresInDays,
              sort_order: 0
            })
          })
            .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
            .then(function(o) {
              if (o.ok && o.data.id) { showScreen('screenList'); setTab('certs'); loadCertList(); }
              else { alert(o.data.detail || 'Ошибка создания'); }
            })
            .catch(function() { alert('Ошибка сети'); });
        }
      };
      document.getElementById('btnDeleteCert').onclick = function() {
        if (!state.editingCertId) return;
        showAppConfirm('Удалить этот сертификат?', { okText: 'Удалить', cancelText: 'Отмена' }).then(function (ok) {
          if (!ok) return;
          fetch(apiUrl('/trainer/certificate-products/' + state.editingCertId), {
            method: 'DELETE',
            headers: headers()
          })
            .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
            .then(function(o) {
              if (o.ok) { showScreen('screenList'); setTab('certs'); loadCertList(); }
              else { alert(o.data.detail || 'Ошибка удаления'); }
            })
            .catch(function() { alert('Ошибка сети'); });
        });
      };

      document.getElementById('btnAdd').onclick = function() {
        state.editingId = null;
        showScreen('screenForm');
        openForm(null);
      };

      document.getElementById('btnCancelForm').onclick = function() {
        showScreen('screenList');
        loadList();
      };

      document.getElementById('btnSaveForm').onclick = function() {
        var name = (document.getElementById('inputName').value || '').trim();
        var sessions = parseInt(document.getElementById('inputSessions').value, 10);
        var priceByn = parseInt(document.getElementById('inputPrice').value, 10);
        if (!name) { alert('Введите название'); return; }
        if (!sessions || sessions < 1) { alert('Укажите количество занятий'); return; }
        if (isNaN(priceByn) || priceByn < 0) { alert('Укажите цену в BYN'); return; }
        var priceCents = priceByn * 100;

        var serviceIds = getPassProductSelectedServiceIds();
        var tierKinds = getPassProductSelectedTierKinds();
        var availableTiers = getPassProductAvailableTierKinds(serviceIds);
        if (tierKinds.length && availableTiers.length) {
          tierKinds = tierKinds.filter(function(k) { return availableTiers.indexOf(k) >= 0; });
        }
        if (tierKinds.length === 0 && availableTiers.length === 0 && getPassProductSelectedTierKinds().length) {
          alert('Выбранные тарифы не настроены в профиле для этих услуг.');
          return;
        }
        if (state.editingId) {
          var body = { name: name, sessions_total: sessions, price_cents: priceCents, is_active: document.getElementById('inputActive').checked, service_ids: serviceIds, tier_kinds: tierKinds };
          fetch(apiUrl('/trainer/pass-products/' + state.editingId), {
            method: 'PATCH',
            headers: headers(),
            body: JSON.stringify(body)
          })
            .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
            .then(function(o) {
              if (o.ok) { showScreen('screenList'); loadList(); }
              else { alert(o.data.detail || 'Ошибка сохранения'); }
            })
            .catch(function() { alert('Ошибка сети'); });
        } else {
          var body = { name: name, sessions_total: sessions, price_cents: priceCents, service_ids: serviceIds, tier_kinds: tierKinds };
          fetch(apiUrl('/trainer/pass-products'), {
            method: 'POST',
            headers: headers(),
            body: JSON.stringify(body)
          })
            .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
            .then(function(o) {
              if (o.ok && o.data.id) { showScreen('screenList'); loadList(); }
              else { alert(o.data.detail || 'Ошибка создания'); }
            })
            .catch(function() { alert('Ошибка сети'); });
        }
      };

      document.getElementById('btnDeleteProduct').onclick = function() {
        if (!state.editingId) return;
        showAppConfirm('Удалить этот абонемент? Удаление возможно только если по нему не было покупок.', { okText: 'Удалить', cancelText: 'Отмена' }).then(function (ok) {
          if (!ok) return;
          fetch(apiUrl('/trainer/pass-products/' + state.editingId), {
            method: 'DELETE',
            headers: headers()
          })
            .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
            .then(function(o) {
              if (o.ok) { showScreen('screenList'); loadList(); }
              else { alert(o.data.detail || 'Не удалось удалить. Возможно, по абонементу уже были покупки — тогда деактивируйте его (снимите галочку «Активен»).'); }
            })
            .catch(function() { alert('Ошибка сети'); });
        });
      };

      /** Deep-link: ?pass_instance_id=… [&client_id=…] [&tab=issued] */
      function parsePassDetailDeepLink() {
        var params = new URLSearchParams(window.location.search || '');
        var pid = parseInt(params.get('pass_instance_id') || '', 10);
        if (!pid) return null;
        var clientId = parseInt(params.get('client_id') || '', 10);
        var tab = (params.get('tab') || 'issued').toLowerCase();
        return {
          passInstanceId: pid,
          returnClientId: clientId > 0 ? clientId : null,
          returnTab: tab === 'passes' || tab === 'certs' ? tab : 'issued',
        };
      }

      var passIssueDeepLink = parsePassIssueDeepLink();
      var passDetailDeepLink = parsePassDetailDeepLink();

      function startCatalogLoads() {
        loadList();
        loadCertList();
        if (state.activeTab === 'issued') loadIssuedList();
      }

      if (passDetailDeepLink) {
        var startPassDetailDeepLink = function() {
          openPassDetail(passDetailDeepLink.passInstanceId, {
            returnTab: passDetailDeepLink.returnTab,
            returnClientId: passDetailDeepLink.returnClientId,
          });
        };
        if (initData && window.TrainerMiniAppGate) {
          window.TrainerMiniAppGate.fetchAccess(initData)
            .then(function (a) {
              if (a && !window.TrainerMiniAppGate.isActive(a)) {
                window.TrainerMiniAppGate.showBlockingOverlay(a);
                return;
              }
              startPassDetailDeepLink();
            })
            .catch(startPassDetailDeepLink);
        } else {
          startPassDetailDeepLink();
        }
      } else if (passIssueDeepLink) {
        var startPassIssueDeepLink = function() {
          runPassIssueDeepLink(passIssueDeepLink);
        };
        if (initData && window.TrainerMiniAppGate) {
          window.TrainerMiniAppGate.fetchAccess(initData)
            .then(function (a) {
              if (a && !window.TrainerMiniAppGate.isActive(a)) {
                window.TrainerMiniAppGate.showBlockingOverlay(a);
                return;
              }
              startPassIssueDeepLink();
            })
            .catch(startPassIssueDeepLink);
        } else {
          startPassIssueDeepLink();
        }
      } else if (initData && window.TrainerMiniAppGate) {
        window.TrainerMiniAppGate.fetchAccess(initData)
          .then(function (a) {
            if (a && !window.TrainerMiniAppGate.isActive(a)) {
              window.TrainerMiniAppGate.showBlockingOverlay(a);
              return;
            }
            startCatalogLoads();
          })
          .catch(function () {
            startCatalogLoads();
          });
      } else {
        startCatalogLoads();
      }
      (function checkCertIssuePrefillFromRequest() {
        var params = new URLSearchParams(window.location.search || '');
        var cpidRaw = params.get('certificate_product_id');
        if (!cpidRaw) return;
        var cpid = parseInt(cpidRaw, 10);
        if (!cpid) return;
        state.prefillCertProductIdForIssue = cpid;
        state.prefillCertRecipientEmail = (params.get('recipient_email') || '').trim();
        state.prefillCertRecipientName = (params.get('recipient_name') || '').trim();
        var pbn = (params.get('purchased_by_name') || '').trim();
        state.prefillCertPurchasedByName = pbn || null;
        var cidRaw = params.get('client_id');
        if (cidRaw) {
          var cid = parseInt(cidRaw, 10);
          if (cid) state.prefillClientIdForCertIssue = cid;
        }
        setTab('certs');
        var certsP = fetch(apiUrl('/trainer/certificate-products') + initDataParam(), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) { state.certItems = data.items || []; });
        var clientsP = fetch(apiUrl('/trainer/clients') + initDataParam(), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) { state.clients = data.clients || []; })
          .catch(function() { state.clients = []; });
        Promise.all([certsP, clientsP]).then(function() {
          var active = (state.certItems || []).filter(function(c) { return c.is_active; });
          if (!active.length) return;
          openCertIssueScreen();
        });
      })();
    })();
