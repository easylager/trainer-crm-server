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

describe('витрина следует теме Telegram', () => {
  it('trainers.html без data-force-theme — colorScheme сам', () => {
    const html = fs.readFileSync(
      path.resolve(__dirname, '../../static/webapp/trainers.html'),
      'utf8',
    );
    assert.doesNotMatch(html, /data-force-theme/);
  });

  it('showcase CSS: светлая Ice Paper и тёмная ARENA', () => {
    assert.match(css, /--a-bg:\s*#F1F3F2/);
    assert.match(css, /data-app-theme="dark"[\s\S]*--a-bg:\s*#0B0C0E/);
  });
});
