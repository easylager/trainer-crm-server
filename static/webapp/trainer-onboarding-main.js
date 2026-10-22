/**
 * Первый запуск тренера — вся логика онбординга (TASK-312).
 *
 * Вступление → три шага → ссылка. Шаг 1: что ведёте (плитки услуг, длительность, роль строкой).
 * Шаг 2: где (город, один список площадок с галочками, до трёх). Шаг 3: когда — неделя окнами
 * «утро / день / вечер», окно раскрывается в точные старты (trainer-onboarding-week-model.js).
 * Финал: ссылка + одна кнопка «Отправить ученику».
 *
 * Роль, своя услуга, город и площадка добавляются одним паттерном: «…нет в списке» → панель
 * с полем и «Добавить»/«Отмена». Создание площадки и города — здесь же, без редиректа в профиль.
 * Сохранение — один POST quick-setup со всеми стартами недели, как и раньше.
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

  function pageUrl(pathWithQuery) {
    var url = String(pathWithQuery || '');
    var raw = currentInit();
    if (raw) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(raw);
    return url;
  }

  var OB_DONE_STORAGE_KEY = 'obDoneReturn';
  var WM = window.TrainerOnboardingWeekModel;

  var MAX_SPECIALIST_ROLES = 5;
  /** Сколько площадок показываем в комбобоксе до сужения поиском (весь город не листаем). */
  var ARENA_BROWSE_CAP = 15;
  /* Реальные длительности ледового занятия. Не поле ввода — три варианта, один тап. */
  var DURATIONS = [45, 60, 90];

  var state = {
    services: [],
    selectedServices: [],
    /* Кем себя называет специалист. Свободный текст с подсказками: к нам идут
       не только тренеры по конькам, и угадать список ролей заранее нельзя.
       null = ещё не спрашивали — чип не подсвечиваем, а не подставляем «Тренер». */
    roleSuggestions: [],
    selectedRoles: [],
    roleIsCustom: false,
    /* Услуги, вписанные вручную на этом экране. Уходят отдельным полем: id у них
       появится только на сервере, после дедупа. */
    customServiceNames: [],
    /* service_id → bool; default false (venue). */
    serviceOnlineById: {},
    /* custom name → bool. */
    customServiceOnlineByName: {},
    /* Draft format while adding a custom service. */
    newCustomServiceOnline: false,
    /* Типы площадок для формы создания (ice|gym|choreo|…). */
    venueTypes: [],
    newArenaVenueType: 'ice',
    cities: [],
    cityId: null,
    arenas: [],
    /* 'none' | 'single' | 'multi' | 'online' — производное от pickedArenaIds и формата услуг. */
    arenaMode: 'none',
    /* Чьё время отмечает следующий тап, когда площадок несколько. */
    activeArenaTab: null,
    /* Площадки, отмеченные во втором шаге, — один список вместо режимов «одна / несколько».
       arenaMode и activeArenaTab — производные (syncArenaDerived). */
    pickedArenaIds: [],
    /* Map<dayOfWeek, {минута старта: {a: площадка|null, d: длительность|null}}>. Точные старты:
       своя минута (13:25) и вторая площадка в тот же день хранятся как есть и уходят на
       сервер нетронутыми — отдельного «перенесённого» больше нет. */
    week: {},
    weekIsSuggestion: false,
    weekTouched: false,
    /* Раскрытое окно недели: 'день:окно' (например, '0:eve'). */
    openWindow: null,
    durationMinutes: 60,
    /* 0 — вступление, 1–3 — шаги. */
    step: 0,
    done: false,
    firstName: '',
    lastName: '',
    photoUrl: null,
    alreadyDone: false,
    busy: false,
    /* Bumped on every city change / arena create so a stale in-flight quick-setup refetch
       (see afterCreatedArena) can detect it is no longer current and skip applying itself. */
    arenaRefreshToken: 0,
    /* One key per open create-form session (see openArenaCreate) — reused across retries
       (double-tap, "создать всё равно" after a duplicate warning) so the server treats them
       as one logical submit; there is no DB uniqueness constraint on `arenas`. */
    arenaCreateIdemKey: null,
    /* Причина последнего неудачного сохранения. Живёт в состоянии, а не только в
       DOM: syncCta() в конце вызывает note(''), и ошибка, поставленная в catch,
       затиралась следующей же строкой — экран молча возвращался в исходный вид,
       и «Готово» выглядела так, будто ничего не произошло. */
    submitError: null,
  };

  var el = {};
  function byId(id) { return document.getElementById(id); }

  function cacheEls() {
    [
      'obLoading', 'obFatal', 'obIntro', 'obSetup', 'obDone', 'obFoot', 'obCta', 'obNote', 'obSkip',
      'obBack', 'obProgress', 'obStepCount', 'obPreview', 'obPreviewLine', 'obPreviewTimes',
      'obStep1', 'obStep2', 'obStep3', 'obRoleValue', 'obRoleEdit', 'obRoleBox',
      'obServices', 'obDuration', 'obDurationLockedNote',
      'obCity', 'obCityWrap', 'obArenaNeedCity', 'obArenaOnlineNote', 'obArenaBrowseHint',
      'obArenaSearch', 'obArenaList',
      'obCityAddBtn', 'obCityCreateWrap', 'obCityCreateName', 'obCityCreateStatus',
      'obCityCreateSubmit', 'obCityCreateCancel',
      'obArenaTabs',
      'obArenaCreateWrap', 'obArenaCreateName', 'obArenaCreateAddress',
      'obArenaCreateStatus', 'obArenaCreateDup', 'obArenaCreateSubmit', 'obArenaCreateCancel',
      'obArenaCreateLead',
      'obShell', 'obWeek', 'obWindowPanel', 'obWindowTitle', 'obWindowClear', 'obWindowSlots',
      'obWeekHint', 'obWeekSummary',
      'obDoneTitle', 'obDoneLead', 'obDoneScheduleLink', 'obDonePricesBtn',
      'obRole', 'obRoleCustomWrap', 'obRoleCustom',
      'obRoleAddBtn', 'obRoleAddSubmit', 'obRoleAddCancel', 'obRoleAddStatus',
      'obServiceAddWrap', 'obServiceAddInput',
      'obServiceAddSubmit', 'obServiceAddCancel', 'obServiceAddStatus',
      'obServiceFormats', 'obServiceAddFormat', 'obArenaCreateType',
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

  /* ── Кто вы: роль специалиста ── */

  function renderRole() {
    if (!el.obRole) return;
    el.obRole.innerHTML = '';
    var suggestions = state.roleSuggestions || [];
    suggestions.forEach(function (label) {
      el.obRole.appendChild(roleChip(label, false));
    });
    /* Свои роли вне подсказок — отдельные чипы с ✕. */
    (state.selectedRoles || []).forEach(function (label) {
      if (suggestions.indexOf(label) < 0) {
        el.obRole.appendChild(roleChip(label, true));
      }
    });
    if (el.obRoleAddBtn) {
      var rolePanelOpen = el.obRoleCustomWrap && !el.obRoleCustomWrap.hidden;
      el.obRoleAddBtn.hidden = rolePanelOpen || !canAddMoreRoles();
    }
    syncRoleLine();
  }

  /* Роль — не отдельный вопрос, а строка под карточкой: пустая роль читается сервером как
     «Тренер», и так же её показываем. Поменять — «Изменить», чипы те же, что были. */
  function syncRoleLine() {
    if (!el.obRoleValue) return;
    var roles = state.selectedRoles || [];
    el.obRoleValue.textContent = roles.length ? roles.join(' · ') : 'Тренер';
  }

  function toggleRoleBox() {
    if (!el.obRoleBox) return;
    var open = el.obRoleBox.hidden;
    el.obRoleBox.hidden = !open;
    if (el.obRoleEdit) {
      el.obRoleEdit.setAttribute('aria-expanded', open ? 'true' : 'false');
      el.obRoleEdit.textContent = open ? 'Готово' : 'Изменить';
    }
    haptic('light');
  }

  function canAddMoreRoles() {
    return (state.selectedRoles || []).length < MAX_SPECIALIST_ROLES;
  }

  function rolesLimitMessage() {
    return 'Не больше ' + MAX_SPECIALIST_ROLES + ' специальностей.';
  }

  /** Добавить роль в выбор; false, если упёрлись в лимит. */
  function trySelectRole(label) {
    if (state.selectedRoles.indexOf(label) >= 0) return true;
    if (!canAddMoreRoles()) {
      roleAddNote(rolesLimitMessage(), true);
      if (el.obRoleCustomWrap && el.obRoleCustomWrap.hidden) {
        note(rolesLimitMessage(), true);
      }
      return false;
    }
    state.selectedRoles.push(label);
    return true;
  }

  function roleChip(label, isCustom) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'ob-chip';
    b.textContent = isCustom ? label + ' ✕' : label;
    var on = state.selectedRoles.indexOf(label) >= 0;
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    if (isCustom) b.title = 'Убрать «' + label + '»';
    b.onclick = function () {
      if (isCustom) {
        state.selectedRoles = state.selectedRoles.filter(function (r) { return r !== label; });
        syncRoleIsCustomFlag();
      } else {
        var i = state.selectedRoles.indexOf(label);
        if (i >= 0) {
          state.selectedRoles.splice(i, 1);
          roleAddNote('');
        } else if (trySelectRole(label)) {
          roleAddNote('');
        }
      }
      renderRole();
      haptic('light');
    };
    return b;
  }

  function syncRoleIsCustomFlag() {
    var suggestions = state.roleSuggestions || [];
    state.roleIsCustom = (state.selectedRoles || []).some(function (r) {
      return suggestions.indexOf(r) < 0;
    });
  }

  function openRoleAdd() {
    if (!canAddMoreRoles()) {
      note(rolesLimitMessage(), true);
      return;
    }
    if (el.obRoleCustomWrap) el.obRoleCustomWrap.hidden = false;
    if (el.obRoleAddBtn) el.obRoleAddBtn.hidden = true;
    if (el.obRoleCustom) el.obRoleCustom.focus();
  }

  function closeRoleAdd() {
    if (el.obRoleCustomWrap) el.obRoleCustomWrap.hidden = true;
    if (el.obRoleCustom) el.obRoleCustom.value = '';
    roleAddNote('');
    renderRole();
  }

  function roleAddNote(text, isError) {
    if (!el.obRoleAddStatus) return;
    el.obRoleAddStatus.hidden = !text;
    el.obRoleAddStatus.textContent = text || '';
    el.obRoleAddStatus.classList.toggle('is-error', !!isError);
  }

  function addCustomRole() {
    var raw = (el.obRoleCustom && el.obRoleCustom.value ? el.obRoleCustom.value : '').trim();
    if (!raw) {
      roleAddNote('Напишите, кем вы себя называете.', true);
      return;
    }
    if (raw.length > 64) {
      roleAddNote('Не длиннее 64 символов.', true);
      return;
    }
    /* Совпало с подсказкой — выбираем её, а не плодим второй чип с тем же смыслом. */
    var match = (state.roleSuggestions || []).filter(function (r) {
      return r.toLowerCase() === raw.toLowerCase();
    })[0];
    if (match) {
      if (!trySelectRole(match)) return;
    } else if (state.selectedRoles.indexOf(raw) < 0) {
      if (!trySelectRole(raw)) return;
    }
    syncRoleIsCustomFlag();
    closeRoleAdd();
    renderRole();
    syncCta();
    haptic('light');
  }

  function currentRolesPayload() {
    return state.selectedRoles.length ? state.selectedRoles.slice() : [];
  }

  /* ── Свои услуги ── */

  function openServiceAdd() {
    state.newCustomServiceOnline = false;
    if (el.obServiceAddFormat) {
      bindFormatPair(el.obServiceAddFormat, false, function (online) {
        state.newCustomServiceOnline = !!online;
      });
    }
    if (el.obServiceAddWrap) el.obServiceAddWrap.hidden = false;
    if (el.obServiceAddBtn) el.obServiceAddBtn.hidden = true;
    if (el.obServiceAddInput) el.obServiceAddInput.focus();
  }

  function closeServiceAdd() {
    if (el.obServiceAddWrap) el.obServiceAddWrap.hidden = true;
    if (el.obServiceAddInput) el.obServiceAddInput.value = '';
    state.newCustomServiceOnline = false;
    serviceAddNote('');
    renderServices();
  }

  function serviceAddNote(text, isError) {
    if (!el.obServiceAddStatus) return;
    el.obServiceAddStatus.hidden = !text;
    el.obServiceAddStatus.textContent = text || '';
    el.obServiceAddStatus.classList.toggle('is-error', !!isError);
  }

  /*
   * Вписанная услуга кладётся в state и рисуется чипом сразу, до сохранения:
   * id ей выдаст сервер при отправке формы (там же дедуп — «ОФП» и «офп»
   * не должны стать двумя услугами). Поэтому здесь только имя.
   */
  function addCustomService() {
    var raw = (el.obServiceAddInput && el.obServiceAddInput.value ? el.obServiceAddInput.value : '').trim();
    if (!raw) {
      serviceAddNote('Напишите название услуги.', true);
      return;
    }
    if (raw.length > 128) {
      serviceAddNote('Название — не длиннее 128 символов.', true);
      return;
    }
    var key = raw.toLowerCase().replace(/ё/g, 'е').replace(/[^\wа-я\s]/gi, ' ').replace(/\s+/g, ' ').trim();
    var dupInList = state.services.some(function (svc) {
      var n = String(svc.name || '').toLowerCase().replace(/ё/g, 'е')
        .replace(/[^\wа-я\s]/gi, ' ').replace(/\s+/g, ' ').trim();
      return n === key;
    });
    var dupInCustom = state.customServiceNames.some(function (n) {
      return n.toLowerCase().replace(/ё/g, 'е') === raw.toLowerCase().replace(/ё/g, 'е');
    });
    if (dupInList || dupInCustom) {
      serviceAddNote('Такое занятие уже есть в списке — отметьте его плиткой.', true);
      return;
    }
    if (state.customServiceNames.length >= 5) {
      serviceAddNote('Можно добавить не больше 5 своих услуг.', true);
      return;
    }
    state.customServiceNames.push(raw);
    state.customServiceOnlineByName[raw] = !!state.newCustomServiceOnline;
    closeServiceAdd();
    renderServices();
    syncOnlineArenaWithServices({ fromFormat: true });
    syncCta();
    haptic('light');
  }

  function bindFormatPair(container, isOnline, onChange) {
    if (!container) return;
    container.querySelectorAll('[data-online]').forEach(function (btn) {
      var online = btn.getAttribute('data-online') === '1';
      btn.setAttribute('aria-pressed', (online === !!isOnline) ? 'true' : 'false');
      btn.onclick = function () {
        onChange(online);
        container.querySelectorAll('[data-online]').forEach(function (b) {
          b.setAttribute(
            'aria-pressed',
            (b.getAttribute('data-online') === '1') === !!online ? 'true' : 'false'
          );
        });
        haptic('light');
      };
    });
  }


  function selectedOfferCount() {
    return state.selectedServices.length + state.customServiceNames.length;
  }

  /** Every selected/custom offer is online (and at least one exists). */
  function allSelectedOffersOnline() {
    if (!selectedOfferCount()) return false;
    var i;
    for (i = 0; i < state.selectedServices.length; i++) {
      if (!state.serviceOnlineById[state.selectedServices[i]]) return false;
    }
    for (i = 0; i < state.customServiceNames.length; i++) {
      if (!state.customServiceOnlineByName[state.customServiceNames[i]]) return false;
    }
    return true;
  }

  function serviceAllowsOnline(svc) {
    return !!(svc && svc.allows_online);
  }

  function syncOnlineArenaWithServices(opts) {
    opts = opts || {};
    var fromFormat = !!opts.fromFormat;
    if (allSelectedOffersOnline()) {
      /* Exclusive «онлайн» only when not already picking venues (hybrid OK). */
      if (state.arenaMode === 'none') {
        state.arenaMode = 'online';
        state.pickedArenaIds = [];
        syncArenaDerived();
        setAllSlotsArena(null);
        renderArenaStep();
        renderArenaList();
        renderArenaTabs();
        syncDurationLock();
        renderWeek();
        submitArenaOnlineFormat();
      }
    } else if (state.arenaMode === 'online' && fromFormat) {
      state.arenaMode = 'none';
      renderArenaStep();
      renderArenaTabs();
      syncDurationLock();
      renderWeek();
      clearArenaOnlineFormat();
    }
    syncCta();
  }

  function renderServiceFormats() {
    var box = el.obServiceFormats;
    if (!box) return;
    box.innerHTML = '';
    var rows = [];
    state.selectedServices.forEach(function (sid) {
      var svc = state.services.find(function (s) { return s.id === sid; });
      if (!serviceAllowsOnline(svc)) return;
      rows.push({
        key: 'id:' + sid,
        name: (svc && svc.name) || ('Услуга #' + sid),
        online: !!state.serviceOnlineById[sid],
        setOnline: function (v) { state.serviceOnlineById[sid] = !!v; },
      });
    });
    state.customServiceNames.forEach(function (name) {
      rows.push({
        key: 'custom:' + name,
        name: name,
        online: !!state.customServiceOnlineByName[name],
        setOnline: function (v) { state.customServiceOnlineByName[name] = !!v; },
      });
    });
    box.hidden = rows.length === 0;
    rows.forEach(function (row) {
      var wrap = document.createElement('div');
      wrap.className = 'ob-svc-format-row';
      var nm = document.createElement('span');
      nm.className = 'ob-svc-format-row__name';
      nm.textContent = row.name;
      wrap.appendChild(nm);
      [
        { online: false, label: 'На площадке' },
        { online: true, label: 'Онлайн' },
      ].forEach(function (opt) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'ob-chip';
        b.setAttribute('data-online', opt.online ? '1' : '0');
        b.setAttribute('aria-pressed', (opt.online === row.online) ? 'true' : 'false');
        b.textContent = opt.label;
        b.onclick = function () {
          row.setOnline(opt.online);
          wrap.querySelectorAll('[data-online]').forEach(function (x) {
            x.setAttribute(
              'aria-pressed',
              (x.getAttribute('data-online') === '1') === !!opt.online ? 'true' : 'false'
            );
          });
          syncOnlineArenaWithServices({ fromFormat: true });
          haptic('light');
        };
        wrap.appendChild(b);
      });
      box.appendChild(wrap);
    });
  }

  /* Иконка плитки по названию услуги. Список закрытый и весь про лёд — сопоставление по
     корню слова надёжнее id: id на стендах разные. Незнакомое — конёк. */
  var ICON_SKATE = 'M6 4v10h10a3 3 0 0 0 3-3l-6-2V4z M4 18h16';
  var SERVICE_ICONS = [
    [/нул/i, ICON_SKATE],
    [/совершенств/i, 'M4 17l6-6 4 4 6-6 M14 9h6v6'],
    [/фигур/i, 'M12 12a1.5 1.5 0 1 1 1.5 1.5a3.5 3.5 0 1 1 3.5-3.5a5.5 5.5 0 1 1-5.5-5.5a7.5 7.5 0 0 1 7.5 7.5'],
    [/охм|мастерств/i, 'M12 4a8 8 0 1 0 0 16a8 8 0 1 0 0-16z M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8z'],
    [/хокке/i, 'M16 3l-5 14H5 M5 17v2h6 M14 19a3 1.5 0 1 0 6 0a3 1.5 0 1 0-6 0'],
    [/ролик/i, 'M6 3v10h10a3 3 0 0 0 3-3l-6-2V3z M5 16h15 M6 19a2 2 0 1 0 4 0a2 2 0 1 0-4 0 M14 19a2 2 0 1 0 4 0a2 2 0 1 0-4 0'],
    [/офп|сфп|физ/i, 'M6 8v8 M18 8v8 M3 10v4 M21 10v4 M6 12h12'],
  ];
  var ICON_CUSTOM = 'M5 5h14v14H5z M9 12h6';
  var ICON_PLUS = 'M12 5v14 M5 12h14';
  var ICON_CHECK = 'M5 12l5 5 9-10';
  var ICON_CROSS = 'M7 7l10 10 M17 7L7 17';

  function svgIcon(d, size, strokeWidth) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('width', String(size || 24));
    svg.setAttribute('height', String(size || 24));
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', String(strokeWidth || 1.8));
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    var p = document.createElementNS(ns, 'path');
    p.setAttribute('d', d);
    svg.appendChild(p);
    return svg;
  }

  function serviceIcon(name) {
    for (var i = 0; i < SERVICE_ICONS.length; i++) {
      if (SERVICE_ICONS[i][0].test(name || '')) return SERVICE_ICONS[i][1];
    }
    return ICON_SKATE;
  }

  /** «ОХМ(отработка хоккейного мастерства)» → заголовок «ОХМ» и подпись под ним. */
  function splitServiceName(name) {
    var m = /^(.+?)\s*\((.+)\)\s*$/.exec(String(name || ''));
    return m ? { title: glueShortWords(m[1]), sub: glueShortWords(m[2]) } : { title: glueShortWords(name), sub: '' };
  }

  /* «катанию «с нуля»» не должно рваться после «с»: короткий предлог держится за следующее слово. */
  function glueShortWords(text) {
    return String(text || '').replace(/(^|[\s«(])(с|в|к|и|о|у|на|по|до|за|от|для)\s+/gi, '$1$2\u00a0');
  }

  function serviceTile(opts) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'ob-tile' + (opts.add ? ' ob-tile--add' : '');
    if (!opts.add) b.setAttribute('aria-pressed', opts.on ? 'true' : 'false');
    if (opts.label) b.setAttribute('aria-label', opts.label);
    b.appendChild(svgIcon(opts.icon));
    var nm = document.createElement('span');
    nm.className = 'ob-tile__name';
    nm.textContent = opts.title;
    if (opts.sub) {
      var sub = document.createElement('span');
      sub.className = 'ob-tile__sub';
      sub.textContent = opts.sub;
      nm.appendChild(sub);
    }
    b.appendChild(nm);
    if (!opts.add) {
      var check = document.createElement('span');
      check.className = 'ob-tile__check';
      check.appendChild(svgIcon(opts.custom ? ICON_CROSS : ICON_CHECK, 12, 3));
      b.appendChild(check);
    }
    b.onclick = opts.onClick;
    return b;
  }

  /* ── Услуги: плитки ── */
  function renderServices() {
    if (!el.obServices) return;
    el.obServices.innerHTML = '';
    state.services.forEach(function (svc) {
      var parts = splitServiceName(svc.name);
      var on = state.selectedServices.indexOf(svc.id) >= 0;
      el.obServices.appendChild(serviceTile({
        icon: serviceIcon(svc.name),
        title: parts.title,
        sub: parts.sub,
        on: on,
        label: svc.name,
        onClick: function () {
          var i = state.selectedServices.indexOf(svc.id);
          if (i >= 0) {
            state.selectedServices.splice(i, 1);
            delete state.serviceOnlineById[svc.id];
          } else {
            state.selectedServices.push(svc.id);
            if (state.serviceOnlineById[svc.id] == null) state.serviceOnlineById[svc.id] = false;
          }
          haptic('light');
          renderServices();
          syncOnlineArenaWithServices({ fromFormat: true });
          renderPreview();
          syncCta();
        },
      }));
    });

    /* Вписанные, но ещё не сохранённые услуги. Всегда выбраны — тренер только что
       сам их назвал; тап снимает не выбор, а саму услугу, поэтому крестик. */
    state.customServiceNames.forEach(function (name, idx) {
      el.obServices.appendChild(serviceTile({
        icon: ICON_CUSTOM,
        title: name,
        sub: state.customServiceOnlineByName[name] ? 'своё · онлайн' : 'своё',
        on: true,
        custom: true,
        label: 'Убрать «' + name + '»',
        onClick: function () {
          var removed = state.customServiceNames.splice(idx, 1)[0];
          if (removed) delete state.customServiceOnlineByName[removed];
          renderServices();
          renderPreview();
          syncCta();
          haptic('light');
        },
      }));
    });

    var addOpen = el.obServiceAddWrap && !el.obServiceAddWrap.hidden;
    if (!addOpen) {
      el.obServices.appendChild(serviceTile({
        add: true,
        icon: ICON_PLUS,
        title: 'Своё занятие',
        onClick: function () { openServiceAdd(); renderServices(); },
      }));
    }
    renderServiceFormats();
  }

  function renderDuration() {
    if (!el.obDuration) return;
    /* Значение из профиля может не совпасть ни с одним вариантом (тренер менял его в
       настройках) — тогда показываем и его, чтобы выбор не «перескочил» молча на соседнее. */
    var options = DURATIONS.slice();
    if (options.indexOf(state.durationMinutes) < 0) {
      options.push(state.durationMinutes);
      options.sort(function (a, b) { return a - b; });
    }
    el.obDuration.innerHTML = '';
    options.forEach(function (mins) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = mins + ' мин';
      b.setAttribute('aria-pressed', state.durationMinutes === mins ? 'true' : 'false');
      b.onclick = function () {
        if (state.durationMinutes === mins) return;
        state.durationMinutes = mins;
        haptic('light');
        renderDuration();
        onDurationChanged();
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

  /** Площадки, отмеченные во втором шаге: [] / [одна] / до трёх. */
  function activeArenas() {
    return state.pickedArenaIds.map(arenaById).filter(function (a) { return !!a; });
  }

  /** Площадка, которой отмечается время прямо сейчас: единственная или выбранная над сеткой. */
  function currentBrushArena() {
    if (!state.pickedArenaIds.length) return null;
    return arenaById(state.activeArenaTab);
  }


  /* Порядковый индекс площадки среди отмеченных — держит цвет точки стабильным, пока саму
     площадку не сняли. */
  function arenaColorIndex(arenaId) {
    var i = state.pickedArenaIds.indexOf(arenaId);
    return i >= 0 ? i : 0;
  }


  function arenaMetaLabel(arena) {
    var bits = [];
    if (arena.address) bits.push(arena.address);
    else if (arena.city_name) bits.push(arena.city_name);
    var off = arenaOffset(arena);
    if (off) {
      bits.push('слоты с :' + (off < 10 ? '0' + off : off) + ' каждого часа');
    }
    if (arena.fixed_duration_minutes) {
      bits.push(arena.fixed_duration_minutes + ' мин фиксированно');
    }
    return bits.join(' · ');
  }

  function arenasInSelectedCity() {
    if (state.cityId == null) return [];
    return state.arenas.filter(function (a) {
      return Number(a.city_id) === Number(state.cityId);
    });
  }

  function filteredArenas(query) {
    var pool = arenasInSelectedCity();
    var q = (query || '').trim().toLowerCase();
    if (!q) return [];
    return pool.filter(function (a) {
      return (a.name || '').toLowerCase().indexOf(q) >= 0 ||
        (a.address || '').toLowerCase().indexOf(q) >= 0;
    });
  }

  function sortArenasByName(list) {
    return list.slice().sort(function (a, b) {
      return (a.name || '').localeCompare(b.name || '', 'ru');
    });
  }

  function arenasForPicker(query, isSelected) {
    var pool = sortArenasByName(arenasInSelectedCity());
    var q = (query || '').trim();
    if (q) {
      var filtered = filteredArenas(q);
      return {
        items: filtered,
        total: pool.length,
        shown: filtered.length,
        truncated: false,
      };
    }
    var picked = [];
    var rest = [];
    pool.forEach(function (a) {
      if (isSelected(a.id)) picked.push(a);
      else rest.push(a);
    });
    var seen = {};
    var items = [];
    picked.forEach(function (a) {
      if (seen[a.id]) return;
      seen[a.id] = true;
      items.push(a);
    });
    rest.forEach(function (a) {
      if (items.length >= ARENA_BROWSE_CAP) return;
      if (seen[a.id]) return;
      seen[a.id] = true;
      items.push(a);
    });
    return {
      items: items,
      total: pool.length,
      shown: items.length,
      truncated: pool.length > items.length,
    };
  }

  function syncArenaBrowseHint(hintEl, meta, q) {
    if (!hintEl) return;
    if (q || state.cityId == null) {
      hintEl.hidden = true;
      hintEl.textContent = '';
      return;
    }
    if (!meta.total) {
      hintEl.textContent = 'В каталоге этого города пока нет площадок.';
      hintEl.hidden = false;
      return;
    }
    hintEl.textContent = meta.truncated
      ? ('Показано ' + meta.shown + ' из ' + meta.total + '. Остальные — через поиск.')
      : '';
    hintEl.hidden = !meta.truncated;
  }

  function arenaThumbUrl(arena) {
    var u = arena && arena.thumb_url;
    return u && String(u).trim() ? String(u).trim() : '';
  }

  function buildArenaThumbEl(arena) {
    var wrap = document.createElement('div');
    wrap.className = 'ob-arena-thumb';
    var url = arenaThumbUrl(arena);
    if (url) {
      var img = document.createElement('img');
      img.src = url;
      img.alt = '';
      img.loading = 'lazy';
      img.decoding = 'async';
      wrap.appendChild(img);
    } else {
      wrap.classList.add('ob-arena-thumb--ph');
      wrap.setAttribute('aria-hidden', 'true');
      wrap.textContent = (arena && arena.venue_chip) ? arena.venue_chip : '🏟';
    }
    var check = document.createElement('span');
    check.className = 'ob-arena-thumb__check';
    check.setAttribute('aria-hidden', 'true');
    check.textContent = '✓';
    wrap.appendChild(check);
    return wrap;
  }

  function appendArenaCreateCta(host, query) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'ob-arena-create-cta';
    var q = (query || '').trim();
    b.textContent = q ? ('Добавить «' + q + '»') : 'Моей площадки нет в списке';
    b.onclick = function () { openArenaCreate(q); };
    host.appendChild(b);
  }

  function renderArenaOptionsInto(host, query, isSelected, onPick, browseHintEl) {
    if (!host) return;
    var q = (query || '').trim();
    var meta = arenasForPicker(query, isSelected);
    var list = meta.items;
    syncArenaBrowseHint(browseHintEl, meta, q);
    host.innerHTML = '';
    if (!list.length) {
      var empty = document.createElement('div');
      empty.className = 'ob-arena-empty';
      empty.textContent = q
        ? 'Площадок не найдено.'
        : 'В каталоге этого города пока нет площадок.';
      host.appendChild(empty);
      appendArenaCreateCta(host, q);
      return;
    }
    list.forEach(function (a) {
      var selected = isSelected(a.id);
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-arena-row' + (selected ? ' is-on' : '');
      b.setAttribute('role', 'option');
      b.setAttribute('aria-selected', selected ? 'true' : 'false');
      b.setAttribute('aria-pressed', selected ? 'true' : 'false');
      b.appendChild(buildArenaThumbEl(a));
      var body = document.createElement('div');
      body.className = 'ob-arena-row__body';
      var nameEl = document.createElement('span');
      nameEl.className = 'ob-arena-option__name';
      nameEl.textContent = a.name;
      if (a.is_confirmed === false) {
        nameEl.appendChild(document.createTextNode(' '));
        var badge = document.createElement('span');
        badge.className = 'ob-arena-unconfirmed-badge';
        badge.textContent = 'на проверке';
        nameEl.appendChild(badge);
      }
      body.appendChild(nameEl);
      var meta = arenaMetaLabel(a);
      if (meta) {
        var metaEl = document.createElement('span');
        metaEl.className = 'ob-arena-option__meta';
        metaEl.textContent = meta;
        body.appendChild(metaEl);
      }
      b.appendChild(body);
      b.onclick = function () { onPick(a.id); };
      host.appendChild(b);
    });
    appendArenaCreateCta(host, q);
  }

  function renderArenaList() {
    var q = el.obArenaSearch ? el.obArenaSearch.value : '';
    renderArenaOptionsInto(
      el.obArenaList,
      q,
      function (id) { return state.pickedArenaIds.indexOf(id) >= 0; },
      togglePickedArena,
      el.obArenaBrowseHint
    );
  }


  /*
   * Клавиатура на телефоне. Telegram не сжимает страницу под клавиатуру: поле уезжает под неё,
   * а закреплённая кнопка внизу ложится поверх. Поэтому одно правило на все поля экрана —
   * роль, своё занятие, город, поиск и создание площадки:
   *   - пока поле в фокусе, кнопки внизу нет (.ob-kb), а снизу есть запас прокрутки на высоту
   *     клавиатуры (--ob-kb-pad, из visualViewport; без него — половина экрана);
   *   - поле прокручивается в видимую часть: по центру, поиск площадки — к верху, чтобы под ним
   *     был виден список (data-ob-reveal="start");
   *   - тап мимо поля и его панели убирает клавиатуру.
   */
  var kbRevealT = null;

  function isTextField(node) {
    if (!node || !node.tagName) return false;
    if (node.tagName === 'TEXTAREA') return true;
    if (node.tagName !== 'INPUT') return false;
    var t = (node.getAttribute('type') || 'text').toLowerCase();
    return ['text', 'search', 'tel', 'email', 'number', 'url'].indexOf(t) >= 0;
  }

  function keyboardInset() {
    var vv = window.visualViewport;
    if (!vv) return 0;
    return Math.max(0, Math.round(window.innerHeight - vv.height - (vv.offsetTop || 0)));
  }

  function revealField(node, delay) {
    if (kbRevealT) clearTimeout(kbRevealT);
    kbRevealT = setTimeout(function () {
      kbRevealT = null;
      if (document.activeElement !== node) return;
      var inset = keyboardInset();
      document.body.style.setProperty('--ob-kb-pad', inset > 80 ? (inset + 24) + 'px' : '50vh');
      var target = node.getAttribute('data-ob-reveal') === 'start' ? (node.closest('.ob-where-bar') || node) : node;
      try {
        target.scrollIntoView({ block: node.getAttribute('data-ob-reveal') === 'start' ? 'start' : 'center', behavior: 'smooth' });
      } catch (eS) { /* старый WebView */ }
    }, delay);
  }

  function hideKeyboard() {
    var ae = document.activeElement;
    if (isTextField(ae)) {
      try { ae.blur(); } catch (eB) { /* */ }
    }
    try {
      var tg = getTg();
      if (tg && typeof tg.hideKeyboard === 'function') tg.hideKeyboard();
    } catch (eTg) { /* */ }
  }

  function dismissArenaSearchKeyboard() {
    if (el.obArenaSearch && document.activeElement === el.obArenaSearch) hideKeyboard();
  }

  function bindKeyboardSafety() {
    if (document._obKeyboardBound) return;
    document._obKeyboardBound = true;
    document.addEventListener('focusin', function (e) {
      if (!isTextField(e.target)) return;
      document.body.classList.add('ob-kb');
      /* Дважды: сразу (Android уже сжал окно) и после анимации клавиатуры (iOS). */
      revealField(e.target, 60);
      setTimeout(function () { revealField(e.target, 0); }, 420);
    });
    document.addEventListener('focusout', function () {
      setTimeout(function () {
        if (isTextField(document.activeElement)) return;
        document.body.classList.remove('ob-kb');
      }, 120);
    });
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', function () {
        if (isTextField(document.activeElement)) revealField(document.activeElement, 50);
      });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || !isTextField(e.target)) return;
      hideKeyboard();
    });
    document.addEventListener(
      'touchstart',
      function (e) {
        var ae = document.activeElement;
        if (!isTextField(ae)) return;
        var t = e.target;
        if (isTextField(t)) return;
        var zone = ae.closest('.ob-addbox, .ob-arena-create, .ob-where-bar');
        if (zone && t && zone.contains(t)) return;
        if (ae === el.obArenaSearch && t && t.closest && t.closest('.ob-arena-list')) return;
        hideKeyboard();
      },
      { passive: true, capture: true }
    );
  }

  function bindArenaSearchMobile() {
    var inp = el.obArenaSearch;
    if (!inp || inp._obArenaMobileBound) return;
    inp._obArenaMobileBound = true;
    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        dismissArenaSearchKeyboard();
      }
    });
  }

  /* ── Неделя: доступ к стартам. state.week[dow] = { минута: { a: площадка, d: длительность } } ── */
  function dayMap(dow, create) {
    if (!state.week[dow] && create) state.week[dow] = {};
    return state.week[dow] || {};
  }

  function pruneEmptyDays() {
    Object.keys(state.week).forEach(function (dow) {
      if (!Object.keys(state.week[dow]).length) delete state.week[dow];
    });
  }

  function eachSlot(fn) {
    Object.keys(state.week).forEach(function (dow) {
      var day = state.week[dow];
      Object.keys(day).forEach(function (m) { fn(Number(dow), Number(m), day[m], day); });
    });
  }

  function setAllSlotsArena(arenaId) {
    eachSlot(function (dow, m, slot) { slot.a = arenaId; });
  }

  function removeArenaSlots(arenaId) {
    eachSlot(function (dow, m, slot, day) { if (slot.a === arenaId) delete day[m]; });
    pruneEmptyDays();
  }

  /**
   * Первая площадка забирает себе время, отмеченное «без площадки»: старт сдвигается на её
   * минутную сетку (:30), а то, что не помещается в её часы или налезает, — снимается.
   */
  function adoptUnassignedSlots(arena) {
    if (!arena) return;
    var off = WM.arenaOffset(arena);
    var dur = WM.effectiveDuration(arena, state.durationMinutes);
    Object.keys(state.week).forEach(function (dow) {
      var day = state.week[dow];
      var next = {};
      Object.keys(day).map(Number).sort(function (a, b) { return a - b; }).forEach(function (m) {
        var slot = day[m];
        if (slot.a != null) { next[m] = slot; return; }
        var start = (m % 60 === 0) ? m + off : m;
        var h = Math.floor(start / 60);
        if (arena.hour_start != null && h < arena.hour_start) return;
        if (arena.hour_end != null && h > arena.hour_end) return;
        if (next[start] || WM.overlapWith(next, start, dur, arenaById, state.durationMinutes) != null) return;
        next[start] = { a: arena.id, d: slot.d };
      });
      state.week[dow] = next;
    });
    pruneEmptyDays();
  }

  /** Производные поля режима площадок — из одного списка отмеченных. */
  function syncArenaDerived() {
    var ids = state.pickedArenaIds;
    if (state.arenaMode === 'online' && !ids.length) {
      state.activeArenaTab = null;
      return;
    }
    state.arenaMode = ids.length === 0 ? 'none' : (ids.length === 1 ? 'single' : 'multi');
    if (state.activeArenaTab == null || ids.indexOf(state.activeArenaTab) < 0) {
      state.activeArenaTab = ids.length ? ids[0] : null;
    }
  }

  /* Больше трёх площадок на одной неделе не различить точками, а в онбординге и не нужно:
     остальные тренер добавит в «Расписании». */
  var MAX_BRUSH_ARENAS = 3;

  /**
   * Одна галочка вместо развилки «одна / несколько / пока не указывать». Сняли единственную —
   * время остаётся «без площадки» (как раньше при «Пока не указывать»); сняли одну из
   * нескольких — уходит только её время: остальные дни уже размечены другими площадками.
   */
  function togglePickedArena(arenaId) {
    var ids = state.pickedArenaIds.slice();
    var i = ids.indexOf(arenaId);
    var wasOnline = state.arenaMode === 'online';
    if (i >= 0) {
      ids.splice(i, 1);
      if (ids.length) removeArenaSlots(arenaId);
      else setAllSlotsArena(null);
    } else {
      if (ids.length >= MAX_BRUSH_ARENAS) {
        note('Пока можно отметить не больше трёх площадок — остальные добавите в «Расписании».', true);
        return;
      }
      ids.push(arenaId);
      if (ids.length === 1 && !(state.weekIsSuggestion && !state.weekTouched)) {
        adoptUnassignedSlots(arenaById(arenaId));
      }
    }
    state.pickedArenaIds = ids;
    if (wasOnline && ids.length) state.arenaMode = 'single';
    syncArenaDerived();
    if (wasOnline && ids.length) clearArenaOnlineFormat();
    /* Нетронутая подсказка перестраивается по сетке первого катка; правленая неделя — нет. */
    refreshSuggestedWeek();
    state.openWindow = null;
    haptic('light');
    renderArenaList();
    renderArenaStep();
    renderArenaTabs();
    syncDurationLock();
    renderWeek();
    syncCta();
  }


  /* Больше трёх кистей на сетке не различить: цвет и буква на клетке 7×N клеток начинают
     повторяться, а не добавлять ясность. Честный ответ — не тащить в онбординг больше трёх,
     остальные площадки тренер добавит в «Расписании» уже после сохранения. */
  var MAX_BRUSH_ARENAS = 3;


  /* Кнопки над неделей — только при нескольких площадках: выбирают, чьё время отмечает
     следующий тап. Цвет точки тот же, что на окнах и слотах. */
  function renderArenaTabs() {
    if (!el.obArenaTabs) return;
    el.obArenaTabs.innerHTML = '';
    var ids = state.pickedArenaIds;
    if (ids.length < 2) {
      el.obArenaTabs.hidden = true;
      return;
    }
    el.obArenaTabs.hidden = false;
    ids.forEach(function (aid, idx) {
      var arena = arenaById(aid);
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-arena-tab';
      b.setAttribute('aria-pressed', state.activeArenaTab === aid ? 'true' : 'false');
      var dot = document.createElement('i');
      dot.className = 'ob-arena-tab__dot ob-dot-' + idx;
      b.appendChild(dot);
      var label = document.createElement('span');
      label.textContent = arena ? arena.name : ('Площадка #' + aid);
      b.appendChild(label);
      b.onclick = function () {
        if (state.activeArenaTab === aid) return;
        state.activeArenaTab = aid;
        haptic('light');
        renderArenaTabs();
        renderWeek();
      };
      el.obArenaTabs.appendChild(b);
    });
  }

  function renderCitySelect() {
    var sel = el.obCity;
    if (!sel) return;
    sel.innerHTML = '';
    var opt0 = document.createElement('option');
    opt0.value = '';
    opt0.textContent = 'Выберите город';
    sel.appendChild(opt0);
    (state.cities || []).forEach(function (c) {
      var o = document.createElement('option');
      o.value = String(c.id);
      o.textContent = c.name || '';
      sel.appendChild(o);
    });
    sel.value = state.cityId != null ? String(state.cityId) : '';
  }

  function cityNameById(id) {
    var n = Number(id);
    for (var i = 0; i < (state.cities || []).length; i++) {
      if (Number(state.cities[i].id) === n) return state.cities[i].name || '';
    }
    return '';
  }

  function dropArenasOutsideCity() {
    function inCity(id) {
      var a = arenaById(id);
      return !!(a && Number(a.city_id) === Number(state.cityId));
    }
    var before = state.pickedArenaIds.length;
    state.pickedArenaIds = state.pickedArenaIds.filter(inCity);
    eachSlot(function (dow, m, slot, day) {
      if (slot.a != null && !inCity(slot.a)) delete day[m];
    });
    pruneEmptyDays();
    syncArenaDerived();
    if (before !== state.pickedArenaIds.length) state.openWindow = null;
  }

  function setCityCreateStatus(text, isError) {
    if (!el.obCityCreateStatus) return;
    el.obCityCreateStatus.textContent = text || '';
    el.obCityCreateStatus.hidden = !text;
    el.obCityCreateStatus.classList.toggle('is-error', !!isError);
  }

  function closeCityCreate() {
    if (el.obCityCreateWrap) el.obCityCreateWrap.hidden = true;
    if (el.obCityCreateName) el.obCityCreateName.value = '';
    setCityCreateStatus('');
    if (el.obCityAddBtn) el.obCityAddBtn.hidden = false;
  }

  function openCityCreate() {
    closeArenaCreate();
    if (el.obCityCreateWrap) el.obCityCreateWrap.hidden = false;
    if (el.obCityAddBtn) el.obCityAddBtn.hidden = true;
    setCityCreateStatus('');
    if (el.obCityCreateName) {
      try { el.obCityCreateName.focus(); } catch (eF) { /* */ }
    }
  }

  function normalizeCityNameForMatch(name) {
    return String(name || '').trim().replace(/\s+/g, ' ').toLowerCase();
  }

  function findCityInListByName(name) {
    var key = normalizeCityNameForMatch(name);
    if (!key) return null;
    for (var i = 0; i < (state.cities || []).length; i++) {
      var c = state.cities[i];
      if (normalizeCityNameForMatch(c.name) === key) return c;
    }
    return null;
  }

  function cityPickedFeedback(name) {
    note('«' + (name || 'Город') + '» выбран', false);
    if (el.obCity) {
      el.obCity.classList.add('ob-city-select--picked');
      window.setTimeout(function () {
        if (el.obCity) el.obCity.classList.remove('ob-city-select--picked');
      }, 1600);
    }
    if (el.obCityWrap && typeof el.obCityWrap.scrollIntoView === 'function') {
      try { el.obCityWrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (eS) { /* */ }
    }
  }

  function afterCreatedCity(payload) {
    var cid = Number(payload.city_id);
    var name = payload.name || '';
    var exists = false;
    for (var i = 0; i < (state.cities || []).length; i++) {
      if (Number(state.cities[i].id) === cid) {
        exists = true;
        state.cities[i].name = name;
        state.cities[i].is_active = payload.is_active === true;
        break;
      }
    }
    if (!exists) {
      state.cities.push({
        id: cid,
        name: name,
        is_active: payload.is_active === true,
      });
    }
    closeCityCreate();
    cityPickedFeedback(name);
    setCity(String(cid), true);
  }

  function submitCityCreate() {
    var nm = el.obCityCreateName ? String(el.obCityCreateName.value || '').trim() : '';
    if (!nm) {
      setCityCreateStatus('Укажите название города.', true);
      return;
    }
    var dup = findCityInListByName(nm);
    if (dup) {
      haptic('light');
      afterCreatedCity({
        city_id: dup.id,
        name: dup.name,
        is_active: dup.is_active === true,
        status: dup.is_active === false ? 'existing_inactive' : 'existing_active',
      });
      return;
    }
    if (el.obCityCreateSubmit) el.obCityCreateSubmit.disabled = true;
    setCityCreateStatus('Добавляем…', false);
    fetch(apiUrl('/trainer/onboarding/city'), {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ name: nm }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok) {
            throw new Error(body && body.detail ? body.detail : 'Не удалось добавить город.');
          }
          return body;
        });
      })
      .then(function (body) {
        haptic('medium');
        afterCreatedCity(body);
      })
      .catch(function (err) {
        setCityCreateStatus((err && err.message) || 'Не удалось добавить город.', true);
      })
      .finally(function () {
        if (el.obCityCreateSubmit) el.obCityCreateSubmit.disabled = false;
      });
  }

  function setCity(raw, force) {
    var next = raw === '' || raw == null ? null : Number(raw);
    if (next != null && isNaN(next)) next = null;
    if (!force && next === state.cityId) {
      renderCitySelect();
      return;
    }
    state.cityId = next;
    state.arenaRefreshToken++;
    dropArenasOutsideCity();
    closeArenaCreate();
    closeCityCreate();
    haptic('light');
    renderCitySelect();
    renderArenaStep();
    renderArenaList();
    renderArenaTabs();
    renderWeek();
    syncCta();
  }

  function setArenaCreateStatus(text, isError) {
    if (!el.obArenaCreateStatus) return;
    el.obArenaCreateStatus.textContent = text || '';
    el.obArenaCreateStatus.hidden = !text;
    el.obArenaCreateStatus.classList.toggle('is-error', !!isError);
  }

  function closeArenaCreate() {
    if (el.obArenaCreateWrap) el.obArenaCreateWrap.hidden = true;
    if (el.obArenaCreateDup) {
      el.obArenaCreateDup.hidden = true;
      el.obArenaCreateDup.innerHTML = '';
    }
    setArenaCreateStatus('');
    state.arenaCreateIdemKey = null;
  }

  /*
   * Тип площадки в форме создания. До этого поля не было вообще, и любая новая
   * площадка молча становилась катком — так зал «Lifestyle» (#201) и попал
   * в ледовый каталог со снежинкой и «карточкой катка».
   */
  function renderVenueTypePicker() {
    if (!el.obArenaCreateType) return;
    el.obArenaCreateType.innerHTML = '';
    (state.venueTypes || []).forEach(function (vt) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-chip';
      b.textContent = (vt.icon ? vt.icon + ' ' : '') + vt.noun;
      b.setAttribute('aria-pressed', state.newArenaVenueType === vt.key ? 'true' : 'false');
      b.onclick = function () {
        state.newArenaVenueType = vt.key;
        renderVenueTypePicker();
        haptic('light');
      };
      el.obArenaCreateType.appendChild(b);
    });
  }

  function openArenaCreate(prefillName) {
    if (state.cityId == null) {
      note('Сначала выберите город.', true);
      return;
    }
    dismissArenaSearchKeyboard();
    closeCityCreate();
    state.arenaCreateIdemKey = 'arn' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
    if (el.obArenaCreateWrap) el.obArenaCreateWrap.hidden = false;
    if (el.obArenaCreateName) {
      el.obArenaCreateName.value = prefillName || el.obArenaCreateName.value || '';
    }
    if (el.obArenaCreateDup) {
      el.obArenaCreateDup.hidden = true;
      el.obArenaCreateDup.innerHTML = '';
    }
    setArenaCreateStatus('');
    /* Каждая новая форма начинается со льда: это по-прежнему подавляющее
       большинство площадок, и лишний тап им платить не за что. */
    state.newArenaVenueType = 'ice';
    renderVenueTypePicker();
    if (el.obArenaCreateName && !el.obArenaCreateName.value) {
      try { el.obArenaCreateName.focus(); } catch (eF) {}
    } else if (el.obArenaCreateAddress) {
      try { el.obArenaCreateAddress.focus(); } catch (eA) {}
    }
  }

  function selectCreatedArena(arenaId) {
    var id = Number(arenaId);
    if (state.pickedArenaIds.indexOf(id) < 0) togglePickedArena(id);
  }

  function afterCreatedArena(arenaId, payload) {
    var created = {
      id: Number(arenaId),
      name: (el.obArenaCreateName && el.obArenaCreateName.value) || '',
      address: (el.obArenaCreateAddress && el.obArenaCreateAddress.value) || '',
      city_id: state.cityId,
      city_name: cityNameById(state.cityId),
      grid_kind: 'quarter_15',
      minute_offset: 0,
      hour_start: 6,
      hour_end: 23,
      fixed_duration_minutes: null,
      is_confirmed: false,
      venue_type: (payload && payload.venue_type) || 'ice_rink',
      venue_chip: (payload && payload.venue_chip) || '🏒',
      thumb_url: (payload && payload.thumb_url) || null,
    };
    var exists = false;
    for (var i = 0; i < state.arenas.length; i++) {
      if (Number(state.arenas[i].id) === created.id) {
        exists = true;
        break;
      }
    }
    if (!exists) state.arenas.push(created);
    closeArenaCreate();
    selectCreatedArena(created.id);
    renderArenaList();
    renderArenaTabs();
    renderWeek();
    syncCta();
    /* Refresh grids from GET so a venue with a real preset replaces the stub. Guarded by a
       token: if the trainer changes city (or creates another arena) before this resolves, a
       stale response must not snap state.cityId / state.arenas back — same bug class already
       fixed once for citySel.onchange in the profile screen. */
    var refreshToken = ++state.arenaRefreshToken;
    fetch(apiUrl('/trainer/onboarding/quick-setup'), { headers: apiHeaders() })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || refreshToken !== state.arenaRefreshToken) return;
        if (data.arenas) state.arenas = data.arenas;
        if (data.cities) state.cities = data.cities;
        if (data.city_id != null) state.cityId = Number(data.city_id);
        renderCitySelect();
        renderArenaList();
        renderArenaTabs();
        renderWeek();
      })
      .catch(function () { /* stub already selected */ });
    void payload;
  }

  function submitArenaCreate(confirmDuplicate) {
    var nm = el.obArenaCreateName ? String(el.obArenaCreateName.value || '').trim() : '';
    var addr = el.obArenaCreateAddress ? String(el.obArenaCreateAddress.value || '').trim() : '';
    if (!state.cityId) {
      setArenaCreateStatus('Сначала выберите город.', true);
      return;
    }
    if (!nm || !addr) {
      setArenaCreateStatus(!nm ? 'Укажите название площадки.' : 'Укажите адрес площадки.', true);
      return;
    }
    if (el.obArenaCreateSubmit) el.obArenaCreateSubmit.disabled = true;
    setArenaCreateStatus('Добавляем…', false);
    if (!state.arenaCreateIdemKey) {
      state.arenaCreateIdemKey = 'arn' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
    }
    var idemHeaders = apiHeaders();
    idemHeaders['Idempotency-Key'] = state.arenaCreateIdemKey;
    fetch(apiUrl('/trainer/profile/arena-setup'), {
      method: 'POST',
      headers: idemHeaders,
      body: JSON.stringify({
        mode: 'create',
        arena_name: nm,
        address: addr,
        confirm_duplicate: !!confirmDuplicate,
        city_id: state.cityId,
        venue_type: state.newArenaVenueType || 'ice',
      }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, status: r.status, data: data };
        });
      })
      .then(function (o) {
        if (el.obArenaCreateSubmit) el.obArenaCreateSubmit.disabled = false;
        if (!o.ok) {
          var detail = o.data && o.data.detail;
          if (typeof detail !== 'string') detail = 'Не удалось добавить площадку.';
          setArenaCreateStatus(detail, true);
          return;
        }
        if (o.data && o.data.status === 'duplicate_warning') {
          renderArenaCreateDuplicates(o.data.duplicates || []);
          setArenaCreateStatus('Похожая площадка уже есть. Если это другая — добавьте всё равно.', true);
          return;
        }
        var arenaId = o.data && o.data.arena_id;
        if (!arenaId) {
          setArenaCreateStatus('Площадка создана, но не вернулся id — обновите экран.', true);
          return;
        }
        afterCreatedArena(arenaId, o.data);
      })
      .catch(function () {
        if (el.obArenaCreateSubmit) el.obArenaCreateSubmit.disabled = false;
        setArenaCreateStatus('Не удалось отправить. Проверьте соединение.', true);
      });
  }

  function renderArenaCreateDuplicates(dups) {
    if (!el.obArenaCreateDup) return;
    el.obArenaCreateDup.innerHTML = '';
    el.obArenaCreateDup.hidden = !(dups && dups.length);
    (dups || []).forEach(function (d) {
      var p = document.createElement('p');
      p.textContent = (d.name || 'Площадка') + (d.address ? (' · ' + d.address) : '');
      el.obArenaCreateDup.appendChild(p);
    });
    var again = document.createElement('button');
    again.type = 'button';
    again.className = 'ob-chip';
    again.textContent = 'Это другая — всё равно добавить';
    again.onclick = function () { submitArenaCreate(true); };
    el.obArenaCreateDup.appendChild(again);
  }

  function renderArenaStep() {
    var hasCity = state.cityId != null;
    if (el.obArenaNeedCity) el.obArenaNeedCity.hidden = hasCity;
    if (el.obArenaList) el.obArenaList.hidden = !hasCity;
    if (el.obArenaOnlineNote) el.obArenaOnlineNote.hidden = state.arenaMode !== 'online';
    if (!hasCity) closeArenaCreate();
  }

  function clearArenaOnlineFormat() {
    /* Leaving exclusive online — do not force services offline (hybrid allowed). */
    fetch(apiUrl('/trainer/profile/arena-setup'), {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ mode: 'clear' }),
    }).catch(function () { /* non-blocking */ });
  }

  /* «Онлайн» takes effect immediately (like arena create) rather than waiting for the final
     quick-setup submit — same endpoint the profile screen uses, client-visible: an "Онлайн"
     tag replaces the arena name on this trainer's card in «Лёд» (ice-tab-model.js). */
  function submitArenaOnlineFormat() {
    fetch(apiUrl('/trainer/profile/arena-setup'), {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ mode: 'online' }),
    })
      .then(function (r) { return r.ok ? null : Promise.reject(); })
      .catch(function () {
        note('Не удалось сохранить формат «Онлайн». Проверьте соединение и попробуйте ещё раз.', true);
      });
  }

  /* ── Неделя окнами: утро / день / вечер → точные старты ── */

  function totalSlots() {
    return WM.totalStarts(state.week);
  }

  function windowKey(dow, win) { return dow + ':' + win.id; }

  /**
   * Черновик недели для первого запуска: будни, два утренних и три вечерних занятия — те же,
   * что предлагает сервер (7, 8, 18, 19, 20 при 60 минутах), но по сетке катка: его смещение
   * (:15 у «Замка»), часы работы и длительность. Иначе подсказка стоит мимо слотов окна и сама
   * блокирует соседние.
   */
  function buildSuggestedWeek(arena) {
    var dur = WM.effectiveDuration(arena, state.durationMinutes);
    function pick(winId, from, count) {
      var starts = WM.windowStarts(WM.windowById(winId), arena, dur);
      var late = starts.filter(function (m) { return m >= from; });
      return (late.length >= count ? late : starts).slice(0, count);
    }
    var starts = pick('mor', 7 * 60, 2).concat(pick('eve', 18 * 60, 3));
    var week = {};
    for (var dow = 0; dow < 5; dow++) {
      var day = {};
      starts.forEach(function (m) { day[m] = { a: arena ? arena.id : null, d: null }; });
      week[dow] = day;
    }
    return week;
  }

  /** Подсказанная неделя, которую тренер ещё не трогал, следует за длительностью и катком. */
  function refreshSuggestedWeek() {
    if (!state.weekIsSuggestion || state.weekTouched) return false;
    state.week = buildSuggestedWeek(arenaById(state.pickedArenaIds[0]) || null);
    return true;
  }

  function onDurationChanged() {
    refreshSuggestedWeek();
    state.openWindow = null;
    renderWeek();
  }

  function syncWeekHint() {
    if (!el.obWeekHint) return;
    var bits = [];
    activeArenas().forEach(function (a) {
      var parts = [];
      var off = WM.arenaOffset(a);
      if (off) parts.push('с :' + (off < 10 ? '0' + off : off));
      if (a.fixed_duration_minutes) parts.push(a.fixed_duration_minutes + ' мин');
      if (parts.length) bits.push('«' + a.name + '» — занятия ' + parts.join(', '));
    });
    el.obWeekHint.textContent = bits.join('. ');
    el.obWeekHint.hidden = !bits.length;
  }

  function dotsFor(arenaIds) {
    var wrap = document.createElement('span');
    wrap.className = 'ob-win__dots';
    wrap.setAttribute('aria-hidden', 'true');
    arenaIds.forEach(function (aid) {
      var i = document.createElement('i');
      i.className = 'ob-dot-' + arenaColorIndex(aid);
      wrap.appendChild(i);
    });
    return wrap;
  }

  function renderWeek() {
    if (!el.obWeek) return;
    var brush = currentBrushArena();
    var dur = state.durationMinutes;
    var brushDur = WM.effectiveDuration(brush, dur);
    var multi = state.pickedArenaIds.length > 1;
    el.obWeek.innerHTML = '';

    var head = document.createElement('div');
    head.className = 'ob-week__row';
    head.appendChild(document.createElement('span'));
    WM.DAY_SHORT.forEach(function (label, idx) {
      var d = document.createElement('span');
      d.className = 'ob-week__dayhead' + (idx >= 5 ? ' is-weekend' : '');
      d.textContent = label;
      head.appendChild(d);
    });
    el.obWeek.appendChild(head);

    WM.WINDOWS.forEach(function (win) {
      var row = document.createElement('div');
      row.className = 'ob-week__row';
      var lab = document.createElement('span');
      lab.className = 'ob-week__label';
      lab.innerHTML = '<b></b><small></small>';
      lab.firstChild.textContent = win.label;
      lab.lastChild.textContent = win.from + '–' + win.to;
      row.appendChild(lab);

      for (var dow = 0; dow < 7; dow++) {
        (function (dow) {
          var day = dayMap(dow, false);
          var picked = WM.startsInWindow(day, win);
          var offered = WM.windowStarts(win, brush, brushDur);
          var full = picked.length > 0 && offered.length > 0 && offered.every(function (s) { return !!day[s]; });
          var key = windowKey(dow, win);
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'ob-win' +
            (picked.length ? (full ? ' is-full' : ' is-part') : '') +
            (state.openWindow === key ? ' is-open' : '');
          b.setAttribute('aria-pressed', picked.length ? 'true' : 'false');
          b.setAttribute('aria-label', WM.DAY_SHORT[dow] + ', ' + win.label.toLowerCase() + ': ' +
            (picked.length ? picked.map(WM.minuteLabel).join(', ') : 'не отмечено'));
          if (picked.length && !full) b.textContent = String(picked.length);
          if (!picked.length && !offered.length) b.disabled = true;
          if (multi && picked.length) {
            var arenasHere = [];
            picked.forEach(function (m) {
              var a = day[m].a;
              if (a != null && arenasHere.indexOf(a) < 0) arenasHere.push(a);
            });
            b.appendChild(dotsFor(arenasHere));
          }
          b.onclick = function () { tapWindow(dow, win); };
          row.appendChild(b);
        })(dow);
      }
      el.obWeek.appendChild(row);
    });

    renderWindowPanel();
    renderWeekSummary();
    syncWeekHint();
    renderPreview();
    syncCta();
  }

  /** Пустое окно — отметить целиком и раскрыть; отмеченное — раскрыть или свернуть. */
  function tapWindow(dow, win) {
    var key = windowKey(dow, win);
    var day = dayMap(dow, false);
    if (!WM.startsInWindow(day, win).length) {
      WM.fillWindow(dayMap(dow, true), win, currentBrushArena(), state.durationMinutes, arenaById);
      pruneEmptyDays();
      state.weekTouched = true;
      state.openWindow = key;
    } else {
      state.openWindow = state.openWindow === key ? null : key;
    }
    haptic('light');
    renderWeek();
  }

  function renderWindowPanel() {
    var panel = el.obWindowPanel;
    if (!panel) return;
    if (!state.openWindow) {
      panel.hidden = true;
      return;
    }
    var parts = state.openWindow.split(':');
    var dow = Number(parts[0]);
    var win = WM.windowById(parts[1]);
    var brush = currentBrushArena();
    var brushId = brush ? brush.id : null;
    var dur = state.durationMinutes;
    var brushDur = WM.effectiveDuration(brush, dur);
    var day = dayMap(dow, false);
    var multi = state.pickedArenaIds.length > 1;

    var starts = WM.windowStarts(win, brush, brushDur).concat(WM.startsInWindow(day, win));
    starts = starts.filter(function (m, i) { return starts.indexOf(m) === i; }).sort(function (a, b) { return a - b; });

    panel.hidden = false;
    if (el.obWindowTitle) el.obWindowTitle.textContent = WM.DAY_SHORT[dow] + ', ' + win.label.toLowerCase();
    if (!el.obWindowSlots) return;
    el.obWindowSlots.innerHTML = '';
    starts.forEach(function (m) {
      var slot = day[m];
      var mine = !slot || slot.a === brushId;
      var len = slot ? WM.slotDuration(slot, arenaById, dur) : brushDur;
      var blocked = slot ? !mine : WM.overlapWith(day, m, brushDur, arenaById, dur) != null;
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ob-slot';
      b.setAttribute('aria-pressed', slot ? 'true' : 'false');
      if (blocked) b.disabled = true;
      if (multi && slot && slot.a != null) {
        var dot = document.createElement('i');
        dot.className = 'ob-dot-' + arenaColorIndex(slot.a);
        b.appendChild(dot);
      }
      b.appendChild(document.createTextNode(WM.minuteLabel(m) + '–' + WM.minuteLabel(m + len)));
      var owner = slot && slot.a != null ? arenaById(slot.a) : null;
      b.setAttribute('aria-label', WM.minuteLabel(m) + '–' + WM.minuteLabel(m + len) +
        (owner && multi ? ', ' + owner.name : '') + (blocked && !slot ? ', пересекается с другим занятием' : ''));
      b.onclick = function () {
        WM.toggleStart(dayMap(dow, true), m, brush, dur, arenaById);
        pruneEmptyDays();
        state.weekTouched = true;
        haptic('light');
        renderWeek();
      };
      el.obWindowSlots.appendChild(b);
    });
  }

  function clearOpenWindow() {
    if (!state.openWindow) return;
    var parts = state.openWindow.split(':');
    var dow = Number(parts[0]);
    var win = WM.windowById(parts[1]);
    var brush = currentBrushArena();
    var only = state.pickedArenaIds.length > 1 ? (brush ? brush.id : null) : undefined;
    WM.clearWindow(dayMap(dow, false), win, only);
    pruneEmptyDays();
    state.weekTouched = true;
    state.openWindow = null;
    haptic('light');
    renderWeek();
  }

  function renderWeekSummary() {
    var box = el.obWeekSummary;
    if (!box) return;
    box.innerHTML = '';
    var rows = WM.weekSummary(state.week);
    if (!rows.length) {
      var empty = document.createElement('div');
      empty.className = 'ob-summary__row';
      empty.innerHTML = '<span></span>';
      empty.firstChild.textContent = 'Пока ничего не отмечено';
      empty.firstChild.style.color = 'var(--ob-muted)';
      box.appendChild(empty);
      return;
    }
    rows.forEach(function (r) {
      var row = document.createElement('div');
      row.className = 'ob-summary__row';
      row.innerHTML = '<span></span><span></span>';
      row.firstChild.textContent = r.days;
      row.lastChild.textContent = r.times;
      box.appendChild(row);
    });
  }

  /* ── Мини-карточка «как увидит ученик» ── */
  function initials() {
    var a = (state.firstName || '').trim().charAt(0);
    var b = (state.lastName || '').trim().charAt(0);
    return ((a + b) || 'Т').toUpperCase();
  }

  function timeChip(day, time, empty) {
    var t = document.createElement('span');
    t.className = 'ob-time' + (empty ? ' ob-time--empty' : '');
    t.innerHTML = '<small></small><b></b>';
    t.firstChild.textContent = day || '';
    t.lastChild.textContent = time;
    return t;
  }

  function previewLine() {
    var names = [];
    state.selectedServices.forEach(function (sid) {
      var svc = state.services.find(function (s) { return Number(s.id) === Number(sid); });
      if (svc) names.push(splitServiceName(svc.name).title);
    });
    state.customServiceNames.forEach(function (n) { names.push(n); });
    var what = names.slice(0, 2).join(' · ') + (names.length > 2 ? ' и ещё ' + (names.length - 2) : '');
    var where = activeArenas().map(function (a) { return '«' + a.name + '»'; }).join(', ');
    if (!where && state.arenaMode === 'online') where = 'онлайн';
    return { what: what, where: where };
  }

  function renderPreview() {
    var fullName = [state.firstName, state.lastName].filter(Boolean).join(' ');
    document.querySelectorAll('[data-ob-name]').forEach(function (n) { n.textContent = fullName || 'Ваше имя'; });
    document.querySelectorAll('[data-ob-avatar]').forEach(function (av) {
      if (av.dataset.obPhoto === (state.photoUrl || '')) {
        if (!state.photoUrl) av.textContent = initials();
        return;
      }
      av.dataset.obPhoto = state.photoUrl || '';
      av.textContent = '';
      if (state.photoUrl) {
        var img = document.createElement('img');
        img.src = state.photoUrl;
        img.alt = '';
        img.onerror = function () { av.textContent = initials(); };
        av.appendChild(img);
      } else {
        av.textContent = initials();
      }
    });

    var line = previewLine();
    if (el.obPreviewLine) {
      el.obPreviewLine.innerHTML = '';
      if (!line.what && !line.where) {
        el.obPreviewLine.innerHTML = '<span class="ob-card__blanks"><span class="ob-blank">что ведёте</span><span class="ob-blank">где</span></span>';
      } else {
        el.obPreviewLine.textContent = [line.what, line.where].filter(Boolean).join(' · ');
      }
    }

    var picks = WM.previewStarts(state.week, 3);
    document.querySelectorAll('[data-ob-times]').forEach(function (box) {
      box.innerHTML = '';
      var intro = box !== el.obPreviewTimes;
      for (var i = 0; i < 3; i++) {
        var p = intro ? null : picks[i];
        box.appendChild(p ? timeChip(p.day, p.time, false) : timeChip(intro ? ['чт', 'сб', 'вс'][i] : '', '—:—', true));
      }
    });
    if (el.obPreviewTimes) el.obPreviewTimes.hidden = state.step !== 3;
  }

  /* ── Шаги ── */
  function hasService() {
    return state.selectedServices.length > 0 || state.customServiceNames.length > 0;
  }

  function canGoBack() {
    return state.step > 1 || (state.step === 1 && !state.alreadyDone);
  }

  function syncTelegramBack() {
    var tg = getTg();
    if (!tg || !tg.BackButton) return;
    try {
      if (!state.done && canGoBack()) tg.BackButton.show();
      else tg.BackButton.hide();
    } catch (e) { /* старый клиент */ }
  }

  function showStep(n) {
    state.step = n;
    if (el.obIntro) el.obIntro.hidden = n !== 0;
    if (el.obSetup) el.obSetup.hidden = n === 0;
    [el.obStep1, el.obStep2, el.obStep3].forEach(function (pane, idx) {
      if (pane) pane.hidden = n !== idx + 1;
    });
    if (el.obProgress) {
      Array.prototype.forEach.call(el.obProgress.children, function (seg, idx) {
        seg.classList.toggle('is-on', idx < n);
      });
    }
    if (el.obStepCount) el.obStepCount.textContent = n ? n + '/3' : '';
    if (el.obBack) el.obBack.style.visibility = canGoBack() ? 'visible' : 'hidden';
    if (n !== 2) dismissArenaSearchKeyboard();
    state.submitError = null;
    syncTelegramBack();
    renderPreview();
    syncCta();
    try { window.scrollTo(0, 0); } catch (e) { /* */ }
  }

  function goBack() {
    if (state.busy || state.done) return;
    if (state.step > 1) showStep(state.step - 1);
    else if (state.step === 1 && !state.alreadyDone) showStep(0);
    haptic('light');
  }

  function goNext() {
    if (state.busy || state.done) return;
    if (state.step === 0) { showStep(1); haptic('light'); return; }
    if (state.step === 1) {
      if (!hasService()) { syncCta(); return; }
      showStep(2);
      haptic('light');
      return;
    }
    if (state.step === 2) { showStep(3); haptic('light'); return; }
    submit();
  }

  function onSkip() {
    if (state.busy || state.done) return;
    /* На шаге 3 пропуска нет: ссылка без единого времени — тупик для ученика, ему нечего
       выбрать. Подсказанная неделя уже отмечена, тренер только правит её. */
    if (state.step === 2) showStep(3);
  }

  function syncCta() {
    if (!el.obCta || state.done) return;
    var step = state.step;
    var skip = el.obSkip;
    if (skip) skip.hidden = true;
    el.obCta.disabled = !!state.busy;
    if (step === 0) {
      el.obCta.textContent = 'Начать';
      note('Около двух минут');
      return;
    }
    if (step === 1) {
      el.obCta.textContent = 'Дальше';
      /* Вписанная своя услуга — такой же ответ, как отмеченная плитка: специалиста
         смежной дисциплины, которому наш список не подошёл, не держим у закрытой кнопки. */
      if (!hasService()) {
        el.obCta.disabled = true;
        note('Отметьте хотя бы одно занятие');
      } else {
        note('');
      }
      return;
    }
    if (step === 2) {
      el.obCta.textContent = 'Дальше';
      if (skip && !state.pickedArenaIds.length && state.arenaMode !== 'online') {
        skip.hidden = false;
        skip.textContent = 'Пропустить';
      }
      note('');
      return;
    }
    /* Шаг 3. Хотя бы одно время — иначе по ссылке ученику нечего выбрать. */
    el.obCta.textContent = state.alreadyDone ? 'Сохранить' : 'Получить ссылку';
    if (!state.busy && totalSlots() === 0) {
      el.obCta.disabled = true;
      note('Отметьте хотя бы одно время — иначе ученику нечего выбрать');
      return;
    }
    if (state.busy) note('Сохраняем…');
    else if (state.submitError) note(state.submitError, true);
    else note('');
  }

  /* ── Загрузка ── */
  function load() {
    if (maybeRestoreDoneScreen()) return;
    fetch(apiUrl('/trainer/onboarding/quick-setup'), { headers: apiHeaders() })
      .then(function (r) {
        if (r.status === 403) throw new Error('forbidden');
        if (!r.ok) throw new Error('http_' + r.status);
        return r.json();
      })
      .then(function (data) {
        state.services = data.services || [];
        state.selectedServices = (data.selected_service_ids || []).slice();
        state.serviceOnlineById = {};
        (data.selected_services || []).forEach(function (item) {
          if (item && item.service_id != null) {
            var svc = state.services.find(function (s) { return s.id === item.service_id; });
            var online = !!item.is_online && serviceAllowsOnline(svc);
            state.serviceOnlineById[Number(item.service_id)] = online;
          }
        });
        state.selectedServices.forEach(function (sid) {
          if (state.serviceOnlineById[sid] == null) state.serviceOnlineById[sid] = false;
        });
        state.cities = data.cities || [];
        state.cityId = data.city_id != null ? Number(data.city_id) : null;
        state.arenas = data.arenas || [];
        state.durationMinutes = data.duration_minutes || 60;
        state.alreadyDone = !!data.already_done;
        /* Разбор недели: каждый сохранённый старт ложится как есть — со своей минутой,
           площадкой и длительностью. Отмеченные площадки — те, что встречаются в неделе. */
        var picked = [];
        state.week = {};
        (data.week || []).forEach(function (d) {
          var dow = d.day_of_week;
          if (!d.slots) {
            /* Старый ответ без slots — читаем часы, как читали раньше. */
            var legacyArena = d.arena_id != null ? d.arena_id : null;
            (d.hours || []).forEach(function (h) {
              dayMap(dow, true)[h * 60 + WM.arenaOffset(arenaById(legacyArena))] = { a: legacyArena, d: null };
            });
            if (legacyArena != null && picked.indexOf(legacyArena) < 0) picked.push(legacyArena);
            return;
          }
          d.slots.forEach(function (raw) {
            var aid = raw.arena_id != null ? raw.arena_id : null;
            dayMap(dow, true)[raw.start_minute] = {
              a: aid,
              d: raw.duration_minutes != null ? raw.duration_minutes : null,
            };
            if (aid != null && picked.indexOf(aid) < 0) picked.push(aid);
          });
        });
        pruneEmptyDays();
        state.weekIsSuggestion = !!data.week_is_suggestion;
        /* Подсказку перестраиваем шагом в длительность тренера — при 90 минутах серверная
           подсказка 7:00 и 8:00 сама себе накладывалась бы. */
        if (state.weekIsSuggestion) state.week = buildSuggestedWeek(arenaById(picked[0]) || null);
        state.pickedArenaIds = picked;
        syncArenaDerived();
        if (state.cityId == null) {
          var seedArena = arenaById(picked[0] || null);
          if (seedArena && seedArena.city_id != null) state.cityId = Number(seedArena.city_id);
        }
        renderCitySelect();

        state.firstName = (data.first_name || '').trim();
        state.lastName = (data.last_name || '').trim();
        state.photoUrl = data.photo_url || null;

        state.roleSuggestions = data.specialist_role_suggestions || [];
        /* NULL от сервера = роль ещё не спрашивали. Тогда не подсвечиваем ни один
           чип: подставленный «Тренер» выглядел бы как уже сделанный выбор. */
        if (data.specialist_roles && data.specialist_roles.length) {
          state.selectedRoles = data.specialist_roles.slice();
        } else if (data.specialist_role) {
          state.selectedRoles = [data.specialist_role];
        } else {
          state.selectedRoles = [];
        }
        syncRoleIsCustomFlag();
        state.venueTypes = data.venue_types || [];

        if (el.obLoading) el.obLoading.style.display = 'none';
        if (el.obFoot) el.obFoot.hidden = false;
        renderRole();
        renderVenueTypePicker();
        renderServices();
        renderArenaStep();
        renderArenaList();
        renderArenaTabs();
        syncDurationLock();
        renderWeek();
        /* Вернувшийся тренер уже видел вступление — сразу к первому шагу. */
        showStep(state.alreadyDone ? 1 : 0);
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
    state.submitError = null;
    syncCta();

    /* Каждый отмеченный старт идёт как есть — своя минута и своя площадка на слот, а не общий
       час/арена на день. Только так один день может нести две площадки и занятия по 90 минут. */
    var byDay = {};
    function pushSlot(dow, startMinute, durationMinutes, arenaId) {
      (byDay[dow] = byDay[dow] || []).push({
        start_minute: startMinute,
        duration_minutes: durationMinutes,
        arena_id: arenaId,
      });
    }
    eachSlot(function (dow, minute, slot) {
      pushSlot(dow, minute, slot.d, slot.a);
    });
    var days = Object.keys(byDay).map(function (d) {
      return { day_of_week: parseInt(d, 10), slots: byDay[d] };
    });

    fetch(apiUrl('/trainer/onboarding/quick-setup'), {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({
        service_ids: state.selectedServices,
        services: state.selectedServices.map(function (sid) {
          var svc = state.services.find(function (s) { return Number(s.id) === Number(sid); });
          var online = !!state.serviceOnlineById[sid];
          if (!serviceAllowsOnline(svc)) online = false;
          return { service_id: sid, is_online: online };
        }),
        custom_services: state.customServiceNames.map(function (name) {
          return { name: name, is_online: !!state.customServiceOnlineByName[name] };
        }),
        /* Пустой список не шлём — иначе каждое сохранение сбрасывало бы роли в БД. */
        specialist_roles: state.selectedRoles.length ? currentRolesPayload() : undefined,
        days: days,
        duration_minutes: state.durationMinutes,
        city_id: state.cityId,
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
        state.submitError = (err && err.message) || 'Не удалось сохранить. Попробуйте ещё раз.';
        syncCta();
      });
  }

  function persistDonePayload(body) {
    try {
      sessionStorage.setItem(OB_DONE_STORAGE_KEY, JSON.stringify({
        open_slots_ahead: body.open_slots_ahead || 0,
        link: body.link || null,
        share_text: body.share_text || null,
        share_body: body.share_body || null,
        needs_schedule: !!body.needs_schedule,
      }));
    } catch (e) {}
  }

  function goSetPrices() {
    persistDonePayload({
      open_slots_ahead: state._doneOpenSlots,
      link: state._doneLink,
      share_text: state._doneShareText,
      share_body: state._doneShareBody,
      needs_schedule: !!state._doneNeedsSchedule,
    });
    window.location.href = pageUrl('trainer-prices?from=onboarding');
  }

  function maybeRestoreDoneScreen() {
    var sp;
    try { sp = new URLSearchParams(window.location.search); } catch (e) { return false; }
    if (!sp || sp.get('done') !== '1') return false;
    var body = null;
    try {
      var raw = sessionStorage.getItem(OB_DONE_STORAGE_KEY);
      if (raw) body = JSON.parse(raw);
    } catch (e2) {}
    if (body) {
      if (el.obLoading) el.obLoading.style.display = 'none';
      showDone(body);
      return true;
    }
    fetch(apiUrl('/trainer/hub/universal-invite-link'), { headers: apiHeaders() })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (o) {
        if (el.obLoading) el.obLoading.style.display = 'none';
        showDone((o.ok && o.data) ? o.data : {});
      })
      .catch(function () {
        if (el.obLoading) el.obLoading.style.display = 'none';
        showDone({});
      });
    return true;
  }

  function showDone(body) {
    body = body || {};
    state.busy = false;
    state.done = true;
    if (el.obSetup) el.obSetup.hidden = true;
    if (el.obIntro) el.obIntro.hidden = true;
    if (el.obDone) el.obDone.classList.add('is-on');
    syncTelegramBack();

    var open = body.open_slots_ahead || 0;
    /* Неделю можно было оставить пустой намеренно. Тогда обещать «окна появятся
       со следующей недели» — неправда: они не появятся, пока их не отметят. */
    var leftWeekEmpty = !open && totalSlots() === 0;
    if (el.obDoneTitle) {
      if (open) el.obDoneTitle.textContent = open + ' ' + slotsWord(open) + ' на две недели';
      else if (leftWeekEmpty) el.obDoneTitle.textContent = 'Профиль сохранён';
      else el.obDoneTitle.textContent = 'Расписание сохранено';
    }
    if (el.obDoneLead) {
      if (open) {
        el.obDoneLead.textContent =
          'Ученик увидит их и выберет сам — без переписки «когда вам удобно».';
      } else if (leftWeekEmpty) {
        el.obDoneLead.textContent =
          'Время занятий добавите позже в кабинете — ссылку ученику можно отправлять уже сейчас.';
      } else {
        el.obDoneLead.textContent = 'Ближайшие свободные окна появятся со следующей недели.';
      }
    }

    var link = body.link;
    var shareText = body.share_text || '';
    var shareBody = body.share_body || '';
    state._doneOpenSlots = open;
    state._doneLink = link;
    state._doneShareText = shareText;
    state._doneShareBody = shareBody;
    persistDonePayload(body);
    if (el.obFoot) el.obFoot.hidden = false;
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
        note('Ссылка для учеников появится чуть позже — настройки уже сохранены.');
      }
    }
    if (el.obSkip) {
      el.obSkip.hidden = !link;
      el.obSkip.textContent = 'Перейти в кабинет';
      el.obSkip.onclick = goHub;
    }
    /* Только тем, у кого реально есть время вне часовой сетки — остальным строка
       была бы просто шумом (DEC-002: «Точное время» в онбординг не тащим). */
    if (el.obDoneScheduleLink) {
      var needsSchedule = !!body.needs_schedule;
      state._doneNeedsSchedule = needsSchedule;
      el.obDoneScheduleLink.hidden = !needsSchedule;
      if (needsSchedule) {
        el.obDoneScheduleLink.onclick = function (e) {
          e.preventDefault();
          window.location.href = pageUrl('schedule-editor');
        };
      }
    }
    if (el.obDonePricesBtn) {
      el.obDonePricesBtn.onclick = goSetPrices;
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
    window.location.href = pageUrl('trainer-home');
  }

  function bind() {
    if (el.obCta) el.obCta.onclick = goNext;
    if (el.obSkip) el.obSkip.onclick = onSkip;
    if (el.obBack) el.obBack.onclick = goBack;
    var tg = getTg();
    if (tg && tg.BackButton && typeof tg.BackButton.onClick === 'function') {
      try { tg.BackButton.onClick(goBack); } catch (eBk) { /* старый клиент */ }
    }
    if (el.obRoleEdit) el.obRoleEdit.onclick = toggleRoleBox;
    if (el.obWindowClear) el.obWindowClear.onclick = clearOpenWindow;
    if (el.obCity) {
      el.obCity.onchange = function () { setCity(el.obCity.value); };
    }
    if (el.obCityAddBtn) el.obCityAddBtn.onclick = openCityCreate;
    if (el.obCityCreateSubmit) el.obCityCreateSubmit.onclick = submitCityCreate;
    if (el.obCityCreateCancel) el.obCityCreateCancel.onclick = closeCityCreate;
    if (el.obCityCreateName) {
      el.obCityCreateName.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          submitCityCreate();
        }
      });
    }
    bindKeyboardSafety();
    bindArenaSearchMobile();
    if (el.obArenaSearch) el.obArenaSearch.oninput = renderArenaList;
    if (el.obArenaCreateSubmit) {
      el.obArenaCreateSubmit.onclick = function () { submitArenaCreate(false); };
    }
    if (el.obArenaCreateCancel) el.obArenaCreateCancel.onclick = closeArenaCreate;
    if (el.obArenaCreateName) {
      el.obArenaCreateName.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        if (el.obArenaCreateAddress) el.obArenaCreateAddress.focus();
      });
    }
    if (el.obArenaCreateAddress) {
      el.obArenaCreateAddress.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        submitArenaCreate(false);
      });
    }

    if (el.obServiceAddSubmit) el.obServiceAddSubmit.onclick = addCustomService;
    if (el.obServiceAddCancel) el.obServiceAddCancel.onclick = closeServiceAdd;
    if (el.obServiceAddInput) {
      el.obServiceAddInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          addCustomService();
        }
      });
    }
    if (el.obRoleAddBtn) el.obRoleAddBtn.onclick = openRoleAdd;
    if (el.obRoleAddSubmit) el.obRoleAddSubmit.onclick = addCustomRole;
    if (el.obRoleAddCancel) el.obRoleAddCancel.onclick = closeRoleAdd;
    if (el.obRoleCustom) {
      el.obRoleCustom.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          addCustomRole();
        }
      });
    }
    if (el.obServiceAddFormat) {
      bindFormatPair(el.obServiceAddFormat, false, function (online) {
        state.newCustomServiceOnline = !!online;
      });
    }
  }

  cacheEls();
  bind();
  waitForInitDataThen(load);
})();
