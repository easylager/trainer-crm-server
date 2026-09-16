/**
 * Auto-geolocation guard + response parsing for client catalog cold-open city detection.
 * Run: node --test tests/js/catalog-geo-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/catalog-geo-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

function baseCtx(overrides) {
  return Object.assign(
    {
      cityId: null,
      hasExplicitQueryCityId: false,
      hasCollectiveContext: false,
      hasDeepLinkTrainer: false,
      hasPrimaryTrainer: false,
      geolocationSupported: true,
      previouslyDeclined: false,
    },
    overrides || {}
  );
}

describe('shouldAutoGeolocate', () => {
  it('fires on a genuinely cold, contextless open', () => {
    const M = loadModel();
    assert.equal(M.shouldAutoGeolocate(baseCtx()), true);
  });

  it('does not fire when a city is already resolved', () => {
    const M = loadModel();
    assert.equal(M.shouldAutoGeolocate(baseCtx({ cityId: 1 })), false);
  });

  it('does not fire with an explicit ?city_id= in the URL', () => {
    const M = loadModel();
    assert.equal(M.shouldAutoGeolocate(baseCtx({ hasExplicitQueryCityId: true })), false);
  });

  it('does not fire inside a collective/org catalog context', () => {
    const M = loadModel();
    assert.equal(M.shouldAutoGeolocate(baseCtx({ hasCollectiveContext: true })), false);
  });

  it('does not fire with a deep-linked trainer', () => {
    const M = loadModel();
    assert.equal(M.shouldAutoGeolocate(baseCtx({ hasDeepLinkTrainer: true })), false);
  });

  it('does not fire when a primary trainer was resolved from saved edges', () => {
    const M = loadModel();
    assert.equal(M.shouldAutoGeolocate(baseCtx({ hasPrimaryTrainer: true })), false);
  });

  it('does not fire without navigator.geolocation support', () => {
    const M = loadModel();
    assert.equal(M.shouldAutoGeolocate(baseCtx({ geolocationSupported: false })), false);
  });

  it('does not fire again after a prior decline/failure', () => {
    const M = loadModel();
    assert.equal(M.shouldAutoGeolocate(baseCtx({ previouslyDeclined: true })), false);
  });
});

describe('pickCityFromNearResponse', () => {
  it('reads city_id off the first item', () => {
    const M = loadModel();
    assert.equal(M.pickCityFromNearResponse({ items: [{ city_id: 42 }] }), 42);
  });

  it('returns null for empty items', () => {
    const M = loadModel();
    assert.equal(M.pickCityFromNearResponse({ items: [] }), null);
  });

  it('returns null for missing/malformed response', () => {
    const M = loadModel();
    assert.equal(M.pickCityFromNearResponse(null), null);
    assert.equal(M.pickCityFromNearResponse({}), null);
    assert.equal(M.pickCityFromNearResponse({ items: [{}] }), null);
    assert.equal(M.pickCityFromNearResponse({ items: [{ city_id: 'x' }] }), null);
  });

  it('rejects non-positive city ids', () => {
    const M = loadModel();
    assert.equal(M.pickCityFromNearResponse({ items: [{ city_id: 0 }] }), null);
    assert.equal(M.pickCityFromNearResponse({ items: [{ city_id: -3 }] }), null);
  });
});

describe('buildNearUrl', () => {
  it('matches the existing Ice-tab near= endpoint shape', () => {
    const M = loadModel();
    assert.equal(
      M.buildNearUrl(53.9, 27.5667),
      '/api/public/ice/arenas?intent=coach&near=53.90000%2C27.56670&limit=1'
    );
  });
});

describe('declined flag round-trip', () => {
  it('reads false when unset, true after writing', () => {
    const M = loadModel();
    const store = {
      _v: {},
      getItem(k) { return Object.prototype.hasOwnProperty.call(this._v, k) ? this._v[k] : null; },
      setItem(k, v) { this._v[k] = v; },
    };
    assert.equal(M.readDeclinedFlag(store), false);
    M.writeDeclinedFlag(store);
    assert.equal(M.readDeclinedFlag(store), true);
  });

  it('is safe when storage is unavailable', () => {
    const M = loadModel();
    assert.equal(M.readDeclinedFlag(null), false);
    assert.doesNotThrow(() => M.writeDeclinedFlag(null));
  });
});
