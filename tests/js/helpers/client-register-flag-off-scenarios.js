'use strict';
/**
 * TASK-401: форма регистрации при ВЫКЛЮЧЕННОМ флаге. Снимок снят на базе d4419b77 (до TASK-401):
 * tests/js/fixtures/client-register-flag-off.snapshot.json. Снимается дерево страницы, все запросы
 * (полный URL и тело), переходы, таймеры автоперехода и sessionStorage.
 */
const { bootRegister, jsonResponse, tick } = require('./client-register-harness');

function snap(h) {
  return {
    tree: h.tree(),
    fetches: h.fetches.map((f) => f.method + ' ' + f.url + (f.body ? ' ' + JSON.stringify(f.body) : '')),
    replaced: h.replaced.slice(),
    hrefs: h.hrefs.slice(),
    timers: h.timeouts.map((t) => t.ms),
    store: JSON.stringify(h.store),
  };
}

const failSelfRegister = (status) => ({
  match: (u) => u.includes('/client/self-register'),
  reply: () => (status ? jsonResponse(status, { detail: 'Ошибка ' + status }) : Promise.reject(new TypeError('Failed to fetch'))),
});

async function capture(opts = {}) {
  const base = { withRuName: opts.withRuName, file: opts.file };
  const out = {};

  // Новый клиент по ссылке со слотом: форма, отправка, автопереход по таймеру.
  {
    const h = bootRegister({ ...base, search: '?trainer_id=7&slot_id=55' });
    await tick();
    out.fresh = snap(h);
    h.ids.crPhone.value = '29 123-45-67';
    h.ids.crFirstName.value = 'Мария';
    h.submit();
    await tick();
    out['fresh:submitted'] = snap(h);
    const timer = h.timeouts.find((t) => t.ms >= 2000 && t.ms < 10000);
    if (timer) timer.fn();
    out['fresh:redirect'] = snap(h);
  }

  // Профиль уже полный: привязка к тренеру и автопереход.
  {
    const h = bootRegister({ ...base, session: { client_phone: '+375291112233', client_first_name: 'Мария' } });
    await tick();
    out.already = snap(h);
  }

  // Профиль полный, привязка упала: 409, 500, сеть.
  for (const st of [409, 500, 0]) {
    const h = bootRegister({
      ...base,
      session: { client_phone: '+375291112233', client_first_name: 'Мария' },
      routes: [failSelfRegister(st)],
    });
    await tick();
    out['already:fail' + st] = snap(h);
  }

  // Отправка формы с ошибкой сервера: 409 под полем телефона, 500 — общая.
  for (const st of [409, 500]) {
    const h = bootRegister({ ...base, routes: [failSelfRegister(st)] });
    await tick();
    h.ids.crPhone.value = '29 123-45-67';
    h.ids.crFirstName.value = 'Мария';
    h.submit();
    await tick();
    out['submit:fail' + st] = snap(h);
  }

  return out;
}

module.exports = { capture };
