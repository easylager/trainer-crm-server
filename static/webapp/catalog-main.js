    (function() {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { 
        tg.ready(); 
        tg.expand(); 
        if (typeof window.__applyCatalogTheme === 'function') {
          window.__applyCatalogTheme();
        }
        function syncTelegramChromeColors() {
          try {
            var darkUi = tg.colorScheme === 'dark' ||
              (tg.colorScheme !== 'light' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
            var bgHex = darkUi ? '#1c1c1c' : '#fffbec';
            if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
            if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
            if (typeof tg.setBottomBarColor === 'function') tg.setBottomBarColor(bgHex);
          } catch (e) { /* older clients */ }
        }
        syncTelegramChromeColors();
        if (tg.onEvent) {
          tg.onEvent('themeChanged', function () {
            if (typeof window.__applyCatalogTheme === 'function') {
              window.__applyCatalogTheme();
            }
            syncTelegramChromeColors();
          });
        }
      }

      var state = {
        cityId: null,
        cityName: '',
        serviceId: null,
        serviceName: '',
        arenaId: null,
        arenaName: 'Любая',
        trainerId: null,
        trainerName: '',
        trainers: [],
        total: 0,
        offset: 0,
        limit: 10,
        selectedTrainer: null,
        /** When trainer has multiple price tiers for filtered service — required by POST /client/booking */
        catalogBookingPriceVariantId: null,
        slotsForTrainer: [],
        selectedSlot: null,
        returnToSummary: false,
        requestForTrainer: null,
        requestFormOpenedFrom: null,
        activeTab: 'catalog',
        openedFromMyTrainerTab: false,
        /** trainers | groups — список после выбора города/услуги/арены */
        catalogMode: 'trainers',
        /** From GET /client/session — clients.phone for prefill in booking form */
        clientPhone: '',
        /** When true, booking/request forms must collect first name (last optional). */
        needsProfileName: true,
        clientFirstName: '',
        clientLastName: '',
        // Time-based filters
        filters: {
          days: [], // [1,2,3,4,5,6,0] for Mon-Sun
          timeSlots: [] // ['06:00-09:00', '09:00-12:00', etc.]
        }
      };

      function primaryVenueLabel(t) {
        if (!t) return '';
        if (t.primary_arena_name && String(t.primary_arena_name).trim()) return String(t.primary_arena_name).trim();
        var ids = t.arena_ids || [];
        var names = t.arena_names || [];
        var idx = ids.indexOf(t.primary_arena_id);
        if (idx >= 0 && names[idx]) return names[idx];
        return '';
      }
      function isNonPrimaryArenaFilter() {
        if (state.arenaId == null) return false;
        var t = state.selectedTrainer;
        if (!t || t.primary_arena_id == null) return false;
        return state.arenaId !== t.primary_arena_id;
      }

      /** Switch catalog filter to trainer's primary arena (online booking). */
      function applyTrainerPrimaryArenaToCatalogFilter(t) {
        if (!t || t.primary_arena_id == null) return false;
        state.arenaId = t.primary_arena_id;
        var label = primaryVenueLabel(t);
        state.arenaName = label || 'Основная площадка';
        return true;
      }
      function updateBookingVenueHint() {
        var el = document.getElementById('bookingVenueHint');
        if (!el) return;
        var label = primaryVenueLabel(state.selectedTrainer);
        var nonPrimary = isNonPrimaryArenaFilter();
        el.className = 'booking-venue-hint' + (nonPrimary ? ' booking-venue-hint--alert' : '');
        if (!label && !nonPrimary) {
          el.style.display = 'none';
          el.textContent = '';
          return;
        }
        el.style.display = 'block';
        if (nonPrimary && label) {
          var filterName = (state.arenaName && state.arenaName !== 'Любая') ? state.arenaName : 'другой арене';
          el.innerHTML = 'Вы смотрите тренера по фильтру «' + escapeHtml(filterName) + '». <strong>Онлайн-запись оформляется на основную площадку: ' + escapeHtml(label) + '.</strong> Чтобы заниматься на площадке из фильтра — оставьте заявку: тренер согласует место и запишет вас сам.';
        } else if (label) {
          el.textContent = 'Площадка: ' + label;
        } else {
          el.textContent = '';
          el.style.display = 'none';
        }
      }

      var CATALOG_PRICE_TIER_LABELS = {
        child: 'Детский',
        adult: 'Взрослый',
        two_children: '2 ребенка',
        two_adults: '2 взрослых',
        adult_and_child: 'Взрослый + ребенок',
      };
      function catalogTierLabelRu(tier) {
        var k = (tier.tier_kind || '').toLowerCase();
        return CATALOG_PRICE_TIER_LABELS[k] || tier.label || 'Тариф';
      }

      function getTiersForCatalogBooking() {
        var t = state.selectedTrainer;
        if (!t || !t.services || state.serviceId == null) return [];
        var sid = Number(state.serviceId);
        var svc = null;
        var i;
        for (i = 0; i < t.services.length; i++) {
          if (Number(t.services[i].service_id) === sid) {
            svc = t.services[i];
            break;
          }
        }
        if (!svc || !svc.price_tiers) return [];
        return svc.price_tiers;
      }

      /** Услуга из фильтра + выбор тарифа при нескольких ценах (строгий режим API). Групповые слоты — без выбора тира. */
      function updateBookingFormServiceAndTiers() {
        var svcEl = document.getElementById('bookingFormServiceLine');
        var block = document.getElementById('bookingPriceTierBlockCatalog');
        var host = document.getElementById('bookingPriceTierRadiosCatalog');
        state.catalogBookingPriceVariantId = null;
        if (svcEl) {
          var nm = (state.serviceName || '').trim();
          if (nm) {
            svcEl.style.display = 'block';
            svcEl.textContent = 'Услуга: ' + nm;
          } else {
            svcEl.style.display = 'none';
            svcEl.textContent = '';
          }
        }
        if (!block || !host) return;
        host.innerHTML = '';
        var slot = state.selectedSlot;
        var capRaw = slot && slot.capacity != null ? parseInt(slot.capacity, 10) : 1;
        var cap = isNaN(capRaw) ? 1 : capRaw;
        if (cap > 1) {
          block.style.display = 'none';
          return;
        }
        var tiers = getTiersForCatalogBooking();
        if (tiers.length <= 1) {
          block.style.display = 'none';
          if (tiers.length === 1 && tiers[0].id != null) {
            state.catalogBookingPriceVariantId = parseInt(String(tiers[0].id), 10);
          }
          return;
        }
        block.style.display = 'block';
        tiers.forEach(function(tier) {
          var lab = document.createElement('label');
          var inp = document.createElement('input');
          inp.type = 'radio';
          inp.name = 'catalogPriceTierChoice';
          inp.value = String(tier.id);
          var pb = tier.price_byn;
          var priceStr = (pb === Math.floor(pb) ? pb : Number(pb).toFixed(2)) + ' BYN';
          lab.appendChild(inp);
          var tierTxt = document.createElement('span');
          tierTxt.className = 'tier-radio-text';
          tierTxt.textContent = catalogTierLabelRu(tier) + ' — ' + priceStr;
          lab.appendChild(tierTxt);
          inp.addEventListener('change', function() {
            state.catalogBookingPriceVariantId = parseInt(inp.value, 10);
          });
          host.appendChild(lab);
        });
        var first = host.querySelector('input');
        if (first) {
          first.checked = true;
          state.catalogBookingPriceVariantId = parseInt(first.value, 10);
        }
      }

      var prefetch = {
        firstPageKey: null,
        firstPageData: null
      };
      /** Monotonic id: ignore stale list responses after city/service/mode/filter changes. */
      var catalogListReqId = 0;
      /** One shared in-flight Promise per first-page key so prefetch and loadCatalogList never duplicate GET.
       *  Manual smoke: open summary with city+service — Network should show one GET /api/public/trainers (or training-groups) for page 1 when prefetch races loadCatalogList. */
      var catalogFirstPageInflight = {};
      function fetchCatalogFirstPage(path, params, key) {
        if (catalogFirstPageInflight[key]) {
          return catalogFirstPageInflight[key];
        }
        var p = getJson(path, params).then(function(data) {
          return data;
        }).finally(function() {
          delete catalogFirstPageInflight[key];
        });
        catalogFirstPageInflight[key] = p;
        return p;
      }
      /** Skip optional second-page warmup on save-data / 2G — cheap heuristic. */
      function shouldSkipCatalogConnectionHeavyPrefetch() {
        var c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
        if (c && c.saveData) return true;
        if (c && (c.effectiveType === 'slow-2g' || c.effectiveType === '2g')) return true;
        return false;
      }
      /** Defer non-critical catalog fetches until the browser is idle (fallback: timeout). */
      function scheduleCatalogIdlePrefetch(run, timeoutMs) {
        var t = timeoutMs != null ? timeoutMs : 2500;
        var ric = window.requestIdleCallback;
        if (typeof ric === 'function') {
          return ric(function() { run(); }, { timeout: t });
        }
        return setTimeout(function() { run(); }, t > 0 ? t : 2000);
      }
      // First-page list cache: TTL=0 disables sessionStorage; when TTL>0, clear keys on filter/mode/booking via clearCatalogSessionStorageCache().
      var CATALOG_CACHE_PREFIX = 'tcb_catalog_trainers_v1_';
      var CATALOG_CACHE_TTL_MS = 0;
      function clearCatalogSessionStorageCache() {
        if (!CATALOG_CACHE_TTL_MS) return;
        try {
          var rm = [];
          var i;
          for (i = 0; i < sessionStorage.length; i++) {
            var k = sessionStorage.key(i);
            if (k && k.indexOf(CATALOG_CACHE_PREFIX) === 0) rm.push(k);
          }
          for (i = 0; i < rm.length; i++) {
            sessionStorage.removeItem(rm[i]);
          }
        } catch (e) { /* ignore */ }
      }
      function readCatalogFirstPageFromStorage(listKey) {
        if (!CATALOG_CACHE_TTL_MS) return null;
        try {
          var raw = sessionStorage.getItem(CATALOG_CACHE_PREFIX + listKey);
          if (!raw) return null;
          var parsed = JSON.parse(raw);
          if (!parsed || !parsed.ts || !parsed.data) return null;
          if (Date.now() - parsed.ts > CATALOG_CACHE_TTL_MS) {
            sessionStorage.removeItem(CATALOG_CACHE_PREFIX + listKey);
            return null;
          }
          return parsed.data;
        } catch (e) {
          return null;
        }
      }
      function writeCatalogFirstPageToStorage(listKey, data) {
        if (!CATALOG_CACHE_TTL_MS) return;
        try {
          sessionStorage.setItem(CATALOG_CACHE_PREFIX + listKey, JSON.stringify({ ts: Date.now(), data: data }));
        } catch (e) {
          // QuotaExceeded: ignore; in-memory prefetch still helps.
        }
      }

      function closeApp() {
        if (tg) tg.close(); else window.close();
      }

      function canBrowserGoBack() {
        try {
          if (window.navigation && typeof window.navigation.canGoBack === 'function') {
            return window.navigation.canGoBack();
          }
        } catch (e) { /* older WebViews */ }
        return window.history && window.history.length > 1;
      }

      /** Header #btnBack: in-app stack for booking/slot/request; otherwise browser back. */
      function syncCatalogHeaderBack() {
        var btn = document.getElementById('btnBack');
        if (!btn) return;
        var active = document.querySelector('[data-screen].active');
        var sid = active ? active.id : '';
        if (sid === 'screenBookingForm' || sid === 'screenSlotPick') {
          btn.hidden = false;
          btn.onclick = function() { showScreen('screenTrainerDetail'); };
          return;
        }
        if (sid === 'screenRequestForm') {
          btn.hidden = false;
          btn.onclick = function() {
            if (state.requestFormOpenedFrom === 'trainerDetail') {
              showScreen('screenTrainerDetail');
            } else {
              showScreen('screenTrainers');
            }
          };
          return;
        }
        if (sid === 'screenTrainers') {
          btn.hidden = false;
          btn.onclick = function() {
            if (state.returnToSummary) {
              goBackToSummary();
            } else {
              showScreen('screenArena');
            }
          };
          return;
        }
        btn.hidden = !canBrowserGoBack();
        btn.onclick = function() { window.history.back(); };
      }

      function showScreen(id) {
        document.querySelectorAll('[data-screen]').forEach(function(el) { el.classList.remove('active'); });
        var el = document.getElementById(id);
        if (el) el.classList.add('active');
        if (id === 'screenTrainerDetail') {
          document.querySelectorAll('#catalogTabsOnDetail .tab-btn').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.tab === 'my_trainer');
          });
        }
        if (id === 'screenSummary') {
          renderSummary();
          switchTab(state.activeTab);
        }
        syncCatalogHeaderBack();
      }

      window.addEventListener('popstate', syncCatalogHeaderBack);

      function photoUrl(fileKey) {
        if (!fileKey) return null;
        return '/api/public/photos/' + encodeURIComponent(fileKey);
      }
      function photoSrcList(photo) {
        if (!photo) return null;
        if (photo.list_url) return photo.list_url;
        if (photo.url) return photo.url;
        var fk = photo.file_key_list || photo.file_key;
        return fk ? photoUrl(fk) : null;
      }
      function photoSrcDetail(photo) {
        if (!photo) return null;
        if (photo.url) return photo.url;
        if (photo.list_url) return photo.list_url;
        return photo.file_key ? photoUrl(photo.file_key) : null;
      }
      function warmupImageUrls(urls) {
        // Warm up browser cache for first visible cards.
        (urls || []).forEach(function(src) {
          if (!src) return;
          var img = new Image();
          img.decoding = 'async';
          img.src = src;
        });
      }
      /** Prefetch list + detail URLs for catalog rows (detail may differ from list thumb). */
      function catalogItemFirstPhoto(item) {
        if (!item) return null;
        var p0 = item.photos && item.photos[0];
        if (p0) return p0;
        var tr = item.trainer;
        return tr && tr.photos && tr.photos[0] ? tr.photos[0] : null;
      }
      function warmupCatalogImagesFromItems(items, maxRows) {
        var n = maxRows != null ? maxRows : 16;
        var slice = (items || []).slice(0, n);
        warmupImageUrls(slice.map(function(t) {
          return photoSrcList(catalogItemFirstPhoto(t));
        }));
        warmupImageUrls(slice.map(function(t) {
          var p0 = catalogItemFirstPhoto(t);
          var a = photoSrcDetail(p0);
          var b = photoSrcList(p0);
          return a && b && a !== b ? a : null;
        }));
      }
      function photoProxyListFallback(photo) {
        if (!photo) return '';
        var fk = photo.file_key_list || photo.file_key;
        return fk ? photoUrl(fk) : '';
      }
      function photoProxyFullFallback(photo) {
        if (!photo || !photo.file_key) return '';
        return photoUrl(photo.file_key);
      }
      function bindTrainerDetailPhotoWrap() {
        var wrap = document.querySelector('#trainerDetailTop .trainer-detail-photo-wrap');
        if (!wrap) return;
        var ph = wrap.querySelector('.trainer-detail-photo-placeholder');
        function hidePh() { if (ph) ph.style.display = 'none'; }
        var single = wrap.querySelector('img.trainer-detail-photo-single');
        var base = wrap.querySelector('img.trainer-detail-photo-base');
        var full = wrap.querySelector('img.trainer-detail-photo-full');
        if (single) {
          single.onload = function() { single.classList.add('loaded'); hidePh(); };
          single.onerror = function() {
            var fb = single.dataset.fallback;
            if (fb) { single.onerror = null; single.src = fb; }
          };
          if (single.complete && single.naturalWidth) { single.classList.add('loaded'); hidePh(); }
          return;
        }
        if (base) {
          base.onload = function() { base.classList.add('loaded'); hidePh(); };
          base.onerror = function() {
            var fb = base.dataset.fallbackBase;
            if (fb) { base.onerror = null; base.src = fb; }
          };
          if (base.complete && base.naturalWidth) { base.classList.add('loaded'); hidePh(); }
        }
        if (full) {
          full.onload = function() { full.classList.add('loaded'); hidePh(); };
          full.onerror = function() {
            var fb = full.dataset.fallbackFull;
            if (fb) { full.onerror = null; full.src = fb; }
          };
          if (full.complete && full.naturalWidth) { full.classList.add('loaded'); hidePh(); }
        }
      }
      function makeTrainerListParams(offset) {
        var params = { limit: state.limit, offset: offset, city_id: state.cityId, service_id: state.serviceId, order_by: 'rating' };
        if (state.arenaId) params.arena_id = state.arenaId;
        var f = state.filters;
        if (f.days.length > 0) {
          params.filter_days = f.days.join(',');
        }
        if (f.timeSlots.length > 0) {
          params.filter_time_slots = f.timeSlots.join(',');
        }
        return params;
      }
      /** Каталог: чипы дней 0=Вс..6=Сб (как PG DOW для слотов) → правила групп 0=Пн..6=Вс */
      function mapCatalogChipDaysToGroupRuleDays(days) {
        return days.map(function(d) {
          var n = parseInt(d, 10);
          if (n === 0) return 6;
          return n - 1;
        });
      }
      function makeGroupListParams(offset) {
        var params = { limit: state.limit, offset: offset, city_id: state.cityId, service_id: state.serviceId };
        if (state.arenaId) params.arena_id = state.arenaId;
        var f = state.filters;
        if (f.days.length > 0) {
          params.filter_days = mapCatalogChipDaysToGroupRuleDays(f.days).join(',');
        }
        return params;
      }
      function makeFirstPageKey() {
        var f = state.filters;
        var dayPart = f.days.length ? f.days.slice().sort(function(a, b) { return a - b; }).join('-') : '';
        var timePart = f.timeSlots.length ? f.timeSlots.slice().sort().join('|') : '';
        var mode = state.catalogMode || 'trainers';
        return [mode, state.cityId || 0, state.serviceId || 0, state.arenaId || 0, state.limit || 10, dayPart, timePart].join(':');
      }

      function toggleFilterPanel() {
        var panel = document.getElementById('timeFilters');
        if (panel) panel.classList.toggle('expanded');
      }

      function updateFilterSummary() {
        var summary = [];
        var f = state.filters;
        
        if (f.days.length > 0 && f.days.length < 7) {
          var dayNames = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
          summary.push(f.days.map(d => dayNames[d]).join(', '));
        }
        if (f.timeSlots.length > 0) {
          var timeLabels = f.timeSlots.map(function(slot) {
            var parts = slot.split('-');
            return parts[0] + '-' + parts[1];
          });
          summary.push(timeLabels.join(', '));
        }

        var summaryEl = document.getElementById('filterSummary');
        var clearBtn = document.getElementById('clearFilters');
        
        if (summary.length === 0) {
          summaryEl.textContent =
            state.catalogMode === 'groups'
              ? 'Любые дни (серия группы)'
              : 'Все временные промежутки';
          if (clearBtn) clearBtn.style.display = 'none';
        } else {
          summaryEl.textContent =
            state.catalogMode === 'groups' && f.days.length > 0
              ? ('Серия в: ' + summary.join(' · '))
              : summary.join(' · ');
          if (clearBtn) clearBtn.style.display = 'inline';
        }
      }

      function clearAllFilters() {
        state.filters = {
          days: [],
          timeSlots: []
        };
        
        // Clear UI
        document.querySelectorAll('.filter-chip.selected').forEach(chip => {
          chip.classList.remove('selected');
        });
        
        updateFilterSummary();
        applyFiltersAndReload();
      }


      function applyFiltersAndReload() {
        state.offset = 0;
        prefetch.firstPageKey = null;
        prefetch.firstPageData = null;
        clearCatalogSessionStorageCache();
        loadCatalogList();
      }

      function updateCatalogModeUi() {
        var isGroups = state.catalogMode === 'groups';
        var titleEl = document.getElementById('screenTrainersTitle');
        if (titleEl) titleEl.textContent = isGroups ? 'Группы с набором' : 'Тренеры';
        var ts = document.getElementById('timeSlotFiltersSection');
        if (ts) ts.style.display = isGroups ? 'none' : '';
        document.querySelectorAll('#catalogListMode .catalog-mode-btn').forEach(function(btn) {
          var on = btn.getAttribute('data-mode') === state.catalogMode;
          btn.classList.toggle('active', on);
          btn.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        var ft = document.getElementById('timeFilters');
        if (ft && isGroups) {
          ft.classList.add('expanded');
        }
        updateFilterSummary();
      }

      function loadCatalogList(opts) {
        updateCatalogModeUi();
        if (state.catalogMode === 'groups') {
          loadTrainingGroupsCatalog(opts);
        } else {
          loadTrainers(opts);
        }
      }

      function initCatalogModeToggle() {
        var row = document.getElementById('catalogListMode');
        if (!row || row.getAttribute('data-bound') === '1') return;
        row.setAttribute('data-bound', '1');
        row.querySelectorAll('.catalog-mode-btn').forEach(function(btn) {
          btn.addEventListener('click', function() {
            var mode = btn.getAttribute('data-mode');
            if (!mode || mode === state.catalogMode) return;
            state.catalogMode = mode;
            if (mode === 'groups') {
              state.filters.timeSlots = [];
              document.querySelectorAll('#timeSlotFilters .filter-chip').forEach(function(chip) {
                chip.classList.remove('selected');
              });
              updateFilterSummary();
            }
            state.offset = 0;
            prefetch.firstPageKey = null;
            prefetch.firstPageData = null;
            clearCatalogSessionStorageCache();
            loadCatalogList();
          });
        });
      }

      var filterHandlersInitialized = false;
      function initializeFilterHandlers() {
        if (filterHandlersInitialized) return;
        filterHandlersInitialized = true;
        
        // Day filters
        document.querySelectorAll('#dayFilters .filter-chip').forEach(function(chip) {
          chip.addEventListener('click', function() {
            var day = parseInt(chip.dataset.day);
            var index = state.filters.days.indexOf(day);
            if (index === -1) {
              state.filters.days.push(day);
              chip.classList.add('selected');
            } else {
              state.filters.days.splice(index, 1);
              chip.classList.remove('selected');
            }
            updateFilterSummary();
            applyFiltersAndReload();
          });
        });

        // Time slot filters
        document.querySelectorAll('#timeSlotFilters .filter-chip').forEach(function(chip) {
          chip.addEventListener('click', function() {
            var timeSlot = chip.dataset.time;
            var index = state.filters.timeSlots.indexOf(timeSlot);
            if (index === -1) {
              state.filters.timeSlots.push(timeSlot);
              chip.classList.add('selected');
            } else {
              state.filters.timeSlots.splice(index, 1);
              chip.classList.remove('selected');
            }
            updateFilterSummary();
            applyFiltersAndReload();
          });
        });

        // Clear filters button
        var clearBtn = document.getElementById('clearFilters');
        if (clearBtn) {
          clearBtn.addEventListener('click', clearAllFilters);
        }
      }

      /** Russian pluralization for trainer count (найден N тренер/тренера/тренеров). */
      function formatTrainerCountMessage(n) {
        n = n | 0;
        var mod10 = n % 10;
        var mod100 = n % 100;
        if (mod10 === 1 && mod100 !== 11) {
          return 'Найден ' + n + ' тренер';
        }
        if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
          return 'Найдено ' + n + ' тренера';
        }
        return 'Найдено ' + n + ' тренеров';
      }

      /** Склонение числительного с «год» (1 год, 2 года, 5 лет, 11 лет, 32 года). */
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

      /** Строка для списка: «32 года опыта». */
      function formatExperienceCatalogLine(years) {
        if (years == null || !isFinite(Number(years))) return null;
        var y = Number(years);
        return y + ' ' + ruYearsWord(y) + ' опыта';
      }

      function formatGroupCountMessage(n) {
        n = n | 0;
        var mod10 = n % 10;
        var mod100 = n % 100;
        if (mod10 === 1 && mod100 !== 11) {
          return 'Найдена ' + n + ' группа';
        }
        if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
          return 'Найдено ' + n + ' группы';
        }
        return 'Найдено ' + n + ' групп';
      }

      function updateResultsCount(count) {
        var resultsEl = document.getElementById('resultsCount');
        if (!resultsEl) return;
        if (state.catalogMode === 'groups') {
          resultsEl.textContent = formatGroupCountMessage(count);
        } else {
          resultsEl.textContent = formatTrainerCountMessage(count);
        }
      }
      function prefetchFirstPageIfNeeded() {
        if (!state.cityId || !state.serviceId) return;
        var key = makeFirstPageKey();
        if (prefetch.firstPageKey === key && prefetch.firstPageData) return;
        var cached = readCatalogFirstPageFromStorage(key);
        if (cached) {
          prefetch.firstPageKey = key;
          prefetch.firstPageData = cached;
          warmupCatalogImagesFromItems(cached.items || [], 16);
          return;
        }
        var path = state.catalogMode === 'groups' ? '/training-groups' : '/trainers';
        var params = state.catalogMode === 'groups' ? makeGroupListParams(0) : makeTrainerListParams(0);
        fetchCatalogFirstPage(path, params, key).then(function(data) {
          if (makeFirstPageKey() !== key) return;
          prefetch.firstPageKey = key;
          prefetch.firstPageData = data;
          writeCatalogFirstPageToStorage(key, data);
          var items = data && data.items ? data.items : [];
          warmupCatalogImagesFromItems(items, 16);
        }).catch(function() {
          // ignore prefetch failures: must never block UX
        });
      }

      function trainerName(t) {
        var p = t && t.profile;
        if (!p) return 'Тренер';
        var n = ((p.first_name || '') + ' ' + (p.last_name || '')).trim();
        return n || 'Тренер';
      }

      function educationTypeHintLabel(typeKey) {
        var key = (typeKey || '').trim();
        if (key === 'formal_education') return 'Вуз / колледж / ССО';
        if (key === 'course_or_certificate') return 'Курсы / сертификат';
        return '';
      }

      function buildCatalogEducationYearLine(edu) {
        if (!edu) return '';
        if (edu.is_in_progress) return 'в процессе';
        var sy = edu.start_year;
        var ey = edu.end_year;
        if (sy != null && ey != null) return sy + '–' + ey;
        if (ey != null) return String(ey);
        if (sy != null) return 'с ' + sy;
        return '';
      }

      function normalizeCatalogEducationDocumentPhotos(edu) {
        var rows = edu && Array.isArray(edu.document_photos) ? edu.document_photos : [];
        var out = [];
        var seen = {};
        rows.forEach(function(item) {
          if (!item || typeof item !== 'object') return;
          var fk = (item.file_key || '').toString().trim();
          var fkl = (item.file_key_list || '').toString().trim();
          if (!fk || seen[fk]) return;
          seen[fk] = true;
          out.push({ file_key: fk, file_key_list: fkl ? fkl : null });
        });
        return out;
      }

      /** Short education one-liner for list cards. */
      function formatCatalogEducationEntry(edu) {
        if (!edu) return '';
        var inst = (edu.institution_name || '').trim();
        var prog = (edu.program_or_title || '').trim();
        var city = (edu.city || '').trim();
        var country = (edu.country || '').trim();
        var place = [city, country].filter(Boolean).join(', ');
        var head = inst || prog || educationTypeHintLabel(edu.education_type);
        var line = head;
        if (inst && prog && inst !== prog) line = inst + ' — ' + prog;
        var y = buildCatalogEducationYearLine(edu);
        if (line && y) line += ' (' + y + ')';
        if (!line && place) line = place;
        else if (line && place && line.indexOf(place) === -1) line += ' · ' + place;
        return (line || '').trim();
      }

      function buildCatalogEducationItemHtml(edu) {
        if (!edu) return '';
        var summary = formatCatalogEducationEntry(edu) || 'Запись об образовании';
        var degree = (edu.degree_level || '').trim();
        var city = (edu.city || '').trim();
        var country = (edu.country || '').trim();
        var place = [city, country].filter(Boolean).join(', ');
        var years = buildCatalogEducationYearLine(edu);
        var typeHint = educationTypeHintLabel(edu.education_type);
        var docs = normalizeCatalogEducationDocumentPhotos(edu);

        var summaryMetaParts = [];
        if (years) summaryMetaParts.push(years);
        if (place) summaryMetaParts.push(place);
        var summaryMeta = summaryMetaParts.join(' · ');

        var body = '';
        if (typeHint) {
          body += '<div class="trainer-detail-education-body-line"><b>Тип:</b> ' + escapeHtml(typeHint) + '</div>';
        }
        if (degree) {
          body += '<div class="trainer-detail-education-body-line"><b>Квалификация:</b> ' + escapeHtml(degree) + '</div>';
        }
        if (years) {
          body += '<div class="trainer-detail-education-body-line"><b>Период:</b> ' + escapeHtml(years) + '</div>';
        }
        if (place) {
          body += '<div class="trainer-detail-education-body-line"><b>Город:</b> ' + escapeHtml(place) + '</div>';
        }
        if (docs.length) {
          var docsHtml = docs.slice(0, 4).map(function(doc, idx) {
            var imgSrc = photoUrl(doc.file_key_list || doc.file_key);
            var href = photoUrl(doc.file_key);
            return (
              '<a class="trainer-detail-education-doc" href="' + href + '" target="_blank" rel="noopener noreferrer" aria-label="Документ #' + (idx + 1) + '">' +
                '<img src="' + imgSrc + '" alt="Документ #' + (idx + 1) + '" loading="lazy" decoding="async">' +
              '</a>'
            );
          }).join('');
          if (docs.length > 4) {
            docsHtml += '<span class="trainer-detail-education-doc-more">+' + (docs.length - 4) + '</span>';
          }
          body += '<div class="trainer-detail-education-docs">' + docsHtml + '</div>';
        }
        if (!body) {
          body = '<div class="trainer-detail-education-body-line">Без дополнительных деталей.</div>';
        }

        return (
          '<details class="trainer-detail-education-item">' +
            '<summary>' +
              '<div class="trainer-detail-education-summary-main">' +
                '<div class="trainer-detail-education-summary-title">' + escapeHtml(summary) + '</div>' +
                (summaryMeta ? '<div class="trainer-detail-education-summary-meta">' + escapeHtml(summaryMeta) + '</div>' : '') +
              '</div>' +
              '<div class="trainer-detail-education-summary-right">' +
                (docs.length ? '<span class="trainer-detail-education-badge">' + docs.length + ' фото</span>' : '') +
                '<span class="trainer-detail-education-chevron">▾</span>' +
              '</div>' +
            '</summary>' +
            '<div class="trainer-detail-education-body">' + body + '</div>' +
          '</details>'
        );
      }

      /** Анкетное «Образование» — короткие категории из API (не дублируем под блоком записей). */
      function isProfileEducationCategoryOnly(s) {
        if (!s || typeof s !== 'string') return false;
        var t = s.trim();
        var cats = [
          'Среднее специальное', 'Высшее профильное', 'Высшее непрофильное',
          'Курсы и сертификация', 'Ученая степень', 'Другое'
        ];
        return cats.indexOf(t) >= 0;
      }

      function openTrainerDetailFromTrainerObject(t, prefetchPhotos) {
        if (!t || !t.id) return;
        state.trainerId = t.id;
        state.trainerName = trainerName(t);
        persistTrainerSelection(t.id);
        if (prefetchPhotos) {
          var detailPhoto = t.photos && t.photos[0];
          var pl = photoSrcList(detailPhoto);
          var pf = photoSrcDetail(detailPhoto);
          if (pl) { var iml = new Image(); iml.decoding = 'async'; iml.src = pl; }
          if (pf && pf !== pl) { var imf = new Image(); imf.decoding = 'async'; imf.fetchPriority = 'high'; imf.src = pf; }
        }
        loadTrainerById(t.id).then(function(full) {
          state.selectedTrainer = full || t;
          state.trainerName = trainerName(state.selectedTrainer);
          renderTrainerDetail();
          showScreen('screenTrainerDetail');
        }).catch(function() {
          state.selectedTrainer = t;
          renderTrainerDetail();
          showScreen('screenTrainerDetail');
        });
      }

      function getJson(path, params) {
        var q = '';
        if (params) {
          var parts = [];
          Object.keys(params).forEach(function(k) {
            var v = params[k];
            if (v === undefined || v === null) return;
            parts.push(k + '=' + encodeURIComponent(v));
          });
          if (parts.length) q = '?' + parts.join('&');
        }
        return fetch('/api/public' + path + q, { cache: 'no-store' }).then(function(r) { return r.json(); });
      }
      function loadTrainerById(trainerId) {
        return fetch('/api/public/trainers/' + encodeURIComponent(trainerId), { cache: 'no-store' })
          .then(function(r) {
            if (r.status === 404) return null;
            if (!r.ok) throw new Error(r.statusText);
            return r.json();
          });
      }
      function switchTab(tab) {
        state.activeTab = tab;
        document.querySelectorAll('.catalog-tabs .tab-btn').forEach(function(btn) {
          btn.classList.toggle('active', btn.dataset.tab === tab);
        });
        document.getElementById('catalogTabPanel').classList.toggle('active', tab === 'catalog');
        document.getElementById('myTrainerTabPanel').classList.toggle('active', tab === 'my_trainer');
        document.getElementById('myTrainerLoading').style.display = 'none';
        if (tab === 'my_trainer') {
          if (state.trainerId && state.trainerName) {
            openMyTrainerCard();
            return;
          }
          document.getElementById('myTrainerEmpty').style.display = 'block';
          document.getElementById('myTrainerCardShort').style.display = 'none';
        }
      }
      function openMyTrainerCard() {
        if (!state.trainerId) return;
        document.getElementById('myTrainerLoading').style.display = 'block';
        document.getElementById('myTrainerCardShort').style.display = 'none';
        state.openedFromMyTrainerTab = true;
        loadTrainerById(state.trainerId).then(function(t) {
          document.getElementById('myTrainerLoading').style.display = 'none';
          if (!t) {
            state.trainerId = null;
            state.trainerName = '';
            document.getElementById('myTrainerCardShort').style.display = 'none';
            document.getElementById('myTrainerEmpty').style.display = 'block';
            return;
          }
          state.selectedTrainer = t;
          state.trainerName = trainerName(t);
          renderTrainerDetail();
          showScreen('screenTrainerDetail');
        }).catch(function() {
          document.getElementById('myTrainerLoading').style.display = 'none';
          document.getElementById('myTrainerCardShort').style.display = 'block';
        });
      }

      function getClientSession() {
        var initData = tg && tg.initData ? tg.initData : '';
        var headers = { 'Content-Type': 'application/json' };
        if (initData) headers['X-Telegram-Init-Data'] = initData;
        return fetch('/api/webapp/client/session', { headers: headers }).then(function(r) {
          if (!r.ok) throw new Error(r.statusText);
          return r.json();
        });
      }

      function applySessionToState(session) {
        if (session.city_id) { state.cityId = session.city_id; state.cityName = session.city_name || ''; }
        if (session.service_id) { state.serviceId = session.service_id; state.serviceName = session.service_name || ''; }
        if (session.arena_id != null) { state.arenaId = session.arena_id; state.arenaName = session.arena_name || 'Любая'; }
        else { state.arenaId = null; state.arenaName = 'Любая'; }
        if (session.trainer_id) { state.trainerId = session.trainer_id; state.trainerName = session.trainer_name || ''; }
        else { state.trainerId = null; state.trainerName = ''; }
        state.clientPhone =
          session.client_phone != null && session.client_phone !== undefined
            ? String(session.client_phone).trim()
            : '';
        state.needsProfileName = !!session.needs_profile_name;
        state.clientFirstName =
          session.client_first_name != null && session.client_first_name !== undefined
            ? String(session.client_first_name).trim()
            : '';
        state.clientLastName =
          session.client_last_name != null && session.client_last_name !== undefined
            ? String(session.client_last_name).trim()
            : '';
      }

      function updateBookingNameFieldsVisibility() {
        var block = document.getElementById('bookingNameBlockCatalog');
        if (!block) return;
        var show = !!state.needsProfileName;
        block.style.display = show ? 'block' : 'none';
        if (show) {
          var f = document.getElementById('bookingFirstName');
          var l = document.getElementById('bookingLastName');
          if (f) f.value = state.clientFirstName || '';
          if (l) l.value = state.clientLastName || '';
        }
      }

      function updateRequestNameFieldsVisibility() {
        var block = document.getElementById('requestNameBlockCatalog');
        if (!block) return;
        block.style.display = state.needsProfileName ? 'block' : 'none';
        if (state.needsProfileName) {
          var f = document.getElementById('requestFirstName');
          var l = document.getElementById('requestLastName');
          if (f) f.value = state.clientFirstName || '';
          if (l) l.value = state.clientLastName || '';
        }
      }

      /** Refresh client phone from API (e.g. before booking form) so DB updates are visible. */
      function refreshClientPhoneForBookingForm(cb) {
        getClientSession().then(function(session) {
          applySessionToState(session);
          updateBookingNameFieldsVisibility();
          if (cb) cb();
        }).catch(function() {
          updateBookingNameFieldsVisibility();
          if (cb) cb();
        });
      }

      function prefillBookingPhoneField() {
        var el = document.getElementById('bookingPhone');
        if (!el) return;
        el.value = (state.clientPhone || '').trim();
      }

      function persistTrainerSelection(trainerId) {
        // Persist trainer choice so the next open starts from the same context (city/service/arena/trainer).
        if (!trainerId || !state.cityId || !state.serviceId) return;
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return;
        var headers = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData };
        var url = '/api/webapp/client/session?init_data=' + encodeURIComponent(initData);
        fetch(url, {
          method: 'POST',
          headers: headers,
          body: JSON.stringify({ city_id: state.cityId, service_id: state.serviceId, arena_id: state.arenaId, trainer_id: trainerId })
        }).catch(function() { /* no UX impact */ });
      }

      function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }
      function escapeAttr(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/"/g, '&quot;');
      }
      function formatCatalogGroupDow(dow) {
        var labels = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
        if (dow == null || dow < 0 || dow > 6) return '—';
        return labels[dow] || '—';
      }
      function formatCatalogGroupRules(rules) {
        if (!rules || !rules.length) return '';
        return rules.map(function(r) {
          return formatCatalogGroupDow(r.day_of_week) + ' ' + (r.start_time || '').slice(0, 5);
        }).join(', ');
      }
      function loadTrainingGroupsBlock(trainer) {
        var el = document.getElementById('trainerDetailGroups');
        if (!el || !trainer || !trainer.id) return;
        el.innerHTML = '';
        getJson('/trainers/' + trainer.id + '/training-groups').then(function(data) {
          var groups = (data && data.groups) || [];
          if (!groups.length) return;
          var html = '<div class="trainer-detail-groups-title">Набор в группы</div>';
          groups.forEach(function(g) {
            var sched = formatCatalogGroupRules(g.schedule_rules);
            html += '<div class="trainer-detail-group-card">';
            html += '<div class="trainer-detail-group-name">' + escapeHtml(g.name || '') + '</div>';
            html += '<div class="trainer-detail-group-meta">' + escapeHtml(g.service_name || '—');
            if (g.arena_name) html += ' · ' + escapeHtml(g.arena_name);
            html += '</div>';
            if (sched) html += '<div class="trainer-detail-group-sched">' + escapeHtml(sched) + '</div>';
            if (g.catalog_pitch) html += '<div class="trainer-detail-group-pitch">' + escapeHtml(g.catalog_pitch) + '</div>';
            html += '<div class="trainer-detail-group-spots">Занято: ' + (g.seated_count != null ? g.seated_count : 0) + ' из ' + (g.max_members || '—') + ' · свободно ' + (g.spots_left != null ? g.spots_left : '—') + '</div>';
            html += '<button type="button" class="btn-primary btn-block catalog-group-join" data-group-id="' + g.id + '">Вступить в группу</button>';
            html += '</div>';
          });
          el.innerHTML = html;
          el.querySelectorAll('.catalog-group-join').forEach(function(btn) {
            btn.onclick = function() {
              var gid = parseInt(btn.getAttribute('data-group-id'), 10);
              if (!gid) return;
              submitCatalogGroupJoinRequest(gid);
            };
          });
        }).catch(function() { /* no block */ });
      }
      function submitCatalogGroupJoinRequest(groupId) {
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) {
          alert('Откройте каталог из Telegram, чтобы отправить заявку.');
          return;
        }
        var headers = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData };
        var url = '/api/webapp/client/training-groups/' + groupId + '/join-request?initData=' + encodeURIComponent(initData);
        fetch(url, { method: 'POST', headers: headers, body: '{}' })
          .then(function(r) {
            return r.json().then(function(j) {
              if (!r.ok) {
                var d = j && j.detail;
                throw new Error(typeof d === 'string' ? d : (r.statusText || 'Ошибка'));
              }
              return j;
            });
          })
          .then(function() {
            prefetch.firstPageKey = null;
            prefetch.firstPageData = null;
            clearCatalogSessionStorageCache();
            alert('Вы добавлены в группу. Тренер увидит вас в списке участников.');
          })
          .catch(function(e) {
            alert(e.message || 'Не удалось отправить заявку');
          });
      }
      function renderSummary() {
        var rows = [
          { key: 'city', label: 'Город', value: state.cityName || '—', cls: '' },
          { key: 'service', label: 'Услуга', value: state.serviceName || '—', cls: '' },
          { key: 'arena', label: 'Арена', value: state.arenaName || '—', cls: '' },
          { key: 'trainer', label: 'Тренер', value: state.trainerName || 'Не выбран', cls: state.trainerName ? '' : 'muted' }
        ];
        document.getElementById('summaryRows').innerHTML = rows.map(function(r) {
          return '<button type="button" class="summary-row summary-row-clickable" data-action="' + r.key + '">' +
            '<span class="label">' + r.label + '</span>' +
            '<span class="value ' + (r.cls || '') + '">' + escapeHtml(r.value || '—') + '</span><span class="row-arrow">→</span></button>';
        }).join('');
        document.querySelectorAll('#summaryRows .summary-row-clickable').forEach(function(btn) {
          btn.onclick = function() {
            var action = btn.dataset.action;
            if (action === 'city') {
              state.returnToSummary = true;
              document.getElementById('backFromCityToSummary').style.display = 'block';
              loadCities();
              showScreen('screenCity');
            } else if (action === 'service') {
              if (!state.cityId) {
                state.returnToSummary = true;
                document.getElementById('backFromCityToSummary').style.display = 'block';
                loadCities();
                showScreen('screenCity');
              } else {
                state.returnToSummary = true;
                document.getElementById('backFromServiceToSummary').style.display = 'block';
                loadServices();
                showScreen('screenService');
              }
            } else if (action === 'arena') {
              if (!state.cityId) {
                state.returnToSummary = true;
                document.getElementById('backFromCityToSummary').style.display = 'block';
                loadCities();
                showScreen('screenCity');
              } else {
                state.returnToSummary = true;
                document.getElementById('backFromArenaToSummary').style.display = 'block';
                loadArenas();
                showScreen('screenArena');
              }
            } else if (action === 'trainer') {
              if (!state.cityId || !state.serviceId) return;
              state.returnToSummary = true;
              state.offset = 0;
              loadCatalogList();
              showScreen('screenTrainers');
            }
          };
        });
      }

      function loadCities() {
        document.getElementById('cityList').innerHTML = '<div class="loading">Загрузка...</div>';
        getJson('/cities').then(function(data) {
          var items = data.items || [];
          if (!items.length) {
            document.getElementById('cityList').innerHTML = '<div class="empty">Нет городов</div>';
            return;
          }
          var html = items.map(function(c) {
            return '<button type="button" class="choice-card" data-id="' + c.id + '" data-name="' + (c.name || '').replace(/"/g, '&quot;') + '"><div class="main"><div class="label">Город</div><div class="value">' + (c.name || '') + '</div></div><span class="arrow">→</span></button>';
          }).join('');
          document.getElementById('cityList').innerHTML = html;
          document.getElementById('backFromCityToSummary').style.display = state.returnToSummary ? 'block' : 'none';
          document.querySelectorAll('#cityList .choice-card').forEach(function(btn) {
            btn.onclick = function() {
              state.cityId = parseInt(btn.dataset.id, 10);
              state.cityName = btn.dataset.name || '';
              clearCatalogSessionStorageCache();
              if (state.returnToSummary) {
                state.returnToSummary = false;
                state.serviceId = null; state.serviceName = '';
                state.arenaId = null; state.arenaName = 'Любая';
                state.trainerId = null; state.trainerName = '';
                document.getElementById('backFromCityToSummary').style.display = 'none';
                renderSummary();
                showScreen('screenSummary');
              } else {
                loadServices();
                showScreen('screenService');
              }
              prefetchFirstPageIfNeeded();
            };
          });
        }).catch(function() {
          document.getElementById('cityList').innerHTML = '<div class="error">Ошибка загрузки</div>';
        });
      }

      function loadServices() {
        document.getElementById('serviceList').innerHTML = '<div class="loading">Загрузка...</div>';
        getJson('/services').then(function(data) {
          var items = data.items || [];
          if (!items.length) {
            document.getElementById('serviceList').innerHTML = '<div class="empty">Нет услуг</div>';
            var backCityEmpty = document.getElementById('backToCity');
            if (backCityEmpty) backCityEmpty.style.display = state.returnToSummary ? 'none' : 'block';
            return;
          }
          var html = items.map(function(s) {
            return '<button type="button" class="choice-card" data-id="' + s.id + '" data-name="' + (s.name || '').replace(/"/g, '&quot;') + '"><div class="main"><div class="label">Услуга</div><div class="value">' + (s.name || '') + '</div></div><span class="arrow">→</span></button>';
          }).join('');
          document.getElementById('serviceList').innerHTML = html;
          document.getElementById('backFromServiceToSummary').style.display = state.returnToSummary ? 'block' : 'none';
          var backCity = document.getElementById('backToCity');
          if (backCity) backCity.style.display = state.returnToSummary ? 'none' : 'block';
          document.querySelectorAll('#serviceList .choice-card').forEach(function(btn) {
            btn.onclick = function() {
              state.serviceId = parseInt(btn.dataset.id, 10);
              state.serviceName = btn.dataset.name || '';
              clearCatalogSessionStorageCache();
              if (state.returnToSummary) {
                state.returnToSummary = false;
                state.arenaId = null; state.arenaName = 'Любая';
                state.trainerId = null; state.trainerName = '';
                document.getElementById('backFromServiceToSummary').style.display = 'none';
                renderSummary();
                showScreen('screenSummary');
              } else {
                loadArenas();
                showScreen('screenArena');
              }
              prefetchFirstPageIfNeeded();
            };
          });
        }).catch(function() {
          document.getElementById('serviceList').innerHTML = '<div class="error">Ошибка загрузки</div>';
          var backCityErr = document.getElementById('backToCity');
          if (backCityErr) backCityErr.style.display = state.returnToSummary ? 'none' : 'block';
        });
      }

      function loadArenas() {
        document.getElementById('arenaList').innerHTML = '<div class="loading">Загрузка...</div>';
        getJson('/arenas', { city_id: state.cityId }).then(function(data) {
          var items = data.items || [];
          var html = '<button type="button" class="choice-card" data-id="" data-name="Любая"><div class="main"><div class="label">Арена</div><div class="value">Любая</div></div><span class="arrow">→</span></button>';
          html += items.map(function(a) {
            return '<button type="button" class="choice-card" data-id="' + a.id + '" data-name="' + (a.name || '').replace(/"/g, '&quot;') + '"><div class="main"><div class="label">Арена</div><div class="value">' + (a.name || '') + '</div></div><span class="arrow">→</span></button>';
          }).join('');
          document.getElementById('arenaList').innerHTML = html;
          document.getElementById('backFromArenaToSummary').style.display = state.returnToSummary ? 'block' : 'none';
          // From summary: only "К выбору" — "Другая услуга" duplicates back affordance and skips loadServices (broken screen).
          var backSvc = document.getElementById('backToService');
          if (backSvc) backSvc.style.display = state.returnToSummary ? 'none' : 'block';
          document.querySelectorAll('#arenaList .choice-card').forEach(function(btn) {
            btn.onclick = function() {
              state.arenaId = btn.dataset.id ? parseInt(btn.dataset.id, 10) : null;
              state.arenaName = btn.dataset.name || 'Любая';
              state.offset = 0;
              clearCatalogSessionStorageCache();
              if (state.returnToSummary) {
                state.returnToSummary = false;
                state.trainerId = null; state.trainerName = '';
                document.getElementById('backFromArenaToSummary').style.display = 'none';
                renderSummary();
                showScreen('screenSummary');
              } else {
                loadCatalogList();
                showScreen('screenTrainers');
              }
              prefetchFirstPageIfNeeded();
            };
          });
        }).catch(function() {
          document.getElementById('arenaList').innerHTML = '<div class="error">Ошибка загрузки</div>';
          var backSvc = document.getElementById('backToService');
          if (backSvc) backSvc.style.display = state.returnToSummary ? 'none' : 'block';
        });
      }

      function formatCatalogServicePrice(s) {
        var minV = s.price_byn_min != null ? s.price_byn_min : s.price_byn;
        var maxV = s.price_byn_max != null ? s.price_byn_max : s.price_byn;
        if (minV == null && s.price_byn == null) return 'по запросу';
        if (minV != null && maxV != null && minV !== maxV) {
          var a = (minV === Math.floor(minV) ? minV : minV.toFixed(2));
          return 'от ' + a + ' BYN';
        }
        var v = minV != null ? minV : s.price_byn;
        return (v === Math.floor(v) ? v : v.toFixed(2)) + ' BYN';
      }

      /** Rows while /trainers or /training-groups fetch — matches list card layout (photo + text + arrow). */
      var CATALOG_LIST_SKELETON_ROWS = 5;

      function buildCatalogTrainerListSkeletonHtml() {
        var parts = [
          '<div class="catalog-trainer-list-skel" role="status" aria-busy="true" aria-label="Загрузка тренеров">',
        ];
        for (var i = 0; i < CATALOG_LIST_SKELETON_ROWS; i++) {
          parts.push(
            '<div class="catalog-trainer-skel-card" aria-hidden="true">' +
              '<div class="catalog-trainer-skel-card__photo catalog-skel-shimmer"></div>' +
              '<div class="catalog-trainer-skel-card__main">' +
                '<div class="catalog-skel-line catalog-skel-line--title catalog-skel-shimmer"></div>' +
                '<div class="catalog-skel-line catalog-skel-line--meta catalog-skel-shimmer"></div>' +
                '<div class="catalog-skel-line catalog-skel-line--meta2 catalog-skel-shimmer"></div>' +
              '</div>' +
              '<span class="catalog-trainer-skel-card__arrow catalog-skel-shimmer"></span>' +
            '</div>'
          );
        }
        parts.push('</div>');
        return parts.join('');
      }

      function buildCatalogGroupListSkeletonHtml() {
        var parts = [
          '<div class="catalog-group-list-skel" role="status" aria-busy="true" aria-label="Загрузка групп">',
        ];
        for (var j = 0; j < CATALOG_LIST_SKELETON_ROWS; j++) {
          parts.push(
            '<div class="catalog-group-skel-card" aria-hidden="true">' +
              '<div class="catalog-group-skel-card__photo catalog-skel-shimmer"></div>' +
              '<div class="catalog-group-skel-card__body">' +
                '<div class="catalog-skel-line catalog-skel-line--group-title catalog-skel-shimmer"></div>' +
                '<div class="catalog-skel-line catalog-skel-line--group-meta catalog-skel-shimmer"></div>' +
                '<div class="catalog-skel-line catalog-skel-line--group-meta2 catalog-skel-shimmer"></div>' +
                '<div class="catalog-group-skel-card__actions">' +
                  '<div class="catalog-skel-line catalog-skel-line--btn catalog-skel-shimmer"></div>' +
                  '<div class="catalog-skel-line catalog-skel-line--btn catalog-skel-line--btn--secondary catalog-skel-shimmer"></div>' +
                '</div>' +
              '</div>' +
            '</div>'
          );
        }
        parts.push('</div>');
        return parts.join('');
      }

      function setCatalogListLoadingPlaceholder() {
        var listEl = document.getElementById('trainerList');
        var footEl = document.getElementById('trainerListFooter');
        if (!listEl) return;
        listEl.innerHTML =
          state.catalogMode === 'groups'
            ? buildCatalogGroupListSkeletonHtml()
            : buildCatalogTrainerListSkeletonHtml();
        if (footEl) footEl.style.display = 'none';
      }

      /** Fade + slight lift when replacing skeleton (or prior list) with loaded content — mirrors client hub bookings. */
      function revealCatalogListContent(innerHtml) {
        var block = document.getElementById('trainerList');
        if (!block) return;
        block.innerHTML = '<div class="catalog-list-mount">' + innerHtml + '</div>';
        var mount = block.firstElementChild;
        if (!mount) return;
        requestAnimationFrame(function() {
          requestAnimationFrame(function() {
            mount.classList.add('catalog-list-mount--visible');
          });
        });
      }

      function loadTrainingGroupsCatalog(opts) {
        opts = opts || {};
        var myReq = ++catalogListReqId;
        if (!opts.silent) {
          setCatalogListLoadingPlaceholder();
          document.getElementById('pagination').innerHTML = '';
        }
        initializeFilterHandlers();
        initCatalogModeToggle();
        updateCatalogModeUi();
        var params = makeGroupListParams(state.offset);
        var firstPageKey = makeFirstPageKey();
        var request;
        if (state.offset === 0) {
          if (!(prefetch.firstPageKey === firstPageKey && prefetch.firstPageData)) {
            var fromDisk = readCatalogFirstPageFromStorage(firstPageKey);
            if (fromDisk) {
              prefetch.firstPageKey = firstPageKey;
              prefetch.firstPageData = fromDisk;
            }
          }
        }
        if (state.offset === 0 && prefetch.firstPageKey === firstPageKey && prefetch.firstPageData) {
          request = Promise.resolve(prefetch.firstPageData);
        } else if (state.offset === 0) {
          request = fetchCatalogFirstPage('/training-groups', params, firstPageKey);
        } else {
          request = getJson('/training-groups', params);
        }
        request.then(function(data) {
          if (myReq !== catalogListReqId) return;
          var items = data.items || [];
          var total = data.total != null ? data.total : items.length;
          state.groupCatalogItems = items;
          state.total = total;
          state.photoSource = data._photo_source || 'proxy';
          updateResultsCount(total);
          if (!items.length) {
            if (myReq !== catalogListReqId) return;
            revealCatalogListContent(
              '<div class="empty">Групп с набором по вашему запросу пока нет.</div>' +
                '<div class="empty-state-request">' +
                '<p class="empty-state-text">Попробуйте другие дни или арену — или оставьте заявку.</p>' +
                '<button type="button" class="btn-block btn-leave-request" id="btnEmptyStateRequestGroups">Оставить заявку</button>' +
                '</div>'
            );
            document.getElementById('pagination').innerHTML = '';
            var btnEg = document.getElementById('btnEmptyStateRequestGroups');
            if (btnEg) btnEg.onclick = openGeneralRequestForm;
            document.getElementById('trainerListFooter').innerHTML = '';
            document.getElementById('trainerListFooter').style.display = 'none';
            return;
          }
          if (state.offset === 0) {
            writeCatalogFirstPageToStorage(firstPageKey, data);
            prefetch.firstPageKey = firstPageKey;
            prefetch.firstPageData = data;
          }
          warmupCatalogImagesFromItems(items, 16);
          if (myReq !== catalogListReqId) return;
          var html = items.map(function(g, idx) {
            var tr = g.trainer || {};
            var p = tr.profile || {};
            var photo = tr.photos && tr.photos[0];
            var src = photoSrcList(photo);
            var proxyFallback = photo ? photoUrl(photo.file_key_list || photo.file_key) : '';
            var tname = trainerName(tr);
            var sched = formatCatalogGroupRules(g.schedule_rules);
            var meta = [
              tname,
              (g.service_name || '—'),
              g.arena_name ? g.arena_name : null,
              sched
            ].filter(Boolean).join(' · ');
            var spots = (g.spots_left != null && g.max_members != null)
              ? ('Свободно ' + g.spots_left + ' из ' + g.max_members)
              : '';
            var photoHtml = src
              ? '<div class="cg-photo-wrap"><img class="cg-photo" src="' + src + '" alt="" loading="lazy" decoding="async" data-fallback="' + (proxyFallback || '').replace(/"/g, '&quot;') + '"></div>'
              : '<div class="cg-photo-wrap cg-photo-wrap--placeholder" aria-hidden="true"></div>';
            var joinBtn = '<button type="button" class="btn-primary btn-block catalog-group-join" data-group-id="' + g.id + '">Вступить в группу</button>';
            var profileBtn = '<button type="button" class="btn-secondary btn-block catalog-group-open-trainer" data-index="' + idx + '">Профиль тренера</button>';
            return '<div class="catalog-group-list-card" data-index="' + idx + '">' +
              photoHtml +
              '<div class="cg-body">' +
              '<div class="cg-name">' + escapeHtml(g.name || 'Группа') + '</div>' +
              '<div class="cg-meta">' + escapeHtml(meta) + '</div>' +
              (spots ? '<div class="cg-meta">' + escapeHtml(spots) + '</div>' : '') +
              (g.catalog_pitch ? '<div class="cg-meta">' + escapeHtml(g.catalog_pitch.length > 120 ? g.catalog_pitch.slice(0, 117) + '…' : g.catalog_pitch) + '</div>' : '') +
              '<div class="cg-actions">' + joinBtn + profileBtn + '</div>' +
              '</div></div>';
          }).join('');
          if (myReq !== catalogListReqId) return;
          revealCatalogListContent(html);
          document.querySelectorAll('#trainerList .cg-photo-wrap img.cg-photo').forEach(function(img) {
            function showLoaded() {
              img.classList.add('loaded');
            }
            img.onload = showLoaded;
            img.onerror = function() {
              var fb = img.dataset.fallback;
              if (fb) {
                img.onerror = null;
                img.src = fb;
                return;
              }
              img.style.display = 'none';
            };
            if (img.complete && img.naturalWidth) showLoaded();
          });
          document.querySelectorAll('#trainerList .catalog-group-join').forEach(function(btn) {
            btn.addEventListener('click', function(ev) {
              ev.stopPropagation();
              var gid = parseInt(btn.getAttribute('data-group-id'), 10);
              if (gid) submitCatalogGroupJoinRequest(gid);
            });
          });
          document.querySelectorAll('#trainerList .catalog-group-open-trainer').forEach(function(btn) {
            btn.addEventListener('click', function(ev) {
              ev.stopPropagation();
              var ix = parseInt(btn.getAttribute('data-index'), 10);
              var row = state.groupCatalogItems[ix];
              if (row && row.trainer) openTrainerDetailFromTrainerObject(row.trainer, true);
            });
          });
          document.querySelectorAll('#trainerList .catalog-group-list-card').forEach(function(card) {
            card.addEventListener('click', function(ev) {
              if (ev.target.closest && (ev.target.closest('.catalog-group-join') || ev.target.closest('.catalog-group-open-trainer'))) return;
              var ix = parseInt(card.getAttribute('data-index'), 10);
              var row = state.groupCatalogItems[ix];
              if (row && row.trainer) openTrainerDetailFromTrainerObject(row.trainer, true);
            });
          });
          var page = Math.floor(state.offset / state.limit) + 1;
          var totalPages = Math.max(1, Math.ceil(total / state.limit));
          var pagHtml = '';
          if (state.offset > 0) {
            pagHtml += '<button type="button" id="pagePrevGroups">◀ Назад</button>';
          }
          pagHtml += '<span>Стр. ' + page + ' из ' + totalPages + '</span>';
          if (state.offset + items.length < total) {
            pagHtml += '<button type="button" id="pageNextGroups">Вперёд ▶</button>';
          }
          document.getElementById('pagination').innerHTML = pagHtml;
          var prevG = document.getElementById('pagePrevGroups');
          if (prevG) prevG.onclick = function() { state.offset -= state.limit; loadTrainingGroupsCatalog(); };
          var nextG = document.getElementById('pageNextGroups');
          if (nextG) nextG.onclick = function() { state.offset += state.limit; loadTrainingGroupsCatalog(); };
          var footerHtml = 'Не нашли группу? <span class="link" id="linkGeneralRequestFromGroupList">Оставить заявку</span>';
          var photoSourceLabel = state.photoSource === 'cdn' ? 'через CDN' : (state.photoSource === 'direct' ? 'напрямую с S3' : 'через сервер');
          footerHtml += '<div class="photo-source-hint">Фото: ' + photoSourceLabel + '</div>';
          document.getElementById('trainerListFooter').innerHTML = footerHtml;
          document.getElementById('trainerListFooter').style.display = 'block';
          var linkG = document.getElementById('linkGeneralRequestFromGroupList');
          if (linkG) linkG.onclick = openGeneralRequestForm;
          if (state.offset === 0 && !shouldSkipCatalogConnectionHeavyPrefetch()) {
            var sk = firstPageKey;
            var mr = myReq;
            scheduleCatalogIdlePrefetch(function() {
              if (mr !== catalogListReqId) return;
              if (makeFirstPageKey() !== sk) return;
              if (state.offset !== 0) return;
              var nextPageParams = makeGroupListParams(state.limit);
              getJson('/training-groups', nextPageParams).then(function(nextData) {
                if (mr !== catalogListReqId) return;
                var nextItems = nextData && nextData.items ? nextData.items : [];
                warmupImageUrls(nextItems.slice(0, 6).map(function(g) {
                  var tr = g.trainer || {};
                  var photo = tr.photos && tr.photos[0];
                  return photoSrcList(photo) || (photo ? photoUrl(photo.file_key_list || photo.file_key) : '');
                }).filter(Boolean));
              }).catch(function() { /* no-op */ });
            }, 2500);
          }
        }).catch(function() {
          if (myReq !== catalogListReqId) return;
          if (opts.silent) return;
          revealCatalogListContent('<div class="error">Ошибка загрузки</div>');
        });
      }

      function loadTrainers(opts) {
        opts = opts || {};
        var myReq = ++catalogListReqId;
        if (!opts.silent) {
          setCatalogListLoadingPlaceholder();
          document.getElementById('pagination').innerHTML = '';
        }
        
        // Initialize filter handlers if not already done
        initializeFilterHandlers();
        initCatalogModeToggle();
        updateCatalogModeUi();
        
        // Only city/service/arena — never trainer_id, so list shows all matching trainers (selected trainer is on "Мой тренер" tab).
        var params = makeTrainerListParams(state.offset);
        var request;
        var firstPageKey = makeFirstPageKey();
        if (state.offset === 0) {
          if (!(prefetch.firstPageKey === firstPageKey && prefetch.firstPageData)) {
            var fromDisk = readCatalogFirstPageFromStorage(firstPageKey);
            if (fromDisk) {
              prefetch.firstPageKey = firstPageKey;
              prefetch.firstPageData = fromDisk;
            }
          }
        }
        if (state.offset === 0 && prefetch.firstPageKey === firstPageKey && prefetch.firstPageData) {
          request = Promise.resolve(prefetch.firstPageData);
        } else if (state.offset === 0) {
          request = fetchCatalogFirstPage('/trainers', params, firstPageKey);
        } else {
          request = getJson('/trainers', params);
        }
        request.then(function(data) {
          if (myReq !== catalogListReqId) return;
          var items = data.items || [];
          var total = data.total != null ? data.total : items.length;
          state.trainers = items;
          state.total = total;
          state.photoSource = data._photo_source || 'proxy';
          updateResultsCount(total);
          if (!items.length) {
            if (myReq !== catalogListReqId) return;
            revealCatalogListContent(
              '<div class="empty">Тренеров по вашему запросу пока нет.</div>' +
                '<div class="empty-state-request">' +
                '<p class="empty-state-text">Оставьте заявку — подберём вариант и напишем в боте.</p>' +
                '<button type="button" class="btn-block btn-leave-request" id="btnEmptyStateRequest">Оставить заявку</button>' +
                '</div>'
            );
            document.getElementById('pagination').innerHTML = '';
            var btnEmpty = document.getElementById('btnEmptyStateRequest');
            if (btnEmpty) btnEmpty.onclick = openGeneralRequestForm;
            document.getElementById('trainerListFooter').innerHTML = '';
            document.getElementById('trainerListFooter').style.display = 'none';
            return;
          }
          if (state.offset === 0) {
            writeCatalogFirstPageToStorage(firstPageKey, data);
            prefetch.firstPageKey = firstPageKey;
            prefetch.firstPageData = data;
          }
          if (myReq !== catalogListReqId) return;
          document.querySelectorAll('link[data-tcb-catalog-preload]').forEach(function(el) { el.remove(); });
          for (var pi = 0; pi < Math.min(3, items.length); pi++) {
            var p0p = items[pi].photos && items[pi].photos[0];
            var ls = photoSrcList(p0p);
            if (ls) {
              var lk = document.createElement('link');
              lk.rel = 'preload';
              lk.as = 'image';
              lk.href = ls;
              lk.setAttribute('data-tcb-catalog-preload', '1');
              document.head.appendChild(lk);
            }
            var ds = photoSrcDetail(p0p);
            if (ds && ds !== ls) {
              var dk = document.createElement('link');
              dk.rel = 'preload';
              dk.as = 'image';
              dk.href = ds;
              dk.setAttribute('data-tcb-catalog-preload', '1');
              document.head.appendChild(dk);
            }
          }
          warmupCatalogImagesFromItems(items, 16);
          var runIdle = window.requestIdleCallback || function(cb) { return setTimeout(function() { cb({}); }, 400); };
          runIdle(function() {
            if (myReq !== catalogListReqId) return;
            warmupCatalogImagesFromItems(items, 50);
          }, { timeout: 2500 });
          if (myReq !== catalogListReqId) return;
          var html = items.map(function(t, idx) {
            var photo = t.photos && t.photos[0];
            var src = photoSrcList(photo);
            var proxyFallback = photo ? photoUrl(photo.file_key_list || photo.file_key) : '';
            var isPriority = idx < 3;
            var p = t.profile || {};

            var metaTop = [];
            if (p && (p.rating_avg != null) && (p.rating_count || 0) > 0) {
              metaTop.push(p.rating_avg.toFixed(1) + ' ★ (' + p.rating_count + ')');
            }
            if (p && p.experience_years != null) {
              var expLine = formatExperienceCatalogLine(p.experience_years);
              if (expLine) metaTop.push(expLine);
            }

            var metaBottom = [];
            if (typeof t.free_slots_14d === 'number') {
              metaBottom.push('Свободных слотов: ' + t.free_slots_14d);
            }
            var services = t.services || [];
            if (services.length) {
              var s0 = services[0];
              metaBottom.push((s0.service_name || 'Услуга') + ': ' + formatCatalogServicePrice(s0));
            }
            if (t.arena_names && t.arena_names.length) {
              metaBottom.push(t.arena_names.slice(0, 2).join(', '));
            }
            // List cards: skip education preview; full block stays on trainer detail.

            var infoHtml = '<div class="info"><div class="name">' + trainerName(t) + '</div>';
            if (metaTop.length) {
              infoHtml += '<div class="meta">' + metaTop.join(' · ') + '</div>';
            }
            if (metaBottom.length) {
              infoHtml += '<div class="meta">' + metaBottom.join(' · ') + '</div>';
            }
            infoHtml += '</div>';
            var groupBadgeHtml = '';
            if (typeof t.open_groups_count === 'number' && t.open_groups_count > 0) {
              groupBadgeHtml = '<div class="catalog-trainer-group-badge">Набор в группу</div>';
            }

            var photoHtml = src
              ? '<div class="trainer-card-photo-wrap"><div class="trainer-card-photo-placeholder"></div><img src="' + src + '" alt="" loading="' + (isPriority ? 'eager' : 'lazy') + '" fetchpriority="' + (isPriority ? 'high' : 'auto') + '" decoding="async" class="trainer-card-img"' + (proxyFallback ? ' data-fallback="' + proxyFallback.replace(/"/g, '&quot;') + '"' : '') + '></div>'
              : '<div class="trainer-card-photo-wrap"><div class="trainer-card-photo-placeholder"></div></div>';
            return '<button type="button" class="trainer-list-card" data-index="' + idx + '">' +
              photoHtml +
              '<div class="trainer-list-card__main">' + infoHtml + groupBadgeHtml + '</div>' +
              '<span class="arrow">→</span></button>';
          }).join('');
          if (myReq !== catalogListReqId) return;
          revealCatalogListContent(html);
          document.querySelectorAll('#trainerList .trainer-card-img').forEach(function(img) {
            function showLoaded() {
              img.classList.add('loaded');
              var ph = img.previousElementSibling;
              if (ph) ph.style.display = 'none';
            }
            img.onload = showLoaded;
            img.onerror = function() {
              var fb = img.dataset.fallback;
              if (fb) { img.onerror = null; img.src = fb; }
            };
            if (img.complete) showLoaded();
          });
          document.querySelectorAll('#trainerList .trainer-list-card').forEach(function(btn) {
            btn.onclick = function() {
              var idx = parseInt(btn.dataset.index, 10);
              var t = state.trainers[idx];
              openTrainerDetailFromTrainerObject(t, true);
            };
          });
          var page = Math.floor(state.offset / state.limit) + 1;
          var totalPages = Math.max(1, Math.ceil(total / state.limit));
          var pagHtml = '';
          if (state.offset > 0) {
            pagHtml += '<button type="button" id="pagePrev">◀ Назад</button>';
          }
          pagHtml += '<span>Стр. ' + page + ' из ' + totalPages + '</span>';
          if (state.offset + items.length < total) {
            pagHtml += '<button type="button" id="pageNext">Вперёд ▶</button>';
          }
          document.getElementById('pagination').innerHTML = pagHtml;
          var prevBtn = document.getElementById('pagePrev');
          if (prevBtn) prevBtn.onclick = function() { state.offset -= state.limit; loadCatalogList(); };
          var nextBtn = document.getElementById('pageNext');
          if (nextBtn) nextBtn.onclick = function() { state.offset += state.limit; loadCatalogList(); };
          var footerHtml = 'Не нашли подходящего? <span class="link" id="linkGeneralRequestFromList">Оставить заявку</span>';
          var photoSourceLabel = state.photoSource === 'cdn' ? 'через CDN' : (state.photoSource === 'direct' ? 'напрямую с S3' : 'через сервер');
          footerHtml += '<div class="photo-source-hint">Фото: ' + photoSourceLabel + '</div>';
          document.getElementById('trainerListFooter').innerHTML = footerHtml;
          document.getElementById('trainerListFooter').style.display = 'block';
          var linkReq = document.getElementById('linkGeneralRequestFromList');
          if (linkReq) linkReq.onclick = openGeneralRequestForm;
          if (state.offset === 0 && !shouldSkipCatalogConnectionHeavyPrefetch()) {
            var sk = firstPageKey;
            var mr = myReq;
            scheduleCatalogIdlePrefetch(function() {
              if (mr !== catalogListReqId) return;
              if (makeFirstPageKey() !== sk) return;
              if (state.offset !== 0) return;
              var nextPageParams = makeTrainerListParams(state.limit);
              getJson('/trainers', nextPageParams).then(function(nextData) {
                if (mr !== catalogListReqId) return;
                var nextItems = nextData && nextData.items ? nextData.items : [];
                warmupImageUrls(nextItems.slice(0, 6).map(function(t) {
                  return photoSrcList(t.photos && t.photos[0]) || photoSrcDetail(t.photos && t.photos[0]);
                }));
              }).catch(function() { /* no-op */ });
            }, 2500);
          }
        }).catch(function() {
          if (myReq !== catalogListReqId) return;
          if (opts.silent) return;
          revealCatalogListContent('<div class="error">Ошибка загрузки</div>');
        });
      }

      var SLOT_DAYS = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
      var SLOT_MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
      function formatSlotLabel(s) {
        var d = (s.slot_date || '').split('-');
        if (d.length !== 3) return (s.start_time || '') + '–' + (s.end_time || '');
        var day = parseInt(d[2], 10); var month = parseInt(d[1], 10) - 1;
        var dateObj = new Date(d[0], month, day);
        var dayName = SLOT_DAYS[dateObj.getDay()];
        var dateStr = day + ' ' + SLOT_MONTHS[month];
        return dateStr + ' (' + dayName + '), ' + (s.start_time || '') + '–' + (s.end_time || '');
      }

      /** Russian plural for «N мест(о/а/ )» in group-slot UI. */
      function ruSpotsWord(n) {
        var k = Math.abs(parseInt(n, 10)) % 100;
        var k1 = k % 10;
        if (k > 10 && k < 20) return 'мест';
        if (k1 === 1) return 'место';
        if (k1 >= 2 && k1 <= 4) return 'места';
        return 'мест';
      }

      /** Full line for booking form (includes spots for group slots). */
      function formatSlotSelectionSummary(s) {
        var base = formatSlotLabel(s);
        var cap = (s.capacity != null) ? parseInt(s.capacity, 10) : 1;
        var sl = (s.spots_left != null) ? parseInt(s.spots_left, 10) : null;
        if (cap > 1 && sl != null && !isNaN(sl) && sl > 0) {
          return base + ' · осталось ' + sl + ' ' + ruSpotsWord(sl);
        }
        return base;
      }

      function slotGroupSpotsPillHtml(s) {
        var cap = (s.capacity != null) ? parseInt(s.capacity, 10) : 1;
        var sl = (s.spots_left != null) ? parseInt(s.spots_left, 10) : null;
        if (cap > 1 && sl != null && !isNaN(sl) && sl > 0) {
          var w = ruSpotsWord(sl);
          var label = 'Осталось ' + sl + ' ' + w;
          return '<span class="slot-spots-pill" aria-label="' + label.replace(/"/g, '&quot;') + '">' + label + '</span>';
        }
        return '';
      }

      function loadSlotsForTrainer(trainerId, trainerFromList) {
        var initData = tg ? tg.initData : '';
        var q = 'trainer_id=' + encodeURIComponent(trainerId);
        if (trainerFromList && trainerFromList.profile) {
          var mh = trainerFromList.profile.min_hours_before_booking;
          if (mh != null) q += '&min_hours=' + encodeURIComponent(mh);
          var tn = trainerName(trainerFromList);
          if (tn) q += '&trainer_name=' + encodeURIComponent(tn);
        }
        if (state.serviceId != null) q += '&service_id=' + encodeURIComponent(state.serviceId);
        if (initData) q += '&init_data=' + encodeURIComponent(initData);
        var headers = {};
        if (initData) headers['X-Telegram-Init-Data'] = initData;
        return fetch('/api/webapp/client/slots?' + q, { headers: headers }).then(function(r) {
          return r.json().then(function(data) {
            if (!r.ok) throw new Error(data.detail || r.statusText);
            return data;
          });
        });
      }

      /**
       * Multiple arenas: show primary + muted secondaries and a short client hint (request for other venues).
       */
      function buildTrainerArenasBlock(t) {
        var ids = t.arena_ids || [];
        var names = t.arena_names || [];
        var n = ids.length;
        if (n <= 1) {
          return '<div class="trainer-detail-stat-value">' + escapeHtml((names[0] && names[0].trim()) ? names[0] : '—') + '</div>';
        }
        var primaryId = t.primary_arena_id;
        var primaryIdx = 0;
        if (primaryId != null) {
          var pi = ids.indexOf(primaryId);
          if (pi >= 0) primaryIdx = pi;
        }
        var primaryName = (names[primaryIdx] || '—').trim();
        var others = [];
        for (var i = 0; i < n; i++) {
          if (i === primaryIdx) continue;
          others.push((names[i] || '—').trim());
        }
        var html = '<div class="trainer-detail-arena-stack">';
        html += '<div class="trainer-detail-arena-primary-row">';
        html += '<span class="trainer-detail-arena-primary-name">' + escapeHtml(primaryName) + '</span>';
        html += '<span class="trainer-detail-arena-pill">основная</span>';
        html += '</div>';
        if (others.length) {
          html += '<div class="trainer-detail-arena-others">';
          others.forEach(function(nm) {
            html += '<div class="trainer-detail-arena-secondary">' + escapeHtml(nm) + '</div>';
          });
          html += '</div>';
        }
        html += '<p class="trainer-detail-arena-hint">Запись в каталоге — на основную площадку. Нужна другая? Оставьте заявку — тренер согласует.</p>';
        html += '</div>';
        return html;
      }

      function renderTrainerDetail() {
        var t = state.selectedTrainer;
        if (!t) return;
        var p = t.profile || {};
        var name = trainerName(t);
        var ratingStr = (p.rating_avg != null && (p.rating_count || 0) > 0) ? (p.rating_avg.toFixed(1) + ' ★ (' + p.rating_count + ')') : '—';
        var duration = p.session_duration_minutes || 45;
        var arenaIds = t.arena_ids || [];
        var arenaStatClass = 'trainer-detail-stat';
        var arenaInnerHtml;
        if (arenaIds.length > 1) {
          arenaStatClass += ' trainer-detail-stat--arenas';
          arenaInnerHtml = buildTrainerArenasBlock(t);
        } else if (arenaIds.length === 1) {
          arenaInnerHtml = '<div class="trainer-detail-stat-value">' + escapeHtml((t.arena_names && t.arena_names[0]) ? t.arena_names[0] : '—') + '</div>';
        } else {
          arenaInnerHtml = '<div class="trainer-detail-stat-value">—</div>';
        }
        var services = t.services || [];
        var servicesStr = services.length ? services.map(function(s) {
          return (s.service_name || '—') + ': ' + formatCatalogServicePrice(s);
        }).join(', ') : '—';
        var desc = (p.description || '').trim() || '—';
        var detailPhoto = t.photos && t.photos[0];
        var listSrc = photoSrcList(detailPhoto);
        var fullSrc = photoSrcDetail(detailPhoto);
        var fbList = photoProxyListFallback(detailPhoto);
        var fbFull = photoProxyFullFallback(detailPhoto);
        var html = '';
        if (listSrc || fullSrc) {
          html += '<div class="trainer-detail-photo-wrap">';
          html += '<div class="trainer-detail-photo-placeholder"></div>';
          if (listSrc && fullSrc && listSrc !== fullSrc) {
            html += '<img src="' + listSrc + '" alt="" loading="eager" fetchpriority="high" decoding="async" class="trainer-detail-photo-base"';
            if (fbList) html += ' data-fallback-base="' + escapeAttr(fbList) + '"';
            html += '>';
            html += '<img src="' + fullSrc + '" alt="" loading="eager" fetchpriority="high" decoding="async" class="trainer-detail-photo-full"';
            if (fbFull) html += ' data-fallback-full="' + escapeAttr(fbFull) + '"';
            html += '>';
          } else {
            var oneSrc = fullSrc || listSrc;
            html += '<img src="' + oneSrc + '" alt="" loading="eager" fetchpriority="high" decoding="async" class="trainer-detail-photo trainer-detail-photo-single"';
            if (fbFull || fbList) html += ' data-fallback="' + escapeAttr(fbFull || fbList) + '"';
            html += '>';
          }
          html += '</div>';
        }
        html += '<div class="trainer-detail-header">';
        html += '<div class="trainer-detail-name">' + name + '</div>';
        if (ratingStr !== '—') {
          html += '<div class="trainer-detail-rating" style="cursor: pointer;" onclick="showTrainerReviews(' + t.id + ')">⭐ ' + ratingStr + '</div>';
        }
        html += '</div>';
        
        html += '<div class="trainer-detail-stats">';
        html += '<div class="trainer-detail-stat">';
        html += '<div class="trainer-detail-stat-label">Опыт</div>';
        html += '<div class="trainer-detail-stat-value">' + (p.experience_years != null ? (p.experience_years + ' ' + ruYearsWord(p.experience_years)) : '—') + '</div>';
        html += '</div>';
        html += '<div class="trainer-detail-stat">';
        html += '<div class="trainer-detail-stat-label">Занятие</div>';
        html += '<div class="trainer-detail-stat-value">' + duration + ' мин</div>';
        html += '</div>';
        html += '<div class="' + arenaStatClass + '">';
        html += '<div class="trainer-detail-stat-label">Арены</div>';
        html += arenaInnerHtml;
        html += '</div>';
        html += '</div>';
        
        if (services.length > 0) {
          var selectedServiceDescEscaped = '';
          if (state.serviceId != null) {
            var selSvcId = Number(state.serviceId);
            var sj;
            for (sj = 0; sj < services.length; sj++) {
              var sx = services[sj];
              if (sx.service_id == null || Number(sx.service_id) !== selSvcId) continue;
              var rawDesc = sx.description && String(sx.description).trim();
              if (rawDesc) selectedServiceDescEscaped = escapeHtml(rawDesc).replace(/\n/g, '<br>');
              break;
            }
          }
          if (selectedServiceDescEscaped) {
            html += '<div class="trainer-detail-service-callout" role="region" aria-label="О выбранной услуге">';
            html += '<div class="trainer-detail-service-callout-kicker">К вашему выбору в каталоге</div>';
            html += '<div class="trainer-detail-service-callout-body">' + selectedServiceDescEscaped + '</div>';
            html += '</div>';
          }
          html += '<div class="trainer-detail-services">';
          html += '<div class="trainer-detail-services-title">Услуги и цены</div>';
          services.forEach(function(s) {
            var serviceName = s.service_name || '—';
            var priceText = formatCatalogServicePrice(s);
            var sid = s.service_id != null ? Number(s.service_id) : NaN;
            var matchCatalog =
              state.serviceId != null &&
              !isNaN(sid) &&
              Number(state.serviceId) === sid;
            html += '<div class="trainer-detail-service' + (matchCatalog ? ' trainer-detail-service--catalog-selected' : '') + '">';
            html += '<div class="trainer-detail-service-top">';
            html += '<span class="trainer-detail-service-name">' + escapeHtml(serviceName) + '</span>';
            html += '<span class="trainer-detail-service-price">' + escapeHtml(priceText) + '</span>';
            html += '</div>';
            html += '</div>';
          });
          html += '</div>';
        }
        var htmlTop = html;
        html = '';
        
        var eduRows = Array.isArray(t.education_entries) ? t.education_entries : [];
        var profileEduDetail = (p.education && typeof p.education === 'string' && p.education.trim())
          ? p.education.trim()
          : '';
        var profileExtraForDetail = profileEduDetail;
        if (eduRows && eduRows.length > 0 && profileEduDetail && isProfileEducationCategoryOnly(profileEduDetail)) {
          profileExtraForDetail = '';
        }
        if (eduRows.length > 0) {
          html += '<div class="trainer-detail-education">';
          html += '<div class="trainer-detail-education-title">Образование</div>';
          html += '<p class="trainer-detail-education-hint">Нажмите на запись, чтобы раскрыть детали и фото документов.</p>';
          var eduAnyHtml = '';
          eduRows.forEach(function(edu) {
            var itemHtml = buildCatalogEducationItemHtml(edu);
            if (itemHtml) eduAnyHtml += itemHtml;
          });
          if (eduAnyHtml) {
            html += eduAnyHtml;
          } else if (profileEduDetail) {
            html += '<div class="trainer-detail-education-body-line">' + escapeHtml(profileEduDetail).replace(/\n/g, '<br>') + '</div>';
          }
          if (profileExtraForDetail) {
            html += '<div class="trainer-detail-education-extra">';
            html += '<div class="trainer-detail-education-extra-label">Дополнительно</div>';
            html += '<div class="trainer-detail-education-extra-body">' + escapeHtml(profileExtraForDetail).replace(/\n/g, '<br>') + '</div>';
            html += '</div>';
          }
          html += '</div>';
        } else if (profileEduDetail) {
          html += '<div class="trainer-detail-education">';
          html += '<div class="trainer-detail-education-title">Образование</div>';
          html += '<div class="trainer-detail-education-extra">';
          html += '<div class="trainer-detail-education-extra-body">' + escapeHtml(profileEduDetail).replace(/\n/g, '<br>') + '</div>';
          html += '</div>';
          html += '</div>';
        }
        
        if (desc !== '—') {
          html += '<div class="trainer-detail-desc">' + escapeHtml(desc).replace(/\n/g, '<br>') + '</div>';
        }
        var photoSourceLabel = (detailPhoto && detailPhoto._source === 'cdn') ? 'Фото: через CDN' : (detailPhoto && detailPhoto._source === 'direct') ? 'Фото: напрямую с S3' : 'Фото: через сервер';
        html += '<div class="photo-source-hint trainer-detail-photo-source">' + photoSourceLabel + '</div>';
        document.getElementById('trainerDetailTop').innerHTML = htmlTop;
        document.getElementById('trainerDetailRest').innerHTML = html;
        document.querySelectorAll('#trainerDetailRest .trainer-detail-education-doc').forEach(function(linkEl) {
          linkEl.addEventListener('click', function(ev) {
            if (tg && typeof tg.openLink === 'function') {
              ev.preventDefault();
              tg.openLink(linkEl.href);
            }
          });
        });
        document.getElementById('trainerDetailGroups').innerHTML = '';
        bindTrainerDetailPhotoWrap();
        loadTrainingGroupsBlock(t);
        document.getElementById('trainerDetailSlots').innerHTML = '<div class="slots-empty">Загрузка слотов…</div>';
        document.getElementById('trainerDetailActions').innerHTML = '';
        var canBook = t.can_book === true;
        if (!canBook) {
          var phoneLine = '';
          var ph = (p.phone || '').trim();
          var ct = (p.contacts || '').trim();
          if (ph) phoneLine += '<div class="slots-empty slots-contact"><strong>Телефон:</strong> <a href="tel:' + ph.replace(/[^\d+]/g, '') + '">' + escapeHtml(ph) + '</a></div>';
          if (ct) phoneLine += '<div class="slots-empty slots-contact"><strong>Контакты:</strong> ' + escapeHtml(ct) + '</div>';
          document.getElementById('trainerDetailSlots').innerHTML =
            '<div class="slots-title">Онлайн-запись</div>' +
            '<div class="slots-empty">У этого тренера нет самозаписи через каталог. Свяжитесь напрямую — тренер в каталоге, как и раньше.</div>' +
            phoneLine;
          state.slotsForTrainer = [];
          var actionsEl = document.getElementById('trainerDetailActions');
          actionsEl.innerHTML = '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
          document.getElementById('trainerDetailSecondary').innerHTML = '';
          return;
        }
        loadSlotsForTrainer(t.id, t).then(function(data) {
          state.slotsForTrainer = data.slots || [];
          var slotsEl = document.getElementById('trainerDetailSlots');
          var actionsEl = document.getElementById('trainerDetailActions');
          var slots = state.slotsForTrainer;
          var slotsHtml = '<div class="slots-title">Ближайшие слоты</div>';
          if (isNonPrimaryArenaFilter()) {
            var primArenaName = primaryVenueLabel(t);
            var btnPrimarySlotsLabel = primArenaName
              ? ('Слоты на основной площадке: «' + escapeHtml(primArenaName) + '»')
              : 'Показать слоты на основной площадке';
            slotsEl.innerHTML = slotsHtml +
              '<div class="slots-empty">Онлайн-запись только на основную площадку тренера. Чтобы заниматься на другой арене, оставьте заявку — тренер согласует место и время.</div>';
            actionsEl.innerHTML = '';
            actionsEl.innerHTML += '<button type="button" class="btn-primary btn-block" id="btnCatalogSlotsPrimaryArena">' + btnPrimarySlotsLabel + '</button>';
            actionsEl.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
            if (t.has_pass_products || t.has_certificate_products) {
              actionsEl.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="buy-pass">Абонементы/Сертификаты</button>';
            }
            var btnPrim = document.getElementById('btnCatalogSlotsPrimaryArena');
            if (btnPrim) {
              btnPrim.onclick = function() {
                var tr = state.selectedTrainer;
                if (!applyTrainerPrimaryArenaToCatalogFilter(tr)) return;
                renderSummary();
                persistTrainerSelection(tr.id);
                renderTrainerDetail();
              };
            }
            document.getElementById('trainerDetailSecondary').innerHTML = '';
            return;
          }
          if (slots.length === 0) {
            slotsHtml += '<div class="slots-empty">Сейчас нет свободных слотов.</div>';
            slotsHtml += '<div class="slots-empty slots-empty-hint">Оставьте заявку — тренер предложит удобное время.</div>';
          } else {
            var showCount = Math.min(slots.length, 6);
            for (var i = 0; i < showCount; i++) {
              var s = slots[i];
              slotsHtml += '<button type="button" class="slot-row" data-slot-index="' + i + '">' +
                '<span class="slot-row-main"><span class="slot-row-line">' + formatSlotLabel(s) + '</span>' +
                slotGroupSpotsPillHtml(s) + '</span><span>→</span></button>';
            }
            if (slots.length > showCount) {
              slotsHtml += '<button type="button" class="slot-row slot-row-more" id="btnShowAllSlots">Ещё слоты (' + (slots.length - showCount) + ') →</button>';
            }
          }
          slotsEl.innerHTML = slotsHtml;
          slotsEl.querySelectorAll('.slot-row[data-slot-index]').forEach(function(btn) {
            btn.onclick = function() {
              var i = parseInt(btn.dataset.slotIndex, 10);
              state.selectedSlot = state.slotsForTrainer[i];
              document.getElementById('bookingFormSlotLabel').textContent = 'Выбрано: ' + formatSlotSelectionSummary(state.selectedSlot);
              document.getElementById('bookingComment').value = '';
              refreshClientPhoneForBookingForm(function() {
                prefillBookingPhoneField();
                updateBookingVenueHint();
                updateBookingFormServiceAndTiers();
                showScreen('screenBookingForm');
              });
            };
          });
          var btnMore = document.getElementById('btnShowAllSlots');
          if (btnMore) btnMore.onclick = function() { renderSlotPickList(); showScreen('screenSlotPick'); };
          // Очищаем и добавляем кнопки с новым дизайном
          actionsEl.innerHTML = '';
          if (slots.length > 0) {
            actionsEl.innerHTML += '<button type="button" class="btn-primary btn-block" id="btnBookFromDetail">Записаться</button>';
          }
          actionsEl.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
          if (t.has_pass_products || t.has_certificate_products) {
            actionsEl.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="buy-pass">Абонементы/Сертификаты</button>';
          }
          var btnBook = document.getElementById('btnBookFromDetail');
          if (btnBook) btnBook.onclick = function() { renderSlotPickList(); showScreen('screenSlotPick'); };
          document.getElementById('trainerDetailSecondary').innerHTML = '';
        }).catch(function() {
          document.getElementById('trainerDetailSlots').innerHTML = '<div class="slots-title">Ближайшие слоты</div><div class="slots-empty">Не удалось загрузить слоты</div>';
          document.getElementById('trainerDetailActions').innerHTML = '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
          document.getElementById('trainerDetailSecondary').innerHTML = '';
        });
      }

      function renderSlotPickList() {
        var list = document.getElementById('slotPickList');
        var slots = state.slotsForTrainer || [];
        
        if (slots.length === 0) {
          list.innerHTML = '<div class="slots-empty">Нет слотов</div>';
          return;
        }
        
        // Группируем слоты по дням
        var byDay = {};
        slots.forEach(function(s, i) {
          var date = s.slot_date || '';
          if (!byDay[date]) byDay[date] = [];
          byDay[date].push({ slot: s, index: i });
        });
        
        var days = Object.keys(byDay).sort();
        var html = '';
        
        days.forEach(function(dateKey) {
          var daySlots = byDay[dateKey].sort(function(a, b) { 
            return (a.slot.start_time || '').localeCompare(b.slot.start_time || ''); 
          });
          
          // Форматируем заголовок дня
          var d = dateKey.split('-');
          if (d.length === 3) {
            var day = parseInt(d[2], 10);
            var month = parseInt(d[1], 10) - 1;
            var dateObj = new Date(d[0], month, day);
            var dayName = SLOT_DAYS[dateObj.getDay()];
            var dateStr = day + '.' + String(month + 1).padStart(2, '0') + ' (' + dayName + ')';
            html += '<div class="day-block"><div class="day-title">' + dateStr + '</div>';
          }
          
          daySlots.forEach(function(item) {
            var s = item.slot;
            var i = item.index;
            html += '<button type="button" class="slot-card" data-slot-index="' + i + '">' +
              '<span class="slot-card-body"><span class="slot-time">' + (s.start_time || '') + '–' + (s.end_time || '') + '</span>' +
              slotGroupSpotsPillHtml(s) + '</span><span>→</span></button>';
          });
          
          html += '</div>';
        });
        
        list.innerHTML = html;
        
        list.querySelectorAll('.slot-card').forEach(function(btn) {
          btn.onclick = function() {
            var i = parseInt(btn.dataset.slotIndex, 10);
            state.selectedSlot = state.slotsForTrainer[i];
            document.getElementById('bookingFormSlotLabel').textContent = 'Выбрано: ' + formatSlotSelectionSummary(state.selectedSlot);
            document.getElementById('bookingComment').value = '';
            refreshClientPhoneForBookingForm(function() {
              prefillBookingPhoneField();
              updateBookingVenueHint();
              updateBookingFormServiceAndTiers();
              showScreen('screenBookingForm');
            });
          };
        });
      }

      document.getElementById('btnSubmitBooking').onclick = function() {
        var slot = state.selectedSlot;
        if (!slot || !state.selectedTrainer) return;
        var phone = (document.getElementById('bookingPhone').value || '').trim();
        if (!phone || (phone.replace(/\D/g, '').length < 10)) {
          alert('Введите корректный телефон');
          return;
        }
        if (state.needsProfileName) {
          var fn = (document.getElementById('bookingFirstName') && document.getElementById('bookingFirstName').value || '').trim();
          if (!fn) {
            alert('Укажите имя');
            return;
          }
        }
        var btn = document.getElementById('btnSubmitBooking');
        btn.disabled = true;
        var initData = tg ? tg.initData : '';
        var headers = { 'Content-Type': 'application/json' };
        if (initData) headers['X-Telegram-Init-Data'] = initData;
        var body = { slot_id: slot.id, phone: phone, comment: (document.getElementById('bookingComment').value || '').trim() || null };
        if (state.needsProfileName) {
          body.first_name = (document.getElementById('bookingFirstName').value || '').trim();
          var ln = (document.getElementById('bookingLastName').value || '').trim();
          if (ln) body.last_name = ln;
        }
        if (state.serviceId != null) body.service_id = state.serviceId;
        if (state.catalogBookingPriceVariantId != null) {
          body.service_price_variant_id = state.catalogBookingPriceVariantId;
        }
        fetch('/api/webapp/client/booking', {
          method: 'POST',
          headers: headers,
          body: JSON.stringify(body)
        }).then(function(r) {
          return r.json().then(function(data) {
            if (r.ok && data.success) {
              var okMsg = '✅ <b>Вы записаны</b>.<br><br>Ожидайте подтверждения от тренера в боте.';
              if (data.used_primary_venue_for_online_booking) {
                okMsg += '<br><span style="color: var(--tg-theme-hint-color); font-size: 14px; display: inline-block; margin-top: 10px;">Запись создана на <strong>основную площадку</strong> тренера. Чтобы заниматься на площадке из вашего фильтра — оставьте заявку, тренер согласует место.</span>';
              }
              prefetch.firstPageKey = null;
              prefetch.firstPageData = null;
              clearCatalogSessionStorageCache();
              document.getElementById('successText').innerHTML = okMsg;
              showScreen('screenSuccess');
              getClientSession().then(function(session) {
                applySessionToState(session);
                updateBookingNameFieldsVisibility();
              }).catch(function() {});
            } else { alert(data.detail || 'Не удалось записаться'); }
            btn.disabled = false;
          });
        }).catch(function() {
          alert('Ошибка сети');
          btn.disabled = false;
        });
      };


      document.getElementById('btnCloseSuccess').onclick = closeApp;

      document.getElementById('backToCity').onclick = function() { showScreen('screenCity'); };
      document.getElementById('backToService').onclick = function() { showScreen('screenService'); };

      function updateRequestFormContext() {
        var titleEl = document.getElementById('requestFormTitle');
        var ctxEl = document.getElementById('requestFormContext');
        if (state.requestForTrainer) {
          titleEl.textContent = 'Заявка для ' + state.requestForTrainer.name;
          ctxEl.innerHTML = '<div class="context-line">Заявка придёт <strong>только этому тренеру</strong>.</div>';
        } else {
          titleEl.textContent = 'Общая заявка';
          ctxEl.innerHTML = '<div class="context-line">Любой тренер по вашему городу и услуге увидит заявку.</div>';
        }
      }

      function openLeaveRequestFromDetail() {
        var t = state.selectedTrainer;
        if (!t) return;
        var name = trainerName(t);
        state.requestForTrainer = { id: t.id, name: name };
        state.requestFormOpenedFrom = 'trainerDetail';
        document.getElementById('requestComment').value = '';
        updateRequestFormContext();
        getClientSession().then(function(session) {
          applySessionToState(session);
          updateRequestNameFieldsVisibility();
          showScreen('screenRequestForm');
        }).catch(function() {
          updateRequestNameFieldsVisibility();
          showScreen('screenRequestForm');
        });
      }

      document.getElementById('trainerDetailActions').addEventListener('click', function(e) {
        var action = e.target.closest('[data-action]');
        if (action && action.dataset.action === 'leave-request') {
          openLeaveRequestFromDetail();
          return;
        }
        if (action && action.dataset.action === 'buy-pass') {
          var t = state.selectedTrainer;
          if (!t) return;
          var name = trainerName(t);
          var base = window.location.pathname.replace(/[^/]+$/, '');
          var q = 'trainer_id=' + encodeURIComponent(t.id) + '&trainer_name=' + encodeURIComponent(name);
          if (state.cityId != null) q += '&city_id=' + encodeURIComponent(state.cityId);
          if (state.serviceId != null) q += '&service_id=' + encodeURIComponent(state.serviceId);
          if (state.arenaId != null) q += '&arena_id=' + encodeURIComponent(state.arenaId);
          if (state.offset != null) q += '&offset=' + encodeURIComponent(state.offset);
          window.location.href = base + 'client-buy-pass?' + q;
        }
      });
      function openGeneralRequestForm() {
        state.requestForTrainer = null;
        state.requestFormOpenedFrom = 'trainerList';
        document.getElementById('requestComment').value = '';
        updateRequestFormContext();
        getClientSession().then(function(session) {
          applySessionToState(session);
          updateRequestNameFieldsVisibility();
          showScreen('screenRequestForm');
        }).catch(function() {
          updateRequestNameFieldsVisibility();
          showScreen('screenRequestForm');
        });
      }

      function submitRequestFromForm(comment) {
        var btn = document.getElementById('btnSubmitRequestWithComment');
        btn.disabled = true;
        var initData = tg && tg.initData ? tg.initData : '';
        var headers = { 'Content-Type': 'application/json' };
        if (initData) headers['X-Telegram-Init-Data'] = initData;
        var body = {
          city_id: state.cityId,
          service_id: state.serviceId
        };
        if (state.requestForTrainer && state.requestForTrainer.id) body.trainer_id = state.requestForTrainer.id;
        var commentStr = comment != null && String(comment).trim() ? String(comment).trim() : null;
        if (commentStr) body.comment = commentStr;
        if (state.needsProfileName) {
          var rfn = (document.getElementById('requestFirstName') && document.getElementById('requestFirstName').value || '').trim();
          if (!rfn) {
            alert('Укажите имя');
            btn.disabled = false;
            return;
          }
          body.first_name = rfn;
          var rln = (document.getElementById('requestLastName') && document.getElementById('requestLastName').value || '').trim();
          if (rln) body.last_name = rln;
        }
        fetch('/api/webapp/client/request', {
          method: 'POST',
          headers: headers,
          body: JSON.stringify(body)
        }).then(function(r) {
          return r.json().then(function(data) {
            if (r.ok && data.success) {
              prefetch.firstPageKey = null;
              prefetch.firstPageData = null;
              clearCatalogSessionStorageCache();
              document.getElementById('successText').innerHTML =
                '✅ <b>Заявка отправлена</b>.<br><br>Когда появится подходящий тренер — напишем вам в боте.';
              showScreen('screenSuccess');
              getClientSession().then(function(session) {
                applySessionToState(session);
                updateRequestNameFieldsVisibility();
              }).catch(function() {});
            } else {
              alert(data.detail || 'Не удалось отправить заявку. Попробуйте ещё раз.');
            }
            btn.disabled = false;
          });
        }).catch(function() {
          alert('Ошибка сети. Проверьте интернет и попробуйте снова.');
          btn.disabled = false;
        });
      }
      document.getElementById('btnSubmitRequestWithComment').onclick = function() {
        var text = document.getElementById('requestComment').value;
        submitRequestFromForm(text);
      };
      document.getElementById('btnPickTrainer').onclick = function() {
        if (!state.cityId || !state.serviceId) return;
        state.returnToSummary = true;
        state.offset = 0;
        loadCatalogList();
        showScreen('screenTrainers');
      };
      document.getElementById('tabCatalog').onclick = function() { switchTab('catalog'); };
      document.getElementById('tabMyTrainer').onclick = function() { switchTab('my_trainer'); };
      document.getElementById('btnOpenMyTrainerCard').onclick = openMyTrainerCard;
      document.getElementById('btnMyTrainerPick').onclick = function() {
        if (state.cityId && state.serviceId) {
          state.returnToSummary = true;
          state.offset = 0;
          loadCatalogList();
          showScreen('screenTrainers');
        } else {
          switchTab('catalog');
        }
      };
      document.getElementById('tabCatalogFromDetail').onclick = function() {
        renderSummary();
        switchTab('catalog');
        showScreen('screenSummary');
      };
      document.getElementById('tabMyTrainerFromDetail').onclick = function() { /* already on my trainer card */ };

      function goBackToSummary() {
        state.returnToSummary = false;
        document.getElementById('backFromCityToSummary').style.display = 'none';
        document.getElementById('backFromServiceToSummary').style.display = 'none';
        document.getElementById('backFromArenaToSummary').style.display = 'none';
        var backSvc = document.getElementById('backToService');
        if (backSvc) backSvc.style.display = 'block';
        var backCity = document.getElementById('backToCity');
        if (backCity) backCity.style.display = 'block';
        // showScreen('screenSummary') runs switchTab(state.activeTab); my_trainer would call openMyTrainerCard() and leave the summary empty.
        state.activeTab = 'catalog';
        renderSummary();
        showScreen('screenSummary');
      }
      document.getElementById('backFromCityToSummary').onclick = goBackToSummary;
      document.getElementById('backFromServiceToSummary').onclick = goBackToSummary;
      document.getElementById('backFromArenaToSummary').onclick = goBackToSummary;

      getClientSession()
        .then(function(session) {
          applySessionToState(session);
          updateBookingNameFieldsVisibility();
          updateRequestNameFieldsVisibility();
          var returnCtx = (function() {
            var p = new URLSearchParams(window.location.search || '');
            var tid = p.get('trainer_id');
            if (!tid) return null;
            var id = parseInt(tid, 10);
            if (!id) return null;
            return { trainer_id: id, city_id: p.get('city_id'), service_id: p.get('service_id'), arena_id: p.get('arena_id'), offset: p.get('offset') };
          })();
          if (returnCtx) {
            if (returnCtx.city_id != null) state.cityId = parseInt(returnCtx.city_id, 10) || null;
            if (returnCtx.service_id != null) state.serviceId = parseInt(returnCtx.service_id, 10) || null;
            if (returnCtx.arena_id != null) state.arenaId = returnCtx.arena_id === '' ? null : (parseInt(returnCtx.arena_id, 10) || null);
            if (returnCtx.offset != null) state.offset = Math.max(0, parseInt(returnCtx.offset, 10) || 0);
          }
          function showInitialScreen() {
            if (state.cityId && state.serviceId) {
              prefetchFirstPageIfNeeded();
              renderSummary();
              showScreen('screenSummary');
              switchTab(state.activeTab);
              loadCatalogList();
            } else {
              loadCities();
              showScreen('screenCity');
            }
          }
          /* Deep link ?trainer_id= — открыть карточку напрямую (в т.ч. возврат из book.html) */
          if (returnCtx && returnCtx.trainer_id) {
            loadTrainerById(returnCtx.trainer_id).then(function(t) {
              if (t) {
                state.selectedTrainer = t;
                state.trainerName = trainerName(t);
                renderTrainerDetail();
                showScreen('screenTrainerDetail');
                return;
              }
              if (state.trainerId) {
                state.openedFromMyTrainerTab = true;
                loadTrainerById(state.trainerId).then(function(t2) {
                  if (t2) {
                    state.selectedTrainer = t2;
                    state.trainerName = trainerName(t2);
                    renderTrainerDetail();
                    showScreen('screenTrainerDetail');
                  } else {
                    state.trainerId = null;
                    state.trainerName = '';
                    showInitialScreen();
                  }
                }).catch(function() {
                  state.trainerId = null;
                  state.trainerName = '';
                  showInitialScreen();
                });
                return;
              }
              showInitialScreen();
            }).catch(function() {
              if (state.trainerId) {
                state.openedFromMyTrainerTab = true;
                loadTrainerById(state.trainerId).then(function(t2) {
                  if (t2) {
                    state.selectedTrainer = t2;
                    state.trainerName = trainerName(t2);
                    renderTrainerDetail();
                    showScreen('screenTrainerDetail');
                  } else {
                    state.trainerId = null;
                    state.trainerName = '';
                    showInitialScreen();
                  }
                }).catch(function() {
                  state.trainerId = null;
                  state.trainerName = '';
                  showInitialScreen();
                });
                return;
              }
              showInitialScreen();
            });
            return;
          }
          if (state.trainerId) {
            state.openedFromMyTrainerTab = true;
            loadTrainerById(state.trainerId).then(function(t) {
              if (t) {
                state.selectedTrainer = t;
                state.trainerName = trainerName(t);
                renderTrainerDetail();
                showScreen('screenTrainerDetail');
              } else {
                state.trainerId = null;
                state.trainerName = '';
                showInitialScreen();
              }
            }).catch(function() {
              state.trainerId = null;
              state.trainerName = '';
              showInitialScreen();
            });
            return;
          }
          showInitialScreen();
        })
        .catch(function() {
          loadCities();
          showScreen('screenCity');
        });

      var catalogVisibilityDebounceTimer = null;
      document.addEventListener('visibilitychange', function() {
        if (document.hidden) return;
        if (catalogVisibilityDebounceTimer) clearTimeout(catalogVisibilityDebounceTimer);
        catalogVisibilityDebounceTimer = setTimeout(function() {
          catalogVisibilityDebounceTimer = null;
          var sum = document.getElementById('screenSummary');
          if (!sum || !sum.classList.contains('active')) return;
          if (state.activeTab !== 'catalog') return;
          getClientSession().then(function(session) {
            applySessionToState(session);
            if (state.cityId && state.serviceId) {
              loadCatalogList({ silent: true });
            }
          }).catch(function() {});
        }, 400);
      });

      // Keep first-page prefetch hot while user is on summary and updates filters.
      document.addEventListener('click', function(e) {
        var actionBtn = e.target && e.target.closest && e.target.closest('#summaryRows .summary-row-clickable, #tabCatalog, #tabMyTrainer');
        if (actionBtn) {
          setTimeout(prefetchFirstPageIfNeeded, 0);
        }
      });
      
      // Функция для показа отзывов тренера
      window.showTrainerReviews = function(trainerId) {
        var modal = document.getElementById('reviewsModal');
        var modalBody = document.getElementById('reviewsModalBody');
        var modalTitle = document.getElementById('reviewsModalTitle');
        
        modalTitle.textContent = 'Отзывы о тренере';
        modalBody.innerHTML = '<div class="reviews-loading">Загрузка отзывов...</div>';
        modal.classList.add('show');
        
        // Публичный список отзывов (см. GET /api/public/trainers/{id}/reviews — items, review_text)
        fetch('/api/public/trainers/' + encodeURIComponent(trainerId) + '/reviews', { cache: 'no-store' })
          .then(function(res) {
            return res.json().then(function(data) {
              if (!res.ok) throw new Error((data && data.detail) || res.statusText);
              return data;
            });
          })
          .then(function(data) {
            var reviews = data.items || [];
            if (reviews.length === 0) {
              modalBody.innerHTML = '<div class="reviews-empty">У этого тренера пока нет отзывов</div>';
              return;
            }
            
            var html = '';
            reviews.forEach(function(review) {
              html += '<div class="review-item">';
              html += '<div class="review-rating">⭐ ' + review.rating + '/5</div>';
              var text = review.review_text || review.comment;
              if (text) {
                html += '<div class="review-text">' + escapeHtml(text) + '</div>';
              }
              if (review.created_at) {
                var date = new Date(review.created_at).toLocaleDateString('ru-RU');
                html += '<div class="review-date">' + date + '</div>';
              }
              html += '</div>';
            });
            modalBody.innerHTML = html;
          })
          .catch(function() {
            modalBody.innerHTML = '<div class="reviews-empty">Не удалось загрузить отзывы</div>';
          });
      };
      
      // Закрытие модального окна
      window.closeReviewsModal = function() {
        document.getElementById('reviewsModal').classList.remove('show');
      };
    })();
