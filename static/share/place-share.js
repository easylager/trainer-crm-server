/**
 * TASK-252: выбор сеанса на /p/… и GlideShareSheet как в Mini App.
 */
(function () {
  'use strict';

  var boot = window.__PLACE_SHARE__;
  if (!boot || !boot.ref) return;

  var root = document.documentElement;
  root.classList.add('js');

  var M = window.ArenaCardModel;
  var PD = window.PublicDisplayModel;
  var MT = window.MinskTime;
  if (!M || !PD || !MT || !window.GlideShareSheet) return;

  var pickId = boot.sessionId != null ? String(boot.sessionId) : null;
  var invite = !!boot.invite;

  function todayIso() {
    return boot.today || MT.todayIsoInTz(boot.timezone || 'Europe/Minsk');
  }

  function combinedDays() {
    return M.combineSessionDayLists(boot.days || [], boot.ohmDays || []);
  }

  function scheduleSlots() {
    return M.shareSlots(combinedDays(), todayIso(), 0);
  }

  function sessionExists(id) {
    if (id == null) return false;
    var sid = String(id);
    return scheduleSlots().some(function (s) {
      return String(s.id) === sid;
    });
  }

  function resolvedSessionId() {
    if (pickId && sessionExists(pickId)) return pickId;
    var slots = scheduleSlots();
    return slots.length ? String(slots[0].id) : null;
  }

  function inviteLabel(sessionId) {
    if (!sessionId) return 'Позвать с собой';
    var when = M.shareSlotInviteLabel(combinedDays(), todayIso(), sessionId, boot.focusDay || '');
    if (when && PD.formatClock) when = PD.formatClock(when);
    return when ? 'Позвать на ' + when : 'Позвать с собой';
  }

  function sharePayload() {
    var days = combinedDays();
    var today = todayIso();
    return {
      slots: M.shareSlots(days, today, 0),
      slotSections: M.shareSlotsGrouped(days, today),
    };
  }

  function syncUrl(sessionId) {
    if (!sessionId || !boot.basePath) return;
    try {
      var u = new URL(boot.basePath, location.origin);
      u.searchParams.set('s', String(sessionId));
      if (invite) u.searchParams.set('i', '1');
      else u.searchParams.delete('i');
      history.replaceState(null, '', u.pathname + u.search + u.hash);
    } catch (e) {
      /* */
    }
  }

  function applyPick(sessionId, opts) {
    var sid = sessionId != null ? String(sessionId) : null;
    if (!sid || !sessionExists(sid)) return;
    pickId = sid;
    document.querySelectorAll('.b-ticket[data-session-id]').forEach(function (el) {
      var on = el.getAttribute('data-session-id') === sid;
      el.classList.toggle('b-ticket--picked', on);
      var fb = el.nextElementSibling;
      if (fb && fb.classList.contains('place-share-fallback')) {
        fb.hidden = !on;
      }
    });
    var btn = document.getElementById('placeShareBtn');
    if (btn) btn.textContent = inviteLabel(sid);
    if (!opts || !opts.skipUrl) syncUrl(sid);
    revealPickedTicket();
  }

  function revealPickedTicket() {
    var el = document.querySelector('.b-ticket--picked');
    if (!el || typeof el.scrollIntoView !== 'function') return;
    var run = function () {
      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    };
    run();
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(function () {
        requestAnimationFrame(run);
      });
    }
  }

  function openShare() {
    var sid = resolvedSessionId();
    if (!sid) return;
    var payload = sharePayload();
    var loadSlots =
      payload.slots.length <= 1
        ? function () {
            var today = todayIso();
            var to = MT.addDaysIso(today, 13);
            return fetch(
              '/api/public/arenas/' +
                encodeURIComponent(String(boot.ref)) +
                '/sessions?from=' +
                encodeURIComponent(today) +
                '&to=' +
                encodeURIComponent(to),
              { credentials: 'same-origin' }
            )
              .then(function (r) {
                return r.ok ? r.json() : null;
              })
              .then(function (data) {
                if (!data) return payload;
                var days = M.combineSessionDayLists(data.days || [], data.ohm_days || []);
                return {
                  slots: M.shareSlots(days, today, 0),
                  slotSections: M.shareSlotsGrouped(days, today),
                };
              })
              .catch(function () {
                return payload;
              });
          }
        : null;
    window.GlideShareSheet.open({
      ref: boot.ref,
      slots: payload.slots,
      slotSections: payload.slotSections,
      sessionId: sid,
      sessionMissing: boot.sessionMissing && !sessionExists(sid),
      invite: invite,
      venueType: 'ice',
      context: 'arena_card',
      placeName: boot.placeName || '',
      loadSlots: loadSlots,
    });
  }

  document.querySelectorAll('.b-ticket[data-session-id]').forEach(function (el) {
    el.addEventListener('click', function (event) {
      event.preventDefault();
      applyPick(el.getAttribute('data-session-id'));
    });
  });

  window.addEventListener('load', function () {
    if (document.querySelector('.b-ticket--picked')) revealPickedTicket();
  });

  var btn = document.getElementById('placeShareBtn');
  if (btn) {
    btn.addEventListener('click', function () {
      openShare();
    });
  }

  document.querySelectorAll('.place-share-fallback [data-copy]').forEach(function (copyBtn) {
    copyBtn.addEventListener('click', function () {
      var text = copyBtn.getAttribute('data-copy') || '';
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(function () {});
      }
    });
  });

  var initial = resolvedSessionId();
  if (initial) applyPick(initial, { skipUrl: !!boot.sessionId });
  else if (btn) btn.disabled = true;
})();
