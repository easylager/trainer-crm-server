/**
 * TASK-401: форма K (доска Register). Флаг выключен — как на базе d4419b77 (снимок), таймер и хаб.
 * Флаг включён — заголовок, пояснение, имя → телефон, подсказка, слот в две строки, replace на карточку.
 * Run: node --test tests/js/client-register-unified.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { bootRegister, jsonResponse, tick } = require('./helpers/client-register-harness');
const { capture } = require('./helpers/client-register-flag-off-scenarios');
const SNAPSHOT = require('./fixtures/client-register-flag-off.snapshot.json');

const SLOT = { available: true, slot: { slot_date: '2026-11-21', start_time: '10:00', arena_name: 'Замок' } };
const LISTED_KEY = 'trainer_crm_listed_trainer_id';
const selfRegister = (reply) => ({ match: (u) => u.includes('/client/self-register'), reply });
const texts = (h, id) => (h.ids[id] ? h.ids[id].textContent : undefined);

describe('форма регистрации: флаг выключен', () => {
  it('дерево, запросы, таймеры и переходы побайтно как на базе d4419b77', async () => {
    const now = await capture({ withRuName: true });
    assert.deepEqual(Object.keys(now), Object.keys(SNAPSHOT));
    for (const k of Object.keys(SNAPSHOT)) assert.deepEqual(now[k], SNAPSHOT[k], k);
  });

  it('хаб и таймер, без пояснения K', async () => {
    const h = bootRegister({ session: { client_phone: '+375291112233', client_first_name: 'Анна' } });
    await tick();
    const redirect = h.timeouts.find((t) => t.ms >= 2000 && t.ms < 10000);
    assert.ok(redirect, 'автопереход');
    redirect.fn();
    assert.ok(h.hrefs.some((u) => u.includes('client-home')));
    assert.equal(h.replaced.length, 0);
    assert.equal(h.ids.crPhoneNote, undefined);
    assert.equal(texts(h, 'crHeroTitle'), 'Короткий профиль');
  });
});

describe('K: слот по ссылке (A1)', () => {
  it('адрес /client/slot — один «?», trainer_id и init_data на месте', async () => {
    const h = bootRegister({ unified: true, search: '?trainer_id=7&slot_id=55', slot: SLOT });
    await tick();
    const call = h.fetches.find((f) => f.url.includes('/client/slot/'));
    assert.ok(call, 'слот запрошен');
    assert.equal((call.url.match(/\?/g) || []).length, 1, call.url);
    const u = new URL(call.url, 'https://x');
    assert.equal(u.pathname, '/api/webapp/client/slot/55');
    assert.equal(u.searchParams.get('trainer_id'), '7');
    assert.equal(u.searchParams.get('init_data'), 'user=1');
  });

  it('вне Telegram (без initData) — адрес без init_data, trainer_id на месте', async () => {
    const h = bootRegister({ unified: true, search: '?trainer_id=7&slot_id=55', initData: '', slot: SLOT });
    await tick();
    const call = h.fetches.find((f) => f.url.includes('/client/slot/'));
    assert.equal(call.url, '/api/webapp/client/slot/55?trainer_id=7');
  });
});

describe('K по доске Register (A2, A3)', () => {
  it('заголовок, пояснение, имя → телефон, подсказка без точки, приватность, слот в две строки', async () => {
    const h = bootRegister({ unified: true, search: '?trainer_id=7&slot_id=55', slot: SLOT });
    await tick();
    assert.equal(texts(h, 'crHeroTitle'), 'Профиль для записи к Анне');
    assert.equal(texts(h, 'crHeroSub'),
      'Чтобы Анна нашла вас в своём списке и подтянула ваши абонементы и записи — укажите имя и телефон.');
    assert.equal(texts(h, 'crPhoneNote'), 'Тот же номер, что у вас записан у Анны');
    assert.equal(texts(h, 'crKPrivacy'), 'Имя и телефон видит только Анна');
    assert.equal(h.ids.crLastNameBlock.hidden, true);
    assert.equal(h.ids.crPhone.getAttribute('aria-describedby'), 'crPhoneNote');

    const card = h.ids.crFormCard.children;
    assert.ok(card.indexOf(h.ids.crFirstName.parentNode) < card.indexOf(h.ids.crPhone.parentNode.parentNode), 'сначала имя');
    const tree = h.tree();
    assert.match(tree, /label \{Ваше имя\}/);
    assert.match(tree, /label \{Телефон\}/);
    // подсказка сразу под полем телефона, до строки ошибки
    const phoneStack = h.ids.crPhoneError.parentNode.children;
    assert.equal(phoneStack.indexOf(h.ids.crPhoneNote) + 1, phoneStack.indexOf(h.ids.crPhoneError));

    const bar = h.ids.crSlotBar;
    assert.equal(h.ids.crShell.children[0], bar, 'слот сверху');
    assert.deepEqual(bar.children.map((c) => c.textContent), ['Сб, 10:00', 'Анна Соколова · «Замок»']);
  });

  it('мужское имя — «нашёл/подтянул», «к Дмитрию», «у Дмитрия»', async () => {
    const h = bootRegister({ unified: true, trainerInfo: { id: 7, name: 'Дмитрий Петров' } });
    await tick();
    assert.equal(texts(h, 'crHeroTitle'), 'Профиль для записи к Дмитрию');
    assert.match(texts(h, 'crHeroSub'), /^Чтобы Дмитрий нашёл вас в своём списке и подтянул /);
    assert.equal(texts(h, 'crPhoneNote'), 'Тот же номер, что у вас записан у Дмитрия');
  });

  it('склонение не сработало (нет ru-person-name.js, латиница) — имя как есть, без ошибки', async () => {
    const noLib = bootRegister({ unified: true, withRuName: false });
    await tick();
    assert.equal(texts(noLib, 'crHeroTitle'), 'Профиль для записи к Анна');
    assert.equal(texts(noLib, 'crPhoneNote'), 'Тот же номер, что у вас записан у Анна');
    const latin = bootRegister({ unified: true, trainerInfo: { id: 7, name: 'Anna Sokolova' } });
    await tick();
    assert.equal(texts(latin, 'crPhoneNote'), 'Тот же номер, что у вас записан у Anna');
  });

  it('имя тренера не пришло — «тренер», без пустых мест', async () => {
    const h = bootRegister({ unified: true, routes: [{ match: (u) => u.includes('/trainer-info/'), reply: () => jsonResponse(404, { detail: 'нет' }) }] });
    await tick();
    assert.equal(texts(h, 'crHeroTitle'), 'Профиль для записи к тренеру');
    assert.equal(texts(h, 'crPhoneNote'), 'Тот же номер, что у вас записан у тренера');
    assert.equal(texts(h, 'crKPrivacy'), 'Имя и телефон видит только тренер');
  });

  it('слот недоступен — полосы нет', async () => {
    const h = bootRegister({ unified: true, search: '?trainer_id=7&slot_id=55' });
    await tick();
    assert.equal(h.ids.crSlotBar, undefined);
  });
});

describe('K: после сохранения', () => {
  it('replace на карточку без таймера; привязка записана для этого тренера', async () => {
    const h = bootRegister({
      unified: true,
      search: '?trainer_id=7&slot_id=55',
      session: { client_phone: '+375291112233', client_first_name: 'Анна' },
      slot: SLOT,
    });
    await tick();
    assert.ok(h.replaced.some((u) => u.includes('trainers?trainer_id=7') && u.includes('listed=1') && u.includes('slot_id=55')));
    assert.ok(!h.timeouts.some((t) => t.ms >= 2000 && t.ms < 10000));
    assert.equal(h.hrefs.length, 0);
    assert.equal(h.store[LISTED_KEY], '7');
  });

  it('отправка формы: успех → привязка записана и replace', async () => {
    const h = bootRegister({ unified: true });
    await tick();
    h.ids.crPhone.value = '29 123-45-67';
    h.ids.crFirstName.value = 'Мария';
    h.submit();
    await tick();
    assert.equal(h.store[LISTED_KEY], '7');
    assert.equal(h.replaced.length, 1);
  });

  it('отправка формы: 409 — ошибка под телефоном, привязки нет, переходов нет', async () => {
    const h = bootRegister({ unified: true, routes: [selfRegister(() => jsonResponse(409, { detail: 'Этот номер уже используется другим аккаунтом Telegram.' }))] });
    await tick();
    h.ids.crPhone.value = '29 123-45-67';
    h.ids.crFirstName.value = 'Мария';
    h.submit();
    await tick();
    assert.equal(h.store[LISTED_KEY], undefined);
    assert.equal(h.replaced.length, 0);
    assert.match(texts(h, 'crPhoneError'), /уже используется/);
  });
});

describe('K: профиль уже полный, привязка не удалась (A6)', () => {
  for (const [name, reply, re] of [
    ['409', () => jsonResponse(409, { detail: 'Этот номер уже используется другим аккаунтом Telegram.' }), /уже используется/],
    ['500', () => jsonResponse(500, { detail: 'Internal Server Error' }), /Internal Server Error/],
    ['сеть', () => Promise.reject(new TypeError('Failed to fetch')), /Проверьте интернет/],
  ]) {
    it(name + ': ошибка на экране, форма для повтора, ни «Вы в списке», ни перехода', async () => {
      const h = bootRegister({
        unified: true,
        session: { client_phone: '+375291112233', client_first_name: 'Анна' },
        routes: [selfRegister(reply)],
      });
      await tick();
      assert.equal(h.replaced.length, 0, 'нет перехода на карточку');
      assert.equal(h.hrefs.length, 0);
      assert.equal(h.store[LISTED_KEY], undefined, 'привязка не записана');
      assert.match(texts(h, 'crGlobalError'), re);
      assert.ok(h.ids.crGlobalError.classList.contains('cr-global-error--visible'));
      assert.notEqual(h.ids.crFormCard.style.display, 'none', 'форма на месте');
      assert.notEqual(h.ids.crActions.style.display, 'none', 'кнопка «Продолжить» на месте');
    });
  }
});
