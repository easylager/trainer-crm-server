/**
 * Плашка «Открыть в Telegram»: в потоке у начала страницы, после прокрутки — пилюля внизу.
 * Заполнитель той же высоты убирает CLS, когда nav уходит в position: fixed.
 */
(function () {
  'use strict';

  var dock = document.querySelector('.b-tgdock');
  if (!dock || document.body.hasAttribute('data-client-shell')) return;

  var host = dock.closest('.b-tgdock-host');
  var spacer = host && host.querySelector('.b-tgdock__spacer');
  var inner = dock.querySelector('.b-tgdock__inner');
  var THRESHOLD = 48;

  function dockBlockHeight() {
    if (!inner) return dock.offsetHeight;
    var style = window.getComputedStyle(dock);
    return (
      inner.offsetHeight +
      parseFloat(style.paddingTop || 0) +
      parseFloat(style.paddingBottom || 0)
    );
  }

  function sync() {
    var floating = window.scrollY > THRESHOLD;
    if (floating) {
      if (spacer) spacer.style.height = dockBlockHeight() + 'px';
    } else if (spacer) {
      spacer.style.height = '0px';
    }
    dock.classList.toggle('is-floating', floating);
  }

  window.addEventListener('scroll', sync, { passive: true });
  window.addEventListener('resize', sync);
  if (typeof ResizeObserver === 'function' && inner) {
    new ResizeObserver(sync).observe(inner);
  }
  sync();
})();
