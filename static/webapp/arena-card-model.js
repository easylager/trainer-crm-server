/**
 * TASK-052 arena card — pure view-model (no DOM).
 * Browser: window.ArenaCardModel. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ArenaCardModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var AMENITY_ORDER = [
    ['skate_rental', 'Прокат'],
    ['skate_sharpening', 'Заточка'],
    ['parking', 'Парковка'],
    ['locker_rooms', 'Раздевалки'],
    ['cafe', 'Кафе'],
    ['accessibility', 'Доступность'],
  ];

  var MONTHS_PREP = [
    '',
    'января',
    'февраля',
    'марта',
    'апреля',
    'мая',
    'июня',
    'июля',
    'августа',
    'сентября',
    'октября',
    'ноября',
    'декабря',
  ];

  var WEEKDAYS_SHORT = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

  function parseLocalDate(iso) {
    if (!iso) return null;
    var p = String(iso).slice(0, 10).split('-');
    if (p.length < 3) return null;
    return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
  }

  function ymd(d) {
    var m = d.getMonth() + 1;
    var day = d.getDate();
    return (
      d.getFullYear() +
      '-' +
      (m < 10 ? '0' : '') +
      m +
      '-' +
      (day < 10 ? '0' : '') +
      day
    );
  }

  var ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  var SOCIAL_KEYS = [
    ['instagram', 'Instagram'],
    ['facebook', 'Facebook'],
    ['vk', 'VK'],
    ['telegram', 'Telegram'],
  ];

  function isoDate(value) {
    var s = String(value || '').slice(0, 10);
    return ISO_DATE_RE.test(s) ? s : null;
  }

  function addDaysYmd(iso, n) {
    var d = parseLocalDate(iso);
    if (!d) return null;
    d.setDate(d.getDate() + n);
    return ymd(d);
  }

  function dayTabFromIso(iso, todayIso) {
    var date = isoDate(iso);
    var today = isoDate(todayIso);
    if (!date || !today) return 'today';
    if (date === today) return 'today';
    if (date === addDaysYmd(today, 1)) return 'tomorrow';
    return date;
  }

  function ribbonIsoForDay(day, todayIso) {
    if (day === 'week') return null;
    var today = isoDate(todayIso);
    if (day === 'tomorrow') return today ? addDaysYmd(today, 1) : null;
    if (day === 'today' || !day) return today;
    return isoDate(day) || today;
  }

  function practiceContacts(card) {
    card = card || {};
    var website = String(card.website_url || '').trim();
    var desc = String(card.short_description || '').trim();
    var socials = [];
    var urls = card.social_urls && typeof card.social_urls === 'object' ? card.social_urls : {};
    var i;
    for (i = 0; i < SOCIAL_KEYS.length; i++) {
      var key = SOCIAL_KEYS[i][0];
      var href = String(urls[key] || '').trim();
      if (href) socials.push({ key: key, label: SOCIAL_KEYS[i][1], href: href });
    }
    return {
      shortDescription: desc || null,
      website: website ? { href: website, label: 'Сайт катка' } : null,
      socials: socials,
    };
  }

  function formatMinor(minor, currency) {
    if (minor == null || minor === '') return null;
    var n = Number(minor);
    if (isNaN(n)) return null;
    var major = n / 100;
    var text = Number.isInteger(major) ? String(major) : major.toFixed(2).replace(/\.00$/, '');
    if (currency) return { amount: text, withCurrency: text + ' ' + currency };
    return { amount: text, withCurrency: text };
  }

  function formatSessionPrices(session) {
    session = session || {};
    var currency = session.currency_code || 'BYN';
    var adult = formatMinor(session.price_adult_minor, currency);
    var child = formatMinor(session.price_child_minor, currency);
    var rental = formatMinor(session.price_rental_minor, currency);
    var parts = [];
    if (adult && child) {
      parts.push('взр. ' + adult.amount);
      parts.push('дет. ' + child.amount);
    } else if (adult) {
      parts.push(adult.withCurrency);
    } else if (child) {
      parts.push('дет. ' + child.withCurrency);
    }
    if (rental) {
      parts.push('прокат +' + rental.amount);
    } else if (parts.length) {
      parts.push('без проката');
    }
    return parts.join(' · ');
  }

  function daysBetween(fromIso, now) {
    var from = new Date(fromIso);
    if (isNaN(from.getTime()) || !now) return null;
    var a = Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), from.getUTCDate());
    var b = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    return Math.round((b - a) / 86400000);
  }

  function pluralDays(n) {
    var abs = Math.abs(n);
    var mod10 = abs % 10;
    var mod100 = abs % 100;
    if (mod10 === 1 && mod100 !== 11) return abs + ' день';
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return abs + ' дня';
    return abs + ' дней';
  }

  function formatFreshness(freshness, now) {
    freshness = freshness || {};
    if (!freshness.schedule_observed_at) return null;
    var days = daysBetween(freshness.schedule_observed_at, now || new Date());
    if (days == null || days < 0) return null;
    var when;
    if (days === 0) when = 'сегодня';
    else when = pluralDays(days) + ' назад';
    var text = 'Расписание обновлено ' + when;
    if (freshness.source_label) {
      text += ' · по данным ' + freshness.source_label;
    }
    return text;
  }

  function sessionNowState(session, now) {
    if (!session) return 'upcoming';
    var start = session.starts_at_utc ? new Date(session.starts_at_utc) : null;
    var end = session.ends_at_utc ? new Date(session.ends_at_utc) : null;
    var t = now ? now.getTime() : Date.now();
    if (start && end && !isNaN(start.getTime()) && !isNaN(end.getTime())) {
      if (t >= start.getTime() && t < end.getTime()) return 'live';
      if (t >= end.getTime()) return 'past';
    }
    return 'upcoming';
  }

  function iceKindLabel(session) {
    session = session || {};
    if (session.session_label) return session.session_label;
    if (session.kind === 'open_ice') return 'Свободный лёд';
    return 'Массовое катание';
  }

  function iceRowCta(session) {
    var href = String((session && session.external_url) || '').trim() || null;
    return {
      cta: 'Билет на месте',
      ctaKind: 'ghost',
      href: href,
      bookable: false,
    };
  }

  function hhmm(value) {
    if (!value) return '';
    return String(value).slice(0, 5);
  }

  function buildRibbonForDay(opts) {
    opts = opts || {};
    var rows = [];
    var now = opts.now || new Date();
    var sessions = opts.sessions || [];
    var i;
    for (i = 0; i < sessions.length; i++) {
      var s = sessions[i];
      var nowState = sessionNowState(s, now);
      var meta = formatSessionPrices(s);
      if (nowState !== 'upcoming') continue;
      var cta = iceRowCta(s);
      rows.push({
        nature: 'ice',
        stripe: 'ice',
        time: hhmm(s.starts_at_local),
        title: iceKindLabel(s),
        meta: meta,
        cta: cta.cta,
        ctaKind: cta.ctaKind,
        href: cta.href,
        bookable: false,
        nowState: nowState,
        session: s,
      });
    }
    var groups = opts.groups || [];
    var weekday = opts.weekday;
    for (i = 0; i < groups.length; i++) {
      var g = groups[i];
      var rules = g.schedule_rules || [];
      var r;
      for (r = 0; r < rules.length; r++) {
        if (Number(rules[r].day_of_week) !== Number(weekday)) continue;
        var spots = g.spots_left != null ? Number(g.spots_left) : null;
        var metaG = spots != null && spots > 0 ? 'идёт набор · ' + spots + ' места' : 'идёт набор';
        var age = g.catalog_pitch || '';
        rows.push({
          nature: 'lesson',
          stripe: 'lesson',
          time: hhmm(rules[r].start_time),
          title: g.name || 'Группа',
          meta: age ? age + ' · ' + metaG : metaG,
          cta: 'Заявка',
          ctaKind: 'solid',
          bookable: true,
          nowState: 'upcoming',
          group: g,
          trainerId: g.trainer_id,
        });
      }
    }
    rows.sort(function (a, b) {
      if (a.time === b.time) return 0;
      return a.time < b.time ? -1 : 1;
    });
    return rows;
  }

  function countLessonsOnDate(groups, dateObj) {
    var weekday = dateObj.getDay();
    var n = 0;
    var gi;
    for (gi = 0; gi < (groups || []).length; gi++) {
      var rules = groups[gi].schedule_rules || [];
      var ri;
      for (ri = 0; ri < rules.length; ri++) {
        if (Number(rules[ri].day_of_week) === weekday) n += 1;
      }
    }
    return n;
  }

  function sessionTimeRange(sessions) {
    var times = [];
    var i;
    for (i = 0; i < (sessions || []).length; i++) {
      var t = hhmm(sessions[i].starts_at_local);
      if (t) times.push(t);
    }
    times.sort();
    if (!times.length) return '';
    return 'с ' + times[0] + (times.length > 1 ? ' до ' + times[times.length - 1] : '');
  }

  function buildWeekSummaries(opts) {
    opts = opts || {};
    var start = parseLocalDate(opts.from);
    var end = parseLocalDate(opts.to);
    if (!start || !end) return [];
    var byDate = {};
    var sessionDays = opts.sessionDays || [];
    var i;
    for (i = 0; i < sessionDays.length; i++) {
      byDate[sessionDays[i].local_date] = sessionDays[i].sessions || [];
    }
    var groups = opts.groups || [];
    var out = [];
    var cursor = new Date(start.getTime());
    while (cursor.getTime() <= end.getTime()) {
      var key = ymd(cursor);
      var sessions = byDate[key] || [];
      var lessonN = countLessonsOnDate(groups, cursor);
      var iceN = sessions.length;
      if (!iceN && !lessonN) {
        out.push({
          localDate: key,
          weekday: WEEKDAYS_SHORT[cursor.getDay()],
          empty: true,
          title: 'Данных нет',
          meta: 'расписание на неделю уточняется',
          cta: '—',
        });
      } else {
        var iceWord = iceN === 1 ? 'сеанс' : iceN >= 2 && iceN <= 4 ? 'сеанса' : 'сеансов';
        var lesWord = lessonN === 1 ? 'занятие' : lessonN >= 2 && lessonN <= 4 ? 'занятия' : 'занятий';
        var titleParts = [];
        if (iceN) titleParts.push(iceN + ' ' + iceWord);
        if (lessonN) titleParts.push(lessonN + ' ' + lesWord);
        out.push({
          localDate: key,
          weekday: WEEKDAYS_SHORT[cursor.getDay()],
          empty: false,
          title: titleParts.join(' · ') || 'Есть лёд',
          meta: sessionTimeRange(sessions),
          cta: 'Открыть',
        });
      }
      cursor.setDate(cursor.getDate() + 1);
    }
    return out;
  }

  function heroPhotoUrl(card) {
    card = card || {};
    var hero = card.hero;
    if (!hero || !hero.variants) return null;
    var v = hero.variants;
    return v.hero || v.card || v.thumb || null;
  }

  function heroView(card) {
    var url = heroPhotoUrl(card);
    return { mode: url ? 'photo' : 'placeholder', url: url };
  }

  function ribbonLegend() {
    return [
      {
        nature: 'ice',
        stripe: 'ice',
        text: 'открытый лёд — только информация',
      },
      {
        nature: 'lesson',
        stripe: 'lesson',
        text: 'занятие — можно записаться',
      },
    ];
  }

  function trainerCta(trainer) {
    if (trainer && trainer.can_book) {
      return { label: 'Записаться', kind: 'solid' };
    }
    return { label: 'Написать', kind: 'ghost' };
  }

  function buildBookingHref(opts) {
    opts = opts || {};
    var parts = ['from=arena'];
    if (opts.trainerId != null) parts.push('trainer_id=' + encodeURIComponent(String(opts.trainerId)));
    if (opts.arenaId != null) parts.push('arena_id=' + encodeURIComponent(String(opts.arenaId)));
    // Группу нужно донести до карточки тренера: на арене человек тапает конкретный
    // набор («Группа · 3 места»), и без id он попадал на общий список времени —
    // группа, которую он выбрал, просто терялась по дороге.
    if (opts.groupId != null) parts.push('group_id=' + encodeURIComponent(String(opts.groupId)));
    if (opts.action) parts.push('action=' + encodeURIComponent(String(opts.action)));
    return 'catalog?' + parts.join('&');
  }

  function parseArenaRef(search, startParam) {
    var qp = new URLSearchParams(search || '');
    var ref = qp.get('ref') || qp.get('arena') || qp.get('arena_id') || qp.get('id') || qp.get('slug');
    if (ref) return String(ref).trim();
    var sp = startParam != null ? String(startParam).trim() : '';
    if (!sp) return null;
    var m = /^arena[_-](.+)$/i.exec(sp);
    if (m) return m[1];
    return sp || null;
  }

  function iceSectionMode(opts) {
    opts = opts || {};
    if (opts.hasSessions) return 'ribbon';
    var tier = String(opts.tier || '').toUpperCase();
    if (tier === 'C') return 'none';
    return 'pending';
  }

  function iceFeedView(opts) {
    opts = opts || {};
    var card = opts.card || {};
    var banner = seasonClosedBanner(card);
    if (banner) {
      return { mode: 'closed', banner: banner, showRibbon: false };
    }
    var mode = iceSectionMode({
      tier: opts.tier || card.tier,
      hasSessions: opts.hasSessions,
    });
    return { mode: mode, banner: null, showRibbon: mode === 'ribbon' };
  }

  function seasonClosedBanner(card) {
    card = card || {};
    if (card.in_season !== false) return null;
    var start = Number(card.season_start_month);
    var monthName = MONTHS_PREP[start] || '';
    if (monthName) return 'Закрыт до ' + monthName;
    return 'Закрыт на сезон';
  }

  function amenityChips(amenities) {
    amenities = amenities || {};
    var chips = [];
    var i;
    for (i = 0; i < AMENITY_ORDER.length; i++) {
      var key = AMENITY_ORDER[i][0];
      if (amenities[key] === true) chips.push(AMENITY_ORDER[i][1]);
    }
    return chips;
  }

  function formatOpeningHours(hours) {
    hours = hours || {};
    var daily = hours.daily;
    if (daily && (daily.open || daily.close)) {
      return 'Пн–Вс ' + (daily.open || '') + '–' + (daily.close || '');
    }
    return '';
  }

  function openUntilLabel(hours) {
    hours = hours || {};
    var daily = hours.daily;
    if (daily && daily.close) return 'открыт до ' + daily.close;
    return '';
  }

  function heroMetaLine(card) {
    card = card || {};
    var bits = [];
    if (card.district) bits.push(card.district);
    if (card.distance_km != null && card.distance_km !== '') {
      var km = Number(card.distance_km);
      if (!isNaN(km)) bits.push(km.toFixed(1).replace('.', ',') + ' км');
    }
    var until = openUntilLabel(card.opening_hours);
    if (until) bits.push(until);
    return bits.join(' · ');
  }

  function trainerSubtitle(trainer) {
    trainer = trainer || {};
    var services = trainer.services || [];
    var names = [];
    var minPrice = null;
    var i;
    for (i = 0; i < services.length; i++) {
      var s = services[i];
      if (s.name) names.push(s.name);
      var p = s.price_cents != null ? Number(s.price_cents) : s.price_byn != null ? Number(s.price_byn) * 100 : NaN;
      if (!isNaN(p) && p > 0 && (minPrice == null || p < minPrice)) minPrice = p;
    }
    var bits = [];
    if (names.length) bits.push(names[0]);
    if (minPrice != null) {
      var fmt = formatMinor(minPrice, 'BYN');
      if (fmt) bits.push('от ' + fmt.amount + ' BYN');
    }
    return bits.join(' · ');
  }

  function startParamFromLocation(loc) {
    loc = loc || (typeof window !== 'undefined' ? window.location : null);
    if (!loc) return null;
    try {
      var hash = String(loc.hash || '');
      var m = /(?:^|[&#])tgWebAppStartParam=([^&]+)/.exec(hash);
      if (m) return decodeURIComponent(m[1]);
    } catch (e) { /* ignore */ }
    return null;
  }

  return {
    AMENITY_ORDER: AMENITY_ORDER,
    formatSessionPrices: formatSessionPrices,
    formatFreshness: formatFreshness,
    sessionNowState: sessionNowState,
    iceKindLabel: iceKindLabel,
    iceRowCta: iceRowCta,
    buildRibbonForDay: buildRibbonForDay,
    buildWeekSummaries: buildWeekSummaries,
    heroPhotoUrl: heroPhotoUrl,
    heroView: heroView,
    ribbonLegend: ribbonLegend,
    trainerCta: trainerCta,
    buildBookingHref: buildBookingHref,
    parseArenaRef: parseArenaRef,
    iceSectionMode: iceSectionMode,
    iceFeedView: iceFeedView,
    seasonClosedBanner: seasonClosedBanner,
    amenityChips: amenityChips,
    formatOpeningHours: formatOpeningHours,
    heroMetaLine: heroMetaLine,
    trainerSubtitle: trainerSubtitle,
    parseLocalDate: parseLocalDate,
    ymd: ymd,
    dayTabFromIso: dayTabFromIso,
    ribbonIsoForDay: ribbonIsoForDay,
    practiceContacts: practiceContacts,
    startParamFromLocation: startParamFromLocation,
    WEEKDAYS_SHORT: WEEKDAYS_SHORT,
  };
});
