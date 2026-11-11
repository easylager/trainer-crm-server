'use strict';
// Внутри Telegram «назад» одна: нативная стрелка в шапке. Своя круглая кнопка игры на подэкранах её дублирует.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..', '..', 'static', 'webapp');
const js = fs.readFileSync(path.join(root, 'kto-kogo.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'kto-kogo.css'), 'utf8');

test('игра помечает страницу, когда у Telegram есть нативная «назад»', () => {
  assert.match(js, /MiniAppBack\.isNative\(\)\)\s*document\.body\.classList\.add\('kk-native-back'\)/);
});

test('при нативной «назад» своя кнопка в строке экрана скрыта, а в полосе шапки только невидима', () => {
  assert.match(css, /\.kk-native-back \.kk-top > \.kk-round\[aria-label="Назад"\]\s*\{\s*display:\s*none;/);
  assert.match(css, /\.kk-native-back \.kk-hero__bar > \.kk-round\[aria-label="Назад"\]\s*\{\s*visibility:\s*hidden;/);
});

test('без нативной «назад» (браузер) правил скрытия нет: класс добавляется только по isNative', () => {
  const adds = js.match(/classList\.add\('kk-native-back'\)/g) || [];
  assert.equal(adds.length, 1);
});
