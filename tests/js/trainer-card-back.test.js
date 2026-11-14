/**
 * TASK-403: «Назад», история и диплинки в витрине под флагом единой карточки (SPEC §8.1 п. 2–5, 8; ENTRIES §D).
 * Стенд эмулирует history (pushState/replaceState/back → popstate) и нативную стрелку Telegram (MiniAppBack).
 * Флаг выключен — прежнее поведение держат trainer-showcase-nav.test.js и снимки 161bd810.
 * Run: node --test tests/js/trainer-card-back.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');
const { STATES } = require('./fixtures/trainer-card-states');

const trainer = STATES.A.trainer;
const other = STATES.B.trainer;
const SESSION = { city_id: 1, city_name: 'Минск', client_phone: '+375291112233', client_first_name: 'Анна' };

/** Нативная стрелка Telegram: последний вызов set/clear — то, что сейчас видно в шапке. */
function nativeBack() {
  return {
    fn: null, shown: false, sets: 0,
    isNative() { return true; },
    set(fn) { this.fn = fn; this.shown = true; this.sets += 1; return true; },
    clear() { this.fn = null; this.shown = false; },
    press() { assert.ok(this.shown && this.fn, 'стрелка должна быть видна'); this.fn(); },
  };
}

function slotsRoute(list) {
  return { match: (c) => c.url.split('?')[0] === '/api/webapp/client/slots', reply: () => resp(200, { slots: typeof list === 'function' ? list() : list }) };
}

const SAME_ORIGIN = 'https://x/static/webapp/client-home';
const FOREIGN = 'https://evil.example/landing';

function open(opts = {}) {
  return boot({
    unified: opts.unified !== false,
    search: opts.search || '?trainer_id=' + trainer.id,
    initData: 'x',
    historyLength: opts.historyLength == null ? 1 : opts.historyLength,
    navigation: opts.navigation || null,
    referrer: opts.referrer || '',
    sessionStore: opts.sessionStore || {},
    showcase: { items: [trainer, other] },
    session: opts.session || SESSION,
    routes: opts.routes || [slotsRoute(STATES.A.slots)],
    miniAppBack: opts.miniAppBack,
  });
}

const OTHERS = /<button type="button" class="tc-sec" data-act="to-list">Другие тренеры в Минске<\/button>/;
const HERO_BACK = /tc-hbtn--back/;
const slotCalls = (h) => h.calls.filter((c) => c.url.split('?')[0] === '/api/webapp/client/slots').length;

describe('AC-001 · внешний вход без слота — карточка корень', () => {
  it('Telegram: стрелки нет, внизу «Другие тренеры в Минске», кнопка ведёт в список', async () => {
    const back = nativeBack();
    const h = open({ miniAppBack: back });
    await tick(60);
    assert.equal(h.S.view, 'trainer');
    assert.equal(back.shown, false, 'корень по ссылке — без нативной стрелки');
    assert.match(h.app.innerHTML, OTHERS);
    h.click({ 'data-act': 'to-list' });
    assert.equal(h.S.view, 'list');
    assert.equal(back.shown, false);
    h.click({ 'data-act': 'trainer', 'data-tid': String(other.id) });
    await tick(40);
    assert.equal(back.shown, true, 'из списка вглубь — стрелка есть');
    assert.doesNotMatch(h.app.innerHTML, /Другие тренеры в/, 'не корень — без кнопки');
    back.press();
    assert.equal(h.S.view, 'list');
  });

  it('браузер: на фото нет своей стрелки «Назад», кнопка «Другие тренеры» есть', async () => {
    const h = open();
    await tick(60);
    assert.doesNotMatch(h.app.innerHTML, HERO_BACK);
    assert.match(h.app.innerHTML, OTHERS);
  });

  it('popstate браузера на корне оставляет карточку, а не уводит в список', async () => {
    const back = nativeBack();
    const h = open({ search: '?trainer_id=1&slot_id=101', miniAppBack: back });
    await tick(80);
    assert.equal(h.S.view, 'book');
    back.press(); // нативная стрелка не снимает запись истории — она остаётся «висеть»
    assert.equal(h.S.view, 'trainer');
    h.ctx.history.back(); // браузерная «назад» поверх неё
    assert.equal(h.S.view, 'trainer');
    assert.match(h.app.innerHTML, OTHERS);
  });

  it('вход из приложения (same-origin referrer) — стрелка есть и уводит туда, кнопки «Другие тренеры» нет', async () => {
    const back = nativeBack();
    const h = open({ historyLength: 5, referrer: SAME_ORIGIN, miniAppBack: back });
    await tick(60);
    assert.equal(back.shown, true);
    assert.doesNotMatch(h.app.innerHTML, /Другие тренеры в/);
    back.press();
    assert.equal(h.ctx.history.left, 1);
  });

  it('с хаба (from=hub) — не корень, даже если история пуста', async () => {
    const back = nativeBack();
    const h = open({ search: '?trainer_id=1&from=hub', historyLength: 1, miniAppBack: back });
    await tick(60);
    assert.equal(back.shown, true);
    assert.doesNotMatch(h.app.innerHTML, /Другие тренеры в/);
  });

  it('город: падеж неизвестен — «· Тверь»; список другого города (city_id адреса) — без города', async () => {
    const tver = open({ session: { ...SESSION, city_id: 9, city_name: 'Тверь' } });
    await tick(60);
    assert.match(tver.app.innerHTML, /data-act="to-list">Другие тренеры · Тверь<\/button>/);
    const foreign = open({ search: '?trainer_id=1&city_id=2' });
    await tick(60);
    assert.match(foreign.app.innerHTML, /data-act="to-list">Другие тренеры<\/button>/);
  });
});

describe('CAME_FROM: Navigation API вместо history.length (iframe Telegram Web)', () => {
  it('history.length 5, но canGoBack=false — холодная ссылка, карточка корень', async () => {
    const back = nativeBack();
    const h = open({ historyLength: 5, navigation: { canGoBack: false }, miniAppBack: back });
    await tick(60);
    assert.equal(back.shown, false);
    assert.match(h.app.innerHTML, OTHERS);
  });

  it('history.length 1, но canGoBack=true — пришли из приложения, стрелка уводит туда', async () => {
    const back = nativeBack();
    const h = open({ historyLength: 1, navigation: { canGoBack: true }, miniAppBack: back });
    await tick(60);
    assert.equal(back.shown, true);
    back.press();
    assert.equal(h.ctx.history.left, 1);
  });

  it('флаг выключен — Navigation API не читаем: как раньше, по history.length', async () => {
    const h = open({ unified: false, historyLength: 5, navigation: { canGoBack: false } });
    await tick(60);
    assert.match(h.app.innerHTML, /data-act="back">‹ Назад<\/button>/);
    h.click({ 'data-act': 'back' });
    assert.equal(h.ctx.history.left, 1);
  });

  it('API нет × referrer пустой: history.length не делает карточку «из приложения»', async () => {
    const back = nativeBack();
    const h = open({ historyLength: 5, referrer: '', miniAppBack: back });
    await tick(60);
    assert.equal(back.shown, false);
    assert.match(h.app.innerHTML, OTHERS);
  });

  it('API нет × referrer свой: пришли из приложения, даже если история короткая', async () => {
    const back = nativeBack();
    const h = open({ historyLength: 1, referrer: SAME_ORIGIN, miniAppBack: back });
    await tick(60);
    assert.equal(back.shown, true);
    back.press();
    assert.equal(h.ctx.history.left, 1);
  });

  it('API нет × referrer чужой: холодная ссылка, карточка корень', async () => {
    const back = nativeBack();
    const h = open({ historyLength: 5, referrer: FOREIGN, miniAppBack: back });
    await tick(60);
    assert.equal(back.shown, false);
    assert.match(h.app.innerHTML, OTHERS);
  });

  it('API нет × referrer пустой, но метка оболочки: пришли из приложения', async () => {
    const back = nativeBack();
    const h = open({
      historyLength: 1,
      referrer: '',
      sessionStore: { trainer_crm_showcase_from_app: '1' },
      miniAppBack: back,
    });
    await tick(60);
    assert.equal(back.shown, true);
    assert.equal(h.ctx.sessionStorage.getItem('trainer_crm_showcase_from_app'), null);
    back.press();
    assert.equal(h.ctx.history.left, 1);
  });

  it('свой referrer всё равно снимает метку оболочки', async () => {
    const h = open({
      historyLength: 1,
      referrer: SAME_ORIGIN,
      sessionStore: { trainer_crm_showcase_from_app: '1' },
    });
    await tick(60);
    assert.equal(h.ctx.sessionStorage.getItem('trainer_crm_showcase_from_app'), null);
  });

  it('холодный replace: свой referrer не делает карточку «из приложения»', async () => {
    const back = nativeBack();
    const h = open({
      historyLength: 2,
      referrer: SAME_ORIGIN,
      sessionStore: { trainer_crm_showcase_cold: '1', trainer_crm_showcase_from_app: '1' },
      miniAppBack: back,
    });
    await tick(60);
    assert.equal(back.shown, false);
    assert.match(h.app.innerHTML, OTHERS);
    assert.equal(h.ctx.sessionStorage.getItem('trainer_crm_showcase_cold'), null);
    assert.equal(h.ctx.sessionStorage.getItem('trainer_crm_showcase_from_app'), null);
  });

  it('каток открыл карточку, а canGoBack врёт false — стрелка есть и возвращает на арену', async () => {
    const back = nativeBack();
    const h = open({
      search: '?trainer_id=' + trainer.id + '&arena_id=9',
      historyLength: 2,
      navigation: { canGoBack: false },
      sessionStore: { trainer_crm_showcase_from_app: '1' },
      miniAppBack: back,
    });
    assert.equal(back.shown, true, 'стрелка включается сразу, скелет её не прячет');
    await tick(60);
    assert.equal(h.S.view, 'trainer');
    assert.equal(back.shown, true);
    assert.doesNotMatch(h.app.innerHTML, /Другие тренеры в/);
    back.press();
    assert.deepEqual(h.ctx.navigated, ['arena?ref=9']);
    assert.equal(h.ctx.history.left, 0);
  });

  it('API есть — referrer его не перебивает', async () => {
    const cold = nativeBack();
    const h = open({ historyLength: 1, referrer: SAME_ORIGIN, navigation: { canGoBack: false }, miniAppBack: cold });
    await tick(60);
    assert.equal(cold.shown, false);
    assert.match(h.app.innerHTML, OTHERS);
    const fromApp = nativeBack();
    const h2 = open({ historyLength: 5, referrer: '', navigation: { canGoBack: true }, miniAppBack: fromApp });
    await tick(60);
    assert.equal(fromApp.shown, true);
  });

  it('флаг выключен: same-origin referrer при history.length 1 не считается приходом', async () => {
    const h = open({ unified: false, historyLength: 1, referrer: SAME_ORIGIN });
    await tick(60);
    h.click({ 'data-act': 'back' });
    assert.equal(h.ctx.history.left, 0);
    assert.equal(h.S.view, 'list');
  });
});

describe('AC-001 · вход со слотом — «Назад» из записи на карточку этого тренера', () => {
  it('Telegram: запись → стрелка → карточка тренера 1 (корень, без стрелки, «Другие тренеры»)', async () => {
    const back = nativeBack();
    const h = open({ search: '?trainer_id=1&slot_id=101', miniAppBack: back });
    await tick(80);
    assert.equal(h.S.view, 'book');
    assert.equal(back.shown, true);
    back.press();
    assert.equal(h.S.view, 'trainer');
    assert.equal(h.S.trainer.id, 1);
    assert.equal(back.shown, false);
    assert.match(h.app.innerHTML, OTHERS);
  });

  it('браузер: своя «Назад» на записи снимает свою запись истории и возвращает на карточку', async () => {
    const h = open({ search: '?trainer_id=1&slot_id=101' });
    await tick(80);
    assert.equal(h.S.view, 'book');
    assert.equal(h.ctx.history.entries.length, 1);
    h.click({ 'data-act': 'back' });
    assert.equal(h.S.view, 'trainer');
    assert.equal(h.S.trainer.id, 1);
    assert.equal(h.ctx.history.entries.length, 0);
    assert.equal(h.ctx.history.left, 0);
  });
});

describe('AC-002 · после отправки записи история заменена', () => {
  async function booked(opts = {}) {
    let n = 0;
    const h = open({
      miniAppBack: opts.miniAppBack,
      routes: [
        // После записи 10:00 занято — второй ответ его уже не содержит.
        slotsRoute(() => (n++ === 0 ? STATES.A.slots : STATES.A.slots.slice(1))),
        { match: (c) => c.url.split('?')[0] === '/api/webapp/client/booking', reply: () => resp(200, { success: true }) },
      ],
    });
    await tick(60);
    h.click({ 'data-act': 'slot', 'data-slot': '101' });
    h.click({ 'data-act': 'pick', 'data-k': 'adult' });
    h.input('name', 'Анна', 'self');
    h.S.book.phone = '+375291112233';
    h.click({ 'data-act': 'submit' });
    await tick(60);
    assert.equal(h.S.view, 'sent');
    return h;
  }

  it('браузерная «назад» (popstate) с E — карточка, не форма; запись формы заменена', async () => {
    const h = await booked();
    assert.equal(JSON.stringify(h.ctx.history.state), '{"tswSent":1}');
    assert.equal(h.ctx.history.entries.length, 1, 'новой записи истории E не добавляет');
    h.ctx.history.back();
    assert.equal(h.S.view, 'trainer');
    assert.doesNotMatch(h.app.innerHTML, /Кто будет заниматься/);
  });

  it('«Назад» с E перезапрашивает окна: занятое 10:00 не стоит на главной кнопке', async () => {
    const back = nativeBack();
    const h = await booked({ miniAppBack: back });
    const before = slotCalls(h);
    back.press();
    await tick(40);
    assert.equal(h.S.view, 'trainer');
    assert.equal(slotCalls(h) - before, 1);
    assert.doesNotMatch(h.app.innerHTML, /data-slot="101"/);
    assert.match(h.app.innerHTML, /data-act="slot" data-slot="102">Записаться на сб, 11:30<\/button>/);
  });

  it('«Назад» с E сначала скелетон, не прежнее «сб, 10:00»', async () => {
    let n = 0;
    const back = nativeBack();
    const h = open({
      miniAppBack: back,
      routes: [
        {
          match: (c) => c.url.split('?')[0] === '/api/webapp/client/slots',
          reply: () => {
            n += 1;
            const slots = n === 1 ? STATES.A.slots : STATES.A.slots.slice(1);
            return resp(200, { slots }, n === 1 ? 0 : 250);
          },
        },
        { match: (c) => c.url.split('?')[0] === '/api/webapp/client/booking', reply: () => resp(200, { success: true }) },
      ],
    });
    await tick(60);
    h.click({ 'data-act': 'slot', 'data-slot': '101' });
    h.click({ 'data-act': 'pick', 'data-k': 'adult' });
    h.input('name', 'Анна', 'self');
    h.S.book.phone = '+375291112233';
    h.click({ 'data-act': 'submit' });
    await tick(60);
    assert.equal(h.S.view, 'sent');
    back.press();
    assert.equal(h.S.view, 'trainer');
    assert.equal(h.S.slots, null);
    assert.match(h.app.innerHTML, /class="tc-sk"/);
    assert.doesNotMatch(h.app.innerHTML, /data-slot="101"|Записаться на сб, 10:00/);
    await tick(320);
    assert.match(h.app.innerHTML, /data-act="slot" data-slot="102">Записаться на сб, 11:30<\/button>/);
  });
});

describe('нативная стрелка и «висящие» записи истории', () => {
  it('из приложения: неделя → стрелка → стрелка — один уход со страницы, без цикла и без списка', async () => {
    const back = nativeBack();
    const h = open({ historyLength: 2, referrer: SAME_ORIGIN, miniAppBack: back });
    await tick(60);
    h.click({ 'data-act': 'week' });
    assert.equal(h.S.view, 'week');
    assert.equal(h.ctx.history.entries.length, 1);
    back.press();
    assert.equal(h.S.view, 'trainer');
    assert.equal(h.ctx.history.entries.length, 1, 'нативная стрелка запись не снимает');
    back.press();
    assert.equal(h.ctx.history.left, 1, 'ушли один раз');
    assert.equal(h.ctx.history.backs, 2, 'своя запись + уход');
    assert.equal(h.S.view, 'trainer', 'список по пути не мелькнул');
  });
});

describe('syncUrl', () => {
  it('без entry в адресе фильтр всё равно снимает одноразовые параметры и entry не появляется', async () => {
    const h = open({ search: '?trainer_id=1&slot_id=5&service_id=3&via=p3&intent=save&city_id=1' });
    await tick(60);
    h.click({ 'data-act': 'to-list' });
    h.click({ 'data-act': 'tab', 'data-key': 's-nulya' });
    const q = new URLSearchParams(String(h.ctx.history.url).split('?')[1] || '');
    for (const k of ['trainer_id', 'slot_id', 'service_id', 'via', 'intent', 'entry']) assert.equal(q.has(k), false, k);
    assert.equal(q.get('tab'), 's-nulya');
    assert.equal(q.get('city_id'), '1');
  });

  it('фильтр витрины пишет адрес заменой: без trainer_id/slot_id/service_id/via/intent/entry, state прежний', async () => {
    const h = open({ search: '?trainer_id=1&slot_id=5&service_id=3&via=p3&intent=save&entry=rebook&city_id=1' });
    await tick(60);
    h.click({ 'data-act': 'to-list' });
    const state = h.ctx.history.state;
    const entries = h.ctx.history.entries.length;
    h.click({ 'data-act': 'tab', 'data-key': 's-nulya' });
    const q = new URLSearchParams(String(h.ctx.history.url).split('?')[1] || '');
    for (const k of ['trainer_id', 'slot_id', 'service_id', 'via', 'intent', 'entry']) assert.equal(q.has(k), false, k);
    assert.equal(q.get('tab'), 's-nulya');
    assert.equal(q.get('city_id'), '1');
    assert.equal(h.ctx.history.state, state);
    assert.equal(h.ctx.history.entries.length, entries, 'в историю не добавляет');
  });
});
