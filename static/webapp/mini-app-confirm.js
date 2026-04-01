/**
 * In-app confirm dialog (replaces window.confirm) so OK uses brand CTA, not WebView blue.
 * Requires theme.css + mini-app-components.css (btn-primary / btn-secondary).
 */
(function () {
  var pendingResolve = null;

  function onKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close(false);
    }
  }

  function close(result) {
    document.removeEventListener('keydown', onKeyDown, true);
    var el = document.getElementById('appConfirmOverlay');
    if (el) {
      el.style.display = 'none';
      el.setAttribute('aria-hidden', 'true');
    }
    if (pendingResolve) {
      var r = pendingResolve;
      pendingResolve = null;
      r(result);
    }
  }

  function wireButtons() {
    var cancelBtn = document.getElementById('appConfirmCancel');
    var okBtn = document.getElementById('appConfirmOk');
    if (!cancelBtn || !okBtn) return;
    /* Re-bind every open — fixes orphaned overlay if first init threw before onclick was set. */
    cancelBtn.onclick = function () {
      close(false);
    };
    okBtn.onclick = function () {
      close(true);
    };
  }

  function ensureDom() {
    var existing = document.getElementById('appConfirmOverlay');
    var okBtnEl = document.getElementById('appConfirmOk');
    if (existing && okBtnEl) return;
    if (existing) {
      try {
        existing.remove();
      } catch (e) {
        /* ignore */
      }
    }
    var overlay = document.createElement('div');
    overlay.id = 'appConfirmOverlay';
    overlay.className = 'modal-overlay app-confirm-overlay';
    overlay.style.display = 'none';
    overlay.style.zIndex = '100050';
    overlay.setAttribute('aria-hidden', 'true');
    overlay.innerHTML =
      '<div class="modal app-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="appConfirmText">' +
      '<h3 id="appConfirmTitle" class="app-confirm-title" hidden></h3>' +
      '<p id="appConfirmText" class="app-confirm-message"></p>' +
      '<div class="app-confirm-actions">' +
      '<button type="button" class="btn-secondary btn-block" id="appConfirmCancel"></button>' +
      '<button type="button" class="btn-primary btn-block app-confirm-ok" id="appConfirmOk"></button>' +
      '</div></div>';
    document.body.appendChild(overlay);
    wireButtons();
  }

  /**
   * @param {string} message
   * @param {{ title?: string, okText?: string, cancelText?: string }} [options]
   * @returns {Promise<boolean>}
   */
  window.showAppConfirm = function (message, options) {
    options = options || {};
    ensureDom();
    wireButtons();
    return new Promise(function (resolve) {
      var titleEl = document.getElementById('appConfirmTitle');
      var textEl = document.getElementById('appConfirmText');
      var okBtn = document.getElementById('appConfirmOk');
      var cancelBtn = document.getElementById('appConfirmCancel');
      var overlay = document.getElementById('appConfirmOverlay');
      if (!titleEl || !textEl || !okBtn || !cancelBtn || !overlay) {
        /* Broken DOM — fall back so destructive flows still work */
        var okNative =
          typeof window.confirm === 'function' &&
          window.confirm(message == null ? '' : String(message));
        resolve(!!okNative);
        return;
      }
      pendingResolve = resolve;
      okBtn.classList.add('app-confirm-ok');
      if (options.title) {
        titleEl.textContent = options.title;
        titleEl.removeAttribute('hidden');
      } else {
        titleEl.textContent = '';
        titleEl.setAttribute('hidden', '');
      }
      textEl.textContent = message == null ? '' : String(message);
      okBtn.textContent = options.okText || 'OK';
      cancelBtn.textContent = options.cancelText || 'Отмена';
      overlay.style.display = 'flex';
      overlay.setAttribute('aria-hidden', 'false');
      document.addEventListener('keydown', onKeyDown, true);
      try {
        setTimeout(function () {
          try {
            okBtn.focus();
          } catch (e) {
            /* ignore */
          }
        }, 0);
      } catch (e) {
        /* ignore */
      }
    });
  };
})();
