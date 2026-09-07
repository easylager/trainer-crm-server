/**
 * TASK-053 / TASK-076 Ice tab page.
 * Skate/group: GET /api/public/ice/arenas. Coach: GET /api/public/trainers (city list).
 * Trainer card tap deep-links to catalog?tab=catalog&trainer_id=… — chip itself stays on ice.html.
 */
(function (global) {
  'use strict';

  var M = global.IceTabModel;
  var state = {
    intent: 'skate',
    view: 'list',
    cityId: null,
    cityName: '',
    cities: [],
    items: [],
    total: 0,
    cursor: null,
    loading: false,
    groupCount: 0,
    skateCount: null,
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
    if (el) el.textContent = '📍 ' + (state.cityName || 'Город');
  }

  function setChips() {
    document.querySelectorAll('#iceIntentChips .ice-chip').forEach(function (btn) {
      var intent = btn.getAttribute('data-intent');
      if (intent === 'group') {
        btn.hidden = !M.shouldShowGroupChip(state.groupCount);
      }
      if (intent === 'skate') {
        btn.hidden = !M.shouldShowSkateChip(state.skateCount);
      }
      btn.setAttribute('aria-pressed', intent === state.intent ? 'true' : 'false');
    });
  }

  function setViewToggle() {
    document.querySelectorAll('#iceViewSeg button').forEach(function (btn) {
      btn.setAttribute('aria-pressed', btn.getAttribute('data-view') === state.view ? 'true' : 'false');
    });
    var listSec = $('iceListSec');
    var mapSec = $('iceMapSec');
    if (listSec) listSec.hidden = state.view !== 'list';
    if (mapSec) mapSec.hidden = state.view !== 'map';
    if (state.view === 'map') {
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
      var loadingEl = $('iceMapLoading');
      if (stageEl) stageEl.hidden = true;
      if (loadingEl) loadingEl.hidden = true;
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
        loadingEl: $('iceMapLoading'),
        getCityCenter: function () {
          var city = selectedCity() || {};
          if (city.latitude == null || city.longitude == null) return null;
          return [Number(city.latitude), Number(city.longitude)];
        },
        getTrainerCount: function () {
          var city = selectedCity() || {};
          return Number(city.trainer_count) || 0;
        },
        getMapRinkCount: function () {
          var city = selectedCity() || {};
          return Number(city.map_rink_count) || 0;
        },
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

  function renderArenaCard(item) {
    var tone = M.liveTone(item);
    var tier = String(item.tier || 'C').toUpperCase();
    var thumb = item.thumb;
    var live = M.formatLiveLine(item);
    var href = M.arenaHref(item);
    var cta = M.listRowCta(item);
    if (cta) live += ' · ' + cta;
    return (
      '<a class="ice-acard" href="' +
      esc(href) +
      '" data-href="' +
      esc(href) +
      '">' +
      '<span class="ice-acard__ph' +
      (thumb ? '' : ' ice-acard__ph--empty') +
      '"' +
      acardThumbStyle(thumb) +
      '></span>' +
      '<span class="ice-acard__body">' +
      '<span class="ice-acard__name">' +
      esc(item.name) +
      '<span class="ice-tier ice-tier--' +
      tone +
      '">' +
      esc(tier) +
      '</span></span>' +
      '<span class="ice-acard__meta">' +
      esc(M.formatMeta(item)) +
      '</span>' +
      '<span class="ice-live ice-live--' +
      tone +
      '">' +
      esc(live) +
      '</span>' +
      '</span></a>'
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
      '></span>' +
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

  function renderList() {
    var list = $('iceList');
    var cap = $('iceCaption');
    if (cap) {
      cap.textContent = M.formatSortCaption({
        total: state.total,
        items: state.items,
        intent: state.intent,
      });
    }
    if (!list) return;
    if (state.loading && !state.items.length) {
      list.innerHTML =
        '<div class="ice-state">' +
        (state.intent === 'coach' ? 'Загрузка тренеров…' : 'Загрузка катков…') +
        '</div>';
      return;
    }
    if (!state.items.length) {
      var empty = emptyView();
      list.innerHTML =
        '<div class="ice-empty"><b>' +
        esc(empty.title) +
        '</b><p>' +
        esc(empty.body) +
        '</p>' +
        (empty.cta
          ? '<button type="button" class="ice-empty__cta" data-action="ice-interest">' +
            esc(empty.cta) +
            '</button>'
          : '') +
        '</div>';
      return;
    }
    list.innerHTML = state.items
      .map(function (item) {
        return state.intent === 'coach' ? renderTrainerCard(item) : renderArenaCard(item);
      })
      .join('');
  }

  function selectedCity() {
    return (
      state.cities.filter(function (c) {
        return Number(c.id) === Number(state.cityId);
      })[0] || null
    );
  }

  function emptyView() {
    var city = selectedCity() || {};
    return M.formatEmptyList(state.intent, {
      trainerCount: city.trainer_count,
      mapRinkCount: city.map_rink_count,
      hasSkate: M.shouldShowSkateChip(state.skateCount),
    });
  }

  function recordIceInterest() {
    if (!state.cityId) return;
    var btn = document.querySelector('[data-action="ice-interest"]');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Записываем…';
    }
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
        document.querySelectorAll('[data-action="ice-interest"]').forEach(function (el) {
          el.disabled = true;
          el.textContent = 'Записали — подскажем, когда появятся сеансы';
        });
      })
      .catch(function () {
        if (btn) {
          btn.disabled = false;
          btn.textContent = (emptyView().cta || 'Хочу кататься здесь');
        }
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
    return state.intent === 'coach' ? loadTrainers() : loadArenas();
  }

  function applyCity(city) {
    if (!city) return;
    state.cityId = city.id;
    state.cityName = city.name || '';
    setCityLabel();
    persist();
    var token = initData();
    if (token && city.id) {
      fetch('/api/webapp/client/session/catalog-filters', {
        method: 'PATCH',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
        body: JSON.stringify({ city_id: city.id }),
      }).catch(function () {});
    }
    state.skateCount = null; // unknown again for the new city — stay optimistic until probed
    loadList();
    probeGroups();
    probeSkate();
  }

  function probeGroups() {
    if (!state.cityId) {
      state.groupCount = 0;
      maybeDropUnavailableIntent();
      setChips();
      return Promise.resolve();
    }
    return fetchJson(M.buildGroupsProbeUrl({ cityId: state.cityId }))
      .then(function (data) {
        var total = data && data.total != null ? data.total : ((data && data.items) || []).length;
        state.groupCount = Number(total) || 0;
        maybeDropUnavailableIntent();
        setChips();
      })
      .catch(function () {
        state.groupCount = 0;
        maybeDropUnavailableIntent();
        setChips();
      });
  }

  function probeSkate() {
    if (!state.cityId) {
      state.skateCount = 0;
      maybeDropUnavailableIntent();
      setChips();
      return Promise.resolve();
    }
    return fetchJson(M.buildListUrl({ cityId: state.cityId, intent: 'skate', limit: 1 }))
      .then(function (data) {
        var total = data && data.total != null ? data.total : ((data && data.items) || []).length;
        state.skateCount = Number(total) || 0;
        maybeDropUnavailableIntent();
        setChips();
      })
      .catch(function () {
        // Network hiccup on the probe only — don't punish the primary lens for it.
        state.skateCount = null;
        setChips();
      });
  }

  function maybeDropUnavailableIntent() {
    var next = M.sanitizeIntent(state.intent, {
      hasGroups: M.shouldShowGroupChip(state.groupCount),
      hasSkate: M.shouldShowSkateChip(state.skateCount),
    });
    if (next === state.intent) return;
    state.intent = next;
    persist();
    loadList();
  }

  function cityButtonHtml(c, cls) {
    return (
      '<button type="button" class="' +
      cls +
      '" data-city-id="' +
      esc(c.id) +
      '">' +
      esc(c.name) +
      '</button>'
    );
  }

  function renderCityPicker(filter) {
    var box = $('iceCityList');
    var popularBox = $('iceCityPopular');
    var popularLabel = $('iceCityPopularLabel');
    if (!box) return;
    var q = String(filter || '').trim().toLowerCase();
    if (!q) {
      // Nothing typed yet: a handful of popular chips beat scrolling ~25+ cities.
      var popular = M.rankPopularCities(state.cities, 8);
      if (popularBox) {
        popularBox.innerHTML = popular.map(function (c) {
          return cityButtonHtml(c, 'ice-picker__popular-item');
        }).join('');
      }
      if (popularLabel) popularLabel.hidden = popular.length === 0;
      box.innerHTML = '';
      return;
    }
    if (popularBox) popularBox.innerHTML = '';
    if (popularLabel) popularLabel.hidden = true;
    var rows = state.cities.filter(function (c) {
      return String(c.name || '').toLowerCase().indexOf(q) >= 0;
    });
    box.innerHTML = rows
      .map(function (c) {
        return cityButtonHtml(c, 'ice-picker__item');
      })
      .join('') || '<div class="ice-state">Город не найден</div>';
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
        state.cities = (data && data.items) || [];
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
      if (listSec) listSec.hidden = state.view !== 'list';
      if (mapSec) mapSec.hidden = state.view !== 'map';
      if (state.view === 'map' && mapCtl) mapCtl.resize();
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
    var interest = ev.target.closest('[data-action="ice-interest"]');
    if (interest) {
      ev.preventDefault();
      recordIceInterest();
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
    if (href) shellNav(href);
  }

  function bind() {
    document.querySelectorAll('#iceIntentChips .ice-chip').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var intent = btn.getAttribute('data-intent');
        if (intent === 'group' && !M.shouldShowGroupChip(state.groupCount)) return;
        if (intent === 'skate' && !M.shouldShowSkateChip(state.skateCount)) return;
        var action = M.intentChipAction(intent);
        if (action.type !== 'list') return;
        state.intent = action.intent;
        setChips();
        persist();
        loadList();
      });
    });

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
    var mapEmpty = $('iceMapEmpty');
    if (mapEmpty) mapEmpty.addEventListener('click', onRootClick);
    var results = $('iceSearchResults');
    if (results) results.addEventListener('click', onRootClick);

    var change = $('iceCityChange');
    if (change) change.addEventListener('click', function () {
      openCityPicker(true);
    });

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

    function onCityPick(ev) {
      var item = ev.target.closest('[data-city-id]');
      if (!item) return;
      var id = Number(item.getAttribute('data-city-id'));
      var city = state.cities.filter(function (c) {
        return Number(c.id) === id;
      })[0];
      openCityPicker(false);
      applyCity(city || { id: id, name: item.textContent });
    }

    var cityList = $('iceCityList');
    if (cityList) cityList.addEventListener('click', onCityPick);
    var cityPopular = $('iceCityPopular');
    if (cityPopular) cityPopular.addEventListener('click', onCityPick);

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
    setChips();
    setViewToggle();
    var saved = M.loadIceState(global.sessionStorage);
    if (saved && saved.intent) state.intent = saved.intent;
    if (saved && saved.view === 'map') state.view = 'map';
    try {
      var params = new URLSearchParams(global.location.search || '');
      if (params.get('view') === 'map') state.view = 'map';
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
