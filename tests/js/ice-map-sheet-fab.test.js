/**
 * Ice map layout (TASK-147): шторка overlay поверх карты; каркас шторки
 * собирается один раз и живёт постоянно; пины и кластеры с содержимым.
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

describe('ice map layout — шторка overlay (TASK-147)', () => {
  it('шторка fixed, прижата к таб-бару, высоту ставит JS', () => {
    const css = read('ice-tab.css');
    const start = css.indexOf('.ice-map-sheet {');
    const block = css.slice(start, css.indexOf('}', start));
    assert.match(block, /position:\s*fixed/);
    assert.match(block, /bottom:\s*var\(--client-shell-tab-inset/);
    assert.match(block, /height:\s*222px/, 'дефолтное half-положение');
  });

  it('карта в режиме карты — fixed на весь экран под таб-бар', () => {
    const css = read('ice-tab.css');
    const block = css.slice(
      css.indexOf('body.ice-view-map .ice-map-stage {'),
      css.indexOf('}', css.indexOf('body.ice-view-map .ice-map-stage {'))
    );
    assert.match(block, /position:\s*fixed/);
    assert.match(block, /inset:\s*0/);
  });

  it('каркас шторки собирается один раз (grab/head/toggle/rail), рельса живёт постоянно', () => {
    const js = read('ice-map.js');
    assert.match(js, /ice-map-sheet__grab/);
    assert.match(js, /ice-map-sheet__toggle/);
    // Rail — единственная динамическая часть: chrome.rail.innerHTML = ...
    assert.match(js, /chrome\.rail\.innerHTML/);
    assert.match(js, /__railBound/, 'скролл-слушатель вешается один раз, не умирает на repaint');
  });

  it('скролл рельсы и drag шторки — с локом и снапом', () => {
    const js = read('ice-map.js');
    assert.match(js, /railLock/);
    assert.match(js, /snapFor/);
    assert.match(js, /onSheetFull/, 'тяга вверх ведёт в списочный вид');
  });

  it('выделение пина трогает только сменившиеся плейсмарки', () => {
    const js = read('ice-map.js');
    assert.match(js, /obj\.properties\.get\('sel'\) !== want/);
  });

  it('кластер считает содержимое по geoObjects в build()', () => {
    const js = read('ice-map.js');
    assert.match(js, /clusterSummary\(items\)/);
    assert.match(js, /geoObjects/);
    assert.match(js, /ice-ycluster--quiet/);
  });

  it('zoomMargin кластера учитывает шторку и плавающий верх', () => {
    const js = read('ice-map.js');
    assert.match(js, /sheetVisiblePx\(\) \+ 24/);
    assert.match(js, /margin:\s*\[150, 70,/);
  });

  it('город: в списке пилюля у masthead, в карте — внутри поиска', () => {
    const css = read('ice-tab.css');
    const html = read('ice.html');
    assert.match(css, /\.ice-citypill--insearch\s*{\s*display:\s*none/);
    assert.match(css, /body\.ice-view-map \.ice-citypill--insearch\s*{\s*display:\s*inline-flex/);
    assert.match(html, /id="iceCityChange"/);
    assert.match(html, /ice-citypill--insearch/);
    // В hero-top город на месте (список не пострадал)
    assert.match(html, /ice-hero-top[\s\S]{0,200}ice-citypill/);
  });

  it('режим карты скрывает masthead, интент- и сервис- и вью-чипы, «Рядом» в поиске', () => {
    const css = read('ice-tab.css');
    const block = css.slice(
      css.indexOf('body.ice-view-map .ice-sec--hero .ice-kicker'),
      css.indexOf('}', css.indexOf('body.ice-view-map .ice-sec--hero .ice-kicker'))
    );
    assert.match(block, /\.ice-hero-top/);
    assert.match(block, /#iceIntentChips/);
    assert.match(block, /#iceVenueChips/);
    assert.match(block, /#iceNearestBtn/);
  });

  it('кнопка «Где я» — круглая FAB над шторкой, копирайт следует за шторкой', () => {
    const css = read('ice-tab.css');
    const fab = css.slice(css.indexOf('.ice-near {'), css.indexOf('}', css.indexOf('.ice-near {')));
    assert.match(fab, /width:\s*44px/);
    assert.match(fab, /border-radius:\s*50%/);
    assert.match(css, /ice-map-attrib/);
    assert.match(css, /body\.ice-view-map \.ice-viewswitch\s*{\s*display:\s*none/);
  });

  it('тёмная подложка — фильтр только на слое тайлов', () => {
    const css = read('ice-tab.css');
    assert.match(css, /html\.client-mini-dark \[class\*="ground-pane"\]/);
    assert.match(css, /invert\(1\)\s+hue-rotate\(180deg\)/);
  });

  it('бамп ?v= статики карты в ice.html', () => {
    const html = read('ice.html');
    for (const file of ['ice-tab.css', 'ice-map-model.js', 'ice-map.js', 'ice-tab.js']) {
      const m = html.match(new RegExp(file.replace('.', '\\.') + '\\?v=([0-9]+)'));
      assert.ok(m, file + ' подключён с ?v=');
      assert.ok(Number(m[1]) >= 202610041, file + ' версия бампнута, стоит ' + m[1]);
    }
  });

  it('VerticalSwipes: свайп шторки не конфликтует со свайпом закрытия мини-аппа', () => {
    const js = read('ice-tab.js');
    assert.match(js, /disableVerticalSwipes/);
    assert.match(js, /enableVerticalSwipes/);
  });
});
