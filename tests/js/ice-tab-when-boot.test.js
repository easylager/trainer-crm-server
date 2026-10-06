/**
 * TASK-149: boot вкладки «Поиск» применяет ?when=<окно> из ссылки.
 * Run: node --test tests/js/ice-tab-when-boot.test.js
 *
 * ice-tab.js — IIFE без экспортов, state внутри замыкания. Поэтому настоящий исходник
 * исполняется в vm с заглушками окружения, а применённое окно читается по единственному
 * наблюдаемому следу — query запроса к /api/public/ice/arenas (when=…).
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

/** Универсальная заглушка DOM-узла: любой неизвестный метод — no-op. */
function stubElement() {
  const target = {
    hidden: false,
    innerHTML: '',
    textContent: '',
    style: {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => null,
    querySelectorAll: () => [],
    closest: () => null,
    getAttribute: () => null,
  };
  return new Proxy(target, {
    get(t, key) {
      return key in t ? t[key] : () => {};
    },
    set(t, key, value) {
      t[key] = value;
      return true;
    },
  });
}

/**
 * Запускает настоящий boot с заданным location.search и (опционально) состоянием,
 * сохранённым в sessionStorage. Возвращает URL всех запросов и содержимое storage.
 */
async function bootWith(search, savedState, localWhenPref) {
  delete require.cache[require.resolve(modelPath)];
  const model = require(modelPath);
  const requests = [];
  const store = {};
  if (savedState) store[model.ICE_STATE_KEY] = JSON.stringify(savedState);
  const localStore = {};
  if (localWhenPref) {
    localStore[model.ICE_WHEN_PREF_KEY] = JSON.stringify(localWhenPref);
  }

  const fetchStub = (url) => {
    requests.push(String(url));
    let body = {};
    if (String(url).includes('/api/public/ice/cities')) {
      body = { items: [{ id: 1, name: 'Минск', skate_count: 5, trainer_count: 3 }] };
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  };
  const sandboxWindow = {
    IceTabModel: model,
    location: { search },
    sessionStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => {
        store[k] = String(v);
      },
    },
    localStorage: {
      getItem: (k) => (k in localStore ? localStore[k] : null),
      setItem: (k, v) => {
        localStore[k] = String(v);
      },
    },
    addEventListener() {},
    // Fire only zero-delay callbacks synchronously; real timers (e.g. the
    // 20 s fetchJson timeout) never fire inside the test.
    setTimeout: (fn, delay) => {
      if (!delay) fn();
      return 0;
    },
    clearTimeout() {},
    scrollTo() {},
    scrollY: 0,
  };
  const context = vm.createContext({
    window: sandboxWindow,
    document: {
      readyState: 'complete',
      body: stubElement(),
      getElementById: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
    },
    fetch: fetchStub,
    URLSearchParams,
    Promise,
    console,
  });
  vm.runInContext(tabSource, context);
  // boot → resolveCity → fetch → loadArenas; даём цепочке промисов дойти до запроса.
  for (let i = 0; i < 50; i += 1) await Promise.resolve();
  return { requests, store, model };
}

function arenasRequest(requests) {
  return requests.find((u) => u.includes('/api/public/ice/arenas')) || null;
}

describe('TASK-149: ?when= при открытии «Поиска»', () => {
  it('?city_id=1&when=today_evening → запрос списка идёт с окном «вечером»', async () => {
    const { requests } = await bootWith('?city_id=1&when=today_evening');
    const url = arenasRequest(requests);
    assert.ok(url, 'список мест должен быть запрошен: ' + requests.join(' | '));
    assert.match(url, /[?&]when=today_evening(&|$)/);
  });

  it('?intent=coach&when=today_evening → окно не применяется, едут тренеры', async () => {
    const { requests } = await bootWith('?city_id=1&intent=coach&when=today_evening');
    assert.equal(arenasRequest(requests), null);
    assert.ok(
      requests.some((u) => u.includes('/api/public/trainers')),
      'ожидали запрос тренеров: ' + requests.join(' | ')
    );
    assert.ok(!requests.some((u) => u.includes('when=')), requests.join(' | '));
  });

  it('?when=junk → дефолт any, запрос идентичен запросу без параметра', async () => {
    const withJunk = await bootWith('?city_id=1&when=junk');
    const without = await bootWith('?city_id=1');
    assert.match(arenasRequest(withJunk.requests), /[?&]when=any(&|$)/);
    assert.equal(arenasRequest(withJunk.requests), arenasRequest(without.requests));
  });

  it('без ?when= по умолчанию «Любое время» (when=any)', async () => {
    const { requests } = await bootWith('?city_id=1');
    assert.match(arenasRequest(requests), /[?&]when=any(&|$)/);
  });

  it('регистр не важен: ?when=WEEKEND', async () => {
    const { requests } = await bootWith('?city_id=1&when=WEEKEND');
    assert.match(arenasRequest(requests), /[?&]when=weekend(&|$)/);
  });

  it('?venue=ice&when=weekend → у льда окно есть', async () => {
    const { requests } = await bootWith('?city_id=1&venue=ice&when=weekend');
    assert.match(arenasRequest(requests), /[?&]when=weekend(&|$)/);
  });

  it('?venue=shop&when=tomorrow → у магазина окна нет, параметр игнорируется', async () => {
    const { requests } = await bootWith('?city_id=1&venue=shop&when=tomorrow');
    const url = arenasRequest(requests);
    assert.ok(url, requests.join(' | '));
    assert.ok(!/[?&]when=/.test(url), url);
  });

  it('?venue=gym при сохранённом coach: intent → skate, но окна у зала нет', async () => {
    const { requests } = await bootWith('?city_id=1&venue=gym&when=any', { intent: 'coach' });
    const url = arenasRequest(requests);
    assert.ok(url, requests.join(' | '));
    assert.ok(!/[?&]when=/.test(url), url);
  });

  it('?intent=skate&when=tomorrow при сохранённом coach → окно применяется', async () => {
    const { requests } = await bootWith('?city_id=1&intent=skate&when=tomorrow', { intent: 'coach' });
    assert.match(arenasRequest(requests), /[?&]when=tomorrow(&|$)/);
  });

  it('?when= без ?intent= при сохранённом coach — окно игнорируется, как и раньше', async () => {
    // Зафиксированное поведение (риск описан в отчёте TASK-149): ссылки на «лёд с окном»
    // должны нести &intent=skate, иначе сохранённая вкладка «Тренеры» победит.
    const { requests } = await bootWith('?city_id=1&when=tomorrow', { intent: 'coach' });
    assert.equal(arenasRequest(requests), null);
  });

  it('возврат с карточки арены: when из sessionStorage → запрос с тем же окном', async () => {
    const { requests } = await bootWith('?city_id=1', {
      intent: 'skate',
      cityId: 1,
      when: 'tomorrow',
      whenDay: '',
    });
    assert.match(arenasRequest(requests), /[?&]when=tomorrow(&|$)/);
  });

  it('без session, но с localStorage — восстанавливает окно', async () => {
    const { requests } = await bootWith('?city_id=1', null, { when: 'weekend', whenDay: '' });
    assert.match(arenasRequest(requests), /[?&]when=weekend(&|$)/);
  });

  it('sessionStorage с when=auto мигрирует в any', async () => {
    const { requests } = await bootWith('?city_id=1', {
      intent: 'skate',
      cityId: 1,
      when: 'auto',
    });
    assert.match(arenasRequest(requests), /[?&]when=any(&|$)/);
  });

  it('?when= в ссылке сильнее сохранённого окна', async () => {
    const { requests } = await bootWith('?city_id=1&when=weekend', {
      intent: 'skate',
      cityId: 1,
      when: 'tomorrow',
    });
    assert.match(arenasRequest(requests), /[?&]when=weekend(&|$)/);
  });

  it('вкладка «Магазины» из sessionStorage — запрос с venue_type=shop', async () => {
    const { requests } = await bootWith('?city_id=1', { intent: 'skate', venueTypes: ['shop'] });
    const url = arenasRequest(requests);
    assert.ok(url, requests.join(' | '));
    assert.match(url, /[?&]venue_type=shop(&|$)/);
  });
});
