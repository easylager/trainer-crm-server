/**
 * TASK-148 (AC-3): секция «Подборки» в хабе — правила рендера по данным.
 *   - карточка рендерится только при счётчике > 0;
 *   - секция целиком — только при >= 2 живых карточках;
 *   - «Сегодня вечером» первым, дальше — по счётчику;
 *   - счётчики — только из существующих публичных данных (фасеты, window.hits).
 * Run: node --test tests/js/hub-collections-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/hub-collections-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

/** Минск с данными: 5 крытых, 3 открытых (с живыми сеансами), 2 магазина, вечер — 4 катка. */
function richData(overrides) {
  return Object.assign(
    {
      facets: [
        { key: 'ice', chip: 'Лёд', count: 5 },
        { key: 'outdoor', chip: 'Открытые', count: 3 },
        { key: 'shop', chip: 'Магазин', count: 2 },
      ],
      eveningHits: 4,
      outdoorLive: true,
    },
    overrides || {}
  );
}

describe('buildPods: карточка только при счётчике > 0', () => {
  it('рендерит карточку только для ненулевых счётчиков', () => {
    const { buildPods } = loadModel();
    const pods = buildPods(richData({ facets: [{ key: 'ice', count: 5 }, { key: 'shop', count: 0 }] }), 7);
    const keys = pods.map((p) => p.key);
    assert.ok(keys.includes('ice'));
    assert.ok(!keys.includes('shop'), 'карточка с нулевым счётчиком не рендерится');
  });

  it('«Открытые» без живых сеансов (лето) не рендерится, даже если фасет не пуст', () => {
    const { buildPods } = loadModel();
    const pods = buildPods(
      richData({ facets: [{ key: 'ice', count: 5 }, { key: 'outdoor', count: 3 }], outdoorLive: false }),
      7
    );
    const keys = pods.map((p) => p.key);
    assert.ok(!keys.includes('outdoor'));
  });

  it('«Бесплатно» и «Заточка» не рендерятся: публичных счётчиков для них нет', () => {
    const { buildPods } = loadModel();
    const pods = buildPods(richData(), 7);
    const keys = pods.map((p) => p.key);
    assert.ok(!keys.includes('free'));
    assert.ok(!keys.includes('sharpening'));
  });

  it('нет фасетов и окна — подборок нет вообще', () => {
    const { buildPods } = loadModel();
    assert.deepEqual(buildPods({}, 7), []);
  });
});

describe('sectionVisible: секция только при >= 2 живых карточках', () => {
  it('отсутствует при < 2 живых подборок', () => {
    const { buildPods, sectionVisible } = loadModel();
    // Один живой каток — секции нет.
    assert.equal(sectionVisible(buildPods(richData({ facets: [{ key: 'ice', count: 1 }], eveningHits: null }), 7)), false);
    // Вообще без данных — секции нет.
    assert.equal(sectionVisible(buildPods({}, 7)), false);
  });

  it('рендерится при >= 2 живых подборках', () => {
    const { buildPods, sectionVisible } = loadModel();
    assert.equal(sectionVisible(buildPods(richData({ facets: [{ key: 'ice', count: 1 }, { key: 'shop', count: 2 }], eveningHits: null }), 7)), true);
    assert.equal(sectionVisible(buildPods(richData(), 7)), true);
  });
});

describe('порядок карточек: вечер первым, дальше по счётчику', () => {
  it('«Сегодня вечером» первым, остальные по убыванию счётчика', () => {
    const { buildPods } = loadModel();
    const pods = buildPods(
      richData({
        facets: [
          { key: 'ice', count: 2 },
          { key: 'shop', count: 6 },
          { key: 'outdoor', count: 4 },
        ],
        eveningHits: 3,
        outdoorLive: true,
      }),
      7
    );
    assert.deepEqual(
      pods.map((p) => p.key),
      ['today_evening', 'shop', 'outdoor', 'ice']
    );
  });

  it('без вечернего окна — просто по счётчику', () => {
    const { buildPods } = loadModel();
    const pods = buildPods(
      richData({
        facets: [{ key: 'ice', count: 2 }, { key: 'shop', count: 6 }],
        eveningHits: null,
        outdoorLive: true,
      }),
      7
    );
    assert.deepEqual(pods.map((p) => p.key), ['shop', 'ice']);
  });
});

describe('ссылки в каталог по конвенциям диплинков', () => {
  it('строит ссылки ?city_id + ?venue по типу', () => {
    const { podHref } = loadModel();
    assert.equal(podHref('ice', 7), 'ice?city_id=7&venue=ice');
    assert.equal(podHref('outdoor', 7), 'ice?city_id=7&venue=outdoor');
    assert.equal(podHref('shop', 7), 'ice?city_id=7&venue=shop');
    assert.equal(podHref('today_evening', 7), 'ice?city_id=7');
  });
});

describe('renderPodsHtml', () => {
  it('рисует карточку с названием, счётчиком и ссылкой', () => {
    const { buildPods, renderPodsHtml } = loadModel();
    const pods = buildPods(richData({ facets: [{ key: 'ice', count: 5 }, { key: 'shop', count: 2 }], eveningHits: null }), 7);
    const html = renderPodsHtml(pods);
    assert.ok(html.includes('Крытые'));
    assert.ok(html.includes('5 катков'));
    assert.ok(html.includes('ice?city_id=7&amp;venue=ice'));
    assert.ok(html.includes('hub-pod__art--ice'));
  });

  it('пустой список — пустая разметка', () => {
    const { renderPodsHtml } = loadModel();
    assert.equal(renderPodsHtml([]), '');
  });
});
