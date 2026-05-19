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
        // Canonical multi-arena filter for trainer *list*. arenaId/arenaName are derived for
        // legacy single-arena API (session POST, back-links from book.html).
        arenaIds: [],
        arenaNames: [],
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
        /** GET /client/session?for_trainer_id → tier hint for booking_context service when it matches effective service. */
        bookingContextServicePriceVariantId: null,
        bookingContextServiceId: null,
        /** Last booking by created_at (trainer+client): align tier when repeating same service (catalog filter / slot). */
        lastCreatedBookingServiceId: null,
        lastCreatedBookingPriceVariantId: null,
        /** Per slot selection — POST /client/booking Idempotency-Key (retry after dropped response). */
        catalogBookingIdempotencyKey: null,
        slotsForTrainer: [],
        /** Subset of trainer arenas used as GET /client/slots arena_ids= (OR). Empty ⇒ all venues. */
        trainerSlotsArenaIds: [],
        selectedSlot: null,
        returnToSummary: false,
        requestForTrainer: null,
        requestFormOpenedFrom: null,
        activeTab: 'catalog',
        openedFromMyTrainerTab: false,
        /** trainers | groups — список после выбора города/услуги/арены */
        catalogMode: 'trainers',
        /** Quick scenario chip (stub); maps to presets later. */
        catalogScenarioStub: null,
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
        },
        /** Edge state map: trainerIdStr → {is_saved, is_primary, completed_count} */
        trainerEdges: {},
        /** From GET /client/trainer-edges ``primary`` — same priority as client hub (not legacy session row). */
        hubPrimaryTrainerIdFromEdges: null,
        /** From GET /client/session — last booking service hint for suggested_service_for_trainer_id only. */
        suggestedServiceForTrainer: null,
        suggestedServiceForTrainerId: null
      };

      /**
       * BFCache (Telegram / mobile WebKit): leaving catalog for hub then opening
       * catalog?trainer_id=… can restore stale in-memory catalog UI while the URL
       * already encodes the hub trainer — scripts do not re-run, so deep-link bootstrap never fires.
       */
      window.addEventListener('pageshow', function(ev) {
        if (!ev.persisted) return;
        try {
          var p = new URLSearchParams(window.location.search || '');
          if (p.get('trainer_id') || p.get('action') === 'book') {
            window.location.reload();
          }
        } catch (eBf) { /* noop */ }
      });

      /**
       * Single source of truth for arena selection in the catalog list flow.
       */
      function setArenaSelection(ids, names) {
        var safeIds = Array.isArray(ids) ? ids.filter(function(v) { return v != null; }).map(function(v) { return parseInt(v, 10); }).filter(function(v) { return !isNaN(v); }) : [];
        var safeNames = Array.isArray(names) ? names.slice(0, safeIds.length) : [];
        while (safeNames.length < safeIds.length) safeNames.push('Арена');
        state.arenaIds = safeIds;
        state.arenaNames = safeNames;
        if (safeIds.length === 1) {
          state.arenaId = safeIds[0];
          state.arenaName = safeNames[0] || 'Арена';
        } else {
          state.arenaId = null;
          state.arenaName = safeIds.length === 0 ? 'Любая' : (safeIds.length + ' арены');
        }
        // Card `/client/slots` filter stays on `trainerSlotsArenaIds`; do not mutate it here.
      }
      function clearArenaSelection() {
        setArenaSelection([], []);
      }
      /** Display label for the summary row: handles 0 / 1 / 2 / 3+ cases gracefully. */
      function arenaSummaryLabel() {
        var n = state.arenaIds.length;
        if (n === 0) return 'Любая';
        if (n === 1) return state.arenaNames[0] || 'Арена';
        if (n === 2) return state.arenaNames.join(' · ');
        return state.arenaNames.slice(0, 2).join(' · ') + ' и ещё ' + (n - 2);
      }
      /** Stable cache fragment for arena selection (sorted to ignore selection order). */
      function arenaIdsCacheKey() {
        if (!state.arenaIds.length) return '0';
        return state.arenaIds.slice().sort(function(a, b) { return a - b; }).join('-');
      }

      function primaryVenueLabel(t) {
        if (!t) return '';
        if (t.primary_arena_name && String(t.primary_arena_name).trim()) return String(t.primary_arena_name).trim();
        var ids = t.arena_ids || [];
        var names = t.arena_names || [];
        var idx = ids.indexOf(t.primary_arena_id);
        if (idx >= 0 && names[idx]) return names[idx];
        return '';
      }
      function buildSlotVenueBlockHtml(slot) {
        if (!slot) return '';
        var name = (slot.arena_name && String(slot.arena_name).trim()) || '';
        var addr = (slot.arena_address && String(slot.arena_address).trim()) || '';
        var city = (slot.arena_city_name && String(slot.arena_city_name).trim()) || '';
        var mapLink = (slot.map_link && String(slot.map_link).trim()) || '';
        var parts = [];
        if (name || addr || city) {
          var loc = [name, addr].filter(Boolean).join(' — ');
          if (city) loc = loc ? loc + ' · ' + city : city;
          parts.push('<div class="booking-venue-slot-title"><strong>Где</strong></div>');
          parts.push('<div class="booking-venue-slot-lines">' + escapeHtml(loc) + '</div>');
        } else {
          var fb = primaryVenueLabel(state.selectedTrainer);
          if (fb) {
            parts.push(
              '<div class="booking-venue-slot-lines">Площадка: <strong>' +
                escapeHtml(fb) +
                '</strong>. Адрес пришлёт тренер после подтверждения или смотрите в «Мои записи».</div>'
            );
          }
        }
        if (mapLink && /^https:\/\//i.test(mapLink)) {
          parts.push(
            '<div class="booking-venue-slot-map"><a href="' +
              escapeHtml(mapLink) +
              '" target="_blank" rel="noopener noreferrer">Открыть на карте</a></div>'
          );
        }
        return parts.length ? '<div class="booking-venue-slot">' + parts.join('') + '</div>' : '';
      }

      function updateBookingVenueHint() {
        var el = document.getElementById('bookingVenueHint');
        if (!el) return;
        var slot = state.selectedSlot;
        var slotHtml = buildSlotVenueBlockHtml(slot);
        var label = primaryVenueLabel(state.selectedTrainer);
        var chunks = [];
        if (slotHtml) chunks.push(slotHtml);
        else if (label) {
          chunks.push('<div class="booking-venue-slot-lines">Площадка: ' + escapeHtml(label) + '</div>');
        }
        el.className = 'booking-venue-hint';
        if (!chunks.length) {
          el.style.display = 'none';
          el.innerHTML = '';
          return;
        }
        el.style.display = 'block';
        el.innerHTML = chunks.join('');
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

      function newCatalogBookingIdempotencyKey() {
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
          return crypto.randomUUID();
        }
        return 'bk-' + Date.now() + '-' + Math.random().toString(36).slice(2, 11);
      }

      function assignCatalogBookingIdempotencyKeyForSlot() {
        state.catalogBookingIdempotencyKey = newCatalogBookingIdempotencyKey();
      }

      /** Avoid false «network error» when res.ok but body is not JSON or parse fails. */
      function catalogParseBookingJsonResponse(text) {
        try {
          return JSON.parse(text || 'null');
        } catch (e) {
          return null;
        }
      }

      /** Card / catalog filter wins over slot.snapshot: API may tag slots with another service_id while times are shared. */
      function catalogEffectiveServiceIdForBooking() {
        var slot = state.selectedSlot;
        var t = state.selectedTrainer;
        var services = (t && t.services) ? t.services : [];
        var allowed = {};
        var i;
        for (i = 0; i < services.length; i++) {
          var id = Number(services[i].service_id);
          if (!isNaN(id) && id > 0) allowed[id] = true;
        }
        if (state.serviceId != null) {
          var cur = Number(state.serviceId);
          if (!isNaN(cur) && cur > 0 && allowed[cur]) return cur;
        }
        if (slot && slot.service_id != null) {
          var ps = Number(slot.service_id);
          if (!isNaN(ps) && ps > 0 && allowed[ps]) return ps;
        }
        return null;
      }

      function catalogServiceDisplayNameForId(serviceId) {
        var t = state.selectedTrainer;
        var services = (t && t.services) ? t.services : [];
        var sidNum = Number(serviceId);
        var i;
        for (i = 0; i < services.length; i++) {
          if (Number(services[i].service_id) === sidNum) {
            return String(services[i].service_name || '').trim();
          }
        }
        return (state.serviceName || '').trim();
      }

      function getTiersForCatalogBooking() {
        var t = state.selectedTrainer;
        if (!t || !t.services) return [];
        var sid = catalogEffectiveServiceIdForBooking();
        if (sid == null) return [];
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

      /** Prefer last-created-booking tier, then booking_context tier, only when IDs match effective catalog service. */
      function catalogPriceVariantHintForEffectiveService(effSid) {
        if (effSid == null) return null;
        var e = Number(effSid);
        if (!isFinite(e) || e <= 0) return null;
        var lcSid = state.lastCreatedBookingServiceId;
        var lcVid = state.lastCreatedBookingPriceVariantId;
        if (lcSid != null && Number(lcSid) === e && lcVid != null) {
          var v0 = Number(lcVid);
          if (isFinite(v0) && v0 > 0) return v0;
        }
        var bcSid = state.bookingContextServiceId;
        var bcVid = state.bookingContextServicePriceVariantId;
        if (bcSid != null && Number(bcSid) === e && bcVid != null) {
          var v1 = Number(bcVid);
          if (isFinite(v1) && v1 > 0) return v1;
        }
        return null;
      }

      /** Услуга из фильтра + выбор тарифа при нескольких ценах (строгий режим API). Групповые слоты — без выбора тира. */
      function updateBookingFormServiceAndTiers() {
        var svcEl = document.getElementById('bookingFormServiceLine');
        var block = document.getElementById('bookingPriceTierBlockCatalog');
        var host = document.getElementById('bookingPriceTierRadiosCatalog');
        state.catalogBookingPriceVariantId = null;
        var effSid = catalogEffectiveServiceIdForBooking();
        var nm = effSid != null ? catalogServiceDisplayNameForId(effSid) : (state.serviceName || '').trim();
        if (svcEl) {
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
        var hintedVid = catalogPriceVariantHintForEffectiveService(effSid);
        var hintOk =
          hintedVid != null &&
          tiers.some(function(tier) {
            return Number(tier.id) === Number(hintedVid);
          });
        var preferredId = hintOk ? Number(hintedVid) : null;
        tiers.forEach(function(tier) {
          var lab = document.createElement('label');
          var inp = document.createElement('input');
          inp.type = 'radio';
          inp.name = 'catalogPriceTierChoice';
          inp.value = String(tier.id);
          var pb = tier.price_byn;
          var priceNum = pb === Math.floor(pb) ? String(pb) : Number(pb).toFixed(2);
          var priceHtml = escapeHtml(priceNum) + ' BYN';
          lab.appendChild(inp);
          var tierTxt = document.createElement('span');
          tierTxt.className = 'tier-radio-text';
          tierTxt.innerHTML = escapeHtml(catalogTierLabelRu(tier)) + ' — ' + priceHtml;
          lab.appendChild(tierTxt);
          inp.addEventListener('change', function() {
            state.catalogBookingPriceVariantId = parseInt(inp.value, 10);
          });
          host.appendChild(lab);
        });
        var pick =
          preferredId != null
            ? host.querySelector('input[name="catalogPriceTierChoice"][value="' + preferredId + '"]')
            : null;
        if (pick) {
          pick.checked = true;
          state.catalogBookingPriceVariantId = preferredId;
        } else {
          var first = host.querySelector('input');
          if (first) {
            first.checked = true;
            state.catalogBookingPriceVariantId = parseInt(first.value, 10);
          }
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
        // City / service / arena: header «Назад» = «К выбору» when editing from summary (returnToSummary).
        if (sid === 'screenCity' || sid === 'screenService' || sid === 'screenArena') {
          var showPickerBack = state.returnToSummary || canBrowserGoBack();
          btn.hidden = !showPickerBack;
          btn.onclick = function() {
            if (state.returnToSummary) {
              goBackToSummary();
            } else {
              window.history.back();
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
        // Single arena → legacy arena_id (kept for proxy/CDN cache compat); multi → arena_ids CSV.
        if (state.arenaIds.length === 1) params.arena_id = state.arenaIds[0];
        else if (state.arenaIds.length > 1) params.arena_ids = state.arenaIds.join(',');
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
        if (state.arenaIds.length === 1) params.arena_id = state.arenaIds[0];
        else if (state.arenaIds.length > 1) params.arena_ids = state.arenaIds.join(',');
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
        return [mode, state.cityId || 0, state.serviceId || 0, arenaIdsCacheKey(), state.limit || 10, dayPart, timePart].join(':');
      }

      function syncTimeFilterPanelAria() {
        var panel = document.getElementById('timeFilters');
        var header = document.getElementById('timeFiltersHeader');
        if (!panel || !header) return;
        var open = panel.classList.contains('expanded');
        header.setAttribute('aria-expanded', open ? 'true' : 'false');
      }

      function setTimeFilterPanelExpanded(expanded) {
        var panel = document.getElementById('timeFilters');
        if (!panel) return;
        panel.classList.toggle('expanded', !!expanded);
        syncTimeFilterPanelAria();
      }

      function toggleFilterPanel() {
        var panel = document.getElementById('timeFilters');
        if (panel) {
          panel.classList.toggle('expanded');
          syncTimeFilterPanelAria();
        }
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
              : 'Свободные слоты на 14 дней';
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

        var filterHeader = document.getElementById('timeFiltersHeader');
        if (filterHeader) {
          filterHeader.addEventListener('click', toggleFilterPanel);
          filterHeader.addEventListener('keydown', function(ev) {
            if (ev.key === 'Enter' || ev.key === ' ') {
              ev.preventDefault();
              toggleFilterPanel();
            }
          });
        }
        syncTimeFilterPanelAria();
        
        // Day filters
        document.querySelectorAll('#dayFilters .filter-chip').forEach(function(chip) {
          chip.addEventListener('click', function() {
            setTimeFilterPanelExpanded(true);
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
            setTimeFilterPanelExpanded(true);
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

      /** Compact offer count for service rows (N тренер/тренера/тренеров in city). */
      function formatServiceOfferCount(n) {
        n = n | 0;
        if (n <= 0) return 'Пока нет тренеров';
        var mod10 = n % 10;
        var mod100 = n % 100;
        if (mod10 === 1 && mod100 !== 11) return n + ' тренер';
        if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return n + ' тренера';
        return n + ' тренеров';
      }

      function lookupServiceTrainerCount(serviceId, cityId) {
        if (!cityId || serviceId == null) return null;
        var items = _catalogServicesCacheByCity[catalogServicesCacheKey(cityId)] || [];
        for (var i = 0; i < items.length; i++) {
          if (items[i].id === serviceId) {
            return items[i].trainer_count != null ? items[i].trainer_count | 0 : 0;
          }
        }
        return null;
      }

      function patchSummaryServiceOfferMeta() {
        var tile = document.querySelector('#summaryRows .catalog-filter-tile[data-action="service"]');
        if (!tile || !state.cityId) return;
        var body = tile.querySelector('.catalog-filter-tile__body');
        if (!body) return;
        var metaEl = body.querySelector('.catalog-filter-tile__meta');
        var label = '';
        if (state.serviceId) {
          var c = lookupServiceTrainerCount(state.serviceId, state.cityId);
          if (c !== null) label = formatServiceOfferCount(c);
        }
        if (!label) {
          if (metaEl) metaEl.remove();
          return;
        }
        if (!metaEl) {
          metaEl = document.createElement('span');
          metaEl.className = 'catalog-filter-tile__meta';
          body.appendChild(metaEl);
        }
        metaEl.textContent = label;
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
          reconcileCatalogServiceWithTrainerAsync(state.selectedTrainer).then(function() {
            initTrainerSlotsArenaFilterFromCatalog(state.selectedTrainer);
            renderTrainerDetail();
            showScreen('screenTrainerDetail');
          });
        }).catch(function() {
          state.selectedTrainer = t;
          reconcileCatalogServiceWithTrainerAsync(t).then(function() {
            initTrainerSlotsArenaFilterFromCatalog(t);
            renderTrainerDetail();
            showScreen('screenTrainerDetail');
          });
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
        return fetch('/api/public' + path + q, { cache: 'no-store' }).then(function(r) {
          return r.json().then(function(data) {
            if (!r.ok) {
              var detail = (data && data.detail) ? data.detail : r.statusText;
              throw new Error(typeof detail === 'string' ? detail : 'HTTP ' + r.status);
            }
            return data;
          });
        });
      }
      /** When trainer is «мой / основной» but not public-catalog-visible, public API 404s — authenticated fallback. */
      function loadTrainerByIdViaWebappFallback(trainerId) {
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return Promise.resolve(null);
        return fetch('/api/webapp/client/catalog-trainer/' + encodeURIComponent(trainerId), {
          headers: { 'X-Telegram-Init-Data': initData },
          cache: 'no-store',
        })
          .then(function(r) {
            if (r.status === 404) return null;
            if (!r.ok) throw new Error(r.statusText);
            return r.json();
          })
          .catch(function() {
            return null;
          });
      }

      function loadTrainerById(trainerId) {
        return fetch('/api/public/trainers/' + encodeURIComponent(trainerId), { cache: 'no-store' })
          .then(function(r) {
            if (r.status === 404) {
              return loadTrainerByIdViaWebappFallback(trainerId);
            }
            if (!r.ok) throw new Error(r.statusText);
            return r.json();
          })
          .catch(function() {
            return loadTrainerByIdViaWebappFallback(trainerId);
          });
      }
      function switchTab(tab) {
        state.activeTab = tab;
        document.querySelectorAll('.catalog-tabs .tab-btn').forEach(function(btn) {
          btn.classList.toggle('active', btn.dataset.tab === tab);
        });
        document.getElementById('catalogTabPanel').classList.toggle('active', tab === 'catalog');
        document.getElementById('myTrainerTabPanel').classList.toggle('active', tab === 'my_trainer');
        if (tab === 'catalog') {
          document.getElementById('myTrainerLoading').style.display = 'none';
        }
        if (tab === 'my_trainer') {
          /* trainerId may be set from hub primary edges without trainerName — still open card (avoid empty flash). */
          var eff = state.trainerId;
          if (eff == null || eff === '' || !(Number(eff) > 0)) {
            eff = resolveCatalogAutoTrainerIdFromEdges();
          }
          var tidNum = eff != null ? Number(eff) : NaN;
          if (!isNaN(tidNum) && tidNum > 0) {
            state.trainerId = tidNum;
            document.getElementById('myTrainerEmpty').style.display = 'none';
            openMyTrainerCard();
            return;
          }
          document.getElementById('myTrainerLoading').style.display = 'none';
          document.getElementById('myTrainerEmpty').style.display = 'block';
          document.getElementById('myTrainerCardShort').style.display = 'none';
        }
      }
      function openMyTrainerCard() {
        if (!state.trainerId) return;
        document.getElementById('myTrainerEmpty').style.display = 'none';
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
          reconcileCatalogServiceWithTrainerAsync(t).then(function() {
            initTrainerSlotsArenaFilterFromCatalog(t);
            renderTrainerDetail();
            showScreen('screenTrainerDetail');
          });
        }).catch(function() {
          document.getElementById('myTrainerLoading').style.display = 'none';
          document.getElementById('myTrainerCardShort').style.display = 'block';
        });
      }

      /**
       * @param {{ forTrainerId?: number }} [opts] Pass forTrainerId to align suggested_service_* with that card.
       */
      function getClientSession(opts) {
        var q = '';
        if (opts && opts.forTrainerId != null && opts.forTrainerId !== '') {
          q = '?for_trainer_id=' + encodeURIComponent(opts.forTrainerId);
        }
        var initData = tg && tg.initData ? tg.initData : '';
        var headers = { 'Content-Type': 'application/json' };
        if (initData) headers['X-Telegram-Init-Data'] = initData;
        return fetch('/api/webapp/client/session' + q, { headers: headers, cache: 'no-store' }).then(function(r) {
          if (!r.ok) throw new Error(r.statusText);
          return r.json();
        });
      }

      /**
       * If catalog session service is not in this trainer's offers, replace it using server hint or first offer;
       * persists client session so book.html and slots see a consistent service_id.
       */
      function reconcileCatalogServiceWithTrainerAsync(trainer) {
        return new Promise(function(resolve) {
          if (!trainer || trainer.id == null) {
            resolve();
            return;
          }
          var services = trainer.services || [];
          if (!services.length) {
            resolve();
            return;
          }
          function buildAllowed() {
            var m = {};
            services.forEach(function(s) {
              var id = s.service_id != null ? Number(s.service_id) : NaN;
              if (!isNaN(id)) m[id] = s;
            });
            return m;
          }
          var allowed = buildAllowed();
          function applyPick(sid, doPersist) {
            var num = Number(sid);
            if (isNaN(num) || !allowed[num]) return false;
            state.serviceId = num;
            state.serviceName = String(allowed[num].service_name || '').trim();
            if (doPersist && state.cityId && state.serviceId) persistTrainerSelection(trainer.id);
            return true;
          }
          var cur = state.serviceId != null ? Number(state.serviceId) : NaN;
          if (!isNaN(cur) && allowed[cur]) {
            state.serviceName = String(allowed[cur].service_name || state.serviceName || '').trim();
            if (state.cityId && state.serviceId) persistCatalogFilters(trainer.id);
            resolve();
            return;
          }
          var locSugg = state.suggestedServiceForTrainer;
          var locCtx = state.suggestedServiceForTrainerId;
          if (
            locSugg != null &&
            !isNaN(Number(locSugg)) &&
            locCtx != null &&
            !isNaN(Number(locCtx)) &&
            Number(locCtx) === Number(trainer.id) &&
            applyPick(locSugg, true)
          ) {
            resolve();
            return;
          }
          getClientSession({ forTrainerId: trainer.id })
            .then(function(sess) {
              if (sess) {
                var st = sess.suggested_service_for_trainer_id;
                var sidRaw = sess.suggested_service_id_for_trainer;
                state.suggestedServiceForTrainerId =
                  st != null && st !== '' && !isNaN(Number(st)) ? Number(st) : null;
                state.suggestedServiceForTrainer =
                  sidRaw != null && sidRaw !== '' && !isNaN(Number(sidRaw)) ? Number(sidRaw) : null;
                if (
                  state.suggestedServiceForTrainer != null &&
                  state.suggestedServiceForTrainerId != null &&
                  Number(state.suggestedServiceForTrainerId) === Number(trainer.id) &&
                  applyPick(state.suggestedServiceForTrainer, true)
                ) {
                  resolve();
                  return;
                }
              }
              var pick0 = services[0];
              var zid = pick0 && pick0.service_id != null ? Number(pick0.service_id) : NaN;
              if (!isNaN(zid)) {
                state.serviceId = zid;
                state.serviceName = String(pick0.service_name || '').trim();
                if (state.cityId && state.serviceId) persistTrainerSelection(trainer.id);
              }
              resolve();
            })
            .catch(function() {
              var pick0 = services[0];
              if (pick0 && pick0.service_id != null) {
                state.serviceId = Number(pick0.service_id);
                state.serviceName = String(pick0.service_name || '').trim();
                if (state.cityId && state.serviceId) persistTrainerSelection(trainer.id);
              }
              resolve();
            });
        });
      }

      /** Load all client↔trainer edges once on init; stores into state.trainerEdges keyed by trainer_id. */
      function loadTrainerEdges() {
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return Promise.resolve();
        var headers = { 'X-Telegram-Init-Data': initData };
        return fetch('/api/webapp/client/trainer-edges', { headers: headers })
          .then(function(r) { return r.ok ? r.json() : null; })
          .then(function(data) {
            if (!data || !Array.isArray(data.all)) return;
            state.trainerEdges = {};
            data.all.forEach(function(e) {
              state.trainerEdges[String(e.trainer_id)] = e;
            });
            state.hubPrimaryTrainerIdFromEdges = null;
            if (data.primary && data.primary.trainer_id != null) {
              var pt = Number(data.primary.trainer_id);
              if (!isNaN(pt) && pt > 0) {
                state.hubPrimaryTrainerIdFromEdges = pt;
                var dn = data.primary.trainer_display_name;
                if (dn != null && String(dn).trim()) state.trainerName = String(dn).trim();
              }
            }
          })
          .catch(function() { /* non-critical — save button falls back to unknown state */ });
      }

      /**
       * Primary trainer id from GET /client/trainer-edges ``primary`` only (strict server tiers).
       * No client-side fallback to legacy ``is_primary`` — avoids contradicting hub / «Мои тренеры».
       */
      function resolveCatalogAutoTrainerIdFromEdges() {
        if (state.hubPrimaryTrainerIdFromEdges != null) {
          var h = Number(state.hubPrimaryTrainerIdFromEdges);
          if (!isNaN(h) && h > 0) return h;
        }
        return null;
      }

      /**
       * Show a brief toast notification at the bottom of the screen.
       * Auto-dismisses after `durationMs` (default 2400ms). Non-blocking.
       */
      var _toastTimer = null;
      function showToast(message, durationMs) {
        var dur = durationMs || 2400;
        var el = document.getElementById('appToast');
        if (!el) {
          el = document.createElement('div');
          el.id = 'appToast';
          el.className = 'app-toast';
          document.body.appendChild(el);
        }
        el.textContent = message;
        el.classList.add('app-toast--visible');
        if (_toastTimer) clearTimeout(_toastTimer);
        _toastTimer = setTimeout(function() {
          el.classList.remove('app-toast--visible');
        }, dur);
      }

      /** Toggle save state for current trainer. Optimistic UI update then API call. */
      function toggleSaveTrainer(trainerId) {
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return;
        var key = String(trainerId);
        var edge = state.trainerEdges[key] || {};
        var nowSaved = !!edge.is_saved;
        var nextSaved = !nowSaved;

        // Optimistic update
        state.trainerEdges[key] = Object.assign({}, edge, { is_saved: nextSaved });
        _updateSaveButtonUI(trainerId, nextSaved);

        var headers = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData };
        var method = nextSaved ? 'POST' : 'DELETE';
        var url = nextSaved
          ? '/api/webapp/client/trainer-edges/save'
          : '/api/webapp/client/trainer-edges/save/' + trainerId;
        var body = nextSaved
          ? JSON.stringify(function() {
              var payload = { trainer_id: trainerId };
              if (state.serviceId != null) {
                var ns = Number(state.serviceId);
                if (!isNaN(ns)) payload.catalog_service_id = ns;
              }
              return payload;
            }())
          : undefined;
        fetch(url, { method: method, headers: headers, body: body })
          .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function(data) {
            if (data && data.edge) {
              state.trainerEdges[key] = data.edge;
              _updateSaveButtonUI(trainerId, !!data.edge.is_saved);
            }
          })
          .catch(function() {
            // Rollback optimistic on error
            state.trainerEdges[key] = Object.assign({}, edge, { is_saved: nowSaved });
            _updateSaveButtonUI(trainerId, nowSaved);
          });
      }

      function _updateSaveButtonUI(trainerId, isSaved) {
        var chip = document.getElementById('chipSaveTrainer');
        if (!chip || parseInt(chip.dataset.trainerId, 10) !== trainerId) return;
        chip.querySelector('span').textContent = isSaved ? 'Сохранено' : 'Сохранить';
        chip.querySelector('.chip-icon').textContent = isSaved ? '❤️' : '🤍';
        chip.classList.toggle('is-active', isSaved);
      }

      function _updateNotifyChipUI(trainerId, isNotify) {
        var chip = document.getElementById('chipNotifySlots');
        if (!chip || parseInt(chip.dataset.trainerId, 10) !== trainerId) return;
        chip.querySelector('span').textContent = isNotify ? 'Подписан' : 'Напомнить';
        chip.querySelector('.chip-icon').textContent = isNotify ? '🔔' : '🔕';
        chip.classList.toggle('is-active', isNotify);
        chip.classList.toggle('wants-attention', !isNotify);

        var hint = document.getElementById('chipsContextHint');
        if (hint) {
          var noSlotsCtx = chip.dataset.noSlotsContext === '1';
          if (isNotify) {
            hint.textContent = '🔔 Уведомим, когда появятся свободные окна';
          } else if (noSlotsCtx) {
            hint.textContent = 'Нет слотов — нажмите 🔕, чтобы получить уведомление';
          } else {
            hint.textContent = 'Нажмите 🔕 — напомним о новых окнах в расписании';
          }
        }
      }

      /** Toggle slot-notification subscription. Optimistic UI + toast feedback. */
      function toggleNotifySlots(trainerId) {
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return;
        var key = String(trainerId);
        var edge = state.trainerEdges[key] || {};
        var nowNotify = !!edge.notify_when_slots;
        var nextNotify = !nowNotify;

        state.trainerEdges[key] = Object.assign({}, edge, { notify_when_slots: nextNotify });
        _updateNotifyChipUI(trainerId, nextNotify);

        // Immediate feedback — tells user exactly what will happen
        if (nextNotify) {
          showToast('🔔 Уведомим, когда тренер добавит свободные окна');
        } else {
          showToast('Подписка на уведомления отменена');
        }

        var headers = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData };
        var method = nextNotify ? 'POST' : 'DELETE';
        var url = nextNotify
          ? '/api/webapp/client/trainer-edges/notify-slots'
          : '/api/webapp/client/trainer-edges/notify-slots/' + trainerId;
        var body = nextNotify ? JSON.stringify({ trainer_id: trainerId }) : undefined;
        fetch(url, { method: method, headers: headers, body: body })
          .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function(data) {
            if (data && data.edge) {
              state.trainerEdges[key] = data.edge;
              _updateNotifyChipUI(trainerId, !!data.edge.notify_when_slots);
            }
          })
          .catch(function() {
            state.trainerEdges[key] = Object.assign({}, edge, { notify_when_slots: nowNotify });
            _updateNotifyChipUI(trainerId, nowNotify);
          });
      }

      /**
       * Client→friend trainer recommendation (same deep link as client-home «Поделиться»).
       */
      function openTrainerShareDialog(trainerId, shareContext) {
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData || trainerId == null) return;
        var ctx = shareContext || 'catalog';
        var url =
          '/api/webapp/client/share-trainer/' +
          encodeURIComponent(String(trainerId)) +
          '?share_context=' +
          encodeURIComponent(ctx) +
          '&init_data=' +
          encodeURIComponent(initData);
        fetch(url, { headers: { 'X-Telegram-Init-Data': initData } })
          .then(function(r) {
            return r.ok ? r.json() : Promise.reject();
          })
          .then(function(data) {
            var shareUrl = (data.share_url || '').trim();
            var shareBody = (data.share_body || '').trim();
            var shareText = (data.share_text || '').trim();
            if (!shareUrl && !shareText) return;
            if (typeof window.openTelegramShareUrlFromMiniApp === 'function') {
              window.openTelegramShareUrlFromMiniApp({
                shareUrl: shareUrl,
                shareBody: shareBody,
                fullMessage: shareText,
              });
              return;
            }
            var href;
            if (shareUrl) {
              href = 'https://t.me/share/url?url=' + encodeURIComponent(shareUrl);
              if (shareBody) href += '&text=' + encodeURIComponent(shareBody);
            } else {
              href = 'https://t.me/share/url?text=' + encodeURIComponent(shareText);
            }
            if (tg && typeof tg.openTelegramLink === 'function') {
              tg.openTelegramLink(href);
            }
          })
          .catch(function() {});
      }

      /**
       * Dual-chip row: [🔔 Напомнить] [❤️ Сохранить].
       * Compact secondary actions — never obscure the primary CTA.
       * noSlots=true adds a subtle pulse to the notify chip to draw attention.
       */
      function appendTrainerActionChips(container, trainer, noSlots) {
        if (!container || !trainer || trainer.id == null) return;
        if (!tg || !tg.initData) return;
        var tid = trainer.id;
        var edge = state.trainerEdges[String(tid)] || {};
        var isSaved = !!edge.is_saved;
        var isNotify = !!edge.notify_when_slots;

        var row = document.createElement('div');
        row.className = 'trainer-action-chips';

        // ── Notify chip (left) ──
        var chipNotify = document.createElement('button');
        chipNotify.type = 'button';
        chipNotify.id = 'chipNotifySlots';
        chipNotify.setAttribute('data-trainer-id', String(tid));
        chipNotify.className = 'trainer-action-chip trainer-action-chip--notify' +
          (isNotify ? ' is-active' : '') +
          (!isNotify && noSlots ? ' wants-attention' : '');
        chipNotify.setAttribute('data-no-slots-context', noSlots ? '1' : '0');
        chipNotify.innerHTML =
          '<span class="chip-icon">' + (isNotify ? '🔔' : '🔕') + '</span>' +
          '<span>' + (isNotify ? 'Подписан' : 'Напомнить') + '</span>';
        chipNotify.onclick = function() { toggleNotifySlots(tid); };

        // ── Save chip (right) ──
        var chipSave = document.createElement('button');
        chipSave.type = 'button';
        chipSave.id = 'chipSaveTrainer';
        chipSave.setAttribute('data-trainer-id', String(tid));
        chipSave.className = 'trainer-action-chip trainer-action-chip--save' +
          (isSaved ? ' is-active' : '');
        chipSave.innerHTML =
          '<span class="chip-icon">' + (isSaved ? '❤️' : '🤍') + '</span>' +
          '<span>' + (isSaved ? 'Сохранено' : 'Сохранить') + '</span>';
        chipSave.onclick = function() { toggleSaveTrainer(tid); };

        row.appendChild(chipNotify);
        row.appendChild(chipSave);
        container.appendChild(row);

        var shareWide = document.createElement('button');
        shareWide.type = 'button';
        shareWide.className = 'trainer-share-wide-btn';
        shareWide.setAttribute('aria-label', 'Поделиться тренером');
        shareWide.innerHTML =
          '<span class="trainer-share-wide-icon" aria-hidden="true">↗</span>' +
          '<span>Поделиться тренером</span>';
        shareWide.onclick = function(ev) {
          ev.preventDefault();
          ev.stopPropagation();
          openTrainerShareDialog(tid, 'catalog');
        };
        container.appendChild(shareWide);

        // Context hint always under chips (was omitted when slots existed and user unsubscribed).
        var hint = document.createElement('p');
        hint.className = 'chips-hint';
        hint.id = 'chipsContextHint';
        if (isNotify) {
          hint.textContent = '🔔 Уведомим, когда появятся свободные окна';
        } else if (noSlots) {
          hint.textContent = 'Нет слотов — нажмите 🔕, чтобы получить уведомление';
        } else {
          hint.textContent = 'Нажмите 🔕 — напомним о новых окнах в расписании';
        }
        container.appendChild(hint);
      }

      /**
       * @deprecated Use appendTrainerActionChips. Kept for safety in case any
       * branch still calls it — silently delegates to the new implementation.
       */
      function appendSaveTrainerButton(container, trainer) {
        appendTrainerActionChips(container, trainer, false);
      }

      /**
       * @param {object} session — GET /client/session JSON
       * @param {{ bookingFormRefresh?: boolean }} [opts] If true, only refresh phone/profile flags.
       *   Does not touch city, arena, or service_id — those stay as on the trainer card so booking_context
       *   from GET /client/session cannot revert a service the user just picked.
       */
      function applySessionToState(session, opts) {
        opts = opts || {};
        var bookingOnly = !!opts.bookingFormRefresh;
        if (!bookingOnly) {
          if (session.city_id != null && session.city_id !== '') {
            state.cityId = parseInt(session.city_id, 10) || null;
            state.cityName = session.city_name || '';
          }
          if (session.service_id != null && session.service_id !== '') {
            state.serviceId = parseInt(session.service_id, 10) || null;
            state.serviceName = session.service_name || '';
          }
          if (session.arena_id != null) {
            // Persisted single-arena session (server only stores one) is restored as a 1-element selection.
            setArenaSelection([session.arena_id], [session.arena_name || 'Арена']);
          } else {
            clearArenaSelection();
          }
          if (session.trainer_id) { state.trainerId = session.trainer_id; state.trainerName = session.trainer_name || ''; }
          else { state.trainerId = null; state.trainerName = ''; }
        }
        var stid = session.suggested_service_for_trainer_id;
        state.suggestedServiceForTrainerId =
          stid != null && stid !== '' && !isNaN(Number(stid)) ? Number(stid) : null;
        var sidS = session.suggested_service_id_for_trainer;
        state.suggestedServiceForTrainer =
          sidS != null && sidS !== '' && !isNaN(Number(sidS)) ? Number(sidS) : null;
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
        var bpvRaw = session.booking_context_service_price_variant_id;
        state.bookingContextServicePriceVariantId =
          bpvRaw != null && bpvRaw !== '' && !isNaN(Number(bpvRaw)) && Number(bpvRaw) > 0
            ? Number(bpvRaw)
            : null;
        var bctxRaw = session.booking_context_service_id;
        state.bookingContextServiceId =
          bctxRaw != null && bctxRaw !== '' && !isNaN(Number(bctxRaw)) && Number(bctxRaw) > 0
            ? Number(bctxRaw)
            : null;
        var lcSidRaw = session.last_created_booking_service_id;
        state.lastCreatedBookingServiceId =
          lcSidRaw != null && lcSidRaw !== '' && !isNaN(Number(lcSidRaw)) && Number(lcSidRaw) > 0
            ? Number(lcSidRaw)
            : null;
        var lcVidRaw = session.last_created_booking_service_price_variant_id;
        state.lastCreatedBookingPriceVariantId =
          lcVidRaw != null && lcVidRaw !== '' && !isNaN(Number(lcVidRaw)) && Number(lcVidRaw) > 0
            ? Number(lcVidRaw)
            : null;
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
        var tid = state.selectedTrainer && state.selectedTrainer.id != null ? state.selectedTrainer.id : null;
        var req = tid != null ? getClientSession({ forTrainerId: tid }) : getClientSession();
        req.then(function(session) {
          applySessionToState(session, tid != null ? { bookingFormRefresh: true } : undefined);
          updateBookingNameFieldsVisibility();
          if (cb) cb();
        }).catch(function() {
          updateBookingNameFieldsVisibility();
          if (cb) cb();
        });
      }

      function normalizeCatalogBookingPhoneFromField(raw) {
        var d =
          typeof window.extractNational375Digits === 'function'
            ? window.extractNational375Digits(raw)
            : (function () {
                var x = String(raw || '').replace(/\D/g, '');
                while (x.length >= 2 && x.slice(0, 2) === '00') x = x.slice(2);
                while (x.length > 9 && x.indexOf('375') === 0) x = x.slice(3);
                if (x.indexOf('80') === 0 && x.length >= 9) x = x.slice(2);
                while (x.length > 9 && x.indexOf('375') === 0) x = x.slice(3);
                return x.length > 9 ? x.slice(0, 9) : x;
              })();
        if (d.length !== 9) return '';
        return '+375' + d;
      }

      function prefillBookingPhoneField() {
        var el = document.getElementById('bookingPhone');
        if (!el) return;
        var raw = (state.clientPhone || '').trim();
        if (!raw) {
          el.value = '';
          return;
        }
        var d =
          typeof window.extractNational375Digits === 'function'
            ? window.extractNational375Digits(raw)
            : (function () {
                var x = raw.replace(/\D/g, '');
                while (x.length >= 2 && x.slice(0, 2) === '00') x = x.slice(2);
                while (x.length > 9 && x.indexOf('375') === 0) x = x.slice(3);
                if (x.indexOf('80') === 0 && x.length >= 9) x = x.slice(2);
                while (x.length > 9 && x.indexOf('375') === 0) x = x.slice(3);
                return x.length > 9 ? x.slice(0, 9) : x;
              })();
        if (d.length < 9) {
          el.value = '';
          return;
        }
        el.value = d.slice(0, 9);
        if (typeof window.applyNational375MaskedToInput === 'function') {
          window.applyNational375MaskedToInput(el);
        }
      }

      /** Persist summary filters (and optional trainer) so reopening catalog keeps city/service/arena. */
      function persistCatalogFilters(trainerId) {
        if (!state.cityId && !state.serviceId) return Promise.resolve();
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return Promise.resolve();
        var body = {};
        if (state.cityId) body.city_id = state.cityId;
        if (state.serviceId) body.service_id = state.serviceId;
        if (state.arenaId != null) body.arena_id = state.arenaId;
        var tid = trainerId != null ? trainerId : state.trainerId;
        if (tid != null && Number(tid) > 0) body.trainer_id = Number(tid);
        return fetch('/api/webapp/client/session/catalog-filters', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData },
          body: JSON.stringify(body),
        }).catch(function() { /* no UX impact */ });
      }

      function persistTrainerSelection(trainerId) {
        if (!trainerId || !state.cityId || !state.serviceId) return;
        persistCatalogFilters(trainerId);
      }

      /** Drop service/scenario chip when the service has no trainers in the new city. */
      function clearServiceIfInvalidForCity(cityId) {
        if (!state.serviceId && !state.catalogScenarioStub) return Promise.resolve();
        return fetchCatalogServices(cityId).then(function(items) {
          if (!state.serviceId) return items;
          var stillValid = items.some(function(s) {
            return s.id === state.serviceId;
          });
          if (!stillValid) {
            state.serviceId = null;
            state.serviceName = '';
            state.catalogScenarioStub = null;
            syncScenarioChipSelection();
            clearCatalogSessionStorageCache();
          }
          return items;
        });
      }

      function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }
      function escapeAttr(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/"/g, '&quot;');
      }

      var CATALOG_NOTICE_PREFIX = 'В стоимость не входят:';

      /** Text after the fixed prefix for display (or full text if prefix missing — still shown under the same lead). */
      function parseCatalogClientNoticeItems(raw) {
        var s = (raw || '').trim();
        if (!s) return '';
        var rePlural = /^В стоимость не входят:\s*/i;
        if (rePlural.test(s)) return s.replace(rePlural, '').replace(/\.\s*$/, '').trim();
        var reSingular = /^В стоимость не входит:\s*/i;
        if (reSingular.test(s)) return s.replace(reSingular, '').replace(/\.\s*$/, '').trim();
        return s;
      }

      /** Prominent block for the service selected in the catalog filter. */
      function catalogImportantNoticeBlockHtml(raw) {
        var items = parseCatalogClientNoticeItems(raw);
        if (!items) return '';
        var esc = escapeHtml(items).replace(/\n/g, '<br>');
        return (
          '<div class="trainer-detail-service-important-callout" role="region" aria-label="Важно">' +
          '<div class="trainer-detail-service-important-kicker">Важно!</div>' +
          '<div class="trainer-detail-service-important-lead">' +
          escapeHtml(CATALOG_NOTICE_PREFIX) +
          '</div>' +
          '<div class="trainer-detail-service-important-items">' +
          esc +
          '</div>' +
          '</div>'
        );
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
          var html =
            '<details class="trainer-detail-groups-details">' +
            '<summary class="trainer-detail-groups-summary">Набор в группы</summary>' +
            '<div class="trainer-detail-groups-inner">';
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
          html += '</div></details>';
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
      /** Summary filter row labels (trainer is chosen on the list screen, not in this panel). */
      var CATALOG_FILTER_LABELS = {
        city: '📍 Город',
        service: '🎯 Что ищете',
        arena: '🏟️ Площадка',
      };
      var CATALOG_FILTER_ICONS = { city: '📍', service: '🎯', arena: '🏟️' };
      var CATALOG_FILTER_SHORT_LABELS = { city: 'Город', service: 'Что ищете', arena: 'Площадка' };

      /**
       * Quick goal chips → catalog services (names from seed / migrations).
       * skating → «Совершенствование катания»; from-zero → «Обучение катанию «с нуля»».
       */
      var CATALOG_SCENARIO_STUBS = {
        skating: {
          label: '⛸️ Улучшить катание',
          servicePatterns: ['совершенствование катания'],
        },
        'from-zero': {
          label: '🌱 С нуля',
          servicePatterns: ['обучение катанию'],
        },
      };
      var _catalogServicesCacheByCity = {};

      function catalogServicesCacheKey(cityId) {
        return cityId ? String(cityId) : '_all';
      }

      function invalidateCatalogServicesCache() {
        _catalogServicesCacheByCity = {};
      }

      function normalizeCatalogServiceName(name) {
        return String(name || '')
          .toLowerCase()
          .replace(/[«»"'`]/g, '')
          .replace(/\s+/g, ' ')
          .trim();
      }

      function matchServiceForScenario(stubKey, items) {
        var stub = CATALOG_SCENARIO_STUBS[stubKey];
        if (!stub || !items || !items.length) return null;
        var patterns = stub.servicePatterns || [];
        for (var i = 0; i < items.length; i++) {
          var norm = normalizeCatalogServiceName(items[i].name);
          for (var p = 0; p < patterns.length; p++) {
            if (norm.indexOf(patterns[p]) !== -1) return items[i];
          }
        }
        return null;
      }

      function fetchCatalogServices(cityId) {
        var key = catalogServicesCacheKey(cityId);
        if (_catalogServicesCacheByCity[key]) return Promise.resolve(_catalogServicesCacheByCity[key]);
        var params = cityId ? { city_id: cityId } : null;
        return getJson('/services', params).then(function(data) {
          _catalogServicesCacheByCity[key] = data.items || [];
          return _catalogServicesCacheByCity[key];
        });
      }

      /** Bind scenario chip to real service_id when API exposes the name. */
      function applyScenarioService(stubKey) {
        if (!stubKey) return Promise.resolve(false);
        return fetchCatalogServices(state.cityId || null)
          .then(function(items) {
            var hit = matchServiceForScenario(stubKey, items);
            if (!hit) return false;
            state.serviceId = hit.id;
            state.serviceName = hit.name || '';
            clearCatalogSessionStorageCache();
            return true;
          })
          .catch(function() {
            return false;
          });
      }

      function syncScenarioChipSelection() {
        var host = document.getElementById('catalogScenarioChips');
        if (!host) return;
        var stubKey = state.catalogScenarioStub;
        if (!stubKey && state.serviceId) {
          var items = _catalogServicesCacheByCity[catalogServicesCacheKey(state.cityId || null)];
          if (items) {
            for (var k in CATALOG_SCENARIO_STUBS) {
              if (!Object.prototype.hasOwnProperty.call(CATALOG_SCENARIO_STUBS, k)) continue;
              var hit = matchServiceForScenario(k, items);
              if (hit && hit.id === state.serviceId) stubKey = k;
            }
          }
        }
        host.querySelectorAll('.catalog-scenario-chip').forEach(function(c) {
          var on = (c.getAttribute('data-scenario') || '') === stubKey;
          c.classList.toggle('catalog-scenario-chip--selected', on);
          c.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
      }

      var CATALOG_CTA_LABEL = 'Показать результаты';

      function updateCatalogHomeMode() {
        var titleEl = document.getElementById('catalogHeroTitle');
        var leadEl = document.getElementById('catalogHeroLead');
        if (!titleEl || !leadEl) return;
        if (state.cityId && state.serviceId) {
          titleEl.textContent = 'Готово к поиску';
          leadEl.textContent = 'Нажмите «Показать результаты» — откроем подходящих тренеров.';
        } else {
          titleEl.textContent = 'Найдите тренировку';
          leadEl.textContent = 'Выберите город и занятие — покажем тренеров со свободными слотами.';
        }
      }

      function wireCatalogScenarioChips() {
        var host = document.getElementById('catalogScenarioChips');
        if (!host) return;
        host.querySelectorAll('.catalog-scenario-chip').forEach(function(chip) {
          chip.setAttribute('aria-pressed', 'false');
          chip.addEventListener('click', function() {
            var key = chip.getAttribute('data-scenario') || '';
            var stub = CATALOG_SCENARIO_STUBS[key];
            if (!stub) return;
            var wasSelected = chip.classList.contains('catalog-scenario-chip--selected');
            host.querySelectorAll('.catalog-scenario-chip').forEach(function(c) {
              c.classList.remove('catalog-scenario-chip--selected');
              c.setAttribute('aria-pressed', 'false');
            });
            if (!wasSelected) {
              chip.classList.add('catalog-scenario-chip--selected');
              chip.setAttribute('aria-pressed', 'true');
              state.catalogScenarioStub = key;
              state.catalogMode = 'trainers';
              renderSummary();
              applyScenarioService(key).then(function(ok) {
                if (ok) state.catalogScenarioStub = null;
                syncScenarioChipSelection();
                renderSummary();
                if (ok) persistCatalogFilters();
              });
            } else {
              var matched = matchServiceForScenario(
                key,
                _catalogServicesCacheByCity[catalogServicesCacheKey(state.cityId || null)] || []
              );
              if (matched && state.serviceId === matched.id) {
                state.serviceId = null;
                state.serviceName = '';
              }
              state.catalogScenarioStub = null;
              clearCatalogSessionStorageCache();
              syncScenarioChipSelection();
              renderSummary();
            }
            var wg = window.Telegram && window.Telegram.WebApp;
            if (wg && wg.HapticFeedback && wg.HapticFeedback.selectionChanged) {
              try {
                wg.HapticFeedback.selectionChanged();
              } catch (eh) {
                /* noop */
              }
            }
          });
        });
      }

      function catalogServiceSummaryDisplay() {
        if (state.serviceName) return state.serviceName;
        var stub = state.catalogScenarioStub && CATALOG_SCENARIO_STUBS[state.catalogScenarioStub];
        if (stub) return stub.label;
        return '';
      }

      function catalogFilterPlaceholder(key, rawValue) {
        if (rawValue && rawValue !== '—') return rawValue;
        if (key === 'city') return 'Выберите город';
        if (key === 'service') return 'Выберите занятие';
        if (key === 'arena') return 'Любая площадка';
        return 'Выберите';
      }

      /** Hint under CTA; label «Выбрать город» or «Показать результаты». */
      function updateCatalogFindUi() {
        var hintEl = document.getElementById('catalogFindHint');
        var btn = document.getElementById('btnPickTrainer');
        if (!hintEl || !btn) return;
        var labelEl = btn.querySelector('.catalog-find-btn__label');
        var hasCity = !!state.cityId;
        if (labelEl) labelEl.textContent = hasCity ? CATALOG_CTA_LABEL : 'Выбрать город';
        var hasService = !!state.serviceId;
        var ready = hasCity && hasService;
        var hint;
        if (ready) {
          var offerCnt = lookupServiceTrainerCount(state.serviceId, state.cityId);
          if (offerCnt === 0) {
            hint = 'В этом городе пока нет тренеров по этой услуге — можно оставить заявку';
          } else if (offerCnt != null && offerCnt > 0) {
            hint = formatServiceOfferCount(offerCnt) + ' · площадку можно уточнить выше';
          } else {
            hint = 'Площадку можно уточнить в параметрах выше';
          }
        } else if (!hasCity && hasService) {
          hint = 'Осталось выбрать город в параметрах выше';
        } else if (!hasCity) {
          hint = 'Начните с города или нажмите вариант в «Популярное»';
        } else {
          hint = 'Укажите занятие в параметрах или в «Популярное»';
        }
        hintEl.textContent = hint;
        btn.classList.toggle('catalog-find-btn--ready', ready);
        updateCatalogHomeMode();
      }

      function renderSummary() {
        var serviceDisplay = catalogServiceSummaryDisplay();
        var arenaDisplay = arenaSummaryLabel();
        var rows = [
          { key: 'city', value: state.cityName || '', scenario: false },
          { key: 'service', value: serviceDisplay, scenario: !state.serviceName && !!state.catalogScenarioStub },
          { key: 'arena', value: arenaDisplay, scenario: false },
        ];
        document.getElementById('summaryRows').innerHTML = rows
          .map(function(r) {
            var display = catalogFilterPlaceholder(r.key, r.value);
            var isSet = !!(r.value && r.value !== '—');
            var offerMeta = '';
            if (r.key === 'service' && state.cityId && state.serviceId) {
              var cnt = lookupServiceTrainerCount(state.serviceId, state.cityId);
              if (cnt !== null) offerMeta = formatServiceOfferCount(cnt);
            }
            var tileCls =
              'catalog-filter-tile' +
              (isSet ? ' catalog-filter-tile--set' : ' catalog-filter-tile--empty') +
              (r.scenario ? ' catalog-filter-tile--scenario' : '');
            return (
              '<button type="button" class="' +
              tileCls +
              '" data-action="' +
              r.key +
              '">' +
              '<span class="catalog-filter-tile__icon" aria-hidden="true">' +
              (CATALOG_FILTER_ICONS[r.key] || '') +
              '</span>' +
              '<span class="catalog-filter-tile__body">' +
              '<span class="catalog-filter-tile__label">' +
              escapeHtml(CATALOG_FILTER_SHORT_LABELS[r.key] || r.key) +
              '</span>' +
              '<span class="catalog-filter-tile__value">' +
              escapeHtml(display) +
              '</span>' +
              (offerMeta
                ? '<span class="catalog-filter-tile__meta">' + escapeHtml(offerMeta) + '</span>'
                : '') +
              '</span>' +
              (isSet
                ? '<span class="catalog-filter-tile__check" aria-hidden="true">✓</span>'
                : '<span class="catalog-filter-tile__chev" aria-hidden="true">›</span>') +
              '</button>'
            );
          })
          .join('');
        updateCatalogFindUi();
        if (state.cityId) {
          fetchCatalogServices(state.cityId).then(function() {
            patchSummaryServiceOfferMeta();
            updateCatalogFindUi();
          });
        }
        document.querySelectorAll('#summaryRows .catalog-filter-tile').forEach(function(btn) {
          btn.onclick = function() {
            var action = btn.dataset.action;
            if (action === 'city') {
              state.returnToSummary = true;
              loadCities();
              showScreen('screenCity');
            } else if (action === 'service') {
              if (!state.cityId) {
                state.returnToSummary = true;
                loadCities();
                showScreen('screenCity');
              } else {
                state.returnToSummary = true;
                loadServices();
                showScreen('screenService');
              }
            } else if (action === 'arena') {
              if (!state.cityId) {
                state.returnToSummary = true;
                loadCities();
                showScreen('screenCity');
              } else {
                state.returnToSummary = true;
                loadArenas();
                showScreen('screenArena');
              }
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
            syncCatalogHeaderBack();
            return;
          }
          var html = items.map(function(c) {
            return '<button type="button" class="choice-card" data-id="' + c.id + '" data-name="' + (c.name || '').replace(/"/g, '&quot;') + '"><div class="main"><div class="label">' + CATALOG_FILTER_LABELS.city + '</div><div class="value">' + (c.name || '') + '</div></div><span class="arrow">→</span></button>';
          }).join('');
          document.getElementById('cityList').innerHTML = html;
          document.querySelectorAll('#cityList .choice-card').forEach(function(btn) {
            btn.onclick = function() {
              var newCityId = parseInt(btn.dataset.id, 10);
              var cityChanged = state.cityId != null && state.cityId !== newCityId;
              state.cityId = newCityId;
              state.cityName = btn.dataset.name || '';
              invalidateCatalogServicesCache();
              clearCatalogSessionStorageCache();
              var afterCity = function() {
                persistCatalogFilters();
                if (state.returnToSummary) {
                  state.returnToSummary = false;
                  if (cityChanged) {
                    clearArenaSelection();
                    state.trainerId = null;
                    state.trainerName = '';
                  }
                  renderSummary();
                  syncScenarioChipSelection();
                  showScreen('screenSummary');
                } else {
                  loadServices();
                  showScreen('screenService');
                }
                prefetchFirstPageIfNeeded();
              };
              if (cityChanged) {
                clearServiceIfInvalidForCity(newCityId).then(afterCity);
              } else {
                afterCity();
              }
            };
          });
          syncCatalogHeaderBack();
        }).catch(function() {
          document.getElementById('cityList').innerHTML = '<div class="error">Ошибка загрузки</div>';
          syncCatalogHeaderBack();
        });
      }

      function openServiceSummaryModal(title, bodyText) {
        var modal = document.getElementById('serviceSummaryModal');
        var modalTitle = document.getElementById('serviceSummaryModalTitle');
        var modalBody = document.getElementById('serviceSummaryModalBody');
        if (!modal || !modalTitle || !modalBody) return;
        modalTitle.textContent = title || 'Услуга';
        modalBody.textContent = bodyText != null && bodyText !== '' ? String(bodyText) : '';
        modal.classList.add('show');
      }

      function closeServiceSummaryModal() {
        var modal = document.getElementById('serviceSummaryModal');
        if (modal) modal.classList.remove('show');
      }

      var SERVICE_INFO_SVG =
        '<svg class="service-info-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>';

      function loadServices() {
        document.getElementById('serviceList').innerHTML = '<div class="loading">Загрузка...</div>';
        var titleEl = document.getElementById('screenServiceTitle');
        if (titleEl) {
          titleEl.textContent = state.cityName ? 'Занятия · ' + state.cityName : 'Что ищете';
        }
        var loadReq = state.cityId
          ? fetchCatalogServices(state.cityId).then(function(cached) {
              return { items: cached };
            })
          : getJson('/services', null);
        loadReq.then(function(data) {
          var items = data.items || [];
          if (!items.length) {
            var emptyMsg = 'Нет услуг в каталоге';
            document.getElementById('serviceList').innerHTML = '<div class="empty">' + emptyMsg + '</div>';
            var backCityEmpty = document.getElementById('backToCity');
            if (backCityEmpty) backCityEmpty.style.display = state.returnToSummary ? 'none' : 'block';
            syncCatalogHeaderBack();
            return;
          }
          var summaryById = {};
          items.forEach(function(s) {
            if (s.client_summary != null && String(s.client_summary).trim() !== '') {
              summaryById[s.id] = String(s.client_summary);
            }
          });
          var html = items.map(function(s) {
            var hasSummary = summaryById[s.id] != null;
            var nameAttr = (s.name || '').replace(/"/g, '&quot;');
            var escName = escapeHtml(s.name || '');
            var count = s.trainer_count != null ? s.trainer_count | 0 : null;
            var showCount = state.cityId && count !== null;
            var offerLine = showCount
              ? '<div class="choice-card__meta">' + escapeHtml(formatServiceOfferCount(count)) + '</div>'
              : '';
            var noOffers = showCount && count === 0;
            var btnInner =
              '<div class="main">' +
              '<div class="label">' +
              CATALOG_FILTER_LABELS.service +
              '</div>' +
              '<div class="value">' +
              escName +
              '</div>' +
              offerLine +
              '</div><span class="arrow">→</span>';
            var mainBtn =
              '<button type="button" class="choice-card' +
              (hasSummary ? ' service-choice-main' : '') +
              (noOffers ? ' choice-card--no-offers' : '') +
              '" data-id="' +
              s.id +
              '" data-name="' +
              nameAttr +
              '">' +
              btnInner +
              '</button>';
            if (!hasSummary) return mainBtn;
            return (
              '<div class="service-choice-row">' +
              mainBtn +
              '<button type="button" class="service-info-btn" data-id="' +
              s.id +
              '" aria-label="Подробнее об услуге">' +
              SERVICE_INFO_SVG +
              '</button></div>'
            );
          }).join('');
          document.getElementById('serviceList').innerHTML = html;
          var backCity = document.getElementById('backToCity');
          if (backCity) backCity.style.display = state.returnToSummary ? 'none' : 'block';
          document.querySelectorAll('#serviceList .choice-card').forEach(function(btn) {
            btn.onclick = function() {
              state.serviceId = parseInt(btn.dataset.id, 10);
              state.serviceName = btn.dataset.name || '';
              state.catalogScenarioStub = null;
              var chipHost = document.getElementById('catalogScenarioChips');
              if (chipHost) {
                chipHost.querySelectorAll('.catalog-scenario-chip').forEach(function(c) {
                  c.classList.remove('catalog-scenario-chip--selected');
                  c.setAttribute('aria-pressed', 'false');
                });
              }
              clearCatalogSessionStorageCache();
              persistCatalogFilters();
              if (state.returnToSummary) {
                state.returnToSummary = false;
                clearArenaSelection();
                state.trainerId = null; state.trainerName = '';
                renderSummary();
                showScreen('screenSummary');
              } else {
                loadArenas();
                showScreen('screenArena');
              }
              prefetchFirstPageIfNeeded();
            };
          });
          document.querySelectorAll('#serviceList .service-info-btn').forEach(function(btn) {
            btn.addEventListener('click', function(ev) {
              ev.preventDefault();
              ev.stopPropagation();
              var sid = parseInt(btn.getAttribute('data-id'), 10);
              var title = '';
              for (var i = 0; i < items.length; i++) {
                if (items[i].id === sid) {
                  title = items[i].name || '';
                  break;
                }
              }
              openServiceSummaryModal(title, summaryById[sid] || '');
            });
          });
          syncCatalogHeaderBack();
        }).catch(function() {
          document.getElementById('serviceList').innerHTML = '<div class="error">Ошибка загрузки</div>';
          var backCityErr = document.getElementById('backToCity');
          if (backCityErr) backCityErr.style.display = state.returnToSummary ? 'none' : 'block';
          syncCatalogHeaderBack();
        });
      }

      // Pending arena selection on the screen — committed via "Готово". Allows the user to
      // toggle freely without firing list reloads on every checkbox tap.
      var arenaScreenDraft = { ids: [], names: [], items: [] };

      // Leaflet map for the arena selection screen. Lazily initialised — created on first
      // mount, then re-bound each time loadArenas() runs. Hidden when no arenas have coords.
      var arenaMapInstance = null;
      var arenaMapMarkers = {}; // id -> L.marker

      function ensureArenaMapMounted() {
        var wrap = document.getElementById('arenaMapWrap');
        var node = document.getElementById('arenaMap');
        if (!wrap || !node) return;
        var items = (arenaScreenDraft.items || []).filter(function(a) { return a.latitude != null && a.longitude != null; });
        if (!items.length) {
          wrap.setAttribute('hidden', '');
          return;
        }
        // Leaflet loads with `defer` — on slow networks may not yet be parsed when arenas come back.
        // Retry once the script signals readiness (or quietly stay list-only after the timeout).
        if (typeof window.L === 'undefined') {
          wrap.setAttribute('hidden', '');
          var waited = 0;
          var poll = setInterval(function() {
            waited += 200;
            if (typeof window.L !== 'undefined') {
              clearInterval(poll);
              ensureArenaMapMounted();
            } else if (waited >= 4000) {
              clearInterval(poll);
            }
          }, 200);
          return;
        }
        wrap.removeAttribute('hidden');

        // Destroy old map on each (re)mount to reset markers cleanly.
        if (arenaMapInstance) {
          try { arenaMapInstance.remove(); } catch (e) { /* ignore — node will be re-used */ }
          arenaMapInstance = null;
          arenaMapMarkers = {};
        }
        // Lock map height in CSS; tap handlers don't need keyboard.
        var L = window.L;
        var map = L.map(node, {
          zoomControl: false,
          attributionControl: true,
          // Lower default sensitivity helps inside a Telegram WebView where vertical scroll wins.
          tap: true,
        });
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 18,
          // OSM ToS requires visible attribution. Keep it short.
          attribution: '&copy; OpenStreetMap',
        }).addTo(map);
        // Leaflet 1.9+ default prefix includes a flag in the attribution bar; we only need OSM credit.
        if (map.attributionControl && typeof map.attributionControl.setPrefix === 'function') {
          map.attributionControl.setPrefix(false);
        }

        items.forEach(function(a) {
          var lat = parseFloat(a.latitude);
          var lng = parseFloat(a.longitude);
          if (isNaN(lat) || isNaN(lng)) return;
          var marker = L.marker([lat, lng], {
            icon: makeArenaPinIcon(arenaScreenDraft.ids.indexOf(a.id) >= 0),
            title: a.name || 'Арена',
            keyboard: false,
            riseOnHover: true,
          });
          marker.on('click', function() {
            toggleArenaInDraft(a.id, a.name || 'Арена');
          });
          marker.addTo(map);
          arenaMapMarkers[a.id] = marker;
        });

        var bounds = L.latLngBounds(items.map(function(a) { return [parseFloat(a.latitude), parseFloat(a.longitude)]; }));
        // Padding leaves room for the legend + makes single-pin cities not zoom in too far.
        if (items.length === 1) {
          map.setView(bounds.getCenter(), 14);
        } else {
          map.fitBounds(bounds, { padding: [28, 28], maxZoom: 15 });
        }
        arenaMapInstance = map;

        // Tile layout often misjudges the container height on first render inside a hidden screen.
        // requestAnimationFrame triggers a one-shot invalidateSize after the screen is visible.
        requestAnimationFrame(function() {
          if (arenaMapInstance) arenaMapInstance.invalidateSize();
        });

        // Public API for renderArenaListCheckboxes ↔ marker sync (no global reach into Leaflet).
        window.__arenaMapSyncSelection = function(ids) {
          var idset = {};
          (ids || []).forEach(function(id) { idset[id] = true; });
          Object.keys(arenaMapMarkers).forEach(function(key) {
            var marker = arenaMapMarkers[key];
            marker.setIcon(makeArenaPinIcon(!!idset[key]));
          });
        };
      }

      function makeArenaPinIcon(isSelected) {
        var L = window.L;
        return L.divIcon({
          className: 'arena-pin-icon',
          html: '<div class="arena-pin' + (isSelected ? ' arena-pin--selected' : '') + '"></div>',
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        });
      }

      function loadArenas() {
        var listEl = document.getElementById('arenaList');
        listEl.innerHTML = '<div class="loading">Загрузка...</div>';
        var mapWrap = document.getElementById('arenaMapWrap');
        if (mapWrap) mapWrap.setAttribute('hidden', '');
        var actions = document.getElementById('arenaListActions');
        if (actions) actions.setAttribute('hidden', '');
        var applyBar = document.getElementById('arenaApplyBar');
        if (applyBar) applyBar.setAttribute('hidden', '');
        getJson('/arenas', { city_id: state.cityId }).then(function(data) {
          var items = data.items || [];
          arenaScreenDraft.items = items;
          arenaScreenDraft.ids = state.arenaIds.slice();
          arenaScreenDraft.names = state.arenaNames.slice();

          renderArenaListCheckboxes();
          updateArenaScreenChrome();
          ensureArenaMapMounted();

          // From summary: hide «Другая услуга» — header «Назад» returns to summary; backToService would skip loadServices.
          var backSvc = document.getElementById('backToService');
          if (backSvc) backSvc.style.display = state.returnToSummary ? 'none' : 'block';
          syncCatalogHeaderBack();
        }).catch(function() {
          listEl.innerHTML = '<div class="error">Ошибка загрузки</div>';
          var backSvc = document.getElementById('backToService');
          if (backSvc) backSvc.style.display = state.returnToSummary ? 'none' : 'block';
          syncCatalogHeaderBack();
        });
      }

      function renderArenaListCheckboxes() {
        var listEl = document.getElementById('arenaList');
        var items = arenaScreenDraft.items || [];
        if (!items.length) {
          listEl.innerHTML = '<div class="empty">В этом городе арены пока не добавлены</div>';
          return;
        }
        var selectedSet = {};
        arenaScreenDraft.ids.forEach(function(id) { selectedSet[id] = true; });
        var html = items.map(function(a) {
          var isSel = !!selectedSet[a.id];
          var name = (a.name || '').replace(/"/g, '&quot;');
          var addr = a.address ? ('<div class="arena-card__addr">' + escapeHtml(a.address) + '</div>') : '';
          return (
            '<label class="arena-card' + (isSel ? ' selected' : '') + '" data-id="' + a.id + '" data-name="' + name + '">' +
              '<span class="arena-card__check" aria-hidden="true">' +
                (isSel
                  ? '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="3.5 8.5 6.8 11.8 12.5 5.2"/></svg>'
                  : '') +
              '</span>' +
              '<span class="arena-card__main">' +
                '<span class="arena-card__name">' + (a.name || '') + '</span>' +
                addr +
              '</span>' +
            '</label>'
          );
        }).join('');
        listEl.innerHTML = '<div class="arena-card-list">' + html + '</div>';
        listEl.querySelectorAll('.arena-card').forEach(function(card) {
          card.addEventListener('click', function(ev) {
            ev.preventDefault();
            var id = parseInt(card.dataset.id, 10);
            if (!id) return;
            var name = card.dataset.name || 'Арена';
            toggleArenaInDraft(id, name);
          });
        });
      }

      function toggleArenaInDraft(id, name) {
        var idx = arenaScreenDraft.ids.indexOf(id);
        if (idx >= 0) {
          arenaScreenDraft.ids.splice(idx, 1);
          arenaScreenDraft.names.splice(idx, 1);
        } else {
          arenaScreenDraft.ids.push(id);
          arenaScreenDraft.names.push(name);
        }
        renderArenaListCheckboxes();
        updateArenaScreenChrome();
        if (typeof window.__arenaMapSyncSelection === 'function') {
          window.__arenaMapSyncSelection(arenaScreenDraft.ids);
        }
      }

      function updateArenaScreenChrome() {
        var counter = document.getElementById('arenaListCounter');
        var anyBtn = document.getElementById('arenaAnyBtn');
        var actions = document.getElementById('arenaListActions');
        var applyBar = document.getElementById('arenaApplyBar');
        var applyBtn = document.getElementById('arenaApplyBtn');
        var n = arenaScreenDraft.ids.length;
        if (counter) counter.textContent = n === 0 ? 'Любая арена' : ('Выбрано: ' + n);
        if (anyBtn) anyBtn.classList.toggle('selected', n === 0);
        if (actions) actions.removeAttribute('hidden');
        if (applyBar) applyBar.removeAttribute('hidden');
        if (applyBtn) applyBtn.textContent = n === 0 ? 'Готово · любая арена' : ('Готово · ' + n);
      }

      function commitArenaScreenSelection() {
        setArenaSelection(arenaScreenDraft.ids.slice(), arenaScreenDraft.names.slice());
        state.offset = 0;
        clearCatalogSessionStorageCache();
        persistCatalogFilters();
        if (state.returnToSummary) {
          state.returnToSummary = false;
          state.trainerId = null; state.trainerName = '';
          renderSummary();
          showScreen('screenSummary');
        } else {
          loadCatalogList();
          showScreen('screenTrainers');
        }
        prefetchFirstPageIfNeeded();
      }

      function clearArenaScreenSelection() {
        arenaScreenDraft.ids = [];
        arenaScreenDraft.names = [];
        renderArenaListCheckboxes();
        updateArenaScreenChrome();
        if (typeof window.__arenaMapSyncSelection === 'function') {
          window.__arenaMapSyncSelection([]);
        }
      }

      function formatCatalogServicePrice(s) {
        var minV = s.price_byn_min != null ? s.price_byn_min : s.price_byn;
        var maxV = s.price_byn_max != null ? s.price_byn_max : s.price_byn;
        if (minV == null && s.price_byn == null) return escapeHtml('по запросу');
        if (minV != null && maxV != null && minV !== maxV) {
          var a = minV === Math.floor(minV) ? String(minV) : minV.toFixed(2);
          return 'от ' + escapeHtml(a) + ' BYN';
        }
        var v = minV != null ? minV : s.price_byn;
        var numStr = v === Math.floor(v) ? String(v) : v.toFixed(2);
        return escapeHtml(numStr) + ' BYN';
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
          updateResultsCount(total);
          if (!items.length) {
            if (myReq !== catalogListReqId) return;
            var fEmpty = state.filters;
            var hasSlotFilters =
              (fEmpty.days && fEmpty.days.length > 0) ||
              (fEmpty.timeSlots && fEmpty.timeSlots.length > 0);
            var emptyHint = hasSlotFilters
              ? ' Попробуйте сбросить фильтр по времени или выбрать другие дни.'
              : state.cityId && state.serviceId
                ? ' Попробуйте другую услугу или арену.'
                : '';
            revealCatalogListContent(
              '<div class="empty">Тренеров по вашему запросу пока нет.' + emptyHint + '</div>' +
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
        if (state.trainerSlotsArenaIds && state.trainerSlotsArenaIds.length) {
          q += '&arena_ids=' + encodeURIComponent(
            state.trainerSlotsArenaIds.slice().sort(function(a, b) { return a - b; }).join(',')
          );
        }
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

      /** When opening a trainer card: intersect catalog arena filter with trainer's venues (empty ⇒ all). */
      function initTrainerSlotsArenaFilterFromCatalog(t) {
        if (!t || !t.arena_ids || !t.arena_ids.length) {
          state.trainerSlotsArenaIds = [];
          return;
        }
        var tarenas = (t.arena_ids || []).map(Number);
        var picked = [];
        (state.arenaIds || []).forEach(function(cid) {
          var n = Number(cid);
          if (isNaN(n)) return;
          if (tarenas.indexOf(n) >= 0) picked.push(n);
        });
        state.trainerSlotsArenaIds = picked;
      }

      function clearTrainerArenaSlotFilterBar() {
        var wrap = document.getElementById('trainerDetailArenaSlotFilter');
        if (!wrap) return;
        wrap.innerHTML = '';
        wrap.style.display = 'none';
      }

      /** Multi-arena trainers: toggle GET /client/slots?arena_ids= without touching list-level catalog filter. */
      function paintTrainerArenaSlotFilterBar(t) {
        var el = document.getElementById('trainerDetailArenaSlotFilter');
        if (!el) return;
        var ids = (t && t.arena_ids) ? t.arena_ids : [];
        var names = (t && t.arena_names) ? t.arena_names : [];
        if (ids.length <= 1) {
          el.innerHTML = '';
          el.style.display = 'none';
          return;
        }
        el.style.display = 'block';
        var idnums = [];
        for (var z = 0; z < ids.length; z++) {
          var zx = Number(ids[z]);
          if (!isNaN(zx)) idnums.push(zx);
        }
        var allMode = !state.trainerSlotsArenaIds || state.trainerSlotsArenaIds.length === 0;
        var html = '';
        html += '<div class="trainer-detail-arena-filter">';
        html += '<div class="trainer-detail-arena-filter-title">Показать слоты</div>';
        html += '<div class="trainer-detail-arena-filter-chips" role="group" aria-label="Площадки">';
        html +=
          '<button type="button" class="trainer-detail-arena-chip' +
          (allMode ? ' trainer-detail-arena-chip--active' : '') +
          '" data-catalog-arena-filter="all">Все площадки</button>';
        for (var i = 0; i < ids.length; i++) {
          var aid = Number(ids[i]);
          if (isNaN(aid)) continue;
          var nm = (names[i] && String(names[i]).trim()) ? String(names[i]).trim() : 'Площадка ' + aid;
          var sel = !allMode && state.trainerSlotsArenaIds.indexOf(aid) >= 0;
          html +=
            '<button type="button" class="trainer-detail-arena-chip' +
            (sel ? ' trainer-detail-arena-chip--active' : '') +
            '" data-catalog-arena-filter="' +
            aid +
            '">' +
            escapeHtml(nm) +
            '</button>';
        }
        html += '</div></div>';
        el.innerHTML = html;
        el.querySelectorAll('[data-catalog-arena-filter]').forEach(function(btn) {
          btn.onclick = function() {
            var raw = btn.getAttribute('data-catalog-arena-filter');
            if (raw === 'all') {
              state.trainerSlotsArenaIds = [];
            } else {
              var id = parseInt(raw, 10);
              if (isNaN(id)) return;
              var cur = state.trainerSlotsArenaIds.slice();
              if (cur.length === 0) {
                cur = [id];
              } else {
                var ix = cur.indexOf(id);
                if (ix >= 0) cur.splice(ix, 1);
                else cur.push(id);
              }
              if (cur.length === 0 || cur.length >= idnums.length) cur = [];
              state.trainerSlotsArenaIds = cur;
            }
            refetchTrainerSlotsForCard();
          };
        });
      }

      function refetchTrainerSlotsForCard() {
        var tt = state.selectedTrainer;
        if (!tt || tt.can_book !== true) return;
        paintTrainerArenaSlotFilterBar(tt);
        document.getElementById('trainerDetailSlots').innerHTML = '<div class="slots-empty">Загрузка слотов…</div>';
        document.getElementById('trainerDetailActions').innerHTML = '';
        loadSlotsForTrainer(tt.id, tt)
          .then(function(d) {
            paintTrainerSlotsAndActionsSection(tt, d);
          })
          .catch(function() {
            document.getElementById('trainerDetailSlots').innerHTML =
              '<div class="slots-title">Ближайшие слоты</div><div class="slots-empty">Не удалось загрузить слоты</div>';
            var errActions = document.getElementById('trainerDetailActions');
            errActions.innerHTML = '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
            appendTrainerActionChips(errActions, tt, false);
            document.getElementById('trainerDetailSecondary').innerHTML = '';
          });
      }

      function paintTrainerSlotsAndActionsSection(t, data) {
        state.slotsForTrainer = (data && data.slots) || [];
        var slotsEl = document.getElementById('trainerDetailSlots');
        var actionsEl = document.getElementById('trainerDetailActions');
        var slots = state.slotsForTrainer;
        var slotsHtml = '<div class="slots-title">Ближайшие слоты</div>';
        if (slots.length === 0) {
          slotsHtml += '<div class="slots-empty">Сейчас нет свободных слотов.</div>';
          slotsHtml += '<div class="slots-empty slots-empty-hint">Оставьте заявку — тренер предложит удобное время.</div>';
        } else {
          var showCount = Math.min(slots.length, 6);
          for (var i = 0; i < showCount; i++) {
            var s = slots[i];
            slotsHtml +=
              '<button type="button" class="slot-row" data-slot-index="' +
              i +
              '">' +
              '<span class="slot-row-main"><span class="slot-row-line">' +
              formatSlotLabel(s) +
              '</span>' +
              slotGroupSpotsPillHtml(s) +
              '</span><span>→</span></button>';
          }
          if (slots.length > showCount) {
            slotsHtml +=
              '<button type="button" class="slot-row slot-row-more" id="btnShowAllSlots">Ещё слоты (' +
              (slots.length - showCount) +
              ') →</button>';
          }
        }
        slotsEl.innerHTML = slotsHtml;
        slotsEl.querySelectorAll('.slot-row[data-slot-index]').forEach(function(btn) {
          btn.onclick = function() {
            var ii = parseInt(btn.dataset.slotIndex, 10);
            state.selectedSlot = state.slotsForTrainer[ii];
            assignCatalogBookingIdempotencyKeyForSlot();
            document.getElementById('bookingFormSlotLabel').textContent =
              'Выбрано: ' + formatSlotSelectionSummary(state.selectedSlot);
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
        if (btnMore)
          btnMore.onclick = function() {
            renderSlotPickList();
            showScreen('screenSlotPick');
          };
        actionsEl.innerHTML = '';
        if (slots.length > 0) {
          actionsEl.innerHTML += '<button type="button" class="btn-primary btn-block" id="btnBookFromDetail">Записаться</button>';
        }
        actionsEl.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
        if (t.has_pass_products || t.has_certificate_products) {
          actionsEl.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="buy-pass">Абонементы/Сертификаты</button>';
        }
        appendTrainerActionChips(actionsEl, t, slots.length === 0);
        var btnBook = document.getElementById('btnBookFromDetail');
        if (btnBook)
          btnBook.onclick = function() {
            renderSlotPickList();
            showScreen('screenSlotPick');
          };
        document.getElementById('trainerDetailSecondary').innerHTML = '';
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
        html += '<p class="trainer-detail-arena-hint">Запись доступна на те площадки, где у тренера есть свободные слоты. Ниже можно отфильтровать по арене.</p>';
        html += '</div>';
        return html;
      }

      window.selectTrainerService = function(serviceId) {
        if (!state.selectedTrainer) return;
        var sid = Number(serviceId);
        if (isNaN(sid)) return;
        if (state.serviceId === sid) return;
        state.serviceId = sid;
        
        var services = state.selectedTrainer.services || [];
        for (var i = 0; i < services.length; i++) {
          if (Number(services[i].service_id) === sid) {
            state.serviceName = String(services[i].service_name || '').trim();
            break;
          }
        }
        
        // Update URL to reflect the new service ID so if they reload it stays
        if (window.history && window.history.replaceState) {
          var url = new URL(window.location.href);
          url.searchParams.set('service_id', sid);
          window.history.replaceState(null, '', url.toString());
        }

        var tid = state.selectedTrainer && state.selectedTrainer.id != null ? state.selectedTrainer.id : null;
        if (tid != null && state.cityId && state.serviceId != null) persistTrainerSelection(tid);

        renderTrainerDetail();
      };

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
          var selectedServiceNoticeEscaped = '';
          if (state.serviceId != null) {
            var selSvcId = Number(state.serviceId);
            var sj;
            for (sj = 0; sj < services.length; sj++) {
              var sx = services[sj];
              if (sx.service_id == null || Number(sx.service_id) !== selSvcId) continue;
              var rawDesc = sx.description && String(sx.description).trim();
              if (rawDesc) selectedServiceDescEscaped = escapeHtml(rawDesc).replace(/\n/g, '<br>');
              var rawNotice = sx.client_notice && String(sx.client_notice).trim();
              if (rawNotice) selectedServiceNoticeEscaped = rawNotice;
              break;
            }
          }
          // Extra-cost notice before marketing copy — faster go / no-go.
          if (selectedServiceNoticeEscaped) {
            html += catalogImportantNoticeBlockHtml(selectedServiceNoticeEscaped);
          }
          if (selectedServiceDescEscaped) {
            html += '<div class="trainer-detail-service-callout" role="region" aria-label="Описание услуги">';
            html += '<div class="trainer-detail-service-callout-kicker">Описание услуги</div>';
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
            var isClickable = !isNaN(sid) && !matchCatalog;
            /* Native <button>: iOS/WebView reliably delivers taps as click; DIV+inline onclick often does not. */
            if (isClickable) {
              html += '<button type="button" class="trainer-detail-service trainer-detail-service--clickable" data-catalog-service-select="' + sid + '">';
            } else {
              html +=
                '<div class="trainer-detail-service' +
                (matchCatalog ? ' trainer-detail-service--catalog-selected' : '') +
                '">';
            }
            html += '<div class="trainer-detail-service-top">';
            html += '<span class="trainer-detail-service-name">' + escapeHtml(serviceName) + '</span>';
            html += '<span class="trainer-detail-service-price">' + priceText + '</span>';
            html += '</div>';
            html += isClickable ? '</button>' : '</div>';
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
        var eduSectionInner = '';
        if (eduRows.length > 0) {
          eduSectionInner += '<p class="trainer-detail-education-hint">Нажмите на запись, чтобы раскрыть детали и фото документов.</p>';
          var eduAnyHtml = '';
          eduRows.forEach(function(edu) {
            var itemHtml = buildCatalogEducationItemHtml(edu);
            if (itemHtml) eduAnyHtml += itemHtml;
          });
          if (eduAnyHtml) {
            eduSectionInner += eduAnyHtml;
          } else if (profileEduDetail) {
            eduSectionInner += '<div class="trainer-detail-education-body-line">' + escapeHtml(profileEduDetail).replace(/\n/g, '<br>') + '</div>';
          }
          if (profileExtraForDetail) {
            eduSectionInner += '<div class="trainer-detail-education-extra">';
            eduSectionInner += '<div class="trainer-detail-education-extra-label">Дополнительно</div>';
            eduSectionInner +=
              '<div class="trainer-detail-education-extra-body">' + escapeHtml(profileExtraForDetail).replace(/\n/g, '<br>') + '</div>';
            eduSectionInner += '</div>';
          }
        } else if (profileEduDetail) {
          eduSectionInner += '<div class="trainer-detail-education-extra">';
          eduSectionInner +=
            '<div class="trainer-detail-education-extra-body">' + escapeHtml(profileEduDetail).replace(/\n/g, '<br>') + '</div>';
          eduSectionInner += '</div>';
        }
        if (eduSectionInner) {
          html +=
            '<details class="trainer-detail-section-details">' +
            '<summary class="trainer-detail-section-summary">Образование</summary>' +
            '<div class="trainer-detail-section-panel"><div class="trainer-detail-education">' +
            eduSectionInner +
            '</div></div></details>';
        }

        if (desc !== '—') {
          html +=
            '<details class="trainer-detail-section-details">' +
            '<summary class="trainer-detail-section-summary">О тренере</summary>' +
            '<div class="trainer-detail-section-panel">' +
            '<div class="trainer-detail-desc">' +
            escapeHtml(desc).replace(/\n/g, '<br>') +
            '</div></div></details>';
        }
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
          clearTrainerArenaSlotFilterBar();
          var phoneLine = '';
          var ph = (p.phone || '').trim();
          var ct = (p.contacts || '').trim();
          if (ph) phoneLine += '<div class="slots-empty slots-contact"><strong>Телефон:</strong> <a href="tel:' + ph.replace(/[^\d+]/g, '') + '">' + escapeHtml(ph) + '</a></div>';
          if (ct) phoneLine += '<div class="slots-empty slots-contact"><strong>Контакты:</strong> ' + escapeHtml(ct) + '</div>';
          // Lead Mode: trainer kept in catalog after subscription expiry. Promote a strong
          // "Write in Telegram" CTA over the generic "leave request" path so we capture the
          // contact_click signal and route the visitor straight to the trainer's DM.
          var isLeadMode = t.is_lead_mode === true;
          var tgUrl = (typeof t.contact_telegram_url === 'string' && t.contact_telegram_url) ? t.contact_telegram_url : '';
          if (isLeadMode && tgUrl) {
            document.getElementById('trainerDetailSlots').innerHTML =
              '<div class="slots-title">Онлайн-запись</div>' +
              '<div class="slots-empty">Онлайн-запись временно недоступна. Напишите тренеру в Telegram — ответит лично.</div>' +
              phoneLine;
            state.slotsForTrainer = [];
            var actionsLeadEl = document.getElementById('trainerDetailActions');
            actionsLeadEl.innerHTML = '';
            actionsLeadEl.innerHTML += '<button type="button" class="btn-primary btn-block" id="btnContactTelegram">Написать в Telegram</button>';
            actionsLeadEl.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
            appendTrainerActionChips(actionsLeadEl, t, true);
            var btnTg = document.getElementById('btnContactTelegram');
            if (btnTg) {
              btnTg.onclick = function() {
                // Use Telegram's openLink when available — keeps the redirect inside the WebView
                // and lets t.me launch the native Telegram client.
                if (tg && typeof tg.openLink === 'function') {
                  tg.openLink(tgUrl);
                } else {
                  window.open(tgUrl, '_blank');
                }
              };
            }
            document.getElementById('trainerDetailSecondary').innerHTML = '';
            return;
          }
          // ACTIVE trainer without `online` module — keep existing "contact directly" copy.
          document.getElementById('trainerDetailSlots').innerHTML =
            '<div class="slots-title">Онлайн-запись</div>' +
            '<div class="slots-empty">У этого тренера нет самозаписи через каталог. Свяжитесь напрямую — тренер в каталоге, как и раньше.</div>' +
            phoneLine;
          state.slotsForTrainer = [];
          var actionsEl = document.getElementById('trainerDetailActions');
          actionsEl.innerHTML = '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
          appendTrainerActionChips(actionsEl, t, true);
          document.getElementById('trainerDetailSecondary').innerHTML = '';
          return;
        }
        paintTrainerArenaSlotFilterBar(t);
        loadSlotsForTrainer(t.id, t)
          .then(function(data) {
            paintTrainerSlotsAndActionsSection(t, data);
          })
          .catch(function() {
            document.getElementById('trainerDetailSlots').innerHTML =
              '<div class="slots-title">Ближайшие слоты</div><div class="slots-empty">Не удалось загрузить слоты</div>';
            var errActions = document.getElementById('trainerDetailActions');
            errActions.innerHTML = '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
            appendTrainerActionChips(errActions, t, false);
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
            assignCatalogBookingIdempotencyKeyForSlot();
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

      (function wireCatalogBookingPhoneMask() {
        var el = document.getElementById('bookingPhone');
        if (!el || el.dataset.crmNat375Mask === '1') return;
        if (typeof window.wireNational375PhoneInputMask === 'function') {
          window.wireNational375PhoneInputMask(el);
        }
      })();

      document.getElementById('btnSubmitBooking').onclick = function() {
        var slot = state.selectedSlot;
        if (!slot || !state.selectedTrainer) return;
        var phoneRaw = (document.getElementById('bookingPhone').value || '').trim();
        var phone = normalizeCatalogBookingPhoneFromField(phoneRaw);
        if (!phone) {
          alert('Введите 9 цифр номера после +375 (например 29 123-45-67).');
          return;
        }
        if (state.needsProfileName) {
          var fn = (document.getElementById('bookingFirstName') && document.getElementById('bookingFirstName').value || '').trim();
          if (!fn) {
            alert('Укажите имя');
            return;
          }
        }
        var effBookingSid = catalogEffectiveServiceIdForBooking();
        var btn = document.getElementById('btnSubmitBooking');
        btn.disabled = true;
        var initData = tg ? tg.initData : '';
        var body = { slot_id: slot.id, phone: phone, comment: (document.getElementById('bookingComment').value || '').trim() || null };
        if (state.needsProfileName) {
          body.first_name = (document.getElementById('bookingFirstName').value || '').trim();
          var ln = (document.getElementById('bookingLastName').value || '').trim();
          if (ln) body.last_name = ln;
        }
        if (effBookingSid != null) body.service_id = effBookingSid;
        if (state.catalogBookingPriceVariantId != null) {
          body.service_price_variant_id = state.catalogBookingPriceVariantId;
        }
        if (!state.catalogBookingIdempotencyKey) assignCatalogBookingIdempotencyKeyForSlot();
        var headers = { 'Content-Type': 'application/json' };
        if (initData) headers['X-Telegram-Init-Data'] = initData;
        headers['Idempotency-Key'] = state.catalogBookingIdempotencyKey;
        fetch('/api/webapp/client/booking', {
          method: 'POST',
          headers: headers,
          body: JSON.stringify(body)
        }).then(function(r) {
          return r.text().then(function(text) {
            var data = catalogParseBookingJsonResponse(text);
            if (data == null) {
              if (r.ok) {
                alert(
                  'Ответ сервера не распознан, но запись могла сохраниться. Откройте «Мои записи» в боте. ' +
                    'Повторная кнопка с тем же временем подставит тот же запрос и обычно не дублирует бронь.'
                );
              } else {
                alert('Ошибка сервера (' + r.status + '). Проверьте «Мои записи» в боте перед повтором.');
              }
              return;
            }
            if (r.ok && data.success) {
              state.catalogBookingIdempotencyKey = null;
              var okMsg = '✅ <b>Вы записаны</b>.<br><br>Ожидайте подтверждения от тренера в боте.';
              if (data.used_primary_venue_for_online_booking) {
                okMsg += '<br><span style="color: var(--tg-theme-hint-color); font-size: 14px; display: inline-block; margin-top: 10px;">Запись создана на <strong>основную площадку</strong> тренера. Чтобы заниматься на площадке из вашего фильтра — оставьте заявку, тренер согласует место.</span>';
              }
              prefetch.firstPageKey = null;
              prefetch.firstPageData = null;
              clearCatalogSessionStorageCache();
              document.getElementById('successText').innerHTML = okMsg;
              persistCatalogFilters(state.selectedTrainer && state.selectedTrainer.id);
              showScreen('screenSuccess');
              getClientSession().then(function(session) {
                applySessionToState(session);
                renderSummary();
                updateBookingNameFieldsVisibility();
              }).catch(function() {});
            } else {
              alert((data && data.detail) || 'Не удалось записаться');
            }
          });
        }).catch(function() {
          alert(
            'Сеть не ответила. Запись могла всё равно создаться — проверьте «Мои записи» в боте. ' +
              'Повтор с тем же слотом использует тот же ключ запроса и возвращает успех, если бронь уже есть.'
          );
        }).finally(function() { btn.disabled = false; });
      };


      function closeCatalogSuccessToHubOrApp() {
        if (typeof window.navigateClientHome === 'function') {
          window.navigateClientHome();
          return;
        }
        closeApp();
      }

      document.getElementById('btnCloseSuccess').onclick = closeCatalogSuccessToHubOrApp;

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
        if (!state.cityId || !state.serviceId) {
          alert('Сначала выберите город и занятие в параметрах поиска.');
          state.returnToSummary = true;
          renderSummary();
          showScreen('screenSummary');
          switchTab('catalog');
          return;
        }
        state.requestForTrainer = null;
        state.requestFormOpenedFrom = 'trainerList';
        document.getElementById('requestComment').value = '';
        updateRequestFormContext();
        getClientSession().then(function(session) {
          applySessionToState(session, { bookingFormRefresh: true });
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
        function proceedFind() {
          if (!state.cityId) {
            state.returnToSummary = true;
            loadCities();
            showScreen('screenCity');
            return;
          }
          if (!state.serviceId) {
            state.returnToSummary = true;
            loadServices();
            showScreen('screenService');
            return;
          }
          state.returnToSummary = true;
          state.offset = 0;
          loadCatalogList();
          showScreen('screenTrainers');
        }
        if (state.catalogScenarioStub && !state.serviceId) {
          applyScenarioService(state.catalogScenarioStub).then(function() {
            renderSummary();
            proceedFind();
          });
          return;
        }
        if (!state.cityId) {
          proceedFind();
          return;
        }
        if (!state.serviceId) {
          proceedFind();
          return;
        }
        proceedFind();
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
        var backSvc = document.getElementById('backToService');
        if (backSvc) backSvc.style.display = 'block';
        var backCity = document.getElementById('backToCity');
        if (backCity) backCity.style.display = 'block';
        // showScreen('screenSummary') runs switchTab(state.activeTab); my_trainer would call openMyTrainerCard() and leave the summary empty.
        state.activeTab = 'catalog';
        renderSummary();
        showScreen('screenSummary');
      }
      (function bindArenaScreenControls() {
        var anyBtn = document.getElementById('arenaAnyBtn');
        if (anyBtn) anyBtn.onclick = clearArenaScreenSelection;
        var applyBtn = document.getElementById('arenaApplyBtn');
        if (applyBtn) applyBtn.onclick = commitArenaScreenSelection;
      })();

      wireCatalogScenarioChips();
      fetchCatalogServices().then(function() {
        syncScenarioChipSelection();
      });

      Promise.all([loadTrainerEdges(), getClientSession()])
        .then(function(results) {
          var session = results[1];
          var qp = new URLSearchParams(window.location.search || '');
          applySessionToState(session);
          var rawDeepTid = qp.get('trainer_id');
          var deepTidParsed = rawDeepTid != null && rawDeepTid !== '' ? parseInt(rawDeepTid, 10) : NaN;
          var deepTrainerFromUrl = !isNaN(deepTidParsed) && deepTidParsed > 0 ? deepTidParsed : null;
          var primaryTid = resolveCatalogAutoTrainerIdFromEdges();
          if (deepTrainerFromUrl != null) {
            state.trainerId = deepTrainerFromUrl;
          } else if (primaryTid != null) {
            state.trainerId = primaryTid;
          }
          updateBookingNameFieldsVisibility();
          updateRequestNameFieldsVisibility();
          /* From "Мои тренеры" / saved hub: open catalog list, not auto-jump to session primary trainer card */
          var forceCatalogBrowse = qp.get('tab') === 'catalog';
          var returnCtx = (function() {
            var tid = qp.get('trainer_id');
            if (!tid) return null;
            var id = parseInt(tid, 10);
            if (!id) return null;
            return {
              trainer_id: id,
              city_id: qp.get('city_id'),
              service_id: qp.get('service_id'),
              arena_id: qp.get('arena_id'),
              arena_ids: qp.get('arena_ids'),
              offset: qp.get('offset'),
              service_price_variant_id: qp.get('service_price_variant_id'),
            };
          })();
          if (returnCtx) {
            if (returnCtx.city_id != null) state.cityId = parseInt(returnCtx.city_id, 10) || null;
            if (returnCtx.service_id != null) state.serviceId = parseInt(returnCtx.service_id, 10) || null;
            // Deep-link supports both `arena_ids=1,2,3` (multi) and legacy `arena_id=1` (single).
            if (returnCtx.arena_ids != null && returnCtx.arena_ids !== '') {
              var deepIds = returnCtx.arena_ids.split(',').map(function(s) { return parseInt(s, 10); }).filter(function(n) { return !isNaN(n); });
              if (deepIds.length) setArenaSelection(deepIds, deepIds.map(function() { return 'Арена'; }));
              else clearArenaSelection();
            } else if (returnCtx.arena_id != null) {
              var deepOne = returnCtx.arena_id === '' ? null : (parseInt(returnCtx.arena_id, 10) || null);
              if (deepOne) setArenaSelection([deepOne], ['Арена']);
              else clearArenaSelection();
            }
            if (returnCtx.offset != null) state.offset = Math.max(0, parseInt(returnCtx.offset, 10) || 0);
            var dVariant = returnCtx.service_price_variant_id;
            if (dVariant != null && dVariant !== '') {
              var dv = parseInt(dVariant, 10);
              if (!isNaN(dv) && dv > 0) state.bookingContextServicePriceVariantId = dv;
            }
          }
          function showInitialScreen() {
            fetchCatalogServices(state.cityId || null)
              .then(function() {
                syncScenarioChipSelection();
                renderSummary();
                showScreen('screenSummary');
                switchTab(state.activeTab || 'catalog');
                if (state.cityId && state.serviceId) prefetchFirstPageIfNeeded();
              })
              .catch(function() {
                renderSummary();
                showScreen('screenSummary');
                switchTab(state.activeTab || 'catalog');
              });
          }
          /* Deep link ?trainer_id= — открыть карточку напрямую (в т.ч. возврат из book.html) */
          if (returnCtx && returnCtx.trainer_id) {
            loadTrainerById(returnCtx.trainer_id).then(function(t) {
              if (t) {
                state.trainerId = t.id != null ? Number(t.id) : returnCtx.trainer_id;
                state.selectedTrainer = t;
                state.trainerName = trainerName(t);
                reconcileCatalogServiceWithTrainerAsync(t).then(function() {
                  initTrainerSlotsArenaFilterFromCatalog(t);
                  renderTrainerDetail();
                  showScreen('screenTrainerDetail');
                });
                return;
              }
              if (state.trainerId) {
                state.openedFromMyTrainerTab = true;
                loadTrainerById(state.trainerId).then(function(t2) {
                  if (t2) {
                    state.trainerId = t2.id != null ? Number(t2.id) : state.trainerId;
                    state.selectedTrainer = t2;
                    state.trainerName = trainerName(t2);
                    reconcileCatalogServiceWithTrainerAsync(t2).then(function() {
                      initTrainerSlotsArenaFilterFromCatalog(t2);
                      renderTrainerDetail();
                      showScreen('screenTrainerDetail');
                    });
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
                    state.trainerId = t2.id != null ? Number(t2.id) : state.trainerId;
                    state.selectedTrainer = t2;
                    state.trainerName = trainerName(t2);
                    reconcileCatalogServiceWithTrainerAsync(t2).then(function() {
                      initTrainerSlotsArenaFilterFromCatalog(t2);
                      renderTrainerDetail();
                      showScreen('screenTrainerDetail');
                    });
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
          /* Session has selected primary trainer — normally open their card. ``?tab=catalog`` skips this (browse list). */
          if (state.trainerId && !forceCatalogBrowse) {
            state.openedFromMyTrainerTab = true;
            loadTrainerById(state.trainerId).then(function(t) {
              if (t) {
                state.trainerId = t.id != null ? Number(t.id) : state.trainerId;
                state.selectedTrainer = t;
                state.trainerName = trainerName(t);
                reconcileCatalogServiceWithTrainerAsync(t).then(function() {
                  initTrainerSlotsArenaFilterFromCatalog(t);
                  renderTrainerDetail();
                  showScreen('screenTrainerDetail');
                });
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
            applySessionToState(session, { bookingFormRefresh: true });
            if (state.cityId && state.serviceId) {
              loadCatalogList({ silent: true });
            }
          }).catch(function() {});
        }, 400);
      });

      // Keep first-page prefetch hot while user is on summary and updates filters.
      document.addEventListener('click', function(e) {
        var svcPick = e.target && e.target.closest && e.target.closest('#trainerDetailTop [data-catalog-service-select]');
        if (svcPick) {
          var raw = svcPick.getAttribute('data-catalog-service-select');
          var sidNum = raw != null && raw !== '' ? parseInt(raw, 10) : NaN;
          if (!isNaN(sidNum)) window.selectTrainerService(sidNum);
          return;
        }
        var actionBtn = e.target && e.target.closest && e.target.closest('#summaryRows .catalog-filter-tile, #summaryRows .summary-row-clickable, #tabCatalog, #tabMyTrainer');
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

      (function setupServiceSummaryModal() {
        var modal = document.getElementById('serviceSummaryModal');
        var closeBtn = document.getElementById('serviceSummaryModalClose');
        if (modal) {
          modal.addEventListener('click', function(e) {
            if (e.target === modal) closeServiceSummaryModal();
          });
        }
        if (closeBtn) closeBtn.addEventListener('click', closeServiceSummaryModal);
        document.addEventListener('keydown', function(e) {
          if (e.key !== 'Escape') return;
          if (modal && modal.classList.contains('show')) closeServiceSummaryModal();
        });
      })();
    })();
