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
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { cb(data || {}); })
      .catch(function () { cb({}); });
  }

  function text(id, value) {
    var el = document.getElementById(id);
    if (el && value != null) el.textContent = value;
  }

  function applyConfig(cfg) {
    var brand = cfg.brand || {};
    var hero = cfg.hero || {};
    var cta = cfg.cta || {};
    var footer = cfg.footer || {};
    var visual = cfg.visual || {};

    text('brandName', brand.name);
    text('heroEyebrow', brand.eyebrow);
    text('heroTagline', brand.tagline);
    text('heroTitle', hero.title);
    text('heroSub', hero.subtitle);
    text('ctaBandTitle', cta.band_title);
    text('ctaBandSub', cta.band_subtitle);
    text('footerBrand', brand.name);
    text('footerGeo', footer.geo);

    var primaryLabel = hero.cta_primary || 'Начать в Telegram';
    ['heroCta', 'bandCta', 'stickyCtaBtn'].forEach(function (id) {
      var btn = document.getElementById(id);
      if (btn) btn.textContent = primaryLabel;
    });
    if (visual.hero_image) {
      var photo = document.getElementById('heroPhoto');
      if (photo) {
        photo.style.backgroundImage = 'url("' + visual.hero_image + '")';
      }
      var preload = document.createElement('link');
      preload.rel = 'preload';
      preload.as = 'image';
      preload.href = visual.hero_image;
      document.head.appendChild(preload);
    }

    if (visual.hero_image_credit) {
      text('footerCredit', visual.hero_image_credit);
    }

    if (visual.bento_texture) {
      document.documentElement.style.setProperty(
        '--landing-bento-texture',
        'url("' + visual.bento_texture + '")'
      );
    }

    renderPillars(cfg.value_pillars || []);
    renderActivationArc(cfg.activation_arc || []);
    renderBento(cfg.bento || [], cfg.stats_labels || {});
    renderSteps(cfg.steps || []);

    var sections = cfg.sections || {};
    text('arcEyebrow', sections.arc_eyebrow);
    text('arcHeading', sections.arc_heading);
    text('arcSub', sections.arc_subtitle);
    text('bentoEyebrow', sections.bento_eyebrow);
    text('bentoHeading', sections.bento_heading);
    text('stepsEyebrow', sections.steps_eyebrow);
    text('stepsHeading', sections.steps_heading);

    window.__landingCfg = cfg;
  }

  function pillarIconSvg(icon) {
    if (icon === 'telegram') {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>';
    }
    if (icon === 'link') {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
    }
    if (icon === 'bell') {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>';
    }
    if (icon === 'notes') {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/></svg>';
    }
    if (icon === 'discover') {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>';
    }
    if (icon === 'chart') {
      return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 17V11"/><path d="M12 17V7"/><path d="M16 17v-4"/></svg>';
    }
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/></svg>';
  }

  function renderPillars(pillars) {
    var list = document.getElementById('heroPillars');
    if (!list) return;
    list.innerHTML = '';
    pillars.forEach(function (p) {
      var li = document.createElement('li');
      li.className = 'landing-pillar';
      li.innerHTML =
        '<span class="landing-pillar__icon" aria-hidden="true">' + pillarIconSvg(p.icon) + '</span>' +
        '<span>' + esc(p.label) + '</span>';
      list.appendChild(li);
    });
  }

  function arcStepMockHtml(id) {
    if (id !== 'link') return '';
    return (
      '<div class="landing-arc__mock" aria-hidden="true">' +
      '<div class="landing-arc__mock-url">' +
      '<span class="landing-arc__mock-url-bot">t.me/IceStudioBot</span>' +
      '<span class="landing-arc__mock-url-label">Запись к тренеру</span>' +
      '</div>' +
      '<div class="landing-arc__mock-row">' +
      '<span>Среда 18:00 · Свободно</span>' +
      '<span class="landing-arc__mock-cta">Записаться</span>' +
      '</div></div>'
    );
  }

  function renderActivationArc(steps) {
    var list = document.getElementById('arcList');
    if (!list) return;
    list.innerHTML = '';
    steps.forEach(function (step, i) {
      var li = document.createElement('li');
      li.className = 'landing-arc__step landing-reveal-scroll' + (step.id === 'link' ? ' landing-arc__step--link' : '');
      li.innerHTML =
        '<div class="landing-arc__head">' +
        '<span class="landing-arc__icon" aria-hidden="true">' +
        pillarIconSvg(step.icon).replace(/width="16"/g, 'width="18"').replace(/height="16"/g, 'height="18"') +
        '</span>' +
        '<div class="landing-arc__head-text">' +
        '<span class="landing-arc__num">' + String(i + 1).padStart(2, '0') + '</span>' +
        '<h3 class="landing-arc__title">' + esc(step.title) + '</h3>' +
        '</div></div>' +
        '<p class="landing-arc__body">' + esc(step.body) + '</p>' +
        arcStepMockHtml(step.id);
      list.appendChild(li);
    });
  }

  function bentoIconSvg(icon) {
    return pillarIconSvg(icon).replace(/width="16"/g, 'width="20"').replace(/height="16"/g, 'height="20"');
  }

  function bentoVizHtml(id) {
    if (id === 'slots') {
      return (
        '<div class="landing-bento__viz bv-sched" aria-hidden="true">' +
        '<p class="bv-sched__day">Среда · Minsk Arena</p>' +
        '<ul class="bv-sched__list">' +
        '<li class="bv-sched__row bv-sched__row--sky">' +
        '<span class="bv-sched__time">17:00</span>' +
        '<span class="bv-sched__main"><span class="bv-sched__name">Анна</span><span class="bv-sched__meta">Фигурное катание</span></span>' +
        '</li>' +
        '<li class="bv-sched__row bv-sched__row--free bv-sched__row--sky">' +
        '<span class="bv-sched__time">18:00</span>' +
        '<span class="bv-sched__main"><span class="bv-sched__name">Свободно</span><span class="bv-sched__meta">Клиент записывается сам</span></span>' +
        '<span class="bv-sched__cta">Запись</span>' +
        '</li>' +
        '<li class="bv-sched__row bv-sched__row--amber">' +
        '<span class="bv-sched__time">19:00</span>' +
        '<span class="bv-sched__main"><span class="bv-sched__name">Дарья</span><span class="bv-sched__meta">Minsk Arena</span></span>' +
        '</li>' +
        '</ul></div>'
      );
    }
    if (id === 'catalog') {
      return (
        '<div class="landing-bento__viz bv-catalog" aria-hidden="true">' +
        '<span class="bv-catalog__pill">Ice Studio · Минск</span>' +
        '<div class="bv-catalog__row">' +
        '<div class="bv-catalog__avatar"></div>' +
        '<div class="bv-catalog__main">' +
        '<p class="bv-catalog__name">Алексей <span>· тренер</span></p>' +
        '<p class="bv-catalog__meta">Minsk Arena · фигурное</p>' +
        '</div>' +
        '<span class="bv-catalog__cta">Запись</span>' +
        '</div></div>'
      );
    }
    if (id === 'analytics') {
      return (
        '<div class="landing-bento__viz bv-analytics" aria-hidden="true">' +
        '<p class="bv-analytics__banner">Неделя 16–22 июня</p>' +
        '<div class="bv-analytics__metrics">' +
        '<div class="bv-analytics__metric"><strong>12</strong><span>записей</span></div>' +
        '<div class="bv-analytics__metric bv-analytics__metric--hi"><strong>840</strong><span>BYN</span></div>' +
        '<div class="bv-analytics__metric"><strong>+3</strong><span>новых</span></div>' +
        '</div>' +
        '<div class="bv-analytics__spark" aria-hidden="true">' +
        '<span style="height:38%"></span><span style="height:55%"></span>' +
        '<span class="is-peak" style="height:72%"></span><span style="height:48%"></span>' +
        '<span class="is-peak" style="height:88%"></span><span style="height:62%"></span>' +
        '<span style="height:44%"></span></div></div>'
      );
    }
    if (id === 'notes') {
      return (
        '<div class="landing-bento__viz bv-dossier" aria-hidden="true">' +
        '<div class="bv-dossier__client">' +
        '<div class="bv-dossier__avatar">А</div>' +
        '<div><p class="bv-dossier__name">Анна К.</p><p class="bv-dossier__sub">Фигурное · Minsk Arena</p></div>' +
        '</div>' +
        '<div class="bv-dossier__tags">' +
        '<span class="bv-d-tag">Фигурное</span>' +
        '<span class="bv-d-tag">Новичок</span>' +
        '<span class="bv-d-tag bv-d-tag--sys">12 занятий</span>' +
        '</div>' +
        '<div class="bv-dossier__profile">' +
        '<div class="bv-dossier__profile-head"><span>Профиль клиента</span><span class="bv-dossier__chev">▾</span></div>' +
        '<p class="bv-dossier__field-label">Цели</p>' +
        '<p class="bv-dossier__field-val">Программа на сезон · тройной аксель</p>' +
        '<div class="bv-dossier__season"><span class="bv-d-season">Соревнования</span><span class="bv-d-season">Техника</span></div>' +
        '</div>' +
        '<div class="bv-dossier__timeline">' +
        '<div class="bv-dossier__tl-head"><span>Заметки по занятиям</span><span class="bv-dossier__add">+ Добавить</span></div>' +
        '<div class="bv-d-entry"><span class="bv-d-entry__date">12.06</span><span class="bv-d-entry__text">Отработали кремлё — увереннее на левом</span></div>' +
        '<div class="bv-d-entry"><span class="bv-d-entry__date">05.06</span><span class="bv-d-entry__text">План: раскладка перед тренировкой</span></div>' +
        '</div></div>'
      );
    }
    return '';
  }

  function appendBentoHead(cell, item, kickerExtra) {
    if (!item.kicker && !item.icon) return;
    var head = document.createElement('div');
    head.className = 'landing-bento__head';
    if (item.kicker) {
      var kick = document.createElement('span');
      kick.className = 'landing-bento__kicker' + (kickerExtra ? ' ' + kickerExtra : '');
      kick.textContent = item.kicker;
      head.appendChild(kick);
    }
    if (item.icon) {
      var badge = document.createElement('span');
      badge.className = 'landing-bento__badge';
      badge.setAttribute('aria-hidden', 'true');
      badge.innerHTML = bentoIconSvg(item.icon);
      head.appendChild(badge);
    }
    cell.appendChild(head);
  }

  function renderBento(items, labels) {
    var grid = document.getElementById('bentoGrid');
    if (!grid) return;
    grid.innerHTML = '';

    items.forEach(function (item) {
      var cell = document.createElement('article');
      cell.className = 'landing-bento__cell landing-reveal-scroll';

      if (item.size === 'large') {
        cell.classList.add('landing-bento__cell--large', 'landing-bento__cell--slots', 'has-texture');
      } else if (item.size === 'stat') {
        cell.classList.add('landing-bento__cell--stat');
        appendBentoHead(cell, item, 'landing-bento__kicker--live');
        if (item.title) {
          var st = document.createElement('h3');
          st.className = 'landing-bento__title';
          st.textContent = item.title;
          cell.appendChild(st);
        }
        var statWrap = document.createElement('div');
        statWrap.className = 'landing-bento__stat';
        statWrap.id = 'bentoStats';
        statWrap.innerHTML =
          '<div class="landing-stat"><span class="landing-stat__num" data-stat="trainers">—</span>' +
          '<span class="landing-stat__label">' + esc(labels.trainers || 'тренеров') + '</span></div>' +
          '<div class="landing-stat"><span class="landing-stat__num" data-stat="arenas">—</span>' +
          '<span class="landing-stat__label">' + esc(labels.arenas || 'арен') + '</span></div>' +
          '<div class="landing-stat"><span class="landing-stat__num" data-stat="cities">—</span>' +
          '<span class="landing-stat__label">' + esc(labels.cities || 'городов') + '</span></div>';
        cell.appendChild(statWrap);
        grid.appendChild(cell);
        return;
      } else if (item.size === 'quote') {
        cell.classList.add('landing-bento__cell--quote');
        var q = document.createElement('p');
        q.className = 'landing-bento__body';
        q.textContent = item.body || '';
        cell.appendChild(q);
        grid.appendChild(cell);
        return;
      } else if (item.id === 'analytics') {
        cell.classList.add('landing-bento__cell--analytics', 'landing-bento__cell--medium');
      } else if (item.id === 'catalog') {
        cell.classList.add('landing-bento__cell--catalog', 'landing-bento__cell--medium');
      } else if (item.id === 'notes') {
        cell.classList.add('landing-bento__cell--notes', 'landing-bento__cell--wide');
      } else if (item.size === 'wide') {
        cell.classList.add('landing-bento__cell--wide');
      } else {
        cell.classList.add('landing-bento__cell--medium');
      }

      var isLarge = item.size === 'large';
      var content = document.createElement('div');
      content.className = 'landing-bento__copy';

      appendBentoHead(content, item, '');

      if (item.title) {
        var h = document.createElement('h3');
        h.className = 'landing-bento__title';
        h.textContent = item.title;
        content.appendChild(h);
      }
      if (item.body) {
        var p = document.createElement('p');
        p.className = 'landing-bento__body';
        p.textContent = item.body;
        content.appendChild(p);
      }

      var vizHtml = bentoVizHtml(item.id);
      cell.appendChild(content);
      if (vizHtml) cell.insertAdjacentHTML('beforeend', vizHtml);

      grid.appendChild(cell);
    });
  }

  function renderSteps(steps) {
    var list = document.getElementById('stepsList');
    if (!list) return;
    list.innerHTML = '';
    steps.forEach(function (step, i) {
      var li = document.createElement('li');
      li.className = 'landing-step landing-reveal-scroll';
      li.innerHTML =
        '<span class="landing-step__num">' + (i + 1) + '</span>' +
        '<h3 class="landing-step__title">' + esc(step.title) + '</h3>' +
        '<p class="landing-step__body">' + esc(step.body) + '</p>';
      list.appendChild(li);
    });
  }

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showError(msg) {
    var el = document.getElementById('landingError');
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    setTimeout(function () { el.hidden = true; }, 6000);
  }

  function startTelegram(btn) {
    var cfg = window.__landingCfg || {};
    var hero = cfg.hero || {};

    if (cfg.registration_enabled === false) {
      showError('Регистрация временно недоступна. Попробуйте позже.');
      return;
    }

    var ref = new URLSearchParams(window.location.search).get('ref') || '';
    var joinPath = (cfg.join_url || '/join') + (ref ? ('?ref=' + encodeURIComponent(ref)) : '');
    if (btn) {
      var loading = hero.cta_loading || 'Открываем Telegram…';
      btn.disabled = true;
      btn.textContent = loading;
    }
    window.location.href = joinPath;
  }

  function bindCtas() {
    ['heroCta', 'bandCta', 'stickyCtaBtn'].forEach(function (id) {
      var btn = document.getElementById(id);
      if (btn) {
        btn.addEventListener('click', function () { startTelegram(btn); });
      }
    });
  }

  function animateCount(el, target, duration) {
    if (!el || isNaN(target)) return;
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      el.textContent = String(target);
      return;
    }
    var start = 0;
    var t0 = performance.now();
    function frame(now) {
      var p = Math.min(1, (now - t0) / duration);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = String(Math.round(start + (target - start) * eased));
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function loadStats() {
    fetch('/api/public/platform-stats')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var map = {
          trainers: data.trainers_total,
          arenas: data.arenas_count,
          cities: data.cities_count,
        };
        Object.keys(map).forEach(function (key) {
          var el = document.querySelector('[data-stat="' + key + '"]');
          if (el && map[key] != null) animateCount(el, map[key], 900);
        });
      })
      .catch(function () {});
  }

  function setupScrollReveal() {
    var nodes = document.querySelectorAll('.landing-reveal-scroll, .landing-bento__cell, .landing-step, .landing-arc__step');
    if (!('IntersectionObserver' in window)) {
      nodes.forEach(function (n) { n.classList.add('is-visible'); });
      var stepsList = document.getElementById('stepsList');
      if (stepsList) stepsList.classList.add('is-visible');
      var arcList = document.getElementById('arcList');
      if (arcList) arcList.classList.add('is-visible');
      return;
    }
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: '0px 0px -8% 0px' }
    );
    nodes.forEach(function (n) { io.observe(n); });

    var stepsList = document.getElementById('stepsList');
    var arcList = document.getElementById('arcList');
    if (stepsList) {
      var stepsIo = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              stepsList.classList.add('is-visible');
              stepsIo.disconnect();
            }
          });
        },
        { threshold: 0.2 }
      );
      stepsIo.observe(stepsList);
    }
    if (arcList) {
      var arcIo = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              arcList.classList.add('is-visible');
              arcIo.disconnect();
            }
          });
        },
        { threshold: 0.15 }
      );
      arcIo.observe(arcList);
    }
  }

  function setupStickyCta() {
    var sticky = document.getElementById('stickyCta');
    var heroCta = document.getElementById('heroCta');
    var bandCta = document.getElementById('bandCta');
    if (!sticky || window.matchMedia('(min-width: 860px)').matches) return;

    var heroVisible = true;
    var bandVisible = false;

    function syncSticky() {
      // One primary CTA on screen: hide sticky when hero or closing band CTA is visible.
      var show = !heroVisible && !bandVisible && window.scrollY > 48;
      sticky.hidden = !show;
      document.body.classList.toggle('landing--sticky-cta', show);
    }

    if (typeof IntersectionObserver === 'function') {
      var io = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.target === heroCta) heroVisible = entry.isIntersecting;
            if (entry.target === bandCta) bandVisible = entry.isIntersecting;
          });
          syncSticky();
        },
        {
          threshold: 0.15,
          rootMargin: '0px 0px -72px 0px',
        }
      );
      if (heroCta) io.observe(heroCta);
      if (bandCta) io.observe(bandCta);
    }

    window.addEventListener('scroll', syncSticky, { passive: true });
    syncSticky();
  }

  function setupPhoneTilt() {
    var phone = document.getElementById('phoneMock');
    if (!phone || window.matchMedia('(max-width: 859px)').matches) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    phone.classList.add('landing-phone--tilt');
    window.addEventListener(
      'scroll',
      function () {
        var y = Math.min(1, window.scrollY / (window.innerHeight * 0.6));
        var rotX = y * 4;
        var rotY = y * -3;
        phone.style.transform = 'rotateX(' + rotX + 'deg) rotateY(' + rotY + 'deg)';
      },
      { passive: true }
    );
  }

  function setupShowcaseRotate() {
    var showcase = document.getElementById('landingShowcase');
    if (!showcase) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      showcase.setAttribute('data-screen', 'hub');
      return;
    }
    var ms = 4500;
    var timer = null;
    function tick() {
      var cur = showcase.getAttribute('data-screen') || 'hub';
      showcase.setAttribute('data-screen', cur === 'schedule' ? 'hub' : 'schedule');
    }
    function start() {
      if (timer) clearInterval(timer);
      timer = setInterval(tick, ms);
    }
    function stop() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) stop();
      else start();
    });
    start();
  }

  function runIntro() {
    requestAnimationFrame(function () {
      document.body.classList.remove('landing--intro');
      document.body.classList.add('landing--ready');
    });
  }

  loadConfig(function (cfg) {
    applyConfig(cfg);
    bindCtas();
    setupStickyCta();
    setupPhoneTilt();
    setupShowcaseRotate();
    setupScrollReveal();
    loadStats();
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', runIntro);
    } else {
      runIntro();
    }
  });
})();
