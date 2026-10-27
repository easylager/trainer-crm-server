/**
 * Поле ввода над клавиатурой в полноэкранных листах профиля тренера (#onboardingFlow).
 *
 * Расчёт чистый: числа на входе, число на выходе — так его можно проверить без телефона.
 * Прокручиваем ТОЛЬКО тело листа (#obFlowBody). ``scrollIntoView`` двигает ещё и саму страницу,
 * а на iOS это и есть «скачок»: страница уезжает вниз-вверх под клавиатуру.
 */
(function (global, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (global) {
    global.ObFlowKeyboard = api;
  }
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  var MARGIN = 12;

  function num(v, fallback) {
    var n = Number(v);
    return isFinite(n) ? n : fallback;
  }

  /**
   * На сколько px прокрутить тело листа, чтобы поле было видно целиком.
   * Положительное — вниз, отрицательное — вверх, 0 — уже видно.
   * Поле выше видимой области — прижимаем его верх (там подпись и начало текста).
   */
  function revealDelta(fieldTop, fieldBottom, boxTop, boxBottom, margin) {
    var m = num(margin, MARGIN);
    var top = num(fieldTop, 0);
    var bottom = num(fieldBottom, top);
    var bTop = num(boxTop, 0);
    var bBottom = num(boxBottom, bTop);
    if (bBottom - bTop <= 2 * m) return 0; // видимая область схлопнулась — не гадаем
    if (bottom - top > bBottom - bTop - 2 * m) return top - (bTop + m);
    if (top < bTop + m) return top - (bTop + m);
    if (bottom > bBottom - m) return bottom - (bBottom - m);
    return 0;
  }

  /** Поставить поле к верху видимой области ещё до открытия клавиатуры. */
  function topAlignDelta(fieldTop, boxTop, margin) {
    return num(fieldTop, 0) - (num(boxTop, 0) + num(margin, MARGIN));
  }

  /** Прокручивать ли вообще: дрожание в доли пикселя только мешает. */
  function worthScrolling(delta) {
    return Math.abs(num(delta, 0)) >= 1;
  }

  return { revealDelta: revealDelta, topAlignDelta: topAlignDelta, worthScrolling: worthScrolling, MARGIN: MARGIN };
});
