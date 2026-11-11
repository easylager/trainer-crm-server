/**
 * Вкладка «Я» (TASK-370). Всё — из одного GET /api/webapp/client/me (контракт TASK-368).
 *
 * screenModel(data, opts) — чистая функция: какие блоки и строки видны при каком ответе и что
 * в них написано. Её проверяют tests/js/client-me-model.test.js. Ниже — отрисовка по блокам:
 * после шторки перерисовывается только блок, у которого поменялась модель.
 */
(function (root) {
  'use strict';

  var NBSP = '\u00a0';
  var TZ = 'Europe/Minsk';
  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  var WEEKDAY_IN = ['в воскресенье', 'в понедельник', 'во вторник', 'в среду', 'в четверг', 'в пятницу', 'в субботу'];
  /* В базе клубы без «ё» — на экране с ней (тот же словарь, что clubName в kto-kogo-model.js). */
  var SPELL = { 'Шахтер': 'Шахтёр', 'Могилев': 'Могилёв' };
  var ICE_TITLE = 'Лёд и занятия';
  var WARM_KEY = 'cw_me_warm_v1';
  var WARM_FRESH_MS = 60000;
  var ME_URL = '/api/webapp/client/me';

  function pluralRu(n, one, few, many) {
    var rt = root.RuText;
    if (rt && typeof rt.pluralRu === 'function') return rt.pluralRu(n, one, few, many);
    var a = Math.abs(Number(n));
    var lastTwo = a % 100;
    var last = a % 10;
    if (lastTwo >= 11 && lastTwo <= 14) return many;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  function count(n, one, few, many) {
    return String(n) + NBSP + pluralRu(n, one, few, many);
  }

  function positive(value) {
    return typeof value === 'number' && isFinite(value) && value > 0;
  }

  /* Честный ноль тоже число: сервер отдаёт null, только когда играть было нечего. */
  function isCount(value) {
    return typeof value === 'number' && isFinite(value) && value >= 0;
  }

  function text(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function isObject(value) {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  function minskParts(date) {
    var parts = {};
    new Intl.DateTimeFormat('en-GB', {
      timeZone: TZ,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      weekday: 'short',
      hourCycle: 'h23',
    })
      .formatToParts(date)
      .forEach(function (p) {
        parts[p.type] = p.value;
      });
    return {
      y: Number(parts.year),
      m: Number(parts.month),
      d: Number(parts.day),
      hh: parts.hour,
      mm: parts.minute,
      wd: { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[parts.weekday],
    };
  }

  function dayIndex(p) {
    return Date.UTC(p.y, p.m - 1, p.d) / 86400000;
  }

  /**
   * «сегодня, 19:30» · «завтра, 18:30» · «в пятницу, 19:30» · «13 ноября, 19:30» — по минскому времени,
   * как whenLabel в kto-kogo-model.js; после «в»/«во» — неразрывный пробел. Нет даты — ''.
   */
  function whenLabel(iso, now) {
    if (typeof iso !== 'string' || isNaN(Date.parse(iso))) return '';
    var p = minskParts(new Date(iso));
    var n = minskParts(now || new Date());
    var diff = dayIndex(p) - dayIndex(n);
    var day;
    if (diff === 0) day = 'сегодня';
    else if (diff === 1) day = 'завтра';
    else if (diff > 1 && diff < 7) day = WEEKDAY_IN[p.wd].replace(' ', NBSP);
    else day = p.d + NBSP + MONTHS[p.m - 1];
    return day + ', ' + String(Number(p.hh)) + ':' + p.mm;
  }

  function clubName(name) {
    var raw = text(name);
    return SPELL[raw] || raw;
  }

  function headerModel(data) {
    var club = isObject(data.club) && text(data.club.name) ? data.club : null;
    var city = text(data.city);
    return {
      name: text(data.name) || 'Вы',
      initial: text(data.initial) || '?',
      city: city || null,
      cover: club
        ? { color: text(club.color) || null, label: clubName(club.name), ink: text(club.label_ink) || null }
        : null,
    };
  }

  /* Ячейка с нулём не показывается (README эпика): сервер отдаёт null, но очки бывают 0 при сыгранных матчах. */
  function statsModel(stats) {
    var s = isObject(stats) ? stats : {};
    var cells = [];
    if (positive(s.trainings)) {
      cells.push({ key: 'trainings', value: String(s.trainings), label: pluralRu(s.trainings, 'тренировка', 'тренировки', 'тренировок'), href: 'client-stats' });
    }
    if (positive(s.streak_weeks)) {
      cells.push({ key: 'streak_weeks', value: String(s.streak_weeks), label: pluralRu(s.streak_weeks, 'неделя подряд', 'недели подряд', 'недель подряд'), href: 'client-stats' });
    }
    if (isCount(s.kk_points)) {
      cells.push({ key: 'kk_points', value: String(s.kk_points), label: pluralRu(s.kk_points, 'очко', 'очка', 'очков'), href: 'kto-kogo' });
    }
    if (isCount(s.kk_place)) {
      cells.push({ key: 'kk_place', value: String(s.kk_place), label: 'место', href: 'kto-kogo' });
    }
    return cells.length ? cells : null;
  }

  function clubTile(club, now) {
    if (!isObject(club) || !text(club.name)) return { kind: 'empty' };
    var match = isObject(club.next_match) ? whenLabel(club.next_match.starts_at, now) : '';
    return {
      kind: 'club',
      name: clubName(club.name),
      logo: text(club.logo) || null,
      short: text(club.short),
      color: text(club.color) || null,
      ink: text(club.label_ink) || null,
      note: match ? 'Матч ' + match : null,
    };
  }

  function sessionsNote(home) {
    var left = Number(home.sessions_left_today);
    if (positive(left)) return 'Сегодня ещё' + NBSP + count(left, 'сеанс', 'сеанса', 'сеансов');
    var first = text(home.tomorrow_first);
    if (first) return 'Сегодня сеансов нет, завтра' + NBSP + '— с' + NBSP + first;
    return 'Сегодня сеансов нет';
  }

  function rinkTile(home) {
    if (!isObject(home) || !text(home.name)) return { kind: 'empty' };
    return {
      kind: 'rink',
      id: typeof home.id === 'number' ? home.id : null,
      name: text(home.name),
      href: text(home.href) || null,
      note: sessionsNote(home),
    };
  }

  /**
   * «Семья»: люди без «вас». Безымянный не печатается пустотой — он уходит в «и ещё N»;
   * если безымянные все — «N близкий/близких».
   */
  function familyValue(people) {
    var list = Array.isArray(people) ? people : [];
    var others = list.filter(function (p) {
      return isObject(p) && p.is_you === false;
    });
    if (!others.length) return 'Добавить близкого';
    var named = others
      .map(function (p) {
        return text(p.name);
      })
      .filter(Boolean);
    if (!named.length) return count(others.length, 'близкий', 'близких', 'близких');
    var shown = named.slice(0, 2);
    var rest = others.length - shown.length;
    return shown.join(', ') + (rest > 0 ? ' и' + NBSP + 'ещё' + NBSP + rest : '');
  }

  function iceRows(rows, opts, now) {
    var r = isObject(rows) ? rows : {};
    var out = [];
    if (isObject(r.bookings) && !opts.bookingsTab) {
      out.push({ key: 'bookings', label: 'Мои записи', value: whenLabel(r.bookings.next_starts_at, now), href: 'client-bookings' });
    }
    if (isObject(r.passes)) {
      var left = r.passes.lessons_left;
      out.push({
        key: 'passes',
        label: 'Абонементы',
        value: positive(left) ? count(left, 'занятие', 'занятия', 'занятий') : '',
        href: 'client-passes-certificates',
      });
    }
    if (isObject(r.saved) && positive(r.saved.count)) {
      out.push({ key: 'saved', label: 'Сохранённые', value: String(r.saved.count), href: 'client-saved-trainers' });
    }
    if (isObject(r.requests) && positive(r.requests.count)) {
      out.push({ key: 'requests', label: 'Заявки на\u00a0тренера', value: String(r.requests.count), href: 'client-requests' });
    }
    var people = isObject(r.family) ? r.family.people : null;
    out.push({ key: 'family', label: 'Семья', value: familyValue(people), href: 'client-family-access' });
    return out;
  }

  /**
   * Модель экрана. opts: { bookingsTab: bool — в баре есть «Записи», now: Date }.
   * Шапка, клуб, каток и цифры — всегда про аккаунт; profile_name меняет только заголовок занятий.
   */
  function screenModel(data, opts) {
    var d = isObject(data) ? data : {};
    var o = opts || {};
    var now = o.now || new Date();
    var profile = text(d.profile_name);
    return {
      header: headerModel(d),
      stats: statsModel(d.stats),
      club: clubTile(d.club, now),
      rink: rinkTile(d.home_arena),
      ice: {
        title: profile ? ICE_TITLE + NBSP + '· ' + profile : ICE_TITLE,
        rows: iceRows(d.rows, { bookingsTab: !!o.bookingsTab }, now),
      },
      app: { title: 'Приложение', rows: [{ key: 'support', label: 'Написать нам', value: '', href: 'client-support' }] },
    };
  }

  /** Ответ, по которому можно рисовать: кэш старой схемы (rows.family.profiles) — нет. */
  function isUsable(data) {
    return (
      isObject(data) &&
      typeof data.name === 'string' &&
      isObject(data.rows) &&
      isObject(data.rows.family) &&
      Array.isArray(data.rows.family.people) &&
      data.rows.family.people.length > 0
    );
  }

  function activePerson(data) {
    var people = data.rows.family.people;
    for (var i = 0; i < people.length; i++) {
      if (isObject(people[i]) && people[i].active === true) return people[i];
    }
    return null;
  }

  /**
   * Тёплый кэш бара: {ts, data}, свежий — 60 с. Битый, старой схемы или про другого человека
   * («Лёд и занятия» у ребёнка свои) — null. guessId — профиль, от имени которого спросим сервер.
   */
  function readWarm(raw, nowMs, guessId) {
    var parsed;
    try {
      parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
    } catch (e) {
      return null;
    }
    if (!isObject(parsed) || typeof parsed.ts !== 'number') return null;
    var age = nowMs - parsed.ts;
    if (!(age >= 0 && age < WARM_FRESH_MS)) return null;
    if (!isUsable(parsed.data)) return null;
    var active = activePerson(parsed.data);
    if (!active) return null;
    if (guessId == null) {
      if (active.is_you !== true) return null;
    } else if (active.profile_id !== guessId) {
      return null;
    }
    return parsed.data;
  }

  var model = {
    screenModel: screenModel,
    whenLabel: whenLabel,
    familyValue: familyValue,
    sessionsNote: sessionsNote,
    clubName: clubName,
    isUsable: isUsable,
    readWarm: readWarm,
    WARM_KEY: WARM_KEY,
    WARM_FRESH_MS: WARM_FRESH_MS,
  };
  root.ClientMeModel = model;
  if (typeof module === 'object' && module.exports) module.exports = model;

  /* ── Страница ─────────────────────────────────────────────────────────── */

  var doc = root.document;
  if (!doc || !doc.getElementById || !doc.getElementById('meRoot')) return;

  var ICONS = {
    pencil: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>',
    plus: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
    skate: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 15h11.5c1.5 0 2.5-.8 2.5-2V6h-4v4l-3 1.2c-1.2.5-2 1.6-2 2.8"/><path d="M3 19h17"/><path d="M7 15v4M15 15v4"/></svg>',
    chevron: '<svg class="cm-row__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>',
    bookings: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M8 3v4M16 3v4M3.5 10h17"/>',
    passes: '<path d="M3.5 7h17v3a2 2 0 0 0 0 4v3h-17v-3a2 2 0 0 0 0-4z"/><path d="M14.5 7v10" stroke-dasharray="1.5 2.5"/>',
    saved: '<path d="M7 4h10v16l-5-3.5L7 20z"/>',
    requests: '<path d="M7 3.5h7l4 4V20.5H6V3.5z"/><path d="M13.5 3.5V8H18M9 13.5l2 2 4-4"/>',
    family: '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9.5" r="2.2"/><path d="M3.5 19c.6-3 2.8-5 5.5-5s4.9 2 5.5 5M15.5 14.2c2.2.2 3.7 2 4.2 4.8"/>',
    support: '<path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 5 5z"/>',
  };

  function rowIcon(key) {
    return '<svg class="cm-row__icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[key] + '</svg>';
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* Цвет из API идёт в style — только #rgb/#rrggbb. */
  function safeColor(value) {
    return /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(value || '') ? value : null;
  }

  function headerHtml(h) {
    var cover = '';
    if (h.cover) {
      var bg = safeColor(h.cover.color);
      var ink = safeColor(h.cover.ink);
      cover =
        '<div class="cm-cover"' + (bg ? ' style="background:' + bg + '"' : '') + '>' +
        '<span class="cm-cover__label"' + (ink ? ' style="color:' + ink + '"' : '') + '>' + esc(h.cover.label) + '</span>' +
        '</div>';
    }
    return (
      '<section class="cm-card cm-head' + (h.cover ? ' cm-head--cover' : '') + '" data-block="header">' +
      cover +
      '<div class="cm-id">' +
      '<div class="cm-avatar" aria-hidden="true">' + esc(h.initial) + '</div>' +
      '<div class="cm-id__text">' +
      '<h1 class="cm-name">' + esc(h.name) + '</h1>' +
      (h.city ? '<div class="cm-city">' + esc(h.city) + '</div>' : '') +
      '</div>' +
      '<button type="button" class="cm-edit ga-press" data-act="name" aria-label="Изменить">' + ICONS.pencil + '<span class="cm-edit__t">Изменить</span></button>' +
      '</div>' +
      '</section>'
    );
  }

  function statsHtml(cells) {
    if (!cells) return '';
    return (
      '<section class="cm-card cm-stats" data-block="stats" style="--cm-cols:' + cells.length + '">' +
      cells
        .map(function (c) {
          return (
            '<a class="cm-stat ga-press" href="' + c.href + '" data-nav="' + c.href + '">' +
            '<span class="cm-stat__n">' + esc(c.value) + '</span>' +
            '<span class="cm-stat__l">' + esc(c.label) + '</span>' +
            '</a>'
          );
        })
        .join('') +
      '</section>'
    );
  }

  function emptyTile(kicker, label, act) {
    return (
      '<button type="button" class="cm-tile cm-tile--empty ga-press" data-act="' + act + '">' +
      '<span class="cm-kicker">' + kicker + '</span>' +
      '<span class="cm-tile__add">' + ICONS.plus + label + '</span>' +
      '</button>'
    );
  }

  function clubHtml(c) {
    if (c.kind !== 'club') return emptyTile('Болею за', 'Выбрать команду', 'club');
    var mark;
    if (c.logo) {
      mark = '<span class="cm-tile__logo cm-tile__logo--img"><img src="' + esc(c.logo) + '" alt="" width="40" height="40" decoding="async"></span>';
    } else {
      var bg = safeColor(c.color);
      var ink = safeColor(c.ink);
      var style = (bg ? 'background:' + bg + ';' : '') + (ink ? 'color:' + ink : '');
      mark = '<span class="cm-tile__logo"' + (style ? ' style="' + style + '"' : '') + '>' + esc(c.short) + '</span>';
    }
    return (
      '<button type="button" class="cm-tile ga-press" data-act="club">' +
      '<span class="cm-kicker">Болею за</span>' +
      mark +
      '<span class="cm-tile__name">' + esc(c.name) + '</span>' +
      (c.note ? '<span class="cm-tile__note">' + esc(c.note) + '</span>' : '') +
      '</button>'
    );
  }

  function rinkHtml(r) {
    if (r.kind !== 'rink') return emptyTile('Мой каток', 'Выбрать каток', 'rink');
    var body =
      '<span class="cm-kicker">Мой каток</span>' +
      '<span class="cm-tile__icon">' + ICONS.skate + '</span>' +
      '<span class="cm-tile__name">' + esc(r.name) + '</span>' +
      '<span class="cm-tile__note">' + esc(r.note) + '</span>';
    var tile = r.href
      ? '<a class="cm-tile ga-press" href="' + esc(r.href) + '" data-nav="' + esc(r.href) + '">' + body + '</a>'
      : '<div class="cm-tile">' + body + '</div>';
    return (
      '<div class="cm-tile-wrap">' + tile +
      '<button type="button" class="cm-rink-edit" data-act="rink" aria-label="Сменить каток">' + ICONS.pencil + '</button>' +
      '</div>'
    );
  }

  function tilesHtml(club, rink) {
    return '<div class="cm-tiles" data-block="tiles">' + clubHtml(club) + rinkHtml(rink) + '</div>';
  }

  function listHtml(block, name) {
    return (
      '<div class="cm-group-block" data-block="' + name + '">' +
      '<h2 class="cm-group">' + esc(block.title) + '</h2>' +
      '<nav class="cm-card cm-list" aria-label="' + esc(block.title) + '">' +
      block.rows
        .map(function (r) {
          return (
            '<a class="cm-row ga-press" href="' + r.href + '" data-nav="' + r.href + '">' +
            rowIcon(r.key) +
            '<span class="cm-row__label">' + esc(r.label) + '</span>' +
            (r.value ? '<span class="cm-row__value">' + esc(r.value) + '</span>' : '') +
            ICONS.chevron +
            '</a>'
          );
        })
        .join('') +
      '</nav>' +
      '</div>'
    );
  }

  var BLOCKS = ['header', 'stats', 'tiles', 'ice', 'app'];

  function blockParts(m) {
    return {
      header: { key: JSON.stringify(m.header), html: headerHtml(m.header) },
      stats: { key: JSON.stringify(m.stats), html: statsHtml(m.stats) },
      tiles: { key: JSON.stringify([m.club, m.rink]), html: tilesHtml(m.club, m.rink) },
      ice: { key: JSON.stringify(m.ice), html: listHtml(m.ice, 'ice') },
      app: { key: JSON.stringify(m.app), html: listHtml(m.app, 'app') },
    };
  }

  var mount = doc.getElementById('meRoot');
  var state = { data: null, keys: null, loading: null, again: false, failed: false };

  function tg() {
    return root.Telegram && root.Telegram.WebApp ? root.Telegram.WebApp : null;
  }

  function initData() {
    var rt = root.MiniAppRuntime;
    if (rt && typeof rt.getCredential === 'function') {
      var c = rt.getCredential();
      if (c) return String(c);
    }
    var w = tg();
    if (w && w.initData) return String(w.initData);
    try {
      return new URLSearchParams(root.location.search).get('init_data') || '';
    } catch (e) {
      return '';
    }
  }

  function bookingsTab() {
    var shell = root.ClientShell;
    try {
      return !!(shell && typeof shell.uiFlags === 'function' && shell.uiFlags().bookings_tab);
    } catch (e) {
      return false;
    }
  }

  function profileGuess() {
    var cps = root.ClientProfileSwitcher;
    if (!cps) return null;
    var id = cps.getStoredActiveProfileId();
    if (id == null) id = cps.getCachedDefaultProfileId();
    return id != null && Number(id) > 0 ? Number(id) : null;
  }

  /*
   * Данные рисуем поверх скелета только с загруженными шрифтами: подмена шрифта на уже
   * нарисованном тексте переносит строки на 360 px и двигает списки (CLS). Скелет без текста
   * ждёт не дольше FONT_WAIT_MS.
   */
  var FONT_WAIT_MS = 700;
  var fontsReady = (function () {
    var f = doc.fonts;
    if (!f || typeof f.load !== 'function') return Promise.resolve();
    var faces = ['400 24px "Dela Gothic One"', '400 15px "Golos Text"', '600 15px "Golos Text"', '700 11px "Golos Text"'];
    var loads = Promise.all(faces.map(function (face) {
      /* Файлы разбиты по unicode-range: без кириллического образца грузится только латиница. */
      return f.load(face, 'Яя1').catch(function () { /* шрифт не загрузился — рисуем запасным */ });
    }));
    return Promise.race([loads, new Promise(function (done) { setTimeout(done, FONT_WAIT_MS); })]);
  })();

  /** Рисует ответ. Первый раз — целиком; дальше — только блоки, у которых поменялась модель. */
  function paint(data) {
    state.data = data;
    state.failed = false;
    var m = screenModel(data, { bookingsTab: bookingsTab(), now: new Date() });
    var parts = blockParts(m);
    if (!state.keys) {
      mount.innerHTML = BLOCKS.map(function (b) {
        return parts[b].html;
      }).join('');
      mount.removeAttribute('aria-busy');
      state.keys = {};
      BLOCKS.forEach(function (b) {
        state.keys[b] = parts[b].key;
      });
      fitName();
      return;
    }
    BLOCKS.forEach(function (b, i) {
      if (state.keys[b] === parts[b].key) return;
      state.keys[b] = parts[b].key;
      var old = mount.querySelector('[data-block="' + b + '"]');
      var holder = doc.createElement('div');
      holder.innerHTML = parts[b].html;
      var next = holder.firstElementChild;
      if (old && next) old.replaceWith(next);
      else if (old) old.remove();
      else if (next) {
        var after = null;
        for (var j = i - 1; j >= 0 && !after; j--) after = mount.querySelector('[data-block="' + BLOCKS[j] + '"]');
        if (after) after.after(next);
        else mount.prepend(next);
      }
      if (b === 'header') fitName();
    });
  }

  /*
   * Имя — до двух строк 24 px, не влезает — 20 px; без многоточия и без разрыва посреди слова.
   * Колонка рядом с аватаром узкая, поэтому дальше имя уходит под аватар на всю ширину карточки;
   * только слово шире самой карточки переносится внутри.
   */
  var NAME_STEPS = [
    ['', false],
    ['cm-name--long', false],
    ['', true],
    ['cm-name--long', true],
  ];

  /* В макете «Максим» 24 px заходит на 6 px в зазор 12 px перед «Изменить»; 4 px воздуха оставляем. */
  var NAME_GAP_ALLOWANCE = 8;

  function nameFits(el) {
    if (el.scrollWidth > el.clientWidth + NAME_GAP_ALLOWANCE) return false;
    var lh = parseFloat(root.getComputedStyle(el).lineHeight) || 26.4;
    return el.getBoundingClientRect().height <= lh * 2 + 1;
  }

  function fitName() {
    var el = mount.querySelector('.cm-name');
    var card = mount.querySelector('.cm-head');
    if (!el || !card) return;
    for (var i = 0; i < NAME_STEPS.length; i++) {
      el.classList.toggle('cm-name--long', NAME_STEPS[i][0] !== '');
      el.classList.remove('cm-name--break');
      card.classList.toggle('cm-head--stack', NAME_STEPS[i][1]);
      if (nameFits(el)) return;
    }
    el.classList.add('cm-name--break');
  }

  function showError() {
    state.keys = null;
    state.failed = true;
    mount.removeAttribute('aria-busy');
    mount.innerHTML =
      '<div class="state-panel error cm-state" role="alert">' +
      '<p class="cm-state__text">Не загрузилось</p>' +
      '<button type="button" class="cm-state__retry ga-press" data-act="retry">Повторить</button>' +
      '</div>';
  }

  function writeWarm(data) {
    try {
      root.sessionStorage.setItem(WARM_KEY, JSON.stringify({ ts: Date.now(), data: data }));
    } catch (e) { /* приватный режим или квота */ }
  }

  function request(profileId) {
    var headers = { 'X-Telegram-Init-Data': initData() };
    if (profileId != null) headers['X-Profile-Id'] = String(profileId);
    return root.fetch(ME_URL, { headers: headers, cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('me ' + r.status);
      return r.json();
    });
  }

  function profilesReady() {
    var cps = root.ClientProfileSwitcher;
    return cps && typeof cps.init === 'function' ? cps.init() : Promise.resolve();
  }

  /**
   * Свежий ответ. Есть догадка о профиле — сразу с ней; нет или сервер её не принял — после
   * загрузки профилей (тот же порядок, что «Мои записи»: без X-Profile-Id сервер возьмёт «вас»).
   */
  function load(afterCurrent) {
    if (state.loading) {
      /* После сохранения ответ, который уже летит, мог уйти до него: перезапрашиваем ПОСЛЕ него. */
      if (afterCurrent === true) state.again = true;
      return state.loading;
    }
    var guess = profileGuess();
    var first = guess != null ? request(guess) : profilesReady().then(function () { return request(null); });
    state.loading = first
      .catch(function () {
        if (guess == null) throw new Error('me');
        return profilesReady().then(function () { return request(null); });
      })
      .then(function (data) {
        if (!isUsable(data)) throw new Error('me schema');
        writeWarm(data);
        return fontsReady.then(function () {
          paint(data);
        });
      })
      .catch(function () {
        if (!state.data) showError();
      })
      .then(function () {
        state.loading = null;
        if (state.again) {
          state.again = false;
          return load();
        }
      });
    return state.loading;
  }

  function haptic() {
    var shell = root.ClientShell;
    if (shell && typeof shell.hapticSelection === 'function') shell.hapticSelection();
  }

  function go(path) {
    var shell = root.ClientShell;
    if (shell && typeof shell.navigate === 'function') shell.navigate(path);
    else root.location.href = path;
  }

  function afterSave() {
    load(true);
  }

  function openSheet(act) {
    var d = state.data;
    if (!d) return;
    if (act === 'name') {
      if (!root.ClientNameSheet) return;
      haptic();
      root.ClientNameSheet.open({ current: d.name, onSaved: afterSave });
    } else if (act === 'club') {
      if (!root.ClientClubSheet) return;
      haptic();
      root.ClientClubSheet.open({ current: isObject(d.club) ? d.club.name : null, onSaved: afterSave });
    } else if (act === 'rink') {
      haptic();
      if (root.ClientRinkSheet && typeof root.ClientRinkSheet.open === 'function') {
        root.ClientRinkSheet.open({ currentId: isObject(d.home_arena) ? d.home_arena.id : null, onSaved: afterSave });
      } else {
        /* Скрипт шторки не загрузился — выбор катка там, где он и так есть: «Поиск». */
        go('ice');
      }
    }
  }

  mount.addEventListener('click', function (ev) {
    var target = ev.target && ev.target.closest ? ev.target.closest('[data-act], [data-nav]') : null;
    if (!target || !mount.contains(target)) return;
    var act = target.getAttribute('data-act');
    if (act === 'retry') {
      mount.innerHTML = SKELETON;
      mount.setAttribute('aria-busy', 'true');
      state.failed = false;
      load();
      return;
    }
    if (act) {
      ev.preventDefault();
      openSheet(act);
      return;
    }
    var nav = target.getAttribute('data-nav');
    if (nav) {
      ev.preventDefault();
      go(nav);
    }
  });

  var SKELETON = mount.innerHTML;

  root.addEventListener('client-shell:ui-flags', function () {
    if (state.data) paint(state.data);
  });
  root.addEventListener('client-shell:retap', function (ev) {
    if (ev && ev.detail && ev.detail.tab === 'me') load();
  });
  root.addEventListener('pageshow', function (ev) {
    if (ev && ev.persisted) load();
  });
  if (doc.fonts && doc.fonts.ready && typeof doc.fonts.ready.then === 'function') {
    doc.fonts.ready.then(fitName);
  }
  var fitQueued = false;
  root.addEventListener('resize', function () {
    if (fitQueued) return;
    fitQueued = true;
    (root.requestAnimationFrame || setTimeout)(function () {
      fitQueued = false;
      fitName();
    });
  });

  var warm = null;
  try {
    warm = readWarm(root.sessionStorage.getItem(WARM_KEY), Date.now(), profileGuess());
  } catch (e) {
    warm = null;
  }
  if (warm) {
    fontsReady.then(function () {
      /* Свежий ответ или «Не загрузилось» уже на экране — тёплый кэш поверх них не рисуем. */
      if (!state.data && !state.failed) paint(warm);
    });
  }
  load();
})(typeof window !== 'undefined' ? window : globalThis);
