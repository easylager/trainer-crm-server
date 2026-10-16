/**
 * Лёгкие микровзаимодействия публички: появление блоков, набегающий счётчик,
 * подпись «через N мин» у ближайшего сеанса. Без библиотек.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    factory().wire(root);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var SOON_MAX = 120;
  var REVEAL_MS = 50;
  var COUNT_MS = 700;

  function reduced(win) {
    return !!(win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function minutesUntil(iso, nowMs) {
    var start = Date.parse(iso);
    if (!isFinite(start)) return null;
    return Math.round((start - nowMs) / 60000);
  }

  function soonLabel(minutes) {
    if (minutes == null || minutes <= 0 || minutes > SOON_MAX) return '';
    return 'через ' + minutes + ' мин';
  }

  function easeOut(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function wireSoon(doc, win) {
    function refresh() {
      var nodes = doc.querySelectorAll('.b-soon');
      var now = Date.now();
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var label = soonLabel(minutesUntil(el.getAttribute('data-starts'), now));
        var text = el.querySelector('.b-soon__label');
        if (!label) {
          el.hidden = true;
          continue;
        }
        el.hidden = false;
        if (text) text.textContent = label;
      }
    }
    refresh();
    win.setInterval(refresh, 60000);
  }

  function navigationType(win) {
    var list = win.performance && win.performance.getEntriesByType && win.performance.getEntriesByType('navigation');
    return list && list[0] ? list[0].type : '';
  }

  function wireReveal(doc, win) {
    if (reduced(win) || typeof win.IntersectionObserver !== 'function') return;
    if (navigationType(win) === 'back_forward') return;
    var nodes = doc.querySelectorAll('.b-card2, a.b-tile, a.b-city');
    var pending = [];
    var limit = win.innerHeight - 8;
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.getBoundingClientRect().top < limit) continue;
      el.classList.add('b-reveal');
      pending.push(el);
    }
    if (!pending.length) return;
    var io = new win.IntersectionObserver(
      function (entries) {
        var shown = [];
        for (var j = 0; j < entries.length; j++) {
          if (entries[j].isIntersecting) shown.push(entries[j].target);
        }
        shown.sort(function (a, b) {
          return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
        });
        for (var k = 0; k < shown.length; k++) {
          shown[k].style.transitionDelay = k * REVEAL_MS + 'ms';
          shown[k].classList.add('is-in');
          io.unobserve(shown[k]);
        }
      },
      { threshold: 0.12 }
    );
    for (var n = 0; n < pending.length; n++) io.observe(pending[n]);
  }

  function runCount(el, win) {
    var target = parseInt(el.getAttribute('data-count'), 10);
    if (!isFinite(target) || target < 0) return;
    if (reduced(win)) {
      el.textContent = String(target);
      return;
    }
    var start = win.performance.now();
    function frame(now) {
      var t = Math.min(1, (now - start) / COUNT_MS);
      el.textContent = String(Math.round(target * easeOut(t)));
      if (t < 1) win.requestAnimationFrame(frame);
      else el.textContent = String(target);
    }
    el.textContent = '0';
    win.requestAnimationFrame(frame);
  }

  function wireCounts(doc, win) {
    var nodes = doc.querySelectorAll('.b-count');
    if (!nodes.length) return;
    if (reduced(win) || typeof win.IntersectionObserver !== 'function') return;
    var io = new win.IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (!entries[i].isIntersecting) continue;
          runCount(entries[i].target, win);
          io.unobserve(entries[i].target);
        }
      },
      { threshold: 0.6 }
    );
    for (var j = 0; j < nodes.length; j++) io.observe(nodes[j]);
  }

  function wire(win) {
    var doc = win.document;
    if (!doc) return;
    wireSoon(doc, win);
    if (doc.readyState === 'loading') {
      doc.addEventListener('DOMContentLoaded', function () {
        wireReveal(doc, win);
        wireCounts(doc, win);
      });
    } else {
      wireReveal(doc, win);
      wireCounts(doc, win);
    }
  }

  return {
    SOON_MAX: SOON_MAX,
    minutesUntil: minutesUntil,
    soonLabel: soonLabel,
    easeOut: easeOut,
    wire: wire,
  };
});
