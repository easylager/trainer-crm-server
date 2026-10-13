/**
 * TASK-180: уровни и даты устаревания расписания — в паре с src/application/schedule_staleness.py.
 * TASK-243: публичный UI на уровень не реагирует — сеансы показываем как есть.
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

  var MT =
    typeof module === 'object' && module.exports && typeof require === 'function'
      ? require('./minsk-time.js')
      : typeof globalThis !== 'undefined'
        ? globalThis.MinskTime
        : null;
  var STALE_SHORT = '';
  var MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

  function parseDt(value) {
    if (!value) return null;
    var d = value instanceof Date ? value : new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }

  function minskDaysBetween(earlier, now) {
    return MT.daysBetweenCalendar(earlier, now);
  }

  function checkedAtLabel(observed, now) {
    var moment = parseDt(observed);
    if (!moment || !now) return '';
    var local = MT.localParts(moment);
    var hhmm = MT.pad2(local.hour) + ':' + MT.pad2(local.minute);
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

  function staleNote() {
    return '';
  }

  function shouldWarnScheduleStale() {
    return false;
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
    shouldWarnScheduleStale: shouldWarnScheduleStale,
    scheduleStaleFlag: scheduleStaleFlag,
  };
});
