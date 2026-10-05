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
  it('prefill mentions Glide and is gender-neutral', () => {
    const { prefillText } = loadModel();
    const t = prefillText();
    assert.match(t, /Glide/i);
    assert.match(t, /Здравствуйте/);
    assert.ok(!/\(а\)/.test(t));
  });

  it('hint explains editable prefill', () => {
    const { hintText } = loadModel();
    assert.match(hintText(), /Telegram/);
    assert.match(hintText(), /отредактировать/);
  });
});
