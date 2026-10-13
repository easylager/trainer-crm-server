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
});
