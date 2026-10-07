/**
 * TASK-204: режим расписания арены — в паре с src/shared/arena_schedule_mode.py.
 * Browser: window.ArenaScheduleModeModel. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ArenaScheduleModeModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var MODES = { auto: 'auto', phone: 'phone', season_closed: 'season_closed' };
  var PHONE_LINE = 'Расписание по телефону';
  var SEASON_CLOSED_LINE = 'Сезон закрыт';

  function normalizeMode(raw) {
    var m = String(raw || MODES.auto).trim().toLowerCase();
    return m === MODES.phone || m === MODES.season_closed ? m : MODES.auto;
  }

  function formatReopenSuffix(iso) {
    var s = String(iso || '').slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return '';
    return 'откроется ' + s.slice(8, 10) + '.' + s.slice(5, 7);
  }

  function seasonClosedLine(card) {
    card = card || {};
    var parts = [SEASON_CLOSED_LINE];
    var suffix = formatReopenSuffix(card.schedule_reopen_date);
    if (suffix) parts.push(suffix);
    var line = parts.join(' · ');
    var note = String(card.schedule_mode_note || '').trim();
    return note ? line + ' — ' + note : line;
  }

  function phoneLine() {
    return PHONE_LINE;
  }

  function phoneNumbers(raw) {
    return String(raw || '')
      .split(/[;,\n]/)
      .map(function (p) {
        return p.trim();
      })
      .filter(Boolean);
  }

  function phoneToTelHref(phone) {
    var first = phoneNumbers(phone)[0] || '';
    var cleaned = String(first).replace(/[^\d+]/g, '');
    return cleaned ? 'tel:' + cleaned : '';
  }

  function isIceTodayEligible(card) {
    return normalizeMode(card && card.schedule_mode) !== MODES.season_closed;
  }

  function liveKindForCard(card) {
    var mode = normalizeMode(card && card.schedule_mode);
    if (mode === MODES.phone) return 'phone';
    if (mode === MODES.season_closed) return 'season_closed';
    return '';
  }

  return {
    MODES: MODES,
    PHONE_LINE: PHONE_LINE,
    SEASON_CLOSED_LINE: SEASON_CLOSED_LINE,
    normalizeMode: normalizeMode,
    formatReopenSuffix: formatReopenSuffix,
    seasonClosedLine: seasonClosedLine,
    phoneLine: phoneLine,
    phoneNumbers: phoneNumbers,
    phoneToTelHref: phoneToTelHref,
    isIceTodayEligible: isIceTodayEligible,
    liveKindForCard: liveKindForCard,
  };
});
