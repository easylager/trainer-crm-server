/*
 * Отклик на нажатие для всего Mini App: любая кнопка, ссылка, чип, вкладка и строка списка чуть
 * «проседает» под пальцем и пружинит обратно — как на сайте (b-press.js / .ga-press).
 *
 * Раньше это было по классу .ga-press на отдельных экранах, и чипы вроде «Сегодня / Завтра» на главной
 * не реагировали: нажал — и сразу другой экран. Теперь правило общее, и новым кнопкам ничего
 * добавлять не нужно.
 *
 * - Маленькие элементы (кнопки, чипы, значки) сжимаются на 3% и чуть темнеют (``scale``, а не ``transform``,
 *   чтобы не ломать центрирование через translate). Крупные (карточки, строки) только темнеют.
 * - Нажатие видно с первого кадра и держится не меньше 110 мс, даже если палец отпущен мгновенно.
 * - Сдвиг пальца дальше 8 px, прокрутка или отмена касания снимают нажатие.
 * - Выключить для элемента: data-no-press. prefers-reduced-motion: без сжатия, только затемнение.
 * - Там, где подключён b-press.js (арена, афиша), поведение не дублируем: ставим только стиль.
 */
(function (global) {
  'use strict';

  var doc = global.document;
  if (!doc || global.__gaPress) return;
  global.__gaPress = true;

  var SEL = [
    'button', 'a[href]', '[role="button"]', '[role="tab"]', '[role="menuitem"]', 'summary',
    'label[for]', '[data-action]', '[data-act]', '[data-intent-mode]', '.ga-press',
  ].join(',');
  var MIN_HOLD_MS = 110;
  var MOVE_PX = 8;
  var SOFT_HEIGHT = 72;

  var css = doc.createElement('style');
  css.setAttribute('data-ga-press', '');
  css.textContent =
    ':where(button,a[href],[role="button"],[role="tab"],summary,label[for],[data-action],[data-act]){' +
    'transition:scale .42s cubic-bezier(.22,1.15,.36,1),filter .18s ease}' +
    '.ga-pressed{scale:.97;filter:brightness(.95);transition-duration:70ms,70ms!important}' +
    '.ga-pressed--soft{scale:1;filter:brightness(.94)}' +
    // У .ga-press своё сжатие по :active — не складываем два.
    '.ga-press.ga-pressed{transform:none!important}' +
    '@media (prefers-reduced-motion:reduce){.ga-pressed{scale:1}}';
  (doc.head || doc.documentElement).appendChild(css);

  // b-press.js уже ведёт нажатия (класс b-press) — не дублируем.
  if (doc.querySelector('script[src*="b-press.js"]')) return;

  doc.addEventListener('touchstart', function () {}, { passive: true });

  var el = null;
  var pointer = null;
  var x0 = 0;
  var y0 = 0;
  var t0 = 0;
  var releaseTimer = null;

  function pressable(node) {
    var hit = node && node.closest ? node.closest(SEL) : null;
    if (!hit || hit.disabled || hit.getAttribute('aria-disabled') === 'true' || hit.closest('[data-no-press]')) return null;
    return hit;
  }

  function off(target) {
    if (target) target.classList.remove('ga-pressed', 'ga-pressed--soft');
  }

  function clear() {
    if (releaseTimer) { global.clearTimeout(releaseTimer); releaseTimer = null; }
    off(el);
    el = null;
    pointer = null;
  }

  doc.addEventListener('pointerdown', function (e) {
    if (e.button) return;
    var hit = pressable(e.target);
    if (!hit) return;
    clear();
    el = hit;
    pointer = e.pointerId;
    x0 = e.clientX;
    y0 = e.clientY;
    t0 = e.timeStamp;
    var r = hit.getBoundingClientRect();
    hit.classList.add('ga-pressed');
    if (r.height > SOFT_HEIGHT || r.width > global.innerWidth * 0.9) hit.classList.add('ga-pressed--soft');
  }, { passive: true });

  doc.addEventListener('pointermove', function (e) {
    if (pointer === null || e.pointerId !== pointer) return;
    if (Math.hypot(e.clientX - x0, e.clientY - y0) > MOVE_PX) clear();
  }, { passive: true });

  doc.addEventListener('pointerup', function (e) {
    if (pointer === null || e.pointerId !== pointer) return;
    var target = el;
    var left = MIN_HOLD_MS - (e.timeStamp - t0);
    pointer = null;
    el = null;
    if (left > 0) {
      releaseTimer = global.setTimeout(function () { releaseTimer = null; off(target); }, left);
    } else {
      off(target);
    }
  }, { passive: true });

  doc.addEventListener('pointercancel', clear, { passive: true });
  doc.addEventListener('scroll', clear, { passive: true, capture: true });
  global.addEventListener('pagehide', clear);
})(window);
