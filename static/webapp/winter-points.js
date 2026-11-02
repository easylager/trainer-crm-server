/**
 * Mini App: зимние катки и коробки внутри фасета «Зимой» (TASK-343, волна 2).
 * Блок встаёт над обычной лентой закрытого сезона; Немига (закреп) идёт первой.
 * Статусы и отметки — те же, что на сайте: /api/public/winter/… и /api/webapp/winter/….
 * Логика подписей и сортировки — static/shared/winter-model.js.
 */
(function (global) {
  'use strict';
  var W = global.GlideWinter;
  if (!W) return;

  var ctx = null;
  var host = null;
  var sheet = null;
  var cache = { key: '', data: null };
  var f = { flooded: false, kind: '', district: '' };
  var seq = 0;
  var report = W.reportInit();
  var idem = W.newIdemKey();
  var current = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function headers(json) {
    var h = ctx && ctx.authHeaders ? ctx.authHeaders() : {};
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }
  function openExternal(url) {
    var tg = global.Telegram && global.Telegram.WebApp;
    try {
      if (/^https:\/\/t\.me\//.test(url) && tg && tg.openTelegramLink) return tg.openTelegramLink(url);
      if (tg && tg.openLink) return tg.openLink(url, { try_instant_view: false });
    } catch (e) { /* ниже */ }
    global.open(url, '_blank', 'noopener,noreferrer');
  }

  function remove() {
    if (host && host.parentNode) host.parentNode.removeChild(host);
    host = null;
  }
  function ensureHost() {
    if (host && host.isConnected) return host;
    var list = document.getElementById('iceList');
    if (!list || !list.parentNode) return null;
    host = document.createElement('div');
    host.id = 'iceWinter';
    host.className = 'w-app';
    list.parentNode.insertBefore(host, list);
    host.addEventListener('click', onClick);
    return host;
  }

  function pill(p) {
    var v = W.stateView(p);
    return '<span class="w-pill w-pill--' + v.tone + '">' + esc(v.label) + '</span>';
  }

  function card(p) {
    var tags = W.liveTags(p, new Date()).map(function (t) { return '<span class="w-tag">' + esc(t) + '</span>'; }).join('');
    if (p.dispute) tags += '<span class="w-tag w-tag--warn">Отметки расходятся</span>';
    var checked = W.checkedLine(p, new Date());
    var dist = W.distanceLabel(p.distance_km);
    var photo = p.photos && p.photos[0] && p.photos[0].variants && (p.photos[0].variants.card || p.photos[0].variants.thumb);
    var thumb = '<span class="w-thumb w-thumb--type"><span class="w-thumb__glyph">' + esc(W.kindLabel(p.kind, true)) + '</span></span>';
    if (photo && /^(https?:)?\//.test(photo)) {
      thumb = '<span class="w-thumb"><img src="' + esc(photo) + '" alt="" loading="lazy"><span class="w-thumb__label">' +
        p.photos.length + ' фото</span></span>';
    }
    return '<a class="w-card" href="#" data-w-open="' + p.id + '" aria-label="' + esc(p.name + ', ' + W.stateView(p).label) + '">' + thumb +
      '<span class="w-card__body"><span class="w-card__top"><span>' + esc(W.kindLabel(p.kind, true)) + '</span><span>' + esc(dist) + '</span></span>' +
      '<span class="w-card__name">' + esc(p.name) + '</span><span class="w-card__tags">' + pill(p) + tags + '</span>' +
      '<span class="w-card__meta">' + esc(W.cardMeta(p)) + '</span>' +
      (checked ? '<span class="w-card__meta">' + esc(checked) + '</span>' : '') + '</span></a>';
  }

  function render() {
    var h = ensureHost();
    var data = cache.data;
    if (!h || !data) return;
    var points = data.items || [];
    var origin = ctx.origin;
    var list = W.applyFilters(points, { flooded: f.flooded, kind: f.kind, origin: origin });
    var head = W.headline(points.length, data.flooded || 0);
    var bell = data.bell_near_link;
    var bellHtml = bell
      ? '<div class="w-bell"><span class="w-bell__text"><span class="w-bell__title">Лёд рядом с вами</span>' +
        '<span class="w-bell__hint">Напишем в Telegram, как только зальют в 2 км от дома</span></span>' +
        '<button type="button" class="w-btn w-btn--tg" data-w-near>Ждать</button></div>'
      : '';
    var chips =
      '<div class="w-chips" role="group" aria-label="Фильтры">' +
      '<button type="button" class="w-chip" data-w-f="flooded" aria-pressed="' + f.flooded + '">Залиты · ' + (data.flooded || 0) + '</button>' +
      '<button type="button" class="w-chip" data-w-f="rink" aria-pressed="' + (f.kind === 'rink') + '">Катки</button>' +
      '<button type="button" class="w-chip" data-w-f="hockey_box" aria-pressed="' + (f.kind === 'hockey_box') + '">Коробки</button></div>';
    h.innerHTML =
      '<div class="w-page" style="padding:0 0 12px">' +
      '<p class="w-sub">' + esc(head.title || W.summaryLine(points.length, data.flooded || 0)) + '</p>' +
      (head.hint ? '<p class="w-sub">' + esc(head.hint) + '</p>' : '') +
      (head.bellFirst ? bellHtml : '') + chips +
      '<p class="w-note">' + esc(W.sortNote({ flooded: f.flooded, kind: f.kind, origin: origin })) + '</p>' +
      (list.length ? '<ul class="w-list" style="padding:0;margin:0">' + list.map(function (p) { return '<li>' + card(p) + '</li>'; }).join('') + '</ul>'
        : '<p class="w-empty">' + esc(W.emptyFilterText({ flooded: f.flooded })) + '</p>') +
      (head.bellFirst ? '' : bellHtml) +
      '</div>';
  }

  function load() {
    var key = ctx.cityId + '|' + (ctx.near || '');
    if (cache.key === key && cache.data) return render();
    var my = ++seq;
    var url = '/api/public/winter/cities/' + encodeURIComponent(ctx.cityId) + '/points';
    if (ctx.near) {
      var ll = String(ctx.near).split(',');
      if (ll.length === 2) url += '?lat=' + encodeURIComponent(ll[0]) + '&lon=' + encodeURIComponent(ll[1]);
    }
    fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (my !== seq || !d) return;
        cache = { key: key, data: d };
        render();
      })
      .catch(function () { /* обычная лента ниже остаётся */ });
  }

  /** ctx: {season, cityId, near, facet, authHeaders, openArena(ref)}. Возвращает true, если блок занят. */
  function sync(c) {
    ctx = c;
    ctx.origin = null;
    if (c.near) {
      var ll = String(c.near).split(',');
      if (ll.length === 2 && isFinite(+ll[0]) && isFinite(+ll[1])) ctx.origin = { lat: +ll[0], lon: +ll[1] };
    }
    var wp = c.facet && c.facet.winter_points;
    if (c.season !== 'winter' || !(wp > 0) || !c.cityId) {
      remove();
      return false;
    }
    load();
    return true;
  }

  /* ───── карточка точки (шторка) ───── */
  function closeSheet() {
    if (sheet && sheet.parentNode) sheet.parentNode.removeChild(sheet);
    sheet = null;
    document.body.style.overflow = '';
  }
  function say(el, text, bad) {
    if (!el) return;
    el.textContent = text;
    el.hidden = !text;
    el.className = bad ? 'w-error' : 'w-thanks';
  }

  function openPoint(id) {
    var p = ((cache.data && cache.data.items) || []).filter(function (x) { return x.id === id; })[0];
    if (!p) return;
    if (!p.own_page) {
      /* Немига и другие арены каталога: обычная карточка со своим расписанием. */
      if (ctx.openArena) ctx.openArena(p.slug || String(p.id));
      return;
    }
    current = p;
    report = W.reportInit();
    idem = W.newIdemKey();
    closeSheet();
    sheet = document.createElement('div');
    sheet.className = 'w-sheet';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    sheet.innerHTML = '<button type="button" class="w-sheet__back" data-w-x aria-label="Закрыть"></button><div class="w-sheet__panel"></div>';
    document.body.appendChild(sheet);
    document.body.style.overflow = 'hidden';
    sheet.addEventListener('click', onSheetClick);
    paintSheet(p, null);
    fetch('/api/public/winter/points/' + p.id, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && sheet && current && current.id === p.id) paintSheet(d, d); })
      .catch(function () {});
  }

  function paintSheet(p, full) {
    var panel = sheet.querySelector('.w-sheet__panel');
    var v = W.stateView(p);
    var map = '';
    if (full && full.static_map_url) {
      var open = 'https://yandex.ru/maps/?pt=' + full.lon + ',' + full.lat + '&z=16&l=map';
      map = '<a href="' + esc(open) + '" data-w-ext class="w-hero__map" style="position:relative;display:block;height:160px;border-radius:14px;overflow:hidden">' +
        '<img src="' + esc(full.static_map_url) + '" alt="Карта" style="width:100%;height:100%;object-fit:cover" onerror="this.parentNode.remove()">' +
        '<span class="w-hero__open">Открыть в Картах</span></a>';
    } else if (p.locating) {
      map = '<p class="w-empty">Точку на карте уточняем</p>';
    }
    var tags = W.liveTags(p, new Date()).map(function (t) { return '<span class="w-tag">' + esc(t) + '</span>'; }).join('');
    var checked = W.checkedLine(p, new Date());
    var known = [
      ['Часы', W.hoursLabel(p)], ['Цена', W.priceLabel(p)], ['Телефон', p.phone_display || p.phone || ''], ['Важно', p.often_hockey_note || ''],
    ].filter(function (r) { return r[1]; }).map(function (r) {
      var val = r[0] === 'Телефон' ? '<a href="tel:' + esc(String(p.phone).split(/[;,]/)[0].replace(/[^\d+]/g, '')) + '" data-w-ext>' + esc(p.phone_display || p.phone) + '</a>' : esc(r[1]);
      return '<dt>' + r[0] + '</dt><dd>' + val + '</dd>';
    }).join('');
    var waiting = p.state === 'waiting' || p.state === 'stale';
    panel.innerHTML =
      '<span class="w-sheet__grab" aria-hidden="true"></span><button type="button" class="w-sheet__close" data-w-x aria-label="Закрыть">×</button>' +
      '<div><span class="w-kindbadge">' + esc(W.kindLabel(p.kind)) + '</span><h2 class="w-sheet__title" style="margin-top:8px">' + esc(p.name) + '</h2>' +
      '<p class="w-sheet__sub">' + esc([p.address, p.district].filter(Boolean).join(' · ')) + '</p></div>' + map +
      '<div class="w-card2 ' + (v.tone === 'ok' ? 'w-card2--ok' : v.tone === 'wait' ? 'w-card2--wait' : '') + '">' +
      '<p class="w-status">' + esc(v.label) + '</p>' + (checked ? '<p class="w-note">' + esc(checked) + '</p>' : '') +
      (tags ? '<span class="w-card__tags">' + tags + '</span>' : '') + '<div data-w-body></div>' +
      '<p class="w-thanks" data-w-msg hidden role="status"></p></div>' +
      (waiting ? '<button type="button" class="w-btn w-btn--tg w-btn--wide" data-w-bell>Написать, когда зальют</button>' : '') +
      '<div class="w-card2"><p class="w-lbl">ЧТО ИЗВЕСТНО</p><dl class="w-kv">' + known + '</dl></div>' +
      (p.route_url ? '<a class="w-btn w-btn--soft w-btn--wide" href="' + esc(p.route_url) + '" data-w-ext data-w-route>Маршрут</a>' : '') +
      '<button type="button" class="w-foot" data-w-gone style="background:none;border:0;color:var(--g-accent-ink)">Точки больше нет или ошибка? Сообщить</button>';
    paintBody(p);
  }

  function paintBody(p) {
    var body = sheet.querySelector('[data-w-body]');
    if (!body) return;
    var qs = W.questionsView(report).map(function (q) {
      return '<fieldset class="w-q"><legend>' + esc(q.label) + '</legend><div class="w-q__row">' + q.opts.map(function (o) {
        return '<button type="button" class="w-opt" data-w-q="' + q.key + '" data-w-o="' + o.id + '" aria-pressed="' + o.selected + '">' + esc(o.label) + '</button>';
      }).join('') + '</div></fieldset>';
    }).join('');
    body.innerHTML = '<p class="w-ask" style="margin:0;font-weight:700">Как там сейчас?</p>' + qs +
      '<button type="button" class="w-btn w-btn--dark w-btn--wide" data-w-send aria-disabled="' + !W.reportCanSend(report) + '">' + esc(W.reportSendLabel(report)) + '</button>';
  }

  function onSheetClick(ev) {
    var t = ev.target;
    if (t.closest('[data-w-x]')) return closeSheet();
    var ext = t.closest('[data-w-ext]');
    if (ext) {
      ev.preventDefault();
      if (ext.hasAttribute('data-w-route') && current) {
        fetch('/api/webapp/winter/points/' + current.id + '/route-click', { method: 'POST', headers: headers(), cache: 'no-store' }).catch(function () {});
      }
      return openExternal(ext.getAttribute('href'));
    }
    var msg = sheet.querySelector('[data-w-msg]');
    var opt = t.closest('[data-w-o]');
    if (opt) {
      report = W.reportToggle(report, opt.getAttribute('data-w-q'), opt.getAttribute('data-w-o'));
      return paintBody(current);
    }
    if (t.closest('[data-w-send]')) {
      if (!W.reportCanSend(report)) return;
      var payload = W.reportPayload(report, { idem_key: idem });
      fetch('/api/webapp/winter/points/' + current.id + '/marks', { method: 'POST', headers: headers(true), body: JSON.stringify(payload) })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { status: r.status, body: j, retry: Number(r.headers.get('Retry-After')) || 0 }; }); })
        .then(function (res) {
          if (res.status === 200) {
            var out = W.reportOutcome(report, res.body, 'miniapp');
            sheet.querySelector('[data-w-body]').innerHTML = '<div class="w-result"><b>Спасибо! Уже на странице:</b><strong>' + esc(out.summary) + '</strong><span>' + esc(out.rule) + '</span></div>';
            cache.key = '';
          } else {
            say(msg, W.reportErrorText(res.status, res.retry), true);
          }
        })
        .catch(function () { say(msg, W.reportErrorText(0), true); });
      return;
    }
    if (t.closest('[data-w-bell]')) {
      fetch('/api/webapp/winter/subscriptions/point', { method: 'POST', headers: headers(true), body: JSON.stringify({ arena_id: current.id }) })
        .then(function (r) { return r.ok; })
        .then(function (ok) { say(msg, ok ? 'Готово. Напишем в Telegram, когда зальют.' : 'Не получилось подписаться. Попробуйте ещё раз.', !ok); });
      return;
    }
    if (t.closest('[data-w-gone]')) {
      fetch('/api/webapp/winter/points/' + current.id + '/gone', { method: 'POST', headers: headers(), cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          say(msg, j && j.counted ? 'Спасибо, передали. Если так скажут ещё несколько человек, проверим точку.' :
            (j ? 'Спасибо, мы уже учли ваш сигнал.' : 'Не получилось отправить.'), !j);
        });
    }
  }

  function onClick(ev) {
    var open = ev.target.closest('[data-w-open]');
    if (open) {
      ev.preventDefault();
      return openPoint(Number(open.getAttribute('data-w-open')));
    }
    var fl = ev.target.closest('[data-w-f]');
    if (fl) {
      var k = fl.getAttribute('data-w-f');
      if (k === 'flooded') f.flooded = !f.flooded;
      else f.kind = f.kind === k ? '' : k;
      return render();
    }
    if (ev.target.closest('[data-w-near]')) {
      /* Подписка «рядом»: нужны координаты; без них отправляем в бота, он спросит геопозицию. */
      var go = function (lat, lon) {
        fetch('/api/webapp/winter/subscriptions/near', { method: 'POST', headers: headers(true), body: JSON.stringify({ lat: lat, lon: lon }) })
          .then(function (r) { return r.ok; })
          .then(function (ok) {
            if (ok) {
              var b = host.querySelector('[data-w-near]');
              if (b) { b.textContent = 'Включено'; b.setAttribute('aria-disabled', 'true'); }
            } else if (cache.data && cache.data.bell_near_link) openExternal(cache.data.bell_near_link);
          });
      };
      if (ctx.origin) return go(ctx.origin.lat, ctx.origin.lon);
      if (cache.data && cache.data.bell_near_link) return openExternal(cache.data.bell_near_link);
    }
  }

  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && sheet) closeSheet(); });
  global.IceWinter = { sync: sync };
})(window);
