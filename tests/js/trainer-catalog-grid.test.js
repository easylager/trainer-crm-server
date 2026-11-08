/**
 * Каталог тренеров на сайте: на широком экране карточки в две колонки.
 * Run: node --test tests/js/trainer-catalog-grid.test.js
 */
'use strict';

const { it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const css = fs.readFileSync(path.resolve(__dirname, '../../static/share/trainer-catalog.css'), 'utf8');

it('.tcat-grid: две колонки от 720px', () => {
  assert.match(css, /@media \(min-width:\s*720px\)\s*\{\s*\.tcat-grid\s*\{[^}]*repeat\(2,/);
});
