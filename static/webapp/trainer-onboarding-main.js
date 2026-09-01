/**
 * Первый запуск тренера — вся логика онбординга v2.
 *
 * Экран 1: что тренирую (чипсы) + сколько длится + где (тумблер площадок) + когда обычно
 * (сетка недели, предзаполненная, привязанная к реальной сетке выбранной площадки).
 * Экран 2: ссылка + одна кнопка «Отправить ученику».
 *
 * Чего здесь намеренно нет: полей ввода, шагов «далее», прогресс-бара, города, телефона,
 * фото и слова «каталог». Площадка — единственное исключение из правила «спрашиваем только
 * когда без ответа что-то ломается»: без неё нельзя честно нарисовать сетку часов (разные
 * площадки стартуют слоты в разные минуты и иногда фиксируют длительность), поэтому вопрос
 * задаётся здесь же, но необязательно — «Пока не указывать» остаётся выбором по умолчанию для
 * тех, у кого площадка не важна прямо сейчас.
 */
(function () {
  'use strict';

  function getTg() {
    return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  }

  function applyChrome(tg) {
    if (!tg) return;
    if (typeof tg.ready === 'function') tg.ready();
    if (typeof tg.expand === 'function') tg.expand();
    try {
      var dark = tg.colorScheme === 'dark';
      var bg = dark ? '#0B0C0E' : '#F1F3F2';
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bg);
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bg);
      if (typeof tg.setBottomBarColor === 'function') tg.setBottomBarColor(bg);
    } catch (e) {
      /* старые клиенты Telegram */
    }
  }

  applyChrome(getTg());

  function initDataFromUrl() {
    try {
      var qs = new URLSearchParams(window.location.search || '');
      return qs.get('init_data') || qs.get('initData') || '';
    } catch (e) {
      return '';
    }
  }

  /**
   * Never snapshot initData at parse time. Reply-keyboard Mini Apps («Начать») and cold
   * WebViews often fill Telegram.WebApp.initData a tick after the first script runs.
   * A GET without it is 401 → chrome overlay «Что-то пошло не так». Same wait as hub.
   */
  function currentInit() {
    var t = getTg();
    var raw = (t && t.initData) || initDataFromUrl();
    return raw ? String(raw) : '';
  }

  function waitForInitDataThen(callback) {
    try {
      var tg0 = getTg();
      if (tg0 && typeof tg0.ready === 'function') tg0.ready();
    } catch (eReady) { /* */ }
    if (currentInit()) {
      applyChrome(getTg());
      callback();
      return;
    }
    requestAnimationFrame(function () {
      if (currentInit()) {
        applyChrome(getTg());
        callback();
        return;
      }
      requestAnimationFrame(function () {
        if (currentInit()) {
          applyChrome(getTg());
          callback();
          return;
        }
        var n = 0;
        var maxTicks = 140;
        var iv = setInterval(function () {
          n++;
          if (currentInit()) {
            clearInterval(iv);
            applyChrome(getTg());
            callback();
            return;
          }
          if (n >= maxTicks) {
            clearInterval(iv);
            setTimeout(function () {
              applyChrome(getTg());
              callback();
            }, 420);
          }
        }, 50);
      });
    });
  }
  function apiHeaders() {
    var raw = currentInit();
    var h = { 'Content-Type': 'application/json' };
    if (raw) h['X-Telegram-Init-Data'] = raw;
    return h;
  }
  function apiUrl(path) {
    var raw = currentInit();
    return '/api/webapp' + path + (raw ? '?init_data=' + encodeURIComponent(raw) : '');
  }

  var DAY_LABELS = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'];
  /* Ледовое утро начинается рано, вечер заканчивается поздно — но сразу показывать 6:00–22:00
     значит показать 112 клеток. Открываем ходовой диапазон, остальное — по кнопке.
     Это только для режима «Пока не указывать»: у выбранной площадки уже есть свой явный
     рабочий диапазон, и подбирать его эвристикой незачем — берём как есть. */
  var HOURS_CORE = [7, 8, 9, 17, 18, 19, 20];
  var HOURS_ALL = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22];
  /* Реальные длительности ледового занятия. Не поле ввода — три варианта, один тап. */
  var DURATIONS = [45, 60, 90];

  var state = {
    services: [],
    selectedServices: [],
    arenas: [],
    /* 'none' | 'single' | 'multi' */
    arenaMode: 'none',
    singleArenaId: null,
    /* Площадки, отмеченные в режиме «Несколько» — порядок = порядок вкладок. */
    multiArenaIds: [],
    activeArenaTab: null,
    /* Map<dayOfWeek, {hours: number[], arenaId: number|null}> */
    week: {},
    durationMinutes: 60,
    hoursExpanded: false,
    alreadyDone: false,
    busy: false,
  };

  var el = {};
  function byId(id) { return document.getElementById(id); }

  function cacheEls() {
    [
      'obLoading', 'obFatal', 'obSetup', 'obDone', 'obFoot', 'obCta', 'obNote', 'obSkip',
      'obTitle', 'obServices', 'obDuration', 'obDurationLockedNote',
      'obArenaMode', 'obArenaSingleWrap', 'obArenaSingleSearch', 'obArenaSingleList',
      'obArenaMultiPickWrap', 'obArenaMultiSearch', 'obArenaMultiList', 'obArenaTabs',
      'obGrid', 'obGridCount', 'obGridMore', 'obWeekHint',
      'obDoneTitle', 'obDoneLead',
    ].forEach(function (id) { el[id] = byId(id); });
  }

  function haptic(kind) {
    try {
      var tg = getTg();
      if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.impactOccurred === 'function') {
        tg.HapticFeedback.impactOccurred(kind || 'light');
      }
    } catch (e) { /* нет вибро — не беда */ }
  }

  function fatal(text) {
    if (el.obLoading) el.obLoading.style.display = 'none';
    if (el.obFatal) {
      el.obFatal.textContent = text;
      el.obFatal.style.display = 'block';
    }
  }

  function note(text, isError) {
    if (!el.obNote) return;
    el.obNote.textContent = text || '';
    el.obNote.classList.toggle('is-error', !!isError);
  }

  /* ── Склонения: «1 окно / 2 окна / 5 окон» ── */
  function plural(n, one, few, many) {
    var mod10 = n % 10;
    var mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
    return many;
  }
  function slotsWord(n) { return plural(n, 'окно', 'окна', 'окон'); }

  /* ── Услуги ── */
  function renderServices() {
    if (!el.obServices) return;
    el.obServices.innerHTML = '';
    state.services.forEach(function (svc) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-chip';
      b.textContent = svc.name;
      var on = state.selectedServices.indexOf(svc.id) >= 0;
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.onclick = function () {
        var i = state.selectedServices.indexOf(svc.id);
        if (i >= 0) state.selectedServices.splice(i, 1);
        else state.selectedServices.push(svc.id);
        b.setAttribute('aria-pressed', state.selectedServices.indexOf(svc.id) >= 0 ? 'true' : 'false');
        haptic('light');
        syncCta();
      };
      el.obServices.appendChild(b);
    });
  }

  /* ── Длительность ── */
  function renderDuration() {
    if (!el.obDuration) return;
    /* Значение из профиля может не совпасть ни с одним чипом (тренер менял его в настройках) —
       тогда показываем и его, чтобы выбор не «перескочил» молча на соседнее. */
    var options = DURATIONS.slice();
    if (options.indexOf(state.durationMinutes) < 0) {
      options.push(state.durationMinutes);
      options.sort(function (a, b) { return a - b; });
    }
    el.obDuration.innerHTML = '';
    options.forEach(function (mins) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-chip';
      b.textContent = mins + ' мин';
      b.setAttribute('aria-pressed', state.durationMinutes === mins ? 'true' : 'false');
      b.onclick = function () {
        state.durationMinutes = mins;
        haptic('light');
        renderDuration();
      };
      el.obDuration.appendChild(b);
    });
  }

  /**
   * Площадка фиксирует длительность (например, каток продаёт только 90-минутные слоты) —
   * тогда чипы прячутся и вместо них честная надпись, что именно и почему. Это не меняет
   * state.durationMinutes: тот остаётся общим выбором тренера для дней БЕЗ такой площадки —
   * сервер сам подставляет фиксированное значение только для дней этой конкретной арены
   * (см. _day_grid в trainer_quick_setup_use_cases.py).
   */
  function syncDurationLock() {
    var arena = currentGridArena();
    var fixed = arena ? arena.fixed_duration_minutes : null;
    if (fixed) {
      if (el.obDuration) el.obDuration.hidden = true;
      if (el.obDurationLockedNote) {
        el.obDurationLockedNote.hidden = false;
        el.obDurationLockedNote.textContent =
          'На площадке «' + arena.name + '» длительность зафиксирована: ' + fixed + ' мин. Выбирать не нужно.';
      }
    } else {
      if (el.obDuration) { el.obDuration.hidden = false; renderDuration(); }
      if (el.obDurationLockedNote) el.obDurationLockedNote.hidden = true;
    }
  }

  /* ── Площадки: общие помощники ── */
  function arenaById(id) {
    if (id == null) return null;
    for (var i = 0; i < state.arenas.length; i++) {
      if (state.arenas[i].id === id) return state.arenas[i];
    }
    return null;
  }

  function arenaOffset(arena) {
    return (arena && arena.grid_kind === 'hourly_minute') ? (arena.minute_offset || 0) : 0;
  }

  /** Площадка, чью сетку сейчас рисует грид: выбранная «одна» или активная вкладка «нескольких». */
  function currentGridArena() {
    if (state.arenaMode === 'single') return arenaById(state.singleArenaId);
    if (state.arenaMode === 'multi') return arenaById(state.activeArenaTab);
    return null;
  }

  function arenaMetaLabel(arena) {
    var bits = [];
    if (arena.city_name) bits.push(arena.city_name);
    var off = arenaOffset(arena);
    if (off) {
      bits.push('слоты с :' + (off < 10 ? '0' + off : off) + ' каждого часа');
    }
    if (arena.fixed_duration_minutes) {
      bits.push(arena.fixed_duration_minutes + ' мин фиксированно');
    }
    return bits.join(' · ');
  }

  function filteredArenas(query) {
    var q = (query || '').trim().toLowerCase();
    if (!q) return state.arenas;
    return state.arenas.filter(function (a) {
      return (a.name || '').toLowerCase().indexOf(q) >= 0 ||
        (a.city_name || '').toLowerCase().indexOf(q) >= 0;
    });
  }

  function renderArenaOptionsInto(host, query, isSelected, onPick) {
    if (!host) return;
    var list = filteredArenas(query);
    host.innerHTML = '';
    if (!list.length) {
      var empty = document.createElement('div');
      empty.className = 'ob-arena-empty';
      empty.textContent = 'Площадок не найдено.';
      host.appendChild(empty);
      return;
    }
    list.forEach(function (a) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-arena-option';
      b.setAttribute('aria-pressed', isSelected(a.id) ? 'true' : 'false');
      var nameEl = document.createElement('span');
      nameEl.className = 'ob-arena-option__name';
      nameEl.textContent = a.name;
      b.appendChild(nameEl);
      var meta = arenaMetaLabel(a);
      if (meta) {
        var metaEl = document.createElement('span');
        metaEl.className = 'ob-arena-option__meta';
        metaEl.textContent = meta;
        b.appendChild(metaEl);
      }
      b.onclick = function () { onPick(a.id); };
      host.appendChild(b);
    });
  }

  function renderArenaSingleList() {
    var q = el.obArenaSingleSearch ? el.obArenaSingleSearch.value : '';
    renderArenaOptionsInto(
      el.obArenaSingleList,
      q,
      function (id) { return state.singleArenaId === id; },
      selectSingleArena
    );
  }

  function renderArenaMultiList() {
    var q = el.obArenaMultiSearch ? el.obArenaMultiSearch.value : '';
    renderArenaOptionsInto(
      el.obArenaMultiList,
      q,
      function (id) { return state.multiArenaIds.indexOf(id) >= 0; },
      toggleMultiArena
    );
  }

  /** Отбрасывает часы, не попадающие в рабочее окно площадки — тихо и сразу видно на сетке. */
  function clampHoursToArena(hours, arena) {
    if (!arena) return hours;
    return hours.filter(function (h) { return h >= arena.hour_start && h <= arena.hour_end; });
  }

  function selectSingleArena(arenaId) {
    state.singleArenaId = arenaId;
    var arena = arenaById(arenaId);
    /* Одна площадка — значит одна на всю неделю. Переключение переносит уже отмеченные
       дни на новую площадку (обрезая часы, которые её сетке не подходят), а не оставляет
       их привязанными к прежней — иначе выбор «одна площадка» ничего бы не значил. */
    Object.keys(state.week).forEach(function (dow) {
      var d = state.week[dow];
      if (!d) return;
      var hrs = clampHoursToArena(d.hours, arena);
      if (!hrs.length) { delete state.week[dow]; return; }
      d.hours = hrs;
      d.arenaId = arenaId;
    });
    haptic('light');
    renderArenaSingleList();
    syncDurationLock();
    renderGrid();
    syncCta();
  }

  function toggleMultiArena(arenaId) {
    var i = state.multiArenaIds.indexOf(arenaId);
    if (i >= 0) {
      /* Снимаем площадку — дни под ней освобождаются целиком: иначе в расписании
         останутся часы для площадки, которую тренер только что убрал из списка. */
      state.multiArenaIds.splice(i, 1);
      Object.keys(state.week).forEach(function (dow) {
        if (state.week[dow] && state.week[dow].arenaId === arenaId) delete state.week[dow];
      });
      if (state.activeArenaTab === arenaId) {
        state.activeArenaTab = state.multiArenaIds.length ? state.multiArenaIds[0] : null;
      }
    } else {
      state.multiArenaIds.push(arenaId);
      if (state.activeArenaTab == null) state.activeArenaTab = arenaId;
    }
    haptic('light');
    renderArenaMultiList();
    renderArenaTabs();
    syncDurationLock();
    renderGrid();
    syncCta();
  }

  function renderArenaTabs() {
    if (!el.obArenaTabs) return;
    el.obArenaTabs.innerHTML = '';
    if (state.arenaMode !== 'multi' || !state.multiArenaIds.length) {
      el.obArenaTabs.hidden = true;
      return;
    }
    el.obArenaTabs.hidden = false;
    state.multiArenaIds.forEach(function (aid) {
      var arena = arenaById(aid);
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-arena-tab';
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', state.activeArenaTab === aid ? 'true' : 'false');
      b.textContent = arena ? arena.name : ('Площадка #' + aid);
      b.onclick = function () {
        if (state.activeArenaTab === aid) return;
        state.activeArenaTab = aid;
        haptic('light');
        renderArenaTabs();
        syncDurationLock();
        renderGrid();
      };
      el.obArenaTabs.appendChild(b);
    });
  }

  function renderArenaMode() {
    if (!el.obArenaMode) return;
    Array.prototype.forEach.call(el.obArenaMode.querySelectorAll('[data-arena-mode]'), function (btn) {
      var m = btn.getAttribute('data-arena-mode');
      btn.setAttribute('aria-pressed', m === state.arenaMode ? 'true' : 'false');
    });
    if (el.obArenaSingleWrap) el.obArenaSingleWrap.hidden = state.arenaMode !== 'single';
    if (el.obArenaMultiPickWrap) el.obArenaMultiPickWrap.hidden = state.arenaMode !== 'multi';
  }

  function setArenaMode(mode) {
    if (state.arenaMode === mode) return;
    state.arenaMode = mode;
    /* Переключение режима не сносит уже отмеченные часы — только площадку у них. */
    Object.keys(state.week).forEach(function (dow) {
      if (state.week[dow]) state.week[dow].arenaId = null;
    });
    if (mode === 'single') {
      state.multiArenaIds = [];
      state.activeArenaTab = null;
      if (state.singleArenaId != null) {
        var arena = arenaById(state.singleArenaId);
        Object.keys(state.week).forEach(function (dow) {
          var d = state.week[dow];
          if (!d) return;
          var hrs = clampHoursToArena(d.hours, arena);
          if (!hrs.length) { delete state.week[dow]; return; }
          d.hours = hrs;
          d.arenaId = state.singleArenaId;
        });
      }
    } else if (mode === 'multi') {
      state.singleArenaId = null;
      /* В мульти-режиме день без своей вкладки показать нельзя — начинаем чистый лист:
         сначала отмечаем площадки, потом расставляем часы под каждой из них. */
      Object.keys(state.week).forEach(function (dow) { delete state.week[dow]; });
    }
    haptic('light');
    renderArenaMode();
    renderArenaSingleList();
    renderArenaMultiList();
    renderArenaTabs();
    syncDurationLock();
    renderGrid();
    syncCta();
  }

  /* ── Сетка недели ── */
  function hourLabel(hour, offset) {
    if (!offset) return String(hour);
    var mm = offset < 10 ? '0' + offset : String(offset);
    return hour + ':' + mm;
  }

  function visibleHours(arena) {
    if (arena) {
      var out = [];
      for (var h = arena.hour_start; h <= arena.hour_end; h++) out.push(h);
      return out;
    }
    if (state.hoursExpanded) return HOURS_ALL;
    /* Часы, которые тренер уже отметил, должны быть видны даже если они вне ходового диапазона —
       иначе он «потеряет» свою же отметку и решит, что она не сохранилась. */
    var used = {};
    Object.keys(state.week).forEach(function (d) {
      (state.week[d].hours || []).forEach(function (hh) { used[hh] = true; });
    });
    var core = HOURS_ALL.filter(function (hh) {
      return HOURS_CORE.indexOf(hh) >= 0 || used[hh];
    });
    return core.length ? core : HOURS_CORE;
  }

  function dayHours(dow) {
    var d = state.week[dow];
    return d ? d.hours : [];
  }
  function dayArenaId(dow) {
    var d = state.week[dow];
    return d ? d.arenaId : null;
  }
  function setDayHours(dow, hours, arenaId) {
    if (!hours.length) { delete state.week[dow]; return; }
    state.week[dow] = { hours: hours, arenaId: arenaId };
  }

  function totalSelectedCells() {
    var n = 0;
    Object.keys(state.week).forEach(function (d) { n += state.week[d].hours.length; });
    return n;
  }

  function syncWeekHint(arena) {
    if (!el.obWeekHint) return;
    var later = 'Можно не всё сразу — потом подкорректируете :)';
    if (arena) {
      var off = arenaOffset(arena);
      var offTxt = off ? ('с :' + (off < 10 ? '0' + off : off)) : 'с начала часа';
      el.obWeekHint.textContent =
        '«' + arena.name + '»: ' + offTxt + ', ' +
        arena.hour_start + ':00–' + arena.hour_end + ':00. ' + later;
    } else if (state.alreadyDone) {
      el.obWeekHint.textContent = 'Можно поправить, если что-то изменилось.';
    } else {
      el.obWeekHint.textContent = 'Мы отметили типичное. ' + later;
    }
  }

  /* Контекст площадки для текущей отрисовки грида — читается делегированными pointer-
     хендлерами ниже, чтобы красить ячейки во время drag без полной перерисовки грида. */
  var currentCtxArenaId = null;

  function renderGrid() {
    if (!el.obGrid) return;
    var arena = currentGridArena();
    var offset = arenaOffset(arena);
    var ctxArenaId = arena ? arena.id : null;
    currentCtxArenaId = ctxArenaId;
    var hours = visibleHours(arena);
    syncWeekHint(arena);
    if (el.obGridMore) {
      /* У площадки уже есть свой явный рабочий диапазон — расширять нечего. */
      el.obGridMore.hidden = !!arena;
    }

    el.obGrid.innerHTML = '';

    var corner = document.createElement('div');
    el.obGrid.appendChild(corner);
    DAY_LABELS.forEach(function (label, idx) {
      var d = document.createElement('div');
      d.className = 'ob-grid-dayhead' + (idx >= 5 ? ' is-weekend' : '');
      d.textContent = label;
      el.obGrid.appendChild(d);
    });

    hours.forEach(function (h) {
      var hcell = document.createElement('div');
      hcell.className = 'ob-grid-hour';
      hcell.textContent = hourLabel(h, offset);
      el.obGrid.appendChild(hcell);

      for (var dow = 0; dow < 7; dow++) {
        el.obGrid.appendChild(makeCell(dow, h, ctxArenaId, offset));
      }
    });
    syncGridCount();
  }

  function makeCell(dow, hour, ctxArenaId, offset) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'ob-cell';
    b.dataset.dow = dow;
    b.dataset.hour = hour;

    var existingArena = dayArenaId(dow);
    var hours = dayHours(dow);
    /* Мульти-режим: день, уже занятый другой вкладкой, здесь только для чтения — иначе
       один день незаметно оказался бы разбит между двумя площадками одновременно. */
    var taken = state.arenaMode === 'multi' && existingArena != null &&
      existingArena !== ctxArenaId && hours.length > 0;
    if (taken) {
      b.className += ' ob-cell--taken';
      b.disabled = true;
      var owner = arenaById(existingArena);
      b.setAttribute('aria-label', DAY_LABELS[dow] + ' — занято: ' + (owner ? owner.name : 'другая площадка'));
      return b;
    }

    var on = hours.indexOf(hour) >= 0 && existingArena === ctxArenaId;
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.setAttribute('aria-label', DAY_LABELS[dow] + ', ' + hourLabel(hour, offset));
    /* Клики/тапы и протягивание пальцем обрабатываются делегированно на el.obGrid —
       см. bindGridDrag(). Так одну ячейку можно закрасить без перерисовки всего грида. */
    return b;
  }

  /** Проставляет/снимает значение для одной ячейки и синхронизирует state.week. */
  function paintCell(cellEl, ctxArenaId, value) {
    var dow = parseInt(cellEl.dataset.dow, 10);
    var hour = parseInt(cellEl.dataset.hour, 10);
    var cur = dayHours(dow).slice();
    var i = cur.indexOf(hour);
    if (value && i < 0) cur.push(hour);
    else if (!value && i >= 0) cur.splice(i, 1);
    else return false;
    setDayHours(dow, cur, ctxArenaId);
    cellEl.setAttribute('aria-pressed', value ? 'true' : 'false');
    return true;
  }

  function cellRowCol(cellEl) {
    return cellEl.dataset.dow + '_' + cellEl.dataset.hour;
  }

  function cellUnderPoint(x, y) {
    var target = document.elementFromPoint(x, y);
    var cellEl = target && target.closest ? target.closest('.ob-cell') : null;
    if (!cellEl || cellEl.disabled || !el.obGrid.contains(cellEl)) return null;
    return cellEl;
  }

  /**
   * Тап красит одну ячейку, протягивание пальцем — все ячейки под ним, тем же значением,
   * что взято от первой (toggle). Проведённый штрих не триггерит полную перерисовку грида —
   * только точечные атрибуты, иначе на быстром движении будет видимый рывок/мерцание.
   */
  var dragPaint = null;

  function bindGridDrag() {
    if (!el.obGrid) return;

    el.obGrid.addEventListener('pointerdown', function (e) {
      var cellEl = e.target.closest && e.target.closest('.ob-cell');
      if (!cellEl || cellEl.disabled) return;
      var value = cellEl.getAttribute('aria-pressed') !== 'true';
      dragPaint = { arenaId: currentCtxArenaId, value: value, key: cellRowCol(cellEl), pointerId: e.pointerId };
      paintCell(cellEl, currentCtxArenaId, value);
      haptic('light');
      syncGridCount();
      syncCta();
      try { el.obGrid.setPointerCapture(e.pointerId); } catch (err) { /* старые браузеры без capture */ }
    });

    el.obGrid.addEventListener('pointermove', function (e) {
      if (!dragPaint || dragPaint.pointerId !== e.pointerId) return;
      var cellEl = cellUnderPoint(e.clientX, e.clientY);
      if (!cellEl) return;
      var key = cellRowCol(cellEl);
      if (key === dragPaint.key) return;
      dragPaint.key = key;
      if (paintCell(cellEl, dragPaint.arenaId, dragPaint.value)) {
        haptic('light');
        syncGridCount();
        syncCta();
      }
    });

    function endDrag(e) {
      if (!dragPaint || dragPaint.pointerId !== e.pointerId) return;
      dragPaint = null;
    }
    el.obGrid.addEventListener('pointerup', endDrag);
    el.obGrid.addEventListener('pointercancel', endDrag);

    /* Клик от клавиатуры (Enter/Space на сфокусированной кнопке) не проходит через pointerdown
       выше — ловим его отдельно по detail === 0 (у клика мышью/тапом detail >= 1). */
    el.obGrid.addEventListener('click', function (e) {
      if (e.detail !== 0) return;
      var cellEl = e.target.closest && e.target.closest('.ob-cell');
      if (!cellEl || cellEl.disabled) return;
      var value = cellEl.getAttribute('aria-pressed') !== 'true';
      paintCell(cellEl, currentCtxArenaId, value);
      haptic('light');
      syncGridCount();
      syncCta();
    });
  }

  function syncGridCount() {
    if (!el.obGridCount) return;
    var n = totalSelectedCells();
    el.obGridCount.textContent = n
      ? (n + ' ' + slotsWord(n) + ' в неделю')
      : 'Ничего не отмечено';
  }

  function arenaStepValid() {
    if (state.arenaMode === 'single') return state.singleArenaId != null;
    if (state.arenaMode === 'multi') return state.multiArenaIds.length > 0;
    return true;
  }

  function syncCta() {
    if (!el.obCta) return;
    if (state.busy) {
      el.obCta.disabled = true;
      return;
    }
    var ok = state.selectedServices.length > 0 && arenaStepValid() && totalSelectedCells() > 0;
    el.obCta.disabled = !ok;
    if (!state.selectedServices.length) note('Выберите, что вы тренируете.');
    else if (!arenaStepValid()) note('Выберите площадку или переключитесь на «Пока не указывать».');
    else if (!totalSelectedCells()) note('Отметьте хотя бы одно время.');
    else note('');
  }

  /* ── Загрузка ── */
  function load() {
    fetch(apiUrl('/trainer/onboarding/quick-setup'), { headers: apiHeaders() })
      .then(function (r) {
        if (r.status === 403) throw new Error('forbidden');
        if (!r.ok) throw new Error('http_' + r.status);
        return r.json();
      })
      .then(function (data) {
        state.services = data.services || [];
        state.selectedServices = (data.selected_service_ids || []).slice();
        state.arenas = data.arenas || [];
        state.durationMinutes = data.duration_minutes || 60;
        state.alreadyDone = !!data.already_done;
        (data.week || []).forEach(function (d) {
          state.week[d.day_of_week] = {
            hours: (d.hours || []).slice(),
            arenaId: d.arena_id != null ? d.arena_id : null,
          };
        });

        /* Режим при повторном открытии — производная от того, что реально сохранено,
           а не отдельный флаг: «несколько» значит «в неделе больше одной площадки». */
        if (data.multi_arena) {
          state.arenaMode = 'multi';
          var seen = {};
          state.multiArenaIds = [];
          Object.keys(state.week).forEach(function (dow) {
            var aid = state.week[dow].arenaId;
            if (aid != null && !seen[aid]) { seen[aid] = true; state.multiArenaIds.push(aid); }
          });
          state.activeArenaTab = state.multiArenaIds.length ? state.multiArenaIds[0] : null;
        } else {
          var singleId = null;
          Object.keys(state.week).some(function (dow) {
            if (state.week[dow].arenaId != null) { singleId = state.week[dow].arenaId; return true; }
            return false;
          });
          if (singleId != null) {
            state.arenaMode = 'single';
            state.singleArenaId = singleId;
          }
        }

        var name = (data.first_name || '').trim();
        if (el.obTitle) {
          /* Вернувшемуся тренеру не обещаем «настроим за две минуты» — он уже настроил.
             Экран для него это правка расписания, и заголовок должен говорить именно это. */
          if (state.alreadyDone) {
            el.obTitle.textContent = 'Ваше расписание';
          } else {
            el.obTitle.textContent = name
              ? (name + ', настроим за две минуты')
              : 'Настроим за две минуты';
          }
        }
        var lead = document.querySelector('.ob-lead');
        if (lead && state.alreadyDone) {
          lead.textContent = 'Поправьте, если что-то изменилось, — и заберите ссылку для ученика.';
        }
        if (el.obCta && state.alreadyDone) el.obCta.textContent = 'Сохранить';

        if (el.obLoading) el.obLoading.style.display = 'none';
        if (el.obSetup) el.obSetup.hidden = false;
        if (el.obFoot) el.obFoot.hidden = false;
        renderServices();
        renderArenaMode();
        renderArenaSingleList();
        renderArenaMultiList();
        renderArenaTabs();
        syncDurationLock();
        renderGrid();
        syncCta();
      })
      .catch(function (err) {
        if (err && err.message === 'forbidden') {
          fatal('Этот раздел доступен тренерам. Откройте бот заново по своей ссылке.');
        } else {
          fatal('Не получилось загрузить. Проверьте связь и откройте экран ещё раз.');
        }
      });
  }

  /* ── Сохранение ── */
  function submit() {
    if (state.busy) return;
    state.busy = true;
    syncCta();
    note('Создаём расписание…');

    var days = Object.keys(state.week).map(function (d) {
      var row = state.week[d];
      return { day_of_week: parseInt(d, 10), hours: row.hours, arena_id: row.arenaId };
    });

    fetch(apiUrl('/trainer/onboarding/quick-setup'), {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({
        service_ids: state.selectedServices,
        days: days,
        duration_minutes: state.durationMinutes,
      }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok) throw new Error(body && body.detail ? body.detail : 'Не удалось сохранить.');
          return body;
        });
      })
      .then(function (body) {
        haptic('medium');
        showDone(body);
      })
      .catch(function (err) {
        state.busy = false;
        note((err && err.message) || 'Не удалось сохранить. Попробуйте ещё раз.', true);
        syncCta();
      });
  }

  /* ── Экран 2 ── */
  function showDone(body) {
    state.busy = false;
    if (el.obSetup) el.obSetup.hidden = true;
    if (el.obDone) el.obDone.classList.add('is-on');

    var open = body.open_slots_ahead || 0;
    if (el.obDoneTitle) {
      el.obDoneTitle.textContent = open
        ? (open + ' ' + slotsWord(open) + ' на две недели')
        : 'Расписание сохранено';
    }
    if (el.obDoneLead) {
      el.obDoneLead.textContent = open
        ? 'Ученик увидит их и выберет сам — без переписки «когда вам удобно».'
        : 'Ближайшие свободные окна появятся со следующей недели.';
    }

    var link = body.link;
    var shareText = body.share_text || '';
    var shareBody = body.share_body || '';
    if (el.obCta) {
      if (link) {
        el.obCta.textContent = 'Отправить ученику';
        el.obCta.disabled = false;
        el.obCta.onclick = function () { share(link, shareText, shareBody); };
        note('Откроется список ваших чатов в Telegram.');
      } else {
        /* Без CLIENT_BOT_USERNAME ссылку собрать нечем. Честно говорим об этом,
           а не показываем кнопку, которая ничего не делает. */
        el.obCta.textContent = 'Открыть кабинет';
        el.obCta.disabled = false;
        el.obCta.onclick = goHub;
        note('Ссылка для учеников появится чуть позже — расписание уже сохранено.');
      }
    }
    if (el.obSkip) {
      el.obSkip.hidden = !link;
      el.obSkip.onclick = goHub;
    }
  }

  function share(link, text, shareBody) {
    /* t.me/share/url без url= Telegram молча игнорирует. Ссылку кладём в url=,
       заготовленный текст — в text= (хелпер сам вырежет дубль URL из сообщения). */
    var opened = false;
    if (typeof window.openTelegramShareUrlFromMiniApp === 'function') {
      opened = !!window.openTelegramShareUrlFromMiniApp({
        shareUrl: link,
        shareBody: shareBody || '',
        fullMessage: text || link || '',
      });
    }
    if (opened) {
      /* Telegram не сообщает, отправил ли пользователь сообщение. Поэтому не празднуем
         заранее: меняем подпись на честную и оставляем путь в кабинет. */
      note('Отправили? Как только ученик запишется — придёт уведомление сюда.');
      if (el.obSkip) {
        el.obSkip.hidden = false;
        el.obSkip.textContent = 'Перейти в кабинет';
      }
      return;
    }
    copyLink(link);
  }

  function copyLink(link) {
    var done = function () { note('Ссылка скопирована — вставьте её в чат с учеником.'); };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(link).then(done, function () { legacyCopy(link, done); });
        return;
      }
    } catch (e) { /* ниже */ }
    legacyCopy(link, done);
  }

  function legacyCopy(link, done) {
    try {
      var ta = document.createElement('textarea');
      ta.value = link;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      done();
    } catch (e) {
      note(link, false);
    }
  }

  function goHub() {
    window.location.href = 'trainer-home' +
      (currentInit() ? '?init_data=' + encodeURIComponent(currentInit()) : '');
  }

  function bind() {
    if (el.obCta) el.obCta.onclick = submit;
    bindGridDrag();
    if (el.obGridMore) {
      el.obGridMore.onclick = function () {
        state.hoursExpanded = !state.hoursExpanded;
        el.obGridMore.textContent = state.hoursExpanded ? 'Свернуть часы' : 'Показать больше часов';
        renderGrid();
      };
    }
    if (el.obArenaMode) {
      Array.prototype.forEach.call(el.obArenaMode.querySelectorAll('[data-arena-mode]'), function (btn) {
        btn.onclick = function () { setArenaMode(btn.getAttribute('data-arena-mode')); };
      });
    }
    if (el.obArenaSingleSearch) el.obArenaSingleSearch.oninput = renderArenaSingleList;
    if (el.obArenaMultiSearch) el.obArenaMultiSearch.oninput = renderArenaMultiList;
  }

  cacheEls();
  bind();
  waitForInitDataThen(load);
})();
