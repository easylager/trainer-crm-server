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
 *  - каналы: Telegram · Ссылка · Сторис · В галерею (картинка для сторис/поста) · Другое.
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

  function absoluteMediaUrl(url) {
    try {
      return new URL(String(url || ''), global.location.href).href;
    } catch (e) {
      return String(url || '');
    }
  }

  function copyText(text, done) {
    var s = String(text || '').trim();
    if (!s) {
      if (done) done();
      return;
    }
    if (global.navigator && navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(s).then(function () { if (done) done(); }, function () { if (done) done(); });
    } else if (done) {
      done();
    }
  }

  /** @returns {boolean} */
  function tryShareToStory(p) {
    var t = tg();
    if (!t || typeof t.shareToStory !== 'function') return false;
    if (t.isVersionAtLeast && !t.isVersionAtLeast('7.8')) return false;
    var media = absoluteMediaUrl(p.story_image_url);
    if (!/^https:\/\//i.test(media)) return false;
    var params = {};
    var caption = String(p.share_body || '').trim();
    if (caption) params.text = caption.slice(0, 200);
    var link = String(p.share_url || '').trim();
    if (link) params.widget_link = { url: link, name: 'Карта льда' };
    try {
      t.shareToStory(media, params);
      return true;
    } catch (e) {
      return false;
    }
  }

  /** @returns {Promise<boolean>} */
  function tryShareStoryFile(p) {
    return new Promise(function (resolve) {
      var nav = global.navigator;
      if (!nav || typeof nav.share !== 'function' || typeof nav.canShare !== 'function') {
        resolve(false);
        return;
      }
      var fetchUrl = sameOriginPath(p.story_image_url);
      fetch(fetchUrl, { cache: 'no-store' })
        .then(function (r) {
          if (!r.ok) throw new Error('http');
          return r.blob();
        })
        .then(function (blob) {
          var file = new File([blob], 'glide-story.png', { type: 'image/png' });
          var payload = { files: [file] };
          if (!nav.canShare(payload)) {
            resolve(false);
            return;
          }
          copyText(p.share_url, function () {
            nav.share(payload).then(
              function () { resolve(true); },
              function () { resolve(false); }
            );
          });
        })
        .catch(function () { resolve(false); });
    });
  }

  function cardImagePayload(p) {
    var raw = (p && (p.story_image_url || p.og_image_url)) || '';
    return {
      fetchPath: raw ? sameOriginPath(raw) : '',
      absolute: raw ? absoluteMediaUrl(raw) : '',
      fileName: p && p.story_image_url ? 'glide-story.png' : 'glide-share.png',
    };
  }

  /** @returns {boolean} */
  function tryTelegramDownloadFile(absoluteUrl, fileName) {
    var t = tg();
    var media = String(absoluteUrl || '');
    if (!t || typeof t.downloadFile !== 'function') return false;
    if (t.isVersionAtLeast && !t.isVersionAtLeast('8.0')) return false;
    if (!/^https:\/\//i.test(media)) return false;
    try {
      t.downloadFile({ url: media, file_name: fileName || 'glide-share.png' });
      return true;
    } catch (e) {
      return false;
    }
  }

  /** @returns {Promise<boolean>} */
  function tryBlobDownload(fetchPath, fileName) {
    return fetch(fetchPath, { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('http');
        return r.blob();
      })
      .then(function (blob) {
        var objectUrl = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = objectUrl;
        a.download = fileName || 'glide-share.png';
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        a.remove();
        global.setTimeout(function () {
          URL.revokeObjectURL(objectUrl);
        }, 2000);
        return true;
      })
      .catch(function () {
        return false;
      });
  }

  /**
   * Сохранить картинку карточки (вертикаль для сторис, если есть) в файлы / галерею.
   * @returns {Promise<string>} image_tg | image_os | image_fallback | image_empty
   */
  function openImageSave(p) {
    return new Promise(function (resolve) {
      var img = cardImagePayload(p);
      if (!img.fetchPath) {
        toast('Картинка ещё не готова');
        resolve('image_empty');
        return;
      }
      if (tryTelegramDownloadFile(img.absolute, img.fileName)) {
        toast('Сохраняем в «Загрузки» — оттуда в сторис или галерею');
        resolve('image_tg');
        return;
      }
      tryBlobDownload(img.fetchPath, img.fileName).then(function (ok) {
        if (ok) {
          toast('Сохранено — проверьте «Файлы» или папку загрузок');
          resolve('image_os');
          return;
        }
        copyText(p.share_url, function () {
          openUrl(img.absolute);
          toast('Ссылка в буфере — удержите картинку и «Сохранить в Фото»');
          resolve('image_fallback');
        });
      });
    });
  }

  /** @returns {boolean} */
  function tryDownloadStoryFile(p) {
    var img = cardImagePayload(p);
    return tryTelegramDownloadFile(img.absolute, img.fileName);
  }

  /**
   * Сторис: TG → системный share с файлом → download / открыть картинку.
   * @returns {Promise<string>} канал для telemetry: story_tg | story_os | story_fallback
   */
  function openStoryShare(p) {
    return new Promise(function (resolve) {
      if (tryShareToStory(p)) {
        toast('Откройте редактор истории Telegram');
        resolve('story_tg');
        return;
      }
      tryShareStoryFile(p).then(function (shared) {
        if (shared) {
          toast('Ссылка в буфере — добавьте стикером в Instagram');
          resolve('story_os');
          return;
        }
        copyText(p.share_url, function () {
          if (tryDownloadStoryFile(p)) {
            toast('Ссылка в буфере — добавьте стикер ссылки в сторис');
            resolve('story_fallback');
            return;
          }
          openUrl(absoluteMediaUrl(p.story_image_url));
          toast('Ссылка в буфере — сохраните картинку из просмотра');
          resolve('story_fallback');
        });
      });
    });
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
      openStoryShare(p).then(function (channel) {
        track(channel);
      });
    },
    image: function (p) {
      openImageSave(p).then(function (channel) {
        if (channel !== 'image_empty') track(channel);
      });
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

  function normalizedSections() {
    var sections = state.slotSections;
    var slots = state.slots || [];
    if (sections && sections.length) return sections;
    if (!slots.length) return [];
    return [
      {
        dayLabel: '',
        localDate: '',
        dayNum: '',
        rows: slots.map(function (s) {
          var m = String(s.label || '').match(/(\d{1,2}:\d{2})\s*$/);
          return { id: s.id, time: m ? m[1] : s.label, meta: '' };
        }),
      },
    ];
  }

  function ensureSlotDay() {
    var sections = normalizedSections();
    if (!sections.length) {
      state.slotDay = null;
      return;
    }
    if (state.slotDay && sections.some(function (s) { return s.localDate === state.slotDay; })) return;
    if (state.sessionId) {
      for (var i = 0; i < sections.length; i++) {
        var sec = sections[i];
        if ((sec.rows || []).some(function (r) { return String(r.id) === String(state.sessionId); })) {
          state.slotDay = sec.localDate || null;
          return;
        }
      }
    }
    state.slotDay = sections[0].localDate || null;
  }

  function activeSlotSection() {
    var sections = normalizedSections();
    if (!sections.length) return null;
    if (state.slotDay) {
      for (var i = 0; i < sections.length; i++) {
        if (sections[i].localDate === state.slotDay) return sections[i];
      }
    }
    return sections[0];
  }

  function slotDayStripHtml(sections) {
    if (!sections.length || !sections[0].localDate) return '';
    return (
      '<div class="gss-day-strip" role="tablist" aria-label="День">' +
      sections
        .map(function (sec) {
          var on = sec.localDate === state.slotDay;
          var count = (sec.rows || []).length;
          return (
            '<button type="button" role="tab" class="gss-day-strip__day' +
            (on ? ' is-on' : '') +
            '" data-gss-day="' +
            esc(sec.localDate) +
            '" aria-pressed="' +
            (on ? 'true' : 'false') +
            '">' +
            '<span>' +
            esc(sec.dayLabel) +
            '</span><b>' +
            esc(sec.dayNum) +
            '</b><i>' +
            esc(String(count)) +
            '</i></button>'
          );
        })
        .join('') +
      '</div>'
    );
  }

  function slotRowsHtml(sec) {
    if (!sec) return '';
    var html = '<div class="gss-slot-list" role="listbox" aria-label="Сеанс">';
    (sec.rows || []).forEach(function (row) {
      var on = String(row.id) === String(state.sessionId);
      var meta = row.meta || '';
      if (on) meta = meta ? meta + ' · выбрано' : 'Выбрано';
      html +=
        '<button type="button" class="gss-slot-row' +
        (on ? ' is-on' : '') +
        '" data-slot="' +
        esc(row.id) +
        '"' +
        ' aria-pressed="' +
        (on ? 'true' : 'false') +
        '">' +
        '<span>' +
        esc(row.time) +
        '</span><em>' +
        esc(meta) +
        '</em></button>';
    });
    html += '</div>';
    return html;
  }

  function slotList() {
    var sections = normalizedSections();
    var slots = state.slots || [];
    if (!sections.length) return '';
    ensureSlotDay();
    var html = '<p class="gss-slot-q">На какое время зовём?</p>' + slotDayStripHtml(sections) + slotRowsHtml(activeSlotSection());
    if (state.ref && !state.endpoint && slots.length <= 1 && typeof state.loadSlots === 'function') {
      html += '<button type="button" class="gss-more-slots" data-gss-load-slots>Загрузить расписание</button>';
    }
    return '<div class="gss-slot-picker">' + html + '</div>';
  }

  function sessionPicker() {
    if (state.endpoint) return '';
    if (!state.invite) return '';
    return slotList();
  }

  function renderPreview(p) {
    if (!p || !p.og_image_url) {
      return '<div class="gss-preview__img gss-preview__img--wait"></div>';
    }
    var og =
      '<button type="button" class="gss-preview-save" data-gss-save-image aria-label="Сохранить картинку в галерею">' +
      '<img class="gss-preview__img" src="' +
      esc(sameOriginPath(p.og_image_url)) +
      '" alt="Так ссылку увидят в чате" loading="eager" /></button>';
    if (state.endpoint && p.story_image_url) {
      var story =
        '<img class="gss-preview__img gss-preview__img--story" src="' +
        esc(sameOriginPath(p.story_image_url)) +
        '" alt="Картинка для сторис" loading="eager" />';
      return (
        '<div class="gss-preview-duo">' +
        '<div class="gss-preview-duo__col"><span class="gss-preview-duo__tag">Чат</span>' +
        og +
        '</div>' +
        '<div class="gss-preview-duo__col"><span class="gss-preview-duo__tag">Сторис</span>' +
        story +
        '</div></div>'
      );
    }
    return og;
  }

  function renderTabsHtml() {
    var isIce = (state.venueType || 'ice') === 'ice';
    if (state.endpoint) return '';
    return (
      '<div class="gss-tabs" role="group" aria-label="Тон">' +
      '<button type="button" class="gss-tab' +
      (!state.invite ? ' is-on' : '') +
      '" data-invite="0">' +
      (isIce ? 'Расписание' : 'Место') +
      '</button>' +
      '<button type="button" class="gss-tab' +
      (state.invite ? ' is-on' : '') +
      '" data-invite="1">Позвать с собой</button>' +
      '</div>'
    );
  }

  function renderChannelsHtml(p) {
    return (
      '<div class="gss-channels">' +
      '<button type="button" class="gss-ch gss-ch--tg" data-ch="telegram"' +
      (p ? '' : ' disabled') +
      '>Telegram</button>' +
      '<button type="button" class="gss-ch" data-ch="copy"' +
      (p ? '' : ' disabled') +
      '>Ссылка</button>' +
      '<button type="button" class="gss-ch' +
      (state.endpoint ? ' gss-ch--story' : '') +
      '" data-ch="story"' +
      (p ? '' : ' disabled') +
      '>Сторис</button>' +
      '<button type="button" class="gss-ch gss-ch--image" data-ch="image"' +
      (p ? '' : ' disabled') +
      '>В галерею</button>' +
      '<button type="button" class="gss-ch" data-ch="system"' +
      (p ? '' : ' disabled') +
      '>Другое</button>' +
      '</div>'
    );
  }

  function renderPreviewFigureHtml(p) {
    return (
      '<figure class="gss-preview">' +
      renderPreview(p) +
      '<figcaption>' +
      esc(p ? p.share_body : 'Готовим карточку…') +
      '</figcaption></figure>'
    );
  }

  function paintBody() {
    root.querySelector('.gss-body').innerHTML =
      renderTabsHtml() +
      sessionPicker() +
      '<div class="gss-preview-host">' +
      renderPreviewFigureHtml(state.payload) +
      '</div>' +
      '<div class="gss-channels-host">' +
      renderChannelsHtml(state.payload) +
      '</div>' +
      '<p class="gss-note">В чат — Telegram или Ссылка. «В галерею» — картинка для сторис (вертикаль, если есть). Ссылку для стикера копируем сами.</p>';
  }

  function paintSlotPicker() {
    ensureSlotDay();
    var html = sessionPicker();
    var host = root.querySelector('.gss-slot-picker');
    if (!host) {
      if (html) paintBody();
      return;
    }
    if (!html) {
      host.remove();
      return;
    }
    host.outerHTML = html;
  }

  function paintPreviewBlock() {
    var previewHost = root.querySelector('.gss-preview-host');
    var channelsHost = root.querySelector('.gss-channels-host');
    if (!previewHost || !channelsHost) {
      paintBody();
      return;
    }
    previewHost.innerHTML = renderPreviewFigureHtml(state.payload);
    channelsHost.innerHTML = renderChannelsHtml(state.payload);
  }

  function reloadPreview() {
    state.payload = null;
    paintPreviewBlock();
    var token = (state.token = (state.token || 0) + 1);
    fetchPayload({ record: 'false' })
      .then(function (data) {
        if (token !== state.token) return;
        state.payload = data;
        paintPreviewBlock();
      })
      .catch(function () {
        if (token !== state.token) return;
        root.querySelector('.gss-body').innerHTML =
          '<p class="gss-note">Не получилось подготовить ссылку. Проверьте связь и попробуйте ещё раз.</p>';
      });
  }

  function reload() {
    state.payload = null;
    paintBody();
    reloadPreview();
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
    var dayBtn = ev.target.closest('[data-gss-day]');
    if (dayBtn) {
      var iso = dayBtn.getAttribute('data-gss-day');
      if (iso && iso !== state.slotDay) {
        haptic();
        state.slotDay = iso;
        paintSlotPicker();
      }
      return;
    }
    var slot = ev.target.closest('[data-slot]');
    if (slot) {
      haptic();
      state.sessionId = slot.getAttribute('data-slot');
      paintSlotPicker();
      reloadPreview();
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
        state.slotDay = null;
        reload();
      });
      return;
    }
    if (ev.target.closest('[data-gss-save-image]') && state.payload) {
      haptic();
      CHANNELS.image(state.payload);
      return;
    }
    var ch = ev.target.closest('[data-ch]');
    if (ch && state.payload) {
      var name = ch.getAttribute('data-ch');
      if (name === 'story' || name === 'image') {
        CHANNELS[name](state.payload);
        return;
      }
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
      slotDay: null,
      invite: !!opts.invite,
      context: opts.context || 'arena_card',
      venueType: opts.venueType || 'ice',
      loadSlots: opts.loadSlots || null,
      payload: null,
    };
    ensureSlotDay();
    root.hidden = false;
    global.requestAnimationFrame(function () { root.classList.add('is-open'); });
    reload();
  }

  function close() {
    if (!root) return;
    root.classList.remove('is-open');
    global.setTimeout(function () { if (root) root.hidden = true; }, 180);
  }

  global.GlideShareSheet = {
    open: open,
    close: close,
    _openStoryShare: openStoryShare,
    _openImageSave: openImageSave,
  };
})(window);
