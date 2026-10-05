/**
 * TASK-180: тексты и даты устаревания расписания — в паре с src/application/schedule_staleness.py.
 * Browser: window.ScheduleStalenessModel. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ScheduleStalenessModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var MINSK_TZ = 'Europe/Minsk';
  var STALE_SHORT = 'могло измениться';
  var MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

  function parseDt(value) {
    if (!value) return null;
    var d = value instanceof Date ? value : new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }

  function minskYmd(d) {
    var parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: MINSK_TZ,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(d);
    var y = '1970';
    var m = '01';
    var day = '01';
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].type === 'year') y = parts[i].value;
      if (parts[i].type === 'month') m = parts[i].value;
      if (parts[i].type === 'day') day = parts[i].value;
    }
    return { y: Number(y), m: Number(m), d: Number(day) };
  }

  function minskDaysBetween(earlier, now) {
    var a = minskYmd(earlier);
    var b = minskYmd(now);
    var da = Date.UTC(a.y, a.m - 1, a.d);
    var db = Date.UTC(b.y, b.m - 1, b.d);
    return Math.round((db - da) / 86400000);
  }

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function minskLocalParts(d) {
    var parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: MINSK_TZ,
      hour: '2-digit',
      minute: '2-digit',
      day: 'numeric',
      month: 'numeric',
      hour12: false,
    }).formatToParts(d);
    var out = { hour: 0, minute: 0, day: 1, month: 1 };
    for (var i = 0; i < parts.length; i++) {
      if (parts[i].type === 'hour') out.hour = Number(parts[i].value);
      if (parts[i].type === 'minute') out.minute = Number(parts[i].value);
      if (parts[i].type === 'day') out.day = Number(parts[i].value);
      if (parts[i].type === 'month') out.month = Number(parts[i].value);
    }
    return out;
  }

  function checkedAtLabel(observed, now) {
    var moment = parseDt(observed);
    if (!moment || !now) return '';
    var local = minskLocalParts(moment);
    var hhmm = pad2(local.hour) + ':' + pad2(local.minute);
    var days = minskDaysBetween(moment, now);
    if (days <= 0) return 'сегодня в ' + hhmm;
    if (days === 1) return 'вчера в ' + hhmm;
    return local.day + ' ' + MONTHS_SHORT[local.month - 1] + ' в ' + hhmm;
  }

  function pluralDays(n) {
    var abs = Math.abs(Number(n));
    var mod10 = abs % 10;
    var mod100 = abs % 100;
    if (mod10 === 1 && mod100 !== 11) return abs + ' день';
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return abs + ' дня';
    return abs + ' дней';
  }

  function stalenessLevel(freshness) {
    freshness = freshness || {};
    if (!freshness.schedule_stale) return 'fresh';
    if (freshness.schedule_very_stale) return 'very_stale';
    return 'stale';
  }

  function askTail(opts) {
    opts = opts || {};
    if (opts.hasPhone) return ' — уточните по телефону';
    if (opts.hasSite) return ' — уточните на сайте катка';
    return ' — уточните у катка';
  }

  function staleNote(freshness, now) {
    if (stalenessLevel(freshness) !== 'stale') return '';
    var when = checkedAtLabel((freshness || {}).schedule_observed_at, now);
    if (when) return 'Расписание могло измениться · проверено ' + when;
    return 'Расписание могло измениться — уточните у катка';
  }

  function veryStaleNote(freshness, now, opts) {
    opts = opts || {};
    if (stalenessLevel(freshness) !== 'very_stale') return '';
    var hasPhone = opts.hasPhone !== undefined ? opts.hasPhone : true;
    var tail = askTail({ hasPhone: hasPhone, hasSite: !!opts.hasSite });
    var observed = parseDt((freshness || {}).schedule_observed_at);
    if (!observed) return 'Расписание не подтверждено' + tail;
    var days = Math.max(1, minskDaysBetween(observed, now));
    return 'Расписание не обновлялось ' + pluralDays(days) + tail;
  }

  function shouldWarnScheduleStale(freshness) {
    return stalenessLevel(freshness) === 'stale';
  }

  function scheduleStaleFlag(item) {
    var f = (item && item.freshness) || {};
    if (f.schedule_stale) return true;
    return !!(item && item.schedule_stale);
  }

  return {
    STALE_SHORT: STALE_SHORT,
    minskDaysBetween: minskDaysBetween,
    checkedAtLabel: checkedAtLabel,
    pluralDays: pluralDays,
    stalenessLevel: stalenessLevel,
    staleNote: staleNote,
    veryStaleNote: veryStaleNote,
    shouldWarnScheduleStale: shouldWarnScheduleStale,
    scheduleStaleFlag: scheduleStaleFlag,
  };
});
