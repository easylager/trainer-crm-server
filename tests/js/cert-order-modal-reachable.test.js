/**
 * Форма заказа сертификата должна оставаться управляемой с открытой клавиатурой.
 *
 * Run: node --test "tests/js/*.test.js"
 *
 * Модалка центрировалась (`align-items: center`) внутри `position: fixed; inset: 0` и не
 * объявляла ни одного `overflow`. Пока клавиатура закрыта, лист влезает и всё выглядит
 * правильно. Клавиатура открывается — видимая высота падает почти вдвое, лист выше неё, а
 * центрирование срезает его с обоих концов: «Отмена» и «Отправить тренеру» уезжают под
 * клавиатуру, и добраться до них нечем — прокручивать нечего.
 *
 * Замер на вьюпорте 500×360 (как при открытой клавиатуре на iPhone): до правки scrollTop
 * оставался 0, а низ кнопки был на 421px при экране 360 — недостижим.
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const page = fs.readFileSync(
  path.resolve(__dirname, '../../static/webapp/client-passes-certificates.html'),
  'utf8'
);

/** Тело CSS-правила по селектору — чтобы проверять объявления, а не случайные совпадения. */
function rule(selector) {
  // Селектор ищем от начала строки: иначе `.pass-order-modal-sheet` совпал бы внутри
  // `.pass-order-modal-root:not([hidden]) > .pass-order-modal-sheet`.
  const at = page.indexOf('\n    ' + selector + ' {');
  assert.notEqual(at, -1, `нет правила для ${selector}`);
  const open = page.indexOf('{', at);
  const close = page.indexOf('}', open);
  return page.slice(open + 1, close);
}

describe('модалка заказа сертификата переживает открытую клавиатуру', () => {
  const overlay = rule('.pass-order-modal-root:not([hidden])');

  it('оверлей прокручивается сам — иначе до кнопок не добраться', () => {
    assert.match(overlay, /overflow-y:\s*auto/);
  });

  it('лист прижат к верху, а не обрезан центрированием с обеих сторон', () => {
    assert.match(overlay, /align-items:\s*flex-start/);
    assert.doesNotMatch(overlay, /align-items:\s*center/);
  });

  it('высота считается от динамического вьюпорта, который сжимается под клавиатуру', () => {
    // position: fixed на iOS меряется от layout viewport — он под клавиатуру не сжимается.
    assert.match(overlay, /height:\s*100dvh/);
  });

  it('пока лист ниже экрана — остаётся по центру: margin auto, а не второй набор правил', () => {
    const sheet = rule('.pass-order-modal-root:not([hidden]) > .pass-order-modal-sheet');
    assert.match(sheet, /margin:\s*auto/);
  });

  it('лист не растягивается на всю высоту оверлея — иначе прокрутка бессмысленна', () => {
    assert.match(rule('.pass-order-modal-sheet'), /flex:\s*0 0 auto/);
  });

  it('жест прокрутки не уходит на страницу под оверлеем', () => {
    assert.match(overlay, /overscroll-behavior:\s*contain/);
  });

  it('правило то же, что у общей модалки приложения — один паттерн, не второй', () => {
    const shared = fs.readFileSync(
      path.resolve(__dirname, '../../static/webapp/mini-app-components.css'),
      'utf8'
    );
    const at = shared.indexOf('.modal-overlay {');
    const body = shared.slice(at, shared.indexOf('}', at));
    for (const decl of [/align-items:\s*flex-start/, /overflow-y:\s*auto/]) {
      assert.match(body, decl, 'общий .modal-overlay перестал быть образцом — сверьте оба места');
      assert.match(overlay, decl);
    }
  });
});
