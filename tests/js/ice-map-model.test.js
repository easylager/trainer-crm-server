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

const DEV_LEAK = /YANDEX_MAPS_JS_API_KEY|apikey|переменн|прототип/i;

describe('resolveApiKey / map unavailable copy', () => {
  it('reads meta, env, query, window and ignores the documented placeholder', () => {
    const { resolveApiKey, PLACEHOLDER_API_KEY } = loadModel();
    assert.equal(PLACEHOLDER_API_KEY, 'YOUR_YANDEX_MAPS_JS_API_KEY');
    assert.equal(resolveApiKey({ metaKey: 'from-meta' }), 'from-meta');
    assert.equal(resolveApiKey({ env: { YANDEX_MAPS_JS_API_KEY: 'live-key-abc' } }), 'live-key-abc');
    assert.equal(resolveApiKey({ query: { apikey: 'from-query' } }), 'from-query');
    assert.equal(resolveApiKey({ windowKey: 'from-window' }), 'from-window');
    assert.equal(resolveApiKey({ env: { YANDEX_MAPS_JS_API_KEY: 'YOUR_YANDEX_MAPS_JS_API_KEY' } }), '');
    assert.equal(resolveApiKey({ key: '   ' }), '');
    assert.equal(resolveApiKey({}), '');
  });

  it('mapUnavailableState never exposes developer setup hints to the user', () => {
    const { mapUnavailableState, scriptUrl } = loadModel();
    const reasons = ['config-failed', 'no-key', 'sdk-failed', 'init-error'];
    for (const reason of reasons) {
      const empty = mapUnavailableState(reason);
      assert.equal(empty.canRenderMap, false);
      assert.equal(empty.fallback, 'none');
      assert.equal(empty.reason, reason);
      assert.match(empty.title, /временно недоступна/i);
      assert.ok(!DEV_LEAK.test(empty.title));
      assert.ok(!DEV_LEAK.test(empty.body));
      assert.ok(!DEV_LEAK.test(empty.retryLabel));
      assert.ok(!DEV_LEAK.test(empty.listLabel));
      assert.ok(!/osm|leaflet|openstreet/i.test(empty.body));
    }
    const noKey = mapUnavailableState('no-key');
    assert.equal(noKey.retryLabel, '');
    assert.doesNotMatch(noKey.body, /Попробуйте ещё раз/);
    assert.match(noKey.body, /список мест/);
    const retryable = mapUnavailableState('config-failed');
    assert.match(retryable.body, /Попробуйте ещё раз/);
    assert.match(retryable.retryLabel, /Повторить/);
    assert.match(scriptUrl('abc'), /api-maps\.yandex\.ru\/2\.1\//);
    assert.match(scriptUrl('abc'), /apikey=abc/);
    assert.equal(scriptUrl(''), '');
  });

  it('fetchMapConfigKey retries 429 then returns a key', async () => {
    const { fetchMapConfigKey } = loadModel();
    let calls = 0;
    const fetchImpl = () => {
      calls += 1;
      if (calls === 1) {
        return Promise.resolve({
          ok: false,
          status: 429,
          headers: { get: () => '0' },
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ yandex_maps_js_api_key: 'retry-key' }),
      });
    };
    const result = await fetchMapConfigKey(fetchImpl, { budgetMs: 6000 });
    assert.equal(result.key, 'retry-key');
    assert.equal(result.missingKey, false);
    assert.ok(calls >= 2);
  });

  it('fetchMapConfigKey: empty 200 sets missingKey, transport error does not', async () => {
    const { fetchMapConfigKey } = loadModel();
    const empty = await fetchMapConfigKey(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ yandex_maps_js_api_key: '' }),
      })
    );
    assert.equal(empty.missingKey, true);
    assert.equal(empty.reason, 'no-key');
    const fail = await fetchMapConfigKey(() => Promise.reject(new Error('net')), { budgetMs: 200 });
    assert.equal(fail.missingKey, false);
    assert.equal(fail.reason, 'config-failed');
  });

  it('stops inside the budget and keeps the last real status', async () => {
    const { fetchMapConfigKey } = loadModel();
    const result = await fetchMapConfigKey(
      () =>
        Promise.resolve({
          ok: false,
          status: 503,
          headers: { get: () => '30' },
        }),
      { budgetMs: 80, perFetchMs: 5000 }
    );
    assert.equal(result.status, 503);
    assert.equal(result.missingKey, false);
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

describe('pin chrome (TASK-147: пин = время)', () => {
  it('A/B с сеансом в окне — пилюля с временем; C — имя, outside — приглушено', () => {
    const { pinView } = loadModel();
    const a = pinView(rink());
    assert.equal(a.tone, 'a');
    assert.equal(a.muted, false);
    assert.equal(a.kind, 'place');
    assert.equal(a.label, '11:00');
    assert.equal(a.time, '11:00');
    assert.equal(a.shortName, 'Чижовка');
    assert.equal(a.venue, 'ice');
    assert.equal(a.selected, false);
    const b = pinView(rink({ id: 3, tier: 'B', live: { kind: 'session', starts_at_local: '15:00' } }));
    assert.equal(b.kind, 'place');
    assert.equal(b.label, '15:00');
    assert.equal(b.time, '15:00');
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
    assert.equal(c.kind, 'place');
    assert.equal(c.time, '');
    assert.ok(c.label);
  });

  it('TASK-146: сеанс вне выбранного окна — пин полый и без времени', () => {
    const { pinView } = loadModel();
    const base = rink();
    const off = pinView(rink({ live: Object.assign({}, base.live, { outside_window: true }) }));
    assert.equal(off.when, 'off');
    assert.equal(off.muted, true);
    assert.equal(off.kind, 'place');
    assert.equal(off.time, '');
    assert.equal(pinView(base).when, 'in');
  });

  it('selected флаг пробрасывается', () => {
    const { pinView } = loadModel();
    const sel = pinView(rink(), { selected: true });
    assert.equal(sel.selected, true);
    const unsel = pinView(rink());
    assert.equal(unsel.selected, false);
  });
});

describe('clusterSummary / railOrder / sheetSummary / snapFor (TASK-147)', () => {
  it('clusterSummary считает количество, минимальное время и ярлык', () => {
    const { clusterSummary } = loadModel();
    const items = [
      rink({ id: 1, live: { kind: 'session', starts_at_local: '19:30' } }),
      rink({ id: 2, live: { kind: 'session', starts_at_local: '18:15' } }),
      rink({ id: 3, tier: 'C', live: { kind: 'unknown' } }),
    ];
    const s = clusterSummary(items);
    assert.equal(s.count, 3);
    assert.equal(s.hasHits, true);
    assert.equal(s.minTime, '18:15');
    assert.equal(s.label, 'с 18:15');
  });

  it('clusterSummary без сеансов — «нет сеансов»', () => {
    const { clusterSummary } = loadModel();
    const s = clusterSummary([
      rink({ id: 1, tier: 'C', live: { kind: 'unknown' } }),
      rink({ id: 2, tier: 'C', live: { kind: 'unknown' } }),
    ]);
    assert.equal(s.hasHits, false);
    assert.equal(s.label, 'нет сеансов');
  });

  it('railOrder — сначала места с сеансом по времени, потом остальные', () => {
    const { railOrder } = loadModel();
    const items = [
      rink({ id: 1, live: { kind: 'session', starts_at_local: '19:30' } }),
      rink({ id: 2, tier: 'C', live: { kind: 'unknown' } }),
      rink({ id: 3, live: { kind: 'session', starts_at_local: '18:15' } }),
      rink({ id: 4, tier: 'C', live: { kind: 'unknown' } }),
    ];
    const ordered = railOrder(items);
    assert.deepEqual(
      ordered.map((it) => it.id),
      [3, 1, 2, 4]
    );
  });

  it('sheetSummary — лёд с сеансами и магазины отдельно', () => {
    const { sheetSummary } = loadModel();
    const items = [];
    for (let i = 0; i < 7; i++) {
      items.push(rink({ id: i + 1, live: { kind: 'session', starts_at_local: '19:00' } }));
    }
    items.push(rink({ id: 100, venue_type: 'shop', live: { kind: 'unknown' } }));
    items.push(rink({ id: 101, venue_type: 'shop', live: { kind: 'unknown' } }));
    const s = sheetSummary(items, { key: 'evening', label: 'сегодня вечером' });
    assert.match(s, /7 мест/);
    assert.match(s, /сегодня вечером/);
    assert.match(s, /7 сеансов/);
    assert.match(s, /ещё 2 магазина/);
    assert.doesNotMatch(s, /без сеансов/);
  });

  it('sheetSummary — только магазины на карте', () => {
    const { sheetSummary } = loadModel();
    const items = [];
    for (let i = 0; i < 13; i++) {
      items.push(rink({ id: i + 1, venue_type: 'shop', live: { kind: 'place', text: 'Розница' } }));
    }
    const s = sheetSummary(items, null);
    assert.equal(s, '13 магазинов');
    assert.doesNotMatch(s, /сеанс/);
  });

  it('sheetRailEmptyState — выдача без координат', () => {
    const { sheetRailEmptyState } = loadModel();
    const noCoords = [
      rink({ id: 1, latitude: null, longitude: null, on_map: false }),
      rink({ id: 2, latitude: null, longitude: null, on_map: false }),
    ];
    const st = sheetRailEmptyState({ listItems: noCoords, mapItems: noCoords });
    assert.equal(st.title, 'На карте пока нет точек');
    assert.equal(st.action.kind, 'list');
    const mapped = [rink({ id: 9, latitude: 53.91, longitude: 27.51 })];
    assert.equal(sheetRailEmptyState({ listItems: mapped, mapItems: mapped }), null);
  });

  it('pinLayerSignature меняется при смене live', () => {
    const { pinLayerSignature } = loadModel();
    const a = [rink({ id: 1, live: { starts_at_local: '18:00' } })];
    const b = [rink({ id: 1, live: { starts_at_local: '19:00' } })];
    assert.notEqual(pinLayerSignature(a), pinLayerSignature(b));
  });

  it('singlePlaceFocus — bbox вокруг координат магазина', () => {
    const { singlePlaceFocus } = loadModel();
    const f = singlePlaceFocus({ latitude: 53.9, longitude: 27.56, venue_type: 'shop' }, {
      margin: [150, 70, 240, 70],
    });
    assert.ok(f);
    assert.deepEqual(f.bounds[0], [53.9 - 0.0018, 27.56 - 0.0018]);
    assert.deepEqual(f.margin, [150, 70, 240, 70]);
  });

  it('snapFor — ближайшее положение шторки', () => {
    const { snapFor } = loadModel();
    const snaps = { peek: 96, half: 222, full: 600 };
    assert.equal(snapFor(90, snaps), 'peek');
    assert.equal(snapFor(150, snaps), 'peek'); // 150 ближе к 96, чем к 222
    assert.equal(snapFor(400, snaps), 'half'); // 400 ближе к 222, чем к 600
    assert.equal(snapFor(160, snaps), 'half'); // 160 ближе к 222, чем к 96
    assert.equal(snapFor(500, snaps), 'full'); // 500 ближе к 600, чем к 222
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

  it('does not invent a Minsk camera when the new city has no mapped rinks', () => {
    const { cityCameraFromItems, mapStartDecision } = loadModel();
    assert.equal(cityCameraFromItems([]), null);
    const empty = mapStartDecision({ key: 'live-key', listItems: [], intent: 'skate' });
    assert.equal(empty.kind, 'no-arenas');
    assert.equal(empty.showMap, false);
    const moscow = cityCameraFromItems([], { fallbackCenter: [55.7558, 37.6173] });
    assert.ok(moscow.center[0] > 55.5 && moscow.center[0] < 56);
    assert.ok(moscow.center[1] > 37 && moscow.center[1] < 38);
  });

  it('frames the whole city from cityBounds when only 1-2 pins have a live session (Moscow bug)', () => {
    const { cityCameraFromItems } = loadModel();
    // Real-shape repro: one live pin near the center, but the city (Moscow metro,
    // Zhukovsky/Sergiev Posad/etc.) spans ~150km — far bigger than the Minsk floor.
    const cam = cityCameraFromItems(
      [rink({ id: 1, latitude: 55.75, longitude: 37.62 })],
      { cityBounds: { min_lat: 55.05, max_lat: 56.30, min_lon: 36.60, max_lon: 38.90 } }
    );
    const [[minLat, minLon], [maxLat, maxLon]] = cam.restrict;
    assert.ok(minLat <= 55.05 && maxLat >= 56.30, 'restrict must cover the city-wide bounds, not just the pin');
    assert.ok(minLon <= 36.60 && maxLon >= 38.90);
    assert.ok(maxLat - minLat > 1, 'city-wide span dwarfs the Minsk floor');
    assert.ok(maxLon - minLon > 2);
    // Center follows the wide box, not the single live pin.
    assert.ok(Math.abs(cam.center[0] - 55.675) < 0.2);
  });

  it('never clips a live pin that (implausibly) sits outside the reported cityBounds', () => {
    const { cityCameraFromItems } = loadModel();
    const cam = cityCameraFromItems(
      [rink({ id: 1, latitude: 60.0, longitude: 40.0 })],
      { cityBounds: { min_lat: 55.05, max_lat: 56.30, min_lon: 36.60, max_lon: 38.90 } }
    );
    const [[minLat, minLon], [maxLat, maxLon]] = cam.restrict;
    assert.ok(maxLat >= 60.0 - 1e-9, 'pin hull is unioned with cityBounds, never shrunk below it');
    assert.ok(maxLon >= 40.0 - 1e-9);
  });

  it('uses cityBounds alone (still padded) when there are zero live pins', () => {
    const { cityCameraFromItems } = loadModel();
    const cam = cityCameraFromItems(
      [],
      { cityBounds: { min_lat: 55.05, max_lat: 56.30, min_lon: 36.60, max_lon: 38.90 } }
    );
    assert.ok(cam);
    const [[minLat, minLon], [maxLat, maxLon]] = cam.restrict;
    assert.ok(minLat <= 55.05 && maxLat >= 56.30);
    assert.ok(minLon <= 36.60 && maxLon >= 38.90);
  });

  it('leaves Minsk pixel-identical when cityBounds ≈ the live-pin hull already', () => {
    const { cityCameraFromItems } = loadModel();
    const items = [
      rink({ id: 1, latitude: 53.859, longitude: 27.627 }),
      rink({ id: 2, latitude: 53.908, longitude: 27.55 }),
      rink({ id: 3, latitude: 53.938, longitude: 27.49 }),
    ];
    const without = cityCameraFromItems(items);
    const withBounds = cityCameraFromItems(items, {
      cityBounds: { min_lat: 53.859, max_lat: 53.938, min_lon: 27.49, max_lon: 27.627 },
    });
    assert.deepEqual(withBounds.restrict, without.restrict);
    assert.deepEqual(withBounds.center, without.center);
    assert.equal(withBounds.minZoom, without.minZoom);
    assert.equal(withBounds.maxZoom, without.maxZoom);
  });

  it('falls back to the Minsk floor when cityBounds is malformed/missing (brand new city)', () => {
    const { cityCameraFromItems } = loadModel();
    const bogus = cityCameraFromItems([rink({ latitude: 55.19, longitude: 30.2 })], {
      cityBounds: { min_lat: 'nope', max_lat: null, min_lon: undefined, max_lon: 1 },
    });
    const clean = cityCameraFromItems([rink({ latitude: 55.19, longitude: 30.2 })]);
    assert.deepEqual(bogus.restrict, clean.restrict);
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
    // TASK-146: id важнее slug — slug уникален только внутри города.
    assert.equal(target.href, 'arena?ref=12');
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

describe('clusterFocus (тап по кластеру)', () => {
  it('разнесённые места: вписать с полями под ярлыки и не глубже 16', () => {
    const { clusterFocus } = loadModel();
    const f = clusterFocus([[53.90, 27.55], [53.92, 27.58]], { maxZoom: 19 });
    assert.equal(f.mode, 'zoom');
    assert.deepEqual(f.bounds, [[53.90, 27.55], [53.92, 27.58]]);
    assert.equal(f.maxZoom, 16);
    assert.ok(f.margin[0] >= 100, 'сверху поле под ярлык пина');
  });

  it('места в одном комплексе: не зумить, показать списком', () => {
    const { clusterFocus } = loadModel();
    assert.equal(clusterFocus([[53.9, 27.55], [53.9002, 27.5501]]).mode, 'list');
  });

  it('уважает более строгий maxZoom карты', () => {
    const { clusterFocus } = loadModel();
    assert.equal(clusterFocus([[53.9, 27.5], [53.95, 27.6]], { maxZoom: 14 }).maxZoom, 14);
  });

  it('пустой кластер — ничего не делать', () => {
    const { clusterFocus } = loadModel();
    assert.equal(clusterFocus([]).mode, 'none');
  });
});

describe('тип места: цвет пина и легенда (TASK-147, хвост к макету 02)', () => {
  const fs = require('node:fs');
  const cssPath = path.resolve(__dirname, '../../static/webapp/ice-tab.css');
  const themePath = path.resolve(__dirname, '../../static/webapp/theme.css');

  function place(id, venue, extra) {
    return rink(Object.assign({ id, venue_type: venue, latitude: 53.9 + id / 100, longitude: 27.5 }, extra || {}));
  }

  it('pinView.venue: неизвестный и пустой тип — лёд, как на сервере', () => {
    const { pinView, venueKey } = loadModel();
    const shopPin = pinView(place(1, 'shop'));
    assert.equal(shopPin.venue, 'shop');
    assert.equal(shopPin.kind, 'place');
    assert.ok(shopPin.label);
    assert.equal(shopPin.muted, false);
    assert.equal(pinView(place(2, 'POOL')).venue, 'pool');
    assert.equal(pinView(place(3, 'zoo')).venue, 'ice');
    assert.equal(pinView(place(4, '')).venue, 'ice');
    assert.equal(venueKey({}), 'ice');
    assert.equal(venueKey(null), 'ice');
  });

  it('легенда: только типы из выдачи, фиксированный порядок', () => {
    const { legendView } = loadModel();
    const v = legendView([place(1, 'shop'), place(2, 'ice'), place(3, 'gym'), place(4, 'ice')]);
    assert.equal(v.show, true);
    assert.deepEqual(v.entries.map((e) => e.key), ['ice', 'gym', 'shop']);
    assert.deepEqual(v.entries.map((e) => e.label), ['Лёд', 'Зал', 'Магазин']);
  });

  it('легенда: нет магазинов в выдаче — «Магазин» в легенде нет', () => {
    const { legendView } = loadModel();
    const v = legendView([place(1, 'ice'), place(2, 'gym')]);
    assert.deepEqual(v.entries.map((e) => e.key), ['ice', 'gym']);
  });

  it('outdoor — это лёд: цвет льда, в легенде сводится со льдом в одну запись «Лёд»', () => {
    const { legendView, VENUE_TOKEN, pinView } = loadModel();
    assert.equal(VENUE_TOKEN.outdoor, VENUE_TOKEN.ice);
    assert.equal(VENUE_TOKEN.outdoor, '--app-venue-ice');
    // сам пин по-прежнему знает свой тип (класс ice-ypin--outdoor), цвет ему даёт CSS
    assert.equal(pinView(place(1, 'outdoor')).venue, 'outdoor');
    const mixed = legendView([place(1, 'ice', { venue_chip: 'Лёд' }), place(2, 'outdoor', { venue_chip: 'Улица' }), place(3, 'shop')]);
    assert.deepEqual(mixed.entries.map((e) => e.key), ['ice', 'shop']);
    assert.deepEqual(mixed.entries.map((e) => e.label), ['Лёд', 'Магазин']);
    // только лёд + улица — это один цвет, легенды нет
    assert.equal(legendView([place(1, 'ice'), place(2, 'outdoor')]).show, false);
    // улица одна среди других типов: запись «Лёд», а не «Улица»; в легенде не бывает записи outdoor
    const only = legendView([place(1, 'outdoor', { venue_chip: 'Улица' }), place(2, 'gym')]);
    assert.deepEqual(only.entries.map((e) => e.label), ['Лёд', 'Зал']);
    assert.ok(!only.entries.some((e) => e.key === 'outdoor'));
  });

  it('легенда: один тип (или пусто) — блока нет вообще', () => {
    const { legendView } = loadModel();
    assert.equal(legendView([place(1, 'ice'), place(2, 'ice')]).show, false);
    assert.equal(legendView([place(1, 'gym')]).show, false);
    assert.equal(legendView([]).show, false);
    assert.equal(legendView(null).show, false);
  });

  it('легенда считает только места с координатами (как пины)', () => {
    const { legendView } = loadModel();
    const off = place(2, 'shop', { latitude: null, longitude: null, on_map: false });
    assert.equal(legendView([place(1, 'ice'), off]).show, false);
  });

  it('легенда: подпись с сервера (venue_chip) важнее запасной; без неё — запасная', () => {
    const { legendView } = loadModel();
    const v = legendView([place(1, 'ice', { venue_chip: 'Каток' }), place(2, 'pool')]);
    assert.deepEqual(v.entries.map((e) => e.label), ['Каток', 'Бассейн']);
  });

  it('тип без выдумок: неизвестный тип в выдаче даёт «Лёд», а не новую запись', () => {
    const { legendView } = loadModel();
    const v = legendView([place(1, 'zoo'), place(2, 'ice')]);
    assert.equal(v.show, false);
  });

  it('время на пине — только у льда: у зала/магазина «10:00–20:00» это часы, а не сеанс', () => {
    const { pinView, clusterSummary } = loadModel();
    const gym = place(1, 'gym', { live: { kind: 'place', text: 'Сегодня 10:00–20:00' } });
    const v = pinView(gym);
    assert.equal(v.kind, 'place');
    assert.equal(v.time, '');
    assert.ok(v.label);
    assert.equal(clusterSummary([gym]).hasHits, false);
    const outdoor = place(2, 'outdoor', { live: { kind: 'session', text: 'Сегодня 19:00', starts_at_local: '19:00' } });
    assert.equal(pinView(outdoor).time, '19:00');
  });

  it('каждому типу — токен --app-venue-*, который есть в theme.css, и правило в CSS пина и легенды', () => {
    const { VENUE_TOKEN } = loadModel();
    const css = fs.readFileSync(cssPath, 'utf8');
    const theme = fs.readFileSync(themePath, 'utf8');
    Object.keys(VENUE_TOKEN).forEach((key) => {
      const token = VENUE_TOKEN[key];
      assert.match(token, /^--app-venue-/);
      assert.ok(theme.includes(token + ':'), token + ' объявлен в theme.css');
      [`.ice-ypin--${key}`, `.ice-map-legend__item--${key}`].forEach((sel) => {
        const at = css.indexOf(sel);
        assert.ok(at >= 0, sel + ' есть в ice-tab.css');
        const block = css.slice(at, css.indexOf('}', at));
        assert.ok(block.includes('--map-venue: var(' + token + ')'), sel + ' → ' + token);
      });
    });
  });

  it('CSS карты: новых hex нет в блоках типа и легенды', () => {
    const css = fs.readFileSync(cssPath, 'utf8');
    const from = css.indexOf('TASK-147 (хвост к макету 02)');
    const to = css.indexOf('.ice-map-legend__dot');
    const block = css.slice(from, css.indexOf('}', to));
    assert.doesNotMatch(block, /#[0-9a-fA-F]{3,8}\b/);
  });
  it('полые точки (без сеанса) остаются серыми, как .pin-hollow макета 02', () => {
    const css = fs.readFileSync(cssPath, 'utf8');
    const at = css.indexOf('.ice-ypin--dot::after {');
    const block = css.slice(at, css.indexOf('}', at));
    assert.match(block, /border:\s*1\.5px solid var\(--glide-line-strong\)/);
    assert.doesNotMatch(block, /--map-venue/);
  });

  it('копирайт Яндекса: bottom считается от таб-бара, как у шторки (иначе он под шторкой)', () => {
    const css = fs.readFileSync(cssPath, 'utf8');
    const at = css.indexOf('.ice-map-attrib {');
    const block = css.slice(at, css.indexOf('}', at));
    assert.match(block, /bottom:\s*calc\(var\(--client-shell-tab-inset, 80px\) \+ 104px\)/);
    const js = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/ice-map.js'), 'utf8');
    assert.match(js, /attribEl\.style\.bottom = 'calc\(var\(--client-shell-tab-inset, 80px\) \+ '/);
  });
});
