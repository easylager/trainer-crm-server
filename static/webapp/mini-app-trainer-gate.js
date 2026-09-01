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

  /**
   * @returns {Promise<{ access_state: string, trainer_id: number|null, is_active: boolean }>}
   */
  function fetchTrainerAccess(initData) {
    if (!initData || String(initData).length < 10) {
      return Promise.resolve({ access_state: 'not_linked', trainer_id: null, is_active: false });
    }
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
        if (
          typeof global.document !== 'undefined' &&
          d &&
          typeof d === 'object' &&
          Object.prototype.hasOwnProperty.call(d, 'force_client_chat_relay')
        ) {
          var forceRelay = !!d.force_client_chat_relay;
          global.TRAINER_WEBAPP_FORCE_CLIENT_CHAT_RELAY = forceRelay;
          global.TRAINER_HUB_FORCE_CLIENT_CHAT_RELAY = forceRelay;
        }
        if (d && typeof d.collective_enabled === 'boolean') {
          global.TRAINER_COLLECTIVE_ENABLED = d.collective_enabled;
        }
        return d;
      });
    });
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
        icon: '🔗',
        title: 'Только для тренеров',
        hint: 'Этот бот только для тренеров. Подключение по ссылке с сайта.',
      };
    }
    return {
      icon: '🔗',
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
