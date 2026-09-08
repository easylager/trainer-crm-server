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
   * TASK-084 AC-003 / DEC-002: карта на «Льду» выключена в этом проходе.
   *
   * Код карты — ice-map.js, ice-map-model.js, разметка #iceMapSec и её тесты —
   * намеренно НЕ удалён. Решение владельца 2026-09-08 звучало условием: убрать можно,
   * если мы сможем её вернуть. Возврат = поставить здесь true и вернуть переключатель
   * «Список / Карта» в ice.html; больше ничего.
   *
   * Флаг проверяется в ДВУХ местах не для надёжности, а по необходимости: скрыть
   * переключатель мало — вид «карта» мог остаться в sessionStorage с прошлой сессии
   * или прийти из ?view=map, и тогда экран открылся бы картой без способа вернуться
   * в список.
   */
  var MAP_ENABLED = false;

  function mapViewActive() {
    return MAP_ENABLED && state.intent !== 'coach' && state.view === 'map';
  }

  function setViewToggle() {
    var allowed = MAP_ENABLED && state.intent !== 'coach';
    var seg = $('iceViewSeg');
    if (seg) seg.hidden = !allowed;
    document.querySelectorAll('#iceViewSeg button').forEach(function (btn) {
      var view = btn.getAttribute('data-view') === 'map' ? 'map' : 'list';
      var effective = allowed && state.view === 'map' ? 'map' : 'list';
      btn.setAttribute('aria-pressed', view === effective ? 'true' : 'false');
    });
    var listSec = $('iceListSec');
    var mapSec = $('iceMapSec');
    var showMapView = mapViewActive();
    if (listSec) listSec.hidden = showMapView;
    if (mapSec) mapSec.hidden = !showMapView;
    if (showMapView) {
      showMap();
      if (mapSec && typeof mapSec.scrollIntoView === 'function') {
        mapSec.scrollIntoView({ block: 'start' });
      }
    }
  }

  function showMap() {
    if (!global.IceMap) {
      var emptyEl = $('iceMapEmpty');
      var stageEl = $('iceMapStage');
      if (stageEl) stageEl.hidden = true;
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
      list.innerHTML =
        '<div class="ice-empty"><b>' +
        esc(empty.title) +
        '</b><p>' +
        esc(empty.body) +
        '</p></div>';
      return;
    }
    list.innerHTML = state.items
      .map(function (item) {
        return state.intent === 'coach' ? renderTrainerCard(item) : renderArenaCard(item);
      })
      .join('');
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
    var list = $('iceList');
    if (list) {
      list.innerHTML =
        '<div class="ice-empty"><b>Не удалось загрузить список</b><p>Попробуйте ещё раз.</p></div>';
    }
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
      box.innerHTML = html || '<div class="ice-state">Ничего не найдено</div>';
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
    if (href) shellNav(href);
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

    document.querySelectorAll('#iceViewSeg button').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var view = btn.getAttribute('data-view') || 'list';
        state.view = view === 'map' ? 'map' : 'list';
        setViewToggle();
        persist();
      });
    });

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
    if (saved && saved.view === 'map') state.view = 'map';
    try {
      var params = new URLSearchParams(global.location.search || '');
      if (params.get('view') === 'map') state.view = 'map';
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
