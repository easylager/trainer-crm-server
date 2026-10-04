/**
 * TASK-053 / TASK-076 Ice tab page.
 * Skate/group: GET /api/public/ice/arenas. Coach: GET /api/public/trainers (city list).
 * Trainer card tap deep-links to catalog?trainer_id=… (no tab=catalog — that flashes the old funnel).
 * Chip itself stays on ice.html.
 */
(function (global) {
  'use strict';

  var M = global.IceTabModel;
  var state = {
    intent: 'skate',
    view: 'list',
    cityId: null,
    cityName: '',
    /* Мультивыбор услуг у «Тренеров»: пусто = «Все». */
    serviceIds: [],
    services: [],
    /* Выбранные типы площадок (ключи venue_type) и фасеты последнего ответа.
       Фасеты живут в state, а не выводятся из items: сервер считает их ДО
       фильтра, иначе выбранный чип исчез бы из собственного списка. */
    venueTypes: [],
    venueFacets: [],
    shopSourceItems: [],
    shopService: '',
    shopDiscipline: '',
    shopOpenNow: false,
    shopWhen: 'any',
    shopUiPicker: false,
    shopMapFiltersOpen: false,
    /* TASK-146 (Q-006): окно времени. auto — умный дефолт на сервере; window — что применено. */
    when: 'auto',
    whenDay: '',
    whenMenuExpanded: false,
    urlWhenHydrated: false,
    /* Где человек (lat,lon) — если разрешил геолокацию; ближние места выше. */
    near: null,
    /* «Рядом» нажата: лента по расстоянию (внутри групп окна времени). */
    nearOn: false,
    window: null,
    cities: [],
    items: [],
    skateCount: null,
    total: 0,
    cursor: null,
    loading: false,
    loadedIntent: null,
    /* Открытое выпадающее меню шапки: place | when | false */
    uiPicker: false,
  };
  var searchTimer = null;
  var fetchGen = 0;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function initData() {
    var rt = global.MiniAppRuntime;
    if (rt && typeof rt.getCredential === 'function') {
      var c = rt.getCredential();
      if (c) return c;
    }
    var tg = global.Telegram && global.Telegram.WebApp;
    return (tg && tg.initData) || '';
  }

  function authHeaders() {
    var d = initData();
    return d ? { 'X-Telegram-Init-Data': d } : {};
  }

  function shellNav(path) {
    persist();
    if (global.ClientShell && typeof global.ClientShell.navigate === 'function') {
      global.ClientShell.navigate(path);
      return;
    }
    global.location.href = path;
  }

  /* Тот же ключ, что arena-card.js: шапка рисует кадр мини-карточки, не ждущая hero. */
  function rememberArenaHero(item) {
    if (!item) return;
    var url = item.card || item.thumb || '';
    if (!url) return;
    try {
      sessionStorage.setItem(
        'glideArenaHero',
        JSON.stringify({
          id: item.id != null ? item.id : null,
          slug: item.slug || '',
          url: url,
        })
      );
    } catch (e) { /* private mode */ }
  }

  function persist() {
    M.saveIceState(
      {
        intent: state.intent,
        cityId: state.cityId,
        cityName: state.cityName,
        serviceIds: state.serviceIds,
        venueTypes: state.venueTypes,
        shopService: state.shopService,
        shopDiscipline: state.shopDiscipline,
        shopOpenNow: state.shopOpenNow,
        shopWhen: state.shopWhen,
        when: state.when,
        whenDay: state.whenDay,
        scrollY: global.scrollY || 0,
        view: state.view,
      },
      global.sessionStorage
    );
  }

  var mapCtl = null;

  function $(id) {
    return document.getElementById(id);
  }

  function setSearchPlaceholder() {
    var input = $('iceSearchInput');
    if (!input) return;
    var scope = M.catalogScope(state.intent, state.venueTypes);
    input.placeholder = M.catalogSearchPlaceholder(scope);
  }

  function cityCountsForModes() {
    var city = cityFromState(state.cityId);
    return {
      skateCount: city != null ? city.skate_count : state.skateCount,
      trainerCount: city != null ? city.trainer_count : 0,
      placeCountHint: city != null ? city.place_count : 0,
    };
  }

  function closeUiPicker() {
    state.uiPicker = false;
    state.shopUiPicker = false;
  }

  function closeShopMapFiltersPanel() {
    state.shopMapFiltersOpen = false;
    state.shopUiPicker = false;
  }

  function onShopFiltersClick(ev) {
    var svc = ev.target.closest('[data-shop-service]');
    if (svc) {
      var key = svc.getAttribute('data-shop-service') || '';
      state.shopService = key;
      if (!M.shopDisciplineRowVisible(key)) state.shopDiscipline = '';
      syncShopListFromFilters();
      renderList();
      renderCatalogHeader();
      persist();
      return;
    }
    var disc = ev.target.closest('[data-shop-discipline]');
    if (disc) {
      var dkey = disc.getAttribute('data-shop-discipline') || '';
      state.shopDiscipline = state.shopDiscipline === dkey ? '' : dkey;
      syncShopListFromFilters();
      renderList();
      renderCatalogHeader();
      persist();
      return;
    }
    if (ev.target.closest('#iceShopOpenNow')) {
      state.shopOpenNow = !state.shopOpenNow;
      if (state.shopOpenNow) {
        state.shopWhen = 'any';
        state.shopUiPicker = false;
      }
      syncShopListFromFilters();
      renderList();
      renderCatalogHeader();
      persist();
      return;
    }
    if (ev.target.closest('#iceShopWhenBtn')) {
      if (state.shopOpenNow) return;
      state.shopUiPicker = !state.shopUiPicker;
      renderCatalogHeader();
      return;
    }
    var whenBtn = ev.target.closest('[data-shop-when]');
    if (whenBtn && whenBtn.closest('#iceShopWhenMenu')) {
      state.shopWhen = whenBtn.getAttribute('data-shop-when') || 'any';
      state.shopUiPicker = false;
      syncShopListFromFilters();
      renderList();
      renderCatalogHeader();
      persist();
      return;
    }
    var clearBtn = ev.target.closest('[data-shop-clear]');
    if (clearBtn) {
      var what = clearBtn.getAttribute('data-shop-clear') || '';
      if (what === 'all') {
        clearShopFilters();
        return;
      }
      if (what === 'service') state.shopService = '';
      if (what === 'discipline') state.shopDiscipline = '';
      if (what === 'open') state.shopOpenNow = false;
      if (what === 'when') state.shopWhen = 'any';
      syncShopListFromFilters();
      renderList();
      renderCatalogHeader();
      persist();
    }
  }

  function whenQueryForApi() {
    if (!M.whenPickerVisible(state.intent, state.venueTypes, state.venueFacets)) {
      return { when: '', whenDay: '' };
    }
    return { when: state.when, whenDay: state.whenDay };
  }

  function renderWhenMenuRow(row) {
    if (row.kind === 'toggle') {
      return (
        '<button type="button" class="ice-menu-toggle" data-when-toggle="1" aria-expanded="' +
        (row.expanded ? 'true' : 'false') +
        '"><span>' +
        esc(row.label) +
        '</span></button>'
      );
    }
    var pressed = row.active ? 'true' : 'false';
    var cls = 'ice-menu-day' + (row.nested ? ' ice-menu-day--nested' : '');
    var data =
      row.kind === 'preset'
        ? ' data-when-preset="' + esc(row.id) + '"'
        : ' data-when-day="' + esc(row.date) + '"';
    var sub = row.sub ? '<span class="ice-menu-sub">' + esc(row.sub) + '</span>' : '';
    return (
      '<button type="button" class="' +
      cls +
      '"' +
      data +
      ' aria-pressed="' +
      pressed +
      '"><span class="ice-menu-label">' +
      esc(row.label) +
      sub +
      '</span></button>'
    );
  }

  function renderWhenMenuHtml() {
    var resolved = state.window ? state.window.key : 'any';
    var view = M.whenMenuView({
      when: state.when,
      whenDay: state.whenDay,
      resolvedKey: resolved,
      menuExpanded: state.whenMenuExpanded,
    });
    var html = view.rows.map(renderWhenMenuRow).join('');
    html += '<div class="ice-menu-anchors">';
    html += view.anchors.map(renderWhenMenuRow).join('');
    html += '</div>';
    return html;
  }

  function shopFilterState() {
    return {
      shopService: state.shopService || '',
      shopDiscipline: state.shopDiscipline || '',
      shopOpenNow: !!state.shopOpenNow,
      shopWhen: state.shopWhen || 'any',
    };
  }

  function clearShopFilters(opts) {
    opts = opts || {};
    state.shopService = opts.shopService || '';
    state.shopDiscipline = '';
    state.shopOpenNow = false;
    state.shopWhen = 'any';
    closeUiPicker();
    closeShopMapFiltersPanel();
    syncShopListFromFilters();
    renderList();
    renderCatalogHeader();
    persist();
  }

  function syncMapListItems() {
    if (!mapCtl || state.intent === 'coach') return;
    if (!mapViewActive()) return;
    mapCtl.setListItems(state.items);
  }

  function syncShopListFromFilters() {
    if (!state.shopSourceItems.length) {
      state.items = [];
      state.total = 0;
      syncMapListItems();
      return;
    }
    state.items = M.filterShopCatalog(state.shopSourceItems, shopFilterState(), new Date());
    state.total = state.items.length;
    syncMapListItems();
  }

  function renderShopFilters(show) {
    var host = $('iceShopFilters');
    if (!host) return;
    if (!show) {
      host.hidden = true;
      host.classList.remove('is-expanded', 'ice-shop-filters--map');
      return;
    }
    /* Пока нет выдачи магазинов — не рисуем «пустую» шапку из статического HTML. */
    if (!state.shopSourceItems.length) {
      host.hidden = true;
      host.classList.remove('is-expanded', 'ice-shop-filters--map');
      return;
    }
    host.hidden = false;
    var onMap = mapViewActive();
    host.classList.toggle('ice-shop-filters--map', onMap);
    host.classList.toggle('is-expanded', onMap && state.shopMapFiltersOpen);
    if (!onMap && state.shopMapFiltersOpen) closeShopMapFiltersPanel();
    var filters = shopFilterState();
    var mapBar = $('iceShopMapBar');
    if (mapBar) mapBar.hidden = !onMap;
    var mapBtn = $('iceShopMapFiltersBtn');
    if (mapBtn) {
      mapBtn.setAttribute('aria-expanded', onMap && state.shopMapFiltersOpen ? 'true' : 'false');
    }
    var mapLabel = $('iceShopMapFiltersLabel');
    if (mapLabel) mapLabel.textContent = M.shopMapToolbarLabel(filters);
    var now = new Date();
    var serviceChips = M.shopServiceChipsView(state.shopSourceItems, filters, now);
    var serviceBox = $('iceShopServiceChips');
    if (serviceBox) {
      serviceBox.innerHTML = serviceChips
        .map(function (c) {
          return (
            '<button type="button" class="ice-chip ice-chip--shop" data-shop-service="' +
            esc(c.key) +
            '" aria-pressed="' +
            (c.active ? 'true' : 'false') +
            '">' +
            esc(c.label) +
            (c.key ? ' <span class="ice-chip__n">' + esc(String(c.count)) + '</span>' : '') +
            '</button>'
          );
        })
        .join('');
    }
    var openBtn = $('iceShopOpenNow');
    if (openBtn) openBtn.setAttribute('aria-pressed', state.shopOpenNow ? 'true' : 'false');
    var whenBtn = $('iceShopWhenBtn');
    if (whenBtn) {
      whenBtn.setAttribute('aria-pressed', state.shopWhen !== 'any' && !state.shopOpenNow ? 'true' : 'false');
      whenBtn.setAttribute('aria-expanded', state.shopUiPicker ? 'true' : 'false');
      var whenLabel = whenBtn.querySelector('span');
      if (whenLabel) whenLabel.textContent = M.shopWhenMenuLabel(state.shopOpenNow ? 'any' : state.shopWhen);
      whenBtn.disabled = !!state.shopOpenNow;
    }
    var whenMenu = $('iceShopWhenMenu');
    if (whenMenu) {
      whenMenu.hidden = !state.shopUiPicker;
      whenMenu.innerHTML = M.shopWhenMenuView(state.shopWhen)
        .map(function (w) {
          return (
            '<button type="button" data-shop-when="' +
            esc(w.key) +
            '" aria-pressed="' +
            (w.active ? 'true' : 'false') +
            '">' +
            esc(w.label) +
            '</button>'
          );
        })
        .join('');
    }
    var discBlock = $('iceShopDisciplineBlock');
    if (discBlock) discBlock.hidden = true;
    var activeHost = $('iceShopActiveFilters');
    if (activeHost) {
      activeHost.hidden = true;
      activeHost.innerHTML = '';
    }
  }

  function renderCatalogHeader() {
    var counts = cityCountsForModes();
    var modes = M.catalogModesView({
      facets: state.venueFacets,
      intent: state.intent,
      venueTypes: state.venueTypes,
      skateCount: counts.skateCount,
      trainerCount: counts.trainerCount,
      placeCountHint: counts.placeCountHint,
    });
    var modeSeg = $('iceModeSeg');
    if (modeSeg) {
      if (modes.length < 2) {
        modeSeg.hidden = true;
        modeSeg.innerHTML = '';
      } else {
        modeSeg.hidden = false;
        modeSeg.className = 'ice-seg ice-seg--' + modes.length;
        modeSeg.innerHTML = modes
          .map(function (m) {
            return (
              '<button type="button" role="tab" data-catalog-mode="' +
              esc(m.id) +
              '" aria-pressed="' +
              (m.active ? 'true' : 'false') +
              '">' +
              esc(m.label) +
              '</button>'
            );
          })
          .join('');
      }
    }

    var scope = M.catalogScope(state.intent, state.venueTypes);
    renderServiceChips();

    var tabs = $('icePlaceTabs');
    var tabItems = scope === 'places' ? M.placeTabsView(state.venueFacets, state.venueTypes) : [];
    if (tabs) {
      if (tabItems.length) {
        tabs.hidden = false;
        tabs.className = 'ice-seg ice-seg--quiet ice-seg--n' + tabItems.length;
        tabs.innerHTML = tabItems
          .map(function (c) {
            return (
              '<button type="button" role="tab" data-place-type="' +
              esc(c.key) +
              '" aria-pressed="' +
              (c.active ? 'true' : 'false') +
              '">' +
              esc(c.label) +
              '</button>'
            );
          })
          .join('');
      } else {
        tabs.hidden = true;
        tabs.innerHTML = '';
      }
    }

    var toolsHost = $('iceCatalogTools');
    var toolsRow = $('iceToolsRow');
    var placeMenu = $('icePlaceMenu');
    var whenMenu = $('iceWhenMenu');
    var needPlaceTool = scope === 'places' && M.placeMenuNeeded(state.venueFacets);
    var needWhen = M.whenPickerVisible(state.intent, state.venueTypes, state.venueFacets, {
      activeWindow: !!(state.window && state.window.key),
    });

    if (toolsHost && toolsRow) {
    if (!needPlaceTool && !needWhen) {
      toolsHost.hidden = true;
      toolsRow.innerHTML = '';
      if (placeMenu) placeMenu.hidden = true;
      if (whenMenu) whenMenu.hidden = true;
      if (state.uiPicker) closeUiPicker();
    } else {
    toolsHost.hidden = false;
    var toolHtml = '';
    if (needPlaceTool) {
      var placeOpen = state.uiPicker === 'place';
      toolHtml +=
        '<button type="button" class="ice-tool" data-ui-picker="place" aria-expanded="' +
        (placeOpen ? 'true' : 'false') +
        '"><span>' +
        esc(M.placeMenuLabel(state.venueFacets, state.venueTypes)) +
        '</span></button>';
      if (placeMenu) {
        var menuItems = M.placeMenuView(state.venueFacets, state.venueTypes);
        placeMenu.hidden = !placeOpen;
        placeMenu.innerHTML = menuItems
          .map(function (c) {
            return (
              '<button type="button" data-place-type="' +
              esc(c.key) +
              '" aria-pressed="' +
              (c.active ? 'true' : 'false') +
              '">' +
              esc(c.label) +
              '<b>' +
              esc(String(c.count != null ? c.count : '')) +
              '</b></button>'
            );
          })
          .join('');
      }
    } else if (placeMenu) {
      placeMenu.hidden = true;
      placeMenu.innerHTML = '';
    }

    if (needWhen) {
      var resolved = state.window ? state.window.key : 'any';
      var whenOpen = state.uiPicker === 'when';
      toolHtml +=
        '<button type="button" class="ice-tool" data-ui-picker="when" aria-expanded="' +
        (whenOpen ? 'true' : 'false') +
        '"><span>' +
        esc(M.whenPickerLabel(state.when, state.whenDay, resolved)) +
        '</span></button>';
      if (whenMenu) {
        whenMenu.hidden = !whenOpen;
        whenMenu.innerHTML = renderWhenMenuHtml();
      }
    } else if (whenMenu) {
      whenMenu.hidden = true;
      whenMenu.innerHTML = '';
      if (state.uiPicker === 'when') closeUiPicker();
    }

    var toolCount = (needPlaceTool ? 1 : 0) + (needWhen ? 1 : 0);
    toolsRow.className = 'ice-tools' + (toolCount === 1 ? ' ice-tools--one' : '');
    toolsRow.innerHTML = toolHtml;
    }
    }

    renderShopFilters(scope === 'shop');
    setSearchPlaceholder();
  }

  function setChips() {
    renderCatalogHeader();
  }

  function setCityLabel() {
    var name = state.cityName || 'Город';
    /* Город в двух местах: у чипов намерения (список) и внутри строки поиска (карта). */
    var els = document.querySelectorAll('.ice-citypill__name');
    Array.prototype.forEach.call(els, function (el) {
      el.textContent = name;
    });
  }

  function currentServiceLabel() {
    if (!state.serviceIds.length) return '';
    return (state.services || [])
      .filter(function (s) {
        return state.serviceIds.indexOf(Number(s.id)) >= 0;
      })
      .map(function (s) {
        return M.serviceChipLabel(s.name);
      })
      .join(', ');
  }

  /*
   * КАРТА (TASK-103, вернулась после TASK-084).
   *
   * Карту выключали не потому, что она плохая, а потому что сегмент «Список / Карта»
   * занимал верх первого экрана — против гейта G-P3 «товар над сгибом». Поэтому
   * вернулась она с другим носителем переключателя: плавающая пилюля #iceViewSwitch,
   * ноль высоты полотна (см. ice-tab.css).
   *
   * Флага MAP_ENABLED больше нет, и это осознанно. Он существовал, чтобы гасить один
   * класс багов: вид «карта» мог остаться в sessionStorage или прийти из ?view=map, и
   * экран открывался картой без способа вернуться в список. Правильное лекарство —
   * не второй предохранитель, а невозможность самого состояния: список ВСЕГДА
   * стартовое состояние экрана (см. boot(), где сохранённый и урловый view=map
   * сознательно игнорируются). Тогда «застрять на карте при входе» просто нечему.
   *
   * Тренеров на карте нет, поэтому для чипа «Тренеры» карта и переключатель скрыты.
   */
  var VIEWSWITCH_ICONS = {
    // Пин — «переключиться на карту»; список — «вернуться к списку».
    map: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>',
    list: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/></svg>',
  };

  function mapAllowed() {
    return state.intent !== 'coach';
  }

  function mapViewActive() {
    return mapAllowed() && state.view === 'map';
  }

  /**
   * Карта и список живут в одном DOM: класс body, hidden у секций и панель
   * фильтров магазинов легко расходятся с state.view (возврат из bfcache,
   * свайп шторки, закрытие sheet без setView). Подтягиваем вёрстку к state.
   */
  function repairCatalogChrome() {
    if (!mapViewActive() && state.shopMapFiltersOpen) closeShopMapFiltersPanel();
    setViewToggle();
    renderCatalogHeader();
  }

  function setViewToggle() {
    var allowed = mapAllowed();
    var showMapView = mapViewActive();

    var sw = $('iceViewSwitch');
    if (sw) {
      // TASK-147: в режиме карты пилюля скрыта — её роль у шторки.
      sw.hidden = !allowed || showMapView;
      // aria-pressed отвечает на «карта включена?», а подпись зовёт в другое
      // состояние — иначе кнопка называлась бы тем, что уже видно на экране.
      sw.setAttribute('aria-pressed', showMapView ? 'true' : 'false');
      var icon = $('iceViewSwitchIcon');
      var label = $('iceViewSwitchLabel');
      if (icon) icon.innerHTML = showMapView ? VIEWSWITCH_ICONS.list : VIEWSWITCH_ICONS.map;
      if (label) label.textContent = showMapView ? 'Список' : 'Карта';
    }

    var listSec = $('iceListSec');
    var mapSec = $('iceMapSec');
    if (listSec) listSec.hidden = showMapView;
    if (mapSec) mapSec.hidden = !showMapView;
    if (document.body) {
      document.body.classList.toggle('ice-view-map', !!showMapView);
    }
    if (showMapView) {
      showMap();
    }
  }

  /**
   * Повторный тап «Поиск» в нижнем баре на этой вкладке: выйти с карты (как «Списком»)
   * или закрыть оверлей поиска.
   */
  function onCatalogTabRetap() {
    if (mapViewActive()) {
      setView('list');
      return true;
    }
    var searchSec = $('iceSearchSec');
    if (searchSec && !searchSec.hidden) {
      var input = $('iceSearchInput');
      if (input) input.value = '';
      showSearch('');
      return true;
    }
    return false;
  }

  function setView(next) {
    var wanted = next === 'map' && mapAllowed() ? 'map' : 'list';
    if (state.view === wanted) return;
    state.view = wanted;
    closeShopMapFiltersPanel();
    setViewToggle();
    renderCatalogHeader();
    persist();
    setTelegramSwipes(wanted === 'map');
    if (wanted === 'list') {
      // Возврат в список — наверх: иначе после карты полотно открывается с середины.
      global.scrollTo({ top: 0, behavior: 'auto' });
    }
  }

  /*
   * TASK-147: свайп шторки в режиме карты конфликтует со свайпом закрытия
   * мини-аппа. Отключаем вертикальные свайпы на карте и возвращаем в списке.
   */
  function setTelegramSwipes(on) {
    var tg = global.Telegram && global.Telegram.WebApp;
    if (!tg) return;
    try {
      if (on && typeof tg.disableVerticalSwipes === 'function') tg.disableVerticalSwipes();
      if (!on && typeof tg.enableVerticalSwipes === 'function') tg.enableVerticalSwipes();
    } catch (e) {
      /* старый клиент Telegram — свайп остаётся как есть */
    }
  }

  function showMap() {
    if (!global.IceMap) {
      var emptyEl = $('iceMapEmpty');
      var stageEl = $('iceMapStage');
      var loaderEl = $('iceMapLoader');
      if (stageEl) stageEl.hidden = true;
      if (loaderEl) loaderEl.hidden = true;
      if (emptyEl && global.IceMapModel) {
        emptyEl.hidden = false;
        emptyEl.innerHTML =
          '<strong>Карта не загрузилась</strong><p>Обновите страницу. Файл карты не подключился.</p>';
      }
      return;
    }
    if (!mapCtl) {
      mapCtl = global.IceMap.mount({
        canvas: $('iceMapCanvas'),
        emptyEl: $('iceMapEmpty'),
        sheetEl: $('iceMapSheet'),
        nearBtn: $('iceNearBtn'),
        offMapEl: $('iceMapOffMap'),
        stageEl: $('iceMapStage'),
        loaderEl: $('iceMapLoader'),
        attribEl: $('iceMapAttrib'),
        listUrl: function (extra) {
          extra = extra || {};
          var opts = {
            intent: extra.intent || state.intent,
            /* Карта тянет данные своим запросом (bbox/near), а не берёт их у списка,
               поэтому фильтр надо прокидывать и сюда. Без этого чип «Зал» менял
               список, а на карте по-прежнему висели все катки города. */
            venueTypes: state.venueTypes,
            limit: extra.limit || 50,
            /* Окно времени — и на карту: иначе пин «19:30» под чипом «Завтра» — сегодняшний. */
            when: whenQueryForApi().when,
            whenDay: whenQueryForApi().whenDay,
          };
          if (extra.near) opts.near = extra.near;
          if (extra.bbox) opts.bbox = extra.bbox;
          if (extra.cityId != null && extra.cityId !== '') opts.cityId = extra.cityId;
          else if (state.cityId) opts.cityId = state.cityId;
          return M.buildMapListUrl(opts);
        },
        fetchJson: fetchJson,
        getIntent: function () {
          return state.intent;
        },
        getCatalogScope: function () {
          return M.catalogScope(state.intent, state.venueTypes);
        },
        getShopMapCaption: function () {
          if (M.catalogScope(state.intent, state.venueTypes) !== 'shop') return '';
          return M.shopMapToolbarLabel(shopFilterState());
        },
        getCityId: function () {
          return state.cityId;
        },
        listReady: function () {
          return !state.loading && !!state.cityId;
        },
        getCityCenter: function () {
          var city = cityFromState(state.cityId) || {};
          if (city.latitude == null || city.longitude == null) return null;
          return [Number(city.latitude), Number(city.longitude)];
        },
        // TASK city-wide-camera-bounds: min/max lat/lon over ALL geocoded arenas in
        // the city (not just the ones with a live session) — reused from the same
        // /api/public/ice/cities payload the city picker already fetched into
        // state.cities. Fixes the map locking Moscow/SPb to a tiny box around
        // whatever 1-2 arenas happen to have a schedule right now.
        getCityBounds: function () {
          var city = cityFromState(state.cityId) || {};
          return city.bounds || null;
        },
        arenaHref: M.arenaHref,
        onOpenArena: function (item, href) {
          /* Шторка рисует thumb — его и кладём в prefetch, не card. */
          if (item) rememberArenaHero({ id: item.id, slug: item.slug, card: '', thumb: item.thumb || item.card });
          if (href) shellNav(href);
        },
        onNearList: function (data) {
          if (state.intent === 'coach') return;
          applyArenaPayload(data);
          renderList();
        },
        // TASK-147: full-положение шторки = списочный вид вкладки.
        onSheetFull: function () {
          setView('list');
        },
        // Шапка шторки: «7 мест сегодня вечером …» — метка текущего окна.
        getWindow: function () {
          return state.window;
        },
        /* Магазины: услуга/дисциплина/часы — только на клиенте; bbox-запрос карты без этого. */
        filterMapItems: function (items) {
          if (M.catalogScope(state.intent, state.venueTypes) !== 'shop') return items || [];
          return M.filterShopCatalog(items || [], shopFilterState(), new Date());
        },
      });
    }
    mapCtl.setListItems(state.intent === 'coach' ? [] : state.items);
    mapCtl.start().then(function () {
      mapCtl.resize();
    });
  }

  function acardThumbStyle(src) {
    if (!src) return '';
    return ' style="background-image:url(\'' + esc(src).replace(/'/g, '%27') + '\')"';
  }

  /**
   * TASK-090: карточка катка — табло, а не строка CRM.
   * Кадр во всю ширину несёт карточку; время и имя лежат на кадре под скримом
   * и читаются сверху вниз «когда → где»; условия и глубина предложения —
   * отдельными строками на поверхности карточки, где контраст измерим.
   */
  function renderArenaCard(item) {
    var v = M.boardCardView(item, undefined, { window: state.window });
    /* TASK-148 (AC-2): нет фото — нет фото-блока. Плашка типа места: иконка
       с сервера (venue_icon), фолбэк — монограмма имени. */
    var photo = v.photo
      ? '<span class="ice-board__photo"' + acardThumbStyle(v.photo) + '>'
      : '<span class="ice-board__photo ice-board__photo--empty">' +
        '<span class="ice-board__initial" aria-hidden="true">' +
        esc(v.venueIcon || v.initial) +
        '</span>';
    var scrim =
      '<span class="ice-board__scrim">' +
      (v.offWindow ? '<span class="ice-board__off">' + esc(v.offLabel) + '</span>' : '') +
      (v.isSession
        ? '<span class="ice-board__day">' +
          esc(v.day) +
          '</span><span class="ice-board__time">' +
          esc(v.time) +
          '</span>'
        : '') +
      '<span class="ice-board__name">' +
      esc(v.name) +
      '</span>' +
      (v.where ? '<span class="ice-board__where">' + esc(v.where) + '</span>' : '') +
      '</span>';
    var facts = v.isSession
      ? v.prices
        ? '<span class="ice-board__prices">' + esc(v.prices) + '</span>'
        : ''
      : '<span class="ice-board__status">' + esc(v.status) + '</span>';
    /* «Позвать» — поверх кадра, но вне ссылки карточки: вложенная кнопка в <a> ломает
       клик на iOS, а тап должен звать друга, а не открывать карточку. */
    var invite =
      v.sessionId != null && global.GlideShareSheet
        ? '<button type="button" class="ice-board__invite" data-invite-arena="' + esc(v.arenaId) +
          '" data-invite-session="' + esc(v.sessionId) + '" data-invite-label="' + esc(v.inviteLabel) +
          '">Позвать</button>'
        : '';
    return (
      '<div class="ice-board-wrap">' +
      invite +
      '<a class="ice-board ice-board--type-' + esc(v.venueType) + (v.offWindow ? ' ice-board--off' : '') + '" href="' +
      esc(v.href) +
      '" data-href="' +
      esc(v.href) +
      '">' +
      photo +
      scrim +
      '</span>' +
      (facts ? '<span class="ice-board__facts">' + facts + '</span>' : '') +
      '<span class="ice-board__depth' + (v.stale ? ' ice-board__depth--stale' : '') + '">' +
      esc(v.depth) +
      '<span class="ice-board__go" aria-hidden="true">→</span>' +
      '</span>' +
      '</a>' +
      '</div>'
    );
  }

  function renderTrainerCard(item) {
    var view = M.trainerCardView(item);
    return (
      '<a class="ice-acard" href="' +
      esc(view.href) +
      '" data-href="' +
      esc(view.href) +
      '">' +
      '<span class="ice-acard__ph' +
      (view.thumb ? '' : ' ice-acard__ph--empty') +
      '"' +
      acardThumbStyle(view.thumb) +
      '>' +
      (view.thumb
        ? ''
        : '<span class="ice-acard__mono" aria-hidden="true">' + esc(view.initial || '?') + '</span>') +
      '</span>' +
      '<span class="ice-acard__body">' +
      '<span class="ice-acard__name">' +
      esc(view.name) +
      '</span>' +
      // Специализация — то, чем тренеры отличаются. Пустой строки не бывает:
      // услуга есть у каждого, кто попал в выдачу (по ней же работает фильтр).
      (view.spec ? '<span class="ice-acard__spec">' + esc(view.spec) + '</span>' : '') +
      '<span class="ice-acard__meta">' +
      esc(view.meta) +
      '</span>' +
      '<span class="ice-live ice-live--' +
      esc(view.tone || 'a') +
      '">' +
      esc(view.live) +
      '</span>' +
      '</span></a>'
    );
  }

  /**
   * TASK-095. Скелетоны собираются из тех же классов, что и живые карточки
   * (.ice-board / .ice-acard плюс модификатор), поэтому геометрия совпадает по
   * построению: правка карточки автоматически правит и её скелетон.
   */
  function boardSkeletons(n) {
    var one =
      '<div class="ice-board ice-board--skel" aria-hidden="true">' +
      '<span class="ice-board__photo ice-skel"></span>' +
      '<span class="ice-board__facts"><span class="ice-skel ice-skel--line"></span></span>' +
      '<span class="ice-board__depth"><span class="ice-skel ice-skel--line ice-skel--wide"></span></span>' +
      '</div>';
    return new Array(n + 1).join(one);
  }

  function trainerSkeletons(n) {
    var one =
      '<div class="ice-acard ice-acard--skel" aria-hidden="true">' +
      '<span class="ice-acard__ph ice-skel"></span>' +
      '<span class="ice-acard__body">' +
      '<span class="ice-skel ice-skel--line"></span>' +
      '<span class="ice-skel ice-skel--line ice-skel--short"></span>' +
      '</span></div>';
    return new Array(n + 1).join(one);
  }

  function listEl() {
    return $(M.listHostId(state.intent));
  }

  function showActiveList() {
    var skate = $('iceListSkate');
    var coach = $('iceListCoach');
    var coachOn = state.intent === 'coach';
    if (skate) skate.hidden = coachOn;
    if (coach) coach.hidden = !coachOn;
  }

  function renderList() {
    var list = listEl();
    var cap = $('iceCaption');
    if (cap) {
      cap.textContent = M.formatSortCaption({
        total: state.total,
        items: state.items,
        intent: state.intent,
        loadedIntent: state.loadedIntent,
        serviceLabel: currentServiceLabel(),
        loading: state.loading,
        venueTypes: state.venueTypes,
        window: state.window,
      });
    }
    parkShareButton();
    setShareButton();
    if (!list) return;
    var paint = M.listPaintMode({
      intent: state.intent,
      loadedIntent: state.loadedIntent,
      items: state.items,
      loading: state.loading,
    });
    if (paint === 'skeleton') {
      // TASK-095: вместо строки «Загрузка катков…» — коробки будущих карточек.
      // Текстовая строка обещала одну форму, а приходила совсем другая.
      list.innerHTML = state.intent === 'coach' ? trainerSkeletons(3) : boardSkeletons(2);
      showActiveList();
      return;
    }
    if (paint === 'empty') {
      var city = cityFromState(state.cityId) || {};
      var shopScope = M.catalogScope(state.intent, state.venueTypes) === 'shop';
      var empty;
      if (shopScope && state.shopSourceItems.length && M.hasActiveShopFilters(shopFilterState())) {
        empty = M.formatEmptyShopFilters({
          sharpeningCount: state.shopSourceItems.filter(function (it) {
            return (it.shop_services || []).indexOf('skate_sharpening') >= 0;
          }).length,
        });
      } else {
        empty = M.formatEmptyList(state.intent, {
          serviceName: state.intent === 'coach' && state.serviceIds.length ? currentServiceLabel() : '',
          trainerCount: city.trainer_count,
          mapRinkCount: city.map_rink_count,
          hasSkate: M.shouldShowSkateChip(state.skateCount),
        });
      }
      renderEmpty(list, empty, state.intent === 'coach' ? 'ice' : 'city');
      showActiveList();
      return;
    }
    if (state.intent === 'coach') {
      list.innerHTML = state.items.map(renderTrainerCard).join('');
      showActiveList();
      return;
    }
    /* TASK-146: окно сортирует, а не фильтрует. Между «в окне» и «вне окна» — липкая
       плашка: пока человек листает приглушённые карточки, она висит сверху и не даёт
       забыть, что это уже не ответ на выбранный чип. */
    var parts = M.orderForFeed(state.items, state.window, state.nearOn);
    var brk = parts.hits.length ? M.windowBreakView(state.window, parts.rest, state.venueTypes) : null;
    list.innerHTML =
      parts.hits.map(renderArenaCard).join('') +
      (brk
        ? '<div class="ice-window-break" role="separator">' +
          '<span class="ice-window-break__pill"><b>' + esc(brk.title) + '</b> · ' + esc(brk.sub) + '</span>' +
          '</div>'
        : '') +
      parts.rest.map(renderArenaCard).join('');
    /* Делимся найденным, а не всем списком: кнопка стоит сразу под блоком «в окне»,
       а приглушённые места без нужных сеансов идут уже после неё. */
    var brkEl = brk && list.querySelector('.ice-window-break');
    var shareBtn = $('iceShareBtn');
    if (brkEl && shareBtn) list.insertBefore(shareBtn, brkEl);
    showActiveList();
  }

  /* innerHTML списка стирает всё внутри — возвращаем кнопку на её штатное место под #iceList. */
  function parkShareButton() {
    var btn = $('iceShareBtn');
    var host = $('iceList');
    if (btn && host && btn.parentNode !== host.parentNode) host.parentNode.insertBefore(btn, host.nextSibling);
  }

  function recordIceInterest() {
    if (!state.cityId) return;
    fetch(M.buildIceInterestUrl(), {
      method: 'POST',
      cache: 'no-store',
      headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
      body: JSON.stringify({
        city_id: state.cityId,
        intent: 'skate',
        source: 'coming_soon_cta',
      }),
    })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function () {
        renderEmpty(
          listEl(),
          {
            title: 'Записали',
            body: 'Когда появится расписание в этом городе — вы уже в списке желающих.',
            action: { label: 'Показать тренеров', kind: 'intent:coach' },
          },
          'ice'
        );
      })
      .catch(function () {});
  }

  /**
   * TASK-096 (G-P5). Кнопка видна только там, где есть что переслать: город выбран,
   * намерение «покататься», список не пуст и не грузится. Артефакт — расписание
   * массовых катаний города; для «тренеров» его не существует, а шеринг тренера уже
   * живёт в четырёх других точках.
   */
  function shareAvailable() {
    // TASK-146 / TASK-168: подборка /c/{город} — для площадок (не тренеры/группы).
    if (!state.cityId || state.loading || !state.items.length) return false;
    return state.intent === 'skate';
  }

  function setShareButton() {
    var btn = $('iceShareBtn');
    if (!btn) return;
    var show = shareAvailable();
    btn.hidden = !show;
    if (!show) return;
    var label = $('iceShareLabel');
    if (label) {
      label.textContent = global.GlideShareSheet
        ? 'Поделиться подборкой'
        : state.cityName
          ? 'Поделиться расписанием — ' + state.cityName
          : 'Поделиться расписанием';
    }
    btn.setAttribute(
      'aria-label',
      state.cityName
        ? 'Поделиться расписанием катков: ' + state.cityName
        : 'Поделиться расписанием катков'
    );
  }

  function openIceShareDialog() {
    if (!state.cityId) return;
    /* TASK-146: делимся ровно тем, что на экране — город, тип места, окно времени —
       страницей подборки /c/{город}. Без шита (старые клиенты) — прежний «Лёд сегодня». */
    if (global.GlideShareSheet) {
      var q = ['city_id=' + encodeURIComponent(state.cityId)];
      if (state.venueTypes && state.venueTypes.length === 1) q.push('venue_type=' + encodeURIComponent(state.venueTypes[0]));
      var timeQ = whenQueryForApi();
      if (M.whenPickerVisible(state.intent, state.venueTypes, state.venueFacets)) {
        if (timeQ.day) q.push('day=' + encodeURIComponent(timeQ.day));
        else if (timeQ.when) q.push('when=' + encodeURIComponent(timeQ.when));
      }
      global.GlideShareSheet.open({ endpoint: '/api/public/ice/selection/share?' + q.join('&'), context: 'ice_list' });
      return;
    }
    var btn = $('iceShareBtn');
    if (btn) btn.disabled = true;
    fetchJson('/api/public/ice/share/' + encodeURIComponent(state.cityId) + '?share_context=ice_tab')
      .then(function (data) {
        if (!data) return;
        var shareUrl = String(data.share_url || '').trim();
        var shareBody = String(data.share_body || '').trim();
        var shareText = String(data.share_text || '').trim();
        if (!shareUrl && !shareText) return;
        if (typeof global.openTelegramShareUrlFromMiniApp === 'function') {
          global.openTelegramShareUrlFromMiniApp({
            shareUrl: shareUrl,
            shareBody: shareBody,
            fullMessage: shareText,
          });
          return;
        }
        var href = shareUrl
          ? 'https://t.me/share/url?url=' +
            encodeURIComponent(shareUrl) +
            (shareBody ? '&text=' + encodeURIComponent(shareBody) : '')
          : 'https://t.me/share/url?text=' + encodeURIComponent(shareText);
        global.location.href = href;
      })
      .catch(function () {})
      .then(function () {
        if (btn) btn.disabled = false;
      });
  }

  /**
   * TASK-096 AC-002. Turns a model-side `{title, body, action, secondary}` shape into a real
   * empty state with tappable exits. `kind` strings are resolved here because only the view
   * knows how to switch a chip or open the city sheet.
   */
  function emptyAction(kind) {
    if (kind === 'city') {
      return function () {
        openCityPicker(true);
      };
    }
    if (kind === 'clear-service') {
      return function () {
        state.serviceIds = [];
        renderServiceChips();
        persist();
        loadTrainers();
      };
    }
    if (kind === 'clear-search') {
      return function () {
        var input = $('iceSearchInput');
        if (input) input.value = '';
        showSearch('');
      };
    }
    if (kind === 'retry') {
      return function () {
        loadList();
      };
    }
    if (kind === 'ice-interest') {
      return function () {
        recordIceInterest();
      };
    }
    if (kind === 'clear-shop-filters') {
      return function () {
        clearShopFilters();
      };
    }
    if (kind && kind.indexOf('shop-service:') === 0) {
      var svc = kind.slice('shop-service:'.length);
      return function () {
        clearShopFilters({ shopService: svc });
      };
    }
    if (kind && kind.indexOf('intent:') === 0) {
      var next = kind.slice('intent:'.length);
      return function () {
        state.intent = M.coerceIntent(next);
        renderList();
        setChips();
        setViewToggle();
        persist();
        loadList();
      };
    }
    return null;
  }

  function renderEmpty(container, shape, iconName) {
    if (!container) return;
    var comp = global.MiniAppEmptyState;
    var action = shape && shape.action;
    var onCta = action ? emptyAction(action.kind) : null;
    if (!comp || !onCta) {
      // Degradation, not a designed state: the panel keeps the copy so the screen is never blank.
      container.innerHTML =
        '<div class="ice-empty"><b>' +
        esc(shape.title) +
        '</b><p>' +
        esc(shape.body || '') +
        '</p></div>';
      return;
    }
    var secondary = shape.secondary;
    var onSecondary = secondary ? emptyAction(secondary.kind) : null;
    comp.render(container, {
      icon: comp.ICONS[iconName || 'ice'],
      title: shape.title,
      hint: shape.body,
      ctaLabel: action.label,
      onCta: onCta,
      secondaryLabel: onSecondary ? secondary.label : null,
      onSecondary: onSecondary,
    });
  }

  function applyArenaPayload(data) {
    var incoming = (data && data.items) || [];
    var scope = M.catalogScope(state.intent, state.venueTypes);
    if (scope === 'shop') {
      state.shopSourceItems = incoming.slice();
      syncShopListFromFilters();
    } else {
      state.shopSourceItems = [];
      state.items = incoming.slice();
      state.total = data && data.total != null ? data.total : incoming.length;
    }
    state.cursor = data && data.next_cursor;
    state.venueFacets = (data && data.venue_type_facets) || [];
    state.window = (data && data.window) || null;
    renderCatalogHeader();
  }

  function renderWhenChips() {
    renderCatalogHeader();
  }

  /**
   * TASK-146: «Рядом». Было «Лёд рядом сейчас» — один каток со льдом сегодня. Но в поиске
   * не только лёд: зал, магазин заточки, роллеры. Поэтому кнопка не уводит на один каток,
   * а переставляет текущую ленту по расстоянию — с теми же типом места и окном времени.
   * Второй тап выключает. Город в шапке задаёт каталог; «Ближе» только сортирует
   * по GPS. Если геолокации нет — не зовём в выбор города, когда город уже выбран.
   */
  function setNearButton() {
    var btn = $('iceNearestBtn');
    if (!btn) return;
    btn.setAttribute('aria-pressed', state.nearOn ? 'true' : 'false');
    btn.setAttribute(
      'aria-label',
      state.nearOn
        ? 'Выключить сортировку по расстоянию'
        : 'Сначала ближайшие ко мне (нужна геолокация)'
    );
  }

  function showNearGeoBlocked(reason) {
    var message = M.formatNearGeoBlockedMessage({
      cityId: state.cityId,
      cityName: state.cityName,
      reason: reason,
    });
    var hasCity = !!(state.cityId);
    var tg = global.Telegram && global.Telegram.WebApp;

    if (hasCity) {
      if (tg && typeof tg.showAlert === 'function') {
        try {
          tg.showAlert(message);
          return;
        } catch (e) {
          /* fallback */
        }
      }
      if (tg && typeof tg.showPopup === 'function') {
        try {
          tg.showPopup({
            message: message,
            buttons: [{ id: 'close', type: 'close', text: 'Понятно' }],
          });
          return;
        } catch (e) {
          /* fallback */
        }
      }
      global.alert(message);
      return;
    }

    if (tg && typeof tg.showPopup === 'function') {
      try {
        tg.showPopup(
          {
            message: message,
            buttons: [
              { id: 'city', type: 'default', text: 'Выбрать город' },
              { id: 'close', type: 'cancel' },
            ],
          },
          function (id) {
            if (id === 'city') openCityPicker(true);
          }
        );
        return;
      } catch (e) {
        /* старый клиент Telegram без showPopup с кнопками — ниже обычный confirm */
      }
    }
    if (global.confirm(message + '\n\nОткрыть выбор города?')) openCityPicker(true);
  }

  function toggleNear() {
    var btn = $('iceNearestBtn');
    if (state.nearOn) {
      state.nearOn = false;
      setNearButton();
      renderList();
      return;
    }
    if (!(global.navigator && global.navigator.geolocation)) {
      showNearGeoBlocked('unsupported');
      return;
    }
    if (btn) btn.disabled = true;
    global.navigator.geolocation.getCurrentPosition(
      function (pos) {
        if (btn) btn.disabled = false;
        state.near = pos.coords.latitude.toFixed(5) + ',' + pos.coords.longitude.toFixed(5);
        state.nearOn = true;
        setNearButton();
        // Сервер считает distance_km только по near — перезапрашиваем ту же ленту с ним.
        loadArenas();
      },
      function () {
        if (btn) btn.disabled = false;
        showNearGeoBlocked('denied');
      },
      { timeout: 8000, maximumAge: 120000 }
    );
  }

  function applyTrainerPayload(data) {
    var incoming = (data && data.items) || [];
    state.items = incoming.slice();
    state.total = data && data.total != null ? data.total : incoming.length;
    state.cursor = data && data.next_cursor;
  }

  function fetchJson(url, opts) {
    opts = opts || {};
    var timeoutMs = opts.timeoutMs != null ? Number(opts.timeoutMs) : 20000;
    var headers = opts.auth ? authHeaders() : {};
    var run = function () {
      return fetch(url, {
        cache: 'no-store',
        headers: headers,
      }).then(function (r) {
        return r.ok ? r.json() : null;
      });
    };
    if (!(timeoutMs > 0)) return run();
    return new Promise(function (resolve, reject) {
      var done = false;
      var timer = global.setTimeout(function () {
        if (done) return;
        done = true;
        reject(new Error('fetch-timeout'));
      }, timeoutMs);
      run()
        .then(function (data) {
          if (done) return;
          done = true;
          global.clearTimeout(timer);
          resolve(data);
        })
        .catch(function (err) {
          if (done) return;
          done = true;
          global.clearTimeout(timer);
          reject(err);
        });
    });
  }

  function onListLoaded() {
    renderList();
    if (!mapCtl) return;
    if (state.intent === 'coach') {
      mapCtl.setListItems([]);
      if (state.view === 'map') mapCtl.start();
      return;
    }
    mapCtl.setListItems(state.items);
    if (state.view === 'map') mapCtl.refresh();
  }

  function loadFailed() {
    // TASK-096: «Попробуйте ещё раз» without a button is an instruction the screen doesn't honour.
    renderEmpty(
      listEl(),
      {
        title: 'Не удалось загрузить список',
        body: 'Похоже, пропала связь. Список загрузится заново по кнопке.',
        action: { label: 'Повторить', kind: 'retry' },
      },
      'retry'
    );
  }

  function beginListFetch(lens) {
    fetchGen += 1;
    var gen = fetchGen;
    state.loading = true;
    if (state.loadedIntent !== lens) {
      state.items = [];
      state.total = 0;
      state.loadedIntent = null;
    }
    renderList();
    return gen;
  }

  function isCurrentFetch(gen, lens) {
    if (gen !== fetchGen) return false;
    if (lens === 'coach') return state.intent === 'coach';
    return state.intent !== 'coach';
  }

  function loadArenas() {
    if (!state.cityId) {
      failCatalogBoot();
      return Promise.resolve();
    }
    if (!state.urlWhenHydrated) {
      var urlWhenBoot = M.hydrateWhenFromUrl(global.location.search || '', state.intent, state.venueTypes);
      if (urlWhenBoot) {
        state.when = urlWhenBoot.when;
        state.whenDay = urlWhenBoot.whenDay || '';
        state.urlWhenHydrated = true;
      }
    }
    var gen = beginListFetch('skate');
    var timeQ = whenQueryForApi();
    var url = M.buildListUrl({
      cityId: state.cityId,
      intent: state.intent,
      venueTypes: state.venueTypes,
      limit: 50,
      when: timeQ.when,
      whenDay: timeQ.whenDay,
      // Знаем, где человек, — ближние места выше (сервер считает distance_km).
      near: state.near || '',
    });
    return fetchJson(url)
      .then(function (data) {
        if (!isCurrentFetch(gen, 'skate')) return;
        state.loading = false;
        applyArenaPayload(data);
        state.loadedIntent = 'skate';
        if (state.intent === 'skate' && !state.items.length) {
          return maybeOpenTrainersWhenNoSkate();
        }
        onListLoaded();
      })
      .catch(function () {
        if (!isCurrentFetch(gen, 'skate')) return;
        state.loading = false;
        loadFailed();
      });
  }

  function loadTrainers() {
    if (!state.cityId) return Promise.resolve();
    var gen = beginListFetch('coach');
    var url = M.buildTrainersUrl({
      cityId: state.cityId,
      serviceIds: state.serviceIds,
      limit: 50,
    });
    return fetchJson(url)
      .then(function (data) {
        if (!isCurrentFetch(gen, 'coach')) return;
        state.loading = false;
        applyTrainerPayload(data);
        state.loadedIntent = 'coach';
        onListLoaded();
      })
      .catch(function () {
        if (!isCurrentFetch(gen, 'coach')) return;
        state.loading = false;
        loadFailed();
      });
  }

  function loadList() {
    if (state.intent === 'coach') {
      loadServices();
      return loadTrainers();
    }
    state.services = [];
    renderServiceChips();
    renderVenueChips();
    return loadArenas();
  }

  function renderServiceChips() {
    var box = $('iceServiceChips');
    if (!box) return;
    if (state.intent !== 'coach') {
      box.hidden = true;
      box.innerHTML = '';
      return;
    }
    /* TASK-148 (AC-1): чип рендерится только при данных. Услуги уже отфильтрованы
       по trainer_count > 0 (loadServices); пустой список = в городе нет тренеров,
       и лента «Все» из одного чипа — обещание без наполнения. */
    if (!state.services.length) {
      box.hidden = true;
      box.innerHTML = '';
      return;
    }
    box.hidden = false;
    var html =
      '<button type="button" class="ice-chip" data-service-id="" aria-pressed="' +
      (state.serviceIds.length ? 'false' : 'true') +
      '">Все</button>';
    (state.services || []).forEach(function (s) {
      var id = String(s.id);
      var pressed = state.serviceIds.indexOf(Number(id)) >= 0;
      html +=
        '<button type="button" class="ice-chip" data-service-id="' +
        esc(id) +
        '" aria-pressed="' +
        (pressed ? 'true' : 'false') +
        '">' +
        esc(M.serviceChipLabel(s.name)) +
        '</button>';
    });
    box.innerHTML = html;
  }

  /*
   * Чипы типа площадки: «Все / Лёд / Зал / …». Видны только когда в городе
   * реально больше одного типа — в чисто ледовом городе фильтр из одного
   * варианта это шум, а не выбор (venueChipsView вернёт пустой список).
   * Для чипа «Тренеры» скрыты: там в списке люди, а не площадки.
   */
  function renderVenueChips() {
    renderCatalogHeader();
  }

  function loadServices() {
    if (state.intent !== 'coach' || !state.cityId) {
      state.services = [];
      renderServiceChips();
      return Promise.resolve();
    }
    return fetchJson(M.buildServicesUrl({ cityId: state.cityId }))
      .then(function (data) {
        var items = (data && data.items) || [];
        state.services = items.filter(function (s) {
          return Number(s.trainer_count) > 0;
        });
        if (state.serviceIds.length) {
          var present = state.services.map(function (s) {
            return Number(s.id);
          });
          var kept = state.serviceIds.filter(function (id) {
            return present.indexOf(id) >= 0;
          });
          if (kept.length !== state.serviceIds.length) {
            state.serviceIds = kept;
            persist();
            loadTrainers();
          }
        }
        renderServiceChips();
      })
      .catch(function () {
        state.services = [];
        renderServiceChips();
      });
  }

  function cityFromState(id) {
    return (
      state.cities.filter(function (c) {
        return Number(c.id) === Number(id);
      })[0] || null
    );
  }

  function switchToCoach() {
    state.intent = 'coach';
    state.view = 'list';
    renderList();
    setChips();
    setViewToggle();
    persist();
    return loadTrainers();
  }

  function maybeOpenTrainersWhenNoSkate() {
    var city = cityFromState(state.cityId);
    if (city && (Number(city.trainer_count) || 0) > 0) {
      return switchToCoach();
    }
    if (city && city.trainer_count != null) {
      onListLoaded();
      return Promise.resolve();
    }
    return fetchJson(M.buildTrainersUrl({ cityId: state.cityId, limit: 1 })).then(function (data) {
      var n = data && (data.total != null ? data.total : ((data.items || []).length));
      if (n > 0) return switchToCoach();
      onListLoaded();
    });
  }

  function failCatalogBoot() {
    state.loading = false;
    state.loadedIntent = null;
    renderList();
    loadFailed();
  }

  function ensureProvisionalCity() {
    if (state.cityId) return;
    var fb = M.pickFallbackCity(state.cities);
    if (fb) applyCity(fb);
  }

  function applyCityIfDifferent(city) {
    if (!city || city.id == null) return;
    if (state.cityId != null && Number(city.id) === Number(state.cityId)) return;
    applyCity(city);
  }

  function applyCity(city) {
    if (!city) {
      failCatalogBoot();
      return;
    }
    var known = cityFromState(city.id);
    if (known) {
      city = Object.assign({}, known, { name: city.name || known.name, id: known.id });
    }
    var prevCityId = state.cityId != null && state.cityId !== '' ? Number(state.cityId) : null;
    var nextCityId = Number(city.id);
    var cityChanged = prevCityId !== null && prevCityId !== nextCityId;

    state.cityId = city.id;
    state.cityName = city.name || '';
    state.skateCount = city.skate_count;

    if (cityChanged) {
      var cityCatalog = M.catalogStateAfterCityChange(city, state);
      state.intent = cityCatalog.intent;
      state.venueTypes = cityCatalog.venueTypes.slice();
      state.shopService = cityCatalog.shopService;
      state.shopDiscipline = cityCatalog.shopDiscipline;
      state.shopOpenNow = cityCatalog.shopOpenNow;
      state.shopWhen = cityCatalog.shopWhen;
      state.shopSourceItems = [];
      state.items = [];
      state.total = 0;
      state.venueFacets = [];
      state.shopUiPicker = false;
      closeShopMapFiltersPanel();
    } else {
      /* Тот же город (или первый applyCity после boot): не сбрасываем вкладку «Магазины». */
      var nextIntent =
        state.venueTypes && state.venueTypes.length
          ? state.intent
          : M.pickCityIntent(city, state.intent);
      if (nextIntent !== state.intent) state.intent = nextIntent;
    }
    if (state.intent === 'coach') state.view = 'list';
    setCityLabel();
    setChips();
    setViewToggle();
    persist();
    if (mapCtl && typeof mapCtl.leaveCity === 'function') mapCtl.leaveCity();
    var token = initData();
    if (token && city.id) {
      fetch('/api/webapp/client/session/catalog-filters', {
        method: 'PATCH',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
        body: JSON.stringify({ city_id: city.id }),
      }).catch(function () {});
    }
    loadList();
  }

  function onCityPick(ev) {
    var item = ev.target.closest('[data-city-id]');
    if (!item) return;
    var id = Number(item.getAttribute('data-city-id'));
    var city = state.cities.filter(function (c) {
      return Number(c.id) === id;
    })[0];
    openCityPicker(false);
    applyCity(city || { id: id, name: item.getAttribute('data-city-name') || '' });
  }

  function renderCityPicker(filter) {
    var box = $('iceCityList');
    var popularBox = $('iceCityPopular');
    var popularLabel = $('iceCityPopularLabel');
    if (!box) return;
    var q = String(filter || '').trim().toLowerCase();
    if (!q) {
      var popular = M.rankPopularCities(state.cities, 8);
      if (popularBox) {
        popularBox.innerHTML = popular
          .map(function (c) {
            return (
              '<button type="button" class="ice-picker__popular-item" data-city-id="' +
              esc(c.id) +
              '" data-city-name="' +
              esc(c.name) +
              '">' +
              esc(c.name) +
              '</button>'
            );
          })
          .join('');
      }
      if (popularLabel) popularLabel.hidden = popular.length === 0;
    } else {
      if (popularBox) popularBox.innerHTML = '';
      if (popularLabel) popularLabel.hidden = true;
    }
    var rows = state.cities.filter(function (c) {
      return !q || String(c.name || '').toLowerCase().indexOf(q) >= 0;
    });
    var byKey = {};
    var groups = [];
    rows.forEach(function (c) {
      var key = String(c.country || 'BY').toUpperCase();
      if (!byKey[key]) {
        byKey[key] = [];
        groups.push(key);
      }
      byKey[key].push(c);
    });
    var rank = { BY: 0, RU: 1 };
    groups.sort(function (a, b) {
      var oa = rank[a] != null ? rank[a] : 9;
      var ob = rank[b] != null ? rank[b] : 9;
      if (oa !== ob) return oa - ob;
      return a < b ? -1 : a > b ? 1 : 0;
    });
    box.innerHTML = groups
      .map(function (key) {
        var label = M.cityCountryLabel(key) || key;
        var items = byKey[key]
          .map(function (c) {
            var selected = Number(c.id) === Number(state.cityId);
            return (
              '<button type="button" class="ice-picker__item' +
              (selected ? ' ice-picker__item--current' : '') +
              '" data-city-id="' +
              esc(c.id) +
              '" data-city-name="' +
              esc(c.name) +
              '"' +
              (selected ? ' aria-current="true"' : '') +
              '>' +
              '<span class="ice-picker__city">' +
              esc(c.name) +
              '</span>' +
              '</button>'
            );
          })
          .join('');
        return '<p class="ice-picker__label">' + esc(label) + '</p>' + items;
      })
      .join('');
  }

  function openCityPicker(open) {
    var picker = $('iceCityPicker');
    var back = $('btnBack');
    if (!picker) return;
    picker.hidden = !open;
    if (back) back.hidden = !open;
    if (open) renderCityPicker($('iceCityFilter') && $('iceCityFilter').value);
  }

  function resolveCity() {
    return fetchJson(M.buildIceCitiesUrl())
      .then(function (data) {
        state.cities = M.filterIceCities((data && data.items) || []);
        var urlCityId = M.cityIdFromSearch(global.location.search || '');
        if (urlCityId) {
          var fromUrl = state.cities.filter(function (c) {
            return Number(c.id) === urlCityId;
          })[0];
          if (fromUrl) {
            applyCity(fromUrl);
            return;
          }
        }
        var saved = M.loadIceState(global.sessionStorage);
        if (saved && saved.cityId) {
          var fromSaved = state.cities.filter(function (c) {
            return Number(c.id) === Number(saved.cityId);
          })[0];
          if (fromSaved) {
            applyCity(fromSaved);
            return;
          }
        }
        /* Не блокируем ленту сессией/GPS: сразу дефолтный город, потом уточняем. */
        ensureProvisionalCity();
        return fetchJson('/api/webapp/client/session', { auth: true, timeoutMs: 8000 })
          .then(function (session) {
            var sid = session && session.city_id;
            var fromSession = sid
              ? state.cities.filter(function (c) {
                  return Number(c.id) === Number(sid);
                })[0]
              : null;
            if (fromSession) {
              if (session.city_name) {
                fromSession = Object.assign({}, fromSession, { name: session.city_name });
              }
              applyCityIfDifferent(fromSession);
              return;
            }
            return geolocateOrFallback(session);
          })
          .catch(function () {
            return geolocateOrFallback(null);
          });
      })
      .catch(function () {
        /* cities не загрузились — всё равно пробуем фолбэк, иначе вечное «ищем катки…». */
        if (!state.cities.length) state.cities = [];
        applyCity(M.pickFallbackCity(state.cities));
      })
      .then(function () {
        if (state.cityId) return;
        var fb = M.pickFallbackCity(state.cities);
        if (fb) applyCity(fb);
        else failCatalogBoot();
      });
  }

  /**
   * TASK-146: холодный вход (маркетинговая ссылка, первый запуск) — города нет ни в ссылке,
   * ни в сохранённом, ни в профиле. Спрашиваем геолокацию один раз и берём ближайший город
   * (CatalogGeoModel: не дальше 150 км — дальний «ближайший» не совпадение). Отказ или
   * нет совпадения — прежний фолбэк, и больше не спрашиваем.
   */
  function geolocateOrFallback(session) {
    var G = global.CatalogGeoModel;
    var fallbackCity = M.pickFallbackCity(state.cities);
    var fallback = function () {
      if (!state.cityId) applyCity(fallbackCity);
    };
    var go =
      G &&
      G.shouldAutoGeolocate({
        cityId: null,
        hasExplicitQueryCityId: !!M.cityIdFromSearch(global.location.search || ''),
        hasCollectiveContext: false,
        hasDeepLinkTrainer: false,
        hasPrimaryTrainer: false,
        geolocationSupported: !!(global.navigator && global.navigator.geolocation),
        previouslyDeclined: G.readDeclinedFlag(global.localStorage),
        ipSaysUnserved: !!(session && session.ip_country_served === false),
      });
    if (!go) {
      fallback();
      return;
    }
    /* Не ждём GPS, чтобы отрисовать каталог: сначала дефолтный город, потом уточняем. */
    if (fallbackCity && !state.cityId) applyCity(fallbackCity);
    return new Promise(function (resolve) {
      var settled = false;
      function finish() {
        if (settled) return;
        settled = true;
        resolve();
      }
      global.setTimeout(function () {
        fallback();
        finish();
      }, 9000);
      global.navigator.geolocation.getCurrentPosition(
        function (pos) {
          state.near = pos.coords.latitude.toFixed(5) + ',' + pos.coords.longitude.toFixed(5);
          fetchJson(G.buildNearUrl(pos.coords.latitude, pos.coords.longitude))
            .then(function (data) {
              var cityId = G.pickCityFromNearResponse(data);
              var city = cityId
                ? state.cities.filter(function (c) { return Number(c.id) === cityId; })[0]
                : null;
              if (city && Number(city.id) !== Number(state.cityId)) applyCity(city);
              else fallback();
            })
            .catch(fallback)
            .then(finish);
        },
        function () {
          G.writeDeclinedFlag(global.localStorage);
          fallback();
          finish();
        },
        { timeout: 8000, maximumAge: 300000 }
      );
    });
  }

  function showSearch(q) {
    var searchSec = $('iceSearchSec');
    var listSec = $('iceListSec');
    var mapSec = $('iceMapSec');
    var query = String(q || '').trim();
    if (query.length < 2) {
      if (searchSec) searchSec.hidden = true;
      if (listSec) listSec.hidden = mapViewActive();
      if (mapSec) mapSec.hidden = !mapViewActive();
      if (document.body) document.body.classList.toggle('ice-view-map', mapViewActive());
      if (mapViewActive() && mapCtl) mapCtl.resize();
      return;
    }
    fetchJson(M.buildSearchUrl(query, 8)).then(function (data) {
      var grouped = M.groupSearchResults(data || { groups: [] });
      var box = $('iceSearchResults');
      if (!box) return;
      if (searchSec) searchSec.hidden = false;
      if (listSec) listSec.hidden = true;
      if (mapSec) mapSec.hidden = true;
      if (document.body) document.body.classList.remove('ice-view-map');
      var html = '';
      grouped.forEach(function (g) {
        if (!g.items.length) return;
        html += '<p class="ice-results__label">' + esc(g.label) + '</p>';
        g.items.forEach(function (it) {
          var href = '';
          var title = it.name || '';
          var sub = '';
          if (g.type === 'arena') {
            href = M.arenaHref(it);
            // Тип места, кроме льда: в выдаче по «заточке» мастерская не должна выглядеть катком.
            var chip = it.venue_type && it.venue_type !== 'ice' ? it.venue_chip : '';
            sub = [chip, it.district, it.city_name, it.address].filter(Boolean).join(' · ');
          } else if (g.type === 'trainer') {
            href = M.trainerHref(it);
            title = it.name || [it.first_name, it.last_name].filter(Boolean).join(' ');
          } else if (g.type === 'city') {
            href = 'city:' + it.id;
            title = it.name;
          }
          html +=
            '<button type="button" class="ice-hit" data-href="' +
            esc(href) +
            '" data-city-id="' +
            esc(it.id) +
            '" data-city-name="' +
            esc(it.name || '') +
            '"><b>' +
            esc(title) +
            '</b><span>' +
            esc(sub) +
            '</span></button>';
        });
      });
      if (html) {
        box.innerHTML = html;
        return;
      }
      // TASK-096 AC-002: «Ничего не найдено» was the one state in the app with no exit at all.
      renderEmpty(box, M.formatEmptySearch(query), 'search');
    });
  }

  function catalogTodayIso() {
    var ACM = global.ArenaCardModel;
    if (ACM && typeof ACM.ymd === 'function') return ACM.ymd(new Date());
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function catalogAddDaysIso(iso, n) {
    var ACM = global.ArenaCardModel;
    if (ACM && typeof ACM.parseLocalDate === 'function' && typeof ACM.ymd === 'function') {
      var d = ACM.parseLocalDate(iso);
      d.setDate(d.getDate() + n);
      return ACM.ymd(d);
    }
    return iso;
  }

  function openCatalogInvite(ref, sessionId, label) {
    if (!global.GlideShareSheet || !ref) return;
    var fallback = function () {
      global.GlideShareSheet.open({
        ref: ref,
        sessionId: sessionId,
        slots: sessionId ? [{ id: sessionId, label: label || '' }] : [],
        invite: true,
        context: 'ice_list',
      });
    };
    var ACM = global.ArenaCardModel;
    if (!ACM || typeof ACM.shareSlots !== 'function') {
      fallback();
      return;
    }
    var today = catalogTodayIso();
    var to = catalogAddDaysIso(today, 13);
    fetchJson('/api/public/arenas/' + encodeURIComponent(String(ref)) + '/sessions?from=' + encodeURIComponent(today) + '&to=' + encodeURIComponent(to))
      .then(function (data) {
        var days = (data && data.days) || [];
        var slots = ACM.shareSlots(days, today, 0);
        var slotSections = ACM.shareSlotsGrouped ? ACM.shareSlotsGrouped(days, today) : null;
        var sid = sessionId;
        if (sid && !slots.some(function (s) { return String(s.id) === String(sid); })) {
          slots.unshift({ id: sessionId, label: label || '' });
        }
        if (!sid && slots.length) sid = slots[0].id;
        global.GlideShareSheet.open({
          ref: ref,
          sessionId: sid,
          slots: slots,
          slotSections: slotSections,
          invite: true,
          context: 'ice_list',
        });
      })
      .catch(fallback);
  }

  function onRootClick(ev) {
    var invite = ev.target.closest('[data-invite-arena]');
    if (invite && global.GlideShareSheet) {
      ev.preventDefault();
      openCatalogInvite(
        invite.getAttribute('data-invite-arena'),
        invite.getAttribute('data-invite-session'),
        invite.getAttribute('data-invite-label')
      );
      return;
    }
    var card = ev.target.closest('[data-href]');
    if (!card) return;
    var href = card.getAttribute('data-href') || card.getAttribute('href') || '';
    if (card.tagName === 'A') ev.preventDefault();
    if (href.indexOf('city:') === 0) {
      applyCity({
        id: Number(card.getAttribute('data-city-id')),
        name: card.getAttribute('data-city-name') || '',
      });
      var input = $('iceSearchInput');
      if (input) input.value = '';
      showSearch('');
      return;
    }
    if (href) {
      markHeroForTransition(card);
      var m = /[?&]ref=([^&]+)/.exec(href);
      var ref = m ? decodeURIComponent(m[1]) : '';
      var item = ref
        ? state.items.filter(function (it) {
            return String(it.id) === ref || String(it.slug || '') === ref;
          })[0]
        : null;
      rememberArenaHero(item);
      shellNav(href);
    }
  }

  /*
   * TASK-094 AC-003. Кадр тапнутой карточки получает имя перехода — и только он:
   * в списке таких элементов пять, а view-transition-name обязано быть
   * уникальным в документе, иначе браузер отменит переход целиком.
   * Снимок уходящей страницы делается в pageswap, то есть уже после этой
   * пометки, — успеваем.
   */
  function markHeroForTransition(card) {
    var prev = document.querySelectorAll('[data-vt-hero]');
    var i;
    for (i = 0; i < prev.length; i++) prev[i].removeAttribute('data-vt-hero');
    if (!card || typeof card.querySelector !== 'function') return;
    var photo = card.querySelector('.ice-board__photo');
    if (photo) photo.setAttribute('data-vt-hero', '1');
  }

  function bind() {
    var modeSeg = $('iceModeSeg');
    if (modeSeg) {
      modeSeg.addEventListener('click', function (ev) {
        var btn = ev.target.closest('[data-catalog-mode]');
        if (!btn) return;
        var mode = btn.getAttribute('data-catalog-mode') || 'places';
        var patch = M.applyCatalogMode(mode);
        state.intent = M.coerceIntent(patch.intent);
        state.venueTypes = patch.venueTypes.slice();
        closeUiPicker();
        if (mode === 'coach') state.view = 'list';
        renderList();
        setChips();
        setViewToggle();
        persist();
        loadList();
      });
    }

    var placeTabs = $('icePlaceTabs');
    if (placeTabs) {
      placeTabs.addEventListener('click', function (ev) {
        var tab = ev.target.closest('[data-place-type]');
        if (!tab) return;
        var key = tab.getAttribute('data-place-type') || '';
        state.venueTypes = key ? [key] : [];
        closeUiPicker();
        if (mapCtl && mapViewActive()) mapCtl.refresh();
        renderCatalogHeader();
        loadArenas();
      });
    }

    var mapFiltersBtn = $('iceShopMapFiltersBtn');
    if (mapFiltersBtn) {
      mapFiltersBtn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        state.shopMapFiltersOpen = !state.shopMapFiltersOpen;
        renderCatalogHeader();
      });
    }

    var shopFilters = $('iceShopFilters');
    if (shopFilters && shopFilters.dataset.clickWired !== '1') {
      shopFilters.dataset.clickWired = '1';
      shopFilters.addEventListener('click', onShopFiltersClick);
    }

    var toolsHost = $('iceCatalogTools');
    if (toolsHost) {
      toolsHost.addEventListener('click', function (ev) {
        var pickerBtn = ev.target.closest('[data-ui-picker]');
        if (pickerBtn) {
          var which = pickerBtn.getAttribute('data-ui-picker') || '';
          state.uiPicker = state.uiPicker === which ? false : which;
          renderCatalogHeader();
          return;
        }
        var placeBtn = ev.target.closest('[data-place-type]');
        if (placeBtn && placeBtn.closest('#icePlaceMenu')) {
          var pkey = placeBtn.getAttribute('data-place-type') || '';
          state.venueTypes = pkey ? [pkey] : [];
          closeUiPicker();
          if (mapCtl && mapViewActive()) mapCtl.refresh();
          renderCatalogHeader();
          loadArenas();
          return;
        }
        var whenToggle = ev.target.closest('[data-when-toggle]');
        if (whenToggle && whenToggle.closest('#iceWhenMenu')) {
          state.whenMenuExpanded = !state.whenMenuExpanded;
          renderCatalogHeader();
          return;
        }
        var whenPreset = ev.target.closest('[data-when-preset]');
        if (whenPreset && whenPreset.closest('#iceWhenMenu')) {
          var pick = M.applyWhenMenuPick(state.when, state.whenDay, {
            kind: 'preset',
            id: whenPreset.getAttribute('data-when-preset') || 'any',
          });
          state.when = pick.when;
          state.whenDay = pick.whenDay;
          closeUiPicker();
          renderCatalogHeader();
          persist();
          loadArenas();
          return;
        }
        var whenDayBtn = ev.target.closest('[data-when-day]');
        if (whenDayBtn && whenDayBtn.closest('#iceWhenMenu')) {
          var dayPick = M.applyWhenMenuPick(state.when, state.whenDay, {
            kind: 'day',
            date: whenDayBtn.getAttribute('data-when-day') || '',
          });
          state.when = dayPick.when;
          state.whenDay = dayPick.whenDay;
          closeUiPicker();
          renderCatalogHeader();
          persist();
          loadArenas();
        }
      });
    }

    var svcBox = $('iceServiceChips');
    if (svcBox) {
      svcBox.addEventListener('click', function (ev) {
        var chip = ev.target.closest('[data-service-id]');
        if (!chip) return;
        var raw = chip.getAttribute('data-service-id');
        var id = raw ? Number(raw) : null;
        if (id == null || isNaN(id)) {
          state.serviceIds = [];
        } else {
          /* Тоггл: повторный тап снимает услугу, пустой набор = «Все». */
          var at = state.serviceIds.indexOf(id);
          if (at >= 0) state.serviceIds.splice(at, 1);
          else state.serviceIds.push(id);
        }
        renderServiceChips();
        persist();
        loadTrainers();
      });
    }

    var nearestBtn = $('iceNearestBtn');
    if (nearestBtn) nearestBtn.addEventListener('click', toggleNear);

    var viewSwitch = $('iceViewSwitch');
    if (viewSwitch) {
      viewSwitch.addEventListener('click', function () {
        setView(mapViewActive() ? 'list' : 'map');
      });
    }

    var shareBtn = $('iceShareBtn');
    if (shareBtn) {
      shareBtn.addEventListener('click', openIceShareDialog);
    }

    var search = $('iceSearchInput');
    if (search) {
      search.addEventListener('input', function () {
        global.clearTimeout(searchTimer);
        var q = search.value;
        searchTimer = global.setTimeout(function () {
          showSearch(q);
        }, 220);
      });
    }

    var list = $('iceList');
    if (list) list.addEventListener('click', onRootClick);
    var results = $('iceSearchResults');
    if (results) results.addEventListener('click', onRootClick);

    var change = $('iceCityChange');
    if (change) change.addEventListener('click', function () {
      openCityPicker(true);
    });

    /* TASK-147: дубль пилюли города внутри строки поиска (режим карты). */
    var changeMap = $('iceCityChangeMap');
    if (changeMap) changeMap.addEventListener('click', function () {
      openCityPicker(true);
    });

    var pickerClose = $('iceCityPickerClose');
    if (pickerClose) {
      pickerClose.addEventListener('click', function () {
        openCityPicker(false);
      });
    }

    var back = $('btnBack');
    if (back) {
      back.addEventListener('click', function () {
        openCityPicker(false);
      });
    }

    var home = $('btnHome');
    if (home) {
      home.addEventListener('click', function () {
        shellNav('client-home');
      });
    }

    var cityFilter = $('iceCityFilter');
    if (cityFilter) {
      cityFilter.addEventListener('input', function () {
        renderCityPicker(cityFilter.value);
      });
    }

    var cityList = $('iceCityList');
    if (cityList) {
      cityList.addEventListener('click', onCityPick);
    }
    var cityPopular = $('iceCityPopular');
    if (cityPopular) {
      cityPopular.addEventListener('click', onCityPick);
    }

    var geo = $('iceGeoBtn');
    if (geo) {
      geo.addEventListener('click', function () {
        if (!navigator.geolocation) {
          applyCity(M.pickFallbackCity(state.cities));
          openCityPicker(false);
          return;
        }
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            var near = pos.coords.latitude + ',' + pos.coords.longitude;
            fetchJson(M.buildListUrl({ near: near, intent: 'coach', limit: 1 })).then(function (data) {
              var first = data && data.items && data.items[0];
              if (first && first.city_id) {
                var city = state.cities.filter(function (c) {
                  return Number(c.id) === Number(first.city_id);
                })[0];
                applyCity(city || { id: first.city_id, name: state.cityName });
              } else {
                applyCity(M.pickFallbackCity(state.cities));
              }
              openCityPicker(false);
            });
          },
          function () {
            applyCity(M.pickFallbackCity(state.cities));
            openCityPicker(false);
          },
          { timeout: 6000, maximumAge: 60000 }
        );
      });
    }

    global.addEventListener('pagehide', persist);
    global.addEventListener('pageshow', function (ev) {
      repairCatalogChrome();
      if (!ev.persisted) return;
      var saved = M.loadIceState(global.sessionStorage);
      if (saved && saved.scrollY) global.scrollTo(0, saved.scrollY);
    });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') repairCatalogChrome();
    });
  }

  function boot() {
    bind();
    var saved = M.loadIceState(global.sessionStorage);
    if (saved && saved.intent) state.intent = M.coerceIntent(saved.intent);
    if (saved && saved.serviceIds && saved.serviceIds.length) {
      state.serviceIds = saved.serviceIds.map(Number).filter(function (n) { return n > 0; });
    } else if (saved && saved.serviceId) {
      state.serviceIds = Number(saved.serviceId) > 0 ? [Number(saved.serviceId)] : [];
    }
    /*
     * TASK-103 AC-001: список — всегда стартовое состояние.
     *
     * Здесь сознательно НЕ восстанавливается ни saved.view, ни ?view=map. Это и есть
     * замена флагу MAP_ENABLED: раньше два предохранителя гасили случай «экран
     * открылся картой без способа вернуться», теперь этого случая не существует.
     * Требование владельца 2026-09-09 звучит так же: клиент сначала попадает на список.
     *
     * state.view всё ещё пишется в sessionStorage — им пользуется восстановление
     * скролла на pageshow; читать его как стартовый вид просто некому.
     */
    state.view = 'list';
    try {
      var params = new URLSearchParams(global.location.search || '');
      var urlIntent = M.intentFromSearch(global.location.search || '');
      if (urlIntent) state.intent = M.coerceIntent(urlIntent);
      var urlVenue = M.venueFromSearch(global.location.search || '');
      if (urlVenue) {
        state.intent = 'skate';
        state.venueTypes = [urlVenue];
      } else if (
        saved &&
        saved.venueTypes &&
        saved.venueTypes.length &&
        M.coerceIntent(state.intent) === M.INTENTS.skate
      ) {
        state.venueTypes = saved.venueTypes.slice();
      }
      /* TASK-149: ?when=<окно> из ссылки (хаб «Сегодня вечером»). Читаем ПОСЛЕ intent и
         venue: именно они решают, видны ли чипы окна. У «Тренеров» и у не-ледовых типов
         окна нет — параметр молча игнорируем. Без ?when=/ ?day= восстанавливаем окно из
         sessionStorage (возврат с карточки арены); ссылка сильнее сохранённого. */
      var urlWhenBoot = M.hydrateWhenFromUrl(global.location.search || '', state.intent, state.venueTypes);
      if (urlWhenBoot) {
        state.when = urlWhenBoot.when;
        state.whenDay = urlWhenBoot.whenDay || '';
        state.urlWhenHydrated = true;
      } else if (saved) {
        var savedWhenBoot = M.hydrateWhenFromSaved(saved, state.intent, state.venueTypes);
        if (savedWhenBoot) {
          state.when = savedWhenBoot.when;
          state.whenDay = savedWhenBoot.whenDay || '';
        }
      }
      if (saved) {
        if (saved.shopService) state.shopService = String(saved.shopService);
        if (saved.shopDiscipline) state.shopDiscipline = String(saved.shopDiscipline);
        state.shopOpenNow = !!saved.shopOpenNow;
        if (saved.shopWhen) state.shopWhen = String(saved.shopWhen);
      }
      // TASK-091: строка поиска на Главной ведёт сюда и сразу открывает клавиатуру.
      if (params.get('focus') === 'search') {
        global.setTimeout(function () {
          var input = $('iceSearchInput');
          if (input && typeof input.focus === 'function') input.focus();
        }, 0);
      }
    } catch (e) { /* */ }
    repairCatalogChrome();
    /*
     * TASK-095: скелетон рисуется первым же кадром, не дожидаясь резолва города.
     * Иначе между появлением экрана и первым запросом список — пустое место, и
     * на переходе с Главной (TASK-094) въезжает наполовину собранная страница.
     */
    state.loading = true;
    renderList();
    global.setTimeout(function () {
      if (!state.cityId) {
        ensureProvisionalCity();
        if (!state.cityId && state.loading) failCatalogBoot();
      } else if (state.loading && state.loadedIntent === null) {
        loadList();
      }
    }, 3500);
    resolveCity().then(function () {
      if (!state.cityId) {
        var fb = M.pickFallbackCity(state.cities);
        if (fb) applyCity(fb);
        else failCatalogBoot();
      } else if (state.loading && state.loadedIntent === null) {
        loadList();
      }
      if (saved && saved.scrollY) {
        global.setTimeout(function () {
          global.scrollTo(0, saved.scrollY);
        }, 0);
      }
      if (global.ClientShell && global.ClientShell.reportCatalogPresence && state.cityId) {
        global.ClientShell.reportCatalogPresence('miniapp_ice', null, { city_id: state.cityId });
      }
    });
  }

  function showBootDependencyError() {
    var cap = $('iceCaption');
    if (cap) cap.textContent = 'Каталог не запустился';
    var list = $('iceListSkate');
    if (list) {
      list.innerHTML =
        '<div class="ice-empty"><b>Не загрузились скрипты каталога</b><p>Закройте вкладку «Поиск» и откройте снова. Если не помогло — обновите мини-приложение.</p></div>';
    }
  }

  if (!M) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', showBootDependencyError);
    } else {
      showBootDependencyError();
    }
    return;
  }

  global.IceCatalog = { onTabRetap: onCatalogTabRetap };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(typeof window !== 'undefined' ? window : this);
