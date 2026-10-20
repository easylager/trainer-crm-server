/*
 * Лист «Поделиться» по требованию (TASK-305): на «Поиске» он нужен только по нажатию
 * «Позвать» / «Поделиться», а весит ~25 КБ сжатым. Пока настоящий лист не загружен,
 * GlideShareSheet — заглушка: страница видит, что шаринг есть, а open() догружает
 * mini-app-share-sheet.css/.js и открывает лист. После загрузки страницы лист
 * подтягивается сам в простое — первое нажатие обычно уже мгновенное.
 *
 * Версия файлов — из собственного ?v= (scripts/bump_webapp_assets.py держит её общей).
 */
(function (global) {
  'use strict';

  if (global.GlideShareSheet) return;
  var doc = global.document;
  var me = doc.currentScript && doc.currentScript.getAttribute('src');
  var version = me && /[?&]v=([^&]+)/.exec(me);
  var suffix = version ? '?v=' + version[1] : '';
  var base = me ? me.replace(/share-sheet-lazy\.js.*$/, '') : '';
  var loading = null;

  function load() {
    if (loading) return loading;
    loading = new Promise(function (resolve, reject) {
      var css = doc.createElement('link');
      css.rel = 'stylesheet';
      css.href = base + 'mini-app-share-sheet.css' + suffix;
      doc.head.appendChild(css);
      var js = doc.createElement('script');
      js.src = base + 'mini-app-share-sheet.js' + suffix;
      js.onload = function () { resolve(global.GlideShareSheet); };
      js.onerror = function () {
        loading = null;
        reject(new Error('share sheet failed to load'));
      };
      doc.head.appendChild(js);
    });
    return loading;
  }

  var stub = {
    lazy: true,
    load: load,
    open: function (opts) {
      load().then(function (real) {
        if (real && real !== stub && typeof real.open === 'function') real.open(opts);
      }).catch(function () { /* сеть: следующее нажатие попробует снова */ });
    },
    close: function () {
      if (global.GlideShareSheet && global.GlideShareSheet !== stub) global.GlideShareSheet.close();
    },
  };
  global.GlideShareSheet = stub;

  function warm() {
    var idle = global.requestIdleCallback || function (fn) { return global.setTimeout(fn, 1500); };
    idle(function () { load().catch(function () {}); }, { timeout: 4000 });
  }
  if (doc.readyState === 'complete') warm();
  else global.addEventListener('load', warm);
})(window);
