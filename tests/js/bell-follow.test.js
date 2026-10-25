/**
 * Колокольчик сайта (static/webapp/bell-follow.js): разрешение писать и тексты.
 * Нативный диалог Telegram здесь не воспроизводится: window.Telegram.WebApp — мок,
 * а requestWriteAccess вызывает колбэк так, как это делает Telegram после закрытия диалога.
 *
 * Run: node --test tests/js/bell-follow.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const B = require('../../static/webapp/bell-follow.js');

const DONE = 'Готово. Напишем, когда у «Юность» появится расписание.';
const DECLINED = 'Подписка сохранена, но уведомления выключены.';

/** Мок WebApp. answers — что отвечает диалог на 1-й, 2-й… вызов requestWriteAccess. */
function makeTg(opts) {
  opts = opts || {};
  const tg = {
    initData: 'x',
    initDataUnsafe: { user: Object.assign({ id: 111 }, opts.user || {}) },
    popups: [],
    requests: 0,
    isVersionAtLeast: opts.version === undefined ? () => true : (v) => opts.version >= parseFloat(v),
    // нажатия в попапах: по очереди; по умолчанию закрыть
    taps: (opts.taps || []).slice(),
    showPopup(params, cb) {
      tg.popups.push(params);
      const tap = tg.taps.length ? tg.taps.shift() : null;
      cb(tap);
    },
  };
  if (!opts.noMethod) {
    const answers = (opts.answers || [true]).slice();
    tg.requestWriteAccess = function (cb) {
      tg.requests += 1;
      if (opts.throws) throw new Error('boom');
      cb(answers.length ? answers.shift() : false);
    };
  }
  return tg;
}

function makePost(log, overrides) {
  return function (path, body) {
    log.push({ path, body });
    if (overrides && overrides[path]) return Promise.resolve(overrides[path]);
    if (path === '/api/webapp/client/bell-follow') {
      return Promise.resolve({ ok: true, status: 200, json: { arena_name: 'Юность', created: true } });
    }
    return Promise.resolve({ ok: true, status: 200, json: { ok: true } });
  };
}

function storage() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
}

function go(tg, extra) {
  const log = [];
  const post = makePost(log, extra && extra.responses);
  const p = B.run({ tg, startParam: (extra && extra.sp) || 'follow_arena_7', storage: storage(), post });
  return p.then((res) => ({ res, log }));
}

const outcomes = (log) => log.filter((c) => c.path.endsWith('/outcome')).map((c) => [c.body.outcome, c.body.retry]);

describe('разбор start_param', () => {
  it('follow_arena_N -> id; arena_N и мусор не колокольчик', () => {
    assert.equal(B.parseFollowStartParam('follow_arena_42'), '42');
    assert.equal(B.parseFollowStartParam('arena_42'), null);
    assert.equal(B.parseFollowStartParam('follow_arena_0'), null);
    assert.equal(B.parseFollowStartParam('follow_arena_42_s_1'), null);
    assert.equal(B.parseFollowStartParam(''), null);
  });
  it('arenaStartParam: колокольчик -> arena_N, остальное как есть', () => {
    assert.equal(B.arenaStartParam('follow_arena_42'), 'arena_42');
    assert.equal(B.arenaStartParam('arena_42_s_9'), 'arena_42_s_9');
    assert.equal(B.arenaStartParam('catalog_3'), 'catalog_3');
  });
});

describe('writeAccessState', () => {
  it('allows_write_to_pm === true -> already, без запроса', () => {
    assert.equal(B.writeAccessState(makeTg({ user: { allows_write_to_pm: true } })), 'already');
  });
  it('false / нет поля -> askable', () => {
    assert.equal(B.writeAccessState(makeTg({ user: { allows_write_to_pm: false } })), 'askable');
    assert.equal(B.writeAccessState(makeTg()), 'askable');
  });
  it('метода нет или SDK старше 6.9 -> unsupported', () => {
    assert.equal(B.writeAccessState(makeTg({ noMethod: true })), 'unsupported');
    assert.equal(B.writeAccessState(makeTg({ version: 6.7 })), 'unsupported');
    assert.equal(B.writeAccessState(null), 'unsupported');
  });
});

describe('run: исходы', () => {
  it('уже разрешено: диалог не показываем, успех, исход already', async () => {
    const tg = makeTg({ user: { allows_write_to_pm: true } });
    const { res, log } = await go(tg);
    assert.equal(tg.requests, 0);
    assert.equal(res.status, 'done');
    assert.equal(tg.popups[0].message, DONE);
    assert.deepEqual(outcomes(log), [['already', false]]);
    assert.equal(log[0].path, '/api/webapp/client/bell-follow');
    assert.deepEqual(log[0].body, { arena_id: 7 });
  });

  it('разрешил: ровно один запрос, успех, исход granted', async () => {
    const tg = makeTg({ answers: [true] });
    const { res, log } = await go(tg);
    assert.equal(tg.requests, 1);
    assert.equal(res.status, 'done');
    assert.equal(tg.popups.length, 1);
    assert.equal(tg.popups[0].message, DONE);
    assert.deepEqual(outcomes(log), [['granted', false]]);
  });

  it('отказал: успеха нет, текст про выключенные уведомления с кнопкой, исход denied', async () => {
    const tg = makeTg({ answers: [false] });
    const { res, log } = await go(tg);
    assert.equal(res.status, 'declined');
    assert.equal(tg.popups.length, 1);
    assert.equal(tg.popups[0].message, DECLINED);
    assert.ok(tg.popups.every((p) => p.message !== DONE));
    assert.deepEqual(tg.popups[0].buttons[0], { id: 'enable', type: 'default', text: 'Включить уведомления' });
    assert.deepEqual(outcomes(log), [['denied', false]]);
  });

  it('колбэк с не-true (undefined) не считается разрешением', async () => {
    const tg = makeTg({ answers: [undefined] });
    const { res } = await go(tg);
    assert.equal(res.status, 'declined');
    assert.ok(tg.popups.every((p) => p.message !== DONE));
  });

  it('повтор по кнопке: разрешил со второго раза -> успех, исходы denied, granted(retry)', async () => {
    const tg = makeTg({ answers: [false, true], taps: ['enable'] });
    const { res, log } = await go(tg);
    assert.equal(tg.requests, 2);
    assert.equal(res.status, 'done');
    assert.deepEqual(tg.popups.map((p) => p.message), [DECLINED, DONE]);
    assert.deepEqual(outcomes(log), [['denied', false], ['granted', true]]);
  });

  it('повтор по кнопке не помог (диалог не показался, колбэк false): честно остаёмся на «выключены»', async () => {
    const tg = makeTg({ answers: [false, false], taps: ['enable'] });
    const { res, log } = await go(tg);
    assert.equal(tg.requests, 2);
    assert.equal(res.status, 'declined');
    assert.deepEqual(tg.popups.map((p) => p.message), [DECLINED, DECLINED]);
    assert.deepEqual(outcomes(log), [['denied', false], ['denied', true]]);
  });

  it('метода нет: подписка сохранена, сообщение «выключены», кнопки повтора нет (нажимать нечем), исход unsupported', async () => {
    const tg = makeTg({ noMethod: true });
    const { res, log } = await go(tg);
    assert.equal(res.status, 'declined');
    assert.equal(tg.popups[0].message, DECLINED);
    assert.deepEqual(tg.popups[0].buttons, [{ type: 'close' }]);
    assert.deepEqual(outcomes(log), [['unsupported', false]]);
  });

  it('requestWriteAccess бросает: страница не падает, считаем unsupported-исходом denied-текста', async () => {
    const tg = makeTg({ throws: true });
    const { res, log } = await go(tg);
    assert.equal(res.status, 'declined');
    assert.ok(tg.popups.every((p) => p.message !== DONE));
    assert.deepEqual(outcomes(log), [['unsupported', false]]);
  });
});

describe('run: не Telegram и защёлки', () => {
  it('нет Telegram.WebApp / нет initData: ничего не делаем, сеть не трогаем', async () => {
    for (const tg of [null, { initData: '', initDataUnsafe: {} }]) {
      const { res, log } = await go(tg);
      assert.equal(res.status, 'skipped');
      assert.equal(log.length, 0);
    }
  });

  it('отрицательный суррогатный id (MAX/VK): пропуск целиком, без запроса разрешения', async () => {
    const tg = makeTg({ user: { id: -1000042 } });
    const { res, log } = await go(tg);
    assert.equal(res.status, 'skipped');
    assert.equal(tg.requests, 0);
    assert.equal(tg.popups.length, 0);
    assert.equal(log.length, 0);
  });

  it('сервер ответил 409 channel_unsupported: тихий пропуск, диалога нет', async () => {
    const tg = makeTg();
    const { res, log } = await go(tg, {
      responses: { '/api/webapp/client/bell-follow': { ok: false, status: 409, json: { detail: 'channel_unsupported' } } },
    });
    assert.equal(res.status, 'skipped');
    assert.equal(tg.requests, 0);
    assert.equal(tg.popups.length, 0);
    assert.equal(outcomes(log).length, 0);
  });

  it('подписка не сохранилась: диалог разрешения не показываем, успеха нет', async () => {
    const tg = makeTg();
    const { res } = await go(tg, {
      responses: { '/api/webapp/client/bell-follow': { ok: false, status: 500, json: null } },
    });
    assert.equal(res.status, 'error');
    assert.equal(tg.requests, 0);
    assert.deepEqual(tg.popups.map((p) => p.message), ['Не удалось сохранить подписку.']);
  });

  it('не колокольчик (arena_7): не трогаем ничего', async () => {
    const tg = makeTg();
    const { res, log } = await go(tg, { sp: 'arena_7' });
    assert.equal(res.status, 'not_follow');
    assert.equal(log.length, 0);
    assert.equal(tg.requests, 0);
  });

  it('повторный вход в той же сессии не просит снова', async () => {
    const tg = makeTg({ answers: [true, true] });
    const st = storage();
    const log = [];
    const post = makePost(log);
    const first = await B.run({ tg, startParam: 'follow_arena_7', storage: st, post });
    const second = await B.run({ tg, startParam: 'follow_arena_7', storage: st, post });
    assert.equal(first.status, 'done');
    assert.equal(second.status, 'already_handled');
    assert.equal(tg.requests, 1);
  });

  it('showPopup бросает (попап уже открыт): сценарий завершается без исключения', async () => {
    const tg = makeTg({ answers: [true] });
    tg.showPopup = () => {
      throw new Error('WebAppPopupOpened');
    };
    const { res } = await go(tg);
    assert.equal(res.status, 'done');
  });
});
