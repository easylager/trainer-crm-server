/**
 * Шторка фильтров магазинов на карте: панель в mount, клики по чипам, repair после visibility.
 * Run: node --test tests/js/ice-tab-shop-filters-sheet.test.js
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

function chipTarget(key, attr) {
  attr = attr || 'data-shop-service';
  const btn = {
    getAttribute(a) {
      if (a === attr) return key;
      return null;
    },
    closest(sel) {
      if (sel === '[' + attr + ']') return btn;
      if (sel === '#iceShopWhenMenu') return null;
      return null;
    },
  };
  return btn;
}

async function flushPromises(rounds) {
  for (let i = 0; i < (rounds || 40); i += 1) await Promise.resolve();
}

async function bootShopsOnMap() {
  delete require.cache[require.resolve(modelPath)];
  const model = require(modelPath);
  const store = {};
  const ids = [
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
    'iceShopMapFiltersBtn',
    'iceShopMapFiltersLabel',
    'iceShopFiltersListWrap',
    'iceShopFiltersPanel',
    'iceShopSheetPanelMount',
    'iceShopSheetRoot',
    'iceShopSheetOverlay',
    'iceShopSheet',
    'iceShopSheetHandle',
    'iceShopSheetDone',
    'iceShopSheetReset',
    'iceShopOpenNow',
    'iceShopWhenBtn',
    'iceShopWhenMenu',
    'iceShopDisciplineBlock',
    'iceShopDisciplineChips',
    'iceShopActiveFilters',
    'iceMapLegend',
  ];
  const elements = {};
  ids.forEach((id) => {
    elements[id] = makeElement(id);
  });
  elements.iceShopSheet.querySelector = (sel) => {
    if (sel === '.ice-shop-sheet__head') return makeElement('iceShopSheetHead');
    return null;
  };

  const minskShop = {
    id: 501,
    name: 'SportContinent',
    venue_type: 'shop',
    district: 'Центральный',
    address: 'ул. Притыцкого, 27',
    shop_services: ['retail', 'sharpening'],
    opening_hours: { daily: { open: '11:00', close: '18:00' } },
  };

  const fetchStub = (url) => {
    const u = String(url);
    if (u.includes('/api/public/ice/cities')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            items: [{ id: 1, name: 'Минск', skate_count: 5, trainer_count: 3 }],
          }),
      });
    }
    if (u.includes('/api/public/ice/arenas')) {
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

  const visListeners = [];
  const sandboxWindow = {
    IceTabModel: model,
    IceMap: {
      mount: () => ({
        refresh() {},
        setListItems() {},
        snapPeek() {},
        start: () => Promise.resolve(),
        resize() {},
      }),
    },
    location: { search: '?city_id=1' },
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
      visibilityState: 'visible',
      body: makeElement('body'),
      getElementById: (id) => elements[id] || null,
      querySelectorAll: () => [],
      addEventListener(type, fn) {
        if (type === 'visibilitychange') visListeners.push(fn);
      },
    },
    fetch: fetchStub,
    URLSearchParams,
    Promise,
    console,
  });

  vm.runInContext(tabSource, context);
  await flushPromises(120);

  elements.icePlaceTabs.dispatch('click', {
    target: {
      getAttribute: (a) => (a === 'data-place-type' ? 'shop' : null),
      closest: (sel) => (sel === '[data-place-type]' ? elements.icePlaceTabs : null),
    },
  });
  await flushPromises(40);

  elements.iceViewSwitch.dispatch('click', { target: elements.iceViewSwitch });
  await flushPromises(20);

  return { elements, visListeners, store, model };
}

describe('ice-tab: шторка фильтров магазинов', () => {
  it('открытие sheet: панель в mount, клик по чипу, repair после visibility', async () => {
    const { elements, visListeners, store, model } = await bootShopsOnMap();

    elements.iceShopMapFiltersBtn.dispatch('click', {
      target: elements.iceShopMapFiltersBtn,
      preventDefault() {},
      stopPropagation() {},
    });

    assert.equal(
      elements.iceShopFiltersPanel.parentNode,
      elements.iceShopSheetPanelMount,
      'панель должна жить в шторке'
    );
    assert.equal(elements.iceShopSheetRoot.hidden, false);

    elements.iceShopFiltersPanel.dispatch('click', { target: chipTarget('retail') });
    await flushPromises(10);

    const persisted = JSON.parse(store[model.ICE_STATE_KEY] || '{}');
    assert.equal(persisted.shopService, 'retail');

    visListeners.forEach((fn) => fn());
    await flushPromises(10);

    assert.equal(
      elements.iceShopFiltersPanel.parentNode,
      elements.iceShopSheetPanelMount,
      'после visibilitychange панель не должна уезжать в скрытый list-wrap'
    );
  });
});
