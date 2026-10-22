/**
 * Как кабинет тренера пишет числа (TASK-314, свод деталей Glide). Одно место вместо
 * десятка самодельных форматтеров по экранам:
 *
 *   phone('375293334455')          → «+375 29 333-44-55»
 *   money(40.5, 'BYN')             → «40,50 BYN»;  money(500, 'RUB') → «500 ₽»
 *   date('2026-10-23', {now})      → «завтра» / «пт, 23 окт»
 *   dateLong('2027-11-26')         → «26 ноября 2027»
 *   time('09:00:00')               → «9:00»
 *   plural(3, 'запись', 'записи', 'записей') → «записи»
 *
 * Browser: window.TrainerFormat. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.TrainerFormat = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var NBSP = ' ';
  var WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  var MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  var MONTHS_GEN = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
  ];

  function plural(n, one, few, many) {
    var a = Math.abs(Number(n)) % 100;
    var b = a % 10;
    if (a >= 11 && a <= 14) return many;
    if (b === 1) return one;
    if (b >= 2 && b <= 4) return few;
    return many;
  }

  /** Беларусь и Россия — по маске; остальное — как пришло, без попытки угадать. */
  function phone(raw) {
    var s = String(raw == null ? '' : raw).trim();
    var d = s.replace(/\D/g, '');
    if (d.length === 12 && d.indexOf('375') === 0) {
      return '+375 ' + d.slice(3, 5) + ' ' + d.slice(5, 8) + '-' + d.slice(8, 10) + '-' + d.slice(10);
    }
    if (d.length === 11 && (d[0] === '7' || d[0] === '8')) {
      return '+7 ' + d.slice(1, 4) + ' ' + d.slice(4, 7) + '-' + d.slice(7, 9) + '-' + d.slice(9);
    }
    return s;
  }

  /** Валюта — код из API. Копейки только когда они есть: «45 BYN», «40,50 BYN». */
  function money(amount, currency) {
    var n = Number(amount);
    if (!isFinite(n)) return '';
    var cur = String(currency || 'BYN').toUpperCase();
    var whole = Math.round(n * 100) % 100 === 0;
    var fixed = whole ? String(Math.round(n)) : n.toFixed(2).replace('.', ',');
    var parts = fixed.split(',');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
    var num = parts.join(',');
    if (cur === 'RUB') return num + NBSP + '₽';
    return num + NBSP + cur;
  }

  /** 'YYYY-MM-DD' — календарная дата без часового пояса; Date и ISO с временем — как есть. */
  function toDate(value) {
    if (value instanceof Date) return new Date(value.getFullYear(), value.getMonth(), value.getDate());
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ''));
    if (!m) return null;
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }

  function dayDiff(a, b) {
    return Math.round((a.getTime() - b.getTime()) / 86400000);
  }

  /** «сегодня», «завтра», «вчера», иначе «пт, 23 окт». */
  function date(value, opts) {
    var d = toDate(value);
    if (!d) return '';
    var now = toDate((opts && opts.now) || new Date());
    var diff = dayDiff(d, now);
    if (diff === 0) return 'сегодня';
    if (diff === 1) return 'завтра';
    if (diff === -1) return 'вчера';
    return WEEKDAYS[d.getDay()] + ', ' + d.getDate() + NBSP + MONTHS_SHORT[d.getMonth()];
  }

  /** «26 ноября 2027» — для сроков (подписка, абонемент). */
  function dateLong(value) {
    var d = toDate(value);
    if (!d) return '';
    return d.getDate() + NBSP + MONTHS_GEN[d.getMonth()] + ' ' + d.getFullYear();
  }

  /** «09:00:00» → «9:00». */
  function time(value) {
    var m = /^(\d{1,2}):(\d{2})/.exec(String(value || ''));
    if (!m) return '';
    return String(Number(m[1])) + ':' + m[2];
  }

  return { plural: plural, phone: phone, money: money, date: date, dateLong: dateLong, time: time };
});
