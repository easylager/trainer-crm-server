/**
 * TASK-360: «Кто кого» — монетка. Алгоритм выпадения, шкала анимации, машина состояний, пропуск,
 * короткая версия, reduced motion, вибрация, тексты.
 *
 * Run: TZ=UTC node --test tests/js/kto-kogo-coin-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const C = require('../../static/webapp/kto-kogo-coin-model.js');

const NBSP = ' ';
const root = path.join(__dirname, '../../static/webapp');

/** Генератор по списку: отдаёт значения по очереди, дальше — последнее. */
function seq(...values) {
  let i = 0;
  return () => values[Math.min(i++, values.length - 1)];
}

/** Детерминированный генератор (mulberry32) для статистики. */
function seeded(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Поддельные часы: setTimer/now/advance вместо реального времени. */
function clock() {
  let t = 0;
  let id = 0;
  let timers = [];
  return {
    now: () => t,
    setTimer: (fn, ms) => {
      timers.push({ id: ++id, at: t + ms, fn });
      return id;
    },
    clearTimer: (x) => {
      timers = timers.filter((q) => q.id !== x);
    },
    advance(ms) {
      const end = t + ms;
      for (;;) {
        timers.sort((a, b) => a.at - b.at || a.id - b.id);
        const next = timers[0];
        if (!next || next.at > end) break;
        timers.shift();
        t = Math.max(t, next.at);
        next.fn();
      }
      t = end;
    },
    pending: () => timers.length,
  };
}

/** Монета на поддельных часах с журналом событий. */
function rig(opts) {
  opts = opts || {};
  const ck = clock();
  const log = { change: [], haptic: [], finish: [] };
  const coin = C.createCoin({
    rng: opts.rng || seq(0.1, 0.0), // хозяева, 3:1
    now: ck.now,
    setTimer: ck.setTimer,
    clearTimer: ck.clearTimer,
    reducedMotion: () => !!opts.reduced,
    shortAfter: opts.shortAfter,
    onChange: (key) => log.change.push({ key, at: ck.now(), frame: coin.frame(key) }),
    onHaptic: (kind) => log.haptic.push({ kind, at: ck.now() }),
    onFinish: (key, target) => log.finish.push({ key, target, at: ck.now() }),
  });
  return { ck, log, coin };
}

describe('алгоритм выпадения', () => {
  it('таблица: веса в сумме 100, победитель с большим счётом, ничьих нет', () => {
    assert.equal(C.SCORES.reduce((a, r) => a + r[2], 0), 100);
    for (const [w, l, weight] of C.SCORES) {
      assert.ok(w > l, `${w}:${l}`);
      assert.ok(weight > 0);
    }
    const keys = C.SCORES.map((r) => r[0] + ':' + r[1]);
    assert.equal(new Set(keys).size, keys.length, 'без повторов');
    for (const k of ['3:1', '3:2', '2:1', '4:1', '4:2', '1:0']) assert.ok(keys.includes(k), k);
  });

  it('первый вызов генератора — сторона: меньше 0,52 — хозяева, иначе гости', () => {
    assert.equal(C.draw(seq(0, 0)).side, 'home');
    assert.equal(C.draw(seq(0.5199, 0)).side, 'home');
    assert.equal(C.draw(seq(0.52, 0)).side, 'away');
    assert.equal(C.draw(seq(0.9999, 0)).side, 'away');
  });

  it('второй вызов — счёт по весам: начало таблицы и самый край', () => {
    assert.deepEqual(C.draw(seq(0, 0)), { side: 'home', home: 3, away: 1 });
    assert.deepEqual(C.draw(seq(0.9, 0)), { side: 'away', home: 1, away: 3 }); // у гостей счёт зеркалится
    assert.deepEqual(C.draw(seq(0, 0.999999)), { side: 'home', home: 6, away: 3 });
    // 14 + 14 = 28 → граница между 3:2 и 2:1
    assert.deepEqual(C.draw(seq(0, 0.2799)), { side: 'home', home: 3, away: 2 });
    assert.deepEqual(C.draw(seq(0, 0.28)), { side: 'home', home: 2, away: 1 });
  });

  it('мусор вместо случайного числа не роняет бросок', () => {
    for (const bad of [1, 5, -1, NaN, undefined, null, 'x']) {
      const r = C.draw(() => bad);
      assert.ok(r.side === 'home' || r.side === 'away');
      assert.notEqual(r.home, r.away);
    }
  });

  it('20 000 бросков: ничьих нет, победитель согласован со счётом, хозяева ≈ 52 %', () => {
    const rng = seeded(360);
    const seen = new Map();
    let home = 0;
    const N = 20000;
    for (let i = 0; i < N; i++) {
      const r = C.draw(rng);
      assert.notEqual(r.home, r.away, 'ничья');
      assert.equal(r.side, r.home > r.away ? 'home' : 'away', 'победитель = больший счёт');
      assert.ok(Number.isInteger(r.home) && Number.isInteger(r.away) && r.home >= 0 && r.away >= 0);
      if (r.side === 'home') home++;
      const key = Math.max(r.home, r.away) + ':' + Math.min(r.home, r.away);
      seen.set(key, (seen.get(key) || 0) + 1);
    }
    assert.ok(home / N > 0.5 && home / N < 0.54, 'хозяева ' + home / N);
    // Все 14 результатов выпадают, частые — чаще редких.
    assert.equal(seen.size, C.SCORES.length);
    assert.ok(seen.get('3:1') > seen.get('5:3') * 2);
    assert.ok(seen.get('2:1') > seen.get('6:3') * 5);
    for (const key of seen.keys()) assert.ok(C.SCORES.some((r) => r[0] + ':' + r[1] === key), key);
  });

  it('без подмены генератора берёт Math.random', () => {
    const real = Math.random;
    try {
      Math.random = () => 0;
      assert.deepEqual(C.draw(), { side: 'home', home: 3, away: 1 });
    } finally {
      Math.random = real;
    }
  });
});

describe('шкала броска', () => {
  const target = { side: 'home', home: 3, away: 1 };

  it('фазы по порядку: бросок → выбор → барабаны → готово', () => {
    const p = C.plan(target);
    const order = [];
    for (const s of p.steps) if (order[order.length - 1] !== s.phase) order.push(s.phase);
    assert.deepEqual(order, ['flip', 'choose', 'reels', 'done']);
    const ats = p.steps.map((s) => s.at);
    assert.deepEqual(ats, [...ats].sort((a, b) => a - b), 'шаги идут по времени');
  });

  it('тайминги прототипа: бросок 1,1 с, барабаны встают к 5,76 с, хозяева раньше гостей', () => {
    const p = C.plan(target);
    assert.equal(p.flipMs, 1100);
    assert.equal(p.total, 5760);
    assert.equal(p.runAt, 3820);
    assert.equal(p.steps.find((s) => s.phase === 'choose').at, 1100);
    assert.equal(p.reelMs.home, 1300);
    assert.equal(p.reelMs.away, 1900);
    assert.ok(p.reelMs.home < p.reelMs.away);
    assert.ok(p.runAt + p.reelMs.away <= p.total, 'гости встают до наклейки');
  });

  it('рулетка начинается и кончается на победителе, команды сменяют друг друга, пауза растёт', () => {
    for (const side of ['home', 'away']) {
      const p = C.plan({ side, home: 3, away: 1 });
      const lit = p.steps.filter((s) => s.phase === 'choose' && s.hl);
      assert.equal(lit.length, C.TIMING.gaps.length);
      assert.equal(lit[0].hl, side);
      assert.equal(lit[lit.length - 1].hl, side);
      for (let i = 1; i < lit.length; i++) assert.notEqual(lit[i].hl, lit[i - 1].hl);
      const gaps = lit.map((s, i) => (i ? s.at - lit[i - 1].at : s.at - 1100));
      for (let i = 1; i < gaps.length; i++) assert.ok(gaps[i] >= gaps[i - 1], 'рулетка замедляется');
    }
  });

  it('победитель остаётся один до барабанов; барабаны крутятся только после «run»', () => {
    const p = C.plan(target);
    const f = (t) => C.frameAt(p, t);
    assert.equal(f(0).phase, 'flip');
    assert.equal(f(0).side, null);
    assert.equal(f(1099).phase, 'flip');
    assert.equal(f(1100).phase, 'choose');
    assert.equal(f(1100).hl, null);
    const last = p.steps.filter((s) => s.hl).pop();
    assert.equal(f(last.at + 100).side, null, 'пока подсветка бегает, победитель не назначен');
    assert.equal(f(last.at + 350).side, 'home');
    assert.equal(f(last.at + 350).hl, null);
    assert.equal(f(last.at + 749).phase, 'choose');
    assert.equal(f(last.at + 750).phase, 'reels');
    assert.equal(f(last.at + 750).run, false);
    assert.equal(f(p.runAt).run, true);
    assert.equal(f(p.runAt + 500).reelMs, 500);
    assert.equal(f(p.total - 1).stamp, false);
    assert.equal(f(p.total).phase, 'done');
    assert.equal(f(p.total).stamp, true);
    assert.equal(f(p.total + 10000).phase, 'done');
    assert.equal(f(-5).phase, 'flip');
  });

  it('короткая версия вдвое быстрее по всем отметкам', () => {
    const full = C.plan(target);
    const fast = C.plan(target, { short: true });
    assert.equal(fast.short, true);
    assert.equal(fast.total, full.total / 2);
    assert.equal(fast.flipMs, 550);
    assert.equal(fast.reelMs.home, 650);
    assert.equal(fast.reelMs.away, 950);
    assert.equal(fast.steps.length, full.steps.length);
    fast.steps.forEach((s, i) => {
      assert.equal(s.phase, full.steps[i].phase);
      assert.ok(Math.abs(s.at - full.steps[i].at / 2) <= 0.01);
    });
  });

  it('вибрация: лёгкий удар на стопе каждого барабана и «успех» в самом конце', () => {
    const p = C.plan(target);
    assert.deepEqual(p.haptics.map((x) => x.kind), ['impact', 'impact', 'success']);
    assert.equal(p.haptics[0].at, p.runAt + p.reelMs.home);
    assert.equal(p.haptics[1].at, p.runAt + p.reelMs.away);
    assert.equal(p.haptics[2].at, p.total);
    assert.ok(p.haptics[0].at < p.haptics[1].at && p.haptics[1].at < p.haptics[2].at);
  });

  it('nextMark ведёт по шагам и вибрации, после конца — null', () => {
    const p = C.plan(target);
    assert.equal(C.nextMark(p, 0), 1100);
    assert.equal(C.nextMark(p, p.total - 1), p.total);
    assert.equal(C.nextMark(p, p.total), null);
    assert.ok(p.marks.includes(p.haptics[0].at), 'стоп барабана — тоже отметка');
  });
});

describe('машина состояний', () => {
  it('бросок идёт по фазам и один раз отдаёт результат на сохранение', () => {
    const { ck, log, coin } = rig();
    assert.equal(coin.busy(), false);
    assert.equal(coin.press(7), 'start');
    assert.equal(coin.busy(7), true);
    assert.equal(coin.busy(8), false);
    assert.equal(coin.frame(7).phase, 'flip');
    assert.deepEqual(log.finish, [], 'пока крутится, ход не сохранён');
    ck.advance(1099);
    assert.equal(coin.frame(7).phase, 'flip');
    ck.advance(1);
    assert.equal(coin.frame(7).phase, 'choose');
    ck.advance(5760 - 1100);
    assert.equal(coin.busy(), false);
    assert.equal(coin.frame(7), null);
    assert.equal(log.finish.length, 1);
    assert.deepEqual(log.finish[0], { key: 7, target: { side: 'home', home: 3, away: 1 }, at: 5760 });
    assert.deepEqual(coin.result(7), { side: 'home', home: 3, away: 1 });
    assert.equal(coin.result(8), null);
    assert.equal(ck.pending(), 0, 'таймеры не текут');
    const phases = [];
    for (const c of log.change) {
      const ph = c.frame ? c.frame.phase : 'finished';
      if (phases[phases.length - 1] !== ph) phases.push(ph);
    }
    assert.deepEqual(phases, ['flip', 'choose', 'reels', 'finished']);
  });

  it('вибрация в срок: два удара на стопах барабанов, «успех» в конце, больше ничего', () => {
    const { ck, log, coin } = rig();
    coin.press(1);
    ck.advance(6000);
    const p = C.plan({ side: 'home', home: 3, away: 1 });
    assert.deepEqual(log.haptic, [
      { kind: 'impact', at: p.haptics[0].at },
      { kind: 'impact', at: p.haptics[1].at },
      { kind: 'success', at: p.total },
    ]);
  });

  it('перерисовка просится только когда меняется шаг, а не на каждый удар вибрации', () => {
    const { ck, log, coin } = rig();
    coin.press(1);
    ck.advance(6000);
    const p = C.plan({ side: 'home', home: 3, away: 1 });
    // старт + каждый шаг после нулевого + финал
    assert.equal(log.change.length, 1 + (p.steps.length - 1) + 0);
  });

  it('тап во время броска пропускает: результат сразу, ход сохраняется один раз, «успех» один раз', () => {
    const { ck, log, coin } = rig();
    coin.press(1);
    ck.advance(2000);
    assert.equal(coin.press(1), 'skip');
    assert.equal(coin.busy(), false);
    assert.equal(log.finish.length, 1);
    assert.deepEqual(log.finish[0].target, { side: 'home', home: 3, away: 1 });
    assert.equal(log.finish[0].at, 2000);
    assert.deepEqual(log.haptic, [{ kind: 'success', at: 2000 }]);
    ck.advance(10000);
    assert.equal(log.finish.length, 1, 'после пропуска таймеры не сохраняют второй раз');
    assert.equal(log.haptic.length, 1);
  });

  it('пропуск сразу после тапа и «Крутануть ещё» после результата', () => {
    const { ck, log, coin } = rig({ rng: seq(0.1, 0, 0.9, 0.3) });
    coin.press(1);
    assert.equal(coin.press(1), 'skip');
    assert.deepEqual(log.finish[0].target, { side: 'home', home: 3, away: 1 });
    assert.equal(coin.press(1), 'start', 'после результата тап — новый бросок');
    assert.equal(coin.result(1).side, 'home', 'пока крутится, прежний результат ещё числится');
    assert.equal(coin.frame(1).phase, 'flip');
    ck.advance(6000);
    assert.equal(log.finish.length, 2);
    assert.equal(log.finish[1].target.side, 'away');
    assert.deepEqual(coin.result(1), log.finish[1].target);
  });

  it('reduced motion: сразу результат, анимации нет, ход сохраняется, вибрация «успех»', () => {
    const { ck, log, coin } = rig({ reduced: true });
    assert.equal(coin.press(3), 'instant');
    assert.equal(coin.busy(), false);
    assert.equal(coin.frame(3), null);
    assert.equal(ck.pending(), 0);
    assert.equal(log.finish.length, 1);
    assert.deepEqual(coin.result(3), { side: 'home', home: 3, away: 1 });
    assert.deepEqual(log.haptic, [{ kind: 'success', at: 0 }]);
    assert.ok(log.change.length >= 1);
  });

  it('короткая версия включается после третьего броска за сессию', () => {
    const { ck, coin } = rig({ rng: seeded(5) });
    const totals = [];
    for (let i = 1; i <= 5; i++) {
      coin.press(1);
      totals.push(coin.frame(1).short);
      ck.advance(6000);
      assert.equal(coin.busy(), false);
    }
    assert.deepEqual(totals, [false, false, false, true, true]);
    assert.equal(coin.throws(), 5);
  });

  it('короткий бросок кончается за половину времени', () => {
    const { ck, log, coin } = rig({ shortAfter: 0 });
    coin.press(1);
    assert.equal(coin.frame(1).short, true);
    ck.advance(2879);
    assert.equal(log.finish.length, 0);
    ck.advance(1);
    assert.equal(log.finish.length, 1);
    assert.equal(log.finish[0].at, 2880);
  });

  it('мгновенный результат и пропуск тоже считаются бросками', () => {
    const { coin } = rig({ reduced: true, shortAfter: 3 });
    coin.press(1);
    coin.press(1);
    coin.press(1);
    assert.equal(coin.throws(), 3);
  });

  it('тап по монете другого матча завершает идущий бросок и начинает новый', () => {
    const { ck, log, coin } = rig({ rng: seq(0.1, 0, 0.9, 0.3) });
    coin.press(1);
    ck.advance(1500);
    assert.equal(coin.press(2), 'start');
    assert.equal(log.finish.length, 1);
    assert.equal(log.finish[0].key, 1);
    assert.equal(coin.busy(1), false);
    assert.equal(coin.busy(2), true);
    ck.advance(6000);
    assert.equal(log.finish.length, 2);
    assert.equal(log.finish[1].key, 2);
  });

  it('прерывание без сохранения: таймеры остановлены, ход не отдан', () => {
    const { ck, log, coin } = rig();
    coin.press(1);
    ck.advance(2000);
    assert.equal(coin.cancel(), true);
    assert.equal(coin.cancel(), false);
    assert.equal(coin.busy(), false);
    assert.equal(ck.pending(), 0);
    ck.advance(10000);
    assert.deepEqual(log.finish, []);
    assert.equal(coin.result(1), null);
  });

  it('вкладка спала дольше шкалы: первый же тик довершает бросок и сохраняет его один раз', () => {
    const { ck, log, coin } = rig();
    coin.press(1);
    // Часы убежали вперёд, как у приложения в фоне: таймер сработает с опозданием.
    ck.advance(1000);
    ck.advance(20000);
    assert.equal(log.finish.length, 1);
    assert.deepEqual(log.haptic.map((h) => h.kind), ['impact', 'impact', 'success']);
  });

  it('кадр в любой момент восстанавливается по времени: перерисовка экрана не сбивает анимацию', () => {
    const { ck, coin } = rig();
    coin.press(1);
    ck.advance(4500);
    const f = coin.frame(1);
    assert.equal(f.phase, 'reels');
    assert.equal(f.run, true);
    assert.equal(f.reelMs, 4500 - 3820);
    assert.equal(f.elapsed, 4500);
    assert.deepEqual(f.target, { side: 'home', home: 3, away: 1 });
  });

  it('итог каждого матча помнится отдельно: бросок на другом матче не стирает прежний', () => {
    const { ck, coin } = rig({ rng: seq(0.1, 0, 0.9, 0.3) });
    coin.press(1);
    ck.advance(6000);
    coin.press(2);
    ck.advance(6000);
    assert.deepEqual(coin.result(1), { side: 'home', home: 3, away: 1 });
    assert.equal(coin.result(2).side, 'away');
    coin.forget(1);
    assert.equal(coin.result(1), null);
    assert.ok(coin.result(2));
  });

  it('генератор по умолчанию берётся в момент броска, а не при создании монеты', () => {
    const real = Math.random;
    try {
      const ck = clock();
      const finished = [];
      const coin = C.createCoin({ now: ck.now, setTimer: ck.setTimer, clearTimer: ck.clearTimer, onFinish: (k, t) => finished.push(t) });
      Math.random = seq(0.1, 0);
      coin.press(1);
      ck.advance(6000);
      assert.deepEqual(finished[0], { side: 'home', home: 3, away: 1 });
    } finally {
      Math.random = real;
    }
  });

  it('forget убирает прежний результат', () => {
    const { coin } = rig({ reduced: true });
    coin.press(1);
    assert.ok(coin.result(1));
    coin.forget(2);
    assert.ok(coin.result(1));
    coin.forget(1);
    assert.equal(coin.result(1), null);
  });
});

describe('вид: команды, строка итога, барабаны', () => {
  it('кнопки команд по фазам: бросок притушил обе, рулетка зажигает по очереди, потом одна', () => {
    const p = C.plan({ side: 'away', home: 1, away: 3 });
    const look = (t, side) => C.sideLook(C.frameAt(p, t), side);
    assert.equal(C.sideLook(null, 'home'), null);
    assert.deepEqual(look(300, 'home'), { on: false, hl: false, dim: 2 });
    assert.deepEqual(look(300, 'away'), { on: false, hl: false, dim: 2 });
    assert.deepEqual(look(1100, 'home'), { on: false, hl: false, dim: 1 });
    const lit = p.steps.find((s) => s.hl);
    assert.equal(lit.hl, 'away');
    assert.deepEqual(look(lit.at, 'away'), { on: true, hl: true, dim: 0 });
    assert.deepEqual(look(lit.at, 'home'), { on: false, hl: false, dim: 1 });
    assert.deepEqual(look(p.total - 1, 'away'), { on: true, hl: false, dim: 0 });
    assert.deepEqual(look(p.total - 1, 'home'), { on: false, hl: false, dim: 2 });
  });

  it('строка итога: клуб, точка и счёт держатся вместе', () => {
    assert.equal(C.summaryLine('Химик', { side: 'home', home: 3, away: 1 }), 'Монетка выбрала: Химик' + NBSP + '·' + NBSP + '3:1');
    assert.equal(C.summaryLine('Славутич', { side: 'away', home: 1, away: 4 }), 'Монетка выбрала: Славутич' + NBSP + '·' + NBSP + '1:4');
  });

  it('скринридеру итог читается без точки-разделителя', () => {
    assert.equal(C.spokenLine('Химик', { side: 'home', home: 3, away: 1 }), 'Монетка выбрала Химик, счёт 3:1');
  });

  it('«Монетка выбрала» остаётся, пока ход совпадает с выпавшим; ручная правка её гасит', () => {
    const t = { side: 'home', home: 3, away: 1 };
    assert.equal(C.sameAsDrawn({ side: 'home', score: [3, 1], tie: false }, t), true);
    assert.equal(C.sameAsDrawn({ side: 'home', score: [4, 1], tie: false }, t), false);
    assert.equal(C.sameAsDrawn({ side: 'away', score: [3, 1], tie: false }, t), false);
    assert.equal(C.sameAsDrawn({ side: 'home', score: null, tie: false }, t), false);
    assert.equal(C.sameAsDrawn(null, t), false);
    assert.equal(C.sameAsDrawn({ side: 'home', score: [3, 1] }, null), false);
  });

  it('барабаны встают на цифру счёта: клетка mod 10 = голы, клеток хватает', () => {
    for (const [w, l] of C.SCORES) {
      for (const t of [{ side: 'home', home: w, away: l }, { side: 'away', home: l, away: w }]) {
        const s = C.reelStops(t);
        assert.equal(s.home % 10, t.home);
        assert.equal(s.away % 10, t.away);
        assert.ok(s.home < s.cells && s.away < s.cells, 'клетка внутри ленты');
        assert.ok(s.home >= 10 && s.away >= 10, 'несколько оборотов до цифры');
      }
    }
  });
});

describe('тексты игры', () => {
  it('нет «ставки», «срока», процентов и emoji; надпись на кнопке-монете только в aria-label', () => {
    const all = Object.values(C.TEXT).join(' | ');
    assert.ok(!/став|срок|%/i.test(all), all);
    assert.ok(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(all), 'emoji');
    assert.equal(C.TEXT.coinLabel, 'Крутануть монетку: она выберет победителя и счёт');
    assert.equal(C.TEXT.again, 'Крутануть ещё');
    assert.equal(C.TEXT.stamp, 'ВЫПАЛО');
  });
});

describe('подключение и вёрстка', () => {
  const html = fs.readFileSync(path.join(root, 'kto-kogo.html'), 'utf8');
  const css = fs.readFileSync(path.join(root, 'kto-kogo.css'), 'utf8');
  const view = fs.readFileSync(path.join(root, 'kto-kogo-coin.js'), 'utf8');

  it('скрипты монеты подключены после экранов и до запуска игры, модель раньше вида', () => {
    const order = [...html.matchAll(/kto-kogo[a-z-]*\.js/g)].map((m) => m[0]);
    const at = (f) => order.indexOf(f);
    assert.ok(at('kto-kogo-coin-model.js') > at('kto-kogo-leagues.js'));
    assert.ok(at('kto-kogo-coin.js') > at('kto-kogo-coin-model.js'));
    assert.ok(at('kto-kogo-coin.js') < at('kto-kogo-boot.js'));
  });

  it('стили монеты в своём разделе: рифлёный кант, зона 44 px, reduced motion', () => {
    const i = css.indexOf('/* ===== coin (TASK-360) ===== */');
    assert.ok(i > 0, 'раздел монеты');
    const mine = css.slice(i);
    assert.ok(/\.kk-coin\s*\{[^}]*width:\s*44px[^}]*height:\s*44px/.test(mine), 'зона нажатия 44 px');
    assert.ok(/repeating-conic-gradient/.test(mine), 'рифлёный кант');
    assert.ok(/prefers-reduced-motion:\s*reduce/.test(mine), 'reduced motion');
    assert.ok(/body\.kk-dark/.test(mine), 'тёмная тема');
  });

  it('вид: настоящий button, aria-label из модели, закрытый ход без монеты, итог читает скринридер', () => {
    assert.ok(/'button'/.test(view));
    assert.ok(/TEXT\.coinLabel/.test(view));
    assert.ok(/m\.open/.test(view));
    assert.ok(/aria-live/.test(view));
    assert.ok(/HapticFeedback/.test(view));
    assert.ok(/impactOccurred\('light'\)|impactOccurred\("light"\)/.test(view));
    assert.ok(/notificationOccurred\('success'\)/.test(view));
    assert.ok(/prefers-reduced-motion/.test(view));
  });
});
