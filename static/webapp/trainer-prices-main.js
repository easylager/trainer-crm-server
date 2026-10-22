/**
 * «Услуги и цены» (TASK-313).
 *
 * Карточка на занятие: «Взрослый» и «Детский» сразу, «двое детей / двое взрослых / взрослый
 * с ребёнком» — под «Ещё тарифы». Тариф уходит на сервер, только если у него есть цена; пустая
 * цена — ученик видит «по запросу». Так же решала анкета (галочка + цена), но без галочек: здесь
 * цена сама и есть галочка.
 *
 * Сохраняет `PATCH /trainer/profile` только с `services` — остальная анкета не трогается.
 * Список услуг на сервере заменяется целиком, поэтому каждая услуга уходит со всем, что у неё
 * было: описанием, «что не входит», ценой места в группе, акцентом и форматом.
 */
(function () {
  'use strict';

  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    try { tg.ready(); tg.expand(); } catch (e) { /* */ }
    if (typeof window.__applyTrainerMiniAppTheme === 'function') window.__applyTrainerMiniAppTheme();
    try {
      var bgHex = tg.colorScheme === 'dark' ? '#0B0C0E' : '#F1F3F2';
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
    } catch (e2) { /* */ }
  }

  var MAIN_TIERS = [
    { code: 'adult', label: 'Взрослый' },
    { code: 'child', label: 'Детский' },
  ];
  var EXTRA_TIERS = [
    { code: 'two_children', label: 'Двое детей' },
    { code: 'two_adults', label: 'Двое взрослых' },
    { code: 'adult_and_child', label: 'Взрослый с\u00a0ребёнком' },
  ];
  /* Порядок, в котором тарифы уходят на сервер (как в анкете). */
  var TIER_ORDER = ['child', 'adult', 'two_children', 'two_adults', 'adult_and_child'];
  var MAX_PRICE = 100000;

  var state = {
    boot: null,
    rows: [],
    dirty: false,
    busy: false,
    pickerOpen: false,
    ret: 'account',
  };

  function el(id) { return document.getElementById(id); }

  function credential() {
    var rt = window.MiniAppRuntime;
    if (rt && typeof rt.getCredential === 'function') {
      var c = rt.getCredential();
      if (c) return c;
    }
    if (tg && tg.initData) return String(tg.initData);
    /* Переходы внутри кабинета несут init_data в адресе (как у анкеты). */
    try {
      var qs = new URLSearchParams(window.location.search || '');
      return qs.get('init_data') || qs.get('initData') || '';
    } catch (e) {
      return '';
    }
  }

  function apiUrl(path) {
    var url = '/api/webapp' + path;
    var c = credential();
    if (c) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(c);
    return url;
  }

  function request(method, path, body) {
    var c = credential();
    var h = { Accept: 'application/json', 'Content-Type': 'application/json' };
    if (c) h['X-Telegram-Init-Data'] = c;
    return fetch(apiUrl(path), {
      method: method,
      headers: h,
      cache: 'no-store',
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) {
          var detail = d && d.detail;
          if (window.MiniAppErrorUi && typeof window.MiniAppErrorUi.humanizeDetail === 'function') {
            detail = window.MiniAppErrorUi.humanizeDetail(detail) || detail;
          }
          if (detail && typeof detail !== 'string') detail = null;
          throw new Error(detail || 'Не получилось сохранить. Попробуйте ещё раз.');
        }
        return d;
      });
    });
  }

  function pageUrl(path) {
    var base = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
    var url = base + path;
    var c = credential();
    if (c) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(c);
    return url;
  }

  function haptic(kind) {
    try {
      var hf = tg && tg.HapticFeedback;
      if (!hf) return;
      if (kind === 'success' || kind === 'error') hf.notificationOccurred(kind);
      else hf.impactOccurred('light');
    } catch (e) { /* */ }
  }

  /* ─── Куда возвращаться ───────────────────────────────────────────────── */

  function readReturn() {
    var from = '';
    try { from = new URLSearchParams(window.location.search).get('from') || ''; } catch (e) { /* */ }
    if (from === 'onboarding') state.ret = 'onboarding';
    else if (from === 'hub') state.ret = 'hub';
    else state.ret = 'account';
    el('tpBackLabel').textContent = state.ret === 'onboarding' ? 'Назад' : state.ret === 'hub' ? 'Главная' : 'Профиль';
  }

  function returnUrl() {
    if (state.ret === 'onboarding') return pageUrl('trainer-onboarding?done=1');
    if (state.ret === 'hub') return pageUrl('trainer-home');
    return pageUrl('trainer-account');
  }

  function leave() {
    window.location.href = returnUrl();
  }

  function goBack() {
    if (!state.dirty || state.busy) { leave(); return; }
    var msg = 'Цены не сохранены. Выйти без сохранения?';
    if (tg && typeof tg.showConfirm === 'function') {
      tg.showConfirm(msg, function (ok) { if (ok) leave(); });
    } else if (window.confirm(msg)) {
      leave();
    }
  }

  /* ─── Модель ──────────────────────────────────────────────────────────── */

  function priceText(v) {
    if (v == null || v === '' || isNaN(Number(v))) return '';
    var n = Math.round(Number(v) * 100) / 100;
    return String(n).replace('.', ',');
  }

  function rowFromService(s) {
    var tiers = {};
    TIER_ORDER.forEach(function (c) { tiers[c] = ''; });
    var list = s.price_tiers || [];
    list.forEach(function (t) {
      if (t && tiers.hasOwnProperty(t.tier_kind) && t.price_byn != null) tiers[t.tier_kind] = priceText(t.price_byn);
    });
    /* Старые строки с одной ценой: price_byn — взрослый, price_child_byn — детский. */
    if (!list.length) {
      if (s.price_byn != null) tiers.adult = priceText(s.price_byn);
      if (s.price_child_byn != null) tiers.child = priceText(s.price_child_byn);
    }
    var extraFilled = EXTRA_TIERS.some(function (t) { return tiers[t.code] !== ''; });
    return {
      id: Number(s.service_id),
      name: s.service_name || '',
      isOnline: !!s.is_online,
      tiers: tiers,
      expanded: extraFilled,
      keep: {
        description: s.description || null,
        client_notice: s.client_notice || null,
        group_price_byn: s.group_price_byn != null ? Number(s.group_price_byn) : null,
        ui_accent: s.ui_accent || null,
      },
    };
  }

  function parsePrice(raw) {
    var t = String(raw == null ? '' : raw).replace(/\s+/g, '').replace(',', '.');
    if (!t) return null;
    if (!/^\d+(\.\d{1,2})?$/.test(t)) return NaN;
    var n = Number(t);
    if (n > MAX_PRICE) return NaN;
    return n;
  }

  function invalidRow() {
    for (var i = 0; i < state.rows.length; i++) {
      var r = state.rows[i];
      for (var j = 0; j < TIER_ORDER.length; j++) {
        if (isNaN(parsePrice(r.tiers[TIER_ORDER[j]]))) return { row: r, code: TIER_ORDER[j] };
      }
    }
    return null;
  }

  function payload() {
    return state.rows.map(function (r) {
      var tiers = [];
      TIER_ORDER.forEach(function (code) {
        var p = parsePrice(r.tiers[code]);
        if (p != null && !isNaN(p)) tiers.push({ tier_kind: code, price_byn: p });
      });
      var out = {
        service_id: r.id,
        price_tiers: tiers,
        is_online: r.isOnline,
        description: r.keep.description,
        client_notice: r.isOnline ? null : r.keep.client_notice,
      };
      if (!r.isOnline && r.keep.group_price_byn != null) out.group_price_byn = r.keep.group_price_byn;
      if (r.keep.ui_accent) out.ui_accent = r.keep.ui_accent;
      return out;
    }).sort(function (a, b) { return a.service_id - b.service_id; });
  }

  function trainer() { return (state.boot && state.boot.trainer) || {}; }

  function currency() {
    var sv = trainer().services || [];
    for (var i = 0; i < sv.length; i++) {
      if (sv[i].currency_code === 'RUB') return '₽';
      if (sv[i].currency_code) return 'BYN';
    }
    var cid = (trainer().profile || {}).city_id;
    var cities = (((state.boot || {}).refs || {}).cities || {}).items || [];
    for (var j = 0; j < cities.length; j++) {
      if (Number(cities[j].id) === Number(cid)) return cities[j].country === 'RU' ? '₽' : 'BYN';
    }
    return 'BYN';
  }

  function availableServices() {
    var me = Number(trainer().id);
    var taken = {};
    state.rows.forEach(function (r) { taken[r.id] = true; });
    var items = (((state.boot || {}).refs || {}).services || {}).items || [];
    return items.filter(function (s) {
      if (taken[Number(s.id)]) return false;
      return s.is_public !== false || Number(s.created_by_trainer_id) === me;
    });
  }

  /* ─── Рендер ──────────────────────────────────────────────────────────── */

  /* Предлог не остаётся в конце строки: «катанию «с / нуля»» → неразрывный пробел. */
  function glueShortWords(text) {
    return String(text || '').replace(/(^|[\s«(])(с|в|к|и|о|у|на|по|до|за|от|для)\s+/gi, '$1$2\u00a0');
  }

  function chevron() {
    return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
  }

  function tierRow(row, tier) {
    var lab = document.createElement('label');
    lab.className = 'tp-tier';
    var name = document.createElement('span');
    name.className = 'tp-tier__label';
    name.textContent = tier.label;
    var box = document.createElement('span');
    var inp = document.createElement('input');
    inp.type = 'text';
    inp.inputMode = 'decimal';
    inp.autocomplete = 'off';
    inp.enterKeyHint = 'next';
    inp.placeholder = '—';
    inp.value = row.tiers[tier.code];
    inp.setAttribute('aria-label', 'Цена, ' + tier.label.replace('\u00a0', ' ').toLowerCase() + ', ' + row.name);
    inp.dataset.price = '1';
    var syncBox = function () {
      box.className = 'tp-price' + (String(inp.value).trim() ? '' : ' tp-price--empty');
    };
    syncBox();
    inp.addEventListener('input', function () {
      row.tiers[tier.code] = inp.value;
      syncBox();
      markDirty();
    });
    var cur = document.createElement('span');
    cur.className = 'tp-price__cur';
    cur.textContent = currency();
    box.appendChild(inp);
    box.appendChild(cur);
    lab.appendChild(name);
    lab.appendChild(box);
    return lab;
  }

  function card(row) {
    var c = document.createElement('section');
    c.className = 'tp-card';
    var head = document.createElement('div');
    head.className = 'tp-card__head';
    var nm = document.createElement('span');
    nm.className = 'tp-card__name';
    nm.textContent = glueShortWords(row.name);
    var fmt = document.createElement('span');
    fmt.className = 'tp-card__format';
    fmt.textContent = row.isOnline ? 'онлайн' : 'на\u00a0площадке';
    head.appendChild(nm);
    head.appendChild(fmt);
    c.appendChild(head);
    MAIN_TIERS.forEach(function (t) { c.appendChild(tierRow(row, t)); });

    var more = document.createElement('button');
    more.type = 'button';
    more.className = 'tp-more';
    more.setAttribute('aria-expanded', row.expanded ? 'true' : 'false');
    more.innerHTML =
      '<span class="tp-more__text"><span class="tp-more__title">Ещё тарифы</span>' +
      (row.expanded ? '' : '<span class="tp-more__hint">Двое детей, двое взрослых, взрослый с&nbsp;ребёнком</span>') +
      '</span>' + chevron();
    more.onclick = function () {
      row.expanded = !row.expanded;
      haptic();
      render();
    };
    c.appendChild(more);

    if (row.expanded) {
      var extra = document.createElement('div');
      extra.className = 'tp-extra';
      EXTRA_TIERS.forEach(function (t) { extra.appendChild(tierRow(row, t)); });
      var rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'tp-remove';
      rm.textContent = 'Больше не провожу это занятие';
      rm.onclick = function () { removeRow(row); };
      extra.appendChild(rm);
      c.appendChild(extra);
    }
    return c;
  }

  function picker() {
    var box = document.createElement('section');
    box.className = 'tp-picker';
    var avail = availableServices();
    if (avail.length) {
      var t = document.createElement('p');
      t.className = 'tp-picker__title';
      t.textContent = 'Что ещё проводите';
      box.appendChild(t);
      avail.forEach(function (s) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'tp-picker__item';
        b.innerHTML = '<span></span>' +
          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
        b.firstChild.textContent = s.name;
        b.onclick = function () { addRow({ service_id: s.id, service_name: s.name, is_online: false }); };
        box.appendChild(b);
      });
    }
    var t2 = document.createElement('p');
    t2.className = 'tp-picker__title';
    t2.textContent = 'Нет в списке — впишите своё';
    box.appendChild(t2);
    var own = document.createElement('div');
    own.className = 'tp-picker__own';
    var inp = document.createElement('input');
    inp.type = 'text';
    inp.maxLength = 128;
    inp.placeholder = 'Например, растяжка';
    inp.enterKeyHint = 'done';
    inp.id = 'tpOwnName';
    var add = document.createElement('button');
    add.type = 'button';
    add.className = 'ta-btn ta-btn--small';
    add.textContent = 'Добавить';
    var submitOwn = function () {
      var name = String(inp.value || '').trim();
      if (!name) { inp.focus(); return; }
      add.disabled = true;
      note('Добавляем…');
      request('POST', '/trainer/services/custom', { name: name, is_online: false })
        .then(function (res) {
          add.disabled = false;
          note('');
          addRow({ service_id: res.service_id, service_name: res.name, is_online: !!res.is_online }, true);
        })
        .catch(function (err) {
          add.disabled = false;
          note(err.message, true);
        });
    };
    add.onclick = submitOwn;
    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submitOwn(); }
    });
    own.appendChild(inp);
    own.appendChild(add);
    box.appendChild(own);
    return box;
  }

  function render() {
    var list = el('tpList');
    var focusedId = document.activeElement && document.activeElement.id;
    list.innerHTML = '';
    if (!state.rows.length) {
      var empty = document.createElement('p');
      empty.className = 'tp-empty';
      empty.textContent = 'Пока не выбрано ни одного занятия — ученику нечего выбрать. Добавьте хотя бы одно.';
      list.appendChild(empty);
    }
    state.rows.forEach(function (r) { list.appendChild(card(r)); });
    if (state.pickerOpen || !state.rows.length) {
      list.appendChild(picker());
    } else {
      var addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'tp-add';
      addBtn.innerHTML =
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>' +
        'Добавить занятие';
      addBtn.onclick = function () { state.pickerOpen = true; haptic(); render(); };
      list.appendChild(addBtn);
    }
    if (focusedId && el(focusedId)) el(focusedId).focus();
    syncSave();
  }

  function addRow(svc, alreadySaved) {
    state.rows.push(rowFromService(svc));
    state.pickerOpen = false;
    /* Своё занятие сервер уже привязал к тренеру — само добавление сохранять не нужно,
       но цену к нему — нужно, поэтому кнопка всё равно оживает. */
    markDirty(alreadySaved);
    haptic('success');
    render();
    var cards = document.querySelectorAll('.tp-card');
    var last = cards[cards.length - 1];
    if (last) {
      try { last.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) { last.scrollIntoView(); }
    }
  }

  function removeRow(row) {
    var doIt = function () {
      state.rows = state.rows.filter(function (r) { return r !== row; });
      markDirty();
      render();
    };
    var msg = '«' + row.name + '» пропадёт со страницы записи. Уже назначенные занятия останутся.';
    if (tg && typeof tg.showConfirm === 'function') tg.showConfirm(msg, function (ok) { if (ok) doIt(); });
    else if (window.confirm(msg)) doIt();
  }

  /* ─── Сохранение ──────────────────────────────────────────────────────── */

  function note(text, isError) {
    var n = el('tpNote');
    n.textContent = text || '';
    n.classList.toggle('tp-note--error', !!isError);
  }

  function markDirty(soft) {
    state.dirty = true;
    if (!soft) note('');
    syncSave();
  }

  function syncSave() {
    var btn = el('tpSave');
    btn.disabled = state.busy || !state.dirty;
    btn.textContent = state.busy ? 'Сохраняем…' : 'Сохранить';
  }

  function save() {
    if (state.busy || !state.dirty) return;
    var bad = invalidRow();
    if (bad) {
      haptic('error');
      note('Цена — число, например 45 или 45,50', true);
      return;
    }
    state.busy = true;
    syncSave();
    note('');
    request('PATCH', '/trainer/profile', { services: payload() })
      .then(function () {
        state.busy = false;
        state.dirty = false;
        haptic('success');
        note('Сохранили');
        syncSave();
        setTimeout(leave, 600);
      })
      .catch(function (err) {
        state.busy = false;
        haptic('error');
        note(err.message, true);
        syncSave();
      });
  }

  /* ─── Клавиатура: поле всегда над ней ─────────────────────────────────── */

  function isField(t) {
    return !!(t && t.tagName === 'INPUT');
  }

  function bindKeyboard() {
    document.addEventListener('focusin', function (e) {
      if (!isField(e.target)) return;
      document.body.classList.add('tp-kb');
      var target = e.target;
      setTimeout(function () {
        try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (er) { /* */ }
      }, 250);
    });
    document.addEventListener('focusout', function () {
      setTimeout(function () {
        if (!isField(document.activeElement)) document.body.classList.remove('tp-kb');
      }, 60);
    });
    /* «Далее» на клавиатуре — к следующей цене, на последней — убрать клавиатуру. */
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || !e.target || !e.target.dataset || !e.target.dataset.price) return;
      e.preventDefault();
      var all = Array.prototype.slice.call(document.querySelectorAll('input[data-price]'));
      var i = all.indexOf(e.target);
      if (i >= 0 && all[i + 1]) all[i + 1].focus();
      else e.target.blur();
    });
  }

  /* ─── Загрузка ────────────────────────────────────────────────────────── */

  function load() {
    el('tpLoading').hidden = false;
    el('tpError').hidden = true;
    request('GET', '/trainer/profile/page-bootstrap')
      .then(function (d) {
        state.boot = d;
        state.rows = (trainer().services || []).map(rowFromService);
        var dur = (trainer().profile || {}).session_duration_minutes;
        el('tpLead').innerHTML = (dur ? 'За&nbsp;одно занятие, ' + Number(dur) + '&nbsp;мин. ' : '') +
          'Пустая цена — ученик увидит «по&nbsp;запросу»';
        el('tpLoading').hidden = true;
        el('tpList').hidden = false;
        el('tpFoot').hidden = false;
        render();
      })
      .catch(function () {
        el('tpLoading').hidden = true;
        el('tpError').hidden = false;
      });
  }

  function start() {
    readReturn();
    el('tpBack').onclick = goBack;
    el('tpRetry').onclick = load;
    el('tpSave').onclick = save;
    if (tg && tg.BackButton) {
      try {
        tg.BackButton.show();
        tg.BackButton.onClick(goBack);
      } catch (e) { /* */ }
    }
    bindKeyboard();
    load();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
