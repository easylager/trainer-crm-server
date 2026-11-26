/**
 * TASK-389: модель замера «нажатие на вкладку → содержимое показано».
 * Run: node --test tests/js/tab-timing-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const M = require('../../static/webapp/tab-timing-model.js');

const NOW = 1_800_000_000_000;

function input(over) {
  return Object.assign(
    { tapRaw: null, firstPage: false, nowMs: NOW, sinceOriginMs: 380.6, tab: 'kk', nav: 'navigate', platform: 'android', seasonUi: true },
    over || {}
  );
}

describe('encodeTap / decodeTap', () => {
  it('кладёт и читает вкладку откуда/куда и момент нажатия', () => {
    const raw = M.encodeTap('home', 'kk', NOW - 400);
    assert.equal(raw, 'home|kk|' + (NOW - 400));
    assert.deepEqual(M.decodeTap(raw, NOW), { from: 'home', to: 'kk', at: NOW - 400 });
  });

  it('вкладка «откуда» может быть пустой (нажали со страницы вне вкладок)', () => {
    const raw = M.encodeTap(null, 'me', NOW);
    assert.equal(raw, '|me|' + NOW);
    assert.equal(M.decodeTap(raw, NOW + 5).from, null);
  });

  it('чужая вкладка или мусор — метки нет', () => {
    assert.equal(M.encodeTap('home', 'admin', NOW), '');
    assert.equal(M.decodeTap('', NOW), null);
    assert.equal(M.decodeTap(null, NOW), null);
    assert.equal(M.decodeTap('home|kk', NOW), null);
    assert.equal(M.decodeTap('home|kk|abc', NOW), null);
    assert.equal(M.decodeTap('home|nope|' + NOW, NOW), null);
  });

  it('протухшая метка и метка из будущего (скачок часов) отбрасываются', () => {
    assert.equal(M.decodeTap('home|kk|' + (NOW - M.MAX_TAP_AGE_MS - 1), NOW), null);
    assert.notEqual(M.decodeTap('home|kk|' + (NOW - M.MAX_TAP_AGE_MS), NOW), null);
    assert.equal(M.decodeTap('home|kk|' + (NOW + 1), NOW), null);
  });
});

describe('buildEvent: переход по вкладке', () => {
  it('мс — от нажатия до показа, page_ms — от начала новой страницы', () => {
    const ev = M.buildEvent(input({ tapRaw: M.encodeTap('home', 'kk', NOW - 412) }));
    assert.deepEqual(ev, {
      kind: 'tab',
      from: 'home',
      to: 'kk',
      ms: 412,
      page_ms: 381,
      nav: 'navigate',
      platform: 'android',
      season_ui: true,
    });
  });

  it('метка на другую вкладку (редирект, подмена) — не событие', () => {
    assert.equal(M.buildEvent(input({ tab: 'me', tapRaw: M.encodeTap('home', 'kk', NOW - 100) })), null);
  });

  it('перезагрузка и «назад» с меткой — не событие', () => {
    assert.equal(M.buildEvent(input({ nav: 'reload', tapRaw: M.encodeTap('home', 'kk', NOW - 100) })), null);
    assert.equal(M.buildEvent(input({ nav: 'back_forward', tapRaw: M.encodeTap('home', 'kk', NOW - 100) })), null);
  });

  it('TASK-391: переход внутри оболочки вкладок — событие tab с nav=shell; без нажатия — нет', () => {
    const ev = M.buildEvent(input({ nav: 'shell', tab: 'me', sinceOriginMs: 9000, tapRaw: M.encodeTap('bookings', 'me', NOW - 12) }));
    assert.equal(ev.kind, 'tab');
    assert.equal(ev.nav, 'shell');
    assert.equal(ev.ms, 12);
    assert.equal(ev.from, 'bookings');
    assert.equal(M.buildEvent(input({ nav: 'shell', tab: 'me', firstPage: true })), null);
  });

  it('метка нажатия сильнее холодного старта: первая страница после нажатия — переход', () => {
    const ev = M.buildEvent(input({ firstPage: true, tapRaw: M.encodeTap('home', 'kk', NOW - 90) }));
    assert.equal(ev.kind, 'tab');
  });
});

describe('buildEvent: холодный старт', () => {
  it('первая страница сессии без нажатия: мс от timeOrigin', () => {
    const ev = M.buildEvent(input({ firstPage: true, tab: 'home', sinceOriginMs: 2240.4 }));
    assert.equal(ev.kind, 'cold');
    assert.equal(ev.from, null);
    assert.equal(ev.to, 'home');
    assert.equal(ev.ms, 2240);
    assert.equal(ev.page_ms, 2240);
  });

  it('не первая страница и нет нажатия — не событие (переход по ссылке, возврат)', () => {
    assert.equal(M.buildEvent(input({ firstPage: false })), null);
  });

  it('перезагрузка первой страницы — не холодный старт', () => {
    assert.equal(M.buildEvent(input({ firstPage: true, nav: 'reload' })), null);
  });
});

describe('buildEvent: защита данных', () => {
  it('страница вне вкладок — не событие', () => {
    assert.equal(M.buildEvent(input({ tab: null, firstPage: true })), null);
    assert.equal(M.buildEvent(input({ tab: 'arena', firstPage: true })), null);
  });

  it('мс ограничены сверху, мусорное время — не событие', () => {
    assert.equal(M.buildEvent(input({ firstPage: true, sinceOriginMs: 9e9 })).ms, 120000);
    assert.equal(M.buildEvent(input({ firstPage: true, sinceOriginMs: -5 })), null);
    assert.equal(M.buildEvent(input({ firstPage: true, sinceOriginMs: NaN })), null);
  });

  it('платформа — короткий слаг, иначе unknown; флаг строго булев', () => {
    assert.equal(M.buildEvent(input({ firstPage: true, platform: 'iOS' })).platform, 'ios');
    assert.equal(M.buildEvent(input({ firstPage: true, platform: 'ev il<script>' })).platform, 'unknown');
    assert.equal(M.buildEvent(input({ firstPage: true, platform: undefined })).platform, 'unknown');
    assert.equal(M.buildEvent(input({ firstPage: true, seasonUi: 'yes' })).season_ui, false);
  });

  it('в событии только перечисленные поля, без персональных данных', () => {
    const ev = M.buildEvent(input({ firstPage: true, userId: 7100000003, initData: 'secret' }));
    assert.deepEqual(Object.keys(ev).sort(), ['from', 'kind', 'ms', 'nav', 'page_ms', 'platform', 'season_ui', 'to']);
  });
});

describe('buildEvent: src и data_ms (TASK-448)', () => {
  it('src cache/net и data_ms проходят в событие, когда переданы', () => {
    const ev = M.buildEvent(input({ firstPage: true, src: 'cache', dataMs: 240 }));
    assert.equal(ev.src, 'cache');
    assert.equal(ev.data_ms, 240);
    const ev2 = M.buildEvent(input({ firstPage: true, src: 'net', dataMs: 1180 }));
    assert.equal(ev2.src, 'net');
    assert.equal(ev2.data_ms, 1180);
  });
  it('без src/data_ms полей нет; мусорный src не проходит', () => {
    const ev = M.buildEvent(input({ firstPage: true }));
    assert.equal('src' in ev, false);
    assert.equal('data_ms' in ev, false);
    const ev2 = M.buildEvent(input({ firstPage: true, src: 'wifi', dataMs: -3 }));
    assert.equal('src' in ev2, false);
    assert.equal('data_ms' in ev2, false);
  });
  it('data_ms ограничен сверху и округлён', () => {
    const ev = M.buildEvent(input({ firstPage: true, src: 'cache', dataMs: 240.6 }));
    assert.equal(ev.data_ms, 241);
    const ev2 = M.buildEvent(input({ firstPage: true, src: 'net', dataMs: 9e9 }));
    assert.equal(ev2.data_ms, 120000);
  });
});
