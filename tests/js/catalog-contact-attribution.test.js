/**
 * Catalog → trainer Telegram attribution copy.
 * Run: node --test tests/js/catalog-contact-attribution.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/catalog-contact-attribution.js');

function loadModel() {
  delete require.cache[require.resolve(modelPath)];
  return require(modelPath);
}

describe('catalog contact attribution', () => {
  it('hint politely asks to mention Glide', () => {
    const { hintText } = loadModel();
    const t = hintText();
    assert.match(t, /Если не сложно/);
    assert.match(t, /Glide/);
    assert.ok(t.length < 120);
  });
});
