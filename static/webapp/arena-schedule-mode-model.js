/**
 * TASK-204: режим расписания арены — в паре с src/shared/arena_schedule_mode.py.
 * TASK-207: phoneToTelHref — та же идея, что src/shared/phone_guard.tel_href (упрощённый порт).
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
  var MAX_PHONE_INPUT = 64;
  var PHONE_LIKE = /\+?\d[\d\s().-]{5,}\d/g;
  var CLOCK_COLON = /\d{1,2}:\d{2}/g;
  var EXT_TAIL = /(?:\s|,)*(?:доб\.?|ext\.?|вн\.?)\s*\d.*$/i;

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

  function asciiDigits(s) {
    return (String(s).match(/\d/g) || []).join('');
  }

  function stripColonTimes(s) {
    return String(s).replace(CLOCK_COLON, ' ');
  }

  function shouldStripTrailingParen(inner) {
    return (
      /[a-zA-Zа-яА-Я]/.test(inner) ||
      inner.indexOf('/') >= 0 ||
      CLOCK_COLON.test(inner) ||
      /касса|telegram/i.test(inner)
    );
  }

  function stripTrailingParenNote(chunk) {
    var trimmed = String(chunk || '').trim();
    while (true) {
      var m = /\s*\(([^)]*)\)\s*$/.exec(trimmed);
      if (!m || !shouldStripTrailingParen(m[1])) return trimmed;
      trimmed = trimmed.slice(0, m.index).trim();
    }
  }

  function trimIncompleteParenTail(chunk) {
    var trimmed = String(chunk || '').trim();
    var open = (trimmed.match(/\(/g) || []).length;
    var close = (trimmed.match(/\)/g) || []).length;
    if (open !== close && trimmed.indexOf('(') >= 0) {
      trimmed = trimmed.slice(0, trimmed.lastIndexOf('(')).trim();
    }
    return trimmed;
  }

  function hrefFromPhoneLike(chunk) {
    var trimmed = trimIncompleteParenTail(String(chunk || '').replace(EXT_TAIL, '').trim());
    trimmed = stripTrailingParenNote(trimmed);
    if (!trimmed) return '';
    var plus = trimmed.charAt(0) === '+';
    var digits = asciiDigits(trimmed);
    if (digits.length < 7) return '';
    return plus ? '+' + digits : digits;
  }

  function firstPhoneLikeHref(text) {
    var raw = String(text || '').trim().slice(0, MAX_PHONE_INPUT);
    if (!raw) return '';
    var segments = phoneNumbers(raw);
    if (!segments.length) segments = [raw];
    var i;
    for (i = 0; i < segments.length; i++) {
      var prepared = stripColonTimes(segments[i]);
      var m;
      PHONE_LIKE.lastIndex = 0;
      while ((m = PHONE_LIKE.exec(prepared))) {
        var href = hrefFromPhoneLike(m[0]);
        if (href) return href;
      }
    }
    prepared = stripColonTimes(raw);
    PHONE_LIKE.lastIndex = 0;
    while ((m = PHONE_LIKE.exec(prepared))) {
      var hrefAll = hrefFromPhoneLike(m[0]);
      if (hrefAll) return hrefAll;
    }
    return '';
  }

  function phoneToTelHref(phone) {
    var href = firstPhoneLikeHref(phone);
    return href ? 'tel:' + href : '';
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
