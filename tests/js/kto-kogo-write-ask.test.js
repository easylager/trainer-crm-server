/**
 * «Кто кого»: после первого хода — подводка «Итог — в чат» и системное окно requestWriteAccess.
 * Решение «показывать ли» и ответ на подводку — чистые функции kto-kogo-screens-model.js;
 * состояние Telegram — настоящий write-access.js на подменённом WebApp.
 *
 * Run: node --test tests/js/kto-kogo-write-ask.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
require('../../static/webapp/kto-kogo-model.js');
const S = require('../../static/webapp/kto-kogo-screens-model.js');
const WA = require('../../static/webapp/write-access.js');

const root = path.join(__dirname, '../../static/webapp');
const NBSP = ' ';

/** Telegram WebApp: по умолчанию игроку боту писать нельзя, окно разрешения есть. */
function makeTg(over = {}) {
  const calls = [];
  const tg = {
    initData: 'query_id=1&user=%7B%7D&hash=x',
    initDataUnsafe: { user: { id: 42, allows_write_to_pm: false } },
    isVersionAtLeast: () => true,
    requestWriteAccess(cb) {
      calls.push(cb);
      if (over.throws) throw new Error('WebAppMethodUnsupported');
      cb(over.granted === undefined ? true : over.granted);
    },
    ...over.tg,
  };
  if (over.allows !== undefined) tg.initDataUnsafe.user.allows_write_to_pm = over.allows;
  return { tg, calls };
}

function memStorage() {
  const data = {};
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = String(v);
    },
  };
}

const brokenStorage = {
  getItem() {
    throw new Error('SecurityError');
  },
  setItem() {
    throw new Error('QuotaExceededError');
  },
};

function ctx(over = {}) {
  return { first: true, tg: makeTg().tg, wa: WA, asked: false, remind: true, sheet: null, ...over };
}

describe('первый ход', () => {
  const fresh = { awaiting: 0, me: null, saved: 0, matches: [{ id: 1, my_pick: null }, { id: 2 }], cache: {} };

  it('ходов нигде нет — первый', () => {
    assert.equal(S.isFirstPick(fresh), true);
  });
  it('awaiting не число (список не загрузился) — «не знаем», не первый', () => {
    assert.equal(S.isFirstPick({ ...fresh, awaiting: null }), false);
    assert.equal(S.isFirstPick({ ...fresh, awaiting: undefined }), false);
    assert.equal(S.isFirstPick({}), false);
  });
  it('есть ходы на несыгранные матчи — не первый', () => {
    assert.equal(S.isFirstPick({ ...fresh, awaiting: 2 }), false);
  });
  it('есть строка сезона (очки за сыгранные) — не первый', () => {
    assert.equal(S.isFirstPick({ ...fresh, me: { rank: 5, points: 20, exact: 0, played: 1 } }), false);
  });
  it('ход в загруженном матче или в кэше — не первый', () => {
    assert.equal(S.isFirstPick({ ...fresh, matches: [{ id: 1, my_pick: { side: 'home' } }] }), false);
    assert.equal(S.isFirstPick({ ...fresh, cache: { 9: { id: 9, my_pick: { side: 'away' } } } }), false);
  });
  it('в этой сессии сервер уже принял ход — не первый', () => {
    assert.equal(S.isFirstPick({ ...fresh, saved: 1 }), false);
  });
});

describe('показывать ли подводку', () => {
  it('все условия выполнены — показываем', () => {
    assert.equal(S.shouldAskWrite(ctx()), true);
  });
  it('(а) не первый ход — нет', () => {
    assert.equal(S.shouldAskWrite(ctx({ first: false })), false);
    assert.equal(S.shouldAskWrite(ctx({ first: undefined })), false);
  });
  it('(б) нет Telegram, нет метода, старая версия SDK, нет write-access.js — нет', () => {
    assert.equal(S.shouldAskWrite(ctx({ tg: null })), false);
    assert.equal(S.shouldAskWrite(ctx({ tg: undefined })), false);
    assert.equal(S.shouldAskWrite(ctx({ tg: makeTg({ tg: { requestWriteAccess: undefined } }).tg })), false);
    assert.equal(S.shouldAskWrite(ctx({ tg: makeTg({ tg: { isVersionAtLeast: () => false } }).tg })), false);
    assert.equal(S.shouldAskWrite(ctx({ tg: makeTg({ tg: { initData: '' } }).tg })), false, 'браузер без initData');
    assert.equal(S.shouldAskWrite(ctx({ wa: null })), false);
    assert.equal(S.shouldAskWrite(ctx({ wa: { writeAccessState: () => { throw new Error('x'); } } })), false);
  });
  it('(в) боту уже можно писать (allows_write_to_pm === true) — нет', () => {
    assert.equal(S.shouldAskWrite(ctx({ tg: makeTg({ allows: true }).tg })), false);
    assert.equal(S.shouldAskWrite(ctx({ tg: makeTg({ allows: undefined, tg: { initDataUnsafe: { user: { id: 7 } } } }).tg })), true, 'поля нет — спрашиваем');
  });
  it('(г) на устройстве уже спрашивали — нет', () => {
    assert.equal(S.shouldAskWrite(ctx({ asked: true })), false);
  });
  it('(д) игрок сам выключил «Сообщения в чате» — нет; по умолчанию (true) и не загрузились (null) — спрашиваем', () => {
    assert.equal(S.shouldAskWrite(ctx({ remind: false })), false);
    assert.equal(S.shouldAskWrite(ctx({ remind: true })), true, 'у нового игрока true — значение по умолчанию, писать ему всё равно нельзя');
    assert.equal(S.shouldAskWrite(ctx({ remind: null })), true);
  });
  it('открыта другая шторка — не перебиваем', () => {
    assert.equal(S.shouldAskWrite(ctx({ sheet: { kind: 'points' } })), false);
  });
});

describe('флаг «спрашивали»', () => {
  it('живёт в localStorage', () => {
    const st = memStorage();
    const memo = S.writeAskMemo(st);
    assert.equal(memo.asked(), false);
    memo.mark();
    assert.equal(st.data[S.WRITE_ASK_KEY], '1');
    assert.equal(S.writeAskMemo(st).asked(), true, 'новая сессия на том же устройстве');
  });
  it('хранилище бросает или его нет — помним до конца сессии, не падаем', () => {
    for (const st of [brokenStorage, null, undefined]) {
      const memo = S.writeAskMemo(st);
      assert.equal(memo.asked(), false);
      assert.doesNotThrow(() => memo.mark());
      assert.equal(memo.asked(), true);
    }
  });
});

describe('ответ на подводку', () => {
  it('«Да, писать в чат» и согласие: окно один раз, сохраняем, больше не спрашиваем', async () => {
    const { tg, calls } = makeTg({ granted: true });
    const memo = S.writeAskMemo(memStorage());
    let saved = 0;
    const out = await S.answerWriteAsk('allow', { memo, tg, wa: WA, save: () => saved++ });
    assert.equal(out, 'granted');
    assert.equal(calls.length, 1);
    assert.equal(saved, 1);
    assert.equal(S.shouldAskWrite(ctx({ tg, asked: memo.asked() })), false);
  });
  it('«Да, писать в чат» и отказ в окне Telegram: молча, без сохранения, флаг стоит', async () => {
    const { tg, calls } = makeTg({ granted: false });
    const memo = S.writeAskMemo(memStorage());
    let saved = 0;
    const out = await S.answerWriteAsk('allow', { memo, tg, wa: WA, save: () => saved++ });
    assert.equal(out, 'denied');
    assert.equal(calls.length, 1);
    assert.equal(saved, 0);
    assert.equal(memo.asked(), true);
  });
  it('«Не сейчас»: окна нет, сохранения нет, флаг стоит', async () => {
    const { tg, calls } = makeTg();
    const memo = S.writeAskMemo(memStorage());
    let saved = 0;
    assert.equal(await S.answerWriteAsk('later', { memo, tg, wa: WA, save: () => saved++ }), 'later');
    assert.equal(calls.length, 0);
    assert.equal(saved, 0);
    assert.equal(memo.asked(), true);
  });
  it('requestWriteAccess бросает исключение — промис не отклоняется, сохранения нет', async () => {
    const { tg } = makeTg({ throws: true });
    const memo = S.writeAskMemo(memStorage());
    let saved = 0;
    const out = await S.answerWriteAsk('allow', { memo, tg, wa: WA, save: () => saved++ });
    assert.equal(out, 'unsupported');
    assert.equal(saved, 0);
    assert.equal(memo.asked(), true);
  });
  it('сломанный wa, сбой save, сломанная память — наружу ничего не вылетает', async () => {
    const { tg } = makeTg();
    const badMemo = { mark() { throw new Error('x'); } };
    assert.equal(await S.answerWriteAsk('allow', { memo: badMemo, tg, wa: null }), 'error');
    assert.equal(await S.answerWriteAsk('allow', { tg, wa: { requestWriteAccess: () => Promise.reject(new Error('x')) } }), 'error');
    assert.equal(await S.answerWriteAsk('allow', { tg, wa: WA, save: () => { throw new Error('x'); } }), 'granted');
    assert.equal(await S.answerWriteAsk(), 'later');
  });
  it('нет tg — окно не открывается, промис не отклоняется', async () => {
    let saved = 0;
    assert.equal(await S.answerWriteAsk('allow', { tg: null, wa: WA, save: () => saved++ }), 'unsupported');
    assert.equal(saved, 0);
  });
  it('повторный показ: после любого ответа подводка больше не нужна', async () => {
    const st = memStorage();
    const memo = S.writeAskMemo(st);
    assert.equal(S.shouldAskWrite(ctx({ asked: memo.asked() })), true);
    await S.answerWriteAsk('later', { memo });
    assert.equal(S.shouldAskWrite(ctx({ asked: memo.asked() })), false);
    assert.equal(S.shouldAskWrite(ctx({ asked: S.writeAskMemo(st).asked() })), false);
  });
});

describe('тексты', () => {
  it('голос игры: на «ты», без эмодзи и запретных слов, неразрывные пробелы', () => {
    const T = S.WRITE_ASK;
    assert.equal(T.title, 'Итог' + NBSP + '— в чат');
    assert.equal(T.text.replace(/ /g, ' '), 'Напишем, чем закончился матч, и напомним о следующем ходе. Не чаще раза в день, ночью не пишем.');
    assert.equal(T.allow, 'Да, писать в\u00a0чат');
    assert.equal(T.later.replace(/ /g, ' '), 'Не сейчас');
    const all = Object.values(T).join(' ');
    assert.ok(!/ставк|срок|источник|\p{Extended_Pictographic}/iu.test(all));
  });
});

describe('подключение', () => {
  const read = (f) => fs.readFileSync(path.join(root, f), 'utf8');
  const html = read('kto-kogo.html');
  const core = read('kto-kogo.js');
  const board = read('kto-kogo-board.js');

  it('write-access.js подключён до экранов игры', () => {
    const order = [...html.matchAll(/(write-access|kto-kogo[a-z-]*)\.js/g)].map((m) => m[0]);
    assert.ok(order.indexOf('write-access.js') >= 0);
    assert.ok(order.indexOf('write-access.js') < order.indexOf('kto-kogo-board.js'));
  });
  it('ход: просьба — только после ответа сервера и под try/catch', () => {
    const i = core.indexOf('function sendPick');
    const body = core.slice(i, core.indexOf('function pickSide', i));
    const ok = body.indexOf('.then(function (data)');
    const hook = body.indexOf('afterFirstPick(owner)');
    assert.ok(ok > 0 && hook > ok, 'после успешного ответа');
    assert.ok(hook < body.indexOf('.catch('), 'не в ветке ошибки');
    assert.ok(/try \{ window\.KK\.afterFirstPick\(owner\); \} catch/.test(body));
    assert.ok(/try \{\s*first = S\.isFirstPick/.test(body));
  });
  it('«Да, писать в чат» сохраняет тем же путём, что тумблер «Сообщения в чате»', () => {
    assert.ok(/function setRemind[\s\S]*?saveRemind\(on\)/.test(board));
    assert.ok(/save: function \(\) \{ saveRemind\(true\); \}/.test(board));
    assert.ok(/K\.sheet\(T\.title/.test(board), 'общая шторка игры');
  });
});
