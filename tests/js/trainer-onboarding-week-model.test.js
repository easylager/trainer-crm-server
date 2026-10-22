'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const M = require(path.resolve(__dirname, '../../static/webapp/trainer-onboarding-week-model.js'));

const EVE = M.windowById('eve');
const MOR = M.windowById('mor');
const DAY = M.windowById('day');
const noArena = () => null;

describe('Онбординг: окна недели → точные старты', () => {
  it('60 минут: вечер — каждый час, последнее занятие кончается в 23:00', () => {
    assert.deepEqual(M.windowStarts(EVE, null, 60).map(M.minuteLabel),
      ['17:00', '18:00', '19:00', '20:00', '21:00', '22:00']);
  });

  it('90 минут: шаг полтора часа, занятия не налезают друг на друга', () => {
    assert.deepEqual(M.windowStarts(EVE, null, 90).map(M.minuteLabel), ['17:00', '18:30', '20:00', '21:30']);
    assert.deepEqual(M.windowStarts(DAY, null, 90).map(M.minuteLabel), ['12:00', '13:30', '15:00']);
  });

  it('смещение катка (:30) и его часы работы', () => {
    const rink = { id: 5, grid_kind: 'hourly_minute', minute_offset: 30, hour_start: 8, hour_end: 10 };
    assert.deepEqual(M.windowStarts(MOR, rink, 60).map(M.minuteLabel), ['8:30', '9:30', '10:30']);
  });

  it('фиксированная длительность катка важнее выбора тренера', () => {
    const rink = { id: 7, fixed_duration_minutes: 90 };
    const day = M.fillWindow({}, EVE, rink, 60, (id) => (id === 7 ? rink : null));
    assert.deepEqual(Object.keys(day).map(Number).map(M.minuteLabel), ['17:00', '18:30', '20:00', '21:30']);
    assert.equal(day[17 * 60].a, 7);
  });

  it('окно целиком не задевает уже отмеченное на другом катке', () => {
    const a = { id: 1 };
    const b = { id: 2 };
    const byId = (id) => ({ 1: a, 2: b }[id] || null);
    const day = { [18 * 60]: { a: 1, d: null } };
    M.fillWindow(day, EVE, b, 60, byId);
    assert.equal(day[18 * 60].a, 1, 'чужой старт не перезаписан');
    assert.equal(day[17 * 60].a, 2);
    assert.equal(day[19 * 60].a, 2);
  });

  it('тап: свой старт снимается, пересекающийся — нельзя', () => {
    const day = { [18 * 60]: { a: null, d: 90 } };
    assert.equal(M.toggleStart(day, 19 * 60, null, 60, noArena), 'blocked', '19:00 внутри 18:00–19:30');
    assert.equal(M.toggleStart(day, 20 * 60, null, 60, noArena), 'added');
    assert.equal(M.toggleStart(day, 18 * 60, null, 60, noArena), 'removed');
    assert.equal(M.toggleStart(day, 17 * 60, { id: 3 }, 60, noArena), 'added');
    assert.equal(M.toggleStart(day, 17 * 60, null, 60, noArena), 'blocked', 'чужая площадка');
  });

  it('снять окно: только своей площадки или всё', () => {
    const day = { 1020: { a: 1, d: null }, 1080: { a: 2, d: null }, 600: { a: 1, d: null } };
    M.clearWindow(day, EVE, 1);
    assert.deepEqual(Object.keys(day).map(Number).sort((x, y) => x - y), [600, 1080]);
    M.clearWindow(day, EVE);
    assert.deepEqual(Object.keys(day).map(Number), [600]);
  });

  it('свой старт вне сетки (13:25) остаётся в своём окне', () => {
    assert.equal(M.windowOf(13 * 60 + 25), DAY);
    assert.equal(M.windowOf(5 * 60), MOR);
    assert.equal(M.windowOf(23 * 60), EVE);
  });

  it('сводка склеивает дни с одинаковым временем', () => {
    const slot = { a: null, d: null };
    const week = {
      0: { 1080: slot, 1140: slot },
      2: { 1080: slot, 1140: slot },
      5: { 540: slot },
    };
    assert.deepEqual(M.weekSummary(week), [
      { days: 'пн, ср', times: '18:00 · 19:00' },
      { days: 'сб', times: '9:00' },
    ]);
    assert.deepEqual(M.previewStarts(week, 3), [
      { day: 'пн', time: '18:00' },
      { day: 'ср', time: '18:00' },
      { day: 'сб', time: '9:00' },
    ]);
    assert.equal(M.totalStarts(week), 5);
  });
});
