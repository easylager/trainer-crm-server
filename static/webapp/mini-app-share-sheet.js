/**
 * Шит «Поделиться» (TASK-146, DEC-004 / DEC-013).
 *
 * Один компонент на все места мини-аппа, где делятся местом: карточка арены сейчас,
 * дальше — строки каталога и хаб. Делится не ботом, а публичной страницей места
 * (/p/{city}/{slug}): у неё своё превью, и она открывается в любом мессенджере.
 *
 * Что внутри и почему:
 *  - переключатель «Расписание / Позвать с собой» — один и тот же факт, разный тон
 *    (объявление vs. вопрос другу). Тексты обоих приходят одним запросом;
 *  - выбор сеанса — делятся конкретным временем, а не «приходи как-нибудь»;
 *  - превью — та самая картинка, которую увидит друг. Человек видит результат до
 *    отправки — и охотнее отправляет;
 *  - четыре канала: Telegram · Ссылка (в Viber/WhatsApp/«Избранное») · Картинка
 *    (истории Instagram/VK — у них нет API «опубликовать») · Другое (системное меню).
 *
 * Счётчик честный: переключатели и превью идут с record=false, событие пишется только
 * по нажатию канала (с каналом) — см. GET /api/public/arenas/{ref}/share.
 *
 * API:  GlideShareSheet.open({ ref, slots, sessionId, invite, context, venueType })
 *       slots — [{ id, label }], ближайшие сеансы (необязательно).
 */
(function (global) {
  'use strict';

  var state = null;
  var root = null;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function tg() {
    return global.Telegram && global.Telegram.WebApp;
  }

  function haptic() {
    try {
      var t = tg();
      if (t && t.HapticFeedback) t.HapticFeedback.selectionChanged();
    } catch (e) { /* */ }
  }

  function endpoint(extra) {
    if (state.endpoint) {
      // Подборка (/api/public/ice/selection/share?…): свой URL с фильтрами, без сеанса и тона.
      var tail = Object.keys(extra || {})
        .map(function (k) { return k + '=' + encodeURIComponent(String(extra[k])); })
        .join('&');
      var sep = state.endpoint.indexOf('?') >= 0 ? '&' : '?';
      return state.endpoint + sep + 'share_context=' + encodeURIComponent(state.context || 'ice_list') +
        (tail ? '&' + tail : '');
    }
    var q = ['share_context=' + encodeURIComponent(state.context || 'arena_card')];
    if (state.sessionId) q.push('session_id=' + encodeURIComponent(String(state.sessionId)));
    if (state.invite) q.push('invite=true');
    Object.keys(extra || {}).forEach(function (k) {
      q.push(k + '=' + encodeURIComponent(String(extra[k])));
    });
    return '/api/public/arenas/' + encodeURIComponent(String(state.ref)) + '/share?' + q.join('&');
  }

  function fetchPayload(extra) {
    return fetch(endpoint(extra), { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    });
  }

  /** Событие шеринга — по нажатию канала. Ошибка счётчика не мешает отправке. */
  function track(channel) {
    try {
      fetch(endpoint({ channel: channel }), { cache: 'no-store', keepalive: true }).catch(function () {});
    } catch (e) { /* */ }
  }

  function toast(text) {
    var el = root && root.querySelector('.gss-toast');
    if (!el) return;
    el.textContent = text;
    el.classList.add('is-on');
    global.clearTimeout(toast._t);
    toast._t = global.setTimeout(function () { el.classList.remove('is-on'); }, 1800);
  }

  function fullMessage(p) {
    var body = String(p.share_body || '').trim();
    var url = String(p.share_url || '').trim();
    return body ? body + '\n' + url : url;
  }

  function openUrl(url) {
    var t = tg();
    if (t && typeof t.openLink === 'function') {
      try {
        t.openLink(url);
        return;
      } catch (e) { /* */ }
    }
    global.open(url, '_blank', 'noopener');
  }

  var CHANNELS = {
    telegram: function (p) {
      var opened = false;
      if (typeof global.openTelegramShareUrlFromMiniApp === 'function') {
        opened = global.openTelegramShareUrlFromMiniApp({ shareUrl: p.share_url, shareBody: p.share_body });
      }
      if (!opened) {
        openUrl(
          'https://t.me/share/url?url=' + encodeURIComponent(p.share_url) +
          (p.share_body ? '&text=' + encodeURIComponent(p.share_body) : '')
        );
      }
    },
    copy: function (p) {
      var text = fullMessage(p);
      var done = function () { toast('Скопировано — вставьте в Viber, WhatsApp или любой чат'); };
      if (global.navigator && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { global.prompt('Скопируйте:', text); });
      } else {
        global.prompt('Скопируйте:', text);
      }
    },
    story: function (p) {
      var t = tg();
      var url = p.story_image_url;
      // Bot API 8.0: нативное «Сохранить файл». Старые клиенты — открываем картинку.
      if (t && typeof t.downloadFile === 'function' && (!t.isVersionAtLeast || t.isVersionAtLeast('8.0'))) {
        try {
          t.downloadFile({ url: url, file_name: 'glide-' + (state.ref || 'place') + '.png' });
          return;
        } catch (e) { /* fall through */ }
      }
      openUrl(url);
    },
    system: function (p) {
      if (global.navigator && typeof navigator.share === 'function') {
        navigator.share({ text: p.share_body, url: p.share_url }).catch(function () {});
        return;
      }
      // Нет системного меню (Telegram Desktop и т.п.) — открываем страницу места:
      // на ней кнопки Viber, WhatsApp, VK и «Скопировать».
      openUrl(p.share_url);
    },
  };

  /** Превью грузим с того же origin: в абсолютном URL — публичный домен, а мини-апп
      может жить на другом (staging, локально). Путь у картинки тот же. */
  function sameOriginPath(url) {
    try {
      var u = new URL(url, global.location.href);
      return u.pathname + u.search;
    } catch (e) {
      return url;
    }
  }

  function slotList() {
    var sections = state.slotSections;
    var slots = state.slots || [];
    if (!sections || !sections.length) {
      if (!slots.length) return '';
      sections = [{ dayLabel: '', rows: slots.map(function (s) {
        var m = String(s.label || '').match(/(\d{1,2}:\d{2})\s*$/);
        return { id: s.id, time: m ? m[1] : s.label, meta: '' };
      }) }];
    }
    var html =
      '<p class="gss-slot-q">На какое время зовём?</p>' +
      '<div class="gss-slot-list" role="listbox" aria-label="Сеанс">';
    sections.forEach(function (sec) {
      if (sec.dayLabel) html += '<p class="gss-slot-day">' + esc(sec.dayLabel) + '</p>';
      (sec.rows || []).forEach(function (row) {
        var on = String(row.id) === String(state.sessionId);
        var meta = row.meta || '';
        if (on) meta = meta ? meta + ' · выбрано' : 'Выбрано';
        html +=
          '<button type="button" class="gss-slot-row' + (on ? ' is-on' : '') + '" data-slot="' + esc(row.id) + '"' +
          ' aria-pressed="' + (on ? 'true' : 'false') + '">' +
          '<span>' + esc(row.time) + '</span><em>' + esc(meta) + '</em></button>';
      });
    });
    html += '</div>';
    if (state.ref && !state.endpoint && slots.length <= 1 && typeof state.loadSlots === 'function') {
      html +=
        '<button type="button" class="gss-more-slots" data-gss-load-slots>Загрузить расписание</button>';
    }
    return html;
  }

  function sessionPicker() {
    if (state.endpoint) return '';
    if (!state.invite) return '';
    return slotList();
  }

  function render() {
    var p = state.payload;
    var isIce = (state.venueType || 'ice') === 'ice';
    var preview = p && p.og_image_url
      ? '<img class="gss-preview__img" src="' + esc(sameOriginPath(p.og_image_url)) + '" alt="Так ссылку увидят в чате" loading="eager" />'
      : '<div class="gss-preview__img gss-preview__img--wait"></div>';
    var tabs = state.endpoint
      ? ''
      : '<div class="gss-tabs" role="group" aria-label="Тон">' +
        '<button type="button" class="gss-tab' + (!state.invite ? ' is-on' : '') + '" data-invite="0">' +
        (isIce ? 'Расписание' : 'Место') + '</button>' +
        '<button type="button" class="gss-tab' + (state.invite ? ' is-on' : '') + '" data-invite="1">Позвать с собой</button>' +
        '</div>';
    root.querySelector('.gss-body').innerHTML =
      tabs +
      sessionPicker() +
      '<figure class="gss-preview">' + preview +
      '<figcaption>' + esc(p ? p.share_body : 'Готовим карточку…') + '</figcaption></figure>' +
      '<div class="gss-channels">' +
      '<button type="button" class="gss-ch gss-ch--tg" data-ch="telegram"' + (p ? '' : ' disabled') + '>Telegram</button>' +
      '<button type="button" class="gss-ch" data-ch="copy"' + (p ? '' : ' disabled') + '>Ссылка</button>' +
      '<button type="button" class="gss-ch" data-ch="story"' + (p ? '' : ' disabled') + '>Картинка</button>' +
      '<button type="button" class="gss-ch" data-ch="system"' + (p ? '' : ' disabled') + '>Другое</button>' +
      '</div>' +
      '<p class="gss-note">Друзья увидят время, цену и адрес — без приложения и регистрации.</p>';
  }

  function reload() {
    state.payload = null;
    render();
    var token = (state.token = (state.token || 0) + 1);
    fetchPayload({ record: 'false' })
      .then(function (data) {
        if (token !== state.token) return;
        state.payload = data;
        render();
      })
      .catch(function () {
        if (token !== state.token) return;
        root.querySelector('.gss-body').innerHTML =
          '<p class="gss-note">Не получилось подготовить ссылку. Проверьте связь и попробуйте ещё раз.</p>';
      });
  }

  function onClick(ev) {
    if (ev.target === root || ev.target.closest('[data-gss-close]')) {
      close();
      return;
    }
    var tab = ev.target.closest('[data-invite]');
    if (tab) {
      var invite = tab.getAttribute('data-invite') === '1';
      if (invite !== state.invite) {
        haptic();
        state.invite = invite;
        // Тексты обоих тонов уже в ответе — второй запрос нужен только ради картинки.
        reload();
      }
      return;
    }
    var slot = ev.target.closest('[data-slot]');
    if (slot) {
      haptic();
      state.sessionId = slot.getAttribute('data-slot');
      reload();
      return;
    }
    if (ev.target.closest('[data-gss-load-slots]') && typeof state.loadSlots === 'function') {
      haptic();
      state.loadSlots().then(function (more) {
        if (!more) return;
        if (Array.isArray(more)) {
          state.slots = more;
        } else {
          state.slots = more.slots || [];
          state.slotSections = more.slotSections || null;
        }
        if (!state.sessionId && state.slots[0]) state.sessionId = state.slots[0].id;
        reload();
      });
      return;
    }
    var ch = ev.target.closest('[data-ch]');
    if (ch && state.payload) {
      var name = ch.getAttribute('data-ch');
      track(name);
      CHANNELS[name](state.payload);
    }
  }

  function ensureRoot() {
    if (root) return root;
    root = document.createElement('div');
    root.className = 'gss';
    root.hidden = true;
    root.innerHTML =
      '<div class="gss-sheet" role="dialog" aria-modal="true" aria-label="Поделиться">' +
      '<div class="gss-head"><b>Поделиться</b>' +
      '<button type="button" class="gss-x" data-gss-close aria-label="Закрыть">✕</button></div>' +
      '<div class="gss-body"></div>' +
      '</div>' +
      '<div class="gss-toast" role="status" aria-live="polite"></div>';
    root.addEventListener('click', onClick);
    document.body.appendChild(root);
    return root;
  }

  function open(opts) {
    opts = opts || {};
    if ((opts.ref == null || opts.ref === '') && !opts.endpoint) return;
    ensureRoot();
    state = {
      ref: opts.ref,
      endpoint: opts.endpoint || null,
      slots: opts.slots || [],
      slotSections: opts.slotSections || null,
      sessionId: opts.sessionId || (opts.slots && opts.slots[0] && opts.slots[0].id) || null,
      invite: !!opts.invite,
      context: opts.context || 'arena_card',
      venueType: opts.venueType || 'ice',
      loadSlots: opts.loadSlots || null,
      payload: null,
    };
    root.hidden = false;
    global.requestAnimationFrame(function () { root.classList.add('is-open'); });
    reload();
  }

  function close() {
    if (!root) return;
    root.classList.remove('is-open');
    global.setTimeout(function () { if (root) root.hidden = true; }, 180);
  }

  global.GlideShareSheet = { open: open, close: close };
})(window);
