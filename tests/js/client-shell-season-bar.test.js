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
  const re = /^([a-z0-9]+)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:(\*?)="([^"]*)")?\]/gi;
  let m;
  while ((m = re.exec(sel))) {
    if (m[1]) out.tag = m[1].toLowerCase();
    else if (m[2]) out.id = m[2];
    else if (m[3]) out.classes.push(m[3]);
    else out.attrs.push([m[4], m[6], m[5] === '*']);
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
    return s.attrs.every(([k, v, sub]) => this.attrs.has(k) && (v === undefined || (sub ? this.attrs.get(k).includes(v) : this.attrs.get(k) === v)));
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

function bootShell({ pathname = '/webapp/client-home', search = '', flags, bodyShell = 'tabs', userId = 42, responses = {}, connection = null, readyState = 'complete', fetchAll = false, fetchFail = null, scriptSrc = null, winExtra = null } = {}) {
  const store = new Map();
  if (flags) store.set(FLAGS_KEY, JSON.stringify(Object.assign({ u: String(userId), at: Date.now() }, flags)));
  const session = new Map();
  const docListeners = {};
  const winListeners = {};
  const events = [];
  const fetches = [];
  const fetchOpts = [];
  const scrolls = [];
  const navigations = [];
  const timers = [];

  const doc = { readyState };
  if (scriptSrc) doc.currentScript = { src: scriptSrc };
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
    navigator: connection ? { connection } : {},
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
    fetch(url, opts) {
      fetches.push(url);
      fetchOpts.push(opts);
      if (fetchFail && fetchFail(url)) return Promise.reject(new Error('network'));
      if (fetchAll && url === '/api/webapp/client/ui-flags' && !Object.prototype.hasOwnProperty.call(responses, url)) return new Promise(() => {});
      if (fetchAll && !Object.prototype.hasOwnProperty.call(responses, url)) {
        const text = typeof fetchAll === 'object' && fetchAll[url] ? fetchAll[url] : '';
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({}),
          text: () => Promise.resolve(text),
          arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
        });
      }
      if (Object.prototype.hasOwnProperty.call(responses, url)) {
        const body = responses[url];
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(body),
          text: () => Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body)),
          arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
        });
      }
      return new Promise(() => {});
    },
  };
  win.window = win;
  if (winExtra) Object.assign(win, winExtra);
  const ctx = vm.createContext({
    URL, URLSearchParams, JSON, Date, Promise, Number, String, Object, Array, Math, console,
    window: win, document: doc, location: win.location, history: win.history, Telegram: win.Telegram,
    sessionStorage: win.sessionStorage, localStorage: win.localStorage, addEventListener: win.addEventListener,
    fetch: win.fetch, setTimeout: win.setTimeout, fetchLog: fetches,
  });
  vm.runInContext(shellSrc, ctx);
  return {
    win, doc, store, session, events, fetches, fetchOpts, scrolls, navigations,
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
  /* TASK-395: подгрузка идёт через fetch (а не <link rel=prefetch>), ассеты — всё, что не /api/. */
  const prefetched = (t) => t.fetches.filter((u) => !u.startsWith('/api/')).map((n) => n.replace(/^.*\//, '').replace(/\?.*$/, ''));

  it('kk — css и все kto-kogo*.js из kto-kogo.html', () => {
    const html = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/kto-kogo.html'), 'utf8');
    const expected = [...html.matchAll(/\/static\/webapp\/(kto-kogo[\w-]*\.(?:js|css))/g)].map((m) => m[1]);
    assert.ok(expected.length >= 10);
    const t = bootShell({ flags: SEASON });
    t.btn('kk').fire('pointerdown');
    const got = prefetched(t);
    for (const f of expected) assert.ok(got.includes(f), 'не предзагружен ' + f);
    t.btn('kk').fire('pointerdown');
    assert.equal(prefetched(t).length, got.length, 'повторный pointerdown не дублирует запросы');
  });

  it('kk — адрес и ?v= предзагрузки те же, что у ссылок на странице игры, и это /static/webapp/', () => {
    const html = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/kto-kogo.html'), 'utf8');
    const page = [...html.matchAll(/(?:href|src)="(\/static\/webapp\/kto-kogo[\w-]*\.(?:js|css)\?v=\d+)"/g)].map((m) => m[1]).sort();
    assert.ok(page.length >= 10);
    const t = bootShell({ flags: SEASON });
    t.btn('kk').fire('pointerdown');
    const hrefs = t.fetches.filter((u) => !u.startsWith('/api/')).sort();
    assert.deepEqual(hrefs, page);
    assert.ok(hrefs.every((h) => h.startsWith('/static/webapp/')), 'ни одного /webapp/kto-kogo*');
  });

  it('kk — версия берётся у самой оболочки: сервер штампует ?v= во всех страницах одной меткой', () => {
    const t = bootShell({ flags: SEASON, scriptSrc: 'https://test/webapp/mini-app-client-shell.js?v=128573828630199' });
    t.btn('kk').fire('pointerdown');
    const hrefs = t.fetches.filter((u) => !u.startsWith('/api/'));
    assert.ok(hrefs.length >= 10);
    assert.ok(hrefs.every((h) => h.startsWith('/static/webapp/kto-kogo') && h.endsWith('?v=128573828630199')), hrefs.join());
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

/* ── TASK-395: фоновая подгрузка соседних вкладок через fetch (iPhone/WebKit не знает rel=prefetch) ── */

describe('TASK-395: фоновая подгрузка вкладок', () => {
  const assets = (t) => t.fetches.filter((u) => !u.startsWith('/api/')).map((u) => u.replace(/^.*\//, '').replace(/\?.*$/, ''));
  const drain = async (t) => { for (let i = 0; i < 40; i++) await t.flush(); };
  const links = (t) => t.doc.head.descendants().filter((n) => n.rel === 'prefetch' || n.rel === 'preload');

  it('с Главной подгружаются Поиск, Кто кого и Я; ни одного <link rel=prefetch>', async () => {
    const t = bootShell({ flags: SEASON, fetchAll: true });
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    const got = assets(t);
    for (const f of ['ice-tab.js', 'ice-tab.css', 'catalog-main.js', 'kto-kogo.js', 'kto-kogo.css', 'client-me.js', 'client-me.css']) {
      assert.ok(got.includes(f), 'не подгружен ' + f);
    }
    assert.ok(!got.includes('mini-app-client-bookings.css'), 'вкладки «Записи» нет — её ассеты не нужны');
    assert.equal(links(t).length, 0);
  });

  it('вкладка «Записи» есть — её ассеты подгружаются тоже', async () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, fetchAll: true });
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    assert.ok(assets(t).includes('mini-app-client-bookings.css'));
  });

  it('по одной вкладке подряд: пока простой не наступил, следующая не стартует', async () => {
    const t = bootShell({ flags: SEASON, fetchAll: true });
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    assert.equal(assets(t).length, 0, 'до простоя ничего не качается');
    await t.flush();
    const first = assets(t);
    assert.ok(first.includes('ice-tab.js'));
    assert.ok(!first.includes('kto-kogo.js') && !first.includes('client-me.js'), 'за один шаг — одна вкладка');
    await drain(t);
    assert.ok(assets(t).includes('client-me.js'));
  });

  it('текущая вкладка не подгружается', async () => {
    const t = bootShell({ flags: SEASON, pathname: '/webapp/kto-kogo', bodyShell: null, fetchAll: true });
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    const got = assets(t);
    assert.ok(!got.some((f) => /^kto-kogo/.test(f)), 'kto-kogo*: ' + got.join());
    assert.ok(got.includes('ice-tab.js') && got.includes('client-me.js'));
  });

  it('используется fetch с same-origin и низким приоритетом; повтор — без второго запроса', async () => {
    const t = bootShell({ flags: SEASON, fetchAll: true });
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    const n = t.fetches.filter((u) => /client-me\.js/.test(u)).length;
    assert.equal(n, 1);
    t.btn('me').fire('pointerdown');
    t.btn('kk').fire('pointerdown');
    await t.flush();
    assert.equal(t.fetches.filter((u) => /client-me\.js/.test(u)).length, 1, 'после фона pointerdown не качает заново');
    const idx = t.fetches.findIndex((u) => /ice-tab\.js/.test(u));
    assert.equal(JSON.stringify(t.fetchOpts[idx]), JSON.stringify({ credentials: 'same-origin', priority: 'low' }));
    assert.equal(links(t).length, 0);
  });

  it('pointerdown раньше фона: фон не качает то же второй раз', async () => {
    const t = bootShell({ flags: SEASON, fetchAll: true });
    t.btn('me').fire('pointerdown');
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    assert.equal(t.fetches.filter((u) => /client-me\.js/.test(u)).length, 1);
  });

  it('saveData — фон молчит, касание вкладки по-прежнему подгружает её', async () => {
    const t = bootShell({ flags: SEASON, fetchAll: true, connection: { saveData: true, effectiveType: '4g' } });
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    assert.equal(assets(t).length, 0);
    t.btn('me').fire('pointerdown');
    assert.ok(assets(t).includes('client-me.js'));
  });

  for (const type of ['2g', 'slow-2g']) {
    it('effectiveType ' + type + ' — фон молчит', async () => {
      const t = bootShell({ flags: SEASON, fetchAll: true, connection: { saveData: false, effectiveType: type } });
      t.win.ClientShell.scheduleCatalogNavigationPrefetch();
      await drain(t);
      assert.equal(assets(t).length, 0);
    });
  }

  it('3g и 4g — подгрузка идёт', async () => {
    for (const type of ['3g', '4g']) {
      const t = bootShell({ flags: SEASON, fetchAll: true, connection: { saveData: false, effectiveType: type } });
      t.win.ClientShell.scheduleCatalogNavigationPrefetch();
      await drain(t);
      assert.ok(assets(t).includes('client-me.js'), type);
    }
  });

  it('страница ещё грузится — фон ждёт load', async () => {
    const t = bootShell({ flags: SEASON, fetchAll: true, readyState: 'loading' });
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    assert.equal(assets(t).length, 0);
    t.win.dispatchEvent({ type: 'load' });
    await drain(t);
    assert.ok(assets(t).includes('client-me.js'));
  });

  it('ошибка сети глотается и не рвёт цепочку; неудачный адрес можно запросить снова', async () => {
    const t = bootShell({ flags: SEASON, fetchAll: true, fetchFail: (u) => /ice-tab\.js/.test(u) });
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    assert.ok(assets(t).includes('client-me.js'), 'следующие вкладки подгрузились');
    t.win.ClientShell.prefetchIceAssets();
    await t.flush();
    assert.equal(t.fetches.filter((u) => /ice-tab\.js/.test(u)).length, 2, 'после сбоя адрес не помечен как загруженный');
  });

  it('флаг выключен: прежний набор (каталог, записи, страница записи) через fetch, без «Кто кого» и «Я»', async () => {
    const t = bootShell({ fetchAll: true });
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    const got = assets(t);
    for (const f of ['ice-tab.js', 'catalog-main.js', 'mini-app-client-bookings.css', 'mini-app-phone-field.js']) {
      assert.ok(got.includes(f), 'нет ' + f);
    }
    assert.ok(!got.some((f) => /^kto-kogo|^client-me/.test(f)));
    assert.ok(!got.includes('book') && !t.fetches.some((u) => /nav\.css/.test(u)), 'no-store страницы в фон не качаем');
    assert.equal(links(t).length, 0);
  });

  it('шрифты: адреса берутся из glide-public-fonts.css (с версией шрифтов от сервера), все начертания', async () => {
    const css = "@font-face{src:url('/static/fonts/glide-public/dela-gothic-one-cyr-lat.woff2?v=777') format('woff2')}" +
      "@font-face{src:url('/static/fonts/glide-public/golos-text-cyr-lat-500.woff2?v=777') format('woff2')}" +
      "@font-face{src:url('/static/fonts/glide-public/golos-text-lat-500.woff2?v=777') format('woff2')}";
    const t = bootShell({ flags: SEASON, fetchAll: { '/static/shared/glide-public-fonts.css?v=1': css } });
    const sheet = t.doc.createElement('link');
    sheet.rel = 'stylesheet';
    sheet.href = '/static/shared/glide-public-fonts.css?v=1';
    t.doc.head.appendChild(sheet);
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    for (const f of ['dela-gothic-one-cyr-lat', 'golos-text-cyr-lat-500', 'golos-text-lat-500']) {
      assert.ok(t.fetches.includes('/static/fonts/glide-public/' + f + '.woff2?v=777'), f);
    }
    assert.equal(t.fetches.filter((u) => /glide-public-fonts\.css/.test(u)).length, 1, 'css запрошен один раз');
  });

  it('общие файлы страниц «Кто кого» и «Я», у которых адрес не как на Главной, подгружаются в фоне, но не на касании', async () => {
    const t = bootShell({ flags: SEASON, fetchAll: true, scriptSrc: 'https://test/webapp/mini-app-client-shell.js?v=555' });
    t.btn('kk').fire('pointerdown');
    t.btn('me').fire('pointerdown');
    const tap = t.fetches.filter((u) => !u.startsWith('/api/'));
    assert.ok(!tap.some((u) => /write-access|client-sheet|minsk-time/.test(u)), 'на касании только основные ассеты');
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    for (const u of ['/static/webapp/mini-app-client-shell.js?v=555', '/static/webapp/mini-app-client-shell.css?v=555', '/static/webapp/write-access.js?v=555',
      '/static/webapp/client-sheet.js?v=555', '/static/webapp/client-rink-sheet.js?v=555', '/webapp/minsk-time.js?v=555', '/webapp/glide-copy.js?v=555']) {
      assert.ok(t.fetches.includes(u), 'не подгружен ' + u);
    }
  });

  it('списки файлов «Я» сверены со страницей client-me.html: всё подгружаемое там есть', async () => {
    const html = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/client-me.html'), 'utf8');
    const page = [...html.matchAll(/(?:href|src)="([^"?]+\.(?:js|css))\?v=\d+"/g)].map((m) => m[1].replace(/^.*\//, ''));
    const t = bootShell({ flags: SEASON, fetchAll: true });
    t.btn('me').fire('pointerdown');
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await drain(t);
    const fetched = t.fetches.filter((u) => /\/(client-me|client-sheet|client-club-sheet|client-name-sheet|client-rink-sheet|minsk-time|opening-hours|glide-copy|public-display-model)[\w.-]*\.(js|css)/.test(u));
    assert.ok(fetched.length >= 9, fetched.join());
    for (const u of fetched) {
      const f = u.replace(/^.*\//, '').replace(/\?.*$/, '');
      assert.ok(page.includes(f), f + ' нет на странице client-me.html — список в шелле устарел');
    }
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
  it('TASK-391: переход на страницу без opt-in (Кто кого, тренеры) не начинается — без InvalidStateError', () => {
    const t = bootShell({ flags: SEASON, winExtra: { onpageswap: null } });
    const swap = (url) => {
      let skipped = 0;
      const ev = { type: 'pageswap', viewTransition: { skipTransition() { skipped++; } }, activation: { entry: { url } } };
      t.win.dispatchEvent(ev);
      return skipped;
    };
    assert.equal(swap('https://test/webapp/kto-kogo?init_data=x'), 1);
    assert.equal(swap('https://test/webapp/trainers?trainer_id=3'), 1);
    assert.equal(swap('https://test/webapp/client-me?init_data=x'), 0);
    assert.equal(swap('https://test/webapp/ice'), 0);
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

describe('отклик бара на нажатие', () => {
  const css = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/mini-app-client-shell.css'), 'utf8');

  it('жмётся плашка значка по :active, .ga-pressed и .b-press; сама кнопка не двигается', () => {
    const icon = css.match(/\.client-tab-bar--season \.client-tab-bar__btn:is\(:active, \.ga-pressed, \.b-press\) \.client-tab-bar__icon-wrap \{([^}]*)\}/);
    assert.ok(icon, 'правило плашки значка');
    assert.match(icon[1], /transform:\s*scale\(0\.84\)/);
    const btn = css.match(/\.client-tab-bar--season \.client-tab-bar__btn:is\(:active, \.ga-pressed, \.b-press\) \{([^}]*)\}/);
    assert.ok(btn, 'правило кнопки');
    assert.match(btn[1], /transform:\s*none\s*!important/);
  });

  it('подсветка плашки только у неактивных вкладок: активная не мигает цветом', () => {
    assert.match(css, /__btn:not\(\.client-tab-bar__btn--active\):is\(:active, \.ga-pressed, \.b-press\) \.client-tab-bar__icon-wrap \{[^}]*background:\s*var\(--g-chip\)/);
  });

  it('кнопки бара остаются .ga-press: ga-press.js ставит им .ga-pressed', () => {
    assert.match(shellSrc, /client-tab-bar__btn ga-press/);
  });
});

/* ── TASK-390: вкладка активна под пальцем, переход по click ───────────────────────────── */

describe('TASK-390: активное состояние на pointerdown', () => {
  const down = (t, id, ev) => t.btn(id).fire('pointerdown', Object.assign({ pointerId: 1, clientX: 10, clientY: 10, button: 0, isPrimary: true }, ev));
  const switching = (t) => t.bar().classList.contains('client-tab-bar--switching');
  const selected = (t) => t.bar().querySelectorAll('.client-tab-bar__btn').filter((b) => b.getAttribute('aria-selected') === 'true').map((b) => b.dataset.tabId);

  it('season: касание «Кто кого» — активна сразу она, бар в режиме переключения; click уводит, подсветка остаётся', async () => {
    const t = bootShell({ flags: SEASON });
    down(t, 'kk');
    assert.deepEqual(t.active(), ['kk']);
    assert.deepEqual(selected(t), ['kk']);
    assert.ok(switching(t));
    assert.equal(t.navigations.length, 0, 'на pointerdown перехода нет');
    t.btn('kk').fire('click');
    assert.equal(t.navigations.length, 1);
    assert.match(t.navigations[0], /kto-kogo/);
    await t.flush();
    assert.deepEqual(t.active(), ['kk'], 'до выгрузки страницы бар не откатывается');
    assert.ok(!switching(t), 'класс анимации снят после переключения');
  });

  it('направление перехода считается от текущей страницы, а не от подсветки', () => {
    const t = bootShell({ flags: SEASON, pathname: '/webapp/kto-kogo' });
    down(t, 'home');
    t.btn('home').fire('click');
    assert.equal(t.session.get('tcb_nav_dir_v1'), 'back');
  });

  it('палец уехал больше 8 px — подсветка возвращается, перехода нет', () => {
    const t = bootShell({ flags: SEASON });
    down(t, 'me');
    t.emitDoc('pointermove', { pointerId: 1, clientX: 12, clientY: 15 });
    assert.deepEqual(t.active(), ['me'], 'дрожание пальца не отменяет');
    t.emitDoc('pointermove', { pointerId: 1, clientX: 10, clientY: -30 });
    assert.deepEqual(t.active(), ['home']);
    assert.equal(t.navigations.length, 0);
  });

  it('pointercancel (прокрутка, системный жест) — откат', () => {
    const t = bootShell({ flags: SEASON });
    down(t, 'catalog');
    t.emitDoc('pointercancel', { pointerId: 1 });
    assert.deepEqual(t.active(), ['home']);
  });

  it('pointerup без click — откат по таймеру; чужой палец не считается', async () => {
    const t = bootShell({ flags: SEASON });
    down(t, 'catalog');
    t.emitDoc('pointercancel', { pointerId: 2 });
    assert.deepEqual(t.active(), ['catalog']);
    t.emitDoc('pointerup', { pointerId: 1 });
    assert.deepEqual(t.active(), ['catalog'], 'click ещё может прийти');
    await t.flush();
    assert.deepEqual(t.active(), ['home']);
  });

  it('click после pointerup отменяет откат', async () => {
    const t = bootShell({ flags: SEASON });
    down(t, 'catalog');
    t.emitDoc('pointerup', { pointerId: 1 });
    t.btn('catalog').fire('click');
    await t.flush();
    assert.deepEqual(t.active(), ['catalog']);
    assert.equal(t.navigations.length, 1);
  });

  it('касание активной вкладки ничего не переключает (это повтор — наверх)', () => {
    const t = bootShell({ flags: SEASON });
    t.win.scrollY = 400;
    down(t, 'home');
    assert.deepEqual(t.active(), ['home']);
    assert.ok(!switching(t));
    t.btn('home').fire('click');
    assert.equal(t.navigations.length, 0);
    assert.equal(JSON.stringify(t.scrolls), JSON.stringify([{ top: 0, behavior: 'smooth' }]));
  });

  it('правая кнопка мыши и второй палец не подсвечивают', () => {
    const t = bootShell({ flags: SEASON });
    down(t, 'kk', { button: 2 });
    down(t, 'me', { isPrimary: false });
    assert.deepEqual(t.active(), ['home']);
  });

  it('click без pointerdown (клавиатура) тоже подсвечивает перед уходом', () => {
    const t = bootShell({ flags: SEASON });
    t.btn('me').fire('click');
    assert.deepEqual(t.active(), ['me']);
    assert.equal(t.navigations.length, 1);
  });

  it('возврат из bfcache (pageshow persisted) — бар по адресу, без анимации', () => {
    const t = bootShell({ flags: SEASON });
    down(t, 'kk');
    t.btn('kk').fire('click');
    t.win.dispatchEvent({ type: 'pageshow', persisted: true });
    assert.deepEqual(t.active(), ['home']);
    assert.ok(!switching(t));
  });

  it('обычный pageshow (не из кэша) ничего не трогает', () => {
    const t = bootShell({ flags: SEASON });
    down(t, 'kk');
    t.win.dispatchEvent({ type: 'pageshow', persisted: false });
    assert.deepEqual(t.active(), ['kk']);
  });

  it('вибрация selectionChanged — один раз на нажатие, без SDK — тишина', () => {
    const t = bootShell({ flags: SEASON });
    let n = 0;
    t.win.Telegram.WebApp.HapticFeedback = { selectionChanged() { n++; } };
    down(t, 'kk');
    t.btn('kk').fire('click');
    assert.equal(n, 1);
    const t2 = bootShell({ flags: SEASON });
    assert.doesNotThrow(() => { down(t2, 'kk'); t2.btn('kk').fire('click'); });
  });

  it('загрузка страницы: бар сразу в конечном состоянии, без класса анимации', () => {
    const t = bootShell({ flags: SEASON, pathname: '/webapp/kto-kogo', bodyShell: null });
    assert.deepEqual(t.active(), ['kk']);
    assert.ok(!switching(t));
  });
});

describe('TASK-390: старый бар (флаг выключен)', () => {
  const down = (t, id) => t.btn(id).fire('pointerdown', { pointerId: 1, clientX: 10, clientY: 10, button: 0, isPrimary: true });

  it('касание «Поиска» подсвечивает его сразу; отмена возвращает разметку байт в байт', async () => {
    const t = bootShell({});
    down(t, 'catalog');
    assert.deepEqual(t.active(), ['catalog']);
    t.emitDoc('pointercancel', { pointerId: 1 });
    await t.flush();
    assert.equal(t.bar().html(), LEGACY_BAR_HTML);
  });

  it('«Ещё» на pointerdown не подсвечивается: шторку открывает click, как раньше', () => {
    const t = bootShell({});
    down(t, 'more');
    assert.deepEqual(t.active(), ['home']);
    t.btn('more').fire('click');
    assert.deepEqual(t.active(), ['home', 'more']);
  });

  it('страница из «Ещё»: касание «Главной» гасит «Ещё»', () => {
    const t = bootShell({ pathname: '/webapp/client-requests' });
    assert.deepEqual(t.active(), ['more']);
    down(t, 'home');
    assert.deepEqual(t.active(), ['home']);
    t.emitDoc('pointercancel', { pointerId: 1 });
    assert.deepEqual(t.active(), ['more']);
  });
});

describe('TASK-390: CSS плашки', () => {
  const css = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/mini-app-client-shell.css'), 'utf8');

  it('плашка — ::before с размерами макета: 52 px при четырёх вкладках, 48 при пяти', () => {
    const base = css.match(/\.client-tab-bar--season \.client-tab-bar__icon-wrap::before \{([^}]*)\}/);
    assert.ok(base);
    assert.match(base[1], /width:\s*52px/);
    assert.match(base[1], /background:\s*var\(--g-accent\)/);
    assert.match(css, /\.client-tab-bar--n5 \.client-tab-bar__icon-wrap::before \{[^}]*width:\s*48px/);
  });

  it('анимация только под --switching и только opacity/transform', () => {
    const rules = css.match(/[^}]*::before \{[^}]*transition:[^}]*\}/g) || [];
    const anim = rules.filter((r) => !/prefers-reduced-motion/.test(r) && /transition:\s*opacity/.test(r));
    assert.equal(anim.length, 1);
    assert.match(anim[0], /\.client-tab-bar--switching/);
    assert.ok(!/width|left|margin/.test(anim[0].split('transition:')[1]));
  });

  it('prefers-reduced-motion выключает переход плашки', () => {
    const rm = css.slice(css.lastIndexOf('@media (prefers-reduced-motion: reduce)'));
    assert.match(rm, /--switching \.client-tab-bar__icon-wrap::before \{ transition: none; \}/);
  });
});

/* ── TASK-391: оболочка вкладок (client-tabs.js) подключена к шеллу ──────────────────────── */

describe('TASK-391: шелл отдаёт вкладки оболочки роутеру', () => {
  const fakeTabs = (t, { take = true, mounted = [] } = {}) => {
    const calls = [];
    t.win.ClientTabs = {
      hosted: true,
      hosts: (id) => id === 'me' || id === 'bookings',
      isMounted: (id) => mounted.includes(id),
      go: (p) => { calls.push('go:' + p); return take; },
      prefetch: (id) => { calls.push('prefetch:' + id); return Promise.resolve(); },
    };
    return calls;
  };

  it('нажатие на вкладку оболочки — без перезагрузки, через ClientTabs.go', () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-me' });
    const calls = fakeTabs(t);
    t.btn('bookings').fire('click');
    assert.deepEqual(calls, ['go:client-bookings']);
    assert.equal(t.navigations.length, 0);
    assert.equal(t.session.get('tcb_nav_dir_v1'), undefined, 'направление view transition не пишется');
  });

  it('роутер не взял (не его вкладка, сбой) или переход replace — полная загрузка, как без флага', () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-me' });
    fakeTabs(t, { take: false });
    t.btn('kk').fire('click');
    assert.equal(t.navigations.length, 1);
    const t2 = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-me' });
    const calls = fakeTabs(t2);
    t2.win.ClientShell.navigate('client-bookings', { replace: true });
    assert.deepEqual(calls, []);
    assert.equal(t2.navigations.length, 1);
  });

  it('без ClientTabs (флаг выключен) navigate — как раньше', () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-me' });
    t.btn('bookings').fire('click');
    assert.equal(t.navigations.length, 1);
    assert.match(t.navigations[0], /client-bookings/);
  });

  it('pointerdown на невыгруженную вкладку оболочки: фрагмент и данные, не старые ассеты; живая — ничего', async () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-me', fetchAll: true });
    const calls = fakeTabs(t);
    t.btn('bookings').fire('pointerdown');
    await t.flush();
    assert.deepEqual(calls, ['prefetch:bookings']);
    assert.ok(t.fetches.includes('/api/webapp/client/bookings'), 'тёплый кэш записей');
    assert.ok(!t.fetches.some((u) => /mini-app-client-bookings\.css/.test(u)), 'ассеты берёт фрагмент');
    const t2 = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-me', fetchAll: true });
    const calls2 = fakeTabs(t2, { mounted: ['bookings'] });
    t2.btn('bookings').fire('pointerdown');
    await t2.flush();
    assert.deepEqual(calls2, []);
    assert.ok(!t2.fetches.includes('/api/webapp/client/bookings'));
  });

  it('в оболочке соседняя вкладка — первый шаг, каталог ещё не начат', async () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-me', fetchAll: true });
    const calls = fakeTabs(t);
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    await t.flush();
    assert.deepEqual(calls, ['prefetch:bookings']);
    assert.ok(!t.fetches.some((u) => /ice-tab\.js/.test(u)), 'каталог ждёт, пока прогреется вкладка оболочки');
  });

  it('фоновая подгрузка: шаг вкладки оболочки — ClientTabs.prefetch; остальные — как были', async () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-me', fetchAll: true });
    const calls = fakeTabs(t);
    t.win.ClientShell.scheduleCatalogNavigationPrefetch();
    for (let i = 0; i < 40; i++) await t.flush();
    assert.deepEqual(calls, ['prefetch:bookings']);
    const got = t.fetches.map((u) => u.replace(/^.*\//, '').replace(/\?.*$/, ''));
    assert.ok(got.includes('ice-tab.js') && got.includes('kto-kogo.js'));
    assert.ok(!got.includes('client-me.js'), 'текущая вкладка не качается');
  });

  it('tabSwitchDone снимает подсветку нажатия: активна вкладка по адресу', () => {
    const t = bootShell({ flags: SEASON_BOOKINGS, pathname: '/webapp/client-me' });
    fakeTabs(t);
    t.btn('bookings').fire('pointerdown', { pointerId: 1, button: 0, isPrimary: true });
    t.btn('bookings').fire('click');
    t.win.location.pathname = '/webapp/client-bookings';
    t.win.ClientShell.tabSwitchDone();
    assert.deepEqual(t.active(), ['bookings']);
    t.win.location.pathname = '/webapp/client-me';
    t.win.ClientShell.syncTabBarActive();
    assert.deepEqual(t.active(), ['me'], 'подсветка нажатия больше не держит бар');
  });
});
