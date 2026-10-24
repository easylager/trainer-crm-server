/**
 * TASK-052 arena card page. Data: GET /api/public/arenas/{ref} + /sessions + /trainers.
 */
(function (global) {
  'use strict';

  var RuText = global.RuText;
  var M = global.ArenaCardModel;
  var MT = global.MinskTime;
  var root = document.getElementById('arenaRoot');
  var state = {
    ref: null,
    card: null,
    sessions: null,
    trainers: null,
    day: null,
    galleryIndex: 0,
    focus: null,
    /* Сеанс для «Позвать» / «Поделиться»; тап по времени в сетке. */
    sharePickSessionId: null,
    /* Выбранный день в секции ОХМ (независимо от МК). */
    ohmDay: null,
    sessionsError: false,
    trainersError: false,
    iceWatchKinds: {},
    iceWatchIds: {},
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* Обычная загрузка сеанса (TASK-290): полоска из трёх делений под временем. Слово уровня
     показывается на выбранной плитке, если касса не дала живой остаток — он важнее. */
  var LOAD_WORDS = { calm: 'обычно свободно', medium: 'обычно в меру', busy: 'обычно людно' };
  var LOAD_LABELS = {
    calm: 'Обычно свободно — можно без спешки',
    medium: 'Обычно народу в меру',
    busy: 'Обычно людно — билет лучше взять заранее',
  };

  function loadMeterHtml(level) {
    if (!LOAD_LABELS[level]) return '';
    return (
      '<span class="arena-load" data-level="' + level + '" role="img" aria-label="' + LOAD_LABELS[level] + '">' +
      '<i></i><i></i><i></i></span>'
    );
  }

  function slotTag(t) {
    if (t.seats) return t.seats.label;
    return (t.picked && LOAD_WORDS[t.load]) || (t.next ? 'Ближайший' : '');
  }

  /* Живой остаток вместо полоски; мало мест — подпись акцентом. */
  function slotBody(t) {
    var tag = slotTag(t);
    var tagCls = t.seats && t.seats.low ? ' class="arena-seats--low"' : '';
    return (
      '<b>' + esc(t.time) + '</b>' +
      (t.seats ? '' : loadMeterHtml(t.load)) +
      (tag ? '<small' + tagCls + '>' + esc(tag) + '</small>' : '')
    );
  }

  function todayIso(now) {
    now = now || new Date();
    var tz = state.card && state.card.timezone;
    if (tz && M) return M.ymdInTimeZone(now, tz);
    return MT ? MT.dateIso(now) : M.ymd(now);
  }

  function addDaysIso(iso, n) {
    if (MT) return MT.addDaysIso(iso, n);
    var d = M.parseLocalDate(iso);
    d.setDate(d.getDate() + n);
    return M.ymd(d);
  }

  function weekdayOf(iso) {
    return M.parseLocalDate(iso).getDay();
  }

  function sessionsByDate() {
    var map = {};
    var days = (state.sessions && state.sessions.days) || [];
    var i;
    for (i = 0; i < days.length; i++) {
      map[days[i].local_date] = days[i].sessions || [];
    }
    return map;
  }

  function allGroups() {
    return (state.trainers && state.trainers.groups) || [];
  }

  function hasAnySessions() {
    var days = (state.sessions && state.sessions.days) || [];
    var i;
    for (i = 0; i < days.length; i++) {
      if ((days[i].sessions || []).length) return true;
    }
    return false;
  }

  function initData() {
    var tg = global.Telegram && global.Telegram.WebApp;
    return (tg && tg.initData) || '';
  }

  function syncIceWatches() {
    var id = initData();
    if (!id || !state.card || state.card.id == null) return Promise.resolve();
    return fetch('/api/webapp/client/watches', {
      headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': id },
      cache: 'no-store',
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var kinds = {};
        var ids = {};
        var aid = Number(state.card.id);
        (data && data.ice_watch_items || []).forEach(function (w) {
          if (Number(w.arena_id) !== aid) return;
          var k = String(w.kind);
          kinds[k] = true;
          if (w.id != null) ids[k] = Number(w.id);
        });
        state.iceWatchKinds = kinds;
        state.iceWatchIds = ids;
      })
      .catch(function () {});
  }

  function seasonRemindActive() {
    if (typeof M.seasonRemindView !== 'function') return false;
    var v = M.seasonRemindView(state.card || {}, { subscribed: false });
    return v.show;
  }

  function renderSeasonRemindBlock() {
    if (!initData() || typeof M.seasonRemindView !== 'function') return '';
    var on = !!(state.iceWatchKinds && state.iceWatchKinds.season_open);
    var v = M.seasonRemindView(state.card || {}, { subscribed: on });
    if (!v.show) return '';
    var mainLabel = on ? v.labelOn : v.labelOff;
    var btnClass = on ? 'arena-btn' : 'arena-btn arena-btn--pri';
    var offBtn =
      on
        ? '<button type="button" class="linkish" data-action="ice-watch" data-watch-kind="season_open">Выключить</button>'
        : '';
    return (
      '<div class="arena-season-remind">' +
      '<button type="button" class="' +
      btnClass +
      '" data-action="ice-watch" data-watch-kind="season_open" aria-pressed="' +
      (on ? 'true' : 'false') +
      '">' +
      esc(mainLabel) +
      '</button>' +
      offBtn +
      '<p class="arena-sub">' +
      esc(v.hint) +
      '</p></div>'
    );
  }

  function iceWatchBtnHtml() {
    if (!initData()) return '';
    if (seasonRemindActive()) return '';
    var kind = 'sessions';
    var on = state.iceWatchKinds && state.iceWatchKinds[kind];
    // Выкл — 🔔; вкл — 🔕. Текст только в подсказке, не отдельной полосой под заголовком.
    var hint = on
      ? copyLine('schedule.bell_on', 'Напоминание включено')
      : copyLine('schedule.bell_hint', 'Сообщить о\u00a0новом расписании');
    return (
      '<button type="button" class="arena-watch-btn' +
      (on ? ' arena-watch-btn--on' : '') +
      '" data-action="ice-watch" data-watch-kind="' +
      esc(kind) +
      '" aria-pressed="' +
      (on ? 'true' : 'false') +
      '" aria-label="' +
      esc(hint) +
      '" title="' +
      esc(hint) +
      '"><span class="arena-watch-btn__icon" aria-hidden="true">' +
      // TASK-306: колокольчик контуром, а не эмодзи; включён — заливка плашки.
      '<svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 20a2 2 0 0 0 4 0"/>' +
      (on ? '<path d="M4 4l16 16"/>' : '') +
      '</svg></span></button>'
    );
  }

  function scheduleHeaderTools(tickets) {
    // Карточка v2: колокольчик живёт на обложке; здесь он остаётся, только если обложка его не показала.
    var watch = visit() ? '' : iceWatchBtnHtml();
    var ticket =
      tickets
        ? '<a class="arena-cta arena-cta--link ga-press" href="' +
          esc(tickets.href) +
          '" data-action="external" data-href="' +
          esc(tickets.href) +
          '">Билеты онлайн</a>'
        : '';
    if (!watch && !ticket) return '';
    return '<div class="arena-h-row__tools">' + watch + ticket + '</div>';
  }

  function toggleIceWatch(kind) {
    kind = kind || 'sessions';
    if (state.iceWatchKinds && state.iceWatchKinds[kind]) {
      unsubscribeIceWatch(kind);
    } else {
      subscribeIceWatch(kind);
    }
  }

  /* TASK-330: бот пишет первым, только если человек это разрешил. Mini App, открытая по
     прямой ссылке без запуска бота, иначе оформила бы подписку, которую некуда доставить. */
  function ensureWriteAccess(done) {
    var tg = global.Telegram && global.Telegram.WebApp;
    var user = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
    var supported =
      tg &&
      typeof tg.requestWriteAccess === 'function' &&
      (typeof tg.isVersionAtLeast !== 'function' || tg.isVersionAtLeast('6.9'));
    if (!supported || (user && user.allows_write_to_pm === true)) {
      done(true);
      return;
    }
    try {
      tg.requestWriteAccess(function (granted) {
        done(!!granted);
      });
    } catch (e) {
      done(true);
    }
  }

  function subscribeIceWatch(kind) {
    var id = initData();
    if (!id || !state.card) {
      var tg = global.Telegram && global.Telegram.WebApp;
      if (tg && tg.showAlert) tg.showAlert('Откройте карточку из клиентского бота Telegram.');
      return;
    }
    kind = kind || 'sessions';
    ensureWriteAccess(function (granted) {
      if (granted) {
        postIceWatch(kind, id);
        return;
      }
      var tg = global.Telegram && global.Telegram.WebApp;
      if (tg && tg.showAlert) tg.showAlert('Без разрешения писать бот не\u00a0сможет прислать напоминание.');
    });
  }

  function postIceWatch(kind, id) {
    fetch('/api/webapp/client/ice-watches', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': id },
      body: JSON.stringify({
        arena_id: state.card.id,
        city_id: state.card.city_id || null,
        watch_kind: kind,
        when: 'any',
        intent: 'skate',
      }),
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (body) {
        var wasWaitBlock = kind === 'sessions' && !hasAnySessions();
        state.iceWatchKinds = state.iceWatchKinds || {};
        state.iceWatchIds = state.iceWatchIds || {};
        state.iceWatchKinds[kind] = true;
        if (body && body.watch && body.watch.id != null) {
          state.iceWatchIds[kind] = Number(body.watch.id);
        }
        paint();
        var tg = global.Telegram && global.Telegram.WebApp;
        // На пустой карточке включение видно в самом блоке — лишний алерт не нужен.
        if (!wasWaitBlock && tg && tg.showAlert) {
          tg.showAlert('Сообщим в\u00a0Telegram, как только появится новое расписание.');
        }
      })
      .catch(function (status) {
        var tg = global.Telegram && global.Telegram.WebApp;
        if (!tg || !tg.showAlert) return;
        if (status === 409) tg.showAlert('Напоминания пока приходят только в\u00a0Telegram.');
        else tg.showAlert('Не удалось оформить подписку. Завершите регистрацию в боте.');
      });
  }

  function unsubscribeIceWatch(kind) {
    var id = initData();
    if (!id || !state.card) return;
    kind = kind || 'sessions';
    var wid = state.iceWatchIds && state.iceWatchIds[kind];
    function doDelete(watchId) {
      fetch('/api/webapp/client/ice-watches/' + encodeURIComponent(String(watchId)), {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': id },
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function () {
          if (state.iceWatchKinds) delete state.iceWatchKinds[kind];
          if (state.iceWatchIds) delete state.iceWatchIds[kind];
          paint();
          var tg = global.Telegram && global.Telegram.WebApp;
          if (tg && tg.showAlert) tg.showAlert('Напоминание отключено.');
        })
        .catch(function () {
          var tg = global.Telegram && global.Telegram.WebApp;
          if (tg && tg.showAlert) tg.showAlert('Не удалось отключить напоминание.');
        });
    }
    if (wid) {
      doDelete(wid);
      return;
    }
    syncIceWatches().then(function () {
      var retry = state.iceWatchIds && state.iceWatchIds[kind];
      if (retry) doDelete(retry);
      else {
        var tg = global.Telegram && global.Telegram.WebApp;
        if (tg && tg.showAlert) tg.showAlert('Подписка уже отключена.');
        paint();
      }
    });
  }

  function shellNav(path) {
    if (global.ClientShell && typeof global.ClientShell.navigate === 'function') {
      global.ClientShell.navigate(path);
      return;
    }
    global.location.href = path;
  }

  function copyArenaPhone(raw) {
    var text = String(raw || '').trim();
    if (!text) return;
    var tg = global.Telegram && global.Telegram.WebApp;
    function notifyOk() {
      if (tg && typeof tg.showAlert === 'function') {
        try {
          tg.showAlert('Номер скопирован:\n' + text);
          return;
        } catch (e) {
          /* noop */
        }
      }
      try {
        global.alert('Номер скопирован:\n' + text);
      } catch (e2) {
        /* noop */
      }
    }
    function notifyFail() {
      if (tg && typeof tg.showAlert === 'function') {
        try {
          tg.showAlert('Скопируйте номер вручную:\n' + text);
          return;
        } catch (e) {
          /* noop */
        }
      }
      try {
        global.alert(text);
      } catch (e2) {
        /* noop */
      }
    }
    var clip = global.navigator && global.navigator.clipboard;
    if (clip && typeof clip.writeText === 'function') {
      clip.writeText(text).then(notifyOk).catch(notifyFail);
      return;
    }
    notifyFail();
  }

  function openExternal(url) {
    var tg = global.Telegram && global.Telegram.WebApp;
    if (tg && typeof tg.openLink === 'function') {
      try {
        tg.openLink(url, { try_instant_view: false });
        return;
      } catch (e1) {
        try {
          tg.openLink(url);
          return;
        } catch (e2) { /* fall through */ }
      }
    }
    global.open(url, '_blank', 'noopener,noreferrer');
  }

  /**
   * С арены всегда открываем карточку тренера — `action` здесь больше нет.
   *
   * Раньше параметр по умолчанию подставлял `'book'`, поэтому «не передавать
   * действие» было невозможно: любой вызов всё равно уходил на выбор времени.
   *
   * @param {string|number} trainerId
   * @param {{groupId?: string|number}} [opts] группа, если тапнули строку набора
   */
  function goBooking(trainerId, opts) {
    opts = opts || {};
    var arenaId = state.card && state.card.id;
    if (global.BookingClient && typeof global.BookingClient.markArenaCatalogStack === 'function') {
      global.BookingClient.markArenaCatalogStack(arenaId);
    } else {
      try {
        global.sessionStorage.setItem('tcb_catalog_arena_stack_v1', String(arenaId));
      } catch (eMark) { /* private mode */ }
    }
    shellNav(
      M.buildBookingHref({
        trainerId: trainerId,
        arenaId: arenaId,
        groupId: opts.groupId,
      })
    );
  }

  /*
   * goWrite убран вместе с развилкой по can_book: тренер без онлайн-записи тоже
   * ведёт на карточку, а «Написать» живёт там — рядом с ценой, услугами и
   * заявкой. Уводить человека в личку из списка на арене значило показать ему
   * контакт раньше, чем он узнал, кому пишет.
   */

  /**
   * Фото тренера. Готовый url — не единственный вариант, и в этом была ошибка.
   *
   * Сервер (`_enrich_trainer_photo_urls`) проставляет `url`/`list_url` только когда
   * настроен CDN или доступен presign S3. Без них он отдаёт `file_key` и
   * `_source: "proxy"`, рассчитывая, что клиент сам соберёт ссылку на прокси —
   * ровно это делает вкладка «Лёд» (`ice-tab-model.js:trainerPhotoUrl`). Карточка
   * арены такой ветки не имела и молча рисовала пустой кружок вместо фотографии.
   */
  function photoUrl(trainer) {
    var photos = (trainer && trainer.photos) || [];
    var ph = photos[0] || {};
    if (ph.list_url) return ph.list_url;
    if (ph.url) return ph.url;
    var fk = ph.file_key_list || ph.file_key;
    if (fk) return '/api/public/photos/' + encodeURIComponent(fk);
    return '';
  }

  function trainerName(t) {
    var p = (t && t.profile) || t || {};
    return [p.first_name, p.last_name].filter(Boolean).join(' ').trim() || 'Тренер';
  }

  /**
   * Первая буква имени для тренера без фотографии.
   *
   * Тот же приём, что у катка без кадра и у карточки на «Льду» (TASK-090 / AC-006):
   * пустое место должно что-то говорить. Эмодзи в имени пропускаем — «🪴» в кружке
   * читается как чужой значок, а не как инициал.
   */
  function trainerInitial(t) {
    var name = trainerName(t);
    for (var i = 0; i < name.length; i++) {
      var ch = name[i];
      if (/[A-Za-zА-Яа-яЁёІіЎў]/.test(ch)) return ch.toUpperCase();
    }
    return '?';
  }

  var HERO_PREFETCH_KEY = 'glideArenaHero';

  function readHeroPrefetch() {
    try {
      var raw = sessionStorage.getItem(HERO_PREFETCH_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function applyPrefetchHero(ref) {
    var rec = readHeroPrefetch();
    if (!M.heroPrefetchMatches(rec, ref)) return;
    var boot = document.getElementById('arenaBoot');
    if (!boot) return;
    boot.classList.add('arena-hero--photo');
    boot.style.backgroundImage = "url('" + String(rec.url).replace(/'/g, '%27') + "')";
  }

  function bindHeroFallbacks(scope) {
    var img = scope && scope.querySelector('.arena-hero__img');
    if (!img || img.__heroBound) return;
    img.__heroBound = true;
    img.addEventListener('error', function () {
      var rest = String(img.getAttribute('data-fallbacks') || '')
        .split('\n')
        .filter(Boolean);
      if (!rest.length) {
        var box = img.closest('.arena-hero');
        if (box) {
          box.classList.remove('arena-hero--photo');
          box.classList.add('arena-hero--placeholder');
        }
        img.remove();
        return;
      }
      img.setAttribute('data-fallbacks', rest.slice(1).join('\n'));
      img.src = rest[0];
    });
  }

  /** Фото тренера не отдалось — буква имени, а не значок битой картинки. */
  function bindAvatarFallbacks(scope) {
    if (!scope) return;
    [].forEach.call(scope.querySelectorAll('img.arena-coachcard__ava'), function (img) {
      if (img.__avaBound) return;
      img.__avaBound = true;
      img.addEventListener('error', function () {
        var mono = document.createElement('i');
        mono.className = 'arena-coachcard__ava arena-coachcard__ava--mono';
        mono.setAttribute('aria-hidden', 'true');
        mono.textContent = img.getAttribute('data-initial') || '';
        img.replaceWith(mono);
      });
    });
  }

  function prefetchUrlFor(card) {
    var rec = readHeroPrefetch();
    if (!card || !rec) return '';
    if (M.heroPrefetchMatches(rec, card.id) || M.heroPrefetchMatches(rec, card.slug)) {
      return rec.url;
    }
    return '';
  }

  function renderHero() {
    var card = state.card;
    var hero = M.heroView(card, prefetchUrlFor(card));
    var url = hero.url;
    var rest = (hero.urls || []).slice(1);
    var gallery = card.gallery || [];
    var n = gallery.length || (hero.mode === 'photo' ? 1 : 0);
    var cls = 'arena-hero' + (hero.mode === 'photo' ? ' arena-hero--photo' : ' arena-hero--placeholder');
    var galleryHtml = n === 1
      ? '<span class="arena-hero__gallery">Фото</span>'
      : '';
    var imgHtml = url
      ? '<img class="arena-hero__img" alt="" src="' +
        esc(url) +
        '"' +
        (rest.length ? ' data-fallbacks="' + esc(rest.join('\n')) + '"' : '') +
        '>'
      : '';
    /* TASK-306: «назад» и «поделиться» — круглыми кнопками на фото (шапка «Каток / Назад» ушла),
       Маршрут · Позвонить · Сайт — таблетками под названием, как на холсте. */
    var shareRound = global.GlideShareSheet
      ? '<button type="button" class="ga-round ga-press" data-action="share" aria-label="Поделиться">' + icon('share') + '</button>'
      : '';
    return (
      '<div class="' +
      cls +
      '">' +
      imgHtml +
      (hero.mode === 'photo' ? '<span class="arena-hero__shade"></span>' : '<span class="arena-hero__glare"></span>') +
      '<span class="arena-hero__top">' +
      '<button type="button" class="ga-round ga-press" data-action="back" aria-label="Назад">' + icon('back') + '</button>' +
      shareRound +
      '</span>' +
      '<span class="arena-hero__txt">' +
      '<h1>' +
      esc(card.name || 'Арена') +
      '</h1>' +
      '<span class="arena-hero__meta">' +
      esc(M.heroMetaLine(card)) +
      '</span>' +
      renderQuickActions() +
      '</span>' +
      galleryHtml +
      '</div>'
    );
  }

  /**
   * TASK-146: «Поделиться» на карточке места (DEC-004). Для катка с ближайшими
   * сеансами главная кнопка — «Позвать с собой»: зовут на конкретное время, а не
   * пересылают объявление (DEC-014 — приглашение не прячется в оверлей).
   */
  function skatingCard() {
    var c = state.card || {};
    if (typeof c.has_skating === 'boolean') return c.has_skating;
    var vt = String(c.venue_type || 'ice');
    return vt === 'ice' || vt === 'outdoor';
  }

  function scheduleFreshness() {
    var fromSessions = state.sessions && state.sessions.freshness;
    var fromCard = state.card && state.card.freshness;
    return fromSessions || fromCard || {};
  }

  function getFocusState() {
    var focusId = state.focus && state.focus.sessionId;
    var opts = {
      focusSessionId: focusId,
      freshness: scheduleFreshness(),
      sessionsError: state.sessionsError,
      sessionsLoaded: state.sessions != null && !state.sessionsError,
      todayIso: todayIso(),
      now: new Date(),
    };
    /* ОХМ лежит в ohm_days. Искать только массовое катание — и живой сеанс
       из ссылки объявляется пропавшим в блоке «Расписание». */
    return M.focusState(Object.assign({ days: combinedScheduleDays() }, opts));
  }

  function sharePickedId() {
    if (state.sharePickSessionId) return String(state.sharePickSessionId);
    var fs = getFocusState();
    if (fs.kind === 'found' && state.focus && state.focus.sessionId) {
      return String(state.focus.sessionId);
    }
    return null;
  }

  function resolvedShareSessionId() {
    var slots = scheduleSlots();
    var picked = sharePickedId();
    if (picked && sessionExistsInSchedule(picked)) return picked;
    var fs = getFocusState();
    if (fs.kind === 'gone') return null;
    return slots.length ? String(slots[0].id) : null;
  }

  function shareInviteCtaLabel() {
    var sid = resolvedShareSessionId();
    if (!sid || !scheduleSlots().length) return 'Позвать с собой';
    var when = M.shareSlotInviteLabel(
      combinedScheduleDays(),
      todayIso(),
      sid,
      state.day || state.ohmDay || todayIso()
    );
    return when ? 'Позвать на ' + when : 'Позвать с собой';
  }

  function companyButton() {
    if (!state.card || state.card.ice_company !== true) return '';
    var sid = resolvedShareSessionId();
    if (!sid) return '';
    return (
      '<button type="button" class="ga-btn ga-btn--dark ga-press" data-haptic="tap" data-action="ice-company" data-session="' +
      esc(sid) +
      '">' + icon('company') + 'Собрать компанию</button>'
    );
  }

  /** Строка над кнопками панели: «Сегодня, 10:15 · Массовое катание». */
  function shareBarWhen() {
    var sid = resolvedShareSessionId();
    if (!sid) return '';
    var label = M.shareSlotInviteLabel(combinedScheduleDays(), todayIso(), sid, todayIso());
    if (!label) return '';
    var isToday = /^\d{1,2}:\d{2}$/.test(label);
    var kind = sessionInOhm(sid) ? ohmChipTitle() : iceSectionTitle();
    return (isToday ? 'Сегодня, ' + label : capitalize(label)) + (kind ? ' · ' + kind : '');
  }

  function sessionInOhm(sid) {
    var days = ohmScheduleDays();
    var i;
    var j;
    for (i = 0; i < days.length; i++) {
      var list = days[i].sessions || [];
      for (j = 0; j < list.length; j++) if (String(list[j].id) === String(sid)) return true;
    }
    return false;
  }

  /*
   * TASK-306: «Позвать на …» и «Собрать компанию» — панелью внизу экрана. Тап по времени
   * меняет подпись, она мягко подпрыгивает, «Позвать» один раз светится — кнопка говорит
   * о выборе человека, а не об абстрактном «поделиться».
   */
  function renderShareBar() {
    if (!global.GlideShareSheet) return '';
    if (!scheduleSlots().length) return '';
    var company = companyButton();
    return (
      '<div class="ga-actionbar arena-bar" id="arenaShareBar">' +
      '<span class="arena-bar__when" id="arenaBarWhen">' + esc(shareBarWhen()) + '</span>' +
      '<div class="ga-actionbar__row' + (company ? '' : ' arena-bar__row--one') + '">' +
      '<button type="button" class="ga-btn ga-press" data-haptic="tap" data-action="share-invite">' + icon('invite') +
      '<span id="arenaBarInvite">' + esc(shareInviteCtaLabel()) + '</span></button>' +
      (company || '<button type="button" class="ga-btn ga-btn--soft ga-press" data-action="share">Поделиться</button>') +
      '</div>' +
      '</div>'
    );
  }

  function fetchShareSlots() {
    var today = todayIso();
    var to = addDaysIso(today, 13);
    var base = '/api/public/arenas/' + encodeURIComponent(String(state.card.id));
    return fetchJson(base + '/sessions?from=' + encodeURIComponent(today) + '&to=' + encodeURIComponent(to)).then(
      function (data) {
        if (data) {
          state.sessions = data;
        } else if (state.sessions == null && state.focus && state.focus.sessionId) {
          /* 404 при фокусе из ссылки — не помечаем расписание «загруженным пустым». */
        } else if (state.sessions == null) {
          state.sessions = { days: [], ohm_days: [] };
        }
        var days = combinedScheduleDays();
        return {
          slots: M.shareSlots(days, today, 0),
          slotSections: M.shareSlotsGrouped(days, today),
        };
      }
    );
  }

  function openShare(mode) {
    if (!global.GlideShareSheet || !state.card) return;
    var isIce = skatingCard();
    var payload = isIce ? shareSheetPayload() : { slots: [], slotSections: [] };
    var loadSlots =
      isIce && payload.slots.length <= 1
        ? function () {
            return fetchShareSlots();
          }
        : null;
    var fs = getFocusState();
    global.GlideShareSheet.open({
      ref: state.card.id,
      slots: payload.slots,
      slotSections: payload.slotSections,
      sessionId: resolvedShareSessionId(),
      sessionMissing: fs.kind === 'gone',
      invite: mode === 'invite',
      variant: mode === 'company' ? 'company' : '',
      company: !!(state.card && state.card.ice_company === true),
      venueType: skatingCard() ? 'ice' : state.card.venue_type,
      context: 'arena_card',
      placeName: state.card.name || '',
      loadSlots: loadSlots,
    });
  }

  function renderAmenities() {
    if (String(state.card.venue_type || '') === 'shop') return renderShopServices();
    var chips = M.amenityChips(state.card.amenities);
    if (!chips.length) return '';
    var food = foodPartner();
    return (
      '<div class="arena-sec"><div class="arena-amen">' +
      chips.map(function (c) {
        // Чип «Кафе» при партнёре-кафе ведёт к блоку «После катка».
        if (food && c === 'Кафе') {
          return '<a href="#arenaPartners">' + esc(c) + '<span class="gp-chip-mark">' + esc(food.offer) + '</span></a>';
        }
        return '<span>' + esc(c) + '</span>';
      }).join('') +
      '</div></div>'
    );
  }

  function partnersList() {
    var list = state.card && state.card.partners;
    return Array.isArray(list) ? list : [];
  }

  function foodPartner() {
    var list = partnersList();
    for (var i = 0; i < list.length; i++) {
      if (list[i].kind === 'food' || list[i].kind === 'coffee') return list[i];
    }
    return null;
  }

  /** «После катка»: партнёры рядом (src/application/arena_partners.py), шторка — partner-sheet.js. */
  function renderPartners() {
    var list = partnersList();
    if (!list.length || !global.GlidePartners) return '';
    var rows = list.map(function (p) {
      var photo = (p.photos && p.photos[0]) || p.logo;
      var media = photo
        ? '<img class="gp-row__media" src="' + esc(photo) + '" alt="" width="80" height="80" loading="lazy" decoding="async" />'
        : '<span class="gp-row__media"></span>';
      var line = [p.line, p.where].filter(Boolean).join(' · ');
      return (
        '<button type="button" class="gp-row" data-partner="' + esc(p.slug) + '">' + media +
        '<span class="gp-row__body"><span class="gp-row__name">' + esc(p.name) + '</span>' +
        '<span class="gp-row__line">' + esc(line) + '</span>' +
        '<span class="gp-row__offer">' + esc(p.offer) + ' с\u00a0Glide</span></span>' +
        '<svg class="gp-row__chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg></button>'
      );
    }).join('');
    return (
      '<div class="arena-sec" id="arenaPartners"><div class="gp-head-row"><p class="arena-h">После катка</p>' +
      '<span class="gp-kicker">Партнёры Glide</span></div><div class="gp-list">' + rows + '</div></div>'
    );
  }

  /** Окна массового катания и прокат — structured opening_hours, не простыня в описании. */
  function renderMassAccess() {
    var mass = M.massAccessView(state.card);
    if (!mass.enabled) return '';
    var html = '<div class="arena-sec"><p class="arena-h">Когда можно приехать</p>';
    var headOnly = html;
    if (mass.freeEntry) {
      html += '<p class="arena-kicker arena-kicker--ok">Вход бесплатно · бронь слотов не нужна</p>';
    }
    if (mass.accessNote) {
      html += '<p class="arena-sub">' + esc(mass.accessNote) + '</p>';
    }
    if (mass.week) {
      var status = mass.week.status ? '<em class="arena-info__open">' + esc(mass.week.status) + '</em>' : '';
      if (mass.week.uniform) {
        html +=
          '<div class="arena-info arena-info--flat"><small>Каждый день</small><b>Ежедневно ' +
          esc(mass.week.rows[0].value) +
          '</b>' +
          status +
          '</div>';
      } else {
        html +=
          '<div class="arena-info arena-info--flat"><small>Окна для любителей</small>' +
          status +
          '<ul class="arena-week">' +
          mass.week.rows
            .map(function (r) {
              return (
                '<li class="' +
                (r.today ? 'is-today' : '') +
                (r.closed ? ' is-closed' : '') +
                '"><span>' +
                esc(r.label) +
                '</span><span>' +
                esc(r.value) +
                '</span></li>'
              );
            })
            .join('') +
          '</ul></div>';
      }
    }
    var foot = [];
    if (mass.rentalClose) foot.push('Прокат до ' + mass.rentalClose);
    if (mass.trackClose) foot.push('освещение трассы до ' + mass.trackClose);
    if (foot.length) {
      html += '<p class="arena-sub arena-sub--tight">' + esc(foot.join(' · ')) + '</p>';
    }
    // Прайс проката сам по себе не «когда приехать»: без часов и пометок заголовок остался бы пустым.
    html = html === headOnly ? '' : html + '</div>';
    if (mass.rentalCatalog.length && !visit()) {
      html += '<div class="arena-sec"><p class="arena-h">' + esc(mass.rentalTitle || 'Прокат инвентаря') + '</p><ul class="arena-price-list">';
      mass.rentalCatalog.forEach(function (row) {
        html +=
          '<li class="arena-price-list__row"><span class="arena-price-list__name">' +
          esc(row.label || '') +
          '</span><span class="arena-price-list__price">' +
          esc(row.price || '') +
          (row.per ? '<small>/' + esc(row.per) + '</small>' : '') +
          '</span>';
        if (row.note) {
          html += '<span class="arena-price-list__note">' + esc(row.note) + '</span>';
        }
        html += '</li>';
      });
      if (mass.rentalNote) {
        html += '<p class="arena-sub">' + esc(mass.rentalNote) + '</p>';
      }
      html += '</div>';
    }
    return html;
  }

  function renderPriceRows(catalog) {
    var html = '<ul class="arena-price-list">';
    catalog.forEach(function (row) {
      html +=
        '<li class="arena-price-list__row"><span class="arena-price-list__name">' +
        esc(row.label || '') +
        '</span><span class="arena-price-list__price">' +
        esc(row.price || '') +
        (row.per ? '<small>/' + esc(row.per) + '</small>' : '') +
        '</span>';
      if (row.note) html += '<span class="arena-price-list__note">' + esc(row.note) + '</span>';
      html += '</li>';
    });
    return html + '</ul>';
  }

  /** Хоккейный центр: что это за место и прайс. Часы и телефон остаются в контактах. */
  function renderCenterOffer() {
    if (typeof M.centerOfferView !== 'function') return '';
    var offer = M.centerOfferView(state.card);
    if (!offer.enabled) return '';
    var html = '<div class="arena-sec">';
    if (offer.about) html += '<p class="arena-sub">' + esc(offer.about) + '</p>';
    if (offer.catalog.length) {
      html += '<p class="arena-h">' + esc(offer.title || 'Услуги') + '</p>';
      html += renderPriceRows(offer.catalog);
      if (offer.note) html += '<p class="arena-sub">' + esc(offer.note) + '</p>';
    }
    return html + '</div>';
  }

  /** TASK-146: у магазина вместо чипов удобств — плитки услуг и специализация. */
  function renderShopServices() {
    var v = M.shopServicesView(state.card.amenities);
    if (!v.tiles.length && !v.disciplines.length) return '';
    var tiles = v.tiles
      .map(function (t) {
        return (
          '<div class="arena-svc"><b>' + esc(t.title) + '</b><span>' + esc(t.sub) + '</span></div>'
        );
      })
      .join('');
    var tags = v.disciplines.length
      ? '<div class="arena-amen arena-svc-for">' +
        v.disciplines.map(function (d) { return '<span>' + esc(d) + '</span>'; }).join('') +
        '</div>'
      : '';
    return (
      '<div class="arena-sec"><p class="arena-h">Что здесь можно сделать</p>' +
      (tiles ? '<div class="arena-svcs">' + tiles + '</div>' : '') +
      tags +
      '</div>'
    );
  }

  function rowHtml(row) {
    var stripe = row.stripe || (row.nature === 'lesson' ? 'lesson' : 'ice');
    var cls =
      'arena-row' +
      (stripe === 'lesson' ? ' arena-row--lesson' : '') +
      (row.nowState === 'live' ? ' arena-row--live' : '') +
      (row.empty ? ' arena-row--empty' : '');
    var ctaCls = 'arena-cta arena-cta--' + (row.ctaKind || 'ghost');
    var tag = 'div';
    var extra = '';
    if (row.nature === 'lesson' || row.openDay) {
      tag = 'button';
      extra = ' type="button"';
    } else if (row.nature === 'ice' && row.href && !row.empty) {
      tag = 'a';
      extra =
        ' href="' +
        esc(row.href) +
        '" data-action="external" data-href="' +
        esc(row.href) +
        '" target="_blank" rel="noopener noreferrer"';
    }
    if (row.nature === 'lesson' && row.group) {
      extra += ' data-action="group" data-trainer="' + esc(row.trainerId) + '" data-group="' + esc(row.group.id) + '"';
    }
    if (row.openDay) extra += ' data-action="open-day" data-date="' + esc(row.localDate) + '"';
    return (
      '<' + tag + ' class="' + cls + '"' + extra + '>' +
      '<span class="arena-row__t">' + esc(row.time || row.weekday) + '</span>' +
      '<span class="arena-row__m"><b>' + esc(row.title) + '</b><span>' + esc(row.meta || '') + '</span></span>' +
      (row.cta ? '<span class="' + ctaCls + '">' + esc(row.cta) + '</span>' : '') +
      '</' + tag + '>'
    );
  }

  function ribbonForIso(iso) {
    var byDate = sessionsByDate();
    return M.buildRibbonForDay({
      localDate: iso,
      sessions: byDate[iso] || [],
      groups: allGroups(),
      weekday: weekdayOf(iso),
      now: new Date(),
      ticketsUrl: state.card && state.card.tickets_url,
    });
  }

  var ICONS = {
    route: '<path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    copyPhone:
      '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
    site: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    insta: '<rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.5"/><circle cx="17" cy="7" r="0.6"/>',
    share: '<path d="M12 15V4M8 8l4-4 4 4"/><path d="M5 13v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/>',
    back: '<path d="M15 18l-6-6 6-6"/>',
    invite: '<path d="M21 4L3 11l6 2 2 6 3-4 5 4z"/>',
    company: '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M15 14.5c3 .2 6 2.4 6 5.5"/>',
    buy: '<path d="M7 17L17 7M9 7h8v8"/>',
  };

  function icon(id) {
    return '<svg viewBox="0 0 24 24" aria-hidden="true">' + (ICONS[id] || '') + '</svg>';
  }

  /** Ряд быстрых действий под обложкой: то, ради чего открывают карточку места. */
  function renderPhoneLinks(phones) {
    return (phones || []).map(function (p, i) {
      var sep = i ? '<span class="arena-info__phone-sep">; </span>' : '';
      return (
        sep +
        '<button type="button" class="arena-info__tel arena-info__tel--copy" data-action="copy-phone" data-copy-phone="' +
        esc(p) +
        '">' +
        esc(p) +
        '</button>'
      );
    }).join('');
  }

  function renderQuickActions() {
    var items = M.quickActions(state.card).map(function (a) {
      if (a.id === 'copyPhone') {
        return (
          '<button type="button" class="ga-onphoto ga-press" data-action="copy-phone" data-copy-phone="' +
          esc(a.phone || '') +
          '">' +
          icon(a.id) +
          '<span>' +
          esc(a.label) +
          '</span></button>'
        );
      }
      return (
        '<a class="ga-onphoto ga-press" href="' +
        esc(a.href) +
        '" data-action="external" data-href="' +
        esc(a.href) +
        '">' +
        icon(a.id) +
        '<span>' +
        esc(a.label) +
        '</span></a>'
      );
    });
    // «Поделиться» теперь всегда круглой кнопкой на фото — здесь только то, ради чего открывают место.
    var bell = heroBellHtml();
    if (bell) items.push(bell);
    if (!items.length) return '';
    return '<span class="arena-hero__chips">' + items.join('') + '</span>';
  }

  function scheduleDays() {
    return (state.sessions && state.sessions.days) || [];
  }

  function ohmScheduleDays() {
    return (state.sessions && state.sessions.ohm_days) || [];
  }

  /** MK + ОХМ в одной ленте; дублируем merge, если WebView держит старый arena-card-model.js. */
  function combineSessionDayLists(days, ohmDays) {
    if (M && typeof M.combineSessionDayLists === 'function') {
      return M.combineSessionDayLists(days, ohmDays);
    }
    var order = [];
    var byDate = {};
    function add(list) {
      list = list || [];
      var i;
      for (i = 0; i < list.length; i++) {
        var iso = list[i].local_date;
        if (!iso) continue;
        if (!byDate[iso]) {
          byDate[iso] = [];
          order.push(iso);
        }
        byDate[iso] = byDate[iso].concat(list[i].sessions || []);
      }
    }
    add(days);
    add(ohmDays);
    return order.map(function (iso) {
      return { local_date: iso, sessions: byDate[iso] };
    });
  }

  function combinedScheduleDays() {
    return combineSessionDayLists(scheduleDays(), ohmScheduleDays());
  }

  function scheduleSlots() {
    return skatingCard() ? M.shareSlots(combinedScheduleDays(), todayIso(), 0) : [];
  }

  function shareSheetPayload() {
    var today = todayIso();
    var days = combinedScheduleDays();
    return {
      slots: M.shareSlots(days, today, 0),
      slotSections: M.shareSlotsGrouped(days, today),
    };
  }

  function sessionExistsInSchedule(sessionId) {
    if (sessionId == null) return false;
    var id = String(sessionId);
    return scheduleSlots().some(function (s) { return String(s.id) === id; });
  }

  function copyLine(key, fallback) {
    var GC = global.GlideCopy;
    if (GC && typeof GC.t === 'function') {
      var label = GC.t(key);
      if (label && label !== key) return String(label);
    }
    return fallback;
  }

  function displayHost(url) {
    var rest = String(url || '').replace(/^[a-z][a-z0-9+.-]*:\/\//i, '');
    var host = rest.split('/')[0].split('?')[0].split('#')[0].replace(/^www\./i, '');
    return host || String(url || '');
  }

  /** Заголовок блока сеансов катка: «Массовое катание», не «Расписание» — так же, как на сайте. */
  function iceSectionTitle() {
    var GC = global.GlideCopy;
    if (GC && typeof GC.t === 'function') {
      var label = GC.t('kind.public_skate');
      if (label && label !== 'kind.public_skate') return String(label);
    }
    return 'Массовое катание';
  }

  function ohmChipTitle() {
    var GC = global.GlideCopy;
    if (GC && typeof GC.t === 'function') {
      var label = GC.t('kind.hockey_practice');
      if (label && label !== 'kind.hockey_practice') return String(label);
    }
    return 'ОХМ';
  }

  function strip() {
    return M.dayStrip((state.sessions && state.sessions.days) || [], todayIso(), new Date(), 7);
  }

  /** TASK-223: сеанс из ссылки не в ленте — честно, без «прошёл». */
  function renderFocusGoneNotice(fs) {
    if (!fs || fs.kind !== 'gone') return '';
    // TODO(TASK-223-D): событие share_session_gone
    var nearestBtn = '';
    if (fs.nearest && fs.nearest.id != null) {
      nearestBtn =
        '<button type="button" class="arena-focus-gone__pick" data-action="pick-session" data-session-id="' +
        esc(String(fs.nearest.id)) +
        '" data-local-date="' +
        esc(fs.nearest.localDate || '') +
        '">Ближайший: ' +
        esc(fs.nearest.label || '') +
        '</button>';
    }
    return (
      '<div class="arena-focus-gone">' +
      '<p class="arena-focus-gone__title">Сеанса из ссылки уже нет в расписании</p>' +
      nearestBtn +
      '</div>'
    );
  }

  /** «Сегодня» → «Сег», «Завтра» → «Зав»: семь дней в ряд без обрезанного «Сегод…». */
  function shortDayTop(top) {
    var low = String(top || '').toLowerCase();
    if (low === 'сегодня') return 'Сег';
    if (low === 'завтра') return 'Зав';
    return top;
  }

  function renderDayStrip(days) {
    return (
      '<div class="arena-strip" id="arenaDayTabs" role="tablist">' +
      days.map(function (d) {
        return (
          '<button type="button" role="tab" class="arena-strip__day' +
          (d.count ? '' : ' arena-strip__day--empty') +
          (d.weekend ? ' arena-strip__day--weekend' : '') +
          '" data-day="' + esc(d.iso) + '" aria-pressed="' + (state.day === d.iso ? 'true' : 'false') + '">' +
          '<span>' + esc(shortDayTop(d.top)) + '</span><b>' + esc(d.num) + '</b>' +
          '<i>' + (d.count ? esc(String(d.count)) : '—') + '</i>' +
          '</button>'
        );
      }).join('') +
      '</div>'
    );
  }

  /** Подпись дня для «билета»: «СЕГОДНЯ», «ЗАВТРА», «ЧТ, 22». */
  function ticketDayLabel(days, iso) {
    var d = (days || []).filter(function (x) { return x.iso === iso; })[0];
    if (!d) return '';
    var top = String(d.top || '');
    var low = top.toLowerCase();
    return (low === 'сегодня' || low === 'завтра' ? top : top + ', ' + d.num).toUpperCase();
  }

  /*
   * TASK-306: выбранный сеанс — «билет» над сеткой: время крупно, загрузка, цены и «Купить билет».
   * В сетке остаётся только время с загрузкой — без ↗ у каждой плитки: купить можно из «билета»,
   * а главные кнопки «Позвать» и «Собрать компанию» — в панели внизу.
   */
  function showGroupHtml(g, sectionTitle, dayLabel, pricesAbove) {
    var ownTitle = g.title && g.title !== sectionTitle ? g.title : '';
    var hasPick = g.times.some(function (t) { return t.picked; });
    var head = '';
    // Длительность уже в «билете» — над ним её не повторяем.
    if (ownTitle || (g.duration && !hasPick)) {
      head =
        '<div class="arena-show__head">' +
        (ownTitle ? '<b>' + esc(ownTitle) + '</b>' : '') +
        (g.duration && !hasPick ? '<span>' + esc(g.duration) + '</span>' : '') +
        '</div>';
    }
    var picked = g.times.filter(function (t) { return t.picked; })[0] || null;
    // Цены уже стоят плитками над расписанием — строкой под датами их не повторяем.
    var pricesLine = !picked && !pricesAbove && g.prices.length
      ? '<p class="arena-show__line">' + g.prices.map(function (p) { return esc(p.label) + ' ' + esc(p.value); }).join(' · ') + '</p>'
      : '';
    var ticket = '';
    if (picked) {
      var tag = slotTag(picked);
      var low = picked.seats && picked.seats.low;
      ticket =
        '<div class="arena-ticket">' +
        '<div class="arena-ticket__top"><span class="arena-ticket__lead">' +
        '<span class="arena-ticket__kick">' + esc([dayLabel, g.duration ? g.duration.toUpperCase() : ''].filter(Boolean).join(' · ')) + '</span>' +
        '<b class="arena-ticket__time">' + esc(picked.time) + '</b></span>' +
        (tag ? '<span class="arena-ticket__seats' + (low ? ' arena-seats--low' : '') + '">' + esc(tag) + '</span>' : loadMeterHtml(picked.load)) +
        '</div>' +
        (g.prices.length
          ? '<div class="arena-ticket__prices">' + g.prices.map(function (p) {
              return '<span><small>' + esc(p.label) + '</small><b>' + esc(p.value) + '</b></span>';
            }).join('') + '</div>'
          : '') +
        (picked.ticketHref
          ? '<button type="button" class="ga-btn ga-btn--dark ga-btn--block ga-press" data-action="external" data-href="' +
            esc(picked.ticketHref) + '">Купить билет' + icon('buy') + '</button>'
          : '') +
        (g.note ? '<p class="arena-ticket__note">' + esc(g.note) + '</p>' : '') +
        '</div>';
    }
    var grid = g.times.map(function (t) {
      var slotCls = 'arena-slot arena-slot--no-buy';
      if (t.picked) slotCls += ' arena-slot--picked';
      var timeCls = 'arena-slot-time ga-press';
      if (t.picked) timeCls += ' arena-time--picked';
      else if (t.next) timeCls += ' arena-time--next';
      var body = slotBody(t);
      if (t.sessionId == null) return '<div class="' + slotCls + '"><span class="' + timeCls + '">' + body + '</span></div>';
      return (
        '<div class="' + slotCls + '">' +
        '<button type="button" class="' + timeCls + '" data-action="pick-session" data-session-id="' + esc(t.sessionId) +
        '" aria-pressed="' + (t.picked ? 'true' : 'false') + '">' + body + '</button></div>'
      );
    }).join('');
    return (
      '<div class="arena-show">' + head + pricesLine + ticket +
      '<div class="arena-times">' + grid + '</div>' +
      (g.note && !picked ? '<p class="arena-show__note">' + esc(g.note) + '</p>' : '') +
      '</div>'
    );
  }

  function renderShowtimes() {
    var iso = state.day || todayIso();
    var byDate = sessionsByDate();
    var view = M.showtimesForDay({
      sessions: byDate[iso] || [],
      now: new Date(),
      ticketsUrl: state.card && state.card.tickets_url,
      markNext: iso === todayIso(),
      pickedId: resolvedShareSessionId(),
    });
    var lessons = ribbonForIso(iso).filter(function (r) { return r.nature === 'lesson'; });
    var html = '';
    if (!view.count) {
      var next = strip().filter(function (d) { return d.count && d.iso > iso; })[0];
      html +=
        '<div class="arena-none"><b>' + (iso === todayIso() ? 'Сегодня сеансов больше нет' : 'В этот день сеансов нет') + '</b>' +
        (next ? '<button type="button" class="linkish" data-day-jump="' + esc(next.iso) + '">Ближайший — ' + esc(next.top.toLowerCase() === 'завтра' ? 'завтра' : next.top + ' ' + next.num) + ' →</button>' : '') +
        '</div>';
    }
    var sectionTitle = iceSectionTitle();
    var dayLabel = ticketDayLabel(strip(), iso);
    var f = priceFloors();
    var pricesAbove = !!(f.adult || f.child || f.rental);
    view.groups.forEach(function (g) {
      html += showGroupHtml(g, sectionTitle, dayLabel, pricesAbove);
    });
    if (lessons.length) {
      html += '<p class="arena-h arena-h--sub">Занятия с тренером</p><div class="arena-rows">' + lessons.map(rowHtml).join('') + '</div>';
    }
    return html;
  }

  var BELL_PATHS = '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 20a2 2 0 0 0 4 0"/>';

  /** TASK-330: сеансов нет, каток расписание ведёт — привычка катка и колокольчик главным действием. */
  function renderScheduleWait(feed) {
    var w = feed.wait;
    var canWatch = !!initData();
    var on = !!(state.iceWatchKinds && state.iceWatchKinds.sessions);
    var bell = '';
    if (canWatch && on) {
      bell =
        '<div class="arena-wait__on">' +
        '<svg class="arena-wait__ico" viewBox="0 0 24 24" aria-hidden="true">' + BELL_PATHS + '</svg>' +
        '<span class="arena-wait__on-t">' + esc(w.on) + '</span>' +
        '<button type="button" class="linkish" data-action="ice-watch" data-watch-kind="sessions" aria-pressed="true">' +
        esc(w.off) +
        '</button></div>';
    } else if (canWatch) {
      bell =
        '<button type="button" class="arena-btn arena-btn--pri arena-wait__cta" data-action="ice-watch" data-watch-kind="sessions" aria-pressed="false">' +
        '<svg class="arena-wait__ico" viewBox="0 0 24 24" aria-hidden="true">' + BELL_PATHS + '</svg>' +
        '<span>' + esc(w.cta) + '</span></button>' +
        '<p class="arena-wait__note">' + esc(w.note) + '</p>';
    }
    var alt = '';
    if (feed.mode === 'phone' && feed.callHref) {
      alt = '<a class="arena-btn" href="' + esc(feed.callHref) + '">' + esc(copyLine('cta.call', 'Позвонить')) + '</a>';
    } else if (feed.mode === 'site' && feed.siteHref) {
      alt =
        '<a class="arena-btn" href="' + esc(feed.siteHref) + '" data-action="external" data-href="' + esc(feed.siteHref) + '">' +
        esc(displayHost(feed.siteHref)) +
        '</a>';
    }
    return (
      '<div class="arena-sec">' +
      '<p class="arena-h">' + esc(iceSectionTitle()) + '</p>' +
      '<div class="arena-wait">' +
      '<div class="arena-wait__head">' +
      (w.kicker ? '<p class="arena-wait__kicker">' + esc(w.kicker) + '</p>' : '') +
      '<p class="arena-wait__title">' + esc(w.title) + '</p>' +
      (canWatch ? '<p class="arena-wait__sub">' + esc(w.sub) + '</p>' : '') +
      '</div>' +
      bell +
      alt +
      '</div></div>'
    );
  }

  function renderScheduleFact(feed) {
    feed = feed || {};
    var action = '';
    if (feed.mode === 'phone' && feed.callHref) {
      action =
        '<a class="arena-btn arena-btn--pri" href="' +
        esc(feed.callHref) +
        '">' +
        esc(copyLine('cta.call', 'Позвонить')) +
        '</a>';
    } else if (feed.mode === 'site' && feed.siteHref) {
      action =
        '<a class="arena-btn" href="' +
        esc(feed.siteHref) +
        '" data-action="external" data-href="' +
        esc(feed.siteHref) +
        '">' +
        esc(displayHost(feed.siteHref)) +
        '</a>';
    }
    if (!feed.banner && !action) return '';
    var intro = feed.banner ? '<div class="arena-closed">' + esc(feed.banner) + '</div>' : '';
    return (
      '<div class="arena-sec">' +
      '<p class="arena-h">' +
      esc(iceSectionTitle()) +
      '</p>' +
      intro +
      action +
      '</div>'
    );
  }

  function renderIceSection() {
    /* Секция про массовое катание существует только для льда. На зале она
       обещала бы расписание сеансов, которых там не бывает в принципе —
       это неверный вопрос к площадке. */
    // has_skating — каток или уличный лёд (сервер: venue_types.has_public_skating).
    if (!skatingCard()) return '';
    if (state.sessionsError) {
      return (
        '<div class="arena-sec">' +
        '<p class="arena-h">' + esc(iceSectionTitle()) + '</p>' +
        '<div class="arena-empty">' +
        '<b>Не удалось загрузить расписание</b>' +
        '<p>Похоже, пропала связь. Расписание можно загрузить заново.</p>' +
        '<button type="button" class="arena-btn" data-action="retry-sessions">Повторить</button>' +
        '</div>' +
        '</div>'
      );
    }
    var feed = M.iceFeedView({
      card: state.card,
      hasSessions: hasAnySessions(),
    });
    if (feed.mode === 'closed') {
      return (
        '<div class="arena-sec">' +
        '<p class="arena-h">' + esc(iceSectionTitle()) + '</p>' +
        '<div class="arena-closed">' + esc(feed.banner) + '</div>' +
        renderSeasonRemindBlock() +
        '</div>'
      );
    }
    if (feed.wait) return renderScheduleWait(feed);
    if (feed.mode === 'phone' || feed.mode === 'site' || feed.mode === 'none' || feed.mode === 'pending') {
      return renderScheduleFact(feed);
    }
    var days = strip();
    if (!state.day) {
      // День из ленты — если он есть в полосе; иначе свой умный дефолт.
      var focusDay = state.focus && state.focus.day;
      var inStrip = focusDay && days.some(function (d) { return d.iso === focusDay; });
      state.day = inStrip ? focusDay : M.defaultScheduleDay(days);
    }
    var tickets = M.ticketCta(state.card);
    var iso = state.day || todayIso();
    var byDate = sessionsByDate();
    var daySessions = byDate[iso] || [];
    var hasTicketLinks = daySessions.some(function (s) {
      return M.iceRowCta(s, state.card && state.card.tickets_url).href;
    });
    var hasLoad = daySessions.some(function (s) {
      return !!LOAD_LABELS[s.typical_load_level];
    });
    var hasSeats = daySessions.some(function (s) {
      return !!M.liveSeats(s.capacity_note);
    });
    var hint = M.scheduleInviteHint(hasTicketLinks, hasLoad, hasSeats);
    var focusGone = renderFocusGoneNotice(getFocusState());
    return (
      '<div class="arena-sec">' +
      '<div class="arena-h-row"><p class="arena-h">' + esc(iceSectionTitle()) + '</p>' +
      scheduleHeaderTools(tickets) +
      '</div>' +
      focusGone +
      renderVisitPrices() +
      renderBuyLine() +
      (hint ? '<p class="arena-schedule-hint">' + esc(hint) + '</p>' : '') +
      renderDayStrip(days) +
      '<div id="arenaRows">' + renderShowtimes() + '</div>' +
      '</div>'
    );
  }

  function hasOhmSessions() {
    var days = ohmScheduleDays();
    var i;
    for (i = 0; i < days.length; i++) {
      if ((days[i].sessions || []).length) return true;
    }
    return false;
  }

  function ohmStrip() {
    return M.dayStrip(ohmScheduleDays(), todayIso(), new Date(), 7);
  }

  function renderOhmShowtimes() {
    var iso = state.ohmDay || todayIso();
    var byDate = {};
    var days = ohmScheduleDays();
    var i;
    for (i = 0; i < days.length; i++) {
      byDate[days[i].local_date] = days[i].sessions || [];
    }
    var view = M.showtimesForDay({
      sessions: byDate[iso] || [],
      now: new Date(),
      ticketsUrl: state.card && state.card.tickets_url,
      markNext: iso === todayIso(),
      pickedId: resolvedShareSessionId(),
    });
    if (!view.count) {
      var next = ohmStrip().filter(function (d) { return d.count && d.iso > iso; })[0];
      return (
        '<div class="arena-none"><b>' +
        (iso === todayIso() ? 'Сегодня ОХМ больше нет' : 'В этот день ОХМ нет') +
        '</b>' +
        (next
          ? '<button type="button" class="linkish" data-ohm-day-jump="' +
            esc(next.iso) +
            '">Ближайший — ' +
            esc(next.top.toLowerCase() === 'завтра' ? 'завтра' : next.top + ' ' + next.num) +
            ' →</button>'
          : '') +
        '</div>'
      );
    }
    var html = '';
    var sectionTitle = ohmChipTitle();
    var ohmDayLabel = ticketDayLabel(ohmStrip(), iso);
    view.groups.forEach(function (g) {
      html += showGroupHtml(g, sectionTitle, ohmDayLabel);
    });
    return html;
  }

  function renderOhmSection() {
    if (!skatingCard() || state.sessionsError || !hasOhmSessions()) return '';
    var days = ohmStrip();
    if (!state.ohmDay) {
      var focusDay = state.focus && state.focus.day;
      var inStrip = focusDay && days.some(function (d) { return d.iso === focusDay; });
      var focusInOhm =
        state.focus &&
        state.focus.sessionId &&
        M.dayForSession(ohmScheduleDays(), state.focus.sessionId);
      state.ohmDay = focusInOhm || (inStrip ? focusDay : M.defaultScheduleDay(days));
    }
    return (
      '<div class="arena-sec" id="arenaOhm">' +
      '<div class="arena-h-row"><p class="arena-h">' +
      esc(ohmChipTitle()) +
      '</p></div>' +
      '<div class="arena-strip" id="arenaOhmDayTabs" role="tablist" aria-label="' +
      esc(ohmChipTitle()) +
      '">' +
      days
        .map(function (d) {
          return (
            '<button type="button" role="tab" class="arena-strip__day' +
            (d.count ? '' : ' arena-strip__day--empty') +
            (d.weekend ? ' arena-strip__day--weekend' : '') +
            '" data-ohm-day="' +
            esc(d.iso) +
            '" aria-pressed="' +
            (state.ohmDay === d.iso ? 'true' : 'false') +
            '">' +
            '<span>' +
            esc(d.top) +
            '</span><b>' +
            esc(d.num) +
            '</b>' +
            '<i>' +
            (d.count ? esc(String(d.count)) : '—') +
            '</i></button>'
          );
        })
        .join('') +
      '</div>' +
      '<div id="arenaOhmRows">' +
      renderOhmShowtimes() +
      '</div>' +
      '</div>'
    );
  }

  /** Конец выбранного сеанса по местному времени катка: «2026-10-20T11:00». */
  function selectedSessionEndLocal() {
    var sid = resolvedShareSessionId();
    if (!sid) return '';
    var lists = [];
    var byDate = sessionsByDate();
    Object.keys(byDate).forEach(function (k) { lists.push(byDate[k] || []); });
    ohmScheduleDays().forEach(function (d) { lists.push(d.sessions || []); });
    var i;
    var j;
    for (i = 0; i < lists.length; i++) {
      for (j = 0; j < lists[i].length; j++) {
        var x = lists[i][j];
        if (String(x.id) === String(sid)) return String(x.ends_at_local || x.starts_at_local || '').slice(0, 16);
      }
    }
    return '';
  }

  /*
   * TASK-306: тренеры — отдельный тёмный блок после расписания, а не список внизу.
   * У каждого — ближайшие свободные окна на этом катке (`windows` из /arenas/{ref}/trainers);
   * первое окно после выбранного сеанса подсвечено: «после твоего катания — свободно в 13:00».
   * Окон нет — карточка ведёт в профиль тренера, как раньше («Записаться» / «Написать»).
   */
  function renderTrainers() {
    if (state.trainersError) {
      return (
        '<div class="arena-sec"><p class="arena-h">Тренеры на этой арене</p>' +
        '<div class="arena-empty">' +
        '<b>Не удалось загрузить тренеров</b>' +
        '<p>Похоже, пропала связь. Список тренеров можно загрузить заново.</p>' +
        '<button type="button" class="arena-btn" data-action="retry-trainers">Повторить</button>' +
        '</div></div>'
      );
    }
    var items = (state.trainers && state.trainers.items) || [];
    if (!items.length) return '';
    var after = selectedSessionEndLocal();
    var place = (state.card && state.card.name) || '';
    var anyFit = false;
    /* Вариант А (владелец 2026-10-20): фото-витрина. Вся карточка ведёт в профиль тренера —
       окна больше не кнопки: запись по голому окну без контекста тренера не открывалась. */
    var cards = items.map(function (t) {
      var v = M.trainerPreview(t, { after: after });
      if (v.fit) anyFit = true;
      var ava = photoUrl(t);
      return (
        '<button type="button" class="arena-coachcard ga-press" data-action="trainer" data-trainer="' + esc(t.id) +
        '" data-can-book="' + (t.can_book ? '1' : '0') + '">' +
        '<span class="arena-coachcard__ph">' +
        (ava
          ? '<img class="arena-coachcard__ava" alt="" data-initial="' + esc(trainerInitial(t)) + '" src="' + esc(ava) + '">'
          : '<i class="arena-coachcard__ava arena-coachcard__ava--mono" aria-hidden="true">' + esc(trainerInitial(t)) + '</i>') +
        (v.rate ? '<span class="arena-coachcard__rate"><i aria-hidden="true">★</i>' + esc(v.rate) + '</span>' : '') +
        (v.fit ? '<span class="arena-coachcard__fit">' + esc(v.fit) + '</span>' : '') +
        '</span>' +
        '<span class="arena-coachcard__body">' +
        '<b class="arena-coachcard__name">' + esc(trainerName(t)) + '</b>' +
        (v.what ? '<span class="arena-coachcard__what">' + esc(v.what) + '</span>' : '') +
        (v.facts ? '<span class="arena-coachcard__facts">' + esc(v.facts) + '</span>' : '') +
        '<span class="arena-coachcard__price">' + (v.price ? '<b>' + esc(v.price) + '</b>' : '<b></b>') +
        '<span>' + esc(v.fit ? 'Профиль →' : v.next) + '</span></span>' +
        '</span>' +
        '</button>'
      );
    }).join('');
    // Заголовок — по выбранному сеансу: с клюшкой — про бросок, иначе — «научат здесь же».
    var sid = resolvedShareSessionId();
    var title = !sid ? 'Тренеры этого катка' : sessionInOhm(sid) ? 'Поставят бросок здесь же' : 'Научат здесь же';
    var kick = (sid ? 'Тренеры этого катка' : place || 'Тренеры') + ' · ' + items.length;
    return (
      '<section class="arena-coaches" aria-labelledby="arenaCoachesTitle">' +
      '<div class="arena-coaches__head">' +
      '<span class="ga-kicker arena-coaches__kick">' + esc(kick) + '</span>' +
      '<h2 class="ga-h2" id="arenaCoachesTitle">' + esc(title) + '</h2>' +
      (anyFit ? '<p class="arena-coaches__sub">Есть свободные окна сразу после твоего катания</p>' : '') +
      '</div>' +
      '<div class="arena-coaches__row">' + cards + '</div>' +
      '</section>'
    );
  }

  function renderGroups() {
    var groups = allGroups();
    if (!groups.length) return '';
    var html = '<div class="arena-sec"><p class="arena-h">Группы с набором</p>';
    var i;
    for (i = 0; i < groups.length; i++) {
      var g = groups[i];
      var right =
        g.spots_left > 0 ? g.spots_left + ' места' : 'набор открыт';
      html +=
        '<button type="button" class="arena-fake-row" data-action="group" data-trainer="' +
        esc(g.trainer_id) +
        '" data-group="' +
        esc(g.id) +
        '"><b style="font-weight:640;font-size:14px">' +
        esc(g.name || 'Группа') +
        '</b><span>' +
        esc(right) +
        '</span></button>';
    }
    html += '</div>';
    return html;
  }

  /** «Адрес и часы»: одинаковые строки, длинные часы не вылезают — по дням списком. */
  function renderInfo() {
    var card = state.card;
    var contacts = M.practiceContacts(card);
    var rows = '';
    var route = M.quickActions(card).filter(function (a) { return a.id === 'route'; })[0];
    if (card.address) {
      rows +=
        '<a class="arena-info"' + (route ? ' href="' + esc(route.href) + '" data-action="external" data-href="' + esc(route.href) + '"' : '') + '>' +
        '<small>Адрес</small><b>' + esc(card.address) + '</b>' + (card.district ? '<span>' + esc(card.district) + '</span>' : '') +
        '</a>';
    }
    var mass = M.massAccessView(card);
    var week = mass.enabled ? null : M.weekHours(card.opening_hours, new Date());
    if (week) {
      var hoursLabel =
        typeof M.closedSeasonHoursLabel === 'function'
          ? M.closedSeasonHoursLabel(card)
          : 'Часы работы';
      var showLiveStatus = card.in_season !== false;
      var status = showLiveStatus && week.status ? '<em class="arena-info__open">' + esc(week.status) + '</em>' : '';
      if (week.uniform) {
        rows += '<div class="arena-info"><small>' + esc(hoursLabel) + '</small><b>Ежедневно ' + esc(week.rows[0].value) + '</b>' + status + '</div>';
      } else {
        rows +=
          '<div class="arena-info"><small>' + esc(hoursLabel) + '</small>' + status +
          '<ul class="arena-week">' +
          week.rows.map(function (r) {
            return '<li class="' + (r.today ? 'is-today' : '') + (r.closed ? ' is-closed' : '') + '"><span>' + esc(r.label) + '</span><span>' + esc(r.value) + '</span></li>';
          }).join('') +
          '</ul></div>';
      }
    } else if (card.season_start_month === 1 && card.season_end_month === 12) {
      rows += '<div class="arena-info"><small>Сезон</small><b>Круглый год</b></div>';
    }
    var phones = M.phoneNumbers(card.phone);
    if (phones.length) {
      rows +=
        '<div class="arena-info arena-info--phones">' +
        '<small>Телефон</small>' +
        '<div class="arena-info__phone-row">' +
        renderPhoneLinks(phones) +
        '</div></div>';
    }
    if (contacts.website) {
      rows +=
        '<a class="arena-info" href="' + esc(contacts.website.href) + '" data-action="external" data-href="' + esc(contacts.website.href) + '">' +
        '<small>Сайт</small><b>' + esc(contacts.website.href.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')) + '</b></a>';
    }
    contacts.socials.forEach(function (x) {
      rows +=
        '<a class="arena-info" href="' + esc(x.href) + '" data-action="external" data-href="' + esc(x.href) + '">' +
        '<small>' + esc(x.label) + '</small><b>' + esc(x.href.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')) + '</b></a>';
    });
    var offer = typeof M.centerOfferView === 'function' ? M.centerOfferView(card) : { enabled: false };
    var lead = contacts.shortDescription && !mass.enabled && !offer.enabled ? contacts.shortDescription : null;
    if (!rows && !lead) return '';
    return (
      '<div class="arena-sec"><p class="arena-h">Адрес и контакты</p>' +
      (lead ? '<p class="arena-sub">' + esc(lead) + '</p>' : '') +
      '<div class="arena-infos">' + rows + '</div></div>'
    );
  }

  function renderFreshness() {
    // TASK-243: ни свежести, ни проверки, ни оговорок — только «Сообщить об ошибке».
    var html = '<div class="arena-sec"><div class="arena-fresh">';
    html +=
      '<span><button type="button" class="linkish" data-action="report">Сообщить об ошибке</button></span>';
    html += '</div></div>';
    return html;
  }

  /* ── Карточка катка v2 (arena_visit_info.visit_view → card.visit) ──────────
     Порядок блоков тот же, что на сайте: cover, ice, facts, services, trainers, partners, more.
     Блок без данных не рисуется. */
  var VISIT_ICONS = {
    hanger: '<path d="M10 7a2 2 0 1 1 3 1.7c-.7.4-1 .9-1 1.6v.7"/><path d="M3 18l9-6 9 6z"/>',
    lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    cup: '<path d="M4 9h12v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z"/><path d="M16 10h2a2 2 0 0 1 0 4h-2"/><path d="M8 3v3M12 3v3"/>',
    parking: '<circle cx="12" cy="12" r="9"/><path d="M10 16V8h3a2.5 2.5 0 0 1 0 5h-3"/>',
    thermo: '<path d="M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0z"/><path d="M12 9v6"/>',
    card: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 10h18M7 15h3"/>',
    child: '<circle cx="12" cy="5.5" r="2.5"/><path d="M7 11h10M12 9v6M9 21l3-6 3 6"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    ruler: '<path d="M4 15 15 4l5 5L9 20z"/><path d="M8 11l2 2M11 8l2 2M14 5l2 2"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    person: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    skate: '<path d="M6 4v9h8l4 2v2H5"/><path d="M4 20h16"/>',
    sharpen: '<circle cx="10" cy="8.5" r="5"/><circle cx="10" cy="8.5" r="1.2"/><path d="M3 18.5h16a2 2 0 0 0 2-2"/><path d="M8 18.5v-2.5h6l1.5 2.5"/>',
    shield: '<path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/>',
    helmet: '<path d="M4 16a8 8 0 0 1 16 0v1H4z"/><path d="M12 8v4M4 17h16"/>',
    ticket: '<path d="M4 7h16v3a2 2 0 0 0 0 4v3H4v-3a2 2 0 0 0 0-4z"/><path d="M14 8v8"/>',
    pass: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 10h18M7 15h4"/>',
    rink: '<rect x="3" y="6" width="18" height="12" rx="6"/><path d="M12 6v12"/><circle cx="12" cy="12" r="2"/>',
    phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
    down: '<path d="M6 9l6 6 6-6"/>'
  };
  var PENGUIN =
    '<svg class="av-penguin" viewBox="0 0 64 64" role="img" aria-label="Опора «пингвин»">' +
    '<path d="M20 20c0-12 24-12 24 0" fill="none" stroke="#0d1b26" stroke-width="4" stroke-linecap="round"/>' +
    '<ellipse cx="32" cy="38" rx="15" ry="20" fill="#0d1b26"/><ellipse cx="32" cy="43" rx="9.5" ry="13" fill="#fff"/>' +
    '<path d="M19 31h26v4H19z" fill="#45B9BB"/><circle cx="27" cy="25" r="3" fill="#fff"/><circle cx="37" cy="25" r="3" fill="#fff"/>' +
    '<circle cx="27.5" cy="25.5" r="1.4" fill="#0d1b26"/><circle cx="36.5" cy="25.5" r="1.4" fill="#0d1b26"/>' +
    '<path d="M29.5 28.5h5l-2.5 3z" fill="#f2a33a"/><ellipse cx="25" cy="58" rx="6" ry="2.6" fill="#f2a33a"/>' +
    '<ellipse cx="39" cy="58" rx="6" ry="2.6" fill="#f2a33a"/></svg>';

  function visitIcon(name) {
    return '<svg class="av-ic__svg" viewBox="0 0 24 24" aria-hidden="true">' + (VISIT_ICONS[name] || VISIT_ICONS.info) + '</svg>';
  }

  function visit() {
    var v = state.card && state.card.visit;
    return v && typeof v === 'object' ? v : null;
  }

  function moneyMinor(minor, currency) {
    var f = M.formatMinor ? M.formatMinor(minor, currency) : null;
    if (f) return f.withCurrency;
    var major = Number(minor) / 100;
    return (Number.isInteger(major) ? String(major) : major.toFixed(2)) + ' ' + currency;
  }

  /** Минимум недели по взрослому, детскому и прокату — как на сайте (place_visit_blocks.price_floors). */
  function priceFloors() {
    var seen = { adult: {}, child: {}, rental: {} };
    var currency = 'BYN';
    ((state.sessions && state.sessions.days) || []).forEach(function (d) {
      (d.sessions || []).forEach(function (s) {
        if (s.currency_code) currency = s.currency_code;
        var adult = s.price_adult_minor != null ? s.price_adult_minor : s.price_minor;
        if (adult != null) seen.adult[adult] = 1;
        if (s.price_child_minor != null) seen.child[s.price_child_minor] = 1;
        if (s.price_rental_minor != null) seen.rental[s.price_rental_minor] = 1;
      });
    });
    var out = { currency: currency };
    Object.keys(seen).forEach(function (k) {
      var vals = Object.keys(seen[k]).map(Number);
      if (vals.length) out[k] = { minor: Math.min.apply(null, vals), varies: vals.length > 1 };
    });
    return out;
  }

  function renderVisitPrices() {
    var v = visit() || {};
    var f = priceFloors();
    function money(k) {
      return (f[k].varies ? 'от ' : '') + moneyMinor(f[k].minor, f.currency);
    }
    var cells = [];
    if (f.adult) cells.push(['Взрослый', money('adult'), '']);
    if (f.child) cells.push(['Детский', money('child'), v.child_age_max ? 'до ' + v.child_age_max + ' лет' : '']);
    if (f.rental) cells.push(['Прокат', money('rental'), v.sizes ? 'размеры ' + v.sizes : 'коньки']);
    if (!cells.length) return '';
    var html = '<div class="av-prices av-prices--' + cells.length + '">' + cells.map(function (c) {
      return '<div class="av-price"><span class="av-price__k">' + esc(c[0]) + '</span><b class="av-price__v">' +
        esc(c[1]) + '</b>' + (c[2] ? '<span class="av-price__s">' + esc(c[2]) + '</span>' : '') + '</div>';
    }).join('') + '</div>';
    if (f.adult && f.rental) {
      html += '<p class="av-sum">Взрослому с прокатом — ' + (f.adult.varies || f.rental.varies ? 'от ' : '') +
        esc(moneyMinor(f.adult.minor + f.rental.minor, f.currency)) + '.</p>';
    }
    return html;
  }

  function renderBuyLine() {
    var v = visit();
    if (!v || !v.tickets) return '';
    var t = v.tickets;
    var detail = t.detail || '';
    var note = String(t.note || '').replace(/\.$/, '');
    if (t.mode === 'box_office') {
      var tail = [detail, note].filter(Boolean).join(' · ');
      return '<p class="av-line av-line--desk">' + visitIcon('ticket') + '<span><b>Билеты только в кассе</b>' +
        (tail ? ' · ' + esc(tail) : '') + '</span></p>';
    }
    if (t.mode === 'same_day') {
      return '<p class="av-line av-line--soft">' + visitIcon('clock') +
        '<span><b>Онлайн продают только в день сеанса.</b> Заранее — в кассе.' + (detail ? ' ' + esc(detail) + '.' : '') + '</span></p>';
    }
    var bits = [detail, note].filter(Boolean).join(' · ');
    return bits ? '<p class="av-line av-line--plain">' + visitIcon('ticket') + '<span>' + esc(bits) + '</span></p>' : '';
  }

  function renderFacts() {
    var v = visit();
    var facts = (v && v.facts) || [];
    if (!facts.length) return '';
    var food = foodPartner();
    var visible = v.facts_visible || 4;
    function cell(f) {
      var badge = f.key === 'cafe' && food ? '<span class="av-fact__badge">' + esc(food.offer) + '</span>' : '';
      var tag = badge ? 'a' : 'div';
      var href = badge ? ' href="#arenaPartners"' : '';
      return '<' + tag + ' class="av-fact"' + href + '><span class="av-ic av-ic--sm">' + visitIcon(f.icon) + '</span>' +
        '<b class="av-fact__t">' + esc(f.title) + badge + '</b>' +
        (f.note ? '<span class="av-fact__n">' + esc(f.note) + '</span>' : '') + '</' + tag + '>';
    }
    var html = '<div class="arena-sec"><p class="arena-h">Что важно знать</p><div class="av-facts">' +
      facts.slice(0, visible).map(cell).join('') + '</div>';
    var rest = facts.slice(visible);
    if (rest.length) {
      html += '<details class="av-facts-more"><summary>Ещё ' + rest.length + '</summary><div class="av-facts">' +
        rest.map(cell).join('') + '</div></details>';
    }
    return html + '</div>';
  }

  function renderServices() {
    var v = visit();
    var sv = (v && v.services) || {};
    var rows = sv.rows || [];
    if (!rows.length) return '';
    var priced = rows.some(function (r) { return !!r.price; });
    var html = '<div class="arena-sec"><div class="arena-h-row"><p class="arena-h">Прокат и услуги</p>' +
      (priced ? '<span class="av-aside">в кассе</span>' : '') + '</div><div class="av-list">';
    var fl = priceFloors();
    rows.forEach(function (r) {
      if (r.kind === 'rental' && !r.price && fl.rental) {
        r = Object.assign({}, r, {
          price: (fl.rental.varies ? 'от ' : '') + moneyMinor(fl.rental.minor, fl.currency),
          note: r.note === 'цена в кассе' ? '' : r.note
        });
      }
      var media = r.icon === 'penguin'
        ? '<span class="av-pic">' + PENGUIN + '</span>'
        : '<span class="av-ic">' + visitIcon(r.icon) + '</span>';
      html += '<div class="av-row">' + media + '<span class="av-row__b"><b>' + esc(r.title) + '</b>' +
        (r.note ? '<span>' + esc(r.note) + '</span>' : '') + '</span>' +
        (r.price ? '<span class="av-row__p">' + esc(r.price) + '</span>' : '') + '</div>';
    });
    html += '</div>';
    (sv.notes || []).forEach(function (n) {
      html += '<p class="av-line av-line--soft">' + visitIcon('info') + '<span>' + esc(n) + '</span></p>';
    });
    return html + '</div>';
  }

  function schoolTable(school) {
    var rows = school.rows || [];
    var hasChild = rows.some(function (r) { return !!r.child; });
    var hasAdult = rows.some(function (r) { return !!r.adult; });
    var html = '<table class="av-table"><thead><tr><th></th>' + (hasChild ? '<th>Детям</th>' : '') +
      (hasAdult ? '<th>Взрослым</th>' : '') + '</tr></thead><tbody>' + rows.map(function (r) {
        return '<tr><td>' + esc(r.label) + '</td>' + (hasChild ? '<td>' + esc(r.child || '—') + '</td>' : '') +
          (hasAdult ? '<td>' + esc(r.adult || '—') + '</td>' : '') + '</tr>';
      }).join('') + '</tbody></table>';
    if (school.phone) {
      var digits = String(school.phone).replace(/[^\d+]/g, '');
      html += '<a class="av-call ga-press" href="tel:' + esc(digits) + '">' + visitIcon('phone') + 'Записаться: ' +
        esc(school.phone) + (school.contact ? ' · ' + esc(school.contact) : '') + '</a>';
    }
    return html;
  }

  function moreRow(key, icon, title, note, inner, solo) {
    return '<details class="av-more' + (solo ? ' av-more--solo' : '') + '"><summary><span class="av-ic">' + visitIcon(icon) +
      '</span><span class="av-row__b"><b>' + esc(title) + '</b>' + (note ? '<span>' + esc(note) + '</span>' : '') +
      '</span><span class="av-more__chev">' + visitIcon('down') + '</span></summary><div class="av-more__body">' + inner +
      '</div></details>';
  }

  function renderSchoolInTrainers() {
    var v = visit();
    var school = v && v.school;
    if (!school || !school.rows || !school.rows.length) return '';
    return '<div class="arena-sec av-sec--tight">' +
      moreRow('school', 'child', 'Школа катка', school.age_from ? 'с ' + school.age_from + ' лет' : '', schoolTable(school), true) +
      '</div>';
  }

  function renderMore() {
    var v = visit();
    var more = (v && v.more) || [];
    if (!more.length) return '';
    var phone = state.card && state.card.contacts && state.card.contacts.phone;
    var html = more.map(function (m) {
      var d = m.detail || {};
      var inner = '';
      if (m.key === 'school') inner = schoolTable(d);
      else if (m.key === 'passes') {
        var cols = d.columns || [];
        inner = '<table class="av-table"><thead><tr><th></th>' + cols.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') +
          '</tr></thead><tbody>' + (d.rows || []).map(function (r) {
            return '<tr><td>' + esc(r.label) + '</td>' + (r.values || []).slice(0, cols.length).map(function (x) {
              return '<td>' + esc(x || '—') + '</td>';
            }).join('') + '</tr>';
          }).join('') + '</tbody></table>';
      } else {
        var tel = d.phone || phone || '';
        inner = '<p class="av-lead">Весь каток на вашу компанию: день рождения, хоккей с друзьями, корпоратив.</p>' +
          '<div class="av-rink">' + (d.rows || []).map(function (r) {
            return '<div><span>' + esc(r.label) + (r.minutes ? ', ' + r.minutes + ' минут' : '') + '</span><b>' + esc(r.price) + '</b></div>';
          }).join('') + '</div>' +
          (tel ? '<a class="av-call ga-press" href="tel:' + esc(String(tel).split(';')[0].replace(/[^\d+]/g, '')) + '">' +
            visitIcon('phone') + 'Позвонить и забронировать</a>' : '');
      }
      return moreRow(m.key, m.icon, m.title, m.note, inner, false);
    }).join('');
    return '<div class="arena-sec"><p class="arena-h">Ещё на катке</p><div class="av-list">' + html + '</div></div>';
  }

  /** Колокольчик «следить за катком» — на обложке рядом с Маршрутом и Телефоном. */
  function heroBellHtml() {
    if (!initData() || !skatingCard() || seasonRemindActive()) return '';
    var on = state.iceWatchKinds && state.iceWatchKinds.sessions;
    var hint = on
      ? copyLine('schedule.bell_on', 'Напоминание включено')
      : copyLine('schedule.bell_hint', 'Сообщить о\u00a0новом расписании');
    return '<button type="button" class="ga-onphoto ga-onphoto--icon ga-press' + (on ? ' is-on' : '') +
      '" data-action="ice-watch" data-watch-kind="sessions" aria-pressed="' + (on ? 'true' : 'false') +
      '" aria-label="' + esc(hint) + '" title="' + esc(hint) + '">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 20a2 2 0 0 0 4 0"/>' +
      (on ? '<path d="M4 4l16 16"/>' : '') + '</svg></button>';
  }

  function paint() {
    if (!root || !state.card) return;
    var title = document.getElementById('headerTitle');
    // Имя места — на обложке; в шапке — что это за место, без дубля.
    if (title) title.textContent = capitalize(state.card.venue_noun) || 'Площадка';
    try {
      root.innerHTML =
        renderHero() +
        renderIceSection() +
        renderOhmSection() +
        // Карточка v2 — порядок PLACE_BLOCKS, как на сайте: на месте → тренеры → партнёры → ещё.
        (visit() && String(state.card.venue_type || '') !== 'shop' ? renderFacts() : renderAmenities()) +
        renderServices() +
        renderMassAccess() +
        renderTrainers() +
        (state.trainers && state.trainers.items && state.trainers.items.length ? renderSchoolInTrainers() : '') +
        renderPartners() +
        renderMore() +
        renderCenterOffer() +
        renderGroups() +
        renderInfo() +
        renderFreshness() +
        renderShareBar();
      bindHeroFallbacks(root);
      bindAvatarFallbacks(root);
    } catch (err) {
      if (global.console && global.console.error) {
        global.console.error('arena-card paint failed', err);
      }
      root.innerHTML =
        '<div class="arena-state">Не удалось отрисовать карточку. Закройте и откройте снова или обновите мини-приложение.</div>';
    }
  }

  function capitalize(text) {
    text = String(text || '');
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
  }

  function paintRowsOnly() {
    var el = document.getElementById('arenaRows');
    if (el) el.innerHTML = renderShowtimes();
    var ohmEl = document.getElementById('arenaOhmRows');
    if (ohmEl) ohmEl.innerHTML = renderOhmShowtimes();
    paintShareBar();
    var tabs = document.getElementById('arenaDayTabs');
    if (tabs) {
      [].forEach.call(tabs.querySelectorAll('[data-day]'), function (b) {
        b.setAttribute('aria-pressed', b.getAttribute('data-day') === state.day ? 'true' : 'false');
      });
    }
    var ohmTabs = document.getElementById('arenaOhmDayTabs');
    if (ohmTabs) {
      [].forEach.call(ohmTabs.querySelectorAll('[data-ohm-day]'), function (b) {
        b.setAttribute(
          'aria-pressed',
          b.getAttribute('data-ohm-day') === state.ohmDay ? 'true' : 'false'
        );
      });
    }
  }

  var barTick = 0;

  function paintTrainersOnly() {
    var box = root && root.querySelector('.arena-coaches');
    if (!box) return;
    var holder = document.createElement('div');
    holder.innerHTML = renderTrainers();
    var next = holder.firstElementChild;
    if (!next) return;
    // Лента тренеров могла быть прокручена — не сбрасываем.
    var row = box.querySelector('.arena-coaches__row');
    var left = row ? row.scrollLeft : 0;
    box.replaceWith(next);
    bindAvatarFallbacks(next);
    var nextRow = next.querySelector('.arena-coaches__row');
    if (nextRow) nextRow.scrollLeft = left;
  }

  function paintShareBar() {
    var bar = document.getElementById('arenaShareBar');
    if (!bar) return;
    var label = document.getElementById('arenaBarInvite');
    var when = document.getElementById('arenaBarWhen');
    var next = shareInviteCtaLabel();
    var changed = label && label.textContent !== next;
    if (label) label.textContent = next;
    if (when) when.textContent = shareBarWhen();
    var company = bar.querySelector('[data-action="ice-company"]');
    if (company) company.setAttribute('data-session', resolvedShareSessionId() || '');
    if (!changed) return;
    // Два одинаковых кадра: смена класса перезапускает анимацию на каждом выборе.
    barTick += 1;
    var odd = barTick % 2 === 1;
    [label, when].forEach(function (n) {
      if (!n) return;
      n.classList.remove('ga-pop-a', 'ga-pop-b');
      n.classList.add(odd ? 'ga-pop-a' : 'ga-pop-b');
    });
    var pri = bar.querySelector('[data-action="share-invite"]');
    if (pri) {
      pri.classList.remove('ga-glow-a', 'ga-glow-b');
      pri.classList.add(odd ? 'ga-glow-a' : 'ga-glow-b');
    }
  }

  var REPORT_FIELDS = [
    { id: 'schedule', label: 'Расписание / время сеанса' },
    { id: 'price_adult', label: 'Цена взрослый' },
    { id: 'price_child', label: 'Цена детский' },
    { id: 'price_rental', label: 'Прокат' },
    { id: 'phone', label: 'Телефон' },
    { id: 'hours', label: 'Часы работы' },
    { id: 'other', label: 'Другое' },
  ];

  function openModal() {
    var modal = document.getElementById('arenaModal');
    var title = document.getElementById('arenaModalTitle');
    var lead = document.getElementById('arenaModalLead');
    var field = document.getElementById('arenaModalField');
    var value = document.getElementById('arenaModalValue');
    if (!modal) return;
    modal.dataset.kind = 'report';
    title.textContent = 'Сообщить об ошибке';
    lead.textContent = 'Укажите поле и верное значение — не письмо в поддержку.';
    field.innerHTML = REPORT_FIELDS.map(function (f) {
      return '<option value="' + f.id + '">' + esc(f.label) + '</option>';
    }).join('');
    value.placeholder = 'Например: 10:30 или +375 29 123-45-67';
    value.value = '';
    modal.hidden = false;
    requestAnimationFrame(function () {
      modal.classList.add('is-open');
    });
    var closeBtn = document.getElementById('arenaModalClose');
    if (closeBtn) closeBtn.focus();
  }

  function closeModal() {
    var modal = document.getElementById('arenaModal');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.hidden = true;
  }

  function storeLocalReport(payload) {
    var key = 'tcb_arena_reports_v1';
    var list = [];
    try {
      list = JSON.parse(global.localStorage.getItem(key) || '[]');
    } catch (e) {
      list = [];
    }
    if (!Array.isArray(list)) list = [];
    list.push(payload);
    try {
      global.localStorage.setItem(key, JSON.stringify(list.slice(-50)));
    } catch (e2) { /* quota */ }
  }

  function submitModal(ev) {
    ev.preventDefault();
    var modal = document.getElementById('arenaModal');
    var field = document.getElementById('arenaModalField');
    var value = document.getElementById('arenaModalValue');
    var suggested = value && String(value.value || '').trim();
    var tg = global.Telegram && global.Telegram.WebApp;
    if (!suggested) {
      if (tg && tg.showAlert) tg.showAlert('Напишите, как должно быть правильно.');
      else if (value) value.focus();
      return;
    }
    var kind = modal && modal.dataset.kind;
    var payload = {
      kind: kind || 'report',
      arena_id: state.card && state.card.id,
      arena_slug: state.card && state.card.slug,
      field: field && field.value,
      suggested: suggested,
      at: new Date().toISOString(),
    };
    var msg =
      '[arena-' +
      payload.kind +
      '] arena=' +
      (payload.arena_id || payload.arena_slug) +
      ' field=' +
      payload.field +
      ' value=' +
      suggested;
    storeLocalReport(payload);
    var cred = initData();
    var submitBtn = document.getElementById('arenaModalSubmit');
    if (submitBtn) submitBtn.disabled = true;

    function done(ok, detail) {
      if (submitBtn) submitBtn.disabled = false;
      closeModal();
      if (tg && tg.showAlert) {
        tg.showAlert(
          ok
            ? 'Спасибо, передали администратору.'
            : detail || 'Не удалось отправить. Попробуйте позже или напишите в поддержку из бота.'
        );
      }
    }

    if (!cred) {
      done(false, 'Откройте карточку из Telegram — тогда сообщение уйдёт команде. Сейчас сохранили только на устройстве.');
      return;
    }
    fetch('/api/webapp/support', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': cred,
      },
      body: JSON.stringify({ message: msg, role: 'client' }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      })
      .then(function (body) {
        if (body && body.ok) done(true);
        else throw new Error('not ok');
      })
      .catch(function () {
        done(false);
      });
  }

  function onRootClick(ev) {
    var toPartners = ev.target.closest('a[href="#arenaPartners"]');
    if (toPartners) {
      ev.preventDefault();
      var block = document.getElementById('arenaPartners');
      if (block) block.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    var partnerBtn = ev.target.closest('[data-partner]');
    if (partnerBtn && global.GlidePartners) {
      var slug = partnerBtn.getAttribute('data-partner');
      var hit = partnersList().filter(function (p) { return p.slug === slug; })[0];
      if (hit) {
        global.GlidePartners.open(hit, {
          surface: 'miniapp_arena',
          arenaId: state.card.id,
          cityId: state.card.city_id,
          placeName: state.card.name || '',
        });
      }
      return;
    }
    var dayBtn = ev.target.closest('[data-day]');
    if (dayBtn && dayBtn.closest('#arenaDayTabs')) {
      state.day = dayBtn.getAttribute('data-day');
      paintRowsOnly();
      return;
    }
    var ohmDayBtn = ev.target.closest('[data-ohm-day]');
    if (ohmDayBtn && ohmDayBtn.closest('#arenaOhmDayTabs')) {
      state.ohmDay = ohmDayBtn.getAttribute('data-ohm-day');
      paintRowsOnly();
      return;
    }
    var jump = ev.target.closest('[data-day-jump]');
    if (jump) {
      state.day = jump.getAttribute('data-day-jump');
      paintRowsOnly();
      return;
    }
    var ohmJump = ev.target.closest('[data-ohm-day-jump]');
    if (ohmJump) {
      state.ohmDay = ohmJump.getAttribute('data-ohm-day-jump');
      paintRowsOnly();
      return;
    }
    var t = ev.target.closest('[data-action]');
    if (!t) return;
    var action = t.getAttribute('data-action');
    if (action === 'trainer') {
      /*
       * Тренер с арены ведёт СТРОГО на его карточку — не на выбор времени.
       *
       * Раньше при can_book прыгали сразу на слоты (`action=book`), и человек
       * попадал на список голого времени: чьи это слоты, что за тренер, где они
       * проходят — по экрану непонятно. А если слотов на этой арене нет, экран
       * оказывался тупиком. Карточка — единственное место, где есть весь
       * контекст: цена, услуги, арены, слоты и выход в заявку. С неё же «Назад»
       * честно возвращает на арену.
       */
      goBooking(t.getAttribute('data-trainer'));
      return;
    }
    if (action === 'group') {
      // Группа ведёт на карточку тренера и раскрывает там именно этот набор.
      // Прыжок на общий список времени терял выбранную группу.
      goBooking(t.getAttribute('data-trainer'), { groupId: t.getAttribute('data-group') });
      return;
    }
    if (action === 'copy-phone') {
      ev.preventDefault();
      copyArenaPhone(t.getAttribute('data-copy-phone'));
      return;
    }
    if (action === 'call') {
      /* В Telegram WebView tap по tel: на плитке часто молчит — открываем набор через JS. href остаётся для long-press. */
      ev.preventDefault();
      var callPhone = (t.getAttribute('data-call-phone') || '').trim();
      if (!callPhone) {
        var callHref = (t.getAttribute('href') || '').trim();
        if (callHref.toLowerCase().indexOf('tel:') === 0) callPhone = callHref.slice(4);
      }
      if (!dialPhone(callPhone)) {
        var tg = global.Telegram && global.Telegram.WebApp;
        if (tg && typeof tg.showAlert === 'function') {
          tg.showAlert('Не удалось открыть набор номера. Удержите номер, чтобы скопировать.');
        }
      }
      return;
    }
    if (action === 'external') {
      // Касса, карта, сайт: из Mini App — через Telegram, иначе ссылка откроется внутри webview.
      ev.preventDefault();
      openExternal(t.getAttribute('data-href'));
      return;
    }
    if (action === 'back') {
      if (global.history.length > 1) global.history.back();
      else shellNav('ice');
      return;
    }
    if (action === 'pick-session') {
      var sid = t.getAttribute('data-session-id');
      if (!sid) return;
      state.sharePickSessionId = sid;
      var pickDay = t.getAttribute('data-local-date');
      if (pickDay) state.day = pickDay;
      if (pickDay) paint();
      else {
        paintRowsOnly();
        paintTrainersOnly();
      }
      // Новый выбор приподнимается один раз (ga-lift); при других перерисовках — уже стоит наверху.
      var picked = document.querySelector('.arena-time--picked, .arena-slot--picked .arena-slot-time');
      if (picked) picked.classList.add('ga-lift');
      if (global.GlideTouch) global.GlideTouch.haptic('select');
      else {
        try {
          var tgw = global.Telegram && global.Telegram.WebApp;
          if (tgw && tgw.HapticFeedback) tgw.HapticFeedback.selectionChanged();
        } catch (eHap) { /* без вибрации */ }
      }
      return;
    }
    if (action === 'share' || action === 'share-invite' || action === 'ice-company') {
      openShare(action === 'share-invite' ? 'invite' : action === 'ice-company' ? 'company' : 'schedule');
      return;
    }
    if (action === 'report') openModal();
    if (action === 'retry-trainers') {
      reloadTrainers();
      return;
    }
    if (action === 'retry-sessions') {
      reloadSessions();
      return;
    }
    if (action === 'ice-watch') {
      toggleIceWatch(t.getAttribute('data-watch-kind') || 'sessions');
      return;
    }
  }

  function arenaApiBase() {
    if (!state.ref) return '';
    return '/api/public/arenas/' + encodeURIComponent(state.ref);
  }

  function applyScheduleFocus() {
    var fs = getFocusState();
    if (fs.kind === 'found') {
      if (fs.day) state.focus.day = fs.day;
      state.sharePickSessionId = String(fs.focusSessionId);
    } else if (state.focus && state.focus.sessionId && fs.kind === 'gone') {
      state.sharePickSessionId = null;
    }
    if (state.focus && state.focus.sessionId && state.sessions) {
      if (!state.focus.day) {
        var found =
          M.dayForSession(state.sessions.days, state.focus.sessionId) ||
          M.dayForSession(state.sessions.ohm_days, state.focus.sessionId);
        if (found) state.focus.day = found;
      }
      var ohmDay = M.dayForSession(ohmScheduleDays(), state.focus.sessionId);
      if (ohmDay) {
        state.ohmDay = ohmDay;
        if (sessionExistsInSchedule(state.focus.sessionId)) {
          state.sharePickSessionId = String(state.focus.sessionId);
        }
      }
    }
  }

  function reloadSessions() {
    var base = arenaApiBase();
    if (!base || !state.card) return;
    state.sessionsError = false;
    var today = todayIso();
    var to = addDaysIso(today, 13);
    fetchJson(base + '/sessions?from=' + encodeURIComponent(today) + '&to=' + encodeURIComponent(to))
      .then(function (data) {
        state.sessions = data || { days: [] };
        state.sessionsError = false;
        applyScheduleFocus();
        paint();
      })
      .catch(function () {
        state.sessionsError = true;
        paint();
      });
  }

  function reloadTrainers() {
    var base = arenaApiBase();
    if (!base || !state.card) return;
    state.trainersError = false;
    fetchJson(base + '/trainers')
      .then(function (data) {
        state.trainers = data || { items: [], groups: [] };
        state.trainersError = false;
        paint();
      })
      .catch(function () {
        state.trainersError = true;
        state.trainers = { items: [], groups: [] };
        paint();
      });
  }

  function fetchJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      if (r.status === 404) return null;
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    });
  }

  function showError(text) {
    if (!root) return;
    root.innerHTML = '<div class="arena-state">' + esc(text) + '</div>';
    state.card = null;
  }

  function load() {
    var tg = global.Telegram && global.Telegram.WebApp;
    var start =
      (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) ||
      M.startParamFromLocation(global.location);
    state.ref = M.parseArenaRef(global.location.search || '', start);
    state.focus = M.parseScheduleFocus(global.location.search || '');
    if (state.focus && !state.focus.sessionId) {
      var fromStart = M.sessionIdFromStartParam(start);
      if (fromStart) state.focus.sessionId = fromStart;
    }
    if (!state.ref) {
      showError('Не указана арена. Откройте карточку по ссылке из каталога или бота.');
      return;
    }
    applyPrefetchHero(state.ref);
    var base = arenaApiBase();
    state.sessionsError = false;
    state.trainersError = false;
    fetchJson(base)
      .then(function (card) {
        if (!card) {
          showError('Арена не найдена.');
          return;
        }
        state.card = card;
        state.trainers = { items: [], groups: [] };
        syncIceWatches().then(function () {
          paint();
        });
        reloadSessions();
        reloadTrainers();
        if (global.ClientShell && global.ClientShell.reportCatalogPresence) {
          global.ClientShell.reportCatalogPresence('miniapp_arena', start, { arena_id: Number(state.ref) });
        }
      })
      .catch(function () {
        showError('Не удалось загрузить карточку. Попробуйте ещё раз.');
      });
  }

  function bindChrome() {
    var home = document.getElementById('btnHome');
    if (home) {
      home.addEventListener('click', function () {
        shellNav('client-home');
      });
    }
    var back = document.getElementById('btnBack');
    if (back) {
      back.addEventListener('click', function () {
        if (global.history.length > 1) global.history.back();
        else {
          shellNav('ice');
        }
      });
    }
    if (root) root.addEventListener('click', onRootClick);
    var form = document.getElementById('arenaModalForm');
    if (form) form.addEventListener('submit', submitModal);
    var cancel = document.getElementById('arenaModalCancel');
    if (cancel) cancel.addEventListener('click', closeModal);
    var backdrop = document.getElementById('arenaModalBackdrop');
    if (backdrop) backdrop.addEventListener('click', closeModal);
    var closeX = document.getElementById('arenaModalClose');
    if (closeX) closeX.addEventListener('click', closeModal);
    global.document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape') return;
      var modal = document.getElementById('arenaModal');
      if (modal && !modal.hidden) closeModal();
    });
    if (global.ClientShell && typeof global.ClientShell.setForcedTab === 'function') {
      global.ClientShell.setForcedTab('catalog');
    }
  }

  global.ArenaCardPage = {
    load: load,
    paint: paint,
    state: state,
  };

  /* Токены сайта темнеют по body.tg-dark, а тема Mini App ставит hub-is-dark на <html> — как на главной. */
  (function syncGlideDark() {
    var sync = function () {
      var b = document.body;
      var h = document.documentElement;
      if (!b || !b.classList || !h || !h.classList) return;
      b.classList.toggle('tg-dark', h.classList.contains('hub-is-dark'));
    };
    sync();
    if (global.MutationObserver && document.documentElement) {
      new global.MutationObserver(sync).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    }
  })();
  bindChrome();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})(typeof window !== 'undefined' ? window : this);
