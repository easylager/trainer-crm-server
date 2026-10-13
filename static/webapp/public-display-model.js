/**
 * Публичный вывод времени, дня и цены — пара с src/shared/public_display.py
 * и format_price_minor в ice_city_day.py. Browser: window.PublicDisplayModel.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.PublicDisplayModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var WEEKDAYS_SHORT = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];

  function formatClock(hhmm) {
    var raw = String(hhmm == null ? '' : hhmm).trim();
    var m = /^(\d{1,2}):(\d{2})/.exec(raw);
    if (!m) return raw.slice(0, 5);
    return String(Number(m[1])) + ':' + m[2];
  }

  function parseIsoDate(iso) {
    var s = String(iso || '').slice(0, 10);
    var bits = s.split('-');
    if (bits.length < 3) return null;
    return { y: Number(bits[0]), m: Number(bits[1]), d: Number(bits[2]), iso: s };
  }

  function addDaysIso(iso, days) {
    var p = parseIsoDate(iso);
    if (!p) return iso;
    var dt = new Date(Date.UTC(p.y, p.m - 1, p.d + days));
    var y = dt.getUTCFullYear();
    var mo = dt.getUTCMonth() + 1;
    var d = dt.getUTCDate();
    return y + '-' + (mo < 10 ? '0' : '') + mo + '-' + (d < 10 ? '0' : '') + d;
  }

  function weekdayMon0FromIso(iso) {
    var p = parseIsoDate(iso);
    if (!p) return 0;
    var wd = new Date(Date.UTC(p.y, p.m - 1, p.d)).getUTCDay();
    return wd === 0 ? 6 : wd - 1;
  }

  function shortDayWord(dayIso, todayIso) {
    var day = String(dayIso || '').slice(0, 10);
    var today = String(todayIso || '').slice(0, 10);
    if (!day || !today) return '';
    if (day === today) return 'сегодня';
    if (day === addDaysIso(today, 1)) return 'завтра';
    return WEEKDAYS_SHORT[weekdayMon0FromIso(day)] || '';
  }

  function sessionDayPhrase(dayIso, hhmm, todayIso) {
    var clock = formatClock(hhmm);
    var word = shortDayWord(dayIso, todayIso);
    return (word + ' ' + clock).trim();
  }

  function sentenceWhen(dayIso, hhmm, todayIso) {
    var clock = formatClock(hhmm);
    var word = shortDayWord(dayIso, todayIso);
    if (!clock) return word;
    return word + ', ' + clock;
  }

  /** minor без валюты — «10», «8,50» (список льда). */
  function formatMinorAmount(minor) {
    if (minor == null || minor === '' || isNaN(Number(minor))) return '';
    var major = Number(minor) / 100;
    if (major === Math.floor(major)) return String(Math.floor(major));
    return major.toFixed(2).replace('.', ',');
  }

  /** minor + currency → «8,50 BYN»; целые без копеек — «10 BYN». */
  function formatPriceMinor(minor, currency) {
    if (minor == null || minor === '' || isNaN(Number(minor))) return '';
    var code = String(currency || 'BYN').trim();
    var major = Number(minor) / 100;
    if (major === Math.floor(major)) return String(Math.floor(major)) + ' ' + code;
    var text = major.toFixed(2).replace('.', ',');
    return text + ' ' + code;
  }

  return {
    formatClock: formatClock,
    shortDayWord: shortDayWord,
    sessionDayPhrase: sessionDayPhrase,
    sentenceWhen: sentenceWhen,
    formatMinorAmount: formatMinorAmount,
    formatPriceMinor: formatPriceMinor,
    addDaysIso: addDaysIso,
  };
});
