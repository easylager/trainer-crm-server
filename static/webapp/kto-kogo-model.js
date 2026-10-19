/**
 * «Кто кого» — чистые функции экрана (TASK-299): даты, цвета пары команд, тексты.
 * Без DOM и сети: их проверяют tests/js/kto-kogo-model.test.js.
 */
(function (global) {
  'use strict';

  var TZ = 'Europe/Minsk';
  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  var WEEKDAY_IN = ['в воскресенье', 'в понедельник', 'во вторник', 'в среду', 'в четверг', 'в пятницу', 'в субботу'];
  var WEEKDAY_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  var NEUTRAL = '#5D7285';
  var NBSP = ' ';

  /** Части даты в минском времени — у игроков не всегда минский пояс в телефоне. */
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
    var wd = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[parts.weekday];
    return {
      y: Number(parts.year),
      m: Number(parts.month),
      d: Number(parts.day),
      hh: parts.hour,
      mm: parts.minute,
      wd: wd,
    };
  }

  function dayIndex(p) {
    return Date.UTC(p.y, p.m - 1, p.d) / 86400000;
  }

  function time(p) {
    // 9:00, а не 09:00.
    return String(Number(p.hh)) + ':' + p.mm;
  }

  /** «сегодня, 19:30» · «завтра, 17:00» · «в четверг, 19:30» · «22 октября, 19:30». */
  function whenLabel(iso, now) {
    var p = minskParts(new Date(iso));
    var n = minskParts(now || new Date());
    var diff = dayIndex(p) - dayIndex(n);
    var day;
    if (diff === 0) day = 'сегодня';
    else if (diff === 1) day = 'завтра';
    else if (diff === -1) day = 'вчера';
    else if (diff > 1 && diff < 7) day = WEEKDAY_IN[p.wd];
    else day = p.d + NBSP + MONTHS[p.m - 1];
    return day + ', ' + time(p);
  }

  /** Надпись над карточкой: «ЧТ, 22 ОКТЯБРЯ · 19:30» (капсом рисует CSS). */
  function kicker(iso) {
    var p = minskParts(new Date(iso));
    return WEEKDAY_SHORT[p.wd] + ', ' + p.d + NBSP + MONTHS[p.m - 1] + ' · ' + time(p);
  }

  function hexToRgb(hex) {
    var h = String(hex || '').replace('#', '');
    if (h.length === 3) h = h.replace(/(.)/g, '$1$1');
    var n = parseInt(h, 16);
    if (h.length !== 6 || isNaN(n)) return null;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  /** Взвешенное RGB-расстояние («redmean») — дёшево и достаточно, чтобы поймать «синий против синего». */
  function colorDistance(a, b) {
    var x = hexToRgb(a);
    var y = hexToRgb(b);
    if (!x || !y) return Infinity;
    var r = (x[0] + y[0]) / 2;
    var dr = x[0] - y[0];
    var dg = x[1] - y[1];
    var db = x[2] - y[2];
    return Math.sqrt((2 + r / 256) * dr * dr + 4 * dg * dg + (2 + (255 - r) / 256) * db * db);
  }

  var CLOSE = 120;

  /**
   * Цвета половинок. У Динамо, Барыса, Сочи, Торпедо — близкие тёмно-синие: рядом они сливаются.
   * Тогда хозяева в своём цвете, гости — нейтральный тёмно-серый. Клубный цвет не подменяем чужим.
   */
  function pairColors(home, away) {
    var h = (home && home.color) || NEUTRAL;
    var a = (away && away.color) || NEUTRAL;
    if (colorDistance(h, a) < CLOSE) {
      // Если и нейтральный рядом с хозяевами — всё равно лучше, чем два одинаковых синих.
      a = colorDistance(h, NEUTRAL) < CLOSE ? '#3B4252' : NEUTRAL;
    }
    return { home: h, away: a };
  }

  function plural(n, one, few, many) {
    var m10 = n % 10;
    var m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  /** Подпись под половинкой: кто из друзей за эту команду. */
  function fansLine(names, mine) {
    var list = (names || []).slice();
    if (mine) {
      if (!list.length) return 'ты первый';
      if (list.length === 1) return 'ты и' + NBSP + list[0];
      return 'ты и' + NBSP + 'ещё' + NBSP + list.length;
    }
    if (!list.length) return '';
    if (list.length <= 2) return list.join(', ');
    return list[0] + ' и' + NBSP + 'ещё' + NBSP + (list.length - 1);
  }

  function points(n) {
    return n + NBSP + plural(n, 'очко', 'очка', 'очков');
  }

  /** Как назвать исход моего хода после матча. */
  function verdict(pointsWon) {
    if (pointsWon === 5) return { head: 'в точку!', sticker: '+5', tone: 'win' };
    if (pointsWon === 1) return { head: 'есть победитель', sticker: '+1', tone: 'ok' };
    return { head: 'в этот раз мимо', sticker: '0', tone: 'miss' };
  }

  function decidedLabel(d) {
    if (d === 'ot') return 'в' + NBSP + 'овертайме';
    if (d === 'so') return 'по' + NBSP + 'буллитам';
    return 'в' + NBSP + 'основное время';
  }

  /** Черновик счёта в шторке: 0…20, ничьих нет. */
  function clampGoals(n) {
    n = Number(n) || 0;
    return Math.max(0, Math.min(20, Math.round(n)));
  }

  function scoreError(home, away) {
    if (home === away) return 'В хоккее ничьих нет';
    return '';
  }

  /** startapp=kk_<КОД> → код лиги или ''. */
  function inviteCode(startParam) {
    var m = /^kk_([A-Za-z0-9]{4,16})$/.exec(String(startParam || '').trim());
    return m ? m[1].toUpperCase() : '';
  }

  /** Сторона моего хода, если ход — точный счёт, тоже даёт сторону. */
  function pickSide(pick) {
    if (!pick) return '';
    return pick.side || '';
  }

  var api = {
    NEUTRAL: NEUTRAL,
    whenLabel: whenLabel,
    kicker: kicker,
    colorDistance: colorDistance,
    pairColors: pairColors,
    plural: plural,
    fansLine: fansLine,
    points: points,
    verdict: verdict,
    decidedLabel: decidedLabel,
    clampGoals: clampGoals,
    scoreError: scoreError,
    inviteCode: inviteCode,
    pickSide: pickSide,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.KtoKogoModel = api;
})(typeof window !== 'undefined' ? window : globalThis);
