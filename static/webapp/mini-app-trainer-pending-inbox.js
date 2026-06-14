/**
 * Trainer pending bookings inbox — shared sheet, batch confirm, badge sync, analytics (Wave C).
 * Used by trainer-home and schedule-editor.
 */
(function (global) {
  'use strict';

  var cfg = null;
  var wired = false;
  var batchInFlight = false;
  var lastInboxBadges = { schedule: 0, more: 0, clients: 0 };
  var shownItemIdsSession = {};

  function c(key) {
    return cfg && cfg[key];
  }

  function pluralRu(n, one, few, many) {
    if (c('pluralRu')) return c('pluralRu')(n, one, few, many);
    n = Math.abs(parseInt(String(n), 10) || 0);
    var mod10 = n % 10;
    var mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && !(mod100 >= 12 && mod100 <= 14)) return few;
    return many;
  }

  function escapeHtml(s) {
    if (c('escapeHtml')) return c('escapeHtml')(s);
    return String(s || '');
  }

  function toast(msg) {
    if (c('toast')) c('toast')(msg);
  }

  function postJson(path, body) {
    if (c('postJsonTrainer')) return c('postJsonTrainer')(path, body);
    return fetch(c('apiUrlWithQuery')(path), {
      method: 'POST',
      headers: c('headersJson')(),
      body: body != null ? JSON.stringify(body) : null,
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error((data && data.detail) || r.statusText || 'Ошибка');
        return data;
      });
    });
  }

  function fetchJson(path) {
    return fetch(c('apiUrlWithQuery')(path), { headers: c('headersJson')(), cache: 'no-store' }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error((data && data.detail) || r.statusText || 'Ошибка');
        return data;
      });
    });
  }

  function clientLabel(b) {
    var first = (b.client_first_name || '').trim();
    var last = (b.client_last_name || '').trim();
    var name = (first + ' ' + last).trim();
    if (name) return name;
    if (b.client_phone) return b.client_phone;
    return 'Клиент';
  }

  function dayHeaderLine(day) {
    if (c('dayHeaderLine')) return c('dayHeaderLine')(day);
    var dateStr = day.date || '';
    var lab = (day.day_label || '').trim();
    if (dateStr && lab) return dateStr + ' (' + lab + ')';
    return dateStr || lab || '';
  }

  function syncShellBadges(badges) {
    lastInboxBadges = badges || { schedule: 0, more: 0, clients: 0 };
    if (global.TrainerShell && typeof global.TrainerShell.setInboxBadges === 'function') {
      global.TrainerShell.setInboxBadges(lastInboxBadges);
    }
    if (c('chipEl')) {
      var n = parseInt(String(lastInboxBadges.schedule || 0), 10) || 0;
      if (n > 0) {
        c('chipEl').removeAttribute('hidden');
        var label = c('chipEl').querySelector('.se-pending-inbox-chip__label');
        if (label) {
          label.textContent =
            n +
            ' ' +
            pluralRu(n, 'запись ждёт подтверждения', 'записи ждут подтверждения', 'записей ждут подтверждения');
        }
      } else {
        c('chipEl').setAttribute('hidden', 'hidden');
      }
    }
  }

  function trackEvent(eventName, payload) {
    var body = {
      event: eventName,
      surface: c('surface') || 'hub',
    };
    if (payload && typeof payload === 'object') {
      Object.keys(payload).forEach(function (k) {
        body[k] = payload[k];
      });
    }
    postJson('/trainer/hub/inbox-event', body).catch(function () {});
  }

  function trackInboxItemsShown(items) {
    if (!items || !items.length) return;
    items.forEach(function (it) {
      var key = String(it.id || it.kind || '');
      if (!key || shownItemIdsSession[key]) return;
      shownItemIdsSession[key] = true;
      trackEvent('inbox_item_shown', {
        item_id: it.id || null,
        kind: it.kind || null,
        count: it.count != null ? it.count : null,
      });
    });
  }

  function defaultPendingRowsFromBookingsPayload(data) {
    var out = [];
    var days = (data && data.days) || (Array.isArray(data) ? data : []);
    (days || []).forEach(function (day) {
      (day.bookings || []).forEach(function (b) {
        if (b && String(b.status || '').toLowerCase() === 'pending' && b.id != null) {
          out.push({ id: b.id, booking: b, day: day });
        }
      });
    });
    return out;
  }

  function fetchPendingRows() {
    if (c('getPendingRows')) {
      var local = c('getPendingRows')() || [];
      if (local.length) return Promise.resolve(local);
      if (c('getPendingBookingIds')) {
        var ids = c('getPendingBookingIds')() || [];
        if (ids.length) {
          return Promise.resolve(
            ids.map(function (id) {
              return { id: id, booking: { id: id }, day: { date: '' } };
            })
          );
        }
      }
      if (c('getPendingCount') && (parseInt(String(c('getPendingCount')()), 10) || 0) > 0) {
        return fetchJson('/trainer/bookings?limit=32').then(defaultPendingRowsFromBookingsPayload);
      }
      return Promise.resolve([]);
    }
    return fetchJson('/trainer/bookings?limit=32').then(defaultPendingRowsFromBookingsPayload);
  }

  function refreshInboxCounts() {
    if (!c('getInitData') || !c('getInitData')()) return Promise.resolve(null);
    return fetchJson('/trainer/hub/inbox-count')
      .then(function (data) {
        if (data && data.badges) syncShellBadges(data.badges);
        return data;
      })
      .catch(function () {
        return null;
      });
  }

  function closeSheet() {
    var overlay = document.getElementById('hubPendingSheetOverlay');
    if (!overlay) return;
    overlay.setAttribute('hidden', 'hidden');
    overlay.setAttribute('aria-hidden', 'true');
    overlay.classList.remove('hub-pending-sheet-overlay--busy');
    if (global.TrainerShell && typeof global.TrainerShell.enableVerticalSwipes === 'function') {
      global.TrainerShell.enableVerticalSwipes();
    }
  }

  function openSheet() {
    var overlay = document.getElementById('hubPendingSheetOverlay');
    var listEl = document.getElementById('hubPendingSheetList');
    var leadEl = document.getElementById('hubPendingSheetLead');
    var confirmBtn = document.getElementById('hubPendingConfirmAll');
    if (!overlay || !listEl) return Promise.resolve();

    return fetchPendingRows().then(function (pendingRows) {
      if (!pendingRows.length) {
        toast('Нет записей, ожидающих подтверждения.');
        return refreshInboxCounts();
      }

      listEl.innerHTML = pendingRows
        .map(function (row) {
          var b = row.booking || {};
          var day = row.day || {};
          var time =
            ((b.start_time || '').slice(0, 5) || '') + '–' + ((b.end_time || '').slice(0, 5) || '');
          var meta = [dayHeaderLine(day), time, (b.services_str || '').trim()].filter(Boolean).join(' · ');
          return (
            '<li class="hub-pending-sheet__row">' +
            '<div class="hub-pending-sheet__row-title">' +
            escapeHtml(clientLabel(b)) +
            '</div>' +
            '<div class="hub-pending-sheet__row-meta">' +
            escapeHtml(meta) +
            '</div></li>'
          );
        })
        .join('');

      if (leadEl) {
        leadEl.textContent =
          pendingRows.length +
          ' ' +
          pluralRu(pendingRows.length, 'запись', 'записи', 'записей') +
          ' — клиенты не увидят занятие как согласованное, пока вы не подтвердите.';
      }
      if (confirmBtn) {
        confirmBtn.textContent =
          pendingRows.length > 1
            ? 'Подтвердить все (' + pendingRows.length + ')'
            : 'Подтвердить';
        confirmBtn.disabled = false;
      }

      overlay.removeAttribute('hidden');
      overlay.setAttribute('aria-hidden', 'false');
      if (global.TrainerShell && typeof global.TrainerShell.disableVerticalSwipes === 'function') {
        global.TrainerShell.disableVerticalSwipes();
      }
    });
  }

  function batchConfirmAll() {
    if (batchInFlight) return Promise.resolve();
    return fetchPendingRows().then(function (pendingRows) {
      if (!pendingRows.length) {
        closeSheet();
        return refreshInboxCounts();
      }
      batchInFlight = true;
      var overlay = document.getElementById('hubPendingSheetOverlay');
      var confirmBtn = document.getElementById('hubPendingConfirmAll');
      if (overlay) overlay.classList.add('hub-pending-sheet-overlay--busy');
      if (confirmBtn) confirmBtn.disabled = true;

      var bookingIds = pendingRows
        .map(function (row) {
          return parseInt(String(row.id), 10);
        })
        .filter(function (n) {
          return !isNaN(n) && n > 0;
        });

      function finish(ok, total) {
        closeSheet();
        if (ok > 0) {
          trackEvent('batch_confirm_success', {
            confirmed_count: ok,
            requested_count: total,
          });
        }
        if (total - ok === 0 && ok > 0) {
          toast(
            ok + ' ' + pluralRu(ok, 'запись подтверждена', 'записи подтверждены', 'записей подтверждено')
          );
        } else if (ok > 0) {
          toast('Подтверждено ' + ok + ' из ' + total + '. Попробуйте ещё раз для остальных.');
        } else {
          toast('Не удалось подтвердить записи. Попробуйте позже.');
        }
        if (c('onAfterConfirm')) c('onAfterConfirm')(ok, total);
        return refreshInboxCounts();
      }

      return postJson('/trainer/bookings/confirm-batch', { booking_ids: bookingIds })
        .then(function (res) {
          var ok = parseInt(String((res && res.confirmed_count) || 0), 10) || 0;
          return finish(ok, bookingIds.length);
        })
        .catch(function () {
          return Promise.allSettled(
            pendingRows.map(function (row) {
              return postJson('/trainer/bookings/' + encodeURIComponent(String(row.id)) + '/confirm', null);
            })
          ).then(function (results) {
            var ok = results.filter(function (r) {
              return r.status === 'fulfilled';
            }).length;
            return finish(ok, results.length);
          });
        })
        .finally(function () {
          batchInFlight = false;
          if (overlay) overlay.classList.remove('hub-pending-sheet-overlay--busy');
          if (confirmBtn) confirmBtn.disabled = false;
        });
    });
  }

  function wireSheet() {
    if (wired) return;
    wired = true;
    var overlay = document.getElementById('hubPendingSheetOverlay');
    var closeBtn = document.getElementById('hubPendingSheetClose');
    var confirmBtn = document.getElementById('hubPendingConfirmAll');
    if (closeBtn) closeBtn.onclick = closeSheet;
    if (confirmBtn) confirmBtn.onclick = function () {
      batchConfirmAll();
    };
    if (overlay) {
      overlay.addEventListener('click', function (ev) {
        if (ev.target === overlay) closeSheet();
      });
      var handle = overlay.querySelector('.hub-pending-sheet__handle');
      if (handle) handle.addEventListener('click', closeSheet);
    }
    if (c('chipEl')) {
      c('chipEl').addEventListener('click', function () {
        openSheet();
      });
    }
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') refreshInboxCounts();
    });
  }

  function init(options) {
    cfg = options || {};
    wireSheet();
  }

  global.TrainerPendingInbox = {
    init: init,
    openSheet: openSheet,
    closeSheet: closeSheet,
    batchConfirmAll: batchConfirmAll,
    refreshInboxCounts: refreshInboxCounts,
    syncShellBadges: syncShellBadges,
    trackEvent: trackEvent,
    trackInboxItemsShown: trackInboxItemsShown,
    getLastBadges: function () {
      return lastInboxBadges;
    },
  };
})(window);
