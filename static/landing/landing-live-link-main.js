(function () {
  'use strict';

  function readConfig() {
    var el = document.getElementById('landing-config');
    if (el && el.textContent) {
      try {
        return JSON.parse(el.textContent);
      } catch (e) {
        return null;
      }
    }
    return null;
  }

  function loadConfig(cb) {
    var cfg = readConfig();
    if (cfg) {
      cb(cfg);
      return;
    }
    fetch('/api/public/landing-config')
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        cb(data || {});
      })
      .catch(function () {
        cb({});
      });
  }

  function text(id, value) {
    var el = document.getElementById(id);
    if (el && value != null && value !== '') el.textContent = value;
  }

  function applyConfig(cfg) {
    var brand = cfg.brand || {};
    var hero = cfg.hero || {};
    var footer = cfg.footer || {};
    var cta = cfg.cta || {};

    var seo = cfg.seo || {};

    text('heroEyebrow', brand.eyebrow);
    text('heroTitle', hero.title);
    text('heroLede', hero.subtitle);
    text('closeTitle', cta.band_title);
    text('closeSub', cta.band_subtitle);
    text('footerBrand', brand.name);
    text('footerGeo', footer.geo);

    var label = hero.cta_primary || 'Начать в Telegram';
    document.querySelectorAll('.js-landing-cta').forEach(function (btn) {
      btn.textContent = label;
    });

    var demoLink = document.getElementById('demoInviteLink');
    if (demoLink) {
      var sample = 't.me/glide_bot?start=b_demo';
      var join = cfg.telegram_join_url || '';
      var m = join.match(/t\.me\/([^/?]+)/i);
      if (m) sample = 't.me/' + m[1] + '?start=b_demo';
      demoLink.textContent = sample;
    }

    if (seo.title) document.title = seo.title;
    else if (hero.title) document.title = hero.title + ' — Glide';
    window.__landingCfg = cfg;
  }

  function showError(msg) {
    var el = document.getElementById('landingError');
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    setTimeout(function () {
      el.hidden = true;
    }, 6000);
  }

  function startTelegram(btn) {
    var cfg = window.__landingCfg || {};
    var hero = cfg.hero || {};

    if (cfg.registration_enabled === false) {
      showError('Регистрация временно недоступна. Попробуйте позже.');
      return;
    }

    var ref = new URLSearchParams(window.location.search).get('ref') || '';
    var joinPath = (cfg.join_url || '/join') + (ref ? '?ref=' + encodeURIComponent(ref) : '');
    if (btn) {
      btn.disabled = true;
      btn.textContent = hero.cta_loading || 'Открываем Telegram…';
    }
    window.location.href = joinPath;
  }

  function bindCtas() {
    document.querySelectorAll('.js-landing-cta').forEach(function (btn) {
      btn.addEventListener('click', function () {
        startTelegram(btn);
      });
    });
  }

  function init() {
    loadConfig(function (cfg) {
      applyConfig(cfg);
      bindCtas();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
