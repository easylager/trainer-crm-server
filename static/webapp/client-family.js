/**
 * Страница «Семья» (TASK-387): люди аккаунта и общий доступ.
 * Люди — из GET /api/webapp/client/me → rows.family.people (контракт TASK-368), число общего
 * доступа — из GET /api/webapp/client/family-access. Выбор человека — тот же механизм, что у
 * переключателя на Главной: ClientProfileSwitcher.setActiveProfileId (cw_active_profile_id_v1).
 *
 * Чистые функции (peopleModel, accessValue, addPerson, ...) проверяет tests/js/client-family-model.test.js,
 * ниже — отрисовка и обработчики; они работают только на странице с #familyRoot.
 */
(function (root) {
  'use strict';

  var NBSP = ' ';
  var ME_URL = '/api/webapp/client/me';
  var ACCESS_URL = '/api/webapp/client/family-access';
  var PROFILES_URL = '/api/webapp/client/profiles';
  var NET_HINT = 'Не сохранилось. Попробуй ещё раз';
  var EMPTY_HINT = 'Имя не может быть пустым';
  var NO_LETTER_HINT = 'Нужна хотя бы одна буква, цифра или эмодзи';
  var CYRILLIC_RE = /^[Ѐ-ӿ\s-]+$/;

  function isObject(value) {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  function text(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function pluralRu(n, one, few, many) {
    var a = Math.abs(Number(n));
    var lastTwo = a % 100;
    var last = a % 10;
    if (lastTwo >= 11 && lastTwo <= 14) return many;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  /** Ответ /client/me, по которому можно рисовать: кэш старой схемы (rows.family.profiles) — нет. */
  function isUsable(data) {
    return (
      isObject(data) &&
      typeof data.name === 'string' &&
      isObject(data.rows) &&
      isObject(data.rows.family) &&
      Array.isArray(data.rows.family.people) &&
      data.rows.family.people.length > 0
    );
  }

  /** «Занятия и записи Ани»: падеж только для кириллицы, иначе имя как есть (латиница не склоняется). */
  function lessonsLine(name) {
    var given = text(name);
    if (!given) return 'Занятия и записи';
    var gen = given;
    var rpn = root.RuPersonName;
    if (CYRILLIC_RE.test(given) && rpn && typeof rpn.inflectPersonName === 'function') {
      try {
        gen = rpn.inflectPersonName(given, '', 'gen') || given;
      } catch (e) {
        gen = given;
      }
    }
    return 'Занятия и записи' + NBSP + gen;
  }

  function initialOf(name) {
    var chars = Array.from(text(name));
    return chars.length ? chars[0].toUpperCase() : '•';
  }

  /**
   * Люди для списка. «Вы» первым (так отдаёт сервер), подпись — имя аккаунта; безымянный близкий —
   * «Близкий». Ровно один active: если сервер не отметил никого — «Вы».
   */
  function peopleModel(data) {
    if (!isUsable(data)) return null;
    var out = [];
    data.rows.family.people.forEach(function (p, i) {
      if (!isObject(p)) return;
      var you = p.is_you === true;
      var name = text(p.name);
      out.push({
        key: you ? 'you' : 'p' + (p.profile_id != null ? p.profile_id : i),
        profileId: p.profile_id != null && Number(p.profile_id) > 0 ? Number(p.profile_id) : null,
        isYou: you,
        title: you ? 'Вы' : name || 'Близкий',
        subtitle: you ? name || text(data.name) : lessonsLine(name),
        initial: initialOf(you ? name || data.name : name),
        active: p.active === true,
      });
    });
    if (!out.length) return null;
    var firstActive = -1;
    out.forEach(function (p, i) {
      if (p.active && firstActive < 0) firstActive = i;
      else p.active = false;
    });
    if (firstActive < 0) {
      var you = out.findIndex(function (p) { return p.isYou; });
      out[you >= 0 ? you : 0].active = true;
    }
    return out;
  }

  /** Тап по человеку: тот же список, ровно один active. */
  function withActive(people, key) {
    if (!people.some(function (p) { return p.key === key; })) return people;
    return people.map(function (p) {
      return Object.assign({}, p, { active: p.key === key });
    });
  }

  /**
   * Значение справа у «Семейного доступа»: сколько человек получили доступ по приглашению.
   * Нет ответа — пусто (строка без числа); 0 — «Не настроен».
   */
  function accessValue(data) {
    if (!isObject(data)) return '';
    var n = data.extra_members_count;
    if (typeof n !== 'number' || !isFinite(n) || n < 0) return '';
    if (n === 0) return 'Не настроен';
    return n + NBSP + pluralRu(n, 'человек', 'человека', 'человек');
  }

  function nameCheck(raw) {
    var sheet = root.ClientNameSheet;
    if (sheet && typeof sheet.checkDisplayName === 'function') return sheet.checkDisplayName(raw);
    var name = text(raw).replace(/\s+/g, ' ');
    return { ok: name !== '', name: name, reason: name === '' ? 'empty' : '' };
  }

  /** Подсказка под полем: пусто — ничего; без буквы — своя; иначе ''. */
  function nameHint(raw) {
    var check = nameCheck(raw);
    if (check.name === '') return EMPTY_HINT;
    if (check.reason === 'no-letter') return NO_LETTER_HINT;
    return '';
  }

  /**
   * POST /client/profiles. Возвращает {ok:true, clientId} или {ok:false, message}.
   * Пустое/плохое имя до сети не доходит. 409 (лимит) и 400 — текст сервера как есть.
   */
  function addPerson(raw, deps) {
    var check = nameCheck(raw);
    if (!check.ok) return Promise.resolve({ ok: false, message: nameHint(raw) || EMPTY_HINT });
    var headers = { 'Content-Type': 'application/json' };
    if (deps.initData) headers['X-Telegram-Init-Data'] = deps.initData;
    return deps
      .fetch(PROFILES_URL, { method: 'POST', headers: headers, body: JSON.stringify({ first_name: check.name }) })
      .then(function (r) {
        return r
          .json()
          .catch(function () { return {}; })
          .then(function (body) {
            if (r.ok && body && Number(body.client_id) > 0) return { ok: true, clientId: Number(body.client_id) };
            var detail = body && typeof body.detail === 'string' ? body.detail : '';
            if ((r.status === 409 || r.status === 400) && detail) return { ok: false, message: detail };
            return { ok: false, message: NET_HINT };
          });
      })
      .catch(function () {
        return { ok: false, message: NET_HINT };
      });
  }

  var model = {
    isUsable: isUsable,
    peopleModel: peopleModel,
    withActive: withActive,
    lessonsLine: lessonsLine,
    accessValue: accessValue,
    nameHint: nameHint,
    addPerson: addPerson,
    ME_URL: ME_URL,
    ACCESS_URL: ACCESS_URL,
  };
  root.ClientFamilyModel = model;
  if (typeof module === 'object' && module.exports) module.exports = model;

  var doc = root.document;
  if (!doc || !doc.getElementById || !doc.getElementById('familyRoot')) return;

  /* ── страница ───────────────────────────────────────────────────── */
  var mount = doc.getElementById('familyRoot');
  var state = { people: null, access: null, accessFailed: false, ready: false };

  var CHECK = '<svg class="cf-check" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
  var RING = '<span class="cf-ring" aria-hidden="true"></span>';
  var PLUS = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
  var USERS = '<svg class="cf-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9.5" r="2.2"/><path d="M3.5 19c.6-3 2.8-5 5.5-5s4.9 2 5.5 5M15.5 14.2c2.2.2 3.7 2 4.2 4.8"/></svg>';
  var CHEV = '<svg class="cf-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>';

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function tg() {
    return root.Telegram && root.Telegram.WebApp ? root.Telegram.WebApp : null;
  }

  function initData() {
    var w = tg();
    if (w && w.initData) return String(w.initData);
    try {
      return new URLSearchParams(root.location.search).get('init_data') || '';
    } catch (e) {
      return '';
    }
  }

  function haptic() {
    try {
      var w = tg();
      if (w && w.HapticFeedback) w.HapticFeedback.selectionChanged();
    } catch (e) { /* нет вибрации */ }
  }

  function render() {
    if (!state.people) return;
    var rows = state.people
      .map(function (p) {
        return (
          '<button type="button" class="cf-row ga-press' + (p.active ? ' is-active' : '') + '" data-person="' + esc(p.key) + '" role="radio" aria-checked="' + (p.active ? 'true' : 'false') + '">' +
          '<span class="cf-avatar' + (p.active ? ' is-active' : '') + '">' + esc(p.initial) + '</span>' +
          '<span class="cf-meta"><span class="cf-title">' + esc(p.title) + '</span><span class="cf-sub">' + esc(p.subtitle) + '</span></span>' +
          (p.active ? CHECK : RING) +
          '</button>'
        );
      })
      .join('');
    var value = accessValue(state.access);
    mount.innerHTML =
      '<h1 class="cf-h1">Семья</h1>' +
      '<p class="cf-lead">Выберите, для кого сейчас записи и' + NBSP + 'абонементы. Тот же выбор — на' + NBSP + 'главной.</p>' +
      '<h2 class="cf-group">Кто катается</h2>' +
      '<nav class="cf-card cf-list" role="radiogroup" aria-label="Кто катается">' + rows +
      '<button type="button" class="cf-row cf-row--add ga-press" data-act="add"><span class="cf-avatar cf-avatar--add">' + PLUS + '</span><span class="cf-title">Добавить близкого</span></button>' +
      '</nav>' +
      '<h2 class="cf-group">Общий доступ</h2>' +
      '<nav class="cf-card cf-list" aria-label="Общий доступ">' +
      '<a class="cf-row cf-row--access ga-press" href="client-family-access" data-nav="client-family-access">' + USERS +
      '<span class="cf-title cf-title--flex">Семейный доступ</span>' +
      (value ? '<span class="cf-value">' + esc(value) + '</span>' : '') + CHEV + '</a>' +
      '</nav>' +
      '<p class="cf-note">Пригласите близкого, чтобы он видел ваши записи и' + NBSP + 'абонементы.</p>';
    mount.removeAttribute('aria-busy');
  }

  function showError() {
    mount.removeAttribute('aria-busy');
    mount.innerHTML =
      '<div class="state-panel error cf-state" role="alert"><p class="cf-state__text">Не загрузилось</p>' +
      '<button type="button" class="cf-state__retry ga-press" data-act="retry">Повторить</button></div>';
  }

  function getJson(url) {
    return root
      .fetch(url, { headers: { 'X-Telegram-Init-Data': initData() }, cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      });
  }

  function profilesReady() {
    var cps = root.ClientProfileSwitcher;
    return cps && typeof cps.init === 'function' ? cps.init() : Promise.resolve();
  }

  /* Профили загружены → fetch сам подставит X-Profile-Id активного, сервер отметит active. */
  function load() {
    var meP = profilesReady()
      .catch(function () { /* без переключателя тоже рисуем */ })
      .then(function () { return getJson(ME_URL); });
    var accessP = getJson(ACCESS_URL).catch(function () { return null; });
    return Promise.all([meP, accessP])
      .then(function (res) {
        var people = peopleModel(res[0]);
        if (!people) throw new Error('schema');
        state.people = people;
        state.access = res[1];
        state.ready = true;
        render();
      })
      .catch(function () {
        if (!state.people) showError();
      });
  }

  function choose(key) {
    var person = (state.people || []).filter(function (p) { return p.key === key; })[0];
    if (!person || person.active) return;
    var cps = root.ClientProfileSwitcher;
    if (!cps || typeof cps.setActiveProfileId !== 'function') return;
    haptic();
    cps.setActiveProfileId(person.profileId);
    state.people = withActive(state.people, key);
    render();
  }

  function go(path) {
    var data = initData();
    var url = path;
    if (data && !/[?&]init_data=/.test(url)) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(data);
    root.location.href = url;
  }

  function el(tag, className, content) {
    var node = doc.createElement(tag);
    if (className) node.className = className;
    if (content != null) node.textContent = content;
    return node;
  }

  function openAdd() {
    if (!root.ClientSheet) return;
    haptic();
    var busy = false;
    var alive = true;
    var content = el('div', 'cf-add');
    var title = el('h2', 'cf-add__title', 'Как зовут близкого?');
    title.id = 'cf-add-title';
    var sub = el('p', 'cf-add__sub', 'У близкого будут свои записи и абонементы, а переключаться между вами можно в одно касание.');
    var field = el('label', 'cf-add__field');
    field.appendChild(el('span', 'cs-sr', 'Имя'));
    var input = doc.createElement('input');
    input.type = 'text';
    input.className = 'cf-add__input';
    input.setAttribute('maxlength', '40');
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('enterkeyhint', 'done');
    input.setAttribute('aria-describedby', 'cf-add-hint');
    var hint = el('span', 'cf-add__hint', '');
    hint.id = 'cf-add-hint';
    field.appendChild(input);
    field.appendChild(hint);
    var save = el('button', 'cf-add__save', 'Добавить');
    save.type = 'button';
    content.appendChild(title);
    content.appendChild(sub);
    content.appendChild(field);
    content.appendChild(save);

    var serverHint = '';
    function paint() {
      var ok = nameCheck(input.value).ok;
      hint.textContent = (input.value.trim() !== '' ? nameHint(input.value) : '') || serverHint;
      save.disabled = busy || !ok;
      input.classList.toggle('is-filled', input.value.trim() !== '');
    }
    function submit() {
      if (busy || !alive || !nameCheck(input.value).ok) return;
      busy = true;
      serverHint = '';
      paint();
      addPerson(input.value, { fetch: root.fetch.bind(root), initData: initData() }).then(function (res) {
        if (!alive) return;
        busy = false;
        if (!res.ok) {
          serverHint = res.message;
          paint();
          return;
        }
        alive = false;
        sheet.close();
        var cps = root.ClientProfileSwitcher;
        if (cps && typeof cps.setActiveProfileId === 'function') cps.setActiveProfileId(res.clientId);
        load();
      });
    }
    input.addEventListener('input', function () {
      var sheetApi = root.ClientNameSheet;
      if (sheetApi && typeof sheetApi.fitNameField === 'function') {
        var fit = sheetApi.fitNameField(input.value);
        if (fit !== input.value) input.value = fit;
      }
      serverHint = '';
      paint();
    });
    input.addEventListener('keydown', function (event) {
      if (!event || event.key !== 'Enter' || event.isComposing) return;
      event.preventDefault();
      submit();
    });
    save.addEventListener('click', submit);
    paint();
    var sheet = root.ClientSheet.open({
      labelledBy: 'cf-add-title',
      content: content,
      onClose: function () { alive = false; },
    });
    (root.requestAnimationFrame || function (fn) { fn(); })(function () {
      try { input.focus(); } catch (e) { /* фокус недоступен */ }
    });
  }

  mount.addEventListener('click', function (ev) {
    var target = ev.target && ev.target.closest ? ev.target.closest('[data-act], [data-nav], [data-person]') : null;
    if (!target || !mount.contains(target)) return;
    var act = target.getAttribute('data-act');
    if (act === 'retry') {
      mount.innerHTML = SKELETON;
      mount.setAttribute('aria-busy', 'true');
      load();
      return;
    }
    if (act === 'add') {
      ev.preventDefault();
      openAdd();
      return;
    }
    var person = target.getAttribute('data-person');
    if (person) {
      ev.preventDefault();
      choose(person);
      return;
    }
    var nav = target.getAttribute('data-nav');
    if (nav) {
      ev.preventDefault();
      go(nav);
    }
  });

  var SKELETON = mount.innerHTML;

  /* «Назад»: флаг season_ui включён — история, иначе client-me (TASK-375); выключен — history.back(). */
  var backBtn = doc.getElementById('btnBack');
  if (backBtn) {
    backBtn.hidden = false;
    backBtn.addEventListener('click', function () {
      var S = root.ClientSeasonBack;
      var how = S && typeof S.goBack === 'function' ? S.goBack(root) : 'legacy';
      if (how === 'legacy') root.history.back();
    });
  }
  var w = tg();
  if (w) {
    try {
      if (typeof w.ready === 'function') w.ready();
      if (typeof w.expand === 'function') w.expand();
    } catch (e) { /* старый клиент */ }
  }

  root.addEventListener('pageshow', function (ev) {
    if (ev && ev.persisted) load();
  });
  load();
})(typeof window !== 'undefined' ? window : globalThis);
