/**
 * ОХМ + МК в одном списке сеансов для share sheet.
 * Run: node --test tests/js/arena-card-model-share-days.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const modelPath = path.resolve(__dirname, '../../static/webapp/arena-card-model.js');
const modelSrc = fs.readFileSync(modelPath, 'utf8');

function loadModel() {
  const context = {
    window: {},
    global: {},
    document: {},
    GlideCopy: { t: (k) => (k === 'kind.hockey_practice' ? 'Хоккей для любителей (ОХМ)' : k) },
  };
  context.global = context.window = context;
  vm.runInNewContext(modelSrc, context);
  return context.ArenaCardModel;
}

describe('ArenaCardModel.combineSessionDayLists', () => {
  const M = loadModel();

  it('склеивает days и ohm_days по local_date', () => {
    const merged = M.combineSessionDayLists(
      [{ local_date: '2026-10-12', sessions: [{ id: 1, kind: 'public_skate', starts_at_local: '09:00' }] }],
      [{ local_date: '2026-10-12', sessions: [{ id: 99, kind: 'hockey_practice', starts_at_local: '13:00' }] }]
    );
    assert.equal(merged.length, 1);
    assert.equal(merged[0].sessions.length, 2);
    assert.ok(merged[0].sessions.some((s) => s.id === 99));
  });

  it('экспортирует combineSessionDayLists', () => {
    assert.equal(typeof M.combineSessionDayLists, 'function');
  });
});
