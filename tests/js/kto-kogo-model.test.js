/**
 * TASK-299: «Кто кого» — даты в минском времени, цвета пары команд, тексты.
 *
 * Run: node --test tests/js/kto-kogo-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const M = require('../../static/webapp/kto-kogo-model.js');

const NBSP = ' ';
const NOW = new Date('2026-10-19T09:00:00Z'); // понедельник, 12:00 в Минске

describe('whenLabel', () => {
  it('сегодня, завтра, день недели, дата — в минском времени', () => {
    assert.equal(M.whenLabel('2026-10-19T16:30:00Z', NOW), 'сегодня, 19:30');
    assert.equal(M.whenLabel('2026-10-20T14:00:00Z', NOW), 'завтра, 17:00');
    assert.equal(M.whenLabel('2026-10-22T16:30:00Z', NOW), 'в четверг, 19:30');
    assert.equal(M.whenLabel('2026-10-28T16:00:00Z', NOW), '28' + NBSP + 'октября, 19:00');
    assert.equal(M.whenLabel('2026-10-18T14:00:00Z', NOW), 'вчера, 17:00');
  });
  it('без ведущего нуля у часа', () => {
    assert.equal(M.whenLabel('2026-10-20T06:05:00Z', NOW), 'завтра, 9:05');
  });
  it('kicker', () => {
    assert.equal(M.kicker('2026-10-22T16:30:00Z'), 'чт, 22' + NBSP + 'октября · 19:30');
  });
});

describe('pairColors', () => {
  it('Динамо и Барыс — два тёмно-синих: гости нейтральные', () => {
    const c = M.pairColors({ color: '#003DA5' }, { color: '#003E73' });
    assert.equal(c.home, '#003DA5');
    assert.notEqual(c.away, '#003E73');
    assert.ok(M.colorDistance(c.home, c.away) >= 120);
  });
  it('Динамо и Ак Барс различимы — свои цвета', () => {
    assert.deepEqual(M.pairColors({ color: '#003DA5' }, { color: '#006B3F' }), { home: '#003DA5', away: '#006B3F' });
  });
  it('нет цвета — нейтральный', () => {
    assert.equal(M.pairColors({}, { color: '#8C1515' }).home, M.NEUTRAL);
  });
});

describe('тексты', () => {
  it('склонения', () => {
    assert.equal(M.points(1), '1' + NBSP + 'очко');
    assert.equal(M.points(3), '3' + NBSP + 'очка');
    assert.equal(M.points(11), '11' + NBSP + 'очков');
    assert.equal(M.points(22), '22' + NBSP + 'очка');
  });
  it('друзья на половинке', () => {
    assert.equal(M.fansLine([], true), 'ты первый');
    assert.equal(M.fansLine(['Катя'], true), 'ты и' + NBSP + 'Катя');
    assert.equal(M.fansLine(['Катя', 'Саша'], true), 'ты и' + NBSP + 'ещё' + NBSP + '2');
    assert.equal(M.fansLine(['Катя', 'Саша'], false), 'Катя, Саша');
    assert.equal(M.fansLine(['Катя', 'Саша', 'Игорь'], false), 'Катя и' + NBSP + 'ещё' + NBSP + '2');
    assert.equal(M.fansLine([], false), '');
  });
  it('итог по правилам FIFA: 50, 30, 20, 10, 0 — разные слова, без «в точку» мимо цели', () => {
    assert.equal(M.EXACT, 50);
    assert.equal(M.verdict(50).head, 'в точку!');
    assert.equal(M.verdict(50).sticker, '+50');
    assert.equal(M.verdict(30).head, 'почти в точку');
    assert.equal(M.verdict(20).sticker, '+20');
    assert.equal(M.verdict(10).head, 'шайбы угаданы');
    assert.equal(M.verdict(0).tone, 'miss');
    for (const p of [0, 10, 20, 30]) assert.notEqual(M.verdict(p).head, 'в точку!');
    // Род собеседника неизвестен — подписи без «угадал/угадала».
    for (const p of [0, 10, 20, 30, 50]) assert.ok(!/угадал[аи]?\b/.test(M.verdict(p).tail), M.verdict(p).tail);
    assert.match(M.RULES, /Победитель — 20/);
  });
});

describe('счёт и ссылки', () => {
  it('ход звучит как ставка, без нового правила', () => {
    const names = { home: 'Динамо-Минск', away: 'Спартак' };
    const side = { side: 'home', home_score: null, away_score: null };
    const score = { side: 'home', home_score: 3, away_score: 1 };
    assert.equal(M.stakeLine(null, names, 'open'), '');
    assert.equal(M.stakeLine(side, names, 'open'), 'ход принят · ты за' + NBSP + 'Динамо-Минск');
    assert.equal(M.stakeLine(score, names, 'open'), 'ход принят · 3:1 · в точку — 50');
    assert.equal(M.stakeLine(score, names, 'live'), 'твой счёт 3:1 · ждём сирену');
    assert.equal(M.stakeLine(null, names, 'live'), 'ходы закрыты · этот матч без тебя');
    assert.equal(M.moveLine(score, names), 'твой счёт 3:1');
    assert.equal(M.scoreHint(3, 1), '3:1 · в точку — 50');
    assert.equal(M.scoreHint(2, 2), 'В хоккее ничьих нет');
    assert.equal(M.nudgeLine({ home: [], away: [] }, names), 'без хода очков не будет · победитель — 20');
    assert.equal(
      M.nudgeLine({ home: ['Катя'], away: [] }, names),
      'Катя уже за' + NBSP + 'Динамо-Минск · твой ход — 20'
    );
    assert.equal(
      M.nudgeLine({ home: ['Катя'], away: ['Саша'] }, names),
      'Катя и' + NBSP + 'ещё' + NBSP + '1 уже сделали ход · твой — 20'
    );
  });
  it('черновик счёта 0…20', () => {
    assert.equal(M.clampGoals(-1), 0);
    assert.equal(M.clampGoals(25), 20);
    assert.equal(M.scoreError(2, 2), 'В хоккее ничьих нет');
    assert.equal(M.scoreError(2, 3), '');
  });
  it('kk_<код>', () => {
    assert.equal(M.inviteCode('kk_abcd2345'), 'ABCD2345');
    assert.equal(M.inviteCode('arena_12'), '');
    assert.equal(M.inviteCode('kk_'), '');
  });
  it('ссылки с карточек в чате: код лиги и откуда пришли', () => {
    assert.equal(M.inviteCode('kkl_abcd2345'), 'ABCD2345');
    assert.equal(M.inviteCode('kkr_abcd2345'), 'ABCD2345');
    assert.equal(M.inviteCode('kkr'), '');
    assert.equal(M.cardFrom('kkl_abcd2345', null), 'league');
    assert.equal(M.cardFrom('kkr', null), 'result');
    assert.equal(M.cardFrom('kk_abcd2345', null), '');
    assert.equal(M.cardFrom('', 'league'), 'league');
    assert.equal(M.cardFrom('', 'hack'), '');
  });
});
