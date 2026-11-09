/**
 * «Кто кого» — монетка (TASK-360): чистая логика без DOM и сети. Игрок жмёт золотую монету рядом с матчем,
 * монета бросается, рулетка выбирает команду, барабаны набирают счёт, ход сохраняется обычным путём.
 * Здесь: алгоритм выпадения, временная шкала анимации, машина состояний (flip → choose → reels → done),
 * пропуск, короткая версия, reduced motion, вибрация. Вёрстку и сохранение хода делает kto-kogo-coin.js;
 * логику проверяет tests/js/kto-kogo-coin-model.test.js. Слова: ход, победитель, счёт. Не «ставка», не «срок».
 */
(function (global) {
  'use strict';

  var NBSP = ' ';

  /** Хозяева выигрывают чуть чаще: 52 из 100 бросков. */
  var HOME_CHANCE = 0.52;

  /**
   * Частые хоккейные результаты: [голы победителя, голы проигравшего, вес]. Сумма весов — 100.
   * Победитель всегда с большим счётом, ничьих нет (овертайм и буллиты дают тот же «на шайбу больше»).
   */
  var SCORES = [
    [3, 1, 14], [3, 2, 14], [2, 1, 14], [4, 1, 10], [4, 2, 10], [1, 0, 5], [2, 0, 6],
    [3, 0, 6], [5, 2, 5], [4, 3, 6], [5, 1, 4], [5, 3, 3], [6, 2, 2], [6, 3, 1],
  ];

  /** Тайминги полной версии, мс (прототип «Монетка», Main.dc.html). */
  var T = {
    flip: 1100,
    gaps: [80, 80, 85, 95, 110, 130, 160, 200, 250, 320, 400], // паузы подсветки: рулетка замедляется
    hold: 350, // после последней подсветки победитель стоит один
    toReels: 750, // от последней подсветки до появления барабанов
    spin: 60, // барабаны трогаются
    homeReel: 1300, // стоп барабана хозяев
    awayReel: 1900, // стоп барабана гостей
    reels: 2000, // от появления барабанов до наклейки «ВЫПАЛО»
  };
  /** Короткая версия вдвое быстрее. */
  var SHORT_K = 0.5;
  /** Столько бросков за сессию идут полной версией; со следующего — короткая. */
  var SHORT_AFTER = 3;

  /** Клетки барабана: цифры идут по кругу, барабаны хозяев и гостей встают на разных кругах. */
  var REEL_CELLS = 50;
  var HOME_LAP = 30;
  var AWAY_LAP = 40;

  var TEXT = {
    coinLabel: 'Крутануть монетку: она выберет победителя и счёт',
    skipLabel: 'Пропустить анимацию',
    again: 'Крутануть ещё',
    stamp: 'ВЫПАЛО',
    chosen: 'Монетка выбрала: ',
    closed: 'Ходы на этот матч уже закрыты',
  };

  function noop() {}

  /** Генератор вернул 1, NaN или мусор — не падаем, берём ближайшее допустимое. */
  function unit(rng) {
    var r = Number(rng());
    if (!(r >= 0)) return 0;
    return r >= 1 ? 0.999999999 : r;
  }

  function weightSum() {
    return SCORES.reduce(function (a, r) { return a + r[2]; }, 0);
  }

  /** Счёт по таблице частых результатов: [победитель, проигравший]. */
  function pickScore(rng) {
    var x = unit(rng) * weightSum();
    for (var i = 0; i < SCORES.length; i++) {
      x -= SCORES[i][2];
      if (x < 0) return [SCORES[i][0], SCORES[i][1]];
    }
    return [SCORES[0][0], SCORES[0][1]];
  }

  /**
   * Что выпало: {side: 'home' | 'away', home, away}. Сначала победитель (первый вызов rng), потом счёт (второй).
   * rng подменяется в тестах; по умолчанию Math.random.
   */
  function draw(rng) {
    rng = rng || Math.random;
    var home = unit(rng) < HOME_CHANCE;
    var w = pickScore(rng);
    return home ? { side: 'home', home: w[0], away: w[1] } : { side: 'away', home: w[1], away: w[0] };
  }

  // ---------- временная шкала ----------

  function r1(n) {
    return Math.round(n * 100) / 100;
  }

  /**
   * Шкала броска для выпавшего target. Шаги упорядочены по времени `at` (мс от тапа); состояние в любой
   * момент — последний шаг с at ≤ t. Вибрация — отдельный список меток. Пересборка экрана посреди броска
   * не сбивает анимацию: по времени, прошедшему с тапа, состояние восстанавливается заново.
   */
  function plan(target, opts) {
    var short = !!(opts && opts.short);
    var k = short ? SHORT_K : 1;
    var other = target.side === 'home' ? 'away' : 'home';
    var steps = [{ at: 0, phase: 'flip', hl: null, side: null, run: false }];
    var t = T.flip;
    steps.push({ at: t, phase: 'choose', hl: null, side: null, run: false });
    var n = T.gaps.length;
    T.gaps.forEach(function (g, i) {
      t += g;
      // Рулетка заканчивается на победителе: с конца счёт идёт «победитель, другая, победитель…».
      steps.push({ at: t, phase: 'choose', hl: (n - 1 - i) % 2 === 0 ? target.side : other, side: null, run: false });
    });
    steps.push({ at: t + T.hold, phase: 'choose', hl: null, side: target.side, run: false });
    var reelsAt = t + T.toReels;
    var runAt = reelsAt + T.spin;
    var total = reelsAt + T.reels;
    steps.push({ at: reelsAt, phase: 'reels', hl: null, side: target.side, run: false });
    steps.push({ at: runAt, phase: 'reels', hl: null, side: target.side, run: true });
    steps.push({ at: total, phase: 'done', hl: null, side: target.side, run: true });
    steps.forEach(function (s) { s.at = r1(s.at * k); });
    var haptics = [
      { at: r1((runAt + T.homeReel) * k), kind: 'impact' },
      { at: r1((runAt + T.awayReel) * k), kind: 'impact' },
      { at: r1(total * k), kind: 'success' },
    ];
    var marks = steps.map(function (s) { return s.at; }).concat(haptics.map(function (x) { return x.at; }));
    marks = marks.filter(function (v, i) { return marks.indexOf(v) === i; }).sort(function (a, b) { return a - b; });
    return {
      steps: steps,
      haptics: haptics,
      marks: marks,
      short: short,
      total: r1(total * k),
      runAt: r1(runAt * k),
      reelMs: { home: r1(T.homeReel * k), away: r1(T.awayReel * k) },
      flipMs: r1(T.flip * k),
    };
  }

  function stepIndex(p, elapsed) {
    var idx = 0;
    for (var i = 0; i < p.steps.length; i++) {
      if (p.steps[i].at <= elapsed) idx = i;
      else break;
    }
    return idx;
  }

  /** Состояние броска через elapsed мс: {phase, hl, side, run, stamp, reelMs, elapsed, short}. */
  function frameAt(p, elapsed) {
    var e = elapsed > 0 ? elapsed : 0;
    var s = p.steps[stepIndex(p, e)];
    return {
      phase: s.phase,
      hl: s.hl,
      side: s.side,
      run: s.run,
      stamp: s.phase === 'done',
      reelMs: s.run ? Math.max(0, e - p.runAt) : 0,
      elapsed: e,
      short: p.short,
    };
  }

  /** Ближайшая метка (смена шага или вибрация) строго после elapsed; null — шкала кончилась. */
  function nextMark(p, elapsed) {
    for (var i = 0; i < p.marks.length; i++) if (p.marks[i] > elapsed) return p.marks[i];
    return null;
  }

  // ---------- машина состояний ----------

  /**
   * Машина броска: idle → flip → choose → reels → done. Одновременно идёт один бросок.
   * Всё внешнее приходит параметрами, поэтому её гоняют в тестах на поддельных часах:
   *   rng, now, setTimer, clearTimer, reducedMotion() — окружение;
   *   shortAfter — сколько бросков идут полной версией;
   *   onChange(key) — пора перерисовать, onHaptic('impact' | 'success'), onFinish(key, target) — сохранить ход.
   */
  function createCoin(o) {
    o = o || {};
    var rng = o.rng || function () { return Math.random(); };
    var now = o.now || function () { return Date.now(); };
    var setT = o.setTimer || function (f, ms) { return setTimeout(f, ms); };
    var clearT = o.clearTimer || function (id) { clearTimeout(id); };
    var reduced = o.reducedMotion || function () { return false; };
    var shortAfter = typeof o.shortAfter === 'number' ? o.shortAfter : SHORT_AFTER;
    var onChange = o.onChange || noop;
    var onHaptic = o.onHaptic || noop;
    var onFinish = o.onFinish || noop;
    var run = null; // идущий бросок
    var results = {}; // что выпало на матче, пока ход не поправили: id матча → target
    var throws = 0;

    function delayTo(r, el) {
      var nx = nextMark(r.plan, el);
      return Math.max(0, (nx === null ? r.plan.total : nx) - el);
    }

    function fire(r, el) {
      for (var i = r.fired + 1; i < r.plan.haptics.length; i++) {
        if (r.plan.haptics[i].at > el) break;
        r.fired = i;
        onHaptic(r.plan.haptics[i].kind);
      }
    }

    function finish(r) {
      if (run !== r) return;
      if (r.timer !== null) clearT(r.timer);
      run = null;
      results[r.key] = r.target;
      // Результат уже записан: сохранение хода перерисует экран и увидит готовый итог.
      onFinish(r.key, r.target);
      onChange(r.key);
    }

    function tick(r) {
      if (run !== r) return;
      var el = now() - r.startedAt;
      fire(r, el);
      if (el >= r.plan.total) return finish(r);
      var idx = stepIndex(r.plan, el);
      if (idx !== r.idx) {
        r.idx = idx;
        onChange(r.key);
      }
      r.timer = setT(function () { tick(r); }, delayTo(r, el));
    }

    /**
     * Тап по монете матча key. Идёт бросок этого матча — пропуск (результат сразу, ход сохраняется).
     * Идёт бросок другого матча — тот завершается и сохраняется, этот стартует. Иначе новый бросок.
     * Возвращает 'start' | 'skip' | 'instant'.
     */
    function press(key) {
      if (run) {
        var cur = run;
        if (cur.key === key) {
          onHaptic('success');
          finish(cur);
          return 'skip';
        }
        finish(cur);
      }
      var target = draw(rng);
      var short = throws >= shortAfter;
      throws++;
      if (reduced()) {
        results[key] = target;
        onHaptic('success');
        onFinish(key, target);
        onChange(key);
        return 'instant';
      }
      var r = { key: key, target: target, plan: plan(target, { short: short }), startedAt: now(), timer: null, fired: -1, idx: 0 };
      run = r;
      onChange(key);
      r.timer = setT(function () { tick(r); }, delayTo(r, 0));
      return 'start';
    }

    /** Бросок прерван без сохранения (игрок ушёл с экрана). */
    function cancel() {
      if (!run) return false;
      if (run.timer !== null) clearT(run.timer);
      run = null;
      return true;
    }

    return {
      press: press,
      cancel: cancel,
      busy: function (key) { return !!run && (key === undefined || key === null || run.key === key); },
      running: function () { return run ? run.key : null; },
      frame: function (key) {
        if (!run || run.key !== key) return null;
        var f = frameAt(run.plan, now() - run.startedAt);
        f.target = run.target;
        return f;
      },
      result: function (key) { return results[key] || null; },
      forget: function (key) { delete results[key]; },
      throws: function () { return throws; },
    };
  }

  // ---------- вид ----------

  /**
   * Как рисовать кнопку команды, пока идёт бросок: {on, hl, dim}. null — на этом матче броска нет,
   * кнопка рисуется из хода как обычно. dim: 0 — обычная, 1 — притихла, 2 — отыграла.
   */
  function sideLook(f, side) {
    if (!f) return null;
    if (f.phase === 'flip') return { on: false, hl: false, dim: 2 };
    if (f.side) return f.side === side ? { on: true, hl: false, dim: 0 } : { on: false, hl: false, dim: 2 };
    return f.hl === side ? { on: true, hl: true, dim: 0 } : { on: false, hl: false, dim: 1 };
  }

  /** Совпадает ли ход игрока (с учётом черновика) с тем, что выпало: тогда строка «Монетка выбрала» остаётся. */
  function sameAsDrawn(eff, target) {
    return !!(eff && target && eff.side === target.side && eff.score && eff.score[0] === target.home && eff.score[1] === target.away);
  }

  /** «Монетка выбрала: Химик · 3:1» — клуб, точка-разделитель и счёт не рвутся при переносе. */
  function summaryLine(clubName, target) {
    return TEXT.chosen + clubName + NBSP + '·' + NBSP + target.home + ':' + target.away;
  }

  /** То же для скринридера: без точки-разделителя, которую читают вслух. */
  function spokenLine(clubName, target) {
    return 'Монетка выбрала ' + clubName + ', счёт ' + target.home + ':' + target.away;
  }

  /** Куда встают барабаны: номер клетки (клетка = цифра mod 10) для хозяев и гостей. */
  function reelStops(target) {
    return { cells: REEL_CELLS, home: HOME_LAP + target.home, away: AWAY_LAP + target.away };
  }

  var api = {
    HOME_CHANCE: HOME_CHANCE,
    SCORES: SCORES,
    TIMING: T,
    SHORT_K: SHORT_K,
    SHORT_AFTER: SHORT_AFTER,
    TEXT: TEXT,
    draw: draw,
    plan: plan,
    frameAt: frameAt,
    nextMark: nextMark,
    createCoin: createCoin,
    sideLook: sideLook,
    sameAsDrawn: sameAsDrawn,
    summaryLine: summaryLine,
    spokenLine: spokenLine,
    reelStops: reelStops,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.KtoKogoCoin = api;
})(typeof window !== 'undefined' ? window : globalThis);
