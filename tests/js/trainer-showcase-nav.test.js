/**
 * Этап 1 входов в витрину: навигация на самой витрине — панель вкладок продукта и «‹ Назад».
 * Стенд: настоящий trainer-showcase-main.js, history и ClientShell подменены (helpers/trainer-showcase-harness.js).
 * Run: node --test tests/js/trainer-showcase-nav.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');

const webapp = path.resolve(__dirname, '../../static/webapp');
const svc = { service_id: 1, service_name: 'С нуля', is_public: true, is_online: false, currency_code: 'BYN', price_cents: 5000,
  price_tiers: [{ id: 100, tier_kind: 'adult', price_cents: 5000, currency_code: 'BYN' }] };
const trainer = (id, extra = {}) => ({
  id, name: 'Тренер ' + id, first_name: 'Тренер' + id, can_book: true, services: [svc], arenas: [{ id: 3, name: 'Каток' }], windows: [], ...extra,
});
const slot = (id) => ({ id, slot_date: '2026-11-20', start_time: '10:00', end_time: '10:45', capacity: 1, spots_left: 1, arena_id: 3, is_online: false });
const isPath = (c, p) => c.url.split('?')[0] === p;
const PHONE = { client_phone: '+375291234567' };
const slotsRoute = { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101)] }) };
const backHtml = (h) => (/<button type="button" class="back" data-act="back">‹ ([^<]*)<\/button>/.exec(h.app.innerHTML) || [])[1] || null;
const lastTab = (h) => h.ctx.tabBar[h.ctx.tabBar.length - 1];

describe('панель вкладок на витрине', () => {
  it('trainers.html подключает оболочку клиента в режиме вкладок', () => {
    const html = fs.readFileSync(path.join(webapp, 'trainers.html'), 'utf8');
    assert.match(html, /<body class="tsw" data-client-shell="tabs">/);
    assert.match(html, /mini-app-client-shell\.css/);
    assert.match(html, /mini-app-client-shell\.js/);
  });

  it('«Поиск» подсвечен на витрине: trainers — раздел поиска', () => {
    const src = fs.readFileSync(path.join(webapp, 'mini-app-client-shell.js'), 'utf8');
    const body = src.slice(src.indexOf('function resolveActiveTab'), src.indexOf('function isMoreRoute'));
    assert.match(body, /key === 'trainers'/);
  });

  it('видна на витрине, тренере и «другом времени»; на записи и «отправлено» спрятана', async () => {
    const profiles = { items: [{ client_id: 10, role: 'self', first_name: 'Мама' }], default_profile_id: 10 };
    const h = boot({ profiles, showcase: { items: [trainer(1)] }, session: PHONE, routes: [
      slotsRoute,
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => resp(200, { success: true }) },
    ] });
    await tick();
    assert.equal(lastTab(h), true, 'витрина');
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    assert.equal(lastTab(h), true, 'тренер');
    h.click({ 'data-act': 'week' });
    assert.equal(h.S.view, 'week');
    assert.equal(lastTab(h), true, 'другое время');
    h.click({ 'data-act': 'back' });
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    await tick();
    assert.equal(h.S.view, 'book');
    assert.equal(lastTab(h), false, 'запись: панель не перекрывает форму и «Записаться»');
    h.click({ 'data-act': 'submit' });
    await tick();
    assert.equal(h.S.view, 'sent');
    assert.equal(lastTab(h), false, 'отправлено');
    h.click({ 'data-act': 'to-list' });
    assert.equal(lastTab(h), true, '«Другие тренеры» → снова витрина с панелью');
  });

  it('«заявка отправлена» — без панели', async () => {
    const h = boot({ showcase: { items: [trainer(5, { can_book: false })] }, session: { ...PHONE, city_id: 1 }, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/request'), reply: () => resp(200, { success: true, request_id: 1 }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 5 });
    await tick();
    h.click({ 'data-act': 'request' });
    h.sheetInput('rq-name', 'Анна');
    h.sheetClick({ 'data-act': 'rq-send' });
    await tick();
    assert.equal(h.S.view, 'reqsent');
    assert.equal(lastTab(h), false);
  });

  it('закреплённый низ встаёт над панелью, шторки — над ней', () => {
    const css = fs.readFileSync(path.join(webapp, 'trainer-showcase.css'), 'utf8');
    assert.match(css, /body\.tsw\.client-shell-body:not\(\.client-shell-tabs-hidden\) \.ft \{ bottom: var\(--client-shell-tab-inset\)/);
    assert.match(css, /\.dim \{[^}]*z-index: 9500/);
    assert.match(css, /body\.tsw\.client-shell-body\.client-shell-tabs-hidden \{ padding-bottom: env\(safe-area-inset-bottom, 12px\); \}/);
  });
});

describe('«‹ Назад» на корне витрины', () => {
  it('пришли с другого экрана — на списке своей кнопки нет, «Назад» (панель Telegram) уводит туда (history.back)', async () => {
    const h = boot({ historyLength: 3, showcase: { items: [trainer(1), trainer(2)] }, session: PHONE });
    await tick();
    assert.equal(backHtml(h), null);
    h.click({ 'data-act': 'back' });
    assert.equal(h.ctx.history.left, 1);
    assert.deepEqual([...h.ctx.navigated], []);
  });

  it('открыли витрину первой (история пуста) — кнопки «Назад» нет, выход — панелью', async () => {
    const h = boot({ historyLength: 1, showcase: { items: [trainer(1), trainer(2)] }, session: PHONE });
    await tick();
    assert.equal(backHtml(h), null);
  });

  it('внутри витрины «Назад» — на предыдущий вид, а из корня — на экран, откуда пришли', async () => {
    const h = boot({ historyLength: 2, showcase: { items: [trainer(1), trainer(2)] }, session: PHONE, routes: [slotsRoute] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    assert.equal(backHtml(h), 'Тренеры');
    h.click({ 'data-act': 'back' });
    assert.equal(h.S.view, 'list');
    assert.equal(h.ctx.history.left, 0, 'со своей записи истории со страницы не уходим');
    h.click({ 'data-act': 'back' });
    assert.equal(h.ctx.history.left, 1);
  });
});

describe('нативная «назад» Telegram (MiniAppBack)', () => {
  const stub = () => {
    const log = { set: [], clear: 0 };
    return { log, isNative: () => true, set: (fn) => { log.set.push(fn); return true; }, clear: () => { log.clear += 1; } };
  };

  it('на карточке тренера своей кнопки нет, «назад» — нативная и ведёт в список', async () => {
    const back = stub();
    const h = boot({ historyLength: 1, showcase: { items: [trainer(1), trainer(2)] }, session: PHONE, routes: [slotsRoute], miniAppBack: back });
    await tick();
    assert.equal(back.log.set.length, 0, 'корень без истории — стрелки нет');
    assert.ok(back.log.clear > 0);
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    assert.equal(backHtml(h), null);
    assert.ok(back.log.set.length > 0, 'внутри витрины стрелка включена');
    back.log.set[back.log.set.length - 1]();
    assert.equal(h.S.view, 'list');
  });

  it('если пришли с другого экрана, стрелка есть и на списке', async () => {
    const back = stub();
    boot({ historyLength: 3, showcase: { items: [trainer(1), trainer(2)] }, session: PHONE, miniAppBack: back });
    await tick();
    assert.ok(back.log.set.length > 0);
  });
});

describe('прямая ссылка на тренера (?trainer_id=)', () => {
  it('пришли с катка/«Поиска» — «‹ Назад» возвращает туда, а не в список', async () => {
    const h = boot({ search: '?trainer_id=2&arena_id=3', historyLength: 4, showcase: { items: [trainer(1), trainer(2)] }, session: PHONE, routes: [slotsRoute] });
    await tick();
    assert.equal(h.S.view, 'trainer');
    assert.equal(backHtml(h), 'Назад');
    h.click({ 'data-act': 'back' });
    assert.equal(h.ctx.history.left, 1);
    assert.equal(h.S.view, 'trainer');
  });

  it('некуда возвращаться (ссылка из чата) — «‹ Все тренеры» ведёт в список', async () => {
    const h = boot({ search: '?trainer_id=2', historyLength: 1, showcase: { items: [trainer(1), trainer(2)] }, session: PHONE, routes: [slotsRoute] });
    await tick();
    assert.equal(h.S.view, 'trainer');
    assert.equal(backHtml(h), 'Все тренеры');
    h.click({ 'data-act': 'back' });
    assert.equal(h.S.view, 'list');
    assert.equal(h.ctx.history.left, 0);
  });

  it('с тренера по ссылке — «другое время» и назад: снова тренер, со страницы не уходим', async () => {
    const h = boot({ search: '?trainer_id=2', historyLength: 2, showcase: { items: [trainer(1), trainer(2)] }, session: PHONE, routes: [slotsRoute] });
    await tick();
    h.click({ 'data-act': 'week' });
    assert.equal(h.S.view, 'week');
    h.click({ 'data-act': 'back' });
    assert.equal(h.S.view, 'trainer');
    assert.equal(h.ctx.history.left, 0);
  });
});
