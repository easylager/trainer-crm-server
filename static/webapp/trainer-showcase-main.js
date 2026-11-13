/**
 * Витрина тренеров, карточка тренера и запись — Mini App (TASK-357, дизайн PDEC-033 v2).
 *
 * Экраны: 1 витрина · 2 тренер · 3 другое время · 4/5 запись (новый / постоянный) · 6/6б отправлено ·
 * 7 время заняли (шторка) · 8 нет времени · 9 без онлайн-записи · 10 заявка (шторка) · 11 заявка отправлена.
 *
 * Логика записи — существующие API и BookingClient: тариф прошлой записи — свой у каждого профиля и тренера,
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
  // Пришли с другого экрана (главная, «Поиск», каток, «Сохранённые») — снимок до наших pushState:
  // тогда «‹ Назад» в корне витрины уводит обратно (history.back), как #btnBack на других экранах клиента.
  var CAME_FROM = (function () { try { return Number(history.length) > 1; } catch (e) { return false; } })();
  // Панель вкладок прячем там, где закреплена кнопка записи/итога: запись, «отправлено», «заявка отправлена».
  var TABBAR_VIEWS = { list: true, trainer: true, week: true };

  var S = {
    cityId: num(qs.get('city_id')),
    tab: M.direction(qs.get('tab')) ? qs.get('tab') : 'all',
    arenaId: num(qs.get('arena_id')),
    items: null,
    loadError: false,
    session: null,
    profiles: [],
    passes: {},
    // Профили, про которые точно известно, что это ребёнок (добавлены здесь как ребёнок) — детский тариф.
    knownChildIds: {},
    // Тариф прошлой записи по профилю у тренера: { trainerId: { profileId: { sid, vid } } }.
    profileHints: {},
    // Ребёнок, созданный здесь для записи: имя (lower) → client_id. Живёт дольше формы: повтор записи
    // («время заняли» → другое время, вторая запись подряд) не создаёт второй профиль того же ребёнка.
    childIds: {},
    stack: [],
    view: 'list',
    trainer: null,
    // Поколение открытого тренера и номер запроса слотов: поздний ответ прежнего тренера (или прежней
    // услуги) отбрасывается — иначе карточка Б показывала бы время А и запись ушла бы к А.
    trainerGen: 0,
    slotsSeq: 0,
    dirKey: null,
    serviceId: null,
    slots: null,
    slotsError: false,
    weekStart: null,
    day: null,
    // Экран H: выбранное окно дня. Пусто — первое окно этого дня.
    weekSlot: null,
    // G: дата последнего занятия с ребра (last_completed_at). Нет поля — строки нет.
    lastCompletedAt: null,
    // G: «О тренере, отзывы и дипломы» свёрнуто, пока человек сам не откроет.
    trustOpen: false,
    // Тариф прошлой записи (last_created_booking_service_price_variant_id) — только подпись цены на G.
    pastVariant: null,
    saved: false,
    notify: false,
    waBlock: '',
    saveNote: '',
    entryNote: '',
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
    // Первый GET сессии создаёт её строку; параллельный запрос другого экрана может поймать гонку
    // (уникальный ключ client_sessions) — один повтор.
    var tid = num(qs.get('trainer_id'));
    return BC.fetchClientSession(tid, initData)
      .catch(function () { return BC.fetchClientSession(tid, initData); })
      .catch(function () { return null; });
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
    return api(url).then(M.trainerFromCatalogCard);
  }

  /**
   * Слоты открытого тренера. Промис → true, если ответ применён; false — ответ устарел (за это время
   * открыли другого тренера или запросили слоты заново): `S` не тронут, вызывающий ничего не делает.
   */
  /**
   * @param {{ retain?: boolean }} [opts] retain — не сбрасывать слоты в null на время запроса
   *   (смена вкладки/услуги: иначе на секунду вспыхивает «N мин · ближайшее время»).
   */
  function loadSlots(opts) {
    opts = opts || {};
    var t = S.trainer;
    var seq = ++S.slotsSeq;
    function fresh() { return seq === S.slotsSeq && S.trainer === t; }
    if (!t) return Promise.resolve(true);
    if (!t.can_book) {
      S.slots = [];
      return Promise.resolve(true);
    }
    if (!initData) {
      // Вне Telegram записи нет — показываем окна витрины, запись попросит открыть в Telegram.
      S.slots = (t.windows || []).map(function (w) { return decorateSlot(M.windowToSlot(w), t); });
      return Promise.resolve(true);
    }
    if (!opts.retain) S.slots = null;
    S.slotsError = false;
    var svc = currentService();
    return BC.fetchClientSlots({ trainerId: t.id, serviceId: svc ? svc.service_id : null, initData: initData })
      .then(function (d) {
        if (!fresh()) return false;
        S.slots = M.sortSlots((d && d.slots) || []).map(function (x) { return decorateSlot(x, t); });
        return true;
      })
      .catch(function () {
        if (!fresh()) return false;
        S.slots = [];
        S.slotsError = true;
        return true;
      });
  }

  /** Слот помечается тренером, для которого его загрузили, — запись проверяет, что это открытый тренер. */
  function decorateSlot(s, t) {
    t = t || S.trainer;
    if (t && s.trainer_id == null) s.trainer_id = t.id;
    var a = arenaOf(t, s.arena_id);
    if (a && !s.arena_name) s.arena_name = a.name;
    return s;
  }

  function arenaOf(t, id) {
    var list = (t && t.arenas) || [];
    for (var i = 0; i < list.length; i++) if (Number(list[i].id) === Number(id)) return list[i];
    return null;
  }

  function arenaById(id) {
    return arenaOf(S.trainer, id);
  }

  function loadPasses() {
    var p = !initData || !S.profiles.length ? Promise.resolve() : Promise.all(
      S.profiles.map(function (pr) {
        return api('/api/webapp/client/passes', { profileId: pr.client_id })
          .then(function (d) { S.passes[pr.client_id] = (d && d.items) || []; })
          .catch(function () { S.passes[pr.client_id] = []; });
      })
    );
    // Плашка N появляется после абонементов. Флаг выключен — промис тот же, перерисовки нет.
    if (LISTED_TID) {
      return p.then(function () { if (S.view === 'trainer') render(); });
    }
    return p;
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
    // Экран E заменяет запись: «Назад» возвращает на карточку, не в форму (SPEC §8.1.5). Флаг выключен — как раньше.
    if (unifiedCard() && S.view === 'sent') {
      S.view = 'trainer';
      S.stack = [];
      render();
      window.scrollTo(0, 0);
      return;
    }
    var prev = S.stack.pop();
    if (!prev) {
      // Корень витрины (или тренер по прямой ссылке): есть откуда пришли — туда; иначе тренер → список.
      if (CAME_FROM) {
        leave();
        return;
      }
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

  /** Уйти с витрины туда, откуда пришли (каток, «Поиск», главная, «Сохранённые»). */
  function leave() {
    try { history.back(); } catch (e) { /* */ }
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

  function trainerPhone(t) {
    return String((t && t.phone) || '').trim();
  }

  /** Скопировать телефон тренера — как на записях клиента. */
  function copyTrainerPhone(phone) {
    var p = String(phone || '').trim();
    if (!p) return;
    function ok() {
      if (tg && tg.HapticFeedback) try { tg.HapticFeedback.notificationOccurred('success'); } catch (e) { /* */ }
      if (tg && typeof tg.showAlert === 'function') tg.showAlert('Номер скопирован');
      else try { window.alert('Номер скопирован'); } catch (e2) { /* */ }
    }
    function fail() {
      if (tg && typeof tg.showAlert === 'function') tg.showAlert('Не удалось скопировать. Номер: ' + p);
      else try { window.alert('Не удалось скопировать. Номер: ' + p); } catch (e2) { /* */ }
    }
    if (tg && typeof tg.copyText === 'function') {
      try { tg.copyText(p); ok(); return; } catch (e) { /* */ }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(p).then(ok).catch(fail);
      return;
    }
    fail();
  }

  /**
   * Выходы, когда запись сейчас недоступна: Написать / Заявка / Телефон / Telegram.
   * Sticky и карточки никогда не остаются без хотя бы одного действия, если есть хоть какой-то канал.
   */
  function exitButtons(t, opts) {
    opts = opts || {};
    var bits = [];
    var tidAttr = opts.tid ? ' data-tid="' + t.id + '"' : '';
    if (t.contact_url) {
      bits.push('<button type="button" class="' + (opts.writeClass || 'sec2') + '" data-act="write"' + tidAttr + '>Написать тренеру</button>');
    }
    if (initData && opts.request !== false) {
      bits.push('<button type="button" class="' + (opts.requestClass || 'sec2') + '" data-act="request">Оставить заявку</button>');
    }
    if (trainerPhone(t) && opts.phone !== false) {
      bits.push('<button type="button" class="' + (opts.phoneClass || 'sec2') + '" data-act="copy-phone"' + tidAttr + '>Скопировать телефон</button>');
    }
    // Браузер без Telegram-сессии: как сайт — уводим в Telegram, а не оставляем тупик.
    if (!initData && t.telegram_url && !t.contact_url && opts.openTg !== false) {
      bits.push('<button type="button" class="' + (opts.tgClass || 'cta') + '" data-act="open-tg"' + tidAttr + '>Открыть в Telegram</button>');
    }
    return bits.join('');
  }

  /* ── Общие куски ─────────────────────────────────────────────────── */

  function backBtn(label) {
    // В Telegram «назад» — нативная стрелка в шапке (MiniAppBack); своя кнопка только в браузере.
    if (window.MiniAppBack && window.MiniAppBack.isNative()) return '';
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

  /** Направление всегда закреплено: нужное, если оно у тренера есть, иначе первое его направление. */
  function pinDirection(t, want) {
    var dirs = M.trainerDirections(t);
    if (dirs.some(function (d) { return d.key === want; })) return want;
    return dirs.length ? dirs[0].key : M.DIRECTIONS[0].key;
  }

  /** В направлении несколько услуг — карточка сразу показывает первую выбранной; одна — выбирать нечего. */
  function firstServiceId(t, key) {
    var svcs = M.servicesInDirection(t, key);
    return svcs.length > 1 ? svcs[0].service_id : null;
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

  /** Услуги, которые можно записать на этот слот (онлайн/очно — как проверяет сервер): сначала из направления. */
  function servicesForSlot(t, slot) {
    var fit = M.servicesForSlot(serviceList(t, S.dirKey), slot);
    return fit.length ? fit : M.servicesForSlot(t.services, slot);
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
      return '<div class="bd bd--list"><h1 class="h1a">Учиться с тренером</h1><div class="card"><p>Не удалось загрузить тренеров.</p>' +
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
    var h = '<div class="bd bd--list"><h1 class="h1a">Учиться с тренером</h1>';
    if (!solo) {
      h += '<div class="tabsA" role="tablist">' + M.DIRECTIONS.filter(function (d) {
        return d.key === 'all' || d.key === key || counts[d.key] > 0;
      }).map(function (d) {
        return '<button type="button" role="tab" data-act="tab" data-key="' + d.key + '" aria-selected="' + (d.key === key) + '">' +
          esc(d.title) + '<b>' + counts[d.key] + '</b></button>';
      }).join('') + '</div>';
    }
    h += '<span class="mut">' + esc(dir.lead) + '</span>';
    var minPrice = M.minPriceOf(list, key);
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
    } else {
      // Нет окон (или free-card): выход на карточке списка. Заявку не ставим здесь —
      // openRequest() смотрит S.trainer; заявка — на экране тренера.
      var listExit = exitButtons(t, {
        writeClass: 'alt wide', tid: true,
        phoneClass: 'alt wide', tgClass: 'alt wide', request: false,
      });
      if (listExit) times = listExit;
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

  /** Сохранён ли тренер и подписан ли человек на время — состояние с сервера, не догадка. */
  function loadEdge(t) {
    if (!initData) return;
    var gen = S.trainerGen;
    api('/api/webapp/client/trainer-edges').then(function (d) {
      if (gen !== S.trainerGen) return;
      var e = ((d && d.all) || []).filter(function (x) { return Number(x.trainer_id) === Number(t.id); })[0];
      if (!e) return;
      S.saved = !!e.is_saved;
      S.notify = !!e.notify_when_slots;
      // Поле уже есть в ребре. Пустое или отсутствующее — «Последнее занятие» не показываем.
      S.lastCompletedAt = e.last_completed_at ? e.last_completed_at : null;
      if (S.view === 'trainer' && S.trainer === t) render();
    }).catch(function () { /* не критично: кнопки останутся в исходном состоянии */ });
  }

  function openTrainer(t, opts) {
    opts = opts || {};
    S.trainerGen++;
    S.trainer = t;
    var dirs = M.trainerDirections(t);
    var want = opts.dirKey || (S.tab !== 'all' ? S.tab : null);
    S.dirKey = pinDirection(t, want);
    S.serviceId = num(qs.get('service_id')) && Number(t.id) === num(qs.get('trainer_id')) ? num(qs.get('service_id')) : null;
    if (S.serviceId == null) S.serviceId = firstServiceId(t, S.dirKey);
    // Прошлый формат — last_created_booking_service_* этой сессии с тренером. Чип слота не трогаем:
    // у окна своя услуга, подмена отфильтровала бы его из выдачи.
    S.pastVariant = null;
    if (fromHub() && !qs.get('slot_id') && S.session) {
      var pastSid = Number(S.session.last_created_booking_service_id);
      var hasPast = pastSid > 0 && (t.services || []).some(function (s) { return Number(s.service_id) === pastSid; });
      if (hasPast) {
        S.serviceId = pastSid;
        var pastDir = M.directionKeyForServiceId(pastSid);
        if (pastDir) S.dirKey = pinDirection(t, pastDir);
        var pastVid = Number(S.session.last_created_booking_service_price_variant_id);
        S.pastVariant = pastVid > 0 ? pastVid : null;
      }
    }
    S.saved = false;
    S.notify = false;
    S.lastCompletedAt = null;
    S.trustOpen = false;
    S.weekSlot = null;
    S.waBlock = '';
    S.saveNote = '';
    S.entryNote = '';
    S.shareNote = '';
    S.bioOpen = false;
    loadEdge(t);
    if (opts.view !== false) go('trainer');
    return loadSlots().then(function (fresh) {
      if (fresh) render();
      return fresh;
    });
  }

  function renderTrainer() {
    if (unifiedCard()) return renderTrainerCard();
    var t = S.trainer;
    var dirs = M.trainerDirections(t);
    var svcs = serviceList(t, S.dirKey);
    var svc = currentService() || (svcs.length > 1 ? svcs[0] : null);
    var h = '<div class="bd">' + backBtn(S.stack.length ? 'Тренеры' : CAME_FROM ? 'Назад' : 'Все тренеры') +
      (S.entryNote ? '<div class="entry-note" role="status">' + esc(S.entryNote) + '</div>' : '') + heroHtml(t, trainerSubLine(t));
    h += trustHtml(t);
    h += '<div class="pc">';
    if (!t.can_book) {
      h += '<p>' + esc(M.selfBookingLine(t.first_name, RuName, {
        canWrite: !!t.contact_url, canRequest: !!initData, hasPhone: !!trainerPhone(t),
      })) + '</p></div>';
    } else {
      if (dirs.length > 1) {
        h += '<div class="seg">' + dirs.map(function (d) {
          return '<button type="button" data-act="dir" data-key="' + d.key + '" aria-pressed="' + (d.key === S.dirKey) + '">' + esc(d.title) + '</button>';
        }).join('') + '</div>';
      }
      if (svcs.length > 1) {
        // Несколько услуг в направлении: компактный radiogroup, ниже — деталь выбранной (крючок и тарифы) один раз.
        var dur = t.session_duration_minutes ? t.session_duration_minutes + ' мин' : '';
        h += '<span class="lb" id="svcLb">Какое занятие?</span><div class="svcs" role="radiogroup" aria-labelledby="svcLb">' + svcs.map(function (s) {
          var on = Number(svc.service_id) === Number(s.service_id);
          return '<button type="button" role="radio" data-act="svc" data-sid="' + s.service_id + '" aria-checked="' + on + '"><i></i>' +
            '<span class="nm">' + esc(s.title || s.service_name) + (dur ? '<small>' + esc(dur) + '</small>' : '') + '</span>' +
            '<em>' + esc(M.priceFrom(s)) + '</em></button>';
        }).join('') + '</div>';
      }
      if (svc) {
        if (svc.summary_hook) h += '<p class="hk">' + esc(svc.summary_hook) + '</p>';
        h += tiersHtml(svc);
      }
      var where = svc && svc.is_online ? 'онлайн' : ((t.arenas || []).length === 1 ? t.arenas[0].name : '');
      var lb = [t.session_duration_minutes ? t.session_duration_minutes + ' мин' : '', where, 'ближайшее время'].filter(Boolean).join(' · ');
      // Подпись с длительностью — только когда есть окна. При null (загрузка) её не рисуем:
      // иначе при смене вкладки без слотов «N мин · ближайшее время» мигает и пропадает.
      if (S.slots && S.slots.length) {
        h += '<span class="lb">' + esc(lb) + '</span>';
        h += '<div class="times">' + S.slots.slice(0, 3).map(function (s) { return slotLabel(s, (t.arenas || []).length > 1); }).join('') +
          '<button type="button" class="alt" data-act="week">Другое время</button></div>';
      } else if (S.slots === null) {
        h += '<span style="color:var(--a-hint)">Загружаем время…</span>';
      } else if (S.slotsError) {
        h += '<span style="color:var(--a-hint)">Не удалось загрузить время.</span>';
      }
      h += '</div>';
      if (S.slots && !S.slots.length && !S.slotsError) {
        var emptyHint = initData
          ? 'Попросите сообщить, когда появится, или оставьте заявку.'
          : (t.contact_url ? 'Напишите тренеру или откройте Telegram — там видны следующие недели.'
            : 'Откройте Telegram — там видны следующие недели и можно договориться.');
        h += '<div class="card"><h4>На ближайшие 2 недели свободного времени нет</h4><p class="mut">' + esc(emptyHint) + '</p>' +
          (initData ? '<button type="button" class="sec2" data-act="notify"' + (S.notify ? ' disabled' : '') + '>' +
            (S.notify ? 'Сообщим, когда появится время' : 'Сообщить, когда появится время') + '</button>' : '') +
          (S.waBlock ? '<div class="warn">' + BC.writeAccessBlockHtml(S.waBlock) + '</div>' : '') + '</div>';
      }
      if (S.slotsError) h += '<button type="button" class="sec2" data-act="reslots">Повторить</button>';
    }
    h += aboutCard(svcs, svc);
    h += whereCard(t, svc);
    var duo = svc ? M.whoOptions(svc).duo : [];
    if (duo.length) {
      h += '<div class="card"><h4>Другие тарифы</h4>' + duo.map(function (r) {
        return '<div class="kv"><span>' + esc(r.title) + '</span><b>' + esc(M.formatMoney(r.priceCents, svc.currency_code)) + '</b></div>';
      }).join('') + '</div>';
    }
    if (initData) {
      h += '<button type="button" class="more" data-act="save" aria-pressed="' + !!S.saved + '">' + (S.saved ? '♥ Тренер сохранён · убрать' : '♡ Сохранить тренера') + '</button>';
      if (S.saveNote) h += '<span class="mut" role="alert">' + esc(S.saveNote) + '</span>';
    }
    h += '</div>';
    if (!t.can_book) {
      var freeFt = exitButtons(t, { writeClass: 'cta', requestClass: 'sec2', phoneClass: 'sec2', tgClass: 'cta' });
      if (freeFt) h += '<div class="ft col">' + freeFt + '</div>';
    } else if (S.slots && S.slots.length) {
      var first = S.slots[0];
      h += '<div class="ft"><button type="button" class="cta" data-act="slot" data-slot="' + esc(first.id) + '">Записаться на ' +
        esc(M.ctaDay(first.slot_date, S.todayIso) + ', ' + String(first.start_time).slice(0, 5)) + '</button>' +
        (t.contact_url ? '<button type="button" class="ico" data-act="write" aria-label="Написать тренеру"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg></button>' : '') + '</div>';
    } else if (S.slots !== null) {
      // Нет окон или ошибка загрузки — sticky всегда с выходом (не только «Повторить»).
      var stuckFt = exitButtons(t, { writeClass: 'sec2', requestClass: 'sec2', phoneClass: 'sec2', tgClass: 'cta' });
      if (stuckFt) h += '<div class="ft col">' + stuckFt + '</div>';
    }
    return h;
  }

  /* ── 2u · Единая карточка тренера (TASK-400, SPEC §3.1, макеты A/B/C/F/M) ─────────────────────
     Только при window.__UNIFIED_TRAINER_CARD__ (страница /webapp/trainers при включённом флаге).
     Флаг выключен — renderTrainer() выше, разметка прежняя. Логика записи, «Назад» и входов не меняется. */

  function unifiedCard() {
    return window.__UNIFIED_TRAINER_CARD__ === true;
  }

  /** Вход с хаба под флагом. Флаг выключен — from=hub ничего не меняет. */
  function fromHub() {
    return unifiedCard() && qs.get('from') === 'hub';
  }

  /** №37: «Снова к» — тот же action=book, но карточка G, не неделя. */
  function hubRebookEntry() {
    return fromHub() && qs.get('entry') === 'rebook';
  }

  /** №35: action=book&from=hub без entry=rebook → экран H. */
  function hubWeekEntry() {
    return fromHub() && qs.get('action') === 'book' && !qs.get('slot_id') && !hubRebookEntry();
  }

  /** №34 и №37: карточка вернувшегося (G). */
  function returningCard() {
    return fromHub() && !qs.get('slot_id') && (qs.get('action') !== 'book' || hubRebookEntry());
  }

  var TC_SVG = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
  var TC_ICON = {
    back: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 5-7 7 7 7"/></svg>',
    mail: TC_SVG + '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    pin: TC_SVG + '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11Z"/><circle cx="12" cy="10" r="2.5"/></svg>',
    cap: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 9 9-5 9 5-9 5-9-5Z"/><path d="M7 11.5V16c0 1 2.2 2.5 5 2.5s5-1.5 5-2.5v-4.5"/></svg>',
    chevron: '<svg class="tc-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>',
    down: '<svg class="tc-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
    bell: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 17h12l-1.5-2V10a4.5 4.5 0 0 0-9 0v5L6 17Z"/><path d="M10 20h4"/></svg>',
    share: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 15V4"/><path d="m7.5 8.5 4.5-4.5 4.5 4.5"/><path d="M5 13v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/></svg>',
    search: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    check: '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
  };
  function tcHeart(on) {
    return '<svg width="20" height="20" viewBox="0 0 24 24" fill="' + (on ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z"/></svg>';
  }

  var TC_WEEKDAY = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

  /** «сб, 10:00», «9:00» без ведущего нуля (SPEC §5.2, §10). */
  function tcWhen(slot) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(slot.slot_date || ''));
    var wd = m ? TC_WEEKDAY[new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()] : '';
    var time = String(slot.start_time || '').slice(0, 5).replace(/^0(\d)/, '$1');
    return wd ? wd + ', ' + time : time;
  }

  function tcFirstName(t) {
    return String((t && t.first_name) || '').trim().split(/\s+/)[0] || 'Тренер';
  }

  /** Плашка фактов: factStrip из TASK-399 (опыт → кого учит → каток ≤10 знаков или «от N»). <2 фактов — нет. */
  function tcFacts(t) {
    var facts = M.factStrip({
      experience_years: t.experience_years,
      tier_kinds: M.tierKinds(t.services || []),
      rink_name: t.primary_arena_name,
      price_cents: t.min_session_price_cents,
      currency: t.min_session_price_currency,
    });
    if (!facts.length) return '';
    return '<ul class="tc-facts tc-facts--' + facts.length + '" aria-label="Коротко о тренере">' + facts.map(function (f) {
      return '<li><b>' + esc(f.value) + '</b><span>' + esc(f.label) + '</span></li>';
    }).join('') + '</ul>';
  }

  /** «★ 4,9 · 14 оценок · В Glide с сентября 2026» — части независимы, нет данных — нет части. */
  function tcMetaLine(t) {
    var parts = [];
    var cap = M.ratingLine(t.rating_avg, t.rating_count);
    var m = /^★\s*([\d,]+)\s*·\s*(.+)$/.exec(cap || '');
    if (m) {
      parts.push('<span role="img" aria-label="Оценка ' + esc(m[1]) + ' из 5"><span class="tc-star" aria-hidden="true">★</span> ' + esc(m[1]) + '</span>');
      parts.push(esc(m[2]));
    }
    var since = M.glideSince(t.glide_since);
    if (since) parts.push(esc(since));
    return parts.length ? '<p class="tc-hero-meta">' + parts.join(' · ') + '</p>' : '';
  }

  /** «направления · город». Города нет — хвоста нет (SPEC §3.1, решение по эскалации). */
  function tcDirLine(t) {
    var titles = M.trainerDirections(t).map(function (d) { return d.title; }).filter(Boolean);
    var city = String((t && t.city_name) || '').trim();
    if (city) titles.push(city);
    return titles.join(' · ');
  }

  /** Без фото под именем: «город · каток» (SPEC §6.2). Нет части — её нет в строке. */
  function tcPlaceLine(t) {
    var rink = t.primary_arena_name || ((t.arenas || []).length === 1 ? t.arenas[0].name : '');
    var city = String((t && t.city_name) || '').trim();
    return [city, rink].filter(Boolean).join(' · ');
  }

  function tcHero(t) {
    var dirs = M.trainerDirections(t);
    var dirLine = tcDirLine(t);
    var capLine = dirs.map(function (d) { return d.title; }).filter(Boolean).join(' · ');
    var backLabel = S.stack.length ? 'Тренеры' : CAME_FROM ? 'Назад' : 'Все тренеры';
    // «Назад» — как прежде: в Telegram нативная стрелка в шапке, своя кнопка только в браузере (TASK-403 не трогаем).
    var btns = backBtn(backLabel)
      ? '<button type="button" class="tc-hbtn tc-hbtn--back" data-act="back" aria-label="' + esc(backLabel) + '">' + TC_ICON.back + '</button>'
      : '';
    if (initData) {
      btns += '<button type="button" class="tc-hbtn tc-hbtn--save" data-act="save" aria-label="Сохранить тренера" aria-pressed="' + !!S.saved + '">' + tcHeart(S.saved) + '</button>';
    }
    var meta = tcMetaLine(t);
    if (t.photo_url) {
      return '<header class="tc-hero tc-hero--photo"><img src="' + esc(t.photo_url) + '" alt="">' + btns +
        '<div class="tc-hero-t"><h1>' + esc(t.name) + '</h1>' + (dirLine ? '<p class="tc-hero-sub">' + esc(dirLine) + '</p>' : '') + meta + '</div></header>';
    }
    // Без фото — типографский герой (SPEC §6.2): капсула направления, крупное имя, «город · каток».
    var hockey = dirs.length > 0 && dirs.every(function (d) { return d.key === 's-klyushkoy'; });
    var place = tcPlaceLine(t);
    return '<header class="tc-hero tc-hero--noph' + (hockey ? ' tc-hero--hockey' : '') + '">' +
      '<svg class="tc-lines" viewBox="0 0 390 300" preserveAspectRatio="none" fill="none" aria-hidden="true"><path d="M-20 215 C 90 175, 200 225, 410 155" stroke-width="2"/><path d="M-20 247 C 110 207, 230 257, 410 192" stroke-width="2" opacity=".66"/></svg>' +
      btns + '<div class="tc-hero-t">' + (capLine ? '<span class="tc-cap">' + esc(capLine) + '</span>' : '') +
      '<h1>' + esc(t.name) + '</h1>' + (place ? '<p class="tc-hero-sub">' + esc(place) + '</p>' : '') + meta + '</div></header>';
  }

  /** Плитки тарифов направления: Ребёнок/Взрослый. Одинаковые цены — по-прежнему две плитки (SPEC §5.1). */
  function tcTiles(svc) {
    var cur = (svc && svc.currency_code) || 'BYN';
    return M.whoOptions(svc).single
      .filter(function (r) { return r.priceCents != null && r.priceCents > 0; })
      .map(function (r) { return { title: r.title, price: M.formatMoney(r.priceCents, cur) }; });
  }

  function tcChip(slot, i, many) {
    var small = [];
    if (many && slot.arena_name) small.push(slot.arena_name);
    if (slot.capacity > 1 && slot.spots_left != null) small.push('осталось ' + M.word(slot.spots_left, 'место', 'места', 'мест'));
    return '<button type="button" class="tc-chip' + (i === 0 ? ' is-first' : '') + (small.length ? ' tc-chip--2' : '') + '" data-act="slot" data-slot="' + esc(slot.id) + '">' +
      esc(tcWhen(slot)) + (small.length ? '<small>' + esc(small.join(' · ')) + '</small>' : '') + '</button>';
  }

  /** Время: чипы (до 3) + «Другое время» / загрузка без прыжка / ошибка / «окон нет» (C, SPEC §6.3). */
  function tcTimes(t) {
    if (S.slots === null) {
      return '<span class="tc-vh" role="status">Загружаем время…</span><div class="tc-times" aria-hidden="true"><i class="tc-sk"></i><i class="tc-sk"></i><i class="tc-sk"></i></div>';
    }
    if (S.slotsError) {
      // L1 (доска States 1): «Повторить» и «Написать» в ряд. Нет Telegram — ни кнопки «Написать», ни строки о ней.
      var write = t.contact_url
        ? '<button type="button" class="tc-sec" data-act="write">Написать</button>'
        : '';
      return '<p class="tc-empty-t">Не удалось загрузить время</p>' +
        '<p class="tc-empty-p">Проверьте сеть и повторите.' + (t.contact_url ? ' Тренеру можно и написать.' : '') + '</p>' +
        '<div class="tc-l1-acts"><button type="button" class="tc-sec tc-sec--main" data-act="reslots">Повторить</button>' + write + '</div>';
    }
    if (!S.slots.length) {
      var hint = initData
        ? (t.contact_url ? 'Напишите тренеру — время можно согласовать. Или попросите сообщить, когда оно появится.'
          : 'Попросите сообщить, когда появится, или оставьте заявку.')
        : (t.contact_url ? 'Напишите тренеру или откройте Telegram — там видны следующие недели.'
          : 'Откройте Telegram — там видны следующие недели и можно договориться.');
      return '<p class="tc-empty-t">На ближайшие 2 недели свободного времени нет</p><p class="tc-empty-p">' + esc(hint) + '</p>' +
        (initData ? '<button type="button" class="tc-sec tc-sec--in" data-act="notify"' + (S.notify ? ' disabled' : '') + '>' + TC_ICON.bell +
          (S.notify ? 'Сообщим, когда появится время' : 'Сообщить, когда появится время') + '</button>' : '') +
        (S.waBlock ? '<div class="warn">' + BC.writeAccessBlockHtml(S.waBlock) + '</div>' : '');
    }
    var many = (t.arenas || []).length > 1;
    return '<div class="tc-times">' + S.slots.slice(0, 3).map(function (s, i) { return tcChip(s, i, many); }).join('') +
      '<button type="button" class="tc-chip tc-chip--alt" data-act="week">Другое время</button></div>';
  }

  /** Карточка цены (только can_book): направления → занятие → тарифы → время (макеты A, B, C, M3–M7). */
  function tcPriceCard(t, dirs, svcs, svc) {
    var h = '<section class="tc-card tc-pc" aria-label="Цена и время">';
    if (dirs.length > 1) {
      h += '<div class="tc-seg" role="group" aria-label="Занятие">' + dirs.map(function (d) {
        return '<button type="button" data-act="dir" data-key="' + d.key + '" aria-pressed="' + (d.key === S.dirKey) + '">' + esc(d.title) + '</button>';
      }).join('') + '</div>';
    }
    if (svcs.length > 1) {
      var dur0 = t.session_duration_minutes ? t.session_duration_minutes + ' мин' : '';
      h += '<span class="tc-lb" id="svcLb">Какое занятие?</span><div class="svcs" role="radiogroup" aria-labelledby="svcLb">' + svcs.map(function (s) {
        var on = Number(svc.service_id) === Number(s.service_id);
        return '<button type="button" role="radio" data-act="svc" data-sid="' + s.service_id + '" aria-checked="' + on + '"><i></i>' +
          '<span class="nm">' + esc(s.title || s.service_name) + (dur0 ? '<small>' + esc(dur0) + '</small>' : '') + '</span>' +
          '<em>' + esc(M.priceFrom(s)) + '</em></button>';
      }).join('') + '</div>';
    }
    var online = !!(svc && svc.is_online);
    var n = (t.arenas || []).length;
    var where = online ? 'онлайн' : n === 1 ? t.arenas[0].name : n > 1 ? M.word(n, 'каток', 'катка', 'катков') : '';
    var dur = t.session_duration_minutes ? t.session_duration_minutes + ' мин' : '';
    var has = !!(S.slots && S.slots.length);
    var tiles = svc ? tcTiles(svc) : [];
    if (tiles.length > 1) {
      h += '<div class="tc-tiles">' + tiles.map(function (x) { return '<div><small>' + esc(x.title) + '</small><b>' + esc(x.price) + '</b></div>'; }).join('') + '</div>';
      // Подпись на месте и при загрузке: меняется только текст, высота та же — время не прыгает.
      var lb = has ? [dur, where, 'ближайшее время'].filter(Boolean).join(' · ') : 'Ближайшее время';
      h += '<p class="tc-lb">' + esc(lb) + '</p>' + tcTimes(t);
    } else {
      // Одна цена (макет B): «Ближайшее время» и длительность с катком справа, цена строкой внизу.
      var meta = [dur, where].filter(Boolean).join(' · ');
      h += '<div class="tc-lbrow"><p class="tc-lb">Ближайшее время</p>' + (has && meta ? '<span>' + esc(meta) + '</span>' : '') + '</div>';
      h += tcTimes(t);
      var price = svc ? M.priceFrom(svc) : '';
      if (price) h += '<div class="tc-one"><span>' + esc((svc && (svc.title || svc.service_name)) || 'Занятие') + '</span><b>' + esc(price) + '</b></div>';
      else h += '<p class="tc-one tc-one--none"><b>Цену уточните у тренера</b></p>';
    }
    if (online && has) h += '<p class="tc-note">Ссылку пришлёт тренер после подтверждения. Билет и прокат не нужны.</p>';
    return h + '</section>';
  }

  /** «О тренере» — слова тренера дословно; «Читать полностью» — только если текст длиннее 5 строк. */
  function tcAbout(t) {
    var bio = M.tidyText(t.description);
    if (!bio) return '';
    return '<section class="tc-card" aria-labelledby="tcAboutH"><h2 class="tc-h2" id="tcAboutH">О тренере</h2>' +
      '<p class="tc-bio' + (S.bioOpen ? ' open' : '') + '" id="tcBio">' + esc(bio) + '</p>' +
      (S.bioOpen ? '' : '<button type="button" class="tc-link" data-act="bio-more" aria-controls="tcBio" aria-expanded="false" hidden>Читать полностью</button>') +
      '</section>';
  }

  function tcEducation(t) {
    var e = String(t.education || '').trim();
    if (!e) return '';
    return '<section class="tc-card" aria-labelledby="tcEduH"><h2 class="tc-h2" id="tcEduH">Образование и дипломы</h2>' +
      '<ul class="tc-list"><li><span class="tc-ic tc-ic--sm">' + TC_ICON.cap + '</span><b>' + esc(e) + '</b></li></ul></section>';
  }

  /** «Где проходят занятия»: каток, адрес, прокат — до записи. Онлайн — формат в карточке цены (M4). */
  function tcWhere(t, svc) {
    if (svc && svc.is_online) return '';
    var arenas = t.arenas || [];
    if (!arenas.length) return '';
    var rows = arenas.map(function (a) {
      var sub = [a.address || '', a.rental_cents ? 'прокат ' + M.formatMoney(a.rental_cents, a.rental_currency) : ''].filter(Boolean).join(' · ');
      var inner = '<span class="tc-ic">' + TC_ICON.pin + '</span><span class="tc-where-t"><b>' + esc(a.name) + '</b>' +
        (sub ? '<span>' + esc(sub) + '</span>' : '') + '</span>';
      return a.map_link
        ? '<button type="button" class="tc-where-row" data-act="map" data-href="' + esc(a.map_link) + '">' + inner + TC_ICON.chevron + '</button>'
        : '<div class="tc-where-row">' + inner + '</div>';
    }).join('');
    return '<section class="tc-card" aria-labelledby="tcWhereH"><h2 class="tc-h2" id="tcWhereH">Где проходят занятия</h2>' + rows +
      '<p class="tc-note tc-note--sm">Билет на сеанс покупается в кассе катка.</p></section>';
  }

  function tcOtherTariffs(svc) {
    var duo = svc ? M.whoOptions(svc).duo : [];
    if (!duo.length) return '';
    return '<section class="tc-card" aria-labelledby="tcTariffsH"><h2 class="tc-h2" id="tcTariffsH">Другие тарифы</h2><div class="tc-rows">' + duo.map(function (r) {
      return '<div><span>' + esc(r.title) + '</span><b>' + esc(M.formatMoney(r.priceCents, svc.currency_code)) + '</b></div>';
    }).join('') + '</div></section>';
  }

  /** Выходы без записи: первый — главный. F — «Оставить заявку» первым (SPEC §5.3), C — «Написать тренеру». */
  function tcExitFooter(t, requestFirst) {
    var acts = [];
    if (t.contact_url) acts.push({ act: 'write', label: 'Написать тренеру' });
    if (initData) acts[requestFirst ? 'unshift' : 'push']({ act: 'request', label: 'Оставить заявку' });
    if (trainerPhone(t)) acts.push({ act: 'copy-phone', label: 'Скопировать телефон' });
    if (!initData && t.telegram_url && !t.contact_url) acts.push({ act: 'open-tg', label: 'Открыть в Telegram' });
    if (!acts.length) return '';
    return '<div class="ft col tc-ft">' + acts.map(function (a, i) {
      var btn = '<button type="button" class="' + (i === 0 ? 'cta' : 'sec2') + '" data-act="' + a.act + '">' + a.label + '</button>';
      return btn + (i === 0 && a.act === 'request' ? '<small>Ответ придёт в Telegram</small>' : '');
    }).join('') + '</div>';
  }

  function renderTrainerCard() {
    if (returningCard()) return renderReturningCard();
    var t = S.trainer;
    var dirs = M.trainerDirections(t);
    var svcs = serviceList(t, S.dirKey);
    var svc = currentService() || (svcs.length > 1 ? svcs[0] : null);
    var h = '<div class="tc">' + tcHero(t) + tcFacts(t) + '<div class="tc-body">';
    if (screenN_isListed(t)) h += screenN_banner(t);
    if (S.entryNote) h += '<div class="entry-note" role="status">' + esc(S.entryNote) + '</div>';
    if (t.can_book) h += tcPriceCard(t, dirs, svcs, svc);
    h += tcAbout(t);
    h += aboutCard(svcs, svc, { unified: true });
    h += tcEducation(t);
    h += tcWhere(t, svc);
    h += tcOtherTariffs(svc);
    if (initData) {
      h += '<div class="tc-acts"><button type="button" class="tc-sec" data-act="save" aria-pressed="' + !!S.saved + '">' +
        (S.saved ? '♥ Тренер сохранён · убрать' : '♡ Сохранить тренера') + '</button>' +
        '<button type="button" class="tc-sec" data-act="share">' + TC_ICON.share + 'Поделиться тренером</button></div>';
      if (S.saveNote) h += '<span class="mut" role="alert">' + esc(S.saveNote) + '</span>';
      if (S.shareNote) h += '<span class="mut" role="alert">' + esc(S.shareNote) + '</span>';
    }
    h += '</div></div>';
    if (!t.can_book) return h + tcExitFooter(t, true);
    if (S.slots && S.slots.length) {
      var first = S.slots[0];
      return h + '<div class="ft col tc-ft"><div class="tc-ft-row"><button type="button" class="cta" data-act="slot" data-slot="' + esc(first.id) + '">Записаться на ' +
        esc(tcWhen(first)) + '</button>' +
        (t.contact_url ? '<button type="button" class="ico" data-act="write" aria-label="Написать тренеру">' + TC_ICON.mail + '</button>' : '') + '</div>' +
        (initData ? '<small>' + esc(tcFirstName(t)) + ' подтвердит — сообщение придёт в Telegram</small>' : '') + '</div>';
    }
    if (S.slots !== null) return h + tcExitFooter(t, false);
    return h;
  }

  /** Скелетон карточки по прямой ссылке (M1): герой, плашка и карточка цены на своих местах — без прыжка. */
  function renderTrainerSkeleton() {
    return '<div class="tc tc--sk" aria-busy="true"><span class="tc-vh" role="status">Загружаем карточку тренера…</span>' +
      '<div class="tc-hero tc-sk-hero" aria-hidden="true"></div><div class="tc-facts tc-facts--3" aria-hidden="true"><i></i><i></i><i></i></div>' +
      '<div class="tc-body" aria-hidden="true"><div class="tc-card"><i class="tc-sk-line"></i><i class="tc-sk-line tc-sk-line--short"></i>' +
      '<div class="tc-times"><i class="tc-sk"></i><i class="tc-sk"></i><i class="tc-sk"></i></div></div></div></div>';
  }

  /** «Читать полностью» показываем, только когда текст правда обрезан (после отрисовки, по пикселям). */
  function tcAfterRender() {
    if (!appEl.querySelector) return;
    var bio = appEl.querySelector('.tc-bio');
    var more = appEl.querySelector('[data-act="bio-more"]');
    if (bio && more) more.hidden = !(bio.scrollHeight > bio.clientHeight + 1);
    fitFacts(appEl.querySelector('.tc-facts'));
    // Dela догружается после первой отрисовки и шире запасного шрифта — подгоняем ещё раз.
    var fonts = document.fonts;
    if (fonts && fonts.status !== 'loaded' && fonts.ready) {
      fonts.ready.then(function () { if (S.view === 'trainer') fitFacts(appEl.querySelector('.tc-facts')); });
    }
  }

  /**
   * Плашка не переполняется (SPEC §12): Dela широкий — ««Замок»» в 20px шире колонки и на 390.
   * Слово не влезает — уменьшаем шрифт всей плашки (одинаковый у всех фактов), слова не рвём. Не меньше 12px.
   */
  function fitFacts(ul) {
    if (!ul || !ul.style) return;
    var base = /tc-facts--2/.test(ul.className) ? 24 : 20;
    var bs = ul.querySelectorAll('b');
    var size = base;
    ul.style.setProperty('--tc-fact-fs', size + 'px');
    function overflows() {
      for (var i = 0; i < bs.length; i++) if (bs[i].scrollWidth > bs[i].clientWidth + 0.5) return true;
      return false;
    }
    while (size > 12 && overflows()) {
      size -= 0.5;
      ul.style.setProperty('--tc-fact-fs', size + 'px');
    }
  }

  window.addEventListener('resize', function () {
    if (S.view === 'trainer' && unifiedCard() && appEl.querySelector) fitFacts(appEl.querySelector('.tc-facts'));
  });

  /** «Поделиться тренером» (ENTRIES №53): тот же API и лист Telegram, что у старой карточки каталога. */
  function shareTrainer(el) {
    var t = S.trainer;
    if (!t || !initData) return;
    var tid = t.id;
    el.disabled = true;
    S.shareNote = '';
    api('/api/webapp/client/share-trainer/' + encodeURIComponent(tid) + '?share_context=catalog')
      .then(function (d) {
        el.disabled = false;
        var url = String((d && d.share_url) || '').trim();
        var body = String((d && d.share_body) || '').trim();
        var text = String((d && d.share_text) || '').trim();
        if (!url && !text) throw new Error('empty');
        if (typeof window.openTelegramShareUrlFromMiniApp === 'function') {
          window.openTelegramShareUrlFromMiniApp({ shareUrl: url, shareBody: body, fullMessage: text });
          return;
        }
        openLink(url
          ? 'https://t.me/share/url?url=' + encodeURIComponent(url) + (body ? '&text=' + encodeURIComponent(body) : '')
          : 'https://t.me/share/url?text=' + encodeURIComponent(text));
      })
      .catch(function () {
        el.disabled = false;
        if (!S.trainer || S.trainer.id !== tid) return;
        S.shareNote = 'Не получилось — попробуйте ещё раз.';
        render();
      });
  }

  /** Под фото: кто это — слова тренера и проверяемые факты, до цены и времени. */
  function trustHtml(t) {
    var chips = [];
    if (t.education) chips.push(t.education);
    var who = M.whoTeaches(t.services || []);
    if (who) chips.push('Учит ' + who);
    var n = (t.arenas || []).length;
    if (n === 1) chips.push(t.arenas[0].name);
    else if (n > 1) chips.push(M.word(n, 'каток', 'катка', 'катков'));
    if (t.session_duration_minutes) chips.push('Занятие ' + t.session_duration_minutes + ' мин');
    var bio = M.tidyText(t.description);
    if (!bio && !chips.length) return '';
    return '<div class="trust">' + (bio ? '<p class="bio" data-act="bio">' + esc(bio) + '</p>' : '') +
      (chips.length ? '<ul class="chips">' + chips.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ul>' : '') + '</div>';
  }

  function tiersHtml(svc, tag) {
    tag = tag || 'div';
    var o = '<' + tag + '>', c = '</' + tag + '>';
    var rows = M.priceRows(svc);
    var inner;
    if (rows.length) {
      inner = rows.map(function (r) {
        return o + '<small>' + esc(r.title) + '</small><b>' + esc(r.price) + '</b>' + c;
      }).join('');
    } else {
      inner = o + '<small>Занятие</small><b>' + M.cardPriceHtml(svc).replace(/<\/?b>/g, '') + '</b>' + c;
    }
    return '<' + tag + ' class="tiers">' + inner + c;
  }

  /** Карточка «О занятии»: наши тексты услуги + слова тренера дословно + «Не входит в цену». Данных нет — карточки нет. */
  function aboutCard(svcs, svc, opts) {
    opts = opts || {};
    var targets = svc ? [svc] : svcs;
    var named = svcs.length > 1;
    var parts = targets.map(function (s) {
      var a = M.serviceAbout(s);
      if (!a) return '';
      var h = '<div class="ab">';
      if (named && a.title) h += '<b class="abt">' + esc(a.title) + '</b>';
      if (a.hook) h += '<p class="abh">' + esc(a.hook) + '</p>';
      a.body.forEach(function (p) { h += '<p>' + esc(p) + '</p>'; });
      if (a.words) h += '<blockquote class="words"><p>' + esc(a.words) + '</p><cite>Слова тренера</cite></blockquote>';
      if (a.notice) {
        h += '<p class="nt">' + (a.notice.lead ? '<span>Не входит в цену</span>' : '<span>Заметка тренера</span>') + esc(a.notice.text) + '</p>';
      }
      return h + '</div>';
    }).filter(Boolean);
    if (!parts.length) return '';
    if (opts.unified) {
      return '<section class="card tc-card" aria-labelledby="tcLessonH"><h2 class="tc-h2" id="tcLessonH">О занятии</h2>' + parts.join('') + '</section>';
    }
    return '<div class="card"><h4>О занятии</h4>' + parts.join('') + '</div>';
  }

  /** Как связаться с тренером перед занятием: только реальные каналы, без пустых кнопок. */
  function contactActs(t) {
    var bits = [];
    if (t.contact_url) bits.push('<button type="button" class="sec2" data-act="write">Написать тренеру</button>');
    if (trainerPhone(t)) bits.push('<button type="button" class="sec2" data-act="copy-phone">Скопировать телефон</button>');
    return bits.join('');
  }

  /** «Где встретимся»: каток, адрес, маршрут и как найти тренера за 15 минут до начала. */
  function meetHtml(t, arenas, opts) {
    opts = opts || {};
    var rows = (arenas || []).filter(Boolean).map(function (a) {
      return '<div class="mt-place"><div><b>' + esc(a.name) + '</b>' + (a.address ? '<span>' + esc(a.address) + '</span>' : '') +
        (opts.rental && a.rental_cents ? '<span>Прокат коньков ' + esc(M.formatMoney(a.rental_cents, a.rental_currency)) + '</span>' : '') + '</div>' +
        (a.map_link ? '<button type="button" class="mt-route" data-act="map" data-href="' + esc(a.map_link) + '">Маршрут</button>' : '') + '</div>';
    }).join('');
    var acts = contactActs(t);
    var who = M.dativeFirst(t.first_name, RuName);
    var verb = t.contact_url && trainerPhone(t) ? 'напишите или позвоните' : t.contact_url ? 'напишите' : 'позвоните';
    var lead = acts
      ? 'Приходите за 15 минут до начала — ' + verb + ' ' + esc(who) + ', и вас встретят у входа.'
      : 'Приходите за 15 минут до начала. ' + esc(t.first_name) + ' напишет вам в чат с ботом, где встретиться.';
    var meetHead = unifiedCard() ? '<h2 class="tc-h2">Где встретимся</h2>' : '<h4>Где встретимся</h4>';
    return '<div class="card meet">' + meetHead + rows + '<p class="mt-lead">' + lead + '</p>' +
      (acts ? '<div class="mt-acts">' + acts + '</div>' : '') +
      (opts.rental ? '<p class="mut" style="font-size:12.5px">Билет на сеанс покупается в кассе катка.</p>' : '') + '</div>';
  }

  function whereCard(t, svc) {
    if (svc && svc.is_online) return '<div class="card"><h4>Где проходят занятия</h4><p>Онлайн.</p></div>';
    var arenas = t.arenas || [];
    if (!arenas.length) return '';
    return meetHtml(t, arenas, { rental: true });
  }

  /* ── 3 · Другое время ────────────────────────────────────────────── */

  function openWeek() {
    if (unifiedCard()) {
      S.day = null;
      S.weekSlot = null;
      go('week');
      return;
    }
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

  var TC_MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
    'сентября', 'октября', 'ноября', 'декабря'];
  var TC_WEEKDAY_FULL = ['Воскресенье', 'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота'];

  /** «2 ноября». Неразобранная дата — пусто, строку не показываем. */
  function tcDayMonth(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || '').slice(0, 10));
    if (!m) return '';
    var mo = TC_MONTHS[+m[2] - 1];
    return mo ? String(+m[3]) + ' ' + mo : '';
  }

  function tcWeekdayFull(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || '').slice(0, 10));
    if (!m) return '';
    return TC_WEEKDAY_FULL[new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()] || '';
  }

  function tcInitials(t) {
    var parts = String((t && t.name) || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '';
    return (parts[0].charAt(0) + (parts[1] ? parts[1].charAt(0) : '')).toLocaleUpperCase('ru');
  }

  /** Кнопка «Назад» как на записи: в Telegram её нет, там нативная стрелка. */
  function tcBarBack() {
    if (window.MiniAppBack && window.MiniAppBack.isNative()) return '';
    var label = S.stack.length ? 'Тренеры' : CAME_FROM ? 'Назад' : 'Все тренеры';
    return '<button type="button" class="tc-bback" data-act="back" aria-label="' + esc(label) + '">' + TC_ICON.back + '</button>';
  }

  function horizonEndIso() {
    return slotsHorizonIso();
  }

  function horizonDays() {
    var end = horizonEndIso();
    var out = [];
    var iso = S.todayIso;
    while (iso && iso <= end) {
      out.push(iso);
      iso = M.addDays(iso, 1);
    }
    return out;
  }

  function slotsOn(iso) {
    return (S.slots || []).filter(function (s) { return s.slot_date === iso && s.slot_date <= horizonEndIso() && s.slot_date >= S.todayIso; });
  }

  function chooseHorizonDay() {
    if (S.slots === null) {
      if (!S.day) S.day = S.todayIso;
      return;
    }
    var days = horizonDays();
    var still = S.day && days.indexOf(S.day) >= 0 && slotsOn(S.day).length;
    if (!still) {
      var found = days.filter(function (d) { return slotsOn(d).length; })[0];
      S.day = found || S.todayIso;
      S.weekSlot = null;
    }
  }

  function pickedHorizonSlot() {
    var rows = slotsOn(S.day);
    var cur = rows.filter(function (s) { return String(s.id) === String(S.weekSlot); })[0];
    return cur || rows[0] || null;
  }

  function gPriceRow(svc) {
    if (!svc) return '';
    var rows = M.whoOptions(svc).single.filter(function (r) { return r.priceCents > 0; });
    var row = S.pastVariant ? rows.filter(function (r) { return r.variantId === S.pastVariant; })[0] : null;
    if (!row && rows.length === 1) row = rows[0];
    if (!row) return '';
    var money = M.formatMoney(row.priceCents, svc.currency_code || 'BYN');
    if (!money) return '';
    return '<div class="tc-g-price"><span>' + esc(row.title) + '</span><b>' + esc(money) + '</b></div>';
  }

  function gRink(t) {
    var arenas = t.arenas || [];
    var primary = String(t.primary_arena_name || '').trim();
    var a = arenas.filter(function (x) { return primary && (x.name === primary || x.name === primary.replace(/[«»]/g, '')); })[0] || arenas[0];
    var name = (a && a.name) || primary;
    if (!name) return '';
    var sub = [a && a.address, 'основной каток'].filter(Boolean).join(' · ');
    var inner = '<span class="tc-ic">' + TC_ICON.pin + '</span><span class="tc-where-t"><b>' + esc(name) + '</b>' +
      (sub ? '<span>' + esc(sub) + '</span>' : '') + '</span>';
    if (a && a.map_link) {
      return '<button type="button" class="tc-g-rink" data-act="map" data-href="' + esc(a.map_link) + '">' + inner + '</button>';
    }
    return '<div class="tc-g-rink">' + inner + '</div>';
  }

  /** G · карточка вернувшегося (доска MyTrainer). Обычная карточка — renderTrainerCard выше. */
  function renderReturningCard() {
    var t = S.trainer;
    var svcs = serviceList(t, S.dirKey);
    var svc = currentService() || (svcs.length > 1 ? svcs[0] : null);
    var back = tcBarBack();
    var heart = initData
      ? '<button type="button" class="tc-g-icon" data-act="save" aria-label="' + (S.saved ? 'Тренер сохранён' : 'Сохранить тренера') + '" aria-pressed="' + !!S.saved + '">' + tcHeart(S.saved) + '</button>'
      : '';
    var dirLine = tcDirLine(t);
    // last_completed_at — дата создания записи, не занятия. Честной даты нет — строки нет.
    var h = '<div class="tc tc-g"><div class="tc-gbar">' + back + heart + '</div><div class="tc-g-pad">';
    h += '<div class="tc-g-who">' + (t.photo_url
      ? '<img class="tc-g-ava" src="' + esc(t.photo_url) + '" alt="">'
      : '<div class="tc-g-ava tc-g-ava--i" aria-hidden="true">' + esc(tcInitials(t)) + '</div>') +
      '<div class="tc-g-id"><h1>' + esc(t.name) + '</h1>' +
      (dirLine ? '<p>' + esc(dirLine) + '</p>' : '') + '</div></div>';
    if (t.can_book) h += gBookCard(t, svc);
    var trustBits = [tcAbout(t), tcEducation(t)].filter(Boolean);
    if (trustBits.length) {
      h += '<button type="button" class="tc-g-trust" data-act="trust" aria-expanded="' + !!S.trustOpen + '">О тренере и дипломы' + TC_ICON.down + '</button>';
      if (S.trustOpen) h += '<div class="tc-g-trust-b">' + trustBits.join('') + '</div>';
    }
    h += gRink(t);
    h += '</div></div>';
    if (!t.can_book) return h + tcExitFooter(t, true);
    var first = (S.slots && S.slots.length) ? S.slots[0] : null;
    if (first) {
      return h + '<div class="ft col tc-ft"><div class="tc-ft-row"><button type="button" class="cta" data-act="slot" data-slot="' + esc(first.id) + '">Записаться снова на ' +
        esc(tcWhen(first)) + '</button>' +
        (t.contact_url ? '<button type="button" class="ico" data-act="write" aria-label="Написать тренеру">' + TC_ICON.mail + '</button>' : '') + '</div>' +
        (initData ? '<small>' + esc(tcFirstName(t)) + ' подтвердит — сообщение придёт в Telegram</small>' : '') + '</div>';
    }
    if (S.slots !== null && !S.slotsError) return h + tcExitFooter(t, false);
    return h;
  }

  function gBookCard(t, svc) {
    var h = '<section class="tc-card tc-g-book" aria-label="Записаться снова">';
    h += '<div class="tc-g-kicker">Записаться снова</div>';
    if (S.slots === null) {
      return h + '<span class="tc-vh" role="status">Загружаем время…</span><div class="tc-times" aria-hidden="true"><i class="tc-sk"></i><i class="tc-sk"></i></div></section>';
    }
    if (S.slotsError) {
      var write = t.contact_url ? '<button type="button" class="tc-sec" data-act="write">Написать</button>' : '';
      return h + '<p class="tc-empty-t">Не удалось загрузить время</p>' +
        '<p class="tc-empty-p">Проверьте сеть и повторите.' + (t.contact_url ? ' Тренеру можно и написать.' : '') + '</p>' +
        '<div class="tc-l1-acts"><button type="button" class="tc-sec tc-sec--main" data-act="reslots">Повторить</button>' + write + '</div></section>';
    }
    var first = S.slots[0];
    if (!first) {
      return h + '<p class="tc-empty-t">На ближайшие 2 недели свободного времени нет</p></section>';
    }
    h += '<div class="tc-g-when">' + esc(screenL_slotTitle(first)) + '</div>';
    var bits = [];
    if (first.arena_name) bits.push(first.arena_name);
    var fmt = svc && (svc.title || svc.service_name);
    if (fmt) bits.push(fmt);
    if (t.session_duration_minutes) bits.push(t.session_duration_minutes + ' мин');
    if (bits.length) h += '<p class="tc-g-meta">' + esc(bits.join(' · ')) + '</p>';
    var rest = S.slots.slice(1, 3);
    h += '<div class="tc-g-times">' + rest.map(function (s) {
      return '<button type="button" class="tc-chip" data-act="slot" data-slot="' + esc(s.id) + '">' + esc(tcWhen(s)) + '</button>';
    }).join('') + '<button type="button" class="tc-chip tc-chip--alt" data-act="week">Другое время</button></div>';
    var price = gPriceRow(svc);
    if (price) h += price;
    return h + '</section>';
  }

  /** H · время на две недели (доска Week). Горизонт — окно /client/slots: сегодня до воскресенья следующей недели. */
  function renderWeekH() {
    var t = S.trainer;
    if (!t) return '';
    chooseHorizonDay();
    var dur = t.session_duration_minutes ? t.session_duration_minutes + ' мин' : '';
    var sub = [t.name, dur].filter(Boolean).join(' · ');
    var h = '<div class="tc tc-h"><div class="tc-bhead tc-h-head">' + tcBarBack() +
      '<div class="tc-h-title"><h1>Время на две недели</h1>' + (sub ? '<p>' + esc(sub) + '</p>' : '') + '</div></div>';
    h += '<div class="tc-h-pad">';
    if (S.slots === null) {
      return h + '<div class="tc-h-sk" aria-busy="true"><span class="tc-vh" role="status">Загружаем время…</span>' +
        '<i></i><i></i><i></i><i></i><i></i></div></div></div>';
    }
    if (S.slotsError) {
      var write = t.contact_url ? '<button type="button" class="tc-sec" data-act="write">Написать</button>' : '';
      return h + '<p class="tc-empty-t">Не удалось загрузить время</p>' +
        '<p class="tc-empty-p">Проверьте сеть и повторите.' + (t.contact_url ? ' Тренеру можно и написать.' : '') + '</p>' +
        '<div class="tc-l1-acts"><button type="button" class="tc-sec tc-sec--main" data-act="reslots">Повторить</button>' + write + '</div></div></div>';
    }
    var days = horizonDays();
    var any = days.some(function (iso) { return slotsOn(iso).length; });
    if (!t.can_book || !any) {
      h += weekDeadEnd(t);
      return h + '</div></div>';
    }
    h += '<div class="tc-h-days" role="tablist" aria-label="Дни">';
    days.forEach(function (iso) {
      var n = slotsOn(iso).length;
      var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
      var wd = m ? TC_WEEKDAY[new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()] : '';
      if (wd) wd = wd.charAt(0).toLocaleUpperCase('ru') + wd.slice(1);
      var num = m ? String(+m[3]) : '';
      var on = iso === S.day && n > 0;
      if (!n) {
        h += '<button type="button" class="tc-h-day tc-h-day--empty" disabled aria-disabled="true">' +
          '<span>' + esc(wd) + '</span><b>' + esc(num) + '</b><small>нет</small></button>';
        return;
      }
      var count = M.word(n, 'окно', 'окна', 'окон');
      h += '<button type="button" class="tc-h-day" role="tab" data-act="day" data-day="' + iso + '" aria-selected="' + on + '" aria-controls="tcHDay">' +
        '<span>' + esc(wd) + '</span><b>' + esc(num) + '</b><small>' + esc(count) + '</small></button>';
    });
    h += '</div>';
    var rows = slotsOn(S.day);
    var picked = pickedHorizonSlot();
    var head = tcWeekdayFull(S.day);
    var dm = tcDayMonth(S.day);
    h += '<div id="tcHDay" role="tabpanel">';
    if (head && dm) h += '<h2 class="tc-h-daytitle">' + esc(head) + ', ' + esc(dm) + '</h2>';
    if (rows.length) {
      h += '<div class="tc-h-grid">' + rows.map(function (s) {
        var on = picked && String(picked.id) === String(s.id);
        return '<button type="button" class="tc-h-tile" data-act="week-slot" data-slot="' + esc(s.id) + '" aria-pressed="' + !!on + '"><b>' +
          esc(String(s.start_time || '').slice(0, 5).replace(/^0(\d)/, '$1')) + '</b>' +
          (s.arena_name ? '<span>' + esc(s.arena_name) + '</span>' : '') + '</button>';
      }).join('') + '</div>';
    }
    h += '</div>';
    if (t.contact_url) {
      h += '<div class="tc-h-ask"><div><b>Не подходит время?</b><span>Напишите тренеру, чтобы предложить своё время</span></div>' +
        '<button type="button" class="tc-sec" data-act="write">Написать</button></div>';
    }
    h += '</div></div>';
    if (picked) {
      h += '<div class="ft col tc-ft"><button type="button" class="cta" data-act="slot" data-slot="' + esc(picked.id) + '">Записаться на ' +
        esc(tcWhen(picked)) + '</button>' +
        (initData ? '<small>' + esc(tcFirstName(t)) + ' подтвердит — сообщение придёт в Telegram</small>' : '') + '</div>';
    }
    return h;
  }

  /** H без окон или без онлайн-записи: не пустая полоса дней и не пустой заголовок дня. */
  function weekDeadEnd(t) {
    if (!t.can_book) {
      return '<p class="tc-empty-t">Сейчас записаться онлайн нельзя</p>' +
        (initData ? '<button type="button" class="tc-sec tc-sec--main" data-act="request">Оставить заявку</button>' : '');
    }
    return '<p class="tc-empty-t">На ближайшие две недели свободного времени нет</p>' +
      '<button type="button" class="tc-sec" data-act="to-trainer">Назад к тренеру</button>';
  }

  function renderWeek() {
    if (unifiedCard()) return renderWeekH();
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
    var weekExit = exitButtons(t, {
      writeClass: 'more', requestClass: 'more', phoneClass: 'more', tgClass: 'more',
      // Заявка рядом с «Написать», если человек в Telegram — иначе текст без кнопки.
      request: !!initData,
    });
    if (weekExit) {
      var weekLead = t.contact_url
        ? ('Не нашли подходящее время? Напишите ' + M.dativeFirst(t.first_name, RuName) + ' — обсудите другое время.')
        : (initData
          ? ('Не нашли подходящее время? Оставьте заявку ' + M.dativeFirst(t.first_name, RuName) + ' — обсудите другое время.')
          : 'Не нашли подходящее время? Откройте Telegram или скопируйте телефон — обсудите другое время.');
      h += '<div class="card"><p>' + esc(weekLead) + '</p>' + weekExit + '</div>';
    }
    h += '</div>';
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

  /** Профиль, выбранный в хабе (активный ?? по умолчанию) — им же отмечаем строку в форме. */
  function actingProfileId() {
    var CPS = window.ClientProfileSwitcher;
    var id = CPS && typeof CPS.getActiveProfileId === 'function' ? CPS.getActiveProfileId() : null;
    return id != null ? id : S.defaultProfileId;
  }

  /**
   * Тариф прошлой записи — у каждого профиля свой и только у этого тренера: /client/session?for_trainer_id=
   * с X-Profile-Id профиля (явный заголовок главнее патча переключателя профилей).
   */
  function loadProfileHints(trainerId) {
    if (!initData || !S.profiles.length || S.profileHints[trainerId]) return Promise.resolve();
    var map = {};
    S.profileHints[trainerId] = map;
    // По очереди, не параллельно: GET сессии пишет строку client_sessions аккаунта.
    return S.profiles.reduce(function (chain, p) {
      return chain.then(function () {
        return api('/api/webapp/client/session?for_trainer_id=' + encodeURIComponent(trainerId), { profileId: p.client_id })
          .then(function (d) {
            if (d && d.last_created_booking_service_id != null && d.last_created_booking_service_price_variant_id != null) {
              map[p.client_id] = { sid: Number(d.last_created_booking_service_id), vid: Number(d.last_created_booking_service_price_variant_id) };
            }
          })
          .catch(function () { /* без подсказки — явный выбор тарифа */ });
      });
    }, Promise.resolve());
  }

  function openBooking(slot, opts) {
    // Слот другого тренера (поздний ответ) — не записываем: запись ушла бы не тому тренеру.
    if (!S.trainer || (slot.trainer_id != null && Number(slot.trainer_id) !== Number(S.trainer.id))) return;
    var keep = S.book && S.book.slot && S.view === 'book' ? S.book : null;
    var regular = isRegular();
    var def = null;
    if (regular) {
      var defId = actingProfileId();
      def = S.profiles.filter(function (p) { return Number(p.client_id) === Number(defId); })[0] || S.profiles[0];
      loadProfileHints(S.trainer.id).then(function () { if (S.view === 'book') render(); });
    }
    S.book = {
      slot: slot,
      // Форма нового ученика остаётся ею при смене времени, даже если профиль ребёнка уже создан.
      regular: keep ? keep.regular : regular,
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
      idem: BC.newIdempotencyKey(),
      submitting: false,
      notice: '',
    };
    if (slot.capacity > 1 && slot.service_id) S.serviceId = slot.service_id;
    else if (S.serviceId != null) {
      var picked = (S.trainer.services || []).filter(function (s) { return Number(s.service_id) === Number(S.serviceId); })[0];
      if (picked && !M.serviceFitsSlot(picked, slot)) S.serviceId = null; // форма спросит подходящую услугу
    }
    // В группу — одно место на запись: из двоих, отмеченных на прошлом слоте, остаётся первый.
    if (slot.capacity > 1 && S.book.selected.length > 1) S.book.selected = S.book.selected.slice(0, 1);
    BC.emitBookingAnalytics('booking_step_viewed', { step: 'form', host: 'trainers' });
    // Чип с хаба: запись — корень, «Назад» уходит на хаб существующим back() (стек пуст). go() не зовём.
    if (opts && opts.root) {
      S.stack = [];
      S.view = 'book';
      render();
      return;
    }
    if (S.view === 'book') render();
    else go('book');
  }

  function bookingService() {
    var b = S.book;
    if (b && b.slot && b.slot.capacity > 1 && b.slot.service_id) {
      var g = (S.trainer.services || []).filter(function (s) { return Number(s.service_id) === Number(b.slot.service_id); })[0];
      if (g) return g;
    }
    var svc = currentService();
    if (!b || !b.slot) return svc;
    // Онлайн-услуга на очный слот (и наоборот) — сервер ответит 422; такую пару форма не собирает.
    if (svc && M.serviceFitsSlot(svc, b.slot)) return svc;
    var fit = servicesForSlot(S.trainer, b.slot);
    return fit.length === 1 ? fit[0] : null;
  }

  /** Групповой слот: одна запись = одно место = один участник (второй профиль и «двое» недоступны). */
  function isGroupBooking() {
    return !!(S.book && S.book.slot && S.book.slot.capacity > 1);
  }

  /** Опции тарифа постоянного: подсказки только этого тренера и этой услуги, известные дети, явный выбор. */
  function regularOpts(svc) {
    var hints = {};
    var map = (S.trainer && S.profileHints[S.trainer.id]) || {};
    Object.keys(map).forEach(function (pid) {
      if (svc && map[pid].sid === Number(svc.service_id)) hints[pid] = map[pid].vid;
    });
    return { hints: hints, knownChildIds: S.knownChildIds, override: S.book ? S.book.override : null, group: isGroupBooking() };
  }

  /** Тариф и участники текущего выбора: { tier, duo, ready, participant, kindTitle }. */
  function bookingChoice() {
    var b = S.book;
    var svc = bookingService();
    var group = b.slot.capacity > 1;
    if (!svc) return { ready: false };
    if (b.regular) {
      if (!b.selected.length) return { ready: false };
      var opts = regularOpts(svc);
      var tier = group ? null : M.regularTier(svc, b.selected, opts);
      var hasTiers = (svc.price_tiers || []).length > 0;
      return {
        // Тариф не определился (вид профиля неизвестен) — форма просит выбрать его явно.
        ready: group ? b.selected.length === 1 : (!hasTiers && b.selected.length === 1) || !!tier,
        needsTier: !group && hasTiers && !tier,
        tier: tier,
        duo: !!(tier && M.isDuoKind(tier.tier_kind)) || b.selected.length === 2,
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
    var h = unifiedCard() ? '<div class="tc tc-book">' + screenD_head() : '<div class="bd">' + backBtn('Назад');
    h += '<div class="sum"><div class="k">' + (t.photo_url ? '<img src="' + esc(t.photo_url) + '" alt="">' : '<i>' + esc(t.initial || 'Т') + '</i>') +
      '<div class="when"><b>' + esc(M.slotWhen(slot, S.todayIso)) + '</b><br><span>' + esc([t.name, what, place].filter(Boolean).join(' · ')) + '</span></div></div></div>';
    if (!svc) {
      var svcs = servicesForSlot(t, slot);
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
    if (!slot.is_online && arenaById(slot.arena_id)) h += meetHtml(t, [arenaById(slot.arena_id)]);
    if (b.notice) h += '<p class="note" role="alert">' + esc(b.notice) + '</p>';
    h += '</div>' + bookFooter(choice.ready);
    return h;
  }

  function payHtml(svc, choice) {
    var b = S.book;
    var slot = b.slot;
    var arena = arenaById(slot.arena_id);
    var pass = null;
    if (b.regular && b.selected.length) {
      // Запись уходит на первого отмеченного — его абонемент сервер и спишет (если покрывает тариф).
      var kind = choice.tier ? choice.tier.tier_kind : null;
      pass = M.usablePass(S.passes[b.selected[0].client_id], S.trainer.id, svc.service_id, kind);
      for (var i = 1; i < b.selected.length && !pass; i++) {
        pass = M.usablePass(S.passes[b.selected[i].client_id], S.trainer.id, svc.service_id, kind);
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
    var caption = unifiedCard()
      ? esc(tcFirstName(S.trainer)) + ' подтвердит — сообщение придёт в Telegram'
      : esc(S.trainer.first_name) + ' подтвердит запись';
    var footClass = unifiedCard() ? 'ft col tc-ft' : 'ft col';
    return '<div class="' + footClass + '"><button type="button" class="cta' + (ready ? '' : ' off') + '" data-act="submit"' + (ready && !b.submitting ? '' : ' disabled') + '>' + esc(label) + '</button>' +
      '<small>' + caption + '</small></div>';
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
    var whoHead = unifiedCard()
      ? '<h2 class="tc-h2" id="whoLbl">Кто будет заниматься?</h2>'
      : '<span class="lbl" id="whoLbl">Кто будет заниматься?</span>';
    var h = '<div class="fl">' + whoHead + '<div class="pick" role="radiogroup" aria-labelledby="whoLbl">' +
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
    var opts = regularOpts(svc);
    var hasDuo = !opts.group && M.tierChoices(svc, 2).length > 0;
    var whoReg = unifiedCard()
      ? '<h2 class="tc-h2" id="whoRegLbl">Кого записываем?' + (hasDuo ? ' <span class="mut">Можно двоих</span>' : '') + '</h2>'
      : '<span class="lbl">Кого записываем?' + (hasDuo ? ' <span class="mut" style="font-weight:500">Можно двоих</span>' : '') + '</span>';
    var h = '<div class="fl">' + whoReg + '<div class="pick multi"' + (unifiedCard() ? ' role="group" aria-labelledby="whoRegLbl"' : '') + '>';
    h += S.profiles.map(function (p) {
      var on = b.selected.some(function (x) { return Number(x.client_id) === Number(p.client_id); });
      var single = { hints: opts.hints, knownChildIds: opts.knownChildIds, group: opts.group };
      var tier = M.regularTier(svc, [p], single);
      var last = !!M.hintTier(svc, p, single);
      var kindWord = tier ? (tier.tier_kind === 'child' ? 'детский' : 'взрослый') : '';
      var sub = unifiedCard() && last && kindWord
        ? 'как в прошлый раз · ' + kindWord
        : last ? 'как в прошлый раз' : kindWord;
      var dis = !on && !M.canAddProfile(svc, b.selected, p, single);
      return pickRow(p.client_id, p.first_name || 'Без имени', sub, tier ? M.formatMoney(tier.price_cents, svc.currency_code) : '', on, dis, 'checkbox');
    }).join('');
    h += '</div></div>';
    h += '<div class="row2"><button type="button" class="more" data-act="add-child">+ Добавить ребёнка</button>' +
      ((svc.price_tiers || []).length > 1 ? '<button type="button" class="more" data-act="other-tier">Другой тариф</button>' : '') + '</div>';
    if (b.addChild) {
      h += '<div class="fl"><label for="newChild">Имя ребёнка</label><input id="newChild" class="inpx" data-field="new-child" maxlength="64" placeholder="Например, Соня">' +
        '<button type="button" class="sec2" data-act="add-child-save">Добавить</button></div>';
    }
    var choice = bookingChoice();
    if (b.otherTier || choice.needsTier) {
      var list = M.tierChoices(svc, b.selected.length || 1);
      h += (choice.needsTier ? '<span class="lbl">Какой тариф?</span>' : '') + '<div class="opt">' + list.map(function (x) {
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

  function childNameKey(name) {
    return String(name || '').trim().replace(/\s+/g, ' ').toLowerCase();
  }

  function ensureChildProfile(name) {
    var key = childNameKey(name);
    if (S.childIds[key]) return Promise.resolve(S.childIds[key]);
    var existing = S.profiles.filter(function (p) { return p.role !== 'self' && childNameKey(p.first_name) === key; })[0];
    if (existing) {
      S.knownChildIds[existing.client_id] = true;
      return Promise.resolve(existing.client_id);
    }
    return api('/api/webapp/client/profiles', { method: 'POST', body: { first_name: name } }).then(function (d) {
      S.childIds[key] = d.client_id;
      S.knownChildIds[d.client_id] = true;
      // Как «+ Добавить ребёнка»: профиль сразу в списке — следующая запись найдёт его, а не создаст второй.
      if (!S.profiles.some(function (p) { return Number(p.client_id) === Number(d.client_id); })) {
        S.profiles.push({ client_id: d.client_id, role: 'guardian', first_name: name });
        S.passes[d.client_id] = S.passes[d.client_id] || [];
      }
      return d.client_id;
    });
  }

  /** После записи — профили с сервера (новый «я»/ребёнок), их абонементы и тарифы прошлой записи заново. */
  function refreshProfiles() {
    return loadProfiles().then(function (list) {
      if (!list.length) return;
      S.profiles = list;
      S.profileHints = {};
      return loadPasses();
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
    b.sentProfileId = null;
    render();
    profilePromise
      .then(function (profileId) {
        // Профиль, на который уходит запись: при обрыве связи проверяем записи именно у него.
        b.sentProfileId = profileId;
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
          onBooked(r.data, choice, x.profileId);
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
        verifyUnknown(b.sentProfileId, choice);
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
          onBooked({ success: true }, choice, profileId);
          return;
        }
        b.notice = 'Записи пока не видно. Нажмите ещё раз — дубль не создастся.';
        render();
      })
      .catch(function () {
        b.notice = 'Сеть не ответила. Запись могла создаться — проверьте «Мои записи», прежде чем нажимать снова.';
        render();
      });
  }

  function onBooked(data, choice, profileId) {
    var b = S.book;
    BC.hapticSuccess();
    S.sent = { data: data, slot: b.slot, participant: choice.participant, trainer: S.trainer, dirKey: S.dirKey, profileId: profileId != null ? profileId : null };
    S.stack = [];
    S.view = 'sent';
    render();
    window.scrollTo(0, 0);
    S.book = null;
    if (unifiedCard()) {
      try { history.replaceState({ tswSent: 1 }, ''); } catch (e) { /* история недоступна */ }
    }
    refreshProfiles();
  }

  /* ── 7 · Время заняли ────────────────────────────────────────────── */

  function showTaken(missingTitle) {
    var b = S.book;
    var lostId = b ? b.slot.id : null;
    var unified = unifiedCard();
    var when = b && unified ? screenL_slotTitle(b.slot) : '';
    var title = b
      ? (unified ? when + ' уже заняли' : String(b.slot.start_time).slice(0, 5) + ' уже недоступно')
      : (missingTitle || (unified ? 'Это время уже заняли' : 'Это время уже недоступно'));
    loadSlots().then(function (fresh) {
      if (!fresh) return;
      var alt = (S.slots || []).filter(function (s) { return String(s.id) !== String(lostId); }).slice(0, 3);
      var svc = currentService();
      var price = svc ? M.cardPriceHtml(svc).replace(/<\/?b>/g, '') : '';
      if (unified) {
        screenL_takenSheet(title, alt, !!b);
        if (S.view === 'book') render();
        return;
      }
      var saved = b ? 'Данные запомнили. ' : '';
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

  /** L2 (доска States 2): «Выберите другое время у {Имя}:», окна чипами «сб, 11:30», «Всё время тренера». */
  function screenL_takenSheet(title, alt, hadForm) {
    var saved = hadForm ? 'Ваши данные сохранены. ' : '';
    var tail = alt.length ? 'Выберите другое время у ' + genFirst(S.trainer.first_name) + ':' : 'Другого свободного времени пока нет.';
    var chips = alt.map(function (s) {
      return '<button type="button" class="tc-chip" data-act="slot" data-slot="' + esc(s.id) + '">' + esc(tcWhen(s)) + '</button>';
    }).join('');
    openSheet('<div class="sh"><h4>' + esc(title) + '</h4><button type="button" class="x" data-act="sheet-close" aria-label="Закрыть">✕</button></div>' +
      '<span class="mut">' + esc(saved + tail) + '</span>' +
      (chips ? '<div class="tc-l2-times">' + chips + '</div>' : '') +
      '<button type="button" class="tc-sec" data-act="week">Всё время тренера</button>');
  }

  /** D: шапка «‹ Запись» (доска Book). В Telegram стрелка нативная — остаётся только заголовок. */
  function screenD_head() {
    var native = window.MiniAppBack && window.MiniAppBack.isNative();
    return '<div class="tc-bhead">' +
      (native ? '' : '<button type="button" class="tc-bback" data-act="back" aria-label="Назад">' + TC_ICON.back + '</button>') +
      '<h1>Запись</h1></div>';
  }

  /** «Сб, 10:00» — заголовок шторки L2. Пустое время не подставляем. */
  function screenL_slotTitle(slot) {
    var w = tcWhen(slot);
    return w ? w.charAt(0).toUpperCase() + w.slice(1) : '';
  }

  /** L3: тренера нет. Город — как в сессии, без склонения (именительного «в Минск» не пишем). */
  function screenL_missing() {
    var city = String((S.session && S.session.city_name) || '').trim();
    var label = city ? 'Другие тренеры · ' + city : 'Другие тренеры';
    return '<div class="tc tc-miss"><div class="tc-body"><div class="tc-miss-card">' +
      '<span class="tc-miss-ic">' + TC_ICON.search + '</span><h1>Такого тренера нет</h1>' +
      '<p class="tc-empty-p">Возможно, ссылка устарела. Другие тренеры города — по кнопке ниже.</p>' +
      '<button type="button" class="cta" data-act="to-list">' + esc(label) + '</button></div></div></div>';
  }

  /**
   * N: «Вы в списке» — только у того тренера, к которому форма K реально привязала (успешный ответ
   * self-register записан в sessionStorage). Параметр listed=1 в ссылке сам по себе ничего не доказывает:
   * его можно дописать руками, а после «Назад» → список → другой тренер он остаётся в адресе.
   */
  var LISTED_TID = screenN_listedTrainerId();

  function screenN_listedTrainerId() {
    if (!unifiedCard() || qs.get('listed') !== '1') return null;
    var tid = num(qs.get('trainer_id'));
    try {
      var linked = num(window.sessionStorage.getItem('trainer_crm_listed_trainer_id'));
      return tid && linked === tid ? tid : null;
    } catch (e) {
      return null;
    }
  }

  function screenN_isListed(t) {
    return !!(LISTED_TID && t && Number(t.id) === LISTED_TID);
  }

  /** Тренер по ссылке не загрузился (сеть, 5xx): не «тренера нет», а повтор (как L1 на доске States). */
  function screenL_loadError() {
    return '<div class="tc tc-miss"><div class="tc-body"><div class="tc-miss-card"><h1>Не удалось загрузить тренера</h1>' +
      '<p class="tc-empty-p">Проверьте сеть и повторите.</p>' +
      '<button type="button" class="cta" data-act="retry-trainer">Повторить</button></div></div></div>';
  }

  /** N: после регистрации по ссылке тренера. Абонемента нет — строки нет. */
  function screenN_banner(t) {
    var first = tcFirstName(t);
    var name = first;
    if (RuName && /^[А-Яа-яЁё-]+$/.test(first)) {
      name = RuName.inflectPersonName(first, '', 'gen') || first;
    }
    var pass = screenN_passLine(t);
    return '<div class="tc-roster" role="status"><b>Вы в списке у ' + esc(name) + '</b>' + pass + '</div>';
  }

  function screenN_passLine(t) {
    var ids = Object.keys(S.passes || {});
    for (var i = 0; i < ids.length; i++) {
      var items = S.passes[ids[i]] || [];
      for (var j = 0; j < items.length; j++) {
        var p = items[j];
        if (Number(p.trainer_id) !== Number(t.id)) continue;
        if (p.status && p.status !== 'active') continue;
        var left = Number(p.sessions_remaining);
        if (!(left > 0)) continue;
        var total = Number(p.sessions_total);
        var of = total > 0 ? ' из ' + total : '';
        return '<span>Абонемент: осталось ' + M.word(left, 'занятие', 'занятия', 'занятий') + of + '</span>';
      }
    }
    return '';
  }

  function genFirst(first) {
    var f = String(first || '').trim().split(/\s+/)[0] || '';
    if (!/^[А-Яа-яЁё-]+$/.test(f) || !RuName) return 'тренера';
    return RuName.inflectPersonName(f, '', 'gen') || 'тренера';
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
    var unified = unifiedCard();
    var sentTitle = 'Запись отправлена ' + esc(M.dativeFirst(t.first_name, RuName));
    var h = '<div class="' + (unified ? 'tc tc-sent' : 'bd') + '"><div class="okc" aria-hidden="true">' + (unified ? TC_ICON.check : '✓') + '</div><div class="ctr">' +
      (unified ? '<h1>' + sentTitle + '</h1>' : '<h3>' + sentTitle + '</h3>') +
      '<span class="mut">' + esc(line) + '</span></div>';
    var steps;
    if (canWrite) {
      steps = [unified
        ? esc(t.first_name) + ' подтвердит запись — сообщение в Telegram.'
        : esc(t.first_name) + ' подтвердит запись — пришлём сообщение в чат с ботом.'];
      // «Напомним за 2 часа» нет в продукте (SPEC §18 B). При флаге строку не показываем.
      if (!unified) {
        var plan = x.data && x.data.reminder_plan ? String(x.data.reminder_plan).trim() : '';
        if (plan) steps.push('Напомним ' + esc(plan) + '.');
      }
      steps.push('Детали, адрес и отмена — в «Моих записях».');
    } else {
      if (unreachable) h += '<div class="warn">' + BC.writeAccessBlockHtml(unreachable) + '</div>';
      steps = ['Подтверждение тренера появится в «Моих записях».', 'Там же — детали, адрес и отмена.'];
    }
    var nextHead = unified ? '<h2 class="tc-h2">Что дальше</h2>' : '<h4>Что дальше</h4>';
    h += '<div class="card">' + nextHead + '<ol class="ol">' + steps.map(function (s) { return '<li>' + s + '</li>'; }).join('') + '</ol></div>';
    if (!slot.is_online) {
      var met = arenaById(slot.arena_id) || (slot.arena_name ? { name: slot.arena_name, map_link: slot.map_link } : null);
      if (met && !met.map_link && slot.map_link) met = Object.assign({}, met, { map_link: slot.map_link });
      // При флаге блока «Где встретимся» нет (доска Sent): маршрут — кнопкой внизу, адрес — в «Моих записях».
      if (met && !unified) h += meetHtml(t, [met]);
      var bring = unified ? '<h2 class="tc-h2">Что взять с собой</h2>' : '<h4>Что взять с собой</h4>';
      h += '<div class="card">' + bring + '<p>' + esc(M.takeWithYou(x.dirKey, arenaById(slot.arena_id))) + '</p></div>';
    }
    if (unified) {
      var mapLink = slot.map_link || (arenaById(slot.arena_id) || {}).map_link;
      var route = mapLink
        ? '<button type="button" class="sec2" data-act="route">Маршрут до катка</button>'
        : '';
      h += '</div><div class="ft col tc-ft"><button type="button" class="cta" data-act="my-bookings">Мои записи</button>' +
        route + '<button type="button" class="tc-link tc-done" data-act="done">Готово</button></div>';
    } else {
      h += '</div><div class="ft col"><button type="button" class="cta" data-act="my-bookings">Мои записи</button>' +
'</div>';
    }
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
    // Город сессии, иначе — тренера; нет и его — сервер возьмёт город тренера по trainer_id.
    var cityId = S.cityId || (S.session && S.session.city_id) || t.city_id || null;
    if (!String(r.name || '').trim()) { r.notice = 'Укажите имя.'; paintRequest(); return; }
    var ph = readPhone(r);
    if (!ph.ok) { r.notice = ph.error; paintRequest(); return; }
    if (!svc) { r.notice = 'Не удалось определить город или услугу. Напишите тренеру напрямую.'; paintRequest(); return; }
    r.sending = true;
    r.notice = '';
    paintRequest();
    var selfP = selfProfile();
    api('/api/webapp/client/request', {
      method: 'POST',
      // Заявка — от самого человека, а не от профиля, выбранного в хабе.
      profileId: selfP ? selfP.client_id : null,
      body: { city_id: cityId || undefined, service_id: svc.service_id, trainer_id: t.id, comment: r.comment.trim() || null, first_name: r.name.trim(), phone: ph.phone },
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

  /** Подписка обещает сообщение — оформляем её, только когда боту разрешено писать. */
  function subscribeNotify(el) {
    var tid = S.trainer.id;
    var WA = window.GlideWriteAccess;
    el.disabled = true;
    function mine() { return S.trainer && S.trainer.id === tid; }
    function failed() {
      if (!mine()) return;
      el.disabled = false;
      el.textContent = 'Не получилось — попробовать ещё раз';
    }
    function post() {
      return api('/api/webapp/client/trainer-edges/notify-slots', { method: 'POST', body: { trainer_id: tid } })
        .then(function () {
          if (!mine()) return;
          S.notify = true;
          S.waBlock = '';
          render();
        })
        .catch(failed);
    }
    if (!WA || !tg) { post(); return; }
    WA.gate(tg, { surface: 'slot_wait', trainerId: tid }).then(
      function (res) {
        if (res === 'proceed') { post(); return; }
        if (!mine()) return;
        S.waBlock = BC.unreachableState() || '';
        render();
      },
      post
    );
  }

  /** «Сохранить тренера» — тумблер: состояние берём с сервера, ошибку показываем. */
  function toggleSaved(el) {
    var tid = S.trainer.id;
    var next = !S.saved;
    el.disabled = true;
    S.saveNote = '';
    var req = next
      ? api('/api/webapp/client/trainer-edges/save', { method: 'POST', body: { trainer_id: tid } })
      : api('/api/webapp/client/trainer-edges/save/' + encodeURIComponent(tid), { method: 'DELETE' });
    req.then(function () {
      if (!S.trainer || S.trainer.id !== tid) return;
      S.saved = next;
      render();
    }).catch(function () {
      if (!S.trainer || S.trainer.id !== tid) return;
      S.saveNote = 'Не получилось — попробуйте ещё раз.';
      render();
    });
  }

  var SHEET_FOCUSABLE = 'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';
  var sheetOpener = null;
  var sheetOpenerAct = null;

  function sheetFocusables() {
    return Array.prototype.slice.call(sheetEl.querySelectorAll(SHEET_FOCUSABLE));
  }

  function setBackgroundInert(on) {
    if (on) {
      appEl.setAttribute('inert', '');
      appEl.setAttribute('aria-hidden', 'true');
    } else {
      appEl.removeAttribute('inert');
      appEl.removeAttribute('aria-hidden');
    }
  }

  /** Шторка — модальное окно: имя, фокус внутри, фон недоступен, возврат фокуса при закрытии (Esc и Tab — в onSheetKey). */
  function openSheet(inner) {
    var reopen = !sheetEl.hidden;
    var active = document.activeElement;
    var keepIdx = -1;
    var keepSel = null;
    if (reopen && active && sheetEl.contains(active)) {
      // Перерисовка той же шторки (заявка): фокус и курсор остаются на месте.
      keepIdx = sheetFocusables().indexOf(active);
      if (typeof active.selectionStart === 'number') keepSel = [active.selectionStart, active.selectionEnd];
    } else if (!reopen) {
      sheetOpener = active && active !== document.body ? active : null;
      sheetOpenerAct = sheetOpener && sheetOpener.getAttribute ? sheetOpener.getAttribute('data-act') : null;
    }
    var sheetClass = unifiedCard() ? 'sheet tc-sheet' : 'sheet';
    sheetEl.innerHTML = '<div class="dim" data-act="sheet-dim"><div class="' + sheetClass + '" role="dialog" aria-modal="true" aria-labelledby="sheetTitle" tabindex="-1">' +
      inner.replace('<h4>', '<h4 id="sheetTitle">') + '</div></div>';
    sheetEl.hidden = false;
    setBackgroundInert(true);
    var target = null;
    if (keepIdx >= 0) target = sheetFocusables()[keepIdx] || null;
    if (!target) target = sheetEl.querySelector('.sheet');
    if (target && typeof target.focus === 'function') {
      target.focus();
      if (keepSel && keepIdx >= 0 && typeof target.setSelectionRange === 'function') {
        try { target.setSelectionRange(keepSel[0], keepSel[1]); } catch (e) { /* не текстовое поле */ }
      }
    }
  }

  function closeSheet() {
    var wasOpen = !sheetEl.hidden;
    sheetEl.hidden = true;
    sheetEl.innerHTML = '';
    setBackgroundInert(false);
    var back = sheetOpener;
    sheetOpener = null;
    // Экран под шторкой мог перерисоваться — тогда ищем такую же кнопку заново.
    if (wasOpen && back && back.isConnected === false && sheetOpenerAct) back = appEl.querySelector('[data-act="' + sheetOpenerAct + '"]');
    if (wasOpen && back && typeof back.focus === 'function') back.focus();
  }

  function onSheetKey(ev) {
    if (sheetEl.hidden) return;
    if (ev.key === 'Escape') {
      ev.preventDefault();
      closeSheet();
      return;
    }
    if (ev.key !== 'Tab') return;
    var list = sheetFocusables();
    if (!list.length) { ev.preventDefault(); return; }
    var first = list[0];
    var last = list[list.length - 1];
    var cur = document.activeElement;
    var dlg = sheetEl.querySelector('.sheet');
    if (!cur || !sheetEl.contains(cur)) {
      ev.preventDefault();
      (ev.shiftKey ? last : first).focus();
    } else if (ev.shiftKey && (cur === first || cur === dlg)) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && cur === last) {
      ev.preventDefault();
      first.focus();
    }
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

  function syncBack() {
    var Back = window.MiniAppBack;
    if (!Back) return;
    // Список — корень раздела «Поиск» (панель вкладок под рукой): стрелки нет. Она появляется,
    // только когда идём вглубь (карточка тренера, неделя, запись) и ведёт на шаг назад.
    if (S.view !== 'list' || S.stack.length) Back.set(back);
    else Back.clear();
  }

  function render() {
    if (S.view === 'book') capturePhone(S.book, appEl);
    var html;
    if (S.view === 'trainer') html = renderTrainer();
    else if (S.view === 'week') html = renderWeek();
    else if (S.view === 'book') html = renderBook();
    else if (S.view === 'sent') html = renderSent();
    else if (S.view === 'reqsent') html = renderReqSent();
    else if (S.view === 'missing') html = screenL_missing();
    else if (S.view === 'trainer-error') html = screenL_loadError();
    else if (unifiedCard() && !S.items && !S.loadError && num(qs.get('trainer_id'))) html = renderTrainerSkeleton();
    else html = renderList();
    appEl.innerHTML = '<div class="tsw-view">' + html + '</div>';
    if (S.view === 'trainer' && unifiedCard()) tcAfterRender();
    syncBack();
    syncTabBar();
    if (S.view === 'book' && S.book) wirePhone(S.book);
    if (S.view === 'sent' || (S.view === 'trainer' && S.waBlock)) BC.bindWriteAccessBlock(appEl);
  }

  /** Нижняя панель «Главная / Поиск / Записи / Ещё» (mini-app-client-shell.js): видна на витрине, тренере и
   *  «другом времени»; на записи и итогах спрятана — не перекрывает закреплённую кнопку и форму. */
  function syncTabBar() {
    var shell = window.ClientShell;
    if (shell && typeof shell.setTabBarVisible === 'function') shell.setTabBarVisible(!!TABBAR_VIEWS[S.view]);
  }

  function syncUrl() {
    var q = new URLSearchParams(location.search);
    if (S.tab && S.tab !== 'all') q.set('tab', S.tab); else q.delete('tab');
    if (S.arenaId) q.set('arena_id', String(S.arenaId)); else q.delete('arena_id');
    // Фильтры витрины — в адресе; вход в тренера/время одноразовый и при перезагрузке не повторяется.
    ['trainer_id', 'slot_id', 'service_id', 'via', 'intent', 'entry'].forEach(function (k) { q.delete(k); });
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
          if (t) openTrainer(t).then(function (fresh) { if (fresh) openWeek(); });
        } else openWeek();
        break;
      case 'write':
        ev.stopPropagation();
        t = el.getAttribute('data-tid') ? trainerFromEl(el) : S.trainer;
        if (t) openLink(t.contact_url);
        break;
      case 'open-tg':
        ev.stopPropagation();
        t = el.getAttribute('data-tid') ? trainerFromEl(el) : S.trainer;
        if (t) openLink(t.telegram_url);
        break;
      case 'copy-phone':
        ev.stopPropagation();
        t = el.getAttribute('data-tid') ? trainerFromEl(el) : S.trainer;
        copyTrainerPhone(trainerPhone(t));
        break;
      case 'dir':
        S.dirKey = el.getAttribute('data-key');
        S.serviceId = firstServiceId(S.trainer, S.dirKey);
        // retain: пустой экран без слотов не мигает «N мин · ближайшее время» на время запроса.
        loadSlots({ retain: true }).then(render);
        render();
        break;
      case 'svc':
        S.serviceId = Number(el.getAttribute('data-sid'));
        if (S.view === 'book') render();
        else loadSlots({ retain: true }).then(render);
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
      case 'day':
        S.day = el.getAttribute('data-day');
        if (unifiedCard()) S.weekSlot = null;
        render();
        break;
      case 'week-slot': S.weekSlot = el.getAttribute('data-slot'); render(); break;
      case 'trust': S.trustOpen = !S.trustOpen; render(); break;
      case 'to-trainer': S.view = 'trainer'; S.stack = []; render(); window.scrollTo(0, 0); break;
      case 'notify':
        subscribeNotify(el);
        break;
      case 'save':
        toggleSaved(el);
        break;
      case 'bio': el.classList.toggle('open'); break;
      case 'bio-more': {
        S.bioOpen = true;
        render();
        // Кнопка исчезла — фокус на раскрытый текст, а не в начало страницы.
        var bioEl = appEl.querySelector && appEl.querySelector('#tcBio');
        if (bioEl) { bioEl.setAttribute('tabindex', '-1'); try { bioEl.focus({ preventScroll: true }); } catch (e) { /* */ } }
        break;
      }
      case 'share': shareTrainer(el); break;
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
            // Сервер отдаёт уже существующего ребёнка с тем же именем — второй строки в списке не будет.
            var prof = S.profiles.filter(function (x) { return Number(x.client_id) === Number(d.client_id); })[0];
            if (!prof) {
              prof = { client_id: d.client_id, role: 'guardian', first_name: name };
              S.profiles.push(prof);
              S.passes[d.client_id] = [];
            }
            S.knownChildIds[d.client_id] = true; // добавлен как ребёнок — детский тариф
            b.addChild = false;
            b.override = null;
            var already = b.selected.some(function (x) { return Number(x.client_id) === Number(prof.client_id); });
            if (!already && M.canAddProfile(bookingService(), b.selected, prof, regularOpts(bookingService()))) b.selected = b.selected.concat([prof]);
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
      case 'my-bookings': showBookedProfile(); navigate('client-bookings'); break;
      case 'done': navigate('client-home'); break;
      case 'my-requests': navigate('client-requests'); break;
      case 'route': {
        var sentSlot = S.sent && S.sent.slot;
        var mapLink = sentSlot && (sentSlot.map_link || (arenaById(sentSlot.arena_id) || {}).map_link);
        openLink(mapLink);
        break;
      }
      case 'map': ev.stopPropagation(); openLink(el.getAttribute('data-href')); break;
      case 'to-list': S.view = 'list'; S.stack = []; render(); window.scrollTo(0, 0); break;
      case 'retry-trainer': S.trainerLoadError = false; S.loadError = false; S.items = null; S.view = 'list'; render(); boot(); break;
      default: break;
    }
  }

  /** «Мои записи» после записи ребёнка — его профиль: иначе список открылся бы у родителя и записи «не было». */
  function showBookedProfile() {
    var pid = S.sent && S.sent.profileId;
    var CPS = window.ClientProfileSwitcher;
    if (pid == null || !CPS || typeof CPS.setActiveProfileId !== 'function') return;
    if (Number(CPS.getActiveProfileId()) !== Number(pid)) CPS.setActiveProfileId(pid);
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
  document.addEventListener('keydown', onSheetKey);
  document.addEventListener('keydown', onWeekKey);

  /** Вкладки дней H: стрелки, как ждёт role=tablist. */
  function onWeekKey(ev) {
    if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
    var cur = document.activeElement;
    if (!cur || !cur.getAttribute || cur.getAttribute('data-act') !== 'day') return;
    if (!appEl.querySelectorAll) return;
    var list = appEl.querySelectorAll('[data-act="day"]');
    var idx = -1;
    for (var i = 0; i < list.length; i++) if (list[i] === cur) idx = i;
    if (idx < 0) return;
    var next = ev.key === 'ArrowRight' ? idx + 1 : idx - 1;
    if (next < 0 || next >= list.length) return;
    ev.preventDefault();
    S.day = list[next].getAttribute('data-day');
    S.weekSlot = null;
    render();
    if (!appEl.querySelectorAll) return;
    var again = appEl.querySelectorAll('[data-act="day"]');
    for (var j = 0; j < again.length; j++) {
      if (again[j].getAttribute('data-day') === S.day) {
        try { again[j].focus(); } catch (e) { /* */ }
      }
    }
  }
  appEl.addEventListener('input', onInput);
  sheetEl.addEventListener('input', onInput);

  /** Время с витрины → тренер (для «Назад») → сразу запись; окно ушло — «Время заняли». */
  function openTrainerAndSlot(t, slotId, viaList) {
    var gen = ++S.trainerGen;
    var stale = {};
    function current() { return gen === S.trainerGen && S.trainer === t; }
    S.trainer = t;
    if (viaList) noteShowcasePick();
    var dirs = M.trainerDirections(t);
    // Направление закреплено всегда: услуга этого слота (если окно её несёт), иначе вкладка списка, иначе первое
    // направление тренера. Услугу внутри направления форма записи спросит сама, если она не определена.
    var win = (t.windows || []).filter(function (w) { return String(w.slot_id) === String(slotId); })[0];
    var slotDir = win && win.service_id != null ? M.directionKeyForServiceId(win.service_id) : null;
    S.dirKey = pinDirection(t, slotDir || (S.tab !== 'all' ? S.tab : null));
    S.serviceId = viaList ? null : num(qs.get('service_id'));
    if (viaList) go('trainer');
    else if (!(fromHub() && qs.get('slot_id'))) S.view = 'trainer';
    if (!(fromHub() && qs.get('slot_id'))) render();
    return loadSlots()
      .then(function (fresh) {
        if (!fresh || !current()) return stale;
        var slot = slotById(slotId);
        if (slot || !initData) return slot;
        // Список — только эта и следующая неделя; время по ссылке может быть дальше — проверяем его отдельно.
        return api('/api/webapp/client/slot/' + encodeURIComponent(slotId) + '?trainer_id=' + t.id)
          .then(function (d) { return d && d.available && d.slot ? decorateSlot(d.slot, t) : null; })
          .catch(function () { return null; });
      })
      .then(function (slot) {
        // Пока ждали ответ, открыли другого тренера — ответ этого уже не нужен.
        if (slot === stale || !current()) return;
        if (slot) openBooking(slot, fromHub() && qs.get('slot_id') ? { root: true } : null);
        else {
          // Окно с хаба уже заняли: под шторкой карточка этого тренера, не список.
          if (fromHub() && qs.get('slot_id') && S.view !== 'trainer') {
            S.view = 'trainer';
            S.stack = [];
          }
          render();
          showTaken();
        }
      });
  }

  /**
   * Кнопки сайта «Сохранить» / «Оставить заявку» приходят ссылкой с ``_i_save`` / ``_i_request`` → ``?intent=``.
   * Выполняем один раз при входе в карточку; сохранение идемпотентно (повторный вход не снимает сохранение).
   */
  function applyEntryIntent(tr) {
    var intent = qs.get('intent');
    if (!initData || !tr || (intent !== 'save' && intent !== 'request')) return;
    if (intent === 'request') { openRequest(); return; }
    var tid = tr.id;
    api('/api/webapp/client/trainer-edges/save', { method: 'POST', body: { trainer_id: tid } }).then(function () {
      if (!S.trainer || S.trainer.id !== tid) return;
      S.saved = true;
      S.entryNote = '♥ Тренер сохранён — он в «Сохранённых»';
      render();
      loadEdge(tr);
    }).catch(function () {
      if (!S.trainer || S.trainer.id !== tid) return;
      S.entryNote = 'Не получилось сохранить — нажмите «Сохранить тренера» внизу.';
      render();
    });
  }

  function boot() {
    Promise.all([loadSession(), loadProfiles()]).then(function (res) {
      S.session = res[0];
      S.profiles = res[1] || [];
      if (!S.cityId && S.session && S.session.city_id) S.cityId = num(S.session.city_id);
      loadPasses();
      return loadShowcase()
        .then(function (d) { S.items = (d && d.items) || []; S.loadError = false; })
        .catch(function () { S.items = null; S.loadError = true; });
    }).then(function () {
      var tid = num(qs.get('trainer_id'));
      if (!tid) { render(); return; }
      var t = trainerById(tid);
      var gen = S.trainerGen;
      var p = t ? Promise.resolve(t) : loadTrainerFallback(tid).catch(function (err) {
        // L3 «Такого тренера нет» — только когда сервер так и ответил (404). Сеть и 5xx — ошибка загрузки с «Повторить».
        if (unifiedCard() && !(err && err.status === 404)) S.trainerLoadError = true;
        return null;
      });
      return p.then(function (tr) {
        // Пока грузили тренера по ссылке, человек уже открыл другого — не перебиваем его выбор.
        if (gen !== S.trainerGen) return;
        if (!tr) {
          if (unifiedCard() && tid) {
            S.view = S.trainerLoadError ? 'trainer-error' : 'missing';
            render();
            return;
          }
          render();
          return;
        }
        var sid = qs.get('slot_id');
        if (sid) return openTrainerAndSlot(tr, sid, false);
        var weekRoot = hubWeekEntry();
        S.view = weekRoot ? 'week' : 'trainer';
        return openTrainer(tr, { view: false }).then(function (r) {
          if (weekRoot) {
            S.stack = [];
            S.view = 'week';
          }
          // Карточка уже на экране до действия: шторка заявки и баннер «сохранён» не должны лечь на пустой экран.
          render();
          if (!weekRoot) applyEntryIntent(tr);
          return r;
        });
      });
    });
  }

  render();
  boot();

  window.__trainerShowcase = { state: S, render: render };
})();
