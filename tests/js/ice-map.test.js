/**
 * Ice map loader: retries, unavailable UI, SDK failures.
 * Run: node --test tests/js/ice-map.test.js
 */
'use strict';

const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const modelPath = path.join(webapp, 'ice-map-model.js');
const mapPath = path.join(webapp, 'ice-map.js');

function flushPromises(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms || 40));
}

function makeEl(id) {
  return {
    id,
    hidden: false,
    innerHTML: '',
    style: {},
    classList: { add() {}, remove() {} },
    addEventListener() {},
    setAttribute() {},
    removeAttribute() {},
    querySelector() {
      return null;
    },
    appendChild() {},
  };
}

async function bootMap(fetchImpl, ymapsFactory) {
  delete require.cache[require.resolve(modelPath)];
  const model = require(modelPath);
  const elements = {
    iceMapCanvas: makeEl('iceMapCanvas'),
    iceMapEmpty: makeEl('iceMapEmpty'),
    iceMapSheet: makeEl('iceMapSheet'),
    iceMapStage: makeEl('iceMapStage'),
    iceMapLoader: makeEl('iceMapLoader'),
  };
  const sandboxWindow = {
    IceMapModel: model,
    IceTabModel: { formatLiveLine: (it) => (it && it.live && it.live.text) || '' },
    document: {
      getElementById: () => null,
      querySelector: (sel) => (sel === 'meta[name="ymaps-key"]' ? null : null),
      createElement: (tag) => {
        const el = { src: '', async: false, onload: null, onerror: null };
        if (tag === 'script') {
          setTimeout(() => {
            if (el.onerror) el.onerror();
          }, 0);
        }
        return el;
      },
      head: { appendChild() {} },
    },
    fetch: fetchImpl,
    ymaps: ymapsFactory ? ymapsFactory() : undefined,
    setTimeout: global.setTimeout,
    clearTimeout: global.clearTimeout,
    console: { warn() {} },
  };
  sandboxWindow.document = sandboxWindow.document;
  const ctx = vm.createContext({
    window: sandboxWindow,
    document: sandboxWindow.document,
    global: { document: sandboxWindow.document },
    console: sandboxWindow.console,
    setTimeout: sandboxWindow.setTimeout,
    clearTimeout: sandboxWindow.clearTimeout,
    Promise,
    AbortController: global.AbortController,
  });
  vm.runInContext(fs.readFileSync(mapPath, 'utf8'), ctx);
  const ctl = sandboxWindow.IceMap.mount({
    canvas: elements.iceMapCanvas,
    emptyEl: elements.iceMapEmpty,
    sheetEl: null,
    stageEl: elements.iceMapStage,
    loaderEl: elements.iceMapLoader,
    listUrl: () => '',
    fetchJson: () => Promise.resolve({ items: [] }),
    getIntent: () => 'skate',
    getCityId: () => 1,
    getCityCenter: () => [53.9, 27.5],
    getCityBounds: () => null,
    listReady: () => true,
    onShowList: () => {},
  });
  ctl.setListItems([
    {
      id: 1,
      name: 'Test',
      latitude: 53.9,
      longitude: 27.5,
      on_map: true,
      tier: 'A',
      live: { kind: 'session', starts_at_local: '18:00' },
    },
  ]);
  return { ctl, elements, model, sandboxWindow };
}

describe('ice-map.js start()', () => {
  it('429 on map-config then success → map stage shown', async () => {
    let calls = 0;
    const fetchImpl = () => {
      calls += 1;
      if (calls === 1) {
        return Promise.resolve({ ok: false, status: 429, headers: { get: () => '0' } });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ yandex_maps_js_api_key: 'k1' }),
      });
    };
    const ymaps = {
      ready(fn) {
        fn();
      },
      templateLayoutFactory: { createClass: () => ({}) },
      Map: function () {
        this.container = { fitToViewport() {} };
        this.geoObjects = { add() {} };
        this.events = { add() {} };
        this.options = { get: () => 16, set() {} };
        this.setBounds = () => Promise.resolve();
        this.getZoom = () => 10;
        this.getBounds = () => [[53.8, 27.4], [54.0, 27.7]];
      },
      Clusterer: function () {
        this.options = { get: () => 2, set() {} };
        this.events = { add() {} };
        this.removeAll = () => {};
        this.getGeoObjects = () => [];
        this.add = () => {};
      },
      Placemark: function () {
        this.events = { add() {} };
        this.properties = { get() {}, set() {} };
        this.geometry = { getCoordinates() {} };
      },
    };
    const { ctl, elements } = await bootMap(fetchImpl, () => ymaps);
    await ctl.start();
    await flushPromises(450);
    assert.equal(elements.iceMapStage.hidden, false);
    assert.ok(calls >= 2);
  });

  it('SDK load failure → sdk-failed copy, retry does not stick missingKey', async () => {
    const fetchImpl = () =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ yandex_maps_js_api_key: 'k2' }),
      });
    const { ctl, elements } = await bootMap(fetchImpl, () => undefined);
    await ctl.start();
    await flushPromises(120);
    assert.match(elements.iceMapEmpty.innerHTML, /временно недоступна/i);
    assert.match(elements.iceMapEmpty.innerHTML, /Повторить/);
    await ctl.start();
    await flushPromises(20);
    assert.match(elements.iceMapEmpty.innerHTML, /временно недоступна/i);
  });
});
