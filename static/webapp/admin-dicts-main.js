    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { tg.ready(); tg.expand(); }
      var initData = tg ? tg.initData : '';

      function apiUrl(path) {
        if (path.indexOf('/api') === 0) return path;
        return '/api/webapp' + path;
      }
      function fetchWithTimeout(url, opts, ms) {
        ms = ms || 15000;
        var c = new AbortController();
        var t = setTimeout(function() { c.abort(); }, ms);
        return fetch(url, Object.assign({}, opts || {}, { signal: c.signal }))
          .then(function(r) { clearTimeout(t); return r; })
          .catch(function(e) { clearTimeout(t); throw e; });
      }
      function withInit(url) {
        var sep = url.indexOf('?') >= 0 ? '&' : '?';
        if (initData) url += sep + 'init_data=' + encodeURIComponent(initData);
        return url;
      }
      function getJson(path) {
        var url = withInit(apiUrl(path));
        return fetchWithTimeout(url).then(function(r) {
          return r.json().catch(function() { return {}; }).then(function(data) {
            if (!r.ok) {
              var msg = (data && data.detail) || r.statusText || ('Ошибка ' + r.status);
              throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
            }
            return data;
          });
        });
      }
      function sendForm(path, formData) {
        var url = withInit(apiUrl(path));
        return fetchWithTimeout(url, { method: 'POST', body: formData }, 30000).then(function(r) {
          if (!r.ok) {
            return r.json().catch(function() {}).then(function(err) {
              var msg = (err && err.detail) || ('Ошибка ' + r.status);
              throw new Error(msg);
            });
          }
          return r.json().catch(function() { return {}; });
        });
      }
      function sendJson(method, path, body) {
        var url = withInit(apiUrl(path));
        return fetchWithTimeout(url, {
          method: method,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body || {})
        }, 15000).then(function(r) {
          if (!r.ok) {
            return r.json().catch(function() {}).then(function(err) {
              var msg = (err && err.detail) || ('Ошибка ' + r.status);
              throw new Error(msg);
            });
          }
          return r.json().catch(function() { return {}; });
        });
      }

      var state = {
        cities: [],
        selectedCityId: null,
        arenas: [],
        cityQ: '',
        cityIncludeInactive: false,
        arenaQ: '',
        arenaIncludeInactive: false,
        iceWeekStart: {},
        iceOpen: {},
        arenaDrafts: {},
        expandedArenaId: null,
        pendingGeo: {}
      };

      var SOCIAL_FIELDS = [
        ['instagram', 'Instagram'],
        ['facebook', 'Facebook'],
        ['vk', 'VK'],
        ['telegram', 'Telegram']
      ];

      function mergedArena(a) {
        var d = state.arenaDrafts[a.id];
        if (!d) return a;
        var m = Object.assign({}, a, d);
        m.id = a.id;
        m.slug = a.slug;
        m.gallery = a.gallery;
        m.is_active = a.is_active;
        if (d.social_urls) {
          m.social_urls = Object.assign({}, a.social_urls || {}, d.social_urls);
        }
        var geo = state.pendingGeo[a.id];
        if (geo) {
          m.latitude = geo.latitude;
          m.longitude = geo.longitude;
        }
        return m;
      }

      function trimOrNull(v) {
        var s = (v || '').trim();
        return s || null;
      }

      function collectDraftFromRow(row) {
        var social = {};
        SOCIAL_FIELDS.forEach(function(pair) {
          var el = row.querySelector('[data-field="social_' + pair[0] + '"]');
          if (el) social[pair[0]] = (el.value || '').trim();
        });
        var openH = (row.querySelector('[data-field="hours_open"]') || {}).value || '';
        var closeH = (row.querySelector('[data-field="hours_close"]') || {}).value || '';
        var venueType = (row.querySelector('[data-field="venue_type"]') || {}).value || 'ice';
        var allowed = {};
        amenityOptionsFor(venueType).forEach(function(pair) { allowed[pair[0]] = true; });
        var amenities = {};
        row.querySelectorAll('[data-amenity]').forEach(function(cb) {
          var key = cb.getAttribute('data-amenity');
          if (allowed[key]) amenities[key] = !!cb.checked;
        });
        var seasonStart = (row.querySelector('[data-field="season_start_month"]') || {}).value;
        var seasonEnd = (row.querySelector('[data-field="season_end_month"]') || {}).value;
        var addressEl = row.querySelector('textarea[data-field="address"], input[data-field="address"]');
        var draft = {
          name: trimOrNull((row.querySelector('[data-field="name"]') || {}).value),
          address: trimOrNull(addressEl && addressEl.value),
          district: trimOrNull((row.querySelector('[data-field="district"]') || {}).value),
          phone: trimOrNull((row.querySelector('[data-field="phone"]') || {}).value),
          website_url: trimOrNull((row.querySelector('[data-field="website_url"]') || {}).value),
          tickets_url: trimOrNull((row.querySelector('[data-field="tickets_url"]') || {}).value),
          short_description: trimOrNull((row.querySelector('[data-field="short_description"]') || {}).value),
          status: (row.querySelector('[data-field="status"]') || {}).value || 'published',
          venue_type: venueType,
          season_start_month: seasonStart ? Number(seasonStart) : null,
          season_end_month: seasonEnd ? Number(seasonEnd) : null,
          amenities: amenities,
          opening_hours: (openH.trim() || closeH.trim())
            ? { daily: { open: openH.trim() || null, close: closeH.trim() || null } }
            : null,
          social_urls: social
        };
        var scheduleEl = row.querySelector('[data-field="schedule_mode"]');
        if (scheduleEl) {
          draft.schedule_mode = scheduleEl.value || 'auto';
          if (draft.schedule_mode === 'season_closed') {
            draft.schedule_mode_note = trimOrNull((row.querySelector('[data-field="schedule_mode_note"]') || {}).value);
            draft.reopen_date = trimOrNull((row.querySelector('[data-field="reopen_date"]') || {}).value);
          }
        }
        var visitInfo = collectVisitInfo(row);
        if (visitInfo !== undefined) draft.visit_info = visitInfo;
        var sortEl = row.querySelector('[data-field="sort_order"]');
        if (sortEl && sortEl.value !== '') {
          var so = Number(sortEl.value);
          if (isFinite(so)) draft.sort_order = so;
        }
        return draft;
      }

      function captureArenaDraftsFromDom() {
        document.querySelectorAll('#arenasCard .arena-row').forEach(function(row) {
          var id = Number(row.getAttribute('data-id'));
          if (!id) return;
          state.arenaDrafts[id] = collectDraftFromRow(row);
        });
      }

      function buildSavePayloadFromRow(row, arenaId) {
        var draft = collectDraftFromRow(row);
        var payload = Object.assign({}, draft);
        var current = (state.arenas.filter(function(x) { return Number(x.id) === arenaId; })[0] || {});
        var currentHours = current.opening_hours || {};
        if (payload.opening_hours) {
          // keep weekly hours from import if daily fields empty
        } else if (currentHours.weekly) {
          delete payload.opening_hours;
        } else {
          payload.opening_hours = null;
        }
        var geo = state.pendingGeo[arenaId];
        if (geo && geo.latitude != null && geo.longitude != null) {
          payload.latitude = geo.latitude;
          payload.longitude = geo.longitude;
        }
        var cleanedSocial = {};
        SOCIAL_FIELDS.forEach(function(pair) {
          var v = trimOrNull((payload.social_urls || {})[pair[0]]);
          if (v) cleanedSocial[pair[0]] = v;
        });
        payload.social_urls = cleanedSocial;
        if (payload.venue_type === 'shop') {
          delete payload.schedule_mode;
          delete payload.schedule_mode_note;
          delete payload.reopen_date;
        } else if (payload.schedule_mode && payload.schedule_mode !== 'season_closed') {
          delete payload.schedule_mode_note;
          delete payload.reopen_date;
        }
        return payload;
      }

      function showAlert(text) {
        if (tg && tg.showAlert) tg.showAlert(text);
        else window.alert(text);
      }
      function showToast(text) {
        var el = document.getElementById('toast');
        if (!el) return;
        el.textContent = text;
        el.classList.add('visible');
        clearTimeout(el._toastT);
        el._toastT = setTimeout(function() { el.classList.remove('visible'); }, 2500);
      }

      var ICE_KIND_LABELS = {
        public_skate: 'МК',
        open_ice: 'Свободное',
        rental: 'Аренда',
        school_group: 'Школа',
        event: 'Событие'
      };
      var ICE_DOW = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

      function mondayIso(d) {
        var day = d instanceof Date ? d : new Date(d);
        var wd = (day.getDay() + 6) % 7;
        day.setDate(day.getDate() - wd);
        return day.toISOString().slice(0, 10);
      }
      function shiftWeek(iso, days) {
        var d = new Date(iso + 'T00:00:00');
        d.setDate(d.getDate() + days);
        return d.toISOString().slice(0, 10);
      }
      function minorFromInput(el) {
        var raw = (el && el.value || '').trim();
        if (!raw) return null;
        var n = Number(raw.replace(',', '.'));
        if (!isFinite(n)) return null;
        return Math.round(n * 100);
      }
      function icePanel(arenaId) {
        return document.querySelector('.ice-week[data-arena-id="' + arenaId + '"]');
      }
      function renderIceWeek(arenaId, data) {
        var el = icePanel(arenaId);
        if (!el) return;
        var weekStart = data.week_start;
        state.iceWeekStart[arenaId] = weekStart;
        var html = '<div class="ice-week-nav">';
        html += '<button type="button" class="btn-ghost" data-ice="prev">←</button>';
        html += '<span>Лёд · ' + weekStart + ' · ' + (data.currency_code || '') + '</span>';
        html += '<span><button type="button" class="btn-ghost" data-ice="copy">Копировать неделю</button>';
        html += '<button type="button" class="btn-ghost" data-ice="next">→</button></span></div>';
        html += '<div class="ice-week-days">';
        (data.days || []).forEach(function(day) {
          html += '<div class="ice-day" data-date="' + day.local_date + '">';
          html += '<div class="ice-day-label">' + (ICE_DOW[day.weekday] || '') + ' ' + day.local_date.slice(8) + '</div>';
          (day.sessions || []).forEach(function(s) {
            html += '<div class="ice-slot' + (s.status === 'cancelled' ? ' ice-slot-cancelled' : '') + '">';
            html += escapeHtml((s.starts_at_local || '') + ' ' + (ICE_KIND_LABELS[s.kind] || s.kind));
            html += '<button type="button" data-ice="del" data-session-id="' + s.id + '" title="Удалить">×</button>';
            html += '</div>';
          });
          html += '</div>';
        });
        html += '</div>';
        html += '<div class="ice-add">';
        html += '<input type="date" data-ice-field="local_date" value="' + weekStart + '">';
        html += '<input type="time" data-ice-field="starts_at_local" value="11:00">';
        html += '<input type="number" data-ice-field="duration_minutes" min="30" max="120" value="45" placeholder="мин">';
        html += '<select data-ice-field="kind">';
        ['public_skate','open_ice','rental','school_group','event'].forEach(function(k) {
          html += '<option value="' + k + '">' + ICE_KIND_LABELS[k] + '</option>';
        });
        html += '</select>';
        html += '<input type="number" step="0.01" min="0" data-ice-field="price_adult" placeholder="взр. ' + (data.currency_code || '') + '">';
        html += '<input type="number" step="0.01" min="0" data-ice-field="price_child" placeholder="дет.">';
        html += '<input type="number" step="0.01" min="0" data-ice-field="price_rental" placeholder="прокат">';
        html += '<label class="muted"><input type="checkbox" data-ice-field="repeat_weekly"> каждую неделю</label>';
        html += '</div>';
        html += '<button type="button" class="btn-ghost" data-ice="add" style="margin-top:6px">+ Сеанс</button>';
        el.innerHTML = html;
        el.querySelector('[data-ice="prev"]').addEventListener('click', function() {
          loadIceWeek(arenaId, shiftWeek(weekStart, -7));
        });
        el.querySelector('[data-ice="next"]').addEventListener('click', function() {
          loadIceWeek(arenaId, shiftWeek(weekStart, 7));
        });
        el.querySelector('[data-ice="copy"]').addEventListener('click', function() {
          sendJson('POST', '/admin/arenas/' + arenaId + '/ice-sessions/copy-week', { from_week_start: weekStart })
            .then(function(res) {
              showToast('Скопировано: ' + (res.copied || 0));
              return loadIceWeek(arenaId, shiftWeek(weekStart, 7));
            })
            .catch(function(err) { showAlert(err.message || String(err)); });
        });
        el.querySelectorAll('[data-ice="del"]').forEach(function(btn) {
          btn.addEventListener('click', function() {
            sendJson('DELETE', '/admin/ice-sessions/' + btn.getAttribute('data-session-id'), {})
              .then(function() { return loadIceWeek(arenaId, weekStart); })
              .catch(function(err) { showAlert(err.message || String(err)); });
          });
        });
        el.querySelector('[data-ice="add"]').addEventListener('click', function() {
          var payload = {
            local_date: (el.querySelector('[data-ice-field="local_date"]') || {}).value,
            starts_at_local: (el.querySelector('[data-ice-field="starts_at_local"]') || {}).value,
            duration_minutes: Number((el.querySelector('[data-ice-field="duration_minutes"]') || {}).value || 45),
            kind: (el.querySelector('[data-ice-field="kind"]') || {}).value || 'public_skate',
            price_adult_minor: minorFromInput(el.querySelector('[data-ice-field="price_adult"]')),
            price_child_minor: minorFromInput(el.querySelector('[data-ice-field="price_child"]')),
            price_rental_minor: minorFromInput(el.querySelector('[data-ice-field="price_rental"]')),
            repeat_weekly: !!(el.querySelector('[data-ice-field="repeat_weekly"]') || {}).checked
          };
          sendJson('POST', '/admin/arenas/' + arenaId + '/ice-sessions', payload)
            .then(function() {
              showToast('Сеанс сохранён');
              return loadIceWeek(arenaId, weekStart);
            })
            .catch(function(err) { showAlert(err.message || String(err)); });
        });
      }
      function loadIceWeek(arenaId, weekStart) {
        var start = weekStart || state.iceWeekStart[arenaId] || mondayIso(new Date());
        return getJson('/admin/arenas/' + arenaId + '/ice-sessions?week_start=' + encodeURIComponent(start) + '&include_cancelled=true')
          .then(function(data) {
            var panel = icePanel(arenaId);
            if (panel) panel.hidden = false;
            state.iceOpen[arenaId] = true;
            renderIceWeek(arenaId, data);
          })
          .catch(function(err) { showAlert(err.message || String(err)); });
      }

      function renderCities() {
        var card = document.getElementById('citiesCard');
        if (!state.cities.length) {
          card.innerHTML = '<div class="empty">Пока нет городов. Добавьте первый.</div>';
          document.getElementById('btnAddArena').disabled = true;
          document.getElementById('arenasCard').innerHTML = '<div class="empty">Выберите город слева, чтобы увидеть арены.</div>';
          document.getElementById('arenasTitle').textContent = 'Арены';
          return;
        }
        var html = '<div class="list">';
        state.cities.forEach(function(c) {
          var active = c.id === state.selectedCityId;
          var isActive = c.is_active !== false;
          html += '<div class="city-row' + (active ? ' active' : '') + '" data-id="' + c.id + '">';
          html += '<div class="city-main">';
          html += '<div class="city-name">' + (c.name || '—') + (isActive ? '' : ' <span class="badge-inactive">неактив.</span>') + '</div>';
          html += '<div class="city-meta">Арен: ' + (c.arenas_count || 0) + '</div>';
          html += '</div>';
          html += '<div class="city-actions">';
          html += '<button class="icon-btn" data-role="' + (isActive ? 'deactivate' : 'activate') + '" data-id="' + c.id + '" title="' + (isActive ? 'Деактивировать' : 'Вернуть') + '">' + (isActive ? '⏸' : '▶') + '</button>';
          html += '<button class="icon-btn" data-role="edit" data-id="' + c.id + '">✏️</button>';
          html += '</div>';
          html += '</div>';
        });
        html += '</div>';
        card.innerHTML = html;

        card.querySelectorAll('.city-row').forEach(function(el) {
          el.addEventListener('click', function(e) {
            var id = Number(el.getAttribute('data-id'));
            if (state.selectedCityId !== id) {
              state.selectedCityId = id;
              state.arenaDrafts = {};
              state.pendingGeo = {};
              state.expandedArenaId = null;
              loadArenas();
              renderCities();
            }
          });
        });
        card.querySelectorAll('.icon-btn[data-role="edit"]').forEach(function(btn) {
          btn.addEventListener('click', function(e) {
            e.stopPropagation();
            var id = Number(btn.getAttribute('data-id'));
            var city = state.cities.find(function(c) { return c.id === id; });
            if (!city) return;
            showEditCityForm(true, id, city.name || '');
          });
        });
        card.querySelectorAll('.icon-btn[data-role="deactivate"], .icon-btn[data-role="activate"]').forEach(function(btn) {
          btn.addEventListener('click', function(e) {
            e.stopPropagation();
            var id = Number(btn.getAttribute('data-id'));
            var isAct = btn.getAttribute('data-role') === 'activate';
            sendJson('PATCH', '/admin/cities/' + id, { is_active: isAct })
              .then(function() { return loadCities(true); })
              .catch(function(err) { showAlert(err.message || String(err)); });
          });
        });
      }

      var AMENITY_OPTIONS = [
        ['skate_rental', 'Прокат'],
        ['skate_sharpening', 'Заточка'],
        ['parking', 'Парковка'],
        ['locker_rooms', 'Раздевалки'],
        ['cafe', 'Кафе'],
        ['accessibility', 'Доступность']
      ];
      /* TASK-146: у магазина вместо удобств — услуги. Прокат и заточка — те же ключи,
         что у катка (сервер сверяет набор с типом площадки: arena_profile.py). */
      var SHOP_AMENITY_OPTIONS = [
        ['retail', 'Розница'],
        ['skate_sharpening', 'Заточка'],
        ['skate_molding', 'Формовка'],
        ['blade_profiling', 'Профилирование'],
        ['foot_scan', '3D-скан стопы'],
        ['skate_rental', 'Прокат'],
        ['repair', 'Ремонт'],
        ['discipline_hockey', 'Хоккей'],
        ['discipline_figure', 'Фигурное'],
        ['discipline_roller', 'Ролики'],
        ['parking', 'Парковка'],
        ['accessibility', 'Доступность']
      ];
      var VENUE_TYPE_FALLBACK = [
        { key: 'ice', chip: 'Лёд' }, { key: 'gym', chip: 'Зал' },
        { key: 'choreo', chip: 'Хореография' }, { key: 'pool', chip: 'Бассейн' },
        { key: 'outdoor', chip: 'Улица' }, { key: 'other', chip: 'Другое' },
        { key: 'shop', chip: 'Магазин' }
      ];
      function amenityOptionsFor(venueType) {
        return venueType === 'shop' ? SHOP_AMENITY_OPTIONS : AMENITY_OPTIONS;
      }
      function venueTypeSelectHtml(dataAttr, selected) {
        var types = (state.venueTypes && state.venueTypes.length) ? state.venueTypes : VENUE_TYPE_FALLBACK;
        var html = '<select ' + dataAttr + '>';
        types.forEach(function(t) {
          html += '<option value="' + escapeHtml(t.key) + '"' + (t.key === selected ? ' selected' : '') + '>' + escapeHtml(t.chip) + '</option>';
        });
        return html + '</select>';
      }

      function escapeHtml(s) {
        return String(s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      var ARENA_STATUS_OPTS = [
        ['draft', 'Черновик'],
        ['published', 'Опубликовано'],
        ['archived', 'В архиве']
      ];
      var NEW_ARENA_KEY = 'new';

      function arenaStatusOptionsHtml(status) {
        var html = '';
        ARENA_STATUS_OPTS.forEach(function(pair) {
          html += '<option value="' + pair[0] + '"' + (status === pair[0] ? ' selected' : '') + '>' +
            escapeHtml(pair[1]) + '</option>';
        });
        return html;
      }

      function emptyArenaDefaults() {
        return {
          name: '',
          address: '',
          district: '',
          phone: '',
          website_url: '',
          tickets_url: '',
          short_description: '',
          status: 'published',
          venue_type: 'ice',
          schedule_mode: 'auto',
          schedule_mode_note: '',
          reopen_date: '',
          sort_order: null,
          season_start_month: null,
          season_end_month: null,
          amenities: {},
          social_urls: {},
          opening_hours: null
        };
      }

      // ── Карточка катка (arena_profiles.visit_info). Ключи — контракт arena_visit_info.py ──
      var VISIT_TICKET_MODES = [
        ['', 'Авто'], ['online', 'Онлайн'], ['same_day', 'Онлайн в день сеанса'],
        ['box_office', 'Только касса'], ['phone', 'Расписание по телефону']
      ];
      var VISIT_TRI = [['', 'не знаем'], ['true', 'да'], ['false', 'нет']];
      var VISIT_FACT_STATES = [['', 'не знаем'], ['yes', 'есть'], ['no', 'нет']];
      var VISIT_WARMTH = [['', 'не знаем'], ['warm', 'тепло'], ['cool', 'прохладно'], ['cold', 'холодно']];
      var VISIT_FACT_ICONS = [
        ['hanger', 'Раздевалка'], ['lock', 'Замок'], ['cup', 'Кафе'], ['thermo', 'Температура'],
        ['card', 'Оплата'], ['child', 'Дети'], ['eye', 'Трибуна'], ['ruler', 'Размеры'],
        ['clock', 'Время'], ['info', 'Инфо'], ['parking', 'Парковка'], ['person', 'Человек']
      ];
      var VISIT_SERVICE_KINDS = [
        ['aid', 'Опора «пингвин»'], ['rental', 'Прокат коньков'], ['sharpening', 'Заточка'],
        ['protection', 'Защита'], ['helmet', 'Шлем'], ['other', 'Другое']
      ];
      var VISIT_LISTS = {
        custom_facts: { add: '+ Факт', cols: [['icon', 'select', VISIT_FACT_ICONS, 'info'], ['title', 'text', 'Заголовок'], ['note', 'text', 'Пояснение']] },
        services: { add: '+ Услуга', cols: [['kind', 'select', VISIT_SERVICE_KINDS, 'rental'], ['label', 'text', 'Название (если «Другое»)'], ['price', 'text', 'Цена'], ['note', 'text', 'Пояснение']] },
        'school.rows': { add: '+ Строка', cols: [['label', 'text', 'Занятие'], ['child', 'text', 'Детям'], ['adult', 'text', 'Взрослым']] },
        'passes.rows': { add: '+ Абонемент', cols: [['label', 'text', 'Название'], ['v0', 'text', 'Цена 1'], ['v1', 'text', 'Цена 2']] },
        'rink_rental.rows': { add: '+ Тариф', cols: [['label', 'text', 'Название'], ['minutes', 'number', 'Минут'], ['price', 'text', 'Цена']] }
      };

      function visitGet(obj, path) {
        var cur = obj;
        String(path).split('.').forEach(function(k) {
          cur = (cur && typeof cur === 'object') ? cur[k] : undefined;
        });
        return cur;
      }
      function visitSet(obj, path, value) {
        var keys = String(path).split('.');
        var cur = obj;
        keys.slice(0, -1).forEach(function(k) {
          if (!cur[k] || typeof cur[k] !== 'object') cur[k] = {};
          cur = cur[k];
        });
        cur[keys[keys.length - 1]] = value;
      }
      function visitStr(v) {
        return v === true ? 'true' : v === false ? 'false' : (v == null ? '' : String(v));
      }
      function visitInput(path, v, opts) {
        opts = opts || {};
        return '<input data-v="' + path + '"' + (opts.type ? ' type="' + opts.type + '"' : '') +
          (opts.ph ? ' placeholder="' + escapeHtml(opts.ph) + '"' : '') + ' value="' + escapeHtml(visitStr(v)) + '">';
      }
      function visitSelect(attr, pairs, current) {
        var html = '<select ' + attr + '>';
        pairs.forEach(function(p) {
          html += '<option value="' + p[0] + '"' + (visitStr(current) === p[0] ? ' selected' : '') + '>' + escapeHtml(p[1]) + '</option>';
        });
        return html + '</select>';
      }
      function visitField(label, inner) {
        return '<div class="field"><label>' + label + '</label>' + inner + '</div>';
      }
      function visitRowHtml(listKey, row) {
        var spec = VISIT_LISTS[listKey];
        var html = '<div class="visit-row">';
        spec.cols.forEach(function(c) {
          var v = row[c[0]];
          if (c[0] === 'v0' || c[0] === 'v1') v = (row.values || [])[c[0] === 'v0' ? 0 : 1];
          if (c[1] === 'select') html += visitSelect('data-vk="' + c[0] + '"', c[2], v || c[3]);
          else html += '<input data-vk="' + c[0] + '"' + (c[1] === 'number' ? ' type="number" inputmode="numeric"' : '') +
            ' placeholder="' + escapeHtml(c[2]) + '" value="' + escapeHtml(visitStr(v)) + '">';
        });
        return html + '<button type="button" class="btn-ghost" data-vrole="del" title="Убрать">×</button></div>';
      }
      function visitListHtml(listKey, rows) {
        var html = '<div class="visit-list" data-vlist="' + listKey + '">';
        (rows || []).forEach(function(r) { html += visitRowHtml(listKey, r || {}); });
        return html + '</div><button type="button" class="btn-ghost visit-add" data-vrole="add" data-vlist-key="' +
          listKey + '">' + VISIT_LISTS[listKey].add + '</button>';
      }
      function visitGroup(title, inner, open) {
        return '<details class="visit-group"' + (open ? ' open' : '') + '><summary>' + title + '</summary>' + inner + '</details>';
      }
      function visitInfoSectionHtml(a) {
        var v = (a.visit_info && typeof a.visit_info === 'object') ? a.visit_info : {};
        var armId = 'vm' + (a.id != null ? a.id : 'new');
        var html = '<details class="arena-section visit-section"><summary class="arena-section-title">Карточка катка</summary>';
        var mode = visitStr(visitGet(v, 'tickets.mode'));
        var g = '<div class="field"><label>Как продаются билеты</label><div class="amenity-grid visit-modes">';
        VISIT_TICKET_MODES.forEach(function(p) {
          g += '<label><input type="radio" name="' + armId + '" data-v="tickets.mode" value="' + p[0] + '"' +
            (mode === p[0] ? ' checked' : '') + '> ' + escapeHtml(p[1]) + '</label>';
        });
        g += '</div></div>';
        g += '<div class="field-row">' + visitField('Касса с', visitInput('tickets.open', visitGet(v, 'tickets.open'), { ph: '09:00' })) +
          visitField('до', visitInput('tickets.close', visitGet(v, 'tickets.close'), { ph: '21:00' })) + '</div>';
        g += '<div class="field-row field-row--3">' +
          visitField('Продают за (дней)', visitInput('tickets.presale_days', visitGet(v, 'tickets.presale_days'), { type: 'number' })) +
          visitField('Картой', visitSelect('data-v="tickets.card"', VISIT_TRI, visitGet(v, 'tickets.card'))) +
          visitField('Наличными', visitSelect('data-v="tickets.cash"', VISIT_TRI, visitGet(v, 'tickets.cash'))) + '</div>';
        g += '<div class="amenity-grid"><label><input type="checkbox" data-v="tickets.desk_only_services"' +
          (visitGet(v, 'tickets.desk_only_services') === true ? ' checked' : '') + '> Прокат и заточку оплачивают только в кассе</label></div>';
        g += visitField('Пояснение к билетам', visitInput('tickets.note', visitGet(v, 'tickets.note')));
        html += visitGroup('Как купить билет', g, true);

        html += visitGroup('Вход', visitField('Детский билет до (лет)', visitInput('child_age_max', v.child_age_max, { type: 'number' })));

        g = '';
        [['locker_rooms', 'Раздевалка'], ['lockers', 'Камеры хранения'], ['cafe', 'Кафе'], ['parking', 'Парковка']].forEach(function(p) {
          g += '<div class="field-row">' + visitField(p[1], visitSelect('data-v="facts.' + p[0] + '.state"', VISIT_FACT_STATES, visitGet(v, 'facts.' + p[0] + '.state'))) +
            visitField('Пояснение', visitInput('facts.' + p[0] + '.note', visitGet(v, 'facts.' + p[0] + '.note'))) + '</div>';
        });
        g += '<div class="field-row">' + visitField('Температура внутри', visitSelect('data-v="facts.warmth.state"', VISIT_WARMTH, visitGet(v, 'facts.warmth.state'))) +
          visitField('Пояснение', visitInput('facts.warmth.note', visitGet(v, 'facts.warmth.note'))) + '</div>';
        g += '<div class="field-row field-row--3">' + visitField('Трибуна', visitSelect('data-v="facts.spectators.state"', VISIT_FACT_STATES, visitGet(v, 'facts.spectators.state'))) +
          visitField('Цена', visitInput('facts.spectators.price', visitGet(v, 'facts.spectators.price'))) +
          visitField('Пояснение', visitInput('facts.spectators.note', visitGet(v, 'facts.spectators.note'))) + '</div>';
        g += '<div class="field"><label>Свои факты</label>' + visitListHtml('custom_facts', v.custom_facts) + '</div>';
        html += visitGroup('Что важно знать', g);

        g = '<div class="field"><label>Услуги</label>' + visitListHtml('services', v.services) + '</div>';
        g += '<div class="field-row">' + visitField('Размеры проката', visitInput('rental.sizes', visitGet(v, 'rental.sizes'), { ph: '28–46' })) +
          visitField('Залог', visitInput('rental.deposit', visitGet(v, 'rental.deposit'))) + '</div>';
        html += visitGroup('Прокат и услуги', g);

        g = '<div class="field-row field-row--3">' + visitField('Учат с (лет)', visitInput('school.age_from', visitGet(v, 'school.age_from'), { type: 'number' })) +
          visitField('Телефон', visitInput('school.phone', visitGet(v, 'school.phone'))) +
          visitField('Контакт', visitInput('school.contact', visitGet(v, 'school.contact'))) + '</div>';
        g += '<div class="field"><label>Занятия и цены</label>' + visitListHtml('school.rows', visitGet(v, 'school.rows')) + '</div>';
        html += visitGroup('Школа катка', g);

        var cols = visitGet(v, 'passes.columns');
        cols = (cols && cols.length) ? cols : ['Детский', 'Взрослый'];
        g = '<div class="field-row">' + visitField('Колонка 1', visitInput('passes.col0', cols[0])) +
          visitField('Колонка 2', visitInput('passes.col1', cols[1] || '')) + '</div>';
        g += '<div class="field"><label>Абонементы</label>' + visitListHtml('passes.rows', visitGet(v, 'passes.rows')) + '</div>';
        html += visitGroup('Абонементы', g);

        g = '<div class="field"><label>Тарифы</label>' + visitListHtml('rink_rental.rows', visitGet(v, 'rink_rental.rows')) + '</div>';
        g += visitField('Телефон для заказа', visitInput('rink_rental.phone', visitGet(v, 'rink_rental.phone')));
        html += visitGroup('Снять лёд целиком', g);
        return html + '</details>';
      }
      function collectVisitInfo(row) {
        var sec = row.querySelector('.visit-section');
        if (!sec) return undefined;
        var out = {};
        sec.querySelectorAll('[data-v]').forEach(function(el) {
          var path = el.getAttribute('data-v');
          var val;
          if (el.type === 'radio') {
            if (!el.checked) return;
            val = el.value;
          } else if (el.type === 'checkbox') {
            val = el.checked ? true : '';
          } else {
            val = (el.value || '').trim();
            if (el.tagName === 'SELECT') {
              if (val === 'true') val = true;
              else if (val === 'false') val = false;
            }
          }
          visitSet(out, path, val);
        });
        if (out.passes) {
          out.passes.columns = [out.passes.col0 || '', out.passes.col1 || ''].filter(function(c) { return c; });
          delete out.passes.col0;
          delete out.passes.col1;
        }
        sec.querySelectorAll('.visit-list').forEach(function(list) {
          var key = list.getAttribute('data-vlist');
          var rows = [];
          list.querySelectorAll('.visit-row').forEach(function(r) {
            var item = {};
            var values = [];
            r.querySelectorAll('[data-vk]').forEach(function(el) {
              var k = el.getAttribute('data-vk');
              var val = (el.value || '').trim();
              if (k === 'v0') values[0] = val;
              else if (k === 'v1') values[1] = val;
              else item[k] = val;
            });
            if (key === 'passes.rows') item.values = values.map(function(x) { return x || ''; });
            rows.push(item);
          });
          visitSet(out, key, rows);
        });
        return out;
      }
      function bindVisitIn(root) {
        (root || document).querySelectorAll('.visit-section').forEach(function(sec) {
          if (sec.getAttribute('data-bound') === '1') return;
          sec.setAttribute('data-bound', '1');
          sec.addEventListener('click', function(e) {
            var btn = e.target.closest ? e.target.closest('[data-vrole]') : null;
            if (!btn) return;
            e.stopPropagation();
            if (btn.getAttribute('data-vrole') === 'del') {
              var rowEl = btn.closest('.visit-row');
              if (rowEl) rowEl.parentNode.removeChild(rowEl);
              return;
            }
            var key = btn.getAttribute('data-vlist-key');
            var list = btn.previousElementSibling;
            if (!list || !VISIT_LISTS[key]) return;
            var tmp = document.createElement('div');
            tmp.innerHTML = visitRowHtml(key, {});
            list.appendChild(tmp.firstChild);
          });
        });
      }

      function arenaProfileBodyHtml(a, opts) {
        opts = opts || {};
        var includePhotos = opts.includePhotos !== false;
        var arenaId = opts.arenaId;
        var hours = (a.opening_hours && a.opening_hours.daily) || {};
        var amenities = a.amenities || {};
        var socials = a.social_urls || {};
        var status = a.status || 'published';
        var venueType = a.venue_type || 'ice';
        var html = '';
        html += '<section class="arena-section"><h3 class="arena-section-title">Основное</h3>';
        html += '<div class="field-row field-row--1"><div class="field"><label>Название</label><input data-field="name" value="' + escapeHtml(a.name || '') + '" placeholder="Как в каталоге"></div></div>';
        html += '<div class="field-row field-row--3">';
        html += '<div class="field"><label>Тип места</label>' + venueTypeSelectHtml('data-field="venue_type"', venueType) + '</div>';
        html += '<div class="field"><label>Порядок в списке</label><input data-field="sort_order" type="number" value="' + (a.sort_order != null ? a.sort_order : '') + '" placeholder="0" title="Меньше — выше"></div>';
        html += '<div class="field"><label>Публикация</label><select data-field="status">' + arenaStatusOptionsHtml(status) + '</select></div>';
        html += '</div>';
        html += '<div class="field-row field-row--1"><div class="field field-address">';
        html += '<label>Адрес</label>';
        html += '<textarea data-field="address" rows="3" placeholder="Улица, дом, ориентиры">' + escapeHtml(a.address || '') + '</textarea>';
        html += '</div></div></section>';
        html += '<section class="arena-section"><h3 class="arena-section-title">Контакты и ссылки</h3>';
        html += '<div class="field-row">';
        html += '<div class="field"><label>Район</label><input data-field="district" value="' + escapeHtml(a.district || '') + '" placeholder="Заводской"></div>';
        html += '<div class="field"><label>Телефон</label><input data-field="phone" type="tel" inputmode="tel" value="' + escapeHtml(a.phone || '') + '" placeholder="+375…"></div>';
        html += '</div>';
        html += '<div class="field-row field-row--1">';
        html += '<div class="field"><label>Сайт</label><input data-field="website_url" type="url" inputmode="url" value="' + escapeHtml(a.website_url || '') + '" placeholder="https://"></div>';
        html += '</div>';
        html += '<div class="field-row field-row--1">';
        html += '<div class="field"><label>Билеты онлайн</label><input data-field="tickets_url" type="url" inputmode="url" value="' + escapeHtml(a.tickets_url || '') + '" placeholder="https://…"></div>';
        html += '</div></section>';
        html += '<section class="arena-section"><h3 class="arena-section-title">Соцсети</h3><div class="field-row social-row">';
        SOCIAL_FIELDS.forEach(function(pair) {
          html += '<div class="field"><label>' + pair[1] + '</label><input data-field="social_' + pair[0] + '" type="url" inputmode="url" value="' + escapeHtml(socials[pair[0]] || '') + '" placeholder="https://"></div>';
        });
        html += '</div></section>';
        if (venueType !== 'shop') {
          var seasonClosed = (a.schedule_mode || 'auto') === 'season_closed';
          html += '<section class="arena-section arena-section-schedule"><h3 class="arena-section-title">Режим расписания</h3>';
          html += '<div class="field-row field-row--1"><div class="field"><label>Как показывать сеансы</label><select data-field="schedule_mode">';
          [['auto', 'авто (парсер)'], ['phone', 'по телефону'], ['season_closed', 'сезон закрыт']].forEach(function(opt) {
            var sel = (a.schedule_mode || 'auto') === opt[0] ? ' selected' : '';
            html += '<option value="' + opt[0] + '"' + sel + '>' + opt[1] + '</option>';
          });
          html += '</select></div></div>';
          html += '<div class="field-row field-row--1 schedule-season-only"' + (seasonClosed ? '' : ' hidden') + '><div class="field"><label>Откроется (дата)</label>';
          html += '<input data-field="reopen_date" type="date" value="' + escapeHtml((a.reopen_date || '').slice(0, 10)) + '"></div></div>';
          html += '<div class="field-row field-row--1 schedule-season-only"' + (seasonClosed ? '' : ' hidden') + '><div class="field field-address"><label>Текст для гостей</label>';
          html += '<input data-field="schedule_mode_note" value="' + escapeHtml(a.schedule_mode_note || '') + '" placeholder="Например: откроем в декабре"></div></div>';
          html += '</section>';
        }
        html += '<section class="arena-section"><h3 class="arena-section-title">Описание и часы</h3>';
        html += '<div class="field-row field-row--1"><div class="field field-address"><label>Краткое описание</label>';
        html += '<textarea data-field="short_description" rows="3">' + escapeHtml(a.short_description || '') + '</textarea></div></div>';
        html += '<div class="field-row">';
        html += '<div class="field"><label>Открыт с</label><input data-field="hours_open" inputmode="numeric" placeholder="07:00" value="' + escapeHtml(hours.open || '') + '"></div>';
        html += '<div class="field"><label>до</label><input data-field="hours_close" inputmode="numeric" placeholder="23:00" value="' + escapeHtml(hours.close || '') + '"></div>';
        html += '</div>';
        html += '<div class="field-row">';
        html += '<div class="field"><label>Сезон с (мес.)</label><input data-field="season_start_month" type="number" min="1" max="12" value="' + (a.season_start_month || '') + '"></div>';
        html += '<div class="field"><label>по (мес.)</label><input data-field="season_end_month" type="number" min="1" max="12" value="' + (a.season_end_month || '') + '"></div>';
        html += '</div>';
        html += '<div class="field"><label>' + (venueType === 'shop' ? 'Услуги' : 'Удобства') + '</label><div class="amenity-grid">';
        amenityOptionsFor(venueType).forEach(function(pair) {
          var checked = amenities[pair[0]] === true ? ' checked' : '';
          html += '<label><input type="checkbox" data-amenity="' + pair[0] + '"' + checked + '> ' + pair[1] + '</label>';
        });
        html += '</div></div></section>';
        if (includePhotos && venueType !== 'shop') html += visitInfoSectionHtml(a);
        if (includePhotos && arenaId != null) {
          html += '<section class="arena-section"><h3 class="arena-section-title">Фото</h3>';
          html += '<p class="muted" style="margin:0 0 8px;">До 6 снимков. Первое — hero в каталоге.</p>';
          html += '<div class="field"><label class="visually-hidden">Галерея</label>';
          html += '<div class="arena-gallery" data-arena-id="' + arenaId + '">';
          var gallery = a.gallery || [];
          if (!gallery.length) {
            html += '<div class="arena-photo-placeholder">Нет фото — в карточке будет плейсхолдер</div>';
          }
          gallery.forEach(function(item, idx) {
            var variants = item.variants || {};
            var thumb = variants.thumb || variants.card || variants.hero || '';
            html += '<div class="arena-photo" data-media-id="' + item.id + '">';
            if (thumb) html += '<img src="' + escapeHtml(thumb) + '" alt="">';
            else html += '<div class="arena-photo-placeholder"></div>';
            if (idx === 0) html += '<span class="arena-photo-hero">hero</span>';
            html += '<div class="arena-photo-actions">';
            html += '<button type="button" class="btn-ghost" data-role="photo-up" data-id="' + arenaId + '">↑</button>';
            html += '<button type="button" class="btn-ghost" data-role="photo-down" data-id="' + arenaId + '">↓</button>';
            html += '<button type="button" class="btn-ghost" data-role="photo-del" data-id="' + arenaId + '" data-media-id="' + item.id + '">×</button>';
            html += '</div></div>';
          });
          if (gallery.length < 6) {
            html += '<label class="arena-photo-add">+<input type="file" accept="image/*" data-role="photo-file" data-id="' + arenaId + '" hidden></label>';
          }
          html += '</div>';
          html += '<div class="field-row">';
          html += '<div class="field"><label>Лицензия нового фото</label><select data-field="photo_license">';
          [['own', 'своё'], ['operator', 'оператор'], ['user', 'пользователь'], ['permitted', 'с разрешения']].forEach(function(opt) {
            html += '<option value="' + opt[0] + '">' + opt[1] + '</option>';
          });
          html += '</select></div>';
          html += '<div class="field"><label>Источник / атрибуция</label><input data-field="photo_source" placeholder="URL или «Каток Замок»"></div>';
          html += '</div></div></section>';
        } else if (!includePhotos) {
          html += '<p class="muted new-arena-photo-hint">Фото можно загрузить сразу после создания — карточка откроется автоматически.</p>';
        }
        return html;
      }

      function mapLinksHtml(a, id) {
        var addr = (a.address || '').trim();
        var yandexUrl = addr ? 'https://yandex.ru/maps/?text=' + encodeURIComponent(addr) : '';
        var googleUrl = addr ? 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(addr) : '';
        var html = '<div class="map-links">';
        if (yandexUrl) html += '<a href="' + yandexUrl + '" target="_blank" rel="noopener">Яндекс карта</a>';
        if (googleUrl) html += '<a href="' + googleUrl + '" target="_blank" rel="noopener">Google карта</a>';
        html += '<button type="button" class="btn-geocode" data-role="geocode" data-id="' + id + '">Координаты по адресу</button>';
        html += '</div>';
        return html;
      }

      function bindScheduleModeIn(root) {
        (root || document).querySelectorAll('[data-field="schedule_mode"]').forEach(function(sel) {
          var row = sel.closest('.arena-row') || sel.closest('#addArenaForm');
          if (!row) return;
          function syncScheduleFields() {
            var show = sel.value === 'season_closed';
            row.querySelectorAll('.schedule-season-only').forEach(function(el) {
              el.hidden = !show;
            });
          }
          sel.addEventListener('change', syncScheduleFields);
          syncScheduleFields();
        });
      }

      function bindGeocodeIn(root) {
        (root || document).querySelectorAll('[data-role="geocode"]').forEach(function(btn) {
          if (btn.getAttribute('data-bound') === '1') return;
          btn.setAttribute('data-bound', '1');
          btn.addEventListener('click', function() {
            var idAttr = btn.getAttribute('data-id');
            var geoKey = idAttr === NEW_ARENA_KEY ? NEW_ARENA_KEY : Number(idAttr);
            var row = btn.closest('.arena-row') || document.getElementById('addArenaForm');
            if (!row) return;
            var addressEl = row.querySelector('[data-field="address"]');
            var addr = (addressEl && addressEl.value || '').trim();
            if (!addr) {
              showAlert('Сначала укажите адрес');
              return;
            }
            btn.disabled = true;
            getJson('/admin/geocode?address=' + encodeURIComponent(addr))
              .then(function(data) {
                state.pendingGeo[geoKey] = { latitude: data.latitude, longitude: data.longitude };
                if (geoKey !== NEW_ARENA_KEY) {
                  captureArenaDraftsFromDom();
                  showToast('Координаты найдены — нажмите 💾');
                  renderArenas();
                } else {
                  showToast('Координаты найдены — сохранятся при добавлении');
                }
              })
              .catch(function(err) { showAlert(err.message || String(err)); })
              .then(function() { btn.disabled = false; });
          });
        });
      }

      function draftFromNewArenaRow(row) {
        var draft = collectDraftFromRow(row);
        var a = Object.assign(emptyArenaDefaults(), draft);
        if (draft.social_urls) a.social_urls = draft.social_urls;
        if (draft.amenities) a.amenities = draft.amenities;
        if (draft.opening_hours) a.opening_hours = draft.opening_hours;
        return a;
      }

      function renderAddArenaFormBody() {
        var row = document.querySelector('#addArenaForm .arena-row--new');
        if (!row) return;
        var body = row.querySelector('.arena-body');
        if (!body) return;
        var a = draftFromNewArenaRow(row);
        body.innerHTML = arenaProfileBodyHtml(a, { includePhotos: false, arenaId: NEW_ARENA_KEY }) + mapLinksHtml(a, NEW_ARENA_KEY);
        bindScheduleModeIn(body);
        bindGeocodeIn(body);
        body.querySelectorAll('[data-field="venue_type"]').forEach(function(sel) {
          sel.addEventListener('change', function() {
            renderAddArenaFormBody();
          });
        });
      }

      function renderArenas() {
        var card = document.getElementById('arenasCard');
        var btnAdd = document.getElementById('btnAddArena');
        var title = document.getElementById('arenasTitle');
        var selectedCity = state.cities.find(function(c) { return c.id === state.selectedCityId; });
        if (!selectedCity) {
          btnAdd.disabled = true;
          title.textContent = 'Арены';
          card.innerHTML = '<div class="empty">Выберите город слева, чтобы увидеть арены.</div>';
          return;
        }
        btnAdd.disabled = false;
        title.textContent = 'Арены: ' + (selectedCity.name || '');
        if (!state.arenas.length) {
          card.innerHTML = '<div class="empty">Пока нет арен. Нажмите «+ Арена».</div>';
          return;
        }
        var html = '';
        state.arenas.forEach(function(raw) {
          var a = mergedArena(raw);
          var isActive = a.is_active !== false;
          var addr = (a.address || '').trim();
          var expanded = state.expandedArenaId === a.id;
          var hasDraft = !!state.arenaDrafts[a.id];
          var geo = state.pendingGeo[a.id];
          var coordHint = geo
            ? 'координаты готовы к сохранению'
            : (a.latitude != null && a.longitude != null ? 'на карте' : 'без координат');
          html += '<div class="arena-row' + (expanded ? ' expanded' : '') + (hasDraft ? ' has-draft' : '') + '" data-id="' + a.id + '">';
          html += '<div class="arena-header" role="button" tabindex="0" aria-expanded="' + expanded + '">';
          html += '<div class="arena-header-main">';
          html += '<span class="arena-chevron" aria-hidden="true">' + (expanded ? '▾' : '▸') + '</span>';
          html += '<div>';
          html += '<div class="arena-name">' + escapeHtml(a.name || '—') + (isActive ? '' : ' <span class="badge-inactive">неактив.</span>') + (hasDraft ? ' <span class="badge-draft">черновик</span>' : '') + '</div>';
          html += '<div class="arena-meta">' + (addr || 'Адрес не указан') + (a.slug ? ' · ' + escapeHtml(a.slug) : '') + ' · ' + coordHint + '</div>';
          html += '</div>';
          html += '</div>';
          html += '<div class="arena-header-actions">';
          html += '<button type="button" class="icon-btn" data-role="ice-schedule" data-id="' + a.id + '" title="Расписание льда">⛸</button>';
          html += '<button type="button" class="icon-btn" data-role="' + (isActive ? 'deactivate' : 'activate') + '" data-id="' + a.id + '" title="' + (isActive ? 'Деактивировать' : 'Вернуть') + '">' + (isActive ? '⏸' : '▶') + '</button>';
          html += '<button type="button" class="icon-btn" data-role="save" data-id="' + a.id + '" title="Сохранить">💾</button>';
          html += '</div>';
          html += '</div>';
          html += '<div class="arena-body">';
          html += arenaProfileBodyHtml(a, { includePhotos: true, arenaId: a.id });
          html += '<div class="ice-week" data-arena-id="' + a.id + '" hidden></div>';
          html += mapLinksHtml(a, a.id);
          html += '<div class="arena-save-bar"><button type="button" class="btn-save-primary" data-role="save" data-id="' + a.id + '">Сохранить профиль</button></div>';
          html += '</div></div>';
        });
        card.innerHTML = html;

        card.querySelectorAll('.arena-header').forEach(function(hdr) {
          hdr.addEventListener('click', function(e) {
            if (e.target.closest('.icon-btn')) return;
            var row = hdr.closest('.arena-row');
            if (!row) return;
            var id = Number(row.getAttribute('data-id'));
            captureArenaDraftsFromDom();
            state.expandedArenaId = state.expandedArenaId === id ? -1 : id;
            renderArenas();
          });
        });
        bindGeocodeIn(card);
        bindScheduleModeIn(card);
        bindVisitIn(card);
        card.querySelectorAll('.icon-btn[data-role="save"], .btn-save-primary[data-role="save"]').forEach(function(btn) {
          btn.addEventListener('click', function(e) {
            e.stopPropagation();
            var id = Number(btn.getAttribute('data-id'));
            var row = btn.closest('.arena-row');
            if (!row) return;
            var payload = buildSavePayloadFromRow(row, id);
            sendJson('PATCH', '/admin/arenas/' + id, payload).then(function() {
              delete state.arenaDrafts[id];
              delete state.pendingGeo[id];
              showToast('Профиль арены сохранён');
              return fetchAndRenderArenas();
            }).catch(function(err) {
              showAlert(err.message || String(err));
            });
          });
        });
        card.querySelectorAll('.icon-btn[data-role="deactivate"], .icon-btn[data-role="activate"]').forEach(function(btn) {
          btn.addEventListener('click', function() {
            var id = Number(btn.getAttribute('data-id'));
            var isAct = btn.getAttribute('data-role') === 'activate';
            sendJson('PATCH', '/admin/arenas/' + id, { is_active: isAct })
              .then(function() { return loadArenas(); })
              .catch(function(err) { showAlert(err.message || String(err)); });
          });
        });
        card.querySelectorAll('[data-role="photo-file"]').forEach(function(input) {
          input.addEventListener('change', function() {
            var file = input.files && input.files[0];
            if (!file) return;
            var row = input.closest('.arena-row');
            var arenaId = Number(input.getAttribute('data-id'));
            var license = ((row && row.querySelector('[data-field="photo_license"]')) || {}).value || 'own';
            var source = ((row && row.querySelector('[data-field="photo_source"]')) || {}).value || '';
            var fd = new FormData();
            fd.append('file', file);
            fd.append('license', license);
            if (license !== 'own') {
              var trimmed = source.trim();
              if (!trimmed) {
                showAlert('Для лицензии не «своё» укажите URL источника или атрибуцию');
                input.value = '';
                return;
              }
              if (/^https?:\/\//i.test(trimmed)) fd.append('source_url', trimmed);
              else fd.append('attribution', trimmed);
            } else if (source.trim()) {
              fd.append('attribution', source.trim());
            }
            sendForm('/admin/arenas/' + arenaId + '/photos', fd)
              .then(function() { showToast('Фото загружено'); return loadArenas(); })
              .catch(function(err) { showAlert(err.message || String(err)); })
              .then(function() { input.value = ''; });
          });
        });
        function galleryIds(galleryEl) {
          return Array.prototype.map.call(galleryEl.querySelectorAll('.arena-photo[data-media-id]'), function(el) {
            return Number(el.getAttribute('data-media-id'));
          });
        }
        card.querySelectorAll('[data-role="photo-up"], [data-role="photo-down"]').forEach(function(btn) {
          btn.addEventListener('click', function() {
            var gallery = btn.closest('.arena-gallery');
            var photo = btn.closest('.arena-photo');
            if (!gallery || !photo) return;
            var ids = galleryIds(gallery);
            var id = Number(photo.getAttribute('data-media-id'));
            var idx = ids.indexOf(id);
            var swap = btn.getAttribute('data-role') === 'photo-up' ? idx - 1 : idx + 1;
            if (idx < 0 || swap < 0 || swap >= ids.length) return;
            var tmp = ids[idx];
            ids[idx] = ids[swap];
            ids[swap] = tmp;
            sendJson('PATCH', '/admin/arenas/' + btn.getAttribute('data-id') + '/photos', { ids: ids })
              .then(function() { return loadArenas(); })
              .catch(function(err) { showAlert(err.message || String(err)); });
          });
        });
        card.querySelectorAll('[data-role="photo-del"]').forEach(function(btn) {
          btn.addEventListener('click', function() {
            var arenaId = btn.getAttribute('data-id');
            var mediaId = btn.getAttribute('data-media-id');
            sendJson('DELETE', '/admin/arenas/' + arenaId + '/photos/' + mediaId, {})
              .then(function() { return loadArenas(); })
              .catch(function(err) { showAlert(err.message || String(err)); });
          });
        });
        card.querySelectorAll('.icon-btn[data-role="ice-schedule"]').forEach(function(btn) {
          btn.addEventListener('click', function(e) {
            e.stopPropagation();
            var arenaId = Number(btn.getAttribute('data-id'));
            var q = '?city_id=' + encodeURIComponent(state.selectedCityId || '') +
              '&arena_id=' + encodeURIComponent(arenaId);
            window.location.href = '/webapp/admin-ice-schedule' + q;
          });
        });
      }

      function buildCitiesPath() {
        var path = '/admin/cities';
        var parts = [];
        if (state.cityQ) parts.push('q=' + encodeURIComponent(state.cityQ));
        if (state.cityIncludeInactive) parts.push('include_inactive=true');
        if (parts.length) path += '?' + parts.join('&');
        return path;
      }

      function buildArenasPath() {
        var path = '/admin/arenas?city_id=' + encodeURIComponent(state.selectedCityId);
        if (state.arenaQ) path += '&q=' + encodeURIComponent(state.arenaQ);
        if (state.arenaIncludeInactive) path += '&include_inactive=true';
        return path;
      }

      function loadCities(keepSelection) {
        return getJson(buildCitiesPath()).then(function(data) {
          state.cities = (data && data.items) || [];
          if (!keepSelection || !state.cities.some(function(c) { return c.id === state.selectedCityId; })) {
            state.selectedCityId = state.cities.length ? state.cities[0].id : null;
          }
          renderCities();
          return loadArenas();
        }).catch(function(err) {
          showAlert(err.message || 'Не удалось загрузить города');
        });
      }

      function fetchAndRenderArenas() {
        if (!state.selectedCityId) {
          state.arenas = [];
          renderArenas();
          return Promise.resolve();
        }
        return getJson(buildArenasPath())
          .then(function(data) {
            state.arenas = (data && data.items) || [];
            state.venueTypes = (data && data.venue_types) || state.venueTypes || [];
            if (state.expandedArenaId === null && state.arenas.length) {
              state.expandedArenaId = state.arenas[0].id;
            } else if (
              state.expandedArenaId > 0 &&
              !state.arenas.some(function(a) { return a.id === state.expandedArenaId; })
            ) {
              state.expandedArenaId = state.arenas.length ? state.arenas[0].id : null;
            }
            renderArenas();
          }).catch(function(err) {
            showAlert(err.message || 'Не удалось загрузить арены');
          });
      }

      function loadArenas() {
        captureArenaDraftsFromDom();
        return fetchAndRenderArenas();
      }

      function showAddCityForm(show) {
        var form = document.getElementById('addCityForm');
        if (!form) return;
        form.classList.toggle('visible', !!show);
        if (show) {
          document.getElementById('editCityForm').classList.remove('visible');
          document.getElementById('newCityName').value = '';
          document.getElementById('newCityName').focus();
        }
      }
      function showEditCityForm(show, cityId, currentName) {
        var form = document.getElementById('editCityForm');
        if (!form) return;
        form.classList.toggle('visible', !!show);
        if (show) {
          document.getElementById('addCityForm').classList.remove('visible');
          form._editCityId = cityId;
          var inp = document.getElementById('editCityName');
          inp.value = currentName || '';
          inp.focus();
        } else {
          form._editCityId = null;
        }
      }
      document.getElementById('btnAddCity').addEventListener('click', function() {
        showAddCityForm(true);
      });
      document.getElementById('btnCityCancel').addEventListener('click', function() { showAddCityForm(false); });
      document.getElementById('btnCityEditCancel').addEventListener('click', function() { showEditCityForm(false); });
      document.getElementById('btnCityEditSubmit').addEventListener('click', function() {
        var form = document.getElementById('editCityForm');
        var id = form && form._editCityId;
        if (!id) return;
        var name = (document.getElementById('editCityName').value || '').trim();
        if (!name) {
          showAlert('Введите название города');
          return;
        }
        showEditCityForm(false);
        sendJson('PATCH', '/admin/cities/' + id, { name: name })
          .then(function() {
            showToast('Город сохранён');
            return loadCities(true);
          })
          .catch(function(err) { showAlert(err.message || String(err)); });
      });
      document.getElementById('btnCitySubmit').addEventListener('click', function() {
        var name = (document.getElementById('newCityName').value || '').trim();
        if (!name) {
          showAlert('Введите название города');
          return;
        }
        showAddCityForm(false);
        sendJson('POST', '/admin/cities', { name: name, sort_order: 0 })
          .then(function() {
            showToast('Город добавлен');
            return loadCities(true);
          })
          .catch(function(err) { showAlert(err.message || String(err)); });
      });

      function showAddArenaForm(show) {
        var form = document.getElementById('addArenaForm');
        if (!form) return;
        form.classList.toggle('visible', !!show);
        if (show) {
          delete state.pendingGeo[NEW_ARENA_KEY];
          renderAddArenaFormBody();
          var nameEl = form.querySelector('[data-field="name"]');
          if (nameEl) nameEl.focus();
        }
      }
      document.getElementById('btnAddArena').addEventListener('click', function() {
        if (!state.selectedCityId) return;
        showAddArenaForm(true);
      });
      document.getElementById('btnArenaCancel').addEventListener('click', function() {
        showAddArenaForm(false);
      });
      document.getElementById('btnArenaSubmit').addEventListener('click', function() {
        var row = document.querySelector('#addArenaForm .arena-row--new');
        if (!row) return;
        var draft = collectDraftFromRow(row);
        if (!draft.name) {
          showAlert('Введите название арены');
          return;
        }
        var geo = state.pendingGeo[NEW_ARENA_KEY];
        var postBody = {
          city_id: state.selectedCityId,
          name: draft.name,
          address: draft.address || undefined,
          venue_type: draft.venue_type || 'ice'
        };
        if (draft.sort_order != null) postBody.sort_order = draft.sort_order;
        if (geo && geo.latitude != null && geo.longitude != null) {
          postBody.latitude = geo.latitude;
          postBody.longitude = geo.longitude;
        }
        var venueType = postBody.venue_type;
        showAddArenaForm(false);
        sendJson('POST', '/admin/arenas', postBody).then(function(res) {
          var id = res.id;
          var payload = buildSavePayloadFromRow(row, id);
          if (geo && geo.latitude != null && geo.longitude != null) {
            payload.latitude = geo.latitude;
            payload.longitude = geo.longitude;
          }
          return sendJson('PATCH', '/admin/arenas/' + id, payload).then(function() { return id; });
        }).then(function(newId) {
          delete state.pendingGeo[NEW_ARENA_KEY];
          state.expandedArenaId = newId;
          showToast(venueType === 'shop' ? 'Магазин добавлен' : 'Арена добавлена');
          return loadCities(true);
        }).catch(function(err) {
          showAlert(err.message || String(err));
        });
      });

      var searchDebounce;
      document.getElementById('citySearch').addEventListener('input', function() {
        state.cityQ = this.value.trim();
        clearTimeout(searchDebounce);
        searchDebounce = setTimeout(function() { loadCities(true); }, 300);
      });
      document.getElementById('cityShowInactive').addEventListener('change', function() {
        state.cityIncludeInactive = this.checked;
        loadCities(true);
      });
      document.getElementById('arenaSearch').addEventListener('input', function() {
        state.arenaQ = this.value.trim();
        clearTimeout(searchDebounce);
        searchDebounce = setTimeout(function() { loadArenas(); }, 300);
      });
      document.getElementById('arenaShowInactive').addEventListener('change', function() {
        state.arenaIncludeInactive = this.checked;
        loadArenas();
      });

      loadCities(false);
    })();
