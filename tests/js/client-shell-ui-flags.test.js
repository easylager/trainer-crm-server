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

function bootShell({ userId = 42, initData = 'user=%7B%22id%22%3A42%7D&hash=x', stored, response, failFetch, storageThrows, status, session, sessionThrows, pathname = '/webapp/client-home' } = {}) {
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
    location: { pathname, search: '', href: 'https://test' + pathname, replace() {} },
    history: { length: 1 },
    document: {
      readyState: 'complete', body, documentElement: { style: { setProperty() {} } },
      getElementById() { return null; },
      createElement() { domOps.push(['create']); return el(); },
      head: { appendChild(c) { domOps.push(['head', c]); return c; } }, addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    },
    addEventListener() {},
    dispatchEvent(ev) { events.push(ev); return true; },
    CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
    sessionStorage: sessionThrows
      ? { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() {} }
      : session
        ? { getItem: (k) => (session.has(k) ? session.get(k) : null), setItem: (k, v) => session.set(k, String(v)), removeItem: (k) => session.delete(k) }
        : { getItem() { return null; }, setItem() {}, removeItem() {} },
    localStorage,
    Telegram: { WebApp: { initData, initDataUnsafe: userId == null ? {} : { user: { id: userId } } } },
    navigation: null,
    setTimeout(fn) { timers.push(fn); return timers.length; },
    fetch(url, opts) {
      fetches.push({ url, opts });
      if (url === '/api/webapp/client/ui-flags') {
        if (failFetch) return Promise.reject(new Error('offline'));
        if (status) return Promise.resolve({ ok: false, status, json: () => Promise.resolve({}) });
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

const on = { u: '42', season_ui: true, bookings_tab: true, at: Date.now() };

describe('TASK-366 client shell ui flags', () => {
  it('читает кэш своего пользователя синхронно, до запроса', () => {
    const s = bootShell({ stored: on, response: on });
    assert.deepEqual(s.startFlags, { season_ui: true, bookings_tab: true, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
    assert.equal(s.flagFetches().length, 0);
  });

  it('TASK-437: кэш другого пользователя, битый JSON и недоступный storage → включено по умолчанию, без «Записей»', () => {
    for (const opts of [{ stored: { ...on, u: '7' } }, { stored: '{oops' }, { storageThrows: true }, {}]) {
      const s = bootShell({ ...opts, response: { season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false } });
      assert.deepEqual(s.startFlags, { season_ui: true, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
    }
  });

  it('bookings_tab без season_ui в кэше не включается', () => {
    const s = bootShell({ stored: { u: '42', season_ui: false, bookings_tab: true, at: Date.now() } });
    assert.deepEqual(s.startFlags, { season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
  });

  it('после монтирования спрашивает сервер, пишет кэш и шлёт событие один раз при изменении', async () => {
    const s = bootShell({ response: { season_ui: true, bookings_tab: true, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false } });
    assert.deepEqual(s.startFlags, { season_ui: true, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
    await s.runTimers();
    const f = s.flagFetches();
    assert.equal(f.length, 1);
    assert.equal(f[0].opts.cache, 'no-store');
    assert.equal(f[0].opts.headers['X-Telegram-Init-Data'], 'user=%7B%22id%22%3A42%7D&hash=x');
    const cached = JSON.parse(s.store.get(KEY));
    assert.equal(cached.u, '42');
    assert.equal(cached.season_ui, true);
    assert.equal(cached.bookings_tab, true);
    assert.equal(typeof cached.at, 'number');
    assert.equal(s.events.length, 1);
    assert.equal(s.events[0].type, 'client-shell:ui-flags');
    assert.deepEqual({ ...s.events[0].detail }, { season_ui: true, bookings_tab: true, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
    assert.deepEqual({ ...s.window.ClientShell.uiFlags() }, { season_ui: true, bookings_tab: true, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
    await s.runTimers();
    assert.equal(s.events.length, 1);
  });

  it('без изменений события нет; выключенный флаг не трогает DOM', async () => {
    const s = bootShell({ stored: { u: '42', season_ui: false, bookings_tab: false, at: Date.now() }, response: { season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false } });
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
    assert.deepEqual({ ...s.window.ClientShell.uiFlags() }, { season_ui: true, bookings_tab: true, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
  });

  it('TASK-445: redesign_s1 из кэша и с сервера включает season-режим и «Записи»', async () => {
    const cached = bootShell({
      stored: { u: '42', season_ui: false, bookings_tab: true, redesign_s1: true, at: Date.now() },
      response: { season_ui: false, bookings_tab: true, redesign_s1: true, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false },
    });
    assert.deepEqual({ ...cached.startFlags }, { season_ui: true, bookings_tab: true, redesign_s1: true, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
    const fresh = bootShell({ response: { season_ui: false, bookings_tab: true, redesign_s1: true, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false } });
    await fresh.runTimers();
    assert.deepEqual({ ...fresh.window.ClientShell.uiFlags() }, { season_ui: true, bookings_tab: true, redesign_s1: true, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
    const saved = JSON.parse(fresh.store.get(KEY));
    assert.equal(saved.redesign_s1, true);
    assert.equal(saved.season_ui, true);
    assert.equal(saved.bookings_tab, true);
  });

  it('вне Telegram — выключено и без запроса', async () => {
    const s = bootShell({ initData: '', userId: null, stored: on });
    await s.runTimers();
    assert.deepEqual(s.startFlags, { season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false });
    assert.equal(s.flagFetches().length, 0);
  });
});

/* ── Кэш флагов: TTL, сброс по ошибке, один запрос на сессию ───────────────────────────── */

const DAY = 24 * 60 * 60 * 1000;
const OFF = { season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false };
const ON = { season_ui: true, bookings_tab: true, redesign_s1: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false };
const seasonBack = require('../../static/webapp/client-season-back.js');
const gateSrc = (() => {
  const html = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/kto-kogo.html'), 'utf8');
  const m = /<script id="kk-shell-gate">([\s\S]*?)<\/script>/.exec(html);
  assert.ok(m, 'гейт #kk-shell-gate найден');
  return m[1];
})();

/** Три читателя кэша: оболочка, client-season-back, гейт игры. Возвращают, включён ли season_ui. */
function readers(raw, { throws = false, user = 42 } = {}) {
  const storage = throws
    ? { getItem() { throw new Error('denied'); } }
    : { getItem: (k) => (k === KEY && raw !== undefined ? raw : null) };
  const shell = bootShell({ stored: raw === undefined ? undefined : raw, storageThrows: throws, userId: user, initData: user == null ? '' : undefined }).startFlags.season_ui;
  const back = seasonBack.readCachedSeasonUi(storage, user == null ? '' : String(user));
  const writes = [];
  const win = {
    Telegram: { WebApp: { initDataUnsafe: user == null ? {} : { user: { id: user } } } },
    localStorage: storage,
  };
  const doc = { write(s) { writes.push(s); } };
  vm.runInNewContext(gateSrc, { window: win, document: doc, JSON, Date, String });
  return { shell, back, gate: writes.length > 0 };
}

describe('TASK-381 кэш флагов: одно правило в трёх местах', () => {
  const now = Date.now();
  const cases = [
    /* TASK-437: по умолчанию включено; выключает только свежий false этого пользователя. */
    ['нет кэша', undefined, true],
    ['season_ui false свежий', JSON.stringify({ u: '42', season_ui: false, bookings_tab: false, at: now }), false],
    ['season_ui false почти сутки', JSON.stringify({ u: '42', season_ui: false, at: now - DAY + 60000 }), false],
    ['season_ui false просроченный', JSON.stringify({ u: '42', season_ui: false, at: now - DAY - 60000 }), true],
    ['season_ui false без at', JSON.stringify({ u: '42', season_ui: false }), true],
    ['season_ui false, at строкой', JSON.stringify({ u: '42', season_ui: false, at: String(now) }), true],
    ['season_ui false, at из будущего', JSON.stringify({ u: '42', season_ui: false, at: now + DAY }), true],
    ['"false" строкой', JSON.stringify({ u: '42', season_ui: 'false', at: now }), true],
    ['чужой u с false', JSON.stringify({ u: '7', season_ui: false, at: now }), true],
    ['битый JSON', '{season_ui:false', true],
    ['свежий true', JSON.stringify({ u: '42', season_ui: true, bookings_tab: true, at: now - 60000 }), true],
    ['просроченный true', JSON.stringify({ u: '42', season_ui: true, at: now - DAY - 60000 }), true],
  ];
  for (const [name, raw, want] of cases) {
    it(`${name} → ${want ? 'включено' : 'выключено'} везде`, () => {
      assert.deepEqual(readers(raw), { shell: want, back: want, gate: want });
    });
  }
  it('storage бросает → включено везде', () => {
    assert.deepEqual(readers(undefined, { throws: true }), { shell: true, back: true, gate: true });
  });
  it('нет пользователя Telegram → выключено везде', () => {
    assert.deepEqual(readers(JSON.stringify({ u: '42', season_ui: true, at: now }), { user: null }), { shell: false, back: false, gate: false });
  });
  it('TTL в трёх местах один: сутки', () => {
    assert.equal(seasonBack.UI_FLAGS_TTL_MS, DAY);
    assert.match(shellSrc, /UI_FLAGS_TTL_MS = 24 \* 60 \* 60 \* 1000/);
    assert.match(gateSrc, /age < 86400000/);
  });
});

describe('TASK-381 ответ сервера и сессия', () => {
  const stored = { u: '42', season_ui: true, bookings_tab: true, at: Date.now() };

  it('401 сбрасывает кэш в выключенное, шлёт событие и ставит метку', async () => {
    const session = new Map();
    const s = bootShell({ stored, status: 401, session });
    assert.deepEqual(s.startFlags, ON);
    await s.runTimers();
    const cached = JSON.parse(s.store.get(KEY));
    assert.equal(cached.season_ui, false);
    assert.equal(cached.bookings_tab, false);
    assert.equal(cached.u, '42');
    assert.deepEqual({ ...s.window.ClientShell.uiFlags() }, OFF);
    assert.equal(s.events.length, 1);
    assert.deepEqual({ ...s.events[0].detail }, OFF);
    assert.equal(session.get('cw_ui_flags_sync_v1'), '42');
  });

  it('матрица ответов: 401/403 и битый JSON сбрасывают, 500/502/сеть — нет; 200 пишет', async () => {
    for (const status of [401, 403]) {
      const session = new Map();
      const s = bootShell({ stored, status, session });
      await s.runTimers();
      assert.equal(JSON.parse(s.store.get(KEY)).season_ui, false, String(status));
      assert.equal(s.events.length, 1, String(status));
      assert.equal(session.get('cw_ui_flags_sync_v1'), '42');
    }
    for (const status of [500, 502]) {
      const session = new Map();
      const s = bootShell({ stored, status, session });
      await s.runTimers();
      assert.equal(JSON.parse(s.store.get(KEY)).season_ui, true, String(status));
      assert.deepEqual({ ...s.window.ClientShell.uiFlags() }, ON);
      assert.equal(s.events.length, 0);
      assert.equal(session.has('cw_ui_flags_sync_v1'), false);
    }
    const ok = bootShell({ stored: { ...stored, season_ui: false, bookings_tab: false }, response: ON, session: new Map() });
    await ok.runTimers();
    assert.equal(JSON.parse(ok.store.get(KEY)).season_ui, true);
    assert.equal(ok.events.length, 1);
  });

  it('следующая загрузка после сброса стартует выключенной', async () => {
    const first = bootShell({ stored, status: 401 });
    await first.runTimers();
    const next = bootShell({ stored: first.store.get(KEY), response: OFF });
    assert.deepEqual(next.startFlags, OFF);
  });

  it('ответ без тела (json падает) тоже сбрасывает', async () => {
    const s = bootShell({ stored, response: undefined });
    s.window.fetch = (url) => Promise.resolve({ ok: true, json: () => Promise.reject(new Error('bad json')) });
    await s.runTimers();
    assert.equal(JSON.parse(s.store.get(KEY)).season_ui, false);
  });

  it('сеть недоступна — кэш и метка не трогаются', async () => {
    const session = new Map();
    const s = bootShell({ stored, failFetch: true, session });
    await s.runTimers();
    assert.equal(JSON.parse(s.store.get(KEY)).season_ui, true);
    assert.equal(session.has('cw_ui_flags_sync_v1'), false);
  });

  it('один запрос на сессию: вторая страница с меткой флаги не спрашивает', async () => {
    const session = new Map();
    const a = bootShell({ stored, response: ON, session });
    await a.runTimers();
    assert.equal(a.flagFetches().length, 1);
    const b = bootShell({ stored: a.store.get(KEY), response: ON, session });
    await b.runTimers();
    assert.equal(b.flagFetches().length, 0);
    assert.deepEqual(b.startFlags, ON);
  });

  it('метка другого пользователя не мешает; sessionStorage бросает — запрос на каждой странице, как раньше', async () => {
    const other = bootShell({ stored, response: ON, session: new Map([['cw_ui_flags_sync_v1', '7']]) });
    await other.runTimers();
    assert.equal(other.flagFetches().length, 1);
    const throwing = bootShell({ stored, response: ON, sessionThrows: true });
    await throwing.runTimers();
    assert.equal(throwing.flagFetches().length, 1);
  });

  it('выключенный флаг: запрос, DOM и события те же, что до правки', async () => {
    const s = bootShell({ stored: { ...stored, season_ui: false, bookings_tab: false }, response: OFF });
    await s.runTimers();
    assert.equal(s.flagFetches().length, 1);
    assert.equal(s.events.length, 0);
    assert.equal(s.domOps.length, s.domOpsAtBoot);
  });
});

/* ── TASK-446 (5.2): redesign_s5 — проброс флага и загрузчик checkin-live ──────── */

describe('TASK-446 redesign_s5', () => {
  it('кэш только с s5 (season_ui:false): флаг доезжает, season-режим не включается', () => {
    const s = bootShell({
      stored: { u: '42', season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: true, redesign_s2: false, redesign_s3: false, at: Date.now() },
      response: { season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: true, redesign_s2: false, redesign_s3: false, redesign_s4: false },
    });
    assert.deepEqual(s.startFlags, { season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: true, redesign_s2: false, redesign_s3: false, redesign_s4: false });
  });

  it('сервер прислал redesign_s5: uiFlags и кэш его сохраняют', async () => {
    const s = bootShell({ response: { season_ui: true, bookings_tab: false, redesign_s1: false, redesign_s5: true, redesign_s2: false, redesign_s3: false, redesign_s4: false } });
    await s.runTimers();
    assert.equal(s.window.ClientShell.uiFlags().redesign_s5, true);
    assert.equal(JSON.parse(s.store.get(KEY)).redesign_s5, true);
  });

  it('s5 на странице «Лёд»: подгружаются checkin-sheet.css, checkin-sheet.js, checkin-live.js', async () => {
    const s = bootShell({
      pathname: '/webapp/ice',
      stored: { u: '42', season_ui: false, redesign_s5: true, redesign_s2: false, redesign_s3: false, at: Date.now() },
      response: { season_ui: false, redesign_s5: true, redesign_s2: false, redesign_s3: false, redesign_s4: false },
    });
    await s.runTimers();
    const srcs = s.domOps.filter(([k]) => k === 'head').map(([, c]) => c.src || c.href || '');
    assert.equal(srcs.filter((x) => x.includes('checkin-sheet.css')).length, 1);
    assert.equal(srcs.filter((x) => x.includes('checkin-sheet.js')).length, 1);
    assert.equal(srcs.filter((x) => x.includes('checkin-live.js')).length, 1);
  });

  /* PDEC-040 батч C: главная тоже в списке страниц — там карточки «Ты на
     катке?» и «Твоя компания». Ленивый пакет шире листа отметки: значки +
     заглушка шаринга. */
  it('s5 на «Я», катке и главной грузит ленивый пакет; флаг выключен — ни одного тега', async () => {
    for (const path of ['/webapp/client-me', '/webapp/arena', '/webapp/client-home']) {
      const s = bootShell({
        pathname: path,
        stored: { u: '42', season_ui: false, redesign_s5: true, redesign_s2: false, redesign_s3: false, at: Date.now() },
        response: { season_ui: false, redesign_s5: true, redesign_s2: false, redesign_s3: false, redesign_s4: false },
      });
      await s.runTimers();
      const srcs = s.domOps.filter(([k]) => k === 'head').map(([, c]) => c.src || c.href || '');
      assert.equal(srcs.filter((x) => x.includes('checkin-live.js')).length, 1, path);
      assert.equal(srcs.filter((x) => x.includes('badge-collection.js')).length, 1, path);
      assert.equal(srcs.filter((x) => x.includes('share-sheet-lazy.js')).length, 1, path);
    }
    const off = bootShell({
      pathname: '/webapp/ice',
      stored: { u: '42', season_ui: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, at: Date.now() },
      response: { season_ui: false, redesign_s5: false, redesign_s2: false, redesign_s3: false, redesign_s4: false },
    });
    await off.runTimers();
    assert.equal(off.domOps.filter(([k]) => k === 'head').length, 0);
  });
});

/* ── TASK-447: redesign_s2 — проброс флага ─────────────────────────────────── */

describe('TASK-447 redesign_s2', () => {
  it('кэш только с s2 (season_ui:false): флаг доезжает, season-режим не включается', () => {
    const s = bootShell({
      stored: { u: '42', season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: true, redesign_s3: false, at: Date.now() },
      response: { season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: true, redesign_s3: false, redesign_s4: false },
    });
    assert.deepEqual(s.startFlags, { season_ui: false, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: true, redesign_s3: false, redesign_s4: false });
  });

  it('сервер прислал redesign_s2: uiFlags и кэш его сохраняют', async () => {
    const s = bootShell({ response: { season_ui: true, bookings_tab: false, redesign_s1: false, redesign_s5: false, redesign_s2: true, redesign_s3: false, redesign_s4: false } });
    await s.runTimers();
    assert.equal(s.window.ClientShell.uiFlags().redesign_s2, true);
    assert.equal(JSON.parse(s.store.get(KEY)).redesign_s2, true);
  });

  it('s2 не подгружает никаких ассетов: только флаг для страницы', async () => {
    const s = bootShell({
      pathname: '/webapp/client-home',
      stored: { u: '42', season_ui: false, redesign_s2: true, redesign_s3: false, at: Date.now() },
      response: { season_ui: false, redesign_s2: true, redesign_s3: false, redesign_s4: false },
    });
    await s.runTimers();
    assert.equal(s.domOps.filter(([k]) => k === 'head').length, 0);
    assert.equal(s.window.ClientShell.uiFlags().redesign_s2, true);
  });
});

/* TASK-448: redesign_s3 — та же схема кэша, season-режим не включает. */
describe('shell ui-flags redesign_s3', () => {
  it('кэш s3 переживает season_ui:false и доезжает до старта', () => {
    const s = bootShell({
      stored: { u: '42', season_ui: false, redesign_s3: true, at: Date.now() },
      response: { season_ui: false, redesign_s3: true, redesign_s4: false },
    });
    assert.equal(s.startFlags.redesign_s3, true);
    assert.equal(s.startFlags.season_ui, false);
  });
  it('ответ сервера с s3 пишется в кэш и виден через uiFlags()', async () => {
    const s = bootShell({ response: { season_ui: true, bookings_tab: false, redesign_s3: true, redesign_s4: false } });
    await s.runTimers();
    assert.equal(s.window.ClientShell.uiFlags().redesign_s3, true);
    assert.equal(JSON.parse(s.store.get(KEY)).redesign_s3, true);
  });
  it('без s3 в ответе и в кэше флаг выключен', async () => {
    const s = bootShell({ response: { season_ui: false } });
    await s.runTimers();
    assert.equal(s.window.ClientShell.uiFlags().redesign_s3, false);
  });
});

/* TASK-449: redesign_s4 — вкладки «Лёд»/«Я» v2, та же схема кэша. */
describe('shell ui-flags redesign_s4', () => {
  it('кэш s4 переживает season_ui:false и доезжает до старта', () => {
    const s = bootShell({
      stored: { u: '42', season_ui: false, redesign_s4: true, at: Date.now() },
      response: { season_ui: false, redesign_s4: true },
    });
    assert.equal(s.startFlags.redesign_s4, true);
    assert.equal(s.startFlags.season_ui, false);
  });
  it('ответ сервера с s4 пишется в кэш и виден через uiFlags()', async () => {
    const s = bootShell({ response: { season_ui: true, bookings_tab: false, redesign_s4: true } });
    await s.runTimers();
    assert.equal(s.window.ClientShell.uiFlags().redesign_s4, true);
    assert.equal(JSON.parse(s.store.get(KEY)).redesign_s4, true);
  });
  it('без s4 в ответе и в кэше флаг выключен', async () => {
    const s = bootShell({ response: { season_ui: false } });
    await s.runTimers();
    assert.equal(s.window.ClientShell.uiFlags().redesign_s4, false);
  });
});
