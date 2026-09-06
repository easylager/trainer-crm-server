/**
 * TASK-054: Ice tab Yandex map — clustering, bbox, near-me, missing-key, off-map.
 * Run: node --test tests/js/ice-map-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/ice-map-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

function rink(overrides) {
  return Object.assign(
    {
      id: 1,
      name: 'Ледовый дворец «Чижовка»',
      district: 'Заводской',
      latitude: 53.859,
      longitude: 27.627,
      on_map: true,
      tier: 'A',
      distance_km: null,
      live: { kind: 'session', text: 'Сегодня 11:00 · взр. 12 BYN', starts_at_local: '11:00' },
    },
    overrides || {}
  );
}

function moscowGrid() {
  const items = [];
  for (let i = 0; i < 60; i += 1) {
    const row = Math.floor(i / 10);
    const col = i % 10;
    items.push(
      rink({
        id: i + 1,
        name: 'Арена ' + (i + 1),
        latitude: 55.75 + row * 0.004,
        longitude: 37.62 + col * 0.006,
        tier: i < 8 ? 'A' : i < 20 ? 'B' : 'C',
        live: i < 8 ? { kind: 'session', starts_at_local: '15:00', text: 'Сегодня 15:00' } : { kind: 'unknown', text: 'Есть в справочнике' },
      })
    );
  }
  return items;
}

describe('resolveApiKey / missing-key empty state', () => {
  it('reads YANDEX_MAPS_JS_API_KEY and ignores the documented placeholder', () => {
    const { resolveApiKey, PLACEHOLDER_API_KEY } = loadModel();
    assert.equal(PLACEHOLDER_API_KEY, 'YOUR_YANDEX_MAPS_JS_API_KEY');
    assert.equal(resolveApiKey({ env: { YANDEX_MAPS_JS_API_KEY: 'live-key-abc' } }), 'live-key-abc');
    assert.equal(resolveApiKey({ query: { apikey: 'from-query' } }), 'from-query');
    assert.equal(resolveApiKey({ windowKey: 'from-window' }), 'from-window');
    assert.equal(resolveApiKey({ env: { YANDEX_MAPS_JS_API_KEY: 'YOUR_YANDEX_MAPS_JS_API_KEY' } }), '');
    assert.equal(resolveApiKey({ key: '   ' }), '');
    assert.equal(resolveApiKey({}), '');
  });

  it('does not invent an OSM fallback when the key is missing', () => {
    const { missingKeyState, scriptUrl } = loadModel();
    const empty = missingKeyState();
    assert.equal(empty.canRenderMap, false);
    assert.equal(empty.fallback, 'none');
    assert.match(empty.title, /карт/i);
    assert.match(empty.body, /YANDEX_MAPS_JS_API_KEY/);
    assert.ok(!/osm|leaflet|openstreet/i.test(empty.body));
    assert.match(scriptUrl('abc'), /api-maps\.yandex\.ru\/2\.1\//);
    assert.match(scriptUrl('abc'), /apikey=abc/);
    assert.equal(scriptUrl(''), '');
  });
});

describe('splitMapAndList (AC-006)', () => {
  it('keeps an arena without coords in the list and off the map', () => {
    const { splitMapAndList, formatOffMapNote } = loadModel();
    const withCoords = rink({ id: 10 });
    const noCoords = rink({
      id: 11,
      name: 'Каток без координат',
      latitude: null,
      longitude: null,
      on_map: false,
      tier: 'C',
    });
    const split = splitMapAndList([withCoords, noCoords]);
    assert.deepEqual(
      split.onMap.map((it) => it.id),
      [10]
    );
    assert.deepEqual(
      split.list.map((it) => it.id),
      [10, 11]
    );
    assert.equal(split.offMapCount, 1);
    assert.match(formatOffMapNote(split.offMapCount), /без координат/);
    assert.match(formatOffMapNote(split.offMapCount), /списк/);
  });
});

describe('clusters (AC-001)', () => {
  it('packs 60 city-zoom arenas into numbered clusters instead of 60 overlapping pins', () => {
    const { clusterArenas, cellDegForZoom } = loadModel();
    const items = moscowGrid();
    const city = clusterArenas(items, { cellDeg: cellDegForZoom(11) });
    const clusters = city.filter((n) => n.type === 'cluster');
    const pins = city.filter((n) => n.type === 'pin');
    assert.ok(clusters.length >= 1, 'city zoom must show at least one cluster');
    assert.ok(pins.length + clusters.length < 60);
    assert.equal(
      clusters.reduce((sum, c) => sum + c.count, 0) + pins.length,
      60
    );
    clusters.forEach((c) => {
      assert.ok(c.count >= 2);
      assert.ok(typeof c.latitude === 'number');
      assert.ok(typeof c.longitude === 'number');
    });
  });

  it('splits a cluster into pins at street zoom', () => {
    const { clusterArenas, cellDegForZoom } = loadModel();
    const items = moscowGrid().slice(0, 4);
    const street = clusterArenas(items, { cellDeg: cellDegForZoom(17) });
    assert.equal(
      street.filter((n) => n.type === 'pin').length,
      4
    );
  });
});

describe('pin chrome (A label, muted C)', () => {
  it('labels A-pins with short name and next session time; C pins stay mute', () => {
    const { pinView } = loadModel();
    const a = pinView(rink());
    assert.equal(a.tone, 'a');
    assert.equal(a.muted, false);
    assert.equal(a.label, 'Чижовка · 11:00');
    const c = pinView(
      rink({
        id: 2,
        name: 'Каток «Юность»',
        tier: 'C',
        live: { kind: 'unknown', text: 'Есть в справочнике · данных пока нет' },
      })
    );
    assert.equal(c.tone, 'c');
    assert.equal(c.muted, true);
    assert.equal(c.label, '');
  });
});

describe('bbox load on pan (AC-002)', () => {
  it('formats ymaps bounds as min_lat,min_lon,max_lat,max_lon and skips a no-op pan', () => {
    const { boundsToBbox, planBboxFetch } = loadModel();
    const bbox = boundsToBbox([
      [53.8, 27.4],
      [54.0, 27.7],
    ]);
    assert.equal(bbox, '53.8,27.4,54,27.7');
    const first = planBboxFetch(null, bbox);
    assert.equal(first.fetch, true);
    assert.equal(first.bbox, bbox);
    const same = planBboxFetch(first, bbox);
    assert.equal(same.fetch, false);
    const moved = planBboxFetch(
      first,
      boundsToBbox([
        [53.81, 27.41],
        [54.02, 27.72],
      ])
    );
    assert.equal(moved.fetch, true);
  });
});

describe('рядом со мной (AC-003 + EDGE-001/002)', () => {
  it('does not geolocate on map start — only on the near button', () => {
    const { nearMePolicy, geoDeniedState, noArenasNearState } = loadModel();
    assert.equal(nearMePolicy.geolocateOnStart, false);
    assert.equal(nearMePolicy.geolocateOnButton, true);
    const denied = geoDeniedState();
    assert.equal(denied.blocksMap, false);
    assert.match(denied.body, /геолокац/i);
    const empty = noArenasNearState();
    assert.match(empty.title, /нет катков|не нашли/i);
  });

  it('picks the nearest mapped arena for the sheet and keeps distance sort', () => {
    const { pickNearest, sortByDistance } = loadModel();
    const far = rink({ id: 2, name: 'Далёкий', distance_km: 9.1, latitude: 53.95, longitude: 27.4 });
    const near = rink({ id: 1, distance_km: 2.4 });
    const missing = rink({
      id: 3,
      name: 'Без координат',
      latitude: null,
      longitude: null,
      on_map: false,
      distance_km: null,
    });
    const sorted = sortByDistance([far, missing, near]);
    assert.deepEqual(
      sorted.map((it) => it.id),
      [1, 2, 3]
    );
    const sheet = pickNearest([far, missing, near]);
    assert.equal(sheet.id, 1);
    assert.match(String(sheet.sheetMeta || ''), /ближайш/);
  });
});
