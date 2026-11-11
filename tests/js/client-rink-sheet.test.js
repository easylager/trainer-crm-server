/**
 * «Мой каток» (TASK-372).
 * Run: node --test tests/js/client-rink-sheet.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const sheetSrc = fs.readFileSync(path.join(webapp, 'client-sheet.js'), 'utf8');
const rinkSrc = fs.readFileSync(path.join(webapp, 'client-rink-sheet.js'), 'utf8');
const rink = require(path.join(webapp, 'client-rink-sheet.js'));
const ice = require(path.join(webapp, 'ice-tab-model.js'));
const bell = require(path.join(webapp, 'bell-follow.js'));

const TODAY = '2026-11-11';

describe('подписи и шаг', () => {
  it('склоняет 1, 2, 5, 11 и 21', () => {
    assert.equal(rink.pluralRu(1, 'сеанс', 'сеанса', 'сеансов'), 'сеанс');
    assert.equal(rink.pluralRu(2, 'сеанс', 'сеанса', 'сеансов'), 'сеанса');
    assert.equal(rink.pluralRu(5, 'сеанс', 'сеанса', 'сеансов'), 'сеансов');
    assert.equal(rink.pluralRu(11, 'сеанс', 'сеанса', 'сеансов'), 'сеансов');
    assert.equal(rink.pluralRu(21, 'сеанс', 'сеанса', 'сеансов'), 'сеанс');
    assert.equal(rink.sessionsCaption({ sessionsLeftToday: 1 }), 'сегодня ещё\u00a01\u00a0сеанс');
    assert.equal(rink.sessionsCaption({ sessionsLeftToday: 2 }), 'сегодня ещё\u00a02\u00a0сеанса');
    assert.equal(rink.sessionsCaption({ sessionsLeftToday: 5 }), 'сегодня ещё\u00a05\u00a0сеансов');
    assert.equal(rink.sessionsCaption({ sessionsLeftToday: 11 }), 'сегодня ещё\u00a011\u00a0сеансов');
    assert.equal(rink.sessionsCaption({ sessionsLeftToday: 21 }), 'сегодня ещё\u00a021\u00a0сеанс');
  });

  it('три подписи строки и час без ведущего нуля', () => {
    assert.equal(
      rink.sessionsCaption({ sessionsLeftToday: 0, tomorrowFirst: '09:00' }),
      'сегодня сеансов нет, завтра\u00a0— с\u00a09:00',
    );
    assert.equal(
      rink.sessionsCaption({ sessionsLeftToday: 0, tomorrowFirst: '12:15' }),
      'сегодня сеансов нет, завтра\u00a0— с\u00a012:15',
    );
    assert.equal(rink.sessionsCaption({ sessionsLeftToday: 0, tomorrowFirst: null }), 'сегодня сеансов нет');
    assert.equal(rink.sessionsCaption({ sessionsLeftToday: 0, tomorrowFirst: '' }), 'сегодня сеансов нет');
    assert.equal(
      rink.rinkCaption({ sessions_left_today: 3, tomorrow_first: '09:00' }, TODAY),
      'сегодня ещё\u00a03\u00a0сеанса',
    );
  });

  it('ближайший сегодня при многих будущих не берёт more_count как «сегодня ещё»', () => {
    const todayMany = {
      live: { kind: 'session', local_date: TODAY, more_count: 34, starts_at_local: '19:00' },
    };
    assert.equal(rink.rinkCaption(todayMany, TODAY), '');
    assert.equal(
      rink.rinkCaption(Object.assign({ sessions_left_today: 2 }, todayMany), TODAY),
      'сегодня ещё\u00a02\u00a0сеанса',
    );
    assert.deepEqual(rink.countsFromLive(todayMany, TODAY), { sessionsLeftToday: null, tomorrowFirst: null });
    assert.equal(
      rink.rinkCaption({ live: { kind: 'session', local_date: '2026-11-12', more_count: 4, starts_at_local: '09:00' } }, TODAY),
      'сегодня сеансов нет, завтра\u00a0— с\u00a09:00',
    );
    assert.equal(
      rink.rinkCaption({ live: { kind: 'session', local_date: '2026-11-13', starts_at_local: '10:00' } }, TODAY),
      'сегодня сеансов нет',
    );
    assert.equal(rink.rinkCaption({ live: { kind: 'phone', text: 'Время — по телефону' } }, TODAY), 'сегодня сеансов нет');
  });

  it('подписка уже есть — шага 2 нет; нет подписки — вопрос', () => {
    assert.equal(rink.afterSave({ subscribed: true }), 'done');
    assert.equal(rink.afterSave({ subscribed: false }), 'subscribe');
    assert.equal(rink.afterSave(null), 'subscribe');
    assert.equal(rink.afterSave({ subscribed: 'true' }), 'subscribe');
  });

  it('кнопка гаснет, пока каток не выбран и пока запрос идёт', () => {
    assert.deepEqual(rink.buttonState(null, false), { label: 'Выбери каток', disabled: true });
    assert.deepEqual(rink.buttonState({ id: 1 }, false), { label: 'Это мой каток', disabled: false });
    assert.deepEqual(rink.buttonState({ id: 1 }, true), { label: 'Это мой каток', disabled: true });
  });

  it('ищет по имени, «ё» совпадает с «е», порядок не меняет', () => {
    const items = [{ name: 'Берёза' }, { name: 'Чижовка-арена' }, { name: 'Замок' }];
    assert.deepEqual(rink.filterRinks(items, 'береза').map((item) => item.name), ['Берёза']);
    assert.deepEqual(rink.filterRinks(items, 'ЧИЖОВКА').map((item) => item.name), ['Чижовка-арена']);
    assert.equal(rink.filterRinks(items, '   ').length, 3);
    assert.deepEqual(rink.filterRinks(null, 'а'), []);
  });

  it('город человека и окно «когда» — как у «Поиска», без своего запроса', () => {
    assert.equal(
      rink.searchQuery({ session: { city_id: 4 }, iceState: { when: 'today' }, whenPref: { when: 'weekend' }, model: ice }).when,
      'today',
    );
    assert.equal(
      rink.searchQuery({
        session: { city_id: 4, ice_when: 'tomorrow' },
        iceState: { when: 'today' },
        whenPref: { when: 'weekend' },
        model: ice,
      }).when,
      'tomorrow',
    );
    const plain = rink.searchQuery({ session: { city_id: 4 }, model: ice });
    assert.equal(plain.when, 'any');
    assert.equal(plain.intent, 'skate');
    assert.equal(plain.near, '');
    assert.deepEqual(plain.venueTypes, []);
    assert.equal(plain.cityId, 4);
    assert.equal(rink.searchQuery({ session: {}, model: ice }).cityId, null);
  });

  it('порядок ленты — orderForFeed «Поиска», без «Рядом»', () => {
    const items = [
      { id: 1, name: 'Позже', live: { kind: 'session', outside_window: true } },
      { id: 2, name: 'Сейчас', live: { kind: 'session', outside_window: false } },
    ];
    assert.deepEqual(
      rink.orderedRinks(items, { key: 'today' }, ice).map((item) => item.name),
      ['Сейчас', 'Позже'],
    );
    assert.deepEqual(rink.orderedRinks(items, null, ice).map((item) => item.id), [1, 2]);
  });

  it('заголовок шага 2 берёт имя в ёлочки', () => {
    assert.equal(rink.stepTitle('Чижовка-арена'), '«Чижовка-арена»\u00a0— твой каток');
    assert.equal(rink.stepTitle('Ледовый дворец'), '«Ледовый дворец»\u00a0— твой каток');
    assert.equal(rink.stepTitle('«Чижовка-арена»'), '«Чижовка-арена»\u00a0— твой каток');
  });

  it('не звучит как букмекерка и не красит хексами', () => {
    assert.doesNotMatch(rinkSrc, /×|процент|коэфф/i);
    assert.equal(rinkSrc.match(/#[0-9a-fA-F]{3,8}/g), null);
    assert.match(rinkSrc, /Не сохранилось\. Попробуй ещё раз/);
  });
});

function matchesOne(el, sel) {
  if (sel === 'a[href]') return el.tagName === 'A' && el.hasAttribute('href');
  const not = sel.match(/^(\w+):not\(\[disabled\]\)$/);
  if (not) return el.tagName === not[1].toUpperCase() && !el.disabled;
  if (sel === '[tabindex]:not([tabindex="-1"])') {
    return el.hasAttribute('tabindex') && el.getAttribute('tabindex') !== '-1';
  }
  const attr = sel.match(/^\[([\w-]+)="([^"]*)"\]$/);
  if (attr) return el.getAttribute(attr[1]) === attr[2];
  if (sel[0] === '.') return el.classList.contains(sel.slice(1));
  if (sel[0] === '#') return el.id === sel.slice(1);
  if (/^[a-z][a-z0-9]*$/i.test(sel)) return el.tagName === sel.toUpperCase();
  return false;
}

function matches(el, selector) {
  return String(selector).split(',').some((part) => matchesOne(el, part.trim()));
}

function walk(el, sel, out) {
  if (!el || !el.tagName) return;
  if (matches(el, sel)) out.push(el);
  for (const child of el.children) walk(child, sel, out);
}

class El {
  constructor(tag, doc) {
    this.tagName = String(tag).toUpperCase();
    this.doc = doc;
    this.attrs = {};
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this._text = '';
    this._disabled = false;
    this.id = '';
    this.classList = {
      _s: new Set(),
      add(...names) { names.forEach((name) => this._s.add(name)); },
      remove(...names) { names.forEach((name) => this._s.delete(name)); },
      contains: (name) => this.classList._s.has(name),
      toggle(name, force) {
        const on = force === undefined ? !this._s.has(name) : !!force;
        if (on) this._s.add(name);
        else this._s.delete(name);
      },
    };
    this.style = {};
    this.nodeType = 1;
    this.checked = false;
    this.value = '';
  }

  get textContent() {
    if (this.children.length) return this.children.map((child) => child.textContent).join('');
    return this._text;
  }

  set textContent(value) {
    this._text = value == null ? '' : String(value);
    this.children = [];
  }

  get disabled() { return this._disabled; }

  set disabled(value) {
    this._disabled = !!value;
    if (this._disabled) this.attrs.disabled = '';
    else delete this.attrs.disabled;
  }

  get hidden() { return this.hasAttribute('hidden'); }

  set hidden(value) {
    if (value) this.setAttribute('hidden', '');
    else this.removeAttribute('hidden');
  }

  get className() { return [...this.classList._s].join(' '); }

  set className(value) {
    this.classList._s = new Set(String(value || '').split(/\s+/).filter(Boolean));
  }

  get firstChild() { return this.children[0] || null; }

  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === this.doc.documentElement;
  }

  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === 'id') this.id = String(value);
    if (name === 'class') this.className = String(value);
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }

  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); }

  removeAttribute(name) { delete this.attrs[name]; }

  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    this._text = '';
    return child;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }

  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }

  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== fn);
  }

  dispatch(type, event) {
    const ev = Object.assign({ bubbles: true }, event || {});
    ev.target = ev.target || this;
    ev.preventDefault = () => { ev.defaultPrevented = true; };
    ev.stopPropagation = () => { ev.stopped = true; };
    let node = this;
    while (node) {
      const list = (node.listeners && node.listeners[type]) ? node.listeners[type].slice() : [];
      for (const fn of list) fn(ev);
      if (ev.stopped || !ev.bubbles || !node.parentNode) break;
      node = node.parentNode;
    }
    if (!ev.stopped && ev.bubbles && this.doc && this.doc.listeners && this.doc.listeners[type]) {
      for (const fn of this.doc.listeners[type].slice()) fn(ev);
    }
    return ev;
  }

  focus() { this.doc.activeElement = this; }

  contains(node) {
    if (node === this) return true;
    return this.children.some((child) => child.contains(node));
  }

  closest(sel) {
    let node = this;
    while (node && node.tagName) {
      if (matches(node, sel)) return node;
      node = node.parentNode;
    }
    return null;
  }

  querySelectorAll(sel) {
    const all = [];
    for (const child of this.children) walk(child, sel, all);
    return all;
  }

  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function flush() {
  for (let i = 0; i < 12; i += 1) await tick();
}

const RINKS = [
  { id: 10, name: '«Чижовка-арена»', city_name: 'Минск', sessions_left_today: 2, tomorrow_first: null },
  { id: 11, name: '«Замок»', city_name: 'Минск', sessions_left_today: 1, tomorrow_first: null },
  { id: 12, name: 'Ледовый дворец', city_name: 'Минск', sessions_left_today: 0, tomorrow_first: '09:00' },
  { id: 13, name: 'Минск-Арена', city_name: 'Минск', sessions_left_today: 0, tomorrow_first: null },
];

function harness(options) {
  options = options || {};
  const calls = [];
  const haptic = [];
  const popups = [];
  const document = {
    activeElement: null,
    documentElement: null,
    body: null,
    listeners: {},
    createElement(tag) { return new El(tag, document); },
    createElementNS(_ns, tag) { return new El(tag, document); },
    addEventListener(type, fn) {
      if (!this.listeners[type]) this.listeners[type] = [];
      this.listeners[type].push(fn);
    },
    removeEventListener(type, fn) {
      this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== fn);
    },
    querySelector(sel) {
      const all = [];
      walk(document.documentElement, sel, all);
      return all[0] || null;
    },
    querySelectorAll(sel) {
      const all = [];
      walk(document.documentElement, sel, all);
      return all;
    },
  };
  const html = new El('html', document);
  const body = new El('body', document);
  html.appendChild(body);
  document.documentElement = html;
  document.body = body;
  document.activeElement = body;
  const back = {
    isVisible: false,
    fn: null,
    onClick(fn) { this.fn = fn; },
    offClick() { this.fn = null; },
    show() { this.isVisible = true; },
    hide() { this.isVisible = false; },
  };
  let saveGate = null;
  const sandbox = {
    document,
    console,
    URLSearchParams,
    JSON,
    location: { search: options.search || '' },
    matchMedia() { return { matches: true }; },
    requestAnimationFrame(fn) { fn(); return 0; },
    setTimeout(fn) { fn(); return 0; },
    clearTimeout() {},
    scrollY: 0,
    scrollTo() {},
    fetch(url, opts) {
      const call = { url: String(url), opts: opts || {} };
      calls.push(call);
      const href = call.url;
      if (href.includes('/client/me/home-arena')) {
        if (options.hangSave) return new Promise((resolve, reject) => { saveGate = { resolve, reject }; });
        if (options.saveReject) return Promise.reject(new Error('offline'));
        const home = options.home === undefined
          ? { id: 10, name: '«Чижовка-арена»', subscribed: false, sessions_left_today: 2, tomorrow_first: null, href: '/webapp/arena?id=10' }
          : options.home;
        return Promise.resolve({
          ok: options.saveOk !== false,
          json: () => Promise.resolve(home ? { home_arena: home } : { home_arena: null }),
        });
      }
      if (href.includes('bell-follow')) {
        const body = JSON.parse((opts && opts.body) || '{}');
        if (href.includes('/outcome')) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
        const status = options.bellStatus || (options.bellOk === false ? 500 : 200);
        return Promise.resolve({
          ok: status >= 200 && status < 300,
          status: status,
          json: () => Promise.resolve({ arena_name: '«Чижовка-арена»', arena_id: body.arena_id }),
        });
      }
      if (href.includes('/client/session')) {
        if (options.sessionReject) return Promise.reject(new Error('offline'));
        return Promise.resolve({
          ok: options.sessionOk !== false,
          json: () => Promise.resolve(options.session || { city_id: 1, city_name: 'Минск' }),
        });
      }
      if (href.includes('/ice/arenas')) {
        if (options.listReject) return Promise.reject(new Error('offline'));
        if (href.includes('cursor=')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ items: options.page2 || [], next_cursor: null, window: options.window || null }),
          });
        }
        return Promise.resolve({
          ok: options.listOk !== false,
          json: () => Promise.resolve({
            items: options.items || RINKS,
            next_cursor: options.nextCursor || null,
            window: options.window || null,
          }),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    },
    IceTabModel: ice,
    GlideBellFollow: bell,
    Telegram: options.telegram === false ? undefined : {
      WebApp: {
        initData: options.initData == null ? 'init-1' : options.initData,
        initDataUnsafe: { user: { id: options.userId == null ? 7 : options.userId, allows_write_to_pm: false } },
        BackButton: back,
        HapticFeedback: { notificationOccurred(kind) { haptic.push(kind); } },
        isVersionAtLeast() { return true; },
        requestWriteAccess(cb) { if (cb) cb(options.writeGranted === true); },
        showPopup(config, cb) {
          popups.push(config);
          if (cb) cb('close');
        },
      },
    },
  };
  sandbox.window = sandbox;
  sandbox.fetch.bind = Function.prototype.bind;
  vm.createContext(sandbox);
  vm.runInContext(sheetSrc, sandbox);
  vm.runInContext(rinkSrc, sandbox);
  return { sandbox, document, calls, haptic, popups, back, saveGate: () => saveGate };
}

function radios(sheet) {
  return sheet.el.querySelectorAll('input').filter((node) => node.getAttribute('type') === 'radio' || node.type === 'radio');
}

function lines(sheet) {
  return sheet.el.querySelectorAll('.cr-line').map((node) => node.textContent);
}

describe('ClientRinkSheet', () => {
  it('тот же адрес ленты, город в шапке, текущий каток отмечен', async () => {
    const h = harness({ currentId: 10 });
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10 });
    await flush();
    assert.equal(sheet.el.getAttribute('aria-labelledby'), 'cr-title');
    assert.equal(sheet.el.querySelector('.cr-title').textContent, 'Где катаешься чаще всего?');
    assert.equal(sheet.el.querySelector('.cr-sub').textContent, 'Покажем его сеансы в\u00a0«Я».');
    assert.equal(sheet.el.querySelector('input').getAttribute('placeholder'), 'Название катка');
    assert.equal(sheet.el.querySelector('.cs-sr').textContent, 'Найти каток');
    assert.equal(sheet.el.querySelector('h3').textContent, 'Минск');
    assert.deepEqual(lines(sheet), [
      'сегодня ещё\u00a02\u00a0сеанса',
      'сегодня ещё\u00a01\u00a0сеанс',
      'сегодня сеансов нет, завтра\u00a0— с\u00a09:00',
      'сегодня сеансов нет',
    ]);
    const boxes = radios(sheet);
    assert.deepEqual(boxes.map((node) => node.value), ['10', '11', '12', '13']);
    assert.equal(boxes[0].checked, true);
    assert.equal(sheet.el.querySelector('.cr-save').textContent, 'Это мой каток');
    assert.equal(sheet.el.querySelector('.cr-save').disabled, false);
    const query = rink.searchQuery({ session: { city_id: 1, city_name: 'Минск' }, model: ice });
    assert.equal(h.calls[0].url, '/api/webapp/client/session');
    assert.equal(h.calls[0].opts.headers['X-Telegram-Init-Data'], 'init-1');
    assert.equal(h.calls[1].url, ice.buildListUrl(Object.assign({}, query, { limit: ice.LIST_PAGE_LIMIT })));
    assert.equal(h.calls.some((call) => String(call.url).includes('/sessions')), false);
    assert.equal(sheet.el.querySelector('.cr-mark').classList.contains('is-on'), true);
  });

  it('без выбора кнопка неактивна, фильтр не придумывает пустую фразу', async () => {
    const h = harness();
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: null });
    await flush();
    assert.equal(radios(sheet).some((node) => node.checked), false);
    assert.equal(sheet.el.querySelector('.cr-save').textContent, 'Выбери каток');
    assert.equal(sheet.el.querySelector('.cr-save').disabled, true);
    const input = sheet.el.querySelector('input');
    input.value = 'нет такого';
    input.dispatch('input', {});
    assert.equal(radios(sheet).length, 0);
    assert.equal(sheet.el.querySelector('h3'), null);
    assert.equal(sheet.el.textContent.includes('Такой'), false);
  });

  it('догружает следующую страницу тем же списком и сохраняет порядок окна', async () => {
    const h = harness({
      items: [
        { id: 1, name: 'Позже', sessions_left_today: 0, tomorrow_first: null, live: { kind: 'session', outside_window: true } },
        { id: 2, name: 'Сейчас', sessions_left_today: 1, tomorrow_first: null, live: { kind: 'session', outside_window: false } },
      ],
      nextCursor: '50',
      page2: [{ id: 3, name: 'Ещё каток', sessions_left_today: 5, tomorrow_first: null }],
      window: { key: 'today' },
    });
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: null });
    await flush();
    assert.deepEqual(radios(sheet).map((node) => node.value), ['2', '3', '1']);
    assert.equal(h.calls.filter((call) => call.url.includes('/ice/arenas')).length, 2);
    assert.match(h.calls.map((call) => call.url).join('\n'), /cursor=/);
  });

  it('subscribed false — тот же лист, шаг 2; «назад» закрывает, каток уже отдан', async () => {
    const saved = [];
    const h = harness();
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10, onSaved(home) { saved.push(home); } });
    await flush();
    const same = sheet.el;
    sheet.el.querySelector('.cr-save').dispatch('click', {});
    await flush();
    assert.equal(sheet.el, same);
    assert.equal(sheet.el.isConnected, true);
    assert.equal(h.haptic.length, 0);
    assert.equal(saved.length, 1);
    assert.equal(saved[0].subscribed, false);
    const put = h.calls.find((call) => call.url.includes('home-arena'));
    assert.equal(put.opts.method, 'PUT');
    assert.equal(put.opts.body, '{"arena_id":10}');
    assert.equal(sheet.el.getAttribute('aria-labelledby'), 'cr-bell-title');
    assert.equal(sheet.el.querySelector('.cr-bell-title').textContent, '«Чижовка-арена»\u00a0— твой каток');
    assert.equal(sheet.el.querySelector('.cr-ask').textContent, 'Писать в\u00a0Telegram, когда каток выложит новое расписание?');
    assert.equal(sheet.el.querySelector('.cr-yes').textContent, 'Да, писать');
    assert.equal(sheet.el.querySelector('.cr-no').textContent, 'Не надо');
    h.back.fn();
    assert.equal(sheet.el.isConnected, false);
    assert.equal(saved.length, 1);
    assert.equal(h.calls.some((call) => call.url.includes('bell-follow')), false);
  });

  it('«Не надо» закрывает шторку и не зовёт колокольчик', async () => {
    const h = harness();
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10, onSaved() {} });
    await flush();
    sheet.el.querySelector('.cr-save').dispatch('click', {});
    await flush();
    sheet.el.querySelector('.cr-no').dispatch('click', {});
    assert.equal(sheet.el.isConnected, false);
    assert.equal(h.calls.some((call) => call.url.includes('bell-follow')), false);
  });

  it('«Да, писать» идёт в bell-follow и показывает его текст отказа', async () => {
    const h = harness();
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10, onSaved() {} });
    await flush();
    sheet.el.querySelector('.cr-save').dispatch('click', {});
    await flush();
    sheet.el.querySelector('.cr-yes').dispatch('click', {});
    await flush();
    const follow = h.calls.find((call) => call.url === '/api/webapp/client/bell-follow');
    assert.ok(follow);
    assert.equal(follow.opts.method, 'POST');
    assert.equal(JSON.parse(follow.opts.body).arena_id, 10);
    assert.equal(follow.opts.headers['X-Telegram-Init-Data'], 'init-1');
    const outcome = h.calls.find((call) => call.url.includes('bell-follow/outcome'));
    assert.ok(outcome);
    assert.equal(JSON.parse(outcome.opts.body).outcome, 'denied');
    assert.equal(h.popups[0].message, bell.COPY_DECLINED);
    assert.equal(h.popups[0].buttons[0].text, bell.COPY_ENABLE);
    assert.equal(sheet.el.isConnected, false);
  });

  it('подписка уже есть — шторка закрывается, вибрация, шага 2 нет', async () => {
    const saved = [];
    const h = harness({
      home: { id: 11, name: '«Замок»', subscribed: true, sessions_left_today: 1, tomorrow_first: null, href: '/webapp/arena?id=11' },
    });
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 11, onSaved(home) { saved.push(home); } });
    await flush();
    radios(sheet).find((node) => node.value === '11').dispatch('change', {});
    sheet.el.querySelector('.cr-save').dispatch('click', {});
    await flush();
    assert.equal(sheet.el.isConnected, false);
    assert.deepEqual(h.haptic, ['success']);
    assert.equal(saved[0].name, '«Замок»');
    assert.equal(saved[0].subscribed, true);
    assert.equal(h.popups.length, 0);
    assert.equal(h.calls.some((call) => call.url.includes('bell-follow')), false);
  });

  it('ошибка сохранения — фраза из отчёта, выбор на месте, повтор не двоит запрос', async () => {
    const h = harness({ hangSave: true });
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10 });
    await flush();
    const save = sheet.el.querySelector('.cr-save');
    save.dispatch('click', {});
    save.dispatch('click', {});
    assert.equal(h.calls.filter((call) => call.url.includes('home-arena')).length, 1);
    assert.equal(save.disabled, true);
    h.saveGate().resolve({ ok: false, json: () => Promise.resolve({}) });
    await flush();
    assert.equal(sheet.el.isConnected, true);
    assert.equal(radios(sheet).find((node) => node.value === '10').checked, true);
    assert.equal(save.disabled, false);
    assert.equal(sheet.el.querySelector('.cr-toast').hidden, false);
    assert.equal(sheet.el.querySelector('.cr-toast').textContent, 'Не сохранилось. Попробуй ещё раз');
  });

  it('обрыв сети при сохранении и при списке — та же фраза', async () => {
    const saved = harness({ saveReject: true });
    const sheet = saved.sandbox.ClientRinkSheet.open({ currentId: 10 });
    await flush();
    sheet.el.querySelector('.cr-save').dispatch('click', {});
    await flush();
    assert.equal(sheet.el.querySelector('.cr-toast').textContent, 'Не сохранилось. Попробуй ещё раз');
    assert.equal(sheet.el.isConnected, true);

    const listed = harness({ listReject: true });
    const empty = listed.sandbox.ClientRinkSheet.open({ currentId: null });
    await flush();
    assert.equal(empty.el.querySelector('.cr-toast').textContent, 'Не сохранилось. Попробуй ещё раз');
    assert.equal(radios(empty).length, 0);
  });

  it('разрешение писать есть — текст «Готово» колокольчика', async () => {
    const h = harness({ writeGranted: true });
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10, onSaved() {} });
    await flush();
    sheet.el.querySelector('.cr-save').dispatch('click', {});
    await flush();
    sheet.el.querySelector('.cr-yes').dispatch('click', {});
    await flush();
    assert.equal(h.popups[0].message, bell.copyDone('«Чижовка-арена»'));
    assert.equal(JSON.parse(h.calls.find((call) => call.url.includes('outcome')).opts.body).outcome, 'granted');
    assert.equal(sheet.el.isConnected, false);
  });

  it('не Telegram — шага 2 нет, колокольчик не зовётся', async () => {
    const saved = [];
    const h = harness({ userId: -1 });
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10, onSaved(home) { saved.push(home); } });
    await flush();
    sheet.el.querySelector('.cr-save').dispatch('click', {});
    await flush();
    assert.equal(saved.length, 1);
    assert.equal(sheet.el.isConnected, false);
    assert.equal(h.haptic.length, 0);
    assert.equal(h.calls.some((call) => call.url.includes('bell-follow')), false);
    assert.equal(sheet.el.querySelector('.cr-bell-title'), null);
  });

  it('409 колокольчика не закрывает шторку и пишет его фразу отказа', async () => {
    const h = harness({ bellStatus: 409 });
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10, onSaved() {} });
    await flush();
    sheet.el.querySelector('.cr-save').dispatch('click', {});
    await flush();
    sheet.el.querySelector('.cr-yes').dispatch('click', {});
    await flush();
    assert.equal(sheet.el.isConnected, true);
    assert.equal(sheet.el.querySelector('.cr-toast').textContent, 'Не удалось сохранить подписку.');
    assert.equal(h.popups.length, 0);
  });

  it('успешный PUT после закрытия всё равно зовёт onSaved', async () => {
    const saved = [];
    const h = harness({ hangSave: true });
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10, onSaved(home) { saved.push(home); } });
    await flush();
    sheet.el.querySelector('.cr-save').dispatch('click', {});
    h.back.fn();
    assert.equal(sheet.el.isConnected, false);
    assert.equal(saved.length, 0);
    h.saveGate().resolve({
      ok: true,
      json: () => Promise.resolve({ home_arena: { id: 10, name: 'Чижовка-арена', subscribed: false } }),
    });
    await flush();
    assert.equal(saved.length, 1);
    assert.equal(saved[0].id, 10);
  });

  it('Escape в поиске с текстом очищает поле и не закрывает шторку', async () => {
    const h = harness();
    const sheet = h.sandbox.ClientRinkSheet.open({ currentId: 10 });
    await flush();
    const input = sheet.el.querySelector('input');
    input.value = 'замок';
    input.dispatch('input', {});
    assert.equal(radios(sheet).length, 1);
    input.dispatch('keydown', { key: 'Escape' });
    assert.equal(input.value, '');
    assert.equal(sheet.el.isConnected, true);
    assert.equal(radios(sheet).length, 4);
    input.dispatch('keydown', { key: 'Escape' });
    assert.equal(sheet.el.isConnected, false);
  });
});
