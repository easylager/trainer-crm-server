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
    return firstWord(name).charAt(0).toUpperCase() || '?';
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
    var rest = (list || []).filter(function (m) { return m.id !== exceptId; });
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
        { value: '+' + P.diff, text: 'За совпавшую разницу, шайбы хозяев или гостей.', gold: false },
        { value: String(P.exact), text: 'Угадал точный счёт — это «в точку».', gold: true },
      ],
      trumpTitle: 'Козырь',
      trumpText: 'Один на неделю. Выбери матч для козыря — очки за него удвоятся. Передумаешь — перенеси его на другой матч недели, пока игра не началась.',
      foot: 'Ход можно изменить до минуты перед стартом матча. Очки приходят после финальной сирены.',
    };
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
    if (x.crown) return 'Это был последний матч месяца в таблице «' + sliceLabel(x.club, month) + '»: корона появится после проверки итога.';
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

  /** Что показать: верх таблицы; если игрок ниже шестого — пять первых, разрыв и он с соседями. */
  function tableRows(view) {
    var items = (view && view.items) || [];
    var me = view && view.me;
    if (!me || me.rank <= 6) return items.slice(0, 6).map(function (r) { return { type: 'row', r: r }; });
    var out = items.slice(0, 5).map(function (r) { return { type: 'row', r: r }; });
    var neighbors = ((view && view.neighbors) || []).filter(function (r) { return r.rank > 5; });
    if (neighbors.length && neighbors[0].rank > 6) out.push({ type: 'gap' });
    neighbors.forEach(function (r) { out.push({ type: 'row', r: r }); });
    return out;
  }

  function tableCaption(view, club) {
    var n = (view && view.players) || 0;
    var what = club ? 'только матчи ' + clubGen(club) : 'Динамо и вся Экстралига';
    return spaced(n) + NBSP + Base.plural(n, 'игрок', 'игрока', 'игроков') + ' · ' + what;
  }

  /** Плашка про корону под фильтрами. */
  function tableCrownLine(view, club, periodKey, seasonTitle) {
    var team = club ? ' по матчам ' + clubGen(club) : '';
    if (periodKey === 'season') {
      return club
        ? 'В конце сезона первому — звание «Знаток ' + clubGen(club) + ' ' + (seasonTitle || '').replace(/^сезон /, '') + '».'
        : 'В конце сезона первому — звание «Знаток сезона ' + (seasonTitle || '').replace(/^сезон /, '') + '». Значок у имени — все короны игрока: месяцы, клубы, лиги.';
    }
    var title = periodLabel(periodKey).toLowerCase();
    var enough = view && view.players_with_points >= 3;
    if (!enough) return 'Корона за ' + title + team + ' появится, когда очки будут хотя бы у троих.';
    var me = view && view.me;
    var tail = me ? (me.rank === 1 ? ' Сейчас первое место твоё.' : ' До первого места — ' + Base.points((view && view.to_crown) || 0) + '.') : '';
    return 'Корона за ' + title + team + ' — у лидера после последнего матча месяца.' + tail;
  }

  /** Мало игроков с очками: таблица честная, короны нет. Позвать болельщиков клуба. */
  function fewPlayers(view, club, periodKey) {
    if (!view || view.players_with_points >= 3) return null;
    var n = view.players_with_points || 0;
    var label = sliceLabel(club, periodLabel(periodKey, '').toLowerCase());
    return {
      head: n ? label + ' — ' + n + NBSP + Base.plural(n, 'игрок', 'игрока', 'игроков') + ' с очками' : label + ' — пока никого',
      body: 'Таблица уже открыта. Корона появится, когда очки будут хотя бы у троих.',
      invite: 'Создать лигу и' + NBSP + 'позвать',
    };
  }

  /** Плашка вместо строки «ты», если в срезе нет моих ходов. */
  function noMeLine(club, periodKey, nowIso) {
    var closed = periodKey !== 'season' && periodKey !== monthKey(nowIso);
    if (closed) return 'В этом периоде у тебя не было ходов — загляни в другой';
    return 'Сделай первый ход' + (club ? ' на матч ' + clubGen(club) : '') + ' — и появишься в этой таблице';
  }

  function peakChip(p) {
    return sliceLabel(p.club, p.period_title) + ' · ' + p.rank + NBSP + 'место';
  }

  /** Плитка «Твоя вершина» на хабе. */
  function peakTile(p, crowns) {
    var isMonth = p.period !== 'season';
    var crowned = isMonth && (crowns || []).some(function (c) { return c.kind === 'month' && c.period === p.period && (c.club || null) === (p.club || null); });
    var note = crowned ? 'корона твоя' : p.rank === 1 ? 'лидируешь' : 'из ' + spaced(p.players);
    return { rank: String(p.rank), label: sliceLabel(p.club, p.period_title), note: note, gold: crowned || p.rank === 1 };
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

  function leagueCrownLine(l, tab, me, leaderPoints) {
    if (tab === 'month' && l.period) {
      var mon = periodLabel(l.period.key).toLowerCase();
      var base = 'Корону лиги за ' + mon + ' заберёт лидер после последнего матча месяца.';
      if (!me) return base;
      if (me.rank === 1) return base + ' Сейчас первое место твоё.';
      return base + ' Сейчас ты на ' + me.rank + '-м месте, до первого — ' + Base.points(Math.max(0, leaderPoints - me.points)) + '.';
    }
    if (l.term === 'season' || l.term === 'dates' || l.term === 'playoff') return 'Чемпиона лиги определим ' + endLabel(l.ends_at) + '. Короны за месяцы копятся у имени.';
    return 'Корону лиги заберёт лидер, когда лига закончится — ' + endLabel(l.ends_at) + '.';
  }

  function leagueMeta(l, members) {
    return leagueSub(l) + ' · ' + members + NBSP + Base.plural(members, 'человек', 'человека', 'человек');
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

  function seasonTitleLine(p, seasonLabelText) {
    var lines = [];
    if (p.overall) lines.push({ rank: p.overall.rank, label: 'Знаток сезона · все матчи', note: p.overall.to_first ? 'до 1-го места — ' + Base.points(p.overall.to_first) : 'первое место', total: p.overall.players });
    if (p.club_place && p.club) lines.push({ rank: p.club_place.rank, label: 'Знаток ' + clubGen(p.club.name) + ' ' + seasonLabelText, note: p.club_place.to_first ? 'до 1-го места — ' + Base.points(p.club_place.to_first) : 'первое место', total: p.club_place.players });
    return lines;
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
    tableCaption: tableCaption,
    tableCrownLine: tableCrownLine,
    fewPlayers: fewPlayers,
    noMeLine: noMeLine,
    peakChip: peakChip,
    peakTile: peakTile,
    crownCount: crownCount,
    scopeText: scopeText,
    termText: termText,
    leagueSub: leagueSub,
    termsBody: termsBody,
    termsError: termsError,
    formError: formError,
    termChoices: termChoices,
    scopePhrase: scopePhrase,
    termsSummary: termsSummary,
    leagueCrownLine: leagueCrownLine,
    leagueMeta: leagueMeta,
    inviteText: inviteText,
    crownLabel: crownLabel,
    seasonTitleLine: seasonTitleLine,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.KtoKogoScreens = api;
})(typeof window !== 'undefined' ? window : globalThis);
