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
        if (!q) {
          state.filteredClients = state.allClients.slice();
        } else {
          var qLower = q.toLowerCase();
          var digits = q.replace(/\\D/g, '');
          state.filteredClients = state.allClients.filter(function(c) {
            var name = ((c.first_name || '') + ' ' + (c.last_name || '')).trim().toLowerCase();
            var phone = (c.phone || '').toLowerCase();
            var phoneDigits = (c.phone || '').replace(/\\D/g, '');
            return name.indexOf(qLower) !== -1
              || phone.indexOf(qLower) !== -1
              || (digits && phoneDigits.indexOf(digits) !== -1);
          });
        }
        renderList();
      }

      function clientInitials(displayName) {
        var s = (displayName || '').trim();
        if (!s) return '?';
        var parts = s.split(/\s+/).filter(Boolean);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        if (parts[0].length >= 2) return parts[0].slice(0, 2).toUpperCase();
        return parts[0][0].toUpperCase();
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

      function renderList() {
        var listEl = document.getElementById('clientsList');
        if (state.clientsListLoading) {
          listEl.innerHTML = buildClientsListSkeletonHtml();
          return;
        }
        listEl.innerHTML = '';
        if (!state.filteredClients.length) {
          listEl.innerHTML = '<div class=\"empty\"><div class=\"empty-inner\"><div class=\"empty-title\">Пока пусто</div>Пока нет клиентов с записями. Как только клиенты начнут записываться, они появятся здесь.</div></div>';
          return;
        }
        var html = state.filteredClients.map(function(c) {
          var name = ((c.first_name || '') + ' ' + (c.last_name || '')).trim() || 'Клиент';
          var initials = clientInitials(name);
          var phone = c.phone || 'Телефон не указан';
          var lastLabel = c.last_date
            ? ('Последнее занятие: ' + formatDate(c.last_date) + (c.last_start ? ' ' + formatTime(c.last_start) : ''))
            : 'Был(а) на занятии ранее';
          return (
            '<button type=\"button\" class=\"client-card\" data-id=\"' + c.id + '\">' +
              '<div class=\"client-avatar\" aria-hidden=\"true\">' + escapeHtml(initials) + '</div>' +
              '<div class=\"client-main\">' +
                '<div class=\"client-name\">' + escapeHtml(name) + '</div>' +
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
        var detailContainer = document.getElementById('clientDetail');
        var loadingBlock = document.createElement('div');
        loadingBlock.className = 'tc-history-wrap';
        loadingBlock.innerHTML = '<div class="history-section-title">История занятий</div><div class="history-list">Загрузка…</div>';
        detailContainer.appendChild(loadingBlock);
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
            totalWrap.style.display = 'flex';
          }
          var html = '';
          html += '<div class="tc-history-wrap"><div class="history-section-title">История занятий' + (total > 0 ? ' (' + total + ')' : '') + '</div>';
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
          detailContainer.removeChild(loadingBlock);
          detailContainer.insertAdjacentHTML('beforeend', html);
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
          detailContainer.removeChild(loadingBlock);
          detailContainer.insertAdjacentHTML(
            'beforeend',
            '<div class="tc-history-wrap"><div class="detail-label">История занятий</div><div class="detail-value">Не удалось загрузить историю.</div></div>'
          );
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
        var hasContent = fields.some(function(f) { return (dossierState.profile[f.key] || '').trim(); });
        // Keep expanded while editing: empty profile would otherwise re-render without .is-open and collapse the block.
        var profileExpanded = hasContent || !!dossierState.editingField;
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
            var section = document.getElementById('dossierProfileSection');
            section.classList.toggle('is-open');
          };
        }
        document.querySelectorAll('.dossier-field-value').forEach(function(el) {
          el.onclick = function() {
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
          btn.onclick = function() {
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
          renderDossier();
        }).catch(function() {
          var container = document.getElementById('dossierContainer');
          if (container) container.innerHTML = '<div class="dossier-empty">Не удалось загрузить досье</div>';
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
        }).then(function(r) { return r.json(); }).then(function(data) {
          dossierState.profile = data;
          dossierState.editingField = null;
          renderDossier();
        }).catch(function() {
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

      function openClientDetail(id) {
        var client = state.allClients.find(function(c) { return c.id === id; });
        if (!client) return;
        state.selectedClientId = id;
        var name = ((client.first_name || '') + ' ' + (client.last_name || '')).trim() || 'Клиент';
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
        var detail = '' +
          '<div class=\"tc-detail\">' +
          '<div class=\"tc-hero\">' +
            '<div class=\"tc-avatar\" aria-hidden=\"true\">' + escapeHtml(initials) + '</div>' +
            '<div class=\"tc-hero-text\">' +
              '<h1 class=\"tc-name\">' + escapeHtml(name) + '</h1>' +
              (firstDateLabel ? '<p class=\"tc-since\">' + escapeHtml(firstDateLabel) + '</p>' : '') +
            '</div>' +
          '</div>' +
          '<div class=\"tc-stats\">' +
            '<span class=\"tc-stat\"><span class=\"tc-stat-label\">Последнее</span><strong id=\"clientLastLabel\">' + escapeHtml(lastLabel) + '</strong></span>' +
            '<span class=\"tc-stat\"><span class=\"tc-stat-label\">Следующее</span><strong id=\"clientNextBooking\">…</strong></span>' +
            '<span class=\"tc-stat\" id=\"clientTotalWrap\" style=\"display:none;\"><span class=\"tc-stat-label\">Всего занятий</span><strong id=\"clientTotalCount\">0</strong></span>' +
          '</div>' +
          '<div class=\"tc-section-label\">Контакты и абонементы</div>' +
          '<div class=\"tc-rows\">' +
            '<div class=\"tc-row\"><div class=\"detail-label\">Телефон</div><div class=\"detail-value\">' + phoneDisplay + '</div></div>' +
            '<div class=\"tc-row\" id=\"clientPassesCertsBlock\">' +
              '<div class=\"detail-label\">Абонементы и сертификаты</div>' +
              '<div class=\"detail-value\" id=\"clientPassesCertsContent\">Загрузка…</div>' +
            '</div>' +
          '</div>' +
          '<div id=\"dossierContainer\"><div class=\"dossier-empty\">Загрузка досье…</div></div>' +
          '<div class=\"tc-actions\">' +
            '<a href=\"#\" class=\"bd-btn bd-btn--primary\" id=\"btnBookClient\">' + ICO_CAL + ' Записать на занятие</a>' +
            '<button type=\"button\" class=\"bd-btn bd-btn--secondary\" id=\"btnIssuePass\">' + ICO_TICKET + ' Выдать абонемент</button>';
        if (phone && phone !== '—') {
          detail += '<button type=\"button\" class=\"bd-btn bd-btn--surface\" id=\"btnCopyPhone\">' + ICO_PHONE + ' Скопировать телефон</button>';
        }
        detail += '<button type=\"button\" class=\"bd-btn bd-btn--surface\" id=\"btnWriteClient\">' + ICO_SEND + ' Написать в TG</button>';
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
        detail += '</div></div>';
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
        var writeBtn = document.getElementById('btnWriteClient');
        var username = client && client.telegram_username;
        if (writeBtn && username) {
          writeBtn.onclick = function() {
            var url = 'https://t.me/' + encodeURIComponent(username);
            if (tg && tg.openLink) {
              tg.openLink(url);
            } else {
              window.location.href = url;
            }
          };
        } else if (writeBtn) {
          writeBtn.style.display = 'none';
        }
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
            contentEl.textContent = parts.join(' · ');
          }).catch(function() {
            contentEl.textContent = 'Не удалось загрузить';
          });
        })();
        fetch(withInit('/api/webapp/trainer/clients/' + encodeURIComponent(id) + '/next-booking'))
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
              nextEl.textContent = t;
            } else {
              nextEl.textContent = '—';
            }
          })
          .catch(function() {
            var nextEl = document.getElementById('clientNextBooking');
            if (nextEl) nextEl.textContent = '—';
          });
        var bookBtn = document.getElementById('btnBookClient');
        if (bookBtn) {
          var path = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
          var bookHref = path + 'schedule-editor?flow=book&client_id=' + encodeURIComponent(id);
          if (initData) bookHref += '&init_data=' + encodeURIComponent(initData);
          bookBtn.href = bookHref;
          bookBtn.onclick = function(e) {
            e.preventDefault();
            window.location.href = bookBtn.href;
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
            state.filteredClients = state.allClients.slice();
            renderList();
            openClientDetail(id);
          })
          .catch(function(err) {
            setStateMessage(err.message || 'Клиент недоступен', 'error');
          });
      }

      function mergeFullClientList(data) {
        state.allClients = data.clients || [];
        state.filteredClients = state.allClients.slice();
        renderList();
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
            state.filteredClients = state.allClients.slice();
            state.clientsListLoading = false;
            setStateMessage('');
            renderList();
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
                state.filteredClients = state.allClients.slice();
                state.clientsListLoading = false;
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
          navigator.clipboard.writeText(link).then(function() { alert('Ссылка скопирована'); }).catch(function() { alert(link); });
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
