/**
 * Shared booking-context picker for hub, clients, and schedule-editor (Wave C).
 * Remembers last context per client in sessionStorage (O4.2).
 */
(function (global) {
  'use strict';

  var STORAGE_PREFIX = 'tcb_book_ctx_';

  function escapeHtmlFallback(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/"/g, '&quot;');
  }

  function normalizePayload(payload) {
    if (!payload || !payload.contexts || !payload.contexts.length) {
      return {
        contexts: [
          {
            kind: 'personal_slot',
            context_id: 'personal',
            label: 'Личное расписание',
            collective_slug: null,
          },
        ],
        needs_context_picker: false,
        delegate: null,
        default_context_id: 'personal',
        studio_access_mode: null,
      };
    }
    return payload;
  }

  function needsContextPicker(payload) {
    var p = normalizePayload(payload);
    return !!p.needs_context_picker && p.contexts.length > 1;
  }

  function storageKey(clientId) {
    return STORAGE_PREFIX + String(clientId || 'global');
  }

  function rememberContextForClient(clientId, contextId) {
    if (!contextId) return;
    try {
      sessionStorage.setItem(storageKey(clientId), String(contextId));
    } catch (e) {
      /* sessionStorage may be blocked in embedded webviews */
    }
  }

  function getRememberedContextId(clientId) {
    try {
      return sessionStorage.getItem(storageKey(clientId)) || null;
    } catch (e) {
      return null;
    }
  }

  /** Returns matched context or null when user must pick manually. */
  function resolveInitialContext(payload, clientId) {
    var p = normalizePayload(payload);
    if (!needsContextPicker(p)) {
      return p.contexts[0] || null;
    }
    var remembered = getRememberedContextId(clientId);
    if (remembered) {
      for (var i = 0; i < p.contexts.length; i++) {
        if (p.contexts[i].context_id === remembered) {
          return p.contexts[i];
        }
      }
    }
    if (p.default_context_id) {
      for (var j = 0; j < p.contexts.length; j++) {
        if (p.contexts[j].context_id === p.default_context_id) {
          return p.contexts[j];
        }
      }
    }
    return null;
  }

  function fetchContexts(fetchFn) {
    return fetchFn('/trainer/booking-contexts')
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .catch(function () {
        return null;
      })
      .then(normalizePayload);
  }

  /**
   * @param {HTMLElement} container
   * @param {object} payload
   * @param {{ escapeHtml?: function, attrPrefix?: string, clientId?: number, onSelect?: function }} options
   */
  function renderPicker(container, payload, options) {
    if (!container) return;
    options = options || {};
    var escapeHtml = options.escapeHtml || escapeHtmlFallback;
    var attrPrefix = options.attrPrefix || 'data-book';
    var slugAttr = options.slugAttr || attrPrefix + '-slug';
    var contexts = (payload && payload.contexts) || [];
    container.innerHTML = contexts
      .map(function (ctx) {
        return (
          '<button type="button" class="btn-book-option" ' +
          attrPrefix +
          '-context="' +
          escapeHtml(ctx.context_id) +
          '" ' +
          attrPrefix +
          '-kind="' +
          escapeHtml(ctx.kind) +
          '" ' +
          slugAttr +
          '="' +
          escapeHtml(ctx.collective_slug || '') +
          '">' +
          '<span class="btn-book-option-body"><span class="btn-book-option-text">' +
          escapeHtml(ctx.label) +
          '</span></span>' +
          '<span class="btn-book-option-arrow" aria-hidden="true">›</span>' +
          '</button>'
        );
      })
      .join('');
    var selector = '[' + attrPrefix + '-kind]';
    container.querySelectorAll(selector).forEach(function (btn) {
      btn.onclick = function () {
        var ctx = {
          kind: btn.getAttribute(attrPrefix + '-kind') || 'personal_slot',
          context_id: btn.getAttribute(attrPrefix + '-context') || 'personal',
          collective_slug: btn.getAttribute(slugAttr) || null,
          label: (btn.textContent || '').trim(),
        };
        if (options.clientId != null) {
          rememberContextForClient(options.clientId, ctx.context_id);
        }
        if (options.onSelect) options.onSelect(ctx, btn);
      };
    });
  }

  function applyContext(ctx) {
    return {
      kind: (ctx && ctx.kind) || 'personal_slot',
      context_id: (ctx && ctx.context_id) || 'personal',
      collective_slug: (ctx && ctx.collective_slug) || null,
      label: (ctx && ctx.label) || '',
    };
  }

  /** Staff center booking: API returns assigned_coaches; legacy payloads used coaches. */
  function centerCoachesForStaffBooking(session, actorTrainerId) {
    var coaches = ((session && (session.assigned_coaches || session.coaches)) || []).slice();
    var actorId = actorTrainerId != null ? parseInt(String(actorTrainerId), 10) : NaN;
    if (isNaN(actorId)) return coaches;
    for (var i = 0; i < coaches.length; i++) {
      if (parseInt(String(coaches[i].trainer_id), 10) === actorId) {
        coaches[i] = {
          trainer_id: coaches[i].trainer_id,
          display_name: 'Я',
        };
        return coaches;
      }
    }
    coaches.unshift({ trainer_id: actorId, display_name: 'Я' });
    return coaches;
  }

  global.TrainerBookingContext = {
    normalizePayload: normalizePayload,
    needsContextPicker: needsContextPicker,
    rememberContextForClient: rememberContextForClient,
    getRememberedContextId: getRememberedContextId,
    resolveInitialContext: resolveInitialContext,
    fetchContexts: fetchContexts,
    renderPicker: renderPicker,
    applyContext: applyContext,
    centerCoachesForStaffBooking: centerCoachesForStaffBooking,
  };
})(window);
