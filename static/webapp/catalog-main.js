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
            var darkUi = tg.colorScheme === 'dark';
            var bgHex = darkUi ? '#0B0C0E' : '#F1F3F2';
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
        /** Cached trainer count for summary CTA (city+service+arena filter). */
        catalogOfferCount: null,
        catalogOfferCountKey: null,
        offset: 0,
        limit: 10,
        selectedTrainer: null,
        collectiveSlug: null,
        collectiveBrand: null,
        centerSessions: null,
        clientCenterPasses: null,
        centerBookingDraft: null,
        centerPassOrderDraft: null,
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
        /** When true, skip auto-pick from slot availability (URL arena or user toggled chips). */
        trainerSlotsArenaFilterExplicit: false,
        /** Deep link ?slot_id= — open booking form once slots for the card are loaded. */
        pendingDeepLinkSlotId: null,
        selectedSlot: null,
        returnToSummary: false,
        requestForTrainer: null,
        requestFormOpenedFrom: null,
        activeTab: 'catalog',
        /** Invite / ?trainer_id= deep link: pin «Мой тренер» to this id over hub booking primary. */
        deepLinkTrainerId: null,
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
        invalidateCatalogOfferCount();
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

      function findSlotById(slots, slotId) {
        var sid = parseInt(slotId, 10);
        if (!slots || !slots.length || isNaN(sid) || sid <= 0) return null;
        for (var i = 0; i < slots.length; i++) {
          if (parseInt(slots[i].id, 10) === sid) return slots[i];
        }
        return null;
      }

      /** Same path as tapping a slot row on the trainer card — service/tier can be changed on the form. */
      function openCatalogBookingFormForSlot(slot) {
        if (!slot) return false;
        document.body.classList.remove('catalog-booking-deeplink');
        state.selectedSlot = slot;
        assignCatalogBookingIdempotencyKeyForSlot();
        var labelEl = document.getElementById('bookingFormSlotLabel');
        if (labelEl) {
          labelEl.textContent = 'Выбрано: ' + formatSlotSelectionSummary(state.selectedSlot);
        }
        var commentEl = document.getElementById('bookingComment');
        if (commentEl) commentEl.value = '';
        refreshClientPhoneForBookingForm(function() {
          if (
            state.selectedTrainer &&
            (isHubDirectBookEntry() ||
              state.bookingContextServiceId != null ||
              state.lastCreatedBookingServiceId != null)
          ) {
            applyCatalogRepeatBookingDefaults(state.selectedTrainer);
          }
          prefillBookingPhoneField();
          updateBookingVenueHint();
          updateBookingFormServiceAndTiers();
          if (window.BookingClient) {
            window.BookingClient.emitBookingAnalytics('booking_step_viewed', { step: 'form', host: 'catalog' });
          }
          showScreen('screenBookingForm');
        });
        return true;
      }

      function maybeOpenPendingDeepLinkSlotBooking(trainer, slots) {
        var pendingSid = state.pendingDeepLinkSlotId;
        if (pendingSid == null || pendingSid === '') return false;
        state.pendingDeepLinkSlotId = null;
        var slot = findSlotById(slots, pendingSid);
        if (!slot) {
          document.body.classList.remove('catalog-booking-deeplink');
          showToast('Это окно уже занято или недоступно. Выберите другое время.');
          return false;
        }
        openCatalogBookingFormForSlot(slot);
        return true;
      }

      function isCatalogSlotBookingDeepLink(qp) {
        if (!qp) qp = new URLSearchParams(window.location.search || '');
        return !!(qp.get('trainer_id') && qp.get('slot_id'));
      }

      function isCatalogBookActionDeepLink(qp) {
        if (!qp) qp = new URLSearchParams(window.location.search || '');
        if (qp.get('action') !== 'book') return false;
        if (isCatalogSlotBookingDeepLink(qp)) return false;
        var raw = qp.get('trainer_id');
        if (raw == null || raw === '') return false;
        var id = parseInt(raw, 10);
        return !isNaN(id) && id > 0;
      }

      function isCatalogTrainerDetailDeepLink(qp) {
        if (!qp) qp = new URLSearchParams(window.location.search || '');
        if (qp.get('tab') === 'catalog') return false;
        if (isCatalogSlotBookingDeepLink(qp)) return false;
        if (isCatalogBookActionDeepLink(qp)) return false;
        var raw = qp.get('trainer_id');
        if (raw == null || raw === '') return false;
        var id = parseInt(raw, 10);
        return !isNaN(id) && id > 0;
      }

      function isHubDirectBookEntry() {
        try {
          var qp = new URLSearchParams(window.location.search || '');
          return qp.get('from') === 'hub' && qp.get('action') === 'book';
        } catch (eHub) {
          return false;
        }
      }

      function clearCatalogDeepLinkShellClasses() {
        document.documentElement.classList.remove(
          'catalog-trainer-deeplink',
          'catalog-booking-deeplink',
          'catalog-slotpick-deeplink'
        );
        document.body.classList.remove(
          'catalog-trainer-deeplink',
          'catalog-booking-deeplink',
          'catalog-slotpick-deeplink'
        );
      }

      function activateCatalogBookingDeepLinkShell() {
        clearCatalogDeepLinkShellClasses();
        document.body.classList.add('catalog-booking-deeplink');
        document.querySelectorAll('[data-screen]').forEach(function(el) { el.classList.remove('active'); });
        var form = document.getElementById('screenBookingForm');
        if (form) form.classList.add('active');
        syncClientShellTabBarForScreen('screenBookingForm');
      }

      function activateCatalogSlotPickDeepLinkShell() {
        clearCatalogDeepLinkShellClasses();
        document.body.classList.add('catalog-slotpick-deeplink');
        document.querySelectorAll('[data-screen]').forEach(function(el) { el.classList.remove('active'); });
        var pick = document.getElementById('screenSlotPick');
        if (pick) pick.classList.add('active');
        var list = document.getElementById('slotPickList');
        if (list) {
          list.innerHTML =
            '<div class="catalog-trainer-detail-skel catalog-trainer-detail-skel--compact" role="status" aria-busy="true" aria-label="Загрузка слотов">' +
            '<div class="catalog-skel-shimmer catalog-skel-line"></div>' +
            '<div class="catalog-skel-shimmer catalog-skel-line"></div>' +
            '<div class="catalog-skel-shimmer catalog-skel-line"></div>' +
            '</div>';
        }
        syncClientShellTabBarForScreen('screenSlotPick');
      }

      function activateCatalogTrainerDeepLinkShell() {
        clearCatalogDeepLinkShellClasses();
        document.documentElement.classList.add('catalog-trainer-deeplink');
        document.body.classList.add('catalog-trainer-deeplink');
        document.querySelectorAll('[data-screen]').forEach(function(el) { el.classList.remove('active'); });
        var detail = document.getElementById('screenTrainerDetail');
        if (detail) detail.classList.add('active');
        paintTrainerDetailSkeleton();
        syncClientShellTabBarForScreen('screenTrainerDetail');
      }

      /** Full-card shimmer while trainer profile loads (deep link / list tap). */
      function buildTrainerDetailSkeletonHtml() {
        return (
          '<div class="catalog-trainer-detail-skel" role="status" aria-busy="true" aria-label="Загрузка карточки тренера">' +
            '<div class="catalog-trainer-detail-skel__photo catalog-skel-shimmer"></div>' +
            '<div class="catalog-trainer-detail-skel__header">' +
              '<div class="catalog-skel-line catalog-trainer-detail-skel__name catalog-skel-shimmer"></div>' +
              '<div class="catalog-skel-line catalog-trainer-detail-skel__rating catalog-skel-shimmer"></div>' +
            '</div>' +
            '<div class="catalog-trainer-detail-skel__stats">' +
              '<div class="catalog-trainer-detail-skel__stat catalog-skel-shimmer"></div>' +
              '<div class="catalog-trainer-detail-skel__stat catalog-skel-shimmer"></div>' +
              '<div class="catalog-trainer-detail-skel__stat catalog-skel-shimmer"></div>' +
            '</div>' +
            '<div class="catalog-skel-line catalog-trainer-detail-skel__section catalog-skel-shimmer"></div>' +
            '<div class="catalog-trainer-detail-skel__service catalog-skel-shimmer"></div>' +
            '<div class="catalog-trainer-detail-skel__service catalog-trainer-detail-skel__service--short catalog-skel-shimmer"></div>' +
          '</div>'
        );
      }

      function buildTrainerDetailSlotsSkeletonHtml() {
        var rows = '';
        for (var i = 0; i < 3; i++) {
          rows += '<div class="catalog-trainer-detail-skel__slot-row catalog-skel-shimmer"></div>';
        }
        return (
          '<div class="catalog-trainer-detail-skel__slots-block" aria-hidden="true">' +
            '<div class="catalog-skel-line catalog-trainer-detail-skel__slots-title catalog-skel-shimmer"></div>' +
            rows +
          '</div>'
        );
      }

      function paintTrainerDetailSkeleton() {
        var top = document.getElementById('trainerDetailTop');
        if (top) top.innerHTML = buildTrainerDetailSkeletonHtml();
        var about = document.getElementById('trainerDetailAbout');
        if (about) {
          about.innerHTML = '';
          about.style.display = 'none';
        }
        var groups = document.getElementById('trainerDetailGroups');
        if (groups) groups.innerHTML = '';
        clearTrainerArenaSlotFilterBar();
        var slots = document.getElementById('trainerDetailSlots');
        if (slots) slots.innerHTML = buildTrainerDetailSlotsSkeletonHtml();
        var actions = document.getElementById('trainerDetailActions');
        if (actions) actions.innerHTML = '';
        var secondary = document.getElementById('trainerDetailSecondary');
        if (secondary) secondary.innerHTML = '';
        var rest = document.getElementById('trainerDetailRest');
        if (rest) rest.innerHTML = '';
      }

      /** Hub FAB / «Записаться снова»: skip marketing card, open slot picker directly. */
      function openTrainerDeepLinkSlotPick(returnCtx, explicitTrainerArenaIdsFromUrl, onFail) {
        loadTrainerById(returnCtx.trainer_id).then(function(t) {
          if (!t) {
            if (onFail) onFail();
            return;
          }
          state.trainerId = t.id != null ? Number(t.id) : returnCtx.trainer_id;
          state.selectedTrainer = t;
          state.trainerName = trainerName(t);
          var tid = t.id != null ? Number(t.id) : NaN;
          var sessionReq =
            !isNaN(tid) && tid > 0
              ? getClientSession({ forTrainerId: tid }).then(function(sess) {
                  applySessionToState(sess, { bookingFormRefresh: true });
                })
              : Promise.resolve();
          sessionReq
            .then(function() {
              return reconcileCatalogServiceWithTrainerAsync(t);
            })
            .then(function() {
              initTrainerSlotsArenaFilter(t, { explicitArenaIds: explicitTrainerArenaIdsFromUrl });
              return loadTrainerDetailSlots(t);
            })
            .then(function(slots) {
              state.slotsForTrainer = slots || [];
              if (state.pendingDeepLinkSlotId && maybeOpenPendingDeepLinkSlotBooking(t, slots)) return;
              clearCatalogDeepLinkShellClasses();
              renderSlotPickList();
              showScreen('screenSlotPick');
            })
            .catch(function() {
              clearCatalogDeepLinkShellClasses();
              state.slotsForTrainer = [];
              renderSlotPickList();
              showScreen('screenSlotPick');
            });
        }).catch(function() {
          if (onFail) onFail();
        });
      }

      /** trainer_id deep link: skip trainer card flash when slot_id targets booking form. */
      function openTrainerDeepLinkTrainerCard(returnCtx, explicitTrainerArenaIdsFromUrl, onFail) {
        loadTrainerById(returnCtx.trainer_id).then(function(t) {
          if (!t) {
            if (onFail) onFail();
            return;
          }
          state.trainerId = t.id != null ? Number(t.id) : returnCtx.trainer_id;
          state.selectedTrainer = t;
          state.trainerName = trainerName(t);
          reconcileCatalogServiceWithTrainerAsync(t).then(function() {
            initTrainerSlotsArenaFilter(t, { explicitArenaIds: explicitTrainerArenaIdsFromUrl });
            if (state.pendingDeepLinkSlotId) {
              loadTrainerDetailSlots(t)
                .then(function(slots) {
                  if (!maybeOpenPendingDeepLinkSlotBooking(t, slots)) {
                    clearCatalogDeepLinkShellClasses();
                    renderTrainerDetail();
                    showScreen('screenTrainerDetail');
                  }
                })
                .catch(function() {
                  clearCatalogDeepLinkShellClasses();
                  renderTrainerDetail();
                  showScreen('screenTrainerDetail');
                });
              return;
            }
            clearCatalogDeepLinkShellClasses();
            renderTrainerDetail();
            showScreen('screenTrainerDetail');
          });
        }).catch(function() {
          if (onFail) onFail();
        });
      }

      /** Avoid false «network error» when res.ok but body is not JSON or parse fails. */
      function catalogParseBookingJsonResponse(text) {
        if (window.BookingClient) return window.BookingClient.parseBookingJsonResponse(text);
        try {
          return JSON.parse(text || 'null');
        } catch (e) {
          return null;
        }
      }

      var catalogTrainerStickyObserver = null;

      function teardownCatalogTrainerStickyObserver() {
        if (catalogTrainerStickyObserver) {
          catalogTrainerStickyObserver.disconnect();
          catalogTrainerStickyObserver = null;
        }
      }

      function catalogTrainerStickyEligible() {
        return !!(
          state.slotsForTrainer &&
          state.slotsForTrainer.length > 0 &&
          state.selectedTrainer &&
          state.selectedTrainer.can_book === true
        );
      }

      /** Show fixed bottom CTA only while inline «Записаться» is off-screen — never duplicate both. */
      function installCatalogTrainerStickyObserver() {
        teardownCatalogTrainerStickyObserver();
        var bar = document.getElementById('catalogTrainerStickyCta');
        var anchor = document.getElementById('btnBookFromDetail');
        if (!bar || bar.hidden || !anchor) {
          if (bar) bar.classList.remove('catalog-trainer-sticky-cta--visible');
          return;
        }
        function setStickyVisible(show) {
          if (!bar || bar.hidden) return;
          if (show) bar.classList.add('catalog-trainer-sticky-cta--visible');
          else bar.classList.remove('catalog-trainer-sticky-cta--visible');
        }
        if (typeof IntersectionObserver !== 'function') {
          setStickyVisible(true);
          return;
        }
        /* Tab bar + sticky dock — inline CTA counts as visible before it sits under the bar. */
        catalogTrainerStickyObserver = new IntersectionObserver(
          function(entries) {
            var entry = entries[0];
            if (!entry) return;
            setStickyVisible(!entry.isIntersecting);
          },
          { root: null, threshold: 0, rootMargin: '0px 0px -140px 0px' }
        );
        catalogTrainerStickyObserver.observe(anchor);
      }

      function syncCatalogTrainerStickyCta(visible) {
        var el = document.getElementById('catalogTrainerStickyCta');
        if (!el) return;
        if (!visible) {
          el.hidden = true;
          el.classList.remove('catalog-trainer-sticky-cta--visible');
          teardownCatalogTrainerStickyObserver();
          return;
        }
        el.hidden = false;
        el.classList.remove('catalog-trainer-sticky-cta--visible');
        requestAnimationFrame(function() {
          installCatalogTrainerStickyObserver();
        });
      }

      /** Card / catalog filter wins over slot.snapshot: API may tag slots with another service_id while times are shared. */
      function catalogEffectiveServiceIdForBooking() {
        var t = state.selectedTrainer;
        var services = (t && t.services) ? t.services : [];
        if (window.BookingClient) {
          return window.BookingClient.effectiveServiceIdForBooking({
            trainerServices: services,
            filterServiceId: state.serviceId,
            slot: state.selectedSlot,
          });
        }
        var slot = state.selectedSlot;
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
        var sid = catalogEffectiveServiceIdForBooking();
        var t = state.selectedTrainer;
        if (window.BookingClient && t && t.services) {
          return window.BookingClient.getTiersForService(t.services, sid);
        }
        if (!t || !t.services) return [];
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
        if (window.BookingClient) {
          return window.BookingClient.priceVariantHint(
            {
              lastCreatedBookingServiceId: state.lastCreatedBookingServiceId,
              lastCreatedBookingPriceVariantId: state.lastCreatedBookingPriceVariantId,
              bookingContextServiceId: state.bookingContextServiceId,
              bookingContextServicePriceVariantId: state.bookingContextServicePriceVariantId,
            },
            effSid
          );
        }
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

      /** Switch service on booking form without leaving screenBookingForm (hub deep-link path). */
      function selectCatalogBookingService(serviceId) {
        if (!state.selectedTrainer) return;
        var sid = Number(serviceId);
        if (isNaN(sid) || sid <= 0) return;
        state.serviceId = sid;
        var services = state.selectedTrainer.services || [];
        var i;
        for (i = 0; i < services.length; i++) {
          if (Number(services[i].service_id) === sid) {
            state.serviceName = String(services[i].service_name || '').trim();
            break;
          }
        }
        if (window.history && window.history.replaceState) {
          var url = new URL(window.location.href);
          url.searchParams.set('service_id', sid);
          window.history.replaceState(null, '', url.toString());
        }
        var tid = state.selectedTrainer && state.selectedTrainer.id != null ? state.selectedTrainer.id : null;
        if (tid != null && state.cityId && state.serviceId != null) persistTrainerSelection(tid);
        updateBookingFormServiceAndTiers();
      }

      /** Server hints from GET /client/session?for_trainer_id — last booking service + tier. */
      function applyCatalogRepeatBookingDefaults(trainer) {
        var services = (trainer && trainer.services) || [];
        if (!services.length) return false;
        var allowed = {};
        services.forEach(function(s) {
          var id = s.service_id != null ? Number(s.service_id) : NaN;
          if (!isNaN(id) && id > 0) allowed[id] = s;
        });
        function pick(sid) {
          var num = Number(sid);
          if (isNaN(num) || !allowed[num]) return false;
          state.serviceId = num;
          state.serviceName = String(allowed[num].service_name || '').trim();
          return true;
        }
        if (pick(state.bookingContextServiceId)) return true;
        if (pick(state.lastCreatedBookingServiceId)) return true;
        return false;
      }

      /** Услуга из фильтра + выбор тарифа при нескольких ценах (строгий режим API). Групповые слоты — без выбора тира. */
      function updateBookingFormServiceAndTiers() {
        var svcBlock = document.getElementById('bookingFormServiceBlock');
        var svcEl = document.getElementById('bookingFormServiceLine');
        var svcSelect = document.getElementById('bookingFormServiceSelect');
        var block = document.getElementById('bookingPriceTierBlockCatalog');
        var host = document.getElementById('bookingPriceTierRadiosCatalog');
        state.catalogBookingPriceVariantId = null;
        var effSid = catalogEffectiveServiceIdForBooking();
        var nm = effSid != null ? catalogServiceDisplayNameForId(effSid) : (state.serviceName || '').trim();
        var t = state.selectedTrainer;
        var services = (t && t.services) ? t.services : [];
        var slot = state.selectedSlot;
        var capRaw = slot && slot.capacity != null ? parseInt(slot.capacity, 10) : 1;
        var cap = isNaN(capRaw) ? 1 : capRaw;
        var isGroupSlot = cap > 1;
        if (svcBlock) {
          if (!services.length) {
            svcBlock.style.display = 'none';
            if (svcEl) {
              svcEl.style.display = 'none';
              svcEl.textContent = '';
            }
            if (svcSelect) {
              svcSelect.innerHTML = '';
              svcSelect.style.display = 'none';
            }
          } else if (services.length === 1) {
            var lineNm = nm || String(services[0].service_name || '').trim();
            if (!lineNm) {
              svcBlock.style.display = 'none';
            } else {
              svcBlock.style.display = 'block';
              if (svcEl) {
                svcEl.style.display = 'block';
                svcEl.textContent = lineNm;
              }
            }
            if (svcSelect) {
              svcSelect.innerHTML = '';
              svcSelect.style.display = 'none';
            }
          } else {
            svcBlock.style.display = 'block';
            if (svcEl) {
              svcEl.style.display = 'none';
              svcEl.textContent = '';
            }
            if (svcSelect) {
              svcSelect.style.display = 'block';
              svcSelect.innerHTML = '';
              var pickSid = effSid;
              services.forEach(function(s) {
                var sid = s.service_id != null ? Number(s.service_id) : NaN;
                if (isNaN(sid) || sid <= 0) return;
                var opt = document.createElement('option');
                opt.value = String(sid);
                var label = String(s.service_name || '—').trim();
                var priceLabel = formatCatalogServicePrice(s);
                if (priceLabel && priceLabel !== 'по запросу') {
                  label += ' — ' + priceLabel.replace(/<[^>]+>/g, '');
                }
                opt.textContent = label;
                svcSelect.appendChild(opt);
              });
              if (pickSid != null && svcSelect.querySelector('option[value="' + String(pickSid) + '"]')) {
                svcSelect.value = String(pickSid);
              } else if (svcSelect.options.length) {
                svcSelect.selectedIndex = 0;
              }
            }
          }
        }
        if (!block || !host) return;
        host.innerHTML = '';
        if (isGroupSlot) {
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
          var priceHtml = escapeHtml(priceNum) + ' <i class="nbrb-icon">&#xe901;</i>';
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
          btn.onclick = function() {
            if (sid === 'screenSlotPick' && isHubDirectBookEntry()) {
              if (window.BookingClient && typeof window.BookingClient.navigateBookingReturn === 'function') {
                window.BookingClient.navigateBookingReturn('hub');
              } else if (typeof window.navigateClientHome === 'function') {
                window.navigateClientHome();
              } else if (canBrowserGoBack()) {
                window.history.back();
              }
              return;
            }
            if (sid === 'screenBookingForm' && isHubDirectBookEntry()) {
              renderSlotPickList();
              showScreen('screenSlotPick');
              return;
            }
            showScreen('screenTrainerDetail');
          };
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

      function syncClientShellTabBarForScreen(screenId) {
        var shell = window.ClientShell;
        if (!shell || typeof shell.setTabBarVisible !== 'function') return;
        shell.setTabBarVisible(screenId === 'screenSummary');
        if (typeof shell.setForcedTab === 'function') {
          shell.setForcedTab(screenId === 'screenSummary' ? 'catalog' : null);
        }
      }

      function setCatalogListLoading(el, count) {
        if (!el) return;
        if (window.ClientShell && typeof window.ClientShell.renderSkeletonList === 'function') {
          window.ClientShell.renderSkeletonList(el, count || 3);
        } else {
          el.innerHTML = '<div class="loading">Загрузка...</div>';
        }
      }

      function showScreen(id) {
        document.querySelectorAll('[data-screen]').forEach(function(el) { el.classList.remove('active'); });
        var el = document.getElementById(id);
        if (el) el.classList.add('active');
        if (id !== 'screenCity') resetPickerSearch('city');
        if (id !== 'screenArena') resetPickerSearch('arena');
        if (id === 'screenCity') focusPickerSearch('city');
        if (id === 'screenArena') focusPickerSearch('arena');
        if (id === 'screenTrainerDetail') {
          document.querySelectorAll('#catalogTabsOnDetail .tab-btn').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.tab === 'my_trainer');
          });
        }
        if (id === 'screenSummary') {
          renderSummary();
          switchTab(state.activeTab);
        }
        syncClientShellTabBarForScreen(id);
        syncCatalogHeaderBack();
        syncCatalogTrainerStickyCta(id === 'screenTrainerDetail' && catalogTrainerStickyEligible());
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
        if (state.collectiveSlug) params.collective_slug = state.collectiveSlug;
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
        var colPart = state.collectiveSlug || '';
        return [mode, state.cityId || 0, state.serviceId || 0, arenaIdsCacheKey(), state.limit || 10, dayPart, timePart, colPart].join(':');
      }

      function collectiveLocationLine(brand) {
        if (!brand) return '';
        var contacts = brand.contacts || {};
        var address = (contacts.address || '').trim();
        if (address) return address;
        if (brand.default_city_name) return String(brand.default_city_name).trim();
        return '';
      }

      function isCenterCatalogBrand(brand) {
        return !!(brand && brand.catalog_mode === 'center_grid');
      }

      function isStudioRosterBrand(brand) {
        return !!(brand && brand.catalog_mode === 'studio_roster');
      }

      function resolveCatalogModeFromBrand(brand) {
        if (isCenterCatalogBrand(brand)) return 'center_schedule';
        return 'trainers';
      }

      function collectiveContactLines(brand) {
        var contacts = (brand && brand.contacts) || {};
        var lines = [];
        var phone = (contacts.phone || '').trim();
        var tg = (contacts.telegram || '').trim();
        var ig = (contacts.instagram || '').trim();
        var address = (contacts.address || '').trim();
        if (phone) lines.push('<div class="empty-state-text"><strong>Телефон:</strong> ' + phoneCallHtml(phone) + '</div>');
        if (tg) lines.push('<div class="empty-state-text"><strong>Telegram:</strong> ' + escapeHtml(tg) + '</div>');
        if (ig) lines.push('<div class="empty-state-text"><strong>Instagram:</strong> ' + escapeHtml(ig) + '</div>');
        if (address) lines.push('<div class="empty-state-text"><strong>Адрес:</strong> ' + escapeHtml(address) + '</div>');
        return lines.join('');
      }

      function buildStudioRosterEmptyHtml(brand) {
        var name = escapeHtml((brand && brand.display_name) || 'Студия');
        var contacts = collectiveContactLines(brand);
        return '<div class="empty catalog-collective-roster-empty">' +
          '<p class="empty-state-text"><strong>' + name + '</strong> скоро откроется — команда набирает тренеров.</p>' +
          (contacts || '<p class="empty-state-text">Следите за обновлениями в наших соцсетях.</p>') +
          '</div>';
      }

      function restoreDefaultCatalogModeTabs() {
        var row = document.getElementById('catalogListMode');
        if (!row) return;
        row.hidden = false;
        row.innerHTML =
          '<button type="button" class="catalog-mode-btn active" data-mode="trainers" role="tab" aria-selected="true">Тренеры</button>' +
          '<button type="button" class="catalog-mode-btn" data-mode="groups" role="tab" aria-selected="false">Группы с набором</button>';
        row.removeAttribute('data-bound');
      }

      function syncCollectiveCatalogModeTabs(brand) {
        var row = document.getElementById('catalogListMode');
        if (!row) return;
        if (brand && isCenterCatalogBrand(brand) && brand.show_coaches_catalog_tab) {
          row.hidden = false;
          row.innerHTML =
            '<button type="button" class="catalog-mode-btn' + (state.catalogMode === 'center_coaches' ? '' : ' active') + '" data-mode="center_schedule" role="tab" aria-selected="' + (state.catalogMode === 'center_coaches' ? 'false' : 'true') + '">Расписание</button>' +
            '<button type="button" class="catalog-mode-btn' + (state.catalogMode === 'center_coaches' ? ' active' : '') + '" data-mode="center_coaches" role="tab" aria-selected="' + (state.catalogMode === 'center_coaches' ? 'true' : 'false') + '">Тренеры</button>';
          row.removeAttribute('data-bound');
          initCatalogModeToggle();
          return;
        }
        if (brand && isCenterCatalogBrand(brand)) {
          row.hidden = true;
          return;
        }
        restoreDefaultCatalogModeTabs();
        initCatalogModeToggle();
      }

      function applyCollectiveHero(brand) {
        var hero = document.getElementById('catalogHero');
        var titleEl = document.getElementById('catalogHeroTitle');
        var venueEl = document.getElementById('catalogHeroVenue');
        var leadEl = document.getElementById('catalogHeroLead');
        var aboutEl = document.getElementById('catalogHeroAbout');
        var galleryEl = document.getElementById('catalogHeroGallery');
        var logoEl = document.getElementById('catalogHeroLogo');
        var poweredEl = document.getElementById('catalogHeroPowered');
        if (!brand || !state.collectiveSlug) {
          document.body.classList.remove('catalog-collective-mode');
          document.documentElement.style.removeProperty('--catalog-collective-accent');
          document.documentElement.style.removeProperty('--catalog-collective-accent-soft');
          document.documentElement.style.removeProperty('--catalog-collective-accent-border');
          if (titleEl) titleEl.textContent = 'Найдите тренера';
          if (venueEl) { venueEl.hidden = true; venueEl.textContent = ''; }
          if (leadEl) leadEl.textContent = 'Город и занятие — покажем свободные слоты на аренах.';
          if (aboutEl) { aboutEl.hidden = true; aboutEl.textContent = ''; }
          if (galleryEl) { galleryEl.hidden = true; galleryEl.innerHTML = ''; }
          if (logoEl) { logoEl.hidden = true; logoEl.removeAttribute('src'); }
          if (hero) hero.style.backgroundImage = '';
          if (hero) hero.classList.remove('catalog-hero--cover');
          if (poweredEl) { poweredEl.hidden = true; poweredEl.textContent = ''; }
          restoreDefaultCatalogModeTabs();
          initCatalogModeToggle();
          return;
        }
        document.body.classList.add('catalog-collective-mode');
        var accent = brand.accent || {};
        if (accent.accent) document.documentElement.style.setProperty('--catalog-collective-accent', accent.accent);
        if (accent.accent_soft) document.documentElement.style.setProperty('--catalog-collective-accent-soft', accent.accent_soft);
        if (accent.accent_border) document.documentElement.style.setProperty('--catalog-collective-accent-border', accent.accent_border);
        if (titleEl) titleEl.textContent = brand.display_name || state.collectiveSlug;
        var locationLine = collectiveLocationLine(brand);
        if (venueEl) {
          if (locationLine) {
            venueEl.textContent = locationLine;
            venueEl.hidden = false;
          } else {
            venueEl.hidden = true;
            venueEl.textContent = '';
          }
        }
        if (leadEl) {
          if (brand.hero_variant === 'center') {
            leadEl.textContent = brand.tagline || 'Расписание центра — выберите окно и формат визита.';
          } else {
            leadEl.textContent = brand.tagline ||
              'Тренеры студии — выберите город и занятие, как в обычном каталоге.';
          }
        }
        if (logoEl) {
          if (brand.logo_url) {
            logoEl.src = brand.logo_url;
            logoEl.hidden = false;
          } else {
            logoEl.hidden = true;
            logoEl.removeAttribute('src');
          }
        }
        if (hero) {
          if (brand.cover_url) {
            hero.classList.add('catalog-hero--cover');
            hero.style.backgroundImage =
              'linear-gradient(180deg, rgba(0,0,0,0.08) 0%, rgba(0,0,0,0.55) 100%), url(' + brand.cover_url + ')';
            hero.style.backgroundSize = 'cover';
            hero.style.backgroundPosition = 'center';
          } else {
            hero.classList.remove('catalog-hero--cover');
            hero.style.backgroundImage = '';
          }
        }
        if (aboutEl) {
          if (brand.about) {
            aboutEl.textContent = brand.about;
            aboutEl.hidden = false;
          } else {
            aboutEl.hidden = true;
            aboutEl.textContent = '';
          }
        }
        if (galleryEl) {
          var gallery = brand.gallery || [];
          if (gallery.length) {
            galleryEl.innerHTML = gallery.map(function(item) {
              return '<img src="' + escapeHtml(item.url) + '" alt="" loading="lazy" />';
            }).join('');
            galleryEl.hidden = false;
          } else {
            galleryEl.hidden = true;
            galleryEl.innerHTML = '';
          }
        }
        if (poweredEl) {
          if (state.collectiveSlug) {
            poweredEl.hidden = false;
            poweredEl.textContent = 'Powered by ' + (brand.powered_by || 'Glide');
          } else {
            poweredEl.hidden = true;
            poweredEl.textContent = '';
          }
        }
      }

      var CENTER_ATTENDANCE_MODES = [
        {
          id: 'lane_self',
          emoji: '🎯',
          title: 'Дорожка',
          subtitle: 'Самостоятельная тренировка',
          needsCoach: false,
          needsGuests: false,
        },
        {
          id: 'lane_with_guest',
          emoji: '👥',
          title: 'Дорожка + гость',
          subtitle: 'Вы и сопровождающий на дорожке',
          needsCoach: false,
          needsGuests: true,
          minGuests: 1,
        },
        {
          id: 'lane_own_coach',
          emoji: '🏋️',
          title: 'Со своим тренером',
          subtitle: 'Дорожка; тренер свой (не из центра)',
          needsCoach: false,
          needsGuests: false,
          optionalGuests: true,
        },
        {
          id: 'center_coach_individual',
          emoji: '🎓',
          title: 'Индивидуально',
          subtitle: 'Занятие с тренером центра',
          needsCoach: true,
          coachMode: true,
        },
        {
          id: 'center_coach_pair',
          emoji: '🤝',
          title: 'Парная',
          subtitle: 'Вы + партнёр с тренером центра',
          needsCoach: true,
          coachMode: true,
          minGuests: 1,
        },
      ];

      function centerBookingHapticSelection() {
        if (window.ClientShell && typeof window.ClientShell.hapticSelection === 'function') {
          window.ClientShell.hapticSelection();
        } else if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.selectionChanged === 'function') {
          tg.HapticFeedback.selectionChanged();
        }
      }

      function formatCenterSessionWhen(session) {
        if (!session) return '';
        var datePart = session.slot_date || '';
        try {
          var parts = String(datePart).split('-');
          if (parts.length === 3) {
            var d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
            var weekdays = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
            var months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
            datePart = weekdays[d.getDay()] + ', ' + d.getDate() + ' ' + months[d.getMonth()];
          }
        } catch (e) {}
        return datePart + ' · ' + (session.start_time || '') + '–' + (session.end_time || '');
      }

      function formatCenterSeatsLabel(seats) {
        var n = Number(seats);
        if (isNaN(n) || n < 0) return '—';
        if (n === 1) return '1 место';
        if (n >= 2 && n <= 4) return n + ' места';
        return n + ' мест';
      }

      function buildCenterPriceBreakdown(mode, guestCount, tariffs) {
        var guest = Number((tariffs && tariffs.guest_surcharge_cents) != null ? tariffs.guest_surcharge_cents : 1500);
        var guests = Math.max(0, parseInt(guestCount, 10) || 0);
        var guestWord = guests === 1 ? 'гость' : (guests >= 2 && guests <= 4 ? 'гостя' : 'гостей');
        if (mode === 'lane_self') return 'Дорожка 1 ч';
        if (mode === 'lane_with_guest') {
          return 'Дорожка + ' + guests + ' ' + guestWord + ' × ' + (guest / 100).toFixed(0) + ' BYN';
        }
        if (mode === 'lane_own_coach') {
          if (guests > 0) {
            return 'Дорожка + ' + guests + ' ' + guestWord + ' × ' + (guest / 100).toFixed(0) + ' BYN';
          }
          return 'Дорожка 1 ч · свой тренер';
        }
        if (mode === 'center_coach_individual') return 'Индивидуально с тренером центра';
        if (mode === 'center_coach_pair') return 'Парное занятие с тренером центра';
        return '';
      }

      function formatCenterPriceByn(cents) {
        if (cents == null || isNaN(cents)) return '—';
        var v = Number(cents) / 100;
        return (Math.round(v) === v ? v.toFixed(0) : v.toFixed(2)) + ' BYN';
      }

      function computeCenterBookingPriceCents(mode, guestCount, tariffs) {
        var lane = Number((tariffs && tariffs.lane_hour_cents) != null ? tariffs.lane_hour_cents : 2000);
        var guest = Number((tariffs && tariffs.guest_surcharge_cents) != null ? tariffs.guest_surcharge_cents : 1500);
        var coachInd = Number((tariffs && tariffs.coach_individual_cents) != null ? tariffs.coach_individual_cents : 7000);
        var coachPair = Number((tariffs && tariffs.coach_pair_cents) != null ? tariffs.coach_pair_cents : 10000);
        var guests = Math.max(0, parseInt(guestCount, 10) || 0);
        if (mode === 'lane_self') return lane;
        if (mode === 'lane_with_guest') return lane + guests * guest;
        if (mode === 'lane_own_coach') {
          var base = lane;
          if (guests > 0) base += guests * guest;
          return base;
        }
        if (mode === 'center_coach_individual') return coachInd;
        if (mode === 'center_coach_pair') return coachPair;
        return 0;
      }

      function centerPassKindForMode(mode) {
        if (mode === 'center_coach_individual' || mode === 'center_coach_pair') return 'coach';
        if (mode === 'lane_self' || mode === 'lane_with_guest' || mode === 'lane_own_coach') return 'lane';
        return null;
      }

      function centerPassCreditsForMode(mode) {
        if (mode === 'center_coach_pair') return 2;
        return 1;
      }

      function computeCenterBookingPriceWithPassCents(mode, guestCount, tariffs, passKind) {
        var guests = Math.max(0, parseInt(guestCount, 10) || 0);
        var guestRate = Number((tariffs && tariffs.guest_surcharge_cents) != null ? tariffs.guest_surcharge_cents : 1500);
        if (!passKind) return computeCenterBookingPriceCents(mode, guestCount, tariffs);
        if (passKind === 'lane') {
          if (mode === 'lane_with_guest') return guests * guestRate;
          if (mode === 'lane_own_coach' && guests > 0) return guests * guestRate;
          if (mode === 'lane_self') return 0;
          return computeCenterBookingPriceCents(mode, guestCount, tariffs);
        }
        if (passKind === 'coach' && (mode === 'center_coach_individual' || mode === 'center_coach_pair')) {
          return 0;
        }
        return computeCenterBookingPriceCents(mode, guestCount, tariffs);
      }

      function eligibleCenterPassesForMode(mode) {
        var passes = (state.clientCenterPasses && state.clientCenterPasses.passes) || [];
        var kind = centerPassKindForMode(mode);
        var credits = centerPassCreditsForMode(mode);
        if (!kind) return [];
        return passes.filter(function(p) {
          return p.pass_kind === kind && Number(p.sessions_remaining) >= credits;
        });
      }

      function loadClientCenterPasses() {
        if (!state.collectiveSlug) return Promise.resolve(null);
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return Promise.resolve(null);
        return fetch('/api/webapp/client/collective-passes?collective_slug=' + encodeURIComponent(state.collectiveSlug), {
          headers: { 'X-Telegram-Init-Data': initData },
          cache: 'no-store',
        })
          .then(function(r) {
            return r.json().then(function(d) {
              if (!r.ok) throw new Error((d && d.detail) || 'passes_failed');
              return d;
            });
          })
          .then(function(d) {
            state.clientCenterPasses = d;
            return d;
          })
          .catch(function() {
            state.clientCenterPasses = { passes: [] };
            return null;
          });
      }

      function findCenterSessionById(sessionId) {
        var sessions = (state.centerSessions && state.centerSessions.sessions) || [];
        for (var i = 0; i < sessions.length; i++) {
          if (Number(sessions[i].id) === Number(sessionId)) return sessions[i];
        }
        return null;
      }

      function centerBookingModeOptions(session) {
        var coaches = (session && session.assigned_coaches) || [];
        return CENTER_ATTENDANCE_MODES.filter(function(m) {
          if (m.coachMode && !coaches.length) return false;
          return true;
        });
      }

      function centerBookingErrorMessage(detail) {
        var raw = (detail || '').toString();
        var map = {
          'Session not available': 'Окно недоступно для записи',
          'Session full': 'Свободных мест больше нет',
          'Coach required for this mode': 'Выберите тренера центра',
          'Coach not assigned to session': 'Этот тренер не назначен на это окно',
          'Guest count required': 'Укажите количество гостей',
          'Center coach not allowed': 'Для этого формата тренер не нужен',
          'Client profile required': 'Не удалось определить профиль клиента',
          'Укажите имя': 'Укажите имя в профиле Telegram',
        };
        return map[raw] || raw || 'Не удалось записаться';
      }

      function formatCollectivePassValidity(product) {
        if (!product || product.validity_days == null) return 'без срока';
        return String(product.validity_days) + ' дн.';
      }

      function collectivePassKindLabel(kind) {
        return kind === 'coach' ? 'Тренер' : 'Дорожка';
      }

      function buildCollectivePassProductCard(product) {
        var visits = product.sessions_total != null ? product.sessions_total : '—';
        var price = formatCenterPriceByn(product.price_cents);
        var validity = formatCollectivePassValidity(product);
        var kindBadge = collectivePassKindLabel(product.pass_kind);
        return '<div class="catalog-collective-pass-card" data-pass-product-id="' + product.id + '">' +
          '<div class="catalog-collective-pass-card__head">' +
          '<span class="catalog-collective-pass-card__kind">' + escapeHtml(kindBadge) + '</span>' +
          '<span class="catalog-collective-pass-card__price">' + escapeHtml(price) + '</span>' +
          '</div>' +
          '<div class="catalog-collective-pass-card__name">' + escapeHtml(product.name || 'Абонемент') + '</div>' +
          '<p class="catalog-collective-pass-card__meta">' +
          escapeHtml(String(visits) + ' посещений · ' + validity) +
          '</p>' +
          '<button type="button" class="btn-primary catalog-collective-pass-order" data-pass-product-id="' + product.id + '">Оформить</button>' +
          '</div>';
      }

      function buildCenterPassesCatalogHtml(passProducts) {
        if (!passProducts || !passProducts.length) return '';
        var lane = passProducts.filter(function(p) { return p.pass_kind === 'lane'; });
        var coach = passProducts.filter(function(p) { return p.pass_kind === 'coach'; });
        var html = '<div class="catalog-collective-passes">' +
          '<div class="catalog-collective-passes-title">Абонементы центра</div>' +
          '<p class="catalog-collective-passes-hint">Оплата на месте — центр свяжется после заявки</p>';
        if (lane.length) {
          html += '<div class="catalog-collective-passes-group">' +
            '<div class="catalog-collective-passes-group__label">Дорожка</div>' +
            '<div class="catalog-collective-passes-grid">' +
            lane.map(buildCollectivePassProductCard).join('') +
            '</div></div>';
        }
        if (coach.length) {
          html += '<div class="catalog-collective-passes-group">' +
            '<div class="catalog-collective-passes-group__label">С тренером</div>' +
            '<div class="catalog-collective-passes-grid">' +
            coach.map(buildCollectivePassProductCard).join('') +
            '</div></div>';
        }
        html += '</div>';
        return html;
      }

      function bindCenterPassOrderButtons(panel) {
        if (!panel) return;
        panel.querySelectorAll('.catalog-collective-pass-order').forEach(function(btn) {
          btn.addEventListener('click', function() {
            centerBookingHapticSelection();
            var productId = parseInt(btn.getAttribute('data-pass-product-id'), 10);
            var products = (state.centerSessions && state.centerSessions.pass_products) || [];
            var product = products.find(function(p) { return Number(p.id) === productId; });
            if (!product) {
              if (tg && tg.showAlert) tg.showAlert('Абонемент не найден — обновите страницу');
              return;
            }
            openCenterPassOrderConfirm(product, btn);
          });
        });
      }

      function closeCenterPassOrderConfirm() {
        var modal = document.getElementById('centerPassOrderConfirmModal');
        if (modal) modal.hidden = true;
        state.centerPassOrderDraft = null;
      }

      function openCenterPassOrderConfirm(product, sourceBtn) {
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) {
          if (tg && tg.showAlert) tg.showAlert('Откройте каталог через клиентский бот Telegram');
          return;
        }
        state.centerPassOrderDraft = { product: product, button: sourceBtn || null };
        var textEl = document.getElementById('centerPassOrderConfirmText');
        if (textEl) {
          var visits = product.sessions_total != null ? product.sessions_total : '—';
          textEl.innerHTML =
            '<strong>' + escapeHtml(product.name || 'Абонемент') + '</strong><br>' +
            escapeHtml(collectivePassKindLabel(product.pass_kind) + ' · ' + visits + ' посещений · ' +
              formatCollectivePassValidity(product) + ' · ' + formatCenterPriceByn(product.price_cents));
        }
        var modal = document.getElementById('centerPassOrderConfirmModal');
        if (modal) modal.hidden = false;
      }

      function submitCenterPassOrderRequest() {
        var draft = state.centerPassOrderDraft;
        if (!draft || !draft.product) return;
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return;
        if (!state.collectiveSlug) {
          if (tg && tg.showAlert) tg.showAlert('Центр не определён — обновите страницу');
          return;
        }
        var btn = draft.button;
        var sendBtn = document.getElementById('centerPassOrderConfirmSend');
        if (sendBtn) {
          sendBtn.disabled = true;
          sendBtn.textContent = 'Отправка…';
        }
        if (btn) {
          btn.disabled = true;
          btn.textContent = 'Отправка…';
        }
        fetch('/api/webapp/client/collective-pass-order/request', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData },
          body: JSON.stringify({
            collective_slug: state.collectiveSlug,
            collective_pass_product_id: draft.product.id,
          }),
        })
          .then(function(r) {
            return r.json().then(function(d) { return { ok: r.ok, data: d }; });
          })
          .then(function(o) {
            if (sendBtn) {
              sendBtn.disabled = false;
              sendBtn.textContent = 'Отправить заявку';
            }
            if (btn) {
              btn.disabled = false;
              btn.textContent = 'Оформить';
            }
            closeCenterPassOrderConfirm();
            if (o.ok && o.data && o.data.success) {
              if (window.ClientShell && typeof window.ClientShell.hapticSuccess === 'function') {
                window.ClientShell.hapticSuccess();
              }
              if (tg && tg.showAlert) {
                tg.showAlert('Заявка отправлена — центр свяжется с вами для оплаты');
              }
              return;
            }
            var detail = o.data && (o.data.detail || o.data.message);
            if (tg && tg.showAlert) tg.showAlert(detail || 'Не удалось отправить заявку');
          })
          .catch(function() {
            if (sendBtn) {
              sendBtn.disabled = false;
              sendBtn.textContent = 'Отправить заявку';
            }
            if (btn) {
              btn.disabled = false;
              btn.textContent = 'Оформить';
            }
            if (tg && tg.showAlert) tg.showAlert('Ошибка сети. Попробуйте ещё раз.');
          });
      }

      function initCenterPassOrderModal() {
        var cancelBtn = document.getElementById('centerPassOrderConfirmCancel');
        var sendBtn = document.getElementById('centerPassOrderConfirmSend');
        var backdrop = document.getElementById('centerPassOrderConfirmBackdrop');
        if (cancelBtn) cancelBtn.addEventListener('click', closeCenterPassOrderConfirm);
        if (backdrop) backdrop.addEventListener('click', closeCenterPassOrderConfirm);
        if (sendBtn) sendBtn.addEventListener('click', submitCenterPassOrderRequest);
      }

      function renderCenterSessionsCatalog() {
        var listRoot = document.getElementById('trainerList');
        if (!listRoot) return;
        var panel = document.getElementById('centerSessionsPanel');
        if (!panel) {
          panel = document.createElement('div');
          panel.id = 'centerSessionsPanel';
          panel.className = 'catalog-center-sessions';
          listRoot.parentNode.insertBefore(panel, listRoot);
        }
        var brand = state.collectiveBrand;
        var sessions = state.centerSessions;
        var showCenterPanel = !!(brand && isCenterCatalogBrand(brand) && sessions &&
          (state.catalogMode === 'center_schedule' || !brand.show_coaches_catalog_tab));
        if (!showCenterPanel) {
          panel.hidden = true;
          panel.innerHTML = '';
          if (listRoot) listRoot.style.display = '';
          return;
        }
        panel.hidden = false;
        if (listRoot) listRoot.style.display = 'none';
        var tariffs = sessions.tariffs || {};
        var lanePrice = tariffs.lane_hour_cents != null ? (tariffs.lane_hour_cents / 100).toFixed(0) : '20';
        var items = sessions.sessions || [];
        var passProducts = (sessions.pass_products || []).filter(function(p) { return p.is_active !== false; });
        var html = '';
        if (items.length) {
          html += '<div class="catalog-collective-sessions-block">' +
            '<div class="catalog-collective-sessions-title">Запись в центр</div>' +
            '<p class="catalog-collective-sessions-hint">Выберите окно и формат — дорожка от ' + lanePrice + ' BYN, гость +15 BYN</p>' +
            items.map(function(s) {
              var coaches = (s.assigned_coaches || []).map(function(c) { return escapeHtml(c.display_name); }).join(', ');
              var coachLine = coaches
                ? 'Тренеры на смене: ' + coaches
                : 'Можно прийти самостоятельно или со своим тренером';
              var seats = (s.seats_left != null ? s.seats_left : Math.max(0, (s.capacity || 1) - (s.booked_count || 0)));
              return '<div class="catalog-collective-session-card" data-session-id="' + s.id + '">' +
                '<div class="catalog-collective-session-card__head">' +
                '<div class="catalog-collective-session-card__when">' + escapeHtml(formatCenterSessionWhen(s)) + '</div>' +
                '<span class="catalog-collective-session-card__seats">' + escapeHtml(formatCenterSeatsLabel(seats)) + '</span>' +
                '</div>' +
                '<p class="catalog-collective-sessions-coaches">' + coachLine + '</p>' +
                '<button type="button" class="btn-primary catalog-collective-session-book" data-session-id="' + s.id + '">Выбрать формат</button>' +
                '</div>';
            }).join('') +
            '</div>';
        } else if (!passProducts.length) {
          html += '<div class="catalog-collective-sessions-empty">Свободных окон и абонементов пока нет — загляните позже.</div>';
        } else {
          html += '<div class="catalog-collective-sessions-empty catalog-collective-sessions-empty--compact">Свободных окон пока нет — ниже можно оформить абонемент.</div>';
        }
        html += buildCenterPassesCatalogHtml(passProducts);
        panel.innerHTML = html;
        panel.querySelectorAll('.catalog-collective-session-book').forEach(function(btn) {
          btn.addEventListener('click', function() {
            centerBookingHapticSelection();
            openCenterSessionBookingModal(parseInt(btn.getAttribute('data-session-id'), 10));
          });
        });
        bindCenterPassOrderButtons(panel);
      }

      function openCenterSessionBookingModal(sessionId) {
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) {
          if (tg && tg.showAlert) tg.showAlert('Откройте каталог через клиентский бот Telegram');
          return;
        }
        var session = findCenterSessionById(sessionId);
        if (!session) {
          if (tg && tg.showAlert) tg.showAlert('Окно не найдено — обновите страницу');
          return;
        }
        var modes = centerBookingModeOptions(session);
        var defaultMode = modes.length ? modes[0].id : 'lane_self';
        var coaches = session.assigned_coaches || [];
        state.centerBookingDraft = {
          sessionId: sessionId,
          session: session,
          mode: defaultMode,
          guestCount: 0,
          centerCoachId: coaches.length === 1 ? coaches[0].trainer_id : null,
          comment: '',
          passInstanceId: null,
        };
        loadClientCenterPasses().then(function() {
          var eligible = eligibleCenterPassesForMode(defaultMode);
          if (eligible.length === 1) {
            state.centerBookingDraft.passInstanceId = eligible[0].id;
          }
          renderCenterBookingModal();
        });
        renderCenterBookingModal();
        var modal = document.getElementById('centerSessionBookingModal');
        if (modal) {
          modal.hidden = false;
          document.body.classList.add('center-booking-sheet-open');
          requestAnimationFrame(function() {
            modal.classList.add('is-open');
          });
        }
        if (window.ClientShell && typeof window.ClientShell.setTabBarVisible === 'function') {
          window.ClientShell.setTabBarVisible(false);
        }
      }

      function closeCenterSessionBookingModal() {
        var modal = document.getElementById('centerSessionBookingModal');
        if (modal) {
          modal.classList.remove('is-open');
          document.body.classList.remove('center-booking-sheet-open');
          window.setTimeout(function() {
            if (!modal.classList.contains('is-open')) modal.hidden = true;
          }, 340);
        }
        state.centerBookingDraft = null;
        if (window.ClientShell && typeof window.ClientShell.setTabBarVisible === 'function') {
          window.ClientShell.setTabBarVisible(true);
        }
      }

      function getCenterBookingModeDef(modeId) {
        for (var i = 0; i < CENTER_ATTENDANCE_MODES.length; i++) {
          if (CENTER_ATTENDANCE_MODES[i].id === modeId) return CENTER_ATTENDANCE_MODES[i];
        }
        return null;
      }

      function renderCenterBookingModal() {
        var draft = state.centerBookingDraft;
        if (!draft || !draft.session) return;
        var session = draft.session;
        var tariffs = (state.centerSessions && state.centerSessions.tariffs) || {};
        var metaEl = document.getElementById('centerBookingModalMeta');
        if (metaEl) metaEl.textContent = formatCenterSessionWhen(session);
        var modes = centerBookingModeOptions(session);
        var modeListEl = document.getElementById('centerBookingModeList');
        if (modeListEl) {
          modeListEl.innerHTML = modes.map(function(m) {
            var guestPreview = 0;
            if (m.id === 'center_coach_pair') guestPreview = 1;
            else if (m.needsGuests) guestPreview = Math.max(m.minGuests || 1, draft.guestCount || 1);
            else if (m.optionalGuests) guestPreview = Math.max(0, draft.guestCount || 0);
            var price = computeCenterBookingPriceCents(m.id, guestPreview, tariffs);
            var active = draft.mode === m.id ? ' is-active' : '';
            return '<button type="button" class="center-booking-mode' + active + '" data-mode="' + m.id + '" role="radio" aria-checked="' + (active ? 'true' : 'false') + '">' +
              '<span class="center-booking-mode__emoji" aria-hidden="true">' + (m.emoji || '•') + '</span>' +
              '<span class="center-booking-mode__main">' +
              '<span class="center-booking-mode__title">' + escapeHtml(m.title) + '</span>' +
              '<span class="center-booking-mode__subtitle">' + escapeHtml(m.subtitle) + '</span>' +
              '</span>' +
              '<span class="center-booking-mode__price">' + escapeHtml(formatCenterPriceByn(price)) + '</span>' +
              '</button>';
          }).join('');
          modeListEl.querySelectorAll('.center-booking-mode').forEach(function(btn) {
            btn.addEventListener('click', function() {
              centerBookingHapticSelection();
              draft.mode = btn.getAttribute('data-mode') || 'lane_self';
              var def = getCenterBookingModeDef(draft.mode);
              if (def && def.needsGuests) draft.guestCount = Math.max(def.minGuests || 1, draft.guestCount || 1);
              if (def && def.optionalGuests && !def.needsGuests && draft.guestCount < 0) draft.guestCount = 0;
              if (def && def.coachMode) {
                var coaches = session.assigned_coaches || [];
                if (coaches.length === 1) draft.centerCoachId = coaches[0].trainer_id;
              }
              var eligible = eligibleCenterPassesForMode(draft.mode);
              if (draft.passInstanceId && !eligible.some(function(p) { return Number(p.id) === Number(draft.passInstanceId); })) {
                draft.passInstanceId = eligible.length === 1 ? eligible[0].id : null;
              } else if (!draft.passInstanceId && eligible.length === 1) {
                draft.passInstanceId = eligible[0].id;
              }
              renderCenterBookingModal();
            });
          });
        }

        var modeDef = getCenterBookingModeDef(draft.mode) || modes[0];
        var coachSection = document.getElementById('centerBookingCoachSection');
        var coachListEl = document.getElementById('centerBookingCoachList');
        var coaches = session.assigned_coaches || [];
        if (coachSection && coachListEl) {
          var showCoach = !!(modeDef && modeDef.needsCoach && coaches.length);
          coachSection.hidden = !showCoach;
          if (showCoach) {
            coachListEl.innerHTML = coaches.map(function(c) {
              var active = Number(draft.centerCoachId) === Number(c.trainer_id) ? ' is-active' : '';
              return '<button type="button" class="center-booking-coach' + active + '" data-coach-id="' + c.trainer_id + '">' +
                escapeHtml(c.display_name) + '</button>';
            }).join('');
            coachListEl.querySelectorAll('.center-booking-coach').forEach(function(btn) {
              btn.addEventListener('click', function() {
                centerBookingHapticSelection();
                draft.centerCoachId = parseInt(btn.getAttribute('data-coach-id'), 10);
                renderCenterBookingModal();
              });
            });
          }
        }

        var guestSection = document.getElementById('centerBookingGuestSection');
        var guestValueEl = document.getElementById('centerBookingGuestValue');
        var guestHintEl = document.getElementById('centerBookingGuestHint');
        var guestLabelEl = document.getElementById('centerBookingGuestLabel');
        var guestMinus = document.getElementById('centerBookingGuestMinus');
        var guestPlus = document.getElementById('centerBookingGuestPlus');
        var showGuests = !!(modeDef && (modeDef.needsGuests || modeDef.optionalGuests));
        if (guestSection) guestSection.hidden = !showGuests;
        if (showGuests) {
          if (guestLabelEl) {
            guestLabelEl.textContent = modeDef.optionalGuests ? 'Дополнительных гостей' : 'Гостей';
          }
          if (guestValueEl) guestValueEl.textContent = String(draft.guestCount);
          if (guestHintEl) {
            guestHintEl.textContent = modeDef.optionalGuests
              ? '+15 BYN за каждого гостя на дорожке'
              : '+15 BYN за каждого гостя сверх вас';
          }
          var minG = modeDef.needsGuests ? (modeDef.minGuests || 1) : 0;
          if (guestMinus) {
            guestMinus.disabled = draft.guestCount <= minG;
            guestMinus.onclick = function() {
              if (draft.guestCount > minG) {
                centerBookingHapticSelection();
                draft.guestCount -= 1;
                renderCenterBookingModal();
              }
            };
          }
          if (guestPlus) {
            guestPlus.disabled = draft.guestCount >= 10;
            guestPlus.onclick = function() {
              if (draft.guestCount < 10) {
                centerBookingHapticSelection();
                draft.guestCount += 1;
                renderCenterBookingModal();
              }
            };
          }
        }

        var commentEl = document.getElementById('centerBookingComment');
        if (commentEl && commentEl !== document.activeElement) {
          commentEl.value = draft.comment || '';
        }

        var passSection = document.getElementById('centerBookingPassSection');
        var passListEl = document.getElementById('centerBookingPassList');
        var eligiblePasses = eligibleCenterPassesForMode(draft.mode);
        if (passSection && passListEl) {
          passSection.hidden = !eligiblePasses.length;
          if (eligiblePasses.length) {
            var passButtons = [
              '<button type="button" class="center-booking-coach' + (!draft.passInstanceId ? ' is-active' : '') + '" data-pass-id="">Без абонемента · PAYG</button>',
            ].concat(eligiblePasses.map(function(p) {
              var active = Number(draft.passInstanceId) === Number(p.id) ? ' is-active' : '';
              var label = (p.product_name || 'Абонемент') + ' · ' + p.sessions_remaining + ' ост.';
              return '<button type="button" class="center-booking-coach' + active + '" data-pass-id="' + p.id + '">' + escapeHtml(label) + '</button>';
            }));
            passListEl.innerHTML = passButtons.join('');
            passListEl.querySelectorAll('[data-pass-id]').forEach(function(btn) {
              btn.addEventListener('click', function() {
                centerBookingHapticSelection();
                var raw = btn.getAttribute('data-pass-id');
                draft.passInstanceId = raw ? parseInt(raw, 10) : null;
                renderCenterBookingModal();
              });
            });
          }
        }

        var guestCountForPrice = 0;
        if (modeDef) {
          if (modeDef.id === 'center_coach_pair') guestCountForPrice = 1;
          else if (modeDef.needsGuests) guestCountForPrice = Math.max(modeDef.minGuests || 1, draft.guestCount);
          else if (modeDef.optionalGuests) guestCountForPrice = Math.max(0, draft.guestCount);
        }
        var totalCents = computeCenterBookingPriceWithPassCents(
          draft.mode,
          guestCountForPrice,
          tariffs,
          draft.passInstanceId ? centerPassKindForMode(draft.mode) : null
        );
        var priceEl = document.getElementById('centerBookingPriceLine');
        if (priceEl) {
          priceEl.textContent = draft.passInstanceId && totalCents === 0
            ? 'По абонементу'
            : formatCenterPriceByn(totalCents);
        }
        var breakdownEl = document.getElementById('centerBookingPriceBreakdown');
        if (breakdownEl) {
          if (draft.passInstanceId) {
            var credits = centerPassCreditsForMode(draft.mode);
            var extra = totalCents > 0 ? ' · доплата ' + formatCenterPriceByn(totalCents) : '';
            breakdownEl.textContent = 'Списание ' + credits + ' посещ. с абонемента' + extra;
          } else {
            breakdownEl.textContent = buildCenterPriceBreakdown(draft.mode, guestCountForPrice, tariffs);
          }
        }

        var submitBtn = document.getElementById('centerBookingSubmit');
        if (submitBtn) {
          var canSubmit = true;
          if (modeDef && modeDef.needsCoach && !draft.centerCoachId) canSubmit = false;
          if (modeDef && modeDef.needsGuests && draft.guestCount < (modeDef.minGuests || 1)) canSubmit = false;
          submitBtn.disabled = !canSubmit;
          if (!submitBtn.disabled && submitBtn.textContent === 'Отправляем…') {
            submitBtn.textContent = 'Отправить заявку';
          }
        }
      }

      function submitCenterSessionBooking() {
        var draft = state.centerBookingDraft;
        if (!draft) return;
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return;
        var modeDef = getCenterBookingModeDef(draft.mode);
        var guestCount = 0;
        if (modeDef) {
          if (modeDef.id === 'center_coach_pair') guestCount = 1;
          else if (modeDef.needsGuests) guestCount = Math.max(modeDef.minGuests || 1, draft.guestCount);
          else if (modeDef.optionalGuests) guestCount = Math.max(0, draft.guestCount);
        }
        var commentEl = document.getElementById('centerBookingComment');
        if (commentEl) draft.comment = (commentEl.value || '').trim();

        var submitBtn = document.getElementById('centerBookingSubmit');
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.textContent = 'Отправляем…';
        }

        var payload = {
          session_id: draft.sessionId,
          attendance_mode: draft.mode,
          guest_count: guestCount,
          client_comment: draft.comment || null,
        };
        if (modeDef && modeDef.needsCoach && draft.centerCoachId) {
          payload.center_coach_id = draft.centerCoachId;
        }
        if (draft.passInstanceId) {
          payload.collective_pass_instance_id = draft.passInstanceId;
        }

        fetch('/api/webapp/client/collective-session-booking', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData },
          body: JSON.stringify(payload),
        })
          .then(function(r) {
            return r.json().then(function(d) {
              if (!r.ok) throw new Error(centerBookingErrorMessage(d && d.detail));
              return d;
            });
          })
          .then(function() {
            closeCenterSessionBookingModal();
            if (window.ClientShell && typeof window.ClientShell.hapticSuccess === 'function') {
              window.ClientShell.hapticSuccess();
            }
            if (tg && tg.showAlert) tg.showAlert('Заявка отправлена — центр подтвердит запись');
            loadCenterSessionsCatalog();
          })
          .catch(function(e) {
            if (submitBtn) {
              submitBtn.disabled = false;
              submitBtn.textContent = 'Отправить заявку';
            }
            if (tg && tg.showAlert) tg.showAlert(e.message || 'Не удалось записаться');
          });
      }

      function initCenterBookingModal() {
        var modal = document.getElementById('centerSessionBookingModal');
        var backdrop = document.getElementById('centerBookingModalBackdrop');
        var closeBtn = document.getElementById('centerBookingModalClose');
        var submitBtn = document.getElementById('centerBookingSubmit');
        var commentEl = document.getElementById('centerBookingComment');
        if (closeBtn) closeBtn.addEventListener('click', closeCenterSessionBookingModal);
        if (backdrop) backdrop.addEventListener('click', closeCenterSessionBookingModal);
        if (modal) {
          modal.addEventListener('click', function(e) {
            if (e.target === modal) closeCenterSessionBookingModal();
          });
        }
        if (submitBtn) submitBtn.addEventListener('click', submitCenterSessionBooking);
        if (commentEl) {
          commentEl.addEventListener('input', function() {
            if (state.centerBookingDraft) state.centerBookingDraft.comment = commentEl.value;
          });
        }
      }

      initCenterBookingModal();
      initCenterPassOrderModal();

      function loadCenterSessionsCatalog() {
        if (!state.collectiveSlug || !state.collectiveBrand || !isCenterCatalogBrand(state.collectiveBrand)) {
          state.centerSessions = null;
          renderCenterSessionsCatalog();
          return Promise.resolve(null);
        }
        return fetch('/api/public/collectives/' + encodeURIComponent(state.collectiveSlug) + '/sessions', { cache: 'no-store' })
          .then(function(res) {
            return res.json().then(function(data) {
              if (!res.ok) throw new Error((data && data.detail) || 'sessions_failed');
              return data;
            });
          })
          .then(function(data) {
            state.centerSessions = data;
            renderCenterSessionsCatalog();
            return data;
          })
          .catch(function() {
            state.centerSessions = { sessions: [], tariffs: {}, pass_products: [] };
            renderCenterSessionsCatalog();
            return null;
          });
      }

      function bootstrapCollectiveFromQuery(qp) {
        var slug = (qp && qp.get('collective')) || '';
        slug = (slug || '').trim().toLowerCase();
        if (!slug) {
          state.collectiveSlug = null;
          state.collectiveBrand = null;
          applyCollectiveHero(null);
          return Promise.resolve(null);
        }
        state.collectiveSlug = slug;
        return fetch('/api/public/collectives/' + encodeURIComponent(slug), { cache: 'no-store' })
          .then(function(res) {
            return res.json().then(function(data) {
              if (!res.ok) throw new Error((data && data.detail) || 'collective_not_found');
              return data;
            });
          })
          .then(function(data) {
            state.collectiveBrand = data;
            state.catalogMode = resolveCatalogModeFromBrand(data);
            syncCollectiveCatalogModeTabs(data);
            applyCollectiveHero(data);
            return loadCenterSessionsCatalog().then(function() { return data; });
          })
          .catch(function() {
            state.collectiveSlug = null;
            state.collectiveBrand = null;
            applyCollectiveHero(null);
            return null;
          });
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
              : state.catalogMode === 'center_schedule'
                ? 'Окна записи в центр'
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
        var mode = state.catalogMode || 'trainers';
        var isGroups = mode === 'groups';
        var isCenterSchedule = mode === 'center_schedule';
        var titleEl = document.getElementById('screenTrainersTitle');
        if (titleEl) {
          if (isGroups) titleEl.textContent = 'Группы с набором';
          else if (isCenterSchedule) titleEl.textContent = 'Расписание центра';
          else if (mode === 'center_coaches') titleEl.textContent = 'Тренеры центра';
          else titleEl.textContent = 'Тренеры';
        }
        var ts = document.getElementById('timeSlotFiltersSection');
        if (ts) ts.style.display = (isGroups || isCenterSchedule) ? 'none' : '';
        document.querySelectorAll('#catalogListMode .catalog-mode-btn').forEach(function(btn) {
          var on = btn.getAttribute('data-mode') === mode;
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
        if (state.catalogMode === 'center_schedule') {
          renderCenterSessionsCatalog();
          return;
        }
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

      function catalogOfferCountCacheKey() {
        return [state.cityId || 0, state.serviceId || 0, arenaIdsCacheKey()].join(':');
      }

      /** Trainer count for summary/CTA: city-wide or arena-filtered (distinct trainers, not sum per arena). */
      function lookupCatalogOfferTrainerCountSync() {
        if (!state.cityId || !state.serviceId) return null;
        var key = catalogOfferCountCacheKey();
        if (state.catalogOfferCountKey === key && state.catalogOfferCount != null) {
          return state.catalogOfferCount;
        }
        if (state.arenaIds.length === 0) {
          return lookupServiceTrainerCount(state.serviceId, state.cityId);
        }
        var fpKey = makeFirstPageKey();
        if (
          prefetch.firstPageKey === fpKey &&
          prefetch.firstPageData &&
          prefetch.firstPageData.total != null
        ) {
          return prefetch.firstPageData.total | 0;
        }
        return null;
      }

      function invalidateCatalogOfferCount() {
        state.catalogOfferCount = null;
        state.catalogOfferCountKey = null;
      }

      function refreshCatalogOfferTrainerCount() {
        if (!state.cityId || !state.serviceId) {
          invalidateCatalogOfferCount();
          patchSummaryServiceOfferMeta();
          patchSummaryArenaOfferMeta();
          updateCatalogFindUi();
          return Promise.resolve(null);
        }
        var key = catalogOfferCountCacheKey();
        if (state.arenaIds.length === 0) {
          var cityWide = lookupServiceTrainerCount(state.serviceId, state.cityId);
          state.catalogOfferCount = cityWide;
          state.catalogOfferCountKey = key;
          patchSummaryServiceOfferMeta();
          patchSummaryArenaOfferMeta();
          updateCatalogFindUi();
          return Promise.resolve(cityWide);
        }
        var fpKey = makeFirstPageKey();
        if (prefetch.firstPageKey === fpKey && prefetch.firstPageData && prefetch.firstPageData.total != null) {
          state.catalogOfferCount = prefetch.firstPageData.total | 0;
          state.catalogOfferCountKey = key;
          patchSummaryServiceOfferMeta();
          patchSummaryArenaOfferMeta();
          updateCatalogFindUi();
          return Promise.resolve(state.catalogOfferCount);
        }
        if (state.catalogOfferCountKey === key && state.catalogOfferCount != null) {
          patchSummaryServiceOfferMeta();
          patchSummaryArenaOfferMeta();
          updateCatalogFindUi();
          return Promise.resolve(state.catalogOfferCount);
        }
        return getJson('/trainers', makeTrainerListParams(0))
          .then(function(data) {
            if (catalogOfferCountCacheKey() !== key) return null;
            var total = data.total != null ? data.total | 0 : (data.items || []).length;
            state.catalogOfferCount = total;
            state.catalogOfferCountKey = key;
            patchSummaryServiceOfferMeta();
            patchSummaryArenaOfferMeta();
            updateCatalogFindUi();
            return total;
          })
          .catch(function() {
            patchSummaryServiceOfferMeta();
            patchSummaryArenaOfferMeta();
            updateCatalogFindUi();
            return null;
          });
      }

      function formatCatalogOfferHint(offerCnt) {
        var hasArenaFilter = state.arenaIds.length > 0;
        if (offerCnt === 0) {
          return hasArenaFilter
            ? 'На выбранных площадках пока нет тренеров — можно оставить заявку'
            : 'В этом городе пока нет тренеров по этой услуге — можно оставить заявку';
        }
        if (offerCnt != null && offerCnt > 0) {
          return hasArenaFilter
            ? formatServiceOfferCount(offerCnt) + ' · на выбранных площадках'
            : formatServiceOfferCount(offerCnt) + ' · площадку можно уточнить выше';
        }
        if (hasArenaFilter) return 'Считаем тренеров на выбранных площадках…';
        return 'Площадку можно уточнить в параметрах выше';
      }

      function patchFilterTileOfferMeta(action, label) {
        var tile = document.querySelector('#summaryRows .catalog-filter-tile[data-action="' + action + '"]');
        if (!tile) return;
        var body = tile.querySelector('.catalog-filter-tile__body');
        if (!body) return;
        var metaEl = body.querySelector('.catalog-filter-tile__meta');
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

      function patchSummaryServiceOfferMeta() {
        if (!state.cityId || !state.serviceId) {
          patchFilterTileOfferMeta('service', '');
          return;
        }
        var cnt = lookupCatalogOfferTrainerCountSync();
        var label = cnt !== null ? formatServiceOfferCount(cnt) : '';
        patchFilterTileOfferMeta('service', label);
      }

      function patchSummaryArenaOfferMeta() {
        patchFilterTileOfferMeta('arena', '');
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
          if (state.arenaIds.length > 0 && state.cityId && state.serviceId) {
            var offerKey = catalogOfferCountCacheKey();
            state.catalogOfferCount = data.total != null ? data.total | 0 : items.length;
            state.catalogOfferCountKey = offerKey;
            patchSummaryServiceOfferMeta();
            patchSummaryArenaOfferMeta();
            updateCatalogFindUi();
          }
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

      function buildCatalogEducationSectionInner(eduRows, profileEduDetail, profileExtraForDetail) {
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
        return eduSectionInner;
      }

      function catalogBioNeedsExpand(desc) {
        if (!desc || desc === '—') return false;
        var lines = desc.split(/\r?\n/).filter(function(line) { return line.trim().length > 0; });
        if (lines.length > 3) return true;
        return desc.length > 220;
      }

      /** Trust block: bio preview + education teasers above slots; full details on expand. */
      function buildTrainerAboutSectionHtml(desc, eduRows, profileEduDetail, profileExtraForDetail) {
        var hasDesc = desc !== '—';
        var eduSectionInner = buildCatalogEducationSectionInner(eduRows, profileEduDetail, profileExtraForDetail);
        var eduPreview = [];
        eduRows.forEach(function(edu) {
          if (eduPreview.length >= 2) return;
          var line = formatCatalogEducationEntry(edu);
          if (line) eduPreview.push(line);
        });
        var eduHiddenCount = Math.max(0, eduRows.length - eduPreview.length);
        var profileEduChip = '';
        var profileEduLine = '';
        if (eduPreview.length === 0 && profileEduDetail) {
          if (isProfileEducationCategoryOnly(profileEduDetail)) {
            profileEduChip = profileEduDetail;
          } else {
            profileEduLine = profileEduDetail.split(/\r?\n/).map(function(s) { return s.trim(); }).filter(Boolean)[0] || '';
          }
        }
        var hasEduPreview = eduPreview.length > 0 || !!profileEduChip || !!profileEduLine;
        var needsEduDetails = false;
        if (eduSectionInner) {
          needsEduDetails =
            eduRows.length > 0 ||
            !!profileExtraForDetail ||
            (profileEduDetail && !isProfileEducationCategoryOnly(profileEduDetail) && eduRows.length === 0 && (profileEduDetail.length > 120 || profileEduDetail.indexOf('\n') >= 0));
        }
        if (!hasDesc && !hasEduPreview && !needsEduDetails) return '';

        var html = '<div class="trainer-detail-about">';
        html += '<div class="trainer-detail-about-kicker">О тренере</div>';

        if (hasDesc) {
          var bioHtml = escapeHtml(desc).replace(/\n/g, '<br>');
          if (catalogBioNeedsExpand(desc)) {
            html += '<div class="trainer-detail-about-bio-wrap">';
            html += '<p class="trainer-detail-about-bio trainer-detail-about-bio--clamp">' + bioHtml + '</p>';
            html += '<details class="trainer-detail-about-bio-more">';
            html += '<summary class="trainer-detail-about-bio-more-summary">Читать полностью</summary>';
            html += '<div class="trainer-detail-about-bio trainer-detail-about-bio--full">' + bioHtml + '</div>';
            html += '</details></div>';
          } else {
            html += '<p class="trainer-detail-about-bio">' + bioHtml + '</p>';
          }
        }

        if (hasEduPreview) {
          html += '<div class="trainer-detail-about-edu">';
          if (profileEduChip) {
            html += '<span class="trainer-detail-about-edu-chip">' + escapeHtml(profileEduChip) + '</span>';
          } else {
            eduPreview.forEach(function(line) {
              html += '<div class="trainer-detail-about-edu-line">' + escapeHtml(line) + '</div>';
            });
            if (profileEduLine && eduPreview.length === 0) {
              html += '<div class="trainer-detail-about-edu-line">' + escapeHtml(profileEduLine) + '</div>';
            }
            if (eduHiddenCount > 0) {
              html += '<div class="trainer-detail-about-edu-more">Ещё ' + eduHiddenCount + ' ' + (eduHiddenCount === 1 ? 'запись' : 'записи') + '</div>';
            }
          }
          html += '</div>';
        }

        if (needsEduDetails && eduSectionInner) {
          html +=
            '<details class="trainer-detail-about-edu-details">' +
            '<summary class="trainer-detail-about-edu-summary">Образование и документы</summary>' +
            '<div class="trainer-detail-about-edu-panel"><div class="trainer-detail-education">' +
            eduSectionInner +
            '</div></div></details>';
        }

        html += '</div>';
        return html;
      }

      function bindTrainerDetailEducationDocLinks(rootEl) {
        if (!rootEl) return;
        rootEl.querySelectorAll('.trainer-detail-education-doc').forEach(function(linkEl) {
          linkEl.addEventListener('click', function(ev) {
            if (tg && typeof tg.openLink === 'function') {
              ev.preventDefault();
              tg.openLink(linkEl.href);
            }
          });
        });
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
        paintTrainerDetailSkeleton();
        showScreen('screenTrainerDetail');
        loadTrainerById(t.id).then(function(full) {
          state.selectedTrainer = full || t;
          state.trainerName = trainerName(state.selectedTrainer);
          reconcileCatalogServiceWithTrainerAsync(state.selectedTrainer).then(function() {
            initTrainerSlotsArenaFilter(state.selectedTrainer, {});
            renderTrainerDetail();
            showScreen('screenTrainerDetail');
          });
        }).catch(function() {
          state.selectedTrainer = t;
          reconcileCatalogServiceWithTrainerAsync(t).then(function() {
            initTrainerSlotsArenaFilter(t, {});
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
        var initData = tg && tg.initData ? tg.initData : '';
        if (initData) {
          return loadTrainerByIdViaWebappFallback(trainerId).then(function(t) {
            if (t) return t;
            return fetch('/api/public/trainers/' + encodeURIComponent(trainerId), { cache: 'no-store' })
              .then(function(r) {
                if (r.status === 404) return null;
                if (!r.ok) throw new Error(r.statusText);
                return r.json();
              })
              .catch(function() {
                return null;
              });
          });
        }
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
          /* Invite ?trainer_id= pins tab; else card context; else hub primary from edges. */
          var eff = state.deepLinkTrainerId;
          if (eff == null || eff === '' || !(Number(eff) > 0)) {
            eff = state.trainerId;
          }
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
        document.getElementById('myTrainerLoading').style.display = 'none';
        document.getElementById('myTrainerCardShort').style.display = 'none';
        state.openedFromMyTrainerTab = true;
        paintTrainerDetailSkeleton();
        showScreen('screenTrainerDetail');
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
            initTrainerSlotsArenaFilter(t, {});
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
            if (isHubDirectBookEntry() && applyCatalogRepeatBookingDefaults(trainer)) {
              if (state.cityId && state.serviceId) persistCatalogFilters(trainer.id);
              resolve();
              return;
            }
            state.serviceName = String(allowed[cur].service_name || state.serviceName || '').trim();
            if (state.cityId && state.serviceId) persistCatalogFilters(trainer.id);
            resolve();
            return;
          }
          if (applyCatalogRepeatBookingDefaults(trainer)) {
            if (state.cityId && state.serviceId) persistTrainerSelection(trainer.id);
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
      function applyTrainerEdgesPayload(data) {
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
      }

      function loadTrainerEdges() {
        var initData = tg && tg.initData ? tg.initData : '';
        if (!initData) return Promise.resolve();
        var headers = { 'X-Telegram-Init-Data': initData };
        return fetch('/api/webapp/client/trainer-edges', { headers: headers })
          .then(function(r) { return r.ok ? r.json() : null; })
          .then(function(data) {
            applyTrainerEdgesPayload(data);
            return data;
          })
          .catch(function() { /* non-critical */ return null; });
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
       * Resolve trackable /r/tg/{id} redirect to an absolute URL for Telegram WebApp openLink.
       */
      function trainerContactTelegramUrl(trainer) {
        var raw = trainer && typeof trainer.contact_telegram_url === 'string'
          ? trainer.contact_telegram_url.trim()
          : '';
        if (!raw) return '';
        if (/^https?:\/\//i.test(raw)) return raw;
        var origin = window.location.origin || '';
        return origin + (raw.charAt(0) === '/' ? raw : '/' + raw);
      }

      function openTrainerTelegramContact(trainer) {
        var url = trainerContactTelegramUrl(trainer);
        if (url) {
          if (tg && typeof tg.openLink === 'function') {
            try {
              tg.openLink(url, { try_instant_view: false });
              return true;
            } catch (e1) {
              try {
                tg.openLink(url);
                return true;
              } catch (e2) { /* fall through */ }
            }
          }
          try {
            window.open(url, '_blank');
            return true;
          } catch (e3) { /* fall through */ }
        }
        if (typeof window.openTelegramChatFromMiniApp === 'function') {
          var p = (trainer && trainer.profile) || {};
          var un = String(
            (trainer && trainer.telegram_username) ||
              p.telegram_username ||
              (trainer && trainer.contact_telegram_username) ||
              ''
          )
            .replace(/^@/, '')
            .trim();
          return window.openTelegramChatFromMiniApp({
            username: un,
            telegramId: trainer && trainer.telegram_id != null ? trainer.telegram_id : null,
          });
        }
        return false;
      }

      /**
       * Adds «Написать тренеру» when contact_telegram_url is available from GET /trainers/{id}.
       * Uses data-action delegation on #trainerDetailActions — innerHTML += would drop .onclick handlers.
       * Returns true if the button was inserted.
       */
      function appendContactTrainerButton(container, trainer, opts) {
        opts = opts || {};
        if (!container || !trainer || !trainerContactTelegramUrl(trainer)) return false;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = (opts.primary ? 'btn-primary' : 'btn-secondary') + ' btn-block trainer-contact-btn';
        btn.setAttribute('data-action', 'contact-trainer');
        if (opts.id) btn.id = opts.id;
        btn.textContent = opts.label || 'Написать тренеру';
        if (opts.prepend && container.firstChild) {
          container.insertBefore(btn, container.firstChild);
        } else {
          container.appendChild(btn);
        }
        return true;
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
            loadCatalogScenariosFromApi(state.cityId);
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

      function prefillBookingPhoneField() {
        var el = document.getElementById('bookingPhone');
        if (!el) return;
        var raw = (state.clientPhone || '').trim();
        if (window.CrmPhoneField) {
          if (raw) CrmPhoneField.setE164(el, raw);
          else CrmPhoneField.setE164(el, '');
          return;
        }
        el.value = raw;
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

      function phoneCallHtml(phone, extraClass) {
        var p = String(phone || '').trim();
        if (!p) return '';
        var Pf = window.CrmPhoneField;
        if (Pf && typeof Pf.phoneTelLinkHtml === 'function') {
          return Pf.phoneTelLinkHtml(p, extraClass || 'bd-tel', escapeHtml);
        }
        return escapeHtml(p);
      }

      function wirePhoneCallLinks(root) {
        var Pf = window.CrmPhoneField;
        if (!Pf) return;
        if (typeof Pf.wirePhoneCallButtons === 'function') Pf.wirePhoneCallButtons(root || document);
        else if (typeof Pf.wirePhoneTelLinks === 'function') Pf.wirePhoneTelLinks(root || document);
      }

      function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }
      function escapeAttr(s) {
        if (s == null || s === undefined) return '';
        return String(s).replace(/"/g, '&quot;');
      }

      /** Show search whenever there is anything to filter (even 2 cities — user expects the field). */
      var CATALOG_PICKER_SEARCH_MIN = 1;

      var catalogCityItems = [];
      var catalogCitySearchBound = false;
      var catalogArenaSearchBound = false;

      function normalizePickerSearch(value) {
        return String(value || '')
          .toLowerCase()
          .replace(/ё/g, 'е')
          .replace(/\s+/g, ' ')
          .trim();
      }

      function pickerSearchTokens(query) {
        var q = normalizePickerSearch(query);
        return q ? q.split(' ') : [];
      }

      /** Every whitespace-separated token must appear in the combined haystack. */
      function pickerItemMatchesQuery(query, parts) {
        var tokens = pickerSearchTokens(query);
        if (!tokens.length) return true;
        var hay = normalizePickerSearch((parts || []).filter(Boolean).join(' '));
        if (!hay) return false;
        for (var i = 0; i < tokens.length; i++) {
          if (hay.indexOf(tokens[i]) < 0) return false;
        }
        return true;
      }

      function syncPickerSearchChrome(kind, totalCount, visibleCount, query) {
        var wrap = document.getElementById(kind + 'SearchWrap');
        var input = document.getElementById(kind + 'SearchInput');
        var clearBtn = document.getElementById(kind + 'SearchClear');
        var meta = document.getElementById(kind + 'SearchMeta');
        if (!wrap || !input) return;
        var showSearch = totalCount >= CATALOG_PICKER_SEARCH_MIN;
        if (showSearch) wrap.removeAttribute('hidden');
        else wrap.setAttribute('hidden', '');
        var hasQuery = !!normalizePickerSearch(query);
        if (clearBtn) {
          if (hasQuery) clearBtn.removeAttribute('hidden');
          else clearBtn.setAttribute('hidden', '');
        }
        if (meta) {
          if (!showSearch || !hasQuery) {
            meta.setAttribute('hidden', '');
            meta.textContent = '';
          } else if (visibleCount === 0) {
            meta.removeAttribute('hidden');
            meta.textContent = 'Ничего не найдено — попробуйте другое название или адрес';
          } else if (visibleCount < totalCount) {
            meta.removeAttribute('hidden');
            meta.textContent = 'Показано ' + visibleCount + ' из ' + totalCount;
          } else {
            meta.setAttribute('hidden', '');
            meta.textContent = '';
          }
        }
      }

      function resetPickerSearch(kind) {
        var input = document.getElementById(kind + 'SearchInput');
        if (!input || !input.value) return;
        input.value = '';
        if (kind === 'city') renderCityList();
        else if (kind === 'arena') renderArenaListCheckboxes();
      }

      function focusPickerSearch(kind) {
        var wrap = document.getElementById(kind + 'SearchWrap');
        var input = document.getElementById(kind + 'SearchInput');
        if (!wrap || wrap.hasAttribute('hidden') || !input) return;
        requestAnimationFrame(function() {
          try { input.focus({ preventScroll: true }); } catch (eFocus) { input.focus(); }
        });
      }

      function maybeFocusActivePickerSearch(kind) {
        var screenId = kind === 'city' ? 'screenCity' : 'screenArena';
        var screen = document.getElementById(screenId);
        var input = document.getElementById(kind + 'SearchInput');
        if (!screen || !screen.classList.contains('active') || !input || input.value) return;
        focusPickerSearch(kind);
      }

      function bindPickerSearchOnce(kind, onInput) {
        var boundFlag = kind === 'city' ? catalogCitySearchBound : catalogArenaSearchBound;
        if (boundFlag) return;
        if (kind === 'city') catalogCitySearchBound = true;
        else catalogArenaSearchBound = true;
        var input = document.getElementById(kind + 'SearchInput');
        var clearBtn = document.getElementById(kind + 'SearchClear');
        if (!input) return;
        input.addEventListener('input', onInput);
        if (clearBtn) {
          clearBtn.addEventListener('click', function() {
            input.value = '';
            onInput();
            input.focus();
          });
        }
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

      function loadCatalogScenariosFromApi(cityId) {
        var params = cityId ? { city_id: cityId } : {};
        return getJson('/catalog-scenarios', params)
          .then(function (data) {
            var items = (data && data.items) || [];
            if (!items.length) return;
            var map = {};
            items.forEach(function (it) {
              if (!it || !it.key) return;
              map[it.key] = {
                label: it.label || it.key,
                servicePatterns: it.service_patterns || [],
              };
            });
            if (Object.keys(map).length) CATALOG_SCENARIO_STUBS = map;
          })
          .catch(function () { /* ice defaults */ });
      }
      var _catalogServicesCacheByCity = {};
      var _catalogArenasCache = {};

      function catalogServicesCacheKey(cityId) {
        return cityId ? String(cityId) : '_all';
      }

      function catalogArenasCacheKey(cityId, serviceId) {
        return String(cityId || 0) + ':' + String(serviceId || 0);
      }

      function invalidateCatalogServicesCache() {
        _catalogServicesCacheByCity = {};
      }

      function invalidateCatalogArenasCache() {
        _catalogArenasCache = {};
      }

      /** Arenas for city; with service_id each row has trainer_count (one GET, cached). */
      function fetchCatalogArenas(cityId, serviceId) {
        var key = catalogArenasCacheKey(cityId, serviceId);
        if (_catalogArenasCache[key]) return Promise.resolve(_catalogArenasCache[key]);
        var params = { city_id: cityId };
        if (serviceId) params.service_id = serviceId;
        return getJson('/arenas', params).then(function(data) {
          _catalogArenasCache[key] = data.items || [];
          return _catalogArenasCache[key];
        });
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

      var CATALOG_CTA_LABEL = 'Найти тренера';

      var catalogSummaryHydrated = false;
      var catalogHydrateFingerprint = '';

      function catalogSessionFingerprint(sess) {
        if (!sess) return 'none';
        return [
          sess.city_id || '',
          sess.service_id || '',
          sess.arena_id || '',
          sess.trainer_id || '',
          sess.city_name || '',
          sess.service_name || '',
        ].join('|');
      }

      function catalogStateFingerprint() {
        return [
          state.cityId || '',
          state.serviceId || '',
          state.arenaId || '',
          state.trainerId || '',
          state.cityName || '',
          state.serviceName || '',
        ].join('|');
      }

      function applyWarmCatalogServices(warm) {
        if (!warm || !warm.servicesByCity) return;
        Object.keys(warm.servicesByCity).forEach(function(k) {
          _catalogServicesCacheByCity[k] = warm.servicesByCity[k];
        });
      }

      function renderCatalogFilterSkeleton() {
        var rows = document.getElementById('summaryRows');
        if (!rows) return;
        if (rows.querySelector('.catalog-filter-skel-list')) return;
        var html = '<div class="catalog-filter-skel-list" role="status" aria-busy="true" aria-label="Загрузка параметров">';
        for (var i = 0; i < 3; i++) {
          html +=
            '<div class="catalog-filter-skel catalog-skel-shimmer" aria-hidden="true">' +
            '<div class="catalog-filter-skel__icon"></div>' +
            '<div class="catalog-filter-skel__body">' +
            '<div class="catalog-skel-line catalog-skel-line--filter-label"></div>' +
            '<div class="catalog-skel-line catalog-skel-line--filter-value"></div>' +
            '</div>' +
            '<div class="catalog-filter-skel__chev"></div>' +
            '</div>';
        }
        html += '</div>';
        rows.innerHTML = html;
      }

      function activateSummaryScreen() {
        clearCatalogDeepLinkShellClasses();
        document.querySelectorAll('[data-screen]').forEach(function(el) { el.classList.remove('active'); });
        var el = document.getElementById('screenSummary');
        if (el) el.classList.add('active');
        syncClientShellTabBarForScreen('screenSummary');
        syncCatalogHeaderBack();
      }

      function finishCatalogBootReveal() {
        var home = document.getElementById('catalogHome');
        if (home) home.classList.remove('catalog-home--booting');
        document.body.classList.add('catalog-body--revealed');
        updateCatalogFindUi();
      }

      function hydrateCatalogSummary(opts) {
        opts = opts || {};
        var cityId = state.cityId || null;
        return fetchCatalogServices(cityId)
          .then(function() {
            syncScenarioChipSelection();
            renderSummary();
            if (!catalogSummaryHydrated) {
              catalogSummaryHydrated = true;
              finishCatalogBootReveal();
            }
            catalogHydrateFingerprint = catalogStateFingerprint();
            if (opts.activateScreen !== false) {
              activateSummaryScreen();
              switchTab(state.activeTab || 'catalog');
            }
            if (state.cityId && state.serviceId) prefetchFirstPageIfNeeded();
          })
          .catch(function() {
            renderSummary();
            if (!catalogSummaryHydrated) {
              catalogSummaryHydrated = true;
              finishCatalogBootReveal();
            }
            catalogHydrateFingerprint = catalogStateFingerprint();
            if (opts.activateScreen !== false) {
              activateSummaryScreen();
              switchTab(state.activeTab || 'catalog');
            }
          });
      }

      function updateCatalogHomeMode() {
        var titleEl = document.getElementById('catalogHeroTitle');
        var leadEl = document.getElementById('catalogHeroLead');
        if (!titleEl || !leadEl) return;
        var home = document.getElementById('catalogHome');
        if (home && home.classList.contains('catalog-home--booting')) return;
        if (state.cityId && state.serviceId) {
          titleEl.textContent = 'Готово к поиску';
          leadEl.textContent = 'Нажмите «Найти тренера» — покажем подходящих специалистов.';
        } else {
          titleEl.textContent = 'Найдите тренера';
          leadEl.textContent = 'Город и занятие — покажем свободные слоты на аренах.';
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
          var offerCnt = lookupCatalogOfferTrainerCountSync();
          hint = formatCatalogOfferHint(offerCnt);
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
              var cnt = lookupCatalogOfferTrainerCountSync();
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
            refreshCatalogOfferTrainerCount();
          });
        } else {
          refreshCatalogOfferTrainerCount();
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
        bindPickerSearchOnce('city', renderCityList);
        resetPickerSearch('city');
        setCatalogListLoading(document.getElementById('cityList'), 3);
        var searchWrap = document.getElementById('citySearchWrap');
        if (searchWrap) searchWrap.setAttribute('hidden', '');
        getJson('/cities').then(function(data) {
          catalogCityItems = data.items || [];
          if (!catalogCityItems.length) {
            document.getElementById('cityList').innerHTML = '<div class="empty">Нет городов</div>';
            syncPickerSearchChrome('city', 0, 0, '');
            syncCatalogHeaderBack();
            return;
          }
          renderCityList();
          syncCatalogHeaderBack();
        }).catch(function() {
          catalogCityItems = [];
          document.getElementById('cityList').innerHTML = '<div class="error">Ошибка загрузки</div>';
          syncPickerSearchChrome('city', 0, 0, '');
          syncCatalogHeaderBack();
        });
      }

      function renderCityList() {
        var listEl = document.getElementById('cityList');
        if (!listEl) return;
        var input = document.getElementById('citySearchInput');
        var query = input ? input.value : '';
        var items = catalogCityItems || [];
        var filtered = items.filter(function(c) {
          return pickerItemMatchesQuery(query, [c.name]);
        });
        syncPickerSearchChrome('city', items.length, filtered.length, query);
        if (!filtered.length) {
          listEl.innerHTML =
            '<div class="empty">' +
            (normalizePickerSearch(query)
              ? 'Город не найден<div class="catalog-picker-search__empty-hint">Проверьте написание или очистите поиск</div>'
              : 'Нет городов') +
            '</div>';
          return;
        }
        var html = filtered.map(function(c) {
          return (
            '<button type="button" class="choice-card" data-id="' + c.id + '" data-name="' + escapeAttr(c.name || '') + '">' +
            '<div class="main"><div class="label">' + CATALOG_FILTER_LABELS.city + '</div><div class="value">' + escapeHtml(c.name || '') + '</div></div>' +
            '<span class="arrow">→</span></button>'
          );
        }).join('');
        listEl.innerHTML = html;
        listEl.querySelectorAll('.choice-card').forEach(function(btn) {
          btn.onclick = function() {
            var newCityId = parseInt(btn.dataset.id, 10);
            var cityChanged = state.cityId != null && state.cityId !== newCityId;
            state.cityId = newCityId;
            state.cityName = btn.dataset.name || '';
            resetPickerSearch('city');
            loadCatalogScenariosFromApi(newCityId);
            invalidateCatalogServicesCache();
            invalidateCatalogArenasCache();
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
        maybeFocusActivePickerSearch('city');
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
        setCatalogListLoading(document.getElementById('serviceList'), 4);
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
              invalidateCatalogArenasCache();
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
      var leafletLoadPromise = null;

      /** Leaflet is only needed on the arena screen — load on demand instead of blocking every catalog open. */
      function ensureLeafletLoaded() {
        if (typeof window.L !== 'undefined') return Promise.resolve();
        if (leafletLoadPromise) return leafletLoadPromise;
        leafletLoadPromise = new Promise(function(resolve, reject) {
          if (!document.querySelector('link[data-leaflet-css]')) {
            var link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
            link.crossOrigin = 'anonymous';
            link.setAttribute('data-leaflet-css', '1');
            document.head.appendChild(link);
          }
          var s = document.createElement('script');
          s.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
          s.crossOrigin = 'anonymous';
          s.onload = function() { resolve(); };
          s.onerror = function() {
            leafletLoadPromise = null;
            reject(new Error('leaflet'));
          };
          document.head.appendChild(s);
        });
        return leafletLoadPromise;
      }

      function ensureArenaMapMounted() {
        var wrap = document.getElementById('arenaMapWrap');
        var node = document.getElementById('arenaMap');
        if (!wrap || !node) return;
        var items = (arenaScreenDraft.items || []).filter(function(a) { return a.latitude != null && a.longitude != null; });
        if (!items.length) {
          wrap.setAttribute('hidden', '');
          return;
        }
        ensureLeafletLoaded().then(function() {
          mountArenaMap(items, wrap, node);
        }).catch(function() {
          wrap.setAttribute('hidden', '');
        });
      }

      function mountArenaMap(items, wrap, node) {
        if (typeof window.L === 'undefined') {
          wrap.setAttribute('hidden', '');
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
        bindPickerSearchOnce('arena', renderArenaListCheckboxes);
        resetPickerSearch('arena');
        var listEl = document.getElementById('arenaList');
        setCatalogListLoading(listEl, 3);
        var mapWrap = document.getElementById('arenaMapWrap');
        if (mapWrap) mapWrap.setAttribute('hidden', '');
        var actions = document.getElementById('arenaListActions');
        if (actions) actions.setAttribute('hidden', '');
        var applyBar = document.getElementById('arenaApplyBar');
        if (applyBar) applyBar.setAttribute('hidden', '');
        var arenaSearchWrap = document.getElementById('arenaSearchWrap');
        if (arenaSearchWrap) arenaSearchWrap.setAttribute('hidden', '');
        fetchCatalogArenas(state.cityId, state.serviceId).then(function(items) {
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

      function arenaListPrefersReducedMotion() {
        return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
      }

      /**
       * Keep selected arenas at the top of the list (most recently selected first).
       * Unselected keep their relative catalog order. Makes map taps findable without hunting.
       */
      function sortArenasSelectedFirst(filtered, selectedSet) {
        var selected = [];
        var rest = [];
        filtered.forEach(function(a) {
          if (selectedSet[a.id]) selected.push(a);
          else rest.push(a);
        });
        selected.sort(function(a, b) {
          return arenaScreenDraft.ids.indexOf(a.id) - arenaScreenDraft.ids.indexOf(b.id);
        });
        return selected.concat(rest);
      }

      /** FLIP: invert old→new positions so the reorder reads as a slide, not a hard jump. */
      function animateArenaListReorder(listEl, firstRects) {
        if (!firstRects || !Object.keys(firstRects).length) return;
        if (arenaListPrefersReducedMotion()) return;
        listEl.querySelectorAll('.arena-card[data-id]').forEach(function(el) {
          var first = firstRects[String(el.dataset.id)];
          if (!first) return;
          var last = el.getBoundingClientRect();
          var dy = first.top - last.top;
          if (Math.abs(dy) < 1) return;
          el.style.transition = 'none';
          el.style.transform = 'translateY(' + dy + 'px)';
          // Force layout before playing the transition forward.
          void el.offsetWidth;
          el.style.transition = 'transform 0.34s cubic-bezier(0.22, 1, 0.36, 1)';
          el.style.transform = '';
          var clear = function(ev) {
            if (ev && ev.propertyName && ev.propertyName !== 'transform') return;
            el.style.transition = '';
            el.style.transform = '';
            el.removeEventListener('transitionend', clear);
          };
          el.addEventListener('transitionend', clear);
          setTimeout(clear, 450);
        });
      }

      /** Pulse highlight only — never scrollIntoView (map taps must keep the viewport on the map). */
      function pulseArenaCardAfterPromote(card) {
        if (!card) return;
        card.classList.add('arena-card--just-selected');
        setTimeout(function() { card.classList.remove('arena-card--just-selected'); }, 700);
      }

      function renderArenaListCheckboxes(opts) {
        opts = opts || {};
        var promoteId = opts.promoteId != null ? opts.promoteId : null;
        var listEl = document.getElementById('arenaList');
        var items = arenaScreenDraft.items || [];
        var input = document.getElementById('arenaSearchInput');
        var query = input ? input.value : '';
        if (!items.length) {
          listEl.innerHTML = '<div class="empty">В этом городе арены пока не добавлены</div>';
          syncPickerSearchChrome('arena', 0, 0, query);
          return;
        }
        var filtered = items.filter(function(a) {
          return pickerItemMatchesQuery(query, [a.name, a.address]);
        });
        syncPickerSearchChrome('arena', items.length, filtered.length, query);
        if (!filtered.length) {
          listEl.innerHTML =
            '<div class="empty">' +
            'Площадка не найдена<div class="catalog-picker-search__empty-hint">Попробуйте часть названия или адреса</div>' +
            '</div>';
          return;
        }
        var selectedSet = {};
        arenaScreenDraft.ids.forEach(function(id) { selectedSet[id] = true; });

        // Lock scroll across the DOM rebuild — otherwise Telegram/WebKit can jump the page
        // when cards reorder under a tall map.
        var lockedScrollY = promoteId != null
          ? (window.scrollY || window.pageYOffset || document.documentElement.scrollTop || 0)
          : null;

        var firstRects = null;
        if (promoteId != null) {
          firstRects = {};
          listEl.querySelectorAll('.arena-card[data-id]').forEach(function(el) {
            firstRects[String(el.dataset.id)] = el.getBoundingClientRect();
          });
        }

        filtered = sortArenasSelectedFirst(filtered, selectedSet);

        var html = filtered.map(function(a) {
          var isSel = !!selectedSet[a.id];
          var name = (a.name || '').replace(/"/g, '&quot;');
          var addr = a.address ? ('<div class="arena-card__addr">' + escapeHtml(a.address) + '</div>') : '';
          var count = a.trainer_count != null ? a.trainer_count | 0 : null;
          var showCount = state.cityId && state.serviceId && count !== null;
          var offerLine = showCount
            ? '<div class="arena-card__meta">' + escapeHtml(formatServiceOfferCount(count)) + '</div>'
            : '';
          var noOffers = showCount && count === 0;
          return (
            '<label class="arena-card' + (isSel ? ' selected' : '') + (noOffers ? ' arena-card--no-offers' : '') + '" data-id="' + a.id + '" data-name="' + name + '">' +
              '<span class="arena-card__check" aria-hidden="true">' +
                (isSel
                  ? '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="3.5 8.5 6.8 11.8 12.5 5.2"/></svg>'
                  : '') +
              '</span>' +
              '<span class="arena-card__main">' +
                '<span class="arena-card__name">' + (a.name || '') + '</span>' +
                addr +
                offerLine +
              '</span>' +
            '</label>'
          );
        }).join('');
        listEl.innerHTML = '<div class="arena-card-list">' + html + '</div>';
        if (lockedScrollY != null) {
          window.scrollTo(0, lockedScrollY);
        }
        listEl.querySelectorAll('.arena-card').forEach(function(card) {
          card.addEventListener('click', function(ev) {
            ev.preventDefault();
            var id = parseInt(card.dataset.id, 10);
            if (!id) return;
            var name = card.dataset.name || 'Арена';
            toggleArenaInDraft(id, name);
          });
        });
        if (promoteId != null) {
          animateArenaListReorder(listEl, firstRects);
          pulseArenaCardAfterPromote(
            listEl.querySelector('.arena-card[data-id="' + promoteId + '"]')
          );
          // Restore again after FLIP layout — some WebViews nudge scroll during transform setup.
          if (lockedScrollY != null) {
            window.scrollTo(0, lockedScrollY);
            requestAnimationFrame(function() { window.scrollTo(0, lockedScrollY); });
          }
          // Do not re-focus search on promote — focus can scroll the page away from the map.
        } else {
          maybeFocusActivePickerSearch('arena');
        }
      }

      function toggleArenaInDraft(id, name) {
        var idx = arenaScreenDraft.ids.indexOf(id);
        var selecting = idx < 0;
        if (!selecting) {
          arenaScreenDraft.ids.splice(idx, 1);
          arenaScreenDraft.names.splice(idx, 1);
        } else {
          // Most recent selection leads the list — map tap → card appears at the top.
          arenaScreenDraft.ids.unshift(id);
          arenaScreenDraft.names.unshift(name);
        }
        renderArenaListCheckboxes(selecting ? { promoteId: id } : {});
        updateArenaScreenChrome();
        if (typeof window.__arenaMapSyncSelection === 'function') {
          window.__arenaMapSyncSelection(arenaScreenDraft.ids);
        }
      }

      function arenaDraftItemById(id) {
        var items = arenaScreenDraft.items || [];
        for (var i = 0; i < items.length; i++) {
          if (items[i].id === id) return items[i];
        }
        return null;
      }

      function selectedArenaDraftAllZeroTrainers() {
        if (!state.serviceId || arenaScreenDraft.ids.length === 0) return false;
        return arenaScreenDraft.ids.every(function(id) {
          var a = arenaDraftItemById(id);
          return a && a.trainer_count != null && (a.trainer_count | 0) === 0;
        });
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
        if (applyBtn) {
          if (n === 0) applyBtn.textContent = 'Готово · любая арена';
          else if (selectedArenaDraftAllZeroTrainers()) {
            applyBtn.textContent = 'Готово · на выбранных аренах нет тренеров';
          } else applyBtn.textContent = 'Готово · ' + n;
        }
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
        wirePhoneCallLinks(block);
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
            if (state.collectiveSlug && isStudioRosterBrand(state.collectiveBrand) && !hasSlotFilters) {
              revealCatalogListContent(buildStudioRosterEmptyHtml(state.collectiveBrand));
              document.getElementById('pagination').innerHTML = '';
              document.getElementById('trainerListFooter').innerHTML = '';
              document.getElementById('trainerListFooter').style.display = 'none';
              return;
            }
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

      /** When opening a trainer card: optional explicit arena from URL; else pick after slots load. */
      function parseExplicitTrainerArenaIdsFromQuery(qp) {
        if (!qp) return null;
        var rawIds = qp.get('arena_ids');
        if (rawIds != null && rawIds !== '') {
          var ids = rawIds.split(',').map(function(s) { return parseInt(s, 10); }).filter(function(n) { return !isNaN(n) && n > 0; });
          if (ids.length) return ids;
        }
        var rawOne = qp.get('arena_id');
        if (rawOne != null && rawOne !== '') {
          var one = parseInt(rawOne, 10);
          if (!isNaN(one) && one > 0) return [one];
        }
        return null;
      }

      function trainerSlotsArenaIdsEqual(a, b) {
        var left = (a || []).slice().sort(function(x, y) { return x - y; });
        var right = (b || []).slice().sort(function(x, y) { return x - y; });
        if (left.length !== right.length) return false;
        for (var i = 0; i < left.length; i++) {
          if (left[i] !== right[i]) return false;
        }
        return true;
      }

      /**
       * Default card filter: one venue with slots → that venue; several → primary if it has slots; else all.
       */
      function pickDefaultTrainerSlotsArenaIds(trainer, slots) {
        if (!trainer || !slots || !slots.length) return [];
        var withSlots = {};
        slots.forEach(function(s) {
          var aid = s.arena_id != null ? Number(s.arena_id) : NaN;
          if (!isNaN(aid) && aid > 0) withSlots[aid] = true;
        });
        var ids = Object.keys(withSlots).map(Number).filter(function(n) { return !isNaN(n); });
        if (ids.length === 0) return [];
        if (ids.length === 1) return [ids[0]];
        var primary = trainer.primary_arena_id != null ? Number(trainer.primary_arena_id) : NaN;
        if (!isNaN(primary) && primary > 0 && withSlots[primary]) return [primary];
        return [];
      }

      function initTrainerSlotsArenaFilter(trainer, opts) {
        opts = opts || {};
        var tarenas = (trainer && trainer.arena_ids ? trainer.arena_ids : []).map(Number).filter(function(n) { return !isNaN(n); });
        if (!tarenas.length) {
          state.trainerSlotsArenaIds = [];
          state.trainerSlotsArenaFilterExplicit = !!opts.explicit;
          return;
        }
        var explicit = Array.isArray(opts.explicitArenaIds) ? opts.explicitArenaIds : null;
        if (explicit && explicit.length) {
          var picked = explicit.filter(function(id) { return tarenas.indexOf(Number(id)) >= 0; }).map(Number);
          state.trainerSlotsArenaIds = picked.length ? picked : [];
          state.trainerSlotsArenaFilterExplicit = true;
          return;
        }
        state.trainerSlotsArenaIds = [];
        state.trainerSlotsArenaFilterExplicit = !!opts.explicit;
      }

      /** @deprecated alias — use initTrainerSlotsArenaFilter */
      function initTrainerSlotsArenaFilterFromCatalog(t) {
        initTrainerSlotsArenaFilter(t, {});
      }

      /**
       * Load slots for trainer card; auto-pick arena filter from availability unless explicit/user-set.
       */
      function loadTrainerDetailSlots(trainer) {
        return loadSlotsForTrainer(trainer.id, trainer).then(function(data) {
          var slots = (data && data.slots) || [];
          if (!state.trainerSlotsArenaFilterExplicit) {
            var picked = pickDefaultTrainerSlotsArenaIds(trainer, slots);
            if (picked.length && !trainerSlotsArenaIdsEqual(picked, state.trainerSlotsArenaIds)) {
              state.trainerSlotsArenaIds = picked;
              return loadSlotsForTrainer(trainer.id, trainer).then(function(data2) {
                return (data2 && data2.slots) || [];
              });
            }
          }
          return slots;
        });
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
            state.trainerSlotsArenaFilterExplicit = true;
            var raw = btn.getAttribute('data-catalog-arena-filter');
            if (raw === 'all') {
              state.trainerSlotsArenaIds = [];
            } else {
              var id = parseInt(raw, 10);
              if (isNaN(id)) return;
              // Single-select chips: tap one venue → only that venue (not multi-toggle → «all»).
              state.trainerSlotsArenaIds = [id];
            }
            refetchTrainerSlotsForCard();
          };
        });
      }

      function refetchTrainerSlotsForCard() {
        var tt = state.selectedTrainer;
        if (!tt || tt.can_book !== true) return;
        paintTrainerArenaSlotFilterBar(tt);
        document.getElementById('trainerDetailSlots').innerHTML = buildTrainerDetailSlotsSkeletonHtml();
        document.getElementById('trainerDetailActions').innerHTML = '';
        loadSlotsForTrainer(tt.id, tt)
          .then(function(d) {
            paintTrainerSlotsAndActionsSection(tt, d);
          })
          .catch(function() {
            document.getElementById('trainerDetailSlots').innerHTML =
              '<div class="slots-title">Ближайшие слоты</div><div class="slots-empty">Не удалось загрузить слоты</div>';
            var errActions = document.getElementById('trainerDetailActions');
            errActions.innerHTML = '';
            appendContactTrainerButton(errActions, tt, { primary: true, label: 'Написать тренеру' });
            errActions.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
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
            openCatalogBookingFormForSlot(state.slotsForTrainer[ii]);
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
        appendContactTrainerButton(actionsEl, t, { primary: slots.length === 0, label: 'Написать тренеру' });
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
        var stickyBtn = document.getElementById('btnStickyBookTrainer');
        if (stickyBtn) {
          stickyBtn.onclick = function () {
            renderSlotPickList();
            showScreen('screenSlotPick');
          };
        }
        syncCatalogTrainerStickyCta(slots.length > 0 && t.can_book === true);
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
        
        var statsParts = [];
        if (p.experience_years != null) {
          statsParts.push(
            '<div class="trainer-detail-stat">' +
              '<div class="trainer-detail-stat-label">Опыт</div>' +
              '<div class="trainer-detail-stat-value">' +
                p.experience_years +
                ' ' +
                ruYearsWord(p.experience_years) +
              '</div>' +
            '</div>'
          );
        }
        statsParts.push(
          '<div class="' + arenaStatClass + '">' +
            '<div class="trainer-detail-stat-label">Арены</div>' +
            arenaInnerHtml +
          '</div>'
        );
        if (statsParts.length) {
          html += '<div class="trainer-detail-stats">' + statsParts.join('') + '</div>';
        }
        
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
        var htmlAbout = buildTrainerAboutSectionHtml(desc, eduRows, profileEduDetail, profileExtraForDetail);

        document.getElementById('trainerDetailTop').innerHTML = htmlTop;
        var aboutEl = document.getElementById('trainerDetailAbout');
        if (aboutEl) {
          aboutEl.innerHTML = htmlAbout;
          aboutEl.style.display = htmlAbout ? '' : 'none';
          bindTrainerDetailEducationDocLinks(aboutEl);
        }
        document.getElementById('trainerDetailRest').innerHTML = '';
        document.getElementById('trainerDetailGroups').innerHTML = '';
        bindTrainerDetailPhotoWrap();
        loadTrainingGroupsBlock(t);
        document.getElementById('trainerDetailSlots').innerHTML = buildTrainerDetailSlotsSkeletonHtml();
        document.getElementById('trainerDetailActions').innerHTML = '';
        var canBook = t.can_book === true;
        if (!canBook) {
          clearTrainerArenaSlotFilterBar();
          var phoneLine = '';
          var ph = (p.phone || '').trim();
          var ct = (p.contacts || '').trim();
          if (ph) phoneLine += '<div class="slots-empty slots-contact"><strong>Телефон:</strong> ' + phoneCallHtml(ph) + '</div>';
          if (ct) phoneLine += '<div class="slots-empty slots-contact"><strong>Контакты:</strong> ' + escapeHtml(ct) + '</div>';
          // Lead Mode: trainer kept in catalog after subscription expiry. Promote a strong
          // "Write in Telegram" CTA over the generic "leave request" path so we capture the
          // contact_click signal and route the visitor straight to the trainer's DM.
          var isLeadMode = t.is_lead_mode === true;
          var hasContact = !!trainerContactTelegramUrl(t);
          document.getElementById('trainerDetailSlots').innerHTML =
            '<div class="slots-title">Онлайн-запись</div>' +
            '<div class="slots-empty">' +
            (isLeadMode
              ? 'Онлайн-запись временно недоступна. Напишите тренеру в Telegram — ответит лично.'
              : 'У этого тренера нет самозаписи через каталог. Напишите тренеру — он подберёт время.') +
            '</div>' +
            phoneLine;
          state.slotsForTrainer = [];
          var actionsLeadEl = document.getElementById('trainerDetailActions');
          actionsLeadEl.innerHTML = '';
          if (hasContact) {
            appendContactTrainerButton(actionsLeadEl, t, {
              primary: true,
              id: 'btnContactTelegram',
              label: 'Написать тренеру',
            });
          }
          actionsLeadEl.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
          appendTrainerActionChips(actionsLeadEl, t, true);
          document.getElementById('trainerDetailSecondary').innerHTML = '';
          wirePhoneCallLinks(document.getElementById('trainerDetailSlots'));
          return;
        }
        loadTrainerDetailSlots(t)
          .then(function(slots) {
            paintTrainerArenaSlotFilterBar(t);
            paintTrainerSlotsAndActionsSection(t, { slots: slots });
            if (maybeOpenPendingDeepLinkSlotBooking(t, slots)) return;
          })
          .catch(function() {
            document.getElementById('trainerDetailSlots').innerHTML =
              '<div class="slots-title">Ближайшие слоты</div><div class="slots-empty">Не удалось загрузить слоты</div>';
            var errActions = document.getElementById('trainerDetailActions');
            errActions.innerHTML = '';
            appendContactTrainerButton(errActions, t, { primary: true, label: 'Написать тренеру' });
            errActions.innerHTML += '<button type="button" class="btn-secondary btn-block" data-action="leave-request">Оставить заявку</button>';
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
            openCatalogBookingFormForSlot(state.slotsForTrainer[i]);
          };
        });
      }

      (function wireCatalogBookingPhoneMask() {
        if (window.CrmPhoneField) CrmPhoneField.initAll(document.getElementById('screenBookingForm') || document);
      })();

      (function wireBookingFormServiceSelect() {
        var sel = document.getElementById('bookingFormServiceSelect');
        if (!sel) return;
        sel.addEventListener('change', function() {
          var sid = parseInt(sel.value, 10);
          if (!isNaN(sid) && sid > 0) selectCatalogBookingService(sid);
        });
      })();

      document.getElementById('btnSubmitBooking').onclick = function() {
        var slot = state.selectedSlot;
        if (!slot || !state.selectedTrainer) return;
        var phoneEl = document.getElementById('bookingPhone');
        var phCheck = window.CrmPhoneField ? CrmPhoneField.validate(phoneEl) : { ok: false, error: 'Укажите номер телефона.' };
        if (!phCheck.ok) {
          alert(phCheck.error || 'Укажите номер телефона.');
          return;
        }
        var phone = phCheck.e164;
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
        if (!state.catalogBookingIdempotencyKey) assignCatalogBookingIdempotencyKeyForSlot();
        var payloadBody = window.BookingClient
          ? window.BookingClient.buildBookingPayload({
              slotId: slot.id,
              phone: phone,
              comment: (document.getElementById('bookingComment').value || '').trim() || null,
              serviceId: effBookingSid,
              priceVariantId: state.catalogBookingPriceVariantId,
              needsProfileName: state.needsProfileName,
              firstName: state.needsProfileName
                ? (document.getElementById('bookingFirstName').value || '').trim()
                : null,
              lastName: state.needsProfileName
                ? (document.getElementById('bookingLastName').value || '').trim()
                : null,
            })
          : {
              slot_id: slot.id,
              phone: phone,
              comment: (document.getElementById('bookingComment').value || '').trim() || null,
            };
        if (!window.BookingClient) {
          if (state.needsProfileName) {
            payloadBody.first_name = (document.getElementById('bookingFirstName').value || '').trim();
            var ln = (document.getElementById('bookingLastName').value || '').trim();
            if (ln) payloadBody.last_name = ln;
          }
          if (effBookingSid != null) payloadBody.service_id = effBookingSid;
          if (state.catalogBookingPriceVariantId != null) {
            payloadBody.service_price_variant_id = state.catalogBookingPriceVariantId;
          }
        }
        var submitFn = window.BookingClient
          ? window.BookingClient.submitBooking({
              body: payloadBody,
              initData: initData,
              idempotencyKey: state.catalogBookingIdempotencyKey,
            })
          : fetch('/api/webapp/client/booking', {
              method: 'POST',
              headers: (function () {
                var h = { 'Content-Type': 'application/json' };
                if (initData) h['X-Telegram-Init-Data'] = initData;
                h['Idempotency-Key'] = state.catalogBookingIdempotencyKey;
                return h;
              })(),
              body: JSON.stringify(payloadBody),
            }).then(function (r) {
              return r.text().then(function (text) {
                return { res: r, data: catalogParseBookingJsonResponse(text) };
              });
            });
        submitFn.then(function (out) {
          var r = out.res;
          var data = out.data;
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
              syncCatalogTrainerStickyCta(false);
              var okMsg = window.BookingClient
                ? window.BookingClient.formatSuccessMessage(data, {})
                : '✅ <b>Вы записаны</b>.<br><br>Ожидайте подтверждения от тренера в боте.';
              prefetch.firstPageKey = null;
              prefetch.firstPageData = null;
              clearCatalogSessionStorageCache();
              persistCatalogFilters(state.selectedTrainer && state.selectedTrainer.id);
              if (window.BookingClient) {
                window.BookingClient.showBookingSuccess({
                  host: 'catalog',
                  messageHtml: okMsg,
                  showScreen: showScreen,
                });
              } else {
                document.getElementById('successText').innerHTML = okMsg;
                showScreen('screenSuccess');
              }
              getClientSession().then(function(session) {
                applySessionToState(session);
                renderSummary();
                updateBookingNameFieldsVisibility();
              }).catch(function() {});
            } else {
              alert((data && data.detail) || 'Не удалось записаться');
            }
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
      var btnSuccessBookingsCatalog = document.getElementById('btnSuccessBookingsCatalog');
      if (btnSuccessBookingsCatalog) {
        btnSuccessBookingsCatalog.onclick = function () {
          if (window.ClientShell && typeof window.ClientShell.navigate === 'function') {
            window.ClientShell.navigate('client-bookings');
          } else {
            closeCatalogSuccessToHubOrApp();
          }
        };
      }

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
        if (action && action.dataset.action === 'contact-trainer') {
          e.preventDefault();
          e.stopPropagation();
          var t = state.selectedTrainer;
          if (t) openTrainerTelegramContact(t);
          return;
        }
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
              var isPersonal = !!(state.requestForTrainer && state.requestForTrainer.id);
              var trainerName = isPersonal && state.requestForTrainer.name ? state.requestForTrainer.name : '';
              document.getElementById('successText').innerHTML = isPersonal
                ? ('✅ <b>Заявка отправлена</b> ' + (trainerName ? trainerName : 'тренеру') + '.<br><br>Когда тренер ответит — напишем вам в боте.')
                : '✅ <b>Заявка отправлена</b>.<br><br>Когда появится подходящий тренер — напишем вам в боте.';
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

      /** Paint catalog shell immediately — do not wait for session/edges network round-trip. */
      (function bootstrapCatalogUiFast() {
        var shell = window.ClientShell;
        var warm = shell && shell.readCatalogWarmCache ? shell.readCatalogWarmCache() : null;
        var qp = new URLSearchParams(window.location.search || '');
        state.activeTab = qp.get('tab') === 'my_trainer' ? 'my_trainer' : 'catalog';
        var slotBookingDeepLink = isCatalogSlotBookingDeepLink(qp);
        var bookActionDeepLink = isCatalogBookActionDeepLink(qp);
        var trainerDetailDeepLink = isCatalogTrainerDetailDeepLink(qp);

        var home = document.getElementById('catalogHome');
        if (home && !slotBookingDeepLink && !trainerDetailDeepLink && !bookActionDeepLink) home.classList.add('catalog-home--booting');

        if (slotBookingDeepLink) {
          activateCatalogBookingDeepLinkShell();
        } else if (bookActionDeepLink) {
          activateCatalogSlotPickDeepLinkShell();
        } else if (trainerDetailDeepLink) {
          activateCatalogTrainerDeepLinkShell();
        } else {
          activateSummaryScreen();
          renderCatalogFilterSkeleton();
          switchTab(state.activeTab);
        }

        if (warm && !slotBookingDeepLink && !trainerDetailDeepLink && !bookActionDeepLink) {
          applyWarmCatalogServices(warm);
          if (warm.session) {
            applySessionToState(warm.session);
            catalogHydrateFingerprint = catalogSessionFingerprint(warm.session);
          }
          if (warm.trainerEdges) applyTrainerEdgesPayload(warm.trainerEdges);
          if (warm.session) {
            hydrateCatalogSummary({ activateScreen: false });
          }
        }
      })();

      Promise.all([loadTrainerEdges(), getClientSession()])
        .then(function(results) {
          var edgesPayload = results[0];
          var session = results[1];
          if (window.ClientShell && window.ClientShell.writeCatalogWarmCache) {
            window.ClientShell.writeCatalogWarmCache({
              session: session,
              trainerEdges: edgesPayload,
              servicesByCity: (function() {
                if (!state.cityId) return null;
                var key = catalogServicesCacheKey(state.cityId);
                var items = _catalogServicesCacheByCity[key];
                if (!items) return null;
                var bag = {};
                bag[key] = items;
                return bag;
              })(),
            });
          }
          var qp = new URLSearchParams(window.location.search || '');
          var explicitTrainerArenaIdsFromUrl = parseExplicitTrainerArenaIdsFromQuery(qp);
          bootstrapCollectiveFromQuery(qp).finally(function() {
          applySessionToState(session);
          if (state.collectiveBrand && state.collectiveBrand.default_city_id && !qp.get('city_id')) {
            state.cityId = Number(state.collectiveBrand.default_city_id);
            state.cityName = state.collectiveBrand.default_city_name || '';
            loadCatalogScenariosFromApi(state.cityId);
          }
          var freshSessionFingerprint = catalogSessionFingerprint(session);
          var rawDeepTid = qp.get('trainer_id');
          var deepTidParsed = rawDeepTid != null && rawDeepTid !== '' ? parseInt(rawDeepTid, 10) : NaN;
          var deepTrainerFromUrl = !isNaN(deepTidParsed) && deepTidParsed > 0 ? deepTidParsed : null;
          var primaryTid = resolveCatalogAutoTrainerIdFromEdges();
          if (deepTrainerFromUrl != null) {
            state.deepLinkTrainerId = deepTrainerFromUrl;
            state.trainerId = deepTrainerFromUrl;
            state.activeTab = 'my_trainer';
          } else if (primaryTid != null) {
            state.trainerId = primaryTid;
          }
          updateBookingNameFieldsVisibility();
          updateRequestNameFieldsVisibility();
          /* From "Мои тренеры" / saved hub: open catalog list, not auto-jump to session primary trainer card */
          var forceCatalogBrowse = qp.get('tab') === 'catalog';
          if (forceCatalogBrowse) state.activeTab = 'catalog';
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
              slot_id: qp.get('slot_id'),
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
            if (returnCtx.slot_id != null && returnCtx.slot_id !== '') {
              var deepSlot = parseInt(returnCtx.slot_id, 10);
              state.pendingDeepLinkSlotId = !isNaN(deepSlot) && deepSlot > 0 ? deepSlot : null;
            }
            var dVariant = returnCtx.service_price_variant_id;
            if (dVariant != null && dVariant !== '') {
              var dv = parseInt(dVariant, 10);
              if (!isNaN(dv) && dv > 0) state.bookingContextServicePriceVariantId = dv;
            }
          }
          function showInitialScreen() {
            if (catalogSummaryHydrated && freshSessionFingerprint === catalogHydrateFingerprint) {
              activateSummaryScreen();
              switchTab(state.activeTab || 'catalog');
              refreshCatalogOfferTrainerCount();
              if (state.cityId && state.serviceId) prefetchFirstPageIfNeeded();
              return;
            }
            hydrateCatalogSummary();
          }
          /* Deep link ?trainer_id= — карточка или сразу слоты (?action=book from hub) */
          if (returnCtx && returnCtx.trainer_id) {
            var hubBookAction = qp.get('action') === 'book' && !returnCtx.slot_id;
            if (hubBookAction) {
              openTrainerDeepLinkSlotPick(returnCtx, explicitTrainerArenaIdsFromUrl, function() {
                showToast('Не удалось загрузить слоты. Попробуйте ещё раз.');
                showInitialScreen();
              });
              return;
            }
            openTrainerDeepLinkTrainerCard(returnCtx, explicitTrainerArenaIdsFromUrl, function() {
              if (state.trainerId) {
                state.openedFromMyTrainerTab = true;
                loadTrainerById(state.trainerId).then(function(t2) {
                  if (t2) {
                    state.trainerId = t2.id != null ? Number(t2.id) : state.trainerId;
                    state.selectedTrainer = t2;
                    state.trainerName = trainerName(t2);
                    reconcileCatalogServiceWithTrainerAsync(t2).then(function() {
                      initTrainerSlotsArenaFilter(t2, { explicitArenaIds: explicitTrainerArenaIdsFromUrl });
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
              if (returnCtx && returnCtx.trainer_id) {
                showToast('Не удалось открыть карточку тренера. Попробуйте ещё раз из ссылки в чате.');
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
                  initTrainerSlotsArenaFilter(t, { explicitArenaIds: explicitTrainerArenaIdsFromUrl });
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
