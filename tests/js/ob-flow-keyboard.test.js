'use strict';
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const K = require('../../static/webapp/ob-flow-keyboard.js');

describe('ObFlowKeyboard.revealDelta', () => {
  // Видимая часть тела листа над клавиатурой: 100..400 (300px), отступ 12.
  it('поле целиком в видимой области — не двигаем', () => {
    assert.equal(K.revealDelta(150, 250, 100, 400), 0);
  });
  it('поле под клавиатурой — прокрутить вниз ровно настолько, чтобы низ стал виден', () => {
    assert.equal(K.revealDelta(380, 480, 100, 400), 480 - (400 - 12));
  });
  it('поле выше видимой области — прокрутить вверх', () => {
    assert.equal(K.revealDelta(60, 140, 100, 400), 60 - (100 + 12));
  });
  it('поле выше окна — прижимаем верх, а не низ', () => {
    assert.equal(K.revealDelta(300, 900, 100, 400), 300 - (100 + 12));
  });
  it('схлопнутая область (клавиатура на весь лист) не даёт безумных прокруток', () => {
    assert.equal(K.revealDelta(300, 400, 100, 110), 0);
  });
  it('мусор на входе даёт 0, а не NaN', () => {
    assert.equal(K.revealDelta(undefined, undefined, undefined, undefined), 0);
    assert.equal(K.worthScrolling(NaN), false);
  });
});

describe('ObFlowKeyboard.topAlignDelta и worthScrolling', () => {
  it('верх поля встаёт на отступ от верха области', () => {
    assert.equal(K.topAlignDelta(500, 100), 500 - (100 + K.MARGIN));
    assert.equal(K.topAlignDelta(100, 100, 0), 0);
  });
  it('доли пикселя не стоят прокрутки', () => {
    assert.equal(K.worthScrolling(0.4), false);
    assert.equal(K.worthScrolling(-1), true);
  });
});
