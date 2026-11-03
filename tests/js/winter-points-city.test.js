/** Mini App «Зимой»: список прошлого города не живёт после смены города; сбой загрузки виден и лечится. */
'use strict';
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const parent = {
  children: [],
  insertBefore(node) { this.children.push(node); node.parentNode = this; node.isConnected = true; },
  removeChild(node) { this.children = this.children.filter((n) => n !== node); node.isConnected = false; },
};
const list = { parentNode: parent };
const hostEl = () => parent.children.find((n) => n.id === 'iceWinter');

global.window = global;
global.document = {
  getElementById: (id) => (id === 'iceList' ? list : null),
  addEventListener() {},
  createElement: () => ({ querySelector() { return this._q || (this._q = { set innerHTML(v) { this.html = v; }, get innerHTML() { return this.html || ''; }, set textContent(v) {}, set hidden(v) {} }); }, appendChild() {}, addEventListener(type, fn) { if (type === 'click') this._click = fn; }, set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html || ''; } }),
  body: {},
};
global.GlideWinter = require(path.resolve(__dirname, '../../static/shared/winter-model.js'));
require(path.resolve(__dirname, '../../static/webapp/winter-points.js'));

const point = (id, name) => ({ id, name, kind: 'rink', state: 'waiting', own_page: true, photos: [], lat: 53.9, lon: 27.5, map_allowed: true, hours: {} });
const ctx = (cityId) => ({ season: 'winter', cityId, near: '', facet: { winter_points: 3 }, authHeaders: () => ({}) });
const tick = () => new Promise((r) => setImmediate(r));

describe('IceWinter: смена города', () => {
  it('пока грузится новый город, список прошлого не показывается; потом — список нового', async () => {
    const pending = {};
    global.fetch = (url) => new Promise((resolve) => { pending[/cities\/(\d+)/.exec(url)[1]] = resolve; });
    global.IceWinter.sync(ctx(1));
    pending[1]({ ok: true, json: async () => ({ items: [point(1, 'Минская точка')], total: 1, flooded: 0 }) });
    await tick(); await tick();
    assert.match(hostEl().innerHTML, /Минская точка/);

    global.IceWinter.sync(ctx(2));
    assert.doesNotMatch(hostEl().innerHTML, /Минская точка/);
    assert.match(hostEl().innerHTML, /Загружаем/);
    pending[2]({ ok: true, json: async () => ({ items: [point(2, 'Гродненская точка')], total: 1, flooded: 0 }) });
    await tick(); await tick();
    assert.match(hostEl().innerHTML, /Гродненская точка/);
    assert.doesNotMatch(hostEl().innerHTML, /Минская точка/);
  });

  it('уход из «Зимой» убирает блок, поздний ответ его не возвращает', async () => {
    let resolve;
    global.fetch = () => new Promise((r) => { resolve = r; });
    global.IceWinter.sync(ctx(3));
    global.IceWinter.sync({ ...ctx(3), season: '' });
    assert.equal(hostEl(), undefined);
    resolve({ ok: true, json: async () => ({ items: [point(5, 'Поздняя')], total: 1, flooded: 0 }) });
    await tick(); await tick();
    assert.equal(hostEl(), undefined);
  });

  it('сбой загрузки — сообщение и «Повторить», а не тишина', async () => {
    global.fetch = async () => ({ ok: false });
    global.IceWinter.sync(ctx(4));
    await tick(); await tick();
    assert.match(hostEl().innerHTML, /Не получилось загрузить/);
    assert.match(hostEl().innerHTML, /data-w-retry/);
  });

  it('чипы «Ближе ко мне» и «Район» на месте; карта хочет зимние точки только с координатами', async () => {
    global.fetch = async () => ({
      ok: true,
      json: async () => ({ items: [{ ...point(6, 'А'), district: 'Центр' }, { ...point(7, 'Б'), district: 'Центр' }], total: 2, flooded: 0 }),
    });
    global.IceWinter.sync(ctx(6));
    await tick(); await tick();
    assert.match(hostEl().innerHTML, /data-w-f="near"/);
    assert.match(hostEl().innerHTML, /data-w-f="district"/);
    assert.equal(global.IceWinter.mapWanted(), true);
  });

  it('заголовок с городом, один абзац, сегмент «Список | Карта», колокольчик после списка', async () => {
    global.fetch = async () => ({
      ok: true,
      json: async () => ({ items: [point(8, 'Точка')], total: 1, flooded: 0, where: 'Минске', bell_near_link: 'https://t.me/x' }),
    });
    const seen = [];
    global.IceWinter.sync({ ...ctx(8), setView: (v) => seen.push(v) });
    await tick(); await tick();
    const html = hostEl().innerHTML;
    assert.match(html, /<h2 class="w-title">Зимой в Минске<\/h2>/);
    assert.equal((html.match(/class="w-lead"/g) || []).length, 1);
    assert.ok(html.indexOf('data-w-view="list"') < html.indexOf('w-list'));
    assert.ok(html.indexOf('w-list') < html.indexOf('w-bell'), 'колокольчик ниже карточек');
    hostEl()._click({ target: { closest: (sel) => (sel === '[data-w-view]' ? { getAttribute: () => 'map' } : null) } });
    assert.deepEqual(seen, ['map']);
  });

  it('без названия города в ответе заголовок — просто «Зимой»', async () => {
    global.fetch = async () => ({ ok: true, json: async () => ({ items: [point(9, 'Т')], total: 1, flooded: 0 }) });
    global.IceWinter.sync(ctx(9));
    await tick(); await tick();
    assert.match(hostEl().innerHTML, /<h2 class="w-title">Зимой<\/h2>/);
  });

  it('карта: секция переходит на зимнюю и возвращается обратно', async () => {
    global.fetch = async () => ({ ok: true, json: async () => ({ items: [point(10, 'К')], total: 1, flooded: 0 }) });
    global.IceWinter.sync(ctx(10));
    await tick(); await tick();
    const classes = new Set();
    const sec = { classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c) }, appendChild() {} };
    global.IceMap = { loadYmapsDefault: () => new Promise(() => {}) };
    assert.equal(global.IceWinter.showMap(sec), true);
    assert.ok(classes.has('ice-map-wrap--winter'));
    global.IceWinter.hideMap();
    assert.ok(!classes.has('ice-map-wrap--winter'));
  });
});
