/**
 * TASK-334 S5: «Кто кого», зимняя модель экранов — срезы, «Если угадаешь», живые очки, козырь, лиги.
 *
 * Run: TZ=UTC node --test tests/js/kto-kogo-screens-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
require('../../static/webapp/kto-kogo-model.js');
const S = require('../../static/webapp/kto-kogo-screens-model.js');

const NBSP = '\u00a0';
const NOW = new Date('2026-11-06T09:00:00Z'); // пятница, 12:00 в Минске

describe('даты и подписи', () => {
  it('неделя козыря — понедельник по Минску, в ночь на понедельник — уже новая неделя', () => {
    assert.equal(S.weekKey('2026-11-06T16:00:00Z'), '2026-11-02');
    assert.equal(S.weekKey('2026-11-08T20:59:00Z'), '2026-11-02'); // вс 23:59 Минск
    assert.equal(S.weekKey('2026-11-08T21:00:00Z'), '2026-11-09'); // пн 00:00 Минск
  });
  it('месяц и конец срока включительно', () => {
    assert.equal(S.monthKey('2026-11-30T21:30:00Z'), '2026-12'); // 1 декабря по Минску
    assert.equal(S.endLabel('2026-08-01T00:00:00+03:00'), '31' + NBSP + 'июля');
    assert.equal(S.monthEndLabel('2026-11'), '30' + NBSP + 'ноября');
  });
  it('«Шахтер» в базе — «Шахтёр» на экране; срез — «Клуб · период»', () => {
    assert.equal(S.clubName('Шахтер'), 'Шахтёр');
    assert.equal(S.clubGen('Юность'), 'Юности');
    assert.equal(S.clubGen('Динамо-Минск'), 'Динамо-Минск');
    assert.equal(S.clubGen('Новая Команда'), 'Новая Команда');
    assert.equal(S.clubShort('Динамо-Минск'), 'Динамо');
    assert.equal(S.clubShort('Могилев'), 'Могилёв');
    assert.equal(S.seasonTitleFor('2026-11-06T09:00:00Z'), 'сезон 2026/27');
    assert.equal(S.seasonTitleFor('2027-03-06T09:00:00Z'), 'сезон 2026/27');
    assert.equal(S.seasonTitleFor('2027-08-02T09:00:00Z'), 'сезон 2027/28');
    assert.equal(S.sliceLabel('Юность', 'ноябрь'), 'Юность · ноябрь');
    assert.equal(S.sliceLabel(null, 'сезон 2026/27'), 'Все · сезон');
  });
});

describe('«Если угадаешь»', () => {
  it('срез с короной — золотая строка, лиги и места — условные', () => {
    const lines = S.stakeLines([
      { kind: 'slice', club: 'Юность', period_title: 'ноябрь', rank_now: 3, rank_if: 1, crown: true },
      { kind: 'slice', club: null, period_title: 'сезон 2026/27', rank_now: 214, rank_if: 190, crown: false },
      { kind: 'league', league_name: 'Офис', rank_now: 3, rank_if: 2, crown: false },
    ]);
    assert.deepEqual(lines.map((l) => l.icon), ['crown', 'up', 'duel']);
    assert.equal(lines[0].gold, true);
    assert.equal(lines[0].text, 'Юность · ноябрь: 3-е → около 1-го · корона');
    assert.equal(lines[1].text, 'Все · сезон: 214-е → около 190-го');
    assert.equal(lines[2].text, 'Лига «Офис»: 3-е → около 2-го');
  });
  it('новичок без места: «станешь N-м»', () => {
    const [l] = S.stakeLines([{ kind: 'slice', club: 'Лида', period_title: 'ноябрь', rank_now: null, rank_if: 2, crown: false }]);
    assert.equal(l.text, 'Лида · ноябрь: станешь 2-м');
  });
});

describe('места вживую', () => {
  it('победитель угадан сейчас — места с выигрышем, иначе прежние', () => {
    const items = [
      { kind: 'slice', club: 'Юность', period_title: 'ноябрь', rank_now: 2, rank_if: 1, crown: true },
      { kind: 'league', league_name: 'Офис', rank_now: 3, rank_if: 2, crown: false },
    ];
    const win = S.livePlaces(items, true);
    assert.deepEqual(win.map((r) => [r.from, r.to, r.tone, r.crown]), [['2', '1', 'up', true], ['3', '2', 'up', false]]);
    const hold = S.livePlaces(items, false);
    assert.deepEqual(hold.map((r) => [r.from, r.to, r.tone, r.crown]), [['2', '2', 'same', false], ['3', '3', 'same', false]]);
  });
});

describe('очки и живой счёт', () => {
  const pick = (side, h, a, doubled) => ({ side, home_score: h, away_score: a, doubled: !!doubled });
  it('очки как у сервера: 20 / 10 / 10 / 10 / 50', () => {
    assert.equal(S.pickPoints(pick('home', 3, 2), 3, 2), 50);
    assert.equal(S.pickPoints(pick('home', 4, 2), 3, 2), 30); // победитель + шайбы гостей; разница 2 против 1 мимо
    assert.equal(S.pickPoints(pick('home', 2, 1), 3, 2), 30); // победитель + разница
    assert.equal(S.pickPoints(pick('home', null, null), 3, 2), 20);
    assert.equal(S.pickPoints(pick('away', 2, 3), 3, 2), 0);
  });
  it('шайбы засчитываются и при неугаданном победителе', () => {
    assert.equal(S.pickPoints(pick('away', 1, 2), 3, 2), 10); // гости 2 = 2
    assert.equal(S.pickPoints(pick('away', 3, 4), 3, 2), 10); // хозяева 3 = 3
  });
  it('ничья на табло: очков нет, победителя ещё нет', () => {
    assert.equal(S.livePoints(pick('home', 3, 2), { home_score: 1, away_score: 1 }), null);
    assert.match(S.liveWhy(pick('home', 3, 2), { home_score: 1, away_score: 1 }), /Пока ничья — победителя ещё нет/);
  });
  it('козырь удваивает живые очки', () => {
    assert.equal(S.livePoints(pick('home', null, null, true), { home_score: 2, away_score: 1 }), 40);
  });
  it('из чего сложились очки', () => {
    assert.deepEqual(S.liveParts(pick('home', 3, 2), { home_score: 2, away_score: 1 }), ['победитель', 'разница']);
    assert.deepEqual(S.liveParts(pick('home', 3, 2), { home_score: 3, away_score: 2 }), ['точный счёт']);
    assert.equal(S.liveWhy(pick('home', 3, 2), { home_score: 0, away_score: 4 }), 'Пока мимо — до сирены всё может поменяться');
    const names = { home: 'Динамо', away: 'СКА' };
    assert.equal(S.liveWhy(pick('home', 3, 1), { home_score: 2, away_score: 1 }, names), 'Пока сходится: Динамо впереди. До «в точку» не хватает одной шайбы.');
    assert.equal(S.liveWhy(pick('home', 4, 1), { home_score: 2, away_score: 1 }, names), 'Пока сходится: Динамо впереди. До «в точку» не хватает 2\u00a0шайбы.');
    assert.match(S.liveWhy(pick('home', 2, 1), { home_score: 2, away_score: 1 }, names), /«в точку»/);
    assert.equal(S.liveWhy({ side: 'home', home_score: null }, { home_score: 2, away_score: 1 }, names), 'Пока сходится: Динамо впереди.');
    assert.equal(S.liveWhy(pick('home', 3, 2), null), 'Счёт обновляется раз в 15\u00a0минут');
    // Шайб на табло уже больше, чем в ходе: «в точку» не выйдет.
    assert.equal(S.liveWhy(pick('home', 3, 1), { home_score: 4, away_score: 1 }, names), 'Пока сходится: Динамо впереди. «В точку» уже не выйдет.');
  });
  it('метка времени опроса — по Минску', () => {
    assert.equal(S.liveStamp({ updated_at: '2026-11-06T16:42:00Z' }), 'счёт на 19:42');
    assert.equal(S.liveStamp(null), '');
  });
  it('дуэль на живом счёте: веду, отстаю, ровно', () => {
    const live = { home_score: 2, away_score: 1 };
    assert.equal(S.duelLive(pick('home', 3, 2), pick('away', 1, 3), live).state, 'lead');
    assert.equal(S.duelLive(pick('away', 1, 3), pick('home', 3, 2), live).state, 'trail');
    assert.equal(S.duelLive(pick('home', null, null), pick('home', null, null), live).state, 'even');
  });
  it('метка дуэли до старта и итог дуэли', () => {
    assert.deepEqual(S.duelPill('home', 'away'), { label: 'ДУЭЛЬ', hot: true });
    assert.deepEqual(S.duelPill('home', 'home'), { label: 'ДУЭЛЬ НА СЧЁТ', hot: false });
    assert.equal(S.duelFinal(50, 0), 'win');
    assert.equal(S.duelFinal(0, 10), 'lose');
    assert.equal(S.duelFinal(20, 20), 'tie');
    assert.equal(S.duelFinal(null, 20), null);
  });
  it('кто за кого: люди, а не проценты — «Я», друзья, «+N» из счётчика сторон', () => {
    const mk = (over) => Object.assign({ sides: { home: 15, away: 4 }, my_pick: { side: 'home' }, friend_moves: [
      { display_name: 'Аня К.', side: 'home' }, { display_name: 'Петя', side: 'home' }, { display_name: 'Лёша', side: 'away' }, { display_name: 'Оля', side: 'home' },
    ] }, over || {});
    const home = S.crowdPeople(mk(), 'home');
    assert.deepEqual(home.faces.map((f) => f.initial), ['Я', 'А', 'П']);
    assert.equal(home.faces[0].me, true);
    assert.equal(home.more, 12);
    assert.equal(home.caption, 'Ты, Аня, Петя и\u00a0ещё\u00a012');
    const away = S.crowdPeople(mk(), 'away');
    assert.deepEqual(away.faces.map((f) => f.initial), ['Л']);
    assert.equal(away.caption, 'Лёша и\u00a0ещё\u00a03');
    assert.equal(S.crowdPeople({ sides: { home: 0, away: 0 }, friend_moves: [] }, 'home').caption, 'Пока никого');
    assert.equal(S.crowdPeople({ sides: { home: 5, away: 0 }, friend_moves: [] }, 'home').caption, '5\u00a0игроков');
    // Сервер отстал со счётчиком — людей не меньше, чем названных.
    assert.equal(S.crowdPeople(mk({ sides: { home: 1, away: 0 } }), 'home').total, 3);
    const all = JSON.stringify([home, away, S.CROWD_NOTE]);
    assert.ok(!/%|процент/i.test(all), all);
  });
});

describe('козырь недели', () => {
  const m = (id, over) => Object.assign({ id, starts_at: '2026-11-07T16:00:00Z', my_pick: { side: 'home', doubled: false } }, over || {});
  const week = [{ week_start: '2026-11-02', match_id: null, locked: false }];
  it('без хода козырь не ставится', () => {
    assert.equal(S.trumpState(m(1, { my_pick: null }), week).kind, 'nopick');
  });
  it('свободен, стоит здесь, стоит на другом матче, уже сыграл, недели нет', () => {
    assert.equal(S.trumpState(m(1), week, NOW.toISOString()).kind, 'free');
    assert.equal(S.trumpState(m(1), week, NOW.toISOString()).note, 'один на неделю: очки за этот матч удвоятся');
    assert.equal(S.trumpState(m(1, { my_pick: { side: 'home', doubled: true } }), week).kind, 'on');
    assert.equal(S.trumpState(m(1), [{ week_start: '2026-11-02', match_id: 9, locked: false }]).kind, 'other');
    assert.equal(S.trumpState(m(1), [{ week_start: '2026-11-02', match_id: 9, locked: true }]).usable, false);
    assert.equal(S.trumpState(m(1, { starts_at: '2026-11-20T16:00:00Z' }), week).kind, 'na');
  });
  it('до матча в подписи хода нет чисел очков, козырь — словами', () => {
    assert.equal(S.pointsLine(null), 'Тап за команду — и ход сделан');
    assert.equal(S.questionLine({ side: 'home', home_score: 3, away_score: 2 }, 'Юность'), 'Твой ход: 3:2');
    assert.equal(S.questionLine({ side: 'home', home_score: null }, 'Юность'), 'Твой ход: за\u00a0Юность');
    assert.equal(S.trumpLabel(false), 'Козырь');
    assert.equal(S.trumpLabel(true), 'Козырь здесь');
    for (const k of ['nopick', 'on', 'free', 'other', 'locked', 'na']) {
      const pick = k === 'nopick' ? null : { side: 'home', doubled: k === 'on' };
      const doubles = k === 'na' ? [] : [{ week_start: '2026-11-02', match_id: k === 'other' || k === 'locked' ? (k === 'other' ? 9 : 1) : null, locked: k === 'locked' }];
      const st = S.trumpState(m(1, { my_pick: pick }), doubles, NOW.toISOString());
      assert.equal(st.label, S.trumpLabel(k === 'on'), k);
    }
  });
});

describe('матчи дня и пауза', () => {
  const mk = (id, iso, extra) => Object.assign({ id, starts_at: iso, open: true, status: 'scheduled', league: 'extraliga', my_pick: null, home_team: 'A', away_team: 'B' }, extra || {});
  it('берёт ближайший день с открытым матчем; закрытые того же дня остаются в списке', () => {
    const list = [mk(1, '2026-11-05T16:00:00Z', { open: false, status: 'final' }), mk(2, '2026-11-06T15:30:00Z', { my_pick: { side: 'home' } }), mk(3, '2026-11-06T16:00:00Z'), mk(4, '2026-11-06T11:00:00Z', { open: false }), mk(5, '2026-11-07T16:00:00Z')];
    const d = S.dayMatches(list, NOW);
    assert.equal(d.heading, 'ЭКСТРАЛИГА · СЕГОДНЯ, ПТ 6 НОЯБРЯ');
    assert.deepEqual(d.items.map((x) => x.id), [4, 2, 3]);
    assert.equal(d.total, 2);
    assert.equal(d.made, 1);
    assert.equal(S.dayCount(d.made, d.total), '1 из 2');
    assert.equal(S.dayCount(2, 2), 'все ходы сделаны');
  });
  it('нет матчей сегодня — «ближайшие» с днём недели; нет открытых — null', () => {
    const d = S.dayMatches([mk(1, '2026-11-10T16:00:00Z')], NOW);
    assert.equal(d.heading, 'ЭКСТРАЛИГА · ВТ 10 НОЯБРЯ');
    assert.equal(S.dayMatches([mk(1, '2026-11-10T16:00:00Z', { open: false })], NOW), null);
  });
  it('пауза Экстралиги: следующий матч дальше трёх дней; календаря нет — паузы нет', () => {
    assert.deepEqual(S.pauseInfo([mk(1, '2026-11-09T16:00:00Z')], NOW), { until: '9' + NBSP + 'ноября' });
    assert.equal(S.pauseInfo([mk(1, '2026-11-07T16:00:00Z')], NOW), null);
    assert.equal(S.pauseInfo([], NOW), null);
    assert.equal(S.pauseInfo([mk(1, '2026-11-20T16:00:00Z', { league: 'khl' })], NOW), null);
  });
  it('следующий ход: свои клубы раньше чужих', () => {
    const done = { id: 1, home_team: 'Юность', away_team: 'Шахтер' };
    const list = [mk(2, '2026-11-07T16:00:00Z', { home_team: 'Лида', away_team: 'Брест' }), mk(3, '2026-11-09T16:00:00Z', { home_team: 'Неман', away_team: 'Юность' })];
    assert.equal(S.nextMatch(list, done).id, 3);
    assert.equal(S.nextMatch([list[0]], done).id, 2);
    assert.equal(S.nextMatch([], done), null);
  });
});

describe('итог и движение', () => {
  it('голова итога по очкам, строки движения с короной', () => {
    assert.equal(S.resultHead(50), 'В точку!');
    assert.equal(S.resultHead(0), 'Мимо');
    assert.equal(S.resultHead(30), 'Почти в точку');
    assert.equal(S.resultHead(20), 'Есть победитель');
    const rows = S.movementRows([
      { kind: 'slice', club: 'Юность', period_title: 'ноябрь', rank_before: 2, rank_after: 1, crown: true },
      { kind: 'slice', club: null, period_title: 'сезон 2026/27', rank_before: 214, rank_after: 214, crown: false },
      { kind: 'league', league_name: 'Офис', rank_before: 1, rank_after: 3, crown: false },
      { kind: 'slice', club: 'Лида', period_title: 'ноябрь', rank_before: null, rank_after: 2, crown: false },
    ]);
    assert.deepEqual(rows.map((r) => r.tone), ['up', 'same', 'down', 'up']);
    assert.equal(rows[0].crown, true);
    assert.equal(rows[2].label, 'Лига «Офис»');
    assert.equal(rows[3].from, '—');
  });
  it('корона месяца: держишь, не хватает, последний матч', () => {
    const base = { kind: 'slice', club: 'Юность', period_title: 'ноябрь', ends_at: '2026-11-30T21:00:00Z', crown: true, left: 3, to_crown: 0 };
    assert.match(S.crownLineAfter([base]), /Корона за ноябрь пока твоя\. Впереди ещё 3.матча Юности — удержи до 30.ноября\./);
    assert.match(S.crownLineAfter([Object.assign({}, base, { crown: false, to_crown: 10 })]), /^До короны за ноябрь — 10.очков\. Впереди ещё 3.матча Юности\.$/);
    assert.match(S.crownLineAfter([Object.assign({}, base, { left: 0 })]), /последний матч/);
    assert.equal(S.crownLineAfter([{ kind: 'league' }]), '');
  });
});

describe('таблица', () => {
  const r = (rank, over) => Object.assign({ rank, display_name: 'И' + rank, points: 100 - rank, exact: 0, played: rank, correct_percent: 60, crowns: 0, is_me: false }, over || {});
  it('выше шестого места — шесть строк; ниже — пять, разрыв и соседи', () => {
    const items = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => r(n));
    assert.equal(S.tableRows({ items, me: r(3, { is_me: true }), neighbors: [] }).length, 6);
    assert.equal(S.tableRows({ items, me: null, neighbors: [] }).length, 6);
    const rows = S.tableRows({ items, me: r(214, { is_me: true }), neighbors: [r(213), r(214, { is_me: true }), r(215)] });
    assert.deepEqual(rows.map((x) => (x.type === 'gap' ? 'gap' : x.r.rank)), [1, 2, 3, 4, 5, 'gap', 213, 214, 215]);
    const near = S.tableRows({ items, me: r(7, { is_me: true }), neighbors: [r(6), r(7, { is_me: true }), r(8)] });
    assert.deepEqual(near.map((x) => (x.type === 'gap' ? 'gap' : x.r.rank)), [1, 2, 3, 4, 5, 6, 7, 8]);
  });
  it('подпись строки, шапка, периоды', () => {
    assert.equal(S.rowSub(r(1, { played: 34, exact: 2, correct_percent: 64 })), '34' + NBSP + 'хода · 2' + NBSP + 'в' + NBSP + 'точку');
    assert.equal(S.rowSub(r(1, { played: 12, exact: 0, correct_percent: 67 })), '12' + NBSP + 'ходов');
    assert.equal(S.rowSub(r(1, { played: 1, correct_percent: null })), '1' + NBSP + 'ход');
    assert.equal(S.tableCaption({ players: 1380 }, null), '1' + NBSP + '380' + NBSP + 'игроков · Динамо и вся Экстралига');
    assert.equal(S.tableCaption({ players: 3 }, 'Шахтер'), '3' + NBSP + 'игрока · только матчи Шахтёра');
    const periods = S.periodChoices('сезон 2026/27', '2026-12-10T09:00:00Z', [{ kind: 'month', period: '2026-11', club: null }]);
    assert.deepEqual(periods.map((p) => p.key), ['season', '2026-12', '2026-11']);
    assert.deepEqual(periods.map((p) => p.note), ['все матчи сезона', 'идёт', 'закрыт']);
    assert.equal(periods[2].crown, true);
    assert.equal(periods[1].crown, false);
    assert.equal(periods[0].label, 'Сезон 2026/27');
  });
  it('мало игроков: честная плашка и приглашение; три и больше — без плашки', () => {
    const few = S.fewPlayers({ players_with_points: 2 }, 'Лида', '2026-11');
    assert.match(few.head, /^Лида · ноябрь — 2.игрока с очками$/);
    assert.equal(few.invite, 'Создать лигу и\u00a0позвать');
    assert.equal(S.fewPlayers({ players_with_points: 3 }, 'Лида', '2026-11'), null);
    assert.match(S.fewPlayers({ players_with_points: 0 }, null, 'season').head, /пока никого/);
  });
  it('плашка новичка: сезон и текущий месяц — «первый ход», закрытый месяц — «не было ходов»', () => {
    assert.match(S.noMeLine(null, 'season', '2026-11-06T09:00:00Z'), /^Сделай первый ход/);
    assert.match(S.noMeLine('Юность', '2026-11', '2026-11-06T09:00:00Z'), /на матч Юности/);
    assert.match(S.noMeLine(null, '2026-10', '2026-11-06T09:00:00Z'), /не было ходов/);
  });
  it('строка про корону: порог трёх, моё положение, звание сезона', () => {
    const view = { players_with_points: 5, me: { rank: 3 }, to_crown: 20 };
    assert.match(S.tableCrownLine(view, 'Юность', '2026-11', 'сезон 2026/27'), /^Корона за ноябрь по матчам Юности — тому, кто будет первым после последнего матча месяца\. До первого места — 20.очков\.$/);
    assert.match(S.tableCrownLine({ players_with_points: 5, me: { rank: 1 }, to_crown: 0 }, null, '2026-11', ''), /Сейчас первое место твоё/);
    assert.match(S.tableCrownLine({ players_with_points: 2 }, null, '2026-11', ''), /хотя бы у троих/);
    assert.match(S.tableCrownLine(view, null, 'season', 'сезон 2026/27'), /Знаток сезона 2026\/27/);
    assert.match(S.tableCrownLine(view, 'Юность', 'season', 'сезон 2026/27'), /Знаток Юности 2026\/27/);
  });
  it('вершины: чип и плитка, корона записью', () => {
    const p = { club: 'Юность', period: '2026-11', period_title: 'ноябрь', rank: 2, players: 38 };
    assert.equal(S.peakChip(p), 'Юность · ноябрь · 2' + NBSP + 'место');
    assert.deepEqual(S.peakTile(p, []), { rank: '2', label: 'Юность · ноябрь', note: 'из 38', gold: false });
    const crown = [{ kind: 'month', period: '2026-11', club: 'Юность' }];
    assert.equal(S.peakTile(Object.assign({}, p, { rank: 1 }), crown).note, 'корона твоя');
    assert.equal(S.peakTile(Object.assign({}, p, { rank: 1 }), []).note, 'лидируешь');
    assert.equal(S.crownCount(2), '2' + NBSP + 'короны');
  });
});

describe('лиги', () => {
  const league = { scope: 'clubs', clubs: ['Юность', 'Динамо-Минск'], term: 'season', starts_at: '2026-11-06T00:00:00Z', ends_at: '2027-07-31T21:00:00Z' };
  it('подпись: команды и срок', () => {
    assert.equal(S.leagueSub(league), 'Юность и Динамо-Минск · до 31' + NBSP + 'июля');
  });
  it('команды: все, Экстралига, Динамо, больше двух', () => {
    assert.equal(S.scopeText('all'), 'Все матчи');
    assert.equal(S.scopeText('extraliga'), 'Вся Экстралига');
    assert.equal(S.scopeText('dinamo'), 'Динамо-Минск');
    assert.equal(S.scopeText('clubs', ['Юность', 'Неман', 'Лида', 'Брест']), 'Юность, Неман и ещё 2');
  });
  it('тело запроса: «выбрать» → clubs, месяц — текущий, свои даты', () => {
    const f = { scope: 'pick', clubs: ['Юность'], term: 'month', startsOn: '', endsOn: '' };
    assert.deepEqual(S.termsBody(f, '2026-11-06T09:00:00Z'), { scope: 'clubs', clubs: ['Юность'], term: 'month', month: '2026-11' });
    assert.deepEqual(S.termsBody({ scope: 'all', clubs: ['Юность'], term: 'weeks4' }, 'x'), { scope: 'all', clubs: [], term: 'weeks4' });
    assert.deepEqual(S.termsBody({ scope: 'dinamo', clubs: [], term: 'dates', startsOn: '2026-11-10', endsOn: '2026-12-01' }, 'x'), { scope: 'dinamo', clubs: [], term: 'dates', starts_on: '2026-11-10', ends_on: '2026-12-01' });
  });
  it('кнопка формы говорит, чего не хватает: название, команда, даты', () => {
    assert.equal(S.formError({ name: '', scope: 'all', clubs: [], term: 'season' }), 'Назови лигу');
    assert.equal(S.formError({ name: 'Офис', scope: 'pick', clubs: [], term: 'season' }), 'Выбери команду');
    assert.equal(S.formError({ name: 'Офис', scope: 'all', clubs: [], term: 'dates', startsOn: '', endsOn: '' }), 'Укажи даты');
    assert.equal(S.formError({ name: 'Офис', scope: 'all', clubs: [], term: 'dates', startsOn: '2026-12-01', endsOn: '2026-11-01' }), 'Конец раньше начала');
    assert.equal(S.formError({ name: 'Офис', scope: 'all', clubs: [], term: 'season' }), '');
    // Название не мешает превью «Как будет»: окно дат можно показать и без него.
    assert.equal(S.termsError({ name: '', scope: 'all', clubs: [], term: 'season' }), '');
  });
  it('сроки с сервера: подписи окон и корона по флагу, «Свои даты» всегда есть', () => {
    const opts = {
      items: [
        { term: 'season', starts_at: '2026-08-01T00:00:00Z', ends_at: '2027-07-31T21:00:00Z', monthly_crowns: true },
        { term: 'month', starts_at: '2026-11-01T00:00:00Z', ends_at: '2026-11-30T21:00:00Z', monthly_crowns: false },
        { term: 'weeks4', starts_at: '2026-11-03T00:00:00Z', ends_at: '2026-11-30T21:00:00Z', monthly_crowns: false },
        { term: 'playoff', starts_at: '2027-03-01T00:00:00Z', ends_at: '2027-05-31T21:00:00Z', monthly_crowns: false },
      ],
      season_ends_at: '2027-07-31T21:00:00Z',
      max_clubs: 20,
    };
    const ch = S.termChoices(opts);
    assert.deepEqual(ch.map((c) => c.term), ['season', 'month', 'weeks4', 'playoff', 'dates']);
    assert.equal(ch[0].label, 'До конца сезона');
    assert.match(ch[0].sub, /по 31.июля · корона каждый месяц/);
    assert.equal(ch[1].label, 'Ноябрь');
    assert.match(ch[1].sub, /одна корона в конце/);
    assert.match(ch[2].sub, /с сегодняшнего дня по 30.ноября/);
    assert.match(ch[3].sub, /1.марта.–.31.мая/);
    assert.match(ch[4].sub, /не дальше 31.июля/);
    // Плей-офф кончился — сервер его не прислал: в списке его нет.
    const noPo = S.termChoices({ items: opts.items.slice(0, 3), season_ends_at: opts.season_ends_at });
    assert.deepEqual(noPo.map((c) => c.term), ['season', 'month', 'weeks4', 'dates']);
  });
  it('«Как будет»: название, матчи, окно, короны, новички', () => {
    const f = { name: 'Офис', scope: 'pick', clubs: ['Юность'], term: 'weeks4' };
    const prev = { starts_at: '2026-11-05T21:00:00Z', ends_at: '2026-12-03T21:00:00Z', matches_in_term: 3, few_matches: true, monthly_crowns: false };
    const s = S.termsSummary(f, prev);
    assert.equal(s.title, '«Офис»');
    assert.equal(s.what, 'Матчи: Юность');
    assert.match(s.when, /^С 6.ноября по 3.декабря · впереди 3.матча$/);
    assert.equal(s.crowns, 'Корона чемпиону в конце.');
    assert.match(s.few, /мало/);
    assert.match(s.note, /вступит позже/);
    assert.equal(S.termsSummary({ name: '', scope: 'pick', clubs: [], term: 'season' }, null).what, 'Выбери хотя бы одну команду');
    const monthly = S.termsSummary({ name: 'X', scope: 'dinamo', clubs: [], term: 'season' }, Object.assign({}, prev, { few_matches: false, monthly_crowns: true }));
    assert.equal(monthly.crowns, 'Корона лидеру каждого месяца и чемпион лиги в конце.');
    assert.equal(monthly.what, 'Матчи Динамо-Минск');
  });
  it('строка про корону лиги: месяц и весь срок', () => {
    const l = { term: 'season', ends_at: '2027-07-31T21:00:00Z', period: { key: '2026-11' } };
    assert.equal(S.leagueCrownLine(l, 'month', { rank: 3, points: 210 }, 230), 'Корону лиги за ноябрь получит тот, кто будет первым после последнего матча месяца. Сейчас ты на 3-м месте, до первого — 20' + NBSP + 'очков.');
    assert.match(S.leagueCrownLine(l, 'month', { rank: 1, points: 230 }, 230), /Сейчас первое место твоё/);
    assert.match(S.leagueCrownLine(l, 'all', null, 0), /^Чемпиона лиги назовём после 31.июля/);
    assert.match(S.leagueCrownLine({ term: 'month', ends_at: '2026-11-30T21:00:00Z' }, 'all', null, 0), /^Корону лиги получит тот, кто будет первым, когда лига закончится: 30.ноября/);
  });
  it('приглашение без азартных слов', () => {
    assert.match(S.inviteText('Офис', { scope: 'extraliga', clubs: [] }), /Вся Экстралига/);
  });
});

describe('карточка болельщика', () => {
  it('подписи корон и званий сезона', () => {
    assert.equal(S.crownLabel({ kind: 'month', club: 'Юность', period: '2026-10' }), 'Октябрь · болельщики Юности');
    assert.equal(S.crownLabel({ kind: 'month', club: null, period: '2026-10' }), 'Октябрь · все игроки');
    assert.equal(S.crownLabel({ kind: 'league_month', league_name: 'Офис', period: '2026-11' }), 'Ноябрь · лига «Офис»');
    assert.equal(S.crownLabel({ kind: 'league_term', league_name: 'Офис' }), 'Чемпион лиги «Офис»');
    const lines = S.seasonTitleLine({ overall: { rank: 214, players: 1380, to_first: 900 }, club: { name: 'Юность' }, club_place: { rank: 3, players: 212, to_first: 40 } }, '2026/27');
    assert.equal(lines[0].label, 'Знаток сезона · все матчи');
    assert.equal(lines[1].label, 'Знаток Юности 2026/27');
    assert.equal(lines[1].note, 'до 1-го места — 40\u00a0очков');
  });
});

describe('слова игры', () => {
  const FILES = ['kto-kogo-model.js', 'kto-kogo-screens-model.js', 'kto-kogo.js', 'kto-kogo-views.js', 'kto-kogo-hub-cards.js', 'kto-kogo-board.js', 'kto-kogo-leagues.js', 'kto-kogo-boot.js'];
  const BANNED = /ставк|коэффициент|прогноз|пари\b|выигрыш|букмекер|банк\b|ставь|поставить|срок/i;
  it('в строках игроку нет азартных слов', () => {
    for (const f of FILES) {
      const file = path.join(__dirname, '../../static/webapp', f);
      if (!fs.existsSync(file)) continue;
      const src = fs.readFileSync(file, 'utf8');
      const strings = [...src.matchAll(/'((?:[^'\\\n]|\\.){3,})'/g)].map((m) => m[1]);
      const hits = strings.filter((s) => BANNED.test(s));
      assert.deepEqual(hits, [], f);
    }
  });

  // Стиль «весёлая игра» (владелец): до матча нигде нет «×2» и «до N очков»; числа очков — только как результат после матча.
  const MULT = /×|х2(?![а-яё\d])|(^|[^а-яё])до\s+\+\d|(^|[^а-яё])до\s+\d+\s*(очк|за\s|к\s|$)/i;
  it('в исходных строках игры нет множителей и «до N»', () => {
    for (const f of FILES) {
      const file = path.join(__dirname, '../../static/webapp', f);
      if (!fs.existsSync(file)) continue;
      const src = fs.readFileSync(file, 'utf8');
      const strings = [...src.matchAll(/'((?:[^'\\\n]|\\.){2,})'/g)].map((m) => m[1]);
      assert.deepEqual(strings.filter((s) => MULT.test(s)), [], f);
    }
  });
  it('собранные тексты хода до матча — без множителей и чисел очков', () => {
    const M = require('../../static/webapp/kto-kogo-model.js');
    const texts = [];
    for (const doubled of [false, true]) {
      const pick = { side: 'home', home_score: 3, away_score: 2, doubled };
      const side = { side: 'home', home_score: null, away_score: null, doubled };
      for (const p of [pick, side, null]) {
        texts.push(S.pointsLine(p), S.questionLine(p, 'Динамо'), M.stakeLine(p, { home: 'Динамо', away: 'СКА' }, 'open'), M.moveLine(p, {}));
      }
      for (const eff of [S.effectivePick(side, [3, 2]), S.effectivePick(side, [2, 2]), S.effectivePick(side, null)]) {
        const sum = S.moveSummary(eff, doubled, 'Динамо');
        texts.push(sum.text, sum.sticker);
      }
      texts.push(S.trumpLabel(doubled));
    }
    const wk = '2026-11-02';
    const m = { id: 1, starts_at: '2026-11-07T16:00:00Z', home: { name: 'Динамо-Минск' }, away: { name: 'СКА' }, my_pick: { side: 'home' } };
    for (const d of [[], [{ week_start: wk, match_id: null, locked: false }], [{ week_start: wk, match_id: 9, locked: false }], [{ week_start: wk, match_id: 1, locked: true }]]) {
      const st = S.trumpState(m, d, '2026-11-03T10:00:00Z');
      texts.push(st.label, st.note, S.trumpHint(m, d, [m], '2026-11-03T10:00:00Z'));
    }
    texts.push(M.scoreHint(3, 2), M.scoreHint(2, 2), M.nudgeLine({ home: [], away: [] }, {}), M.nudgeLine({ home: ['Аня'], away: [] }, { home: 'Динамо' }), M.nudgeLine({ home: ['Аня'], away: ['Лёша'] }, {}));
    texts.push(S.liveWhy({ side: 'home', home_score: 3, away_score: 2 }, { home_score: 2, away_score: 1 }, { home: 'Динамо', away: 'СКА' }));
    for (const s of texts) assert.ok(!MULT.test(s) && !/%/.test(s), s);
  });
});

describe('итог и «мимо»', () => {
  const next = { starts_at: '2026-11-07T16:00:00Z', home: { name: 'Динамо-Минск' }, away: { name: 'Торпедо' } };
  it('мимо — без красного голоса: бывает, следующий матч', () => {
    assert.equal(S.missLine(next, new Date('2026-11-05T10:00:00Z')), 'Бывает — следующий матч Динамо — Торпедо в субботу.');
    assert.equal(S.missLine(next, new Date('2026-11-06T10:00:00Z')), 'Бывает — следующий матч Динамо — Торпедо завтра.');
    assert.equal(S.missLine(null, new Date()), 'Бывает. Следующий ход — на главной игры.');
    assert.ok(!/угадал/i.test(S.missLine(next, new Date())));
  });
  it('кнопка «Следующий ход» и чип места в лиге', () => {
    assert.equal(S.nextTurnLabel(next), 'Следующий ход · сб, Динамо — Торпедо');
    assert.equal(S.nextTurnLabel(null), 'Следующий ход');
    assert.equal(S.bestLeagueChip([{ kind: 'league', league_name: 'Офис', rank_after: 3 }, { kind: 'league', league_name: 'Двор', rank_after: 5 }, { kind: 'slice', rank_after: 1 }]), '3-е место в' + NBSP + 'лиге «Офис»');
    assert.equal(S.bestLeagueChip([{ kind: 'slice', rank_after: 1 }]), null);
    assert.equal(S.bestLeagueChip([]), null);
  });
});

describe('шторка «Как считаются очки»', () => {
  it('числа — из POINTS, слова — из макета, минута закрытия сходится', () => {
    const M = require('../../static/webapp/kto-kogo-model.js');
    const r = S.pointsRules();
    assert.deepEqual(r.rows.map((x) => x.value), [String(M.POINTS.winner), '+' + M.POINTS.diff, String(M.POINTS.exact)]);
    assert.equal(M.POINTS.diff, M.POINTS.goals); // одна строка «+10» говорит и про разницу, и про голы
    assert.equal(r.rows[2].gold, true);
    assert.equal(r.rows[0].text, 'Победитель угадан.');
    assert.equal(r.trumpTitle, 'Козырь');
    assert.match(r.trumpText, /удвоятся/);
    assert.equal(M.PICK_CLOSES_BEFORE_SEC, 60);
    assert.match(r.foot, /за минуту до начала матча/);
  });
});