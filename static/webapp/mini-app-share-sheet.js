/**
 * Шит «Поделиться» (TASK-146, DEC-004 / DEC-013).
 *
 * Один компонент на все места мини-аппа, где делятся местом: карточка арены сейчас,
 * дальше — строки каталога и хаб. Делится не ботом, а публичной страницей места
 * (/p/{city}/{slug}): у неё своё превью, и она открывается в любом мессенджере.
 *
 * Что внутри и почему:
 *  - переключатель варианта. У катка: «Погнали кататься», «Компания», «Открытка», «Расписание».
 *    «Компания» есть только когда сбор включён для города. У остальных мест — «Место» и «Позвать с собой».
 *    Тексты ссылки приходят одним запросом;
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

  /** TASK-254: пустой WebApp без initData — сайт в браузере, не Mini App. */
  function isTelegramMiniApp() {
    var t = tg();
    var initData = t && t.initData;
    return !!(initData && String(initData).length > 0);
  }

  /** В браузере «Сторис» только при Web Share с файлом; в Telegram — как раньше. */
  function browserStoryShareAvailable() {
    var nav = global.navigator;
    if (!nav || typeof nav.share !== 'function' || typeof nav.canShare !== 'function') return false;
    try {
      var probe = new File(['x'], 'probe.png', { type: 'image/png' });
      return nav.canShare({ files: [probe] });
    } catch (e) {
      return false;
    }
  }

  function storyChannelVisible() {
    return isTelegramMiniApp() || browserStoryShareAvailable();
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

  /**
   * Креденшл Mini App, если он есть. Тот же заголовок, что authHeaders в
   * booking-client.js и MiniAppRuntime.authHeaders: вне Telegram запрос уходит без него.
   */
  function shareRequestHeaders() {
    var rt = global.MiniAppRuntime;
    if (rt && typeof rt.authHeaders === 'function') return rt.authHeaders() || {};
    var tg = global.Telegram && global.Telegram.WebApp;
    var cred = tg && tg.initData ? String(tg.initData) : '';
    return cred ? { 'X-Telegram-Init-Data': cred } : {};
  }

  var CARD_WEEKDAYS = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
  var CARD_MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

  function postcardReady(sheetState) {
    if (!sheetState || sheetState.endpoint) return false;
    if ((sheetState.venueType || 'ice') !== 'ice') return false;
    return sheetState.sessionId != null && String(sheetState.sessionId).trim() !== '';
  }

  function postcardVia(sheetState) {
    return sheetState && sheetState.context === 'ice_list' ? 'ice_list' : 'arena_card';
  }

  function placeNameFromShare(body) {
    var line = String(body || '').split('\n')[0].trim();
    var at = line.indexOf(' — ');
    if (at <= 0) return '';
    return line.slice(0, at).trim();
  }

  function shortCardDate(iso) {
    var parts = String(iso || '').split('-');
    if (parts.length < 3 || !parts[0]) return '';
    var date = new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2])));
    if (isNaN(date.getTime())) return '';
    return CARD_WEEKDAYS[date.getUTCDay()] + ', ' + date.getUTCDate() + ' ' + CARD_MONTHS[date.getUTCMonth()];
  }

  function sectionsOf(sheetState) {
    if (!sheetState) return [];
    if (sheetState.slotSections && sheetState.slotSections.length) return sheetState.slotSections;
    var slots = sheetState.slots || [];
    if (!slots.length) return [];
    return [
      {
        dayLabel: '',
        localDate: '',
        dayNum: '',
        rows: slots.map(function (s) {
          var m = String(s.label || '').match(/(\d{1,2}:\d{2})\s*$/);
          return { id: s.id, time: m ? m[1] : s.label, meta: s.meta || '' };
        }),
      },
    ];
  }

  function selectedPostcardSlot(sheetState) {
    if (!sheetState || sheetState.sessionId == null || String(sheetState.sessionId).trim() === '') return null;
    var want = String(sheetState.sessionId);
    var sections = sectionsOf(sheetState);
    var i;
    var j;
    for (i = 0; i < sections.length; i++) {
      var rows = sections[i].rows || [];
      for (j = 0; j < rows.length; j++) {
        if (String(rows[j].id) === want) return { section: sections[i], row: rows[j] };
      }
    }
    return null;
  }

  function rinkName(sheetState) {
    if (!sheetState) return '';
    if (sheetState.placeName) return String(sheetState.placeName);
    var payload = sheetState.payload;
    return placeNameFromShare(payload && payload.place_share_body);
  }

  function postcardInput(sheetState) {
    var picked = selectedPostcardSlot(sheetState);
    var row = picked && picked.row;
    var meta = row ? String(row.meta || '') : '';
    var day = '';
    if (picked && picked.section) {
      day = shortCardDate(picked.section.localDate);
      if (!day && picked.section.dayLabel) {
        day = picked.section.dayLabel + (picked.section.dayNum ? ' ' + picked.section.dayNum : '');
      }
    }
    var z = (sheetState && sheetState.zovi) || {};
    return {
      toName: z.to || '',
      fromName: z.from || '',
      kind: (row && row.kind) || (meta.indexOf('ОХМ') !== -1 ? 'hockey_practice' : 'public_skate'),
      time: row && row.time ? String(row.time) : '',
      day: day,
      place: rinkName(sheetState),
    };
  }

  var ZOVI_FROM_KEY = 'zovi_from';
  /* Открытка грузится по требованию: бюджет веса каталога (test_webapp_page_weight_budget). */
  var ZOVI_SCRIPTS = [
    '/static/shared/zovi-model.js?v=15',
    '/static/shared/zovi-create.js?v=15',
    '/static/shared/zovi-live.js?v=15',
  ];
  var zoviLoading = null;

  function zoviLoaded() {
    return !!(global.ZoviModel && global.ZoviCreate && global.ZoviLive);
  }

  /* fetch с заголовком: бесплатный ngrok иначе отдаёт телефону HTML вместо JS. */
  function loadScript(src) {
    return fetch(src, { credentials: 'same-origin', headers: { 'ngrok-skip-browser-warning': '1' } })
      .then(function (r) {
        if (!r.ok || !/javascript/.test(r.headers.get('content-type') || '')) throw new Error(src);
        return r.text();
      })
      .then(function (code) {
        var tag = document.createElement('script');
        tag.text = code + '\n//# sourceURL=' + src;
        (document.head || document.documentElement).appendChild(tag);
      });
  }

  function loadZovi() {
    if (zoviLoaded()) return Promise.resolve(true);
    if (zoviLoading) return zoviLoading;
    zoviLoading = ZOVI_SCRIPTS.reduce(function (chain, src) {
      return chain.then(function () { return loadScript(src); });
    }, Promise.resolve()).then(zoviLoaded, function () {
      zoviLoading = null;
      return false;
    });
    return zoviLoading;
  }

  function onZoviLoaded(ok) {
    if (!state || !state.zovi) return;
    state.zovi.failed = !ok;
    if (!ok) {
      if (state.variantId === 'postcard') preserveSheetScroll(paintPreviewBlock);
      return;
    }
    if (!state.zovi.from) state.zovi.from = prefillFromName();
    if (state.variantId === 'postcard') preserveSheetScroll(paintPreviewBlock);
  }

  function zoviApi() {
    return global.ZoviCreate || null;
  }

  /** Пуш шлёт Telegram-бот; у MAX тот же заголовок, но пуша нет. */
  function botWillAnswer() {
    var h = shareRequestHeaders();
    return !!h['X-Telegram-Init-Data'] && String(h['X-Mini-App-Platform'] || 'telegram') === 'telegram';
  }

  function cleanName(raw) {
    var api = zoviApi();
    if (!api || typeof api.validateInviteName !== 'function') return '';
    var res = api.validateInviteName(raw, 'from_name', true);
    return res.ok ? res.value : '';
  }

  function prefillFromName() {
    try {
      var saved = global.localStorage && global.localStorage.getItem(ZOVI_FROM_KEY);
      if (saved && cleanName(saved)) return cleanName(saved);
    } catch (e) { /* */ }
    var t = tg();
    var user = t && t.initDataUnsafe && t.initDataUnsafe.user;
    return user ? cleanName(user.first_name) : '';
  }

  function fetchPayload(extra) {
    return fetch(endpoint(extra), { cache: 'no-store', headers: shareRequestHeaders() }).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    });
  }

  /** Событие шеринга — по нажатию канала. Ошибка счётчика не мешает отправке. */
  function track(channel) {
    try {
      fetch(endpoint({ channel: channel }), {
        cache: 'no-store',
        keepalive: true,
        headers: shareRequestHeaders(),
      }).catch(function () {});
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

  /**
   * Кастомные схемы (viber://) из мини-аппа: сначала WebApp.openLink — иначе WebView
   * глотает location.href и Viber не открывается.
   */
  function openDeepLink(url) {
    var u = String(url || '').trim();
    if (!u) return false;
    var t = tg();
    if (t && typeof t.openLink === 'function') {
      try {
        t.openLink(u, { try_instant_view: false });
        return true;
      } catch (e1) {
        try {
          t.openLink(u);
          return true;
        } catch (e2) { /* */ }
      }
    }
    try {
      var a = document.createElement('a');
      a.href = u;
      a.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;pointer-events:auto;';
      (document.body || document.documentElement).appendChild(a);
      a.click();
      global.setTimeout(function () {
        if (a.parentNode) a.parentNode.removeChild(a);
      }, 0);
      return true;
    } catch (e3) { /* */ }
    try {
      global.location.href = u;
      return true;
    } catch (e4) { /* */ }
    return false;
  }

  function openUrl(url) {
    var u = String(url || '').trim();
    if (!u) return;
    if (/^[a-z][a-z0-9+.-]*:/i.test(u) && !/^https?:\/\//i.test(u)) {
      if (!openDeepLink(u)) {
        global.open(u, '_blank', 'noopener');
      }
      return;
    }
    var t = tg();
    if (t && typeof t.openLink === 'function') {
      try {
        t.openLink(u, { try_instant_view: false });
        return;
      } catch (e) {
        try {
          t.openLink(u);
          return;
        } catch (e2) { /* */ }
      }
    }
    global.open(u, '_blank', 'noopener');
  }

  /** src в ссылке шаринга (TASK-223): tg, vb, wa, copy, story, sys, img */
  function withSrc(url, src) {
    var raw = String(url || '');
    var code = String(src || '').trim();
    if (!raw || !code) return raw;
    try {
      var absolute = /^https?:\/\//i.test(raw);
      var u = absolute ? new URL(raw) : new URL(raw, 'https://share.local/');
      if (u.searchParams.has('src')) return raw;
      u.searchParams.set('src', code);
      if (absolute) return u.origin + u.pathname + u.search + (u.hash || '');
      var rel = u.pathname;
      if (rel.charAt(0) === '/') rel = rel.slice(1);
      return rel + u.search + (u.hash || '');
    } catch (e) {
      return raw;
    }
  }

  function payloadForSrc(p, src) {
    if (!p || !src) return p;
    return {
      share_url: withSrc(p.share_url, src),
      share_body: p.share_body,
      story_image_url: p.story_image_url,
      og_image_url: p.og_image_url,
    };
  }

  function shareFullMessage(p) {
    var url = String((p && p.share_url) || '').trim();
    var body = String((p && p.share_body) || '').trim();
    return body ? body + '\n' + url : url;
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
    // TASK-222: сторис — кадр плюс ссылка, без подписи. Своя подпись уже нарисована
    // в самой картинке, а text попадал в редактор истории простынёй поверх неё.
    var link = String((p && p.share_url) || '').trim();
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

  /** Телефон умеет «Сохранить изображение» в галерею. Компьютер — только файл. */
  function phoneSavesToPhotos() {
    var nav = global.navigator || {};
    var ua = String(nav.userAgent || '');
    if (/iPad|iPhone|iPod/.test(ua)) return true;
    if (nav.platform === 'MacIntel' && nav.maxTouchPoints > 1) return true;
    return /Android/i.test(ua);
  }

  /**
   * Картинка для «В галерею», уже скачанная к нажатию.
   * share() после fetch теряет жест, и Safari вместо галереи молча уходит в «Файлы».
   */
  var galleryBlobs = {};

  function prefetchGalleryImage(p) {
    var img = cardImagePayload(p);
    if (!img.fetchPath || !phoneSavesToPhotos() || galleryBlobs[img.fetchPath]) return;
    galleryBlobs[img.fetchPath] = { blob: null };
    fetch(img.fetchPath, { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('http');
        return r.blob();
      })
      .then(function (blob) {
        if (galleryBlobs[img.fetchPath]) galleryBlobs[img.fetchPath].blob = blob;
      })
      .catch(function () {
        delete galleryBlobs[img.fetchPath];
      });
  }

  function readyGalleryBlob(fetchPath) {
    var entry = galleryBlobs[fetchPath];
    return entry && entry.blob ? entry.blob : null;
  }

  /**
   * Системное меню с одним файлом: на телефоне верхний пункт — «Сохранить изображение».
   * @returns {Promise<'shared'|'abort'|false>}
   */
  function tryShareImageFile(blob, fileName) {
    return new Promise(function (resolve) {
      var nav = global.navigator;
      if (!phoneSavesToPhotos() || !nav || typeof nav.share !== 'function' || typeof nav.canShare !== 'function') {
        resolve(false);
        return;
      }
      var file;
      try {
        file = new File([blob], fileName || 'glide-story.png', { type: (blob && blob.type) || 'image/png' });
      } catch (e) {
        resolve(false);
        return;
      }
      var payload = { files: [file] };
      try {
        if (!nav.canShare(payload)) {
          resolve(false);
          return;
        }
      } catch (e2) {
        resolve(false);
        return;
      }
      toast('«Сохранить изображение» — кадр попадёт в галерею');
      nav.share(payload).then(
        function () { resolve('shared'); },
        function (err) { resolve(err && err.name === 'AbortError' ? 'abort' : false); }
      );
    });
  }

  function downloadBlob(blob, fileName) {
    try {
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
        return downloadBlob(blob, fileName);
      })
      .catch(function () {
        return false;
      });
  }

  /**
   * Сохранить картинку карточки (вертикаль для сторис, если есть).
   * В мини-аппе — downloadFile, Telegram кладёт кадр в галерею.
   * На сайте с телефона — системное «Сохранить изображение», не файл в «Файлы».
   * @returns {Promise<string>} image_tg | image_os | image_abort | image_fallback | image_empty
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
      function afterBlob(blob) {
        if (!blob) {
          copyText(p.share_url, function () {
            openUrl(img.absolute);
            toast('Ссылка в буфере — удержите картинку и «Сохранить в Фото»');
            resolve('image_fallback');
          });
          return;
        }
        tryShareImageFile(blob, img.fileName).then(function (shared) {
          if (shared === 'shared' || shared === 'abort') {
            resolve(shared === 'abort' ? 'image_abort' : 'image_os');
            return;
          }
          if (downloadBlob(blob, img.fileName)) {
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
      }
      var cached = readyGalleryBlob(img.fetchPath);
      if (cached) {
        afterBlob(cached);
        return;
      }
      fetch(img.fetchPath, { cache: 'no-store' })
        .then(function (r) {
          if (!r.ok) throw new Error('http');
          return r.blob();
        })
        .then(afterBlob)
        .catch(function () { afterBlob(null); });
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
          if (isTelegramMiniApp()) {
            toast('Ссылка в буфере — добавьте стикером в Instagram');
          } else {
            toast('Ссылка скопирована');
          }
          resolve('story_os');
          return;
        }
        if (!isTelegramMiniApp()) {
          resolve('story_fallback');
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

  /**
   * Подборка города (есть endpoint): в Telegram уходит только ссылка.
   * Превью карточки Telegram и так берёт из og-картинки, а вставленный текст
   * дублирует её простынёй. Место и сеанс текст оставляют.
   * «Ссылка» и «Другое» текст не теряют — там превью мессенджера нет.
   */
  function telegramShareHref(shareUrl, shareBody, linkOnly) {
    var body = linkOnly ? '' : String(shareBody || '');
    var href = 'https://t.me/share/url?url=' + encodeURIComponent(String(shareUrl || ''));
    if (body) href += '&text=' + encodeURIComponent(body);
    return href;
  }

  function telegramLinkOnly() {
    return !!(state && state.endpoint);
  }

  /**
   * Telegram: подборка — только ссылка на обоих путях, место — со текстом.
   * Тело обнуляем до вызова, а не внутри telegramShareHref: Mini App-путь уходит
   * мимо этой функции, и раньше он оставался единственным, кто передавал текст.
   */
  function sendTelegramShare(p, linkOnly) {
    var body = linkOnly ? '' : String((p && p.share_body) || '');
    var opened = false;
    if (typeof global.openTelegramShareUrlFromMiniApp === 'function') {
      opened = !!global.openTelegramShareUrlFromMiniApp({ shareUrl: p.share_url, shareBody: body });
    }
    if (!opened) openUrl(telegramShareHref(p.share_url, body, linkOnly));
  }

  var CHANNELS = {
    telegram: function (p) {
      sendTelegramShare(payloadForSrc(p, 'tg'), telegramLinkOnly());
    },
    viber: function (p) {
      var ap = payloadForSrc(p, 'vb');
      var msg = shareFullMessage(ap);
      var href = 'viber://forward?text=' + encodeURIComponent(msg);
      if (!openDeepLink(href)) {
        copyText(msg, function () {
          toast('Текст скопирован — вставьте в Viber');
        });
      }
    },
    whatsapp: function (p) {
      var ap = payloadForSrc(p, 'wa');
      openUrl('https://wa.me/?text=' + encodeURIComponent(shareFullMessage(ap)));
    },
    copy: function (p) {
      // Только URL. Текст для чата — в Telegram / «Другое», не сюда.
      var text = String(withSrc(p.share_url, 'copy') || '').trim();
      var done = function () { toast('Ссылка скопирована'); };
      if (!text) {
        toast('Ссылка недоступна');
        return;
      }
      if (global.navigator && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { global.prompt('Скопируйте:', text); });
      } else {
        global.prompt('Скопируйте:', text);
      }
    },
    story: function (p) {
      openStoryShare(payloadForSrc(p, 'story')).then(function (channel) {
        track(channel);
      });
    },
    image: function (p) {
      openImageSave(payloadForSrc(p, 'img')).then(function (channel) {
        if (channel !== 'image_empty' && channel !== 'image_abort') track(channel);
      });
    },
    system: function (p) {
      var ap = payloadForSrc(p, 'sys');
      if (global.navigator && typeof navigator.share === 'function') {
        var data = { url: ap.share_url };
        if (ap.share_body) data.text = ap.share_body;
        navigator.share(data).catch(function () {});
        return;
      }
      // Нет системного меню (Telegram Desktop и т.п.) — открываем страницу места:
      // на ней кнопки Viber, WhatsApp, VK и «Скопировать».
      openUrl(ap.share_url);
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
    return sectionsOf(state);
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

  function slotRowMeta(row) {
    var meta = row.meta || '';
    if (String(row.id) === String(state.sessionId)) meta = meta ? meta + ' · выбрано' : 'Выбрано';
    return meta;
  }

  function slotRowButtonHtml(row) {
    var on = String(row.id) === String(state.sessionId);
    return (
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
      esc(slotRowMeta(row)) +
      '</em></button>'
    );
  }

  function slotRowsInnerHtml(sec) {
    if (!sec) return '';
    return (sec.rows || []).map(slotRowButtonHtml).join('');
  }

  function slotRowsHtml(sec) {
    if (!sec) return '';
    return (
      '<div class="gss-slot-list" role="listbox" aria-label="Сеанс">' + slotRowsInnerHtml(sec) + '</div>'
    );
  }

  function sheetEl() {
    return root && root.querySelector('.gss-sheet');
  }

  /** Превью перерисовывается без сдвига списка слотов и позиции шита. */
  function preserveSheetScroll(run) {
    var sheet = sheetEl();
    var top = sheet ? sheet.scrollTop : 0;
    run();
    if (sheet) sheet.scrollTop = top;
  }

  function syncDayStrip() {
    var strip = root.querySelector('.gss-day-strip');
    if (!strip) return false;
    var scroll = strip.scrollLeft;
    [].forEach.call(strip.querySelectorAll('[data-gss-day]'), function (btn) {
      var on = btn.getAttribute('data-gss-day') === state.slotDay;
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    strip.scrollLeft = scroll;
    return true;
  }

  function syncSlotRows() {
    var list = root.querySelector('.gss-slot-list');
    var sec = activeSlotSection();
    if (!list || !sec) return false;
    var scroll = list.scrollTop;
    var byId = {};
    (sec.rows || []).forEach(function (row) {
      byId[String(row.id)] = row;
    });
    [].forEach.call(list.querySelectorAll('[data-slot]'), function (btn) {
      var id = btn.getAttribute('data-slot');
      var row = byId[id];
      var on = String(id) === String(state.sessionId);
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      var em = btn.querySelector('em');
      if (em && row) em.textContent = slotRowMeta(row);
    });
    list.scrollTop = scroll;
    return true;
  }

  function paintSlotListForDay() {
    var list = root.querySelector('.gss-slot-list');
    var sec = activeSlotSection();
    if (!list || !sec) return false;
    list.scrollTop = 0;
    list.innerHTML = slotRowsInnerHtml(sec);
    return true;
  }

  function syncSlotPickerUi(mode) {
    ensureSlotDay();
    if (mode === 'day') {
      if (!syncDayStrip()) return paintSlotPicker();
      if (!paintSlotListForDay()) return paintSlotPicker();
      return;
    }
    if (mode === 'slot') {
      if (!syncDayStrip() || !syncSlotRows()) paintSlotPicker();
      return;
    }
    paintSlotPicker();
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

  function variantNeedsSession(variant, sheetState) {
    if (!variant) return false;
    var source = sheetState || state || {};
    return typeof variant.needsSession === 'function' ? !!variant.needsSession(source) : !!variant.needsSession;
  }

  function sessionPicker() {
    var variant = activeVariant();
    if (!variantNeedsSession(variant)) return '';
    if (variant.collapsesPicker && !state.zovi.pickOpen) {
      var picked = selectedPostcardSlot(state);
      if (picked) return pickedSlotSummary(picked);
    }
    return slotList();
  }

  function pickedSlotSummary(picked) {
    var day = shortCardDate(picked.section.localDate) || picked.section.dayLabel || '';
    var when = (day ? day + ' · ' : '') + (picked.row.time || '');
    return (
      '<div class="gss-slot-picker gss-slot-sum">' +
      '<span class="gss-slot-sum__when"><b>' + esc(when) + '</b>' +
      (picked.row.meta ? '<em>' + esc(picked.row.meta) + '</em>' : '') +
      '</span>' +
      '<button type="button" class="gss-slot-sum__change" data-gss-pick-open>Другое время</button>' +
      '</div>'
    );
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

  function isIcePlace(sheetState) {
    return (sheetState && sheetState.venueType ? sheetState.venueType : 'ice') === 'ice';
  }

  var SHARE_NOTE_TELEGRAM =
    'В чат — Telegram или «Ссылка». «В галерею» сохраняет вертикальную картинку для сторис. Ссылку для стикера скопируйте сами.';
  var SHARE_NOTE_BROWSER =
    'В чат — Telegram или «Ссылка». «В галерею» сохраняет вертикальную картинку для сторис.';

  function shareNoteHtml() {
    var text = isTelegramMiniApp() ? SHARE_NOTE_TELEGRAM : SHARE_NOTE_BROWSER;
    return '<p class="gss-note">' + esc(text) + '</p>';
  }

  function renderChannelsHtml(p) {
    var storyBtn =
      storyChannelVisible()
        ? '<button type="button" class="gss-ch' +
          (state.endpoint ? ' gss-ch--story' : '') +
          '" data-ch="story"' +
          (p ? '' : ' disabled') +
          '>Сторис</button>'
        : '';
    return (
      '<div class="gss-channels">' +
      '<button type="button" class="gss-ch gss-ch--tg" data-ch="telegram"' +
      (p ? '' : ' disabled') +
      '>Telegram</button>' +
      '<button type="button" class="gss-ch" data-ch="copy"' +
      (p ? '' : ' disabled') +
      '>Ссылка</button>' +
      '<button type="button" class="gss-ch gss-ch--viber" data-ch="viber"' +
      (p ? '' : ' disabled') +
      '>Viber</button>' +
      '<button type="button" class="gss-ch gss-ch--wa" data-ch="whatsapp"' +
      (p ? '' : ' disabled') +
      '>WhatsApp</button>' +
      storyBtn +
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
    // Подборка: текст дублирует то, что уже нарисовано на og/story — только картинки.
    var caption = '';
    if (!state || !state.endpoint) {
      caption =
        '<figcaption>' +
        esc(p ? p.share_body : 'Готовим карточку…') +
        '</figcaption>';
    }
    return '<figure class="gss-preview">' + renderPreview(p) + caption + '</figure>';
  }

  function renderPostcardPreview(sheetState) {
    var live = global.ZoviLive;
    if (!live) {
      return sheetState.zovi && sheetState.zovi.failed
        ? '<p class="gss-note">Открытка не загрузилась. <button type="button" class="gss-zlink" data-gss-zretry>Ещё раз</button></p>'
        : '<div class="gss-live gss-live--wait" aria-busy="true"></div>';
    }
    return '<div class="gss-live">' + live.html(postcardInput(sheetState)) + '</div>';
  }

  function postcardTo(sheetState) {
    var z = (sheetState && sheetState.zovi) || {};
    return String(z.to || '').trim();
  }

  function renderPostcardBottom(sheetState) {
    var z = sheetState.zovi || {};
    var to = postcardTo(sheetState);
    if (z.created) {
      var whom = to ? (global.ZoviModel ? global.ZoviModel.decline(to, 'dat') : to) : 'в чат';
      return (
        '<div class="gss-zdone">' +
        '<p class="gss-zdone__t">Открытка готова. Отправь ' + esc(whom) + '</p>' +
        (z.created.viaTelegram
          ? '<p class="gss-zdone__how">Когда ответят, бот пришлёт билет сюда, в Telegram.</p>'
          : '<p class="gss-zdone__how">Ответ появится на странице ответа — ' +
            '<button type="button" class="gss-zlink gss-zlink--inline" data-gss-zstatus>открыть и сохранить</button></p>') +
        '<div class="gss-channels gss-channels--3">' +
        '<button type="button" class="gss-ch gss-ch--tg" data-zch="telegram">Telegram</button>' +
        '<button type="button" class="gss-ch" data-zch="copy">Ссылка</button>' +
        '<button type="button" class="gss-ch" data-zch="system">Другое</button>' +
        '</div>' +
        '<div class="gss-zdone__more">' +
        '<button type="button" class="gss-zlink" data-gss-zopen>Посмотреть как ' + esc(to || 'друг') + '</button>' +
        '<button type="button" class="gss-zlink" data-gss-zedit>Изменить</button>' +
        '</div></div>'
      );
    }
    return (
      '<div class="gss-zf">' +
      '<label class="gss-zf__f"><span>Кого зовёшь</span>' +
      '<input type="text" data-gss-z="to" maxlength="20" autocomplete="off" enterkeyhint="next" placeholder="Лера" value="' +
      esc(z.to || '') +
      '" /></label>' +
      '<label class="gss-zf__f"><span>Твоё имя</span>' +
      '<input type="text" data-gss-z="from" maxlength="20" autocomplete="given-name" enterkeyhint="done" placeholder="Макс" value="' +
      esc(z.from || '') +
      '" /></label>' +
      '</div>' +
      '<p class="gss-zf__err" data-gss-zerr role="alert">' + esc(z.error || '') + '</p>' +
      '<button type="button" class="gss-zovi__btn" data-variant-action="postcard"' +
      (postcardReady(sheetState) && !z.busy ? '' : ' disabled') +
      '>' + (z.busy ? 'Создаём…' : 'Создать открытку') + '</button>' +
      '<p class="gss-zf__hint">' +
      (botWillAnswer()
        ? 'Ответ пришлёт бот сюда, в Telegram, — с билетом.'
        : 'Ответ появится на странице ответа — ссылку покажем после создания.') +
      '</p>'
    );
  }

  function renderShareBottom(sheetState) {
    return renderChannelsHtml(sheetState.payload) + shareNoteHtml();
  }

  var COMPANY_MINS = ['2', '3', '4', '5', '6'];

  function companyFormOf(sheetState) {
    return (sheetState && sheetState.companyForm) || {};
  }

  function companyMin(form) {
    var min = String(form.min == null || form.min === '' ? '3' : form.min);
    return COMPANY_MINS.indexOf(min) >= 0 ? min : '3';
  }

  function renderCompanyBottom(sheetState) {
    var form = companyFormOf(sheetState);
    if (form.shared) {
      var retry = form.shareFailed
        ? '<button type="button" class="gss-zovi__btn" data-gss-cshare="telegram">Ещё раз в чат</button>'
        : '';
      return (
        '<div class="gss-zdone">' +
        '<p class="gss-zdone__t">Карточка в чате</p>' +
        '<p class="gss-zdone__how">Там жмут «Иду». Кто откроет ссылку — встаёт на лёд.</p>' +
        '<button type="button" class="gss-zlink" data-gss-cshare="copy">Скопировать ссылку</button>' +
        retry +
        '<p class="gss-zf__err" data-gss-cerr role="alert">' + esc(form.error || '') + '</p>' +
        '</div>'
      );
    }
    var min = companyMin(form);
    var missing = String(Math.max(0, Number(min) - 1));
    var name = String(form.name || '').trim();
    var chips = COMPANY_MINS.map(function (n) {
      var on = n === min;
      return (
        '<button type="button" class="gss-slot' + (on ? ' is-on' : '') +
        '" data-gss-cmin="' + n + '" aria-pressed="' + (on ? 'true' : 'false') + '">' + n + '</button>'
      );
    }).join('');
    var who = name && !form.editName
      ? '<p class="gss-company-who"><span>Тебя увидят как <b>' + esc(name) + '</b></span>' +
        '<button type="button" class="gss-zlink" data-gss-cname>Изменить</button></p>'
      : '<label class="gss-zf__f"><span>Как записать тебя</span>' +
        '<input type="text" data-gss-c="name" maxlength="20" autocomplete="given-name" enterkeyhint="done" placeholder="Макс" value="' +
        esc(form.name || '') + '" /></label>';
    return (
      '<p class="gss-slot-q">Сколько должно встать на лёд</p>' +
      '<div class="gss-company-mins" role="group" aria-label="Сколько человек нужно">' + chips + '</div>' +
      '<p class="gss-company-need">С тобой ещё ' + missing + '.</p>' +
      who +
      '<p class="gss-zf__err" data-gss-cerr role="alert">' + esc(form.error || '') + '</p>' +
      '<button type="button" class="gss-zovi__btn" data-variant-action="company"' +
      (form.busy ? ' disabled' : '') +
      '>' + (form.busy ? 'Ставим в чат…' : 'В чат') + '</button>'
    );
  }

  function onCompanyInput(ev) {
    var input = ev.target && ev.target.closest && ev.target.closest('[data-gss-c]');
    if (!input || !state || !state.companyForm) return;
    state.companyForm[input.getAttribute('data-gss-c')] = input.value;
    if (state.companyForm.error) {
      state.companyForm.error = '';
      var err = root.querySelector('[data-gss-cerr]');
      if (err) err.textContent = '';
    }
  }

  function paintCompany() {
    var host = root && root.querySelector('.gss-channels-host');
    if (!host) return;
    host.innerHTML = renderCompanyBottom(state);
  }

  function companyErrorText(body) {
    var detail = body && body.detail;
    if (typeof detail === 'string' && detail.trim()) return detail.trim();
    if (Array.isArray(detail) && detail[0]) return String(detail[0].msg || 'Не получилось');
    return 'Не получилось';
  }

  function createCompany() {
    var form = state && state.companyForm;
    if (!form || form.busy) return;
    var headers = shareRequestHeaders();
    if (form.shared) return;
    if (form.created) {
      shareCompany('telegram');
      return;
    }
    if (!headers['X-Telegram-Init-Data']) {
      form.error = 'Собрать компанию можно из Telegram.';
      paintCompany();
      return;
    }
    var name = String(form.name || '').trim();
    var min = Number(companyMin(form));
    if (!name) {
      form.editName = true;
      form.error = 'Как тебя записать?';
      paintCompany();
      return;
    }
    if (state.sessionId == null || String(state.sessionId).trim() === '') {
      form.error = 'Выбери сеанс.';
      paintCompany();
      return;
    }
    haptic();
    form.busy = true;
    form.error = '';
    paintCompany();
    headers['Content-Type'] = 'application/json';
    headers.Accept = 'application/json';
    var sheetState = state;
    fetch('/api/public/ice-companies', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({
        session_id: Number(state.sessionId),
        min_people: min,
        display_name: name,
        surface: 'miniapp',
      }),
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (res) {
        if (sheetState !== state) return;
        form.busy = false;
        if (!res.ok || !res.body || !res.body.public_code) {
          form.error = companyErrorText(res.body);
          paintCompany();
          return;
        }
        var page = String(res.body.page_url || '');
        if (page && page.charAt(0) === '/') page = global.location.origin + page;
        form.created = {
          code: res.body.public_code,
          pageUrl: page,
          cardText: res.body.card_text || '',
        };
        form.shared = false;
        form.shareFailed = false;
        form.busy = true;
        shareCompany('telegram');
      })
      .catch(function () {
        if (sheetState !== state) return;
        form.busy = false;
        form.error = 'Не получилось. Проверь связь и попробуй ещё раз.';
        paintCompany();
      });
  }

  function dropUnsharedCompany(sheetState, message) {
    var form = sheetState && sheetState.companyForm;
    var code = form && form.created && form.created.code;
    if (form) {
      form.created = null;
      form.shared = false;
      form.sharing = '';
      form.busy = false;
      form.shareFailed = false;
      form.error = message || '';
    }
    if (sheetState === state) paintCompany();
    if (!code) return;
    fetch('/api/public/ice-companies/' + encodeURIComponent(code) + '/cancel', {
      method: 'POST',
      headers: shareRequestHeaders(),
    }).catch(function () {});
  }

  function shareCompany(channel) {
    var form = state && state.companyForm;
    var created = form && form.created;
    if (!form || !created || form.sharing) return;
    if (channel === 'copy') {
      var text = String(created.pageUrl || '').trim();
      var done = function () { toast('Ссылка скопирована'); };
      if (!text) {
        form.error = 'Ссылка недоступна.';
        paintCompany();
        return;
      }
      haptic();
      if (global.navigator && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { global.prompt('Скопируйте:', text); });
      } else {
        global.prompt('Скопируйте:', text);
      }
      return;
    }
    var headers = shareRequestHeaders();
    if (!headers['X-Telegram-Init-Data']) {
      form.error = 'Отправить карточку можно из Telegram.';
      paintCompany();
      return;
    }
    haptic();
    form.sharing = 'telegram';
    form.error = '';
    paintCompany();
    var sheetState = state;
    fetch('/api/public/ice-companies/' + encodeURIComponent(created.code) + '/telegram-prepare', {
      method: 'POST',
      headers: headers,
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (res) {
        if (sheetState !== state) return;
        if (!res.ok) {
          dropUnsharedCompany(sheetState, 'Не получилось открыть чат.');
          return;
        }
        var app = tg();
        var prep = res.body || {};
        if (prep.prepared_message_id && app && app.shareMessage) {
          app.shareMessage(prep.prepared_message_id, function (ok) {
            if (sheetState !== state) return;
            if (!ok) {
              dropUnsharedCompany(sheetState, '');
              return;
            }
            form.busy = false;
            form.sharing = '';
            form.shared = true;
            paintCompany();
          });
          return;
        }
        if (app && app.switchInlineQuery && prep.inline_query) {
          form.busy = false;
          form.sharing = '';
          paintCompany();
          app.switchInlineQuery(prep.inline_query, ['users', 'groups']);
          return;
        }
        dropUnsharedCompany(sheetState, 'Не получилось открыть чат.');
      })
      .catch(function () {
        if (sheetState !== state) return;
        dropUnsharedCompany(sheetState, 'Не получилось открыть чат.');
      });
  }

  function humanError(detail) {
    var text = typeof detail === 'string' ? detail : '';
    return text.replace(/^(to_name|from_name):\s*/, '') || 'Не получилось создать открытку. Попробуй ещё раз.';
  }

  function createPostcard() {
    var z = state.zovi;
    var api = zoviApi();
    if (!api || z.busy || !postcardReady(state)) return;
    var built = api.inviteRequestBody({
      sessionId: Number(state.sessionId),
      toName: z.to,
      fromName: z.from,
      showPrice: false,
      deviceToken: api.ensureDeviceToken(global.localStorage),
      via: postcardVia(state),
    });
    if (!built.ok) {
      z.error = humanError(built.toError || built.fromError || built.formError);
      if (!String(z.from || '').trim()) z.error = 'Подпиши открытку — как тебя зовут?';
      if (!String(z.to || '').trim()) z.error = 'Кого зовёшь? Впиши имя.';
      paintPostcardBottom();
      return;
    }
    haptic();
    z.busy = true;
    z.error = '';
    paintPostcardBottom();
    var headers = shareRequestHeaders();
    headers['Content-Type'] = 'application/json';
    headers.Accept = 'application/json';
    var forSession = String(state.sessionId);
    var sheetState = state;
    fetch('/api/public/invites', { method: 'POST', headers: headers, body: JSON.stringify(built.body) })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (res) {
        if (sheetState !== state) return;
        z.busy = false;
        if (!res.ok || !res.body || !res.body.invite_path) {
          z.error = humanError(res.body && res.body.detail);
          paintPostcardBottom();
          return;
        }
        if (String(state.sessionId) !== forSession) {
          paintPostcardBottom();
          return;
        }
        z.created = {
          code: res.body.code,
          url: global.location.origin + res.body.invite_path,
          statusUrl: global.location.origin + res.body.status_path,
          viaTelegram: botWillAnswer(),
        };
        rememberMine(z.created, built.body.to_name);
        try { global.localStorage.setItem(ZOVI_FROM_KEY, built.body.from_name); } catch (e) { /* */ }
        paintPostcardBottom();
      })
      .catch(function () {
        if (sheetState !== state) return;
        z.busy = false;
        z.error = 'Нет связи. Попробуй ещё раз.';
        paintPostcardBottom();
      });
  }

  function rememberMine(created, toName) {
    try {
      var input = postcardInput(state);
      var raw = global.localStorage.getItem('zovi_mine');
      var items = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(items)) items = [];
      items = items.filter(function (item) { return item && item.code !== created.code; });
      items.unshift({
        code: created.code,
        to: toName || 'компания',
        when: [input.day, input.time, input.place].filter(Boolean).join(' · '),
        status_path: created.statusUrl,
      });
      global.localStorage.setItem('zovi_mine', JSON.stringify(items.slice(0, 20)));
    } catch (e) { /* */ }
  }

  /* Только ссылка, без текста: вопрос и сеанс уже в превью ссылки (решение владельца). */
  function postcardPayload() {
    return { share_url: state.zovi.created.url, share_body: '' };
  }

  function paintPostcardBottom() {
    var host = root && root.querySelector('.gss-channels-host');
    if (!host) return;
    host.innerHTML = renderPostcardBottom(state);
  }

  function mountLive() {
    if (state && state.zoviLive) {
      state.zoviLive.destroy();
      state.zoviLive = null;
    }
    var el = root && root.querySelector('.gss-live [data-zl]');
    if (!el || !global.ZoviLive) return;
    if (!state.zoviKb) state.zoviKb = global.ZoviLive.liftForKeyboard(sheetEl());
    state.zoviLive = global.ZoviLive.attach(el, {
      onDodge: function () {
        try {
          var t = tg();
          if (t && t.HapticFeedback) t.HapticFeedback.impactOccurred('light');
        } catch (e) { /* */ }
      },
    });
  }

  function onSheetInput(ev) {
    onPostcardInput(ev);
    onCompanyInput(ev);
  }

  function onPostcardInput(ev) {
    var input = ev.target && ev.target.closest && ev.target.closest('[data-gss-z]');
    if (!input || !state || !state.zovi) return;
    state.zovi[input.getAttribute('data-gss-z')] = input.value;
    if (state.zovi.error) {
      state.zovi.error = '';
      var err = root.querySelector('[data-gss-zerr]');
      if (err) err.textContent = '';
    }
    var live = root.querySelector('.gss-live [data-zl]');
    if (live && global.ZoviLive) global.ZoviLive.update(live, postcardInput(state));
  }

  /**
   * Вариант шита — одна запись. Новый вариант: запись и свои рендеры,
   * без правок paintBody и обработчиков.
   * shareInvite: null — свой низ, запрос «поделиться» не шлём.
   */
  var SHARE_VARIANTS = [
    {
      id: 'invite',
      label: function (sheetState) {
        return isIcePlace(sheetState) ? 'Погнали кататься' : 'Позвать с собой';
      },
      rank: function (sheetState) {
        return isIcePlace(sheetState) ? 0 : 1;
      },
      needsSession: true,
      shareInvite: true,
      available: function (sheetState) {
        return !sheetState.endpoint;
      },
      renderPreview: function (sheetState) {
        return renderPreviewFigureHtml(sheetState.payload);
      },
      renderBottom: renderShareBottom,
    },
    {
      id: 'company',
      label: function () {
        return 'Компания';
      },
      rank: function () {
        return 1;
      },
      needsSession: true,
      shareInvite: null,
      available: function (sheetState) {
        return !sheetState.endpoint && isIcePlace(sheetState) && !!sheetState.company;
      },
      renderPreview: function () {
        return '';
      },
      renderBottom: renderCompanyBottom,
      onAction: createCompany,
      onSession: function () {
        if (!state.companyForm || !state.companyForm.created) return;
        state.companyForm.created = null;
        state.companyForm.busy = false;
        state.companyForm.sharing = '';
        state.companyForm.shareFailed = false;
        state.companyForm.error = '';
        paintCompany();
      },
    },
    {
      id: 'postcard',
      label: function () {
        return 'Открытка';
      },
      rank: function () {
        return 2;
      },
      needsSession: true,
      shareInvite: null,
      available: function (sheetState) {
        return !sheetState.endpoint && isIcePlace(sheetState);
      },
      renderPreview: renderPostcardPreview,
      renderBottom: renderPostcardBottom,
      onAction: createPostcard,
      collapsesPicker: true,
      onSession: function () {
        // Другой сеанс — другая открытка: готовую ссылку не подсовываем.
        state.zovi.created = null;
        state.zovi.pickOpen = false;
        paintSlotPicker();
        preserveSheetScroll(paintPreviewBlock);
      },
    },
    {
      id: 'schedule',
      label: function (sheetState) {
        return isIcePlace(sheetState) ? 'Расписание' : 'Место';
      },
      rank: function (sheetState) {
        return isIcePlace(sheetState) ? 3 : 0;
      },
      // Карточка катка показывает сеанс (session_id уходит в запрос) — значит, его можно сменить,
      // как в «Погнали кататься» и «Открытке». У места без льда сеансов нет.
      needsSession: function (sheetState) {
        return isIcePlace(sheetState);
      },
      shareInvite: false,
      available: function (sheetState) {
        return !sheetState.endpoint;
      },
      renderPreview: function (sheetState) {
        return renderPreviewFigureHtml(sheetState.payload);
      },
      renderBottom: renderShareBottom,
    },
  ];

  function variantById(id) {
    var i;
    for (i = 0; i < SHARE_VARIANTS.length; i++) {
      if (SHARE_VARIANTS[i].id === id) return SHARE_VARIANTS[i];
    }
    return null;
  }

  function visibleVariants(sheetState) {
    var list = [];
    var i;
    var source = sheetState || {};
    for (i = 0; i < SHARE_VARIANTS.length; i++) {
      if (SHARE_VARIANTS[i].available(source)) list.push(SHARE_VARIANTS[i]);
    }
    list.sort(function (a, b) {
      return a.rank(source) - b.rank(source);
    });
    return list;
  }

  function activeVariant() {
    if (!state || !state.variantId) return null;
    var variant = variantById(state.variantId);
    if (!variant || !variant.available(state)) return null;
    return variant;
  }

  function initialVariantId(opts) {
    opts = opts || {};
    if (opts.endpoint) return null;
    if (opts.variant === 'company' && opts.company) return 'company';
    return opts.invite ? 'invite' : 'schedule';
  }

  function selectVariant(id) {
    var variant = variantById(id);
    if (!variant || !state || !variant.available(state)) return false;
    state.variantId = id;
    if (state.zovi) state.zovi.pickOpen = false;
    if (variant.shareInvite != null) state.invite = !!variant.shareInvite;
    return true;
  }

  function renderTabsHtml() {
    var list = visibleVariants(state);
    if (!list.length) return '';
    return (
      '<div class="gss-tabs" role="group" aria-label="Тон">' +
      list
        .map(function (variant) {
          var on = variant.id === state.variantId;
          return (
            '<button type="button" class="gss-tab' +
            (on ? ' is-on' : '') +
            '" data-variant="' +
            esc(variant.id) +
            '" aria-pressed="' +
            (on ? 'true' : 'false') +
            '">' +
            esc(variant.label(state)) +
            '</button>'
          );
        })
        .join('') +
      '</div>'
    );
  }

  function previewHtml() {
    var variant = activeVariant();
    if (variant) return variant.renderPreview(state);
    return renderPreviewFigureHtml(state.payload);
  }

  function bottomHtml() {
    var variant = activeVariant();
    if (variant) return variant.renderBottom(state);
    return renderShareBottom(state);
  }

  function revealPickedSlot() {
    var list = root && root.querySelector('.gss-slot-list');
    var row = list && list.querySelector('.gss-slot-row.is-on');
    if (!row) return;
    var top = row.offsetTop - list.offsetTop;
    if (top < list.scrollTop || top + row.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = Math.max(0, top - 8);
    }
  }

  function paintBody() {
    paintBodyHtml();
    revealPickedSlot();
    mountLive();
  }

  function paintBodyHtml() {
    root.querySelector('.gss-body').innerHTML =
      renderTabsHtml() +
      sessionPicker() +
      '<div class="gss-preview-host">' +
      previewHtml() +
      '</div>' +
      '<div class="gss-channels-host">' +
      bottomHtml() +
      '</div>';
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
    previewHost.innerHTML = previewHtml();
    channelsHost.innerHTML = bottomHtml();
    mountLive();
  }

  function rememberPlace(data) {
    var name = placeNameFromShare(data && data.place_share_body);
    if (name) state.placeName = name;
  }

  function reloadPreview() {
    state.payload = null;
    preserveSheetScroll(paintPreviewBlock);
    var token = (state.token = (state.token || 0) + 1);
    fetchPayload({ record: 'false' })
      .then(function (data) {
        if (token !== state.token) return;
        state.payload = data;
        prefetchGalleryImage(data);
        rememberPlace(data);
        preserveSheetScroll(paintPreviewBlock);
      })
      .catch(function () {
        if (token !== state.token) return;
        root.querySelector('.gss-body').innerHTML =
          '<p class="gss-note">Не получилось подготовить ссылку. Проверьте связь и попробуйте ещё раз.</p>';
      });
  }

  function variantLoadsShare() {
    var variant = activeVariant();
    if (!variant) return true;
    return variant.shareInvite != null;
  }

  function reload() {
    if (variantLoadsShare()) state.payload = null;
    paintBody();
    if (variantLoadsShare()) reloadPreview();
  }

  function onClick(ev) {
    if (ev.target === root || ev.target.closest('[data-gss-close]')) {
      close();
      return;
    }
    var tab = ev.target.closest('[data-variant]');
    if (tab) {
      var nextId = tab.getAttribute('data-variant');
      if (nextId && nextId !== state.variantId && selectVariant(nextId)) {
        haptic();
        // Тексты обоих тонов уже в ответе — второй запрос нужен только ради картинки.
        // Открытка запрос не шлёт и событие не пишет.
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
        syncSlotPickerUi('day');
      }
      return;
    }
    var slot = ev.target.closest('[data-slot]');
    if (slot) {
      haptic();
      state.sessionId = slot.getAttribute('data-slot');
      syncSlotPickerUi('slot');
      if (slot.blur) slot.blur();
      var slotVariant = activeVariant();
      if (slotVariant && typeof slotVariant.onSession === 'function') slotVariant.onSession();
      else reloadPreview();
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
        if (!state.sessionId && state.slots[0] && !state.sessionMissing) {
          state.sessionId = state.slots[0].id;
        }
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
    if (ev.target.closest('[data-gss-zretry]')) {
      state.zovi.failed = false;
      preserveSheetScroll(paintPreviewBlock);
      loadZovi().then(onZoviLoaded);
      return;
    }
    if (ev.target.closest('[data-gss-pick-open]')) {
      haptic();
      state.zovi.pickOpen = true;
      ensureSlotDay();
      preserveSheetScroll(paintSlotPicker);
      revealPickedSlot();
      return;
    }
    var zch = ev.target.closest('[data-zch]');
    if (zch && state.zovi && state.zovi.created) {
      haptic();
      CHANNELS[zch.getAttribute('data-zch')](postcardPayload());
      return;
    }
    if (ev.target.closest('[data-gss-zstatus]') && state.zovi && state.zovi.created) {
      openUrl(state.zovi.created.statusUrl);
      return;
    }
    if (ev.target.closest('[data-gss-zopen]') && state.zovi && state.zovi.created) {
      openUrl(state.zovi.created.url);
      return;
    }
    if (ev.target.closest('[data-gss-zedit]') && state.zovi) {
      haptic();
      state.zovi.created = null;
      paintPostcardBottom();
      return;
    }
    var companyMinBtn = ev.target.closest('[data-gss-cmin]');
    if (companyMinBtn && state && state.companyForm && !state.companyForm.created) {
      var nextMin = companyMinBtn.getAttribute('data-gss-cmin');
      if (nextMin && nextMin !== companyMin(state.companyForm)) {
        haptic();
        state.companyForm.min = nextMin;
        paintCompany();
      }
      return;
    }
    if (ev.target.closest('[data-gss-cname]') && state && state.companyForm && !state.companyForm.created) {
      haptic();
      state.companyForm.editName = true;
      paintCompany();
      var nameInput = root.querySelector('[data-gss-c="name"]');
      if (nameInput && nameInput.focus) nameInput.focus();
      return;
    }
    var companyShare = ev.target.closest('[data-gss-cshare]');
    if (companyShare && state && state.companyForm && state.companyForm.created) {
      if (companyShare.disabled) return;
      shareCompany(companyShare.getAttribute('data-gss-cshare'));
      return;
    }
    var actionBtn = ev.target.closest('[data-variant-action]');
    if (actionBtn) {
      if (actionBtn.disabled) return;
      var actionVariant = activeVariant();
      if (actionVariant && typeof actionVariant.onAction === 'function') actionVariant.onAction(actionBtn);
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
    root.addEventListener('input', onSheetInput);
    document.body.appendChild(root);
    return root;
  }

  function resolveInitialSessionId(opts) {
    if (opts.sessionId != null && String(opts.sessionId).trim() !== '') {
      return String(opts.sessionId).trim();
    }
    if (opts.sessionMissing) return null;
    var slots = opts.slots || [];
    return slots[0] && slots[0].id != null ? String(slots[0].id) : null;
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
      sessionId: resolveInitialSessionId(opts),
      slotDay: null,
      invite: !!opts.invite,
      variantId: null,
      placeName: opts.placeName ? String(opts.placeName) : '',
      sessionMissing: !!opts.sessionMissing,
      context: opts.context || 'arena_card',
      venueType: opts.venueType || 'ice',
      company: !!opts.company,
      companyForm: {
        min: '3',
        name: prefillFromName(),
        editName: false,
        busy: false,
        sharing: '',
        error: '',
        shareFailed: false,
        created: null,
      },
      loadSlots: opts.loadSlots || null,
      payload: null,
      zovi: { to: '', from: prefillFromName(), created: null, busy: false, error: '', pickOpen: false },
      zoviLive: null,
    };
    if (!state.endpoint && (state.venueType || 'ice') === 'ice') loadZovi().then(onZoviLoaded);
    var opening = initialVariantId(opts);
    if (opening) selectVariant(opening);
    ensureSlotDay();
    root.hidden = false;
    global.requestAnimationFrame(function () { root.classList.add('is-open'); });
    reload();
  }

  function close() {
    if (!root) return;
    if (state && state.zoviLive) {
      state.zoviLive.destroy();
      state.zoviLive = null;
    }
    if (state && state.zoviKb) {
      state.zoviKb();
      state.zoviKb = null;
    }
    root.classList.remove('is-open');
    global.setTimeout(function () { if (root) root.hidden = true; }, 180);
  }

  global.GlideShareSheet = {
    open: open,
    close: close,
    _withSrc: withSrc,
    _shareFullMessage: shareFullMessage,
    _payloadForSrc: payloadForSrc,
    _openStoryShare: openStoryShare,
    _openImageSave: openImageSave,
    _telegramShareHref: telegramShareHref,
    _isTelegramMiniApp: isTelegramMiniApp,
    _shareNoteHtml: shareNoteHtml,
    _storyChannelVisible: storyChannelVisible,
    _resolveInitialSessionId: resolveInitialSessionId,
    variantsFor: function (sheetState) {
      return visibleVariants(sheetState).map(function (variant) {
        return {
          id: variant.id,
          label: variant.label(sheetState),
          picksSession: variantNeedsSession(variant, sheetState),
        };
      });
    },
    initialVariantId: initialVariantId,
    postcardReady: postcardReady,
    postcardVia: postcardVia,
    postcardInput: postcardInput,
    postcardBottomHtml: renderPostcardBottom,
    companyBottomHtml: renderCompanyBottom,
    _previewFigureHtml: function (payload, selection) {
      var prev = state;
      state = selection
        ? { endpoint: '/api/public/ice/selection/share', venueType: 'ice', context: 'ice_list' }
        : { endpoint: null, venueType: 'ice', context: 'arena_card' };
      try {
        return renderPreviewFigureHtml(payload);
      } finally {
        state = prev;
      }
    },
  };
})(window);
