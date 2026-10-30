'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const M = require(path.resolve(__dirname, '../../static/webapp/arena-card-model.js'));
const read = (rel) => fs.readFileSync(path.resolve(__dirname, '../..', rel), 'utf8');

describe('все виды сеансов в одном списке (фигурное, семейное, ОХМ)', () => {
  it('combineSessionDayLists берёт сколько угодно списков и сортирует день по времени', () => {
    const days = M.combineSessionDayLists(
      [{ local_date: '2026-11-01', sessions: [{ id: 1, starts_at_local: '18:15' }] }],
      [{ local_date: '2026-11-01', sessions: [{ id: 2, starts_at_local: '07:00', kind: 'hockey_practice' }] }],
      [{ local_date: '2026-11-01', sessions: [{ id: 3, starts_at_local: '12:00', kind: 'figure_free' }] }],
      [{ local_date: '2026-11-02', sessions: [{ id: 4, starts_at_local: '14:00', kind: 'family_skate' }] }]
    );
    assert.deepEqual(days.map((d) => d.sessions.map((s) => s.id)), [[2, 3, 1], [4]]);
  });

  it('allSessionDays собирает ответ /sessions целиком', () => {
    const days = M.allSessionDays({
      days: [],
      ohm_days: [],
      figure_days: [{ local_date: '2026-11-01', sessions: [{ id: 3, starts_at_local: '12:00' }] }],
      family_days: [{ local_date: '2026-11-01', sessions: [{ id: 4, starts_at_local: '14:00' }] }],
    });
    assert.deepEqual(days[0].sessions.map((s) => s.id), [3, 4]);
  });

  it('сайт и share sheet ищут сеанс и в фигурном, и в семейном', () => {
    const place = read('static/share/place-share.js');
    assert.match(place, /boot\.figureDays/);
    assert.match(place, /boot\.familyDays/);
    assert.match(place, /data\.figure_days/);
    for (const rel of ['static/share/catalog-list-share.js', 'static/webapp/ice-tab.js']) {
      assert.match(read(rel), /figure_days[\s\S]*family_days/, rel);
    }
  });
});
