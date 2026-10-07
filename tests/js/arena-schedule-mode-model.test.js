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

  it('phoneToTelHref skips dot-times and keeps the real number', () => {
    assert.equal(
      M.phoneToTelHref('пн-пт 10.00-22.00; +375 29 123-45-67'),
      'tel:+375291234567',
    );
    assert.equal(
      M.phoneToTelHref('10.00-22.00; 8 017 222-22-22'),
      'tel:80172222222',
    );
    assert.equal(
      M.phoneToTelHref('Касса 10.00-22.00 тел 8 017 222-22-22'),
      'tel:80172222222',
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

  it('phoneToTelHref keeps only the first of adjacent numbers', () => {
    assert.equal(M.phoneToTelHref('8 029 111-11-11 8 029 222-22-22'), 'tel:80291111111');
    assert.equal(M.phoneToTelHref('8 017 222-22-22\n8 029 111 22 33'), 'tel:80172222222');
    assert.equal(M.phoneToTelHref('80291111111 80292222222'), 'tel:80291111111');
    assert.equal(M.phoneToTelHref('8 017 222-22-22 10.00-22.00'), 'tel:80172222222');
  });

  it('phoneToTelHref respects the 64/256 scan window', () => {
    assert.equal(M.phoneToTelHref('x'.repeat(60) + '+375291234567'), 'tel:+375291234567');
    assert.equal(M.phoneToTelHref('x'.repeat(70) + '+375291234567'), '');
    assert.equal(M.phoneToTelHref('8' + ' '.repeat(50) + '1'.repeat(300)), '');
  });

  it('phoneToTelHref ignores calendar dates', () => {
    assert.equal(M.phoneToTelHref('07.10.2026'), '');
    assert.equal(M.phoneToTelHref('2026.10.07'), '');
    assert.equal(M.phoneToTelHref('закрыто до 01.11.2026'), '');
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
