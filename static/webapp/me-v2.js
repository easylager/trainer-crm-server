/* TASK-449 (этап 4B): вкладка «Я» v2 за флагом redesign_s4. */
(function () {
  'use strict';

  var root = typeof window !== 'undefined' ? window : globalThis;
  var doc = root.document;
  var page = doc && doc.getElementById('mv2Page');
  if (!page) return;

  var CACHE_KEY_PREFIX = 'mv2_screen_v1:';
  var CACHE_TTL = 24 * 3600 * 1000;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function isObj(v) { return v && typeof v === 'object' && !Array.isArray(v); }
  function text(v) { return typeof v === 'string' && v.trim() ? v.trim() : ''; }
  function shell() { return root.ClientShell || null; }
  function navigate(href) {
    var sh = shell();
    if (sh && typeof sh.navigate === 'function') { sh.navigate(href); return; }
    root.location.href = href;
  }
  function tgId() {
    var u = root.Telegram && root.Telegram.WebApp && root.Telegram.WebApp.initDataUnsafe;
    return u && u.user && u.user.id ? String(u.user.id) : '0';
  }
  function profileId() {
    var sh = shell();
    var p = sh && sh.activeProfileId ? sh.activeProfileId() : null;
    return p ? String(p) : '0';
  }
  function s3on() {
    try {
      var f = JSON.parse(root.localStorage.getItem('cw_ui_flags_v1') || 'null');
      return !!(f && f.redesign_s4);
    } catch (e) { return false; }
  }
  function s5on() {
    try {
      var f = JSON.parse(root.localStorage.getItem('cw_ui_flags_v1') || 'null');
      return !!(f && f.redesign_s5);
    } catch (e) { return false; }
  }

  /* ---- screen cache (как в ice-v2) ---- */
  function cacheKey() { return CACHE_KEY_PREFIX + tgId() + ':' + profileId(); }
  function cacheRead() {
    if (!s3on()) return null;
    try {
      var raw = root.localStorage.getItem(cacheKey());
      if (!raw) return null;
      var e = JSON.parse(raw);
      if (!e || e.v !== 1 || !e.data) return null;
      if (Date.now() - e.at > CACHE_TTL) return null;
      return e;
    } catch (e2) { return null; }
  }
  function cacheWrite(data) {
    if (!s3on()) return;
    try {
      var body = JSON.stringify({ v: 1, at: Date.now(), data: data });
      if (body.length > 150 * 1024) return;
      root.localStorage.setItem(cacheKey(), body);
    } catch (e) {
      try {
        Object.keys(root.localStorage).forEach(function (k) {
          if (k.indexOf(CACHE_KEY_PREFIX) === 0) root.localStorage.removeItem(k);
        });
      } catch (e2) {}
    }
  }

  function api(path, opts) {
    opts = opts || {};
    var url = path.charAt(0) === '/' && path.indexOf('/api') !== 0 ? '/api/webapp' + path : path;
    var headers = { 'X-Telegram-Init-Data': (root.Telegram && root.Telegram.WebApp && root.Telegram.WebApp.initData) || '' };
    if (opts.headers) for (var k in opts.headers) headers[k] = opts.headers[k];
    var init = { method: opts.method || 'GET', headers: headers, cache: 'no-store' };
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body);
    }
    return fetch(url, init).then(function (r) {
      if (!r.ok) throw new Error('api ' + r.status);
      return r.json();
    });
  }

  /* ---- блоки ---- */
  function headHtml(d) {
    var u = root.Telegram && root.Telegram.WebApp && root.Telegram.WebApp.initDataUnsafe;
    var avaUrl = d.avatar_url || (u && u.user && u.user.photo_url) || '';
    var ava = avaUrl
      ? '<img src="' + esc(avaUrl) + '" alt="" width="56" height="56">'
      : esc((d.initial || (d.name || 'Я')[0] || 'Я').toUpperCase());
    var sub = [d.city, d.joined_label].filter(Boolean).map(esc).join(' · ');
    return '<div class="mv2-head">' +
      '<div class="mv2-head__ava">' + ava + '</div>' +
      '<div><button type="button" class="mv2-head__name" id="mv2Name">' + esc(d.name || 'Я') + '</button>' +
      (sub ? '<div class="mv2-head__sub">' + sub + '</div>' : '') +
      '</div></div>';
  }

  function passHtml(p) {
    if (!isObj(p)) return '';
    var pct = p.total ? Math.round((p.left / p.total) * 100) : 0;
    var gen = null;
    if (root.RuPersonName && typeof root.RuPersonName.inflectPersonName === 'function' && p.trainer_name) {
      var tp = String(p.trainer_name).trim().split(/\s+/);
      gen = root.RuPersonName.inflectPersonName(tp[0], tp.slice(1).join(' '), 'gen') || null;
    }
    var sub = gen
      ? 'Абонемент у ' + gen + (p.expires_label ? ' · ' + p.expires_label : '')
      : 'Абонемент' + (p.trainer_name ? ' · ' + p.trainer_name : '') + (p.expires_label ? ' · ' + p.expires_label : '');
    var photo = p.trainer_photo_key ? '/api/public/photos/' + encodeURIComponent(p.trainer_photo_key) : '';
    return '<section class="mv2-card mv2-pass">' +
      '<div class="mv2-pass__top">' +
        '<div class="mv2-pass__ring" style="--mv2-p:' + pct + '%"><b>' + esc(p.left) + '</b><span>из ' + esc(p.total) + '</span></div>' +
        '<div><div class="mv2-pass__t">Осталось ' + esc(p.left) + ' ' + plural(p.left, 'занятие', 'занятия', 'занятий') + '</div>' +
        '<div class="mv2-pass__s">' + esc(sub) + '</div></div>' +
      '</div>' +
      '<div class="mv2-pass__divider"></div>' +
      '<div class="mv2-pass__tr">' +
        (photo ? '<img src="' + photo + '" alt="" width="40" height="40" loading="lazy" onerror="this.remove()">' : '') +
        '<div><div class="mv2-pass__tr-n">' + esc(p.trainer_name) + '</div>' +
        '<div class="mv2-pass__tr-w" id="mv2PassWindow">ближайшее окно уточняем…</div></div>' +
        '<a class="mv2-pass__book ga-press" href="' + esc(p.book_href || '#') + '" data-nav="' + esc(p.book_href || '') + '">Записаться</a>' +
      '</div></section>';
  }

  function plural(n, one, few, many) {
    n = Math.abs(n) % 100; var d = n % 10;
    if (n > 10 && n < 20) return many;
    if (d > 1 && d < 5) return few;
    if (d === 1) return one;
    return many;
  }

  /* ---- TASK-451: значки волны 1. Разметка и логика — общий модуль
     badge-collection.js (window.GlideBadgeShelf): тот же код рисует полку
     и на старом «Я» (PDEC-040, батч C). Флаг — свой у каждой страницы. ---- */
  function badgeList(d) { return Array.isArray(d && d.badges) ? d.badges : []; }
  function badgesHtml(d) {
    if (!s5on() || !root.GlideBadgeShelf) return '';
    return root.GlideBadgeShelf.shelfHtml(badgeList(d));
  }
  function nextStreakBadge(list) {
    return root.GlideBadgeShelf ? root.GlideBadgeShelf.nextStreakBadge(list) : null;
  }
  /* Тап по открытому значку — лист вручения ещё раз (можно поделиться). */
  function wireBadgeTiles(scope, d) {
    if (root.GlideBadgeShelf) root.GlideBadgeShelf.wireShelf(scope, badgeList(d));
  }

  function seasonHtml(season, d) {
    if (!season) return '';
    if (!season.season_days) {
      return '<section class="mv2-card mv2-season">' +
        '<div class="mv2-season__goal">Сезон ещё не начат</div>' +
        '<div class="mv2-season__hint">Отметься «Я здесь» на сеансе — это будет первый раз</div>' +
        (season.next_line ? '<div class="mv2-season__hint">' + esc(season.next_line) + '</div>' : '') +
        '</section>';
    }
    var weeks = Math.min(10, Math.max(0, season.streak_weeks || 0));
    var bar = '';
    for (var i = 0; i < 10; i++) bar += '<i class="' + (i < weeks ? 'on' : '') + '"></i>';
    /* TASK-451: «до «Крепкого льда» 2 недели» под полоской или «Серия оборвалась». */
    var tail = '';
    if (weeks) {
      var nb = s5on() && isObj(d) ? nextStreakBadge(d.badges) : null;
      if (nb && nb.progress && nb.progress.total > nb.progress.done) {
        var left = nb.progress.total - nb.progress.done;
        tail = '<div class="mv2-season__hint">До «' + esc(nb.name_gen || nb.name) + '» — ' + left + ' ' +
          plural(left, 'неделя', 'недели', 'недель') + '</div>';
      }
    } else if (season.season_days > 0) {
      tail = '<div class="mv2-season__hint mv2-season__hint--broken">Серия оборвалась · начни новую</div>';
    }
    return '<section class="mv2-card mv2-season">' +
      '<div class="mv2-season__lbl">Сезон</div>' +
      '<div class="mv2-season__n">' + esc(season.season_days) + ' ' + plural(season.season_days, 'раз', 'раза', 'раз') + ' на льду</div>' +
      (weeks ? '<div class="mv2-season__streak">Серия ' + weeks + ' ' + plural(weeks, 'неделя', 'недели', 'недель') + ' подряд</div>' +
        '<div class="mv2-season__bar">' + bar + '</div>' : '') +
      tail +
      '</section>';
  }

  function rinkHtml(h) {
    if (!isObj(h)) return '';
    var img = isObj(h.photo) && h.photo.card
      ? '<img class="mv2-rink__img" src="' + esc(h.photo.card) + '" alt="" fetchpriority="high">'
      : '';
    var times = '';
    if (Array.isArray(h.today_times) && h.today_times.length) {
      times = 'Сегодня ещё ' + h.today_times.map(esc).join(' · ');
    } else if (h.tomorrow_first) {
      times = 'Завтра с ' + esc(h.tomorrow_first);
    }
    return '<a class="mv2-rink ga-press" href="' + esc(h.href || '#') + '" data-nav="' + esc(h.href || '') + '" id="mv2Rink">' +
      img + '<div class="mv2-rink__grad"></div>' +
      '<span class="mv2-rink__chip"><i>●</i>Мой каток</span>' +
      '<button type="button" class="mv2-rink__change" id="mv2RinkChange">Сменить</button>' +
      '<div class="mv2-rink__bottom"><div class="mv2-rink__name">' + esc(h.name) + '</div>' +
      (times ? '<div class="mv2-rink__times">' + times + '</div>' : '') +
      '</div></a>';
  }

  function clubHtml(c) {
    if (!isObj(c)) return '';
    var logo = c.logo ? '<img class="mv2-row__logo" src="' + esc(c.logo) + '" alt="" width="32" height="32" loading="lazy">' : '';
    var next = isObj(c.next_match) && c.next_match.label ? c.next_match.label : '';
    return '<a class="mv2-row ga-press" href="kto-kogo" data-nav="kto-kogo">' + logo +
      '<div class="mv2-row__main"><div class="mv2-row__t">Болею за ' + esc(c.name || '') + '</div>' +
      (next ? '<div class="mv2-row__s">' + esc(next) + '</div>' : '') +
      '</div><svg class="mv2-row__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg></a>';
  }

  function pickRinkHtml() {
    return '<button type="button" class="mv2-row ga-press" id="mv2RinkPick">' +
      '<div class="mv2-row__main"><div class="mv2-row__t">Выбрать каток</div>' +
      '<div class="mv2-row__s">покажем расписание рядом</div></div>' +
      '<svg class="mv2-row__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg></button>';
  }

  function companiesHtml(d) {
    if (!s5on()) return '';
    var list = Array.isArray(d.companies) ? d.companies : [];
    if (!list.length) return '';
    var rows = list.map(function (c) {
      var names = (c.going_names || []).slice(0, 3);
      var avas = names.map(function (n) {
        return '<span class="mv2-comp__ava">' + esc(String(n || '?').trim().charAt(0).toUpperCase()) + '</span>';
      }).join('');
      var who = c.my_status === 'organizer' ? 'организатор' : 'ты идёшь';
      var sub = [c.day_label, c.arena_name + (c.starts_local ? ', ' + c.starts_local : ''), who].filter(Boolean).join(' · ');
      var title = names.length
        ? namesJoin(names) + (c.going_count > names.length ? ' и ещё ' + (c.going_count - names.length) : '')
        : (c.name || 'Компания');
      return '<a class="mv2-row mv2-row--quiet ga-press" href="' + esc(c.page_url) + '" data-company="' + esc(c.page_url) + '">' +
        '<span class="mv2-comp__avas">' + avas + '</span>' +
        '<div class="mv2-row__main"><div class="mv2-row__t">' + esc(title) + '</div>' +
        '<div class="mv2-row__s">' + esc(sub) + '</div></div>' +
        '<svg class="mv2-row__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg></a>';
    }).join('');
    return '<section class="mv2-sec"><h2 class="mv2-sec__h">Мои компании</h2><div class="mv2-card mv2-set">' + rows + '</div></section>';
  }

  /* «Аня и Дима», «Аня, Дима и Света» — последнее имя через «и». */
  function namesJoin(arr) {
    return arr.length > 1 ? arr.slice(0, -1).join(', ') + ' и ' + arr[arr.length - 1] : (arr[0] || '');
  }

  function tilesHtml(d) {
    var fam = isObj(d.rows) && isObj(d.rows.family) ? d.rows.family : {};
    var famLine = text(fam.value) || 'Добавить ребёнка';
    var saved = isObj(d.saved_detail) && d.saved_detail.line ? d.saved_detail.line
      : (isObj(d.rows) && isObj(d.rows.saved) && d.rows.saved.count ? String(d.rows.saved.count) : 'Пока пусто');
    return '<div class="mv2-tiles">' +
      '<a class="mv2-tile ga-press" href="client-family" data-nav="client-family"><div class="mv2-tile__t">Семья</div><div class="mv2-tile__s">' + esc(famLine) + '</div></a>' +
      '<a class="mv2-tile ga-press" href="client-saved-trainers" data-nav="client-saved-trainers"><div class="mv2-tile__t">Сохранённое</div><div class="mv2-tile__s">' + esc(saved || 'Пока пусто') + '</div></a>' +
      '</div>';
  }

  function settingsHtml(d) {
    var toggle = '<button type="button" class="mv2-switch" id="mv2Remind" role="switch" aria-checked="false" aria-label="Сообщения в чате"></button>';
    return '<section class="mv2-card mv2-set">' +
      '<div class="mv2-row mv2-row--quiet"><div class="mv2-row__main"><div class="mv2-row__t">Сообщения в чате</div>' +
      '<div class="mv2-row__s">игра, серия, друзья</div></div>' + toggle + '</div>' +
      '<a class="mv2-row mv2-row--quiet ga-press" href="client-stats" data-nav="client-stats"><div class="mv2-row__main"><div class="mv2-row__t">История</div><div class="mv2-row__s">абонементы и записи</div></div>' +
      '<svg class="mv2-row__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg></a>' +
      '<a class="mv2-row mv2-row--quiet ga-press" href="client-settings" data-nav="client-settings"><div class="mv2-row__main"><div class="mv2-row__t">Город и уведомления</div></div>' +
      '<svg class="mv2-row__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg></a>' +
      '<a class="mv2-row mv2-row--quiet ga-press" href="client-support" data-nav="client-support"><div class="mv2-row__main"><div class="mv2-row__t">Написать нам</div></div>' +
      '<svg class="mv2-row__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg></a>' +
      '</section>';
  }

  function render(d, season) {
    var html = headHtml(d) +
      passHtml(d['pass']) +
      seasonHtml(season, d) +
      badgesHtml(d) +
      (isObj(d.home_arena) && d.home_arena.id ? rinkHtml(d.home_arena) : pickRinkHtml()) +
      clubHtml(d.club) +
      companiesHtml(d) +
      tilesHtml(d) +
      settingsHtml(d);
    page.innerHTML = html;
    wire(d);
  }

  function wire(d) {
    var nameBtn = doc.getElementById('mv2Name');
    if (nameBtn) nameBtn.addEventListener('click', function () {
      if (root.ClientNameSheet && root.ClientNameSheet.open) {
        root.ClientNameSheet.open({ current: d.name, onSaved: function () { load(); } });
      }
    });
    var change = doc.getElementById('mv2RinkChange');
    if (change) change.addEventListener('click', function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      openRinkSheet(d);
    });
    var pick = doc.getElementById('mv2RinkPick');
    if (pick) pick.addEventListener('click', function () { openRinkSheet(d); });
    /* «Все значки» → коллекция + тапы по плиткам — внутри wireShelf общего модуля. */
    wireBadgeTiles(page, d);
    var sw = doc.getElementById('mv2Remind');
    if (sw) {
      api('/client/hockey/remind').then(function (r) {
        sw.setAttribute('aria-checked', r && r.on ? 'true' : 'false');
      }).catch(function () {});
      sw.addEventListener('click', function () {
        var on = sw.getAttribute('aria-checked') !== 'true';
        sw.setAttribute('aria-checked', on ? 'true' : 'false');
        api('/client/hockey/remind', { method: 'PUT', body: { on: on } }).catch(function () {
          sw.setAttribute('aria-checked', on ? 'false' : 'true');
        });
      });
    }
    page.addEventListener('click', function (ev) {
      var cb = ev.target.closest && ev.target.closest('[data-company]');
      if (cb) {
        ev.preventDefault();
        var cu = cb.getAttribute('data-company');
        var tw = root.Telegram && root.Telegram.WebApp;
        if (cu && tw && tw.openTelegramLink) { tw.openTelegramLink(cu); return; }
        if (cu) { root.open(cu, '_blank'); }
        return;
      }
      var a = ev.target.closest && ev.target.closest('[data-nav]');
      if (!a) return;
      var href = a.getAttribute('data-nav');
      if (!href || href === '#') return;
      ev.preventDefault();
      navigate(href);
    });
    // ближайшее окно тренера — после первого paint
    var p = d['pass'];
    if (p && p.trainer_id) {
      setTimeout(function () {
        api('/client/slots?trainer_id=' + encodeURIComponent(p.trainer_id)).then(function (r) {
          var el = doc.getElementById('mv2PassWindow');
          if (!el) return;
          var s = r && (r.next || (r.slots && r.slots[0]));
          if (s && s.label) el.textContent = 'ближайшее окно ' + s.label;
          else el.textContent = 'окон пока нет';
        }).catch(function () {
          var el = doc.getElementById('mv2PassWindow');
          if (el) el.textContent = '';
        });
      }, 0);
    }
  }

  function openRinkSheet(d) {
    if (root.ClientRinkSheet && root.ClientRinkSheet.open) {
      root.ClientRinkSheet.open({
        currentId: isObj(d.home_arena) ? d.home_arena.id : null,
        onSaved: function () { load(); }
      });
    }
  }

  var lastData = null;

  function load() {
    var headers = {};
    var pid = profileId();
    if (pid !== '0') headers['X-Profile-Id'] = pid;
    var seasonP = s5on()
      ? api('/client/checkins/state?session_ids=').catch(function () { return null; })
      : Promise.resolve(null);
    return Promise.all([
      api('/api/webapp/client/me', { headers: headers }),
      seasonP
    ]).then(function (rr) {
      var d = rr[0], st = rr[1];
      var season = null;
      var me = st && isObj(st.me) ? st.me : null;
      if (s5on() && me) {
        season = { season_days: me.season_days || 0, streak_weeks: me.streak_weeks || 0, next_line: me.next_line || null };
      }
      lastData = { d: d, season: season };
      render(d, season);
      cacheWrite(lastData);
      var sh = shell();
      if (sh && typeof sh.contentShown === 'function') sh.contentShown({ src: 'net' });
    });
  }

  /* ---- boot ---- */
  var cached = cacheRead();
  if (cached && cached.data && cached.data.d) {
    render(cached.data.d, cached.data.season);
    var sh = shell();
    if (sh && typeof sh.contentShown === 'function') sh.contentShown({ src: 'cache' });
  }
  load().catch(function () {
    if (!cached) {
      page.innerHTML = '<div class="mv2-card"><div class="mv2-row__t">Не удалось загрузить</div>' +
        '<div class="mv2-row__s">Проверьте соединение и откройте ещё раз</div></div>';
    }
  });
})();
