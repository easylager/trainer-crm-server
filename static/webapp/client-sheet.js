/**
 * Базовая нижняя шторка экранов «Я» (TASK-371 S1).
 * ClientSheet.open({ labelledBy, content, onClose }) → { close, el }.
 * Одна шторка за раз: новая закрывает предыдущую сразу.
 */
(function (root) {
  'use strict';

  var current = null;
  var locks = 0;
  var lockSaved = null;

  function motionOff() {
    var mq = root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)');
    return !!(mq && mq.matches);
  }

  function lockScroll() {
    locks += 1;
    if (locks !== 1) return;
    var html = document.documentElement;
    var body = document.body;
    lockSaved = {
      y: root.scrollY || root.pageYOffset || 0,
      htmlOverflow: html.style.overflow,
      bodyOverflow: body.style.overflow,
      bodyPosition: body.style.position,
      bodyTop: body.style.top,
      bodyWidth: body.style.width,
    };
    html.style.overflow = 'hidden';
    body.style.overflow = 'hidden';
    body.style.position = 'fixed';
    body.style.top = '-' + lockSaved.y + 'px';
    body.style.width = '100%';
  }

  function unlockScroll() {
    if (locks === 0) return;
    locks -= 1;
    if (locks !== 0 || !lockSaved) return;
    var html = document.documentElement;
    var body = document.body;
    var y = lockSaved.y;
    html.style.overflow = lockSaved.htmlOverflow;
    body.style.overflow = lockSaved.bodyOverflow;
    body.style.position = lockSaved.bodyPosition;
    body.style.top = lockSaved.bodyTop;
    body.style.width = lockSaved.bodyWidth;
    lockSaved = null;
    if (root.scrollTo) root.scrollTo(0, y);
  }

  function tgBack() {
    var tg = root.Telegram && root.Telegram.WebApp;
    return tg && tg.BackButton ? tg.BackButton : null;
  }

  function focusable(sheet) {
    var sel = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return sheet.querySelectorAll(sel);
  }

  function open(opts) {
    opts = opts || {};
    if (current) current.close(true);

    var opener = document.activeElement;
    var layer = document.createElement('div');
    layer.className = 'cs-root';

    var backdrop = document.createElement('div');
    backdrop.className = 'cs-backdrop';

    var sheet = document.createElement('section');
    sheet.className = 'cs-sheet';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    sheet.setAttribute('tabindex', '-1');
    if (opts.labelledBy) sheet.setAttribute('aria-labelledby', opts.labelledBy);

    var handle = document.createElement('div');
    handle.className = 'cs-handle';
    handle.setAttribute('aria-hidden', 'true');

    var body = document.createElement('div');
    body.className = 'cs-body';
    if (opts.content && opts.content.nodeType === 1) body.appendChild(opts.content);

    sheet.appendChild(handle);
    sheet.appendChild(body);
    layer.appendChild(backdrop);
    layer.appendChild(sheet);
    document.body.appendChild(layer);
    var scrollers = body.querySelectorAll('.cs-scroll');
    for (var s = 0; s < scrollers.length; s++) watchScroll(scrollers[s]);

    var record = { el: sheet, close: null };
    var state = 'open';
    var timer = null;
    var backHeld = false;
    var backWasVisible = false;
    var drag = null;
    var swallowClick = false;

    function place() {
      var vv = root.visualViewport;
      if (!vv) return;
      var top = vv.offsetTop || 0;
      var height = vv.height;
      layer.style.top = top + 'px';
      layer.style.height = height + 'px';
      layer.style.bottom = 'auto';
      sheet.style.maxHeight = Math.max(0, height - 100) + 'px';
    }

    function onViewport() {
      place();
    }

    function holdBack() {
      var btn = tgBack();
      if (!btn || backHeld) return;
      try {
        backWasVisible = !!btn.isVisible;
        if (typeof btn.onClick === 'function') btn.onClick(onTelegramBack);
        if (typeof btn.show === 'function') btn.show();
        backHeld = true;
      } catch (err) { /* старый клиент Telegram */ }
    }

    function releaseBack() {
      if (!backHeld) return;
      backHeld = false;
      var btn = tgBack();
      if (!btn) return;
      try {
        if (typeof btn.offClick === 'function') btn.offClick(onTelegramBack);
        if (!backWasVisible && typeof btn.hide === 'function') btn.hide();
      } catch (err) { /* старый клиент Telegram */ }
    }

    function finish() {
      if (state === 'done') return;
      state = 'done';
      if (root.visualViewport) {
        root.visualViewport.removeEventListener('resize', onViewport);
        root.visualViewport.removeEventListener('scroll', onViewport);
      }
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('pointerup', onPointerUp);
      document.removeEventListener('pointercancel', onPointerUp);
      document.removeEventListener('touchmove', onTouchMove);
      document.removeEventListener('touchend', onTouchEnd);
      document.removeEventListener('touchcancel', onTouchCancel);
      if (layer.parentNode) layer.parentNode.removeChild(layer);
      if (current === record) current = null;
      releaseVerticalSwipe();
      unlockScroll();
      if (typeof opts.onClose === 'function') opts.onClose();
      if (!current && opener && typeof opener.focus === 'function') {
        var connected = opener.isConnected !== false;
        if (connected) opener.focus();
      }
    }

    function dismiss(immediate) {
      if (state === 'done') return;
      if (state === 'closing' && !immediate) return;
      sheet.setAttribute('data-closing', '1');
      releaseBack();
      endDrag();
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      if (immediate || motionOff()) {
        state = 'closing';
        finish();
        return;
      }
      state = 'closing';
      layer.classList.remove('is-open');
      sheet.style.transform = '';
      timer = setTimeout(finish, 220);
    }

    function onTelegramBack() {
      dismiss(false);
    }

    /* Жест вниз в Telegram сворачивает мини-приложение раньше, чем его видит шторка. */
    function webApp() {
      return root.Telegram && root.Telegram.WebApp ? root.Telegram.WebApp : null;
    }

    function holdVerticalSwipe() {
      var app = webApp();
      if (!app || typeof app.disableVerticalSwipes !== 'function') return;
      try { app.disableVerticalSwipes(); } catch (err) { /* старый клиент */ }
    }

    function releaseVerticalSwipe() {
      if (current) return;
      var body = document.body;
      if (body && body.classList && body.classList.contains('client-shell-more-open')) return;
      var app = webApp();
      if (!app || typeof app.enableVerticalSwipes !== 'function') return;
      try { app.enableVerticalSwipes(); } catch (err) { /* старый клиент */ }
    }

    function targetElement(event) {
      var target = event && event.target;
      if (target && target.nodeType === 3) target = target.parentNode;
      return target;
    }

    function scrollOf(target) {
      if (!target || typeof target.closest !== 'function') return null;
      return target.closest('.cs-scroll');
    }

    /* Список в начале отдаёт жест шторке. Строки «Мой каток» и «За кого болею» — это label
       на всю ширину: если считать метку запретом, свайп по списку не начнётся никогда. */
    function blockedDrag(target) {
      if (!target || typeof target.closest !== 'function') return false;
      var list = scrollOf(target);
      if (list) return list.scrollTop > 1;
      return !!target.closest('button, a, input, textarea, select, label');
    }

    function watchScroll(list) {
      function sync() {
        /* pan-y на верху списка: браузер забирает вертикальный жест и не даёт его отменить.
           Пока прокрутка в начале — жест наш (шторка). Ниже — снова прокрутка списка. */
        list.style.touchAction = list.scrollTop > 1 ? 'pan-y' : 'none';
      }
      sync();
      list.addEventListener('scroll', sync);
    }

    function onPointerDown(event) {
      if (state !== 'open') return;
      holdVerticalSwipe();
      if (event.button != null && event.button !== 0) return;
      var target = targetElement(event);
      if (blockedDrag(target)) return;
      if (typeof event.clientY !== 'number') return;
      drag = { y: event.clientY, last: event.clientY, moved: false };
      sheet.style.transition = 'none';
    }

    function onPointerMove(event) {
      if (!drag || typeof event.clientY !== 'number') return;
      drag.last = event.clientY;
      var dy = Math.max(0, event.clientY - drag.y);
      if (dy > 8) drag.moved = true;
      sheet.style.transform = 'translateY(' + dy + 'px)';
    }

    function endDrag() {
      drag = null;
    }

    function onPointerUp(event) {
      if (!drag) return;
      /* pointercancel приходит без координат: берём последнюю точку движения. */
      var y = typeof event.clientY === 'number' ? event.clientY : drag.last;
      var dy = Math.max(0, y - drag.y);
      if (drag.moved) swallowClick = true;
      endDrag();
      sheet.style.transition = '';
      sheet.style.transform = '';
      if (dy > 80) dismiss(false);
    }

    function onClick(event) {
      if (!swallowClick) return;
      swallowClick = false;
      if (event.preventDefault) event.preventDefault();
      if (event.stopPropagation) event.stopPropagation();
    }

    /* Список .cs-scroll на тач-экране забирает вертикальный жест (touch-action: pan-y), и pointer-события
       до нас не доходят. Когда список прокручен к началу, жест вниз ведём через touch-события. */
    var touch = null;

    function scrollAncestor(target) {
      if (!target || typeof target.closest !== 'function') return null;
      return target.closest('.cs-scroll');
    }

    function onTouchStart(event) {
      touch = null;
      if (state !== 'open') return;
      holdVerticalSwipe();
      var t = event.touches && event.touches[0];
      var list = scrollAncestor(targetElement(event));
      if (!t || !list || typeof t.clientY !== 'number') return;
      touch = { y: t.clientY, last: t.clientY, list: list, active: false };
    }

    function onTouchMove(event) {
      if (!touch) return;
      var t = event.touches && event.touches[0];
      if (!t || typeof t.clientY !== 'number') return;
      var dy = t.clientY - touch.y;
      if (!touch.active) {
        if (touch.list.scrollTop > 1) { touch = null; return; }
        /* Короткий рывок вверх в начале жеста — шум пальца, не отказ от закрытия. */
        if (dy < -8) { touch = null; return; }
        if (dy > 0 && event.cancelable !== false && event.preventDefault) event.preventDefault();
        if (dy < 8) return;
        touch.active = true;
        sheet.style.transition = 'none';
      }
      touch.last = t.clientY;
      if (event.cancelable !== false && event.preventDefault) event.preventDefault();
      sheet.style.transform = 'translateY(' + Math.max(0, dy) + 'px)';
    }

    function onTouchEnd() {
      var cur = touch;
      touch = null;
      if (!cur || !cur.active) return;
      var dy = Math.max(0, cur.last - cur.y);
      if (cur.active) swallowClick = true;
      sheet.style.transition = '';
      sheet.style.transform = '';
      if (dy > 80) dismiss(false);
    }

    function onTouchCancel() {
      onTouchEnd();
    }

    function onKey(event) {
      if (current !== record || state !== 'open') return;
      if (event.key === 'Escape') {
        if (event.preventDefault) event.preventDefault();
        dismiss(false);
        return;
      }
      if (event.key !== 'Tab') return;
      var items = focusable(sheet);
      if (!items.length) {
        if (event.preventDefault) event.preventDefault();
        sheet.focus();
        return;
      }
      var first = items[0];
      var last = items[items.length - 1];
      var active = document.activeElement;
      if (event.shiftKey && (active === first || active === sheet || !sheet.contains(active))) {
        if (event.preventDefault) event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        if (event.preventDefault) event.preventDefault();
        first.focus();
      }
    }

    backdrop.addEventListener('click', function () {
      dismiss(false);
    });
    sheet.addEventListener('click', onClick, true);
    sheet.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp);
    document.addEventListener('pointercancel', onPointerUp);
    sheet.addEventListener('touchstart', onTouchStart, { passive: true });
    document.addEventListener('touchmove', onTouchMove, { passive: false });
    document.addEventListener('touchend', onTouchEnd);
    document.addEventListener('touchcancel', onTouchCancel);
    document.addEventListener('keydown', onKey);
    if (root.visualViewport) {
      root.visualViewport.addEventListener('resize', onViewport);
      root.visualViewport.addEventListener('scroll', onViewport);
    }

    record.close = dismiss;
    current = record;
    holdVerticalSwipe();
    lockScroll();
    holdBack();
    place();

    var raf = root.requestAnimationFrame || function (fn) { fn(); };
    raf(function () {
      if (state === 'open') {
        layer.classList.add('is-open');
        sheet.focus();
      }
    });

    return { close: function () { dismiss(false); }, el: sheet };
  }

  var api = { open: open };
  root.ClientSheet = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
