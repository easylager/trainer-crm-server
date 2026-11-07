/**
 * Витрина тренеров, карточка тренера и запись — Mini App (TASK-357, дизайн PDEC-033 v2).
 *
 * Экраны: 1 витрина · 2 тренер · 3 другое время · 4/5 запись (новый / постоянный) · 6/6б отправлено ·
 * 7 время заняли (шторка) · 8 нет времени · 9 без онлайн-записи · 10 заявка (шторка) · 11 заявка отправлена.
 *
 * Логика записи — существующие API и BookingClient: тариф прошлой записи (priceVariantHint),
 * ключ идемпотентности, профили семьи (X-Profile-Id), абонементы (/client/passes), блок «Разрешить».
 * Тело записи собирается в одном месте — buildBookingBody() → BookingClient.buildBookingPayload.
 *
 * Адрес: trainers?tab=s-nulya&arena_id=3&city_id=1 · &trainer_id=9 · &slot_id=55 (сразу запись).
 */
(function () {
  'use strict';

  var M = window.TrainerShowcaseModel;
  var BC = window.BookingClient;
  var RuName = window.RuPersonName;
  var esc = M.esc;
  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  var initData = BC.getInitData();
  var qs = new URLSearchParams(location.search);
  var appEl = document.getElementById('app');
  var sheetEl = document.getElementById('sheet');

  var S = {
    cityId: num(qs.get('city_id')),
    tab: M.direction(qs.get('tab')) ? qs.get('tab') : 'all',
    arenaId: num(qs.get('arena_id')),
    items: null,
    loadError: false,
    session: null,
    profiles: [],
    passes: {},
    stack: [],
    view: 'list',
    trainer: null,
    dirKey: null,
    serviceId: null,
    slots: null,
    slotsError: false,
    weekStart: null,
    day: null,
    saved: false,
    book: null,
    sent: null,
    req: null,
    todayIso: minskToday(),
  };

  function num(v) {
    var n = Number(v);
    return isFinite(n) && n > 0 ? n : null;
  }

  function minskToday() {
    try {
      return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Minsk', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    } catch (e) {
      return new Date().toISOString().slice(0, 10);
    }
  }

  /* ── API ─────────────────────────────────────────────────────────── */

  function withInit(path) {
    if (!initData) return path;
    return path + (path.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = { Accept: 'application/json' };
    if (initData) headers['X-Telegram-Init-Data'] = initData;
    if (opts.profileId != null) headers['X-Profile-Id'] = String(opts.profileId);
    if (opts.body) headers['Content-Type'] = 'application/json';
    return fetch(withInit(path), {
      method: opts.method || 'GET',
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      return r.text().then(function (t) {
        var data = null;
        try { data = JSON.parse(t || 'null'); } catch (e) { data = null; }
        if (!r.ok) {
          var err = new Error((data && typeof data.detail === 'string' && data.detail) || ('HTTP ' + r.status));
          err.status = r.status;
          throw err;
        }
        return data;
      });
    });
  }

  function loadSession() {
    if (!initData) return Promise.resolve(null);
    return BC.fetchClientSession(num(qs.get('trainer_id')), initData).catch(function () { return null; });
  }

  function loadProfiles() {
    if (!initData) return Promise.resolve([]);
    return api('/api/webapp/client/profiles')
      .then(function (d) {
        S.defaultProfileId = d && d.default_profile_id;
        return (d && d.items) || [];
      })
      .catch(function () { return []; });
  }

  function loadShowcase() {
    var q = S.cityId ? '?city_id=' + S.cityId : '';
    return fetch('/api/public/trainer-showcase' + q, { headers: { Accept: 'application/json' } }).then(function (r) {
      if (!r.ok) throw new Error('showcase ' + r.status);
      return r.json();
    });
  }

  /** Тренер не из выдачи города (личная ссылка, другой город) — та же форма из карточки каталога. */
  function loadTrainerFallback(id) {
    var url = initData ? '/api/webapp/client/catalog-trainer/' + id : '/api/public/trainers/' + id;
    return api(url).then(function (t) {
      var p = t.profile || {};
      var name = ((p.first_name || '') + ' ' + (p.last_name || '')).trim() || 'Тренер';
      var photo = (t.photos || [])[0] || {};
      return {
        id: t.id,
        name: name,
        first_name: (p.first_name || '').trim() || name,
        initial: (name.match(/\p{L}/u) || ['Т'])[0].toUpperCase(),
        photo_url: photo.url || photo.list_url || null,
        experience_years: p.experience_years,
        description: (p.description || '').trim(),
        education: (p.education || '').trim(),
        rating_avg: p.rating_avg,
        rating_count: p.rating_count || 0,
        session_duration_minutes: p.session_duration_minutes,
        glide_since: null,
        can_book: !!t.can_book,
        contact_url: t.contact_telegram_url || null,
        services: (t.services || []).map(function (s) {
          return {
            service_id: s.service_id, service_name: s.service_name, is_public: true, is_online: !!s.is_online,
            price_cents: s.price_cents, currency_code: s.currency_code || 'BYN', description: s.description,
            price_tiers: s.price_tiers || [],
          };
        }),
        arenas: (t.arena_ids || []).map(function (id, i) { return { id: id, name: (t.arena_names || [])[i] || '' }; }).filter(function (a) { return a.name; }),
        windows: [],
      };
    });
  }

  function loadSlots() {
    var t = S.trainer;
    if (!t) return Promise.resolve();
    if (!t.can_book) {
      S.slots = [];
      return Promise.resolve();
    }
    if (!initData) {
      // Вне Telegram записи нет — показываем окна витрины, запись попросит открыть в Telegram.
      S.slots = (t.windows || []).map(function (w) { return decorateSlot(M.windowToSlot(w)); });
      return Promise.resolve();
    }
    S.slots = null;
    S.slotsError = false;
    var svc = currentService();
    return BC.fetchClientSlots({ trainerId: t.id, serviceId: svc ? svc.service_id : null, initData: initData })
      .then(function (d) {
        S.slots = M.sortSlots((d && d.slots) || []).map(decorateSlot);
      })
      .catch(function () {
        S.slots = [];
        S.slotsError = true;
      });
  }

  function decorateSlot(s) {
    var a = arenaById(s.arena_id);
    if (a && !s.arena_name) s.arena_name = a.name;
    return s;
  }

  function arenaById(id) {
    var list = (S.trainer && S.trainer.arenas) || [];
    for (var i = 0; i < list.length; i++) if (Number(list[i].id) === Number(id)) return list[i];
    return null;
  }

  function loadPasses() {
    if (!initData || !S.profiles.length) return Promise.resolve();
    return Promise.all(
      S.profiles.map(function (p) {
        return api('/api/webapp/client/passes', { profileId: p.client_id })
          .then(function (d) { S.passes[p.client_id] = (d && d.items) || []; })
          .catch(function () { S.passes[p.client_id] = []; });
      })
    );
  }

  /* ── Навигация: «‹ Назад» на странице (BackButton продукт прячет); фильтры и место в списке сохраняются ── */

  function go(view, data) {
    S.stack.push({ view: S.view, scroll: window.scrollY || 0 });
    S.view = view;
    try { history.pushState({ tsw: S.stack.length }, ''); } catch (e) { /* */ }
    render();
    window.scrollTo(0, 0);
    return data;
  }

  function back() {
    closeSheet();
    var prev = S.stack.pop();
    if (!prev) {
      if (S.view !== 'list') {
        S.view = 'list';
        render();
        return;
      }
      if (window.ClientShell && typeof window.ClientShell.navigate === 'function') window.ClientShell.navigate('client-home');
      return;
    }
    S.view = prev.view;
    render();
    window.scrollTo(0, prev.scroll || 0);
  }

  window.addEventListener('popstate', function () {
    back();
  });

  function navigate(path) {
    if (window.ClientShell && typeof window.ClientShell.navigate === 'function') window.ClientShell.navigate(path);
    else location.href = withInit(path);
  }

  function openLink(url) {
    if (!url) return;
    var abs = new URL(url, location.href).href;
    if (tg && typeof tg.openTelegramLink === 'function' && /^https:\/\/t\.me\//.test(abs)) {
      try { tg.openTelegramLink(abs); return; } catch (e) { /* */ }
    }
    if (tg && typeof tg.openLink === 'function') {
      try { tg.openLink(abs); return; } catch (e) { /* */ }
    }
    window.open(abs, '_blank');
  }

  /* ── Общие куски ─────────────────────────────────────────────────── */

  function backBtn(label) {
    return '<button type="button" class="back" data-act="back">‹ ' + esc(label) + '</button>';
  }

  function trainerById(id) {
    var list = S.items || [];
    for (var i = 0; i < list.length; i++) if (Number(list[i].id) === Number(id)) return list[i];
    return null;
  }

  function serviceList(t, key) {
    var svcs = key ? M.servicesInDirection(t, key) : [];
    if (!svcs.length) svcs = (t.services || []).slice();
    return svcs;
  }

  function currentService() {
    var t = S.trainer;
    if (!t) return null;
    var svcs = serviceList(t, S.dirKey);
    if (S.serviceId != null) {
      var found = (t.services || []).filter(function (s) { return Number(s.service_id) === Number(S.serviceId); })[0];
      if (found) return found;
    }
    return svcs.length === 1 ? svcs[0] : null;
  }

  function slotLabel(slot, withArena) {
    var small = M.daySmall(slot.slot_date, S.todayIso);
    if (withArena && slot.arena_name) small += ' · ' + slot.arena_name;
    if (slot.capacity > 1 && slot.spots_left != null) small += ' · осталось ' + M.word(slot.spots_left, 'место', 'места', 'мест');
    return '<button type="button" data-act="slot" data-slot="' + esc(slot.id) + '">' + esc(String(slot.start_time).slice(0, 5)) + '<small>' + esc(small) + '</small></button>';
  }

  function heroHtml(t, sub) {
    var badge = M.experienceBadge(t.experience_years);
    if (!t.photo_url) {
      return '<div class="noph"><i>' + esc(t.initial || 'Т') + '</i><div><b>' + esc(t.name) + '</b>' +
        (sub ? '<span class="mut">' + esc(sub) + '</span>' : '') + (badge ? '<span class="mut"> · ' + esc(badge) + '</span>' : '') + '</div></div>';
    }
    return '<div class="hro"><img src="' + esc(t.photo_url) + '" alt="">' + (badge ? '<span class="badge">' + esc(badge) + '</span>' : '') +
      '<div class="t"><b>' + esc(t.name) + '</b>' + (sub ? '<span>' + esc(sub) + '</span>' : '') + '</div></div>';
  }

  function trainerSubLine(t) {
    var parts = [];
    var r = M.ratingLine(t.rating_avg, t.rating_count);
    if (r) parts.push(r);
    var g = M.glideSince(t.glide_since);
    if (g) parts.push(parts.length ? g.charAt(0).toLowerCase() + g.slice(1) : g);
    if (!parts.length) {
      var dirs = M.trainerDirections(t).map(function (d) { return d.title; });
      if (dirs.length) parts.push(dirs.join(' · '));
    }
    return parts.join(' · ');
  }

  /* ── 1 · Витрина ─────────────────────────────────────────────────── */

  function renderList() {
    if (S.loadError) {
      return '<div class="bd"><h1 class="h1a">Учиться с тренером</h1><div class="card"><p>Не удалось загрузить тренеров.</p>' +
        '<button type="button" class="sec2" data-act="retry">Повторить</button></div></div>';
    }
    if (!S.items) return '<div class="bd"><div class="skel"></div><div class="skel"></div></div>';
    var all = M.visibleTrainers(S.items, 'all', null);
    var solo = all.length <= 1;
    var key = solo ? 'all' : S.tab;
    var arenaId = solo ? null : S.arenaId;
    var counts = M.tabCounts(S.items, arenaId);
    var list = M.visibleTrainers(S.items, key, arenaId);
    var dir = M.direction(key);
    var h = '<div class="bd"><h1 class="h1a">Учиться с тренером</h1>';
    if (!solo) {
      h += '<div class="tabsA" role="tablist">' + M.DIRECTIONS.filter(function (d) {
        return d.key === 'all' || d.key === key || counts[d.key] > 0;
      }).map(function (d) {
        return '<button type="button" role="tab" data-act="tab" data-key="' + d.key + '" aria-selected="' + (d.key === key) + '">' +
          esc(d.title) + '<b>' + counts[d.key] + '</b></button>';
      }).join('') + '</div>';
    }
    h += '<span class="mut">' + esc(dir.lead) + '</span>';
    var minPrice = M.minPriceOf(list);
    var facts = [M.word(list.length, 'тренер', 'тренера', 'тренеров')];
    if (minPrice) facts.push('от ' + M.formatMoney(minPrice.cents, minPrice.currency));
    facts.push('оплата на месте');
    var arenas = M.arenaOptions(S.items, key);
    var arenaName = '';
    if (arenaId) {
      var found = M.arenaOptions(S.items, 'all').filter(function (a) { return Number(a.id) === Number(arenaId); })[0];
      arenaName = found ? found.name : 'Каток';
    }
    var arenaBtn = solo || (arenas.length < 2 && !arenaId) ? '' :
      '<button type="button" class="f2" data-act="arena-sheet">' + (arenaId ? esc(arenaName) + ' ✕' : 'Все катки ▾') + '</button>';
    h += '<div class="facts"><span>' + (list.length ? esc(facts.join(' · ')) : '') + '</span>' + arenaBtn + '</div>';
    if (!list.length) {
      h += '<div class="card"><p>' + esc((arenaName || 'Здесь') + ': тренеров «' + dir.title + '» здесь пока нет') + '</p>' +
        (key !== 'all' && arenaId ? '<button type="button" class="sec2" data-act="tab" data-key="all">Все тренеры этого катка</button>' : '') +
        (arenaId ? '<button type="button" class="sec2" data-act="arena-clear">' + esc(dir.key === 'all' ? 'Все катки' : dir.title + ' на всех катках') + '</button>' : '') +
        '</div>';
    } else {
      h += '<span class="mut" style="font-size:12px">Сверху — тренеры с онлайн-записью, по ближайшему свободному времени.</span>';
      h += list.map(function (t) { return cardHtml(t, key, arenaId); }).join('');
    }
    return h + '</div>';
  }

  function cardHtml(t, key, arenaId) {
    var svc = M.servicesInDirection(t, key)[0] || null;
    var rating = M.ratingLine(t.rating_avg, t.rating_count);
    var badge = M.experienceBadge(t.experience_years);
    var head = t.photo_url
      ? '<div class="im"><img src="' + esc(t.photo_url) + '" alt="" loading="lazy">' + (badge ? '<span class="badge">' + esc(badge) + '</span>' : '') +
        '<div class="nm"><b>' + esc(t.name) + '</b>' + (rating ? '<span>' + esc(rating) + '</span>' : '') + '</div></div>'
      : '<div class="noph"><i>' + esc(t.initial || 'Т') + '</i><div><b>' + esc(t.name) + '</b><span class="mut">' +
        esc(rating || M.trainerDirections(t).map(function (d) { return d.title; }).join(' · ')) + '</span></div></div>';
    var since = M.glideSince(t.glide_since);
    var facts = M.cardFacts(t, key);
    var many = (t.arenas || []).length > 1;
    var wins = (t.windows || []).filter(function (w) { return !arenaId || Number(w.arena_id) === Number(arenaId); }).slice(0, 2);
    var times = '';
    if (t.can_book && wins.length) {
      times = wins.map(function (w) {
        var a = many ? (t.arenas.filter(function (x) { return Number(x.id) === Number(w.arena_id); })[0] || {}).name : '';
        return '<button type="button" data-act="win" data-tid="' + t.id + '" data-slot="' + w.slot_id + '">' + esc(w.time) +
          '<small>' + esc(w.day + (a ? ' · ' + a : '')) + '</small></button>';
      }).join('') + '<button type="button" class="alt" data-act="week" data-tid="' + t.id + '">Другое время</button>';
    } else if (t.contact_url) {
      times = '<button type="button" class="alt wide" data-act="write" data-tid="' + t.id + '">Написать тренеру</button>';
    }
    return '<article class="vc" data-act="trainer" data-tid="' + t.id + '">' + head + '<div class="in">' +
      (since ? '<span class="proof">' + esc(since) + '</span>' : '') +
      (facts.length ? '<dl class="facts4">' + facts.map(function (r) { return '<div><dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd></div>'; }).join('') + '</dl>' : '') +
      '<div class="price">' + M.cardPriceHtml(svc) + '</div>' +
      (times ? '<div class="times">' + times + '</div>' : '') + '</div></article>';
  }

  /* ── 2 · Тренер (8 — нет времени, 9 — без онлайн-записи) ─────────── */

  /** Тренера выбрали в витрине — источник записи «Mini App» (TASK-351), если сеанс пришёл не по ссылке. */
  function noteShowcasePick() {
    var B = window.GlideBookingSource;
    if (B && typeof B.noteInApp === 'function') B.noteInApp({ arenaId: S.arenaId, cityId: S.cityId });
  }

  function openTrainer(t, opts) {
    opts = opts || {};
    S.trainer = t;
    var dirs = M.trainerDirections(t);
    var want = opts.dirKey || (S.tab !== 'all' ? S.tab : null);
    S.dirKey = dirs.some(function (d) { return d.key === want; }) ? want : dirs.length ? dirs[0].key : null;
    S.serviceId = num(qs.get('service_id')) && Number(t.id) === num(qs.get('trainer_id')) ? num(qs.get('service_id')) : null;
    S.saved = false;
    if (opts.view !== false) go('trainer');
    return loadSlots().then(render);
  }

  function renderTrainer() {
    var t = S.trainer;
    var dirs = M.trainerDirections(t);
    var svcs = serviceList(t, S.dirKey);
    var svc = currentService();
    var h = '<div class="bd">' + backBtn(S.stack.length ? 'Тренеры' : 'Все тренеры') + heroHtml(t, trainerSubLine(t));
    h += '<div class="pc">';
    if (!t.can_book) {
      h += '<p>' + esc(M.selfBookingLine(t.first_name, RuName)) + '</p></div>';
    } else {
      if (dirs.length > 1) {
        h += '<div class="seg">' + dirs.map(function (d) {
          return '<button type="button" data-act="dir" data-key="' + d.key + '" aria-pressed="' + (d.key === S.dirKey) + '">' + esc(d.title) + '</button>';
        }).join('') + '</div>';
      }
      if (svcs.length > 1) {
        h += '<span class="lb">Какое занятие?</span><div class="svcs">' + svcs.map(function (s) {
          var dur = t.session_duration_minutes ? t.session_duration_minutes + ' мин · ' : '';
          return '<button type="button" data-act="svc" data-sid="' + s.service_id + '" aria-pressed="' + (svc && Number(svc.service_id) === Number(s.service_id)) + '">' +
            '<span>' + esc(s.service_name) + '<small>' + esc(dur) + M.cardPriceHtml(s).replace(/<\/?b>/g, '') + '</small></span></button>';
        }).join('') + '</div>';
      }
      if (svc) h += tiersHtml(svc);
      var where = svc && svc.is_online ? 'онлайн' : ((t.arenas || []).length === 1 ? t.arenas[0].name : '');
      var lb = [t.session_duration_minutes ? t.session_duration_minutes + ' мин' : '', where, 'ближайшее время'].filter(Boolean).join(' · ');
      var noTime = S.slots && !S.slots.length && !S.slotsError;
      if (!noTime) h += '<span class="lb">' + esc(lb) + '</span>';
      if (S.slots === null) h += '<span style="color:var(--a-hero-hint)">Загружаем время…</span>';
      else if (S.slots.length) {
        h += '<div class="times">' + S.slots.slice(0, 3).map(function (s) { return slotLabel(s, (t.arenas || []).length > 1); }).join('') +
          '<button type="button" class="alt" data-act="week">Другое время</button></div>';
      } else if (S.slotsError) {
        h += '<span style="color:var(--a-hero-hint)">Не удалось загрузить время.</span>';
      }
      h += '</div>';
      if (S.slots && !S.slots.length && !S.slotsError) {
        h += '<div class="card"><h4>На ближайшие 2 недели свободного времени нет</h4><p class="mut">Попросите сообщить, когда появится.</p>' +
          (initData ? '<button type="button" class="sec2" data-act="notify">Напомнить, когда появится время</button>' : '') + '</div>';
      }
      if (S.slotsError) h += '<button type="button" class="sec2" data-act="reslots">Повторить</button>';
    }
    h += whereCard(t, svc);
    if (t.description || t.education) {
      h += '<div class="card"><h4>О тренере</h4>' + (t.description ? '<p>' + esc(t.description) + '</p>' : '') +
        (t.education ? '<span class="mut">' + esc(t.education) + '</span>' : '') + '</div>';
    }
    if (svc && svc.description) h += '<div class="card"><h4>' + esc(svc.service_name) + '</h4><p>' + esc(svc.description) + '</p></div>';
    var duo = svc ? M.whoOptions(svc).duo : [];
    if (duo.length) {
      h += '<div class="card"><h4>Другие тарифы</h4>' + duo.map(function (r) {
        return '<div class="kv"><span>' + esc(r.title) + '</span><b>' + esc(M.formatMoney(r.priceCents, svc.currency_code)) + '</b></div>';
      }).join('') + '</div>';
    }
    if (initData) h += '<button type="button" class="more" data-act="save">' + (S.saved ? '♥ Тренер сохранён' : '♡ Сохранить тренера') + '</button>';
    h += '</div>';
    if (!t.can_book) {
      h += '<div class="ft col">' + (t.contact_url ? '<button type="button" class="cta" data-act="write">Написать тренеру</button>' : '') +
        (initData ? '<button type="button" class="sec2" data-act="request">Оставить заявку</button>' : '') + '</div>';
    } else if (S.slots && S.slots.length) {
      var first = S.slots[0];
      h += '<div class="ft"><button type="button" class="cta" data-act="slot" data-slot="' + esc(first.id) + '">Записаться на ' +
        esc(M.ctaDay(first.slot_date, S.todayIso) + ', ' + String(first.start_time).slice(0, 5)) + '</button>' +
        (t.contact_url ? '<button type="button" class="ico" data-act="write" aria-label="Написать тренеру"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg></button>' : '') + '</div>';
    } else if (t.contact_url) {
      h += '<div class="ft"><button type="button" class="sec2" style="flex:1" data-act="write">Написать тренеру</button></div>';
    }
    return h;
  }

  function tiersHtml(svc) {
    var single = M.whoOptions(svc).single.filter(function (r) { return r.priceCents != null; });
    if (single.length) {
      return '<div class="tiers">' + single.map(function (r) {
        return '<div><small>' + esc(r.title) + '</small><b>' + esc(M.formatMoney(r.priceCents, svc.currency_code)) + '</b></div>';
      }).join('') + '</div>';
    }
    return '<div class="tiers"><div><small>Занятие</small><b>' + M.cardPriceHtml(svc).replace(/<\/?b>/g, '') + '</b></div></div>';
  }

  function whereCard(t, svc) {
    if (svc && svc.is_online) return '<div class="card"><h4>Где проходят занятия</h4><p>Онлайн.</p></div>';
    var arenas = t.arenas || [];
    if (!arenas.length) return '';
    return '<div class="card"><h4>Где проходят занятия</h4>' + arenas.map(function (a) {
      return '<div class="kv"><span>' + esc(a.name) + '</span><b>' + (a.rental_cents ? 'прокат ' + esc(M.formatMoney(a.rental_cents, a.rental_currency)) : '') + '</b></div>';
    }).join('') + '<p class="mut" style="font-size:12.5px">Билет на сеанс покупается в кассе катка.</p></div>';
  }

  /* ── 3 · Другое время ────────────────────────────────────────────── */

  function openWeek() {
    S.weekStart = S.todayIso;
    var first = (S.slots || [])[0];
    S.day = first && M.daysBetween(S.todayIso, first.slot_date) < 7 ? first.slot_date : S.todayIso;
    go('week');
  }

  /** Конец данных /client/slots: эта неделя и следующая (по воскресенье). */
  function slotsHorizonIso() {
    var d = new Date(S.todayIso + 'T00:00:00Z');
    var wd = (d.getUTCDay() + 6) % 7;
    return M.addDays(S.todayIso, 13 - wd);
  }

  function renderWeek() {
    var t = S.trainer;
    var dirs = M.trainerDirections(t);
    var slots = S.slots || [];
    var h = '<div class="bd">' + backBtn(t.name);
    if (dirs.length > 1) {
      h += '<div class="tabsA" style="margin:0;padding:0">' + dirs.map(function (d) {
        return '<button type="button" data-act="dir" data-key="' + d.key + '" aria-selected="' + (d.key === S.dirKey) + '">' + esc(d.title) + '</button>';
      }).join('') + '</div>';
    }
    var end = M.addDays(S.weekStart, 6);
    var weekSlots = slots.filter(function (s) { return s.slot_date >= S.weekStart && s.slot_date <= end; });
    h += '<div class="wk"><button type="button" data-act="wk-prev" aria-label="Предыдущая неделя"' + (S.weekStart <= S.todayIso ? ' disabled' : '') + '>‹</button>' +
      '<b>' + esc(M.weekRange(S.weekStart)) + '</b>' +
      '<button type="button" data-act="wk-next" aria-label="Следующая неделя"' + (M.addDays(S.weekStart, 7) > slotsHorizonIso() ? ' disabled' : '') + '>›</button></div>';
    h += '<div class="days">' + M.weekDays(S.weekStart, weekSlots).map(function (d) {
      return '<button type="button" data-act="day" data-day="' + d.iso + '" class="' + (d.off ? 'off' : '') + '" aria-pressed="' + (d.iso === S.day) + '"' + (d.iso > slotsHorizonIso() ? ' disabled' : '') + '>' + d.wd + '<b>' + d.day + '</b></button>';
    }).join('') + '</div>';
    var dayRows = slots.filter(function (s) { return s.slot_date === S.day; });
    var dayWord = S.day === S.todayIso ? 'сегодня' : 'в этот день';
    if (S.slots === null) h += '<span class="mut">Загружаем время…</span>';
    else if (dayRows.length) {
      h += '<div class="rows">' + dayRows.map(function (s) {
        var mins = M.slotMinutes(s);
        var sub = [mins ? mins + ' мин' : '', s.is_online ? 'онлайн' : s.arena_name, s.capacity > 1 && s.spots_left != null ? 'осталось ' + M.word(s.spots_left, 'место', 'места', 'мест') : '']
          .filter(Boolean).join(' · ');
        return '<button type="button" data-act="slot" data-slot="' + esc(s.id) + '"><b>' + esc(String(s.start_time).slice(0, 5)) + '</b><span>' + esc(sub) + '</span><em>›</em></button>';
      }).join('') + '</div><span class="mut">На другие часы ' + dayWord + ' свободного времени нет.</span>';
    } else {
      h += '<span class="mut">' + (dayWord === 'сегодня' ? 'Сегодня' : 'В этот день') + ' свободного времени нет.</span>';
    }
    var horizon = slotsHorizonIso();
    if (end > horizon) {
      h += '<span class="mut">Время после ' + esc(M.dayLabel(horizon, '0000-01-01').replace(/^[^,]+, /, '')) + ' здесь пока не видно — спросите тренера.</span>';
    }
    h += '<div class="card"><p>Не нашли подходящее время? Напишите ' + esc(M.dativeFirst(t.first_name, RuName)) + ' — обсудите другое время.</p>' +
      (t.contact_url ? '<button type="button" class="more" data-act="write">Написать тренеру</button>' : '') +
      (initData && !t.contact_url ? '<button type="button" class="more" data-act="request">Оставить заявку</button>' : '') + '</div></div>';
    return h;
  }

  /* ── 4/5 · Запись ────────────────────────────────────────────────── */

  function slotById(id) {
    var list = S.slots || [];
    for (var i = 0; i < list.length; i++) if (String(list[i].id) === String(id)) return list[i];
    return null;
  }

  function selfProfile() {
    return S.profiles.filter(function (p) { return p.role === 'self'; })[0] || null;
  }

  /** Постоянный: у аккаунта уже есть профили семьи — выбор из них, телефон подставлен, если известен. */
  function isRegular() {
    return S.profiles.length > 0;
  }

  function tgFirstName() {
    var u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
    var saved = S.session && S.session.client_first_name;
    return String(saved || (u && u.first_name) || '').trim();
  }

  function openBooking(slot) {
    var keep = S.book && S.book.slot && S.view === 'book' ? S.book : null;
    var regular = isRegular();
    var def = null;
    if (regular) {
      var defId = S.defaultProfileId;
      def = S.profiles.filter(function (p) { return Number(p.client_id) === Number(defId); })[0] || S.profiles[0];
    }
    S.book = {
      slot: slot,
      regular: regular,
      kind: keep ? keep.kind : null,
      duoOpen: keep ? keep.duoOpen : false,
      names: keep ? keep.names : { self: tgFirstName() },
      selected: keep ? keep.selected : def ? [def] : [],
      override: keep ? keep.override : null,
      otherTier: false,
      addChild: false,
      comment: keep ? keep.comment : '',
      commentOpen: keep ? keep.commentOpen : false,
      phone: keep ? keep.phone : String((S.session && S.session.client_phone) || ''),
      phoneEdit: keep ? keep.phoneEdit : false,
      phoneManual: keep ? keep.phoneManual : false,
      childIds: keep ? keep.childIds : {},
      idem: BC.newIdempotencyKey(),
      submitting: false,
      notice: '',
    };
    if (slot.capacity > 1 && slot.service_id) S.serviceId = slot.service_id;
    BC.emitBookingAnalytics('booking_step_viewed', { step: 'form', host: 'trainers' });
    if (S.view === 'book') render();
    else go('book');
  }

  function bookingService() {
    var b = S.book;
    if (b && b.slot && b.slot.capacity > 1 && b.slot.service_id) {
      var g = (S.trainer.services || []).filter(function (s) { return Number(s.service_id) === Number(b.slot.service_id); })[0];
      if (g) return g;
    }
    return currentService();
  }

  function lastVariantOpts(svc) {
    var hint = S.session && svc ? BC.priceVariantHint({
      lastCreatedBookingServiceId: S.session.last_created_booking_service_id,
      lastCreatedBookingPriceVariantId: S.session.last_created_booking_service_price_variant_id,
      bookingContextServiceId: S.session.booking_context_service_id,
      bookingContextServicePriceVariantId: S.session.booking_context_service_price_variant_id,
    }, svc.service_id) : null;
    return { lastVariantId: hint, lastProfileId: S.defaultProfileId };
  }

  /** Тариф и участники текущего выбора: { tier, duo, ready, participant, kindTitle }. */
  function bookingChoice() {
    var b = S.book;
    var svc = bookingService();
    var group = b.slot.capacity > 1;
    if (!svc) return { ready: false };
    if (b.regular) {
      if (!b.selected.length) return { ready: false };
      var opts = lastVariantOpts(svc);
      opts.override = b.override;
      var tier = group ? null : M.regularTier(svc, b.selected, opts);
      var hasTiers = (svc.price_tiers || []).length > 0;
      return {
        ready: group || !hasTiers || !!tier,
        tier: tier,
        duo: !!(tier && ['two_children', 'adult_and_child', 'two_adults'].indexOf(tier.tier_kind) >= 0) || b.selected.length === 2,
        participant: b.selected.map(function (p) { return p.first_name; }).join(' и '),
      };
    }
    if (!b.kind) return { ready: false };
    var o = M.whoOptions(svc, { group: group });
    var row = o.single.concat(o.duo).filter(function (r) { return r.kind === b.kind; })[0];
    var t = row && row.variantId != null ? (svc.price_tiers || []).filter(function (x) { return Number(x.id) === row.variantId; })[0] : null;
    var plan = M.newClientBookingPlan(b.kind, b.names);
    return {
      ready: !!row,
      tier: t,
      duo: ['two_children', 'adult_and_child', 'two_adults'].indexOf(b.kind) >= 0,
      participant: [plan.participant, plan.secondName].filter(Boolean).join(' и '),
    };
  }

  function renderBook() {
    var b = S.book;
    var t = S.trainer;
    var svc = bookingService();
    var slot = b.slot;
    var place = slot.is_online ? 'онлайн' : (slot.arena_name || (arenaById(slot.arena_id) || {}).name || '');
    var svcDir = svc ? M.direction(M.directionKeyForServiceId(svc.service_id)) : null;
    var what = svc ? (svcDir && svcDir.ids.length === 1 && svc.is_public !== false ? svcDir.title : svc.service_name) : '';
    var h = '<div class="bd">' + backBtn('Назад');
    h += '<div class="sum"><div class="k">' + (t.photo_url ? '<img src="' + esc(t.photo_url) + '" alt="">' : '<i>' + esc(t.initial || 'Т') + '</i>') +
      '<div class="when"><b>' + esc(M.slotWhen(slot, S.todayIso)) + '</b><br><span>' + esc([t.name, what, place].filter(Boolean).join(' · ')) + '</span></div></div></div>';
    if (!svc) {
      var svcs = serviceList(t, S.dirKey);
      h += '<div class="fl"><span class="lbl">Какое занятие?</span><div class="opt">' + svcs.map(function (s) {
        var dur = t.session_duration_minutes ? t.session_duration_minutes + ' мин · ' : '';
        return '<button type="button" data-act="svc" data-sid="' + s.service_id + '"><span><b>' + esc(s.service_name) + '</b><br>' + esc(dur) +
          M.cardPriceHtml(s).replace(/<\/?b>/g, '') + '</span><em>›</em></button>';
      }).join('') + '</div></div></div>' + bookFooter(false);
      return h;
    }
    h += b.regular ? regularFormHtml(svc) : newFormHtml(svc);
    var choice = bookingChoice();
    if (choice.ready) {
      h += '<div data-after style="display:grid;gap:12px">';
      if (!b.regular) h += namesHtml();
      h += phoneHtml(b);
      h += b.commentOpen
        ? '<div class="fl"><label for="tswComment">Комментарий для тренера</label><textarea id="tswComment" class="inpx" data-field="comment" maxlength="500">' + esc(b.comment) + '</textarea></div>'
        : '<button type="button" class="more" data-act="comment">+ Комментарий для тренера</button>';
      h += '<p class="payl">' + payHtml(svc, choice) + '</p></div>';
    }
    if (b.notice) h += '<p class="note" role="alert">' + esc(b.notice) + '</p>';
    h += '</div>' + bookFooter(choice.ready);
    return h;
  }

  function payHtml(svc, choice) {
    var b = S.book;
    var slot = b.slot;
    var arena = arenaById(slot.arena_id);
    var pass = null;
    if (b.regular) {
      for (var i = 0; i < b.selected.length && !pass; i++) {
        pass = M.usablePass(S.passes[b.selected[i].client_id], S.trainer.id, svc.service_id);
      }
    }
    var groupCents = slot.capacity > 1 && svc.group_price_cents ? svc.group_price_cents : null;
    return M.payLine({
      tier: choice.tier,
      duo: !!(choice.duo && choice.tier),
      pass: pass,
      currency: svc.currency_code,
      online: !!slot.is_online,
      rentalCents: arena && arena.rental_cents,
      rentalCurrency: arena && arena.rental_currency,
      fallbackCents: groupCents || svc.price_cents,
    });
  }

  function bookFooter(ready) {
    var b = S.book;
    var label = ready ? 'Записаться на ' + String(b.slot.start_time).slice(0, 5)
      : b.regular ? 'Отметьте, кого записываем' : 'Выберите, кто будет заниматься';
    if (b.submitting) label = 'Отправляем…';
    return '<div class="ft col"><button type="button" class="cta' + (ready ? '' : ' off') + '" data-act="submit"' + (ready && !b.submitting ? '' : ' disabled') + '>' + esc(label) + '</button>' +
      '<small>' + esc(S.trainer.first_name) + ' подтвердит запись</small></div>';
  }

  function pickRow(key, title, sub, price, checked, disabled, role) {
    return '<button type="button" role="' + role + '" data-act="pick" data-k="' + esc(key) + '" aria-checked="' + !!checked + '"' + (disabled ? ' disabled' : '') + '><i></i>' +
      '<span><b>' + esc(title) + '</b>' + (sub ? '<small>' + esc(sub) + '</small>' : '') + '</span><em>' + esc(price || '') + '</em></button>';
  }

  function newFormHtml(svc) {
    var b = S.book;
    var o = M.whoOptions(svc, { group: b.slot.capacity > 1 });
    var duoSelected = o.duo.some(function (r) { return r.kind === b.kind; });
    var open = b.duoOpen || duoSelected;
    var h = '<div class="fl"><span class="lbl" id="whoLbl">Кто будет заниматься?</span><div class="pick" role="radiogroup" aria-labelledby="whoLbl">' +
      o.single.map(function (r) { return pickRow(r.kind, r.title, '', r.price, b.kind === r.kind, false, 'radio'); }).join('') + '</div>';
    if (o.duo.length) {
      h += '<button type="button" class="duo" data-act="duo" aria-expanded="' + open + '">Двое на одном занятии ' + (open ? '▴' : '▾') + '</button>' +
        '<div class="pick" role="radiogroup"' + (open ? '' : ' hidden') + '>' +
        o.duo.map(function (r) { return pickRow(r.kind, r.title, '', r.price, b.kind === r.kind, false, 'radio'); }).join('') + '</div>';
    }
    return h + '</div>';
  }

  function namesHtml() {
    var b = S.book;
    return M.nameFields(b.kind, b.names.self).map(function (f) {
      var v = b.names[f.key] != null ? b.names[f.key] : f.value;
      return '<div class="fl"><label for="nm_' + f.key + '">' + esc(f.label) + '</label><input id="nm_' + f.key + '" class="inpx" data-field="name" data-key="' + f.key +
        '" value="' + esc(v) + '" placeholder="' + esc(f.placeholder) + '" maxlength="64" autocomplete="' + (f.key === 'self' ? 'given-name' : 'off') + '"></div>';
    }).join('');
  }

  function regularFormHtml(svc) {
    var b = S.book;
    var opts = lastVariantOpts(svc);
    var hasDuo = (svc.price_tiers || []).some(function (x) { return ['two_children', 'adult_and_child', 'two_adults'].indexOf(x.tier_kind) >= 0; });
    var h = '<div class="fl"><span class="lbl">Кого записываем?' + (hasDuo ? ' <span class="mut" style="font-weight:500">Можно двоих</span>' : '') + '</span><div class="pick multi">';
    h += S.profiles.map(function (p) {
      var on = b.selected.some(function (x) { return Number(x.client_id) === Number(p.client_id); });
      var tier = M.regularTier(svc, [p], opts);
      var last = tier && opts.lastVariantId != null && Number(tier.id) === Number(opts.lastVariantId) && Number(p.client_id) === Number(opts.lastProfileId);
      var sub = last ? 'как в прошлый раз' : tier ? String(BC.priceTierLabelRu(tier) || '').toLowerCase() : '';
      if (tier && tier.tier_kind === 'child') sub = last ? sub : 'детский';
      var dis = !on && !M.canAddProfile(svc, b.selected, p);
      return pickRow(p.client_id, p.first_name || 'Без имени', sub, tier ? M.formatMoney(tier.price_cents, svc.currency_code) : '', on, dis, 'checkbox');
    }).join('');
    h += '</div></div>';
    h += '<div class="row2"><button type="button" class="more" data-act="add-child">+ Добавить ребёнка</button>' +
      ((svc.price_tiers || []).length > 1 ? '<button type="button" class="more" data-act="other-tier">Другой тариф</button>' : '') + '</div>';
    if (b.addChild) {
      h += '<div class="fl"><label for="newChild">Имя ребёнка</label><input id="newChild" class="inpx" data-field="new-child" maxlength="64" placeholder="Например, Соня">' +
        '<button type="button" class="sec2" data-act="add-child-save">Добавить</button></div>';
    }
    if (b.otherTier) {
      h += '<div class="opt">' + (svc.price_tiers || []).map(function (x) {
        return '<button type="button" data-act="tier" data-vid="' + x.id + '" aria-pressed="' + (Number(b.override) === Number(x.id)) + '"><span><b>' +
          esc(M.TIER_TITLE[x.tier_kind] || x.label) + '</b></span><em>' + esc(M.formatMoney(x.price_cents, svc.currency_code)) + '</em></button>';
      }).join('') + '</div>';
    }
    return h;
  }

  /** Телефон: известен — подставлен (как сейчас); нет — «Поделиться номером из Telegram» и ручной ввод запасным путём. */
  function phoneHtml(st) {
    var known = String(st.phone || '').trim();
    var canShare = !!(tg && typeof tg.requestContact === 'function');
    var field = '<div class="crm-phone-field" data-crm-phone-field data-default-country="BY"><div class="crm-phone-field-row">' +
      '<button type="button" class="crm-phone-country-btn" aria-label="Код страны" aria-haspopup="listbox" aria-expanded="false"><span class="crm-phone-country-flag" aria-hidden="true">🇧🇾</span><span class="crm-phone-country-dial">+375</span><span class="crm-phone-country-chevron" aria-hidden="true">▾</span></button>' +
      '<input type="tel" id="tswPhone" class="crm-phone-national-input" placeholder="29 123-45-67" autocomplete="tel-national" inputmode="tel" aria-required="true" aria-label="Телефон для тренера"></div>' +
      '<div class="crm-phone-country-menu" role="listbox" hidden><button type="button" class="crm-phone-country-option crm-phone-country-option--active" role="option" data-country="BY" aria-selected="true">🇧🇾 Беларусь +375</button>' +
      '<button type="button" class="crm-phone-country-option" role="option" data-country="RU" aria-selected="false">🇷🇺 Россия +7</button></div></div>';
    var h = '<div class="fl"><span class="lbl">Телефон для тренера</span>';
    if (known && !st.phoneEdit) {
      return h + '<div class="kv" style="border:0;padding:0;align-items:center"><b>' + esc(known) + '</b><button type="button" class="more" data-act="phone-edit">Изменить</button></div></div>';
    }
    if (!known && canShare && !st.phoneManual) {
      return h + '<button type="button" class="tgph" data-act="share-phone">Поделиться номером из Telegram</button>' +
        '<button type="button" class="more c" data-act="phone-manual">Ввести вручную</button></div>';
    }
    return h + field + (st.phoneHint ? '<span class="mut">' + esc(st.phoneHint) + '</span>' : '') + '</div>';
  }

  function wirePhone(st) {
    var wrap = document.querySelector('[data-crm-phone-field]');
    if (!wrap || !window.CrmPhoneField) return;
    window.CrmPhoneField.init(wrap);
    if (st.phone) window.CrmPhoneField.setE164(wrap, st.phone);
    var input = wrap.querySelector('input');
    if (input) input.addEventListener('input', function () { st.phoneDraft = true; });
  }

  /** Текущий телефон формы: E.164 из поля или подставленный. */
  function readPhone(st) {
    var wrap = document.querySelector('[data-crm-phone-field]');
    if (wrap && window.CrmPhoneField) {
      var v = window.CrmPhoneField.validate(wrap);
      return v.ok ? { ok: true, phone: v.e164 } : { ok: false, error: v.error };
    }
    if (String(st.phone || '').trim()) return { ok: true, phone: String(st.phone).trim() };
    return { ok: false, error: 'Укажите телефон для тренера.' };
  }

  function sharePhone(st) {
    if (!tg || typeof tg.requestContact !== 'function') {
      st.phoneManual = true;
      repaintPhone(st);
      return;
    }
    try {
      tg.requestContact(function (shared, res) {
        var phone = M.phoneFromContact(res);
        if (shared && phone) {
          st.phone = phone;
          st.phoneEdit = true;
          st.phoneHint = '';
        } else {
          st.phoneManual = true;
          st.phoneHint = shared ? 'Номер ушёл в чат с ботом — продублируйте его здесь.' : '';
        }
        repaintPhone(st);
      });
    } catch (e) {
      st.phoneManual = true;
      repaintPhone(st);
    }
  }

  /** Поле телефона живёт в форме записи или в шторке заявки — перерисовываем владельца. */
  function repaintPhone(st) {
    if (st === S.req && !sheetEl.hidden) paintRequest();
    else render();
  }

  /** Одно место, где собирается тело записи (поле source добавляет TASK-351 — сюда же). */
  function buildBookingBody(o) {
    return BC.buildBookingPayload({
      slotId: o.slot.id,
      phone: o.phone,
      comment: o.comment,
      serviceId: o.serviceId,
      priceVariantId: o.priceVariantId,
      needsProfileName: o.needsProfileName,
      firstName: o.firstName,
      lastName: o.lastName,
    });
  }

  function ensureChildProfile(name) {
    var b = S.book;
    var key = name.toLowerCase();
    if (b.childIds[key]) return Promise.resolve(b.childIds[key]);
    var existing = S.profiles.filter(function (p) { return p.role !== 'self' && String(p.first_name || '').trim().toLowerCase() === key; })[0];
    if (existing) return Promise.resolve(existing.client_id);
    return api('/api/webapp/client/profiles', { method: 'POST', body: { first_name: name } }).then(function (d) {
      b.childIds[key] = d.client_id;
      return d.client_id;
    });
  }

  function submit() {
    var b = S.book;
    if (b.submitting) return;
    if (!initData) {
      b.notice = 'Запись работает в Telegram — откройте Glide в Telegram.';
      render();
      return;
    }
    var svc = bookingService();
    var choice = bookingChoice();
    if (!svc || !choice.ready) return;
    var ph = readPhone(b);
    if (!ph.ok) {
      b.notice = ph.error || 'Укажите телефон для тренера.';
      render();
      return;
    }
    b.phone = ph.phone;
    var plan;
    var second = '';
    var profilePromise;
    var firstName = '';
    if (b.regular) {
      var p0 = b.selected[0];
      second = b.selected[1] ? b.selected[1].first_name : '';
      profilePromise = Promise.resolve(p0.client_id);
    } else {
      plan = M.newClientBookingPlan(b.kind, b.names);
      var missing = M.nameFields(b.kind, '').some(function (f) { return !String(b.names[f.key] || '').trim(); });
      if (missing) {
        b.notice = 'Укажите имя каждого, кто будет заниматься.';
        render();
        return;
      }
      second = plan.secondName;
      firstName = plan.selfName;
      var self = selfProfile();
      profilePromise = plan.profile === 'child' ? ensureChildProfile(plan.childName) : Promise.resolve(self ? self.client_id : null);
    }
    b.submitting = true;
    b.notice = '';
    render();
    profilePromise
      .then(function (profileId) {
        var isSelf = !b.regular ? plan.profile === 'self' : (b.selected[0].role === 'self');
        var body = buildBookingBody({
          slot: b.slot,
          phone: b.phone,
          comment: M.bookingComment(second, b.comment) || null,
          serviceId: svc.service_id,
          priceVariantId: b.slot.capacity > 1 ? null : choice.tier ? Number(choice.tier.id) : null,
          needsProfileName: isSelf && !!firstName,
          firstName: firstName,
          lastName: '',
        });
        return BC.submitBooking({ body: body, initData: initData, idempotencyKey: b.idem, profileId: profileId }).then(function (r) {
          return { r: r, profileId: profileId };
        });
      })
      .then(function (x) {
        var r = x.r;
        b.submitting = false;
        if (r.res.ok && r.data && r.data.success) {
          onBooked(r.data, choice);
          return;
        }
        var detail = r.data && typeof r.data.detail === 'string' ? r.data.detail : '';
        if (r.res.status === 400 && /slot not available/i.test(detail)) {
          showTaken();
          return;
        }
        if (!r.data || r.res.status >= 500) {
          verifyUnknown(x.profileId, choice);
          return;
        }
        b.notice = detail || 'Не удалось записаться. Попробуйте ещё раз.';
        render();
      })
      .catch(function (err) {
        b.submitting = false;
        if (err && err.status) {
          b.notice = err.message || 'Не удалось записаться.';
          render();
          return;
        }
        verifyUnknown(null, choice);
      });
  }

  /** Неизвестный результат — сначала проверить запись, потом предлагать повтор (тем же ключом идемпотентности). */
  function verifyUnknown(profileId, choice) {
    var b = S.book;
    api('/api/webapp/client/bookings', { profileId: profileId })
      .then(function (d) {
        var found = ((d && d.days) || []).some(function (day) {
          return (day.bookings || []).some(function (x) { return String(x.slot_id) === String(b.slot.id); });
        });
        if (found) {
          onBooked({ success: true }, choice);
          return;
        }
        b.notice = 'Запись не дошла. Нажмите ещё раз — второй записи не будет.';
        render();
      })
      .catch(function () {
        b.notice = 'Сеть не ответила. Запись могла создаться — проверьте «Мои записи», прежде чем нажимать снова.';
        render();
      });
  }

  function onBooked(data, choice) {
    var b = S.book;
    BC.hapticSuccess();
    S.sent = { data: data, slot: b.slot, participant: choice.participant, trainer: S.trainer, dirKey: S.dirKey };
    S.stack = [];
    S.view = 'sent';
    render();
    window.scrollTo(0, 0);
    S.book = null;
  }

  /* ── 7 · Время заняли ────────────────────────────────────────────── */

  function showTaken(missingTitle) {
    var b = S.book;
    var lostId = b ? b.slot.id : null;
    var title = b ? String(b.slot.start_time).slice(0, 5) + ' только что заняли' : (missingTitle || 'Это время уже заняли');
    var who = b ? bookingChoice().participant : '';
    loadSlots().then(function () {
      var alt = (S.slots || []).filter(function (s) { return String(s.id) !== String(lostId); }).slice(0, 3);
      var svc = currentService();
      var price = svc ? M.cardPriceHtml(svc).replace(/<\/?b>/g, '') : '';
      var saved = b ? (who ? who + ' и телефон сохранены. ' : 'Телефон сохранён. ') : '';
      openSheet('<div class="sh"><h4>' + esc(title) + '</h4><button type="button" class="x" data-act="sheet-close" aria-label="Закрыть">✕</button></div>' +
        '<span class="mut">' + esc(saved + (alt.length ? 'Свободное время у ' + genFirst(S.trainer.first_name) + ':' : 'Другого свободного времени пока нет.')) + '</span>' +
        '<div class="opt">' + alt.map(function (s) {
          var sub = [s.is_online ? 'онлайн' : s.arena_name, price].filter(Boolean).join(' · ');
          return '<button type="button" data-act="slot" data-slot="' + esc(s.id) + '"><span><b>' + esc(M.slotWhen(s, S.todayIso).replace(/–.*$/, '')) + '</b><br>' + esc(sub) + '</span><em>›</em></button>';
        }).join('') + '</div>' +
        '<button type="button" class="more c" data-act="week">Другое время</button>');
      if (S.view === 'book') render();
    });
  }

  function genFirst(first) {
    var f = String(first || '').trim().split(/\s+/)[0] || '';
    if (!/^[А-Яа-яЁё-]+$/.test(f) || !RuName) return f || 'тренера';
    return RuName.inflectPersonName(f, '', 'gen') || f;
  }

  /* ── 6/6б · Запись отправлена ────────────────────────────────────── */

  function renderSent() {
    var x = S.sent;
    var t = x.trainer;
    var WA = window.GlideWriteAccess;
    var waState = '';
    try { waState = WA && tg ? WA.writeAccessState(tg) : ''; } catch (e) { waState = ''; }
    var canWrite = waState === 'already';
    var unreachable = BC.unreachableState();
    var slot = x.slot;
    var place = slot.is_online ? 'онлайн' : (slot.arena_name || '');
    var line = [x.participant, M.daySmall(slot.slot_date, S.todayIso) + ', ' + String(slot.start_time).slice(0, 5), place].filter(Boolean).join(' · ');
    var h = '<div class="bd"><div class="okc" aria-hidden="true">✓</div><div class="ctr"><h3>Запись отправлена ' + esc(M.dativeFirst(t.first_name, RuName)) + '</h3>' +
      '<span class="mut">' + esc(line) + '</span></div>';
    var steps;
    if (canWrite) {
      steps = [esc(t.first_name) + ' подтвердит запись — пришлём сообщение в чат с ботом.'];
      var plan = x.data && x.data.reminder_plan ? String(x.data.reminder_plan).trim() : '';
      if (plan) steps.push('Напомним ' + esc(plan) + '.');
      steps.push('Детали, адрес и отмена — в «Моих записях».');
    } else {
      if (unreachable) h += '<div class="warn">' + BC.writeAccessBlockHtml(unreachable) + '</div>';
      steps = ['Подтверждение тренера появится в «Моих записях».', 'Там же — детали, адрес и отмена.'];
    }
    h += '<div class="card"><h4>Что дальше</h4><ol class="ol">' + steps.map(function (s) { return '<li>' + s + '</li>'; }).join('') + '</ol></div>';
    if (!slot.is_online) {
      h += '<div class="card"><h4>Что взять с собой</h4><p>' + esc(M.takeWithYou(x.dirKey, arenaById(slot.arena_id))) + '</p></div>';
    }
    h += '</div><div class="ft col"><button type="button" class="cta" data-act="my-bookings">Мои записи</button>' +
      (slot.map_link ? '<button type="button" class="sec2" data-act="route">Маршрут до катка</button>' : '') + '</div>';
    return h;
  }

  /* ── 10/11 · Заявка ──────────────────────────────────────────────── */

  function openRequest() {
    var t = S.trainer;
    S.req = { name: tgFirstName(), comment: '', phone: String((S.session && S.session.client_phone) || ''), phoneEdit: false, phoneManual: false, sending: false, notice: '' };
    paintRequest();
    return t;
  }

  function paintRequest() {
    var r = S.req;
    capturePhone(r, sheetEl);
    var t = S.trainer;
    openSheet('<div class="sh"><h4>Оставить заявку ' + esc(M.dativeFirst(t.first_name, RuName)) + '</h4><button type="button" class="x" data-act="sheet-close" aria-label="Закрыть">✕</button></div>' +
      '<div class="fl"><label for="rqName">Как вас зовут?</label><input id="rqName" class="inpx" data-field="rq-name" maxlength="64" value="' + esc(r.name) + '" autocomplete="given-name"></div>' +
      '<div class="fl"><label for="rqComment">Кто будет заниматься и когда удобно?</label><textarea id="rqComment" class="inpx" data-field="rq-comment" maxlength="500" placeholder="Например: дочь, выходные утром">' + esc(r.comment) + '</textarea></div>' +
      phoneHtml(r) + (r.notice ? '<p class="note" role="alert">' + esc(r.notice) + '</p>' : '') +
      '<button type="button" class="cta" data-act="rq-send"' + (r.sending ? ' disabled' : '') + '>' + (r.sending ? 'Отправляем…' : 'Отправить заявку') + '</button>');
    wirePhone(r);
  }

  function sendRequest() {
    var r = S.req;
    var t = S.trainer;
    var svc = currentService() || serviceList(t, S.dirKey)[0] || (t.services || [])[0];
    var cityId = S.cityId || (S.session && S.session.city_id);
    if (!String(r.name || '').trim()) { r.notice = 'Укажите имя.'; paintRequest(); return; }
    var ph = readPhone(r);
    if (!ph.ok) { r.notice = ph.error; paintRequest(); return; }
    if (!svc || !cityId) { r.notice = 'Не удалось определить город или услугу. Напишите тренеру напрямую.'; paintRequest(); return; }
    r.sending = true;
    r.notice = '';
    paintRequest();
    api('/api/webapp/client/request', {
      method: 'POST',
      body: { city_id: cityId, service_id: svc.service_id, trainer_id: t.id, comment: r.comment.trim() || null, first_name: r.name.trim(), phone: ph.phone },
    })
      .then(function () {
        closeSheet();
        S.stack = [];
        S.view = 'reqsent';
        render();
        window.scrollTo(0, 0);
      })
      .catch(function (e) {
        r.sending = false;
        r.notice = (e && e.message) || 'Не удалось отправить заявку.';
        paintRequest();
      });
  }

  function renderReqSent() {
    var t = S.trainer;
    return '<div class="bd"><div class="okc" aria-hidden="true">✓</div><div class="ctr"><h3>Заявка отправлена ' + esc(M.dativeFirst(t.first_name, RuName)) + '</h3>' +
      '<span class="mut">Статус и ответ — в «Моих заявках».</span></div>' +
      '<div class="card"><p>Пока ждёте — посмотрите тренеров с онлайн-записью: у них свободное время видно сразу.</p></div></div>' +
      '<div class="ft col"><button type="button" class="cta" data-act="my-requests">Мои заявки</button><button type="button" class="sec2" data-act="to-list">Другие тренеры</button></div>';
  }

  /* ── Шторки ──────────────────────────────────────────────────────── */

  function openSheet(inner) {
    sheetEl.innerHTML = '<div class="dim" data-act="sheet-dim"><div class="sheet" role="dialog" aria-modal="true">' + inner + '</div></div>';
    sheetEl.hidden = false;
  }

  function closeSheet() {
    sheetEl.hidden = true;
    sheetEl.innerHTML = '';
  }

  function openArenaSheet() {
    var list = M.arenaOptions(S.items, S.tab);
    openSheet('<div class="sh"><h4>Каток</h4><button type="button" class="x" data-act="sheet-close" aria-label="Закрыть">✕</button></div><div class="opt">' +
      '<button type="button" data-act="arena" data-aid="" aria-pressed="' + !S.arenaId + '"><span><b>Все катки</b></span></button>' +
      list.map(function (a) {
        return '<button type="button" data-act="arena" data-aid="' + a.id + '" aria-pressed="' + (Number(S.arenaId) === Number(a.id)) + '"><span><b>' + esc(a.name) + '</b><br>' +
          esc(M.word(a.count, 'тренер', 'тренера', 'тренеров')) + '</span></button>';
      }).join('') + '</div>');
  }

  /* ── Рендер и события ────────────────────────────────────────────── */

  /** Перед перерисовкой забираем набранный номер в состояние — иначе «+ Комментарий» и выбор тарифа его стирают. */
  function capturePhone(st, root) {
    var wrap = st && root && root.querySelector('[data-crm-phone-field]');
    if (!wrap || !window.CrmPhoneField) return;
    var input = wrap.querySelector('input');
    if (!input || !String(input.value || '').trim()) return;
    var e164 = window.CrmPhoneField.getE164(wrap);
    if (e164) {
      st.phone = e164;
      st.phoneEdit = true;
    }
  }

  function render() {
    if (S.view === 'book') capturePhone(S.book, appEl);
    var html;
    if (S.view === 'trainer') html = renderTrainer();
    else if (S.view === 'week') html = renderWeek();
    else if (S.view === 'book') html = renderBook();
    else if (S.view === 'sent') html = renderSent();
    else if (S.view === 'reqsent') html = renderReqSent();
    else html = renderList();
    appEl.innerHTML = '<div class="tsw-view">' + html + '</div>';
    if (S.view === 'book' && S.book) wirePhone(S.book);
    if (S.view === 'sent') BC.bindWriteAccessBlock(appEl);
  }

  function syncUrl() {
    var q = new URLSearchParams(location.search);
    if (S.tab && S.tab !== 'all') q.set('tab', S.tab); else q.delete('tab');
    if (S.arenaId) q.set('arena_id', String(S.arenaId)); else q.delete('arena_id');
    // Фильтры витрины — в адресе; вход в тренера/время одноразовый и при перезагрузке не повторяется.
    ['trainer_id', 'slot_id', 'service_id', 'via'].forEach(function (k) { q.delete(k); });
    try { history.replaceState(history.state, '', location.pathname + '?' + q.toString()); } catch (e) { /* */ }
  }

  function trainerFromEl(el) {
    return trainerById(el.getAttribute('data-tid'));
  }

  function onClick(ev) {
    var el = ev.target.closest('[data-act]');
    if (!el || el.disabled) return;
    var act = el.getAttribute('data-act');
    var b = S.book;
    var t;
    switch (act) {
      case 'back':
        if (history.state && history.state.tsw) history.back();
        else back();
        break;
      case 'retry': S.loadError = false; render(); boot(); break;
      case 'tab': S.tab = el.getAttribute('data-key'); syncUrl(); render(); break;
      case 'arena-sheet': if (S.arenaId) { S.arenaId = null; syncUrl(); render(); } else openArenaSheet(); break;
      case 'arena-clear': S.arenaId = null; syncUrl(); render(); break;
      case 'arena': S.arenaId = num(el.getAttribute('data-aid')); closeSheet(); syncUrl(); render(); break;
      case 'trainer': t = trainerFromEl(el); if (t) { noteShowcasePick(); openTrainer(t); } break;
      case 'win':
        ev.stopPropagation();
        t = trainerFromEl(el);
        if (t) openTrainerAndSlot(t, el.getAttribute('data-slot'), true);
        break;
      case 'week':
        ev.stopPropagation();
        closeSheet();
        if (el.getAttribute('data-tid')) {
          t = trainerFromEl(el);
          if (t) openTrainer(t).then(openWeek);
        } else openWeek();
        break;
      case 'write':
        ev.stopPropagation();
        t = el.getAttribute('data-tid') ? trainerFromEl(el) : S.trainer;
        if (t) openLink(t.contact_url);
        break;
      case 'dir':
        S.dirKey = el.getAttribute('data-key');
        S.serviceId = null;
        loadSlots().then(render);
        render();
        break;
      case 'svc':
        S.serviceId = Number(el.getAttribute('data-sid'));
        if (S.view === 'book') render();
        else loadSlots().then(render);
        break;
      case 'slot': {
        var slot = slotById(el.getAttribute('data-slot'));
        closeSheet();
        if (slot) openBooking(slot);
        break;
      }
      case 'reslots': loadSlots().then(render); render(); break;
      case 'wk-prev': S.weekStart = M.addDays(S.weekStart, -7); if (S.weekStart < S.todayIso) S.weekStart = S.todayIso; S.day = S.weekStart; render(); break;
      case 'wk-next': S.weekStart = M.addDays(S.weekStart, 7); S.day = S.weekStart; render(); break;
      case 'day': S.day = el.getAttribute('data-day'); render(); break;
      case 'notify':
        el.disabled = true;
        api('/api/webapp/client/trainer-edges/notify-slots', { method: 'POST', body: { trainer_id: S.trainer.id } })
          .then(function () { el.textContent = 'Сообщим, когда появится время'; })
          .catch(function () { el.disabled = false; el.textContent = 'Не получилось — попробовать ещё раз'; });
        break;
      case 'save':
        el.disabled = true;
        api('/api/webapp/client/trainer-edges/save', { method: 'POST', body: { trainer_id: S.trainer.id } })
          .then(function () { S.saved = true; render(); })
          .catch(function () { el.disabled = false; });
        break;
      case 'pick': {
        var k = el.getAttribute('data-k');
        if (b.regular) {
          var p = S.profiles.filter(function (x) { return String(x.client_id) === k; })[0];
          var on = b.selected.some(function (x) { return String(x.client_id) === k; });
          b.selected = on ? b.selected.filter(function (x) { return String(x.client_id) !== k; }) : b.selected.concat([p]);
          b.override = null;
        } else {
          b.kind = k;
        }
        b.notice = '';
        render();
        break;
      }
      case 'duo': b.duoOpen = !b.duoOpen; render(); break;
      case 'comment': b.commentOpen = true; render(); var c = document.getElementById('tswComment'); if (c) c.focus(); break;
      case 'other-tier': b.otherTier = !b.otherTier; render(); break;
      case 'tier': b.override = Number(el.getAttribute('data-vid')); render(); break;
      case 'add-child': b.addChild = !b.addChild; render(); break;
      case 'add-child-save': {
        var inp = document.getElementById('newChild');
        var name = inp ? inp.value.trim() : '';
        if (!name) return;
        el.disabled = true;
        api('/api/webapp/client/profiles', { method: 'POST', body: { first_name: name } })
          .then(function (d) {
            var prof = { client_id: d.client_id, role: 'guardian', first_name: name };
            S.profiles.push(prof);
            S.passes[d.client_id] = [];
            b.addChild = false;
            if (M.canAddProfile(bookingService(), b.selected, prof)) b.selected = b.selected.concat([prof]);
            render();
          })
          .catch(function (e) { b.notice = (e && e.message) || 'Не удалось добавить.'; render(); });
        break;
      }
      case 'phone-edit': (S.req && !sheetEl.hidden ? S.req : b).phoneEdit = true; rerenderPhoneOwner(); break;
      case 'phone-manual': (S.req && !sheetEl.hidden ? S.req : b).phoneManual = true; rerenderPhoneOwner(); break;
      case 'share-phone': sharePhoneFor(S.req && !sheetEl.hidden ? S.req : b); break;
      case 'submit': submit(); break;
      case 'request': openRequest(); break;
      case 'rq-send': sendRequest(); break;
      case 'sheet-close': closeSheet(); break;
      case 'sheet-dim': if (ev.target === el) closeSheet(); break;
      case 'my-bookings': navigate('client-bookings'); break;
      case 'my-requests': navigate('client-requests'); break;
      case 'route': openLink(S.sent && S.sent.slot.map_link); break;
      case 'to-list': S.view = 'list'; S.stack = []; render(); window.scrollTo(0, 0); break;
      default: break;
    }
  }

  function rerenderPhoneOwner() {
    if (S.req && !sheetEl.hidden) paintRequest();
    else render();
  }

  function sharePhoneFor(st) {
    sharePhone(st);
  }

  function onInput(ev) {
    var el = ev.target;
    var f = el.getAttribute && el.getAttribute('data-field');
    if (!f) return;
    if (f === 'name' && S.book) S.book.names[el.getAttribute('data-key')] = el.value;
    else if (f === 'comment' && S.book) S.book.comment = el.value;
    else if (f === 'rq-name' && S.req) S.req.name = el.value;
    else if (f === 'rq-comment' && S.req) S.req.comment = el.value;
  }

  appEl.addEventListener('click', onClick);
  sheetEl.addEventListener('click', onClick);
  appEl.addEventListener('input', onInput);
  sheetEl.addEventListener('input', onInput);

  /** Время с витрины → тренер (для «Назад») → сразу запись; окно ушло — «Время заняли». */
  function openTrainerAndSlot(t, slotId, viaList) {
    S.trainer = t;
    if (viaList) noteShowcasePick();
    var dirs = M.trainerDirections(t);
    // Время с вкладки направления — услуга этого направления; со «Все» при нескольких направлениях
    // услугу не угадываем: форма спросит «Какое занятие?».
    S.dirKey = S.tab !== 'all' && dirs.some(function (d) { return d.key === S.tab; }) ? S.tab : dirs.length === 1 ? dirs[0].key : null;
    S.serviceId = viaList ? null : num(qs.get('service_id'));
    if (viaList) go('trainer');
    else S.view = 'trainer';
    render();
    return loadSlots()
      .then(function () {
        var slot = slotById(slotId);
        if (slot || !initData) return slot;
        // Список — только эта и следующая неделя; время по ссылке может быть дальше — проверяем его отдельно.
        return api('/api/webapp/client/slot/' + encodeURIComponent(slotId) + '?trainer_id=' + t.id)
          .then(function (d) { return d && d.available && d.slot ? decorateSlot(d.slot) : null; })
          .catch(function () { return null; });
      })
      .then(function (slot) {
        if (slot) openBooking(slot);
        else {
          render();
          showTaken('Это время уже заняли');
        }
      });
  }

  function boot() {
    Promise.all([loadSession(), loadProfiles()]).then(function (res) {
      S.session = res[0];
      S.profiles = res[1] || [];
      if (!S.cityId && S.session && S.session.city_id) S.cityId = num(S.session.city_id);
      loadPasses();
      return loadShowcase()
        .then(function (d) { S.items = (d && d.items) || []; })
        .catch(function () { S.items = null; S.loadError = true; });
    }).then(function () {
      var tid = num(qs.get('trainer_id'));
      if (!tid) { render(); return; }
      var t = trainerById(tid);
      var p = t ? Promise.resolve(t) : loadTrainerFallback(tid).catch(function () { return null; });
      return p.then(function (tr) {
        if (!tr) { render(); return; }
        var sid = qs.get('slot_id');
        if (sid) return openTrainerAndSlot(tr, sid, false);
        S.view = 'trainer';
        return openTrainer(tr, { view: false });
      });
    });
  }

  render();
  boot();

  window.__trainerShowcase = { state: S, render: render };
})();
