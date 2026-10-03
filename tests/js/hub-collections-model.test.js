/**
 * TASK-148 (AC-3) → TASK-149: рынок в хабе — пресеты-данные, плитки «Куда катимся»,
 * приветствие из фактов.
 *   - пресет/плитка рендерится только при счётчике > 0;
 *   - секция «Куда катимся» — при >= 1 плитке (прежнее правило «>= 2 подборок» снято
 *     вместе с секцией «Подборки»: сетка не обязана быть 2×2);
 *   - «Сегодня вечером» первым среди пресетов, дальше — по счётчику;
 *   - счётчики — только из существующих публичных данных (фасеты, window.hits, total тренеров);
 *   - плитки «Сервис», «Бесплатно», «Заточка» не существуют;
 *   - приветствие: время суток по часу, имя, подпись только из фактов (город, N катков вечером).
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

/** Минск с данными: 5 крытых, 3 открытых (с живыми сеансами), 2 магазина, вечер — 4 катка, 14 тренеров. */
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
      trainersTotal: 14,
    },
    overrides || {}
  );
}

describe('buildPods: пресет только при счётчике > 0', () => {
  it('рендерит пресет только для ненулевых счётчиков', () => {
    const { buildPods } = loadModel();
    const pods = buildPods(richData({ facets: [{ key: 'ice', count: 5 }, { key: 'shop', count: 0 }] }), 7);
    const keys = pods.map((p) => p.key);
    assert.ok(keys.includes('ice'));
    assert.ok(!keys.includes('shop'), 'пресет с нулевым счётчиком не рендерится');
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

  it('нет фасетов и окна — пресетов нет вообще', () => {
    const { buildPods } = loadModel();
    assert.deepEqual(buildPods({}, 7), []);
  });
});

describe('tilesVisible: секция «Куда катимся» при >= 1 плитке (было: >= 2 подборок)', () => {
  it('отсутствует, когда плиток нет: пустой рынок', () => {
    const { buildTiles, tilesVisible } = loadModel();
    assert.equal(tilesVisible(buildTiles({}, 7)), false);
    assert.equal(tilesVisible([]), false);
    assert.equal(tilesVisible(null), false);
    // Фасеты есть, но все нули и тренеров нет.
    assert.equal(
      tilesVisible(
        buildTiles(
          { facets: [{ key: 'ice', count: 0 }, { key: 'shop', count: 0 }], eveningHits: 0, trainersTotal: 0 },
          7
        )
      ),
      false
    );
  });

  it('рендерится уже при одной плитке (один каток — секция есть)', () => {
    const { buildTiles, tilesVisible } = loadModel();
    const one = buildTiles({ facets: [{ key: 'ice', count: 1 }], eveningHits: null }, 7);
    assert.equal(one.length, 1);
    assert.equal(tilesVisible(one), true);
  });

  it('рендерится при нескольких плитках', () => {
    const { buildTiles, tilesVisible } = loadModel();
    assert.equal(tilesVisible(buildTiles(richData(), 7)), true);
  });
});

describe('порядок пресетов: вечер первым, дальше по счётчику', () => {
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
  it('строит ссылки ?city_id + ?venue по типу; вечер — с ?when=today_evening', () => {
    const { podHref } = loadModel();
    assert.equal(podHref('ice', 7), 'ice?city_id=7&venue=ice');
    assert.equal(podHref('outdoor', 7), 'ice?city_id=7&venue=outdoor');
    assert.equal(podHref('shop', 7), 'ice?city_id=7&venue=shop');
    // Было: 'ice?city_id=7' (окно в URL «Поиск» не принимал). Стало: окно передаётся явно.
    assert.equal(podHref('today_evening', 7), 'ice?city_id=7&when=today_evening');
  });
});

describe('buildTiles: Катки / Тренеры / Магазины, каждая только при честном счётчике', () => {
  it('на богатых данных — три плитки в порядке лёд → тренеры → магазины', () => {
    const { buildTiles } = loadModel();
    const tiles = buildTiles(richData(), 7);
    assert.deepEqual(tiles.map((t) => t.key), ['rinks', 'trainers', 'shops']);
  });

  it('«Катки» = крытые + открытые с живым сеансом; подпись и ссылка — вечернее окно', () => {
    const { buildTiles } = loadModel();
    const rinks = buildTiles(richData(), 7)[0];
    assert.equal(rinks.count, 8);
    assert.equal(rinks.title, 'Катки');
    assert.equal(rinks.sub, '4 катка вечером');
    assert.equal(rinks.href, 'ice?city_id=7&when=today_evening');
  });

  it('«Катки» без вечернего окна: честная подпись по составу, ссылка без when', () => {
    const { buildTiles } = loadModel();
    const both = buildTiles(richData({ eveningHits: 0 }), 7)[0];
    assert.equal(both.sub, 'крытые и открытые');
    assert.equal(both.href, 'ice?city_id=7');
    const onlyIce = buildTiles(
      richData({ eveningHits: null, facets: [{ key: 'ice', count: 5 }] }),
      7
    )[0];
    assert.equal(onlyIce.count, 5);
    assert.equal(onlyIce.sub, 'крытые');
  });

  it('летом открытые без живых сеансов не входят в счётчик «Катков»', () => {
    const { buildTiles } = loadModel();
    const rinks = buildTiles(richData({ outdoorLive: false }), 7)[0];
    assert.equal(rinks.count, 5);
  });

  it('«Тренеры» — total публичного списка; ссылка в «Поиск» с intent=coach', () => {
    const { buildTiles } = loadModel();
    const trainers = buildTiles(richData(), 7).find((t) => t.key === 'trainers');
    assert.equal(trainers.count, 14);
    assert.equal(trainers.href, 'ice?city_id=7&intent=coach');
  });

  it('плитка скрыта при счётчике 0 / null / мусоре', () => {
    const { buildTiles } = loadModel();
    for (const total of [0, null, undefined, 'x', -3]) {
      const keys = buildTiles(richData({ trainersTotal: total }), 7).map((t) => t.key);
      assert.ok(!keys.includes('trainers'), `trainersTotal=${total} → плитки тренеров нет`);
    }
    const noShop = buildTiles(richData({ facets: [{ key: 'ice', count: 5 }, { key: 'shop', count: 0 }] }), 7);
    assert.ok(!noShop.map((t) => t.key).includes('shops'));
    const noRinks = buildTiles(richData({ facets: [{ key: 'shop', count: 2 }], eveningHits: 0 }), 7);
    assert.ok(!noRinks.map((t) => t.key).includes('rinks'));
  });

  it('«Магазины» ведут в ice?venue=shop', () => {
    const { buildTiles } = loadModel();
    const shops = buildTiles(richData(), 7).find((t) => t.key === 'shops');
    assert.equal(shops.count, 2);
    assert.equal(shops.href, 'ice?city_id=7&venue=shop');
  });

  it('никакого «Сервиса», «Бесплатно», «Заточки», «Школ» ни в данных, ни в разметке', () => {
    const { buildTiles, renderTilesHtml } = loadModel();
    const tiles = buildTiles(richData(), 7);
    const dump = JSON.stringify(tiles) + renderTilesHtml(tiles);
    for (const banned of ['Сервис', 'Бесплатно', 'Заточка', 'заточка', 'sharpening', 'Школ', 'Каток недели']) {
      assert.ok(!dump.includes(banned), `запрещённое «${banned}» просочилось в плитки`);
    }
  });

  it('при нечётном числе плиток первая — на всю ширину; при чётном — сетка 2×N', () => {
    const { buildTiles } = loadModel();
    const three = buildTiles(richData(), 7);
    assert.equal(three.length, 3);
    assert.equal(three[0].wide, true);
    assert.ok(!three[1].wide && !three[2].wide);
    const two = buildTiles(richData({ facets: [{ key: 'ice', count: 5 }] }), 7);
    assert.equal(two.length, 2);
    assert.ok(!two[0].wide);
    const one = buildTiles({ facets: [{ key: 'shop', count: 2 }] }, 7);
    assert.equal(one.length, 1);
    assert.equal(one[0].wide, true);
  });

  it('нет ни одной плитки без данных', () => {
    const { buildTiles } = loadModel();
    assert.deepEqual(buildTiles(undefined, 7), []);
    assert.deepEqual(buildTiles({ facets: [] }, 7), []);
  });
});

describe('renderTilesHtml', () => {
  it('рисует плитку с иконкой типа на плашке, названием, счётчиком, подписью и ссылкой', () => {
    const { buildTiles, renderTilesHtml } = loadModel();
    const html = renderTilesHtml(buildTiles(richData({ eveningHits: null }), 7));
    assert.ok(html.includes('Катки'));
    assert.ok(html.includes('hub-cg__cnt">8<'));
    assert.ok(html.includes('hub-cg__ic--ice'));
    assert.ok(html.includes('hub-cg__ic--trainer'));
    assert.ok(html.includes('hub-cg__ic--shop'));
    assert.ok(html.includes('<svg'));
    assert.ok(html.includes('крытые и открытые'));
    assert.ok(html.includes('href="ice?city_id=7&amp;venue=shop"'));
    assert.ok(html.includes('hub-cg__tile--wide'));
  });

  it('экранирует данные', () => {
    const { renderTilesHtml } = loadModel();
    const html = renderTilesHtml([
      { key: 'x', type: 'ice', title: '<b>', count: 1, sub: '"q"', href: 'ice?a=1&b=2' },
    ]);
    assert.ok(!html.includes('<b>'));
    assert.ok(html.includes('&lt;b&gt;'));
    assert.ok(html.includes('href="ice?a=1&amp;b=2"'));
  });

  it('пустой список — пустая разметка', () => {
    const { renderTilesHtml } = loadModel();
    assert.equal(renderTilesHtml([]), '');
  });
});

describe('приветствие (TASK-149 S1): время суток по часу устройства', () => {
  it('границы суток: 5–11 утро, 12–17 день, 18–22 вечер, 23–4 ночь', () => {
    const { dayPart } = loadModel();
    const expected = {
      0: 'night', 4: 'night', 5: 'morning', 11: 'morning', 12: 'day', 17: 'day',
      18: 'evening', 22: 'evening', 23: 'night',
    };
    for (const [hour, part] of Object.entries(expected)) {
      assert.equal(dayPart(Number(hour)), part, `час ${hour}`);
    }
  });

  it('мусорный час не ломает приветствие', () => {
    const { dayPart } = loadModel();
    assert.equal(dayPart(NaN), 'day');
    assert.equal(dayPart(undefined), 'day');
    assert.equal(dayPart(25), 'night'); // 25 mod 24 = 1
    assert.equal(dayPart(-1), 'night'); // -1 → 23
  });

  it('«Вечер, Максим» с именем', () => {
    const { greetingText } = loadModel();
    assert.equal(greetingText(19, 'Максим'), 'Вечер, Максим');
    assert.equal(greetingText(8, 'Анна'), 'Утро, Анна');
    assert.equal(greetingText(13, 'Анна'), 'День, Анна');
    assert.equal(greetingText(2, 'Анна'), 'Ночь, Анна');
  });

  it('без имени — без имени и без висящей запятой', () => {
    const { greetingText } = loadModel();
    for (const name of [null, undefined, '', '   ']) {
      const text = greetingText(19, name);
      assert.equal(text, 'Добрый вечер');
      assert.ok(!text.includes(','));
    }
  });
});

describe('подпись под приветствием: только факты, без погоды', () => {
  it('город + «N катков вечером»', () => {
    const { greetingSub } = loadModel();
    assert.equal(greetingSub({ cityName: 'Минск', eveningHits: 4 }), 'Минск · 4 катка вечером');
    assert.equal(greetingSub({ cityName: 'Минск', eveningHits: 1 }), 'Минск · 1 каток вечером');
    assert.equal(greetingSub({ cityName: 'Минск', eveningHits: 11 }), 'Минск · 11 катков вечером');
  });

  it('нет вечерних катков — только город, не «0 катков»', () => {
    const { greetingSub } = loadModel();
    for (const hits of [0, null, undefined, 'x', -1]) {
      assert.equal(greetingSub({ cityName: 'Минск', eveningHits: hits }), 'Минск');
    }
  });

  it('страновой фолбэк — это не город клиента, подписи нет; число без города не показывается', () => {
    const { greetingSub } = loadModel();
    assert.equal(greetingSub({ cityName: 'Минск', isCountryFallback: true, eveningHits: 4 }), '');
    assert.equal(greetingSub({ cityName: '', eveningHits: 4 }), '');
    assert.equal(greetingSub({ cityName: null, eveningHits: 4 }), '');
    assert.equal(greetingSub(null), '');
    assert.equal(greetingSub(), '');
  });

  it('ни погоды, ни градусов, ни выдуманных фраз', () => {
    const { greetingSub, greetingText } = loadModel();
    const all = [];
    for (let h = 0; h < 24; h++) {
      all.push(greetingText(h, 'Максим'), greetingText(h, null));
    }
    all.push(greetingSub({ cityName: 'Минск', eveningHits: 4 }));
    const dump = all.join(' | ');
    assert.ok(!/°|градус|погод|лёд держит|идеальн|снег|мороз/i.test(dump), dump);
  });
});
