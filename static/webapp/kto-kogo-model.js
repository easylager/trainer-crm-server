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

  /**
   * Очки как в прогнозах FIFA (владелец, 2026-10-19): победитель — 20, разница шайб — 10,
   * шайбы каждой команды — по 10, точный счёт — 50. Считает сервер; здесь только слова.
   */
  var EXACT = 50;
  var RULES = 'Победитель — 20 очков, разница шайб — 10, шайбы каждой команды — по 10. Точный счёт — все 50.';

  /** Как назвать исход моего хода после матча. Итоги бывают 0, 10, 20, 30, 50. */
  function verdict(pointsWon) {
    if (pointsWon === 50) return { head: 'в точку!', sticker: '+50', tone: 'win', tail: 'точный счёт' };
    if (pointsWon === 30) return { head: 'почти в точку', sticker: '+30', tone: 'ok', tail: 'победитель и ещё часть счёта' };
    if (pointsWon === 20) return { head: 'есть победитель', sticker: '+20', tone: 'ok', tail: 'победитель угадан' };
    if (pointsWon === 10) return { head: 'шайбы угаданы', sticker: '+10', tone: 'ok', tail: 'шайбы одной команды' };
    return { head: 'в этот раз мимо', sticker: '0', tone: 'miss', tail: 'в этот раз мимо' };
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

  /** Коротко, что поставил игрок: «3:1» или «ты за Динамо». Пусто без хода. */
  function moveLine(pick, names) {
    if (!pick || !pick.side) return '';
    if (pick.home_score != null && pick.away_score != null) return 'твой счёт ' + pick.home_score + ':' + pick.away_score;
    var team = pick.side === 'away' ? names && names.away : names && names.home;
    return 'ты за' + NBSP + (team || '');
  }

  /**
   * Строка под карточкой, пока итога нет.
   * phase: 'open' — ход ещё можно сменить; 'live' — матч уже начался.
   */
  function stakeLine(pick, names, phase) {
    var live = phase === 'live';
    var move = moveLine(pick, names);
    if (!move) return live ? 'ходы закрыты · этот матч без тебя' : '';
    if (live) return move + ' · ждём сирену';
    // ×2 (TASK-335): ставка не меняется, удваиваются очки — пишем итоговое число.
    if (pick.home_score != null) {
      return 'ход принят · ' + pick.home_score + ':' + pick.away_score + ' · в точку — ' + (pick.doubled ? 100 : 50);
    }
    return 'ход принят · ' + move + (pick.doubled ? ' · очки ×2' : '');
  }

  /**
   * Зачем тапнуть, пока хода нет. Друзья — уже сделанные ходы {home, away: имена}.
   * Очки те же, что в правилах: победитель даёт 20.
   */
  function nudgeLine(friends, names) {
    var home = (friends && friends.home) || [];
    var away = (friends && friends.away) || [];
    var n = home.length + away.length;
    if (!n) return 'без хода очков не будет · победитель — 20';
    if (n === 1) {
      var who = home[0] || away[0];
      var team = home.length ? names && names.home : names && names.away;
      return who + ' уже за' + NBSP + (team || '') + ' · твой ход — 20';
    }
    var first = home[0] || away[0];
    return first + ' и' + NBSP + 'ещё' + NBSP + (n - 1) + ' уже сделали ход · твой — 20';
  }

  /** Подсказка в шторке счёта: этот черновик, не правила целиком. */
  function scoreHint(home, away) {
    if (home === away) return 'В хоккее ничьих нет';
    return home + ':' + away + ' · в точку — 50';
  }

  /** startapp=kk_<КОД> → код лиги или ''. */
  /** Код лиги из ссылки: kk_КОД — приглашение, kkl_/kkr_КОД — кнопки карточек в чате. */
  function inviteCode(startParam) {
    var m = /^kk[lr]?_([A-Za-z0-9]{4,16})$/.exec(String(startParam || '').trim());
    return m ? m[1].toUpperCase() : '';
  }

  /** С какой карточки в чате пришли: 'league' | 'result' | ''. */
  function cardFrom(startParam, fromParam) {
    if (fromParam === 'league' || fromParam === 'result') return fromParam;
    var m = /^kk([lr])(?:_[A-Za-z0-9]{4,16})?$/.exec(String(startParam || '').trim());
    if (!m) return '';
    return m[1] === 'l' ? 'league' : 'result';
  }

  /** Сторона моего хода, если ход — точный счёт, тоже даёт сторону. */
  function pickSide(pick) {
    if (!pick) return '';
    return pick.side || '';
  }

  // ---------- гонка месяца (TASK-334) ----------

  /** Шапка таблицы: месяц и сколько сыграно. До первой гонки — просто «таблица». */
  function raceHead(race) {
    if (!race || !race.monthly) return { title: 'таблица', left: '' };
    var played = race.played || 0;
    var known = race.known || 0;
    var left = '';
    if (known && race.final_match_id && played === known - 1) left = 'остался финал';
    else if (known) left = 'сыграно ' + played + ' из ' + known;
    return { title: race.title, left: left };
  }

  /** Полоса матчей месяца: сыгранные, впереди, последний — финал (если календарь месяца прочитан). */
  function raceSegments(race) {
    if (!race || !race.monthly || !race.known) return [];
    var out = [];
    for (var i = 0; i < Math.min(race.known, 16); i++) {
      if (i < race.played) out.push('played');
      else if (race.final_match_id && i === race.known - 1) out.push('final');
      else out.push('ahead');
    }
    return out;
  }

  /** Синяя строка под подиумом: где ты относительно первого места. */
  function chaseLine(rows) {
    var me = null;
    for (var i = 0; i < (rows || []).length; i++) if (rows[i].is_me) me = rows[i];
    if (!me || !rows.length) return null;
    if (me.rank === 1) {
      if (!me.points) return null;
      var second = rows.filter(function (r) { return !r.is_me; })[0];
      if (!second) return null;
      var lead = me.points - second.points;
      return lead > 0 ? { text: 'Ты первый. Отрыв', num: points(lead) } : { text: 'Первое место делишь', num: '' };
    }
    return { text: 'Ты ' + me.rank + '-й. До первого места', num: points(rows[0].points - me.points) };
  }

  /** Строка под финалом месяца: факт без шансов («Катя впереди на 20»). */
  function leaderNote(leader) {
    if (!leader) return '';
    if (leader.me_leading) return leader.gap ? 'Ты впереди на ' + points(leader.gap) : 'Очков поровну — решит финал';
    return leader.gap ? leader.leader + ' впереди на ' + points(leader.gap) : 'Очков поровну — решит финал';
  }

  function joinNames(names) {
    if (names.length < 2) return names[0] || '';
    return names.slice(0, -1).join(', ') + ' и ' + names[names.length - 1];
  }

  /** Итоги месяца: заголовок и строка под ним. */
  function monthHead(res) {
    if (res.won) return res.title + ' твой';
    if (!res.winners || !res.winners.length) return res.title + ' без короны';
    return 'корона — ' + joinNames(res.winners);
  }

  function monthLine(res) {
    var where = res.league ? 'в «' + res.league.name + '»' : 'в общей таблице';
    if (res.won) return 'Первое место ' + where + NBSP + '· ' + points(res.points);
    if (res.rank == null) return 'В этом месяце без твоих ходов ' + where;
    if (!res.gap) return 'Ты ' + res.rank + '-й ' + where;
    return 'Ты ' + res.rank + '-й ' + where + ', до короны не хватило ' + points(res.gap);
  }

  /** Вступил в середине месяца — сколько матчей осталось. */
  function remainingLine(race) {
    if (!race || !race.monthly) return '';
    var n = Math.max(0, (race.known || 0) - (race.played || 0));
    var head = n ? 'В этом месяце ещё ' + n + ' ' + plural(n, 'матч', 'матча', 'матчей') + '. ' : '';
    return head + 'Очки в лиге — с ближайшего матча, с 1-го числа все с нуля.';
  }

  // ---------- волна 2 (TASK-335) ----------

  var DINAMO = 'Динамо-Минск';

  /** Очки хода с ×2: сервер хранит базовые (по ним «в точку»), наклейка показывает итог. */
  function totalPoints(pick) {
    if (!pick || pick.points == null) return null;
    return pick.doubled ? pick.points * 2 : pick.points;
  }

  /** Расклад по друзьям со стартом матча: «6 из 8 за Динамо-Минск». Меньше двух ходов — молчим. */
  function crowd(m, moves, mine) {
    var sides = (moves || []).map(function (x) { return x.side; });
    var my = pickSide(mine);
    if (my) sides.push(my);
    if (sides.length < 2) return null;
    var home = sides.filter(function (x) { return x === 'home'; }).length;
    var away = sides.length - home;
    var side = m.home.name === DINAMO ? 'home' : m.away.name === DINAMO ? 'away' : home >= away ? 'home' : 'away';
    var n = side === 'home' ? home : away;
    return { text: n + ' из ' + sides.length + ' за ' + m[side].name, home: home, away: away };
  }

  /** Строка хода друга в списке «счета открыты». */
  function friendMove(x, names) {
    if (x.home_score != null && x.away_score != null) return x.home_score + ':' + x.away_score;
    return 'без счёта';
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
    EXACT: EXACT,
    RULES: RULES,
    decidedLabel: decidedLabel,
    clampGoals: clampGoals,
    scoreError: scoreError,
    moveLine: moveLine,
    stakeLine: stakeLine,
    scoreHint: scoreHint,
    nudgeLine: nudgeLine,
    inviteCode: inviteCode,
    cardFrom: cardFrom,
    pickSide: pickSide,
    raceHead: raceHead,
    raceSegments: raceSegments,
    chaseLine: chaseLine,
    leaderNote: leaderNote,
    monthHead: monthHead,
    monthLine: monthLine,
    remainingLine: remainingLine,
    totalPoints: totalPoints,
    crowd: crowd,
    friendMove: friendMove,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.KtoKogoModel = api;
})(typeof window !== 'undefined' ? window : globalThis);
