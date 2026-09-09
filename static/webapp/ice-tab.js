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
    serviceId: null,
    services: [],
    cities: [],
    items: [],
    total: 0,
    cursor: null,
    loading: false,
  };
  var searchTimer = null;

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

  function persist() {
    M.saveIceState(
      {
        intent: state.intent,
        cityId: state.cityId,
        cityName: state.cityName,
        serviceId: state.serviceId,
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

  function setCityLabel() {
    var el = $('iceCityName');
    if (el) el.textContent = state.cityName || 'Город';
  }

  function currentServiceLabel() {
    if (!state.serviceId) return '';
    var found = (state.services || []).filter(function (s) {
      return Number(s.id) === Number(state.serviceId);
    })[0];
    return found ? M.serviceChipLabel(found.name) : '';
  }

  function setChips() {
    document.querySelectorAll('#iceIntentChips .ice-chip').forEach(function (btn) {
      btn.setAttribute('aria-pressed', btn.getAttribute('data-intent') === state.intent ? 'true' : 'false');
    });
    renderServiceChips();
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

  function setViewToggle() {
    var allowed = mapAllowed();
    var showMapView = mapViewActive();

    var sw = $('iceViewSwitch');
    if (sw) {
      sw.hidden = !allowed;
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
    if (showMapView) {
      showMap();
      if (mapSec && typeof mapSec.scrollIntoView === 'function') {
        mapSec.scrollIntoView({ block: 'start' });
      }
    }
  }

  function setView(next) {
    var wanted = next === 'map' && mapAllowed() ? 'map' : 'list';
    if (state.view === wanted) return;
    state.view = wanted;
    setViewToggle();
    persist();
    if (wanted === 'list') {
      // Возврат в список — наверх: иначе после карты полотно открывается с середины.
      global.scrollTo({ top: 0, behavior: 'auto' });
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
        listUrl: function (extra) {
          extra = extra || {};
          var opts = {
            intent: extra.intent || state.intent,
            limit: extra.limit || 50,
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
        getCityId: function () {
          return state.cityId;
        },
        listReady: function () {
          return !state.loading && !!state.cityId;
        },
        arenaHref: M.arenaHref,
        onOpenArena: function (item, href) {
          if (href) shellNav(href);
        },
        onNearList: function (data) {
          if (state.intent === 'coach') return;
          applyArenaPayload(data);
          renderList();
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
    var v = M.boardCardView(item);
    var photo = v.photo
      ? '<span class="ice-board__photo"' + acardThumbStyle(v.photo) + '>'
      : '<span class="ice-board__photo ice-board__photo--empty">' +
        '<span class="ice-board__initial" aria-hidden="true">' +
        esc(v.initial) +
        '</span>';
    var scrim =
      '<span class="ice-board__scrim">' +
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
    return (
      '<a class="ice-board" href="' +
      esc(v.href) +
      '" data-href="' +
      esc(v.href) +
      '">' +
      photo +
      scrim +
      '</span>' +
      (facts ? '<span class="ice-board__facts">' + facts + '</span>' : '') +
      '<span class="ice-board__depth">' +
      esc(v.depth) +
      '<span class="ice-board__go" aria-hidden="true">→</span>' +
      '</span>' +
      '</a>'
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

  function renderList() {
    var list = $('iceList');
    var cap = $('iceCaption');
    if (cap) {
      cap.textContent = M.formatSortCaption({
        total: state.total,
        items: state.items,
        intent: state.intent,
        serviceLabel: currentServiceLabel(),
        loading: state.loading,
      });
    }
    setShareButton();
    if (!list) return;
    if (state.loading && !state.items.length) {
      // TASK-095: вместо строки «Загрузка катков…» — коробки будущих карточек.
      // Текстовая строка обещала одну форму, а приходила совсем другая.
      list.innerHTML = state.intent === 'coach' ? trainerSkeletons(3) : boardSkeletons(2);
      return;
    }
    if (!state.items.length) {
      var empty = M.formatEmptyList(state.intent, {
        serviceName: state.intent === 'coach' && state.serviceId ? currentServiceLabel() : '',
      });
      renderEmpty(list, empty, state.intent === 'coach' ? 'ice' : 'city');
      return;
    }
    list.innerHTML = state.items
      .map(function (item) {
        return state.intent === 'coach' ? renderTrainerCard(item) : renderArenaCard(item);
      })
      .join('');
  }

  /**
   * TASK-096 (G-P5). Кнопка видна только там, где есть что переслать: город выбран,
   * намерение «покататься», список не пуст и не грузится. Артефакт — расписание
   * массовых катаний города; для «тренеров» его не существует, а шеринг тренера уже
   * живёт в четырёх других точках.
   */
  function shareAvailable() {
    return !!(
      state.cityId &&
      state.intent === 'skate' &&
      !state.loading &&
      state.items.length
    );
  }

  function setShareButton() {
    var btn = $('iceShareBtn');
    if (!btn) return;
    var show = shareAvailable();
    btn.hidden = !show;
    if (!show) return;
    var label = $('iceShareLabel');
    if (label) {
      label.textContent = state.cityName
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
        state.serviceId = null;
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
    if (kind && kind.indexOf('intent:') === 0) {
      var next = kind.slice('intent:'.length);
      return function () {
        state.intent = M.coerceIntent(next);
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
    state.items = M.filterSkateLens(incoming, state.intent);
    state.total = data && data.total != null ? data.total : incoming.length;
    if (state.items.length < incoming.length) state.total = state.items.length;
    state.cursor = data && data.next_cursor;
  }

  function applyTrainerPayload(data) {
    var incoming = (data && data.items) || [];
    state.items = incoming.slice();
    state.total = data && data.total != null ? data.total : incoming.length;
    state.cursor = data && data.next_cursor;
  }

  function fetchJson(url, opts) {
    opts = opts || {};
    return fetch(url, {
      cache: 'no-store',
      headers: opts.auth ? authHeaders() : {},
    }).then(function (r) {
      return r.ok ? r.json() : null;
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
      $('iceList'),
      {
        title: 'Не удалось загрузить список',
        body: 'Похоже, пропала связь. Список загрузится заново по кнопке.',
        action: { label: 'Повторить', kind: 'retry' },
      },
      'retry'
    );
  }

  function loadArenas() {
    if (!state.cityId) return Promise.resolve();
    state.loading = true;
    renderList();
    var url = M.buildListUrl({
      cityId: state.cityId,
      intent: state.intent,
      limit: 50,
    });
    return fetchJson(url)
      .then(function (data) {
        state.loading = false;
        applyArenaPayload(data);
        if (state.intent === 'skate' && !state.items.length) {
          return maybeOpenTrainersWhenNoSkate();
        }
        onListLoaded();
      })
      .catch(function () {
        state.loading = false;
        loadFailed();
      });
  }

  function loadTrainers() {
    if (!state.cityId) return Promise.resolve();
    state.loading = true;
    renderList();
    var url = M.buildTrainersUrl({
      cityId: state.cityId,
      serviceId: state.serviceId,
      limit: 50,
    });
    return fetchJson(url)
      .then(function (data) {
        state.loading = false;
        applyTrainerPayload(data);
        onListLoaded();
      })
      .catch(function () {
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
    box.hidden = false;
    var html =
      '<button type="button" class="ice-chip" data-service-id="" aria-pressed="' +
      (state.serviceId ? 'false' : 'true') +
      '">Все</button>';
    (state.services || []).forEach(function (s) {
      var id = String(s.id);
      var pressed = String(state.serviceId || '') === id;
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
        if (state.serviceId) {
          var still = state.services.some(function (s) {
            return Number(s.id) === Number(state.serviceId);
          });
          if (!still) {
            state.serviceId = null;
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

  function applyCity(city) {
    if (!city) return;
    var known = cityFromState(city.id);
    if (known) {
      city = Object.assign({}, known, { name: city.name || known.name, id: known.id });
    }
    state.cityId = city.id;
    state.cityName = city.name || '';
    var nextIntent = M.pickCityIntent(city, state.intent);
    if (nextIntent !== state.intent) state.intent = nextIntent;
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

  function renderCityPicker(filter) {
    var box = $('iceCityList');
    if (!box) return;
    var q = String(filter || '').trim().toLowerCase();
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
        return fetchJson('/api/webapp/client/session', { auth: true }).then(function (session) {
          var sid = session && session.city_id;
          var fromSession = sid
            ? state.cities.filter(function (c) {
                return Number(c.id) === Number(sid);
              })[0]
            : null;
          if (fromSession) {
            if (session.city_name) fromSession = Object.assign({}, fromSession, { name: session.city_name });
            applyCity(fromSession);
            return;
          }
          applyCity(M.pickFallbackCity(state.cities));
        });
      })
      .catch(function () {
        applyCity(M.pickFallbackCity(state.cities));
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
            sub = [it.district, it.city_name, it.address].filter(Boolean).join(' · ');
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

  function onRootClick(ev) {
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
    document.querySelectorAll('#iceIntentChips .ice-chip').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var intent = btn.getAttribute('data-intent');
        var action = M.intentChipAction(intent);
        if (action.type !== 'list') return;
        state.intent = M.coerceIntent(action.intent);
        setChips();
        setViewToggle();
        persist();
        loadList();
      });
    });

    var svcBox = $('iceServiceChips');
    if (svcBox) {
      svcBox.addEventListener('click', function (ev) {
        var chip = ev.target.closest('[data-service-id]');
        if (!chip) return;
        var raw = chip.getAttribute('data-service-id');
        state.serviceId = raw ? Number(raw) : null;
        if (state.serviceId && isNaN(state.serviceId)) state.serviceId = null;
        renderServiceChips();
        persist();
        loadTrainers();
      });
    }

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
      cityList.addEventListener('click', function (ev) {
        var item = ev.target.closest('[data-city-id]');
        if (!item) return;
        var id = Number(item.getAttribute('data-city-id'));
        var city = state.cities.filter(function (c) {
          return Number(c.id) === id;
        })[0];
        openCityPicker(false);
        applyCity(city || { id: id, name: item.getAttribute('data-city-name') || '' });
      });
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
      if (!ev.persisted) return;
      var saved = M.loadIceState(global.sessionStorage);
      if (saved && saved.scrollY) global.scrollTo(0, saved.scrollY);
    });
  }

  function boot() {
    bind();
    var saved = M.loadIceState(global.sessionStorage);
    if (saved && saved.intent) state.intent = M.coerceIntent(saved.intent);
    if (saved && saved.serviceId) state.serviceId = Number(saved.serviceId) || null;
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
      // TASK-091: строка поиска на Главной ведёт сюда и сразу открывает клавиатуру.
      if (params.get('focus') === 'search') {
        global.setTimeout(function () {
          var input = $('iceSearchInput');
          if (input && typeof input.focus === 'function') input.focus();
        }, 0);
      }
    } catch (e) { /* */ }
    setChips();
    setViewToggle();
    /*
     * TASK-095: скелетон рисуется первым же кадром, не дожидаясь резолва города.
     * Иначе между появлением экрана и первым запросом список — пустое место, и
     * на переходе с Главной (TASK-094) въезжает наполовину собранная страница.
     */
    state.loading = true;
    renderList();
    resolveCity().then(function () {
      if (saved && saved.scrollY) {
        global.setTimeout(function () {
          global.scrollTo(0, saved.scrollY);
        }, 0);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(typeof window !== 'undefined' ? window : this);
