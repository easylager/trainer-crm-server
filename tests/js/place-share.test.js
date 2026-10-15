/**
 * TASK-252: place-share.js — тот же контракт GlideShareSheet.open, что arena-card.
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const placeSharePath = path.resolve(__dirname, '../../static/share/place-share.js');
const src = fs.readFileSync(placeSharePath, 'utf8');
const PD = require(path.resolve(__dirname, '../../static/webapp/public-display-model.js'));

describe('place-share.js (TASK-252)', () => {
  it('открывает GlideShareSheet с arena_card и sessionId', () => {
    assert.match(src, /GlideShareSheet\.open\(/);
    assert.match(src, /context:\s*'arena_card'/);
    assert.match(src, /venueType:\s*'ice'/);
    assert.match(src, /sessionId:\s*sid/);
    assert.match(src, /shareSlots/);
    assert.match(src, /shareSlotsGrouped/);
  });

  it('тап по билету не уходит с страницы', () => {
    assert.match(src, /preventDefault\(\)/);
    assert.match(src, /data-session-id/);
  });

  it('тап показывает и обновляет блок «Выбранный сеанс»', () => {
    assert.match(src, /paintPlan\(/);
    assert.match(src, /setPlanText\(plan, 'time'/);
    assert.match(src, /setPlanText\(plan, 'soon'/);
    assert.match(src, /showPlan: true/);
  });

  it('док зовёт «Погнали», а не «Расписание»', () => {
    assert.match(src, /invite:\s*true/);
    assert.doesNotMatch(src, /invite:\s*invite\b/);
    assert.match(src, /PD\.inviteCtaWhen/);
    assert.doesNotMatch(src, /formatClock\(when\)/);
  });

  it('без ?s= окно не прокручивается', () => {
    assert.match(src, /searchParams\.has\('s'\)/);
    assert.match(src, /if \(openedOnSession\) revealAboveDock\(\)/);
    assert.doesNotMatch(src, /place-share-zovi/);
  });

  it('подпись: сегодня, завтра, дальше', () => {
    const today = '2026-10-13';
    assert.equal(PD.inviteCtaWhen(today, '22:15', today), '22:15');
    assert.equal(PD.inviteCtaWhen('2026-10-14', '12:15', today), 'завтра 12:15');
    assert.equal(PD.inviteCtaWhen('2026-10-17', '10:15', today), 'сб 10:15');
    assert.equal(PD.inviteCtaWhen('2026-10-14', '09:00', today), 'завтра 9:00');
  });
});
