/**
 * Главная клиента — направление А «Сайт в кармане» (TASK-303, PDEC-023).
 *
 * Рисует из `home` в /client/hub/bootstrap: шапку города, слот «сейчас», «Ближайший лёд» и «Что нужно».
 * Личное («Мои занятия», запись сегодня, выбор города) рисует карточка клиента в client-home-main.js;
 * этот модуль только даёт ей место: HubHome.slot() и HubHome.mine().
 *
 * Только textContent и createElement — данные приходят с сервера и из чужих названий.
 */
(function (global) {
  'use strict';

  var doc = global.document;
  var tg = global.Telegram && global.Telegram.WebApp;
  var TZ = 'Europe/Minsk';
  // v2: в кэш попадает только фото, которое реально открылось. v1 хранил первый URL
  // сразу и на следующем заходе шапка начинала с 404.
  var CACHE_KEY = 'glide.hub.hero.v2';
  var GREETING = { morning: 'Доброе утро', day: 'Добрый день', evening: 'Добрый вечер', night: 'Доброй ночи' };
  var WD_SHORT = { понедельник: 'пн', вторник: 'вт', среда: 'ср', четверг: 'чт', пятница: 'пт', суббота: 'сб', воскресенье: 'вс' };
  var WEEKDAY_IN = ['в воскресенье', 'в понедельник', 'во вторник', 'в среду', 'в четверг', 'в пятницу', 'в субботу'];
  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  var NBSP = ' ';

  var ICON = {
    crown: 'M3 7l4.5 4L12 4l4.5 7L21 7l-2 12H5z',
    skate: 'M12 2v20M4.9 7l14.2 10M19.1 7 4.9 17M9 3.5l3 2.5 3-2.5M9 20.5l3-2.5 3 2.5',
    ohm: 'M15 3 8.5 17.5a2 2 0 0 1-1.8 1.2H3M3 21h8M16.5 21a2 2 0 1 0 0-.01',
    service: 'M3 16h14a3 3 0 0 0 3-3v-1H8L5.5 7H3zM3 20h18',
    shop: 'M5 8h14l-1 12H6zM9 8V6a3 3 0 0 1 6 0v2',
    coach: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0',
    chevron: 'm9 6 6 6-6 6',
    down: 'm6 9 6 6 6-6',
    invite: 'M9 11.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20a6.5 6.5 0 0 1 13 0M19 8v6M16 11h6',
  };

  // ---------- мелочи ----------

  function $(id) {
    return doc.getElementById(id);
  }

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function icon(name, cls) {
    var ns = 'http://www.w3.org/2000/svg';
    var s = doc.createElementNS(ns, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    // Корона — залитая: контуром в наклейке она не читается.
    s.setAttribute('fill', name === 'crown' ? 'currentColor' : 'none');
    s.setAttribute('stroke', name === 'crown' ? 'none' : 'currentColor');
    s.setAttribute('stroke-width', name === 'chevron' || name === 'down' ? '2' : '1.8');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    if (cls) s.setAttribute('class', cls);
    var p = doc.createElementNS(ns, 'path');
    p.setAttribute('d', ICON[name] || '');
    s.appendChild(p);
    return s;
  }

  function haptic() {
    try {
      if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
    } catch (e) { /* старый клиент */ }
  }

  function initData() {
    return (tg && tg.initData) || new URLSearchParams(global.location.search).get('init_data') || '';
  }

  function go(path) {
    var shell = global.ClientShell;
    if (shell && typeof shell.navigate === 'function') return shell.navigate(path);
    var data = initData();
    global.location.href = '/webapp/' + path + (data ? (path.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(data) : '');
  }

  function link(node, path) {
    node.href = path;
    node.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey) return;
      e.preventDefault();
      haptic();
      go(path);
    });
    return node;
  }

  function share(url, text) {
    if (!url) return;
    var target = 'https://t.me/share/url?url=' + encodeURIComponent(url) + '&text=' + encodeURIComponent(text || '');
    if (tg && typeof tg.openTelegramLink === 'function') tg.openTelegramLink(target);
    else global.open(target, '_blank');
  }

  function cacheRead() {
    try {
      return JSON.parse(global.localStorage.getItem(CACHE_KEY) || 'null');
    } catch (e) {
      return null;
    }
  }

  function cacheWrite(value) {
    try {
      global.localStorage.setItem(CACHE_KEY, JSON.stringify(value));
    } catch (e) { /* приватный режим — просто без кэша */ }
  }

  function minskParts(date) {
    var parts = {};
    new Intl.DateTimeFormat('en-GB', {
      timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', weekday: 'short', hourCycle: 'h23',
    }).formatToParts(date).forEach(function (p) { parts[p.type] = p.value; });
    return {
      y: Number(parts.year), m: Number(parts.month), d: Number(parts.day), hh: Number(parts.hour), mm: parts.minute,
      wd: { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[parts.weekday],
    };
  }

  /** «завтра, 19:30» — как в игре (kto-kogo-model.whenLabel). */
  function whenLabel(iso, now) {
    var p = minskParts(new Date(iso));
    var n = minskParts(now || new Date());
    var diff = (Date.UTC(p.y, p.m - 1, p.d) - Date.UTC(n.y, n.m - 1, n.d)) / 86400000;
    var day;
    if (diff === 0) day = 'сегодня';
    else if (diff === 1) day = 'завтра';
    else if (diff === -1) day = 'вчера';
    else if (diff > 1 && diff < 7) day = WEEKDAY_IN[p.wd];
    else day = p.d + NBSP + MONTHS[p.m - 1];
    return day + ', ' + p.hh + ':' + p.mm;
  }

  function minutesUntil(hhmm, now) {
    var m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm || ''));
    if (!m) return null;
    var n = minskParts(now || new Date());
    return Number(m[1]) * 60 + Number(m[2]) - (n.hh * 60 + Number(n.mm));
  }

  function plural(n, one, few, many) {
    var m10 = n % 10;
    var m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  /** «через 22 минуты» / «через 1 ч 15 мин» / «уже идёт». */
  function soonLabel(minutes) {
    if (minutes == null) return '';
    if (minutes <= 0) return 'уже идёт';
    if (minutes < 60) return 'через ' + minutes + NBSP + plural(minutes, 'минуту', 'минуты', 'минут');
    var h = Math.floor(minutes / 60);
    var rest = minutes % 60;
    return 'через ' + h + NBSP + 'ч' + (rest ? ' ' + rest + NBSP + 'мин' : '');
  }

  function greetingText(hour, name) {
    var part = hour >= 5 && hour < 12 ? 'morning' : hour >= 12 && hour < 17 ? 'day' : hour >= 17 && hour < 23 ? 'evening' : 'night';
    var clean = String(name == null ? '' : name).trim();
    return clean ? GREETING[part] + ', ' + clean : GREETING[part];
  }

  function shortKicker(kicker) {
    var s = String(kicker || '');
    var comma = s.indexOf(',');
    if (comma < 0) return s;
    var wd = s.slice(0, comma).toLowerCase();
    return (WD_SHORT[wd] || wd) + s.slice(comma);
  }

  // ---------- шапка ----------

  var heroSettle = Promise.resolve();
  var heroSettleResolve = function () {};
  var heroProbeGen = 0;

  function beginHeroSettle() {
    heroSettle = new Promise(function (resolve) { heroSettleResolve = resolve; });
  }

  function finishHeroSettle() {
    var resolve = heroSettleResolve;
    heroSettleResolve = function () {};
    resolve();
  }

  /**
   * Фото остаётся скрытым, пока файл не открылся. Битый URL — следующее фото города.
   * Прогрев других вкладок ждёт whenHeroSettled, чтобы не делить канал с шапкой.
   * Кандидаты пробуем отдельной картинкой. Уже показанное фото не снимаем,
   * пока запасное реально не открылось: иначе 404 первого катка гасит обложку.
   */
  // Каждая попытка — круг до сервера. Больше четырёх подряд на телефоне — секунды тёмной шапки.
  var HERO_MAX_TRIES = 4;
  // Прогрев вкладок не ждёт обложку дольше этого: фото — украшение, вкладки — дело.
  var HERO_SETTLE_MAX_MS = 1500;

  function armHeroPhoto(photo, list, onPhoto) {
    list = list.slice(0, HERO_MAX_TRIES);
    beginHeroSettle();
    var gen = ++heroProbeGen;
    var settled = false;
    function settle(src) {
      if (settled || gen !== heroProbeGen) return;
      settled = true;
      if (src && onPhoto) onPhoto(src);
      finishHeroSettle();
    }
    var showing = !!(photo.classList.contains('is-in') && !photo.hidden && photo.naturalWidth);
    function giveUp() {
      if (!showing) {
        photo.classList.remove('is-in');
        photo.hidden = true;
      }
      settle(null);
    }
    function tryAt(i) {
      if (gen !== heroProbeGen) return;
      if (i >= list.length) {
        giveUp();
        return;
      }
      var probe = new global.Image();
      // Шапка — самая крупная картинка экрана: пробный запрос идёт с тем же приоритетом, что и тег.
      if (i === 0) probe.fetchPriority = 'high';
      probe.onload = function () {
        if (gen !== heroProbeGen) return;
        if (!probe.naturalWidth) {
          tryAt(i + 1);
          return;
        }
        if (photo.getAttribute('src') !== list[i]) photo.src = list[i];
        revealHeroPhoto(photo);
        settle(list[i]);
      };
      probe.onerror = function () {
        if (gen !== heroProbeGen) return;
        tryAt(i + 1);
      };
      probe.src = list[i];
    }
    if (photo.getAttribute('src') === list[0] && photo.complete && photo.naturalWidth) {
      photo.hidden = false;
      photo.classList.add('is-in');
      settle(list[0]);
      return;
    }
    tryAt(0);
  }

  function revealHeroPhoto(photo) {
    photo.hidden = false;
    if (photo.classList.contains('is-in')) return;
    photo.classList.remove('is-in');
    if (typeof global.requestAnimationFrame === 'function') {
      global.requestAnimationFrame(function () { photo.classList.add('is-in'); });
    } else {
      photo.classList.add('is-in');
    }
  }

  function paintHero(hero) {
    var title = $('hubHeroTitle');
    var line = $('hubHeroLine');
    var sub = $('hubGreetingSub');
    var pill = $('hubCityLabel');
    var photo = $('hubHeroPhoto');
    if (title) {
      var name = hero.city || '';
      title.textContent = '';
      title.appendChild(doc.createTextNode(name || 'Лёд'));
      title.appendChild(el('br'));
      title.appendChild(doc.createTextNode(name ? 'на льду' : 'рядом'));
      title.classList.toggle('hh__title--long', name.length > 8);
    }
    if (line) line.textContent = hero.line || '';
    if (sub) {
      sub.textContent = hero.kicker ? ' · ' + hero.kicker : '';
      sub.hidden = !hero.kicker;
    }
    if (pill) pill.textContent = hero.city || 'Город';
    var list = hero.photos && hero.photos.length ? hero.photos : hero.photo ? [hero.photo] : [];
    if (photo && list.length) {
      // Файл не отдался — следующее фото города; кончились — тёмная плашка, а не значок битой картинки.
      armHeroPhoto(photo, list, hero.onPhoto);
    } else {
      if (photo) photo.hidden = true;
      finishHeroSettle();
    }
    var hh = $('hubHero');
    if (hh) hh.classList.remove('hh--loading');
  }

  function heroFrom(city) {
    if (!city) return { city: '', line: 'Выберите город — покажем лёд рядом', kicker: '', photo: null };
    var raw = city.hero_photos && city.hero_photos.length ? city.hero_photos : city.hero_photo ? [city.hero_photo] : [];
    var photos = [];
    raw.forEach(function (p) {
      if (!p) return;
      // card часто 404, хотя hero того же катка уже в кэше телефона. thumb не берём:
      // растянутый на 300px шапки, он мылит обложку хуже, чем фон без фото.
      [p.card, p.hero].forEach(function (src) {
        if (src && photos.indexOf(src) < 0) photos.push(src);
      });
    });
    return { city: city.name, line: city.counts_line || '', kicker: shortKicker(city.kicker), photo: photos[0] || null, photos: photos };
  }

  // ---------- слот «сейчас» ----------

  function teamButton(team, side, onPick) {
    var b = el('button', 'hn__team');
    b.type = 'button';
    b.setAttribute('aria-label', 'Я за ' + team.name);
    var logo = el('span', 'hn__logo');
    if (team.logo) {
      var img = el('img');
      img.src = team.logo;
      img.alt = '';
      logo.appendChild(img);
    } else {
      logo.textContent = team.short || '';
    }
    b.appendChild(logo);
    b.appendChild(doc.createTextNode(team.name));
    b.addEventListener('click', function () { onPick(side); });
    return b;
  }

  function teamLogo(team, cls) {
    var logo = el('span', cls || 'hn__logo');
    if (team && team.logo) {
      var img = el('img');
      img.src = team.logo;
      img.alt = '';
      logo.appendChild(img);
    } else {
      logo.textContent = (team && team.short) || '';
    }
    return logo;
  }

  var WD_TAG = ['ВС', 'ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ'];

  /** Метка ивента в углу карточки: МАТЧ · ПТ → ● СЕГОДНЯ → ● ИДЁТ → ИТОГ 3:2 (холст TASK-304, экран 10). */
  function eventTag(card, now) {
    var m = card.match;
    var r = m.result;
    if (card.mode === 'live') return { text: 'ИДЁТ', dot: true, live: true };
    if (r && r.home_score != null) return { text: 'ИТОГ ' + r.home_score + ':' + r.away_score, dot: false, live: false };
    // Последний матч месяца в гонке «Кто кого» (TASK-334): та же наклейка, другие слова.
    if (m.race_final) return { text: 'ФИНАЛ МЕСЯЦА', dot: false, live: false };
    var p = minskParts(new Date(m.starts_at));
    var n = minskParts(now || new Date());
    if (p.y === n.y && p.m === n.m && p.d === n.d) return { text: 'СЕГОДНЯ', dot: true, live: false };
    return { text: 'МАТЧ · ' + WD_TAG[p.wd], dot: false, live: false };
  }

  /** Домашний матч — ивент: вся карточка ведёт на его страницу, игра — уже там (TASK-304). */
  function eventCard(card, host) {
    var m = card.match;
    var tag = eventTag(card);
    var a = link(el('a', 'hn__card hn__ev'), card.event_href);
    a.setAttribute('aria-label', m.home.name + ' — ' + m.away.name + ', ' + tag.text.toLowerCase());
    var pair = el('span', 'hn__pair');
    pair.appendChild(teamLogo(m.home, 'hn__logo hn__logo--round'));
    pair.appendChild(teamLogo(m.away, 'hn__logo hn__logo--round'));
    a.appendChild(pair);
    var what = el('span', 'hn__what');
    what.appendChild(el('span', 'hn__name hn__name--one', m.home.name + ' — ' + m.away.name));
    var when = card.mode === 'live' ? 'идёт сейчас' : m.result ? whenLabel(m.starts_at).split(',')[0] : whenLabel(m.starts_at);
    what.appendChild(el('span', 'hn__sub hn__name--one', when + ' · Минск-Арена'));
    a.appendChild(what);
    a.appendChild(icon('chevron', 'hn__go hn__go--ev'));
    var t = el('span', 'hn__tag' + (tag.live ? ' hn__tag--live' : ''));
    t.setAttribute('aria-hidden', 'true');
    if (tag.dot) t.appendChild(el('span', 'hn__tag-dot'));
    t.appendChild(doc.createTextNode(tag.text));
    a.appendChild(t);
    host.replaceChildren(a);
  }

  // Карточка слота «сейчас» по kind; false — такой карточки нет.
  function nowCard(now, host) {
    var kind = now ? now.kind : 'none';
    if ((kind === 'kk_before' || kind === 'kk_result') && now.hockey && now.hockey.event_href) eventCard(now.hockey, host);
    else if (kind === 'kk_before') kkBefore(now.hockey, host);
    else if (kind === 'kk_result') kkResult(now.hockey, host);
    else if (kind === 'kk_month') kkMonth(now.hockey, host);
    else if (kind === 'ice') iceCard(now.session, host);
    else if (kind === 'extraliga') xlCard(now, host);
    else if (kind === 'more') moreCard(now, host);
    else return false;
    return true;
  }

  /*
   * TASK-340, экран 11: слот «сейчас» — лента. Матчи города и выезды его клуба, Динамо,
   * «N матчей на неделе». Каждая карточка рисуется своей функцией в свою ячейку.
   */
  function feed(items, host) {
    var strip = el('div', 'hn__feed');
    strip.setAttribute('role', 'list');
    strip.setAttribute('aria-label', 'Матчи на неделе');
    items.forEach(function (item) {
      var cell = el('div', 'hn__cell' + (item.kind === 'more' ? ' hn__cell--more' : ''));
      cell.setAttribute('role', 'listitem');
      if (nowCard(item, cell) && cell.firstChild) strip.appendChild(cell);
    });
    host.replaceChildren(strip);
    var n = strip.children.length;
    if (n < 2) return;
    var dots = el('div', 'hn__dots');
    dots.setAttribute('aria-hidden', 'true');
    for (var i = 0; i < n; i++) dots.appendChild(el('span', 'hn__dot' + (i ? '' : ' hn__dot--on')));
    host.appendChild(dots);
    strip.addEventListener('scroll', function () {
      var w = strip.firstChild.offsetWidth + 12;
      var at = strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 4 ? n - 1 : Math.round(strip.scrollLeft / w);
      Array.prototype.forEach.call(dots.children, function (d, j) {
        d.className = 'hn__dot' + (j === at ? ' hn__dot--on' : '');
      });
    }, { passive: true });
  }

  function xlCard(c, host) {
    var r = c.result;
    var a = link(el('a', 'hn__card hn__ev hn__xl'), c.href);
    var tag = c.live ? { text: 'ИДЁТ', dot: true, live: true }
      : r ? { text: 'ИТОГ ' + r.home_score + ':' + r.away_score }
      : c.sticker ? { text: c.sticker, dot: c.sticker === 'СЕГОДНЯ' } : null;
    a.setAttribute('aria-label', c.home.name + ' — ' + c.away.name + ', ' + whenLabel(c.starts_at) + (c.arena ? ', ' + c.arena : ''));
    var pair = el('span', 'hn__pair');
    pair.appendChild(teamLogo(c.home, 'hn__logo hn__logo--round'));
    pair.appendChild(teamLogo(c.away, 'hn__logo hn__logo--round'));
    a.appendChild(pair);
    var what = el('span', 'hn__what');
    what.appendChild(el('span', 'hn__name hn__name--one', c.home.name + ' — ' + c.away.name));
    var when = c.live ? 'идёт сейчас' : r ? whenLabel(c.starts_at).split(',')[0] : whenLabel(c.starts_at);
    var where = c.arena || c.city;
    what.appendChild(el('span', 'hn__sub hn__name--one', when + (where ? ' · ' + where : '')));
    a.appendChild(what);
    a.appendChild(icon('chevron', 'hn__go hn__go--ev'));
    if (tag) {
      var t = el('span', 'hn__tag' + (tag.live ? ' hn__tag--live' : ''));
      t.setAttribute('aria-hidden', 'true');
      if (tag.dot) t.appendChild(el('span', 'hn__tag-dot'));
      t.appendChild(doc.createTextNode(tag.text));
      a.appendChild(t);
    }
    host.replaceChildren(a);
  }

  function moreCard(c, host) {
    var a = link(el('a', 'hn__card hn__ev hn__more'), c.href || 'client-matches');
    var what = el('span', 'hn__what');
    what.appendChild(el('span', 'hn__more-n hh-display', String(c.count)));
    what.appendChild(el('span', 'hn__sub', plural(c.count, 'матч', 'матча', 'матчей') + ' на неделе'));
    what.appendChild(el('span', 'hn__more-go', 'Все матчи →'));
    a.appendChild(what);
    host.replaceChildren(a);
  }

  function kkBefore(card, host) {
    var m = card.match;
    var pick = card.my_pick;
    var root = el('section', 'hn__card');
    root.setAttribute('aria-label', 'Кто кого');
    if (pick && pick.side) {
      var mine = m[pick.side] || {};
      var row = link(el('a', 'hn__card'), 'kto-kogo');
      row.style.flexDirection = 'row';
      row.style.alignItems = 'center';
      var logo = el('span', 'hn__logo');
      if (mine.logo) {
        var img = el('img');
        img.src = mine.logo;
        img.alt = '';
        logo.appendChild(img);
      } else logo.textContent = mine.short || '';
      row.appendChild(logo);
      var what = el('span', 'hn__what');
      what.appendChild(el('span', 'hn__name', 'Ты за ' + mine.name));
      what.appendChild(el('span', 'hn__sub', m.home.name + ' — ' + m.away.name + ', ' + whenLabel(m.starts_at)));
      row.appendChild(what);
      var hasScore = pick.home_score != null;
      row.appendChild(el('span', 'hn__chip', hasScore ? pick.home_score + ':' + pick.away_score : 'счёт +50'));
      host.replaceChildren(row);
      return;
    }
    var head = el('div', 'hn__row');
    head.appendChild(el('span', 'hn__title hh-display', 'Кто кого?'));
    head.appendChild(el('span', 'hn__when', whenLabel(m.starts_at)));
    root.appendChild(head);
    var teams = el('div', 'hn__teams');
    function onPick(side) {
      haptic();
      var next = { mode: 'before', match: m, my_pick: { side: side, home_score: null, away_score: null } };
      kkBefore(next, host);
      fetch('/api/webapp/client/hockey/matches/' + m.id + '/pick', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData() },
        body: JSON.stringify({ side: side }),
      }).then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
      }).catch(function () {
        kkBefore(card, host);
      });
    }
    teams.appendChild(teamButton(m.home, 'home', onPick));
    teams.appendChild(teamButton(m.away, 'away', onPick));
    root.appendChild(teams);
    var hint = el('span', 'hn__hint', 'Без хода очков не будет. Точный счёт — ');
    hint.appendChild(el('b', 'hn__plus', '+50'));
    root.appendChild(hint);
    host.replaceChildren(root);
  }

  function kkResult(card, host) {
    var m = card.match;
    var r = m.result || {};
    var pts = card.points == null ? 0 : card.points;
    // Те же слова, что KtoKogoModel.verdict: модель игры на главную не грузим ради одной строки.
    var head = pts === 50 ? 'в точку!' : pts === 30 ? 'почти в точку' : pts === 20 ? 'есть победитель' : pts === 10 ? 'шайбы угаданы' : 'в этот раз мимо';
    var a = link(el('a', 'hn__card hn__card--dark'), 'kto-kogo?reveal=' + m.id);
    // ×2 (TASK-335): слова — по базовым очкам, наклейка — с умножением.
    var doubled = !!(card.my_pick && card.my_pick.doubled);
    a.appendChild(el('span', 'hn__sticker' + (pts ? '' : ' hn__sticker--miss'), pts ? '+' + (doubled ? pts * 2 : pts) : '0'));
    var what = el('span', 'hn__what');
    what.appendChild(el('span', 'hn__head hh-display', head));
    var line = m.home.name + ' — ' + m.away.name + ' ' + r.home_score + ':' + r.away_score;
    if (card.place) line += ' · ты ' + card.place.rank + '-й в лиге';
    what.appendChild(el('span', 'hn__sub', line));
    a.appendChild(what);
    a.appendChild(icon('chevron', 'hn__go'));
    host.replaceChildren(a);
  }

  /** Итог месяца «Кто кого» (TASK-334): сутки после финала, пока не открыли. Слова — как KtoKogoModel.monthHead. */
  function kkMonth(card, host) {
    var res = card.race || {};
    var won = !!res.won;
    var winners = res.winners || [];
    var head = won ? res.title + ' твой' : winners.length ? 'корона — ' + winners.join(' и ') : res.title + ' без короны';
    var where = res.league ? 'в «' + res.league.name + '»' : 'в общей таблице';
    var line = won ? 'Первое место ' + where : res.rank ? 'Ты ' + res.rank + '-й ' + where : 'Итоги ' + where;
    var a = link(el('a', 'hn__card hn__card--dark'), 'kto-kogo?month=' + res.race_id);
    a.setAttribute('aria-label', 'Итоги месяца: ' + head);
    var st = el('span', 'hn__sticker' + (won ? '' : ' hn__sticker--miss'));
    if (won) st.appendChild(icon('crown', 'hn__crown'));
    else st.textContent = res.rank ? String(res.rank) : '–';
    a.appendChild(st);
    var what = el('span', 'hn__what');
    what.appendChild(el('span', 'hn__head hh-display', head));
    what.appendChild(el('span', 'hn__sub', line + ' · все с нуля'));
    a.appendChild(what);
    a.appendChild(icon('chevron', 'hn__go'));
    host.replaceChildren(a);
  }

  function iceCard(s, host) {
    // Корень — не ссылка: внутри две разные цели, а интерактив в интерактиве WebView путает.
    var card = el('div', 'hn__card');
    var main = link(el('a', 'hn__main'), s.href || 'ice');
    var soon = s.label ? s.label.toLowerCase() : soonLabel(s.day === 'сегодня' ? minutesUntil(s.time) : null);
    main.appendChild(el('span', 'hn__live', 'Ближайший лёд' + (soon ? ' · ' + soon : s.day && s.day !== 'сегодня' ? ' · ' + s.day : '')));
    var big = el('span', 'hn__big');
    big.appendChild(el('span', 'hn__time hh-display', s.time));
    var what = el('span', 'hn__what');
    what.appendChild(el('span', 'hn__name', s.place));
    if (s.price) what.appendChild(el('span', 'hn__sub', s.price));
    big.appendChild(what);
    main.appendChild(big);
    card.appendChild(main);
    var btns = el('div', 'hn__btns');
    btns.appendChild(link(el('a', 'hn__btn', 'Подробнее'), s.href || 'ice'));
    if (s.invite_url) {
      var inv = el('button', 'hn__btn hn__btn--soft');
      inv.type = 'button';
      inv.appendChild(icon('invite'));
      inv.appendChild(doc.createTextNode('Позвать'));
      inv.addEventListener('click', function () {
        share(s.invite_url, 'Поехали на лёд: ' + s.place + ', ' + (s.day && s.day !== 'сегодня' ? s.day + ' ' : '') + s.time);
      });
      btns.appendChild(inv);
    } else if (s.pickCity) {
      // Города нет: второй шаг рядом — выбрать свой, а не искать его в шапке.
      btns.appendChild(link(el('a', 'hn__btn hn__btn--soft', 'Выбрать город'), 'ice'));
    }
    card.appendChild(btns);
    host.replaceChildren(card);
  }

  /** Города нет: ближайший лёд по стране или честное «пока не в вашем городе» (IceTeaserModel). */
  function teaserCard(teaser, host) {
    var model = global.IceTeaserModel;
    var v = model && typeof model.formatIceCard === 'function' ? model.formatIceCard(teaser, new Date()) : null;
    if (!v || v.hidden) {
      host.replaceChildren();
      return;
    }
    if (v.isFar) {
      var far = el('div', 'hn__card');
      far.appendChild(el('span', 'hn__live', v.kicker));
      far.appendChild(el('span', 'hn__name', v.title));
      far.appendChild(el('span', 'hn__sub', v.cityLine));
      var btns = el('span', 'hn__btns');
      btns.appendChild(link(el('a', 'hn__btn', 'Выбрать город'), 'ice'));
      btns.appendChild(link(el('a', 'hn__btn hn__btn--soft', v.cta || 'Смотреть каталог'), 'ice'));
      far.appendChild(btns);
      host.replaceChildren(far);
      return;
    }
    iceCard({ time: v.time, day: '', place: v.name + (v.city ? ', ' + v.city : ''), price: v.facts, href: v.href, invite_url: null, label: v.day, pickCity: true }, host);
  }

  /**
   * Модели «города нет» (тизер льда по стране, геолокация) — только тому, у кого города нет.
   * Клиенту с городом четыре файла в критическом пути не нужны (TASK-303, AC-P2).
   */
  var NO_CITY_SCRIPTS = ['minsk-time.js', 'schedule-staleness-model.js', 'ice-teaser-model.js', 'catalog-geo-model.js'];
  var noCityPromise = null;

  function assetVersion() {
    var own = doc && doc.querySelector('script[src*="hub-home.js"]');
    var m = own && /[?&]v=([^&]+)/.exec(own.getAttribute('src') || '');
    return m ? m[1] : '';
  }

  function loadScript(name, v) {
    return new Promise(function (resolve, reject) {
      var tag = doc.createElement('script');
      tag.src = name + (v ? '?v=' + v : '');
      tag.onload = resolve;
      tag.onerror = reject;
      doc.head.appendChild(tag);
    });
  }

  function needNoCityModels() {
    if (!noCityPromise) {
      var v = assetVersion();
      noCityPromise = NO_CITY_SCRIPTS.reduce(function (chain, name) {
        return chain.then(function () { return loadScript(name, v); });
      }, Promise.resolve());
    }
    return noCityPromise;
  }

  var lastTeaserHub = null;

  function showTeaser(teaser) {
    var host = $('hubNow');
    needNoCityModels().then(function () { teaserCard(teaser, host); }, function () { host.replaceChildren(); });
  }

  // ---------- «Ближайший лёд» и «Что нужно» ----------

  function nearest(city, skipFirst) {
    var sec = $('hubNearest');
    if (!sec) return;
    var items = (city && city.upcoming) || [];
    if (skipFirst) items = items.slice(1);
    if (!items.length) {
      sec.hidden = true;
      return;
    }
    var more = $('hubNearestMore');
    if (more) {
      more.textContent = city.upcoming_more || 'Весь день';
      link(more, city.upcoming_href || 'ice');
    }
    var row = $('hubNearestRow');
    row.replaceChildren();
    items.forEach(function (s) {
      // Ссылка накрывает карточку, «Позвать» — соседняя кнопка поверх: без кнопки внутри ссылки.
      var card = el('div', 'hl__card');
      var hit = link(el('a', 'hl__hit'), s.href || 'ice');
      hit.setAttribute('aria-label', s.place + ', ' + (s.badge || s.time));
      card.appendChild(hit);
      var ph = el('span', 'hl__photo');
      var src = s.photo && (s.photo.card || s.photo.thumb);
      if (src) {
        var img = el('img');
        img.src = src;
        img.alt = '';
        img.loading = 'lazy';
        img.decoding = 'async';
        img.onerror = function () { img.remove(); };
        ph.appendChild(img);
      }
      ph.appendChild(el('span', 'hl__time', s.badge || s.time));
      card.appendChild(ph);
      if (s.invite_url) {
        var inv = el('button', 'hl__invite', 'Позвать');
        inv.type = 'button';
        inv.addEventListener('click', function () {
          share(s.invite_url, 'Поехали на лёд: ' + s.place + ', ' + s.badge);
        });
        card.appendChild(inv);
      }
      var text = el('span', 'hl__text');
      text.appendChild(el('span', 'hl__name', s.place));
      if (s.price) text.appendChild(el('span', 'hl__price', s.price));
      card.appendChild(text);
      row.appendChild(card);
    });
    sec.hidden = false;
  }

  function needs(city) {
    var sec = $('hubNeeds');
    if (!sec) return;
    var rows = (city && city.needs) || [];
    if (!rows.length) {
      sec.hidden = true;
      return;
    }
    var list = $('hubNeedsList');
    list.replaceChildren();
    rows.forEach(function (n) {
      var row = el('div', 'hw__row');
      var hit = link(el('a', 'hw__link'), n.href);
      hit.setAttribute('aria-label', n.title);
      row.appendChild(hit);
      var ic = el('span', 'hw__icon');
      ic.appendChild(icon(n.key === 'ohm' ? 'ohm' : n.key));
      row.appendChild(ic);
      var body = el('span', 'hw__body');
      body.appendChild(el('span', 'hw__title', n.title));
      if (n.line) body.appendChild(el('span', 'hw__line', n.line));
      if (n.windows && n.windows.length) {
        var chips = el('span', 'hw__chips');
        n.windows.forEach(function (w) {
          var chip;
          if (w.href) {
            chip = link(el('a', 'hw__chip' + (w.hot ? ' hw__chip--hot' : '')), w.href);
            chip.appendChild(doc.createTextNode(w.label + ' '));
            chip.appendChild(el('small', null, String(w.count)));
          } else {
            chip = el('span', 'hw__chip hw__chip--off', w.label + ' —');
          }
          chips.appendChild(chip);
        });
        body.appendChild(chips);
      }
      row.appendChild(body);
      row.appendChild(icon('chevron', 'hw__go'));
      list.appendChild(row);
    });
    sec.hidden = false;
  }

  // ---------- сборка ----------

  var readySent = false;

  function ready() {
    if (readySent) return;
    readySent = true;
    try {
      global.dispatchEvent(new Event('glide:hub-ready'));
    } catch (e) { /* очень старый webview */ }
  }

  /**
   * Bootstrap пришёл. Возвращает вид слота: 'booking' и 'none' — место для карточки клиента,
   * остальное слот нарисовал сам.
   */
  function apply(hub) {
    var home = (hub && hub.home) || {};
    var city = home.city || null;
    var now = home.now || null;
    var hero = heroFrom(city);
    // В кэш — то фото, что действительно загрузилось: в следующий раз шапка не начнёт с битого.
    if (city) {
      // Пишем после onload: первый URL часто 404, и кэш не должен начинать следующий заход с него.
      hero.onPhoto = function (src) { cacheWrite({ city: hero.city, line: hero.line, photo: src, cityId: city.id }); };
    }
    paintHero(hero);
    var host = $('hubNow');
    var kind = now ? now.kind : 'none';
    if (kind === 'feed') feed(now.items || [], host);
    else if (nowCard(now, host)) { /* одна карточка */ }
    else if (!city && hub && hub.ice_teaser) {
      lastTeaserHub = hub;
      showTeaser(hub.ice_teaser);
    }
    else host.replaceChildren();
    nearest(city, kind === 'ice');
    needs(city);
    return kind;
  }

  /** До bootstrap: то, что было в прошлый раз, — шапка не мигает пустой. */
  function paintCached() {
    var cached = cacheRead();
    if (cached && cached.city) paintHero({ city: cached.city, line: cached.line, kicker: '', photo: cached.photo });
  }

  function fail() {
    paintHero(heroFrom(null));
    var host = $('hubNow');
    if (host) host.replaceChildren();
    ready();
  }

  global.HubHome = {
    apply: apply,
    paintCached: paintCached,
    whenHeroSettled: function () {
      return Promise.race([heroSettle, new Promise(function (r) { global.setTimeout(r, HERO_SETTLE_MAX_MS); })]);
    },
    fail: fail,
    ready: ready,
    greetingText: greetingText,
    needNoCityModels: needNoCityModels,
    /** Геолокация уточнила ближайший лёд — перерисовать слот, если города всё ещё нет. */
    refineTeaser: function (teaser) {
      if (lastTeaserHub && teaser) showTeaser(teaser);
    },
    slot: function () { return $('hubNow'); },
    mine: function () { return $('hubMine'); },
    // Для тестов.
    _whenLabel: whenLabel,
    _eventTag: eventTag,
    _soonLabel: soonLabel,
    _shortKicker: shortKicker,
  };

  /**
   * Тема: Mini App ставит `hub-is-dark` на <html> (client-mini-app-theme.js), а токены сайта
   * переключаются по `body.tg-dark`. На главной повторяем признак, общие токены не трогаем.
   */
  function syncDark() {
    if (!doc.body) return;
    doc.body.classList.toggle('tg-dark', doc.documentElement.classList.contains('hub-is-dark'));
  }

  if (typeof module === 'object' && module.exports) module.exports = global.HubHome;
  if (!doc) return; // node-тесты: только чистые функции
  syncDark();
  if (global.MutationObserver) {
    new MutationObserver(syncDark).observe(doc.documentElement, { attributes: true, attributeFilter: ['class'] });
  }
  paintCached();
})(typeof window !== 'undefined' ? window : globalThis);
