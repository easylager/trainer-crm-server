/**
 * TASK-415: адрес №37 «Снова к» и №35 «Все окна» с хаба.
 * Исполняются настоящие функции client-home-main.js, не сверка исходника.
 * Run: node --test tests/js/hub-rebook-address.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const homePath = path.resolve(__dirname, '../../static/webapp/client-home-main.js');

function fnBody(src, name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('нет ' + name);
  let depth = 0;
  for (let i = src.indexOf('{', start); i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) return src.slice(start, i + 1);
  }
  throw new Error('не закрыта ' + name);
}

function load(src) {
  const paths = [];
  const primaryCatalogServiceId = 3;
  const lastBookingTrainerId = null;
  const lastBookingServiceId = null;
  const api = new Function(
    'primaryCatalogServiceId',
    'lastBookingTrainerId',
    'lastBookingServiceId',
    'navigateTo',
    'stopHubCardControl',
    `${fnBody(src, 'catalogPrimaryServiceQuery')}
     ${fnBody(src, 'buildBookPathFromHubContext')}
     ${fnBody(src, 'hubRepeatBookServiceId')}
     ${fnBody(src, 'navigateToRebookTarget')}
     function runAllSlots(tid) {
       var action = 'all-slots';
       var ev = {};
       var btn = { getAttribute: function () { return tid; } };
       var hubMeCardTrainerId = tid;
       ${allSlotsBranch(src)}
     }
     return { navigateToRebookTarget, runAllSlots };`
  )(
    primaryCatalogServiceId,
    lastBookingTrainerId,
    lastBookingServiceId,
    (p) => paths.push(p),
    () => {}
  );
  return { paths, ...api };
}

function allSlotsBranch(src) {
  const from = src.indexOf("if (action === 'all-slots')");
  const to = src.indexOf("if (action === 'book-slot')");
  if (from < 0 || to < from) throw new Error('нет ветки all-slots');
  return src.slice(from, to);
}

function oneQuestion(url) {
  assert.equal((url.match(/\?/g) || []).length, 1, url);
  return new URL('https://x/' + url);
}

describe('хаб: №37 и №35', () => {
  const src = fs.readFileSync(homePath, 'utf8');

  it('«Снова к» — полный адрес с entry=rebook, услугой и from=hub', () => {
    const hub = load(src);
    hub.navigateToRebookTarget({
      trainer_id: 7,
      service_id: 3,
      arena_id: 9,
      trainer_display_name: 'Анна',
    });
    assert.equal(hub.paths.length, 1);
    const url = hub.paths[0];
    const u = oneQuestion(url);
    assert.equal(
      url,
      'catalog?trainer_id=7&action=book&from=hub&service_id=3&entry=rebook'
    );
    assert.equal(u.searchParams.get('entry'), 'rebook');
    assert.equal(u.searchParams.get('service_id'), '3');
    assert.equal(u.searchParams.get('from'), 'hub');
    assert.equal(u.searchParams.get('trainer_id'), '7');
    assert.equal(u.searchParams.get('action'), 'book');
  });

  it('«Все окна» — тот же сборщик без entry', () => {
    const hub = load(src);
    hub.runAllSlots('7');
    assert.equal(hub.paths.length, 1);
    const url = hub.paths[0];
    const u = oneQuestion(url);
    assert.equal(url, 'catalog?trainer_id=7&action=book&from=hub&service_id=3');
    assert.equal(u.searchParams.get('entry'), null);
    assert.equal(u.searchParams.get('service_id'), '3');
    assert.equal(u.searchParams.get('from'), 'hub');
  });
});
