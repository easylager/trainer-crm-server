/**
 * Живая открытка: тексты превью и куда отскакивает «Нет».
 * Run: node --test tests/js/zovi-live.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

globalThis.ZoviModel = require('../../static/shared/zovi-model.js');
const live = require('../../static/shared/zovi-live.js');

describe('тексты живой открытки', () => {
  it('имя адресата и отправителя', () => {
    const m = live.model({ toName: 'Лера', fromName: 'Макс', kind: 'public_skate' });
    assert.equal(m.name, 'Лера');
    assert.equal(m.ask, ', пойдёшь со мной на каток?');
    assert.equal(m.kicker, 'Приглашение на лёд от');
    assert.equal(m.from, 'Макса');
    assert.equal(m.caption, 'Так увидит Лера. Попробуй нажать «Нет».');
  });

  it('без адресата — для компании; ОХМ — на хоккей', () => {
    const m = live.model({ toName: ' ', fromName: '', kind: 'hockey_practice' });
    assert.equal(m.name, '');
    assert.equal(m.ask, 'Пойдёшь со мной на хоккей?');
    assert.equal(m.kicker, 'Приглашение на лёд');
    assert.equal(m.caption, 'Так увидят в чате. Попробуй нажать «Нет».');
  });

  it('разметка экранирует имена', () => {
    const html = live.html({ toName: '<b>', fromName: 'Макс', time: '20:00', day: 'Пн, 12 окт', place: 'Чижовка' });
    assert.equal(html.includes('<b>,'), false);
    assert.match(html, /&lt;b&gt;/);
    assert.match(html, /data-zl-no/);
  });
});

describe('куда отскакивает «Нет»', () => {
  const rink = { w: 320, h: 92 };
  const btn = { w: 80, h: 42 };
  const yes = { x: 38, y: 25, w: 64, h: 42 };

  function seq(values) {
    let i = 0;
    return () => values[i++ % values.length];
  }

  it('внутри катка и не на «Да»', () => {
    for (let k = 0; k < 50; k += 1) {
      const spot = live.pickSpot(rink, btn, yes, { x: 200, y: 46 });
      assert.ok(spot.x >= 0 && spot.x <= rink.w - btn.w);
      assert.ok(spot.y >= 0 && spot.y <= rink.h - btn.h);
      const overlaps = spot.x < yes.x + yes.w + 8 && spot.x + btn.w > yes.x - 8;
      assert.equal(overlaps && spot.y < yes.y + yes.h + 6 && spot.y + btn.h > yes.y - 6, false);
    }
  });

  it('подальше от пальца', () => {
    const spot = live.pickSpot(rink, btn, yes, { x: 300, y: 46 }, seq([0.5, 0.5, 0.95, 0.1, 0.0, 0.9]));
    assert.ok(spot.x + btn.w / 2 < 300 - 60);
  });

  it('подписи «Нет» по шагам и не выходят за список', () => {
    assert.equal(live.nextLabel(0), 'Нет');
    assert.equal(live.nextLabel(1), 'Не-а');
    assert.equal(live.nextLabel(99), 'Нет');
  });
});
