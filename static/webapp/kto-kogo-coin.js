/**
 * «Кто кого» — монетка (TASK-360): вёрстка и сохранение хода. Логика броска, тайминги и тексты — в
 * kto-kogo-coin-model.js (K.coin — только DOM). Холст: claude.ai/artifact/WjisnSqHGkH81nW3VLyZR3.
 *
 * Публичный контракт для экранов (хаб, матч, список матчей):
 *   K.coin.button(match)     — кнопка-монета (всегда DOM-узел; на закрытом ходе — пустая скрытая заглушка);
 *   K.coin.panel(match)      — барабаны счёта, «ВЫПАЛО», строка «Монетка выбрала» и «Крутануть ещё»; null, если показывать нечего;
 *   K.coin.side(match, side) — как рисовать кнопку команды во время броска: {on, cls} или null;
 *   K.coin.busy(match)       — идёт бросок этого матча (счёт и «Угадать» в это время прячем).
 * Экран пересобирается целиком (K.render), поэтому бросок живёт здесь, а вид каждый раз восстанавливается
 * по времени, прошедшему с тапа: CSS-анимации продолжаются с нужного места (отрицательная задержка).
 * Результат сохраняется обычным ходом (K.saveScore) в конце броска или сразу при пропуске.
 */
(function () {
  'use strict';

  var K = window.KK;
  var C = window.KtoKogoCoin;
  if (!K || !C) return;
  var h = K.h;
  var S = K.S;
  var state = K.state;
  var TEXT = C.TEXT;

  var owner = null; // экран, на котором начат бросок: ушёл игрок — бросок снимается без сохранения
  var startSeq = {}; // id матча → число ходов на старте: если за бросок игрок сделал ход сам, монета его не затирает
  var finishAt = {}; // id матча → когда бросок кончился (для наклейки «ВЫПАЛО»: хлопок один раз)
  var skipTap = { id: null, until: 0 }; // пропуск уже сделан на касании: клик, который за ним следует, новый бросок не начинает
  var live = null;

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  /** Лёгкий удар на стопе барабана. «Успех» в конце не наш: его даёт сохранение хода (sendPick в kto-kogo.js). */
  function buzz() {
    try {
      var hf = K.tg && K.tg.HapticFeedback;
      if (hf) hf.impactOccurred('light');
    } catch (e) { /* старый клиент без вибрации */ }
  }

  /** Невидимая зона для скринридера вне корня игры: K.render её не пересоздаёт, поэтому итог читается один раз и по-настоящему. */
  function announce(text) {
    try {
      if (!live) {
        live = h('div', { class: 'kk-coin-sr', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' });
        document.body.appendChild(live);
      }
      live.textContent = '';
      setTimeout(function () { live.textContent = text; }, 60);
    } catch (e) { /* */ }
  }

  function clubName(m, side) {
    return S.clubName(m[side].name);
  }

  /** Конец броска: ход сохраняется так же, как тап по команде и «+/−» у счёта. */
  function commit(key, target) {
    finishAt[key] = Date.now();
    var m = K.findMatch(key);
    if (!m) return;
    if (!m.open) {
      ctl.forget(key);
      K.toast(TEXT.closed);
      return;
    }
    // Пока крутилось, игрок сам сделал ход — его выбор важнее.
    if ((m.pickSeq || 0) !== (startSeq[key] || 0)) {
      ctl.forget(key);
      return;
    }
    delete state.drafts[m.id];
    announce(C.spokenLine(clubName(m, target.side), target));
    K.saveScore(m, target.home, target.away);
  }

  var ctl = C.createCoin({
    reducedMotion: reducedMotion,
    onChange: function () { K.render(); },
    onHaptic: buzz,
    onFinish: commit,
  });

  /** Бросок этого матча, если он идёт на этом экране; иначе null (и бросок снимается, если экран или ход ушли). */
  function frameOf(m) {
    if (!ctl.busy(m.id)) return null;
    if (K.current() !== owner || !m.open) {
      ctl.cancel();
      return null;
    }
    return ctl.frame(m.id);
  }

  function press(m, fromAgain) {
    if (!m || !m.open) return;
    if (!ctl.busy(m.id)) {
      owner = K.current();
      startSeq[m.id] = m.pickSeq || 0;
      delete finishAt[m.id];
    }
    ctl.press(m.id);
    // «Крутануть ещё» пропала вместе с итогом — фокус не теряем, переносим на монету.
    if (fromAgain) {
      setTimeout(function () {
        var b = document.getElementById('kk-coin-' + m.id);
        if (b) b.focus();
      }, 0);
    }
  }

  // ---------- монета ----------

  function face(f) {
    var flip = !!f && f.phase === 'flip';
    var dur = f && f.short ? C.TIMING.flip * C.SHORT_K : C.TIMING.flip;
    return h('span', {
      class: 'kk-cn' + (flip ? ' is-flip' : ''),
      style: flip ? '--kk-cn-dur:' + dur + 'ms;--kk-cn-delay:-' + Math.round(f.elapsed) + 'ms' : null,
      'aria-hidden': 'true',
    }, [
      h('span', { class: 'kk-cn__f' }, [
        h('span', { class: 'kk-cn__pk' }, [h('i'), h('b')]),
        h('span', { class: 'kk-cn__shw' }, [h('span', { class: 'kk-cn__shine' })]),
      ]),
      h('span', { class: 'kk-cn__f kk-cn__b' }),
    ]);
  }

  /** Кнопка-монета: без текста, зона нажатия 44 px, золото 32 px. Ход закрыт — монеты нет (скрытая заглушка, а не null). */
  function button(m) {
    if (!m || !m.open) return h('span', { class: 'kk-coin-none', hidden: true, 'aria-hidden': 'true' });
    var f = frameOf(m);
    return h('button', {
      type: 'button',
      class: 'kk-coin' + (f ? ' is-busy' : ''),
      id: 'kk-coin-' + m.id,
      'data-keep': '',
      'aria-label': f ? TEXT.skipLabel : TEXT.coinLabel,
      // Пропуск по касанию, а не по клику: пока рулетка бежит, экран пересобирается каждые 80 мс и клик теряется.
      onpointerdown: function (e) {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        if (!ctl.busy(m.id)) return;
        e.preventDefault();
        skipTap = { id: m.id, until: Date.now() + 350 };
        press(m);
      },
      onclick: function () {
        if (skipTap.id === m.id && Date.now() < skipTap.until) return;
        press(m);
      },
    }, [face(f)]);
  }

  // ---------- команды во время броска ----------

  function side(m, s) {
    var f = frameOf(m);
    if (!f) return null;
    var look = C.sideLook(f, s);
    return {
      on: look.on,
      cls: (look.hl ? ' is-coin-hl' : '') + (look.dim === 2 ? ' is-coin-dim' : look.dim === 1 ? ' is-coin-soft' : ''),
    };
  }

  function busy(m) {
    return !!m && !!frameOf(m);
  }

  // ---------- барабаны, наклейка, строка итога ----------

  function reelCol(which, m, f, stops) {
    var k = f.short ? C.SHORT_K : 1;
    var dur = (which === 'home' ? C.TIMING.homeReel : C.TIMING.awayReel) * k;
    var cells = [];
    for (var i = 0; i < stops.cells; i++) cells.push(h('div', { class: 'kk-cp__c', text: String(i % 10) }));
    var style = '--kk-n:' + stops[which];
    var cls = 'kk-cp__strip';
    if (f.phase === 'done') cls += ' is-set';
    else if (f.run) {
      cls += ' is-run';
      style += ';--kk-dur:' + dur + 'ms;--kk-delay:-' + Math.round(f.reelMs) + 'ms';
    }
    return h('div', { class: 'kk-cp__col' }, [
      h('div', { class: 'kk-cp__win' }, [h('div', { class: 'kk-cp__mask' }, [h('div', { class: cls, style: style }, cells)])]),
      h('span', { class: 'kk-cp__nm', text: S.clubShort(m[which].name) }),
    ]);
  }

  function stamp(m, f) {
    if (f.phase !== 'done') return null;
    var since = finishAt[m.id] ? Date.now() - finishAt[m.id] : 0;
    var pop = since < 320;
    return h('span', {
      class: 'kk-cp__stamp' + (pop ? ' is-pop' : ''),
      style: pop ? '--kk-delay:-' + Math.max(0, Math.round(since)) + 'ms' : null,
      'aria-hidden': 'true',
      text: TEXT.stamp,
    });
  }

  function reels(m, f) {
    var stops = C.reelStops(f.target);
    return h('div', { class: 'kk-cp__reels', 'aria-hidden': 'true' }, [
      reelCol('home', m, f, stops),
      h('b', { class: 'kk-cp__sep', text: ':' }),
      reelCol('away', m, f, stops),
      stamp(m, f),
    ]);
  }

  /** Блок под командами: барабаны (пока крутятся и после), затем строка «Монетка выбрала» с «Крутануть ещё». */
  function panel(m) {
    if (!m || !m.open) return null;
    var f = frameOf(m);
    if (f) {
      if (f.phase !== 'reels' && f.phase !== 'done') {
        // Повторный бросок: место прежних барабанов держим пустым, карточка и список под ней не прыгают.
        return ctl.result(m.id) ? h('div', { class: 'kk-cp kk-cp--hold', 'aria-hidden': 'true' }) : null;
      }
      return h('div', { class: 'kk-cp' }, [reels(m, f)]);
    }
    var t = ctl.result(m.id);
    if (!t) return null;
    var eff = S.effectivePick(m.my_pick, state.drafts[m.id] || null);
    if (!C.sameAsDrawn(eff, t)) {
      // Игрок поправил ход вручную (или ход не дошёл до сервера): это уже не монета.
      ctl.forget(m.id);
      return null;
    }
    var fin = { phase: 'done', run: false, reelMs: 0, short: false, target: t };
    return h('div', { class: 'kk-cp' }, [
      reels(m, fin),
      h('div', { class: 'kk-cp__sum' }, [
        h('span', { class: 'kk-cp__t', text: C.summaryLine(clubName(m, t.side), t) }),
        h('button', {
          type: 'button',
          class: 'kk-cp__again',
          id: 'kk-coin-again-' + m.id,
          'data-keep': '',
          onclick: function () { press(m, true); },
          text: TEXT.again,
        }),
      ]),
    ]);
  }

  K.coin = { button: button, panel: panel, side: side, busy: busy };
})();
