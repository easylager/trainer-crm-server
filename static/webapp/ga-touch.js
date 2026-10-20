/*
 * Тактильный слой Mini App (TASK-308): отклик на касание и вибрация — одним языком на всех экранах.
 *
 * - Нажатие видно сразу: iOS WebKit включает :active только при слушателе touchstart на странице.
 * - Вибрация по атрибуту: <button data-haptic="select|tap|success|warning|error">. Срабатывает
 *   на click, не на касание — прокрутка не вибрирует. Два отклика подряд (< 80 мс) сливаются в один,
 *   чтобы атрибут и код страницы не дребезжали вместе.
 * - Сегменты .ga-seg--slide: подложка переезжает к выбранной кнопке (только transform).
 */
(function (global) {
  'use strict';

  var doc = global.document;
  var last = 0;

  function feedback() {
    var tg = global.Telegram && global.Telegram.WebApp;
    return tg && tg.HapticFeedback;
  }

  function haptic(kind) {
    var now = Date.now();
    if (now - last < 80) return;
    last = now;
    try {
      var h = feedback();
      if (!h) return;
      if (kind === 'select') h.selectionChanged();
      else if (kind === 'success' || kind === 'warning' || kind === 'error') h.notificationOccurred(kind);
      else h.impactOccurred(kind === 'medium' || kind === 'rigid' || kind === 'soft' ? kind : 'light');
    } catch (e) { /* без вибрации — не беда */ }
  }

  function placeThumb(seg) {
    var thumb = seg.querySelector(':scope > .ga-seg__thumb');
    var on = seg.querySelector('.ga-seg__btn[aria-selected="true"], .ga-seg__btn.is-on');
    if (!thumb) return;
    if (!on) { thumb.style.opacity = '0'; return; }
    thumb.style.width = on.offsetWidth + 'px';
    thumb.style.transform = 'translateX(' + on.offsetLeft + 'px)';
    thumb.style.opacity = '1';
  }

  function enhanceSeg(seg) {
    if (seg.__gaSlide) return;
    seg.__gaSlide = true;
    var thumb = doc.createElement('span');
    thumb.className = 'ga-seg__thumb';
    thumb.setAttribute('aria-hidden', 'true');
    seg.insertBefore(thumb, seg.firstChild);
    // Первая расстановка — без анимации, иначе подложка «въедет» при открытии страницы.
    seg.classList.add('ga-seg--still');
    placeThumb(seg);
    global.requestAnimationFrame(function () { seg.classList.remove('ga-seg--still'); });
    if (global.MutationObserver) {
      new global.MutationObserver(function () { placeThumb(seg); })
        .observe(seg, { subtree: true, attributes: true, attributeFilter: ['aria-selected', 'class', 'hidden'] });
    }
    // Сегмент мог быть скрыт при загрузке (ширина 0) — поставим подложку, когда он получит размер.
    if (global.ResizeObserver) new global.ResizeObserver(function () { placeThumb(seg); }).observe(seg);
  }

  function enhance(rootEl) {
    var list = (rootEl || doc).querySelectorAll('.ga-seg--slide');
    for (var i = 0; i < list.length; i += 1) enhanceSeg(list[i]);
  }

  // Тёмная тема языка хаба (--g-*) включается body.tg-dark; признак ставит client-mini-app-theme.js на html.
  function syncDark() {
    var b = doc.body;
    var h = doc.documentElement;
    if (b && b.classList && h && h.classList) b.classList.toggle('tg-dark', h.classList.contains('hub-is-dark'));
  }
  if (doc.body) syncDark();
  else doc.addEventListener('DOMContentLoaded', syncDark);
  if (global.MutationObserver && doc.documentElement) {
    new global.MutationObserver(syncDark).observe(doc.documentElement, { attributes: true, attributeFilter: ['class'] });
  }

  doc.addEventListener('touchstart', function () {}, { passive: true });
  doc.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('[data-haptic]') : null;
    if (t && !t.disabled) haptic(t.getAttribute('data-haptic'));
  }, true);
  global.addEventListener('resize', function () {
    var list = doc.querySelectorAll('.ga-seg--slide');
    for (var i = 0; i < list.length; i += 1) placeThumb(list[i]);
  });
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', function () { enhance(); });
  else enhance();

  global.GlideTouch = { haptic: haptic, enhance: enhance };
})(typeof window !== 'undefined' ? window : globalThis);
