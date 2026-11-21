/**
 * TASK-438: «Поиск» — табло льда. Отрисовка и события; правила — в ice-board-model.js.
 * Данные: GET /api/webapp/client/ice-board (только для флага search_board).
 */
(function (global) {
  'use strict';

  var M = global.IceBoardModel;
  var CITY_KEY = 'ice_board_city_v1';
  var VIEW_KEY = 'ice_board_view_v1';

  var state = {
    cityId: null,
    cityName: '',
    cities: [],
    group: 'skate',
    option: 'today',
    customDate: '',
    today: '',
    payload: null,
    expanded: false,
    reqId: 0,
  };

  var els = {};

  /* ── Окружение ───────────────────────────────────── */

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

  function getJson(url, auth) {
    return fetch(url, { cache: 'no-store', headers: auth ? authHeaders() : {} }).then(function (r) {
      if (!r.ok) {
        var err = new Error('http-' + r.status);
        err.status = r.status;
        throw err;
      }
      return r.json();
    });
  }

  function readJson(key) {
    try {
      return JSON.parse(global.sessionStorage.getItem(key) || 'null');
    } catch (e) {
      return null;
    }
  }

  function writeJson(key, value) {
    try {
      global.sessionStorage.setItem(key, JSON.stringify(value));
    } catch (e) { /* приватный режим — без памяти */ }
  }

  function readCity() {
    try {
      return JSON.parse(global.localStorage.getItem(CITY_KEY) || 'null');
    } catch (e) {
      return null;
    }
  }

  function writeCity(city) {
    try {
      global.localStorage.setItem(CITY_KEY, JSON.stringify({ id: city.id, name: city.name }));
    } catch (e) { /* */ }
  }

  function navigate(path) {
    writeJson(VIEW_KEY, {
      group: state.group,
      option: state.option,
      customDate: state.customDate,
      expanded: state.expanded,
      scroll: global.scrollY || 0,
    });
    if (global.ClientShell && typeof global.ClientShell.navigate === 'function') {
      global.ClientShell.navigate(path);
      return;
    }
    global.location.href = path;
  }

  function haptic() {
    try {
      var tg = global.Telegram && global.Telegram.WebApp;
      if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
    } catch (e) { /* */ }
  }

  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var CHEV =
    '<svg class="ib-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>';

  var GROUP_ICONS = {
    skate:
      '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 2v20M4.9 7l14.2 10M4.9 17 19.1 7M9 3.5l3 2 3-2M9 20.5l3-2 3 2"/></svg>',
    hockey:
      '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M17 3 9 17H4a1 1 0 0 0-1 1v2h7l9-17z"/><circle cx="17" cy="19" r="2"/></svg>',
    figure:
      '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 4h6l1 8h6a3 3 0 0 1 3 3v1H5z"/><path d="M3 20h18"/></svg>',
  };

  /* ── Данные ──────────────────────────────────────── */

  function currentRange() {
    if (state.customDate) return { from: state.customDate, days: 1 };
    var opts = M.dayOptions(state.today);
    for (var i = 0; i < opts.length; i++) if (opts[i].id === state.option) return opts[i];
    return opts[0];
  }

  function load() {
    if (!state.cityId) return;
    var range = state.today ? currentRange() : { from: '', days: 1 };
    var id = ++state.reqId;
    renderSkeleton();
    var url =
      '/api/webapp/client/ice-board?city_id=' +
      encodeURIComponent(state.cityId) +
      (range.from ? '&from=' + encodeURIComponent(range.from) : '') +
      '&days=' +
      range.days;
    getJson(url, true)
      .then(function (data) {
        if (id !== state.reqId) return;
        var firstLoad = !state.today;
        state.today = data.today;
        /* Первый ответ пришёл без from: узнали «сегодня» города — догружаем выбранный вид. */
        if (firstLoad && (state.option !== 'today' || state.customDate)) {
          load();
          return;
        }
        state.payload = data;
        render();
        restoreScroll();
      })
      .catch(function (err) {
        if (id !== state.reqId) return;
        renderError(err);
      });
  }

  var pendingScroll = null;

  function restoreScroll() {
    if (pendingScroll == null) return;
    var y = pendingScroll;
    pendingScroll = null;
    global.requestAnimationFrame(function () {
      global.scrollTo(0, y);
    });
  }

  /* ── Отрисовка ───────────────────────────────────── */

  function renderHead() {
    var p = state.payload;
    els.city.firstChild.nodeValue = (state.cityName || 'Город') + ' ';
    var range = currentRange();
    var head =
      range.days === 1 ? M.dayHeadline(p, state.group, range.from) : M.rangeHeadline(p, state.group, state.option);
    els.title.textContent = head.title;
    els.sub.textContent = head.sub;

    els.groups.innerHTML = M.GROUPS.map(function (g) {
      var n = M.countFor(p.days, g.id);
      var sel = g.id === state.group;
      return (
        '<button type="button" role="tab" class="ib-group" data-group="' +
        g.id +
        '" aria-selected="' +
        sel +
        '">' +
        GROUP_ICONS[g.id] +
        '<span>' +
        esc(g.label) +
        (!sel && n ? ' <span class="ib-group__n">· ' + n + '</span>' : '') +
        '</span></button>'
      );
    }).join('');

    var opts = M.dayOptions(state.today);
    var html = opts
      .map(function (o) {
        var sel = !state.customDate && o.id === state.option;
        return (
          '<button type="button" role="tab" class="ib-day" data-option="' +
          o.id +
          '" aria-selected="' +
          sel +
          '">' +
          esc(o.label) +
          '</button>'
        );
      })
      .join('');
    if (state.customDate) {
      /* День, открытый из «Недели», — отдельной выбранной пилюлей, чтобы было видно, где мы. */
      html =
        '<button type="button" role="tab" class="ib-day" aria-selected="true" data-option="custom">' +
        esc(M.dayChip(state.customDate)) +
        '</button>' +
        html;
    }
    els.days.innerHTML = html;
  }

  function cardPhoto(thumb) {
    if (thumb) return '<img class="ib-card__img" src="' + esc(thumb) + '" alt="" loading="lazy" decoding="async">';
    return '<span class="ib-card__img ib-card__img--empty" aria-hidden="true">' + GROUP_ICONS.skate + '</span>';
  }

  function crest(team, cls) {
    var t = team || {};
    var inner = t.logo
      ? '<img src="' + esc(t.logo) + '" alt="" loading="lazy">'
      : esc(String(t.name || '').slice(0, 1));
    return '<span class="ib-crest ' + cls + '">' + inner + '</span>';
  }

  function itemHtml(it) {
    if (it.type === 'match') {
      var m = it.match;
      var name = (m.home && m.home.name) + ' — ' + (m.away && m.away.name);
      return (
        '<a class="ib-card" href="kto-kogo?match=' +
        encodeURIComponent(String(m.match_id)) +
        '" data-nav>' +
        '<span class="ib-crests" aria-hidden="true">' +
        crest(m.home, 'ib-crest--home') +
        crest(m.away, 'ib-crest--away') +
        '</span><span class="ib-card__body"><span class="ib-card__name">' +
        esc(name) +
        '</span><span class="ib-card__meta">матч' +
        (m.league ? ' · ' + esc(m.league) : '') +
        '</span></span>' +
        CHEV +
        '</a>'
      );
    }
    var s = it.session;
    return (
      '<a class="ib-card" href="' +
      esc(it.href) +
      '" data-nav>' +
      cardPhoto(s.thumb) +
      '<span class="ib-card__body"><span class="ib-card__name">' +
      esc(s.arena_name) +
      '</span><span class="ib-card__meta">' +
      esc(it.price) +
      '</span></span>' +
      CHEV +
      '</a>'
    );
  }

  function rowsHtml(rows) {
    return rows
      .map(function (r) {
        return (
          '<div class="ib-row"><span class="ib-row__t">' +
          esc(r.time) +
          '</span><div class="ib-row__list">' +
          r.items.map(itemHtml).join('') +
          '</div></div>'
        );
      })
      .join('');
  }

  function nowHtml() {
    var p = state.payload;
    return (
      '<div class="ib-now" aria-hidden="true"><span class="ib-now__dot"></span><span class="ib-now__t">Сейчас ' +
      esc(p.now_local) +
      '</span><span class="ib-now__line"></span></div>'
    );
  }

  function emptyHtml(title, sub) {
    return (
      '<div class="ib-empty"><p class="ib-empty__t">' +
      esc(title) +
      '</p>' +
      (sub ? '<p class="ib-empty__s">' + esc(sub) + '</p>' : '') +
      '</div>'
    );
  }

  function emptyForDay() {
    var others = M.GROUPS.filter(function (g) {
      return g.id !== state.group && M.countFor(state.payload.days, g.id) > 0;
    });
    var hint = state.option !== 'week' ? 'Загляните в «Неделю» — там видно ближайшие дни.' : '';
    if (others.length) hint = 'Есть «' + others[0].label + '» — переключите вид выше.';
    return emptyHtml('В этот день сеансов нет', hint);
  }

  function dayView(date) {
    var rows = M.timeline(state.payload, state.group, date);
    if (!rows.length) return emptyForDay();
    var split = M.splitTimeline(rows);
    var html = date === state.payload.today ? nowHtml() : '';
    html += rowsHtml(split.head);
    if (split.more) {
      if (state.expanded) {
        html += rowsHtml(split.tail);
      } else {
        html +=
          '<button type="button" class="ib-more" data-more><span>' +
          esc(split.more.label) +
          '</span>' +
          (split.more.hint ? '<span class="ib-more__hint">' + esc(split.more.hint) + '</span>' : '') +
          '</button>';
      }
    }
    return html;
  }

  function multiDayView() {
    var days = M.multiDayFeed(state.payload, state.group);
    if (!days.length) return emptyForDay();
    return days
      .map(function (d) {
        return '<h2 class="ib-sep">' + esc(d.title) + '</h2>' + rowsHtml(d.rows);
      })
      .join('');
  }

  function weekView() {
    var head = M.weekHeader(state.payload, state.group)
      .map(function (d) {
        var cls = 'ib-wd' + (d.isToday ? ' ib-wd--today' : '') + (d.total ? '' : ' ib-wd--zero');
        return (
          '<button type="button" class="' +
          cls +
          '" data-date="' +
          esc(d.date) +
          '" aria-label="' +
          esc(M.dayChip(d.date) + ': ' + d.total + ' ' + M.plural(d.total, 'сеанс', 'сеанса', 'сеансов')) +
          '"><span class="ib-wd__d">' +
          esc(d.short) +
          '</span><span class="ib-wd__n">' +
          esc(d.num) +
          '</span><span class="ib-wd__t">' +
          (d.total || '—') +
          '</span></button>'
        );
      })
      .join('');
    var html = '<div class="ib-week-head" role="group" aria-label="Дни недели">' + head + '</div>';
    if (state.group !== 'skate') return html + multiDayView();
    var rows = M.weekArenas(state.payload, state.group);
    if (!rows.length) return html + emptyForDay();
    html += '<p class="ib-note">Сначала катки, где лёд есть чаще. Цифра — сколько сеансов в этот день.</p>';
    html += rows
      .map(function (a) {
        var cells = a.cells
          .map(function (c) {
            if (!c.count) {
              return (
                '<span class="ib-cell ib-cell--empty"><span class="ib-cell__d">' +
                esc(c.short) +
                '</span><span class="ib-cell__n">—</span></span>'
              );
            }
            return (
              '<a class="ib-cell" href="' +
              esc(c.href) +
              '" data-nav><span class="ib-cell__d">' +
              esc(c.short) +
              '</span><span class="ib-cell__n">' +
              c.count +
              '</span></a>'
            );
          })
          .join('');
        return (
          '<div class="ib-wcard"><a class="ib-wcard__top" href="arena?ref=' +
          encodeURIComponent(String(a.arena_id)) +
          '" data-nav>' +
          cardPhoto(a.thumb) +
          '<span class="ib-card__body"><span class="ib-card__name">' +
          esc(a.name) +
          '</span><span class="ib-card__meta">' +
          esc(a.meta) +
          '</span>' +
          (a.next ? '<span class="ib-wcard__next">' + esc(a.next) + '</span>' : '') +
          '</span>' +
          CHEV +
          '</a><div class="ib-cells">' +
          cells +
          '</div></div>'
        );
      })
      .join('');
    return html;
  }

  function weekendView() {
    if (state.group !== 'skate') return multiDayView();
    var rows = M.weekendArenas(state.payload, state.group);
    if (!rows.length) return emptyForDay();
    return rows
      .map(function (a) {
        var cols = a.cols
          .map(function (c) {
            var times = c.times
              .map(function (t) {
                return '<a class="ib-time" href="' + esc(t.href) + '" data-nav>' + esc(t.time) + '</a>';
              })
              .join('');
            if (c.more) {
              times +=
                '<a class="ib-time ib-time--more" href="' +
                esc(c.moreHref) +
                '" data-nav aria-label="Ещё ' +
                c.more +
                '">+' +
                c.more +
                '</a>';
            }
            return (
              '<div class="ib-col"><span class="ib-col__d">' +
              esc(c.label) +
              '</span>' +
              (times ? '<div class="ib-times">' + times + '</div>' : '<span class="ib-col__none">нет</span>') +
              '</div>'
            );
          })
          .join('');
        return (
          '<div class="ib-wcard"><a class="ib-wcard__top" href="arena?ref=' +
          encodeURIComponent(String(a.arena_id)) +
          '" data-nav>' +
          cardPhoto(a.thumb) +
          '<span class="ib-card__body"><span class="ib-card__name">' +
          esc(a.name) +
          '</span><span class="ib-card__meta">' +
          esc(a.price || 'цена на месте') +
          '</span></span>' +
          CHEV +
          '</a><div class="ib-cols">' +
          cols +
          '</div></div>'
        );
      })
      .join('');
  }

  function placesHtml() {
    var q = state.cityId ? '&city_id=' + encodeURIComponent(state.cityId) : '';
    var links = [
      ['Заточка', 'ice?intent=service' + q],
      ['Магазины', 'ice?venue=shop' + q],
      ['Зимой на улице', 'ice?venue=outdoor' + q],
      ['Хоккейные центры', 'ice?intent=ohm&seg=centers' + q],
    ];
    return (
      '<nav class="ib-places" aria-label="Места без сеансов"><span class="ib-places__label">Ещё в городе</span>' +
      links
        .map(function (l) {
          return '<a class="ib-place" href="' + esc(l[1]) + '" data-nav>' + esc(l[0]) + '</a>';
        })
        .join('') +
      '</nav>'
    );
  }

  function render() {
    renderHead();
    var range = currentRange();
    var body;
    if (range.days === 1) body = dayView(range.from);
    else if (state.option === 'week') body = weekView();
    else body = weekendView();
    els.main.innerHTML = body + placesHtml();
    document.body.classList.remove('ice-booting');
    if (global.ClientShell && global.ClientShell.contentShown) global.ClientShell.contentShown();
  }

  function renderSkeleton() {
    if (!state.payload) {
      els.title.textContent = ' ';
      els.sub.textContent = ' ';
    }
    els.main.innerHTML =
      '<div class="ib-skel"></div><div class="ib-skel"></div><div class="ib-skel"></div><div class="ib-skel"></div>';
  }

  function renderError(err) {
    var ui = global.MiniAppErrorUi;
    els.main.innerHTML = '';
    if (ui && typeof ui.renderLoadError === 'function') {
      ui.renderLoadError(els.main, { error: err, onRetry: load });
    } else {
      els.main.innerHTML = emptyHtml('Не загрузилось', '');
    }
    document.body.classList.remove('ice-booting');
  }

  /* ── Город ───────────────────────────────────────── */

  function openCitySheet() {
    var list = state.cities.length ? Promise.resolve(state.cities) : getJson('/api/public/ice/cities', false).then(function (d) {
      state.cities = (d && d.items) || [];
      return state.cities;
    });
    els.sheet.hidden = false;
    list
      .then(function (cities) {
        els.cityList.innerHTML = cities
          .map(function (c) {
            return (
              '<button type="button" class="ib-cityopt" data-city-id="' +
              esc(c.id) +
              '" aria-current="' +
              (Number(c.id) === Number(state.cityId)) +
              '">' +
              esc(c.name) +
              '</button>'
            );
          })
          .join('');
      })
      .catch(function (err) {
        var ui = global.MiniAppErrorUi;
        if (ui) ui.renderLoadError(els.cityList, { error: err, onRetry: openCitySheet });
      });
  }

  function closeCitySheet() {
    els.sheet.hidden = true;
  }

  function pickCity(city) {
    closeCitySheet();
    if (Number(city.id) === Number(state.cityId)) return;
    state.cityId = Number(city.id);
    state.cityName = city.name;
    state.customDate = '';
    state.expanded = false;
    writeCity(city);
    if (initData()) {
      fetch('/api/webapp/client/session/catalog-filters', {
        method: 'PATCH',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
        body: JSON.stringify({ city_id: city.id }),
      }).catch(function () {});
    }
    load();
  }

  function resolveCity() {
    var fromUrl = /[?&]city_id=([1-9]\d*)/.exec(global.location.search || '');
    var saved = readCity();
    if (fromUrl) {
      state.cityId = Number(fromUrl[1]);
      if (saved && Number(saved.id) === state.cityId) state.cityName = saved.name;
    } else if (saved && saved.id) {
      state.cityId = Number(saved.id);
      state.cityName = saved.name || '';
    }
    if (state.cityId && state.cityName) return Promise.resolve();
    var shell = global.ClientShell;
    var req =
      shell && typeof shell.getJsonOnce === 'function'
        ? shell.getJsonOnce('/api/webapp/client/session')
        : getJson('/api/webapp/client/session', true);
    return Promise.resolve(req)
      .catch(function () {
        return null;
      })
      .then(function (session) {
        if (!state.cityId && session && session.city_id) state.cityId = Number(session.city_id);
        if (session && session.city_name && Number(session.city_id) === state.cityId) state.cityName = session.city_name;
        if (state.cityId && state.cityName) return;
        return getJson('/api/public/ice/cities', false).then(function (d) {
          state.cities = (d && d.items) || [];
          var hit = state.cities.filter(function (c) {
            return Number(c.id) === Number(state.cityId);
          })[0];
          var city = hit || state.cities[0];
          if (city) {
            state.cityId = Number(city.id);
            state.cityName = city.name;
          }
        });
      })
      .then(function () {
        if (state.cityId) writeCity({ id: state.cityId, name: state.cityName });
      });
  }

  /* ── События ─────────────────────────────────────── */

  function bind() {
    els.groups.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-group]');
      if (!b || b.getAttribute('data-group') === state.group) return;
      haptic();
      state.group = b.getAttribute('data-group');
      state.expanded = false;
      /* Вид меняет только фильтр по уже загруженным дням — без запроса. */
      render();
    });
    els.days.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-option]');
      if (!b) return;
      var opt = b.getAttribute('data-option');
      if (opt === 'custom' || (opt === state.option && !state.customDate)) return;
      haptic();
      state.option = opt;
      state.customDate = '';
      state.expanded = false;
      load();
    });
    els.main.addEventListener('click', function (ev) {
      var more = ev.target.closest('[data-more]');
      if (more) {
        state.expanded = true;
        render();
        return;
      }
      var wd = ev.target.closest('[data-date]');
      if (wd) {
        haptic();
        state.customDate = wd.getAttribute('data-date');
        state.expanded = false;
        load();
        global.scrollTo(0, 0);
        return;
      }
      var a = ev.target.closest('a[data-nav]');
      if (a) {
        ev.preventDefault();
        navigate(a.getAttribute('href'));
      }
    });
    els.city.addEventListener('click', openCitySheet);
    els.search.addEventListener('click', function (ev) {
      ev.preventDefault();
      navigate(els.search.getAttribute('href'));
    });
    els.sheet.addEventListener('click', function (ev) {
      if (ev.target === els.sheet || ev.target.closest('[data-close]')) {
        closeCitySheet();
        return;
      }
      var opt = ev.target.closest('[data-city-id]');
      if (!opt) return;
      var id = Number(opt.getAttribute('data-city-id'));
      var city = state.cities.filter(function (c) {
        return Number(c.id) === id;
      })[0];
      if (city) pickCity(city);
    });
    /* Фото не загрузилось — та же заглушка, что у катка без фото, а не значок битой картинки. */
    els.main.addEventListener(
      'error',
      function (ev) {
        var img = ev.target;
        if (!img || img.tagName !== 'IMG' || !img.classList.contains('ib-card__img')) return;
        var ph = document.createElement('span');
        ph.className = 'ib-card__img ib-card__img--empty';
        ph.setAttribute('aria-hidden', 'true');
        ph.innerHTML = GROUP_ICONS.skate;
        img.replaceWith(ph);
      },
      true
    );
    global.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && !els.sheet.hidden) closeCitySheet();
    });
  }

  function paintTelegramChrome() {
    try {
      var tg = global.Telegram && global.Telegram.WebApp;
      if (!tg) return;
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor('#0d1b26');
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor('#0d1b26');
    } catch (e) { /* старый клиент Telegram */ }
  }

  function boot() {
    els = {
      city: document.getElementById('ibCity'),
      search: document.getElementById('ibSearch'),
      title: document.getElementById('ibTitle'),
      sub: document.getElementById('ibSub'),
      groups: document.getElementById('ibGroups'),
      days: document.getElementById('ibDays'),
      main: document.getElementById('ibMain'),
      sheet: document.getElementById('ibSheet'),
      cityList: document.getElementById('ibCityList'),
    };
    paintTelegramChrome();
    /* Возврат с карточки катка: тот же вид, день и место в ленте. */
    var saved = readJson(VIEW_KEY);
    if (saved) {
      if (saved.group) state.group = saved.group;
      if (saved.option) state.option = saved.option;
      state.customDate = saved.customDate || '';
      state.expanded = !!saved.expanded;
      pendingScroll = Number(saved.scroll) || 0;
    }
    bind();
    renderSkeleton();
    resolveCity().then(function () {
      if (!state.cityId) {
        renderError(new Error('no-city'));
        return;
      }
      if (global.ClientShell && global.ClientShell.reportCatalogPresence) {
        global.ClientShell.reportCatalogPresence('miniapp_ice', null, { city_id: state.cityId });
      }
      load();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})(window);
