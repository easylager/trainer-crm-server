/**
 * TASK-148 (AC-4): блок «Сегодня на льду» в хабе — 2–3 ближайших сеанса
 * массового катания из live-данных тизера (поле ice_teaser.sessions, которое
 * хаб и так получает в bootstrap — новых запросов блок не делает).
 * Pure view-model (no DOM). Browser: window.HubIceTodayModel. Node: module.exports.
 *
 * Блок ДОПОЛНЯЕТ ice teaser, а не заменяет: тизер показывает ближайший сеанс
 * целиком, этот блок — следующие за ним строки (время · место · цена).
 * Нет сеансов кроме тизерного — блока нет.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.HubIceTodayModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var MINSK_TZ = 'Europe/Minsk';
  var MAX_ROWS = 3;

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function minskDateIso(now) {
    var parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: MINSK_TZ,
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

  function addDaysIso(iso, days) {
    var bits = String(iso).split('-');
    if (bits.length < 3) return iso;
    var dt = new Date(Date.UTC(Number(bits[0]), Number(bits[1]) - 1, Number(bits[2]) + days));
    return dt.getUTCFullYear() + '-' + pad2(dt.getUTCMonth() + 1) + '-' + pad2(dt.getUTCDate());
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function hhmm(raw) {
    var s = String(raw || '').trim();
    return s.length >= 5 ? s.slice(0, 5) : s;
  }

  function dayLabel(localDate, now) {
    var iso = String(localDate || '').slice(0, 10);
    if (!iso) return '';
    var today = minskDateIso(now);
    if (iso === today) return 'Сегодня';
    if (iso === addDaysIso(today, 1)) return 'Завтра';
    return iso.slice(8, 10) + '.' + iso.slice(5, 7);
  }

  function venueWord(venueType) {
    var key = String(venueType || '').toLowerCase();
    if (key === 'outdoor') return 'открытый';
    if (key === 'ice') return 'крытый';
    return '';
  }

  function formatPrice(minor, currency) {
    if (minor == null || minor === '' || isNaN(Number(minor))) return '';
    var major = Number(minor) / 100;
    var num = Number.isInteger(major) ? String(major) : major.toFixed(2);
    return num + ' ' + (currency || 'BYN');
  }

  function hasStarted(session, now) {
    var startMs = Date.parse((session && session.starts_at_utc) || '');
    return !isNaN(startMs) && startMs <= now.getTime();
  }

  /** Ссылка на карточку места с выделенным сеансом — конвенция IceTabModel.arenaHref. */
  function rowHref(session) {
    var ref = (session && (session.arena_id != null ? session.arena_id : session.arena_slug)) || '';
    if (!ref) return '';
    var href = 'arena?ref=' + encodeURIComponent(String(ref));
    var day = String((session && session.local_date) || '').slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(day)) {
      href += '&day=' + day;
      if (session.session_id != null) href += '&s=' + encodeURIComponent(String(session.session_id));
    }
    return href;
  }

  function formatRow(session, now) {
    var name = String((session && session.arena_name) || '').trim();
    var word = venueWord(session && session.venue_type);
    var place = name;
    if (word) place += ' · ' + word;
    var day = dayLabel(session && session.local_date, now);
    if (day && day !== 'Сегодня') place = day + ' · ' + place;
    return {
      time: hhmm(session && session.starts_at_local),
      place: place,
      price: formatPrice(session && session.price_adult_minor, session && session.currency_code),
      href: rowHref(session),
    };
  }

  /**
   * Строки блока из payload тизера: сеансы кроме тизерного, ещё не начавшиеся,
   * не больше MAX_ROWS. Нет тизера / нет сеансов / только тизерный — [].
   */
  function rowsFromTeaser(teaser, now) {
    if (!teaser || typeof teaser !== 'object') return [];
    var sessions = teaser.sessions;
    if (!Array.isArray(sessions) || sessions.length < 2) return [];
    now = now instanceof Date ? now : new Date();
    var ownId = teaser.session_id != null ? Number(teaser.session_id) : null;
    var rows = [];
    for (var i = 0; i < sessions.length && rows.length < MAX_ROWS; i++) {
      var s = sessions[i] || {};
      if (s.session_id != null && ownId != null && Number(s.session_id) === ownId) continue;
      // Фолбэк для старых payload без session_id: не дублируем тизерный сеанс
      // по той же арене и времени старта.
      if (s.session_id == null || ownId == null) {
        var sameArena = String(s.arena_id || '') === String(teaser.arena_id || '');
        var sameStart = String(s.starts_at_utc || '') === String(teaser.starts_at_utc || '');
        if (sameArena && sameStart && s.starts_at_utc) continue;
      }
      if (hasStarted(s, now)) continue;
      var row = formatRow(s, now);
      if (row.time && row.href) rows.push(row);
    }
    return rows;
  }

  function renderRowsHtml(rows) {
    var html = '';
    (rows || []).forEach(function (row) {
      html +=
        '<a class="hub-ice-today__row" href="' + escapeHtml(row.href) + '">' +
        '<span class="hub-ice-today__dot" aria-hidden="true"></span>' +
        '<span class="hub-ice-today__time">' + escapeHtml(row.time) + '</span>' +
        '<span class="hub-ice-today__place">' + escapeHtml(row.place) + '</span>' +
        (row.price ? '<span class="hub-ice-today__price">' + escapeHtml(row.price) + '</span>' : '') +
        '</a>';
    });
    return html;
  }

  return {
    MAX_ROWS: MAX_ROWS,
    rowsFromTeaser: rowsFromTeaser,
    renderRowsHtml: renderRowsHtml,
    rowHref: rowHref,
  };
});
