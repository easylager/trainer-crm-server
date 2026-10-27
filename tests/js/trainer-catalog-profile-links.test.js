'use strict';
// «Дополнить в анкете» ведёт в раздел нового профиля по недостающему полю, а не в старую анкету одним списком.
const { it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const src = fs.readFileSync(path.join(__dirname, '../../static/webapp/trainer-catalog-main.js'), 'utf8');
const account = fs.readFileSync(path.join(__dirname, '../../static/webapp/trainer-account-main.js'), 'utf8');

it('телефон ведёт в раздел «Контакты» с возвратом в каталог', () => {
  assert.match(src, /phone: 'trainer-profile\?task=contacts'/);
  assert.match(src, /'&return=trainer-catalog'/);
});

it('«Дополнить» больше не открывает голый trainer-profile', () => {
  assert.doesNotMatch(src, /webappUrl\('trainer-profile'\)\s*;/);
});

it('профиль тренера подсказывает, что не хватает телефона', () => {
  assert.match(account, /label: 'Телефона'[\s\S]*ROUTES\.contacts/);
});
