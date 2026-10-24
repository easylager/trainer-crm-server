/* Лендинг тренера: к ссылкам «Начать» дописываем источник для аудита /join
   (ref, UTM из адреса страницы, внешний сайт-источник) и шлём цель trainer_join. */
(function () {
  'use strict';

  function config() {
    try {
      var el = document.getElementById('tl-config');
      return el ? JSON.parse(el.textContent || '{}') : {};
    } catch (e) {
      return {};
    }
  }

  function externalReferrerHost() {
    try {
      var host = document.referrer ? new URL(document.referrer).hostname : '';
      return host && host !== window.location.hostname ? host : '';
    } catch (e) {
      return '';
    }
  }

  function withSource(href) {
    var url;
    try {
      url = new URL(href, window.location.origin);
    } catch (e) {
      return href;
    }
    var here = new URLSearchParams(window.location.search);
    ['ref', 'utm_source', 'utm_medium', 'utm_campaign'].forEach(function (key) {
      var v = here.get(key);
      if (v && !url.searchParams.get(key)) url.searchParams.set(key, v);
    });
    var from = externalReferrerHost();
    if (from && !url.searchParams.get('from')) url.searchParams.set('from', from);
    return url.pathname + url.search;
  }

  function reportGoal(cfg) {
    try {
      if (cfg.ym_counter_id && typeof window.ym === 'function') window.ym(cfg.ym_counter_id, 'reachGoal', 'trainer_join');
      if (typeof window.gtag === 'function') window.gtag('event', 'trainer_join');
    } catch (e) { /* аналитика не мешает переходу */ }
  }

  function init() {
    var cfg = config();
    document.querySelectorAll('.js-tl-join').forEach(function (a) {
      a.setAttribute('href', withSource(a.getAttribute('href') || '/join'));
      a.addEventListener('click', function () { reportGoal(cfg); });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
