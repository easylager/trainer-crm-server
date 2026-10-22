/**
 * Партнёр рядом с катком: шторка и экран «Показать на кассе».
 * Один модуль на сайт (/p/…) и Mini App (arena.html); данные — card.partners
 * (src/application/arena_partners.py). Цвета — токены --g-* (glide-tokens.css).
 */
(function (global) {
  'use strict';

  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var ICONS = {
    close: 'M6 6l12 12M18 6L6 18',
    walk: 'M13 4.5a1.5 1.5 0 1 0 0-.01M10 21l2-6 3 3v3M9 12l1.5-4 3.5 1 2 3 2 1M10.5 8L7 10v3',
    clock: 'M12 4a8 8 0 1 0 0 16a8 8 0 1 0 0-16M12 8v4l3 2',
    pin: 'M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11zM12 8a2 2 0 1 0 0 4a2 2 0 1 0 0-4',
    phone: 'M6.5 3.5h3l1.5 4-2 1.5a12 12 0 0 0 6 6l1.5-2 4 1.5v3a2 2 0 0 1-2 2A15 15 0 0 1 4.5 5.5a2 2 0 0 1 2-2z',
    ig: 'M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4zm5 5a4 4 0 1 0 0 8a4 4 0 0 0 0-8zm6.5-1.8h.01',
  };

  var dialog = null;
  var timer = null;
  var current = null;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }

  function icon(name) {
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('class', 'gp-icon');
    var p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', ICONS[name]);
    svg.appendChild(p);
    return svg;
  }

  function capitalize(s) {
    s = String(s || '');
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  }

  function pad(n) { return n < 10 ? '0' + n : String(n); }

  function stamp() {
    var d = new Date();
    return 'Сегодня, ' + d.getDate() + ' ' + MONTHS[d.getMonth()] + ' · ' +
      d.getHours() + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

  function beacon(action) {
    if (!current || !navigator.sendBeacon) return;
    var o = current.opts;
    var q = 'action=' + action + '&surface=' + encodeURIComponent(o.surface || 'place_page') +
      '&partner=' + encodeURIComponent(current.partner.slug);
    if (o.cityId) q += '&city_id=' + encodeURIComponent(String(o.cityId));
    if (o.arenaId) q += '&arena_id=' + encodeURIComponent(String(o.arenaId));
    try { navigator.sendBeacon('/api/public/catalog/contact-click?' + q); } catch (e) { /* учёт не мешает показу */ }
  }

  function openExternal(url, e) {
    var tg = global.Telegram && global.Telegram.WebApp;
    if (tg && tg.initData && typeof tg.openLink === 'function') {
      if (e) e.preventDefault();
      tg.openLink(url);
    }
  }

  function fact(name, text) {
    var li = el('li', 'gp-fact');
    li.appendChild(icon(name));
    li.appendChild(el('span', '', text));
    return li;
  }

  function buildCard(p) {
    var sec = el('section', 'gp-card');
    var close = el('button', 'gp-close');
    close.type = 'button';
    close.setAttribute('aria-label', 'Закрыть');
    close.appendChild(icon('close'));
    close.addEventListener('click', hide);
    sec.appendChild(close);

    if (p.photos && p.photos.length) {
      var strip = el('div', 'gp-photos');
      p.photos.forEach(function (src) {
        var img = el('img');
        img.src = src;
        img.alt = '';
        img.decoding = 'async';
        strip.appendChild(img);
      });
      sec.appendChild(strip);
    }

    var head = el('header', 'gp-head');
    if (p.logo) {
      var logo = el('img', 'gp-logo');
      logo.src = p.logo;
      logo.alt = '';
      head.appendChild(logo);
    }
    var names = el('div', 'gp-names');
    var h = el('h2', 'gp-name', p.name);
    h.id = 'gp-title';
    names.appendChild(h);
    names.appendChild(el('p', 'gp-line', [p.line, 'партнёр Glide'].filter(Boolean).join(' · ')));
    head.appendChild(names);
    sec.appendChild(head);

    var long = String(p.offer || '').length > 10;
    var offer = el('div', 'gp-offer' + (long ? ' gp-offer--long' : ''));
    offer.appendChild(el('b', 'gp-offer__big' + (long ? ' gp-offer__big--long' : ''), p.offer));
    var offerText = el('span', 'gp-offer__text');
    if (p.offer_note) offerText.appendChild(el('strong', '', p.offer_note));
    offerText.appendChild(el('span', '', 'Покажите экран на кассе'));
    offer.appendChild(offerText);
    sec.appendChild(offer);

    var facts = el('ul', 'gp-facts');
    if (p.where) facts.appendChild(fact('walk', capitalize(p.where)));
    if (p.hours) facts.appendChild(fact('clock', p.hours));
    if (facts.childNodes.length) sec.appendChild(facts);

    var contacts = el('div', 'gp-contacts');
    if (p.phone && p.phone_tel) {
      var tel = el('a', 'gp-contact');
      tel.href = p.phone_tel;
      tel.appendChild(icon('phone'));
      tel.appendChild(el('span', '', p.phone));
      contacts.appendChild(tel);
    }
    if (p.instagram) {
      var ig = el('a', 'gp-contact');
      ig.href = p.instagram;
      ig.target = '_blank';
      ig.rel = 'noopener nofollow';
      ig.appendChild(icon('ig'));
      ig.appendChild(el('span', '', '@' + (p.instagram_handle || 'instagram')));
      ig.addEventListener('click', function (e) { openExternal(p.instagram, e); });
      contacts.appendChild(ig);
    }
    if (contacts.childNodes.length) sec.appendChild(contacts);

    var actions = el('div', 'gp-actions');
    var show = el('button', 'gp-btn gp-btn--main', 'Показать на кассе');
    show.type = 'button';
    show.addEventListener('click', showCounter);
    actions.appendChild(show);
    if (p.maps_url) {
      var route = el('a', 'gp-btn gp-btn--quiet');
      route.href = p.maps_url;
      route.target = '_blank';
      route.rel = 'noopener';
      route.appendChild(icon('pin'));
      route.appendChild(document.createTextNode('Маршрут'));
      route.addEventListener('click', function (e) { openExternal(p.maps_url, e); });
      actions.appendChild(route);
    }
    sec.appendChild(actions);
    return sec;
  }

  function buildCounter(p, opts) {
    var sec = el('section', 'gp-counter');
    sec.hidden = true;
    var top = el('div', 'gp-counter__top');
    top.appendChild(el('span', 'gp-counter__brand', 'Glide'));
    var done = el('button', 'gp-counter__done', 'Готово');
    done.type = 'button';
    done.addEventListener('click', hide);
    top.appendChild(done);
    sec.appendChild(top);

    var mid = el('div', 'gp-counter__mid');
    if (p.logo) {
      var logo = el('img', 'gp-counter__logo');
      logo.src = p.logo;
      logo.alt = p.name;
      mid.appendChild(logo);
    }
    var long = String(p.offer || '').length > 10;
    mid.appendChild(el('span', 'gp-counter__for', (/[−\-]\d+\s*%/.test(p.offer) ? 'Скидка в ' : 'Акция в ') + p.name));
    mid.appendChild(el('span', 'gp-counter__big' + (long ? ' gp-counter__big--long' : ''), p.offer));
    if (p.code) {
      var code = el('div', 'gp-counter__code');
      code.appendChild(el('span', 'gp-counter__kicker', 'Промокод'));
      code.appendChild(el('span', 'gp-counter__word', p.code));
      mid.appendChild(code);
    }
    var live = el('div', 'gp-counter__live');
    live.appendChild(el('span', 'gp-counter__dot'));
    var clock = el('span', 'gp-counter__clock', stamp());
    live.appendChild(clock);
    mid.appendChild(live);
    sec.appendChild(mid);

    if (opts.placeName) sec.appendChild(el('p', 'gp-counter__foot', 'С катка: ' + opts.placeName));
    sec._clock = clock;
    return sec;
  }

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = el('dialog', 'gp');
    dialog.setAttribute('aria-labelledby', 'gp-title');
    dialog.addEventListener('click', function (e) {
      if (e.target === dialog) hide();
    });
    dialog.addEventListener('close', stopClock);
    document.body.appendChild(dialog);
    return dialog;
  }

  function stopClock() {
    if (timer) global.clearInterval(timer);
    timer = null;
  }

  function showCounter() {
    if (!dialog) return;
    var card = dialog.querySelector('.gp-card');
    var counter = dialog.querySelector('.gp-counter');
    card.hidden = true;
    counter.hidden = false;
    dialog.classList.add('gp--counter');
    counter._clock.textContent = stamp();
    stopClock();
    timer = global.setInterval(function () { counter._clock.textContent = stamp(); }, 1000);
    beacon('partner_show');
  }

  function hide() {
    stopClock();
    if (dialog && dialog.open) dialog.close();
  }

  function open(partner, opts) {
    if (!partner) return;
    current = { partner: partner, opts: opts || {} };
    var d = ensureDialog();
    d.classList.remove('gp--counter');
    d.textContent = '';
    d.appendChild(buildCard(partner));
    d.appendChild(buildCounter(partner, current.opts));
    if (typeof d.showModal === 'function') d.showModal();
    else d.setAttribute('open', '');
    beacon('partner_open');
  }

  /** Строки блока «После катка» с data-partner — по клику открывают шторку. */
  function bind(root, partners, opts) {
    if (!root || !partners || !partners.length) return;
    var bySlug = {};
    partners.forEach(function (p) { bySlug[p.slug] = p; });
    root.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('[data-partner]');
      if (!a || !root.contains(a)) return;
      var p = bySlug[a.getAttribute('data-partner')];
      if (!p) return;
      e.preventDefault();
      open(p, opts);
    });
  }

  global.GlidePartners = { open: open, bind: bind, close: hide };
})(window);
