/**
 * Client Mini App shell: bottom tab bar, «Ещё» sheet, navigate with init_data + view transitions.
 */
(function (global) {
  'use strict';

  var SHELL_VERSION = '202610051';
  // Версия ассетов — та же, с которой загружен этот скрипт (bump_webapp_assets.py держит её
  // общей). Префетч с вписанной руками версией качал файлы, которые вкладка уже не просит.
  var ASSET_V = (function () {
    var cur = global.document && global.document.currentScript;
    var m = cur && /[?&]v=(\d+)/.exec(cur.src || '');
    return m ? m[1] : '';
  })();

  function assetUrl(base, file, ver) {
    var v = ver || ASSET_V;
    return base + file + (v ? '?v=' + v : '');
  }

  var CATALOG_WARM_KEY = 'tcb_catalog_warm_v1';
  var CATALOG_WARM_TTL_MS = 90000;
  var BOOKINGS_WARM_KEY = 'tcb_bookings_warm_v2';
  var BOOKINGS_WARM_TTL_MS = 90000;

  var TAB_ICONS = {
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V9.5z"/></svg>',
    /* Лупа, а не снежинка: вкладка держит и площадки (лёд, залы, хореография),
       и тренеров, и группы. Снежинка обещала только лёд. */
    catalog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.9-3.9"/></svg>',
    bookings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    /* TASK-369: вкладки режима season_ui. Шайба — «Кто кого», человек — «Я». */
    kk: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="9.5" rx="8" ry="3.5"/><path d="M4 9.5v4.5c0 1.9 3.6 3.5 8 3.5s8-1.6 8-3.5V9.5"/></svg>',
    me: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4 4-6.5 8-6.5s7.2 2.5 8 6.5"/></svg>',
    more: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="5" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="19" r="1.5" fill="currentColor" stroke="none"/></svg>',
  };

  var MORE_ITEMS = [
    {
      path: 'kto-kogo',
      label: 'Кто кого',
      iconId: 'kto-kogo',
      hint: 'Угадывай матчи Динамо и Экстралиги',
    },
    {
      path: 'client-saved-trainers',
      label: 'Сохранённые',
      iconId: 'client-saved',
      hint: 'Тренеры, катки и активные напоминания',
    },
    {
      path: 'client-stats',
      label: 'Ваша активность',
      iconId: 'client-activity',
      hint: 'Серия тренировок и статистика сезона',
    },
    {
      path: 'client-passes-certificates',
      label: 'Абонементы',
      iconId: 'client-pass',
      hint: 'Сколько занятий осталось и подарочные сертификаты',
    },
    {
      path: 'client-family-access',
      label: 'Семейный доступ',
      iconId: 'client-family',
      hint: 'Близкие в одном аккаунте — записи и абонементы вместе',
    },
    {
      path: 'client-requests',
      label: 'Мои заявки',
      iconId: 'client-requests',
      hint: 'Запрос на подбор тренера и ответы специалистов',
    },
    {
      // TASK-303: сообщество и форма поддержки — с главной сюда.
      path: 'client-support',
      label: 'Идеи и поддержка',
      iconId: 'client-support',
      hint: 'Напишите, чего не хватает, — мы читаем каждое сообщение',
    },
  ];

  function moreItemPlate(iconId) {
    var icons = global.GlideMoreIcons;
    if (icons && typeof icons.plateHtml === 'function') {
      return icons.plateHtml(iconId);
    }
    return '<span class="glide-more-plate" aria-hidden="true"></span>';
  }

  var MORE_CHEVRON =
    '<svg class="client-more-sheet__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M9 6l6 6-6 6"/></svg>';

  var state = {
    mode: 'hidden',
    tabBarVisible: true,
    moreOpen: false,
    forcedTab: null,
    watchesActiveCount: 0,
    inited: false,
    baseMode: 'hidden',
    kbdHidden: false,
    kbdWired: false,
  };

  /*
   * TASK-366: флаги новой навигации (your-season). Читаются из кэша синхронно, до первого
   * кадра; сервер уточняет после монтирования. Бар по ним пересобирает TASK-369.
   */
  var UI_FLAGS_KEY = 'cw_ui_flags_v1';
  /*
   * Кэш живёт сутки по полю at: просроченный (и с at из будущего) = «выключено». То же правило и тот же
   * TTL — в client-season-back.js и в гейте #kk-shell-gate (kto-kogo.html); tests/js/client-shell-ui-flags-ttl.test.js
   * держит три копии одинаковыми.
   */
  var UI_FLAGS_TTL_MS = 24 * 60 * 60 * 1000;
  /* Метка «флаги уже спрошены в этой сессии» (sessionStorage): один запрос на сессию, а не на страницу. */
  var UI_FLAGS_SYNC_KEY = 'cw_ui_flags_sync_v1';
  var uiFlags = { season_ui: false, bookings_tab: false };
  var uiFlagsRefreshed = false;

  function normalizeUiFlags(raw) {
    var season = !!raw && raw.season_ui === true;
    return { season_ui: season, bookings_tab: season && raw.bookings_tab === true };
  }

  function initDataUserId() {
    try {
      var tg = getTg();
      var u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
      if (u && u.id != null) return String(u.id);
      var initData = getInitData();
      if (!initData) return '';
      var raw = new URLSearchParams(initData).get('user');
      var parsed = raw ? JSON.parse(raw) : null;
      return parsed && parsed.id != null ? String(parsed.id) : '';
    } catch (e) {
      return '';
    }
  }

  function readUiFlags() {
    var uid = initDataUserId();
    if (!uid) return normalizeUiFlags(null);
    try {
      var cached = JSON.parse(global.localStorage.getItem(UI_FLAGS_KEY) || 'null');
      if (!cached || String(cached.u) !== uid) return normalizeUiFlags(null);
      var age = Date.now() - cached.at;
      if (typeof cached.at !== 'number' || !(age >= 0 && age < UI_FLAGS_TTL_MS)) return normalizeUiFlags(null);
      return normalizeUiFlags(cached);
    } catch (e) {
      return normalizeUiFlags(null);
    }
  }

  function writeUiFlagsCache(flags) {
    var uid = initDataUserId();
    if (!uid) return;
    try {
      global.localStorage.setItem(
        UI_FLAGS_KEY,
        JSON.stringify({ u: uid, season_ui: flags.season_ui, bookings_tab: flags.bookings_tab, at: Date.now() })
      );
    } catch (e) { /* storage может быть запрещён */ }
  }

  function uiFlagsSyncedThisSession(uid) {
    try {
      return !!uid && global.sessionStorage.getItem(UI_FLAGS_SYNC_KEY) === uid;
    } catch (e) {
      return false;
    }
  }

  function markUiFlagsSynced(uid) {
    try {
      if (uid) global.sessionStorage.setItem(UI_FLAGS_SYNC_KEY, uid);
    } catch (e) { /* без метки — запрос на каждой странице, как раньше */ }
  }

  function applyUiFlags(next) {
    var changed = next.season_ui !== uiFlags.season_ui || next.bookings_tab !== uiFlags.bookings_tab;
    uiFlags = next;
    if (changed && typeof global.CustomEvent === 'function') {
      global.dispatchEvent(new global.CustomEvent('client-shell:ui-flags', { detail: getUiFlags() }));
    }
  }

  function refreshUiFlags() {
    if (uiFlagsRefreshed) return;
    var initData = getInitData();
    if (!initData || typeof global.fetch !== 'function') return;
    var uid = initDataUserId();
    if (uiFlagsSyncedThisSession(uid)) {
      uiFlagsRefreshed = true;
      return;
    }
    uiFlagsRefreshed = true;
    global
      .fetch('/api/webapp/client/ui-flags', { headers: { 'X-Telegram-Init-Data': initData }, cache: 'no-store' })
      .then(function (r) {
        /* 401/403 — доступа нет, флаг выключен: кэш сбрасывается, метка ставится. 5xx и прочие не-ok — временный сбой:
           кэш и метку не трогаем (повторим на следующей странице). */
        if (r.status === 401 || r.status === 403) return { __failed: true };
        if (!r.ok) return null;
        return r.json().catch(function () { return { __failed: true }; });
      })
      .then(function (data) {
        if (!data) return;
        var next = data.__failed ? normalizeUiFlags(null) : normalizeUiFlags(data);
        writeUiFlagsCache(next);
        markUiFlagsSynced(uid);
        applyUiFlags(next);
      })
      .catch(function () {});
  }

  function getUiFlags() {
    return { season_ui: uiFlags.season_ui, bookings_tab: uiFlags.bookings_tab };
  }

  function getTg() {
    return global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null;
  }

  function webappBasePath() {
    var p = global.location.pathname || '';
    return p.indexOf('/static/webapp/') === 0 ? '/static/webapp/' : '/webapp/';
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
    if (body) body.classList.toggle('client-shell-more-open', !!state.moreOpen);
    setNativeVerticalSwipeEnabled(!state.moreOpen);
  }

  function resetMoreSheetDragTransform(sheet) {
    if (!sheet) return;
    sheet.style.transform = '';
    sheet.style.transition = '';
  }

  function hapticSuccess() {
    var tg = getTg();
    try {
      if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.notificationOccurred === 'function') {
        tg.HapticFeedback.notificationOccurred('success');
      }
    } catch (e) { /* */ }
  }

  function pathnameKey() {
    var p = (global.location.pathname || '').replace(/\/$/, '');
    var seg = p.split('/').pop() || '';
    return seg.replace(/\.html$/, '');
  }

  function isPublicPlaceRoute() {
    var p = global.location.pathname || '';
    return /^\/p\/[^/]+\/[^/]+/.test(p);
  }

  /*
   * TASK-369: активная вкладка в режиме season_ui. Отдельная функция, чтобы старый разбор
   * ниже остался как был. «Ещё» здесь нет: его страницы уехали в «Я».
   */
  var SEASON_ME_ROUTES = {
    'client-me': 1,
    'client-requests': 1,
    'client-saved-trainers': 1,
    'client-stats': 1,
    'client-passes-certificates': 1,
    'client-passes': 1,
    'client-certificates': 1,
    'client-family-access': 1,
    'client-support': 1,
  };

  function seasonTabForKey(key, search) {
    if (key === 'client-home') return 'home';
    if (key === 'arena' || key === 'ice' || key === 'trainers') return 'catalog';
    if (key === 'catalog') {
      var q = search || '';
      if (q.indexOf('tab=catalog') >= 0 || q.indexOf('tab=') < 0) return 'catalog';
      return null;
    }
    if (key === 'client-bookings') return uiFlags.bookings_tab ? 'bookings' : 'me';
    if (key === 'kto-kogo') return 'kk';
    if (SEASON_ME_ROUTES[key] === 1) return 'me';
    return null;
  }

  function seasonForcedTab(id) {
    if (id === 'more') return 'me';
    if (id === 'bookings' && !uiFlags.bookings_tab) return 'me';
    return id;
  }

  function resolveActiveTab() {
    if (state.forcedTab) return uiFlags.season_ui ? seasonForcedTab(state.forcedTab) : state.forcedTab;
    var key = pathnameKey();
    if (uiFlags.season_ui) return seasonTabForKey(key, global.location.search);
    if (key === 'client-home') return 'home';
    // Витрина тренеров — раздел «Поиска» (этап 1 входов): подсвечена вкладка «Поиск».
    if (key === 'arena' || key === 'ice' || key === 'trainers') return 'catalog';
    if (key === 'catalog') {
      var q = global.location.search || '';
      if (q.indexOf('tab=catalog') >= 0 || q.indexOf('tab=') < 0) return 'catalog';
      return null;
    }
    if (key === 'client-bookings') return 'bookings';
    if (
      key === 'client-requests' ||
      key === 'client-saved-trainers' ||
      key === 'client-stats' ||
      key === 'client-passes-certificates' ||
      key === 'client-family-access' ||
      key === 'client-passes' ||
      key === 'client-certificates'
    ) {
      return 'more';
    }
    return null;
  }

  function isMoreRoute() {
    return resolveActiveTab() === 'more';
  }

  /*
   * TASK-369: бар режима season_ui — «Главная · Поиск · [Записи] · Кто кого · Я», без «Ещё».
   * Живёт отдельно от buildTabBar ниже: тот остаётся как был, ветвление по флагу — одно.
   */
  function seasonTabs() {
    var tabs = [
      { id: 'home', label: 'Главная', path: 'client-home', icon: TAB_ICONS.home },
      { id: 'catalog', label: 'Поиск', path: 'ice', icon: TAB_ICONS.catalog },
    ];
    if (uiFlags.bookings_tab) {
      tabs.push({ id: 'bookings', label: 'Записи', path: 'client-bookings', icon: TAB_ICONS.bookings });
    }
    tabs.push({ id: 'kk', label: 'Кто кого', path: 'kto-kogo', icon: TAB_ICONS.kk });
    tabs.push({ id: 'me', label: 'Я', path: 'client-me', icon: TAB_ICONS.me });
    return tabs;
  }

  function dispatchRetap(tabId) {
    if (typeof global.CustomEvent !== 'function') return;
    global.dispatchEvent(new global.CustomEvent('client-shell:retap', { detail: { tab: tabId } }));
  }

  /* TASK-391: вкладка, которую держит оболочка (client-tabs.js): уже живая — качать нечего. */
  function shellTabs() {
    var t = global.ClientTabs;
    return t && t.hosted ? t : null;
  }

  function inFastTabsShell() {
    var el = document.documentElement;
    return !!(el && typeof el.hasAttribute === 'function' && el.hasAttribute('data-ft-shell'));
  }

  function prefetchShellTab(tabId) {
    var t = shellTabs();
    if (t.isMounted(tabId)) return Promise.resolve();
    return Promise.all([t.prefetch(tabId), tabId === 'me' ? prefetchMeWarmCache() : prefetchBookingsWarmCache()]);
  }

  function onSeasonTabPointerDown(tabId) {
    if (shellTabs() && shellTabs().hosts(tabId)) {
      prefetchShellTab(tabId);
      return;
    }
    if (tabId === 'catalog') {
      prefetchIceAssets();
      prefetchCatalogAssets();
      prefetchCatalogWarmCache();
    } else if (tabId === 'bookings') {
      prefetchBookingsAssets();
      prefetchBookingsWarmCache();
    } else if (tabId === 'kk') {
      prefetchKkAssets();
    } else if (tabId === 'me') {
      prefetchMeAssets();
      /* Повторный тап по «Я» на самой «Я»: страницу перезапросит client-shell:retap, второй GET не нужен. */
      if (!/(^|\/)client-me\/?$/.test(global.location.pathname || '')) prefetchMeWarmCache();
    }
  }

  function buildSeasonTabBar() {
    var tabs = seasonTabs();
    var nav = document.createElement('nav');
    nav.id = 'clientTabBar';
    nav.className = 'client-tab-bar client-tab-bar--season client-tab-bar--n' + tabs.length;
    nav.setAttribute('role', 'tablist');
    nav.setAttribute('aria-label', 'Навигация');

    tabs.forEach(function (tab) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'client-tab-bar__btn ga-press';
      btn.setAttribute('role', 'tab');
      btn.dataset.tabId = tab.id;
      btn.innerHTML =
        '<span class="client-tab-bar__icon-wrap">' +
        tab.icon +
        '</span><span>' +
        tab.label +
        '</span>';
      btn.addEventListener(
        'pointerdown',
        function (ev) {
          onTabPressStart(tab.id, ev);
          onSeasonTabPointerDown(tab.id);
        },
        { passive: true }
      );
      btn.addEventListener('click', function () {
        hapticSelection();
        if (isSameTabRoute(tab.path)) {
          // Повторный тап: как раньше (наверх / выход с карты «Поиска») плюс сигнал странице.
          if (!(tab.id === 'catalog' && handleCatalogTabRetap())) scrollPageTop();
          resetTabPress();
          dispatchRetap(tab.id);
          return;
        }
        rememberTabTap(tab.id);
        commitTabPress(tab.id);
        navigate(tab.path);
      });
      nav.appendChild(btn);
    });

    return nav;
  }

  function buildTabBar() {
    if (uiFlags.season_ui) return buildSeasonTabBar();
    var nav = document.createElement('nav');
    nav.id = 'clientTabBar';
    nav.className = 'client-tab-bar';
    nav.setAttribute('role', 'tablist');
    nav.setAttribute('aria-label', 'Навигация');

    var tabs = [
      { id: 'home', label: 'Главная', path: 'client-home', icon: TAB_ICONS.home },
      { id: 'catalog', label: 'Поиск', path: 'ice', icon: TAB_ICONS.catalog },
      { id: 'bookings', label: 'Записи', path: 'client-bookings', icon: TAB_ICONS.bookings },
      { id: 'more', label: 'Ещё', path: null, icon: TAB_ICONS.more },
    ];

    tabs.forEach(function (tab) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'client-tab-bar__btn ga-press';
      btn.setAttribute('role', 'tab');
      btn.dataset.tabId = tab.id;
      btn.innerHTML =
        '<span class="client-tab-bar__icon-wrap">' +
        tab.icon +
        '</span><span>' +
        tab.label +
        '</span>';
      if (tab.id !== 'more') {
        btn.addEventListener(
          'pointerdown',
          function (ev) {
            onTabPressStart(tab.id, ev);
          },
          { passive: true }
        );
      }
      if (tab.id === 'catalog' || tab.id === 'bookings') {
        btn.addEventListener(
          'pointerdown',
          function () {
            if (tab.id === 'catalog') {
              prefetchIceAssets();
              prefetchCatalogAssets();
              prefetchCatalogWarmCache();
            } else {
              prefetchBookingsAssets();
              prefetchBookingsWarmCache();
            }
          },
          { passive: true }
        );
      }
      btn.addEventListener('click', function () {
        hapticSelection();
        if (tab.id === 'more') {
          toggleMoreSheet();
          return;
        }
        if (tab.path && isSameTabRoute(tab.path)) {
          if (tab.id === 'catalog' && handleCatalogTabRetap()) {
            closeMoreSheet();
            resetTabPress();
            return;
          }
          scrollPageTop();
          resetTabPress();
          return;
        }
        rememberTabTap(tab.id);
        commitTabPress(tab.id);
        navigate(tab.path);
      });
      nav.appendChild(btn);
    });

    return nav;
  }

  function buildMoreSheet() {
    var overlay = document.createElement('div');
    overlay.id = 'clientMoreOverlay';
    overlay.className = 'client-more-sheet-overlay';
    overlay.addEventListener('click', closeMoreSheet);

    var sheet = document.createElement('div');
    sheet.id = 'clientMoreSheet';
    sheet.className = 'client-more-sheet';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-label', 'Дополнительные разделы');
    sheet.addEventListener('click', function (ev) {
      ev.stopPropagation();
    });

    var handle = document.createElement('div');
    handle.className = 'client-more-sheet__handle';
    sheet.appendChild(handle);

    var title = document.createElement('h2');
    title.className = 'client-more-sheet__title';
    title.textContent = 'Ещё';
    sheet.appendChild(title);

    var subtitle = document.createElement('p');
    subtitle.className = 'client-more-sheet__subtitle';
    subtitle.textContent = 'Избранное, абонементы, семья и заявки — всё, что не в нижних вкладках';
    sheet.appendChild(subtitle);

    var list = document.createElement('ul');
    list.className = 'client-more-sheet__list';

    MORE_ITEMS.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'client-more-sheet__item';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'client-more-sheet__link';
      var badge =
        item.path === 'client-saved-trainers' && state.watchesActiveCount > 0
          ? '<span class="client-more-sheet__badge" aria-hidden="true">' +
            String(state.watchesActiveCount) +
            '</span>'
          : '';
      btn.innerHTML =
        moreItemPlate(item.iconId) +
        badge +
        '<span class="client-more-sheet__body"><span class="client-more-sheet__label">' +
        item.label +
        '</span><span class="client-more-sheet__hint">' +
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
    wireMoreSheetGestures(sheet);
    return overlay;
  }

  function wireMoreSheetGestures(sheet) {
    if (!sheet || sheet.dataset.dismissWired === '1') return;
    sheet.dataset.dismissWired = '1';
    var handle = sheet.querySelector('.client-more-sheet__handle');
    var title = sheet.querySelector('.client-more-sheet__title');
    var dragEls = [handle, title].filter(Boolean);
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

  function syncTabBarActive() {
    var bar = document.getElementById('clientTabBar');
    if (!bar) return;
    var pressed = tabPress.tab;
    var active = pressed || resolveActiveTab();
    bar.querySelectorAll('.client-tab-bar__btn').forEach(function (btn) {
      var id = btn.dataset.tabId;
      var isActive = id === active || (!pressed && id === 'more' && (state.moreOpen || isMoreRoute()));
      btn.classList.toggle('client-tab-bar__btn--active', !!isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
  }

  /* ── TASK-390: вкладка становится активной под пальцем ─────────────────────
   *
   * Раньше активная вкладка менялась только на новой странице: нажал — бар стоит
   * как был, пока грузится следующий экран. Теперь новая вкладка подсвечивается
   * на pointerdown, в том же кадре, а переход по-прежнему по click: палец уехал
   * (больше 8 px, как в ga-press.js), касание отменено или click так и не пришёл —
   * подсветка возвращается. Анимация смены включается классом --switching только
   * на время переключения: при загрузке страницы, возврате из bfcache и
   * программной смене (setForcedTab) бар встаёт в конечное состояние без движения.
   */
  var TAB_PRESS_MOVE_PX = 8;
  var TAB_PRESS_CLICK_WAIT_MS = 450;
  var TAB_SWITCH_MS = 260;
  var tabPress = { tab: null, pointer: null, x: 0, y: 0, committed: false, revertTimer: null, switchTimer: null };

  function clearTabPressTimer(name) {
    if (tabPress[name] && typeof global.clearTimeout === 'function') global.clearTimeout(tabPress[name]);
    tabPress[name] = null;
  }

  function markTabSwitching() {
    var bar = document.getElementById('clientTabBar');
    if (!bar) return;
    bar.classList.add('client-tab-bar--switching');
    clearTabPressTimer('switchTimer');
    if (typeof global.setTimeout !== 'function') return;
    tabPress.switchTimer = global.setTimeout(function () {
      tabPress.switchTimer = null;
      var current = document.getElementById('clientTabBar');
      if (current) current.classList.remove('client-tab-bar--switching');
    }, TAB_SWITCH_MS);
  }

  function showTabPress(tabId) {
    if (tabPress.tab === tabId) return;
    tabPress.tab = tabId;
    markTabSwitching();
    syncTabBarActive();
  }

  function onTabPressStart(tabId, ev) {
    if (ev && ((ev.button != null && ev.button !== 0) || ev.isPrimary === false)) return;
    clearTabPressTimer('revertTimer');
    tabPress.pointer = ev && ev.pointerId != null ? ev.pointerId : null;
    tabPress.x = ev && ev.clientX != null ? ev.clientX : 0;
    tabPress.y = ev && ev.clientY != null ? ev.clientY : 0;
    tabPress.committed = false;
    if (tabPress.tab === tabId) return;
    // Нажатие на уже активную вкладку — это повтор (наверх), подсветка не меняется.
    if (!tabPress.tab && resolveActiveTab() === tabId) {
      tabPress.pointer = null;
      return;
    }
    showTabPress(tabId);
  }

  function cancelTabPress() {
    clearTabPressTimer('revertTimer');
    tabPress.pointer = null;
    if (!tabPress.tab || tabPress.committed) return;
    tabPress.tab = null;
    markTabSwitching();
    syncTabBarActive();
  }

  /* click пришёл: подсветка остаётся до выгрузки страницы (её сменит новая страница). */
  function commitTabPress(tabId) {
    clearTabPressTimer('revertTimer');
    tabPress.pointer = null;
    showTabPress(tabId);
    tabPress.committed = true;
  }

  /* Сброс без анимации: повторный тап, возврат страницы из bfcache. */
  function resetTabPress() {
    clearTabPressTimer('revertTimer');
    clearTabPressTimer('switchTimer');
    tabPress.tab = null;
    tabPress.pointer = null;
    tabPress.committed = false;
    var bar = document.getElementById('clientTabBar');
    if (bar) bar.classList.remove('client-tab-bar--switching');
    syncTabBarActive();
  }

  function isTrackedTabPointer(ev) {
    return tabPress.pointer !== null && !tabPress.committed && (!ev || ev.pointerId == null || ev.pointerId === tabPress.pointer);
  }

  document.addEventListener(
    'pointermove',
    function (ev) {
      if (!isTrackedTabPointer(ev)) return;
      var dx = (ev.clientX || 0) - tabPress.x;
      var dy = (ev.clientY || 0) - tabPress.y;
      if (Math.sqrt(dx * dx + dy * dy) > TAB_PRESS_MOVE_PX) cancelTabPress();
    },
    { passive: true }
  );
  document.addEventListener(
    'pointercancel',
    function (ev) {
      if (isTrackedTabPointer(ev)) cancelTabPress();
    },
    { passive: true }
  );
  document.addEventListener(
    'pointerup',
    function (ev) {
      if (!isTrackedTabPointer(ev)) return;
      tabPress.pointer = null;
      if (!tabPress.tab || typeof global.setTimeout !== 'function') return;
      // click идёт следом за pointerup; не пришёл — касание не стало нажатием.
      clearTabPressTimer('revertTimer');
      tabPress.revertTimer = global.setTimeout(function () {
        tabPress.revertTimer = null;
        cancelTabPress();
      }, TAB_PRESS_CLICK_WAIT_MS);
    },
    { passive: true }
  );
  global.addEventListener('pageshow', function (ev) {
    // Назад из bfcache: страница восстановлена с подсветкой вкладки, на которую уходили.
    if (ev && ev.persisted) resetTabPress();
  });

  function applyTabBarVisibility() {
    var bar = document.getElementById('clientTabBar');
    var body = document.body;
    if (!bar || !body) return;
    var show = state.mode === 'tabs' && state.tabBarVisible;
    if (show) {
      bar.removeAttribute('hidden');
      bar.classList.remove('client-tab-bar--hidden');
      body.classList.remove('client-shell-tabs-hidden');
    } else {
      bar.setAttribute('hidden', 'hidden');
      bar.classList.add('client-tab-bar--hidden');
      body.classList.add('client-shell-tabs-hidden');
    }
  }

  function normalizeRoutePath(path) {
    return String(path || '').replace(/^\.\//, '').split('#')[0];
  }

  function queryHasTabCatalog(q) {
    return q.indexOf('tab=catalog') >= 0 || q.indexOf('tab=') < 0;
  }

  /** Повторный тап «Поиск» на ice.html — выход с карты в список (см. IceCatalog.onTabRetap). */
  /* Повторный тап по текущей вкладке — плавно наверх, как в нативных приложениях. */
  function scrollPageTop() {
    var y = global.scrollY || global.pageYOffset || 0;
    if (y <= 0 || typeof global.scrollTo !== 'function') return;
    var reduce = false;
    try { reduce = global.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { /* */ }
    try {
      global.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
    } catch (e) {
      global.scrollTo(0, 0);
    }
  }

  function handleCatalogTabRetap() {
    try {
      if (global.IceCatalog && typeof global.IceCatalog.onTabRetap === 'function') {
        return !!global.IceCatalog.onTabRetap();
      }
    } catch (e) { /* */ }
    return false;
  }

  function isSameTabRoute(path) {
    var target = normalizeRoutePath(path);
    var targetPath = target.split('?')[0];
    var targetQuery = target.indexOf('?') >= 0 ? target.slice(target.indexOf('?') + 1) : '';
    var currentKey = pathnameKey();
    if (targetPath !== currentKey) return false;
    if (targetPath === 'catalog') {
      var curQ = (global.location.search || '').replace(/^\?/, '');
      return queryHasTabCatalog(targetQuery) && queryHasTabCatalog(curQ);
    }
    return true;
  }

  /* ── TASK-389: замер «нажатие на вкладку → содержимое показано» ─────────────
   *
   * Нажатие ставит метку в sessionStorage (откуда|куда|время), страница вкладки, когда её
   * содержимое показано, зовёт ClientShell.contentShown(); событие собирает tab-timing-model.js
   * (грузится только тогда, когда событие будет) и уходит на сервер уже после показа.
   * Ошибки глотаются: замер не должен ничего менять для клиента. Без персональных данных.
   */
  var TAP_KEY = 'tcb_tab_tap_v1';
  var TT_SEEN_KEY = 'tcb_tt_seen_v1';
  var tabTimingFirstPage = false;
  var tabTimingDone = false;
  var tabTimingNav = null;

  try {
    tabTimingFirstPage = !global.sessionStorage.getItem(TT_SEEN_KEY);
    global.sessionStorage.setItem(TT_SEEN_KEY, '1');
  } catch (e) { /* без storage первая страница неизвестна — холодный старт не считаем */ }

  function rememberTabTap(toTab) {
    try {
      var from = resolveActiveTab();
      var tab = from === null ? '' : String(from);
      global.sessionStorage.setItem(TAP_KEY, tab + '|' + toTab + '|' + Date.now());
    } catch (e) { /* замер не мешает навигации */ }
  }

  function readNavType() {
    try {
      var e = global.performance.getEntriesByType('navigation')[0];
      return e && e.type ? String(e.type) : 'navigate';
    } catch (err) {
      return 'navigate';
    }
  }

  function sendTabTiming(ev) {
    var initData = getInitData();
    if (!ev || !initData || typeof global.fetch !== 'function') return;
    try {
      global.fetch('/api/webapp/client/tab-timing', {
        method: 'POST',
        keepalive: true,
        headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData },
        body: JSON.stringify(ev),
      }).catch(function () {});
    } catch (e) { /* учёт не мешает показу */ }
  }

  function loadTabTimingModel(done) {
    if (global.TabTimingModel) return done(global.TabTimingModel);
    var s = document.createElement('script');
    s.async = true;
    s.src = assetUrl('/static/webapp/', 'tab-timing-model.js');
    s.onload = function () {
      done(global.TabTimingModel || null);
    };
    s.onerror = function () {};
    document.head.appendChild(s);
  }

  /**
   * Страница вкладки зовёт, когда на экране первое осмысленное содержимое (данные или тёплый
   * кэш, не скелетон). Один раз за загрузку страницы; время берётся в кадре после показа.
   */
  function contentShown() {
    if (tabTimingDone) return;
    tabTimingDone = true;
    try {
      var tapRaw = null;
      try {
        tapRaw = global.sessionStorage.getItem(TAP_KEY);
        global.sessionStorage.removeItem(TAP_KEY);
      } catch (e) { /* */ }
      if (!tapRaw && !tabTimingFirstPage) return;
      var measure = function () {
        if (document.visibilityState === 'hidden') return;
        var nowMs = Date.now();
        var sinceOriginMs = global.performance.now();
        var tg = getTg();
        var input = {
          tapRaw: tapRaw,
          firstPage: tabTimingFirstPage,
          nowMs: nowMs,
          sinceOriginMs: sinceOriginMs,
          tab: resolveActiveTab(),
          nav: tabTimingNav || readNavType(),
          platform: tg && tg.platform,
          seasonUi: uiFlags.season_ui,
        };
        loadTabTimingModel(function (model) {
          if (!model) return;
          sendTabTiming(model.buildEvent(input));
        });
      };
      if (typeof global.requestAnimationFrame === 'function') global.requestAnimationFrame(measure);
      else global.setTimeout(measure, 0);
    } catch (e) { /* замер не должен ломать страницу */ }
  }

  /* TASK-391: переход внутри оболочки — новый замер без перезагрузки (nav=shell). */
  function armTabTiming(nav) {
    tabTimingDone = false;
    tabTimingFirstPage = false;
    tabTimingNav = nav || null;
  }

  /* TASK-391: оболочка показала вкладку — подсветка нажатия больше не нужна, анимация бара доигрывает. */
  function tabSwitchDone() {
    clearTabPressTimer('revertTimer');
    tabPress.tab = null;
    tabPress.pointer = null;
    tabPress.committed = false;
    syncTabBarActive();
  }

  /* ── TASK-094: направление перехода ───────────────────────────────────────
   *
   * Направление знает только уходящая страница — новая видит лишь то, что её
   * открыли. Поэтому оно кладётся в sessionStorage перед уходом и читается на
   * pagereveal. Навигационный API, когда он есть, точнее (ловит и системную
   * кнопку «назад»), поэтому он в приоритете, а флаг — фолбэк.
   */
  var NAV_DIR_KEY = 'tcb_nav_dir_v1';
  var TAB_ORDER = { home: 0, catalog: 1, bookings: 2, more: 3 };
  var TAB_ORDER_SEASON = { home: 0, catalog: 1, bookings: 2, kk: 3, me: 4 };

  function rememberNavDirection(path) {
    var season = uiFlags.season_ui;
    var order = season ? TAB_ORDER_SEASON : TAB_ORDER;
    var from = order[resolveActiveTab()];
    var toTab = null;
    var key = normalizeRoutePath(path).split('?')[0];
    if (season) toTab = seasonTabForKey(key, '');
    else if (key === 'client-home') toTab = 'home';
    else if (key === 'ice' || key === 'catalog' || key === 'arena' || key === 'trainers') toTab = 'catalog';
    else if (key === 'client-bookings') toTab = 'bookings';
    var to = order[toTab];
    // Уход вглубь (карточка арены, «Ещё») — всегда «вперёд»: назад оттуда
    // вернёт системная кнопка, и её направление посчитает Navigation API.
    var dir = from != null && to != null && to < from ? 'back' : 'forward';
    try {
      global.sessionStorage.setItem(NAV_DIR_KEY, dir);
    } catch (e) {
      /* приватный режим — переход просто будет кросс-фейдом */
    }
  }

  function takeNavDirection() {
    try {
      var dir = global.sessionStorage.getItem(NAV_DIR_KEY);
      global.sessionStorage.removeItem(NAV_DIR_KEY);
      return dir === 'back' || dir === 'forward' ? dir : null;
    } catch (e) {
      return null;
    }
  }

  /*
   * TASK-391: «Кто кого» и витрина тренеров не подключают mini-app-client-theme.css, то есть не
   * включают переходы. Уходящая страница их включила — Chrome начинал переход и обрывал его на новой
   * странице (InvalidStateError «ViewTransition opt-in disabled» в консоли). Переход туда не
   * начинаем вовсе: на экране то же самое, что было (обрыв), без ошибки.
   */
  var NO_VIEW_TRANSITION_PAGE = /\/(kto-kogo|trainers)(\.html)?$/;

  function skipTransitionToPagesWithoutOptIn(ev) {
    var vt = ev && ev.viewTransition;
    var entry = ev && ev.activation && ev.activation.entry;
    if (!vt || !entry || !entry.url) return;
    try {
      if (NO_VIEW_TRANSITION_PAGE.test(new URL(entry.url).pathname)) vt.skipTransition();
    } catch (e) { /* */ }
  }

  function bindViewTransitions() {
    if ('onpageswap' in global) global.addEventListener('pageswap', skipTransitionToPagesWithoutOptIn);
    // Нет поддержки — ничего не подписываем, навигация остаётся как была.
    if (!('onpagereveal' in global)) return;
    global.addEventListener('pagereveal', function (ev) {
      if (!ev.viewTransition) return;
      // Флаг снимаем всегда, иначе он протечёт в следующий переход.
      var stored = takeNavDirection();
      /*
       * Навигационный API отвечает на другой вопрос: он знает про движение по
       * стеку истории, а не про смысл перехода. Уход «Лёд → Главная» — это
       * push вперёд по стеку, но назад по вкладкам. Поэтому API имеет право
       * утверждать только «это возврат по истории»; смысл остальных переходов
       * знает уходившая страница, и он лежит во флаге.
       */
      var traversalBack = false;
      var nav = global.navigation;
      if (nav && nav.activation && nav.activation.from && nav.activation.entry) {
        var fromIndex = nav.activation.from.index;
        var toIndex = nav.activation.entry.index;
        traversalBack =
          typeof fromIndex === 'number' && typeof toIndex === 'number' && toIndex >= 0 && toIndex < fromIndex;
      }
      var dir = traversalBack ? 'back' : stored || 'forward';
      try {
        ev.viewTransition.types.add(dir);
      } catch (e) {
        /* types не поддержаны — останется кросс-фейд по умолчанию */
      }
    });
  }

  function navigate(path, opts) {
    if (isSameTabRoute(path)) {
      closeMoreSheet();
      if (normalizeRoutePath(path).split('?')[0] === 'ice' && handleCatalogTabRetap()) {
        syncTabBarActive();
        return;
      }
      syncTabBarActive();
      return;
    }
    if (!(opts && opts.replace) && shellTabs() && shellTabs().go(path)) return;
    rememberNavDirection(path);
    /* /p/… — публичная страница места, не файл внутри /static/webapp/. */
    var raw = String(path || '');
    var url = raw.charAt(0) === '/' ? withInit(raw) : withInit(webappBasePath() + raw);
    // Full page loads in Telegram WebView: View Transitions delay navigation until snapshot capture.
    if (opts && opts.replace) global.location.replace(url);
    else global.location.href = url;
  }

  document.addEventListener('click', function (ev) {
    var tg = getTg();
    if (ev.defaultPrevented || !tg || !getInitData()) return;
    var a = ev.target.closest('a[href]');
    if (!a) return;
    var url = new URL(a.href, global.location.href);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
    if (url.origin === new URL(global.location.href).origin && a.getAttribute('target') !== '_blank' && a.getAttribute('data-action') !== 'external') return;
    ev.preventDefault();
    try {
      tg.openLink(url.href, { try_instant_view: false });
    } catch (e) {
      if (typeof tg.showAlert === 'function') tg.showAlert('Не удалось открыть ссылку. Попробуйте ещё раз.');
    }
  });

  function openMoreSheet() {
    if (uiFlags.season_ui) return; // «Ещё» в режиме season_ui нет
    refreshWatchesSummary();
    state.moreOpen = true;
    var overlay = document.getElementById('clientMoreOverlay');
    if (!overlay) return;
    overlay.classList.add('client-more-sheet-overlay--open');
    var sheet = document.getElementById('clientMoreSheet');
    if (sheet) {
      resetMoreSheetDragTransform(sheet);
      sheet.classList.add('client-more-sheet--open');
    }
    syncMoreSheetBodyLock();
    syncTabBarActive();
  }

  function closeMoreSheet() {
    state.moreOpen = false;
    var overlay = document.getElementById('clientMoreOverlay');
    if (!overlay) return;
    overlay.classList.remove('client-more-sheet-overlay--open');
    var sheet = document.getElementById('clientMoreSheet');
    if (sheet) {
      sheet.classList.remove('client-more-sheet--open');
      resetMoreSheetDragTransform(sheet);
    }
    syncMoreSheetBodyLock();
    syncTabBarActive();
  }

  function toggleMoreSheet() {
    if (state.moreOpen) closeMoreSheet();
    else openMoreSheet();
  }

  function setTabBarVisible(visible) {
    state.tabBarVisible = !!visible;
    applyTabBarVisibility();
  }

  function setForcedTab(tabId) {
    state.forcedTab = tabId || null;
    syncTabBarActive();
  }

  function init(opts) {
    opts = opts || {};
    var body = document.body;
    if (!body) return;

    var attr = body.getAttribute('data-client-shell');
    state.baseMode = opts.mode || attr || 'hidden';
    state.mode = computeMode(state.baseMode);
    state.inited = true;
    if (state.mode !== 'tabs') return;

    body.classList.add('client-shell-body');

    var earlyBar = document.getElementById('clientTabBar');
    if (!earlyBar) {
      document.body.appendChild(buildTabBar());
    } else if (earlyBar.parentNode === body && earlyBar !== body.lastElementChild) {
      // Поставленная до разбора body панель — в конец, как раньше: порядок фокуса не меняется.
      body.appendChild(earlyBar);
    }
    // В режиме season_ui шторки «Ещё» нет вовсе — DOM не создаём.
    if (!uiFlags.season_ui && !document.getElementById('clientMoreOverlay')) {
      document.body.appendChild(buildMoreSheet());
    }

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && state.moreOpen) closeMoreSheet();
    });
    wireKeyboardHide();

    applyTabBarVisibility();
    syncTabBarActive();
    observeTabBarMetrics();
  }

  /*
   * TASK-369: страница игры (kto-kogo) — вкладка «Кто кого»; бар там только в режиме season_ui,
   * без флага она остаётся без оболочки, как была.
   */
  function computeMode(base) {
    if (base === 'tabs') return 'tabs';
    if (uiFlags.season_ui && pathnameKey() === 'kto-kogo') return 'tabs';
    return base;
  }

  /*
   * TASK-369: клавиатура. Пока в фокусе поле ввода, бар прячется (visibility, не display и не
   * класс client-shell-tabs-hidden): место бара в раскладке остаётся, и содержимое не прыгает
   * ни при появлении клавиатуры, ни при возврате бара.
   */
  var NON_TEXT_INPUT = /^(checkbox|radio|button|submit|reset|range|file|color|image|hidden)$/i;

  function isTextEntry(el) {
    if (!el || !el.tagName) return false;
    var tag = String(el.tagName).toUpperCase();
    if (tag === 'TEXTAREA') return true;
    if (tag !== 'INPUT') return false;
    return !NON_TEXT_INPUT.test(el.type || (el.getAttribute && el.getAttribute('type')) || 'text');
  }

  function setKeyboardHidden(hidden) {
    state.kbdHidden = !!hidden;
    var bar = document.getElementById('clientTabBar');
    if (bar) bar.classList.toggle('client-tab-bar--kbd', state.kbdHidden);
    if (document.body) document.body.classList.toggle('client-shell-kbd', state.kbdHidden);
  }

  function wireKeyboardHide() {
    if (state.kbdWired) return;
    state.kbdWired = true;
    document.addEventListener('focusin', function (ev) {
      if (!uiFlags.season_ui || state.mode !== 'tabs') return;
      if (isTextEntry(ev.target)) setKeyboardHidden(true);
    });
    document.addEventListener('focusout', function (ev) {
      if (!uiFlags.season_ui || state.mode !== 'tabs' || !state.kbdHidden) return;
      // Фокус переезжает в соседнее поле — бар не мигает.
      if (isTextEntry(ev.relatedTarget)) return;
      setKeyboardHidden(false);
    });
  }

  /*
   * TASK-369: флаг сменился на лету (client-shell:ui-flags, TASK-366) — бар пересобирается на
   * месте. Без перезагрузки, без анимации: новый узел встаёт на место старого целиком.
   */
  function onUiFlagsChanged() {
    var body = document.body;
    if (!state.inited || !body) return;
    state.mode = computeMode(state.baseMode);
    var old = document.getElementById('clientTabBar');
    var overlay = document.getElementById('clientMoreOverlay');

    if (state.mode !== 'tabs') {
      if (state.moreOpen) closeMoreSheet();
      if (old) old.remove();
      if (overlay) overlay.remove();
      setKeyboardHidden(false);
      body.classList.remove('client-shell-body', 'client-shell-tabs-hidden');
      return;
    }

    body.classList.add('client-shell-body');
    if (state.moreOpen) closeMoreSheet();
    setKeyboardHidden(false);
    var next = buildTabBar();
    if (old) old.replaceWith(next);
    else body.appendChild(next);

    if (uiFlags.season_ui) {
      if (overlay) overlay.remove();
    } else if (!overlay) {
      body.appendChild(buildMoreSheet());
    }
    wireKeyboardHide();
    applyTabBarVisibility();
    syncTabBarActive();
    observeTabBarMetrics();
  }

  /*
   * Фактическая высота панели → --client-tab-bar-measured (TASK-093).
   *
   * CSS знает только заявленные 62px, а панель рендерится в 69px: высота зависит от
   * гарнитуры и от того, перенеслась ли подпись. Разница уходила в нижний отступ
   * полотна, и последние 7px контента оставались под панелью на каждом экране.
   *
   * Пишем в ОТДЕЛЬНУЮ переменную, а не в --client-tab-bar-height: та задаёт панели
   * min-height, и запись измеренного значения обратно в неё замкнула бы наблюдателя
   * сам на себя.
   */
  function syncTabBarMetrics() {
    var bar = document.getElementById('clientTabBar');
    if (!bar) return;
    var h = Math.round(bar.getBoundingClientRect().height);
    if (!h) return;
    try {
      document.documentElement.style.setProperty('--client-tab-bar-measured', h + 'px');
    } catch (e) { /* */ }
  }

  function observeTabBarMetrics() {
    var bar = document.getElementById('clientTabBar');
    if (!bar) return;
    syncTabBarMetrics();

    /*
     * Наблюдатель нужен не «на всякий случай»: первый замер снимается системным
     * фолбэком, Golos Text доезжает позже и меняет высоту подписи. Без пересчёта
     * мы зафиксировали бы высоту чужого шрифта.
     */
    if (typeof global.ResizeObserver === 'function') {
      try {
        new global.ResizeObserver(syncTabBarMetrics).observe(bar);
      } catch (e) {
        global.addEventListener('resize', syncTabBarMetrics);
      }
    } else {
      global.addEventListener('resize', syncTabBarMetrics);
    }

    if (document.fonts && document.fonts.ready && typeof document.fonts.ready.then === 'function') {
      document.fonts.ready.then(syncTabBarMetrics).catch(function () { /* */ });
    }
  }

  function writeCatalogWarmCache(payload) {
    try {
      sessionStorage.setItem(
        CATALOG_WARM_KEY,
        JSON.stringify({
          ts: Date.now(),
          session: payload.session || null,
          trainerEdges: payload.trainerEdges || null,
          servicesByCity: payload.servicesByCity || null,
        })
      );
    } catch (e) { /* quota */ }
  }

  function readCatalogWarmCache() {
    try {
      var raw = sessionStorage.getItem(CATALOG_WARM_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || !parsed.ts || Date.now() - parsed.ts > CATALOG_WARM_TTL_MS) {
        sessionStorage.removeItem(CATALOG_WARM_KEY);
        return null;
      }
      return parsed;
    } catch (e) {
      return null;
    }
  }

  /** Warm session + trainer edges while user stays on hub — catalog opens with data already in memory. */
  function patchMoreSheetWatchesBadge() {
    var sheet = document.getElementById('clientMoreSheet');
    if (!sheet) return;
    var link = sheet.querySelector('.client-more-sheet__link');
    if (!link) return;
    var existing = link.querySelector('.client-more-sheet__badge');
    var n = state.watchesActiveCount;
    if (n <= 0) {
      if (existing) existing.remove();
      return;
    }
    if (!existing) {
      existing = document.createElement('span');
      existing.className = 'client-more-sheet__badge';
      existing.setAttribute('aria-hidden', 'true');
      var plate = link.querySelector('.glide-more-plate');
      if (plate) plate.insertAdjacentElement('afterend', existing);
      else link.insertBefore(existing, link.firstChild);
    }
    existing.textContent = String(n);
  }

  function refreshWatchesSummary() {
    if (isPublicPlaceRoute()) return Promise.resolve();
    var initData = getInitData();
    if (!initData) return Promise.resolve();
    var headers = { 'X-Telegram-Init-Data': initData };
    return fetch('/api/webapp/client/watches/summary', { headers: headers, cache: 'no-store' })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (!data) return;
        state.watchesActiveCount = Number(data.active_count) || 0;
        patchMoreSheetWatchesBadge();
      })
      .catch(function () {});
  }

  /*
   * Один GET на страницу (TASK-332): сессию и окна тренера просили оболочка при старте,
   * прогрев соседних вкладок и сам экран — до трёх одинаковых запросов на открытие.
   * Неудача не кэшируется: следующий вызов спросит снова.
   */
  var jsonOnce = {};

  function getJsonOnce(path) {
    var initData = getInitData();
    if (!initData) return Promise.resolve(null);
    if (!jsonOnce[path]) {
      var headers = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData };
      jsonOnce[path] = global
        .fetch(path, { headers: headers, cache: 'no-store' })
        .then(function (r) {
          return r.ok ? r.json() : null;
        })
        .catch(function () {
          return null;
        })
        .then(function (data) {
          if (data == null) delete jsonOnce[path];
          return data;
        });
    }
    return jsonOnce[path];
  }

  function prefetchCatalogWarmCache() {
    var initData = getInitData();
    if (!initData) return Promise.resolve();
    return Promise.all([
      getJsonOnce('/api/webapp/client/session'),
      getJsonOnce('/api/webapp/client/trainer-edges'),
    ])
      .then(function (results) {
        var session = results[0];
        var edges = results[1];
        if (
          session &&
          typeof CatalogPublicUrl !== 'undefined' &&
          CatalogPublicUrl.applyClientSession
        ) {
          CatalogPublicUrl.applyClientSession(session);
        }
        if (!session && !edges) return;
        var cityId = session && session.city_id;
        if (!cityId) {
          writeCatalogWarmCache({ session: session, trainerEdges: edges, servicesByCity: null });
          return;
        }
        return fetch('/api/public/services?city_id=' + encodeURIComponent(cityId), { cache: 'no-store' })
          .then(function (r) {
            return r.ok ? r.json() : null;
          })
          .then(function (data) {
            var servicesByCity = null;
            if (data && data.items) {
              servicesByCity = {};
              servicesByCity[String(cityId)] = data.items;
            }
            writeCatalogWarmCache({ session: session, trainerEdges: edges, servicesByCity: servicesByCity });
          });
      })
      .catch(function () {});
  }

  /*
   * TASK-395: подгрузка ассетов соседних вкладок через fetch, а не <link rel="prefetch">.
   * WebKit (iPhone, Telegram на iOS) rel=prefetch не выполняет вовсе, поэтому на iPhone вкладки
   * раньше не подгружались совсем. fetch с чтением тела кладёт ответ в HTTP-кэш; ассеты с ?v=
   * отдаются public, max-age=31536000, immutable — страница потом берёт их из кэша.
   * Один и тот же href за жизнь страницы запрашивается один раз; ошибки глотаются.
   */
  var assetFetchSeen = {};

  function fetchAsset(href) {
    if (!href || assetFetchSeen[href] || typeof global.fetch !== 'function') return Promise.resolve();
    assetFetchSeen[href] = true;
    var forget = function () {
      delete assetFetchSeen[href];
    };
    try {
      return global
        .fetch(href, { credentials: 'same-origin', priority: 'low' })
        .then(function (r) {
          if (!r || !r.ok) {
            forget();
            return null;
          }
          /* Тело читаем до конца: без этого ответ может не лечь в кэш целиком. */
          return typeof r.arrayBuffer === 'function' ? r.arrayBuffer() : null;
        })
        .then(
          function () {},
          function () {
            forget();
          }
        );
    } catch (e) {
      forget();
      return Promise.resolve();
    }
  }

  function fetchAssets(hrefs) {
    return Promise.all(hrefs.map(fetchAsset)).then(function () {});
  }

  /** Prefetch catalog bundles while user reads the hub — cuts cold-start on tab switch. */
  function prefetchIceAssets() {
    var base = webappBasePath();
    return fetchAssets([
      assetUrl(base, 'ice-tab.js'),
      assetUrl(base, 'ice-tab-model.js'),
      assetUrl(base, 'ice-map-model.js'),
      assetUrl(base, 'ice-map.js'),
      assetUrl(base, 'ice-tab.css'),
    ]);
  }

  function prefetchCatalogAssets() {
    var base = webappBasePath();
    return fetchAssets([
      assetUrl(base, 'catalog-main.js'),
      assetUrl(base, 'mini-app-catalog.css'),
      assetUrl(base, 'mini-app-phone-field.js'),
    ]);
  }

  function writeBookingsWarmCache(payload) {
    try {
      var profileId = null;
      if (global.ClientProfileSwitcher && typeof global.ClientProfileSwitcher.getActiveProfileId === 'function') {
        profileId = global.ClientProfileSwitcher.getActiveProfileId();
      }
      sessionStorage.setItem(
        BOOKINGS_WARM_KEY,
        JSON.stringify({
          ts: Date.now(),
          days: payload.days || [],
          profile_id: profileId != null ? Number(profileId) : null,
        })
      );
    } catch (e) { /* quota */ }
  }

  function readBookingsWarmCache() {
    try {
      var raw = sessionStorage.getItem(BOOKINGS_WARM_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || !parsed.ts || Date.now() - parsed.ts > BOOKINGS_WARM_TTL_MS) {
        sessionStorage.removeItem(BOOKINGS_WARM_KEY);
        return null;
      }
      var acting = null;
      if (global.ClientProfileSwitcher && typeof global.ClientProfileSwitcher.getActiveProfileId === 'function') {
        acting = global.ClientProfileSwitcher.getActiveProfileId();
      }
      // Stale/wrong-profile warm data (often empty from a pre-profile race) must not paint.
      if (acting != null && parsed.profile_id != null && Number(parsed.profile_id) !== Number(acting)) {
        sessionStorage.removeItem(BOOKINGS_WARM_KEY);
        return null;
      }
      return parsed;
    } catch (e) {
      return null;
    }
  }

  /** Warm bookings list while user reads hub — «Записи» opens instantly when empty. */
  function prefetchBookingsWarmCache() {
    var initData = getInitData();
    if (!initData) return Promise.resolve();
    var ready =
      global.ClientProfileSwitcher && typeof global.ClientProfileSwitcher.init === 'function'
        ? global.ClientProfileSwitcher.init()
        : Promise.resolve();
    return ready
      .then(function () {
        return fetch('/api/webapp/client/bookings', {
          headers: { 'X-Telegram-Init-Data': initData },
          cache: 'no-store',
        });
      })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (data) writeBookingsWarmCache({ days: data.days || [] });
      })
      .catch(function () {});
  }

  function prefetchBookingsAssets() {
    return fetchAssets([assetUrl(webappBasePath(), 'mini-app-client-bookings.css')]);
  }

  /* TASK-369: ассеты соседних вкладок режима season_ui — на pointerdown, как у «Поиска». */
  function prefetchFiles(files) {
    var base = webappBasePath();
    return fetchAssets(
      files.map(function (entry) {
        /* Строка — файл рядом со страницей (/webapp/ или /static/webapp/) с версией оболочки;
           {file, base, v} — файл с другой базой/версией (игра грузится из /static/webapp/ со своими ?v=). */
        return typeof entry === 'string' ? assetUrl(base, entry) : assetUrl(entry.base, entry.file, entry.v);
      })
    );
  }

  /*
   * Список — из kto-kogo.html: адрес и ?v= те же, что у <link>/<script> страницы игры, иначе предзагрузка
   * не попадёт в кэш (а /webapp/kto-kogo*.js вовсе 404: маршрутов нет). write-access.js общий, он не kto-kogo*.
   * При бампе версий в kto-kogo.html правится и этот список; tests/js/client-shell-season-bar.test.js сверяет.
   */
  var KK_BASE = '/static/webapp/';
  var KK_ASSET_VERSIONS = [
    ['kto-kogo.css', '202611122'],
    ['kto-kogo-model.js', '202611122'],
    ['kto-kogo-screens-model.js', '202611122'],
    ['kto-kogo.js', '202611122'],
    ['kto-kogo-views.js', '202611122'],
    ['kto-kogo-hub-cards.js', '202611122'],
    ['kto-kogo-board.js', '202611122'],
    ['kto-kogo-leagues.js', '202611122'],
    ['kto-kogo-coin-model.js', '202611122'],
    ['kto-kogo-coin.js', '202611122'],
    ['kto-kogo-matches.js', '202611122'],
    ['kto-kogo-league-identity.js', '202611122'],
    ['kto-kogo-boot.js', '202611122'],
  ];
  /* Сервер подставляет в html всех страниц одну метку ?v= (asset_stamp.py), а не литерал из kto-kogo.html.
     Поэтому берём метку самой оболочки (ASSET_V — из её же <script src>); литерал из списка — запасной,
     когда версии у скрипта нет. Иначе адрес предзагрузки не совпадёт со страницей игры и кэш не сработает. */
  var KK_ASSETS = KK_ASSET_VERSIONS.map(function (pair) {
    return { file: pair[0], base: KK_BASE, v: ASSET_V || pair[1] };
  });

  /*
   * Шрифты (Dela Gothic, Golos) берём из glide-public-fonts.css, который сервер отдаёт с подставленной
   * версией шрифтов (app.py): адрес и ?v= совпадут с теми, что запросит страница. Часть начертаний уже
   * в кэше с Главной (там preload), остальные — 500 и т. п. — страница игры иначе качает в момент открытия.
   * CSS уже лежит в кэше страницы, повторный запрос дешёвый; один раз за жизнь страницы.
   */
  var FONT_URL_RE = /url\(\s*['"]?([^'")\s]*\.woff2\?v=[^'")\s]*)/g;
  var fontsPrefetch = null;

  function prefetchFonts() {
    if (fontsPrefetch) return fontsPrefetch;
    var sheet = document.querySelector && document.querySelector('link[href*="glide-public-fonts.css"]');
    var href = sheet && (sheet.getAttribute ? sheet.getAttribute('href') : sheet.href);
    if (!href || typeof global.fetch !== 'function') return Promise.resolve();
    fontsPrefetch = global
      .fetch(href, { credentials: 'same-origin', priority: 'low' })
      .then(function (r) {
        return r && r.ok ? r.text() : '';
      })
      .then(function (css) {
        var urls = [];
        var m;
        FONT_URL_RE.lastIndex = 0;
        while ((m = FONT_URL_RE.exec(css || ''))) urls.push(m[1]);
        return fetchAssets(urls);
      })
      .catch(function () {});
    return fontsPrefetch;
  }

  /*
   * Файлы, которые страница вкладки берёт с адресами, отличными от Главной (/static/webapp/ против /webapp/)
   * или которых на Главной нет. Только в фоне: на касании вкладки они конкурировали бы с самой страницей.
   * Файлы с no-cache (темы, telegram-chrome) не перечислены: кэш их всё равно не хранит.
   */
  var KK_EXTRA_FILES = ['mini-app-client-shell.css', 'mini-app-client-shell.js', 'write-access.js'].map(function (f) {
    return { file: f, base: KK_BASE, v: ASSET_V || KK_ASSET_VERSIONS[0][1] };
  });
  var ME_EXTRA_FILES = [
    { file: 'client-sheet.css', base: KK_BASE },
    { file: 'client-sheet.js', base: KK_BASE },
    { file: 'client-club-sheet.js', base: KK_BASE },
    { file: 'client-name-sheet.js', base: KK_BASE },
    { file: 'client-rink-sheet.js', base: KK_BASE },
    { file: 'minsk-time.js' },
    { file: 'opening-hours.js' },
    { file: 'glide-copy.js' },
    { file: 'public-display-model.js' },
  ];

  function prefetchKkExtras() {
    return Promise.all([prefetchFiles(KK_EXTRA_FILES), prefetchFonts()]).then(function () {});
  }

  function prefetchMeExtras() {
    var base = webappBasePath();
    return fetchAssets(
      ME_EXTRA_FILES.map(function (e) {
        return assetUrl(e.base || base, e.file);
      })
    );
  }

  function prefetchKkAssets() {
    return prefetchFiles(KK_ASSETS);
  }

  function prefetchMeAssets() {
    return prefetchFiles(['client-me.css', 'client-me.js']);
  }

  /*
   * Тёплый кэш «Я»: {ts, data} в sessionStorage['cw_me_warm_v1'] — TASK-370 читает его на первом
   * кадре (свежее 60 с). Свежий кэш не перезапрашиваем; параллельные тапы — один запрос.
   */
  var ME_WARM_KEY = 'cw_me_warm_v1';
  var ME_WARM_FRESH_MS = 30000;
  var meWarmInFlight = null;

  function prefetchMeWarmCache() {
    var initData = getInitData();
    if (!initData || typeof global.fetch !== 'function') return Promise.resolve();
    try {
      var cur = JSON.parse(global.sessionStorage.getItem(ME_WARM_KEY) || 'null');
      if (cur && cur.ts && Date.now() - cur.ts < ME_WARM_FRESH_MS) return Promise.resolve();
    } catch (e) { /* битый кэш — перезапросим */ }
    if (meWarmInFlight) return meWarmInFlight;
    meWarmInFlight = global
      .fetch('/api/webapp/client/me', { headers: { 'X-Telegram-Init-Data': initData }, cache: 'no-store' })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (!data) return;
        try {
          global.sessionStorage.setItem(ME_WARM_KEY, JSON.stringify({ ts: Date.now(), data: data }));
        } catch (e) { /* quota */ }
      })
      .catch(function () {})
      .then(function () {
        meWarmInFlight = null;
      });
    return meWarmInFlight;
  }

  /*
   * Страница записи: раньше сюда же входили сама страница `book` и mini-app-client-nav.css без ?v=.
   * Обе отдаются no-cache/no-store: через fetch в кэш они не ложатся (это ~100 КБ впустую на каждую
   * загрузку страницы, теперь и на iPhone), а страница берёт nav.css с версией — адрес не совпадал.
   * Остался только кэшируемый файл с ?v=.
   */
  function prefetchBookAssets() {
    return fetchAssets([assetUrl(webappBasePath(), 'mini-app-phone-field.js')]);
  }

  /* Экономия трафика и медленная сеть: фоном ничего не качаем (касание вкладки по-прежнему подгружает её). */
  function backgroundPrefetchAllowed() {
    var nav = global.navigator;
    var c = nav && (nav.connection || nav.mozConnection || nav.webkitConnection);
    if (!c) return true;
    if (c.saveData) return false;
    return !/(^|-)2g$/.test(String(c.effectiveType || ''));
  }

  /*
   * Шаги фоновой подгрузки: по одной вкладке за раз. Вкладка «Главная» и текущая страница не качаются.
   * Тёплые кэши данных — те же, что раньше (каталог, записи); для «Я» и «Кто кого» запросов данных нет.
   */
  function backgroundPrefetchSteps() {
    var steps = [];
    var step = function (fn) {
      steps.push(function () {
        return Promise.all(fn()).then(function () {});
      });
    };
    var catalogStep = function () {
      return [prefetchIceAssets(), prefetchCatalogAssets(), prefetchCatalogWarmCache()];
    };
    var bookingsStep = function () {
      return [prefetchBookingsAssets(), prefetchBookingsWarmCache()];
    };
    if (uiFlags.season_ui) {
      var active = resolveActiveTab();
      var tabs = seasonTabs();
      /* В оболочке соседняя живая вкладка — первая: иначе каталог (сотни КБ) занимает канал,
         и первый заход в «Записи»/«Я» не успевает прогреться. */
      var shell = shellTabs();
      if (shell) {
        var hosted = [];
        var rest = [];
        tabs.forEach(function (tab) {
          (shell.hosts(tab.id) ? hosted : rest).push(tab);
        });
        tabs = hosted.concat(rest);
      }
      tabs.forEach(function (tab) {
        if (tab.id === active) return;
        if (shell && shell.hosts(tab.id)) step(function () { return [prefetchShellTab(tab.id)]; });
        else if (tab.id === 'catalog') step(catalogStep);
        else if (tab.id === 'bookings') step(bookingsStep);
        else if (tab.id === 'kk') step(function () { return [prefetchKkAssets(), prefetchKkExtras()]; });
        else if (tab.id === 'me') step(function () { return [prefetchMeAssets(), prefetchMeExtras()]; });
      });
    } else {
      step(catalogStep);
      step(bookingsStep);
    }
    step(function () { return [prefetchBookAssets()]; });
    return steps;
  }

  var backgroundPrefetchStarted = false;

  function scheduleCatalogNavigationPrefetch() {
    if (backgroundPrefetchStarted || !backgroundPrefetchAllowed()) return;
    backgroundPrefetchStarted = true;
    var whenIdle = function (fn) {
      if (typeof global.requestIdleCallback === 'function') {
        global.requestIdleCallback(fn, { timeout: 3000 });
      } else {
        global.setTimeout(fn, 600);
      }
    };
    var run = function () {
      var steps = backgroundPrefetchSteps();
      var i = 0;
      var next = function () {
        if (i >= steps.length || !backgroundPrefetchAllowed()) return;
        var step = steps[i++];
        var done = function () {
          whenIdle(next);
        };
        try {
          step().then(done, done);
        } catch (e) {
          done();
        }
      };
      next();
    };
    /* Только после первого экрана: страница дозагрузилась, дальше — в простое. */
    var start = function () {
      whenIdle(run);
    };
    if (document.readyState === 'complete') start();
    else global.addEventListener('load', start, { once: true });
  }

  function escHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /**
   * TASK-096: one renderer, not two. The implementation lives in mini-app-empty-state.js so that
   * shell-free screens can use it; this stays as the call site the shell's own screens already use.
   * The old version tolerated an empty state with no CTA — that is exactly what AC-002 forbids,
   * so the shared renderer now refuses it instead of quietly drawing a dead end.
   */
  function renderEmptyState(container, options) {
    if (!container) return;
    options = options || {};
    var title = options.title || 'Пока пусто';
    var fallbackHtml = '<div class="empty">' + escHtml(title) + '</div>';
    var comp = global.MiniAppEmptyState;
    if (!comp || typeof comp.render !== 'function') {
      if (global.console && global.console.error) {
        global.console.error('ClientShell.renderEmptyState: mini-app-empty-state.js is not loaded');
      }
      // TASK-103: without this, «Мои записи» keeps the skeleton forever when the
      // shared file 404s — the list fetch already succeeded, only the empty paint failed.
      container.innerHTML = fallbackHtml;
      return;
    }
    var painted = comp.render(container, {
      icon: options.icon || TAB_ICONS.catalog,
      title: title,
      hint: options.hint,
      ctaLabel: options.ctaLabel,
      ctaPath: options.ctaPath,
      ctaHref: options.ctaHref,
      onCta: options.onCta,
      secondaryLabel: options.secondaryLabel,
      secondaryPath: options.secondaryPath,
      onSecondary: options.onSecondary,
    });
    // Same stuck-skeleton failure when CTA is omitted: MiniAppEmptyState returns false
    // and leaves the container untouched (e.g. empty booking history for a parent profile).
    if (!painted) {
      container.innerHTML = fallbackHtml;
    }
  }

  function renderSkeletonList(container, count) {
    if (!container) return;
    count = count || 4;
    var html = '<div class="client-skel-list" role="status" aria-busy="true" aria-label="Загрузка">';
    for (var i = 0; i < count; i++) {
      html +=
        '<div class="client-skel-card client-skel-shimmer">' +
        '<div class="client-skel-line client-skel-line--wide"></div>' +
        '<div class="client-skel-line client-skel-line--mid"></div>' +
        '<div class="client-skel-line client-skel-line--short"></div>' +
        '</div>';
    }
    html += '</div>';
    container.innerHTML = html;
  }

  global.ClientShell = {
    VERSION: SHELL_VERSION,
    init: init,
    navigate: navigate,
    withInit: withInit,
    webappBasePath: webappBasePath,
    setTabBarVisible: setTabBarVisible,
    setForcedTab: setForcedTab,
    openMoreSheet: openMoreSheet,
    closeMoreSheet: closeMoreSheet,
    toggleMoreSheet: toggleMoreSheet,
    syncTabBarActive: syncTabBarActive,
    renderEmptyState: renderEmptyState,
    renderSkeletonList: renderSkeletonList,
    hapticSelection: hapticSelection,
    hapticSuccess: hapticSuccess,
    getJsonOnce: getJsonOnce,
    prefetchCatalogWarmCache: prefetchCatalogWarmCache,
    prefetchCatalogAssets: prefetchCatalogAssets,
    prefetchIceAssets: prefetchIceAssets,
    scheduleCatalogNavigationPrefetch: scheduleCatalogNavigationPrefetch,
    readCatalogWarmCache: readCatalogWarmCache,
    writeCatalogWarmCache: writeCatalogWarmCache,
    prefetchBookingsWarmCache: prefetchBookingsWarmCache,
    prefetchBookingsAssets: prefetchBookingsAssets,
    prefetchBookAssets: prefetchBookAssets,
    readBookingsWarmCache: readBookingsWarmCache,
    writeBookingsWarmCache: writeBookingsWarmCache,
    maybeOpenArenaDeepLink: maybeOpenArenaDeepLinkWithSession,
    deepLinkTarget: deepLinkTarget,
    reportCatalogPresence: reportCatalogPresence,
    contentShown: contentShown,
    armTabTiming: armTabTiming,
    tabSwitchDone: tabSwitchDone,
    fetchAsset: fetchAsset,
    readStartParam: readStartParam,
    TAB_ICONS: TAB_ICONS,
    uiFlags: getUiFlags,
  };

  function readStartParam() {
    var tg = getTg();
    var fromTg = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    if (fromTg) return String(fromTg);
    try {
      var hash = global.location.hash || '';
      var m = /(?:^|[&#])tgWebAppStartParam=([^&]+)/.exec(hash);
      if (m) return decodeURIComponent(m[1]);
    } catch (e) { /* ignore */ }
    try {
      var qp = new URLSearchParams(global.location.search || '');
      return qp.get('tgWebAppStartParam') || qp.get('startapp') || '';
    } catch (e2) {
      return '';
    }
  }

  /**
   * startapp-диплинки (src/application/place_links.py — там же их собирает сервер):
   *   arena_<id>[_s_<session>]     → карточка места, при сеансе — на этот сеанс;
   *   catalog_<city>[_<token>][_<when>]
   *     token: skate | coach — интент; shop | gym | ice | outdoor | choreo | pool | other — тип места.
   *     when: today_evening | today | tomorrow | weekend — то же окно, что на /c/.
   * Срабатывает один раз за сессию мини-аппа: start_param живёт всё время, пока
   * открыт WebView, и без защёлки «Назад» с карточки снова уводил бы на неё же.
   */
  var DEEP_LINK_FLAG = 'glide_start_param_used_v1';
  var CATALOG_PRESENCE_PREFIX = 'glide_cat_presence_v1_';

  /**
   * Учёт входа в мини-апп каталога (WAU, startapp после шаринга). Один раз на surface/день/start_param.
   */
  function reportCatalogPresence(surface, startParam, extra) {
    if (isPublicPlaceRoute()) return;
    var tg = getTg();
    if (!tg || !tg.initData) return;
    var sp = startParam != null ? String(startParam).trim() : '';
    var day = new Date().toISOString().slice(0, 10);
    var dedupeKey = CATALOG_PRESENCE_PREFIX + surface + '_' + day + '_' + sp;
    try {
      if (global.sessionStorage.getItem(dedupeKey)) return;
      global.sessionStorage.setItem(dedupeKey, '1');
    } catch (e) { /* */ }
    var body = { surface: surface, start_param: sp || null };
    if (extra && extra.city_id) body.city_id = Number(extra.city_id);
    if (extra && extra.arena_id) body.arena_id = Number(extra.arena_id);
    global.fetch('/api/webapp/client/catalog/presence', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': tg.initData,
      },
      body: JSON.stringify(body),
    }).catch(function () {});
  }

  function deepLinkTarget(sp) {
    var G = global.GlideDeepLink;
    if (G && typeof G.deepLinkTarget === 'function') {
      return G.deepLinkTarget(sp);
    }
    sp = String(sp || '').trim();
    var arena = /^arena[_-]([1-9][0-9]*)(?:_s_([1-9][0-9]*))?$/i.exec(sp);
    if (arena) {
      var arenaPath = 'arena?ref=' + arena[1];
      if (arena[2]) arenaPath += '&s=' + arena[2];
      return { key: 'arena', path: arenaPath };
    }
    // Голый «catalog» — маркетинговая ссылка /go: каталог без города, город — по геолокации.
    if (/^catalog$/i.test(sp)) return { key: 'ice', path: 'ice' };
    // Запасной разбор, если glide-deeplink.js не загрузился: trainer_<id> + хвосты _a_/_s_/_v_ в любом порядке.
    var coach = /^trainer_([1-9][0-9]*)((?:_[a-z]+_[A-Za-z0-9]+)*)$/i.exec(sp);
    if (coach) {
      var tail = coach[2] || '';
      var arenaTail = /_a_([1-9][0-9]*)(?=_|$)/i.exec(tail);
      var slotTail = /_s_([1-9][0-9]*)(?=_|$)/i.exec(tail);
      var viaTail = /_v_([A-Za-z0-9]+)(?=_|$)/i.exec(tail);
      var intentTail = /_i_(save|request)(?=_|$)/i.exec(tail);
      // Как GlideDeepLink.trainerDeepLinkTarget: со слотом — запись и метка источника в адресе.
      return {
        key: 'trainers',
        path:
          'trainers?trainer_id=' + coach[1] +
          (slotTail ? '&slot_id=' + slotTail[1] : '') +
          (arenaTail ? '&arena_id=' + arenaTail[1] : '') +
          (slotTail && viaTail ? '&via=' + encodeURIComponent(viaTail[1].toLowerCase()) : '') +
          (!slotTail && intentTail ? '&intent=' + intentTail[1].toLowerCase() : ''),
      };
    }
    // «Кто кого»: приглашение в лигу друзей (TASK-298/299).
    var league = /^kk_([A-Za-z0-9]{4,16})$/.exec(sp);
    if (league) return { key: 'kto-kogo', path: 'kto-kogo?join=' + league[1].toUpperCase() };
    // Кнопки карточек в чате (TASK-300): kkl_КОД — приглашение, kkr[_КОД] — итог «в точку!».
    var fromCard = /^kk([lr])(?:_([A-Za-z0-9]{4,16}))?$/.exec(sp);
    if (fromCard) {
      var cardKind = fromCard[1] === 'l' ? 'league' : 'result';
      if (fromCard[2]) return { key: 'kto-kogo', path: 'kto-kogo?join=' + fromCard[2].toUpperCase() + '&from=' + cardKind };
      if (cardKind === 'result') return { key: 'kto-kogo', path: 'kto-kogo?from=result' };
    }
    // Домашний матч — ивент (TASK-304): kkm_<матч>[_<код компании>] — «Подробнее» и «Позвать» из чата.
    var matchEvent = /^kkm_([1-9][0-9]*)(?:_([A-Za-z0-9]{4,16}))?$/.exec(sp);
    if (matchEvent) {
      return { key: 'client-match', path: 'client-match?id=' + matchEvent[1] + (matchEvent[2] ? '&c=' + matchEvent[2] : '') };
    }
    var company = /^company_([1-9][0-9]*)$/i.exec(sp);
    if (company) return { key: 'ice-company', path: 'ice-company?s=' + company[1] };
    var catalog = /^catalog_([1-9][0-9]*)(?:_(skate|coach|shop|gym|ice|outdoor|choreo|pool|other|ohm|service))?(?:_(today_evening|today|tomorrow|weekend))?$/i.exec(sp);
    if (catalog) {
      var q = 'city_id=' + catalog[1];
      var intent = (catalog[2] || '').toLowerCase();
      var when = (catalog[3] || '').toLowerCase();
      var venueToken = intent === 'shop' || intent === 'gym' || intent === 'ice' || intent === 'outdoor' ||
        intent === 'choreo' || intent === 'pool' || intent === 'other';
      if (venueToken) q += '&venue=' + intent;
      else if (intent) q += '&intent=' + intent;
      else if (when) q += '&intent=skate';
      if (when) q += '&when=' + when;
      return { key: 'ice', path: 'ice?' + q };
    }
    return null;
  }

  function isAlreadyOnDeepLinkTarget(target) {
    if (!target || !target.path) return false;
    var raw = String(target.path);
    if (raw.charAt(0) === '/') {
      var wantPath = raw.split('?')[0];
      var wantQuery = raw.indexOf('?') >= 0 ? '?' + raw.split('?').slice(1).join('?') : '';
      return global.location.pathname === wantPath && (global.location.search || '') === wantQuery;
    }
    var current = pathnameKey();
    if (current === target.key && target.key === 'arena') return true;
    if (current === target.key) {
      var qPart = target.path.indexOf('?') >= 0 ? target.path.split('?')[1] : '';
      return global.location.search === (qPart ? '?' + qPart : '');
    }
    return false;
  }

  function followDeepLinkTarget(sp, target) {
    if (!target) return false;
    try {
      if (global.sessionStorage.getItem(DEEP_LINK_FLAG) === sp) return false;
      global.sessionStorage.setItem(DEEP_LINK_FLAG, sp);
    } catch (e) { /* без storage — как раньше, по ключу страницы */ }
    if (isAlreadyOnDeepLinkTarget(target)) return false;
    navigate(target.path, { replace: true });
    return true;
  }

  function fetchPublicArenaCardForDeepLink(arenaId) {
    return global
      .fetch('/api/public/arenas/' + encodeURIComponent(String(arenaId)), { cache: 'no-store' })
      .then(function (r) {
        return r.ok ? r.json() : null;
      });
  }

  function maybeOpenArenaDeepLinkWithSession(session) {
    var sp = String(readStartParam() || '').trim();
    /* Колокольчик сайта (follow_arena_<id>) ведёт на ту же карточку, что arena_<id>. */
    if (global.GlideBellFollow) sp = global.GlideBellFollow.arenaStartParam(sp);
    var G = global.GlideDeepLink;
    var serverPlaceCard = !!(session && session.mini_app_server_place_card);
    if (G && typeof G.resolveArenaDeepLinkTarget === 'function') {
      return G.resolveArenaDeepLinkTarget(sp, {
        serverPlaceCard: serverPlaceCard,
        fetchPublicArenaCard: fetchPublicArenaCardForDeepLink,
      }).then(function (target) {
        return followDeepLinkTarget(sp, target);
      });
    }
    return Promise.resolve(followDeepLinkTarget(sp, deepLinkTarget(sp)));
  }

  function loadClientSessionBeforeDeepLink() {
    return getJsonOnce('/api/webapp/client/session');
  }

  /* Колокольчик сайта: подписка + запрос разрешения писать до ухода на карточку (bell-follow.js). */
  function runBellFollow() {
    var B = global.GlideBellFollow;
    var sp = String(readStartParam() || '').trim();
    var initData = getInitData();
    if (!B || !initData || !B.parseFollowStartParam(sp)) return Promise.resolve();
    var storage = null;
    try {
      storage = global.sessionStorage;
    } catch (e) { /* без storage */ }
    return B.run({
      tg: getTg(),
      startParam: sp,
      storage: storage,
      post: B.makePost(initData, global.fetch.bind(global)),
    }).catch(function () {});
  }

  function bootAfterSession(session) {
    if (
      session &&
      typeof CatalogPublicUrl !== 'undefined' &&
      CatalogPublicUrl.applyClientSession
    ) {
      CatalogPublicUrl.applyClientSession(session);
    }
    refreshWatchesSummary();
    reportCatalogPresence('miniapp_shell', readStartParam());
    return runBellFollow().then(function () {
      return maybeOpenArenaDeepLinkWithSession(session);
    }).then(function (opened) {
      if (opened) return;
      // На главной префетч каталога стартует после снятия скелетона: иначе он
      // занимает соединения, пока хаб ещё ждёт bootstrap.
      if (
        state.mode === 'tabs' &&
        pathnameKey() !== 'catalog' &&
        (pathnameKey() !== 'client-bookings' || inFastTabsShell()) &&
        pathnameKey() !== 'client-home'
      ) {
        scheduleCatalogNavigationPrefetch();
      }
      global.navigateClientHome = function () {
        navigate('client-home');
      };
    });
  }

  function boot() {
    if (isPublicPlaceRoute() && !getInitData()) return;
    init();
    if (typeof global.setTimeout === 'function') global.setTimeout(refreshUiFlags, 0);
    if (isPublicPlaceRoute()) {
      if (state.mode === 'tabs') setForcedTab('catalog');
      return;
    }
    loadClientSessionBeforeDeepLink().then(bootAfterSession);
  }

  /*
   * Панель — до первого кадра новой страницы (TASK-332). Иначе переход снимает
   * страницу без панели: она исчезает и появляется заново после DOMContentLoaded.
   * Скрипт стоит синхронно в <head>, поэтому body ещё нет — ждём, пока парсер его создаст.
   */
  function mountTabBarEarly() {
    var mount = function (body) {
      if (document.getElementById('clientTabBar')) return;
      var tabsPage = body.getAttribute('data-client-shell') === 'tabs';
      if (!tabsPage && !(uiFlags.season_ui && pathnameKey() === 'kto-kogo')) return;
      body.appendChild(buildTabBar());
      syncTabBarActive();
    };
    if (document.body) {
      mount(document.body);
      return;
    }
    if (typeof MutationObserver === 'undefined') return;
    var observer = new MutationObserver(function () {
      if (!document.body) return;
      observer.disconnect();
      mount(document.body);
    });
    observer.observe(document.documentElement, { childList: true });
  }

  try {
    if (getTg() && getInitData()) global.sessionStorage.setItem('glide_mini_app_active_v1', '1');
  } catch (e) { /* storage может быть запрещён */ }
  uiFlags = readUiFlags();
  mountTabBarEarly();
  global.addEventListener('client-shell:ui-flags', onUiFlagsChanged);

  /*
   * Подписка на pagereveal — на уровне модуля, а не в boot(): событие
   * срабатывает до первой отрисовки, то есть раньше DOMContentLoaded.
   * Подписаться позже значит не получить первый же переход.
   */
  bindViewTransitions();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(window);
