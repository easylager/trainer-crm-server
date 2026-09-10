/**
 * Shared client booking module — session, slots, form payload, submit, success, back stack.
 * Used by catalog-main.js and book.html (strangler hosts).
 */
(function (global) {
  'use strict';

  var PRICE_TIER_LABEL_RU = {
    adult: 'Взрослый',
    two_children: '2 ребенка',
    two_adults: '2 взрослых',
    adult_and_child: 'Взрослый + ребенок',
  };

  function getTg() {
    return global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null;
  }

  function getInitData() {
    var tg = getTg();
    return tg && tg.initData ? tg.initData : '';
  }

  function apiUrl(path, initData) {
    var cred = initData != null ? initData : getInitData();
    return path + (cred ? '?init_data=' + encodeURIComponent(cred) : '');
  }

  function authHeaders(initData, extra) {
    var h = extra ? Object.assign({}, extra) : {};
    var cred = initData != null ? initData : getInitData();
    if (cred) h['X-Telegram-Init-Data'] = cred;
    return h;
  }

  function parseBookingJsonResponse(text) {
    try {
      return JSON.parse(text || 'null');
    } catch (e) {
      return null;
    }
  }

  function newIdempotencyKey() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    return 'bk-' + Date.now() + '-' + Math.random().toString(36).slice(2, 9);
  }

  function priceTierLabelRu(tier) {
    var k = ((tier && tier.tier_kind) || '').toLowerCase();
    return PRICE_TIER_LABEL_RU[k] || (tier && tier.label) || 'Тариф';
  }

  /** Card / filter service wins over slot.service_id when both are in trainer.services. */
  function effectiveServiceIdForBooking(ctx) {
    ctx = ctx || {};
    var services = ctx.trainerServices || [];
    var allowed = {};
    var i;
    for (i = 0; i < services.length; i++) {
      var id = Number(services[i].service_id);
      if (!isNaN(id) && id > 0) allowed[id] = true;
    }
    if (ctx.filterServiceId != null) {
      var cur = Number(ctx.filterServiceId);
      if (!isNaN(cur) && cur > 0 && allowed[cur]) return cur;
    }
    if (ctx.selectedServiceId != null) {
      var sel = Number(ctx.selectedServiceId);
      if (!isNaN(sel) && sel > 0 && allowed[sel]) return sel;
    }
    if (ctx.slot && ctx.slot.service_id != null) {
      var ps = Number(ctx.slot.service_id);
      if (!isNaN(ps) && ps > 0 && allowed[ps]) return ps;
    }
    if (ctx.forceServiceChoice) return null;
    if (ctx.sessionServiceId != null) {
      var ss = Number(ctx.sessionServiceId);
      if (!isNaN(ss) && ss > 0 && allowed[ss]) return ss;
    }
    return null;
  }

  function getTiersForService(trainerServices, serviceId) {
    if (!trainerServices || serviceId == null) return [];
    var sid = Number(serviceId);
    var i;
    for (i = 0; i < trainerServices.length; i++) {
      if (Number(trainerServices[i].service_id) === sid) {
        return trainerServices[i].price_tiers || [];
      }
    }
    return [];
  }

  /** Prefer last-booking tier, then booking_context tier when service IDs match. */
  function priceVariantHint(ctx, effServiceId) {
    if (effServiceId == null) return null;
    var e = Number(effServiceId);
    if (!isFinite(e) || e <= 0) return null;
    var lcSid = ctx.lastCreatedBookingServiceId;
    var lcVid = ctx.lastCreatedBookingPriceVariantId;
    if (lcSid != null && Number(lcSid) === e && lcVid != null) {
      var v0 = Number(lcVid);
      if (isFinite(v0) && v0 > 0) return v0;
    }
    var bcSid = ctx.bookingContextServiceId;
    var bcVid = ctx.bookingContextServicePriceVariantId;
    if (bcSid != null && Number(bcSid) === e && bcVid != null) {
      var v1 = Number(bcVid);
      if (isFinite(v1) && v1 > 0) return v1;
    }
    return null;
  }

  function buildSlotsQueryParams(opts) {
    opts = opts || {};
    var q = { trainer_id: opts.trainerId };
    if (opts.serviceId != null) q.service_id = opts.serviceId;
    if (opts.arenaId != null && Number(opts.arenaId) > 0) q.arena_id = opts.arenaId;
    if (opts.weekStart) q.week_start = opts.weekStart;
    return q;
  }

  function slotsUrl(params, initData) {
    var parts = [];
    var k;
    for (k in params) {
      if (!Object.prototype.hasOwnProperty.call(params, k)) continue;
      if (params[k] == null || params[k] === '') continue;
      parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(String(params[k])));
    }
    return apiUrl('/api/webapp/client/slots' + (parts.length ? '?' + parts.join('&') : ''), initData);
  }

  function fetchClientSession(forTrainerId, initData) {
    var url = '/api/webapp/client/session';
    if (forTrainerId != null) url += '?for_trainer_id=' + encodeURIComponent(String(forTrainerId));
    return fetch(apiUrl(url, initData), {
      headers: authHeaders(initData),
    }).then(function (r) {
      if (!r.ok) throw new Error('session ' + r.status);
      return r.json();
    });
  }

  function fetchClientSlots(opts) {
    opts = opts || {};
    var params = buildSlotsQueryParams(opts);
    return fetch(slotsUrl(params, opts.initData), {
      headers: authHeaders(opts.initData),
    }).then(function (r) {
      if (!r.ok) throw new Error('slots ' + r.status);
      return r.json();
    });
  }

  function validateBookingForm(opts) {
    opts = opts || {};
    var phoneEl = opts.phoneEl;
    if (global.CrmPhoneField && phoneEl) {
      var phCheck = global.CrmPhoneField.validate(phoneEl);
      if (!phCheck.ok) {
        return { ok: false, error: phCheck.error || 'Укажите номер телефона.' };
      }
      var out = { ok: true, phone: phCheck.e164 };
      if (opts.needsProfileName) {
        var fn = (opts.firstName || '').trim();
        if (!fn) return { ok: false, error: 'Укажите имя' };
        out.firstName = fn;
        var ln = (opts.lastName || '').trim();
        if (ln) out.lastName = ln;
      }
      return out;
    }
    return { ok: false, error: 'Укажите номер телефона.' };
  }

  function buildBookingPayload(opts) {
    opts = opts || {};
    var body = {
      slot_id: opts.slotId,
      phone: opts.phone,
      comment: opts.comment || null,
    };
    if (opts.requestId != null) body.request_id = opts.requestId;
    else if (opts.serviceId != null) body.service_id = opts.serviceId;
    if (opts.priceVariantId != null) body.service_price_variant_id = opts.priceVariantId;
    if (opts.needsProfileName && opts.firstName) {
      body.first_name = opts.firstName;
      if (opts.lastName) body.last_name = opts.lastName;
    }
    return body;
  }

  function submitBooking(opts) {
    opts = opts || {};
    var initData = opts.initData != null ? opts.initData : getInitData();
    var headers = authHeaders(initData, { 'Content-Type': 'application/json' });
    if (opts.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;
    // Explicit acting profile for this booking (form override). Always set when known so a
    // race with the global fetch patch cannot drop X-Profile-Id.
    if (opts.profileId != null && opts.profileId !== '') {
      headers['X-Profile-Id'] = String(opts.profileId);
    }
    emitBookingAnalytics('booking_submitted', { slot_id: opts.body && opts.body.slot_id });
    return fetch(apiUrl('/api/webapp/client/booking', initData), {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(opts.body || {}),
    }).then(function (res) {
      return res.text().then(function (text) {
        return { res: res, data: parseBookingJsonResponse(text), text: text };
      });
    });
  }

  function formatPlaceMismatchNotice(slot) {
    if (!slot || !slot.place_mismatch) return '';
    var name = (slot.arena_name && String(slot.arena_name).trim()) || '';
    if (name) {
      return 'Занятие пройдёт на площадке «' + name + '», а не на арене, с которой вы открыли запись.';
    }
    return 'Место занятия отличается от арены, с которой вы открыли запись.';
  }

  function escSuccessHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  /**
   * TASK-096 AC-004 — момент первого успеха.
   *
   * Экран после первой записи отличается от экрана после пятидесятой, потому что
   * отличается сам человек: тот, кто записался впервые, не знает, сработало ли,
   * кто ответит и что будет дальше. Эта неизвестность и портит первый успех —
   * не отсутствие анимации. Поэтому «момент» — три честных факта о будущем.
   *
   * Каждый пункт выводится из базы (`is_first_booking`, `reminder_plan` приходят
   * с сервера). Ни одного придуманного: нет плана напоминаний — нет и строки
   * про напоминания, вместо неё не появляется утешительная неправда (AC-005).
   */
  function formatFirstBookingSuccess(data) {
    var steps = ['Тренер подтвердит запись — уведомление придёт сюда, в бот.'];
    var plan = data && data.reminder_plan ? String(data.reminder_plan).trim() : '';
    if (plan) {
      steps.push('Напомним о тренировке ' + escSuccessHtml(plan) + '.');
    }
    steps.push('Детали, адрес и отмена — всегда в «Моих записях».');

    return (
      '<div class="booking-first-success">' +
      '<p class="booking-first-success__title">Готово. Это ваша первая запись.</p>' +
      '<p class="booking-first-success__lede">Дальше всё делаем мы:</p>' +
      '<ol class="booking-first-success__steps">' +
      steps
        .map(function (line) {
          return '<li>' + line + '</li>';
        })
        .join('') +
      '</ol>' +
      '</div>'
    );
  }

  function formatSuccessMessage(data, opts) {
    opts = opts || {};
    var first = data && data.is_first_booking ? formatFirstBookingSuccess(data) : '';
    var main = first || '✅ <b>Вы записаны</b>.<br><br>Ожидайте подтверждения от тренера в боте.';
    var ctx = '';
    if (opts.requestId) {
      ctx =
        '<br><span class="booking-success-note">Запись связана с вашей заявкой и откликом тренера.</span>';
    }
    // Первый экран уже сказал, где живут детали и отмена, — повторять это ниже
    // значило бы дважды написать одно и то же на одном экране.
    var foot = first
      ? ''
      : '<br><span class="booking-success-note">Детали, адрес и отмена — в «Мои записи» в меню бота.</span>';
    return main + ctx + foot;
  }

  function hapticSuccess() {
    if (global.ClientShell && typeof global.ClientShell.hapticSuccess === 'function') {
      global.ClientShell.hapticSuccess();
      return;
    }
    var tg = getTg();
    if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.notificationOccurred === 'function') {
      try {
        tg.HapticFeedback.notificationOccurred('success');
      } catch (e) { /* WebView */ }
    }
  }

  /**
   * Unified full-screen booking success.
   * host: 'book' | 'catalog'
   */
  function showBookingSuccess(opts) {
    opts = opts || {};
    hapticSuccess();
    try {
      global.scrollTo(0, 0);
    } catch (e) { /* */ }

    emitBookingAnalytics('booking_step_viewed', { step: 'success', host: opts.host || 'unknown' });

    if (opts.host === 'book') {
      global.document.documentElement.classList.remove('book-slot-deeplink');
      global.document.body.classList.remove('book-slot-deeplink');
      global.document.documentElement.classList.add('book-booking-success', 'booking-screen-state--success');
      global.document.body.classList.add('book-booking-success', 'booking-screen-state--success');
      var slotsEl = global.document.getElementById('screenSlots');
      var formEl = global.document.getElementById('screenForm');
      var successEl = global.document.getElementById('screenSuccess');
      if (slotsEl) slotsEl.style.display = 'none';
      if (formEl) formEl.style.display = 'none';
      if (successEl) successEl.style.display = 'flex';
      var headerTitle = global.document.getElementById('headerTitle');
      if (headerTitle) headerTitle.textContent = '✅ Запись создана';
      var backBtn = global.document.getElementById('btnBack');
      if (backBtn) backBtn.hidden = true;
      if (opts.messageHtml) {
        var bodyEl = global.document.getElementById('successMsgBody');
        if (bodyEl) bodyEl.innerHTML = opts.messageHtml;
      }
      enableBookSuccessShell();
      return;
    }

    if (opts.host === 'catalog') {
      global.document.body.classList.add('booking-screen-state--success');
      if (opts.messageHtml) {
        var st = global.document.getElementById('successText');
        if (st) st.innerHTML = opts.messageHtml;
      }
      if (typeof opts.showScreen === 'function') {
        opts.showScreen('screenSuccess');
      }
    }
  }

  function enableBookSuccessShell() {
    var body = global.document.body;
    if (!body) return;
    if (!body.getAttribute('data-client-shell')) {
      body.setAttribute('data-client-shell', 'tabs');
    }
    if (global.ClientShell) {
      if (typeof global.ClientShell.init === 'function') global.ClientShell.init();
      if (typeof global.ClientShell.setForcedTab === 'function') global.ClientShell.setForcedTab('bookings');
      if (typeof global.ClientShell.setTabBarVisible === 'function') global.ClientShell.setTabBarVisible(true);
    }
  }

  function queryParam(query, key) {
    if (!query) return null;
    if (typeof query.get === 'function') return query.get(key);
    var v = query[key];
    return v == null ? null : String(v);
  }

  /**
   * Catalog header «Назад» on booking / slot-pick screens.
   * Hub nearest-slot (`from=hub&slot_id`) must return to hub — not an empty trainer tab.
   * Hub «book again» (`action=book`) still goes form → slot pick → hub.
   */
  function catalogFormBackAction(query, screenId) {
    var fromHub = queryParam(query, 'from') === 'hub';
    var slotRaw = queryParam(query, 'slot_id');
    var hasSlot = slotRaw != null && String(slotRaw).trim() !== '';
    var isBookAction = queryParam(query, 'action') === 'book';
    if (screenId === 'screenSlotPick' && fromHub && isBookAction) return 'hub';
    if (screenId === 'screenBookingForm' && fromHub && hasSlot) return 'hub';
    if (screenId === 'screenBookingForm' && fromHub && isBookAction) return 'slot-pick';
    if (screenId === 'screenBookingForm' || screenId === 'screenSlotPick') return 'trainer-detail';
    return null;
  }

  function escapePriceHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /** Amount + currency for HTML. BYN is letters — NBRB PUA glyph does not render in Telegram WebView. */
  function formatPriceAmountHtml(amount, currency) {
    if (amount == null) return escapePriceHtml('по запросу');
    var n = Number(amount);
    var num = n === Math.floor(n) ? String(n) : n.toFixed(2);
    if (currency === 'RUB') return escapePriceHtml(num) + ' ₽';
    return escapePriceHtml(num) + ' BYN';
  }

  function resolveBookingReturn(from, ctx) {
    ctx = ctx || {};
    if (from === 'hub') return { type: 'hub', path: 'client-home' };
    // Вход с карточки арены (`catalog?from=arena&...`). Раньше этой ветки не было,
    // и «Назад» с выбора времени уводило на неотрисованный экран карточки тренера —
    // человек, пришедший с арены, попадал на пустую страницу вместо арены.
    if (from === 'arena' && ctx.arenaId != null && ctx.arenaId !== '') {
      return { type: 'arena', path: 'arena?ref=' + encodeURIComponent(String(ctx.arenaId)) };
    }
    if (from === 'requests') return { type: 'shell', path: 'client-requests' };
    if (from === 'saved-trainers') return { type: 'shell', path: 'client-saved-trainers' };
    if (from === 'catalog' && ctx.trainerId) {
      return { type: 'catalog-trainer', path: 'catalog?trainer_id=' + encodeURIComponent(String(ctx.trainerId)) };
    }
    if (ctx.trainerId) {
      return { type: 'catalog-trainer', path: 'catalog?trainer_id=' + encodeURIComponent(String(ctx.trainerId)) };
    }
    return { type: 'catalog', path: 'ice?intent=coach' };
  }

  function navigateBookingReturn(from, ctx) {
    var target = resolveBookingReturn(from, ctx);
    if (target.type === 'hub' && typeof global.navigateClientHome === 'function') {
      global.navigateClientHome();
      return true;
    }
    if (global.ClientShell && typeof global.ClientShell.navigate === 'function') {
      global.ClientShell.navigate(target.path);
      return true;
    }
    var base = (global.location.pathname || '').replace(/[^/]+$/, '');
    var initData = getInitData();
    var url = base + target.path;
    if (initData) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
    global.location.href = url;
    return true;
  }

  function emitBookingAnalytics(event, props) {
    try {
      global.dispatchEvent(
        new CustomEvent('booking:funnel', { detail: { event: event, props: props || {}, ts: Date.now() } })
      );
    } catch (e) { /* CustomEvent unsupported */ }
  }

  function mountFadeIn(el) {
    if (!el) return;
    el.classList.add('booking-mount');
    requestAnimationFrame(function () {
      el.classList.add('booking-mount--visible');
    });
  }

  global.BookingClient = {
    parseBookingJsonResponse: parseBookingJsonResponse,
    newIdempotencyKey: newIdempotencyKey,
    priceTierLabelRu: priceTierLabelRu,
    effectiveServiceIdForBooking: effectiveServiceIdForBooking,
    getTiersForService: getTiersForService,
    priceVariantHint: priceVariantHint,
    buildSlotsQueryParams: buildSlotsQueryParams,
    slotsUrl: slotsUrl,
    fetchClientSession: fetchClientSession,
    fetchClientSlots: fetchClientSlots,
    validateBookingForm: validateBookingForm,
    buildBookingPayload: buildBookingPayload,
    submitBooking: submitBooking,
    formatPlaceMismatchNotice: formatPlaceMismatchNotice,
    formatSuccessMessage: formatSuccessMessage,
    formatFirstBookingSuccess: formatFirstBookingSuccess,
    showBookingSuccess: showBookingSuccess,
    catalogFormBackAction: catalogFormBackAction,
    formatPriceAmountHtml: formatPriceAmountHtml,
    resolveBookingReturn: resolveBookingReturn,
    navigateBookingReturn: navigateBookingReturn,
    hapticSuccess: hapticSuccess,
    emitBookingAnalytics: emitBookingAnalytics,
    mountFadeIn: mountFadeIn,
    getInitData: getInitData,
  };
})(typeof window !== 'undefined' ? window : this);
