/**
 * Trainer Mini App onboarding gate: one GET /api/webapp/trainer/access, friendly UI when not active.
 * Depends on theme.css + mini-app-components.css for .bd-trainer-gate.
 */
(function (global) {
  'use strict';

  var _blockingOverlayActive = false;

  function apiAccessUrl(initData) {
    var path = '/api/webapp/trainer/access';
    if (!initData) return path;
    return path + (path.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
  }

  /*
   * Доступ меняется редко (деактивация), а спрашивали его на каждой вкладке и только потом
   * шли за данными экрана — лишний круг до сервера перед каждым экраном. Ответ
   * помним 10 минут в рамках сессии Telegram и сверяем в фоне; если сервер ответил иначе —
   * перезагружаем экран, чтобы гейт показался честно.
   */
  var ACCESS_CACHE_KEY = 'trainer_access_v1';
  var ACCESS_CACHE_TTL_MS = 10 * 60 * 1000;

  function initFingerprint(initData) {
    var s = String(initData || '');
    var m = /(?:^|&)hash=([^&]+)/.exec(s);
    return m ? m[1] : s.slice(-64);
  }

  function applyAccessSideEffects(d) {
    if (!d || typeof d !== 'object') return;
    if (Object.prototype.hasOwnProperty.call(d, 'force_client_chat_relay')) {
      var forceRelay = !!d.force_client_chat_relay;
      global.TRAINER_WEBAPP_FORCE_CLIENT_CHAT_RELAY = forceRelay;
      global.TRAINER_HUB_FORCE_CLIENT_CHAT_RELAY = forceRelay;
    }
    if (typeof d.collective_enabled === 'boolean') {
      global.TRAINER_COLLECTIVE_ENABLED = d.collective_enabled;
    }
    /* Валюта тренера по городу (BYN/RUB): другим экранам — через TrainerFormat.currencyCode(). */
    if (typeof d.currency === 'string' && d.currency) {
      global.TRAINER_CURRENCY = d.currency;
      try { global.sessionStorage.setItem('trainer_currency_v1', d.currency); } catch (e) { /* */ }
    }
  }

  function rememberAccess(initData, d) {
    try {
      if (d && typeof d === 'object' && d.access_state) {
        sessionStorage.setItem(
          ACCESS_CACHE_KEY,
          JSON.stringify({ at: Date.now(), fp: initFingerprint(initData), d: d })
        );
      } else {
        sessionStorage.removeItem(ACCESS_CACHE_KEY);
      }
    } catch (e) { /* */ }
  }

  function readRememberedAccess(initData) {
    try {
      var raw = sessionStorage.getItem(ACCESS_CACHE_KEY);
      if (!raw) return null;
      var c = JSON.parse(raw);
      if (!c || !c.d || !c.d.access_state) return null;
      if (c.fp !== initFingerprint(initData)) return null;
      if (!(Date.now() - c.at < ACCESS_CACHE_TTL_MS)) return null;
      return c.d;
    } catch (e) {
      return null;
    }
  }

  function fetchTrainerAccessFromServer(initData) {
    return fetch(apiAccessUrl(initData), {
      method: 'GET',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        'X-Telegram-Init-Data': initData,
      },
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error((d && d.detail) || r.statusText || 'access');
        if (typeof global.document !== 'undefined') applyAccessSideEffects(d);
        rememberAccess(initData, d);
        return d;
      });
    });
  }

  /**
   * @returns {Promise<{ access_state: string, trainer_id: number|null, is_active: boolean }>}
   */
  function fetchTrainerAccess(initData) {
    if (!initData || String(initData).length < 10) {
      return Promise.resolve({ access_state: 'not_linked', trainer_id: null, is_active: false });
    }
    var remembered = readRememberedAccess(initData);
    if (remembered) {
      applyAccessSideEffects(remembered);
      fetchTrainerAccessFromServer(initData)
        .then(function (fresh) {
          if (
            !fresh ||
            fresh.access_state !== remembered.access_state ||
            fresh.is_active !== remembered.is_active ||
            fresh.schedule_unlocked !== remembered.schedule_unlocked
          ) {
            global.location.reload();
          }
        })
        .catch(function () { /* сеть моргнула — остаёмся на запомненном */ });
      return Promise.resolve(remembered);
    }
    return fetchTrainerAccessFromServer(initData);
  }

  function webappBasePath() {
    var p = global.location.pathname || '';
    return p.replace(/[^/]+$/, '') || '/webapp/';
  }

  function withInit(page, initData) {
    var url = webappBasePath() + page.replace(/^\//, '');
    if (!initData) return url;
    return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
  }

  function isHubPage() {
    return /trainer-home(?:\.html)?$/i.test(String(global.location.pathname || ''));
  }

  /**
   * Онбординг v2: у гейта осталось два настоящих состояния.
   *
   * blocked_profile / booking_ready / pending_moderation удалены вместе со старой моделью:
   * незаполненная анкета и очередь модерации больше не закрывают тренеру его же инструменты,
   * поэтому и объяснять здесь нечего. Если сервер когда-нибудь вернёт незнакомое состояние,
   * мы показываем нейтральный текст, а не пугающий.
   */
  function gateCopy(access) {
    var st = (access && access.access_state) || '';
    if (st === 'deactivated') {
      return {
        icon: '⏸️',
        title: 'Аккаунт на паузе',
        hint: 'Профиль деактивирован. Если это ошибка — напишите в поддержку через /guide в боте.',
      };
    }
    if (st === 'not_linked') {
      return {
        icon: '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>',
        title: 'Только для тренеров',
        hint: 'Этот бот только для тренеров. Подключение по ссылке с сайта.',
      };
    }
    return {
      icon: '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>',
      title: 'Откройте из бота',
      hint: 'Запустите мини-приложение из чата бота тренера (кнопка в меню или под сообщением).',
    };
  }

  function gateActionsHtml(access) {
    var st = (access && access.access_state) || '';
    if (st === 'not_linked' || st === 'deactivated' || isHubPage()) return '';
    return (
      '<div class="bd-trainer-gate__actions">' +
      '<button type="button" class="bd-btn bd-btn--secondary" data-trainer-gate="hub">На главную</button>' +
      '</div>'
    );
  }

  function gateCardHtml(access, compact) {
    var c = gateCopy(access);
    var compactClass = compact ? ' bd-trainer-gate__card--compact' : '';
    return (
      '<div class="bd-trainer-gate__card' +
      compactClass +
      '">' +
      '<div class="bd-trainer-gate__icon" aria-hidden="true">' +
      c.icon +
      '</div>' +
      '<h2 class="bd-trainer-gate__title">' +
      c.title +
      '</h2>' +
      '<p class="bd-trainer-gate__hint">' +
      c.hint +
      '</p>' +
      gateActionsHtml(access) +
      '</div>'
    );
  }

  function wireGate(container, initData) {
    if (!container) return;
    container.querySelectorAll('[data-trainer-gate]').forEach(function (btn) {
      btn.onclick = function () {
        /* Осталась одна кнопка — «На главную»: гейт больше не ведёт в анкету. */
        var a = btn.getAttribute('data-trainer-gate');
        if (a === 'hub') window.location.href = withInit('trainer-home', initData);
      };
    });
  }

  function showBlockingOverlay(access) {
    var id = 'trainerAccessGateOverlay';
    var el = document.getElementById(id);
    if (!el) {
      el = document.createElement('div');
      el.id = id;
      el.className = 'bd-trainer-gate bd-trainer-gate--overlay';
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-modal', 'true');
      document.body.appendChild(el);
    }
    var tg = global.Telegram && global.Telegram.WebApp;
    var initData = tg && tg.initData ? tg.initData : '';
    el.innerHTML = gateCardHtml(access, false);
    el.style.display = 'flex';
    _blockingOverlayActive = true;
    wireGate(el, initData);
  }

  function hideBlockingOverlay() {
    var el = document.getElementById('trainerAccessGateOverlay');
    if (el) el.style.display = 'none';
    _blockingOverlayActive = false;
  }

  global.TrainerMiniAppGate = {
    fetchAccess: fetchTrainerAccess,
    /** Главная получает доступ в hub/bootstrap — кладём его сюда, чтобы вкладки не спрашивали снова. */
    rememberAccess: rememberAccess,
    gateCardHtml: gateCardHtml,
    wireGate: wireGate,
    showBlockingOverlay: showBlockingOverlay,
    hideBlockingOverlay: hideBlockingOverlay,
    shouldBlockFeatureFetch: function () {
      return _blockingOverlayActive;
    },
    /**
     * «Может работать». Единственная закрытая дверь — деактивированный аккаунт;
     * модерация каталога сюда больше не входит.
     */
    isActive: function (a) {
      if (!a) return false;
      var st = String(a.access_state || '').trim().toLowerCase();
      if (st === 'deactivated' || st === 'not_linked') return false;
      if (a.schedule_unlocked === true || a.schedule_unlocked === 'true' || a.schedule_unlocked === 1) return true;
      if (st === 'active') return true;
      if (a.is_active === true || a.is_active === 'true' || a.is_active === 1) return true;
      return String(a.trainer_status || '').trim().toLowerCase() === 'active';
    },
  };
})(window);
