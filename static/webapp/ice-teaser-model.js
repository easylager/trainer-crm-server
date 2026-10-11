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

  var MT =
    typeof module === 'object' && module.exports && typeof require === 'function'
      ? require('./minsk-time.js')
      : typeof globalThis !== 'undefined'
        ? globalThis.MinskTime
        : null;
  var rootRef = typeof globalThis !== 'undefined' ? globalThis : this;

  function staleApi() {
    return rootRef.ScheduleStalenessModel || null;
  }

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
    if (!isNaN(startMs) && startMs <= now.getTime()) return '';
    if (!isNaN(startMs)) {
      var mins = Math.round((startMs - now.getTime()) / 60000);
      if (mins >= 0 && mins < 60) {
        if (mins <= 0) return 'сейчас';
        return 'через ' + mins + ' ' + pluralMinutes(mins);
      }
    }
    var localDate = String(payload.local_date || '').slice(0, 10);
    var time = hhmm(payload.starts_at_local);
    var today = MT.dateIso(now);
    if (localDate === today) return 'сегодня в ' + time;
    if (localDate === MT.addDaysIso(today, 1)) return 'завтра в ' + time;
    if (localDate) return localDate.slice(8, 10) + '.' + localDate.slice(5, 7) + ' в ' + time;
    return time ? 'в ' + time : '';
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
    // id важнее slug: тизер бывает «ближайший по стране», а slug уникален только в городе.
    var ref = (payload && (payload.arena_id != null ? payload.arena_id : payload.arena_slug)) || '';
    if (!ref) return '';
    return 'arena?ref=' + encodeURIComponent(String(ref));
  }

  function slotHasStarted(payload, now) {
    return MT.liveSessionStarted(payload, now);
  }

  /** TASK-184: после старта первого сеанса — следующий из payload.sessions. */
  function resolveTeaserPayload(payload, now) {
    if (!payload || typeof payload !== 'object') return null;
    now = now instanceof Date ? now : new Date();
    var sessions = payload.sessions;
    if (Array.isArray(sessions) && sessions.length) {
      for (var i = 0; i < sessions.length; i++) {
        var slot = sessions[i];
        if (slotHasStarted(slot, now)) continue;
        var merged = {};
        var k;
        for (k in payload) {
          if (Object.prototype.hasOwnProperty.call(payload, k) && k !== 'sessions') merged[k] = payload[k];
        }
        for (k in slot) {
          if (Object.prototype.hasOwnProperty.call(slot, k)) merged[k] = slot[k];
        }
        merged.sessions = sessions;
        return merged;
      }
      return null;
    }
    return slotHasStarted(payload, now) ? null : payload;
  }

  function formatIceTeaser(payload, now) {
    payload = resolveTeaserPayload(payload, now);
    if (!payload) return hiddenView();
    var href = arenaHref(payload);
    var time = hhmm(payload.starts_at_local);
    if (!href || !time) return hiddenView();
    now = now instanceof Date ? now : new Date();
    var when = formatWhen(payload, now);
    var parts = [];
    var name = String(payload.arena_name || '').trim();
    if (name) parts.push(name);
    var dist = MT.formatDistanceKm(payload.distance_km);
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
    var today = MT.dateIso(now);
    if (localDate === today) return 'Сегодня';
    if (localDate === MT.addDaysIso(today, 1)) return 'Завтра';
    return localDate.slice(8, 10) + '.' + localDate.slice(5, 7);
  }

  function initialOf(name) {
    var clean = String(name || '')
      .replace(/[^\p{L}\p{N}]+/gu, ' ')
      .trim();
    return clean ? clean.charAt(0).toUpperCase() : '?';
  }

  /**
   * Same "is this actually near you" bar as CatalogGeoModel.MAX_MATCH_DISTANCE_KM
   * (static/webapp/catalog-geo-model.js) — kept as a separate constant (not a shared
   * import) since this file has no build step and stays a plain <script>, but the two
   * should move together if the threshold ever changes.
   */
  var FAR_DISTANCE_THRESHOLD_KM = 150;

  function formatFarCard(payload) {
    var name = String(payload.arena_name || '').trim();
    var city = String(payload.city_name || '').trim();
    return {
      hidden: false,
      isFar: true,
      href: 'ice',
      kicker: 'Скоро и у вас',
      title: 'Пока нет тренеров в вашем городе',
      cityLine: city ? 'Ближе всего — «' + name + '», ' + city : 'Ближе всего — «' + name + '»',
      cta: 'Смотреть каталог',
    };
  }

  function formatIceCard(payload, now) {
    payload = resolveTeaserPayload(payload, now);
    if (!payload) return hiddenCard();
    var href = arenaHref(payload);
    var time = hhmm(payload.starts_at_local);
    if (!href || !time) return hiddenCard();
    now = now instanceof Date ? now : new Date();
    var dist = payload.distance_km;
    var distanceSaysFar = dist != null && !isNaN(Number(dist)) && Number(dist) > FAR_DISTANCE_THRESHOLD_KM;
    // far_confirmed: IP-country (src/shared/ip_geo.py) already placed this visitor outside
    // every served market, with no GPS distance computed at all — treat it identically.
    if (distanceSaysFar || payload.far_confirmed) {
      return formatFarCard(payload);
    }
    var facts = [kindLabel(payload.kind)];
    var price = formatPrice(payload.price_adult_minor, payload.currency_code);
    if (price) facts.push(price);
    var S = staleApi();
    if (S && S.STALE_SHORT && S.scheduleStaleFlag(payload)) facts.push(S.STALE_SHORT);
    var name = String(payload.arena_name || '').trim();
    var city = String(payload.city_name || '').trim();
    return {
      hidden: false,
      isFar: false,
      href: href,
      kicker: city ? 'На льду · ' + city : 'На льду',
      photo: payload.card || payload.thumb || '',
      initial: initialOf(name),
      day: dayLabel(payload, now),
      time: time,
      name: name,
      where: String(payload.arena_district || '').trim(),
      facts: facts.join(' · '),
      city: city,
    };
  }

  function renderFarCardHtml(view) {
    return (
      '<a class="hub-ice-card hub-ice-card--far" href="' +
      escapeHtml(view.href) +
      '">' +
      '<span class="hub-ice-card__photo hub-ice-card__photo--empty">' +
      '<span class="hub-ice-card__initial" aria-hidden="true">📍</span>' +
      '</span>' +
      '<span class="hub-ice-card__row">' +
      '<span class="hub-ice-card__what">' +
      '<span class="hub-ice-card__name">' +
      escapeHtml(view.title) +
      '</span>' +
      '<span class="hub-ice-card__facts">' +
      escapeHtml(view.cityLine) +
      '</span>' +
      '<span class="hub-ice-card__cta">' +
      escapeHtml(view.cta) +
      '</span>' +
      '</span>' +
      '<span class="hub-ice-card__chev" aria-hidden="true">→</span>' +
      '</a>'
    );
  }

  function renderIceCardHtml(view) {
    if (!view || view.hidden) return '';
    if (view.isFar) return renderFarCardHtml(view);
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
    resolveTeaserPayload: resolveTeaserPayload,
    arenaHref: arenaHref,
    FAR_DISTANCE_THRESHOLD_KM: FAR_DISTANCE_THRESHOLD_KM,
  };
});
