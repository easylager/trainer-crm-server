/** TASK-343: Mini App-блок «Зимой» включается только при зимних точках в фасете. */
'use strict';
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

global.window = global;
global.document = { getElementById: () => null, addEventListener() {}, createElement() { return {}; }, body: {} };
global.GlideWinter = require(path.resolve(__dirname, '../../static/shared/winter-model.js'));
require(path.resolve(__dirname, '../../static/webapp/winter-points.js'));

describe('IceWinter.sync', () => {
  const base = { cityId: 1, near: '', authHeaders: () => ({}) };
  it('вне «Зимой» блока нет', () => {
    assert.equal(global.IceWinter.sync({ ...base, season: '', facet: { count: 3, winter_points: 3 } }), false);
  });
  it('в «Зимой» без зимних точек (только закрытые арены) блока нет', () => {
    assert.equal(global.IceWinter.sync({ ...base, season: 'winter', facet: { count: 2 } }), false);
  });
  it('без города блока нет', () => {
    assert.equal(global.IceWinter.sync({ ...base, cityId: null, season: 'winter', facet: { winter_points: 2 } }), false);
  });
});
