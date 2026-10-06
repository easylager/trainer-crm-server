/**
 * TASK-196 AC-2: тренер из RU-города показывает цены в RUB (₽).
 *
 * Валюта приходит с ценой (currency_code на услуге и тире — как у сеансов льда),
 * а не зашита в клиент «BYN». Отображение — конвенция TASK-109 для цен тренера:
 * RUB знаком ₽, BYN буквами. Полезные нагрузки без валюты читаются как BYN —
 * это условие совместимости со старым кэшем.
 *
 * Run: node --test tests/js/task-196-trainer-currency.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const STALE_PATH = path.resolve(__dirname, '../../static/webapp/schedule-staleness-model.js');

function loadIceTabModel() {
  delete require.cache[require.resolve(STALE_PATH)];
  require(STALE_PATH);
  const resolved = require.resolve(path.resolve(__dirname, '../../static/webapp/ice-tab-model.js'));
  delete require.cache[resolved];
  return require(resolved);
}

function loadArenaCardModel() {
  delete require.cache[require.resolve(STALE_PATH)];
  require(STALE_PATH);
  const resolved = require.resolve(path.resolve(__dirname, '../../static/webapp/arena-card-model.js'));
  delete require.cache[resolved];
  return require(resolved);
}

const SRC = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/catalog-main.js'), 'utf8');

function sliceBetween(src, startMarker, endMarker) {
  const start = src.indexOf(startMarker);
  assert.ok(start >= 0, 'marker not found: ' + startMarker);
  const end = src.indexOf(endMarker, start);
  assert.ok(end > start, 'end marker not found: ' + endMarker);
  return src.slice(start, end + endMarker.length);
}

/** Карточка тренера: модель вкладки «Лёд» (trainerCardView → formatTrainerPriceFrom). */
function trainerCard(item) {
  const { trainerCardView } = loadIceTabModel();
  return trainerCardView(item);
}

describe('вкладка «Лёд»: цена тренера из RU-города — в ₽', () => {
  it('trainerCardView рисует «от 40 ₽» по currency_code услуги', () => {
    const view = trainerCard({
      id: 1,
      profile: { first_name: 'Алексей', last_name: 'Агуреев' },
      primary_arena_name: 'Арена в Санкт-Петербурге',
      services: [{ service_name: 'Обучение катанию', price_byn_min: 40, currency_code: 'RUB' }],
    });
    assert.ok(view.meta.includes('от 40 ₽'), 'meta: ' + view.meta);
    assert.ok(!view.meta.includes('BYN'), 'валюта не захардкожена: ' + view.meta);
  });

  it('услуга без валюты читается как BYN (старые полезные нагрузки)', () => {
    const view = trainerCard({
      id: 2,
      profile: { first_name: 'Минск' },
      services: [{ service_name: 'Обучение катанию', price_byn_min: 25 }],
    });
    assert.ok(view.meta.includes('от 25 BYN'), 'meta: ' + view.meta);
  });
});

describe('карточка места: строка тренера — в валюте услуги', () => {
  it('trainerSubtitle подписывает минимальную цену ₽', () => {
    const { trainerSubtitle } = loadArenaCardModel();
    const line = trainerSubtitle({
      services: [
        { name: 'Хоккей', price_cents: 600000, currency_code: 'RUB' },
        { name: 'Фигурное', price_cents: 400000, currency_code: 'RUB' },
      ],
    });
    assert.ok(line.includes('от 4000 ₽'), 'subtitle: ' + line);
    assert.ok(!line.includes('BYN'), 'валюта не захардкожена: ' + line);
  });

  it('услуги без валюты читаются как BYN', () => {
    const { trainerSubtitle } = loadArenaCardModel();
    const line = trainerSubtitle({ services: [{ name: 'Хоккей', price_cents: 150000 }] });
    assert.ok(line.includes('от 1500 BYN'), 'subtitle: ' + line);
  });
});

describe('каталог: цена услуги — в валюте услуги', () => {
  function loadCatalogFormatters() {
    const escapeFn = sliceBetween(SRC, 'function escapeHtml(s) {', '\n      }');
    const labelFn = sliceBetween(SRC, 'function priceCurrencyLabel(code) {', '\n      }');
    const priceFn = sliceBetween(SRC, 'function formatCatalogServicePrice(s) {', '\n      }');
    const code =
      escapeFn +
      '\n' +
      labelFn +
      '\n' +
      priceFn +
      '\nmodule.exports = { formatCatalogServicePrice: formatCatalogServicePrice, priceCurrencyLabel: priceCurrencyLabel };';
    const ctx = { module: { exports: {} } };
    vm.createContext(ctx);
    vm.runInContext(code, ctx);
    return ctx.module.exports;
  }

  it('formatCatalogServicePrice подписывает цену ₽ для RUB', () => {
    const { formatCatalogServicePrice, priceCurrencyLabel } = loadCatalogFormatters();
    assert.equal(
      formatCatalogServicePrice({ price_byn_min: 40, price_byn_max: 60, currency_code: 'RUB' }),
      'от 40 ₽'
    );
    assert.equal(
      formatCatalogServicePrice({ price_byn: 40, currency_code: 'RUB' }),
      '40 ₽'
    );
    assert.equal(
      formatCatalogServicePrice({ price_byn: 40 }),
      '40 BYN'
    );
    // Тир в диалоге записи (tier radio): ₽ для RUB, BYN для старых нагрузок.
    assert.equal(priceCurrencyLabel('RUB'), '₽');
    assert.equal(priceCurrencyLabel(undefined), 'BYN');
    assert.equal(priceCurrencyLabel('BYN'), 'BYN');
  });
});

describe('центр (коллектив): тарифы — в валюте владельца', () => {
  function loadCenterFormatters() {
    const labelFn = sliceBetween(SRC, 'function priceCurrencyLabel(code) {', '\n      }');
    const curFn = sliceBetween(SRC, 'function centerTariffCurrency(tariffs) {', '\n      }');
    const breakdownFn = sliceBetween(SRC, 'function buildCenterPriceBreakdown(mode, guestCount, tariffs) {', '\n      }');
    const priceFn = sliceBetween(SRC, 'function formatCenterPriceByn(cents) {', '\n      }');
    const code =
      labelFn +
      '\n' +
      curFn +
      '\n' +
      breakdownFn +
      '\n' +
      priceFn +
      '\nvar state = { centerSessions: { tariffs: { currency_code: "RUB" } } };' +
      '\nmodule.exports = { centerTariffCurrency: centerTariffCurrency, buildCenterPriceBreakdown: buildCenterPriceBreakdown, formatCenterPriceByn: formatCenterPriceByn };';
    const ctx = { module: { exports: {} } };
    vm.createContext(ctx);
    vm.runInContext(code, ctx);
    return ctx.module.exports;
  }

  it('цена дорожки и доплаты за гостя — ₽ из tariffs', () => {
    const fns = loadCenterFormatters();
    const rubTariffs = { currency_code: 'RUB', guest_surcharge_cents: 1500 };
    assert.equal(fns.buildCenterPriceBreakdown('lane_with_guest', 2, rubTariffs), 'Дорожка + 2 гостя × 15 ₽');
    assert.equal(fns.formatCenterPriceByn(400000), '4000 ₽');
    assert.equal(fns.centerTariffCurrency(rubTariffs), '₽');
  });

  it('tariffs без валюты читаются как BYN', () => {
    const fns = loadCenterFormatters();
    assert.equal(fns.centerTariffCurrency({}), 'BYN');
    assert.equal(fns.centerTariffCurrency(null), 'BYN');
  });
});
