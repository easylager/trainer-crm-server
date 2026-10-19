/**
 * TASK-304: страница домашнего матча — тексты без DOM.
 * Данные — GET /api/webapp/client/hockey/matches/{id}/event (см. src/application/hockey_event.py).
 */
(function (global) {
  'use strict';

  var TZ = 'Europe/Minsk';
  var NBSP = ' ';
  var WD = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  var EXACT = 50;

  function parts(d) {
    var f = new Intl.DateTimeFormat('ru-RU', {
      timeZone: TZ, year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short',
    });
    var o = {};
    f.formatToParts(d).forEach(function (p) { o[p.type] = p.value; });
    var wd = { 'вс': 0, 'пн': 1, 'вт': 2, 'ср': 3, 'чт': 4, 'пт': 5, 'сб': 6 }[String(o.weekday || '').replace('.', '').toLowerCase()];
    return { y: +o.year, m: +o.month, d: +o.day, hh: o.hour, mm: o.minute, wd: wd == null ? new Date(d).getUTCDay() : wd };
  }

  function dayDiff(a, b) {
    return Math.round((Date.UTC(a.y, a.m - 1, a.d) - Date.UTC(b.y, b.m - 1, b.d)) / 86400000);
  }

  /** «пт, 23 октября · 19:30» — строка под названием матча. */
  function heroWhen(iso) {
    var p = parts(new Date(iso));
    return WD[p.wd] + ', ' + p.d + NBSP + MONTHS[p.m - 1] + ' · ' + p.hh + ':' + p.mm;
  }

  /** Плашка в шапке: «через 3 дня» → «сегодня» → «идёт» → «финал». */
  function status(match, now) {
    if (match.status === 'cancelled') return { text: 'матч отменён', live: false };
    if (match.result && match.result.home_score != null) return { text: 'финал', live: false };
    var start = new Date(match.starts_at);
    var n = now || new Date();
    if (start <= n) return { text: 'идёт', live: true };
    var diff = dayDiff(parts(start), parts(n));
    if (diff <= 0) return { text: 'сегодня', live: false };
    if (diff === 1) return { text: 'завтра', live: false };
    return { text: 'через ' + diff + NBSP + plural(diff, 'день', 'дня', 'дней'), live: false };
  }

  function plural(n, one, few, many) {
    var a = Math.abs(n) % 100;
    var b = a % 10;
    if (a > 10 && a < 20) return many;
    if (b > 1 && b < 5) return few;
    if (b === 1) return one;
    return many;
  }

  /** «Аня», «Аня и Петя», «Аня, Петя и Дима». */
  function joinNames(names) {
    if (names.length <= 1) return names.join('');
    return names.slice(0, -1).join(', ') + ' и' + NBSP + names[names.length - 1];
  }

  /**
   * «Кто из ваших». Пусто — блока нет: сервер не отдаёт список из одного себя.
   * Себя называем «Ты» и ставим первым — так человек сразу видит свой ответ среди друзей.
   */
  function who(people) {
    var list = people || [];
    if (!list.length) return null;
    var going = [];
    var home = [];
    list.forEach(function (p) {
      var name = p.is_me ? 'Ты' : p.name;
      var bucket = p.status === 'going' ? going : p.status === 'maybe' ? home : null;
      if (!bucket) return;
      if (p.is_me) bucket.unshift(name);
      else bucket.push(name);
    });
    if (!going.length && !home.length) return null;
    var line = [];
    if (going.length) line.push(joinNames(going) + ' ' + verb(going, 'идёшь', 'идёт', 'идут'));
    if (home.length) line.push(joinNames(home) + ' ' + verb(home, 'смотришь дома', 'смотрит дома', 'смотрят дома'));
    var count = going.length ? going.length + NBSP + (going.length === 1 ? 'идёт' : 'идут') : home.length + NBSP + 'дома';
    return {
      line: line.join(' · '),
      count: count,
      initials: list.filter(function (p) { return p.status !== 'cant'; }).sort(function (a, b) {
        return (b.is_me ? 1 : 0) - (a.is_me ? 1 : 0);
      }).slice(0, 5).map(function (p) {
        return { letter: p.is_me ? 'Я' : String(p.name || '?').charAt(0).toUpperCase(), me: !!p.is_me };
      }),
    };
  }

  function verb(names, you, one, many) {
    if (names.length > 1) return many;
    return names[0] === 'Ты' ? you : one;
  }

  function teamName(match, side) {
    var t = side === 'away' ? match.away : match.home;
    return (t && t.name) || '';
  }

  function verdict(points) {
    if (points === EXACT) return 'В точку! +50';
    if (points === 30) return 'Почти в точку · +30';
    if (points === 20) return 'Есть победитель · +20';
    if (points === 10) return 'Шайбы угаданы · +10';
    return 'В этот раз мимо';
  }

  function moveText(pick, match) {
    if (!pick || !pick.side) return '';
    if (pick.home_score != null && pick.away_score != null) return 'твой счёт ' + pick.home_score + ':' + pick.away_score;
    return 'ты за' + NBSP + teamName(match, pick.side);
  }

  function cap(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  }

  /**
   * Строка «КТО КОГО?» на ивенте: одна, небольшая, ведёт в игру (решение владельца 2026-10-20).
   * Имена друзей — только если они уже сделали ход; иначе строка без имён.
   */
  function kkRow(ev) {
    var kk = ev.kk || {};
    var m = ev.match;
    var names = kk.company_names || [];
    // Без рода и падежа: «Уже с ходом: Аня и Петя», а не «Аня сделала» или «вместе с Аней».
    var friends = names.length ? 'Уже с' + NBSP + 'ходом: ' + joinNames(names) : '';
    var pick = kk.my_pick;
    var start = parts(new Date(m.starts_at));
    if (kk.phase === 'open') {
      return {
        title: 'Угадай счёт',
        sub: friends ? friends + ' · точный — 50' : 'Точный счёт — 50 очков',
        href: 'kto-kogo',
      };
    }
    if (kk.phase === 'picked') {
      return { title: cap(moveText(pick, m)), sub: 'Можно изменить до ' + start.hh + ':' + start.mm, href: 'kto-kogo' };
    }
    if (kk.phase === 'live') {
      var mine = moveText(pick, m);
      return {
        title: mine ? 'Ходы закрыты · ' + mine : 'Ходы закрыты',
        sub: names.length ? 'Ходы компании: ' + joinNames(names) : 'Итог — после финальной сирены',
        href: 'kto-kogo',
      };
    }
    // final
    var r = m.result || {};
    if (!pick) {
      return { title: 'Итог ' + r.home_score + ':' + r.away_score, sub: 'Таблица и следующий матч', href: 'kto-kogo' };
    }
    var pts = kk.points == null ? null : Number(kk.points);
    if (pts == null) return { title: 'Считаем очки', sub: cap(moveText(pick, m)), href: 'kto-kogo' };
    return {
      title: verdict(pts),
      sub: pts >= 20 ? 'Похвастаться в чате' : cap(moveText(pick, m)),
      href: 'kto-kogo?reveal=' + m.id,
    };
  }

  /** Подпись кнопки ответа и тост. */
  var ANSWERS = [
    { status: 'going', label: 'Иду', toast: 'Записали: идёшь' },
    { status: 'maybe', label: 'Смотрю дома', toast: 'Записали: смотришь дома' },
    { status: 'cant', label: 'Не смогу', toast: 'Записали: не сможешь' },
  ];

  var api = {
    heroWhen: heroWhen,
    status: status,
    who: who,
    kkRow: kkRow,
    joinNames: joinNames,
    ANSWERS: ANSWERS,
  };
  global.ClientMatchModel = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
