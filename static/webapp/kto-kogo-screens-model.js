/**
 * «Кто кого», зимняя модель (TASK-334 S5): чистые функции экранов — срезы «команда × период», «Если угадаешь»,
 * живые очки, дуэли, козырь недели, лиги на набор команд. Без DOM и сети: их проверяет
 * tests/js/kto-kogo-screens-model.test.js. Слова: угадай, ход, дуэль, корона. Не «ставка», не «прогноз».
 * Тексты нейтральны по роду: мы не знаем, «он» или «она» играет.
 */
(function (global) {
  'use strict';

  var Base = global.KtoKogoModel || (typeof require !== 'undefined' ? require('./kto-kogo-model.js') : null);
  var NBSP = '\u00a0';
  var FIRST_MONTH = '2026-11';
  var WEEKDAY_UP = ['ВОСКРЕСЕНЬЕ', 'ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА'];
  var WEEKDAY_ON = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'];
  var MONTH_NOM = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
  var WEEKDAY_ON_IN = ['в воскресенье', 'в понедельник', 'во вторник', 'в среду', 'в четверг', 'в пятницу', 'в субботу'];

  function pad(n) {
    return n < 10 ? '0' + n : String(n);
  }

  var clubName = Base.clubName;
  var clubGen = Base.clubGen;

  var SHORT = { 'Динамо-Минск': 'Динамо', 'Динамо-Молодечно': 'Молодечно', 'Металлург Жлобин': 'Металлург', 'Локомотив Орша': 'Локомотив' };

  /** Короткое имя клуба для плитки: четыре в ряд на 390 px. */
  function clubShort(name) {
    return SHORT[name] || clubName(name);
  }

  /** «сезон 2026/27» по дате: сезон идёт с августа. */
  function seasonTitleFor(nowIso) {
    var p = Base.minskParts(new Date(nowIso));
    var y = p.m >= 8 ? p.y : p.y - 1;
    return 'сезон ' + y + '/' + pad((y + 1) % 100);
  }

  function cap(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  }

  // ---------- даты (Минск) ----------

  function dayKey(iso) {
    var p = Base.minskParts(new Date(iso));
    return p.y + '-' + pad(p.m) + '-' + pad(p.d);
  }

  /** Понедельник недели матча по Минску: неделя козыря — пн–вс. Тот же ключ, что `week_start` у сервера. */
  function weekKey(iso) {
    var p = Base.minskParts(new Date(iso));
    var back = (p.wd + 6) % 7;
    var d = new Date(Date.UTC(p.y, p.m - 1, p.d - back));
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
  }

  function monthKey(iso) {
    var p = Base.minskParts(new Date(iso));
    return p.y + '-' + pad(p.m);
  }

  function dateLabel(iso) {
    var p = Base.minskParts(new Date(iso));
    return p.d + NBSP + Base.MONTHS[p.m - 1];
  }

  /** Последний день включительно: срок лиги и периоды у сервера заканчиваются «не включая» полночь. */
  function endLabel(iso) {
    return dateLabel(new Date(new Date(iso).getTime() - 1).toISOString());
  }

  function timeOnly(iso) {
    return Base.time(Base.minskParts(new Date(iso)));
  }

  /** Время закрытия ходов по Минску: «19:29» для старта в 19:30. */
  function closeTime(iso) {
    return Base.time(Base.minskParts(Base.closesAt(iso)));
  }

  /** Диапазон дат: «3–30 ноября» в одном месяце, «28 ноября – 3 декабря» в двух. Конец — последний день включительно. */
  function rangeLabel(startIso, endIso) {
    var a = Base.minskParts(new Date(startIso));
    var b = Base.minskParts(new Date(new Date(endIso).getTime() - 1));
    if (a.m === b.m && a.y === b.y) return a.d + '–' + b.d + NBSP + Base.MONTHS[b.m - 1];
    return a.d + NBSP + Base.MONTHS[a.m - 1] + NBSP + '–' + NBSP + b.d + NBSP + Base.MONTHS[b.m - 1];
  }

  function monthEndLabel(key) {
    var m = /^(\d{4})-(\d{2})$/.exec(key || '');
    if (!m) return '';
    var last = new Date(Date.UTC(Number(m[1]), Number(m[2]), 0)).getUTCDate();
    return last + NBSP + Base.MONTHS[Number(m[2]) - 1];
  }

  // ---------- подписи срезов ----------

  function periodShort(title) {
    return /^сезон/.test(title || '') ? 'сезон' : title || '';
  }

  /** «Юность · ноябрь», «Все · сезон». */
  function sliceLabel(club, periodTitle) {
    return (club ? clubName(club) : 'Все') + ' · ' + periodShort(periodTitle);
  }

  /** Будущее место: без места — «пока без места». */
  function becomeText(n) {
    return n == null ? 'пока без места' : 'будешь на ' + n + '-м месте';
  }

  // ---------- «Если угадаешь» ----------

  /** Строки блока по ответу /stakes. Иконка: crown | up | duel. Места условные — «оценка по текущей таблице». */
  function stakeLines(items) {
    return (items || []).map(function (s) {
      var label = s.kind === 'league' ? 'Лига «' + s.league_name + '»' : sliceLabel(s.club, s.period_title);
      var move = s.rank_now == null
        ? becomeText(s.rank_if)
        : s.rank_now === s.rank_if
          ? s.rank_now + '-е место'
          : s.rank_now + '-е → около ' + s.rank_if + '-го';
      return {
        icon: s.crown ? 'crown' : s.kind === 'league' ? 'duel' : 'up',
        gold: !!s.crown,
        text: label + ': ' + move + (s.crown ? ' · корона' : ''),
      };
    });
  }

  var STAKES_NOTE = 'Это оценка: другие игроки ещё могут поменять ход.';

  function stakesEmpty(hasPick) {
    return hasPick ? 'Здесь угаданный победитель места не меняет — очки всё равно копятся.' : 'Сделай ход — покажем, где ты поднимешься.';
  }

  // ---------- очки и живой счёт ----------

  /** Как `pick_points` на сервере: победитель 20, разница 10, шайбы каждой — по 10, точный — все 50. */
  function pickPoints(pick, rh, ra) {
    var winner = rh > ra ? 'home' : 'away';
    var pts = pick.side === winner ? 20 : 0;
    if (pick.home_score == null || pick.away_score == null) return pts;
    if (pick.home_score - pick.away_score === rh - ra) pts += 10;
    if (pick.home_score === rh) pts += 10;
    if (pick.away_score === ra) pts += 10;
    return pts;
  }

  /** Очки, если матч закончится как сейчас; ничья на табло — победителя ещё нет. */
  function livePoints(pick, live) {
    if (!pick || !live || live.home_score === live.away_score) return null;
    return pickPoints(pick, live.home_score, live.away_score) * (pick.doubled ? 2 : 1);
  }

  /** Из чего сложились очки сейчас: «победитель, разница, шайбы хозяев». */
  function liveParts(pick, live) {
    if (!pick || !live || live.home_score === live.away_score) return [];
    var rh = live.home_score;
    var ra = live.away_score;
    if (pick.home_score === rh && pick.away_score === ra) return ['точный счёт'];
    var parts = [];
    if (pick.side === (rh > ra ? 'home' : 'away')) parts.push('победитель');
    if (pick.home_score != null && pick.away_score != null) {
      if (pick.home_score - pick.away_score === rh - ra) parts.push('разница');
      if (pick.home_score === rh) parts.push('шайбы хозяев');
      if (pick.away_score === ra) parts.push('шайбы гостей');
    }
    return parts;
  }

  /**
   * Что сейчас с ходом, словами и без очков: числа очков — только после финальной сирены.
   * names — {home, away} коротко. «Пока сходится: Динамо впереди. До «в точку» не хватает одной шайбы.»
   */
  function liveWhy(pick, live, names) {
    if (!live) return 'Счёт появится здесь, как только будет доступен';
    if (live.home_score === live.away_score) return 'Пока ничья — победителя ещё нет';
    var leader = live.home_score > live.away_score ? 'home' : 'away';
    var lead = names && names[leader] ? names[leader] : leader === 'home' ? 'хозяева' : 'гости';
    if (!pick || pick.side !== leader) return 'Пока мимо — до сирены всё может поменяться';
    var head = 'Пока сходится: ' + lead + ' впереди.';
    if (pick.home_score == null || pick.away_score == null) return head;
    // Шайбы не вычитаются: если на табло уже больше, чем в ходе, «в точку» не выйдет.
    if (live.home_score > pick.home_score || live.away_score > pick.away_score) return head + ' «В точку» уже не выйдет.';
    var miss = pick.home_score - live.home_score + (pick.away_score - live.away_score);
    if (!miss) return head + ' Счёт сейчас — «в точку».';
    return head + ' До «в точку» не хватает ' + (miss === 1 ? 'одной шайбы' : miss + NBSP + Base.plural(miss, 'шайба', 'шайбы', 'шайб')) + '.';
  }

  /** Время опроса счёта: «счёт на 19:42». */
  function liveStamp(live) {
    return live && live.updated_at ? 'счёт на ' + timeOnly(live.updated_at) : '';
  }

  /** Что такое дуэль: hockey_screens._DUELS — очки за один матч (с козырем) против друга из общей лиги; в счёте только победы и поражения. */
  var DUEL_HINT = 'Дуэль — у\u00a0кого из\u00a0вас двоих больше очков за\u00a0матч. Соперники — друзья из\u00a0твоих лиг.';

  /** Дуэль на живом счёте: мои очки против очков друга по тому же табло. */
  function duelLive(mine, friend, live) {
    var a = livePoints(mine, live);
    var b = livePoints(friend, live);
    if (a == null || b == null) return { me: a, they: b, state: 'even', label: 'РОВНО' };
    if (a > b) return { me: a, they: b, state: 'lead', label: 'ВЕДЁШЬ' };
    if (a < b) return { me: a, they: b, state: 'trail', label: 'ОТСТАЁШЬ' };
    return { me: a, they: b, state: 'even', label: 'РОВНО' };
  }

  /** Метка дуэли до старта: за разных — дуэль на победителя, за одну команду — на счёт. */
  function duelPill(mySide, theirSide) {
    return mySide && theirSide && mySide !== theirSide ? { label: 'ДУЭЛЬ', hot: true } : { label: 'ДУЭЛЬ НА СЧЁТ', hot: false };
  }

  /** Итог дуэли по очкам хода: победа, ничья, проигрыш. */
  function duelFinal(myPts, theirPts) {
    if (myPts == null || theirPts == null) return null;
    if (myPts > theirPts) return 'win';
    if (myPts < theirPts) return 'lose';
    return 'tie';
  }

  var CROWD_NAMED = 3;

  function firstWord(name) {
    return String(name || '').trim().split(/\s+/)[0] || '';
  }

  function initialOf(name) {
    return Base.firstChars(firstWord(name), 1).toUpperCase() || '?';
  }

  /**
   * Кто за эту команду, людьми, без процентов. Сначала «Я», потом друзья из лиг (m.friend_moves — приходят со стартом),
   * остальные — числом «+N» из m.sides. Подпись: «Ты, Аня, Петя и ещё 12».
   * Возвращает {faces: [{me, initial, name}], more, caption, total}.
   */
  function crowdPeople(m, side) {
    var total = (m.sides && m.sides[side]) || 0;
    var named = [];
    if (m.my_pick && m.my_pick.side === side) named.push({ me: true, initial: 'Я', name: 'Ты' });
    (m.friend_moves || []).forEach(function (f) {
      if (f.side === side && named.length < CROWD_NAMED) named.push({ me: false, initial: initialOf(f.display_name), name: firstWord(f.display_name) });
    });
    total = Math.max(total, named.length);
    var more = total - named.length;
    var caption;
    if (!total) caption = 'Пока никого';
    else if (!named.length) caption = total + NBSP + Base.plural(total, 'игрок', 'игрока', 'игроков');
    else if (more > 0) caption = named.map(function (x) { return x.name; }).join(', ') + ' и' + NBSP + 'ещё' + NBSP + more;
    else if (named.length === 1) caption = named[0].name === 'Ты' ? 'Пока только ты' : named[0].name;
    else caption = named.slice(0, -1).map(function (x) { return x.name; }).join(', ') + ' и' + NBSP + named[named.length - 1].name;
    return { faces: named, more: more, caption: caption, total: total };
  }

  var CROWD_NOTE = 'Сначала — друзья из твоих лиг. Остальные — числом.';

  // ---------- козырь недели ----------

  /**
   * Состояние козыря на матче. doubles — ответ /matches: недели с козырем {week_start, match_id, locked}.
   * kind: nopick | on | free | other | locked | na.
   */
  function trumpLabel(on) {
    return on ? 'Козырь здесь' : 'Козырь';
  }

  /** Понедельник перед неделей матча: с него козырь на эту неделю уже можно ставить («weeks_ahead=1»). */
  function trumpOpensLabel(weekStart) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(weekStart || '');
    if (!m) return '';
    var d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]) - 7));
    return d.getUTCDate() + NBSP + Base.MONTHS[d.getUTCMonth()];
  }

  function trumpState(m, doubles, nowIso) {
    var mine = m.my_pick;
    if (!mine) return { kind: 'nopick', label: trumpLabel(false), note: 'сначала тапни за команду', on: false, usable: false };
    var wk = weekKey(m.starts_at);
    if (mine.doubled) return { kind: 'on', label: trumpLabel(true), note: 'тапни ещё раз, чтобы снять', on: true, usable: true };
    var d = (doubles || []).filter(function (x) { return x.week_start === wk; })[0];
    if (!d) return { kind: 'na', label: trumpLabel(false), note: 'козырь откроется ' + trumpOpensLabel(wk), on: false, usable: false };
    if (d.match_id && d.locked) return { kind: 'locked', label: trumpLabel(false), note: 'козырь этой недели уже сыгран', on: false, usable: false };
    if (d.match_id && d.match_id !== m.id) return { kind: 'other', label: trumpLabel(false), note: 'стоит на другом матче недели — тап перенесёт сюда', on: false, usable: true };
    return { kind: 'free', label: trumpLabel(false), note: 'один на неделю: очки за этот матч удвоятся', on: false, usable: true };
  }

  /**
   * Одна строка под кнопкой козыря — по состоянию. Козырь недели один; пока его матч не начался, он переносится
   * (set_double в hockey_game.py: перенос запрещён только когда матч с козырем уже стартовал).
   */
  function trumpHint(m, doubles, matches, nowIso) {
    var st = trumpState(m, doubles, nowIso);
    if (st.kind !== 'other') return st.note.charAt(0).toUpperCase() + st.note.slice(1) + '.';
    var wk = weekKey(m.starts_at);
    var d = (doubles || []).filter(function (x) { return x.week_start === wk; })[0];
    var other = (matches || []).filter(function (x) { return x.id === d.match_id; })[0];
    var where = other ? 'на матче ' + clubShort(other.home.name) + ' — ' + clubShort(other.away.name) : 'на другом матче';
    // Перенос живёт ровно пока открыт ход на тот матч — те же 60 секунд до его старта.
    var until = other ? ' до ' + closeTime(other.starts_at) : ' до начала его матча';
    return 'Козырь этой недели стоит ' + where + '. Перенести сюда можно' + until + '.';
  }

  /** Подпись хода до матча — без чисел очков: «Тап за команду — и ход сделан». */
  function pointsLine(pick) {
    return pick ? 'Твой ход принят' : 'Тап за команду — и ход сделан';
  }

  /** «Твой ход: 3:2» / «Твой ход: за Динамо-Минск». */
  function questionLine(pick, teamName) {
    if (!pick) return 'Кто победит?';
    if (pick.home_score != null) return 'Твой ход: ' + pick.home_score + ':' + pick.away_score;
    return 'Твой ход: за' + NBSP + teamName;
  }

  /** «Твои места прямо сейчас»: места по таблице до матча; если так закончится и победитель угадан — с выигрышем. */
  function livePlaces(items, winningNow) {
    return (items || []).map(function (x) {
      var label = x.kind === 'league' ? 'Лига «' + x.league_name + '»' : sliceLabel(x.club, x.period_title);
      var from = x.rank_now;
      var to = winningNow && x.rank_if != null ? x.rank_if : from;
      return { label: label, from: from == null ? '—' : String(from), to: to == null ? '—' : String(to), tone: from == null || to < from ? 'up' : 'same', crown: !!x.crown && winningNow };
    });
  }

  // ---------- матчи дня ----------

  var WEEKDAY_SHORT_UP = ['ВС', 'ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ'];
  var LEAGUE_UP = { khl: 'КХЛ', extraliga: 'ЭКСТРАЛИГА' };

  function leagueUp(m) {
    return m.league === 'extraliga' ? LEAGUE_UP.extraliga : LEAGUE_UP.khl;
  }

  /** «СЕГОДНЯ, ВТ 3 НОЯБРЯ» · «ЗАВТРА, СР 4 НОЯБРЯ» · «ЧТ 5 НОЯБРЯ». */
  function dayLabelUp(iso, now) {
    var p = Base.minskParts(new Date(iso));
    var diff = Base.dayIndex(p) - Base.dayIndex(Base.minskParts(now || new Date()));
    var date = WEEKDAY_SHORT_UP[p.wd] + ' ' + p.d + ' ' + Base.MONTHS[p.m - 1].toUpperCase();
    return (diff === 0 ? 'СЕГОДНЯ, ' : diff === 1 ? 'ЗАВТРА, ' : '') + date;
  }

  /**
   * Ближайший день с открытым матчем и все матчи этого дня; null — открытых матчей нет.
   * exceptId — матч, который уже показан в блоке «Твоя команда»: из дня он выпадает, а если он был
   * единственным открытым, день считается по следующему матчу.
   */
  function dayMatches(list, now, exceptId) {
    var skip = Array.isArray(exceptId) ? exceptId : [exceptId];
    var rest = (list || []).filter(function (m) { return skip.indexOf(m.id) < 0; });
    var open = rest.filter(function (m) { return m.open; }).sort(function (a, b) { return a.starts_at < b.starts_at ? -1 : 1; });
    if (!open.length) return null;
    var first = dayKey(open[0].starts_at);
    var items = rest
      .filter(function (m) { return m.status !== 'cancelled' && dayKey(m.starts_at) === first; })
      .sort(function (a, b) { return a.starts_at < b.starts_at ? -1 : a.starts_at > b.starts_at ? 1 : a.id - b.id; });
    var openItems = items.filter(function (m) { return m.open; });
    var made = openItems.filter(function (m) { return m.my_pick; }).length;
    var wd = Base.minskParts(new Date(open[0].starts_at)).wd;
    var today = first === dayKey((now || new Date()).toISOString());
    var leagues = {};
    items.forEach(function (m) { leagues[m.league === 'extraliga' ? 'extraliga' : 'khl'] = true; });
    var names = Object.keys(leagues);
    return {
      day: first,
      today: today,
      wd: wd,
      items: items,
      total: openItems.length,
      made: made,
      mixed: names.length > 1,
      heading: (names.length > 1 ? 'МАТЧИ' : LEAGUE_UP[names[0]]) + ' · ' + dayLabelUp(open[0].starts_at, now),
    };
  }

  // ---------- хаб: «Твоя команда» ----------

  /**
   * Матч для большой карточки хаба. С клубом — ближайший открытый матч клуба, дома или в гостях.
   * Без клуба («Все») — матч дня: ближайший открытый матч Динамо, иначе первый открытый. Нет матча — null.
   */
  function heroMatch(list, club, now) {
    var open = (list || []).filter(function (m) { return m.open && m.status !== 'cancelled'; }).sort(function (a, b) { return a.starts_at < b.starts_at ? -1 : a.starts_at > b.starts_at ? 1 : a.id - b.id; });
    if (club) {
      var own = open.filter(function (m) { return m.home_team === club || m.away_team === club; })[0];
      return own ? { match: own, tag: 'ТВОЯ КОМАНДА' } : null;
    }
    var dinamo = open.filter(function (m) { return m.home_team === Base.DINAMO || m.away_team === Base.DINAMO; })[0];
    var pick = dinamo || open[0];
    return pick ? { match: pick, tag: 'МАТЧ ДНЯ' } : null;
  }

  /** «ЧТ 5 НОЯБРЯ · 19:30 · КХЛ · МИНСК-АРЕНА». */
  function heroMeta(m) {
    var p = Base.minskParts(new Date(m.starts_at));
    var place = m.arena || m.city || '';
    return [WEEKDAY_SHORT_UP[p.wd] + ' ' + p.d + ' ' + Base.MONTHS[p.m - 1].toUpperCase(), Base.time(p), leagueUp(m), place.toUpperCase()].filter(Boolean).join(' · ');
  }

  /** «Можно менять в четверг до 19:29»: время закрытия ходов, а не старта. */
  function changeUntil(iso, now) {
    var p = Base.minskParts(Base.closesAt(iso));
    var diff = Base.dayIndex(p) - Base.dayIndex(Base.minskParts(now || new Date()));
    var day = diff === 0 ? 'сегодня' : diff === 1 ? 'завтра' : diff > 1 && diff < 7 ? WEEKDAY_ON_IN[p.wd] : p.d + NBSP + Base.MONTHS[p.m - 1];
    return 'Можно менять ' + day + ' до ' + Base.time(p);
  }

  /** Черновик счёта после тапа −/+ (idx 0 — хозяева, 1 — гости). Основа: черновик, иначе счёт хода, иначе 0:0. */
  function stepScore(mine, draft, idx, delta) {
    var base = draft || (mine && mine.home_score != null && mine.away_score != null ? [mine.home_score, mine.away_score] : [0, 0]);
    var next = [base[0], base[1]];
    next[idx] = Base.clampGoals(next[idx] + delta);
    return next;
  }

  /**
   * Ход так, как его видит игрок сейчас: серверный ход плюс черновик счёта.
   * Счёт с перевесом переключает сторону; ничья — сторона прежняя, tie: true, отправлять нечего.
   */
  function effectivePick(mine, draft) {
    var side = (mine && mine.side) || null;
    var score = draft || (mine && mine.home_score != null && mine.away_score != null ? [mine.home_score, mine.away_score] : null);
    var tie = !!score && score[0] === score[1];
    if (score && !tie) side = score[0] > score[1] ? 'home' : 'away';
    return { side: side, score: score, tie: tie };
  }

  /** Тап по кнопке команды: ход меняется, только если это другая сторона (счёт тогда сбрасывается). */
  function sideTapSends(mine, draft, side) {
    return effectivePick(mine, draft).side !== side;
  }

  var TIE_LINE = 'Ничьей в хоккее не бывает — поправь счёт';

  /** Итог хода под степперами: {text, sticker}. Без стороны — null. Без чисел очков: козырь — стикером «с козырем». */
  function moveSummary(eff, doubled, sideName) {
    if (!eff.side) return null;
    if (eff.tie) return { text: TIE_LINE, sticker: '' };
    var sticker = doubled ? 'с козырем' : '';
    if (eff.score) return { text: 'Твой ход: ' + eff.score[0] + ':' + eff.score[1], sticker: sticker };
    return { text: 'Твой ход: за' + NBSP + sideName, sticker: sticker };
  }

  function dayCount(made, total) {
    if (!total) return '';
    if (total === 1) return made ? 'готово' : 'ход не сделан';
    return made === total ? 'все ходы сделаны' : made + ' из ' + total;
  }

  /** Экстралига отдыхает: в ближайшие дни её матчей нет, а следующий — позже (или календаря ещё нет). */
  function pauseInfo(list, now) {
    var t = (now || new Date()).getTime();
    var ex = (list || []).filter(function (m) { return m.league === 'extraliga' && m.status === 'scheduled' && new Date(m.starts_at).getTime() > t; });
    if (!ex.length) return null;
    ex.sort(function (a, b) { return a.starts_at < b.starts_at ? -1 : 1; });
    var next = ex[0];
    if (new Date(next.starts_at).getTime() - t <= 3 * 86400000) return null;
    return { until: dateLabel(next.starts_at) };
  }

  /** Следующий ход после итога: ближайший открытый матч тех же клубов, иначе любой ближайший. */
  function nextMatch(list, done) {
    var clubs = [done.home_team, done.away_team];
    var open = (list || []).filter(function (m) { return m.open && m.id !== done.id; }).sort(function (a, b) { return a.starts_at < b.starts_at ? -1 : 1; });
    var own = open.filter(function (m) { return clubs.indexOf(m.home_team) >= 0 || clubs.indexOf(m.away_team) >= 0; });
    return own[0] || open[0] || null;
  }

  // ---------- итог и движение по срезам ----------

  function resultHead(points) {
    return cap(Base.verdict(points == null ? 0 : points).head);
  }

  // «Трибуна» — с какой долей игроков совпал ход. Те же правила и порог, что tribune_line в hockey_notices.py.
  var TRIBUNE_MIN = 8;

  /** Доли сторон и строка под итогом; меньше TRIBUNE_MIN ходов или итога нет — null. */
  function tribune(m) {
    var mine = m && m.my_pick;
    var r = m && m.result;
    var sides = m && m.sides;
    if (!mine || !r || !sides || mine.points == null) return null;
    var total = (sides.home || 0) + (sides.away || 0);
    if (total < TRIBUNE_MIN) return null;
    var home = Math.round((100 * sides.home) / total);
    var out = { total: total, home: home, away: 100 - home, side: mine.side, line: '', chip: '', soft: false };
    if (mine.points === Base.EXACT) {
      // same_exact есть только в ответе по одному матчу; у записи из списка он null — «никто не назвал» писать нельзя.
      if (m.same_exact == null) return null;
      var same = m.same_exact;
      out.chip = same ? 'Так сходили ещё ' + same : 'Больше никто из ' + total;
      out.line = same ? 'Такой счёт назвали ещё ' + same + ' из ' + total + '.' : 'Такой счёт больше никто из ' + total + ' не назвал.';
      return out;
    }
    var winner = r.home_score > r.away_score ? 'home' : 'away';
    var won = winner === 'home' ? out.home : out.away;
    var minePct = mine.side === 'home' ? out.home : out.away;
    var mineCount = mine.side === 'home' ? sides.home : sides.away;
    if (mine.side === winner) out.line = 'Победителя угадали ' + won + '% игроков — и ты в их числе.';
    else if (2 * mineCount > total) {
      out.line = 'Трибуна тоже промахнулась: ' + minePct + '% были за ' + clubName(m[mine.side].name) + '.';
      out.soft = true;
    } else {
      out.line = 'Победителя угадали ' + won + '% игроков.';
      out.soft = true;
    }
    return out;
  }

  /** После промаха: «Бывает — следующий матч Динамо — Торпедо в субботу.» Нет матча — отсылка к хабу. */
  function missLine(next, now) {
    if (!next) return 'Бывает. Следующий ход — на главной игры.';
    var day = Base.whenLabel(next.starts_at, now).split(',')[0];
    return 'Бывает — следующий матч ' + clubShort(next.home.name) + ' — ' + clubShort(next.away.name) + ' ' + day + '.';
  }

  /** Кнопка «Следующий ход · сб, Динамо — Торпедо». */
  function nextTurnLabel(next) {
    if (!next) return 'Следующий ход';
    var wd = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'][Base.minskParts(new Date(next.starts_at)).wd];
    return 'Следующий ход · ' + wd + ', ' + clubShort(next.home.name) + ' — ' + clubShort(next.away.name);
  }

  /** Лучшее место игрока среди лиг в движении после матча: «3-е место в «Офисе»». Нет лиг — null. */
  function bestLeagueChip(items) {
    var best = null;
    (items || []).forEach(function (x) {
      if (x.kind === 'league' && x.rank_after != null && (!best || x.rank_after < best.rank_after)) best = x;
    });
    return best ? best.rank_after + '-е место в\u00a0лиге «' + best.league_name + '»' : null;
  }

  /** Шторка «Как считаются очки»: числа берём из POINTS, слова — из макета. */
  function pointsRules() {
    var P = Base.POINTS;
    return {
      rows: [
        { value: String(P.winner), text: 'Угадал победителя.', gold: false },
        { value: '+' + P.diff, text: 'Угадал разницу шайб.', gold: false },
        { value: '+' + P.goals, text: 'Угадал шайбы хозяев.', gold: false },
        { value: '+' + P.goals, text: 'Угадал шайбы гостей.', gold: false },
        { value: String(P.exact), text: 'Угадал точный счёт — все четыре сразу, это «в точку».', gold: true },
      ],
      trumpTitle: 'Козырь',
      trumpText: 'Один на неделю. Выбери матч для козыря — очки за него удвоятся. Передумаешь — перенеси его на другой матч недели, пока игра не началась.',
      tablesTitle: 'Таблицы и короны',
      tables: [
        { title: 'Кто выше', text: 'Больше очков — выше. Очки равны — выше тот, у кого больше точных счётов. Совпали и они — выше тот, кто сыграл меньше матчей. Всё поровну — место делите.' },
        { title: 'Корона', text: 'Корона — лидеру таблицы после последнего матча месяца. Её разыгрывают в общей таблице и в таблице каждой команды. Первое место поделили — корона у каждого. В лиге друзей её отдают, когда лига закончится.' },
        { title: 'Сколько игроков нужно', text: 'Для короны в таблице должно быть минимум трое игроков с очками. В лиге друзей хватит двоих. Без очков корону не дают.' },
        { title: 'Когда придёт', text: 'В течение двух суток после последнего матча: мы сверяем итоги. Если игроков для короны не хватило, над таблицей так и написано.' },
      ],
      foot: 'Ход можно изменить до минуты перед стартом матча. Очки приходят после финальной сирены.',
    };
  }

  /** Значок звания на аватарке и в строке: «Кепка дня» — 🧢 на макушке, «В чужом шарфе» — 🧣 на шее (как в первой версии). */
  var TITLE_MARK = { cap: '🧢', scarf: '🧣' };

  function titleMark(title) {
    return (title && TITLE_MARK[title.id]) || '';
  }

  /** Пояснение под таблицей лиги: что значат звания, которые на ней висят (шарф, кепка). Нет званий — нет строки. */
  function titlesNote(items) {
    var has = {};
    (items || []).forEach(function (r) { if (r.title && r.title.id) has[r.title.id] = true; });
    var parts = [];
    if (has.scarf) parts.push('Шарф — за ход против своей команды на её ближайший матч.');
    if (has.cap) parts.push('Кепка дня — тому, кто хуже всех угадывал в последний сыгранный вечер лиги. Носит до следующего.');
    return parts.join(' ');
  }

  /** Пьедестал лиги: [2-е, 1-е, 3-е] места; меньше троих — пьедестала нет, остаётся обычная таблица. */
  function podiumOrder(items) {
    if (!items || items.length < 3) return null;
    return [items[1], items[0], items[2]];
  }

  /** Строки «куда сдвинулась» по ответу /movement. */
  function movementRows(items) {
    return (items || []).map(function (x) {
      var label = x.kind === 'league' ? 'Лига «' + x.league_name + '»' : sliceLabel(x.club, x.period_title);
      var from = x.rank_before;
      var to = x.rank_after;
      return {
        label: label,
        from: from == null ? '—' : String(from),
        to: String(to),
        tone: from == null || to < from ? 'up' : to > from ? 'down' : 'same',
        crown: !!x.crown,
      };
    });
  }

  /** Строка про корону месяца под движением: когда решится и сколько матчей осталось. */
  function crownLineAfter(items) {
    var m = (items || []).filter(function (x) { return x.kind === 'slice' && x.left != null; });
    if (!m.length) return '';
    m.sort(function (a, b) { return (a.club ? 0 : 1) - (b.club ? 0 : 1); });
    var x = m[0];
    var month = x.period_title;
    var matches = x.left + NBSP + Base.plural(x.left, 'матч', 'матча', 'матчей') + (x.club ? ' ' + clubGen(x.club) : '');
    if (x.crown && x.left > 0) return 'Корона за ' + month + ' пока твоя. Впереди ещё ' + matches + ' — удержи до ' + endLabel(x.ends_at) + '.';
    if (x.crown) return 'Это был последний матч месяца в таблице «' + sliceLabel(x.club, month) + '»: корона придёт в течение двух суток, когда сверим итоги.';
    if (x.left > 0) return 'До короны за ' + month + ' — ' + Base.points(x.to_crown || 0) + '. Впереди ещё ' + matches + '.';
    return 'Матчи месяца в таблице «' + sliceLabel(x.club, month) + '» сыграны.';
  }

  // ---------- таблица ----------

  /** Периоды таблицы: сезон и месяцы с первого игрового. Закрытый месяц с моей короной помечен. */
  function periodChoices(seasonTitle, nowIso, crowns) {
    var cur = monthKey(nowIso);
    var out = [{ key: 'season', label: cap(seasonTitle || 'сезон'), note: 'все матчи сезона', crown: false }];
    var y = Number(FIRST_MONTH.slice(0, 4));
    var m = Number(FIRST_MONTH.slice(5, 7));
    var months = [];
    for (var guard = 0; guard < 24; guard++) {
      var key = y + '-' + pad(m);
      if (key > cur) break;
      months.push(key);
      m += 1;
      if (m > 12) { m = 1; y += 1; }
    }
    months.reverse().forEach(function (key) {
      var mine = (crowns || []).some(function (c) { return c.period === key && (c.kind === 'month'); });
      out.push({ key: key, label: cap(MONTH_NOM[Number(key.slice(5, 7)) - 1]), note: key === cur ? 'идёт' : 'закрыт', crown: mine });
    });
    return out;
  }

  function periodLabel(key, seasonTitle) {
    if (key === 'season') return 'Сезон';
    var m = /^\d{4}-(\d{2})$/.exec(key || '');
    return m ? cap(MONTH_NOM[Number(m[1]) - 1]) : key;
  }

  function movesWord(n) {
    return n + NBSP + Base.plural(n, 'ход', 'хода', 'ходов');
  }

  function rowSub(r) {
    // Место решают очки, потом точные счета и меньшее число ходов: показываем то, по чему идёт сортировка.
    return movesWord(r.played) + (r.exact > 0 ? ' · ' + r.exact + NBSP + 'в' + NBSP + 'точку' : '');
  }

  function spaced(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  }

  /** Таблица до стольких игроков видна целиком: обрезать девять строк до шести — прятать людей ради трёх строк. */
  var TABLE_FULL_MAX = 15;

  /**
   * Что показать. Маленькая таблица или раскрытая кнопкой — все строки, что прислал сервер.
   * Иначе верх: шесть первых; если игрок ниже шестого — пять первых, разрыв и он с соседями.
   */
  function tableRows(view, expanded) {
    var items = (view && view.items) || [];
    var me = view && view.me;
    var top = expanded || items.length <= TABLE_FULL_MAX ? items.length : me && me.rank > 6 ? 5 : 6;
    var out = items.slice(0, top).map(function (r) { return { type: 'row', r: r }; });
    if (!me || me.rank <= top) return out;
    var neighbors = ((view && view.neighbors) || []).filter(function (r) { return r.rank > top; });
    if (neighbors.length && neighbors[0].rank > top + 1) out.push({ type: 'gap' });
    neighbors.forEach(function (r) { out.push({ type: 'row', r: r }); });
    return out;
  }

  /** После «всех/первых N»: родительный — 21 игрока, 37 игроков. */
  function playersGen(n) {
    return n % 10 === 1 && n % 100 !== 11 ? 'игрока' : 'игроков';
  }

  /** Кнопка под сокращённой таблицей; null — прятать нечего. Сервер шлёт не больше 50 строк, поэтому «всех» не всегда. */
  function tableMore(view, expanded) {
    var items = (view && view.items) || [];
    if (expanded || items.length <= TABLE_FULL_MAX) return null;
    var n = (view && view.players) || 0;
    return n > items.length ? 'Показать первых' + NBSP + items.length + NBSP + playersGen(items.length) : 'Показать всех' + NBSP + spaced(n) + NBSP + playersGen(n);
  }

  function tableCaption(view, club) {
    var n = (view && view.players) || 0;
    var what = club ? 'только матчи ' + clubGen(club) : 'Динамо и вся Экстралига';
    return spaced(n) + NBSP + Base.plural(n, 'игрок', 'игрока', 'игроков') + ' · ' + what;
  }

  /** Пороги короны — те же, что CROWN_MIN_PLAYERS и LEAGUE_CROWN_MIN_MEMBERS в hockey_slices.py. */
  var CROWN_MIN = 3;
  var LEAGUE_CROWN_MIN = 2;
  var HOW_MANY = ['ни одного', 'один', 'двое'];

  /** Месячная таблица, где для короны пока мало игроков с очками: плашка приглушена, не золотая. */
  function tableCrownMuted(view, periodKey) {
    if (!periodKey || periodKey === 'season') return false;
    return !view || (view.players_with_points || 0) < CROWN_MIN;
  }

  /** Плашка про корону под фильтрами. Период не задан — это сезон, как у таблицы по умолчанию. */
  function tableCrownLine(view, club, periodKey, seasonTitle) {
    periodKey = periodKey || 'season';
    var team = club ? ' по матчам ' + clubGen(club) : '';
    if (periodKey === 'season') {
      return club
        ? 'В конце сезона первому — звание «Знаток ' + clubGen(club) + ' ' + (seasonTitle || '').replace(/^сезон /, '') + '».'
        : 'В конце сезона первому — звание «Знаток сезона ' + (seasonTitle || '').replace(/^сезон /, '') + '». Значок у имени — все короны игрока: месяцы, клубы, лиги.';
    }
    var title = periodLabel(periodKey).toLowerCase();
    if (tableCrownMuted(view, periodKey)) {
      var n = (view && view.players_with_points) || 0;
      return 'Корона за ' + title + team + ' появится, когда в таблице будет минимум трое игроков с очками. Сейчас — ' + HOW_MANY[n] + '.';
    }
    var me = view && view.me;
    var tail = me ? (me.rank === 1 ? ' Сейчас первое место твоё.' : ' До первого места — ' + Base.points((view && view.to_crown) || 0) + '.') : '';
    return 'Корона за ' + title + team + ' — у лидера после последнего матча месяца. Придёт в течение двух суток.' + tail;
  }

  /** Мало игроков с очками: таблица честная, короны нет. Позвать болельщиков клуба. */
  function fewPlayers(view, club, periodKey) {
    if (!view || view.players_with_points >= CROWN_MIN) return null;
    periodKey = periodKey || 'season';
    var n = view.players_with_points || 0;
    var label = sliceLabel(club, periodLabel(periodKey, '').toLowerCase());
    return {
      head: n ? label + ' — ' + n + NBSP + Base.plural(n, 'игрок', 'игрока', 'игроков') + ' с очками' : label + ' — пока никого',
      body: 'Таблица уже открыта. Корона появится, когда очки будут хотя бы у троих.',
      invite: 'Создать лигу и' + NBSP + 'позвать',
    };
  }

  /** Строка над кнопкой «Сделать ход», если в срезе нет моих ходов. */
  function noMeLine(club, periodKey, nowIso) {
    var closed = periodKey !== 'season' && periodKey !== monthKey(nowIso);
    if (closed) return 'В этом периоде у тебя не было ходов — загляни в другой';
    return 'Сделай первый ход' + (club ? ' на матч ' + clubGen(club) : '') + ' — и появишься в этой таблице';
  }

  function peakChip(p) {
    return sliceLabel(p.club, p.period_title) + ' · ' + p.rank + NBSP + 'место';
  }

  /** Какую таблицу открыть кнопкой «Таблица»: выбранную руками, иначе лучшую вершину, иначе общую. */
  function tableStartArgs(choice, start) {
    var s = choice || start;
    return { club: (s && s.club) || null, period: (s && s.period) || 'season' };
  }

  /** Общая таблица — все матчи за сезон. */
  function isGeneralTable(a) {
    return !a.club && (a.period || 'season') === 'season';
  }

  /** Плитка «Твоя вершина» на хабе. */
  function peakTile(p, crowns) {
    var isMonth = p.period !== 'season';
    var crowned = isMonth && (crowns || []).some(function (c) { return c.kind === 'month' && c.period === p.period && (c.club || null) === (p.club || null); });
    var note = crowned ? 'корона твоя' : p.rank === 1 ? 'лидируешь' : 'из ' + spaced(p.players);
    return { rank: String(p.rank), name: p.club ? clubShort(p.club) : 'Все матчи', slice: periodShort(p.period_title), note: note, gold: crowned || p.rank === 1 };
  }

  function crownCount(n) {
    return n + NBSP + Base.plural(n, 'корона', 'короны', 'корон');
  }

  // ---------- лиги ----------

  function scopeText(scope, clubs) {
    if (scope === 'all') return 'Все матчи';
    if (scope === 'extraliga') return 'Вся Экстралига';
    if (scope === 'dinamo') return 'Динамо-Минск';
    var names = (clubs || []).map(clubName);
    if (names.length <= 2) return names.join(' и ');
    return names.slice(0, 2).join(', ') + ' и ещё ' + (names.length - 2);
  }

  function termText(l) {
    if (!l || !l.ends_at) return '';
    if (l.term === 'season') return 'до ' + endLabel(l.ends_at);
    if (l.term === 'month') return MONTH_NOM[Base.minskParts(new Date(l.starts_at)).m - 1];
    if (l.term === 'weeks4') return '4 недели';
    if (l.term === 'playoff') return 'плей-офф';
    return rangeLabel(l.starts_at, l.ends_at);
  }

  function leagueSub(l) {
    return scopeText(l.scope, l.clubs) + ' · ' + termText(l);
  }

  /** Тело запроса новой лиги из формы. */
  function termsBody(form, nowIso) {
    var scope = form.scope === 'pick' ? 'clubs' : form.scope;
    var body = { scope: scope, clubs: scope === 'clubs' ? form.clubs.slice() : [], term: form.term };
    if (form.term === 'month') body.month = monthKey(nowIso);
    if (form.term === 'dates') {
      body.starts_on = form.startsOn;
      body.ends_on = form.endsOn;
    }
    return body;
  }

  /** Ошибки набора команд и окон — то, что мешает спросить у сервера «Как будет». */
  function termsError(form) {
    if (form.scope === 'pick' && !form.clubs.length) return 'Выбери команду';
    if (form.term === 'dates') {
      if (!form.startsOn || !form.endsOn) return 'Укажи даты';
      if (form.endsOn <= form.startsOn) return 'Конец раньше начала';
    }
    return '';
  }

  /** Текст кнопки по состоянию формы: поля экрана идут сверху вниз — название, команды, время. */
  function formError(form) {
    if (!(form.name || '').trim()) return 'Назови лигу';
    return termsError(form);
  }

  /**
   * Сроки экрана «Новая лига» по ответу term-options: даты и правило корон — с сервера,
   * у клиента своего календаря нет. Последней строкой всегда «Свои даты» — окон у неё нет,
   * игрок выбирает сам, не дальше конца сезона.
   */
  function termChoices(options) {
    var items = (options && options.items) || [];
    var TITLES = { season: 'До конца сезона', weeks4: '4 недели', playoff: 'Плей-офф' };
    var out = items.map(function (it) {
      var range =
        it.term === 'season' || it.term === 'month'
          ? 'по ' + endLabel(it.ends_at)
          : it.term === 'weeks4'
            ? 'с ' + dateLabel(it.starts_at) + ' по ' + endLabel(it.ends_at)
            : rangeLabel(it.starts_at, it.ends_at);
      return {
        term: it.term,
        label: TITLES[it.term] || periodLabel(monthKey(it.starts_at)),
        sub: range + ' · ' + (it.monthly_crowns ? 'корона каждый месяц' : 'одна корона в конце'),
      };
    });
    out.push({ term: 'dates', label: 'Свои даты', sub: options && options.season_ends_at ? 'не дальше ' + endLabel(options.season_ends_at) : '' });
    return out;
  }

  /**
   * Срок, с которым форма «Новая лига» остаётся после загрузки списка сроков. Пока список не пришёл,
   * выбор не трогаем: в нём есть только «Свои даты», и откат на него переключал форму навсегда.
   * Выбранное окно ушло из списка (плей-офф прошёл) — берём первый открытый срок.
   */
  function settleTerm(term, options) {
    if (!options) return term;
    var choices = termChoices(options);
    if (choices.length && choices.every(function (c) { return c.term !== term; })) return choices[0].term;
    return term;
  }

  /** Одна строка «что считаем» для карточки «Как будет». */
  function scopePhrase(form) {
    if (form.scope === 'dinamo') return 'Матчи Динамо-Минск';
    if (form.scope === 'extraliga') return 'Матчи всей Экстралиги — чемпионата Беларуси';
    if (form.scope === 'all') return 'Матчи Динамо-Минск и всей Экстралиги';
    return (form.clubs || []).length ? 'Матчи: ' + form.clubs.map(clubName).join(', ') : 'Выбери хотя бы одну команду';
  }

  /**
   * Карточка «Как будет» на экране «Новая лига». preview — ответ terms-preview или null:
   * окно дат, число матчей и правило корон честно приходят с сервера.
   */
  function termsSummary(form, preview) {
    var name = (form.name || '').trim();
    var when = '';
    var crowns = '';
    var few = '';
    if (preview && preview.ends_at) {
      var count = preview.matches_in_term;
      when = 'С ' + dateLabel(preview.starts_at) + ' по ' + endLabel(preview.ends_at) + ' · впереди ' + count + NBSP + Base.plural(count, 'матч', 'матча', 'матчей');
      crowns = preview.monthly_crowns ? 'Корона лидеру каждого месяца и чемпион лиги в конце.' : 'Корона чемпиону в конце.';
      if (preview.few_matches) few = 'Матчей мало — таблица будет почти пустой. Можно взять время подлиннее.';
    }
    return {
      title: name ? '«' + name + '»' : '',
      what: scopePhrase(form),
      when: when,
      crowns: crowns,
      few: few,
      note: 'Кто вступит позже — считаем с того дня, как вступил.',
    };
  }

  // ---------- лига изнутри ----------

  /** Сколько участников лиги с очками в показанной таблице (ходящий с нулём не считается, как на сервере). */
  function leagueWithPoints(l) {
    return ((l && l.items) || []).filter(function (r) { return r.points > 0; }).length;
  }

  /** Очки меньше чем у двоих: корону лиги пока не дать — плашка приглушена. */
  function leagueCrownMuted(l) {
    return leagueWithPoints(l) < LEAGUE_CROWN_MIN;
  }

  /** Плашка над таблицей лиги. Число игроков с очками — по строкам той же таблицы (l.items). */
  function leagueCrownLine(l, tab, me, leaderPoints) {
    if (leagueCrownMuted(l)) {
      return 'Корону лиги получит лидер, когда очки будут хотя бы у двоих. ' + (leagueWithPoints(l) ? 'Пока очки только у одного.' : 'Пока их нет ни у кого.');
    }
    if (tab === 'month' && l.period) {
      var mon = periodLabel(l.period.key).toLowerCase();
      var base = 'Корону лиги за ' + mon + ' заберёт лидер после последнего матча месяца.';
      if (!me) return base;
      if (me.rank === 1) return base + ' Сейчас первое место твоё.';
      return base + ' Сейчас ты на ' + me.rank + '-м месте, до первого — ' + Base.points(Math.max(0, leaderPoints - me.points)) + '.';
    }
    return 'Корона лиги — у лидера, когда лига закончится. Для неё хватит и двоих игроков с очками.';
  }

  function leagueMeta(l, members) {
    return leagueSub(l) + ' · ' + members + NBSP + Base.plural(members, 'человек', 'человека', 'человек');
  }

  // ---------- вечер лиги (TASK-431, макет design/kto-kogo-league-evening/League.dc.html) ----------

  /** Жесты вечера: ключ — как у сервера, подпись — на кнопке. */
  var GESTURES = [['stick', 'Стук клюшкой'], ['pen', '2' + NBSP + 'минуты']];

  /** «Вечер 18 ноября» по игровому дню '2026-11-18' (день уже минский, часовой пояс не нужен). */
  function eveningTitle(day) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day || '');
    return m ? 'Вечер ' + Number(m[3]) + NBSP + Base.MONTHS[Number(m[2]) - 1] : 'Вечер';
  }

  function eveningMatchTitle(m) {
    return clubShort(m.home) + ' — ' + clubShort(m.away);
  }

  /** Счёт матча дня; несыгранный — «идёт» или время начала. Ходов и очков тут нет. */
  function eveningScore(m) {
    if (m.status === 'final' && m.home_score != null && m.away_score != null) return m.home_score + ':' + m.away_score;
    return m.started ? 'идёт' : timeOnly(m.starts_at);
  }

  /** Подзаголовок дня: «Динамо — СКА 3:2 · ещё 3 матча». */
  function eveningSummary(ev) {
    var ms = (ev && ev.matches) || [];
    if (!ms.length) return '';
    var head = eveningMatchTitle(ms[0]) + ' ' + eveningScore(ms[0]);
    var rest = ms.length - 1;
    return rest ? head + ' · ещё ' + rest + NBSP + Base.plural(rest, 'матч', 'матча', 'матчей') : head;
  }

  /** «3 из 4»: в плюсе из всех матчей дня. */
  function eveningMoves(r, ev) {
    return (r.hits || 0) + ' из ' + (((ev && ev.matches) || []).length);
  }

  /** Очки за день — числом только когда в дне есть сыгранный матч: до матча очков не показываем. */
  function eveningPoints(r, ev) {
    var played = ((ev && ev.matches) || []).some(function (m) { return m.status === 'final'; });
    return played ? '+' + (r.points || 0) : '';
  }

  function joinNames(names) {
    if (names.length < 2) return names[0] || '';
    return names.slice(0, -1).join(', ') + ' и ' + names[names.length - 1];
  }

  /**
   * Кто что дал строке: «Аня и Саша постучали клюшкой», «Ты и Саша дали 2 минуты».
   * Пола игрока мы не знаем, поэтому одного человека пишем без глагола: «Аня — стук клюшкой».
   */
  function gestureNote(r) {
    var by = { stick: [], pen: [] };
    (r.gestures || []).forEach(function (g) {
      if (!by[g.kind]) return;
      if (g.from_me) by[g.kind].unshift('Ты');
      else by[g.kind].push(g.from);
    });
    var parts = [];
    if (by.stick.length) parts.push(by.stick.length > 1 ? joinNames(by.stick) + ' постучали клюшкой' : by.stick[0] + ' — стук клюшкой');
    if (by.pen.length) parts.push(by.pen.length > 1 ? joinNames(by.pen) + ' дали 2' + NBSP + 'минуты' : by.pen[0] + ' — 2' + NBSP + 'минуты');
    return parts.join(' · ');
  }

  /** Почему без кепки: шарф дня или мало ходов для спора (только когда кепку разыгрывали). */
  function eveningReason(r, ev) {
    if (r.scarf) return 'Болеет за ' + clubShort(r.scarf.club) + ', ход — за ' + clubShort(r.scarf.picked);
    var cap = ev && ev.cap;
    if (!cap || !cap.in_play || r.in_cap_race) return '';
    var n = ((ev && ev.matches) || []).length;
    if (!r.moves) return 'Без ходов — не в споре за кепку';
    return Base.plural(r.moves, 'Ход', 'Хода', 'Ходов') + ' ' + r.moves + ' из ' + n + ' — не в споре за кепку';
  }

  /** Строки под именем в вечере: жесты и причина. Пусто — строк нет. */
  function eveningNotes(r, ev) {
    return [gestureNote(r), eveningReason(r, ev)].filter(Boolean);
  }

  var FEW_WORD = { 2: 'двоих', 3: 'троих', 4: 'четверых', 5: 'пятерых' };

  /** Строка под карточкой вечера. Кепку не разыграли (в споре меньше троих) — так и пишем. */
  function eveningFoot(ev) {
    var cap = ev && ev.cap;
    if (cap && cap.decided && !cap.in_play) return 'Кепку в этот вечер не разыграли: в споре меньше ' + (FEW_WORD[cap.min_players] || cap.min_players) + '.';
    return 'Кепка дня — тому, кто хуже всех угадывал в этот вечер.';
  }

  /** Тап по жесту: тот же жест снимает его, другой — меняет. */
  function gestureNext(current, kind) {
    return current === kind ? null : kind;
  }

  /** Строка таблицы месяца: «12 мин штрафа · 3 кепки · 9 стуков»; нулевые части не показываем. */
  function leagueMarks(r) {
    var parts = [];
    if (r && r.penalty_minutes) parts.push(r.penalty_minutes + NBSP + 'мин штрафа');
    if (r && r.caps) parts.push(r.caps + NBSP + Base.plural(r.caps, 'кепка', 'кепки', 'кепок'));
    if (r && r.sticks) parts.push(r.sticks + NBSP + Base.plural(r.sticks, 'стук', 'стука', 'стуков'));
    return parts.join(' · ');
  }

  /** Шторка правил, раздел «Кепка» (макет Rules.dc.html). */
  function capRules() {
    return {
      lead: 'Кепка дня достаётся тому, кто хуже всех угадывал в этот день',
      items: [
        { k: 'Как сравниваем.', t: 'Очки за день делим на число ходов — у кого меньше в среднем за ход, тот и в кепке.' },
        { k: 'Кто в споре.', t: 'Только те, кто сходил хотя бы на половину матчей дня. Пропустил — кепки нет, но и очков тоже.' },
        { k: 'Когда.', t: 'Решается после последнего матча дня. Носишь до следующего игрового дня лиги.' },
        { k: 'Ничья.', t: 'Хуже всех сразу двое — кепка у обоих. Все угадали одинаково — кепки нет.' },
        { k: 'Сколько нужно.', t: 'Кепка разыгрывается, если в этот день сходили хотя бы трое.' },
      ],
      exampleTitle: 'Пример: вечер из 4 матчей',
      example: [
        { name: 'Аня', moves: '4 хода · +80', value: '20 за ход' },
        { name: 'Саша', moves: '3 хода · +50', value: '17 за ход' },
        { name: 'Олег', moves: '3 хода · +10', value: '3 за ход — кепка' },
        { name: 'Дима', moves: '1 ход · +20', value: 'не в споре', out: true },
      ],
      foot: 'Кепки за месяц видны в таблице лиги: «3 кепки». 1-го числа — с нуля, вместе с короной.',
    };
  }

  /** Шторка правил, раздел «Жесты». Черновик агента: в макете раздела нет, текст утверждает владелец. */
  function gestureRules() {
    return {
      lead: 'Жест — шутка вечера: другу, когда все матчи дня сыграны',
      items: [
        { k: 'Стук клюшкой.', t: 'Хорошо сходил — уважаем.' },
        { k: '2 минуты.', t: 'Удаление на две минуты: за промах, за чужой шарф или просто так.' },
        { k: 'Сколько.', t: 'Один жест от тебя каждому другу за вечер. Передумаешь — смени или сними. Себе нельзя.' },
        { k: 'Где видно.', t: 'В строке вечера и в таблице лиги: «4 мин штрафа». Сообщений в чат за жесты нет.' },
      ],
    };
  }

  // ---------- своя лига в один тап (TASK-431, макет Ready.dc.html) ----------

  /** Переключатель «Какие матчи» на экране «Лига готова»: ключ — scope для сервера. */
  var READY_SCOPES = [['all', 'Все'], ['dinamo', 'Динамо'], ['clubs', 'Свои команды']];
  var READY_TAIL = 'Название и картинку можно поменять потом.';

  /** Строка под названием: что считаем и до когда. */
  function readyLine(scope, clubs) {
    if (scope === 'dinamo') return 'Матчи Динамо-Минск, до конца сезона. ' + READY_TAIL;
    if (scope === 'clubs') {
      var names = (clubs || []).map(clubName);
      if (!names.length) return 'Выбери свои команды — считаем их матчи до конца сезона.';
      return 'Матчи: ' + names.join(', ') + ' — до конца сезона. ' + READY_TAIL;
    }
    return 'Все матчи «Кто кого», до конца сезона. ' + READY_TAIL;
  }

  /** Что мешает нажать «Позвать друзей». Пусто — можно. */
  function readyError(form) {
    if (form && form.scope === 'clubs' && !(form.clubs || []).length) return 'Выбери команду';
    return '';
  }

  /** Тело «Позвать друзей»: набор команд, «на что играем» (уже очищенная строка) и метка входа. */
  function readyBody(form, stake, src) {
    var body = { scope: form.scope, clubs: form.scope === 'clubs' ? (form.clubs || []).slice() : [] };
    if (stake) body.stake_text = stake;
    if (src) body.src = src;
    return body;
  }

  function inviteText(name, l) {
    var what = l && l.scope !== 'all' ? ': ' + scopeText(l.scope, l.clubs) : l ? '' : ': Динамо-Минск';
    return 'Угадываем хоккейные матчи' + what + ' — лига «' + name + '». Тапни за команду, посмотрим, кто кого.';
  }

  // ---------- карточка болельщика ----------

  function crownLabel(c) {
    var month = c.period ? cap(MONTH_NOM[Number(c.period.slice(5, 7)) - 1]) : '';
    if (c.kind === 'league_term') return 'Чемпион лиги «' + (c.league_name || '') + '»';
    if (c.kind === 'league_month') return month + ' · лига «' + (c.league_name || '') + '»';
    return month + ' · ' + (c.club ? 'болельщики ' + clubGen(c.club) : 'все игроки');
  }

  /**
   * Стенд наград (TASK-430): короны игрока по клубам, общей таблице и лигам из ``profile.crowns``.
   * ``clubs`` — каталог клубов (Динамо-Минск первым): на стенде видны все, и те, где корон ещё нет.
   * Цифра у клуба — сколько раз игрок был первым в нём (месяцы), месяцы идут от новых к старым.
   */
  function standModel(crowns, clubs) {
    var byClub = {};
    var overall = 0;
    var leagues = 0;
    (crowns || []).forEach(function (c) {
      if (c.league_id || (c.kind && String(c.kind).indexOf('league_') === 0)) { leagues += 1; return; }
      if (c.club) { (byClub[c.club] = byClub[c.club] || []).push(c.period || ''); return; }
      overall += 1;
    });
    var list = (clubs || []).map(function (club) {
      var months = (byClub[club.name] || []).slice().sort().reverse();
      return { club: club, count: months.length, months: months };
    });
    return { total: (crowns || []).length, overall: overall, leagues: leagues, clubs: list };
  }

  /**
   * Сравнение двух стендов по клубам: в скольких клубах корон больше у меня, у него и поровну.
   * Клубы, где у обоих ноль, не считаются: «поровну» значит поровну корон, а не «ничего нет».
   */
  function standCompare(theirs, mine) {
    var out = { mine: 0, theirs: 0, same: 0 };
    theirs.clubs.forEach(function (e, i) {
      var a = e.count;
      var b = mine.clubs[i] ? mine.clubs[i].count : 0;
      if (!a && !b) return;
      if (b > a) out.mine += 1;
      else if (a > b) out.theirs += 1;
      else out.same += 1;
    });
    return out;
  }

  /** Мини-стенд в строке: клубы с коронами, у кого больше — первыми (при равенстве порядок каталога), до ``limit``. */
  function standMini(model, limit) {
    var withCrowns = model.clubs.filter(function (c) { return c.count > 0; }).map(function (c, i) { return { c: c, i: i }; });
    withCrowns.sort(function (a, b) { return b.c.count - a.c.count || a.i - b.i; });
    var shown = withCrowns.slice(0, limit).map(function (x) { return x.c; });
    return { shown: shown, more: Math.max(0, withCrowns.length - shown.length) };
  }

  /** «14 корон» / «1 корона» / «Пока без корон»: подпись у строки стенда. */
  function standCountLabel(total) {
    if (!total) return 'Пока без корон';
    return total + NBSP + Base.plural(total, 'корона', 'короны', 'корон');
  }

  /** Месяцы корон клуба для карточки клуба: «Октябрь», «Сентябрь». */
  function clubCrownMonths(entry) {
    return (entry.months || []).filter(Boolean).map(function (p) { return cap(MONTH_NOM[Number(p.slice(5, 7)) - 1]); });
  }

  function seasonTitleLine(p, seasonLabelText) {
    var lines = [];
    if (p.overall) lines.push({ rank: p.overall.rank, label: 'Знаток сезона · все матчи', note: p.overall.to_first ? 'до 1-го места — ' + Base.points(p.overall.to_first) : 'первое место', total: p.overall.players });
    if (p.club_place && p.club) lines.push({ rank: p.club_place.rank, label: 'Знаток ' + clubGen(p.club.name) + ' ' + seasonLabelText, note: p.club_place.to_first ? 'до 1-го места — ' + Base.points(p.club_place.to_first) : 'первое место', total: p.club_place.players });
    return lines;
  }

  // ---------- «Матчи и мои ходы» (TASK-359) ----------

  /** Те же числа, что MATCH_LIVE_FOR и MATCH_STALE_AFTER в hockey_game.py: часы сервера и клиента не должны расходиться. */
  var LIVE_FOR_MS = 3 * 3600 * 1000;
  var STALE_AFTER_MS = 3 * 86400 * 1000;

  function startMs(m) {
    return new Date(m.starts_at).getTime();
  }

  /**
   * Фаза матча: upcoming | live | waiting | done | cancelled. Основа — серверная m.phase (знает про запомненный итог),
   * клиент лишь двигает её по часам: экран, открытый до старта, сам переходит в «идёт», а «идёт» через три часа — в «ждём итог».
   */
  function matchPhase(m, now) {
    if (m.status === 'cancelled') return 'cancelled';
    if (m.status === 'final') return 'done';
    var t = (now || new Date()).getTime();
    var start = startMs(m);
    if (t < start) return 'upcoming';
    if (m.status === 'review' || m.phase === 'waiting') return 'waiting';
    return t - start < LIVE_FOR_MS ? 'live' : 'waiting';
  }

  /** Итога нет больше трёх суток: автоматика уже не подтвердит. Такая строка уходит из «ждём итог» в «Сыграли». */
  function isStale(m, now) {
    return matchPhase(m, now) === 'waiting' && (now || new Date()).getTime() - startMs(m) >= STALE_AFTER_MS;
  }

  function byStart(a, b) {
    return startMs(a) - startMs(b) || a.id - b.id;
  }

  /** Мои ходы на начавшихся матчах без итога: идущие первыми, дальше ждущие итога. Для хаба игры и сводки. */
  function pendingMatches(list, now) {
    var live = [];
    var waiting = [];
    (list || []).forEach(function (m) {
      if (!m.my_pick) return;
      var ph = matchPhase(m, now);
      if (ph === 'live') live.push(m);
      else if (ph === 'waiting' && !isStale(m, now)) waiting.push(m);
    });
    return live.sort(byStart).concat(waiting.sort(byStart));
  }

  /** Заголовок блока хаба: «ТВОЯ КОМАНДА · ЖДЁМ ИТОГ», «ИДЁТ», «ИДЁТ И ЖДЁМ ИТОГ». */
  function pendingHead(items, club, now) {
    var live = items.some(function (m) { return matchPhase(m, now) === 'live'; });
    var waiting = items.some(function (m) { return matchPhase(m, now) === 'waiting'; });
    var what = live && waiting ? 'ИДЁТ И ЖДЁМ ИТОГ' : live ? 'ИДЁТ' : 'ЖДЁМ ИТОГ';
    var mine = !!club && items.some(function (m) { return m.home_team === club || m.away_team === club; });
    return (mine ? 'ТВОЯ КОМАНДА · ' : '') + what;
  }

  var WAIT_NOTE = 'Итог подтверждаем по двум проверкам.';
  /** Подпись под «Идёт и ждём итог»: про бота — только если игрок включил сообщения в чате. */
  function waitNote(remindOn) {
    return WAIT_NOTE + (remindOn ? ' Пришлём результат сюда и в бота.' : ' Результат появится здесь.');
  }

  function relDay(iso, now) {
    var diff = Base.dayIndex(Base.minskParts(new Date(iso))) - Base.dayIndex(Base.minskParts(now || new Date()));
    return diff === 0 ? 'СЕГОДНЯ' : diff === 1 ? 'ЗАВТРА' : diff === -1 ? 'ВЧЕРА' : '';
  }

  /** «СЕГОДНЯ, ПН 9 НОЯБРЯ» · «ЗАВТРА, ВТ 10 НОЯБРЯ» · «ВЧЕРА, ВС 8 НОЯБРЯ» · «ЧТ 5 НОЯБРЯ». */
  function dayHeading(iso, now) {
    var p = Base.minskParts(new Date(iso));
    var date = WEEKDAY_SHORT_UP[p.wd] + ' ' + p.d + ' ' + Base.MONTHS[p.m - 1].toUpperCase();
    var rel = relDay(iso, now);
    return rel ? rel + ', ' + date : date;
  }

  /** Шапка строки: «ЗАВТРА 19:00 · ЭКСТРАЛИГА · МИНСК», «ВС 8 НОЯБРЯ · 17:00 · КХЛ». У перенесённого время в центре, в шапке день. */
  function rowLabel(m, phase, now, moved) {
    var p = Base.minskParts(new Date(m.starts_at));
    var time = Base.time(p);
    var rel = relDay(m.starts_at, now);
    var date = WEEKDAY_SHORT_UP[p.wd] + ' ' + p.d + ' ' + Base.MONTHS[p.m - 1].toUpperCase();
    var when = moved ? [date] : rel === 'СЕГОДНЯ' || rel === 'ЗАВТРА' ? [rel + ' ' + time] : [date, time];
    var parts = when.concat([leagueUp(m)]);
    if (phase === 'upcoming' && m.city) parts.push(String(m.city).toUpperCase());
    return parts.join(' · ');
  }

  function moveText(m) {
    var pick = m.my_pick;
    var team = clubShort(m[pick.side].name);
    return pick.home_score != null && pick.away_score != null ? team + ' · ' + pick.home_score + ':' + pick.away_score : team;
  }

  var NO_MOVE = 'ты не ходил';
  /** Сервер уже увидел итог или проверяет его (m.checking) — матч окончен, а не идёт дольше трёх часов. */
  var CHECKING_CAP = 'Матч окончен · сверяем счёт';
  var AFTER_RESULT = 'Очки — после итога';

  /** Подпись под счётом сыгранного матча: «итог», «в овертайме», «по буллитам». */
  function decidedCaption(decidedIn) {
    return decidedIn === 'ot' ? 'в овертайме' : decidedIn === 'so' ? 'по буллитам' : 'итог';
  }

  /** Очки сыгранного хода с козырем: золото только за «в точку» (базовые 50), ноль — нейтральная плашка. */
  function pointsChip(m) {
    var pick = m.my_pick;
    var total = m.my_points != null ? m.my_points : Base.totalPoints(pick);
    if (total == null) return { kind: 'note', text: 'Считаем очки' };
    var trump = !!pick.doubled;
    if (total === 0) return { kind: 'points', tone: 'zero', text: '0 · не угадал', trump: trump };
    if (pick.points === Base.POINTS.exact) return { kind: 'points', tone: 'exact', text: '+' + total + ' В ТОЧКУ', trump: trump };
    return { kind: 'points', tone: 'pos', text: '+' + total, trump: trump };
  }

  function movedFrom(m) {
    return m.moved_from && !isNaN(Date.parse(m.moved_from)) ? m.moved_from : '';
  }

  /**
   * Всё, что рисует строка списка, одним объектом: рисовать остаётся только DOM.
   * chip: live | wait | moved | cancelled (значок в шапке); center: {big, cap}; move: {text, muted}; right: button | note | points | none.
   * Счёта в «ждём итог» нет, очков до итога нет, срока не обещаем (правила игры и AC-004).
   */
  function rowModel(m, now) {
    now = now || new Date();
    var phase = matchPhase(m, now);
    var stale = isStale(m, now);
    var mine = !!m.my_pick;
    var moved = phase === 'upcoming' && !!movedFrom(m);
    var out = { id: m.id, phase: phase, stale: stale, chip: null, label: '', center: { big: '', cap: '' }, move: { label: 'ТВОЙ ХОД', text: '', muted: false }, right: { kind: 'none' }, struck: false };
    out.label = rowLabel(m, phase, now, moved);
    out.move.text = mine ? moveText(m) : '';
    if (phase === 'upcoming') {
      var open = !!m.open;
      if (moved) out.chip = { kind: 'moved', text: 'ПЕРЕНЕСЁН' };
      out.center = { big: timeOnly(m.starts_at), cap: moved ? 'было ' + timeOnly(m.moved_from) : open ? 'ход открыт' : 'ходы закрыты' };
      if (!mine) {
        out.move.text = 'ещё не выбран';
        out.move.muted = true;
      }
      out.right = open ? { kind: 'button', text: mine ? 'Изменить' : 'Сделать ход', gold: !mine } : { kind: 'note', text: 'Ходы закрыты' };
    } else if (phase === 'live') {
      out.chip = { kind: 'live', text: 'ИДЁТ' };
      // Промежуточный счёт есть не у каждого матча. 0:0 рядом с прочерком читается как известная ничья.
      out.center = { big: '—:—', cap: 'идёт матч' };
      if (mine) out.right = { kind: 'note', text: AFTER_RESULT };
    } else if (phase === 'waiting') {
      out.chip = { kind: 'wait', text: stale ? 'БЕЗ ИТОГА' : 'ЖДЁМ ИТОГ' };
      out.center = { big: '—:—', cap: stale ? 'итог не подтверждён' : m.checking ? CHECKING_CAP : 'итог уточняем' };
      if (mine) out.right = { kind: 'note', text: AFTER_RESULT };
    } else if (phase === 'done') {
      var r = m.result;
      out.center = r ? { big: r.home_score + ':' + r.away_score, cap: decidedCaption(r.decided_in) } : { big: '—:—', cap: 'итог' };
      if (mine) out.right = pointsChip(m);
    } else {
      out.chip = { kind: 'cancelled', text: 'ОТМЕНЁН' };
      out.center = { big: '—', cap: 'матч отменён' };
      out.struck = true;
      if (mine) {
        out.move.text = 'ход снят';
        out.move.muted = true;
        out.right = { kind: 'note', text: 'В очки не входит' };
      }
    }
    if (!mine && phase !== 'upcoming') {
      out.move.text = NO_MOVE;
      out.move.muted = true;
    }
    return out;
  }

  function byDay(list, now) {
    var days = [];
    var index = {};
    list.forEach(function (m) {
      var key = dayKey(m.starts_at);
      if (!index[key]) {
        index[key] = { day: key, head: dayHeading(m.starts_at, now), items: [] };
        days.push(index[key]);
      }
      index[key].items.push(m);
    });
    return days;
  }

  /** Сколько матч с итогом держится над «Впереди»: иначе только что сыгранный уходит под сорок будущих. */
  var RECENT_MS = 48 * 3600 * 1000;

  /**
   * Список по секциям: active — идёт и ждём итог (идущие, затем ждущие), recent — итог есть, начались за двое суток,
   * от новых к старым; upcoming — впереди по дням; done — сыграли по дням от новых к старым
   * (сюда же матчи без итога старше трёх суток и прошедшие отменённые).
   */
  function groupMatches(items, now) {
    now = now || new Date();
    var live = [];
    var waiting = [];
    var recent = [];
    var upcoming = [];
    var done = [];
    (items || []).forEach(function (m) {
      var ph = matchPhase(m, now);
      if (ph === 'live') live.push(m);
      else if (ph === 'waiting' && !isStale(m, now)) waiting.push(m);
      else if (ph === 'upcoming' || (ph === 'cancelled' && startMs(m) > now.getTime())) upcoming.push(m);
      else if (ph === 'done' && now.getTime() - startMs(m) < RECENT_MS) recent.push(m);
      else done.push(m);
    });
    return {
      active: live.sort(byStart).concat(waiting.sort(byStart)),
      recent: recent.sort(function (a, b) { return byStart(b, a); }),
      upcoming: byDay(upcoming.sort(byStart), now),
      done: byDay(done.sort(function (a, b) { return byStart(b, a); }), now),
    };
  }

  /** Две цифры сводки (DEC-001): «ждут итога N» и «очки · R-е место» из me. Процентов нет. */
  function matchesSummary(me, awaiting) {
    var n = awaiting || 0;
    var pts = me ? me.points : 0;
    var place = me && me.rank ? me.rank + '-е' + NBSP + 'место' : 'пока без места';
    return {
      awaiting: String(n),
      awaitingLabel: n === 1 ? 'ждёт итога' : 'ждут итога',
      points: spaced(pts),
      pointsLabel: Base.plural(pts, 'очко', 'очка', 'очков') + ' · ' + place,
    };
  }

  /** Подпись секции «Сыграли»: «14 ходов» — ходы с начисленными очками за сезон (me.played), не число матчей. */
  function playedCount(me) {
    return me ? movesWord(me.played) : '';
  }

  /** Строка под названием входа из хаба и профиля: «3 ждут итога · 12-е место». */
  function entryLine(awaiting, me) {
    var parts = [];
    if (awaiting) parts.push(awaiting + NBSP + (awaiting === 1 ? 'ждёт итога' : 'ждут итога'));
    if (me && me.rank) parts.push(me.rank + '-е' + NBSP + 'место');
    return parts.join(' · ') || 'Статус каждого хода';
  }

  var MATCHES_TITLE = 'Матчи и мои ходы';
  var ENTRY_TITLE = 'Все матчи и мои ходы';
  var MATCHES_EMPTY = {
    label: 'ПОКА ПУСТО',
    head: 'Здесь будут твои ходы и их итоги',
    text: 'Выбери победителя ближайшего матча, и он появится в этом списке.',
    cta: 'К ближайшему матчу',
  };

  /** Новый игрок: в «Мои ходы» нет ни одного хода и подгружать нечего — вместо списка пустое состояние. */
  function matchesEmpty(items, hasMore) {
    return !hasMore && !(items || []).some(function (m) { return m.my_pick; });
  }

  /** Куда ведёт «К ближайшему матчу»: ближайший открытый матч, иначе — хаб (null). */
  function nearestOpen(items) {
    return (items || []).filter(function (m) { return m.open && m.status === 'scheduled'; }).sort(byStart)[0] || null;
  }

  function cursorParts(cursor) {
    var m = /^(\d+)_(\d+)$/.exec(cursor || '');
    return m ? { t: Math.floor(Number(m[1]) / 1000), id: Number(m[2]) } : null;
  }

  function isHistory(m, now) {
    var ph = matchPhase(m, now);
    return ph === 'done' || isStale(m, now) || (ph === 'cancelled' && startMs(m) <= now.getTime());
  }

  /**
   * Свежая первая страница поверх уже загруженного списка: то, что игрок подгрузил кнопкой «Показать раньше»,
   * остаётся, остальное заменяется ответом. prev — {items, hasMore, cursor} или null, history — ответ сервера.
   */
  function mergeMatchList(prev, items, history, now) {
    now = now || new Date();
    history = history || {};
    var out = items.slice();
    var next = { hasMore: !!history.has_more, cursor: history.next_before || null };
    var floor = history.has_more ? cursorParts(history.next_before) : null;
    if (prev && prev.items && prev.cursor && floor) {
      var seen = {};
      items.forEach(function (m) { seen[m.id] = true; });
      var older = prev.items.filter(function (m) {
        return !seen[m.id] && isHistory(m, now) && (startMs(m) < floor.t || (startMs(m) === floor.t && m.id < floor.id));
      });
      if (older.length) {
        out = out.concat(older);
        next = { hasMore: !!prev.hasMore, cursor: prev.cursor };
      }
    }
    return { items: out.sort(byStart), hasMore: next.hasMore, cursor: next.cursor };
  }

  /** Страница «Показать раньше»: дописывается к списку, дубли отбрасываются. */
  function appendMatchPage(prev, items, history) {
    var seen = {};
    (prev.items || []).forEach(function (m) { seen[m.id] = true; });
    var add = items.filter(function (m) { return !seen[m.id]; });
    return { items: (prev.items || []).concat(add).sort(byStart), hasMore: !!(history && history.has_more), cursor: (history && history.next_before) || null };
  }

  // ---------- «Итог — в чат»: после первого хода просим разрешить боту писать первым ----------

  /** Тексты подводки: в одном тоне со строкой «Сообщения в чате» на хабе. */
  var WRITE_ASK = {
    title: 'Итог' + NBSP + '— в чат',
    text: 'Напишем, чем закончился матч, и' + NBSP + 'напомним о' + NBSP + 'следующем ходе. Не' + NBSP + 'чаще раза в' + NBSP + 'день, ночью не' + NBSP + 'пишем.',
    allow: 'Да, писать в' + NBSP + 'чат',
    later: 'Не' + NBSP + 'сейчас',
  };
  var WRITE_ASK_KEY = 'kk_write_ask';

  function hasPick(list) {
    for (var k in list || {}) {
      if (Object.prototype.hasOwnProperty.call(list, k) && list[k] && list[k].my_pick) return true;
    }
    return false;
  }

  /**
   * Это первый ход игрока? Смотрим перед отправкой хода. Ответ сервера про сам ход этого не говорит, а
   * profile.played считает только ходы на сыгранные матчи — поэтому сверяем всё, что знаем:
   * awaiting (ходы на несыгранные матчи, число из /matches; не число — список не загрузился, «не знаем» = нет),
   * me (строка сезона: есть очки за сыгранные), ходы в загруженных матчах и успешные ходы этой сессии.
   */
  function isFirstPick(o) {
    o = o || {};
    if (typeof o.awaiting !== 'number' || o.awaiting !== 0) return false;
    if (o.me) return false;
    if ((o.saved || 0) > 0) return false;
    return !hasPick(o.matches) && !hasPick(o.cache);
  }

  /** Флаг «уже спрашивали» на устройстве; хранилище недоступно — помним до конца сессии. */
  function writeAskMemo(storage) {
    var mem = false;
    return {
      asked: function () {
        if (mem) return true;
        try {
          return !!storage && storage.getItem(WRITE_ASK_KEY) === '1';
        } catch (e) {
          return false;
        }
      },
      mark: function () {
        mem = true;
        try {
          if (storage) storage.setItem(WRITE_ASK_KEY, '1');
        } catch (e) { /* в памяти уже отмечено */ }
      },
    };
  }

  /**
   * Показывать ли подводку. o: {first, tg, wa (GlideWriteAccess), asked, remind, sheet}.
   * wa.writeAccessState(tg) === 'askable' — это Telegram, метод есть, а боту писать ещё нельзя.
   */
  function shouldAskWrite(o) {
    o = o || {};
    // remind === false — сам выключил или после «Не сейчас». true/null у новичка без права писать — как раз повод для подводки.
    if (o.first !== true || o.asked === true || o.remind === false || o.sheet) return false;
    if (!o.tg || !o.wa || typeof o.wa.writeAccessState !== 'function') return false;
    try {
      return o.wa.writeAccessState(o.tg) === 'askable';
    } catch (e) {
      return false;
    }
  }

  /**
   * Ответ на подводку: флаг ставится всегда. 'allow' — системное окно Telegram (wa.requestWriteAccess),
   * и только при согласии o.save(). Промис не отклоняется: 'later' | 'granted' | 'denied' | 'unsupported' | 'error'.
   */
  function answerWriteAsk(choice, o) {
    o = o || {};
    try {
      if (o.memo) o.memo.mark();
    } catch (e) { /* */ }
    if (choice !== 'allow') return Promise.resolve('later');
    var req;
    try {
      req = o.wa.requestWriteAccess(o.tg);
    } catch (e) {
      return Promise.resolve('error');
    }
    return Promise.resolve(req).then(function (outcome) {
      if (outcome === 'granted') {
        try {
          if (typeof o.save === 'function') o.save();
        } catch (e) { /* */ }
      }
      return outcome;
    }, function () {
      return 'error';
    });
  }

  var api = {
    clubName: clubName,
    clubGen: clubGen,
    clubShort: clubShort,
    seasonTitleFor: seasonTitleFor,
    dayKey: dayKey,
    weekKey: weekKey,
    monthKey: monthKey,
    dateLabel: dateLabel,
    endLabel: endLabel,
    timeOnly: timeOnly,
    monthEndLabel: monthEndLabel,
    rangeLabel: rangeLabel,
    sliceLabel: sliceLabel,
    stakeLines: stakeLines,
    stakesEmpty: stakesEmpty,
    STAKES_NOTE: STAKES_NOTE,
    livePlaces: livePlaces,
    pickPoints: pickPoints,
    livePoints: livePoints,
    liveParts: liveParts,
    liveWhy: liveWhy,
    liveStamp: liveStamp,
    duelLive: duelLive,
    duelPill: duelPill,
    DUEL_HINT: DUEL_HINT,
    duelFinal: duelFinal,
    crowdPeople: crowdPeople,
    CROWD_NOTE: CROWD_NOTE,
    TIE_LINE: TIE_LINE,
    trumpLabel: trumpLabel,
    missLine: missLine,
    nextTurnLabel: nextTurnLabel,
    bestLeagueChip: bestLeagueChip,
    pointsRules: pointsRules,
    trumpState: trumpState,
    trumpHint: trumpHint,
    closeTime: closeTime,
    pointsLine: pointsLine,
    questionLine: questionLine,
    dayMatches: dayMatches,
    heroMatch: heroMatch,
    heroMeta: heroMeta,
    changeUntil: changeUntil,
    stepScore: stepScore,
    effectivePick: effectivePick,
    sideTapSends: sideTapSends,
    moveSummary: moveSummary,
    dayLabelUp: dayLabelUp,
    dayCount: dayCount,
    pauseInfo: pauseInfo,
    nextMatch: nextMatch,
    resultHead: resultHead,
    movementRows: movementRows,
    crownLineAfter: crownLineAfter,
    periodChoices: periodChoices,
    periodLabel: periodLabel,
    rowSub: rowSub,
    spaced: spaced,
    tableRows: tableRows,
    tableMore: tableMore,
    tableCaption: tableCaption,
    tableCrownLine: tableCrownLine,
    tableCrownMuted: tableCrownMuted,
    fewPlayers: fewPlayers,
    noMeLine: noMeLine,
    peakChip: peakChip,
    peakTile: peakTile,
    tableStartArgs: tableStartArgs,
    isGeneralTable: isGeneralTable,
    crownCount: crownCount,
    scopeText: scopeText,
    termText: termText,
    leagueSub: leagueSub,
    termsBody: termsBody,
    termsError: termsError,
    formError: formError,
    termChoices: termChoices,
    settleTerm: settleTerm,
    scopePhrase: scopePhrase,
    termsSummary: termsSummary,
    leagueCrownLine: leagueCrownLine,
    leagueCrownMuted: leagueCrownMuted,
    leagueMeta: leagueMeta,
    inviteText: inviteText,
    crownLabel: crownLabel,
    standModel: standModel,
    standMini: standMini,
    standCompare: standCompare,
    standCountLabel: standCountLabel,
    clubCrownMonths: clubCrownMonths,
    seasonTitleLine: seasonTitleLine,
    matchPhase: matchPhase,
    isStale: isStale,
    pendingMatches: pendingMatches,
    pendingHead: pendingHead,
    waitNote: waitNote,
    dayHeading: dayHeading,
    rowModel: rowModel,
    groupMatches: groupMatches,
    matchesSummary: matchesSummary,
    playedCount: playedCount,
    entryLine: entryLine,
    matchesEmpty: matchesEmpty,
    nearestOpen: nearestOpen,
    mergeMatchList: mergeMatchList,
    appendMatchPage: appendMatchPage,
    MATCHES_TITLE: MATCHES_TITLE,
    ENTRY_TITLE: ENTRY_TITLE,
    MATCHES_EMPTY: MATCHES_EMPTY,
    WRITE_ASK: WRITE_ASK,
    WRITE_ASK_KEY: WRITE_ASK_KEY,
    isFirstPick: isFirstPick,
    writeAskMemo: writeAskMemo,
    shouldAskWrite: shouldAskWrite,
    answerWriteAsk: answerWriteAsk,
    tribune: tribune,
    podiumOrder: podiumOrder,
    titleMark: titleMark,
    titlesNote: titlesNote,
    TRIBUNE_MIN: TRIBUNE_MIN,
    GESTURES: GESTURES,
    eveningTitle: eveningTitle,
    eveningMatchTitle: eveningMatchTitle,
    eveningScore: eveningScore,
    eveningSummary: eveningSummary,
    eveningMoves: eveningMoves,
    eveningPoints: eveningPoints,
    gestureNote: gestureNote,
    eveningReason: eveningReason,
    eveningNotes: eveningNotes,
    eveningFoot: eveningFoot,
    gestureNext: gestureNext,
    leagueMarks: leagueMarks,
    capRules: capRules,
    gestureRules: gestureRules,
    READY_SCOPES: READY_SCOPES,
    readyLine: readyLine,
    readyError: readyError,
    readyBody: readyBody,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.KtoKogoScreens = api;
})(typeof window !== 'undefined' ? window : globalThis);
