/**
 * Org Команда (TASK-141 S4): ростер тренеров школы + приглашение.
 * DEC-002: только просмотр состава и приглашение в этом заходе — промоут/ремув нет.
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

  function memberRow(member) {
    var name = member.display_name || (member.telegram_username ? '@' + member.telegram_username : 'Тренер #' + member.trainer_id);
    var statusLabel = member.status === 'active' ? 'в школе' : 'ждёт ответа';
    return (
      '<div class="org-subscription-card org-team-row">' +
      '<p class="org-subscription-card__title">' + escapeHtml(name) + '</p>' +
      '<p class="org-subscription-card__meta">' + statusLabel + '</p>' +
      '</div>'
    );
  }

  function escapeHtml(text) {
    var d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  function render(data) {
    hide(el('orgTeamLoading'));
    hide(el('orgTeamError'));
    show(el('orgTeamRoot'));

    el('orgTeamStatusText').textContent = data.active_count + ' в школе';

    var members = data.members || [];
    if (members.length === 0) {
      hide(el('orgTeamList'));
      show(el('orgTeamEmpty'));
    } else {
      show(el('orgTeamList'));
      hide(el('orgTeamEmpty'));
      el('orgTeamList').innerHTML = members.map(memberRow).join('');
    }

    var pendingEl = el('orgTeamPending');
    if (data.pending_invites > 0) {
      pendingEl.textContent = 'Ожидают перехода по ссылке: ' + data.pending_invites;
      show(pendingEl);
    } else {
      hide(pendingEl);
    }

    var inviteBtn = el('orgTeamInvite');
    if (data.role !== 'owner') {
      inviteBtn.hidden = true;
    } else {
      inviteBtn.hidden = false;
    }
  }

  function renderError(text) {
    hide(el('orgTeamLoading'));
    hide(el('orgTeamRoot'));
    show(el('orgTeamError'));
    el('orgTeamErrorText').textContent = text;
  }

  function load() {
    show(el('orgTeamLoading'));
    hide(el('orgTeamRoot'));
    hide(el('orgTeamError'));

    fetch('/api/webapp/org/team', { headers: authHeaders() })
      .then(function (resp) {
        if (resp.status === 404) throw new Error('Вы пока не оператор ни одной школы.');
        if (resp.status === 401) throw new Error('Не удалось подтвердить вход. Откройте кабинет из бота.');
        if (!resp.ok) throw new Error('Не удалось загрузить раздел');
        return resp.json();
      })
      .then(render)
      .catch(function (err) {
        renderError(err.message || 'Не удалось загрузить раздел');
      });
  }

  function copyLink(link, done) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(link).then(done, function () { legacyCopy(link, done); });
        return;
      }
    } catch (e) { /* ниже */ }
    legacyCopy(link, done);
  }

  function legacyCopy(link, done) {
    try {
      var ta = document.createElement('textarea');
      ta.value = link;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      done();
    } catch (e) {
      var note = el('orgTeamInviteNote');
      note.textContent = 'Ссылка: ' + link;
      show(note);
    }
  }

  function invite() {
    var btn = el('orgTeamInvite');
    var note = el('orgTeamInviteNote');
    hide(note);
    btn.disabled = true;

    fetch('/api/webapp/org/team/invite', {
      method: 'POST',
      headers: authHeaders(),
    })
      .then(function (resp) {
        if (resp.status === 409) throw new Error('Достигнут лимит мест в школе.');
        if (resp.status === 403) throw new Error('Приглашать может только владелец школы.');
        if (!resp.ok) throw new Error('Не удалось создать приглашение');
        return resp.json();
      })
      .then(function (data) {
        var link = data.invite_link;
        if (!link) {
          note.textContent = 'Приглашение создано, но ссылка недоступна.';
          show(note);
          return;
        }
        var opened = false;
        if (typeof window.openTelegramShareUrlFromMiniApp === 'function') {
          opened = !!window.openTelegramShareUrlFromMiniApp({
            shareUrl: link,
            shareBody: '',
            fullMessage: 'Присоединяйтесь к школе как тренер: ' + link,
          });
        }
        if (opened) {
          note.textContent = 'Отправьте ссылку тренеру в Telegram.';
          show(note);
        } else {
          copyLink(link, function () {
            note.textContent = 'Ссылка скопирована — отправьте её тренеру.';
            show(note);
          });
        }
        load();
      })
      .catch(function (err) {
        note.textContent = err.message || 'Не удалось создать приглашение';
        show(note);
      })
      .finally(function () {
        btn.disabled = false;
      });
  }

  var backBtn = el('orgTeamBack');
  if (backBtn) {
    backBtn.addEventListener('click', function () {
      window.location.href = 'org-home';
    });
  }

  var retryBtn = el('orgTeamRetry');
  if (retryBtn) retryBtn.addEventListener('click', load);

  var inviteBtn = el('orgTeamInvite');
  if (inviteBtn) inviteBtn.addEventListener('click', invite);

  if (window.MiniAppRuntime && typeof window.MiniAppRuntime.ready === 'function') {
    window.MiniAppRuntime.ready();
  }
  load();
})();
