/**
 * Trainer Mini App shell: bottom tab bar, «Ещё» sheet, navigate with init_data.
 * Exposes window.TrainerShell for inter-module communication.
 *
 * Drill-down detection is reactive:
 *   - schedule-editor: MutationObserver on #screenMain[class] — tab bar hides when
 *     main screen loses .active (booking-detail / decline opened).
 *   - trainer-clients: MutationObserver on #clientsSection[style] — tab bar hides
 *     when client detail replaces the list view.
 */
(function (global) {
  'use strict';

  var SHELL_VERSION = '202606114';

  var TAB_ICONS = {
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V9.5z"/></svg>',
    schedule: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    clients: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    more: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none"/></svg>',
  };

  var MORE_ITEMS = [
    {
      path: 'trainer-profile',
      label: 'Профиль',
      emoji: '👤',
      hint: 'Анкета, услуги и модерация',
    },
    {
      path: 'trainer-pass-products',
      label: 'Абонементы',
      emoji: '🎫',
      hint: 'Настройка и выдача клиентам',
    },
    {
      path: 'trainer-subscription',
      label: 'Подписка',
      emoji: '💳',
      hint: 'Тариф и способ оплаты',
    },
    {
      path: 'trainer-requests',
      label: 'Заявки',
      emoji: '📋',
      hint: 'Отклики клиентов и входящие запросы',
    },
    {
      path: 'trainer-stats',
      label: 'Статистика',
      emoji: '📊',
      hint: 'Выручка, посещаемость, активность',
    },
    {
      path: 'trainer-groups',
      label: 'Группы',
      emoji: '👥',
      hint: 'Групповые занятия и расписание',
    },
    {
      path: 'trainer-referral',
      label: 'Рефералы',
      emoji: '🎁',
      hint: 'Пригласи коллегу — получи бонус',
    },
  ];

  var MORE_CHEVRON =
    '<svg class="trainer-more-sheet__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M9 6l6 6-6 6"/></svg>';

  /** Pages whose route key maps to «Ещё» tab */
  var MORE_ROUTE_KEYS = [
    'trainer-requests',
    'trainer-profile',
    'trainer-pass-products',
    'trainer-subscription',
    'trainer-stats',
    'trainer-groups',
    'trainer-referral',
    'trainer-bookings',
    'trainer-faq',
  ];

  var state = {
    mode: 'hidden',
    tabBarVisible: true,
    moreOpen: false,
    forcedTab: null,
    onboardingData: null,
    onboardingLoaded: false,
  };

  /* ─── Telegram helpers ──────────────────────────────────────────────────── */

  function getTg() {
    return global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null;
  }

  function webappBasePath() {
    var p = global.location.pathname || '';
    return p.replace(/[^/]+$/, '') || '/webapp/';
  }

  function getInitData() {
    var rt = global.MiniAppRuntime;
    if (rt && typeof rt.getCredential === 'function') {
      var c = rt.getCredential();
      if (c) return c;
    }
    var tg = getTg();
    return tg && tg.initData ? String(tg.initData) : '';
  }

  function withInit(url) {
    var initData = getInitData();
    if (!initData) return url;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(initData);
  }

  function hapticSelection() {
    var tg = getTg();
    try {
      if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.selectionChanged === 'function') {
        tg.HapticFeedback.selectionChanged();
      }
    } catch (e) { /* */ }
  }

  /* ─── Route resolution ──────────────────────────────────────────────────── */

  function pathnameKey() {
    var p = (global.location.pathname || '').replace(/\/$/, '');
    var seg = p.split('/').pop() || '';
    return seg.replace(/\.html$/, '');
  }

  function resolveActiveTab() {
    if (state.forcedTab) return state.forcedTab;
    var key = pathnameKey();
    if (key === 'trainer-home') return 'home';
    if (key === 'schedule-editor') return 'schedule';
    if (key === 'trainer-clients') return 'clients';
    for (var i = 0; i < MORE_ROUTE_KEYS.length; i++) {
      if (key === MORE_ROUTE_KEYS[i]) return 'more';
    }
    return null;
  }

  function isMoreRoute() {
    return resolveActiveTab() === 'more';
  }

  function isSameTabRoute(path) {
    var targetKey = String(path || '').replace(/^\.\//, '').split('?')[0].split('#')[0];
    return targetKey === pathnameKey();
  }

  /* ─── Onboarding navigation guard ───────────────────────────────────────── */

  function onboardingBookingStepDone(data) {
    if (!data) return false;
    return !!(data.has_any_booking || data.has_confirmed_booking || data.has_upcoming_booking);
  }

  function onboardingAllComplete(data) {
    if (!data) return true;
    if (!onboardingBookingStepDone(data)) return false;
    if (data.is_active && data.profile_complete) return true;
    if (!data.is_active && data.schedule_unlocked && data.tt_minimal_complete) return true;
    return false;
  }

  function pathRouteKey(path) {
    return String(path || '').replace(/^\.\//, '').split('?')[0].split('#')[0];
  }

  /** Whether a shell route is reachable during «Первые шаги». */
  function evaluateOnboardingPath(path) {
    var data = state.onboardingData;
    if (!data || onboardingAllComplete(data)) return { allow: true };

    var key = pathRouteKey(path);
    if (key === 'trainer-home') return { allow: true };

    var ttOk = !!data.tt_minimal_complete;
    var schedUnlocked = !!(data.schedule_unlocked || data.is_active);

    if (!ttOk) {
      return {
        allow: false,
        title: 'Сначала анкета',
        hint: 'Завершите шаг «Расскажите о себе» в блоке «Первые шаги» на главной — тогда откроются остальные разделы.',
        primary: { path: 'trainer-home', label: 'Первые шаги' },
        secondary: null,
      };
    }

    if (key === 'schedule-editor' && schedUnlocked) return { allow: true };

    if (!onboardingBookingStepDone(data)) {
      return {
        allow: false,
        title: 'Сначала первая запись',
        hint: 'Сделайте тестовую или реальную запись на главной — разделы оживут после этого шага.',
        primary: { path: 'trainer-home', label: 'Первые шаги' },
        secondary: schedUnlocked ? { path: 'schedule-editor', label: 'Расписание' } : null,
      };
    }

    return { allow: true };
  }

  function ensureOnboardingNavSheet() {
    var id = 'trainerOnboardingNavSheet';
    if (document.getElementById(id)) return;
    var overlay = document.createElement('div');
    overlay.id = id;
    overlay.className = 'trainer-onboarding-nav-overlay';
    overlay.setAttribute('hidden', '');
    overlay.innerHTML =
      '<div class="trainer-onboarding-nav-sheet" role="dialog" aria-modal="true" aria-labelledby="trainerOnboardingNavTitle">' +
      '<div class="trainer-onboarding-nav-sheet__handle" aria-hidden="true"></div>' +
      '<h2 class="trainer-onboarding-nav-sheet__title" id="trainerOnboardingNavTitle"></h2>' +
      '<p class="trainer-onboarding-nav-sheet__hint" id="trainerOnboardingNavHint"></p>' +
      '<div class="trainer-onboarding-nav-sheet__actions" id="trainerOnboardingNavActions"></div>' +
      '</div>';
    overlay.addEventListener('click', function (ev) {
      if (ev.target === overlay) closeOnboardingNavSheet();
    });
    document.body.appendChild(overlay);
  }

  function closeOnboardingNavSheet() {
    var overlay = document.getElementById('trainerOnboardingNavSheet');
    if (!overlay) return;
    overlay.setAttribute('hidden', '');
    overlay.classList.remove('trainer-onboarding-nav-overlay--open');
  }

  function showOnboardingNavSheet(decision) {
    ensureOnboardingNavSheet();
    var overlay = document.getElementById('trainerOnboardingNavSheet');
    if (!overlay || !decision) return;
    var title = document.getElementById('trainerOnboardingNavTitle');
    var hint = document.getElementById('trainerOnboardingNavHint');
    var actions = document.getElementById('trainerOnboardingNavActions');
    if (title) title.textContent = decision.title || 'Пока недоступно';
    if (hint) hint.textContent = decision.hint || '';
    if (actions) {
      actions.innerHTML = '';
      function addBtn(cta, primary) {
        if (!cta || !cta.path) return;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = primary ? 'bd-btn bd-btn--primary' : 'bd-btn bd-btn--secondary';
        btn.textContent = cta.label || 'Продолжить';
        btn.addEventListener('click', function () {
          hapticSelection();
          closeOnboardingNavSheet();
          closeMoreSheet();
          navigateUnchecked(cta.path);
        });
        actions.appendChild(btn);
      }
      addBtn(decision.primary, true);
      addBtn(decision.secondary, false);
    }
    overlay.removeAttribute('hidden');
    overlay.classList.add('trainer-onboarding-nav-overlay--open');
  }

  function navigateUnchecked(path) {
    if (isSameTabRoute(path)) {
      closeMoreSheet();
      syncTabBarActive();
      return;
    }
    global.location.href = withInit(webappBasePath() + path);
  }

  function tryNavigate(path) {
    var decision = evaluateOnboardingPath(path);
    if (decision.allow) {
      navigateUnchecked(path);
      return;
    }
    hapticSelection();
    showOnboardingNavSheet(decision);
  }

  function syncOnboardingTabLocks() {
    var bar = document.getElementById('trainerTabBar');
    if (!bar) return;
    var data = state.onboardingData;
    var onboarding = data && !onboardingAllComplete(data);

    bar.querySelectorAll('.trainer-tab-bar__btn').forEach(function (btn) {
      var id = btn.dataset.tabId;
      var locked = false;
      if (onboarding) {
        if (id === 'home') locked = false;
        else if (id === 'schedule') locked = !evaluateOnboardingPath('schedule-editor').allow;
        else if (id === 'clients') locked = !evaluateOnboardingPath('trainer-clients').allow;
        else if (id === 'more') locked = false;
      }
      btn.classList.toggle('trainer-tab-bar__btn--locked', locked);
      btn.setAttribute('aria-disabled', locked ? 'true' : 'false');
    });

    var list = document.querySelector('.trainer-more-sheet__list');
    if (list) {
      list.querySelectorAll('.trainer-more-sheet__link').forEach(function (link) {
        var path = link.getAttribute('data-shell-path') || '';
        var locked = onboarding && !evaluateOnboardingPath(path).allow;
        link.classList.toggle('trainer-more-sheet__link--locked', locked);
        link.setAttribute('aria-disabled', locked ? 'true' : 'false');
      });
    }
  }

  function fetchOnboardingChecklist() {
    var initData = getInitData();
    if (!initData) {
      state.onboardingLoaded = true;
      return Promise.resolve(null);
    }
    var url = '/api/webapp/trainer/onboarding/checklist';
    url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
    return fetch(url, {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json', 'X-Telegram-Init-Data': initData },
    })
      .then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) return null;
          return d;
        });
      })
      .catch(function () {
        return null;
      })
      .then(function (d) {
        state.onboardingData = d;
        state.onboardingLoaded = true;
        syncOnboardingTabLocks();
        return d;
      });
  }

  function syncOnboarding(data) {
    state.onboardingData = data || null;
    state.onboardingLoaded = true;
    syncOnboardingTabLocks();
  }

  /* ─── Navigation ────────────────────────────────────────────────────────── */

  function navigate(path) {
    tryNavigate(path);
  }

  /* ─── Tab bar DOM ───────────────────────────────────────────────────────── */

  function buildTabBar() {
    var nav = document.createElement('nav');
    nav.id = 'trainerTabBar';
    nav.className = 'trainer-tab-bar';
    nav.setAttribute('role', 'tablist');
    nav.setAttribute('aria-label', 'Навигация');

    var tabs = [
      { id: 'home',     label: 'Главная',    path: 'trainer-home',     icon: TAB_ICONS.home },
      { id: 'schedule', label: 'Расписание', path: 'schedule-editor',  icon: TAB_ICONS.schedule },
      { id: 'clients',  label: 'Клиенты',    path: 'trainer-clients',  icon: TAB_ICONS.clients },
      { id: 'more',     label: 'Ещё',        path: null,               icon: TAB_ICONS.more },
    ];

    tabs.forEach(function (tab) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'trainer-tab-bar__btn';
      btn.setAttribute('role', 'tab');
      btn.dataset.tabId = tab.id;
      btn.innerHTML =
        '<span class="trainer-tab-bar__icon-wrap">' +
        tab.icon +
        '</span><span>' +
        tab.label +
        '</span>';
      btn.addEventListener('click', function () {
        hapticSelection();
        if (tab.id === 'more') {
          openMoreSheet();
          return;
        }
        if (btn.classList.contains('trainer-tab-bar__btn--locked') && tab.path) {
          showOnboardingNavSheet(evaluateOnboardingPath(tab.path));
          return;
        }
        if (tab.path && isSameTabRoute(tab.path)) {
          syncTabBarActive();
          return;
        }
        navigate(tab.path);
      });
      nav.appendChild(btn);
    });

    return nav;
  }

  /* ─── More sheet DOM ────────────────────────────────────────────────────── */

  function buildMoreSheet() {
    var overlay = document.createElement('div');
    overlay.id = 'trainerMoreOverlay';
    overlay.className = 'trainer-more-sheet-overlay';
    overlay.addEventListener('click', closeMoreSheet);

    var sheet = document.createElement('div');
    sheet.id = 'trainerMoreSheet';
    sheet.className = 'trainer-more-sheet';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-label', 'Дополнительные разделы');
    sheet.addEventListener('click', function (ev) {
      ev.stopPropagation();
    });

    var handle = document.createElement('div');
    handle.className = 'trainer-more-sheet__handle';
    sheet.appendChild(handle);

    var title = document.createElement('h2');
    title.className = 'trainer-more-sheet__title';
    title.textContent = 'Ещё';
    sheet.appendChild(title);

    var subtitle = document.createElement('p');
    subtitle.className = 'trainer-more-sheet__subtitle';
    subtitle.textContent = 'Профиль, финансы, группы и всё остальное';
    sheet.appendChild(subtitle);

    var list = document.createElement('ul');
    list.className = 'trainer-more-sheet__list';

    MORE_ITEMS.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'trainer-more-sheet__item';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'trainer-more-sheet__link';
      btn.setAttribute('data-shell-path', item.path);
      btn.innerHTML =
        '<span class="trainer-more-sheet__emoji" aria-hidden="true">' +
        item.emoji +
        '</span><span class="trainer-more-sheet__body"><span class="trainer-more-sheet__label">' +
        item.label +
        '</span><span class="trainer-more-sheet__hint">' +
        item.hint +
        '</span></span>' +
        MORE_CHEVRON;
      btn.addEventListener('click', function () {
        hapticSelection();
        closeMoreSheet();
        navigate(item.path);
      });
      li.appendChild(btn);
      list.appendChild(li);
    });

    sheet.appendChild(list);
    overlay.appendChild(sheet);
    return overlay;
  }

  /* ─── Tab bar state sync ────────────────────────────────────────────────── */

  function syncTabBarActive() {
    var bar = document.getElementById('trainerTabBar');
    if (!bar) return;
    var active = resolveActiveTab();
    bar.querySelectorAll('.trainer-tab-bar__btn').forEach(function (btn) {
      var id = btn.dataset.tabId;
      var isActive = id === active || (id === 'more' && (state.moreOpen || isMoreRoute()));
      btn.classList.toggle('trainer-tab-bar__btn--active', !!isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
  }

  function applyTabBarVisibility() {
    var bar = document.getElementById('trainerTabBar');
    var body = document.body;
    if (!bar || !body) return;
    var show = state.mode === 'tabs' && state.tabBarVisible;
    if (show) {
      bar.removeAttribute('hidden');
      bar.classList.remove('trainer-tab-bar--hidden');
      body.classList.remove('trainer-shell-tabs-hidden');
    } else {
      bar.setAttribute('hidden', 'hidden');
      bar.classList.add('trainer-tab-bar--hidden');
      body.classList.add('trainer-shell-tabs-hidden');
    }
  }

  /* ─── More sheet open/close ─────────────────────────────────────────────── */

  function openMoreSheet() {
    state.moreOpen = true;
    var overlay = document.getElementById('trainerMoreOverlay');
    if (!overlay) return;
    overlay.classList.add('trainer-more-sheet-overlay--open');
    var sheet = document.getElementById('trainerMoreSheet');
    if (sheet) sheet.classList.add('trainer-more-sheet--open');
    syncTabBarActive();
  }

  function closeMoreSheet() {
    state.moreOpen = false;
    var overlay = document.getElementById('trainerMoreOverlay');
    if (!overlay) return;
    overlay.classList.remove('trainer-more-sheet-overlay--open');
    var sheet = document.getElementById('trainerMoreSheet');
    if (sheet) sheet.classList.remove('trainer-more-sheet--open');
    syncTabBarActive();
  }

  /* ─── Public API ────────────────────────────────────────────────────────── */

  function setTabBarVisible(visible) {
    state.tabBarVisible = !!visible;
    applyTabBarVisibility();
  }

  function setForcedTab(tabId) {
    state.forcedTab = tabId || null;
    syncTabBarActive();
  }

  /* ─── Reactive drill-down detection ────────────────────────────────────── */

  /**
   * schedule-editor: hide tab bar whenever #screenMain loses .active class
   * (booking detail or decline screen is shown in its place).
   */
  function watchScheduleEditorScreens() {
    var screenMain = document.getElementById('screenMain');
    if (!screenMain) return;

    var observer = new MutationObserver(function () {
      var onMain = screenMain.classList.contains('active');
      setTabBarVisible(onMain);
    });
    observer.observe(screenMain, { attributes: true, attributeFilter: ['class'] });

    /* Sync once on boot — screen-main may already be inactive (deep-link to booking). */
    setTabBarVisible(screenMain.classList.contains('active'));
  }

  /**
   * trainer-clients: hide tab bar when client detail replaces the list.
   * openClientDetail() hides #clientsSection via style.display = 'none'.
   */
  function watchClientDetailTransitions() {
    var clientsSection = document.getElementById('clientsSection');
    if (!clientsSection) return;

    var observer = new MutationObserver(function () {
      var listVisible = clientsSection.style.display !== 'none';
      setTabBarVisible(listVisible);
    });
    observer.observe(clientsSection, { attributes: true, attributeFilter: ['style'] });

    setTabBarVisible(clientsSection.style.display !== 'none');
  }

  function setupDrilldownObserver() {
    /* Wait for deferred scripts that render these elements before observing. */
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        watchScheduleEditorScreens();
        watchClientDetailTransitions();
      });
    } else {
      watchScheduleEditorScreens();
      watchClientDetailTransitions();
    }
  }

  /* ─── Init ──────────────────────────────────────────────────────────────── */

  function init(opts) {
    opts = opts || {};
    var body = document.body;
    if (!body) return;

    var attr = body.getAttribute('data-trainer-shell');
    state.mode = opts.mode || attr || 'hidden';
    if (state.mode !== 'tabs') return;

    body.classList.add('trainer-shell-body');

    if (!document.getElementById('trainerTabBar')) {
      document.body.appendChild(buildTabBar());
    }
    if (!document.getElementById('trainerMoreOverlay')) {
      document.body.appendChild(buildMoreSheet());
    }

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        if (state.moreOpen) closeMoreSheet();
        closeOnboardingNavSheet();
      }
    });

    setupDrilldownObserver();
    applyTabBarVisibility();
    syncTabBarActive();
    fetchOnboardingChecklist();
  }

  /* ─── Auto-init via data attribute ─────────────────────────────────────── */

  function autoInit() {
    if (document.body && document.body.getAttribute('data-trainer-shell') === 'tabs') {
      init();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoInit);
  } else {
    autoInit();
  }

  /* ─── Public namespace ──────────────────────────────────────────────────── */

  global.TrainerShell = {
    version: SHELL_VERSION,
    init: init,
    navigate: navigate,
    setTabBarVisible: setTabBarVisible,
    setForcedTab: setForcedTab,
    openMoreSheet: openMoreSheet,
    closeMoreSheet: closeMoreSheet,
    syncOnboarding: syncOnboarding,
    fetchOnboardingChecklist: fetchOnboardingChecklist,
  };
})(window);
