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
    GlideCopy: { t: (k) => (k === 'kind.hockey_practice' ? 'ОХМ' : k) },
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

describe('shareSlotsGrouped без Node global', () => {
  it('сеанс ОХМ не роняет шит «Поделиться» в браузере, где нет global', () => {
    const mtPath = path.resolve(__dirname, '../../static/webapp/minsk-time.js');
    const context = {
      window: {},
      document: {},
      GlideCopy: { t: (k) => (k === 'kind.hockey_practice' ? 'ОХМ' : k) },
    };
    context.window = context;
    vm.runInNewContext(fs.readFileSync(mtPath, 'utf8'), context);
    vm.runInNewContext(modelSrc, context);
    const sections = context.ArenaCardModel.shareSlotsGrouped(
      [
        {
          local_date: '2026-10-12',
          sessions: [
            { id: 1, kind: 'public_skate', starts_at_local: '10:00', price_adult_minor: 1200, currency_code: 'BYN' },
            { id: 2, kind: 'hockey_practice', starts_at_local: '13:00', price_adult_minor: 1500, currency_code: 'BYN' },
          ],
        },
      ],
      '2026-10-12'
    );
    assert.equal(sections.length, 1);
    assert.equal(sections[0].rows[1].meta, '15 BYN · ОХМ');
  });
});
