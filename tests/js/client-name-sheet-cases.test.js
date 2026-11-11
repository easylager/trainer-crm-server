/**
 * TASK-382: общая таблица входов имени — та же, что в tests/application/test_client_account.py.
 * Run: node --test tests/js/client-name-sheet-cases.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const nameSheet = require(path.resolve(__dirname, '../../static/webapp/client-name-sheet.js'));
const table = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../fixtures/display_name_cases.json'), 'utf8'));

describe('общая таблица входов имени (как сервер)', () => {
  for (const c of table.cases) {
    it(c.note, () => {
      const got = nameSheet.checkDisplayName(c.input);
      assert.equal(got.ok, c.valid);
      if (c.valid) assert.equal(got.name, c.result);
      assert.equal(nameSheet.draftState('', c.input).canSave, c.valid);
    });
  }

  it('подсказка: пусто и «нет буквы» — разные', () => {
    assert.equal(nameSheet.draftState('', 'ㅤ').hint, 'Имя не может быть пустым');
    assert.equal(nameSheet.draftState('', '!!!').hint, 'Нужна хотя бы одна буква, цифра или эмодзи');
    assert.equal(nameSheet.draftState('', 'Макс').hint, '');
  });
});
