/**
 * Интеграция: смена города сбрасывает сегмент «Магазины» и не оставляет старую выдачу.
 * Run: node --test tests/js/ice-tab-city-change.test.js
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

async function bootCatalog(opts) {
  opts = opts || {};
  delete require.cache[require.resolve(modelPath)];
  const model = require(modelPath);
  const requests = [];
  const store = {};
  const savedState = opts.savedState;
  if (savedState) store[model.ICE_STATE_KEY] = JSON.stringify(savedState);

  const elements = {};
  REQUIRED_IDS.forEach((id) => {
    elements[id] = makeElement(id);
  });

  const minskShop = {
    id: 501,
    name: 'SportContinent',
    venue_type: 'shop',
    district: 'Центральный',
    address: 'ул. Притыцкого, 27',
    shop_services: ['retail'],
    opening_hours: { daily: { open: '11:00', close: '18:00' } },
  };

  const fetchStub = (url) => {
    requests.push(String(url));
    const u = String(url);
    if (u.includes('/api/public/ice/cities')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            items: [
              { id: 1, name: 'Минск', skate_count: 5, trainer_count: 3 },
              { id: 2, name: 'Бобруйск', skate_count: 1, trainer_count: 1 },
            ],
          }),
      });
    }
    if (u.includes('/api/public/ice/arenas')) {
      if (/[?&]city_id=2(&|$)/.test(u)) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [],
              total: 0,
              venue_type_facets: [{ key: 'ice', count: 1 }],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            items: [minskShop],
            total: 1,
            venue_type_facets: [{ key: 'shop', count: 1 }],
          }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  };

  const sandboxWindow = {
    IceTabModel: model,
    location: { search: opts.search || '?city_id=1' },
    sessionStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => {
        store[k] = String(v);
      },
    },
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener() {},
    setTimeout: (fn, ms) => {
      /* boot ставит 3500ms fallback до resolveCity — в тесте не гоняем раньше времени. */
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
  await flushPromises(120);

  return { requests, store, model, elements };
}

function arenasRequests(requests) {
  return requests.filter((u) => u.includes('/api/public/ice/arenas'));
}

function simulateCityPick(elements, cityId, name) {
  const target = {
    getAttribute(attr) {
      if (attr === 'data-city-id') return String(cityId);
      if (attr === 'data-city-name') return name;
      return null;
    },
    closest(sel) {
      return sel === '[data-city-id]' ? target : null;
    },
  };
  elements.iceCityList.dispatch('click', { target });
}

describe('ice-tab: смена города и магазины', () => {
  it('из «Магазинов» Минска → Бобруйск: без venue_type=shop, state очищен, старая карточка не в DOM', async () => {
    const { requests, store, model, elements } = await bootCatalog({
      search: '?city_id=1',
      savedState: {
        intent: 'skate',
        cityId: 1,
        cityName: 'Минск',
        venueTypes: ['shop'],
        shopService: '',
        shopOpenNow: false,
      },
    });

    const arenaCalls = arenasRequests(requests);
    assert.ok(arenaCalls.length >= 1, requests.join(' | '));
    assert.ok(
      arenaCalls.some((u) => /[?&]venue_type=shop(&|$)/.test(u)),
      'ожидали venue_type=shop в одном из запросов: ' + arenaCalls.join(' | ')
    );
    const shopCall = arenaCalls.find((u) => /[?&]venue_type=shop(&|$)/.test(u));

    assert.ok(
      elements.iceListSkate.innerHTML.includes('SportContinent'),
      'до смены города виден минский магазин; html=' + elements.iceListSkate.innerHTML.slice(0, 200)
    );

    simulateCityPick(elements, 2, 'Бобруйск');
    await flushPromises(60);

    const after = arenasRequests(requests);
    assert.ok(after.length >= 2, after.join(' | '));
    const last = after[after.length - 1];
    assert.match(last, /[?&]city_id=2(&|$)/, last);
    assert.ok(!/[?&]venue_type=shop(&|$)/.test(last), 'после смены города не фильтруем как магазины: ' + last);

    const persisted = JSON.parse(store[model.ICE_STATE_KEY] || '{}');
    assert.deepEqual(persisted.venueTypes, []);
    assert.equal(persisted.shopService, '');
    assert.equal(persisted.shopOpenNow, false);

    assert.ok(
      !elements.iceListSkate.innerHTML.includes('SportContinent'),
      'минский магазин не должен оставаться после пустого ответа по Бобруйску'
    );
  });
});
