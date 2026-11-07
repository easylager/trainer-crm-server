/*
 * «Учиться с тренером» по требованию (TASK-354): страницы подключают только этот маленький файл.
 * Стили, модель витрины, модель блока и сам компонент (learn-block-core.js) догружаются, когда
 * блок реально собираются показать (mount), — как лист «Поделиться» (share-sheet-lazy.js):
 * «Поиск» и каток не платят весом за блок, который многим не нужен. hide() ничего не грузит.
 * Версия файлов — из собственного ?v= (scripts/bump_webapp_assets.py держит её общей).
 */
(function (global) {
  'use strict';

  if (global.LearnBlock) return;
  var doc = global.document;
  var me = doc.currentScript && doc.currentScript.getAttribute('src');
  var version = me && /[?&]v=([^&]+)/.exec(me);
  var suffix = version ? '?v=' + version[1] : '';
  var base = me ? me.replace(/learn-block\.js.*$/, '') : '';
  var loading = null;

  function script(name) {
    return new Promise(function (resolve, reject) {
      var js = doc.createElement('script');
      js.src = base + name + suffix;
      js.async = false;
      js.onload = resolve;
      js.onerror = function () { reject(new Error(name + ' failed to load')); };
      doc.head.appendChild(js);
    });
  }

  function style() {
    return new Promise(function (resolve) {
      var css = doc.createElement('link');
      css.rel = 'stylesheet';
      css.href = base + 'learn-block.css' + suffix;
      css.onload = resolve;
      css.onerror = resolve; // без стилей блок хуже, но экран не страдает
      doc.head.appendChild(css);
    });
  }

  function load() {
    if (loading) return loading;
    loading = Promise.all([
      style(),
      script('trainer-showcase-model.js')
        .then(function () { return script('learn-block-model.js'); })
        .then(function () { return script('learn-block-core.js'); }),
    ]).then(function () { return global.LearnBlock; }, function (e) {
      loading = null;
      throw e;
    });
    return loading;
  }

  function el(target) {
    return typeof target === 'string' ? doc.querySelector(target) : target;
  }

  global.LearnBlock = {
    lazy: true,
    mount: function (target, spec) {
      reserve(target, spec);
      return load().then(function (real) {
        if (real && real !== this_ && typeof real.mount === 'function') return real.mount(target, spec);
      }, function () {
        hideEl(target);
      });
    },
    hide: function (target) {
      if (global.LearnBlock !== this_) return global.LearnBlock.hide(target);
      hideEl(target);
    },
    clientCityId: function () {
      return load().then(function (real) { return real.clientCityId(); }, function () { return null; });
    },
  };
  var this_ = global.LearnBlock;

  function hideEl(target) {
    var host = el(target);
    if (!host) return;
    host.hidden = true;
    host.innerHTML = '';
    host.style.minHeight = '';
    host.style.margin = '';
    host.removeAttribute('data-lb-wait');
  }

  /* Место под блок, пока грузятся его файлы и данные (CSS ещё не пришёл — размеры инлайном):
     без этого контент ниже прыгает на высоту карточки (CLS). Высота — измеренная карточка без
     направлений-чипов (212) и с ними на «главной»/«Моих записях» (266). Пустой ответ/ошибка → hideEl. */
  function reserve(target, spec) {
    var host = el(target);
    if (!host || !host.hidden) return;
    host.hidden = false;
    host.style.margin = '12px 16px';
    host.style.minHeight = (spec && spec.place === 'city' ? 266 : 212) + 'px';
    host.setAttribute('data-lb-wait', '');
  }
})(window);
