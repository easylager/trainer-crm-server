/**
 * «Кто кого», хаб v2: блок «Твоя команда», день без этого матча, счёт и сторона, очки из констант.
 *
 * Run: TZ=UTC node --test tests/js/kto-kogo-hub-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../../static/webapp/kto-kogo-model.js');
const S = require('../../static/webapp/kto-kogo-screens-model.js');

const NOW = new Date('2026-11-03T09:00:00Z'); // вторник, 12:00 в Минске
const mk = (id, iso, extra) => Object.assign({ id, starts_at: iso, open: true, status: 'scheduled', league: 'extraliga', my_pick: null, home_team: 'A', away_team: 'B' }, extra || {});
const khl = (id, iso, home, away, extra) => mk(id, iso, Object.assign({ league: 'khl', home_team: home, away_team: away }, extra || {}));

describe('очки — те же числа, что на сервере', () => {
  const py = fs.readFileSync(path.join(__dirname, '../../src/application/hockey_game.py'), 'utf8');
  const num = (name) => Number(new RegExp('^' + name + ' = (\\d+)', 'm').exec(py)[1]);
  it('POINTS на клиенте равны POINTS_* в hockey_game.py', () => {
    assert.equal(M.POINTS.winner, num('POINTS_WINNER'));
    assert.equal(M.POINTS.diff, num('POINTS_DIFF'));
    assert.equal(M.POINTS.goals, num('POINTS_GOALS'));
    assert.equal(M.POINTS.exact, M.POINTS.winner + M.POINTS.diff + 2 * M.POINTS.goals);
  });
  it('закрытие ходов на клиенте равно PICK_CLOSES_BEFORE в hockey_game.py', () => {
    const sec = Number(/^PICK_CLOSES_BEFORE = timedelta\(seconds=(\d+)\)/m.exec(py)[1]);
    assert.equal(M.PICK_CLOSES_BEFORE_SEC, sec);
    assert.equal(M.closesAt('2026-11-05T16:30:00Z').toISOString(), '2026-11-05T16:29:00.000Z');
    assert.equal(S.closeTime('2026-11-05T16:30:00Z'), '19:29');
    assert.equal(S.closeTime('2026-11-05T21:00:00Z'), '23:59');
  });
  it('козырь: строка под кнопкой — своя на каждый случай', () => {
    const wk = S.weekKey('2026-11-05T16:30:00Z');
    const a = { id: 1, starts_at: '2026-11-05T16:30:00Z', home: { name: 'Динамо-Минск' }, away: { name: 'Металлург Жлобин' }, my_pick: { side: 'home' } };
    const b = { id: 2, starts_at: '2026-11-06T16:30:00Z', home: { name: 'Локомотив Орша' }, away: { name: 'Лида' }, my_pick: { side: 'away' } };
    const now = NOW.toISOString();
    const free = [{ week_start: wk, match_id: null, locked: false }];
    assert.equal(S.trumpHint(a, free, [a, b], now), 'Один на неделю: очки за этот матч удвоятся.');
    const onA = [{ week_start: wk, match_id: 1, locked: false }];
    assert.equal(S.trumpHint({ ...a, my_pick: { side: 'home', doubled: true } }, onA, [a, b], now), 'Тапни ещё раз, чтобы снять.');
    assert.equal(S.trumpHint(a, [{ week_start: wk, match_id: 2, locked: true }], [a, b], now), 'Козырь этой недели уже сыгран.');
    assert.equal(S.trumpHint(a, [], [a, b], now), 'Козырь откроется 26\u00a0октября.');
    const onB = [{ week_start: wk, match_id: 2, locked: false }];
    assert.equal(S.trumpHint(a, onB, [a, b], now), 'Козырь этой недели стоит на матче Локомотив — Лида. Перенести сюда можно до 19:29.');
    assert.match(S.trumpHint({ id: 3, starts_at: a.starts_at, my_pick: null }, free, [], now), /^Сначала тапни за команду\.$/);
  });
});

describe('heroMatch — «Твоя команда»', () => {
  const list = [
    mk(1, '2026-11-03T15:30:00Z', { home_team: 'Химик', away_team: 'Локомотив Орша' }),
    khl(2, '2026-11-05T16:30:00Z', 'СКА', 'Динамо-Минск'),
    khl(3, '2026-11-08T16:30:00Z', 'Динамо-Минск', 'Спартак'),
  ];
  it('ближайший открытый матч любимого клуба — в гостях тоже', () => {
    const h = S.heroMatch(list, 'Динамо-Минск', NOW);
    assert.equal(h.match.id, 2);
    assert.equal(h.tag, 'ТВОЯ КОМАНДА');
  });
  it('закрытые матчи клуба пропускаются; открытых нет — блока нет', () => {
    const l = [khl(2, '2026-11-05T16:30:00Z', 'СКА', 'Динамо-Минск', { open: false }), list[0]];
    assert.equal(S.heroMatch(l, 'Динамо-Минск', NOW), null);
    assert.equal(S.heroMatch(list, 'Шахтер', NOW), null);
  });
  it('без клуба — матч Динамо, даже если ближайший день занят Экстралигой', () => {
    const h = S.heroMatch(list, null, NOW);
    assert.equal(h.match.id, 2);
    assert.equal(h.tag, 'МАТЧ ДНЯ');
  });
  it('без клуба и без Динамо — первый открытый матч', () => {
    assert.equal(S.heroMatch([list[0]], null, NOW).match.id, 1);
    assert.equal(S.heroMatch([], null, NOW), null);
  });
  it('подпись: день, время, лига, арена', () => {
    assert.equal(S.heroMeta(khl(2, '2026-11-05T16:30:00Z', 'СКА', 'Динамо-Минск', { arena: 'Минск-Арена' })), 'ЧТ 5 НОЯБРЯ · 19:30 · КХЛ · МИНСК-АРЕНА');
    assert.equal(S.heroMeta(mk(1, '2026-11-03T15:30:00Z')), 'ВТ 3 НОЯБРЯ · 18:30 · ЭКСТРАЛИГА');
  });
  it('«Можно менять до»', () => {
    assert.equal(S.changeUntil('2026-11-05T16:30:00Z', NOW), 'Можно менять в четверг до 19:29');
    assert.equal(S.changeUntil('2026-11-03T16:30:00Z', NOW), 'Можно менять сегодня до 19:29');
  });
});

describe('dayMatches без матча из «Твоей команды»', () => {
  const x1 = mk(11, '2026-11-03T15:30:00Z');
  const x2 = mk(12, '2026-11-03T16:00:00Z', { my_pick: { side: 'home' } });
  const dm = khl(2, '2026-11-05T16:30:00Z', 'СКА', 'Динамо-Минск');
  it('исключённый матч выпадает из дня и из счётчика', () => {
    const d = S.dayMatches([x1, x2, dm], NOW, 12);
    assert.deepEqual(d.items.map((m) => m.id), [11]);
    assert.equal(d.total, 1);
    assert.equal(d.made, 0);
  });
  it('если исключённый был единственным в день — берётся следующий день', () => {
    const d = S.dayMatches([x1, dm], NOW, 11);
    assert.deepEqual(d.items.map((m) => m.id), [2]);
    assert.equal(S.dayMatches([x1], NOW, 11), null);
  });
  it('заголовок: лига, «сегодня», смешанные лиги — «МАТЧИ»', () => {
    assert.equal(S.dayMatches([x1, x2], NOW).heading, 'ЭКСТРАЛИГА · СЕГОДНЯ, ВТ 3 НОЯБРЯ');
    const mixed = S.dayMatches([x1, khl(5, '2026-11-03T17:00:00Z', 'Динамо-Минск', 'СКА')], NOW);
    assert.equal(mixed.heading, 'МАТЧИ · СЕГОДНЯ, ВТ 3 НОЯБРЯ');
    assert.equal(mixed.mixed, true);
    assert.equal(S.dayMatches([dm], NOW).heading, 'КХЛ · ЧТ 5 НОЯБРЯ');
  });
});

describe('счёт и сторона согласованы', () => {
  const mine = { side: 'home', home_score: null, away_score: null };
  it('первый тап считает от 0:0; значения в пределах', () => {
    assert.deepEqual(S.stepScore(mine, null, 0, 1), [1, 0]);
    assert.deepEqual(S.stepScore(mine, null, 1, -1), [0, 0]);
    assert.deepEqual(S.stepScore(null, [20, 3], 0, 1), [20, 3]);
  });
  it('шаг идёт от черновика, а не от серверного счёта', () => {
    const m = { side: 'home', home_score: 3, away_score: 2 };
    assert.deepEqual(S.stepScore(m, null, 1, 1), [3, 3]);
    assert.deepEqual(S.stepScore(m, [4, 2], 0, 1), [5, 2]);
  });
  it('перевес переключает сторону', () => {
    assert.equal(S.effectivePick(mine, [0, 1]).side, 'away');
    assert.equal(S.effectivePick({ side: 'away' }, [2, 1]).side, 'home');
  });
  it('ничья: сторона прежняя, tie, отправлять нечего', () => {
    const e = S.effectivePick(mine, [2, 2]);
    assert.equal(e.tie, true);
    assert.equal(e.side, 'home');
  });
  it('без черновика — серверный ход как есть', () => {
    const e = S.effectivePick({ side: 'away', home_score: 1, away_score: 4 }, null);
    assert.deepEqual([e.side, e.score, e.tie], ['away', [1, 4], false]);
    assert.deepEqual(S.effectivePick(null, null), { side: null, score: null, tie: false });
  });
  it('тап по той же стороне ничего не отправляет, по другой — отправляет', () => {
    assert.equal(S.sideTapSends({ side: 'home', home_score: 3, away_score: 1 }, null, 'home'), false);
    assert.equal(S.sideTapSends({ side: 'home', home_score: 3, away_score: 1 }, null, 'away'), true);
    assert.equal(S.sideTapSends(null, null, 'home'), true);
    assert.equal(S.sideTapSends({ side: 'home' }, [0, 2], 'away'), false); // черновик уже сдвинул сторону
  });
  it('итог хода: счёт, козырь, без счёта, ничья', () => {
    const eff = (mineP, d) => S.effectivePick(mineP, d);
    assert.deepEqual(S.moveSummary(eff({ side: 'home' }, [3, 2]), true, 'Динамо-Минск'), { text: 'Твой ход: 3:2', sticker: 'с козырем' });
    assert.deepEqual(S.moveSummary(eff({ side: 'home' }, [3, 2]), false, 'Динамо-Минск'), { text: 'Твой ход: 3:2', sticker: '' });
    assert.deepEqual(S.moveSummary(eff({ side: 'away' }, null), false, 'СКА'), { text: 'Твой ход: за\u00a0СКА', sticker: '' });
    assert.deepEqual(S.moveSummary(eff({ side: 'away' }, null), true, 'СКА'), { text: 'Твой ход: за\u00a0СКА', sticker: 'с козырем' });
    assert.deepEqual(S.moveSummary(eff({ side: 'home' }, [2, 2]), true, 'X'), { text: 'Ничьей в хоккее не бывает — поправь счёт', sticker: '' });
    assert.equal(S.moveSummary(eff(null, null), false, 'X'), null);
  });
});
