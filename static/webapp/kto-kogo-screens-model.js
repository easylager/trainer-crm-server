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
  var SPELL = { 'Шахтер': 'Шахтёр', 'Могилев': 'Могилёв' };

  function pad(n) {
    return n < 10 ? '0' + n : String(n);
  }

  /** Имя клуба для глаз: в базе «Шахтер» без ё, на экране — «Шахтёр». В запросы уходит имя из базы. */
  function clubName(name) {
    return SPELL[name] || name || '';
  }

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

  function placeText(n) {
    return n == null ? '—' : String(n);
  }

  // ---------- «Если угадаешь» ----------

  /** Строки блока по ответу /stakes. Иконка: crown | up | duel. Места условные — «оценка по текущей таблице». */
  function stakeLines(items) {
    return (items || []).map(function (s) {
      var label = s.kind === 'league' ? 'Лига «' + s.league_name + '»' : sliceLabel(s.club, s.period_title);
      var move = s.rank_now == null ? 'выйдешь на ' + placeText(s.rank_if) : 'место ' + s.rank_now + ' → ' + (s.rank_now === s.rank_if ? '' : '~') + s.rank_if;
      return {
        icon: s.crown ? 'crown' : s.kind === 'league' ? 'duel' : 'up',
        gold: !!s.crown,
        text: label + ': ' + move + (s.crown ? ' · корона' : ''),
      };
    });
  }

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

  function liveWhy(pick, live) {
    if (!live) return 'Счёт появится, как только его прочитаем';
    if (live.home_score === live.away_score) return 'Ничья на табло — победитель решится в овертайме или по буллитам';
    var parts = liveParts(pick, live);
    return parts.length ? 'Сейчас: ' + parts.join(', ') : 'Пока мимо — до сирены всё может поменяться';
  }

  /** Время опроса счёта: «счёт на 19:42». */
  function liveStamp(live) {
    return live && live.updated_at ? 'счёт на ' + timeOnly(live.updated_at) : '';
  }

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

  /** Доли «за хозяев / за гостей» по всем ходам; без ходов — null. */
  function crowdShare(sides, names, nameOf) {
    var h = (sides && sides.home) || 0;
    var a = (sides && sides.away) || 0;
    if (h + a === 0) return null;
    var homePct = Math.round((100 * h) / (h + a));
    var side = h >= a ? 'home' : 'away';
    var pct = side === 'home' ? homePct : 100 - homePct;
    return { home: homePct, away: 100 - homePct, text: pct + '% игроков за ' + clubName(nameOf(side)) };
  }

  // ---------- козырь недели ----------

  /**
   * Состояние козыря на матче. doubles — ответ /matches: недели с козырем {week_start, match_id, locked}.
   * kind: nopick | on | free | other | locked | na.
   */
  function trumpState(m, doubles, nowIso) {
    var mine = m.my_pick;
    if (!mine) return { kind: 'nopick', label: 'Козырь ×2', note: 'сначала тапни за команду', on: false, usable: false };
    var wk = weekKey(m.starts_at);
    if (mine.doubled) return { kind: 'on', label: 'Козырь стоит', note: 'на этой неделе больше нет', on: true, usable: true };
    var d = (doubles || []).filter(function (x) { return x.week_start === wk; })[0];
    if (!d) return { kind: 'na', label: 'Козырь ×2', note: 'откроется ближе к неделе матча', on: false, usable: false };
    if (d.match_id && d.locked) return { kind: 'locked', label: 'Козырь ×2', note: 'козырь этой недели уже сыграл', on: false, usable: false };
    if (d.match_id && d.match_id !== m.id) return { kind: 'other', label: 'Козырь ×2', note: 'стоит на другом матче недели — тап перенесёт сюда', on: false, usable: true };
    var thisWeek = nowIso && weekKey(nowIso) === wk;
    return { kind: 'free', label: 'Козырь ×2', note: thisWeek ? 'есть до воскресенья' : 'на этой неделе свободен', on: false, usable: true };
  }

  /** Очки хода с учётом козыря: «+20 за победителя · точный счёт — до 50». */
  function pointsLine(pick) {
    if (!pick) return 'Тап за команду — и ход сделан';
    var k = pick.doubled ? 2 : 1;
    var exact = pick.home_score != null ? ' · до ' + 50 * k + ' за точный счёт' : ' · точный счёт — до ' + 50 * k;
    return '+' + 20 * k + ' за победителя' + exact + (pick.doubled ? ' · козырь' : '');
  }

  function questionLine(pick, teamName) {
    if (!pick) return 'Кто победит?';
    if (pick.home_score != null) return 'Ты за ' + teamName + ' · ' + pick.home_score + ':' + pick.away_score;
    return 'Ты за ' + teamName;
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

  /** Ближайший день с открытым матчем и все матчи этого дня; null — открытых матчей нет. */
  function dayMatches(list, now) {
    var open = (list || []).filter(function (m) { return m.open; }).sort(function (a, b) { return a.starts_at < b.starts_at ? -1 : 1; });
    if (!open.length) return null;
    var first = dayKey(open[0].starts_at);
    var items = (list || [])
      .filter(function (m) { return m.status !== 'cancelled' && dayKey(m.starts_at) === first; })
      .sort(function (a, b) { return a.starts_at < b.starts_at ? -1 : a.starts_at > b.starts_at ? 1 : a.id - b.id; });
    var openItems = items.filter(function (m) { return m.open; });
    var made = openItems.filter(function (m) { return m.my_pick; }).length;
    var wd = Base.minskParts(new Date(open[0].starts_at)).wd;
    var today = first === dayKey((now || new Date()).toISOString());
    return {
      day: first,
      today: today,
      wd: wd,
      items: items,
      total: openItems.length,
      made: made,
      heading: (today ? 'МАТЧИ ДНЯ · ' : 'БЛИЖАЙШИЕ МАТЧИ · ') + WEEKDAY_UP[wd],
    };
  }

  function dayCount(made, total) {
    if (!total) return '';
    if (total === 1) return made ? 'готово' : 'ход не сделан';
    return made === total ? 'все ' + total + ' — готово' : made + ' из ' + total;
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
    var who = x.club ? clubName(x.club) : 'всех';
    var matches = x.left + NBSP + Base.plural(x.left, 'матч', 'матча', 'матчей');
    if (x.crown && x.left > 0) return 'Корона месяца (' + month + ') твоя, если удержишь до ' + endLabel(x.ends_at) + ': впереди ещё ' + matches + ' ' + (x.club ? 'у ' + clubName(x.club) : 'в срезе') + '.';
    if (x.crown) return 'Это был последний матч среза «' + sliceLabel(x.club, month) + '»: корона появится после проверки итога.';
    if (x.left > 0) return 'До короны месяца (' + month + ') ' + Base.points(x.to_crown || 0) + ': впереди ещё ' + matches + ' ' + (x.club ? 'у ' + clubName(x.club) : 'в срезе') + '.';
    return 'Срез «' + sliceLabel(x.club, month) + '» отыгран' + (who ? '' : '') + '.';
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
    return movesWord(r.played) + (r.correct_percent == null ? '' : ' · угадано ' + r.correct_percent + '%');
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
    var what = club ? 'только матчи ' + clubName(club) : 'Динамо и вся Экстралига';
    return spaced(n) + NBSP + Base.plural(n, 'игрок', 'игрока', 'игроков') + ' · ' + what;
  }

  /** Плашка про корону под фильтрами. */
  function tableCrownLine(view, club, periodKey, seasonTitle) {
    var team = club ? ' · ' + clubName(club) : '';
    if (periodKey === 'season') {
      return club
        ? 'В конце сезона первому — звание «Знаток ' + clubName(club) + ' ' + (seasonTitle || '').replace(/^сезон /, '') + '».'
        : 'В конце сезона первому — звание «Знаток сезона ' + (seasonTitle || '').replace(/^сезон /, '') + '». Значок у имени — все короны игрока: месяцы, клубы, лиги.';
    }
    var title = periodLabel(periodKey).toLowerCase();
    var enough = view && view.players_with_points >= 3;
    if (!enough) return 'Корона ' + title + team + ' появится, когда очки будут хотя бы у троих.';
    var me = view && view.me;
    var tail = me ? (me.rank === 1 ? ' Сейчас она твоя.' : ' До неё ' + Base.points((view && view.to_crown) || 0) + '.') : '';
    return 'Корона ' + title + team + ' — первому после последнего матча месяца.' + tail;
  }

  /** Мало игроков с очками: таблица честная, короны нет. Позвать болельщиков клуба. */
  function fewPlayers(view, club, periodKey) {
    if (!view || view.players_with_points >= 3) return null;
    var n = view.players_with_points || 0;
    var label = sliceLabel(club, periodLabel(periodKey, '').toLowerCase());
    return {
      head: n ? label + ' — ' + n + NBSP + Base.plural(n, 'игрок', 'игрока', 'игроков') + ' с очками' : label + ' — пока никого',
      body: 'Таблицу видно честно, а корона появится, когда очки будут хотя бы у троих.',
      invite: club ? 'Позвать болельщиков ' + clubName(club) : 'Позвать друзей',
    };
  }

  /** Плашка вместо строки «ты», если в срезе нет моих ходов. */
  function noMeLine(club, periodKey, nowIso) {
    var closed = periodKey !== 'season' && periodKey !== monthKey(nowIso);
    if (closed) return 'В этом срезе у тебя не было ходов — загляни в другой период';
    return 'Сделай первый ход' + (club ? ' на матч ' + clubName(club) : '') + ' — и появишься в этой таблице';
  }

  function peakChip(p) {
    return sliceLabel(p.club, p.period_title) + ' · ' + p.rank + NBSP + 'место';
  }

  /** Плитка «Твоя вершина» на хабе. */
  function peakTile(p, crowns) {
    var isMonth = p.period !== 'season';
    var crowned = isMonth && (crowns || []).some(function (c) { return c.kind === 'month' && c.period === p.period && (c.club || null) === (p.club || null); });
    var note = crowned ? 'корона твоя' : p.rank === 1 ? 'лидер среза' : 'из ' + spaced(p.players);
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
    return dateLabel(l.starts_at) + ' – ' + endLabel(l.ends_at);
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

  function formError(form) {
    if (form.scope === 'pick' && !form.clubs.length) return 'Нужна команда';
    if (form.term === 'dates') {
      if (!form.startsOn || !form.endsOn) return 'Укажи даты';
      if (form.endsOn <= form.startsOn) return 'Конец раньше начала';
    }
    return '';
  }

  /** «Как будет»: что считаем, когда и сколько матчей. preview — ответ terms-preview или null. */
  function termsSummary(form, preview) {
    var what;
    if (form.scope === 'all') what = 'Все матчи: Динамо-Минск и вся Экстралига';
    else if (form.scope === 'extraliga') what = 'Вся Экстралига, без Динамо-Минск';
    else if (form.scope === 'dinamo') what = 'Только матчи Динамо-Минск в КХЛ';
    else what = form.clubs.length ? 'Матчи: ' + scopeText('clubs', form.clubs).replace(/, /g, ', ') : 'Выбери хотя бы одну команду';
    var when = '';
    var few = false;
    if (preview && preview.ends_at) {
      var count = preview.matches_in_term;
      what += ' · ещё ' + count + NBSP + Base.plural(count, 'матч', 'матча', 'матчей') + ' в срок';
      var rolling = form.term === 'season' || form.term === 'dates' || form.term === 'playoff';
      when = 'С ' + dateLabel(preview.starts_at) + ' по ' + endLabel(preview.ends_at) + (rolling ? ' · корона каждый месяц и чемпион лиги в конце' : ' · корона победителю в конце');
      few = !!preview.few_matches;
    }
    return { what: what, when: when, few: few ? 'Матчей в сроке мало — таблица будет почти пустой. Можно взять срок подлиннее.' : '' };
  }

  // ---------- лига изнутри ----------

  function leagueCrownLine(l, tab, me, leaderPoints) {
    if (tab === 'month' && l.period) {
      var mon = periodLabel(l.period.key).toLowerCase();
      var key = l.period.key;
      var base = 'Корона лиги за ' + mon + ' — ' + monthEndLabel(key) + '.';
      if (!me) return base;
      if (me.rank === 1) return base + ' Сейчас она твоя.';
      return base + ' Твоё место ' + me.rank + ', до первого ' + Base.points(Math.max(0, leaderPoints - me.points)) + '.';
    }
    if (l.term === 'season' || l.term === 'dates' || l.term === 'playoff') return 'Чемпион лиги — ' + endLabel(l.ends_at) + '. Месячные короны копятся рядом с именем.';
    return 'Корона лиги — ' + endLabel(l.ends_at) + ', в конце срока.';
  }

  function leagueMeta(l, members) {
    return leagueSub(l) + ' · ' + members + NBSP + Base.plural(members, 'человек', 'человека', 'человек');
  }

  function inviteText(name, l) {
    var what = l ? scopeText(l.scope, l.clubs) : 'Динамо-Минск';
    return 'Угадываем матчи (' + what + ') в лиге «' + name + '». Тапни за команду — посмотрим, кто кого.';
  }

  // ---------- карточка болельщика ----------

  function crownLabel(c) {
    var month = c.period ? cap(MONTH_NOM[Number(c.period.slice(5, 7)) - 1]) : '';
    if (c.kind === 'league_term') return 'Чемпион лиги «' + (c.league_name || '') + '»';
    if (c.kind === 'league_month') return month + ' · лига «' + (c.league_name || '') + '»';
    return month + ' · ' + (c.club ? 'болельщики ' + clubName(c.club) : 'все игроки');
  }

  function seasonTitleLine(p, seasonLabelText) {
    var lines = [];
    if (p.overall) lines.push({ rank: p.overall.rank, label: 'Знаток сезона · все матчи', note: p.overall.to_first ? 'до 1-го ' + p.overall.to_first : 'впереди', total: p.overall.players });
    if (p.club_place && p.club) lines.push({ rank: p.club_place.rank, label: 'Знаток ' + clubName(p.club.name) + ' ' + seasonLabelText, note: p.club_place.to_first ? 'до 1-го ' + p.club_place.to_first : 'впереди', total: p.club_place.players });
    return lines;
  }

  var api = {
    clubName: clubName,
    clubShort: clubShort,
    seasonTitleFor: seasonTitleFor,
    dayKey: dayKey,
    weekKey: weekKey,
    monthKey: monthKey,
    dateLabel: dateLabel,
    endLabel: endLabel,
    timeOnly: timeOnly,
    monthEndLabel: monthEndLabel,
    sliceLabel: sliceLabel,
    stakeLines: stakeLines,
    stakesEmpty: stakesEmpty,
    livePlaces: livePlaces,
    pickPoints: pickPoints,
    livePoints: livePoints,
    liveParts: liveParts,
    liveWhy: liveWhy,
    liveStamp: liveStamp,
    duelLive: duelLive,
    duelPill: duelPill,
    duelFinal: duelFinal,
    crowdShare: crowdShare,
    trumpState: trumpState,
    pointsLine: pointsLine,
    questionLine: questionLine,
    dayMatches: dayMatches,
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
    formError: formError,
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
