/**
 * TASK-204: arena schedule mode copy — mirror Python arena_schedule_mode.py.
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/arena-schedule-mode-model.js');
const M = require(modelPath);

describe('arena schedule mode model', () => {
  it('phone line and tel href', () => {
    assert.equal(M.phoneLine(), 'Расписание по телефону');
    assert.equal(M.phoneToTelHref('+375 (29) 111-22-33'), 'tel:+375291112233');
  });

  it('phoneToTelHref uses only the first semicolon-separated number', () => {
    assert.equal(
      M.phoneToTelHref('+375447885600; +375233435259'),
      'tel:+375447885600',
    );
  });

  it('phoneToTelHref strips extension and parenthetical notes', () => {
    assert.equal(
      M.phoneToTelHref('+375 29 123-45-67 доб. 12'),
      'tel:+375291234567',
    );
    assert.equal(
      M.phoneToTelHref('8 017 222-22-22 (10:00-22:00)'),
      'tel:80172222222',
    );
    assert.equal(
      M.phoneToTelHref('+375 (29) 33 00 749 (+ Telegram)'),
      'tel:+375293300749',
    );
  });

  it('season closed with reopen date', () => {
    const line = M.seasonClosedLine({
      schedule_mode: 'season_closed',
      schedule_reopen_date: '2026-11-01',
      schedule_mode_note: 'ремонт',
    });
    assert.match(line, /Сезон закрыт/);
    assert.match(line, /откроется 01\.11/);
    assert.match(line, /ремонт/);
  });
});
