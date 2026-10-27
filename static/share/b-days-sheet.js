/**
 * Лист «Выберите день» (TASK-337): открытие, закрытие и свайп вниз.
 * Работает и на главной, и в хабе города. Без JS лист открывается якорем #when-days (:target).
 *
 * Что делает руками, а не оставляет браузеру:
 *  - свайп вниз по листу тянет сам лист и закрывает его (иначе в мобильных браузерах и во
 *    встроенном браузере Telegram жест уходит странице и сворачивает весь браузер);
 *  - пока лист открыт, страница под ним не прокручивается;
 *  - крестик, тап по фону и Esc закрывают.
 */
(function () {
  'use strict';

  var ID = 'when-days';
  var OPEN = 'is-open';
  var LOCK = 'days-sheet-open';
  var CLOSE_DISTANCE = 90; // px
  var CLOSE_VELOCITY = 0.6; // px/ms
  var drag = null;

  function sheet() { return document.getElementById(ID); }
  function panel() { var s = sheet(); return s && s.querySelector('.b-days-sheet__panel'); }
  function isOpen() { var s = sheet(); return !!s && s.classList.contains(OPEN); }

  // Во встроенном Telegram жест вниз сворачивает окно: на время листа просим его не трогать.
  function tgSwipes(on) {
    try {
      var w = window.Telegram && window.Telegram.WebApp;
      if (w) (on ? w.enableVerticalSwipes : w.disableVerticalSwipes) && (on ? w.enableVerticalSwipes() : w.disableVerticalSwipes());
    } catch (_) { /* не мини-апп */ }
  }

  function reset() {
    var p = panel(), s = sheet();
    if (p) { p.style.transform = ''; p.style.transition = ''; }
    if (s) s.style.removeProperty('--sheet-dim');
  }

  function open() {
    var s = sheet();
    if (!s) return;
    reset();
    s.classList.add(OPEN);
    document.documentElement.classList.add(LOCK);
    tgSwipes(false);
    var first = s.querySelector('.b-dayc[aria-current="true"]') || s.querySelector('.b-dayc');
    if (first && first.focus) first.focus({ preventScroll: true });
  }

  function close() {
    var s = sheet();
    if (s) s.classList.remove(OPEN);
    document.documentElement.classList.remove(LOCK);
    reset();
    tgSwipes(true);
    // Страница открыта со #when-days: :target держит лист открытым, и pushState его не снимает.
    // Переход к пустому фрагменту без новой записи в истории снимает.
    if (location.hash === '#' + ID) location.replace(location.pathname + location.search + '#');
  }

  window.glideDaysSheet = { open: open, close: close };

  document.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('a.b-cal, .b-days-sheet__bg, .b-days-sheet__x') : null;
    if (!t || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    if (t.classList.contains('b-cal')) open(); else close();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isOpen()) close();
  });

  // Назад из истории браузера может вернуть страницу с открытым листом.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted && isOpen()) close();
  });

  // ── Свайп вниз ─────────────────────────────────────────────────────────────────────────
  document.addEventListener('touchstart', function (e) {
    var p = panel();
    if (!isOpen() || !p || e.touches.length !== 1) return;
    if (!p.contains(e.target)) return;
    drag = { y: e.touches[0].clientY, t: Date.now(), dy: 0, on: false };
  }, { passive: true });

  document.addEventListener('touchmove', function (e) {
    var p = panel();
    if (!drag || !p) return;
    var dy = e.touches[0].clientY - drag.y;
    if (!drag.on) {
      if (dy > 6 && p.scrollTop <= 0) { drag.on = true; p.style.transition = 'none'; }
      else if (dy < -6) { drag = null; return; }
      else return;
    }
    e.preventDefault(); // иначе жест уйдёт браузеру: обновление страницы или сворачивание окна
    drag.dy = Math.max(0, dy);
    p.style.transform = 'translateY(' + drag.dy + 'px)';
    sheet().style.setProperty('--sheet-dim', String(Math.max(0, 1 - drag.dy / 320)));
  }, { passive: false });

  function end() {
    var d = drag, p = panel();
    drag = null;
    if (!d || !d.on || !p) return;
    var speed = d.dy / Math.max(1, Date.now() - d.t);
    if (d.dy > CLOSE_DISTANCE || speed > CLOSE_VELOCITY) {
      p.style.transition = 'transform 160ms ease-out';
      p.style.transform = 'translateY(100%)';
      setTimeout(close, 150);
    } else {
      p.style.transition = 'transform 180ms ease-out';
      p.style.transform = '';
      sheet().style.removeProperty('--sheet-dim');
    }
  }
  document.addEventListener('touchend', end, { passive: true });
  document.addEventListener('touchcancel', end, { passive: true });
})();
