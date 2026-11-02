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
    assert.equal(lines[0].text, 'Юность · ноябрь: место 3 → ~1 · корона');
    assert.equal(lines[1].text, 'Все · сезон: место 214 → ~190');
    assert.equal(lines[2].text, 'Лига «Офис»: место 3 → ~2');
  });
  it('новичок без места: «выйдешь на N»', () => {
    const [l] = S.stakeLines([{ kind: 'slice', club: 'Лида', period_title: 'ноябрь', rank_now: null, rank_if: 2, crown: false }]);
    assert.equal(l.text, 'Лида · ноябрь: выйдешь на 2');
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
  it('ничья на табло: очков нет, объяснение про овертайм', () => {
    assert.equal(S.livePoints(pick('home', 3, 2), { home_score: 1, away_score: 1 }), null);
    assert.match(S.liveWhy(pick('home', 3, 2), { home_score: 1, away_score: 1 }), /овертайме/);
  });
  it('козырь удваивает живые очки', () => {
    assert.equal(S.livePoints(pick('home', null, null, true), { home_score: 2, away_score: 1 }), 40);
  });
  it('из чего сложились очки', () => {
    assert.deepEqual(S.liveParts(pick('home', 3, 2), { home_score: 2, away_score: 1 }), ['победитель', 'разница']);
    assert.deepEqual(S.liveParts(pick('home', 3, 2), { home_score: 3, away_score: 2 }), ['точный счёт']);
    assert.equal(S.liveWhy(pick('home', 3, 2), { home_score: 0, away_score: 4 }), 'Пока мимо — до сирены всё может поменяться');
    assert.match(S.liveWhy(pick('home', 3, 2), null), /прочитаем/);
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
  it('доля игроков: без ходов молчим', () => {
    const name = (side) => (side === 'home' ? 'Юность' : 'Шахтер');
    assert.equal(S.crowdShare({ home: 0, away: 0 }, null, name), null);
    assert.equal(S.crowdShare({ home: 3, away: 1 }, null, name).text, '75% игроков за Юность');
    assert.equal(S.crowdShare({ home: 1, away: 3 }, null, name).text, '75% игроков за Шахтёр');
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
    assert.equal(S.trumpState(m(1), week, NOW.toISOString()).note, 'есть до воскресенья');
    assert.equal(S.trumpState(m(1, { my_pick: { side: 'home', doubled: true } }), week).kind, 'on');
    assert.equal(S.trumpState(m(1), [{ week_start: '2026-11-02', match_id: 9, locked: false }]).kind, 'other');
    assert.equal(S.trumpState(m(1), [{ week_start: '2026-11-02', match_id: 9, locked: true }]).usable, false);
    assert.equal(S.trumpState(m(1, { starts_at: '2026-11-20T16:00:00Z' }), week).kind, 'na');
  });
  it('очки хода с козырем удваиваются в подписи', () => {
    assert.equal(S.pointsLine(null), 'Тап за команду — и ход сделан');
    assert.equal(S.pointsLine({ side: 'home', home_score: null, doubled: false }), '+20 за победителя · точный счёт — до 50');
    assert.equal(S.pointsLine({ side: 'home', home_score: 3, doubled: true }), '+40 за победителя · до 100 за точный счёт · козырь');
    assert.equal(S.questionLine({ side: 'home', home_score: 3, away_score: 2 }, 'Юность'), 'Ты за Юность · 3:2');
  });
});

describe('матчи дня и пауза', () => {
  const mk = (id, iso, extra) => Object.assign({ id, starts_at: iso, open: true, status: 'scheduled', league: 'extraliga', my_pick: null, home_team: 'A', away_team: 'B' }, extra || {});
  it('берёт ближайший день с открытым матчем; закрытые того же дня остаются в списке', () => {
    const list = [mk(1, '2026-11-05T16:00:00Z', { open: false, status: 'final' }), mk(2, '2026-11-06T15:30:00Z', { my_pick: { side: 'home' } }), mk(3, '2026-11-06T16:00:00Z'), mk(4, '2026-11-06T11:00:00Z', { open: false }), mk(5, '2026-11-07T16:00:00Z')];
    const d = S.dayMatches(list, NOW);
    assert.equal(d.heading, 'МАТЧИ ДНЯ · ПЯТНИЦА');
    assert.deepEqual(d.items.map((x) => x.id), [4, 2, 3]);
    assert.equal(d.total, 2);
    assert.equal(d.made, 1);
    assert.equal(S.dayCount(d.made, d.total), '1 из 2');
    assert.equal(S.dayCount(2, 2), 'все 2 — готово');
  });
  it('нет матчей сегодня — «ближайшие» с днём недели; нет открытых — null', () => {
    const d = S.dayMatches([mk(1, '2026-11-10T16:00:00Z')], NOW);
    assert.equal(d.heading, 'БЛИЖАЙШИЕ МАТЧИ · ВТОРНИК');
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
    assert.equal(S.resultHead(0), 'В этот раз мимо');
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
    assert.match(S.crownLineAfter([base]), /твоя, если удержишь до 30.ноября.*ещё 3.матча у Юность/);
    assert.match(S.crownLineAfter([Object.assign({}, base, { crown: false, to_crown: 10 })]), /^До короны месяца \(ноябрь\) 10.очков/);
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
    assert.equal(S.rowSub(r(1, { played: 34, correct_percent: 64 })), '34' + NBSP + 'хода · угадано 64%');
    assert.equal(S.rowSub(r(1, { played: 1, correct_percent: null })), '1' + NBSP + 'ход');
    assert.equal(S.tableCaption({ players: 1380 }, null), '1' + NBSP + '380' + NBSP + 'игроков · Динамо и вся Экстралига');
    assert.equal(S.tableCaption({ players: 3 }, 'Шахтер'), '3' + NBSP + 'игрока · только матчи Шахтёр');
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
    assert.equal(few.invite, 'Позвать болельщиков Лида');
    assert.equal(S.fewPlayers({ players_with_points: 3 }, 'Лида', '2026-11'), null);
    assert.match(S.fewPlayers({ players_with_points: 0 }, null, 'season').head, /пока никого/);
  });
  it('плашка новичка: сезон и текущий месяц — «первый ход», закрытый месяц — «не было ходов»', () => {
    assert.match(S.noMeLine(null, 'season', '2026-11-06T09:00:00Z'), /^Сделай первый ход/);
    assert.match(S.noMeLine('Юность', '2026-11', '2026-11-06T09:00:00Z'), /на матч Юность/);
    assert.match(S.noMeLine(null, '2026-10', '2026-11-06T09:00:00Z'), /не было ходов/);
  });
  it('строка про корону: порог трёх, моё положение, звание сезона', () => {
    const view = { players_with_points: 5, me: { rank: 3 }, to_crown: 20 };
    assert.match(S.tableCrownLine(view, 'Юность', '2026-11', 'сезон 2026/27'), /^Корона ноябрь · Юность — первому после последнего матча месяца\. До неё 20.очков\.$/);
    assert.match(S.tableCrownLine({ players_with_points: 5, me: { rank: 1 }, to_crown: 0 }, null, '2026-11', ''), /Сейчас она твоя/);
    assert.match(S.tableCrownLine({ players_with_points: 2 }, null, '2026-11', ''), /хотя бы у троих/);
    assert.match(S.tableCrownLine(view, null, 'season', 'сезон 2026/27'), /Знаток сезона 2026\/27/);
    assert.match(S.tableCrownLine(view, 'Юность', 'season', 'сезон 2026/27'), /Знаток Юность 2026\/27/);
  });
  it('вершины: чип и плитка, корона записью', () => {
    const p = { club: 'Юность', period: '2026-11', period_title: 'ноябрь', rank: 2, players: 38 };
    assert.equal(S.peakChip(p), 'Юность · ноябрь · 2' + NBSP + 'место');
    assert.deepEqual(S.peakTile(p, []), { rank: '2', label: 'Юность · ноябрь', note: 'из 38', gold: false });
    const crown = [{ kind: 'month', period: '2026-11', club: 'Юность' }];
    assert.equal(S.peakTile(Object.assign({}, p, { rank: 1 }), crown).note, 'корона твоя');
    assert.equal(S.peakTile(Object.assign({}, p, { rank: 1 }), []).note, 'лидер среза');
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
  it('форма: без команды и с перепутанными датами создать нельзя', () => {
    assert.equal(S.formError({ scope: 'pick', clubs: [], term: 'season' }), 'Нужна команда');
    assert.equal(S.formError({ scope: 'all', clubs: [], term: 'dates', startsOn: '', endsOn: '' }), 'Укажи даты');
    assert.equal(S.formError({ scope: 'all', clubs: [], term: 'dates', startsOn: '2026-12-01', endsOn: '2026-11-01' }), 'Конец раньше начала');
    assert.equal(S.formError({ scope: 'all', clubs: [], term: 'season' }), '');
  });
  it('«Как будет»: матчи в срок, предупреждение про малое число матчей', () => {
    const f = { scope: 'pick', clubs: ['Юность'], term: 'weeks4' };
    const prev = { starts_at: '2026-11-05T21:00:00Z', ends_at: '2026-12-03T21:00:00Z', matches_in_term: 3, few_matches: true };
    const s = S.termsSummary(f, prev);
    assert.match(s.what, /^Матчи: Юность · ещё 3.матча в срок$/);
    assert.match(s.when, /^С 6.ноября по 3.декабря · корона победителю в конце$/);
    assert.match(s.few, /мало/);
    assert.equal(S.termsSummary({ scope: 'pick', clubs: [], term: 'season' }, null).what, 'Выбери хотя бы одну команду');
    assert.match(S.termsSummary({ scope: 'all', clubs: [], term: 'season' }, Object.assign({}, prev, { few_matches: false })).when, /корона каждый месяц и чемпион лиги в конце/);
  });
  it('строка про корону лиги: месяц и весь срок', () => {
    const l = { term: 'season', ends_at: '2027-07-31T21:00:00Z', period: { key: '2026-11' } };
    assert.equal(S.leagueCrownLine(l, 'month', { rank: 3, points: 210 }, 230), 'Корона лиги за ноябрь — 30' + NBSP + 'ноября. Твоё место 3, до первого 20' + NBSP + 'очков.');
    assert.match(S.leagueCrownLine(l, 'month', { rank: 1, points: 230 }, 230), /Сейчас она твоя/);
    assert.match(S.leagueCrownLine(l, 'all', null, 0), /^Чемпион лиги — 31.июля/);
    assert.match(S.leagueCrownLine({ term: 'month', ends_at: '2026-11-30T21:00:00Z' }, 'all', null, 0), /^Корона лиги — 30.ноября/);
  });
  it('приглашение без азартных слов', () => {
    assert.match(S.inviteText('Офис', { scope: 'extraliga', clubs: [] }), /Вся Экстралига/);
  });
});

describe('карточка болельщика', () => {
  it('подписи корон и званий сезона', () => {
    assert.equal(S.crownLabel({ kind: 'month', club: 'Юность', period: '2026-10' }), 'Октябрь · болельщики Юность');
    assert.equal(S.crownLabel({ kind: 'month', club: null, period: '2026-10' }), 'Октябрь · все игроки');
    assert.equal(S.crownLabel({ kind: 'league_month', league_name: 'Офис', period: '2026-11' }), 'Ноябрь · лига «Офис»');
    assert.equal(S.crownLabel({ kind: 'league_term', league_name: 'Офис' }), 'Чемпион лиги «Офис»');
    const lines = S.seasonTitleLine({ overall: { rank: 214, players: 1380, to_first: 900 }, club: { name: 'Юность' }, club_place: { rank: 3, players: 212, to_first: 40 } }, '2026/27');
    assert.equal(lines[0].label, 'Знаток сезона · все матчи');
    assert.equal(lines[1].label, 'Знаток Юность 2026/27');
    assert.equal(lines[1].note, 'до 1-го 40');
  });
});

describe('слова игры', () => {
  const FILES = ['kto-kogo-model.js', 'kto-kogo-screens-model.js', 'kto-kogo.js', 'kto-kogo-views.js', 'kto-kogo-board.js', 'kto-kogo-leagues.js'];
  const BANNED = /ставк|коэффициент|прогноз|пари\b|выигрыш|букмекер|банк\b|ставь|поставить/i;
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
});
