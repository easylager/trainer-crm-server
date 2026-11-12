/**
 * Вкладки бара клиента: одинаковый <meta name="viewport"> на всех страницах.
 * Иначе env(safe-area-inset-bottom) на iOS разный, и бар прыгает по высоте при переключении
 * (так было с «Кто кого» и viewport-fit=cover).
 * Run: node --test tests/js/client-tab-pages-viewport.test.js
 */
'use strict';

const { it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const PAGES = ['client-home', 'ice', 'client-bookings', 'kto-kogo', 'client-me'];

function viewportOf(page) {
  const html = fs.readFileSync(path.resolve(__dirname, '../../static/webapp', page + '.html'), 'utf8');
  const m = html.match(/<meta name="viewport" content="([^"]*)">/);
  assert.ok(m, page + ': нет meta viewport');
  return m[1];
}

it('все вкладки бара объявляют один и тот же viewport', () => {
  const ref = viewportOf(PAGES[0]);
  for (const page of PAGES) assert.equal(viewportOf(page), ref, page);
});
