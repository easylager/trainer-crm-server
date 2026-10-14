/**
 * Отклик нажатия на публичке: iOS нужен пустой touchstart (passive), иначе :active/класс не срабатывает.
 * Класс b-press — после 80 ms; снимается при движении >8 px или scroll (как в ленте Mini App).
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
  var MOVE_PX = 8;
  var PRESS_CLASS = 'b-press';

  var pressEl = null;
  var pressTimer = null;
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
    if (pressEl) {
      pressEl.classList.remove(PRESS_CLASS);
      pressEl = null;
    }
    activePointer = null;
  }

  document.addEventListener('scroll', clearPress, { passive: true, capture: true });

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

  document.addEventListener('pointerup', clearPress, { passive: true });
  document.addEventListener('pointercancel', clearPress, { passive: true });
})();
