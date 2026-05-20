(function () {
  'use strict';

  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    if (typeof tg.ready === 'function') tg.ready();
    if (typeof tg.expand === 'function') tg.expand();
    try {
      var dark = tg.colorScheme === 'dark' ||
        (tg.colorScheme !== 'light' &&
          window.matchMedia &&
          window.matchMedia('(prefers-color-scheme: dark)').matches);
      var bg = dark ? '#1c1c1e' : '#f2f2f7';
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bg);
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bg);
    } catch (e) {
      /* older clients */
    }
  }

  var qs = new URLSearchParams(window.location.search);
  var initData =
    tg && tg.initData ? tg.initData : qs.get('init_data') || qs.get('initData') || '';

  function currentInit() {
    if (tg && tg.initData) initData = tg.initData;
    return initData || '';
  }
  function apiHeaders() {
    var raw = currentInit();
    return raw
      ? { 'X-Telegram-Init-Data': raw, 'Content-Type': 'application/json' }
      : { 'Content-Type': 'application/json' };
  }
  function apiUrl(path) {
    var raw = currentInit();
    return '/api/webapp' + path + (raw ? '?init_data=' + encodeURIComponent(raw) : '');
  }

  /** Telegram/WebView occasionally drops ?trainer_id=; persist after first successful open. */
  var TRAINER_REG_KEY = 'trainer_crm_client_register_tid';

  /** Server injects trainer id into HTML when the page is requested with ?trainer_id= — survives empty location.search. */
  function trainerIdFromMeta() {
    var m = document.querySelector('meta[name="trainer-crm-register-trainer-id"]');
    if (!m || typeof m.getAttribute !== 'function') return null;
    var raw = String(m.getAttribute('content') || '').trim();
    if (!raw) return null;
    var v = parseInt(raw, 10);
    return v > 0 ? v : null;
  }

  function resolveTrainerId() {
    var fromMeta = trainerIdFromMeta();
    if (fromMeta) {
      try {
        sessionStorage.setItem(TRAINER_REG_KEY, String(fromMeta));
      } catch (e) {
        /* private mode */
      }
      return fromMeta;
    }
    var q = parseInt(qs.get('trainer_id') || '', 10);
    if (q > 0) {
      try {
        sessionStorage.setItem(TRAINER_REG_KEY, String(q));
      } catch (e) {
        /* private mode */
      }
      return q;
    }
    try {
      var sid = parseInt(sessionStorage.getItem(TRAINER_REG_KEY) || '', 10);
      return sid > 0 ? sid : null;
    } catch (e2) {
      return null;
    }
  }

  var trainerId = resolveTrainerId();

  var heroSub = document.getElementById('crHeroSub');
  var phoneInput = document.getElementById('crPhone');
  var phoneError = document.getElementById('crPhoneError');
  var firstNameInput = document.getElementById('crFirstName');
  var firstNameError = document.getElementById('crFirstNameError');
  var lastNameInput = document.getElementById('crLastName');
  var globalError = document.getElementById('crGlobalError');
  var btnSubmit = document.getElementById('crBtnSubmit');
  var formCard = document.getElementById('crFormCard');
  var actions = document.getElementById('crActions');
  var successScreen = document.getElementById('crSuccessScreen');
  var successSub = document.getElementById('crSuccessSub');
  var btnOpenHome = document.getElementById('crBtnOpenHome');

  // Phone mask (+375 rendered outside — same as trainer-clients)
  if (phoneInput) {
    try {
      if (typeof window.wireNational375PhoneInputMask === 'function') {
        window.wireNational375PhoneInputMask(phoneInput);
      } else {
        function applyFragMask() {
          var raw = String(phoneInput.value || '')
            .replace(/\D/g, '')
            .slice(0, 9);
          var n = raw.length;
          var f = '';
          if (n > 0) f = raw.slice(0, 2);
          if (n > 2) f += ' ' + raw.slice(2, 5);
          if (n > 5) f += '-' + raw.slice(5, 7);
          if (n > 7) f += '-' + raw.slice(7, 9);
          phoneInput.value = f;
        }
        phoneInput.addEventListener('input', applyFragMask);
        phoneInput.addEventListener('blur', applyFragMask);
      }
    } catch (maskErr) {
      /* never block Continue if mask wiring throws */
    }
  }

  function extractNational(raw) {
    if (typeof window.extractNational375Digits === 'function') {
      return window.extractNational375Digits(raw);
    }
    var d = String(raw || '').replace(/\D/g, '');
    while (d.length >= 2 && d.slice(0, 2) === '00') d = d.slice(2);
    while (d.length > 9 && d.indexOf('375') === 0) d = d.slice(3);
    if (d.indexOf('80') === 0 && d.length >= 9) d = d.slice(2);
    return d.slice(0, 9);
  }

  function validatePhone(raw) {
    var nat = extractNational(raw);
    if (!nat || nat.length < 9) return 'Введите 9 цифр номера.';
    return null;
  }

  function scrollMsgIntoView(el) {
    if (!el) return;
    try {
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } catch (e) {
      try {
        el.scrollIntoView();
      } catch (e2) {
        /* older WebView */
      }
    }
  }

  function showFieldError(el, msg) {
    if (!el) return;
    el.textContent = msg || '';
    el.classList.toggle('cr-error--visible', !!msg);
    if (msg) scrollMsgIntoView(el);
  }
  function showGlobalError(msg) {
    if (!globalError) return;
    globalError.textContent = msg || '';
    globalError.classList.toggle('cr-global-error--visible', !!msg);
    if (globalError.style) globalError.style.display = '';
    if (msg) scrollMsgIntoView(globalError);
  }
  function clearErrors() {
    showFieldError(phoneError, '');
    showFieldError(firstNameError, '');
    showGlobalError('');
  }

  function setLoading(on) {
    if (!btnSubmit) return;
    btnSubmit.disabled = !!on;
    btnSubmit.classList.toggle('cr-loading', !!on);
  }

  function showSuccess(opts) {
    opts = opts || {};
    if (formCard) formCard.style.display = 'none';
    if (actions) actions.style.display = 'none';
    if (globalError) globalError.style.display = 'none';
    if (successScreen) successScreen.classList.add('cr-success-screen--visible');
    if (successSub) {
      successSub.textContent = opts.message ||
        'Профиль сохранён. Откройте «Главная» — кнопка слева внизу в Telegram. Там ваш тренер как основной.';
    }
    if (btnOpenHome) {
      btnOpenHome.style.display = 'block';
    }
    if (!opts.skipAutoRedirect) {
      window.setTimeout(function () {
        window.location.href = clientHomeUrl();
      }, opts.redirectMs != null ? opts.redirectMs : 2200);
    }
  }

  /** Profile already complete — block re-submit via stale «Продолжить» Web App button. */
  function checkAlreadyRegistered() {
    if (!currentInit()) return;
    fetch(apiUrl('/client/session'), { headers: apiHeaders(), cache: 'no-store' })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (sess) {
        if (!sess) return;
        var phone =
          sess.client_phone != null && String(sess.client_phone).trim() !== '';
        if (!phone) return;
        showSuccess({
          message:
            'Профиль уже сохранён. Откройте «Главная» — кнопка слева внизу в Telegram. Там ваш тренер как основной.',
          skipAutoRedirect: false,
          redirectMs: 2800,
        });
      })
      .catch(function () {
        /* non-critical */
      });
  }

  function clientHomeUrl() {
    var path = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
    var raw = currentInit();
    return path + 'client-home' + (raw ? '?init_data=' + encodeURIComponent(raw) : '');
  }

  function goToClientHome() {
    window.location.href = clientHomeUrl();
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function loadTrainerInfo() {
    if (!trainerId) return;
    fetch(apiUrl('/client/register/trainer-info/' + trainerId), {
      headers: { 'X-Telegram-Init-Data': currentInit() },
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        if (data && data.name) {
          var name = String(data.name).trim();
          if (heroSub) {
            heroSub.innerHTML =
              'Приглашение от <strong class="cr-hero-trainer-name">' +
              escapeHtml(name) +
              '</strong>. Заполните поля — и продолжите в приложении.';
          }
        }
      })
      .catch(function () {
        /* non-critical */
      });
  }

  function parseFetchJsonResponse(r) {
    var ct = (r.headers.get('content-type') || '').toLowerCase();
    if (ct.indexOf('application/json') >= 0) {
      return r.json().then(function (data) {
        return { ok: r.ok, status: r.status, data: data };
      });
    }
    return r.text().then(function (text) {
      return {
        ok: r.ok,
        status: r.status,
        data: {
          detail: !r.ok
            ? 'Сервер вернул не JSON (код ' + r.status + '). Проверьте соединение.'
            : null,
          _bodyPreview: text ? text.slice(0, 160) : '',
        },
      };
    });
  }

  function handleSubmit() {
    try {
      clearErrors();

      if (!trainerId) {
        showGlobalError(
          'В ссылке нет параметра тренера. Закройте мини-приложение и откройте снова через кнопку в сообщении от бота.'
        );
        return;
      }

      var rawPhone = phoneInput ? String(phoneInput.value || '') : '';
      var phoneErr = validatePhone(rawPhone);
      if (phoneErr) {
        showFieldError(phoneError, phoneErr);
        if (phoneInput) phoneInput.focus();
        return;
      }
      var nat = extractNational(rawPhone);
      var fullPhone = '+375' + nat;

      var firstName = firstNameInput ? String(firstNameInput.value || '').trim() : '';
      if (!firstName) {
        showFieldError(firstNameError, 'Укажите имя.');
        if (firstNameInput) firstNameInput.focus();
        return;
      }

      var lastName = lastNameInput ? String(lastNameInput.value || '').trim() : '';

      setLoading(true);

      var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
      var tOut = window.setTimeout(function () {
        if (ctrl)
          try {
            ctrl.abort();
          } catch (abortErr) {
            /* noop */
          }
      }, 60000);

      fetch(apiUrl('/client/self-register'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          trainer_id: trainerId,
          phone: fullPhone,
          first_name: firstName,
          last_name: lastName || null,
        }),
        signal: ctrl ? ctrl.signal : undefined,
      })
        .then(parseFetchJsonResponse)
        .then(function (res) {
          if (!res.ok) {
            var detail =
              res.data && res.data.detail
                ? String(res.data.detail)
                : 'Ошибка при сохранении. Попробуйте ещё раз.';
            if (res.status === 409) showFieldError(phoneError, detail);
            else if (res.status === 422) {
              var ed = res.data && res.data.detail;
              showGlobalError(
                Array.isArray(ed)
                  ? ed.map(function (e) {
                      return e.msg || String(e);
                    }).join(' ')
                  : detail
              );
            } else showGlobalError(detail);
            return;
          }
          var st = res.data && res.data.status ? String(res.data.status) : '';
          var hubHint =
            'Откройте «Главная» — кнопка слева внизу в Telegram. Там ваш тренер как основной.';
          if (st === 'already_registered' || st === 'linked') {
            showSuccess({
              message: 'Профиль уже есть. ' + hubHint,
              redirectMs: 3200,
            });
            return;
          }
          showSuccess({
            message: 'Профиль сохранён. ' + hubHint,
            redirectMs: 3200,
          });
        })
        .catch(function (err) {
          var name = err && err.name ? String(err.name) : '';
          showGlobalError(
            name === 'AbortError'
              ? 'Превышено время ожидания. Попробуйте ещё раз.'
              : 'Проблема с соединением. Проверьте интернет и попробуйте ещё раз.'
          );
        })
        .finally(function () {
          window.clearTimeout(tOut);
          setLoading(false);
        });
    } catch (err) {
      setLoading(false);
      showGlobalError('Не удалось отправить форму. Обновите мини-приложение.');
    }
  }

  /** WebView-safe entry: bound in JS (inline onclick is unreliable in some Telegram WebViews). */
  window.__trainerCrmRegSubmit = function (ev) {
    try {
      if (ev && ev.preventDefault) ev.preventDefault();
      if (ev && ev.stopPropagation) ev.stopPropagation();
    } catch (e1) {
      /* noop */
    }
    try {
      if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.impactOccurred === 'function') {
        tg.HapticFeedback.impactOccurred('light');
      }
    } catch (e2) {
      /* noop */
    }
    handleSubmit();
  };

  if (btnSubmit) {
    btnSubmit.addEventListener('click', window.__trainerCrmRegSubmit, false);
  }

  ['crPhone', 'crFirstName', 'crLastName'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) {
      el.addEventListener(
        'keydown',
        function (e) {
          if (e.key === 'Enter') {
            e.preventDefault();
            handleSubmit();
          }
        },
        false
      );
    }
  });

  if (phoneInput) {
    phoneInput.addEventListener(
      'input',
      function () {
        showFieldError(phoneError, '');
      },
      false
    );
  }
  if (firstNameInput) {
    firstNameInput.addEventListener(
      'input',
      function () {
        showFieldError(firstNameError, '');
      },
      false
    );
  }

  if (btnOpenHome) {
    btnOpenHome.addEventListener('click', goToClientHome, false);
  }

  if (tg && tg.BackButton) {
    tg.BackButton.show();
    tg.BackButton.onClick(function () {
      tg.close();
    });
  }

  loadTrainerInfo();
  checkAlreadyRegistered();
})();
