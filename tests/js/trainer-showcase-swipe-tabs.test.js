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

describe('витрина: светлая — --g-* каталога, тёмная — те же --g-*', () => {
  it('светлая тема на --g-*, токены объявлены и на body.tsw (там включается tg-dark)', () => {
    assert.match(css, /background:\s*var\(--a-bg\)\s*!important/);
    assert.match(css, /:root, body\.tsw \{/);
    assert.match(css, /--a-bg:\s*var\(--g-bg/);
    assert.match(css, /--a-sf:\s*var\(--g-surface/);
  });

  it('тёмная тема — те же --g-* каталога, без собственного графита', () => {
    const dark = css.split('body.tsw.tg-dark {')[1].split('}')[0];
    assert.doesNotMatch(dark, /--a-(bg|sf|tx|line)\s*:/);
    assert.doesNotMatch(css, /#0B0C0E/i);
  });

  it('theme.js ставит body.tg-dark для сайтных --g-*', () => {
    const js = fs.readFileSync(
      path.resolve(__dirname, '../../static/webapp/client-mini-app-theme.js'),
      'utf8',
    );
    assert.match(js, /classList\.toggle\('tg-dark',\s*dark\)/);
  });
});
