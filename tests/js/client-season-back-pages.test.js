/**
 * TASK-375: исполнение страниц «из Ещё» (vm + заглушка DOM, jsdom в репозитории нет).
 * Скрипты страницы выполняются в порядке документа: синхронные и inline — сразу, defer — после.
 * Ловит класс ошибки «хелпер подключён позже встроенного скрипта».
 * Run: node --test tests/js/client-season-back*.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const WEBAPP = path.join(__dirname, '../../static/webapp');
const PAGES = ['client-saved-trainers', 'client-stats', 'client-passes-certificates', 'client-passes',
  'client-certificates', 'client-family-access', 'client-support'];
const KEY = 'cw_ui_flags_v1';
const ON = JSON.stringify({ u: '42', season_ui: true, at: Date.now() });

function scriptsOf(html) {
  const out = [];
  const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/g;
  let m;
  while ((m = re.exec(html))) {
    const src = /\bsrc="([^"]+)"/.exec(m[1]);
    out.push({ src: src ? src[1] : null, defer: /\bdefer\b/.test(m[1]), async: /\basync\b/.test(m[1]), code: m[2] });
  }
  return out;
}

function localPath(src) {
  if (/^https?:/.test(src)) return null;
  const clean = src.split('?')[0];
  const rel = clean.startsWith('/static/webapp/') ? clean.slice('/static/webapp/'.length) : clean.replace(/^\//, '');
  const p = path.join(WEBAPP, rel);
  return fs.existsSync(p) ? p : null;
}

/** Заглушка элемента: достаточно для загрузки страницы и чтения hidden/onclick. */
function makeEl(id, attrs = {}) {
  const cls = new Set();
  const el = {
    id, hidden: id === 'btnBack' ? attrs.hidden !== false : false, onclick: null, style: { setProperty() {}, removeProperty() {} }, dataset: {},
    textContent: '', innerHTML: '', value: '', children: [], childNodes: [], disabled: false,
    classList: {
      add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c),
      toggle: (c, f) => { if (f === undefined ? !cls.has(c) : f) cls.add(c); else cls.delete(c); }, _s: cls,
    },
    getAttribute: (n) => (n in attrs ? attrs[n] : null),
    hasAttribute: (n) => n in attrs,
    setAttribute() {}, removeAttribute() {}, addEventListener() {}, removeEventListener() {},
    appendChild() {}, remove() {}, focus() {}, click() {}, scrollIntoView() {},
    querySelector: () => null, querySelectorAll: () => [], closest: () => null, matches: () => false,
    getBoundingClientRect: () => ({ top: 0, left: 0, width: 0, height: 0 }),
  };
  return el;
}

/** Грузит страницу. opts: cache, storageThrows, history, nav. */
function loadPage(page, opts = {}) {
  const html = fs.readFileSync(path.join(WEBAPP, page + '.html'), 'utf8');
  const btnAttrs = {};
  const bm = /<button[^>]*id="btnBack"([^>]*)>|<button([^>]*)id="btnBack"[^>]*>/.exec(html);
  const tag = bm ? bm[0] : '';
  if (/data-season-back/.test(tag)) btnAttrs['data-season-back'] = '';
  if (/data-skip-history-back/.test(tag)) btnAttrs['data-skip-history-back'] = 'true';
  const els = {};
  const get = (id) => {
    if (!els[id]) els[id] = makeEl(id, id === 'btnBack' ? btnAttrs : {});
    return els[id];
  };
  const log = { back: 0, hrefs: [], errors: [] };
  const domReady = [];
  const raw = opts.cache === undefined ? ON : opts.cache;
  const noop = () => {};
  const window = {
    location: { pathname: '/webapp/' + page, search: '', hash: '', set href(v) { log.hrefs.push(v); }, get href() { return ''; } },
    history: { length: opts.history === undefined ? 3 : opts.history, back() { log.back++; }, replaceState: noop, pushState: noop },
    navigation: opts.nav,
    Telegram: { WebApp: { initData: 'a=1', initDataUnsafe: { user: { id: 42 } }, ready: noop, expand: noop } },
    localStorage: opts.storageThrows
      ? { getItem() { throw new Error('denied'); }, setItem: noop }
      : { getItem: (k) => (k === KEY ? raw : null), setItem: noop, removeItem: noop },
    sessionStorage: { getItem: () => null, setItem: noop, removeItem: noop },
    addEventListener: noop, removeEventListener: noop, matchMedia: () => ({ matches: false, addEventListener: noop }),
    fetch: () => new Promise(() => {}), setTimeout: noop, setInterval: noop, clearTimeout: noop, requestAnimationFrame: noop,
    URLSearchParams, encodeURIComponent, decodeURIComponent, JSON, Date, Math, console,
    CustomEvent: function () {}, MutationObserver: function () { this.observe = noop; },
  };
  window.window = window;
  window.document = {
    readyState: 'loading',
    documentElement: makeEl('html'), body: makeEl('body'), head: makeEl('head'),
    addEventListener: (n, f) => { if (n === 'DOMContentLoaded') domReady.push(f); },
    removeEventListener: noop,
    getElementById: get, createElement: (t) => makeEl(t), createTextNode: () => makeEl('t'),
    querySelector: () => null, querySelectorAll: () => [], getElementsByClassName: () => [],
  };
  const ctx = vm.createContext(window);
  const run = (code, name) => {
    try { vm.runInContext(code, ctx, { filename: name }); } catch (e) { log.errors.push(name + ': ' + e.message); }
  };
  const deferred = [];
  const order = [];
  for (const s of scriptsOf(html)) {
    if (s.src) {
      const p = localPath(s.src);
      if (!p || /ga-(touch|press)|profile-switcher/.test(p)) continue;
      if (s.defer) deferred.push([p, path.basename(p)]);
      else { order.push(path.basename(p)); run(fs.readFileSync(p, 'utf8'), path.basename(p)); }
    } else if (s.code.trim()) {
      order.push('inline');
      run(s.code, page + ' inline');
    }
  }
  window.document.readyState = 'interactive';
  for (const [p, n] of deferred) { order.push(n); run(fs.readFileSync(p, 'utf8'), n); }
  window.document.readyState = 'complete';
  for (const f of domReady) { try { f(); } catch (e) { log.errors.push('DOMContentLoaded: ' + e.message); } }
  return { btn: get('btnBack'), home: get('btnHome'), log, order, els, window };
}

describe('порядок подключения: хелпер раньше любого скрипта, который его использует', () => {
  for (const page of PAGES) {
    it(page, () => {
      const html = fs.readFileSync(path.join(WEBAPP, page + '.html'), 'utf8');
      const list = scriptsOf(html);
      const h = list.findIndex((s) => s.src && s.src.includes('client-season-back.js'));
      assert.ok(h >= 0, 'хелпер подключён');
      assert.ok(!list[h].defer && !list[h].async, 'хелпер синхронный');
      list.forEach((s, i) => {
        const uses = s.src
          ? /mini-app-client-home\.js|-main\.js/.test(s.src)
          : /ClientSeasonBack|seasonBackOn/.test(s.code);
        if (uses) assert.ok(h < i, `хелпер должен идти раньше скрипта #${i} ${s.src || '(inline)'}`);
      });
    });
  }
});

describe('исполнение страниц: флаг включён (кэш season_ui true со своим u)', () => {
  for (const page of PAGES) {
    it(`${page}: страница грузится без ошибок, #btnBack виден на корне, без истории → client-me`, () => {
      const r = loadPage(page, { history: 1 });
      assert.deepEqual(r.log.errors, []);
      assert.equal(r.btn.hidden, false);
      assert.equal(typeof r.btn.onclick, 'function');
      r.btn.onclick();
      assert.equal(r.log.back, 0);
      assert.deepEqual(r.log.hrefs, ['/webapp/client-me?init_data=a%3D1']);
    });
    it(`${page}: с историей → history.back()`, () => {
      const r = loadPage(page, { history: 3 });
      assert.equal(r.btn.hidden, false);
      r.btn.onclick();
      assert.equal(r.log.back, 1);
      assert.deepEqual(r.log.hrefs, []);
    });
  }
  for (const [page, detail, list] of [['client-passes', 'screenDetail', 'showScreen'],
    ['client-passes-certificates', 'pass-screenDetail', 'showPassScreen']]) {
    it(`${page}: на экране детали «назад» остаётся внутренним (не уходит со страницы)`, () => {
      const r = loadPage(page, { history: 1 });
      r.els[detail] = r.els[detail] || r.window.document.getElementById(detail);
      r.els[detail].classList.add('active');
      r.btn.onclick();
      assert.equal(r.log.back, 0);
      assert.deepEqual(r.log.hrefs, []);
    });
  }
});

describe('исполнение страниц: флаг выключен — как раньше', () => {
  const offStates = [
    ['нет кэша', { cache: null }],
    ['season_ui false', { cache: JSON.stringify({ u: '42', season_ui: false, at: Date.now() }) }],
    ['"true" строкой', { cache: JSON.stringify({ u: '42', season_ui: 'true', at: Date.now() }) }],
    ['чужой u', { cache: JSON.stringify({ u: '7', season_ui: true, at: Date.now() }) }],
    ['битый JSON', { cache: '{oops' }],
    ['storage бросает', { storageThrows: true }],
  ];
  for (const page of PAGES) {
    for (const [name, st] of offStates) {
      it(`${page}: ${name}`, () => {
        const noHist = loadPage(page, { ...st, history: 1 });
        assert.deepEqual(noHist.log.errors, []);
        assert.deepEqual(noHist.log.hrefs, []);
        // Без истории кнопка скрыта везде: и на корне stats/passes (skip-history-back), и у остальных.
        assert.equal(noHist.btn.hidden, true);
      });
    }
    it(`${page}: нет флага, есть история — по-прежнему только там, где «назад» был`, () => {
      const r = loadPage(page, { cache: null, history: 3 });
      const visible = !r.btn.hidden;
      // saved-trainers, certificates, family-access, support показывают «назад» с историей; корни skip-страниц — нет.
      const expected = ['client-saved-trainers', 'client-certificates', 'client-family-access', 'client-support'].includes(page);
      assert.equal(visible, expected);
      if (visible) { r.btn.onclick(); assert.equal(r.log.back, 1); }
    });
  }
  for (const page of PAGES) {
    it(`${page}: «Главная» → client-home (флаг выкл и вкл)`, () => {
      for (const cache of [null, ON]) {
        const r = loadPage(page, { cache });
        assert.equal(typeof r.home.onclick, 'function');
        r.home.onclick();
        assert.deepEqual(r.log.hrefs, ['/webapp/client-home?init_data=a%3D1']);
      }
    });
  }
  for (const [page, detail, listId] of [['client-passes', 'screenDetail', 'screenList'],
    ['client-passes-certificates', 'pass-screenDetail', 'pass-screenList']]) {
    it(`${page}: флаг выкл, экран детали — «назад» ведёт к списку внутри страницы, как раньше`, () => {
      const r = loadPage(page, { cache: null, history: 3 });
      r.els[detail] = r.window.document.getElementById(detail);
      r.els[listId] = r.window.document.getElementById(listId);
      r.els[detail].classList.add('active');
      r.btn.onclick();
      assert.equal(r.log.back, 0);
      assert.deepEqual(r.log.hrefs, []);
      assert.equal(r.els[listId].classList.contains('active'), true);
      // querySelectorAll в заглушке пуст, поэтому снятие 'active' с детали не проверяем — только показ списка и скрытие кнопки
      assert.equal(r.btn.hidden, true);
    });
  }
});
