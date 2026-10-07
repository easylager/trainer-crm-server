/**
 * Список катков перерисовывается, когда меняется фильтр или текст карточки.
 * Run: node --test tests/js/ice-tab-list-repaint.test.js
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
  return {
    id,
    hidden: false,
    innerHTML: '',
    textContent: '',
    style: {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector(sel) {
      if (sel === '.ice-board' && String(this.innerHTML).includes('ice-board')) return {};
      return null;
    },
    querySelectorAll: () => [],
    setAttribute() {},
    getAttribute: () => null,
    insertBefore() {},
    appendChild() {},
    addEventListener(type, fn) {
      (listeners[type] || (listeners[type] = [])).push(fn);
    },
    dispatch(type, ev) {
      (listeners[type] || []).forEach((fn) => fn(ev));
    },
  };
}

const IDS = [
  'iceListSkate', 'iceListCoach', 'iceCaption', 'iceList', 'iceShopFilters', 'iceCatalogTools',
  'iceModeSeg', 'iceSearchInput', 'iceShareBtn', 'iceNearestBtn', 'iceViewSwitch',
];

async function flush() {
  for (let i = 0; i < 80; i += 1) await Promise.resolve();
}

function boot(search, arenas) {
  delete require.cache[require.resolve(modelPath)];
  const model = require(modelPath);
  const elements = {};
  IDS.forEach((id) => {
    elements[id] = makeElement(id);
  });
  const fetchImpl = (url) => {
    const u = String(url);
    if (u.includes('/ice/cities')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ items: [{ id: 1, name: 'Минск', skate_count: 4, trainer_count: 1 }] }),
      });
    }
    if (u.includes('/ice/arenas')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(arenas()) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [] }) });
  };
  const sandbox = {
    IceTabModel: model,
    IceMap: { mount: () => ({ setListItems() {}, start: () => Promise.resolve(), refresh() {}, resize() {} }) },
    location: { search },
    sessionStorage: { getItem: () => null, setItem() {} },
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener() {},
    setTimeout: (fn, ms) => {
      if (ms > 1000) return 0;
      fn();
      return 0;
    },
    clearTimeout() {},
    scrollTo() {},
    scrollY: 0,
    navigator: {},
  };
  const ctx = vm.createContext({
    window: sandbox,
    document: {
      readyState: 'complete',
      body: makeElement('body'),
      getElementById: (id) => elements[id] || null,
      querySelectorAll: () => [],
      querySelector: () => null,
      addEventListener() {},
    },
    fetch: fetchImpl,
    URLSearchParams,
    Promise,
    console,
  });
  vm.runInContext(tabSource, ctx);
  return flush().then(() => elements);
}

describe('ice list repaint', () => {
  it('фильтр магазина → пусто → снять фильтр → карточки снова на месте', async () => {
    const elements = await boot('?city_id=1&venue=shop', () => ({
      items: [
        {
          id: 7,
          name: 'Заточка у Юры',
          venue_type: 'shop',
          shop_services: ['skate_rental'],
          thumb: '/t.jpg',
          card: '/c.jpg',
        },
      ],
      total: 1,
    }));
    assert.match(elements.iceListSkate.innerHTML, /Заточка у Юры/);
    elements.iceShopFilters.dispatch('click', {
      target: {
        closest(sel) {
          if (sel === '[data-shop-service]') {
            return { getAttribute: () => 'skate_sharpening', closest: () => null };
          }
          return null;
        },
      },
    });
    assert.match(elements.iceListSkate.innerHTML, /Сейчас никто не подходит/);
    assert.doesNotMatch(elements.iceListSkate.innerHTML, /Заточка у Юры/);
    elements.iceShopFilters.dispatch('click', {
      target: {
        closest(sel) {
          if (sel === '[data-shop-clear]') return { getAttribute: () => 'all', closest: () => null };
          return null;
        },
      },
    });
    assert.match(elements.iceListSkate.innerHTML, /Заточка у Юры/);
  });

  it('те же id с другим временем сеанса перерисовывают текст', async () => {
    let time = '18:15';
    const elements = await boot('?city_id=1', () => ({
      items: [
        {
          id: 3,
          name: 'ТЦ Замок',
          venue_type: 'ice',
          card: '/photos/3_card.jpg',
          thumb: '/photos/3_thumb.jpg',
          live: { kind: 'session', local_date: '2026-10-07', starts_at_local: time, more_count: 1 },
        },
      ],
      total: 1,
      window: { key: 'any', label: '' },
    }));
    assert.match(elements.iceListSkate.innerHTML, /18:15/);
    time = '19:45';
    elements.iceCatalogTools.dispatch('click', {
      target: {
        closest(sel) {
          if (sel === '[data-place-type]') {
            return { getAttribute: () => '', closest: () => true };
          }
          return null;
        },
      },
    });
    await flush();
    assert.match(elements.iceListSkate.innerHTML, /19:45/);
    assert.doesNotMatch(elements.iceListSkate.innerHTML, /18:15/);
  });
});

describe('trainer photo frame', () => {
  it('.ice-acard__ph держит абсолютный img внутри карточки', () => {
    const css = fs.readFileSync(path.join(webapp, 'ice-tab.css'), 'utf8');
    const at = css.indexOf('.ice-acard__ph {');
    const block = css.slice(at, css.indexOf('}', at));
    assert.match(block, /position:\s*relative/);
    assert.match(block, /overflow:\s*hidden/);
    const board = css.slice(css.indexOf('.ice-board__photo {'), css.indexOf('}', css.indexOf('.ice-board__photo {')));
    assert.match(board, /position:\s*relative/);
    assert.match(board, /overflow:\s*hidden/);
  });
});
