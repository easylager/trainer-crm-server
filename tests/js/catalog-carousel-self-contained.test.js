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
  it('хаб ведёт в раздел «Каталог», а карусель запускает он', () => {
    /* TASK-140: хаб больше не открывает карусель сам. Все его ветки каталога ведут во вкладку
       «Каталог» — она знает состояние карточки и запускает визард с return, чтобы вернуть
       тренера к предпросмотру. Раньше хаб угадывал, какой флоу нужен, по двум флагам. */
    const js = read('trainer-home-main.js');
    assert.equal(
      (js.match(/task=vitrine/g) || []).length,
      0,
      'витрина как отдельный флоу не вернулась'
    );
    assert.equal(
      (js.match(/openHubCatalogProfileGaps/g) || []).length,
      0,
      'хаб не открывает карусель напрямую — это делает раздел «Каталог»'
    );
    assert.match(js, /navigateTo\('trainer-catalog'\)/);
    const section = read('trainer-catalog-main.js');
    assert.match(section, /task=catalog&return=trainer-catalog/);
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

  it('«Не сейчас» / крестик не шлют на модерацию', () => {
    const js = read('trainer-profile-main.js');
    assert.match(js, /finishFocusedProfileTask\(\{ submit: false \}\)/);
    assert.match(js, /finishFocusedProfileTask\(\{ submit: true \}\)/);
    assert.match(
      js,
      /wantSubmit = opts\.submit === true/
    );
    /* Force-submit только внутри ветки wantSubmit, не на каждый finish. */
    const finishFn = js.slice(
      js.indexOf('function finishFocusedProfileTask'),
      js.indexOf('function syncProfileBlockTourBar')
    );
    assert.match(finishFn, /if \(!wantSubmit \|\| !catalogish\)/);
    assert.match(finishFn, /maybeAutoSubmitForModeration\(\{ force: true \}\)/);
    assert.ok(
      finishFn.indexOf('if (!wantSubmit || !catalogish)') <
        finishFn.indexOf('maybeAutoSubmitForModeration({ force: true })')
    );
  });
});
