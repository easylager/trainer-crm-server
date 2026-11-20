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
    assert.equal(lines[0].text, 'Можешь выйти на 1-е место в таблице Юности за ноябрь — и взять корону');
    assert.equal(lines[1].text, 'Можешь подняться на 190-е место в общей таблице за сезон (сейчас 214-е)');
    assert.equal(lines[2].text, 'Можешь подняться на 2-е место в лиге «Офис» (сейчас 3-е)');
  });
  it('новичок без места: будущее место', () => {
    const [l] = S.stakeLines([{ kind: 'slice', club: 'Лида', period_title: 'ноябрь', rank_now: null, rank_if: 2, crown: false }]);
    assert.equal(l.text, 'Займёшь 2-е место в таблице Лиды за ноябрь');
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
    assert.equal(S.liveWhy(pick('home', 3, 2), null), 'Счёт появится здесь, как только будет доступен');
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
    assert.equal(S.resultHead(20), 'Победитель угадан');
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
    assert.match(S.crownLineAfter([Object.assign({}, base, { left: 0 })]), /последний матч месяца в таблице «Юность · ноябрь»: корона придёт в течение двух суток, когда сверим итоги\.$/);
    assert.equal(S.crownLineAfter([{ kind: 'league' }]), '');
  });
});

describe('таблица', () => {
  const r = (rank, over) => Object.assign({ rank, display_name: 'И' + rank, points: 100 - rank, exact: 0, played: rank, correct_percent: 60, crowns: 0, is_me: false }, over || {});
  it('большая таблица: выше шестого места — шесть строк; ниже — пять, разрыв и соседи', () => {
    const items = Array.from({ length: 20 }, (_, i) => r(i + 1));
    assert.equal(S.tableRows({ items, me: r(3, { is_me: true }), neighbors: [] }).length, 6);
    assert.equal(S.tableRows({ items, me: null, neighbors: [] }).length, 6);
    const rows = S.tableRows({ items, me: r(214, { is_me: true }), neighbors: [r(213), r(214, { is_me: true }), r(215)] });
    assert.deepEqual(rows.map((x) => (x.type === 'gap' ? 'gap' : x.r.rank)), [1, 2, 3, 4, 5, 'gap', 213, 214, 215]);
    const near = S.tableRows({ items, me: r(7, { is_me: true }), neighbors: [r(6), r(7, { is_me: true }), r(8)] });
    assert.deepEqual(near.map((x) => (x.type === 'gap' ? 'gap' : x.r.rank)), [1, 2, 3, 4, 5, 6, 7, 8]);
  });
  it('до пятнадцати игроков таблица целиком, без кнопки', () => {
    const items = [1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => r(n));
    const view = { items, me: r(2, { is_me: true }), neighbors: [], players: 9 };
    assert.equal(S.tableRows(view).length, 9);
    assert.equal(S.tableMore(view), null);
  });
  it('кнопка раскрывает присланное: «всех», если прислано всё, иначе «первых 50»; я ниже — разрыв и соседи', () => {
    const items = Array.from({ length: 20 }, (_, i) => r(i + 1));
    const view = { items, me: r(3, { is_me: true }), neighbors: [], players: 20 };
    assert.equal(S.tableMore(view), 'Показать всех' + NBSP + '20' + NBSP + 'игроков');
    assert.equal(S.tableRows(view, true).length, 20);
    assert.equal(S.tableMore(view, true), null);
    const top = Array.from({ length: 50 }, (_, i) => r(i + 1));
    const big = { items: top, me: r(214, { is_me: true }), neighbors: [r(213), r(214, { is_me: true }), r(215)], players: 1380 };
    assert.equal(S.tableMore(big), 'Показать первых' + NBSP + '50' + NBSP + 'игроков')
    assert.equal(S.tableMore({ items: top.slice(0, 21), players: 1000 }), 'Показать первых' + NBSP + '21' + NBSP + 'игрока');
    const rows = S.tableRows(big, true);
    assert.equal(rows.length, 54);
    assert.deepEqual(rows.slice(49).map((x) => (x.type === 'gap' ? 'gap' : x.r.rank)), [50, 'gap', 213, 214, 215]);
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
    assert.match(S.tableCrownLine(view, 'Юность', '2026-11', 'сезон 2026/27'), /^Корона за ноябрь по матчам Юности — у лидера после последнего матча месяца\. Придёт в течение двух суток\. До первого места — 20.очков\.$/);
    assert.equal(S.tableCrownMuted(view, '2026-11'), false);
    assert.match(S.tableCrownLine({ players_with_points: 5, me: { rank: 1 }, to_crown: 0 }, null, '2026-11', ''), /Придёт в течение двух суток\. Сейчас первое место твоё/);
    assert.match(S.tableCrownLine({ players_with_points: 3 }, null, '2026-11', ''), /^Корона за ноябрь — у лидера после последнего матча месяца\. Придёт в течение двух суток\.$/);
    assert.match(S.tableCrownLine(view, null, 'season', 'сезон 2026/27'), /Знаток сезона 2026\/27/);
    assert.match(S.tableCrownLine(view, 'Юность', 'season', 'сезон 2026/27'), /Знаток Юности 2026\/27/);
  });
  it('плашка короны: игроков с очками меньше трёх — приглушённая, со счётом словами', () => {
    const line = (n, club) => S.tableCrownLine({ players_with_points: n }, club, '2026-11', '');
    assert.equal(line(0, 'Динамо-Минск'), 'Корона за ноябрь по матчам Динамо-Минск появится, когда в таблице будет минимум трое игроков с очками. Сейчас — ни одного.');
    assert.equal(line(1, null), 'Корона за ноябрь появится, когда в таблице будет минимум трое игроков с очками. Сейчас — один.');
    assert.equal(line(2, 'Юность'), 'Корона за ноябрь по матчам Юности появится, когда в таблице будет минимум трое игроков с очками. Сейчас — двое.');
    for (const n of [0, 1, 2]) assert.equal(S.tableCrownMuted({ players_with_points: n }, '2026-11'), true, String(n));
    assert.equal(S.tableCrownMuted({ players_with_points: 3 }, '2026-11'), false);
    // Сезон — звание, а не корона: плашка не приглушается.
    assert.equal(S.tableCrownMuted({ players_with_points: 0 }, 'season'), false);
    assert.equal(S.tableCrownMuted({ players_with_points: 0 }, undefined), false);
  });
  it('вершины: чип и плитка, корона записью', () => {
    const p = { club: 'Юность', period: '2026-11', period_title: 'ноябрь', rank: 2, players: 38 };
    assert.equal(S.peakChip(p), 'Юность · ноябрь · 2' + NBSP + 'место');
    assert.deepEqual(S.peakTile(p, []), { rank: '2-е', name: 'Юность', slice: 'ноябрь', note: 'место из\u00a038', gold: false });
    const crown = [{ kind: 'month', period: '2026-11', club: 'Юность' }];
    assert.equal(S.peakTile(Object.assign({}, p, { rank: 1 }), crown).note, 'корона твоя');
    assert.equal(S.peakTile(Object.assign({}, p, { rank: 1 }), []).note, 'место · лидируешь');
    assert.equal(S.peakTile({ club: 'Динамо-Минск', period: 'season', period_title: 'сезон 2026/27', rank: 3, players: 9 }, []).name, 'Динамо');
    assert.equal(S.peakTile({ club: null, period: 'season', period_title: 'сезон 2026/27', rank: 3, players: 9 }, []).name, 'Все матчи');
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
    assert.match(ch[2].sub, /с 3.ноября по 30.ноября/);
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
  it('строка про корону лиги: месяц и весь срок, порог двоих', () => {
    const two = [{ points: 230 }, { points: 210 }, { points: 0 }];
    const l = { term: 'season', ends_at: '2027-07-31T21:00:00Z', period: { key: '2026-11' }, items: two };
    assert.equal(S.leagueCrownLine(l, 'month', { rank: 3, points: 210 }, 230), 'Корону лиги за ноябрь заберёт лидер после последнего матча месяца. Сейчас ты на 3-м месте, до первого — 20' + NBSP + 'очков.');
    assert.match(S.leagueCrownLine(l, 'month', { rank: 1, points: 230 }, 230), /Сейчас первое место твоё/);
    const full = 'Корона лиги — у лидера, когда лига закончится. Для неё хватит и двоих игроков с очками.';
    assert.equal(S.leagueCrownLine(l, 'all', null, 0), full);
    assert.equal(S.leagueCrownLine({ term: 'month', ends_at: '2026-11-30T21:00:00Z', items: two }, 'all', null, 0), full);
    assert.equal(S.leagueCrownMuted(l), false);
  });
  it('корона лиги: очков меньше чем у двоих — приглушённая плашка', () => {
    const none = { term: 'season', ends_at: '2027-07-31T21:00:00Z', period: { key: '2026-11' }, items: [{ points: 0 }, { points: 0 }] };
    const one = Object.assign({}, none, { items: [{ points: 30 }, { points: 0 }] });
    assert.equal(S.leagueCrownLine(none, 'all', null, 0), 'Корону лиги получит лидер, когда очки будут хотя бы у двоих. Пока их нет ни у кого.');
    assert.equal(S.leagueCrownLine(one, 'all', null, 0), 'Корону лиги получит лидер, когда очки будут хотя бы у двоих. Пока очки только у одного.');
    assert.equal(S.leagueCrownLine(one, 'month', { rank: 1, points: 30 }, 30), 'Корону лиги получит лидер, когда очки будут хотя бы у двоих. Пока очки только у одного.');
    assert.equal(S.leagueCrownMuted(none), true);
    assert.equal(S.leagueCrownMuted(one), true);
    assert.equal(S.leagueCrownMuted({ items: [] }), true);
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
  const FILES = ['kto-kogo-model.js', 'kto-kogo-screens-model.js', 'kto-kogo.js', 'kto-kogo-kit.js', 'kto-kogo-views.js', 'kto-kogo-hub-cards.js', 'kto-kogo-board.js', 'kto-kogo-leagues.js', 'kto-kogo-matches.js', 'kto-kogo-boot.js'];
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

describe('с какой таблицы открыть «Таблицу»', () => {
  it('выбор руками, иначе вершина от десяти, иначе общая', () => {
    assert.deepEqual(S.tableStartArgs(null, null), { club: null, period: 'season' });
    assert.deepEqual(S.tableStartArgs(null, { club: 'Юность', period: '2026-11' }), { club: 'Юность', period: '2026-11' });
    assert.deepEqual(S.tableStartArgs({ club: null, period: 'season' }, { club: 'Юность', period: '2026-11' }), { club: null, period: 'season' });
  });
  it('общая — все матчи за сезон', () => {
    assert.equal(S.isGeneralTable({ club: null, period: 'season' }), true);
    assert.equal(S.isGeneralTable({}), true);
    assert.equal(S.isGeneralTable({ club: null, period: '2026-11' }), false);
    assert.equal(S.isGeneralTable({ club: 'Юность', period: 'season' }), false);
  });
});

describe('«Трибуна» в итоге', () => {
  const match = (pick, sides, result, extra) => Object.assign({ home: { name: 'Неман' }, away: { name: 'Шахтер' }, my_pick: pick, sides: sides, result: result || { home_score: 2, away_score: 3 } }, extra || {});
  it('угадал, мимо с большинством, мимо в меньшинстве', () => {
    const t = S.tribune(match({ side: 'away', points: 20 }, { home: 114, away: 34 }));
    assert.deepEqual([t.home, t.away, t.total, t.side, t.soft], [77, 23, 148, 'away', false]);
    assert.equal(t.line, 'Победителя угадали 23% игроков — и ты в их числе.');
    assert.equal(S.tribune(match({ side: 'home', points: 0 }, { home: 114, away: 34 })).line, 'Трибуна тоже промахнулась: 77% были за Неман.');
    assert.equal(S.tribune(match({ side: 'away', points: 0 }, { home: 5, away: 15 }, { home_score: 4, away_score: 1 })).line, 'Трибуна тоже промахнулась: 75% были за Шахтёр.');
    assert.equal(S.tribune(match({ side: 'away', points: 0 }, { home: 114, away: 34 }, { home_score: 4, away_score: 1 })).line, 'Победителя угадали 77% игроков.');
  });
  it('точный счёт — чип и строка, как в боте', () => {
    const alone = S.tribune(match({ side: 'away', points: 50 }, { home: 114, away: 34 }, null, { same_exact: 0 }));
    assert.equal(alone.chip, 'Больше никто из 148');
    assert.equal(alone.line, 'Такой счёт больше никто из 148 не назвал.');
    const three = S.tribune(match({ side: 'away', points: 50 }, { home: 114, away: 34 }, null, { same_exact: 3 }));
    assert.equal(three.chip, 'Так сходили ещё 3');
    assert.equal(three.line, 'Такой счёт назвали ещё 3 из 148.');
  });
  it('точный счёт, а same_exact ещё не пришёл (запись из списка) — блока нет, а не «никто не назвал»', () => {
    assert.equal(S.tribune(match({ side: 'away', points: 50 }, { home: 114, away: 34 }, null, { same_exact: null })), null);
    assert.equal(S.tribune(match({ side: 'away', points: 50 }, { home: 114, away: 34 })), null);
  });
  it('гости — остаток до 100, как в боте: 1 из 40 за хозяев → 97%', () => {
    assert.equal(S.tribune(match({ side: 'away', points: 20 }, { home: 1, away: 39 })).line, 'Победителя угадали 97% игроков — и ты в их числе.');
  });
  it('меньше 8 ходов, очки не посчитаны или хода нет — блока нет', () => {
    assert.equal(S.TRIBUNE_MIN, 8);
    assert.equal(S.tribune(match({ side: 'away', points: 20 }, { home: 4, away: 3 })), null);
    assert.equal(S.tribune(match({ side: 'away', points: 20 }, { home: 4, away: 4 })).line, 'Победителя угадали 50% игроков — и ты в их числе.');
    assert.equal(S.tribune(match({ side: 'away', points: null }, { home: 114, away: 34 })), null);
    assert.equal(S.tribune(match(null, { home: 114, away: 34 })), null);
  });
  it('половина вверх, как в боте', () => {
    assert.equal(S.tribune(match({ side: 'home', points: 20 }, { home: 1, away: 39 }, { home_score: 3, away_score: 2 })).line, 'Победителя угадали 3% игроков — и ты в их числе.');
  });
});

describe('шторка «Как считаются очки»', () => {
  it('числа — из POINTS, слова — из макета, минута закрытия сходится', () => {
    const M = require('../../static/webapp/kto-kogo-model.js');
    const r = S.pointsRules();
    assert.deepEqual(r.rows.map((x) => x.value), [String(M.POINTS.winner), '+' + M.POINTS.diff, '+' + M.POINTS.goals, '+' + M.POINTS.goals, String(M.POINTS.exact)]);
    // Точный счёт = победитель + разница + шайбы хозяев + шайбы гостей.
    assert.equal(M.POINTS.winner + M.POINTS.diff + 2 * M.POINTS.goals, M.POINTS.exact);
    assert.deepEqual(r.rows.map((x) => x.text).slice(1, 4), ['Угадана разница шайб.', 'Угаданы шайбы хозяев.', 'Угаданы шайбы гостей.']);
    assert.equal(r.rows[4].gold, true);
    assert.equal(r.rows[0].text, 'Угадан победитель.');
    assert.equal(r.trumpTitle, 'Козырь');
    assert.match(r.trumpText, /удвоятся/);
    assert.equal(M.PICK_CLOSES_BEFORE_SEC, 60);
    assert.match(r.foot, /не позже чем за минуту до начала матча/);
  });
  it('«Таблицы и короны»: четыре пункта макета, пороги три и два, два дня на сверку', () => {
    const r = S.pointsRules();
    assert.equal(r.tablesTitle, 'Таблицы и короны');
    assert.deepEqual(r.tables.map((x) => x.title), ['Кто выше', 'Корона', 'Сколько игроков нужно', 'Когда придёт']);
    assert.match(r.tables[0].text, /больше точных счётов.*меньше матчей.*место делите/);
    assert.match(r.tables[1].text, /Первое место поделили — корона у каждого/);
    assert.match(r.tables[2].text, /минимум трое игроков с очками\. В лиге друзей хватит двоих\./);
    assert.match(r.tables[3].text, /^В течение двух суток после последнего матча/);
  });
  it('блок «Таблицы и короны» в шторке: свёрнут, кнопка с aria-expanded раскрывает и сворачивает', () => {
    const vm = require('node:vm');
    function el(tag) {
      const attrs = {};
      const listeners = {};
      const classes = new Set();
      return {
        tag, attrs, children: [], hidden: false, textContent: '',
        setAttribute(k, v) { attrs[k] = String(v); if (k === 'hidden') this.hidden = true; },
        getAttribute(k) { return k in attrs ? attrs[k] : null; },
        addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
        click() { (listeners.click || []).forEach((fn) => fn({})); },
        classList: { toggle(c, on) { if (on) classes.add(c); else classes.delete(c); }, contains: (c) => classes.has(c) },
        appendChild(c) { this.children.push(c); },
      };
    }
    function h(tag, attrs, kids) {
      const e = el(tag);
      Object.keys(attrs || {}).forEach((k) => {
        const v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') e.className = v;
        else if (k === 'text') e.textContent = v;
        else if (k.indexOf('on') === 0) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? '' : v);
      });
      (kids || []).forEach((c) => { if (c) e.appendChild(c); });
      return e;
    }
    const state = { sheet: { kind: 'points' } };
    const K = { h, M: {}, S, I: { down: [], chev: [] }, state, icon: () => el('svg'), sheet: (title, sub, kids) => h('div', { class: 'sheet' }, kids) };
    const ctx = { window: { KK: K } };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo-hub-cards.js'), 'utf8'), ctx);
    const walk = (n, out) => { out.push(n); (n.children || []).forEach((c) => walk(c, out)); return out; };
    const find = (root, cls) => walk(root, []).find((n) => n.className === cls || (n.className || '').split(' ').includes(cls));
    let root = K.hubCards.pointsSheet();
    let btn = find(root, 'kk-rl__more');
    let panel = find(root, 'kk-rl__panel');
    assert.equal(btn.tag, 'button');
    assert.equal(btn.getAttribute('aria-expanded'), 'false');
    assert.equal(btn.getAttribute('aria-controls'), panel.getAttribute('id'));
    assert.equal(panel.hidden, true);
    // Сверху разделы «Очки · Кепка · Жесты» (TASK-431); блок стоит между карточкой «Козырь» и нижней подписью.
    const kids = root.children.map((c) => c.className);
    assert.equal(kids[0], 'kk-rtabs');
    assert.deepEqual(kids.slice(2), ['kk-rl__trump', 'kk-rl__tables', 'kk-sub']);
    assert.equal(panel.children.length, 4);
    btn.click();
    assert.equal(btn.getAttribute('aria-expanded'), 'true');
    assert.equal(panel.hidden, false);
    assert.equal(state.sheet.tablesOpen, true);
    // Перерисовка шторки не сворачивает открытый блок.
    root = K.hubCards.pointsSheet();
    btn = find(root, 'kk-rl__more');
    panel = find(root, 'kk-rl__panel');
    assert.equal(btn.getAttribute('aria-expanded'), 'true');
    assert.equal(panel.hidden, false);
    btn.click();
    assert.equal(btn.getAttribute('aria-expanded'), 'false');
    assert.equal(panel.hidden, true);
  });
});

describe('таблица без периода в аргументах (повторное открытие «Таблицы» из хаба)', () => {
  // Первый кадр экрана рисуется до enter, где ставятся умолчания: period ещё undefined, а таблица уже в кеше.
  // Раньше здесь было TypeError на toLowerCase — стек и экран расходились, «Назад» и «Таблица» молчали.
  it('плашка про корону и «мало игроков» считают пустой период сезоном', () => {
    const view = { players_with_points: 1, me: { rank: 1 }, to_crown: 0 };
    assert.equal(S.tableCrownLine(view, null, undefined, 'сезон 2026/27'), S.tableCrownLine(view, null, 'season', 'сезон 2026/27'));
    assert.deepEqual(S.fewPlayers(view, null, undefined), S.fewPlayers(view, null, 'season'));
  });
});

describe('срок формы «Новая лига» (TASK-362)', () => {
  const items = [
    { term: 'season', starts_at: '2026-11-09T21:00:00Z', ends_at: '2027-04-30T21:00:00Z', monthly_crowns: true },
    { term: 'weeks4', starts_at: '2026-11-09T21:00:00Z', ends_at: '2026-12-07T21:00:00Z', monthly_crowns: false },
  ];
  const opts = { items, season_ends_at: '2027-04-30T21:00:00Z' };

  it('пока сроки не загружены, выбор не трогаем (раньше форма уходила на «Свои даты»)', () => {
    assert.equal(S.settleTerm('season', null), 'season');
    assert.equal(S.settleTerm('season', undefined), 'season');
  });

  it('выбор из списка сохраняется', () => {
    assert.equal(S.settleTerm('season', opts), 'season');
    assert.equal(S.settleTerm('weeks4', opts), 'weeks4');
    assert.equal(S.settleTerm('dates', opts), 'dates');
  });

  it('выбранного окна уже нет — первый открытый срок', () => {
    assert.equal(S.settleTerm('playoff', opts), 'season');
  });

  it('открытых сроков нет совсем — остаются «Свои даты»', () => {
    assert.equal(S.settleTerm('season', { items: [], season_ends_at: '2027-04-30T21:00:00Z' }), 'dates');
  });
});

describe('пьедестал лиги', () => {
  it('меньше троих — пьедестала нет; иначе порядок 2-е, 1-е, 3-е', () => {
    assert.equal(S.podiumOrder([]), null);
    assert.equal(S.podiumOrder([{ rank: 1 }, { rank: 2 }]), null);
    const top = S.podiumOrder([{ rank: 1 }, { rank: 2 }, { rank: 3 }, { rank: 4 }]);
    assert.deepEqual(top.map((r) => r.rank), [2, 1, 3]);
  });
  it('значок звания: кепка и шарф есть, остальным званиям значка нет', () => {
    assert.equal(S.titleMark({ id: 'cap' }), '🧢');
    assert.equal(S.titleMark({ id: 'scarf' }), '🧣');
    assert.equal(S.titleMark({ id: 'vanga' }), '');
    assert.equal(S.titleMark(null), '');
  });
  it('пояснение к званиям: только о тех, что висят на таблице', () => {
    assert.equal(S.titlesNote([{ title: null }, {}]), '');
    assert.match(S.titlesNote([{ title: { id: 'scarf' } }]), /^Шарф — за ход против своей команды/);
    const both = S.titlesNote([{ head: { item: 'cap' } }, { title: { id: 'scarf' } }]);
    assert.match(both, /Шарф/);
    assert.match(both, /Кепка дня — тому, кто хуже всех угадывал в последний сыгранный вечер лиги/);
    assert.match(S.titlesNote([{ captain: true }, { head: { item: 'bucket' } }]), /^«C» — капитан последнего вечера/);
  });
});

describe('стенд наград (TASK-430)', () => {
  const clubs = [{ name: 'Динамо-Минск' }, { name: 'Брест' }, { name: 'Неман' }, { name: 'Лида' }];
  const crowns = [
    { kind: 'month', club: 'Динамо-Минск', league_id: null, period: '2026-09' },
    { kind: 'month', club: 'Динамо-Минск', league_id: null, period: '2026-10' },
    { kind: 'month', club: 'Брест', league_id: null, period: '2026-10' },
    { kind: 'month', club: null, league_id: null, period: '2026-10' },
    { kind: 'league_month', club: null, league_id: 7, period: '2026-10' },
    { kind: 'league_term', club: null, league_id: 7, period: '2026-10' },
  ];

  it('считает короны по клубам, общей таблице и лигам; все клубы каталога на стенде', () => {
    const m = S.standModel(crowns, clubs);
    assert.equal(m.total, 6);
    assert.equal(m.overall, 1);
    assert.equal(m.leagues, 2);
    assert.deepEqual(m.clubs.map((c) => [c.club.name, c.count]), [['Динамо-Минск', 2], ['Брест', 1], ['Неман', 0], ['Лида', 0]]);
    assert.deepEqual(m.clubs[0].months, ['2026-10', '2026-09']);
  });

  it('пустой стенд: короны ноль, клубы остаются', () => {
    const m = S.standModel([], clubs);
    assert.equal(m.total, 0);
    assert.equal(m.clubs.length, 4);
    assert.deepEqual(S.standMini(m, 6), { shown: [], more: 0 });
  });

  it('мини-стенд: у кого короны, больше — первым, остаток считается', () => {
    const many = [
      { kind: 'month', club: 'Лида', league_id: null, period: '2026-10' },
      { kind: 'month', club: 'Лида', league_id: null, period: '2026-09' },
      { kind: 'month', club: 'Неман', league_id: null, period: '2026-10' },
      { kind: 'month', club: 'Брест', league_id: null, period: '2026-10' },
    ];
    const mini = S.standMini(S.standModel(many, clubs), 2);
    assert.deepEqual(mini.shown.map((c) => c.club.name), ['Лида', 'Брест']); // 2 короны, затем порядок каталога
    assert.equal(mini.more, 1);
  });

  it('подпись и месяцы клуба', () => {
    assert.equal(S.standCountLabel(0), 'Пока без корон');
    assert.equal(S.standCountLabel(1), '1' + NBSP + 'корона');
    assert.equal(S.standCountLabel(14), '14' + NBSP + 'корон');
    assert.deepEqual(S.clubCrownMonths({ months: ['2026-10', '2026-09'] }), ['Октябрь', 'Сентябрь']);
  });

  it('сравнение стендов: у кого больше, поровну; клубы без корон у обоих не считаются', () => {
    const mk = (counts) => S.standModel(
      counts.flatMap((n, i) => Array.from({ length: n }, () => ({ kind: 'month', club: clubs[i].name, league_id: null, period: '2026-10' }))),
      clubs,
    );
    const theirs = mk([2, 1, 0, 0]);
    const mine = mk([4, 1, 3, 0]);
    assert.deepEqual(S.standCompare(theirs, mine), { mine: 2, theirs: 0, same: 1 });
    assert.deepEqual(S.standCompare(mk([0, 0, 0, 0]), mk([0, 0, 0, 0])), { mine: 0, theirs: 0, same: 0 });
    assert.deepEqual(S.standCompare(mk([3, 0, 0, 0]), mk([1, 0, 0, 0])), { mine: 0, theirs: 1, same: 0 });
  });
});

describe('previewView: «Перед матчем» — только то, что есть', () => {
  const m = { home: { name: 'Юность' }, away: { name: 'Неман' }, sides: { home: 0, away: 0 } };
  const g = (o) => ({ home_team: 'Юность', away_team: 'Неман', home_score: 4, away_score: 3, decided_in: 'regulation', starts_at: '2026-10-27T16:00:00+00:00', ...o });
  const labels = (v) => v.rows.map((r) => r.label);

  it('нет данных, пустой ответ или мусор — блока нет', () => {
    assert.equal(S.previewView(null, m), null);
    assert.equal(S.previewView({}, m), null);
    assert.equal(S.previewView({ home: {}, meetings: [] }, m), null);
    assert.equal(S.previewView({ home: { form: [] } }, null), null);
  });

  it('всё есть: порядок как на сайте, потом игровое', () => {
    const v = S.previewView({
      home: { place: 13, points: 11, form: [{ ...g({ decided_in: 'so' }), win: true, home: true, opponent: 'Неман' }, { ...g({}), win: false, home: false, opponent: 'Неман' }], mine: { total: 4, winner: 3, exact: 1 } },
      away: { place: 1, points: 21, mine: { total: 2, winner: 0, exact: 0 } },
      meetings: [g({ decided_in: 'so' }), g({}), g({}), g({})],
    }, { ...m, sides: { home: 16, away: 9 } });
    assert.deepEqual(labels(v), [
      'Юность в таблице', 'Неман в таблице', 'Форма: Юность', 'Прошлая встреча', 'Встреча 27.10', 'Встреча 27.10',
      'За кого пошли игроки', 'Ты и Юность', 'Ты и Неман',
    ]);
    assert.equal(v.rows[0].value, `13-е · 11${NBSP}очков`);
    assert.equal(v.rows[1].value, `1-е · 21${NBSP}очко`);
    assert.deepEqual(v.rows[2].chips.map((c) => [c.text, c.win]), [['В·Б', true], ['П', false]]);
    assert.match(v.rows[2].chips[1].label, /^Поражение 3:4 от .+, 27\.10$/);
    assert.equal(v.rows[3].value, `Юность — Неман 4:3${NBSP}Б`);
    assert.deepEqual([v.rows[6].home.pct, v.rows[6].away.pct], [64, 36]);
    assert.equal(v.rows[7].value, 'победитель — 3 из 4, точный счёт — 1');
    assert.equal(v.rows[8].value, 'победитель — 0 из 2');
  });

  it('частично: место без очков, мало ходов — без трибуны и без своей истории', () => {
    const v = S.previewView({ away: { place: 2, mine: { total: 1, winner: 1, exact: 1 } } }, { ...m, sides: { home: 5, away: 2 } });
    assert.deepEqual(v.rows.map((r) => [r.label, r.value]), [['Неман в таблице', '2-е']]);
  });

  it('только трибуна — тоже блок; доли без количеств', () => {
    const v = S.previewView({}, { ...m, sides: { home: 4, away: 4 } });
    assert.deepEqual(labels(v), ['За кого пошли игроки']);
    assert.doesNotMatch(JSON.stringify(v), /"4"|: ?4[,}]/);
  });

  it('без слов из ставок и без рода', () => {
    const v = S.previewView({ home: { place: 2, points: 3, mine: { total: 3, winner: 2, exact: 1 } }, meetings: [g({})] }, { ...m, sides: { home: 9, away: 1 } });
    const t = JSON.stringify(v);
    assert.doesNotMatch(t, /ставк|коэф|выигрыш|банк|поставил/i);
    assert.doesNotMatch(t, /угадал[^и]|выбрал/);
  });
});
