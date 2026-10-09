/**
 * Основание расписания (projected / photo / manual) клиенту в Mini App не показываем.
 * Run: node --test tests/js/schedule-basis-hint.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

function load(file) {
  const p = path.resolve(__dirname, '../../static/webapp/' + file);
  delete require.cache[require.resolve(p)];
  return require(p);
}

const now = new Date('2026-09-06T08:00:00Z');

function iceItem(basis, more) {
  return {
    id: 3,
    name: 'Каток',
    tier: 'A',
    live: {
      kind: 'session',
      local_date: '2026-09-06',
      starts_at_local: '18:15',
      price_adult_minor: 1000,
      currency_code: 'BYN',
      more_count: more,
      schedule_basis: basis,
    },
  };
}

describe('лента «Лёд»: boardCardView', () => {
  it('projected/photo не подменяют depth — обычный счётчик или «Расписание и цены»', () => {
    const { boardCardView } = load('ice-tab-model.js');
    assert.equal(boardCardView(iceItem('projected', 69), now).depth, 'Ещё 69 сеансов в расписании');
    assert.equal(boardCardView(iceItem('photo', 0), now).depth, 'Расписание и цены');
    assert.doesNotMatch(boardCardView(iceItem('projected', 0), now).depth, /сетка|фото|вручную/i);
  });

  it('live — прежняя подпись глубины', () => {
    const { boardCardView } = load('ice-tab-model.js');
    assert.equal(boardCardView(iceItem('live', 69), now).depth, 'Ещё 69 сеансов в расписании');
    assert.equal(boardCardView(iceItem(undefined, 0), now).depth, 'Расписание и цены');
  });
});

describe('карточка арены: buildRibbonForDay', () => {
  function session(basis) {
    return {
      id: 1,
      kind: 'public_skate',
      starts_at_utc: '2026-09-06T15:15:00Z',
      ends_at_utc: '2026-09-06T16:15:00Z',
      starts_at_local: '18:15',
      ends_at_local: '19:15',
      local_date: '2026-09-06',
      price_adult_minor: 1000,
      currency_code: 'BYN',
      schedule_basis: basis,
    };
  }

  it('не-live сеанс не несёт подпись основания в meta', () => {
    const { buildRibbonForDay } = load('arena-card-model.js');
    const rows = buildRibbonForDay({ now, sessions: [session('manual')] });
    assert.equal(rows.length, 1);
    assert.doesNotMatch(rows[0].meta, /уточните|вручную|сетка|фото/i);
    assert.equal(rows[0].scheduleBasis, 'manual');
  });

  it('scheduleBasisHint пустой для любого основания', () => {
    const { scheduleBasisHint } = load('arena-card-model.js');
    assert.equal(scheduleBasisHint({}), '');
    assert.equal(scheduleBasisHint({ schedule_basis: 'projected' }), '');
    assert.equal(scheduleBasisHint({ schedule_basis: 'photo' }), '');
  });
});
