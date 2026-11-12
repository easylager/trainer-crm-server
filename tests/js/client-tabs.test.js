/**
 * TASK-391: оболочка с живыми вкладками «Я» и «Записи» (client-tabs.js) — роутер, хранилище, контракт.
 * Run: node --test tests/js/client-tabs.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC_PATH = path.resolve(__dirname, '../../static/webapp/client-tabs.js');
const SRC = fs.readFileSync(SRC_PATH, 'utf8');
const M = require(SRC_PATH);

describe('модель: какой переход берёт оболочка', () => {
  it('голый путь вкладки — её id; init_data не мешает', () => {
    assert.equal(M.tabForPath('client-bookings'), 'bookings');
    assert.equal(M.tabForPath('./client-me'), 'me');
    assert.equal(M.tabForPath('/webapp/client-me?init_data=a%3Db'), 'me');
    assert.equal(M.tabForPath('/static/webapp/client-bookings.html'), 'bookings');
  });

  it('свой query страницы, чужая вкладка, чужой каталог — полной загрузкой', () => {
    assert.equal(M.tabForPath('client-bookings?open_booking=5&from=hub'), null);
    assert.equal(M.tabForPath('client-me?x=1&init_data=z'), null);
    assert.equal(M.tabForPath('client-home'), null);
    assert.equal(M.tabForPath('ice'), null);
    assert.equal(M.tabForPath('client-family'), null);
    assert.equal(M.tabForPath('/p/minsk/client-me'), null);
  });

  it('адрес в истории: каталог оболочки, путь вкладки и только init_data', () => {
    assert.equal(
      M.tabUrl('client-bookings', '/webapp/client-me', '?init_data=auth%3D1%26hash%3Dx&foo=1'),
      '/webapp/client-bookings?init_data=auth%3D1%26hash%3Dx'
    );
    assert.equal(M.tabUrl('client-me', '/webapp/client-bookings', ''), '/webapp/client-me');
  });

  it('один файл по /webapp/ и /static/webapp/ — один ключ', () => {
    assert.equal(M.assetKey('/static/webapp/client-sheet.js?v=1'), 'client-sheet.js');
    assert.equal(M.assetKey('client-sheet.js?v=2'), 'client-sheet.js');
    assert.equal(M.cssKey({ code: 'x' }, 'bookings', 9), 'code:bookings:9');
  });
});

describe('модель: хранилище — показ из памяти, обновление в фоне', () => {
  const base = { now: 100000, profileAtMount: '', profileNow: '' };
  it('свежие данные (< 10 с) — ничего', () => {
    assert.equal(M.decideOnShow(Object.assign({ refreshedAt: 100000 - 9000 }, base)), 'none');
  });
  it('устаревшие, неизвестные или из будущего — тихое обновление', () => {
    assert.equal(M.decideOnShow(Object.assign({ refreshedAt: 100000 - M.REFRESH_AFTER_MS }, base)), 'refresh');
    assert.equal(M.decideOnShow(Object.assign({ refreshedAt: 0 }, base)), 'refresh');
    assert.equal(M.decideOnShow(Object.assign({ refreshedAt: 200000 }, base)), 'refresh');
  });
  it('профиль сменился — перезагрузка, даже если данные свежие', () => {
    assert.equal(M.decideOnShow({ now: 1, refreshedAt: 1, profileAtMount: '', profileNow: '77' }), 'reload');
    assert.equal(M.decideOnShow({ now: 1, refreshedAt: 1, profileAtMount: '77', profileNow: '' }), 'reload');
  });
});

describe('модель: классы body и скрипты вкладки', () => {
  it('тема, оболочка и хаб — документа; остальное — вкладки', () => {
    assert.deepEqual(
      M.ownedBodyClasses(['tg-dark', 'client-shell-body', 'client-shell-tabs-hidden', 'hub-body--loading', 'cm-body', 'bookings-body--revealed', '']),
      ['cm-body', 'bookings-body--revealed']
    );
  });
  it('обычные по порядку, defer после; загруженные и однократные — нет', () => {
    const plan = M.scriptPlan(
      [
        { src: 'https://telegram.org/js/telegram-web-app.js' },
        { src: 'mini-app-client-shell.js?v=1' },
        { src: '/static/webapp/ga-press.js?v=1', defer: true },
        { src: 'learn-block.js?v=1' },
        { code: 'a()' },
        { src: 'client-sheet.js?v=1' },
        { src: 'mini-app-telegram-chrome.js?v=1', defer: true },
        { code: 'b()' },
      ],
      { 'client-sheet.js': true },
      (name) => name === 'Telegram' || name === 'ClientShell' || name === 'MiniAppBack'
    );
    assert.deepEqual(plan.map((s) => s.key || s.code), ['learn-block.js', 'a()', 'b()', 'ga-press.js']);
  });
});

/* ── Контракт в живом документе (минимальный DOM) ───────────────────────────── */

class El {
  constructor(tag, doc) {
    this.tagName = tag.toUpperCase();
    this.doc = doc;
    this.attrs = new Map();
    this.children = [];
    this.parentNode = null;
    this._classes = [];
    this.textContent = '';
    this._html = '';
    const self = this;
    this.classList = {
      add(...c) { c.forEach((x) => { if (!self._classes.includes(x)) self._classes.push(x); }); },
      remove(...c) { self._classes = self._classes.filter((x) => !c.includes(x)); },
      contains(c) { return self._classes.includes(c); },
      [Symbol.iterator]() { return self._classes[Symbol.iterator](); },
      get length() { return self._classes.length; },
    };
  }
  get className() { return this._classes.join(' '); }
  set className(v) { this._classes = String(v).split(/\s+/).filter(Boolean); }
  get hidden() { return this.attrs.has('hidden'); }
  set hidden(v) { if (v) this.attrs.set('hidden', ''); else this.attrs.delete('hidden'); }
  set innerHTML(v) { this._html = v; }
  get innerHTML() { return this._html; }
  set rel(v) { this.attrs.set('rel', v); }
  set href(v) { this.attrs.set('href', v); }
  set src(v) { this.attrs.set('src', v); }
  get src() { return this.attrs.get('src') || ''; }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  removeAttribute(k) { this.attrs.delete(k); }
  hasAttribute(k) { return this.attrs.has(k); }
  get firstElementChild() { return this.children[0] || null; }
  get nextElementSibling() {
    const p = this.parentNode;
    return p ? p.children[p.children.indexOf(this) + 1] || null : null;
  }
  get nextSibling() { return this.nextElementSibling; }
  appendChild(c) { return this.insertBefore(c, null); }
  insertBefore(c, ref) {
    if (c.parentNode) c.parentNode.children.splice(c.parentNode.children.indexOf(c), 1);
    const i = ref ? this.children.indexOf(ref) : -1;
    if (i >= 0) this.children.splice(i, 0, c);
    else this.children.push(c);
    c.parentNode = this;
    this.doc.onInsert(c);
    return c;
  }
  all() {
    const out = [];
    (function walk(n) { n.children.forEach((c) => { out.push(c); walk(c); }); })(this);
    return out;
  }
}

function matches(el, sel) {
  return sel.split(',').some((one) => {
    const s = one.trim();
    let m = /^\.ft-tab(?:\[data-ft-tab="(\w+)"\])?$/.exec(s);
    if (m) return el.classList.contains('ft-tab') && (!m[1] || el.getAttribute('data-ft-tab') === m[1]);
    m = /^script\[([\w-]+)\]$/.exec(s);
    if (m) return el.tagName === 'SCRIPT' && el.hasAttribute(m[1]);
    throw new Error('selector not supported: ' + s);
  });
}

function boot({ initial = 'me', fragments = {}, failFragment = false, profile = '' } = {}) {
  const pushes = [];
  const navigations = [];
  const events = [];
  const fetches = [];
  const ran = [];
  const listeners = {};
  const scrolls = [];
  const store = new Map(profile ? [['cw_active_profile_id_v1', profile]] : []);
  let clock = 1000000;
  const doc = {
    title: 'Я',
    onInsert(el) {
      if (el.tagName === 'SCRIPT') {
        if (el.textContent) {
          ran.push('code:' + el.textContent);
          vm.runInContext(el.textContent, ctx);
        } else if (el.src) {
          ran.push(el.src);
          setImmediate(() => el.onload && el.onload());
        }
      }
      if (el.tagName === 'LINK') setImmediate(() => el.onload && el.onload());
    },
  };
  doc.createElement = (t) => new El(t, doc);
  doc.documentElement = new El('html', doc);
  doc.documentElement.setAttribute('data-ft-shell', initial);
  doc.head = new El('head', doc);
  doc.body = new El('body', doc);
  doc.querySelectorAll = (sel) => [...doc.head.all(), ...doc.body.all()].filter((n) => matches(n, sel));
  doc.querySelector = (sel) => doc.querySelectorAll(sel)[0] || null;
  const link = (href) => { const l = new El('link', doc); l.setAttribute('rel', 'stylesheet'); l.setAttribute('href', href); return l; };
  ['/static/shared/glide-tokens.css?v=1', 'theme.css?v=1', 'mini-app-client-shell.css?v=1', 'client-me.css?v=1'].forEach((h) => doc.head.appendChild(link(h)));
  const ft = new El('style', doc);
  ft.textContent = '.ft-tab{display:contents}';
  doc.head.appendChild(ft);
  const shellScript = new El('script', doc);
  shellScript.setAttribute('src', 'mini-app-client-shell.js?v=1');
  doc.head.children.push(shellScript);
  shellScript.parentNode = doc.head;
  doc.body.className = 'cm-body client-shell-body';
  const meEl = new El('div', doc);
  meEl.className = 'ft-tab';
  meEl.setAttribute('data-ft-tab', initial);
  doc.body.children.push(meEl);
  meEl.parentNode = doc.body;
  const sheetJs = new El('script', doc);
  sheetJs.setAttribute('src', '/static/webapp/client-sheet.js?v=1');
  meEl.children.push(sheetJs);
  sheetJs.parentNode = meEl;
  const bar = new El('nav', doc);
  doc.body.children.push(bar);
  bar.parentNode = doc.body;

  const shellCalls = [];
  const win = {
    document: doc,
    location: {
      pathname: '/webapp/client-me',
      search: '?init_data=q',
      get href() { return 'https://t' + this.pathname + this.search; },
      set href(u) { navigations.push(u); },
      reload() { navigations.push('reload'); },
    },
    history: {
      replaceState() {},
      pushState(state, _t, url) {
        pushes.push(url);
        const u = new URL(url, 'https://t');
        win.location.pathname = u.pathname;
        win.location.search = u.search;
      },
    },
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null) },
    scrollY: 0,
    scrollTo(_x, y) { scrolls.push(y); win.scrollY = y; },
    setTimeout: (fn, ms) => setTimeout(fn, Math.min(ms, 5)),
    clearTimeout,
    CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
    addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
    dispatchEvent(ev) { events.push(ev); (listeners[ev.type] || []).forEach((fn) => fn(ev)); return true; },
    fetch(url) {
      fetches.push(url);
      const id = /client-tab\/(\w+)\.json/.exec(url);
      if (!id || failFragment) return Promise.resolve({ ok: false, status: 500 });
      return Promise.resolve({ ok: true, json: () => Promise.resolve(fragments[id[1]]) });
    },
    ClientShell: {
      setTabBarVisible(v) { shellCalls.push('bar:' + v); doc.body.classList[v ? 'remove' : 'add']('client-shell-tabs-hidden'); },
      armTabTiming(n) { shellCalls.push('arm:' + n); },
      contentShown() { shellCalls.push('shown'); },
      tabSwitchDone() { shellCalls.push('done'); },
      fetchAsset(u) { fetches.push('asset:' + u); return Promise.resolve(); },
    },
    MiniAppBack: { clear() { shellCalls.push('back:clear'); }, bridgeLegacy() { shellCalls.push('bridge'); } },
    GlideTouch: { enhance() { shellCalls.push('enhance'); } },
    URLSearchParams,
  };
  win.window = win;
  Object.defineProperty(win, 'Telegram', { value: {}, enumerable: true });
  const ctx = vm.createContext(Object.assign(win, { Date: { now: () => clock }, Promise, JSON, Math, Object, Array, String, Error, console }));
  vm.runInContext(SRC, ctx);
  return {
    win, doc, pushes, navigations, events, fetches, ran, scrolls, shellCalls, store, meEl,
    tabs: () => doc.querySelectorAll('.ft-tab').map((t) => t.getAttribute('data-ft-tab') + (t.hidden ? ':hidden' : ':shown')),
    media: () => doc.head.children.filter((c) => c.getAttribute('media') === 'not all').map((c) => M.assetKey(c.getAttribute('href')) || c.textContent),
    tick(ms) { clock += ms; },
    fire(t, ev) { (listeners[t] || []).forEach((fn) => fn(ev || {})); },
    async settle() { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); },
  };
}

const BOOKINGS = {
  tab: 'bookings',
  path: 'client-bookings',
  title: 'Записи',
  bodyClass: 'client-bookings-body ga-body',
  css: [
    { href: '/static/shared/glide-tokens.css?v=1' },
    { href: 'theme.css?v=1' },
    { href: '/static/webapp/glide-app.css?v=1' },
    { href: 'mini-app-client-bookings.css?v=1' },
    { href: 'mini-app-client-shell.css?v=1' },
    { code: 'html.x{}' },
  ],
  scripts: [
    { src: 'mini-app-client-shell.js?v=1' },
    { src: 'learn-block.js?v=1' },
    { code: 'window.__order = (window.__order || []).concat("main"); document.body.classList.add("bookings-body--revealed");' },
    { src: '/static/webapp/client-sheet.js?v=1' },
    { code: 'window.__order = window.__order.concat("streak");' },
  ],
  html: '<div id="screenList"></div>',
};

describe('контракт: первая «Записи» внутри «Я»', () => {
  it('mount: история, контейнер, стили на местах, скрипты по порядку без повторов', async () => {
    const t = boot({ fragments: { bookings: BOOKINGS } });
    assert.equal(t.win.ClientTabs.go('client-bookings'), true);
    await t.settle();
    assert.deepEqual(t.pushes, ['/webapp/client-bookings?init_data=q']);
    assert.deepEqual(t.navigations, [], 'без перезагрузки');
    assert.deepEqual(t.tabs(), ['me:hidden', 'bookings:shown']);
    assert.equal(t.doc.title, 'Записи');
    // Скрипты: оболочка и client-sheet уже есть; встроенные — по порядку.
    assert.deepEqual(t.ran.filter((r) => !r.startsWith('code:')), ['learn-block.js?v=1']);
    assert.deepEqual([...t.win.__order], ['main', 'streak']);
    // Стили: glide-app и bookings.css — перед общим shell.css, как на странице «Записей».
    const order = t.doc.head.children.map((c) => M.assetKey(c.getAttribute('href')) || (c.textContent.startsWith('.ft') ? 'ft' : c.textContent));
    assert.ok(order.indexOf('glide-app.css') < order.indexOf('mini-app-client-shell.css'), order.join());
    assert.ok(order.indexOf('mini-app-client-bookings.css') < order.indexOf('mini-app-client-shell.css'));
    assert.deepEqual(t.media(), ['client-me.css'], 'выключены только стили «Я»');
    assert.equal(t.doc.body.className, 'client-shell-body client-bookings-body ga-body bookings-body--revealed');
    assert.ok(t.shellCalls.includes('arm:shell') && t.shellCalls.includes('enhance') && t.shellCalls.includes('bridge'));
    assert.equal(t.shellCalls[t.shellCalls.length - 1], 'done');
  });

  it('обратно на «Я» и снова «Записи»: из памяти, прокрутка своя, классы и стили свои', async () => {
    const t = boot({ fragments: { bookings: BOOKINGS } });
    t.win.scrollY = 420;
    t.win.ClientTabs.go('client-bookings');
    await t.settle();
    t.win.scrollY = 90;
    t.shellCalls.length = 0;
    t.win.ClientTabs.go('client-me');
    assert.deepEqual(t.tabs(), ['me:shown', 'bookings:hidden'], 'синхронно, без ожидания');
    assert.equal(t.win.scrollY, 420);
    assert.equal(t.doc.body.className, 'client-shell-body cm-body');
    assert.deepEqual(t.media().sort(), ['glide-app.css', 'html.x{}', 'mini-app-client-bookings.css'].sort());
    assert.deepEqual(t.shellCalls.slice(0, 4), ['bar:true', 'back:clear', 'done', 'arm:shell']);
    assert.ok(t.shellCalls.includes('shown'), 'замер перехода');
    t.win.ClientTabs.go('client-bookings');
    assert.equal(t.win.scrollY, 90);
    assert.equal(t.fetches.filter((u) => /client-tab/.test(u)).length, 1, 'фрагмент — один раз');
    assert.deepEqual(t.pushes.length, 3);
  });

  it('refresh: только устаревшей вкладке и не чаще 10 с', async () => {
    const t = boot({ fragments: { bookings: BOOKINGS } });
    t.win.ClientTabs.go('client-bookings');
    await t.settle();
    const refreshes = () => t.events.filter((e) => e.type === 'client-tabs:refresh').map((e) => e.detail.tab);
    t.win.ClientTabs.go('client-me');
    assert.deepEqual(refreshes(), [], 'данные «Я» свежие');
    t.tick(11000);
    t.win.ClientTabs.go('client-bookings');
    assert.deepEqual(refreshes(), ['bookings']);
    t.win.ClientTabs.go('client-me');
    assert.deepEqual(refreshes(), ['bookings', 'me']);
    t.win.ClientTabs.go('client-bookings');
    assert.deepEqual(refreshes(), ['bookings', 'me'], 'только что обновлялась');
  });

  it('бар скрыт на вкладке (детали записи) — возвращается её состояние, а не чужое', async () => {
    const t = boot({ fragments: { bookings: BOOKINGS } });
    t.win.ClientTabs.go('client-bookings');
    await t.settle();
    t.doc.body.classList.add('client-shell-tabs-hidden');
    t.win.ClientTabs.go('client-me');
    assert.ok(!t.doc.body.classList.contains('client-shell-tabs-hidden'));
    t.win.ClientTabs.go('client-bookings');
    assert.ok(t.doc.body.classList.contains('client-shell-tabs-hidden'));
  });

  it('сбой фрагмента — обычный переход по тому же адресу', async () => {
    const t = boot({ failFragment: true });
    t.win.ClientTabs.go('client-bookings');
    await t.settle();
    assert.deepEqual(t.navigations, ['/webapp/client-bookings?init_data=q']);
    assert.deepEqual(t.pushes, []);
    assert.deepEqual(t.tabs(), ['me:shown']);
  });

  it('не вкладка оболочки и свой query — false: ClientShell грузит страницу сам', () => {
    const t = boot();
    assert.equal(t.win.ClientTabs.go('client-home'), false);
    assert.equal(t.win.ClientTabs.go('client-bookings?open_booking=3'), false);
    assert.equal(t.win.ClientTabs.go('client-me'), true, 'та же вкладка');
    assert.deepEqual(t.pushes, []);
  });
});

describe('история, bfcache, профиль', () => {
  it('popstate показывает живую вкладку без замера и без новой записи', async () => {
    const t = boot({ fragments: { bookings: BOOKINGS } });
    t.win.ClientTabs.go('client-bookings');
    await t.settle();
    t.shellCalls.length = 0;
    t.win.location.pathname = '/webapp/client-me';
    t.fire('popstate', { state: { ftTab: 'me' } });
    assert.deepEqual(t.tabs(), ['me:shown', 'bookings:hidden']);
    assert.ok(!t.shellCalls.includes('shown'));
    assert.equal(t.pushes.length, 1);
  });

  it('popstate на невыгруженную вкладку — перезагрузка этого адреса', () => {
    const t = boot();
    t.fire('popstate', { state: { ftTab: 'bookings' } });
    assert.deepEqual(t.navigations, ['reload']);
  });

  it('pageshow.persisted: тот же профиль — тихий refresh активной, другие — устаревшие', async () => {
    const t = boot({ fragments: { bookings: BOOKINGS }, profile: '5' });
    t.win.ClientTabs.go('client-bookings');
    await t.settle();
    t.fire('pageshow', { persisted: true });
    assert.deepEqual(t.events.filter((e) => e.type === 'client-tabs:refresh').map((e) => e.detail.tab), ['bookings']);
    t.win.ClientTabs.go('client-me');
    assert.deepEqual(t.events.filter((e) => e.type === 'client-tabs:refresh').map((e) => e.detail.tab), ['bookings', 'me']);
    assert.deepEqual(t.navigations, []);
  });

  it('pageshow.persisted после смены профиля на Главной — перезагрузка', () => {
    const t = boot({ profile: '5' });
    t.store.set('cw_active_profile_id_v1', '9');
    t.fire('pageshow', { persisted: true });
    assert.deepEqual(t.navigations, ['reload']);
  });

  it('показ вкладки после смены профиля — перезагрузка', async () => {
    const t = boot({ fragments: { bookings: BOOKINGS } });
    t.win.ClientTabs.go('client-bookings');
    await t.settle();
    t.store.set('cw_active_profile_id_v1', '9');
    t.win.ClientTabs.go('client-me');
    assert.deepEqual(t.navigations, ['reload']);
  });
});

describe('префетч', () => {
  it('фрагмент и его недостающие файлы с ?v= через ClientShell.fetchAsset; живую вкладку — нет', async () => {
    const t = boot({ fragments: { bookings: BOOKINGS } });
    await t.win.ClientTabs.prefetch('bookings');
    const assets = t.fetches.filter((u) => u.startsWith('asset:')).map((u) => M.assetKey(u.slice(6)));
    assert.deepEqual(assets.sort(), ['glide-app.css', 'learn-block.js', 'mini-app-client-bookings.css']);
    const n = t.fetches.length;
    await t.win.ClientTabs.prefetch('me');
    assert.equal(t.fetches.length, n, '«Я» уже живая');
  });
});

describe('без флага файл ничего не делает', () => {
  it('нет data-ft-shell — ClientTabs не появляется', () => {
    const ctx = vm.createContext({
      document: { documentElement: { getAttribute: () => null } },
      Date, Promise, JSON, Math, Object, Array, String, Error,
    });
    ctx.window = ctx;
    vm.runInContext(SRC, ctx);
    assert.equal(ctx.ClientTabs, undefined);
    assert.equal(typeof ctx.ClientTabsModel.tabForPath, 'function');
  });
});
