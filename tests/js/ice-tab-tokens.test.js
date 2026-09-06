/**
 * TASK-076 AC-001: Ice tab and arena card chrome use Mini App teal tokens, not prototype amber.
 * Run: node --test tests/js/ice-tab-tokens.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

function readCss(name) {
  return fs.readFileSync(path.join(webapp, name), 'utf8');
}

describe('ice / arena brand tokens (TASK-076 AC-001)', () => {
  it('ice-tab.css does not hardcode prototype amber as the screen brand', () => {
    const css = readCss('ice-tab.css');
    assert.ok(!/#c2761a/i.test(css));
    assert.ok(!/194,\s*118,\s*26/.test(css));
    assert.match(css, /--app-cta-fill/);
    assert.match(css, /--accent-rgb|--glide-ink-teal|--app-cta-text/);
  });

  it('arena-card.css lesson stripe uses app CTA fill without an amber fallback', () => {
    const css = readCss('arena-card.css');
    assert.ok(!/#c2761a/i.test(css));
    assert.match(css, /\.arena-row--lesson[\s\S]*--app-cta-fill/);
    assert.match(css, /\.arena-cta--solid[\s\S]*--app-cta-fill/);
  });
});
