/**
 * TASK-222: компактный шеринг в шапке ленты рядом с подписью результата.
 * Run: node --test tests/js/ice-share-head.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

describe('ice share head (TASK-222)', () => {
  it('вместо «Ближе» в шапке ленты — компактная «Поделиться», нижняя кнопка на месте', () => {
    const html = fs.readFileSync(path.join(webapp, 'ice.html'), 'utf8');
    assert.match(html, /id="iceShareHeadBtn"/);
    assert.match(html, /class="ice-share-head"/);
    assert.match(html, /ice-share-head__icon/);
    assert.match(html, /Поделиться<\/span>/);
    assert.match(html, /id="iceShareBtn"/);
    assert.doesNotMatch(html, /id="iceNearestBtn"/);
    assert.doesNotMatch(html, />Ближе</);
  });

  it('ice-tab.js вешает тот же openIceShareDialog на шапку и низ', () => {
    const js = fs.readFileSync(path.join(webapp, 'ice-tab.js'), 'utf8');
    assert.match(js, /iceShareHeadBtn/);
    assert.match(js, /shareHead\.addEventListener\('click', openIceShareDialog\)/);
    assert.match(js, /shareBtn\.addEventListener\('click', openIceShareDialog\)/);
  });

  it('CSS: пилюля с иконкой CTA-цвета, без заливки-конкурента карточке', () => {
    const css = fs.readFileSync(path.join(webapp, 'ice-tab.css'), 'utf8');
    assert.match(css, /TASK-222\. Компактный шеринг/);
    assert.match(css, /\.ice-share-head \{[\s\S]*?border-radius:\s*var\(--app-radius-pill\)/);
    assert.match(css, /\.ice-share-head \{[\s\S]*?background:\s*var\(--glide-surface\)/);
    assert.match(css, /\.ice-share-head__icon \{[\s\S]*?color:\s*var\(--app-cta-fill\)/);
    assert.doesNotMatch(css, /\.ice-nearest\s*\{/);
  });
});
