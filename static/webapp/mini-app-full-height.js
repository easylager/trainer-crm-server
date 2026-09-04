/**
 * Раскрытие Mini App на всю высоту — надёжно, даже когда telegram-web-app.js подключён с async.
 *
 * Страницы-входы (trainer-home / trainer-onboarding) грузят SDK асинхронно: блокирующий запрос
 * к telegram.org на плохой сети оставлял приложение на сплеше навсегда. Побочный эффект —
 * встроенные `if (tg) { tg.ready(); tg.expand(); }` выполнялись до появления window.Telegram.WebApp
 * и молча не делали НИЧЕГО: приложение открывалось полушторкой, её приходилось тянуть вверх руками.
 *
 * Только expand() — НЕ requestFullscreen(). Fullscreen на iOS/Android уводит контент под
 * статус-бар и кнопки Telegram (✕ / ⋯), шапка «лезет» за край экрана. expand() поднимает
 * шторку на максимум, оставляя нативную шапку Telegram сверху.
 */
(function (w) {
  'use strict';

  function getTg() {
    return (w.Telegram && w.Telegram.WebApp) || null;
  }

  function expand(tg) {
    try {
      if (typeof tg.expand === 'function') tg.expand();
    } catch (e) { /* старый клиент */ }
  }

  /** Шторка ещё не на полной доступной высоте (half-sheet / не expand). */
  function looksHalfSheet(tg) {
    if (tg.isExpanded === true) return false;
    var vh = Number(tg.viewportStableHeight || tg.viewportHeight || 0);
    var screenH = 0;
    try {
      screenH = Number((w.screen && (w.screen.height || w.screen.availHeight)) || 0);
    } catch (e) { /* */ }
    if (!vh) return true;
    if (screenH > 0 && vh < screenH * 0.55) return true;
    return false;
  }

  /**
   * Разворачивает переданный (или текущий) WebApp. Возвращает false, если SDK ещё нет.
   */
  function openFullHeight(tg) {
    tg = tg || getTg();
    if (!tg) return false;
    /* Если когда-то остались в fullscreen от прошлой версии — выходим. */
    try {
      if (tg.isFullscreen === true && typeof tg.exitFullscreen === 'function') {
        tg.exitFullscreen();
      }
    } catch (e) { /* */ }
    expand(tg);
    return true;
  }

  function bindViewportRetry(tg) {
    if (w.__tgFullHeightBound || typeof tg.onEvent !== 'function') return;
    w.__tgFullHeightBound = true;
    try {
      tg.onEvent('viewportChanged', function () {
        if (looksHalfSheet(tg)) expand(tg);
      });
    } catch (e) { /* */ }
  }

  function scheduleRetries(tg) {
    var delays = [80, 250, 600, 1200];
    delays.forEach(function (ms) {
      setTimeout(function () {
        if (!getTg()) return;
        if (looksHalfSheet(tg)) expand(tg);
      }, ms);
    });
  }

  function boot() {
    var tg = getTg();
    if (!tg) return false;
    bindViewportRetry(tg);
    try {
      if (typeof tg.ready === 'function') tg.ready();
    } catch (e) { /* */ }
    w.__tgReadyCalled = true;
    openFullHeight(tg);
    scheduleRetries(tg);
    return true;
  }

  var pending = [];

  function flushPending(tg) {
    while (pending.length) {
      try { pending.shift()(tg); } catch (e) { /* один упавший колбэк не роняет остальные */ }
    }
  }

  /**
   * Выполнить cb(tg), как только SDK появится (или сразу, если он уже есть).
   */
  w.tgWhenReady = function (cb) {
    if (typeof cb !== 'function') return;
    var tg = getTg();
    if (tg) { try { cb(tg); } catch (e) { /* */ } return; }
    pending.push(cb);
  };

  w.tgOpenFullHeight = openFullHeight;

  if (boot()) {
    flushPending(getTg());
  } else {
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (boot()) {
        clearInterval(timer);
        flushPending(getTg());
      } else if (tries > 300) {
        clearInterval(timer);
        pending.length = 0;
      }
    }, 30);
  }
})(window);
