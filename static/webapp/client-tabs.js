/**
 * TASK-391 (PDEC-035): оболочка с живыми вкладками «Я» и «Записи».
 *
 * Сервер отдаёт её вместо страницы вкладки, только когда включён флаг fast_tabs; признак —
 * <html data-ft-shell="me|bookings">. Без него файл не загружается вовсе, и всё идёт по-старому.
 *
 * Вкладка — контейнер .ft-tab в body. Первая пришла с html; вторая — фрагментом
 * /webapp/client-tab/{tab}.json?v= (тело её страницы без скриптов, её стили и скрипты по порядку).
 * Контракт вкладки:
 *   mount(el)  — разметка, недостающие стили на свои места в каскаде, скрипты страницы по порядку
 *                (уже загруженные по имени файла не повторяются), затем то, что страница делала на
 *                DOMContentLoaded для всего документа (сегменты ga-touch, мост «Назад»);
 *   show()     — контейнер, свои классы body, title, видимость бара, своя прокрутка; стили чужой
 *                вкладки выключены (media="not all") — каскад каждой вкладки как на её странице;
 *   hide()     — запомнить прокрутку, классы body и видимость бара, спрятать;
 *   refresh()  — событие client-tabs:refresh {tab}: код страницы тихо перезапрашивает данные.
 * Любой сбой загрузки — обычный переход, как без флага.
 *
 * Модель (чистые функции) — window.ClientTabsModel и module.exports для node-тестов.
 */
(function (root) {
  'use strict';

  var TAB_PATHS = { me: 'client-me', bookings: 'client-bookings' };
  /* Показ вкладки берёт данные из памяти; фоновое обновление — не чаще, чем раз в 10 с. */
  var REFRESH_AFTER_MS = 10000;
  var LOAD_TIMEOUT_MS = 8000;
  /* Классы body, которые принадлежат документу, а не вкладке: тема, оболочка, хаб. */
  var GLOBAL_BODY_CLASS = /^(tg-|client-shell-|hub-)/;
  /* Скрипты, которые во второй раз выполнять нельзя ни при каких условиях: признак — их глобал. */
  var ONCE_GLOBALS = {
    'telegram-web-app.js': 'Telegram',
    'mini-app-client-shell.js': 'ClientShell',
    'client-tabs.js': 'ClientTabs',
    'client-profile-switcher.js': 'ClientProfileSwitcher',
    'mini-app-telegram-chrome.js': 'MiniAppBack',
  };

  /* ── Модель ─────────────────────────────────────────────────────────────── */

  /** Имя файла без каталога и query: один и тот же файл по /webapp/ и /static/webapp/ — один ключ. */
  function assetKey(url) {
    var s = String(url || '').split('#')[0].split('?')[0];
    return s.slice(s.lastIndexOf('/') + 1).toLowerCase();
  }

  /** «client-me», «./client-bookings?x», «/webapp/client-me.html» → {key, query}. */
  function parsePath(path) {
    var raw = String(path || '').split('#')[0];
    var q = raw.indexOf('?');
    var p = q >= 0 ? raw.slice(0, q) : raw;
    var query = q >= 0 ? raw.slice(q + 1) : '';
    p = p.replace(/^\.\//, '').replace(/\/$/, '');
    var key = p.slice(p.lastIndexOf('/') + 1).replace(/\.html$/, '');
    return { key: key, dir: p.slice(0, p.lastIndexOf('/') + 1), query: query };
  }

  function tabForKey(key, paths) {
    var map = paths || TAB_PATHS;
    for (var id in map) {
      if (Object.prototype.hasOwnProperty.call(map, id) && map[id] === key) return id;
    }
    return null;
  }

  /**
   * Вкладка оболочки по адресу перехода — только голый путь: любой свой query (open_booking,
   * from=hub…) читается страницей при загрузке, поэтому такой переход — полной загрузкой.
   * Каталог — только тот же, что у оболочки (/webapp/ или относительный).
   */
  function tabForPath(path, paths) {
    var parsed = parsePath(path);
    if (parsed.dir && parsed.dir !== '/webapp/' && parsed.dir !== '/static/webapp/') return null;
    var params = parsed.query ? parsed.query.split('&') : [];
    for (var i = 0; i < params.length; i++) {
      var name = params[i].split('=')[0];
      if (name && name !== 'init_data') return null;
    }
    return tabForKey(parsed.key, paths);
  }

  /** Адрес вкладки для истории: каталог оболочки + путь + тот же init_data, больше ничего. */
  function tabUrl(tabPath, pathname, search) {
    var dir = String(pathname || '/webapp/').replace(/[^/]*$/, '') || '/webapp/';
    var init = '';
    try {
      init = new URLSearchParams(search || '').get('init_data') || '';
    } catch (e) {
      init = '';
    }
    return dir + tabPath + (init ? '?init_data=' + encodeURIComponent(init) : '');
  }

  /**
   * Что сделать при показе вкладки (и при возврате страницы из bfcache):
   *  reload  — активный профиль сменился на другой странице: память документа (переключатель,
   *            данные вкладок) от прежнего профиля, честный сброс — перезагрузка;
   *  refresh — данные старше REFRESH_AFTER_MS: показать из памяти и тихо обновить;
   *  none    — свежие.
   */
  function decideOnShow(o) {
    if (o.profileNow !== o.profileAtMount) return 'reload';
    if (!(o.refreshedAt > 0) || o.now - o.refreshedAt >= REFRESH_AFTER_MS || o.now < o.refreshedAt) return 'refresh';
    return 'none';
  }

  function ownedBodyClasses(classes) {
    var out = [];
    for (var i = 0; i < classes.length; i++) {
      var c = classes[i];
      if (c && !GLOBAL_BODY_CLASS.test(c) && out.indexOf(c) < 0) out.push(c);
    }
    return out;
  }

  /** Ключ стиля из фрагмента: файл — по имени, встроенный — по вкладке и номеру. */
  function cssKey(entry, tab, index) {
    return entry.href ? assetKey(entry.href) : 'code:' + tab + ':' + index;
  }

  /**
   * Порядок выполнения скриптов страницы: обычные по порядку, затем defer (как у парсера).
   * Уже выполненные (по имени файла) и «однократные» пропускаются.
   */
  function scriptPlan(scripts, loadedKeys, hasGlobal) {
    var plain = [];
    var deferred = [];
    for (var i = 0; i < scripts.length; i++) {
      var s = scripts[i];
      if (s.src) {
        var key = assetKey(s.src);
        if (loadedKeys[key]) continue;
        if (ONCE_GLOBALS[key] && hasGlobal && hasGlobal(ONCE_GLOBALS[key])) continue;
        (s.defer ? deferred : plain).push({ src: s.src, key: key });
      } else if (s.code) {
        plain.push({ code: s.code });
      }
    }
    return plain.concat(deferred);
  }

  var model = {
    TAB_PATHS: TAB_PATHS,
    REFRESH_AFTER_MS: REFRESH_AFTER_MS,
    assetKey: assetKey,
    parsePath: parsePath,
    tabForKey: tabForKey,
    tabForPath: tabForPath,
    tabUrl: tabUrl,
    decideOnShow: decideOnShow,
    ownedBodyClasses: ownedBodyClasses,
    cssKey: cssKey,
    scriptPlan: scriptPlan,
  };
  root.ClientTabsModel = model;
  if (typeof module === 'object' && module.exports) module.exports = model;

  /* ── Оболочка ───────────────────────────────────────────────────────────── */

  var doc = root.document;
  if (!doc || !doc.documentElement || typeof doc.documentElement.getAttribute !== 'function') return;
  var initialTab = doc.documentElement.getAttribute('data-ft-shell');
  if (!initialTab || !TAB_PATHS[initialTab] || root.ClientTabs) return;

  var ASSET_V = (function () {
    var cur = doc.currentScript;
    var m = cur && /[?&]v=(\d+)/.exec(cur.src || '');
    return m ? m[1] : '';
  })();
  var PROFILE_KEY = 'cw_active_profile_id_v1';

  function now() {
    return Date.now();
  }

  function profileNow() {
    try {
      return root.localStorage.getItem(PROFILE_KEY) || '';
    } catch (e) {
      return '';
    }
  }

  function shell() {
    return root.ClientShell || null;
  }

  /* Реестр стилей: ключ → элемент. Стили страницы — всё, что в head до стиля оболочки. */
  var cssByKey = {};
  var head = doc.head;
  (function registerPageCss() {
    var n = 0;
    for (var el = head.firstElementChild; el; el = el.nextElementSibling) {
      var tag = el.tagName;
      if (tag === 'STYLE' && /\.ft-tab\{/.test(el.textContent || '')) break;
      var key = null;
      if (tag === 'LINK' && /(^|\s)stylesheet(\s|$)/i.test(el.getAttribute('rel') || '')) key = assetKey(el.getAttribute('href'));
      else if (tag === 'STYLE') key = el.getAttribute('data-file') ? assetKey(el.getAttribute('data-file')) : 'boot:' + n++;
      if (key && !cssByKey[key]) {
        cssByKey[key] = el;
        el.__ftMedia = el.getAttribute('media');
      }
    }
  })();

  function loadedScriptKeys() {
    var keys = {};
    var list = doc.querySelectorAll('script[src], script[data-file]');
    for (var i = 0; i < list.length; i++) {
      keys[assetKey(list[i].getAttribute('src') || list[i].getAttribute('data-file'))] = true;
    }
    return keys;
  }

  var tabs = {};
  function entry(id) {
    if (!tabs[id]) {
      tabs[id] = {
        id: id,
        path: TAB_PATHS[id],
        el: null,
        mounted: false,
        cssKeys: null,
        title: '',
        bodyClasses: [],
        barVisible: true,
        scrollY: 0,
        refreshedAt: 0,
        profileAtMount: null,
      };
    }
    return tabs[id];
  }

  var active = initialTab;
  (function adoptInitial() {
    var t = entry(initialTab);
    t.el = doc.querySelector('.ft-tab[data-ft-tab="' + initialTab + '"]');
    t.mounted = !!t.el;
    t.cssKeys = {};
    for (var k in cssByKey) t.cssKeys[k] = true;
    t.title = doc.title;
    t.refreshedAt = now();
    t.profileAtMount = profileNow();
    try {
      root.history.replaceState({ ftTab: initialTab }, '', root.location.href);
    } catch (e) { /* без истории — переходы всё равно работают */ }
  })();

  function applyCss(t) {
    for (var key in cssByKey) {
      var el = cssByKey[key];
      if (t.cssKeys[key]) {
        if (el.__ftMedia) el.setAttribute('media', el.__ftMedia);
        else el.removeAttribute('media');
      } else {
        el.setAttribute('media', 'not all');
      }
    }
  }

  function hide(t) {
    t.scrollY = root.scrollY || root.pageYOffset || 0;
    var body = doc.body;
    t.bodyClasses = ownedBodyClasses(String(body.className || '').split(/\s+/));
    t.bodyClasses.forEach(function (c) {
      body.classList.remove(c);
    });
    t.barVisible = !body.classList.contains('client-shell-tabs-hidden');
    t.el.hidden = true;
  }

  function show(t) {
    var body = doc.body;
    t.bodyClasses.forEach(function (c) {
      body.classList.add(c);
    });
    applyCss(t);
    t.el.hidden = false;
    if (t.title) doc.title = t.title;
    var sh = shell();
    if (sh && typeof sh.setTabBarVisible === 'function') sh.setTabBarVisible(t.barVisible);
    /* Корень вкладки — без стрелки «назад» в шапке Telegram, как при загрузке страницы. */
    if (root.MiniAppBack && typeof root.MiniAppBack.clear === 'function') root.MiniAppBack.clear();
    if (typeof root.scrollTo === 'function') root.scrollTo(0, t.scrollY);
  }

  function refresh(t) {
    t.refreshedAt = now();
    if (typeof root.CustomEvent !== 'function') return;
    root.dispatchEvent(new root.CustomEvent('client-tabs:refresh', { detail: { tab: t.id } }));
  }

  /* Переход внутри оболочки — тоже нажатие на вкладку: tab-timing с nav=shell. */
  function armTiming() {
    var sh = shell();
    if (sh && typeof sh.armTabTiming === 'function') sh.armTabTiming('shell');
  }

  function switchDone() {
    var sh = shell();
    if (sh && typeof sh.tabSwitchDone === 'function') sh.tabSwitchDone();
  }

  /* ── Фрагмент и его ассеты ─────────────────────────────────────────────── */

  var fragments = {};
  /* Уже поставленные preload: повтор не нужен, а второй link с тем же href Chrome качает снова. */
  var preloaded = {};

  /**
   * Прогрев файла для будущего <link rel=stylesheet> / <script src>.
   * fetch() этого не делает: ответ лежит в кэше другого режима запроса, и тег качает файл заново
   * (замер: те же URL, transferSize как у первой загрузки, ~150 мс на файл, скрипты по очереди).
   * rel=preload с тем же as браузер отдаёт тегу из своего preload-кэша и в Chromium, и в WebKit.
   * rel=prefetch нельзя: WebKit его не выполняет, а Chrome при no-store качает дважды.
   */
  function preloadAsset(href, as) {
    if (!href || preloaded[href]) return Promise.resolve();
    preloaded[href] = true;
    return new Promise(function (resolve) {
      var el = doc.createElement('link');
      el.rel = 'preload';
      el.setAttribute('as', as);
      el.onload = function () { resolve(); };
      el.onerror = function () { resolve(); };
      el.href = href;
      head.appendChild(el);
    });
  }

  function fragmentUrl(id) {
    var dir = (root.location.pathname || '/webapp/').replace(/[^/]*$/, '') || '/webapp/';
    return dir + 'client-tab/' + id + '.json' + (ASSET_V ? '?v=' + ASSET_V : '');
  }

  function loadFragment(id) {
    if (!fragments[id]) {
      fragments[id] = root
        .fetch(fragmentUrl(id), { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error('fragment ' + r.status);
          return r.json();
        })
        .then(function (f) {
          if (!f || f.tab !== id || typeof f.html !== 'string' || !Array.isArray(f.css) || !Array.isArray(f.scripts)) {
            throw new Error('fragment schema');
          }
          return f;
        });
      fragments[id].catch(function () {
        delete fragments[id];
      });
    }
    return fragments[id];
  }

  function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
      var timer = root.setTimeout(function () {
        reject(new Error('timeout'));
      }, ms);
      promise.then(
        function (v) {
          root.clearTimeout(timer);
          resolve(v);
        },
        function (e) {
          root.clearTimeout(timer);
          reject(e);
        }
      );
    });
  }

  /** Стили вкладки: недостающие встают перед следующим своим соседом — каскад как на её странице. */
  function ensureCss(t, frag) {
    var keys = {};
    var waits = [];
    var next = null;
    for (var i = frag.css.length - 1; i >= 0; i--) {
      var c = frag.css[i];
      var key = cssKey(c, t.id, i);
      keys[key] = true;
      var el = cssByKey[key];
      if (!el) {
        if (c.href) {
          el = doc.createElement('link');
          el.rel = 'stylesheet';
          el.href = c.href;
          waits.push(
            new Promise(function (resolve, reject) {
              el.onload = resolve;
              el.onerror = reject;
            })
          );
        } else {
          el = doc.createElement('style');
          el.textContent = c.code;
        }
        el.__ftMedia = null;
        /* Пока вкладка не показана, её стили не трогают текущую. */
        el.setAttribute('media', 'not all');
        if (next && next.parentNode === head) head.insertBefore(el, next);
        else head.appendChild(el);
        cssByKey[key] = el;
      }
      next = el;
    }
    t.cssKeys = keys;
    return Promise.all(waits);
  }

  function runScripts(t, frag) {
    var plan = scriptPlan(frag.scripts, loadedScriptKeys(), function (name) {
      return !!root[name];
    });
    return plan.reduce(function (chain, step) {
      return chain.then(function () {
        return new Promise(function (resolve, reject) {
          var s = doc.createElement('script');
          if (step.code != null) {
            s.textContent = step.code;
            t.el.appendChild(s);
            resolve();
            return;
          }
          s.async = false;
          s.onload = function () {
            resolve();
          };
          s.onerror = function () {
            reject(new Error('script ' + step.key));
          };
          s.src = step.src;
          t.el.appendChild(s);
        });
      });
    }, Promise.resolve());
  }

  /* Что страница делала на DOMContentLoaded для всего документа, — для новой вкладки. */
  function afterMount(t) {
    try {
      if (root.GlideTouch && typeof root.GlideTouch.enhance === 'function') root.GlideTouch.enhance(t.el);
    } catch (e) { /* */ }
    try {
      if (root.MiniAppBack && typeof root.MiniAppBack.bridgeLegacy === 'function') root.MiniAppBack.bridgeLegacy();
    } catch (e) { /* */ }
  }

  function mount(t, frag) {
    var el = doc.createElement('div');
    el.className = 'ft-tab';
    el.setAttribute('data-ft-tab', t.id);
    el.setAttribute('data-ft-path', t.path);
    el.innerHTML = frag.html;
    var last = doc.querySelectorAll('.ft-tab');
    var anchor = last[last.length - 1];
    anchor.parentNode.insertBefore(el, anchor.nextSibling);
    t.el = el;
    t.title = frag.title || '';
    t.bodyClasses = ownedBodyClasses(String(frag.bodyClass || '').split(/\s+/));
    t.barVisible = true;
    t.scrollY = 0;
    t.mounted = true;
    t.refreshedAt = now();
    t.profileAtMount = profileNow();
  }

  /* ── Роутер ─────────────────────────────────────────────────────────────── */

  var pending = null;

  function fallback(url, pushed) {
    pending = null;
    try {
      if (pushed) root.location.reload();
      else root.location.href = url;
    } catch (e) { /* */ }
  }

  function activate(id, opts) {
    var from = tabs[active];
    var t = entry(id);
    if (from && from !== t && from.el) hide(from);
    active = id;
    show(t);
    switchDone();
    var decision = decideOnShow({
      now: now(),
      refreshedAt: t.refreshedAt,
      profileAtMount: t.profileAtMount,
      profileNow: profileNow(),
    });
    if (decision === 'reload') {
      root.location.reload();
      return;
    }
    if (!(opts && opts.silent)) {
      armTiming();
      var sh = shell();
      if (sh && typeof sh.contentShown === 'function') sh.contentShown();
    }
    if (decision === 'refresh') refresh(t);
  }

  function openTab(id, url, opts) {
    var t = entry(id);
    var pop = !!(opts && opts.pop);
    if (t.mounted) {
      pending = null;
      if (!pop) root.history.pushState({ ftTab: id }, '', url);
      activate(id, opts);
      return;
    }
    pending = id;
    var pushed = false;
    withTimeout(
      loadFragment(id).then(function (frag) {
        return ensureCss(t, frag).then(function () {
          return frag;
        });
      }),
      LOAD_TIMEOUT_MS
    )
      .then(function (frag) {
        if (pending !== id) return null;
        if (!pop) {
          root.history.pushState({ ftTab: id }, '', url);
          pushed = true;
        }
        var from = tabs[active];
        if (from && from.el) hide(from);
        mount(t, frag);
        active = id;
        show(t);
        armTiming();
        return withTimeout(runScripts(t, frag), LOAD_TIMEOUT_MS).then(function () {
          afterMount(t);
          pending = null;
          switchDone();
        });
      })
      .catch(function () {
        if (pending !== id && !pushed) return;
        fallback(url, pushed || pop);
      });
  }

  /**
   * Переход из ClientShell.navigate: true — взял роутер (вкладка оболочки), false — обычный переход.
   */
  function go(path) {
    var id = tabForPath(path);
    if (!id || typeof root.history.pushState !== 'function') return false;
    var url = tabUrl(TAB_PATHS[id], root.location.pathname, root.location.search);
    if (id === active) {
      /* Нажали другую вкладку и тут же вернулись: недогруженная не показывается. */
      pending = null;
      switchDone();
      return true;
    }
    openTab(id, url, null);
    return true;
  }

  root.addEventListener('popstate', function (ev) {
    var key = parsePath(root.location.pathname).key;
    var id = (ev && ev.state && ev.state.ftTab) || tabForKey(key);
    if (!id || !TAB_PATHS[id]) {
      root.location.reload();
      return;
    }
    if (id === active) return;
    if (!entry(id).mounted) {
      root.location.reload();
      return;
    }
    pending = null;
    activate(id, { pop: true, silent: true });
  });

  /* «Назад» из вторичного экрана вернул оболочку из bfcache: профиль мог смениться, данные — устареть. */
  root.addEventListener('pageshow', function (ev) {
    if (!ev || !ev.persisted) return;
    var t = entry(active);
    if (decideOnShow({ now: now(), refreshedAt: 1, profileAtMount: t.profileAtMount, profileNow: profileNow() }) === 'reload') {
      root.location.reload();
      return;
    }
    for (var id in tabs) {
      if (id !== active) tabs[id].refreshedAt = 0;
    }
    refresh(t);
  });

  function prefetch(id) {
    var t = entry(id);
    if (t.mounted || !TAB_PATHS[id]) return Promise.resolve();
    return loadFragment(id)
      .then(function (frag) {
        var loaded = loadedScriptKeys();
        var waits = [];
        frag.css.forEach(function (c) {
          if (c.href && !cssByKey[assetKey(c.href)]) waits.push(preloadAsset(c.href, 'style'));
        });
        frag.scripts.forEach(function (s) {
          if (s.src && !loaded[assetKey(s.src)] && /\?v=\d+/.test(s.src)) waits.push(preloadAsset(s.src, 'script'));
        });
        return Promise.all(waits);
      })
      .catch(function () {});
  }

  root.ClientTabs = {
    hosted: true,
    hosts: function (id) {
      return !!TAB_PATHS[id];
    },
    isMounted: function (id) {
      return !!(tabs[id] && tabs[id].mounted);
    },
    active: function () {
      return active;
    },
    go: go,
    prefetch: prefetch,
  };
})(typeof window !== 'undefined' ? window : globalThis);
