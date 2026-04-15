    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { tg.ready(); tg.expand(); }

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
      /** Visible confirmation — title + short subtitle for clarity in WebView. */
      function showSaveToast(title, description) {
        var el = document.getElementById('saveToast');
        var tEl = document.getElementById('saveToastTitle');
        var dEl = document.getElementById('saveToastDesc');
        if (!el || !tEl || !dEl) return;
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
        snapshot: null,
        scheduleSettings: null,
        scheduleGridSelectedStep: 15,
      };

      var SCHEDULE_GRID_STEPS = [10, 15, 30, 60];

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

      function syncScheduleGridSaveButton() {
        var btn = document.getElementById('btnSaveScheduleGrid');
        if (!btn || !state.scheduleSettings) return;
        var locked = !!state.scheduleSettings.arena_grid_locked;
        var saved = parseInt(state.scheduleSettings.schedule_grid_step_minutes, 10);
        if (isNaN(saved) || SCHEDULE_GRID_STEPS.indexOf(saved) < 0) saved = 15;
        var dirty = !locked && state.scheduleGridSelectedStep !== saved;
        btn.disabled = !dirty;
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
          syncScheduleGridSaveButton();
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
            syncScheduleGridSaveButton();
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
        syncScheduleGridSaveButton();
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

      function saveScheduleGridSettings() {
        var err = document.getElementById('err_schedule_grid');
        if (err) {
          err.hidden = true;
          err.textContent = '';
        }
        var btn = document.getElementById('btnSaveScheduleGrid');
        if (!btn || btn.disabled || !state.scheduleSettings) return;
        btn.classList.add('saving');
        fetch(apiUrl('/trainer/profile'), {
          method: 'PATCH',
          headers: headersJson(),
          body: JSON.stringify({ schedule_grid_step_minutes: state.scheduleGridSelectedStep }),
        })
          .then(parseJsonResponse)
          .then(function(o) {
            btn.classList.remove('saving');
            if (!o.ok) {
              if (err) {
                err.hidden = false;
                err.textContent = friendlyApiMsg(o.data && o.data.detail ? o.data.detail : '');
              }
              if (o.status === 422) haptic('warning');
              syncScheduleGridSaveButton();
              return;
            }
            state.scheduleSettings.schedule_grid_step_minutes = state.scheduleGridSelectedStep;
            if (state.trainer) state.trainer.schedule_grid_step_minutes = state.scheduleGridSelectedStep;
            syncScheduleGridSaveButton();
            showSaveToast('Сохранено', 'Сетка расписания обновлена');
            haptic('success');
          })
          .catch(function() {
            btn.classList.remove('saving');
            if (err) {
              err.hidden = false;
              err.textContent = 'Ошибка сети.';
            }
            syncScheduleGridSaveButton();
          });
      }
      /** Fixed tariff codes (must match server price_tier_kind). */
      var SERVICE_TIER_ORDER = ['child', 'adult', 'two_children', 'two_adults', 'adult_and_child'];
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

      /** Статус в шапке: для черновика учитываем полноту и факт отправки на модерацию. */
      function heroStatusLabelRu(st, d) {
        st = (st || '').trim();
        d = d || {};
        if (st === 'pending_profile') {
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
          if (d.already_submitted_for_moderation) return 'pending';
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
        'first_name', 'last_name', 'age', 'city_id', 'phone', 'contacts', 'description',
        'experience_years', 'education', 'session_duration_minutes', 'min_hours_before_booking',
      ];
      /** Fields shown on «Настройки» tab — used to switch tab on validation errors. */
      var SETTINGS_FORMAT_FIELD_IDS = ['session_duration_minutes', 'min_hours_before_booking'];
      var PHONE_MAX_LEN = 32;
      /** Aligned with server: Belarus E.164 `+375` + 9 digits after country code. */
      var PHONE_BY_RE = /^\+375\d{9}$/;
      var PHONE_BY_ERR = 'Укажите корректный номер телефона.';
      var MIN_DESCRIPTION_CHARS = 25;
      var MAX_DESCRIPTION_CHARS = 5000;
      /** Per-service blurb in «Услуги и цены»; aligned with LEN_TRAINER_SERVICE_DESCRIPTION on the server. */
      var MAX_SERVICE_DESCRIPTION_CHARS = 800;
      /** Fallback if API omits field; must match MODERATION_CRITERIA_TOTAL on the server. */
      var MODERATION_CRITERIA_TOTAL_FALLBACK = 12;
      var MAX_EDUCATION_DOCUMENT_PHOTOS = 12;

      /** Russian plural for "остался N критерий" (criteria, not form fields). */
      function ruCriteriaWord(n) {
        n = Math.floor(Math.abs(n));
        var n100 = n % 100;
        var n10 = n % 10;
        if (n100 >= 11 && n100 <= 14) return 'критериев';
        if (n10 === 1) return 'критерий';
        if (n10 >= 2 && n10 <= 4) return 'критерия';
        return 'критериев';
      }

      function ruOstalosCriteria(n) {
        n = Math.floor(Math.abs(n));
        if (n <= 0) return '';
        if (n === 1) return 'Остался 1 критерий';
        return 'Осталось ' + n + ' ' + ruCriteriaWord(n);
      }

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
      }

      function showFieldError(fieldId, message) {
        var el = fieldId === 'general' ? document.getElementById('err_general') : ensureErrorEl(fieldId);
        if (!el) return;
        el.textContent = message;
        el.hidden = !message;
        if (fieldId !== 'general') setFieldInvalid(fieldId, !!message);
      }

      /** Map FastAPI/Pydantic loc to form field id (profile.*) or 'general'. */
      function locToProfileFieldId(loc) {
        if (!loc || !loc.length) return 'general';
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
        var raw = String(s || '').trim();
        if (!raw) return '';
        var d = raw.replace(/\D/g, '');
        if (!d) return raw.slice(0, PHONE_MAX_LEN);
        if (d.length === 12 && d.indexOf('375') === 0) return '+' + d;
        if (d.length === 11 && d.indexOf('80') === 0) return '+375' + d.slice(2);
        if (d.length === 9) return '+375' + d;
        return raw.replace(/\s+/g, '').replace(/-/g, '').replace(/\(/g, '').replace(/\)/g, '').replace(/\./g, '').slice(0, PHONE_MAX_LEN);
      }

      /** Mirrors `src.shared.profile_phone.validate_phone_non_empty`. */
      function validatePhoneMessage(normalized) {
        var t = normalized;
        if (!t) return null;
        if (t.length > PHONE_MAX_LEN) return 'Телефон: не длиннее 32 символов.';
        if (!PHONE_BY_RE.test(t)) return PHONE_BY_ERR;
        return null;
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
            minHint.style.color = '#f59e0b';
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
          var digits = el.value.replace(/\D/g, '');
          if (digits.length > 0) {
            var fullPhone = '+375' + digits;
            msg = validatePhoneMessage(fullPhone);
          }
        } else if (fieldId === 'first_name') {
          if (!(el.value || '').trim()) msg = 'Укажите имя.';
        } else if (fieldId === 'last_name') {
          if (!(el.value || '').trim()) msg = 'Укажите фамилию.';
        } else if (fieldId === 'age') {
          var av = el.value;
          if (av === '' || av === null) msg = 'Укажите возраст.';
          else {
            var an = Number(av);
            if (isNaN(an) || !Number.isInteger(an)) msg = 'Укажите целое число.';
          }
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

      /** Same rules as PATCH / ProfilePatch; no side effects. */
      function collectProfileFieldErrors(parsed) {
        var pr = parsed.profile;
        var errs = [];
        if (!pr.first_name || !String(pr.first_name).trim()) errs.push(['first_name', 'Укажите имя.']);
        if (!pr.last_name || !String(pr.last_name).trim()) errs.push(['last_name', 'Укажите фамилию.']);
        if (pr.age == null || pr.age === '') errs.push(['age', 'Укажите возраст.']);
        else {
          var ageN = Number(pr.age);
          if (isNaN(ageN) || !Number.isInteger(ageN)) errs.push(['age', 'Укажите целое число.']);
        }
        if (pr.city_id == null || pr.city_id === '' || Number(pr.city_id) < 1) errs.push(['city_id', 'Выберите город из списка.']);
        var ph = normalizePhoneClient(pr.phone);
        var pmsg = validatePhoneMessage(ph);
        if (pmsg) errs.push(['phone', pmsg]);
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

      function serviceEntryPricesOk(entry) {
        var tiers = entry.price_tiers;
        if (!tiers || !tiers.length) return false;
        var j;
        for (j = 0; j < tiers.length; j++) {
          var pb = tiers[j].price_byn;
          if (pb == null || pb === '') return false;
          var n = Number(pb);
          if (isNaN(n) || n < 0) return false;
        }
        return true;
      }

      function servicesPricesValid(parsed) {
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
            var anyTier = false;
            SERVICE_TIER_ORDER.forEach(function(code) {
              var tcb = document.getElementById('svc_tier_' + s.id + '_' + code);
              var pel = document.getElementById('price_tier_' + s.id + '_' + code);
              if (tcb && tcb.checked && pel && pel.value.trim() !== '') {
                var tn = Number(pel.value);
                if (!isNaN(tn) && tn >= 0) anyTier = true;
              }
            });
            if (!anyTier) invalid = true;
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
            errEl.textContent = 'Описание услуги не длиннее ' + MAX_SERVICE_DESCRIPTION_CHARS + ' символов.';
            errEl.hidden = false;
            openProfileCollapseContaining(errEl);
          } else if (!svcOk && (parsed.services || []).length > 0) {
            errEl.textContent = 'Для каждой выбранной услуги отметьте хотя бы один тариф и укажите цену.';
            errEl.hidden = false;
            openProfileCollapseContaining(errEl);
          } else {
            errEl.textContent = '';
            errEl.hidden = true;
          }
        }
      }

      function isFormValidForSave() {
        try {
          var parsed = JSON.parse(readFormSnapshot());
        } catch (e) {
          return false;
        }
        if (collectProfileFieldErrors(parsed).length) return false;
        if (!servicesPricesValid(parsed)) return false;
        if (!serviceDescriptionsLengthOk(parsed)) return false;
        if (parsed.arena_ids && parsed.arena_ids.length >= 2) {
          if (!parsed.primary_arena_id || parsed.arena_ids.indexOf(parsed.primary_arena_id) < 0) return false;
        }
        return true;
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
        var errs = collectProfileFieldErrors(parsed);
        if (!servicesPricesValid(parsed)) {
          errs.push(['services', 'Для каждой выбранной услуги отметьте хотя бы один тариф и укажите цену.']);
        }
        if (!serviceDescriptionsLengthOk(parsed)) {
          errs.push(['services', 'Описание услуги не длиннее ' + MAX_SERVICE_DESCRIPTION_CHARS + ' символов.']);
        }
        if (parsed.arena_ids && parsed.arena_ids.length >= 2) {
          if (!parsed.primary_arena_id || parsed.arena_ids.indexOf(parsed.primary_arena_id) < 0) {
            errs.push(['primary_arena', 'Выберите основную площадку для онлайн-записи.']);
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
          } else {
            showFieldError(pair[0], pair[1]);
          }
        });
        return false;
      }

      /**
       * После каждого успешного «Сохранить» (и после загрузки фото): синхронизировали state с сервером —
       * если статус черновик и анкета полная и ещё не в очереди на проверку, отправляем в админ-бот.
       * Тренер отдельно модерацию не запускает.
       */
      function maybeAutoSubmitForModeration() {
        var t = state.trainer;
        var d = state.moderation_readiness || {};
        var st = (t && t.status) ? String(t.status).trim() : '';
        if (st !== 'pending_profile' || !d.complete || d.already_submitted_for_moderation) {
          return Promise.resolve();
        }
        return fetch(apiUrl('/trainer/onboarding/submit-for-moderation'), {
          method: 'POST',
          headers: Object.assign(headers(), { 'Content-Type': 'application/json' }),
          body: '{}',
        })
          .then(parseJsonResponse)
          .then(function(sub) {
            if (!sub.ok) return Promise.resolve();
            if (sub.data && sub.data.noop) return Promise.resolve();
            return loadProfile();
          })
          .catch(function() { return Promise.resolve(); });
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
          var gpOut = null;
          if (s.group_price_byn != null && !isNaN(Number(s.group_price_byn))) gpOut = Number(s.group_price_byn);
          var row = { service_id: s.service_id, price_tiers: tiers, description: descOut };
          if (gpOut != null) row.group_price_byn = gpOut;
          return row;
        }).sort(function(a, b) { return a.service_id - b.service_id; });
        var arena_ids = (state.trainer && state.trainer.arena_ids) ? state.trainer.arena_ids.slice().sort(function(a,b){ return a-b; }) : [];
        var primary_arena_id = (state.trainer && state.trainer.primary_arena_id != null) ? Number(state.trainer.primary_arena_id) : null;
        return JSON.stringify({
          profile: {
            first_name: p.first_name || '',
            last_name: p.last_name || '',
            age: p.age != null ? Number(p.age) : null,
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
        function phoneStr() {
          var el = document.getElementById('phone');
          if (!el) return '';
          var digits = el.value.replace(/\D/g, '');
          if (!digits) return '';
          return '+375' + digits;
        }
        var cityEl = document.getElementById('city_id');
        var cityVal = cityEl && cityEl.value !== '' ? Number(cityEl.value) : null;
        var services = [];
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
            if (tiers.length) {
              var svcObj = { service_id: s.id, price_tiers: tiers };
              var sdEl = document.getElementById('svc_desc_' + s.id);
              var sdRaw = sdEl ? sdEl.value.trim() : '';
              svcObj.description = sdRaw ? sdRaw : null;
              var gpel = document.getElementById('price_group_' + s.id);
              if (gpel && gpel.value.trim() !== '') {
                var gpg = Number(gpel.value);
                if (!isNaN(gpg) && gpg >= 0) svcObj.group_price_byn = gpg;
              }
              services.push(svcObj);
            }
          }
        });
        services.sort(function(a, b) { return a.service_id - b.service_id; });
        var arena_ids = [];
        state.arenasList.forEach(function(a) {
          var cb = document.getElementById('arena_' + a.id);
          if (cb && cb.checked) arena_ids.push(a.id);
        });
        arena_ids.sort(function(a, b) { return a - b; });
        var primary_arena_id = null;
        if (arena_ids.length >= 2) {
          var pr = document.querySelector('input[name="primary_arena"]:checked');
          primary_arena_id = pr ? parseInt(pr.value, 10) : null;
        } else if (arena_ids.length === 1) {
          primary_arena_id = arena_ids[0];
        }
        var eduSel = document.getElementById('education');
        var eduVal = eduSel && eduSel.value ? eduSel.value : '';
        return JSON.stringify({
          profile: {
            first_name: str('first_name'),
            last_name: str('last_name'),
            age: num('age', true),
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
        });
      }

      function setDirty() {
        var dirty = state.snapshot !== null && readFormSnapshot() !== state.snapshot;
        var btn = document.getElementById('btnSave');
        if (!btn) return;
        syncServicesValidationUi();
        btn.disabled = !dirty || !isFormValidForSave();
      }

      function showMain() {
        document.getElementById('skeleton').style.display = 'none';
        var m = document.getElementById('mainContent');
        m.style.display = 'block';
        requestAnimationFrame(function() { m.classList.add('visible'); });
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
      }

      /**
       * Scroll/focus the first field that moderation still treats as missing (same order as API missing_fields).
       * Falls back to «Основное» if the list is empty.
       */
      function focusNextMissingProfileField() {
        var d = state.moderation_readiness || {};
        var missing = d.missing_fields || [];
        var key = missing.length ? missing[0] : null;

        function focusEl(el) {
          if (!el) return;
          openProfileCollapseContaining(el);
          try {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (e) {}
          setTimeout(function() {
            try {
              if (el.focus) el.focus({ preventScroll: true });
            } catch (e2) {
              try {
                if (el.focus) el.focus();
              } catch (e3) {}
            }
          }, 120);
        }

        if (!key) {
          setTab('form');
          setTimeout(function() {
            var anchor = document.getElementById('anketaStart');
            if (anchor) anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
            focusEl(document.getElementById('first_name'));
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
            case 'age':
              el = document.getElementById('age');
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
              var uc = document.querySelector('#servicesWrap input[type="checkbox"]:not(:checked)');
              el = uc || document.getElementById('servicesWrap');
              break;
            }
            case 'arenas': {
              var uca = document.querySelector('#arenasWrap input[type="checkbox"]:not(:checked)');
              if (uca) {
                el = uca;
                break;
              }
              var pwrap = document.getElementById('primaryArenaWrap');
              if (pwrap && pwrap.style.display !== 'none') {
                if (!document.querySelector('input[name="primary_arena"]:checked')) {
                  el = document.querySelector('input[name="primary_arena"]');
                }
              }
              if (!el) el = document.getElementById('arenasWrap') || document.getElementById('arenaHint');
              break;
            }
            default:
              el = document.getElementById('anketaStart');
          }
          if (el) focusEl(el);
        }, 80);
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
          if (!phone) { el.value = ''; return; }
          var digits = String(phone).replace(/\D/g, '');
          if (digits.startsWith('375')) digits = digits.slice(3);
          else if (digits.startsWith('80')) digits = digits.slice(2);
          if (digits.length > 9) digits = digits.slice(0, 9);
          var formatted = '';
          if (digits.length > 0) formatted += digits.slice(0, 2);
          if (digits.length > 2) formatted += ' ' + digits.slice(2, 5);
          if (digits.length > 5) formatted += ' ' + digits.slice(5, 7);
          if (digits.length > 7) formatted += ' ' + digits.slice(7, 9);
          el.value = formatted;
        }
        setv('first_name', p.first_name);
        setv('last_name', p.last_name);
        setv('age', p.age);
        setPhone(p.phone);
        setv('contacts', p.contacts);
        setv('description', p.description);
        updateDescriptionMeta();
        setv('experience_years', p.experience_years);
        setv('session_duration_minutes', p.session_duration_minutes);
        setv('min_hours_before_booking', p.min_hours_before_booking);
        var gce = document.getElementById('group_classes_enabled');
        if (gce) gce.checked = !!p.group_classes_enabled;
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
        return loadArenasForCity(p.city_id).then(function() {
          renderArenas();
          renderHeroSummary();
        });
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

        if (st === 'active') {
          missTitle.style.display = 'none';
          hint.textContent = 'Вы в каталоге — клиенты могут вас найти и записаться.';
        } else if (st === 'deactivated') {
          missTitle.style.display = 'none';
          hint.textContent = 'Каталог недоступен. Восстановление — через поддержку.';
        } else if (st === 'pending_contract') {
          missTitle.style.display = 'none';
          hint.textContent = 'Следующий шаг — договор с менеджером.';
        } else if (st === 'pending_payment') {
          missTitle.style.display = 'none';
          hint.textContent = 'Следующий шаг — оплата подписки.';
        } else if (st === 'pending_profile') {
          var fbRaw = state.trainer && state.trainer.moderation_feedback;
          var fbTrim = (fbRaw != null && String(fbRaw).trim()) ? String(fbRaw).trim() : '';
          if (fbTrim) {
            missTitle.style.display = 'none';
            hint.textContent = 'Модератор оставил комментарий — см. жёлтый блок выше. Внесите правки и снова сохраните анкету.';
          } else if (d.already_submitted_for_moderation) {
            missTitle.style.display = 'none';
            hint.textContent = 'Ожидается проверка в админ-боте.';
          } else if (d.complete) {
            missTitle.style.display = 'none';
            hint.textContent = 'Все критерии для очереди на проверку выполнены.';
          } else {
            missTitle.style.display = 'block';
            hint.textContent = '';
            (d.missing_labels_ru || []).forEach(function(label) {
              var li = document.createElement('li');
              li.textContent = label;
              missList.appendChild(li);
            });
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

      function updateProgressRing() {
        var d = state.moderation_readiness || {};
        var missing = d.missing_fields || [];
        var totalCriteria =
          d.moderation_criteria_total != null && !isNaN(Number(d.moderation_criteria_total))
            ? Math.max(1, Math.floor(Number(d.moderation_criteria_total)))
            : MODERATION_CRITERIA_TOTAL_FALLBACK;
        var filledCriteria = Math.max(0, totalCriteria - missing.length);
        var percent = Math.round((filledCriteria / totalCriteria) * 100);
        
        var percentEl = document.getElementById('progressPercent');
        var titleEl = document.getElementById('progressTitle');
        var subtitleEl = document.getElementById('progressSubtitle');
        var ringFill = document.querySelector('.progress-ring-fill');
        var ringCircle = document.querySelector('.progress-ring-fill circle');
        
        if (percentEl) percentEl.textContent = percent + '%';
        
        if (ringCircle) {
          var circumference = 2 * Math.PI * 18;
          var offset = circumference - (percent / 100) * circumference;
          ringCircle.style.strokeDashoffset = offset;
        }
        
        if (ringFill) {
          ringFill.classList.toggle('complete', percent === 100);
        }
        
        if (titleEl && subtitleEl) {
          if (percent === 100) {
            titleEl.textContent = 'Профиль готов!';
            subtitleEl.textContent = 'Все ' + totalCriteria + ' критериев готовности выполнены';
          } else if (percent >= 75) {
            titleEl.textContent = 'Почти готово';
            subtitleEl.textContent = ruOstalosCriteria(missing.length);
          } else if (percent >= 50) {
            titleEl.textContent = 'Хороший прогресс';
            subtitleEl.textContent = 'Готово ' + filledCriteria + ' из ' + totalCriteria + ' критериев';
          } else {
            titleEl.textContent = 'Заполнение профиля';
            subtitleEl.textContent =
              'Нужно закрыть до ' + totalCriteria + ' критериев (как в модерации) — см. вкладку «Статус»';
          }
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
                  showSaveToast('Запись удалена', 'Список образования обновлён.');
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
        }
        if (found.price_byn != null && out.adult == null) out.adult = Number(found.price_byn);
        if (found.price_child_byn != null && out.child == null) out.child = Number(found.price_child_byn);
        return out;
      }

      /** Same tier price is shared across selected services while editing (profile UX). */
      var _tierPriceSyncing = false;

      function propagateTierPriceAcrossServices(sourceServiceId, tierCode, value) {
        if (_tierPriceSyncing) return;
        _tierPriceSyncing = true;
        try {
          state.servicesCatalog.forEach(function(s) {
            var sid = s.id;
            if (sid === sourceServiceId) return;
            var svcCb = document.getElementById('svc_' + sid);
            if (!svcCb || !svcCb.checked) return;
            var tcb = document.getElementById('svc_tier_' + sid + '_' + tierCode);
            if (!tcb || !tcb.checked) return;
            var pel = document.getElementById('price_tier_' + sid + '_' + tierCode);
            if (pel) pel.value = value;
          });
        } finally {
          _tierPriceSyncing = false;
        }
        setDirty();
      }

      /** First non-empty price among selected services for this tier (optionally skip one row). */
      function getPeerTierPriceValue(tierCode, excludeServiceId) {
        var i, s, sid, pel, tcb, svcCb;
        for (i = 0; i < state.servicesCatalog.length; i++) {
          s = state.servicesCatalog[i];
          sid = s.id;
          if (sid === excludeServiceId) continue;
          svcCb = document.getElementById('svc_' + sid);
          if (!svcCb || !svcCb.checked) continue;
          tcb = document.getElementById('svc_tier_' + sid + '_' + tierCode);
          if (!tcb || !tcb.checked) continue;
          pel = document.getElementById('price_tier_' + sid + '_' + tierCode);
          if (pel && pel.value.trim() !== '') return pel.value;
        }
        return null;
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

      function renderServices() {
        var wrap = document.getElementById('servicesWrap');
        wrap.innerHTML = '';
        var selectedIds = {};
        (state.trainer.services || []).forEach(function(s) {
          selectedIds[s.service_id] = true;
        });
        state.servicesCatalog.forEach(function(s) {
          var row = document.createElement('div');
          row.className = 'service-row';
          var id = s.id;
          var isSelected = !!selectedIds[id];
          if (isSelected) row.classList.add('service-active');
          var pricesByCode = getServiceTierPricesByCode(id);

          var chk = document.createElement('input');
          chk.type = 'checkbox';
          chk.id = 'svc_' + id;
          chk.checked = isSelected;

          var span = document.createElement('span');
          span.className = 'svc-name';
          span.textContent = s.name || ('Услуга #' + id);

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
            inp.placeholder = '0.00';
            inp.id = 'price_tier_' + id + '_' + code;
            inp.disabled = !isSelected || !tchk.checked;
            if (hasPrice) inp.value = String(pv);
            var suf = document.createElement('span');
            suf.className = 'price-suffix';
            suf.textContent = 'BYN';
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
              if (inp.value.trim() === '') {
                var peer = getPeerTierPriceValue(code, id);
                if (peer) inp.value = peer;
              }
              if (inp.value.trim() !== '') {
                propagateTierPriceAcrossServices(id, code, inp.value);
              } else {
                setDirty();
              }
            }
            tchk.addEventListener('change', syncTierInput);
            function onTierPriceInput() {
              if (_tierPriceSyncing) return;
              propagateTierPriceAcrossServices(id, code, inp.value);
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
          gRow.className = 'svc-tier-row';
          var gpw = document.createElement('div');
          gpw.className = 'tier-price-wrap';
          var gInp = document.createElement('input');
          gInp.type = 'number';
          gInp.step = '0.01';
          gInp.min = '0';
          gInp.id = 'price_group_' + id;
          gInp.disabled = !isSelected;
          gInp.setAttribute('aria-label', 'Цена за человека на групповом занятии, BYN');
          var gpv = getGroupPriceValue(id);
          if (gpv != null && !isNaN(gpv)) gInp.value = String(gpv);
          var gsuf = document.createElement('span');
          gsuf.className = 'price-suffix';
          gsuf.textContent = 'BYN';
          gpw.appendChild(gInp);
          gpw.appendChild(gsuf);
          gRow.appendChild(gpw);
          groupWrap.appendChild(groupLab);
          groupWrap.appendChild(groupHint);
          groupWrap.appendChild(gRow);
          gInp.addEventListener('input', setDirty);
          gInp.addEventListener('change', setDirty);

          tierBody.appendChild(descBlock);
          tierBody.appendChild(tierWrap);
          tierBody.appendChild(groupWrap);

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
              SERVICE_TIER_ORDER.forEach(function(code) {
                var pel = document.getElementById('price_tier_' + id + '_' + code);
                var tcb = document.getElementById('svc_tier_' + id + '_' + code);
                if (pel && tcb) pel.disabled = !tcb.checked;
              });
              var pgeOn = document.getElementById('price_group_' + id);
              if (pgeOn) pgeOn.disabled = false;
            }
            setDirty();
          });

          row.appendChild(chk);
          row.appendChild(span);
          row.appendChild(toggleBtn);
          var block = document.createElement('div');
          block.className = 'service-block';
          block.appendChild(row);
          block.appendChild(tierBody);
          wrap.appendChild(block);
        });
      }

      function updatePrimaryArenaUi() {
        var wrap = document.getElementById('primaryArenaWrap');
        if (!wrap) return;
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
          inp.addEventListener('change', function() { setDirty(); });
        });
      }

      function renderArenas() {
        var wrap = document.getElementById('arenasWrap');
        var hint = document.getElementById('arenaHint');
        wrap.innerHTML = '';
        var selected = {};
        (state.trainer.arena_ids || []).forEach(function(id) { selected[id] = true; });
        if (!state.arenasList.length) {
          hint.style.display = 'block';
          hint.textContent = state.trainer.profile && state.trainer.profile.city_id
            ? 'Нет арен для выбранного города.'
            : 'Выберите город — появится список доступных арен.';
          var pwrap = document.getElementById('primaryArenaWrap');
          if (pwrap) {
            pwrap.innerHTML = '';
            pwrap.style.display = 'none';
          }
          return;
        }
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
            updatePrimaryArenaUi();
            setDirty();
          });
          
          var lab = document.createElement('label');
          lab.htmlFor = 'arena_' + a.id;
          lab.textContent = a.name || ('Арена #' + a.id);
          
          row.appendChild(cb);
          row.appendChild(lab);
          wrap.appendChild(row);
        });
        updatePrimaryArenaUi();
      }

      function loadArenasForCity(cityId) {
        state.arenasList = [];
        if (!cityId) return Promise.resolve();
        return fetch('/api/public/arenas?city_id=' + encodeURIComponent(cityId))
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
          loadArenasForCity(cid).then(function() {
            state.trainer.arena_ids = [];
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
              document.getElementById('skeleton').innerHTML = '<p style="color:var(--app-danger); padding: 20px; text-align: center;">' +
                (o.data.detail || 'Ошибка загрузки профиля') + '</p>';
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
            updateProgressRing();
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
              document.getElementById('skeleton').innerHTML = '<p style="color:var(--app-danger); padding: 20px; text-align: center;">' +
                (o.data.detail || 'Ошибка загрузки профиля') + '</p>';
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
            updateProgressRing();
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

      function save() {
        var btn = document.getElementById('btnSave');
        if (btn && btn.disabled) return;
        var parsed;
        try {
          parsed = JSON.parse(readFormSnapshot());
        } catch (e) {
          haptic('error');
          alert('Ошибка формы. Обновите страницу.');
          return;
        }
        clearFormErrors();
        if (!clientValidateProfile(parsed)) {
          haptic('error');
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
        var pr = parsed.profile;
        var body = {
          profile: {
            first_name: pr.first_name,
            last_name: pr.last_name,
            age: pr.age,
            city_id: pr.city_id,
            phone: pr.phone || '',
            contacts: pr.contacts || '',
            description: pr.description || '',
            experience_years: pr.experience_years,
            education: pr.education,
            session_duration_minutes: pr.session_duration_minutes,
            min_hours_before_booking: pr.min_hours_before_booking,
            group_classes_enabled: !!pr.group_classes_enabled,
          },
          services: parsed.services,
          arena_ids: parsed.arena_ids,
        };
        if (parsed.primary_arena_id != null) {
          body.primary_arena_id = parsed.primary_arena_id;
        }

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
                  showSaveToast('Сохранено', 'Изменения успешно применены');
                  return maybeAutoSubmitForModeration();
                });
              }).catch(function(eduErr) {
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
            if (o.status === 422 && o.data && o.data.detail) {
              applyValidationDetail(o.data.detail);
              var stErr =
                SETTINGS_FORMAT_FIELD_IDS.some(function(fid) {
                  var e = document.getElementById('err_' + fid);
                  return e && !e.hidden;
                }) ? 'settings'
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
            console.error(err);
            showFieldError('general', 'Ошибка сети. Проверьте подключение и попробуйте снова.');
          })
          .finally(function() {
            btn.classList.remove('saving');
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
                showSaveToast('Фото загружено', 'Новое изображение отображается в профиле');
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
      var btnSaveScheduleGrid = document.getElementById('btnSaveScheduleGrid');
      if (btnSaveScheduleGrid) btnSaveScheduleGrid.onclick = saveScheduleGridSettings;
      
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
          heroPhotoDropZone.style.boxShadow = '0 0 0 2px rgba(247, 166, 0, 0.85)';
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
        el.addEventListener('input', function() {
          if (id === 'phone') {
            formatPhoneInput(el);
          }
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
      (function() {
        var gce = document.getElementById('group_classes_enabled');
        if (gce) {
          gce.addEventListener('change', function() {
            setDirty();
          });
        }
      })();
      
      function formatPhoneInput(el) {
        var val = el.value.replace(/\D/g, '');
        if (val.startsWith('375')) val = val.slice(3);
        else if (val.startsWith('80')) val = val.slice(2);
        if (val.length > 9) val = val.slice(0, 9);
        
        var formatted = '';
        if (val.length > 0) formatted += val.slice(0, 2);
        if (val.length > 2) formatted += ' ' + val.slice(2, 5);
        if (val.length > 5) formatted += ' ' + val.slice(5, 7);
        if (val.length > 7) formatted += ' ' + val.slice(7, 9);
        
        el.value = formatted;
      }
      
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
      loadInitial();
    })();
