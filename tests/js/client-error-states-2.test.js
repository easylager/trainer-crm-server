/**
 * Три мелочи клиентского приложения:
 *  - «Сообщить об ошибке» вне Telegram не закрывается молча;
 *  - фильтр «когда», не дошедший до сервера, не помечается сохранённым и досылается при `online`;
 *  - предзагрузка расписания считает «сегодня» по Минску, а не по поясу телефона.
 * Run: node --test tests/js/client-error-states-2.test.js
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
const minskSource = fs.readFileSync(path.join(webapp, 'minsk-time.js'), 'utf8');
const iceModelPath = path.join(webapp, 'ice-tab-model.js');
const arenaModelPath = path.join(webapp, 'arena-card-model.js');

function makeElement(id) {
  const listeners = {};
  const classes = new Set();
  const el = {
    id,
    hidden: false,
    innerHTML: '',
    textContent: '',
    value: '',
    style: {},
    dataset: {},
    classList: {
      add: (...a) => a.forEach((x) => classes.add(x)),
      remove: (...a) => a.forEach((x) => classes.delete(x)),
      toggle() {},
      contains: (n) => classes.has(n),
    },
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute() {},
    getAttribute: () => null,
    focus() {},
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

describe('«Сообщить об ошибке» вне Telegram', () => {
  it('не закрывается молча: пользователь получает сообщение, окно остаётся', async () => {
    delete require.cache[require.resolve(arenaModelPath)];
    const model = require(arenaModelPath);
    const ids = ['arenaRoot', 'arenaModal', 'arenaModalForm', 'arenaModalField', 'arenaModalValue', 'arenaModalSubmit', 'arenaModalTitle', 'arenaModalLead'];
    const els = {};
    ids.forEach((id) => { els[id] = makeElement(id); });
    els.arenaModal.classList.add('is-open');
    els.arenaModalValue.value = '10:30';
    els.arenaModalField.value = 'hours';
    const alerts = [];
    const win = {
      ArenaCardModel: model,
      RuText: {},
      location: { search: '', href: 'https://example.test/arena' },
      history: { length: 1, back() {} },
      sessionStorage: { getItem: () => null, setItem() {} },
      localStorage: { getItem: () => null, setItem() {} },
      addEventListener() {},
      setTimeout: (fn, ms) => { if (ms >= 5000) return 0; fn(); return 0; },
      clearTimeout() {},
      navigator: { clipboard: null },
      alert: (t) => alerts.push(String(t)),
    };
    const ctx = vm.createContext({
      window: win,
      document: {
        readyState: 'complete',
        getElementById: (id) => els[id] || (id === 'btnHome' || id === 'btnBack' ? makeElement(id) : null),
        addEventListener() {},
      },
      fetch: () => json({}),
      Promise,
      console,
    });
    win.document = ctx.document;
    vm.runInContext(arenaSource, ctx);
    await flush();
    els.arenaModalForm.dispatch('submit', { preventDefault() {} });
    await flush();
    assert.equal(alerts.length, 1, 'ждали одно сообщение пользователю');
    assert.match(alerts[0], /Telegram/);
    assert.ok(els.arenaModal.classList.contains('is-open'), 'окно не должно закрываться');
  });
});

function bootIce(opts) {
  delete require.cache[require.resolve(iceModelPath)];
  const model = require(iceModelPath);
  const ids = [
    'iceCityList', 'iceCityPopular', 'iceListSkate', 'iceListCoach', 'iceCaption', 'iceModeSeg',
    'icePlaceTabs', 'iceServiceChips', 'iceNearestBtn', 'iceCatalogHeader', 'iceShopFilters',
    'iceViewSwitch', 'iceCityChange', 'iceCityChangeMap', 'btnBack', 'btnHome', 'iceShareBtn',
    'iceList', 'iceSearchSec', 'iceListSec', 'iceMapSec', 'iceSearchResults', 'iceSearchInput',
  ];
  const els = {};
  ids.forEach((id) => { els[id] = makeElement(id); });
  const store = {};
  const online = [];
  const requests = [];
  const win = {
    IceTabModel: model,
    location: { search: '?city_id=1' },
    sessionStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener: (type, fn) => { if (type === 'online') online.push(fn); },
    setTimeout: (fn, ms) => { if (ms != null && ms > 1000) return 0; fn(); return 0; },
    clearTimeout() {},
    scrollTo() {},
    scrollY: 0,
    navigator: { geolocation: null },
    Telegram: { WebApp: { initData: 'init-data' } },
    GlideShareSheet: opts.shareSheet,
    ArenaCardModel: opts.arenaModel,
  };
  const sandbox = {
    window: win,
    document: {
      readyState: 'complete',
      visibilityState: 'visible',
      body: makeElement('body'),
      getElementById: (id) => els[id] || null,
      querySelectorAll: () => [],
      addEventListener() {},
    },
    fetch: (url, init) => {
      requests.push({ url: String(url), method: (init && init.method) || 'GET', body: (init && init.body) || '' });
      return opts.fetch(String(url), init);
    },
    URLSearchParams,
    Promise,
    console,
  };
  win.fetch = sandbox.fetch;
  if (opts.Date) sandbox.Date = opts.Date;
  const ctx = vm.createContext(sandbox);
  if (opts.minsk) {
    vm.runInContext(minskSource, ctx);
    win.MinskTime = ctx.MinskTime;
  }
  vm.runInContext(tabSource, ctx);
  return { els, store, online, requests, model };
}

const baseFetch = (patch) => (u, init) => {
  if (u.includes('/catalog-filters')) return patch(u, init);
  if (u.includes('/api/public/ice/cities')) {
    return json({ items: [{ id: 1, name: 'Минск', skate_count: 5, trainer_count: 3, map_rink_count: 2 }] });
  }
  if (u.includes('/api/public/ice/arenas')) return json({ items: [], total: 0 });
  return json({});
};

describe('фильтр «когда» без сети', () => {
  it('сбой PATCH не помечает фильтр сохранённым; при online он досылается', async () => {
    let fail = true;
    const t = bootIce({
      fetch: baseFetch(() => (fail ? Promise.reject(new Error('offline')) : json({ ok: true }))),
    });
    await flush(400);
    const patches = () => t.requests.filter((r) => r.method === 'PATCH' && r.body.indexOf('ice_when') >= 0);
    assert.ok(patches().length >= 1, 'ждали попытку сохранить на сервере');
    const first = patches().length;
    assert.ok(!('glide_ice_server_synced_v1_when' in t.store), 'после сбоя «синхронизировано» не пишем');
    assert.ok(t.online.length >= 1, 'ждали подписку на online');
    fail = false;
    t.online.forEach((fn) => fn());
    await flush(40);
    assert.equal(patches().length, first + 1, 'при online — повторная отправка');
    assert.ok('glide_ice_server_synced_v1_when' in t.store, 'после успеха — помечено');
  });
});

describe('«сегодня» в предзагрузке расписания', () => {
  it('телефон восточнее Минска: from=день по Минску, а не по телефону', async () => {
    const prevTz = process.env.TZ;
    process.env.TZ = 'Pacific/Auckland'; // UTC+13: 04.11 20:00Z — в Минске ещё 04.11 23:00, у телефона уже 05.11
    try {
      const FIXED = Date.parse('2026-11-04T20:00:00Z');
      const RealDate = Date;
      class FakeDate extends RealDate {
        constructor(...a) { super(...(a.length ? a : [FIXED])); }
        static now() { return FIXED; }
      }
      let inviteArgs = null;
      const t = bootIce({
        Date: FakeDate,
        minsk: true,
        shareSheet: { open: (o) => { inviteArgs = o; } },
        arenaModel: { shareSlots: () => [], ymd: (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`, parseLocalDate: (s) => new FakeDate(s + 'T00:00:00') },
        fetch: baseFetch(() => json({})),
      });
      await flush(120);
      const invite = {
        getAttribute: (n) => ({ 'data-invite-arena': '42', 'data-invite-session': '', 'data-invite-label': '', 'data-invite-place': '' }[n]),
      };
      t.els.iceList.dispatch('click', {
        target: { closest: (sel) => (sel === '[data-invite-arena]' ? invite : null) },
        preventDefault() {},
      });
      await flush(60);
      const call = t.requests.find((r) => r.url.includes('/arenas/42/sessions'));
      assert.ok(call, JSON.stringify(t.requests.map((r) => r.url)));
      assert.match(call.url, /from=2026-11-04(&|$)/, call.url);
      assert.match(call.url, /to=2026-11-17(&|$)/, call.url);
      void inviteArgs;
    } finally {
      if (prevTz === undefined) delete process.env.TZ;
      else process.env.TZ = prevTz;
    }
  });
});
