'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const motion = require(path.resolve(__dirname, '../../static/share/glide-motion.js'));

describe('glide-motion', () => {
  it('labels only a session inside two hours', () => {
    const now = Date.parse('2026-10-16T12:00:00Z');
    assert.equal(motion.soonLabel(motion.minutesUntil('2026-10-16T12:40:00Z', now)), 'через 40 мин');
    assert.equal(motion.soonLabel(motion.minutesUntil('2026-10-16T14:30:00Z', now)), '');
    assert.equal(motion.soonLabel(motion.minutesUntil('2026-10-16T11:50:00Z', now)), '');
  });

  it('eases from zero to one', () => {
    assert.equal(motion.easeOut(0), 0);
    assert.equal(motion.easeOut(1), 1);
    assert.ok(motion.easeOut(0.5) > 0.5);
  });
});
