/**
 * Trainer mini apps: navigate to hub (trainer-home.html) preserving Telegram init_data in URL.
 * Wires #btnHome when present (DOM ready or immediately if DOM already loaded).
 */
(function () {
  function webappBasePath() {
    var p = window.location.pathname || '';
    return p.replace(/[^/]+$/, '') || '/webapp/';
  }

  function withInit(url) {
    var tg = window.Telegram && window.Telegram.WebApp;
    var initData = tg && tg.initData ? tg.initData : '';
    if (!initData) return url;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(initData);
  }

  /**
   * @param { { subscriptionCelebrationHint?: boolean, reopenGroupSlot?: number|string } } [opts]
   *   subscriptionCelebrationHint: append hub_celebrate=1 so hub can show banner if sessionStorage was cleared (Telegram WebView).
   *   reopenGroupSlot: trainer-home reopens group modal (return from booking detail opened from hub modal).
   */
  function navigateTrainerHome(opts) {
    opts = opts || {};
    /* Canonical app route is /webapp/trainer-home (no .html) — see src/api/app.py */
    var url = withInit(webappBasePath() + 'trainer-home');
    if (opts.subscriptionCelebrationHint) {
      url += (url.indexOf('?') >= 0 ? '&' : '?') + 'hub_celebrate=1';
    }
    if (opts.reopenGroupSlot != null && opts.reopenGroupSlot !== '') {
      var sid = parseInt(String(opts.reopenGroupSlot), 10);
      if (!isNaN(sid) && sid > 0) {
        url += (url.indexOf('?') >= 0 ? '&' : '?') + 'reopen_group_slot=' + encodeURIComponent(String(sid));
      }
    }
    window.location.href = url;
  }

  window.navigateTrainerHome = navigateTrainerHome;

  function canBrowserGoBack() {
    try {
      if (window.navigation && typeof window.navigation.canGoBack === 'function') {
        return window.navigation.canGoBack();
      }
    } catch (e) { /* older WebViews */ }
    return window.history && window.history.length > 1;
  }

  function wireBack() {
    var btn = document.getElementById('btnBack');
    if (!btn || btn.getAttribute('data-skip-history-back') === 'true') return;
    function sync() {
      btn.hidden = !canBrowserGoBack();
    }
    btn.onclick = function () {
      window.history.back();
    };
    sync();
    window.addEventListener('popstate', sync);
  }

  /*
   * Вложенный экран (TASK-314): сверху одна кнопка «‹ Откуда», системная «Назад» Telegram
   * делает то же. Раньше было «Главная» + «Назад» — два выхода, и «Главная» уводила мимо
   * «Профиля», откуда тренер пришёл. Корневые вкладки и анкета ведут шапку сами.
   */
  var SELF_MANAGED = {
    'trainer-home': 1, 'schedule-editor': 1, 'trainer-clients': 1, 'trainer-catalog': 1,
    'trainer-account': 1, 'trainer-collective': 1, 'trainer-profile': 1, schedule: 1,
  };
  var ORIGIN_LABELS = {
    'trainer-home': 'Главная',
    'trainer-account': 'Профиль',
    'schedule-editor': 'Расписание',
    'trainer-clients': 'Клиенты',
    'trainer-catalog': 'Каталог',
    'trainer-referral': 'Приглашение',
    'trainer-requests': 'Заявки',
    'trainer-stats': 'Статистика',
  };
  var DEFAULT_ORIGIN = { 'referral-rules': 'trainer-referral' };

  function pageKey(pathname) {
    return String(pathname || '').replace(/\.html$/, '').replace(/^.*\//, '');
  }

  function resolveOrigin(here) {
    var store = 'trainer_origin:' + here;
    var key = null;
    try {
      var ref = document.referrer ? new URL(document.referrer) : null;
      if (ref && ref.origin === window.location.origin) {
        var k = pageKey(ref.pathname);
        if (k !== here && ORIGIN_LABELS[k]) key = k;
      }
    } catch (e) { /* без referrer */ }
    try {
      if (key) sessionStorage.setItem(store, key);
      else key = sessionStorage.getItem(store);
    } catch (e) { /* приватный режим */ }
    if (!key || !ORIGIN_LABELS[key]) key = DEFAULT_ORIGIN[here] || 'trainer-account';
    return key;
  }

  function wireNestedHeader(here) {
    var nav = document.querySelector('.trainer-mini-nav');
    var origin = (nav && nav.querySelector('.btn-app-home')) || document.getElementById('btnHomeList');
    if (!origin) return false;
    var key = resolveOrigin(here);
    var back = document.getElementById('btnBack');
    var pageOwnsBack = !!back && back.getAttribute('data-skip-history-back') === 'true';

    function goOrigin() {
      var url = withInit(webappBasePath() + key);
      try {
        var ref = document.referrer ? new URL(document.referrer) : null;
        if (ref && ref.origin === window.location.origin && pageKey(ref.pathname) === key && canBrowserGoBack()) {
          window.history.back();
          return;
        }
      } catch (e) { /* */ }
      window.location.href = url;
    }

    origin.textContent = '‹ ' + ORIGIN_LABELS[key];
    origin.classList.add('btn-app-home--origin');
    origin.setAttribute('aria-label', 'Назад: ' + ORIGIN_LABELS[key]);
    origin.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      goOrigin();
    }, true);

    if (back && !pageOwnsBack) back.hidden = true;
    /* Экран сам показывает «Назад» во внутреннем виде (заявка, абонемент) — тогда «‹ Откуда» прячем. */
    function syncPair() {
      var hide = !!(back && pageOwnsBack && !back.hidden);
      origin.hidden = hide;
      /* Тема держит display у .btn-app-home с !important — одного hidden мало. */
      origin.style.setProperty('display', hide ? 'none' : '', hide ? 'important' : '');
    }
    if (back && pageOwnsBack && typeof MutationObserver === 'function') {
      new MutationObserver(syncPair).observe(back, { attributes: true, attributeFilter: ['hidden'] });
    }
    syncPair();

    var tg = window.Telegram && window.Telegram.WebApp;
    if (tg && tg.BackButton) {
      try {
        tg.BackButton.onClick(function () {
          if (back && pageOwnsBack && !back.hidden) back.click();
          else goOrigin();
        });
        tg.BackButton.show();
      } catch (e) { /* старые клиенты */ }
    }
    return true;
  }

  function wire() {
    var here = pageKey(window.location.pathname);
    if (!SELF_MANAGED[here] && wireNestedHeader(here)) return;
    var b = document.getElementById('btnHome');
    if (b) b.onclick = navigateTrainerHome;
    wireBack();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
