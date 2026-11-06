/**
 * TASK-350: «Показать вас родителям на катках …?» — один экран по центру, один тап.
 *
 * Открывается сразу после онбординга и один раз на главной кабинета у тренера, чья карточка
 * готова, но ещё черновик (`state === 'draft'`, `can_act`, `readiness.submit_ready`). Показывает
 * карточку ровно такой, какой её увидит родитель, и публикует тем же POST /trainer/catalog/submit,
 * что и раздел «Каталог». После публикации — страница тренера на сайте и кнопка «Отправить родителям».
 *
 * «Пока только по ссылке» закрывает окно и больше его не показывает (на этом устройстве); строка
 * «Вас пока нет в каталоге» на главной при этом остаётся — тренер не может исчезнуть молча.
 *
 * Использование: TrainerCatalogOffer.maybeOpen({ apiUrl, headers, source, once })
 *   apiUrl(path) → '/api/webapp' + path + init_data; headers() → заголовки с init data.
 */
(function (global) {
  'use strict';

  var SEEN_KEY = 'glide_catalog_offer_seen_v1';
  var STYLE_ID = 'tco-style';
  var CSS =
    '.tco-back{position:fixed;inset:0;z-index:9000;background:rgba(10,20,28,.45);display:flex;align-items:center;justify-content:center;padding:16px}' +
    '.tco{width:100%;max-width:380px;max-height:calc(100vh - 32px);overflow:auto;box-sizing:border-box;border-radius:20px;padding:20px 18px 16px;' +
    'background:var(--tg-theme-bg-color,var(--g-surface,#fff));color:var(--tg-theme-text-color,var(--g-ink,#0d1b26));box-shadow:0 12px 40px rgba(0,0,0,.25)}' +
    '.tco h2{margin:0 0 6px;font-size:20px;line-height:1.25;font-weight:650}' +
    '.tco p{margin:0 0 12px;font-size:15px;line-height:1.4;color:var(--tg-theme-hint-color,var(--g-muted,#5b6b77))}' +
    '.tco-card{display:flex;gap:12px;align-items:center;padding:12px;border-radius:14px;margin:4px 0 14px;' +
    'background:var(--tg-theme-secondary-bg-color,var(--g-bg,#f4f6f7))}' +
    '.tco-ava{flex:0 0 48px;width:48px;height:48px;border-radius:50%;overflow:hidden;display:flex;align-items:center;justify-content:center;' +
    'font-weight:650;background:var(--g-accent-wash,#e3f2f1);color:var(--g-accent-ink,#0B6E70)}' +
    '.tco-ava img{width:100%;height:100%;object-fit:cover}' +
    '.tco-name{display:block;font-weight:650;font-size:16px}' +
    '.tco-line{display:block;font-size:13px;margin-top:2px;color:var(--tg-theme-hint-color,var(--g-muted,#5b6b77))}' +
    '.tco-btn{display:block;width:100%;min-height:48px;border:0;border-radius:12px;font-size:16px;font-weight:600;margin-top:8px;cursor:pointer;' +
    'background:var(--tg-theme-button-color,var(--g-accent,#0B6E70));color:var(--tg-theme-button-text-color,#fff)}' +
    '.tco-btn[disabled]{opacity:.6}' +
    '.tco-btn--ghost{background:transparent;color:var(--tg-theme-link-color,var(--g-accent-ink,#0B6E70))}' +
    '.tco-url{display:block;word-break:break-all;font-size:14px;padding:10px 12px;border-radius:10px;margin:0 0 4px;' +
    'background:var(--tg-theme-secondary-bg-color,var(--g-bg,#f4f6f7));color:var(--tg-theme-text-color,#0d1b26)}' +
    '.tco-note{font-size:13px!important;margin:8px 0 0!important}';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function storage() {
    try { return global.localStorage; } catch (e) { return null; }
  }

  function seen() {
    var s = storage();
    try { return !!(s && s.getItem(SEEN_KEY)); } catch (e) { return false; }
  }

  function markSeen() {
    var s = storage();
    try { if (s) s.setItem(SEEN_KEY, String(Date.now())); } catch (e) { /* приватный режим */ }
  }

  /** Готова ли карточка к публикации одним тапом — то же условие, что у блока на экране «Готово». */
  function eligible(p) {
    return !!(p && String(p.state || 'draft') === 'draft' && p.can_act && p.readiness && p.readiness.submit_ready);
  }

  /** «ТЦ Замок и Чижовка» / «ТЦ Замок, Чижовка и ещё 2» / '' (онлайн, без катков). */
  function placesPhrase(pv) {
    var names = (pv && pv.arena_names) || [];
    if (!names.length || pv.arena_work_format === 'online') return '';
    if (names.length === 1) return names[0];
    if (names.length === 2) return names[0] + ' и ' + names[1];
    return names[0] + ', ' + names[1] + ' и ещё ' + (names.length - 2);
  }

  function cardHtml(pv) {
    pv = pv || {};
    var name = [pv.first_name, pv.last_name].filter(Boolean).join(' ').trim();
    var lines = [];
    if (pv.service_line) lines.push(pv.service_line);
    if (pv.arena_work_format === 'online') lines.push('Онлайн');
    else if (pv.arena_names && pv.arena_names.length) lines.push(pv.arena_names.slice(0, 2).join(', '));
    var initials = name ? name.split(/\s+/).slice(0, 2).map(function (w) { return w.charAt(0); }).join('').toUpperCase() : '·';
    var ava = pv.photo_file_key
      ? '<img src="/api/public/photos/' + encodeURIComponent(pv.photo_file_key) + '" alt="">'
      : esc(initials);
    return (
      '<div class="tco-card"><span class="tco-ava">' + ava + '</span><span>' +
      '<span class="tco-name">' + esc(name || 'Ваша карточка') + '</span>' +
      '<span class="tco-line">' + esc(lines.join(' · ') || 'Так вас увидят родители') + '</span></span></div>'
    );
  }

  function ensureStyle() {
    if (global.document.getElementById(STYLE_ID)) return;
    var st = global.document.createElement('style');
    st.id = STYLE_ID;
    st.textContent = CSS;
    global.document.head.appendChild(st);
  }

  function getJson(opts, path, method) {
    return global
      .fetch(opts.apiUrl(path), { method: method || 'GET', headers: opts.headers() })
      .then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, data: d }; }, function () { return { ok: r.ok, data: null }; });
      });
  }

  function pageUrlFromLink(link) {
    return String(link || '').split('?')[0];
  }

  function openExternal(url) {
    var tg = global.Telegram && global.Telegram.WebApp;
    if (tg && typeof tg.openLink === 'function') {
      try { tg.openLink(url); return; } catch (e) { /* */ }
    }
    global.open(url, '_blank', 'noopener');
  }

  function shareLink(link, text, body) {
    if (typeof global.openTelegramShareUrlFromMiniApp === 'function') {
      var opened = global.openTelegramShareUrlFromMiniApp({ shareUrl: link, shareBody: body || '', fullMessage: text || link });
      if (opened) return 'shared';
    }
    try {
      if (global.navigator && global.navigator.clipboard) {
        global.navigator.clipboard.writeText(link);
        return 'copied';
      }
    } catch (e) { /* */ }
    return 'none';
  }

  function close(back) {
    if (back && back.parentNode) back.parentNode.removeChild(back);
  }

  function renderPublished(box, back, opts, places) {
    box.innerHTML =
      '<h2>Вы на странице ' + (places ? 'катков' : 'Glide') + '</h2>' +
      '<p>' + (places ? 'Родители увидят вас на ' + esc(places) + '. ' : '') +
      'Вот ваша страница — отправьте её ученикам, с неё они запишутся в Telegram.</p>' +
      '<span class="tco-url" data-tco-url>…</span>' +
      '<button type="button" class="tco-btn" data-tco-share disabled>Отправить родителям</button>' +
      '<button type="button" class="tco-btn tco-btn--ghost" data-tco-open disabled>Посмотреть, как увидят родители</button>' +
      '<button type="button" class="tco-btn tco-btn--ghost" data-tco-close>Готово</button>' +
      '<p class="tco-note" data-tco-note></p>';
    box.querySelector('[data-tco-close]').onclick = function () {
      close(back);
      if (typeof opts.onDone === 'function') opts.onDone({ published: true });
    };
    getJson(opts, '/trainer/hub/universal-invite-link').then(function (o) {
      var d = (o && o.ok && o.data) || {};
      var link = d.link ? String(d.link) : '';
      var urlEl = box.querySelector('[data-tco-url]');
      if (!link) {
        if (urlEl) urlEl.textContent = 'Ссылка появится в кабинете — кнопка «Ссылка на запись».';
        return;
      }
      if (urlEl) urlEl.textContent = pageUrlFromLink(link);
      var shareBtn = box.querySelector('[data-tco-share]');
      var openBtn = box.querySelector('[data-tco-open]');
      shareBtn.disabled = false;
      openBtn.disabled = false;
      shareBtn.onclick = function () {
        var res = shareLink(link, d.share_text, d.share_body);
        var note = box.querySelector('[data-tco-note]');
        if (note) {
          note.textContent = res === 'copied'
            ? 'Ссылка скопирована — вставьте её в чат с родителями.'
            : 'Как только ученик запишется, придёт сообщение в Telegram.';
        }
      };
      openBtn.onclick = function () { openExternal(pageUrlFromLink(link)); };
    });
  }

  function render(p, opts) {
    ensureStyle();
    var pv = p.preview || {};
    var places = placesPhrase(pv);
    var back = global.document.createElement('div');
    back.className = 'tco-back';
    back.setAttribute('role', 'dialog');
    back.setAttribute('aria-modal', 'true');
    var box = global.document.createElement('div');
    box.className = 'tco';
    box.innerHTML =
      '<h2>' + (places ? 'Показать вас родителям на ' + esc(places) + '?' : 'Показать вас родителям в Glide?') + '</h2>' +
      '<p>Карточка бесплатная. Родители увидят её на странице катка и на вашей странице в Glide.</p>' +
      cardHtml(pv) +
      '<button type="button" class="tco-btn" data-tco-yes>Показать меня</button>' +
      '<button type="button" class="tco-btn tco-btn--ghost" data-tco-no>Пока только по ссылке</button>' +
      '<p class="tco-note">Дополнить или поправить карточку можно в любой момент в «Профиле», убрать — в «Каталоге».</p>';
    back.appendChild(box);
    global.document.body.appendChild(back);
    markSeen();

    box.querySelector('[data-tco-no]').onclick = function () {
      close(back);
      if (typeof opts.onDone === 'function') opts.onDone({ published: false });
    };
    var yes = box.querySelector('[data-tco-yes]');
    yes.onclick = function () {
      if (yes.disabled) return;
      yes.disabled = true;
      yes.textContent = 'Публикуем…';
      getJson(opts, '/trainer/catalog/submit', 'POST').then(function (o) {
        if (o.ok && o.data && o.data.state === 'published') {
          renderPublished(box, back, opts, places);
          return;
        }
        yes.disabled = false;
        yes.textContent = 'Показать меня';
        var labels = o.data && o.data.detail && o.data.detail.missing_labels_ru;
        var note = box.querySelector('.tco-note');
        if (note) {
          note.textContent = labels && labels.length
            ? 'Сначала заполните: ' + labels.join(', ') + '.'
            : 'Не получилось — попробуйте ещё раз из раздела «Каталог».';
        }
      }, function () {
        yes.disabled = false;
        yes.textContent = 'Показать меня';
      });
    };
  }

  /**
   * Открыть окно, если карточку можно опубликовать прямо сейчас. Возвращает Promise<boolean> — открылось ли.
   * `once: true` — не показывать, если тренер уже видел окно на этом устройстве (главная кабинета).
   */
  function maybeOpen(opts) {
    opts = opts || {};
    if (!opts.apiUrl || !opts.headers || !global.fetch) return Promise.resolve(false);
    if (opts.once && seen()) return Promise.resolve(false);
    return getJson(opts, '/trainer/catalog').then(function (o) {
      if (!o.ok || !eligible(o.data)) return false;
      render(o.data, opts);
      return true;
    }, function () { return false; });
  }

  var api = { maybeOpen: maybeOpen, eligible: eligible, placesPhrase: placesPhrase, SEEN_KEY: SEEN_KEY };
  global.TrainerCatalogOffer = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
