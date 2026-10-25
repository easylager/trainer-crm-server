/**
 * Экран успеха записи: блок «Разрешить» и честные обещания.
 * Нативный диалог Telegram не воспроизводится: window.Telegram.WebApp — мок.
 *
 * Run: node --test tests/js/write-access-booking.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const waSource = fs.readFileSync(path.join(webapp, 'write-access.js'), 'utf8');
const bookingSource = fs.readFileSync(path.join(webapp, 'booking-client.js'), 'utf8');

const ASK = 'Чтобы получить подтверждение и напоминание о тренировке, разрешите сообщения от бота.';
const GRANTED = 'Готово. Напишем, когда тренер подтвердит запись, и напомним о тренировке.';
const DENIED = 'Уведомления выключены. Статус записи виден в приложении.';
const OPEN_BOT = 'Откройте бота и нажмите «Старт», чтобы получать уведомления.';

async function flush() {
  for (let i = 0; i < 30; i += 1) await Promise.resolve();
}

/** tgOpts: null — вне Telegram. */
function boot(tgOpts, botLink) {
  const fetchCalls = [];
  const win = {};
  win.window = win;
  win.document = { getElementById: (id) => (id === 'successText' ? win.__container || null : null), body: { classList: { add() {} } }, documentElement: { classList: { add() {}, remove() {} } } };
  win.scrollTo = () => {};
  win.requestAnimationFrame = () => {};
  win.fetch = (url, init) => {
    fetchCalls.push({ url, init, body: init && init.body ? JSON.parse(init.body) : null });
    return Promise.resolve({
      ok: true,
      text: () => Promise.resolve('{}'),
      json: () => Promise.resolve({ ok: true, bot_link: botLink === undefined ? 'https://t.me/glide_bot' : botLink }),
    });
  };
  const tg = tgOpts
    ? {
        initData: 'x',
        initDataUnsafe: { user: Object.assign({ id: 5 }, tgOpts.user || {}) },
        requests: 0,
        opened: [],
        isVersionAtLeast: () => true,
        openTelegramLink(u) {
          tg.opened.push(u);
        },
      }
    : null;
  if (tg && !tgOpts.noMethod) {
    tg.requestWriteAccess = (cb) => {
      tg.requests += 1;
      cb(tgOpts.answer === undefined ? true : tgOpts.answer);
    };
  }
  if (tg) win.Telegram = { WebApp: tg };
  const ctx = vm.createContext(win);
  vm.runInContext(waSource, ctx);
  vm.runInContext(bookingSource, ctx);
  win.BookingClient.__win = win;
  return { BC: win.BookingClient, tg, fetchCalls, win };
}

/** Мини-DOM контейнера успеха: достаточно для bindWriteAccessBlock. */
function fakeContainer(html) {
  const m = /data-wa-block="(\w+)"/.exec(html);
  if (!m) return { querySelector: () => null, innerHTML: html };
  const text = { textContent: '' };
  const btn = { hidden: m[1] === 'unsupported', disabled: false, textContent: '', onclick: null };
  const block = {
    getAttribute: () => m[1],
    querySelector: (sel) => (sel === '[data-wa-text]' ? text : sel === '[data-wa-allow]' ? btn : null),
  };
  return { querySelector: (sel) => (sel === '[data-wa-block]' ? block : null), innerHTML: html, text, btn };
}

function showSuccess(BC, html) {
  const container = fakeContainer(html);
  BC.__win.__container = container;
  BC.showBookingSuccess({
    host: 'catalog',
    messageHtml: html,
    showScreen() {},
  });
  return container;
}

describe('блок разрешения на экране успеха', () => {
  it('askable: блок есть, ложные обещания скрыты, диалог сам не открывается', () => {
    const { BC, tg } = boot({});
    const html = BC.formatSuccessMessage({ success: true }, {});
    assert.match(html, /data-wa-block="askable"/);
    assert.ok(html.includes(ASK));
    assert.ok(!html.includes('в боте.'), 'обещание «в боте» не должно стоять рядом с блоком');
    assert.match(html, /Ожидайте подтверждения от тренера\./);
    assert.equal(tg.requests, 0);
  });

  it('первая запись: у недостижимого нет «придёт сюда, в бот» и «Напомним»', () => {
    const { BC } = boot({});
    const html = BC.formatSuccessMessage({ is_first_booking: true, reminder_plan: 'за сутки' }, {});
    assert.ok(!html.includes('в бот'));
    assert.ok(!/Напомним/.test(html));
    assert.match(html, /Тренер подтвердит запись\./);
    assert.match(html, /Моих записях/);
    assert.match(html, /data-wa-block="askable"/);
  });

  it('allows_write_to_pm === true: блока нет, обещания как раньше', () => {
    const { BC } = boot({ user: { allows_write_to_pm: true } });
    const html = BC.formatSuccessMessage({ is_first_booking: true, reminder_plan: 'за сутки' }, {});
    assert.ok(!html.includes('data-wa-block'));
    assert.match(html, /уведомление придёт сюда, в бот/);
    assert.match(html, /Напомним о тренировке за сутки/);
  });

  it('вне Telegram и MAX/VK: ничего не меняется', () => {
    for (const b of [boot(null), boot({ user: { id: -77 } })]) {
      const html = b.BC.formatSuccessMessage({ is_first_booking: true, reminder_plan: 'за сутки' }, {});
      assert.ok(!html.includes('data-wa-block'));
      assert.match(html, /уведомление придёт сюда, в бот/);
    }
  });

  it('тап «Разрешить»: диалог открывается ровно один раз и только по тапу; granted заменяет блок', async () => {
    const { BC, tg, fetchCalls } = boot({ answer: true });
    const html = BC.formatSuccessMessage({ success: true }, {});
    const c = showSuccess(BC, html);
    assert.equal(tg.requests, 0, 'до тапа диалога нет (блок привязан показом экрана успеха)');
    assert.equal(typeof c.btn.onclick, 'function');
    c.btn.onclick();
    await flush();
    assert.equal(tg.requests, 1);
    assert.equal(c.text.textContent, GRANTED);
    assert.equal(c.btn.hidden, true);
    assert.equal(fetchCalls.at(-1).body.surface, 'booking');
    assert.equal(fetchCalls.at(-1).body.outcome, 'granted');
  });

  it('отказ: строка про выключенные уведомления и кнопка «Разрешить» остаётся', async () => {
    const { BC, tg, fetchCalls } = boot({ answer: false });
    const c = fakeContainer(BC.formatSuccessMessage({ success: true }, {}));
    BC.bindWriteAccessBlock(c);
    c.btn.onclick();
    await flush();
    assert.equal(c.text.textContent, DENIED);
    assert.equal(c.btn.hidden, false);
    assert.equal(c.btn.textContent, 'Разрешить');
    assert.equal(fetchCalls.at(-1).body.outcome, 'denied');
    c.btn.onclick();
    await flush();
    assert.equal(tg.requests, 2);
    assert.equal(fetchCalls.at(-1).body.retry, true);
  });

  it('unsupported: честная строка и кнопка, открывающая чат бота по ссылке с сервера', async () => {
    const { BC, tg, fetchCalls } = boot({ noMethod: true }, 'https://t.me/glide_bot');
    const html = BC.formatSuccessMessage({ success: true }, {});
    assert.match(html, /data-wa-block="unsupported"/);
    assert.ok(html.includes(OPEN_BOT.replace(/«/g, '«')));
    const c = fakeContainer(html);
    BC.bindWriteAccessBlock(c);
    await flush();
    assert.equal(fetchCalls.at(-1).body.outcome, 'unsupported');
    assert.equal(c.btn.hidden, false);
    c.btn.onclick();
    assert.deepEqual(tg.opened, ['https://t.me/glide_bot']);
  });

  it('unsupported без ссылки: кнопки нет, строка честная', async () => {
    const { BC } = boot({ noMethod: true }, null);
    const c = fakeContainer(BC.formatSuccessMessage({ success: true }, {}));
    BC.bindWriteAccessBlock(c);
    await flush();
    assert.equal(c.btn.hidden, true);
  });

  it('already: на экране успеха фиксируется исход already, блока нет', async () => {
    const { BC, fetchCalls } = boot({ user: { allows_write_to_pm: true } });
    showSuccess(BC, BC.formatSuccessMessage({ success: true }, {}));
    await flush();
    assert.equal(fetchCalls.length, 1);
    assert.equal(fetchCalls[0].body.outcome, 'already');
  });

  it('запись не затрагивается: submit/payload не вызывают ни диалог, ни метрику', async () => {
    const { BC, tg, fetchCalls } = boot({});
    BC.buildBookingPayload({ slotId: 1, phone: '+375291112233' });
    await BC.submitBooking({ body: { slot_id: 1 }, initData: 'x' });
    assert.equal(tg.requests, 0);
    assert.deepEqual(
      fetchCalls.map((c) => c.url.split('?')[0]),
      ['/api/webapp/client/booking']
    );
  });
});
