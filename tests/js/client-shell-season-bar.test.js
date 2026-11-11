/**
 * TASK-369: таб-бар your-season в оболочке клиента.
 * Run: node --test tests/js/client-shell-season-bar.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const shellSrc = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/mini-app-client-shell.js'), 'utf8');
const FLAGS_KEY = 'cw_ui_flags_v1';

/* ── Минимальный DOM: ровно столько, сколько трогает оболочка, плюс сериализация. ───────── */

function parseSelector(sel) {
  const out = { tag: null, id: null, classes: [], attrs: [] };
  const re = /^([a-z0-9]+)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/gi;
  let m;
  while ((m = re.exec(sel))) {
    if (m[1]) out.tag = m[1].toLowerCase();
    else if (m[2]) out.id = m[2];
    else if (m[3]) out.classes.push(m[3]);
    else out.attrs.push([m[4], m[5]]);
  }
  return out;
}

class Node {
  constructor(tag, doc) {
    this.tagName = tag.toUpperCase();
    this.doc = doc;
    this.attrs = new Map();
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.innerHTML = '';
    this.textContent = '';
    this._classes = [];
    const self = this;
    this.classList = {
      add(...c) { c.forEach((x) => { if (!self._classes.includes(x)) self._classes.push(x); }); },
      remove(...c) { self._classes = self._classes.filter((x) => !c.includes(x)); },
      toggle(c, force) {
        const has = self._classes.includes(c);
        const want = force === undefined ? !has : !!force;
        if (want && !has) self._classes.push(c);
        if (!want && has) self._classes = self._classes.filter((x) => x !== c);
        return want;
      },
      contains(c) { return self._classes.includes(c); },
    };
  }
  get id() { return this.attrs.get('id') || ''; }
  set id(v) { this.attrs.set('id', v); }
  get className() { return this._classes.join(' '); }
  set className(v) { this._classes = String(v).split(/\s+/).filter(Boolean); }
  get lastElementChild() { return this.children[this.children.length - 1] || null; }
  get type() { return this.attrs.get('type') || ''; }
  set type(v) { this.attrs.set('type', v); }
  get href() { return this.attrs.get('href') || ''; }
  set href(v) { this.attrs.set('href', v); }
  set rel(v) { this.attrs.set('rel', v); }
  get rel() { return this.attrs.get('rel') || ''; }
  set as(v) { this.attrs.set('as', v); }
  setAttribute(n, v) { this.attrs.set(n, String(v)); }
  getAttribute(n) { return this.attrs.has(n) ? this.attrs.get(n) : null; }
  removeAttribute(n) { this.attrs.delete(n); }
  hasAttribute(n) { return this.attrs.has(n); }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  fire(t, ev) {
    const e = Object.assign({ type: t, target: this, preventDefault() {}, stopPropagation() {} }, ev || {});
    (this.listeners[t] || []).slice().forEach((fn) => fn.call(this, e));
  }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    this.children.push(c);
    return c;
  }
  removeChild(c) {
    this.children = this.children.filter((x) => x !== c);
    c.parentNode = null;
    return c;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  replaceWith(n) {
    const p = this.parentNode;
    assert.ok(p, 'replaceWith: у узла нет родителя');
    if (n.parentNode) n.parentNode.removeChild(n);
    const i = p.children.indexOf(this);
    p.children[i] = n;
    n.parentNode = p;
    this.parentNode = null;
  }
  insertAdjacentElement() {}
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  closest() { return null; }
  matches(sel) {
    const s = parseSelector(sel);
    if (s.tag && this.tagName.toLowerCase() !== s.tag) return false;
    if (s.id && this.id !== s.id) return false;
    if (s.classes.some((c) => !this._classes.includes(c))) return false;
    return s.attrs.every(([k, v]) => this.attrs.has(k) && (v === undefined || this.attrs.get(k) === v));
  }
  descendants() {
    const out = [];
    (function walk(n) { n.children.forEach((c) => { out.push(c); walk(c); }); })(this);
    return out;
  }
  querySelectorAll(sel) { return this.descendants().filter((n) => n.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getBoundingClientRect() { return { height: 0, width: 0 }; }
  html() {
    const tag = this.tagName.toLowerCase();
    const attrs = [];
    if (this._classes.length) attrs.push(['class', this.className]);
    this.attrs.forEach((v, k) => attrs.push([k, v]));
    Object.keys(this.dataset).forEach((k) => attrs.push(['data-' + k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase()), this.dataset[k]]));
    const open = '<' + tag + attrs.map(([k, v]) => ' ' + k + '="' + v + '"').join('') + '>';
    const inner = this.innerHTML || this.children.map((c) => c.html()).join('') || this.textContent;
    return open + inner + '</' + tag + '>';
  }
}

function bootShell({ pathname = '/webapp/client-home', search = '', flags, bodyShell = 'tabs', userId = 42, responses = {} } = {}) {
  const store = new Map();
  if (flags) store.set(FLAGS_KEY, JSON.stringify(Object.assign({ u: String(userId), at: Date.now() }, flags)));
  const session = new Map();
  const docListeners = {};
  const winListeners = {};
  const events = [];
  const fetches = [];
  const scrolls = [];
  const navigations = [];
  const timers = [];

  const doc = { readyState: 'complete' };
  doc.createElement = (tag) => new Node(tag, doc);
  doc.documentElement = new Node('html', doc);
  doc.documentElement.style = { setProperty() {} };
  doc.head = new Node('head', doc);
  doc.body = new Node('body', doc);
  if (bodyShell) doc.body.setAttribute('data-client-shell', bodyShell);
  doc.getElementById = (id) => doc.body.descendants().find((n) => n.id === id) || null;
  doc.querySelector = (sel) => [...doc.head.descendants(), ...doc.body.descendants()].find((n) => n.matches(sel)) || null;
  doc.querySelectorAll = (sel) => [...doc.head.descendants(), ...doc.body.descendants()].filter((n) => n.matches(sel));
  doc.addEventListener = (t, fn) => { (docListeners[t] = docListeners[t] || []).push(fn); };
  doc.activeElement = null;

  const win = {
    document: doc,
    location: {
      pathname, search, href: 'https://test' + pathname + search, replace(u) { navigations.push(u); },
      set href(u) { navigations.push(u); }, get href() { return 'https://test' + pathname + search; },
    },
    history: { length: 1 },
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) },
    sessionStorage: {
      getItem: (k) => (session.has(k) ? session.get(k) : null),
      setItem: (k, v) => session.set(k, String(v)),
      removeItem: (k) => session.delete(k),
    },
    Telegram: { WebApp: { initData: 'user=%7B%22id%22%3A' + userId + '%7D&hash=x', initDataUnsafe: { user: { id: userId } } } },
    CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
    addEventListener(t, fn) { (winListeners[t] = winListeners[t] || []).push(fn); },
    dispatchEvent(ev) {
      events.push(ev);
      (winListeners[ev.type] || []).slice().forEach((fn) => fn(ev));
      return true;
    },
    scrollY: 0,
    scrollTo(a) { scrolls.push(a); },
    matchMedia: () => ({ matches: false }),
    navigation: null,
    setTimeout(fn) { timers.push(fn); return timers.length; },
    fetch(url) {
      fetches.push(url);
      if (Object.prototype.hasOwnProperty.call(responses, url)) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(responses[url]) });
      }
      return new Promise(() => {});
    },
  };
  win.window = win;
  const ctx = vm.createContext({
    URL, URLSearchParams, JSON, Date, Promise, Number, String, Object, Array, Math, console,
    window: win, document: doc, location: win.location, history: win.history, Telegram: win.Telegram,
    sessionStorage: win.sessionStorage, localStorage: win.localStorage, addEventListener: win.addEventListener,
    fetch: win.fetch, setTimeout: win.setTimeout, fetchLog: fetches,
  });
  vm.runInContext(shellSrc, ctx);
  return {
    win, doc, store, session, events, fetches, scrolls, navigations,
    bar: () => doc.getElementById('clientTabBar'),
    overlay: () => doc.getElementById('clientMoreOverlay'),
    tabIds: () => (doc.getElementById('clientTabBar') ? doc.getElementById('clientTabBar').querySelectorAll('.client-tab-bar__btn').map((b) => b.dataset.tabId) : []),
    active: () => doc.getElementById('clientTabBar').querySelectorAll('.client-tab-bar__btn--active').map((b) => b.dataset.tabId),
    labels: () => doc.getElementById('clientTabBar').querySelectorAll('.client-tab-bar__btn').map((b) => b.innerHTML.replace(/^.*<\/span><span>|<\/span>$/g, '')),
    btn: (id) => doc.getElementById('clientTabBar').querySelectorAll('.client-tab-bar__btn').find((b) => b.dataset.tabId === id),
    emitDoc(t, ev) { (docListeners[t] || []).slice().forEach((fn) => fn(Object.assign({ type: t }, ev))); },
    async flush() {
      while (timers.length) timers.shift()();
      for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r));
    },
    input(type) {
      const n = doc.createElement(type === 'textarea' ? 'textarea' : 'input');
      if (type !== 'textarea') n.setAttribute('type', type);
      return n;
    },
  };
}

const SEASON = { season_ui: true, bookings_tab: false };
const SEASON_BOOKINGS = { season_ui: true, bookings_tab: true };

/* ── AC-1: флаг выключен — DOM как до TASK-369 ──────────────────────────────────────────── */

describe('AC-1: season_ui = false — старый бар байт в байт', () => {
  const variants = {
    'флага нет в кэше': undefined,
    'season_ui:false': { season_ui: false, bookings_tab: false },
    'bookings_tab без season_ui игнорируется': { season_ui: false, bookings_tab: true },
  };
  for (const [name, flags] of Object.entries(variants)) {
    it(name, () => {
      const t = bootShell({ flags });
      assert.equal(t.bar().html(), LEGACY_BAR_HTML);
      assert.equal(t.overlay().html(), LEGACY_OVERLAY_HTML);
    });
  }

  it('нет ни одного класса и атрибута режима season', () => {
    const t = bootShell({});
    assert.ok(!/season|kbd|n4|n5/.test(t.bar().html()));
    assert.deepEqual(t.tabIds(), ['home', 'catalog', 'bookings', 'more']);
  });
});

/* ── AC-2 / AC-3: набор вкладок ─────────────────────────────────────────────────────────── */

describe('AC-2: season_ui без bookings_tab — четыре вкладки, «Ещё» нет', () => {
  const t = bootShell({ flags: SEASON });

  it('порядок: Главная, Поиск, Кто кого, Я', () => {
    assert.deepEqual(t.tabIds(), ['home', 'catalog', 'kk', 'me']);
    assert.deepEqual(t.labels(), ['Главная', 'Поиск', 'Кто кого', 'Я']);
  });

  it('шторки «Ещё» в DOM нет вовсе', () => {
    assert.equal(t.overlay(), null);
    assert.equal(t.doc.getElementById('clientMoreSheet'), null);
    assert.ok(!t.doc.body.descendants().some((n) => /more/.test(n.className)), 'классов more нет нигде в body');
    assert.ok(!/data-tab-id="more"/.test(t.bar().html()));
  });

  it('openMoreSheet — пустой вызов: страница не блокируется', () => {
    t.win.ClientShell.openMoreSheet();
    t.win.ClientShell.toggleMoreSheet();
    assert.ok(!t.doc.body.classList.contains('client-shell-more-open'));
  });

  it('класс бара — season + n4 (сетка из четырёх колонок)', () => {
    assert.match(t.bar().className, /\bclient-tab-bar--season\b/);
    assert.match(t.bar().className, /\bclient-tab-bar--n4\b/);
  });
});

describe('AC-3: season_ui и bookings_tab — пять вкладок, «Записи» третья', () => {
  const t = bootShell({ flags: SEASON_BOOKINGS });
  it('порядок и подписи', () => {
    assert.deepEqual(t.tabIds(), ['home', 'catalog', 'bookings', 'kk', 'me']);
    assert.deepEqual(t.labels(), ['Главная', 'Поиск', 'Записи', 'Кто кого', 'Я']);
  });
  it('класс n5, шторки нет', () => {
    assert.match(t.bar().className, /\bclient-tab-bar--n5\b/);
    assert.equal(t.overlay(), null);
  });
  it('пути вкладок', () => {
    const paths = [];
    const t2 = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/ice' });
    for (const id of ['home', 'catalog', 'bookings', 'kk', 'me']) {
      t2.navigations.length = 0;
      if (id === 'catalog') continue; // уже на «Поиске»: повторный тап
      t2.btn(id).fire('click');
      paths.push(t2.navigations[0].replace(/\?.*$/, '').replace(/^.*\//, ''));
    }
    assert.deepEqual(paths, ['client-home', 'client-bookings', 'kto-kogo', 'client-me']);
  });
});

describe('иконки новых вкладок', () => {
  const t = bootShell({ flags: SEASON });
  const wrap = (inner) =>
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>';
  it('шайба и человек — как в спеке, тот же каркас, что у соседей', () => {
    assert.equal(
      t.win.ClientShell.TAB_ICONS.kk,
      wrap('<ellipse cx="12" cy="9.5" rx="8" ry="3.5"/><path d="M4 9.5v4.5c0 1.9 3.6 3.5 8 3.5s8-1.6 8-3.5V9.5"/>')
    );
    assert.equal(
      t.win.ClientShell.TAB_ICONS.me,
      wrap('<circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4 4-6.5 8-6.5s7.2 2.5 8 6.5"/>')
    );
  });
  it('иконки стоят в кнопках', () => {
    assert.ok(t.btn('kk').innerHTML.includes(t.win.ClientShell.TAB_ICONS.kk));
    assert.ok(t.btn('me').innerHTML.includes(t.win.ClientShell.TAB_ICONS.me));
  });
});

/* ── AC-4: таблица маршрутов, каждая строка ─────────────────────────────────────────────── */

describe('AC-4: активная вкладка по маршруту', () => {
  const rows = [
    ['client-home', 'home'],
    ['ice', 'catalog'],
    ['arena', 'catalog'],
    ['trainers', 'catalog'],
    ['catalog', 'catalog'],
    ['kto-kogo', 'kk'],
    ['client-me', 'me'],
    ['client-requests', 'me'],
    ['client-saved-trainers', 'me'],
    ['client-stats', 'me'],
    ['client-passes-certificates', 'me'],
    ['client-passes', 'me'],
    ['client-certificates', 'me'],
    ['client-family-access', 'me'],
    ['client-support', 'me'],
  ];
  for (const flags of [SEASON, SEASON_BOOKINGS]) {
    for (const [route, tab] of rows) {
      it(`${route} → ${tab} (bookings_tab=${flags.bookings_tab})`, () => {
        const t = bootShell({ flags, pathname: '/webapp/' + route });
        assert.deepEqual(t.active(), [tab]);
      });
    }
  }
  it('client-bookings → bookings, если вкладка есть', () => {
    assert.deepEqual(bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-bookings' }).active(), ['bookings']);
  });
  it('client-bookings → me, если вкладки нет', () => {
    assert.deepEqual(bootShell({ flags: SEASON, pathname: '/webapp/client-bookings' }).active(), ['me']);
  });
  it('catalog с чужим tab= — ничего не подсвечено, как раньше', () => {
    assert.deepEqual(bootShell({ flags: SEASON, pathname: '/webapp/catalog', search: '?tab=trainers' }).active(), []);
  });
  it('setForcedTab(more) в season уходит в «Я»; bookings без вкладки — тоже в «Я»', () => {
    const t = bootShell({ flags: SEASON });
    t.win.ClientShell.setForcedTab('more');
    assert.deepEqual(t.active(), ['me']);
    t.win.ClientShell.setForcedTab('bookings');
    assert.deepEqual(t.active(), ['me']);
    t.win.ClientShell.setForcedTab('catalog');
    assert.deepEqual(t.active(), ['catalog']);
  });
  it('флаг выключен: прежняя разметка активной вкладки («Ещё» для страниц из шторки)', () => {
    for (const [route, tab] of [['client-home', 'home'], ['ice', 'catalog'], ['client-bookings', 'bookings'], ['client-support', null], ['client-stats', 'more'], ['client-requests', 'more'], ['kto-kogo', null]]) {
      const t = bootShell({ pathname: '/webapp/' + route });
      assert.deepEqual(t.active(), tab ? [tab] : [], route);
    }
  });
});

/* ── AC-5: повторный тап ────────────────────────────────────────────────────────────────── */

describe('AC-5: повторный тап шлёт client-shell:retap', () => {
  const retaps = (t) => t.events.filter((e) => e.type === 'client-shell:retap');

  for (const [route, id] of [['client-home', 'home'], ['ice', 'catalog'], ['kto-kogo', 'kk'], ['client-me', 'me']]) {
    it(`${id}: событие с detail.tab, прокрутка наверх остаётся`, () => {
      const t = bootShell({ flags: SEASON, pathname: '/webapp/' + route });
      t.win.scrollY = 300;
      t.btn(id).fire('click');
      assert.equal(retaps(t).length, 1);
      assert.deepEqual({ ...retaps(t)[0].detail }, { tab: id });
      assert.equal(t.scrolls.length, 1);
      assert.equal(t.scrolls[0].top, 0);
      assert.equal(t.navigations.length, 0, 'повторный тап не уходит со страницы');
    });
  }

  it('bookings при пяти вкладках', () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-bookings' });
    t.btn('bookings').fire('click');
    assert.deepEqual({ ...retaps(t)[0].detail }, { tab: 'bookings' });
  });

  it('тап по другой вкладке уходит на страницу и retap не шлёт', () => {
    const t = bootShell({ flags: SEASON, pathname: '/webapp/client-home' });
    t.btn('me').fire('click');
    assert.equal(retaps(t).length, 0);
    assert.match(t.navigations[0], /client-me/);
  });

  it('«Я» на вложенной странице: тап ведёт в корень «Я», не retap', () => {
    const t = bootShell({ flags: SEASON, pathname: '/webapp/client-stats' });
    t.btn('me').fire('click');
    assert.equal(retaps(t).length, 0);
    assert.match(t.navigations[0], /client-me/);
  });

  it('флаг выключен: событие не шлётся (поведение как раньше)', () => {
    const t = bootShell({ pathname: '/webapp/client-home' });
    t.win.scrollY = 300;
    t.btn('home').fire('click');
    assert.equal(retaps(t).length, 0);
    assert.equal(t.scrolls.length, 1);
  });
});

/* ── AC-6: смена флага на лету ──────────────────────────────────────────────────────────── */

describe('AC-6: client-shell:ui-flags пересобирает бар', () => {
  const URL_FLAGS = '/api/webapp/client/ui-flags';

  it('кэша нет, сервер включил season_ui: бар заменён на месте, шторка убрана, событие одно', async () => {
    const t = bootShell({ responses: { [URL_FLAGS]: { season_ui: true, bookings_tab: true } } });
    const before = t.bar();
    assert.deepEqual(t.tabIds(), ['home', 'catalog', 'bookings', 'more']);
    assert.ok(t.overlay());
    await t.flush();
    const after = t.bar();
    assert.notEqual(after, before, 'узел пересобран');
    assert.equal(before.parentNode, null, 'старый узел снят');
    assert.equal(after.parentNode, t.doc.body);
    assert.equal(t.doc.body.children.filter((n) => n.id === 'clientTabBar').length, 1);
    assert.deepEqual(t.tabIds(), ['home', 'catalog', 'bookings', 'kk', 'me']);
    assert.equal(t.overlay(), null);
    assert.equal(t.events.filter((e) => e.type === 'client-shell:ui-flags').length, 1);
    assert.deepEqual(t.active(), ['home']);
    assert.equal(t.navigations.length, 0, 'без перезагрузки');
  });

  it('активная вкладка — по текущему маршруту', async () => {
    const t = bootShell({ pathname: '/webapp/client-stats', responses: { [URL_FLAGS]: { season_ui: true, bookings_tab: false } } });
    assert.deepEqual(t.active(), ['more']);
    await t.flush();
    assert.deepEqual(t.active(), ['me']);
  });

  it('сервер выключил season_ui: возвращается старый бар и шторка', async () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, responses: { [URL_FLAGS]: { season_ui: false, bookings_tab: false } } });
    assert.deepEqual(t.tabIds(), ['home', 'catalog', 'bookings', 'kk', 'me']);
    await t.flush();
    assert.equal(t.bar().html(), LEGACY_BAR_HTML);
    assert.equal(t.overlay().html(), LEGACY_OVERLAY_HTML);
  });

  it('bookings_tab вырос — «Записи» появились', async () => {
    const t = bootShell({ flags: SEASON, responses: { [URL_FLAGS]: { season_ui: true, bookings_tab: true } } });
    await t.flush();
    assert.deepEqual(t.tabIds(), ['home', 'catalog', 'bookings', 'kk', 'me']);
  });

  it('без события бар не перерисовывается: сервер подтвердил кэш', async () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, responses: { [URL_FLAGS]: { season_ui: true, bookings_tab: true } } });
    const before = t.bar();
    await t.flush();
    assert.equal(t.events.filter((e) => e.type === 'client-shell:ui-flags').length, 0);
    assert.equal(t.bar(), before, 'тот же узел');
  });

  it('без события бар не перерисовывается: флаг выключен и остался выключенным', async () => {
    const t = bootShell({ responses: { [URL_FLAGS]: { season_ui: false, bookings_tab: false } } });
    const before = t.bar();
    await t.flush();
    assert.equal(t.bar(), before);
  });

  it('вручную посланное событие пересобирает бар по текущим флагам', () => {
    const t = bootShell({ flags: SEASON });
    const before = t.bar();
    t.win.dispatchEvent(new t.win.CustomEvent('client-shell:ui-flags', { detail: {} }));
    assert.notEqual(t.bar(), before);
    assert.deepEqual(t.tabIds(), ['home', 'catalog', 'kk', 'me']);
  });

  it('скрытый бар остаётся скрытым после пересборки', async () => {
    const t = bootShell({ responses: { [URL_FLAGS]: { season_ui: true, bookings_tab: false } } });
    t.win.ClientShell.setTabBarVisible(false);
    await t.flush();
    assert.equal(t.bar().getAttribute('hidden'), 'hidden');
  });
});

/* ── п. 7: страница игры ────────────────────────────────────────────────────────────────── */

describe('п. 7: бар на kto-kogo — только в режиме season', () => {
  it('season: бар смонтирован без data-client-shell, активна «Кто кого»', () => {
    const t = bootShell({ flags: SEASON, pathname: '/webapp/kto-kogo', bodyShell: null });
    assert.ok(t.bar());
    assert.deepEqual(t.active(), ['kk']);
    assert.equal(t.overlay(), null);
  });
  it('без флага на kto-kogo бара нет, как сейчас', () => {
    const t = bootShell({ pathname: '/webapp/kto-kogo', bodyShell: null });
    assert.equal(t.bar(), null);
    assert.equal(t.overlay(), null);
  });
  it('флаг пришёл с сервера — бар появляется на странице игры', async () => {
    const t = bootShell({ pathname: '/webapp/kto-kogo', bodyShell: null, responses: { '/api/webapp/client/ui-flags': { season_ui: true, bookings_tab: false } } });
    assert.equal(t.bar(), null);
    await t.flush();
    assert.deepEqual(t.tabIds(), ['home', 'catalog', 'kk', 'me']);
  });
  it('флаг снят на лету — бар на странице игры исчезает', async () => {
    const t = bootShell({ flags: SEASON, pathname: '/webapp/kto-kogo', bodyShell: null, responses: { '/api/webapp/client/ui-flags': { season_ui: false, bookings_tab: false } } });
    assert.ok(t.bar());
    await t.flush();
    assert.equal(t.bar(), null);
  });
  it('на других страницах без data-client-shell бар не монтируется даже в season', () => {
    const t = bootShell({ flags: SEASON, pathname: '/webapp/trainer-home', bodyShell: null });
    assert.equal(t.bar(), null);
  });
});

/* ── п. 5: предзагрузка ─────────────────────────────────────────────────────────────────── */

describe('п. 5: предзагрузка на pointerdown', () => {
  const prefetched = (t) => t.doc.head.descendants().filter((n) => n.rel === 'prefetch').map((n) => n.href.replace(/^.*\//, '').replace(/\?.*$/, ''));

  it('kk — css и все kto-kogo*.js из kto-kogo.html', () => {
    const html = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/kto-kogo.html'), 'utf8');
    const expected = [...html.matchAll(/\/static\/webapp\/(kto-kogo[\w-]*\.(?:js|css))/g)].map((m) => m[1]);
    assert.ok(expected.length >= 10);
    const t = bootShell({ flags: SEASON });
    t.btn('kk').fire('pointerdown');
    const got = prefetched(t);
    for (const f of expected) assert.ok(got.includes(f), 'не предзагружен ' + f);
    t.btn('kk').fire('pointerdown');
    assert.equal(prefetched(t).length, got.length, 'повторный pointerdown не дублирует ссылки');
  });

  it('kk — адрес и ?v= предзагрузки те же, что у ссылок на странице игры, и это /static/webapp/', () => {
    const html = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/kto-kogo.html'), 'utf8');
    const page = [...html.matchAll(/(?:href|src)="(\/static\/webapp\/kto-kogo[\w-]*\.(?:js|css)\?v=\d+)"/g)].map((m) => m[1]).sort();
    assert.ok(page.length >= 10);
    const t = bootShell({ flags: SEASON });
    t.btn('kk').fire('pointerdown');
    const hrefs = t.doc.head.descendants().filter((n) => n.rel === 'prefetch').map((n) => n.href.replace(/^https?:\/\/[^/]+/, '')).sort();
    assert.deepEqual(hrefs, page);
    assert.ok(hrefs.every((h) => h.startsWith('/static/webapp/')), 'ни одного /webapp/kto-kogo*');
  });

  it('me — client-me.css, client-me.js и тёплый кэш', async () => {
    const payload = { name: 'Максим', tiles: [1, 2] };
    const t = bootShell({ flags: SEASON, responses: { '/api/webapp/client/me': payload } });
    t.btn('me').fire('pointerdown');
    const got = prefetched(t);
    assert.ok(got.includes('client-me.css') && got.includes('client-me.js'));
    await t.flush();
    const warm = JSON.parse(t.session.get('cw_me_warm_v1'));
    assert.deepEqual(warm.data, payload);
    assert.ok(typeof warm.ts === 'number' && Date.now() - warm.ts < 5000);
  });

  it('me — два быстрых тапа дают один запрос; свежий кэш не перезапрашивается', async () => {
    const t = bootShell({ flags: SEASON, responses: { '/api/webapp/client/me': { a: 1 } } });
    t.btn('me').fire('pointerdown');
    t.btn('me').fire('pointerdown');
    await t.flush();
    t.btn('me').fire('pointerdown');
    await t.flush();
    assert.equal(t.fetches.filter((u) => u === '/api/webapp/client/me').length, 1);
  });

  it('me — на самой странице «Я» тёплый кэш не запрашивается (retap спросит страница), с другой — да', async () => {
    const onMe = bootShell({ flags: SEASON, pathname: '/webapp/client-me', responses: { '/api/webapp/client/me': { a: 1 } } });
    onMe.btn('me').fire('pointerdown');
    await onMe.flush();
    assert.equal(onMe.fetches.filter((u) => u === '/api/webapp/client/me').length, 0);
    const other = bootShell({ flags: SEASON, pathname: '/webapp/client-home', responses: { '/api/webapp/client/me': { a: 1 } } });
    other.btn('me').fire('pointerdown');
    await other.flush();
    assert.equal(other.fetches.filter((u) => u === '/api/webapp/client/me').length, 1);
  });

  it('me — ответ с ошибкой кэш не пишет', async () => {
    const t = bootShell({ flags: SEASON });
    t.win.fetch = () => Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    t.btn('me').fire('pointerdown');
    await t.flush();
    assert.equal(t.session.get('cw_me_warm_v1'), undefined);
  });

  it('поиск и записи грузятся как раньше', () => {
    const t = bootShell({ flags: SEASON_BOOKINGS });
    t.btn('catalog').fire('pointerdown');
    t.btn('bookings').fire('pointerdown');
    const got = prefetched(t);
    assert.ok(got.includes('ice-tab.js') && got.includes('catalog-main.js') && got.includes('mini-app-client-bookings.css'));
    assert.ok(t.fetches.includes('/api/webapp/client/session'));
  });

  it('флаг выключен: у кнопок «Ещё» и «Главная» предзагрузки нет, у «Поиска» и «Записей» — как раньше', () => {
    const t = bootShell({});
    t.btn('home').fire('pointerdown');
    t.btn('more').fire('pointerdown');
    assert.equal(prefetched(t).length, 0);
    t.btn('bookings').fire('pointerdown');
    assert.deepEqual(prefetched(t), ['mini-app-client-bookings.css']);
  });
});

/* ── AC-9: клавиатура ───────────────────────────────────────────────────────────────────── */

describe('AC-9: фокус в поле ввода прячет бар', () => {
  it('input text: прячется, расфокус возвращает', () => {
    const t = bootShell({ flags: SEASON });
    const i = t.input('text');
    t.emitDoc('focusin', { target: i });
    assert.ok(t.bar().classList.contains('client-tab-bar--kbd'));
    t.emitDoc('focusout', { target: i, relatedTarget: null });
    assert.ok(!t.bar().classList.contains('client-tab-bar--kbd'));
  });

  it('textarea и input без type', () => {
    const t = bootShell({ flags: SEASON });
    t.emitDoc('focusin', { target: t.input('textarea') });
    assert.ok(t.bar().classList.contains('client-tab-bar--kbd'));
    t.emitDoc('focusout', { target: t.input('textarea'), relatedTarget: null });
    const bare = t.doc.createElement('input');
    t.emitDoc('focusin', { target: bare });
    assert.ok(t.bar().classList.contains('client-tab-bar--kbd'));
  });

  it('содержимое не сдвигается: отступ тела не меняется, класса tabs-hidden нет', () => {
    const t = bootShell({ flags: SEASON });
    t.emitDoc('focusin', { target: t.input('search') });
    assert.ok(!t.doc.body.classList.contains('client-shell-tabs-hidden'));
    assert.equal(t.bar().getAttribute('hidden'), null);
    assert.ok(t.doc.body.classList.contains('client-shell-kbd'), 'гасится только скрим');
    t.emitDoc('focusout', { target: t.input('search'), relatedTarget: null });
    assert.ok(!t.doc.body.classList.contains('client-shell-kbd'));
  });

  it('фокус переходит из поля в поле — бар не мигает', () => {
    const t = bootShell({ flags: SEASON });
    const a = t.input('text');
    const b = t.input('tel');
    t.emitDoc('focusin', { target: a });
    t.emitDoc('focusout', { target: a, relatedTarget: b });
    assert.ok(t.bar().classList.contains('client-tab-bar--kbd'));
    t.emitDoc('focusin', { target: b });
    t.emitDoc('focusout', { target: b, relatedTarget: null });
    assert.ok(!t.bar().classList.contains('client-tab-bar--kbd'));
  });

  it('чекбокс, радио и кнопка клавиатуру не вызывают', () => {
    const t = bootShell({ flags: SEASON });
    for (const type of ['checkbox', 'radio', 'button', 'submit']) {
      t.emitDoc('focusin', { target: t.input(type) });
      assert.ok(!t.bar().classList.contains('client-tab-bar--kbd'), type);
    }
    const div = t.doc.createElement('div');
    t.emitDoc('focusin', { target: div });
    assert.ok(!t.bar().classList.contains('client-tab-bar--kbd'));
  });

  it('флаг выключен: бар не прячется', () => {
    const t = bootShell({});
    t.emitDoc('focusin', { target: t.input('text') });
    assert.ok(!t.bar().classList.contains('client-tab-bar--kbd'));
    assert.ok(!t.doc.body.classList.contains('client-shell-kbd'));
  });

  it('пересборка бара при открытой клавиатуре не оставляет бар спрятанным', async () => {
    const t = bootShell({ flags: SEASON, responses: { '/api/webapp/client/ui-flags': { season_ui: true, bookings_tab: true } } });
    t.emitDoc('focusin', { target: t.input('text') });
    await t.flush();
    assert.ok(!t.bar().classList.contains('client-tab-bar--kbd'));
    assert.ok(!t.doc.body.classList.contains('client-shell-kbd'));
  });
});

/* ── направление перехода (TASK-094) в season ───────────────────────────────────────────── */

describe('направление view transition в season', () => {
  const dir = (t) => t.session.get('tcb_nav_dir_v1');
  it('вправо по порядку вкладок — forward, влево — back', () => {
    let t = bootShell({ flags: SEASON, pathname: '/webapp/client-home' });
    t.btn('kk').fire('click');
    assert.equal(dir(t), 'forward');
    t = bootShell({ flags: SEASON, pathname: '/webapp/kto-kogo' });
    t.btn('home').fire('click');
    assert.equal(dir(t), 'back');
    t = bootShell({ flags: SEASON, pathname: '/webapp/client-me' });
    t.btn('kk').fire('click');
    assert.equal(dir(t), 'back');
  });
  it('флаг выключен: порядок прежний (kto-kogo не вкладка — всегда forward)', () => {
    const t = bootShell({ pathname: '/webapp/client-bookings' });
    t.btn('home').fire('click');
    assert.equal(dir(t), 'back');
  });
});

/* Снимок снят с оболочки до TASK-369 (epic/your-season @ dc6d07b2), флаг выключен. */
const LEGACY_BAR_HTML =
    "<nav class=\"client-tab-bar\" id=\"clientTabBar\" role=\"tablist\" aria-label=\"Навигация\">" +
    "<button class=\"client-tab-bar__btn ga-press client-tab-bar__btn--active\" type=\"button\" role=\"tab\" aria-selected=\"true\" data-tab-id=\"home\">" +
    "<span class=\"client-tab-bar__icon-wrap\">" +
    "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<path d=\"M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V9.5z\"/>" +
    "</svg>" +
    "</span>" +
    "<span>Главная</span>" +
    "</button>" +
    "<button class=\"client-tab-bar__btn ga-press\" type=\"button\" role=\"tab\" aria-selected=\"false\" data-tab-id=\"catalog\">" +
    "<span class=\"client-tab-bar__icon-wrap\">" +
    "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<circle cx=\"11\" cy=\"11\" r=\"7\"/>" +
    "<path d=\"m20 20-3.9-3.9\"/>" +
    "</svg>" +
    "</span>" +
    "<span>Поиск</span>" +
    "</button>" +
    "<button class=\"client-tab-bar__btn ga-press\" type=\"button\" role=\"tab\" aria-selected=\"false\" data-tab-id=\"bookings\">" +
    "<span class=\"client-tab-bar__icon-wrap\">" +
    "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<rect x=\"3\" y=\"4\" width=\"18\" height=\"18\" rx=\"2\"/>" +
    "<path d=\"M16 2v4M8 2v4M3 10h18\"/>" +
    "</svg>" +
    "</span>" +
    "<span>Записи</span>" +
    "</button>" +
    "<button class=\"client-tab-bar__btn ga-press\" type=\"button\" role=\"tab\" aria-selected=\"false\" data-tab-id=\"more\">" +
    "<span class=\"client-tab-bar__icon-wrap\">" +
    "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<circle cx=\"12\" cy=\"5\" r=\"1.5\" fill=\"currentColor\" stroke=\"none\"/>" +
    "<circle cx=\"12\" cy=\"12\" r=\"1.5\" fill=\"currentColor\" stroke=\"none\"/>" +
    "<circle cx=\"12\" cy=\"19\" r=\"1.5\" fill=\"currentColor\" stroke=\"none\"/>" +
    "</svg>" +
    "</span>" +
    "<span>Ещё</span>" +
    "</button>" +
    "</nav>";
const LEGACY_OVERLAY_HTML =
    "<div class=\"client-more-sheet-overlay\" id=\"clientMoreOverlay\">" +
    "<div class=\"client-more-sheet\" id=\"clientMoreSheet\" role=\"dialog\" aria-label=\"Дополнительные разделы\" data-dismiss-wired=\"1\">" +
    "<div class=\"client-more-sheet__handle\" role=\"button\" tabindex=\"0\" aria-label=\"Свернуть раздел «Ещё»\">" +
    "</div>" +
    "<h2 class=\"client-more-sheet__title\">Ещё</h2>" +
    "<p class=\"client-more-sheet__subtitle\">Избранное, абонементы, семья и заявки — всё, что не в нижних вкладках</p>" +
    "<ul class=\"client-more-sheet__list\">" +
    "<li class=\"client-more-sheet__item\">" +
    "<button class=\"client-more-sheet__link\" type=\"button\">" +
    "<span class=\"glide-more-plate\" aria-hidden=\"true\">" +
    "</span>" +
    "<span class=\"client-more-sheet__body\">" +
    "<span class=\"client-more-sheet__label\">Кто кого</span>" +
    "<span class=\"client-more-sheet__hint\">Угадывай матчи Динамо и Экстралиги</span>" +
    "</span>" +
    "<svg class=\"client-more-sheet__chevron\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<path d=\"M9 6l6 6-6 6\"/>" +
    "</svg>" +
    "</button>" +
    "</li>" +
    "<li class=\"client-more-sheet__item\">" +
    "<button class=\"client-more-sheet__link\" type=\"button\">" +
    "<span class=\"glide-more-plate\" aria-hidden=\"true\">" +
    "</span>" +
    "<span class=\"client-more-sheet__body\">" +
    "<span class=\"client-more-sheet__label\">Сохранённые</span>" +
    "<span class=\"client-more-sheet__hint\">Тренеры, катки и активные напоминания</span>" +
    "</span>" +
    "<svg class=\"client-more-sheet__chevron\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<path d=\"M9 6l6 6-6 6\"/>" +
    "</svg>" +
    "</button>" +
    "</li>" +
    "<li class=\"client-more-sheet__item\">" +
    "<button class=\"client-more-sheet__link\" type=\"button\">" +
    "<span class=\"glide-more-plate\" aria-hidden=\"true\">" +
    "</span>" +
    "<span class=\"client-more-sheet__body\">" +
    "<span class=\"client-more-sheet__label\">Ваша активность</span>" +
    "<span class=\"client-more-sheet__hint\">Серия тренировок и статистика сезона</span>" +
    "</span>" +
    "<svg class=\"client-more-sheet__chevron\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<path d=\"M9 6l6 6-6 6\"/>" +
    "</svg>" +
    "</button>" +
    "</li>" +
    "<li class=\"client-more-sheet__item\">" +
    "<button class=\"client-more-sheet__link\" type=\"button\">" +
    "<span class=\"glide-more-plate\" aria-hidden=\"true\">" +
    "</span>" +
    "<span class=\"client-more-sheet__body\">" +
    "<span class=\"client-more-sheet__label\">Абонементы</span>" +
    "<span class=\"client-more-sheet__hint\">Сколько занятий осталось и подарочные сертификаты</span>" +
    "</span>" +
    "<svg class=\"client-more-sheet__chevron\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<path d=\"M9 6l6 6-6 6\"/>" +
    "</svg>" +
    "</button>" +
    "</li>" +
    "<li class=\"client-more-sheet__item\">" +
    "<button class=\"client-more-sheet__link\" type=\"button\">" +
    "<span class=\"glide-more-plate\" aria-hidden=\"true\">" +
    "</span>" +
    "<span class=\"client-more-sheet__body\">" +
    "<span class=\"client-more-sheet__label\">Семейный доступ</span>" +
    "<span class=\"client-more-sheet__hint\">Близкие в одном аккаунте — записи и абонементы вместе</span>" +
    "</span>" +
    "<svg class=\"client-more-sheet__chevron\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<path d=\"M9 6l6 6-6 6\"/>" +
    "</svg>" +
    "</button>" +
    "</li>" +
    "<li class=\"client-more-sheet__item\">" +
    "<button class=\"client-more-sheet__link\" type=\"button\">" +
    "<span class=\"glide-more-plate\" aria-hidden=\"true\">" +
    "</span>" +
    "<span class=\"client-more-sheet__body\">" +
    "<span class=\"client-more-sheet__label\">Мои заявки</span>" +
    "<span class=\"client-more-sheet__hint\">Запрос на подбор тренера и ответы специалистов</span>" +
    "</span>" +
    "<svg class=\"client-more-sheet__chevron\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<path d=\"M9 6l6 6-6 6\"/>" +
    "</svg>" +
    "</button>" +
    "</li>" +
    "<li class=\"client-more-sheet__item\">" +
    "<button class=\"client-more-sheet__link\" type=\"button\">" +
    "<span class=\"glide-more-plate\" aria-hidden=\"true\">" +
    "</span>" +
    "<span class=\"client-more-sheet__body\">" +
    "<span class=\"client-more-sheet__label\">Идеи и поддержка</span>" +
    "<span class=\"client-more-sheet__hint\">Напишите, чего не хватает, — мы читаем каждое сообщение</span>" +
    "</span>" +
    "<svg class=\"client-more-sheet__chevron\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">" +
    "<path d=\"M9 6l6 6-6 6\"/>" +
    "</svg>" +
    "</button>" +
    "</li>" +
    "</ul>" +
    "</div>" +
    "</div>";
