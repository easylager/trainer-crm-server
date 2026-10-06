/**
 * TASK-182: часы работы места — одна реализация для вкладки «Лёд» (ice-tab-model.js)
 * и карточки места (arena-card-model.js). Раньше было две копии, и они разошлись:
 * карточка умела интервал через полночь, фильтр «Открыто сейчас» — нет
 * (10:00–00:00 в 12:00 считался закрытым).
 *
 * Формат как на сервере (src/application/arena_profile.py): `daily: {open, close}`
 * или `weekly: {mon: [[open, close], …], …}`; неделя с понедельника (0 = пн).
 * Интервал, у которого close <= open, заканчивается на следующий день:
 * 10:00–00:00 — до полуночи, 18:00–02:00 — до двух ночи.
 *
 * Browser: window.OpeningHours. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.OpeningHours = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var WEEK_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  var DAY_MINUTES = 24 * 60;

  /** «9», «9.30», « 09:30 » → «09:00», «09:30». Мусор → ''. */
  function normHhmm(raw) {
    var t = String(raw == null ? '' : raw).trim().replace('.', ':');
    var m = /^(\d{1,2})(?::(\d{1,2}))?$/.exec(t);
    if (!m) return '';
    var h = Number(m[1]);
    var mi = Number(m[2] || 0);
    if (h > 24 || mi > 59) return '';
    return (h < 10 ? '0' : '') + h + ':' + (mi < 10 ? '0' : '') + mi;
  }

  function toMinutes(hhmm) {
    var n = normHhmm(hhmm);
    if (!n) return null;
    var p = n.split(':');
    return Number(p[0]) * 60 + Number(p[1]);
  }

  function parseDayIntervals(raw) {
    if (!raw || !raw.length) return [];
    if (Array.isArray(raw[0])) {
      var out = [];
      for (var i = 0; i < raw.length; i++) {
        var seg = raw[i];
        if (!seg || seg.length !== 2) continue;
        var o = normHhmm(seg[0]);
        var c = normHhmm(seg[1]);
        if (o && c) out.push([o, c]);
      }
      return out;
    }
    if (raw.length === 2) {
      var o2 = normHhmm(raw[0]);
      var c2 = normHhmm(raw[1]);
      return o2 && c2 ? [[o2, c2]] : [];
    }
    return [];
  }

  /** Интервалы дня недели (0 = пн) как [['10:00', '20:00'], …]. */
  function intervalsForWeekday(hours, weekday) {
    hours = hours && typeof hours === 'object' ? hours : {};
    if (hours.weekly && typeof hours.weekly === 'object') {
      return parseDayIntervals(hours.weekly[WEEK_KEYS[((weekday % 7) + 7) % 7]]);
    }
    var daily = hours.daily;
    if (daily && typeof daily === 'object') {
      var o = normHhmm(daily.open);
      var c = normHhmm(daily.close);
      return o && c ? [[o, c]] : [];
    }
    return [];
  }

  /** Интервал в минутах от полуночи дня открытия; close > 1440 — уже следующий день. */
  function intervalMinutes(open, close) {
    var o = toMinutes(open);
    var c = toMinutes(close);
    if (o == null || c == null) return null;
    if (c <= o) c += DAY_MINUTES;
    return [o, c];
  }

  /** Строки «ЧЧ:ММ»: попадает ли время в интервал с учётом перехода через полночь. */
  function hhmmInInterval(hm, open, close) {
    var t = toMinutes(hm);
    var iv = intervalMinutes(open, close);
    if (t == null || !iv) return false;
    return (t >= iv[0] && t < iv[1]) || t + DAY_MINUTES < iv[1];
  }

  /**
   * Открытый сейчас интервал или null. Учитывает и вчерашний ночной хвост:
   * пятница 18:00–02:00 держит место открытым в субботу в 01:00.
   */
  function openIntervalAt(hours, weekday, minutes) {
    if (minutes == null || isNaN(minutes)) return null;
    var today = intervalsForWeekday(hours, weekday);
    var i;
    for (i = 0; i < today.length; i++) {
      var iv = intervalMinutes(today[i][0], today[i][1]);
      if (iv && minutes >= iv[0] && minutes < iv[1]) return today[i];
    }
    var yesterday = intervalsForWeekday(hours, (((weekday - 1) % 7) + 7) % 7);
    for (i = 0; i < yesterday.length; i++) {
      var y = intervalMinutes(yesterday[i][0], yesterday[i][1]);
      if (y && minutes + DAY_MINUTES < y[1]) return yesterday[i];
    }
    return null;
  }

  function isOpenAt(hours, weekday, minutes) {
    return !!openIntervalAt(hours, weekday, minutes);
  }

  /** Открыто ли в этот день недели вообще. */
  function opensOnWeekday(hours, weekday) {
    return intervalsForWeekday(hours, weekday).length > 0;
  }

  /** Сегодня ещё будет открыто после `after` (минуты) и после `minutes` (сейчас). */
  function openAfterToday(hours, weekday, minutes, after) {
    var today = intervalsForWeekday(hours, weekday);
    for (var i = 0; i < today.length; i++) {
      var iv = intervalMinutes(today[i][0], today[i][1]);
      if (iv && iv[1] > after && iv[1] > minutes) return true;
    }
    return false;
  }

  return {
    WEEK_KEYS: WEEK_KEYS,
    normHhmm: normHhmm,
    toMinutes: toMinutes,
    parseDayIntervals: parseDayIntervals,
    intervalsForWeekday: intervalsForWeekday,
    intervalMinutes: intervalMinutes,
    hhmmInInterval: hhmmInInterval,
    openIntervalAt: openIntervalAt,
    isOpenAt: isOpenAt,
    opensOnWeekday: opensOnWeekday,
    openAfterToday: openAfterToday,
  };
});
