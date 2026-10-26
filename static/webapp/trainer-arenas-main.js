/**
 * «Где занимаюсь» (TASK-313).
 *
 * Был блок анкеты: чипы выбранного, комбобокс с эмодзи вместо фото, «Моей площадки нет» раскрывал
 * пустое место, а под ним форма с типами места (лёд, зал, бассейн, улица, хореография). Здесь:
 *   ваши катки сверху (основной помечен, «Сделать основным») →
 *   город и поиск → остальные катки города с кружками → «Моего катка нет в списке» →
 *   шторка с двумя полями. Похожий каток уже есть — предлагаем его, а не дубль.
 *
 * Тип места — только «Каток» или «Зал»: без выбора зал «Lifestyle» (#201) попал в ледовый каталог,
 * а бассейн, «площадка» и «площадка на улице» тренеров путали. Остальное поправит модератор.
 * Сохранение — `PATCH /trainer/profile {arena_ids, primary_arena_id, profile.city_id}`.
 * Добавленный каток сервер сразу привязывает к тренеру (`arena-setup`, mode=create).
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

  var RINK_ICON =
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="6"/>' +
    '<path d="M12 6v12"/><circle cx="12" cy="12" r="2.2"/></svg>';
  var CHECK_ICON =
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>';
  var PLUS_ICON =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';

  var state = {
    boot: null,
    cities: [],
    cityId: null,
    arenasByCity: {},
    known: {},
    picked: [],
    primaryId: null,
    locked: {},
    query: '',
    dirty: false,
    busy: false,
    adding: false,
    pendingNew: null,
    newVenue: 'ice',
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

  function request(method, path, body, extraHeaders) {
    var c = credential();
    var h = { Accept: 'application/json', 'Content-Type': 'application/json' };
    if (c) h['X-Telegram-Init-Data'] = c;
    Object.keys(extraHeaders || {}).forEach(function (k) { h[k] = extraHeaders[k]; });
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
      if (kind === 'success' || kind === 'error' || kind === 'warning') hf.notificationOccurred(kind);
      else hf.selectionChanged();
    } catch (e) { /* */ }
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function confirmDialog(msg, cb) {
    if (tg && typeof tg.showConfirm === 'function') tg.showConfirm(msg, function (ok) { if (ok) cb(); });
    else if (window.confirm(msg)) cb();
  }

  function alertDialog(msg) {
    if (tg && typeof tg.showAlert === 'function') tg.showAlert(msg);
    else window.alert(msg);
  }

  /* ─── Куда возвращаться ───────────────────────────────────────────────── */

  function readReturn() {
    var from = '';
    try { from = new URLSearchParams(window.location.search).get('from') || ''; } catch (e) { /* */ }
    state.ret = from === 'hub' ? 'hub' : 'account';
    el('tpBackLabel').textContent = state.ret === 'hub' ? 'Главная' : 'Профиль';
    if (state.ret === 'hub') el('tpBackIc').innerHTML = ICON_CHEVRON;
  }

  function leave() {
    window.location.href = pageUrl(state.ret === 'hub' ? 'trainer-home' : 'trainer-account');
  }

  /* Назад без перезагрузки: если пришли из «Профиля» и ничего не сохраняли, возвращаемся по истории —
     «Профиль» открывается из кэша, а не грузится заново. После сохранения — обычный переход, чтобы
     «Профиль» показал новые данные. */
  var ICON_CHEVRON = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M15 18l-6-6 6-6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>';

  function cameFromAccount() {
    try {
      var ref = document.referrer ? new URL(document.referrer) : null;
      return !!ref && ref.origin === window.location.origin && /\/trainer-account$/.test(ref.pathname);
    } catch (e) { return false; }
  }

  function exitSection() {
    if (state.ret === 'account' && !state.saved && cameFromAccount() && window.history.length > 1) {
      window.history.back();
      return;
    }
    leave();
  }

  function goBack() {
    if (!el('arSheet').hidden) { closeSheet(); return; }
    if (!state.dirty || state.busy) { exitSection(); return; }
    confirmDialog('Изменения не сохранены. Выйти без сохранения?', exitSection);
  }

  /* ─── Данные ──────────────────────────────────────────────────────────── */

  function cityName(id) {
    for (var i = 0; i < state.cities.length; i++) {
      if (Number(state.cities[i].id) === Number(id)) return state.cities[i].name;
    }
    return '';
  }

  function remember(items) {
    (items || []).forEach(function (a) { state.known[Number(a.id)] = a; });
  }

  function loadCity(cityId) {
    if (!cityId) return Promise.resolve([]);
    if (state.arenasByCity[cityId]) return Promise.resolve(state.arenasByCity[cityId]);
    return request('GET', '/trainer/profile/arenas?city_id=' + encodeURIComponent(cityId)).then(function (d) {
      var items = (d && d.items) || [];
      state.arenasByCity[cityId] = items;
      remember(items);
      return items;
    });
  }

  function arenaById(id) {
    return state.known[Number(id)] || null;
  }

  function isPicked(id) {
    return state.picked.indexOf(Number(id)) >= 0;
  }

  /* Короткий адрес: «Минск, ул. Ташкентская, 19» → «ул. Ташкентская, 19» в своём городе. */
  function shortAddress(a) {
    var addr = String((a && a.address) || '').trim();
    var city = cityName(a && a.city_id);
    if (city && addr.indexOf(city + ',') === 0) addr = addr.slice(city.length + 1).trim();
    return addr;
  }

  function matches(a, q) {
    if (!q) return true;
    var hay = (String(a.name || '') + ' ' + String(a.address || '')).toLowerCase().replace(/ё/g, 'е');
    return q.split(/\s+/).every(function (w) { return !w || hay.indexOf(w) >= 0; });
  }

  /* ─── Рендер ──────────────────────────────────────────────────────────── */

  function thumb(a) {
    var url = a && a.thumb_url;
    var d = document.createElement('span');
    d.className = 'ar-thumb';
    d.setAttribute('aria-hidden', 'true');
    if (url) d.style.backgroundImage = 'url("' + String(url).replace(/"/g, '%22') + '")';
    else d.innerHTML = RINK_ICON;
    return d;
  }

  function row(a, opts) {
    var id = Number(a.id);
    var on = isPicked(id);
    var locked = on && !!state.locked[id];
    var wrap = document.createElement('div');
    var b = document.createElement('div');
    b.className = 'ar-row';
    b.setAttribute('role', 'checkbox');
    b.setAttribute('aria-checked', on ? 'true' : 'false');
    b.setAttribute('aria-label', a.name || 'Каток');
    b.tabIndex = 0;
    b.appendChild(thumb(a));
    var main = document.createElement('span');
    main.className = 'ar-row__main';
    var text = document.createElement('span');
    text.className = 'ar-row__text';
    var nm = document.createElement('span');
    nm.className = 'ar-row__name';
    nm.innerHTML = '<span>' + esc(a.name || 'Каток') + '</span>' +
      (opts && opts.primary ? '<span class="ar-badge">Основной</span>' : '');
    text.appendChild(nm);
    var addrText = shortAddress(a);
    if (a.is_confirmed === false) addrText = (addrText ? addrText + ' · ' : '') + 'на\u00a0проверке';
    if (locked) addrText = (addrText ? addrText + ' · ' : '') + 'есть записи';
    if (addrText) {
      var ad = document.createElement('span');
      ad.className = 'ar-row__addr';
      ad.textContent = addrText;
      text.appendChild(ad);
    }
    if (opts && opts.canPrimary) {
      var pb = document.createElement('button');
      pb.type = 'button';
      pb.className = 'ar-primary-btn';
      pb.textContent = 'Сделать основным';
      pb.onclick = function (ev) {
        ev.stopPropagation();
        state.primaryId = id;
        markDirty();
        haptic();
        render();
      };
      text.appendChild(pb);
    }
    main.appendChild(text);
    var ck = document.createElement('span');
    ck.className = 'ar-check' + (on ? ' ar-check--on' : '') + (locked ? ' ar-check--locked' : '');
    ck.innerHTML = on ? CHECK_ICON : '';
    main.appendChild(ck);
    b.appendChild(main);
    var toggle = function () { togglePick(id); };
    b.addEventListener('click', toggle);
    b.addEventListener('keydown', function (ev) {
      if (ev.key === ' ' || ev.key === 'Enter') { ev.preventDefault(); toggle(); }
    });
    wrap.appendChild(b);
    return wrap;
  }

  function renderMine() {
    var box = el('arMine');
    var list = el('arMineList');
    list.innerHTML = '';
    box.hidden = !state.picked.length;
    var many = state.picked.length > 1;
    state.picked.forEach(function (id) {
      var a = arenaById(id) || { id: id, name: 'Каток' };
      var primary = many && Number(state.primaryId) === id;
      list.appendChild(row(a, { primary: primary, canPrimary: many && !primary }));
    });
    el('arPrimaryNote').hidden = !many;
  }

  function renderOthers() {
    var host = el('arOthers');
    host.innerHTML = '';
    var q = state.query.trim().toLowerCase().replace(/ё/g, 'е');
    var items = (state.arenasByCity[state.cityId] || []).filter(function (a) {
      return !isPicked(a.id) && matches(a, q);
    });
    if (!state.cityId) {
      var pickCity = document.createElement('p');
      pickCity.className = 'ar-empty';
      pickCity.textContent = 'Выберите город — покажем катки в нём.';
      host.appendChild(pickCity);
    } else if (!items.length) {
      var none = document.createElement('p');
      none.className = 'ar-empty';
      var inMine = q && state.picked.some(function (id) { var a = arenaById(id); return a && matches(a, q); });
      none.textContent = inMine
        ? 'Уже среди ваших катков — вверху.'
        : q ? 'Ничего не нашли. Добавьте свой каток — это минута.' : 'Все катки города уже у вас.';
      host.appendChild(none);
    }
    items.forEach(function (a) { host.appendChild(row(a)); });
    if (state.cityId) {
      var add = document.createElement('div');
      var ab = document.createElement('button');
      ab.type = 'button';
      ab.className = 'ar-row';
      ab.innerHTML = '<span class="ar-add-tile">' + PLUS_ICON + '</span>' +
        '<span class="ar-row__main"><span class="ar-add-label">Моего катка нет в списке</span></span>';
      ab.onclick = openSheet;
      add.appendChild(ab);
      host.appendChild(add);
    }
  }

  function renderCity() {
    el('arCityName').textContent = cityName(state.cityId) || 'Город';
  }

  function render() {
    renderMine();
    renderCity();
    renderOthers();
    syncSave();
  }

  /* ─── Действия ────────────────────────────────────────────────────────── */

  function togglePick(id) {
    if (isPicked(id)) {
      if (state.locked[id]) {
        haptic('warning');
        alertDialog('На этом катке есть записи учеников. Чтобы убрать его, сначала перенесите или отмените их в «Расписании».');
        return;
      }
      state.picked = state.picked.filter(function (x) { return x !== id; });
      if (Number(state.primaryId) === id) state.primaryId = state.picked[0] || null;
    } else {
      state.picked.push(id);
      if (!state.primaryId) state.primaryId = id;
    }
    haptic();
    markDirty();
    render();
  }

  function onCityChange() {
    var cid = Number(el('arCity').value) || null;
    if (cid === state.cityId) return;
    state.cityId = cid;
    state.query = '';
    el('arSearch').value = '';
    markDirty();
    renderCity();
    el('arOthers').innerHTML = '<p class="ar-empty">Загружаем катки…</p>';
    loadCity(cid)
      .then(render)
      .catch(function () {
        el('arOthers').innerHTML = '<p class="ar-empty">Не получилось загрузить катки. Попробуйте ещё раз.</p>';
      });
  }

  /* ─── Шторка «Добавить каток» ─────────────────────────────────────────── */

  function openSheet() {
    haptic();
    el('arNewName').value = state.query.trim();
    el('arNewAddress').value = '';
    el('arNewCity').textContent = cityName(state.cityId) ? cityName(state.cityId) + ',' : '';
    el('arAddError').hidden = true;
    setVenue('ice');
    el('arAddView').hidden = false;
    el('arSimilarView').hidden = true;
    el('arSheetBack').hidden = false;
    el('arSheet').hidden = false;
    setTimeout(function () { try { el('arNewName').focus(); } catch (e) { /* */ } }, 220);
  }

  function setVenue(key) {
    state.newVenue = key === 'gym' ? 'gym' : 'ice';
    Array.prototype.forEach.call(document.querySelectorAll('.ar-seg__btn'), function (b) {
      b.setAttribute('aria-checked', b.getAttribute('data-venue') === state.newVenue ? 'true' : 'false');
    });
  }

  function closeSheet() {
    el('arSheet').hidden = true;
    el('arSheetBack').hidden = true;
    state.pendingNew = null;
    try { document.activeElement && document.activeElement.blur(); } catch (e) { /* */ }
    syncKeyboard();
  }

  function addError(msg) {
    var n = el('arAddError');
    n.textContent = msg || '';
    n.hidden = !msg;
  }

  function submitNew(confirmDuplicate) {
    if (state.adding) return;
    var name = String(el('arNewName').value || '').trim();
    var addr = String(el('arNewAddress').value || '').trim();
    if (!name) { addError('Напишите, как называется каток.'); el('arNewName').focus(); return; }
    if (!addr) { addError('Напишите адрес — по нему ученик найдёт каток.'); el('arNewAddress').focus(); return; }
    var city = cityName(state.cityId);
    var fullAddr = city && addr.toLowerCase().indexOf(city.toLowerCase()) !== 0 ? city + ', ' + addr : addr;
    state.adding = true;
    state.pendingNew = { name: name, address: fullAddr };
    var btn = el('arAddSubmit');
    btn.disabled = true;
    btn.textContent = 'Добавляем…';
    addError('');
    request('POST', '/trainer/profile/arena-setup', {
      mode: 'create',
      arena_name: name,
      address: fullAddr,
      city_id: state.cityId,
      venue_type: state.newVenue,
      confirm_duplicate: !!confirmDuplicate,
    }, { 'Idempotency-Key': 'arena-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8) })
      .then(function (res) {
        state.adding = false;
        btn.disabled = false;
        btn.textContent = 'Добавить';
        if (res && res.status === 'duplicate_warning' && (res.duplicates || []).length) {
          showSimilar(res.duplicates);
          return;
        }
        onCreated(res, name, fullAddr);
      })
      .catch(function (err) {
        state.adding = false;
        btn.disabled = false;
        btn.textContent = 'Добавить';
        el('arAddView').hidden = false;
        el('arSimilarView').hidden = true;
        addError(err.message);
        haptic('error');
      });
  }

  function onCreated(res, name, addr) {
    var id = Number(res && res.arena_id);
    if (!id) { addError('Не получилось добавить. Попробуйте ещё раз.'); return; }
    /* Сервер уже привязал каток к тренеру — он и в списке города, и среди «ваших». */
    var a = { id: id, city_id: state.cityId, name: name, address: addr, thumb_url: null };
    remember([a]);
    var list = state.arenasByCity[state.cityId];
    if (list && !list.some(function (x) { return Number(x.id) === id; })) list.push(a);
    if (!isPicked(id)) state.picked.push(id);
    if (!state.primaryId) state.primaryId = id;
    state.query = '';
    el('arSearch').value = '';
    closeSheet();
    haptic('success');
    render();
    note('Каток добавлен');
  }

  function showSimilar(dups) {
    el('arAddView').hidden = true;
    el('arSimilarView').hidden = false;
    try { document.activeElement && document.activeElement.blur(); } catch (e) { /* */ }
    var host = el('arSimilarList');
    host.innerHTML = '';
    dups.slice(0, 3).forEach(function (d) {
      var id = Number(d.arena_id);
      var known = arenaById(id) || { id: id, name: d.name, address: d.address, city_id: state.cityId };
      var addr = shortAddress({ address: d.address || known.address, city_id: state.cityId });
      if (known.is_confirmed === false) addr = (addr ? addr + ' · ' : '') + 'на\u00a0проверке';
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ar-similar__item';
      b.appendChild(thumb(known));
      var t = document.createElement('span');
      t.className = 'ar-row__text';
      t.innerHTML = '<span class="ar-row__name"><span>' + esc(d.name || known.name) + '</span></span>' +
        '<span class="ar-row__addr">' + esc(addr) + '</span>';
      b.appendChild(t);
      b.onclick = function () {
        remember([known]);
        if (!isPicked(id)) state.picked.push(id);
        if (!state.primaryId) state.primaryId = id;
        markDirty();
        closeSheet();
        haptic('success');
        render();
      };
      host.appendChild(b);
    });
    var anyway = el('arAddAnyway');
    anyway.textContent = 'Нет, добавить «' + ((state.pendingNew && state.pendingNew.name) || 'свой каток') + '»';
    anyway.onclick = function () {
      el('arAddView').hidden = false;
      el('arSimilarView').hidden = true;
      submitNew(true);
    };
    haptic('warning');
  }

  /* ─── Сохранение ──────────────────────────────────────────────────────── */

  function note(text, isError) {
    var n = el('tpNote');
    n.textContent = text || '';
    n.classList.toggle('tp-note--error', !!isError);
  }

  function markDirty() {
    state.dirty = true;
    note('');
    syncSave();
  }

  function syncSave() {
    var btn = el('tpSave');
    btn.disabled = state.busy || !state.dirty;
    btn.textContent = state.busy ? 'Сохраняем…' : 'Сохранить';
  }

  function save() {
    if (state.busy || !state.dirty) return;
    state.busy = true;
    syncSave();
    var body = { arena_ids: state.picked.slice() };
    if (state.cityId) body.profile = { city_id: state.cityId };
    if (state.picked.length && state.primaryId && isPicked(state.primaryId)) {
      body.primary_arena_id = Number(state.primaryId);
    }
    request('PATCH', '/trainer/profile', body)
      .then(function () {
        state.busy = false;
        state.dirty = false;
        state.saved = true;
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

  /* ─── Клавиатура: поле и кнопка над ней ───────────────────────────────── */

  function keyboardInset() {
    var vv = window.visualViewport;
    if (!vv) return 0;
    return Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop));
  }

  function isField(t) {
    return !!(t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA'));
  }

  function syncKeyboard() {
    var inset = keyboardInset();
    var open = inset > 80 || (isField(document.activeElement) && inset > 0);
    document.body.classList.toggle('tp-kb', open);
    el('tpFoot').style.bottom = open ? inset + 'px' : '';
    /* Шторка встаёт над клавиатурой целиком — поля не уходят под неё. */
    el('arSheet').style.bottom = open ? inset + 'px' : '';
  }

  function bindKeyboard() {
    document.addEventListener('focusin', function (e) {
      if (!isField(e.target)) return;
      var target = e.target;
      setTimeout(function () {
        syncKeyboard();
        if (!target.closest('.ar-sheet') && target.id !== 'arSearch') {
          try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (er) { /* */ }
        }
      }, 250);
    });
    document.addEventListener('focusout', function () { setTimeout(syncKeyboard, 60); });
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', syncKeyboard);
      window.visualViewport.addEventListener('scroll', syncKeyboard);
    }
  }

  /* ─── Загрузка ────────────────────────────────────────────────────────── */

  function load() {
    el('tpLoading').hidden = false;
    el('tpError').hidden = true;
    request('GET', '/trainer/profile/page-bootstrap')
      .then(function (d) {
        state.boot = d;
        var t = d.trainer || {};
        var refs = d.refs || {};
        state.cities = (refs.cities && refs.cities.items) || [];
        state.cityId = Number((t.profile || {}).city_id) || null;
        state.picked = (t.arena_ids || []).map(Number);
        state.primaryId = t.primary_arena_id != null ? Number(t.primary_arena_id) : state.picked[0] || null;
        state.locked = {};
        (t.arena_ids_locked || []).forEach(function (id) { state.locked[Number(id)] = true; });
        /* Имена выбранных катков из других городов — из профиля, адресов у них нет. */
        var names = t.arena_names || [];
        state.picked.forEach(function (id, i) {
          if (!state.known[id]) state.known[id] = { id: id, name: names[i] || 'Каток', address: '' };
        });
        var sel = el('arCity');
        sel.innerHTML = '';
        if (!state.cityId) {
          var o0 = document.createElement('option');
          o0.value = '';
          o0.textContent = 'Выберите город';
          sel.appendChild(o0);
        }
        state.cities.forEach(function (c) {
          var o = document.createElement('option');
          o.value = String(c.id);
          o.textContent = c.name;
          sel.appendChild(o);
        });
        sel.value = state.cityId ? String(state.cityId) : '';
        return loadCity(state.cityId);
      })
      .then(function () {
        el('tpLoading').hidden = true;
        el('arRoot').hidden = false;
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
    el('arCity').addEventListener('change', onCityChange);
    el('arSearch').addEventListener('input', function () {
      state.query = el('arSearch').value || '';
      renderOthers();
    });
    el('arSheetBack').onclick = closeSheet;
    el('arSheetClose').onclick = closeSheet;
    Array.prototype.forEach.call(document.querySelectorAll('.ar-seg__btn'), function (b) {
      b.addEventListener('click', function () { setVenue(b.getAttribute('data-venue')); haptic(); });
    });
    el('arAddSubmit').onclick = function () { submitNew(false); };
    el('arNewName').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); el('arNewAddress').focus(); }
    });
    el('arNewAddress').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submitNew(false); }
    });
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
