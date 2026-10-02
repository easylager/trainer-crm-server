/**
 * Org Клиенты (TASK-141 S7): агрегированный список клиентов школы.
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

  function authHeaders() {
    return window.MiniAppRuntime ? window.MiniAppRuntime.authHeaders() : {};
  }

  function escapeHtml(text) {
    var d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  var state = {
    clients: [],
  };

  function clientRow(client) {
    var name = [client.first_name, client.last_name].filter(Boolean).join(' ') || 'Без имени';
    var meta = [];
    if (client.phone) meta.push(client.phone);
    if (client.telegram_username) meta.push('@' + client.telegram_username);
    var count = client.bookings_count || 0;
    return (
      '<div class="org-clients-row">' +
      '<div>' +
      '<div class="org-clients-row__name">' + escapeHtml(name) + '</div>' +
      (meta.length ? '<div class="org-clients-row__meta">' + escapeHtml(meta.join(' · ')) + '</div>' : '') +
      '</div>' +
      '<div class="org-clients-row__count">' + count + ' записей</div>' +
      '</div>'
    );
  }

  function render() {
    hide(el('orgClientsLoading'));
    hide(el('orgClientsError'));
    show(el('orgClientsRoot'));

    var list = el('orgClientsList');
    var empty = el('orgClientsEmpty');
    var clients = state.clients;

    if (clients.length === 0) {
      hide(list);
      show(empty);
    } else {
      show(list);
      hide(empty);
      list.innerHTML = clients.map(clientRow).join('');
    }
  }

  function renderError(text) {
    hide(el('orgClientsLoading'));
    hide(el('orgClientsRoot'));
    show(el('orgClientsError'));
    el('orgClientsErrorText').textContent = text;
  }

  function load() {
    show(el('orgClientsLoading'));
    hide(el('orgClientsRoot'));
    hide(el('orgClientsError'));

    fetch('/api/webapp/org/clients', { headers: authHeaders() })
      .then(function (resp) {
        if (resp.status === 401) throw new Error('Не удалось подтвердить вход. Откройте кабинет из бота.');
        if (!resp.ok) throw new Error('Не удалось загрузить клиентов');
        return resp.json();
      })
      .then(function (data) {
        state.clients = data.clients || [];
        render();
      })
      .catch(function (err) {
        renderError(err.message || 'Не удалось загрузить клиентов');
      });
  }

  function filterClients() {
    var q = (el('orgClientsSearch').value || '').trim().toLowerCase();
    if (!q) {
      render();
      return;
    }
    var digits = q.replace(/\D/g, '');
    var filtered = state.clients.filter(function (c) {
      var name = ((c.first_name || '') + ' ' + (c.last_name || '')).toLowerCase();
      var phone = (c.phone || '').toLowerCase();
      if (name.indexOf(q) >= 0) return true;
      if (phone.indexOf(q) >= 0) return true;
      if (digits && (c.phone || '').replace(/\D/g, '').indexOf(digits) >= 0) return true;
      return false;
    });
    var list = el('orgClientsList');
    var empty = el('orgClientsEmpty');
    if (filtered.length === 0) {
      hide(list);
      show(empty);
      empty.textContent = 'Ничего не найдено';
    } else {
      show(list);
      hide(empty);
      list.innerHTML = filtered.map(clientRow).join('');
    }
  }

  var backBtn = el('orgClientsBack');
  if (backBtn) {
    backBtn.addEventListener('click', function () {
      window.location.href = 'org-home';
    });
  }

  var retryBtn = el('orgClientsRetry');
  if (retryBtn) retryBtn.addEventListener('click', load);

  var searchInput = el('orgClientsSearch');
  if (searchInput) searchInput.addEventListener('input', filterClients);

  if (window.MiniAppRuntime && typeof window.MiniAppRuntime.ready === 'function') {
    window.MiniAppRuntime.ready();
  }

  load();
})();
