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

  var rootRef = typeof globalThis !== 'undefined' ? globalThis : this;
  function scheduleModeApi() {
    return rootRef.ArenaScheduleModeModel || null;
  }
  function glideCopy() {
    if (typeof module === 'object' && module.exports && typeof require === 'function') {
      return require('./glide-copy.js');
    }
    return rootRef.GlideCopy || null;
  }
  function copyLine(key, fallback) {
    var GC = glideCopy();
    if (GC && typeof GC.t === 'function') {
      var label = GC.t(key);
      if (label && label !== key) return String(label);
    }
    return fallback;
  }
  function safeHttpUrl(value) {
    var url = String(value || '').trim();
    var low = url.toLowerCase();
    if (low.indexOf('https://') !== 0 && low.indexOf('http://') !== 0) return '';
    return url;
  }
  function callHrefFor(card) {
    var SM = scheduleModeApi();
    var raw = card && card.phone;
    if (SM && typeof SM.phoneToTelHref === 'function') return SM.phoneToTelHref(raw) || '';
    var digits = String(raw || '').replace(/\D/g, '');
    return digits.length >= 7 ? 'tel:' + String(raw || '').replace(/[^\d+]/g, '') : '';
  }
  /** Нет сеансов: телефон (часы — в блоке info), иначе сайт, иначе секции нет. */
  function scheduleAsk(card) {
    var callHref = callHrefFor(card);
    if (callHref) {
      return {
        mode: 'phone',
        banner: null,
        showRibbon: false,
        callHref: callHref,
      };
    }
    var siteHref = safeHttpUrl(card && card.website_url);
    if (siteHref) {
      return {
        mode: 'site',
        banner: copyLine('place.site_schedule', 'Время массового катания — на сайте катка'),
        showRibbon: false,
        siteHref: siteHref,
      };
    }
    return { mode: 'none', banner: null, showRibbon: false };
  }

  var RuText = typeof globalThis !== 'undefined' ? globalThis.RuText : null;
  /* TASK-182: часы работы — общий модуль со вкладкой «Лёд» (opening-hours.js). */
  var OH =
    typeof module === 'object' && module.exports && typeof require === 'function'
      ? require('./opening-hours.js')
      : typeof globalThis !== 'undefined'
        ? globalThis.OpeningHours
        : null;
  var MT =
    typeof module === 'object' && module.exports && typeof require === 'function'
      ? require('./minsk-time.js')
      : typeof globalThis !== 'undefined'
        ? globalThis.MinskTime
        : null;
  var PD =
    typeof module === 'object' && module.exports && typeof require === 'function'
      ? require('./public-display-model.js')
      : typeof globalThis !== 'undefined'
        ? globalThis.PublicDisplayModel
        : null;
  var ruText = RuText;

  var AMENITY_ORDER = [
    ['skate_rental', 'Прокат'],
    ['skate_sharpening', 'Заточка'],
    ['parking', 'Парковка'],
    ['locker_rooms', 'Раздевалки'],
    ['cafe', 'Кафе'],
    ['accessibility', 'Доступность'],
    /* TASK-146: услуги магазина (ключи — src/application/arena_profile.py). */
    ['retail', 'Розница'],
    ['skate_molding', 'Формовка'],
    ['blade_profiling', 'Профилирование'],
    ['foot_scan', '3D-скан стопы'],
    ['repair', 'Ремонт'],
  ];

  /* TASK-146: услуги магазина — плитками с подписью, специализация — тегами. */
  var SHOP_SERVICES = [
    ['retail', 'Розница', 'Коньки, защита, форма'],
    ['skate_sharpening', 'Заточка', 'Лезвия под ваш стиль катания'],
    ['skate_molding', 'Формовка', 'Ботинок по форме стопы'],
    ['blade_profiling', 'Профилирование', 'Профиль лезвия под игрока'],
    ['foot_scan', '3D-скан стопы', 'Точный подбор размера'],
    ['skate_rental', 'Прокат', 'Коньки на время'],
    ['repair', 'Ремонт', 'Коньки, клюшки, форма'],
  ];
  var SHOP_DISCIPLINES = [
    ['discipline_hockey', 'Хоккей'],
    ['discipline_figure', 'Фигурное'],
    ['discipline_roller', 'Ролики'],
  ];

  function shopServicesView(amenities) {
    amenities = amenities || {};
    var tiles = SHOP_SERVICES.filter(function (s) { return amenities[s[0]] === true; }).map(function (s) {
      return { key: s[0], title: s[1], sub: s[2] };
    });
    var disciplines = SHOP_DISCIPLINES.filter(function (d) { return amenities[d[0]] === true; }).map(function (d) {
      return d[1];
    });
    return { tiles: tiles, disciplines: disciplines };
  }

  var MONTHS_IN = [
    '',
    'январе',
    'феврале',
    'марте',
    'апреле',
    'мае',
    'июне',
    'июле',
    'августе',
    'сентябре',
    'октябре',
    'ноябре',
    'декабре',
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
    return MT.dateIso(d instanceof Date ? d : new Date());
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
    if (!isoDate(iso)) return null;
    return MT.addDaysIso(iso, n);
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
      /* Подпись склоняет сервер по venue_type: «Сайт зала» для зала.
         Фолбэк — для ответов старого API без поля. */
      website: website
        ? { href: website, label: String(card.venue_site_label || '').trim() || 'Сайт площадки' }
        : null,
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

  var MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
    'сентября', 'октября', 'ноября', 'декабря'];

  function sessionStartMs(session) {
    if (!session) return 0;
    if (session.starts_at_utc) {
      var utc = new Date(session.starts_at_utc).getTime();
      if (!isNaN(utc)) return utc;
    }
    var iso = String(session.local_date || '').slice(0, 10);
    var hm = hhmm(session.starts_at_local);
    if (iso && hm) {
      var ms = Date.parse(iso + 'T' + hm + ':00+03:00');
      if (!isNaN(ms)) return ms;
    }
    return 0;
  }

  function compareSessionsByStart(a, b) {
    return sessionStartMs(a) - sessionStartMs(b);
  }

  /** Календарный «сегодня» в часовом поясе арены (не устройства). */
  function ymdInTimeZone(date, timeZone) {
    return MT.dateIso(date, timeZone);
  }

  function sessionNowState(session, now) {
    if (!session) return 'upcoming';
    var start = session.starts_at_utc ? new Date(session.starts_at_utc) : null;
    var end = session.ends_at_utc ? new Date(session.ends_at_utc) : null;
    var t = now ? now.getTime() : Date.now();
    if (start && !isNaN(start.getTime())) {
      if (t < start.getTime()) return 'upcoming';
      if (end && !isNaN(end.getTime()) && t < end.getTime()) return 'live';
      return 'past';
    }
    return 'upcoming';
  }

  function iceKindLabel(session) {
    session = session || {};
    var own = String(session.session_label || '').trim();
    // «Трен.» / «Главная» — зал из колонки «Арена» на ledlife.by, а не название сеанса.
    if (own && !/^(трен\.?|главная|тренировочная|главная арена)$/i.test(own)) return own;
    var GCk = rootRef.GlideCopy;
    if ((session.kind === 'figure_free' || session.kind === 'family_skate') && GCk && typeof GCk.t === 'function') {
      var kl = GCk.t('kind.' + session.kind);
      if (kl && kl !== 'kind.' + session.kind) return String(kl);
    }
    if (session.kind === 'figure_free') return 'Свободное фигурное катание';
    if (session.kind === 'family_skate') return 'Семейное массовое катание';
    if (session.kind === 'hockey_practice') {
      var GC = rootRef.GlideCopy;
      if (GC && typeof GC.t === 'function') {
        var label = GC.t('kind.hockey_practice');
        if (label && label !== 'kind.hockey_practice') return String(label);
      }
      return 'ОХМ';
    }
    if (session.kind === 'open_ice') return 'Свободный лёд';
    return 'Массовое катание';
  }

  /** Зал сеанса полным названием; старые строки держат его в session_label («Трен.», «Главная»). */
  function sessionHall(session) {
    session = session || {};
    var hall = String(session.hall || '').trim();
    if (hall) return hall;
    var legacy = String(session.session_label || '').trim().replace(/\.$/, '').toLowerCase();
    if (legacy === 'трен' || legacy === 'тренировочная') return 'Тренировочная арена';
    if (legacy === 'главная' || legacy === 'главная арена') return 'Главная арена';
    return '';
  }

  function scheduleBasisHint(/* session */) {
    // Клиенту не важно, откуда слот (сайт / сетка / фото / вручную).
    return '';
  }

  /**
   * Кнопка строки сеанса. Раньше на каждом сеансе стояло «Билет на месте» — даже у Замка,
   * где билеты продаются онлайн с остатком мест: приложение врало. Теперь только факт:
   * ссылка на сеанс (касса или страница события) или общая касса места — «Билеты»;
   * нет ни того ни другого — кнопки нет, строка говорит временем и ценой.
   */
  function iceRowCta(session, ticketsUrl) {
    var href = safeHttpUrl(session && session.external_url) || safeHttpUrl(ticketsUrl);
    if (!href) return { cta: '', ctaKind: '', href: null, bookable: false };
    // Не 'solid': заливка у нас — своя запись («Заявка»), а это уход во внешнюю кассу.
    return { cta: 'Билеты', ctaKind: 'link', href: href, bookable: false };
  }

  function safeHttpUrl(value) {
    var href = String(value || '').trim();
    var lower = href.toLowerCase();
    if (lower.indexOf('https://') !== 0 && lower.indexOf('http://') !== 0) return null;
    if (/\s/.test(href)) return null;
    return href;
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
      var basisNote = scheduleBasisHint(s);
      if (basisNote) meta = basisNote + (meta ? ' · ' + meta : '');
      if (nowState !== 'upcoming') continue;
      var cta = iceRowCta(s, opts.ticketsUrl);
      rows.push({
        nature: 'ice',
        stripe: 'ice',
        time: hhmm(s.starts_at_local),
        title: iceKindLabel(s),
        meta: meta,
        scheduleBasis: String(s.schedule_basis || 'live'),
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

  function countLessonsOnDate(groups, isoYmd) {
    var weekday = MT.weekdaySun0FromIso(isoYmd);
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
    var fromIso = isoDate(opts.from);
    var toIso = isoDate(opts.to);
    if (!fromIso || !toIso) return [];
    var byDate = {};
    var sessionDays = opts.sessionDays || [];
    var i;
    for (i = 0; i < sessionDays.length; i++) {
      byDate[sessionDays[i].local_date] = sessionDays[i].sessions || [];
    }
    var groups = opts.groups || [];
    var out = [];
    var cursor = fromIso;
    while (cursor <= toIso) {
      var key = cursor;
      var sessions = byDate[key] || [];
      var lessonN = countLessonsOnDate(groups, key);
      var iceN = sessions.length;
      var wd = MT.weekdaySun0FromIso(key);
      if (!iceN && !lessonN) {
        out.push({
          localDate: key,
          weekday: WEEKDAYS_SHORT[wd],
          empty: true,
          title: copyLine('place.day_empty', 'Сеансов нет'),
          meta: '',
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
          weekday: WEEKDAYS_SHORT[wd],
          empty: false,
          title: titleParts.join(' · ') || 'Есть лёд',
          meta: sessionTimeRange(sessions),
          cta: 'Открыть',
        });
      }
      cursor = MT.addDaysIso(cursor, 1);
    }
    return out;
  }

  function isPublicPhotoUrl(url) {
    var u = String(url || '').trim();
    if (!u) return false;
    var low = u.toLowerCase();
    if (low.indexOf('javascript:') === 0 || low.indexOf('data:') === 0) return false;
    return low.charAt(0) === '/' || low.indexOf('https://') === 0 || low.indexOf('http://') === 0;
  }

  function heroPhotoUrls(card, preferUrl) {
    /* Карточка списка уже показала card/thumb — тот кадр в кэше. hero (1600px)
       часто 404, и шапка остаётся пустой при живой мини-карточке. */
    card = card || {};
    var hero = card.hero;
    var v = hero && hero.variants ? hero.variants : {};
    var out = [];
    var seen = {};
    [v.card, v.thumb, v.hero].forEach(function (raw) {
      if (!isPublicPhotoUrl(raw) || seen[raw]) return;
      seen[raw] = true;
      out.push(raw);
    });
    if (isPublicPhotoUrl(preferUrl)) {
      out = [preferUrl].concat(out.filter(function (u) { return u !== preferUrl; }));
    }
    return out;
  }

  function heroPhotoUrl(card, preferUrl) {
    var urls = heroPhotoUrls(card, preferUrl);
    return urls.length ? urls[0] : null;
  }

  function heroView(card, preferUrl) {
    var urls = heroPhotoUrls(card, preferUrl);
    return {
      mode: urls.length ? 'photo' : 'placeholder',
      url: urls.length ? urls[0] : null,
      urls: urls,
    };
  }

  function heroPrefetchRecord(item) {
    if (!item) return null;
    var url = item.card || item.thumb || '';
    if (!isPublicPhotoUrl(url)) return null;
    return {
      id: item.id != null ? item.id : null,
      slug: item.slug || item.arena_slug || '',
      url: url,
    };
  }

  function heroPrefetchMatches(record, ref) {
    if (!record || !isPublicPhotoUrl(record.url) || ref == null || ref === '') return false;
    var r = String(ref);
    if (record.id != null && String(record.id) === r) return true;
    if (record.slug && String(record.slug) === r) return true;
    return false;
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

  function ticketCta(card) {
    var href = safeHttpUrl(card && card.tickets_url);
    if (!href) return null;
    return { href: href, label: 'Купить билет' };
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

  /** «?day=2026-10-03&s=123» из ленты: день и сеанс, на которых открыть расписание. */
  function parseScheduleFocus(search) {
    var qp = new URLSearchParams(search || '');
    var day = isoDate(qp.get('day'));
    var sid = String(qp.get('s') || '').trim();
    return { day: day, sessionId: /^\d+$/.test(sid) ? sid : null };
  }

  function parseArenaRef(search, startParam) {
    var qp = new URLSearchParams(search || '');
    var ref = qp.get('ref') || qp.get('arena') || qp.get('arena_id') || qp.get('id') || qp.get('slug');
    if (ref) return String(ref).trim();
    var sp = startParam != null ? String(startParam).trim() : '';
    if (!sp) return null;
    var withSession = /^arena[_-]([1-9][0-9]*)(?:_s_([1-9][0-9]*))?$/i.exec(sp);
    if (withSession) return withSession[1];
    var m = /^arena[_-](.+)$/i.exec(sp);
    if (m) return m[1];
    return sp || null;
  }

  /** ``arena_42_s_7`` → ``"7"``. Сеанс в диплинке, когда в query его ещё нет. */
  function sessionIdFromStartParam(startParam) {
    var m = /^arena[_-][1-9][0-9]*_s_([1-9][0-9]*)$/i.exec(String(startParam || '').trim());
    return m ? m[1] : null;
  }

  /** Окно ленты сеансов на карточке: сегодня … сегодня+13 (как reloadSessions). */
  var ARENA_SESSION_WINDOW_DAYS = 14;

  /** День сеанса в ленте карточки, если ссылка принесла только id. */
  function dayForSession(days, sessionId) {
    var want = String(sessionId || '');
    if (!want) return null;
    var list = days || [];
    var i;
    var j;
    for (i = 0; i < list.length; i++) {
      var sessions = list[i].sessions || [];
      for (j = 0; j < sessions.length; j++) {
        var id = sessions[j] && sessions[j].id;
        if (id != null && String(id) === want) return String(list[i].local_date || '') || null;
      }
    }
    return null;
  }

  /** Первый ещё не начавшийся сеанс в ленте — для «Ближайший: …» при пропавшем фокусе. */
  function nearestScheduleSlot(days, todayIso, now) {
    days = days || [];
    now = now || new Date();
    var tomorrow = isoDate(todayIso) ? MT.addDaysIso(todayIso, 1) : '';
    var i;
    for (i = 0; i < days.length; i++) {
      var iso = String(days[i].local_date || '').slice(0, 10);
      var upcoming = upcomingSessions(days[i].sessions || [], now).sort(compareSessionsByStart);
      if (!upcoming.length) continue;
      var s = upcoming[0];
      if (s.id == null) continue;
      var time = hhmm(s.starts_at_local);
      if (!time) continue;
      var head =
        iso === todayIso
          ? 'Сегодня'
          : iso === tomorrow
            ? 'Завтра'
            : WEEKDAYS_SHORT[MT.weekdaySun0FromIso(iso)];
      return {
        id: s.id,
        localDate: iso,
        time: time,
        label: head + ' ' + time,
      };
    }
    return null;
  }

  /**
   * TASK-223: сеанс из шаринга в загруженной ленте — найден или пропал.
   * «gone» только при успешной загрузке и отсутствии id. Свежесть расписания не влияет (TASK-243).
   */
  function focusState(opts) {
    opts = opts || {};
    var want = opts.focusSessionId != null ? String(opts.focusSessionId).trim() : '';
    if (!want) return { kind: 'none' };
    if (opts.sessionsError) {
      return { kind: 'none', focusSessionId: want };
    }
    if (!opts.sessionsLoaded) {
      return { kind: 'none', focusSessionId: want };
    }
    var days = opts.days || [];
    var day = dayForSession(days, want);
    if (day) {
      return { kind: 'found', focusSessionId: want, day: day };
    }
    return {
      kind: 'gone',
      focusSessionId: want,
      nearest: nearestScheduleSlot(days, opts.todayIso, opts.now),
    };
  }

  /* TASK-330: пустая карточка катка, который ведёт расписание. Даты не обещаем —
     только наблюдение о привычке катка («Обычно по пятницам») и колокольчик. */
  function copyWith(key, fallback, kw) {
    var GC = glideCopy();
    if (GC && typeof GC.t === 'function') {
      var label = GC.t(key, kw);
      if (label && label !== key) return String(label);
    }
    return String(fallback).replace(/\{(\w+)\}/g, function (match, name) {
      return kw && Object.prototype.hasOwnProperty.call(kw, name) ? String(kw[name]) : match;
    });
  }

  var DOW_DAT_PL = ['понедельникам', 'вторникам', 'средам', 'четвергам', 'пятницам', 'субботам', 'воскресеньям'];

  function scheduleWaitView(card) {
    card = card || {};
    var habit = card.schedule_habit && typeof card.schedule_habit === 'object' ? card.schedule_habit : {};
    var kicker = '';
    var title = '';
    var wd = habit.weekday;
    if (habit.level === 'day' && typeof wd === 'number' && wd >= 0 && wd <= 6 && Math.floor(wd) === wd) {
      var day = copyLine('schedule.dow_' + wd, DOW_DAT_PL[wd]);
      title = copyWith('schedule.habit_day', 'Обычно по\u00a0{day}', { day: day });
    } else if (habit.level === 'week') {
      title = copyLine('schedule.habit_week', 'Обычно раз в\u00a0неделю');
    }
    if (title) {
      kicker = copyLine('schedule.wait_kicker', 'Новое расписание');
    } else {
      title = copyLine('schedule.wait_none', 'Ждём новое расписание');
    }
    return {
      kicker: kicker,
      title: title,
      sub: copyLine('schedule.wait_sub', 'Сообщим в\u00a0Telegram, как только появится.'),
      cta: copyLine('schedule.bell_cta', 'Сообщить, когда появится'),
      note: copyLine('schedule.bell_note', 'Одно сообщение, потом колокольчик сам выключится.'),
      on: copyLine('schedule.bell_on', 'Напоминание включено'),
      off: copyLine('schedule.bell_off', 'Выключить'),
    };
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
    var SM = scheduleModeApi();
    var mode = SM ? SM.normalizeMode(card.schedule_mode) : 'auto';
    if (SM && mode === 'phone') {
      return scheduleAsk(card);
    }
    if (SM && mode === 'season_closed') {
      return { mode: 'closed', banner: SM.seasonClosedLine(card), showRibbon: false };
    }
    var banner = seasonClosedBanner(card);
    if (banner) {
      return { mode: 'closed', banner: banner, showRibbon: false };
    }
    var sectionMode = iceSectionMode({
      tier: opts.tier || card.tier,
      hasSessions: opts.hasSessions,
    });
    if (sectionMode === 'ribbon') {
      return { mode: 'ribbon', banner: null, showRibbon: true };
    }
    var ask = scheduleAsk(card);
    // TASK-330: сеансов нет, но каток расписание ведёт — ждём его и зовём на колокольчик.
    if (card.schedule_tracked === true) ask.wait = scheduleWaitView(card);
    return ask;
  }

  function seasonClosedBanner(card) {
    card = card || {};
    if (card.in_season !== false) return null;
    var start = Number(card.season_start_month);
    var monthName = MONTHS_PREP[start] || '';
    if (monthName) return 'Закрыт до ' + monthName;
    return 'Закрыт на сезон';
  }

  /** TASK-226: напоминание о календарном старте сезона (не schedule_mode season_closed). */
  function seasonRemindView(card, opts) {
    card = card || {};
    opts = opts || {};
    var SM = scheduleModeApi();
    if (SM && SM.normalizeMode(card.schedule_mode) === 'season_closed') {
      return { show: false };
    }
    if (card.in_season !== false) return { show: false };
    var start = Number(card.season_start_month);
    if (!start || start < 1 || start > 12) return { show: false };
    var monthPrep = MONTHS_IN[start] || '';
    var subscribed = !!opts.subscribed;
    var hint = monthPrep
      ? 'В ' + monthPrep + ' напишем один раз. Лёд заливают по погоде — перед поездкой лучше уточнить.'
      : 'Напишем один раз, когда начнётся сезон. Лёд заливают по погоде — перед поездкой лучше уточнить.';
    if (subscribed) {
      hint = 'Одно сообщение, потом напоминание само выключится.';
    }
    return {
      show: true,
      subscribed: subscribed,
      watchKind: 'season_open',
      monthPrep: monthPrep,
      labelOff: 'Напомнить, когда начнётся сезон',
      labelOn: monthPrep ? 'Напомним в ' + monthPrep : 'Напоминание включено',
      hint: hint,
    };
  }

  function closedSeasonHoursLabel(card) {
    card = card || {};
    if (card.in_season === false && card.season_start_month) return 'Часы прошлого сезона';
    return 'Часы работы';
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

  /* TASK-146: часы бывают daily (каждый день) и weekly (по дням). Ключи — как на сервере
     (src/application/arena_profile.py: WEEKDAY_KEYS), неделя с понедельника. */
  var WEEK_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

  function intervalsForWeekday(hours, weekday) {
    return OH.intervalsForWeekday(hours, weekday);
  }

  function formatIntervalsRu(intervals) {
    return (intervals || [])
      .map(function (p) {
        return p[0] + '–' + p[1];
      })
      .join(' и ');
  }

  /** Первый интервал дня — для совместимости. */
  function hoursForWeekday(hours, weekday) {
    var intervals = intervalsForWeekday(hours, weekday);
    return intervals.length ? intervals[0] : null;
  }

  function formatOpeningHours(hours) {
    var days = [];
    var known = false;
    for (var d = 0; d < 7; d++) {
      var iv = intervalsForWeekday(hours, d);
      days.push(iv.length ? formatIntervalsRu(iv) : null);
      if (iv.length) known = true;
    }
    if (!known) return '';
    var key = function (p) { return p || 'выходной'; };
    var parts = [];
    var start = 0;
    for (var i = 1; i <= 7; i++) {
      if (i === 7 || key(days[i]) !== key(days[start])) {
        var label = i - 1 === start ? WEEK_SHORT[start] : WEEK_SHORT[start] + '–' + WEEK_SHORT[i - 1];
        parts.push(label + ' ' + key(days[start]));
        start = i;
      }
    }
    return parts.join(' · ');
  }

  /** «открыто до 20:00» — только если открыто сейчас; до открытия — «откроется в 10:00». */
  function openUntilLabel(hours, now, timeZone) {
    now = now instanceof Date ? now : new Date();
    var tz = MT.resolveTimeZone(timeZone);
    var weekday = MT.weekdayMon0(now, tz);
    var nowMins = OH.toMinutes(MT.hhmm(now, tz));
    /* Вчерашний ночной хвост (пт 18:00–02:00 → сб 01:00) тоже «открыто». */
    var open = OH.openIntervalAt(hours, weekday, nowMins);
    if (open) return 'открыто до ' + PD.formatClock(open[1]);
    var intervals = intervalsForWeekday(hours, weekday);
    var hm = MT.hhmm(now, tz);
    for (var i = 0; i < intervals.length; i++) {
      if (hm < intervals[i][0]) return 'откроется в ' + PD.formatClock(intervals[i][0]);
    }
    return '';
  }

  /*
   * TASK-146: расписание как сеансы в кино. Раньше каждая строка повторяла «Массовое катание ·
   * взр. 10 · дет. 8 · прокат +9» — у Замка тринадцать раз подряд. Теперь цены один раз над
   * группой, ниже — сетка времени; у каждого времени своя ссылка в кассу, если она есть.
   */
  var DAY_TOP = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

  function upcomingSessions(sessions, now) {
    /* PDEC-005: в витрине только сеансы, которые ещё не начались (как на сервере). */
    return (sessions || []).filter(function (s) { return sessionNowState(s, now) === 'upcoming'; });
  }

  /** Полоса дней: «Сегодня · Завтра · Пн 5 …», у каждого — число сеансов впереди. */
  function dayStrip(sessionDays, todayIso, now, n) {
    var byDate = {};
    (sessionDays || []).forEach(function (d) { byDate[String(d.local_date || '').slice(0, 10)] = d.sessions || []; });
    var out = [];
    for (var i = 0; i < (n || 7); i++) {
      var iso = addDaysYmd(todayIso, i);
      var wd = MT.weekdaySun0FromIso(iso);
      out.push({
        iso: iso,
        top: i === 0 ? 'Сегодня' : i === 1 ? 'Завтра' : DAY_TOP[wd],
        num: iso.slice(8, 10),
        count: upcomingSessions(byDate[iso], now).length,
        weekend: wd === 0 || wd === 6,
      });
    }
    return out;
  }

  /** Сегодня, если впереди есть сеансы; иначе первый день со льдом; иначе сегодня. */
  function defaultScheduleDay(strip) {
    for (var i = 0; i < (strip || []).length; i++) if (strip[i].count) return strip[i].iso;
    return strip && strip.length ? strip[0].iso : null;
  }

  function minutesBetween(a, b) {
    var pa = String(a || '').split(':');
    var pb = String(b || '').split(':');
    if (pa.length < 2 || pb.length < 2) return null;
    var d = (Number(pb[0]) * 60 + Number(pb[1])) - (Number(pa[0]) * 60 + Number(pa[1]));
    if (d < 0) d += 24 * 60;
    return d > 0 && d < 12 * 60 ? d : null;
  }

  function priceChips(session) {
    var cur = session.currency_code || 'BYN';
    var adult = formatMinor(session.price_adult_minor, cur);
    var child = formatMinor(session.price_child_minor, cur);
    var rental = formatMinor(session.price_rental_minor, cur);
    var out = [];
    // Семейные комбинации и прочие тарифы вне сетки взрослый/детский/прокат (ice_sessions.price_tiers).
    (Array.isArray(session.price_tiers) ? session.price_tiers : []).forEach(function (t) {
      var v = t && formatMinor(t.minor, cur);
      if (v && t.label) out.push({ label: String(t.label), value: v.withCurrency });
    });
    if (out.length && !adult && !child) return out;
    if (adult) out.push({ label: child ? 'Взрослый' : 'Билет', value: adult.withCurrency });
    if (child) out.push({ label: 'Детский', value: child.withCurrency });
    if (rental) out.push({ label: 'Прокат', value: rental.withCurrency });
    return out;
  }

  /** Подпись к детскому тарифу: «до 16 лет» без контекста непонятна родителям. */
  function formatChildTicketAgeNote(raw) {
    var note = String(raw || '').trim();
    if (!note) return '';
    // \b не работает с кириллицей, поэтому граница слова — пробел, тире или конец строки.
    if (/^детский\s+билет(?=[\s\-–—]|$)/i.test(note)) {
      return note.replace(/^детский\s+билет\s*[-–—]?\s*/i, 'Детский билет — ');
    }
    if (/^до\s+\d+\s+лет$/i.test(note)) {
      return 'Детский билет — ' + note.charAt(0).toLowerCase() + note.slice(1);
    }
    var m = note.match(/^(?:детский|дети|детям)\s+(.+)$/i);
    if (m) return 'Детский билет — ' + m[1];
    return note;
  }

  /**
   * Сеансы дня, сгруппированные по «что это и сколько стоит». Одинаковые сеансы —
   * одна группа с сеткой времени; другой тип или другая цена — своя группа.
   * `next` — ближайший сеанс дня (подсвечивается), только среди будущих.
   */
  /* Живой остаток из кассы (парсер пишет «70 мест» / «нет мест» раз в ~15 минут). Где он
     есть, плитка показывает только его: число понятнее полоски «обычно», а вместе они
     говорили бы одно и то же. Другие заметки (у ОХМ «30–35 человек») — не остаток. */
  /* «Мало» — 20 и меньше: около 20% зала Замка (115 мест). */
  var LOW_SEATS = 20;
  /* Полоска на времени — когда раскуплено больше трети: дальше Замок обычно уходит за час. */
  var FILLING_SHARE = 1 / 3;

  /**
   * TASK-333: остаток говорит формой, а цифрой — только у выбранного сеанса.
   * capacity — вместимость из снимка кассы («из 115»); без неё полоски нет, цифра остаётся.
   */
  function liveSeats(note, capacity) {
    var text = String(note || '').trim();
    var cap = Number(capacity) > 0 ? Number(capacity) : null;
    if (/^нет мест$/i.test(text)) return { label: 'нет мест', low: true, gone: true, free: 0, capacity: cap, sold: cap ? 1 : null, filling: false };
    var m = /^(\d+)\s+мест[а-я]*$/i.exec(text);
    if (!m) return null;
    var n = Number(m[1]);
    var word = n % 10 === 1 && n % 100 !== 11 ? 'место'
      : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'места' : 'мест';
    var sold = cap && cap >= n ? (cap - n) / cap : null;
    var low = n <= LOW_SEATS;
    return {
      label: low ? 'осталось\u00a0' + n : n + ' ' + word,
      count: n + ' ' + word,
      low: low,
      gone: false,
      free: n,
      capacity: cap,
      sold: sold,
      filling: !low && sold != null && sold >= FILLING_SHARE,
    };
  }

  /*
   * Тёплый кэш карточки (TASK-332): последние открытые катки — каток и расписание. Карточка
   * рисуется из него сразу, а свежие данные тихо подменяют. Лента кладёт сюда же по касанию,
   * ещё до перехода. Четыре катка по ~80 КБ — далеко от квоты sessionStorage.
   */
  var ARENA_WARM_KEY = 'glideArenaWarm:v1';
  var ARENA_WARM_MAX = 4;
  var ARENA_WARM_TTL_MS = 10 * 60 * 1000;

  function readWarmMap(storage) {
    try {
      var raw = storage && storage.getItem(ARENA_WARM_KEY);
      var map = raw ? JSON.parse(raw) : null;
      return map && typeof map === 'object' ? map : {};
    } catch (e) {
      return {};
    }
  }

  function readArenaWarm(storage, ref, nowMs) {
    if (!ref) return null;
    var rec = readWarmMap(storage)[String(ref)];
    if (!rec || !rec.card || !(rec.at > 0)) return null;
    if (nowMs - rec.at > ARENA_WARM_TTL_MS) return null;
    return { card: rec.card, sessions: rec.sessions || null, at: rec.at };
  }

  function writeArenaWarm(storage, ref, patch, nowMs) {
    if (!storage || !ref || !patch) return false;
    var map = readWarmMap(storage);
    var key = String(ref);
    var prev = map[key] || {};
    var rec = {
      at: nowMs,
      card: patch.card || prev.card || null,
      sessions: patch.sessions || prev.sessions || null,
    };
    if (!rec.card) return false;
    map[key] = rec;
    var keys = Object.keys(map).sort(function (a, b) { return (map[b].at || 0) - (map[a].at || 0); });
    keys.slice(ARENA_WARM_MAX).forEach(function (k) { delete map[k]; });
    try {
      storage.setItem(ARENA_WARM_KEY, JSON.stringify(map));
      return true;
    } catch (e) {
      try { storage.removeItem(ARENA_WARM_KEY); } catch (e2) { /* */ }
      return false;
    }
  }

  /** «72 из 115» — когда вместимость известна; иначе «72 места». */
  function seatsFreeText(seats) {
    if (!seats || seats.gone) return '';
    return seats.capacity ? seats.free + ' из\u00a0' + seats.capacity : seats.count;
  }

  function showtimesForDay(opts) {
    opts = opts || {};
    var list = upcomingSessions(opts.sessions, opts.now || new Date()).slice().sort(compareSessionsByStart);
    var groups = [];
    var index = {};
    var picked = opts.pickedId != null ? String(opts.pickedId) : null;
    var hasPicked = !!picked && list.some(function (x) { return String(x.id) === picked; });
    var nearestId = list.length && list[0].id != null ? String(list[0].id) : null;
    // Заметка про возраст делит сеансы на группы только если в одном «что и почём» их две разные:
    // у одного сеанса заметка есть, у другого парсер её не вернул — это один и тот же тариф.
    // mergePrices: цены уже показаны плитками над расписанием — сеансы одного вида и длительности
    // в один день идут одной группой (дневной и вечерний тариф не делят 12:00 и 21:00 на два блока).
    function baseKey(x, dur) {
      if (opts.mergePrices) return [iceKindLabel(x), dur].join('|');
      return [iceKindLabel(x), x.price_adult_minor, x.price_child_minor, x.price_rental_minor, dur].join('|');
    }
    var notesByBase = {};
    list.forEach(function (x) {
      var d = minutesBetween(hhmm(x.starts_at_local), hhmm(x.ends_at_local));
      var note = String(x.age_note || '').trim();
      var b = baseKey(x, d);
      notesByBase[b] = notesByBase[b] || {};
      if (note) notesByBase[b][note] = 1;
    });
    list.forEach(function (s) {
      var start = hhmm(s.starts_at_local);
      var dur = minutesBetween(start, hhmm(s.ends_at_local));
      var base = baseKey(s, dur);
      var notes = Object.keys(notesByBase[base]);
      var key = notes.length > 1 ? base + '|' + (s.age_note || '') : base;
      if (!(key in index)) {
        index[key] = groups.length;
        groups.push({
          title: iceKindLabel(s),
          duration: dur ? dur + ' мин' : '',
          prices: priceChips(s),
          note: formatChildTicketAgeNote(notes.length === 1 ? notes[0] : s.age_note),
          times: [],
        });
      }
      var cta = iceRowCta(s, opts.ticketsUrl);
      groups[index[key]].times.push({
        time: start,
        ticketHref: cta.href,
        sessionId: s.id != null ? s.id : null,
        next: !!opts.markNext && nearestId && String(s.id) === nearestId,
        picked: hasPicked && String(s.id) === picked,
        prices: priceChips(s),
        hall: sessionHall(s),
        seats: liveSeats(s.capacity_note, s.seats_capacity),
        load: s.typical_load_level || '',
      });
    });
    return { groups: groups, count: list.length };
  }

  /** Несколько номеров в каталоге часто идут через «;» — для tel: нужен каждый отдельно. */
  function phoneNumbers(raw) {
    return String(raw || '')
      .split(/[;,\n]/)
      .map(function (p) {
        return p.trim();
      })
      .filter(Boolean);
  }

  function phoneToTelHref(phone) {
    var cleaned = String(phone || '').replace(/[^\d+]/g, '');
    return cleaned ? 'tel:' + cleaned : '';
  }

  /** Быстрые действия под обложкой: маршрут, звонок, сайт/инстаграм — только то, что есть. */
  function quickActions(card) {
    card = card || {};
    var out = [];
    if (card.latitude != null && card.longitude != null) {
      out.push({ id: 'route', label: 'Маршрут', href: 'https://yandex.by/maps/?rtext=~' + card.latitude + ',' + card.longitude + '&rtt=auto' });
    } else if (card.address) {
      out.push({ id: 'route', label: 'Маршрут', href: 'https://yandex.by/maps/?text=' + encodeURIComponent(card.address) });
    }
    var phones = phoneNumbers(card.phone);
    if (phones.length) {
      out.push({
        id: 'copyPhone',
        label: 'Телефон',
        phone: phones[0],
        phones: phones,
      });
    }
    var contacts = practiceContacts(card);
    var insta = contacts.socials.filter(function (x) { return x.label === 'Instagram'; })[0];
    if (contacts.website) out.push({ id: 'site', label: 'Сайт', href: contacts.website.href });
    else if (insta) out.push({ id: 'insta', label: 'Instagram', href: insta.href });
    return out;
  }

  /**
   * Массовый доступ без сеансов льда: окна по дням + прокат из opening_hours.
   * Не пихаем расписание и прайс в short_description — карточка рисует секции.
   */
  function massAccessView(card) {
    card = card || {};
    var hours = card.opening_hours;
    if (!hours || typeof hours !== 'object') return { enabled: false };
    var catalog = Array.isArray(hours.rental_catalog) ? hours.rental_catalog : [];
    var week = weekHours(hours, new Date(), card.timezone);
    /* Центр по записи: прайс — отдельная секция, часы остаются в контактах.
       «Когда можно приехать» — про массовый доступ, не про бронь площадки. */
    var center = String(hours.center_badge || '').trim();
    var enabled =
      !center &&
      (catalog.length > 0 ||
        hours.free_entry === true ||
        Boolean(hours.rental_close && week) ||
        Boolean(hours.access_note && week));
    if (!enabled) return { enabled: false };
    return {
      enabled: true,
      week: week,
      freeEntry: hours.free_entry === true,
      rentalClose: String(hours.rental_close || '').trim(),
      trackClose: String(hours.track_close || '').trim(),
      accessNote: String(hours.access_note || '').trim(),
      rentalCatalog: catalog,
      rentalTitle: rentalSectionTitle(card, hours),
      rentalNote: String(hours.rental_note || '').trim(),
    };
  }

  /** Прайс Minikatok — услуги площадки, не прокат роликов ФК «Минск». */
  function rentalSectionTitle(card, hours) {
    var explicit = String((hours && hours.rental_title) || '').trim();
    if (explicit) return explicit;
    var blob = (String(card.name || '') + ' ' + String(card.website_url || '')).toLowerCase();
    if (blob.indexOf('minikatok') !== -1) return 'Услуги';
    return 'Прокат инвентаря';
  }

  /** Карточка хоккейного центра: коротко о месте и прайс, без ленты «открыть карточку». */
  function centerOfferView(card) {
    card = card || {};
    var hours = card.opening_hours;
    if (!hours || typeof hours !== 'object') return { enabled: false };
    if (!String(hours.center_badge || '').trim()) return { enabled: false };
    var catalog = Array.isArray(hours.rental_catalog) ? hours.rental_catalog : [];
    var about = String(card.short_description || '').trim();
    if (!catalog.length && !about) return { enabled: false };
    return {
      enabled: true,
      title: rentalSectionTitle(card, hours),
      catalog: catalog,
      note: String(hours.rental_note || '').trim(),
      about: about,
    };
  }

  /** Часы по дням для списка «Часы работы»: сегодняшний день отмечен. */
  function weekHours(hours, now, timeZone) {
    now = now instanceof Date ? now : new Date();
    var tz = MT.resolveTimeZone(timeZone);
    var today = MT.weekdayMon0(now, tz);
    var known = false;
    var rows = [];
    for (var d = 0; d < 7; d++) {
      var iv = intervalsForWeekday(hours, d);
      if (iv.length) known = true;
      rows.push({
        label: WEEK_SHORT[d],
        value: iv.length ? formatIntervalsRu(iv) : 'выходной',
        today: d === today,
        closed: !iv.length,
      });
    }
    if (!known) return null;
    var uniform = rows.every(function (r) { return r.value === rows[0].value; });
    return {
      uniform: uniform,
      rows: rows,
      todayValue: rows[today].value,
      status: openUntilLabel(hours, now, tz),
    };
  }

  function heroMetaLine(card) {
    card = card || {};
    var bits = [];
    if (card.district) bits.push(card.district);
    if (card.distance_km != null && card.distance_km !== '') {
      var km = Number(card.distance_km);
      if (!isNaN(km)) bits.push(km.toFixed(1).replace('.', ',') + ' км');
    }
    if (card.in_season !== false) {
      var until = openUntilLabel(card.opening_hours, undefined, card.timezone);
      if (until) bits.push(until);
    }
    return bits.join(' · ');
  }

  /* TASK-196: валюта услуги — код из полезной нагрузки. Отображение — конвенция
     TASK-109: RUB — «руб.», BYN буквами. */
  function priceCurrencyLabel(code) {
    var c = String(code || '').trim().toUpperCase();
    return c === 'RUB' ? 'руб.' : (c || 'BYN');
  }

  function trainerSubtitle(trainer) {
    trainer = trainer || {};
    var services = trainer.services || [];
    var names = [];
    var minPrice = null;
    var minCur = 'BYN';
    var i;
    for (i = 0; i < services.length; i++) {
      var s = services[i];
      // API отдаёт service_name; name — старые полезные нагрузки и тесты.
      var sName = s.service_name || s.name;
      if (sName) names.push(sName);
      var p = s.price_cents != null ? Number(s.price_cents) : s.price_byn != null ? Number(s.price_byn) * 100 : NaN;
      if (!isNaN(p) && p > 0 && (minPrice == null || p < minPrice)) {
        minPrice = p;
        // Валюта — у услуги с минимальной ценой (TASK-196): тренер из RU-города
        // показывает цены в RUB. Полезные нагрузки без валюты читаются как BYN.
        minCur = String(s.currency_code || 'BYN');
      }
    }
    var bits = [];
    if (names.length) bits.push(names[0]);
    // TASK-265: сервер считает самое дешёвое занятие (абонемент на занятие, тарифы,
    // групповые) — trainer_min_price.py; сайт показывает ту же строку.
    if (trainer.min_session_price_cents != null && Number(trainer.min_session_price_cents) > 0) {
      var best = formatMinor(
        Number(trainer.min_session_price_cents),
        priceCurrencyLabel(trainer.min_session_price_currency || 'BYN')
      );
      if (best) bits.push('от ' + best.withCurrency.replace('.', ',') + ' за занятие');
      return bits.join(' · ');
    }
    if (minPrice != null) {
      var fmt = formatMinor(minPrice, priceCurrencyLabel(minCur));
      if (fmt) bits.push('от ' + (fmt.withCurrency || fmt.amount));
    }
    return bits.join(' · ');
  }

  function yearsWord(n) {
    var m10 = n % 10;
    var m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return 'год';
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return 'года';
    return 'лет';
  }

  /**
   * Превью тренера на карточке катка, вариант А (владелец 2026-10-20): фото-витрина.
   * Только то, что есть: нет отзывов — нет рейтинга (без «0 отзывов»), нет цены — нет строки цены.
   * `after` — конец выбранного сеанса «YYYY-MM-DDTHH:MM»: первое окно после него — «Свободен в 13:15» на фото.
   */
  function trainerPreview(trainer, opts) {
    trainer = trainer || {};
    opts = opts || {};
    var p = trainer.profile || {};
    var count = Number(p.rating_count) || 0;
    var rate = count > 0 && p.rating_avg != null ? Number(p.rating_avg).toFixed(1).replace('.', ',') + ' · ' + count : '';
    var names = (trainer.services || [])
      .map(function (s) { return String(s.service_name || s.name || '').trim(); })
      .filter(Boolean);
    var facts = [];
    var exp = Math.floor(Number(p.experience_years) || 0);
    if (exp > 0) facts.push(exp + ' ' + yearsWord(exp) + ' на льду');
    if (trainer.has_pass_products) facts.push('есть абонементы');
    var price = '';
    var cents = Number(trainer.min_session_price_cents);
    if (cents > 0) {
      var best = formatMinor(cents, priceCurrencyLabel(trainer.min_session_price_currency || 'BYN'));
      if (best) price = 'от ' + String(best.withCurrency || best.amount).replace('.', ',');
    }
    var wins = trainer.windows || [];
    var fit = null;
    if (opts.after) {
      for (var i = 0; i < wins.length; i++) {
        if (String(wins[i].starts_at || '').slice(0, 16) >= opts.after) { fit = wins[i]; break; }
      }
    }
    var next = '';
    if (!fit && wins[0]) {
      var day = String(wins[0].day || '');
      next = (day ? day.charAt(0).toUpperCase() + day.slice(1) + ' ' : '') + String(wins[0].time || '');
    }
    return {
      rate: rate,
      fit: fit ? 'Свободен в ' + fit.time : '',
      what: names.slice(0, 3).join(' · '),
      facts: facts.join(' · '),
      price: price,
      next: next.trim() || 'Профиль →',
    };
  }

  /**
   * Массовое катание (days) и ОХМ (ohm_days) — в одном списке для share sheet.
   * Без merge каталог на вкладке «С клюшкой» подставлял первый сеанс МК вместо ОХМ.
   */
  function combineSessionDayLists(days, ohmDays) {
    var order = [];
    var byDate = {};
    function add(list) {
      list = list || [];
      for (var i = 0; i < list.length; i++) {
        var iso = list[i].local_date;
        if (!iso) continue;
        if (!byDate[iso]) {
          byDate[iso] = [];
          order.push(iso);
        }
        byDate[iso] = byDate[iso].concat(list[i].sessions || []);
      }
    }
    add(days);
    add(ohmDays);
    // Массовое и ОХМ приходят двумя списками; в дне — один порядок, по времени.
    order.sort();
    return order.map(function (iso) {
      var sessions = byDate[iso].slice().sort(function (a, b) {
        var ta = String((a && a.starts_at_local) || '');
        var tb = String((b && b.starts_at_local) || '');
        return ta < tb ? -1 : ta > tb ? 1 : 0;
      });
      return { local_date: iso, sessions: sessions };
    });
  }

  function shareSlotKindNote(session) {
    var kind = session && session.kind;
    if (kind === 'hockey_practice') {
      var GC = rootRef.GlideCopy;
      if (GC && typeof GC.t === 'function') {
        var full = String(GC.t('kind.hockey_practice') || '');
        if (full && full !== 'kind.hockey_practice') {
          return full.indexOf('ОХМ') >= 0 ? 'ОХМ' : full;
        }
      }
      return 'ОХМ';
    }
    return '';
  }

  /**
   * TASK-146: ближайшие сеансы для шита «Поделиться» — делятся конкретным временем.
   * «Сегодня 19:00» / «Завтра 11:00» / «Сб 18:30». Порядок — как в ленте.
   */
  function shareSlots(days, todayIso, limit) {
    days = days || [];
    var unlimited = limit === 0 || limit == null;
    if (!unlimited) limit = limit || 6;
    var tomorrow = isoDate(todayIso) ? MT.addDaysIso(todayIso, 1) : '';
    var out = [];
    for (var i = 0; i < days.length && (unlimited || out.length < limit); i++) {
      var iso = days[i].local_date;
      var head =
        iso === todayIso
          ? 'Сегодня'
          : iso === tomorrow
            ? 'Завтра'
            : WEEKDAYS_SHORT[MT.weekdaySun0FromIso(iso)];
      var list = days[i].sessions || [];
      for (var j = 0; j < list.length && (unlimited || out.length < limit); j++) {
        var hhmm = String(list[j].starts_at_local || '').slice(0, 5);
        if (list[j].id == null || !hhmm) continue;
        out.push({ id: list[j].id, label: head + ' ' + hhmm, localDate: iso, time: hhmm });
      }
    }
    return out;
  }

  /** TASK-158: список сеансов в share sheet — группы по дню. */
  function shareSlotsGrouped(days, todayIso) {
    days = days || [];
    var tomorrow = isoDate(todayIso) ? MT.addDaysIso(todayIso, 1) : '';
    var sections = [];
    for (var i = 0; i < days.length; i++) {
      var iso = days[i].local_date;
      var dayLabel =
        iso === todayIso
          ? 'Сегодня'
          : iso === tomorrow
            ? 'Завтра'
            : WEEKDAYS_SHORT[MT.weekdaySun0FromIso(iso)];
      var list = days[i].sessions || [];
      var rows = [];
      for (var j = 0; j < list.length; j++) {
        var s = list[j];
        var time = String(s.starts_at_local || '').slice(0, 5);
        if (s.id == null || !time) continue;
        var price = formatMinor(s.price_adult_minor, s.currency_code || 'BYN');
        var metaBits = [];
        if (price && price.withCurrency) metaBits.push(price.withCurrency);
        var kindNote = shareSlotKindNote(s);
        if (kindNote) metaBits.push(kindNote);
        rows.push({
          id: s.id,
          time: time,
          meta: metaBits.join(' · '),
          kind: s.kind || '',
        });
      }
      if (rows.length) {
        sections.push({
          dayLabel: dayLabel,
          localDate: iso,
          dayNum: String(Number(iso.slice(8, 10))),
          rows: rows,
        });
      }
    }
    return sections;
  }

  function shareSlotInviteLabel(days, todayIso, sessionId, focusIso) {
    if (sessionId == null) return '';
    var id = String(sessionId);
    var slots = shareSlots(days, todayIso, 0);
    for (var i = 0; i < slots.length; i++) {
      if (String(slots[i].id) !== id) continue;
      if (focusIso && slots[i].localDate === focusIso) return slots[i].time;
      if (slots[i].localDate === todayIso) return slots[i].time;
      return slots[i].label;
    }
    return '';
  }

  /* Подсказка над временем. Полоска загрузки (TASK-290) объясняется здесь же: у плитки
     Mini App нет места под слово, а подпись под временем занята остатком мест. */
  function scheduleInviteHint(hasTicketLinks, hasLoad, hasSeats) {
    /* TASK-333: остаток виден только когда мест мало, билет — в панели внизу: объяснять их не нужно. */
    if (hasTicketLinks && hasLoad && !hasSeats) {
      return 'Выберите время — позовём на него друзей. Полоска — насколько обычно людно; на красные часы билет лучше взять заранее.';
    }
    if (hasTicketLinks) return 'Выберите время — позовём на него друзей.';
    if (hasLoad && !hasSeats) return 'Полоска под временем — насколько обычно людно в эти часы.';
    return '';
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
    sessionNowState: sessionNowState,
    sessionStartMs: sessionStartMs,
    compareSessionsByStart: compareSessionsByStart,
    ymdInTimeZone: ymdInTimeZone,
    iceKindLabel: iceKindLabel,
    sessionHall: sessionHall,
    priceChips: priceChips,
    scheduleBasisHint: scheduleBasisHint,
    iceRowCta: iceRowCta,
    buildRibbonForDay: buildRibbonForDay,
    buildWeekSummaries: buildWeekSummaries,
    heroPhotoUrl: heroPhotoUrl,
    heroPhotoUrls: heroPhotoUrls,
    heroPrefetchRecord: heroPrefetchRecord,
    heroPrefetchMatches: heroPrefetchMatches,
    heroView: heroView,
    ribbonLegend: ribbonLegend,
    trainerCta: trainerCta,
    ticketCta: ticketCta,
    buildBookingHref: buildBookingHref,
    parseArenaRef: parseArenaRef,
    sessionIdFromStartParam: sessionIdFromStartParam,
    dayForSession: dayForSession,
    ARENA_SESSION_WINDOW_DAYS: ARENA_SESSION_WINDOW_DAYS,
    nearestScheduleSlot: nearestScheduleSlot,
    focusState: focusState,
    iceSectionMode: iceSectionMode,
    iceFeedView: iceFeedView,
    scheduleWaitView: scheduleWaitView,
    seasonClosedBanner: seasonClosedBanner,
    seasonRemindView: seasonRemindView,
    closedSeasonHoursLabel: closedSeasonHoursLabel,
    amenityChips: amenityChips,
    formatOpeningHours: formatOpeningHours,
    openUntilLabel: openUntilLabel,
    hoursForWeekday: hoursForWeekday,
    heroMetaLine: heroMetaLine,
    trainerSubtitle: trainerSubtitle,
    trainerPreview: trainerPreview,
    parseLocalDate: parseLocalDate,
    ymd: ymd,
    dayTabFromIso: dayTabFromIso,
    ribbonIsoForDay: ribbonIsoForDay,
    practiceContacts: practiceContacts,
    startParamFromLocation: startParamFromLocation,
    combineSessionDayLists: combineSessionDayLists,
    shareSlots: shareSlots,
    shareSlotsGrouped: shareSlotsGrouped,
    shareSlotInviteLabel: shareSlotInviteLabel,
    scheduleInviteHint: scheduleInviteHint,
    liveSeats: liveSeats,
    seatsFreeText: seatsFreeText,
    readArenaWarm: readArenaWarm,
    writeArenaWarm: writeArenaWarm,
    ARENA_WARM_TTL_MS: ARENA_WARM_TTL_MS,
    shopServicesView: shopServicesView,
    WEEKDAYS_SHORT: WEEKDAYS_SHORT,
    dayStrip: dayStrip,
    parseScheduleFocus: parseScheduleFocus,
    defaultScheduleDay: defaultScheduleDay,
    formatChildTicketAgeNote: formatChildTicketAgeNote,
    showtimesForDay: showtimesForDay,
    phoneNumbers: phoneNumbers,
    phoneToTelHref: phoneToTelHref,
    quickActions: quickActions,
    weekHours: weekHours,
    massAccessView: massAccessView,
    centerOfferView: centerOfferView,
    intervalsForWeekday: intervalsForWeekday,
    formatIntervalsRu: formatIntervalsRu,
  };
});
