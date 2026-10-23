/**
 * Trainer Mini App shell: bottom tab bar, navigate with init_data.
 *
 * Пятая вкладка — «Профиль» (TASK-313): экран trainer-account со всеми разделами группами.
 * Раньше здесь была шторка «Ещё», и тренер не находил в ней ни профиль, ни цены. Внутренний
 * id вкладки остался 'more' — на нём держатся серверные бейджи (`badges.more`) и стили.
 * Шторка по-прежнему собирается (скрыто): из неё вкладка «Профиль» берёт бейджи разделов
 * и пункт «Студия» через getMenuState().
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

  var SHELL_VERSION = '202610221';

  /** Prod default: off until TRAINER_COLLECTIVE_ENABLED=1 on API + hub bootstrap / access flag. */
  function isCollectiveFeatureEnabled() {
    if (global.TRAINER_COLLECTIVE_ENABLED === true) return true;
    if (global.TRAINER_COLLECTIVE_ENABLED === false) return false;
    var attr = document.body && document.body.getAttribute('data-trainer-collective-enabled');
    if (attr === '1' || attr === 'true') return true;
    return false;
  }

  function applyCollectiveFeatureFlag(enabled) {
    global.TRAINER_COLLECTIVE_ENABLED = !!enabled;
    if (!enabled) removeCollectiveMoreItem();
  }

  /** Collective menu only when API/bootstrap returned a real studio slug. */
  function hasCollectiveMembershipPayload(data) {
    return !!(data && data.slug && String(data.slug).trim());
  }

  function removeCollectiveMoreItem() {
    state.collectiveMenuVisible = false;
    emitMenuState();
  }

  var TAB_ICONS = {
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V9.5z"/></svg>',
    schedule: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    clients: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    center: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 21h18"/><path d="M6 21V7l6-4 6 4v14"/><path d="M10 21v-6h4v6"/></svg>',
    more: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
    catalog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h2M7 17h2"/></svg>',
  };

  var CENTER_TAB_PATH = 'trainer-collective?tab=brand';

  var COLLECTIVE_MORE_ITEM = {
    path: 'trainer-collective',
    label: 'Студия',
    iconId: 'trainer-collective',
    hint: 'Бренд, команда и ссылка для клиентов',
  };


  /** Pages whose route key maps to the «Профиль» tab */
  var MORE_ROUTE_KEYS = [
    'trainer-account',
    'trainer-prices',
    'trainer-arenas',
    'trainer-requests',
    'trainer-profile',
    'trainer-pass-products',
    'trainer-subscription',
    'trainer-stats',
    'trainer-groups',
    'trainer-referral',
    'trainer-collective',
    'trainer-bookings',
    'trainer-faq',
  ];

  var state = {
    mode: 'hidden',
    tabBarVisible: true,
    forcedTab: null,
    onboardingData: null,
    onboardingLoaded: false,
    inboxBadges: { schedule: 0, center: 0, more: 0, clients: 0 },
    menuBadges: {},
    menuBadgeHints: {},
    collectiveMenuVisible: false,
    collectiveMenuChecked: false,
    collectiveBootstrap: null,
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

  /** While «Ещё» sheet is open, block Telegram’s swipe-to-minimize so the sheet can dismiss first. */
  function setNativeVerticalSwipeEnabled(enabled) {
    var tg = getTg();
    if (!tg) return;
    try {
      if (enabled && typeof tg.enableVerticalSwipes === 'function') tg.enableVerticalSwipes();
      else if (!enabled && typeof tg.disableVerticalSwipes === 'function') tg.disableVerticalSwipes();
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
    /* Вкладку в бар добавили (TASK-140), а сюда — нет: на собственном экране «Каталог» бар
       не подсвечивал ни одной вкладки, и раздел выглядел как чужая страница. */
    if (key === 'trainer-catalog') return 'catalog';
    if (key === 'trainer-collective' && showCenterGridTab()) return 'center';
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

  function pathRouteKey(path) {
    return String(path || '').replace(/^\.\//, '').split('?')[0].split('#')[0];
  }

  function studioAccessMode() {
    if (state.onboardingData && state.onboardingData.studio_access_mode) {
      return state.onboardingData.studio_access_mode;
    }
    if (state.collectiveBootstrap && state.collectiveBootstrap.studio_access_mode) {
      return state.collectiveBootstrap.studio_access_mode;
    }
    return 'full_trainer';
  }

  function organizationCapabilities() {
    if (state.collectiveBootstrap && state.collectiveBootstrap.capabilities) {
      return state.collectiveBootstrap.capabilities;
    }
    if (state.onboardingData && state.onboardingData.capabilities) {
      return state.onboardingData.capabilities;
    }
    return null;
  }

  function shellNavProfile() {
    var caps = organizationCapabilities();
    if (caps && caps.shell_nav_profile) return caps.shell_nav_profile;
    return studioAccessMode() === 'studio_admin_only' ? 'organization_admin' : 'full';
  }

  function collectiveScreenTitle() {
    var caps = organizationCapabilities();
    if (caps && caps.collective_screen_title) return caps.collective_screen_title;
    if (organizationFormat() === 'center' || organizationFormat() === 'center_hybrid') return 'Центр';
    return 'Студия';
  }

  function collectiveMoreLabel() {
    return collectiveScreenTitle();
  }

  function organizationLabel() {
    var caps = organizationCapabilities();
    if (caps && caps.organization_label) return caps.organization_label;
    return organizationFormat() === 'center' || organizationFormat() === 'center_hybrid' ? 'центр' : 'студия';
  }

  function organizationFormat() {
    var caps = organizationCapabilities();
    if (caps && caps.organization_format) return caps.organization_format;
    if (state.collectiveBootstrap && state.collectiveBootstrap.organization_format) {
      return state.collectiveBootstrap.organization_format;
    }
    return 'studio';
  }

  function collectiveMoreHint() {
    var caps = organizationCapabilities();
    if (caps && caps.catalog_mode === 'center_grid') {
      if (caps.show_personal_crm) return 'Центр и ваши личные клиенты';
      return 'Управление центром и сеткой';
    }
    return 'Команда и бренд студии';
  }

  function isOrganizationAdminNav() {
    return shellNavProfile() === 'organization_admin';
  }

  function showPersonalCrm() {
    var caps = organizationCapabilities();
    if (caps && caps.show_personal_crm != null) return !!caps.show_personal_crm;
    // Until capabilities load, keep solo wedge nav — hide only when API explicitly says so.
    return true;
  }

  function showCenterGridTab() {
    var caps = organizationCapabilities();
    return !!(caps && caps.show_center_grid);
  }

  /**
   * Доступен ли маршрут. Единственное оставшееся ограничение — режим центра/студии:
   * это не онбординг, а роль аккаунта, у которого личного расписания просто нет.
   * Всё, что было связано с анкетой и первой записью, удалено вместе со старой моделью.
   */
  function evaluateOnboardingPath(path) {
    var key = pathRouteKey(path);
    if (isOrganizationAdminNav() && !showPersonalCrm()) {
      var screenTitle = collectiveScreenTitle();
      if (key === 'trainer-home' || key === 'trainer-collective') return { allow: true };
      return {
        allow: false,
        title: 'Режим ' + organizationLabel(),
        hint: 'Для вашего аккаунта открыты главная и раздел «' + screenTitle + '».',
        primary: { path: CENTER_TAB_PATH, label: 'Открыть ' + screenTitle.toLowerCase() },
        secondary: null,
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

  function buildCenterTabButton() {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'trainer-tab-bar__btn';
    btn.setAttribute('role', 'tab');
    btn.dataset.tabId = 'center';
    btn.innerHTML =
      '<span class="trainer-tab-bar__icon-wrap">' +
      TAB_ICONS.center +
      '<span class="trainer-tab-bar__badge" hidden aria-hidden="true"></span>' +
      '</span><span>' +
      collectiveScreenTitle() +
      '</span>';
    btn.addEventListener('click', function () {
      hapticSelection();
      if (btn.classList.contains('trainer-tab-bar__btn--locked')) {
        showOnboardingNavSheet(evaluateOnboardingPath('trainer-collective'));
        return;
      }
      if (isSameTabRoute('trainer-collective')) {
        syncTabBarActive();
        return;
      }
      navigate(CENTER_TAB_PATH);
    });
    return btn;
  }

  function updateCenterTabLabel() {
    var btn = document.querySelector('.trainer-tab-bar__btn[data-tab-id="center"]');
    if (!btn) return;
    var spans = btn.querySelectorAll('span');
    var label = spans.length ? spans[spans.length - 1] : null;
    if (label) label.textContent = collectiveScreenTitle();
  }

  function ensureCenterTabButton() {
    var bar = document.getElementById('trainerTabBar');
    if (!bar) return;
    var existing = bar.querySelector('[data-tab-id="center"]');
    if (!showCenterGridTab()) {
      if (existing) existing.remove();
      syncCollectiveMoreItemVisibility();
      return;
    }
    if (!existing) {
      var moreBtn = bar.querySelector('[data-tab-id="more"]');
      var centerBtn = buildCenterTabButton();
      if (moreBtn) bar.insertBefore(centerBtn, moreBtn);
      else bar.appendChild(centerBtn);
    } else {
      updateCenterTabLabel();
      existing.removeAttribute('hidden');
      existing.style.display = '';
    }
    syncCollectiveMoreItemVisibility();
  }

  function syncCollectiveMoreItemVisibility() {
    emitMenuState();
  }

  function syncShellNavForCapabilities() {
    var bar = document.getElementById('trainerTabBar');
    if (!bar) return;
    var caps = organizationCapabilities();
    var hidePersonalTabs = !!(caps && caps.show_personal_crm === false);
    bar.querySelectorAll('.trainer-tab-bar__btn').forEach(function (btn) {
      var id = btn.dataset.tabId;
      if (id === 'center') return;
      if (hidePersonalTabs && (id === 'schedule' || id === 'clients')) {
        btn.setAttribute('hidden', 'hidden');
        btn.style.display = 'none';
      } else {
        btn.removeAttribute('hidden');
        btn.style.display = '';
      }
    });
    ensureCenterTabButton();
    emitMenuState();
    syncOnboardingTabLocks();
    syncInboxBadges();
  }

  /** Замки вкладок остались только для режима организации. */
  function syncOnboardingTabLocks() {
    var bar = document.getElementById('trainerTabBar');
    if (!bar) return;

    bar.querySelectorAll('.trainer-tab-bar__btn').forEach(function (btn) {
      var id = btn.dataset.tabId;
      var locked = false;
      if (id === 'schedule') locked = !evaluateOnboardingPath('schedule-editor').allow;
      else if (id === 'clients') locked = !evaluateOnboardingPath('trainer-clients').allow;
      else if (id === 'center') locked = !evaluateOnboardingPath('trainer-collective').allow;
      btn.classList.toggle('trainer-tab-bar__btn--locked', locked);
      btn.setAttribute('aria-disabled', locked ? 'true' : 'false');
    });
  }

  /*
   * Бейджи бара и чеклист меняются редко, а спрашивались на каждой вкладке до того, как бар
   * становился «настоящим». Последний ответ держим в sessionStorage: бар сразу рисуется
   * с ним, а свежий ответ приходит, когда браузер освободился от данных экрана.
   */
  var SHELL_CACHE_KEY = 'trainer_shell_cache_v1';
  var SHELL_CACHE_TTL_MS = 30 * 60 * 1000;

  function readShellCache() {
    try {
      var c = JSON.parse(sessionStorage.getItem(SHELL_CACHE_KEY) || 'null');
      if (!c || !(Date.now() - c.at < SHELL_CACHE_TTL_MS)) return null;
      return c;
    } catch (e) {
      return null;
    }
  }

  function writeShellCache(part) {
    try {
      var c = readShellCache() || {};
      Object.keys(part).forEach(function (k) { c[k] = part[k]; });
      c.at = Date.now();
      sessionStorage.setItem(SHELL_CACHE_KEY, JSON.stringify(c));
    } catch (e) { /* */ }
  }

  function whenIdle(fn) {
    if (typeof global.requestIdleCallback === 'function') global.requestIdleCallback(fn, { timeout: 2000 });
    else setTimeout(fn, 600);
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
        if (d) writeShellCache({ onboarding: d });
        state.onboardingData = d;
        state.onboardingLoaded = true;
        syncOnboardingTabLocks();
        syncShellNavForCapabilities();
        return d;
      });
  }

  function syncOnboarding(data) {
    if (data) writeShellCache({ onboarding: data });
    state.onboardingData = data || null;
    state.onboardingLoaded = true;
    syncOnboardingTabLocks();
    syncShellNavForCapabilities();
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
      /* Каталог — постоянная вкладка с первого дня (TASK-140). Раньше публикация жила тумблером
         в «Настройках» профиля: самое публичное решение тренера было спрятано глубже всего, и
         узнать о каталоге можно было только из хинта, который легко смахнуть. Место — четвёртое,
         перед «Ещё»: мышечную память первых трёх вкладок не сдвигаем. */
      { id: 'catalog',  label: 'Каталог',     path: 'trainer-catalog',  icon: TAB_ICONS.catalog },
      { id: 'more',     label: 'Профиль',    path: 'trainer-account',  icon: TAB_ICONS.more },
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
        '<span class="trainer-tab-bar__badge" hidden aria-hidden="true"></span>' +
        '</span><span>' +
        tab.label +
        '</span>';
      btn.addEventListener('click', function () {
        hapticSelection();
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

  /** Бейджи разделов, подсказки и пункт «Студия» — для экрана «Профиль». */
  function getMenuState() {
    var collective = null;
    if (state.collectiveMenuVisible && !showCenterGridTab()) {
      collective = {
        path: COLLECTIVE_MORE_ITEM.path,
        label: collectiveMoreLabel(),
        hint: collectiveMoreHint(),
      };
    }
    return {
      badges: state.menuBadges || {},
      hints: state.menuBadgeHints || {},
      collective: collective,
    };
  }

  function emitMenuState() {
    try {
      document.dispatchEvent(new CustomEvent('trainer-shell:menu', { detail: getMenuState() }));
    } catch (e) { /* старые WebView без CustomEvent */ }
  }

  /* Бейджи разделов показывает вкладка «Профиль» (trainer-account) — по событию trainer-shell:menu. */
  function syncMoreMenuBadges() {
    emitMenuState();
  }

  function fetchInboxBadgesFromServer() {
    var initData = getInitData();
    if (!initData) return Promise.resolve(null);
    var url = '/api/webapp/trainer/hub/inbox-count?init_data=' + encodeURIComponent(initData);
    return fetch(url, {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json', 'X-Telegram-Init-Data': initData },
    })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (payload) {
        if (payload && payload.badges) setInboxBadges(payload.badges);
        return payload;
      })
      .catch(function () {
        return null;
      });
  }

  function syncInboxBadges() {
    var bar = document.getElementById('trainerTabBar');
    if (!bar) return;
    var badges = state.inboxBadges || {};
    bar.querySelectorAll('.trainer-tab-bar__btn').forEach(function (btn) {
      var id = btn.dataset.tabId;
      var badgeEl = btn.querySelector('.trainer-tab-bar__badge');
      if (!badgeEl) return;
      var n = 0;
      if (id === 'schedule') n = parseInt(String(badges.schedule || 0), 10) || 0;
      else if (id === 'center') n = parseInt(String(badges.center || 0), 10) || 0;
      else if (id === 'more') n = parseInt(String(badges.more || 0), 10) || 0;
      else if (id === 'clients') n = parseInt(String(badges.clients || 0), 10) || 0;
      else if (id === 'catalog') n = parseInt(String(badges.catalog || 0), 10) || 0;
      /* Каталог — одна карточка: «сколько» бессмысленно, поэтому точка, а не число. */
      var asDot = id === 'catalog';
      badgeEl.classList.toggle('trainer-tab-bar__badge--dot', asDot);
      if (n > 0) {
        badgeEl.textContent = asDot ? '' : n > 9 ? '9+' : String(n);
        badgeEl.removeAttribute('hidden');
        badgeEl.setAttribute('aria-hidden', 'false');
      } else {
        badgeEl.setAttribute('hidden', 'hidden');
        badgeEl.setAttribute('aria-hidden', 'true');
        badgeEl.textContent = '';
      }
    });
    syncMoreMenuBadges();
  }

  function setInboxBadges(badges, fromCache) {
    badges = badges || { schedule: 0, center: 0, more: 0, clients: 0, catalog: 0 };
    if (!fromCache) writeShellCache({ badges: badges });
    var menu = badges.menu && typeof badges.menu === 'object' ? badges.menu : {};
    state.inboxBadges = {
      schedule: parseInt(String(badges.schedule || 0), 10) || 0,
      center: parseInt(String(badges.center || 0), 10) || 0,
      /* Server sends actionable-only count for tab «Ещё» (requests, not catalog hints). */
      more: parseInt(String(badges.more != null ? badges.more : 0), 10) || 0,
      clients: parseInt(String(badges.clients || 0), 10) || 0,
      /* 1 = карточке нужно действие тренера (paused / needs_revision), см. TASK-140. */
      catalog: parseInt(String(badges.catalog || 0), 10) || 0,
    };
    state.menuBadges = menu;
    state.menuBadgeHints =
      badges.menu_hints && typeof badges.menu_hints === 'object' ? badges.menu_hints : {};
    syncInboxBadges();
  }

  /* ─── Tab bar state sync ────────────────────────────────────────────────── */

  function syncTabBarActive() {
    var bar = document.getElementById('trainerTabBar');
    if (!bar) return;
    var active = resolveActiveTab();
    bar.querySelectorAll('.trainer-tab-bar__btn').forEach(function (btn) {
      var id = btn.dataset.tabId;
      var isActive = id === active || (id === 'more' && isMoreRoute());
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

  /** «Студия» в «Профиле»: membership подтверждён — пункт появится по trainer-shell:menu. */
  function ensureCollectiveMoreItem() {
    if (!isCollectiveFeatureEnabled()) {
      removeCollectiveMoreItem();
      return false;
    }
    state.collectiveMenuVisible = true;
    syncCollectiveMoreItemVisibility();
    syncOnboardingTabLocks();
    return true;
  }

  function fetchCollectiveMenuVisibility(forceRefresh) {
    if (!isCollectiveFeatureEnabled()) {
      removeCollectiveMoreItem();
      state.collectiveMenuChecked = true;
      state.collectiveMenuVisible = false;
      return Promise.resolve(false);
    }
    if (!forceRefresh && state.collectiveMenuChecked) {
      return Promise.resolve(state.collectiveMenuVisible);
    }
    var initData = getInitData();
    if (!initData) {
      state.collectiveMenuChecked = true;
      state.collectiveMenuVisible = false;
      return Promise.resolve(false);
    }
    var url = '/api/webapp/trainer/collective';
    url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
    return fetch(url, {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json', 'X-Telegram-Init-Data': initData },
    })
      .then(function (r) {
        state.collectiveMenuChecked = true;
        if (!r.ok) {
          removeCollectiveMoreItem();
          state.collectiveMenuVisible = false;
          return false;
        }
        return r.json().then(function (data) {
          if (!hasCollectiveMembershipPayload(data) || (data && data.enabled === false)) {
            removeCollectiveMoreItem();
            state.collectiveMenuVisible = false;
            return false;
          }
          ensureCollectiveMoreItem();
          return state.collectiveMenuVisible;
        });
      })
      .catch(function () {
        removeCollectiveMoreItem();
        state.collectiveMenuChecked = true;
        state.collectiveMenuVisible = false;
        return false;
      });
  }

  /** Hub bootstrap already resolved membership — skip extra round-trip. */
  function syncCollectiveMenuFromBootstrap(collectivePayload) {
    if (!isCollectiveFeatureEnabled()) {
      removeCollectiveMoreItem();
      return;
    }
    if (!hasCollectiveMembershipPayload(collectivePayload)) {
      removeCollectiveMoreItem();
      return;
    }
    state.collectiveBootstrap = collectivePayload;
    state.collectiveMenuChecked = true;
    ensureCollectiveMoreItem();
    syncShellNavForCapabilities();
  }

  function ensureSuspendedBannerEl() {
    var el = document.getElementById('trainerShellSuspendedBanner');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'trainerShellSuspendedBanner';
    el.className = 'trainer-shell-suspended-banner';
    el.setAttribute('role', 'status');
    el.hidden = true;
    document.body.insertBefore(el, document.body.firstChild);
    return el;
  }

  /** O8.4: show when collective status is suspended — catalog/brand booking off. */
  function syncSuspendedCollectiveNotice(notice) {
    var el = ensureSuspendedBannerEl();
    if (!notice || notice.suspended !== true) {
      el.hidden = true;
      el.textContent = '';
      document.body.classList.remove('trainer-shell-has-suspended-banner');
      return;
    }
    el.hidden = false;
    el.textContent =
      notice.message ||
      'Организация приостановлена — каталог и запись через бренд недоступны.';
    document.body.classList.add('trainer-shell-has-suspended-banner');
  }

  function fetchSuspendedCollectiveNotice() {
    if (!isCollectiveFeatureEnabled()) return Promise.resolve();
    var initData = getInitData();
    if (!initData) return Promise.resolve();
    var url =
      '/api/webapp/trainer/collective/suspended-notice?init_data=' +
      encodeURIComponent(initData);
    return fetch(url, {
      method: 'GET',
      cache: 'no-store',
      headers: { Accept: 'application/json', 'X-Telegram-Init-Data': initData },
    })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (payload) {
        if (payload) syncSuspendedCollectiveNotice(payload);
      })
      .catch(function () {
        /* non-fatal */
      });
  }

  function refreshCollectiveMenuVisibility() {
    state.collectiveMenuChecked = false;
    state.collectiveMenuVisible = false;
    return fetchCollectiveMenuVisibility(true);
  }

  /* Вкладка «Профиль»: раньше открывала шторку «Ещё», теперь — экран trainer-account. */
  function toggleMoreSheet() {
    if (!isSameTabRoute('trainer-account')) navigate('trainer-account');
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
   * schedule-editor: «Расписание» — корневая вкладка, бар виден на неделе, как на остальных
   * четырёх (TASK-314). Полоса дней стоит над баром (mini-app-schedule-editor.css). Во вложенных
   * видах — запись, отказ, редактор дня, выбор дня — бара нет, выход через «Назад».
   */
  function watchScheduleEditorScreens() {
    var main = document.getElementById('screenMain');
    if (!main) return;
    var watched = ['screenMain', 'screenEdit', 'screenDayPick']
      .map(function (id) { return document.getElementById(id); })
      .filter(Boolean);
    function sync() {
      var open = function (id) {
        var el = document.getElementById(id);
        return !!el && el.style.display === 'block';
      };
      setTabBarVisible(main.classList.contains('active') && !open('screenEdit') && !open('screenDayPick'));
    }
    var observer = new MutationObserver(sync);
    watched.forEach(function (el) {
      observer.observe(el, { attributes: true, attributeFilter: ['class', 'style'] });
    });
    sync();
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

    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') fetchInboxBadgesFromServer();
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        closeOnboardingNavSheet();
      }
    });

    setupDrilldownObserver();
    applyTabBarVisibility();
    syncTabBarActive();
    syncInboxBadges();
    /* Главная отдаёт чеклист и счётчики из hub/bootstrap сама (syncOnboarding, setInboxBadges):
       второй запрос за тем же на первом экране не нужен. */
    var pageFeedsShell = body.getAttribute('data-shell-fed-by-page') === '1';
    var cached = readShellCache();
    if (cached && cached.onboarding && !state.onboardingLoaded) {
      state.onboardingData = cached.onboarding;
      state.onboardingLoaded = true;
      syncOnboardingTabLocks();
      syncShellNavForCapabilities();
    }
    if (cached && cached.badges) setInboxBadges(cached.badges, true);
    /* С кэшем бар уже верный — свежий ответ подождёт, пока экран получит свои данные. */
    var refreshShell = cached ? whenIdle : function (fn) { fn(); };
    if (!pageFeedsShell) refreshShell(fetchOnboardingChecklist);
    if (isCollectiveFeatureEnabled()) {
      fetchCollectiveMenuVisibility();
      fetchSuspendedCollectiveNotice();
    }
    if (!pageFeedsShell) refreshShell(fetchInboxBadgesFromServer);
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
    toggleMoreSheet: toggleMoreSheet,
    setInboxBadges: setInboxBadges,
    fetchInboxBadgesFromServer: fetchInboxBadgesFromServer,
    getMenuState: getMenuState,
    syncOnboarding: syncOnboarding,
    fetchOnboardingChecklist: fetchOnboardingChecklist,
    syncCollectiveMenuFromBootstrap: syncCollectiveMenuFromBootstrap,
    syncSuspendedCollectiveNotice: syncSuspendedCollectiveNotice,
    refreshCollectiveMenuVisibility: refreshCollectiveMenuVisibility,
    applyCollectiveFeatureFlag: applyCollectiveFeatureFlag,
    isCollectiveFeatureEnabled: isCollectiveFeatureEnabled,
    organizationCapabilities: organizationCapabilities,
    shellNavProfile: shellNavProfile,
    collectiveScreenTitle: collectiveScreenTitle,
    disableVerticalSwipes: function () {
      setNativeVerticalSwipeEnabled(false);
    },
    enableVerticalSwipes: function () {
      setNativeVerticalSwipeEnabled(true);
    },
  };
})(window);
