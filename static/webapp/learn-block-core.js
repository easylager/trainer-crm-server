/**
 * [Загружается по требованию из learn-block.js вместе с trainer-showcase-model.js, learn-block-model.js и learn-block.css.]
 * Блок «Учиться с тренером» в точках входа Mini App (TASK-354, PDEC-033): главная, Поиск,
 * карточка катка, «Мои записи». Один компонент на все экраны; что и когда показывать — решает
 * экран (правило места), что написать — LearnBlockModel.
 *
 * Данные — один запрос `/api/public/trainer-showcase?city_id=` на город, с кешем на сеанс
 * (память + sessionStorage). Ошибка загрузки — блок просто не показывается, экран не страдает.
 *
 *   LearnBlock.mount('#id' | element, { place: 'city'|'skate'|'hockey'|'arena', cityId, arenaId })
 *   LearnBlock.hide('#id' | element)
 */
(function (global) {
  'use strict';

  var M = global.TrainerShowcaseModel;
  var L = global.LearnBlockModel;
  var CACHE_KEY = 'glide_learn_showcase_v1:';
  var CACHE_TTL_MS = 10 * 60 * 1000;
  var memory = {};
  var inflight = {};

  function cacheKey(cityId) {
    return String(cityId || 'all');
  }

  function readStored(key) {
    try {
      var raw = global.sessionStorage.getItem(CACHE_KEY + key);
      if (!raw) return null;
      var rec = JSON.parse(raw);
      if (!rec || !Array.isArray(rec.items) || Date.now() - rec.at > CACHE_TTL_MS) return null;
      return rec.items;
    } catch (e) {
      return null;
    }
  }

  function writeStored(key, items) {
    try {
      global.sessionStorage.setItem(CACHE_KEY + key, JSON.stringify({ at: Date.now(), items: items }));
    } catch (e) { /* без памяти или песочница */ }
  }

  /** Выдача города из кеша сеанса или null. */
  function cached(cityId) {
    var key = cacheKey(cityId);
    if (memory[key]) return memory[key];
    var stored = readStored(key);
    if (stored) memory[key] = stored;
    return stored;
  }

  function load(cityId) {
    var have = cached(cityId);
    if (have) return Promise.resolve(have);
    var key = cacheKey(cityId);
    if (!inflight[key]) {
      var q = cityId ? '?city_id=' + encodeURIComponent(cityId) : '';
      inflight[key] = fetch('/api/public/trainer-showcase' + q, { headers: { Accept: 'application/json' } })
        .then(function (r) {
          if (!r.ok) throw new Error('showcase ' + r.status);
          return r.json();
        })
        .then(function (d) {
          var items = (d && Array.isArray(d.items)) ? d.items : [];
          memory[key] = items;
          writeStored(key, items);
          delete inflight[key];
          return items;
        }, function (e) {
          delete inflight[key];
          throw e;
        });
    }
    return inflight[key];
  }

  function el(target) {
    if (!target) return null;
    return typeof target === 'string' ? global.document.querySelector(target) : target;
  }

  function hide(target) {
    var host = el(target);
    if (!host) return;
    host.hidden = true;
    host.innerHTML = '';
  }

  function render(b) {
    var esc = M.esc;
    var faces = b.faces.map(function (f) {
      return f.photo
        ? '<img src="' + esc(f.photo) + '" alt="" width="34" height="34" loading="lazy" decoding="async" data-lb-initial="' + esc(f.initial) + '">'
        : '<span class="lb-learn__mono" aria-hidden="true">' + esc(f.initial) + '</span>';
    }).join('');
    var chips = b.chips.length
      ? '<nav class="lb-learn__chips" aria-label="Направления">' + b.chips.map(function (c) {
        return '<a href="' + esc(c.href) + '" data-lb-go>' + esc(c.label) + '</a>';
      }).join('') + '</nav>'
      : '';
    return '<section class="lb-learn">' +
      '<div class="lb-learn__faces">' + faces + '<span class="lb-learn__n">' + esc(b.countText) + '</span></div>' +
      '<h2 class="lb-learn__t">' + esc(b.title) + '</h2>' +
      (b.line ? '<p class="lb-learn__line">' + esc(b.line) + '</p>' : '') + chips +
      '<a class="lb-learn__go" href="' + esc(b.href) + '" data-lb-go><span>' + esc(b.button) + '</span><span aria-hidden="true">→</span></a>' +
      '</section>';
  }

  function bind(host) {
    if (host.__lbBound) return;
    host.__lbBound = true;
    host.addEventListener('click', function (ev) {
      var a = ev.target && ev.target.closest ? ev.target.closest('a[data-lb-go]') : null;
      if (!a) return;
      ev.preventDefault();
      var to = a.getAttribute('href');
      if (global.ClientShell && typeof global.ClientShell.navigate === 'function') global.ClientShell.navigate(to);
      else global.location.href = to;
    });
    // Нет фото (битая ссылка) — буква, как у тренера без фото.
    host.addEventListener('error', function (ev) {
      var img = ev.target;
      if (!img || img.tagName !== 'IMG' || !img.hasAttribute('data-lb-initial')) return;
      var mono = global.document.createElement('span');
      mono.className = 'lb-learn__mono';
      mono.setAttribute('aria-hidden', 'true');
      mono.textContent = img.getAttribute('data-lb-initial');
      img.replaceWith(mono);
    }, true);
  }

  function paint(target, items, spec) {
    var host = el(target);
    if (!host) return false;
    var b = L.build(items, spec.place, { cityId: spec.cityId, arenaId: spec.arenaId });
    if (!b) {
      hide(host);
      return false;
    }
    var html = render(b);
    if (host.getAttribute('data-lb-sig') !== html || host.hidden) {
      host.innerHTML = html;
      host.setAttribute('data-lb-sig', html);
    }
    host.hidden = false;
    bind(host);
    return true;
  }

  /**
   * Показать блок в target (если по данным есть что показать). Из кеша — сразу, иначе после запроса;
   * ошибка загрузки — блока нет. Элемент ищем заново при отрисовке: экран мог перерисоваться.
   */
  function mount(target, spec) {
    spec = spec || {};
    var have = cached(spec.cityId);
    if (have) {
      paint(target, have, spec);
      return Promise.resolve();
    }
    return load(spec.cityId).then(function (items) {
      paint(target, items, spec);
    }, function () {
      hide(target);
    });
  }

  /** Город клиента — для экранов, где его нет под рукой («Мои записи»). */
  function clientCityId() {
    var tg = global.Telegram && global.Telegram.WebApp;
    var initData = (tg && tg.initData) || '';
    if (!initData) return Promise.resolve(null);
    return fetch('/api/webapp/client/session', { headers: { Accept: 'application/json', 'X-Telegram-Init-Data': initData } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { return s && s.city_id ? Number(s.city_id) : null; })
      .catch(function () { return null; });
  }

  global.LearnBlock = { mount: mount, hide: hide, clientCityId: clientCityId };
})(typeof window !== 'undefined' ? window : globalThis);
