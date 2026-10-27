'use strict';
// Поле телефона на тренерских экранах: страна по умолчанию — по валюте тренера, а не всегда +375.
const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');

function fakeWrap(defaultCountry) {
  const attrs = { 'data-default-country': defaultCountry, 'data-crm-phone-field': '' };
  const dial = { textContent: '' };
  const flag = { textContent: '' };
  const input = { value: 'x', placeholder: '', dataset: {}, setAttribute() {}, addEventListener() {} };
  const btn = { dataset: {}, setAttribute() {}, addEventListener() {} };
  return {
    dataset: {},
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    setAttribute: (k, v) => { attrs[k] = v; },
    querySelector: (sel) =>
      sel === '.crm-phone-country-dial' ? dial : sel === '.crm-phone-country-flag' ? flag : sel === '.crm-phone-national-input' ? input : sel === '.crm-phone-country-btn' ? btn : null,
    querySelectorAll: () => [],
    addEventListener() {},
    closest() { return this; },
    _dial: dial,
    _input: input,
  };
}

function load(currency) {
  delete require.cache[require.resolve('../../static/webapp/mini-app-phone-field.js')];
  global.window = { document: {}, TRAINER_CURRENCY: currency };
  require('../../static/webapp/mini-app-phone-field.js');
  return global.window.CrmPhoneField;
}

describe('CrmPhoneField: страна по умолчанию', () => {
  beforeEach(() => { delete global.window; });

  it('тренер из РФ (RUB): поле открывается с +7', () => {
    const P = load('RUB');
    const w = fakeWrap('trainer');
    P.init(w);
    assert.equal(w._dial.textContent, '+7');
  });

  it('тренер из Беларуси: +375', () => {
    const P = load('BYN');
    const w = fakeWrap('trainer');
    P.init(w);
    assert.equal(w._dial.textContent, '+375');
  });

  it('сброс поля (пустой номер) возвращает страну по умолчанию, а не всегда BY', () => {
    const P = load('RUB');
    const w = fakeWrap('trainer');
    P.init(w);
    P.setE164(w, '+375291234567');
    assert.equal(w._dial.textContent, '+375');
    P.setE164(w, '');
    assert.equal(w._dial.textContent, '+7');
    assert.equal(w._input.value, '');
  });

  it('клиентские экраны (BY в разметке) от валюты не зависят', () => {
    const P = load('RUB');
    const w = fakeWrap('BY');
    P.init(w);
    assert.equal(w._dial.textContent, '+375');
  });
});
