/**
 * Suggested pass terms for a weekly lesson pack.
 * Run: node --test tests/js/pass-validity-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

const { recommendedValidityDays } = require('../../static/webapp/pass-validity-model.js');

describe('recommendedValidityDays', () => {
  it('leaves a short pack open-ended', () => {
    assert.equal(recommendedValidityDays(1), null);
    assert.equal(recommendedValidityDays(4), null);
  });

  it('gives a weekly pack about a week per visit plus slack', () => {
    assert.equal(recommendedValidityDays(8), 90);
    assert.equal(recommendedValidityDays(12), 120);
    assert.equal(recommendedValidityDays(16), 150);
    assert.equal(recommendedValidityDays(24), 180);
  });

  it('does not invent a term before the trainer enters a size', () => {
    assert.equal(recommendedValidityDays(0), null);
    assert.equal(recommendedValidityDays(''), null);
  });
});
