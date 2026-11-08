/**
 * Горизонтальные вкладки витрины не должны отдавать вертикальный жест в сворачивание TG.
 * Run: node --test tests/js/trainer-showcase-swipe-tabs.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const css = fs.readFileSync(
  path.resolve(__dirname, '../../static/webapp/trainer-showcase.css'),
  'utf8',
);

function block(selector) {
  const re = new RegExp(selector.replace('.', '\\.') + '\\s*\\{([^}]+)\\}');
  const m = re.exec(css);
  assert.ok(m, 'нет правила ' + selector);
  return m[1];
}

describe('swipeable tabs vs Telegram collapse', () => {
  for (const sel of ['.tabsA', '.seg']) {
    it(sel + ': pan-x + overscroll contain, без вертикального overflow', () => {
      const b = block(sel);
      assert.match(b, /touch-action:\s*pan-x/);
      assert.match(b, /overscroll-behavior-x:\s*contain/);
      assert.match(b, /overflow-x:\s*auto/);
      assert.match(b, /overflow-y:\s*hidden/);
    });
  }
});

describe('витрина на фоне каталога/катков (--g-*)', () => {
  it('фон страницы — var(--g-bg), как catalog-hub / ice-hub', () => {
    assert.match(css, /background:\s*var\(--g-bg\)\s*!important/);
    assert.match(css, /--a-bg:\s*var\(--g-bg/);
    assert.match(css, /--a-sf:\s*var\(--g-surface/);
    assert.doesNotMatch(css, /--a-bg:\s*#0B0C0E/);
  });

  it('theme.js ставит body.tg-dark для сайтных --g-*', () => {
    const js = fs.readFileSync(
      path.resolve(__dirname, '../../static/webapp/client-mini-app-theme.js'),
      'utf8',
    );
    assert.match(js, /classList\.toggle\('tg-dark',\s*dark\)/);
  });
});
