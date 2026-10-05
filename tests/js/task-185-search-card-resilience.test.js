/**
 * TASK-185: search generation + arena card partial load.
 * Run: node --test tests/js/task-185-search-card-resilience.test.js
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
    classList: {
      _c: new Set(),
      add(...a) {
        a.forEach((x) => this._c.add(x));
      },
      remove(...a) {
        a.forEach((x) => this._c.delete(x));
      },
      toggle(name, on) {
        if (on === undefined) {
          if (this._c.has(name)) this._c.delete(name);
          else this._c.add(name);
        } else if (on) this._c.add(name);
        else this._c.delete(name);
      },
      contains: (n) => el.classList._c.has(n),
    },
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute() {},
    getAttribute: () => null,
    addEventListener(type, fn) {
      if (!listeners[type]) listeners[type] = [];
      listeners[type].push(fn);
    },
    dispatch(type, ev) {
      (listeners[type] || []).forEach((fn) => fn(ev || { target: el }));
    },
  };
  return el;
}

async function flushPromises(rounds) {
  for (let i = 0; i < (rounds || 60); i += 1) await Promise.resolve();
}

function searchPayload(marker) {
  return {
    groups: [
      {
        type: 'arena',
        items: [{ id: 1, name: marker, city_name: 'Минск', venue_type: 'ice' }],
      },
    ],
  };
}

async function bootIceSearch(fetchImpl) {
  delete require.cache[require.resolve(iceModelPath)];
  const model = require(iceModelPath);
  const store = {};
  const elements = {
    iceSearchSec: makeElement('iceSearchSec'),
    iceListSec: makeElement('iceListSec'),
    iceMapSec: makeElement('iceMapSec'),
    iceSearchResults: makeElement('iceSearchResults'),
    iceSearchInput: makeElement('iceSearchInput'),
    iceList: makeElement('iceList'),
    iceCityList: makeElement('iceCityList'),
    iceCityPopular: makeElement('iceCityPopular'),
    iceListSkate: makeElement('iceListSkate'),
    iceListCoach: makeElement('iceListCoach'),
    iceCaption: makeElement('iceCaption'),
    iceModeSeg: makeElement('iceModeSeg'),
    icePlaceTabs: makeElement('icePlaceTabs'),
    iceServiceChips: makeElement('iceServiceChips'),
    iceNearestBtn: makeElement('iceNearestBtn'),
    iceCatalogHeader: makeElement('iceCatalogHeader'),
    iceShopFilters: makeElement('iceShopFilters'),
    iceViewSwitch: makeElement('iceViewSwitch'),
    iceCityChange: makeElement('iceCityChange'),
    iceCityChangeMap: makeElement('iceCityChangeMap'),
    iceCityPickerClose: makeElement('iceCityPickerClose'),
    btnBack: makeElement('btnBack'),
    btnHome: makeElement('btnHome'),
    iceCityFilter: makeElement('iceCityFilter'),
    iceGeoBtn: makeElement('iceGeoBtn'),
    iceShareBtn: makeElement('iceShareBtn'),
  };
  elements.body = makeElement('body');

  const sandboxWindow = {
    IceTabModel: model,
    location: { search: '?city_id=1', href: 'https://example.test/ice' },
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
      body: elements.body,
      getElementById: (id) => elements[id] || null,
      querySelectorAll: () => [],
      addEventListener() {},
    },
    fetch: fetchImpl,
    URLSearchParams,
    Promise,
    console,
  });

  vm.runInContext(tabSource, context);
  await flushPromises(80);
  return { elements, model, store };
}

async function bootArenaCard(fetchImpl) {
  delete require.cache[require.resolve(arenaModelPath)];
  const model = require(arenaModelPath);
  const root = makeElement('arenaRoot');
  const sandboxWindow = {
    ArenaCardModel: model,
    RuText: {},
    location: { search: '?arena_id=42', href: 'https://example.test/arena' },
    history: { length: 1, back() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener() {},
    setTimeout: (fn) => {
      fn();
      return 0;
    },
    clearTimeout() {},
    navigator: { clipboard: null },
  };

  const context = vm.createContext({
    window: sandboxWindow,
    document: {
      readyState: 'complete',
      getElementById: (id) => {
        if (id === 'arenaRoot') return root;
        if (id === 'headerTitle') return makeElement('headerTitle');
        if (id === 'btnHome' || id === 'btnBack') return makeElement(id);
        return null;
      },
      addEventListener() {},
    },
    fetch: fetchImpl,
    Promise,
    console,
  });
  sandboxWindow.document = context.document;

  vm.runInContext(arenaSource, context);
  await flushPromises(80);
  return { root, page: sandboxWindow.ArenaCardPage, model };
}

describe('TASK-185 AC-1: гонка поиска', () => {
  it('ответы приходят в обратном порядке → на экране результат последнего запроса', async () => {
    const gates = [];
    const fetchImpl = (url) => {
      const u = String(url);
      if (u.includes('/api/public/ice/cities')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ items: [{ id: 1, name: 'Минск', skate_count: 5, trainer_count: 3 }] }),
        });
      }
      if (u.includes('/api/public/ice/arenas')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [], total: 0 }) });
      }
      if (u.includes('/search')) {
        let release;
        const body = new Promise((resolve) => {
          release = resolve;
        });
        gates.push({ url: u, release });
        return body.then((data) => ({ ok: true, json: () => Promise.resolve(data) }));
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    };

    const { elements } = await bootIceSearch(fetchImpl);
    elements.iceSearchInput.value = 'Mi';
    elements.iceSearchInput.dispatch('input');
    elements.iceSearchInput.value = 'Minsk';
    elements.iceSearchInput.dispatch('input');

    assert.equal(gates.length, 2, 'ожидали два поисковых запроса');
    gates[1].release(searchPayload('RESULT-LAST'));
    await flushPromises(10);
    gates[0].release(searchPayload('RESULT-STALE'));
    await flushPromises(20);

    assert.match(elements.iceSearchResults.innerHTML, /RESULT-LAST/);
    assert.doesNotMatch(elements.iceSearchResults.innerHTML, /RESULT-STALE/);
  });
});

describe('TASK-185 AC-2: карточка арены', () => {
  it('/trainers 500 → карточка и сеансы видны, блок тренеров с «Повторить»', async () => {
    const card = {
      id: 42,
      name: 'Arena Test Rink',
      venue_type: 'ice',
      has_skating: true,
      tier: 'full',
      in_season: true,
      address: 'ул. Тестовая, 1',
      venue_noun: 'каток',
    };
    const sessions = {
      days: [
        {
          local_date: '2026-10-05',
          sessions: [
            {
              id: 7,
              kind: 'public_skate',
              starts_at_local: '11:00',
              starts_at_utc: '2026-10-05T08:00:00+00:00',
              ends_at_utc: '2026-10-05T09:00:00+00:00',
              price_adult_minor: 1200,
              currency_code: 'BYN',
            },
          ],
        },
      ],
    };

    const fetchImpl = (url) => {
      const u = String(url);
      if (u.endsWith('/api/public/arenas/42')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(card) });
      }
      if (u.includes('/sessions')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(sessions) });
      }
      if (u.includes('/trainers')) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: 'fail' }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    };

    const { root, page } = await bootArenaCard(fetchImpl);
    await flushPromises(40);

    assert.match(root.innerHTML, /Arena Test Rink/);
    assert.match(root.innerHTML, /Расписание/);
    assert.match(root.innerHTML, /id="arenaRows"/);
    assert.doesNotMatch(root.innerHTML, /Не удалось загрузить расписание/);
    assert.match(root.innerHTML, /Не удалось загрузить тренеров/);
    assert.match(root.innerHTML, /data-action="retry-trainers"/);
    assert.ok(page.state.card, 'карточка должна остаться на экране');
    assert.equal(page.state.trainersError, true);
    assert.equal(page.state.sessionsError, false);
  });
});
