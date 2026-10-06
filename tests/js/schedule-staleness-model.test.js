/**
 * TASK-180: schedule staleness copy — mirror Python schedule_staleness.py.
 * Run: node --test tests/js/schedule-staleness-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/schedule-staleness-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

describe('TASK-180 schedule staleness (AC-3)', () => {
  it('checkedAtLabel uses Minsk calendar days at 01:00', () => {
    const { checkedAtLabel } = loadModel();
    const now = new Date('2026-10-05T22:00:00.000Z'); // 01:00 Minsk 6 Oct
    assert.equal(checkedAtLabel('2026-10-05T21:20:00.000Z', now), 'сегодня в 00:20');
    assert.equal(checkedAtLabel('2026-10-05T20:50:00.000Z', now), 'вчера в 23:50');
  });

  it('stale and very_stale notes match backend wording', () => {
    const { staleNote, veryStaleNote } = loadModel();
    const now = new Date('2026-10-06T06:00:00.000Z');
    const stale = {
      schedule_stale: true,
      schedule_very_stale: false,
      schedule_observed_at: '2026-10-05T15:40:00.000Z',
    };
    assert.match(staleNote(stale, now), /^Расписание могло измениться · проверено /);
    const very = {
      schedule_stale: true,
      schedule_very_stale: true,
      schedule_observed_at: '2026-10-02T09:00:00.000Z',
    };
    assert.equal(veryStaleNote(very, now, { hasPhone: true }), 'Расписание не обновлялось 4 дня — уточните по телефону');
  });
});
