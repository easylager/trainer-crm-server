/**
 * «Похоже, Ольга — это Анна из вашего списка» (TASK-314).
 *
 * Номер, который человек набрал сам, ничего не привязывает: набрать можно любой. Решает
 * тренер — он своих учеников знает: один человек, родитель и ребёнок или разные люди.
 * Лист сам берёт открытые пары, после ответа показывает следующую и закрывается, когда
 * их не осталось.
 */
(function (global) {
  'use strict';

  var opts = null;
  var overlay = null;
  var matches = [];
  var busy = false;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function firstName(full) {
    return String(full || '').trim().split(/\s+/)[0] || '';
  }

  function tgApp() {
    return global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null;
  }

  var backWasVisible = false;
  function onTgBack() { close(); }

  function holdTelegram(on) {
    var tg = tgApp();
    if (!tg || !tg.BackButton) return;
    try {
      if (on) {
        backWasVisible = !!tg.BackButton.isVisible;
        tg.BackButton.onClick(onTgBack);
        tg.BackButton.show();
      } else {
        tg.BackButton.offClick(onTgBack);
        if (!backWasVisible) tg.BackButton.hide();
      }
    } catch (e) { /* старые клиенты */ }
  }

  function ensureOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'tfs-overlay';
    overlay.setAttribute('hidden', '');
    overlay.innerHTML =
      '<div class="tfs-sheet tcm-sheet" role="dialog" aria-modal="true" aria-labelledby="tcmTitle">' +
      '<div class="tfs-sheet__handle" aria-hidden="true"></div>' +
      '<button type="button" class="tfs-sheet__close" data-tcm="close" aria-label="Закрыть">' +
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
      '</button>' +
      '<div id="tcmBody"></div>' +
      '</div>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', function (ev) {
      if (ev.target === overlay) { close(); return; }
      var btn = ev.target.closest && ev.target.closest('[data-tcm]');
      if (!btn) return;
      var act = btn.getAttribute('data-tcm');
      if (act === 'close') close();
      else answer(act, btn);
    });
    return overlay;
  }

  function render() {
    var m = matches[0];
    var body = overlay.querySelector('#tcmBody');
    var who = m.client_name || 'Ученик';
    var other = m.other_name || 'ученик';
    var whoFirst = firstName(who) || who;
    var otherFirst = firstName(other) || other;
    var more = matches.length > 1
      ? '<p class="tcm-more">Ещё ' + (matches.length - 1) + ' после этого</p>'
      : '';
    body.innerHTML =
      '<h2 class="tfs-sheet__title" id="tcmTitle">Это один человек?</h2>' +
      '<dl class="tcm-pair">' +
      '<div class="tcm-pair__row"><dt>Записывается через приложение</dt><dd>' + esc(who) + '</dd></div>' +
      '<div class="tcm-pair__row"><dt>В вашем списке</dt><dd>' + esc(other) + '</dd></div>' +
      (m.phone ? '<div class="tcm-pair__row"><dt>Телефон у обоих</dt><dd class="tcm-mono">' + esc(m.phone) + '</dd></div>' : '') +
      '</dl>' +
      '<div class="tcm-options">' +
      '<button type="button" class="tcm-option" data-tcm="same">' +
      '<span class="tcm-option__title">Один человек</span>' +
      '<span class="tcm-option__hint">Карточки объединятся: история, абонементы и напоминания — в одной</span>' +
      '</button>' +
      '<button type="button" class="tcm-option" data-tcm="parent">' +
      '<span class="tcm-option__title">Родитель и ребёнок</span>' +
      '<span class="tcm-option__hint">' + esc(whoFirst) + ' — родитель, ' + esc(otherFirst) + ' — ребёнок. ' +
      'Профиль ребёнка появится в приложении родителя, напоминания о занятиях придут туда</span>' +
      '</button>' +
      '</div>' +
      '<button type="button" class="tcm-quiet" data-tcm="different">Разные люди</button>' +
      more +
      '<p class="tfs-error" id="tcmError" hidden></p>';
  }

  var DONE = {
    same: 'Карточки объединены',
    parent: 'Профиль добавлен родителю',
    different: 'Больше не спросим',
  };

  function answer(decision, btn) {
    if (busy || !matches.length) return;
    var m = matches[0];
    busy = true;
    if (btn) btn.setAttribute('aria-busy', 'true');
    opts
      .post('/trainer/client-matches', {
        client_id: m.client_id,
        other_client_id: m.other_client_id,
        decision: decision,
      })
      .then(function () {
        busy = false;
        matches.shift();
        if (typeof opts.notify === 'function') opts.notify(DONE[decision] || 'Готово');
        if (matches.length) render();
        else close();
      })
      .catch(function (err) {
        busy = false;
        if (btn) btn.removeAttribute('aria-busy');
        var el = overlay.querySelector('#tcmError');
        if (el) {
          el.textContent = (err && err.message) || 'Не получилось. Попробуйте ещё раз.';
          el.removeAttribute('hidden');
        }
      });
  }

  function open(options) {
    opts = options;
    return opts.get('/trainer/client-matches').then(function (data) {
      matches = (data && data.matches) || [];
      if (!matches.length) {
        if (typeof opts.onChanged === 'function') opts.onChanged(0);
        return;
      }
      ensureOverlay();
      render();
      overlay.removeAttribute('hidden');
      document.body.classList.add('tfs-sheet-open');
      holdTelegram(true);
    });
  }

  function close() {
    if (!overlay || overlay.hasAttribute('hidden')) return;
    overlay.setAttribute('hidden', '');
    document.body.classList.remove('tfs-sheet-open');
    holdTelegram(false);
    if (opts && typeof opts.onChanged === 'function') opts.onChanged(matches.length);
  }

  global.TrainerClientMatch = { open: open, close: close };
})(typeof window !== 'undefined' ? window : globalThis);
