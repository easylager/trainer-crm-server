/**
 * Заявка с карточки тренера: валидация, тело запроса и модалка под клавиатурой.
 * Run: node --test tests/js/client-buy-pass-order.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/client-buy-pass-order.js');
const pagePath = path.resolve(__dirname, '../../static/webapp/client-buy-pass.html');

function loadModel() {
  delete require.cache[require.resolve(modelPath)];
  return require(modelPath);
}

function rule(page, selector) {
  const at = page.indexOf('\n    ' + selector + ' {');
  assert.notEqual(at, -1, `нет правила для ${selector}`);
  const open = page.indexOf('{', at);
  const close = page.indexOf('}', open);
  return page.slice(open + 1, close);
}

describe('заявка с карточки тренера', () => {
  const api = loadModel();

  it('абонемент уходит тренеру с карточки', () => {
    assert.deepEqual(api.passRequestBody(15, 9), {
      pass_product_id: 9,
      trainer_id: 15,
    });
  });

  it('сертификат с фиксированным номиналом не шлёт сумму', () => {
    assert.deepEqual(api.certRequestBody(4, 8, 'a@b.co', '', null), {
      certificate_product_id: 8,
      trainer_id: 4,
      recipient_email: 'a@b.co',
      recipient_name: '',
    });
  });

  it('сертификат «любая сумма» передаёт номинал', () => {
    const body = api.certRequestBody(4, 8, 'a@b.co', 'Соча', 50);
    assert.equal(body.nominal_byn, 50);
    assert.equal(body.recipient_name, 'Соча');
  });

  it('пустой и кривой email не уходят на сервер', () => {
    for (const email of ['', 'нет', 'a@b', 'a @b.co']) {
      const parsed = api.validateCertOrder({ email: email, recipientName: '', anyAmount: false });
      assert.equal(parsed.ok, false);
      assert.equal(parsed.field, 'email');
    }
  });

  it('запятая в сумме считается как десятичный разделитель', () => {
    const parsed = api.validateCertOrder({
      email: 'gift@example.com',
      recipientName: '',
      anyAmount: true,
      amountRaw: '50,5',
    });
    assert.equal(parsed.ok, true);
    assert.equal(parsed.nominalByn, 50.5);
  });

  it('сумма меньше 1 BYN и пустая сумма не проходят', () => {
    for (const raw of ['', '0', '0,5']) {
      const parsed = api.validateCertOrder({
        email: 'gift@example.com',
        anyAmount: true,
        amountRaw: raw,
      });
      assert.equal(parsed.ok, false);
      assert.equal(parsed.field, 'amount');
    }
  });

  it('повтор и лимит дня блокируют кнопку, прочие ошибки — нет', () => {
    assert.equal(api.classifyOrderFailure(409, { detail: 'Уже есть' }).lockCard, true);
    assert.equal(api.classifyOrderFailure(429, { detail: 'Сегодня уже' }).lockCard, true);
    const other = api.classifyOrderFailure(422, { detail: 'У тренера не заполнен город' });
    assert.equal(other.lockCard, false);
    assert.match(other.message, /город/);
  });

  it('без сессии бота просим открыть страницу из бота', () => {
    const auth = api.classifyOrderFailure(401, { detail: 'Что-то пошло не так' });
    assert.match(auth.message, /бота/);
    assert.equal(auth.lockCard, false);
  });
});

describe('страница карточки умеет отправить заявку', () => {
  const page = fs.readFileSync(pagePath, 'utf8');

  it('кнопка заказа и модалки есть в разметке', () => {
    assert.match(page, /client-buy-pass-order\.js/);
    assert.match(page, /data-order/);
    assert.match(page, /id="pass-orderConfirmModal"/);
    assert.match(page, /id="cert-orderModal"/);
    assert.match(page, /passRequestBody/);
    assert.match(page, /certRequestBody/);
  });

  it('модалка переживает открытую клавиатуру', () => {
    const overlay = rule(page, '.pass-order-modal-root:not([hidden])');
    assert.match(overlay, /overflow-y:\s*auto/);
    assert.match(overlay, /align-items:\s*flex-start/);
    assert.match(overlay, /height:\s*100dvh/);
    assert.match(overlay, /overscroll-behavior:\s*contain/);
    assert.match(rule(page, '.pass-order-modal-root:not([hidden]) > .pass-order-modal-sheet'), /margin:\s*auto/);
    assert.match(rule(page, '.pass-order-modal-sheet'), /flex:\s*0 0 auto/);
  });
});
