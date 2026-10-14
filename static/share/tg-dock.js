/**
 * Плашка «Открыть в Telegram»: в потоке у начала страницы; когда её место уходит за экран —
 * пилюля внизу. Заполнитель той же высоты убирает CLS, когда nav уходит в position: fixed.
 */
(function () {
  'use strict';

  var dock = document.querySelector('.b-tgdock');
  if (!dock || document.body.hasAttribute('data-client-shell')) return;

  var host = dock.closest('.b-tgdock-host');
  var spacer = host && host.querySelector('.b-tgdock__spacer');
  var inner = dock.querySelector('.b-tgdock__inner');
  var THRESHOLD = 48;

  // Высота плашки в потоке. Мерить можно только пока она в потоке: плавающая
  // пилюля ниже, и заполнитель по ней дёргал контент на разницу высот.
  var inFlowHeight = 0;
  // Пилюлей плашка становится, только когда её место в потоке ушло за край экрана:
  // заполнитель тогда никто не видит — ни пустого блока, ни прыжка ленты.
  var hostVisible = true;

  function sync() {
    var floating = window.scrollY > THRESHOLD && !hostVisible;
    if (!dock.classList.contains('is-floating')) inFlowHeight = dock.offsetHeight;
    if (spacer) spacer.style.height = floating ? inFlowHeight + 'px' : '0px';
    dock.classList.toggle('is-floating', floating);
  }

  if (host && typeof IntersectionObserver === 'function') {
    new IntersectionObserver(function (entries) {
      hostVisible = entries[entries.length - 1].isIntersecting;
      sync();
    }).observe(host);
  } else {
    hostVisible = false;
  }

  window.addEventListener('scroll', sync, { passive: true });
  window.addEventListener('resize', sync);
  if (typeof ResizeObserver === 'function' && inner) {
    new ResizeObserver(sync).observe(inner);
  }
  sync();
})();
