/**
 * Catalog auto-geolocation — pure view-model (no DOM, no browser APIs).
 * Browser: window.CatalogGeoModel. Node tests: module.exports.
 *
 * Client catalog has no city picker. When a client opens it with zero city context
 * (no session city, no ?city_id=, no collective brand, no deep-linked/primary trainer),
 * the trainer list query omits city_id entirely and returns an unfiltered, rating-sorted
 * list across ALL cities — which today is dominated by Minsk simply because that's where
 * most of the trainer base already is. This isn't a hardcoded "default to Minsk"; it just
 * looks like one to a visitor from another city/country. This model decides when it's safe
 * to ask the browser for the visitor's real location instead of falling through to that
 * unfiltered global list.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.CatalogGeoModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var DECLINED_STORAGE_KEY = 'glide_geo_declined_v1';

  /**
   * @param {object} ctx
   * @param {number|null} ctx.cityId — resolved city after all existing session/query/
   *   collective/deep-link logic has run.
   * @param {boolean} ctx.hasExplicitQueryCityId — `?city_id=` was present in the URL.
   * @param {boolean} ctx.hasCollectiveContext — opened via `?collective=` brand.
   * @param {boolean} ctx.hasDeepLinkTrainer — `?trainer_id=` deep link.
   * @param {boolean} ctx.hasPrimaryTrainer — a primary trainer was resolved from saved edges.
   * @param {boolean} ctx.geolocationSupported — `!!navigator.geolocation` at call site.
   * @param {boolean} ctx.previouslyDeclined — decline flag already set (see declineFlag* below).
   * @returns {boolean} true only for a genuinely cold, contextless open.
   */
  function shouldAutoGeolocate(ctx) {
    ctx = ctx || {};
    if (ctx.cityId) return false;
    if (ctx.hasExplicitQueryCityId) return false;
    if (ctx.hasCollectiveContext) return false;
    if (ctx.hasDeepLinkTrainer) return false;
    if (ctx.hasPrimaryTrainer) return false;
    if (!ctx.geolocationSupported) return false;
    if (ctx.previouslyDeclined) return false;
    return true;
  }

  /**
   * The nearest match has no distance cap on the server (it always returns the closest
   * item in the whole database, however far). A visitor with no served city nearby would
   * otherwise get silently assigned whatever city happens to be geographically closest —
   * e.g. someone thousands of km away still "matches" Minsk. Beyond this radius we treat
   * it as "no confident match" rather than guessing.
   */
  var MAX_MATCH_DISTANCE_KM = 150;

  /**
   * Extract a usable city_id from GET /api/public/ice/arenas?near=...&limit=1.
   * Defensive against empty/malformed responses — never throws. Rejects matches farther
   * than MAX_MATCH_DISTANCE_KM (see above) — a distant nearest-anything is not a real match.
   */
  function pickCityFromNearResponse(data) {
    if (!data || !Array.isArray(data.items) || !data.items.length) return null;
    var first = data.items[0];
    if (!first || first.city_id == null) return null;
    var dist = first.distance_km;
    if (dist != null && Number(dist) > MAX_MATCH_DISTANCE_KM) return null;
    var id = parseInt(first.city_id, 10);
    return isNaN(id) || id <= 0 ? null : id;
  }

  /** Same endpoint/shape as the existing Ice-tab "Определить город" button (ice-tab.js). */
  function buildNearUrl(lat, lon) {
    var near = Number(lat).toFixed(5) + ',' + Number(lon).toFixed(5);
    return '/api/public/ice/arenas?intent=coach&near=' + encodeURIComponent(near) + '&limit=1';
  }

  function readDeclinedFlag(storage) {
    try {
      return !!(storage && storage.getItem(DECLINED_STORAGE_KEY));
    } catch (e) {
      return false;
    }
  }

  function writeDeclinedFlag(storage) {
    try {
      if (storage) storage.setItem(DECLINED_STORAGE_KEY, '1');
    } catch (e) {
      /* storage unavailable (e.g. private mode) — worst case we ask again next open */
    }
  }

  return {
    DECLINED_STORAGE_KEY: DECLINED_STORAGE_KEY,
    MAX_MATCH_DISTANCE_KM: MAX_MATCH_DISTANCE_KM,
    shouldAutoGeolocate: shouldAutoGeolocate,
    pickCityFromNearResponse: pickCityFromNearResponse,
    buildNearUrl: buildNearUrl,
    readDeclinedFlag: readDeclinedFlag,
    writeDeclinedFlag: writeDeclinedFlag,
  };
});
