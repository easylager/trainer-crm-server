/**
 * Ice map: mini card below the map (not over pins); list pill at tab bar.
 * Run: node --test tests/js/ice-map-sheet-fab.test.js
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

describe('ice map layout — карточка под картой', () => {
  it('мини-карточка в потоке, не absolute overlay', () => {
    const css = read('ice-tab.css');
    const block = css.slice(
      css.indexOf('body.ice-view-map .ice-map-sheet {'),
      css.indexOf('body.ice-view-map .ice-map-sheet:empty')
    );
    assert.match(block, /position:\s*relative/);
    assert.ok(!/position:\s*absolute/.test(block), 'не должна перекрывать пины');
  });

  it('список скрыт в режиме карты (без чёрной дыры над картой)', () => {
    const css = read('ice-tab.css');
    assert.match(css, /body\.ice-view-map\s+#iceListSec/);
    assert.match(css, /display:\s*none\s*!important/);
  });

  it('после paintSheet вызывается fitToViewport', () => {
    const js = read('ice-map.js');
    assert.match(js, /fitToViewport/);
    assert.match(js, /Sheet in-flow changes map stage height/);
  });
});
