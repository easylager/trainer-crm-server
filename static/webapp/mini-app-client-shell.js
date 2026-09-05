/**
 * Client Mini App shell: bottom tab bar, «Ещё» sheet, navigate with init_data + view transitions.
 */
(function (global) {
  'use strict';

  var SHELL_VERSION = '202609062';

  var CATALOG_WARM_KEY = 'tcb_catalog_warm_v1';
  var CATALOG_WARM_TTL_MS = 90000;
  var BOOKINGS_WARM_KEY = 'tcb_bookings_warm_v1';
  var BOOKINGS_WARM_TTL_MS = 90000;

  var TAB_ICONS = {
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V9.5z"/></svg>',
    catalog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v18M5 7l14 10M19 7L5 17"/></svg>',
    bookings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    more: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="5" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="19" r="1.5" fill="currentColor" stroke="none"/></svg>',
  };

  var MORE_ITEMS = [
    {
      path: 'client-saved-trainers',
      label: 'Сохранённые',
      emoji: '🔖',
      hint: 'Тренеры из каталога — вернуться к записи в один тап',
    },
    {
      path: 'client-stats',
      label: 'Ваша активность',
      emoji: '🔥',
      hint: 'Серия тренировок и статистика сезона',
    },
    {
      path: 'client-passes-certificates',
      label: 'Абонементы',
      emoji: '🎫',
      hint: 'Сколько занятий осталось и подарочные сертификаты',
    },
    {
      path: 'client-family-access',
      label: 'Семейный доступ',
      emoji: '👨‍👩‍👧',
      hint: 'Близкие в одном аккаунте — записи и абонементы вместе',
    },
    {
      path: 'client-requests',
      label: 'Мои заявки',
      emoji: '💬',
      hint: 'Запрос на подбор тренера и ответы специалистов',
    },
  ];

  var MORE_CHEVRON =
    '<svg class="client-more-sheet__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M9 6l6 6-6 6"/></svg>';

  var state = {
    mode: 'hidden',
    tabBarVisible: true,
    moreOpen: false,
    forcedTab: null,
  };

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

  function resolveActiveTab() {
    if (state.forcedTab) return state.forcedTab;
    var key = pathnameKey();
    if (key === 'client-home') return 'home';
    if (key === 'arena' || key === 'ice') return 'catalog';
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

  function buildTabBar() {
    var nav = document.createElement('nav');
    nav.id = 'clientTabBar';
    nav.className = 'client-tab-bar';
    nav.setAttribute('role', 'tablist');
    nav.setAttribute('aria-label', 'Навигация');

    var tabs = [
      { id: 'home', label: 'Главная', path: 'client-home', icon: TAB_ICONS.home },
      { id: 'catalog', label: 'Лёд', path: 'ice', icon: TAB_ICONS.catalog },
      { id: 'bookings', label: 'Записи', path: 'client-bookings', icon: TAB_ICONS.bookings },
      { id: 'more', label: 'Ещё', path: null, icon: TAB_ICONS.more },
    ];

    tabs.forEach(function (tab) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'client-tab-bar__btn';
      btn.setAttribute('role', 'tab');
      btn.dataset.tabId = tab.id;
      btn.innerHTML =
        '<span class="client-tab-bar__icon-wrap">' +
        tab.icon +
        '</span><span>' +
        tab.label +
        '</span>';
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
          syncTabBarActive();
          return;
        }
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
      btn.innerHTML =
        '<span class="client-more-sheet__emoji" aria-hidden="true">' +
        item.emoji +
        '</span><span class="client-more-sheet__body"><span class="client-more-sheet__label">' +
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
    var active = resolveActiveTab();
    bar.querySelectorAll('.client-tab-bar__btn').forEach(function (btn) {
      var id = btn.dataset.tabId;
      var isActive = id === active || (id === 'more' && (state.moreOpen || isMoreRoute()));
      btn.classList.toggle('client-tab-bar__btn--active', !!isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
  }

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

  function navigate(path) {
    if (isSameTabRoute(path)) {
      closeMoreSheet();
      syncTabBarActive();
      return;
    }
    var url = withInit(webappBasePath() + path);
    // Full page loads in Telegram WebView: View Transitions delay navigation until snapshot capture.
    global.location.href = url;
  }

  function openMoreSheet() {
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
    state.mode = opts.mode || attr || 'hidden';
    if (state.mode !== 'tabs') return;

    body.classList.add('client-shell-body');

    if (!document.getElementById('clientTabBar')) {
      document.body.appendChild(buildTabBar());
    }
    if (!document.getElementById('clientMoreOverlay')) {
      document.body.appendChild(buildMoreSheet());
    }

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && state.moreOpen) closeMoreSheet();
    });

    applyTabBarVisibility();
    syncTabBarActive();
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
  function prefetchCatalogWarmCache() {
    var initData = getInitData();
    if (!initData) return Promise.resolve();
    var headers = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData };
    return Promise.all([
      fetch('/api/webapp/client/session', { headers: headers, cache: 'no-store' }).then(function (r) {
        return r.ok ? r.json() : null;
      }),
      fetch('/api/webapp/client/trainer-edges', { headers: headers }).then(function (r) {
        return r.ok ? r.json() : null;
      }),
    ])
      .then(function (results) {
        var session = results[0];
        var edges = results[1];
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

  /** Prefetch catalog bundles while user reads the hub — cuts cold-start on tab switch. */
  function prefetchIceAssets() {
    var base = webappBasePath();
    var assets = [
      { href: base + 'ice-tab.js?v=202609062', as: 'script' },
      { href: base + 'ice-tab-model.js?v=202609062', as: 'script' },
      { href: base + 'ice-tab.css?v=202609062', as: 'style' },
    ];
    assets.forEach(function (spec) {
      if (document.querySelector('link[rel="prefetch"][href="' + spec.href + '"]')) return;
      var link = document.createElement('link');
      link.rel = 'prefetch';
      link.href = spec.href;
      if (spec.as) link.as = spec.as;
      document.head.appendChild(link);
    });
  }

  function prefetchCatalogAssets() {
    var base = webappBasePath();
    var assets = [
      { href: base + 'catalog-main.js?v=202605273', as: 'script' },
      { href: base + 'mini-app-catalog.css?v=202605273', as: 'style' },
      { href: base + 'mini-app-phone-field.js?v=202606281', as: 'script' },
    ];
    assets.forEach(function (spec) {
      if (document.querySelector('link[rel="prefetch"][href="' + spec.href + '"]')) return;
      var link = document.createElement('link');
      link.rel = 'prefetch';
      link.href = spec.href;
      if (spec.as) link.as = spec.as;
      document.head.appendChild(link);
    });
  }

  function writeBookingsWarmCache(payload) {
    try {
      sessionStorage.setItem(
        BOOKINGS_WARM_KEY,
        JSON.stringify({ ts: Date.now(), days: payload.days || [] })
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
      return parsed;
    } catch (e) {
      return null;
    }
  }

  /** Warm bookings list while user reads hub — «Записи» opens instantly when empty. */
  function prefetchBookingsWarmCache() {
    var initData = getInitData();
    if (!initData) return Promise.resolve();
    return fetch('/api/webapp/client/bookings', {
      headers: { 'X-Telegram-Init-Data': initData },
      cache: 'no-store',
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
    var base = webappBasePath();
    var href = base + 'mini-app-client-bookings.css?v=202605279';
    if (document.querySelector('link[rel="prefetch"][href="' + href + '"]')) return;
    var link = document.createElement('link');
    link.rel = 'prefetch';
    link.href = href;
    link.as = 'style';
    document.head.appendChild(link);
  }

  /** Prefetch book page shell — hub slot taps open book?slot_id= directly. */
  function prefetchBookAssets() {
    var base = webappBasePath();
    var assets = [
      base + 'book',
      base + 'mini-app-client-nav.css',
      base + 'mini-app-phone-field.js?v=202606281',
    ];
    assets.forEach(function (href) {
      if (document.querySelector('link[rel="prefetch"][href="' + href + '"]')) return;
      var link = document.createElement('link');
      link.rel = 'prefetch';
      link.href = href;
      document.head.appendChild(link);
    });
  }

  function scheduleCatalogNavigationPrefetch() {
    var run = function () {
      prefetchIceAssets();
      prefetchCatalogAssets();
      prefetchCatalogWarmCache();
      prefetchBookingsAssets();
      prefetchBookingsWarmCache();
      prefetchBookAssets();
    };
    if (typeof global.requestIdleCallback === 'function') {
      global.requestIdleCallback(run, { timeout: 2000 });
    } else {
      setTimeout(run, 600);
    }
  }

  function escHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderEmptyState(container, options) {
    if (!container) return;
    options = options || {};
    var icon = options.icon || TAB_ICONS.catalog;
    var title = escHtml(options.title || 'Пока пусто');
    var hint = options.hint ? escHtml(options.hint) : '';
    var ctaLabel = options.ctaLabel;
    var ctaPath = options.ctaPath;

    var html =
      '<div class="client-empty-state" role="status">' +
      '<div class="client-empty-state__icon">' +
      icon +
      '</div>' +
      '<p class="client-empty-state__title">' +
      title +
      '</p>';
    if (hint) {
      html += '<p class="client-empty-state__hint">' + hint + '</p>';
    }
    if (ctaLabel && ctaPath) {
      html +=
        '<button type="button" class="btn-primary btn-block client-empty-state__cta" data-nav-path="' +
        ctaPath +
        '">' +
        ctaLabel +
        '</button>';
    }
    html += '</div>';
    container.innerHTML = html;
    var cta = container.querySelector('.client-empty-state__cta');
    if (cta) {
      cta.addEventListener('click', function () {
        hapticSelection();
        navigate(cta.getAttribute('data-nav-path'));
      });
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
    maybeOpenArenaDeepLink: maybeOpenArenaDeepLink,
    TAB_ICONS: TAB_ICONS,
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

  function maybeOpenArenaDeepLink() {
    var key = pathnameKey();
    if (key === 'arena') return false;
    var sp = String(readStartParam() || '').trim();
    var m = /^arena[_-](.+)$/i.exec(sp);
    if (!m) return false;
    navigate('arena?ref=' + encodeURIComponent(m[1]));
    return true;
  }

  function boot() {
    init();
    if (maybeOpenArenaDeepLink()) return;
    if (state.mode === 'tabs' && pathnameKey() !== 'catalog' && pathnameKey() !== 'client-bookings') {
      scheduleCatalogNavigationPrefetch();
    }
    /* Keep navigateClientHome for legacy buttons on tier B pages */
    global.navigateClientHome = function () {
      navigate('client-home');
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(window);
