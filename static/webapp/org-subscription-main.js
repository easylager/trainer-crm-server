/**
 * Org Подписка (TASK-141 S2): read-only status of the school's platform subscription.
 * Activation itself is a platform-admin manual grant (TASK-113) — not self-serve here,
 * same reasoning as the backend route (no BYN/RSD gateway for a manually-billed pilot org).
 */
(function () {
  'use strict';

  function el(id) {
    return document.getElementById(id);
  }

  function show(node) {
    if (node) node.hidden = false;
  }

  function hide(node) {
    if (node) node.hidden = true;
  }

  function formatDate(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString('ru-RU');
    } catch (e) {
      return iso;
    }
  }

  var TIER_LABELS = {
    crm: 'CRM',
    online: 'CRM + онлайн-запись',
    analytics: 'CRM + онлайн-запись + аналитика',
  };

  function render(data) {
    hide(el('orgSubLoading'));
    hide(el('orgSubError'));
    show(el('orgSubRoot'));

    var dot = el('orgSubStatus').querySelector('.org-home-status__dot');
    dot.classList.remove('org-home-status__dot--ok', 'org-home-status__dot--wait');

    if (data.has_active_subscription && data.active) {
      dot.classList.add('org-home-status__dot--ok');
      el('orgSubStatusText').textContent = 'Подписка активна';
      el('orgSubTier').textContent = TIER_LABELS[data.active.tier] || data.active.tier || '';
      el('orgSubExpires').textContent = data.active.expires_at
        ? 'До ' + formatDate(data.active.expires_at)
        : '';
      show(el('orgSubCard'));
      hide(el('orgSubSupport'));
    } else {
      dot.classList.add('org-home-status__dot--wait');
      el('orgSubStatusText').textContent = 'Подписки пока нет';
      hide(el('orgSubCard'));
      if (data.support_url) {
        var support = el('orgSubSupport');
        support.innerHTML =
          'Чтобы подключить школу, напишите нам: <a href="' +
          data.support_url +
          '">' +
          data.support_url +
          '</a>';
        show(support);
      }
    }
  }

  function renderError(text) {
    hide(el('orgSubLoading'));
    hide(el('orgSubRoot'));
    show(el('orgSubError'));
    el('orgSubErrorText').textContent = text;
  }

  function load() {
    show(el('orgSubLoading'));
    hide(el('orgSubRoot'));
    hide(el('orgSubError'));

    var headers = window.MiniAppRuntime ? window.MiniAppRuntime.authHeaders() : {};
    fetch('/api/webapp/org/collective/subscription', { headers: headers })
      .then(function (resp) {
        if (resp.status === 404) {
          throw new Error('Вы пока не оператор ни одной школы.');
        }
        if (resp.status === 401) {
          throw new Error('Не удалось подтвердить вход. Откройте кабинет из бота.');
        }
        if (!resp.ok) {
          throw new Error('Не удалось загрузить раздел');
        }
        return resp.json();
      })
      .then(render)
      .catch(function (err) {
        renderError(err.message || 'Не удалось загрузить раздел');
      });
  }

  var backBtn = el('orgSubBack');
  if (backBtn) {
    backBtn.addEventListener('click', function () {
      window.location.href = 'org-home';
    });
  }

  var retryBtn = el('orgSubRetry');
  if (retryBtn) retryBtn.addEventListener('click', load);

  if (window.MiniAppRuntime && typeof window.MiniAppRuntime.ready === 'function') {
    window.MiniAppRuntime.ready();
  }
  load();
})();
