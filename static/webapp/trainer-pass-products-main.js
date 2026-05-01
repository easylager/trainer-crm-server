    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        tg.ready();
        tg.expand();
        if (typeof window.__applyTrainerPassProductsTheme === 'function') {
          window.__applyTrainerPassProductsTheme();
        }
        try {
          var darkUi = tg.colorScheme === 'dark' ||
            (tg.colorScheme !== 'light' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
          var bgHex = darkUi ? '#1a1a1a' : '#fffbeb';
          if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
          if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
        } catch (e) { /* ignore older clients */ }
        if (tg.onEvent) {
          tg.onEvent('themeChanged', function () {
            if (typeof window.__applyTrainerPassProductsTheme === 'function') {
              window.__applyTrainerPassProductsTheme();
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
      var initData = tg ? tg.initData : '';
      function initDataParam() {
        return initData ? '?init_data=' + encodeURIComponent(initData) : '';
      }
      function headers() {
        var h = { 'Content-Type': 'application/json' };
        if (initData) h['X-Telegram-Init-Data'] = initData;
        return h;
      }
      function apiUrl(path) { return '/api/webapp' + path; }

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
      }
      function setTab(tab) {
        state.activeTab = tab;
        document.querySelectorAll('.tab').forEach(function(t) { t.classList.toggle('active', t.dataset.tab === tab); });
        document.querySelectorAll('.tab-panel').forEach(function(p) {
          var isPasses = p.id === 'panelPasses';
          p.classList.toggle('active', (tab === 'passes' && isPasses) || (tab === 'certs' && !isPasses));
        });
      }

      var state = { items: [], editingId: null, certItems: [], editingCertId: null, editingCert: null, activeTab: 'passes', clients: [], services: [], prefillClientIdForPassIssue: null, prefillPassProductIdForPassIssue: null, passIssueFilteredClients: [], passIssueSelectedClientId: null, passIssueSelectedClient: null, certIssueSubmitting: false, certIssueIdempotencyKey: null };

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
          var meta = p.sessions_total + ' занятий · ' + formatPrice(p.price_cents) + ' · ' + serviceLabel;
          var cardClass = 'product-card';
          if (!p.is_active) cardClass += ' inactive';
          html += '<button type="button" class="' + cardClass + '" data-id="' + p.id + '">';
          html += '<div class="main">';
          html += '<div class="title">' + escapeHtml(p.name) + '</div>';
          html += '<div class="meta">' + meta + '</div>';
          html += '</div>';
          html += '<span class="arrow">→</span></button>';
        });
        wrap.innerHTML = html;
        wrap.querySelectorAll('.product-card').forEach(function(btn) {
          btn.onclick = function() {
            var id = parseInt(btn.dataset.id, 10);
            var p = state.items.find(function(x) { return x.id === id; });
            if (p) { state.editingId = p.id; openForm(p); showScreen('screenForm'); }
          };
        });
      }

      function updateActiveLabel() {
        var checked = document.getElementById('inputActive').checked;
        document.getElementById('labelActive').textContent = checked
          ? 'Активен (клиенты видят в каталоге)'
          : 'Неактивен (скрыт из каталога)';
      }

      function fillServiceSelect() {
        var sel = document.getElementById('inputServiceId');
        if (!sel) return;
        var current = sel.value;
        sel.innerHTML = '<option value="">Любая услуга</option>';
        (state.services || []).forEach(function(s) {
          var opt = document.createElement('option');
          opt.value = s.id;
          opt.textContent = s.name || '—';
          sel.appendChild(opt);
        });
        if (current) sel.value = current;
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
        var serviceIdVal = product && product.service_id ? String(product.service_id) : '';
        if (state.services.length === 0) {
          fetch(apiUrl('/trainer/my-services') + initDataParam(), { headers: headers() })
            .then(function(r) { return r.json(); })
            .then(function(data) { state.services = data.services || []; fillServiceSelect(); document.getElementById('inputServiceId').value = serviceIdVal; })
            .catch(function() { fillServiceSelect(); document.getElementById('inputServiceId').value = serviceIdVal; });
        } else {
          fillServiceSelect();
          document.getElementById('inputServiceId').value = serviceIdVal;
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
          opt.textContent = (p.name || '') + ' · ' + (p.sessions_total || 0) + ' занятий · ' + serviceLabel;
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
          openPassIssueScreen();
        }
        var itemsPromise = state.items.length > 0
          ? Promise.resolve()
          : fetch(apiUrl('/trainer/pass-products') + initDataParam(), { headers: headers() })
              .then(function(r) { return r.json(); })
              .then(function(data) { state.items = data.items || []; });
        var clientsPromise = fetch(apiUrl('/trainer/clients') + initDataParam(), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) { state.clients = data.clients || []; })
          .catch(function() { state.clients = []; });
        Promise.all([itemsPromise, clientsPromise]).then(function() {
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
      document.getElementById('btnCancelPassIssue').onclick = function() {
        showScreen('screenList');
        setTab('passes');
      };
      document.getElementById('btnPassIssueSuccessBack').onclick = function() {
        showScreen('screenList');
        setTab('passes');
      };
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
            } else {
              alert(o.data.detail || 'Ошибка выдачи');
            }
          })
          .catch(function() {
            btn.disabled = false;
            alert('Ошибка сети');
          });
      };

      document.getElementById('tabPasses').onclick = function() { setTab('passes'); };
      document.getElementById('tabCerts').onclick = function() {
        setTab('certs');
        if (state.certItems.length === 0) loadCertList();
      };

      document.getElementById('certAnyAmount').onchange = function() {
        document.getElementById('certAmountGroup').style.display = document.getElementById('certAnyAmount').checked ? 'none' : 'block';
      };

      function formatCertAmount(c) {
        if (c.amount_cents == null) return 'Любая сумма';
        return (c.amount_cents / 100) + ' BYN';
      }
      function renderCertList() {
        var wrap = document.getElementById('certListContent');
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
          html += '<button type="button" class="' + cardClass + '" data-id="' + c.id + '">';
          html += '<div class="main"><div class="title">' + escapeHtml(formatCertAmount(c)) + '</div></div>';
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
        document.getElementById('certListContent').innerHTML = '<div class="pp-state pp-state--loading"><div class="pp-state-icon" aria-hidden="true">⏳</div><p class="pp-state-title">Загрузка</p><div class="pp-loading-dots" aria-hidden="true"><span></span><span></span><span></span></div></div>';
        fetch(apiUrl('/trainer/certificate-products') + initDataParam(), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            state.certItems = data.items || [];
            renderCertList();
          })
          .catch(function() {
            document.getElementById('certListContent').innerHTML = '<div class="pp-state pp-state--error"><div class="pp-state-icon" aria-hidden="true">⚠️</div><p class="pp-state-title">Не удалось загрузить</p><p class="pp-state-text">Проверьте соединение и откройте экран из бота.</p></div>';
          });
      }
      function openCertForm(cert) {
        document.getElementById('certFormTitle').textContent = cert ? 'Редактировать сертификат' : 'Новый сертификат';
        var anyAmount = cert ? cert.amount_cents == null : true;
        document.getElementById('certAnyAmount').checked = anyAmount;
        document.getElementById('certAmountGroup').style.display = anyAmount ? 'none' : 'block';
        document.getElementById('certAmountByn').value = cert && cert.amount_cents != null ? String(Math.round(cert.amount_cents / 100)) : '';
        document.getElementById('certActive').checked = cert ? cert.is_active : true;
        document.getElementById('certActiveGroup').style.display = cert ? 'block' : 'none';
        document.getElementById('btnDeleteCert').style.display = cert ? 'block' : 'none';
        state.editingCertId = cert ? cert.id : null;
        state.editingCert = cert || null;
      }
      document.getElementById('btnAddCert').onclick = function() {
        state.editingCertId = null;
        openCertForm(null);
        showScreen('screenCertForm');
      };

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
          opt.textContent = formatCertAmount(c);
          productSelect.appendChild(opt);
        });
        document.getElementById('certIssueClientSearch').value = '';
        document.getElementById('certIssueClientSearchGroup').style.display = 'block';
        document.getElementById('certIssueSelectedGroup').style.display = 'none';
        renderCertIssueClientList();
        document.getElementById('issueRecipientName').value = '';
        document.getElementById('issueRecipientEmail').value = '';
        document.getElementById('certIssueResult').style.display = 'none';
        document.getElementById('certIssueEmailSent').style.display = 'none';
        document.getElementById('certIssueDownloadLink').style.display = 'none';
        showScreen('screenCertIssue');
      }
      document.getElementById('btnIssueCert').onclick = function() {
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
          opt.textContent = (p.name || '').trim() || (p.sessions_total + ' занятий · ' + formatPrice(p.price_cents));
          sel.appendChild(opt);
        });
        document.getElementById('passWelcomeLinkResult').style.display = 'none';
        showScreen('screenPassWelcomeLink');
      }
      document.getElementById('btnPassWelcomeLink').onclick = function() {
        var promise = state.items.length > 0
          ? Promise.resolve()
          : fetch(apiUrl('/trainer/pass-products') + initDataParam(), { headers: headers() })
              .then(function(r) { return r.json(); })
              .then(function(data) { state.items = data.items || []; })
              .catch(function() { state.items = []; });
        promise.then(openPassWelcomeLinkScreen).catch(function() { state.items = []; openPassWelcomeLinkScreen(); });
      };
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
        var name = buildCertProductName(anyAmount, amountCents);
        var expiresDaysInput = document.getElementById('certExpiresDays');
        var expiresInDays = null;
        if (expiresDaysInput && expiresDaysInput.value) {
          var d = parseInt(expiresDaysInput.value, 10);
          if (!isNaN(d) && d > 0) { expiresInDays = d; }
        }
        if (state.editingCertId) {
          var body = {
            name: name,
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
        openForm(null);
        showScreen('screenForm');
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

        var serviceVal = document.getElementById('inputServiceId').value;
        var serviceId = serviceVal ? parseInt(serviceVal, 10) : null;
        if (state.editingId) {
          var body = { name: name, sessions_total: sessions, price_cents: priceCents, is_active: document.getElementById('inputActive').checked, service_id: serviceId };
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
          var body = { name: name, sessions_total: sessions, price_cents: priceCents, service_id: serviceId };
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

      if (initData && window.TrainerMiniAppGate) {
        window.TrainerMiniAppGate.fetchAccess(initData)
          .then(function (a) {
            if (a && !window.TrainerMiniAppGate.isActive(a)) {
              window.TrainerMiniAppGate.showBlockingOverlay(a);
              return;
            }
            loadList();
            loadCertList();
          })
          .catch(function () {
            loadList();
            loadCertList();
          });
      } else {
        loadList();
        loadCertList();
      }
      (function checkPassIssuePrefill() {
        var params = new URLSearchParams(window.location.search || '');
        var cid = params.get('client_id');
        if (cid) {
          var clientId = parseInt(cid, 10);
          if (clientId) state.prefillClientIdForPassIssue = clientId;
        }
        var ppidRaw = params.get('pass_product_id');
        if (ppidRaw) {
          var ppid = parseInt(ppidRaw, 10);
          if (ppid) state.prefillPassProductIdForPassIssue = ppid;
        }
        if (!state.prefillClientIdForPassIssue && !state.prefillPassProductIdForPassIssue) return;
        setTab('passes');
        var itemsP = fetch(apiUrl('/trainer/pass-products') + initDataParam(), { headers: headers() }).then(function(r) { return r.json(); }).then(function(data) { state.items = data.items || []; });
        var clientsP = fetch(apiUrl('/trainer/clients') + initDataParam(), { headers: headers() }).then(function(r) { return r.json(); }).then(function(data) { state.clients = data.clients || []; }).catch(function() { state.clients = []; });
        Promise.all([itemsP, clientsP]).then(function() {
          if (state.items.filter(function(p) { return p.is_active; }).length === 0 || !state.clients.length) return;
          openPassIssueScreen();
        });
      })();
    })();
