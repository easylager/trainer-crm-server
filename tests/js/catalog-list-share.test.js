/**
 * TASK-253: catalog-list-share.js — контракт GlideShareSheet как ice-tab.
 * Run: node --test tests/js/catalog-list-share.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const src = fs.readFileSync(
  path.resolve(__dirname, '../../static/share/catalog-list-share.js'),
  'utf8'
);

describe('catalog-list-share.js (TASK-253)', () => {
  it('открывает GlideShareSheet для приглашения и подборки', () => {
    assert.match(src, /GlideShareSheet\.open\(/);
    assert.match(src, /invite:\s*true/);
    assert.match(src, /context:\s*'ice_list'/);
    assert.match(src, /endpoint:\s*endpoint/);
  });

  it('ловит клик по data-invite-arena и data-catalog-selection-share', () => {
    assert.match(src, /closest\('\[data-invite-arena\]'\)/);
    assert.match(src, /closest\('\[data-catalog-selection-share\]'\)/);
    assert.match(src, /preventDefault/);
  });
});
