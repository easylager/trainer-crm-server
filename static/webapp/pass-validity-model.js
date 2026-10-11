/**
 * Suggested term for a trainer session pack.
 *
 * A weekly lesson plus about two weeks of slack, snapped to the terms studios
 * actually sell. Four visits or fewer stay open-ended: the pack runs out
 * before a clock would matter. The trainer can still pick another term.
 */
(function (root) {
  'use strict';

  var PRESETS = [30, 90, 120, 150, 180, 365];

  function recommendedValidityDays(sessions) {
    var n = parseInt(sessions, 10);
    if (!n || n < 1) return null;
    if (n <= 4) return null;
    if (n <= 8) return 90;
    if (n <= 12) return 120;
    if (n <= 16) return 150;
    return 180;
  }

  var api = {
    PRESETS: PRESETS,
    recommendedValidityDays: recommendedValidityDays,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.PassValidity = api;
})(typeof window !== 'undefined' ? window : globalThis);
