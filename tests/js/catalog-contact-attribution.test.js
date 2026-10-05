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
  it('hint is short and mentions Glide', () => {
    const { hintText } = loadModel();
    const t = hintText();
    assert.match(t, /Glide/i);
    assert.match(t, /по желанию/i);
    assert.ok(t.length < 120);
  });
});
