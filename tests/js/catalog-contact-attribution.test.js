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
  it('hint only says the chat opens in Telegram', () => {
    const { hintText } = loadModel();
    const t = hintText();
    assert.match(t, /Telegram/);
    assert.match(t, /Личный чат/);
    assert.ok(t.length < 120);
  });
});
