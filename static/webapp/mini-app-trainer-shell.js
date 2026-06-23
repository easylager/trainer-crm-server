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

  var SHELL_VERSION = '202606200';

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
    var link = document.querySelector('[data-shell-path="trainer-collective"]');
    var item = link && link.closest('.trainer-more-sheet__item');
    if (item) item.remove();
    state.collectiveMenuVisible = false;
  }

  var TAB_ICONS = {
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V9.5z"/></svg>',
    schedule: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    clients: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    center: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 21h18"/><path d="M6 21V7l6-4 6 4v14"/><path d="M10 21v-6h4v6"/></svg>',
    more: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none"/></svg>',
  };

  var CENTER_TAB_PATH = 'trainer-collective?tab=brand';

  /** Lucide-style stroke icons — same language as tab bar and booking detail (.bd-icon). */
  function moreIconSvg(inner) {
    return (
      '<svg class="trainer-more-sheet__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      inner +
      '</svg>'
    );
  }

  var MORE_ICONS = {
    profile: moreIconSvg('<circle cx="12" cy="8" r="4"/><path d="M6 20v-1a6 6 0 0 1 12 0v1"/>'),
    passes: moreIconSvg('<path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2"/><path d="M13 17v2"/><path d="M13 11v2"/>'),
    subscription: moreIconSvg('<rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/>'),
    requests: moreIconSvg('<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'),
    stats: moreIconSvg('<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>'),
    groups: moreIconSvg('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
    referral: moreIconSvg('<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13"/><path d="M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7"/><path d="M7.5 8a2.5 2.5 0 0 1 0-5A4.8 8 0 0 1 12 8a4.8 8 0 0 1 4.5-5 2.5 2.5 0 0 1 0 5"/>'),
    collective: moreIconSvg('<path d="M3 21h18"/><path d="M6 21V7l6-4 6 4v14"/><path d="M10 21v-6h4v6"/>'),
  };

  var COLLECTIVE_MORE_ITEM = {
    path: 'trainer-collective',
    label: 'Студия',
    icon: MORE_ICONS.collective,
    hint: 'Бренд, команда и ссылка для клиентов',
  };

  var MORE_ITEMS = [
    {
      path: 'trainer-profile',
      label: 'Профиль',
      icon: MORE_ICONS.profile,
      hint: 'Анкета, услуги и модерация',
    },
    {
      path: 'trainer-pass-products',
      label: 'Абонементы',
      icon: MORE_ICONS.passes,
      hint: 'Настройка и выдача клиентам',
    },
    {
      path: 'trainer-subscription',
      label: 'Подписка',
      icon: MORE_ICONS.subscription,
      hint: 'Тариф и способ оплаты',
    },
    {
      path: 'trainer-requests',
      label: 'Заявки',
      icon: MORE_ICONS.requests,
      hint: 'Отклики клиентов и входящие запросы',
    },
    {
      path: 'trainer-stats',
      label: 'Статистика',
      icon: MORE_ICONS.stats,
      hint: 'Выручка, посещаемость, активность',
    },
    {
      path: 'trainer-groups',
      label: 'Группы',
      icon: MORE_ICONS.groups,
      hint: 'Групповые занятия и расписание',
    },
    {
      path: 'trainer-referral',
      label: 'Рефералы',
      icon: MORE_ICONS.referral,
      hint: 'Пригласи коллегу — получи бонус',
    },
  ];

  var MORE_CHEVRON =
    '<svg class="trainer-more-sheet__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M9 6l6 6-6 6"/></svg>';

  /** Route key → default hint; replaced when menu badge is active (syncMoreMenuBadges). */
  var MORE_MENU_BADGE_HINTS = {
    'trainer-requests': function (n) {
      return (
        n +
        ' ' +
        pluralRuMore(n, 'новая заявка без ответа', 'новые заявки без ответа', 'новых заявок без ответа')
      );
    },
    'trainer-profile': function () {
      return 'Можно дополнить анкету — каталог по желанию';
    },
  };

  var MORE_MENU_LABELS = {
    'trainer-requests': 'Заявки',
    'trainer-profile': 'Профиль',
    'trainer-pass-products': 'Абонементы',
    'trainer-subscription': 'Подписка',
    'trainer-stats': 'Статистика',
    'trainer-groups': 'Группы',
    'trainer-referral': 'Рефералы',
    'trainer-collective': 'Студия',
  };

  /** Lower number = higher in «Требует внимания» block. */
  var MORE_MENU_ATTENTION_PRIORITY = {
    'trainer-requests': 10,
    'trainer-profile': 20,
  };

  /** Pages whose route key maps to «Ещё» tab */
  var MORE_ROUTE_KEYS = [
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
    moreOpen: false,
    forcedTab: null,
    onboardingData: null,
    onboardingLoaded: false,
    inboxBadges: { schedule: 0, center: 0, more: 0, clients: 0 },
    menuBadges: {},
    menuBadgeHints: {},
    collectiveMenuVisible: false,
    collectiveMenuChecked: false,
    pendingCollectiveBootstrap: null,
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

  function syncMoreSheetBodyLock() {
    var body = document.body;
    if (body) body.classList.toggle('trainer-shell-more-open', !!state.moreOpen);
    setNativeVerticalSwipeEnabled(!state.moreOpen);
  }

  function resetMoreSheetDragTransform(sheet) {
    if (!sheet) return;
    sheet.style.transform = '';
    sheet.style.transition = '';
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

  /** Whether a shell route is reachable during «Первые шаги». */
  function evaluateOnboardingPath(path) {
    var data = state.onboardingData;
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

    if (!data || onboardingAllComplete(data)) return { allow: true };
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
    var link = document.querySelector('[data-shell-path="trainer-collective"]');
    var item = link && link.closest('.trainer-more-sheet__item');
    if (!item) return;
    if (showCenterGridTab()) {
      item.setAttribute('hidden', 'hidden');
      item.style.display = 'none';
    } else {
      item.removeAttribute('hidden');
      item.style.display = '';
    }
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
    updateCollectiveMoreItemHint();
    updateCollectiveMoreItemLabel();
    syncOnboardingTabLocks();
    syncInboxBadges();
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
        else if (id === 'center') locked = !evaluateOnboardingPath('trainer-collective').allow;
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
        syncShellNavForCapabilities();
        return d;
      });
  }

  function syncOnboarding(data) {
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
        '<span class="trainer-tab-bar__badge" hidden aria-hidden="true"></span>' +
        '</span><span>' +
        tab.label +
        '</span>';
      btn.addEventListener('click', function () {
        hapticSelection();
        if (tab.id === 'more') {
          toggleMoreSheet();
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

    var scroll = document.createElement('div');
    scroll.className = 'trainer-more-sheet__scroll';
    scroll.setAttribute('data-more-sheet-scroll', '1');

    var title = document.createElement('h2');
    title.className = 'trainer-more-sheet__title';
    title.textContent = 'Ещё';
    scroll.appendChild(title);

    var subtitle = document.createElement('p');
    subtitle.className = 'trainer-more-sheet__subtitle';
    subtitle.textContent = 'Профиль, финансы, группы и всё остальное';
    scroll.appendChild(subtitle);

    var attention = document.createElement('div');
    attention.id = 'trainerMoreAttention';
    attention.className = 'trainer-more-sheet__attention';
    attention.setAttribute('hidden', 'hidden');
    scroll.appendChild(attention);

    var list = document.createElement('ul');
    list.className = 'trainer-more-sheet__list';

    MORE_ITEMS.forEach(function (item) {
      list.appendChild(buildMoreSheetItem(item));
    });

    scroll.appendChild(list);
    sheet.appendChild(scroll);
    overlay.appendChild(sheet);
    wireMoreSheetGestures(sheet);
    wireMoreSheetScrollGuard(scroll);
    return overlay;
  }

  /** Keep vertical pans inside the sheet — Telegram WebView may steal them when swipes are disabled. */
  function wireMoreSheetScrollGuard(scrollEl) {
    if (!scrollEl || scrollEl.dataset.scrollGuardWired === '1') return;
    scrollEl.dataset.scrollGuardWired = '1';
    scrollEl.addEventListener(
      'touchmove',
      function (ev) {
        if (scrollEl.scrollHeight > scrollEl.clientHeight + 1) {
          ev.stopPropagation();
        }
      },
      { passive: true }
    );
  }

  /** Upgrade legacy sheet DOM (list-only scroll) to unified scroll body. */
  function ensureMoreSheetScrollUpgrade() {
    var sheet = document.getElementById('trainerMoreSheet');
    if (!sheet || sheet.querySelector('[data-more-sheet-scroll]')) return;

    var scroll = document.createElement('div');
    scroll.className = 'trainer-more-sheet__scroll';
    scroll.setAttribute('data-more-sheet-scroll', '1');

    var movable = [];
    sheet.querySelectorAll(
      '.trainer-more-sheet__title, .trainer-more-sheet__subtitle, #trainerMoreAttention, .trainer-more-sheet__list'
    ).forEach(function (el) {
      movable.push(el);
    });
    if (!movable.length) return;

    movable.forEach(function (el) {
      scroll.appendChild(el);
    });
    sheet.appendChild(scroll);
    wireMoreSheetScrollGuard(scroll);
  }

  /** Tap handle or swipe down — dismiss sheet without collapsing the whole Mini App. */
  function wireMoreSheetGestures(sheet) {
    if (!sheet || sheet.dataset.dismissWired === '1') return;
    sheet.dataset.dismissWired = '1';
    var handle = sheet.querySelector('.trainer-more-sheet__handle');
    var dragEls = [handle].filter(Boolean);
    if (!dragEls.length) return;

    if (handle) {
      handle.setAttribute('role', 'button');
      handle.setAttribute('tabindex', '0');
      handle.setAttribute('aria-label', 'Свернуть раздел «Ещё»');
    }

    var dragStartY = 0;
    var dragDy = 0;
    var dragging = false;
    var dragMoved = false;
    var activePointer = null;

    function finishDrag() {
      if (!dragging) return;
      dragging = false;
      activePointer = null;
      sheet.style.transition = '';
      if (dragDy > 72) {
        resetMoreSheetDragTransform(sheet);
        closeMoreSheet();
        return;
      }
      resetMoreSheetDragTransform(sheet);
    }

    dragEls.forEach(function (el) {
      el.addEventListener('pointerdown', function (ev) {
        if (!state.moreOpen || (ev.button != null && ev.button !== 0)) return;
        dragging = true;
        dragMoved = false;
        dragStartY = ev.clientY;
        dragDy = 0;
        activePointer = ev.pointerId;
        sheet.style.transition = 'none';
        if (el.setPointerCapture) {
          try {
            el.setPointerCapture(ev.pointerId);
          } catch (e) { /* */ }
        }
      });

      el.addEventListener('pointermove', function (ev) {
        if (!dragging || ev.pointerId !== activePointer) return;
        dragDy = Math.max(0, ev.clientY - dragStartY);
        if (dragDy > 8) dragMoved = true;
        sheet.style.transform = 'translateY(' + dragDy + 'px)';
      });

      el.addEventListener('pointerup', function (ev) {
        if (ev.pointerId !== activePointer) return;
        if (!dragMoved && dragDy <= 8) closeMoreSheet();
        finishDrag();
      });

      el.addEventListener('pointercancel', function (ev) {
        if (ev.pointerId !== activePointer) return;
        finishDrag();
      });

      if (el === handle) {
        el.addEventListener('keydown', function (ev) {
          if ((ev.key === 'Enter' || ev.key === ' ') && state.moreOpen) {
            ev.preventDefault();
            closeMoreSheet();
          }
        });
      }
    });
  }

  function pluralRuMore(n, one, few, many) {
    n = Math.abs(parseInt(String(n), 10) || 0);
    var mod10 = n % 10;
    var mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) return few;
    return many;
  }

  function menuBadgeHintForPath(path, count) {
    if (state.menuBadgeHints && state.menuBadgeHints[path]) {
      return String(state.menuBadgeHints[path]);
    }
    var fn = MORE_MENU_BADGE_HINTS[path];
    if (typeof fn === 'function') return fn(count);
    return '';
  }

  function attentionPriorityForPath(path) {
    var p = MORE_MENU_ATTENTION_PRIORITY[path];
    return p != null ? p : 50;
  }

  function attentionPillLabel(path, count) {
    var label = MORE_MENU_LABELS[path] || path;
    var hint = menuBadgeHintForPath(path, count);
    if (hint) return label + ' — ' + hint;
    if (count > 1) return label + ' · ' + count;
    return label;
  }

  /** Inject attention block / row badges if sheet was built before this upgrade. */
  function ensureMoreSheetAttentionUpgrade() {
    var sheet = document.getElementById('trainerMoreSheet');
    if (!sheet) return;
    if (!document.getElementById('trainerMoreAttention')) {
      var list = sheet.querySelector('.trainer-more-sheet__list');
      if (list) {
        var attention = document.createElement('div');
        attention.id = 'trainerMoreAttention';
        attention.className = 'trainer-more-sheet__attention';
        attention.setAttribute('hidden', 'hidden');
        var scrollHost = list.parentElement;
        if (scrollHost) scrollHost.insertBefore(attention, list);
        else sheet.insertBefore(attention, list);
      }
    }
    sheet.querySelectorAll('.trainer-more-sheet__link[data-shell-path]').forEach(function (link) {
      if (link.querySelector('.trainer-more-sheet__badge')) return;
      var badge = document.createElement('span');
      badge.className = 'trainer-more-sheet__badge';
      badge.setAttribute('hidden', 'hidden');
      badge.setAttribute('aria-hidden', 'true');
      var chevron = link.querySelector('.trainer-more-sheet__chevron');
      if (chevron) link.insertBefore(badge, chevron);
      else link.appendChild(badge);
    });
  }

  function syncMoreSheetSubtitle(hasUrgentAttention) {
    var subtitle = document.querySelector('.trainer-more-sheet__subtitle');
    if (!subtitle) return;
    subtitle.textContent = hasUrgentAttention
      ? 'Сначала разделы с пометкой — там ждут ответа'
      : 'Профиль, финансы, группы и всё остальное';
  }

  function isNoticeMenuPath(path) {
    return path === 'trainer-requests';
  }

  /** Optional onboarding hint — not an alarm; no top banner or tab badge. */
  function isSoftHintMenuPath(path) {
    return path === 'trainer-profile';
  }

  function syncMoreMenuBadges() {
    var menu = state.menuBadges || {};
    var list = document.querySelector('.trainer-more-sheet__list');
    if (list) {
      list.querySelectorAll('.trainer-more-sheet__link[data-shell-path]').forEach(function (link) {
        var path = link.getAttribute('data-shell-path') || '';
        var n = parseInt(String(menu[path] || 0), 10) || 0;
        var badgeEl = link.querySelector('.trainer-more-sheet__badge');
        var hintEl = link.querySelector('.trainer-more-sheet__hint');
        var defaultHint = link.getAttribute('data-default-hint') || '';
        var notice = isNoticeMenuPath(path);
        var softHint = isSoftHintMenuPath(path);
        link.classList.toggle('trainer-more-sheet__link--attention', n > 0 && !notice && !softHint);
        link.classList.toggle('trainer-more-sheet__link--notice', n > 0 && notice);
        link.classList.toggle('trainer-more-sheet__link--hint', n > 0 && softHint);
        if (badgeEl) {
          badgeEl.classList.toggle('trainer-more-sheet__badge--notice', n > 0 && notice);
          if (n > 0 && !softHint) {
            badgeEl.textContent = n > 9 ? '9+' : String(n);
            badgeEl.removeAttribute('hidden');
            badgeEl.setAttribute('aria-hidden', 'false');
          } else {
            badgeEl.setAttribute('hidden', 'hidden');
            badgeEl.setAttribute('aria-hidden', 'true');
            badgeEl.textContent = '';
          }
        }
        if (hintEl) {
          if (n > 0) {
            var activeHint = menuBadgeHintForPath(path, n);
            hintEl.textContent = activeHint || defaultHint;
            hintEl.classList.toggle('trainer-more-sheet__hint--notice', notice);
            hintEl.classList.toggle('trainer-more-sheet__hint--attention', !notice && !softHint);
            hintEl.classList.toggle('trainer-more-sheet__hint--soft', softHint);
          } else {
            hintEl.textContent = defaultHint;
            hintEl.classList.remove(
              'trainer-more-sheet__hint--attention',
              'trainer-more-sheet__hint--notice',
              'trainer-more-sheet__hint--soft'
            );
          }
        }
      });
    }

    var attentionEl = document.getElementById('trainerMoreAttention');
    if (!attentionEl) {
      syncMoreSheetSubtitle(false);
      return;
    }
    var parts = [];
    Object.keys(menu).forEach(function (path) {
      var n = parseInt(String(menu[path] || 0), 10) || 0;
      if (n <= 0 || isSoftHintMenuPath(path)) return;
      parts.push({ path: path, label: MORE_MENU_LABELS[path] || path, count: n });
    });
    parts.sort(function (a, b) {
      var pa = attentionPriorityForPath(a.path);
      var pb = attentionPriorityForPath(b.path);
      if (pa !== pb) return pa - pb;
      return String(a.label).localeCompare(String(b.label), 'ru');
    });
    if (!parts.length) {
      attentionEl.setAttribute('hidden', 'hidden');
      attentionEl.innerHTML = '';
      attentionEl.classList.remove('trainer-more-sheet__attention--notice');
      syncMoreSheetSubtitle(false);
      return;
    }
    var allNotice = parts.every(function (p) {
      return isNoticeMenuPath(p.path);
    });
    attentionEl.classList.toggle('trainer-more-sheet__attention--notice', allNotice);
    syncMoreSheetSubtitle(true);
    attentionEl.removeAttribute('hidden');
    var pills = parts
      .map(function (p) {
        var pillClass = 'trainer-more-sheet__attention-pill';
        if (isNoticeMenuPath(p.path)) pillClass += ' trainer-more-sheet__attention-pill--notice';
        return (
          '<button type="button" class="' +
          pillClass +
          '" data-attention-path="' +
          p.path +
          '">' +
          escapeHtml(attentionPillLabel(p.path, p.count)) +
          '</button>'
        );
      })
      .join('');
    var kicker = allNotice ? 'Есть новое' : 'Требует внимания';
    attentionEl.innerHTML =
      '<p class="trainer-more-sheet__attention-kicker">' +
      kicker +
      '</p>' +
      '<div class="trainer-more-sheet__attention-pills" role="group" aria-label="Разделы с новым">' +
      pills +
      '</div>';
    attentionEl.querySelectorAll('.trainer-more-sheet__attention-pill').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var path = btn.getAttribute('data-attention-path');
        if (!path) return;
        hapticSelection();
        closeMoreSheet();
        navigate(path);
      });
    });
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
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
      if (n > 0) {
        badgeEl.textContent = n > 9 ? '9+' : String(n);
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

  function setInboxBadges(badges) {
    badges = badges || { schedule: 0, center: 0, more: 0, clients: 0 };
    var menu = badges.menu && typeof badges.menu === 'object' ? badges.menu : {};
    state.inboxBadges = {
      schedule: parseInt(String(badges.schedule || 0), 10) || 0,
      center: parseInt(String(badges.center || 0), 10) || 0,
      /* Server sends actionable-only count for tab «Ещё» (requests, not catalog hints). */
      more: parseInt(String(badges.more != null ? badges.more : 0), 10) || 0,
      clients: parseInt(String(badges.clients || 0), 10) || 0,
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

  function buildMoreSheetItem(item) {
    var li = document.createElement('li');
    li.className = 'trainer-more-sheet__item';
    li.dataset.collectiveItem = item.path === 'trainer-collective' ? '1' : '0';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'trainer-more-sheet__link';
    btn.setAttribute('data-shell-path', item.path);
    btn.setAttribute('data-default-hint', item.hint || '');
    btn.innerHTML =
      '<span class="trainer-more-sheet__icon-wrap" aria-hidden="true">' +
      item.icon +
      '</span><span class="trainer-more-sheet__body"><span class="trainer-more-sheet__label">' +
      item.label +
      '</span><span class="trainer-more-sheet__hint">' +
      item.hint +
      '</span></span>' +
      '<span class="trainer-more-sheet__badge" hidden aria-hidden="true"></span>' +
      MORE_CHEVRON;
    btn.addEventListener('click', function () {
      hapticSelection();
      closeMoreSheet();
      navigate(item.path);
    });
    li.appendChild(btn);
    return li;
  }

  /** Inserts «Студия» into the More sheet when membership is confirmed. Idempotent. */
  function updateCollectiveMoreItemHint() {
    var hintEl = document.querySelector(
      '[data-shell-path="trainer-collective"] .trainer-more-sheet__hint'
    );
    if (hintEl) hintEl.textContent = collectiveMoreHint();
  }

  function updateCollectiveMoreItemLabel() {
    var labelEl = document.querySelector(
      '[data-shell-path="trainer-collective"] .trainer-more-sheet__label'
    );
    if (labelEl) labelEl.textContent = collectiveMoreLabel();
  }

  function ensureCollectiveMoreItem() {
    if (!isCollectiveFeatureEnabled()) {
      removeCollectiveMoreItem();
      return false;
    }
    var list = document.querySelector('.trainer-more-sheet__list');
    if (!list) return false;
    if (list.querySelector('[data-shell-path="trainer-collective"]')) {
      state.collectiveMenuVisible = true;
      updateCollectiveMoreItemHint();
      return true;
    }
    var groupsItem = list.querySelector('[data-shell-path="trainer-groups"]');
    var item = Object.assign({}, COLLECTIVE_MORE_ITEM, { hint: collectiveMoreHint() });
    var node = buildMoreSheetItem(item);
    if (groupsItem && groupsItem.parentElement) {
      groupsItem.parentElement.insertAdjacentElement('afterend', node);
    } else {
      list.appendChild(node);
    }
    state.collectiveMenuVisible = true;
    syncCollectiveMoreItemVisibility();
    syncOnboardingTabLocks();
    return true;
  }

  function flushPendingCollectiveBootstrap() {
    if (!state.pendingCollectiveBootstrap) return;
    var payload = state.pendingCollectiveBootstrap;
    state.pendingCollectiveBootstrap = null;
    syncCollectiveMenuFromBootstrap(payload);
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
    if (!document.querySelector('.trainer-more-sheet__list')) {
      state.pendingCollectiveBootstrap = collectivePayload;
      return;
    }
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

  function openMoreSheet() {
    state.moreOpen = true;
    var overlay = document.getElementById('trainerMoreOverlay');
    if (!overlay) return;
    overlay.classList.add('trainer-more-sheet-overlay--open');
    var sheet = document.getElementById('trainerMoreSheet');
    if (sheet) {
      resetMoreSheetDragTransform(sheet);
      sheet.classList.add('trainer-more-sheet--open');
      var scroll = sheet.querySelector('[data-more-sheet-scroll]');
      if (scroll) scroll.scrollTop = 0;
    }
    syncMoreSheetBodyLock();
    syncTabBarActive();
  }

  function closeMoreSheet() {
    state.moreOpen = false;
    var overlay = document.getElementById('trainerMoreOverlay');
    if (!overlay) return;
    overlay.classList.remove('trainer-more-sheet-overlay--open');
    var sheet = document.getElementById('trainerMoreSheet');
    if (sheet) {
      sheet.classList.remove('trainer-more-sheet--open');
      resetMoreSheetDragTransform(sheet);
    }
    syncMoreSheetBodyLock();
    syncTabBarActive();
  }

  function toggleMoreSheet() {
    if (state.moreOpen) {
      closeMoreSheet();
      return;
    }
    fetchCollectiveMenuVisibility(true).finally(function () {
      fetchInboxBadgesFromServer().finally(function () {
        syncMoreMenuBadges();
        openMoreSheet();
      });
    });
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
   * schedule-editor: bottom day strip needs the full safe area — global tab bar overlaps it.
   * Header «Главная» (shown when tabs hidden) is the primary exit; same pattern as booking detail.
   */
  function watchScheduleEditorScreens() {
    if (!document.getElementById('screenMain')) return;
    setTabBarVisible(false);
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
    ensureMoreSheetAttentionUpgrade();
    ensureMoreSheetScrollUpgrade();
    flushPendingCollectiveBootstrap();

    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') fetchInboxBadgesFromServer();
    });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        if (state.moreOpen) closeMoreSheet();
        closeOnboardingNavSheet();
      }
    });

    setupDrilldownObserver();
    applyTabBarVisibility();
    syncTabBarActive();
    syncInboxBadges();
    fetchOnboardingChecklist();
    if (isCollectiveFeatureEnabled()) {
      fetchCollectiveMenuVisibility();
      fetchSuspendedCollectiveNotice();
    }
    fetchInboxBadgesFromServer();
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
    toggleMoreSheet: toggleMoreSheet,
    setInboxBadges: setInboxBadges,
    fetchInboxBadgesFromServer: fetchInboxBadgesFromServer,
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
