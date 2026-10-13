/**
 * TASK-253: «Позвать» с плиток каталога и «Поделиться подборкой» — тот же GlideShareSheet, что ice-tab.
 */
(function () {
  'use strict';

  var root = document.documentElement;
  root.classList.add('js');

  function fetchJson(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (!r.ok) return null;
      return r.json();
    });
  }

  function catalogTodayIso() {
    var ACM = window.ArenaCardModel;
    if (ACM && typeof ACM.ymd === 'function') return ACM.ymd(new Date());
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function catalogAddDaysIso(iso, n) {
    var ACM = window.ArenaCardModel;
    if (ACM && typeof ACM.parseLocalDate === 'function' && typeof ACM.ymd === 'function') {
      var d = ACM.parseLocalDate(iso);
      d.setDate(d.getDate() + n);
      return ACM.ymd(d);
    }
    return iso;
  }

  function openCatalogInvite(ref, sessionId, label, placeName) {
    if (!window.GlideShareSheet || !ref) return;
    var picked =
      sessionId != null && String(sessionId).trim() !== '' ? String(sessionId).trim() : null;
    var fallback = function () {
      window.GlideShareSheet.open({
        ref: ref,
        sessionId: picked,
        slots: picked ? [{ id: picked, label: label || '' }] : [],
        invite: true,
        context: 'ice_list',
        placeName: placeName || '',
      });
    };
    var ACM = window.ArenaCardModel;
    if (!ACM || typeof ACM.shareSlots !== 'function') {
      fallback();
      return;
    }
    var today = catalogTodayIso();
    var to = catalogAddDaysIso(today, 13);
    fetchJson(
      '/api/public/arenas/' +
        encodeURIComponent(String(ref)) +
        '/sessions?from=' +
        encodeURIComponent(today) +
        '&to=' +
        encodeURIComponent(to)
    )
      .then(function (data) {
        var days =
          ACM.combineSessionDayLists && typeof ACM.combineSessionDayLists === 'function'
            ? ACM.combineSessionDayLists((data && data.days) || [], (data && data.ohm_days) || [])
            : (data && data.days) || [];
        var slots = ACM.shareSlots(days, today, 0);
        var slotSections = ACM.shareSlotsGrouped ? ACM.shareSlotsGrouped(days, today) : null;
        var sid = picked;
        if (sid && !slots.some(function (s) {
          return String(s.id) === String(sid);
        })) {
          slots.unshift({ id: sid, label: label || '' });
        }
        if (!sid && slots.length) sid = String(slots[0].id);
        window.GlideShareSheet.open({
          ref: ref,
          sessionId: sid,
          slots: slots,
          slotSections: slotSections,
          invite: true,
          context: 'ice_list',
          placeName: placeName || '',
        });
      })
      .catch(fallback);
  }

  function openSelectionShare(endpoint) {
    if (!window.GlideShareSheet || !endpoint) return;
    window.GlideShareSheet.open({ endpoint: endpoint, context: 'ice_list' });
  }

  document.addEventListener('click', function (ev) {
    var invite = ev.target.closest('[data-invite-arena]');
    if (invite) {
      ev.preventDefault();
      openCatalogInvite(
        invite.getAttribute('data-invite-arena'),
        invite.getAttribute('data-invite-session'),
        invite.getAttribute('data-invite-label'),
        invite.getAttribute('data-invite-place')
      );
      return;
    }
    var shareBtn = ev.target.closest('[data-catalog-selection-share]');
    if (shareBtn) {
      ev.preventDefault();
      openSelectionShare(shareBtn.getAttribute('data-catalog-selection-share') || '');
    }
  });

})();
