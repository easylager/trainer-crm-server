/**
 * Trainer ↔ client messaging via bots when native Telegram DM is unavailable (no @username, WebView blocks tg://user?id=).
 * Opens a small modal and POSTs to /api/webapp/trainer/clients/{id}/relay-messages.
 */
(function (global) {
  'use strict';

  var MODAL_ID = 'trainerClientRelayOverlay';
  var TEXT_ID = 'trainerClientRelayText';
  var ERR_ID = 'trainerClientRelayErr';
  var SEND_ID = 'trainerClientRelaySend';
  var SUBTITLE_ID = 'trainerClientRelaySubtitle';
  var COPY_PHONE_ID = 'trainerClientRelayCopyPhone';
  var NO_PHONE_ID = 'trainerClientRelayNoPhone';

  /** E.164-style BY/RU phone for clipboard. */
  function normalizeClientPhoneForCopy(raw) {
    var s = String(raw == null ? '' : raw).trim();
    if (!s || s === '—' || s === '-') return '';
    if (global.CrmPhoneField && global.CrmPhoneField.parseE164ToCountryAndNational) {
      var parsed = CrmPhoneField.parseE164ToCountryAndNational(s);
      var e164 = CrmPhoneField.nationalToE164(parsed.national, parsed.country);
      if (e164) return e164;
    }
    var d = s.replace(/\D/g, '');
    if (d.length === 12 && d.indexOf('375') === 0) return '+' + d;
    if (d.length === 11 && d.indexOf('80') === 0) return '+375' + d.slice(2);
    if (d.length === 9) return '+375' + d;
    if (d.length === 11 && d.charAt(0) === '8') return '+7' + d.slice(1);
    if (d.length === 11 && d.charAt(0) === '7') return '+' + d;
    if (d.length === 10 && d.charAt(0) === '9') return '+7' + d;
    if (s.charAt(0) === '+' && d.length >= 10) return '+' + d.slice(0, 15);
    return s.replace(/\s+/g, ' ').trim();
  }

  /** Read init_data like trainer-home-main (Telegram fills initData async; URL fallback for in-app navigation). */
  function getInitData() {
    var t = global.Telegram && global.Telegram.WebApp;
    var raw = (t && t.initData) || '';
    if (!raw) {
      try {
        var qs = new URLSearchParams(global.location.search || '');
        raw = qs.get('init_data') || qs.get('initData') || '';
      } catch (e) {
        raw = '';
      }
    }
    return raw ? String(raw) : '';
  }

  function withInit(url) {
    var id = getInitData();
    if (!id) return url;
    var sep = url.indexOf('?') === -1 ? '?' : '&';
    return url + sep + 'init_data=' + encodeURIComponent(id);
  }

  /** @type { { clientId: number, clientPhone: string, onSent?: function() } | null } */
  var pending = null;

  function closeModal() {
    var root = global.document && global.document.getElementById(MODAL_ID);
    if (!root) return;
    root.setAttribute('aria-hidden', 'true');
    pending = null;
  }

  var STYLE_ID = 'trainerClientRelayUiCss';

  /** Minimal sheet styles — schedule-editor hub does not load trainer-clients.css. */
  function ensureRelayBaseStyles() {
    if (!global.document.head || global.document.getElementById(STYLE_ID)) return;
    var s = global.document.createElement('style');
    s.id = STYLE_ID;
    s.textContent =
      '#' +
      MODAL_ID +
      '.trainer-relay-overlay{position:fixed;inset:0;z-index:10050;display:flex;align-items:flex-end;justify-content:center;' +
      'background:rgba(15,15,20,.48);padding:12px;padding-bottom:max(12px,env(safe-area-inset-bottom));box-sizing:border-box;' +
      '-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}' +
      '@media(min-width:520px){#' +
      MODAL_ID +
      '.trainer-relay-overlay{align-items:center}}' +
      '#' +
      MODAL_ID +
      '.trainer-relay-overlay[aria-hidden="true"]{display:none !important}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-sheet{width:100%;max-width:440px;border-radius:16px 16px 0 0;background:var(--tg-theme-bg-color,#F4F2EC);' +
      'color:var(--tg-theme-text-color,#1a1a1a);padding:18px 16px 16px;margin:0;box-sizing:border-box;' +
      'box-shadow:0 -12px 40px rgba(0,0,0,.22)}' +
      '@media(min-width:520px){#' +
      MODAL_ID +
      ' .trainer-relay-sheet{border-radius:16px;margin:0 auto}}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-title{font-size:1.15rem;font-weight:700;margin:0;line-height:1.25;letter-spacing:-.02em}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-sub{margin-top:10px;margin-bottom:0;font-size:.95rem;line-height:1.4}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-callout{margin:12px 0 10px;padding:10px 12px;border-radius:10px;font-size:13px;line-height:1.5;' +
      'background:color-mix(in srgb,var(--tg-theme-secondary-bg-color,#f0f0f0) 88%,transparent);' +
      'border-left:3px solid var(--tg-theme-button-color,#34C6C4);color:var(--tg-theme-text-color,#1a1a1a)}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-callout strong{font-weight:700}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-hint{margin:8px 0 10px;font-size:13px;line-height:1.45;color:var(--tg-theme-hint-color,#666)}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-err{margin-top:10px;color:#c62828;font-size:13px}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-field{margin-top:12px;display:flex;flex-direction:column;gap:6px}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-field label{font-size:13px;font-weight:600}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-ta{width:100%;box-sizing:border-box;border-radius:10px;' +
      'border:1px solid color-mix(in srgb,var(--tg-theme-hint-color,#888) 40%,transparent);' +
      'background:var(--tg-theme-secondary-bg-color,#FFFFFF);color:inherit;padding:11px 12px;' +
      'font:inherit;font-size:16px;line-height:1.45;resize:vertical;min-height:120px}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-copy-wrap{margin-top:12px}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-btn-copy{width:100%;border-radius:11px;padding:11px 14px;font-weight:600;font-size:14px;' +
      'font-family:inherit;touch-action:manipulation;cursor:pointer;' +
      'border:1px solid color-mix(in srgb,var(--tg-theme-hint-color,#888) 45%,transparent);' +
      'background:transparent;color:var(--tg-theme-text-color)}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-btn-copy[hidden]{display:none !important}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-no-phone{margin-top:10px;font-size:12px;line-height:1.45;color:var(--tg-theme-hint-color,#666)}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-no-phone[hidden]{display:none !important}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-actions{display:flex;gap:10px;margin-top:12px}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-actions button{flex:1;border-radius:11px;padding:12px 14px;font-weight:600;' +
      'border:none;cursor:pointer;font-size:15px;font-family:inherit;touch-action:manipulation}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-btn-secondary{background:color-mix(in srgb,var(--tg-theme-secondary-bg-color) 82%,transparent);' +
      'color:var(--tg-theme-text-color)}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-btn-primary{background:var(--tg-theme-button-color,#34C6C4);' +
      'color:var(--tg-theme-button-text-color,#1a1a1a)}' +
      '#' +
      MODAL_ID +
      ' .trainer-relay-actions button:disabled{opacity:.55;cursor:default}';
    global.document.head.appendChild(s);
  }

  function ensureModal() {
    if (global.document.getElementById(MODAL_ID)) return;

    ensureRelayBaseStyles();
    global.document.body.insertAdjacentHTML(
      'beforeend',
      '<div id="' +
        MODAL_ID +
        '" class="trainer-relay-overlay" role="presentation" aria-hidden="true">' +
        '<div class="trainer-relay-sheet" role="dialog" aria-modal="true" aria-labelledby="trainerClientRelayTitle">' +
        '<h3 id="trainerClientRelayTitle" class="trainer-relay-title">Сообщение клиенту</h3>' +
        '<p id="' +
        SUBTITLE_ID +
        '" class="trainer-relay-sub" hidden></p>' +
        '<div class="trainer-relay-callout" role="note">' +
        '<p class="trainer-relay-callout__text">' +
        'Личные сообщения в Telegram этому клиенту недоступны — текст ниже доставляется через его бота. ' +
        'Телефон для звонка — нажмите на номер в карточке или кнопку «Скопировать телефон».' +
        '</p></div>' +
        '<p class="trainer-relay-hint">' +
        'Ответ клиента придёт в ваш тренерский бот.' +
        '</p>' +
        '<div class="trainer-relay-field">' +
        '<label for="' +
        TEXT_ID +
        '">Текст сообщения</label>' +
        '<textarea id="' +
        TEXT_ID +
        '" class="trainer-relay-ta" rows="5" maxlength="4000" ' +
        'placeholder="Например: перенесём на среду в 18:00?"></textarea>' +
        '</div>' +
        '<p id="' +
        ERR_ID +
        '" class="trainer-relay-err" hidden role="alert"></p>' +
        '<div class="trainer-relay-actions">' +
        '<button type="button" class="trainer-relay-btn-secondary" id="trainerClientRelayCancel">Отмена</button>' +
        '<button type="button" class="trainer-relay-btn-primary" id="' +
        SEND_ID +
        '">Отправить</button>' +
        '</div>' +
        '<div class="trainer-relay-copy-wrap">' +
        '<button type="button" class="trainer-relay-btn-copy" id="' +
        COPY_PHONE_ID +
        '" hidden>Скопировать телефон</button>' +
        '</div>' +
        '<p id="' +
        NO_PHONE_ID +
        '" class="trainer-relay-no-phone" hidden role="note">' +
        'Телефона в карточке нет — только сообщение выше.' +
        '</p>' +
        '</div></div>'
    );

    var root = global.document.getElementById(MODAL_ID);
    global.document.getElementById('trainerClientRelayCancel').onclick = closeModal;
    root.addEventListener('click', function (ev) {
      if (ev.target === root) closeModal();
    });
    global.document.getElementById(SEND_ID).onclick = onSendClicked;
    global.document.getElementById(COPY_PHONE_ID).onclick = onCopyPhoneClicked;
  }

  function notifyCopied() {
    var tg = global.Telegram && global.Telegram.WebApp;
    if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.impactOccurred === 'function') {
      try {
        tg.HapticFeedback.impactOccurred('light');
      } catch (h0) {
        /* noop */
      }
    }
    if (tg && typeof tg.showAlert === 'function') {
      try {
        tg.showAlert('Телефон скопирован');
        return;
      } catch (a0) {
        /* noop */
      }
    }
    try {
      global.alert('Телефон скопирован');
    } catch (a1) {
      /* noop */
    }
  }

  function onCopyPhoneClicked() {
    var p = pending && pending.clientPhone ? String(pending.clientPhone).trim() : '';
    if (!p) return;
    if (global.navigator && global.navigator.clipboard && global.navigator.clipboard.writeText) {
      global.navigator.clipboard.writeText(p).then(
        function () {
          notifyCopied();
        },
        function () {
          fallbackCopyText(p);
        }
      );
      return;
    }
    fallbackCopyText(p);
  }

  function fallbackCopyText(text) {
    try {
      var ta = global.document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      global.document.body.appendChild(ta);
      ta.select();
      global.document.execCommand('copy');
      global.document.body.removeChild(ta);
      notifyCopied();
    } catch (e) {
      var tg = global.Telegram && global.Telegram.WebApp;
      if (tg && typeof tg.showAlert === 'function') {
        try {
          tg.showAlert('Скопируйте номер вручную:\n' + text);
          return;
        } catch (e2) {
          /* noop */
        }
      }
    }
  }

  function syncPhoneCopyRow() {
    var phone = pending && pending.clientPhone ? String(pending.clientPhone).trim() : '';
    var copyBtn = global.document.getElementById(COPY_PHONE_ID);
    var noPh = global.document.getElementById(NO_PHONE_ID);
    if (copyBtn) {
      copyBtn.hidden = !phone;
      copyBtn.disabled = !phone;
      if (phone) copyBtn.setAttribute('aria-label', 'Скопировать номер телефона клиента в буфер обмена');
      else copyBtn.removeAttribute('aria-label');
    }
    if (noPh) {
      noPh.hidden = !!phone;
    }
  }

  function setErr(msg) {
    var el = global.document.getElementById(ERR_ID);
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      el.hidden = false;
    } else {
      el.textContent = '';
      el.hidden = true;
    }
  }

  function onSendClicked() {
    if (!pending) return;
    var ta = global.document.getElementById(TEXT_ID);
    var btn = global.document.getElementById(SEND_ID);
    if (!ta || !btn) return;
    var text = String(ta.value || '').trim();
    setErr('');
    if (!text) {
      setErr('Введите текст сообщения.');
      return;
    }
    btn.disabled = true;
    var url = withInit(
      '/api/webapp/trainer/clients/' + encodeURIComponent(String(pending.clientId)) + '/relay-messages'
    );
    global
      .fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text }),
      })
      .then(function (r) {
        var ct = (r.headers && r.headers.get && r.headers.get('content-type')) || '';
        var isJson = ct.indexOf('application/json') >= 0;
        return (isJson ? r.json() : r.text().then(function (t) { return null; })).then(function (d) {
          if (!r.ok) {
            if (!isJson || d == null)
              throw new Error(r.status === 502 ? 'Сервис временно недоступен. Попробуйте позже.' : r.statusText || 'Ошибка');
            var detailMsg = '';
            if (d.detail != null) {
              var det = d.detail;
              if (typeof det === 'string') detailMsg = det;
              else if (Array.isArray(det))
                detailMsg = det
                  .map(function (x) {
                    return x && typeof x.msg === 'string' ? x.msg : '';
                  })
                  .filter(Boolean)
                  .join(' ');
              else detailMsg = String(det);
            }
            throw new Error(
              (detailMsg || (d.message && String(d.message)) || r.statusText || 'Ошибка')
            );
          }
          return d;
        });
      })
      .then(function () {
        var cb = pending && pending.onSent;
        closeModal();
        var tg = global.Telegram && global.Telegram.WebApp;
        if (tg && typeof tg.showAlert === 'function') {
          try {
            tg.showAlert('Сообщение отправлено');
            return;
          } catch (e1) {
            /* fallback */
          }
        }
        try {
          global.alert('Сообщение отправлено');
        } catch (e2) {
          /* noop */
        }
        if (typeof cb === 'function') {
          try {
            cb();
          } catch (e3) {
            /* noop */
          }
        }
      })
      .catch(function (err) {
        var msg = err && err.message ? String(err.message) : 'Не удалось отправить.';
        /* Humanize gateway */
        if (/bad gateway|502|503/i.test(msg)) msg = 'Сервис временно недоступен. Попробуйте позже.';
        setErr(msg);
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  }

  /**
   * @param { { clientId: number|string, subtitle?: string, clientPhone?: string, onSent?: function() } } opts
   * @returns { boolean } True when relay UI was shown or user was notified (no secondary fallback alerts).
   */
  function openSendModal(opts) {
    opts = opts || {};
    var cid = parseInt(String(opts.clientId || ''), 10);
    if (global.document.readyState === 'loading') {
      global.document.addEventListener('DOMContentLoaded', function once() {
        global.document.removeEventListener('DOMContentLoaded', once);
        openSendModal(opts);
      });
      return true;
    }
    ensureModal();
    var idata = getInitData();
    if (!idata) {
      var tgMiss = global.Telegram && global.Telegram.WebApp;
      if (tgMiss && typeof tgMiss.showAlert === 'function') {
        try {
          tgMiss.showAlert(
            'Нет авторизации Telegram. Закройте мини-приложение и откройте снова из бота тренера.'
          );
          return true;
        } catch (eM) {
          /* noop */
        }
      }
      global.alert('Нет авторизации Telegram. Откройте мини-приложение из бота тренера.');
      return true;
    }
    if (isNaN(cid) || cid < 1) {
      var tgBad = global.Telegram && global.Telegram.WebApp;
      if (tgBad && typeof tgBad.showAlert === 'function') {
        try {
          tgBad.showAlert('Не удалось определить клиента.');
          return true;
        } catch (eB) {
          /* noop */
        }
      }
      try {
        global.alert('Не удалось определить клиента.');
      } catch (eBb) {
        /* noop */
      }
      return true;
    }
    pending = {
      clientId: cid,
      onSent: opts.onSent,
      clientPhone: normalizeClientPhoneForCopy(opts.clientPhone != null ? opts.clientPhone : opts.phone || ''),
    };
    var ta = global.document.getElementById(TEXT_ID);
    var sub = global.document.getElementById(SUBTITLE_ID);
    if (ta) {
      ta.value = '';
      setTimeout(function () {
        try {
          ta.focus();
        } catch (eF) {
          /* noop */
        }
      }, 120);
    }
    if (sub) {
      var name = String(opts.subtitle || '').trim();
      sub.textContent = name ? 'Клиент: ' + name + '.' : '';
      sub.hidden = !name;
    }
    setErr('');
    syncPhoneCopyRow();
    var root = global.document.getElementById(MODAL_ID);
    if (root) root.setAttribute('aria-hidden', 'false');
    if (!root) {
      try {
        var stale = global.document.getElementById(MODAL_ID);
        if (stale && stale.parentNode) stale.parentNode.removeChild(stale);
      } catch (eStale) {
        /* noop */
      }
      ensureModal();
      root = global.document.getElementById(MODAL_ID);
      if (root) root.setAttribute('aria-hidden', 'false');
    }
    return !!root;
  }

  function trainerHubCoerceRelayFlag(raw) {
    if (raw === true || raw === 1 || raw === '1') return true;
    if (typeof raw === 'string' && raw.trim().toLowerCase() === 'true') return true;
    return false;
  }

  /** Hub message icon: relay modal vs t.me — must match TrainerRelayHelpers.shouldUseRelayModal + chrome fallback. */
  function hubBookingButtonWantsRelay(btn) {
    if (!btn) return false;
    if (
      trainerHubCoerceRelayFlag(global.TRAINER_WEBAPP_FORCE_CLIENT_CHAT_RELAY) ||
      trainerHubCoerceRelayFlag(global.TRAINER_HUB_FORCE_CLIENT_CHAT_RELAY)
    ) {
      return true;
    }
    return btn.getAttribute('data-hub-relay') === '1';
  }

  function resolveRelayClientIdFromHubButton(btn) {
    var cid = parseInt(String(btn.getAttribute('data-client-id') || ''), 10);
    if (!isNaN(cid) && cid >= 1) return cid;
    var bid = String(btn.getAttribute('data-booking-id') || '').trim();
    if (!bid) return NaN;
    var map = global.__hubRelayClientIdByBookingId;
    var fromMap = map && Object.prototype.hasOwnProperty.call(map, bid) ? map[bid] : null;
    if (fromMap == null) return NaN;
    var c2 = parseInt(String(fromMap), 10);
    return !isNaN(c2) && c2 >= 1 ? c2 : NaN;
  }

  function relayAlertBrokenHub(msg) {
    var tgA = global.Telegram && global.Telegram.WebApp;
    if (tgA && typeof tgA.showAlert === 'function') {
      try {
        tgA.showAlert(msg);
        return true;
      } catch (e1) {
        /* noop */
      }
    }
    try {
      global.alert(msg);
    } catch (e2) {
      /* noop */
    }
    return true;
  }

  /**
   * Hub «написать» icon — resilient to stale HTML caches (booking-id map + modal re-mount).
   */
  function openRelayFromBookingButton(btn) {
    if (!btn || !hubBookingButtonWantsRelay(btn)) return false;
    var cid = resolveRelayClientIdFromHubButton(btn);
    if (isNaN(cid) || cid < 1) {
      relayAlertBrokenHub(
        'Не удалось связать запись с клиентом. Закройте мини-приложение и откройте снова из бота — подтянется список «Ближайшие записи».'
      );
      return true;
    }
    return !!openSendModal({
      clientId: cid,
      subtitle: btn.getAttribute('data-client-label') || '',
      clientPhone: btn.getAttribute('data-client-phone') || '',
    });
  }

  global.TrainerClientRelayUi = {
    openSendModal: openSendModal,
    closeModal: closeModal,
    openRelayFromBookingButton: openRelayFromBookingButton,
    hubBookingButtonWantsRelay: hubBookingButtonWantsRelay,
  };
})(typeof window !== 'undefined' ? window : globalThis);
