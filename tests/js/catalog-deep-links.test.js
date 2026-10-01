/**
 * TASK-146: диплинки каталога — startapp → нужный экран мини-аппа.
 * Run: node --test tests/js/catalog-deep-links.test.js
 *
 * Шелл (mini-app-client-shell.js) не модуль и при загрузке сразу бутится, поэтому
 * чистую функцию разбора вынимаем из исходника и исполняем отдельно.
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

function loadDeepLinkTarget() {
  const src = fs.readFileSync(path.join(webapp, 'mini-app-client-shell.js'), 'utf8');
  const start = src.indexOf('function deepLinkTarget(sp) {');
  assert.ok(start >= 0, 'deepLinkTarget must exist in the shell');
  const end = src.indexOf('\n  }\n', start);
  // eslint-disable-next-line no-new-func
  return new Function(src.slice(start, end + 4) + '\nreturn deepLinkTarget;')();
}

function loadIceModel() {
  const p = path.join(webapp, 'ice-tab-model.js');
  delete require.cache[require.resolve(p)];
  return require(p);
}

describe('deepLinkTarget', () => {
  const target = loadDeepLinkTarget();

  it('arena_<id> ведёт на карточку места', () => {
    assert.deepEqual(target('arena_42'), { key: 'arena', path: 'arena?ref=42' });
  });

  it('catalog_<city> ведёт в каталог города', () => {
    assert.deepEqual(target('catalog_7'), { key: 'ice', path: 'ice?city_id=7' });
    assert.deepEqual(target('catalog_7_coach'), { key: 'ice', path: 'ice?city_id=7&intent=coach' });
  });

  it('магазин и зал — это фильтр по типу места, а не интент', () => {
    assert.equal(target('catalog_7_shop').path, 'ice?city_id=7&venue=shop');
    assert.equal(target('catalog_7_gym').path, 'ice?city_id=7&venue=gym');
  });

  it('чужие и кривые payload не трогаем', () => {
    assert.equal(target(''), null);
    assert.equal(target('cert_ABC'), null);
    assert.equal(target('catalog_0'), null);
    assert.equal(target('catalog_7_sauna'), null);
  });
});

describe('ice tab URL: город и тип места из ссылки', () => {
  it('city_id из ссылки', () => {
    const M = loadIceModel();
    assert.equal(M.cityIdFromSearch('?city_id=12&intent=coach'), 12);
    assert.equal(M.cityIdFromSearch('?city_id=abc'), null);
    assert.equal(M.cityIdFromSearch(''), null);
  });

  it('venue из ссылки — только известные типы', () => {
    const M = loadIceModel();
    assert.equal(M.venueFromSearch('?venue=shop'), 'shop');
    assert.equal(M.venueFromSearch('?venue=SHOP'), 'shop');
    assert.equal(M.venueFromSearch('?venue=casino'), null);
  });
});
