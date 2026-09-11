/**
 * Catalog entry must open one self-contained carousel (with phone), never vitrine polish.
 * Run: node --test tests/js/ice-map-sheet-fab.test.js  (and this file)
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

function read(name) {
  return fs.readFileSync(path.join(webapp, name), 'utf8');
}

describe('catalog carousel — одна самодостаточная карусель', () => {
  it('хаб не открывает task=vitrine для каталога', () => {
    const js = read('trainer-home-main.js');
    assert.equal(
      (js.match(/task=vitrine/g) || []).length,
      0,
      'profile_catalog / open_profile должны вести в catalog'
    );
    assert.match(js, /openHubCatalogProfileGaps/);
    assert.match(js, /task=catalog/);
  });

  it('vitrine — алиас catalog; рельс без education/about', () => {
    const js = read('trainer-profile-main.js');
    assert.match(js, /if \(task === 'vitrine'\) task = 'catalog'/);
    const catalogBlock = js.slice(
      js.indexOf("catalog: {"),
      js.indexOf("vitrine: {")
    );
    assert.match(catalogBlock, /phone/);
    assert.match(catalogBlock, /anketa_main/);
    assert.ok(!/education/.test(catalogBlock));
    assert.ok(!/about/.test(catalogBlock));
  });
});
