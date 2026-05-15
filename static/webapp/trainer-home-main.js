    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        /* tg.ready() + expand() are called earlier (inline after splash HTML)
           to eliminate the Telegram robot loading flash. Guard against double-call. */
        if (!window.__tgReadyCalled) {
          if (typeof tg.ready  === 'function') tg.ready();
          if (typeof tg.expand === 'function') tg.expand();
        }
        if (typeof window.__applyTrainerHomeTheme === 'function') window.__applyTrainerHomeTheme();
        try {
          var darkUi = document.documentElement.classList.contains('hub-is-dark');
          var bgHex = darkUi ? '#1c1c1c' : '#fffbec';
          if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
          if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
        } catch (e) {}
      }

      /**
       * Production often caches an old mini-app-telegram-chrome.js without openTelegramChatFromMiniApp /
       * wireHubSlotMessageButtons — «Написать» would do nothing (no server logs). Polyfill from the
       * main bundle so new ?v= on trainer-home-main.js alone fixes the hub.
       */
      (function ensureTrainerTelegramDmHelpers() {
        if (typeof window.openTelegramChatFromMiniApp !== 'function') {
          window.openTelegramChatFromMiniApp = function (opts) {
            opts = opts || {};
            var un = String(opts.username || '').replace(/^@/, '').trim();
            var tid = opts.telegramId;
            var url;
            if (un) url = 'https://t.me/' + encodeURIComponent(un);
            else if (tid != null && tid !== '') url = 'tg://user?id=' + encodeURIComponent(String(tid));
            else return false;
            var w = window.Telegram && window.Telegram.WebApp;
            var isTgUser = url.indexOf('tg://') === 0;
            var isTme = url.indexOf('https://t.me/') === 0;
            if (isTgUser) {
              if (w && w.platform === 'web') {
                if (typeof w.showAlert === 'function') {
                  try {
                    w.showAlert(
                      'В браузерной версии Telegram нельзя открыть чат только по внутреннему ID. Обновите «Ближайшие записи» — подтянется @username, или откройте тот же мини-апп в приложении Telegram на телефоне.'
                    );
                  } catch (e0) { /* noop */ }
                }
                return false;
              }
              try {
                window.location.assign(url);
              } catch (e1) { /* noop */ }
              return true;
            }
            if (isTme && w) {
              if (typeof w.openTelegramLink === 'function') {
                try {
                  w.openTelegramLink(url);
                  return true;
                } catch (e) { /* continue */ }
              }
              if (typeof w.openLink === 'function') {
                try {
                  w.openLink(url, { try_instant_view: false });
                  return true;
                } catch (e2) {
                  try {
                    w.openLink(url);
                    return true;
                  } catch (e3) { /* continue */ }
                }
              }
            }
            try {
              var a = document.createElement('a');
              a.href = url;
              a.rel = 'noopener noreferrer';
              a.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;pointer-events:auto;';
              a.target = '_blank';
              (document.body || document.documentElement).appendChild(a);
              a.click();
              setTimeout(function () {
                try {
                  if (a && a.parentNode) a.parentNode.removeChild(a);
                } catch (x) { /* noop */ }
              }, 0);
            } catch (e4) { /* noop */ }
            try {
              window.location.href = url;
            } catch (e5) { /* noop */ }
            return true;
          };
        }
        if (typeof window.wireHubSlotMessageButtons !== 'function') {
          window.wireHubSlotMessageButtons = function (root) {
            if (!root || !root.querySelectorAll) return;
            root.querySelectorAll('button.hub-slot-msg').forEach(function (btn) {
              btn.addEventListener(
                'click',
                function (ev) {
                  ev.preventDefault();
                  ev.stopPropagation();
                  var UiRg = window.TrainerClientRelayUi;
                  var wf = window.TRAINER_WEBAPP_FORCE_CLIENT_CHAT_RELAY;
                  var hubWF = window.TRAINER_HUB_FORCE_CLIENT_CHAT_RELAY;
                  var relayForceGlobal =
                    wf === true ||
                    wf === 1 ||
                    wf === '1' ||
                    hubWF === true ||
                    hubWF === 1 ||
                    hubWF === '1';
                  var hubWantsRelay =
                    UiRg && typeof UiRg.hubBookingButtonWantsRelay === 'function'
                      ? UiRg.hubBookingButtonWantsRelay(btn)
                      : btn.getAttribute('data-hub-relay') === '1' || relayForceGlobal;
                  if (hubWantsRelay) {
                    var UiRf = window.TrainerClientRelayUi;
                    var openedRf =
                      UiRf &&
                      typeof UiRf.openRelayFromBookingButton === 'function' &&
                      UiRf.openRelayFromBookingButton(btn);
                    if (!openedRf) {
                      var H = window.TrainerRelayHelpers;
                      openedRf =
                        H && typeof H.openRelayFromHubButton === 'function' && H.openRelayFromHubButton(btn);
                    }
                    if (openedRf) {
                      return;
                    }
                    var wg = window.Telegram && window.Telegram.WebApp;
                    if (wg && typeof wg.showAlert === 'function') {
                      try {
                        wg.showAlert(
                          'Не удалось открыть переписку через бота. Обновите страницу или откройте мини-приложение снова.'
                        );
                      } catch (eRelayPf) {
                        /* noop */
                      }
                    }
                    return;
                  }
                  if (typeof window.openTelegramChatFromMiniApp === 'function') {
                    window.openTelegramChatFromMiniApp({
                      username: btn.getAttribute('data-dm-un'),
                      telegramId: btn.getAttribute('data-dm-tid'),
                    });
                  }
                },
                true
              );
            });
          };
        }
      })();

      /**
       * Never cache initData at parse time — some Telegram WebViews fill it after the first tick.
       * Fall back to URL (in-app navigation may preserve init_data as query).
       */
      function initDataFromUrl() {
        try {
          var qs = new URLSearchParams(window.location.search || '');
          return qs.get('init_data') || qs.get('initData') || '';
        } catch (e) {
          return '';
        }
      }
      function getInitData() {
        var t = window.Telegram && window.Telegram.WebApp;
        var raw = (t && t.initData) || initDataFromUrl();
        return raw ? String(raw) : '';
      }
      /**
       * Reply keyboard / some WebViews fill initData a tick after the first script run. Without this,
       * the first quick-book API calls go unauthenticated and fail — user sees «Не удалось подготовить
       * форму…», the second try works. Mirrors waitForInitThen in trainer-groups-main.js.
       */
      function waitForTrainerInitDataThen(callback) {
        try {
          var tg0 = window.Telegram && window.Telegram.WebApp;
          if (tg0 && typeof tg0.ready === 'function') tg0.ready();
        } catch (eReady) {}
        if (getInitData()) {
          callback();
          return;
        }
        requestAnimationFrame(function() {
          if (getInitData()) {
            callback();
            return;
          }
          requestAnimationFrame(function() {
            if (getInitData()) {
              callback();
              return;
            }
            var n = 0;
            var maxTicks = 140;
            var iv = setInterval(function() {
              n++;
              if (getInitData()) {
                clearInterval(iv);
                callback();
                return;
              }
              if (n >= maxTicks) {
                clearInterval(iv);
                /* One extra beat: cold WebView sometimes delivers initData right after idle. */
                setTimeout(function() {
                  callback();
                }, 420);
              }
            }, 50);
          });
        });
      }
      /** Set after GET /trainer/access when initData present (onboarding vs active). */
      var trainerAccessSnapshot = null;
      var hubForceClientChatRelay = false;

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
      /** Last lifecycle payload (stage + signals_recap) from bootstrap or GET /trainer/lifecycle. */
      var hubLastLifecycle = null;

      /** When opening fill-slots from client-cancel deep link: target slot + exclude former booker. */
      var hubFillSlotsInviteContext = { slotId: null, excludeClientId: null };
      /** Last GET /trainer/onboarding/checklist payload — drives hero + empty list copy (avoid slots CTA before profile/active). */
      var hubOnboardingData = null;
      /** Last bookings payload from /trainer/bookings — used to refresh empty-state HTML after onboarding loads. */
      var hubLastBookingsDays = null;
      var hubLastTodayCount = 0;
      /** Today's sessions not yet started (Europe/Minsk); excludes current slot — aligned with backend ``today_sessions.remaining``. */
      var hubLastTodayRemaining = 0;
      var hubLastFirstWhen = '';
      /** For hero/fallback only: row count in truncated hub list (may be < full week). */
      var hubLastWeekCount = 0;
      /** Calendar week (Mon–Sun, Minsk): not-yet-started slots — API ``week_sessions.remaining``. */
      var hubLastWeekRemaining = 0;
      var hubLastUpcomingListCount = 0;
      /** Bookings with status pending — drives summary hint + week card highlight. */
      var hubLastPendingCount = 0;
      /** Pending только среди первых HUB_UPCOMING_BOOKINGS_MAX карточек «Ближайшие» — как на экране. */
      var hubLastPendingInNearestStripCount = 0;
      /** Formatted revenue for hub «С 1-го числа» (MTD API), or null. */
      var hubMtdRevenueText = null;
      /** Client requests without trainer response (GET /trainer/requests/summary). */
      var hubLastNewRequestsCount = 0;
      var hubRequestsStatReady = false;
      /** From trainer profile — group classes switch in trainer form. */
      var hubGroupClassesEnabled = false;
      /** From subscription status — groups module gate (must be enabled in paid modules). */
      var hubGroupsModuleEnabled = false;
      /** From subscription status — controls public booking link feature on hub header. */
      var hubOnlineBookingEnabled = false;
      /** False until first GET /trainer/subscription/status completes (initData only) — drives Stats placeholder tile. */
      var hubSubscriptionStatusReady = false;
      /** When hub bootstrap included MTD revenue, skip duplicate GET /trainer/hub/revenue-mtd in loadBookings. */
      var hubRevenueSkipFetchOnce = false;
      /** Non-blocking success toast after booking (inline strip, not tg.showAlert). */
      var hubInlineToastTimer = null;
      var hubInlineToastActionHandler = null;
      /** One-shot visual highlight for freshly created booking in «Ближайшие записи». */
      var hubPendingHighlightBookingId = null;
      /** When false, the hubSummaryHints strip is not shown (applyHubRhythmResolver still runs). */
      var HUB_NEXT_BEST_HINT_UI_ENABLED = false;
      /** Rhythm hints shown in hubRhythmSlot0/1 — used to avoid duplicating the same message in hubSummaryHints when enabled. */
      var hubActiveRhythmHintIds = [];
      /** Last picked candidates per slot (CTA wiring). */
      var hubLastRhythmPicked = [null, null];
      /** «Мало записей» vs свободные слоты (aligned with product). */
      var HUB_RHYTHM_BOOKINGS_LOW_THRESHOLD = 6;
      /** × dismiss: короткий / длинный mute для rhythm hints. */
      var HUB_RHYTHM_DISMISS_DAYS_SHORT = 1;
      var HUB_RHYTHM_DISMISS_DAYS_LONG = 2;
      /** schedule-editor ставит метку после создания слотов — поднимаем приоритет хинта «Напомнить» (рассылка приглашений). */
      var HUB_FILL_SLOTS_RHYTHM_BOOST_KEY = 'trainer_hub_fill_slots_rhythm_boost_v1';
      var HUB_FILL_SLOTS_RHYTHM_BOOST_TTL_MS = 72 * 60 * 60 * 1000;
      var HUB_RHYTHM_FILL_SLOTS_NOTIFY_PRIORITY_BOOST = 130;
      /** Set at start of applyHubRhythmResolver — read by buildHubRhythmCandidates in same pass. */
      var hubFillSlotsRhythmBoostActiveThisResolverPass = false;
      /**
       * After onboarding checklist is applied (bootstrap or GET) or fetch failed — rhythm resolver may hide skeleton.
       * Stays false until then so two placeholder cards reserve space and reduce CLS.
       */
      var hubRhythmHintsReady = false;

      function showHubRhythmHintsSkeleton() {
        if (!getInitData() || hubRhythmHintsReady) return;
        var sk = document.getElementById('hubRhythmHintsSkeleton');
        if (!sk) return;
        sk.removeAttribute('hidden');
        sk.style.display = 'flex';
        sk.setAttribute('aria-busy', 'true');
      }

      function hideHubRhythmHintsSkeleton() {
        var sk = document.getElementById('hubRhythmHintsSkeleton');
        if (!sk) return;
        sk.setAttribute('hidden', 'hidden');
        sk.style.display = 'none';
        sk.setAttribute('aria-busy', 'false');
      }

      function syncHubHeroCompact() {
        var el = document.querySelector('.hub-hero');
        if (!el) return;
        el.classList.toggle('hub-hero--compact', hubLastUpcomingListCount > 0);
      }

      function headersJson() {
        var h = { 'Content-Type': 'application/json' };
        var raw = getInitData();
        if (raw) h['X-Telegram-Init-Data'] = raw;
        return h;
      }
      function withInit(url) {
        var raw = getInitData();
        if (!raw) return url;
        return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(raw);
      }
      function apiUrlWithQuery(path) {
        var url = '/api/webapp' + path;
        var raw = getInitData();
        if (raw) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(raw);
        return url;
      }

      /** GET with AbortSignal timeout — Telegram WebView sometimes leaves fetch hanging without failing. */
      var HUB_QB_FETCH_TIMEOUT_MS = 22000;
      function hubFetchJsonForQuickBookPrepare(path) {
        var ctrl = new AbortController();
        var tid = setTimeout(function() {
          ctrl.abort();
        }, HUB_QB_FETCH_TIMEOUT_MS);
        return fetch(apiUrlWithQuery(path), {
          headers: headersJson(),
          cache: 'no-store',
          signal: ctrl.signal,
        }).finally(function() {
          clearTimeout(tid);
        });
      }

      /** Same aggregate as «Профиль»: if шапка shows «Одобрено», hub must not stay in onboarding lock. */
      function fetchTrainerProfileForHub() {
        if (!getInitData()) return Promise.resolve({ ok: false, data: null });
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

      function syncHubOnlineBookingAccessFromSubscription(status) {
        if (!status || typeof status !== 'object') {
          hubOnlineBookingEnabled = false;
          return;
        }
        if (status.modules && typeof status.modules === 'object') {
          hubOnlineBookingEnabled = !!status.modules.online;
          return;
        }
        if (Array.isArray(status.unlocked_features)) {
          hubOnlineBookingEnabled = status.unlocked_features.indexOf('online') !== -1;
          return;
        }
        hubOnlineBookingEnabled = false;
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
        if (!getInitData()) return false;
        /* Checklist / snapshot first: same API answers user sees in Network; do NOT require TrainerMiniAppGate. */
        if (hubDataSaysTrainerActive(hubOnboardingData)) return true;
        if (hubDataSaysTrainerActive(trainerAccessSnapshot)) return true;
        if (!window.TrainerMiniAppGate) return false;
        if (!trainerAccessSnapshot) return false;
        return TrainerMiniAppGate.isActive(trainerAccessSnapshot);
      }

      function showTrainerOnboardingNavAlert() {
        var snap = trainerAccessSnapshot || {};
        var st = String(snap.access_state || '')
          .trim()
          .toLowerCase();
        var msg =
          st === 'booking_ready' || snap.schedule_unlocked
            ? 'Расписание уже доступно: откройте его с главной. Для каталога позже дополните анкету и пройдите проверку — раздел «Первые шаги».'
            : 'Анкета ещё не готова: завершите шаги в блоке «Быстрый старт» и дождитесь активации.';
        if (tg && typeof tg.showAlert === 'function') tg.showAlert(msg);
        else alert(msg);
      }

      /** While «Быстрый старт» is visible, the «Профиль» tile is off — use strip CTA + ?onboarding=blocks. */
      function alertHubProfileUseFirstSteps() {
        var msg =
          'Откройте анкету через кнопку в блоке «Быстрый старт» сверху — шаг «Заполни анкету» или «Продолжить».';
        if (tg && typeof tg.showAlert === 'function') tg.showAlert(msg);
        else alert(msg);
      }

      function hubOnboardingStripVisible() {
        var strip = document.getElementById('onboardingStrip');
        if (!strip) return false;
        if (strip.hasAttribute('hidden')) return false;
        if (String(strip.style.display || '').toLowerCase() === 'none') return false;
        return true;
      }

      function hubTrainerProfileNavAllowedDuringOnboarding(pathWithQuery) {
        var raw = String(pathWithQuery || '');
        var base = raw.split('#')[0];
        var q = base.indexOf('?') >= 0 ? base.slice(base.indexOf('?') + 1) : '';
        return q.indexOf('onboarding=blocks') !== -1;
      }

      /** True while strip is visible and hub priority actions are locked (only profile step is active). */
      function hubOnboardingNavBlocksGeneralNavigation() {
        if (!hubOnboardingStripVisible()) return false;
        var d = hubOnboardingData || null;
        if (!d) return true;
        var active = !!(d.is_active || hubDataSaysTrainerActive(d));
        var ttOk = !!d.tt_minimal_complete;
        var stage1Done = active ? !!d.profile_complete : ttOk;
        var schedUnlocked = !!(d.schedule_unlocked || d.is_active);
        var bookLocked = !schedUnlocked || (!active && !ttOk);
        return !stage1Done || bookLocked;
      }

      function alertHubOnboardingStepOrder() {
        var msg = 'Сейчас доступен только текущий шаг в блоке «Быстрый старт» сверху.';
        if (tg && typeof tg.showAlert === 'function') tg.showAlert(msg);
        else alert(msg);
      }

      function navigateToImpl(pathWithQuery) {
        var url = webappBasePath() + pathWithQuery;
        url = withInit(url);
        window.location.href = url;
      }

      function applyHubLockedState() {
        var stripOn = hubOnboardingStripVisible();
        var sectionsOpen = canOpenTrainerSectionsSync();
        var d = hubOnboardingData || null;
        var active = !!(d && (d.is_active || hubDataSaysTrainerActive(d)));
        var ttOk = !!(d && d.tt_minimal_complete);
        var stage1Done = active ? !!(d && d.profile_complete) : ttOk;
        var schedUnlocked = !!(d && (d.schedule_unlocked || d.is_active));
        var bookLocked = !schedUnlocked || (!active && !ttOk);
        var hubSoftGateFirstBookingPhase = !!(
          stripOn &&
          d &&
          stage1Done &&
          !bookLocked &&
          !onboardingBookingStepDone(d)
        );

        var gridLockedAll = stripOn && !hubSoftGateFirstBookingPhase;
        var gridLockedPartial = !sectionsOpen && !stripOn;

        var grid = document.getElementById('hubGrid');
        if (grid) {
          grid.querySelectorAll('.hub-tile:not(.hub-tile--skeleton)').forEach(function(btn) {
            var path = btn.getAttribute('data-path') || '';
            var isLocked;
            if (gridLockedAll) {
              isLocked = true;
            } else if (gridLockedPartial) {
              isLocked = path !== 'trainer-profile';
            } else {
              isLocked = false;
            }
            btn.classList.toggle('hub-tile--locked', isLocked);
            btn.setAttribute('aria-disabled', isLocked ? 'true' : 'false');
          });
        }

        var prioLocked;
        if (stripOn) {
          if (!stage1Done || bookLocked) prioLocked = true;
          else prioLocked = false;
        } else {
          prioLocked = !sectionsOpen;
        }
        var pri = document.getElementById('hubPriorityActions');
        if (pri) {
          pri.querySelectorAll('.hub-quick-action').forEach(function(btn) {
            btn.classList.toggle('hub-quick-action--locked', prioLocked);
            btn.setAttribute('aria-disabled', prioLocked ? 'true' : 'false');
          });
        }

        var shareBtn = document.getElementById('hubShareBookingLinkBtn');
        if (shareBtn && !shareBtn.hasAttribute('hidden')) {
          shareBtn.classList.toggle('hub-share-btn--onboarding-lock', stripOn);
          if (stripOn) {
            shareBtn.setAttribute('disabled', 'disabled');
            shareBtn.setAttribute('aria-disabled', 'true');
          } else {
            shareBtn.removeAttribute('disabled');
            shareBtn.setAttribute('aria-disabled', 'false');
          }
        }

        syncPriorityActionFocus();
        syncHubHeroScheduleClick();
      }

      /** Before first booking, make «Записать клиента» visually dominant as the next best action. */
      function syncPriorityActionFocus() {
        var wrap = document.getElementById('hubPriorityActions');
        if (!wrap) return;
        var d = hubOnboardingData || null;
        var schedUnlocked = !!(d && (d.schedule_unlocked || d.is_active));
        var bookDone = onboardingBookingStepDone(d);
        var focusBook = !!(d && schedUnlocked && !bookDone);
        wrap.classList.toggle('hub-priority-actions--booking-focus', focusBook);
      }

      /** Big hero → расписание, когда день свободен и разделы не заблокированы. */
      function syncHubHeroScheduleClick() {
        var el = document.getElementById('heroScheduleCta');
        if (!el) return;
        var stripOn = hubOnboardingStripVisible();
        var d = hubOnboardingData || null;
        var active = !!(d && (d.is_active || hubDataSaysTrainerActive(d)));
        var ttOk = !!(d && d.tt_minimal_complete);
        var stage1Done = active ? !!(d && d.profile_complete) : ttOk;
        var schedUnlocked = !!(d && (d.schedule_unlocked || d.is_active));
        var bookLocked = !schedUnlocked || (!active && !ttOk);
        var onboardingBlocksHero = stripOn && (!stage1Done || bookLocked);
        var allowed =
          !!getInitData() &&
          hubLastTodayCount === 0 &&
          canOpenTrainerSectionsSync() &&
          !onboardingBlocksHero;
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
        var raw = String(pathWithQuery || '');
        if (isProfilePath(raw)) {
          if (hubOnboardingStripVisible() && !hubTrainerProfileNavAllowedDuringOnboarding(raw)) {
            if (hubTrainerAwaitingFirstBooking()) {
              openHubFirstBookingSoftGate('profile');
            } else {
              alertHubProfileUseFirstSteps();
            }
            return;
          }
          navigateToImpl(raw);
          return;
        }
        if (hubOnboardingNavBlocksGeneralNavigation()) {
          alertHubOnboardingStepOrder();
          return;
        }
        if (canOpenTrainerSectionsSync()) {
          completeHubSectionNavigation(pathWithQuery);
          return;
        }
        /* After moderation, is_active flips on the server while WebView keeps stale JS state — always refetch before blocking. */
        if (!getInitData() || !window.TrainerMiniAppGate) {
          showTrainerOnboardingNavAlert();
          return;
        }
        Promise.all([
          window.TrainerMiniAppGate.fetchAccess(getInitData()).catch(function() {
            return null;
          }),
          fetchTrainerProfileForHub(),
        ])
          .then(function(results) {
            var a = results[0];
            var prof = results[1];
            trainerAccessSnapshot = a;
            mergeHubAccessFromProfilePayload(prof);
            syncHubForceClientChatRelayFromTrainerAccess();
            applyHubLockedState();
            if (trainerAccessSnapshot && window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)) {
              completeHubSectionNavigation(pathWithQuery);
            } else {
              showTrainerOnboardingNavAlert();
            }
          });
      }

      function navigateToWithHash(path, hash) {
        var p = String(path || '').replace(/^\//, '');
        if (p === 'trainer-profile' && hubOnboardingStripVisible()) {
          var h = String(hash || '').replace(/^#/, '');
          var d = hubOnboardingData;
          var allowMod =
            d &&
            h === 'moderation' &&
            ((d.profile_complete && !d.is_active) ||
              (d.is_active && !d.profile_complete) ||
              (!d.is_active && !d.profile_complete && d.tt_minimal_complete));
          if (!allowMod) {
            if (hubTrainerAwaitingFirstBooking()) {
              openHubFirstBookingSoftGate('profile');
            } else {
              alertHubProfileUseFirstSteps();
            }
            return;
          }
        }
        var url = webappBasePath() + p;
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
        if (!getInitData() || !window.TrainerMiniAppGate) {
          showTrainerOnboardingNavAlert();
          return;
        }
        Promise.all([
          window.TrainerMiniAppGate.fetchAccess(getInitData()).catch(function() {
            return null;
          }),
          fetchTrainerProfileForHub(),
        ]).then(function(results) {
          trainerAccessSnapshot = results[0];
          mergeHubAccessFromProfilePayload(results[1]);
          syncHubForceClientChatRelayFromTrainerAccess();
          applyHubLockedState();
          if (trainerAccessSnapshot && window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)) onAllowed();
          else showTrainerOnboardingNavAlert();
        });
      }

      function onboardingBookingStepDone(data) {
        if (!data) return false;
        // has_any_booking = any bookings row ever (incl. cancelled). Upcoming/confirmed cover active case.
        return !!(
          data.has_any_booking ||
          data.has_confirmed_booking ||
          data.has_upcoming_booking
        );
      }

      function onboardingAllComplete(data) {
        if (!data) return false;
        var bookingOk = onboardingBookingStepDone(data);
        if (!bookingOk) return false;
        if (data.is_active && data.profile_complete) return true;
        if (!data.is_active && data.schedule_unlocked && data.tt_minimal_complete) return true;
        return false;
      }

      /**
       * «Быстрый старт» виден, шаг 1 и расписание пройдены, но ещё нет первой записи —
       * сетку не блокируем; при переходе показываем soft gate вместо жёсткого lock.
       */
      function hubTrainerAwaitingFirstBooking() {
        if (!hubOnboardingStripVisible()) return false;
        if (hubOnboardingNavBlocksGeneralNavigation()) return false;
        return !onboardingBookingStepDone(hubOnboardingData);
      }

      function hubPathToFirstBookingSoftGateId(pathWithQuery) {
        var base = String(pathWithQuery || '')
          .split('?')[0]
          .split('#')[0]
          .replace(/^\//, '')
          .toLowerCase();
        if (base === 'trainer-clients') return 'clients';
        if (base === 'trainer-groups') return 'groups';
        if (base === 'trainer-requests') return 'requests';
        if (base === 'schedule-editor') return 'schedule';
        if (base === 'trainer-profile') return 'profile';
        if (base === 'trainer-pass-products') return 'passes';
        if (base === 'trainer-subscription') return 'subscription';
        if (base === 'trainer-stats') return 'stats';
        if (base === 'trainer-referral') return 'referral';
        return null;
      }

      var HUB_SOFT_GATE_FIRST_BOOKING_INTRO = 'После первой записи здесь будет:';
      var HUB_SOFT_GATE_FIRST_BOOKING_FOOTER =
        'Создайте первую запись (можно тестовую), чтобы посмотреть как это работает.';

      var HUB_FIRST_BOOKING_SOFT_GATE = {
        _default: {
          title: 'Раздел после первой записи',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'связка записи с клиентом и расписанием',
            'напоминания и статусы',
            'история и быстрые действия',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
        clients: {
          title: '👥 Клиенты',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'список клиентов',
            'заметки по каждому',
            'история занятий',
            'быстрый контакт',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
        groups: {
          title: '👥 Группы',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'набор и состав участников',
            'расписание групповых слотов',
            'заполненность и статусы',
            'продукты и оплата',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
        requests: {
          title: '📥 Заявки клиентов',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'новые отклики и вопросы',
            'быстрый ответ и переход к записи',
            'меньше ручного поиска в чатах',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
        schedule: {
          title: '📅 Расписание, шаблоны, история записей',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'слоты и недельный шаблон',
            'история записей и занятых окон',
            'напоминания и статусы в одном месте',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
        profile: {
          title: '👤 Профиль и настройки',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'услуги, цены и площадки',
            'видимость в каталоге',
            'модерация и актуальные данные',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
        passes: {
          title: '🎫 Абонементы и сертификаты',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'продукты: абонементы и подарочные сертификаты',
            'выдача, списание и остатки по клиентам',
            'связь с расписанием',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
        subscription: {
          title: '💳 Тариф и оплата',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'текущий план и продление',
            'доступные модули (группы, аналитика)',
            'апгрейд, когда вырастет поток',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
        stats: {
          title: '📈 Показатели и динамика',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'загрузка и динамика записей',
            'метрики по вашему тарифу',
            'цифры на реальных данных, не «пустые» графики',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
        referral: {
          title: '🎁 Рефералы',
          intro: HUB_SOFT_GATE_FIRST_BOOKING_INTRO,
          bullets: [
            'ваша персональная ссылка или код',
            'бонусы за активных приглашённых',
            'итоги в одном разделе',
          ],
          footer: HUB_SOFT_GATE_FIRST_BOOKING_FOOTER,
        },
      };

      function closeHubFirstBookingSoftGate() {
        var m = document.getElementById('hubFirstBookingSoftGate');
        if (!m) return;
        m.style.display = 'none';
        m.setAttribute('aria-hidden', 'true');
      }

      function openHubFirstBookingSoftGate(gateId) {
        var key = HUB_FIRST_BOOKING_SOFT_GATE[gateId] ? gateId : '_default';
        var def = HUB_FIRST_BOOKING_SOFT_GATE[key];
        var m = document.getElementById('hubFirstBookingSoftGate');
        var tEl = document.getElementById('hubSoftGateTitle');
        var introEl = document.getElementById('hubSoftGateIntro');
        var listEl = document.getElementById('hubSoftGateList');
        var footEl = document.getElementById('hubSoftGateFooter');
        var skipEl = document.getElementById('hubSoftGateSkip');
        if (!m || !tEl || !introEl || !listEl || !footEl) return;
        tEl.textContent = def.title;
        introEl.textContent = def.intro;
        listEl.innerHTML = (def.bullets || []).map(function(b) {
          return '<li>' + escapeHtml(b) + '</li>';
        }).join('');
        footEl.textContent = def.footer;
        if (skipEl) {
          skipEl.hidden = true;
          skipEl.onclick = null;
          skipEl.textContent = '';
          if (key === 'profile') {
            skipEl.hidden = false;
            skipEl.textContent = 'Открыть анкету';
            skipEl.onclick = function() {
              closeHubFirstBookingSoftGate();
              navigateToImpl('trainer-profile?onboarding=blocks');
            };
          } else if (key === 'schedule') {
            skipEl.hidden = false;
            skipEl.textContent = 'Только открыть расписание';
            skipEl.onclick = function() {
              closeHubFirstBookingSoftGate();
              navigateToImpl('schedule-editor');
            };
          } else if (key === 'subscription') {
            skipEl.hidden = false;
            skipEl.textContent = 'Перейти к тарифу и оплате';
            skipEl.onclick = function() {
              closeHubFirstBookingSoftGate();
              navigateToImpl('trainer-subscription?v=20260450');
            };
          }
        }
        m.style.display = 'flex';
        m.setAttribute('aria-hidden', 'false');
      }

      function wireHubFirstBookingSoftGate() {
        var m = document.getElementById('hubFirstBookingSoftGate');
        if (!m || m.dataset.wiredHubFirstBookingSoftGate === '1') return;
        m.dataset.wiredHubFirstBookingSoftGate = '1';
        var primary = document.getElementById('hubSoftGateCtaPrimary');
        var sandbox = document.getElementById('hubSoftGateCtaSandbox');
        var closeBtn = document.getElementById('hubSoftGateClose');
        if (closeBtn) {
          closeBtn.onclick = function() {
            closeHubFirstBookingSoftGate();
          };
        }
        m.onclick = function(ev) {
          if (ev.target === m) closeHubFirstBookingSoftGate();
        };
        if (primary) {
          primary.onclick = function() {
            closeHubFirstBookingSoftGate();
            hubQuickBookIsSandbox = false;
            ensureTrainerSectionsAccess(function() {
              openHubQuickBookClientFlowFirst();
            });
          };
        }
        if (sandbox) {
          sandbox.onclick = function() {
            closeHubFirstBookingSoftGate();
            hubQuickBookIsSandbox = true;
            ensureTrainerSectionsAccess(function() {
              openHubQuickBookClientFlowFirst();
            });
          };
        }
      }

      function completeHubSectionNavigation(pathWithQuery) {
        var raw = String(pathWithQuery || '');
        var gid = hubPathToFirstBookingSoftGateId(raw);
        if (hubTrainerAwaitingFirstBooking() && gid) {
          openHubFirstBookingSoftGate(gid);
          return;
        }
        navigateToImpl(raw);
      }

      function parseNonNegativeInt(v) {
        var n = typeof v === 'number' && !isNaN(v) ? v : parseInt(String(v == null ? '' : v), 10);
        if (isNaN(n) || n < 0) return 0;
        return n;
      }

      function getHubSlotCoverage(onb) {
        var thisWeekCount = parseNonNegativeInt(onb && onb.slots_this_week_count);
        var nextWeekCount = parseNonNegativeInt(onb && onb.slots_next_week_count);
        return { thisWeekCount: thisWeekCount, nextWeekCount: nextWeekCount };
      }

      function hubRhythmHintStorageKeyBase() {
        var id = trainerAccessSnapshot && trainerAccessSnapshot.trainer_id;
        if (id == null || id === '' || isNaN(Number(id))) return null;
        return 'trainer_hub_schedule_rhythm_v2_' + String(id);
      }

      function hubRhythmHintDismissUntilStorageKey() {
        var base = hubRhythmHintStorageKeyBase();
        return base ? base + '_dismiss_until' : null;
      }

      function hubRhythmDismissKey(hintId) {
        var id = trainerAccessSnapshot && trainerAccessSnapshot.trainer_id;
        if (id == null || id === '' || isNaN(Number(id))) return null;
        return 'trainer_hub_rhythm_dismiss_v1_' + String(id) + '_' + String(hintId);
      }

      /**
       * Unified dismiss timestamp per hint id; merges legacy template key (trainer_hub_schedule_rhythm_v2_*_dismiss_until).
       */
      function getRhythmDismissUntilMs(hintId) {
        var k = hubRhythmDismissKey(hintId);
        var now = Date.now();
        var fromNew = 0;
        try {
          if (k) fromNew = parseInt(String(localStorage.getItem(k) || '0'), 10);
        } catch (e) {
          fromNew = 0;
        }
        if (!isNaN(fromNew) && fromNew > now) return fromNew;

        if (hintId === 'template') {
          var dk = hubRhythmHintDismissUntilStorageKey();
          try {
            if (dk) {
              var v = parseInt(String(localStorage.getItem(dk) || '0'), 10);
              if (!isNaN(v) && v > now) return v;
            }
          } catch (e2) { /* */ }
        }
        return 0;
      }

      function setRhythmDismissUntilMs(hintId, untilMs) {
        var k = hubRhythmDismissKey(hintId);
        try {
          if (k) localStorage.setItem(k, String(untilMs));
        } catch (e) { /* */ }
        if (hintId === 'template') {
          var dk = hubRhythmHintDismissUntilStorageKey();
          try {
            if (dk) localStorage.setItem(dk, String(untilMs));
          } catch (e2) { /* */ }
        }
      }

      function isRhythmHintDismissed(hintId) {
        return getRhythmDismissUntilMs(hintId) > Date.now();
      }

      /** True when schedule-editor недавно создал слоты — TTL в localStorage (переживает перезагрузку WebView; sessionStorage Telegram часто чистится). */
      function readTrainerHubFillSlotsRhythmBoostPending() {
        try {
          var raw = localStorage.getItem(HUB_FILL_SLOTS_RHYTHM_BOOST_KEY);
          if (!raw) {
            try {
              var legacy = sessionStorage.getItem(HUB_FILL_SLOTS_RHYTHM_BOOST_KEY);
              if (legacy) {
                localStorage.setItem(HUB_FILL_SLOTS_RHYTHM_BOOST_KEY, legacy);
                sessionStorage.removeItem(HUB_FILL_SLOTS_RHYTHM_BOOST_KEY);
                raw = legacy;
              }
            } catch (e0) {}
          }
          if (!raw) return false;
          var ts = parseInt(raw, 10);
          if (isNaN(ts)) {
            localStorage.removeItem(HUB_FILL_SLOTS_RHYTHM_BOOST_KEY);
            return false;
          }
          if (Date.now() - ts > HUB_FILL_SLOTS_RHYTHM_BOOST_TTL_MS) {
            localStorage.removeItem(HUB_FILL_SLOTS_RHYTHM_BOOST_KEY);
            return false;
          }
          return true;
        } catch (e) {
          return false;
        }
      }

      function hideLegacyRhythmHintCards() {
        ['hubScheduleRhythmHint', 'hubShareLinkGrowthHint', 'hubClientNotesRhythmHint'].forEach(function(id) {
          var el = document.getElementById(id);
          if (el) {
            el.setAttribute('hidden', 'hidden');
            el.style.display = 'none';
          }
        });
      }

      /**
       * Builds rhythm hint candidates (priority desc). Max two shown after dismiss filter.
       */
      function buildHubRhythmCandidates() {
        var out = [];
        var d = hubOnboardingData;
        if (!d || !getInitData()) return out;

        var active = !!d.is_active;
        var complete = onboardingAllComplete(d);

        /* After first booking: nudge catalog path (profile / moderation / visibility) — runs even before full hub unlock. */
        if (onboardingBookingStepDone(d) && !isRhythmHintDismissed('catalog_publication')) {
          var catVis = d.is_catalog_visible !== false && d.is_catalog_visible !== 0;
          var inPublicCatalog = !!d.is_active && !!d.profile_complete && !!catVis;
          if (!inPublicCatalog) {
            var body = '';
            var ctaLab = 'Профиль';
            if (!d.is_active && !d.profile_complete) {
              body =
                'Чтобы вас находили в общем каталоге, доведите профиль до проверки: так мы подтверждаем карточку перед публикацией.';
            } else if (!d.is_active && d.profile_complete) {
              body =
                'Профиль отправлен на проверку. После активации аккаунта вас смогут найти в каталоге — это следующий шаг к новым клиентам из списка.';
            } else if (d.is_active && !d.profile_complete) {
              body =
                'Для показа в каталоге закройте критерии профиля — в разделе статуса видно, что ещё важно для публикации.';
            } else if (d.is_active && !catVis) {
              body =
                'Сейчас вас нет в общем списке. Включите «Показать в каталоге» в профиле, когда будете готовы к новым обращениям оттуда.';
            }
            if (body) {
              out.push({
                id: 'catalog_publication',
                priority: 108,
                text: body,
                ctaLabel: ctaLab,
                action: 'profile_catalog',
              });
            }
          }
        }

        if (!active || !complete) return out;

        /* Growth loop: referral accrual (cap shown on referral page) — show even in Lead Mode. */
        if (!isRhythmHintDismissed('referral_growth')) {
          out.push({
            id: 'referral_growth',
            priority: 66,
            textHtml:
              '<strong>До 60 бесплатных дней</strong> полного доступа — приглашайте коллег по реферальной программе. Подробности в разделе «Рефералы».',
            ctaLabel: 'Рефералы',
            action: 'trainer_referral',
          });
        }

        /* Lead Mode: CRM off — hide operational rhythm (slots, open loops, template). Not subscription_lapsed: Lead banner covers that. */
        if (d.has_crm_subscription_access === false) {
          return out;
        }

        var availThis = parseNonNegativeInt(d.available_slots_this_week_count);
        var availNext = parseNonNegativeInt(d.available_slots_next_week_count);
        var bookThis = parseNonNegativeInt(d.bookings_this_week_count);
        var bookNext = parseNonNegativeInt(d.bookings_next_week_count);
        var slotsNext = parseNonNegativeInt(d.slots_next_week_count);
        var wd = parseNonNegativeInt(d.weekly_template_count);
        var coverage = getHubSlotCoverage(d);
        var thisWeekReady = coverage.thisWeekCount > 0;
        var nextWeekReady = coverage.nextWeekCount > 0;
        /* Until weekly template exists, slot nudges fight onboarding — defer them while template hint is active. */
        var slotRhythmDeferredForTemplateOnboarding =
          wd === 0 && !isRhythmHintDismissed('template');

        var openLoopPending = parseNonNegativeInt(d.open_loop_pending_bookings_count);
        var openLoopNoUpcoming = parseNonNegativeInt(d.open_loop_clients_no_upcoming_count);
        var openLoopNoTg = parseNonNegativeInt(d.open_loop_clients_no_telegram_count);
        var fillSlotsCandidates = parseNonNegativeInt(d.fill_slots_invite_candidates_count);

        /* Open loops (Zeigarnik): unfinished business, not just “do X” maintenance — sorted by priority below. */
        if (openLoopPending > 0 && !isRhythmHintDismissed('open_loop_pending')) {
          /*
           * Checklist считает все pending; блок «Ближайшие» показывает только HUB_UPCOMING_BOOKINGS_MAX карточек.
           * hubLastPendingInNearestStripCount совпадает с видимым списком.
           */
          var hubBookingsHydrated = hubLastBookingsDays !== null;
          var pendingInNearList = hubLastPendingInNearestStripCount;
          var pendingOnlyBeyondHubWindow = hubBookingsHydrated && pendingInNearList === 0;

          var openLoopText =
            'Осталось подтвердить ' +
            openLoopPending +
            ' ' +
            pluralRu(openLoopPending, 'запись', 'записи', 'записей') +
            ' — до подтверждения клиент не увидит занятие как согласованное.';
          var openLoopCand = {
            id: 'open_loop_pending',
            priority: 103,
            text: openLoopText,
            ctaLabel: 'К ближайшим',
            action: 'hub_upcoming_bookings',
          };
          if (pendingOnlyBeyondHubWindow) {
            openLoopCand.cta2Label = 'Расписание';
            openLoopCand.cta2Action = 'schedule';
            openLoopCand.secondaryCtaFirst = true;
          }
          out.push(openLoopCand);
        }
        if (openLoopNoUpcoming > 0 && !isRhythmHintDismissed('open_loop_no_next')) {
          var hasFutureAvailSlots = !!d.has_future_available_slots;
          var noNextBase =
            openLoopNoUpcoming +
            ' ' +
            pluralRu(openLoopNoUpcoming, 'ученик', 'ученика', 'учеников') +
            ' пока без следующей записи';
          if (!hasFutureAvailSlots) {
            out.push({
              id: 'open_loop_no_next',
              priority: 97,
              text:
                noNextBase +
                '. В расписании сейчас нет свободных слотов — сначала добавьте окна, чтобы можно было пригласить на конкретное время.',
              ctaLabel: 'Расписание',
              action: 'schedule',
            });
          } else if (fillSlotsCandidates > 0) {
            /* Ритм-хинт считает «без записи»; модалка «Напомнить» всё равно подгружает всех с Telegram + фильтр в UI. */
            var remindN = fillSlotsCandidates;
            /* Must match open_loop_clients_no_telegram_count, not (no_upcoming − remindN): no-TG with an upcoming booking are still not reachable by «Напомнить». */
            var clientsNotInBot = openLoopNoTg;
            var noNextRemind =
              remindN +
              ' ' +
              pluralRu(remindN, 'ученик', 'ученика', 'учеников') +
              ' без следующей записи' +
              (clientsNotInBot > 0
                ? ' · ещё ' +
                  clientsNotInBot +
                  ' ' +
                  pluralRu(clientsNotInBot, 'клиент', 'клиента', 'клиентов') +
                  ' не в боте — «Напомнить» им не уйдёт; пришлите общую ссылку с главной (кнопка «Связь»)'
                : '') +
              '.';
            var remindCand = {
              id: 'open_loop_no_next',
              priority: 97,
              text: noNextRemind,
              ctaLabel: 'Напомнить',
              action: 'fill_slots_invites',
            };
            if (clientsNotInBot > 0) {
              remindCand.cta2Label = 'Клиенты без бота';
              remindCand.cta2Action = 'trainer_clients_invite_bot';
            }
            out.push(remindCand);
          } else {
            out.push({
              id: 'open_loop_no_next',
              priority: 97,
              text:
                noNextBase +
                '. Напоминание в боте — только подключённым. Остальным: общая ссылка с главной (кнопка «Связь»).',
              ctaLabel: 'Клиенты без бота',
              action: 'trainer_clients_invite_bot',
              cta2Label: 'Рассылка в боте',
              cta2Action: 'fill_slots_invites',
            });
          }
        }
        var mailingRecipients = fillSlotsCandidates > 0;
        var mailingRecipientsShow =
          mailingRecipients &&
          (availNext > 0 ||
            (availThis > 0 &&
              availNext === 0 &&
              hubFillSlotsRhythmBoostActiveThisResolverPass));
        /* После сохранения слотов в редакторе: показать «Напомнить» даже если список для рассылки пуст (временно по продукту). */
        var mailingVacancyAfterNewSlots =
          hubFillSlotsRhythmBoostActiveThisResolverPass &&
          (availNext > 0 || availThis > 0) &&
          !mailingRecipients;
        var blockOpenLoopFreeNextForTemplate =
          slotRhythmDeferredForTemplateOnboarding && !hubFillSlotsRhythmBoostActiveThisResolverPass;
        var showOpenLoopFreeNext =
          !isRhythmHintDismissed('open_loop_free_next') &&
          !blockOpenLoopFreeNextForTemplate &&
          (hubFillSlotsRhythmBoostActiveThisResolverPass ||
            mailingRecipientsShow ||
            mailingVacancyAfterNewSlots);
        if (showOpenLoopFreeNext) {
          var availRemind = availNext > 0 ? availNext : availThis;
          var remindPri = hubFillSlotsRhythmBoostActiveThisResolverPass
            ? HUB_RHYTHM_FILL_SLOTS_NOTIFY_PRIORITY_BOOST
            : 72;
          var mailingBody;
          if (mailingRecipientsShow) {
            mailingBody =
              (availNext > 0 ? 'На следующей неделе ' : 'На этой неделе ') +
              availRemind +
              ' ' +
              pluralRu(
                availRemind,
                'свободный слот',
                'свободных слота',
                'свободных слотов',
              ) +
              ' — кому из клиентов в боте напомнить о записи?';
          } else if (mailingVacancyAfterNewSlots) {
            mailingBody =
              (availNext > 0 ? 'На следующей неделе ' : 'На этой неделе ') +
              availRemind +
              ' ' +
              pluralRu(
                availRemind,
                'свободный слот',
                'свободных слота',
                'свободных слотов',
              ) +
              '. Кому из клиентов в боте напомнить о записи?';
          } else {
            /* Boost right after schedule-editor save: hub bootstrap counts may still be zero for a moment. */
            mailingBody =
              'Слоты в расписании обновлены — напомнить клиентам в боте о возможности записи?';
          }
          out.push({
            id: 'open_loop_free_next',
            priority: remindPri,
            text: mailingBody,
            ctaLabel: 'Напомнить',
            action: 'fill_slots_invites',
          });
        }
        if (
          !slotRhythmDeferredForTemplateOnboarding &&
          availNext > 0 &&
          fillSlotsCandidates === 0 &&
          !isRhythmHintDismissed('open_loop_free_next_growth') &&
          /* Не дублировать «ссылку на запись», если уже показали хинт рассылки после новых слотов. */
          !(hubFillSlotsRhythmBoostActiveThisResolverPass && availNext > 0)
        ) {
          var growthPri = hubFillSlotsRhythmBoostActiveThisResolverPass
            ? HUB_RHYTHM_FILL_SLOTS_NOTIFY_PRIORITY_BOOST
            : 58;
          out.push({
            id: 'open_loop_free_next_growth',
            priority: growthPri,
            text:
              'На следующей неделе ' +
              availNext +
              ' ' +
              pluralRu(
                availNext,
                'свободный слот',
                'свободных слота',
                'свободных слотов',
              ) +
              ' — хороший повод привлечь новых клиентов. Поделитесь ссылкой.',
            ctaLabel: 'Пригласительная ссылка',
            action: 'share_link',
          });
        }

        if (
          !slotRhythmDeferredForTemplateOnboarding &&
          availThis === 0 &&
          bookThis < HUB_RHYTHM_BOOKINGS_LOW_THRESHOLD
        ) {
          out.push({
            id: 'slots_this_week',
            priority: 100,
            text: 'На этой неделе нет свободных слотов. Добавьте окна, чтобы клиенты могли записаться.',
            ctaLabel: 'Добавить слоты',
            action: 'schedule',
          });
        }

        var nextWeekGap =
          slotsNext === 0 || (availNext === 0 && bookNext < HUB_RHYTHM_BOOKINGS_LOW_THRESHOLD);
        if (!slotRhythmDeferredForTemplateOnboarding && nextWeekGap) {
          out.push({
            id: 'slots_next_week',
            priority: 90,
            text: 'На следующей неделе пока нет слотов. Заполните расписание заранее.',
            ctaLabel: 'Добавить слоты',
            action: 'schedule',
          });
        }

        // Universal invite link is available to all trainers (no booking tier gate)
        {
          var hasSomethingToShare =
            wd >= 1 ||
            !!d.has_future_slots ||
            !!d.has_future_available_slots ||
            !!d.has_any_booking ||
            !!d.has_upcoming_booking ||
            !!d.has_confirmed_booking;
          var eligibleForShare =
            complete || (!!d.is_active && onboardingBookingStepDone(d));
          if (eligibleForShare && hasSomethingToShare) {
            out.push({
              id: 'share_link',
              priority: 72,
              text:
                'Поделитесь пригласительной ссылкой с клиентами. Кнопка со значком связи справа вверху.',
              ctaLabel: 'Скопировать ссылку',
              action: 'share_link',
            });
          }
        }

        /* Weekly template: do not gate on _last_shown — that hid the candidate for 10d after any render and left only slot hints. */
        /* Weekly template = onboarding before «maintenance» slot nudges — higher priority than slots_this/next. */
        if (wd === 0 && !isRhythmHintDismissed('template')) {
          var tplText =
            thisWeekReady && nextWeekReady
              ? 'Добавьте часы в шаблон расписания — потом неделю можно накатить из шаблона за пару шагов.'
              : 'Создайте шаблон недели с постоянными часами — так проще держать ритм и наполнять расписание.';
          out.push({
            id: 'template',
            priority: 104,
            text: tplText,
            ctaLabel: 'Шаблон в расписании',
            action: 'template',
          });
        }

        if (!!d.has_completed_booking && !isRhythmHintDismissed('client_notes')) {
          out.push({
            id: 'client_notes',
            priority: 40,
            text:
              'После завершённой записи можно кратко зафиксировать заметки в карточке клиента — так проще вести следующие занятия.',
            ctaLabel: 'Профиль клиента',
            action: 'client_notes',
          });
        }

        /* Same session: at most one of «без следующей записи» vs «свободные слоты — напомнить» (duplicate «Напомнить», high cognitive load). Winner = higher priority (e.g. post–schedule-editor boost 130 beats 97). */
        (function dedupeHubRemindSlotHeadlines() {
          var cluster = out.filter(function(c) {
            return c.id === 'open_loop_no_next' || c.id === 'open_loop_free_next';
          });
          if (cluster.length <= 1) return;
          cluster.sort(function(a, b) {
            return b.priority - a.priority;
          });
          var winner = cluster[0];
          out = out.filter(function(c) {
            if (c.id !== 'open_loop_no_next' && c.id !== 'open_loop_free_next') return true;
            return c === winner;
          });
        })();

        if (
          openLoopNoTg > 0 &&
          !isRhythmHintDismissed('open_loop_no_telegram') &&
          !out.some(function(c) {
            return c.id === 'open_loop_no_next';
          })
        ) {
          out.push({
            id: 'open_loop_no_telegram',
            priority: 88,
            text:
              openLoopNoTg +
              ' ' +
              pluralRu(openLoopNoTg, 'клиент', 'клиента', 'клиентов') +
              ' ещё не в боте. Откройте список по кнопке и отправьте им одну общую пригласительную ссылку с главной страницы кабинета (значок связи справа вверху).',
            ctaLabel: 'Клиенты без бота',
            action: 'trainer_clients_invite_bot',
          });
        }

        return out;
      }

      function runRhythmCandidateAction(cand) {
        if (!cand || !cand.action) return;
        if (cand.action === 'subscription') {
          navigateTo('trainer-subscription?v=20260450');
          return;
        }
        if (cand.action === 'schedule') {
          ensureTrainerSectionsAccess(function() {
            navigateTo('schedule-editor');
          });
          return;
        }
        if (cand.action === 'template') {
          ensureTrainerSectionsAccess(function() {
            navigateTo('schedule-editor?tab=template');
          });
          return;
        }
        if (cand.action === 'share_link') {
          ensureTrainerSectionsAccess(function() {
            var headBtn = document.getElementById('hubShareBookingLinkBtn');
            if (headBtn) headBtn.click();
          });
          return;
        }
        if (cand.action === 'client_notes') {
          ensureTrainerSectionsAccess(function() {
            var od = hubOnboardingData;
            var raw = od && od.last_completed_booking_client_id;
            var cid =
              raw != null && raw !== '' && !isNaN(Number(raw)) ? parseInt(String(raw), 10) : NaN;
            if (!isNaN(cid) && cid > 0) {
              navigateTo('trainer-clients?client_id=' + encodeURIComponent(String(cid)));
            } else {
              navigateTo('trainer-clients');
            }
          });
          return;
        }
        if (cand.action === 'hub_upcoming_bookings') {
          ensureTrainerSectionsAccess(function() {
            var el = document.getElementById('bookingsBlock');
            if (el) {
              try {
                el.scrollIntoView({ behavior: 'smooth', block: 'start' });
              } catch (e) {}
            }
          });
          return;
        }
        if (cand.action === 'trainer_clients') {
          ensureTrainerSectionsAccess(function() {
            navigateTo('trainer-clients');
          });
          return;
        }
        if (cand.action === 'trainer_clients_invite_bot') {
          ensureTrainerSectionsAccess(function() {
            navigateTo('trainer-clients?focus=invite_bot');
          });
          return;
        }
        if (cand.action === 'fill_slots_invites') {
          openHubFillSlotsInvitesFlow(null, null);
          return;
        }
        if (cand.action === 'profile_catalog') {
          var od2 = hubOnboardingData;
          if (od2 && !od2.is_active && od2.tt_minimal_complete && !od2.profile_complete) {
            /* TTV already done — ?onboarding=blocks would finish the tour with zero steps and redirect home. */
            navigateToWithHash('trainer-profile', 'moderation');
            return;
          }
          if (od2 && od2.is_active && !od2.profile_complete) {
            navigateToWithHash('trainer-profile', 'moderation');
            return;
          }
          navigateTo('trainer-profile');
          return;
        }
        if (cand.action === 'trainer_referral') {
          navigateTo('trainer-referral');
          return;
        }
      }

      /** Renders up to two priority rhythm hints; hides legacy fixed strips. */
      function applyHubRhythmResolver() {
        hubFillSlotsRhythmBoostActiveThisResolverPass = readTrainerHubFillSlotsRhythmBoostPending();
        hideLegacyRhythmHintCards();
        var candidates = buildHubRhythmCandidates();
        candidates.sort(function(a, b) {
          return b.priority - a.priority;
        });
        var picked = [];
        for (var i = 0; i < candidates.length && picked.length < 2; i++) {
          if (!isRhythmHintDismissed(candidates[i].id)) picked.push(candidates[i]);
        }
        hubActiveRhythmHintIds = picked.map(function(p) {
          return p.id;
        });
        hubLastRhythmPicked = [picked[0] || null, picked[1] || null];

        for (var s = 0; s < 2; s++) {
          var container = document.getElementById('hubRhythmSlot' + s);
          var cand = picked[s];
          if (!container) continue;
          if (!cand) {
            container.setAttribute('hidden', 'hidden');
            container.style.display = 'none';
            container.dataset.hubRhythmHintId = '';
            var actionsEmpty = container.querySelector('.hub-schedule-rhythm-hint__actions');
            if (actionsEmpty) actionsEmpty.classList.remove('hub-rhythm-actions--secondary-first');
            continue;
          }
          container.dataset.hubRhythmHintId = cand.id;
          container.removeAttribute('hidden');
          container.style.display = 'flex';
          var txt = document.getElementById('hubRhythmSlot' + s + 'Text');
          var cta = document.getElementById('hubRhythmSlot' + s + 'Cta');
          var cta2 = document.getElementById('hubRhythmSlot' + s + 'Cta2');
          if (txt) {
            if (cand.textHtml) txt.innerHTML = cand.textHtml;
            else txt.textContent = cand.text;
          }
          if (cta) {
            cta.textContent = cand.ctaLabel;
            cta.className = 'btn-sm btn-primary';
          }
          if (cta2) {
            if (cand.cta2Label && cand.cta2Action) {
              cta2.textContent = cand.cta2Label;
              cta2.removeAttribute('hidden');
              cta2.style.display = '';
              cta2.className = 'btn-sm btn-secondary hub-rhythm-slot-cta2';
            } else {
              cta2.textContent = '';
              cta2.setAttribute('hidden', 'hidden');
              cta2.style.display = 'none';
            }
          }
          var actionsRow = container.querySelector('.hub-schedule-rhythm-hint__actions');
          if (actionsRow) {
            if (cand.secondaryCtaFirst && cand.cta2Label && cand.cta2Action) {
              actionsRow.classList.add('hub-rhythm-actions--secondary-first');
            } else {
              actionsRow.classList.remove('hub-rhythm-actions--secondary-first');
            }
          }
        }
        if (hubRhythmHintsReady) {
          hideHubRhythmHintsSkeleton();
        }
      }

      function syncHubWeekRhythmPanel() {
        applyHubRhythmResolver();
      }

      function wireHubRhythmSlots() {
        [0, 1].forEach(function(ix) {
          var prefix = 'hubRhythmSlot' + ix;
          var dismissBtn = document.getElementById(prefix + 'Dismiss');
          var ctaBtn = document.getElementById(prefix + 'Cta');
          if (dismissBtn && !dismissBtn.dataset.wiredRhythmSlot) {
            dismissBtn.dataset.wiredRhythmSlot = '1';
            dismissBtn.onclick = function() {
              var container = document.getElementById(prefix);
              var hid = container && container.dataset.hubRhythmHintId;
              if (hid) {
                var days =
                  hid === 'share_link' ||
                  hid === 'template' ||
                  hid === 'client_notes' ||
                  hid === 'catalog_publication' ||
                  hid === 'subscription_lapsed' ||
                  hid === 'referral_growth'
                    ? HUB_RHYTHM_DISMISS_DAYS_LONG
                    : HUB_RHYTHM_DISMISS_DAYS_SHORT;
                setRhythmDismissUntilMs(hid, Date.now() + days * 24 * 60 * 60 * 1000);
              }
              applyHubRhythmResolver();
              renderHubSummaryHints();
            };
          }
          if (ctaBtn && !ctaBtn.dataset.wiredRhythmSlot) {
            ctaBtn.dataset.wiredRhythmSlot = '1';
            ctaBtn.onclick = function() {
              var cand = hubLastRhythmPicked[ix];
              runRhythmCandidateAction(cand);
            };
          }
          var cta2Btn = document.getElementById(prefix + 'Cta2');
          if (cta2Btn && !cta2Btn.dataset.wiredRhythmSlot) {
            cta2Btn.dataset.wiredRhythmSlot = '1';
            cta2Btn.onclick = function() {
              var cand = hubLastRhythmPicked[ix];
              if (cand && cand.cta2Action) {
                runRhythmCandidateAction({ action: cand.cta2Action });
              }
            };
          }
        });
      }

      function wireHubScheduleRhythmHint() {
        var dBtn = document.getElementById('hubScheduleRhythmDismiss');
        var oBtn = document.getElementById('hubScheduleRhythmOpen');
        if (dBtn && !dBtn.dataset.wiredRhythm) {
          dBtn.dataset.wiredRhythm = '1';
          dBtn.onclick = function() {
            setRhythmDismissUntilMs('template', Date.now() + HUB_RHYTHM_DISMISS_DAYS_LONG * 24 * 60 * 60 * 1000);
            syncHubWeekRhythmPanel();
            renderHubSummaryHints();
          };
        }
        if (oBtn && !oBtn.dataset.wiredRhythm) {
          oBtn.dataset.wiredRhythm = '1';
          oBtn.onclick = function() {
            runRhythmCandidateAction({ action: 'template' });
          };
        }
      }

      /** Same storage as «×» on growth strip — call after successful copy or dismiss. */
      function dismissHubShareLinkGrowthHintPersisted() {
        setRhythmDismissUntilMs('share_link', Date.now() + HUB_RHYTHM_DISMISS_DAYS_LONG * 24 * 60 * 60 * 1000);
        applyHubRhythmResolver();
        renderHubSummaryHints();
      }

      function wireHubShareLinkGrowthHint() {
        var dBtn = document.getElementById('hubShareLinkGrowthDismiss');
        var oBtn = document.getElementById('hubShareLinkGrowthOpen');
        if (dBtn && !dBtn.dataset.wiredShareGrowth) {
          dBtn.dataset.wiredShareGrowth = '1';
          dBtn.onclick = function() {
            dismissHubShareLinkGrowthHintPersisted();
          };
        }
        if (oBtn && !oBtn.dataset.wiredShareGrowth) {
          oBtn.dataset.wiredShareGrowth = '1';
          oBtn.onclick = function() {
            runRhythmCandidateAction({ action: 'share_link' });
          };
        }
      }

      function wireHubClientNotesRhythmHint() {
        var dBtn = document.getElementById('hubClientNotesRhythmDismiss');
        var oBtn = document.getElementById('hubClientNotesRhythmOpen');
        if (dBtn && !dBtn.dataset.wiredClientNotesRhythm) {
          dBtn.dataset.wiredClientNotesRhythm = '1';
          dBtn.onclick = function() {
            setRhythmDismissUntilMs('client_notes', Date.now() + HUB_RHYTHM_DISMISS_DAYS_LONG * 24 * 60 * 60 * 1000);
            syncHubWeekRhythmPanel();
            renderHubSummaryHints();
          };
        }
        if (oBtn && !oBtn.dataset.wiredClientNotesRhythm) {
          oBtn.dataset.wiredClientNotesRhythm = '1';
          oBtn.onclick = function() {
            runRhythmCandidateAction({ action: 'client_notes' });
          };
        }
      }

      function applyOnboardingChecklist(data) {
        hubOnboardingData = data;
        hubRhythmHintsReady = true;
        if (data && data.trainer_id != null && data.trainer_id !== '') {
          trainerAccessSnapshot = trainerAccessSnapshot || {};
          trainerAccessSnapshot.trainer_id = data.trainer_id;
        }
        /* Checklist loads async after GET /trainer/access — can show activation before snapshot was refreshed. */
        var tsCh = data && String(data.trainer_status || '')
          .trim()
          .toLowerCase();
        var activeFromChecklist = !!(data && hubDataSaysTrainerActive(data));
        var schedUnlocked = !!(data && (data.schedule_unlocked || activeFromChecklist));
        var ttOk = !!(data && data.tt_minimal_complete);
        if (activeFromChecklist) {
          trainerAccessSnapshot = trainerAccessSnapshot || {};
          trainerAccessSnapshot.is_active = true;
          trainerAccessSnapshot.access_state = 'active';
          trainerAccessSnapshot.schedule_unlocked = true;
          if (tsCh) trainerAccessSnapshot.trainer_status = tsCh;
        } else if (data && data.schedule_unlocked) {
          trainerAccessSnapshot = trainerAccessSnapshot || {};
          trainerAccessSnapshot.is_active = false;
          trainerAccessSnapshot.access_state = 'booking_ready';
          trainerAccessSnapshot.schedule_unlocked = true;
          if (tsCh) trainerAccessSnapshot.trainer_status = tsCh;
        }
        var strip = document.getElementById('onboardingStrip');
        if (!strip) {
          syncHubWeekRhythmPanel();
          return;
        }
        /* Both stages done: hide checklist (no separate sandbox banner — success is toast + bot push). */
        if (data && onboardingAllComplete(data)) {
          strip.setAttribute('hidden', 'hidden');
          strip.style.display = 'none';
          applyHubLockedState();
          applyHubHero();
          refreshHubEmptyBookingsIfNeeded();
          syncHubWeekRhythmPanel();
          renderHubSummaryHints();
          return;
        }
        strip.removeAttribute('hidden');
        strip.style.display = 'block';

        var leadEl = document.querySelector('.onboarding-strip-lead');
        if (leadEl && data) {
          leadEl.textContent = '2 шага — и первый клиент уже в системе.';  // kept short and motivating
        }

        var stepP = document.getElementById('onboardingStepProfile');
        var iconP = document.getElementById('onboardingIconProfile');
        var hintP = document.getElementById('onboardingHintProfile');
        var ctaP = document.getElementById('onboardingCtaProfile');
        var pc = !!(data && data.profile_complete);
        var fpc = !!(data && data.full_profile_complete);
        var active = !!(data && data.is_active);
        /** Stage 1: pending — TTV minimal; active — полная очередь на модерацию. */
        var stage1Done = active ? pc : ttOk;
        if (stepP) {
          stepP.classList.toggle('done', stage1Done);
          stepP.classList.remove('locked');
        }
        if (iconP) iconP.textContent = stage1Done ? '✓' : '1';
        if (hintP) {
          if (!stage1Done && !active) {
            hintP.textContent = 'Откроет расписание и записи.';
          } else if (!stage1Done && active) {
            hintP.textContent = 'Осталось закрыть пару пунктов — и вы в каталоге.';
          } else if (active && !fpc) {
            hintP.textContent = 'Добавьте детали — клиенты видят полный профиль.';
          } else if (schedUnlocked && ttOk && !pc) {
            hintP.textContent = 'База готова — можно отправить на проверку.';
          } else {
            hintP.textContent = 'Готово — анкета ушла на проверку.';
          }
        }
        if (ctaP) {
          if (stage1Done) {
            ctaP.disabled = true;
            ctaP.textContent = 'Готово';
          } else {
            ctaP.disabled = false;
            if (pc) ctaP.textContent = 'Статус';
            else if (!active && !ttOk) ctaP.textContent = 'Продолжить';
            else ctaP.textContent = 'Открыть';
          }
        }

        var bookingStepDone = onboardingBookingStepDone(data);
        var bookDone = schedUnlocked && !!bookingStepDone;
        var bookLocked = !schedUnlocked || (!active && !ttOk);
        var stepB = document.getElementById('onboardingStepBooking');
        var iconB = document.getElementById('onboardingIconBooking');
        var hintB = document.getElementById('onboardingHintBooking');
        var ctasWrap = document.getElementById('onboardingBookingCtas');
        var ctaBReal = document.getElementById('onboardingCtaBookingReal');
        var ctaBSandbox = document.getElementById('onboardingCtaBookingSandbox');
        var ctaBDone = document.getElementById('onboardingCtaBookingDone');
        if (stepB) {
          stepB.classList.toggle('done', bookDone);
          stepB.classList.toggle('locked', bookLocked);
        }
        if (iconB) iconB.textContent = bookDone ? '✓' : '2';
        if (hintB) {
          if (bookLocked) {
            hintB.textContent = 'Откроется после шага 1.';
          } else if (bookDone) {
            hintB.textContent =
              data.has_upcoming_booking || data.has_confirmed_booking
                ? 'Готово — запись в «Ближайших записях».'
                : 'Уже делали — шаг закрыт.';
          } else {
            hintB.textContent = 'Посмотрите, как работает расписание, клиент и напоминания.';
          }
        }
        /* Show two-path CTAs when pending; collapsed «Готово» when done */
        if (ctasWrap) ctasWrap.style.display = (bookDone || bookLocked) ? 'none' : 'flex';
        if (ctaBReal) ctaBReal.disabled = bookLocked || bookDone;
        if (ctaBSandbox) ctaBSandbox.disabled = bookLocked || bookDone;
        if (ctaBDone) ctaBDone.style.display = bookDone ? 'block' : 'none';

        applyHubLockedState();
        applyHubHero();
        refreshHubEmptyBookingsIfNeeded();
        syncPriorityActionFocus();
        syncHubWeekRhythmPanel();
        renderHubSummaryHints();
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
        var schedFlow = !!(onb && (onb.schedule_unlocked || onb.is_active));
        var msg;
        if (!onb) {
          msg =
            'Пока нет предстоящих записей. Сверху есть короткий блок «Первые шаги».';
        } else if (!schedFlow) {
          msg =
            'Сначала закройте шаг в блоке «Первые шаги» выше, затем откроются расписание и записи.';
        } else if (!onb.profile_complete && onb.tt_minimal_complete) {
          msg =
            'Сделайте первую запись кнопкой «Записать клиента» — это и есть быстрый старт.';
        } else if (onb.has_future_slots || onb.has_future_available_slots || onb.has_any_booking) {
          msg =
            'Нет предстоящих записей — когда появятся ближайшие занятия, они отобразятся здесь.';
        } else {
          msg = 'Нет предстоящих записей — добавьте слоты, чтобы клиенты могли выбрать время.';
        }
        var parts = ['<div class="hub-empty">' + escapeHtml(msg) + '</div>'];
        if (schedFlow) {
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
        if (!getInitData()) {
          strip.setAttribute('hidden', 'hidden');
          strip.style.display = 'none';
          /* Do not set hubRhythmHintsReady or hide rhythm skeleton: on iOS initData often arrives
           * late; marking ready here blocks showHubRhythmHintsSkeleton() when bootstrap runs. */
          syncHubWeekRhythmPanel();
          return;
        }
        fetch(apiUrlWithQuery('/trainer/onboarding/checklist'), { headers: headersJson() })
          .then(function(r) {
            return r.json().then(function(d) {
              return { ok: r.ok, data: d };
            });
          })
          .then(function(o) {
            if (!o.ok || !o.data) {
              hubRhythmHintsReady = true;
              syncHubWeekRhythmPanel();
              return;
            }
            applyOnboardingChecklist(o.data);
          })
          .catch(function() {
            hubRhythmHintsReady = true;
            syncHubWeekRhythmPanel();
          });
      }

      function wireOnboardingHub() {
        var ctaP = document.getElementById('onboardingCtaProfile');
        if (ctaP) {
          ctaP.onclick = function() {
            if (ctaP.disabled) return;
            if (ctaP.textContent === 'Статус') {
              navigateToWithHash('trainer-profile', 'moderation');
              return;
            }
            if (ctaP.textContent === 'Продолжить') {
              navigateTo('trainer-profile?onboarding=blocks');
              return;
            }
            navigateTo('trainer-profile?onboarding=blocks');
          };
        }
        var ctaBReal2 = document.getElementById('onboardingCtaBookingReal');
        if (ctaBReal2) {
          ctaBReal2.onclick = function() {
            if (ctaBReal2.disabled) return;
            hubQuickBookIsSandbox = false;
            ensureTrainerSectionsAccess(function() {
              openHubQuickBookClientFlowFirst();
            });
          };
        }
        var ctaBSandbox2 = document.getElementById('onboardingCtaBookingSandbox');
        if (ctaBSandbox2) {
          ctaBSandbox2.onclick = function() {
            if (ctaBSandbox2.disabled) return;
            hubQuickBookIsSandbox = true;
            ensureTrainerSectionsAccess(function() {
              openHubQuickBookClientFlowFirst();
            });
          };
        }
        var faq = document.getElementById('onboardingFaqBtn');
        if (faq) {
          faq.onclick = function() {
            if (hubOnboardingStripVisible()) {
              alertHubOnboardingStepOrder();
              return;
            }
            navigateTo('trainer-faq');
          };
        }
        document.addEventListener('visibilitychange', function() {
          if (document.hidden) return;
          if (hubVisibilityDebounceTimer) clearTimeout(hubVisibilityDebounceTimer);
          hubVisibilityDebounceTimer = setTimeout(function() {
            hubVisibilityDebounceTimer = null;
            if (!getInitData()) return;
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
                  renderBookings(data.bookings);
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
                  window.TrainerMiniAppGate.fetchAccess(getInitData()).catch(function() {
                    return null;
                  }),
                  fetchTrainerProfileForHub(),
                ]).then(function(results) {
                  var a = results[0];
                  var prof = results[1];
                  if (a) trainerAccessSnapshot = a;
                  mergeHubAccessFromProfilePayload(prof);
                  syncHubForceClientChatRelayFromTrainerAccess();
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
        if (!getInitData() || !canOpenTrainerSectionsSync()) {
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

      function rhythmHintActiveInHub(id) {
        return hubActiveRhythmHintIds.indexOf(id) !== -1;
      }

      /**
       * Fallback strip below stats — avoid repeating what hubRhythmSlot0/1 already shows.
       */
      function buildHubNextBestHint() {
        var onb = hubOnboardingData;
        if (!onb) return null;
        if (!onb.is_active) {
          if (onboardingBookingStepDone(onb)) {
            return {
              type: 'info',
              text: 'Следующий шаг: отправьте анкету на модерацию во вкладке «Статус».',
              href: 'trainer-profile',
            };
          }
          if (onb.tt_minimal_complete && (onb.schedule_unlocked || onb.is_active)) {
            return {
              type: 'info',
              text: 'Сделайте первую запись: нажмите «Записать клиента».',
              href: '__book_client__',
            };
          }
          return {
            type: 'info',
            text: 'Закройте шаг «Профиль по блокам», чтобы открыть запись клиентов.',
            href: 'trainer-profile?onboarding=blocks',
          };
        }
        if (onb.full_profile_complete === false) {
          return {
            type: 'info',
            text: 'Доработайте профиль для каталога: фото, описание, опыт и образование.',
            href: 'trainer-profile',
          };
        }

        var availThis = parseNonNegativeInt(onb.available_slots_this_week_count);
        var bookThis = parseNonNegativeInt(onb.bookings_this_week_count);
        var availNext = parseNonNegativeInt(onb.available_slots_next_week_count);
        var bookNext = parseNonNegativeInt(onb.bookings_next_week_count);
        var slotsNext = parseNonNegativeInt(onb.slots_next_week_count);
        var coverage = getHubSlotCoverage(onb);

        if (!rhythmHintActiveInHub('slots_this_week')) {
          if (availThis === 0 && bookThis < HUB_RHYTHM_BOOKINGS_LOW_THRESHOLD) {
            return {
              type: 'info',
              text: 'На этой неделе нет свободных слотов. Добавьте окна в расписании.',
              href: 'schedule-editor',
            };
          }
          if (coverage.thisWeekCount === 0) {
            return {
              type: 'info',
              text: 'На этой неделе нет слотов. Добавьте ближайшие окна, чтобы не терять записи.',
              href: 'schedule-editor',
            };
          }
        }

        var nextWeekGap =
          slotsNext === 0 || (availNext === 0 && bookNext < HUB_RHYTHM_BOOKINGS_LOW_THRESHOLD);
        if (!rhythmHintActiveInHub('slots_next_week')) {
          if (nextWeekGap) {
            return {
              type: 'info',
              text: 'На следующей неделе пока нет слотов. Обновите расписание заранее.',
              href: 'schedule-editor',
            };
          }
          if (coverage.nextWeekCount === 0) {
            return {
              type: 'info',
              text: 'На следующей неделе пока нет слотов. Обновите расписание заранее.',
              href: 'schedule-editor',
            };
          }
        }

        if (!rhythmHintActiveInHub('share_link') && hubOnlineBookingEnabled) {
          return {
            type: 'info',
            text: 'Поделитесь ссылкой на запись: клиенты смогут записываться сами.',
            href: '__share_link__',
          };
        }
        if (!onb.has_future_slots && !onb.has_future_available_slots) {
          return {
            type: 'info',
            text: 'Добавьте ближайшие слоты в расписание, чтобы не терять записи.',
            href: 'schedule-editor',
          };
        }
        return null;
      }

      function runHubHintAction(href) {
        var h = String(href || '').trim();
        if (!h) return;
        if (h === '__book_client__') {
          ensureTrainerSectionsAccess(function() {
            hubQuickBookIsSandbox = false;
            openHubQuickBookClientFlowFirst();
          });
          return;
        }
        if (h === '__share_link__') {
          ensureTrainerSectionsAccess(function() {
            var btnShare = document.getElementById('hubShareBookingLinkBtn');
            if (btnShare && !btnShare.hidden) btnShare.click();
            else hubToast('Ссылка появится после настройки города и услуг в профиле.');
          });
          return;
        }
        navigateTo(h);
      }

      /** Renders one next-best-action hint (plus urgent operational states). */
      /**
       * Lead Mode banner: shown when lifecycle.is_lead_mode === true.
       * Contract: presence stays, control is paywalled. Banner reframes silence as "still being found"
       * using real demand numbers (signals_recap), not a generic "subscription expired" alarm.
       */
      function renderHubLeadModeBanner() {
        var el = document.getElementById('hubLeadModeBanner');
        if (!el) return;
        var lc = hubLastLifecycle;
        if (!lc || !lc.is_lead_mode) {
          el.setAttribute('hidden', '');
          el.setAttribute('aria-hidden', 'true');
          return;
        }
        var recap = lc.signals_recap || {};
        var views = Number(recap.profile_views || 0) | 0;
        var clicks = Number(recap.contact_clicks || 0) | 0;
        var favorites = Number(recap.catalog_favorites || 0) | 0;
        var blocked = Number(recap.booking_attempts_blocked || 0) | 0;

        var signalsEl = document.getElementById('hubLeadBannerSignals');
        if (signalsEl) {
          signalsEl.removeAttribute('hidden');
          var viewsValueEl = document.getElementById('hubLeadSignalViews');
          var viewsLabelEl = document.getElementById('hubLeadSignalViewsLabel');
          if (viewsValueEl) viewsValueEl.textContent = String(views);
          if (viewsLabelEl) {
            viewsLabelEl.textContent = pluralRu(views, 'просмотр профиля', 'просмотра профиля', 'просмотров профиля');
          }
          var clicksValueEl = document.getElementById('hubLeadSignalClicks');
          var clicksLabelEl = document.getElementById('hubLeadSignalClicksLabel');
          if (clicksValueEl) clicksValueEl.textContent = String(clicks);
          if (clicksLabelEl) {
            clicksLabelEl.textContent = pluralRu(clicks, 'переход в Telegram', 'перехода в Telegram', 'переходов в Telegram');
          }
          var favValueEl = document.getElementById('hubLeadSignalFavorites');
          var favLabelEl = document.getElementById('hubLeadSignalFavoritesLabel');
          if (favValueEl) favValueEl.textContent = String(favorites);
          if (favLabelEl) {
            favLabelEl.textContent = pluralRu(
              favorites,
              'добавление в избранное',
              'добавления в избранное',
              'добавлений в избранное'
            );
          }
          var blockedItem = document.getElementById('hubLeadSignalBlockedItem');
          var blockedValueEl = document.getElementById('hubLeadSignalBlocked');
          var blockedLabelEl = document.getElementById('hubLeadSignalBlockedLabel');
          if (blocked > 0) {
            if (blockedItem) blockedItem.removeAttribute('hidden');
            if (blockedValueEl) blockedValueEl.textContent = String(blocked);
            if (blockedLabelEl) {
              blockedLabelEl.textContent = pluralRu(
                blocked,
                'не смог записаться',
                'не смогли записаться',
                'не смогли записаться'
              );
            }
          } else if (blockedItem) {
            blockedItem.setAttribute('hidden', '');
          }
        }

        var lossEl = document.getElementById('hubLeadBannerLoss');
        if (lossEl) {
          if (clicks > 0 || blocked > 0) {
            // Real loss numbers: prefer the strongest signal (blocked >= click >= view).
            var lossPrefix;
            if (blocked > 0) {
              lossPrefix = ruLeadLossBlockedPhrase(blocked);
            } else {
              lossPrefix = ruLeadLossTelegramPhrase(clicks);
            }
            lossEl.textContent =
              lossPrefix +
              ' — с онлайн-записью такие обращения попадают в календарь, а не остаются только в чате.';
            lossEl.removeAttribute('hidden');
          } else {
            lossEl.setAttribute('hidden', '');
          }
        }

        var ctaEl = document.getElementById('hubLeadBannerCta');
        if (ctaEl && !ctaEl.__leadCtaWired) {
          ctaEl.__leadCtaWired = true;
          ctaEl.addEventListener('click', function() {
            try {
              window.location.assign('/webapp/trainer-subscription?from=lead_mode');
            } catch (e) {
              window.location.href = '/webapp/trainer-subscription';
            }
          });
        }

        el.removeAttribute('hidden');
        el.removeAttribute('aria-hidden');
      }

      function applyHubLifecycle(payload) {
        if (!payload || typeof payload !== 'object') {
          return;
        }
        hubLastLifecycle = payload;
        renderHubLeadModeBanner();
      }

      /** Fallback path: bootstrap didn't include lifecycle (legacy, partial error) — fetch standalone. */
      function loadTrainerLifecycle() {
        if (!getInitData()) return Promise.resolve(null);
        return fetch(apiUrlWithQuery('/trainer/lifecycle'), { headers: headersJson() })
          .then(function(r) {
            if (!r.ok) return null;
            return r.json();
          })
          .then(function(data) {
            if (data) applyHubLifecycle(data);
            return data;
          })
          .catch(function() {
            return null;
          });
      }

      function renderHubSummaryHints() {
        applyHubRhythmResolver();
        var el = document.getElementById('hubSummaryHints');
        if (!el) {
          return;
        }
        if (!HUB_NEXT_BEST_HINT_UI_ENABLED) {
          el.setAttribute('hidden', '');
          el.innerHTML = '';
          el.setAttribute('aria-hidden', 'true');
          return;
        }
        el.removeAttribute('aria-hidden');
        if (!getInitData()) {
          el.setAttribute('hidden', '');
          el.innerHTML = '';
          return;
        }
        var hint = null;
        if (hubLastPendingCount > 0) {
          hint = {
            type: 'urgent',
            text:
              hubLastPendingCount +
              ' ' +
              pluralRu(
                hubLastPendingCount,
                'запись требует подтверждения',
                'записи требуют подтверждения',
                'записей требуют подтверждения'
              ),
            href: 'schedule-editor',
          };
        } else if (hubRequestsStatReady && hubLastNewRequestsCount > 0) {
          hint = {
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
          };
        } else {
          hint = buildHubNextBestHint();
        }
        if (!hint) {
          el.setAttribute('hidden', '');
          el.innerHTML = '';
          return;
        }
        var mod = hint.type === 'urgent' ? 'urgent' : 'info';
        el.removeAttribute('hidden');
        el.innerHTML =
          '<button type="button" class="hub-summary-hint hub-summary-hint--' +
          mod +
          '" data-hub-hint-href="' +
          escapeHtml(hint.href || '') +
          '">' +
          '<span class="hub-summary-hint__text">' +
          escapeHtml(hint.text || '') +
          '</span>' +
          '<span class="hub-summary-hint__chev" aria-hidden="true">›</span>' +
          '</button>';
        var btn = el.querySelector('[data-hub-hint-href]');
        if (!btn) {
          return;
        }
        btn.onclick = function() {
          runHubHintAction(btn.getAttribute('data-hub-hint-href'));
        };
      }

      function formatHubMoneyCents(cents) {
        var n = Number(cents);
        var numStr;
        if (!isFinite(n) || n < 0) {
          numStr = '0';
        } else {
          var v = n / 100;
          numStr = v.toFixed(v % 1 === 0 ? 0 : 2);
        }
        return numStr + ' BYN';
      }

      /** Loads accrual MTD (sessions + pass + cert sales); updates hubMtdRevenueText and hero. */
      function fetchHubMtdRevenue() {
        if (!getInitData()) return;
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

      /**
       * Hub summary tiles: «N всего» / «M осталось».
       * When nothing has started yet, N === M is normal — still show both lines (users expect «осталось»).
       */
      function hubFillDualStatValue(el, cardEl, total, remaining, titleText) {
        if (!el) return;
        if (total <= 0) {
          el.classList.remove('hub-stat-value--dual');
          el.textContent = '0';
          if (cardEl) cardEl.removeAttribute('title');
          return;
        }
        var rem =
          typeof remaining === 'number' && remaining >= 0 && !isNaN(remaining) ? remaining : 0;
        el.classList.add('hub-stat-value--dual');
        el.innerHTML =
          '<span class="hub-stat-dual-line"><span class="hub-stat-dual-num">' +
          String(total) +
          '</span> всего</span>' +
          '<span class="hub-stat-dual-line hub-stat-dual-line--sub"><span class="hub-stat-dual-num">' +
          String(rem) +
          '</span> осталось</span>';
        if (cardEl && titleText) cardEl.setAttribute('title', titleText);
      }

      function setStats(todayTotal, weekTotal, todayRemaining, weekRemaining) {
        var wrap = document.getElementById('hubStats');
        var todayValue = document.getElementById('statTodayValue');
        var weekValue = document.getElementById('statWeekValue');
        var revenueValue = document.getElementById('statRevenueValue');

        if (!wrap || !todayValue || !weekValue || !revenueValue) {
          renderHubSummaryHints();
          return;
        }

        if (!getInitData()) {
          wrap.setAttribute('aria-hidden', 'true');
          wrap.style.display = 'none';
          renderHubSummaryHints();
          return;
        }

        wrap.style.display = 'grid';
        wrap.setAttribute('aria-hidden', 'false');

        var todayCard = document.getElementById('statToday');
        var weekCard = document.getElementById('statWeek');
        hubFillDualStatValue(
          todayValue,
          todayCard,
          todayTotal,
          todayRemaining,
          'Всего занятий на сегодня (минское время). «Осталось» — слот ещё не начался; идущее занятие не считается.'
        );
        hubFillDualStatValue(
          weekValue,
          weekCard,
          weekTotal,
          weekRemaining,
          'Календарная неделя с понедельника по воскресенье (Минск). «Осталось» — слот ещё не начался; идущее занятие не считается.'
        );

        revenueValue.textContent =
          hubMtdRevenueText != null && hubMtdRevenueText !== '' ? hubMtdRevenueText : '—';

        if (todayCard) {
          if (todayTotal > 0) {
            todayCard.classList.add('stat-highlight');
          } else {
            todayCard.classList.remove('stat-highlight');
          }
        }

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

        if (!getInitData()) {
          title.textContent = 'Войдите через бота';
          subtitle.textContent = 'Откройте экран из бота тренера — подтянутся записи и быстрый доступ к разделам.';
          setStats(0, 0, 0, 0);
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
          setStats(count, weekCount || 0, hubLastTodayRemaining, hubLastWeekRemaining);
          syncHubHeroScheduleClick();
          return;
        }

        var onb = hubOnboardingData;
        if (!onb) {
          title.textContent = 'Ваш день';
          subtitle.textContent = 'Предстоящих записей на сегодня нет.';
          setStats(0, hubLastWeekCount || 0, 0, hubLastWeekRemaining || 0);
          syncHubHeroScheduleClick();
          return;
        }

        if (!onb.profile_complete) {
          if (onb.tt_minimal_complete && (onb.schedule_unlocked || onb.is_active)) {
            title.textContent = 'Сделайте первую запись';
            subtitle.textContent =
              'Выберите «Записать реального клиента» или «Попробовать на примере» — запись появится прямо здесь.';
            setStats(0, hubLastWeekCount || 0, 0, hubLastWeekRemaining || 0);
            syncHubHeroScheduleClick();
            return;
          }
          title.textContent = 'Сначала анкета';
          subtitle.textContent =
            'Закройте шаг в блоке «Первые шаги» выше (кнопка «Продолжить»), затем сразу делайте первую запись.';
          setStats(0, hubLastWeekCount || 0, 0, hubLastWeekRemaining || 0);
          syncHubHeroScheduleClick();
          return;
        }

        if (!onb.is_active) {
          title.textContent = 'Скоро полный доступ';
          subtitle.textContent =
            'В «Первые шаги» видно статус: при одобрении анкеты откроются заявки и полный доступ. Расписание уже можно вести.';
          setStats(0, hubLastWeekCount || 0, 0, hubLastWeekRemaining || 0);
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
        setStats(0, hubLastWeekCount || 0, 0, hubLastWeekRemaining || 0);
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

      /** Past-tense phrase for lead-mode loss line (Russian number + noun + verb agreement). */
      function ruLeadLossTelegramPhrase(clicks) {
        var n = Number(clicks) | 0;
        var noun = pluralRu(n, 'клиент', 'клиента', 'клиентов');
        var mm = n % 100;
        var m = n % 10;
        // contact_clicks = CTA /r/tg redirect — opens Telegram, not proof a message was sent.
        var verb = m === 1 && mm !== 11 ? 'перешёл' : 'перешли';
        return n + ' ' + noun + ' ' + verb + ' в Telegram';
      }

      function ruLeadLossBlockedPhrase(blocked) {
        var n = Number(blocked) | 0;
        var noun = pluralRu(n, 'клиент', 'клиента', 'клиентов');
        var mm = n % 100;
        var m = n % 10;
        var verb = m === 1 && mm !== 11 ? 'пытался записаться' : 'пытались записаться';
        return n + ' ' + noun + ' ' + verb;
      }

      function openTelegramDmMiniApp(username, telegramId) {
        if (typeof window.openTelegramChatFromMiniApp === 'function') {
          return window.openTelegramChatFromMiniApp({
            username: username,
            telegramId: telegramId,
          });
        }
        return false;
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

      function hubSandboxPillHtml(b) {
        if (!b || !b.is_sandbox) return '';
        return (
          '<span class="hub-sandbox-pill" role="status" aria-label="Тестовая запись">тест</span>'
        );
      }

      function syncHubMyServicesAccentMap(servicesList) {
        (servicesList || []).forEach(function(s) {
          if (s == null || s.id == null) return;
          var slug = s.ui_accent != null ? String(s.ui_accent).trim().toLowerCase() : '';
          if (!slug || HUB_SERVICE_UI_ACCENT_SLUGS.indexOf(slug) < 0) {
            delete hubMyServicesAccentByServiceId[s.id];
            return;
          }
          hubMyServicesAccentByServiceId[s.id] = slug;
        });
      }

      function hubBookingServiceAccentSlug(serviceId) {
        var sid = serviceId != null ? parseInt(String(serviceId), 10) : NaN;
        if (isNaN(sid)) return '';
        var slug = hubMyServicesAccentByServiceId[sid];
        if (!slug || HUB_SERVICE_UI_ACCENT_SLUGS.indexOf(slug) < 0) return '';
        return slug;
      }

      var HUB_SERVICE_SHORT_ALIASES = {
        'персональная тренировка': 'Персоналка',
        'персональная': 'Персоналка',
        'индивидуальная тренировка': 'Индив',
        'групповая тренировка': 'Группа',
        'силовая тренировка': 'Силовая',
        'реабилитационная тренировка': 'Реабил',
        'растяжка': 'Растяжка',
      };

      function hubServiceShortLabel(serviceName) {
        var raw = serviceName == null ? '' : String(serviceName).trim();
        if (!raw) return '';
        var normalized = raw
          .toLowerCase()
          .replace(/[ё]/g, 'е')
          .replace(/[^a-zA-Zа-яА-Я0-9\s-]/g, ' ')
          .replace(/\s+/g, ' ')
          .trim();
        if (!normalized) return '';
        if (HUB_SERVICE_SHORT_ALIASES[normalized]) return HUB_SERVICE_SHORT_ALIASES[normalized];
        var words = normalized.split(/\s+/).filter(Boolean);
        var base = words.slice(0, 2).join(' ');
        if (!base) return '';
        base = base.charAt(0).toUpperCase() + base.slice(1);
        if (base.length <= 14) return base;
        return base.slice(0, 13).trimEnd() + '…';
      }

      function hubServiceBadgeHtml(serviceId, serviceName) {
        var label = hubServiceShortLabel(serviceName);
        if (!label) return '';
        var slug = hubBookingServiceAccentSlug(serviceId);
        var slugCls = slug ? ' svc-badge--' + slug : '';
        return (
          '<span class="svc-badge' + slugCls + '" role="status">' +
            '<span class="svc-badge-dot" aria-hidden="true"></span>' +
            '<span class="svc-badge-label">' + escapeHtml(label) + '</span>' +
          '</span>'
        );
      }

      /** Reads QA flag from last server access snapshot (bootstrap / MiniAppGate.fetchAccess when present). */
      function syncHubForceClientChatRelayFromTrainerAccess() {
        hubForceClientChatRelay = !!(trainerAccessSnapshot && trainerAccessSnapshot.force_client_chat_relay);
        if (typeof window !== 'undefined') window.TRAINER_HUB_FORCE_CLIENT_CHAT_RELAY = hubForceClientChatRelay;
      }

      /**
       * Individual hub row: DM / relay button — must not depend solely on TrainerRelayHelpers (CDN cache / load order).
       * Mirrors TrainerRelayHelpers.relayEligible + username-based direct DM.
       */
      function hubTrainerContactEligibleForBooking(b) {
        if (!b || b.is_sandbox) return null;
        var cap = parseInt(String(b.slot_capacity != null ? b.slot_capacity : '1'), 10);
        if (isNaN(cap) || cap < 1) cap = 1;
        if (cap > 1) return null;
        var cid = b.client_id;
        if (cid == null || cid === '') return null;
        var tid = b.client_telegram_id;
        if (tid == null || tid === '') return null;
        var un = String(b.client_telegram_username || '')
          .replace(/^@/, '')
          .trim();
        return {
          clientId: cid,
          telegramId: tid,
          telegramUsername: un,
        };
      }

      function hubTrainerContactUseRelay(contact) {
        if (!contact) return false;
        if (hubForceClientChatRelay) return true;
        return !contact.telegramUsername;
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
        var serviceBadge = hubServiceBadgeHtml(b.service_id, b.services_str);

        /* Multi-participant slot: meter + modal (same slot_id). Capacity alone (e.g. 2 seats, 1 client) stays a normal row — not «group training». */
        if (cap > 1) {
          var occ = parseInt(String(b.slot_active_bookings != null ? b.slot_active_bookings : ''), 10);
          if (isNaN(occ) || occ < 0) occ = 1;
          occ = Math.min(occ, cap);
          if (occ > 1) {
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
          var badgeRow =
            serviceBadge !== ''
              ? '<div class="slot-service-badge-row">' + serviceBadge + '</div>'
              : '';
          return (
            '<div class="slot-row slot-booked-click slot-group-hub-preview ' + rowMod + '" data-bid="' + String(b.id) + '" data-slot-id="' + String(b.slot_id != null ? b.slot_id : '') + '" data-slot-date="' + escapeHtml(b.slot_date || '') + '" role="button" tabindex="0">' +
              '<div class="slot-row-left">' +
                '<div class="hub-slot-time-row">' +
                  '<span class="slot-time">' + escapeHtml(timeRange) + '</span>' +
                  hubSessionNowPillHtml(b) + hubSandboxPillHtml(b) + hubProblemReportPillHtml(b) +
                  '</div>' +
                badgeRow +
                metaHtml +
                '<div class="slot-group-meter-wrap" aria-hidden="true"><div class="slot-group-meter-fill" style="width:' + pct + '%"></div></div>' +
              '</div>' +
              '<div class="slot-meta slot-meta--group">' +
                '<span class="slot-group-chip">' + occ + '/' + cap + '</span>' +
                (b.is_sandbox ? '<span class="hub-sandbox-pill hub-sandbox-pill--inline" role="status">тест</span>' : '') +
                spotsPill +
                pendingExtra +
              '</div>' +
            '</div>'
          );
          }
        }

        var arena = (b.arenas_str || '').trim();
        var venueInner = arena
          ? escapeHtml(arena)
          : '<span class="venue-muted">не указано</span>';
        var msgBtn = '';
        var hubContact = hubTrainerContactEligibleForBooking(b);
        if (hubContact) {
          var useRelay = hubTrainerContactUseRelay(hubContact);
          /* data-client-* needed for QA flag TRAINER_WEBAPP_FORCE_CLIENT_CHAT_RELAY: chrome delegates before HTML is re-built for relay-marked buttons. */
          var clientRelayDataAttrs =
            ' data-client-id="' +
            escapeHtml(String(hubContact.clientId)) +
            '" data-client-label="' +
            escapeHtml(clientLabel(b)) +
            '" data-client-phone="' +
            escapeHtml(String((b.client_phone || '').trim())) +
            '"';
          var relayAttr = useRelay ? ' data-hub-relay="1"' + clientRelayDataAttrs : clientRelayDataAttrs;
          var tip = useRelay
            ? 'Сообщение через бота клиента (ответ — в бот тренера)'
            : 'Написать клиенту в Telegram';
          msgBtn =
            '<button type="button" class="hub-slot-msg' +
            (useRelay ? ' hub-slot-msg--relay' : '') +
            '" data-hub-dm="trainer"' +
            (b.id != null && b.id !== ''
              ? ' data-booking-id="' + escapeHtml(String(b.id)) + '"'
              : '') +
            relayAttr +
            ' data-dm-un="' + escapeHtml(hubContact.telegramUsername || '') + '"' +
            ' data-dm-tid="' + escapeHtml(String(hubContact.telegramId)) + '"' +
            ' aria-label="' +
            escapeHtml(tip) +
            '" title="' +
            escapeHtml(tip) +
            '">' +
            '<svg class="hub-slot-msg-icon" viewBox="0 0 24 24" aria-hidden="true">' +
            '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>' +
            '</svg>' +
            '</button>';
        }
        var badgeRowSingle =
          serviceBadge !== ''
            ? '<div class="slot-service-badge-row">' + serviceBadge + '</div>'
            : '';
        return (
          '<div class="slot-row slot-booked-click ' + rowMod + '" data-bid="' + String(b.id) + '">' +
            '<div class="slot-row-left">' +
                '<div class="hub-slot-time-row">' +
                  '<span class="slot-time">' + escapeHtml(timeRange) + '</span>' +
                  hubSessionNowPillHtml(b) + hubSandboxPillHtml(b) + hubProblemReportPillHtml(b) +
                  '</div>' +
              badgeRowSingle +
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
              var sandboxPill = bk.is_sandbox
                ? ' <span class="hub-sandbox-pill hub-sandbox-pill--inline" role="status">тест</span>'
                : '';
              var bid = parseInt(bk.booking_id, 10);
              var btn = document.createElement('button');
              btn.type = 'button';
              btn.className = 'group-slot-row';
              btn.innerHTML =
                '<span><span class="g-name">' +
                escapeHtml(String(bk.client_preview || 'Клиент')) +
                sandboxPill +
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
        if (typeof window.extractNational375Digits === 'function') {
          var nd = window.extractNational375Digits(raw);
          if (nd.length === 9) return '+375' + nd;
        }
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

      function hideHubInlineToast() {
        var el = document.getElementById('hubInlineToast');
        if (!el) return;
        el.classList.remove('hub-inline-toast--show');
        el.setAttribute('hidden', 'hidden');
        if (hubInlineToastTimer) {
          clearTimeout(hubInlineToastTimer);
          hubInlineToastTimer = null;
        }
        hubInlineToastActionHandler = null;
      }

      function showHubInlineToast(title, text, opts) {
        var el = document.getElementById('hubInlineToast');
        var titleEl = document.getElementById('hubInlineToastTitle');
        var textEl = document.getElementById('hubInlineToastText');
        var actionBtn = document.getElementById('hubInlineToastAction');
        var closeBtn = document.getElementById('hubInlineToastClose');
        if (!el || !titleEl || !textEl || !actionBtn || !closeBtn) {
          hubToast([title, text].filter(Boolean).join('\n'));
          return;
        }
        opts = opts || {};
        titleEl.textContent = title || 'Готово';
        textEl.textContent = text || '';
        el.classList.remove('hub-inline-toast--success', 'hub-inline-toast--warning');
        el.classList.add(opts.kind === 'warning' ? 'hub-inline-toast--warning' : 'hub-inline-toast--success');

        if (opts.actionLabel && typeof opts.onAction === 'function') {
          actionBtn.hidden = false;
          actionBtn.textContent = opts.actionLabel;
          hubInlineToastActionHandler = opts.onAction;
        } else {
          actionBtn.hidden = true;
          actionBtn.textContent = '';
          hubInlineToastActionHandler = null;
        }
        actionBtn.onclick = function() {
          if (typeof hubInlineToastActionHandler === 'function') hubInlineToastActionHandler();
          hideHubInlineToast();
        };
        closeBtn.onclick = hideHubInlineToast;

        if (hubInlineToastTimer) {
          clearTimeout(hubInlineToastTimer);
          hubInlineToastTimer = null;
        }
        el.removeAttribute('hidden');
        el.classList.add('hub-inline-toast--show');
        hubInlineToastTimer = setTimeout(hideHubInlineToast, Math.max(1800, Number(opts.durationMs) || 4200));
      }

      function stashHubPendingBookingHighlight(bookingId) {
        var bid = Number(bookingId);
        hubPendingHighlightBookingId = !isNaN(bid) && bid > 0 ? bid : null;
      }

      function applyHubPendingBookingHighlight() {
        if (hubPendingHighlightBookingId == null) return;
        var selector = '.slot-row.slot-booked-click[data-bid="' + String(hubPendingHighlightBookingId) + '"]';
        var row = document.querySelector(selector);
        if (!row) return;
        row.classList.remove('hub-booking-row--new');
        void row.offsetWidth; // restart animation if the same row was highlighted previously
        row.classList.add('hub-booking-row--new');
        setTimeout(function() {
          row.classList.remove('hub-booking-row--new');
        }, 2200);
        hubPendingHighlightBookingId = null;
      }

      function presentHubBookingSuccess(apiBooking, fallbackText) {
        var b = apiBooking || {};
        var bookingId = b.booking_id != null ? Number(b.booking_id) : null;
        if (bookingId && !isNaN(bookingId)) stashHubPendingBookingHighlight(bookingId);
        showHubInlineToast(
          'Запись создана',
          fallbackText || 'Клиент добавлен в расписание. Смотрите блок «Ближайшие записи».',
          {
            kind: 'success',
            durationMs: 5000,
          }
        );
      }

      var hubBookSlotId = null;
      var hubBookServiceId = null;
      /** Quick-book only: chosen catalog tier (POST service_price_variant_id). */
      var hubBookPriceVariantId = null;
      /** Consumed on next multi-tier sync after booking-defaults (must not run before service step is open). */
      var hubBookPendingTierPresetVariantId = null;
      var hubBookPendingTierPresetKind = null;
      var hubBookQuickPayload = null;
      var hubBookQuickServices = [];
      /** service_id (catalog id) → accent slug; filled from GET /trainer/my-services + quick-book prepare. */
      var hubMyServicesAccentByServiceId = {};
      var hubMyServicesAccentPrefetchInFlight = false;
      var hubMyServicesAccentPrefetchDone = false;
      /** Last bookings payload so a late my-services fetch can re-run renderBookings. */
      var hubLastBookingsPayloadForAccentRefetch = null;
      var HUB_SERVICE_UI_ACCENT_SLUGS = ['sky', 'amber', 'emerald', 'violet', 'rose', 'slate'];
      var hubBookTrainerArenas = [];
      /** Selected arena for quick-book (trainer hub); preset grid + POST /trainer/booking/quick. */
      var hubBookArenaId = null;
      var hubQuickBookScheduleGrid = null;
      var hubQuickBookSlotsForDay = [];
      /** ISO date for which hub quick-book loaded `/schedule` slots; paired with `hubQuickBookSlotsArenaKey`. */
      var hubQuickBookSlotsIsoDate = null;
      var hubQuickBookSlotsArenaKey = null;
      /** Monotonic counter to ignore stale `/schedule` responses when the user changes date quickly. */
      var hubQuickBookScheduleFetchGen = 0;
      var hubQuickBookRefreshTimer = null;
      var hubBookSlotWhenLabel = '';
      var hubBookPendingClientId = null;
      var hubBookPendingClientName = '';
      /** Selected roster row: must match POST /trainer/booking/quick ``is_sandbox`` vs ``clients.is_sandbox``. */
      var hubBookPendingClientIsSandbox = false;
      /** Prevents double-start of async booking (double-tap «Далее» / «Записать»). */
      var hubBookQuickChainInFlight = false;
      var hubBookConfirmPrimaryLabelCached = null;
      /** Incremented on each open «Записать клиента» — stale fetches must not close a newer session. */
      var hubQuickBookPrepareGen = 0;
      var HUB_QB_PREPARE_MAX_ATTEMPTS = 6;
      /** True when hub quick-book started as client → service → datetime (not group-slot booking). */
      var hubBookClientFirstQuickMode = false;
      /** When client-first flow is showing the service/tariff step (tiers UI allowed without hubBookQuickPayload). */
      var hubBookClientFirstServiceStepOpen = false;
      /** How we entered client-first service step: from new-client form vs from existing-client list. */
      var hubBookClientFirstServiceFromNew = false;
      /** From last GET /trainer/clients (or prefetch). True ⇒ show «Выбрать из списка» immediately; else probing until fetch. */
      var hubTrainerHasClientsCache = null;
      var HUB_BOOK_OPT_EXISTING_HINT = 'Существующий клиент';
      /** True while quick-book flow is onboarding «Попробовать на примере» (POST .../quick is_sandbox). */
      var hubQuickBookIsSandbox = false;
      /** Client-first quick book (hub): hide legacy pair «Выбрать клиента» / «Создать» — landing is search list + chip «Новый клиент». */
      var hubQuickBookHideLegacyClientChoice = false;
      /** Default subtitle under «Записать клиента»; restored after sandbox flow. */
      var hubBookChoiceLeadDefault = null;
      function ensureHubBookChoiceLeadDefault() {
        if (hubBookChoiceLeadDefault != null) return;
        var lead = document.querySelector('#hubBookStepChoice .book-choice-lead');
        hubBookChoiceLeadDefault = lead
          ? String(lead.textContent || '').trim()
          : 'Кого записать на занятие?';
      }
      /** Prefill new-client fields for sandbox TTV; Belarus test MSISDN passes +375 validation. */
      function applyHubSandboxNewClientPrefill() {
        var phoneEl = document.getElementById('hubBookNewPhone');
        var firstEl = document.getElementById('hubBookNewFirstName');
        var lastEl = document.getElementById('hubBookNewLastName');
        if (firstEl) firstEl.value = 'Александр';
        if (lastEl) lastEl.value = 'К.';
        if (phoneEl) {
          phoneEl.value = '291111111';
          try {
            if (typeof window.applyNational375MaskedToInput === 'function') {
              window.applyNational375MaskedToInput(phoneEl);
            }
          } catch (eFmt) {}
        }
      }

      function prefetchHubTrainerClientsPresence() {
        if (!getInitData()) return;
        if (
          trainerAccessSnapshot &&
          window.TrainerMiniAppGate &&
          !window.TrainerMiniAppGate.isActive(trainerAccessSnapshot)
        ) {
          return;
        }
        fetch(apiUrlWithQuery('/trainer/clients'), { headers: headersJson(), cache: 'no-store' })
          .then(function(r) {
            return r.ok ? r.json() : null;
          })
          .then(function(data) {
            if (!data || !Array.isArray(data.clients)) return;
            hubTrainerHasClientsCache = data.clients.length > 0;
          })
          .catch(function() {});
      }

      function hubApplyTrainerHasClientsFromPayload(clientsPayload) {
        var list = (clientsPayload && clientsPayload.clients) || [];
        hubTrainerHasClientsCache = list.length > 0;
        return hubTrainerHasClientsCache;
      }

      function setHubBookOptExistingVisible(show) {
        var btn = document.getElementById('hubBookOptExisting');
        if (!btn) return;
        btn.classList.remove('hub-book-opt-existing--probing');
        btn.disabled = false;
        btn.removeAttribute('aria-busy');
        var hint = btn.querySelector('.btn-book-option-hint');
        if (hint) hint.textContent = HUB_BOOK_OPT_EXISTING_HINT;
        btn.style.display = show ? '' : 'none';
        btn.setAttribute('aria-hidden', show ? 'false' : 'true');
      }

      /**
       * Reserve layout for both choice rows while hidden (visibility) so WebKit/iOS does not paint
       * «Добавить нового» before «Выбрать из списка».
       */
      function primeHubBookChoicePairLayout() {
        var exBtn = document.getElementById('hubBookOptExisting');
        var newBtn = document.getElementById('hubBookOptNew');
        if (exBtn) {
          exBtn.style.display = '';
          exBtn.setAttribute('aria-hidden', 'false');
        }
        if (newBtn) {
          newBtn.style.display = '';
          newBtn.setAttribute('aria-hidden', 'false');
        }
      }

      function setHubBookChoicePairPending(on) {
        var w = document.getElementById('hubBookChoiceActions');
        if (!w) return;
        w.classList.toggle('hub-book-choice-actions--pending', !!on);
      }

      function clearHubBookChoiceQuickUi() {
        var sk = document.getElementById('hubBookChoiceSkel');
        if (sk) {
          sk.hidden = true;
          sk.setAttribute('aria-hidden', 'true');
          sk.removeAttribute('role');
        }
        var newBtn = document.getElementById('hubBookOptNew');
        if (newBtn) {
          newBtn.disabled = false;
          newBtn.classList.remove('hub-book-opt--awaiting-data');
        }
        var exBtn = document.getElementById('hubBookOptExisting');
        if (exBtn) {
          exBtn.disabled = false;
          exBtn.classList.remove('hub-book-opt--awaiting-data');
        }
        setHubBookChoicePairPending(false);
      }

      function setHubBookChoiceQuickLoading(on) {
        var sk = document.getElementById('hubBookChoiceSkel');
        var newBtn = document.getElementById('hubBookOptNew');
        var exBtn = document.getElementById('hubBookOptExisting');
        if (sk) {
          sk.hidden = !on;
          sk.setAttribute('aria-hidden', on ? 'false' : 'true');
          if (on) sk.setAttribute('role', 'status');
          else sk.removeAttribute('role');
          var cf = sk.querySelector('.hub-book-choice-skel-clientfirst');
          var sb = sk.querySelector('.hub-book-choice-skel-sandbox');
          if (cf && sb) {
            if (!on) {
              cf.setAttribute('hidden', 'hidden');
              cf.setAttribute('aria-hidden', 'true');
              sb.setAttribute('hidden', 'hidden');
              sb.setAttribute('aria-hidden', 'true');
            } else if (hubQuickBookIsSandbox) {
              cf.setAttribute('hidden', 'hidden');
              cf.setAttribute('aria-hidden', 'true');
              sb.removeAttribute('hidden');
              sb.setAttribute('aria-hidden', 'false');
            } else {
              sb.setAttribute('hidden', 'hidden');
              sb.setAttribute('aria-hidden', 'true');
              cf.removeAttribute('hidden');
              cf.setAttribute('aria-hidden', 'false');
            }
          }
          var nc = sk.querySelector('.hub-book-choice-skel-newcard');
          if (nc) {
            var showNew = !!on && !!hubQuickBookIsSandbox;
            nc.hidden = !showNew;
            nc.setAttribute('aria-hidden', showNew ? 'false' : 'true');
          }
        }
        if (newBtn) {
          newBtn.disabled = !!on;
          newBtn.classList.toggle('hub-book-opt--awaiting-data', !!on);
        }
        if (exBtn) {
          if (on) {
            exBtn.disabled = true;
            exBtn.style.display = '';
            exBtn.setAttribute('aria-hidden', 'false');
            exBtn.classList.remove('hub-book-opt-existing--probing');
            exBtn.classList.add('hub-book-opt--awaiting-data');
            var hint = exBtn.querySelector('.btn-book-option-hint');
            if (hint) hint.textContent = HUB_BOOK_OPT_EXISTING_HINT;
          } else {
            exBtn.classList.remove('hub-book-opt--awaiting-data');
          }
        }
      }

      /** Disables confirm modal actions and shows progress (blocks double-submit to API). */
      function setHubBookConfirmSubmitting(on) {
        var ov = document.getElementById('hubModalBookGroupConfirm');
        var yes = document.getElementById('hubBookConfirmYes');
        var no = document.getElementById('hubBookConfirmNo');
        if (!yes || !no) return;
        if (on) {
          if (hubBookConfirmPrimaryLabelCached == null) {
            hubBookConfirmPrimaryLabelCached = (yes.textContent || '').trim() || 'Записать';
          }
          yes.textContent = 'Записываем…';
          yes.disabled = true;
          no.disabled = true;
          yes.setAttribute('aria-busy', 'true');
          if (ov) {
            ov.setAttribute('aria-busy', 'true');
            ov.classList.add('hub-book-confirm--busy');
          }
        } else {
          yes.textContent = hubBookConfirmPrimaryLabelCached || 'Записать';
          yes.disabled = false;
          no.disabled = false;
          yes.removeAttribute('aria-busy');
          if (ov) {
            ov.removeAttribute('aria-busy');
            ov.classList.remove('hub-book-confirm--busy');
          }
        }
      }

      function setHubGlobalBookingBusy(on) {
        var id = 'hubGlobalBookingBusy';
        var el = document.getElementById(id);
        if (on) {
          if (!el) {
            el = document.createElement('div');
            el.id = id;
            el.className = 'hub-global-booking-busy';
            el.setAttribute('role', 'status');
            el.setAttribute('aria-live', 'polite');
            el.innerHTML =
              '<span class="hub-global-booking-busy__spinner" aria-hidden="true"></span>' +
              '<span class="hub-global-booking-busy__text">Создаём запись…</span>';
            document.body.appendChild(el);
          }
          el.hidden = false;
        } else if (el) {
          el.hidden = true;
        }
      }

      function closeHubBookGroupModals() {
        var m = document.getElementById('hubModalBookGroupSlot');
        var c = document.getElementById('hubModalBookGroupConfirm');
        clearHubBookChoiceQuickUi();
        setHubBookConfirmSubmitting(false);
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
        hubBookPendingClientIsSandbox = false;
        hubQuickBookHideLegacyClientChoice = false;
        hubDockBookStepNewUnderModalChrome();
      }

      /** Default DOM: `#hubBookStepNew` sits under choice/existing branches, above cancel (standalone new-client step). */
      function hubDockBookStepNewUnderModalChrome() {
        var slotOv = document.getElementById('hubModalBookGroupSlot');
        if (!slotOv) return;
        var modal =
          slotOv.querySelector('.modal.book-flow-modal.hub-book-modal') ||
          slotOv.querySelector('.modal.book-flow-modal');
        var nw = document.getElementById('hubBookStepNew');
        var cancelBtn = document.getElementById('hubBookCancel');
        var backNew = document.getElementById('hubBookBackFromNew');
        if (!modal || !nw || !cancelBtn) return;
        if (nw.parentNode !== modal) {
          modal.insertBefore(nw, cancelBtn);
        }
        if (backNew) backNew.style.display = '';
      }

      /**
       * Onboarding sandbox: tuck phone/name block inside service step above «Далее» — one coherent scroll pane
       * (nested modal columns were collapsing together on narrow webviews).
       */
      function hubEmbedSandboxBookStepNewBeforeQuickNext() {
        if (!hubQuickBookIsSandbox || !hubBookClientFirstQuickMode) return;
        var choice = document.getElementById('hubBookStepChoice');
        var nw = document.getElementById('hubBookStepNew');
        var nextBtn = document.getElementById('hubBookQuickServiceNext');
        var backNew = document.getElementById('hubBookBackFromNew');
        if (!choice || !nw || !nextBtn) return;
        if (nw.parentNode !== choice) {
          choice.insertBefore(nw, nextBtn);
        }
        if (backNew) backNew.style.display = 'none';
      }

      function resetHubBookSlotState() {
        hubBookSlotId = null;
        hubBookServiceId = null;
        hubBookPriceVariantId = null;
        hubBookPendingTierPresetVariantId = null;
        hubBookPendingTierPresetKind = null;
        hubBookQuickServices = [];
        hubQuickBookSlotsForDay = [];
        hubQuickBookSlotsIsoDate = null;
        hubQuickBookSlotsArenaKey = null;
        hubQuickBookScheduleFetchGen += 1;
        hubBookSlotWhenLabel = '';
        hubQuickBookIsSandbox = false;
        hubQuickBookHideLegacyClientChoice = false;
        hubBookClientFirstQuickMode = false;
        hubBookClientFirstServiceStepOpen = false;
        hubBookClientFirstServiceFromNew = false;
        hubBookTrainerArenas = [];
        hubBookArenaId = null;
        hubSyncClientFirstQuickServiceChrome();
        ensureHubBookChoiceLeadDefault();
        var leadR = document.querySelector('#hubBookStepChoice .book-choice-lead');
        if (leadR && hubBookChoiceLeadDefault != null) leadR.textContent = hubBookChoiceLeadDefault;
        var caR = document.getElementById('hubBookChoiceActions');
        if (caR) caR.style.display = '';
        var backNewR = document.getElementById('hubBookBackFromNew');
        if (backNewR) backNewR.style.display = '';
        setHubBookServiceVisibility(false);
        setHubBookArenaVisibility(false);
        fillHubBookServiceSelect([]);
        fillHubBookArenaPicklist([]);
        hubDockBookStepNewUnderModalChrome();
      }

      function resetHubBookSteps() {
        var ch = document.getElementById('hubBookStepChoice');
        var ex = document.getElementById('hubBookStepExisting');
        var nw = document.getElementById('hubBookStepNew');
        var modal = document.getElementById('hubModalBookGroupSlot');
        hubDockBookStepNewUnderModalChrome();
        if (modal) modal.classList.remove('hub-book-flow-overlay--new-client');
        if (hubBookClientFirstQuickMode) hubExitClientFirstServiceStep(true);
        else hubSyncClientFirstQuickServiceChrome();
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

      function hubQuickBookArenaCacheKey() {
        return hubBookArenaId != null ? String(hubBookArenaId) : '';
      }

      function setHubBookArenaVisibility(show) {
        var wrap = document.getElementById('hubBookArenaWrap');
        if (!wrap) return;
        wrap.style.display = show ? 'block' : 'none';
      }

      /** Prefer last booking's arena when linked; else primary / first linked arena. */
      function hubPickDefaultArenaId(arenas, preferredId) {
        var list = arenas || [];
        if (!list.length) return null;
        if (preferredId != null) {
          var want = parseInt(String(preferredId), 10);
          if (!isNaN(want) && list.some(function(a) { return a.id === want; })) return want;
        }
        var prim = list.filter(function(a) { return a.is_primary; })[0];
        if (prim) return prim.id;
        return list[0].id;
      }

      function syncHubBookArenaPickHighlight() {
        var pick = document.getElementById('hubBookArenaPickList');
        if (!pick) return;
        var aid = hubBookArenaId != null ? String(hubBookArenaId) : '';
        pick.querySelectorAll('.hub-book-service-pick').forEach(function(b) {
          var id = b.getAttribute('data-arena-id') || '';
          var on = !!aid && id === aid;
          b.setAttribute('aria-selected', on ? 'true' : 'false');
          b.classList.toggle('is-selected', on);
        });
      }

      /** Renders arena chips when the trainer has more than one linked venue. */
      function fillHubBookArenaPicklist(arenas) {
        var pick = document.getElementById('hubBookArenaPickList');
        if (!pick) return;
        pick.innerHTML = '';
        (arenas || []).forEach(function(a) {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'hub-book-service-pick';
          b.setAttribute('role', 'option');
          b.setAttribute('data-arena-id', String(a.id));
          b.textContent = String(a.name || 'Площадка');
          b.onclick = function() {
            hubBookArenaId = a.id;
            syncHubBookArenaPickHighlight();
            hubQuickBookSlotsIsoDate = null;
            hubQuickBookSlotsArenaKey = null;
            hubQuickBookScheduleFetchGen += 1;
            scheduleHubQuickBookRefresh();
          };
          pick.appendChild(b);
        });
        syncHubBookArenaPickHighlight();
      }

      /** Keeps visible service “cards” in sync with `hubBookServiceId` / hidden `<select>`. */
      function syncHubBookServicePickHighlight() {
        var pick = document.getElementById('hubBookServicePickList');
        if (!pick) return;
        var sid = hubBookServiceId != null ? String(hubBookServiceId) : '';
        pick.querySelectorAll('.hub-book-service-pick').forEach(function(b) {
          var id = b.getAttribute('data-service-id') || '';
          var on = !!sid && id === sid;
          b.setAttribute('aria-selected', on ? 'true' : 'false');
          b.classList.toggle('is-selected', on);
        });
      }

      function fillHubBookServiceSelect(services) {
        var sel = document.getElementById('hubBookServiceSelect');
        var pick = document.getElementById('hubBookServicePickList');
        if (!sel) return;
        sel.innerHTML = '';
        if (pick) pick.innerHTML = '';
        (services || []).forEach(function(s) {
          var opt = document.createElement('option');
          opt.value = String(s.id);
          opt.textContent = String(s.name || 'Услуга');
          sel.appendChild(opt);
        });
        if (hubBookServiceId != null) sel.value = String(hubBookServiceId);
        if (pick) {
          (services || []).forEach(function(s) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'hub-book-service-pick';
            b.setAttribute('role', 'option');
            b.setAttribute('data-service-id', String(s.id));
            b.textContent = String(s.name || 'Услуга');
            b.onclick = function() {
              hubBookServiceId = s.id;
              sel.value = String(s.id);
              syncHubBookServicePickHighlight();
              syncHubBookPriceTierRadios();
            };
            pick.appendChild(b);
          });
          syncHubBookServicePickHighlight();
        }
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

      /** Last-booking preset: use variant id and/or API tier_kind (sync with schedule quick-book). */
      function hubResolveBookingPriceTierId(svc, variantIdRaw, priceTierKindRaw) {
        var tiers = (svc && svc.price_tiers) ? svc.price_tiers : [];
        if (!tiers.length) return null;
        if (tiers.length === 1) return tiers[0].id;
        var vid = variantIdRaw != null ? parseInt(String(variantIdRaw), 10) : NaN;
        if (!isNaN(vid) && tiers.some(function(t) { return Number(t.id) === vid; })) return vid;
        var tk = (priceTierKindRaw || '').toString().trim().toLowerCase();
        if (tk) {
          var hit = tiers.filter(function(t) {
            return (t.tier_kind || '').toString().trim().toLowerCase() === tk;
          })[0];
          if (hit) return hit.id;
        }
        return null;
      }

      /**
       * На шаге «услуга/тариф» прячем блок с двумя кнопками (из списка / нового) — иначе экран
       * визуально совпадает с первым шагом и кажется, что «Далее» ничего не меняет.
       */
      function hubSyncClientFirstQuickChoiceActionsVisible(showChoicePair) {
        var ca = document.getElementById('hubBookChoiceActions');
        if (!ca || !hubBookClientFirstQuickMode) return;
        if (hubQuickBookHideLegacyClientChoice) {
          ca.style.display = 'none';
          return;
        }
        ca.style.display = showChoicePair ? '' : 'none';
      }

      /** Show/hide «Назад» + «Далее» when client-first flow is on service/tariff step. */
      function hubSyncClientFirstQuickServiceChrome() {
        var nextBtn = document.getElementById('hubBookQuickServiceNext');
        var backSvc = document.getElementById('hubBookBackFromService');
        var show = !!(hubBookClientFirstQuickMode && hubBookClientFirstServiceStepOpen);
        if (nextBtn) {
          nextBtn.style.display = show ? '' : 'none';
          if (show) nextBtn.removeAttribute('hidden');
          else nextBtn.setAttribute('hidden', 'hidden');
          nextBtn.setAttribute('aria-hidden', show ? 'false' : 'true');
        }
        if (backSvc) {
          var showBack = !!(show && !hubQuickBookIsSandbox);
          backSvc.style.display = showBack ? '' : 'none';
          if (showBack) backSvc.removeAttribute('hidden');
          else backSvc.setAttribute('hidden', 'hidden');
          backSvc.setAttribute('aria-hidden', showBack ? 'false' : 'true');
        }
      }

      /** «Добавить и записать» vs «Далее» on new-client hub form (depends on flow). */
      function applyHubBookNewSubmitButtonLabel() {
        var btn = document.getElementById('hubBookNewSubmit');
        if (!btn) return;
        /* Sandbox uses one shared «Далее» on the service step (phone + услуги on one screen). */
        if (hubQuickBookIsSandbox && hubBookClientFirstQuickMode) {
          btn.style.display = 'none';
          btn.textContent = 'Добавить и записать';
          return;
        }
        btn.style.display = '';
        if (hubBookSlotId != null || !hubBookClientFirstQuickMode) {
          btn.textContent = 'Добавить и записать';
          return;
        }
        btn.textContent = 'Далее';
      }

      function hubApplyBookingDefaultsPayload(def) {
        def = def || {};
        var svcList = hubBookQuickServices || [];
        var arList = hubBookTrainerArenas || [];
        var dsidRaw = def.service_id != null ? parseInt(String(def.service_id), 10) : NaN;
        var wants = !isNaN(dsidRaw) && svcList.some(function(s) { return s.id === dsidRaw; });
        hubBookServiceId = wants ? dsidRaw : (svcList.length ? svcList[0].id : null);
        var sel = document.getElementById('hubBookServiceSelect');
        if (sel && hubBookServiceId != null) sel.value = String(hubBookServiceId);
        syncHubBookServicePickHighlight();
        hubBookPendingTierPresetVariantId =
          def.service_price_variant_id != null ? def.service_price_variant_id : null;
        hubBookPendingTierPresetKind =
          def.price_tier_kind != null && String(def.price_tier_kind).trim()
            ? def.price_tier_kind
            : null;
        hubBookArenaId = hubPickDefaultArenaId(arList, def.arena_id);
        fillHubBookArenaPicklist(arList);
      }

      function hubEnterClientFirstServiceStep(leadHint) {
        hubBookClientFirstServiceStepOpen = true;
        hubSyncClientFirstQuickChoiceActionsVisible(false);
        setHubBookServiceVisibility(true);
        syncHubBookPriceTierRadios();
        hubSyncClientFirstQuickServiceChrome();
        setHubBookArenaVisibility((hubBookTrainerArenas || []).length > 1);
        applyHubBookNewSubmitButtonLabel();
        if (leadHint) {
          var lead = document.querySelector('#hubBookStepChoice .book-choice-lead');
          if (lead) lead.textContent = leadHint;
        }
        try {
          var svcTop = document.getElementById('hubBookServiceWrap');
          if (svcTop && svcTop.style.display !== 'none' && typeof svcTop.scrollIntoView === 'function') {
            svcTop.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
          }
        } catch (eScroll) { /* noop */ }
      }

      function hubExitClientFirstServiceStep(resetLead) {
        hubBookClientFirstServiceStepOpen = false;
        if (hubBookClientFirstQuickMode) {
          setHubBookServiceVisibility(false);
          setHubBookArenaVisibility(false);
          hubSyncClientFirstQuickChoiceActionsVisible(!!resetLead);
        }
        syncHubBookPriceTierRadios();
        hubSyncClientFirstQuickServiceChrome();
        if (resetLead) {
          ensureHubBookChoiceLeadDefault();
          var lead = document.querySelector('#hubBookStepChoice .book-choice-lead');
          if (lead && hubBookChoiceLeadDefault != null) lead.textContent = hubBookChoiceLeadDefault;
        }
      }

      /**
       * Waits until background prepare populated hubBookQuickServices (GET /trainer/my-services).
       * User can tap faster than the hub prepare fetch finishes — without this, service step breaks.
       */
      function hubWhenQuickBookServicesReady(done, timeoutMs) {
        var limit = timeoutMs != null ? timeoutMs : 14000;
        var deadline = Date.now() + limit;
        (function tick() {
          if ((hubBookQuickServices || []).length) {
            done();
            return;
          }
          if (Date.now() > deadline) {
            hubToast('Не удалось загрузить услуги. Закройте окно и попробуйте снова.');
            var qinp = document.getElementById('hubBookClientSearch');
            loadHubBookClients(qinp ? qinp.value.trim() : '');
            return;
          }
          setTimeout(tick, 45);
        })();
      }

      /**
       * Starts hub «Записать клиента»: client (existing/new) → service/tariffs → datetime → POST.
       * Last booking presets: GET /trainer/clients/{id}/booking-defaults.
       * Uses multi-retry + fetch timeouts — Telegram WebView often drops the first request or delays initData.
       *
       * Обычный режим: сразу экран поиска клиента (+ ненавязчивая «Новый клиент»); блок с двумя крупными кнопками не показываем.
       * Sandbox / «Пример»: прежний skeleton до загрузки услуг (нет промежуточного выбора).
       */
      function openHubQuickBookClientFlowFirst() {
        hubBookClientFirstQuickMode = true;
        hubBookClientFirstServiceStepOpen = false;
        hubBookClientFirstServiceFromNew = false;
        hubBookQuickPayload = null;
        if (!openHubBookModalShell({ quickBookSearchFirst: !hubQuickBookIsSandbox })) return;
        hubQuickBookPrepareGen += 1;
        var prepareGen = hubQuickBookPrepareGen;
        hubBookQuickServices = [];
        hubBookTrainerArenas = [];
        hubBookArenaId = null;
        hubBookServiceId = null;
        hubSyncClientFirstQuickServiceChrome();
        applyHubBookNewSubmitButtonLabel();
        if (hubQuickBookIsSandbox) {
          setHubBookChoiceQuickLoading(true);
        } else {
          setHubBookChoicePairPending(false);
          setHubBookChoiceQuickLoading(false);
          clearHubBookChoiceQuickUi();
        }
        setHubBookServiceVisibility(false);
        fillHubBookServiceSelect([]);
        fillHubBookArenaPicklist([]);
        var ptHost = document.getElementById('hubBookPriceTierRadios');
        var ptWrap = document.getElementById('hubBookPriceTierWrap');
        if (ptHost) ptHost.innerHTML = '';
        if (ptWrap) ptWrap.style.display = 'none';
        hubBookSlotId = null;
        hubBookPriceVariantId = null;
        hubBookSlotWhenLabel = '';

        function failHubQuickBookPrepare(forGen) {
          if (forGen != null && forGen !== hubQuickBookPrepareGen) return;
          setHubBookChoiceQuickLoading(false);
          hubTrainerHasClientsCache = null;
          setHubBookOptExistingVisible(false);
          closeHubBookGroupModals();
          resetHubBookSlotState();
          hubToast('Не удалось подготовить форму записи. Повторите попытку.');
        }

        function runHubQuickBookPrepareAttempt(attemptIdx) {
          if (prepareGen !== hubQuickBookPrepareGen) return;
          if (!getInitData()) {
            failHubQuickBookPrepare(prepareGen);
            return;
          }
          if (hubBookClientFirstQuickMode && !hubQuickBookIsSandbox) {
            try {
              loadHubBookClients('');
            } catch (eQb) {
              /* noop */
            }
          }
          Promise.all([
            hubFetchJsonForQuickBookPrepare('/trainer/my-services').then(function(r) {
              if (!r.ok) return Promise.reject(new Error('services'));
              return r.json();
            }),
            hubFetchJsonForQuickBookPrepare('/trainer/clients').then(function(r) {
              return r.json().then(function(j) {
                if (!r.ok) return Promise.reject(new Error('clients'));
                return j;
              });
            }),
          ])
            .then(function(results) {
              if (prepareGen !== hubQuickBookPrepareGen) return;
              setHubBookChoiceQuickLoading(false);
              var servicePayload = results[0] || {};
              var clientsPayload = results[1] || {};
              hubBookQuickServices = servicePayload.services || [];
              syncHubMyServicesAccentMap(hubBookQuickServices);
              if (!hubBookQuickServices.length) {
                hubApplyTrainerHasClientsFromPayload(clientsPayload);
                setHubBookOptExistingVisible(false);
                closeHubBookGroupModals();
                resetHubBookSlotState();
                hubToast('Добавьте услугу в профиле, чтобы записывать клиентов.');
                return;
              }
              hubBookServiceId = hubBookQuickServices[0].id;
              fillHubBookServiceSelect(hubBookQuickServices);
              hubBookTrainerArenas = servicePayload.arenas || [];
              hubBookArenaId = hubPickDefaultArenaId(hubBookTrainerArenas);
              fillHubBookArenaPicklist(hubBookTrainerArenas);
              hubBookQuickPayload = null;
              var hasClients = hubApplyTrainerHasClientsFromPayload(clientsPayload);
              ensureHubBookChoiceLeadDefault();
              if (hubQuickBookIsSandbox) {
                hubBookClientFirstServiceStepOpen = true;
                setHubBookServiceVisibility(true);
                syncHubBookPriceTierRadios();
                hubSyncClientFirstQuickServiceChrome();
                var leadSx = document.querySelector('#hubBookStepChoice .book-choice-lead');
                if (leadSx) {
                  leadSx.textContent =
                    'Тестовая запись: услуга и тариф, контакт ниже можно заменить. Затем нажмите «Далее» и выберите дату.';
                }
                var caSx = document.getElementById('hubBookChoiceActions');
                if (caSx) caSx.style.display = 'none';
                var stepNewSx = document.getElementById('hubBookStepNew');
                if (stepNewSx) stepNewSx.style.display = 'block';
                var chSx = document.getElementById('hubBookStepChoice');
                if (chSx) chSx.style.display = 'block';
                var backSx = document.getElementById('hubBookBackFromNew');
                if (backSx) backSx.style.display = 'none';
                applyHubSandboxNewClientPrefill();
                setHubBookOptExistingVisible(false);
                applyHubBookNewSubmitButtonLabel();
                setHubBookArenaVisibility((hubBookTrainerArenas || []).length > 1);
                hubEmbedSandboxBookStepNewBeforeQuickNext();
              } else {
                var chEl = document.getElementById('hubBookStepChoice');
                var exEl = document.getElementById('hubBookStepExisting');
                var nwEl = document.getElementById('hubBookStepNew');
                /* User may reach new-client or service step before prepare resolves — keep that navigation. Search-first alone is not "past" initial. */
                var pastInitialChoice =
                  hubBookClientFirstServiceStepOpen ||
                  (nwEl &&
                    nwEl.style.display !== 'none' &&
                    String(nwEl.style.display || '').toLowerCase() !== '') ||
                  (!!chEl &&
                    chEl.style.display !== 'none' &&
                    exEl &&
                    exEl.style.display === 'none');

                if (!pastInitialChoice) {
                  hubBookClientFirstServiceStepOpen = false;
                  setHubBookServiceVisibility(false);
                  syncHubBookPriceTierRadios();
                  hubSyncClientFirstQuickServiceChrome();
                  var qinpN = document.getElementById('hubBookClientSearch');
                  hubEnsureQuickBookSearchOnlyLayout();
                  loadHubBookClients(qinpN ? qinpN.value.trim() : '');
                  var stepNewNx = document.getElementById('hubBookStepNew');
                  var backNx = document.getElementById('hubBookBackFromNew');
                  if (stepNewNx) stepNewNx.style.display = 'none';
                  if (backNx) backNx.style.display = '';
                } else {
                  syncHubBookPriceTierRadios();
                  hubSyncClientFirstQuickServiceChrome();
                }
                setHubBookOptExistingVisible(hasClients);
                applyHubBookNewSubmitButtonLabel();
              }
              requestAnimationFrame(function() {
                setHubBookChoicePairPending(false);
              });
            })
            .catch(function() {
              if (prepareGen !== hubQuickBookPrepareGen) return;
              var canRetry = attemptIdx + 1 < HUB_QB_PREPARE_MAX_ATTEMPTS && !!getInitData();
              if (canRetry) {
                var delay =
                  Math.min(4000, 260 + Math.floor(480 * Math.pow(1.75, attemptIdx))) +
                  Math.floor(Math.random() * 140);
                setTimeout(function() {
                  runHubQuickBookPrepareAttempt(attemptIdx + 1);
                }, delay);
                return;
              }
              failHubQuickBookPrepare(prepareGen);
            });
        }

        waitForTrainerInitDataThen(function() {
          if (prepareGen !== hubQuickBookPrepareGen) return;
          if (!getInitData()) {
            setHubBookChoiceQuickLoading(false);
            hubTrainerHasClientsCache = null;
            setHubBookOptExistingVisible(false);
            closeHubBookGroupModals();
            resetHubBookSlotState();
            hubToast('Сессия ещё подключается. Подождите секунду и откройте запись снова.');
            return;
          }
          runHubQuickBookPrepareAttempt(0);
        });
      }

      /** After datetime confirmed: create trainer client then quick-book (same as legacy one-shot submit). */
      function hubPostNewClientQuickBookChain() {
        if (hubBookQuickChainInFlight) return;
        var phoneEl = document.getElementById('hubBookNewPhone');
        var firstEl = document.getElementById('hubBookNewFirstName');
        var lastEl = document.getElementById('hubBookNewLastName');
        var phoneRaw = phoneEl ? (phoneEl.value || '').trim() : '';
        var first = firstEl ? (firstEl.value || '').trim() : '';
        var last = lastEl ? (lastEl.value || '').trim() : '';
        if (!/[\d]/.test(phoneRaw)) {
          hubToast('Введите номер телефона (цифры).');
          return;
        }
        var phone = normalizePhoneHub(phoneRaw);
        var errPhone = validatePhoneHubMsg(phone);
        if (errPhone) {
          hubToast(errPhone);
          return;
        }
        first = (first || '').trim();
        if (!first) {
          hubToast('Укажите имя клиента.');
          return;
        }
        if (hubBookServiceId == null) {
          hubToast('Выберите услугу.');
          return;
        }
        hubBookQuickChainInFlight = true;
        setHubGlobalBookingBusy(true);
        var wasQuickSandbox = hubQuickBookIsSandbox;
        // Sandbox identity is now created server-side as a real ``clients.is_sandbox=true`` row with
        // a deterministic per-trainer phantom phone (the user's typed phone is ignored on the
        // server). Passing the flag here keeps the request shape clean and makes intent explicit.
        var clientPayload = wasQuickSandbox
          ? { phone: phone, first_name: first || 'Александр', last_name: last || 'К.', is_sandbox: true }
          : { phone: phone, first_name: first, last_name: last || '' };
        fetch(apiUrlWithQuery('/trainer/clients'), {
          method: 'POST',
          headers: headersJson(),
          body: JSON.stringify(clientPayload),
        })
          .then(function(r) {
            if (!r.ok) return r.json().then(function(o) { throw new Error(hubApiErrorMessage(o)); });
            return r.json();
          })
          .then(function(data) {
            hubTrainerHasClientsCache = true;
            return hubPostBooking(data.client_id, !!data.is_sandbox);
          })
          .then(function(res) {
            closeHubBookGroupModals();
            resetHubBookSlotState();
            var bid = res.booking && res.booking.booking_id != null ? Number(res.booking.booking_id) : null;
            if (bid && !isNaN(bid)) stashHubPendingBookingHighlight(bid);
            var baseText = 'Клиент добавлен и запись успешно создана.';
            var tail =
              wasQuickSandbox
                ? ' Запись появится в «Ближайших записях». Отменить можно в «Детали записи».'
                : ' Запись появится в «Ближайших записях».';
            presentHubBookingSuccess(res.booking, baseText + tail);
            loadBookings();
            loadOnboardingChecklist();
          })
          .catch(function(e) {
            hubToast(e.message || 'Ошибка');
          })
          .finally(function() {
            hubBookQuickChainInFlight = false;
            setHubGlobalBookingBusy(false);
          });
      }

      function syncHubBookPriceTierRadios() {
        var wrap = document.getElementById('hubBookPriceTierWrap');
        var host = document.getElementById('hubBookPriceTierRadios');
        if (!wrap || !host) return;
        /* Quick-book tiers: datetime step already chose slot, or client-first flow is on service step. Group slot hides tiers here. */
        var allowTierUi = hubBookQuickPayload != null || hubBookClientFirstServiceStepOpen === true;
        if (!allowTierUi) {
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
          hubBookPendingTierPresetVariantId = null;
          hubBookPendingTierPresetKind = null;
          return;
        }
        wrap.style.display = 'block';
        host.innerHTML = '';
        var gname = 'hub_bpt_' + String(sid || 0);
        var preferredId = hubPickDefaultPriceTierId(tiers);
        var presetV = hubBookPendingTierPresetVariantId;
        var presetK = hubBookPendingTierPresetKind;
        if (presetV != null || (presetK != null && String(presetK).trim() !== '')) {
          var resolved = hubResolveBookingPriceTierId(svc, presetV, presetK);
          if (resolved != null) preferredId = resolved;
        }
        hubBookPendingTierPresetVariantId = null;
        hubBookPendingTierPresetKind = null;
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
          var pb = Number(tier.price_byn);
          if (!isFinite(pb)) pb = 0;
          var numStr = pb === Math.floor(pb) ? String(Math.floor(pb)) : pb.toFixed(2);
          var priceFrag = document.createElement('span');
          priceFrag.textContent = numStr + ' BYN';
          lab.appendChild(inp);
          lab.appendChild(document.createTextNode(hubPriceTierLabelRu(tier) + ' — '));
          lab.appendChild(priceFrag);
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

      function resetHubBookStepsToQuickClientSearchFirst() {
        hubQuickBookHideLegacyClientChoice = true;
        var ch = document.getElementById('hubBookStepChoice');
        var ex = document.getElementById('hubBookStepExisting');
        var nw = document.getElementById('hubBookStepNew');
        var modal = document.getElementById('hubModalBookGroupSlot');
        hubDockBookStepNewUnderModalChrome();
        if (modal) modal.classList.remove('hub-book-flow-overlay--new-client');
        if (hubBookClientFirstQuickMode) hubExitClientFirstServiceStep(false);
        else hubSyncClientFirstQuickServiceChrome();
        if (ch) ch.style.display = 'none';
        if (ex) ex.style.display = 'block';
        if (nw) nw.style.display = 'none';
        var listEl = document.getElementById('hubBookClientList');
        if (listEl) {
          listEl.innerHTML =
            '<p style="text-align:center;padding:16px;color:var(--tg-theme-hint-color);">Загрузка…</p>';
        }
      }

      /** After async prepare: keep search step without clearing the query the trainer may have typed. */
      function hubEnsureQuickBookSearchOnlyLayout() {
        if (!hubBookClientFirstQuickMode || hubQuickBookIsSandbox) return;
        hubQuickBookHideLegacyClientChoice = true;
        var ch = document.getElementById('hubBookStepChoice');
        var ex = document.getElementById('hubBookStepExisting');
        var nw = document.getElementById('hubBookStepNew');
        var modal = document.getElementById('hubModalBookGroupSlot');
        if (modal) modal.classList.remove('hub-book-flow-overlay--new-client');
        if (hubBookClientFirstServiceStepOpen) return;
        if (ch) ch.style.display = 'none';
        if (ex) ex.style.display = 'block';
        if (nw) nw.style.display = 'none';
        hubSyncClientFirstQuickChoiceActionsVisible(false);
      }

      function hubGoBookNewClientFlow() {
        hubDockBookStepNewUnderModalChrome();
        var modal = document.getElementById('hubModalBookGroupSlot');
        if (modal) modal.classList.add('hub-book-flow-overlay--new-client');
        document.getElementById('hubBookStepChoice').style.display = 'none';
        document.getElementById('hubBookStepExisting').style.display = 'none';
        document.getElementById('hubBookStepNew').style.display = 'block';
        applyHubBookNewSubmitButtonLabel();
      }

      function hubReturnFromNewClientToQuickSearch() {
        hubBookClientFirstServiceFromNew = false;
        var modalGo = document.getElementById('hubModalBookGroupSlot');
        if (modalGo) modalGo.classList.remove('hub-book-flow-overlay--new-client');
        document.getElementById('hubBookStepNew').style.display = 'none';
        hubEnsureQuickBookSearchOnlyLayout();
        var qinp = document.getElementById('hubBookClientSearch');
        loadHubBookClients(qinp ? qinp.value.trim() : '');
      }

      function openHubBookModalShell(opts) {
        opts = opts || {};
        resetHubBookFormFields();
        if (opts.quickBookSearchFirst) {
          resetHubBookStepsToQuickClientSearchFirst();
        } else {
          resetHubBookSteps();
          primeHubBookChoicePairLayout();
        }
        setHubBookChoicePairPending(true);
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
          hour_start: 6,
          hour_end: 23,
          step_minutes: 15,
          slot_duration_minutes: null,
        };
      }

      /** When set, GET /schedule `schedule_grid` fixes slot length (arena_schedule_presets.slot_duration_minutes). */
      function hubFixedSlotDurationMinutes() {
        var p = hubQuickBookScheduleGrid || hubDefaultScheduleGrid();
        if (p.slot_duration_minutes == null || p.slot_duration_minutes === '') return null;
        var n = parseInt(p.slot_duration_minutes, 10);
        if (isNaN(n) || n < 15) return null;
        return Math.min(24 * 60, n);
      }

      function hubEnsureDurationSelectOption(selectEl, minutes) {
        if (!selectEl || minutes == null) return;
        var v = String(minutes);
        if (selectEl.querySelector('option[value="' + v + '"]')) return;
        var o = document.createElement('option');
        o.value = v;
        o.textContent = minutes + ' минут';
        selectEl.appendChild(o);
      }

      function hubSyncQuickBookDurationFromGrid() {
        var stack = document.getElementById('hubQuickBookDurationStack');
        var hint = document.getElementById('hubQuickBookDurationFixedHint');
        var durEl = document.getElementById('hubQuickBookDuration');
        var wrap = document.getElementById('hubQuickBookDatetimeWrap');
        if (!durEl) return;
        var fixed = hubFixedSlotDurationMinutes();
        if (fixed != null) {
          hubEnsureDurationSelectOption(durEl, fixed);
          durEl.value = String(fixed);
          durEl.disabled = true;
          if (stack) stack.style.display = 'none';
          if (hint) {
            hint.removeAttribute('hidden');
            hint.textContent = 'Длительность: ' + fixed + ' мин (зафиксировано для площадки).';
            hint.setAttribute('aria-hidden', 'false');
          }
        } else {
          durEl.disabled = false;
          if (stack) stack.style.display = '';
          if (hint) {
            hint.setAttribute('hidden', 'hidden');
            hint.textContent = '';
            hint.setAttribute('aria-hidden', 'true');
          }
        }
        if (wrap) wrap.classList.toggle('hub-quickbook-datetime-wrap--duration-custom', fixed == null);
      }

      function setHubQuickBookDatetimeLoading(on) {
        var wrap = document.getElementById('hubQuickBookDatetimeWrap');
        var modal = document.getElementById('hubModalQuickBookDatetime');
        if (wrap) wrap.classList.toggle('hub-quickbook-datetime-wrap--loading', !!on);
        if (modal) modal.setAttribute('aria-busy', on ? 'true' : 'false');
      }

      function hubApplyQuickBookScheduleGrid(data) {
        if (data && data.schedule_grid) hubQuickBookScheduleGrid = data.schedule_grid;
        else if (!hubQuickBookScheduleGrid) hubQuickBookScheduleGrid = hubDefaultScheduleGrid();
        hubSyncQuickBookDurationFromGrid();
      }

      function hubAllowedStartMinutesFromGrid() {
        var preset = hubQuickBookScheduleGrid || hubDefaultScheduleGrid();
        var kind = (preset.kind || 'uniform_step').toString().trim();
        var h0 = Math.max(0, Math.min(23, parseInt(preset.hour_start, 10)));
        if (isNaN(h0)) h0 = 6;
        var h1 = Math.max(0, Math.min(23, parseInt(preset.hour_end, 10)));
        if (isNaN(h1)) h1 = 23;
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
          if (!isNaN(s) && [10, 15, 30, 60].indexOf(s) >= 0) step = s;
        }
        for (var m = h0 * 60; m <= h1 * 60; m += step) out.push(m);
        return out;
      }

      function setHubQuickBookHint(text, visible) {
        var el = document.getElementById('hubQuickBookHint');
        if (!el) return;
        var on = !!(visible && text);
        el.textContent = on ? String(text) : '';
        el.classList.toggle('is-on', on);
        el.setAttribute('aria-hidden', on ? 'false' : 'true');
      }

      function hubQuickBookSlotAvailability(slotsForDay, startMinutes, durationMinutes, isoDate) {
        var dm = durationMinutes || 45;
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

      function hubRebuildQuickBookTimeSelect(isoDate, dm) {
        var sel = document.getElementById('hubQuickBookTime');
        var btnGo = document.getElementById('hubQuickBookContinue');
        if (!sel || !isoDate) return false;
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
        if (btnGo) btnGo.disabled = !anyFree;
        if (!anyFree) {
          setHubQuickBookHint('Нет доступного времени для выбранной длительности.', true);
        } else {
          setHubQuickBookHint('', false);
        }
        return anyFree;
      }

      function hubRefreshQuickBookTimeOptions(isoDate, opts) {
        opts = opts || {};
        var silentLoadingHint = !!opts.silentLoadingHint;
        var sel = document.getElementById('hubQuickBookTime');
        var durEl = document.getElementById('hubQuickBookDuration');
        var btnGo = document.getElementById('hubQuickBookContinue');
        if (!sel || !isoDate) return Promise.resolve();
        var fixedDm = hubFixedSlotDurationMinutes();
        var dm =
          fixedDm != null
            ? fixedDm
            : durEl
              ? parseInt(durEl.value, 10)
              : 45;
        if (fixedDm == null && (isNaN(dm) || dm < 15)) dm = 45;
        var cacheArena = hubQuickBookArenaCacheKey();
        if (hubQuickBookSlotsIsoDate === isoDate && hubQuickBookSlotsArenaKey === cacheArena) {
          hubRebuildQuickBookTimeSelect(isoDate, dm);
          setHubQuickBookDatetimeLoading(false);
          return Promise.resolve();
        }
        // Paint times from preset grid immediately — empty <select> until /schedule returned caused visible flicker.
        hubQuickBookSlotsForDay = [];
        hubQuickBookSlotsIsoDate = null;
        hubQuickBookSlotsArenaKey = null;
        hubRebuildQuickBookTimeSelect(isoDate, dm);
        var fetchGen = ++hubQuickBookScheduleFetchGen;
        sel.disabled = true;
        if (btnGo) btnGo.disabled = true;
        setHubQuickBookDatetimeLoading(true);
        if (!silentLoadingHint) {
          setHubQuickBookHint('Загрузка сетки расписания…', true);
        }
        var schedulePath =
          '/schedule?from_date=' +
          encodeURIComponent(isoDate) +
          '&to_date=' +
          encodeURIComponent(isoDate);
        if (hubBookArenaId != null) {
          schedulePath += '&arena_id=' + encodeURIComponent(String(hubBookArenaId));
        }
        return fetch(
          apiUrlWithQuery(schedulePath),
          { headers: headersJson() }
        )
          .then(function(r) {
            if (!r.ok) return Promise.reject(new Error('schedule'));
            return r.json();
          })
          .then(function(data) {
            if (fetchGen !== hubQuickBookScheduleFetchGen) return;
            hubApplyQuickBookScheduleGrid(data);
            var slots = (data && data.slots) ? data.slots : [];
            hubQuickBookSlotsForDay = slots.filter(function(s) {
              var d = s.slot_date;
              return d === isoDate || String(d) === isoDate;
            });
            hubQuickBookSlotsIsoDate = isoDate;
            hubQuickBookSlotsArenaKey = hubQuickBookArenaCacheKey();
            hubRebuildQuickBookTimeSelect(isoDate, dm);
            sel.disabled = false;
            setHubQuickBookDatetimeLoading(false);
          })
          .catch(function() {
            if (fetchGen !== hubQuickBookScheduleFetchGen) return;
            hubApplyQuickBookScheduleGrid(null);
            hubQuickBookSlotsForDay = [];
            hubQuickBookSlotsIsoDate = null;
            hubQuickBookSlotsArenaKey = null;
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
            setHubQuickBookDatetimeLoading(false);
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

      function closeHubQuickBookDatetimeModal(keepSandboxIntent) {
        var m = document.getElementById('hubModalQuickBookDatetime');
        if (!m) return;
        if (hubQuickBookRefreshTimer) {
          clearTimeout(hubQuickBookRefreshTimer);
          hubQuickBookRefreshTimer = null;
        }
        hubQuickBookScheduleFetchGen += 1;
        setHubQuickBookDatetimeLoading(false);
        m.style.display = 'none';
        m.setAttribute('aria-hidden', 'true');
        if (!keepSandboxIntent) hubQuickBookIsSandbox = false;
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
        setHubQuickBookDatetimeLoading(false);
        var today = todayIsoLocal();
        dateEl.min = today;
        if (!dateEl.value || dateEl.value < today) dateEl.value = today;
        if (!durEl.value) durEl.value = '45';
        hubSyncQuickBookDurationFromGrid();
        hubQuickBookSlotsForDay = [];
        hubQuickBookSlotsIsoDate = null;
        hubQuickBookSlotsArenaKey = null;
        hubQuickBookScheduleFetchGen += 1;
        setHubQuickBookHint('', false);
        modal.style.display = 'flex';
        modal.setAttribute('aria-hidden', 'false');
        hubRefreshQuickBookTimeOptions(dateEl.value || today, { silentLoadingHint: true });
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
              var emptyHint =
                hubBookClientFirstQuickMode && hubQuickBookHideLegacyClientChoice && !hubQuickBookIsSandbox
                  ? 'Нет клиентов по запросу. Нажмите «Новый клиент» сверху или уточните поиск.'
                  : 'Нет клиентов по поиску. Добавьте нового ниже.';
              list.innerHTML =
                '<p style="padding:8px 0;font-size:14px;color:var(--tg-theme-hint-color);">' +
                escapeHtml(emptyHint) +
                '</p>';
              return;
            }
            var html = '';
            clients.forEach(function(c) {
              var name = ((c.first_name || '') + ' ' + (c.last_name || '')).trim() || 'Клиент';
              var phone = (c.phone || '').trim();
              var noBot = !c.telegram_id;
              var isSb = !!c.is_sandbox;
              var bodyInner =
                escapeHtml(name) +
                (phone ? '<br><span class="phone">' + escapeHtml(phone) + '</span>' : '') +
                (noBot
                  ? '<br><span class="hub-book-client-row__nobot">Без бота</span>'
                  : '');
              html +=
                '<button type="button" class="client-row' +
                (isSb ? ' hub-book-client-row--sandbox' : '') +
                '" data-client-id="' +
                c.id +
                '" data-is-sandbox="' +
                (isSb ? '1' : '0') +
                '" data-client-name="' +
                escapeHtml(name).replace(/"/g, '&quot;') +
                '">' +
                (isSb
                  ? '<span class="hub-book-client-row__main">' +
                    bodyInner +
                    '</span><span class="hub-book-client-row__badge"><span class="hub-sandbox-pill hub-sandbox-pill--clientpick" role="status">тест</span></span>'
                  : bodyInner) +
                '</button>';
            });
            list.innerHTML = html;
            list.querySelectorAll('.client-row').forEach(function(row) {
              row.onclick = function() {
                var clientId = parseInt(row.getAttribute('data-client-id'), 10);
                var clientName = (row.getAttribute('data-client-name') || 'Клиент').replace(/&quot;/g, '"');
                hubBookPendingClientId = clientId;
                hubBookPendingClientName = clientName;
                hubBookPendingClientIsSandbox = row.getAttribute('data-is-sandbox') === '1';
                if (hubBookClientFirstQuickMode) {
                  hubBookClientFirstServiceFromNew = false;
                  list.innerHTML =
                    '<p style="text-align:center;padding:16px;color:var(--tg-theme-hint-color);">Загрузка…</p>';
                  hubWhenQuickBookServicesReady(function() {
                    fetch(
                      apiUrlWithQuery(
                        '/trainer/clients/' + encodeURIComponent(String(clientId)) + '/booking-defaults'
                      ),
                      { headers: headersJson(), cache: 'no-store' }
                    )
                      .then(function(r) {
                        return r.ok ? r.json() : {};
                      })
                      .then(function(def) {
                        var stepEx = document.getElementById('hubBookStepExisting');
                        var stepCh = document.getElementById('hubBookStepChoice');
                        if (stepEx) stepEx.style.display = 'none';
                        if (stepCh) stepCh.style.display = 'block';
                        hubApplyBookingDefaultsPayload(def || {});
                        hubEnterClientFirstServiceStep(
                          'Услуга и тариф — как в прошлый раз. Поменяйте при необходимости.'
                        );
                      })
                      .catch(function() {
                        var stepEx2 = document.getElementById('hubBookStepExisting');
                        var stepCh2 = document.getElementById('hubBookStepChoice');
                        if (stepEx2) stepEx2.style.display = 'none';
                        if (stepCh2) stepCh2.style.display = 'block';
                        hubApplyBookingDefaultsPayload({});
                        hubEnterClientFirstServiceStep(null);
                      });
                  });
                  return;
                }
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
        hubBookClientFirstQuickMode = false;
        hubQuickBookHideLegacyClientChoice = false;
        hubBookClientFirstServiceStepOpen = false;
        hubBookClientFirstServiceFromNew = false;
        hubSyncClientFirstQuickServiceChrome();
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
        applyHubBookNewSubmitButtonLabel();
        syncHubBookPriceTierRadios();
        fetch(apiUrlWithQuery('/trainer/clients'), { headers: headersJson() })
          .then(function(r) {
            return r.json();
          })
          .then(function(data) {
            var has = hubApplyTrainerHasClientsFromPayload(data);
            setHubBookOptExistingVisible(has);
            requestAnimationFrame(function() {
              setHubBookChoicePairPending(false);
            });
          })
          .catch(function() {
            hubTrainerHasClientsCache = null;
            setHubBookOptExistingVisible(false);
            requestAnimationFrame(function() {
              setHubBookChoicePairPending(false);
            });
          });
      }

      function hubApiErrorMessage(o) {
        var d = o && o.detail;
        if (typeof d === 'string') return d;
        if (Array.isArray(d) && d[0] && d[0].msg) return d[0].msg;
        return 'Ошибка';
      }

      /**
       * @param quickBookingClientIsSandbox When quick-booking: must match ``clients.is_sandbox`` for ``client_id``
       * (server rejects mismatched sandbox flags). Omit second arg only for legacy paths — prefers explicit booleans.
       */
      function hubPostBooking(clientId, quickBookingClientIsSandbox) {
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
          if (hubBookArenaId != null) {
            payload.arena_id = hubBookArenaId;
          }
          if (hubBookPriceVariantId != null) {
            payload.service_price_variant_id = hubBookPriceVariantId;
          }
          var explicitSb =
            quickBookingClientIsSandbox !== undefined && quickBookingClientIsSandbox !== null;
          payload.is_sandbox = explicitSb ? !!quickBookingClientIsSandbox : !!hubQuickBookIsSandbox;
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

      function wireHubBookGroupModal() {
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
            syncHubBookServicePickHighlight();
            syncHubBookPriceTierRadios();
          };
        }
        var bo = document.getElementById('hubBookOptExisting');
        if (bo) {
          bo.onclick = function() {
            hubDockBookStepNewUnderModalChrome();
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
            hubGoBookNewClientFlow();
          };
        }
        var bnChip = document.getElementById('hubBookExistingNewChip');
        if (bnChip) {
          bnChip.onclick = function() {
            hubGoBookNewClientFlow();
          };
        }
        var be = document.getElementById('hubBookBackFromExisting');
        if (be) {
          be.onclick = function() {
            if (hubBookClientFirstQuickMode && hubQuickBookHideLegacyClientChoice && !hubQuickBookIsSandbox) {
              var mQx = document.getElementById('hubModalBookGroupSlot');
              if (mQx) {
                mQx.style.display = 'none';
                mQx.setAttribute('aria-hidden', 'true');
              }
              closeHubBookGroupModals();
              resetHubBookSlotState();
              return;
            }
            resetHubBookSteps();
          };
        }
        var bwn = document.getElementById('hubBookBackFromNew');
        if (bwn) {
          bwn.onclick = function() {
            if (hubBookClientFirstQuickMode && hubQuickBookHideLegacyClientChoice && !hubQuickBookIsSandbox) {
              hubReturnFromNewClientToQuickSearch();
              return;
            }
            resetHubBookSteps();
          };
        }
        var hubPhoneInp = document.getElementById('hubBookNewPhone');
        if (hubPhoneInp && hubPhoneInp.dataset.crmNat375Mask !== '1') {
          if (typeof window.wireNational375PhoneInputMask === 'function') {
            window.wireNational375PhoneInputMask(hubPhoneInp);
          }
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
        var qSvcNext = document.getElementById('hubBookQuickServiceNext');
        if (qSvcNext) {
          qSvcNext.onclick = function() {
            if (!hubBookClientFirstQuickMode) return;
            if (hubBookServiceId == null) {
              hubToast('Выберите услугу.');
              return;
            }
            var sidCv = hubBookServiceId;
            var svcCv = (hubBookQuickServices || []).filter(function(x) { return x.id === sidCv; })[0];
            var tiersCv = (svcCv && svcCv.price_tiers) ? svcCv.price_tiers : [];
            if (tiersCv.length > 1 && hubBookPriceVariantId == null) {
              hubToast('Выберите тариф.');
              return;
            }
            var ars = hubBookTrainerArenas || [];
            if (ars.length > 1 && hubBookArenaId == null) {
              hubToast('Выберите площадку.');
              return;
            }
            openHubQuickBookDatetimeModal();
          };
        }
        var qBackSvc = document.getElementById('hubBookBackFromService');
        if (qBackSvc) {
          qBackSvc.onclick = function() {
            if (!hubBookClientFirstQuickMode) return;
            hubDockBookStepNewUnderModalChrome();
            hubBookQuickPayload = null;
            var resetLeadSvc = hubBookClientFirstServiceFromNew === false;
            hubExitClientFirstServiceStep(resetLeadSvc);
            applyHubBookNewSubmitButtonLabel();
            var cameFromNew = hubBookClientFirstServiceFromNew;
            var stepChB = document.getElementById('hubBookStepChoice');
            if (cameFromNew) {
              if (stepChB) stepChB.style.display = 'none';
              var stepNwB = document.getElementById('hubBookStepNew');
              if (stepNwB) stepNwB.style.display = 'block';
              hubBookClientFirstServiceFromNew = false;
            } else {
              hubBookPendingClientId = null;
              hubBookPendingClientName = '';
              hubBookPendingClientIsSandbox = false;
              document.getElementById('hubBookStepExisting').style.display = 'block';
              if (stepChB) stepChB.style.display = 'none';
              var qinpB = document.getElementById('hubBookClientSearch');
              if (hubBookClientFirstQuickMode && !hubQuickBookIsSandbox) {
                hubEnsureQuickBookSearchOnlyLayout();
              }
              loadHubBookClients(qinpB ? qinpB.value.trim() : '');
            }
          };
        }
        var cno = document.getElementById('hubBookConfirmNo');
        if (cno) {
          cno.onclick = function() {
            document.getElementById('hubModalBookGroupConfirm').style.display = 'none';
            document.getElementById('hubModalBookGroupSlot').style.display = 'flex';
            if (hubBookClientFirstQuickMode && hubBookPendingClientId != null && hubBookQuickPayload != null) {
              hubBookQuickPayload = null;
              hubBookClientFirstServiceStepOpen = true;
              hubSyncClientFirstQuickChoiceActionsVisible(false);
              setHubBookServiceVisibility(true);
              setHubBookArenaVisibility((hubBookTrainerArenas || []).length > 1);
              syncHubBookPriceTierRadios();
              hubSyncClientFirstQuickServiceChrome();
              if (hubQuickBookIsSandbox) hubEmbedSandboxBookStepNewBeforeQuickNext();
              return;
            }
            hubBookPendingClientId = null;
            hubBookPendingClientIsSandbox = false;
          };
        }
        var cyes = document.getElementById('hubBookConfirmYes');
        if (cyes) {
          cyes.onclick = function() {
            var cid = hubBookPendingClientId;
            if (cid == null) return;
            if (cyes.disabled) return;
            var successText = hubBookQuickPayload ? 'Запись успешно создана.' : 'Клиент записан в группу.';
            var wasQuickSandbox = hubBookQuickPayload ? hubBookPendingClientIsSandbox : hubQuickBookIsSandbox;
            setHubBookConfirmSubmitting(true);
            hubPostBooking(cid, hubBookPendingClientIsSandbox)
              .then(function(res) {
                closeHubBookGroupModals();
                resetHubBookSlotState();
                var bid = res.booking && res.booking.booking_id != null ? Number(res.booking.booking_id) : null;
                if (bid && !isNaN(bid)) stashHubPendingBookingHighlight(bid);
                var tail =
                  wasQuickSandbox
                    ? ' Запись появится в «Ближайших записях». Отменить можно в «Детали записи».'
                    : ' Запись появится в «Ближайших записях».';
                presentHubBookingSuccess(res.booking, successText + tail);
                loadBookings();
                loadOnboardingChecklist();
              })
              .catch(function(e) {
                hubToast(e.message || 'Ошибка');
              })
              .finally(function() {
                setHubBookConfirmSubmitting(false);
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

            if (hubBookClientFirstQuickMode && hubBookSlotId == null && !hubQuickBookIsSandbox) {
              if (!(hubBookQuickServices || []).length) {
                hubToast('Подождите — подгружаем услуги…');
                return;
              }
              hubDockBookStepNewUnderModalChrome();
              hubBookPendingClientId = null;
              hubBookPendingClientIsSandbox = false;
              hubBookClientFirstServiceFromNew = true;
              document.getElementById('hubBookStepNew').style.display = 'none';
              document.getElementById('hubBookStepChoice').style.display = 'block';
              var modalGo = document.getElementById('hubModalBookGroupSlot');
              if (modalGo) modalGo.classList.remove('hub-book-flow-overlay--new-client');
              hubApplyBookingDefaultsPayload({});
              hubEnterClientFirstServiceStep('Выберите услугу и тариф.');
              return;
            }

            sub.disabled = true;
            var wasQuickSandbox = hubQuickBookIsSandbox;
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
                return hubPostBooking(data.client_id, false);
              })
              .then(function(res) {
                hubTrainerHasClientsCache = true;
                closeHubBookGroupModals();
                resetHubBookSlotState();
                var bid = res.booking && res.booking.booking_id != null ? Number(res.booking.booking_id) : null;
                if (bid && !isNaN(bid)) stashHubPendingBookingHighlight(bid);
                var baseText = hubBookQuickPayload
                  ? 'Клиент добавлен и запись успешно создана.'
                  : 'Клиент добавлен и записан на занятие.';
                var tail =
                  wasQuickSandbox
                    ? ' Запись появится в «Ближайших записях». Отменить можно в «Детали записи».'
                    : ' Запись появится в «Ближайших записях».';
                presentHubBookingSuccess(res.booking, baseText + tail);
                loadBookings();
                loadOnboardingChecklist();
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
              if (hubBookClientFirstQuickMode && hubBookPendingClientId != null && hubBookQuickPayload != null) {
                hubBookQuickPayload = null;
                hubBookClientFirstServiceStepOpen = true;
                hubSyncClientFirstQuickChoiceActionsVisible(false);
                setHubBookServiceVisibility(true);
                setHubBookArenaVisibility((hubBookTrainerArenas || []).length > 1);
                syncHubBookPriceTierRadios();
                hubSyncClientFirstQuickServiceChrome();
                if (hubQuickBookIsSandbox) hubEmbedSandboxBookStepNewBeforeQuickNext();
              } else {
                hubBookPendingClientId = null;
                hubBookPendingClientIsSandbox = false;
              }
            }
          };
        }
        var qCancel = document.getElementById('hubQuickBookCancel');
        if (qCancel) qCancel.onclick = function() { closeHubQuickBookDatetimeModal(false); };
        var qContinue = document.getElementById('hubQuickBookContinue');
        if (qContinue) {
          qContinue.onclick = function() {
            var dateEl = document.getElementById('hubQuickBookDate');
            var timeEl = document.getElementById('hubQuickBookTime');
            var durEl = document.getElementById('hubQuickBookDuration');
            if (!dateEl || !timeEl || !durEl) return;
            var slotDate = String(dateEl.value || '').trim();
            var startMinutes = parseInt(String(timeEl.value || ''), 10);
            var fixedDur = hubFixedSlotDurationMinutes();
            var duration =
              fixedDur != null ? fixedDur : parseInt(String(durEl.value || '45'), 10);
            if (!slotDate) {
              hubToast('Выберите дату.');
              return;
            }
            if (isNaN(startMinutes)) {
              hubToast('Выберите время начала.');
              return;
            }
            if (fixedDur == null && (isNaN(duration) || duration < 15)) duration = 45;
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
            if (hubBookClientFirstQuickMode) {
              hubBookQuickPayload = {
                slot_date: slotDate,
                start_time: startTime,
                duration_minutes: duration,
              };
              hubBookSlotWhenLabel = slotDate + ' ' + startTime;
              /* Hide the book modal *before* closing datetime: otherwise one paint shows the service step underneath. */
              var mSlotUnder = document.getElementById('hubModalBookGroupSlot');
              if (mSlotUnder) {
                mSlotUnder.style.display = 'none';
                mSlotUnder.setAttribute('aria-hidden', 'true');
              }
              if (hubBookPendingClientId != null) {
                var nm = hubBookPendingClientName || 'Клиент';
                var txtCf = document.getElementById('hubBookConfirmText');
                if (txtCf) txtCf.textContent = 'Записать ' + nm + ' на ' + hubBookSlotWhenLabel + '?';
                var cfOv = document.getElementById('hubModalBookGroupConfirm');
                if (cfOv) {
                  cfOv.style.display = 'flex';
                  cfOv.setAttribute('aria-hidden', 'false');
                }
              }
              closeHubQuickBookDatetimeModal(true);
              if (hubBookPendingClientId != null) {
                return;
              }
              hubPostNewClientQuickBookChain();
              return;
            }
            closeHubQuickBookDatetimeModal(true);
            hubToast('Сессия записи устарела. Закройте окно и откройте «Записать клиента» снова.');
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
            if (ev.target === qOverlay) closeHubQuickBookDatetimeModal(false);
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
        { path: 'trainer-subscription?v=20260450', label: 'Подписка', hint: 'Тариф и оплата', icon: 'card', badge: null },
        { path: 'trainer-stats', label: 'Статистика', hint: 'Показатели и динамика', icon: 'chart', badge: null, tier: 'analytics' },
        { path: 'trainer-referral', label: 'Рефералы', hint: 'Пригласи коллегу', icon: 'gift', badge: 'NEW' },
      ];

      function tilesToRender() {
        var out = [];
        TILES.forEach(function(t) {
          if (t.feature === 'groups' && (!hubGroupClassesEnabled || !hubGroupsModuleEnabled)) return;
          if (t.tier === 'analytics') {
            if (getInitData() && !hubSubscriptionStatusReady) {
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
            if (btn.classList.contains('hub-tile--locked')) return;
            navigateTo(btn.getAttribute('data-path'));
          };
        });
        applyHubLockedState();
      }

      /** Skeleton rows while GET /trainer/bookings is in flight (active trainer). */
      function buildHubBookingsSkeletonHtml() {
        var row =
          '<div class="hub-skel-booking-row" aria-hidden="true">' +
          '<div class="hub-skel-booking-left">' +
          '<div class="hub-skel-booking-time hub-skel-shimmer"></div>' +
          '<div class="hub-skel-booking-venue hub-skel-shimmer"></div>' +
          '<div class="hub-skel-booking-client hub-skel-shimmer"></div>' +
          '</div>' +
          '<div class="hub-skel-booking-meta">' +
          '<div class="hub-skel-booking-badge hub-skel-shimmer"></div>' +
          '<div class="hub-skel-booking-msg hub-skel-shimmer"></div>' +
          '</div>' +
          '</div>';
        var parts = [
          '<div class="hub-bookings-skel" role="status" aria-busy="true" aria-label="Загрузка записей">',
        ];
        for (var i = 0; i < 3; i++) {
          parts.push(row);
        }
        parts.push('</div>');
        return parts.join('');
      }

      /** Cold bootstrap: HTML may be cached without skeleton; keep placeholder until renderBookings / loadBookings. */
      function ensureHubBookingsPlaceholder() {
        if (!getInitData()) return;
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
              if (b.first_client_online_pending) prev.first_client_online_pending = true;
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

      function hubTodayYmdMinsk() {
        try {
          return new Intl.DateTimeFormat('en-CA', {
            timeZone: 'Europe/Minsk',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
          }).format(new Date());
        } catch (eMinsk) {
          var t = new Date();
          return (
            t.getFullYear() +
            '-' +
            String(t.getMonth() + 1).padStart(2, '0') +
            '-' +
            String(t.getDate()).padStart(2, '0')
          );
        }
      }

      /** Belarus / trainer hub: wall clock Europe/Minsk ≈ UTC+3 (no DST). */
      function hubMinskWallStartUtcMs(slotDateStr, startHHMM) {
        var p = String(slotDateStr || '').split('-');
        var tt = String(startHHMM || '').slice(0, 5).split(':');
        if (p.length !== 3 || tt.length !== 2) return null;
        var y = parseInt(p[0], 10);
        var mo = parseInt(p[1], 10) - 1;
        var d = parseInt(p[2], 10);
        var h = parseInt(tt[0], 10);
        var mi = parseInt(tt[1], 10);
        if ([y, mo, d, h, mi].some(function(x) {
          return isNaN(x);
        }))
          return null;
        return Date.UTC(y, mo, d, h - 3, mi, 0);
      }

      function hubEstimateRemainingStartsToday(daysForHub) {
        var todayStr = hubTodayYmdMinsk();
        var dayRow = null;
        (daysForHub || []).some(function(d) {
          if (d && d.date === todayStr) {
            dayRow = d;
            return true;
          }
          return false;
        });
        if (!dayRow || !dayRow.bookings) return 0;
        var bs = dedupeHubDayBookings(dayRow.bookings);
        var nowMs = Date.now();
        var rem = 0;
        bs.forEach(function(b) {
          if (!b || b.slot_date == null || b.start_time == null) return;
          var ms = hubMinskWallStartUtcMs(String(b.slot_date), String(b.start_time));
          if (ms != null && ms > nowMs) rem++;
        });
        return rem;
      }

      /** Fallback when API omits week_sessions: all deduped hub rows with start strictly after now (Minsk wall). */
      function hubEstimateRemainingAllBookings(daysForHub) {
        var nowMs = Date.now();
        var rem = 0;
        (daysForHub || []).forEach(function(d) {
          var bs = dedupeHubDayBookings(d.bookings || []);
          bs.forEach(function(b) {
            if (!b || b.slot_date == null || b.start_time == null) return;
            var ms = hubMinskWallStartUtcMs(String(b.slot_date), String(b.start_time));
            if (ms != null && ms > nowMs) rem++;
          });
        });
        return rem;
      }

      /** Non-negative int from hub summary payload, or null if absent/invalid. */
      function hubTrainerSessionSummaryInt(v) {
        if (v === null || v === undefined || v === '') return null;
        var n = typeof v === 'number' ? v : parseInt(String(v), 10);
        if (!Number.isFinite(n) || n < 0) return null;
        return Math.floor(n);
      }

      function renderBookings(daysOrPayload) {
        var rawDays = Array.isArray(daysOrPayload)
          ? daysOrPayload
          : daysOrPayload && daysOrPayload.days;
        var todaySessions =
          daysOrPayload &&
          typeof daysOrPayload === 'object' &&
          !Array.isArray(daysOrPayload)
            ? daysOrPayload.today_sessions
            : null;
            var weekSessions =
          daysOrPayload &&
          typeof daysOrPayload === 'object' &&
          !Array.isArray(daysOrPayload)
            ? daysOrPayload.week_sessions
            : null;
        if (
          daysOrPayload &&
          typeof daysOrPayload === 'object' &&
          !Array.isArray(daysOrPayload) &&
          typeof daysOrPayload.force_client_chat_relay !== 'undefined'
        ) {
          hubForceClientChatRelay = !!daysOrPayload.force_client_chat_relay;
          if (typeof window !== 'undefined') window.TRAINER_HUB_FORCE_CLIENT_CHAT_RELAY = hubForceClientChatRelay;
        }
        var daysForHub = dedupeHubBookingsDays(rawDays || []);
        var relayClientByBookingId = {};
        daysForHub.forEach(function(d) {
          (d.bookings || []).forEach(function(b) {
            var hc = hubTrainerContactEligibleForBooking(b);
            if (!hc || b.id == null || b.id === '') return;
            relayClientByBookingId[String(b.id)] = hc.clientId;
          });
        });
        if (typeof window !== 'undefined') window.__hubRelayClientIdByBookingId = relayClientByBookingId;

        hubLastBookingsDays = daysForHub;
        hubLastBookingsPayloadForAccentRefetch =
          daysOrPayload && typeof daysOrPayload === 'object' && !Array.isArray(daysOrPayload)
            ? daysOrPayload
            : { days: rawDays || [], today_sessions: todaySessions, week_sessions: weekSessions };
        if (
          getInitData() &&
          !hubMyServicesAccentPrefetchDone &&
          !hubMyServicesAccentPrefetchInFlight &&
          daysForHub.some(function(d) {
            return (d.bookings || []).some(function(b) {
              return b && b.service_id != null;
            });
          })
        ) {
          hubMyServicesAccentPrefetchInFlight = true;
          fetch(apiUrlWithQuery('/trainer/my-services'), { headers: headersJson(), cache: 'no-store' })
            .then(function(r) {
              return r.json().then(function(j) {
                return { ok: r.ok, j: j };
              });
            })
            .then(function(x) {
              if (x.ok && x.j && x.j.services) syncHubMyServicesAccentMap(x.j.services);
            })
            .catch(function() {
              /* noop */
            })
            .finally(function() {
              hubMyServicesAccentPrefetchDone = true;
              hubMyServicesAccentPrefetchInFlight = false;
              if (hubLastBookingsPayloadForAccentRefetch) {
                renderBookings(hubLastBookingsPayloadForAccentRefetch);
              }
            });
        }
        var block = document.getElementById('bookingsBlock');
        var todayCount = 0;
        var weekCount = 0;

        var todayStr = hubTodayYmdMinsk();

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

        var tsTotal = hubTrainerSessionSummaryInt(todaySessions && todaySessions.total);
        var tsRem = hubTrainerSessionSummaryInt(todaySessions && todaySessions.remaining);
        var wsTotal = hubTrainerSessionSummaryInt(weekSessions && weekSessions.total);
        var wsRem = hubTrainerSessionSummaryInt(weekSessions && weekSessions.remaining);

        hubLastTodayCount = tsTotal !== null ? tsTotal : todayCount;
        hubLastTodayRemaining = tsRem !== null ? tsRem : hubEstimateRemainingStartsToday(daysForHub);
        hubLastFirstWhen = firstWhen;
        hubLastWeekCount = wsTotal !== null ? wsTotal : weekCount;
        hubLastWeekRemaining = wsRem !== null ? wsRem : hubEstimateRemainingAllBookings(daysForHub);

        var maxN = HUB_UPCOMING_BOOKINGS_MAX;
        var totalBookings = 0;
        daysForHub.forEach(function(day) {
          totalBookings += (day.bookings || []).length;
        });

        var count = 0;
        var pendingInNearestStrip = 0;
        var parts = [];
        var hasFirstOnline = false;
        daysForHub.forEach(function(d) {
          (d.bookings || []).forEach(function(b) {
            if (b && b.first_client_online_pending) hasFirstOnline = true;
          });
        });

        daysForHub.forEach(function(day) {
          if (count >= maxN) return;
          var bs = day.bookings || [];
          if (!bs.length) return;
          parts.push('<div class="hub-day-label">' + escapeHtml(dayHeaderLine(day)) + '</div>');
          parts.push('<div class="hub-bookings-stack">');
          bs.forEach(function(b) {
            if (count >= maxN) return;
            if (b && String(b.status || '').toLowerCase() === 'pending') pendingInNearestStrip += 1;
            var timeRange = (b.start_time || '') + '–' + (b.end_time || '');
            parts.push(hubBookingSlotRowHtml(b, timeRange));
            count++;
          });
          parts.push('</div>');
        });

        hubLastPendingInNearestStripCount = pendingInNearestStrip;
        hubLastUpcomingListCount = count;
        syncHubHeroCompact();
        applyHubHero();

        if (!count) {
          hubPendingHighlightBookingId = null;
          block.innerHTML = buildEmptyBookingsHtml();
          block.onclick = null;
          wireEmptyScheduleButton();
          tryOpenHubGroupModalFromUrl();
          renderHubSummaryHints();
          return;
        }
        if (hasFirstOnline) {
          parts.unshift(
            '<div class="hub-first-online-hint" role="status">✨ Первая онлайн-запись — клиент записался сам</div>'
          );
        }
        var capHint = '';
        if (totalBookings > maxN) {
          capHint = '<div class="hub-bookings-cap">Показаны ' + maxN + ' ближайших записей из ' + totalBookings + '</div>';
        }
        block.innerHTML = parts.join('') + capHint;
        applyHubPendingBookingHighlight();
        if (window.wireHubSlotMessageButtons) {
          try {
            window.wireHubSlotMessageButtons(block);
          } catch (e) { /* noop */ }
        }
        block.onclick = function(ev) {
          var msgBtn = ev.target && ev.target.closest && ev.target.closest('button.hub-slot-msg[data-hub-dm]');
          if (msgBtn) {
            ev.preventDefault();
            ev.stopPropagation();
            var UiRgBlock = window.TrainerClientRelayUi;
            var wfB = window.TRAINER_WEBAPP_FORCE_CLIENT_CHAT_RELAY;
            var hubFb = window.TRAINER_HUB_FORCE_CLIENT_CHAT_RELAY;
            var relayForceBlock =
              wfB === true ||
              wfB === 1 ||
              wfB === '1' ||
              hubFb === true ||
              hubFb === 1 ||
              hubFb === '1';
            var hubWantsRelayBlock =
              UiRgBlock && typeof UiRgBlock.hubBookingButtonWantsRelay === 'function'
                ? UiRgBlock.hubBookingButtonWantsRelay(msgBtn)
                : msgBtn.getAttribute('data-hub-relay') === '1' || relayForceBlock;
            if (hubWantsRelayBlock) {
              var UiHub = window.TrainerClientRelayUi;
              var openedHub =
                UiHub &&
                typeof UiHub.openRelayFromBookingButton === 'function' &&
                UiHub.openRelayFromBookingButton(msgBtn);
              if (!openedHub) {
                var Hoff = window.TrainerRelayHelpers;
                openedHub =
                  Hoff && typeof Hoff.openRelayFromHubButton === 'function' && Hoff.openRelayFromHubButton(msgBtn);
              }
              if (!openedHub) {
                var wgFb = window.Telegram && window.Telegram.WebApp;
                if (wgFb && typeof wgFb.showAlert === 'function') {
                  try {
                    wgFb.showAlert(
                      'Не удалось открыть переписку через бота. Обновите страницу или откройте мини-приложение снова.'
                    );
                  } catch (eFb) { /* noop */ }
                }
              }
              return;
            }
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
        /* Rhythm + summary strip read hubLast* pending — refresh right after list hydrates (bootstrap order). */
        renderHubSummaryHints();
      }

      /** Upcoming bookings: friendly onboarding instead of red «network» when account not active yet. */
      function renderBookingsOnboardingBlock(access) {
        setStateMessage('', '');
        hubLastBookingsDays = null;
        hubLastTodayCount = 0;
        hubLastTodayRemaining = 0;
        hubLastFirstWhen = '';
        hubLastWeekCount = 0;
        hubLastWeekRemaining = 0;
        hubLastUpcomingListCount = 0;
        hubLastPendingCount = 0;
        hubLastPendingInNearestStripCount = 0;
        hubMtdRevenueText = null;
        syncHubHeroCompact();
        applyHubHero();
        var bb = document.getElementById('bookingsBlock');
        if (window.TrainerMiniAppGate && access) {
          bb.innerHTML =
            '<div class="bd-trainer-gate" style="margin-top:4px">' +
            window.TrainerMiniAppGate.gateCardHtml(access, true) +
            '</div>';
          window.TrainerMiniAppGate.wireGate(bb, getInitData());
        } else {
          bb.innerHTML =
            '<div class="hub-empty">Раздел откроется после активации профиля. Заполните анкету в «Первые шаги» или дождитесь проверки — это не сбой сети.</div>';
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
        if (!getInitData()) {
          setStateMessage('', '');
          hubLastBookingsDays = null;
          hubLastTodayCount = 0;
          hubLastTodayRemaining = 0;
          hubLastFirstWhen = '';
          hubLastWeekCount = 0;
          hubLastWeekRemaining = 0;
          hubLastUpcomingListCount = 0;
          hubLastPendingCount = 0;
          hubLastPendingInNearestStripCount = 0;
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
              if (window.TrainerMiniAppGate && getInitData()) {
                return window.TrainerMiniAppGate.fetchAccess(getInitData())
                  .then(function(a) {
                    trainerAccessSnapshot = a;
                    syncHubForceClientChatRelayFromTrainerAccess();
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
              hubLastTodayRemaining = 0;
              hubLastFirstWhen = '';
              hubLastWeekCount = 0;
              hubLastWeekRemaining = 0;
              hubLastUpcomingListCount = 0;
              hubLastPendingCount = 0;
              hubLastPendingInNearestStripCount = 0;
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
            renderBookings(o.data || {});
            /* Refresh checklist so has_completed_booking / last client id stay in sync after mark-complete in schedule. */
            loadOnboardingChecklist();
          })
          .catch(function(err) {
            if (err && err.name === 'AbortError') return;
            setStateMessage('', '');
            /* Offline / timeout: if account likely not active, avoid scary copy */
            if (window.TrainerMiniAppGate && getInitData()) {
              window.TrainerMiniAppGate.fetchAccess(getInitData())
                .then(function(a) {
                  trainerAccessSnapshot = a;
                  syncHubForceClientChatRelayFromTrainerAccess();
                  applyHubLockedState();
                  if (!window.TrainerMiniAppGate.isActive(a)) {
                    renderBookingsOnboardingBlock(a);
                  } else {
                    hubLastBookingsDays = null;
                    hubLastTodayCount = 0;
                    hubLastTodayRemaining = 0;
                    hubLastFirstWhen = '';
                    hubLastWeekCount = 0;
                    hubLastWeekRemaining = 0;
                    hubLastUpcomingListCount = 0;
                    hubLastPendingCount = 0;
                    hubLastPendingInNearestStripCount = 0;
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
                  hubLastTodayRemaining = 0;
                  hubLastFirstWhen = '';
                  hubLastWeekCount = 0;
                  hubLastWeekRemaining = 0;
                  hubLastUpcomingListCount = 0;
                  hubLastPendingCount = 0;
                  hubLastPendingInNearestStripCount = 0;
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
              hubLastTodayRemaining = 0;
              hubLastFirstWhen = '';
              hubLastWeekCount = 0;
              hubLastWeekRemaining = 0;
              hubLastUpcomingListCount = 0;
              hubLastPendingCount = 0;
              hubLastPendingInNearestStripCount = 0;
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

      var hubShareBookingLinkMeta = null;
      /** Last fetched link for modal copy — avoids async clipboard after fetch (Telegram WebView often blocks that). */
      var hubShareBookingLinkPrefetch = null;

      /**
       * Sync copy fallback for Mini App WebViews where Clipboard API fails or loses user activation after await/fetch.
       */
      function copyTextViaExecCommandHub(text) {
        if (!text) return false;
        try {
          var ta = document.createElement('textarea');
          ta.value = text;
          ta.setAttribute('readonly', '');
          ta.setAttribute('aria-hidden', 'true');
          ta.style.position = 'fixed';
          ta.style.left = '0';
          ta.style.top = '0';
          ta.style.width = '1px';
          ta.style.height = '1px';
          ta.style.opacity = '0';
          ta.style.padding = '0';
          ta.style.border = 'none';
          ta.style.margin = '0';
          document.body.appendChild(ta);
          ta.focus();
          ta.select();
          ta.setSelectionRange(0, text.length);
          var ok = false;
          try {
            ok = document.execCommand('copy');
          } catch (eExec) {}
          document.body.removeChild(ta);
          return !!ok;
        } catch (e) {
          return false;
        }
      }

      function copyTextToClipboardHub(value) {
        if (!value) return Promise.resolve(false);
        if (copyTextViaExecCommandHub(value)) return Promise.resolve(true);
        if (!(navigator.clipboard && navigator.clipboard.writeText)) {
          return Promise.resolve(false);
        }
        return navigator.clipboard.writeText(value).then(function() {
          return true;
        }).catch(function() {
          return false;
        });
      }

      function closeHubFillSlotsInvitesModal() {
        var overlay = document.getElementById('hubModalFillSlotsInvites');
        if (!overlay) return;
        hubFillSlotsInviteContext.slotId = null;
        hubFillSlotsInviteContext.excludeClientId = null;
        var lead = document.querySelector('.hub-fill-slots-invites-lead');
        if (lead) {
          lead.innerHTML =
            'Отметьте клиентов. Письмо уходит в <b>клиентском боте</b>; фильтры <b>Без записи</b> / <b>Все</b> — под списком.';
        }
        overlay.style.display = 'none';
        overlay.setAttribute('aria-hidden', 'true');
      }

      /** Bulk checkbox presets for fill-slots modal (dataset data-has-upcoming on cards). */
      function hubFillSlotsBulkSet(host, mode) {
        if (!host) return;
        host.querySelectorAll('.hub-fill-slots-card').forEach(function(card) {
          var cb = card.querySelector('input.hub-fill-slots-pick');
          if (!cb) return;
          var hasUp = card.getAttribute('data-has-upcoming') === '1';
          if (mode === 'none') cb.checked = false;
          else if (mode === 'all') cb.checked = true;
          else if (mode === 'no_upcoming') cb.checked = !hasUp;
        });
        hubFillSlotsUpdateSendButtonLabel();
      }

      function hubFillSlotsSelectedCount(host) {
        if (!host) return 0;
        return host.querySelectorAll('input.hub-fill-slots-pick:checked').length;
      }

      function hubFillSlotsUpdateSendButtonLabel() {
        var host = document.getElementById('hubFillSlotsInvitesHost');
        var btn = document.getElementById('hubFillSlotsInvitesSend');
        if (!btn || !host) return;
        var n = hubFillSlotsSelectedCount(host);
        btn.textContent = n > 0 ? 'Отправить (' + n + ')' : 'Отправить';
        btn.disabled = n === 0 || btn.dataset.sending === '1';
      }

      function renderHubFillSlotsInvitesModalBody(clients, slotInfo) {
        var host = document.getElementById('hubFillSlotsInvitesHost');
        if (!host) return;
        host.innerHTML = '';
        if (slotInfo && slotInfo.label) {
          var slotNote = document.createElement('p');
          slotNote.className = 'hub-fill-slots-slot-note';
          slotNote.style.marginBottom = '12px';
          slotNote.style.fontSize = '14px';
          slotNote.style.color = 'var(--tg-theme-hint-color, #666)';
          slotNote.textContent = 'Сообщение будет про освободившееся окно: ' + String(slotInfo.label);
          host.appendChild(slotNote);
        }
        if (!clients.length) {
          var emptyWrap = document.createElement('div');
          emptyWrap.className = 'hub-fill-slots-empty-state';
          var p = document.createElement('p');
          p.className = 'hub-fill-slots-empty';
          p.textContent =
            'Нет клиентов с привязанным Telegram — напоминание через бот недоступно. Подключите клиентов в разделе «Клиенты» или добавьте новых.';
          emptyWrap.appendChild(p);
          var cta = document.createElement('button');
          cta.type = 'button';
          cta.className = 'btn-block btn-primary hub-fill-slots-empty-cta';
          cta.textContent = 'Открыть раздел «Клиенты»';
          cta.onclick = function() {
            closeHubFillSlotsInvitesModal();
            navigateTo('trainer-clients');
          };
          emptyWrap.appendChild(cta);
          host.appendChild(emptyWrap);
          return;
        }
        if (clients.length >= 250) {
          var capNote = document.createElement('p');
          capNote.className = 'hub-fill-slots-cap-note';
          capNote.textContent =
            'Показаны первые 250 клиентов с Telegram. Если база больше — отправьте этому списку, затем откройте окно снова.';
          host.appendChild(capNote);
        }
        var toolbar = document.createElement('div');
        toolbar.className = 'hub-fill-slots-bulk-toolbar';
        toolbar.setAttribute('role', 'group');
        toolbar.setAttribute('aria-label', 'Быстрый выбор получателей');
        [['Без записи', 'no_upcoming'], ['Все', 'all'], ['Снять', 'none']].forEach(function(pair) {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'hub-fill-slots-bulk-btn';
          b.textContent = pair[0];
          (function(mode) {
            b.onclick = function() {
              hubFillSlotsBulkSet(host, mode);
            };
          })(pair[1]);
          toolbar.appendChild(b);
        });
        host.appendChild(toolbar);

        for (var idx = 0; idx < clients.length; idx++) {
          var c = clients[idx];
          var hasUpcoming = !!(c && c.has_upcoming_booking);
          var card = document.createElement('div');
          card.className = 'hub-fill-slots-card';
          card.setAttribute('data-has-upcoming', hasUpcoming ? '1' : '0');
          var pickRow = document.createElement('label');
          pickRow.className = 'hub-fill-slots-pick-row';
          var cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.className = 'hub-fill-slots-pick';
          cb.value = c && c.id != null ? String(c.id) : '';
          cb.checked = !hasUpcoming;
          cb.addEventListener('change', hubFillSlotsUpdateSendButtonLabel);
          pickRow.appendChild(cb);
          var meta = document.createElement('span');
          meta.className = 'hub-fill-slots-pick-meta';
          var nameRow = document.createElement('span');
          nameRow.className = 'hub-fill-slots-name-row';
          var nameEl = document.createElement('span');
          nameEl.className = 'hub-fill-slots-pick-name';
          nameEl.textContent = c && c.display_name ? String(c.display_name) : 'Клиент';
          nameRow.appendChild(nameEl);
          var badge = document.createElement('span');
          badge.className =
            'hub-fill-slots-status-badge ' +
            (hasUpcoming ? 'hub-fill-slots-status-badge--busy' : 'hub-fill-slots-status-badge--free');
          badge.textContent = hasUpcoming ? 'Есть запись' : 'Без записи';
          nameRow.appendChild(badge);
          meta.appendChild(nameRow);
          pickRow.appendChild(meta);
          card.appendChild(pickRow);
          if (c && c.reason_line) {
            var reasonEl = document.createElement('div');
            reasonEl.className = 'hub-fill-slots-card-reason';
            reasonEl.textContent = String(c.reason_line);
            card.appendChild(reasonEl);
          }
          host.appendChild(card);
        }
        var sendWrap = document.createElement('div');
        sendWrap.className = 'hub-fill-slots-send-wrap';
        var sendBtn = document.createElement('button');
        sendBtn.type = 'button';
        sendBtn.id = 'hubFillSlotsInvitesSend';
        sendBtn.className = 'btn-block btn-primary';
        sendBtn.textContent = 'Отправить';
          sendBtn.onclick = function() {
          var ids = [];
          host.querySelectorAll('input.hub-fill-slots-pick:checked').forEach(function(el) {
            var id = parseInt(String(el.value || ''), 10);
            if (!isNaN(id) && id > 0) ids.push(id);
          });
          if (!ids.length) {
            hubToast('Выберите хотя бы одного клиента с подключённым Telegram.');
            return;
          }
          sendBtn.dataset.sending = '1';
          sendBtn.disabled = true;
          sendBtn.textContent = 'Отправляем…';
          var payload = { client_ids: ids };
          if (hubFillSlotsInviteContext.slotId) {
            payload.slot_id = hubFillSlotsInviteContext.slotId;
          }
          if (hubFillSlotsInviteContext.excludeClientId) {
            payload.exclude_client_id = hubFillSlotsInviteContext.excludeClientId;
          }
          fetch(apiUrlWithQuery('/trainer/hub/fill-slots-invites/send'), {
            method: 'POST',
            headers: headersJson(),
            body: JSON.stringify(payload),
          })
            .then(function(r) {
              return r.json().then(function(data) {
                return { ok: r.ok, data: data, status: r.status };
              });
            })
            .then(function(o) {
              if (!o.ok) {
                var det = o.data && o.data.detail;
                var msgErr =
                  typeof det === 'string'
                    ? det
                    : Array.isArray(det) && det[0] && det[0].msg
                      ? det[0].msg
                      : 'Не удалось отправить (' + o.status + ').';
                throw new Error(msgErr);
              }
              var sent = (o.data && o.data.sent) || [];
              var failed = (o.data && o.data.failed) || [];
              var skipped = (o.data && o.data.skipped_no_telegram) || [];
              var parts = [];
              if (sent.length) parts.push('Отправлено: ' + sent.length);
              if (failed.length) parts.push('Ошибок: ' + failed.length);
              if (skipped.length) parts.push('Без Telegram: ' + skipped.length);
              hubToast(parts.length ? parts.join(' · ') : 'Готово.');
              closeHubFillSlotsInvitesModal();
            })
            .catch(function(err) {
              hubToast((err && err.message) || 'Ошибка отправки.');
            })
            .finally(function() {
              delete sendBtn.dataset.sending;
              sendBtn.disabled = false;
              hubFillSlotsUpdateSendButtonLabel();
            });
        };
        sendWrap.appendChild(sendBtn);
        host.appendChild(sendWrap);
        hubFillSlotsUpdateSendButtonLabel();
      }

      function renderHubFillSlotsInvitesSkeleton(withSlotNote) {
        var host = document.getElementById('hubFillSlotsInvitesHost');
        if (!host) return;
        host.innerHTML = '';
        var root = document.createElement('div');
        root.className = 'hub-fill-slots-skel';
        root.setAttribute('aria-busy', 'true');
        root.setAttribute('aria-label', 'Загрузка списка клиентов');
        if (withSlotNote) {
          var note = document.createElement('div');
          note.className = 'hub-fill-slots-skel-slot-note hub-skel-shimmer';
          note.setAttribute('aria-hidden', 'true');
          root.appendChild(note);
        }
        function skelCard() {
          var card = document.createElement('div');
          card.className = 'hub-fill-slots-skel-card';
          var row = document.createElement('div');
          row.className = 'hub-fill-slots-skel-pick';
          var cb = document.createElement('div');
          cb.className = 'hub-fill-slots-skel-cb hub-skel-shimmer';
          cb.setAttribute('aria-hidden', 'true');
          var col = document.createElement('div');
          col.className = 'hub-fill-slots-skel-textcol';
          var l1 = document.createElement('div');
          l1.className =
            'hub-fill-slots-skel-line hub-fill-slots-skel-line--name hub-skel-shimmer';
          l1.setAttribute('aria-hidden', 'true');
          var l2 = document.createElement('div');
          l2.className =
            'hub-fill-slots-skel-line hub-fill-slots-skel-line--reason hub-skel-shimmer';
          l2.setAttribute('aria-hidden', 'true');
          col.appendChild(l1);
          col.appendChild(l2);
          row.appendChild(cb);
          row.appendChild(col);
          card.appendChild(row);
          return card;
        }
        root.appendChild(skelCard());
        root.appendChild(skelCard());
        var send = document.createElement('div');
        send.className = 'hub-fill-slots-skel-send hub-skel-shimmer';
        send.setAttribute('aria-hidden', 'true');
        root.appendChild(send);
        host.appendChild(root);
      }

      function openHubFillSlotsInvitesFlow(slotIdOpt, excludeClientIdOpt) {
        hubFillSlotsInviteContext.slotId =
          slotIdOpt != null && !isNaN(parseInt(String(slotIdOpt), 10)) && parseInt(String(slotIdOpt), 10) > 0
            ? parseInt(String(slotIdOpt), 10)
            : null;
        hubFillSlotsInviteContext.excludeClientId =
          excludeClientIdOpt != null &&
          !isNaN(parseInt(String(excludeClientIdOpt), 10)) &&
          parseInt(String(excludeClientIdOpt), 10) > 0
            ? parseInt(String(excludeClientIdOpt), 10)
            : null;
        var lead = document.querySelector('.hub-fill-slots-invites-lead');
        if (lead) {
          if (hubFillSlotsInviteContext.slotId) {
            lead.innerHTML =
              'Это окно в сообщении (дата и время). Клиент жмёт «Записаться» в своём боте.';
          } else {
            lead.innerHTML =
              'Отметьте клиентов. Письмо уходит в <b>клиентском боте</b>; фильтры <b>Без записи</b> / <b>Все</b> — под списком.';
          }
        }
        ensureTrainerSectionsAccess(function() {
          var overlay = document.getElementById('hubModalFillSlotsInvites');
          var host = document.getElementById('hubFillSlotsInvitesHost');
          if (!overlay || !host) return;
          renderHubFillSlotsInvitesSkeleton(!!hubFillSlotsInviteContext.slotId);
          overlay.style.display = 'flex';
          overlay.setAttribute('aria-hidden', 'false');

          var path = '/trainer/hub/fill-slots-invites';
          var q = [
            'limit=' + encodeURIComponent('250'),
            'include_with_upcoming=' + encodeURIComponent('true'),
          ];
          if (hubFillSlotsInviteContext.slotId) {
            q.push('slot_id=' + encodeURIComponent(String(hubFillSlotsInviteContext.slotId)));
          }
          if (hubFillSlotsInviteContext.excludeClientId) {
            q.push('exclude_client_id=' + encodeURIComponent(String(hubFillSlotsInviteContext.excludeClientId)));
          }
          path += '?' + q.join('&');

          fetch(apiUrlWithQuery(path), { headers: headersJson() })
            .then(function(r) {
              return r.json().then(function(data) {
                return { ok: r.ok, data: data, status: r.status };
              });
            })
            .then(function(o) {
              if (!o.ok) {
                var det = o.data && o.data.detail;
                throw new Error(
                  typeof det === 'string' ? det : 'Не удалось загрузить подсказки (' + o.status + ').'
                );
              }
              return o.data || {};
            })
            .then(function(data) {
              var clients = (data && data.clients) || [];
              var slot = data && data.slot ? data.slot : null;
              renderHubFillSlotsInvitesModalBody(clients, slot);
            })
            .catch(function(err) {
              hubToast((err && err.message) || 'Не удалось загрузить подсказки.');
              closeHubFillSlotsInvitesModal();
            });
        });
      }

      function stripHubFillSlotsQueryFromUrl() {
        try {
          var params = new URLSearchParams(window.location.search || '');
          if (params.get('open_fill_slots') !== '1') return;
          params.delete('open_fill_slots');
          params.delete('fill_slot_id');
          params.delete('fill_exclude_client_id');
          var ns = params.toString();
          var clean = window.location.pathname + (ns ? '?' + ns : '') + (window.location.hash || '');
          window.history.replaceState({}, '', clean);
        } catch (e) {
          /* */
        }
      }

      function tryOpenHubFillSlotsFromUrl() {
        try {
          var params = new URLSearchParams(window.location.search || '');
          if (params.get('open_fill_slots') !== '1') return;
          var sid = params.get('fill_slot_id');
          var ex = params.get('fill_exclude_client_id');
          var slotId = sid ? parseInt(sid, 10) : NaN;
          var exId = ex ? parseInt(ex, 10) : NaN;
          stripHubFillSlotsQueryFromUrl();
          if (!isNaN(slotId) && slotId > 0) {
            openHubFillSlotsInvitesFlow(
              slotId,
              !isNaN(exId) && exId > 0 ? exId : null
            );
          } else {
            openHubFillSlotsInvitesFlow(null, null);
          }
        } catch (e) {
          /* */
        }
      }

      function wireHubFillSlotsInvitesModal() {
        var overlay = document.getElementById('hubModalFillSlotsInvites');
        var closeBtn = document.getElementById('hubFillSlotsInvitesClose');
        var schedBtn = document.getElementById('hubFillSlotsInvitesSchedule');
        if (overlay && !overlay.dataset.fillSlotsWired) {
          overlay.dataset.fillSlotsWired = '1';
          overlay.onclick = function(ev) {
            if (ev.target === overlay) closeHubFillSlotsInvitesModal();
          };
        }
        if (closeBtn && !closeBtn.dataset.fillSlotsWired) {
          closeBtn.dataset.fillSlotsWired = '1';
          closeBtn.onclick = function() {
            closeHubFillSlotsInvitesModal();
          };
        }
        if (schedBtn && !schedBtn.dataset.fillSlotsWired) {
          schedBtn.dataset.fillSlotsWired = '1';
          schedBtn.onclick = function() {
            closeHubFillSlotsInvitesModal();
            navigateTo('schedule-editor');
          };
        }
      }

      /** Server-side funnel: first time trainer copied a client-facing booking/invite link. */
      function postHubClientInviteLinkFirstCopyRecorded() {
        if (!getInitData()) return;
        fetch(apiUrlWithQuery('/trainer/welcome-link/first-copy'), {
          method: 'POST',
          headers: headersJson(),
        }).catch(function() {});
      }

      function applyHubShareButtonVisibility() {
        var btn = document.getElementById('hubShareBookingLinkBtn');
        if (!btn) return;
        // Universal invite link works for all trainers — not gated on online booking tier
        var allowed = !!getInitData();
        btn.hidden = !allowed;
        btn.disabled = !allowed;
      }

      function loadHubPublicBookingLinkMeta() {
        if (hubShareBookingLinkMeta) return Promise.resolve(hubShareBookingLinkMeta);
        return fetch(apiUrlWithQuery('/trainer/public-booking-link/eligibility'), { headers: headersJson() })
          .then(function(r) {
            return r.json().then(function(data) {
              if (!r.ok) throw new Error((data && data.detail) || r.statusText || 'Ошибка');
              return data;
            });
          })
          .then(function(meta) {
            hubShareBookingLinkMeta = meta || null;
            return hubShareBookingLinkMeta;
          });
      }

      function requestHubPublicBookingLink(serviceId) {
        var url = apiUrlWithQuery('/trainer/public-booking-link');
        if (serviceId != null) {
          url += '&service_id=' + encodeURIComponent(String(serviceId));
        }
        return fetch(url, { headers: headersJson() }).then(function(r) {
          return r.json().then(function(data) {
            if (!r.ok) throw new Error((data && data.detail) || r.statusText || 'Ошибка');
            return data;
          });
        });
      }

      function closeHubShareBookingLinkModal() {
        var ov = document.getElementById('hubModalShareBookingLink');
        if (!ov) return;
        hubShareBookingLinkPrefetch = null;
        ov.style.display = 'none';
        ov.setAttribute('aria-hidden', 'true');
      }

      function scheduleHubShareBookingLinkPrefetch(serviceSelect) {
        if (!serviceSelect) return;
        var sid = parseInt(serviceSelect.value || '', 10);
        if (isNaN(sid) || sid <= 0) return;
        hubShareBookingLinkPrefetch = null;
        requestHubPublicBookingLink(sid)
          .then(function(payload) {
            var link = payload && payload.booking_link ? String(payload.booking_link).trim() : '';
            if (link) hubShareBookingLinkPrefetch = { sid: sid, link: link };
          })
          .catch(function() {
            hubShareBookingLinkPrefetch = null;
          });
      }

      function setHubShareBookingLinkError(text, isError) {
        var errEl = document.getElementById('hubShareLinkError');
        if (!errEl) return;
        if (!text) {
          errEl.style.display = 'none';
          errEl.textContent = '';
          errEl.style.color = '';
          return;
        }
        errEl.textContent = text;
        errEl.style.display = 'block';
        errEl.style.color = isError ? 'var(--app-danger)' : 'var(--tg-theme-hint-color)';
      }

      function showHubShareLinkManualCopy(link, hint, asError) {
        var previewWrap = document.getElementById('hubShareLinkPreviewWrap');
        var preview = document.getElementById('hubShareLinkPreview');
        if (previewWrap) previewWrap.style.display = 'block';
        if (preview) {
          preview.value = link || '';
          try {
            preview.focus();
            preview.select();
          } catch (eFocus) {}
        }
        var err = asError !== false;
        if (hint !== undefined && hint !== null && String(hint).length) {
          setHubShareBookingLinkError(String(hint), err);
        } else {
          setHubShareBookingLinkError('', false);
        }
      }

      /**
       * @param {object} meta eligibility payload
       * @param {{ skipPrefetchOnce?: boolean }} [opts] when link already in hubShareBookingLinkPrefetch for current service
       */
      function openHubShareBookingLinkModal(meta, opts) {
        opts = opts || {};
        var overlay = document.getElementById('hubModalShareBookingLink');
        var serviceWrap = document.getElementById('hubShareLinkServiceWrap');
        var serviceSelect = document.getElementById('hubShareLinkServiceSelect');
        var previewWrap = document.getElementById('hubShareLinkPreviewWrap');
        if (!overlay || !serviceWrap || !serviceSelect || !previewWrap) return;
        var services = (meta && meta.services) || [];
        serviceSelect.innerHTML = '';
        services.forEach(function(s) {
          var sid = parseInt(String(s && s.id), 10);
          if (!sid) return;
          var opt = document.createElement('option');
          opt.value = String(sid);
          opt.textContent = (s && s.name) ? s.name : ('Услуга #' + sid);
          serviceSelect.appendChild(opt);
        });
        var leadEl = document.getElementById('hubShareLinkLead');
        if (leadEl) {
          if (services.length <= 1) {
            var s0 = services[0];
            var nm =
              s0 && s0.name
                ? String(s0.name).trim()
                : s0
                  ? 'Услуга #' + String(s0.id)
                  : 'услугу';
            leadEl.textContent =
              'Запись на «' +
              nm +
              '». Мы уведомим вас, как только клиент перейдёт по ссылке: нового контакта добавим в список; если он уже у вас в списке без Telegram — привяжем аккаунт.';
          } else {
            leadEl.textContent =
              'Выберите услугу — она подставится в ссылку. Мы уведомим вас в боте тренера, как только клиент перейдёт по ней: нового добавим в список; если он уже у вас в базе без Telegram — привяжем аккаунт.';
          }
        }
        serviceWrap.style.display = services.length > 1 ? '' : 'none';
        previewWrap.style.display = 'none';
        setHubShareBookingLinkError('', false);
        var copyBtn = document.getElementById('hubShareLinkCopy');
        if (copyBtn) {
          copyBtn.disabled = false;
          copyBtn.textContent = 'Скопировать ссылку';
        }
        overlay.style.display = 'flex';
        overlay.setAttribute('aria-hidden', 'false');
        serviceSelect.onchange = function() {
          scheduleHubShareBookingLinkPrefetch(serviceSelect);
        };
        if (!opts.skipPrefetchOnce) {
          scheduleHubShareBookingLinkPrefetch(serviceSelect);
        }
      }

      function wireHubShareBookingLinkModal() {
        var overlay = document.getElementById('hubModalShareBookingLink');
        var cancelBtn = document.getElementById('hubShareLinkCancel');
        var copyBtn = document.getElementById('hubShareLinkCopy');
        var serviceSelect = document.getElementById('hubShareLinkServiceSelect');
        if (cancelBtn) cancelBtn.onclick = closeHubShareBookingLinkModal;
        if (overlay) {
          overlay.onclick = function(ev) {
            if (ev.target === overlay) closeHubShareBookingLinkModal();
          };
        }
        if (copyBtn) {
          copyBtn.onclick = function() {
            var previewInDirect = document.getElementById('hubShareLinkPreview');
            var directLink = previewInDirect ? String(previewInDirect.value || '').trim() : '';
            if (directLink) {
              if (copyTextViaExecCommandHub(directLink)) {
                closeHubShareBookingLinkModal();
                dismissHubShareLinkGrowthHintPersisted();
                postHubClientInviteLinkFirstCopyRecorded();
                hubToast('Ссылка на запись скопирована. Отправьте её клиентам.');
                return;
              }
              copyBtn.disabled = true;
              copyBtn.textContent = 'Копируем...';
              copyTextToClipboardHub(directLink)
                .then(function(ok) {
                  if (ok) {
                    closeHubShareBookingLinkModal();
                    dismissHubShareLinkGrowthHintPersisted();
                    postHubClientInviteLinkFirstCopyRecorded();
                    hubToast('Ссылка на запись скопирована. Отправьте её клиентам.');
                    return;
                  }
                  setHubShareBookingLinkError('Скопируйте ссылку вручную из поля выше.', false);
                })
                .finally(function() {
                  copyBtn.disabled = false;
                  copyBtn.textContent = 'Скопировать ссылку';
                });
              return;
            }
            var sid = serviceSelect ? parseInt(serviceSelect.value || '', 10) : NaN;
            if (isNaN(sid) || sid <= 0) {
              setHubShareBookingLinkError('Выберите услугу.', true);
              return;
            }
            setHubShareBookingLinkError('', false);
            var pf = hubShareBookingLinkPrefetch;
            if (pf && pf.sid === sid && pf.link) {
              if (copyTextViaExecCommandHub(pf.link)) {
                closeHubShareBookingLinkModal();
                dismissHubShareLinkGrowthHintPersisted();
                postHubClientInviteLinkFirstCopyRecorded();
                hubToast('Ссылка на запись скопирована. Отправьте её клиентам.');
                return;
              }
              copyBtn.disabled = true;
              copyBtn.textContent = 'Копируем...';
              copyTextToClipboardHub(pf.link)
                .then(function(ok) {
                  if (ok) {
                    closeHubShareBookingLinkModal();
                    dismissHubShareLinkGrowthHintPersisted();
                    postHubClientInviteLinkFirstCopyRecorded();
                    hubToast('Ссылка на запись скопирована. Отправьте её клиентам.');
                    return;
                  }
                  showHubShareLinkManualCopy(pf.link, '', true);
                })
                .finally(function() {
                  copyBtn.disabled = false;
                  copyBtn.textContent = 'Скопировать ссылку';
                });
              return;
            }
            copyBtn.disabled = true;
            copyBtn.textContent = 'Готовим...';
            requestHubPublicBookingLink(sid)
              .then(function(payload) {
                var link = payload && payload.booking_link ? String(payload.booking_link).trim() : '';
                if (!link) {
                  throw new Error('Ссылка недоступна. Обратитесь в поддержку или откройте из бота тренера.');
                }
                hubShareBookingLinkPrefetch = { sid: sid, link: link };
                return copyTextToClipboardHub(link).then(function(ok) {
                  if (ok) {
                    closeHubShareBookingLinkModal();
                    dismissHubShareLinkGrowthHintPersisted();
                    postHubClientInviteLinkFirstCopyRecorded();
                    hubToast('Ссылка на запись скопирована. Отправьте её клиентам.');
                    return;
                  }
                  showHubShareLinkManualCopy(link, '', true);
                });
              })
              .catch(function(err) {
                setHubShareBookingLinkError(err.message || 'Не удалось сформировать ссылку.', true);
              })
              .finally(function() {
                copyBtn.disabled = false;
                copyBtn.textContent = 'Скопировать ссылку';
              });
          };
        }
        // Telegram WebView often fails programmatic copy; user copies from the field via long-press / menu.
        var previewIn = document.getElementById('hubShareLinkPreview');
        if (previewIn && !previewIn.dataset.hubInviteCopyHook) {
          previewIn.dataset.hubInviteCopyHook = '1';
          previewIn.addEventListener('copy', function() {
            postHubClientInviteLinkFirstCopyRecorded();
          });
        }
      }

      // Quick Actions handlers
      function setupQuickActions() {
        var btnSched = document.getElementById('hubBtnSchedule');
        if (btnSched) {
          btnSched.onclick = function() {
            if (btnSched.classList.contains('hub-quick-action--locked')) return;
            if (hubOnboardingData && !hubOnboardingData.schedule_unlocked && !hubOnboardingData.is_active) {
              navigateTo('trainer-profile?onboarding=blocks');
              return;
            }
            navigateTo('schedule-editor');
          };
        }
        var btnBook = document.getElementById('hubBtnBookClient');
        if (btnBook) {
          btnBook.onclick = function() {
            if (btnBook.classList.contains('hub-quick-action--locked')) return;
            if (hubOnboardingData && !hubOnboardingData.schedule_unlocked && !hubOnboardingData.is_active) {
              navigateTo('trainer-profile?onboarding=blocks');
              return;
            }
            ensureTrainerSectionsAccess(function() {
              hubQuickBookIsSandbox = false;
              openHubQuickBookClientFlowFirst();
            });
          };
        }
        var btnShare = document.getElementById('hubShareBookingLinkBtn');
        if (btnShare) {
          btnShare.onclick = function() {
            // Universal invite link: works for all trainers, no subscription gate, no service selection.
            // Fetched fresh each click (response is fast — trainer_id lookup only).
            fetch(apiUrlWithQuery('/trainer/hub/universal-invite-link'), { headers: headersJson() })
              .then(function(r) {
                return r.json().then(function(data) {
                  if (!r.ok) throw new Error((data && data.detail) || r.statusText || 'Ошибка');
                  return data;
                });
              })
              .then(function(data) {
                var link = data && data.link ? String(data.link).trim() : '';
                if (!link) {
                  hubToast('Ссылка недоступна. Попробуйте позже.');
                  return;
                }
                if (copyTextViaExecCommandHub(link)) {
                  dismissHubShareLinkGrowthHintPersisted();
                  postHubClientInviteLinkFirstCopyRecorded();
                  hubToast('Ссылка скопирована — отправьте её клиентам.');
                  return;
                }
                copyTextToClipboardHub(link).then(function(ok) {
                  if (ok) {
                    dismissHubShareLinkGrowthHintPersisted();
                    postHubClientInviteLinkFirstCopyRecorded();
                    hubToast('Ссылка скопирована — отправьте её клиентам.');
                    return;
                  }
                  // Clipboard unavailable: show fallback modal with manual copy
                  openHubShareBookingLinkModal({ services: [] }, { skipPrefetchOnce: true });
                  showHubShareLinkManualCopy(link, 'Скопируйте ссылку вручную из поля выше.', false);
                });
              })
              .catch(function(err) {
                hubToast((err && err.message) || 'Не удалось сформировать ссылку.');
              });
          };
        }
        wireHubShareBookingLinkModal();
        wireHubFillSlotsInvitesModal();
        applyHubShareButtonVisibility();
        applyHubLockedState();
        renderHubSummaryHints();
      }

      function loadSubscriptionStatus() {
        if (!getInitData()) {
          hubSubscriptionStatusReady = true;
          hasAnalyticsAccess = false;
          hubOnlineBookingEnabled = false;
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
            syncHubOnlineBookingAccessFromSubscription(hubLastSubscriptionStatus);
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
            hubOnlineBookingEnabled = false;
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

      /** Profile opens hub with ?from=minimal_profile_done after ✓ overlay — strip param only (no duplicate toast). */
      function scheduleHubMinimalProfileDoneWelcome() {
        try {
          var params = new URLSearchParams(window.location.search || '');
          if (params.get('from') !== 'minimal_profile_done') return;
        } catch (e) {
          return;
        }
        setTimeout(function() {
          try {
            var p2 = new URLSearchParams(window.location.search || '');
            if (p2.get('from') !== 'minimal_profile_done') return;
            p2.delete('from');
            var ns = p2.toString();
            var clean = window.location.pathname + (ns ? '?' + ns : '') + (window.location.hash || '');
            window.history.replaceState({}, '', clean);
          } catch (e2) { /* */ }
        }, 420);
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
      wireHubFirstBookingSoftGate();
      wireHubRhythmSlots();
      wireHubScheduleRhythmHint();
      wireHubShareLinkGrowthHint();
      wireHubClientNotesRhythmHint();

      /** Maps GET /trainer/hub/bootstrap payload into hub globals (single round-trip). */
      function applyHubBootstrapPayload(payload) {
        if (!payload || typeof payload !== 'object') return;
        if (payload.access) {
          trainerAccessSnapshot = payload.access;
          syncHubForceClientChatRelayFromTrainerAccess();
        }
        if (payload.profile) mergeHubAccessFromProfilePayload({ ok: true, data: payload.profile });
        if (payload.onboarding_checklist) applyOnboardingChecklist(payload.onboarding_checklist);
        if (payload.subscription_status) {
          hubLastSubscriptionStatus = payload.subscription_status;
          syncHubGroupsModuleAccessFromSubscription(payload.subscription_status);
          syncHubOnlineBookingAccessFromSubscription(payload.subscription_status);
          if (Array.isArray(payload.subscription_status.unlocked_features)) {
            hasAnalyticsAccess = payload.subscription_status.unlocked_features.indexOf('analytics') !== -1;
          } else {
            hasAnalyticsAccess = false;
          }
          hubSubscriptionStatusReady = true;
        }
        if (payload.lifecycle) {
          applyHubLifecycle(payload.lifecycle);
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
        renderHubSummaryHints();
      }

      /**
       * @param { { bootstrapPayload?: object } } [opts]
       *   When bootstrapPayload is set, skips redundant GETs for sections present in the payload.
       */
      function runHubAfterAccess(opts) {
        opts = opts || {};
        var bs = opts.bootstrapPayload;
        if (getInitData()) {
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
        if (!bs || !bs.lifecycle) {
          loadTrainerLifecycle();
        }
        if (!getInitData()) {
          loadBookings();
          loadHubRequestsSummary();
          loadOnboardingChecklist();
          scheduleHubMinimalProfileDoneWelcome();
          if (window.__hubSplash) window.__hubSplash.markDataReady();
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
          scheduleHubMinimalProfileDoneWelcome();
          if (window.__hubSplash) window.__hubSplash.markDataReady();
          return;
        }
        if (bs && bs.bookings && bs.bookings.days) {
          setStateMessage('');
          renderBookings(bs.bookings);
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
        setTimeout(function() {
          tryOpenHubFillSlotsFromUrl();
        }, 400);
        scheduleHubMinimalProfileDoneWelcome();
        if (window.__hubSplash) window.__hubSplash.markDataReady();
      }

      var hubTrainerMainBootstrapDone = false;
      function runTrainerHubMainBootstrap() {
        if (!getInitData() || hubTrainerMainBootstrapDone) return;
        hubTrainerMainBootstrapDone = true;
        ensureHubBookingsPlaceholder();
        showHubRhythmHintsSkeleton();
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
            prefetchHubTrainerClientsPresence();
          })
          .catch(function() {
            hubTrainerMainBootstrapDone = false;
            if (!window.TrainerMiniAppGate) {
              fetchTrainerProfileForHub().then(function(prof) {
                mergeHubAccessFromProfilePayload(prof);
                runHubAfterAccess({});
              });
            } else {
              Promise.all([
                window.TrainerMiniAppGate.fetchAccess(getInitData()).catch(function() {
                  return null;
                }),
                fetchTrainerProfileForHub(),
              ]).then(function(results) {
                var a = results[0];
                var prof = results[1];
                trainerAccessSnapshot = a;
                mergeHubAccessFromProfilePayload(prof);
                syncHubForceClientChatRelayFromTrainerAccess();
                runHubAfterAccess({});
              });
            }
          });
      }

      if (!getInitData()) {
        runHubAfterAccess({});
        [50, 150, 300, 600, 1200].forEach(function(ms) {
          setTimeout(runTrainerHubMainBootstrap, ms);
        });
      } else {
        runTrainerHubMainBootstrap();
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
