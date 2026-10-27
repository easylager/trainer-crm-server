'use strict';
// Ранняя загрузка записи (TASK-314) стартует до обёртки fetch с заголовком ngrok — заголовок и проверка тела нужны ей самой.
const { it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, '../../static/webapp/schedule-editor.html'), 'utf8');
const main = fs.readFileSync(path.join(__dirname, '../../static/webapp/schedule-editor-main.js'), 'utf8');

it('ранний запрос записи сам шлёт ngrok-skip-browser-warning и не принимает ответ без id', () => {
  const early = html.slice(html.indexOf('__seEarlyBooking'), html.indexOf('window.__seEarlyBooking = {'));
  assert.match(early, /ngrok-skip-browser-warning/);
  assert.match(early, /j\.id != null/);
});

it('если ранний запрос не удался, запись грузится обычным путём', () => {
  assert.match(main, /early\.promise\.catch\(function\(\) \{ return getJsonTrainer/);
});
