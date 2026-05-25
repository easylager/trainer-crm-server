(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    if (typeof tg.ready === 'function') tg.ready();
    if (typeof tg.expand === 'function') tg.expand();
    if (typeof window.__applyTrainerGroupsTheme === 'function') {
      window.__applyTrainerGroupsTheme();
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
        if (typeof window.__applyTrainerGroupsTheme === 'function') {
          window.__applyTrainerGroupsTheme();
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

  var qs = new URLSearchParams(window.location.search);
  function initFromUrl() {
    return qs.get('init_data') || qs.get('initData') || '';
  }
  var initData = (tg && tg.initData) ? tg.initData : initFromUrl();

  function syncInitFromTg() {
    if (tg && tg.initData) initData = tg.initData;
  }

  function currentInit() {
    syncInitFromTg();
    return initData || '';
  }

  var apiBase = '/api/webapp';

  function apiUrlWithQuery(path) {
    var u = apiBase + path;
    var raw = currentInit();
    if (!raw) return u;
    return u + (u.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(raw);
  }

  /** Same entry point as schedule-editor: full client card (passes, TG, history). */
  function trainerClientProfileUrl(clientId, groupId) {
    var path = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
    var u = path + 'trainer-clients?client_id=' + encodeURIComponent(String(clientId));
    if (groupId != null && groupId !== '') {
      u += '&return_from=groups&group_id=' + encodeURIComponent(String(groupId));
    }
    var raw = currentInit();
    if (raw) u += (u.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(raw);
    return u;
  }

  function trainerHubUrl() {
    var path = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
    var u = path + 'trainer-home';
    var raw = currentInit();
    if (raw) u += (u.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(raw);
    return u;
  }

  function apiHeaders() {
    var raw = currentInit();
    var h = {};
    if (raw) h['X-Telegram-Init-Data'] = raw;
    return h;
  }

  function groupsPhoneFromField(el) {
    if (window.CrmPhoneField && el) return CrmPhoneField.validate(el);
    return { ok: false, e164: '', error: 'Укажите номер телефона.' };
  }

  var DAYS = [
    { v: 1, l: 'Пн' }, { v: 2, l: 'Вт' }, { v: 3, l: 'Ср' }, { v: 4, l: 'Чт' },
    { v: 5, l: 'Пт' }, { v: 6, l: 'Сб' }, { v: 7, l: 'Вс' }
  ];
  var DOW_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
  var STATUS_RU = {
    draft: 'Черновик',
    recruiting: 'Набор',
    active: 'Идёт',
    paused: 'Пауза',
    archived: 'Архив'
  };
  var FILTER_LABELS = {
    all: 'Все',
    recruiting: 'Набор',
    active: 'Идут',
    archived: 'Архив'
  };
  var SORT_LABELS = {
    next: 'Ближайшие',
    recruiting: 'Сначала набор',
    occupancy: 'Заполненность',
    name: 'По названию'
  };
  var STATUS_SORT_PRIORITY = {
    recruiting: 0,
    active: 1,
    paused: 2,
    draft: 3,
    archived: 4
  };
  var LIST_UI_STATE_KEY = 'trainer.groups.list-ui.v2';

  var IC = {
    service: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><path d="M3.27 6.96L12 12.01l8.73-5.05"/></svg>',
    session: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>',
    users: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    inbox: '<svg class="bd-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M22 12h-6l-2 3H10l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>'
  };

  function statusPillClass(st) {
    if (st === 'recruiting') return 'tg-status-pill--recruiting';
    if (st === 'active') return 'tg-status-pill--active';
    if (st === 'archived') return 'tg-status-pill--archived';
    if (st === 'paused') return 'tg-status-pill--paused';
    return 'tg-status-pill--draft';
  }

  var state = {
    groups: [],
    filter: 'all',
    sort: 'next',
    onlyFreeSeats: false,
    detailId: null,
    addMemberGroupId: null,
    addMemberSlotId: null,
    addMemberServiceId: null,
    groupMemberIds: [],
    groupSpotsLeft: null,
    groupRosterFull: false,
    slotActionGroupId: null,
    slotActionSlotId: null,
    slotActionServiceId: null,
    slotActionCanCancel: false,
    slotActionLabel: '',
    slotActionOccupancy: '',
    selectedWeekdays: [2, 4],
    editWeekdays: [2, 4],
    editScheduleOriginalSeason: '',
    editScheduleGroupId: null,
    search: '',
    lastAddMemberPickName: null,
    /** GET /training-groups in flight — list shows layout-matched skeleton. */
    groupsListLoading: false
  };
  var addMemberSearchTimer = null;
  var tgAppToastTimer = null;
  loadPersistedListState();

  function loadPersistedListState() {
    try {
      var raw = window.localStorage ? localStorage.getItem(LIST_UI_STATE_KEY) : '';
      if (!raw) return;
      var saved = JSON.parse(raw);
      if (saved && FILTER_LABELS[saved.filter]) state.filter = saved.filter;
      if (saved && SORT_LABELS[saved.sort]) state.sort = saved.sort;
      if (saved && typeof saved.search === 'string') state.search = saved.search.slice(0, 120);
      if (saved) state.onlyFreeSeats = !!saved.onlyFreeSeats;
    } catch (e) {
      // Ignore malformed localStorage and keep defaults.
    }
  }

  function saveListUiState() {
    try {
      if (!window.localStorage) return;
      localStorage.setItem(LIST_UI_STATE_KEY, JSON.stringify({
        filter: state.filter,
        sort: state.sort,
        search: state.search,
        onlyFreeSeats: state.onlyFreeSeats
      }));
    } catch (e) {
      // Ignore WebView storage limitations.
    }
  }

  function showScreen(name) {
    document.getElementById('screenList').classList.toggle('active', name === 'list');
    document.getElementById('screenCreate').classList.toggle('active', name === 'create');
    document.getElementById('screenDetail').classList.toggle('active', name === 'detail');
    document.getElementById('fabNew').style.display = name === 'list' ? 'block' : 'none';
  }

  function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  }

  function fetchJson(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, apiHeaders(), opts.headers || {});
    if (opts.body && typeof opts.body === 'string' && !opts.headers['Content-Type']) {
      opts.headers['Content-Type'] = 'application/json';
    }
    return fetch(url, opts).then(function (r) {
      return r.text().then(function (t) {
        var j = null;
        try { j = t ? JSON.parse(t) : null; } catch (e) { j = null; }
        if (!r.ok) {
          var msg = (j && (j.detail || j.message)) || t || r.statusText;
          if (typeof msg === 'string' && /missing init data/i.test(msg)) {
            msg = 'Откройте раздел из Telegram (мини-приложение тренера).';
          }
          throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }
        return j;
      });
    });
  }

  function showTrainerGroupsToast(text) {
    var el = document.getElementById('tgAppToast');
    if (!el) return;
    el.textContent = text || '';
    el.classList.add('tg-app-toast--visible');
    clearTimeout(tgAppToastTimer);
    if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.notificationOccurred === 'function') {
      try {
        tg.HapticFeedback.notificationOccurred('success');
      } catch (e1) {
        /* ignore */
      }
    }
    tgAppToastTimer = setTimeout(function () {
      el.classList.remove('tg-app-toast--visible');
    }, 3200);
  }

  function showAddMemberStep(step) {
    var choice = document.getElementById('addMemberStepChoice');
    var existing = document.getElementById('addMemberStepExisting');
    var neu = document.getElementById('addMemberStepNew');
    var modalAm = document.getElementById('modalAddMember');
    if (modalAm) {
      modalAm.classList.toggle('book-flow-overlay--new-client', step === 'new');
    }
    if (choice) choice.classList.toggle('active', step === 'choice');
    if (existing) existing.classList.toggle('active', step === 'existing');
    if (neu) neu.classList.toggle('active', step === 'new');
  }

  function closeAddMemberModal() {
    state.addMemberGroupId = null;
    state.addMemberSlotId = null;
    state.addMemberServiceId = null;
    state.lastAddMemberPickName = null;
    var ttl = document.getElementById('addMemberTitle');
    if (ttl) ttl.textContent = 'Добавить участника';
    showAddMemberStep('choice');
    var m = document.getElementById('modalAddMember');
    if (m) {
      m.style.display = 'none';
      m.setAttribute('aria-hidden', 'true');
    }
  }

  function openAddMemberModal(gid, opts) {
    opts = opts || {};
    closeSlotActionsModal();
    state.addMemberGroupId = gid;
    state.addMemberSlotId = opts.slotId != null ? opts.slotId : null;
    state.addMemberServiceId = opts.serviceId != null ? opts.serviceId : null;
    var slotMode = !!state.addMemberSlotId;
    var ttl = document.getElementById('addMemberTitle');
    if (ttl) ttl.textContent = slotMode ? 'Запись на занятие' : 'Добавить участника';
    var lead = document.getElementById('addMemberChoiceLead');
    if (lead) lead.textContent = slotMode ? 'Кого записать на это занятие?' : 'Кого добавить в группу?';
    var exHint = document.getElementById('addMemberExistingHint');
    if (exHint) exHint.textContent = slotMode ? 'Без добавления в состав группы' : 'Существующий клиент';
    var newHint = document.getElementById('addMemberNewHint');
    if (newHint) {
      newHint.textContent = slotMode
        ? 'Одноразовая запись на этот слот — не в состав группы'
        : 'Телефон, имя — и добавить в группу';
    }
    var btnNew = document.getElementById('btnAddMemberNew');
    if (btnNew) btnNew.textContent = slotMode ? 'Создать и записать на слот' : 'Добавить в группу';
    var m = document.getElementById('modalAddMember');
    if (m) {
      m.style.display = 'flex';
      m.setAttribute('aria-hidden', 'false');
    }
    showAddMemberStep('choice');
    var search = document.getElementById('addMemberSearch');
    if (search) search.value = '';
    var ph = document.getElementById('addMemberPhone');
    var fn = document.getElementById('addMemberFn');
    var ln = document.getElementById('addMemberLn');
    if (ph) ph.value = '';
    if (fn) fn.value = '';
    if (ln) ln.value = '';
    var list = document.getElementById('addMemberClientList');
    if (list) list.innerHTML = '';
    state.lastAddMemberPickName = null;
  }

  function closeSlotActionsModal() {
    state.slotActionGroupId = null;
    state.slotActionSlotId = null;
    state.slotActionServiceId = null;
    state.slotActionCanCancel = false;
    state.slotActionLabel = '';
    state.slotActionOccupancy = '';
    var m = document.getElementById('modalSlotActions');
    if (m) {
      m.style.display = 'none';
      m.setAttribute('aria-hidden', 'true');
    }
  }

  function openSlotActionsModal(gid, opts) {
    opts = opts || {};
    state.slotActionGroupId = gid;
    state.slotActionSlotId = opts.slotId != null ? opts.slotId : null;
    state.slotActionServiceId = opts.serviceId != null ? opts.serviceId : null;
    state.slotActionCanCancel = !!opts.canCancel;
    state.slotActionLabel = opts.label || '';
    state.slotActionOccupancy = opts.occupancy || '';
    var title = document.getElementById('slotActionsTitle');
    if (title) title.textContent = state.slotActionLabel || 'Действия со слотом';
    var meta = document.getElementById('slotActionsMeta');
    if (meta) {
      var parts = [];
      if (state.slotActionOccupancy) parts.push(state.slotActionOccupancy);
      if (opts.statusLabel) parts.push(opts.statusLabel);
      meta.textContent = parts.length ? parts.join(' · ') : 'Выберите действие';
    }
    var btnCancel = document.getElementById('btnSlotActionCancel');
    if (btnCancel) btnCancel.style.display = state.slotActionCanCancel ? 'inline-flex' : 'none';
    var m = document.getElementById('modalSlotActions');
    if (m) {
      m.style.display = 'flex';
      m.setAttribute('aria-hidden', 'false');
    }
  }

  function loadAddMemberClients(q) {
    if (!state.addMemberGroupId) return;
    var host = document.getElementById('addMemberClientList');
    if (host) {
      host.innerHTML = '<p class="book-list-loading">Загрузка…</p>';
    }
    var qstr = (q || '').trim();
    var url = '/trainer/clients' + (qstr ? '?q=' + encodeURIComponent(qstr) : '');
    fetchJson(apiUrlWithQuery(url))
      .then(function (data) {
        var clients = (data && data.clients) || [];
        if (!host) return;
        host.innerHTML = clients.map(function (c) {
          var name = [c.first_name, c.last_name].filter(Boolean).join(' ').trim() || 'Клиент';
          return (
            '<button type="button" class="client-row" data-id="' + c.id + '">' +
              '<div>' + esc(name) + '</div>' +
              '<div class="phone">' + esc(c.phone || '') + '</div>' +
            '</button>'
          );
        }).join('') || '<p class="book-list-loading">Нет клиентов</p>';
        Array.prototype.forEach.call(host.querySelectorAll('.client-row'), function (btn) {
          btn.addEventListener('click', function () {
            var cid = parseInt(btn.getAttribute('data-id'), 10);
            var nameEl = btn.querySelector('div');
            state.lastAddMemberPickName = nameEl ? nameEl.textContent.trim() : '';
            postAddMember({ client_id: cid });
          });
        });
      })
      .catch(function (e) {
        if (host) host.innerHTML = '';
        alert(e.message || String(e));
      });
  }

  function postAddMember(payload) {
    var gid = state.addMemberGroupId;
    if (!gid) return;
    if (payload.client_id == null) {
      var fn = ((payload.first_name || '') + '').trim();
      if (!fn) {
        alert('Укажите имя');
        return;
      }
      var phEl = document.getElementById('addMemberPhone');
      var phCheck = groupsPhoneFromField(phEl);
      if (!phCheck.ok) {
        alert(phCheck.error || 'Укажите номер телефона.');
        return;
      }
      payload = Object.assign({}, payload, { phone: phCheck.e164 });
    }
    var slotId = state.addMemberSlotId;
    var svcId = state.addMemberServiceId;

    function bookSlotOnly(clientId) {
      return fetchJson(apiUrlWithQuery('/trainer/booking'), {
        method: 'POST',
        body: JSON.stringify({
          slot_id: slotId,
          client_id: clientId,
          service_id: svcId,
          allow_overbook: true
        })
      });
    }

    function finishOk(toastMsg) {
      closeAddMemberModal();
      if (toastMsg) showTrainerGroupsToast(toastMsg);
      openDetail(gid);
    }

    // One-off slot booking: does NOT add client to group roster (same as schedule).
    if (slotId && svcId) {
      if (payload.client_id != null) {
        bookSlotOnly(payload.client_id).then(function () {
          finishOk('Запись на занятие создана');
        }).catch(function (e) {
          alert(e.message || String(e));
        });
        return;
      }
      fetchJson(apiUrlWithQuery('/trainer/clients'), {
        method: 'POST',
        body: JSON.stringify({
          phone: payload.phone,
          first_name: payload.first_name,
          last_name: payload.last_name
        })
      })
        .then(function (res) {
          var clientId = res && res.client_id;
          if (!clientId) throw new Error('Не удалось создать клиента');
          return bookSlotOnly(clientId);
        })
        .then(function () {
          finishOk('Клиент создан и записан на занятие');
        })
        .catch(function (e) {
          alert(e.message || String(e));
        });
      return;
    }

    var memberIds = state.groupMemberIds || [];

    function postMemberOnce(body) {
      return fetchJson(apiUrlWithQuery('/trainer/training-groups/' + gid + '/members'), {
        method: 'POST',
        body: JSON.stringify(body)
      });
    }

    var cid = payload.client_id;
    var inGroup = cid != null && memberIds.indexOf(cid) >= 0;
    var needRoster = !inGroup;
    if (needRoster && state.groupRosterFull) {
      if (!confirm('Уверены, что хотите расширить группу? Лимит мест будет увеличен.')) return;
    }
    var expand = needRoster && state.groupRosterFull;
    var p = Promise.resolve();
    if (needRoster) {
      p = postMemberOnce(Object.assign({}, payload, { expand_roster: expand }));
    }
    p.then(function (res) {
      var clientId = cid != null ? cid : (res && res.client_id);
      if (!clientId) throw new Error('Не удалось определить клиента');
      var toastMsg = '';
      if (payload.client_id != null) {
        toastMsg = state.lastAddMemberPickName
          ? '«' + state.lastAddMemberPickName + '» добавлен в группу'
          : 'Участник добавлен в группу';
      } else {
        var fn0 = ((payload.first_name || '') + '').trim();
        var ln0 = ((payload.last_name || '') + '').trim();
        var disp = [fn0, ln0].filter(Boolean).join(' ').trim();
        toastMsg = disp ? ('«' + disp + '» добавлен в группу') : 'Участник добавлен в группу';
      }
      state.lastAddMemberPickName = null;
      finishOk(toastMsg);
      return clientId;
    })
      .catch(function (e) {
        alert(e.message || String(e));
      });
  }

  function bindAddMemberModal() {
    var modal = document.getElementById('modalAddMember');
    if (modal) {
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeAddMemberModal();
      });
    }
    var cancel = document.getElementById('btnAddMemberCancel');
    if (cancel) cancel.addEventListener('click', closeAddMemberModal);
    var optEx = document.getElementById('btnAddMemberOptExisting');
    if (optEx) {
      optEx.addEventListener('click', function () {
        showAddMemberStep('existing');
        var search = document.getElementById('addMemberSearch');
        loadAddMemberClients(search ? search.value.trim() : '');
        if (search) search.focus();
      });
    }
    var optNew = document.getElementById('btnAddMemberOptNew');
    if (optNew) optNew.addEventListener('click', function () {
      showAddMemberStep('new');
      var ph = document.getElementById('addMemberPhone');
      if (ph) ph.focus();
    });
    var backEx = document.getElementById('btnAddMemberBackExisting');
    if (backEx) backEx.addEventListener('click', function () { showAddMemberStep('choice'); });
    var backNew = document.getElementById('btnAddMemberBackNew');
    if (backNew) backNew.addEventListener('click', function () { showAddMemberStep('choice'); });
    var search = document.getElementById('addMemberSearch');
    if (search) {
      search.addEventListener('input', function () {
        clearTimeout(addMemberSearchTimer);
        var q = search.value.trim();
        addMemberSearchTimer = setTimeout(function () {
          loadAddMemberClients(q);
        }, 300);
      });
    }
    var btnNew = document.getElementById('btnAddMemberNew');
    if (btnNew) {
      btnNew.addEventListener('click', function () {
        postAddMember({
          phone: '',
          first_name: document.getElementById('addMemberFn') ? document.getElementById('addMemberFn').value : '',
          last_name: document.getElementById('addMemberLn') ? document.getElementById('addMemberLn').value : ''
        });
      });
    }
    if (window.CrmPhoneField) CrmPhoneField.initAll(document.getElementById('modalAddMember') || document);
  }

  function bindSlotActionsModal() {
    var modal = document.getElementById('modalSlotActions');
    if (modal) {
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeSlotActionsModal();
      });
    }
    var btnClose = document.getElementById('btnSlotActionClose');
    if (btnClose) btnClose.addEventListener('click', closeSlotActionsModal);
    var btnAdd = document.getElementById('btnSlotActionAdd');
    if (btnAdd) {
      btnAdd.addEventListener('click', function () {
        var gid = state.slotActionGroupId;
        var sid = state.slotActionSlotId;
        var svc = state.slotActionServiceId;
        closeSlotActionsModal();
        if (!gid || !sid || !svc) return;
        openAddMemberModal(gid, { slotId: sid, serviceId: svc });
      });
    }
    var btnCancel = document.getElementById('btnSlotActionCancel');
    if (btnCancel) {
      btnCancel.addEventListener('click', function () {
        var gid = state.slotActionGroupId;
        var sid = state.slotActionSlotId;
        if (!gid || !sid || !state.slotActionCanCancel) return;
        if (!confirm('Отменить это занятие? Слот станет недоступен.')) return;
        fetchJson(apiUrlWithQuery('/trainer/training-groups/' + gid + '/slots/' + sid + '/cancel'), { method: 'POST' })
          .then(function () {
            closeSlotActionsModal();
            openDetail(gid);
          })
          .catch(function (e) {
            alert(e.message || String(e));
          });
      });
    }
  }

  function setRefreshButtonLoading(isLoading) {
    var btn = document.getElementById('btnRefreshList');
    if (!btn) return;
    btn.disabled = !!isLoading;
    btn.style.opacity = isLoading ? '0.72' : '1';
  }

  function hasActiveListRefinement() {
    return state.filter !== 'all' || !!normalizeText(state.search) || state.sort !== 'next' || state.onlyFreeSeats;
  }

  function syncListControls() {
    var searchInput = document.getElementById('groupSearch');
    if (searchInput && searchInput.value !== state.search) searchInput.value = state.search;
    Array.prototype.forEach.call(document.querySelectorAll('#filterChips .tg-chip[data-filter]'), function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-filter') === state.filter);
    });
    var sortSelect = document.getElementById('sortSelect');
    if (sortSelect && sortSelect.value !== state.sort) sortSelect.value = state.sort;
    var sortLabel = document.getElementById('sortLabel');
    if (sortLabel && sortSelect) {
      var opt = sortSelect.options[sortSelect.selectedIndex];
      if (opt) sortLabel.textContent = opt.text;
    }
    var freeSeatsToggle = document.getElementById('onlyFreeSeats');
    if (freeSeatsToggle) {
      freeSeatsToggle.checked = !!state.onlyFreeSeats;
      var freeSeatsWrap = freeSeatsToggle.closest('.tg-chip-toggle');
      if (freeSeatsWrap) freeSeatsWrap.classList.toggle('is-on', !!state.onlyFreeSeats);
    }
    var resetBtn = document.getElementById('btnResetListState');
    if (resetBtn) resetBtn.style.display = hasActiveListRefinement() ? 'inline-flex' : 'none';
  }

  function resetListRefinements(opts) {
    state.filter = 'all';
    state.sort = 'next';
    state.onlyFreeSeats = false;
    state.search = '';
    saveListUiState();
    renderList();
    if (opts && opts.focusSearch) {
      var searchInput = document.getElementById('groupSearch');
      if (searchInput) searchInput.focus();
    }
  }

  function loadList() {
    var elErr = document.getElementById('listError');
    elErr.style.display = 'none';
    if (!currentInit()) {
      state.groupsListLoading = false;
      elErr.textContent = 'Данные сессии Telegram не переданы. Откройте «Группы» из мини-приложения тренера в боте.';
      elErr.style.display = 'block';
      document.getElementById('groupList').innerHTML = '';
      document.getElementById('fabNew').style.display = 'none';
      return Promise.resolve();
    }
    state.groupsListLoading = true;
    renderList();
    setRefreshButtonLoading(true);
    return fetchJson(apiUrlWithQuery('/trainer/training-groups'))
      .then(function (data) {
        state.groups = data.groups || [];
        showScreen('list');
      })
      .catch(function (e) {
        var m = e.message || String(e);
        if (/missing init data/i.test(m)) m = 'Откройте раздел из Telegram (мини-приложение тренера).';
        if (/subscription module required:\s*groups/i.test(m)) {
          // Access denied by subscription: hide groups screen and route back to hub.
          window.location.replace(trainerHubUrl());
          return;
        }
        elErr.textContent = m;
        elErr.style.display = 'block';
      })
      .finally(function () {
        state.groupsListLoading = false;
        renderList();
        setRefreshButtonLoading(false);
      });
  }

  function groupMatchesFilter(g) {
    if (state.filter === 'all') return true;
    return g.status === state.filter;
  }

  function normalizeText(v) {
    return String(v || '').toLowerCase().replace(/ё/g, 'е').trim();
  }

  function groupMatchesSearch(g) {
    var q = normalizeText(state.search);
    if (!q) return true;
    var hay = normalizeText([g.name, g.service_name, g.arena_name, STATUS_RU[g.status] || g.status].join(' '));
    return hay.indexOf(q) >= 0;
  }

  function groupCapacity(g) {
    var cap = Number(g && g.max_members);
    if (!isFinite(cap) || cap <= 0) return 1;
    return Math.round(cap);
  }

  function groupOccupancy(g) {
    var occ = Number(g && g.member_count);
    if (!isFinite(occ) || occ < 0) return 0;
    return Math.round(occ);
  }

  function groupFreeSeats(g) {
    return Math.max(0, groupCapacity(g) - groupOccupancy(g));
  }

  function groupMatchesOnlyFreeSeats(g) {
    if (!state.onlyFreeSeats) return true;
    return groupFreeSeats(g) > 0;
  }

  function nextSessionTs(g) {
    if (!g || !g.next_session_at) return Number.MAX_SAFE_INTEGER;
    var ts = new Date(g.next_session_at).getTime();
    return isFinite(ts) ? ts : Number.MAX_SAFE_INTEGER;
  }

  function sortRows(rows) {
    var copied = rows.slice();
    copied.sort(function (a, b) {
      if (state.sort === 'name') {
        return String(a.name || '').localeCompare(String(b.name || ''), 'ru', { sensitivity: 'base' });
      }
      if (state.sort === 'occupancy') {
        var ratioA = groupOccupancy(a) / groupCapacity(a);
        var ratioB = groupOccupancy(b) / groupCapacity(b);
        if (ratioB !== ratioA) return ratioB - ratioA;
        return nextSessionTs(a) - nextSessionTs(b);
      }
      if (state.sort === 'recruiting') {
        var prA = STATUS_SORT_PRIORITY[a.status] != null ? STATUS_SORT_PRIORITY[a.status] : 9;
        var prB = STATUS_SORT_PRIORITY[b.status] != null ? STATUS_SORT_PRIORITY[b.status] : 9;
        if (prA !== prB) return prA - prB;
        return nextSessionTs(a) - nextSessionTs(b);
      }
      return nextSessionTs(a) - nextSessionTs(b);
    });
    return copied;
  }

  function updateSearchClearVisibility() {
    var btn = document.getElementById('btnClearSearch');
    if (!btn) return;
    btn.style.display = normalizeText(state.search) ? 'inline-flex' : 'none';
  }

  function formatSeasonDate(v) {
    if (!v) return '';
    var p = String(v).split('-');
    if (p.length !== 3) return String(v);
    var dt = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    if (isNaN(dt.getTime())) return String(v);
    return dt.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
  }

  function formatNextSession(v) {
    if (!v) return 'не запланировано';
    var dt = new Date(v);
    if (isNaN(dt.getTime())) return 'не запланировано';
    // Human-readable relative day label keeps schedule scanning fast.
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var eventDay = new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
    var diff = Math.round((eventDay - today) / 86400000);
    var dayLabel;
    if (diff === 0) dayLabel = 'Сегодня';
    else if (diff === 1) dayLabel = 'Завтра';
    else dayLabel = dt.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' });
    var timeLabel = dt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    return dayLabel + ' · ' + timeLabel;
  }

  function seatsText(v) {
    var n = Math.abs(v) % 100;
    var n1 = n % 10;
    if (n > 10 && n < 20) return v + ' мест';
    if (n1 === 1) return v + ' место';
    if (n1 >= 2 && n1 <= 4) return v + ' места';
    return v + ' мест';
  }

  function renderFilterCounts(rows) {
    var counts = { all: rows.length, recruiting: 0, active: 0, archived: 0 };
    rows.forEach(function (g) {
      if (counts[g.status] != null) counts[g.status] += 1;
    });
    Object.keys(counts).forEach(function (k) {
      var node = document.querySelector('#filterChips .tg-chip-cnt[data-count="' + k + '"]');
      if (node) node.textContent = String(counts[k]);
    });
  }

  function renderStats(rowsBySearch, rowsVisible) {
    var lead = document.getElementById('groupsLead');
    var q = normalizeText(state.search);
    if (!lead) return;
    var activeHints = [];
    if (state.filter !== 'all') activeHints.push('фильтр «' + (FILTER_LABELS[state.filter] || state.filter) + '»');
    if (state.onlyFreeSeats) activeHints.push('только со свободными местами');
    if (state.sort !== 'next') activeHints.push('сортировка «' + (SORT_LABELS[state.sort] || state.sort) + '»');
    if (q) {
      var searchLead = 'Найдено ' + rowsBySearch.length + ' групп по запросу «' + state.search.trim() + '».';
      if (activeHints.length) searchLead += ' Активно: ' + activeHints.join(', ') + '.';
      lead.textContent = searchLead;
      return;
    }
    if (activeHints.length) {
      lead.textContent = 'Показано ' + rowsVisible.length + ' групп. Активно: ' + activeHints.join(', ') + '.';
      return;
    }
    lead.textContent = 'Создавайте группы, открывайте набор и управляйте расписанием без лишних действий.';
  }

  function renderListSkeleton() {
    var sk = 'ma-skel-shimmer';
    function oneCard() {
      return (
        '<article class="group-card-tg group-card-skeleton" data-status="draft" aria-hidden="true">' +
          '<div class="group-card-tg__top">' +
            '<div class="tg-group-skel-title ' + sk + '"></div>' +
            '<div class="group-card-tg__top-end">' +
              '<span class="tg-group-skel-pill ' + sk + '"></span>' +
              '<span class="tg-group-skel-open ' + sk + '"></span>' +
            '</div>' +
          '</div>' +
          '<div class="group-card-tg__meta tg-group-skel-meta-row">' +
            '<span class="tg-group-skel-meta-ico ' + sk + '"></span>' +
            '<div class="tg-group-skel-meta-line ' + sk + '"></div>' +
          '</div>' +
          '<div class="group-card-tg__chips tg-group-skel-chips">' +
            '<span class="tg-group-skel-chip ' + sk + '"></span>' +
            '<span class="tg-group-skel-chip ' + sk + '"></span>' +
          '</div>' +
          '<div class="group-card-tg__bottom">' +
            '<div class="group-card-tg__next-block">' +
              '<div class="group-card-tg__next-label"><span class="tg-group-skel-label ' + sk + '"></span></div>' +
              '<div class="group-card-tg__next tg-group-skel-next ' + sk + '"></div>' +
            '</div>' +
            '<div class="group-card-tg__cap-block">' +
              '<div class="group-card-tg__cap-text tg-group-skel-cap ' + sk + '"></div>' +
              '<div class="group-card-tg__cap-hint tg-group-skel-hint ' + sk + '"></div>' +
              '<div class="group-card-tg__meter"><span class="tg-group-skel-meter ' + sk + '" style="width:58%"></span></div>' +
            '</div>' +
          '</div>' +
        '</article>'
      );
    }
    var parts = ['<div class="tg-groups-skel" role="status" aria-busy="true" aria-label="Загрузка групп">'];
    for (var i = 0; i < 5; i++) parts.push(oneCard());
    parts.push('</div>');
    return parts.join('');
  }

  function renderList() {
    var box = document.getElementById('groupList');
    if (state.groupsListLoading) {
      box.innerHTML = renderListSkeleton();
      return;
    }
    // First apply search, then status filter so chip counters match search scope.
    var rowsBySearch = state.groups.filter(groupMatchesSearch);
    var rows = rowsBySearch.filter(groupMatchesFilter).filter(groupMatchesOnlyFreeSeats);
    rows = sortRows(rows);
    updateSearchClearVisibility();
    syncListControls();
    renderFilterCounts(rowsBySearch);
    renderStats(rowsBySearch, rows);
    if (!rows.length) {
      var q = normalizeText(state.search);
      var emptyTitle = 'В этом разделе пока нет групп';
      var emptyHint = 'Попробуйте другой фильтр или нажмите «Новая группа» — правила серии появятся в календаре автоматически.';
      if (q) {
        emptyTitle = 'По вашему запросу ничего не найдено';
        emptyHint = 'Уточните запрос или очистите поиск. Можно искать по названию, услуге и площадке.';
      } else if (state.filter !== 'all') {
        emptyTitle = 'Нет групп в статусе «' + (FILTER_LABELS[state.filter] || state.filter) + '»';
      } else if (state.onlyFreeSeats) {
        emptyTitle = 'Свободных мест сейчас нет';
        emptyHint = 'Снимите ограничение или обновите список позже — новые места появятся после изменений в группах.';
      }
      var showReset = hasActiveListRefinement();
      box.innerHTML =
        '<div class="tg-empty-state">' +
          '<div class="tg-empty-state__visual" aria-hidden="true">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>' +
              '<path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>' +
            '</svg>' +
          '</div>' +
          '<p class="tg-empty-state__title">' + esc(emptyTitle) + '</p>' +
          '<p class="tg-empty-state__hint">' + esc(emptyHint) + '</p>' +
          (showReset ? '<button type="button" class="btn-secondary btn-block tg-empty-state__action" id="btnResetFromEmpty">Сбросить ограничения</button>' : '') +
        '</div>';
      var btnResetFromEmpty = document.getElementById('btnResetFromEmpty');
      if (btnResetFromEmpty) {
        btnResetFromEmpty.addEventListener('click', function () {
          resetListRefinements({ focusSearch: true });
        });
      }
      return;
    }
    box.innerHTML = rows.map(function (g) {
      var nextStr = formatNextSession(g.next_session_at);
      var cap = groupCapacity(g);
      var occ = groupOccupancy(g);
      var pct = Math.min(100, Math.round((occ / cap) * 100));
      var st = g.status || '';
      var statusLabel = STATUS_RU[st] || st || '—';
      var pillClass = statusPillClass(st);
      var meterClass = pct >= 100 ? 'is-full' : (pct >= 80 ? 'is-high' : '');
      var freeSeats = groupFreeSeats(g);
      var seatsHint = freeSeats ? ('ещё ' + seatsText(freeSeats)) : 'мест нет';
      var chips = [];
      if (g.catalog_visible) {
        chips.push('<span class="group-chip group-chip--catalog">В каталоге</span>');
      }
      if (g.season_start_date) {
        chips.push('<span class="group-chip group-chip--season">Старт ' + esc(formatSeasonDate(g.season_start_date)) + '</span>');
      }
      var chipsHtml = chips.length ? ('<div class="group-card-tg__chips">' + chips.join('') + '</div>') : '';
      return (
        '<article class="group-card-tg" data-id="' + g.id + '" data-status="' + esc(st || 'draft') + '" role="button" tabindex="0">' +
          '<div class="group-card-tg__top">' +
            '<h2 class="group-card-tg__name">' + esc(g.name) + '</h2>' +
            '<div class="group-card-tg__top-end">' +
              '<span class="tg-status-pill ' + pillClass + '">' + esc(statusLabel) + '</span>' +
              '<span class="group-card-tg__open" aria-hidden="true">' +
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"></path></svg>' +
              '</span>' +
            '</div>' +
          '</div>' +
          '<div class="group-card-tg__meta">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>' +
            esc(g.service_name || '—') + ' · ' + esc(g.arena_name || '—') +
          '</div>' +
          chipsHtml +
          '<div class="group-card-tg__bottom">' +
            '<div class="group-card-tg__next-block">' +
              '<div class="group-card-tg__next-label">Ближайшее занятие</div>' +
              '<div class="group-card-tg__next">' + esc(nextStr) + '</div>' +
            '</div>' +
            '<div class="group-card-tg__cap-block">' +
              '<div class="group-card-tg__cap-text">' + occ + ' <span>/ ' + cap + '</span></div>' +
              '<div class="group-card-tg__cap-hint">' + esc(seatsHint) + '</div>' +
              '<div class="group-card-tg__meter" aria-hidden="true"><span class="' + meterClass + '" style="width:' + pct + '%"></span></div>' +
            '</div>' +
          '</div>' +
        '</article>'
      );
    }).join('');
    Array.prototype.forEach.call(box.querySelectorAll('.group-card-tg'), function (el) {
      function go() {
        var id = parseInt(el.getAttribute('data-id'), 10);
        openDetail(id);
      }
      el.addEventListener('click', go);
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
      });
    });
  }

  function loadMetaForCreate() {
    return fetchJson(apiUrlWithQuery('/trainer/my-services')).then(function (data) {
      var services = data.services || [];
      var arenas = data.arenas || [];
      var sSel = document.getElementById('fService');
      var aSel = document.getElementById('fArena');
      sSel.innerHTML = services.map(function (s) {
        return '<option value="' + s.id + '">' + esc(s.name || ('Услуга ' + s.id)) + '</option>';
      }).join('');
      aSel.innerHTML = arenas.length
        ? arenas
            .map(function (a) {
              return '<option value="' + a.id + '">' + esc(a.name || ('Площадка ' + a.id)) + '</option>';
            })
            .join('')
        : '<option value="">' + esc('Добавьте площадку в профиле тренера') + '</option>';
    });
  }

  function renderWeekdayPick() {
    var row = document.getElementById('weekdayPick');
    row.innerHTML = DAYS.map(function (d) {
      var isOn = state.selectedWeekdays.indexOf(d.v) >= 0;
      return '<button type="button" class="wd' + (isOn ? ' on' : '') + '" data-d="' + d.v + '" aria-pressed="' + (isOn ? 'true' : 'false') + '">' + esc(d.l) + '</button>';
    }).join('');
    Array.prototype.forEach.call(row.querySelectorAll('.wd'), function (el) {
      el.addEventListener('click', function () {
        var v = parseInt(el.getAttribute('data-d'), 10);
        var ix = state.selectedWeekdays.indexOf(v);
        if (ix >= 0) state.selectedWeekdays.splice(ix, 1);
        else state.selectedWeekdays.push(v);
        state.selectedWeekdays.sort(function (a, b) { return a - b; });
        renderWeekdayPick();
      });
    });
  }

  function pad2(n) {
    var x = typeof n === 'string' ? parseInt(n, 10) : n;
    if (isNaN(x)) return '00';
    return x < 10 ? '0' + x : String(x);
  }

  function todayYmdLocal() {
    var t = new Date();
    return t.getFullYear() + '-' + pad2(t.getMonth() + 1) + '-' + pad2(t.getDate());
  }

  function addDaysYmd(ymd, days) {
    if (!ymd || ymd.length < 10) return '';
    var p = ymd.split('-');
    var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
    d.setDate(d.getDate() + days);
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }

  function setSeasonDateMin() {
    var el = document.getElementById('fSeason');
    if (!el) return;
    el.min = todayYmdLocal();
  }

  function getGroupStartTimeHHMM() {
    var hEl = document.getElementById('fStartHour');
    var mEl = document.getElementById('fStartMin');
    var h = hEl ? parseInt(hEl.value, 10) : 18;
    var m = mEl ? parseInt(mEl.value, 10) : 0;
    if (isNaN(h) || h < 0 || h > 23) h = 18;
    if (isNaN(m) || m < 0 || m > 59) m = 0;
    return pad2(h) + ':' + pad2(m);
  }

  function initGroupCreateTimePickers() {
    var hEl = document.getElementById('fStartHour');
    var mEl = document.getElementById('fStartMin');
    if (!hEl || !mEl || hEl.options.length) return;
    var hOpts = '';
    for (var h = 0; h < 24; h++) {
      hOpts += '<option value="' + h + '">' + pad2(h) + '</option>';
    }
    hEl.innerHTML = hOpts;
    var mOpts = '';
    for (var mm = 0; mm < 60; mm += 5) {
      mOpts += '<option value="' + mm + '">' + pad2(mm) + '</option>';
    }
    mEl.innerHTML = mOpts;
  }

  function renderEditWeekdayPick() {
    var row = document.getElementById('editWeekdayPick');
    if (!row) return;
    row.innerHTML = DAYS.map(function (d) {
      var isOn = state.editWeekdays.indexOf(d.v) >= 0;
      return '<button type="button" class="wd' + (isOn ? ' on' : '') + '" data-d="' + d.v + '" aria-pressed="' + (isOn ? 'true' : 'false') + '">' + esc(d.l) + '</button>';
    }).join('');
    Array.prototype.forEach.call(row.querySelectorAll('.wd'), function (el) {
      el.addEventListener('click', function () {
        var v = parseInt(el.getAttribute('data-d'), 10);
        var ix = state.editWeekdays.indexOf(v);
        if (ix >= 0) state.editWeekdays.splice(ix, 1);
        else state.editWeekdays.push(v);
        state.editWeekdays.sort(function (a, b) { return a - b; });
        renderEditWeekdayPick();
      });
    });
  }

  function setEditSeasonDateMin() {
    var el = document.getElementById('editFSeason');
    if (!el) return;
    el.min = todayYmdLocal();
  }

  function getEditGroupStartTimeHHMM() {
    var hEl = document.getElementById('editFStartHour');
    var mEl = document.getElementById('editFStartMin');
    var h = hEl ? parseInt(hEl.value, 10) : 18;
    var m = mEl ? parseInt(mEl.value, 10) : 0;
    if (isNaN(h) || h < 0 || h > 23) h = 18;
    if (isNaN(m) || m < 0 || m > 59) m = 0;
    return pad2(h) + ':' + pad2(m);
  }

  function initEditScheduleTimePickers() {
    var hEl = document.getElementById('editFStartHour');
    var mEl = document.getElementById('editFStartMin');
    if (!hEl || !mEl) return;
    if (!hEl.options.length) {
      var hOpts = '';
      for (var h = 0; h < 24; h++) {
        hOpts += '<option value="' + h + '">' + pad2(h) + '</option>';
      }
      hEl.innerHTML = hOpts;
      var mOpts = '';
      for (var mm = 0; mm < 60; mm += 5) {
        mOpts += '<option value="' + mm + '">' + pad2(mm) + '</option>';
      }
      mEl.innerHTML = mOpts;
    }
  }

  function openEditScheduleModal(d) {
    state.editScheduleGroupId = d.id;
    state.editScheduleOriginalSeason = d.season_start_date ? String(d.season_start_date).slice(0, 10) : '';
    var rules = (d.schedule_rules || []).slice();
    var wds = [];
    rules.forEach(function (r) {
      var dw = Number(r.day_of_week);
      if (isFinite(dw)) wds.push(dw + 1);
    });
    state.editWeekdays = wds.filter(function (x, i, a) { return a.indexOf(x) === i; }).sort(function (a, b) { return a - b; });
    if (!state.editWeekdays.length) state.editWeekdays = [2, 4];
    var first = rules[0] || {};
    var t = ((first.start_time || '18:00') + '').slice(0, 5).split(':');
    var h = parseInt(t[0], 10);
    var m = parseInt(t[1], 10) || 0;
    if (isNaN(h)) h = 18;
    if (isNaN(m)) m = 0;
    m = Math.round(m / 5) * 5;
    if (m > 55) m = 55;
    initEditScheduleTimePickers();
    document.getElementById('editFStartHour').value = String(h);
    document.getElementById('editFStartMin').value = String(m);
    document.getElementById('editFDur').value = String(first.duration_minutes || 60);
    var es = document.getElementById('editFSeason');
    if (es) es.value = state.editScheduleOriginalSeason;
    setEditSeasonDateMin();
    renderEditWeekdayPick();
    var errEl = document.getElementById('editScheduleError');
    if (errEl) errEl.style.display = 'none';
    var modal = document.getElementById('modalEditSchedule');
    if (modal) {
      modal.style.display = 'flex';
      modal.setAttribute('aria-hidden', 'false');
    }
  }

  function closeEditScheduleModal() {
    state.editScheduleGroupId = null;
    var m = document.getElementById('modalEditSchedule');
    if (m) {
      m.style.display = 'none';
      m.setAttribute('aria-hidden', 'true');
    }
  }

  function submitEditSchedule() {
    var gid = state.editScheduleGroupId;
    var err = document.getElementById('editScheduleError');
    if (err) err.style.display = 'none';
    if (!gid) return;
    if (!state.editWeekdays.length) {
      if (err) {
        err.textContent = 'Выберите хотя бы один день недели';
        err.style.display = 'block';
      }
      return;
    }
    var timeStr = getEditGroupStartTimeHHMM();
    if (timeStr.length === 5) timeStr = timeStr + ':00';
    var schedule_rules = state.editWeekdays.map(function (ud) {
      return {
        day_of_week: ud - 1,
        start_time: timeStr.slice(0, 5),
        duration_minutes: parseInt(document.getElementById('editFDur').value, 10) || 60
      };
    });
    var body = { schedule_rules: schedule_rules };
    var seasonEl = document.getElementById('editFSeason');
    var newSeason = seasonEl ? seasonEl.value : '';
    if (newSeason !== state.editScheduleOriginalSeason) {
      body.season_start_date = newSeason || '';
    }
    var btn = document.getElementById('btnSubmitEditSchedule');
    if (btn) btn.disabled = true;
    fetchJson(apiUrlWithQuery('/trainer/training-groups/' + gid + '/schedule-rules'), {
      method: 'PUT',
      body: JSON.stringify(body)
    })
      .then(function () {
        closeEditScheduleModal();
        openDetail(gid);
      })
      .catch(function (e) {
        if (err) {
          err.textContent = e.message || String(e);
          err.style.display = 'block';
        }
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  }

  function openCreate() {
    document.getElementById('createError').style.display = 'none';
    document.getElementById('fName').value = '';
    document.getElementById('fMax').value = '8';
    document.getElementById('fStartHour').value = '18';
    document.getElementById('fStartMin').value = '0';
    document.getElementById('fDur').value = '45';
    document.getElementById('fSeason').value = '';
    setSeasonDateMin();
    document.getElementById('fCatalog').checked = true;
    document.getElementById('fCatText').value = '';
    state.selectedWeekdays = [2, 4];
    renderWeekdayPick();
    loadMetaForCreate().then(function () {
      showScreen('create');
    });
  }

  function submitCreate() {
    var err = document.getElementById('createError');
    err.style.display = 'none';
    var name = document.getElementById('fName').value.trim();
    if (!name) {
      err.textContent = 'Укажите название';
      err.style.display = 'block';
      return;
    }
    if (!state.selectedWeekdays.length) {
      err.textContent = 'Выберите хотя бы один день недели';
      err.style.display = 'block';
      return;
    }
    var arenaEl = document.getElementById('fArena');
    var arenaId = arenaEl && arenaEl.value ? parseInt(arenaEl.value, 10) : null;
    var timeStr = getGroupStartTimeHHMM();
    if (timeStr.length === 5) timeStr = timeStr + ':00';
    var schedule_rules = state.selectedWeekdays.map(function (ud) {
      return {
        day_of_week: ud - 1,
        start_time: timeStr.length >= 5 ? timeStr.slice(0, 5) : timeStr,
        duration_minutes: parseInt(document.getElementById('fDur').value, 10) || 60
      };
    });
    var body = {
      name: name,
      service_id: parseInt(document.getElementById('fService').value, 10),
      arena_id: arenaId,
      max_members: parseInt(document.getElementById('fMax').value, 10) || 8,
      status: 'recruiting',
      catalog_visible: document.getElementById('fCatalog').checked,
      catalog_pitch: document.getElementById('fCatText').value.trim() || null,
      season_start_date: document.getElementById('fSeason').value || null,
      schedule_rules: schedule_rules
    };
    var btn = document.getElementById('btnSubmitCreate');
    btn.disabled = true;
    fetchJson(apiUrlWithQuery('/trainer/training-groups'), { method: 'POST', body: JSON.stringify(body) })
      .then(function () {
        showScreen('list');
        return loadList().then(function () {
          showTrainerGroupsToast('Группа «' + name + '» создана');
        });
      })
      .catch(function (e) {
        err.textContent = e.message || String(e);
        err.style.display = 'block';
      })
      .finally(function () { btn.disabled = false; });
  }

  function openDetail(id) {
    state.detailId = id;
    closeSlotActionsModal();
    var box = document.getElementById('detailBody');
    box.innerHTML =
      '<div class="bd-hero" style="opacity:0.6;animation:pulse 1.5s infinite ease-in-out">' +
        '<div class="bd-hero-inner">' +
          '<div style="width:60px;height:12px;background:rgba(128,128,128,0.2);border-radius:4px;margin-bottom:12px"></div>' +
          '<div style="width:140px;height:28px;background:rgba(128,128,128,0.2);border-radius:6px;margin-bottom:12px"></div>' +
          '<div style="width:100px;height:14px;background:rgba(128,128,128,0.2);border-radius:4px"></div>' +
        '</div>' +
      '</div>';
    showScreen('detail');
    Promise.all([
      fetchJson(apiUrlWithQuery('/trainer/training-groups/' + id)),
      fetchJson(apiUrlWithQuery('/trainer/training-groups/' + id + '/upcoming-slots?limit=3')).catch(function () {
        return { slots: [] };
      })
    ])
      .then(function (parts) {
        var d = parts[0];
        var upcomingSlots = (parts[1] && parts[1].slots) ? parts[1].slots : [];
        document.getElementById('detailTitle').textContent = d.name || 'Группа';
        var nextShort = formatNextSession(d.next_session_at);
        var scheduleRules = Array.isArray(d.schedule_rules) ? d.schedule_rules.slice() : [];
        scheduleRules.sort(function (a, b) {
          var dayA = Number(a && a.day_of_week);
          var dayB = Number(b && b.day_of_week);
          if (isFinite(dayA) && isFinite(dayB) && dayA !== dayB) return dayA - dayB;
          var timeA = ((a && a.start_time) || '').slice(0, 5);
          var timeB = ((b && b.start_time) || '').slice(0, 5);
          return timeA.localeCompare(timeB);
        });
        function scheduleSeriesSummary(rules) {
          if (!rules || !rules.length) return 'Не задано';
          var seen = {};
          var days = [];
          for (var ri = 0; ri < rules.length; ri++) {
            var dayIdx = Number(rules[ri].day_of_week);
            var lbl = DOW_SHORT[dayIdx] || String(dayIdx);
            if (!seen[lbl]) {
              seen[lbl] = true;
              days.push(lbl);
            }
          }
          var firstSig = null;
          var uniform = true;
          for (var u = 0; u < rules.length; u++) {
            var tmU = ((rules[u].start_time || '') + '').slice(0, 5) || '—';
            var durU = Number(rules[u].duration_minutes);
            if (!isFinite(durU) || durU <= 0) durU = 45;
            var sig = tmU + '|' + durU;
            if (u === 0) firstSig = sig;
            else if (sig !== firstSig) uniform = false;
          }
          var first = rules[0];
          var tm = ((first.start_time || '') + '').slice(0, 5) || '—';
          var duration = Number(first.duration_minutes);
          if (!isFinite(duration) || duration <= 0) duration = 45;
          if (uniform) {
            return days.join(', ') + ' · ' + tm + ' · ' + duration + ' мин';
          }
          var line = [];
          for (var j = 0; j < rules.length; j++) {
            var r = rules[j];
            var dix = Number(r.day_of_week);
            var lb = DOW_SHORT[dix] || String(dix);
            var tj = ((r.start_time || '') + '').slice(0, 5) || '—';
            var dj = Number(r.duration_minutes);
            if (!isFinite(dj) || dj <= 0) dj = 45;
            line.push(lb + ' ' + tj + ' (' + dj + ' мин)');
          }
          return line.join(', ');
        }
        var seriesLine = scheduleSeriesSummary(scheduleRules);
        var members = (d.members || []).filter(function (m) { return m.status === 'active' || m.status === 'trial'; });
        var cap = groupCapacity(d);
        var occ = members.length;
        var freeSeats = Math.max(0, cap - occ);
        var pct = Math.max(0, Math.min(100, Math.round((occ / cap) * 100)));
        var meterClass = pct >= 100 ? 'is-full' : (pct >= 80 ? 'is-high' : '');
        var seatsHint = freeSeats > 0 ? ('Свободно ' + seatsText(freeSeats)) : 'Группа заполнена';
        var spotsLeft = typeof d.spots_left === 'number' ? d.spots_left : null;
        state.groupMemberIds = members.map(function (m) { return m.client_id; });
        state.groupSpotsLeft = spotsLeft;
        state.groupRosterFull = occ >= cap;
        function clientName(m) {
          var a = [m.first_name, m.last_name].filter(Boolean).join(' ').trim();
          return a || ('Клиент #' + m.client_id);
        }
        function bookingInitials(displayName) {
          var s = (displayName || '').trim();
          if (!s) return '?';
          var parts = s.split(/\s+/).filter(Boolean);
          if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
          if (parts[0].length >= 2) return parts[0].slice(0, 2).toUpperCase();
          return parts[0][0].toUpperCase();
        }
        var st = d.status || '';
        var statusLabel = STATUS_RU[st] || st || '—';
        var pillClass = statusPillClass(st);
        var headerChips =
          '<div class="tg-detail-head-meta">' +
            '<span class="tg-status-pill ' + pillClass + '">' + esc(statusLabel) + '</span>' +
            (d.catalog_visible ? '<span class="group-chip group-chip--catalog">В каталоге</span>' : '') +
            (d.season_start_date ? '<span class="group-chip group-chip--season">Старт ' + esc(formatSeasonDate(d.season_start_date)) + '</span>' : '') +
          '</div>';
        var membersHintShort = d.catalog_visible
          ? 'Заявки из каталога зачисляются автоматически.'
          : 'Участников добавляете вручную.';
        var scheduleEditBtn =
          d.status !== 'archived'
            ? '<button type="button" class="tg-text-link" id="btnOpenEditSchedule">Изменить</button>'
            : '';
        var upcomingHtml = '';
        if (upcomingSlots.length) {
          upcomingHtml =
            '<div class="tg-upcoming-compact">' +
            '<p class="bd-section-label">Ближайшие в календаре</p>' +
            '<p class="tg-upcoming-section-hint">До 3 ближайших слотов</p>' +
            '<div class="bd-rows tg-upcoming-rows">' +
            upcomingSlots.map(function (s) {
              var st = (s.start_time || '').slice(0, 8);
              var iso = s.slot_date + 'T' + (st.length <= 5 ? st + ':00' : st);
              var pretty = new Date(iso).toLocaleString('ru-RU', {
                weekday: 'short',
                day: '2-digit',
                month: 'short',
                hour: '2-digit',
                minute: '2-digit'
              });
              var nb = Number(s.active_bookings) || 0;
              var slotCap = Math.max(1, Number(s.capacity) || 1);
              var canCancel = d.status !== 'archived' && (s.status === 'available') && nb === 0;
              var occupancy = nb + '/' + slotCap;
              var stLabel = (s.status === 'available')
                ? (nb > 0 ? ('Записей: ' + occupancy) : ('Свободно · ' + occupancy))
                : ('Статус: ' + String(s.status || '—') + ' · ' + occupancy);
              var occupancyClass = 'tg-slot-pill ';
              if (nb >= slotCap) occupancyClass += 'tg-slot-pill--full';
              else if (nb > 0) occupancyClass += 'tg-slot-pill--busy';
              else occupancyClass += 'tg-slot-pill--free';
              var slotMenuBtn =
                d.status !== 'archived'
                  ? '<button type="button" class="tg-slot-menu" data-slot-id="' + s.id + '" data-slot-label="' + esc(pretty) + '" data-slot-occupancy="' + esc('Записей: ' + occupancy) + '" data-slot-status="' + esc(String(s.status || '—')) + '" data-slot-can-cancel="' + (canCancel ? '1' : '0') + '" aria-label="Действия со слотом">...</button>'
                  : '';
              return (
                '<div class="bd-row tg-upcoming-row">' +
                  '<div class="bd-row-text">' +
                    '<div class="bd-client-name">' + esc(pretty) + '</div>' +
                    '<div class="bd-row-label">' + esc(stLabel) + '</div>' +
                  '</div>' +
                  '<div class="tg-upcoming-row__actions">' +
                    '<span class="' + occupancyClass + '">' + esc(occupancy) + '</span>' +
                    slotMenuBtn +
                  '</div>' +
                '</div>'
              );
            }).join('') +
            '</div></div>';
        } else if (d.status !== 'archived') {
          upcomingHtml =
            '<div class="tg-upcoming-compact">' +
            '<p class="bd-section-label">Ближайшие в календаре</p>' +
            '<div class="bd-rows"><div class="bd-row">' +
              '<div class="bd-row-text"><div class="bd-row-value" style="color:var(--tg-theme-hint-color)">Пока без слотов в календаре</div></div>' +
            '</div></div></div>';
        }
        var catalogPanel = '';
        if (d.status !== 'archived') {
          catalogPanel =
            '<div class="tg-detail-panel tg-detail-panel--open">' +
              '<p class="bd-section-label">Каталог для клиентов</p>' +
              '<div class="tg-detail-panel__body">' +
                '<label class="tg-catalog-toggle">' +
                  '<input type="checkbox" id="tgCatalogVisible" ' + (d.catalog_visible ? 'checked' : '') + ' /> ' +
                  'Показывать в общем каталоге (поиск по городу и услуге)' +
                '</label>' +
                '<p class="tg-detail-panel__hint">Клиенты смогут сами находить вашу группу и записываться.</p>' +
                '<label class="tg-catalog-pitch-label" for="tgCatalogPitch">Текст для каталога</label>' +
                '<textarea id="tgCatalogPitch" class="tg-catalog-pitch-input" maxlength="2000" rows="4" placeholder="Кратко для клиентов — формат, уровень, что входит">' +
                  esc(d.catalog_pitch || '') +
                '</textarea>' +
                '<button type="button" class="bd-btn bd-btn--secondary tg-catalog-pitch-save" id="btnSaveCatalogPitch">Сохранить описание</button>' +
              '</div>' +
            '</div>';
        }
        var managePanel = '';
        if (d.status !== 'archived') {
          managePanel =
            '<details class="tg-detail-panel">' +
              '<summary>Управление группой</summary>' +
              '<div class="tg-detail-panel__body">' +
                '<p class="tg-detail-panel__hint">Пауза и архив — редкие действия. Рассылки и другие инструменты появятся здесь.</p>' +
                '<button type="button" class="bd-btn bd-btn--secondary" id="btnPause">' + (d.status === 'paused' ? 'Возобновить' : 'Пауза') + '</button>' +
                '<button type="button" class="bd-btn bd-btn--outline-danger" id="btnArchive">В архив</button>' +
                '<button type="button" class="bd-btn bd-btn--surface" disabled title="В разработке">Уведомление участникам</button>' +
              '</div>' +
            '</details>';
        }
        var addMemberCta =
          d.status !== 'archived'
            ? '<div class="tg-detail-cta"><button type="button" class="bd-btn bd-btn--primary" id="btnOpenAddMember">+ Добавить участника</button></div>'
            : '';
        box.innerHTML =
          '<div class="tg-group-detail booking-detail">' +
            '<div class="bd-hero">' +
              '<div class="bd-hero-inner">' +
                headerChips +
                '<div class="bd-hero-kicker">Ближайшее занятие</div>' +
                '<div class="bd-hero-time">' + esc(nextShort) + '</div>' +
                '<div class="bd-hero-date">' + esc((d.service_name || '—') + ' · ' + (d.arena_name || '—')) + '</div>' +
              '</div>' +
            '</div>' +
            '<div class="tg-detail-roster">' +
              '<div class="tg-detail-roster__top">' +
                '<span class="tg-detail-roster__title">Состав</span>' +
                '<div class="tg-detail-roster__top-right">' +
                  '<span class="tg-detail-roster__nums">' + occ + ' / ' + cap + '</span>' +
                '</div>' +
              '</div>' +
              '<div class="group-card-tg__meter" aria-hidden="true"><span class="' + meterClass + '" style="width:' + pct + '%"></span></div>' +
              '<div class="tg-detail-roster__hint">' + esc(seatsHint) + '</div>' +
            '</div>' +
            '<div class="tg-detail-schedule-strip">' +
              '<div>' +
                '<span class="tg-detail-schedule-strip__label">Серия</span>' +
                '<div class="tg-detail-schedule-strip__value tg-detail-schedule-strip__value--with-icon">' + IC.session + '<span>' + esc(seriesLine) + '</span></div>' +
              '</div>' +
              scheduleEditBtn +
            '</div>' +
            upcomingHtml +
            addMemberCta +
            catalogPanel +
            '<p class="bd-section-label">Участники</p>' +
            '<p class="tg-members-note">' + esc(membersHintShort) + '</p>' +
            '<div class="bd-rows">' +
              members.map(function (m) {
                var cName = clientName(m);
                var initials = bookingInitials(cName);
                var profileHref = esc(trainerClientProfileUrl(m.client_id, id));
                var memberChevron =
                  '<svg class="tg-member-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>';
                var removeBtn =
                  d.status !== 'archived'
                    ? '<button type="button" class="bd-btn bd-btn--outline-danger tg-member-remove" data-client-id="' + m.client_id + '">Убрать</button>'
                    : '';
                return (
                  '<div class="bd-row bd-client tg-member-row">' +
                    '<a class="tg-member-profile-hit" href="' + profileHref + '" aria-label="Карточка клиента: ' + esc(cName) + '">' +
                      '<div class="bd-avatar">' + esc(initials) + '</div>' +
                      '<div class="bd-row-text">' +
                        '<div class="bd-client-name">' + esc(cName) + '</div>' +
                        '<div class="bd-row-label tg-member-state' + (m.status === 'trial' ? ' is-trial' : '') + '">' + esc(m.status === 'trial' ? 'Пробное занятие' : 'В составе группы') + '</div>' +
                      '</div>' +
                      memberChevron +
                    '</a>' +
                    removeBtn +
                  '</div>'
                );
              }).join('') +
              (members.length ? '' : '<div class="bd-row"><div class="bd-row-text"><div class="bd-row-value" style="color:var(--tg-theme-hint-color)">Пока никого</div></div></div>') +
            '</div>' +
            managePanel +
          '</div>';
        var catVis = document.getElementById('tgCatalogVisible');
        if (catVis) {
          catVis.addEventListener('change', function () {
            var checked = catVis.checked;
            catVis.disabled = true;
            fetchJson(apiUrlWithQuery('/trainer/training-groups/' + id), {
              method: 'PATCH',
              body: JSON.stringify({ catalog_visible: checked })
            })
              .then(function () {
                openDetail(id);
              })
              .catch(function (e) {
                catVis.checked = !checked;
                alert(e.message || String(e));
              })
              .finally(function () {
                catVis.disabled = false;
              });
          });
        }
        var btnSavePitch = document.getElementById('btnSaveCatalogPitch');
        var taPitch = document.getElementById('tgCatalogPitch');
        if (btnSavePitch && taPitch) {
          btnSavePitch.addEventListener('click', function () {
            var raw = taPitch.value.trim();
            btnSavePitch.disabled = true;
            fetchJson(apiUrlWithQuery('/trainer/training-groups/' + id), {
              method: 'PATCH',
              body: JSON.stringify({ catalog_pitch: raw ? raw : null })
            })
              .then(function () {
                openDetail(id);
              })
              .catch(function (e) {
                alert(e.message || String(e));
              })
              .finally(function () {
                btnSavePitch.disabled = false;
              });
          });
        }
        var btnPause = document.getElementById('btnPause');
        if (btnPause) {
          btnPause.addEventListener('click', function () {
            var nextStatus;
            if (d.status === 'paused') {
              // Must not always send 'active': that wrongly ends recruitment before season start.
              nextStatus = 'active';
              if (d.season_start_date) {
                var p = String(d.season_start_date).split('-');
                if (p.length >= 3) {
                  var sd = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
                  var today = new Date();
                  today.setHours(0, 0, 0, 0);
                  sd.setHours(0, 0, 0, 0);
                  if (sd > today) nextStatus = 'recruiting';
                }
              }
            } else {
              nextStatus = 'paused';
            }
            fetchJson(apiUrlWithQuery('/trainer/training-groups/' + id), {
              method: 'PATCH',
              body: JSON.stringify({ status: nextStatus })
            }).then(function () { openDetail(id); });
          });
        }
        var btnArch = document.getElementById('btnArchive');
        if (btnArch) {
          btnArch.addEventListener('click', function () {
            if (!confirm('Завершить сезон и отменить будущие занятия?')) return;
            fetchJson(apiUrlWithQuery('/trainer/training-groups/' + id), {
              method: 'PATCH',
              body: JSON.stringify({ status: 'archived' })
            }).then(function () { openDetail(id); });
          });
        }
        var btnAdd = document.getElementById('btnOpenAddMember');
        if (btnAdd) {
          btnAdd.addEventListener('click', function () {
            openAddMemberModal(id);
          });
        }
        Array.prototype.forEach.call(box.querySelectorAll('.tg-slot-menu'), function (b) {
          b.addEventListener('click', function () {
            var sid = parseInt(b.getAttribute('data-slot-id'), 10);
            if (!sid) return;
            var rawStatus = String(b.getAttribute('data-slot-status') || '').toLowerCase();
            var statusLabel = 'Слот доступен';
            if (rawStatus === 'booked') statusLabel = 'Слот заполнен';
            else if (rawStatus && rawStatus !== 'available') statusLabel = 'Статус: ' + rawStatus;
            openSlotActionsModal(id, {
              slotId: sid,
              serviceId: d.service_id,
              canCancel: b.getAttribute('data-slot-can-cancel') === '1',
              label: b.getAttribute('data-slot-label') || '',
              occupancy: b.getAttribute('data-slot-occupancy') || '',
              statusLabel: statusLabel
            });
          });
        });
        Array.prototype.forEach.call(box.querySelectorAll('.tg-member-remove'), function (b) {
          b.addEventListener('click', function () {
            var cid = parseInt(b.getAttribute('data-client-id'), 10);
            if (!cid || !confirm('Убрать этого участника из группы?')) return;
            fetchJson(apiUrlWithQuery('/trainer/training-groups/' + id + '/members/' + cid), { method: 'DELETE' })
              .then(function () { openDetail(id); })
              .catch(function (e) { alert(e.message || String(e)); });
          });
        });
        var btnEdit = document.getElementById('btnOpenEditSchedule');
        if (btnEdit) {
          btnEdit.addEventListener('click', function () {
            openEditScheduleModal(d);
          });
        }
      })
      .catch(function (e) {
        box.innerHTML = '<div class="list-err" style="display:block">' + esc(e.message || String(e)) + '</div>';
      });
  }

  document.getElementById('filterChips').addEventListener('click', function (ev) {
    var t = ev.target;
    while (t && t !== ev.currentTarget && (!t.getAttribute || t.getAttribute('data-filter') == null)) {
      t = t.parentNode;
    }
    if (!t || !t.getAttribute || t.getAttribute('data-filter') == null) return;
    state.filter = t.getAttribute('data-filter');
    saveListUiState();
    renderList();
  });

  var sortSelect = document.getElementById('sortSelect');
  if (sortSelect) {
    sortSelect.value = state.sort;
    sortSelect.addEventListener('change', function () {
      state.sort = sortSelect.value || 'next';
      saveListUiState();
      renderList();
    });
  }

  var searchInput = document.getElementById('groupSearch');
  if (searchInput) {
    searchInput.value = state.search;
    searchInput.addEventListener('input', function () {
      state.search = searchInput.value || '';
      saveListUiState();
      renderList();
    });
  }
  var clearSearchBtn = document.getElementById('btnClearSearch');
  if (clearSearchBtn && searchInput) {
    clearSearchBtn.addEventListener('click', function () {
      state.search = '';
      searchInput.value = '';
      saveListUiState();
      searchInput.focus();
      renderList();
    });
  }
  var onlyFreeSeatsToggle = document.getElementById('onlyFreeSeats');
  if (onlyFreeSeatsToggle) {
    onlyFreeSeatsToggle.checked = !!state.onlyFreeSeats;
    onlyFreeSeatsToggle.addEventListener('change', function () {
      state.onlyFreeSeats = !!onlyFreeSeatsToggle.checked;
      saveListUiState();
      renderList();
    });
  }
  var resetListStateBtn = document.getElementById('btnResetListState');
  if (resetListStateBtn) {
    resetListStateBtn.addEventListener('click', function () {
      resetListRefinements({ focusSearch: true });
    });
  }
  var refreshListBtn = document.getElementById('btnRefreshList');
  if (refreshListBtn) {
    refreshListBtn.addEventListener('click', function () {
      loadList();
    });
  }

  document.getElementById('btnFabNew').addEventListener('click', openCreate);
  document.getElementById('btnSubmitCreate').addEventListener('click', submitCreate);

  initGroupCreateTimePickers();
  setSeasonDateMin();
  document.getElementById('btnSeasonToday').addEventListener('click', function () {
    setSeasonDateMin();
    document.getElementById('fSeason').value = todayYmdLocal();
  });
  document.getElementById('btnSeasonWeek').addEventListener('click', function () {
    setSeasonDateMin();
    document.getElementById('fSeason').value = addDaysYmd(todayYmdLocal(), 7);
  });
  document.getElementById('btnSeasonClear').addEventListener('click', function () {
    document.getElementById('fSeason').value = '';
  });

  (function bindEditScheduleModal() {
    var sub = document.getElementById('btnSubmitEditSchedule');
    var can = document.getElementById('btnEditScheduleCancel');
    if (sub) sub.addEventListener('click', submitEditSchedule);
    if (can) can.addEventListener('click', closeEditScheduleModal);
    var m = document.getElementById('modalEditSchedule');
    if (m) {
      m.addEventListener('click', function (ev) {
        if (ev.target === m) closeEditScheduleModal();
      });
    }
    var btnEt = document.getElementById('btnEditSeasonToday');
    if (btnEt) {
      btnEt.addEventListener('click', function () {
        setEditSeasonDateMin();
        var el = document.getElementById('editFSeason');
        if (el) el.value = todayYmdLocal();
      });
    }
    var btnEw = document.getElementById('btnEditSeasonWeek');
    if (btnEw) {
      btnEw.addEventListener('click', function () {
        setEditSeasonDateMin();
        var el = document.getElementById('editFSeason');
        if (el) el.value = addDaysYmd(todayYmdLocal(), 7);
      });
    }
    var btnEc = document.getElementById('btnEditSeasonClear');
    if (btnEc) {
      btnEc.addEventListener('click', function () {
        var el = document.getElementById('editFSeason');
        if (el) el.value = '';
      });
    }
  })();

  document.getElementById('btnHomeList').addEventListener('click', function () {
    if (window.navigateTrainerHome) window.navigateTrainerHome();
    else window.location.href = '/webapp/trainer-home';
  });
  document.getElementById('btnBackCreate').addEventListener('click', function () { showScreen('list'); });

  /** Mini App / WebView: tap outside fields to blur textarea & hide keyboard (catalog comment, etc.). */
  (function bindCreateScreenBlurOnOutsidePointer() {
    var screen = document.getElementById('screenCreate');
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
        if (t.closest && t.closest('.wd')) return;
        if (t.closest && t.closest('.tg-chip-btn')) return;
        if (t.closest && t.closest('textarea, input, select')) return;
        var ae = document.activeElement;
        if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT')) {
          ae.blur();
        }
      },
      false
    );
  })();
  document.getElementById('btnHomeDetail').addEventListener('click', function () {
    if (window.navigateTrainerHome) window.navigateTrainerHome();
    else window.location.href = '/webapp/trainer-home';
  });
  document.getElementById('btnBackDetail').addEventListener('click', function () {
    showScreen('list');
    try {
      var p = new URLSearchParams(window.location.search || '');
      if (p.has('id')) {
        p.delete('id');
        var q = p.toString();
        var next = window.location.pathname + (q ? '?' + q : '') + (window.location.hash || '');
        window.history.replaceState(null, '', next);
      }
    } catch (e) { /* ignore */ }
  });

  renderWeekdayPick();
  showScreen('list');
  syncListControls();
  updateSearchClearVisibility();
  bindAddMemberModal();
  bindSlotActionsModal();

  function waitForInitThen(cb) {
    syncInitFromTg();
    if (currentInit()) {
      cb();
      return;
    }
    if (!tg) {
      cb();
      return;
    }
    var n = 0;
    var iv = setInterval(function () {
      n++;
      syncInitFromTg();
      if (currentInit()) {
        clearInterval(iv);
        cb();
        return;
      }
      if (n >= 300) {
        clearInterval(iv);
        cb();
      }
    }, 50);
  }

  waitForInitThen(function () {
    loadList().then(function () {
      var deep = qs.get('id');
      if (deep) {
        var idNum = parseInt(deep, 10);
        if (isFinite(idNum) && idNum > 0) openDetail(idNum);
      }
    });
  });
})();
