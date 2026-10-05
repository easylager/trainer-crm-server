    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        if (typeof tg.ready === 'function') tg.ready();
        if (typeof tg.expand === 'function') tg.expand();
        if (typeof window.__applyClientHubTheme === 'function') window.__applyClientHubTheme();
        try {
          var darkUi = document.documentElement.classList.contains('hub-is-dark');
          var bgHex = darkUi ? '#0B0C0E' : '#F1F3F2';
          if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
          if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
        } catch (e) {}
      }
      var initData = tg && tg.initData ? tg.initData : '';
      var RuText = window.RuText;
      var genitiveCountRu = RuText && RuText.genitiveCountRu;

      /** Сколько следующих записей держит карточка слота. Дальше — «Смотреть все». */
      var HUB_REST_MAX = 2;

      /* ── SVG icon library ─────────────────────────────────────────── */
      var ICONS = {
        search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>',
        cal:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
        inbox:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
        ticket: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2M13 11v2M13 17v2"/></svg>',
        user:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
        msg:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/></svg>',
        share:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>',
        pin:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>',
        bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m19 21-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/></svg>',
        repeat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
        plus:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
        chart:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-6"/><path d="M22 20V14"/></svg>',
      };

      /** Explore tiles removed — secondary nav lives in bottom tab «Ещё». */

      /* ── State ──────────────────────────────────────────────────────── */
      /** selected_trainer_id from catalog/bot session */
      var selectedTrainerId = null;
      /* TASK-146 (DEC-009): город для карусели каталога — из сессии или из тизера льда. */
      var discoveryCityId = null;
      /* Каток из тизера «На льду» уже на экране — в карусели его не повторяем. */
      var teaserArenaId = null;
      /** From hub bootstrap — service aligned with primary-trainer tier (booking / save / session). */
      var primaryCatalogServiceId = null;
      /** Authoritative last booking (by slot start) from bootstrap — «Записаться снова» must not depend on catalog session. */
      var lastBookingTrainerId = null;
      var lastBookingServiceId = null;
      /** Up to 3 trainers with recent bookings each — multi «Снова к …» pills (bootstrap). */
      var rebookTargets = [];
      /** Primary trainer accepts online booking — drives sticky «Записаться» FAB. */
      var hubPrimaryTrainerCanBook = false;
      /** Nearest upcoming booking on hub — rebook strip replaces bottom FAB. */
      var hubHasUpcomingBooking = false;
      /** Окно уже стоит кнопкой «Записаться на …» — плавающая кнопка её повторяет. */
      var hubOpenWindowShown = false;
      var clientHubBookFabWired = false;
      /**
       * Слот первого экрана занят своим временем (запись или ближайшее окно).
       * Фото льда тогда не второй герой: в зоне остаётся поиск.
       */
      var hubPersonalSlot = false;
      /** Контакт основного тренера — чтобы окно собралось, когда придут слоты. */
      var hubPrimaryTrainer = null;

      /* ── Utils ─────────────────────────────────────────────────────── */
      function headersJson() {
        var h = { 'Content-Type': 'application/json' };
        if (initData) h['X-Telegram-Init-Data'] = initData;
        return h;
      }

      function apiUrl(path) {
        var url = '/api/webapp' + path;
        if (initData) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
        return url;
      }

      function webappBasePath() {
        var p = window.location.pathname || '';
        return p.replace(/[^/]+$/, '') || '/webapp/';
      }

      function withInit(url) {
        if (!initData) return url;
        return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(initData);
      }

      function navigateTo(pathWithQuery) {
        if (window.ClientShell && typeof window.ClientShell.navigate === 'function') {
          window.ClientShell.navigate(pathWithQuery);
          return;
        }
        window.location.href = withInit(webappBasePath() + pathWithQuery);
      }

      /**
       * A client who followed a trainer's referral link but never finished the
       * registration form (phone/name) used to land here silently, with the
       * trainer never notified. Show a full-screen gate back to the form instead
       * of the normal hub — the referral link always means this trainer, so
       * there is no "wrong trainer" case to let the client skip past.
       *
       * Defensive by construction, not by an escape hatch: any error building
       * this (missing fields, DOM issues) is swallowed and treated as "no gate"
       * so a bug here can never trap a real client — see also the server-side
       * fail-open in `_pending_referral_payload`.
       */
      function renderPendingReferralGate(pendingReferral) {
        try {
          if (!pendingReferral || !pendingReferral.trainer_id) return false;
          if (document.getElementById('pendingReferralGate')) return true;

          var overlay = document.createElement('div');
          overlay.id = 'pendingReferralGate';
          overlay.style.cssText =
            'position:fixed;inset:0;z-index:9999;background:var(--glide-bg,#F1F3F2);' +
            'display:flex;align-items:center;justify-content:center;padding:24px;';

          var card = document.createElement('div');
          card.style.cssText =
            'max-width:360px;width:100%;background:var(--glide-surface,#fff);' +
            'border-radius:20px;padding:28px 22px;text-align:center;' +
            'box-shadow:var(--glide-shadow-card,0 10px 28px -18px rgba(16,40,40,.35));';
          var name = esc(pendingReferral.trainer_name || 'тренер');
          card.innerHTML =
            '<div style="font-size:34px;line-height:1;margin-bottom:14px;">👋</div>' +
            '<div style="font-weight:700;font-size:17px;color:var(--glide-text,#101617);margin-bottom:8px;">' +
            'Вас пригласил тренер ' + name + '</div>' +
            '<div style="font-size:14px;color:var(--glide-hint,#5E6B6B);margin-bottom:20px;">' +
            'Заполните короткий профиль — тренер увидит, что вы перешли по ссылке, и вы сможете записаться.' +
            '</div>' +
            '<button type="button" id="pendingReferralContinueBtn" style="width:100%;padding:13px;border:none;' +
            'border-radius:14px;background:var(--glide-brand,#45B9BB);color:var(--glide-on-fill,#04262A);' +
            'font-weight:600;font-size:15px;">Продолжить регистрацию</button>';
          overlay.appendChild(card);
          document.body.appendChild(overlay);

          fetch(apiUrl('/client/register-event'), {
            method: 'POST',
            headers: headersJson(),
            body: JSON.stringify({ event: 'hub_gate_shown', trainer_id: pendingReferral.trainer_id }),
          }).catch(function () {});

          var btn = document.getElementById('pendingReferralContinueBtn');
          if (btn) {
            btn.addEventListener('click', function () {
              navigateTo('client-register?trainer_id=' + encodeURIComponent(pendingReferral.trainer_id));
            });
          }
          return true;
        } catch (e) {
          return false;
        }
      }

      function esc(s) {
        if (s == null) return '';
        return String(s)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      /**
       * TASK-091 (AC-002, AC-005). Лёд города карточкой, а не строкой-примечанием.
       * Зона показывается всегда, когда в городе есть будущий сеанс: это и есть
       * товар, который видит новый клиент вместо приглашения к поиску.
       * Поиск живёт в той же зоне и остаётся даже без льда — иначе клиент без
       * данных упрётся в пустой экран.
       */
      function renderIceTeaser(payload) {
        var zone = document.getElementById('hubIceZone');
        var mount = document.getElementById('hubIceTeaser');
        if (!mount || !zone) return;
        var model = window.IceTeaserModel;
        var html = '';
        var view = null;
        if (model && typeof model.formatIceCard === 'function') {
          view = model.formatIceCard(payload, new Date());
          html = model.renderIceCardHtml(view);
        }
        mount.innerHTML = html;
        mount.hidden = !html;
        zone.hidden = false;
        var kicker = document.getElementById('hubIceKicker');
        if (kicker) {
          if (!html) kicker.textContent = 'Лёд города';
          else kicker.textContent = (view && view.kicker) || 'На льду';
        }
        var head = zone.querySelector('.hub-sec-head');
        if (head) head.hidden = !html;
        applyIceHeroVisibility();
        wireHubIceZoneLinks();
        var link = mount.querySelector('a.hub-ice-card');
        if (link) {
          link.addEventListener('click', function (ev) {
            var href = link.getAttribute('href');
            if (!href) return;
            ev.preventDefault();
            try {
              if (payload && (payload.card || payload.thumb)) {
                sessionStorage.setItem('glideArenaHero', JSON.stringify({
                  id: payload.arena_id != null ? payload.arena_id : null,
                  slug: payload.arena_slug || '',
                  url: payload.card || payload.thumb,
                }));
              }
            } catch (e) { /* private mode */ }
            navigateTo(href);
          });
        }
      }

      /**
       * TASK-148 (AC-4) → TASK-149 (S2). Строки ближайших сеансов — НЕ отдельная
       * секция, а продолжение героя внутри #hubIceZone (под тизером, над поиском):
       * строятся из ice_teaser.sessions (те же live-данные, никаких новых запросов).
       * Тизерный сеанс из строк исключается, начавшиеся — пропускаются.
       * Строки показываются только вместе с героем: нет героя (тизер скрыт) или это
       * «далёкая» карточка «Скоро и у вас» — сеансы другого города под ней не
       * выдаём за «лёд рядом». Нет строк — блока нет.
       */
      function renderIceTodaySessions(teaser) {
        var mount = document.getElementById('hubIceSessions');
        if (!mount) return;
        var model = window.HubIceTodayModel;
        var teaserModel = window.IceTeaserModel;
        var now = new Date();
        var view = teaser && teaserModel && typeof teaserModel.formatIceCard === 'function'
          ? teaserModel.formatIceCard(teaser, now)
          : null;
        var rows = model && view && !view.hidden && !view.isFar ? model.rowsFromTeaser(teaser, now) : [];
        if (!rows.length) {
          mount.hidden = true;
          mount.innerHTML = '';
          return;
        }
        mount.innerHTML = model.renderRowsHtml(rows);
        mount.hidden = false;
        applyIceHeroVisibility();
        wireHubSectionLinks(mount);
      }

      /**
       * Прячет фото льда и строки сеансов, когда слот занят своим временем.
       * Поиск в той же зоне остаётся. Снятие флага возвращает героя, если он есть в DOM.
       */
      function applyIceHeroVisibility() {
        var zone = document.getElementById('hubIceZone');
        if (!zone) return;
        zone.classList.toggle('hub-ice-zone--personal', hubPersonalSlot);
        var head = zone.querySelector('.hub-sec-head');
        var teaser = document.getElementById('hubIceTeaser');
        var sessions = document.getElementById('hubIceSessions');
        if (hubPersonalSlot) {
          if (head) head.hidden = true;
          if (teaser) teaser.hidden = true;
          if (sessions) sessions.hidden = true;
          return;
        }
        var hasCard = !!(teaser && teaser.querySelector('a.hub-ice-card'));
        if (head) head.hidden = !hasCard;
        if (teaser) teaser.hidden = !hasCard;
        if (sessions) sessions.hidden = !sessions.querySelector('.hub-ice-today__row');
      }

      /**
       * Ждём не дольше этого рынок до решения «показывать ли карусель-фолбэк».
       * Публичные запросы быстрые; предел нужен, чтобы зависший запрос не держал
       * весь хаб под скелетоном.
       */
      var HUB_MARKET_WAIT_MS = 2500;

      /** Promise<boolean>: «Куда катимся» показала хотя бы одну плитку. */
      var hubMarketPromise = Promise.resolve(false);

      /** Факты для подписи под приветствием (S1). Число приходит позже города. */
      var hubGreetingFacts = { cityName: null, isCountryFallback: false, eveningHits: null };

      function withTimeout(promise, ms, fallback) {
        return new Promise(function (resolve) {
          var done = false;
          var timer = setTimeout(function () {
            if (!done) { done = true; resolve(fallback); }
          }, ms);
          var settle = function (value) {
            if (done) return;
            done = true;
            clearTimeout(timer);
            resolve(value);
          };
          promise.then(settle, function () { settle(fallback); });
        });
      }

      /**
       * TASK-149 (S1). Подпись под приветствием — только факты данных (город, число
       * катков с вечерним сеансом); собирает её чистая HubCollectionsModel.greetingSub.
       * Строка подписи лежит в зарезервированной высоте строки приветствия, поэтому
       * появление текста не двигает макет (TASK-091/095).
       */
      function paintHubGreetingSub() {
        var el = document.getElementById('hubGreetingSub');
        if (!el) return;
        var model = window.HubCollectionsModel;
        var text = model && typeof model.greetingSub === 'function' ? model.greetingSub(hubGreetingFacts) : '';
        el.textContent = text;
        el.hidden = !text;
      }

      function setHubGreetingFacts(teaser) {
        hubGreetingFacts = {
          cityName: teaser && teaser.city_name != null ? teaser.city_name : null,
          isCountryFallback: !!(teaser && teaser.is_country_fallback),
          eveningHits: null,
        };
        paintHubGreetingSub();
      }

      /**
       * TASK-149 (S3). Секция «Куда катимся» — единственная навигация по рынку
       * (заменила секцию-подборки и карусель «Места и тренеры» в роли второй навигации).
       * Плитки Катки / Тренеры / Магазины — каждая только при честном счётчике > 0;
       * нет ни одной — секции нет. Счётчики — из публичных запросов, которые уже
       * есть (фасеты и window.hits /api/public/ice/arenas, total /api/public/trainers
       * с city_id — тот же список, что «Тренеры» во вкладке «Поиск»); новых
       * эндпоинтов нет. Сбой любого запроса — соответствующей плитки нет.
       * Возвращает Promise<boolean>: показана ли хотя бы одна плитка.
       */
      function renderHubExplore(cityId) {
        var section = document.getElementById('hubExplore');
        if (!section) return Promise.resolve(false);
        var model = window.HubCollectionsModel;
        var hide = function () {
          section.hidden = true;
          section.innerHTML = '';
          return false;
        };
        if (!model || !cityId) return Promise.resolve(hide());
        var cityParam = encodeURIComponent(String(cityId));
        var base = '/api/public/ice/arenas?intent=skate&city_id=' + cityParam;
        var fetchJson = function (url) {
          return fetch(url, { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .catch(function () { return null; });
        };
        return Promise.all([
          fetchJson(base + '&limit=1'),
          fetchJson(base + '&venue_type=ice,outdoor&when=today_evening&limit=1'),
          fetchJson(base + '&venue_type=outdoor&limit=1'),
          fetchJson('/api/public/trainers?order_by=rating&limit=1&city_id=' + cityParam),
        ]).then(function (parts) {
          var facets = (parts[0] && parts[0].venue_type_facets) || [];
          var evening = parts[1] && parts[1].window ? Number(parts[1].window.hits) || 0 : null;
          var outdoorLive = ((parts[2] && parts[2].items) || []).some(function (i) {
            return i && i.live && String(i.live.kind) === 'session';
          });
          var trainersTotal = parts[3] && parts[3].total != null ? Number(parts[3].total) : null;
          hubGreetingFacts.eveningHits = evening;
          paintHubGreetingSub();
          var tiles = model.buildTiles(
            {
              facets: facets,
              eveningHits: evening,
              outdoorLive: outdoorLive,
              trainersTotal: trainersTotal,
            },
            String(cityId)
          );
          if (!model.tilesVisible(tiles)) return hide();
          section.innerHTML =
            '<div class="hub-explore__head">' +
              '<h2 class="hub-explore__title">Куда катимся</h2>' +
              '<a class="hub-sec-link" href="ice?city_id=' + cityParam + '">Все места</a>' +
            '</div>' +
            '<div class="hub-cg">' + model.renderTilesHtml(tiles) + '</div>';
          section.hidden = false;
          wireHubSectionLinks(section);
          // Рынок уже показан плитками — карусель не должна быть вторым входом в него.
          hideDiscovery();
          return true;
        });
      }

      /**
       * Карусель лиц тренеров/мест — фолбэк, а не вторая навигация: рисуется, только
       * если «Куда катимся» плиток не показала (нет города, пустой рынок, сбой
       * запросов). Иначе скрыта — рынок один раз и в одном месте (DEC-004).
       */
      function loadDiscoveryUnlessMarket() {
        return withTimeout(hubMarketPromise, HUB_MARKET_WAIT_MS, false).then(function (hasTiles) {
          if (hasTiles) {
            hideDiscovery();
            return;
          }
          return loadAndRenderDiscovery();
        });
      }

      function wireHubSectionLinks(section) {
        if (!section) return;
        var nodes = section.querySelectorAll('a[href]');
        Array.prototype.forEach.call(nodes, function (link) {
          link.addEventListener('click', function (ev) {
            var href = link.getAttribute('href');
            if (!href) return;
            ev.preventDefault();
            navigateTo(href);
          });
        });
      }

      /**
       * Порядок первого экрана. Intent Engine не переписан: он по-прежнему
       * решает, что главное. Меняется только место зоны льда — у клиента с
       * основным тренером его панель важнее городского катания, поэтому лёд
       * уезжает под неё, а над сгибом остаётся карточка тренера.
       */
      function placeIceZone(mode) {
        var zone = document.getElementById('hubIceZone');
        var shell = document.getElementById('hubShell');
        if (!zone || !shell) return;
        var anchor =
          mode === 'below-trainer'
            ? document.getElementById('hubDiscovery')
            : document.getElementById('myTrainerBlock');
        if (anchor && anchor.parentNode === shell) shell.insertBefore(zone, anchor);
      }

      /**
       * У своего клиента с записью «Ещё занятие» стоит сразу под слотом,
       * а поиск (зона льда) — после своего. В остальных состояниях полоска
       * возвращается на место в разметке, перед списком записей.
       */
      function placeQuickStrip(mode) {
        var shell = document.getElementById('hubShell');
        var strip = document.getElementById('quickStrip');
        if (!shell || !strip) return;
        if (mode === 'after-slot') {
          var zone = document.getElementById('hubIceZone');
          if (zone && zone.parentNode === shell) shell.insertBefore(strip, zone);
          return;
        }
        var upcoming = document.getElementById('upcomingSection');
        if (upcoming && upcoming.parentNode === shell) shell.insertBefore(strip, upcoming);
      }

      /** Hub streak ribbon hidden for now — copy felt odd and said little to the client. */
      function renderStreakRibbon(_activity) {
        var el = document.getElementById('hubStreakRibbon');
        if (!el) return;
        el.style.display = 'none';
        el.innerHTML = '';
        el.onclick = null;
      }

      /** PRD E1 parity with trainer hub: server sets hub_in_session inside [start, end) in Minsk wall time. */
      function hubSessionNowPillHtml(b) {
        if (!b || !b.hub_in_session) return '';
        return (
          '<span class="hub-session-now-pill" role="status" aria-label="Текущее занятие">сейчас</span>'
        );
      }

      function initials(name) {
        // Только буквы и цифры: «Каток «Лидо»» → «КЛ», а не «К«» (TASK-146: места в карусели).
        var words = String(name || '')
          .replace(/[^0-9A-Za-zА-Яа-яЁё\s-]/g, ' ')
          .trim()
          .split(/[\s-]+/)
          .filter(Boolean);
        if (!words.length) return '?';
        if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
        return words[0].slice(0, 2).toUpperCase();
      }

      function trainerHubThumb(fileKey) {
        if (!fileKey) return '';
        return '/api/public/photos/' + encodeURIComponent(fileKey);
      }

      function parseDateTime(dateStr, timeStr) {
        var d = (dateStr || '').slice(0, 10).split('-');
        var t = (timeStr || '00:00').slice(0, 5).split(':');
        if (d.length !== 3) return new Date(0);
        return new Date(
          parseInt(d[0], 10), parseInt(d[1], 10) - 1, parseInt(d[2], 10),
          parseInt(t[0], 10) || 0, parseInt(t[1], 10) || 0
        );
      }

      /** Flatten grouped days → sorted flat list. */
      function flattenBookings(days) {
        var out = [];
        (days || []).forEach(function(day) {
          (day.bookings || []).forEach(function(b) {
            out.push({ b: b, day: day, start: parseDateTime(day.date, b.start_time) });
          });
        });
        out.sort(function(a, b) { return a.start - b.start; });
        return out;
      }

      /** Find the next upcoming booking across all days. */
      function findNextBooking(days) {
        var now = new Date();
        var flat = flattenBookings(days);
        for (var i = 0; i < flat.length; i++) {
          if (flat[i].start >= now) return flat[i];
        }
        return flat.length ? flat[0] : null;
      }

      /** Human-readable relative date: 'Сегодня', 'Завтра', or 'DD.MM (день)'. */
      function relativeDate(dateStr, dayLabel) {
        var now = new Date();
        var todayStr = now.getFullYear() + '-' +
          String(now.getMonth() + 1).padStart(2, '0') + '-' +
          String(now.getDate()).padStart(2, '0');
        var tomorrow = new Date(now);
        tomorrow.setDate(tomorrow.getDate() + 1);
        var tomorrowStr = tomorrow.getFullYear() + '-' +
          String(tomorrow.getMonth() + 1).padStart(2, '0') + '-' +
          String(tomorrow.getDate()).padStart(2, '0');

        var d = (dateStr || '').slice(0, 10);
        if (d === todayStr) return 'Сегодня';
        if (d === tomorrowStr) return 'Завтра';
        var parts = d.split('-');
        var base = parts.length === 3 ? parts[2] + '.' + parts[1] : d;
        return dayLabel ? base + ' (' + dayLabel + ')' : base;
      }

      function canWriteTrainer(b) {
        var tid = b.trainer_telegram_id;
        var un = (b.trainer_telegram_username || '').replace(/^@/, '').trim();
        return (tid != null && tid !== '') || !!un;
      }

      function openTelegramDm(username, telegramId, trainerId) {
        if (typeof window.openTelegramChatFromMiniApp === 'function') {
          if (window.openTelegramChatFromMiniApp({ username: username, telegramId: telegramId })) {
            return true;
          }
        }
        var un = String(username || '').replace(/^@/, '').trim();
        if (trainerId != null && String(trainerId).trim() !== '' && un) {
          var path = '/r/tg/' + encodeURIComponent(String(trainerId)) + '?src=client_app';
          var url = (window.location.origin || '') + path;
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
        }
        return false;
      }

      /* ── Error / status ─────────────────────────────────────────────── */
      function setStateMessage(text, kind) {
        var el = document.getElementById('stateMessage');
        if (!text) { el.style.display = 'none'; el.textContent = ''; return; }
        el.textContent = text;
        el.className = 'state-panel ' + (kind === 'error' ? 'error' : 'loading');
        el.style.display = 'block';
      }

      /* ── Hero text ──────────────────────────────────────────────────── */
      function getTelegramFirstName() {
        var w = window.Telegram && window.Telegram.WebApp;
        var u = w && w.initDataUnsafe && w.initDataUnsafe.user;
        if (!u || u.first_name == null) return null;
        var name = String(u.first_name).trim();
        return name || null;
      }

      /**
       * TASK-149 (S1). «{Утро|День|Вечер|Ночь}, {Имя}» по часу УСТРОЙСТВА; нет имени —
       * «Добрый вечер» и т.п. Логика — в чистой HubCollectionsModel.greetingText
       * (тесты в tests/js/hub-collections-model.test.js). Фолбэк на старый текст —
       * только если модель по какой-то причине не загрузилась.
       */
      function defaultHubGreeting() {
        var name = getTelegramFirstName();
        var model = window.HubCollectionsModel;
        if (model && typeof model.greetingText === 'function') {
          return model.greetingText(new Date().getHours(), name);
        }
        return name ? 'Рады видеть вас, ' + name : 'Рады вас видеть';
      }

      function setHubGreeting(text) {
        var el = document.getElementById('hubGreetingHello');
        if (el) el.textContent = text;
      }

      function setHeroLayout(mode) {
        var hero = document.getElementById('hubHero');
        if (hero) hero.classList.toggle('hub-hero--booking-led', mode === 'booking-led');
        document.body.classList.toggle('hub-body--booking-led', mode === 'booking-led');
      }

      function resetHubHeroLayout() {
        setHeroLayout('full');
        setHubGreeting(defaultHubGreeting());
      }

      /**
       * TASK-091 (AC-001): у hero больше нет ни заголовка, ни подзаголовка —
       * приветствие живёт одной строкой рядом с переключателем профиля во всех
       * сценариях. Сценарий называет не приветствие, а кикер над данными
       * («Ближайшая тренировка», «Сегодня на льду», «Мой тренер»).
       */
      function configureHeroForUpcomingBooking() {
        setHubGreeting(defaultHubGreeting());
        setHeroLayout('booking-led');
      }

      /* ── Next booking hero card (вариант B: время — герой, глагол один) ─ */

      var HUB_SOON_MS = 3 * 60 * 60 * 1000;

      function soonWhenPrefix(ms) {
        var mins = Math.max(1, Math.round(ms / 60000));
        if (mins < 60) {
          return 'через ' + mins + ' ' + pluralRuHub(mins, 'минуту', 'минуты', 'минут');
        }
        var h = Math.round(mins / 60);
        if (h <= 1) return 'через час';
        return 'через ' + h + ' ' + pluralRuHub(h, 'час', 'часа', 'часов');
      }

      /** Штамп справа от даты. Ожидание важнее «скоро»: ответ тренера — действие. */
      function nextCardStamp(b, start) {
        var st = String((b && b.status) || '').toLowerCase();
        if (st === 'pending') return { kind: 'wait', label: 'ждём ответ' };
        if (b && b.hub_in_session) return { kind: 'soon', label: 'сейчас' };
        if (start) {
          var left = start.getTime() - Date.now();
          if (left > 0 && left <= HUB_SOON_MS) return { kind: 'soon', label: 'скоро' };
        }
        return { kind: 'ok', label: 'подтверждено' };
      }

      function nextCardWhenText(dateLabel, dur, stamp, start) {
        var tail = dur ? (' · ' + dur + ' мин') : '';
        if (stamp.kind === 'soon' && stamp.label === 'скоро' && start) {
          return soonWhenPrefix(start.getTime() - Date.now()) + tail;
        }
        return dateLabel + tail;
      }

      function slotDurationMin(slot) {
        if (!slot) return 0;
        var given = Number(slot.duration_minutes || 0);
        if (given > 0) return given;
        var a = String(slot.start_time || '');
        var b = String(slot.end_time || '');
        if (a.length < 5 || b.length < 5) return 0;
        var am = parseInt(a.slice(0, 2), 10) * 60 + parseInt(a.slice(3, 5), 10);
        var bm = parseInt(b.slice(0, 2), 10) * 60 + parseInt(b.slice(3, 5), 10);
        return bm > am ? bm - am : 0;
      }

      function trainerAvatarHtml(name, photoKey) {
        var src = trainerHubThumb(photoKey || '');
        if (src) {
          return '<span class="hub-next-card-trainer-avatar hub-next-card-trainer-avatar--photo"><img src="' + esc(src) + '" alt=""/></span>';
        }
        return '<span class="hub-next-card-trainer-avatar" aria-hidden="true">' + esc(initials(name)) + '</span>';
      }

      /** Аватар и имя. Тап открывает полную карточку тренера, не запись. */
      function trainerWhoLinkHtml(name, photoKey, placeHtml, trainerId) {
        var inner =
          trainerAvatarHtml(name, photoKey) +
          '<span class="hub-next-card-who-text">' +
            '<span class="hub-next-card-trainer-name">' + esc(name) + '</span>' +
            placeHtml +
          '</span>';
        var tid = trainerId != null && String(trainerId).trim() !== '' ? String(trainerId) : '';
        if (!tid) return '<div class="hub-next-card-who-link">' + inner + '</div>';
        return (
          '<button type="button" class="hub-next-card-who-link" data-hub-action="open-trainer"' +
          ' data-trainer-id="' + esc(tid) + '"' +
          ' aria-label="Карточка тренера, ' + esc(name) + '">' +
          inner +
          '</button>'
        );
      }

      function stopHubCardControl(ev) {
        ev.stopPropagation();
        if (window.ClientShell && typeof window.ClientShell.hapticSelection === 'function') {
          window.ClientShell.hapticSelection();
        }
      }

      /* ── TASK-160 (S2): «Моя карточка» вместо карточки записи ─────────── */

      /*
       * Карточку собирает и рисует hub-me-card.js — чистая модель без DOM.
       * Хаб отвечает за три вещи, которых у модели быть не может: данные входа,
       * текущее время и переходы. Разметку и классы хаб не трогает: контракт
       * карточки заморожен, иначе прототип и продакшен разъедутся.
       */

      /**
       * Контекст нарисованной карточки. Кнопки внутри неё id записи не несут
       * (модель их не выдаёт), поэтому «Детали, перенос, отмена» открывает ту
       * запись, под которую карточку и собрали.
       */
      var hubMeCardBookingId = null;
      var hubMeCardTrainerId = null;
      var hubMeCardWired = false;

      /**
       * Склонённые формы имени для подписей карточки. Падежи живут в
       * ru-person-name.js, а модель чистая — поэтому готовые формы кладёт хаб.
       * Имя приходит одной строкой: `formatPersonName` внутри `inflectPersonName`
       * сам разбирает её на имя и фамилию, как это делает catalog-main.js.
       * Модуля нет — полей нет, и модель переходит на безпадежные формы
       * («Написать тренеру»), а не на кривой падеж.
       */
      function hubMeDeclinedForms(fullName) {
        var ru = window.RuPersonName;
        var name = ((fullName || '') + '').trim();
        if (!name || !ru || typeof ru.inflectPersonName !== 'function') return null;
        var out = {};
        var dat = ru.inflectPersonName(name, '', 'dat');
        var gen = ru.inflectPersonName(name, '', 'gen');
        if (dat) out.nameDative = dat;
        if (gen) out.nameGenitive = gen;
        return (out.nameDative || out.nameGenitive) ? out : null;
      }

      /** Сертификаты из bootstrap (TASK-161). Поля нет — кошелёк просто без ячейки. */
      function hubBootstrapCertificates(hubMeta) {
        return Array.isArray(hubMeta && hubMeta.certificates) ? hubMeta.certificates : [];
      }

      function buildMeCardBookingInput(item, hubMeta) {
        var b = (item && item.b) || {};
        var day = (item && item.day) || {};
        var booking = {};
        for (var key in b) {
          if (Object.prototype.hasOwnProperty.call(b, key)) booking[key] = b[key];
        }
        // `start` уже Date (flattenBookings), `date_label` — та же подпись даты,
        // что была у старой карточки: относительные формы считает хаб, не модель.
        booking.start = item && item.start;
        booking.date_label = relativeDate(day.date, day.day_label);
        if (!booking.arena_name) booking.arena_name = b.place_display || '';
        var input = {
          kind: 'booking',
          booking: booking,
          passes: hubBootstrapPasses(hubMeta),
          certificates: hubBootstrapCertificates(hubMeta),
        };
        var forms = hubMeDeclinedForms(b.trainer_name);
        if (forms) input.trainer = forms;
        return input;
      }

      /** Рисует «мою запись» в существующий #nextBookingBlock. */
      function renderMeCardForBooking(item, hubMeta) {
        var block = document.getElementById('nextBookingBlock');
        if (!block) return false;
        var model = window.HubMeCard;
        if (!model || typeof model.buildView !== 'function') return false;
        var view = model.buildView(buildMeCardBookingInput(item, hubMeta), new Date());
        if (!view) {
          block.innerHTML = '';
          return false;
        }
        hubMeCardBookingId = item && item.b && item.b.id != null ? String(item.b.id) : null;
        hubMeCardTrainerId = view.trainerId;
        block.innerHTML = model.renderHtml(view);
        wireMeCardBlock(block);
        return true;
      }

      /**
       * Один делегирующий обработчик на весь блок: карточка перерисовывается
       * целиком, и слушатели на самих кнопках пришлось бы навешивать заново.
       * Список «остальных записей» лежит в том же блоке, поэтому его строки
       * обслуживает этот же обработчик.
       *
       * Неизвестное действие — тишина, а не исключение: S3/S4 добавят заливки
       * тренера, возврата и выбора города, и до тех пор карточка не должна
       * падать на чужом data-me-action.
       */
      function wireMeCardBlock(block) {
        if (hubMeCardWired) return;
        hubMeCardWired = true;
        block.addEventListener('click', function (ev) {
          var t = ev.target;
          if (!t || !t.closest) return;

          var line = t.closest('.hub-next-card-line[data-bid]');
          if (line) {
            stopHubCardControl(ev);
            var lineBid = line.getAttribute('data-bid');
            if (lineBid) navigateTo('client-bookings?open_booking=' + encodeURIComponent(lineBid) + '&from=hub');
            return;
          }
          if (t.closest('[data-hub-action="all-bookings"]')) {
            stopHubCardControl(ev);
            navigateTo('client-bookings');
            return;
          }

          var btn = t.closest('[data-me-action]');
          if (!btn) return;
          var action = btn.getAttribute('data-me-action');
          var tid = btn.getAttribute('data-me-trainer-id') || hubMeCardTrainerId;

          if (action === 'dm') {
            stopHubCardControl(ev);
            openTelegramDm(
              btn.getAttribute('data-me-dm-un'),
              btn.getAttribute('data-me-dm-tid'),
              tid
            );
            return;
          }
          if (action === 'open-booking') {
            stopHubCardControl(ev);
            if (hubMeCardBookingId) {
              navigateTo('client-bookings?open_booking=' + encodeURIComponent(hubMeCardBookingId) + '&from=hub');
            }
            return;
          }
          // Абонемент и сертификат живут на одном экране — ячейка кошелька
          // ведёт туда, а не в две разные истории баланса.
          if (action === 'open-pass' || action === 'open-cert') {
            stopHubCardControl(ev);
            navigateTo('client-passes-certificates');
            return;
          }
          if (action === 'open-trainer') {
            stopHubCardControl(ev);
            if (tid) {
              navigateTo('catalog?trainer_id=' + encodeURIComponent(tid) + catalogPrimaryServiceQuery() + '&from=hub');
            }
            return;
          }
          /*
           * book-slot / all-slots / all-sessions / all-trainers / pick-city /
           * geo / all-country / more-cities — действия заливок S3/S4. Молчим.
           */
        });
      }

      /**
       * Нет записи, есть окно. Ближайшее время — герой, второе — текстовая ссылка.
       * Карточка тренера в этом состоянии не рисуется: человек — строка внутри.
       */
      function renderOpenWindowCard(trainer, slots) {
        var hero = slots[0];
        var alt = slots.length > 1 ? slots[1] : null;
        var time = String(hero.start_time || '').slice(0, 5);
        var dur = slotDurationMin(hero);
        var dateLabel = relativeDate(hero.slot_date, '');
        var when = dur ? (dateLabel + ' · ' + dur + ' мин') : dateLabel;
        var name = ((trainer.name || '') + '').trim() || 'Тренер';
        var place = ((hero.arena_name || hero.arena_city_name || '') + '').trim() || 'ваш тренер';
        var un = (trainer.username || '').replace(/^@/, '').trim();
        var tid = trainer.telegramId != null ? String(trainer.telegramId) : '';
        var quiet = (un || tid)
          ? '<button type="button" class="hub-next-card-quiet" data-hub-dm="window"' +
            ' data-dm-un="' + esc(un) + '" data-dm-tid="' + esc(tid) + '">написать</button>'
          : '';
        var altHtml = '';
        if (alt) {
          var altTime = String(alt.start_time || '').slice(0, 5);
          var altDay = relativeDate(alt.slot_date, '').toLowerCase();
          altHtml =
            '<button type="button" class="hub-next-card-alt" data-slot-id="' + esc(String(alt.id || '')) + '"' +
            (alt.service_id != null ? ' data-service-id="' + esc(String(alt.service_id)) + '"' : '') +
            (alt.arena_id != null ? ' data-arena-id="' + esc(String(alt.arena_id)) + '"' : '') + '>' +
            esc(altDay + ' в ' + altTime) + '</button>';
        }
        var block = document.getElementById('nextBookingBlock');
        if (!block) return;
        hubOpenWindowShown = true;
        syncClientHubBookFab();
        block.innerHTML =
          '<div class="hub-next-card hub-next-card--open" id="nextCard" tabindex="0"' +
          ' aria-label="Ближайшее окно, ' + esc(when) + '">' +
            '<div class="hub-next-card-inner">' +
              '<div class="hub-next-card-time hub-next-card-time--offer">' + esc(time) + '</div>' +
              '<div class="hub-next-card-when"><span class="hub-next-card-date">' + esc(when) + '</span></div>' +
              '<div class="hub-next-card-who">' +
                trainerWhoLinkHtml(
                  name,
                  trainer.photo,
                  '<span class="hub-next-card-place-line">' + ICONS.pin + '<span>' + esc(place) + '</span></span>',
                  trainer.id
                ) +
                quiet +
              '</div>' +
              '<button type="button" class="hub-next-card-fill" data-slot-id="' + esc(String(hero.id || '')) + '"' +
              (hero.service_id != null ? ' data-service-id="' + esc(String(hero.service_id)) + '"' : '') +
              (hero.arena_id != null ? ' data-arena-id="' + esc(String(hero.arena_id)) + '"' : '') + '>' +
              'Записаться на ' + esc(time) + '</button>' +
              altHtml +
            '</div>' +
          '</div>';
        hideMyTrainerBlock();
        var card = document.getElementById('nextCard');
        if (!card) return;
        card.addEventListener('click', function(ev) {
          var dmBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-dm="window"]');
          if (dmBtn) {
            stopHubCardControl(ev);
            openTelegramDm(dmBtn.getAttribute('data-dm-un'), dmBtn.getAttribute('data-dm-tid'), trainer.id);
            return;
          }
          var slotBtn = ev.target && ev.target.closest && ev.target.closest('[data-slot-id]');
          if (slotBtn) {
            stopHubCardControl(ev);
            navigateTo(buildBookPathFromHubContext(trainer.id, {
              serviceId: slotBtn.getAttribute('data-service-id'),
              slotId: slotBtn.getAttribute('data-slot-id'),
              arenaId: slotBtn.getAttribute('data-arena-id'),
              fallbackServiceQuery: catalogPrimaryServiceQuery(),
            }));
            return;
          }
          navigateTo(
            'catalog?trainer_id=' + encodeURIComponent(String(trainer.id)) + catalogPrimaryServiceQuery() + '&from=hub'
          );
        });
      }

      function catalogPrimaryServiceQuery() {
        if (primaryCatalogServiceId == null || primaryCatalogServiceId === '') return '';
        var n = Number(primaryCatalogServiceId);
        if (!isFinite(n) || n <= 0) return '';
        return '&service_id=' + encodeURIComponent(String(n));
      }

      /** Hub → booking: slot chip → catalog form; repeat book → catalog slot pick (action=book). */
      function buildBookPathFromHubContext(trainerId, opts) {
        opts = opts || {};
        var slotRaw = opts.slotId;
        if (slotRaw != null && String(slotRaw).trim() !== '') {
          var parts = ['catalog?trainer_id=' + encodeURIComponent(String(trainerId))];
          parts.push('slot_id=' + encodeURIComponent(String(slotRaw).trim()));
          var svcRaw = opts.serviceId;
          if (svcRaw != null && String(svcRaw).trim() !== '') {
            parts.push('service_id=' + encodeURIComponent(String(svcRaw).trim()));
          } else if (opts.fallbackServiceQuery) {
            parts.push(opts.fallbackServiceQuery.replace(/^&/, ''));
          }
          var arenaRaw = opts.arenaId;
          if (arenaRaw != null && String(arenaRaw).trim() !== '') {
            parts.push('arena_id=' + encodeURIComponent(String(arenaRaw).trim()));
          }
          parts.push('from=hub');
          return parts.join('&');
        }
        var parts = [
          'catalog?trainer_id=' + encodeURIComponent(String(trainerId)),
          'action=book',
          'from=hub',
        ];
        var svcRaw2 = opts.serviceId;
        if (svcRaw2 != null && String(svcRaw2).trim() !== '') {
          parts.push('service_id=' + encodeURIComponent(String(svcRaw2).trim()));
        } else if (opts.fallbackServiceQuery) {
          parts.push(opts.fallbackServiceQuery.replace(/^&/, ''));
        }
        var arenaRaw2 = opts.arenaId;
        if (arenaRaw2 != null && String(arenaRaw2).trim() !== '') {
          parts.push('arena_id=' + encodeURIComponent(String(arenaRaw2).trim()));
        }
        return parts.join('&');
      }

      /** Prefer last booking service with this trainer; else hub primary catalog hint. */
      function hubRepeatBookServiceId(trainerId) {
        var tid = trainerId != null ? Number(trainerId) : NaN;
        if (!isNaN(tid) && tid > 0 && lastBookingTrainerId != null) {
          var lt = Number(lastBookingTrainerId);
          if (!isNaN(lt) && lt === tid && lastBookingServiceId != null) {
            var ls = Number(lastBookingServiceId);
            if (!isNaN(ls) && ls > 0) return ls;
          }
        }
        if (primaryCatalogServiceId == null || primaryCatalogServiceId === '') return null;
        var pn = Number(primaryCatalogServiceId);
        return !isNaN(pn) && pn > 0 ? pn : null;
      }

      /** Hub → book slots (or form) without catalog / trainer-card flash. */
      function navigateToBookAgain(trainerId, serviceId) {
        var svc = serviceId != null && serviceId !== '' ? serviceId : hubRepeatBookServiceId(trainerId);
        navigateTo(buildBookPathFromHubContext(trainerId, {
          serviceId: svc,
          fallbackServiceQuery: catalogPrimaryServiceQuery(),
        }));
      }

      function navigateToPrimaryTrainerBook() {
        if (selectedTrainerId == null || String(selectedTrainerId).trim() === '') return;
        navigateToBookAgain(selectedTrainerId, hubRepeatBookServiceId(selectedTrainerId));
      }

      /** Same path as bottom FAB; fallback when primary trainer cannot book online. */
      function navigateToHubBookLikePrimaryFab(nextBooking) {
        if (hubPrimaryTrainerCanBook && selectedTrainerId != null && String(selectedTrainerId).trim() !== '') {
          navigateToPrimaryTrainerBook();
          return;
        }
        navigateToCatalogBookAgain(nextBooking);
      }

      /** Sticky FAB: primary trainer + online booking; hidden when «Записаться снова» strip is shown. */
      function shouldShowClientHubBookFab() {
        if (!initData) return false;
        if (hubHasUpcomingBooking || hubOpenWindowShown) return false;
        if (selectedTrainerId == null || String(selectedTrainerId).trim() === '') return false;
        return hubPrimaryTrainerCanBook === true;
      }

      function syncClientHubBookFab() {
        var fab = document.getElementById('hubBookFab');
        if (!fab) return;
        var show = shouldShowClientHubBookFab();
        if (show) fab.removeAttribute('hidden');
        else fab.setAttribute('hidden', '');
        try {
          document.body.classList.toggle('hub-body--book-fab-visible', show);
        } catch (eBody) { /* ignore */ }
        if (clientHubBookFabWired) return;
        clientHubBookFabWired = true;
        fab.addEventListener('click', function() {
          if (window.ClientShell && typeof window.ClientShell.hapticSelection === 'function') {
            window.ClientShell.hapticSelection();
          }
          navigateToPrimaryTrainerBook();
        });
      }

      /**
       * «Записаться снова»: слоты тренера с ближайшей записи, иначе последняя запись (bootstrap),
       * без selected_trainer_id из сессии каталога.
       */
      function navigateToCatalogBookAgain(nextBooking) {
        var nb = nextBooking && nextBooking.b;
        var tid = nb && nb.trainer_id != null ? Number(nb.trainer_id) : NaN;
        if (!isNaN(tid) && tid > 0) {
          var sid = nb.service_id != null ? Number(nb.service_id) : null;
          navigateToBookAgain(tid, sid);
          return;
        }
        var lt = lastBookingTrainerId;
        if (lt != null && lt > 0) {
          navigateToBookAgain(lt, lastBookingServiceId);
          return;
        }
        navigateTo('ice?intent=coach');
      }

      /** First word of display name for compact pill label. */
      function trainerFirstNameForPill(displayName) {
        var s = ((displayName || '') + '').trim();
        if (!s) return 'Тренер';
        var parts = s.split(/\s+/);
        return parts[0] || s;
      }

      /** Deep link to book for one rebook row from bootstrap (trainer + last service per trainer). */
      function navigateToRebookTarget(t) {
        var tid = t && t.trainer_id != null ? Number(t.trainer_id) : NaN;
        if (isNaN(tid) || tid <= 0) return;
        var sid = t.service_id != null ? Number(t.service_id) : null;
        navigateToBookAgain(tid, sid);
      }

      /**
       * Order rebook pill targets: when showing upcoming booking, surface matching trainer first.
       * Caps at 3 — further trainers via каталог.
       */
      function orderedRebookPills(nextBooking, targets) {
        var list = (targets || []).filter(function(t) {
          return t && t.trainer_id != null && Number(t.trainer_id) > 0;
        }).map(function(t) { return t; });
        var nb = nextBooking && nextBooking.b;
        var nextTid = nb && nb.trainer_id != null ? Number(nb.trainer_id) : NaN;
        if (!isNaN(nextTid) && nextTid > 0 && list.length >= 2) {
          var idx = -1;
          for (var i = 0; i < list.length; i++) {
            if (Number(list[i].trainer_id) === nextTid) { idx = i; break; }
          }
          if (idx > 0) {
            var copy = list.slice();
            var item = copy.splice(idx, 1)[0];
            copy.unshift(item);
            list = copy;
          }
        }
        return list.slice(0, 3);
      }

      function hideNextBookingSkeleton() {
        var skel = document.getElementById('nextBookingSkel');
        if (skel) skel.remove();
      }

      /** When bootstrap started — used for minimum skeleton display time. */
      var hubLoadStartedAt = Date.now();
      var HUB_SKELETON_MIN_MS = 220;

      /**
       * Drop skeleton only after bootstrap AND scenario-specific async work
       * (primary panel slots, discovery carousel) are done. Idempotent.
       */
      function finishHubInitialLoading() {
        if (document.body.classList.contains('hub-body--revealed')) return;
        var wait = Math.max(0, HUB_SKELETON_MIN_MS - (Date.now() - hubLoadStartedAt));
        setTimeout(function() {
          if (document.body.classList.contains('hub-body--revealed')) return;
          document.body.classList.remove('hub-body--loading');
          document.body.classList.add('hub-body--revealed');
          var skel = document.getElementById('hubInitialSkel');
          if (skel) {
            skel.setAttribute('aria-hidden', 'true');
            skel.removeAttribute('aria-busy');
          }
          syncClientHubBookFab();
        }, wait);
      }

      function clearNextBookingBlock() {
        var block = document.getElementById('nextBookingBlock');
        if (block) block.innerHTML = '';
      }

      /* ── My trainer card ─────────────────────────────────────────────── */

      /**
       * Full recommendation text (opener → имя → услуги → город · арена → CTA → ссылка) — не голый URL.
       */
      function shareTrainer(trainerId, shareCtx) {
        var ctx = shareCtx || 'catalog';
        var path =
          '/client/share-trainer/' +
          encodeURIComponent(String(trainerId)) +
          '?share_context=' +
          encodeURIComponent(ctx);
        fetch(apiUrl(path))
          .then(function(r) { return r.ok ? r.json() : Promise.reject(r.status); })
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
       * Primary-relationship card: uppercase label «ОСНОВНОЙ», main line — trainer name from hub.
       * Opens catalog deep-linked to this trainer_id so we never reuse stale session.trainer_id from browsing.
       * Share action added: 1-tap trainer recommendation via Telegram native share dialog.
       */
      function renderMyTrainerCard(trainerId, trainerName, trainerUsername, trainerTelegramId, listPhotoKey, canBook) {
        var block = document.getElementById('myTrainerBlock');
        if (!block) return;
        var un = (trainerUsername || '').replace(/^@/, '').trim();
        var tid = trainerTelegramId != null ? String(trainerTelegramId) : '';
        var hasDm = !!(un || tid);
        var displayName = ((trainerName || '').trim()) || 'Тренер';
        var onlineBook = canBook !== false;

        var actionBtns = '';
        if (trainerId != null) {
          actionBtns +=
            '<button type="button" class="hub-trainer-share-btn" data-hub-action="share-trainer"' +
            ' data-share-tid="' + esc(String(trainerId)) + '"' +
            ' data-share-context="my_trainer"' +
            ' aria-label="Поделиться тренером">' + ICONS.share + '</button>';
        }
        var actionsHtml = actionBtns
          ? '<div class="hub-trainer-actions">' + actionBtns + '</div>'
          : '';

        var subText = onlineBook
          ? 'Нажмите, чтобы выбрать время'
          : (hasDm ? 'Онлайн-запись недоступна — напишите тренеру' : 'Открыть профиль в каталоге');

        var contactRowHtml = '';
        if (hasDm) {
          contactRowHtml =
            '<button type="button" class="hub-trainer-contact-btn" data-hub-dm="trainer"' +
            ' data-dm-un="' + esc(un) + '" data-dm-tid="' + esc(tid) + '">' +
            ICONS.msg + '<span>Написать тренеру</span>' +
            '</button>';
        }

        var src = trainerHubThumb(listPhotoKey || '');
        var avatarHtml = src
          ? '<div class="hub-trainer-avatar hub-trainer-avatar--photo"><img src="' + esc(src) + '" alt="" loading="lazy"/></div>'
          : '<div class="hub-trainer-avatar">' + esc(initials(displayName)) + '</div>';

        block.innerHTML =
          '<div class="hub-trainer-card" id="trainerCard">' +
            '<div class="hub-trainer-card-main">' +
              avatarHtml +
              '<div class="hub-trainer-info">' +
                '<div class="hub-trainer-label">Основной</div>' +
                '<div class="hub-trainer-name">' + esc(displayName) + '</div>' +
                '<div class="hub-trainer-sub">' + esc(subText) + '</div>' +
              '</div>' +
              actionsHtml +
            '</div>' +
            contactRowHtml +
          '</div>';
        block.style.display = '';

        var card = document.getElementById('trainerCard');
        if (!card) return;
        card.addEventListener('click', function(ev) {
          var dmBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-dm="trainer"]');
          if (dmBtn) {
            ev.stopPropagation();
            openTelegramDm(dmBtn.getAttribute('data-dm-un'), dmBtn.getAttribute('data-dm-tid'), trainerId);
            return;
          }
          var shareBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-action="share-trainer"]');
          if (shareBtn) {
            ev.stopPropagation();
            shareTrainer(
              shareBtn.getAttribute('data-share-tid'),
              shareBtn.getAttribute('data-share-context') || 'my_trainer'
            );
            return;
          }
          if (!onlineBook && hasDm) {
            openTelegramDm(un, tid, trainerId);
            return;
          }
          navigateTo(
            trainerId != null && String(trainerId).trim() !== ''
              ? 'catalog?trainer_id=' + encodeURIComponent(String(trainerId)) + catalogPrimaryServiceQuery()
              : 'catalog'
          );
        });
      }

      /* ── Hero primary actions + contextual pills (no tab duplicates) ─── */

      /**
       * TASK-091 (AC-003). Крупный CTA «Найти тренера» съедал ~15% первого
       * экрана в состоянии нового клиента. Теперь поиск — постоянная строка в
       * зоне льда: доступен всегда и во всех сценариях, но ничего не заслоняет.
       */
      function wireHubIceZoneLinks() {
        var search = document.getElementById('hubSearchRow');
        if (search && !search.dataset.wired) {
          search.dataset.wired = '1';
          search.innerHTML =
            (ICONS.search || '').replace('<svg ', '<svg class="hub-search__ic" ') +
            '<span class="hub-search__text">Найти тренера или каток</span>';
          search.addEventListener('click', function () {
            navigateTo('ice?focus=search');
          });
        }
        var all = document.getElementById('hubIceAll');
        if (all && !all.dataset.wired) {
          all.dataset.wired = '1';
          all.addEventListener('click', function (ev) {
            ev.preventDefault();
            navigateTo('ice');
          });
        }
      }

      function hideQuickStrip() {
        var strip = document.getElementById('quickStrip');
        if (!strip) return;
        strip.innerHTML = '';
        strip.setAttribute('hidden', 'hidden');
        strip.classList.remove('hub-quick-strip--quiet');
      }

      function mountQuickStripPills(pills) {
        var strip = document.getElementById('quickStrip');
        if (!strip) return;
        if (!pills || !pills.length) {
          hideQuickStrip();
          return;
        }
        var quiet = pills.every(function(p) { return p.quiet; });
        strip.classList.toggle('hub-quick-strip--quiet', quiet);
        strip.removeAttribute('hidden');
        strip.innerHTML = pills.map(function(p, i) {
          if (p.quiet) {
            return '<button type="button" class="hub-quick-link" data-pill-idx="' + i + '">' +
              esc(p.label) + '</button>';
          }
          var primaryClass = p.primary ? ' hub-quick-pill--primary' : '';
          return '<button type="button" class="hub-quick-pill' + primaryClass + '" data-pill-idx="' + i + '">' +
            (ICONS[p.icon] || '') + esc(p.label) +
            '</button>';
        }).join('');
        strip.querySelectorAll('.hub-quick-pill, .hub-quick-link').forEach(function(btn) {
          var idx = parseInt(btn.getAttribute('data-pill-idx'), 10);
          btn.addEventListener('click', function() { pills[idx].action(); });
        });
      }

      function rebookPillItems(nextBooking, targets, maxCount) {
        maxCount = maxCount || 2;
        var multi = orderedRebookPills(nextBooking, targets);
        if (multi.length >= 2) {
          return multi.slice(0, maxCount).map(function(t, ix) {
            return {
              label: 'Снова к ' + trainerFirstNameForPill(t.trainer_display_name),
              icon: 'repeat',
              primary: ix === 0,
              action: function() { navigateToRebookTarget(t); },
            };
          });
        }
        return [{
          label: 'Записаться снова',
          icon: 'repeat',
          primary: true,
          action: function() { navigateToHubBookLikePrimaryFab(nextBooking); },
        }];
      }

      /**
       * Пока запись уже есть, «снова» — тихая строка, не вторая кнопка экрана.
       * Без ближайшей записи (были занятия) полоска остаётся действием.
       */
      function rebookQuietItems(nextBooking, targets) {
        var multi = orderedRebookPills(nextBooking, targets);
        if (multi.length >= 2) {
          return multi.slice(0, 2).map(function(t) {
            return {
              label: 'Ещё занятие · ' + trainerFirstNameForPill(t.trainer_display_name),
              quiet: true,
              action: function() { navigateToRebookTarget(t); },
            };
          });
        }
        var single = multi.length === 1 ? multi[0] : null;
        return [{
          label: 'Ещё занятие',
          quiet: true,
          action: function() {
            if (single) navigateToRebookTarget(single);
            else navigateToHubBookLikePrimaryFab(nextBooking);
          },
        }];
      }

      /** Rebook-only pills — bottom tabs cover catalog, bookings, and «Ещё». */
      function renderQuickStrip(scenario, nextBooking) {
        var pills = [];
        if (scenario === 'has-booking') {
          pills = rebookQuietItems(nextBooking, rebookTargets);
        } else if (scenario === 'has-past') {
          pills = rebookPillItems(null, rebookTargets, 2);
        }
        mountQuickStripPills(pills);
      }

      function wireAllBookingsLink() {
        var btn = document.getElementById('btnAllBookings');
        if (btn) btn.addEventListener('click', function() { navigateTo('client-bookings'); });
      }

      function resetHubChromeForState(opts) {
        opts = opts || {};
        hideQuickStrip();
        hidePrimaryPanel();
        hideDiscovery();
        placeQuickStrip('home');
        if (!opts.keepHeroLayout) resetHubHeroLayout();
      }

      /* ── Primary trainer living panel: slots + pass + history ────────── */

      var RU_MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
      var RU_WEEKDAYS_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

      function hidePrimaryPanel() {
        var el = document.getElementById('hubPrimaryPanel');
        if (!el) return;
        el.innerHTML = '';
        el.setAttribute('hidden', 'hidden');
      }

      function hideDiscovery() {
        var el = document.getElementById('hubDiscovery');
        if (!el) return;
        el.innerHTML = '';
        el.setAttribute('hidden', 'hidden');
      }

      function pluralRuHub(n, one, few, many) {
        n = Math.abs(Number(n) || 0);
        var mod100 = n % 100;
        var mod10 = n % 10;
        if (mod100 >= 11 && mod100 <= 14) return many;
        if (mod10 === 1) return one;
        if (mod10 >= 2 && mod10 <= 4) return few;
        return many;
      }

      /** Parses ISO date (YYYY-MM-DD) as local; ISO datetime works too. */
      function parseIsoDateLocal(s) {
        if (!s) return null;
        var raw = String(s).slice(0, 10).split('-');
        if (raw.length !== 3) return null;
        var y = parseInt(raw[0], 10);
        var m = parseInt(raw[1], 10);
        var d = parseInt(raw[2], 10);
        if (!y || !m || !d) return null;
        return new Date(y, m - 1, d);
      }

      /** Compact slot-chip caption: «Сб, 7 июн». */
      function formatSlotDayLabel(dateStr) {
        var d = parseIsoDateLocal(dateStr);
        if (!d) return '';
        var wd = RU_WEEKDAYS_SHORT[d.getDay()] || '';
        var mn = RU_MONTHS_SHORT[d.getMonth()] || '';
        return (wd ? wd.charAt(0).toUpperCase() + wd.slice(1) + ', ' : '') + d.getDate() + ' ' + mn;
      }

      /** Compact long date for history/expiry: «18 мая 2026» or «18 мая» when current year. */
      function formatHistoryDate(dateStr) {
        var d = parseIsoDateLocal(dateStr);
        if (!d) return '';
        var mn = RU_MONTHS_SHORT[d.getMonth()] || '';
        var now = new Date();
        if (d.getFullYear() === now.getFullYear()) return d.getDate() + ' ' + mn;
        return d.getDate() + ' ' + mn + ' ' + d.getFullYear();
      }

      function buildPrimarySlotsHtml(slots) {
        if (!slots || !slots.length) return '';
        var items = slots.slice(0, 4).map(function(s) {
          var t = (s && s.start_time ? String(s.start_time) : '').slice(0, 5);
          var dayLabel = formatSlotDayLabel(s && s.slot_date);
          var place = ((s && (s.arena_name || s.arena_city_name)) || '').toString().trim();
          var placeHtml = place
            ? '<span class="hub-primary-panel__slot-place">' + ICONS.pin + esc(place) + '</span>'
            : '';
          return (
            '<button type="button" class="hub-primary-panel__slot" data-slot-id="' + esc(String(s.id || '')) + '"' +
            (s && s.arena_id != null ? ' data-arena-id="' + esc(String(s.arena_id)) + '"' : '') +
            (s && s.service_id != null ? ' data-service-id="' + esc(String(s.service_id)) + '"' : '') + '>' +
              '<span class="hub-primary-panel__slot-day">' + esc(dayLabel) + '</span>' +
              '<span class="hub-primary-panel__slot-time">' + esc(t) + '</span>' +
              placeHtml +
            '</button>'
          );
        }).join('');
        return (
          '<div class="hub-primary-panel__row hub-primary-panel__row--slots">' +
            '<div class="hub-primary-panel__row-head">Ближайшие окна</div>' +
            '<div class="hub-primary-panel__slots-scroller">' + items + '</div>' +
          '</div>'
        );
      }

      function passProductNameForHubSubline(passInfo, total) {
        var name = String((passInfo && passInfo.product_name) || '').trim();
        if (!name || name === '—') return '';
        if (total > 0) {
          var compact = name.replace(/\s+/g, ' ').trim();
          var sizeRe = new RegExp('^' + total + '\\s*(занятие|занятия|занятий)$', 'i');
          if (sizeRe.test(compact)) return '';
        }
        return name;
      }

      function buildPrimaryPassHtml(passInfo, opts) {
        opts = opts || {};
        if (!passInfo) return '';
        var remaining = Number(passInfo.sessions_remaining || 0);
        if (!remaining || remaining <= 0) return '';
        var total = Number(passInfo.sessions_total || 0);
        var expiry = passInfo.expires_at ? formatHistoryDate(passInfo.expires_at) : '';
        var subParts = [];
        var productLabel = passProductNameForHubSubline(passInfo, total);
        subParts.push(productLabel ? 'Абонемент «' + esc(productLabel) + '»' : 'Абонемент');
        if (expiry) subParts.push('до ' + esc(expiry));
        var subHtml = '<span class="hub-primary-panel__pass-sub">' + subParts.join(' · ') + '</span>';
        var autoNoteHtml = opts.autoDebitNote
          ? '<span class="hub-primary-panel__pass-note">Спишется автоматически после занятия</span>'
          : '';
        var passMod = opts.autoDebitNote ? ' hub-primary-panel__pass--auto-debit' : '';
        var titleHtml;
        var ariaBalance;
        if (total > 0) {
          var totalPhrase = genitiveCountRu(total, 'занятия', 'занятий');
          titleHtml =
            '<span class="hub-primary-panel__pass-kicker">осталось</span>' +
            '<span class="hub-primary-panel__pass-title">из ' + totalPhrase + '</span>';
          ariaBalance = 'Осталось ' + remaining + ' из ' + totalPhrase + ' по абонементу';
        } else {
          var word = pluralRuHub(remaining, 'занятие', 'занятия', 'занятий');
          titleHtml =
            '<span class="hub-primary-panel__pass-kicker">осталось</span>' +
            '<span class="hub-primary-panel__pass-title">' + word + ' по абонементу</span>';
          ariaBalance = 'Осталось ' + remaining + ' ' + word + ' по абонементу';
        }
        return (
          '<button type="button" class="hub-primary-panel__pass' + passMod + '" data-hub-action="open-pass"' +
            ' aria-label="' + esc(ariaBalance) + '">' +
            '<span class="hub-primary-panel__pass-num" aria-hidden="true">' + esc(String(remaining)) + '</span>' +
            '<span class="hub-primary-panel__pass-body">' +
              titleHtml +
              subHtml +
              autoNoteHtml +
            '</span>' +
            '<span class="hub-primary-panel__pass-chevron" aria-hidden="true">›</span>' +
          '</button>'
        );
      }

      function buildPrimaryHistoryHtml(history) {
        if (!history) return '';
        var count = Number(history.completed_count || 0);
        if (count <= 0) return '';
        var word = pluralRuHub(count, 'раз', 'раза', 'раз');
        var lastStr = history.last_completed_at ? formatHistoryDate(history.last_completed_at) : '';
        var line = 'Вы тренировались ' + count + ' ' + word;
        if (lastStr) line += ' · последний раз ' + lastStr;
        return '<div class="hub-primary-panel__history">' + esc(line) + '</div>';
      }

      function selectPrimaryPassForTrainer(items, trainerId) {
        if (!Array.isArray(items) || !items.length) return null;
        var tidNum = Number(trainerId);
        // First active pass tied to this trainer with sessions remaining
        for (var i = 0; i < items.length; i++) {
          var it = items[i] || {};
          var st = String(it.status || '').toLowerCase();
          if (st !== 'active') continue;
          var rem = Number(it.sessions_remaining || 0);
          if (rem <= 0) continue;
          if (Number(it.trainer_id) === tidNum) return it;
        }
        return null;
      }

      /** Any active pass with remaining sessions — for hub states without a pinned trainer. */
      function selectAnyActivePass(items) {
        if (!Array.isArray(items) || !items.length) return null;
        for (var i = 0; i < items.length; i++) {
          var it = items[i] || {};
          if (String(it.status || '').toLowerCase() !== 'active') continue;
          if (Number(it.sessions_remaining || 0) <= 0) continue;
          return it;
        }
        return null;
      }

      function hubBootstrapPasses(hubMeta) {
        return Array.isArray(hubMeta && hubMeta.passes) ? hubMeta.passes : [];
      }

      /**
       * Pass-only panel (no slots fetch) — upcoming booking, saved/past fill, etc.
       */
      function renderPrimaryPassPanel(trainerId, bootstrapPasses, opts) {
        opts = opts || {};
        var el = document.getElementById('hubPrimaryPanel');
        if (!el) return false;
        var passes = Array.isArray(bootstrapPasses) ? bootstrapPasses : [];
        var passInfo = trainerId != null && String(trainerId).trim() !== ''
          ? selectPrimaryPassForTrainer(passes, trainerId)
          : selectAnyActivePass(passes);
        var passHtml = buildPrimaryPassHtml(passInfo, opts);
        if (!passHtml) {
          hidePrimaryPanel();
          return false;
        }
        var rowHead = opts.rowHead ? String(opts.rowHead).trim() : '';
        var inner =
          (rowHead
            ? '<div class="hub-primary-panel__row hub-primary-panel__row--pass">' +
              '<div class="hub-primary-panel__row-head">' + esc(rowHead) + '</div>' +
              passHtml +
              '</div>'
            : passHtml);
        el.innerHTML = inner;
        el.removeAttribute('hidden');
        var wireTid = trainerId != null ? trainerId : (passInfo && passInfo.trainer_id);
        wirePrimaryPanelClicks(el, wireTid);
        return true;
      }

      /**
       * Secondary content so sparse hub states still feel alive: active pass + optional discovery.
       */
      function renderHubSecondaryFill(hubMeta, opts) {
        opts = opts || {};
        var passes = hubBootstrapPasses(hubMeta);
        renderPrimaryPassPanel(opts.trainerId != null ? opts.trainerId : null, passes, {
          autoDebitNote: !!opts.autoDebitNote,
          rowHead: opts.passRowHead || '',
        });
        if (opts.showDiscovery) return loadDiscoveryUnlessMarket();
        return Promise.resolve();
      }

      /* Cancels any in-flight /client/slots request when user navigates away */
      var _primaryPanelAbort = null;

      function loadAndRenderPrimaryPanel(trainerId, history, bootstrapPasses) {
        var el = document.getElementById('hubPrimaryPanel');
        if (!el) return Promise.resolve();
        if (trainerId == null || trainerId === '') {
          hidePrimaryPanel();
          return Promise.resolve();
        }
        if (!initData) {
          hidePrimaryPanel();
          return Promise.resolve();
        }

        // Cancel any previous in-flight slots request to free server resources immediately
        if (_primaryPanelAbort) { _primaryPanelAbort.abort(); }
        var ctl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
        _primaryPanelAbort = ctl;

        var tidStr = encodeURIComponent(String(trainerId));
        var slotsUrl = apiUrl('/client/slots?trainer_id=' + tidStr);
        var slotsPromise = fetch(slotsUrl, { headers: headersJson(), signal: ctl ? ctl.signal : undefined })
          .then(function(r) { return r.ok ? r.json() : { slots: [] }; })
          .catch(function(e) { return (e && e.name === 'AbortError') ? null : { slots: [] }; });

        // Passes come from bootstrap — no extra round-trip needed
        var passes = Array.isArray(bootstrapPasses) ? bootstrapPasses : [];

        return slotsPromise.then(function(slotsData) {
          if (!slotsData) return; // aborted navigation
          _primaryPanelAbort = null;
          var slots = (slotsData.slots || []).filter(function(s) {
            return s && String(s.start_time || '').trim();
          });
          slots.sort(function(a, b) {
            return parseDateTime(a.slot_date, a.start_time) - parseDateTime(b.slot_date, b.start_time);
          });
          var passInfo = selectPrimaryPassForTrainer(passes, trainerId);
          var passHtml = buildPrimaryPassHtml(passInfo, {});
          var histHtml = buildPrimaryHistoryHtml(history);
          var trainer = hubPrimaryTrainer;
          var canBook = !!(trainer && trainer.canBook && String(trainer.id) === String(trainerId));
          if (canBook && slots.length) {
            renderOpenWindowCard(trainer, slots);
            hubPersonalSlot = true;
            applyIceHeroVisibility();
            placeIceZone('top');
            var windowInner = passHtml + histHtml;
            if (!windowInner) {
              hidePrimaryPanel();
              return;
            }
            el.innerHTML = windowInner;
            el.removeAttribute('hidden');
            wirePrimaryPanelClicks(el, trainerId);
            return;
          }
          if (canBook && trainer && !document.getElementById('trainerCard')) {
            renderMyTrainerCard(
              trainer.id, trainer.name, trainer.username, trainer.telegramId, trainer.photo, true
            );
          }
          if (canBook) {
            hubPersonalSlot = false;
            applyIceHeroVisibility();
            placeIceZone('below-trainer');
          }
          var slotsHtml = buildPrimarySlotsHtml(slots);
          var inner = slotsHtml + passHtml + histHtml;
          if (!inner) {
            hidePrimaryPanel();
            return;
          }
          el.innerHTML = inner;
          el.removeAttribute('hidden');
          wirePrimaryPanelClicks(el, trainerId);
        });
      }

      function wirePrimaryPanelClicks(el, trainerId) {
        var serviceQuery = catalogPrimaryServiceQuery();
        var trainerBookPath = 'catalog?trainer_id=' + encodeURIComponent(String(trainerId)) + serviceQuery;
        el.addEventListener('click', function(ev) {
          var slotBtn = ev.target && ev.target.closest && ev.target.closest('.hub-primary-panel__slot');
          if (slotBtn) {
            ev.stopPropagation();
            navigateTo(buildBookPathFromHubContext(trainerId, {
              serviceId: slotBtn.getAttribute('data-service-id'),
              slotId: slotBtn.getAttribute('data-slot-id'),
              arenaId: slotBtn.getAttribute('data-arena-id'),
              fallbackServiceQuery: serviceQuery,
            }));
            return;
          }
          var passBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-action="open-pass"]');
          if (passBtn) {
            ev.stopPropagation();
            navigateTo('client-passes-certificates');
            return;
          }
        });
      }

      /* ── Discovery: real trainers carousel for new clients ───────────── */

      /** Same-origin proxy first — CDN often 404 in Telegram WebView and may not fire img.onerror. */
      function hubDiscoveryPhotoListSrc(photo) {
        if (!photo) return '';
        var fk = photo.file_key_list || photo.file_key;
        if (fk) return trainerHubThumb(fk);
        if (photo.list_url) return photo.list_url;
        if (photo.url) return photo.url;
        return '';
      }

      function hubDiscoveryPhotoCdnFallback(photo) {
        if (!photo) return '';
        if (photo.list_url) return photo.list_url;
        if (photo.url) return photo.url;
        return '';
      }

      function wireDiscoveryCardPhotos(root) {
        if (!root) return;
        root.querySelectorAll('.tcard__media img').forEach(function(img) {
          function showInitialsFallback() {
            var card = img.closest('.tcard');
            var media = img.closest('.tcard__media');
            if (!media) return;
            var nameEl = card && card.querySelector('.tcard__name');
            var name = nameEl ? nameEl.textContent : '?';
            // Сбой загрузки фото приводит к тому же плейсхолдеру, что и его отсутствие:
            // два разных вида «фото нет» выглядели бы как поломка.
            media.classList.add('tcard__media--empty');
            media.innerHTML = initials(name);
          }
          img.onerror = function() {
            var fb = img.getAttribute('data-fallback') || '';
            if (fb && img.src !== fb) {
              img.onerror = showInitialsFallback;
              img.src = fb;
              return;
            }
            showInitialsFallback();
          };
        });
      }

      /*
       * Услуги — завершённые единицы, а не склеенная строка (TASK-092 AC-002).
       *
       * Раньше это был `labels.join(' · ')` под `-webkit-line-clamp: 2`, из-за
       * чего вторая услуга почти всегда обрывалась многоточием. Теперь каждая
       * услуга — свой чип, а остаток честно считается: «ещё 2» вместо «…».
       *
       * Показываем два чипа: по данным у тренеров сейчас одна-две услуги, а
       * длина названий доходит до 36 символов, и третий чип вытеснил бы имя.
       */
      function hubDiscoveryServiceChips(services) {
        var labels = (services || []).map(function(s) {
          return String((s && (s.service_name || s.name)) || '').trim();
        }).filter(Boolean);
        if (!labels.length) return '';
        var shown = labels.slice(0, 2);
        var rest = labels.length - shown.length;
        var chips = shown.map(function(l) {
          return '<span class="tcard__svc">' + esc(l) + '</span>';
        });
        if (rest > 0) {
          chips.push('<span class="tcard__svc tcard__svc--more">ещё ' + esc(String(rest)) + '</span>');
        }
        return '<div class="tcard__svcs">' + chips.join('') + '</div>';
      }

      function buildDiscoveryCardHtml(t) {
        var p = t && t.profile;
        var name = (p ? (((p.first_name || '') + ' ' + (p.last_name || '')).trim()) : '') || 'Тренер';
        var photo = t && t.photos && t.photos[0];
        var src = hubDiscoveryPhotoListSrc(photo);
        var cdnFallback = hubDiscoveryPhotoCdnFallback(photo);
        var mediaHtml = src
          ? '<div class="tcard__media">' +
              '<img src="' + esc(src) + '" alt="" loading="eager" decoding="async"' +
              (cdnFallback && cdnFallback !== src
                ? ' data-fallback="' + esc(cdnFallback) + '"'
                : '') +
              '/></div>'
          : '<div class="tcard__media tcard__media--empty">' + esc(initials(name)) + '</div>';
        var arena = ((t && t.primary_arena_name) || '').toString().trim();
        var arenaHtml = arena ? '<div class="tcard__where">' + ICONS.pin + '<span>' + esc(arena) + '</span></div>' : '';
        var ratingHtml = '';
        if (p && p.rating_avg != null && (p.rating_count || 0) > 0) {
          ratingHtml =
            '<div class="tcard__rating">⭐ ' +
            esc(Number(p.rating_avg).toFixed(1)) +
            ' <span class="tcard__rating-count">(' + esc(String(p.rating_count)) + ')</span></div>';
        }
        var services = (t && Array.isArray(t.services)) ? t.services : [];
        var svcHtml = hubDiscoveryServiceChips(services);
        var tidStr = esc(String((t && t.id) || ''));
        // TASK-104: карусель хаба берёт компактный вариант компонента. Витринные
        // пропорции родные для списка «Льда», где карточка — главный объект экрана;
        // здесь тренеры — один блок из нескольких, и 380px съедали больше половины
        // полезной высоты у клиента, который ещё никого не выбрал.
        return (
          '<button type="button" class="tcard tcard--compact" data-tid="' + tidStr + '">' +
            mediaHtml +
            '<div class="tcard__body">' +
              '<div class="tcard__name">' + esc(name) + '</div>' +
              ratingHtml +
              arenaHtml +
            '</div>' +
            svcHtml +
          '</button>'
        );
      }

      /**
       * TASK-146 (DEC-009). Карточка места в карусели — тот же компактный tcard, что у
       * тренера: каталог один, и на Главной он выглядит одним, а не двумя витринами.
       * Вторая строка — то, ради чего идут: ближайший лёд, услуги магазина, часы зала.
       */
      function buildDiscoveryPlaceHtml(item) {
        var name = String((item && item.name) || '').trim();
        var thumb = item && (item.thumb || item.card);
        var mediaHtml = thumb
          ? '<div class="tcard__media"><img src="' + esc(thumb) + '" alt="" loading="lazy" decoding="async" /></div>'
          : '<div class="tcard__media tcard__media--empty">' + esc(initials(name)) + '</div>';
        var chip = String((item && item.venue_chip) || '').trim();
        var line = String((item && item.live_line) || '').trim();
        return (
          '<button type="button" class="tcard tcard--compact tcard--place" data-arena="' + esc(String(item.id)) + '">' +
            mediaHtml +
            '<div class="tcard__body">' +
              '<div class="tcard__name">' + esc(name) + '</div>' +
              (chip ? '<div class="tcard__where"><span>' + esc(chip) + '</span></div>' : '') +
              (line ? '<div class="tcard__rating">' + esc(line) + '</div>' : '') +
            '</div>' +
          '</button>'
        );
      }

      function fetchDiscoveryPlaces() {
        if (!discoveryCityId) return Promise.resolve([]);
        // Те же места, что во вкладке «Поиск»: живой лёд первым (tier A), магазины — по чипу.
        var url = '/api/public/ice/arenas?intent=skate&limit=4&city_id=' + encodeURIComponent(String(discoveryCityId));
        return fetch(url, { cache: 'no-store' })
          .then(function(r) { return r.ok ? r.json() : { items: [] }; })
          .then(function(p) {
            return ((p && p.items) || []).filter(function(i) {
              return i && i.id != null && Number(i.id) !== teaserArenaId;
            });
          })
          .catch(function() { return []; });
      }

      /**
       * Карусель лиц. TASK-149 (DEC-004): вызывается только через loadDiscoveryUnlessMarket —
       * как фолбэк, когда «Куда катимся» нечего показать. Заголовки «Места и тренеры» /
       * «Где заниматься» остаются только в этом фолбэке, где другой навигации по рынку нет.
       */
      function loadAndRenderDiscovery() {
        var el = document.getElementById('hubDiscovery');
        if (!el) return Promise.resolve();
        var url = '/api/public/trainers?limit=6';
        var trainersP = fetch(url, { headers: { 'Content-Type': 'application/json' } })
          .then(function(r) { return r.ok ? r.json() : { items: [] }; })
          .catch(function() { return { items: [] }; });
        return Promise.all([trainersP, fetchDiscoveryPlaces()])
          .then(function(parts) {
            // Плитки успели появиться, пока грузилась карусель, — она больше не нужна.
            var explore = document.getElementById('hubExplore');
            if (explore && !explore.hidden) {
              hideDiscovery();
              return;
            }
            var payload = parts[0];
            var places = (parts[1] || []).slice(0, 3);
            var items = (payload && (payload.items || payload.trainers)) || [];
            items = items.filter(function(t) { return t && t.id != null; }).slice(0, places.length ? 4 : 6);
            if (!items.length && !places.length) {
              hideDiscovery();
              return;
            }
            var cards = places.map(buildDiscoveryPlaceHtml).join('') + items.map(buildDiscoveryCardHtml).join('');
            // Заголовок — о том, что в карусели реально лежит, а не обещание всего каталога.
            var title = places.length && items.length
              ? 'Места и тренеры'
              : places.length
                ? 'Где заниматься'
                : 'Тренеры на платформе';
            el.innerHTML =
              '<div class="hub-discovery__head">' +
                '<span class="hub-discovery__title">' + title + '</span>' +
                '<button type="button" class="hub-discovery__link" id="hubDiscoveryAll">Все</button>' +
              '</div>' +
              '<div class="hub-discovery__row">' + cards + '</div>';
            el.removeAttribute('hidden');
            wireDiscoveryCardPhotos(el);
            var allBtn = document.getElementById('hubDiscoveryAll');
            if (allBtn) {
              allBtn.addEventListener('click', function() {
                navigateTo(
                  places.length
                    ? 'ice?city_id=' + encodeURIComponent(String(discoveryCityId))
                    : 'ice?intent=coach'
                );
              });
            }
            el.querySelectorAll('.tcard').forEach(function(btn) {
              btn.addEventListener('click', function() {
                var arena = btn.getAttribute('data-arena');
                if (arena) {
                  navigateTo('arena?ref=' + encodeURIComponent(arena));
                  return;
                }
                var tid = btn.getAttribute('data-tid');
                if (tid) navigateTo('catalog?trainer_id=' + encodeURIComponent(tid));
              });
            });
          });
      }

      /* ── Upcoming bookings list ──────────────────────────────────────── */

      function revealBookingsBlock(innerHtml) {
        var block = document.getElementById('bookingsBlock');
        if (!block) return;
        block.innerHTML = '<div class="hub-bookings-mount">' + innerHtml + '</div>';
        var mount = block.firstElementChild;
        if (!mount) return;
        requestAnimationFrame(function() {
          requestAnimationFrame(function() { mount.classList.add('hub-bookings-mount--visible'); });
        });
      }

      function wireUpcomingBookingsBlock() {
        var bblock = document.getElementById('bookingsBlock');
        if (!bblock || bblock.getAttribute('data-hub-list-wired') === '1') return;
        bblock.setAttribute('data-hub-list-wired', '1');
        bblock.addEventListener(
          'click',
          function(ev) {
            var dmBtn = ev.target && ev.target.closest && ev.target.closest('[data-hub-dm="list"]');
            if (dmBtn) {
              ev.preventDefault();
              ev.stopPropagation();
              if (window.ClientShell && typeof window.ClientShell.hapticSelection === 'function') {
                window.ClientShell.hapticSelection();
              }
              openTelegramDm(
                dmBtn.getAttribute('data-dm-un'),
                dmBtn.getAttribute('data-dm-tid'),
                dmBtn.getAttribute('data-trainer-id')
              );
              return;
            }
            var row = ev.target && ev.target.closest && ev.target.closest('.hub-booking-row[data-bid]');
            if (!row) return;
            var bid = row.getAttribute('data-bid');
            if (bid) navigateTo('client-bookings?open_booking=' + encodeURIComponent(bid) + '&from=hub');
          },
          true
        );
      }

      /**
       * Следующие записи — отдельный блок ПОД «моей карточкой» (TASK-160 S2).
       * Вкладывать их внутрь карточки больше некуда: её рамка занята кошельком
       * и подвалом. Поведение строк то же: штамп тот же, кнопки сообщения нет,
       * строка открывает свою запись, больше HUB_REST_MAX на хаб не выносится.
       */
      function renderUpcomingList(days, heroBookingId) {
        var section = document.getElementById('upcomingSection');
        if (section) section.style.display = 'none';
        var block = document.getElementById('nextBookingBlock');
        if (block) {
          var prev = block.querySelector('.rest');
          if (prev) prev.remove();
        }
        var rest = flattenBookings(days).filter(function(item) {
          return String(item.b.id) !== String(heroBookingId);
        });
        var items = rest.slice(0, HUB_REST_MAX);
        if (!items.length || !block) return;

        var byDate = {};
        var dateOrder = [];
        items.forEach(function(item) {
          var ds = item.day.date || '';
          if (!byDate[ds]) { byDate[ds] = { day: item.day, rows: [] }; dateOrder.push(ds); }
          byDate[ds].rows.push(item);
        });

        var parts = ['<div class="rest">'];
        dateOrder.forEach(function(ds) {
          var group = byDate[ds];
          parts.push('<div class="hub-next-card-day">' + esc(relativeDate(ds, group.day.day_label)) + '</div>');
          group.rows.forEach(function(item) {
            var b = item.b;
            var stamp = nextCardStamp(b, item.start);
            var time = (b.start_time || '').slice(0, 5);
            var dur = b.duration_minutes || 45;
            var trainerName = b.trainer_name || 'Тренер';
            var place = ((b.arena_name || b.place_display || '') + '').trim();
            parts.push(
              '<button type="button" class="hub-next-card-line" data-bid="' + esc(String(b.id)) + '">' +
                '<span class="hub-next-card-line-when">' +
                  '<span class="hub-next-card-line-clock">' + esc(time) + '</span>' +
                  '<span class="hub-next-card-line-dur">' + esc(String(dur)) + ' мин</span>' +
                '</span>' +
                '<span class="hub-next-card-line-who">' +
                  '<span class="hub-next-card-line-name">' + esc(trainerName) + '</span>' +
                  (place ? '<span class="hub-next-card-line-place">' + esc(place) + '</span>' : '') +
                '</span>' +
                '<span class="hub-next-card-pill hub-next-card-pill--' + stamp.kind + '">' +
                  '<i class="hub-next-card-status-dot" aria-hidden="true"></i>' + esc(stamp.label) +
                '</span>' +
              '</button>'
            );
          });
        });
        if (rest.length > items.length) {
          parts.push('<button type="button" class="hub-next-card-more" data-hub-action="all-bookings">Смотреть все</button>');
        }
        parts.push('</div>');
        block.insertAdjacentHTML('beforeend', parts.join(''));
      }


      /* ── Saved trainers strip ───────────────────────────────────────── */

      function thumbForHubPhoto(key) {
        if (!key) return '';
        return '/api/public/photos/' + encodeURIComponent(key);
      }

      /**
       * Renders a horizontal scroll strip of saved (bookmarked) trainers.
       * Uses `client_session.saved_trainers` from hub bootstrap when present (names + photo keys).
       */
      function renderSavedTrainersStrip(cs) {
        var block = document.getElementById('myTrainerBlock');
        if (!block) return;
        var list = [];
        if (cs && Array.isArray(cs.saved_trainers) && cs.saved_trainers.length) {
          list = cs.saved_trainers;
        } else if (cs && Array.isArray(cs.saved_trainer_ids) && cs.saved_trainer_ids.length) {
          cs.saved_trainer_ids.forEach(function (id) {
            list.push({
              trainer_id: id,
              trainer_display_name: 'Тренер',
              trainer_list_photo_key: null
            });
          });
        }
        if (!list.length) return;
        var chips = list.map(function (row) {
          var tid = row.trainer_id;
          var label = (row.trainer_display_name || 'Тренер').trim() || 'Тренер';
          var src = thumbForHubPhoto(row.trainer_list_photo_key || null);
          var photoPart = src
            ? '<span class="hub-saved-chip-avatar"><img src="' + esc(src) + '" alt=""/></span>'
            : '<span class="hub-saved-chip-icon" aria-hidden="true">🤍</span>';
          return '<button type="button" class="hub-saved-chip" data-tid="' + esc(String(tid)) + '">' +
            photoPart +
            '<span class="hub-saved-chip-label">' + esc(label) + '</span>' +
            '</button>';
        }).join('');
        block.innerHTML =
          '<div class="hub-saved-section">' +
            '<div class="hub-saved-section-head">' +
              '<span class="hub-saved-section-title">Сохранённые тренеры</span>' +
              '<button type="button" class="hub-saved-section-link" id="btnViewSaved">Все</button>' +
            '</div>' +
            '<div class="hub-saved-strip">' + chips + '</div>' +
          '</div>';
        block.style.display = '';
        var viewBtn = document.getElementById('btnViewSaved');
        if (viewBtn) viewBtn.addEventListener('click', function() { navigateTo('client-saved-trainers'); });
        block.querySelectorAll('.hub-saved-chip').forEach(function(btn) {
          btn.addEventListener('click', function() {
            navigateTo('catalog?trainer_id=' + encodeURIComponent(btn.getAttribute('data-tid')));
          });
        });
      }

      /* ── Main state machine — Intent Engine ─────────────────────────── */

      /**
       * Home intent priority (strict order — first matching level wins):
       *   1. Upcoming booking  → booking hero card + pass (auto-debit note) + rebook pills + list
       *   2. Primary trainer   → "Мой тренер" card + slots / pass / history panel
       *   3. Saved trainers    → saved strip + pass (if any) + discovery carousel
       *   4. Has past sessions → rebook pills + pass (if any) + discovery carousel
       *   5. Clean state       → acquisition hero + discovery carousel
       *
       * This is a decision engine, not a dashboard.
       * It answers: "what is the most important thing for the client right now?"
       */
      var HUB_GEO_REFINED_FLAG = 'glide_hub_geo_refined_v1';

      /**
       * The hub's ice_teaser is a country-wide "closest upcoming session, however far"
       * fallback for a client with no city (get_hub_ice_teaser, `is_country_fallback`).
       * On first paint distance is unknown (no coordinates yet), so it just shows that
       * fallback plainly. Once geolocation resolves, re-ask for the same teaser with
       * `near=` so it can render the honest "not in your city yet" card when it's actually
       * far — same 150km bar as the catalog's own auto-detect (CatalogGeoModel).
       *
       * Uses its own decline/attempted flag (HUB_GEO_REFINED_FLAG), separate from the
       * catalog's `glide_geo_declined_v1`: this call never sets a city (there's nothing to
       * persist, just a distance to compute), so it must not suppress — or be suppressed
       * by — the catalog's own auto-detect, which does set one.
       */
      function attemptHubGeoRefine() {
        var G = window.CatalogGeoModel;
        if (!G) return;
        var already = G.readDeclinedFlag(window.localStorage, HUB_GEO_REFINED_FLAG);
        var go = G.shouldAutoGeolocate({
          cityId: null,
          hasExplicitQueryCityId: false,
          hasCollectiveContext: false,
          hasDeepLinkTrainer: false,
          hasPrimaryTrainer: false,
          geolocationSupported: !!(window.navigator && window.navigator.geolocation),
          previouslyDeclined: already,
        });
        if (!go) return;
        window.navigator.geolocation.getCurrentPosition(
          function (pos) {
            G.writeDeclinedFlag(window.localStorage, HUB_GEO_REFINED_FLAG);
            var near = pos.coords.latitude.toFixed(5) + ',' + pos.coords.longitude.toFixed(5);
            fetch('/api/webapp/client/hub/ice-teaser?near=' + encodeURIComponent(near), { cache: 'no-store' })
              .then(function (r) { return r.json(); })
              .then(function (data) {
                renderIceTeaser(data && data.ice_teaser);
                // TASK-149: строки сеансов зависят от героя (далёкая карточка их прячет).
                renderIceTodaySessions(data && data.ice_teaser);
              })
              .catch(function () { /* keep the plain fallback card already on screen */ });
          },
          function () {
            G.writeDeclinedFlag(window.localStorage, HUB_GEO_REFINED_FLAG);
          },
          { timeout: 6000, maximumAge: 60000 }
        );
      }

      function applyHubState(bookingDays, requestItems, hubMeta) {
        hubPersonalSlot = false;
        hubPrimaryTrainer = null;
        hubOpenWindowShown = false;
        if (window.ClientShell && typeof window.ClientShell.writeBookingsWarmCache === 'function') {
          window.ClientShell.writeBookingsWarmCache({ days: bookingDays || [] });
        }
        var cs = (hubMeta && hubMeta.client_session) || {};
        var iceTeaser = hubMeta && hubMeta.ice_teaser;
        renderIceTeaser(iceTeaser);
        /* TASK-149 (S2): строки сеансов — внутри блока льда, из тех же live-данных тизера. */
        renderIceTodaySessions(iceTeaser);
        setHubGreetingFacts(iceTeaser);
        teaserArenaId = iceTeaser && iceTeaser.arena_id != null ? Number(iceTeaser.arena_id) : null;
        discoveryCityId =
          (cs.city_id != null && cs.city_id !== '' ? Number(cs.city_id) : null) ||
          (iceTeaser && !iceTeaser.is_country_fallback && iceTeaser.city_id ? Number(iceTeaser.city_id) : null);
        /* TASK-149 (S3): «Куда катимся» — монтируется по данным, ниже персональных блоков. */
        hubMarketPromise = renderHubExplore(discoveryCityId);
        // far_confirmed means IP-country (src/shared/ip_geo.py) already told us this visitor
        // is outside every served market — the honest card is already showing, GPS would
        // only ask for a permission we don't need.
        if (iceTeaser && iceTeaser.is_country_fallback && !iceTeaser.far_confirmed) {
          attemptHubGeoRefine();
        }
        // Support both legacy (selected_trainer_id) and new edge-based fields
        var primaryTrainerId = cs.primary_trainer_id != null ? cs.primary_trainer_id
          : (cs.selected_trainer_id != null && cs.selected_trainer_id !== '' ? cs.selected_trainer_id : null);
        var savedTrainersRich = Array.isArray(cs.saved_trainers) ? cs.saved_trainers : [];
        var savedIds = Array.isArray(cs.saved_trainer_ids) ? cs.saved_trainer_ids : [];
        var hasSavedBookmarks = savedTrainersRich.length > 0 || savedIds.length > 0;
        var hasPastSessions = !!cs.has_past_sessions;
        selectedTrainerId = primaryTrainerId;
        var rawPcs = cs.primary_catalog_service_id;
        if (rawPcs != null && rawPcs !== '') {
          var ppn = Number(rawPcs);
          primaryCatalogServiceId = !isNaN(ppn) && ppn > 0 ? ppn : null;
        } else {
          primaryCatalogServiceId = null;
        }

        var rawLt = cs.last_booking_trainer_id;
        if (rawLt != null && String(rawLt).trim() !== '') {
          var nlt = Number(rawLt);
          lastBookingTrainerId = !isNaN(nlt) && nlt > 0 ? nlt : null;
        } else {
          lastBookingTrainerId = null;
        }
        var rawLs = cs.last_booking_service_id;
        if (rawLs != null && String(rawLs).trim() !== '') {
          var nls = Number(rawLs);
          lastBookingServiceId = !isNaN(nls) && nls > 0 ? nls : null;
        } else {
          lastBookingServiceId = null;
        }

        rebookTargets = Array.isArray(cs.rebook_targets) ? cs.rebook_targets : [];
        hubPrimaryTrainerCanBook = cs.primary_trainer_can_book === true;

        function finishHubApply(promise) {
          syncClientHubBookFab();
          return promise;
        }

        var nextItem = findNextBooking(bookingDays);
        hubHasUpcomingBooking = !!nextItem;

        /* ── Priority 1: Has upcoming booking ── */
        if (nextItem) {
          resetHubChromeForState({ keepHeroLayout: true });
          configureHeroForUpcomingBooking();
          placeIceZone('top');
          hubPersonalSlot = true;
          applyIceHeroVisibility();
          /* TASK-160 (S2): герой записи — «моя карточка» (hub-me-card.js).
             Остаток выбирает сама модель: под лицом в карточке показывается
             только остаток этого тренера, поэтому отбора абонемента здесь нет. */
          renderMeCardForBooking(nextItem, hubMeta);
          hideMyTrainerBlock();
          renderQuickStrip('has-booking', nextItem);
          renderUpcomingList(bookingDays, nextItem.b.id);
          placeQuickStrip('after-slot');
          return finishHubApply(Promise.resolve());
        }

        clearNextBookingBlock();
        hideUpcomingSection();
        resetHubChromeForState();
        placeIceZone('top');

        /* ── Priority 2: Has primary trainer ── */
        if (primaryTrainerId != null) {
          resetHubHeroLayout();
          var pname = (cs.primary_trainer_name || '').trim();
          var pphoto = cs.primary_trainer_list_photo_key || null;
          var ptgUn = cs.primary_trainer_telegram_username || null;
          var ptgId = cs.primary_trainer_telegram_id != null ? cs.primary_trainer_telegram_id : null;
          var pCanBook = cs.primary_trainer_can_book === true;
          hubPrimaryTrainer = {
            id: primaryTrainerId,
            name: pname || null,
            username: ptgUn,
            telegramId: ptgId,
            photo: pphoto,
            canBook: pCanBook,
          };
          if (pCanBook) {
            hideMyTrainerBlock();
            placeIceZone('top');
            hubPersonalSlot = true;
            applyIceHeroVisibility();
          } else {
            renderMyTrainerCard(primaryTrainerId, pname || null, ptgUn, ptgId, pphoto, pCanBook);
            placeIceZone('below-trainer');
          }
          return finishHubApply(
            loadAndRenderPrimaryPanel(primaryTrainerId, cs.primary_history || null, hubBootstrapPasses(hubMeta))
          );
        }

        /* ── Priority 3: Has saved trainers (no primary yet) ── */
        if (hasSavedBookmarks && primaryTrainerId == null) {
          resetHubHeroLayout();
          renderSavedTrainersStrip(cs);
          return finishHubApply(renderHubSecondaryFill(hubMeta, { showDiscovery: true, passRowHead: 'Абонемент' }));
        }

        /* ── Priority 4: Has past sessions (churned / dormant) ── */
        if (hasPastSessions) {
          resetHubHeroLayout();
          hideMyTrainerBlock();
          renderQuickStrip('has-past', null);
          return finishHubApply(renderHubSecondaryFill(hubMeta, { showDiscovery: true, passRowHead: 'Абонемент' }));
        }

        /* ── Priority 5: Clean state — find trainer and book ── */
        resetHubHeroLayout();
        clearNextBookingBlock();
        hideMyTrainerBlock();
        return finishHubApply(loadDiscoveryUnlessMarket());
      }

      function hideMyTrainerBlock() {
        var b = document.getElementById('myTrainerBlock');
        if (b) b.style.display = 'none';
      }

      function hideUpcomingSection() {
        var s = document.getElementById('upcomingSection');
        if (s) s.style.display = 'none';
      }

      /* ── Data loading ────────────────────────────────────────────────── */
      function jsonOrThrow(r) {
        return r.json().then(function(d) {
          if (!r.ok) throw new Error(d.detail || r.statusText);
          return d;
        });
      }

      function loadAll() {
        hubLoadStartedAt = Date.now();
        // TASK-149 (S1): приветствие по часу устройства сразу — не ждём bootstrap.
        setHubGreeting(defaultHubGreeting());
        wireAllBookingsLink();
        if (!initData) {
          setStateMessage('', '');
          hideNextBookingSkeleton();
          clearNextBookingBlock();
          // Без initData данных нет, но поиск обязан остаться доступным.
          renderIceTeaser(null);
          renderIceTodaySessions(null);
          hubMarketPromise = renderHubExplore(null);
          renderStreakRibbon(null);
          return loadDiscoveryUnlessMarket().then(finishHubInitialLoading, finishHubInitialLoading);
        }

        /* Bootstrap API: wait for acting profile so X-Profile-Id is set (default child ≠ self). */
        var profilesReady =
          window.ClientProfileSwitcher && typeof ClientProfileSwitcher.init === 'function'
            ? ClientProfileSwitcher.init()
            : Promise.resolve();

        return profilesReady
          .then(function () {
            return fetch(apiUrl('/client/hub/bootstrap'), { headers: headersJson(), cache: 'no-store' });
          })
          .then(jsonOrThrow)
          .then(function(hub) {
            if (renderPendingReferralGate(hub.pending_referral)) {
              return;
            }
            var days = (hub.bookings || {}).days || [];
            var reqs = (hub.requests || {}).items || [];
            renderStreakRibbon(hub.activity || {});
            if (window.ClientShell && typeof window.ClientShell.scheduleCatalogNavigationPrefetch === 'function') {
              window.ClientShell.scheduleCatalogNavigationPrefetch();
            }
            return applyHubState(days, reqs, hub);
          })
          .catch(function() {
            /* Fallback: parallel individual calls */
            return Promise.all([
              fetch(apiUrl('/client/bookings'), { headers: headersJson() }).then(jsonOrThrow),
              fetch(apiUrl('/client/requests'), { headers: headersJson() }).then(jsonOrThrow),
              fetch(apiUrl('/client/session'), { headers: headersJson(), cache: 'no-store' }).then(jsonOrThrow).catch(function() { return {}; }),
            ]).then(function(results) {
              var sess = results[2] || {};
              if (renderPendingReferralGate(sess.pending_referral)) {
                return;
              }
              renderStreakRibbon(null);
              return applyHubState(
                results[0].days || [],
                results[1].items || [],
                { client_session: { selected_trainer_id: sess.trainer_id != null ? sess.trainer_id : null } }
              );
            });
          })
          .catch(function() {
            setStateMessage('Не удалось загрузить данные. Откройте страницу из клиентского бота.', 'error');
            hideNextBookingSkeleton();
            clearNextBookingBlock();
            hideMyTrainerBlock();
            hideUpcomingSection();
            renderIceTodaySessions(null);
            renderHubExplore(null);
            renderStreakRibbon(null);
            hubPrimaryTrainerCanBook = false;
            syncClientHubBookFab();
          })
          .then(finishHubInitialLoading, finishHubInitialLoading);
      }

      (function wireHubFootnoteCollapse() {
        var root = document.getElementById('hubFootnote');
        var btn = document.getElementById('hubFootnoteToggle');
        var panel = document.getElementById('hubFootnoteExpand');
        if (!root || !btn) return;
        btn.addEventListener('click', function() {
          var open = root.classList.toggle('hub-footnote--open');
          btn.setAttribute('aria-expanded', open ? 'true' : 'false');
          if (panel) panel.setAttribute('aria-hidden', open ? 'false' : 'true');
          if (open && typeof root.scrollIntoView === 'function') {
            try {
              root.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            } catch (eScroll) {
              /* noop */
            }
          }
        });
      })();

      (function wireHubSupportForm() {
        var form = document.getElementById('hubSupportForm');
        var ta = document.getElementById('hubSupportMessage');
        var btn = document.getElementById('hubSupportSubmit');
        var statusEl = document.getElementById('hubSupportStatus');
        if (!form || !ta || !btn) return;
        form.addEventListener('submit', function(ev) {
          ev.preventDefault();
          var text = (ta.value || '').trim();
          if (!text) {
            if (statusEl) {
              statusEl.textContent = 'Напишите пару слов — что случилось или что хотите улучшить.';
              statusEl.className = 'hub-support-status hub-support-status--err';
            }
            return;
          }
          if (!initData) {
            if (statusEl) {
              statusEl.textContent =
                'Откройте страницу из клиентского бота или отправьте сообщение через /guide.';
              statusEl.className = 'hub-support-status hub-support-status--err';
            }
            return;
          }
          btn.disabled = true;
          if (statusEl) {
            statusEl.textContent = 'Отправляем…';
            statusEl.className = 'hub-support-status';
          }
          fetch(apiUrl('/support'), {
            method: 'POST',
            headers: headersJson(),
            body: JSON.stringify({ message: text, role: 'client' }),
          })
            .then(function(r) {
              return r.json().then(function(data) {
                return { ok: r.ok, data: data };
              });
            })
            .then(function(o) {
              btn.disabled = false;
              var sid = o.data && o.data.id;
              var okSend = o.ok && o.data && o.data.ok !== false && sid != null;
              if (okSend) {
                ta.value = '';
                if (statusEl) {
                  statusEl.textContent =
                    'Спасибо за ваше сообщение! 💛 Мы обязательно прочитаем и ответим в боте.';
                  statusEl.className = 'hub-support-status hub-support-status--ok';
                }
                var wg = window.Telegram && window.Telegram.WebApp;
                if (wg && wg.HapticFeedback && wg.HapticFeedback.notificationOccurred) {
                  try {
                    wg.HapticFeedback.notificationOccurred('success');
                  } catch (eh) {
                    /* noop */
                  }
                }
              } else {
                var detail =
                  o.data && (o.data.detail || o.data.message)
                    ? String(o.data.detail || o.data.message)
                    : 'Не удалось отправить.';
                if (statusEl) {
                  statusEl.textContent = detail + ' Попробуйте через /guide в боте.';
                  statusEl.className = 'hub-support-status hub-support-status--err';
                }
              }
            })
            .catch(function() {
              btn.disabled = false;
              if (statusEl) {
                statusEl.textContent =
                  'Сеть недоступна. Повторите позже или напишите через /guide в боте.';
                statusEl.className = 'hub-support-status hub-support-status--err';
              }
            });
        });
      })();


      loadAll();
    })();
