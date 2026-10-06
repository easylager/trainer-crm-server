/**
 * TASK-184: календарь и часы каталога — Europe/Minsk (или timezone арены/города).
 * Browser: window.MinskTime. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.MinskTime = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var DEFAULT_TZ = 'Europe/Minsk';
  var WEEKDAY_MON0 = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function resolveTimeZone(timeZone) {
    var tz = String(timeZone || '').trim();
    return tz || DEFAULT_TZ;
  }

  function dateIso(now, timeZone) {
    now = now instanceof Date ? now : new Date();
    var parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: resolveTimeZone(timeZone),
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(now);
    var y = '1970';
    var m = '01';
    var d = '01';
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].type === 'year') y = parts[i].value;
      if (parts[i].type === 'month') m = parts[i].value;
      if (parts[i].type === 'day') d = parts[i].value;
    }
    return y + '-' + m + '-' + d;
  }

  function ymdParts(now, timeZone) {
    var iso = dateIso(now, timeZone);
    var bits = iso.split('-');
    return { y: Number(bits[0]), m: Number(bits[1]), d: Number(bits[2]) };
  }

  function addDaysIso(iso, days) {
    var bits = String(iso).split('-');
    if (bits.length < 3) return iso;
    var dt = new Date(Date.UTC(Number(bits[0]), Number(bits[1]) - 1, Number(bits[2]) + days));
    return dt.getUTCFullYear() + '-' + pad2(dt.getUTCMonth() + 1) + '-' + pad2(dt.getUTCDate());
  }

  function weekdayMon0(now, timeZone) {
    now = now instanceof Date ? now : new Date();
    var wd = new Intl.DateTimeFormat('en-US', {
      timeZone: resolveTimeZone(timeZone),
      weekday: 'short',
    }).format(now);
    return WEEKDAY_MON0[wd] != null ? WEEKDAY_MON0[wd] : 0;
  }

  function hhmm(now, timeZone) {
    now = now instanceof Date ? now : new Date();
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: resolveTimeZone(timeZone),
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(now);
  }

  function localParts(now, timeZone) {
    now = now instanceof Date ? now : new Date();
    var parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: resolveTimeZone(timeZone),
      hour: '2-digit',
      minute: '2-digit',
      day: 'numeric',
      month: 'numeric',
      hour12: false,
    }).formatToParts(now);
    var out = { hour: 0, minute: 0, day: 1, month: 1 };
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].type === 'hour') out.hour = Number(parts[i].value);
      if (parts[i].type === 'minute') out.minute = Number(parts[i].value);
      if (parts[i].type === 'day') out.day = Number(parts[i].value);
      if (parts[i].type === 'month') out.month = Number(parts[i].value);
    }
    return out;
  }

  /** Календарные сутки между двумя моментами в заданной TZ (для «N дней назад»). */
  function daysBetweenCalendar(earlier, later, timeZone) {
    var a = ymdParts(earlier, timeZone);
    var b = ymdParts(later, timeZone);
    var da = Date.UTC(a.y, a.m - 1, a.d);
    var db = Date.UTC(b.y, b.m - 1, b.d);
    return Math.round((db - da) / 86400000);
  }

  function weekdaySun0FromIso(iso) {
    var bits = String(iso).slice(0, 10).split('-');
    if (bits.length < 3) return 0;
    return new Date(Date.UTC(Number(bits[0]), Number(bits[1]) - 1, Number(bits[2]))).getUTCDay();
  }

  /** PDEC-005: сеанс уже начался (по UTC или по local_date + starts_at_local в TZ). */
  function liveSessionStarted(live, now, timeZone) {
    live = live || {};
    now = now instanceof Date ? now : new Date();
    var startUtc = live.starts_at_utc;
    if (startUtc) {
      var ms = Date.parse(startUtc);
      if (!isNaN(ms)) return ms <= now.getTime();
    }
    var iso = String(live.local_date || '').slice(0, 10);
    var hm = String(live.starts_at_local || '').slice(0, 5);
    if (!iso || !hm) return false;
    var tz = resolveTimeZone(timeZone);
    var today = dateIso(now, tz);
    if (iso < today) return true;
    if (iso > today) return false;
    return hm <= hhmm(now, tz);
  }

  function formatDistanceKm(km) {
    if (km == null || km === '' || isNaN(Number(km))) return '';
    var n = Number(km);
    var text = Number.isInteger(n) ? String(n) : n.toFixed(1).replace('.', ',');
    return text + ' км';
  }

  return {
    DEFAULT_TZ: DEFAULT_TZ,
    resolveTimeZone: resolveTimeZone,
    dateIso: dateIso,
    addDaysIso: addDaysIso,
    weekdayMon0: weekdayMon0,
    weekdaySun0FromIso: weekdaySun0FromIso,
    hhmm: hhmm,
    localParts: localParts,
    daysBetweenCalendar: daysBetweenCalendar,
    liveSessionStarted: liveSessionStarted,
    formatDistanceKm: formatDistanceKm,
    pad2: pad2,
  };
});
