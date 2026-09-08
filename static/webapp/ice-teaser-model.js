/**
 * TASK-055 hub teaser «Лёд рядом» — pure view-model (no DOM).
 * Browser: window.IceTeaserModel. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.IceTeaserModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var MINSK_TZ = 'Europe/Minsk';

  function hiddenView() {
    return { hidden: true, title: '', subtitle: '', href: '' };
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

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
    var dt = new Date(Date.UTC(Number(bits[0]), Number(bits[1]) - 1, Number(bits[2]) + days));
    return dt.getUTCFullYear() + '-' + pad2(dt.getUTCMonth() + 1) + '-' + pad2(dt.getUTCDate());
  }

  function hhmm(raw) {
    var s = String(raw || '').trim();
    return s.length >= 5 ? s.slice(0, 5) : s;
  }

  function pluralMinutes(n) {
    var abs = Math.abs(n) % 100;
    if (abs >= 11 && abs <= 14) return 'минут';
    var last = abs % 10;
    if (last === 1) return 'минуту';
    if (last >= 2 && last <= 4) return 'минуты';
    return 'минут';
  }

  function formatWhen(payload, now) {
    var startMs = Date.parse(payload.starts_at_utc || '');
    if (!isNaN(startMs)) {
      var mins = Math.round((startMs - now.getTime()) / 60000);
      if (mins >= 0 && mins < 60) {
        if (mins <= 0) return 'сейчас';
        return 'через ' + mins + ' ' + pluralMinutes(mins);
      }
    }
    var localDate = String(payload.local_date || '').slice(0, 10);
    var time = hhmm(payload.starts_at_local);
    var today = minskDateIso(now);
    if (localDate === today) return 'сегодня в ' + time;
    if (localDate === addDaysIso(today, 1)) return 'завтра в ' + time;
    if (localDate) return localDate.slice(8, 10) + '.' + localDate.slice(5, 7) + ' в ' + time;
    return time ? 'в ' + time : '';
  }

  function formatDistanceKm(km) {
    if (km == null || km === '' || isNaN(Number(km))) return '';
    var n = Number(km);
    var text = Number.isInteger(n) ? String(n) : n.toFixed(1).replace('.', ',');
    return text + ' км';
  }

  function formatPrice(minor, currency) {
    if (minor == null || minor === '' || isNaN(Number(minor))) return '';
    var major = Number(minor) / 100;
    var num = Number.isInteger(major) ? String(major) : major.toFixed(2);
    return 'взр. ' + num + ' ' + (currency || 'BYN');
  }

  function kindLabel(kind) {
    var k = String(kind || '');
    if (k === 'open_ice') return 'свободный лёд';
    return 'массовое';
  }

  function arenaHref(payload) {
    var ref = (payload && (payload.arena_slug || payload.arena_id)) || '';
    if (!ref) return '';
    return 'arena?ref=' + encodeURIComponent(String(ref));
  }

  function formatIceTeaser(payload, now) {
    if (!payload || typeof payload !== 'object') return hiddenView();
    var href = arenaHref(payload);
    var time = hhmm(payload.starts_at_local);
    if (!href || !time) return hiddenView();
    now = now instanceof Date ? now : new Date();
    var when = formatWhen(payload, now);
    var parts = [];
    var name = String(payload.arena_name || '').trim();
    if (name) parts.push(name);
    var dist = formatDistanceKm(payload.distance_km);
    if (dist) parts.push(dist);
    parts.push(kindLabel(payload.kind));
    var price = formatPrice(payload.price_adult_minor, payload.currency_code);
    var last = parts.pop();
    var subtitle = parts.length ? parts.join(' · ') + ' · ' + last : last;
    if (price) subtitle += ', ' + price;
    return {
      hidden: false,
      title: 'Лёд рядом — ' + when,
      subtitle: subtitle,
      href: href,
    };
  }

  function renderIceTeaserHtml(view) {
    if (!view || view.hidden) return '';
    return (
      '<a class="hub-ice-teaser" href="' +
      escapeHtml(view.href) +
      '">' +
      '<span class="hub-ice-teaser__ic" aria-hidden="true">⛸️</span>' +
      '<span class="hub-ice-teaser__text">' +
      '<b>' +
      escapeHtml(view.title) +
      '</b>' +
      '<span>' +
      escapeHtml(view.subtitle) +
      '</span>' +
      '</span>' +
      '<span class="hub-ice-teaser__chev" aria-hidden="true">›</span>' +
      '</a>'
    );
  }

  /* ────────────────────────────────────────────────────────────────────
   * TASK-091. Тизер-строка становится карточкой: тот же объект, что на «Льду»
   * (кадр, время-якорь, каток, условия). Строка внизу первого экрана лёд не
   * продавала — её читали как примечание. Старые formatIceTeaser /
   * renderIceTeaserHtml оставлены: на них есть тесты и они ничего не ломают.
   * ──────────────────────────────────────────────────────────────────── */

  function hiddenCard() {
    return { hidden: true };
  }

  function dayLabel(payload, now) {
    var startMs = Date.parse(payload.starts_at_utc || '');
    if (!isNaN(startMs)) {
      var mins = Math.round((startMs - now.getTime()) / 60000);
      if (mins >= 0 && mins < 60) {
        return mins <= 0 ? 'Сейчас' : 'Через ' + mins + ' ' + pluralMinutes(mins);
      }
    }
    var localDate = String(payload.local_date || '').slice(0, 10);
    if (!localDate) return '';
    var today = minskDateIso(now);
    if (localDate === today) return 'Сегодня';
    if (localDate === addDaysIso(today, 1)) return 'Завтра';
    return localDate.slice(8, 10) + '.' + localDate.slice(5, 7);
  }

  function initialOf(name) {
    var clean = String(name || '')
      .replace(/[^\p{L}\p{N}]+/gu, ' ')
      .trim();
    return clean ? clean.charAt(0).toUpperCase() : '?';
  }

  function formatIceCard(payload, now) {
    if (!payload || typeof payload !== 'object') return hiddenCard();
    var href = arenaHref(payload);
    var time = hhmm(payload.starts_at_local);
    if (!href || !time) return hiddenCard();
    now = now instanceof Date ? now : new Date();
    var facts = [kindLabel(payload.kind)];
    var price = formatPrice(payload.price_adult_minor, payload.currency_code);
    if (price) facts.push(price);
    var name = String(payload.arena_name || '').trim();
    return {
      hidden: false,
      href: href,
      photo: payload.card || payload.thumb || '',
      initial: initialOf(name),
      day: dayLabel(payload, now),
      time: time,
      name: name,
      where: String(payload.arena_district || '').trim(),
      facts: facts.join(' · '),
      city: String(payload.city_name || '').trim(),
    };
  }

  function renderIceCardHtml(view) {
    if (!view || view.hidden) return '';
    var photo = view.photo
      ? '<span class="hub-ice-card__photo" style="background-image:url(\'' +
        escapeHtml(view.photo).replace(/'/g, '%27') +
        '\')"></span>'
      : '<span class="hub-ice-card__photo hub-ice-card__photo--empty">' +
        '<span class="hub-ice-card__initial" aria-hidden="true">' +
        escapeHtml(view.initial) +
        '</span></span>';
    return (
      '<a class="hub-ice-card" href="' +
      escapeHtml(view.href) +
      '">' +
      photo +
      '<span class="hub-ice-card__row">' +
      '<span class="hub-ice-card__when">' +
      '<span class="hub-ice-card__time">' +
      escapeHtml(view.time) +
      '</span>' +
      '<span class="hub-ice-card__day">' +
      escapeHtml(view.day) +
      '</span>' +
      '</span>' +
      '<span class="hub-ice-card__what">' +
      '<span class="hub-ice-card__name">' +
      escapeHtml(view.name) +
      '</span>' +
      '<span class="hub-ice-card__facts">' +
      escapeHtml(view.facts) +
      '</span>' +
      '</span>' +
      '<span class="hub-ice-card__chev" aria-hidden="true">→</span>' +
      '</span></a>'
    );
  }

  return {
    formatIceTeaser: formatIceTeaser,
    renderIceTeaserHtml: renderIceTeaserHtml,
    formatIceCard: formatIceCard,
    renderIceCardHtml: renderIceCardHtml,
    arenaHref: arenaHref,
  };
});
