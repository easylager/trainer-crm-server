/**
 * TASK-438: табло «Поиск» — ряд дней, лента, «Неделя», «Выходные».
 * Run: node --test tests/js/ice-board-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const M = require(path.resolve(__dirname, '../../static/webapp/ice-board-model.js'));

function s(id, date, start, arena, extra) {
  return Object.assign(
    {
      session_id: id,
      date: date,
      start: start,
      end: '',
      group: 'skate',
      kind: 'public_skate',
      label: null,
      arena_id: arena,
      arena_name: 'Каток ' + arena,
      thumb: null,
      price_adult: '12 BYN',
      price_rental: '',
    },
    extra || {}
  );
}

describe('dayOptions', () => {
  it('weekday Mon–Thu: today, tomorrow, weekend, week', () => {
    const o = M.dayOptions('2026-11-23'); // Пн
    assert.deepEqual(o.map((x) => x.id), ['today', 'tomorrow', 'weekend', 'week']);
    assert.equal(o[2].from, '2026-11-28');
    assert.equal(o[2].days, 2);
  });
  it('Friday drops tomorrow: it is already the weekend', () => {
    const o = M.dayOptions('2026-11-27');
    assert.deepEqual(o.map((x) => x.id), ['today', 'weekend', 'week']);
    assert.equal(o[1].from, '2026-11-28');
  });
  it('Saturday and Sunday have no weekend option', () => {
    assert.deepEqual(M.dayOptions('2026-11-21').map((x) => x.id), ['today', 'tomorrow', 'week']);
    assert.deepEqual(M.dayOptions('2026-11-22').map((x) => x.id), ['today', 'tomorrow', 'week']);
  });
});

describe('day feed', () => {
  const payload = {
    today: '2026-11-21',
    now_local: '12:35',
    days: [{ date: '2026-11-21', skate: 4, hockey: 0, figure: 0 }],
    sessions: [
      s(1, '2026-11-21', '13:00', 1),
      s(2, '2026-11-21', '13:00', 2, { price_rental: '10 BYN' }),
      s(3, '2026-11-21', '14:00', 1),
      s(4, '2026-11-21', '18:15', 3, { kind: 'family_skate', price_adult: '' }),
    ],
    matches: [{ match_id: 9, date: '2026-11-21', start: '13:00', home: { name: 'Химик' }, away: { name: 'Юность' } }],
  };

  it('headline counts sessions and arenas, nearest start from now', () => {
    const h = M.dayHeadline(payload, 'skate', '2026-11-21');
    assert.equal(h.title, '4 сеанса массового');
    assert.equal(h.sub, 'сегодня на 3 катках · ближайший через 25 минут');
  });

  it('timeline groups by time and puts the match after sessions', () => {
    const rows = M.timeline(payload, 'skate', '2026-11-21');
    assert.deepEqual(rows.map((r) => r.time), ['13:00', '14:00', '18:15']);
    assert.deepEqual(rows[0].items.map((i) => i.type), ['session', 'session', 'match']);
    assert.equal(rows[0].items[1].price, '12 BYN · прокат 10');
    assert.equal(rows[0].items[0].href, 'arena?ref=1&day=2026-11-21&s=1');
    assert.equal(rows[2].items[0].price, 'семейный · цена на месте');
  });

  it('figure feed carries no matches', () => {
    assert.equal(M.timeline(payload, 'figure', '2026-11-21').length, 0);
  });

  it('split shows the rest count and a family hint', () => {
    const split = M.splitTimeline(M.timeline(payload, 'skate', '2026-11-21'), 1);
    assert.equal(split.more.label, 'Показать дальше · ещё 2');
    assert.equal(split.more.hint, 'есть семейный в 18:15');
  });

  it('empty day says so instead of a zero', () => {
    assert.equal(M.dayHeadline(payload, 'hockey', '2026-11-21').title, 'Нет сеансов с клюшкой');
  });
});

describe('week and weekend', () => {
  const days = ['2026-11-21', '2026-11-22', '2026-11-23'];
  const payload = {
    today: '2026-11-21',
    now_local: '12:00',
    days: days.map((d) => ({ date: d, skate: 1, hockey: 0, figure: 0 })),
    sessions: [
      s(1, '2026-11-21', '10:00', 1),
      s(2, '2026-11-22', '11:00', 1),
      s(3, '2026-11-23', '23:00', 1),
      s(4, '2026-11-21', '17:30', 2, { price_adult: '8,50 BYN' }),
      s(5, '2026-11-22', '16:00', 2, { price_adult: '9 BYN' }),
    ],
  };

  it('week rows: busiest arena first, day cells link to the arena on that day', () => {
    const rows = M.weekArenas(payload, 'skate');
    assert.equal(rows[0].arena_id, 1);
    assert.equal(rows[0].meta, 'каждый день 10:00–23:00 · 12 BYN');
    assert.equal(rows[1].meta, 'по выходным · 8,50–9 BYN');
    assert.deepEqual(rows[1].cells.map((c) => c.count), [1, 1, 0]);
    assert.equal(rows[1].cells[0].href, 'arena?ref=2&day=2026-11-21');
    assert.equal(rows[1].cells[2].href, '');
    assert.equal(rows[0].next, 'сегодня в 10:00');
  });

  it('weekend columns cap times and link the overflow to the arena day', () => {
    const many = { today: '2026-11-21', days: [{ date: '2026-11-21' }, { date: '2026-11-22' }], sessions: [] };
    for (let i = 0; i < 6; i++) many.sessions.push(s(10 + i, '2026-11-21', String(10 + i) + ':00', 7));
    const rows = M.weekendArenas(many, 'skate');
    assert.equal(rows[0].cols[0].times.length, M.WEEKEND_TIMES);
    assert.equal(rows[0].cols[0].more, 2);
    assert.equal(rows[0].cols[0].moreHref, 'arena?ref=7&day=2026-11-21');
    assert.equal(rows[0].cols[1].times.length, 0);
    assert.equal(rows[0].cols[0].label, 'Сб');
  });

  it('week header carries totals per day', () => {
    const h = M.weekHeader(payload, 'skate');
    assert.deepEqual(h.map((d) => [d.short, d.num, d.total]), [['Сб', 21, 1], ['Вс', 22, 1], ['Пн', 23, 1]]);
    assert.equal(h[0].isToday, true);
  });
});
