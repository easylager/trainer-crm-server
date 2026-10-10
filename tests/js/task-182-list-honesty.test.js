/**
 * TASK-182: главный экран каталога «честный список».
 *  AC-1 магазины + «Открыто сейчас» в 23:30 → пустое состояние магазинов, вкладка не меняется;
 *       автопереход на «Тренеров» только для честного «в городе нет льда» и не сохраняется.
 *  AC-2 часы через полночь, одна реализация (opening-hours.js) для ice-tab и arena-card.
 *  AC-3 60 мест: все доступны и в ленте («Показать ещё»), и на карте.
 *  AC-4 холодное открытие — ровно один запрос ленты.
 *  F5   сбой подсчёта тренеров не превращает загруженную ленту в «Не удалось загрузить».
 * Тесты обязаны быть независимы от TZ машины: моменты времени задаются явно
 * (ISO с Z/+03:00 или Date.UTC), а не через new Date(y, m, d, h) в локальной зоне.
 * Run: node --test tests/js/task-182-list-honesty.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const modelPath = path.join(webapp, 'ice-tab-model.js');
const arenaModelPath = path.join(webapp, 'arena-card-model.js');
const hoursPath = path.join(webapp, 'opening-hours.js');
const tabSource = fs.readFileSync(path.join(webapp, 'ice-tab.js'), 'utf8');

const REQUIRED_IDS = [
  'iceCityList', 'iceCityPopular', 'iceListSkate', 'iceListCoach', 'iceCaption', 'iceListSec',
  'iceMapSec', 'iceModeSeg', 'iceShopFilters', 'iceSearchSec', 'iceSearchInput', 'iceServiceChips',
  'icePlaceTabs', 'iceCatalogTools', 'iceToolsRow', 'icePlaceMenu', 'iceWhenMenu', 'iceCityName',
  'iceCityChange', 'iceCityChangeMap', 'iceViewSwitch', 'iceViewSwitchIcon', 'iceViewSwitchLabel',
  'iceNearestBtn', 'iceShareBtn', 'iceList', 'iceSearchResults', 'iceShopServiceChips',
  'iceShopMapBar', 'iceShopFiltersPanel', 'iceShopOpenNow', 'iceShopWhenBtn', 'iceShopWhenMenu',
  'iceShopDisciplineBlock', 'iceShopDisciplineChips', 'iceShopActiveFilters', 'iceMapLegend',
  'iceMapCanvas', 'iceMapEmpty', 'iceMapSheet', 'iceNearBtn', 'iceMapOffMap', 'iceMapStage',
  'iceMapLoader', 'iceMapAttrib',
];

function makeElement(id) {
  const listeners = {};
  return {
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
    insertBefore() {},
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
}

async function flushPromises(rounds) {
  for (let i = 0; i < (rounds || 200); i += 1) await Promise.resolve();
}

function json(body, ok) {
  return Promise.resolve({ ok: ok !== false, json: () => Promise.resolve(body) });
}

function param(url, name) {
  const m = new RegExp('[?&]' + name + '=([^&]*)').exec(url);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Подменяет «сейчас» для model (она живёт в контексте Node) на время теста. */
function withFrozenNow(iso, fn) {
  const RealDate = Date;
  const fixed = new RealDate(iso).getTime();
  class FakeDate extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(fixed);
      else super(...args);
    }
    static now() {
      return fixed;
    }
  }
  global.Date = FakeDate;
  return Promise.resolve()
    .then(fn)
    .finally(() => {
      global.Date = RealDate;
    });
}

/**
 * Поднимает ice-tab.js в vm. opts.arenas(url) отдаёт тело /ice/arenas, opts.trainers(url) —
 * тело /trainers (или Promise.reject для сбоя).
 */
async function bootCatalog(opts) {
  opts = opts || {};
  delete require.cache[require.resolve(modelPath)];
  const model = require(modelPath);
  const requests = [];
  const store = {};
  if (opts.savedState) store[model.ICE_STATE_KEY] = JSON.stringify(opts.savedState);
  const elements = {};
  REQUIRED_IDS.forEach((id) => {
    elements[id] = makeElement(id);
  });
  const cities = opts.cities || [{ id: 1, name: 'Минск', skate_count: 60, trainer_count: 3 }];

  const fetchStub = (url) => {
    const u = String(url);
    requests.push(u);
    if (u.includes('/api/public/ice/cities')) return json({ items: cities });
    if (u.includes('/api/public/ice/arenas')) {
      if (opts.fetchFail && opts.fetchFail(u)) return Promise.reject(new Error('offline'));
      return json(opts.arenas(u));
    }
    if (u.includes('/api/public/trainers')) {
      if (opts.trainers) return opts.trainers(u);
      return json({ items: [], total: 0 });
    }
    return json({});
  };

  const mapCalls = [];
  const mapCtl = {
    setListItems(items) {
      mapCalls.push((items || []).slice());
    },
    start: () => Promise.resolve(),
    refresh() {},
    resize() {},
    leaveCity() {},
  };

  const sandboxWindow = {
    IceTabModel: model,
    IceMap: { mount: () => mapCtl },
    location: { search: opts.search == null ? '?city_id=1' : opts.search },
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
      querySelector: () => null,
      addEventListener() {},
    },
    fetch: fetchStub,
    URLSearchParams,
    Promise,
    console,
  });

  vm.runInContext(tabSource, context);
  await flushPromises();
  const persisted = () => JSON.parse(store[model.ICE_STATE_KEY] || '{}');
  return { requests, persisted, model, elements, mapCalls };
}

const arenaCalls = (requests) => requests.filter((u) => u.includes('/api/public/ice/arenas'));
const trainerCalls = (requests) => requests.filter((u) => u.includes('/api/public/trainers'));

/** Сервер как list_public_ice_arenas: offset из cursor, limit ≤ 100, total — весь город. */
function pagedPlaces(n) {
  const all = Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    slug: 'place-' + (i + 1),
    name: 'Place-' + String(i + 1).padStart(3, '0'),
    venue_type: 'ice',
    latitude: 53.9 + i / 1000,
    longitude: 27.56,
  }));
  return (u) => {
    const limit = Math.min(Number(param(u, 'limit') || 50), 100);
    const offset = Number(param(u, 'cursor') || 0);
    const page = all.slice(offset, offset + limit);
    return {
      items: page,
      total: all.length,
      next_cursor: offset + limit < all.length ? String(offset + limit) : null,
      venue_type_facets: [{ key: 'ice', count: all.length }],
    };
  };
}

function placeNames(html) {
  return new Set(String(html).match(/Place-\d{3}/g) || []);
}

function clickLoadMore(elements) {
  const target = {
    closest: (sel) => (sel === '[data-ice-more]' ? target : null),
  };
  elements.iceList.dispatch('click', { target, preventDefault() {} });
}

describe('TASK-182 AC-1: магазины не превращаются в тренеров', () => {
  const shop = {
    id: 501,
    name: 'SportContinent',
    venue_type: 'shop',
    shop_services: ['retail'],
    opening_hours: { daily: { open: '11:00', close: '18:00' } },
  };

  it('магазины + «Открыто сейчас» в 23:30 по Минску → пустое состояние магазинов, вкладка остаётся', async () => {
    await withFrozenNow('2026-10-06T20:30:00Z', async () => {
      const { requests, persisted, elements } = await bootCatalog({
        savedState: { intent: 'skate', cityId: 1, venueTypes: ['shop'], shopOpenNow: true },
        arenas: () => ({ items: [shop], total: 1, next_cursor: null, venue_type_facets: [{ key: 'shop', count: 1 }] }),
      });
      const shopCall = arenaCalls(requests).find((u) => /venue_type=shop/.test(u));
      assert.ok(shopCall, requests.join(' | '));
      assert.deepEqual(trainerCalls(requests), [], 'тренеры не запрашивались');
      const saved = persisted();
      assert.equal(saved.intent, 'skate');
      assert.deepEqual(saved.venueTypes, ['shop']);
      assert.equal(saved.shopOpenNow, true);
      assert.match(elements.iceListSkate.innerHTML, /Сейчас никто не подходит/);
      assert.equal(elements.iceListCoach.hidden, true, 'лента тренеров не показана');
    });
  });

  it('честное «в городе нет льда» → тренеры на экране, но сохранён прежний выбор', async () => {
    const { requests, persisted, elements } = await bootCatalog({
      cities: [{ id: 1, name: 'Бобруйск', skate_count: null, trainer_count: 2 }],
      arenas: () => ({ items: [], total: 0, next_cursor: null, venue_type_facets: [] }),
      trainers: () => json({ items: [{ id: 7, name: 'Тренер' }], total: 1 }),
    });
    assert.ok(trainerCalls(requests).length >= 1, 'тренеры загружены');
    assert.equal(elements.iceListSkate.hidden, true, 'на экране лента тренеров');
    assert.equal(persisted().intent, 'skate', 'автопереход не записан как выбор человека');
  });

  it('пустой чип «Зал» — не повод уводить на тренеров', async () => {
    const { requests, persisted } = await bootCatalog({
      savedState: { intent: 'skate', cityId: 1, venueTypes: ['gym'] },
      arenas: () => ({ items: [], total: 0, next_cursor: null, venue_type_facets: [{ key: 'ice', count: 3 }] }),
    });
    assert.deepEqual(trainerCalls(requests), []);
    assert.deepEqual(persisted().venueTypes, ['gym']);
  });

  it('noIceInCity: только лента мест и total = 0 от сервера', () => {
    delete require.cache[require.resolve(modelPath)];
    const M = require(modelPath);
    assert.equal(M.noIceInCity('skate', [], { items: [], total: 0 }), true);
    assert.equal(M.noIceInCity('skate', ['ice'], { items: [], total: 0 }), true);
    assert.equal(M.noIceInCity('skate', ['shop'], { items: [], total: 0 }), false);
    assert.equal(M.noIceInCity('skate', ['gym'], { items: [], total: 0 }), false);
    assert.equal(M.noIceInCity('skate', [], { items: [], total: 3 }), false);
    assert.equal(M.noIceInCity('skate', [], null), false);
    assert.equal(M.noIceInCity('coach', [], { items: [], total: 0 }), false);
  });
});

describe('TASK-182 AC-2: часы через полночь, одна реализация', () => {
  const OH = require(hoursPath);

  it('10:00–00:00 открыт в 12:00 и в 23:59, закрыт в 00:30', () => {
    const h = { daily: { open: '10:00', close: '00:00' } };
    assert.equal(OH.isOpenAt(h, 2, 12 * 60), true);
    assert.equal(OH.isOpenAt(h, 2, 23 * 60 + 59), true);
    assert.equal(OH.isOpenAt(h, 2, 30), false);
    assert.equal(OH.isOpenAt(h, 2, 9 * 60), false);
  });

  it('18:00–02:00 открыт в 01:00 — в том числе как вчерашний хвост', () => {
    const daily = { daily: { open: '18:00', close: '02:00' } };
    assert.equal(OH.isOpenAt(daily, 3, 60), true);
    assert.equal(OH.isOpenAt(daily, 3, 3 * 60), false);
    // Только пятница 18–02; в субботу 01:00 ещё открыто, в субботу 19:00 — нет.
    const friOnly = { weekly: { fri: [['18:00', '02:00']] } };
    assert.equal(OH.isOpenAt(friOnly, 5, 60), true);
    assert.equal(OH.isOpenAt(friOnly, 5, 19 * 60), false);
    assert.equal(OH.isOpenAt(friOnly, 4, 19 * 60), true);
  });

  it('фильтр «Открыто сейчас» вкладки «Лёд» (по Минску): 10:00–00:00 в 12:00, 18:00–02:00 в 01:00', () => {
    delete require.cache[require.resolve(modelPath)];
    const M = require(modelPath);
    const filters = { shopOpenNow: true };
    const midnight = { opening_hours: { daily: { open: '10:00', close: '00:00' } } };
    const night = { opening_hours: { daily: { open: '18:00', close: '02:00' } } };
    // 12:00 Минск = 09:00 UTC; 01:00 Минск = 22:00 UTC предыдущего дня.
    assert.equal(M.shopMatchesHours(midnight, filters, new Date('2026-10-06T09:00:00Z')), true);
    assert.equal(M.shopMatchesHours(night, filters, new Date('2026-10-05T22:00:00Z')), true);
    assert.equal(M.shopMatchesHours(night, filters, new Date('2026-10-06T09:00:00Z')), false);
    // «Сегодня вечером» видит ночной интервал (раньше open < close отсекал его).
    assert.equal(
      M.shopMatchesHours(night, { shopWhen: 'evening' }, new Date('2026-10-06T09:00:00Z')),
      true
    );
  });

  it('карточка места: та же логика («открыт до 00:00», «открыт до 02:00»)', () => {
    delete require.cache[require.resolve(arenaModelPath)];
    const A = require(arenaModelPath);
    // Момент задаётся явно по Минску (UTC+3, без DST), а не в TZ машины.
    const at = (h, m) => new Date(Date.UTC(2026, 9, 6, h - 3, m));
    assert.equal(A.openUntilLabel({ daily: { open: '10:00', close: '00:00' } }, at(12, 0)), 'открыт до 00:00');
    assert.equal(A.openUntilLabel({ daily: { open: '18:00', close: '02:00' } }, at(1, 0)), 'открыт до 02:00');
  });

  it('дублей нет: обе модели берут часы из opening-hours.js', () => {
    for (const file of ['ice-tab-model.js', 'arena-card-model.js']) {
      const src = fs.readFileSync(path.join(webapp, file), 'utf8');
      assert.match(src, /require\('\.\/opening-hours\.js'\)/, file);
      assert.match(src, /require\('\.\/minsk-time\.js'\)/, file);
      assert.doesNotMatch(src, /function (normHhmm|normalizeHhmm|parseDayIntervals|hhmmInInterval|hhmmToMinutes)\(/, file);
    }
  });

  it('страницы, где есть модели, подключают opening-hours.js раньше них', () => {
    const pages = fs.readdirSync(webapp).filter((f) => f.endsWith('.html'));
    let checked = 0;
    for (const page of pages) {
      const html = fs.readFileSync(path.join(webapp, page), 'utf8');
      const models = ['ice-tab-model.js', 'arena-card-model.js']
        .map((m) => html.indexOf('src="' + m))
        .filter((i) => i >= 0);
      if (!models.length) continue;
      checked += 1;
      const oh = html.indexOf('src="opening-hours.js');
      const mt = html.indexOf('src="minsk-time.js');
      assert.ok(oh >= 0, page + ': нет opening-hours.js');
      assert.ok(mt >= 0, page + ': нет minsk-time.js');
      assert.ok(oh < Math.min(...models), page + ': opening-hours.js после модели');
      assert.ok(mt < Math.min(...models), page + ': minsk-time.js после модели');
    }
    assert.ok(checked >= 2);
  });
});

describe('TASK-182 AC-3: 60 мест — все в ленте и на карте', () => {
  it('лента: 50 + «Показать ещё» → 60, подпись не обещает больше', async () => {
    const { requests, elements } = await bootCatalog({ arenas: pagedPlaces(60) });
    assert.equal(placeNames(elements.iceListSkate.innerHTML).size, 50);
    assert.match(elements.iceListSkate.innerHTML, /data-ice-more/);
    assert.match(elements.iceCaption.textContent, /^60 /);

    clickLoadMore(elements);
    await flushPromises();
    const names = placeNames(elements.iceListSkate.innerHTML);
    assert.equal(names.size, 60);
    assert.ok(names.has('Place-060'));
    assert.doesNotMatch(elements.iceListSkate.innerHTML, /data-ice-more/, 'кнопка исчезла, хвоста нет');
    const more = arenaCalls(requests).pop();
    assert.equal(param(more, 'cursor'), '50', more);
  });

  it('карта: пины по всем 60, даже если лента показала только первую страницу', async () => {
    const { elements, mapCalls, requests } = await bootCatalog({ arenas: pagedPlaces(60) });
    elements.iceViewSwitch.dispatch('click', {});
    await flushPromises();
    const last = mapCalls[mapCalls.length - 1];
    assert.equal(last.length, 60, 'на карту ушло ' + last.length);
    assert.equal(new Set(last.map((it) => it.id)).size, 60);
    const mapPage = arenaCalls(requests).pop();
    assert.equal(param(mapPage, 'limit'), '100');
    assert.equal(param(mapPage, 'cursor'), '50');
    assert.equal(placeNames(elements.iceListSkate.innerHTML).size, 50, 'лента не раздулась сама');
  });

  it('250 мест: карта листает страницы по 100, пока сервер отдаёт next_cursor', async () => {
    const { elements, mapCalls } = await bootCatalog({ arenas: pagedPlaces(250) });
    elements.iceViewSwitch.dispatch('click', {});
    await flushPromises(400);
    assert.equal(mapCalls[mapCalls.length - 1].length, 250);
  });

  it('магазины (клиентские фильтры) получают весь набор города', async () => {
    const shops = pagedPlaces(130);
    const { elements } = await bootCatalog({
      savedState: { intent: 'skate', cityId: 1, venueTypes: ['shop'] },
      arenas: (u) => {
        const body = shops(u);
        body.items = body.items.map((it) => Object.assign({}, it, { venue_type: 'shop' }));
        return body;
      },
    });
    assert.equal(placeNames(elements.iceListSkate.innerHTML).size, 130);
    assert.match(elements.iceCaption.textContent, /^130 /);
  });
});

describe('TASK-182 AC-4: холодное открытие — один запрос ленты', () => {
  it('?city_id=1 → ровно один /ice/arenas', async () => {
    const { requests } = await bootCatalog({ arenas: pagedPlaces(3) });
    assert.equal(arenaCalls(requests).length, 1, arenaCalls(requests).join(' | '));
  });

  it('город из sessionStorage → ровно один /ice/arenas', async () => {
    const { requests } = await bootCatalog({
      search: '',
      savedState: { intent: 'skate', cityId: 1, venueTypes: [] },
      arenas: pagedPlaces(3),
    });
    assert.equal(arenaCalls(requests).length, 1, arenaCalls(requests).join(' | '));
  });
});

describe('TASK-182 F5: сбой подсчёта тренеров не ломает ленту', () => {
  it('лента пуста честно, подсчёт тренеров упал → не «Не удалось загрузить список»', async () => {
    const { elements, requests } = await bootCatalog({
      cities: [{ id: 1, name: 'Пинск', place_count: 2 }],
      arenas: () => ({ items: [], total: 0, next_cursor: null, venue_type_facets: [] }),
      trainers: () => Promise.reject(new Error('offline')),
    });
    assert.ok(trainerCalls(requests).length === 1, requests.join(' | '));
    assert.doesNotMatch(elements.iceListSkate.innerHTML, /Не удалось загрузить список/);
    assert.match(elements.iceListSkate.innerHTML, /нет массового катания|нет катков/);
  });
});

function pickCity(elements, id) {
  const item = {
    getAttribute: (name) => (name === 'data-city-id' ? String(id) : null),
  };
  const target = { closest: (sel) => (sel === '[data-city-id]' ? item : null) };
  elements.iceCityList.dispatch('click', { target, preventDefault() {} });
}

describe('TASK-182 ревью: автопереход на тренеров не переезжает в другой город', () => {
  it('cityIntentBasis: autoCoach — это «Катание», выбор человека — как есть', () => {
    delete require.cache[require.resolve(modelPath)];
    const M = require(modelPath);
    assert.equal(M.cityIntentBasis({ intent: 'coach', autoCoach: true }), 'skate');
    assert.equal(M.cityIntentBasis({ intent: 'coach', autoCoach: false }), 'coach');
    assert.equal(M.cityIntentBasis({ intent: 'skate', autoCoach: true }), 'skate');
    const withRinks = { skate_count: 5, trainer_count: 3 };
    assert.equal(M.catalogStateAfterCityChange(withRinks, { intent: 'coach', autoCoach: true }).intent, 'skate');
    assert.equal(M.catalogStateAfterCityChange(withRinks, { intent: 'coach', autoCoach: false }).intent, 'coach');
    const noRinks = { skate_count: 0, trainer_count: 3 };
    assert.equal(M.catalogStateAfterCityChange(noRinks, { intent: 'coach', autoCoach: true }).intent, 'coach');
  });

  it('город A без льда → тренеры; город B с катками → лента катков', async () => {
    const { requests, elements } = await bootCatalog({
      cities: [
        { id: 1, name: 'Бобруйск', skate_count: null, trainer_count: 2 },
        { id: 2, name: 'Минск', skate_count: 3, trainer_count: 9 },
      ],
      arenas: (u) =>
        param(u, 'city_id') === '2'
          ? pagedPlaces(3)(u)
          : { items: [], total: 0, next_cursor: null, venue_type_facets: [] },
      trainers: () => json({ items: [{ id: 7, name: 'Тренер' }], total: 1 }),
    });
    assert.equal(elements.iceListSkate.hidden, true, 'в A на экране тренеры');
    requests.length = 0;
    pickCity(elements, 2);
    await flushPromises();
    assert.ok(arenaCalls(requests).some((u) => param(u, 'city_id') === '2'), requests.join(' | '));
    assert.equal(elements.iceListSkate.hidden, false, 'в B на экране катки');
    assert.equal(placeNames(elements.iceListSkate.innerHTML).size, 3);
  });
});

describe('TASK-182 ревью: сбой догрузки магазинов не стирает первую страницу', () => {
  function shopPages(n) {
    const base = pagedPlaces(n);
    return (u) => {
      const body = base(u);
      body.items = body.items.map((it) => Object.assign({}, it, { venue_type: 'shop' }));
      return body;
    };
  }

  it('страница 2 упала → видны 100 магазинов и «Догрузить остальные»; повтор догружает хвост', async () => {
    const fail = new Set(['100']);
    const { elements, requests } = await bootCatalog({
      savedState: { intent: 'skate', cityId: 1, venueTypes: ['shop'] },
      arenas: shopPages(130),
      fetchFail: (u) => fail.has(param(u, 'cursor') || ''),
    });
    const html = elements.iceListSkate.innerHTML;
    assert.doesNotMatch(html, /Не удалось загрузить список/);
    assert.equal(placeNames(html).size, 100);
    assert.match(html, /data-ice-shop-rest/);
    assert.match(html, /Показали не все магазины/);

    fail.clear();
    requests.length = 0;
    const target = { closest: (sel) => (sel === '[data-ice-shop-rest]' ? target : null) };
    elements.iceList.dispatch('click', { target, preventDefault() {} });
    await flushPromises();
    assert.equal(arenaCalls(requests).length, 1, requests.join(' | '));
    assert.equal(param(arenaCalls(requests)[0], 'cursor'), '100');
    const after = elements.iceListSkate.innerHTML;
    assert.equal(placeNames(after).size, 130);
    assert.doesNotMatch(after, /data-ice-shop-rest/);
  });
});
