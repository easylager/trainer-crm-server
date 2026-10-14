/**
 * Отклик нажатия на публичке: iOS нужен пустой touchstart (passive), иначе :active/класс не срабатывает.
 * Класс b-press — после 80 ms удержания; короткий тап — мигание ~100 ms; сброс при движении >8 px, scroll, pagehide.
 */
(function () {
  'use strict';

  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    return;
  }

  document.addEventListener('touchstart', function () {}, { passive: true });

  var PRESS_SEL =
    '.b-city,.b-when a,a.b-tile,a.b-row,a.b-slot,a.b-table__row,a.b-ticket,a.b-card,a.b-card2__thumb,.home-map__city';
  var DELAY_MS = 80;
  var FLASH_MS = 100;
  var MOVE_PX = 8;
  var PRESS_CLASS = 'b-press';

  var pressEl = null;
  var pressTimer = null;
  var releaseTimer = null;
  var flashEl = null;
  var startX = 0;
  var startY = 0;
  var activePointer = null;

  function nearestPressable(node) {
    return node && node.closest ? node.closest(PRESS_SEL) : null;
  }

  function clearPress() {
    if (pressTimer) {
      clearTimeout(pressTimer);
      pressTimer = null;
    }
    if (releaseTimer) {
      clearTimeout(releaseTimer);
      releaseTimer = null;
    }
    if (pressEl) {
      pressEl.classList.remove(PRESS_CLASS);
      pressEl = null;
    }
    if (flashEl) {
      flashEl.classList.remove(PRESS_CLASS);
      flashEl = null;
    }
    activePointer = null;
  }

  function flashPress(el) {
    if (releaseTimer) {
      clearTimeout(releaseTimer);
      releaseTimer = null;
    }
    if (flashEl && flashEl !== el) {
      flashEl.classList.remove(PRESS_CLASS);
    }
    flashEl = el;
    el.classList.add(PRESS_CLASS);
    releaseTimer = window.setTimeout(function () {
      releaseTimer = null;
      if (flashEl === el) {
        el.classList.remove(PRESS_CLASS);
        flashEl = null;
      }
    }, FLASH_MS);
  }

  document.addEventListener('scroll', clearPress, { passive: true, capture: true });
  window.addEventListener('pagehide', clearPress);

  document.addEventListener(
    'pointerdown',
    function (e) {
      if (e.button !== 0) return;
      var el = nearestPressable(e.target);
      if (!el) return;
      clearPress();
      pressEl = el;
      activePointer = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      pressTimer = window.setTimeout(function () {
        pressTimer = null;
        if (pressEl === el && activePointer === e.pointerId) {
          el.classList.add(PRESS_CLASS);
        }
      }, DELAY_MS);
    },
    { passive: true }
  );

  document.addEventListener(
    'pointermove',
    function (e) {
      if (activePointer == null || e.pointerId !== activePointer) return;
      if (Math.hypot(e.clientX - startX, e.clientY - startY) > MOVE_PX) {
        clearPress();
      }
    },
    { passive: true }
  );

  document.addEventListener(
    'pointerup',
    function (e) {
      if (activePointer == null || e.pointerId !== activePointer) return;
      var el = pressEl;
      if (pressTimer) {
        clearTimeout(pressTimer);
        pressTimer = null;
        activePointer = null;
        pressEl = null;
        if (el) flashPress(el);
        return;
      }
      clearPress();
    },
    { passive: true }
  );

  document.addEventListener('pointercancel', clearPress, { passive: true });
})();
