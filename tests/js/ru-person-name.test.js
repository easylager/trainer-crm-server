/**
 * Russian person-name display + inflection for the client request form.
 * Run: node --test tests/js/ru-person-name.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('path');

const modPath = path.resolve(__dirname, '../../static/webapp/ru-person-name.js');

function load() {
  const resolved = require.resolve(modPath);
  delete require.cache[resolved];
  return require(modPath);
}

describe('formatPersonName', () => {
  it('joins first and last with a single space', () => {
    const { formatPersonName } = load();
    assert.equal(formatPersonName('Александр', 'Гаевский'), 'Александр Гаевский');
  });

  it('splits a glued Cyrillic first+last in one field', () => {
    const { formatPersonName } = load();
    assert.equal(formatPersonName('АлександрГаевский', ''), 'Александр Гаевский');
  });

  it('does not duplicate last name already sitting in first', () => {
    const { formatPersonName } = load();
    assert.equal(formatPersonName('Александр Гаевский', 'Гаевский'), 'Александр Гаевский');
  });

  it('keeps a trailing emoji on the given name', () => {
    const { formatPersonName } = load();
    assert.equal(formatPersonName('Максим🪴', 'Василенко'), 'Максим🪴 Василенко');
  });

  it('title-cases ALL CAPS input', () => {
    const { formatPersonName } = load();
    assert.equal(formatPersonName('АЛЕКСАНДР', 'ГАЕВСКИЙ'), 'Александр Гаевский');
  });
});

describe('requestHeading genitive', () => {
  it('склоняет для Александра Гаевского', () => {
    const { requestHeading } = load();
    assert.equal(requestHeading('Александр', 'Гаевский'), 'Для Александра Гаевского');
  });

  it('склоняет Максима Иванова', () => {
    const { requestHeading } = load();
    assert.equal(requestHeading('Максим', 'Иванов'), 'Для Максима Иванова');
  });

  it('склоняет женское имя и фамилию', () => {
    const { requestHeading } = load();
    assert.equal(requestHeading('Мария', 'Иванова'), 'Для Марии Ивановой');
    assert.equal(requestHeading('Ольга', 'Петрова'), 'Для Ольги Петровой');
  });

  it('склоняет Андрея и Никиту', () => {
    const { requestHeading } = load();
    assert.equal(requestHeading('Андрей', 'Сергеев'), 'Для Андрея Сергеева');
    assert.equal(requestHeading('Никита', 'Козлов'), 'Для Никиты Козлова');
  });
});

describe('dativeLine', () => {
  it('даёт Александру Гаевскому', () => {
    const { dativeLine } = load();
    assert.equal(dativeLine('Александр', 'Гаевский'), 'Александру Гаевскому');
  });

  it('даёт Марии Ивановой', () => {
    const { dativeLine } = load();
    assert.equal(dativeLine('Мария', 'Иванова'), 'Марии Ивановой');
  });
});

describe('catalog request form wiring', () => {
  it('loads the name helper and no longer shouts ЗАЯВКА ДЛЯ', () => {
    const html = fs.readFileSync(
      path.resolve(__dirname, '../../static/webapp/catalog.html'),
      'utf8'
    );
    const js = fs.readFileSync(
      path.resolve(__dirname, '../../static/webapp/catalog-main.js'),
      'utf8'
    );
    assert.match(html, /ru-person-name\.js/);
    assert.match(html, /request-sheet__title/);
    assert.doesNotMatch(html, /Комментарий к заявке/);
    assert.match(js, /requestHeading/);
    assert.doesNotMatch(js, /Заявка для /);
  });
});
