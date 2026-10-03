/**
 * TASK-148 (AC-4): блок «Сегодня на льду» — строки из ice_teaser.sessions.
 *   - нет тизера / нет сеансов / только тизерный — блока нет ([]);
 *   - тизерный сеанс из строк исключается (блок дополняет, а не дублирует);
 *   - начавшиеся сеансы пропускаются;
 *   - максимум 3 строки.
 * Run: node --test tests/js/hub-ice-today-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/hub-ice-today-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

/** «Сейчас» для сэмплов: все сеансы в будущем. */
const NOW = new Date('2026-09-06T12:00:00Z');

function session(overrides) {
  return Object.assign(
    {
      session_id: 102,
      arena_id: 12,
      arena_slug: 'chizhovka',
      arena_name: 'Чижовка',
      venue_type: 'ice',
      kind: 'public_skate',
      starts_at_utc: '2026-09-06T16:30:00Z',
      local_date: '2026-09-06',
      starts_at_local: '19:30',
      price_adult_minor: 1000,
      currency_code: 'BYN',
    },
    overrides || {}
  );
}

function teaser(overrides) {
  return Object.assign(
    {
      session_id: 101,
      arena_id: 12,
      arena_name: 'Чижовка',
      starts_at_utc: '2026-09-06T15:00:00Z',
      sessions: [
        session({ session_id: 101, starts_at_utc: '2026-09-06T15:00:00Z', starts_at_local: '18:00' }),
        session({ session_id: 102 }),
        session({
          session_id: 103,
          arena_id: 13,
          arena_name: 'Парк Горького',
          venue_type: 'outdoor',
          starts_at_utc: '2026-09-06T17:15:00Z',
          starts_at_local: '20:15',
          price_adult_minor: 0,
        }),
      ],
    },
    overrides || {}
  );
}

describe('rowsFromTeaser: блок только при сеансах', () => {
  it('отсутствует без тизера', () => {
    const { rowsFromTeaser } = loadModel();
    assert.deepEqual(rowsFromTeaser(null, NOW), []);
  });

  it('отсутствует, когда у тизера нет sessions', () => {
    const { rowsFromTeaser } = loadModel();
    assert.deepEqual(rowsFromTeaser({ session_id: 101, arena_id: 12 }, NOW), []);
  });

  it('отсутствует, когда есть только тизерный сеанс', () => {
    const { rowsFromTeaser } = loadModel();
    const t = teaser({
      sessions: [session({ session_id: 101, starts_at_utc: '2026-09-06T15:00:00Z', starts_at_local: '18:00' })],
    });
    assert.deepEqual(rowsFromTeaser(t, NOW), []);
  });

  it('дополняет тизер: тизерный сеанс исключается, остальные — строками', () => {
    const { rowsFromTeaser } = loadModel();
    const rows = rowsFromTeaser(teaser(), NOW);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].time, '19:30');
    assert.equal(rows[0].place, 'Чижовка · крытый');
    assert.equal(rows[0].price, '10 BYN');
    assert.equal(rows[1].time, '20:15');
    assert.equal(rows[1].place, 'Парк Горького · открытый');
    assert.equal(rows[1].price, '0 BYN');
  });

  it('пропускает начавшиеся сеансы', () => {
    const { rowsFromTeaser } = loadModel();
    const t = teaser({
      sessions: [
        session({ session_id: 101, starts_at_utc: '2026-09-06T15:00:00Z', starts_at_local: '18:00' }),
        session({ session_id: 102, starts_at_utc: '2026-09-06T10:00:00Z', starts_at_local: '13:00' }),
        session({ session_id: 103, starts_at_utc: '2026-09-06T17:15:00Z', starts_at_local: '20:15' }),
      ],
    });
    const rows = rowsFromTeaser(t, NOW);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].time, '20:15');
  });

  it('не больше трёх строк', () => {
    const { rowsFromTeaser, MAX_ROWS } = loadModel();
    const t = teaser({
      sessions: [
        session({ session_id: 101, starts_at_utc: '2026-09-06T15:00:00Z', starts_at_local: '18:00' }),
        session({ session_id: 102, starts_at_utc: '2026-09-06T16:00:00Z', starts_at_local: '19:00' }),
        session({ session_id: 103, starts_at_utc: '2026-09-06T17:00:00Z', starts_at_local: '20:00' }),
        session({ session_id: 104, starts_at_utc: '2026-09-06T18:00:00Z', starts_at_local: '21:00' }),
        session({ session_id: 105, starts_at_utc: '2026-09-06T19:00:00Z', starts_at_local: '22:00' }),
      ],
    });
    assert.equal(rowsFromTeaser(t, NOW).length, MAX_ROWS);
  });

  it('старый payload без session_id: тизерный сеанс исключается по арене и времени', () => {
    const { rowsFromTeaser } = loadModel();
    const t = teaser({ session_id: null });
    t.sessions = [
      session({ session_id: null, starts_at_utc: '2026-09-06T15:00:00Z', starts_at_local: '18:00' }),
      session({ session_id: null, starts_at_utc: '2026-09-06T16:30:00Z', starts_at_local: '19:30' }),
    ];
    const rows = rowsFromTeaser(t, NOW);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].time, '19:30');
  });
});

describe('rowHref: конвенция IceTabModel.arenaHref', () => {
  it('ведёт на карточку места с выделенным днём и сеансом', () => {
    const { rowHref } = loadModel();
    assert.equal(rowHref(session({})), 'arena?ref=12&day=2026-09-06&s=102');
  });
});

describe('renderRowsHtml', () => {
  it('пустой список — пустая разметка', () => {
    const { renderRowsHtml } = loadModel();
    assert.equal(renderRowsHtml([]), '');
  });

  it('рисует строки время · место · цена', () => {
    const { rowsFromTeaser, renderRowsHtml } = loadModel();
    const rows = rowsFromTeaser(teaser(), NOW);
    const html = renderRowsHtml(rows);
    assert.ok(html.includes('hub-ice-today__row'));
    assert.ok(html.includes('19:30'));
    assert.ok(html.includes('Чижовка'));
    assert.ok(html.includes('10 BYN'));
  });
});
