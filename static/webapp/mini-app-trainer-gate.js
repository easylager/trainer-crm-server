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
        /* Mirrors Settings.trainer_webapp_force_client_chat_relay — TrainerRelayHelpers + hub delegates read these. */
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
        return d;
      });
    });
  }

  function webappBasePath() {
    var p = window.location.pathname || '';
    return p.replace(/[^/]+$/, '') || '/webapp/';
  }

  function withInit(page, initData) {
    var url = webappBasePath() + page.replace(/^\//, '');
    if (!initData) return url;
    return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
  }

  function gateCopy(access) {
    var st = (access && access.access_state) || '';
    if (st === 'blocked_profile') {
      return {
        icon: '📋',
        title: 'Сначала анкета',
        hint:
          'Заполните профиль в разделе «Первые шаги» и отправьте анкету на проверку. После активации откроются расписание, заявки и остальные разделы — это не ошибка сети.',
      };
    }
    if (st === 'booking_ready') {
      return {
        icon: '🚀',
        title: 'Почти готово',
        hint:
          'Базовый профиль достаточен: откройте «Расписание» или «Обзор» и сделайте первую тестовую запись. Полную анкету для каталога можно дополнить позже в «Профиле».',
      };
    }
    if (st === 'pending_moderation') {
      return {
        icon: '⏳',
        title: 'Профиль на проверке',
        hint:
          'Команда проверяет анкету. Обычно до одного рабочего дня. Разделы откроются автоматически — можно спокойно закрыть это окно.',
      };
    }
    if (st === 'deactivated') {
      return {
        icon: '⏸️',
        title: 'Аккаунт на паузе',
        hint: 'Профиль деактивирован. Если это ошибка — напишите в поддержку через /guide в боте.',
      };
    }
    return {
      icon: '🔗',
      title: 'Откройте из бота',
      hint: 'Запустите мини-приложение из чата бота тренера (кнопка в меню или под сообщением).',
    };
  }

  function gateCardHtml(access, compact) {
    var c = gateCopy(access);
    var st = (access && access.access_state) || '';
    var compactClass = compact ? ' bd-trainer-gate__card--compact' : '';
    var actionsHtml = '';
    if (st !== 'blocked_profile') {
      if (st === 'pending_moderation') {
        actionsHtml =
          '<div class="bd-trainer-gate__actions">' +
          '<button type="button" class="bd-btn bd-btn--primary" data-trainer-gate="profile">Профиль</button>' +
          '</div>';
      } else {
        actionsHtml =
          '<div class="bd-trainer-gate__actions">' +
          '<button type="button" class="bd-btn bd-btn--primary" data-trainer-gate="profile">Профиль</button>' +
          '<button type="button" class="bd-btn bd-btn--secondary" data-trainer-gate="hub">Обзор</button>' +
          '</div>';
      }
    }
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
      actionsHtml +
      '</div>'
    );
  }

  function wireGate(container, initData) {
    if (!container) return;
    container.querySelectorAll('[data-trainer-gate]').forEach(function (btn) {
      btn.onclick = function () {
        var a = btn.getAttribute('data-trainer-gate');
        if (a === 'profile') window.location.href = withInit('trainer-profile', initData);
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
    isActive: function (a) {
      if (!a) return false;
      /* Strict JSON boolean; tolerate string/number if a proxy mangles the payload. */
      if (a.is_active === true || a.is_active === 'true' || a.is_active === 1) return true;
      if (a.access_state === 'active') return true;
      if (a.schedule_unlocked === true || a.schedule_unlocked === 'true' || a.schedule_unlocked === 1) return true;
      if (a.access_state === 'booking_ready') return true;
      var ts = String(a.trainer_status || '')
        .trim()
        .toLowerCase();
      return ts === 'active';
    },
  };
})(window);
