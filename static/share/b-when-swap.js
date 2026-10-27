/**
 * Главная: «Сегодня · Завтра · В выходные · День…» без перезагрузки.
 * Ползунок едет в момент нажатия; страница того же URL грузится фоном и вливается
 * в текущую морфом: совпавшие узлы не трогаются (фото не мигают), полоса и карта
 * остаются теми же элементами — на них висят переходы и обработчики.
 * Любой сбой — обычный переход по ссылке.
 */
(function () {
  'use strict';

  var main = document.querySelector('main.b-page');
  if (!main || !main.querySelector('.b-when') || !window.fetch || !window.DOMParser || !history.pushState) return;

  // Лист дней календаря (TASK-337): только кнопки дней; фон и «закрыть» — обычные якоря.
  var LINK_SEL = '.b-when a[href], .b-days a[href], .b-sheet__grid a[href]';
  // Классы, которые вешают скрипты страницы, а не сервер: при сравнении их не видно.
  var LIVE_CLASSES = ['is-ready', 'b-reveal', 'is-in', 'b-press', 'is-hot', 'is-live'];
  var CACHE_MS = 60000;
  var SLOW_MS = 180;
  var COUNT_MS = 450;

  var cache = {};
  var seq = 0;

  function sameView(a) {
    return a.origin === location.origin && a.pathname === location.pathname;
  }

  function load(url) {
    var hit = cache[url];
    if (hit && Date.now() - hit.at < CACHE_MS) return hit.p;
    var p = fetch(url, { credentials: 'same-origin', headers: { Accept: 'text/html' } }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.text();
    });
    p.catch(function () {
      if (cache[url] && cache[url].p === p) delete cache[url];
    });
    cache[url] = { at: Date.now(), p: p };
    return p;
  }

  function strip() {
    return main.querySelector('.b-when');
  }

  function markStrip(url) {
    var nav = strip();
    var links = nav.querySelectorAll('a');
    var want = new URL(url, location.href).searchParams.get('when');
    var at = -1;
    for (var i = 0; i < links.length; i++) {
      if (want && new URL(links[i].href).searchParams.get('when') === want) at = i;
    }
    // «/» без when: окно выбирает сервер (после 21:00 — завтра), ждём ответа.
    if (at < 0) return;
    for (var j = 0; j < links.length; j++) {
      if (j === at) links[j].setAttribute('aria-current', 'true');
      else links[j].removeAttribute('aria-current');
    }
    nav.style.setProperty('--when-i', String(at));
  }

  function syncStrip(next) {
    var nav = strip();
    nav.setAttribute('style', next.getAttribute('style') || '');
    var a = nav.querySelectorAll('a');
    var b = next.querySelectorAll('a');
    for (var i = 0; i < a.length && i < b.length; i++) {
      if (b[i].hasAttribute('aria-current')) a[i].setAttribute('aria-current', 'true');
      else a[i].removeAttribute('aria-current');
      a[i].setAttribute('href', b[i].getAttribute('href'));
    }
    // День выбран — у полосы нет активного пункта и нет ползунка (TASK-337); и обратно.
    var thumb = nav.querySelector('.b-when__thumb');
    var nextThumb = next.querySelector('.b-when__thumb');
    if (thumb && !nextThumb) nav.removeChild(thumb);
    else if (!thumb && nextThumb) nav.insertBefore(document.importNode(nextThumb, true), nav.firstChild);
  }

  function key(el) {
    var cls = Array.prototype.filter.call(el.classList, function (c) {
      return LIVE_CLASSES.indexOf(c) < 0;
    });
    return el.tagName + '.' + cls.join(' ');
  }

  function scrub(el) {
    var all = [el].concat(Array.prototype.slice.call(el.querySelectorAll('*')));
    for (var i = 0; i < all.length; i++) {
      for (var k = 0; k < LIVE_CLASSES.length; k++) all[i].classList.remove(LIVE_CLASSES[k]);
      if (all[i].getAttribute('class') === '') all[i].removeAttribute('class');
      if (all[i].style && all[i].style.transitionDelay) {
        all[i].style.transitionDelay = '';
        if (!all[i].getAttribute('style')) all[i].removeAttribute('style');
      }
    }
    return el;
  }

  function same(o, n) {
    return scrub(o.cloneNode(true)).isEqualNode(n);
  }

  function hasText(el) {
    for (var c = el.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3 && c.nodeValue.trim()) return true;
    }
    return false;
  }

  function copyAttrs(to, from) {
    var keep = LIVE_CLASSES.filter(function (c) { return to.classList.contains(c); });
    var i;
    for (i = to.attributes.length - 1; i >= 0; i--) {
      if (!from.hasAttribute(to.attributes[i].name)) to.removeAttribute(to.attributes[i].name);
    }
    for (i = 0; i < from.attributes.length; i++) {
      to.setAttribute(from.attributes[i].name, from.attributes[i].value);
    }
    for (i = 0; i < keep.length; i++) to.classList.add(keep[i]);
  }

  // Совпавший узел остаётся тем же элементом и на том же месте: перестановка обрывает
  // CSS-переходы, а замена — перезапускает загрузку фото и снимает обработчики (карта).
  function morph(oldParent, newParent) {
    var olds = Array.prototype.slice.call(oldParent.children);
    var used = [];
    var wanted = [];
    Array.prototype.forEach.call(newParent.children, function (n) {
      var o = null;
      for (var i = 0; i < olds.length; i++) {
        if (used.indexOf(i) < 0 && key(olds[i]) === key(n)) {
          o = olds[i];
          used.push(i);
          break;
        }
      }
      if (o && o.matches('.b-when')) {
        syncStrip(n);
        wanted.push(o);
      } else if (o && same(o, n)) {
        wanted.push(o);
      } else if (o && o.children.length && n.children.length && !hasText(o) && !hasText(n)) {
        copyAttrs(o, n);
        morph(o, n);
        wanted.push(o);
      } else {
        wanted.push(document.importNode(n, true));
      }
    });
    for (var j = 0; j < wanted.length; j++) {
      if (oldParent.children[j] !== wanted[j]) oldParent.insertBefore(wanted[j], oldParent.children[j] || null);
    }
    while (oldParent.children.length > wanted.length) oldParent.removeChild(oldParent.lastElementChild);
  }

  function counts() {
    return Array.prototype.map.call(main.querySelectorAll('.b-count'), function (el) {
      return parseInt(el.textContent, 10) || 0;
    });
  }

  function rollCounts(before) {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    Array.prototype.forEach.call(main.querySelectorAll('.b-count'), function (el, i) {
      var from = before[i];
      var to = parseInt(el.getAttribute('data-count'), 10);
      if (from == null || !isFinite(to) || from === to) return;
      var t0 = performance.now();
      (function frame(now) {
        var t = Math.min(1, (now - t0) / COUNT_MS);
        el.textContent = String(Math.round(from + (to - from) * (1 - Math.pow(1 - t, 3))));
        if (t < 1) requestAnimationFrame(frame);
      })(t0);
    });
  }

  function show(url, push) {
    var my = ++seq;
    var slow = setTimeout(function () {
      if (my === seq) main.classList.add('is-swapping');
    }, SLOW_MS);
    return load(url)
      .then(function (html) {
        if (my !== seq) return;
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var next = doc.querySelector('main.b-page');
        if (!next || !next.querySelector('.b-when')) throw new Error('no main');
        var before = counts();
        if (push) history.pushState({ bWhen: 1 }, '', url);
        morph(main, next);
        if (doc.title) document.title = doc.title;
        rollCounts(before);
      })
      .catch(function () {
        if (my === seq) location.href = url;
      })
      .then(function () {
        clearTimeout(slow);
        if (my === seq) main.classList.remove('is-swapping');
      });
  }

  function linkFrom(e) {
    var a = e.target && e.target.closest ? e.target.closest(LINK_SEL) : null;
    return a && sameView(a) ? a : null;
  }

  // Префетч до клика: pointerdown опережает click на 50–100 мс, наведение — ещё больше.
  document.addEventListener('pointerdown', function (e) {
    var a = e.button === 0 && linkFrom(e);
    if (a) load(a.href);
  }, { passive: true });
  document.addEventListener('pointerover', function (e) {
    var a = e.pointerType === 'mouse' && linkFrom(e);
    if (a) load(a.href);
  }, { passive: true });

  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = linkFrom(e);
    if (!a || a.target) return;
    e.preventDefault();
    if (a.href === location.href) return;
    strip().classList.add('is-live');
    if (a.closest('.b-when')) markStrip(a.href);
    closeSheet();
    show(a.href, true);
  });

  // Лист дней календаря (TASK-337). С JS он открывается классом, а не якорем: pushState не сбрасывает
  // :target, и после выбора дня лист остался бы открытым. Без JS работает якорь #when-days.
  function sheet() {
    return document.getElementById('when-days');
  }

  function closeSheet() {
    var el = sheet();
    if (el) el.classList.remove('is-open');
  }

  document.addEventListener('click', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('a.b-cal, .b-sheet__bg') : null;
    if (!el || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    if (el.classList.contains('b-cal')) {
      var open = sheet();
      if (!open) return;
      open.classList.add('is-open');
      var current = open.querySelector('.b-dayc[aria-current="true"]') || open.querySelector('.b-dayc');
      if (current) current.focus({ preventScroll: true });
    } else {
      closeSheet();
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeSheet();
  });

  history.replaceState({ bWhen: 1 }, '', location.href);
  window.addEventListener('popstate', function (e) {
    if (!e.state || !e.state.bWhen) return;
    strip().classList.add('is-live');
    markStrip(location.href);
    show(location.href, false);
  });
})();
