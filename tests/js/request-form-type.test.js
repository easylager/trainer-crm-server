/**
 * Catalog request form — calm type hierarchy (approved 2026-09-10 prototype).
 * Run: node --test tests/js/request-form-type.test.js
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

describe('форма заявки в каталоге — спокойная иерархия', () => {
  it('убирает отдельный hint и кладёт подсказку в placeholder', () => {
    const html = read('catalog.html');
    assert.ok(!html.includes('request-sheet__hint'), 'отдельный hint не должен остаться');
    assert.match(
      html,
      /placeholder="Когда удобно, возраст, что хотите получить"/
    );
  });

  it('заголовок и поле не кричат сильнее chrome', () => {
    const css = read('mini-app-catalog.css');
    const titleBlock = css.slice(css.indexOf('.request-sheet__title'), css.indexOf('.request-sheet__note'));
    assert.match(titleBlock, /--app-text-title/);
    assert.ok(!/--app-text-headline/.test(titleBlock));

    const inputBlock = css.slice(css.indexOf('.request-comment-input {'), css.indexOf('.request-comment-input:focus'));
    assert.match(inputBlock, /--app-text-body/);
    assert.ok(!/--app-text-lead/.test(inputBlock));
  });
});
