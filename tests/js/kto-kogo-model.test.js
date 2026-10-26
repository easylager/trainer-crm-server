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

describe('гонка месяца (TASK-334)', () => {
  const race = { monthly: true, title: 'ноябрь', played: 8, known: 12, final_match_id: 7 };
  it('шапка: месяц и сыграно, перед финалом — «остался финал», до гонки — «таблица»', () => {
    assert.deepEqual(M.raceHead(race), { title: 'ноябрь', left: 'сыграно 8 из 12' });
    assert.equal(M.raceHead({ ...race, played: 11 }).left, 'остался финал');
    assert.deepEqual(M.raceHead({ monthly: false }), { title: 'таблица', left: '' });
  });
  it('полоса: финал жёлтый только когда он известен', () => {
    const seg = M.raceSegments(race);
    assert.equal(seg.length, 12);
    assert.equal(seg.filter((x) => x === 'played').length, 8);
    assert.equal(seg[11], 'final');
    assert.equal(M.raceSegments({ ...race, final_match_id: null })[11], 'ahead');
  });
  it('погоня: до первого места, отрыв лидера, без меня — ничего', () => {
    const rows = [
      { rank: 1, display_name: 'Катя', points: 190 },
      { rank: 2, display_name: 'Я', points: 170, is_me: true },
    ];
    assert.deepEqual(M.chaseLine(rows), { text: 'Ты 2-й. До первого места', num: '20' + NBSP + 'очков' });
    const lead = [{ rank: 1, points: 50, is_me: true }, { rank: 2, points: 30 }];
    assert.deepEqual(M.chaseLine(lead), { text: 'Ты первый. Отрыв', num: '20' + NBSP + 'очков' });
    assert.equal(M.chaseLine([{ rank: 1, points: 10 }]), null);
  });
  it('строка финала и итоги месяца', () => {
    assert.equal(M.leaderNote({ leader: 'Катя', gap: 20, me_leading: false }), 'Катя впереди на 20' + NBSP + 'очков');
    assert.equal(M.leaderNote({ gap: 0, me_leading: true }), 'Очков поровну — решит финал');
    const won = { title: 'ноябрь', won: true, points: 280, league: { name: 'ОХМ' }, winners: ['Я'] };
    assert.equal(M.monthHead(won), 'ноябрь твой');
    assert.equal(M.monthLine(won), 'Первое место в «ОХМ» · 280' + NBSP + 'очков');
    const lost = { title: 'ноябрь', won: false, rank: 2, gap: 10, points: 250, league: null, winners: ['Катя', 'Саша'] };
    assert.equal(M.monthHead(lost), 'корона — Катя и Саша');
    assert.equal(M.monthLine(lost), 'Ты 2-й в общей таблице, до короны не хватило 10' + NBSP + 'очков');
  });
  it('вступил в середине месяца', () => {
    assert.equal(M.remainingLine(race), 'В этом месяце ещё 4 матча. Очки в лиге — с ближайшего матча, с 1-го числа все с нуля.');
    assert.equal(M.remainingLine({ monthly: false }), '');
  });
});
