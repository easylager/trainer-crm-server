/**
 * Защита от повторных тапов и честные ошибки в клиентских экранах:
 *  - «Активировать» сертификат: двойной тап = один запрос;
 *  - отписка от тренера: подтверждение и один DELETE;
 *  - отмена записи: одно сообщение, без «[object Object]»;
 *  - запись по занятому окну: свободные окна недели видны под сообщением;
 *  - неделя записи считается по Минску.
 * Run: node --test tests/js/client-actions-guards.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { runInlinePage, json, tick } = require('./helpers/inline-page');

describe('сертификат: двойной тап «Активировать»', () => {
  for (const [file, btn] of [['client-certificates.html', 'btnActivateCert'], ['client-passes-certificates.html', 'cert-btnActivateCert']]) {
    it(file + ': один запрос, после успеха нет «Код не найден»', async () => {
      const calls = [];
      let release;
      const gate = new Promise((r) => { release = r; });
      const page = runInlinePage(file, {
        fetch: (url, init) => {
          calls.push(String(url));
          if (String(url).includes('/certificates/activate')) {
            return calls.filter((u) => u.includes('/activate')).length === 1
              ? gate.then(() => json({ city_id: null }))
              : json({ detail: 'Код не найден или уже использован.' }, false, 404);
          }
          return json({ items: [] });
        },
      });
      page.getEl('certCodeInput').value = 'ABC-123';
      const b = page.getEl(btn);
      assert.ok(b.onclick, 'обработчик кнопки есть');
      b.onclick();
      b.onclick();
      release();
      await tick();
      assert.equal(calls.filter((u) => u.includes('/activate')).length, 1);
      assert.equal(page.alerts.length, 0, 'вместо алерта — панель с кнопкой: ' + JSON.stringify(page.alerts));
      assert.match(page.getEl('certActivatedNote').innerHTML, /Сертификат активирован/);
    });

    it(file + ': после активации есть кнопка — к тренеру или в каталог', async () => {
      for (const [reply, path, label] of [
        [{ city_id: 1, service_id: 2, trainer_id: 9 }, 'catalog?trainer_id=9', /Записаться к тренеру/],
        [{ city_id: null }, 'ice?intent=coach', /Выбрать тренера/],
      ]) {
        const nav = [];
        const page = runInlinePage(file, {
          window: { ClientShell: { navigate: (p) => nav.push(p) } },
          fetch: (url) => (String(url).includes('/certificates/activate') ? json(reply) : json({ items: [] })),
        });
        page.getEl('certCodeInput').value = 'ABC-123';
        page.getEl(btn).onclick();
        await tick();
        const note = page.getEl('certActivatedNote');
        assert.equal(note.hidden, false);
        assert.match(note.innerHTML, label);
        assert.equal(page.alerts.length, 0);
        page.getEl('certActivatedGo').onclick();
        assert.deepEqual(nav, [path]);
      }
    });
  }
});

const { inlineScripts } = require('./helpers/inline-page');

describe('отмена записи: ошибка показывается один раз и читаемо', () => {
  async function failCancel(detail) {
    const src = inlineScripts('client-bookings.html').replace(/\}\)\(\);\s*$/, 'window.__st = state; })();');
    const page = runInlinePage('client-bookings.html', {
      source: src,
      fetch: (url, init) => {
        const u = String(url);
        if (u.includes('/cancel')) return json({ detail }, false, 422);
        return json({ days: [{ date: '2099-01-01', bookings: [{ id: 5 }] }] });
      },
    });
    await tick();
    page.win.__st = page.ctx.window.__st;
    page.ctx.window.__st.cancelBookingId = 5;
    page.getEl('modalCancelYes').onclick();
    await tick(200);
    return page;
  }

  it('detail списком ошибок → текст, а не [object Object]; сообщение одно', async () => {
    const page = await failCancel([{ msg: 'Отмена невозможна менее чем за 2 часа' }]);
    assert.equal(page.alerts.length, 0, 'алерт поверх тоста не нужен: ' + JSON.stringify(page.alerts));
    assert.equal(page.getEl('appToast').textContent, 'Отмена невозможна менее чем за 2 часа');
  });

  it('detail объектом → без [object Object]', async () => {
    const page = await failCancel({ code: 'x', message: 'Слишком поздно' });
    assert.equal(page.getEl('appToast').textContent, 'Слишком поздно');
    assert.equal(page.alerts.length, 0);
  });
});

describe('отписка от тренера (🔕)', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const { webapp } = require('./helpers/inline-page');
  const src = fs
    .readFileSync(path.join(webapp, 'client-saved-trainers-main.js'), 'utf8')
    .replace(/\}\)\(\);\s*$/, 'window.__wire = wireMount; })();');

  function boot(confirmAnswers) {
    const deletes = [];
    const asked = [];
    const page = runInlinePage('x', {
      source: src,
      telegram: {
        showConfirm: (msg, cb) => { asked.push(msg); cb(confirmAnswers.shift()); },
      },
      fetch: (url, init) => {
        if (init && init.method === 'DELETE') { deletes.push(String(url)); return json({ ok: true }); }
        return json({ items: [] });
      },
    });
    const handlers = {};
    const mk = (attr, val) => ({
      getAttribute: (n) => (n === attr ? val : null),
      addEventListener(t, fn) { handlers[attr] = fn; },
    });
    const container = {
      querySelectorAll: (sel) => (sel === '[data-off-trainer]' ? [mk('data-off-trainer', '77')] : []),
      querySelector: () => null,
    };
    page.win.__wire(container);
    const tap = () => handlers['data-off-trainer']({ stopPropagation() {} });
    return { tap, deletes, asked };
  }

  it('отказ в подтверждении — запроса нет', async () => {
    const t = boot([false]);
    t.tap();
    await tick();
    assert.equal(t.asked.length, 1);
    assert.equal(t.deletes.length, 0);
  });

  it('подтвердили, затем двойной тап — один DELETE, второй раз не спрашиваем', async () => {
    const t = boot([true, true]);
    t.tap();
    t.tap();
    await tick();
    assert.equal(t.deletes.length, 1);
    assert.equal(t.asked.length, 1);
  });
});

describe('book.html: окно записи и неделя', () => {
  /* Воскресенье, 23:00 в Минске; у телефона в Окленде (UTC+13) уже понедельник. */
  const NOW = Date.parse('2026-11-01T20:00:00Z');
  const slot = (id, date) => ({ id, slot_date: date, start_time: '10:00', end_time: '11:00', capacity: 1, spots_left: 1 });

  async function openBook(search, slots) {
    const prevTz = process.env.TZ;
    process.env.TZ = 'Pacific/Auckland';
    try {
      const RealDate = Date;
      class FakeDate extends RealDate {
        constructor(...a) { super(...(a.length ? a : [NOW])); }
        static now() { return NOW; }
      }
      const page = runInlinePage('book.html', {
        search,
        pre: ['minsk-time.js'],
        sandbox: { Date: FakeDate },
        fetch: (url) => {
          if (String(url).includes('/client/slots')) return json({ trainer_name: 'Анна', slots });
          return json({});
        },
      });
      await tick(300);
      return page;
    } finally {
      if (prevTz === undefined) delete process.env.TZ;
      else process.env.TZ = prevTz;
    }
  }

  it('ссылка на занятое окно: сообщение и свободные окна недели вместе', async () => {
    const page = await openBook('?trainer_id=5&request_id=3&slot_id=999&service_id=1', [slot(1, '2026-10-28'), slot(2, '2026-10-30')]);
    const html = page.getEl('content').innerHTML;
    assert.match(html, /уже занято или недоступно/);
    assert.match(html, /data-slot-id="1"/);
    assert.match(html, /data-slot-id="2"/);
  });

  it('неделя записи — по Минску, а не по часам телефона', async () => {
    const page = await openBook('?trainer_id=5&request_id=3&service_id=1', [slot(1, '2026-10-28')]);
    assert.equal(page.getEl('weekLabel').textContent, '26 окт – 1 ноя');
    assert.match(page.getEl('content').innerHTML, /data-slot-id="1"/);
  });
});
