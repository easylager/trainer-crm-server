/**
 * Сайт: «Зимой в <городе>» и страница зимней точки (TASK-343, волна 2).
 * Страницы целиком отрисованы на сервере; здесь только поведение: сортировка по расстоянию, чипы,
 * карта Яндекса (JS API, как в Mini App) и шторка «Как там сейчас?». Логика — в winter-model.js.
 */
(function () {
  'use strict';
  var W = window.GlideWinter;
  if (!W) return;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }
  function $all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ───────────────────────── список города ───────────────────────── */
  function initCity() {
    var dataEl = $('#w-data');
    if (!dataEl) return;
    var cfg;
    try {
      cfg = JSON.parse(dataEl.textContent || '{}');
    } catch (e) {
      return;
    }
    var points = cfg.points || [];
    var byId = {};
    points.forEach(function (p) {
      byId[p.id] = p;
    });
    var list = $('[data-w-list]');
    var noteEl = $('[data-w-note]');
    var emptyEl = $('[data-w-empty]');
    var mapBox = $('[data-w-map]');
    var legend = $('[data-w-legend]');
    var chipsBox = $('[data-w-chips]');
    var distBox = $('[data-w-districts]');
    var f = { flooded: false, kind: '', district: '', origin: null };
    var view = 'list';
    var districts = W.districtList(points);
    var items = {};
    $all('.w-li', list).forEach(function (li) {
      var a = $('[data-w-id]', li);
      if (a) items[a.getAttribute('data-w-id')] = li;
    });

    /* «Ближе ко мне» — первая кнопка; геолокацию просим только по тапу. */
    var nearChip = document.createElement('button');
    nearChip.type = 'button';
    nearChip.className = 'w-chip';
    nearChip.setAttribute('data-w-chip', 'near');
    nearChip.setAttribute('aria-pressed', 'false');
    nearChip.textContent = 'Ближе ко мне';
    chipsBox.insertBefore(nearChip, chipsBox.firstChild);

    var districtChip = $('[data-w-chip="district"]');
    if (districts.length >= 1) {
      districtChip.hidden = false;
    }

    function setPressed(btn, on) {
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    }

    function paintTimes() {
      var now = new Date();
      Object.keys(items).forEach(function (id) {
        var p = byId[id];
        var li = items[id];
        var line = $('[data-w-checked]', li);
        if (line) {
          var text = W.checkedLine(p, now);
          line.textContent = text;
          line.hidden = !text;
        }
      });
    }

    function render() {
      var out = W.applyFilters(points, f);
      var shown = {};
      out.forEach(function (p) {
        shown[p.id] = p;
        var li = items[p.id];
        if (!li) return;
        list.appendChild(li);
        li.hidden = false;
        var d = $('[data-w-dist]', li);
        if (d) d.textContent = W.distanceLabel(p.distance_km);
      });
      Object.keys(items).forEach(function (id) {
        if (!shown[id]) items[id].hidden = true;
      });
      noteEl.textContent = W.sortNote(f);
      emptyEl.hidden = out.length > 0;
      if (!out.length) emptyEl.textContent = W.emptyFilterText(f);
      if (view === 'map' && mapCtl) mapCtl.show(out);
    }

    function toggleFilter(name) {
      if (name === 'flooded') {
        f.flooded = !f.flooded;
        setPressed($('[data-w-chip="flooded"]'), f.flooded);
      } else if (name === 'rink' || name === 'hockey_box') {
        f.kind = f.kind === name ? '' : name;
        setPressed($('[data-w-chip="rink"]'), f.kind === 'rink');
        setPressed($('[data-w-chip="hockey_box"]'), f.kind === 'hockey_box');
      } else if (name === 'district') {
        var open = distBox.hidden;
        distBox.hidden = !open;
        setPressed(districtChip, open || !!f.district);
        if (open && !distBox.children.length) {
          districts.forEach(function (d) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'w-chip w-chip--sub';
            b.setAttribute('data-w-district', d.name);
            b.setAttribute('aria-pressed', 'false');
            b.textContent = d.name + ' · ' + d.count;
            distBox.appendChild(b);
          });
        }
        return;
      }
      render();
    }

    function geolocate() {
      if (f.origin) {
        f.origin = null;
        setPressed(nearChip, false);
        render();
        return;
      }
      if (!navigator.geolocation) {
        noteEl.textContent = 'Геолокация недоступна — показываем по районам.';
        return;
      }
      noteEl.textContent = 'Ищем, где вы…';
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          f.origin = { lat: pos.coords.latitude, lon: pos.coords.longitude };
          setPressed(nearChip, true);
          render();
        },
        function () {
          setPressed(nearChip, false);
          noteEl.textContent = 'Геолокация выключена — показываем по районам.';
        },
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 }
      );
    }

    chipsBox.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-w-chip]');
      if (!b) return;
      var name = b.getAttribute('data-w-chip');
      if (name === 'near') geolocate();
      else toggleFilter(name);
    });
    distBox.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-w-district]');
      if (!b) return;
      var name = b.getAttribute('data-w-district');
      f.district = f.district === name ? '' : name;
      $all('[data-w-district]', distBox).forEach(function (x) {
        setPressed(x, x.getAttribute('data-w-district') === f.district);
      });
      setPressed(districtChip, !!f.district || !distBox.hidden);
      render();
    });

    /* Список / Карта */
    var mapCtl = null;
    $all('[data-w-view]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        view = btn.getAttribute('data-w-view');
        $all('[data-w-view]').forEach(function (b) {
          setPressed(b, b === btn);
        });
        var map = view === 'map';
        list.hidden = map;
        mapBox.hidden = !map;
        legend.hidden = !map;
        if (!map) {
          render();
          return;
        }
        if (!mapCtl) mapCtl = createMap(cfg, mapBox, byId);
        mapCtl.show(W.applyFilters(points, f));
      });
    });

    paintTimes();
    render();
  }

  /* Карта Яндекса: тот же JS API и ключ, что в Mini App. Логотип и «Открыть в Картах» не скрываем. */
  var ymapsLoad = null;
  function loadYmaps(key) {
    if (ymapsLoad) return ymapsLoad;
    ymapsLoad = new Promise(function (resolve, reject) {
      if (!key) return reject(new Error('no-key'));
      if (window.ymaps && window.ymaps.ready) return window.ymaps.ready(function () { resolve(window.ymaps); });
      var s = document.createElement('script');
      s.src = 'https://api-maps.yandex.ru/2.1/?apikey=' + encodeURIComponent(key) + '&lang=ru_RU';
      s.async = true;
      s.onload = function () {
        if (!window.ymaps || !window.ymaps.ready) return reject(new Error('ymaps'));
        window.ymaps.ready(function () { resolve(window.ymaps); });
      };
      s.onerror = function () {
        ymapsLoad = null;
        reject(new Error('ymaps-load'));
      };
      document.head.appendChild(s);
    });
    return ymapsLoad;
  }

  var GLYPH = { ok: '✓', wait: '•', quiet: '–', dispute: '!' };

  function createMap(cfg, box, byId) {
    var canvas = $('[data-w-canvas]', box);
    var msg = $('[data-w-mapmsg]', box);
    var card = $('[data-w-mapcard]', box);
    var ym = null;
    var map = null;
    var clusterer = null;
    var pending = null;

    function say(text) {
      msg.textContent = text;
      msg.hidden = !text;
    }

    function openCard(p) {
      var v = W.stateView(p);
      card.hidden = false;
      card.innerHTML =
        '<a class="w-mapcard__name" href="' + esc(p.href) + '">' + esc(p.name) + '</a>' +
        '<span class="w-card__tags"><span class="w-pill w-pill--' + esc(v.tone) + '">' + esc(v.label) + '</span></span>' +
        '<a class="w-btn w-btn--soft" href="' + esc(p.href) + '">Открыть</a>';
    }

    function draw(list) {
      if (!ym) {
        pending = list;
        return;
      }
      var pts = W.mapPoints(list);
      if (!map) {
        var first = pts[0] || { lat: 53.9, lon: 27.56 };
        map = new ym.Map(canvas, { center: [first.lat, first.lon], zoom: 11, controls: ['zoomControl'] });
        map.events.add('click', function () { card.hidden = true; });
      }
      if (clusterer) map.geoObjects.remove(clusterer);
      var Layout = ym.templateLayoutFactory.createClass(
        '<div class="w-pin w-pin--$[properties.pin]"><i>$[properties.glyph]</i></div>'
      );
      clusterer = new ym.Clusterer({ preset: 'islands#invertedDarkBlueClusterIcons', groupByCoordinates: false, hasBalloon: false });
      var marks = pts.map(function (p) {
        var v = W.stateView(p);
        var pm = new ym.Placemark(
          [p.lat, p.lon],
          { pin: v.pin, glyph: GLYPH[v.pin] || '', hintContent: p.name },
          { iconLayout: Layout, iconShape: { type: 'Circle', coordinates: [0, -6], radius: 22 }, hasBalloon: false }
        );
        pm.events.add('click', function () { openCard(byId[p.id] || p); });
        return pm;
      });
      clusterer.add(marks);
      map.geoObjects.add(clusterer);
      if (pts.length) {
        var bounds = clusterer.getBounds();
        if (bounds) map.setBounds(bounds, { checkZoomRange: true, zoomMargin: 40 });
      }
      say(pts.length ? '' : 'На карте пока нечего показать: точный адрес известен не у всех точек.');
      card.hidden = true;
    }

    say('Загружаем карту…');
    loadYmaps(cfg.ymapsKey).then(
      function (y) {
        ym = y;
        say('');
        if (pending) draw(pending);
        else if (map) map.container.fitToViewport();
      },
      function () {
        say('Карта не загрузилась. Список работает как обычно.');
      }
    );
    return {
      show: function (list) {
        draw(list);
        if (map) map.container.fitToViewport();
      },
    };
  }

  /* ───────────────────────── страница точки ───────────────────────── */
  function initPoint() {
    var page = $('[data-w-page="point"]');
    if (!page) return;
    var arenaId = page.getAttribute('data-w-arena');
    var api = page.getAttribute('data-w-api');
    var thanks = $('[data-w-thanks]', page);
    var errBox = $('[data-w-error]', page);
    var token = null;
    var tokenLoaded = null;
    var sheet = $('[data-w-sheet]', page);
    var state = W.reportInit();
    var idem = W.newIdemKey();
    var busy = false;
    var lastFocus = null;

    function loadToken(force) {
      if (tokenLoaded && !force) return tokenLoaded;
      tokenLoaded = fetch(api, { cache: 'no-store', credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { token = (d && d.mark_token) || null; return token; })
        .catch(function () { token = null; return null; });
      return tokenLoaded;
    }
    /* Токен берём не из HTML: страница кэшируется, токен живёт 30 минут. */
    if ('requestIdleCallback' in window) window.requestIdleCallback(function () { loadToken(); });
    else setTimeout(loadToken, 800);

    function post(payload, retried) {
      return loadToken(!!retried).then(function (tok) {
        if (!tok) return { status: 503 };
        var body = Object.assign({}, payload, { token: tok, idem_key: idem, website: '' });
        var hp = sheet && $('[data-w-hp]', sheet);
        if (hp) body.website = hp.value || '';
        return fetch('/api/public/winter/points/' + encodeURIComponent(arenaId) + '/marks', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }).then(function (r) {
          if (r.status === 403 && !retried) return post(payload, true);
          return r.json().catch(function () { return {}; }).then(function (j) {
            return { status: r.status, body: j, retry: Number(r.headers.get('Retry-After')) || 0 };
          });
        });
      }).catch(function () { return { status: 0 }; });
    }

    function showError(box, status, retry) {
      if (!box) return;
      box.textContent = status === 503
        ? 'Отметки с сайта сейчас выключены. Отметить можно в Telegram: кнопка «Написать в Telegram» выше.'
        : W.reportErrorText(status, retry);
      box.hidden = false;
    }

    function afterSuccess(res) {
      var changed = res && res.body && res.body.changed;
      if (changed) setTimeout(function () { location.reload(); }, 1600);
    }

    /* Быстрые отметки на странице «Ждём заливку»: «Уже залит» / «Не зальют». */
    $all('[data-w-quick]', page).forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (busy) return;
        var choice = btn.getAttribute('data-w-quick');
        var payload = W.quickPayload(choice);
        if (!payload) return;
        busy = true;
        errBox.hidden = true;
        thanks.hidden = true;
        $all('[data-w-quick]', page).forEach(function (b) { b.setAttribute('aria-disabled', 'true'); });
        post(payload).then(function (res) {
          busy = false;
          $all('[data-w-quick]', page).forEach(function (b) { b.removeAttribute('aria-disabled'); });
          if (res.status === 200) {
            var st = W.reportInit();
            st.ice = choice;
            var out = W.reportOutcome(st, res.body, 'site');
            thanks.textContent = 'Спасибо! ' + out.rule;
            thanks.hidden = false;
            afterSuccess(res);
            idem = W.newIdemKey();
          } else {
            showError(errBox, res.status, res.retry);
          }
        });
      });
    });

    /* Шторка */
    function renderQuestions() {
      var host = $('[data-w-questions]', sheet);
      host.innerHTML = W.questionsView(state)
        .map(function (q) {
          return (
            '<fieldset class="w-q"><legend>' + esc(q.label) + '</legend><div class="w-q__row">' +
            q.opts.map(function (o) {
              return '<button type="button" class="w-opt" data-w-q="' + q.key + '" data-w-o="' + o.id +
                '" aria-pressed="' + (o.selected ? 'true' : 'false') + '">' + esc(o.label) + '</button>';
            }).join('') +
            '</div></fieldset>'
          );
        })
        .join('');
      var send = $('[data-w-send]', sheet);
      var ok = W.reportCanSend(state);
      send.textContent = W.reportSendLabel(state);
      send.setAttribute('aria-disabled', ok ? 'false' : 'true');
    }

    function focusables() {
      return $all('a[href], button:not([disabled]):not([hidden]), input:not([tabindex="-1"])', sheet).filter(function (el) {
        return el.offsetParent !== null;
      });
    }
    function openSheet() {
      lastFocus = document.activeElement;
      state = W.reportInit();
      $('[data-w-asking]', sheet).hidden = false;
      $('[data-w-done]', sheet).hidden = true;
      $('[data-w-sheet-error]', sheet).hidden = true;
      renderQuestions();
      sheet.hidden = false;
      document.body.style.overflow = 'hidden';
      loadToken();
      var first = focusables()[0];
      if (first) first.focus();
    }
    function closeSheet() {
      sheet.hidden = true;
      document.body.style.overflow = '';
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }
    $all('[data-w-open-sheet]', page).forEach(function (b) { b.addEventListener('click', openSheet); });
    if (sheet) {
      sheet.addEventListener('click', function (ev) {
        if (ev.target.closest('[data-w-close]')) {
          closeSheet();
          return;
        }
        var opt = ev.target.closest('[data-w-o]');
        if (opt) {
          state = W.reportToggle(state, opt.getAttribute('data-w-q'), opt.getAttribute('data-w-o'));
          renderQuestions();
          var again = $('[data-w-q="' + opt.getAttribute('data-w-q') + '"][data-w-o="' + opt.getAttribute('data-w-o') + '"]', sheet);
          if (again) again.focus();
          return;
        }
        if (ev.target.closest('[data-w-send]')) {
          if (!W.reportCanSend(state) || busy) return;
          busy = true;
          var errEl = $('[data-w-sheet-error]', sheet);
          errEl.hidden = true;
          post(W.reportPayload(state)).then(function (res) {
            busy = false;
            if (res.status === 200) {
              var out = W.reportOutcome(state, res.body, 'site');
              $('[data-w-summary]', sheet).textContent = out.summary;
              $('[data-w-rule]', sheet).textContent = out.rule;
              $('[data-w-asking]', sheet).hidden = true;
              $('[data-w-done]', sheet).hidden = false;
              var done = $('[data-w-close]', $('[data-w-done]', sheet));
              if (done) done.focus();
              idem = W.newIdemKey();
              afterSuccess(res);
            } else {
              showError(errEl, res.status, res.retry);
            }
          });
        }
      });
      document.addEventListener('keydown', function (ev) {
        if (sheet.hidden) return;
        if (ev.key === 'Escape') {
          closeSheet();
        } else if (ev.key === 'Tab') {
          var f = focusables();
          if (!f.length) return;
          var first = f[0];
          var last = f[f.length - 1];
          if (ev.shiftKey && document.activeElement === first) {
            ev.preventDefault();
            last.focus();
          } else if (!ev.shiftKey && document.activeElement === last) {
            ev.preventDefault();
            first.focus();
          }
        }
      });
    }
  }

  initCity();
  initPoint();
})();
