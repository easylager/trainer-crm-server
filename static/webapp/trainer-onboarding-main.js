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
    /* Площадки, отмеченные в режиме «Несколько» — порядок = порядок вкладок-кистей.
       Не больше трёх: столько цветов умеет показать сетка одновременно. */
    multiArenaIds: [],
    activeArenaTab: null,
    /* Map<dayOfWeek, {arenaByHour: {hour: arenaId|null}}> — что сетка умеет нарисовать.
       В режимах «пока не указывать»/«одна площадка» arenaId один и тот же (или null) на
       всех клетках; в «нескольких» на клетку — своя площадка, отсюда и кисть, а не вкладка. */
    week: {},
    /* Слоты, которые эта сетка нарисовать не может: минута не с начала часа (13:25),
       вторая площадка внутри дня, час вне окна площадки. Экран их показывает, считает
       и возвращает на сервер нетронутыми — раньше «Сохранить» их молча удалял. */
    carried: [],
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
      'obArenaMissingLink',
      'obGrid', 'obGridCount', 'obGridMore', 'obWeekHint', 'obCarried',
      'obDoneTitle', 'obDoneLead', 'obDoneScheduleLink',
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
    var arenas = activeArenas();
    if (arenas.length <= 1) {
      var arena = arenas[0] || null;
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
      return;
    }
    /* Несколько площадок — у каждой своё правило. Зафиксированные объясняем по имени;
       если хоть одна оставляет выбор, чипы остаются — они относятся именно к ней. */
    var fixedParts = [];
    var hasOpen = false;
    arenas.forEach(function (a) {
      if (a.fixed_duration_minutes) fixedParts.push('«' + a.name + '» — ' + a.fixed_duration_minutes + ' мин');
      else hasOpen = true;
    });
    if (el.obDurationLockedNote) {
      if (fixedParts.length) {
        el.obDurationLockedNote.hidden = false;
        el.obDurationLockedNote.textContent = 'Зафиксировано: ' + fixedParts.join(', ') + '.' +
          (hasOpen ? ' На остальных площадках — выбор ниже.' : ' Выбирать не нужно.');
      } else {
        el.obDurationLockedNote.hidden = true;
      }
    }
    if (el.obDuration) {
      if (hasOpen) { el.obDuration.hidden = false; renderDuration(); }
      else el.obDuration.hidden = true;
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

  /** Площадки, чью сетку сейчас рисует грид: [] / [одна] / до трёх выбранных «кистей». */
  function activeArenas() {
    if (state.arenaMode === 'single') {
      var a = arenaById(state.singleArenaId);
      return a ? [a] : [];
    }
    if (state.arenaMode === 'multi') {
      return state.multiArenaIds.map(arenaById).filter(function (a) { return !!a; });
    }
    return [];
  }

  /** Площадка, которой красит тап прямо сейчас — «одна» целиком или активная кисть «нескольких». */
  function currentBrushArena() {
    if (state.arenaMode === 'single') return arenaById(state.singleArenaId);
    if (state.arenaMode === 'multi') return arenaById(state.activeArenaTab);
    return null;
  }

  /** Общее смещение минут для строк сетки, или null, если у выбранных площадок оно разное —
      тогда подпись часа остаётся голой, а реальная минута видна на самой клетке. */
  function commonOffset(arenas) {
    if (!arenas.length) return 0;
    var first = arenaOffset(arenas[0]);
    var same = arenas.every(function (a) { return arenaOffset(a) === first; });
    return same ? first : null;
  }

  /* Порядковый индекс площадки среди выбранных кистей — держит цвет клетки и её вкладки
     стабильными, пока сама площадка не снята из списка. Максимум три: см. toggleMultiArena. */
  function arenaColorIndex(arenaId) {
    var i = state.multiArenaIds.indexOf(arenaId);
    return i >= 0 ? i : 0;
  }

  /* Нецветовой различитель клетки (AC-005): 1–2 буквы названия площадки. Цвет один не считается
     ответом — в тёмной теме Telegram на 7×N клетках он теряется, буква — нет.
     Short first tokens (ТЦ, ТРЦ, ФОК) are shared acronyms — use the distinctive next word
     («Замок» → «З»), not a duplicate «ТЦ» or glued «ТЗТЦ Замок». */
  function arenaInitial(arena) {
    if (!arena || !arena.name) return '';
    var parts = arena.name.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '';
    if (parts[0].length <= 3 && parts.length >= 2) {
      return parts[1].charAt(0).toUpperCase();
    }
    if (parts[0].length <= 3) return parts[0].slice(0, 2).toUpperCase();
    if (parts.length >= 2) return (parts[0].charAt(0) + parts[1].charAt(0)).toUpperCase();
    return parts[0].charAt(0).toUpperCase();
  }

  function applyArenaColor(cellEl, arena) {
    if (!arena) return;
    cellEl.classList.add('ob-cell--arena-' + arenaColorIndex(arena.id));
    cellEl.textContent = arenaInitial(arena);
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
       часы на новую площадку (обрезая те, что её сетке не подходят), а не оставляет
       их привязанными к прежней — иначе выбор «одна площадка» ничего бы не значил. */
    Object.keys(state.week).forEach(function (dow) {
      var d = state.week[dow];
      if (!d) return;
      var hrs = clampHoursToArena(Object.keys(d.arenaByHour).map(Number), arena);
      if (!hrs.length) { delete state.week[dow]; return; }
      var next = {};
      hrs.forEach(function (h) { next[h] = arenaId; });
      d.arenaByHour = next;
    });
    haptic('light');
    renderArenaSingleList();
    syncDurationLock();
    renderGrid();
    syncCta();
  }

  /* Больше трёх кистей на сетке не различить: цвет и буква на клетке 7×N клеток начинают
     повторяться, а не добавлять ясность. Честный ответ — не тащить в онбординг больше трёх,
     остальные площадки тренер добавит в «Расписании» уже после сохранения. */
  var MAX_BRUSH_ARENAS = 3;

  function toggleMultiArena(arenaId) {
    var i = state.multiArenaIds.indexOf(arenaId);
    if (i >= 0) {
      /* Снимаем площадку — её клетки освобождаются, остальные площадки того же дня остаются:
         блокировка теперь на уровне клетки, а не всего дня. */
      state.multiArenaIds.splice(i, 1);
      Object.keys(state.week).forEach(function (dow) {
        var d = state.week[dow];
        if (!d) return;
        Object.keys(d.arenaByHour).forEach(function (h) {
          if (d.arenaByHour[h] === arenaId) delete d.arenaByHour[h];
        });
        if (!Object.keys(d.arenaByHour).length) delete state.week[dow];
      });
      if (state.activeArenaTab === arenaId) {
        state.activeArenaTab = state.multiArenaIds.length ? state.multiArenaIds[0] : null;
      }
    } else {
      if (state.multiArenaIds.length >= MAX_BRUSH_ARENAS) {
        note('Пока можно закрасить сетку не больше чем тремя площадками — остальные добавите в «Расписании» после сохранения.', true);
        return;
      }
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

  /* Кисти над сеткой: раньше это были вкладки, переключающие видимый день на арену.
     Теперь сетка одна на всю неделю и показывает все выбранные площадки сразу — кнопка
     здесь выбирает не «что показать», а «чем красит следующий тап». */
  function renderArenaTabs() {
    if (!el.obArenaTabs) return;
    el.obArenaTabs.innerHTML = '';
    if (state.arenaMode !== 'multi' || !state.multiArenaIds.length) {
      el.obArenaTabs.hidden = true;
      return;
    }
    el.obArenaTabs.hidden = false;
    el.obArenaTabs.setAttribute('role', 'group');
    state.multiArenaIds.forEach(function (aid, idx) {
      var arena = arenaById(aid);
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-arena-tab ob-arena-tab--arena-' + idx;
      b.setAttribute('aria-pressed', state.activeArenaTab === aid ? 'true' : 'false');
      var swatch = document.createElement('span');
      swatch.className = 'ob-arena-tab__swatch';
      swatch.textContent = arenaInitial(arena);
      swatch.setAttribute('aria-hidden', 'true');
      b.appendChild(swatch);
      var label = document.createElement('span');
      label.className = 'ob-arena-tab__label';
      label.textContent = arena ? arena.name : ('Площадка #' + aid);
      b.appendChild(label);
      var meta = arena ? arenaMetaLabel(arena) : '';
      if (meta) {
        var metaEl = document.createElement('span');
        metaEl.className = 'ob-arena-tab__meta';
        metaEl.textContent = meta;
        b.appendChild(metaEl);
      }
      b.setAttribute(
        'aria-label',
        'Красить площадкой «' + (arena ? arena.name : aid) + '»' + (meta ? ' (' + meta + ')' : '')
      );
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
    if (mode === 'multi') {
      state.singleArenaId = null;
      /* Клетка в режиме «нескольких» обязана знать свою кисть — начинаем чистый лист:
         сначала отмечаем площадки, потом красим сетку под каждой из них. */
      Object.keys(state.week).forEach(function (dow) { delete state.week[dow]; });
    } else {
      state.multiArenaIds = [];
      state.activeArenaTab = null;
      /* Переключение на «одну»/«пока не указывать» не сносит уже отмеченные часы —
         только площадку у них (и обрезает те, что не влезают в новую площадку). */
      var arena = mode === 'single' ? arenaById(state.singleArenaId) : null;
      Object.keys(state.week).forEach(function (dow) {
        var d = state.week[dow];
        if (!d) return;
        var hrs = Object.keys(d.arenaByHour).map(Number);
        if (mode === 'single' && state.singleArenaId != null) hrs = clampHoursToArena(hrs, arena);
        if (!hrs.length) { delete state.week[dow]; return; }
        var next = {};
        hrs.forEach(function (h) { next[h] = mode === 'single' ? state.singleArenaId : null; });
        d.arenaByHour = next;
      });
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

  /** Объединённый рабочий диапазон выбранных площадок — дыр не бывает, только их общая крайняя рамка. */
  function visibleHours(arenas) {
    if (arenas && arenas.length) {
      var lo = null, hi = null;
      arenas.forEach(function (a) {
        if (lo == null || a.hour_start < lo) lo = a.hour_start;
        if (hi == null || a.hour_end > hi) hi = a.hour_end;
      });
      var out = [];
      for (var h = lo; h <= hi; h++) out.push(h);
      return out;
    }
    if (state.hoursExpanded) return HOURS_ALL;
    /* Часы, которые тренер уже отметил, должны быть видны даже если они вне ходового диапазона —
       иначе он «потеряет» свою же отметку и решит, что она не сохранилась. */
    var used = {};
    Object.keys(state.week).forEach(function (d) {
      dayHours(d).forEach(function (hh) { used[hh] = true; });
    });
    var core = HOURS_ALL.filter(function (hh) {
      return HOURS_CORE.indexOf(hh) >= 0 || used[hh];
    });
    return core.length ? core : HOURS_CORE;
  }

  /* ── Аксессоры по клетке: (день, час) → площадка. Единая модель для всех трёх режимов —
     «одна»/«пока не указывать» просто хранят одну и ту же площадку (или null) в каждой
     занятой клетке дня, «несколько» хранит свою в каждой. ── */
  function dayHours(dow) {
    var d = state.week[dow];
    return d ? Object.keys(d.arenaByHour).map(Number).sort(function (a, b) { return a - b; }) : [];
  }
  /** Площадка клетки: undefined — клетка пуста, null/id — чем закрашена. */
  function cellArena(dow, hour) {
    var d = state.week[dow];
    if (!d || !(hour in d.arenaByHour)) return undefined;
    return d.arenaByHour[hour];
  }
  function setCellArena(dow, hour, arenaId) {
    var d = state.week[dow];
    if (!d) { d = state.week[dow] = { arenaByHour: {} }; }
    d.arenaByHour[hour] = arenaId;
  }
  function clearCell(dow, hour) {
    var d = state.week[dow];
    if (!d) return;
    delete d.arenaByHour[hour];
    if (!Object.keys(d.arenaByHour).length) delete state.week[dow];
  }

  function totalSelectedCells() {
    var n = 0;
    Object.keys(state.week).forEach(function (d) { n += Object.keys(state.week[d].arenaByHour).length; });
    return n;
  }

  /** Всё, что уедет на сервер: отмеченное в сетке плюс перенесённое как есть. */
  function totalSlots() {
    return totalSelectedCells() + state.carried.length;
  }

  function minuteLabel(minute) {
    var h = Math.floor(minute / 60);
    var m = minute % 60;
    return h + ':' + (m < 10 ? '0' + m : String(m));
  }

  /**
   * Слот ложится на сетку онбординга?
   *
   * Сетка умеет ровно одно: целый час плюс смещение площадки. Всё, что в него не попадает —
   * своя минута, чужая площадка внутри дня, час вне окна — экран нарисовать не может, но и
   * потерять не имеет права: тренер настроил это в «Расписании».
   */
  function slotFitsGrid(dow, slot, arenasById) {
    var arena = slot.arenaId != null ? arenasById(slot.arenaId) : null;
    if (slot.arenaId != null && !arena) return false;
    var off = arenaOffset(arena);
    if (slot.startMinute % 60 !== off) return false;
    if (!arena) return true;
    var h = Math.floor(slot.startMinute / 60);
    return h >= arena.hour_start && h <= arena.hour_end;
  }

  function renderCarried() {
    if (!el.obCarried) return;
    if (!state.carried.length) {
      el.obCarried.hidden = true;
      el.obCarried.innerHTML = '';
      return;
    }
    var byDay = {};
    state.carried.forEach(function (c) {
      (byDay[c.dow] = byDay[c.dow] || []).push(c);
    });
    var parts = [];
    Object.keys(byDay).sort(function (a, b) { return a - b; }).forEach(function (dow) {
      var times = byDay[dow]
        .sort(function (a, b) { return a.startMinute - b.startMinute; })
        .map(function (c) {
          var arena = arenaById(c.arenaId);
          return minuteLabel(c.startMinute) + (arena ? ' · ' + arena.name : '');
        });
      parts.push(
        '<div class="ob-carried__row"><span class="ob-carried__day">' + DAY_LABELS[dow] +
        '</span><span class="ob-carried__times">' + times.join(', ') + '</span></div>'
      );
    });
    el.obCarried.innerHTML =
      '<p class="ob-carried__title">Уже настроено в «Расписании» — оставляем как есть:</p>' +
      parts.join('') +
      '<p class="ob-carried__hint">Эти окна сюда не помещаются: своё время начала или другая ' +
      'площадка в тот же день. Менять их — в разделе «Расписание».</p>';
    el.obCarried.hidden = false;
  }

  function syncWeekHint(arenas) {
    if (!el.obWeekHint) return;
    var later = 'Можно не всё сразу — потом подкорректируете :)';
    if (arenas.length === 1) {
      var arena = arenas[0];
      var off = arenaOffset(arena);
      var offTxt = off ? ('с :' + (off < 10 ? '0' + off : off)) : 'с начала часа';
      el.obWeekHint.textContent =
        '«' + arena.name + '»: ' + offTxt + ', ' +
        arena.hour_start + ':00–' + arena.hour_end + ':00. ' + later;
    } else if (arenas.length > 1) {
      var bits = arenas.map(function (a) {
        var o = arenaOffset(a);
        return '«' + a.name + '» — ' + (o ? ('с :' + (o < 10 ? '0' + o : o)) : 'с начала часа');
      });
      el.obWeekHint.textContent = bits.join('; ') + '. Красьте той площадкой, что выбрана вверху.';
    } else if (state.alreadyDone) {
      el.obWeekHint.textContent = 'Можно поправить, если что-то изменилось.';
    } else {
      el.obWeekHint.textContent = 'Мы отметили типичное. ' + later;
    }
  }

  /* Текущая кисть — читается делегированными pointer-хендлерами ниже, чтобы красить
     ячейки во время drag без перерисовки всего грида. */
  var currentBrushArenaId = null;

  function renderGrid() {
    if (!el.obGrid) return;
    var arenas = activeArenas();
    var brush = currentBrushArena();
    currentBrushArenaId = brush ? brush.id : null;
    var offset = commonOffset(arenas);
    var hours = visibleHours(arenas);
    syncWeekHint(arenas);
    if (el.obGridMore) {
      /* У выбранных площадок уже есть свой явный рабочий диапазон — расширять нечего. */
      el.obGridMore.hidden = arenas.length > 0;
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
        el.obGrid.appendChild(makeCell(dow, h));
      }
    });
    renderCarried();
    syncGridCount();
  }

  /**
   * Одна клетка = один час одного дня. В режиме «нескольких» клетка, уже закрашенная
   * ЧУЖОЙ кистью, — только для чтения: тренер физически не может быть в этот час на
   * двух аренах, и это видно на самой клетке, а не спрятано за вкладкой (DEC-004).
   */
  function makeCell(dow, hour) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'ob-cell';
    b.dataset.dow = dow;
    b.dataset.hour = hour;

    var occ = cellArena(dow, hour);
    var multi = state.arenaMode === 'multi';
    var locked = multi && occ !== undefined && occ !== currentBrushArenaId;

    if (locked) {
      var owner = arenaById(occ);
      b.className += ' ob-cell--taken';
      applyArenaColor(b, owner);
      b.disabled = true;
      b.setAttribute(
        'aria-label',
        DAY_LABELS[dow] + ', ' + hourLabel(hour, arenaOffset(owner)) +
          ' — занято: ' + (owner ? owner.name : 'другая площадка')
      );
      return b;
    }

    var pressed = occ !== undefined;
    b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    if (pressed && multi) applyArenaColor(b, arenaById(occ));
    /* Реальная минута клетки: занятой — её собственной площадки, пустой в режиме
       «нескольких» — той, что закрасит следующий тап (AC-008). */
    var realOffset = pressed ? arenaOffset(arenaById(occ)) : (multi ? arenaOffset(arenaById(currentBrushArenaId)) : 0);
    b.setAttribute('aria-label', DAY_LABELS[dow] + ', ' + hourLabel(hour, realOffset));
    /* Клики/тапы и протягивание пальцем обрабатываются делегированно на el.obGrid —
       см. bindGridDrag(). Так одну ячейку можно закрасить без перерисовки всего грида. */
    return b;
  }

  /** Проставляет/снимает кисть на одной ячейке и синхронизирует state.week. */
  function paintCell(cellEl, brushArenaId, value) {
    var dow = parseInt(cellEl.dataset.dow, 10);
    var hour = parseInt(cellEl.dataset.hour, 10);
    if (value) setCellArena(dow, hour, brushArenaId);
    else clearCell(dow, hour);
    cellEl.setAttribute('aria-pressed', value ? 'true' : 'false');
    /* В одну ячейку (без перерисовки всей сетки) makeCell() не заглядывает — цвет/букву
       кисти нужно проставить/снять здесь же, иначе клетка красится только логически. */
    if (state.arenaMode === 'multi') {
      cellEl.className = cellEl.className.replace(/\bob-cell--arena-\d\b/g, '').trim();
      cellEl.textContent = '';
      if (value) applyArenaColor(cellEl, arenaById(brushArenaId));
      var realOffset = value ? arenaOffset(arenaById(brushArenaId)) : arenaOffset(arenaById(currentBrushArenaId));
      cellEl.setAttribute('aria-label', DAY_LABELS[dow] + ', ' + hourLabel(hour, realOffset));
    }
    return true;
  }

  function cellRowCol(cellEl) {
    return cellEl.dataset.dow + '_' + cellEl.dataset.hour;
  }

  function cellUnderPoint(x, y) {
    var target = document.elementFromPoint(x, y);
    if (!target || !target.closest) return null;
    var cellEl = target.closest('.ob-cell');
    if (!cellEl || cellEl.disabled || !el.obGrid.contains(cellEl)) return null;
    return cellEl;
  }

  /**
   * Тап/клик красит одну ячейку, протягивание — все ячейки под курсором/пальцем.
   * Pointer Events: мышь на десктопе + тач в WebView (touch-only ломал десктоп).
   */
  var dragPaint = null;

  function bindGridDrag() {
    if (!el.obGrid || el.obGrid.dataset.obDragBound === '1') return;
    el.obGrid.dataset.obDragBound = '1';

    var onPointerMove = function (e) {
      if (!dragPaint || e.pointerId !== dragPaint.pointerId) return;
      if (e.cancelable) e.preventDefault();
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
    };

    var endDrag = function (e) {
      if (!dragPaint || e.pointerId !== dragPaint.pointerId) return;
      dragPaint = null;
      try {
        if (el.obGrid.hasPointerCapture(e.pointerId)) {
          el.obGrid.releasePointerCapture(e.pointerId);
        }
      } catch (errCapture) { /* старые WebView */ }
      document.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('pointerup', endDrag);
      document.removeEventListener('pointercancel', endDrag);
    };

    el.obGrid.addEventListener('pointerdown', function (e) {
      var cellEl = e.target.closest && e.target.closest('.ob-cell');
      if (!cellEl || cellEl.disabled) return;
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      if (e.cancelable) e.preventDefault();
      var value = cellEl.getAttribute('aria-pressed') !== 'true';
      dragPaint = {
        arenaId: currentBrushArenaId,
        value: value,
        key: cellRowCol(cellEl),
        pointerId: e.pointerId,
      };
      try {
        el.obGrid.setPointerCapture(e.pointerId);
      } catch (errCapture) { /* */ }
      if (paintCell(cellEl, currentBrushArenaId, value)) {
        haptic('light');
        syncGridCount();
        syncCta();
      }
      document.addEventListener('pointermove', onPointerMove);
      document.addEventListener('pointerup', endDrag);
      document.addEventListener('pointercancel', endDrag);
    });

    /* Enter/Space на сфокусированной кнопке — click с detail === 0 (мышь/pointer выше). */
    el.obGrid.addEventListener('click', function (e) {
      if (e.detail !== 0) return;
      var cellEl = e.target.closest && e.target.closest('.ob-cell');
      if (!cellEl || cellEl.disabled) return;
      var value = cellEl.getAttribute('aria-pressed') !== 'true';
      paintCell(cellEl, currentBrushArenaId, value);
      haptic('light');
      syncGridCount();
      syncCta();
    });
  }

  function syncGridCount() {
    if (!el.obGridCount) return;
    var n = totalSlots();
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
    var ok = state.selectedServices.length > 0 && arenaStepValid() && totalSlots() > 0;
    el.obCta.disabled = !ok;
    if (!state.selectedServices.length) note('Выберите, что вы тренируете.');
    else if (!arenaStepValid()) note('Выберите площадку или переключитесь на «Пока не указывать».');
    else if (!totalSlots()) note('Отметьте хотя бы одно время.');
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
        /* Разбор недели: слот попадает в сетку, только если а) лежит на своей часовой сетке
           и б) его площадка входит в первые три различные площадки недели — столько кистей
           сетка умеет показать сразу. Остальное уезжает в state.carried и возвращается на
           сервер нетронутым — раньше вторая площадка внутри дня терялась целиком. */
        var byId = function (id) { return arenaById(id); };
        var flatSlots = [];
        (data.week || []).forEach(function (d) {
          var dow = d.day_of_week;
          if (!d.slots) {
            /* Старый ответ без slots — читаем часы, как читали раньше. */
            (d.hours || []).forEach(function (h) {
              var legacyArena = d.arena_id != null ? d.arena_id : null;
              flatSlots.push({
                dow: dow,
                startMinute: h * 60 + arenaOffset(byId(legacyArena)),
                durationMinutes: null,
                arenaId: legacyArena,
              });
            });
            return;
          }
          d.slots.forEach(function (raw) {
            flatSlots.push({
              dow: dow,
              startMinute: raw.start_minute,
              durationMinutes: raw.duration_minutes != null ? raw.duration_minutes : null,
              arenaId: raw.arena_id != null ? raw.arena_id : null,
            });
          });
        });

        var paintableArenas = [];
        flatSlots.forEach(function (slot) {
          if (
            slot.arenaId != null &&
            paintableArenas.indexOf(slot.arenaId) < 0 &&
            paintableArenas.length < MAX_BRUSH_ARENAS &&
            slotFitsGrid(slot.dow, slot, byId)
          ) {
            paintableArenas.push(slot.arenaId);
          }
        });
        flatSlots.forEach(function (slot) {
          var fits = slotFitsGrid(slot.dow, slot, byId);
          var paintable = fits && (slot.arenaId == null || paintableArenas.indexOf(slot.arenaId) >= 0);
          if (paintable) {
            setCellArena(slot.dow, Math.floor(slot.startMinute / 60), slot.arenaId);
          } else {
            state.carried.push(slot);
          }
        });

        /* Режим при повторном открытии — производная от того, что реально сохранено и
           уместилось на сетку, а не отдельный флаг. */
        if (paintableArenas.length > 1) {
          state.arenaMode = 'multi';
          state.multiArenaIds = paintableArenas.slice();
          state.activeArenaTab = paintableArenas[0];
        } else if (paintableArenas.length === 1) {
          state.arenaMode = 'single';
          state.singleArenaId = paintableArenas[0];
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

    /* Каждая закрашенная клетка идёт явным стартом — своя минута (час + смещение её
       площадки) и своя площадка на слот, а не общий час/арена на день. Только так один
       день может нести две площадки: часовая сетка-шорткат этого не умеет в принципе. */
    var byDay = {};
    function pushSlot(dow, startMinute, durationMinutes, arenaId) {
      (byDay[dow] = byDay[dow] || []).push({
        start_minute: startMinute,
        duration_minutes: durationMinutes,
        arena_id: arenaId,
      });
    }
    Object.keys(state.week).forEach(function (d) {
      var dow = parseInt(d, 10);
      var arenaByHour = state.week[d].arenaByHour;
      Object.keys(arenaByHour).forEach(function (h) {
        var hour = parseInt(h, 10);
        var arenaId = arenaByHour[h];
        pushSlot(dow, hour * 60 + arenaOffset(arenaById(arenaId)), null, arenaId);
      });
    });
    /* Перенесённые слоты идут как есть — их точное время и есть то, ради чего они перенесены. */
    state.carried.forEach(function (c) {
      pushSlot(c.dow, c.startMinute, c.durationMinutes, c.arenaId);
    });
    var days = Object.keys(byDay).map(function (d) {
      return { day_of_week: parseInt(d, 10), slots: byDay[d] };
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
    /* Только тем, у кого реально есть время вне часовой сетки — остальным строка
       была бы просто шумом (DEC-002: «Точное время» в онбординг не тащим). */
    if (el.obDoneScheduleLink) {
      var needsSchedule = state.carried.length > 0;
      el.obDoneScheduleLink.hidden = !needsSchedule;
      if (needsSchedule) {
        el.obDoneScheduleLink.onclick = function (e) {
          e.preventDefault();
          window.location.href = 'schedule-editor' +
            (currentInit() ? '?init_data=' + encodeURIComponent(currentInit()) : '');
        };
      }
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

  /**
   * TASK-046: the onboarding picker is intentionally platform-wide with no city question
   * (см. .ai/RESEARCH-onboarding-multi-arena.md) — creating a new arena needs a city, which
   * this screen deliberately never asks. Rather than bolt a second arena-creation form with
   * different rules onto the one-gesture first screen, send the trainer to the profile's
   * «Арены» section, where city is already known and the real create form lives.
   */
  function goAddMissingArena() {
    window.location.href = 'trainer-profile' +
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
    if (el.obArenaMissingLink) {
      el.obArenaMissingLink.onclick = function (e) {
        e.preventDefault();
        goAddMissingArena();
      };
    }
  }

  cacheEls();
  bind();
  waitForInitDataThen(load);
})();
