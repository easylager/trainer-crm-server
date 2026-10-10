/**
 * Заявка на абонемент или сертификат с карточки тренера (client-buy-pass).
 * Сервер: trainer_id в теле POST — тренер карточки, не основной из меню.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ClientBuyPassOrder = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  var MIN_NOMINAL_BYN = 1;
  var MAX_NOMINAL_BYN = 500000;

  function validateCertOrder(fields) {
    var email = String((fields && fields.email) || '').trim();
    var name = String((fields && fields.recipientName) || '').trim();
    if (!EMAIL_RE.test(email)) {
      return {
        ok: false,
        field: 'email',
        message: 'Укажите корректный email — на него тренер отправит PDF.',
      };
    }
    if (name.length > 200) {
      return {
        ok: false,
        field: 'name',
        message: 'Имя получателя слишком длинное.',
      };
    }
    var nominalByn = null;
    if (fields && fields.anyAmount) {
      var raw = String(fields.amountRaw || '').trim().replace(',', '.');
      var n = Number(raw);
      if (!raw || !isFinite(n) || n < MIN_NOMINAL_BYN) {
        return {
          ok: false,
          field: 'amount',
          message: 'Укажите сумму не меньше 1 BYN.',
        };
      }
      if (n > MAX_NOMINAL_BYN) {
        return {
          ok: false,
          field: 'amount',
          message: 'Слишком большая сумма. Укажите разумный номинал.',
        };
      }
      nominalByn = n;
    }
    return { ok: true, email: email, recipientName: name, nominalByn: nominalByn };
  }

  function passRequestBody(trainerId, productId) {
    return {
      pass_product_id: Number(productId),
      trainer_id: Number(trainerId),
    };
  }

  function certRequestBody(trainerId, productId, email, recipientName, nominalByn) {
    var body = {
      certificate_product_id: Number(productId),
      trainer_id: Number(trainerId),
      recipient_email: email,
      recipient_name: recipientName || '',
    };
    if (nominalByn != null) body.nominal_byn = nominalByn;
    return body;
  }

  function classifyOrderFailure(status, data) {
    if (status === 401 || status === 403) {
      return {
        message: 'Откройте страницу из бота, чтобы отправить заявку.',
        lockCard: false,
      };
    }
    var detail = data && data.detail;
    var message = '';
    if (typeof detail === 'string' && detail.trim()) {
      message = detail.trim();
    } else if (Array.isArray(detail) && detail.length && detail[0] && detail[0].msg) {
      message = String(detail[0].msg);
    } else {
      message = 'Не удалось отправить заявку. Попробуйте ещё раз.';
    }
    return {
      message: message,
      lockCard: status === 409 || status === 429,
    };
  }

  return {
    validateCertOrder: validateCertOrder,
    passRequestBody: passRequestBody,
    certRequestBody: certRequestBody,
    classifyOrderFailure: classifyOrderFailure,
  };
});
