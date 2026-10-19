/**
 * TASK-305 (AC-1, AC-2): when to start /client/hub/bootstrap vs /client/profiles.
 * Pure decision model (no DOM). Browser: window.HubBootstrapParallel. Node: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.HubBootstrapParallel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /**
   * Explicit profile pick from localStorage (not account default — unknown until profiles load).
   * @param {number|null} storedActiveProfileId
   */
  function shouldStartBootstrapParallel(storedActiveProfileId) {
    return storedActiveProfileId != null;
  }

  /**
   * After profiles resolve: which bootstrap fetch to await.
   * @param {boolean} parallelStarted early bootstrap already in flight
   * @param {number|null} earlySentProfileId acting id when parallel fetch started
   * @param {number|null} actingProfileId acting id after profiles loaded
   * @returns {'use_early'|'refetch'|'after_profiles'}
   */
  function bootstrapFetchPlan(parallelStarted, earlySentProfileId, actingProfileId) {
    if (!parallelStarted) return 'after_profiles';
    if (earlySentProfileId === actingProfileId) return 'use_early';
    return 'refetch';
  }

  return {
    shouldStartBootstrapParallel: shouldStartBootstrapParallel,
    bootstrapFetchPlan: bootstrapFetchPlan,
  };
});
