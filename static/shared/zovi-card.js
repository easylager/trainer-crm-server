/**
 * TASK-232: открытка «Пойдёшь со мной на каток?» — механика и экраны.
 * Механика перенесена из утверждённого прототипа design/prototypes/2026-10-11-zovi-na-katok.html
 * без изменений: пружины, толчок, борта, пять актов, DWELL, уворот, покачивание, салют, штамп.
 * Отличие от прототипа — только источник данных (JSON из SSR) и вызовы API (TASK-231).
 */
(function () {
  'use strict';
  var M = window.ZoviModel;
  var $ = function (id) { return document.getElementById(id); };
  var DATA = {};
  try { DATA = JSON.parse($('zoviData').textContent || '{}'); } catch (e) { DATA = {}; }
  var CODE = String(DATA.code || '');
  var API = '/api/public/invites/' + encodeURIComponent(CODE);
  var PAGE = '/zovi/' + encodeURIComponent(CODE);

  var state = { to: DATA.to_name || '', from: DATA.from_name || '', tries: 0, answered: false };
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Воронка — TASK-237. «Открыто» и «да» пишет сервер сам (GET карточки и POST answer);
     маячок нужен только тому, чего сервер не видит: попыткам «нет» (с номером акта) и «отправить ответ». */
  var BEACONS = { no_attempt: 'invite_no_attempt', send_answer: 'invite_send_answer' };
  function track(name, data) {
    var kind = BEACONS[name];
    if (!kind || !CODE) return;
    var body = JSON.stringify(M.eventBody(kind, deviceToken, data && data.act));
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(API + '/event', new Blob([body], { type: 'application/json' }))) return;
    } catch (e) { /* ниже запасной путь */ }
    try {
      fetch(API + '/event', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true, credentials: 'same-origin' })
        .catch(function () { /* маячок не повторяем */ });
    } catch (e) { /* */ }
  }

  /* ================= Токен устройства ================= */
  /* В приватном режиме хранилища может не быть: тогда токен живёт до закрытия страницы. */
  var deviceToken = (function () {
    var key = 'zovi_device', tok = '';
    try { tok = window.localStorage.getItem(key) || ''; } catch (e) { tok = ''; }
    if (/^[0-9a-f]{32}$/.test(tok)) return tok;
    var bytes = new Uint8Array(16);
    try { window.crypto.getRandomValues(bytes); } catch (e) { for (var i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256); }
    tok = Array.prototype.map.call(bytes, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
    try { window.localStorage.setItem(key, tok); } catch (e) { /* приватный режим */ }
    return tok;
  })();

  /* ================= Данные → экран ================= */
  function session() { return DATA.session || { arena: {} }; }
  function arena() { return session().arena || {}; }
  function placeLine() {
    var a = arena(), s = session();
    var parts = [a.name];
    if (a.address) parts.push(a.address);
    var line = parts.filter(Boolean).join(', ');
    return s.price ? line + ' · ' + s.price : line;
  }
  function routeUrl() {
    var a = arena();
    var q = [a.city, a.address || a.name].filter(Boolean).join(', ');
    return 'https://yandex.by/maps/?text=' + encodeURIComponent(q);
  }

  function paintQuestion() {
    var q = $('question'), p = M.questionParts(state.to, DATA.kind);
    q.textContent = '';
    if (p.name) {
      var n = document.createElement('span'); n.className = 'name'; n.textContent = p.name; q.appendChild(n);
    }
    q.appendChild(document.createTextNode(p.rest));
  }

  function paint() {
    var s = session(), who = M.ticketWho(state.to, state.from);
    $('fromG').textContent = M.decline(state.from, 'gen');
    $('fromN').textContent = state.from || 'Отправитель';
    // Пуш создателю есть только у открыток из Telegram; иначе билет — единственный путь к нему.
    $('sentNote').hidden = !DATA.creator_notified;
    $('sendBtn').textContent = DATA.creator_notified ? 'Поделиться билетом' : 'Отправить билет ' + M.decline(state.from, 'dat');
    paintQuestion();
    $('tixTo').textContent = who[0];
    $('tixFrom').textContent = who[1];
    $('tixTime').textContent = s.starts_at_local || '';
    $('tixDay').textContent = M.dayLabel(s.local_date, 'ticket');
    $('tixPlace').textContent = placeLine();
    $('routeLink').href = routeUrl();
    paintCalendar();
  }

  /* iPhone открывает .ics сам; Android — Google Календарь; компьютер — .ics и ссылка на Google. */
  function paintCalendar() {
    var s = session(), a = arena();
    var platform = M.calendarPlatform(navigator.userAgent, navigator.maxTouchPoints > 1);
    var ics = PAGE + '/event.ics';
    var gcal = M.googleCalendarUrl(
      DATA.calendar_title || '',
      s.starts_at_utc, s.ends_at_utc,
      [a.name, a.address, a.city].filter(Boolean).join(', '),
      window.location.origin + PAGE
    );
    var cal = $('calBtn'), alt = $('calAlt');
    if (platform === 'android') {
      cal.href = gcal;
      cal.target = '_blank';
      cal.rel = 'noopener';
      alt.hidden = true;
      return;
    }
    cal.href = ics;
    alt.href = gcal;
    alt.hidden = platform !== 'desktop';
  }

  /* ================= Персонаж «Нет» ================= */
  /* Кнопка «Нет» — новичок на коньках. Пять актов, у каждого своя реплика и движение.
     Акт меняется не чаще, чем раз в DWELL мс, и только когда кнопка доехала: реплику
     успевают прочитать, даже если гонять курсор без остановки. */
  var DWELL = 1900;

  function Spring(v, k, c) { this.x = v; this.v = 0; this.to = v; this.k = k; this.c = c; }
  Spring.prototype.step = function (dt) { var a = -this.k * (this.x - this.to) - this.c * this.v; this.v += a * dt; this.x += this.v * dt; };
  Spring.prototype.done = function () { return Math.abs(this.x - this.to) < 0.25 && Math.abs(this.v) < 0.8; };
  Spring.prototype.snap = function (v) { this.x = this.to = v; this.v = 0; };

  var rink = $('rink'), noBtn = $('noBtn'), yesBtn = $('yesBtn'), trail = $('trail');
  /* Скольжение ~0.9 с с мягким докатом. Наклон — недодемпфирован: кнопка балансирует. */
  var nx = new Spring(0, 34, 9.6), ny = new Spring(0, 34, 9.6);
  var rot = new Spring(0, 70, 5.5), sq = new Spring(1, 150, 11), ys = new Spring(1, 90, 13);
  /* «Да» тоже ездит: в акте перестановки кнопки меняются местами. */
  var yx = new Spring(0, 30, 9), yy = new Spring(0, 30, 9);
  var masked = false, swapUntil = 0;
  var raf = 0, lastT = 0, points = [], nextActAt = 0, lastPress = -1e9, lying = false, timers = [];
  var stats = { first: 0, falls: 0 }, idleTimer = 0;
  /* Где курсор сейчас. Нужен и во время скольжения: кнопка не должна въехать под неподвижную мышь. */
  var ptr = null, lastDodge = -1e9, NEAR = 72, DODGE_GAP = 240;

  /* Пока «Нет» не трогают, она нервно балансирует: зовёт попробовать.
     Иначе половина людей сразу жмёт «Да» и не видит представления. */
  function idleWobble() {
    clearInterval(idleTimer);
    if (reduce) return;
    idleTimer = setInterval(function () {
      if (state.answered || state.tries > 0 || rink.hidden) return;
      rot.v += (Math.random() < .5 ? -1 : 1) * 55;
      kick();
    }, 2600);
  }

  function later(fn, ms) { timers.push(setTimeout(fn, reduce ? Math.min(ms, 300) : ms)); }
  function clearLater() { timers.forEach(clearTimeout); timers = []; }

  function rinkBox() { return { w: rink.clientWidth, h: rink.clientHeight }; }
  function noBox() { return { w: noBtn.offsetWidth, h: noBtn.offsetHeight }; }
  /* Прямоугольник «Да» вокруг её цели — с запасом 12 px, чтобы «Нет» не прилипала. */
  function yesBox() { return { x: yx.to - 12, y: yy.to - 12, w: yesBtn.offsetWidth * ys.x + 24, h: yesBtn.offsetHeight * ys.x + 24 }; }

  function apply() {
    /* Наклон в сторону движения: так держат равновесие на льду. Чем позже акт — тем хуже держит. */
    var wob = state.tries >= 4 ? 0.6 : 0.25 + state.tries * 0.12;
    var lean = Math.max(-14, Math.min(14, nx.v * 0.035 * wob * 2));
    noBtn.style.transform = 'translate(' + nx.x.toFixed(2) + 'px,' + ny.x.toFixed(2) + 'px) rotate(' + (rot.x + lean).toFixed(2) + 'deg) scale(1,' + sq.x.toFixed(3) + ')';
    yesBtn.style.transform = 'translate(' + yx.x.toFixed(2) + 'px,' + yy.x.toFixed(2) + 'px) scale(' + ys.x.toFixed(3) + ')';
  }
  function homeNo() {
    var r = rinkBox(), b = noBox();
    nx.snap(Math.max(0, r.w - b.w)); ny.snap(0); rot.snap(0); sq.snap(1); ys.snap(1); yx.snap(0); yy.snap(0); apply();
  }
  function clampTarget(x, y) {
    var r = rinkBox(), b = noBox(), yb = yesBox();
    x = Math.min(Math.max(0, x), r.w - b.w);
    y = Math.min(Math.max(0, y), r.h - b.h);
    /* Не заезжать на «Да»: выталкиваем по самой короткой оси, оставаясь на катке. */
    if (x < yb.x + yb.w && x + b.w > yb.x && y < yb.y + yb.h && y + b.h > yb.y) {
      var opts = [
        { x: yb.x + yb.w, y: y }, { x: yb.x - b.w, y: y },
        { x: x, y: yb.y + yb.h }, { x: x, y: yb.y - b.h }
      ].filter(function (o) { return o.x >= 0 && o.x <= r.w - b.w && o.y >= 0 && o.y <= r.h - b.h; });
      opts.sort(function (a, c) { return Math.hypot(a.x - x, a.y - y) - Math.hypot(c.x - x, c.y - y); });
      if (opts.length) { x = opts[0].x; y = opts[0].y; }
    }
    return { x: x, y: y };
  }
  function glideFrom(px, py, dist) {
    var b = noBox(), cx = nx.x + b.w / 2, cy = ny.x + b.h / 2;
    var dx = cx - px, dy = cy - py, len = Math.hypot(dx, dy) || 1;
    dx /= len; dy /= len;
    var t = clampTarget(nx.x + dx * dist, ny.x + dy * dist * 0.8);
    if (Math.hypot(t.x - nx.x, t.y - ny.x) < dist * 0.45) {
      var r = rinkBox();
      var far = [[r.w - b.w, r.h - b.h], [r.w - b.w, 0], [0, r.h - b.h], [0, 0], [(r.w - b.w) / 2, r.h - b.h]];
      far.sort(function (a, c) { return Math.hypot(c[0] + b.w / 2 - px, c[1] + b.h / 2 - py) - Math.hypot(a[0] + b.w / 2 - px, a[1] + b.h / 2 - py); });
      t = clampTarget(far[0][0], far[0][1]);
    }
    nx.to = t.x; ny.to = t.y;
    /* Отталкивание: стартовая скорость в сторону цели. Без неё пружина первые 150 мс
       почти стоит — и кнопка «зависает» под пальцем. Докат остаётся мягким. */
    var ex = t.x - nx.x, ey = t.y - ny.x, el = Math.hypot(ex, ey) || 1;
    var push = Math.min(900, 380 + el * 3);
    nx.v = nx.v * 0.3 + ex / el * push;
    ny.v = ny.v * 0.3 + ey / el * push;
    rot.v += (dx >= 0 ? 1 : -1) * (30 + state.tries * 25);   /* толчок: качнуло */
    kick();
  }

  function kick() {
    if (reduce) { nx.snap(nx.to); ny.snap(ny.to); rot.snap(rot.to); sq.snap(sq.to); ys.snap(ys.to); yx.snap(yx.to); yy.snap(yy.to); apply(); return; }
    if (!raf) { lastT = performance.now(); raf = requestAnimationFrame(tick); }
  }
  /* Борта катка: толчок может пронести кнопку дальше края — отскакивает, как шайба, теряя скорость. */
  function boards() {
    var r = rinkBox(), b = noBox(), mx = Math.max(0, r.w - b.w), my = Math.max(0, r.h - b.h);
    if (nx.x < 0) { nx.x = 0; if (nx.v < 0) nx.v = -nx.v * 0.35; }
    /* Справа кнопка может оказаться за бортом, когда подпись стала шире: не обрезаем рывком,
       пружина (keepInside) мягко вернёт. Летит наружу — отскок. */
    if (nx.x > mx && nx.v > 0) nx.v = -nx.v * 0.35;
    if (nx.x > mx + 120) nx.x = mx + 120;
    if (ny.x < 0) { ny.x = 0; if (ny.v < 0) ny.v = -ny.v * 0.35; }
    if (ny.x > my) { ny.x = my; if (ny.v > 0) ny.v = -ny.v * 0.35; }
  }

  function tick(t) {
    var dt = Math.min(0.032, (t - lastT) / 1000); lastT = t;
    for (var i = 0; i < 4; i++) { nx.step(dt / 4); ny.step(dt / 4); rot.step(dt / 4); sq.step(dt / 4); ys.step(dt / 4); yx.step(dt / 4); yy.step(dt / 4); boards(); }
    apply();
    var b = noBox(), speed = Math.hypot(nx.v, ny.v);
    if (ptr && !lying && !state.answered && !noBtn.classList.contains('is-yes') && nearNo(ptr.x, ptr.y)) attempt(ptr.x, ptr.y);
    if (speed > 30) points.push({ x: nx.x + b.w * 0.3, y: ny.x + b.h, x2: nx.x + b.w * 0.7, t: t, heavy: lying });
    drawTrail(t);
    if (nx.done() && ny.done() && rot.done() && sq.done() && ys.done() && yx.done() && yy.done() && !points.length) { raf = 0; return; }
    raf = requestAnimationFrame(tick);
  }
  function drawTrail(now) {
    var dpr = window.devicePixelRatio || 1, w = rink.clientWidth, h = rink.clientHeight;
    if (trail.width !== Math.round(w * dpr)) { trail.width = Math.round(w * dpr); trail.height = Math.round(h * dpr); }
    var ctx = trail.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    points = points.filter(function (p) { return now - p.t < 1100; });
    ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--trail').trim(); ctx.lineCap = 'round';
    for (var i = 1; i < points.length; i++) {
      var a = points[i - 1], p = points[i];
      if (p.t - a.t > 80) continue;
      ctx.globalAlpha = Math.max(0, 1 - (now - p.t) / 1100);
      if (p.heavy) {   /* упал — широкая борозда вместо двух лезвий */
        ctx.lineWidth = 7; ctx.beginPath(); ctx.moveTo((a.x + a.x2) / 2, a.y - 3); ctx.lineTo((p.x + p.x2) / 2, p.y - 3); ctx.stroke();
      } else {
        ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.moveTo(a.x, a.y - 2); ctx.lineTo(p.x, p.y - 2); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(a.x2, a.y - 2); ctx.lineTo(p.x2, p.y - 2); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  function say(text, hint) {
    var lbl = $('noLbl'), h = $('hint');
    if (hint != null) { h.style.opacity = '0'; later(function () { h.textContent = hint; h.style.opacity = '1'; }, 160); }
    if (reduce) { lbl.textContent = text; keepInside(); return; }
    lbl.style.opacity = '0';
    later(function () { lbl.textContent = text; lbl.style.opacity = '1'; keepInside(); }, 160);
  }

  /* Подпись стала длиннее — кнопка шире. Плавно отъезжаем от борта, а не торчим за ним. */
  function keepInside() {
    var r = rinkBox(), b = noBox();
    var mx = Math.max(0, r.w - b.w), my = Math.max(0, r.h - b.h);
    if (nx.to > mx) nx.to = mx;
    if (ny.to > my) ny.to = my;
    if (nx.x > mx || ny.x > my || nx.to !== nx.x) kick();
  }

  /* Акты. Номер акта = state.tries. */
  function nextAct(px, py) {
    if (!stats.first) stats.first = performance.now();
    state.tries++;
    var n = state.tries;
    track('no_attempt', { act: n });   /* одна строка на открытие: сервер поднимает в ней номер акта */
    if (n === 1) { say('Не-а', 'Кнопка катается лучше тебя.'); glideFrom(px, py, 150); }
    else if (n === 2) { swap(px, py); return; }
    else if (n === 3) { unmask(); fall(px); return; }
    else if (n === 4) {
      say('Ладно… может быть', 'Устала. Ещё раз — и сдастся.');
      nx.k = ny.k = 18; nx.c = ny.c = 7.5;          /* устала: едет медленно и недалеко */
      glideFrom(px, py, 70);
    } else { giveUp(); return; }
    nextActAt = performance.now() + DWELL;
  }

  function sayYesLabel(text) {
    var lbl = $('yesLbl');
    if (reduce) { lbl.textContent = text; return; }
    lbl.style.opacity = '0';
    later(function () { lbl.textContent = text; lbl.style.opacity = '1'; }, 160);
  }

  /* Акт 2: кнопки меняются местами. Под курсором оказывается «Да», переодетая в «Нет».
     Нажал её — засчитано как «да», с отдельным вердиктом. Настоящая «Нет» уезжает на место «Да». */
  function swap(px, py) {
    var r = rinkBox(), b = noBox();
    var yw = yesBtn.offsetWidth * ys.x, yh = yesBtn.offsetHeight * ys.x;
    var noX = nx.x, noY = ny.x, yesX = yx.x, yesY = yy.x;
    yx.to = Math.min(Math.max(0, noX + (b.w - yw) / 2), r.w - yw);
    yy.to = Math.min(Math.max(0, noY + (b.h - yh) / 2), r.h - yh);
    nx.to = Math.min(Math.max(0, yesX), r.w - b.w);
    ny.to = Math.min(Math.max(0, yesY), r.h - b.h);
    /* Разъехаться по дуге, а не сквозь друг друга: боковой толчок в разные стороны. */
    var dx = noX - yesX, dy = noY - yesY, d = Math.hypot(dx, dy) || 1;
    var pxn = -dy / d, pyn = dx / d;
    yx.v += pxn * 260; yy.v += pyn * 260 - 120;
    nx.v -= pxn * 260; ny.v -= pyn * 260 - 120;
    rot.v += 90;
    masked = true;
    swapUntil = performance.now() + 900;
    later(function () { yesBtn.classList.add('is-mask'); sayYesLabel('Нет'); }, 260);
    say('Настоящая «Нет»', 'Кнопки перепутались. Или нет?');
    kick();
    nextActAt = performance.now() + DWELL + 700;   /* дать заметить подмену */
  }

  /* Снять маскировку: «Да» снова тиловая. */
  function unmask() {
    if (!masked) return;
    masked = false;
    yesBtn.classList.remove('is-mask');
    sayYesLabel('Да');
  }

  /* Акт 3: потеряла равновесие, крутанулась, проехала на «спине», встала. */
  function fall(px) {
    lying = true;
    stats.falls++;
    noBtn.classList.add('is-down');
    var r = rinkBox(), b = noBox();
    var dir = nx.x + b.w / 2 > px ? 1 : -1;
    nx.to = Math.min(Math.max(0, nx.x + dir * 120), r.w - b.w);
    ny.to = r.h - b.h - 4;
    rot.to = dir * 360 + dir * 8;                   /* полный оборот и лёг на бок */
    rot.v += dir * 200;
    sq.to = 0.78;                                    /* придавило */
    say('Ай', null);
    $('hint').style.opacity = '0';
    later(function () { $('hint').textContent = 'Падать на льду не страшно, если есть за кого держаться.'; $('hint').style.opacity = '1'; }, 420);
    kick();
    later(function () {
      rot.x -= dir * 360; rot.to = 0; rot.v = -dir * 120;   /* встаёт, качаясь */
      sq.to = 1; sq.v = 3;
      lying = false; noBtn.classList.remove('is-down');
      say('Я в порядке', null);
      kick();
      nextActAt = performance.now() + DWELL;
    }, 1700);
    nextActAt = performance.now() + 1700 + DWELL;
  }

  /* Акт 5: подъезжает к «Да» и становится вторым «Да». */
  function giveUp() {
    noBtn.classList.add('is-yes');
    say('Да', 'Даже кнопка согласилась.');
    nx.k = ny.k = 26; nx.c = ny.c = 8.5;
    ys.to = 1;
    unmask();
    later(function () {
      /* Встать рядом с «Да»: справа, если влезает, иначе слева. */
      var r = rinkBox(), b = noBox(), yw = yesBtn.offsetWidth;
      var right = yx.to + yw + 8;
      nx.to = right + b.w <= r.w ? right : Math.max(0, yx.to - b.w - 8);
      ny.to = yy.to; rot.to = 0; rot.v += 40;
      kick();
    }, 200);
    kick();
  }

  /* Две независимые вещи. Уклон — всегда: пружина плавно меняет цель, кнопку не поймать.
     История — по таймеру: новая реплика не раньше nextActAt, поэтому её успевают прочитать,
     как бы быстро ни гнали курсор. */
  function attempt(px, py) {
    if (state.answered || lying || noBtn.classList.contains('is-yes')) return;
    var now = performance.now();
    if (now < swapUntil) return;   /* кнопки меняются местами — не сбивать маршрут */
    if (now - lastDodge < DODGE_GAP) return;
    lastDodge = now;
    if (now >= nextActAt) { nextAct(px, py); return; }
    glideFrom(px, py, 110);
  }

  /* Расстояние от точки до прямоугольника кнопки. */
  function nearNo(px, py) {
    var b = noBox();
    var cx = Math.min(Math.max(px, nx.x), nx.x + b.w), cy = Math.min(Math.max(py, ny.x), ny.x + b.h);
    return Math.hypot(px - cx, py - cy) < NEAR;
  }

  function localPoint(e) { var b = rink.getBoundingClientRect(); return { x: e.clientX - b.left, y: e.clientY - b.top }; }

  rink.addEventListener('pointermove', function (e) {
    if (e.pointerType !== 'mouse') return;
    ptr = localPoint(e);
    if (nearNo(ptr.x, ptr.y)) attempt(ptr.x, ptr.y);
  });
  rink.addEventListener('pointerleave', function () { ptr = null; });
  noBtn.addEventListener('pointerdown', function (e) {
    if (noBtn.classList.contains('is-yes')) return;
    e.preventDefault();
    lastPress = performance.now();
    var p = localPoint(e);
    lastDodge = -1e9;   /* палец уже на кнопке — уезжаем сразу */
    attempt(p.x, p.y);
  });
  noBtn.addEventListener('click', function (e) {
    e.preventDefault();
    /* Клик того же касания, что уже обработан в pointerdown, игнорируем: иначе рывок,
       а касание, превратившее «Нет» в «Да», сразу засчитало бы ответ. */
    if (performance.now() - lastPress < 700) return;
    if (noBtn.classList.contains('is-yes')) { sayYes(); return; }
    var b = noBox();
    attempt(nx.x + b.w / 2 + (Math.random() - .5) * 40, ny.x + b.h / 2 + (Math.random() - .5) * 40);
  });
  yesBtn.addEventListener('click', sayYes);

  /* ================= «Да» ================= */
  var answer = null, ticketBlob = null;

  function sayYes() {
    if (state.answered) return;
    state.answered = true;
    stats.tricked = masked;   /* нажали «Нет», а это была «Да» */
    try { if (navigator.vibrate) navigator.vibrate([12, 40, 18]); } catch (e) { /* */ }
    clearInterval(idleTimer);
    var ms = stats.first ? performance.now() - stats.first : 0;
    answer = { tries: state.tries, resist_ms: Math.round(ms), falls: stats.falls, tricked: !!stats.tricked };
    showYes(answer, true);
    track('yes', { tries: answer.tries, tricked: answer.tricked });
    postAnswer(answer, 1);
  }

  /* Экран «да»: билет со статистикой. animate=false — повторное открытие (S8), без штампа и крошки. */
  function showYes(a, animate) {
    state.answered = true;
    clearInterval(idleTimer);
    answer = a;
    var sec = M.resistSeconds(a.resist_ms);
    $('stSec').textContent = sec + ' с';
    $('stTries').textContent = String(a.tries);
    $('stFalls').textContent = String(a.falls);
    $('verdict').textContent = M.verdict(a.tries, a.falls, a.tricked);
    $('askBody').hidden = true;
    var yb = $('yesBody');
    yb.hidden = false;
    var st = $('stamp');
    if (animate) {
      yb.classList.remove('reveal'); void yb.offsetWidth; yb.classList.add('reveal');
      st.classList.remove('hit'); void st.offsetWidth; st.classList.add('hit');
      later(function () { burst($('cardView')); }, 420);   /* крошка — в момент удара штампа */
    } else {
      yb.classList.remove('reveal'); st.classList.remove('hit');
    }
    prefetchTicket();
  }

  function ticketUrl() {
    var a = answer || { tries: 0, resist_ms: 0, falls: 0, tricked: false };
    return PAGE + '/ticket.png' + M.ticketQuery(a.tries, M.resistSeconds(a.resist_ms), a.falls, a.tricked);
  }

  /* Картинка билета грузится заранее: Web Share с файлом должен стартовать прямо из касания,
     иначе Safari теряет «жест пользователя» за время запроса. */
  function prefetchTicket() {
    ticketBlob = null;
    if (!window.fetch || !window.File || !navigator.canShare) return;
    fetch(ticketUrl(), { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.blob() : null; })
      .then(function (b) { ticketBlob = b; }, function () { ticketBlob = null; });
  }

  function postAnswer(a, retries) {
    var body = M.answerBody(deviceToken, a.tries, a.resist_ms, a.falls, a.tricked);
    fetch(API + '/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Zovi-Device': deviceToken },
      body: JSON.stringify(body),
      credentials: 'same-origin'
    }).then(function (r) {
      if (r.status === 409) { DATA.state = 'gone'; showClosed(); }
    }, function () {
      /* Сеть упала: экран «да» уже показан, тихо повторяем один раз. */
      if (retries > 0) setTimeout(function () { postAnswer(a, retries - 1); }, 1500);
    });
  }

  /* Вердикт без рода: открытку шлют кому угодно. Тексты — в zovi-model.js (M.verdict). */

  /* Ледяная крошка из-под конька: мягкий веер вверх, медленное оседание. */
  function burst(host) {
    if (reduce) return;
    var c = document.createElement('canvas'); c.className = 'burst'; host.appendChild(c);
    var w = host.clientWidth, h = host.clientHeight, dpr = window.devicePixelRatio || 1;
    c.width = w * dpr; c.height = h * dpr;
    var ctx = c.getContext('2d'); ctx.scale(dpr, dpr);
    var css = getComputedStyle(document.documentElement);
    var cols = [css.getPropertyValue('--accent').trim(), css.getPropertyValue('--ice').trim(), css.getPropertyValue('--line-strong').trim()];
    var bits = [];
    for (var i = 0; i < 70; i++) {
      var ang = -Math.PI / 2 + (Math.random() - .5) * 1.9, sp = 260 + Math.random() * 360;
      bits.push({ x: w * .5, y: h * .42, vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp, r: 1.5 + Math.random() * 3.2, a: Math.random() * 6, va: (Math.random() - .5) * 6, col: cols[i % 3], flake: Math.random() < .4 });
    }
    var t0 = performance.now(), last = t0;
    (function f(t) {
      var dt = Math.min(0.033, (t - last) / 1000); last = t;
      var age = (t - t0) / 1000;
      ctx.clearRect(0, 0, w, h);
      bits.forEach(function (b) {
        b.vy += 520 * dt; b.vx *= Math.pow(0.18, dt); b.vy *= Math.pow(0.55, dt);
        b.x += b.vx * dt; b.y += b.vy * dt; b.a += b.va * dt;
        ctx.save(); ctx.globalAlpha = Math.max(0, 1 - Math.max(0, age - 1.1) / 0.9);
        ctx.translate(b.x, b.y); ctx.rotate(b.a); ctx.strokeStyle = ctx.fillStyle = b.col; ctx.lineWidth = 1.3;
        if (b.flake) { for (var k = 0; k < 3; k++) { ctx.rotate(Math.PI / 3); ctx.beginPath(); ctx.moveTo(-b.r * 1.7, 0); ctx.lineTo(b.r * 1.7, 0); ctx.stroke(); } }
        else { ctx.beginPath(); ctx.moveTo(0, -b.r); ctx.lineTo(b.r * .8, 0); ctx.lineTo(0, b.r); ctx.lineTo(-b.r * .8, 0); ctx.closePath(); ctx.fill(); }
        ctx.restore();
      });
      if (age < 2) requestAnimationFrame(f); else c.remove();
    })(t0);
  }

  /* ================= Отправить ответ ================= */
  var toastTimer = 0;
  function toast(msg) {
    var t = $('toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 2200);
  }

  /* Без «Поделиться»: на телефоне — картинка в новой вкладке, на компьютере — сразу файл. */
  function openTicket(url) {
    var touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
    if (!touch) {
      var a = document.createElement('a');
      a.href = url; a.download = 'glide-bilet.png';
      document.body.appendChild(a); a.click(); a.remove();
      toast('Билет сохранён — отправь его, куда хочешь');
      return;
    }
    toast('Удержите картинку, чтобы сохранить');
    window.open(url, '_blank', 'noopener');
  }

  $('sendBtn').addEventListener('click', function () {
    track('send_answer', {});
    var url = new URL(ticketUrl(), window.location.href).href;
    var title = 'Мой ответ — ДА 🎟';
    var file = null;
    if (ticketBlob && window.File) {
      try { file = new File([ticketBlob], 'glide-bilet.png', { type: 'image/png' }); } catch (e) { file = null; }
    }
    var done = function () { /* поделились */ };
    var failed = function (err) { if (!err || err.name !== 'AbortError') openTicket(url); };
    try {
      if (file && navigator.canShare && navigator.canShare({ files: [file] })) {
        navigator.share({ files: [file], title: title }).then(done, failed);
        return;
      }
      if (navigator.share) {
        navigator.share({ title: title, text: title, url: url }).then(done, failed);
        return;
      }
    } catch (e) { /* in-app браузер без Web Share */ }
    openTicket(url);
  });

  /* ================= Сеанс убрали или прошёл ================= */
  function showClosed() {
    clearLater();
    clearInterval(idleTimer);
    state.answered = true;
    $('yesBody').hidden = true;
    $('askBody').hidden = false;
    $('rink').hidden = true;
    $('hint').hidden = true;
    var box = $('closed'), next = $('closedNext');
    $('closedTitle').textContent = DATA.state === 'past' ? 'Этот сеанс уже прошёл' : 'Этот сеанс убрали из расписания';
    next.textContent = '';
    var a = arena(), ns = DATA.next_session, link = document.createElement('a');
    if (ns && a.public_path) {
      next.appendChild(document.createTextNode('Ближайший здесь: '));
      link.href = a.public_path + '?s=' + encodeURIComponent(ns.id);
      link.textContent = M.dayLabel(ns.local_date, 'short') + ', ' + ns.starts_at_local;
    } else if (a.public_path) {
      link.href = a.public_path;
      link.textContent = 'Расписание катка';
    } else {
      link.href = '/';
      link.textContent = 'Где покататься — в каталоге Glide';
    }
    next.appendChild(link);
    box.hidden = false;
  }

  /* ================= Старт ================= */
  function reset() {
    clearLater();
    state.tries = 0; state.answered = false; points = []; nextActAt = 0; lying = false;
    stats.first = 0; stats.falls = 0; stats.tricked = false; ptr = null; lastDodge = -1e9;
    masked = false; swapUntil = 0; yesBtn.classList.remove('is-mask'); $('yesLbl').textContent = 'Да'; $('yesLbl').style.opacity = '1';
    nx.k = ny.k = 34; nx.c = ny.c = 9.6;
    $('askBody').hidden = false; $('yesBody').hidden = true;
    noBtn.classList.remove('is-yes', 'is-down'); $('noLbl').textContent = 'Нет'; $('noLbl').style.opacity = '1';
    $('hint').textContent = ''; $('hint').style.opacity = '1';
    paint();
    requestAnimationFrame(function () { homeNo(); drawTrail(performance.now()); });
  }
  window.addEventListener('resize', function () { if (!state.answered && state.tries === 0) homeNo(); });

  /* Ответ сервера после загрузки: он и ставит «открыто» (SSR не ставит — превью-боты без JS). */
  function applyServer(fresh) {
    if (!fresh || typeof fresh !== 'object') return;
    var mine = fresh.my_answer;
    DATA.state = fresh.state || DATA.state;
    DATA.next_session = fresh.next_session || null;
    if (fresh.session) DATA.session = fresh.session;
    paint();
    if (DATA.state !== 'ok') { showClosed(); return; }
    if (mine && !answer) showYes(mine, false);
  }

  reset();
  if (DATA.state && DATA.state !== 'ok') showClosed();
  else idleWobble();
  track('open', { state: DATA.state });
  if (CODE && window.fetch) {
    fetch(API + M.srcQuery(window.location.search), { headers: { 'X-Zovi-Device': deviceToken }, credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(applyServer, function () { /* офлайн: открытка уже нарисована из SSR */ });
  }
})();
