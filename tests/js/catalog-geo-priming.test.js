/**
 * TASK-163: геолокация каталога — только по тапу, два шага, вечный флаг только на
 * системном отказе.
 *
 * Тесты поведенческие: секция геолокации вырезается из catalog-main.js по рамке
 * комментариев и исполняется с подставными window/document/state — так же, как
 * ice-tab-shop-filters-sheet.test.js прогоняет ice-tab.js. Модель
 * catalog-geo-model.js при этом настоящая: именно она решает, что считать отказом.
 *
 * Run: node --test tests/js/catalog-geo-priming.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const mainSource = fs.readFileSync(path.join(webapp, 'catalog-main.js'), 'utf8');
const catalogHtml = fs.readFileSync(path.join(webapp, 'catalog.html'), 'utf8');
const catalogCss = fs.readFileSync(path.join(webapp, 'mini-app-catalog.css'), 'utf8');
const modelPath = path.join(webapp, 'catalog-geo-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

/* ── вырезка секции геолокации из catalog-main.js ─────────────────────────── */

const SLICE_START = '/* ─── Геолокация каталога: только по тапу (TASK-163)';
const SLICE_END = '/** Drop service/scenario chip when the service has no trainers in the new city. */';

function geoSliceSource() {
  const start = mainSource.indexOf(SLICE_START);
  assert.ok(start > -1, 'в catalog-main.js нет секции геолокации TASK-163');
  const end = mainSource.indexOf(SLICE_END, start);
  assert.ok(end > start, 'не нашли конец секции геолокации');
  return mainSource.slice(start, end);
}

const EXPORTED = [
  'openCatalogGeoSheet',
  'closeCatalogGeoSheet',
  'wireCatalogGeoEntry',
  'requestCatalogGeoFromUserGesture',
  'handleCatalogGeoResult',
  'applyAutoDetectedCity',
  'showCatalogGeoConfirm',
  'renderCatalogGeoSheet',
  'setCatalogGeoChipBusy',
  'catalogGeoSheetIsOpen',
];

const geoFactory = vm.runInThisContext(
  '(function (deps) {\n' +
    '  "use strict";\n' +
    '  var window = deps.window;\n' +
    '  var document = deps.document;\n' +
    '  var state = deps.state;\n' +
    '  var fetch = deps.fetch;\n' +
    '  var showToast = deps.showToast;\n' +
    '  var getJson = deps.getJson;\n' +
    '  var persistCatalogFilters = deps.persistCatalogFilters;\n' +
    '  var invalidateCatalogServicesCache = deps.noop;\n' +
    '  var invalidateCatalogArenasCache = deps.noop;\n' +
    '  var clearCatalogSessionStorageCache = deps.noop;\n' +
    '  var loadCatalogScenariosFromApi = deps.noop;\n' +
    '  var renderSummary = deps.noop;\n' +
    '  var syncScenarioChipSelection = deps.noop;\n' +
    '  var loadTrainers = deps.loadTrainers;\n' +
    '  var loadCities = deps.loadCities;\n' +
    '  var showScreen = deps.showScreen;\n' +
    geoSliceSource() +
    '\n  var out = {};\n' +
    EXPORTED.map((n) => '  out.' + n + ' = ' + n + ';').join('\n') +
    '\n  return out;\n' +
    '})',
  { filename: 'catalog-main.js#geo' }
);

/* ── подставной DOM ───────────────────────────────────────────────────────── */

function makeEl(id, opts) {
  const listeners = {};
  const el = {
    id,
    hidden: !!(opts && opts.hidden),
    disabled: false,
    textContent: (opts && opts.textContent) || '',
    _attrs: {},
    classList: {
      _c: new Set(),
      add(...a) { a.forEach((x) => this._c.add(x)); },
      remove(...a) { a.forEach((x) => this._c.delete(x)); },
      contains(n) { return this._c.has(n); },
    },
    setAttribute(n, v) { el._attrs[n] = String(v); },
    getAttribute(n) { return Object.prototype.hasOwnProperty.call(el._attrs, n) ? el._attrs[n] : null; },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    dispatch(type, ev) { (listeners[type] || []).forEach((fn) => fn(ev || { target: el })); },
    hasListener(type) { return !!(listeners[type] && listeners[type].length); },
    closest(sel) { return sel === '#' + id ? el : null; },
  };
  return el;
}

const ELEMENT_SPEC = {
  catalogGeoChip: { textContent: '⌖ Рядом со мной' },
  catalogGeoSheet: { hidden: true },
  catalogGeoSheetTitle: {},
  catalogGeoSheetText: {},
  catalogGeoAllow: {},
  catalogGeoDismiss: {},
  catalogGeoConfirm: { hidden: true },
  catalogGeoConfirmTitle: {},
  catalogGeoConfirmMeta: { hidden: true },
  catalogGeoConfirmYes: {},
  catalogGeoConfirmOther: {},
};

function makeStorage() {
  const map = new Map();
  return {
    _map: map,
    getItem(k) { return map.has(k) ? map.get(k) : null; },
    setItem(k, v) { map.set(k, String(v)); },
    removeItem(k) { map.delete(k); },
  };
}

/**
 * Собирает «страницу»: DOM, window, state и журнал всех внешних эффектов.
 * `telegram` / `geolocation` / `permissions` задаются точечно в каждом тесте.
 */
function makePage(opts) {
  opts = opts || {};
  const els = {};
  Object.keys(ELEMENT_SPEC).forEach((id) => {
    if (opts.without && opts.without.indexOf(id) > -1) return;
    els[id] = makeEl(id, ELEMENT_SPEC[id]);
  });

  const log = {
    toasts: [],
    fetches: [],
    getJson: [],
    persist: 0,
    screens: [],
    loadCities: 0,
    loadTrainers: 0,
    webGeoCalls: 0,
    telegramGetLocation: 0,
    openSettings: 0,
    permissionQueries: 0,
  };

  const storage = makeStorage();
  if (opts.declinedFlag) storage.setItem('glide_geo_declined_v1', '1');

  const navigator = {};
  if (opts.geolocation !== false) {
    navigator.geolocation = {
      getCurrentPosition(ok, fail) {
        log.webGeoCalls += 1;
        const r = opts.webResult || { lat: 53.9, lon: 27.56 };
        if (r.error) fail(r.error);
        else ok({ coords: { latitude: r.lat, longitude: r.lon } });
      },
    };
  }
  if (opts.permissionState) {
    navigator.permissions = {
      query() {
        log.permissionQueries += 1;
        return Promise.resolve({ state: opts.permissionState });
      },
    };
  }

  let telegram = null;
  if (opts.telegram) {
    const lmOpts = opts.telegram.locationManager;
    telegram = { HapticFeedback: { selectionChanged() {} } };
    if (lmOpts) {
      telegram.LocationManager = Object.assign(
        {
          isInited: true,
          isLocationAvailable: true,
          isAccessRequested: false,
          isAccessGranted: false,
          init(cb) { this.isInited = true; if (cb) cb(); },
          getLocation(cb) {
            log.telegramGetLocation += 1;
            // Реальный клиент помечает «спросили» и «не дали» только после диалога.
            if (lmOpts.deniesOnRequest) {
              this.isAccessRequested = true;
              this.isAccessGranted = false;
            }
            cb(lmOpts.location || null);
          },
          openSettings() { log.openSettings += 1; },
        },
        lmOpts.flags || {}
      );
      if (lmOpts.noOpenSettings) delete telegram.LocationManager.openSettings;
    }
  }

  const win = {
    Telegram: telegram ? { WebApp: telegram } : undefined,
    CatalogGeoModel: loadModel(),
    localStorage: storage,
    navigator,
    requestAnimationFrame(fn) { fn(); },
    setTimeout(fn) { fn(); return 0; }, // шторка закрывается без ожидания анимации
  };

  const state = { cityId: opts.cityId || null, cityName: '', serviceId: null, arenaId: null, trainerId: null };

  const nearPayload = opts.nearPayload === undefined
    ? { items: [{ city_id: 3, name: 'Ледовый дворец', distance_km: 2.4 }] }
    : opts.nearPayload;

  const geo = geoFactory({
    window: win,
    document: { getElementById: (id) => els[id] || null },
    state,
    noop() {},
    showToast(msg) { log.toasts.push(msg); },
    getJson(url) {
      log.getJson.push(url);
      if (url === '/cities') return Promise.resolve({ items: [{ id: 3, name: 'Минск' }] });
      return Promise.resolve({});
    },
    fetch(url, init) {
      log.fetches.push({ url, init });
      if (opts.nearFails) return Promise.reject(new Error('offline'));
      return Promise.resolve({ json: () => Promise.resolve(nearPayload) });
    },
    persistCatalogFilters() {
      log.persist += 1;
      const body = {};
      if (state.cityId) body.city_id = state.cityId;
      log.fetches.push({ url: '/api/webapp/client/session/catalog-filters', init: { method: 'PATCH', body: JSON.stringify(body) } });
      return Promise.resolve();
    },
    loadTrainers() { log.loadTrainers += 1; },
    loadCities() { log.loadCities += 1; },
    showScreen(name) { log.screens.push(name); },
  });

  return { geo, els, log, state, storage, win, telegram };
}

async function flush(rounds) {
  for (let i = 0; i < (rounds || 40); i += 1) await Promise.resolve();
}

function tapChip(page) {
  page.els.catalogGeoChip.dispatch('click', { target: page.els.catalogGeoChip });
}

function tapSheet(page, elId) {
  page.els.catalogGeoSheet.dispatch('click', { target: page.els[elId] });
}

/* ── AC-1: открытие вкладки не вызывает системный диалог ──────────────────── */

describe('AC-1 — на загрузке геопозицию не просим', () => {
  it('автовызова attemptCatalogAutoGeoDetect в catalog-main.js больше нет', () => {
    // Имя осталось только в комментарии «было → стало»; вызова быть не должно.
    assert.ok(!mainSource.includes('attemptCatalogAutoGeoDetect('), 'остался автодетект на загрузке');
    assert.ok(!catalogHtml.includes('attemptCatalogAutoGeoDetect'));
  });

  it('getCurrentPosition в catalog-main.js не вызывается вовсе (только через модель)', () => {
    assert.ok(!mainSource.includes('getCurrentPosition('), 'прямой вызов getCurrentPosition в каталоге');
  });

  it('requestLocation вызывается ровно из одного места — обработчика жеста', () => {
    const calls = mainSource.split('G.requestLocation(').length - 1;
    assert.equal(calls, 1, 'requestLocation должен вызываться один раз, из requestCatalogGeoFromUserGesture');
    const fn = mainSource.indexOf('function requestCatalogGeoFromUserGesture(');
    const call = mainSource.indexOf('G.requestLocation(');
    assert.ok(call > fn, 'вызов requestLocation вне обработчика жеста');
  });

  it('ни загрузка секции, ни обвязка слушателей не трогают геолокацию', async () => {
    const page = makePage({ telegram: { locationManager: { location: { latitude: 1, longitude: 2 } } } });
    page.geo.wireCatalogGeoEntry();
    await flush();
    assert.equal(page.log.webGeoCalls, 0);
    assert.equal(page.log.telegramGetLocation, 0);
    assert.equal(page.log.permissionQueries, 0, 'даже разрешение не читаем до тапа');
    assert.equal(page.els.catalogGeoSheet.hidden, true);
  });
});

/* ── AC-2: системный запрос — только два шага ─────────────────────────────── */

describe('AC-2 — два шага: чип, потом «Разрешить геопозицию»', () => {
  it('тап по чипу открывает шторку и системного запроса не делает', async () => {
    const page = makePage();
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoSheet.hidden, false, 'шторка открыта');
    assert.equal(page.els.catalogGeoSheet.classList.contains('is-open'), true);
    assert.equal(page.els.catalogGeoSheetTitle.textContent, 'Показать катки рядом?');
    assert.equal(page.els.catalogGeoAllow.textContent, 'Разрешить геопозицию');
    assert.equal(page.log.webGeoCalls, 0, 'системного запроса на первом шаге быть не должно');
  });

  it('второй шаг — тап по кнопке в шторке — и только он идёт в систему', async () => {
    const page = makePage();
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    tapSheet(page, 'catalogGeoAllow');
    await flush();
    assert.equal(page.log.webGeoCalls, 1, 'ровно один системный запрос');
  });

  it('чип в разметке есть, помечен как открывающий диалог, и он единственный вход', () => {
    assert.match(catalogHtml, /id="catalogGeoChip"[^>]*aria-haspopup="dialog"/);
    assert.match(catalogHtml, /id="catalogGeoSheet"[^>]*hidden/);
    assert.match(catalogHtml, /id="catalogGeoAllow"/);
    assert.match(catalogHtml, /id="catalogGeoDismiss"/);
  });
});

/* ── AC-3: «Не сейчас» вечного флага не ставит ────────────────────────────── */

describe('AC-3 — вечный флаг только на системном отказе', () => {
  it('«Не сейчас» закрывает шторку, флага не пишет, чип остаётся живым', async () => {
    const page = makePage();
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    tapSheet(page, 'catalogGeoDismiss');
    await flush();
    assert.equal(page.els.catalogGeoSheet.hidden, true, 'шторка закрыта');
    assert.equal(page.storage.getItem('glide_geo_declined_v1'), null, '«Не сейчас» — не отказ');
    assert.equal(page.els.catalogGeoChip.disabled, false, 'чип доступен');
  });

  it('после «Не сейчас» шторку можно открыть снова — снова прайминг', async () => {
    const page = makePage();
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    tapSheet(page, 'catalogGeoDismiss');
    await flush();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoSheet.hidden, false);
    assert.equal(page.els.catalogGeoSheetTitle.textContent, 'Показать катки рядом?');
    assert.equal(page.els.catalogGeoAllow.hidden, false);
  });

  it('таймаут/недоступность флага не пишут — предложение попробовать ещё раз', async () => {
    for (const status of ['error', 'unavailable']) {
      const page = makePage();
      page.geo.wireCatalogGeoEntry();
      page.geo.handleCatalogGeoResult({ status });
      await flush();
      assert.equal(page.storage.getItem('glide_geo_declined_v1'), null, status + ' не отказ');
      assert.equal(page.log.toasts.length, 1);
    }
  });

  it('сетевой сбой near= флага не пишет', async () => {
    const page = makePage({ nearFails: true });
    page.geo.wireCatalogGeoEntry();
    page.geo.handleCatalogGeoResult({ status: 'granted', lat: 53.9, lon: 27.56 });
    await flush();
    assert.equal(page.storage.getItem('glide_geo_declined_v1'), null);
    assert.deepEqual(page.log.toasts, ['Не удалось определить город. Попробуйте ещё раз.']);
  });

  it('системный отказ веб-геолокации пишет флаг', async () => {
    const page = makePage({ webResult: { error: { code: 1, PERMISSION_DENIED: 1 } } });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    tapSheet(page, 'catalogGeoAllow');
    await flush();
    assert.equal(page.storage.getItem('glide_geo_declined_v1'), '1');
  });

  it('модель: вечный флаг стоит только статуса denied', () => {
    const M = loadModel();
    assert.equal(M.isPermanentDecline({ status: M.GEO_STATUS.DENIED }), true);
    assert.equal(M.isPermanentDecline({ status: M.GEO_STATUS.ERROR }), false);
    assert.equal(M.isPermanentDecline({ status: M.GEO_STATUS.UNAVAILABLE }), false);
    assert.equal(M.isPermanentDecline({ status: M.GEO_STATUS.GRANTED }), false);
    assert.equal(M.isPermanentDecline(null), false);
  });

  it('writeDeclinedFlag в каталоге вызывается ровно в одной ветке — isPermanentDecline', () => {
    const slice = geoSliceSource();
    assert.equal(slice.split('writeDeclinedFlag(').length - 1, 1);
    const guard = slice.indexOf('G.isPermanentDecline(res)');
    const write = slice.indexOf('G.writeDeclinedFlag(');
    assert.ok(guard > -1 && write > guard, 'флаг пишется только под охраной isPermanentDecline');
  });
});

/* ── AC-4: LocationManager внутри Телеграма, тихий фолбэк вне ─────────────── */

describe('AC-4 — LocationManager против navigator.geolocation', () => {
  it('внутри Телеграма берём LocationManager, веб-геолокацию не трогаем', async () => {
    const page = makePage({
      telegram: { locationManager: { location: { latitude: 53.9, longitude: 27.56 } } },
      permissionState: 'prompt',
    });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    tapSheet(page, 'catalogGeoAllow');
    await flush();
    assert.equal(page.log.telegramGetLocation, 1);
    assert.equal(page.log.webGeoCalls, 0, 'второго диалога быть не должно');
  });

  it('isLocationAvailable === false — тихий фолбэк на navigator, один диалог', async () => {
    const page = makePage({
      telegram: { locationManager: { flags: { isLocationAvailable: false } } },
    });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    tapSheet(page, 'catalogGeoAllow');
    await flush();
    assert.equal(page.log.telegramGetLocation, 0);
    assert.equal(page.log.webGeoCalls, 1);
  });

  it('вне Телеграма — navigator.geolocation', async () => {
    const page = makePage();
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    tapSheet(page, 'catalogGeoAllow');
    await flush();
    assert.equal(page.log.webGeoCalls, 1);
  });

  it('модель: старый клиент без LocationManager.getLocation уходит в веб', () => {
    const M = loadModel();
    assert.equal(M.telegramLocationManager({ LocationManager: {} }), null);
    assert.equal(M.telegramLocationManager({ LocationManager: { getLocation() {}, isLocationAvailable: false } }), null);
    assert.ok(M.telegramLocationManager({ LocationManager: { getLocation() {} } }));
  });

  it('модель: init ответил после таймаута — второго запроса не будет', () => {
    const M = loadModel();
    let late = null;
    const results = [];
    let webCalls = 0;
    M.requestLocation(
      {
        telegram: {
          LocationManager: {
            isInited: false,
            getLocation() { throw new Error('не должно вызваться'); },
            init(cb) { late = cb; },
          },
        },
        navigator: { geolocation: { getCurrentPosition() { webCalls += 1; } } },
        setTimeout: (fn) => { fn(); return 1; },
      },
      (res) => results.push(res)
    );
    assert.equal(results.length, 1);
    assert.equal(results[0].status, M.GEO_STATUS.ERROR, 'молчание клиента — сбой, не отказ');
    late();
    assert.equal(results.length, 1, 'опоздавший init погашен защёлкой');
    assert.equal(webCalls, 0);
  });

  it('модель: LocationManager отдал null при isAccessRequested — это отказ', () => {
    const M = loadModel();
    const got = [];
    M.requestLocation(
      {
        telegram: {
          LocationManager: {
            isInited: true,
            isAccessRequested: true,
            isAccessGranted: false,
            getLocation(cb) { cb(null); },
            openSettings() {},
          },
        },
      },
      (r) => got.push(r)
    );
    assert.equal(got[0].status, M.GEO_STATUS.DENIED);
    assert.equal(got[0].canOpenSettings, true);
  });

  it('модель: null без isAccessRequested — сбой, а не отказ', () => {
    const M = loadModel();
    const got = [];
    M.requestLocation(
      { telegram: { LocationManager: { isInited: true, getLocation(cb) { cb(null); } } } },
      (r) => got.push(r)
    );
    assert.equal(got[0].status, M.GEO_STATUS.ERROR);
  });

  it('модель: таймаут веб-геолокации — ERROR, а не DENIED', () => {
    const M = loadModel();
    const got = [];
    M.requestLocation(
      {
        navigator: {
          geolocation: {
            getCurrentPosition(ok, fail) { fail({ code: 3, PERMISSION_DENIED: 1, TIMEOUT: 3 }); },
          },
        },
      },
      (r) => got.push(r)
    );
    assert.equal(got[0].status, M.GEO_STATUS.ERROR);
  });

  it('модель: геолокации нет вообще — UNAVAILABLE', () => {
    const M = loadModel();
    const got = [];
    M.requestLocation({ navigator: {} }, (r) => got.push(r));
    assert.equal(got[0].status, M.GEO_STATUS.UNAVAILABLE);
  });
});

/* ── AC-5: путь восстановления после системного отказа ────────────────────── */

describe('AC-5 — восстановление после отказа', () => {
  it('в Телеграме после отказа видно шторку с «Открыть настройки»', async () => {
    // До тапа разрешение «не спрашивали» — значит прайминг; отказ случается
    // внутри getLocation, как в реальном клиенте.
    const page = makePage({ telegram: { locationManager: { deniesOnRequest: true } } });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoSheetTitle.textContent, 'Показать катки рядом?');
    tapSheet(page, 'catalogGeoAllow');
    await flush();
    assert.equal(page.storage.getItem('glide_geo_declined_v1'), '1');
    assert.equal(page.els.catalogGeoSheet.hidden, false, 'шторка восстановления открыта');
    assert.equal(page.els.catalogGeoSheetTitle.textContent, 'Доступ к геопозиции закрыт');
    assert.equal(page.els.catalogGeoAllow.hidden, false);
    assert.equal(page.els.catalogGeoAllow.textContent, 'Открыть настройки');
    assert.equal(page.els.catalogGeoAllow.getAttribute('data-geo-action'), 'settings');
  });

  it('openSettings() зовётся из тапа по кнопке, не сам по себе', async () => {
    const page = makePage({
      declinedFlag: true,
      telegram: { locationManager: { flags: { isAccessRequested: true } } },
    });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.log.openSettings, 0, 'до тапа настройки не открываем');
    tapSheet(page, 'catalogGeoAllow');
    await flush();
    assert.equal(page.log.openSettings, 1);
    assert.equal(page.els.catalogGeoSheet.hidden, true);
  });

  it('без LocationManager — честный текст и никакой кнопки', async () => {
    const page = makePage({ declinedFlag: true });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoSheetTitle.textContent, 'Доступ к геопозиции закрыт');
    assert.equal(page.els.catalogGeoAllow.hidden, true, 'кнопки восстановления быть не должно');
    assert.match(page.els.catalogGeoSheetText.textContent, /Выберите город вручную/);
  });

  it('LocationManager без openSettings кнопку тоже не рисует', async () => {
    const page = makePage({
      declinedFlag: true,
      telegram: { locationManager: { noOpenSettings: true, flags: { isAccessRequested: true } } },
    });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoAllow.hidden, true);
  });

  it('модель: openLocationSettings честно отвечает false, когда пути нет', () => {
    const M = loadModel();
    assert.equal(M.openLocationSettings(null), false);
    assert.equal(M.openLocationSettings({ LocationManager: {} }), false);
    assert.equal(M.canOpenLocationSettings({ LocationManager: { openSettings() {} } }), true);
    let hit = 0;
    assert.equal(M.openLocationSettings({ LocationManager: { openSettings() { hit += 1; } } }), true);
    assert.equal(hit, 1);
    assert.equal(
      M.openLocationSettings({ LocationManager: { openSettings() { throw new Error('nope'); } } }),
      false,
      'бросок клиента не должен ломать обработчик тапа'
    );
  });
});

/* ── AC-6: выданное разрешение не показывает прайминг заново ──────────────── */

describe('AC-6 — уже разрешено: прайминга нет', () => {
  it('Телеграм с isAccessGranted — шторка не открывается, запрос идёт сразу', async () => {
    const page = makePage({
      telegram: {
        locationManager: {
          location: { latitude: 53.9, longitude: 27.56 },
          flags: { isAccessRequested: true, isAccessGranted: true },
        },
      },
    });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoSheet.hidden, true, 'шторки-прайминга быть не должно');
    assert.equal(page.els.catalogGeoSheetTitle.textContent, '', 'шторку даже не рендерили');
    assert.equal(page.log.telegramGetLocation, 1);
    assert.equal(page.els.catalogGeoConfirm.hidden, false, 'сразу подтверждение города');
  });

  it('веб с permissions.state === granted — тоже без прайминга', async () => {
    const page = makePage({ permissionState: 'granted' });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoSheet.hidden, true);
    assert.equal(page.log.permissionQueries, 1);
    assert.equal(page.log.webGeoCalls, 1);
  });

  it('веб с permissions.state === prompt — прайминг показываем', async () => {
    const page = makePage({ permissionState: 'prompt' });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoSheet.hidden, false);
    assert.equal(page.els.catalogGeoSheetTitle.textContent, 'Показать катки рядом?');
    assert.equal(page.log.webGeoCalls, 0);
  });

  it('веб с permissions.state === denied — сразу восстановление, не прайминг', async () => {
    const page = makePage({ permissionState: 'denied' });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoSheetTitle.textContent, 'Доступ к геопозиции закрыт');
    assert.equal(page.log.webGeoCalls, 0);
  });

  it('разрешение перебивает устаревший вечный флаг (человек разрешил в настройках)', async () => {
    const page = makePage({ declinedFlag: true, permissionState: 'granted' });
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    assert.equal(page.els.catalogGeoSheet.hidden, true);
    assert.equal(page.log.webGeoCalls, 1);
  });

  it('модель: pickGeoEntryView', () => {
    const M = loadModel();
    const P = M.GEO_PERMISSION;
    const E = M.GEO_ENTRY;
    assert.equal(M.pickGeoEntryView({ permission: P.GRANTED }), E.REQUEST);
    assert.equal(M.pickGeoEntryView({ permission: P.GRANTED, declinedForever: true }), E.REQUEST);
    assert.equal(M.pickGeoEntryView({ permission: P.DENIED }), E.RECOVERY);
    assert.equal(M.pickGeoEntryView({ permission: P.PROMPT, declinedForever: true }), E.RECOVERY);
    assert.equal(M.pickGeoEntryView({ permission: P.PROMPT }), E.PRIMING);
    assert.equal(M.pickGeoEntryView({ permission: P.UNKNOWN }), E.PRIMING);
    assert.equal(M.pickGeoEntryView({}), E.PRIMING);
  });

  it('модель: readLocationPermission не поднимает системный диалог', () => {
    const M = loadModel();
    let geoCalls = 0;
    const seen = [];
    M.readLocationPermission(
      { navigator: { geolocation: { getCurrentPosition() { geoCalls += 1; } } } },
      (p) => seen.push(p)
    );
    assert.equal(geoCalls, 0);
    assert.deepEqual(seen, [M.GEO_PERMISSION.UNKNOWN], 'нет Permissions API — прайминг');
  });

  it('модель: readLocationPermission до init() отвечает UNKNOWN, а не DENIED', () => {
    const M = loadModel();
    const seen = [];
    M.readLocationPermission(
      { telegram: { LocationManager: { isInited: false, getLocation() {} } } },
      (p) => seen.push(p)
    );
    assert.deepEqual(seen, [M.GEO_PERMISSION.UNKNOWN]);
  });

  it('модель: бросок или отказ Permissions API — UNKNOWN', async () => {
    const M = loadModel();
    const seen = [];
    M.readLocationPermission({ navigator: { permissions: { query() { throw new Error('x'); } } } }, (p) => seen.push(p));
    M.readLocationPermission({ navigator: { permissions: { query() { return Promise.reject(new Error('x')); } } } }, (p) => seen.push(p));
    await flush();
    assert.deepEqual(seen, [M.GEO_PERMISSION.UNKNOWN, M.GEO_PERMISSION.UNKNOWN]);
  });

  it('модель: telegramAccessState по флагам LocationManager', () => {
    const M = loadModel();
    const P = M.GEO_PERMISSION;
    const lm = (flags) => ({ LocationManager: Object.assign({ isInited: true, getLocation() {} }, flags) });
    assert.equal(M.telegramAccessState(lm({ isAccessGranted: true })), P.GRANTED);
    assert.equal(M.telegramAccessState(lm({ isAccessRequested: true })), P.DENIED);
    assert.equal(M.telegramAccessState(lm({})), P.PROMPT);
    assert.equal(M.telegramAccessState(null), null, 'вне Телеграма — решает веб-путь');
    assert.equal(M.telegramAccessState(lm({ isLocationAvailable: false })), null);
  });
});

/* ── AC-7: город применяем оптимистично, но не молча ──────────────────────── */

describe('AC-7 — подтверждение найденного города', () => {
  async function detect(opts) {
    const page = makePage(opts);
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    tapSheet(page, 'catalogGeoAllow');
    await flush();
    return page;
  }

  it('город применён сразу, список перезагружен, но в сессию ещё не ушёл', async () => {
    const page = await detect();
    assert.equal(page.state.cityId, 3);
    assert.equal(page.state.cityName, 'Минск');
    assert.equal(page.log.loadTrainers, 1, 'контент перестроился оптимистично');
    assert.equal(page.log.persist, 0, 'в сессию город без подтверждения не пишем');
  });

  it('блок подтверждения показывает город и основание догадки', async () => {
    const page = await detect();
    assert.equal(page.els.catalogGeoConfirm.hidden, false);
    assert.equal(page.els.catalogGeoConfirmTitle.textContent, 'Похоже, вы в Минске?');
    assert.equal(page.els.catalogGeoConfirmMeta.hidden, false);
    assert.equal(page.els.catalogGeoConfirmMeta.textContent, 'Ближайшая площадка — Ледовый дворец · 2,4 км');
    assert.equal(page.els.catalogGeoConfirm.getAttribute('data-city-id'), '3');
  });

  it('«Да, мой город» пишет city_id в сессию и убирает блок', async () => {
    const page = await detect();
    page.els.catalogGeoConfirmYes.dispatch('click');
    await flush();
    assert.equal(page.log.persist, 1);
    const patch = page.log.fetches.filter((f) => f.url.indexOf('catalog-filters') > -1);
    assert.equal(patch.length, 1);
    assert.deepEqual(JSON.parse(patch[0].init.body), { city_id: 3 });
    assert.equal(page.els.catalogGeoConfirm.hidden, true);
  });

  it('«Другой город» открывает выбор города и в сессию ничего не пишет', async () => {
    const page = await detect();
    page.els.catalogGeoConfirmOther.dispatch('click');
    await flush();
    assert.equal(page.log.persist, 0);
    assert.equal(page.log.loadCities, 1);
    assert.deepEqual(page.log.screens, ['screenCity']);
    assert.equal(page.els.catalogGeoConfirm.hidden, true);
  });

  it('координаты не уходят ни в сессию, ни в хранилище', async () => {
    const page = await detect();
    page.els.catalogGeoConfirmYes.dispatch('click');
    await flush();
    const near = page.log.fetches.filter((f) => f.url.indexOf('/api/public/ice/arenas') === 0);
    assert.equal(near.length, 1, 'координаты уходят только в near=, разово');
    assert.equal(near[0].init.method, undefined, 'near= — обычный GET');
    page.log.fetches
      .filter((f) => f.init && f.init.body)
      .forEach((f) => {
        assert.ok(!/53\.9|27\.56|lat|lon/.test(f.init.body), 'координаты в теле запроса: ' + f.init.body);
      });
    [...page.storage._map.entries()].forEach(([k, v]) => {
      assert.ok(!/53\.9|27\.56/.test(k + '=' + v), 'координаты в localStorage: ' + k);
    });
    assert.equal(page.state.lat, undefined);
    assert.equal(page.state.lon, undefined);
    assert.ok(!geoSliceSource().includes('setItem'), 'секция геолокации вообще ничего не пишет в хранилище напрямую');
  });

  it('города рядом нет — подтверждения нет, честный тост', async () => {
    const page = await detect({ nearPayload: { items: [{ city_id: 3, name: 'Далеко', distance_km: 900 }] } });
    assert.equal(page.els.catalogGeoConfirm.hidden, true);
    assert.equal(page.state.cityId, null);
    assert.deepEqual(page.log.toasts, ['Рядом с вами пока нет наших катков. Выберите город вручную.']);
  });

  it('ближайшей площадки нет в ответе — заголовок есть, основание скрыто', async () => {
    const page = makePage();
    page.geo.showCatalogGeoConfirm(3, 'Гродно', null);
    assert.equal(page.els.catalogGeoConfirmTitle.textContent, 'Похоже, вы в Гродно?');
    assert.equal(page.els.catalogGeoConfirmMeta.hidden, true);
    assert.equal(page.els.catalogGeoConfirmMeta.textContent, '');
  });

  it('имя города не доехало — не врём, пишем нейтральное', async () => {
    const page = makePage();
    page.geo.showCatalogGeoConfirm(3, '', { name: 'Арена', distanceKm: null });
    assert.equal(page.els.catalogGeoConfirmTitle.textContent, 'Похоже, мы нашли ваш город');
    assert.equal(page.els.catalogGeoConfirmMeta.textContent, 'Ближайшая площадка — Арена');
  });

  it('падеж города не придумывается: где не уверены — формулировка без падежа', () => {
    const M = loadModel();
    // Наши рынки — словарь (scripts/seed_cities.py, scripts/seed_regional_arenas.py).
    assert.equal(M.formatCityGuessTitle('Минск'), 'Похоже, вы в Минске?');
    assert.equal(M.formatCityGuessTitle('Гродно'), 'Похоже, вы в Гродно?');
    assert.equal(M.formatCityGuessTitle('Лунинец'), 'Похоже, вы в Лунинце?');
    assert.equal(M.formatCityGuessTitle('Барановичи'), 'Похоже, вы в Барановичах?');
    assert.equal(M.formatCityGuessTitle('Москва'), 'Похоже, вы в Москве?');
    // Безопасные правила для городов вне словаря.
    assert.equal(M.cityLocative('Подольск'), 'Подольске');
    assert.equal(M.cityLocative('Балашиха'), 'Балашихе');
    assert.equal(M.cityLocative('Одинцово'), 'Одинцово');
    assert.equal(M.cityLocative('Пушкин'), 'Пушкине');
    // Там, где правило соврало бы, падежа нет — и заголовок переформулирован.
    assert.equal(M.cityLocative('Тверь'), null);
    assert.equal(M.formatCityGuessTitle('Тверь'), 'Похоже, ваш город — Тверь?');
    assert.equal(M.cityLocative('Мытищи'), null);
    assert.equal(M.cityLocative(''), null);
    assert.equal(M.cityLocative(null), null);
    assert.equal(M.formatCityGuessTitle(null), 'Похоже, мы нашли ваш город');
  });

  it('каталог берёт заголовок из модели, своего шаблона падежа не держит', () => {
    const slice = geoSliceSource();
    assert.ok(slice.includes('G.formatCityGuessTitle(cityName)'));
    assert.ok(!slice.includes("'Похоже, вы в '"), 'шаблон падежа не должен жить в каталоге');
  });

  it('модель: ближайшая площадка и запись расстояния', () => {
    const M = loadModel();
    assert.deepEqual(
      M.pickNearestPlaceFromNearResponse({ items: [{ name: 'Юность', distance_km: 3 }] }),
      { name: 'Юность', distanceKm: 3 }
    );
    assert.deepEqual(
      M.pickNearestPlaceFromNearResponse({ items: [{ name: 'Юность', distance_km: null }] }),
      { name: 'Юность', distanceKm: null }
    );
    assert.equal(M.pickNearestPlaceFromNearResponse({ items: [] }), null);
    assert.equal(M.pickNearestPlaceFromNearResponse(null), null);
    assert.equal(M.formatDistanceKm(3), '3 км');
    assert.equal(M.formatDistanceKm(2.42), '2,4 км');
    assert.equal(M.formatDistanceKm(null), '');
    assert.equal(M.formatDistanceKm('x'), '');
  });

  it('разметка подтверждения на месте и скрыта по умолчанию', () => {
    assert.match(catalogHtml, /id="catalogGeoConfirm"[^>]*hidden/);
    assert.match(catalogHtml, /id="catalogGeoConfirmYes"[^>]*>Да, мой город</);
    assert.match(catalogHtml, /id="catalogGeoConfirmOther"[^>]*>Другой город</);
    assert.match(catalogHtml, /id="catalogGeoConfirmMeta"[^>]*hidden/);
  });
});

/* ── общие инварианты ─────────────────────────────────────────────────────── */

describe('инварианты', () => {
  it('повторный тап по «Разрешить» не плодит системных запросов', async () => {
    const page = makePage({ webResult: { lat: 53.9, lon: 27.56 } });
    let pending = null;
    page.win.navigator.geolocation.getCurrentPosition = (ok) => {
      page.log.webGeoCalls += 1;
      pending = ok;
    };
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    tapSheet(page, 'catalogGeoAllow');
    tapSheet(page, 'catalogGeoAllow');
    await flush();
    assert.equal(page.log.webGeoCalls, 1);
    pending({ coords: { latitude: 53.9, longitude: 27.56 } });
    await flush();
    assert.equal(page.state.cityId, 3);
  });

  it('тап по скриму закрывает шторку и флага не пишет', async () => {
    const page = makePage();
    page.geo.wireCatalogGeoEntry();
    tapChip(page);
    await flush();
    page.els.catalogGeoSheet.dispatch('click', { target: page.els.catalogGeoSheet });
    assert.equal(page.els.catalogGeoSheet.hidden, true);
    assert.equal(page.storage.getItem('glide_geo_declined_v1'), null);
  });

  it('без разметки геолокации код не падает', async () => {
    const page = makePage({ without: Object.keys(ELEMENT_SPEC) });
    page.geo.wireCatalogGeoEntry();
    page.geo.openCatalogGeoSheet();
    page.geo.handleCatalogGeoResult({ status: 'denied' });
    page.geo.showCatalogGeoConfirm(3, 'Минск', null);
    await flush();
    assert.ok(true);
  });

  it('shouldAutoGeolocate остался в публичном контракте — его читает хаб', () => {
    const M = loadModel();
    assert.equal(typeof M.shouldAutoGeolocate, 'function');
    const home = fs.readFileSync(path.join(webapp, 'client-home-main.js'), 'utf8');
    assert.ok(home.includes('shouldAutoGeolocate'), 'хаб всё ещё пользуется гардом');
    assert.ok(!mainSource.includes('shouldAutoGeolocate'), 'каталог гардом больше не пользуется');
  });

  it('каталог и хаб не делят вечный флаг отказа', () => {
    const M = loadModel();
    const home = fs.readFileSync(path.join(webapp, 'client-home-main.js'), 'utf8');
    // Хаб передаёт ключ через константу — разворачиваем её значение.
    const refs = [...home.matchAll(/(?:read|write)DeclinedFlag\(\s*window\.localStorage\s*,\s*([A-Za-z_$][\w$]*|'[^']+')/g)]
      .map((m) => m[1]);
    assert.ok(refs.length >= 1, 'хаб должен передавать свой ключ');
    refs.forEach((ref) => {
      let key = ref;
      if (ref[0] !== "'") {
        const decl = home.match(new RegExp('var\\s+' + ref + "\\s*=\\s*'([^']+)'"));
        assert.ok(decl, 'не нашли объявление ' + ref);
        key = "'" + decl[1] + "'";
      }
      assert.notEqual(key.slice(1, -1), M.DECLINED_STORAGE_KEY, 'хаб не должен делить флаг с каталогом');
    });
    // А без ключа — ровно дефолт каталога, и зовёт его только каталог.
    assert.ok(!/DeclinedFlag\(\s*window\.localStorage\s*\)/.test(home), 'хаб не должен читать дефолтный ключ');
  });

  it('CSS геолокации не вводит новых hex-цветов', () => {
    const start = catalogCss.indexOf('Геолокация по тапу (TASK-163)');
    assert.ok(start > -1, 'нет секции стилей геолокации');
    const block = catalogCss.slice(start);
    const hex = block.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
    assert.deepEqual(hex, [], 'hex-цвета в стилях геолокации: ' + hex.join(', '));
    assert.match(block, /\.catalog-geo-chip\s*\{/);
    assert.match(block, /\.catalog-geo-sheet\s*\{/);
    assert.match(block, /\.catalog-geo-confirm\s*\{/);
  });

  it('подпись чипа в разметке и в коде одна и та же', () => {
    const label = (mainSource.match(/var CATALOG_GEO_CHIP_LABEL = '([^']+)'/) || [])[1];
    assert.ok(label, 'нет CATALOG_GEO_CHIP_LABEL');
    assert.ok(catalogHtml.includes('>' + label + '<'), 'подпись чипа разошлась с разметкой');
  });
});
