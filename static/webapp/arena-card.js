/**
 * TASK-052 arena card page. Data: GET /api/public/arenas/{ref} + /sessions + /trainers.
 */
(function (global) {
  'use strict';

  var RuText = global.RuText;
  var M = global.ArenaCardModel;
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
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function todayIso(now) {
    now = now || new Date();
    var tz = state.card && state.card.timezone;
    if (tz) return M.ymdInTimeZone(now, tz);
    return M.ymd(now);
  }

  function addDaysIso(iso, n) {
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
    shellNav(
      M.buildBookingHref({
        trainerId: trainerId,
        arenaId: state.card && state.card.id,
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
    return (
      '<div class="' +
      cls +
      '">' +
      imgHtml +
      (hero.mode === 'photo' ? '<span class="arena-hero__shade"></span>' : '<span class="arena-hero__glare"></span>') +
      '<span class="arena-hero__txt">' +
      '<h1>' +
      esc(card.name || 'Арена') +
      '</h1>' +
      '<span class="arena-hero__meta">' +
      esc(M.heroMetaLine(card)) +
      '</span>' +
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

  function sharePickedId() {
    if (state.sharePickSessionId) return String(state.sharePickSessionId);
    if (state.focus && state.focus.sessionId) return String(state.focus.sessionId);
    return null;
  }

  function resolvedShareSessionId() {
    var slots = scheduleSlots();
    var picked = sharePickedId();
    if (picked && slots.some(function (s) { return String(s.id) === picked; })) return picked;
    return slots.length ? String(slots[0].id) : null;
  }

  function shareInviteCtaLabel() {
    var slots = scheduleSlots();
    var sid = resolvedShareSessionId();
    if (!sid || !slots.length) return 'Позвать с собой';
    for (var i = 0; i < slots.length; i++) {
      if (String(slots[i].id) === sid) return 'Позвать на ' + slots[i].label;
    }
    return 'Позвать с собой';
  }

  function renderShareBar() {
    if (!global.GlideShareSheet) return '';
    if (scheduleSlots().length) {
      return (
        '<div class="arena-share" id="arenaShareBar">' +
        '<button type="button" class="arena-btn arena-btn--pri" data-action="share-invite">' +
        esc(shareInviteCtaLabel()) +
        '</button>' +
        '<button type="button" class="arena-btn" data-action="share">Поделиться</button>' +
        '</div>'
      );
    }
    // Без сеансов «Поделиться» живёт в ряду быстрых действий.
    return '';
  }

  function fetchShareSlots() {
    var today = todayIso();
    var to = addDaysIso(today, 13);
    var base = '/api/public/arenas/' + encodeURIComponent(String(state.card.id));
    return fetchJson(base + '/sessions?from=' + encodeURIComponent(today) + '&to=' + encodeURIComponent(to)).then(
      function (data) {
        return M.shareSlots((data && data.days) || [], today, 8);
      }
    );
  }

  function openShare(invite) {
    if (!global.GlideShareSheet || !state.card) return;
    var isIce = skatingCard();
    var slots = isIce ? scheduleSlots() : [];
    var loadSlots =
      isIce && slots.length <= 1
        ? function () {
            return fetchShareSlots();
          }
        : null;
    global.GlideShareSheet.open({
      ref: state.card.id,
      slots: slots,
      sessionId: resolvedShareSessionId(),
      invite: !!invite,
      venueType: skatingCard() ? 'ice' : state.card.venue_type,
      context: 'arena_card',
      loadSlots: loadSlots,
    });
  }

  function renderAmenities() {
    if (String(state.card.venue_type || '') === 'shop') return renderShopServices();
    var chips = M.amenityChips(state.card.amenities);
    if (!chips.length) return '';
    return (
      '<div class="arena-sec"><div class="arena-amen">' +
      chips.map(function (c) { return '<span>' + esc(c) + '</span>'; }).join('') +
      '</div></div>'
    );
  }

  /** Окна массового катания и прокат — structured opening_hours, не простыня в описании. */
  function renderMassAccess() {
    var mass = M.massAccessView(state.card);
    if (!mass.enabled) return '';
    var html = '<div class="arena-sec"><p class="arena-h">Когда можно приехать</p>';
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
    html += '</div>';
    if (mass.rentalCatalog.length) {
      html += '<div class="arena-sec"><p class="arena-h">Прокат инвентаря</p><ul class="arena-price-list">';
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
      html += '<p class="arena-sub">Ориентиры проката ФК «Минск» — на кассе могут отличаться.</p></div>';
    }
    return html;
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
          '<button type="button" class="arena-qa" data-action="copy-phone" data-copy-phone="' +
          esc(a.phone || '') +
          '">' +
          icon(a.id) +
          '<span>' +
          esc(a.label) +
          '</span></button>'
        );
      }
      return (
        '<a class="arena-qa" href="' +
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
    // У катка с сеансами «Поделиться» стоит рядом с «Позвать с собой»; у остальных — здесь.
    if (!scheduleSlots().length && global.GlideShareSheet) {
      items.push('<button type="button" class="arena-qa" data-action="share">' + icon('share') + '<span>Поделиться</span></button>');
    }
    if (!items.length) return '';
    return '<div class="arena-qas arena-qas--' + items.length + '">' + items.join('') + '</div>';
  }

  function scheduleSlots() {
    return skatingCard() ? M.shareSlots((state.sessions && state.sessions.days) || [], todayIso(), 8) : [];
  }

  function strip() {
    return M.dayStrip((state.sessions && state.sessions.days) || [], todayIso(), new Date(), 7);
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
          '<span>' + esc(d.top) + '</span><b>' + esc(d.num) + '</b>' +
          '<i>' + (d.count ? esc(String(d.count)) : '—') + '</i>' +
          '</button>'
        );
      }).join('') +
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
      pickedId: sharePickedId(),
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
    view.groups.forEach(function (g) {
      html +=
        '<div class="arena-show">' +
        '<div class="arena-show__head"><b>' + esc(g.title) + '</b>' +
        (g.duration ? '<span>' + esc(g.duration) + '</span>' : '') + '</div>' +
        (g.prices.length
          ? '<div class="arena-show__prices">' + g.prices.map(function (p) {
              return '<span><small>' + esc(p.label) + '</small>' + esc(p.value) + '</span>';
            }).join('') + '</div>'
          : '') +
        '<div class="arena-times">' +
        g.times.map(function (t) {
          var cls = 'arena-time';
          if (t.picked) cls += ' arena-time--picked';
          else if (t.next) cls += ' arena-time--next';
          if (t.href) cls += ' arena-time--link';
          var tag = t.picked ? 'В приглашении' : t.next ? 'Ближайший' : t.capacity;
          var body = '<b>' + esc(t.time) + '</b>' + (tag ? '<small>' + esc(tag) + '</small>' : '');
          if (t.href) {
            return '<a class="' + cls + '" href="' + esc(t.href) + '" data-action="external" data-href="' + esc(t.href) + '">' + body + '</a>';
          }
          if (t.sessionId != null) {
            return (
              '<button type="button" class="' +
              cls +
              '" data-action="pick-session" data-session-id="' +
              esc(t.sessionId) +
              '" aria-pressed="' +
              (t.picked ? 'true' : 'false') +
              '">' +
              body +
              '</button>'
            );
          }
          return '<span class="' + cls + '">' + body + '</span>';
        }).join('') +
        '</div>' +
        (g.note ? '<p class="arena-show__note">' + esc(g.note) + '</p>' : '') +
        '</div>';
    });
    if (lessons.length) {
      html += '<p class="arena-h arena-h--sub">Занятия с тренером</p><div class="arena-rows">' + lessons.map(rowHtml).join('') + '</div>';
    }
    return html;
  }

  function renderIceSection() {
    /* Секция про массовое катание существует только для льда. На зале она
       обещала бы расписание сеансов, которых там не бывает в принципе —
       это не «данных пока нет», а неверный вопрос к площадке. */
    // has_skating — каток или уличный лёд (сервер: venue_types.has_public_skating).
    if (!skatingCard()) return '';
    var feed = M.iceFeedView({
      card: state.card,
      hasSessions: hasAnySessions(),
    });
    if (feed.mode === 'closed') {
      return (
        '<div class="arena-sec">' +
        '<p class="arena-h">Расписание</p>' +
        '<div class="arena-closed">' + esc(feed.banner) + '</div>' +
        '</div>'
      );
    }
    if (feed.mode === 'none') {
      return '';
    }
    if (feed.mode === 'pending') {
      return (
        '<div class="arena-sec">' +
        '<p class="arena-h">Расписание</p>' +
        '<div class="arena-empty">' +
        '<b>Расписание уточняется</b>' +
        '<p>Мы пока не получили расписание массового катания от этого катка. Не показываем то, за что не отвечаем — позвоните или загляните на сайт.</p>' +
        '</div>' +
        '</div>'
      );
    }
    var days = strip();
    if (!state.day) {
      // День из ленты — если он есть в полосе; иначе свой умный дефолт.
      var focusDay = state.focus && state.focus.day;
      var inStrip = focusDay && days.some(function (d) { return d.iso === focusDay; });
      state.day = inStrip ? focusDay : M.defaultScheduleDay(days);
    }
    var tickets = M.ticketCta(state.card);
    return (
      '<div class="arena-sec">' +
      '<div class="arena-h-row"><p class="arena-h">Расписание</p>' +
      (tickets
        ? '<a class="arena-cta arena-cta--link" href="' + esc(tickets.href) + '" data-action="external" data-href="' + esc(tickets.href) + '">Билеты онлайн</a>'
        : '') +
      '</div>' +
      renderDayStrip(days) +
      '<div id="arenaRows">' + renderShowtimes() + '</div>' +
      '</div>'
    );
  }

  function renderTrainers() {
    var items = (state.trainers && state.trainers.items) || [];
    if (!items.length) return '';
    var html =
      '<div class="arena-sec"><p class="arena-h">Тренеры на этой арене<span class="arena-new">НОВОЕ</span></p>';
    var i;
    for (i = 0; i < items.length; i++) {
      var t = items[i];
      var cta = M.trainerCta(t);
      var ava = photoUrl(t);
      html +=
        '<button type="button" class="arena-coach" data-action="trainer" data-trainer="' +
        esc(t.id) +
        '" data-can-book="' +
        (t.can_book ? '1' : '0') +
        '">' +
        (ava
          ? '<img class="arena-coach__ava" alt="" src="' + esc(ava) + '">'
          : '<i class="arena-coach__ava arena-coach__ava--mono" aria-hidden="true">' +
            esc(trainerInitial(t)) +
            '</i>') +
        '<span class="arena-coach__b"><b>' +
        esc(trainerName(t)) +
        '</b><span>' +
        esc(M.trainerSubtitle(t)) +
        '</span></span>' +
        '<span class="arena-cta arena-cta--' +
        cta.kind +
        '">' +
        esc(cta.label) +
        '</span>' +
        '</button>';
    }
    html +=
      '<p class="arena-sub">Тренер без онлайн-записи показывается честно — «Написать», а не мёртвая кнопка.</p></div>';
    return html;
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
      var status = week.status ? '<em class="arena-info__open">' + esc(week.status) + '</em>' : '';
      if (week.uniform) {
        rows += '<div class="arena-info"><small>Часы работы</small><b>Ежедневно ' + esc(week.rows[0].value) + '</b>' + status + '</div>';
      } else {
        rows +=
          '<div class="arena-info"><small>Часы работы</small>' + status +
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
    var lead = contacts.shortDescription && !mass.enabled ? contacts.shortDescription : null;
    if (!rows && !lead) return '';
    return (
      '<div class="arena-sec"><p class="arena-h">Адрес и контакты</p>' +
      (lead ? '<p class="arena-sub">' + esc(lead) + '</p>' : '') +
      '<div class="arena-infos">' + rows + '</div></div>'
    );
  }

  function renderFreshness() {
    var text = M.formatFreshness(state.card.freshness, new Date());
    var html = '<div class="arena-sec"><div class="arena-fresh">';
    if (text) html += '<span>' + esc(text) + '</span>';
    M.trustLines(state.card, new Date()).forEach(function (line) {
      html += '<span>' + esc(line) + '</span>';
    });
    html +=
      '<span><button type="button" class="linkish" data-action="report">Сообщить об ошибке</button> — конкретное поле, а не письмо в поддержку</span>';
    html += '</div></div>';
    return html;
  }

  function paint() {
    if (!root || !state.card) return;
    var title = document.getElementById('headerTitle');
    // Имя места — на обложке; в шапке — что это за место, без дубля.
    if (title) title.textContent = capitalize(state.card.venue_noun) || 'Площадка';
    root.innerHTML =
      renderHero() +
      renderShareBar() +
      renderQuickActions() +
      renderIceSection() +
      renderAmenities() +
      renderMassAccess() +
      renderTrainers() +
      renderGroups() +
      renderInfo() +
      renderFreshness();
    bindHeroFallbacks(root);
  }

  function capitalize(text) {
    text = String(text || '');
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
  }

  function paintRowsOnly() {
    var el = document.getElementById('arenaRows');
    if (el) el.innerHTML = renderShowtimes();
    paintShareBar();
    var tabs = document.getElementById('arenaDayTabs');
    if (!tabs) return;
    [].forEach.call(tabs.querySelectorAll('[data-day]'), function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-day') === state.day ? 'true' : 'false');
    });
  }

  function paintShareBar() {
    var bar = document.getElementById('arenaShareBar');
    if (!bar) return;
    var pri = bar.querySelector('[data-action="share-invite"]');
    if (pri) pri.textContent = shareInviteCtaLabel();
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
    var dayBtn = ev.target.closest('[data-day]');
    if (dayBtn && dayBtn.closest('#arenaDayTabs')) {
      state.day = dayBtn.getAttribute('data-day');
      paintRowsOnly();
      return;
    }
    var jump = ev.target.closest('[data-day-jump]');
    if (jump) {
      state.day = jump.getAttribute('data-day-jump');
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
    if (action === 'pick-session') {
      var sid = t.getAttribute('data-session-id');
      if (!sid) return;
      state.sharePickSessionId = sid;
      paintRowsOnly();
      return;
    }
    if (action === 'share' || action === 'share-invite') {
      openShare(action === 'share-invite');
      return;
    }
    if (action === 'report') openModal();
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
    var base = '/api/public/arenas/' + encodeURIComponent(state.ref);
    var today = todayIso();
    var to = addDaysIso(today, 13);
    Promise.all([
      fetchJson(base),
      fetchJson(base + '/sessions?from=' + encodeURIComponent(today) + '&to=' + encodeURIComponent(to)),
      fetchJson(base + '/trainers'),
    ])
      .then(function (parts) {
        if (!parts[0]) {
          showError('Арена не найдена.');
          return;
        }
        state.card = parts[0];
        state.sessions = parts[1] || { days: [] };
        state.trainers = parts[2] || { items: [], groups: [] };
        if (state.focus && state.focus.sessionId && !state.focus.day) {
          var found = M.dayForSession(state.sessions.days, state.focus.sessionId);
          if (found) state.focus.day = found;
        }
        if (state.focus && state.focus.sessionId) {
          state.sharePickSessionId = String(state.focus.sessionId);
        }
        paint();
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

  bindChrome();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})(typeof window !== 'undefined' ? window : this);
