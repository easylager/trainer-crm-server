/**
 * Shared phone field: country dropdown (BY +375 / RU +7) + national mask + E.164 helpers.
 * Depends on mini-app-telegram-chrome.js (optional caret helpers for legacy BY mask).
 */
(function (global) {
  'use strict';

  var COUNTRIES = {
    BY: {
      code: 'BY',
      dial: '+375',
      flag: '🇧🇾',
      label: 'Беларусь',
      nationalLen: 9,
      placeholder: '29 123-45-67',
    },
    RU: {
      code: 'RU',
      dial: '+7',
      flag: '🇷🇺',
      label: 'Россия',
      nationalLen: 10,
      placeholder: '912 345-67-89',
    },
  };

  function stripDigits(raw) {
    return String(raw || '').replace(/\D/g, '');
  }

  function detectCountryFromDigits(d) {
    d = d || '';
    while (d.length >= 2 && d.slice(0, 2) === '00') d = d.slice(2);
    if (d.length >= 12 && d.indexOf('375') === 0) return 'BY';
    if (d.length === 11 && d.indexOf('80') === 0) return 'BY';
    if (d.length === 11 && d.charAt(0) === '8') return 'RU';
    if (d.length >= 11 && d.charAt(0) === '7') return 'RU';
    if (d.length === 10 && d.charAt(0) === '9') return 'RU';
    if (d.length === 9) return 'BY';
    return 'BY';
  }

  function stripLeadingDialForCountry(raw, country) {
    var t = String(raw || '').replace(/^\uFEFF/, '');
    var cc = COUNTRIES[country] || COUNTRIES.BY;
    for (var i = 0; i < 8; i++) {
      var prev = t;
      t = t.replace(/^\s+/, '');
      if (country === 'BY') {
        if (typeof global.stripLeadingDialCodeTokensFor375Field === 'function') {
          t = global.stripLeadingDialCodeTokensFor375Field(t);
          if (t === prev) break;
          continue;
        }
        t = t
          .replace(/^\+\s*375/i, '')
          .replace(/^375(?=\d)/i, '')
          .replace(/^80(?=\d)/i, '')
          .replace(/^\+(?=\s*\d)/, '');
      } else {
        t = t
          .replace(/^\+\s*7/i, '')
          .replace(/^7(?=\d)/, '')
          .replace(/^8(?=\d)/, '')
          .replace(/^\+(?=\s*\d)/, '');
      }
      if (t === prev) break;
    }
    return t;
  }

  function extractNationalDigits(raw, country) {
    var cc = country || 'BY';
    var d = stripDigits(raw);
    while (d.length >= 2 && d.slice(0, 2) === '00') d = d.slice(2);
    if (cc === 'BY') {
      while (d.length > 9 && d.indexOf('375') === 0) d = d.slice(3);
      if (d.indexOf('80') === 0 && d.length >= 9) d = d.slice(2);
      while (d.length > 9 && d.indexOf('375') === 0) d = d.slice(3);
      return d.slice(0, 9);
    }
    while (d.length > 10 && d.charAt(0) === '7') d = d.slice(1);
    if (d.length === 11 && d.charAt(0) === '8') d = d.slice(1);
    if (d.length === 11 && d.charAt(0) === '7') d = d.slice(1);
    return d.slice(0, 10);
  }

  function formatNationalMasked(digits, country) {
    var cc = COUNTRIES[country] || COUNTRIES.BY;
    var d = extractNationalDigits(digits, country);
    if (cc.code === 'BY') {
      var f = '';
      if (d.length > 0) f = d.slice(0, 2);
      if (d.length > 2) f += ' ' + d.slice(2, 5);
      if (d.length > 5) f += '-' + d.slice(5, 7);
      if (d.length > 7) f += '-' + d.slice(7, 9);
      return f;
    }
    var g = '';
    if (d.length > 0) g = d.slice(0, 3);
    if (d.length > 3) g += ' ' + d.slice(3, 6);
    if (d.length > 6) g += '-' + d.slice(6, 8);
    if (d.length > 8) g += '-' + d.slice(8, 10);
    return g;
  }

  function nationalToE164(nationalDigits, country) {
    var cc = COUNTRIES[country] || COUNTRIES.BY;
    var d = extractNationalDigits(nationalDigits, country);
    if (d.length !== cc.nationalLen) return '';
    return cc.dial + d;
  }

  function parseE164ToCountryAndNational(e164) {
    var s = String(e164 || '').trim();
    var d = stripDigits(s);
    if (d.indexOf('375') === 0 && d.length >= 12) {
      return { country: 'BY', national: d.slice(3, 12) };
    }
    if (d.charAt(0) === '7' && d.length >= 11) {
      return { country: 'RU', national: d.slice(1, 11) };
    }
    if (d.length === 9) return { country: 'BY', national: d };
    if (d.length === 10 && d.charAt(0) === '9') return { country: 'RU', national: d };
    var guessed = detectCountryFromDigits(d);
    var nat = extractNationalDigits(d, guessed);
    return { country: guessed, national: nat };
  }

  function digitsBeforeCaret(str, caretIndex) {
    var n = 0;
    var lim = Math.min(Math.max(0, caretIndex), str.length);
    for (var i = 0; i < lim; i++) {
      if (/\d/.test(str.charAt(i))) n++;
    }
    return n;
  }

  function indexAfterDigitCount(str, digitCount) {
    if (digitCount <= 0) return 0;
    var seen = 0;
    for (var i = 0; i < str.length; i++) {
      if (/\d/.test(str.charAt(i))) {
        seen++;
        if (seen === digitCount) return i + 1;
      }
    }
    return str.length;
  }

  function applyMaskedToInput(input, country) {
    if (!input) return;
    var raw = String(input.value || '');
    var ss = typeof input.selectionStart === 'number' ? input.selectionStart : raw.length;
    var se = typeof input.selectionEnd === 'number' ? input.selectionEnd : ss;
    var caret = Math.min(ss, se);
    var work = stripLeadingDialForCountry(raw, country);
    var digitsBefore;
    if (work !== raw) {
      var caret2 = caret - (raw.length - work.length);
      if (caret2 < 0) caret2 = 0;
      digitsBefore = digitsBeforeCaret(work, caret2);
    } else {
      digitsBefore = digitsBeforeCaret(work, caret);
    }
    var masked = formatNationalMasked(work, country);
    if (work === masked) return;
    input.value = masked;
    try {
      var newPos = indexAfterDigitCount(masked, digitsBefore);
      input.setSelectionRange(newPos, newPos);
    } catch (e) {}
  }

  function getWrapCountry(wrap) {
    var c = wrap && wrap.getAttribute('data-crm-phone-country');
    return COUNTRIES[c] ? c : 'BY';
  }

  function setWrapCountry(wrap, country) {
    if (!wrap || !COUNTRIES[country]) return;
    wrap.setAttribute('data-crm-phone-country', country);
    var meta = COUNTRIES[country];
    var btn = wrap.querySelector('.crm-phone-country-btn');
    var flagEl = wrap.querySelector('.crm-phone-country-flag');
    var dialEl = wrap.querySelector('.crm-phone-country-dial');
    var input = wrap.querySelector('.crm-phone-national-input');
    if (flagEl) flagEl.textContent = meta.flag;
    if (dialEl) dialEl.textContent = meta.dial;
    if (input) {
      input.placeholder = meta.placeholder;
      input.setAttribute('maxlength', String(meta.nationalLen + 8));
    }
    wrap.querySelectorAll('.crm-phone-country-option').forEach(function (opt) {
      var on = opt.getAttribute('data-country') === country;
      opt.setAttribute('aria-selected', on ? 'true' : 'false');
      opt.classList.toggle('crm-phone-country-option--active', on);
    });
  }

  function closeCountryMenu(wrap) {
    var menu = wrap && wrap.querySelector('.crm-phone-country-menu');
    var btn = wrap && wrap.querySelector('.crm-phone-country-btn');
    if (menu) menu.hidden = true;
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }

  function openCountryMenu(wrap) {
    var menu = wrap.querySelector('.crm-phone-country-menu');
    var btn = wrap.querySelector('.crm-phone-country-btn');
    if (menu) menu.hidden = false;
    if (btn) btn.setAttribute('aria-expanded', 'true');
  }

  function wireCountryDropdown(wrap) {
    var btn = wrap.querySelector('.crm-phone-country-btn');
    var menu = wrap.querySelector('.crm-phone-country-menu');
    if (!btn || !menu || btn.dataset.crmPhoneCountryWired === '1') return;
    btn.dataset.crmPhoneCountryWired = '1';
    btn.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      if (menu.hidden) openCountryMenu(wrap);
      else closeCountryMenu(wrap);
    });
    menu.querySelectorAll('.crm-phone-country-option').forEach(function (opt) {
      opt.addEventListener('click', function (ev) {
        ev.preventDefault();
        var country = opt.getAttribute('data-country');
        if (!country || !COUNTRIES[country]) return;
        var prev = getWrapCountry(wrap);
        setWrapCountry(wrap, country);
        closeCountryMenu(wrap);
        var input = wrap.querySelector('.crm-phone-national-input');
        if (input && prev !== country) {
          var nat = extractNationalDigits(input.value, country);
          input.value = formatNationalMasked(nat, country);
        }
        input && input.focus();
      });
    });
    if (!global.__crmPhoneFieldDocCloseWired) {
      global.__crmPhoneFieldDocCloseWired = true;
      global.document.addEventListener('click', function () {
        global.document.querySelectorAll('[data-crm-phone-field]').forEach(closeCountryMenu);
      });
    }
  }

  function wireNationalInput(wrap) {
    var input = wrap.querySelector('.crm-phone-national-input');
    if (!input || input.dataset.crmPhoneMaskWired === '1') return;
    input.dataset.crmPhoneMaskWired = '1';
    input.addEventListener('paste', function (e) {
      var cd = e.clipboardData || global.clipboardData;
      if (!cd || typeof cd.getData !== 'function') return;
      var textRaw = cd.getData('text/plain');
      if (textRaw == null || String(textRaw).trim() === '') return;
      e.preventDefault();
      var country = getWrapCountry(wrap);
      var parsed = parseE164ToCountryAndNational(textRaw);
      if (parsed.national.length >= COUNTRIES[country].nationalLen - 1) {
        setWrapCountry(wrap, parsed.country);
        country = parsed.country;
      }
      var cur = String(input.value || '');
      var start = typeof input.selectionStart === 'number' ? input.selectionStart : cur.length;
      var end = typeof input.selectionEnd === 'number' ? input.selectionEnd : start;
      var pasteNat = extractNationalDigits(textRaw, country);
      var merged;
      if (pasteNat.length >= COUNTRIES[country].nationalLen) {
        merged = pasteNat;
      } else {
        var chunk = stripLeadingDialForCountry(String(textRaw), country);
        merged = cur.slice(0, start) + chunk + cur.slice(end);
      }
      input.value = formatNationalMasked(merged, country);
      try {
        var len = input.value.length;
        input.setSelectionRange(len, len);
      } catch (err) {}
    });
    input.addEventListener('input', function () {
      applyMaskedToInput(input, getWrapCountry(wrap));
    });
    input.addEventListener('blur', function () {
      applyMaskedToInput(input, getWrapCountry(wrap));
    });
  }

  function init(wrap, opts) {
    if (!wrap || wrap.dataset.crmPhoneFieldWired === '1') return wrap;
    wrap.dataset.crmPhoneFieldWired = '1';
    var def = (opts && opts.defaultCountry) || wrap.getAttribute('data-default-country') || 'BY';
    setWrapCountry(wrap, COUNTRIES[def] ? def : 'BY');
    wireCountryDropdown(wrap);
    wireNationalInput(wrap);
    return wrap;
  }

  function initAll(root) {
    var scope = root && root.querySelectorAll ? root : global.document;
    var nodes = scope.querySelectorAll ? scope.querySelectorAll('[data-crm-phone-field]') : [];
    for (var i = 0; i < nodes.length; i++) init(nodes[i]);
  }

  function getE164(wrapOrInput) {
    var wrap =
      wrapOrInput && wrapOrInput.getAttribute && wrapOrInput.getAttribute('data-crm-phone-field')
        ? wrapOrInput
        : wrapOrInput && wrapOrInput.closest
          ? wrapOrInput.closest('[data-crm-phone-field]')
          : null;
    if (!wrap) return '';
    var country = getWrapCountry(wrap);
    var input = wrap.querySelector('.crm-phone-national-input');
    return nationalToE164(input ? input.value : '', country);
  }

  function setE164(wrapOrInput, e164) {
    var wrap =
      wrapOrInput && wrapOrInput.getAttribute && wrapOrInput.getAttribute('data-crm-phone-field')
        ? wrapOrInput
        : wrapOrInput && wrapOrInput.closest
          ? wrapOrInput.closest('[data-crm-phone-field]')
          : null;
    if (!wrap) return;
    var parsed = parseE164ToCountryAndNational(e164);
    setWrapCountry(wrap, parsed.country);
    var input = wrap.querySelector('.crm-phone-national-input');
    if (input) input.value = formatNationalMasked(parsed.national, parsed.country);
  }

  function validate(wrapOrInput) {
    var e164 = getE164(wrapOrInput);
    if (!e164) {
      return { ok: false, e164: '', error: 'Укажите номер телефона.' };
    }
    var wrap =
      wrapOrInput && wrapOrInput.closest
        ? wrapOrInput.closest('[data-crm-phone-field]')
        : wrapOrInput;
    var country = getWrapCountry(wrap);
    var cc = COUNTRIES[country];
    var nat = extractNationalDigits(
      (wrap && wrap.querySelector('.crm-phone-national-input') || {}).value || '',
      country
    );
    if (nat.length !== cc.nationalLen) {
      return {
        ok: false,
        e164: '',
        error:
          country === 'RU'
            ? 'Введите 10 цифр номера после +7.'
            : 'Введите 9 цифр номера после +375.',
      };
    }
    return { ok: true, e164: e164, error: null };
  }

  /** Upgrade legacy hub-phone-input-wrap (+375 only) to dropdown field in place. */
  function upgradeLegacyWrap(legacyWrap, inputId) {
    if (!legacyWrap || legacyWrap.getAttribute('data-crm-phone-field')) return legacyWrap;
    var oldInput = legacyWrap.querySelector('input');
    var inputClass = oldInput ? oldInput.className.replace(/\bhub-phone-input\b/g, '').trim() : 'input';
    var ph = oldInput ? oldInput.getAttribute('placeholder') : '';
    var req = oldInput && oldInput.getAttribute('aria-required') === 'true';
    var ac = oldInput ? oldInput.getAttribute('autocomplete') || 'tel-national' : 'tel-national';
    var id = inputId || (oldInput && oldInput.id) || '';
    legacyWrap.className = (legacyWrap.className + ' crm-phone-field').replace(/\bhub-phone-input-wrap\b/g, '').trim();
    legacyWrap.setAttribute('data-crm-phone-field', '');
    legacyWrap.setAttribute('data-default-country', 'BY');
    legacyWrap.innerHTML =
      '<div class="crm-phone-field-row">' +
      '<button type="button" class="crm-phone-country-btn" aria-label="Код страны" aria-haspopup="listbox" aria-expanded="false">' +
      '<span class="crm-phone-country-flag" aria-hidden="true">🇧🇾</span>' +
      '<span class="crm-phone-country-dial">+375</span>' +
      '<span class="crm-phone-country-chevron" aria-hidden="true">▾</span>' +
      '</button>' +
      '<input type="tel" class="crm-phone-national-input ' +
      inputClass +
      '"' +
      (id ? ' id="' + id + '"' : '') +
      ' inputmode="tel" autocomplete="' +
      ac +
      '"' +
      (req ? ' aria-required="true"' : '') +
      ' placeholder="' +
      (ph || '29 123-45-67') +
      '" />' +
      '</div>' +
      '<div class="crm-phone-country-menu" role="listbox" hidden>' +
      '<button type="button" class="crm-phone-country-option crm-phone-country-option--active" role="option" data-country="BY" aria-selected="true">🇧🇾 Беларусь +375</button>' +
      '<button type="button" class="crm-phone-country-option" role="option" data-country="RU" aria-selected="false">🇷🇺 Россия +7</button>' +
      '</div>';
    init(legacyWrap);
    return legacyWrap;
  }

  /** Digits and leading + only — safe tel: URI for Telegram WebView / iOS data detectors. */
  function phoneToTelUri(phone) {
    var s = String(phone || '').trim();
    if (!s) return '';
    var cleaned = s.replace(/[^\d+]/g, '');
    if (!cleaned || cleaned === '+') return '';
    return 'tel:' + cleaned;
  }

  /** Open the system dialer. tel: is NOT supported by Telegram.WebApp.openLink. */
  function openPhoneDialer(phone) {
    var uri = phoneToTelUri(phone);
    if (!uri) return false;
    /* Same-document navigation works in more Telegram iOS builds than window.open(tel:). */
    try {
      window.location.href = uri;
      return true;
    } catch (e0) {
      /* continue */
    }
    try {
      window.location.assign(uri);
      return true;
    } catch (e1) {
      /* continue */
    }
    try {
      var a = document.createElement('a');
      a.href = uri;
      a.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;';
      (document.body || document.documentElement).appendChild(a);
      a.click();
      setTimeout(function () {
        try {
          if (a.parentNode) a.parentNode.removeChild(a);
        } catch (x) {
          /* noop */
        }
      }, 0);
      return true;
    } catch (e2) {
      /* continue */
    }
    try {
      window.open(uri, '_self');
      return true;
    } catch (e3) {
      /* continue */
    }
    return false;
  }

  /**
   * Inline tel control: native <a href="tel:"> for tap + iOS long-press «Позвонить».
   * Programmatic dialer is only for legacy <button data-call-phone> fallbacks.
   */
  function phoneTelLinkHtml(phone, extraClass, escapeHtmlFn) {
    var p = String(phone || '').trim();
    if (!p) return '';
    var esc =
      typeof escapeHtmlFn === 'function'
        ? escapeHtmlFn
        : function (x) {
            return String(x);
          };
    var uri = phoneToTelUri(p);
    if (!uri) return esc(p);
    var cls = extraClass ? esc(extraClass) : 'crm-tel-link';
    return (
      '<a href="' +
      esc(uri) +
      '" class="' +
      cls +
      '" aria-label="\u041f\u043e\u0437\u0432\u043e\u043d\u0438\u0442\u044c ' +
      esc(p) +
      '">' +
      esc(p) +
      '</a>'
    );
  }

  function wirePhoneCallButtons(root) {
    var scope = root && root.querySelectorAll ? root : global.document;
    if (!scope.querySelectorAll) return;
    /* Native tel: anchors — tap/long-press handled by WebView; do not preventDefault. */
    var nodes = scope.querySelectorAll('button[data-call-phone]');
    for (var i = 0; i < nodes.length; i++) {
      var btn = nodes[i];
      if (btn.getAttribute('data-call-phone-wired') === '1') continue;
      btn.setAttribute('data-call-phone-wired', '1');
      btn.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var el = ev.currentTarget;
        var raw = el && el.getAttribute ? el.getAttribute('data-call-phone') || '' : '';
        if (!openPhoneDialer(raw)) {
          var tg = global.Telegram && global.Telegram.WebApp;
          if (tg && typeof tg.showAlert === 'function') {
            try {
              tg.showAlert('Не удалось открыть набор номера. Скопируйте телефон и наберите вручную.');
            } catch (e) {
              /* noop */
            }
          }
        }
      });
    }
  }

  /** @deprecated use wirePhoneCallButtons */
  function wirePhoneTelLinks(root) {
    wirePhoneCallButtons(root);
  }

  global.CrmPhoneField = {
    COUNTRIES: COUNTRIES,
    init: init,
    initAll: initAll,
    getE164: getE164,
    setE164: setE164,
    validate: validate,
    upgradeLegacyWrap: upgradeLegacyWrap,
    extractNationalDigits: extractNationalDigits,
    formatNationalMasked: formatNationalMasked,
    nationalToE164: nationalToE164,
    parseE164ToCountryAndNational: parseE164ToCountryAndNational,
    phoneToTelUri: phoneToTelUri,
    openPhoneDialer: openPhoneDialer,
    phoneTelLinkHtml: phoneTelLinkHtml,
    wirePhoneCallButtons: wirePhoneCallButtons,
    wirePhoneTelLinks: wirePhoneTelLinks,
  };

  /* Backward compat: legacy callers still work for BY-only paths. */
  global.extractNational375Digits = function (raw) {
    return extractNationalDigits(raw, 'BY');
  };
  global.wireNational375PhoneInputMask = function (el) {
    var wrap = el && el.closest && el.closest('[data-crm-phone-field]');
    if (wrap) return;
    var parent = el && el.parentElement;
    if (parent && (parent.classList.contains('hub-phone-input-wrap') || parent.classList.contains('phone-input-wrap') || parent.classList.contains('catalog-phone-input-wrap') || parent.classList.contains('book-phone-input-wrap') || parent.classList.contains('cr-phone-wrap'))) {
      upgradeLegacyWrap(parent, el.id);
      return;
    }
    if (el && el.dataset.crmNat375Mask !== '1') {
      el.dataset.crmNat375Mask = '1';
      el.addEventListener('input', function () {
        applyMaskedToInput(el, 'BY');
      });
      el.addEventListener('blur', function () {
        applyMaskedToInput(el, 'BY');
      });
    }
  };
})(window);
