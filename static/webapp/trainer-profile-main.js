    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        tg.ready();
        /* Вызов expand() с небольшой задержкой, чтобы Telegram полностью инициализировал мини-апп.
           Если вызвать сразу в IIFE, expand() может не сработать для мини-апп открытого из сообщения. */
        setTimeout(function() { if (typeof tg.expand === 'function') tg.expand(); }, 100);
      }

      function initData() { return (tg && tg.initData) ? tg.initData : ''; }
      function headersJson() {
        var h = { 'Accept': 'application/json', 'Content-Type': 'application/json' };
        if (initData()) h['X-Telegram-Init-Data'] = initData();
        return h;
      }
      function headers() {
        var h = { 'Accept': 'application/json' };
        if (initData()) h['X-Telegram-Init-Data'] = initData();
        return h;
      }
      function apiUrl(path) {
        var q = initData() ? ('?init_data=' + encodeURIComponent(initData())) : '';
        return '/api/webapp' + path + q;
      }
      function webappBasePath() {
        var p = window.location.pathname || '';
        return p.replace(/[^/]+$/, '') || '/webapp/';
      }
      function webappPageUrl(pathWithQuery) {
        var url = webappBasePath() + String(pathWithQuery || '').replace(/^\//, '');
        if (initData()) {
          url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData());
        }
        return url;
      }
      function navigateToTrainerHubAfterMinimalTour() {
        window.location.href = webappPageUrl('trainer-home');
      }
      /** Covers full profile UI while we close the block tour — avoids a flash of the «normal» profile before navigation. */
      function showProfileToHubTransitionOverlay(opts) {
        opts = opts || {};
        var title = opts.title || 'Базовый профиль готов';
        var hint = opts.hint || 'Сейчас откроется главная';
        var id = 'profileToHubTransitionOverlay';
        var el = document.getElementById(id);
        if (!el) {
          el = document.createElement('div');
          el.id = id;
          el.className = 'profile-to-hub-transition';
          el.setAttribute('role', 'status');
          el.setAttribute('aria-live', 'polite');
          el.innerHTML =
            '<div class="profile-to-hub-transition__inner">' +
            '<div class="profile-to-hub-transition__icon" aria-hidden="true">✓</div>' +
            '<div class="profile-to-hub-transition__title"></div>' +
            '<p class="profile-to-hub-transition__hint"></p>' +
            '</div>';
          document.body.appendChild(el);
        }
        var titleEl = el.querySelector('.profile-to-hub-transition__title');
        var hintEl = el.querySelector('.profile-to-hub-transition__hint');
        if (titleEl) titleEl.textContent = title;
        if (hintEl) hintEl.textContent = hint;
        el.hidden = false;
        requestAnimationFrame(function() {
          el.classList.add('profile-to-hub-transition--visible');
        });
      }
      /** Ensures fields inside <details.profile-collapse> are visible (focus / validation). */
      function openProfileCollapseContaining(el) {
        if (!el || !el.closest) return;
        var det = el.closest('details.profile-collapse');
        if (det && !det.open) det.open = true;
      }
      function haptic(kind) {
        try {
          if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.notificationOccurred === 'function') {
            tg.HapticFeedback.notificationOccurred(kind || 'success');
          }
        } catch (e) {}
      }

      var saveToastTimer = null;
      /**
       * Toast under save bar: kind drives icon + colors so «warning» never shows a green checkmark.
       * kind: 'success' | 'warning' | 'error' (default success).
       */
      function showSaveToast(title, description, kind) {
        var el = document.getElementById('saveToast');
        var tEl = document.getElementById('saveToastTitle');
        var dEl = document.getElementById('saveToastDesc');
        var mark = el ? el.querySelector('.save-toast-mark') : null;
        if (!el || !tEl || !dEl) return;
        kind = kind || 'success';
        el.classList.remove('save-toast--success', 'save-toast--warning', 'save-toast--error');
        el.classList.add('save-toast--' + kind);
        if (mark) {
          if (kind === 'success') {
            mark.textContent = '✓';
          } else if (kind === 'error') {
            mark.textContent = '×';
          } else {
            mark.textContent = '!';
          }
        }
        el.setAttribute('role', kind === 'success' ? 'status' : 'alert');
        tEl.textContent = title || 'Готово';
        if (description) {
          dEl.textContent = description;
          dEl.style.display = 'block';
        } else {
          dEl.textContent = '';
          dEl.style.display = 'none';
        }
        el.hidden = false;
        el.classList.add('visible');
        if (saveToastTimer) clearTimeout(saveToastTimer);
        saveToastTimer = setTimeout(function() {
          el.classList.remove('visible');
          saveToastTimer = setTimeout(function() {
            el.hidden = true;
            el.classList.remove('save-toast--success', 'save-toast--warning', 'save-toast--error');
            if (mark) mark.textContent = '✓';
            el.setAttribute('role', 'status');
          }, 320);
        }, 3200);
      }

      var state = {
        trainer: null,
        moderation_readiness: null,
        education_entries: [],
        cities: [],
        servicesCatalog: [],
        arenasList: [],
        arenaSearchQuery: '',
        arenaCreateOpen: false,
        arenaSearchTimer: null,
        snapshot: null,
        scheduleSettings: null,
        scheduleGridSelectedStep: 15,
        /** Hub «Продолжить» → ?onboarding=blocks: sticky coach over the form. */
        profileBlockTourActive: false,
        /** First missing TTV key before tour-triggered save — used to pick next step after PATCH. */
        profileBlockTourAdvanceFromKey: null,
        /** One-shot guard: avoid duplicate redirects when final minimal step closes. */
        profileBlockTourHubRedirectScheduled: false,
        /** Wizard shows this step instead of-canonical first gap (rewind via «Назад»). */
        profileBlockTourDisplayedStepOverride: null,
        /**
         * Canonical order of TTV steps for this tour session (fixed at entry).
         * Last key = must be left via explicit «Далее» before hub / moderation auto-submit.
         */
        profileBlockTourSessionSealOrder: null,
        /** User completed the last seal step forward with gaps cleared (allows hub + moderation). */
        profileBlockTourSessionVisitedLastForward: false,
        /** Focused overlay: `?task=prices` — one block, skippable, no TTV hub bounce. */
        profileFocusedTask: null,
        /** Where to go after the overlay: `onboarding` (Done screen) or `hub`. */
        profileFocusedReturn: 'hub',
        /** `?need=full_name,phone` с хаба — запасной список gaps до готовности moderation_readiness. */
        catalogNeedFields: null,
      };

      var SCHEDULE_GRID_STEPS = [10, 15, 30, 60];
      /**
       * UX order for coach UI.
       * Один шаг «Основное»: имя + фамилия + город (сервер шлёт full_name и/или city).
       */
      var PROFILE_TT_BLOCK_ORDER = [
        'anketa_main',
        'phone',
        'session_duration_minutes',
        'min_hours_before_booking',
        'services',
        'arenas',
      ];
      /**
       * TTV block-tour only: «Назад» и канон без шагов из «Настройки» (длительность / окно записи).
       * Серверные tt_minimal_missing_fields больше не содержат эти поля — порядок должен совпадать с продуктом.
       */
      var PROFILE_TT_MINIMAL_WIZARD_ORDER = ['anketa_main', 'phone', 'services', 'arenas'];
      var ARENA_PICKER_MAX_RESULTS = 20;
      var ARENA_PICKER_SEARCH_DEBOUNCE_MS = 120;
      var arenaPickerBound = false;
      /** Stable RU labels by tour step key (do not depend on server array ordering). */
      var PROFILE_TT_BLOCK_LABELS_RU = {
        anketa_main: 'Основное',
        phone: 'контакты',
        city: 'город',
        session_duration_minutes: 'длительность занятия',
        min_hours_before_booking: 'окно записи',
        services: 'услуги',
        arenas: 'арены',
      };

      /**
       * Рельс визарда — ВСЕГДА все шаги минимальной анкеты, а не только текущие зазоры.
       *
       * Раньше рельс строился из незаполненных блоков: у тренера, которому оставалось закрыть
       * один блок, визард писал «Шаг 1 из 1», но рисовал «Назад» (предыдущий шаг существует
       * в каноне) — счётчик, точки и навигация противоречили друг другу. Теперь путь один и
       * тот же для всех: 4 шага, «Шаг X из 4» совпадает с точками, «Назад» — со второго шага.
       */
      function profileBlockTourBuildWizardRail() {
        return PROFILE_TT_MINIMAL_WIZARD_ORDER.slice();
      }

      /** Рельс сессии всегда полон — вызывать перед любым чтением (в т.ч. после reload страницы). */
      function profileBlockTourEnsureRail() {
        if (state.profileFocusedTask && PROFILE_FOCUSED_TASKS[state.profileFocusedTask]) {
          /* Не затирать динамический рельс (task=catalog из missing_fields). */
          if (state.profileBlockTourSessionSealOrder && state.profileBlockTourSessionSealOrder.length) {
            return state.profileBlockTourSessionSealOrder;
          }
          var focusedRail = PROFILE_FOCUSED_TASKS[state.profileFocusedTask].rail.slice();
          state.profileBlockTourSessionSealOrder = focusedRail;
          return focusedRail;
        }
        var rail = state.profileBlockTourSessionSealOrder;
        if (!rail || rail.length !== PROFILE_TT_MINIMAL_WIZARD_ORDER.length) {
          rail = profileBlockTourBuildWizardRail();
          state.profileBlockTourSessionSealOrder = rail;
        }
        return rail;
      }

      /** Индекс шага в рельсе (-1 — шаг не входит в минимальный путь, напр. блоки «Настроек»). */
      function profileBlockTourRailIndex(stepKey) {
        if (!stepKey) return -1;
        return profileBlockTourEnsureRail().indexOf(stepKey);
      }

      /** Первое незаполненное поле в блоке «Основное» (имя → фамилия → город). */
      function getAnketaMainFocusEl() {
        var fn = document.getElementById('first_name');
        var ln = document.getElementById('last_name');
        var city = document.getElementById('city_id');
        var fnv = fn ? String(fn.value || '').trim() : '';
        var cityVal = city ? String(city.value || '').trim() : '';
        if (!fnv) return fn;
        if (!cityVal) return city;
        return fn || ln || city;
      }

      /** Server readiness keys -> UI coach steps (один шаг anketa_main вместо отдельных имя/фамилия/город). */
      function profileBlockTourMissingStepKeys(serverMissingKeys) {
        var inKeys = Array.isArray(serverMissingKeys) ? serverMissingKeys.slice() : [];
        var out = [];
        var has = function(k) { return inKeys.indexOf(k) >= 0; };
        if (has('full_name') || has('city')) {
          out.push('anketa_main');
        }
        if (has('phone')) out.push('phone');
        if (has('session_duration_minutes')) out.push('session_duration_minutes');
        if (has('min_hours_before_booking')) out.push('min_hours_before_booking');
        if (has('services')) out.push('services');
        if (has('arenas')) out.push('arenas');
        /* Submission-tier: фото обязательно для очереди модерации (не optional). */
        if (has('photo')) out.push('photo');
        return out;
      }

      function catalogSubmissionMissingStepKeys() {
        var raw = (state.moderation_readiness && state.moderation_readiness.missing_fields) || [];
        if ((!raw || !raw.length) && state.catalogNeedFields && state.catalogNeedFields.length) {
          raw = state.catalogNeedFields;
        }
        return profileBlockTourMissingStepKeys(Array.isArray(raw) ? raw : []);
      }

      /**
       * Одна карусель каталога: gaps в каноническом порядке, телефон всегда рядом с именем.
       * Витрину (about/experience) не подмешиваем — иначе снова «вторая карусель».
       */
      function buildCatalogFocusedRail() {
        var steps = catalogSubmissionMissingStepKeys();
        var order = [
          'anketa_main',
          'phone',
          'session_duration_minutes',
          'min_hours_before_booking',
          'services',
          'arenas',
          'photo',
        ];
        var out = [];
        var i;
        for (i = 0; i < order.length; i++) {
          if (steps.indexOf(order[i]) >= 0) out.push(order[i]);
        }
        for (i = 0; i < steps.length; i++) {
          if (out.indexOf(steps[i]) < 0) out.push(steps[i]);
        }
        /* Готово к модерации — карусель не открываем (пустой рельс → сразу finish/submit). */
        return out;
      }

      function catalogLocalPhoneE164() {
        var phoneEl = document.getElementById('phone');
        if (!phoneEl) return '';
        if (window.CrmPhoneField) return CrmPhoneField.getE164(phoneEl) || '';
        return String(phoneEl.value || '').trim();
      }

      /** В карусели каталога на шаге телефона прячем «Другие контакты» — иначе красный баннер
       *  про «заполните поля» читается как будто соцсети обязательны. */
      function syncCatalogPhoneStepExtrasVisibility() {
        var extra = document.getElementById('profileContactsExtraField');
        if (!extra) return;
        var hide =
          state.profileFocusedTask === 'catalog' &&
          profileBlockTourEffectiveStepKey() === 'phone';
        extra.hidden = !!hide;
      }

      /** Visible tour step — override rewinds to an already-complete block («Назад»). */
      function profileBlockTourEffectiveStepKey() {
        var rail = profileBlockTourEnsureRail();
        var ov = state.profileBlockTourDisplayedStepOverride;
        if (ov != null && rail.indexOf(ov) >= 0) return ov;
        var canon = profileBlockTourCanonicalFirstMissing();
        if (canon != null && rail.indexOf(canon) >= 0) return canon;
        /* Зазоров нет: держим последний шаг — его нужно покинуть явным «Далее». */
        return rail[rail.length - 1] || null;
      }

      /** Whether this UI wizard key is still listed as missing server-side gaps. */
      function profileBlockTourUiStepStillMissing(uiKey, missingUiKeysArray) {
        if (!uiKey || !missingUiKeysArray || !missingUiKeysArray.length) return false;
        return missingUiKeysArray.indexOf(uiKey) >= 0;
      }

      function profileBlockTourResetWizardStacks() {
        state.profileBlockTourDisplayedStepOverride = null;
        state.profileBlockTourSessionSealOrder = null;
        state.profileBlockTourSessionVisitedLastForward = false;
      }

      /** Last key of the fixed session seal list (explicit «Далее» required before hub / moderation path). */
      function profileBlockTourFinalSealStepKey() {
        var rail = profileBlockTourEnsureRail();
        return rail[rail.length - 1] || null;
      }

      /** After PATCH + loadProfile: mark tour complete only if this save closed gaps leaving the seal's last UI step. */
      function profileBlockTourMarkVisitedSealIfEligible() {
        var advanceKey = state.profileBlockTourAdvanceFromKey;
        if (!state.profileBlockTourActive || advanceKey == null) return;
        var mr = state.moderation_readiness && state.moderation_readiness.tt_minimal_missing_fields;
        var raw = Array.isArray(mr) ? mr : [];
        var missing = profileBlockTourMissingStepKeys(raw);
        if (missing.length) return;
        var fs = profileBlockTourFinalSealStepKey();
        if (fs && advanceKey === fs) state.profileBlockTourSessionVisitedLastForward = true;
      }

      function profileBlockTourOnBackClick() {
        if (!state.profileBlockTourActive) return;
        if (state.profileFocusedTask) {
          var railF = profileBlockTourEnsureRail();
          var currF = profileBlockTourEffectiveStepKey();
          var ixF = railF.indexOf(currF);
          if (ixF > 0) {
            try {
              var aeF = document.activeElement;
              if (aeF && aeF.blur) aeF.blur();
            } catch (eBkF) {}
            state.profileBlockTourDisplayedStepOverride = railF[ixF - 1];
            syncProfileBlockTourBar();
            return;
          }
          finishFocusedProfileTask();
          return;
        }
        try {
          var ae = document.activeElement;
          if (ae && ae.blur) ae.blur();
        } catch (eBk) {}
        var currKey = profileBlockTourEffectiveStepKey();
        var rail = profileBlockTourEnsureRail();
        var ix = profileBlockTourRailIndex(currKey);
        if (ix <= 0) return;
        state.profileBlockTourDisplayedStepOverride = rail[ix - 1];
        syncProfileBlockTourBar();
      }

      function buildScheduleGridPreviewInner(step) {
        var totalMin = 4 * 60;
        var n = Math.floor(totalMin / step);
        var segs = '';
        for (var i = 0; i < n; i++) {
          segs += '<span class="grid-step-preview-seg"></span>';
        }
        return (
          '<div class="grid-step-preview-bar">' +
          segs +
          '</div>' +
          '<div class="grid-step-preview-axis"><span>08:00</span><span>12:00</span></div>'
        );
      }

      /** Step included in dirty snapshot; when arena locks grid, DOM cannot diverge from server. */
      function normScheduleGridStepSnapshot() {
        var ss = state.scheduleSettings;
        if (ss && ss.arena_grid_locked) {
          var n = parseInt(ss.schedule_grid_step_minutes, 10);
          if (!isNaN(n) && SCHEDULE_GRID_STEPS.indexOf(n) >= 0) return n;
          return 15;
        }
        var v = state.trainer && state.trainer.schedule_grid_step_minutes;
        var m = parseInt(v, 10);
        if (!isNaN(m) && SCHEDULE_GRID_STEPS.indexOf(m) >= 0) return m;
        return 15;
      }

      function readScheduleGridStepSnapshot() {
        var ss = state.scheduleSettings;
        if (ss && ss.arena_grid_locked) {
          var n = parseInt(ss.schedule_grid_step_minutes, 10);
          if (!isNaN(n) && SCHEDULE_GRID_STEPS.indexOf(n) >= 0) return n;
          return 15;
        }
        var s = state.scheduleGridSelectedStep;
        if (!isNaN(s) && SCHEDULE_GRID_STEPS.indexOf(s) >= 0) return s;
        return 15;
      }

      function renderScheduleSettingsPanel() {
        var ss = state.scheduleSettings;
        if (!ss) return;
        var locked = !!ss.arena_grid_locked;
        var arenaShell = document.getElementById('scheduleGridArenaLockShell');
        var trainerShell = document.getElementById('scheduleGridTrainerShell');

        if (locked) {
          if (trainerShell) trainerShell.style.display = 'none';
          if (arenaShell) {
            arenaShell.hidden = false;
            var mainEl = document.getElementById('scheduleGridArenaLockMainText');
            var subEl = document.getElementById('scheduleGridArenaLockSubText');
            var arenaName = ss.primary_arena_name ? String(ss.primary_arena_name).trim() : '';
            if (mainEl) {
              if (arenaName) {
                mainEl.textContent =
                  'Сетка начала слотов задаётся пресетом основной арены «' +
                  arenaName +
                  '». Выбор шага 10–60 минут здесь не используется — так вы не путаете «свой» шаг с правилами площадки.';
              } else {
                mainEl.textContent =
                  'Сетка начала слотов задаётся пресетом вашей основной арены. Персональный шаг сетки на этом экране не применяется.';
              }
            }
            if (subEl) {
              var eff = ss.effective_schedule_grid || {};
              var kind = (eff.kind || '').toString();
              var line = '';
              if (kind === 'hourly_minute') {
                var mo = eff.minute_offset != null ? String(eff.minute_offset).padStart(2, '0') : '00';
                line = 'Как сейчас у площадки: допустимые начала — в :' + mo + ' каждый час.';
              } else if (eff.step_minutes != null) {
                line = 'Как сейчас у площадки: шаг ' + eff.step_minutes + ' минут между допустимыми началами.';
              } else {
                line = 'Точные слоты всегда видны в редакторе расписания.';
              }
              subEl.textContent = line;
            }
          }
          setDirty();
          return;
        }

        if (arenaShell) arenaShell.hidden = true;
        if (trainerShell) trainerShell.style.display = '';

        var saved = parseInt(ss.schedule_grid_step_minutes, 10);
        if (isNaN(saved) || SCHEDULE_GRID_STEPS.indexOf(saved) < 0) saved = 15;
        if (isNaN(state.scheduleGridSelectedStep) || SCHEDULE_GRID_STEPS.indexOf(state.scheduleGridSelectedStep) < 0) {
          state.scheduleGridSelectedStep = saved;
        }

        var chipsWrap = document.getElementById('gridStepChips');
        if (!chipsWrap) return;
        chipsWrap.innerHTML = '';
        SCHEDULE_GRID_STEPS.forEach(function(step) {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'grid-step-chip' + (state.scheduleGridSelectedStep === step ? ' selected' : '');
          b.textContent = step + ' мин';
          b.disabled = locked;
          b.setAttribute('data-step', String(step));
          b.addEventListener('click', function() {
            if (locked) return;
            state.scheduleGridSelectedStep = step;
            renderScheduleSettingsPanel();
          });
          chipsWrap.appendChild(b);
        });

        var prevWrap = document.getElementById('gridStepPreviewWrap');
        if (!prevWrap) return;
        prevWrap.innerHTML = '';
        SCHEDULE_GRID_STEPS.forEach(function(step) {
          var card = document.createElement('div');
          card.className =
            'grid-step-preview-card' + (state.scheduleGridSelectedStep === step ? ' is-active' : '');
          card.innerHTML =
            '<div class="grid-step-preview-label">' +
            step +
            ' мин</div>' +
            buildScheduleGridPreviewInner(step);
          prevWrap.appendChild(card);
        });
        setDirty();
      }

      function wireSessionDurationQuickChips() {
        var wrap = document.getElementById('sessionDurationQuickChips');
        if (!wrap || wrap.dataset.wired === '1') return;
        wrap.dataset.wired = '1';
        [45, 60, 90].forEach(function(m) {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'settings-duration-chip';
          b.textContent = m + ' мин';
          b.addEventListener('click', function() {
            var inp = document.getElementById('session_duration_minutes');
            if (!inp) return;
            inp.value = String(m);
            validateFieldRealtime('session_duration_minutes');
            setDirty();
            markFieldValid('session_duration_minutes');
          });
          wrap.appendChild(b);
        });
      }

      function wireMinHoursBeforeQuickChips() {
        var wrap = document.getElementById('minHoursBeforeQuickChips');
        if (!wrap || wrap.dataset.wired === '1') return;
        wrap.dataset.wired = '1';
        [2, 3, 5, 10, 24].forEach(function(h) {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'settings-duration-chip';
          b.textContent = h + ' ч';
          b.addEventListener('click', function() {
            var inp = document.getElementById('min_hours_before_booking');
            if (!inp) return;
            inp.value = String(h);
            validateFieldRealtime('min_hours_before_booking');
            setDirty();
            markFieldValid('min_hours_before_booking');
          });
          wrap.appendChild(b);
        });
      }

      /** Fixed tariff codes (must match server price_tier_kind). */
      var SERVICE_TIER_ORDER = ['child', 'adult', 'two_children', 'two_adults', 'adult_and_child'];
      /** Align with ``src/shared/service_ui_accent.py`` — kept when saving profile so existing accents are not dropped. */
      var SERVICE_UI_ACCENT_SLUGS = ['sky', 'amber', 'emerald', 'violet', 'rose', 'slate'];
      var SERVICE_TIER_DEFS = [
        { code: 'child', label: 'Детский' },
        { code: 'adult', label: 'Взрослый' },
        { code: 'two_children', label: '2 ребенка' },
        { code: 'two_adults', label: '2 взрослых' },
        { code: 'adult_and_child', label: 'Взрослый + ребенок' },
      ];
      /** Базовые подписи по enum (без pending_profile — см. heroStatusLabelRu). */
      function trainerStatusLabelRu(st) {
        var map = {
          pending_contract: 'Договор',
          pending_payment: 'Оплата',
          active: 'Одобрено',
          deactivated: 'Отключён'
        };
        var k = (st || '').trim();
        return map[k] || (k || '—');
      }

      /** Тренер попросился в каталог? Пока нет — «незаполненность» не дефект, а его выбор. */
      function trainerWantsCatalogListing() {
        return !!(state.trainer && state.trainer.is_catalog_visible === true);
      }

      /** Статус в шапке: для черновика учитываем полноту и факт отправки на модерацию. */
      function heroStatusLabelRu(st, d) {
        st = (st || '').trim();
        d = d || {};
        if (st === 'pending_profile') {
          /* Без заявки в каталог статус «Не заполнен» — это оценка, которую тренер не просил:
             он работает по ссылке, и продукт для него полон. Называем состояние, а не пробел. */
          if (!trainerWantsCatalogListing()) return 'Работает по ссылке';
          if (d.tt_minimal_complete && !d.complete) return 'Минимум готов';
          if (!d.complete) return 'Не заполнен';
          if (d.already_submitted_for_moderation) return 'На модерации';
          return 'Черновик';
        }
        return trainerStatusLabelRu(st);
      }

      function pillClassForTrainerStatus(st, d) {
        st = (st || '').trim();
        d = d || {};
        if (st === 'active') return 'ok';
        if (st === 'deactivated') return 'warn';
        if (st === 'pending_contract' || st === 'pending_payment') return 'pending';
        if (st === 'pending_profile') {
          if (!trainerWantsCatalogListing()) return 'ok';
          if (d.already_submitted_for_moderation) return 'pending';
          if (d.tt_minimal_complete && !d.complete) return 'warn';
          if (!d.complete) return 'warn';
          return 'pending';
        }
        return 'warn';
      }

      /** Третий чип: короткие подсказки. Для черновика модерация только через «Сохранить» — без лишнего чипа. */
      function moderationHeroChipText(st, d) {
        st = (st || '').trim();
        if (st === 'active') return null;
        if (st === 'deactivated') return 'Не в каталоге';
        if (st === 'pending_contract') return 'Следующий шаг: договор';
        if (st === 'pending_payment') return 'Следующий шаг: оплата';
        if (st === 'pending_profile') return null;
        return null;
      }

      function parseJsonResponse(r) {
        return r.text().then(function(text) {
          var d = {};
          if (text) {
            try {
              d = JSON.parse(text);
            } catch (e) {
              d = { detail: text || 'Некорректный ответ сервера' };
            }
          }
          return { ok: r.ok, status: r.status, data: d };
        });
      }

      var PROFILE_FIELD_IDS = [
        'first_name', 'last_name', 'birth_date', 'city_id', 'phone', 'contacts', 'description',
        'experience_years', 'education', 'session_duration_minutes', 'min_hours_before_booking',
      ];
      /** Fields shown on «Настройки» tab — used to switch tab on validation errors. */
      var SETTINGS_FORMAT_FIELD_IDS = ['session_duration_minutes', 'min_hours_before_booking', 'push_notification', 'digest'];
      var PHONE_MAX_LEN = 32;
      var PHONE_ERR = 'Укажите корректный номер телефона.';
      function validatePhoneMessage(normalized) {
        if (!normalized) return null;
        if (window.CrmPhoneField) {
          var el = document.getElementById('phone');
          var v = el ? CrmPhoneField.validate(el) : { ok: !!normalized, error: PHONE_ERR };
          return v.ok ? null : v.error || PHONE_ERR;
        }
        if (normalized.length > PHONE_MAX_LEN) return 'Телефон: не длиннее 32 символов.';
        return /^\+(375\d{9}|7\d{10})$/.test(normalized) ? null : PHONE_ERR;
      }
      function todayIsoDate() {
        var d = new Date();
        var y = d.getFullYear();
        var m = String(d.getMonth() + 1).padStart(2, '0');
        var day = String(d.getDate()).padStart(2, '0');
        return y + '-' + m + '-' + day;
      }
      function isoBirthDateToDisplay(iso) {
        var v = String(iso || '').trim();
        if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return '';
        var parts = v.split('-');
        return parts[2] + '.' + parts[1] + '.' + parts[0];
      }
      function parseBirthDateDisplayToIso(display) {
        var v = String(display || '').trim();
        if (!v) return null;
        var m = v.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
        if (!m) return null;
        return m[3] + '-' + m[2] + '-' + m[1];
      }
      function formatBirthDateInputValue(raw) {
        var digits = String(raw || '').replace(/\D/g, '').slice(0, 8);
        var out = '';
        if (digits.length > 0) out = digits.slice(0, 2);
        if (digits.length > 2) out += '.' + digits.slice(2, 4);
        if (digits.length > 4) out += '.' + digits.slice(4, 8);
        return out;
      }
      function setBirthDateInputFromIso(iso) {
        var el = document.getElementById('birth_date');
        if (!el) return;
        el.value = isoBirthDateToDisplay(iso);
      }
      function initBirthDateInput() {
        var el = document.getElementById('birth_date');
        if (!el || el.dataset.birthInputReady === '1') return;
        el.dataset.birthInputReady = '1';
        el.addEventListener('input', function() {
          var next = formatBirthDateInputValue(el.value);
          if (el.value !== next) el.value = next;
          validateFieldRealtime('birth_date');
          setDirty();
          markFieldValid('birth_date');
        });
        el.addEventListener('blur', function() {
          validateFieldRealtime('birth_date');
          markFieldValid('birth_date');
        });
      }
      function isoBirthDateIsReal(iso) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return false;
        var parts = iso.split('-');
        var dt = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
        return (
          dt.getFullYear() === Number(parts[0]) &&
          dt.getMonth() === Number(parts[1]) - 1 &&
          dt.getDate() === Number(parts[2])
        );
      }
      function validateBirthDateMessage(value) {
        var v = String(value || '').trim();
        if (!v) return null;
        var iso = v.indexOf('-') >= 0 ? v : parseBirthDateDisplayToIso(v);
        if (!iso) return 'Дата рождения: формат ДД.ММ.ГГГГ';
        if (!isoBirthDateIsReal(iso)) return 'Дата рождения выглядит некорректно.';
        if (iso < '1900-01-01') return 'Дата рождения выглядит некорректно.';
        if (iso > todayIsoDate()) return 'Дата рождения не может быть в будущем.';
        return null;
      }
      var MIN_DESCRIPTION_CHARS = 25;
      var MAX_DESCRIPTION_CHARS = 5000;
      /** Per-service blurb in «Услуги и цены»; aligned with LEN_TRAINER_SERVICE_DESCRIPTION on the server. */
      var MAX_SERVICE_DESCRIPTION_CHARS = 800;
      var MAX_SERVICE_CLIENT_NOTICE_CHARS = 400;
      /** Stored/sent text; plural «не входят» matches client-facing wording. Legacy «не входит» still parses in catalog/profile. */
      var SERVICE_NOTICE_PREFIX = 'В стоимость не входят:';
      var SERVICE_NOTICE_PREFIX_LEGACY = 'В стоимость не входит:';
      /** Quick-add chips → compose `SERVICE_NOTICE_PREFIX` + comma-separated fragments + '.' */
      var SERVICE_NOTICE_PRESETS = [
        {
          id: 'skates',
          label: 'Коньки',
          fragment: 'прокат коньков (при необходимости)',
          legacyFragments: ['аренда коньков'],
        },
        {
          id: 'rollers',
          label: 'Ролики и защита',
          fragment: 'прокат роликов и защиты (при необходимости)',
          legacyFragments: ['аренда роликов'],
        },
        {
          id: 'ticket_student',
          label: 'Билет для ученика',
          fragment: 'билет на лёд для ученика',
          legacyFragments: ['билет на лёд или вход на арену'],
        },
        {
          id: 'tickets_both',
          label: 'Билеты для ученика и тренера',
          fragment: 'билеты на лёд для ученика и тренера',
          legacyFragments: [],
        },
      ];

      function _serviceNoticeEscapedPrefix(prefix) {
        return new RegExp('^' + String(prefix || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*', 'i');
      }

      var RE_SERVICE_NOTICE_PREFIX = _serviceNoticeEscapedPrefix(SERVICE_NOTICE_PREFIX);
      var RE_SERVICE_NOTICE_PREFIX_LEGACY = _serviceNoticeEscapedPrefix(SERVICE_NOTICE_PREFIX_LEGACY);

      function buildTrainerServiceNoticeFromPresetIds(ids) {
        if (!ids || !ids.length) return '';
        var parts = [];
        SERVICE_NOTICE_PRESETS.forEach(function(pr) {
          if (ids.indexOf(pr.id) >= 0) parts.push(pr.fragment);
        });
        if (!parts.length) return '';
        return SERVICE_NOTICE_PREFIX + ' ' + parts.join(', ') + '.';
      }

      /**
       * Which chips match edited text — strip old/new prefixes, then longest fragments first so
       * «билеты…» is not swallowed by substring «билет…».
       */
      function inferTrainerNoticePresetIds(text) {
        var t = (text || '').trim();
        if (!t) return [];
        var probe = t;
        if (RE_SERVICE_NOTICE_PREFIX.test(probe)) {
          probe = probe.replace(RE_SERVICE_NOTICE_PREFIX, '').replace(/\.\s*$/, '').trim();
        } else if (RE_SERVICE_NOTICE_PREFIX_LEGACY.test(probe)) {
          probe = probe.replace(RE_SERVICE_NOTICE_PREFIX_LEGACY, '').replace(/\.\s*$/, '').trim();
        } else {
          probe = probe.replace(/\.\s*$/, '').trim();
        }
        var low = probe.toLowerCase();
        var out = [];
        var sorted = SERVICE_NOTICE_PRESETS.slice().sort(function(a, b) {
          return (b.fragment || '').length - (a.fragment || '').length;
        });
        sorted.forEach(function(pr) {
          var needles = [pr.fragment].concat(pr.legacyFragments || []);
          var matched = needles.some(function(needle) {
            return needle && low.indexOf(String(needle).toLowerCase()) >= 0;
          });
          if (matched) out.push(pr.id);
        });
        return out;
      }

      var MAX_EDUCATION_DOCUMENT_PHOTOS = 12;

      function friendlyApiMsg(msg) {
        if (!msg) return 'Проверьте поля формы.';
        var s = String(msg);
        if (s.indexOf('Value error, ') === 0) return s.slice('Value error, '.length);
        return s;
      }

      function ensureErrorEl(fieldId) {
        if (fieldId === 'general') return document.getElementById('err_general');
        var id = 'err_' + fieldId;
        var existing = document.getElementById(id);
        if (existing) return existing;
        var input = document.getElementById(fieldId);
        if (!input) return null;
        var wrap = input.closest('.field');
        if (!wrap) return null;
        var p = document.createElement('p');
        p.className = 'field-error';
        p.id = id;
        p.setAttribute('role', 'status');
        p.hidden = true;
        wrap.appendChild(p);
        return p;
      }

      function setFieldInvalid(fieldId, invalid) {
        var inp = document.getElementById(fieldId);
        if (inp) inp.classList.toggle('field-invalid', !!invalid);
      }

      function clearFormErrors() {
        PROFILE_FIELD_IDS.forEach(function(fid) {
          var el = document.getElementById('err_' + fid);
          if (!el) el = ensureErrorEl(fid);
          if (el) {
            el.textContent = '';
            el.hidden = true;
          }
          setFieldInvalid(fid, false);
        });
        var gen = document.getElementById('err_general');
        if (gen) {
          gen.textContent = '';
          gen.hidden = true;
        }
        var es = document.getElementById('err_services');
        if (es) {
          es.textContent = '';
          es.hidden = true;
        }
        var epa = document.getElementById('err_primary_arena');
        if (epa) {
          epa.textContent = '';
          epa.hidden = true;
        }
        var esc = document.getElementById('err_schedule_grid');
        if (esc) {
          esc.textContent = '';
          esc.hidden = true;
        }
        var epush = document.getElementById('err_push_notification');
        if (epush) {
          epush.textContent = '';
          epush.hidden = true;
        }
        var edig = document.getElementById('err_digest');
        if (edig) {
          edig.textContent = '';
          edig.hidden = true;
        }
      }

      function showFieldError(fieldId, message) {
        if (fieldId === 'push_notification') {
          var epn = document.getElementById('err_push_notification');
          if (epn) {
            epn.textContent = message || '';
            epn.hidden = !message;
          }
          return;
        }
        if (fieldId === 'digest') {
          var edg = document.getElementById('err_digest');
          if (edg) {
            edg.textContent = message || '';
            edg.hidden = !message;
          }
          return;
        }
        var el = fieldId === 'general' ? document.getElementById('err_general') : ensureErrorEl(fieldId);
        if (!el) return;
        el.textContent = message;
        el.hidden = !message;
        if (fieldId !== 'general') setFieldInvalid(fieldId, !!message);
      }

      /** Map FastAPI/Pydantic loc to form field id (profile.*) or 'general'. */
      function locToProfileFieldId(loc) {
        if (!loc || !loc.length) return 'general';
        var si;
        for (si = 0; si < loc.length; si++) {
          if (loc[si] === 'schedule_grid_step_minutes') return 'schedule_grid';
          if (loc[si] === 'push_notification_start_hour' || loc[si] === 'push_notification_end_hour') {
            return 'push_notification';
          }
          if (loc[si] === 'digest_send_time' || loc[si] === 'digest_enabled') {
            return 'digest';
          }
        }
        var j = -1;
        for (var i = 0; i < loc.length; i++) {
          if (loc[i] === 'profile') {
            j = i;
            break;
          }
        }
        if (j < 0) return 'general';
        var key = loc[j + 1];
        if (key == null) return 'general';
        var s = String(key);
        if (PROFILE_FIELD_IDS.indexOf(s) >= 0) return s;
        return 'general';
      }

      function applyValidationDetail(detail) {
        clearFormErrors();
        if (detail == null) return;
        if (typeof detail === 'string') {
          showFieldError('general', detail);
          return;
        }
        if (!Array.isArray(detail)) {
          showFieldError('general', 'Не удалось сохранить. Проверьте данные.');
          return;
        }
        var byField = {};
        detail.forEach(function(item) {
          var loc = item.loc || [];
          var fid = locToProfileFieldId(loc);
          var msg = friendlyApiMsg(item.msg || '');
          if (!msg) return;
          if (byField[fid]) byField[fid] += ' ' + msg;
          else byField[fid] = msg;
        });
        Object.keys(byField).forEach(function(fid) {
          showFieldError(fid, byField[fid]);
        });
      }

      /** Mirrors `src.shared.profile_phone.normalize_phone_input`. */
      function normalizePhoneClient(s) {
        if (window.CrmPhoneField) {
          var parsed = CrmPhoneField.parseE164ToCountryAndNational(s);
          return CrmPhoneField.nationalToE164(parsed.national, parsed.country) || String(s || '').trim();
        }
        var raw = String(s || '').trim();
        if (!raw) return '';
        var d = raw.replace(/\D/g, '');
        if (!d) return raw.slice(0, PHONE_MAX_LEN);
        if (d.length === 12 && d.indexOf('375') === 0) return '+' + d;
        if (d.length === 11 && d.indexOf('80') === 0) return '+375' + d.slice(2);
        if (d.length === 9) return '+375' + d;
        if (d.length === 11 && d.charAt(0) === '8') return '+7' + d.slice(1);
        if (d.length === 11 && d.charAt(0) === '7') return '+' + d;
        if (d.length === 10 && d.charAt(0) === '9') return '+7' + d;
        return raw.replace(/\s+/g, '').replace(/-/g, '').replace(/\(/g, '').replace(/\)/g, '').replace(/\./g, '').slice(0, PHONE_MAX_LEN);
      }


      function updateDescriptionMeta() {
        var el = document.getElementById('description');
        var meta = document.getElementById('descriptionMeta');
        var charCount = document.getElementById('descCharCount');
        var progressBar = document.getElementById('descProgressBar');
        var minHint = document.getElementById('descMinHint');
        if (!el || !meta) return;
        var raw = el.value || '';
        var t = raw.trim();
        var len = raw.length;
        var trimLen = t.length;
        
        if (charCount) charCount.textContent = len;
        
        var progress = Math.min(100, (trimLen / MIN_DESCRIPTION_CHARS) * 100);
        if (progressBar) {
          progressBar.style.width = progress + '%';
          progressBar.classList.remove('warn', 'ok');
          if (trimLen >= MIN_DESCRIPTION_CHARS) {
            progressBar.classList.add('ok');
          } else if (trimLen > 0) {
            progressBar.classList.add('warn');
          }
        }
        
        if (minHint) {
          if (trimLen >= MIN_DESCRIPTION_CHARS) {
            minHint.textContent = '✓ достаточно';
            minHint.style.color = '#34c759';
          } else if (trimLen > 0) {
            minHint.textContent = 'ещё ' + (MIN_DESCRIPTION_CHARS - trimLen) + ' симв.';
            minHint.style.color = 'var(--glide-ink-teal, #0B6E70)';
          } else {
            minHint.textContent = 'мин. ' + MIN_DESCRIPTION_CHARS + ' символов';
            minHint.style.color = '';
          }
        }
        
        meta.classList.remove('description-warn', 'description-ok');
        if (trimLen >= MIN_DESCRIPTION_CHARS) {
          meta.classList.add('description-ok');
        } else if (trimLen > 0) {
          meta.classList.add('description-warn');
        }
      }

      /**
       * Per-field validation while typing (same bounds as API / ProfilePatch).
       * Returns true if this field has no blocking error.
       */
      function validateFieldRealtime(fieldId) {
        var el = document.getElementById(fieldId);
        if (!el) return true;
        var msg = null;
        if (fieldId === 'phone') {
          var phoneEl = document.getElementById('phone');
          if (phoneEl && (phoneEl.value || '').replace(/\D/g, '').length > 0) {
            msg = validatePhoneMessage(CrmPhoneField ? CrmPhoneField.getE164(phoneEl) : '');
          }
        } else if (fieldId === 'first_name') {
          if (!(el.value || '').trim()) msg = 'Укажите имя.';
        } else if (fieldId === 'last_name') {
          if (!(el.value || '').trim()) msg = 'Укажите фамилию.';
        } else if (fieldId === 'birth_date') {
          var birthRaw = (el.value || '').trim();
          if (birthRaw && birthRaw.length < 10) msg = null;
          else msg = validateBirthDateMessage(birthRaw);
        } else if (fieldId === 'city_id') {
          if (!el.value) msg = 'Выберите город из списка.';
        } else if (fieldId === 'contacts') {
          if ((el.value || '').length > MAX_DESCRIPTION_CHARS) {
            msg = 'Текст контактов не длиннее ' + MAX_DESCRIPTION_CHARS + ' символов.';
          }
        } else if (fieldId === 'description') {
          var dl = (el.value || '').length;
          if (dl > MAX_DESCRIPTION_CHARS) msg = 'Описание не длиннее ' + MAX_DESCRIPTION_CHARS + ' символов.';
          updateDescriptionMeta();
        } else if (fieldId === 'experience_years') {
          var ev = el.value;
          if (ev !== '' && ev != null) {
            var en = Number(ev);
            if (isNaN(en) || en < 0 || en > 80) msg = 'Опыт: от 0 до 80 лет.';
          }
        } else if (fieldId === 'session_duration_minutes') {
          var sv = el.value;
          if (sv !== '' && sv != null) {
            var sn = Number(sv);
            if (isNaN(sn) || sn < 15 || sn > 240) msg = 'Стандартное время занятия: от 15 до 240 минут.';
          }
        } else if (fieldId === 'min_hours_before_booking') {
          var mv = el.value;
          if (mv !== '' && mv != null) {
            var mn = Number(mv);
            if (isNaN(mn) || mn < 0 || mn > 168) msg = 'От 0 до 168 часов.';
          }
        }
        if (msg) showFieldError(fieldId, msg);
        else clearOneFieldError(fieldId);
        return !msg;
      }

      /** Same rules as PATCH / ProfilePatch; no side effects.
       *  draft=true (PDEC-001): Save may persist partial profile — do not require
       *  first/last/city/phone presence (moderation_readiness still gates catalog).
       *  Format/range errors on filled fields still block Save.
       */
      function collectProfileFieldErrors(parsed, opts) {
        opts = opts || {};
        var draft = !!opts.draft;
        var pr = parsed.profile;
        var errs = [];
        var fn = pr.first_name != null ? String(pr.first_name).trim() : '';
        var ln = pr.last_name != null ? String(pr.last_name).trim() : '';
        if (!draft) {
          if (!fn) errs.push(['first_name', 'Укажите имя.']);
          /* Фамилия необязательна для каталога и TTV — полный досье всё ещё может просить её в статусе. */
        }
        var birthEl = document.getElementById('birth_date');
        var birthDisplay = birthEl ? String(birthEl.value || '').trim() : '';
        if (birthDisplay && birthDisplay.length !== 10) {
          errs.push(['birth_date', 'Дата рождения: формат ДД.ММ.ГГГГ']);
        } else {
          var birthDateMsg = validateBirthDateMessage(pr.birth_date || birthDisplay);
          if (birthDateMsg) errs.push(['birth_date', birthDateMsg]);
        }
        var cityRaw = pr.city_id;
        var hasCity = cityRaw != null && cityRaw !== '' && Number(cityRaw) >= 1;
        if (!draft) {
          if (!hasCity) errs.push(['city_id', 'Выберите город из списка.']);
        } else if (cityRaw != null && cityRaw !== '' && !hasCity) {
          errs.push(['city_id', 'Выберите город из списка.']);
        }
        var ph = normalizePhoneClient(pr.phone);
        var pmsg = validatePhoneMessage(ph);
        if (!draft) {
          if (pmsg) errs.push(['phone', pmsg]);
        } else if (ph) {
          if (pmsg) errs.push(['phone', pmsg]);
        }
        if ((pr.contacts && String(pr.contacts).length) > MAX_DESCRIPTION_CHARS) {
          errs.push(['contacts', 'Текст контактов не длиннее ' + MAX_DESCRIPTION_CHARS + ' символов.']);
        }
        var desc = pr.description != null ? String(pr.description) : '';
        if (desc.length > MAX_DESCRIPTION_CHARS) {
          errs.push(['description', 'Описание не длиннее ' + MAX_DESCRIPTION_CHARS + ' символов.']);
        }
        if (pr.experience_years != null && (pr.experience_years < 0 || pr.experience_years > 80)) {
          errs.push(['experience_years', 'Опыт: от 0 до 80 лет.']);
        }
        if (pr.session_duration_minutes != null && (pr.session_duration_minutes < 15 || pr.session_duration_minutes > 240)) {
          errs.push(['session_duration_minutes', 'Стандартное время занятия: от 15 до 240 минут.']);
        }
        if (pr.min_hours_before_booking != null && (pr.min_hours_before_booking < 0 || pr.min_hours_before_booking > 168)) {
          errs.push(['min_hours_before_booking', 'От 0 до 168 часов.']);
        }
        return errs;
      }

      function canonicalArenaIds() {
        var raw = (state.trainer && state.trainer.arena_ids) ? state.trainer.arena_ids : [];
        var ids = [];
        var seen = {};
        raw.forEach(function(id) {
          var n = Number(id);
          if (!n || seen[n]) return;
          seen[n] = true;
          ids.push(n);
        });
        ids.sort(function(a, b) { return a - b; });
        return ids;
      }

      function arenaIdsOutsideLoadedList() {
        var loaded = {};
        (state.arenasList || []).forEach(function(a) { loaded[Number(a.id)] = true; });
        return canonicalArenaIds().filter(function(id) { return !loaded[id]; });
      }

      function setCanonicalArenaIds(ids) {
        if (!state.trainer) state.trainer = {};
        state.trainer.arena_ids = (ids || []).slice();
      }

      function arenaIsPublic(id) {
        var map = (state.trainer && state.trainer.arena_is_public) || {};
        if (Object.prototype.hasOwnProperty.call(map, String(id))) return map[String(id)] !== false;
        if (Object.prototype.hasOwnProperty.call(map, id)) return map[id] !== false;
        return true;
      }

      function setArenaIsPublicLocal(id, isPublic) {
        if (!state.trainer) state.trainer = {};
        if (!state.trainer.arena_is_public || typeof state.trainer.arena_is_public !== 'object') {
          state.trainer.arena_is_public = {};
        }
        state.trainer.arena_is_public[String(id)] = !!isPublic;
      }

      function syncArenaIdsFromCheckboxes() {
        var ids = [];
        (state.arenasList || []).forEach(function(a) {
          var cb = document.getElementById('arena_' + a.id);
          if (cb && cb.checked) ids.push(a.id);
        });
        arenaIdsOutsideLoadedList().forEach(function(id) {
          if (ids.indexOf(id) < 0) ids.push(id);
        });
        setCanonicalArenaIds(ids);
      }

      function arenaIdsEqual(a, b) {
        var as = (a || []).map(Number).filter(Boolean).sort(function(x, y) { return x - y; });
        var bs = (b || []).map(Number).filter(Boolean).sort(function(x, y) { return x - y; });
        if (as.length !== bs.length) return false;
        var i;
        for (i = 0; i < as.length; i++) if (as[i] !== bs[i]) return false;
        return true;
      }

      /** Default on. `?arena_picker=legacy` restores the full checkbox census (AC-009). */
      function profileArenaPickerEnabled() {
        try {
          return new URLSearchParams(window.location.search).get('arena_picker') !== 'legacy';
        } catch (e) {
          return true;
        }
      }

      function escapeArenaHtml(s) {
        return String(s || '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;');
      }

      function normalizeArenaSearch(value) {
        return String(value || '')
          .toLowerCase()
          .replace(/ё/g, 'е')
          .replace(/\s+/g, ' ')
          .trim();
      }

      function arenaMatchesQuery(arena, query) {
        var tokens = normalizeArenaSearch(query).split(' ').filter(Boolean);
        if (!tokens.length) return true;
        var hay = normalizeArenaSearch(
          [(arena && arena.name) || '', (arena && arena.address) || ''].join(' ')
        );
        if (!hay) return false;
        var i;
        for (i = 0; i < tokens.length; i++) {
          if (hay.indexOf(tokens[i]) < 0) return false;
        }
        return true;
      }

      function findArenaById(id) {
        var n = Number(id);
        var list = state.arenasList || [];
        var i;
        for (i = 0; i < list.length; i++) {
          if (Number(list[i].id) === n) return list[i];
        }
        return null;
      }

      function ensurePrimaryArena() {
        if (!state.trainer) return;
        var ids = canonicalArenaIds();
        var cur = state.trainer.primary_arena_id != null ? Number(state.trainer.primary_arena_id) : null;
        if (!ids.length) {
          state.trainer.primary_arena_id = null;
          return;
        }
        if (!cur || ids.indexOf(cur) < 0) state.trainer.primary_arena_id = ids[0];
      }

      function resetArenaSearch() {
        state.arenaSearchQuery = '';
        var inp = document.getElementById('arenaSearchInput');
        if (inp) inp.value = '';
      }

      function priceFieldInvalid(el) {
        if (!el) return false;
        var raw = (el.value || '').trim();
        if (!raw) return false;
        var n = Number(raw);
        return isNaN(n) || n < 0;
      }

      function serviceRowIsOnRequest(serviceId) {
        var cb = document.getElementById('svc_' + serviceId);
        if (!cb || !cb.checked) return false;
        var hasPrice = false;
        SERVICE_TIER_ORDER.forEach(function(code) {
          var pel = document.getElementById('price_tier_' + serviceId + '_' + code);
          if (!pel) return;
          var raw = (pel.value || '').trim();
          if (!raw) return;
          var n = Number(raw);
          if (!isNaN(n) && n >= 0) hasPrice = true;
        });
        return !hasPrice;
      }

      function syncOnRequestHints() {
        if (!state.servicesCatalog) return;
        state.servicesCatalog.forEach(function(s) {
          var el = document.getElementById('svc_on_request_' + s.id);
          if (!el) return;
          el.hidden = !serviceRowIsOnRequest(s.id);
        });
      }

      function serviceEntryPricesOk(entry) {
        var tiers = entry.price_tiers;
        if (!tiers || !tiers.length) return true;
        var j;
        for (j = 0; j < tiers.length; j++) {
          var pb = tiers[j].price_byn;
          if (pb == null || pb === '') continue;
          var n = Number(pb);
          if (isNaN(n) || n < 0) return false;
        }
        return true;
      }

      /**
       * Checked service may have no prices («по запросу»). Reject only a filled field
       * that is not a number ≥ 0.
       */
      function domServicesPricesCoherent() {
        var coherent = true;
        state.servicesCatalog.forEach(function(s) {
          var cb = document.getElementById('svc_' + s.id);
          if (!cb || !cb.checked) return;
          SERVICE_TIER_ORDER.forEach(function(code) {
            var pel = document.getElementById('price_tier_' + s.id + '_' + code);
            if (priceFieldInvalid(pel)) coherent = false;
          });
          var gpel = document.getElementById('price_group_' + s.id);
          if (priceFieldInvalid(gpel)) coherent = false;
        });
        return coherent;
      }

      var SERVICES_PRICE_HINT_RU =
        'Цена — неотрицательное число. Пустое поле значит «по запросу».';

      /** Expand tiers and focus first missing price (or tariff) for onboarding clarity. */
      function focusFirstMissingServicePrice() {
        var found = false;
        state.servicesCatalog.forEach(function(s) {
          if (found) return;
          var cb = document.getElementById('svc_' + s.id);
          if (!cb || !cb.checked) return;
          var tbody = document.getElementById('svc_tier_body_' + s.id);
          var tbtn = document.getElementById('svc_tier_toggle_' + s.id);
          if (tbody) {
            tbody.hidden = false;
            if (tbtn) {
              tbtn.textContent = 'Свернуть ▴';
              tbtn.setAttribute('aria-expanded', 'true');
            }
          }
          var anyTier = false;
          SERVICE_TIER_ORDER.forEach(function(code) {
            var tcb = document.getElementById('svc_tier_' + s.id + '_' + code);
            var pel = document.getElementById('price_tier_' + s.id + '_' + code);
            if (tcb && tcb.checked && pel) {
              var v = pel.value.trim();
              var n = Number(v);
              if (v !== '' && !isNaN(n) && n >= 0) anyTier = true;
            }
          });
          var focusPel = null;
          SERVICE_TIER_ORDER.forEach(function(code) {
            if (focusPel) return;
            var tcb = document.getElementById('svc_tier_' + s.id + '_' + code);
            var pel = document.getElementById('price_tier_' + s.id + '_' + code);
            if (tcb && tcb.checked && pel) {
              var v2 = pel.value.trim();
              var n2 = Number(v2);
              if (v2 === '' || isNaN(n2) || n2 < 0) focusPel = pel;
            }
          });
          if (focusPel) {
            try {
              focusPel.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } catch (eSc) {}
            try {
              focusPel.focus();
            } catch (eF) {}
            found = true;
            return;
          }
          if (!anyTier) {
            var tcbFocus = null;
            SERVICE_TIER_ORDER.forEach(function(code) {
              if (tcbFocus) return;
              var tcb = document.getElementById('svc_tier_' + s.id + '_' + code);
              if (tcb) tcbFocus = tcb;
            });
            if (tcbFocus) {
              try {
                tcbFocus.scrollIntoView({ behavior: 'smooth', block: 'center' });
              } catch (eSc2) {}
              try {
                tcbFocus.focus();
              } catch (eF2) {}
              found = true;
            }
          }
        });
      }

      function servicesPricesValid(parsed) {
        if (!domServicesPricesCoherent()) return false;
        var services = parsed.services || [];
        var i;
        for (i = 0; i < services.length; i++) {
          if (!serviceEntryPricesOk(services[i])) return false;
        }
        return true;
      }

      function serviceDescriptionsLengthOk(parsed) {
        var services = parsed.services || [];
        var i;
        for (i = 0; i < services.length; i++) {
          var d = services[i].description;
          if (d != null && String(d).length > MAX_SERVICE_DESCRIPTION_CHARS) return false;
          var cn = services[i].client_notice;
          if (cn != null && String(cn).length > MAX_SERVICE_CLIENT_NOTICE_CHARS) return false;
        }
        return true;
      }

      function syncServicesValidationUi() {
        var parsed;
        try {
          parsed = JSON.parse(readFormSnapshot());
        } catch (e) {
          return;
        }
        var svcOk = servicesPricesValid(parsed);
        state.servicesCatalog.forEach(function(s) {
          var cb = document.getElementById('svc_' + s.id);
          var grid = document.getElementById('svc_tier_grid_' + s.id);
          var tbody = document.getElementById('svc_tier_body_' + s.id);
          var tbtn = document.getElementById('svc_tier_toggle_' + s.id);
          if (!cb) return;
          var invalid = false;
          if (cb.checked) {
            SERVICE_TIER_ORDER.forEach(function(code) {
              var pel = document.getElementById('price_tier_' + s.id + '_' + code);
              if (priceFieldInvalid(pel)) invalid = true;
            });
            var gpel = document.getElementById('price_group_' + s.id);
            if (priceFieldInvalid(gpel)) invalid = true;
          }
          if (grid) grid.classList.toggle('svc-tier-grid--error', invalid);
          if (tbody) {
            tbody.classList.toggle('svc-tier-body--error', invalid);
            if (invalid && cb.checked) {
              tbody.hidden = false;
              if (tbtn) {
                tbtn.textContent = 'Свернуть ▴';
                tbtn.setAttribute('aria-expanded', 'true');
              }
            }
          }
        });
        var errEl = document.getElementById('err_services');
        if (errEl) {
          var descOk = serviceDescriptionsLengthOk(parsed);
          if (!descOk) {
            errEl.textContent =
              'Описание — до ' +
              MAX_SERVICE_DESCRIPTION_CHARS +
              ' символов; блок «Важно» — до ' +
              MAX_SERVICE_CLIENT_NOTICE_CHARS +
              '.';
            errEl.hidden = false;
            openProfileCollapseContaining(errEl);
          } else if (!svcOk) {
            errEl.textContent = SERVICES_PRICE_HINT_RU;
            errEl.hidden = false;
            openProfileCollapseContaining(errEl);
          } else {
            errEl.textContent = '';
            errEl.hidden = true;
          }
        }
        syncOnRequestHints();
      }

      function isFormValidForSave() {
        try {
          var parsed = JSON.parse(readFormSnapshot());
        } catch (e) {
          return false;
        }
        /* Draft save (PDEC-001): allow city-only / partial edits without full анкета. */
        if (collectProfileFieldErrors(parsed, { draft: true }).length) return false;
        if (!servicesPricesValid(parsed)) return false;
        if (!serviceDescriptionsLengthOk(parsed)) return false;
        if (parsed.arena_ids && parsed.arena_ids.length >= 2) {
          if (!parsed.primary_arena_id || parsed.arena_ids.indexOf(parsed.primary_arena_id) < 0) return false;
        }
        return true;
      }

      /** Why Save is disabled: profile/tour copy + sticky bar after onboarding. */
      function trainerProfileSaveBlockedExplanation() {
        try {
          var parsed = JSON.parse(readFormSnapshot());
        } catch (e) {
          return 'Проверьте форму.';
        }
        var pe = collectProfileFieldErrors(parsed, { draft: true });
        if (pe.length) return pe[0][1];
        if (!servicesPricesValid(parsed)) return SERVICES_PRICE_HINT_RU;
        if (!serviceDescriptionsLengthOk(parsed)) {
          return 'Сократите описание услуги или текст в блоке «Важно для клиента».';
        }
        if (parsed.arena_ids && parsed.arena_ids.length >= 2) {
          if (!parsed.primary_arena_id || parsed.arena_ids.indexOf(parsed.primary_arena_id) < 0) {
            return 'Несколько площадок — отметьте основную для онлайн-записи.';
          }
        }
        return '';
      }

      /** When Save is inactive — explains «no changes», «tiers/prices», or first validation mismatch. */
      function syncSaveBarHint() {
        var hint = document.getElementById('saveBarHint');
        var btn = document.getElementById('btnSave');
        if (!hint || !btn) return;
        if (!btn.disabled) {
          hint.textContent = '';
          hint.hidden = true;
          return;
        }
        var dirty = false;
        try {
          dirty = state.snapshot !== null && readFormSnapshot() !== state.snapshot;
        } catch (eD) {}
        hint.hidden = false;
        if (!dirty) {
          hint.textContent = '';
          hint.hidden = true;
          return;
        }
        var sub = trainerProfileSaveBlockedExplanation();
        hint.textContent = sub || 'Проверьте обязательные поля и вкладку «Настройки».';
      }

      function profileBlockTourExplainSaveBlocked() {
        var fallback =
          'Заполните обязательные поля — затем нажмите «Сохранить и дальше».';
        try {
          var parsed = JSON.parse(readFormSnapshot());
          clientValidateProfile(parsed);
          var pe = collectProfileFieldErrors(parsed);
          if (pe.length) return pe[0][1];
          if (!servicesPricesValid(parsed)) {
            return SERVICES_PRICE_HINT_RU;
          }
          if (!serviceDescriptionsLengthOk(parsed)) {
            return 'Сократите описание услуги или текст в блоке «Важно для клиента».';
          }
          if (parsed.arena_ids && parsed.arena_ids.length >= 2) {
            if (!parsed.primary_arena_id || parsed.arena_ids.indexOf(parsed.primary_arena_id) < 0) {
              return 'Несколько площадок — отметьте основную.';
            }
          }
        } catch (e) {}
        return fallback;
      }

      /** Client-side checks (mirror server rules) before PATCH. */
      /** First tab to show when save validation fails (profile vs settings). */
      function pickTabForValidationErrors(parsed) {
        var pe = collectProfileFieldErrors(parsed);
        var i;
        for (i = 0; i < pe.length; i++) {
          if (SETTINGS_FORMAT_FIELD_IDS.indexOf(pe[i][0]) >= 0) return 'settings';
        }
        if (!servicesPricesValid(parsed) || !serviceDescriptionsLengthOk(parsed)) return 'form';
        if (parsed.arena_ids && parsed.arena_ids.length >= 2) {
          if (!parsed.primary_arena_id || parsed.arena_ids.indexOf(parsed.primary_arena_id) < 0) {
            return 'form';
          }
        }
        return 'form';
      }

      function clientValidateProfile(parsed) {
        var errs = collectProfileFieldErrors(parsed, { draft: true });
        if (!servicesPricesValid(parsed)) {
          errs.push(['services', SERVICES_PRICE_HINT_RU]);
        }
        if (!serviceDescriptionsLengthOk(parsed)) {
          errs.push([
            'services',
            'Описание — до ' +
              MAX_SERVICE_DESCRIPTION_CHARS +
              ' символов; «Важно для клиента» — до ' +
              MAX_SERVICE_CLIENT_NOTICE_CHARS +
              '.',
          ]);
        }
        if (parsed.arena_ids && parsed.arena_ids.length >= 2) {
          if (!parsed.primary_arena_id || parsed.arena_ids.indexOf(parsed.primary_arena_id) < 0) {
            errs.push(['primary_arena', 'Выберите основную площадку для онлайн-записи.']);
          }
        }
        if (!parsed.push_notif_use_default) {
          var psh = parsed.push_notification_start_hour;
          var peh = parsed.push_notification_end_hour;
          if (psh == null || peh == null || isNaN(psh) || isNaN(peh)) {
            errs.push(['push_notification', 'Укажите окно уведомлений (часы по Минску).']);
          } else if (psh === peh) {
            errs.push(['push_notification', 'Начало и конец окна должны различаться.']);
          }
        }
        if (!errs.length) return true;
        errs.forEach(function(pair) {
          if (pair[0] === 'services') {
            var es = document.getElementById('err_services');
            if (es) {
              es.textContent = pair[1];
              es.hidden = false;
              openProfileCollapseContaining(es);
            }
          } else if (pair[0] === 'primary_arena') {
            var ep = document.getElementById('err_primary_arena');
            if (ep) {
              ep.textContent = pair[1];
              ep.hidden = false;
            }
          } else if (pair[0] === 'push_notification') {
            var epu = document.getElementById('err_push_notification');
            if (epu) {
              epu.textContent = pair[1];
              epu.hidden = false;
            }
          } else {
            showFieldError(pair[0], pair[1]);
          }
        });
        return false;
      }

      /**
       * После каждого успешного «Сохранить» (и после загрузки фото, и после включения тумблера
       * каталога): если тренер попросился в каталог, статус черновик, анкета полная и ещё не в
       * очереди — отправляем в админ-бот.
       *
       * Ключевое условие — is_catalog_visible. Заполненная анкета сама по себе не значит
       * «опубликуйте меня»: тренер может доводить карточку для своих же учеников. Раньше этого
       * условия не было, и полнота профиля молча превращалась в публикацию.
       *
       * @param {{ force?: boolean }} [opts] force=true — не доверять клиентскому
       *   moderation_readiness.complete (после карусели состояние может быть stale); сервер сам
       *   ответит 422 / noop / submitted.
       */
      function maybeAutoSubmitForModeration(opts) {
        opts = opts || {};
        var t = state.trainer;
        var d = state.moderation_readiness || {};
        var st = (t && t.status) ? String(t.status).trim() : '';
        if (!t || t.is_catalog_visible !== true) return Promise.resolve({ kind: 'opt_out' });
        if (st !== 'pending_profile') return Promise.resolve({ kind: 'wrong_status' });
        if (d.already_submitted_for_moderation) return Promise.resolve({ kind: 'already' });
        if (!opts.force && !d.complete) return Promise.resolve({ kind: 'incomplete_client' });
        return fetch(apiUrl('/trainer/onboarding/submit-for-moderation'), {
          method: 'POST',
          headers: Object.assign(headers(), { 'Content-Type': 'application/json' }),
          body: '{}',
        })
          .then(parseJsonResponse)
          .then(function(sub) {
            if (!sub.ok) {
              var missing = [];
              try {
                var det = sub.data && sub.data.detail;
                if (det && Array.isArray(det.missing_labels_ru)) missing = det.missing_labels_ru;
                else if (det && Array.isArray(det.missing_fields)) missing = det.missing_fields;
              } catch (eMiss) {}
              return { kind: 'incomplete', missing: missing };
            }
            if (sub.data && sub.data.noop) {
              return { kind: 'noop', reason: sub.data.reason || '' };
            }
            if (sub.data && sub.data.submitted) {
              return loadProfile().then(function() { return { kind: 'submitted' }; });
            }
            return { kind: 'ok' };
          })
          .catch(function() { return { kind: 'error' }; });
      }

      function _pad2(n) {
        return n < 10 ? '0' + n : String(n);
      }
      function populatePushHourSelects() {
        var s0 = document.getElementById('push_notification_start_hour');
        var s1 = document.getElementById('push_notification_end_hour');
        if (!s0 || !s1 || s0.options.length) return;
        var h;
        for (h = 0; h <= 23; h++) {
          var o = document.createElement('option');
          o.value = String(h);
          o.textContent = _pad2(h) + ':00';
          s0.appendChild(o);
        }
        for (h = 1; h <= 24; h++) {
          var o2 = document.createElement('option');
          o2.value = String(h);
          o2.textContent = h === 24 ? '24:00' : _pad2(h) + ':00';
          s1.appendChild(o2);
        }
      }
      function syncPushNotifUiFromState() {
        populatePushHourSelects();
        var t = state.trainer || {};
        var useDef = t.push_notification_start_hour == null && t.push_notification_end_hour == null;
        var cb = document.getElementById('push_notif_use_default');
        var wrap = document.getElementById('push_notif_custom_wrap');
        if (cb) cb.checked = useDef;
        if (wrap) wrap.style.display = useDef ? 'none' : 'flex';
        var sh = useDef ? 8 : parseInt(t.push_notification_start_hour, 10);
        var eh = useDef ? 22 : parseInt(t.push_notification_end_hour, 10);
        var s0 = document.getElementById('push_notification_start_hour');
        var s1 = document.getElementById('push_notification_end_hour');
        if (s0 && !isNaN(sh)) s0.value = String(sh);
        if (s1 && !isNaN(eh)) s1.value = String(eh);
      }

      function _digestNearestMinute(m) {
        var allowed = [0, 15, 30, 45];
        var best = 0;
        var d = 999;
        var i;
        for (i = 0; i < allowed.length; i++) {
          var ad = Math.abs(allowed[i] - m);
          if (ad < d) {
            d = ad;
            best = allowed[i];
          }
        }
        return best;
      }

      function populateDigestSelects() {
        var hEl = document.getElementById('digest_send_hour');
        var mEl = document.getElementById('digest_send_minute');
        if (!hEl || !mEl || hEl.options.length) return;
        var h;
        for (h = 5; h <= 12; h++) {
          var o = document.createElement('option');
          o.value = String(h);
          o.textContent = _pad2(h) + ':00';
          hEl.appendChild(o);
        }
        [0, 15, 30, 45].forEach(function(mm) {
          var o2 = document.createElement('option');
          o2.value = String(mm);
          o2.textContent = _pad2(mm);
          mEl.appendChild(o2);
        });
      }

      function syncDigestInnerFromState(enOverride) {
        populateDigestSelects();
        var t = state.trainer || {};
        var en =
          enOverride != null ? !!enOverride : t.digest_enabled !== false;
        var useAuto = !t.digest_send_time;
        var dauto = document.getElementById('digest_time_auto');
        var cust = document.getElementById('digest_custom_time_wrap');
        var hint = document.querySelector('.settings-digest-options__hint');
        if (dauto) dauto.checked = useAuto;
        if (cust) cust.style.display = en && !useAuto ? 'flex' : 'none';
        if (hint) hint.hidden = !(en && useAuto);
        var hEl = document.getElementById('digest_send_hour');
        var mEl = document.getElementById('digest_send_minute');
        if (t.digest_send_time && hEl && mEl) {
          var parts = String(t.digest_send_time).split(':');
          var hh = parseInt(parts[0], 10);
          var mm = parseInt(parts[1] || '0', 10);
          if (!isNaN(hh)) {
            if (hh < 5) hh = 5;
            if (hh > 12) hh = 12;
            hEl.value = String(hh);
          }
          if (!isNaN(mm)) {
            mEl.value = String(_digestNearestMinute(mm));
          }
        } else if (hEl && mEl) {
          hEl.value = '8';
          mEl.value = '0';
        }
      }

      function syncDigestUiFromState() {
        var t = state.trainer || {};
        var en = t.digest_enabled !== false;
        var de = document.getElementById('digest_enabled');
        var wrap = document.getElementById('digest_options_wrap');
        if (de) de.checked = en;
        if (wrap) wrap.hidden = !en;
        syncDigestInnerFromState();
      }

      function normSnapshot() {
        var p = state.trainer && state.trainer.profile ? state.trainer.profile : {};
        var services = (state.trainer && state.trainer.services) ? state.trainer.services : [];
        var svc = services.map(function(s) {
          var tiers = [];
          if (s.price_tiers && s.price_tiers.length) {
            s.price_tiers.forEach(function(t) {
              if (t.tier_kind && t.price_byn != null) {
                tiers.push({ tier_kind: t.tier_kind, price_byn: Number(t.price_byn) });
              }
            });
          } else {
            if (s.price_byn != null) tiers.push({ tier_kind: 'adult', price_byn: Number(s.price_byn) });
            if (s.price_child_byn != null) tiers.push({ tier_kind: 'child', price_byn: Number(s.price_child_byn) });
          }
          tiers.sort(function(a, b) {
            return SERVICE_TIER_ORDER.indexOf(a.tier_kind) - SERVICE_TIER_ORDER.indexOf(b.tier_kind);
          });
          var descOut = null;
          if (s.description != null && String(s.description).trim()) descOut = String(s.description).trim();
          var noticeOut = null;
          if (s.client_notice != null && String(s.client_notice).trim()) noticeOut = String(s.client_notice).trim();
          var gpOut = null;
          if (s.group_price_byn != null && !isNaN(Number(s.group_price_byn))) gpOut = Number(s.group_price_byn);
          var row = { service_id: s.service_id, price_tiers: tiers, description: descOut };
          if (noticeOut != null) row.client_notice = noticeOut;
          if (gpOut != null) row.group_price_byn = gpOut;
          if (s.ui_accent != null && String(s.ui_accent).trim()) {
            var uas = String(s.ui_accent).trim().toLowerCase();
            if (SERVICE_UI_ACCENT_SLUGS.indexOf(uas) >= 0) row.ui_accent = uas;
          }
          return row;
        }).sort(function(a, b) { return a.service_id - b.service_id; });
        var arena_ids = (state.trainer && state.trainer.arena_ids) ? state.trainer.arena_ids.slice().sort(function(a,b){ return a-b; }) : [];
        var primary_arena_id = (state.trainer && state.trainer.primary_arena_id != null) ? Number(state.trainer.primary_arena_id) : null;
        var tSnap = state.trainer || {};
        var pushDef = tSnap.push_notification_start_hour == null && tSnap.push_notification_end_hour == null;
        var digestEn = tSnap.digest_enabled !== false;
        var digestTime =
          tSnap.digest_send_time != null && String(tSnap.digest_send_time).trim()
            ? String(tSnap.digest_send_time).trim()
            : null;
        return JSON.stringify({
          profile: {
            first_name: p.first_name || '',
            last_name: p.last_name || '',
            birth_date: p.birth_date || null,
            city_id: p.city_id != null ? Number(p.city_id) : null,
            phone: p.phone || '',
            contacts: p.contacts || '',
            description: p.description || '',
            experience_years: p.experience_years != null ? Number(p.experience_years) : null,
            education: p.education || null,
            session_duration_minutes: p.session_duration_minutes != null ? Number(p.session_duration_minutes) : null,
            min_hours_before_booking: p.min_hours_before_booking != null ? Number(p.min_hours_before_booking) : null,
            group_classes_enabled: !!p.group_classes_enabled,
          },
          services: svc,
          arena_ids: arena_ids,
          primary_arena_id: primary_arena_id,
          education: buildEducationSnapshotFromState(),
          schedule_grid_step_minutes: normScheduleGridStepSnapshot(),
          push_notif_use_default: pushDef,
          push_notification_start_hour:
            tSnap.push_notification_start_hour != null ? Number(tSnap.push_notification_start_hour) : null,
          push_notification_end_hour:
            tSnap.push_notification_end_hour != null ? Number(tSnap.push_notification_end_hour) : null,
          digest_enabled: digestEn,
          digest_send_time: digestTime,
        });
      }

      function readFormSnapshot() {
        function num(id, emptyNull) {
          var el = document.getElementById(id);
          if (!el) return emptyNull ? null : undefined;
          var v = el.value;
          if (v === '' || v === null) return emptyNull ? null : undefined;
          var n = Number(v);
          return isNaN(n) ? null : n;
        }
        function str(id) {
          var el = document.getElementById(id);
          var v = el ? el.value.trim() : '';
          if ((id === 'first_name' || id === 'last_name') && v === '/invite') return '';
          return v;
        }
        function dateStr(id) {
          if (id === 'birth_date') {
            var birthInput = document.getElementById('birth_date');
            var display = birthInput ? String(birthInput.value || '').trim() : '';
            if (!display) return null;
            return parseBirthDateDisplayToIso(display);
          }
          var el = document.getElementById(id);
          var v = el ? String(el.value || '').trim() : '';
          return v || null;
        }
        function phoneStr() {
          var el = document.getElementById('phone');
          if (!el) return '';
          if (window.CrmPhoneField) return CrmPhoneField.getE164(el) || '';
          return normalizePhoneClient(el.value);
        }
        var cityEl = document.getElementById('city_id');
        var cityVal = cityEl && cityEl.value !== '' ? Number(cityEl.value) : null;
        var services = [];
        var uiAccentByServiceId = {};
        (state.trainer && state.trainer.services ? state.trainer.services : []).forEach(function(sv) {
          if (sv.service_id != null) uiAccentByServiceId[sv.service_id] = sv.ui_accent;
        });
        state.servicesCatalog.forEach(function(s) {
          var cb = document.getElementById('svc_' + s.id);
          if (cb && cb.checked) {
            var tiers = [];
            SERVICE_TIER_ORDER.forEach(function(code) {
              var tcb = document.getElementById('svc_tier_' + s.id + '_' + code);
              var pel = document.getElementById('price_tier_' + s.id + '_' + code);
              if (tcb && tcb.checked && pel && pel.value.trim() !== '') {
                var p = Number(pel.value);
                if (!isNaN(p) && p >= 0) tiers.push({ tier_kind: code, price_byn: p });
              }
            });
            var svcObj = { service_id: s.id, price_tiers: tiers };
            var sdEl = document.getElementById('svc_desc_' + s.id);
            var sdRaw = sdEl ? sdEl.value.trim() : '';
            svcObj.description = sdRaw ? sdRaw : null;
            var cnEl = document.getElementById('svc_client_notice_' + s.id);
            var cnRaw = cnEl ? cnEl.value.trim() : '';
            svcObj.client_notice = cnRaw ? cnRaw : null;
            var gpel = document.getElementById('price_group_' + s.id);
            if (gpel && gpel.value.trim() !== '') {
              var gpg = Number(gpel.value);
              if (!isNaN(gpg) && gpg >= 0) svcObj.group_price_byn = gpg;
            }
            if (Object.prototype.hasOwnProperty.call(uiAccentByServiceId, s.id)) {
              var uaRaw = uiAccentByServiceId[s.id];
              if (uaRaw != null && String(uaRaw).trim()) {
                var uax = String(uaRaw).trim().toLowerCase();
                if (SERVICE_UI_ACCENT_SLUGS.indexOf(uax) >= 0) svcObj.ui_accent = uax;
              }
            }
            services.push(svcObj);
          }
        });
        services.sort(function(a, b) { return a.service_id - b.service_id; });
        var arena_ids = canonicalArenaIds();
        var primary_arena_id = null;
        if (arena_ids.length >= 2) {
          var pr = document.querySelector('input[name="primary_arena"]:checked');
          primary_arena_id = pr ? parseInt(pr.value, 10) : null;
          if (primary_arena_id == null || arena_ids.indexOf(primary_arena_id) < 0) {
            var curP = state.trainer && state.trainer.primary_arena_id != null
              ? Number(state.trainer.primary_arena_id)
              : null;
            primary_arena_id = (curP != null && arena_ids.indexOf(curP) >= 0) ? curP : arena_ids[0];
          }
        } else if (arena_ids.length === 1) {
          primary_arena_id = arena_ids[0];
        }
        var eduSel = document.getElementById('education');
        var eduVal = eduSel && eduSel.value ? eduSel.value : '';
        var pushUseDef = (function() {
          var el = document.getElementById('push_notif_use_default');
          return !!(el && el.checked);
        })();
        var pushSh = null;
        var pushEh = null;
        if (!pushUseDef) {
          pushSh = num('push_notification_start_hour', true);
          pushEh = num('push_notification_end_hour', true);
        }
        var digestEnEl = document.getElementById('digest_enabled');
        var digestEn = !digestEnEl || digestEnEl.checked;
        var digestAutoEl = document.getElementById('digest_time_auto');
        var digestAuto = digestEn && digestAutoEl && digestAutoEl.checked;
        var digestTime = null;
        if (!digestEn) {
          if (state.trainer && state.trainer.digest_send_time) {
            digestTime = String(state.trainer.digest_send_time).trim() || null;
          }
        } else if (digestEn && !digestAuto) {
          var dh = num('digest_send_hour', true);
          var dm = num('digest_send_minute', true);
          if (dh != null && dm != null) digestTime = _pad2(dh) + ':' + _pad2(dm);
        }
        return JSON.stringify({
          profile: {
            first_name: str('first_name'),
            last_name: str('last_name'),
            birth_date: dateStr('birth_date'),
            city_id: cityVal,
            phone: phoneStr(),
            contacts: str('contacts'),
            description: str('description'),
            experience_years: num('experience_years', true),
            education: eduVal ? eduVal : null,
            session_duration_minutes: num('session_duration_minutes', true),
            min_hours_before_booking: num('min_hours_before_booking', true),
            group_classes_enabled: (function() {
              var el = document.getElementById('group_classes_enabled');
              return !!(el && el.checked);
            })(),
          },
          services: services,
          arena_ids: arena_ids,
          primary_arena_id: primary_arena_id,
          education: buildEducationSnapshotFromDom(),
          schedule_grid_step_minutes: readScheduleGridStepSnapshot(),
          push_notif_use_default: pushUseDef,
          push_notification_start_hour: pushSh,
          push_notification_end_hour: pushEh,
          digest_enabled: digestEn,
          digest_send_time: digestTime,
        });
      }

      function setDirty() {
        var dirty = state.snapshot !== null && readFormSnapshot() !== state.snapshot;
        var btn = document.getElementById('btnSave');
        if (!btn) return;
        syncServicesValidationUi();
        btn.disabled = !dirty || !isFormValidForSave();
        syncProfileBlockTourNextCta();
        syncSaveBarHint();
      }

      function showMain() {
        document.getElementById('skeleton').style.display = 'none';
        var m = document.getElementById('mainContent');
        m.style.display = 'block';
        requestAnimationFrame(function() { m.classList.add('visible'); });
      }

      /** One-line hint under tabs: what belongs where (onboarding clarity). */
      function syncProfileTabExplainer(tab) {
        var el = document.getElementById('profileTabExplainer');
        if (!el) return;
        if (state.profileBlockTourActive && tab === 'form') {
          el.textContent = 'Заполняйте шаг сверху: «Сохранить и дальше» автоматически переведёт к следующему полю.';
          return;
        }
        if (tab === 'form') {
          el.textContent =
            '«Статус» — готовность к каталогу и что ещё не заполнено; «Настройки» — длительность занятия, окно записи и шаг сетки в расписании.';
        } else if (tab === 'moderation') {
          el.textContent = 'Статус проверки и список того, что ещё стоит дополнить в анкете.';
        } else         if (tab === 'settings') {
          el.textContent =
            'Настройки — правила CRM, окно уведомлений от бота и сетка расписания. Анкета и цены — во вкладке «Анкета».';
        } else {
          el.textContent = '';
        }
      }

      function syncProfileFormNavVisibility(tab) {
        var nav = document.getElementById('profileFormNav');
        if (!nav) return;
        nav.hidden = tab !== 'form';
      }

      function profileNavScrollTo(targetId) {
        var el = document.getElementById(targetId);
        if (!el) return;
        if (el.tagName && el.tagName.toLowerCase() === 'details' && !el.open) {
          el.open = true;
        }
        try {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (e2) {
          try {
            el.scrollIntoView();
          } catch (e3) {}
        }
      }

      function setTab(tab) {
        // Inline JS UI state: keep existing business logic untouched.
        var formPane = document.getElementById('tab-form');
        var moderationPane = document.getElementById('tab-moderation');
        var settingsPane = document.getElementById('tab-settings');
        if (formPane) formPane.classList.toggle('active', tab === 'form');
        if (moderationPane) moderationPane.classList.toggle('active', tab === 'moderation');
        if (settingsPane) settingsPane.classList.toggle('active', tab === 'settings');

        var btns = document.querySelectorAll('#profileFilters .filter-btn');
        btns.forEach(function(b) {
          var bt = b.getAttribute('data-tab');
          b.classList.toggle('active', bt === tab);
        });

        // Sync hash so redirect/deep-link into moderation works,
        // but "save" won't unexpectedly jump back if user changed tab.
        try {
          if (tab === 'moderation') {
            if (window.location.hash !== '#moderation') {
              history.replaceState(null, '', window.location.pathname + window.location.search + '#moderation');
            }
          } else if (tab === 'settings') {
            if (window.location.hash !== '#settings') {
              history.replaceState(null, '', window.location.pathname + window.location.search + '#settings');
            }
          } else {
            if (window.location.hash === '#moderation' || window.location.hash === '#settings') {
              history.replaceState(null, '', window.location.pathname + window.location.search);
            }
          }
        } catch (e) {}

        syncProfileTabExplainer(tab);
        syncProfileFormNavVisibility(tab);
      }

      /** Соответствует overlay #onboardingFlow — для решения «скроллить или нет». */
      function getHtmlScrollPaddingTopPx() {
        try {
          var s = getComputedStyle(document.documentElement).scrollPaddingTop;
          var m = /^([\d.]+)px\s*$/.exec(String(s || '').trim());
          if (m) return parseFloat(m[1]);
          var n = parseFloat(s);
          if (!isNaN(n)) return n;
        } catch (e) {}
        return 260;
      }

      /** Высота нижнего бара тура на телефоне (CSS fixed bottom) — для visualViewport и отступа save-bar. */
      function getProfileTourBottomInsetPx() {
        try {
          var v = getComputedStyle(document.documentElement)
            .getPropertyValue('--profile-tour-bar-height')
            .trim();
          var m = /^([\d.]+)px\s*$/.exec(v);
          if (m) return parseFloat(m[1]);
        } catch (e2) {}
        return 0;
      }

      /**
       * iOS / Telegram WebView: 100dvh не сжимается под клавиатуру. Чтобы кнопка «Далее»
       * не уходила под клаву, размер оболочки визарда берём из visualViewport.height
       * (и смещаем top на visualViewport.offsetTop на случай, когда страница «проваливается»).
       */
      function syncProfileTourBarInset() {
        var flow = document.getElementById('onboardingFlow');
        if (!flow || flow.hidden) {
          if (flow) {
            try { flow.style.removeProperty('height'); } catch (eH1) {}
            try { flow.style.removeProperty('top'); } catch (eT1) {}
          }
          resetObFlowInsetCache();
          return;
        }
        var vv = window.visualViewport;
        if (!vv) return;
        var nh = vv.height;
        var nt = vv.offsetTop || 0;
        if (Math.abs(nh - obFlowLastInsetH) < 0.75 && Math.abs(nt - obFlowLastInsetTop) < 0.75) {
          return;
        }
        obFlowLastInsetH = nh;
        obFlowLastInsetTop = nt;
        try {
          flow.style.height = nh + 'px';
        } catch (eH2) {}
        /*
         * Overlay is position:fixed; inset:0. Following visualViewport.offsetTop
         * jumps the whole wizard when iOS/Telegram pans the layout viewport for the
         * keyboard — price fields appear to "fly" to another place. Keep top at 0;
         * shrinking height is enough for «Далее» to sit above the keyboard.
         */
        try {
          flow.style.removeProperty('top');
        } catch (eT2) {}
      }

      var obFlowInsetDebounceT = null;
      /** Last applied inset to avoid duplicate reflows when vv fires resize+scroll in bursts. */
      var obFlowLastInsetH = NaN;
      var obFlowLastInsetTop = NaN;
      var obFlowFocusScrollT = null;

      /**
       * After keyboard opens and flow height shrinks, scroll the active input back into
       * the visible portion of #obFlowBody. Browser native scroll-into-view only fires at
       * focus time — not when layout changes post-focus. Called after height transition settles.
       */
      function obFlowScrollFocusedIntoView() {
        var flow = document.getElementById('onboardingFlow');
        if (!flow || flow.hidden) return;
        var ae = document.activeElement;
        if (!ae || !flow.contains(ae)) return;
        var tg = ae.tagName;
        /* Native <select> on iOS: scrollIntoView fights the wheel picker — skip entirely. */
        if (tg === 'SELECT') return;
        if (tg !== 'INPUT' && tg !== 'TEXTAREA') return;
        // .field has scroll-margin-top/bottom set in CSS; prefer scrolling the field wrapper
        var target = (ae.closest && ae.closest('.field')) || ae;
        try {
          target.scrollIntoView({ block: 'nearest', behavior: 'auto', inline: 'nearest' });
        } catch (e) {}
      }

      /** Schedule a single deferred scroll of the focused input (cancels any pending attempt). */
      function scheduleObFlowFocusedScroll(delay) {
        if (obFlowFocusScrollT) clearTimeout(obFlowFocusScrollT);
        obFlowFocusScrollT = setTimeout(function() {
          obFlowFocusScrollT = null;
          obFlowScrollFocusedIntoView();
        }, delay || 250);
      }
      /** Coalesce keyboard/focus reflows — double rAF+timeout was shifting the footer mid-gesture (two taps). */
      function scheduleProfileTourBarInsetSync() {
        if (obFlowInsetDebounceT) clearTimeout(obFlowInsetDebounceT);
        obFlowInsetDebounceT = setTimeout(function() {
          obFlowInsetDebounceT = null;
          syncProfileTourBarInset();
        }, 72);
      }

      function resetObFlowInsetCache() {
        obFlowLastInsetH = NaN;
        obFlowLastInsetTop = NaN;
      }

      /**
       * В туре не дёргаем scrollIntoView на каждый тап по соседнему полю — иначе рывок (как в нормальных мобильных формах).
       * Скроллим только если блок реально уехал под липкий бар / клавиатуру.
       */
      function profileTourFieldIsComfortablyVisible(scrollTarget) {
        if (!scrollTarget) return false;
        var r = scrollTarget.getBoundingClientRect();
        /*
         * Fullscreen ob-flow: scroll container is #obFlowBody — comparing against window + stale
         * html scroll-padding (tour class no longer applied) forced scrollIntoView on every tap.
         */
        if (document.body.classList.contains('ob-flow-open')) {
          var obBody = document.getElementById('obFlowBody');
          if (obBody && typeof obBody.getBoundingClientRect === 'function') {
            var br = obBody.getBoundingClientRect();
            var margin = 10;
            if (r.top < br.top + margin) return false;
            if (r.bottom > br.bottom - margin) return false;
            return true;
          }
        }
        var vv = window.visualViewport;
        var vh =
          vv && typeof vv.height === 'number' && vv.height > 0
            ? vv.height
            : window.innerHeight || document.documentElement.clientHeight || 0;
        if (vh < 1) return false;
        var padTop = getHtmlScrollPaddingTopPx() + 6;
        var padBottom = Math.max(20, (window.innerHeight || vh) - vh + 12);
        var tour = state.profileBlockTourActive;
        var extraBottom = 0;
        if (
          tour &&
          window.matchMedia &&
          window.matchMedia('(max-width: 560px)').matches
        ) {
          extraBottom = getProfileTourBottomInsetPx();
          if (extraBottom < 1) extraBottom = 110;
        }
        if (r.top < padTop) return false;
        if (r.bottom > vh - padBottom - extraBottom) return false;
        return true;
      }

      /**
       * @param {HTMLElement} el — фокус (input/checkbox/…).
       * @param {HTMLElement} [scrollAnchor] — если задан, скроллим его (напр. details с заголовком секции), а не внутренний контрол.
       */
      function focusElForProfileField(el, scrollAnchor) {
        if (!el) return;
        openProfileCollapseContaining(el);
        var tour = state.profileBlockTourActive;
        /* scroll-margin на .field задаётся в CSS; scrollIntoView по input его не учитывает — скроллим .field */
        var scrollTarget =
          scrollAnchor ||
          (el.closest && el.closest('.field') ? el.closest('.field') : el);
        if (!scrollAnchor && el.closest && el.closest('#servicesWrap')) {
          var svcRow = el.closest('.svc-tier-row') || el.closest('.svc-group-price-wrap');
          if (svcRow) scrollTarget = svcRow;
        }
        var skipScroll = tour && profileTourFieldIsComfortablyVisible(scrollTarget);
        var tourScrollBlock = 'start';
        if (tour && scrollTarget && scrollTarget.closest && scrollTarget.closest('#servicesWrap')) {
          /* nearest — минимальный сдвиг при смене тарифа; center давал рывок между соседними полями. */
          tourScrollBlock = 'nearest';
        }
        if (!skipScroll) {
          try {
            /* Tour: instant scroll avoids fighting Telegram/WebView + second delayed focus; smooth elsewhere */
            scrollTarget.scrollIntoView({
              behavior: tour ? 'auto' : 'smooth',
              block: tour ? tourScrollBlock : 'center',
              inline: 'nearest',
            });
          } catch (e) {}
        }
        function doFocus() {
          try {
            if (el.focus) el.focus({ preventScroll: true });
          } catch (e2) {
            try {
              if (el.focus) el.focus();
            } catch (e3) {}
          }
        }
        if (tour) {
          requestAnimationFrame(function() {
            requestAnimationFrame(doFocus);
          });
        } else {
          setTimeout(doFocus, 120);
        }
      }

      /**
       * Scroll/focus a single readiness key (moderation / TTV / full-profile field ids).
       * Used by «Дальше» onboarding coach and focusNextMissingProfileField.
       */
      function focusFormFieldForReadinessKey(key) {
        if (!key) {
          setTab('form');
          setTimeout(function() {
            if (!state.profileBlockTourActive) {
              var anchor = document.getElementById('anketaStart');
              if (anchor) {
                try {
                  anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
                } catch (eA) {}
              }
            }
            focusElForProfileField(document.getElementById('first_name'));
          }, 80);
          return;
        }

        if (key === 'photo') {
          setTab('form');
          setTimeout(function() {
            var tap = document.getElementById('heroPhotoTap');
            var hero = document.getElementById('profileHero');
            if (hero) {
              try {
                hero.scrollIntoView({ behavior: 'smooth', block: 'start' });
              } catch (e) {}
            }
            if (tap) {
              setTimeout(function() {
                try {
                  tap.focus({ preventScroll: true });
                } catch (e2) {
                  try {
                    tap.focus();
                  } catch (e3) {}
                }
              }, 200);
            }
          }, 80);
          return;
        }

        setTab('form');
        setTimeout(function() {
          var el = null;
          switch (key) {
            case 'anketa_main': {
              var ank = document.getElementById('anketaStart');
              var fn0 = document.getElementById('first_name');
              if (ank) {
                try {
                  ank.open = true;
                } catch (eOpen) {}
              }
              openProfileCollapseContaining(fn0 || ank);
              function runAnketaFocus() {
                var t = getAnketaMainFocusEl();
                if (t) focusElForProfileField(t);
              }
              /* Один проход + повтор после отрисовки бара — без лишних scrollIntoView (они дают рывки между полями) */
              runAnketaFocus();
              requestAnimationFrame(function() {
                requestAnimationFrame(function() {
                  runAnketaFocus();
                  setTimeout(runAnketaFocus, 360);
                });
              });
              return;
            }
            case 'full_name': {
              var fn = document.getElementById('first_name');
              var ln = document.getElementById('last_name');
              var fns = fn ? String(fn.value || '').trim() : '';
              var lns = ln ? String(ln.value || '').trim() : '';
              if (!fns) el = fn;
              else if (!lns) el = ln;
              else el = fn || ln;
              break;
            }
            case 'birth_date':
              el = document.getElementById('birth_date');
              break;
            case 'phone':
              el = document.getElementById('phone');
              break;
            case 'description':
              el = document.getElementById('description');
              break;
            case 'city':
              el = document.getElementById('city_id');
              break;
            case 'education':
              el = document.getElementById('education');
              if (!el) el = document.getElementById('educationEntriesWrap');
              break;
            case 'experience_years':
              el = document.getElementById('experience_years');
              break;
            case 'session_duration_minutes':
              setTab('settings');
              el = document.getElementById('session_duration_minutes');
              break;
            case 'min_hours_before_booking':
              setTab('settings');
              el = document.getElementById('min_hours_before_booking');
              break;
            case 'services': {
              var svcDetails = document.getElementById('profileServicesCollapse');
              if (svcDetails) {
                try {
                  svcDetails.open = true;
                } catch (eSvc) {}
              }
              var uc = document.querySelector('#servicesWrap input[type="checkbox"]:not(:checked)');
              el = uc || document.getElementById('servicesWrap');
              if (el) focusElForProfileField(el, svcDetails);
              return;
            }
            case 'arenas': {
              var arDetails = document.getElementById('profileNavArenas');
              if (arDetails) {
                try {
                  arDetails.open = true;
                } catch (eAr) {}
              }
              var uca = document.querySelector('#arenasWrap input[type="checkbox"]:not(:checked)');
              if (uca) {
                el = uca;
              } else {
                var pwrap = document.getElementById('primaryArenaWrap');
                if (pwrap && pwrap.style.display !== 'none') {
                  if (!document.querySelector('input[name="primary_arena"]:checked')) {
                    el = document.querySelector('input[name="primary_arena"]');
                  }
                }
                if (!el) {
                  el = document.getElementById('arenaSearchInput')
                    || document.getElementById('arenasWrap')
                    || document.getElementById('arenaHint');
                }
              }
              if (el) focusElForProfileField(el, arDetails);
              return;
            }
            default:
              el = document.getElementById('anketaStart');
          }
          if (el) focusElForProfileField(el);
        }, 80);
      }

      /**
       * Scroll/focus the first missing field: submission tier first, then full-profile tier.
       * Falls back to «Основное» if both lists are empty.
       */
      function focusNextMissingProfileField() {
        var d = state.moderation_readiness || {};
        var primary = d.missing_fields || [];
        var secondary = d.full_profile_missing_fields || [];
        var missing = primary.length ? primary : secondary;
        focusFormFieldForReadinessKey(missing.length ? missing[0] : null);
      }

      /**
       * Онбординг-визард: 1 шаг = 1 экран. Чтобы не дублировать DOM и сохранить всю существующую
       * валидацию / автосохранение / каскад city→phone и т.п., реальные блоки анкеты временно
       * переносятся в #obFlowSlot и возвращаются на место при закрытии или смене шага.
       */
      var OB_FLOW_STEP_DEFS = {
        anketa_main: {
          containerId: 'anketaStart',
          tabId: 'form',
          title: 'Познакомимся',
          subtitle: 'Имя обязательно. Фамилия — по желанию. Город — как в каталоге.',
        },
        phone: {
          containerId: 'profileNavContacts',
          tabId: 'form',
          title: 'Как с вами связаться',
          subtitle: 'Телефон нужен для каталога и подтверждения записей.',
        },
        session_duration_minutes: {
          containerId: 'obSessionDurationWrap',
          tabId: 'settings',
          title: 'Сколько идёт тренировка',
          subtitle: 'Станет длительностью по умолчанию для новых слотов. Поменять можно в любой момент.',
        },
        min_hours_before_booking: {
          containerId: 'obMinHoursWrap',
          tabId: 'settings',
          title: 'Окно записи',
          subtitle: 'За сколько часов до старта вы готовы принять запись.',
        },
        services: {
          containerId: 'profileServicesCollapse',
          tabId: 'form',
          title: 'Услуги и цены',
          subtitle: 'Отметьте, что проводите. Цену можно оставить «по запросу» и заполнить позже.',
        },
        arenas: {
          containerId: 'profileNavArenas',
          tabId: 'form',
          title: 'Где вы тренируете',
          subtitle: 'Выберите арены из списка или укажите, если вашей площадки там нет.',
        },
        photo: {
          containerId: 'profileNavPhoto',
          tabId: 'form',
          title: 'Фото',
          subtitle: 'Лицо на карточке в каталоге. Можно пропустить и добавить позже.',
        },
        about: {
          containerId: 'profileNavAbout',
          tabId: 'form',
          title: 'О себе',
          subtitle: 'Пара предложений, чтобы ученик понял, как вы работаете.',
        },
        experience: {
          containerId: 'profileNavExp',
          tabId: 'form',
          title: 'Опыт',
          subtitle: 'Сколько лет тренируете и какая квалификация — для карточки в каталоге.',
        },
        education: {
          containerId: 'profileEducationCollapse',
          tabId: 'form',
          title: 'Образование',
          subtitle: 'По желанию: вуз, курсы, сертификаты.',
        },
      };

      var PROFILE_FOCUSED_TASKS = {
        prices: {
          rail: ['services'],
          title: 'Указать цены',
          subtitle: 'Пока ученик видит «по запросу». Можно пропустить — запись от этого не зависит.',
          stepLabel: 'Цены',
          nextSave: 'Сохранить',
          nextDone: 'Готово',
        },
        vitrine: {
          rail: ['photo', 'about', 'experience', 'education'],
          title: 'Карточка для каталога',
          subtitle: 'Это витрина, не кабинет. Можно пропустить любой шаг — записи уже идут.',
          stepLabel: 'Витрина',
          nextSave: 'Сохранить',
          nextDone: 'Готово',
        },
        /* С хаба «Хочу в каталог»: одна карусель по submission gaps (имя + телефон…). */
        catalog: {
          rail: ['anketa_main', 'phone'],
          title: 'Карточка для каталога',
          subtitle: 'Имя и телефон — обязательно. Фамилию можно пропустить.',
          stepLabel: 'Каталог',
          nextSave: 'Сохранить',
          nextDone: 'Готово',
        },
      };

      /** Последний смонтированный в слоте ключ шага — чтобы не перемонтировать одно и то же. */
      var obFlowCurrentMountKey = null;

      /** Запомнить исходное место блока в DOM — чтобы потом вернуть ровно туда же. */
      function obFlowRecordHome(el) {
        if (!el) return;
        if (el.dataset.obHomeRecorded === '1') return;
        el.dataset.obHomeRecorded = '1';
        el._obHomeParent = el.parentNode;
        el._obHomeNext = el.nextSibling;
      }

      function obFlowReturnHome(el) {
        if (!el || el.dataset.obHomeRecorded !== '1') return;
        var parent = el._obHomeParent;
        if (!parent) return;
        var next = el._obHomeNext && el._obHomeNext.parentNode === parent ? el._obHomeNext : null;
        try {
          parent.insertBefore(el, next);
        } catch (eRet) {}
      }

      function obFlowUnmountCurrent() {
        var key = obFlowCurrentMountKey;
        obFlowCurrentMountKey = null;
        if (!key) return;
        var def = OB_FLOW_STEP_DEFS[key];
        if (!def) return;
        var el = document.getElementById(def.containerId);
        obFlowReturnHome(el);
      }

      /**
       * Инлайн-подсказка шага (#obFlowError) — прямо над футером, внутри карточки визарда.
       * Тост живёт вне визарда и на маленьком экране может уехать; инлайн-строка видна всегда,
       * поэтому «Далее» никогда не выглядит как «кнопка ничего не сделала».
       */
      function setObFlowError(msg) {
        var el = document.getElementById('obFlowError');
        if (!el) return;
        var text = msg ? String(msg) : '';
        el.textContent = text;
        el.hidden = !text;
      }

      function obFlowMountStep(key) {
        var def = OB_FLOW_STEP_DEFS[key];
        if (!def) return;
        if (obFlowCurrentMountKey === key) return;
        /* Новый шаг — старая претензия неактуальна. */
        setObFlowError('');
        /* Переключить вкладку, чтобы блок «жил» там, где к нему привязаны другие обработчики. */
        if (def.tabId) {
          try { setTab(def.tabId); } catch (eTab) {}
        }
        obFlowUnmountCurrent();
        var slot = document.getElementById('obFlowSlot');
        var el = document.getElementById(def.containerId);
        if (!slot || !el) return;
        obFlowRecordHome(el);
        slot.innerHTML = '';
        slot.appendChild(el);
        if (el.tagName === 'DETAILS') {
          try { el.open = true; } catch (eOpen) {}
        }
        obFlowCurrentMountKey = key;
        /* Анимация входа. */
        var card = document.querySelector('#onboardingFlow .ob-flow__card');
        if (card) {
          card.classList.remove('ob-flow__card--enter');
          void card.offsetWidth;
          card.classList.add('ob-flow__card--enter');
        }
        /* Сбрасываем скролл тела визарда к началу — чтобы заголовок шага был виден сразу. */
        var body = document.getElementById('obFlowBody');
        if (body) {
          try { body.scrollTo({ top: 0, left: 0, behavior: 'auto' }); } catch (eSc) {
            body.scrollTop = 0;
          }
        }
        /*
         * Не ставим автофокус. На iOS/Telegram первый тап по «Далее» при открытой клавиатуре
         * уходит в dismiss keyboard и не доходит до кнопки — шаг «срабатывает со второго раза».
         */
      }

      /**
       * Находит первое пустое поле шага и ставит focus({preventScroll:true}).
       * Не трогает scroll — позволяет iOS решать, когда реально нужно двигать поле.
       */
      function obFlowFocusFirstEmpty(key) {
        var el = null;
        switch (key) {
          case 'anketa_main':
            el = getAnketaMainFocusEl();
            break;
          case 'phone':
            el = document.getElementById('phone');
            break;
          case 'session_duration_minutes':
            el = document.getElementById('session_duration_minutes');
            break;
          case 'min_hours_before_booking':
            el = document.getElementById('min_hours_before_booking');
            break;
          case 'services':
          case 'arenas':
            /* Сложные блоки со списками: авто-фокус не нужен — пользователь сам выбирает. */
            return;
          default:
            return;
        }
        if (!el) return;
        if (el.tagName === 'SELECT') {
          /* На iOS авто-фокус select открывает picker — нежелательно до тапа. */
          return;
        }
        try { el.focus({ preventScroll: true }); } catch (eF) {
          try { el.focus(); } catch (eF2) {}
        }
      }

      function obFlowOpen() {
        var flow = document.getElementById('onboardingFlow');
        if (!flow) return;
        if (!flow.hidden) {
          syncProfileTourBarInset();
          return;
        }
        flow.hidden = false;
        flow.setAttribute('aria-hidden', 'false');
        document.body.classList.add('ob-flow-open');
        syncProfileTourBarInset();
      }

      function obFlowClose() {
        var flow = document.getElementById('onboardingFlow');
        if (!flow) return;
        obFlowUnmountCurrent();
        flow.hidden = true;
        flow.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('ob-flow-open');
        try { flow.style.removeProperty('height'); } catch (eHc) {}
        try { flow.style.removeProperty('top'); } catch (eTc) {}
        resetObFlowInsetCache();
        var extra = document.getElementById('profileContactsExtraField');
        if (extra) extra.hidden = false;
      }

      function startFocusedProfileTask(task, from) {
        var spec = PROFILE_FOCUSED_TASKS[task];
        if (!spec) return;
        state.profileFocusedTask = task;
        state.profileFocusedReturn = from === 'onboarding' ? 'onboarding' : 'hub';
        state.profileBlockTourActive = true;
        state.profileBlockTourHubRedirectScheduled = false;
        profileBlockTourResetWizardStacks();
        var rail = task === 'catalog' ? buildCatalogFocusedRail() : spec.rail.slice();
        if (task === 'catalog' && !rail.length) {
          /* Пробелов нет — сразу submit / хаб, без пустой карусели. */
          finishFocusedProfileTask();
          return;
        }
        if (!rail.length) rail = spec.rail.slice();
        state.profileBlockTourSessionSealOrder = rail;
        state.profileBlockTourDisplayedStepOverride = rail[0];
        state.profileBlockTourSessionVisitedLastForward = false;
        syncProfileBlockTourBar();
      }

      function focusedTaskReturnUrl() {
        if (state.profileFocusedReturn === 'onboarding') {
          return webappPageUrl('trainer-onboarding?done=1');
        }
        return webappPageUrl('trainer-home');
      }

      function finishFocusedProfileTask() {
        var dest = focusedTaskReturnUrl();
        var catalogish =
          state.profileFocusedTask === 'catalog' || state.profileFocusedTask === 'vitrine';
        state.profileBlockTourActive = false;
        state.profileFocusedTask = null;
        state.profileFocusedReturn = 'hub';
        profileBlockTourResetWizardStacks();
        obFlowClose();

        function goDest() {
          try {
            window.location.href = dest;
          } catch (eNav) {
            window.location.href = dest;
          }
        }

        function overlayFromSubmitResult(result) {
          result = result || {};
          if (result.kind === 'submitted' || result.kind === 'already' || result.kind === 'noop') {
            showProfileToHubTransitionOverlay({
              title: 'Отправили на проверку',
              hint: 'В каталоге появитесь после модерации — это не мгновенно',
            });
            return;
          }
          if (result.kind === 'incomplete') {
            var miss = (result.missing || []).slice(0, 3).join(', ');
            showProfileToHubTransitionOverlay({
              title: 'Сохранили',
              hint: miss
                ? ('Для проверки ещё нужно: ' + miss)
                : 'Для каталога ещё нужно дозаполнить профиль — подсказка на главной',
            });
            return;
          }
          if (catalogish) {
            showProfileToHubTransitionOverlay({
              title: 'Сохранили',
              hint: 'Сейчас откроется главная',
            });
            return;
          }
          showProfileToHubTransitionOverlay();
        }

        haptic('success');
        /* Свежий readiness + force submit: иначе stale complete=false → админ-бот молчит. */
        var chain = Promise.resolve();
        try {
          chain = loadProfile();
        } catch (eLoad) {
          chain = Promise.resolve();
        }
        chain
          .catch(function() { return null; })
          .then(function() {
            if (!catalogish) return { kind: 'skip' };
            return maybeAutoSubmitForModeration({ force: true });
          })
          .catch(function() { return { kind: 'error' }; })
          .then(function(result) {
            overlayFromSubmitResult(result);
            setTimeout(goDest, 1200);
          });
      }

      /**
       * Главная «синхронизация» визарда: вызывается из той же точки, где раньше был sticky-бар.
       * Имя оставлено для обратной совместимости с существующими call-site'ами.
       */
      function syncProfileBlockTourBar() {
        if (!state.profileBlockTourActive) {
          profileBlockTourResetWizardStacks();
          obFlowClose();
          syncProfileBlockTourNextCta();
          return;
        }
        if (state.profileFocusedTask) {
          var spec = PROFILE_FOCUSED_TASKS[state.profileFocusedTask];
          if (state.profileBlockTourSessionVisitedLastForward) {
            if (state.profileBlockTourHubRedirectScheduled) return;
            /* Каталог: нельзя «закончить», пока submission-пробелы на месте. */
            if (state.profileFocusedTask === 'catalog') {
              var stillCat = catalogSubmissionMissingStepKeys();
              if (stillCat.length) {
                state.profileBlockTourSessionVisitedLastForward = false;
                state.profileBlockTourHubRedirectScheduled = false;
                state.profileBlockTourDisplayedStepOverride = stillCat[0];
                haptic('warning');
                setObFlowError('Сначала заполните: этот шаг нужен для каталога.');
                /* fall through to remount the gap step */
              } else {
                state.profileBlockTourHubRedirectScheduled = true;
                haptic('success');
                finishFocusedProfileTask();
                return;
              }
            } else {
              state.profileBlockTourHubRedirectScheduled = true;
              haptic('success');
              finishFocusedProfileTask();
              return;
            }
          }
          obFlowOpen();
          var railF = profileBlockTourEnsureRail();
          var currKeyF = profileBlockTourEffectiveStepKey();
          var idxF = railF.indexOf(currKeyF);
          if (idxF < 0) {
            idxF = 0;
            currKeyF = railF[0];
          }
          var defF = OB_FLOW_STEP_DEFS[currKeyF] || {};
          var titleElF = document.getElementById('obFlowTitle');
          if (titleElF) titleElF.textContent = defF.title || (spec ? spec.title : '');
          var subElF = document.getElementById('obFlowSubtitle');
          if (subElF) subElF.textContent = defF.subtitle || (spec ? spec.subtitle : '');
          var stepElF = document.getElementById('obFlowStepLabel');
          if (stepElF) {
            stepElF.textContent = railF.length > 1
              ? ('Шаг ' + (idxF + 1) + ' из ' + railF.length + ' · ' + (spec ? spec.stepLabel : ''))
              : (spec ? spec.stepLabel : '');
          }
          var dotsF = document.getElementById('obFlowDots');
          if (dotsF) {
            dotsF.innerHTML = '';
            if (railF.length > 1) {
              dotsF.hidden = false;
              var diF;
              for (diF = 0; diF < railF.length; diF++) {
                var dotF = document.createElement('span');
                var clsF = 'ob-flow__dot';
                if (diF === idxF) clsF += ' ob-flow__dot--current';
                else if (diF < idxF) clsF += ' ob-flow__dot--done';
                dotF.className = clsF;
                dotsF.appendChild(dotF);
              }
              dotsF.setAttribute('aria-valuemax', String(railF.length));
              dotsF.setAttribute('aria-valuenow', String(idxF + 1));
            } else {
              dotsF.hidden = true;
            }
          }
          var closeBtnF = document.getElementById('obFlowClose');
          if (closeBtnF) closeBtnF.setAttribute('aria-label', 'Пропустить');
          var backBtnF = document.getElementById('obFlowBack');
          if (backBtnF) {
            backBtnF.hidden = false;
            backBtnF.textContent = idxF > 0 ? 'Назад' : 'Не сейчас';
            backBtnF.setAttribute('aria-hidden', 'false');
            backBtnF.setAttribute('aria-label', idxF > 0 ? 'Предыдущий шаг' : 'Пропустить');
          }
          obFlowMountStep(currKeyF || 'services');
          syncCatalogPhoneStepExtrasVisibility();
          syncProfileBlockTourNextCta();
          syncProfileTourBarInset();
          return;
        }
        var d = state.moderation_readiness || {};
        var rawKeys = d.tt_minimal_missing_fields || [];
        var stepKeys = profileBlockTourMissingStepKeys(rawKeys);
        var rail = profileBlockTourEnsureRail();
        if (stepKeys.length) state.profileBlockTourHubRedirectScheduled = false;

        /*
         * Финал онбординга — только когда зазоров нет И последний шаг покинут явным «Далее».
         * Иначе визард закрывался бы сам в момент, когда сервер перестал видеть пробелы,
         * и пользователь не успевал бы увидеть последний экран.
         */
        if (!stepKeys.length && state.profileBlockTourSessionVisitedLastForward) {
          /* Все шаги TTV закрыты — не показываем полный профиль: оверлей + popup, затем хаб. */
          if (state.profileBlockTourHubRedirectScheduled) {
            return;
          }
          state.profileBlockTourHubRedirectScheduled = true;
          state.profileBlockTourActive = false;
          profileBlockTourResetWizardStacks();
          /* Hub completion path: модерация та же что после сохранённого финального шага. */
          try {
            maybeAutoSubmitForModeration();
          } catch (eMod) {}
          showProfileToHubTransitionOverlay();
          obFlowClose();
          syncProfileBlockTourNextCta();
          haptic('success');
          /* Overlay already confirms success — no Telegram popup / hub toast duplicate. */
          var hubNavCommitted = false;
          function goHubOnce() {
            if (hubNavCommitted) return;
            hubNavCommitted = true;
            try {
              navigateToTrainerHubAfterMinimalTour();
            } catch (eNav) {
              window.location.href = webappPageUrl('trainer-home');
            }
          }
          setTimeout(goHubOnce, 1050);
          /* If navigation never happens (e.g. WebView blocked), remove veil so «Главная» and the rest stay usable. */
          setTimeout(function () {
            try {
              var path = String(window.location.pathname || '') + String(window.location.hash || '');
              if (!/trainer-profile/i.test(path)) return;
              var ov = document.getElementById('profileToHubTransitionOverlay');
              if (ov) ov.remove();
            } catch (eRem) {}
          }, 3500);
          return;
        }
        obFlowOpen();
        /* Забываем протухший override (шаг вне рельса) — иначе визард завис бы на нём. */
        if (
          state.profileBlockTourDisplayedStepOverride != null &&
          rail.indexOf(state.profileBlockTourDisplayedStepOverride) < 0
        ) {
          state.profileBlockTourDisplayedStepOverride = null;
        }
        var currKey = profileBlockTourEffectiveStepKey();
        var idx = rail.indexOf(currKey);
        if (idx < 0) {
          idx = 0;
          currKey = rail[0];
        }
        var totalDots = rail.length;
        var def = OB_FLOW_STEP_DEFS[currKey] || {};
        /* Заголовок шага. */
        var titleEl = document.getElementById('obFlowTitle');
        if (titleEl) titleEl.textContent = def.title || PROFILE_TT_BLOCK_LABELS_RU[currKey] || 'Заполните профиль';
        var subEl = document.getElementById('obFlowSubtitle');
        if (subEl) subEl.textContent = def.subtitle || '';
        /* Прогресс: «Шаг X из N · Название». */
        var stepEl = document.getElementById('obFlowStepLabel');
        if (stepEl) {
          var label = PROFILE_TT_BLOCK_LABELS_RU[currKey] || currKey || '';
          stepEl.textContent =
            totalDots > 0 ? 'Шаг ' + (idx + 1) + ' из ' + totalDots + ' · ' + label : '· ' + label;
        }
        var dots = document.getElementById('obFlowDots');
        if (dots) {
          dots.hidden = false;
          dots.innerHTML = '';
          var di;
          for (di = 0; di < totalDots; di++) {
            var dot = document.createElement('span');
            var cls = 'ob-flow__dot';
            /* «Готов» = у шага нет зазоров (а не «левее текущего»): после «Назад» точки не врут. */
            if (di === idx) cls += ' ob-flow__dot--current';
            else if (stepKeys.indexOf(rail[di]) < 0) cls += ' ob-flow__dot--done';
            dot.className = cls;
            dots.appendChild(dot);
          }
          dots.setAttribute('aria-valuemax', String(Math.max(totalDots, 1)));
          dots.setAttribute('aria-valuenow', String(idx + 1));
        }
        var backBtnEl = document.getElementById('obFlowBack');
        if (backBtnEl) {
          /* «Назад» ровно тогда, когда слева по рельсу есть шаг — как показывают точки. */
          var canBack = idx > 0;
          backBtnEl.hidden = !canBack;
          backBtnEl.textContent = 'Назад';
          backBtnEl.setAttribute('aria-label', 'Предыдущий шаг');
          backBtnEl.setAttribute('aria-hidden', canBack ? 'false' : 'true');
        }
        /* Смонтировать актуальный блок, если сменился шаг. */
        obFlowMountStep(currKey);
        syncProfileBlockTourNextCta();
        syncProfileTourBarInset();
      }

      function profileBlockTourNeedsSave() {
        try {
          return state.snapshot !== null && readFormSnapshot() !== state.snapshot;
        } catch (e) {}
        return false;
      }

      function syncProfileBlockTourNextCta() {
        var nx = document.getElementById('obFlowNext');
        if (!nx) return;
        if (nx.classList.contains('is-saving')) return;
        var textEl = document.getElementById('obFlowNextText');
        var label = 'Далее';
        if (state.profileBlockTourActive && state.profileFocusedTask && PROFILE_FOCUSED_TASKS[state.profileFocusedTask]) {
          var fspec = PROFILE_FOCUSED_TASKS[state.profileFocusedTask];
          var frail = profileBlockTourEnsureRail();
          var isLastF = profileBlockTourRailIndex(profileBlockTourEffectiveStepKey()) === frail.length - 1;
          if (profileBlockTourNeedsSave()) {
            label = isLastF ? fspec.nextSave : 'Сохранить и дальше';
          } else {
            label = isLastF ? fspec.nextDone : 'Далее';
          }
        } else if (state.profileBlockTourActive) {
          /* На последнем шаге кнопка обещает финал, а не ещё один экран. */
          var rail = profileBlockTourEnsureRail();
          var isLast = profileBlockTourRailIndex(profileBlockTourEffectiveStepKey()) === rail.length - 1;
          if (profileBlockTourNeedsSave()) {
            label = isLast ? 'Сохранить и завершить' : 'Сохранить и дальше';
          } else {
            label = isLast ? 'Завершить' : 'Далее';
          }
        }
        if (textEl) textEl.textContent = label;
        else nx.textContent = label;
      }

      /** Tour footer CTA: spinner + «Сохраняем…» / «Загружаем…» while PATCH or bootstrap await. */
      function setObFlowNextBusy(busy, mode) {
        var nx = document.getElementById('obFlowNext');
        if (!nx) return;
        var textEl = document.getElementById('obFlowNextText');
        if (!busy) {
          nx.classList.remove('is-saving');
          nx.removeAttribute('aria-busy');
          nx.disabled = false;
          syncProfileBlockTourNextCta();
          return;
        }
        nx.classList.add('is-saving');
        nx.setAttribute('aria-busy', 'true');
        nx.disabled = true;
        if (textEl) {
          textEl.textContent = mode === 'save' ? 'Сохраняем…' : 'Загружаем…';
        }
      }

      function profileBlockTourClearAdvanceStash() {
        state.profileBlockTourAdvanceFromKey = null;
      }

      /** First TTV gap in canonical wizard order (same as server append order, but robust if API changes). */
      function profileBlockTourCanonicalFirstMissing() {
        var rawMissing;
        if (state.profileFocusedTask === 'catalog') {
          rawMissing = (state.moderation_readiness && state.moderation_readiness.missing_fields) || [];
          if ((!rawMissing || !rawMissing.length) && state.catalogNeedFields) {
            rawMissing = state.catalogNeedFields;
          }
        } else {
          rawMissing = (state.moderation_readiness && state.moderation_readiness.tt_minimal_missing_fields) || [];
        }
        var missing = profileBlockTourMissingStepKeys(rawMissing);
        var j;
        for (j = 0; j < PROFILE_TT_BLOCK_ORDER.length; j++) {
          if (missing.indexOf(PROFILE_TT_BLOCK_ORDER[j]) >= 0) return PROFILE_TT_BLOCK_ORDER[j];
        }
        return missing[0] || null;
      }

      /** GET bootstrap + fill form; no focus (caller picks next step). Returns Promise. */
      function profileBlockTourFetchBootstrapRefresh() {
        return fetch(apiUrl('/trainer/profile/page-bootstrap'), { headers: headers() })
          .then(parseJsonResponse)
          .then(function(o) {
            if (!o.ok) return Promise.reject(new Error('bootstrap'));
            state.moderation_readiness = o.data.moderation_readiness;
            state.trainer = o.data.trainer;
            state.scheduleSettings = o.data.schedule_settings || null;
            renderScheduleSettingsPanel();
            renderModeration();
            return fillFormFromTrainer().then(function() {
              state.snapshot = normSnapshot();
              setDirty();
              /*
               * Здесь предупреждений нет: «зазоры не изменились» — норма при проходе вперёд
               * по уже заполненным шагам. Ругается только вызывающий, и только если незакрыт
               * именно текущий шаг (см. profileBlockTourOnNextClickBody).
               */
              syncProfileBlockTourBar();
            });
          })
          .catch(function() {
            return Promise.reject();
          });
      }

      /**
       * Шаг закрыт — сдвигаем визард ровно на одну позицию вправо по рельсу.
       * На последнем шаге сдвигаться некуда: помечаем, что пользователь покинул его вперёд —
       * это единственный вход в завершение онбординга (см. syncProfileBlockTourBar).
       */
      function profileBlockTourAdvanceOneStep(fromKey, missingUiKeys) {
        var rail = profileBlockTourEnsureRail();
        var ix = rail.indexOf(fromKey);
        if (ix >= 0 && ix + 1 < rail.length) {
          state.profileBlockTourDisplayedStepOverride = rail[ix + 1];
          return;
        }
        state.profileBlockTourDisplayedStepOverride = null;
        if (ix === rail.length - 1 && !(missingUiKeys && missingUiKeys.length)) {
          state.profileBlockTourSessionVisitedLastForward = true;
        }
      }

      /**
       * Снимок формы должен видеть актуальное значение ещё до blur:
       * маска телефона / type=number на iOS иногда держат value до change.
       * Не blur'им здесь — blur сжимает visualViewport и уводит футер из-под пальца.
       */
      function profileBlockTourCommitFocusedField() {
        var flow = document.getElementById('onboardingFlow');
        var ae = document.activeElement;
        if (!flow || flow.hidden || !ae || !ae.closest || !flow.contains(ae)) return;
        var tg = ae.tagName;
        if (tg !== 'INPUT' && tg !== 'TEXTAREA' && tg !== 'SELECT') return;
        try {
          ae.dispatchEvent(new Event('input', { bubbles: true }));
          ae.dispatchEvent(new Event('change', { bubbles: true }));
        } catch (eCommit) {}
        try {
          setDirty();
        } catch (eDirty) {}
      }

      /**
       * «Дальше»: сохранить при наличии черновика, затем перейти к следующему блоку по порядку TTV;
       * если форма уже сохранена — только обновить с сервера и перейти, если текущий шаг закрыт.
       */
      function profileBlockTourOnNextClick() {
        if (!state.profileBlockTourActive) return;
        var nxGate = document.getElementById('obFlowNext');
        if (nxGate && (nxGate.disabled || nxGate.classList.contains('is-saving'))) return;
        profileBlockTourCommitFocusedField();
        profileBlockTourOnNextClickBody();
      }

      function profileBlockTourOnNextClickBody() {
        if (!state.profileBlockTourActive) return;
        var nxGate = document.getElementById('obFlowNext');
        if (nxGate && nxGate.classList.contains('is-saving')) return;
        var stepAtClick = profileBlockTourEffectiveStepKey();
        if (state.profileFocusedTask) {
          var dirtyF = false;
          try {
            dirtyF = state.snapshot !== null && readFormSnapshot() !== state.snapshot;
          } catch (eDf) {}
          /* Каталог / телефон: локально номер есть, а dirty не сработал (маска) — всё равно Save. */
          if (state.profileFocusedTask === 'catalog' && stepAtClick === 'phone') {
            var localPh = catalogLocalPhoneE164();
            var phoneMsg = localPh ? validatePhoneMessage(localPh) : 'Укажите номер телефона.';
            if (phoneMsg) {
              haptic('warning');
              setObFlowError(phoneMsg);
              showSaveToast('Нужен телефон', phoneMsg, 'warning');
              focusFormFieldForReadinessKey('phone');
              return;
            }
            var missPhone = catalogSubmissionMissingStepKeys();
            if (dirtyF || profileBlockTourUiStepStillMissing('phone', missPhone)) {
              setObFlowError('');
              state.profileBlockTourAdvanceFromKey = stepAtClick;
              save({ force: true });
              return;
            }
            profileBlockTourAdvanceOneStep(stepAtClick, missPhone);
            syncProfileBlockTourBar();
            return;
          }
          if (dirtyF) {
            var btnSvF = document.getElementById('btnSave');
            /* В карусели каталога Save всё равно вызываем: btnSave может быть disabled
               из‑за чужих полей (цены услуг), draft-save телефона от этого не должен страдать. */
            if (
              state.profileFocusedTask !== 'catalog' &&
              (!btnSvF || btnSvF.disabled)
            ) {
              var whyF = profileBlockTourExplainSaveBlocked();
              haptic('warning');
              setObFlowError(whyF);
              showSaveToast('Сначала дополните шаг', whyF, 'warning');
              return;
            }
            setObFlowError('');
            state.profileBlockTourAdvanceFromKey = stepAtClick;
            save(state.profileFocusedTask === 'catalog' ? { force: true } : undefined);
            return;
          }
          /* Без dirty: для catalog нельзя перепрыгнуть незакрытый submission-шаг. */
          if (state.profileFocusedTask === 'catalog') {
            var missCat = catalogSubmissionMissingStepKeys();
            if (profileBlockTourUiStepStillMissing(stepAtClick, missCat)) {
              haptic('warning');
              var needHint =
                stepAtClick === 'phone'
                  ? 'Укажите телефон и нажмите «Сохранить».'
                  : stepAtClick === 'anketa_main'
                    ? 'Укажите имя и нажмите «Сохранить».'
                    : 'Заполните обязательные поля шага и нажмите «Сохранить».';
              setObFlowError(needHint);
              showSaveToast('Сначала закончите этот шаг', needHint, 'warning');
              focusFormFieldForReadinessKey(stepAtClick === 'anketa_main' ? 'full_name' : stepAtClick);
              return;
            }
            profileBlockTourAdvanceOneStep(stepAtClick, missCat);
            syncProfileBlockTourBar();
            return;
          }
          profileBlockTourAdvanceOneStep(stepAtClick, []);
          syncProfileBlockTourBar();
          return;
        }
        if (stepAtClick === 'services' && !domServicesPricesCoherent()) {
          haptic('warning');
          setObFlowError(SERVICES_PRICE_HINT_RU);
          showSaveToast('Проверьте цены', SERVICES_PRICE_HINT_RU, 'warning');
          try {
            syncServicesValidationUi();
          } catch (eSync) {}
          var esBlock = document.getElementById('err_services');
          if (esBlock) {
            esBlock.textContent = SERVICES_PRICE_HINT_RU;
            esBlock.hidden = false;
            openProfileCollapseContaining(esBlock);
            try {
              esBlock.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } catch (eScr) {}
          }
          focusFirstMissingServicePrice();
          return;
        }

        var dirty = false;
        try {
          dirty = state.snapshot !== null && readFormSnapshot() !== state.snapshot;
        } catch (e) {}

        if (dirty) {
          var btnSv = document.getElementById('btnSave');
          if (!btnSv || btnSv.disabled) {
            var whyBlocked = profileBlockTourExplainSaveBlocked();
            haptic('warning');
            setObFlowError(whyBlocked);
            showSaveToast('Сначала дополните шаг', whyBlocked, 'warning');
            return;
          }
          setObFlowError('');
          state.profileBlockTourAdvanceFromKey = stepAtClick;
          /* Synthetic click is unreliable in some WebViews; call save() directly. */
          save();
          return;
        }

        setObFlowNextBusy(true, 'fetch');
        profileBlockTourFetchBootstrapRefresh()
          .then(function() {
            if (!state.profileBlockTourActive) return;
            var missingRaw = (state.moderation_readiness && state.moderation_readiness.tt_minimal_missing_fields) || [];
            var missing = profileBlockTourMissingStepKeys(missingRaw);
            if (!profileBlockTourUiStepStillMissing(stepAtClick, missing)) {
              profileBlockTourAdvanceOneStep(stepAtClick, missing);
            }
            syncProfileBlockTourBar();
            if (!missing.length) return;
            if (missing.indexOf(stepAtClick) >= 0) {
              haptic('warning');
              setObFlowError('Заполните поля шага и нажмите «Сохранить и дальше».');
              showSaveToast(
                'Сначала закончите этот шаг',
                'Заполните поля шага и нажмите «Сохранить и дальше».',
                'warning'
              );
              focusFormFieldForReadinessKey(stepAtClick);
              return;
            }
          })
          .catch(function() {})
          .finally(function() {
            setObFlowNextBusy(false);
          });
      }

      /** After PATCH profile: advance tour focus (next block after stashed step, or first missing). */
      function profileBlockTourAfterSave() {
        if (!state.profileBlockTourActive) return;
        if (state.profileFocusedTask) {
          var advanceKeyF = state.profileBlockTourAdvanceFromKey;
          profileBlockTourClearAdvanceStash();
          if (state.profileFocusedTask === 'catalog') {
            var missF = catalogSubmissionMissingStepKeys();
            if (advanceKeyF != null && profileBlockTourUiStepStillMissing(advanceKeyF, missF)) {
              haptic('warning');
              setObFlowError('Заполните поля шага и нажмите «Сохранить».');
              syncProfileBlockTourBar();
              return;
            }
            if (advanceKeyF != null) profileBlockTourAdvanceOneStep(advanceKeyF, missF);
            syncProfileBlockTourBar();
            return;
          }
          if (advanceKeyF != null) profileBlockTourAdvanceOneStep(advanceKeyF, []);
          syncProfileBlockTourBar();
          return;
        }
        var missingRaw = (state.moderation_readiness && state.moderation_readiness.tt_minimal_missing_fields) || [];
        var missing = profileBlockTourMissingStepKeys(missingRaw);
        var advanceKey = state.profileBlockTourAdvanceFromKey;
        profileBlockTourClearAdvanceStash();

        if (window.location.hash === '#moderation' || window.location.hash === '#settings') {
          state.profileBlockTourDisplayedStepOverride = null;
          syncProfileBlockTourBar();
          return;
        }

        var stillMissingAdv =
          advanceKey != null && profileBlockTourUiStepStillMissing(advanceKey, missing);
        if (!stillMissingAdv && advanceKey != null) {
          profileBlockTourAdvanceOneStep(advanceKey, missing);
        }

        syncProfileBlockTourBar();

        if (!missing.length) return;
        /* Defer past layout / nested loadProfile from maybeAutoSubmitForModeration. */
        setTimeout(function() {
          if (advanceKey != null && profileBlockTourUiStepStillMissing(advanceKey, missing)) {
            focusFormFieldForReadinessKey(advanceKey);
          }
        }, 400);
      }

      function maybeEnterProfileBlockTourFromQuery() {
        var task = null;
        var from = null;
        var needRaw = null;
        try {
          var sp = new URLSearchParams(window.location.search);
          task = sp.get('task');
          from = sp.get('from');
          needRaw = sp.get('need');
          if (task && PROFILE_FOCUSED_TASKS[task]) {
            if (needRaw) {
              state.catalogNeedFields = String(needRaw)
                .split(',')
                .map(function(s) { return String(s || '').trim(); })
                .filter(Boolean);
            } else {
              state.catalogNeedFields = null;
            }
            sp.delete('task');
            sp.delete('from');
            sp.delete('need');
            var qsF = sp.toString();
            var pathF = window.location.pathname + (qsF ? '?' + qsF : '') + (window.location.hash || '');
            history.replaceState(null, '', pathF);
            startFocusedProfileTask(task, from);
            return;
          }
          if (sp.get('onboarding') !== 'blocks') return;
          sp.delete('onboarding');
          var qs = sp.toString();
          var path = window.location.pathname + (qs ? '?' + qs : '') + (window.location.hash || '');
          history.replaceState(null, '', path);
        } catch (e) {}
        var rawKeys = (state.moderation_readiness && state.moderation_readiness.tt_minimal_missing_fields) || [];
        var keys = profileBlockTourMissingStepKeys(Array.isArray(rawKeys) ? rawKeys : []);
        if (!keys.length) {
          /* TTV minimal already closed — blocks tour would hit «done» branch and bounce to hub (wrong for catalog tier). */
          state.profileBlockTourActive = false;
          state.profileBlockTourHubRedirectScheduled = false;
          syncProfileBlockTourBar();
          setTab('moderation');
          setTimeout(function() {
            var el = document.getElementById('moderation');
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }, 300);
          return;
        }
        state.profileBlockTourActive = true;
        state.profileBlockTourHubRedirectScheduled = false;
        profileBlockTourResetWizardStacks();
        state.profileBlockTourSessionSealOrder = profileBlockTourBuildWizardRail();
        state.profileBlockTourSessionVisitedLastForward = false;
        syncProfileBlockTourBar();
        /* Без автофокуса: открытая клавиатура на iOS съедает первый тап по «Далее». */
      }

      /**
       * Footer CTA: iOS/Telegram часто не шлёт `click` на первый тап, пока открыта клавиатура
       * (`mousedown preventDefault` это усугублял). Ловим pointerup/touchend с preventDefault
       * и глушим повторный click тем же debounce.
       */
      function bindProfileTourBarTap(el, handler) {
        if (!el || el.dataset.tourTapBound) return;
        el.dataset.tourTapBound = '1';
        var last = 0;
        var LOCK_MS = 500;
        var downOn = false;
        function fire(ev) {
          if (el.disabled || el.classList.contains('is-saving')) {
            if (ev) ev.preventDefault();
            return;
          }
          var t = Date.now();
          if (t - last < LOCK_MS) {
            if (ev) ev.preventDefault();
            return;
          }
          last = t;
          if (ev) {
            try {
              ev.preventDefault();
            } catch (ePd) {}
          }
          handler();
        }
        el.addEventListener('pointerdown', function(ev) {
          if (ev.pointerType === 'mouse' && ev.button !== 0) return;
          downOn = true;
        });
        el.addEventListener('pointercancel', function() {
          downOn = false;
        });
        el.addEventListener(
          'pointerup',
          function(ev) {
            if (ev.pointerType === 'mouse' && ev.button !== 0) return;
            if (!downOn) return;
            downOn = false;
            fire(ev);
          },
          { passive: false }
        );
        el.addEventListener(
          'touchend',
          function(ev) {
            if (!downOn && last && Date.now() - last < LOCK_MS) {
              ev.preventDefault();
              return;
            }
            fire(ev);
            downOn = false;
          },
          { passive: false }
        );
        el.addEventListener('click', function(ev) {
          fire(ev);
        });
      }

      function wireProfileBlockTourBar() {
        var closeBtn = document.getElementById('obFlowClose');
        var nextBtn = document.getElementById('obFlowNext');
        var backBtn = document.getElementById('obFlowBack');
        var flow = document.getElementById('onboardingFlow');

        bindProfileTourBarTap(closeBtn, function() {
          if (!state.profileBlockTourActive) {
            obFlowClose();
            return;
          }
          if (state.profileFocusedTask) {
            finishFocusedProfileTask();
            return;
          }
          /* Отложить онбординг: закрываем визард и уводим на хаб.
             Хаб сам покажет «Продолжить», пока readiness не закрыта. */
          state.profileBlockTourActive = false;
          profileBlockTourResetWizardStacks();
          obFlowClose();
          try { window.location.href = webappPageUrl('trainer-home'); } catch (eNav) {
            window.location.href = webappPageUrl('trainer-home');
          }
        });

        bindProfileTourBarTap(nextBtn, profileBlockTourOnNextClick);
        bindProfileTourBarTap(backBtn, profileBlockTourOnBackClick);

        if (flow && !flow.dataset.obFlowInsetWired) {
          flow.dataset.obFlowInsetWired = '1';
          function onFlowResize() {
            if (!flow.hidden) scheduleProfileTourBarInsetSync();
          }
          window.addEventListener('resize', onFlowResize);
          window.addEventListener('orientationchange', onFlowResize);
          if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', onFlowResize);
            /* Do not listen to visualViewport.scroll: it fires while iOS pans on focus
               and rewrites overlay height mid-gesture → visible jump. */
          }
          /* При каждом focusin/focusout пересчитать высоту — iOS показывает клавиатуру не мгновенно. */
          flow.addEventListener('focusin', scheduleProfileTourBarInsetSync);
          flow.addEventListener('focusout', scheduleProfileTourBarInsetSync);
          /* Пользователь начал править поле — снимаем претензию шага, не дожидаясь «Далее». */
          flow.addEventListener('input', function() {
            setObFlowError('');
          });
          flow.addEventListener('change', function() {
            setObFlowError('');
          });
          /*
           * Two-pass focused-field scroll: first pass (80ms) handles fields already near the
           * bottom before keyboard opens; second pass (420ms) fires after iOS keyboard finishes
           * its opening animation (~300ms). Services prices are handled by a dedicated listener.
           */
          flow.addEventListener('focusin', function(ev) {
            var t = ev.target;
            if (!t || !t.tagName) return;
            var tg = t.tagName;
            if (tg !== 'INPUT' && tg !== 'TEXTAREA') return;
            if (t.closest && t.closest('#servicesWrap')) return;
            setTimeout(function() { obFlowScrollFocusedIntoView(); }, 80);
            setTimeout(function() { obFlowScrollFocusedIntoView(); }, 420);
          });
        }

        /** Mobile WebView: tap on non-control areas should dismiss the keyboard (blur focused field). */
        if (flow && !flow.dataset.obKbDismissBound) {
          flow.dataset.obKbDismissBound = '1';
          flow.addEventListener(
            'pointerdown',
            function(ev) {
              if (!state.profileBlockTourActive || flow.hidden) return;
              if (ev.pointerType === 'mouse' && ev.button !== 0) return;
              var t = ev.target;
              if (!t || !t.closest) return;
              if (
                t.closest(
                  'input, textarea, select, button, label, summary, a[href], [contenteditable="true"]'
                )
              ) {
                return;
              }
              var ae = document.activeElement;
              if (!ae || !ae.closest || !flow.contains(ae)) return;
              var tg = ae.tagName;
              if (tg !== 'INPUT' && tg !== 'TEXTAREA' && tg !== 'SELECT') return;
              try {
                ae.blur();
              } catch (eBlur) {}
            },
            true
          );
        }
      }

      (function initTabs() {
        var buttons = document.querySelectorAll('#profileFilters .filter-btn');
        buttons.forEach(function(btn) {
          btn.addEventListener('click', function() {
            var tab = btn.getAttribute('data-tab');
            setTab(tab);
          });
        });
        if (window.location.hash === '#moderation') setTab('moderation');
        else if (window.location.hash === '#settings') setTab('settings');
        else setTab('form');

        var profileFormNav = document.getElementById('profileFormNav');
        if (profileFormNav) {
          profileFormNav.addEventListener('click', function(ev) {
            var t = ev.target;
            var btn = t && t.closest ? t.closest('[data-profile-scroll]') : null;
            if (!btn || !profileFormNav.contains(btn)) return;
            var tid = btn.getAttribute('data-profile-scroll');
            if (tid) profileNavScrollTo(tid);
          });
        }
      })();

      function fillFormFromTrainer() {
        var t = state.trainer;
        if (!t) return Promise.resolve();
        var p = t.profile || {};
        function setv(id, v) {
          var el = document.getElementById(id);
          if (!el) return;
          if (
            (id === 'first_name' || id === 'last_name') &&
            typeof v === 'string' &&
            v.trim() === '/invite'
          ) v = '';
          if (v === null || v === undefined) el.value = '';
          else el.value = v;
        }
        function setPhone(phone) {
          var el = document.getElementById('phone');
          if (!el) return;
          if (window.CrmPhoneField) {
            CrmPhoneField.setE164(el, phone || '');
            return;
          }
          el.value = phone || '';
        }
        setv('first_name', p.first_name);
        setv('last_name', p.last_name);
        setBirthDateInputFromIso(p.birth_date || '');
        setPhone(p.phone);
        setv('contacts', p.contacts);
        setv('description', p.description);
        updateDescriptionMeta();
        setv('experience_years', p.experience_years);
        setv(
          'session_duration_minutes',
          p.session_duration_minutes != null && p.session_duration_minutes !== '' ? p.session_duration_minutes : 45
        );
        setv('min_hours_before_booking', p.min_hours_before_booking);
        var gce = document.getElementById('group_classes_enabled');
        if (gce) gce.checked = !!p.group_classes_enabled;
        renderCatalogVisibility();
        var citySel = document.getElementById('city_id');
        if (citySel) citySel.value = p.city_id != null ? String(p.city_id) : '';
        var eduSel = document.getElementById('education');
        if (eduSel) eduSel.value = p.education || '';

        var photos = t.photos || [];
        var first = photos[0];
        var pfn = document.getElementById('photoFileName');
        if (pfn) {
          pfn.textContent = '';
          pfn.classList.remove('hero-photo-status--error');
        }

        renderServices();
        syncPushNotifUiFromState();
        syncDigestUiFromState();
        var pcb = document.getElementById('push_notif_use_default');
        if (pcb && !pcb._pushBound) {
          pcb._pushBound = true;
          pcb.addEventListener('change', function() {
            var wrap = document.getElementById('push_notif_custom_wrap');
            if (wrap) wrap.style.display = pcb.checked ? 'none' : 'flex';
            setDirty();
          });
        }
        var ps0 = document.getElementById('push_notification_start_hour');
        var ps1 = document.getElementById('push_notification_end_hour');
        if (ps0 && !ps0._pushBound) {
          ps0._pushBound = true;
          ps0.addEventListener('change', setDirty);
        }
        if (ps1 && !ps1._pushBound) {
          ps1._pushBound = true;
          ps1.addEventListener('change', setDirty);
        }
        var deEn = document.getElementById('digest_enabled');
        if (deEn && !deEn._digestBound) {
          deEn._digestBound = true;
          deEn.addEventListener('change', function() {
            var w = document.getElementById('digest_options_wrap');
            if (w) w.hidden = !deEn.checked;
            if (deEn.checked) syncDigestInnerFromState(true);
            setDirty();
          });
        }
        var dAuto = document.getElementById('digest_time_auto');
        if (dAuto && !dAuto._digestBound) {
          dAuto._digestBound = true;
          dAuto.addEventListener('change', function() {
            var cust = document.getElementById('digest_custom_time_wrap');
            var hint = document.querySelector('.settings-digest-options__hint');
            if (cust) cust.style.display = dAuto.checked ? 'none' : 'flex';
            if (hint) hint.hidden = !dAuto.checked;
            setDirty();
          });
        }
        var dsh = document.getElementById('digest_send_hour');
        var dsm = document.getElementById('digest_send_minute');
        if (dsh && !dsh._digestBound) {
          dsh._digestBound = true;
          dsh.addEventListener('change', setDirty);
        }
        if (dsm && !dsm._digestBound) {
          dsm._digestBound = true;
          dsm.addEventListener('change', setDirty);
        }
        return loadArenasForCity(p.city_id).then(function() {
          renderArenas();
          renderHeroSummary();
        });
      }

      /**
       * Catalog listing toggle — shown in every status (separate PATCH, not part of the profile snapshot).
       *
       * Раньше блок появлялся только у active. Пока тренер шёл к активации, сказать «в каталог
       * не хочу» было негде, а анкета уходила на модерацию сама — публикация случалась без
       * согласия. Теперь переключатель и есть согласие: пока он выключен, на проверку ничего
       * не отправляется (см. maybeAutoSubmitForModeration и try_submit_trainer_for_moderation_review).
       */
      function renderCatalogVisibility() {
        var t = state.trainer || {};
        var st = (t.status || '').trim();
        var shellTitle = document.getElementById('catalogVisibilityShell');
        var card = document.getElementById('catalogVisibilityCard');
        var cb = document.getElementById('is_catalog_visible');
        if (!shellTitle || !card || !cb) return;
        shellTitle.hidden = false;
        card.hidden = false;
        var want = t.is_catalog_visible === true;
        cb.checked = want;
        cb.disabled = st === 'deactivated';

        var titleEl = card.querySelector('.settings-group-toggle__title');
        var hintEl = card.querySelector('.settings-group-toggle__hint');
        if (titleEl) titleEl.textContent = 'Показывать в каталоге';
        if (!hintEl) return;
        if (st === 'deactivated') {
          hintEl.textContent = 'Аккаунт выключен. Восстановление — через поддержку.';
        } else if (st === 'active') {
          hintEl.textContent = want
            ? 'Клиенты находят вас в общем списке. Выключите — останется запись по вашей ссылке.'
            : 'Вас нет в общем списке. Запись по вашей ссылке работает как обычно.';
        } else if (want) {
          hintEl.textContent =
            'Готовим карточку к проверке. Как только всё будет заполнено, отправим её модератору.';
        } else {
          hintEl.textContent =
            'Пока только по вашей ссылке — это нормально. Включите, когда захотите, чтобы вас находили новые ученики.';
        }
      }

      function renderModeratorFeedbackBanner() {
        var banner = document.getElementById('moderatorFeedbackBanner');
        var txt = document.getElementById('moderatorFeedbackText');
        if (!banner || !txt) return;
        var fb = state.trainer && state.trainer.moderation_feedback;
        var s = (fb != null && String(fb).trim()) ? String(fb).trim() : '';
        if (s) {
          txt.textContent = s;
          banner.hidden = false;
        } else {
          txt.textContent = '';
          banner.hidden = true;
        }
      }

      function renderModeration() {
        var d = state.moderation_readiness || {};
        var st = (state.trainer && state.trainer.status) ? String(state.trainer.status).trim() : '';
        var missList = document.getElementById('modMissingList');
        missList.innerHTML = '';
        var pill = document.getElementById('modStatusPill');
        if (st) {
          pill.style.display = 'inline-block';
          pill.textContent = heroStatusLabelRu(st, d);
          pill.classList.remove('ok', 'warn', 'pending');
          pill.classList.add(pillClassForTrainerStatus(st, d));
        } else { pill.style.display = 'none'; }
        var hint = document.getElementById('modHint');
        var missTitle = document.getElementById('modMissingTitle');

        function appendGapListItems(labels) {
          (labels || []).forEach(function(label) {
            var li = document.createElement('li');
            li.textContent = label;
            missList.appendChild(li);
          });
        }

        if (st === 'active') {
          var vis = state.trainer && state.trainer.is_catalog_visible !== false;
          var baseHint = vis
            ? 'Профиль одобрен. Вы в каталоге — клиенты могут вас найти и записаться.'
            : 'Профиль одобрен, но скрыт из публичного каталога. Запись по прямой ссылке и для текущих клиентов сохраняется — включите показ в разделе «Настройки», если нужен поиск в каталоге.';
          var activeGapLabels = [];
          if (d.full_profile_complete === false) {
            var flA = d.full_profile_missing_labels_ru;
            if (Array.isArray(flA) && flA.length) activeGapLabels = flA.slice();
          }
          if (activeGapLabels.length) {
            missTitle.style.display = 'block';
            missTitle.textContent = 'Можно усилить карточку в каталоге:';
            hint.textContent =
              baseHint +
              ' Ниже — конкретные поля; правки во вкладке «Анкета». Это необязательно для работы.';
            appendGapListItems(activeGapLabels);
          } else {
            missTitle.style.display = 'none';
            hint.textContent =
              d.full_profile_complete === false
                ? baseHint +
                  ' Для полноты карточки в каталоге остались поля — откройте вкладку «Анкета».'
                : baseHint;
          }
        } else if (st === 'deactivated') {
          missTitle.style.display = 'none';
          hint.textContent = 'Каталог недоступен. Восстановление — через поддержку.';
        } else if (st === 'pending_contract') {
          missTitle.style.display = 'none';
          hint.textContent = 'Следующий шаг — договор с менеджером.';
        } else if (st === 'pending_payment') {
          missTitle.style.display = 'none';
          hint.textContent = 'Следующий шаг — оплата подписки.';
        } else if (st === 'pending_profile' && !(state.trainer && state.trainer.is_catalog_visible === true)) {
          /* Тренер не просился в каталог — значит на проверку ничего не уходит, и говорить
             «осталось заполнить» нечестно: заполнять не нужно, продукт и так работает. */
          missTitle.style.display = 'none';
          hint.textContent =
            'Вы работаете по своей ссылке — этого достаточно, и профиль можно не доводить. ' +
            'Захотите, чтобы вас находили новые ученики, — включите «Показывать в каталоге» ' +
            'в разделе «Настройки», и мы подскажем, что нужно для карточки.';
        } else if (st === 'pending_profile') {
          var fbRaw = state.trainer && state.trainer.moderation_feedback;
          var fbTrim = (fbRaw != null && String(fbRaw).trim()) ? String(fbRaw).trim() : '';
          var fullGapLabels = [];
          if (d.full_profile_complete === false) {
            var fl = d.full_profile_missing_labels_ru;
            if (Array.isArray(fl) && fl.length) fullGapLabels = fl.slice();
          }
          if (fbTrim) {
            missTitle.style.display = 'none';
            hint.textContent = 'Модератор оставил комментарий — см. жёлтый блок выше. Внесите правки и снова сохраните анкету.';
          } else if (d.already_submitted_for_moderation) {
            hint.textContent = 'Ожидается проверка в админ-боте.';
            if (fullGapLabels.length) {
              missTitle.style.display = 'block';
              missTitle.textContent =
                'По желанию до полной карточки в каталоге (можно дополнить, пока идёт проверка):';
              appendGapListItems(fullGapLabels);
            } else if (d.full_profile_complete === false) {
              missTitle.style.display = 'none';
              hint.textContent =
                'Ожидается проверка в админ-боте. Для полноты карточки в каталоге остались необязательные поля — откройте вкладку «Анкета» и пролистайте блоки профиля.';
            } else {
              missTitle.style.display = 'none';
            }
          } else if (d.complete) {
            if (fullGapLabels.length) {
              missTitle.style.display = 'block';
              missTitle.textContent =
                'Для более полной карточки в каталоге (необязательно до первой отправки на проверку):';
              hint.textContent =
                'Обязательные пункты для проверки закрыты. Список ниже — что ещё можно усилить; поля во вкладке «Анкета» или отправьте анкету как есть.';
              appendGapListItems(fullGapLabels);
            } else {
              missTitle.style.display = 'none';
              hint.textContent =
                d.full_profile_complete === false
                  ? 'Обязательные пункты для проверки закрыты. Для полноты карточки в каталоге остались необязательные поля — откройте вкладку «Анкета».'
                  : 'Все пункты профиля для проверки и для каталога заполнены.';
            }
          } else {
            missTitle.style.display = 'block';
            missTitle.textContent = 'Осталось заполнить:';
            hint.textContent = '';
            appendGapListItems(d.missing_labels_ru || []);
          }
        } else {
          missTitle.style.display = 'none';
          hint.textContent = trainerStatusLabelRu(st) + '.';
        }
      }

      /** Склонение к «год» (1 год, 2 года, 5 лет, 11 лет) — как в catalog.html */
      function ruYearsWord(n) {
        if (n == null || !isFinite(Number(n))) return 'лет';
        n = Math.floor(Math.abs(Number(n)));
        var mod100 = n % 100;
        var mod10 = n % 10;
        if (mod100 >= 11 && mod100 <= 14) return 'лет';
        if (mod10 === 1) return 'год';
        if (mod10 >= 2 && mod10 <= 4) return 'года';
        return 'лет';
      }

      function renderHeroSummary() {
        var t = state.trainer || {};
        var p = t.profile || {};
        var d = state.moderation_readiness || {};
        var st = t.status ? String(t.status) : '';

        var firstName = (p.first_name || '').toString().trim();
        var lastName = (p.last_name || '').toString().trim();
        // Same sanitization as in form: Telegram command token may leak into name fields.
        if (firstName === '/invite') firstName = '';
        if (lastName === '/invite') lastName = '';
        var fullName = (firstName + ' ' + lastName).trim() || '—';

        var heroName = document.getElementById('heroName');
        if (heroName) heroName.textContent = fullName;

        var cityName = '—';
        if (p.city_id != null) {
          var cid = Number(p.city_id);
          var c = (state.cities || []).find(function(x) { return Number(x.id) === cid; });
          if (c && c.name) cityName = c.name;
        }

        var servicesCount = (t.services || []).length || 0;
        var arenasCount = (t.arena_ids || []).length || 0;

        var expNum =
          p.experience_years != null && p.experience_years !== '' ? Number(p.experience_years) : NaN;

        var subParts = [];
        if (cityName && cityName !== '—') subParts.push('Город: ' + cityName);
        if (!isNaN(expNum)) subParts.push('Опыт: ' + String(Math.floor(expNum)) + ' ' + ruYearsWord(expNum));
        if (!subParts.length) subParts.push('—');

        var heroSub = document.getElementById('heroSub');
        if (heroSub) heroSub.textContent = subParts.join(' · ');

        var heroStats = document.getElementById('heroStats');
        if (heroStats) {
          heroStats.innerHTML = '';

          var stat1 = document.createElement('div');
          stat1.className = 'hero-stat';
          stat1.textContent = 'Услуги: ' + servicesCount;
          heroStats.appendChild(stat1);

          var stat2 = document.createElement('div');
          stat2.className = 'hero-stat';
          stat2.textContent = 'Арены: ' + arenasCount;
          heroStats.appendChild(stat2);

          var chipExtra = moderationHeroChipText(st, d);
          if (chipExtra != null && chipExtra !== '') {
            var stat3 = document.createElement('div');
            stat3.className = 'hero-stat';
            stat3.textContent = chipExtra;
            heroStats.appendChild(stat3);
          }
        }

        var heroStatusPill = document.getElementById('heroStatusPill');
        if (heroStatusPill) {
          heroStatusPill.style.display = st ? 'inline-block' : 'none';
          if (st) {
            heroStatusPill.textContent = heroStatusLabelRu(st, d);
            heroStatusPill.classList.remove('ok', 'warn', 'pending');
            heroStatusPill.classList.add(pillClassForTrainerStatus(st, d));
          }
        }

        // Hero avatar: same source as catalog; tap opens upload (see wireHeroPhotoTap).
        var photos = t.photos || [];
        var first = photos[0];
        var heroPhoto = document.getElementById('heroPhoto');
        var heroPlaceholder = document.getElementById('heroPhotoPlaceholder');
        var heroFrame = document.getElementById('heroPhotoDropZone');
        var heroTap = document.getElementById('heroPhotoTap');
        var overlayTxt = document.getElementById('heroPhotoOverlayText');
        if (heroPhoto && heroPlaceholder) {
          heroPhoto.style.display = 'none';
          heroPlaceholder.style.display = 'flex';

          // Prefer same-origin proxy by file_key to avoid broken/cross-origin images.
          if (first && first.file_key) {
            heroPhoto.src = '/api/public/photos/' + encodeURIComponent(first.file_key);
            heroPhoto.alt = 'Фото профиля';
            heroPhoto.style.display = 'block';
            heroPlaceholder.style.display = 'none';
          } else if (first && (first.url || first.list_url)) {
            heroPhoto.src = first.url || first.list_url;
            heroPhoto.alt = 'Фото профиля';
            heroPhoto.style.display = 'block';
            heroPlaceholder.style.display = 'none';
          } else {
            heroPhoto.alt = '';
          }

          heroPhoto.onerror = function() {
            heroPhoto.style.display = 'none';
            heroPlaceholder.style.display = 'flex';
            if (heroFrame) heroFrame.classList.add('hero-photo-frame--empty');
            var ot = document.getElementById('heroPhotoOverlayText');
            var ht = document.getElementById('heroPhotoTap');
            if (ot) ot.textContent = 'Добавить фото';
            if (ht) ht.setAttribute('aria-label', 'Добавить фото профиля');
          };
        }
        var hasPhotoFromApi = !!(first && (first.file_key || first.url || first.list_url));
        if (heroFrame) heroFrame.classList.toggle('hero-photo-frame--empty', !hasPhotoFromApi);
        if (overlayTxt) overlayTxt.textContent = hasPhotoFromApi ? 'Изменить' : 'Добавить фото';
        if (heroTap) {
          heroTap.setAttribute('aria-label', hasPhotoFromApi ? 'Изменить фото профиля' : 'Добавить фото профиля');
        }

      }

      function eduModLabelRu(st) {
        var m = {
          pending_moderation: 'на модерации',
          approved: 'в анкете',
          rejected: 'отклонено',
        };
        return m[st] || (st || '');
      }

      function optionalStr(v) {
        var t = (v == null ? '' : String(v)).trim();
        return t === '' ? null : t;
      }

      function educationPhotoUrl(fileKey) {
        if (!fileKey) return '';
        return '/api/public/photos/' + encodeURIComponent(fileKey);
      }

      function normalizeEducationDocumentPhotos(raw) {
        if (!Array.isArray(raw)) return [];
        var out = [];
        var seen = {};
        raw.forEach(function(item) {
          if (!item || typeof item !== 'object') return;
          var fk = (item.file_key || '').toString().trim();
          var fkl = (item.file_key_list || '').toString().trim();
          if (!fk || seen[fk]) return;
          seen[fk] = true;
          out.push({
            file_key: fk,
            file_key_list: fkl ? fkl : null,
          });
        });
        return out;
      }

      function getCardEducationDocumentPhotos(card) {
        if (!card) return [];
        return normalizeEducationDocumentPhotos(card.__documentPhotos || []);
      }

      function setCardEducationDocumentPhotos(card, docs) {
        if (!card) return;
        card.__documentPhotos = normalizeEducationDocumentPhotos(docs);
      }

      function renderEducationDocumentPhotos(card) {
        if (!card) return;
        var listEl = card.querySelector('.edu-docs-list');
        var emptyEl = card.querySelector('.edu-docs-empty');
        var countEl = card.querySelector('.edu-docs-count');
        if (!listEl || !emptyEl || !countEl) return;
        var docs = getCardEducationDocumentPhotos(card);
        listEl.innerHTML = '';
        countEl.textContent = docs.length > 0 ? ('Фото: ' + docs.length) : 'Фото: 0';
        emptyEl.style.display = docs.length ? 'none' : 'block';
        docs.forEach(function(doc, idx) {
          var tile = document.createElement('div');
          tile.className = 'edu-doc-item';

          var previewBtn = document.createElement('button');
          previewBtn.type = 'button';
          previewBtn.className = 'edu-doc-thumb';
          previewBtn.setAttribute('aria-label', 'Открыть фото документа');
          previewBtn.addEventListener('click', function() {
            var href = educationPhotoUrl(doc.file_key);
            if (!href) return;
            if (tg && typeof tg.openLink === 'function') tg.openLink(href);
            else window.open(href, '_blank', 'noopener');
          });

          var img = document.createElement('img');
          img.alt = 'Документ #' + (idx + 1);
          var previewKey = doc.file_key_list || doc.file_key;
          img.src = educationPhotoUrl(previewKey);
          previewBtn.appendChild(img);
          tile.appendChild(previewBtn);

          var removeBtn = document.createElement('button');
          removeBtn.type = 'button';
          removeBtn.className = 'edu-doc-remove';
          removeBtn.setAttribute('aria-label', 'Удалить фото документа');
          removeBtn.textContent = '×';
          removeBtn.addEventListener('click', function() {
            var next = getCardEducationDocumentPhotos(card).filter(function(_, i) { return i !== idx; });
            setCardEducationDocumentPhotos(card, next);
            renderEducationDocumentPhotos(card);
            setDirty();
          });
          tile.appendChild(removeBtn);

          listEl.appendChild(tile);
        });
      }

      function setEducationDocsStatus(card, text, isError) {
        var status = card ? card.querySelector('.edu-docs-status') : null;
        if (!status) return;
        status.textContent = text || '';
        status.classList.toggle('edu-docs-status--error', !!isError);
      }

      function setEducationDocsBusy(card, busy) {
        if (!card) return;
        var uploadBtn = card.querySelector('.edu-doc-upload-btn');
        if (uploadBtn) uploadBtn.disabled = !!busy;
        card.classList.toggle('edu-card--docs-busy', !!busy);
      }

      function uploadEducationDocumentFile(card, file) {
        if (!card || !file) return Promise.resolve();
        if (!file.type || file.type.indexOf('image/') !== 0) {
          setEducationDocsStatus(card, 'Нужен файл изображения (JPEG/PNG/WebP).', true);
          haptic('error');
          return Promise.resolve();
        }
        if (file.size > MAX_TRAINER_PHOTO_BYTES) {
          setEducationDocsStatus(card, 'Файл слишком большой (макс. 15 МБ).', true);
          haptic('error');
          return Promise.resolve();
        }
        if (getCardEducationDocumentPhotos(card).length >= MAX_EDUCATION_DOCUMENT_PHOTOS) {
          setEducationDocsStatus(
            card,
            'Достигнут лимит: не более ' + MAX_EDUCATION_DOCUMENT_PHOTOS + ' фото документов.',
            true
          );
          haptic('error');
          return Promise.resolve();
        }
        setEducationDocsBusy(card, true);
        setEducationDocsStatus(card, 'Загружаем «' + (file.name || 'документ') + '»…', false);
        var fd = new FormData();
        fd.append('file', file, file.name || 'document.jpg');
        var h = {};
        if (initData()) h['X-Telegram-Init-Data'] = initData();
        return fetch('/api/webapp/trainer/education/documents', { method: 'POST', headers: h, body: fd })
          .then(parseJsonResponse)
          .then(function(o) {
            if (!o.ok) {
              var msg = (o.data && o.data.detail) ? String(o.data.detail) : 'Не удалось загрузить документ.';
              if (msg === 'File too large') msg = 'Файл слишком большой (макс. 15 МБ).';
              else if (msg === 'Not a valid image') msg = 'Нужен файл изображения (JPEG/PNG/WebP).';
              setEducationDocsStatus(card, msg, true);
              haptic('error');
              return;
            }
            var fileKey = (o.data && o.data.file_key) ? String(o.data.file_key).trim() : '';
            if (!fileKey) {
              setEducationDocsStatus(card, 'Сервер вернул пустой ключ файла.', true);
              haptic('error');
              return;
            }
            var docs = getCardEducationDocumentPhotos(card);
            docs.push({
              file_key: fileKey,
              file_key_list: (o.data && o.data.file_key_list) ? String(o.data.file_key_list).trim() : null,
            });
            setCardEducationDocumentPhotos(card, docs);
            renderEducationDocumentPhotos(card);
            setEducationDocsStatus(card, 'Документ добавлен. Не забудьте нажать «Сохранить изменения».', false);
            haptic('success');
            setDirty();
          })
          .catch(function() {
            setEducationDocsStatus(card, 'Ошибка сети при загрузке документа.', true);
            haptic('error');
          })
          .finally(function() {
            setEducationDocsBusy(card, false);
          });
      }

      function collectEducationPayload(card) {
        var typeEl = card.querySelector('.edu-type');
        var get = function(sel) {
          var n = card.querySelector(sel);
          return n ? n.value : '';
        };
        var body = {
          education_type: typeEl ? typeEl.value : 'formal_education',
          institution_name: get('.edu-inst').trim(),
          program_or_title: get('.edu-prog').trim(),
          degree_level: optionalStr(get('.edu-degree')),
          country: optionalStr(get('.edu-country')),
          city: optionalStr(get('.edu-city')),
          document_url: optionalStr(get('.edu-doc')),
          document_photos: getCardEducationDocumentPhotos(card),
          is_in_progress: !!(card.querySelector('.edu-inprog') && card.querySelector('.edu-inprog').checked),
        };
        var sy = get('.edu-sy').trim();
        var ey = get('.edu-ey').trim();
        body.start_year = sy === '' ? null : Number(sy);
        body.end_year = ey === '' ? null : Number(ey);
        if (sy !== '' && isNaN(body.start_year)) body.start_year = NaN;
        if (ey !== '' && isNaN(body.end_year)) body.end_year = NaN;
        return body;
      }

      function validateEducationPayload(body, errEl) {
        if (!errEl) return false;
        errEl.textContent = '';
        if ((body.institution_name || '').length < 2) {
          errEl.textContent = 'Укажите учебное заведение (не меньше 2 символов).';
          return false;
        }
        if ((body.program_or_title || '').length < 2) {
          errEl.textContent = 'Укажите программу или специализацию (не меньше 2 символов).';
          return false;
        }
        if (body.start_year != null && (isNaN(body.start_year) || body.start_year < 1950 || body.start_year > 2100)) {
          errEl.textContent = 'Год начала: 1950–2100.';
          return false;
        }
        if (body.end_year != null && (isNaN(body.end_year) || body.end_year < 1950 || body.end_year > 2100)) {
          errEl.textContent = 'Год окончания: 1950–2100.';
          return false;
        }
        if (
          body.start_year != null && !isNaN(body.start_year) &&
          body.end_year != null && !isNaN(body.end_year) &&
          body.start_year > body.end_year
        ) {
          errEl.textContent = 'Год начала не должен быть больше года окончания.';
          return false;
        }
        if (Array.isArray(body.document_photos) && body.document_photos.length > MAX_EDUCATION_DOCUMENT_PHOTOS) {
          errEl.textContent = 'Не более ' + MAX_EDUCATION_DOCUMENT_PHOTOS + ' фото документов.';
          return false;
        }
        return true;
      }

      function educationPayloadFromEntry(e) {
        return {
          education_type: e.education_type || 'formal_education',
          institution_name: (e.institution_name || '').trim(),
          program_or_title: (e.program_or_title || '').trim(),
          degree_level: optionalStr(e.degree_level),
          country: optionalStr(e.country),
          city: optionalStr(e.city),
          document_url: optionalStr(e.document_url),
          document_photos: normalizeEducationDocumentPhotos(e.document_photos),
          is_in_progress: !!e.is_in_progress,
          start_year: e.start_year != null ? Number(e.start_year) : null,
          end_year: e.end_year != null ? Number(e.end_year) : null,
        };
      }

      function buildEducationSnapshotFromState() {
        var items = (state.education_entries || []).map(function(e) {
          return { id: e.id, body: educationPayloadFromEntry(e) };
        });
        items.sort(function(a, b) { return Number(a.id) - Number(b.id); });
        var newWrap = document.getElementById('educationNewWrap');
        var newCard = newWrap && newWrap.style.display !== 'none' ? newWrap.querySelector('.edu-card') : null;
        var newDraft = null;
        if (newCard) {
          newDraft = { id: 'new', body: collectEducationPayload(newCard) };
        }
        return JSON.stringify({ items: items, newDraft: newDraft });
      }

      function buildEducationSnapshotFromDom() {
        var items = [];
        document.querySelectorAll('#educationEntries .edu-card').forEach(function(card) {
          var id = parseInt(card.getAttribute('data-edu-id'), 10);
          if (!isNaN(id)) items.push({ id: id, body: collectEducationPayload(card) });
        });
        items.sort(function(a, b) { return Number(a.id) - Number(b.id); });
        var newWrap = document.getElementById('educationNewWrap');
        var newCard = newWrap && newWrap.style.display !== 'none' ? newWrap.querySelector('.edu-card') : null;
        var newDraft = null;
        if (newCard) {
          newDraft = { id: 'new', body: collectEducationPayload(newCard) };
        }
        return JSON.stringify({ items: items, newDraft: newDraft });
      }

      /**
       * Deletes a persisted education row after confirm. Delegated from #educationEntries (capture)
       * because Telegram/iOS WebView often drops direct button click delivery on small controls.
       */
      function runEducationDelete(delBtn) {
        if (!delBtn || delBtn.disabled) return;
        var card = delBtn.closest('.edu-card');
        if (!card) return;
        var eduId = parseInt(card.getAttribute('data-edu-id'), 10);
        if (isNaN(eduId)) return;
        function doDelete() {
          delBtn.disabled = true;
          fetch(apiUrl('/trainer/education/' + encodeURIComponent(eduId)), {
            method: 'DELETE',
            headers: headers(),
          })
            .then(parseJsonResponse)
            .then(function(o) {
              if (o.ok) {
                haptic('success');
                return loadProfile().then(function() {
                  showSaveToast('Запись удалена', 'Список образования обновлён.', 'success');
                }).then(function() { return maybeAutoSubmitForModeration(); });
              }
              haptic('error');
              var msg = (o.data && o.data.detail) ? String(o.data.detail) : '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0443\u0434\u0430\u043b\u0438\u0442\u044c.';
              alert(msg);
            })
            .catch(function() {
              haptic('error');
              alert('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438.');
            })
            .finally(function() {
              delBtn.disabled = false;
            });
        }
        var q = '\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u044d\u0442\u0443 \u0437\u0430\u043f\u0438\u0441\u044c \u043e\u0431 \u043e\u0431\u0440\u0430\u0437\u043e\u0432\u0430\u043d\u0438\u0438?';
        if (typeof window.showAppConfirm === 'function') {
          window.showAppConfirm(q, { okText: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c', cancelText: '\u041e\u0442\u043c\u0435\u043d\u0430' }).then(function(ok) {
            if (!ok) return;
            doDelete();
          });
        } else if (typeof window.confirm === 'function' && window.confirm(q)) {
          doDelete();
        }
      }

      function makeEducationCard(e) {
        var card = document.createElement('div');
        card.className = 'edu-card';
        card.setAttribute('data-edu-id', String(e.id));

        var eduIdPersisted =
          e.id != null &&
          e.id !== 'new' &&
          String(e.id) !== 'new' &&
          String(e.id).trim() !== '' &&
          !isNaN(parseInt(String(e.id), 10));
        if (eduIdPersisted) {
          var head = document.createElement('div');
          head.className = 'edu-card-header';
          var titleEl = document.createElement('span');
          titleEl.className = 'edu-card-title';
          titleEl.textContent = 'Запись об образовании';
          var delBtn = document.createElement('button');
          delBtn.type = 'button';
          delBtn.className = 'edu-delete';
          delBtn.setAttribute('aria-label', 'Удалить запись');
          delBtn.textContent = '\u00D7';
          head.appendChild(titleEl);
          head.appendChild(delBtn);
          card.appendChild(head);
        }

        function addField(label, input) {
          var row = document.createElement('div');
          row.className = 'field';
          var lab = document.createElement('label');
          lab.textContent = label;
          row.appendChild(lab);
          row.appendChild(input);
          card.appendChild(row);
        }

        var sel = document.createElement('select');
        sel.className = 'edu-type';
        [['formal_education', 'Вуз / колледж / ССО'], ['course_or_certificate', 'Курсы / сертификат']].forEach(function(opt) {
          var o = document.createElement('option');
          o.value = opt[0];
          o.textContent = opt[1];
          sel.appendChild(o);
        });
        sel.value = e.education_type || 'formal_education';
        addField('Тип', sel);

        var inst = document.createElement('input');
        inst.type = 'text';
        inst.className = 'edu-inst';
        inst.maxLength = 160;
        inst.value = e.institution_name || '';
        addField('Учебное заведение', inst);

        var prog = document.createElement('input');
        prog.type = 'text';
        prog.className = 'edu-prog';
        prog.maxLength = 180;
        prog.value = e.program_or_title || '';
        addField('Программа / специализация', prog);

        var deg = document.createElement('input');
        deg.type = 'text';
        deg.className = 'edu-degree';
        deg.maxLength = 64;
        deg.value = e.degree_level || '';
        addField('Степень / квалификация (необязательно)', deg);

        var ctry = document.createElement('input');
        ctry.type = 'text';
        ctry.className = 'edu-country';
        ctry.maxLength = 64;
        ctry.value = e.country || '';
        addField('Страна', ctry);

        var city = document.createElement('input');
        city.type = 'text';
        city.className = 'edu-city';
        city.maxLength = 64;
        city.value = e.city || '';
        addField('Город', city);

        var sy = document.createElement('input');
        sy.type = 'number';
        sy.className = 'edu-sy';
        sy.min = 1950;
        sy.max = 2100;
        sy.placeholder = 'Год';
        sy.inputMode = 'numeric';
        if (e.start_year != null) sy.value = String(e.start_year);
        addField('Год начала', sy);

        var ey = document.createElement('input');
        ey.type = 'number';
        ey.className = 'edu-ey';
        ey.min = 1950;
        ey.max = 2100;
        ey.placeholder = 'Год';
        ey.inputMode = 'numeric';
        if (e.end_year != null) ey.value = String(e.end_year);
        addField('Год окончания', ey);

        var inprog = document.createElement('input');
        inprog.type = 'checkbox';
        inprog.className = 'edu-inprog';
        inprog.id = 'edu_inprog_' + String(e.id) + '_' + Math.random().toString(36).slice(2, 8);
        if (e.is_in_progress) inprog.checked = true;
        var inprogRow = document.createElement('div');
        inprogRow.className = 'arena-row';
        inprogRow.appendChild(inprog);
        var inprogLab = document.createElement('label');
        inprogLab.htmlFor = inprog.id;
        inprogLab.textContent = 'Обучаюсь сейчас';
        inprogLab.style.fontSize = '15px';
        inprogRow.appendChild(inprogLab);
        card.appendChild(inprogRow);

        var doc = document.createElement('input');
        doc.type = 'url';
        doc.className = 'edu-doc';
        doc.maxLength = 512;
        doc.placeholder = 'https://…';
        doc.value = e.document_url || '';
        addField('Ссылка на документ (необязательно)', doc);

        var docsBox = document.createElement('div');
        docsBox.className = 'edu-docs';
        docsBox.innerHTML =
          '<div class="edu-docs-head">' +
            '<div class="edu-docs-title">Фото дипломов и сертификатов</div>' +
            '<div class="edu-docs-count">Фото: 0</div>' +
          '</div>' +
          '<p class="edu-docs-hint">Добавьте несколько фото подтверждающих документов.</p>' +
          '<div class="edu-docs-list"></div>' +
          '<div class="edu-docs-empty">Пока нет загруженных фото документов.</div>' +
          '<div class="edu-doc-upload-row">' +
            '<button type="button" class="edu-doc-upload-btn">+ Загрузить фото документа</button>' +
            '<input type="file" class="edu-doc-upload-input" accept="image/jpeg,image/png,image/webp" multiple />' +
            '<p class="edu-docs-status" aria-live="polite"></p>' +
          '</div>';
        card.appendChild(docsBox);
        setCardEducationDocumentPhotos(card, normalizeEducationDocumentPhotos(e.document_photos));
        renderEducationDocumentPhotos(card);

        var uploadBtn = docsBox.querySelector('.edu-doc-upload-btn');
        var uploadInput = docsBox.querySelector('.edu-doc-upload-input');
        if (uploadBtn && uploadInput) {
          uploadBtn.addEventListener('click', function() {
            uploadInput.click();
          });
          uploadInput.addEventListener('change', function(ev) {
            var files = Array.prototype.slice.call((ev.target && ev.target.files) || []);
            if (!files.length) return;
            var chain = Promise.resolve();
            files.forEach(function(file) {
              chain = chain.then(function() {
                return uploadEducationDocumentFile(card, file);
              });
            });
            chain.finally(function() {
              uploadInput.value = '';
            });
          });
        }

        var err = document.createElement('p');
        err.className = 'edu-err';
        err.setAttribute('role', 'status');
        card.appendChild(err);

        var actions = document.createElement('div');
        actions.className = 'edu-actions';
        var mod = document.createElement('span');
        mod.className = 'edu-mod';
        mod.textContent = e.moderation_status ? ('Статус: ' + eduModLabelRu(e.moderation_status)) : '';
        actions.appendChild(mod);
        card.appendChild(actions);

        [sel, inst, prog, deg, ctry, city, sy, ey, inprog, doc].forEach(function(inp) {
          inp.addEventListener('input', function() {
            err.textContent = '';
            setDirty();
          });
          inp.addEventListener('change', function() {
            err.textContent = '';
            setDirty();
          });
        });

        return card;
      }

      function renderEducationNewForm() {
        var holder = document.getElementById('educationNewWrap');
        if (!holder) return;
        holder.innerHTML = '';
        var blank = {
          id: 'new',
          education_type: 'formal_education',
          institution_name: '',
          program_or_title: '',
          degree_level: null,
          country: null,
          city: null,
          start_year: null,
          end_year: null,
          is_in_progress: false,
          document_url: null,
          document_photos: [],
          moderation_status: null,
        };
        var card = makeEducationCard(blank);
        card.removeAttribute('data-edu-id');
        var hint = document.createElement('p');
        hint.className = 'field-hint';
        hint.style.marginTop = '10px';
        hint.textContent = 'Новая запись сохранится вместе с анкетой — нажмите «Сохранить изменения» внизу экрана.';
        holder.appendChild(card);
        holder.appendChild(hint);
      }

      function renderEducationEntries() {
        var wrap = document.getElementById('educationEntries');
        var newWrap = document.getElementById('educationNewWrap');
        wrap.innerHTML = '';
        var items = state.education_entries || [];
        if (items.length) {
          items.forEach(function(e) {
            wrap.appendChild(makeEducationCard(e));
          });
        }
        if (newWrap && newWrap.style.display !== 'none') {
          renderEducationNewForm();
        }
      }

      /** Per-tier prices from loaded trainer.services (codes -> number|null). */
      // TASK-043/047: price-input suffix follows the trainer's own city currency
      // (RU cities → ₽), instead of a hardcoded 'BYN'. `state.cities` items carry
      // `country` from CatalogRepository.list_cities().
      function getPriceSuffixForTrainer() {
        var cityId = state.trainer && state.trainer.profile ? state.trainer.profile.city_id : null;
        if (cityId == null) return 'BYN';
        var city = (state.cities || []).find(function(c) { return Number(c.id) === Number(cityId); });
        return (city && city.country === 'RU') ? '₽' : 'BYN';
      }

      function getServiceTierPricesByCode(serviceId) {
        var out = {};
        SERVICE_TIER_DEFS.forEach(function(d) { out[d.code] = null; });
        var list = state.trainer.services || [];
        var found = null;
        var i;
        for (i = 0; i < list.length; i++) {
          if (list[i].service_id === serviceId) { found = list[i]; break; }
        }
        if (!found) return out;
        if (found.price_tiers && found.price_tiers.length) {
          found.price_tiers.forEach(function(t) {
            var c = (t.tier_kind || '').toLowerCase();
            if (out.hasOwnProperty(c) && t.price_byn != null) out[c] = Number(t.price_byn);
          });
        } else {
          /* Legacy single-price rows only — price_byn is anchor, not a phantom adult tier. */
          if (found.price_byn != null && out.adult == null) out.adult = Number(found.price_byn);
          if (found.price_child_byn != null && out.child == null) out.child = Number(found.price_child_byn);
        }
        return out;
      }

      /** Optional per-service description for clients (trainer_services.description). */
      function getServiceDescription(serviceId) {
        var list = state.trainer.services || [];
        var i;
        for (i = 0; i < list.length; i++) {
          if (list[i].service_id === serviceId) {
            var d = list[i].description;
            return d != null ? String(d) : '';
          }
        }
        return '';
      }

      /** Optional logistics / not-included note (trainer_services.client_notice). */
      function getServiceClientNotice(serviceId) {
        var list = state.trainer.services || [];
        var i;
        for (i = 0; i < list.length; i++) {
          if (list[i].service_id === serviceId) {
            var n = list[i].client_notice;
            return n != null ? String(n) : '';
          }
        }
        return '';
      }

      /** Optional group per-seat price (trainer_services.group_price_cents); empty = fall back to tier anchor. */
      function getGroupPriceValue(serviceId) {
        var list = state.trainer.services || [];
        var i;
        for (i = 0; i < list.length; i++) {
          if (list[i].service_id === serviceId) {
            var g = list[i].group_price_byn;
            if (g != null && !isNaN(Number(g))) return Number(g);
          }
        }
        return null;
      }

      /**
       * New catalog service checked: copy which tariffs are enabled from a peer (checkboxes only).
       * Prices stay per-service — trainer enters BYN amounts separately so two services can differ on the same tier.
       */
      function primeNewServiceTiersFromPeers(serviceId) {
        var anyTier = false;
        SERVICE_TIER_ORDER.forEach(function(code) {
          var tcb = document.getElementById('svc_tier_' + serviceId + '_' + code);
          if (tcb && tcb.checked) anyTier = true;
        });
        if (anyTier) return;
        var peerId = null;
        state.servicesCatalog.forEach(function(s) {
          if (peerId != null) return;
          if (s.id === serviceId) return;
          var scb = document.getElementById('svc_' + s.id);
          if (!scb || !scb.checked) return;
          var hasTier = false;
          SERVICE_TIER_ORDER.forEach(function(code) {
            var tc = document.getElementById('svc_tier_' + s.id + '_' + code);
            if (tc && tc.checked) hasTier = true;
          });
          if (hasTier) peerId = s.id;
        });
        if (peerId == null) return;
        SERVICE_TIER_ORDER.forEach(function(code) {
          var ptcb = document.getElementById('svc_tier_' + peerId + '_' + code);
          var tcb = document.getElementById('svc_tier_' + serviceId + '_' + code);
          var pel = document.getElementById('price_tier_' + serviceId + '_' + code);
          if (!tcb || !pel) return;
          if (ptcb && ptcb.checked) {
            tcb.checked = true;
            pel.disabled = false;
            pel.value = '';
          }
        });
        var tbody = document.getElementById('svc_tier_body_' + serviceId);
        var tbtn = document.getElementById('svc_tier_toggle_' + serviceId);
        if (tbody && tbtn) {
          tbody.hidden = false;
          tbtn.setAttribute('aria-expanded', 'true');
          tbtn.textContent = 'Свернуть ▴';
        }
      }

      /** Onboarding: if nothing is checked yet, open the two most common tariffs. */
      function ensureDefaultServiceTiers(serviceId) {
        var any = false;
        SERVICE_TIER_ORDER.forEach(function(code) {
          var tcb = document.getElementById('svc_tier_' + serviceId + '_' + code);
          if (tcb && tcb.checked) any = true;
        });
        if (any) return;
        ['adult', 'child'].forEach(function(code) {
          var tcb = document.getElementById('svc_tier_' + serviceId + '_' + code);
          var pel = document.getElementById('price_tier_' + serviceId + '_' + code);
          if (tcb) tcb.checked = true;
          if (pel) {
            pel.disabled = false;
            pel.value = '';
          }
        });
      }

      function openServiceTierBody(serviceId) {
        var tbody = document.getElementById('svc_tier_body_' + serviceId);
        var tbtn = document.getElementById('svc_tier_toggle_' + serviceId);
        if (tbody) tbody.hidden = false;
        if (tbtn) {
          tbtn.setAttribute('aria-expanded', 'true');
          tbtn.textContent = 'Свернуть ▴';
        }
      }

      function renderServices() {
        var wrap = document.getElementById('servicesWrap');
        wrap.innerHTML = '';
        wrap.classList.add('svc-pick');
        var selectedIds = {};
        (state.trainer.services || []).forEach(function(s) {
          selectedIds[s.service_id] = true;
        });
        state.servicesCatalog.forEach(function(s) {
          var row = document.createElement('div');
          row.className = 'service-row svc-pick__row';
          var id = s.id;
          var isSelected = !!selectedIds[id];
          if (isSelected) row.classList.add('service-active');
          var pricesByCode = getServiceTierPricesByCode(id);

          var chk = document.createElement('input');
          chk.type = 'checkbox';
          chk.id = 'svc_' + id;
          chk.checked = isSelected;
          chk.className = 'svc-pick__check';

          var span = document.createElement('span');
          span.className = 'svc-name';
          span.textContent = s.name || ('Услуга #' + id);

          var head = document.createElement('label');
          head.className = 'svc-pick__head';
          head.appendChild(chk);
          head.appendChild(span);

          var toggleBtn = document.createElement('button');
          toggleBtn.type = 'button';
          toggleBtn.className = 'svc-tier-toggle';
          toggleBtn.id = 'svc_tier_toggle_' + id;
          toggleBtn.setAttribute('aria-expanded', 'false');
          toggleBtn.setAttribute('aria-controls', 'svc_tier_body_' + id);
          toggleBtn.textContent = 'Тарифы ▾';
          toggleBtn.title = 'Показать или скрыть список тарифов';
          toggleBtn.disabled = !isSelected;

          var tierBody = document.createElement('div');
          tierBody.className = 'svc-tier-body';
          tierBody.id = 'svc_tier_body_' + id;
          tierBody.hidden = true;

          var descBlock = document.createElement('div');
          descBlock.className = 'svc-desc-wrap';
          var descLabel = document.createElement('label');
          descLabel.className = 'svc-desc-label';
          descLabel.setAttribute('for', 'svc_desc_' + id);
          descLabel.textContent = 'Описание для клиентов (необязательно)';
          var descTa = document.createElement('textarea');
          descTa.className = 'svc-desc-textarea';
          descTa.id = 'svc_desc_' + id;
          descTa.rows = 3;
          descTa.maxLength = MAX_SERVICE_DESCRIPTION_CHARS;
          descTa.setAttribute('aria-label', 'Описание услуги для клиентов');
          descTa.placeholder = 'Кому подходит, формат занятия…';
          descTa.value = getServiceDescription(id);
          descTa.disabled = !isSelected;
          var descCount = document.createElement('div');
          descCount.className = 'svc-desc-count';
          descCount.id = 'svc_desc_count_' + id;
          function refreshSvcDescCount() {
            var len = (descTa.value || '').length;
            descCount.textContent = len + ' / ' + MAX_SERVICE_DESCRIPTION_CHARS;
          }
          refreshSvcDescCount();
          descTa.addEventListener('input', function() {
            refreshSvcDescCount();
            setDirty();
          });
          descTa.addEventListener('change', setDirty);
          descBlock.appendChild(descLabel);
          descBlock.appendChild(descTa);
          descBlock.appendChild(descCount);

          var noticeWrap = document.createElement('div');
          noticeWrap.className = 'svc-client-notice-wrap';
          var noticeKicker = document.createElement('div');
          noticeKicker.className = 'svc-client-notice-kicker';
          noticeKicker.textContent = 'Важно для клиента';
          var noticeHint = document.createElement('p');
          noticeHint.className = 'hint svc-client-notice-hint';
          noticeHint.textContent = 'Что не входит в стоимость? (необязательно)';

          var presetBar = document.createElement('div');
          presetBar.className = 'svc-client-notice-presets';
          presetBar.id = 'svc_notice_presets_' + id;
          presetBar.setAttribute('role', 'group');
          presetBar.setAttribute('aria-label', 'Что не входит в стоимость, необязательно');
          var initialNotice = getServiceClientNotice(id);
          var selectedPresetIds = inferTrainerNoticePresetIds(initialNotice);

          var noticeTa = document.createElement('textarea');
          noticeTa.className = 'svc-desc-textarea';
          noticeTa.id = 'svc_client_notice_' + id;
          noticeTa.rows = 3;
          noticeTa.maxLength = MAX_SERVICE_CLIENT_NOTICE_CHARS;
          noticeTa.setAttribute(
            'aria-label',
            'Что не входит в стоимость занятия (необязательно)'
          );
          noticeTa.placeholder =
            'Например: В стоимость не входят билеты на лёд (для ученика и тренера) и прокат коньков (при необходимости). Или соберите текст кнопками выше.';
          noticeTa.value = initialNotice;
          noticeTa.disabled = !isSelected;
          var noticeCount = document.createElement('div');
          noticeCount.className = 'svc-desc-count';
          noticeCount.id = 'svc_client_notice_count_' + id;
          function refreshClientNoticeCount() {
            var nlen = (noticeTa.value || '').length;
            noticeCount.textContent = nlen + ' / ' + MAX_SERVICE_CLIENT_NOTICE_CHARS;
          }
          function rebuildNoticeFromPresetSelection() {
            var ids = [];
            presetBar.querySelectorAll('button.svc-notice-preset-chip').forEach(function(btn) {
              if (btn.classList.contains('selected')) ids.push(btn.getAttribute('data-preset-id'));
            });
            noticeTa.value = buildTrainerServiceNoticeFromPresetIds(ids);
            refreshClientNoticeCount();
            setDirty();
          }
          function syncPresetChipsFromNoticeText() {
            var ids = inferTrainerNoticePresetIds(noticeTa.value);
            presetBar.querySelectorAll('button.svc-notice-preset-chip').forEach(function(btn) {
              var pid = btn.getAttribute('data-preset-id');
              btn.classList.toggle('selected', ids.indexOf(pid) >= 0);
            });
          }
          SERVICE_NOTICE_PRESETS.forEach(function(pr) {
            var pb = document.createElement('button');
            pb.type = 'button';
            pb.className = 'svc-notice-preset-chip' + (selectedPresetIds.indexOf(pr.id) >= 0 ? ' selected' : '');
            pb.setAttribute('data-preset-id', pr.id);
            pb.textContent = pr.label;
            pb.disabled = !isSelected;
            pb.addEventListener('click', function() {
              if (noticeTa.disabled) return;
              pb.classList.toggle('selected');
              rebuildNoticeFromPresetSelection();
            });
            presetBar.appendChild(pb);
          });
          refreshClientNoticeCount();
          noticeTa.addEventListener('input', function() {
            refreshClientNoticeCount();
            setDirty();
          });
          noticeTa.addEventListener('change', setDirty);
          noticeTa.addEventListener('blur', syncPresetChipsFromNoticeText);
          noticeWrap.appendChild(noticeKicker);
          noticeWrap.appendChild(noticeHint);
          noticeWrap.appendChild(presetBar);
          noticeWrap.appendChild(noticeTa);
          noticeWrap.appendChild(noticeCount);

          var tierWrap = document.createElement('div');
          tierWrap.className = 'svc-tier-grid' + (isSelected ? '' : ' is-disabled');
          tierWrap.id = 'svc_tier_grid_' + id;

          function bindTierRow(def) {
            var code = def.code;
            var tr = document.createElement('div');
            tr.className = 'svc-tier-row';
            var tchk = document.createElement('input');
            tchk.type = 'checkbox';
            tchk.className = 'tier-check';
            tchk.id = 'svc_tier_' + id + '_' + code;
            var pv = pricesByCode[code];
            var hasPrice = pv != null && !isNaN(pv);
            tchk.checked = isSelected && hasPrice;
            var tlab = document.createElement('span');
            tlab.className = 'tier-name';
            tlab.textContent = def.label;
            var pw = document.createElement('div');
            pw.className = 'tier-price-wrap';
            var inp = document.createElement('input');
            inp.type = 'number';
            inp.step = '0.01';
            inp.min = '0';
            inp.inputMode = 'decimal';
            inp.placeholder = '0';
            inp.id = 'price_tier_' + id + '_' + code;
            inp.disabled = !isSelected || !tchk.checked;
            if (hasPrice) inp.value = String(pv);
            var suf = document.createElement('span');
            suf.className = 'price-suffix';
            suf.textContent = getPriceSuffixForTrainer();
            pw.appendChild(inp);
            pw.appendChild(suf);
            tr.appendChild(tchk);
            tr.appendChild(tlab);
            tr.appendChild(pw);
            tierWrap.appendChild(tr);

            function syncTierInput() {
              inp.disabled = !chk.checked || !tchk.checked;
              if (!tchk.checked) {
                inp.value = '';
                setDirty();
                return;
              }
              setDirty();
            }
            tchk.addEventListener('change', syncTierInput);
            function onTierPriceInput() {
              setDirty();
            }
            inp.addEventListener('input', onTierPriceInput);
            inp.addEventListener('change', onTierPriceInput);
          }
          SERVICE_TIER_DEFS.forEach(bindTierRow);

          var groupWrap = document.createElement('div');
          groupWrap.className = 'svc-group-price-wrap';
          var groupLab = document.createElement('label');
          groupLab.className = 'svc-desc-label';
          groupLab.setAttribute('for', 'price_group_' + id);
          groupLab.textContent = 'Групповые занятия: цена за человека';
          var groupHint = document.createElement('div');
          groupHint.className = 'svc-group-hint';
          groupHint.textContent =
            'Если пусто — на группу действует та же цена, что в тарифах выше. Заполните, если за человека на групповом занятии нужна другая сумма.';
          var gRow = document.createElement('div');
          gRow.className = 'svc-tier-row svc-group-price-row';
          /* Same 3-col grid as tariff rows — else the lone .tier-price-wrap sits in col1 and the block «прыгает». */
          var gSpacer = document.createElement('span');
          gSpacer.className = 'svc-tier-check-spacer';
          gSpacer.setAttribute('aria-hidden', 'true');
          var gMid = document.createElement('span');
          gMid.className = 'tier-name svc-group-price-row__mid';
          gMid.setAttribute('aria-hidden', 'true');
          var gpw = document.createElement('div');
          gpw.className = 'tier-price-wrap';
          var gInp = document.createElement('input');
          gInp.type = 'number';
          gInp.step = '0.01';
          gInp.min = '0';
          gInp.id = 'price_group_' + id;
          gInp.disabled = !isSelected;
          gInp.setAttribute('aria-label', 'Цена за человека на групповом занятии, ' + getPriceSuffixForTrainer());
          var gpv = getGroupPriceValue(id);
          if (gpv != null && !isNaN(gpv)) gInp.value = String(gpv);
          var gsuf = document.createElement('span');
          gsuf.className = 'price-suffix';
          gsuf.textContent = getPriceSuffixForTrainer();
          gpw.appendChild(gInp);
          gpw.appendChild(gsuf);
          gRow.appendChild(gSpacer);
          gRow.appendChild(gMid);
          gRow.appendChild(gpw);
          groupWrap.appendChild(groupLab);
          groupWrap.appendChild(groupHint);
          groupWrap.appendChild(gRow);
          gInp.addEventListener('input', setDirty);
          gInp.addEventListener('change', setDirty);

          tierBody.appendChild(descBlock);
          tierBody.appendChild(noticeWrap);
          tierBody.appendChild(tierWrap);
          tierBody.appendChild(groupWrap);

          if (isSelected && document.body.classList.contains('ob-flow-open')) {
            tierBody.hidden = false;
            toggleBtn.setAttribute('aria-expanded', 'true');
            toggleBtn.textContent = 'Свернуть ▴';
          }

          toggleBtn.addEventListener('click', function() {
            if (!chk.checked) return;
            tierBody.hidden = !tierBody.hidden;
            var open = !tierBody.hidden;
            toggleBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
            toggleBtn.textContent = open ? 'Свернуть ▴' : 'Тарифы ▾';
          });

          chk.addEventListener('change', function() {
            row.classList.toggle('service-active', chk.checked);
            tierWrap.classList.toggle('is-disabled', !chk.checked);
            toggleBtn.disabled = !chk.checked;
            if (!chk.checked) {
              tierBody.hidden = true;
              tierBody.classList.remove('svc-tier-body--error');
              toggleBtn.setAttribute('aria-expanded', 'false');
              toggleBtn.textContent = 'Тарифы ▾';
              tierWrap.classList.remove('svc-tier-grid--error');
              var sde = document.getElementById('svc_desc_' + id);
              if (sde) {
                sde.value = '';
                sde.disabled = true;
              }
              var sdc = document.getElementById('svc_desc_count_' + id);
              if (sdc) sdc.textContent = '0 / ' + MAX_SERVICE_DESCRIPTION_CHARS;
              var sne = document.getElementById('svc_client_notice_' + id);
              if (sne) {
                sne.value = '';
                sne.disabled = true;
              }
              var snc = document.getElementById('svc_client_notice_count_' + id);
              if (snc) snc.textContent = '0 / ' + MAX_SERVICE_CLIENT_NOTICE_CHARS;
              var spBar = document.getElementById('svc_notice_presets_' + id);
              if (spBar) {
                spBar.querySelectorAll('button.svc-notice-preset-chip').forEach(function(b) {
                  b.classList.remove('selected');
                  b.disabled = true;
                });
              }
              SERVICE_TIER_ORDER.forEach(function(code) {
                var tcb = document.getElementById('svc_tier_' + id + '_' + code);
                var pel = document.getElementById('price_tier_' + id + '_' + code);
                if (tcb) tcb.checked = false;
                if (pel) { pel.value = ''; pel.disabled = true; }
              });
              var pge = document.getElementById('price_group_' + id);
              if (pge) {
                pge.value = '';
                pge.disabled = true;
              }
            } else {
              var sdeOn = document.getElementById('svc_desc_' + id);
              if (sdeOn) sdeOn.disabled = false;
              var sneOn = document.getElementById('svc_client_notice_' + id);
              if (sneOn) sneOn.disabled = false;
              var spBarOn = document.getElementById('svc_notice_presets_' + id);
              if (spBarOn) {
                spBarOn.querySelectorAll('button.svc-notice-preset-chip').forEach(function(b) {
                  b.disabled = false;
                });
              }
              SERVICE_TIER_ORDER.forEach(function(code) {
                var pel = document.getElementById('price_tier_' + id + '_' + code);
                var tcb = document.getElementById('svc_tier_' + id + '_' + code);
                if (pel && tcb) pel.disabled = !tcb.checked;
              });
              var pgeOn = document.getElementById('price_group_' + id);
              if (pgeOn) pgeOn.disabled = false;
              primeNewServiceTiersFromPeers(id);
              ensureDefaultServiceTiers(id);
              openServiceTierBody(id);
            }
            setDirty();
          });

          row.appendChild(head);
          row.appendChild(toggleBtn);
          var onReq = document.createElement('p');
          onReq.className = 'svc-on-request-hint';
          onReq.id = 'svc_on_request_' + id;
          onReq.textContent = 'Клиент видит: по запросу';
          onReq.hidden = true;
          var block = document.createElement('div');
          block.className = 'service-block svc-pick__item';
          block.appendChild(row);
          block.appendChild(onReq);
          block.appendChild(tierBody);
          wrap.appendChild(block);
        });
        syncOnRequestHints();
      }

      function toggleCanonicalArena(id, on) {
        var ids = canonicalArenaIds();
        var n = Number(id);
        var i = ids.indexOf(n);
        if (on && i < 0) ids.push(n);
        if (!on && i >= 0) ids.splice(i, 1);
        setCanonicalArenaIds(ids);
        ensurePrimaryArena();
        if (profileArenaPickerEnabled()) updateArenaPickerUi();
        updatePrimaryArenaUi();
        setDirty();
      }

      function setPrimaryArena(id) {
        if (!state.trainer) return;
        var n = Number(id);
        if (canonicalArenaIds().indexOf(n) < 0) return;
        state.trainer.primary_arena_id = n;
        if (profileArenaPickerEnabled()) updateArenaChips();
        setDirty();
      }

      function openArenaCreateForm(prefillName) {
        var box = document.getElementById('arenaEmptyActions');
        if (!box) return;
        state.arenaCreateOpen = true;
        box.hidden = false;
        renderArenaCreateForm(box, { name: prefillName || '' });
      }

      function closeArenaCreateForm() {
        state.arenaCreateOpen = false;
        var hasCity = !!(state.trainer && state.trainer.profile && state.trainer.profile.city_id);
        renderArenaAddEntryPoint(hasCity);
      }

      function bindArenaPicker() {
        if (arenaPickerBound) return;
        var inp = document.getElementById('arenaSearchInput');
        if (!inp) return;
        arenaPickerBound = true;
        inp.addEventListener('input', function() {
          state.arenaSearchQuery = inp.value;
          if (state.arenaSearchTimer) clearTimeout(state.arenaSearchTimer);
          state.arenaSearchTimer = setTimeout(function() {
            state.arenaSearchTimer = null;
            updateArenaResults();
          }, ARENA_PICKER_SEARCH_DEBOUNCE_MS);
        });
        inp.addEventListener('keydown', function(e) {
          if (e.key === 'Enter') e.preventDefault();
        });
      }

      function updateArenaChips() {
        var chips = document.getElementById('arenaChips');
        if (!chips) return;
        var ids = canonicalArenaIds();
        if (!ids.length) {
          chips.innerHTML = '';
          chips.hidden = true;
          return;
        }
        chips.hidden = false;
        var primary = state.trainer && state.trainer.primary_arena_id != null
          ? Number(state.trainer.primary_arena_id)
          : null;
        var html = '';
        ids.forEach(function(id) {
          var a = findArenaById(id);
          var name = (a && a.name) ? a.name : ('Арена #' + id);
          var isPrimary = primary === id;
          html += '<div class="arena-chip' + (isPrimary ? ' arena-chip--primary' : '') + '">';
          html += '<span class="arena-chip__name">' + escapeArenaHtml(name) + '</span>';
          if (ids.length > 1) {
            html += '<button type="button" class="arena-chip__star" data-arena-star="' + id + '"'
              + ' aria-pressed="' + (isPrimary ? 'true' : 'false') + '"'
              + ' aria-label="' + (isPrimary ? 'Основная площадка' : 'Сделать основной') + '">★</button>';
          }
          var shown = arenaIsPublic(id);
          html += '<button type="button" class="arena-chip__public" data-arena-public="' + id + '"'
            + ' aria-pressed="' + (shown ? 'true' : 'false') + '"'
            + ' title="' + (shown ? 'Показывать в карточке каталога' : 'Только для расписания, скрыта из каталога') + '">'
            + (shown ? 'в карточке' : 'только слоты') + '</button>';
          html += '<button type="button" class="arena-chip__remove" data-arena-remove="' + id + '" aria-label="Убрать">×</button>';
          html += '</div>';
        });
        chips.innerHTML = html;
        chips.querySelectorAll('[data-arena-star]').forEach(function(btn) {
          btn.addEventListener('click', function() {
            setPrimaryArena(btn.getAttribute('data-arena-star'));
          });
        });
        chips.querySelectorAll('[data-arena-public]').forEach(function(btn) {
          btn.addEventListener('click', function() {
            var aid = Number(btn.getAttribute('data-arena-public'));
            if (!aid) return;
            var next = !arenaIsPublic(aid);
            setArenaIsPublicLocal(aid, next);
            updateArenaChips();
            fetch(apiUrl('/trainer/arenas/' + aid + '/public'), {
              method: 'PATCH',
              headers: headersJson(),
              body: JSON.stringify({ is_public: next }),
            }).then(function(r) {
              return r.json().then(function(data) {
                return { ok: r.ok, data: data };
              });
            }).then(function(o) {
              if (o.ok && o.data && o.data.trainer) {
                state.trainer = o.data.trainer;
                updateArenaChips();
                return;
              }
              if (!o.ok) {
                setArenaIsPublicLocal(aid, !next);
                updateArenaChips();
              }
            }).catch(function() {
              setArenaIsPublicLocal(aid, !next);
              updateArenaChips();
            });
          });
        });
        chips.querySelectorAll('[data-arena-remove]').forEach(function(btn) {
          btn.addEventListener('click', function() {
            toggleCanonicalArena(btn.getAttribute('data-arena-remove'), false);
          });
        });
      }

      function appendArenaCreateCta(results, query) {
        var createBtn = document.createElement('button');
        createBtn.type = 'button';
        createBtn.className = 'filter-btn arena-empty-btn arena-empty-btn--primary';
        createBtn.textContent = query
          ? ('Добавить «' + query + '»')
          : 'Нет в списке — добавить площадку';
        createBtn.addEventListener('click', function() {
          openArenaCreateForm(query || '');
        });
        results.appendChild(createBtn);
      }

      function updateArenaResults() {
        var results = document.getElementById('arenaResults');
        if (!results) return;
        var hasCity = !!(state.trainer && state.trainer.profile && state.trainer.profile.city_id);
        if (!hasCity) {
          results.innerHTML = '';
          return;
        }
        var inp = document.getElementById('arenaSearchInput');
        var query = inp ? inp.value : (state.arenaSearchQuery || '');
        state.arenaSearchQuery = query;
        var qNorm = normalizeArenaSearch(query);
        var selected = {};
        canonicalArenaIds().forEach(function(id) { selected[id] = true; });

        if (!qNorm) {
          results.innerHTML = '';
          var idle = document.createElement('p');
          idle.className = 'arena-results-idle';
          var n = (state.arenasList || []).length;
          idle.textContent = n
            ? ('Начните вводить название или адрес — в городе ' + n + ' площадок.')
            : 'В этом городе пока нет площадок в справочнике.';
          results.appendChild(idle);
          if (!state.arenaCreateOpen) appendArenaCreateCta(results, '');
          return;
        }

        var matches = [];
        (state.arenasList || []).forEach(function(a) {
          if (arenaMatchesQuery(a, query)) matches.push(a);
        });

        results.innerHTML = '';
        if (!matches.length) {
          var empty = document.createElement('p');
          empty.className = 'arena-results-empty';
          empty.textContent = 'Ничего не нашлось.';
          results.appendChild(empty);
          if (!state.arenaCreateOpen) appendArenaCreateCta(results, query.trim());
          return;
        }

        var shown = matches.slice(0, ARENA_PICKER_MAX_RESULTS);
        shown.forEach(function(a) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'arena-result' + (selected[a.id] ? ' is-selected' : '');
          btn.setAttribute('role', 'option');
          btn.setAttribute('aria-selected', selected[a.id] ? 'true' : 'false');
          var nameEl = document.createElement('span');
          nameEl.className = 'arena-result__name';
          nameEl.textContent = a.name || ('Арена #' + a.id);
          if (a.is_confirmed === false) {
            nameEl.appendChild(document.createTextNode(' '));
            var badge = document.createElement('span');
            badge.className = 'arena-unconfirmed-badge';
            badge.textContent = 'на проверке';
            nameEl.appendChild(badge);
          }
          btn.appendChild(nameEl);
          if (a.address) {
            var addrEl = document.createElement('span');
            addrEl.className = 'arena-result__addr';
            addrEl.textContent = a.address;
            btn.appendChild(addrEl);
          }
          btn.addEventListener('click', function() {
            toggleCanonicalArena(a.id, !selected[a.id]);
          });
          results.appendChild(btn);
        });
        if (matches.length > ARENA_PICKER_MAX_RESULTS) {
          var more = document.createElement('p');
          more.className = 'arena-results-more';
          more.textContent = 'Ещё ' + (matches.length - ARENA_PICKER_MAX_RESULTS) + ' — уточните запрос.';
          results.appendChild(more);
        }
      }

      function updateArenaPickerUi() {
        bindArenaPicker();
        updateArenaChips();
        updateArenaResults();
      }

      function updatePrimaryArenaUi() {
        var wrap = document.getElementById('primaryArenaWrap');
        if (!wrap) return;
        if (profileArenaPickerEnabled()) {
          wrap.style.display = 'none';
          wrap.innerHTML = '';
          return;
        }
        var selected = [];
        state.arenasList.forEach(function(a) {
          var cb = document.getElementById('arena_' + a.id);
          if (cb && cb.checked) selected.push(a);
        });
        if (selected.length < 2) {
          wrap.style.display = 'none';
          wrap.innerHTML = '';
          return;
        }
        wrap.style.display = 'block';
        var cur = state.trainer.primary_arena_id != null ? Number(state.trainer.primary_arena_id) : null;
        var selIds = selected.map(function(x) { return x.id; });
        if (!cur || selIds.indexOf(cur) < 0) {
          cur = selected[0].id;
        }
        var html = '<p class="hint" style="margin:0 0 10px;">Основная площадка для онлайн-записи, когда клиент выбирает «Любая арена» в каталоге</p>';
        selected.forEach(function(a) {
          var id = 'primary_arena_' + a.id;
          html += '<div class="arena-row arena-active" style="margin-bottom:8px;"><label style="display:flex;align-items:center;gap:10px;cursor:pointer;">';
          html += '<input type="radio" name="primary_arena" id="' + id + '" value="' + a.id + '"' + (a.id === cur ? ' checked' : '') + ' />';
          html += '<span>' + (a.name || ('Арена #' + a.id)) + '</span></label></div>';
        });
        wrap.innerHTML = html;
        wrap.querySelectorAll('input[name="primary_arena"]').forEach(function(inp) {
          inp.addEventListener('change', function() {
            if (state.trainer) state.trainer.primary_arena_id = parseInt(inp.value, 10);
            setDirty();
          });
        });
      }

      function trainerArenaSetupFormat() {
        var t = state.trainer || {};
        return (t.arena_work_format || '').trim();
      }

      function arenasStepCompleteLocally() {
        var t = state.trainer || {};
        if ((t.arena_ids || []).length) return true;
        var fmt = trainerArenaSetupFormat();
        if (fmt === 'mobile') return true;
        if (fmt === 'pending_request' && (t.arena_request_text || '').trim()) return true;
        return false;
      }

      function clearArenaSetupMessages() {
        var st = document.getElementById('arenaSetupStatus');
        var er = document.getElementById('err_arena_setup');
        if (st) {
          st.hidden = true;
          st.textContent = '';
          st.className = 'arena-setup-status';
        }
        if (er) {
          er.hidden = true;
          er.textContent = '';
        }
      }

      function showArenaSetupStatus(msg, kind) {
        var st = document.getElementById('arenaSetupStatus');
        if (!st) return;
        st.textContent = msg;
        st.hidden = !msg;
        st.className = 'arena-setup-status';
        if (kind === 'ok') st.className += ' arena-setup-status--ok';
        if (kind === 'warn') st.className += ' arena-setup-status--warn';
      }

      function postArenaSetup(body) {
        return fetch(apiUrl('/trainer/profile/arena-setup'), {
          method: 'POST',
          headers: headersJson(),
          body: JSON.stringify(body),
        }).then(function(r) {
          return r.json().then(function(data) {
            return { ok: r.ok, status: r.status, data: data };
          });
        });
      }

      function arenaSetupErrorDetail(data, status) {
        if (!data) return 'Не удалось сохранить. Попробуйте ещё раз.';
        if (typeof data.detail === 'string') return data.detail;
        if (Array.isArray(data.detail)) return 'Проверьте заполненные поля и попробуйте снова.';
        if (status === 403) return 'Сессия устарела — перезапустите мини-приложение.';
        return 'Не удалось сохранить. Попробуйте ещё раз.';
      }

      function afterArenaSetupSuccess(data) {
        if (data && data.trainer) state.trainer = data.trainer;
        if (data && data.moderation_readiness) state.moderation_readiness = data.moderation_readiness;
        state.arenaCreateOpen = false;
        resetArenaSearch();
        var cid = state.trainer && state.trainer.profile ? state.trainer.profile.city_id : null;
        loadArenasForCity(cid).then(function() {
          renderArenas();
          renderModeration();
          syncProfileBlockTourBar();
          if (state.profileBlockTourActive && profileBlockTourEffectiveStepKey() === 'arenas') {
            var missingRaw =
              (state.moderation_readiness && state.moderation_readiness.tt_minimal_missing_fields) || [];
            var missing = profileBlockTourMissingStepKeys(missingRaw);
            if (!profileBlockTourUiStepStillMissing('arenas', missing)) {
              profileBlockTourAdvanceOneStep('arenas', missing);
              syncProfileBlockTourBar();
            }
          }
        });
      }

      function renderArenaSupportBlock(box) {
        var sep = document.createElement('p');
        sep.className = 'hint arena-empty-support-lead';
        sep.textContent = 'Или напишите в поддержку — поможем вручную:';
        box.appendChild(sep);

        var ta = document.createElement('textarea');
        ta.className = 'input arena-support-textarea';
        ta.rows = 3;
        ta.maxLength = 4000;
        ta.placeholder = 'Кратко опишите ситуацию…';
        box.appendChild(ta);

        var sbtn = document.createElement('button');
        sbtn.type = 'button';
        sbtn.className = 'filter-btn arena-empty-btn';
        sbtn.textContent = 'Написать в поддержку';
        var sstat = document.createElement('p');
        sstat.className = 'arena-setup-status';
        sstat.hidden = true;
        sbtn.addEventListener('click', function() {
          var text = (ta.value || '').trim();
          if (!text) {
            sstat.textContent = 'Напишите пару слов — что случилось.';
            sstat.className = 'arena-setup-status arena-setup-status--warn';
            sstat.hidden = false;
            return;
          }
          sbtn.disabled = true;
          fetch(apiUrl('/support'), {
            method: 'POST',
            headers: headersJson(),
            body: JSON.stringify({ message: text, role: 'trainer' }),
          })
            .then(function(r) {
              return r.json().then(function(d) {
                return { ok: r.ok, data: d };
              });
            })
            .then(function(o) {
              sbtn.disabled = false;
              if (o.ok && o.data && o.data.ok !== false) {
                ta.value = '';
                sstat.textContent = 'Сообщение отправлено — ответ придёт в тренерском боте.';
                sstat.className = 'arena-setup-status arena-setup-status--ok';
                sstat.hidden = false;
              } else {
                sstat.textContent = 'Не удалось отправить. Попробуйте через /guide в боте.';
                sstat.className = 'arena-setup-status arena-setup-status--warn';
                sstat.hidden = false;
              }
            })
            .catch(function() {
              sbtn.disabled = false;
              sstat.textContent = 'Ошибка сети. Попробуйте через /guide в боте.';
              sstat.className = 'arena-setup-status arena-setup-status--warn';
              sstat.hidden = false;
            });
        });
        box.appendChild(sbtn);
        box.appendChild(sstat);
      }

      function renderArenaDuplicateWarning(dupBox, duplicates, doSubmit) {
        dupBox.hidden = false;
        dupBox.innerHTML = '';
        var msg = document.createElement('p');
        msg.style.margin = '0 0 8px';
        msg.textContent =
          duplicates.length === 1
            ? 'Похоже, такая площадка уже есть: «' +
              (duplicates[0].name || '') +
              '»' +
              (duplicates[0].address ? ' (' + duplicates[0].address + ')' : '') +
              '.'
            : 'Похоже, такие площадки уже есть в списке.';
        dupBox.appendChild(msg);

        duplicates.forEach(function(d) {
          var useBtn = document.createElement('button');
          useBtn.type = 'button';
          useBtn.className = 'filter-btn arena-empty-btn';
          useBtn.style.marginBottom = '6px';
          useBtn.textContent = 'Выбрать «' + (d.name || ('Арена #' + d.arena_id)) + '»';
          useBtn.addEventListener('click', function() {
            selectExistingArenaCheckbox(d.arena_id);
          });
          dupBox.appendChild(useBtn);
        });

        var again = document.createElement('button');
        again.type = 'button';
        again.className = 'filter-btn arena-empty-btn arena-empty-btn--primary';
        again.textContent = 'Всё равно создать новую';
        again.addEventListener('click', function() {
          doSubmit(true);
        });
        dupBox.appendChild(again);
      }

      function selectExistingArenaCheckbox(arenaId) {
        var n = Number(arenaId);
        var ids = canonicalArenaIds();
        if (n && ids.indexOf(n) < 0) ids.push(n);
        setCanonicalArenaIds(ids);
        ensurePrimaryArena();
        state.arenaCreateOpen = false;
        if (profileArenaPickerEnabled()) {
          renderArenaAddEntryPoint(!!(state.trainer && state.trainer.profile && state.trainer.profile.city_id));
          updateArenaPickerUi();
          setDirty();
          return;
        }
        renderArenas();
        var cb = document.getElementById('arena_' + arenaId);
        if (cb) {
          cb.checked = true;
          cb.dispatchEvent(new Event('change'));
        }
      }

      function renderArenaCreateForm(box, prefills) {
        prefills = prefills || {};
        box.innerHTML = '';
        clearArenaSetupMessages();
        var title = document.createElement('p');
        title.className = 'hint arena-empty-lead';
        title.textContent = 'Арена появится в расписании сразу — команда проверит её позже.';
        box.appendChild(title);

        var nameWrap = document.createElement('div');
        nameWrap.className = 'field';
        var nameLab = document.createElement('label');
        nameLab.textContent = 'Название площадки';
        nameLab.setAttribute('for', 'arenaCreateName');
        var nameInp = document.createElement('input');
        nameInp.type = 'text';
        nameInp.id = 'arenaCreateName';
        nameInp.className = 'input';
        nameInp.maxLength = 128;
        nameInp.placeholder = 'Например, Ледовый дворец на ул. …';
        if (prefills.name) nameInp.value = String(prefills.name);
        nameWrap.appendChild(nameLab);
        nameWrap.appendChild(nameInp);
        box.appendChild(nameWrap);

        var addrWrap = document.createElement('div');
        addrWrap.className = 'field';
        var addrLab = document.createElement('label');
        addrLab.textContent = 'Адрес';
        addrLab.setAttribute('for', 'arenaCreateAddress');
        var addrInp = document.createElement('input');
        addrInp.type = 'text';
        addrInp.id = 'arenaCreateAddress';
        addrInp.className = 'input';
        addrInp.maxLength = 512;
        addrInp.placeholder = 'Улица, дом';
        addrWrap.appendChild(addrLab);
        addrWrap.appendChild(addrInp);
        box.appendChild(addrWrap);

        var dupBox = document.createElement('div');
        dupBox.id = 'arenaDuplicateWarning';
        dupBox.className = 'arena-setup-status arena-setup-status--warn';
        dupBox.hidden = true;
        box.appendChild(dupBox);

        var actions = document.createElement('div');
        actions.className = 'arena-empty-actions-row';
        var submit = document.createElement('button');
        submit.type = 'button';
        submit.className = 'filter-btn arena-empty-btn arena-empty-btn--primary';
        submit.textContent = 'Добавить арену';
        var back = document.createElement('button');
        back.type = 'button';
        back.className = 'filter-btn arena-empty-btn';
        back.textContent = 'Отмена';
        back.addEventListener('click', function() {
          closeArenaCreateForm();
        });

        function doSubmit(confirmDuplicate) {
          var nm = (nameInp.value || '').trim();
          var addr = (addrInp.value || '').trim();
          var er = document.getElementById('err_arena_setup');
          if (!nm || !addr) {
            if (er) {
              er.textContent = !nm ? 'Укажите название площадки.' : 'Укажите адрес площадки.';
              er.hidden = false;
            }
            (!nm ? nameInp : addrInp).focus();
            return;
          }
          dupBox.hidden = true;
          submit.disabled = true;
          postArenaSetup({
            mode: 'create',
            arena_name: nm,
            address: addr,
            confirm_duplicate: !!confirmDuplicate,
            /* Selected city from the form — may not be PATCH'ed yet (PDEC-001 / draft). */
            city_id: (state.trainer.profile && state.trainer.profile.city_id) || null,
          })
            .then(function(o) {
              submit.disabled = false;
              if (!o.ok) {
                if (er) {
                  er.textContent = arenaSetupErrorDetail(o.data, o.status);
                  er.hidden = false;
                }
                return;
              }
              if (o.data && o.data.status === 'duplicate_warning') {
                renderArenaDuplicateWarning(dupBox, o.data.duplicates || [], doSubmit);
                return;
              }
              afterArenaSetupSuccess(o.data);
            })
            .catch(function() {
              submit.disabled = false;
              if (er) {
                er.textContent = 'Не удалось отправить. Проверьте соединение.';
                er.hidden = false;
              }
            });
        }

        submit.addEventListener('click', function() { doSubmit(false); });
        actions.appendChild(submit);
        actions.appendChild(back);
        box.appendChild(actions);
      }

      function renderArenaAddEntryPoint(hasCity) {
        var box = document.getElementById('arenaEmptyActions');
        if (!box) return;
        if (state.arenaCreateOpen) return;
        box.innerHTML = '';
        if (!hasCity) {
          box.hidden = true;
          return;
        }
        box.hidden = false;
        var fmt = trainerArenaSetupFormat();
        if (fmt === 'mobile') {
          showArenaSetupStatus(
            'Вы указали выездной формат без постоянной площадки. Сетку расписания задаёте в «Настройках».',
            'ok'
          );
          return;
        }
        if (fmt === 'pending_request') {
          var txt = (state.trainer.arena_request_text || '').trim();
          showArenaSetupStatus(
            'Ранее вы отправляли заявку на площадку' +
              (txt ? ': «' + txt + '»' : '') +
              '. Теперь можно добавить её сразу — не дожидаясь ответа.',
            'ok'
          );
        }

        var lead = document.createElement('p');
        lead.className = 'hint arena-empty-lead';
        lead.textContent = (state.trainer.arena_ids || []).length
          ? 'Не нашли нужную площадку в списке?'
          : 'Если вашей площадки нет в списке — выберите, как продолжить:';
        if (!profileArenaPickerEnabled()) box.appendChild(lead);

        if (!profileArenaPickerEnabled()) {
          var btnCreate = document.createElement('button');
          btnCreate.type = 'button';
          btnCreate.className = 'filter-btn arena-empty-btn arena-empty-btn--primary';
          btnCreate.textContent = 'Моей площадки нет в списке';
          btnCreate.addEventListener('click', function() {
            openArenaCreateForm('');
          });
          box.appendChild(btnCreate);
        }

        var btnMobile = document.createElement('button');
        btnMobile.type = 'button';
        btnMobile.className = 'filter-btn arena-empty-btn';
        btnMobile.textContent = 'Занимаюсь выездом / без постоянной площадки';
        btnMobile.addEventListener('click', function() {
          if (
            !window.confirm(
              'Выездной формат без привязки к арене из справочника. Продолжить?'
            )
          ) {
            return;
          }
          var er = document.getElementById('err_arena_setup');
          btnMobile.disabled = true;
          postArenaSetup({ mode: 'mobile' })
            .then(function(o) {
              btnMobile.disabled = false;
              if (!o.ok) {
                if (er) {
                  er.textContent = arenaSetupErrorDetail(o.data, o.status);
                  er.hidden = false;
                }
                return;
              }
              afterArenaSetupSuccess(o.data);
            })
            .catch(function() {
              btnMobile.disabled = false;
              if (er) {
                er.textContent = 'Не удалось сохранить. Проверьте соединение.';
                er.hidden = false;
              }
            });
        });
        box.appendChild(btnMobile);
        if (!profileArenaPickerEnabled()) renderArenaSupportBlock(box);
      }

      function renderArenas() {
        var wrap = document.getElementById('arenasWrap');
        var hint = document.getElementById('arenaHint');
        var emptyBox = document.getElementById('arenaEmptyActions');
        var picker = document.getElementById('arenaPicker');
        var hasCity = !!(state.trainer && state.trainer.profile && state.trainer.profile.city_id);
        if (wrap && !state.arenaCreateOpen) wrap.innerHTML = '';
        if (emptyBox && !state.arenaCreateOpen) {
          emptyBox.hidden = true;
          emptyBox.innerHTML = '';
        }
        if (!state.arenaCreateOpen) clearArenaSetupMessages();

        if (profileArenaPickerEnabled()) {
          if (wrap) {
            wrap.innerHTML = '';
            wrap.hidden = true;
          }
          if (picker) picker.hidden = !hasCity;
          if (hint) {
            hint.style.display = hasCity ? 'none' : 'block';
            hint.textContent = 'Выберите город — появится поиск площадок.';
          }
          var pickerPrimary = document.getElementById('primaryArenaWrap');
          if (pickerPrimary) {
            pickerPrimary.innerHTML = '';
            pickerPrimary.style.display = 'none';
          }
          bindArenaPicker();
          if (hasCity) updateArenaPickerUi();
          else {
            var chips = document.getElementById('arenaChips');
            var results = document.getElementById('arenaResults');
            if (chips) {
              chips.innerHTML = '';
              chips.hidden = true;
            }
            if (results) results.innerHTML = '';
          }
          if (!state.arenaCreateOpen) renderArenaAddEntryPoint(hasCity);
          return;
        }

        if (picker) picker.hidden = true;
        if (wrap) wrap.hidden = false;
        var selected = {};
        (state.trainer.arena_ids || []).forEach(function(id) {
          selected[id] = true;
        });
        if (!state.arenasList.length) {
          hint.style.display = 'block';
          hint.textContent = hasCity
            ? 'Нет арен для выбранного города.'
            : 'Выберите город — появится список доступных арен.';
          var pwrap = document.getElementById('primaryArenaWrap');
          if (pwrap) {
            pwrap.innerHTML = '';
            pwrap.style.display = 'none';
          }
        } else {
          hint.style.display = 'none';
          state.arenasList.forEach(function(a) {
            var row = document.createElement('div');
            row.className = 'arena-row';
            var isSelected = !!selected[a.id];
            if (isSelected) row.classList.add('arena-active');

            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.id = 'arena_' + a.id;
            cb.checked = isSelected;
            cb.addEventListener('change', function() {
              row.classList.toggle('arena-active', cb.checked);
              syncArenaIdsFromCheckboxes();
              updatePrimaryArenaUi();
              setDirty();
            });

            var lab = document.createElement('label');
            lab.htmlFor = 'arena_' + a.id;
            lab.textContent = a.name || ('Арена #' + a.id);
            if (a.is_confirmed === false) {
              lab.appendChild(document.createTextNode(' '));
              var badge = document.createElement('span');
              badge.className = 'arena-unconfirmed-badge';
              badge.textContent = 'на проверке';
              lab.appendChild(badge);
            }

            row.appendChild(cb);
            row.appendChild(lab);
            wrap.appendChild(row);
          });
          updatePrimaryArenaUi();
        }
        if (!state.arenaCreateOpen) renderArenaAddEntryPoint(hasCity);
      }

      function loadArenasForCity(cityId) {
        state.arenasList = [];
        if (!cityId) return Promise.resolve();
        // Authenticated endpoint (unlike /api/public/arenas): also includes the trainer's
        // own unconfirmed arenas (TASK-046 AC-004) — they're not in the public catalog yet.
        var base = apiUrl('/trainer/profile/arenas');
        var sep = base.indexOf('?') >= 0 ? '&' : '?';
        return fetch(base + sep + 'city_id=' + encodeURIComponent(cityId), { headers: headers() })
          .then(function(r) { return r.json(); })
          .then(function(data) {
            state.arenasList = data.items || [];
          })
          .catch(function() { state.arenasList = []; });
      }

      /**
       * Builds city/education dropdowns after `state.cities` / `state.servicesCatalog` are set
       * (from page-bootstrap or legacy multi-fetch — page-bootstrap is the hot path).
       */
      function applyRefsToDom(eduOpts) {
        eduOpts = eduOpts || [];
        var eduSel = document.getElementById('education');
        eduSel.innerHTML = '<option value="">—</option>';
        eduOpts.forEach(function(opt) {
          var o = document.createElement('option');
          o.value = opt;
          o.textContent = opt;
          eduSel.appendChild(o);
        });
        var citySel = document.getElementById('city_id');
        citySel.innerHTML = '<option value="">—</option>';
        state.cities.forEach(function(c) {
          var o = document.createElement('option');
          o.value = String(c.id);
          o.textContent = c.name || ('Город #' + c.id);
          citySel.appendChild(o);
        });
        citySel.onchange = function() {
          var cid = citySel.value ? Number(citySel.value) : null;
          var prev = state.trainer && state.trainer.profile ? state.trainer.profile.city_id : null;
          if (state.trainer.profile) state.trainer.profile.city_id = cid;
          if (cid !== prev) {
            state.arenaCreateOpen = false;
            resetArenaSearch();
          }
          loadArenasForCity(cid).then(function() {
            renderArenas();
            setDirty();
          });
        };
      }

      /** First load: one HTTP round-trip (profile + catalog refs). Replaces chained loadRefs + GET profile. */
      function loadInitial() {
        return fetch(apiUrl('/trainer/profile/page-bootstrap'), { headers: headers() })
          .then(parseJsonResponse)
          .then(function(o) {
            if (!o.ok) {
              var rawDetail = o.data.detail != null ? o.data.detail : 'Ошибка загрузки профиля';
              var detailShow =
                window.MiniAppErrorUi && typeof MiniAppErrorUi.humanizeDetail === 'function'
                  ? MiniAppErrorUi.humanizeDetail(rawDetail) || String(rawDetail)
                  : String(rawDetail);
              document.getElementById('skeleton').innerHTML = '<p style="color:var(--app-danger); padding: 20px; text-align: center;">' +
                detailShow + '</p>';
              return Promise.resolve();
            }
            var data = o.data;
            var refs = data.refs || {};
            state.cities = (refs.cities && refs.cities.items) ? refs.cities.items : [];
            state.servicesCatalog = (refs.services && refs.services.items) ? refs.services.items : [];
            var eduOpts = (refs.education_options && refs.education_options.items) ? refs.education_options.items : [];
            applyRefsToDom(eduOpts);
            state.trainer = data.trainer;
            state.scheduleSettings = data.schedule_settings || null;
            state.scheduleGridSelectedStep =
              state.scheduleSettings && state.scheduleSettings.schedule_grid_step_minutes != null
                ? parseInt(state.scheduleSettings.schedule_grid_step_minutes, 10)
                : 15;
            if (isNaN(state.scheduleGridSelectedStep)) state.scheduleGridSelectedStep = 15;
            renderScheduleSettingsPanel();
            state.moderation_readiness = data.moderation_readiness;
            state.education_entries = data.education_entries || [];
            renderEducationEntries();
            renderModeration();
            renderModeratorFeedbackBanner();
            return fillFormFromTrainer().then(function() {
              state.snapshot = normSnapshot();
              setDirty();
              showMain();
              if (window.location.hash === '#moderation') {
                setTab('moderation');
                setTimeout(function() {
                  var el = document.getElementById('moderation');
                  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 300);
              } else if (window.location.hash === '#settings') {
                setTab('settings');
                setTimeout(function() {
                  var el = document.getElementById('tab-settings');
                  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 300);
              } else {
                maybeEnterProfileBlockTourFromQuery();
              }
            });
          })
          .catch(function() {
            document.getElementById('skeleton').innerHTML = '<p style="color:var(--app-danger); padding: 20px; text-align: center;">Ошибка сети. Проверьте подключение.</p>';
            return Promise.resolve();
          });
      }

      function loadProfile() {
        return fetch(apiUrl('/trainer/profile'), { headers: headers() })
          .then(parseJsonResponse)
          .then(function(o) {
            if (!o.ok) {
              var rawDetail2 = o.data.detail != null ? o.data.detail : 'Ошибка загрузки профиля';
              var detailShow2 =
                window.MiniAppErrorUi && typeof MiniAppErrorUi.humanizeDetail === 'function'
                  ? MiniAppErrorUi.humanizeDetail(rawDetail2) || String(rawDetail2)
                  : String(rawDetail2);
              document.getElementById('skeleton').innerHTML = '<p style="color:var(--app-danger); padding: 20px; text-align: center;">' +
                detailShow2 + '</p>';
              return Promise.resolve();
            }
            state.trainer = o.data.trainer;
            state.scheduleSettings = o.data.schedule_settings || null;
            state.scheduleGridSelectedStep =
              state.scheduleSettings && state.scheduleSettings.schedule_grid_step_minutes != null
                ? parseInt(state.scheduleSettings.schedule_grid_step_minutes, 10)
                : 15;
            if (isNaN(state.scheduleGridSelectedStep)) state.scheduleGridSelectedStep = 15;
            renderScheduleSettingsPanel();
            state.moderation_readiness = o.data.moderation_readiness;
            state.education_entries = o.data.education_entries || [];
            renderEducationEntries();
            renderModeration();
            renderModeratorFeedbackBanner();
            return fillFormFromTrainer().then(function() {
              state.snapshot = normSnapshot();
              setDirty();
              showMain();
              if (window.location.hash === '#moderation') {
                setTab('moderation');
                setTimeout(function() {
                  var el = document.getElementById('moderation');
                  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 300);
              } else if (window.location.hash === '#settings') {
                setTab('settings');
                setTimeout(function() {
                  var el = document.getElementById('tab-settings');
                  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 300);
              } else {
                syncProfileBlockTourBar();
              }
            });
          })
          .catch(function() {
            document.getElementById('skeleton').innerHTML = '<p style="color:var(--app-danger); padding: 20px; text-align: center;">Ошибка сети. Проверьте подключение.</p>';
            return Promise.resolve();
          });
      }

      function saveEducationFromDom() {
        var cards = Array.prototype.slice.call(document.querySelectorAll('#educationEntries .edu-card'));
        var newWrap = document.getElementById('educationNewWrap');
        var newCard = newWrap && newWrap.style.display !== 'none' ? newWrap.querySelector('.edu-card') : null;

        function patchOne(card) {
          var err = card.querySelector('.edu-err');
          var payload = collectEducationPayload(card);
          if (!validateEducationPayload(payload, err)) {
            return Promise.reject({ kind: 'edu_validation', card: card });
          }
          var eduId = parseInt(card.getAttribute('data-edu-id'), 10);
          if (isNaN(eduId)) return Promise.resolve();
          return fetch(apiUrl('/trainer/education/' + encodeURIComponent(eduId)), {
            method: 'PATCH',
            headers: headersJson(),
            body: JSON.stringify(payload),
          }).then(parseJsonResponse).then(function(o) {
            if (!o.ok) {
              var msg = (o.data && o.data.detail) ? String(o.data.detail) : 'Не удалось сохранить образование.';
              return Promise.reject({ kind: 'edu_server', message: msg, card: card });
            }
            return undefined;
          });
        }

        function postNewIfFilled() {
          if (!newCard) return Promise.resolve();
          var errNew = newCard.querySelector('.edu-err');
          var payload = collectEducationPayload(newCard);
          var inst = (payload.institution_name || '').trim();
          var prog = (payload.program_or_title || '').trim();
          if (inst.length < 2 && prog.length < 2) {
            return Promise.resolve();
          }
          if (!validateEducationPayload(payload, errNew)) {
            return Promise.reject({ kind: 'edu_validation', card: newCard });
          }
          return fetch(apiUrl('/trainer/education'), {
            method: 'POST',
            headers: headersJson(),
            body: JSON.stringify(payload),
          }).then(parseJsonResponse).then(function(o) {
            if (!o.ok) {
              var msg = (o.data && o.data.detail) ? String(o.data.detail) : 'Не удалось создать запись об образовании.';
              return Promise.reject({ kind: 'edu_server', message: msg, card: newCard });
            }
            return undefined;
          });
        }

        var p = Promise.resolve();
        cards.forEach(function(card) {
          p = p.then(function() { return patchOne(card); });
        });
        return p.then(function() { return postNewIfFilled(); });
      }

      function save(opts) {
        opts = opts || {};
        var btn = document.getElementById('btnSave');
        /* Карусель каталога: кнопка может быть disabled из‑за цен услуг — телефон всё равно сохраняем. */
        if (btn && btn.disabled && !opts.force) return;
        var parsed;
        try {
          parsed = JSON.parse(readFormSnapshot());
        } catch (e) {
          haptic('error');
          profileBlockTourClearAdvanceStash();
          alert('Ошибка формы. Обновите страницу.');
          return;
        }
        clearFormErrors();
        if (!clientValidateProfile(parsed)) {
          haptic('error');
          profileBlockTourClearAdvanceStash();
          var vtab = pickTabForValidationErrors(parsed);
          setTab(vtab);
          syncServicesValidationUi();
          var pane = vtab === 'settings' ? '#tab-settings' : '#tab-form';
          var inv = document.querySelector(pane + ' .field-invalid');
          if (inv) inv.scrollIntoView({ behavior: 'smooth', block: 'center' });
          else {
            var fe = document.querySelector(pane + ' .field-error:not([hidden])');
            if (fe) fe.scrollIntoView({ behavior: 'smooth', block: 'center' });
            else {
              var es = document.getElementById('err_services');
              if (es && !es.hidden) es.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
          }
          return;
        }
        btn.disabled = true;
        btn.classList.add('saving');
        if (state.profileBlockTourActive) {
          setObFlowNextBusy(true, 'save');
        }
        var pr = parsed.profile;
        var fnTrim = pr.first_name != null ? String(pr.first_name).trim() : '';
        var lnTrim = pr.last_name != null ? String(pr.last_name).trim() : '';
        var body = {
          profile: {
            /* Empty names → null so ProfilePatch does not reject "" on draft saves (PDEC-001). */
            first_name: fnTrim || null,
            last_name: lnTrim || null,
            birth_date: pr.birth_date,
            city_id: pr.city_id,
            phone: pr.phone || null,
            contacts: pr.contacts || '',
            description: pr.description || '',
            experience_years: pr.experience_years,
            education: pr.education,
            session_duration_minutes: pr.session_duration_minutes,
            min_hours_before_booking: pr.min_hours_before_booking,
            group_classes_enabled: !!pr.group_classes_enabled,
          },
          services: parsed.services,
        };
        var snapObj = null;
        try {
          snapObj = state.snapshot ? JSON.parse(state.snapshot) : null;
        } catch (e) {}
        var snapArenas = snapObj && snapObj.arena_ids ? snapObj.arena_ids : [];
        if (!arenaIdsEqual(parsed.arena_ids, snapArenas)) {
          body.arena_ids = parsed.arena_ids;
        }
        var snapPrimary = snapObj && snapObj.primary_arena_id != null ? Number(snapObj.primary_arena_id) : null;
        var curPrimary = parsed.primary_arena_id != null ? Number(parsed.primary_arena_id) : null;
        if (body.arena_ids || snapPrimary !== curPrimary) {
          if (curPrimary != null) body.primary_arena_id = curPrimary;
        }
        if (
          state.scheduleSettings &&
          !state.scheduleSettings.arena_grid_locked &&
          snapObj &&
          parsed.schedule_grid_step_minutes !== snapObj.schedule_grid_step_minutes
        ) {
          body.schedule_grid_step_minutes = parsed.schedule_grid_step_minutes;
        }

        if (parsed.push_notif_use_default) {
          body.push_notification_start_hour = null;
          body.push_notification_end_hour = null;
        } else {
          body.push_notification_start_hour = parsed.push_notification_start_hour;
          body.push_notification_end_hour = parsed.push_notification_end_hour;
        }

        body.digest_enabled = !!parsed.digest_enabled;
        body.digest_send_time = parsed.digest_send_time != null ? parsed.digest_send_time : null;

        fetch(apiUrl('/trainer/profile'), {
          method: 'PATCH',
          headers: headersJson(),
          body: JSON.stringify(body),
        })
          .then(parseJsonResponse)
          .then(function(o) {
            if (o.ok) {
              haptic('success');
              clearFormErrors();
              return saveEducationFromDom().then(function() {
                return loadProfile().then(function() {
                  var tourNextSave = state.profileBlockTourAdvanceFromKey != null;
                  if (!tourNextSave) {
                    showSaveToast('Сохранено', 'Изменения применены.', 'success');
                  } else {
                    showSaveToast('Сохранено', 'Переходим к следующему шагу.', 'success');
                  }
                  /* Run tour focus after moderation auto-submit (may call loadProfile again). */
                  profileBlockTourMarkVisitedSealIfEligible();
                  var skipMod =
                    state.profileBlockTourActive && !state.profileBlockTourSessionVisitedLastForward;
                  var modP = skipMod ? Promise.resolve() : maybeAutoSubmitForModeration();
                  return modP.finally(function() {
                    profileBlockTourAfterSave();
                  });
                });
              }).catch(function(eduErr) {
                profileBlockTourClearAdvanceStash();
                if (eduErr && eduErr.kind === 'edu_validation' && eduErr.card) {
                  haptic('error');
                  setTab('form');
                  eduErr.card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                  return Promise.resolve();
                }
                haptic('error');
                var m = (eduErr && eduErr.message) ? String(eduErr.message) : String(eduErr || 'Ошибка сохранения образования');
                showFieldError('general', m);
                setTab('form');
                if (eduErr && eduErr.card) eduErr.card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return Promise.resolve();
              });
            }
            haptic('error');
            profileBlockTourClearAdvanceStash();
            if (o.status === 422 && o.data && o.data.detail) {
              applyValidationDetail(o.data.detail);
              var stErr =
                SETTINGS_FORMAT_FIELD_IDS.some(function(fid) {
                  var e = document.getElementById('err_' + fid);
                  return e && !e.hidden;
                }) ||
                (function() {
                  var eg = document.getElementById('err_schedule_grid');
                  return eg && !eg.hidden;
                })()
                ? 'settings'
                : 'form';
              setTab(stErr);
              var firstErr =
                document.querySelector('#tab-settings .field-error:not([hidden])') ||
                document.querySelector('#tab-form .field-error:not([hidden])');
              if (firstErr) firstErr.scrollIntoView({ behavior: 'smooth', block: 'center' });
              return Promise.resolve();
            }
            var msg = (o.data && o.data.detail) ? o.data.detail : 'Ошибка сохранения';
            if (typeof msg === 'object') msg = JSON.stringify(msg);
            showFieldError('general', String(msg));
            return Promise.resolve();
          })
          .catch(function(err) {
            haptic('error');
            profileBlockTourClearAdvanceStash();
            console.error(err);
            showFieldError('general', 'Ошибка сети. Проверьте подключение и попробуйте снова.');
          })
          .finally(function() {
            btn.classList.remove('saving');
            setObFlowNextBusy(false);
            setDirty();
          });
      }

      var MAX_TRAINER_PHOTO_BYTES = 15 * 1024 * 1024;
      /** catalog.html .trainer-detail-photo-wrap — 4:3; список — круглый thumb (cover). */
      var CATALOG_PHOTO_ASPECT = 4 / 3;
      var CROPPER_CDN_JS = 'https://cdn.jsdelivr.net/npm/cropperjs@1.6.2/dist/cropper.min.js';
      var CROPPER_CDN_CSS = 'https://cdn.jsdelivr.net/npm/cropperjs@1.6.2/dist/cropper.min.css';
      var cropperLoadPromise = null;
      var photoCropper = null;
      var photoCropObjectUrl = null;

      /** Cropper is ~90KB+parse; load only when the user picks a photo (faster first paint). */
      function ensureCropperLoaded() {
        if (typeof Cropper !== 'undefined') return Promise.resolve();
        if (cropperLoadPromise) return cropperLoadPromise;
        cropperLoadPromise = new Promise(function(resolve, reject) {
          var link = document.createElement('link');
          link.rel = 'stylesheet';
          link.href = CROPPER_CDN_CSS;
          document.head.appendChild(link);
          var s = document.createElement('script');
          s.async = true;
          s.src = CROPPER_CDN_JS;
          s.onload = function() { resolve(); };
          s.onerror = function() { reject(new Error('cropper')); };
          document.head.appendChild(s);
        });
        return cropperLoadPromise;
      }

      function closePhotoCropModal() {
        if (photoCropper) {
          try { photoCropper.destroy(); } catch (e) {}
          photoCropper = null;
        }
        if (photoCropObjectUrl) {
          URL.revokeObjectURL(photoCropObjectUrl);
          photoCropObjectUrl = null;
        }
        var img = document.getElementById('photoCropImg');
        if (img) img.src = '';
        var modal = document.getElementById('photoCropModal');
        if (modal) {
          modal.hidden = true;
          modal.setAttribute('aria-hidden', 'true');
        }
      }

      function openPhotoCropModalImpl(file) {
        if (typeof Cropper === 'undefined') {
          uploadPhotoBlob(file, file.name || 'photo.jpg');
          return;
        }
        closePhotoCropModal();
        photoCropObjectUrl = URL.createObjectURL(file);
        var img = document.getElementById('photoCropImg');
        var modal = document.getElementById('photoCropModal');
        if (!img || !modal) {
          if (photoCropObjectUrl) URL.revokeObjectURL(photoCropObjectUrl);
          photoCropObjectUrl = null;
          uploadPhotoBlob(file, file.name || 'photo.jpg');
          return;
        }
        img.src = photoCropObjectUrl;
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        img.onerror = function() {
          img.onerror = null;
          closePhotoCropModal();
          haptic('error');
          var ne = document.getElementById('photoFileName');
          if (ne) {
            ne.textContent = 'Не удалось открыть файл';
            ne.classList.add('hero-photo-status--error');
          }
        };
        img.onload = function() {
          img.onload = null;
          img.onerror = null;
          photoCropper = new Cropper(img, {
            aspectRatio: CATALOG_PHOTO_ASPECT,
            viewMode: 1,
            dragMode: 'move',
            autoCropArea: 0.85,
            responsive: true,
            restore: false,
            guides: true,
            center: true,
            highlight: true,
            cropBoxMovable: true,
            cropBoxResizable: true,
            toggleDragModeOnDblclick: false,
          });
        };
      }

      function openPhotoCropModal(file) {
        if (typeof Cropper !== 'undefined') {
          openPhotoCropModalImpl(file);
          return;
        }
        ensureCropperLoaded()
          .then(function() { openPhotoCropModalImpl(file); })
          .catch(function() {
            uploadPhotoBlob(file, file.name || 'photo.jpg');
          });
      }

      function setHeroPhotoBusy(busy) {
        var tap = document.getElementById('heroPhotoTap');
        var busyEl = document.getElementById('heroPhotoBusy');
        if (tap) tap.classList.toggle('hero-photo-tap--busy', !!busy);
        if (busyEl) busyEl.hidden = !busy;
      }

      function uploadPhotoBlob(blobOrFile, filenameForLog) {
        var nameEl = document.getElementById('photoFileName');
        if (nameEl) {
          nameEl.textContent = 'Загружаем…';
          nameEl.classList.remove('hero-photo-status--error');
        }
        setHeroPhotoBusy(true);
        var fd = new FormData();
        fd.append('file', blobOrFile, filenameForLog || 'photo.jpg');
        var h = {};
        if (initData()) h['X-Telegram-Init-Data'] = initData();
        fetch('/api/webapp/trainer/photos', { method: 'POST', headers: h, body: fd })
          .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
          .then(function(o) {
            if (o.ok) {
              haptic('success');
              /* Do not await maybeAutoSubmitForModeration: it may chain a second loadProfile()
               * and block .finally() → hero spinner stays forever if that request hangs. */
              return loadProfile().then(function() {
                showSaveToast('Фото загружено', 'Новое изображение отображается в профиле.', 'success');
                maybeAutoSubmitForModeration();
              });
            }
            haptic('error');
            var errMsg = 'Не удалось загрузить фото';
            if (o.data && o.data.detail) {
              if (o.data.detail === 'File too large') errMsg = 'Файл слишком большой (макс. 15 МБ)';
              else if (o.data.detail === 'Not a valid image') errMsg = 'Неверный формат изображения';
              else errMsg = o.data.detail;
            }
            if (nameEl) {
              nameEl.textContent = errMsg;
              nameEl.classList.add('hero-photo-status--error');
            }
          })
          .catch(function() {
            haptic('error');
            if (nameEl) {
              nameEl.textContent = 'Ошибка сети. Попробуйте снова.';
              nameEl.classList.add('hero-photo-status--error');
            }
          })
          .finally(function() {
            setHeroPhotoBusy(false);
          });
      }

      function uploadPhoto(file) {
        if (!file) return;
        if (!file.type || !file.type.startsWith('image/')) {
          haptic('error');
          var ne = document.getElementById('photoFileName');
          if (ne) {
            ne.textContent = 'Выберите изображение';
            ne.classList.add('hero-photo-status--error');
          }
          return;
        }
        if (file.size > MAX_TRAINER_PHOTO_BYTES) {
          haptic('error');
          var ne2 = document.getElementById('photoFileName');
          if (ne2) {
            ne2.textContent = 'Файл слишком большой (макс. 15 МБ)';
            ne2.classList.add('hero-photo-status--error');
          }
          return;
        }
        openPhotoCropModal(file);
      }

      document.getElementById('btnSave').onclick = save;

      var photoInput = document.getElementById('photoInput');
      var heroPhotoDropZone = document.getElementById('heroPhotoDropZone');
      var heroPhotoTap = document.getElementById('heroPhotoTap');

      if (heroPhotoTap && photoInput) {
        heroPhotoTap.addEventListener('click', function() {
          if (heroPhotoTap.classList.contains('hero-photo-tap--busy')) return;
          photoInput.click();
        });
      }

      if (photoInput) {
        photoInput.onchange = function(ev) {
          var f = ev.target.files && ev.target.files[0];
          uploadPhoto(f);
          ev.target.value = '';
        };
      }

      if (heroPhotoDropZone) {
        heroPhotoDropZone.addEventListener('dragover', function(e) {
          e.preventDefault();
          e.stopPropagation();
          heroPhotoDropZone.style.boxShadow = '0 0 0 2px rgba(var(--accent-rgb), 0.85)';
        });
        heroPhotoDropZone.addEventListener('dragleave', function(e) {
          e.preventDefault();
          heroPhotoDropZone.style.boxShadow = '';
        });
        heroPhotoDropZone.addEventListener('drop', function(e) {
          e.preventDefault();
          e.stopPropagation();
          heroPhotoDropZone.style.boxShadow = '';
          var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
          if (f && f.type.startsWith('image/')) {
            uploadPhoto(f);
          }
        });
      }

      (function wirePhotoCropModal() {
        var c = document.getElementById('photoCropCancel');
        var ok = document.getElementById('photoCropConfirm');
        var bd = document.getElementById('photoCropBackdrop');
        if (c) c.onclick = function() { closePhotoCropModal(); };
        if (bd) bd.onclick = function() { closePhotoCropModal(); };
        if (ok) ok.onclick = function() {
          if (!photoCropper) return;
          var canvas = photoCropper.getCroppedCanvas({
            maxWidth: 2048,
            maxHeight: 1536,
            imageSmoothingQuality: 'high',
          });
          if (!canvas) {
            haptic('error');
            return;
          }
          canvas.toBlob(function(blob) {
            closePhotoCropModal();
            if (blob) uploadPhotoBlob(blob, 'photo.jpg');
          }, 'image/jpeg', 0.92);
        };
      })();

      // Hero-cta buttons were removed; keep tab navigation exclusively under header.

      function clearOneFieldError(id) {
        var e = document.getElementById('err_' + id);
        if (!e) e = ensureErrorEl(id);
        if (e) {
          e.textContent = '';
          e.hidden = true;
        }
        setFieldInvalid(id, false);
      }
      PROFILE_FIELD_IDS.forEach(function(id) {
        var el = document.getElementById(id);
        if (!el) return;
        if (id === 'phone') {
          /* Mask handled by CrmPhoneField */
        }
        el.addEventListener('input', function() {
          validateFieldRealtime(id);
          setDirty();
          markFieldValid(id);
        });
        el.addEventListener('change', function() {
          validateFieldRealtime(id);
          setDirty();
          markFieldValid(id);
        });
        el.addEventListener('focus', function() {
          var fw = el.closest ? el.closest('.field') : null;
          if (fw) fw.classList.add('field-focused');
        });
        el.addEventListener('blur', function() {
          var fw = el.closest ? el.closest('.field') : null;
          if (fw) fw.classList.remove('field-focused');
        });
      });
      /** Same pattern as «Показывать в каталоге» — do not require full-form validity for one toggle. */
      (function wireGroupClassesToggle() {
        var cb = document.getElementById('group_classes_enabled');
        if (!cb) return;
        var busy = false;
        cb.addEventListener('change', function() {
          if (busy) return;
          var want = !!cb.checked;
          busy = true;
          cb.disabled = true;
          fetch(apiUrl('/trainer/profile'), {
            method: 'PATCH',
            headers: headersJson(),
            body: JSON.stringify({ profile: { group_classes_enabled: want } }),
          })
            .then(parseJsonResponse)
            .then(function(o) {
              busy = false;
              cb.disabled = false;
              if (!o.ok) {
                cb.checked = !want;
                haptic('error');
                var msg =
                  o.data && o.data.detail
                    ? String(o.data.detail)
                    : 'Не удалось сохранить настройку «группы в расписании».';
                if (typeof msg === 'object') msg = JSON.stringify(msg);
                alert(msg);
                return;
              }
              if (state.trainer) {
                state.trainer.profile = state.trainer.profile || {};
                state.trainer.profile.group_classes_enabled = want;
              }
              state.snapshot = normSnapshot();
              setDirty();
              haptic('success');
              showSaveToast(
                'Группы в расписании',
                want
                  ? 'Настройка включена: можно слоты с несколькими местами'
                  : 'Слоты с несколькими местами в новых правилах отключены',
                'success'
              );
            })
            .catch(function() {
              busy = false;
              cb.disabled = false;
              cb.checked = !want;
              haptic('error');
              alert('Ошибка сети. Попробуйте снова.');
            });
        });
      })();
      (function wireCatalogVisibilityToggle() {
        var cb = document.getElementById('is_catalog_visible');
        if (!cb) return;
        var busy = false;
        cb.addEventListener('change', function() {
          if (busy) return;
          var want = !!cb.checked;
          busy = true;
          cb.disabled = true;
          fetch(apiUrl('/trainer/catalog-visibility'), {
            method: 'PATCH',
            headers: headersJson(),
            body: JSON.stringify({ is_catalog_visible: want }),
          })
            .then(parseJsonResponse)
            .then(function(o) {
              busy = false;
              cb.disabled = false;
              if (!o.ok) {
                cb.checked = !want;
                haptic('error');
                var msg =
                  o.data && o.data.detail
                    ? String(o.data.detail)
                    : 'Не удалось обновить настройку каталога.';
                alert(msg);
                return;
              }
              if (state.trainer) state.trainer.is_catalog_visible = want;
              haptic('success');
              renderCatalogVisibility();
              renderModeration();
              var st = (state.trainer && state.trainer.status) ? String(state.trainer.status).trim() : '';
              var body;
              if (st === 'active') {
                body = want
                  ? 'Профиль снова виден в каталоге клиентов'
                  : 'Профиль скрыт из каталога клиентов';
              } else {
                var ready = !!(state.moderation_readiness && state.moderation_readiness.complete);
                body = want
                  ? (ready
                      ? 'Отправляем карточку на проверку — обычно отвечаем в течение рабочего дня'
                      : 'Готовим карточку к проверке — заполните анкету, и мы отправим её модератору')
                  : 'Хорошо, в каталог не отправляем. Запись по вашей ссылке работает';
              }
              showSaveToast('Каталог', body, 'success');
              // Включение тумблера — и есть просьба о публикации: если анкета уже полная,
              // отправляем сразу, чтобы «хочу в каталог» не требовало второго действия.
              if (want) maybeAutoSubmitForModeration();
            })
            .catch(function() {
              busy = false;
              cb.disabled = false;
              cb.checked = !want;
              haptic('error');
              alert('Ошибка сети. Попробуйте снова.');
            });
        });
      })();
            
      function markFieldValid(id) {
        var el = document.getElementById(id);
        var errEl = document.getElementById('err_' + id);
        if (!el) return;
        var hasValue = (el.value || '').trim().length > 0;
        var hasError = errEl && !errEl.hidden && errEl.textContent;
        el.classList.toggle('field-valid', hasValue && !hasError);
      }

      (function initEducationDeleteCapture() {
        var wrap = document.getElementById('educationEntries');
        if (!wrap || wrap.dataset.eduDeleteCapture === '1') return;
        wrap.dataset.eduDeleteCapture = '1';
        wrap.addEventListener(
          'click',
          function(ev) {
            var t = ev.target;
            if (!t || typeof t.closest !== 'function') return;
            var delBtn = t.closest('.edu-delete');
            if (!delBtn) return;
            ev.preventDefault();
            ev.stopPropagation();
            runEducationDelete(delBtn);
          },
          true
        );
      })();

      var btnEduAdd = document.getElementById('btnEducationAdd');
      if (btnEduAdd) {
        btnEduAdd.addEventListener('click', function() {
          var w = document.getElementById('educationNewWrap');
          if (!w) return;
          if (w.style.display === 'none' || !w.style.display) {
            w.style.display = 'block';
            btnEduAdd.textContent = 'Скрыть форму';
            renderEducationNewForm();
          } else {
            w.style.display = 'none';
            btnEduAdd.textContent = '+ Добавить запись';
          }
          setDirty();
        });
      }

      wireSessionDurationQuickChips();
      wireMinHoursBeforeQuickChips();
      wireProfileBlockTourBar();
      /*
       * Тарифы в визарде: при фокусе на цену тарифа строка должна остаться видимой
       * во время анимации открытия iOS-клавиатуры. visualViewport resize приходит с задержкой,
       * поэтому повторяем scrollIntoView несколько раз после первого focusin и при каждом
       * изменении visualViewport, пока поле сфокусировано.
       */
      (function wireServicesTourPriceFocusScroll() {
        var sw = document.getElementById('servicesWrap');
        if (!sw || sw.dataset.tourPriceFocus) return;
        sw.dataset.tourPriceFocus = '1';
        var focusedRow = null;
        function scrollFocusedPriceIfNeeded() {
          if (!focusedRow || !document.body.contains(focusedRow)) return;
          if (profileTourFieldIsComfortablyVisible(focusedRow)) return;
          try {
            focusedRow.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'auto' });
          } catch (e) {}
        }
        sw.addEventListener(
          'focusin',
          function(ev) {
            if (!state.profileBlockTourActive) return;
            var t = ev.target;
            if (!t || typeof t.closest !== 'function') return;
            if (!sw.contains(t)) return;
            if (t.tagName !== 'INPUT' && t.tagName !== 'TEXTAREA') return;
            var row = t.closest('.svc-tier-row') || t.closest('.svc-group-price-wrap');
            if (!row) return;
            focusedRow = row;
            /* After keyboard animation only — never scrollIntoView({center}) (that relocates the whole list). */
            setTimeout(scrollFocusedPriceIfNeeded, 380);
          },
          true
        );
        sw.addEventListener(
          'focusout',
          function() {
            focusedRow = null;
          },
          true
        );
        var vvTourScrollDeb = null;
        function scheduleScrollRowOnViewportChange() {
          if (vvTourScrollDeb) clearTimeout(vvTourScrollDeb);
          vvTourScrollDeb = setTimeout(function() {
            vvTourScrollDeb = null;
            scrollFocusedPriceIfNeeded();
          }, 160);
        }
        if (window.visualViewport) {
          window.visualViewport.addEventListener('resize', scheduleScrollRowOnViewportChange);
        }
      })();

      /**
       * Основная страница профиля (не в fullscreen-онбординге): фиксированный .save-bar и
       * клавиатура режут высоту визуального порта — поле может оказаться под кнопкой.
       * Отложенный scrollIntoView при фокусе + только visualViewport.resize (клавиатура).
       * Не вешаем visualViewport.scroll: на телефоне он срабатывает при каждом пальцевом скролле
       * и снова дёргает scrollIntoView — ощущение «пружины», нельзя пролистать форму.
       */
      (function wireProfileMainFormKeyboardAvoidance() {
        var root = document.getElementById('mainContent');
        if (!root || root.dataset.profileKbAvoid === '1') return;
        root.dataset.profileKbAvoid = '1';

        function activeInProfileForm() {
          var ae = document.activeElement;
          if (!ae || !root.contains(ae)) return null;
          var tg = ae.tagName;
          if (tg !== 'INPUT' && tg !== 'TEXTAREA' && tg !== 'SELECT') return null;
          return ae;
        }

        function scrollProfileMainFocusedFieldIntoView() {
          if (document.body.classList.contains('ob-flow-open')) return;
          var ae = activeInProfileForm();
          if (!ae) return;
          var target =
            (ae.closest && ae.closest('.field')) ||
            (ae.closest && ae.closest('.svc-tier-row')) ||
            (ae.closest && ae.closest('.svc-group-price-wrap')) ||
            (ae.closest && ae.closest('.svc-desc-wrap')) ||
            (ae.closest && ae.closest('.svc-client-notice-wrap')) ||
            (ae.closest && ae.closest('.edu-card')) ||
            ae;
          try {
            target.scrollIntoView({
              block: 'nearest',
              behavior: 'auto',
              inline: 'nearest',
            });
          } catch (e) {}
        }

        var vpDeb = null;
        function onViewportOrResize() {
          if (document.body.classList.contains('ob-flow-open')) return;
          if (vpDeb) clearTimeout(vpDeb);
          vpDeb = setTimeout(function() {
            vpDeb = null;
            scrollProfileMainFocusedFieldIntoView();
          }, 220);
        }

        root.addEventListener(
          'focusin',
          function(ev) {
            if (document.body.classList.contains('ob-flow-open')) return;
            var t = ev.target;
            if (!t || !t.tagName) return;
            var tg = t.tagName;
            if (tg !== 'INPUT' && tg !== 'TEXTAREA' && tg !== 'SELECT') return;
            setTimeout(scrollProfileMainFocusedFieldIntoView, 80);
            setTimeout(scrollProfileMainFocusedFieldIntoView, 420);
          },
          true
        );

        window.addEventListener('resize', onViewportOrResize);
        if (window.visualViewport) {
          window.visualViewport.addEventListener('resize', onViewportOrResize);
        }
      })();

      /**
       * Telegram / mobile WebView: tap on “empty” layout does not blur focused inputs — keyboard stays up.
       * Blur on capture-phase touch/mouse when the hit target is not a text field (and not a label delegating focus).
       */
      (function wireDismissKeyboardOnOutsideTap() {
        var root = document.getElementById('mainContent');
        if (!root || root.dataset.dismissKbTap === '1') return;
        root.dataset.dismissKbTap = '1';

        function isTextLikeInput(el) {
          if (!el || el.tagName !== 'INPUT') return false;
          var tp = (el.type || '').toLowerCase();
          return (
            tp !== 'checkbox' &&
            tp !== 'radio' &&
            tp !== 'button' &&
            tp !== 'submit' &&
            tp !== 'reset' &&
            tp !== 'file' &&
            tp !== 'hidden' &&
            tp !== 'range' &&
            tp !== 'color'
          );
        }

        function isTextEntryElement(el) {
          if (!el || !el.tagName) return false;
          var tag = el.tagName.toUpperCase();
          if (tag === 'TEXTAREA') return true;
          if (tag === 'SELECT') return true;
          if (tag === 'INPUT') return isTextLikeInput(el);
          return false;
        }

        function tryDismiss(ev) {
          var t = ev.target;
          if (!t || typeof t.closest !== 'function') return;
          if (isTextEntryElement(t)) return;
          if (t.closest('label')) return;
          var ae = document.activeElement;
          if (!ae || typeof ae.blur !== 'function') return;
          if (!isTextEntryElement(ae)) return;
          ae.blur();
        }

        document.addEventListener('touchstart', tryDismiss, { passive: true, capture: true });
        document.addEventListener('mousedown', tryDismiss, true);
      })();

      if (window.CrmPhoneField) {
        CrmPhoneField.initAll(document);
      }

      initBirthDateInput();
      loadInitial();
    })();
