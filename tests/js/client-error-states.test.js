/**
 * Сбой сети не маскируется под «ничего нет» / «свежее»:
 *  - поиск при 5xx → «Не удалось выполнить поиск» с повтором;
 *  - прошедший день («Ср 28.10») не живёт в чипе «когда»;
 *  - карточка катка: сбой расписания стирает старое, медленная сеть кончается ошибкой с повтором;
 *  - двойной тап по 🔔 — один запрос.
 * Run: node --test tests/js/client-error-states.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const tabSource = fs.readFileSync(path.join(webapp, 'ice-tab.js'), 'utf8');
const arenaSource = fs.readFileSync(path.join(webapp, 'arena-card.js'), 'utf8');
const iceModelPath = path.join(webapp, 'ice-tab-model.js');
const arenaModelPath = path.join(webapp, 'arena-card-model.js');

function makeElement(id) {
  const listeners = {};
  const el = {
    id,
    hidden: false,
    innerHTML: '',
    textContent: '',
    value: '',
    style: {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute() {},
    getAttribute: () => null,
    addEventListener(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    dispatch(type, ev) {
      (listeners[type] || []).forEach((fn) => fn(ev || { target: el }));
    },
  };
  return el;
}

async function flush(n) {
  for (let i = 0; i < (n || 80); i += 1) await Promise.resolve();
}

const json = (body, ok = true, status = 200) => Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

describe('поиск при сбое сервера', () => {
  it('500 → «Не удалось выполнить поиск» и «Повторить», а не «ничего нет»', async () => {
    delete require.cache[require.resolve(iceModelPath)];
    const model = require(iceModelPath);
    const ids = [
      'iceSearchSec', 'iceListSec', 'iceMapSec', 'iceSearchResults', 'iceSearchInput', 'iceList',
      'iceCityList', 'iceCityPopular', 'iceListSkate', 'iceListCoach', 'iceCaption', 'iceModeSeg',
      'icePlaceTabs', 'iceServiceChips', 'iceNearestBtn', 'iceCatalogHeader', 'iceShopFilters',
      'iceViewSwitch', 'iceCityChange', 'iceCityChangeMap', 'btnBack', 'btnHome', 'iceShareBtn',
    ];
    const elements = {};
    ids.forEach((id) => { elements[id] = makeElement(id); });
    let lastEmpty = null;
    const fetchImpl = (url) => {
      const u = String(url);
      if (u.includes('/search')) return json({}, false, 500);
      if (u.includes('/api/public/ice/cities')) {
        return json({ items: [{ id: 1, name: 'Минск', skate_count: 5, trainer_count: 3, map_rink_count: 2 }] });
      }
      if (u.includes('/api/public/ice/arenas')) return json({ items: [], total: 0 });
      return json({});
    };
    const win = {
      IceTabModel: model,
      MiniAppEmptyState: {
        ICONS: {},
        render(c, o) { lastEmpty = o; c.innerHTML = '[' + o.title + ']'; },
      },
      location: { search: '?city_id=1' },
      sessionStorage: { getItem: () => null, setItem() {} },
      localStorage: { getItem: () => null, setItem() {} },
      addEventListener() {},
      setTimeout: (fn, ms) => { if (ms != null && ms > 1000) return 0; fn(); return 0; },
      clearTimeout() {},
      scrollTo() {},
      scrollY: 0,
      navigator: { geolocation: null },
    };
    const ctx = vm.createContext({
      window: win,
      document: {
        readyState: 'complete',
        visibilityState: 'visible',
        body: makeElement('body'),
        getElementById: (id) => elements[id] || null,
        querySelectorAll: () => [],
        addEventListener() {},
      },
      fetch: fetchImpl,
      URLSearchParams,
      Promise,
      console,
    });
    vm.runInContext(tabSource, ctx);
    await flush(120);
    elements.iceSearchInput.value = 'каток';
    elements.iceSearchInput.dispatch('input');
    await flush(60);
    assert.equal(lastEmpty && lastEmpty.title, 'Не удалось выполнить поиск');
    assert.equal(lastEmpty.ctaLabel, 'Повторить');
  });
});

describe('выбранный день в прошлом', () => {
  const M = () => {
    delete require.cache[require.resolve(iceModelPath)];
    return require(iceModelPath);
  };
  /* Минск — UTC+3 без перевода часов. */
  const iso = (offset) => new Date(Date.now() + 3 * 3600000 + offset * 86400000).toISOString().slice(0, 10);

  it('сохранённый день из прошлой недели отбрасывается, сегодняшний и будущий — нет', () => {
    const m = M();
    const hydrate = (day) => m.hydrateWhenFromSaved({ when: 'day', whenDay: day }, 'skate', []);
    assert.equal(hydrate(iso(-7)), null);
    assert.deepEqual(hydrate(iso(0)), { when: 'day', whenDay: iso(0) });
    assert.deepEqual(hydrate(iso(5)), { when: 'day', whenDay: iso(5) });
  });

  it('?day= из прошлого не становится выбором', () => {
    const m = M();
    assert.equal(m.whenBootFromSearch('?day=' + iso(-3)), null);
    assert.deepEqual(m.whenBootFromSearch('?day=' + iso(4)), { when: 'day', whenDay: iso(4) });
  });
});

const CARD = {
  id: 42, name: 'Arena Test Rink', venue_type: 'ice', has_skating: true, tier: 'full',
  in_season: true, address: 'ул. Тестовая, 1', venue_noun: 'каток',
};
const SESSIONS = {
  days: [{
    local_date: '2026-10-05',
    sessions: [{
      id: 7, kind: 'public_skate', starts_at_local: '11:00',
      starts_at_utc: '2026-10-05T08:00:00+00:00', ends_at_utc: '2026-10-05T09:00:00+00:00',
      price_adult_minor: 1200, currency_code: 'BYN',
    }],
  }],
};

async function bootArena(opts) {
  delete require.cache[require.resolve(arenaModelPath)];
  const model = require(arenaModelPath);
  const root = makeElement('arenaRoot');
  const store = {};
  const timers = [];
  if (opts.warm) model.writeArenaWarm({ getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } }, '42', opts.warm, Date.now());
  const posts = [];
  const win = {
    ArenaCardModel: model,
    RuText: {},
    location: { search: '?arena_id=42', href: 'https://example.test/arena' },
    history: { length: 1, back() {} },
    sessionStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } },
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener() {},
    setTimeout: (fn, ms) => {
      if (ms != null && ms >= 5000) { timers.push(fn); return timers.length; }
      fn();
      return 0;
    },
    clearTimeout() {},
    navigator: { clipboard: null },
    Telegram: opts.tg ? { WebApp: { initData: 'init', showAlert() {} } } : undefined,
    GlideWriteAccess: opts.tg ? { gate: () => Promise.resolve('proceed') } : undefined,
  };
  const ctx = vm.createContext({
    window: win,
    document: {
      readyState: 'complete',
      getElementById: (id) => {
        if (id === 'arenaRoot') return root;
        if (id === 'btnHome' || id === 'btnBack' || id === 'headerTitle') return makeElement(id);
        return null;
      },
      addEventListener() {},
    },
    fetch: (url, init) => {
      if (init && init.method === 'POST') posts.push(String(url));
      return opts.fetch(String(url), init);
    },
    AbortController,
    Promise,
    console,
  });
  win.document = ctx.document;
  vm.runInContext(arenaSource, ctx);
  await flush(80);
  return { root, page: win.ArenaCardPage, model, store, timers, posts };
}

const arenaFetch = (sessionsReply) => (u) => {
  if (u.endsWith('/api/public/arenas/42')) return json(CARD);
  if (u.includes('/sessions')) return sessionsReply();
  if (u.includes('/trainers')) return json({ items: [], groups: [] });
  return json({});
};

describe('карточка катка', () => {
  it('сбой сети при тёплом кэше: старое расписание не показано как свежее и стёрто из кэша', async () => {
    const t = await bootArena({
      warm: { card: CARD, sessions: SESSIONS },
      fetch: arenaFetch(() => json({}, false, 503)),
    });
    assert.equal(t.page.state.sessionsError, true);
    assert.equal(t.page.state.sessions, null);
    assert.match(t.root.innerHTML, /Не удалось загрузить расписание/);
    assert.doesNotMatch(t.root.innerHTML, /id="arenaRows"/);
    const warm = JSON.parse(t.store[t.model.ARENA_WARM_KEY || 'glideArenaWarm:v1'])['42'];
    assert.equal(warm.sessions, null);
  });

  it('сеть молчит: по таймауту — «Не удалось загрузить карточку» и «Повторить»', async () => {
    const t = await bootArena({ fetch: () => new Promise(() => {}) });
    assert.doesNotMatch(t.root.innerHTML, /Не удалось загрузить карточку/);
    assert.ok(t.timers.length >= 1, 'ждали таймер таймаута');
    t.timers.forEach((fn) => fn());
    await flush(80);
    assert.match(t.root.innerHTML, /Не удалось загрузить карточку/);
    assert.match(t.root.innerHTML, /data-action="retry-load"/);
  });

  it('двойной тап по 🔔 даёт один POST', async () => {
    const t = await bootArena({
      tg: true,
      fetch: (u, init) => {
        if (init && init.method === 'POST') return json({ watch: { id: 5 } });
        return arenaFetch(() => json(SESSIONS))(u);
      },
    });
    t.page.subscribeIceWatch('sessions');
    t.page.subscribeIceWatch('sessions');
    await flush(60);
    assert.equal(t.posts.length, 1);
  });
});
