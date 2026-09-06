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

  it('keeps city_id on bbox pan so a world-sized viewport cannot load other cities', () => {
    const { bboxFetchPayload } = loadModel();
    const payload = bboxFetchPayload({
      bbox: '-85,-180,85,180',
      intent: 'skate',
      cityId: 2,
      limit: 50,
    });
    assert.equal(payload.fetch, true);
    assert.equal(payload.cityId, 2);
  });

  it('treats a world-sized bbox as invalid for a city map', () => {
    const { bboxExceedsCity, boundsToBbox } = loadModel();
    assert.equal(bboxExceedsCity('-85,-180,85,180'), true);
    assert.equal(bboxExceedsCity(boundsToBbox([[53.8, 27.4], [54.0, 27.7]])), false);
  });
});

describe('city camera (selected city, not the world)', () => {
  it('fits Minsk rinks to a city box and never to a world restrict', () => {
    const { cityCameraFromItems } = loadModel();
    const cam = cityCameraFromItems([
      rink({ id: 1, latitude: 53.859, longitude: 27.627 }),
      rink({ id: 2, latitude: 53.908, longitude: 27.55 }),
      rink({ id: 3, latitude: 53.938, longitude: 27.49 }),
    ]);
    const [[minLat, minLon], [maxLat, maxLon]] = cam.restrict;
    assert.ok(cam.center[0] > 53.7 && cam.center[0] < 54.1);
    assert.ok(cam.center[1] > 27.3 && cam.center[1] < 27.8);
    assert.ok(maxLat - minLat < 1, 'city span, not a country');
    assert.ok(maxLon - minLon < 1.5);
    assert.ok(minLat > 50 && maxLat < 56);
    assert.ok(cam.minZoom >= 8);
    assert.ok(cam.minZoom <= 10, 'must zoom out far enough to see the whole city');
    assert.ok(cam.maxZoom <= 16);
    assert.ok(cam.zoom <= 11, 'initial zoom is city, not street');
  });

  it('opens on a Minsk-sized box so the whole city fits, not just the rink hull', () => {
    const { cityCameraFromItems } = loadModel();
    const cam = cityCameraFromItems([
      rink({ id: 2, latitude: 53.9394, longitude: 27.4685 }),
      rink({ id: 3, latitude: 53.9165, longitude: 27.5478 }),
      rink({ id: 6, latitude: 53.859, longitude: 27.627 }),
    ]);
    const [[minLat, minLon], [maxLat, maxLon]] = cam.restrict;
    assert.ok(maxLat - minLat >= 0.2, 'north-south must cover Minsk, not three pins');
    assert.ok(maxLon - minLon >= 0.38, 'east-west must cover Minsk');
    assert.ok(minLat <= 53.83 && maxLat >= 53.96);
    assert.ok(minLon <= 27.4 && maxLon >= 27.7);
    assert.ok(cam.minZoom <= 10);
  });

  it('widens a single-rink city so the camera is still a town, not a building', () => {
    const { cityCameraFromItems } = loadModel();
    const cam = cityCameraFromItems([rink({ latitude: 55.19, longitude: 30.2 })]);
    const [[minLat, minLon], [maxLat, maxLon]] = cam.restrict;
    assert.ok(maxLat - minLat >= 0.1);
    assert.ok(maxLon - minLon >= 0.15);
    assert.ok(cam.center[0] > 55 && cam.center[0] < 55.4);
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

  it('geo denied keeps the map usable and never falls back to OSM', () => {
    const { afterGeoDenied } = loadModel();
    const next = afterGeoDenied({ pinCount: 4, sheetOpen: true });
    assert.equal(next.blocksMap, false);
    assert.equal(next.keepStage, true);
    assert.equal(next.keepPins, true);
    assert.equal(next.keepSheet, true);
    assert.equal(next.fallback, 'none');
    assert.equal(next.pinCount, 4);
    assert.match(next.body, /геолокац/i);
    assert.ok(!/osm|leaflet|openstreet/i.test(next.body));
  });
});

describe('bbox payload on pan (TASK-075 AC-002)', () => {
  it('sends bbox + intent + city_id so a pan cannot load another city', () => {
    const { bboxFetchPayload } = loadModel();
    const payload = bboxFetchPayload({
      bbox: '53.8,27.4,54.0,27.7',
      intent: 'skate',
      cityId: 3,
      limit: 50,
    });
    assert.equal(payload.fetch, true);
    assert.equal(payload.bbox, '53.8,27.4,54.0,27.7');
    assert.equal(payload.intent, 'skate');
    assert.equal(payload.limit, 50);
    assert.equal(payload.cityId, 3);
  });
});

describe('pin sheet target (TASK-075 AC-002)', () => {
  it('opens our arena card, never a Yandex org card', () => {
    const { pinSheetTarget } = loadModel();
    const target = pinSheetTarget(rink({ slug: 'minsk-chizhovka', id: 12 }));
    assert.equal(target.href, 'arena?ref=minsk-chizhovka');
    assert.equal(target.opens, 'arena-card');
    assert.equal(target.yandexOrgCard, false);
    assert.equal(pinSheetTarget(rink({ id: 12, slug: null })).href, 'arena?ref=12');
  });
});

describe('coach lens map (TASK-076 AC-002 follow-up)', () => {
  it('does not fetch ice arenas or keep leftover rink pins under coach', () => {
    const { bboxFetchPayload, mapStartDecision } = loadModel();
    const payload = bboxFetchPayload({
      bbox: '53.8,27.4,54.0,27.7',
      intent: 'coach',
      limit: 50,
    });
    assert.equal(payload.fetch, false);
    const leftover = mapStartDecision({
      key: 'live-key',
      intent: 'coach',
      listItems: [rink()],
    });
    assert.equal(leftover.showMap, false);
    assert.notEqual(leftover.kind, 'map');
    assert.match(leftover.empty.title, /тренер/i);
    assert.match(leftover.empty.body, /список/i);
  });
});

describe('map start without key or arenas (TASK-075 AC-004 + EDGE)', () => {
  it('missing key chooses no provider and never OSM/Leaflet', () => {
    const { chooseMapProvider, mapStartDecision } = loadModel();
    const missing = chooseMapProvider({});
    assert.equal(missing.provider, 'none');
    assert.equal(missing.fallback, 'none');
    assert.equal(missing.canRenderMap, false);
    assert.ok(!/osm|leaflet|openstreet/i.test(missing.body || ''));
    const live = chooseMapProvider({ key: 'live-key' });
    assert.equal(live.provider, 'yandex');
    assert.equal(live.fallback, 'none');

    const emptyCity = mapStartDecision({
      key: 'live-key',
      listItems: [],
    });
    assert.equal(emptyCity.kind, 'no-arenas');
    assert.equal(emptyCity.showMap, false);
    assert.match(emptyCity.empty.title, /нет катков/i);

    const ready = mapStartDecision({
      key: 'live-key',
      listItems: [rink()],
    });
    assert.equal(ready.kind, 'map');
    assert.equal(ready.showMap, true);
    assert.equal(ready.provider, 'yandex');
  });
});
