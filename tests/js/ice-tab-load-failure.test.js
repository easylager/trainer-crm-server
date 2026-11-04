/**
 * Сбой сервера не маскируется под успех или пустую ленту:
 *  - лента катков при 5xx → «Повторить», а не «катков нет»;
 *  - 5xx не сбрасывает фильтр «Зимой»;
 *  - «Хочу кататься» пишет «Записали» только после 2xx.
 * Run: node --test tests/js/ice-tab-load-failure.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const modelPath = path.join(webapp, 'ice-tab-model.js');
const tabSource = fs.readFileSync(path.join(webapp, 'ice-tab.js'), 'utf8');

const REQUIRED_IDS = [
  'iceCityList',
  'iceCityPopular',
  'iceListSkate',
  'iceListCoach',
  'iceCaption',
  'iceListSec',
  'iceMapSec',
  'iceModeSeg',
  'iceShopFilters',
  'iceSearchSec',
  'iceSearchInput',
  'iceServiceChips',
  'icePlaceTabs',
  'iceCatalogTools',
  'iceToolsRow',
  'icePlaceMenu',
  'iceWhenMenu',
  'iceCityName',
  'iceCityChange',
  'iceCityChangeMap',
  'iceViewSwitch',
  'iceViewSwitchIcon',
  'iceViewSwitchLabel',
  'iceNearestBtn',
  'iceShareBtn',
  'iceList',
  'iceSearchResults',
  'iceShopServiceChips',
  'iceShopMapBar',
  'iceShopFiltersPanel',
  'iceShopOpenNow',
  'iceShopWhenBtn',
  'iceShopWhenMenu',
  'iceShopDisciplineBlock',
  'iceShopDisciplineChips',
  'iceShopActiveFilters',
  'iceMapLegend',
];

function makeElement(id) {
  const listeners = {};
  const el = {
    id,
    hidden: false,
    innerHTML: '',
    textContent: '',
    style: {},
    dataset: {},
    parentNode: null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute() {},
    getAttribute: () => null,
    appendChild(child) {
      if (child) child.parentNode = this;
      return child;
    },
    addEventListener(type, fn) {
      if (!listeners[type]) listeners[type] = [];
      listeners[type].push(fn);
    },
    dispatch(type, ev) {
      (listeners[type] || []).forEach((fn) => fn(ev));
    },
  };
  return el;
}

async function flushPromises(rounds) {
  for (let i = 0; i < (rounds || 40); i += 1) await Promise.resolve();
}


function boot(opts) {
  delete require.cache[require.resolve(modelPath)];
  const model = require(modelPath);
  const requests = [];
  const store = {};
  store[model.ICE_STATE_KEY] = JSON.stringify(opts.savedState);
  const elements = {};
  REQUIRED_IDS.forEach((id) => {
    elements[id] = makeElement(id);
  });
  const ctl = { arenas: opts.arenas, interest: opts.interest || (() => ({ ok: true, body: { ok: true, identified: true } })) };
  const reply = (r) =>
    Promise.resolve({ ok: r.ok, status: r.status || (r.ok ? 200 : 500), json: () => Promise.resolve(r.body || {}) });
  const fetchStub = (url, init) => {
    const u = String(url);
    requests.push({ url: u, method: (init && init.method) || 'GET' });
    if (u.includes('/api/public/ice/cities')) {
      return reply({
        ok: true,
        body: { items: [Object.assign({ id: 3, name: 'Гомель', skate_count: 0, trainer_count: 2, map_rink_count: 0 }, opts.city)] },
      });
    }
    if (u.includes('/api/public/ice/arenas')) return reply(ctl.arenas(u));
    if (u.includes('/api/public/ice/interest')) return reply(ctl.interest());
    return reply({ ok: true, body: {} });
  };
  let lastEmpty = null;
  const sandboxWindow = {
    IceTabModel: model,
    /* Настоящий MiniAppEmptyState подменён: нам важны заголовок и обработчик кнопки. */
    MiniAppEmptyState: {
      ICONS: {},
      render(container, o) {
        lastEmpty = o;
        container.innerHTML = '[' + o.title + '|' + o.ctaLabel + ']';
      },
    },
    location: { search: '?city_id=3' },
    sessionStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => {
        store[k] = String(v);
      },
    },
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener() {},
    setTimeout: (fn, ms) => {
      if (ms != null && ms > 1000) return 0;
      fn();
      return 0;
    },
    clearTimeout() {},
    scrollTo() {},
    scrollY: 0,
    navigator: { geolocation: null },
  };
  const context = vm.createContext({
    window: sandboxWindow,
    document: {
      readyState: 'complete',
      body: makeElement('body'),
      getElementById: (id) => elements[id] || null,
      querySelectorAll: () => [],
      addEventListener() {},
    },
    fetch: fetchStub,
    URLSearchParams,
    Promise,
    console,
  });
  vm.runInContext(tabSource, context);
  return { requests, store, model, elements, ctl, lastEmpty: () => lastEmpty };
}

const arenasCalls = (reqs) => reqs.filter((r) => r.url.includes('/api/public/ice/arenas'));

describe('ice-tab: сбой сервера не выдаётся за успех', () => {
  it('5xx на ленте при «Зимой»: «Повторить», фильтр остаётся, запросы все с season=winter', async () => {
    const t = boot({
      city: { skate_count: 3, map_rink_count: 2 },
      savedState: { intent: 'skate', cityId: 3, cityName: 'Гомель', season: 'winter' },
      arenas: () => ({ ok: false, status: 503 }),
    });
    await flushPromises(120);

    const calls = arenasCalls(t.requests);
    assert.ok(calls.length >= 1, JSON.stringify(t.requests));
    calls.forEach((c) => assert.match(c.url, /[?&]season=winter(&|$)/, c.url));
    assert.match(t.elements.iceList.innerHTML + t.elements.iceListSkate.innerHTML, /Не удалось загрузить список\|Повторить/);
    assert.equal(JSON.parse(t.store[t.model.ICE_STATE_KEY]).season, 'winter');

    /* «Повторить» перезапрашивает ту же ленту и снова с «Зимой». */
    t.ctl.arenas = () => ({ ok: false, status: 503 });
    const before = arenasCalls(t.requests).length;
    t.lastEmpty().onCta();
    await flushPromises(60);
    const after = arenasCalls(t.requests);
    assert.equal(after.length, before + 1);
    assert.match(after[after.length - 1].url, /[?&]season=winter(&|$)/);
  });

  it('«Хочу кататься»: при 500 нет «Записали», есть «Повторить»; при 2xx — «Записали»', async () => {
    const t = boot({
      savedState: { intent: 'skate', cityId: 3, cityName: 'Гомель', venueTypes: ['gym'] },
      arenas: () => ({ ok: true, body: { items: [], total: 0, venue_type_facets: [] } }),
      interest: () => ({ ok: false, status: 500 }),
    });
    await flushPromises(120);
    let e = t.lastEmpty();
    assert.equal(e.ctaLabel, 'Хочу кататься здесь', 'ждали экран «Скоро добавим катки»');

    e.onCta();
    await flushPromises(60);
    e = t.lastEmpty();
    assert.equal(e.title, 'Не получилось записать');
    assert.equal(e.ctaLabel, 'Повторить');

    t.ctl.interest = () => ({ ok: true, body: { ok: true, id: 1, identified: true } });
    e.onCta();
    await flushPromises(60);
    assert.equal(t.lastEmpty().title, 'Записали');
    assert.match(t.lastEmpty().hint, /в списке желающих/);
    const posts = t.requests.filter((r) => r.method === 'POST');
    assert.equal(posts.length, 2);
  });

  it('анонимный интерес (identified=false): не обещаем уведомление', async () => {
    const t = boot({
      savedState: { intent: 'skate', cityId: 3, cityName: 'Гомель', venueTypes: ['gym'] },
      arenas: () => ({ ok: true, body: { items: [], total: 0, venue_type_facets: [] } }),
      interest: () => ({ ok: true, body: { ok: true, id: 1, identified: false } }),
    });
    await flushPromises(120);
    t.lastEmpty().onCta();
    await flushPromises(60);
    assert.equal(t.lastEmpty().title, 'Записали');
    assert.doesNotMatch(t.lastEmpty().hint, /в списке желающих/);
  });
});
