    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        if (typeof tg.ready === 'function') tg.ready();
        if (typeof tg.expand === 'function') tg.expand();
        if (typeof window.__applyTrainerHomeTheme === 'function') window.__applyTrainerHomeTheme();
        try {
          var darkUi = document.documentElement.classList.contains('hub-is-dark');
          var bgHex = darkUi ? '#1c1c1c' : '#fffbec';
          if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
          if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
        } catch (e) {}
      }
      var initData = tg && tg.initData ? tg.initData : '';
      /** Set after GET /trainer/access when initData present (onboarding vs active). */
      var trainerAccessSnapshot = null;

      var ICONS = {
        cal: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
        users: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
        inbox: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
        ticket: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2"/><path d="M13 11v2"/><path d="M13 17v2"/></svg>',
        user: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
        card: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>',
        chart: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 3v18h18"/><path d="M7 12l4-4 4 4 6-6"/></svg>',
        gift: '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 12v10H4V12"/><rect x="2" y="7" width="20" height="5" rx="1"/><path d="M12 22V7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/></svg>',
        groups:
          '<svg class="hub-tile-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
      };
      /** Cap upcoming booking cards so the hub never renders an unbounded list. */
      var HUB_UPCOMING_BOOKINGS_MAX = 5;
      /** Row cap for GET /trainer/bookings (server); higher than HUB_UPCOMING_BOOKINGS_MAX for group-slot dedupe across days. */
      var HUB_BOOKINGS_FETCH_LIMIT = 32;

      /** Debounce visibility refresh (Telegram WebView tab switches). */
      var hubVisibilityDebounceTimer = null;
      /** Last loadBookings fetch — aborted when a newer load starts. */
      var hubBookingsAbort = null;

      /** Mirrors server gate on GET /trainer/stats (SUBSCRIPTION_TIER_ANALYTICS). */
      var hasAnalyticsAccess = false;
      /** Last JSON from GET /trainer/subscription/status — used if sessionStorage was cleared (Telegram WebView) but URL has hub_celebrate=1. */
      var hubLastSubscriptionStatus = null;

      /** Last GET /trainer/onboarding/checklist payload — drives hero + empty list copy (avoid slots CTA before profile/active). */
      var hubOnboardingData = null;
      /** Last bookings payload from /trainer/bookings — used to refresh empty-state HTML after onboarding loads. */
      var hubLastBookingsDays = null;
      var hubLastTodayCount = 0;
      var hubLastFirstWhen = '';
      var hubLastWeekCount = 0;
      var hubLastUpcomingListCount = 0;
      /** Bookings with status pending — drives summary hint + week card highlight. */
      var hubLastPendingCount = 0;
      /** Formatted revenue for hub «С 1-го числа» (MTD API), or null. */
      var hubMtdRevenueText = null;
      /** Client requests without trainer response (GET /trainer/requests/summary). */
      var hubLastNewRequestsCount = 0;
      var hubRequestsStatReady = false;
      /** From trainer profile — group classes switch in trainer form. */
      var hubGroupClassesEnabled = false;
      /** From subscription status — groups module gate (must be enabled in paid modules). */
      var hubGroupsModuleEnabled = false;
      /** False until first GET /trainer/subscription/status completes (initData only) — drives Stats placeholder tile. */
      var hubSubscriptionStatusReady = false;
      /** When hub bootstrap included MTD revenue, skip duplicate GET /trainer/hub/revenue-mtd in loadBookings. */
      var hubRevenueSkipFetchOnce = false;

      function syncHubHeroCompact() {
        var el = document.querySelector('.hub-hero');
        if (!el) return;
        el.classList.toggle('hub-hero--compact', hubLastUpcomingListCount > 0);
      }

      function headersJson() {
        var h = { 'Content-Type': 'application/json' };
        if (tg && tg.initData) h['X-Telegram-Init-Data'] = tg.initData;
        return h;
      }
      function withInit(url) {
        if (!initData) return url;
        return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(initData);
      }
      function apiUrlWithQuery(path) {
        var url = '/api/webapp' + path;
        if (tg && tg.initData) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(tg.initData);
        return url;
      }

      /** Same aggregate as «Профиль»: if шапка shows «Одобрено», hub must not stay in onboarding lock. */
      function fetchTrainerProfileForHub() {
        if (!initData) return Promise.resolve({ ok: false, data: null });
        return fetch(apiUrlWithQuery('/trainer/profile'), { headers: headersJson() })
          .then(function(r) {
            return r.json().then(function(d) {
              return { ok: r.ok, data: d };
            });
          })
          .catch(function() {
            return { ok: false, data: null };
          });
      }

      function mergeHubAccessFromProfilePayload(prof) {
        if (!prof || !prof.ok || !prof.data || !prof.data.trainer) return;
        var tr = prof.data.trainer;
        var p = tr.profile && typeof tr.profile === 'object' ? tr.profile : {};
        hubGroupClassesEnabled = !!p.group_classes_enabled;
        var st = String(tr.status || '')
          .trim()
          .toLowerCase();
        if (st !== 'active') return;
        trainerAccessSnapshot = trainerAccessSnapshot || {};
        trainerAccessSnapshot.is_active = true;
        trainerAccessSnapshot.access_state = 'active';
        trainerAccessSnapshot.trainer_status = 'active';
        if (tr.id != null) trainerAccessSnapshot.trainer_id = tr.id;
      }

      function syncHubGroupsModuleAccessFromSubscription(status) {
        if (!status || typeof status !== 'object') {
          hubGroupsModuleEnabled = false;
          return;
        }
        if (status.modules && typeof status.modules === 'object') {
          hubGroupsModuleEnabled = !!status.modules.groups;
          return;
        }
        if (Array.isArray(status.unlocked_features)) {
          hubGroupsModuleEnabled = status.unlocked_features.indexOf('groups') !== -1;
          return;
        }
        hubGroupsModuleEnabled = false;
      }

      function webappBasePath() {
        var p = window.location.pathname || '';
        return p.replace(/[^/]+$/, '') || '/webapp/';
      }

      function isProfilePath(pathWithQuery) {
        var p = String(pathWithQuery || '').split('?')[0].replace(/^\//, '').toLowerCase();
        return p === 'trainer-profile';
      }

      /** True if trainer row is active — must not depend on TrainerMiniAppGate (script may fail to load). */
      function hubDataSaysTrainerActive(obj) {
        if (!obj) return false;
        var ia = obj.is_active;
        if (ia === true || ia === 'true' || ia === 1 || ia === '1') return true;
        if (String(obj.trainer_status || '')
          .trim()
          .toLowerCase() === 'active')
          return true;
        return false;
      }

      /** Schedule, clients, etc. — only after trainer account is active (profile stays open for onboarding). */
      function canOpenTrainerSectionsSync() {
        if (!initData) return false;
        /* Checklist / snapshot first: same API answers user sees in Network; do NOT require TrainerMiniAppGate. */
        if (hubDataSaysTrainerActive(hubOnboardingData)) return true;
        if (hubDataSaysTrainerActive(trainerAccessSnapshot)) return true;
        if (!window.TrainerMiniAppGate) return false;
        if (!trainerAccessSnapshot) return false;
        return TrainerMiniAppGate.isActive(trainerAccessSnapshot);
      }

      function showTrainerOnboardingNavAlert() {
        var msg =
          'Профиль ещё не готов: завершите анкету и дождитесь активации. Раздел «Профиль» можно открыть для редактирования.';
        if (tg && typeof tg.showAlert === 'function') tg.showAlert(msg);
        else alert(msg);
      }

      function navigateToImpl(pathWithQuery) {
        var url = webappBasePath() + pathWithQuery;
        url = withInit(url);
        window.location.href = url;
      }

      function applyHubLockedState() {
        var locked = !canOpenTrainerSectionsSync();
        var grid = document.getElementById('hubGrid');
        if (grid) {
          grid.querySelectorAll('.hub-tile:not(.hub-tile--skeleton)').forEach(function(btn) {
            var path = btn.getAttribute('data-path') || '';
            var isLocked = locked && path !== 'trainer-profile';
            btn.classList.toggle('hub-tile--locked', isLocked);
            btn.setAttribute('aria-disabled', isLocked ? 'true' : 'false');
          });
        }
        var pri = document.getElementById('hubPriorityActions');
        if (pri) {
          pri.querySelectorAll('.hub-quick-action').forEach(function(btn) {
            btn.classList.toggle('hub-quick-action--locked', locked);
            btn.setAttribute('aria-disabled', locked ? 'true' : 'false');
          });
        }
        syncHubHeroScheduleClick();
      }

      /** Big hero → расписание, когда день свободен и разделы не заблокированы. */
      function syncHubHeroScheduleClick() {
        var el = document.getElementById('heroScheduleCta');
        if (!el) return;
        var allowed = !!initData && hubLastTodayCount === 0 && canOpenTrainerSectionsSync();
        el.disabled = !allowed;
        el.classList.toggle('hub-hero-main--nav', allowed);
        if (allowed) {
          el.setAttribute(
            'aria-label',
            'Открыть расписание: слоты и записи, в том числе задним числом'
          );
        } else {
          el.removeAttribute('aria-label');
        }
      }

      (function () {
        var heroCta = document.getElementById('heroScheduleCta');
        if (heroCta) {
          heroCta.addEventListener('click', function() {
            if (this.disabled) return;
            navigateTo('schedule-editor');
          });
        }
      })();

      function navigateTo(pathWithQuery) {
        if (isProfilePath(pathWithQuery)) {
          navigateToImpl(pathWithQuery);
          return;
        }
        if (canOpenTrainerSectionsSync()) {
          navigateToImpl(pathWithQuery);
          return;
        }
        /* After moderation, is_active flips on the server while WebView keeps stale JS state — always refetch before blocking. */
        if (!initData || !window.TrainerMiniAppGate) {
          showTrainerOnboardingNavAlert();
          return;
        }
        Promise.all([
          window.TrainerMiniAppGate.fetchAccess(initData).catch(function() {
            return null;
          }),
          fetchTrainerProfileForHub(),
        ])
          .then(function(results) {
            var a = results[0];
            var prof = results[1];
            trainerAccessSnapshot = a;
            mergeHubAccessFromProfilePayload(prof);
            applyHubLockedState();
            if (trainerAccessSnapshot && window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)) {
              navigateToImpl(pathWithQuery);
            } else {
              showTrainerOnboardingNavAlert();
            }
          });
      }

      function navigateToWithHash(path, hash) {
        var url = webappBasePath() + String(path).replace(/^\//, '');
        url = withInit(url);
        if (hash) url += '#' + String(hash).replace(/^#/, '');
        window.location.href = url;
      }

      /** Reuses the same access refresh path as navigateTo, but runs a callback instead of route switch. */
      function ensureTrainerSectionsAccess(onAllowed) {
        if (canOpenTrainerSectionsSync()) {
          onAllowed();
          return;
        }
        if (!initData || !window.TrainerMiniAppGate) {
          showTrainerOnboardingNavAlert();
          return;
        }
        Promise.all([
          window.TrainerMiniAppGate.fetchAccess(initData).catch(function() {
            return null;
          }),
          fetchTrainerProfileForHub(),
        ]).then(function(results) {
          trainerAccessSnapshot = results[0];
          mergeHubAccessFromProfilePayload(results[1]);
          applyHubLockedState();
          if (trainerAccessSnapshot && window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)) onAllowed();
          else showTrainerOnboardingNavAlert();
        });
      }

      function onboardingAllComplete(data) {
        if (!data || !data.profile_complete || !data.is_active) return false;
        var slotsOk = !!(data.has_future_slots || data.has_any_booking);
        var bookingOk =
          'has_confirmed_booking' in data ? !!data.has_confirmed_booking : !!data.has_any_booking;
        return slotsOk && bookingOk;
      }

      function applyOnboardingChecklist(data) {
        hubOnboardingData = data;
        /* Checklist loads async after GET /trainer/access — can show activation before snapshot was refreshed. */
        var tsCh = data && String(data.trainer_status || '')
          .trim()
          .toLowerCase();
        var activeFromChecklist = !!(data && hubDataSaysTrainerActive(data));
        if (activeFromChecklist) {
          trainerAccessSnapshot = trainerAccessSnapshot || {};
          trainerAccessSnapshot.is_active = true;
          trainerAccessSnapshot.access_state = 'active';
          if (tsCh) trainerAccessSnapshot.trainer_status = tsCh;
          applyHubLockedState();
        }
        var strip = document.getElementById('onboardingStrip');
        if (!strip) return;
        /* All three steps done: no need to show the checklist anymore */
        if (data && onboardingAllComplete(data)) {
          strip.setAttribute('hidden', 'hidden');
          strip.style.display = 'none';
          applyHubHero();
          refreshHubEmptyBookingsIfNeeded();
          return;
        }
        strip.removeAttribute('hidden');
        strip.style.display = 'block';

        var stepP = document.getElementById('onboardingStepProfile');
        var iconP = document.getElementById('onboardingIconProfile');
        var hintP = document.getElementById('onboardingHintProfile');
        var ctaP = document.getElementById('onboardingCtaProfile');
        var pc = !!(data && data.profile_complete);
        if (stepP) {
          stepP.classList.toggle('done', pc);
          stepP.classList.remove('locked');
        }
        if (iconP) iconP.textContent = pc ? '✓' : '1';
        if (hintP) {
          hintP.textContent = pc
            ? 'Критерии анкеты закрыты — можно отправить на модерацию или ждать проверки.'
            : 'Заполните анкету по критериям проверки — «Открыть» откроет профиль для редактирования.';
        }
        if (ctaP) {
          ctaP.disabled = false;
          ctaP.textContent = pc ? 'Статус' : 'Открыть';
        }

        var active = !!(data && data.is_active);
        var slotsDone =
          active && !!(data && (data.has_future_slots || data.has_any_booking));
        var slotsLocked = !active;
        var stepS = document.getElementById('onboardingStepSlots');
        var iconS = document.getElementById('onboardingIconSlots');
        var hintS = document.getElementById('onboardingHintSlots');
        var ctaS = document.getElementById('onboardingCtaSlots');
        if (stepS) {
          stepS.classList.toggle('done', slotsDone);
          stepS.classList.toggle('locked', slotsLocked);
        }
        if (iconS) iconS.textContent = slotsDone ? '✓' : '2';
        if (hintS) {
          hintS.textContent = slotsLocked
            ? (data && data.slots_locked_reason) || 'Станет доступно после активации аккаунта.'
            : slotsDone
              ? data.has_future_available_slots
                ? 'В расписании есть свободные слоты.'
                : data.has_future_slots
                  ? 'Слоты в расписании есть — при необходимости добавьте новые окна.'
                  : 'Записи есть — расписание уже использовалось.'
              : 'Добавьте слоты в редакторе расписания.';
        }
        if (ctaS) {
          ctaS.disabled = slotsLocked || slotsDone;
          ctaS.textContent = slotsDone ? 'Готово' : 'Расписание';
        }

        var bookingStepDone =
          data &&
          ('has_confirmed_booking' in data ? !!data.has_confirmed_booking : !!data.has_any_booking);
        var bookDone = active && !!bookingStepDone;
        var bookLocked = !active;
        var stepB = document.getElementById('onboardingStepBooking');
        var iconB = document.getElementById('onboardingIconBooking');
        var hintB = document.getElementById('onboardingHintBooking');
        var ctaB = document.getElementById('onboardingCtaBooking');
        if (stepB) {
          stepB.classList.toggle('done', bookDone);
          stepB.classList.toggle('locked', bookLocked);
        }
        if (iconB) iconB.textContent = bookDone ? '✓' : '3';
        if (hintB) {
          hintB.textContent = bookLocked
            ? (data && data.bookings_locked_reason) || 'Станет доступно после активации аккаунта.'
            : bookDone
              ? 'Есть подтверждённая или завершённая запись.'
              : 'Создайте запись на свободный слот в редакторе расписания.';
        }
        if (ctaB) {
          ctaB.disabled = bookLocked || bookDone;
          ctaB.textContent = bookDone ? 'Готово' : 'К слотам';
        }

        applyHubHero();
        refreshHubEmptyBookingsIfNeeded();
      }

      /** When checklist arrives after bookings, re-render empty list so copy matches onboarding (no duplicate slots CTA). */
      function refreshHubEmptyBookingsIfNeeded() {
        var block = document.getElementById('bookingsBlock');
        if (!block || !hubLastBookingsDays) return;
        var total = 0;
        (hubLastBookingsDays || []).forEach(function(d) {
          total += (d.bookings || []).length;
        });
        if (total > 0) return;
        block.innerHTML = buildEmptyBookingsHtml();
        wireEmptyScheduleButton();
      }

      function buildEmptyBookingsHtml() {
        var onb = hubOnboardingData;
        var msg;
        if (!onb) {
          msg =
            'Нет предстоящих записей. Ниже блок «Первые шаги» подскажет, с чего начать.';
        } else if (!onb.profile_complete) {
          msg =
            'Нет предстоящих записей. Сначала завершите анкету в блоке «Первые шаги» — после проверки здесь появятся занятия.';
        } else if (!onb.is_active) {
          msg =
            'Нет предстоящих записей. Расписание и записи откроются после активации аккаунта.';
        } else if (onb.has_future_slots || onb.has_future_available_slots || onb.has_any_booking) {
          msg =
            'Нет предстоящих записей — когда появятся ближайшие занятия, они отобразятся здесь.';
        } else {
          msg = 'Нет предстоящих записей — добавьте слоты, чтобы клиенты могли выбрать время.';
        }
        var parts = ['<div class="hub-empty">' + escapeHtml(msg) + '</div>'];
        if (onb && onb.profile_complete && onb.is_active) {
          parts.push(
            '<div class="hub-empty-actions">' +
              '<button type="button" class="bd-btn bd-btn--primary" id="btnOpenSchedule">Расписание</button>' +
            '</div>'
          );
        }
        return parts.join('');
      }

      function wireEmptyScheduleButton() {
        var bsched = document.getElementById('btnOpenSchedule');
        if (bsched) bsched.onclick = function() { navigateTo('schedule-editor'); };
      }

      function loadOnboardingChecklist() {
        var strip = document.getElementById('onboardingStrip');
        if (!strip) return;
        if (!initData) {
          strip.setAttribute('hidden', 'hidden');
          strip.style.display = 'none';
          return;
        }
        fetch(apiUrlWithQuery('/trainer/onboarding/checklist'), { headers: headersJson() })
          .then(function(r) {
            return r.json().then(function(d) {
              return { ok: r.ok, data: d };
            });
          })
          .then(function(o) {
            if (!o.ok || !o.data) return;
            applyOnboardingChecklist(o.data);
          })
          .catch(function() {});
      }

      function wireOnboardingHub() {
        var ctaP = document.getElementById('onboardingCtaProfile');
        if (ctaP) {
          ctaP.onclick = function() {
            if (ctaP.textContent === 'Статус') {
              navigateToWithHash('trainer-profile', 'moderation');
              return;
            }
            navigateTo('trainer-profile');
          };
        }
        var ctaS = document.getElementById('onboardingCtaSlots');
        if (ctaS) {
          ctaS.onclick = function() {
            if (ctaS.disabled) return;
            navigateTo('schedule-editor');
          };
        }
        var ctaB = document.getElementById('onboardingCtaBooking');
        if (ctaB) {
          ctaB.onclick = function() {
            if (ctaB.disabled) return;
            navigateTo('schedule-editor');
          };
        }
        var faq = document.getElementById('onboardingFaqBtn');
        if (faq) {
          faq.onclick = function() {
            navigateTo('trainer-faq');
          };
        }
        document.addEventListener('visibilitychange', function() {
          if (document.hidden) return;
          if (hubVisibilityDebounceTimer) clearTimeout(hubVisibilityDebounceTimer);
          hubVisibilityDebounceTimer = setTimeout(function() {
            hubVisibilityDebounceTimer = null;
            if (!initData) return;
            ensureHubBookingsPlaceholder();
            /* One bootstrap round-trip instead of access + profile + bookings (same as cold start). */
            fetch(
              apiUrlWithQuery(
                '/trainer/hub/bootstrap?bookings_limit=' + encodeURIComponent(String(HUB_BOOKINGS_FETCH_LIMIT))
              ),
              { headers: headersJson(), cache: 'no-store' }
            )
              .then(function(r) {
                if (!r.ok) throw new Error('bootstrap');
                return r.json();
              })
              .then(function(data) {
                applyHubBootstrapPayload(data);
                applyHubLockedState();
                if (
                  trainerAccessSnapshot &&
                  window.TrainerMiniAppGate &&
                  !window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)
                ) {
                  renderBookingsOnboardingBlock(trainerAccessSnapshot);
                  renderHubSummaryHints();
                  return;
                }
                if (data.bookings && data.bookings.days) {
                  setStateMessage('');
                  renderBookings(data.bookings.days);
                } else {
                  loadBookings();
                }
                renderHubSummaryHints();
                if (!data.onboarding_checklist) {
                  loadOnboardingChecklist();
                }
              })
              .catch(function() {
                loadOnboardingChecklist();
                if (!window.TrainerMiniAppGate) return;
                Promise.all([
                  window.TrainerMiniAppGate.fetchAccess(initData).catch(function() {
                    return null;
                  }),
                  fetchTrainerProfileForHub(),
                ]).then(function(results) {
                  var a = results[0];
                  var prof = results[1];
                  if (a) trainerAccessSnapshot = a;
                  mergeHubAccessFromProfilePayload(prof);
                  applyHubLockedState();
                  if (trainerAccessSnapshot && window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)) {
                    loadBookings();
                  }
                });
              });
          }, 400);
        });
      }

      function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;');
      }

      function clientLabel(b) {
        var first = (b.client_first_name || '').trim();
        var last = (b.client_last_name || '').trim();
        var name = (first + ' ' + last).trim();
        if (name) return name;
        if (b.client_phone) return b.client_phone;
        return 'Клиент';
      }

      function formatDateShort(iso) {
        if (!iso) return '';
        var d = iso.slice(0, 10).split('-');
        if (d.length !== 3) return iso;
        return d[2] + '.' + d[1] + '.' + d[0];
      }

      function dayHeaderLine(day) {
        var dateStr = formatDateShort(day.date);
        var lab = (day.day_label || '').trim();
        if (dateStr && lab) return dateStr + ' (' + lab + ')';
        return dateStr || lab || '';
      }

      function setStateMessage(text, kind) {
        var el = document.getElementById('stateMessage');
        if (!text) {
          el.style.display = 'none';
          el.textContent = '';
          el.className = 'state-panel';
          return;
        }
        el.textContent = text;
        el.className = 'state-panel ' + (kind === 'error' ? 'error' : 'loading');
        el.style.display = 'block';
      }

      /**
       * Loads unanswered client requests count for contextual summary hints.
       * Safe to call in parallel with loadBookings; re-renders hints when done.
       */
      function loadHubRequestsSummary() {
        if (!initData || !canOpenTrainerSectionsSync()) {
          hubRequestsStatReady = false;
          hubLastNewRequestsCount = 0;
          renderHubSummaryHints();
          return Promise.resolve();
        }
        return fetch(apiUrlWithQuery('/trainer/requests/summary'), { headers: headersJson() })
          .then(function(r) {
            return r.json().then(function(data) {
              return { status: r.status, ok: r.ok, data: data };
            });
          })
          .then(function(o) {
            hubRequestsStatReady = true;
            if (!o.ok || o.status === 401 || o.status === 403) {
              hubLastNewRequestsCount = 0;
            } else {
              var n = o.data && o.data.unanswered_count;
              hubLastNewRequestsCount = typeof n === 'number' && !isNaN(n) ? n : 0;
            }
            renderHubSummaryHints();
          })
          .catch(function() {
            hubRequestsStatReady = true;
            hubLastNewRequestsCount = 0;
            renderHubSummaryHints();
          });
      }

      /** Renders actionable chips under «Сводка» when pending bookings or new requests exist. */
      function renderHubSummaryHints() {
        var el = document.getElementById('hubSummaryHints');
        if (!el) return;
        if (!initData) {
          el.setAttribute('hidden', '');
          el.innerHTML = '';
          return;
        }
        var hints = [];
        if (hubLastPendingCount > 0) {
          var ptxt =
            hubLastPendingCount +
            ' ' +
            pluralRu(
              hubLastPendingCount,
              'запись требует подтверждения',
              'записи требуют подтверждения',
              'записей требуют подтверждения'
            );
          hints.push({ type: 'urgent', text: ptxt, href: 'schedule-editor' });
        }
        if (hubRequestsStatReady && hubLastNewRequestsCount > 0) {
          hints.push({
            type: 'info',
            text:
              hubLastNewRequestsCount +
              ' ' +
              pluralRu(
                hubLastNewRequestsCount,
                'новая заявка без ответа',
                'новые заявки без ответа',
                'новых заявок без ответа'
              ),
            href: 'trainer-requests',
          });
        }
        if (!hints.length) {
          el.setAttribute('hidden', '');
          el.innerHTML = '';
          return;
        }
        el.removeAttribute('hidden');
        el.innerHTML = hints
          .map(function(h) {
            var mod = h.type === 'urgent' ? 'urgent' : 'info';
            return (
              '<button type="button" class="hub-summary-hint hub-summary-hint--' +
              mod +
              '" data-hub-hint-href="' +
              escapeHtml(h.href) +
              '">' +
              '<span class="hub-summary-hint__text">' +
              escapeHtml(h.text) +
              '</span>' +
              '<span class="hub-summary-hint__chev" aria-hidden="true">›</span>' +
              '</button>'
            );
          })
          .join('');
        el.querySelectorAll('[data-hub-hint-href]').forEach(function(btn) {
          btn.onclick = function() {
            navigateTo(btn.getAttribute('data-hub-hint-href'));
          };
        });
      }

      function formatHubMoneyCents(cents) {
        var n = Number(cents);
        if (!isFinite(n) || n < 0) return '0 BYN';
        var v = n / 100;
        return v.toFixed(v % 1 === 0 ? 0 : 2) + ' BYN';
      }

      /** Loads accrual MTD (sessions + pass + cert sales); updates hubMtdRevenueText and hero. */
      function fetchHubMtdRevenue() {
        if (!initData) return;
        if (hubRevenueSkipFetchOnce) {
          hubRevenueSkipFetchOnce = false;
          applyHubHero();
          return;
        }
        if (
          trainerAccessSnapshot &&
          window.TrainerMiniAppGate &&
          !window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)
        ) {
          hubMtdRevenueText = null;
          return;
        }
        fetch(apiUrlWithQuery('/trainer/hub/revenue-mtd'), { headers: headersJson() })
          .then(function(r) {
            if (!r.ok) {
              hubMtdRevenueText = null;
              return null;
            }
            return r.json();
          })
          .then(function(d) {
            var revCard = document.getElementById('statRevenue');
            if (!d || d.revenue_total_cents == null) {
              hubMtdRevenueText = null;
              if (revCard) {
                revCard.removeAttribute('title');
              }
            } else {
              hubMtdRevenueText = formatHubMoneyCents(d.revenue_total_cents);
              if (
                revCard &&
                d.period_start &&
                d.period_end
              ) {
                revCard.setAttribute(
                  'title',
                  'Начислено с ' + String(d.period_start) + ' по ' + String(d.period_end) + ': занятия, абонементы, сертификаты'
                );
              }
            }
            applyHubHero();
          })
          .catch(function() {
            hubMtdRevenueText = null;
            applyHubHero();
          });
      }

      function setStats(todayCount, weekCount) {
        var wrap = document.getElementById('hubStats');
        var todayValue = document.getElementById('statTodayValue');
        var weekValue = document.getElementById('statWeekValue');
        var revenueValue = document.getElementById('statRevenueValue');
        
        if (!wrap || !todayValue || !weekValue || !revenueValue) {
          renderHubSummaryHints();
          return;
        }

        if (!initData) {
          wrap.setAttribute('aria-hidden', 'true');
          wrap.style.display = 'none';
          renderHubSummaryHints();
          return;
        }
        
        wrap.style.display = 'grid';
        wrap.setAttribute('aria-hidden', 'false');
        
        todayValue.textContent = todayCount === 0 ? '0' : String(todayCount);
        weekValue.textContent = weekCount === 0 ? '0' : String(weekCount);
        revenueValue.textContent =
          hubMtdRevenueText != null && hubMtdRevenueText !== '' ? hubMtdRevenueText : '—';
        
        // Highlight today's card if there are bookings
        var todayCard = document.getElementById('statToday');
        if (todayCard) {
          if (todayCount > 0) {
            todayCard.classList.add('stat-highlight');
          } else {
            todayCard.classList.remove('stat-highlight');
          }
        }

        var weekCard = document.getElementById('statWeek');
        if (weekCard) {
          if (hubLastPendingCount > 0) {
            weekCard.classList.add('stat-highlight');
          } else {
            weekCard.classList.remove('stat-highlight');
          }
        }

        renderHubSummaryHints();
      }

      /**
       * Hero + stats: aligned with onboarding — no "add slots" until profile is complete and account active.
       */
      function applyHubHero() {
        var greeting = document.getElementById('heroGreeting');
        var title = document.getElementById('heroTitle');
        var subtitle = document.getElementById('heroSubtitle');

        if (!greeting || !title || !subtitle) return;

        var now = new Date();
        var hour = now.getHours();
        var greetingText = 'Добро пожаловать';
        if (hour >= 6 && hour < 12) greetingText = 'Доброе утро';
        else if (hour >= 12 && hour < 18) greetingText = 'Добрый день';
        else if (hour >= 18 && hour < 23) greetingText = 'Добрый вечер';
        else greetingText = 'Доброй ночи';
        greeting.textContent = greetingText;

        if (!initData) {
          title.textContent = 'Войдите через бота';
          subtitle.textContent = 'Откройте экран из бота тренера — подтянутся записи и быстрый доступ к разделам.';
          setStats(0, 0);
          syncHubHeroScheduleClick();
          return;
        }

        var count = hubLastTodayCount;
        var firstLine = hubLastFirstWhen;
        var weekCount = hubLastWeekCount;

        if (count > 0) {
          title.textContent =
            count === 1 ? 'Одна запись сегодня' : count + ' ' + pluralRu(count, 'запись', 'записи', 'записей') + ' сегодня';
          subtitle.textContent = firstLine
            ? 'Первая в ' + firstLine + ' — карточки на сегодня в списке выше.'
            : 'Сегодняшние занятия перечислены в блоке выше.';
          setStats(count, weekCount || 0);
          syncHubHeroScheduleClick();
          return;
        }

        var onb = hubOnboardingData;
        if (!onb) {
          title.textContent = 'Ваш день';
          subtitle.textContent = 'Предстоящих записей на сегодня нет.';
          setStats(0, weekCount || 0);
          syncHubHeroScheduleClick();
          return;
        }

        if (!onb.profile_complete) {
          title.textContent = 'Сначала анкета';
          subtitle.textContent =
            'Ниже в блоке «Первые шаги» заполните профиль и отправьте анкету на проверку — после одобрения откроются расписание и заявки.';
          setStats(0, weekCount || 0);
          syncHubHeroScheduleClick();
          return;
        }

        if (!onb.is_active) {
          title.textContent = 'Скоро полный доступ';
          subtitle.textContent =
            'Ниже в блоке «Первые шаги» видно статус активации — расписание и записи откроются после активации аккаунта.';
          setStats(0, weekCount || 0);
          syncHubHeroScheduleClick();
          return;
        }

        title.textContent = 'Свободный день';
        if (!onb.has_future_available_slots && !onb.has_future_slots) {
          subtitle.textContent =
            'Предстоящих записей пока нет. Добавьте слоты в расписании — клиенты смогут выбрать время.';
        } else {
          subtitle.textContent =
            'Записей на сегодня нет — когда клиенты запишутся, они появятся здесь.';
        }
        setStats(0, weekCount || 0);
        syncHubHeroScheduleClick();
      }

      function pluralRu(n, one, few, many) {
        var m = n % 10;
        var mm = n % 100;
        if (mm >= 11 && mm <= 14) return many;
        if (m === 1) return one;
        if (m >= 2 && m <= 4) return few;
        return many;
      }

      function openTelegramDmMiniApp(username, telegramId) {
        var un = String(username || '').replace(/^@/, '').trim();
        var url;
        if (un) url = 'https://t.me/' + encodeURIComponent(un);
        else if (telegramId != null && telegramId !== '') url = 'tg://user?id=' + encodeURIComponent(String(telegramId));
        else return;
        var tg = window.Telegram && window.Telegram.WebApp;
        if (tg) {
          try {
            if (typeof tg.openTelegramLink === 'function') {
              tg.openTelegramLink(url);
              return;
            }
          } catch (e) { /* noop */ }
          try {
            if (typeof tg.openLink === 'function') {
              tg.openLink(url);
              return;
            }
          } catch (e2) { /* noop */ }
        }
        window.location.href = url;
      }

      function hubTrainerCanWriteClient(b) {
        var cap = parseInt(String(b.slot_capacity != null ? b.slot_capacity : '1'), 10);
        if (isNaN(cap) || cap > 1) return false;
        var tid = b.client_telegram_id;
        var un = (b.client_telegram_username || '').replace(/^@/, '').trim();
        return (tid != null && tid !== '') || !!un;
      }

      /** PRD E1: backend marks row as inside [start,end); compact label for current session. */
      function hubSessionNowPillHtml(b) {
        if (!b || !b.hub_in_session) return '';
        return (
          '<span class="hub-session-now-pill" role="status" aria-label="Текущее занятие">сейчас</span>'
        );
      }

      /** After E2 report, hub list shows a discreet hint (same API as detail). */
      function hubProblemReportPillHtml(b) {
        if (!b || !b.problem_reported) return '';
        return '<span class="hub-problem-pill" role="status">отчёт отправлен</span>';
      }

      /** Same labels/classes as schedule-editor calendar rows (booked slots). */
      function hubBookingSlotRowHtml(b, timeRange) {
        var bst = String(b.status || 'confirmed').toLowerCase();
        var pending = bst === 'pending';
        var statusLabel = pending ? 'к подтверждению' : 'подтверждено';
        var statusClass = pending ? 'booked booked-pending' : 'booked booked-confirmed';
        var rowMod = pending ? 'slot-booking-pending' : 'slot-booking-confirmed';
        var cap = parseInt(String(b.slot_capacity != null ? b.slot_capacity : '1'), 10);
        if (isNaN(cap) || cap < 1) cap = 1;

        /* Group slot: match schedule-editor group hub — occupancy meter + chip; no client name in preview */
        if (cap > 1) {
          var occ = parseInt(String(b.slot_active_bookings != null ? b.slot_active_bookings : ''), 10);
          if (isNaN(occ) || occ < 0) occ = 1;
          occ = Math.min(occ, cap);
          var spotsLeft = Math.max(0, cap - occ);
          var pct = cap > 0 ? Math.min(100, Math.round((occ / cap) * 100)) : 0;
          var svc = (b.services_str || '').trim();
          var ar = (b.arenas_str || '').trim();
          var metaHtml = '';
          if (svc || ar) {
            metaHtml += '<div class="slot-group-catalog-meta">';
            if (svc) metaHtml += '<div class="slot-group-meta-line">' + escapeHtml(svc) + '</div>';
            if (ar) metaHtml += '<div class="slot-group-meta-line">' + escapeHtml(ar) + '</div>';
            metaHtml += '</div>';
          }
          var spotsPill = spotsLeft > 0
            ? '<span class="slot-status available hub-group-spots-pill">ещё места</span>'
            : '<span class="slot-status booked hub-group-spots-pill">полная</span>';
          var pendingExtra = pending
            ? '<span class="slot-status booked-pending hub-group-spots-pill">' + statusLabel + '</span>'
            : '';
          return (
            '<div class="slot-row slot-booked-click slot-group-hub-preview ' + rowMod + '" data-bid="' + String(b.id) + '" data-slot-id="' + String(b.slot_id != null ? b.slot_id : '') + '" data-slot-date="' + escapeHtml(b.slot_date || '') + '" role="button" tabindex="0">' +
              '<div class="slot-row-left">' +
                '<div class="hub-slot-time-row">' +
                '<span class="slot-time">' + escapeHtml(timeRange) + '</span>' +
                hubSessionNowPillHtml(b) + hubProblemReportPillHtml(b) +
                '</div>' +
                metaHtml +
                '<div class="slot-group-meter-wrap" aria-hidden="true"><div class="slot-group-meter-fill" style="width:' + pct + '%"></div></div>' +
              '</div>' +
              '<div class="slot-meta slot-meta--group">' +
                '<span class="slot-group-chip">' + occ + '/' + cap + '</span>' +
                spotsPill +
                pendingExtra +
              '</div>' +
            '</div>'
          );
        }

        var arena = (b.arenas_str || '').trim();
        var venueInner = arena
          ? escapeHtml(arena)
          : '<span class="venue-muted">не указано</span>';
        var msgBtn = '';
        if (hubTrainerCanWriteClient(b)) {
          msgBtn =
            '<button type="button" class="hub-slot-msg" data-hub-dm="trainer"' +
            ' data-dm-un="' + escapeHtml((b.client_telegram_username || '').replace(/^@/, '')) + '"' +
            ' data-dm-tid="' + escapeHtml(b.client_telegram_id != null ? String(b.client_telegram_id) : '') + '"' +
            ' aria-label="Написать клиенту в Telegram" title="Написать в Telegram">' +
            '<svg class="hub-slot-msg-icon" viewBox="0 0 24 24" aria-hidden="true">' +
            '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>' +
            '</svg>' +
            '</button>';
        }
        return (
          '<div class="slot-row slot-booked-click ' + rowMod + '" data-bid="' + String(b.id) + '" role="button" tabindex="0">' +
            '<div class="slot-row-left">' +
              '<div class="hub-slot-time-row">' +
              '<span class="slot-time">' + escapeHtml(timeRange) + '</span>' +
              hubSessionNowPillHtml(b) + hubProblemReportPillHtml(b) +
              '</div>' +
              '<div class="slot-venue">📍 ' + venueInner + '</div>' +
              '<div class="slot-client-hint">' + escapeHtml(clientLabel(b)) + '</div>' +
            '</div>' +
            '<div class="slot-meta">' +
              '<span class="slot-status ' + statusClass + '">' + statusLabel + '</span>' +
              msgBtn +
            '</div>' +
          '</div>'
        );
      }

      function closeHubGroupSlotModal() {
        var mgr = document.getElementById('hubModalGroupSlot');
        if (!mgr) return;
        mgr.style.display = 'none';
        mgr.setAttribute('aria-hidden', 'true');
      }

      /** Removes full-screen cover shown while reopening group modal from URL (see body inline script). */
      function releaseHubReopenGroupCover() {
        try {
          var c = document.getElementById('hubReopenGroupCover');
          if (c) c.remove();
          document.documentElement.classList.remove('hub-reopen-group-pending');
        } catch (e) { /* */ }
      }

      /** Group slot hub: same UX as schedule-editor openGroupSlotModal (list + add participant). */
      function openHubGroupSlotModal(slotId, slotDateFallback) {
        var id = parseInt(String(slotId), 10);
        if (isNaN(id)) return;
        fetch(apiUrlWithQuery('/trainer/slots/' + id + '/group-hub'), { headers: headersJson() })
          .then(function(r) {
            if (r.status === 404) {
              if (tg && tg.showAlert) tg.showAlert('Слот не найден или не групповой.');
              return Promise.reject(null);
            }
            if (!r.ok) return Promise.reject(new Error('bad'));
            return r.json();
          })
          .then(function(d) {
            if (!d) {
              releaseHubReopenGroupCover();
              return;
            }
            var mgr = document.getElementById('hubModalGroupSlot');
            if (!mgr) {
              releaseHubReopenGroupCover();
              return;
            }
            mgr.style.display = 'flex';
            mgr.setAttribute('aria-hidden', 'false');
            releaseHubReopenGroupCover();
            var cap = parseInt(String(d.capacity), 10) || 1;
            var occ = parseInt(String(d.active_bookings), 10);
            if (isNaN(occ)) occ = 0;
            var spotsLeft = d.spots_left != null ? parseInt(String(d.spots_left), 10) : Math.max(0, cap - occ);
            if (isNaN(spotsLeft)) spotsLeft = Math.max(0, cap - occ);
            document.getElementById('hubGroupSlotTitle').textContent = (d.start_time || '') + '–' + (d.end_time || '');
            var sub = 'Занято ' + occ + ' из ' + cap;
            if (spotsLeft > 0) sub += ' · свободно мест: ' + spotsLeft;
            else sub += ' · группа набрана';
            document.getElementById('hubGroupSlotSub').textContent = sub;
            var listEl = document.getElementById('hubGroupSlotList');
            listEl.innerHTML = '';
            var bookings = d.bookings || [];
            bookings.forEach(function(bk) {
              var st = (bk.status || '').toLowerCase();
              var stLabel = st === 'pending' ? 'Ожидает подтверждения' : 'Подтверждено';
              var bid = parseInt(bk.booking_id, 10);
              var btn = document.createElement('button');
              btn.type = 'button';
              btn.className = 'group-slot-row';
              btn.innerHTML =
                '<span><span class="g-name">' +
                escapeHtml(String(bk.client_preview || 'Клиент')) +
                '</span><br><span class="g-st">' +
                stLabel +
                '</span></span><span aria-hidden="true" style="color:var(--tg-theme-hint-color);font-size:18px;">›</span>';
              btn.onclick = function(ev) {
                ev.stopPropagation();
                closeHubGroupSlotModal();
                navigateTo(
                  'schedule-editor?open_booking=' +
                    encodeURIComponent(bid) +
                    '&from=hub&hub_group_slot=' +
                    encodeURIComponent(String(id))
                );
              };
              listEl.appendChild(btn);
            });
            var addBtn = document.getElementById('hubGroupSlotAddBtn');
            var anchorDate = (d.slot_date || slotDateFallback || '').toString().slice(0, 10);
            if (spotsLeft > 0) {
              addBtn.style.display = 'block';
              addBtn.onclick = function() {
                closeHubGroupSlotModal();
                openHubBookGroupSlotModal(id, d.service_id, (d.start_time || '') + '–' + (d.end_time || ''));
              };
            } else {
              addBtn.style.display = 'none';
              addBtn.onclick = null;
            }
          })
          .catch(function(e) {
            releaseHubReopenGroupCover();
            if (e === null) return;
            if (tg && tg.showAlert) tg.showAlert('Не удалось загрузить группу.');
          });
      }

      /** Belarus phone — aligned with schedule-editor (POST /trainer/clients). */
      var HUB_PHONE_MAX = 32;
      var PHONE_BY_RE_HUB = /^\+375\d{9}$/;
      function normalizePhoneHub(s) {
        var raw = String(s || '').trim();
        if (!raw) return '';
        var d = raw.replace(/\D/g, '');
        if (!d) return raw.slice(0, HUB_PHONE_MAX);
        if (d.length === 12 && d.indexOf('375') === 0) return '+' + d;
        if (d.length === 11 && d.indexOf('80') === 0) return '+375' + d.slice(2);
        if (d.length === 9) return '+375' + d;
        return raw.replace(/\s+/g, '').replace(/-/g, '').replace(/\(/g, '').replace(/\)/g, '').replace(/\./g, '').slice(0, HUB_PHONE_MAX);
      }
      function validatePhoneHubMsg(normalized) {
        var t = normalized;
        if (!t) return 'Укажите номер телефона.';
        if (t.length > HUB_PHONE_MAX) return 'Телефон: не длиннее 32 символов.';
        if (!PHONE_BY_RE_HUB.test(t)) return 'Укажите корректный номер телефона.';
        return null;
      }

      function hubToast(msg) {
        if (tg && tg.showAlert) tg.showAlert(msg);
        else alert(msg);
      }

      var hubBookSlotId = null;
      var hubBookServiceId = null;
      /** Quick-book only: chosen catalog tier (POST service_price_variant_id). */
      var hubBookPriceVariantId = null;
      var hubBookQuickPayload = null;
      var hubBookQuickServices = [];
      var hubQuickBookScheduleGrid = null;
      var hubQuickBookSlotsForDay = [];
      var hubQuickBookRefreshTimer = null;
      var hubBookSlotWhenLabel = '';
      var hubBookPendingClientId = null;
      var hubBookPendingClientName = '';

      function setHubBookOptExistingVisible(show) {
        var btn = document.getElementById('hubBookOptExisting');
        if (!btn) return;
        btn.style.display = show ? '' : 'none';
        btn.setAttribute('aria-hidden', show ? 'false' : 'true');
      }

      function closeHubBookGroupModals() {
        var m = document.getElementById('hubModalBookGroupSlot');
        var c = document.getElementById('hubModalBookGroupConfirm');
        if (m) {
          m.style.display = 'none';
          m.setAttribute('aria-hidden', 'true');
        }
        if (c) {
          c.style.display = 'none';
          c.setAttribute('aria-hidden', 'true');
        }
        hubBookPendingClientId = null;
        hubBookPendingClientName = null;
      }

      function resetHubBookSlotState() {
        hubBookSlotId = null;
        hubBookServiceId = null;
        hubBookPriceVariantId = null;
        hubBookQuickPayload = null;
        hubBookQuickServices = [];
        hubQuickBookSlotsForDay = [];
        hubBookSlotWhenLabel = '';
        setHubBookServiceVisibility(false);
        fillHubBookServiceSelect([]);
      }

      function resetHubBookSteps() {
        var ch = document.getElementById('hubBookStepChoice');
        var ex = document.getElementById('hubBookStepExisting');
        var nw = document.getElementById('hubBookStepNew');
        if (ch) ch.style.display = 'block';
        if (ex) ex.style.display = 'none';
        if (nw) nw.style.display = 'none';
      }

      function hubBookClientsUrl(q) {
        var path = '/trainer/clients';
        if (q && String(q).trim()) path += '?q=' + encodeURIComponent(String(q).trim());
        return apiUrlWithQuery(path);
      }

      function setHubBookServiceVisibility(show) {
        var wrap = document.getElementById('hubBookServiceWrap');
        if (!wrap) return;
        wrap.style.display = show ? 'block' : 'none';
      }

      function fillHubBookServiceSelect(services) {
        var sel = document.getElementById('hubBookServiceSelect');
        if (!sel) return;
        sel.innerHTML = '';
        (services || []).forEach(function(s) {
          var opt = document.createElement('option');
          opt.value = String(s.id);
          opt.textContent = String(s.name || 'Услуга');
          sel.appendChild(opt);
        });
        if (hubBookServiceId != null) sel.value = String(hubBookServiceId);
      }

      var HUB_PRICE_TIER_LABEL_RU = {
        child: 'Детский',
        adult: 'Взрослый',
        two_children: '2 ребенка',
        two_adults: '2 взрослых',
        adult_and_child: 'Взрослый + ребенок',
      };
      function hubPriceTierLabelRu(tier) {
        var k = (tier.tier_kind || '').toLowerCase();
        return HUB_PRICE_TIER_LABEL_RU[k] || tier.label || 'Тариф';
      }

      /** Prefer single-adult tier when API lists child first (same idea as schedule-editor). */
      function hubPickDefaultPriceTierId(tiers) {
        if (!tiers || !tiers.length) return null;
        if (tiers.length === 1) return tiers[0].id;
        var adult = tiers.filter(function(t) { return (t.tier_kind || '').toLowerCase() === 'adult'; })[0];
        return adult ? adult.id : tiers[0].id;
      }

      function syncHubBookPriceTierRadios() {
        var wrap = document.getElementById('hubBookPriceTierWrap');
        var host = document.getElementById('hubBookPriceTierRadios');
        if (!wrap || !host) return;
        if (!hubBookQuickPayload) {
          wrap.style.display = 'none';
          host.innerHTML = '';
          hubBookPriceVariantId = null;
          return;
        }
        var sid = hubBookServiceId;
        var svc = (hubBookQuickServices || []).filter(function(x) { return x.id === sid; })[0];
        var tiers = (svc && svc.price_tiers) ? svc.price_tiers : [];
        if (tiers.length <= 1) {
          wrap.style.display = 'none';
          host.innerHTML = '';
          hubBookPriceVariantId = tiers.length === 1 ? tiers[0].id : null;
          return;
        }
        wrap.style.display = 'block';
        host.innerHTML = '';
        var gname = 'hub_bpt_' + String(sid || 0);
        var preferredId = hubPickDefaultPriceTierId(tiers);
        tiers.forEach(function(tier) {
          var lab = document.createElement('label');
          lab.style.display = 'flex';
          lab.style.alignItems = 'center';
          lab.style.gap = '10px';
          lab.style.marginBottom = '8px';
          var inp = document.createElement('input');
          inp.type = 'radio';
          inp.name = gname;
          inp.value = String(tier.id);
          var pb = tier.price_byn;
          var priceStr = (pb === Math.floor(pb) ? pb : Number(pb).toFixed(2)) + ' BYN';
          lab.appendChild(inp);
          lab.appendChild(document.createTextNode(hubPriceTierLabelRu(tier) + ' — ' + priceStr));
          inp.addEventListener('change', function() {
            hubBookPriceVariantId = parseInt(inp.value, 10);
          });
          host.appendChild(lab);
        });
        var prefInp = host.querySelector('input[value="' + String(preferredId) + '"]');
        if (prefInp) {
          prefInp.checked = true;
          hubBookPriceVariantId = parseInt(prefInp.value, 10);
        }
      }

      function resetHubBookFormFields() {
        var si = document.getElementById('hubBookClientSearch');
        if (si) si.value = '';
        var p = document.getElementById('hubBookNewPhone');
        var f = document.getElementById('hubBookNewFirstName');
        var l = document.getElementById('hubBookNewLastName');
        if (p) p.value = '';
        if (f) f.value = '';
        if (l) l.value = '';
        var list = document.getElementById('hubBookClientList');
        if (list) list.innerHTML = '';
      }

      function openHubBookModalShell() {
        resetHubBookFormFields();
        resetHubBookSteps();
        var cfm = document.getElementById('hubModalBookGroupConfirm');
        if (cfm) {
          cfm.style.display = 'none';
          cfm.setAttribute('aria-hidden', 'true');
        }
        var m = document.getElementById('hubModalBookGroupSlot');
        if (!m) return false;
        m.style.display = 'flex';
        m.setAttribute('aria-hidden', 'false');
        return true;
      }

      function todayIsoLocal() {
        var d = new Date();
        var m = String(d.getMonth() + 1);
        var day = String(d.getDate());
        if (m.length < 2) m = '0' + m;
        if (day.length < 2) day = '0' + day;
        return String(d.getFullYear()) + '-' + m + '-' + day;
      }

      function parseStartToMinutesHub(startTime) {
        var s = (startTime == null ? '' : String(startTime)).trim();
        var parts = s.split(':');
        var h = parseInt(parts[0], 10);
        var min = parts.length > 1 ? parseInt(parts[1], 10) : 0;
        if (isNaN(h)) h = 0;
        if (isNaN(min)) min = 0;
        return h * 60 + min;
      }

      function formatMinuteClockHub(totalMinutes) {
        var m = Math.max(0, Math.floor(totalMinutes));
        var h = Math.floor(m / 60);
        var rem = m % 60;
        return String(h).padStart(2, '0') + ':' + String(rem).padStart(2, '0');
      }

      function intervalsOverlapAbsoluteHub(a0, a1, b0, b1) {
        return a0 < b1 && b0 < a1;
      }

      function slotIntervalMinutesFromRowHub(s) {
        var sm = parseStartToMinutesHub(s.start_time);
        var em = parseStartToMinutesHub(s.end_time);
        if (em <= sm) em = sm + 60;
        return { start: sm, end: em };
      }

      function hubDefaultScheduleGrid() {
        return {
          kind: 'uniform_step',
          minute_offset: 0,
          hour_start: 8,
          hour_end: 21,
          step_minutes: 15,
        };
      }

      function hubApplyQuickBookScheduleGrid(data) {
        if (data && data.schedule_grid) hubQuickBookScheduleGrid = data.schedule_grid;
        else if (!hubQuickBookScheduleGrid) hubQuickBookScheduleGrid = hubDefaultScheduleGrid();
      }

      function hubAllowedStartMinutesFromGrid() {
        var preset = hubQuickBookScheduleGrid || hubDefaultScheduleGrid();
        var kind = (preset.kind || 'uniform_step').toString().trim();
        var h0 = Math.max(0, Math.min(23, parseInt(preset.hour_start, 10)));
        if (isNaN(h0)) h0 = 8;
        var h1 = Math.max(0, Math.min(23, parseInt(preset.hour_end, 10)));
        if (isNaN(h1)) h1 = 21;
        if (h1 < h0) {
          var swap = h0;
          h0 = h1;
          h1 = swap;
        }
        var out = [];
        if (kind === 'hourly_minute') {
          var mo = Math.max(0, Math.min(59, parseInt(preset.minute_offset, 10) || 0));
          for (var h = h0; h <= h1; h++) out.push(h * 60 + mo);
          return out;
        }
        var step = 15;
        if (kind === 'uniform_step') {
          var s = parseInt(preset.step_minutes, 10);
          if (!isNaN(s) && s >= 5) step = s;
        }
        for (var m = h0 * 60; m <= h1 * 60; m += step) out.push(m);
        return out;
      }

      function setHubQuickBookHint(text, visible) {
        var el = document.getElementById('hubQuickBookHint');
        if (!el) return;
        if (!visible || !text) {
          el.style.display = 'none';
          el.textContent = '';
          return;
        }
        el.style.display = 'block';
        el.textContent = text;
      }

      function hubQuickBookSlotAvailability(slotsForDay, startMinutes, durationMinutes, isoDate) {
        var dm = durationMinutes || 60;
        var newEnd = startMinutes + dm;
        if (newEnd > 24 * 60) return 'invalid';
        var todayStr = todayIsoLocal();
        if (isoDate === todayStr) {
          var now = new Date();
          var nowM = now.getHours() * 60 + now.getMinutes();
          if (startMinutes < nowM) return 'past';
        }
        var rows = (slotsForDay || []).filter(function(s) {
          return (s.status || '').toLowerCase() !== 'cancelled';
        });
        for (var i = 0; i < rows.length; i++) {
          var row = rows[i];
          var iv = slotIntervalMinutesFromRowHub(row);
          if (!intervalsOverlapAbsoluteHub(startMinutes, newEnd, iv.start, iv.end)) continue;
          var cap = row.capacity != null ? parseInt(row.capacity, 10) : 1;
          if (isNaN(cap) || cap < 1) cap = 1;
          var occ = row.active_bookings != null ? parseInt(row.active_bookings, 10) : 0;
          if (cap > 1) return 'group';
          if (iv.start === startMinutes && iv.end === newEnd) {
            if (occ >= 1) return 'busy';
            return 'free';
          }
          if (occ >= 1) return 'busy';
          return 'overlap';
        }
        return 'free';
      }

      function hubRefreshQuickBookTimeOptions(isoDate) {
        var sel = document.getElementById('hubQuickBookTime');
        var durEl = document.getElementById('hubQuickBookDuration');
        var btnGo = document.getElementById('hubQuickBookContinue');
        if (!sel || !isoDate) return Promise.resolve();
        var dm = durEl ? parseInt(durEl.value, 10) : 60;
        if (isNaN(dm) || dm < 15) dm = 60;
        sel.disabled = true;
        if (btnGo) btnGo.disabled = true;
        setHubQuickBookHint('Загрузка сетки расписания…', true);
        return fetch(
          apiUrlWithQuery('/schedule?from_date=' + encodeURIComponent(isoDate) + '&to_date=' + encodeURIComponent(isoDate)),
          { headers: headersJson() }
        )
          .then(function(r) {
            if (!r.ok) return Promise.reject(new Error('schedule'));
            return r.json();
          })
          .then(function(data) {
            hubApplyQuickBookScheduleGrid(data);
            var slots = (data && data.slots) ? data.slots : [];
            hubQuickBookSlotsForDay = slots.filter(function(s) {
              var d = s.slot_date;
              return d === isoDate || String(d) === isoDate;
            });
            var prev = sel.value;
            sel.innerHTML = '';
            var anyFree = false;
            var mins = hubAllowedStartMinutesFromGrid();
            mins.forEach(function(m) {
              var opt = document.createElement('option');
              var availability = hubQuickBookSlotAvailability(hubQuickBookSlotsForDay, m, dm, isoDate);
              opt.value = String(m);
              if (availability === 'free') {
                opt.textContent = formatMinuteClockHub(m);
                anyFree = true;
              } else if (availability === 'past') {
                opt.textContent = formatMinuteClockHub(m) + ' — прошло';
                opt.disabled = true;
              } else if (availability === 'busy') {
                opt.textContent = formatMinuteClockHub(m) + ' — занято';
                opt.disabled = true;
              } else if (availability === 'group') {
                opt.textContent = formatMinuteClockHub(m) + ' — группа';
                opt.disabled = true;
              } else if (availability === 'overlap') {
                opt.textContent = formatMinuteClockHub(m) + ' — пересечение';
                opt.disabled = true;
              } else {
                opt.textContent = formatMinuteClockHub(m) + ' — не влезает';
                opt.disabled = true;
              }
              sel.appendChild(opt);
            });
            var prevOpt = sel.querySelector('option[value="' + prev + '"]:not([disabled])');
            if (prevOpt) sel.value = prev;
            else {
              var firstOk = sel.querySelector('option:not([disabled])');
              if (firstOk) sel.value = firstOk.value;
            }
            sel.disabled = false;
            if (btnGo) btnGo.disabled = !anyFree;
            if (!anyFree) {
              setHubQuickBookHint('Нет доступного времени для выбранной длительности.', true);
            } else {
              setHubQuickBookHint('', false);
            }
          })
          .catch(function() {
            hubApplyQuickBookScheduleGrid(null);
            sel.disabled = false;
            sel.innerHTML = '';
            hubAllowedStartMinutesFromGrid().forEach(function(m) {
              var opt = document.createElement('option');
              opt.value = String(m);
              opt.textContent = formatMinuteClockHub(m);
              sel.appendChild(opt);
            });
            if (btnGo) btnGo.disabled = false;
            setHubQuickBookHint('Не удалось проверить занятость. Время можно выбрать вручную.', true);
          });
      }

      function scheduleHubQuickBookRefresh() {
        if (hubQuickBookRefreshTimer) clearTimeout(hubQuickBookRefreshTimer);
        hubQuickBookRefreshTimer = setTimeout(function() {
          hubQuickBookRefreshTimer = null;
          var dateEl = document.getElementById('hubQuickBookDate');
          var iso = dateEl ? String(dateEl.value || '').trim() : '';
          if (iso) hubRefreshQuickBookTimeOptions(iso);
        }, 250);
      }

      function closeHubQuickBookDatetimeModal() {
        var m = document.getElementById('hubModalQuickBookDatetime');
        if (!m) return;
        m.style.display = 'none';
        m.setAttribute('aria-hidden', 'true');
      }

      function openHubQuickBookDatetimeModal() {
        var modal = document.getElementById('hubModalQuickBookDatetime');
        var dateEl = document.getElementById('hubQuickBookDate');
        var timeEl = document.getElementById('hubQuickBookTime');
        var durEl = document.getElementById('hubQuickBookDuration');
        if (!modal || !dateEl || !timeEl || !durEl) {
          hubToast('Не удалось открыть форму записи. Обновите страницу.');
          return;
        }
        var today = todayIsoLocal();
        dateEl.min = today;
        if (!dateEl.value || dateEl.value < today) dateEl.value = today;
        if (!durEl.value) durEl.value = '60';
        setHubQuickBookHint('', false);
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
        hubRefreshQuickBookTimeOptions(dateEl.value || today);
      }

      function openHubQuickBookClientFlow(slotDate, startTime, durationMinutes) {
        if (!openHubBookModalShell()) return;
        hubBookSlotId = null;
        hubBookPriceVariantId = null;
        hubBookQuickPayload = {
          slot_date: slotDate,
          start_time: startTime,
          duration_minutes: durationMinutes,
        };
        hubBookSlotWhenLabel = slotDate + ' ' + startTime;
        Promise.all([
          fetch(apiUrlWithQuery('/trainer/my-services'), { headers: headersJson() }).then(function(r) {
            return r.ok ? r.json() : Promise.reject(new Error('services'));
          }),
          fetch(apiUrlWithQuery('/trainer/clients'), { headers: headersJson() }).then(function(r) {
            return r.json();
          }),
        ])
          .then(function(results) {
            var servicePayload = results[0] || {};
            var clientsPayload = results[1] || {};
            hubBookQuickServices = servicePayload.services || [];
            if (!hubBookQuickServices.length) {
              closeHubBookGroupModals();
              resetHubBookSlotState();
              hubToast('Добавьте услугу в профиле, чтобы записывать клиентов.');
              return;
            }
            hubBookServiceId = hubBookQuickServices[0].id;
            fillHubBookServiceSelect(hubBookQuickServices);
            setHubBookServiceVisibility(true);
            syncHubBookPriceTierRadios();
            var hasClients = !!(clientsPayload.clients && clientsPayload.clients.length);
            setHubBookOptExistingVisible(hasClients);
          })
          .catch(function() {
            closeHubBookGroupModals();
            resetHubBookSlotState();
            hubToast('Не удалось подготовить форму записи. Повторите попытку.');
          });
      }

      function loadHubBookClients(q) {
        fetch(hubBookClientsUrl(q), { headers: headersJson() })
          .then(function(r) {
            return r.json();
          })
          .then(function(data) {
            var list = document.getElementById('hubBookClientList');
            var clients = data.clients || [];
            if (clients.length === 0) {
              list.innerHTML =
                '<p style="padding:8px 0;font-size:14px;color:var(--tg-theme-hint-color);">Нет клиентов по поиску. Добавьте нового ниже.</p>';
              return;
            }
            var html = '';
            clients.forEach(function(c) {
              var name = ((c.first_name || '') + ' ' + (c.last_name || '')).trim() || 'Клиент';
              var phone = (c.phone || '').trim();
              var noBot = !c.telegram_id;
              html +=
                '<button type="button" class="client-row" data-client-id="' +
                c.id +
                '" data-client-name="' +
                escapeHtml(name).replace(/"/g, '&quot;') +
                '">' +
                escapeHtml(name) +
                (phone ? '<br><span class="phone">' + escapeHtml(phone) + '</span>' : '') +
                (noBot ? '<br><span style="font-size:11px;color:var(--tg-theme-hint-color);">Без бота</span>' : '') +
                '</button>';
            });
            list.innerHTML = html;
            list.querySelectorAll('.client-row').forEach(function(row) {
              row.onclick = function() {
                var clientId = parseInt(row.getAttribute('data-client-id'), 10);
                var clientName = (row.getAttribute('data-client-name') || 'Клиент').replace(/&quot;/g, '"');
                hubBookPendingClientId = clientId;
                hubBookPendingClientName = clientName;
                var txt = document.getElementById('hubBookConfirmText');
                if (txt) {
                  txt.textContent = 'Записать ' + clientName + ' на ' + (hubBookSlotWhenLabel || 'слот') + '?';
                }
                var m = document.getElementById('hubModalBookGroupSlot');
                if (m) {
                  m.style.display = 'none';
                  m.setAttribute('aria-hidden', 'true');
                }
                var cf = document.getElementById('hubModalBookGroupConfirm');
                if (cf) {
                  cf.style.display = 'flex';
                  cf.setAttribute('aria-hidden', 'false');
                }
              };
            });
          })
          .catch(function() {
            document.getElementById('hubBookClientList').innerHTML =
              '<p style="color:#c62828;padding:8px;">Ошибка загрузки</p>';
          });
      }

      function openHubBookGroupSlotModal(slotId, serviceId, whenLabel) {
        var sid = parseInt(String(slotId), 10);
        var svc = serviceId != null ? parseInt(String(serviceId), 10) : NaN;
        if (isNaN(sid) || isNaN(svc)) {
          hubToast('У группового слота не задана услуга. Укажите услугу в расписании.');
          return;
        }
        hubBookSlotId = sid;
        hubBookServiceId = svc;
        hubBookQuickPayload = null;
        hubBookQuickServices = [];
        hubBookSlotWhenLabel = (whenLabel || '').trim();
        setHubBookServiceVisibility(false);
        fillHubBookServiceSelect([]);
        if (!openHubBookModalShell()) return;
        syncHubBookPriceTierRadios();
        fetch(apiUrlWithQuery('/trainer/clients'), { headers: headersJson() })
          .then(function(r) {
            return r.json();
          })
          .then(function(data) {
            var has = !!(data.clients && data.clients.length);
            setHubBookOptExistingVisible(has);
          })
          .catch(function() {
            setHubBookOptExistingVisible(false);
          });
      }

      function hubApiErrorMessage(o) {
        var d = o && o.detail;
        if (typeof d === 'string') return d;
        if (Array.isArray(d) && d[0] && d[0].msg) return d[0].msg;
        return 'Ошибка';
      }

      function hubPostBooking(clientId) {
        var url = '/trainer/booking';
        var payload;
        if (hubBookQuickPayload) {
          if (hubBookServiceId == null) return Promise.reject(new Error('Выберите услугу.'));
          url = '/trainer/booking/quick';
          payload = {
            slot_date: hubBookQuickPayload.slot_date,
            start_time: hubBookQuickPayload.start_time,
            duration_minutes: hubBookQuickPayload.duration_minutes,
            client_id: clientId,
            service_id: hubBookServiceId,
          };
          if (hubBookPriceVariantId != null) {
            payload.service_price_variant_id = hubBookPriceVariantId;
          }
        } else {
          payload = { slot_id: hubBookSlotId, client_id: clientId, service_id: hubBookServiceId };
        }
        return fetch(apiUrlWithQuery(url), {
          method: 'POST',
          headers: headersJson(),
          body: JSON.stringify(payload),
        }).then(function(r) {
          return r.json().then(function(d) {
            if (r.ok) return { ok: true, booking: d };
            throw new Error(hubApiErrorMessage(d));
          });
        });
      }

      function closeHubFirstBookingMilestoneModal() {
        var ov = document.getElementById('hubModalFirstBookingMilestone');
        if (!ov) return;
        ov.style.display = 'none';
        ov.setAttribute('aria-hidden', 'true');
      }

      function openHubFirstBookingMilestoneModal(apiResult) {
        var r = apiResult || {};
        if (!r.first_booking_milestone && !r.share_catalog_tip) return;
        var parts = [];
        if (r.first_booking_milestone) {
          parts.push(
            '<p style="margin:0 0 12px;"><strong>Поздравляем — первая запись подтверждена!</strong></p>' +
              '<p style="margin:0;color:var(--tg-theme-hint-color);">Напоминания и заметки по клиенту — здесь, в Telegram, без отдельной CRM.</p>'
          );
        }
        if (r.share_catalog_tip) {
          parts.push(
            '<p style="margin:16px 0 0;"><strong>Следующий шаг</strong></p>' +
              '<p style="margin:0;color:var(--tg-theme-hint-color);">Поделитесь ссылкой на запись к вам или на каталог: в боте тренера откройте «Пригласить клиента»; если ссылки нет — укажите в профиле город и услугу.</p>'
          );
        }
        var body = document.getElementById('hubFirstBookingMilestoneBody');
        var ov = document.getElementById('hubModalFirstBookingMilestone');
        if (!body || !ov) return;
        body.innerHTML = parts.join('');
        ov.style.display = 'flex';
        ov.setAttribute('aria-hidden', 'false');
      }

      function wireHubBookGroupModal() {
        var milOk = document.getElementById('hubFirstBookingMilestoneOk');
        if (milOk) milOk.onclick = function() { closeHubFirstBookingMilestoneModal(); };
        var milOv = document.getElementById('hubModalFirstBookingMilestone');
        if (milOv) {
          milOv.onclick = function(ev) {
            if (ev.target === milOv) closeHubFirstBookingMilestoneModal();
          };
        }
        var cancel = document.getElementById('hubBookCancel');
        if (cancel) {
          cancel.onclick = function() {
            document.getElementById('hubModalBookGroupSlot').style.display = 'none';
            closeHubBookGroupModals();
            resetHubBookSlotState();
          };
        }
        var selSvc = document.getElementById('hubBookServiceSelect');
        if (selSvc) {
          selSvc.onchange = function() {
            hubBookServiceId = this.value ? parseInt(this.value, 10) : null;
            syncHubBookPriceTierRadios();
          };
        }
        var bo = document.getElementById('hubBookOptExisting');
        if (bo) {
          bo.onclick = function() {
            document.getElementById('hubBookStepChoice').style.display = 'none';
            document.getElementById('hubBookStepExisting').style.display = 'block';
            document.getElementById('hubBookClientList').innerHTML =
              '<p style="text-align:center;padding:16px;color:var(--tg-theme-hint-color);">Загрузка…</p>';
            loadHubBookClients('');
          };
        }
        var bn = document.getElementById('hubBookOptNew');
        if (bn) {
          bn.onclick = function() {
            document.getElementById('hubBookStepChoice').style.display = 'none';
            document.getElementById('hubBookStepNew').style.display = 'block';
          };
        }
        var be = document.getElementById('hubBookBackFromExisting');
        if (be) {
          be.onclick = function() {
            resetHubBookSteps();
          };
        }
        var bwn = document.getElementById('hubBookBackFromNew');
        if (bwn) {
          bwn.onclick = function() {
            resetHubBookSteps();
          };
        }
        var bsearch = document.getElementById('hubBookClientSearch');
        var tmr = null;
        if (bsearch) {
          bsearch.oninput = function() {
            var q = bsearch.value.trim();
            if (tmr) clearTimeout(tmr);
            tmr = setTimeout(function() {
              loadHubBookClients(q);
            }, 300);
          };
        }
        var cno = document.getElementById('hubBookConfirmNo');
        if (cno) {
          cno.onclick = function() {
            document.getElementById('hubModalBookGroupConfirm').style.display = 'none';
            document.getElementById('hubModalBookGroupSlot').style.display = 'flex';
            hubBookPendingClientId = null;
          };
        }
        var cyes = document.getElementById('hubBookConfirmYes');
        if (cyes) {
          cyes.onclick = function() {
            var cid = hubBookPendingClientId;
            if (cid == null) return;
            var successText = hubBookQuickPayload ? 'Запись успешно создана.' : 'Клиент записан в группу.';
            hubPostBooking(cid)
              .then(function(res) {
                closeHubBookGroupModals();
                resetHubBookSlotState();
                hubToast(successText);
                loadBookings();
                loadOnboardingChecklist();
                openHubFirstBookingMilestoneModal(res.booking);
              })
              .catch(function(e) {
                hubToast(e.message || 'Ошибка');
              });
          };
        }
        var sub = document.getElementById('hubBookNewSubmit');
        if (sub) {
          sub.onclick = function() {
            var phoneEl = document.getElementById('hubBookNewPhone');
            var firstEl = document.getElementById('hubBookNewFirstName');
            var lastEl = document.getElementById('hubBookNewLastName');
            var phoneRaw = (phoneEl.value || '').trim();
            var first = (firstEl.value || '').trim() || null;
            var last = (lastEl.value || '').trim() || null;
            if (!/[\d]/.test(phoneRaw)) {
              hubToast('Введите номер телефона (цифры).');
              return;
            }
            var phone = normalizePhoneHub(phoneRaw);
            var err = validatePhoneHubMsg(phone);
            if (err) {
              hubToast(err);
              return;
            }
            first = (first || '').trim();
            if (!first) {
              hubToast('Укажите имя клиента.');
              return;
            }
            sub.disabled = true;
            fetch(apiUrlWithQuery('/trainer/clients'), {
              method: 'POST',
              headers: headersJson(),
              body: JSON.stringify({ phone: phone, first_name: first, last_name: last || '' }),
            })
              .then(function(r) {
                if (!r.ok) return r.json().then(function(o) { throw new Error(hubApiErrorMessage(o)); });
                return r.json();
              })
              .then(function(data) {
                return hubPostBooking(data.client_id);
              })
              .then(function(res) {
                var successText = hubBookQuickPayload
                  ? 'Клиент добавлен и запись успешно создана.'
                  : 'Клиент добавлен и записан на занятие.';
                closeHubBookGroupModals();
                resetHubBookSlotState();
                hubToast(successText);
                loadBookings();
                loadOnboardingChecklist();
                openHubFirstBookingMilestoneModal(res.booking);
              })
              .catch(function(e) {
                hubToast(e.message || 'Ошибка');
              })
              .finally(function() {
                sub.disabled = false;
              });
          };
        }
        var ov = document.getElementById('hubModalBookGroupSlot');
        if (ov) {
          ov.onclick = function(ev) {
            if (ev.target === ov) {
              ov.style.display = 'none';
              closeHubBookGroupModals();
              resetHubBookSlotState();
            }
          };
        }
        var ovc = document.getElementById('hubModalBookGroupConfirm');
        if (ovc) {
          ovc.onclick = function(ev) {
            if (ev.target === ovc) {
              ovc.style.display = 'none';
              document.getElementById('hubModalBookGroupSlot').style.display = 'flex';
            }
          };
        }
        var qCancel = document.getElementById('hubQuickBookCancel');
        if (qCancel) qCancel.onclick = function() { closeHubQuickBookDatetimeModal(); };
        var qContinue = document.getElementById('hubQuickBookContinue');
        if (qContinue) {
          qContinue.onclick = function() {
            var dateEl = document.getElementById('hubQuickBookDate');
            var timeEl = document.getElementById('hubQuickBookTime');
            var durEl = document.getElementById('hubQuickBookDuration');
            if (!dateEl || !timeEl || !durEl) return;
            var slotDate = String(dateEl.value || '').trim();
            var startMinutes = parseInt(String(timeEl.value || ''), 10);
            var duration = parseInt(String(durEl.value || '60'), 10);
            if (!slotDate) {
              hubToast('Выберите дату.');
              return;
            }
            if (isNaN(startMinutes)) {
              hubToast('Выберите время начала.');
              return;
            }
            if (isNaN(duration) || duration < 15) duration = 60;
            var availability = hubQuickBookSlotAvailability(
              hubQuickBookSlotsForDay || [],
              startMinutes,
              duration,
              slotDate
            );
            if (availability !== 'free') {
              if (availability === 'past') hubToast('Это время уже прошло.');
              else if (availability === 'busy') hubToast('Это время занято. Выберите другое.');
              else if (availability === 'group') hubToast('На это время есть групповой слот.');
              else if (availability === 'overlap') hubToast('Время пересекается со слотом.');
              else hubToast('Слот не подходит по длительности.');
              scheduleHubQuickBookRefresh();
              return;
            }
            var startTime = formatMinuteClockHub(startMinutes);
            closeHubQuickBookDatetimeModal();
            openHubQuickBookClientFlow(slotDate, startTime, duration);
          };
        }
        var qDate = document.getElementById('hubQuickBookDate');
        if (qDate) {
          qDate.onchange = function() {
            scheduleHubQuickBookRefresh();
          };
        }
        var qDuration = document.getElementById('hubQuickBookDuration');
        if (qDuration) {
          qDuration.onchange = function() {
            scheduleHubQuickBookRefresh();
          };
        }
        var qOverlay = document.getElementById('hubModalQuickBookDatetime');
        if (qOverlay) {
          qOverlay.onclick = function(ev) {
            if (ev.target === qOverlay) closeHubQuickBookDatetimeModal();
          };
        }
      }

      /**
       * Hub grid order (2 columns): Клиенты → [Группы если включены в профиле и подписке] → Заявки → Расписание → Профиль → остальное.
       * `feature: 'groups'` — tile only when profile.group_classes_enabled && subscription.modules.groups.
       */
      /** Synthetic grid item: placeholder while subscription status loads (same cell size as «Статистика»). */
      var HUB_TILE_SKELETON_ANALYTICS = { _hubTileSkeleton: true, tier: 'analytics' };

      var TILES = [
        { path: 'trainer-clients', label: 'Клиенты', hint: 'База и заметки', icon: 'users', badge: null },
        {
          path: 'trainer-groups',
          label: 'Группы',
          hint: 'Набор и расписание',
          icon: 'groups',
          badge: null,
          feature: 'groups',
        },
        { path: 'trainer-requests', label: 'Заявки', hint: 'Отклики клиентов', icon: 'inbox', badge: 'NEW' },
        { path: 'schedule-editor', label: 'Расписание', hint: 'Слоты и записи', icon: 'cal', badge: null },
        { path: 'trainer-profile', label: 'Профиль', hint: 'Анкета и модерация', icon: 'user', badge: null },
        { path: 'trainer-pass-products', label: 'Абонементы', hint: 'Продукты и выдача', icon: 'ticket', badge: null },
        { path: 'trainer-subscription?v=20260448', label: 'Подписка', hint: 'Тариф и оплата', icon: 'card', badge: null },
        { path: 'trainer-stats', label: 'Статистика', hint: 'Показатели и динамика', icon: 'chart', badge: null, tier: 'analytics' },
        { path: 'trainer-referral', label: 'Рефералы', hint: 'Пригласи коллегу', icon: 'gift', badge: 'NEW' },
      ];

      function tilesToRender() {
        var out = [];
        TILES.forEach(function(t) {
          if (t.feature === 'groups' && (!hubGroupClassesEnabled || !hubGroupsModuleEnabled)) return;
          if (t.tier === 'analytics') {
            if (initData && !hubSubscriptionStatusReady) {
              out.push(HUB_TILE_SKELETON_ANALYTICS);
              return;
            }
            if (!hasAnalyticsAccess) return;
          }
          out.push(t);
        });
        return out;
      }

      function renderTiles() {
        var grid = document.getElementById('hubGrid');
        grid.innerHTML = tilesToRender().map(function(t) {
          if (t._hubTileSkeleton) {
            return (
              '<div class="hub-tile hub-tile--skeleton" role="status" aria-busy="true" aria-label="Загрузка">' +
                '<div class="hub-tile-inner">' +
                  '<div class="hub-tile-top">' +
                    '<div class="hub-skel-line hub-skel-line--icon hub-skel-shimmer" aria-hidden="true"></div>' +
                  '</div>' +
                  '<div class="hub-tile-content">' +
                    '<div class="hub-skel-line hub-skel-line--title hub-skel-shimmer" aria-hidden="true"></div>' +
                    '<div class="hub-skel-line hub-skel-line--hint hub-skel-shimmer" aria-hidden="true"></div>' +
                  '</div>' +
                '</div>' +
              '</div>'
            );
          }
          var ic = ICONS[t.icon] || ICONS.cal;
          var badgeHtml = t.badge ? '<div class="hub-tile-badge">' + escapeHtml(t.badge) + '</div>' : '';
          return (
            '<button type="button" class="hub-tile" data-path="' + escapeHtml(t.path) + '">' +
              '<div class="hub-tile-inner">' +
                '<div class="hub-tile-top">' + ic + badgeHtml + '</div>' +
                '<div class="hub-tile-content">' +
                  '<div class="hub-tile-label">' + escapeHtml(t.label) + '</div>' +
                  '<div class="hub-tile-hint">' + escapeHtml(t.hint) + '</div>' +
                '</div>' +
              '</div>' +
            '</button>'
          );
        }).join('');
        grid.querySelectorAll('.hub-tile:not(.hub-tile--skeleton)').forEach(function(btn) {
          btn.onclick = function() {
            navigateTo(btn.getAttribute('data-path'));
          };
        });
        applyHubLockedState();
      }

      /** Skeleton rows while GET /trainer/bookings is in flight (active trainer). */
      function buildHubBookingsSkeletonHtml() {
        var parts = [
          '<div class="hub-bookings-skel" role="status" aria-busy="true" aria-label="Загрузка записей">',
        ];
        for (var i = 0; i < 3; i++) {
          parts.push(
            '<div class="hub-skel-row">' +
              '<div class="hub-skel-line hub-skel-line--time hub-skel-shimmer" aria-hidden="true"></div>' +
              '<div style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;">' +
                '<div class="hub-skel-line hub-skel-line--primary hub-skel-shimmer" aria-hidden="true"></div>' +
                '<div class="hub-skel-line hub-skel-line--secondary hub-skel-shimmer" aria-hidden="true"></div>' +
              '</div>' +
            '</div>'
          );
        }
        parts.push('</div>');
        return parts.join('');
      }

      /** Cold bootstrap: HTML may be cached without skeleton; keep placeholder until renderBookings / loadBookings. */
      function ensureHubBookingsPlaceholder() {
        if (!initData) return;
        var bb = document.getElementById('bookingsBlock');
        if (!bb || bb.querySelector('.hub-bookings-skel')) return;
        if (bb.querySelector('.slot-row, .bd-trainer-gate, .hub-empty')) return;
        bb.innerHTML = buildHubBookingsSkeletonHtml();
      }

      /**
       * Hub «Ближайшие записи»: API returns one row per participant on group slots — collapse to one card per slot_id
       * (aligned with schedule group rows). If any participant is pending, the merged row is pending.
       */
      function dedupeHubDayBookings(bookings) {
        var seenSlot = Object.create(null);
        var out = [];
        (bookings || []).forEach(function(b) {
          if (!b) return;
          var cap = parseInt(String(b.slot_capacity != null ? b.slot_capacity : '1'), 10);
          if (isNaN(cap) || cap < 1) cap = 1;
          if (cap > 1 && b.slot_id != null && b.slot_id !== '') {
            var sk = String(b.slot_id);
            if (seenSlot[sk]) {
              var prev = seenSlot[sk];
              if (String(b.status || '').toLowerCase() === 'pending') prev.status = 'pending';
              return;
            }
            var row = Object.assign({}, b);
            seenSlot[sk] = row;
            out.push(row);
            return;
          }
          out.push(b);
        });
        return out;
      }

      function dedupeHubBookingsDays(days) {
        return (days || []).map(function(d) {
          return Object.assign({}, d, { bookings: dedupeHubDayBookings(d.bookings || []) });
        });
      }

      function renderBookings(days) {
        var daysForHub = dedupeHubBookingsDays(days || []);
        hubLastBookingsDays = daysForHub;
        var block = document.getElementById('bookingsBlock');
        var todayCount = 0;
        var weekCount = 0;

        var today = new Date();
        var todayStr =
          today.getFullYear() +
          '-' +
          String(today.getMonth() + 1).padStart(2, '0') +
          '-' +
          String(today.getDate()).padStart(2, '0');

        var pending = 0;
        daysForHub.forEach(function(d) {
          var dayBookings = (d.bookings || []).length;
          weekCount += dayBookings;

          if (d.date === todayStr) {
            todayCount = dayBookings;
          }
          (d.bookings || []).forEach(function(b) {
            if (b && b.status === 'pending') pending += 1;
          });
        });
        hubLastPendingCount = pending;

        var firstWhen = '';
        var flatFirst = null;
        daysForHub.some(function(d) {
          var bs = d.bookings || [];
          if (bs.length) {
            flatFirst = { day: d, booking: bs[0] };
            return true;
          }
          return false;
        });

        if (flatFirst) {
          var b0 = flatFirst.booking;
          firstWhen = (b0.start_time || '').slice(0, 5);
        }

        hubLastTodayCount = todayCount;
        hubLastFirstWhen = firstWhen;
        hubLastWeekCount = weekCount;

        var maxN = HUB_UPCOMING_BOOKINGS_MAX;
        var totalBookings = 0;
        daysForHub.forEach(function(day) {
          totalBookings += (day.bookings || []).length;
        });

        var count = 0;
        var parts = [];

        daysForHub.forEach(function(day) {
          if (count >= maxN) return;
          var bs = day.bookings || [];
          if (!bs.length) return;
          parts.push('<div class="hub-day-label">' + escapeHtml(dayHeaderLine(day)) + '</div>');
          parts.push('<div class="hub-bookings-stack">');
          bs.forEach(function(b) {
            if (count >= maxN) return;
            var timeRange = (b.start_time || '') + '–' + (b.end_time || '');
            parts.push(hubBookingSlotRowHtml(b, timeRange));
            count++;
          });
          parts.push('</div>');
        });

        hubLastUpcomingListCount = count;
        syncHubHeroCompact();
        applyHubHero();

        if (!count) {
          block.innerHTML = buildEmptyBookingsHtml();
          block.onclick = null;
          wireEmptyScheduleButton();
          tryOpenHubGroupModalFromUrl();
          return;
        }
        var capHint = '';
        if (totalBookings > maxN) {
          capHint = '<div class="hub-bookings-cap">Показаны ' + maxN + ' ближайших записей из ' + totalBookings + '</div>';
        }
        block.innerHTML = parts.join('') + capHint;
        block.onclick = function(ev) {
          var msgBtn = ev.target && ev.target.closest && ev.target.closest('button.hub-slot-msg[data-hub-dm]');
          if (msgBtn) {
            ev.preventDefault();
            ev.stopPropagation();
            openTelegramDmMiniApp(msgBtn.getAttribute('data-dm-un'), msgBtn.getAttribute('data-dm-tid'));
            return;
          }
          var rowGroup = ev.target && ev.target.closest && ev.target.closest('.slot-row.slot-group-hub-preview[data-slot-id]');
          if (rowGroup) {
            var sid = rowGroup.getAttribute('data-slot-id');
            var sdate = rowGroup.getAttribute('data-slot-date') || '';
            if (sid) {
              ev.preventDefault();
              ev.stopPropagation();
              openHubGroupSlotModal(sid, sdate);
              return;
            }
          }
          var row = ev.target && ev.target.closest && ev.target.closest('.slot-row.slot-booked-click[data-bid]');
          if (!row) return;
          var bid = row.getAttribute('data-bid');
          if (bid) navigateTo('schedule-editor?open_booking=' + encodeURIComponent(bid) + '&from=hub');
        };
        tryOpenHubGroupModalFromUrl();
      }

      /** Upcoming bookings: friendly onboarding instead of red «network» when account not active yet. */
      function renderBookingsOnboardingBlock(access) {
        setStateMessage('', '');
        hubLastBookingsDays = null;
        hubLastTodayCount = 0;
        hubLastFirstWhen = '';
        hubLastWeekCount = 0;
        hubLastUpcomingListCount = 0;
        hubLastPendingCount = 0;
        hubMtdRevenueText = null;
        syncHubHeroCompact();
        applyHubHero();
        var bb = document.getElementById('bookingsBlock');
        if (window.TrainerMiniAppGate && access) {
          bb.innerHTML =
            '<div class="bd-trainer-gate" style="margin-top:4px">' +
            window.TrainerMiniAppGate.gateCardHtml(access, true) +
            '</div>';
          window.TrainerMiniAppGate.wireGate(bb, initData);
        } else {
          bb.innerHTML =
            '<div class="hub-empty">Раздел откроется после активации профиля. Заполните анкету в «Профиль» или дождитесь проверки — это не сбой сети.</div>';
        }
      }

      function buildBookingsRetryBlockHtml(message) {
        return (
          '<div class="hub-empty">' +
          escapeHtml(String(message || 'Не удалось обновить список. Попробуйте снова.')) +
          '<div class="hub-empty-actions">' +
          '<button type="button" class="btn-block btn-secondary" id="hubBookingsRetryBtn">Обновить</button>' +
          '</div>' +
          '</div>'
        );
      }

      function wireBookingsRetryButton() {
        var btn = document.getElementById('hubBookingsRetryBtn');
        if (!btn) return;
        btn.onclick = function() {
          if (btn.disabled) return;
          btn.disabled = true;
          btn.textContent = 'Обновляем...';
          loadBookings();
        };
      }

      function loadBookings() {
        if (!initData) {
          setStateMessage('', '');
          hubLastBookingsDays = null;
          hubLastTodayCount = 0;
          hubLastFirstWhen = '';
          hubLastWeekCount = 0;
          hubLastUpcomingListCount = 0;
          hubLastPendingCount = 0;
          hubMtdRevenueText = null;
          syncHubHeroCompact();
          applyHubHero();
          document.getElementById('bookingsBlock').innerHTML =
            '<div class="hub-empty">Авторизация Telegram недоступна в этом режиме.</div>';
          return;
        }
        if (
          trainerAccessSnapshot &&
          window.TrainerMiniAppGate &&
          !window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)
        ) {
          renderBookingsOnboardingBlock(trainerAccessSnapshot);
          return;
        }
        setStateMessage('', '');
        document.getElementById('bookingsBlock').innerHTML = buildHubBookingsSkeletonHtml();
        fetchHubMtdRevenue();
        if (typeof AbortController !== 'undefined') {
          if (hubBookingsAbort) {
            try {
              hubBookingsAbort.abort();
            } catch (eAbort) {}
          }
          hubBookingsAbort = new AbortController();
        }
        var bookingsFetchOpts = { headers: headersJson() };
        if (hubBookingsAbort) bookingsFetchOpts.signal = hubBookingsAbort.signal;
        fetch(
          apiUrlWithQuery('/trainer/bookings?limit=' + encodeURIComponent(String(HUB_BOOKINGS_FETCH_LIMIT))),
          bookingsFetchOpts
        )
          .then(function(r) {
            return r.json().then(function(data) {
              return { status: r.status, ok: r.ok, data: data };
            });
          })
          .then(function(o) {
            /* 401/403: API requires active trainer — same as onboarding, never blame «network». */
            if (o.status === 401 || o.status === 403) {
              setStateMessage('', '');
              if (window.TrainerMiniAppGate && initData) {
                return window.TrainerMiniAppGate.fetchAccess(initData)
                  .then(function(a) {
                    trainerAccessSnapshot = a;
                    applyHubLockedState();
                    renderBookingsOnboardingBlock(a);
                  })
                  .catch(function() {
                    renderBookingsOnboardingBlock(trainerAccessSnapshot || null);
                  });
              }
              renderBookingsOnboardingBlock(trainerAccessSnapshot || null);
              return;
            }
            if (!o.ok) {
              setStateMessage('', '');
              hubLastBookingsDays = null;
              hubLastTodayCount = 0;
              hubLastFirstWhen = '';
              hubLastWeekCount = 0;
              hubLastUpcomingListCount = 0;
              hubLastPendingCount = 0;
              hubMtdRevenueText = null;
              syncHubHeroCompact();
              applyHubHero();
              document.getElementById('bookingsBlock').innerHTML = buildBookingsRetryBlockHtml(
                'Не удалось обновить список. Проверьте соединение и попробуйте снова.'
              );
              wireBookingsRetryButton();
              return;
            }
            setStateMessage('');
            renderBookings((o.data && o.data.days) || []);
          })
          .catch(function(err) {
            if (err && err.name === 'AbortError') return;
            setStateMessage('', '');
            /* Offline / timeout: if account likely not active, avoid scary copy */
            if (window.TrainerMiniAppGate && initData) {
              window.TrainerMiniAppGate.fetchAccess(initData)
                .then(function(a) {
                  trainerAccessSnapshot = a;
                  applyHubLockedState();
                  if (!window.TrainerMiniAppGate.isActive(a)) {
                    renderBookingsOnboardingBlock(a);
                  } else {
                    hubLastBookingsDays = null;
                    hubLastTodayCount = 0;
                    hubLastFirstWhen = '';
                    hubLastWeekCount = 0;
                    hubLastUpcomingListCount = 0;
                    hubLastPendingCount = 0;
                    hubMtdRevenueText = null;
                    syncHubHeroCompact();
                    applyHubHero();
                    document.getElementById('bookingsBlock').innerHTML = buildBookingsRetryBlockHtml(
                      'Не удалось обновить список. Проверьте соединение и попробуйте снова.'
                    );
                    wireBookingsRetryButton();
                  }
                })
                .catch(function() {
                  hubLastBookingsDays = null;
                  hubLastTodayCount = 0;
                  hubLastFirstWhen = '';
                  hubLastWeekCount = 0;
                  hubLastUpcomingListCount = 0;
                  hubLastPendingCount = 0;
                  hubMtdRevenueText = null;
                  syncHubHeroCompact();
                  applyHubHero();
                  document.getElementById('bookingsBlock').innerHTML = buildBookingsRetryBlockHtml(
                    'Не удалось обновить список. Проверьте соединение и попробуйте снова.'
                  );
                  wireBookingsRetryButton();
                });
            } else {
              hubLastBookingsDays = null;
              hubLastTodayCount = 0;
              hubLastFirstWhen = '';
              hubLastWeekCount = 0;
              hubLastUpcomingListCount = 0;
              hubLastPendingCount = 0;
              hubMtdRevenueText = null;
              syncHubHeroCompact();
              applyHubHero();
              document.getElementById('bookingsBlock').innerHTML = buildBookingsRetryBlockHtml(
                'Не удалось обновить список. Проверьте соединение и попробуйте снова.'
              );
              wireBookingsRetryButton();
            }
          });
      }

      // Quick Actions handlers
      function setupQuickActions() {
        var btnSched = document.getElementById('hubBtnSchedule');
        if (btnSched) {
          btnSched.onclick = function() {
            navigateTo('schedule-editor');
          };
        }
        var btnBook = document.getElementById('hubBtnBookClient');
        if (btnBook) {
          btnBook.onclick = function() {
            ensureTrainerSectionsAccess(function() {
              openHubQuickBookDatetimeModal();
            });
          };
        }

        applyHubLockedState();
      }

      function loadSubscriptionStatus() {
        if (!initData) {
          hubSubscriptionStatusReady = true;
          hasAnalyticsAccess = false;
          renderTiles();
          setupQuickActions();
          return Promise.resolve();
        }
        return fetch(apiUrlWithQuery('/trainer/subscription/status'), { headers: headersJson() })
          .then(function(r) {
            return r.json().then(function(data) {
              return { ok: r.ok, data: data };
            });
          })
          .then(function(o) {
            hubLastSubscriptionStatus = o.ok && o.data ? o.data : null;
            syncHubGroupsModuleAccessFromSubscription(hubLastSubscriptionStatus);
            if (o.ok && o.data && Array.isArray(o.data.unlocked_features)) {
              hasAnalyticsAccess = o.data.unlocked_features.indexOf('analytics') !== -1;
            } else {
              hasAnalyticsAccess = false;
            }
            hubSubscriptionStatusReady = true;
            renderTiles();
            setupQuickActions();
          })
          .catch(function() {
            hubLastSubscriptionStatus = null;
            hubGroupsModuleEnabled = false;
            hasAnalyticsAccess = false;
            hubSubscriptionStatusReady = true;
            renderTiles();
            setupQuickActions();
          });
      }

      function hideHubSubscriptionCelebration() {
        var sec = document.getElementById('hubSubscriptionCelebration');
        if (!sec) return;
        sec.setAttribute('hidden', 'hidden');
      }

      function stripHubCelebrateQueryParam() {
        try {
          var params = new URLSearchParams(window.location.search || '');
          if (params.get('hub_celebrate') !== '1') return;
          params.delete('hub_celebrate');
          var ns = params.toString();
          var clean = window.location.pathname + (ns ? '?' + ns : '') + (window.location.hash || '');
          window.history.replaceState({}, '', clean);
        } catch (e) { /* */ }
      }

      /** After booking detail «Назад»: reopen group modal via ?reopen_group_slot= (strip from URL once). */
      function tryOpenHubGroupModalFromUrl() {
        try {
          var params = new URLSearchParams(window.location.search || '');
          var rg = params.get('reopen_group_slot');
          if (!rg) return;
          params.delete('reopen_group_slot');
          var ns = params.toString();
          var clean = window.location.pathname + (ns ? '?' + ns : '') + (window.location.hash || '');
          window.history.replaceState({}, '', clean);
          var sid = parseInt(String(rg), 10);
          if (isNaN(sid) || sid <= 0) {
            releaseHubReopenGroupCover();
            return;
          }
          openHubGroupSlotModal(String(sid), '');
        } catch (e) {
          releaseHubReopenGroupCover();
        }
      }

      /** Same mapping as mini-app-trainer-celebration.js if that script failed to load. */
      function hubCelebrationFeaturesFromUnlocked(unlocked) {
        if (window.TrainerHubCelebration && typeof window.TrainerHubCelebration.featuresFromUnlockedList === 'function') {
          return window.TrainerHubCelebration.featuresFromUnlockedList(unlocked || []);
        }
        var META = {
          crm: { id: 'crm', label: 'CRM и клиентская база', icon: '📋' },
          online: { id: 'online', label: 'Онлайн-запись клиентов', icon: '🌐' },
          analytics: { id: 'analytics', label: 'Аналитика и отчёты', icon: '📊' },
        };
        var order = ['crm', 'online', 'analytics'];
        var out = [];
        var u = unlocked || [];
        order.forEach(function(id) {
          if (u.indexOf(id) === -1) return;
          if (META[id]) out.push(META[id]);
        });
        return out;
      }

      /** Fallback when sessionStorage was empty but user arrived from subscription success (?hub_celebrate=1). */
      function buildCelebrationPayloadFromStatus(s) {
        if (!s || !s.is_active) return null;
        var expiresAt = s.expires_at ? String(s.expires_at).slice(0, 10) : '';
        var pm = s.billing_period_months;
        var periodLabel = null;
        if (pm === 1) periodLabel = '1 мес.';
        else if (pm === 3) periodLabel = '3 мес.';
        else if (pm === 12) periodLabel = '1 год';
        else if (pm) periodLabel = pm + ' мес.';
        var features = hubCelebrationFeaturesFromUnlocked(s.unlocked_features || []);
        return {
          v: 1,
          headline: 'Подписка активирована',
          planName: (s.tier_name_ru || s.tier || 'Подписка').toString(),
          expiresAt: expiresAt,
          periodLabel: periodLabel,
          priceLine: null,
          features: features,
          source: 'hub_status_fallback',
        };
      }

      function showHubSubscriptionCelebrationIfPending() {
        var params = new URLSearchParams(window.location.search || '');
        var urlHint = params.get('hub_celebrate') === '1';

        var payload = null;
        if (window.TrainerHubCelebration && typeof window.TrainerHubCelebration.take === 'function') {
          payload = window.TrainerHubCelebration.take();
        }
        if (!payload && urlHint && hubLastSubscriptionStatus) {
          payload = buildCelebrationPayloadFromStatus(hubLastSubscriptionStatus);
        }
        if (urlHint) {
          stripHubCelebrateQueryParam();
        }
        if (!payload) return;
        var sec = document.getElementById('hubSubscriptionCelebration');
        var hEl = document.getElementById('hubSubCelebrationHeadline');
        var subEl = document.getElementById('hubSubCelebrationSub');
        var chipsEl = document.getElementById('hubSubCelebrationChips');
        var ul = document.getElementById('hubSubCelebrationFeatures');
        if (!sec || !hEl || !subEl || !chipsEl || !ul) return;

        function formatDateRu(iso) {
          if (!iso || String(iso).length < 10) return String(iso || '');
          var p = String(iso).slice(0, 10).split('-');
          if (p.length !== 3) return String(iso);
          return p[2] + '.' + p[1] + '.' + p[0];
        }

        hEl.textContent = payload.headline || 'Подписка активирована';
        var plan = String(payload.planName || '').trim();
        subEl.textContent = plan
          ? 'Тариф «' + plan + '» уже подключён — всё из списка ниже доступно вам в этом кабинете.'
          : 'Ваш тариф уже подключён — возможности ниже доступны в этом кабинете.';

        chipsEl.innerHTML = '';
        function addChip(label, accent) {
          var span = document.createElement('span');
          span.className = 'hub-sub-celebration__chip' + (accent ? ' hub-sub-celebration__chip--accent' : '');
          span.textContent = label;
          chipsEl.appendChild(span);
        }
        if (payload.expiresAt) {
          addChip('До ' + formatDateRu(payload.expiresAt), true);
        }
        if (payload.periodLabel) {
          addChip(String(payload.periodLabel), false);
        }
        if (payload.priceLine) {
          addChip(String(payload.priceLine), false);
        }

        ul.innerHTML = '';
        var feats = payload.features || [];
        feats.forEach(function(f) {
          var li = document.createElement('li');
          li.className = 'hub-sub-celebration__feature';
          var ic = document.createElement('span');
          ic.className = 'hub-sub-celebration__feature-icon';
          ic.setAttribute('aria-hidden', 'true');
          ic.textContent = f.icon || '✓';
          var tx = document.createElement('span');
          tx.textContent = f.label || f.id || '';
          li.appendChild(ic);
          li.appendChild(tx);
          ul.appendChild(li);
        });

        sec.removeAttribute('hidden');
        try {
          if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.notificationOccurred === 'function') {
            tg.HapticFeedback.notificationOccurred('success');
          }
        } catch (eH) {}

        try {
          sec.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } catch (eS) {}
      }

      function wireHubSubscriptionCelebrationClose() {
        var btn = document.getElementById('hubSubCelebrationClose');
        if (btn) btn.onclick = hideHubSubscriptionCelebration;
      }
      wireHubSubscriptionCelebrationClose();

      wireOnboardingHub();

      /** Maps GET /trainer/hub/bootstrap payload into hub globals (single round-trip). */
      function applyHubBootstrapPayload(payload) {
        if (!payload || typeof payload !== 'object') return;
        if (payload.access) trainerAccessSnapshot = payload.access;
        if (payload.profile) mergeHubAccessFromProfilePayload({ ok: true, data: payload.profile });
        if (payload.onboarding_checklist) applyOnboardingChecklist(payload.onboarding_checklist);
        if (payload.subscription_status) {
          hubLastSubscriptionStatus = payload.subscription_status;
          syncHubGroupsModuleAccessFromSubscription(payload.subscription_status);
          if (Array.isArray(payload.subscription_status.unlocked_features)) {
            hasAnalyticsAccess = payload.subscription_status.unlocked_features.indexOf('analytics') !== -1;
          } else {
            hasAnalyticsAccess = false;
          }
          hubSubscriptionStatusReady = true;
        }
        if (payload.requests_summary && typeof payload.requests_summary.unanswered_count === 'number') {
          hubRequestsStatReady = true;
          hubLastNewRequestsCount = payload.requests_summary.unanswered_count;
        }
        if (payload.revenue_mtd && payload.revenue_mtd.revenue_total_cents != null) {
          hubMtdRevenueText = formatHubMoneyCents(payload.revenue_mtd.revenue_total_cents);
          var revCard = document.getElementById('statRevenue');
          if (revCard && payload.revenue_mtd.period_start && payload.revenue_mtd.period_end) {
            revCard.setAttribute(
              'title',
              'Начислено с ' +
                String(payload.revenue_mtd.period_start) +
                ' по ' +
                String(payload.revenue_mtd.period_end) +
                ': занятия, абонементы, сертификаты'
            );
          }
          hubRevenueSkipFetchOnce = true;
        }
      }

      /**
       * @param { { bootstrapPayload?: object } } [opts]
       *   When bootstrapPayload is set, skips redundant GETs for sections present in the payload.
       */
      function runHubAfterAccess(opts) {
        opts = opts || {};
        var bs = opts.bootstrapPayload;
        if (initData) {
          if (!bs || !bs.subscription_status) {
            hubSubscriptionStatusReady = false;
          }
          renderTiles();
          setupQuickActions();
        }
        if (bs && bs.subscription_status) {
          showHubSubscriptionCelebrationIfPending();
        } else {
          loadSubscriptionStatus().then(function() {
            showHubSubscriptionCelebrationIfPending();
          });
        }
        if (!initData) {
          loadBookings();
          loadHubRequestsSummary();
          loadOnboardingChecklist();
          return;
        }
        if (
          trainerAccessSnapshot &&
          window.TrainerMiniAppGate &&
          !window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)
        ) {
          renderBookingsOnboardingBlock(trainerAccessSnapshot);
          if (!bs || !bs.requests_summary) loadHubRequestsSummary();
          else renderHubSummaryHints();
          if (!bs || !bs.onboarding_checklist) loadOnboardingChecklist();
          return;
        }
        if (bs && bs.bookings && bs.bookings.days) {
          setStateMessage('');
          renderBookings(bs.bookings.days);
        } else {
          loadBookings();
        }
        if (!bs || !bs.requests_summary) {
          loadHubRequestsSummary();
        } else {
          renderHubSummaryHints();
        }
        if (!bs || !bs.onboarding_checklist) {
          loadOnboardingChecklist();
        }
      }

      if (!initData) {
        runHubAfterAccess({});
      } else {
        ensureHubBookingsPlaceholder();
        fetch(
          apiUrlWithQuery(
            '/trainer/hub/bootstrap?bookings_limit=' + encodeURIComponent(String(HUB_BOOKINGS_FETCH_LIMIT))
          ),
          { headers: headersJson(), cache: 'no-store' }
        )
          .then(function(r) {
            if (!r.ok) throw new Error('bootstrap');
            return r.json();
          })
          .then(function(data) {
            applyHubBootstrapPayload(data);
            runHubAfterAccess({ bootstrapPayload: data });
          })
          .catch(function() {
            if (!window.TrainerMiniAppGate) {
              fetchTrainerProfileForHub().then(function(prof) {
                mergeHubAccessFromProfilePayload(prof);
                runHubAfterAccess({});
              });
            } else {
              Promise.all([
                window.TrainerMiniAppGate.fetchAccess(initData).catch(function() {
                  return null;
                }),
                fetchTrainerProfileForHub(),
              ]).then(function(results) {
                var a = results[0];
                var prof = results[1];
                trainerAccessSnapshot = a;
                mergeHubAccessFromProfilePayload(prof);
                runHubAfterAccess({});
              });
            }
          });
      }

      (function wireHubGroupModal() {
        var closeBtn = document.getElementById('hubGroupSlotCloseBtn');
        var overlay = document.getElementById('hubModalGroupSlot');
        if (closeBtn) closeBtn.onclick = closeHubGroupSlotModal;
        if (overlay) {
          overlay.onclick = function(ev) {
            if (ev.target === overlay) closeHubGroupSlotModal();
          };
        }
      })();
      wireHubBookGroupModal();
    })();
