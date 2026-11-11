/**
 * TASK-366: флаги новой навигации в оболочке — кэш до первого кадра, уточнение с сервера,
 * событие client-shell:ui-flags только при изменении, DOM не меняется при выключенном флаге.
 * Run: node --test tests/js/client-shell-ui-flags.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const shellSrc = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/mini-app-client-shell.js'), 'utf8');
const KEY = 'cw_ui_flags_v1';

function el() {
  return {
    children: [], style: {}, dataset: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(c) { this.children.push(c); return c; }, setAttribute() {}, getAttribute() { return null; },
    addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    insertAdjacentHTML() {}, remove() {},
  };
}

function bootShell({ userId = 42, initData = 'user=%7B%22id%22%3A42%7D&hash=x', stored, response, failFetch, storageThrows } = {}) {
  const store = new Map();
  if (stored !== undefined) store.set(KEY, typeof stored === 'string' ? stored : JSON.stringify(stored));
  const events = [];
  const fetches = [];
  const timers = [];
  const domOps = [];
  const body = el();
  body.getAttribute = (n) => (n === 'data-client-shell' ? 'hidden' : null);
  body.appendChild = (c) => { domOps.push(['append', c]); return c; };
  const localStorage = storageThrows
    ? { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } }
    : { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
  const window = {
    location: { pathname: '/webapp/client-home', search: '', href: 'https://test/webapp/client-home', replace() {} },
    history: { length: 1 },
    document: {
      readyState: 'complete', body, documentElement: { style: { setProperty() {} } },
      getElementById() { return null; },
      createElement() { domOps.push(['create']); return el(); },
      head: { appendChild() {} }, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    },
    addEventListener() {},
    dispatchEvent(ev) { events.push(ev); return true; },
    CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
    sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    localStorage,
    Telegram: { WebApp: { initData, initDataUnsafe: userId == null ? {} : { user: { id: userId } } } },
    navigation: null,
    setTimeout(fn) { timers.push(fn); return timers.length; },
    fetch(url, opts) {
      fetches.push({ url, opts });
      if (url === '/api/webapp/client/ui-flags') {
        if (failFetch) return Promise.reject(new Error('offline'));
        return Promise.resolve({ ok: true, json: () => Promise.resolve(response) });
      }
      return new Promise(() => {});
    },
  };
  const ctx = vm.createContext({ URL, URLSearchParams, JSON, Date, window });
  for (const k of ['document', 'location', 'history', 'Telegram', 'sessionStorage', 'localStorage', 'addEventListener', 'fetch', 'setTimeout']) ctx[k] = window[k];
  vm.runInContext(shellSrc, ctx);
  const startFlags = { ...window.ClientShell.uiFlags() };
  const domOpsAtBoot = domOps.length;
  return {
    window, store, events, fetches, startFlags, domOps, domOpsAtBoot,
    async runTimers() {
      while (timers.length) timers.shift()();
      for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
    },
    flagFetches: () => fetches.filter((f) => f.url === '/api/webapp/client/ui-flags'),
  };
}

const on = { u: '42', season_ui: true, bookings_tab: true, at: 1 };

describe('TASK-366 client shell ui flags', () => {
  it('читает кэш своего пользователя синхронно, до запроса', () => {
    const s = bootShell({ stored: on, response: on });
    assert.deepEqual(s.startFlags, { season_ui: true, bookings_tab: true });
    assert.equal(s.flagFetches().length, 0);
  });

  it('кэш другого пользователя, битый JSON и недоступный storage → выключено', () => {
    for (const opts of [{ stored: { ...on, u: '7' } }, { stored: '{oops' }, { storageThrows: true }]) {
      const s = bootShell({ ...opts, response: { season_ui: false, bookings_tab: false } });
      assert.deepEqual(s.startFlags, { season_ui: false, bookings_tab: false });
    }
  });

  it('bookings_tab без season_ui в кэше не включается', () => {
    const s = bootShell({ stored: { u: '42', season_ui: false, bookings_tab: true } });
    assert.deepEqual(s.startFlags, { season_ui: false, bookings_tab: false });
  });

  it('после монтирования спрашивает сервер, пишет кэш и шлёт событие один раз при изменении', async () => {
    const s = bootShell({ response: { season_ui: true, bookings_tab: false } });
    await s.runTimers();
    const f = s.flagFetches();
    assert.equal(f.length, 1);
    assert.equal(f[0].opts.cache, 'no-store');
    assert.equal(f[0].opts.headers['X-Telegram-Init-Data'], 'user=%7B%22id%22%3A42%7D&hash=x');
    const cached = JSON.parse(s.store.get(KEY));
    assert.equal(cached.u, '42');
    assert.equal(cached.season_ui, true);
    assert.equal(cached.bookings_tab, false);
    assert.equal(typeof cached.at, 'number');
    assert.equal(s.events.length, 1);
    assert.equal(s.events[0].type, 'client-shell:ui-flags');
    assert.deepEqual({ ...s.events[0].detail }, { season_ui: true, bookings_tab: false });
    assert.deepEqual({ ...s.window.ClientShell.uiFlags() }, { season_ui: true, bookings_tab: false });
    await s.runTimers();
    assert.equal(s.events.length, 1);
  });

  it('без изменений события нет; выключенный флаг не трогает DOM', async () => {
    const s = bootShell({ stored: { u: '42', season_ui: false, bookings_tab: false, at: 1 }, response: { season_ui: false, bookings_tab: false } });
    await s.runTimers();
    assert.equal(s.flagFetches().length, 1);
    assert.equal(s.events.length, 0);
    assert.equal(s.domOps.length, s.domOpsAtBoot);
  });

  it('ошибка сети — молча, кэш не трогается', async () => {
    const raw = JSON.stringify(on);
    const s = bootShell({ stored: raw, failFetch: true });
    await s.runTimers();
    assert.equal(s.store.get(KEY), raw);
    assert.equal(s.events.length, 0);
    assert.deepEqual({ ...s.window.ClientShell.uiFlags() }, { season_ui: true, bookings_tab: true });
  });

  it('вне Telegram — выключено и без запроса', async () => {
    const s = bootShell({ initData: '', userId: null, stored: on });
    await s.runTimers();
    assert.deepEqual(s.startFlags, { season_ui: false, bookings_tab: false });
    assert.equal(s.flagFetches().length, 0);
  });
});
