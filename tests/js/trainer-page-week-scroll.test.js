/**
 * Горизонтальные ленты публичной страницы тренера (неделя, «ещё») на телефоне занимают
 * почти весь экран: `touch-action: pan-x` без `pan-y` отнимает у клиента вертикальный скролл.
 * Run: node --test tests/js/trainer-page-week-scroll.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const css = fs.readFileSync(path.resolve(__dirname, '../../static/share/trainer-page.css'), 'utf8');
const cardCss = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/trainer-showcase.css'), 'utf8');

describe('страница тренера: горизонтальные ленты не блокируют вертикальный жест', () => {
  for (const sel of ['.tp-week', '.tp-more']) {
    it(sel + ': touch-action содержит pan-x и pan-y', () => {
      const re = new RegExp('\\' + sel + '\\s*\\{([^}]+)\\}', 'g');
      const bodies = [...css.matchAll(re)].map((m) => m[1]).filter((b) => /overflow-x:\s*auto/.test(b));
      assert.ok(bodies.length > 0, 'нет горизонтально скроллящегося правила ' + sel);
      for (const b of bodies) {
        const ta = /touch-action:\s*([^;]+);/.exec(b);
        assert.ok(ta, 'нет touch-action у ' + sel);
        assert.match(ta[1], /\bpan-x\b/);
        assert.match(ta[1], /\bpan-y\b/);
      }
    });
  }
});

describe('витрина: ленты не отнимают вертикальный скролл страницы', () => {
  for (const sel of ['.tabsA', '.seg', '.tc-seg', '.tc-h-days']) {
    it(sel + ': touch-action содержит pan-x и pan-y', () => {
      const re = new RegExp('\\' + sel + '\\s*\\{([^}]+)\\}', 'g');
      const bodies = [...cardCss.matchAll(re)].map((m) => m[1]).filter((b) => /overflow-x:\s*auto/.test(b));
      assert.ok(bodies.length > 0, 'нет горизонтально скроллящегося правила ' + sel);
      for (const b of bodies) {
        const ta = /touch-action:\s*([^;]+);/.exec(b);
        assert.ok(ta, 'нет touch-action у ' + sel);
        assert.match(ta[1], /\bpan-x\b/);
        assert.match(ta[1], /\bpan-y\b/);
      }
    });
  }
});
