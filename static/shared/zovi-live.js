/**
 * Живая открытка «Пойдёшь со мной на каток?» — превью там, где её собирают:
 * шит «Поделиться» в каталоге и страница /zovi.
 *
 * Не картинка, а сама открытка в миниатюре: имена меняются по мере ввода, «Нет» убегает
 * от пальца и от курсора, а пока никто не трогает — палец-подсказка сам пытается его
 * нажать. Человек видит, что получит друг, до того как отправит.
 *
 * Цвета — переменные --zl-*: шит берёт их из темы мини-аппа, /zovi — из glide-tokens.
 * Стили компонент кладёт в <head> сам, один раз: у /static/shared нет раздачи CSS.
 *
 * Browser: window.ZoviLive. Node tests: module.exports (чистые функции).
 */
(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ZoviLive = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  var HOCKEY = 'hockey_practice';
  var NO_LABELS = ['Нет', 'Не-а', 'Мимо', 'Не догонишь', 'Ай!', 'Нет'];
  var STYLE_ID = 'zovi-live-style';
  var IDLE_MS = 2600;
  var DODGE_RADIUS = 64;

  var CSS = [
    '.zl{--zl-cut:16px;display:grid;gap:8px;margin:0 0 12px}',
    '.zl-card{position:relative;display:grid;gap:12px;padding:16px 16px 14px 19px;',
    'background:var(--zl-surface,#fff);color:var(--zl-ink,#0d1b26);border:1px solid var(--zl-line,#e2e6e5);',
    'clip-path:polygon(0 0,calc(100% - var(--zl-cut)) 0,100% var(--zl-cut),100% 100%,0 100%)}',
    '.zl-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--zl-ice,#2aa7c9)}',
    '.zl-kicker{margin:0;font-size:12px;font-weight:500;color:var(--zl-muted,#5b6b78)}',
    '.zl-kicker b{color:var(--zl-ink,#0d1b26);font-weight:600}',
    '.zl-q{margin:0;font-size:24px;font-weight:650;line-height:1.1;letter-spacing:-.02em;text-wrap:balance}',
    '.zl-name{color:var(--zl-accent-ink,#127f81)}',
    '.zl-plan{display:grid;grid-template-columns:auto 1fr;column-gap:12px;align-items:center;',
    'padding-top:10px;border-top:1px solid var(--zl-line,#e2e6e5)}',
    '.zl-time{grid-row:span 2;font-size:30px;font-weight:650;letter-spacing:-.03em;line-height:1;font-variant-numeric:tabular-nums}',
    '.zl-day{font-size:12px;font-weight:600;color:var(--zl-accent-ink,#127f81)}',
    '.zl-place{min-width:0;font-size:14px;font-weight:600;line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.zl-rink{position:relative;height:92px;margin:0 -4px;touch-action:manipulation}',
    '.zl-ans{position:absolute;left:0;top:0;display:inline-flex;align-items:center;justify-content:center;',
    'min-height:42px;padding:0 22px;border-radius:12px;font:inherit;font-size:15px;font-weight:600;white-space:nowrap;',
    'user-select:none;-webkit-user-select:none;-webkit-tap-highlight-color:transparent;cursor:pointer}',
    '.zl-yes{z-index:2;border:1px solid transparent;background:var(--zl-accent,#45b9bb);color:var(--zl-on-accent,#04262a)}',
    '.zl-no{z-index:1;background:var(--zl-surface,#fff);color:var(--zl-ink,#0d1b26);border:1px solid var(--zl-line-strong,#cfd6d5);',
    'transition:transform .5s cubic-bezier(.2,.9,.25,1.15)}',
    '.zl-finger{position:absolute;left:0;top:0;z-index:3;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;',
    'border:2px solid var(--zl-accent,#45b9bb);background:rgba(127,215,216,.28);opacity:0;pointer-events:none;',
    'transition:transform .7s cubic-bezier(.4,0,.2,1),opacity .2s}',
    '.zl-finger.is-on{opacity:1}',
    '.zl-yes.is-poke{animation:zl-poke .4s ease}',
    '@keyframes zl-poke{40%{transform:var(--zl-yes-at) scale(1.08)}}',
    '.zl-cap{margin:0;font-size:13px;line-height:1.35;color:var(--zl-muted,#5b6b78)}',
    '@media (prefers-reduced-motion:reduce){.zl-no,.zl-finger{transition:none}.zl-yes.is-poke{animation:none}}'
  ].join('');

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* Склонение — из модели открытки, чтобы превью и сама открытка говорили одинаково. */
  function decline(name, kind) {
    var ZM = root && root.ZoviModel;
    if (ZM && typeof ZM.decline === 'function') return ZM.decline(name, kind);
    return String(name || '').trim();
  }

  /**
   * Тексты превью. input: { toName, fromName, kind, time, day, place }.
   * Имя адресата пустое — открытка для компании, как на самой странице.
   */
  function model(input) {
    var data = input || {};
    var to = String(data.toName || '').trim();
    var from = String(data.fromName || '').trim();
    var where = data.kind === HOCKEY ? 'на хоккей' : 'на каток';
    return {
      kicker: from ? 'Приглашение на лёд от' : 'Приглашение на лёд',
      from: from ? decline(from, 'gen') : '',
      name: to,
      ask: to ? ', пойдёшь со мной ' + where + '?' : 'Пойдёшь со мной ' + where + '?',
      time: String(data.time || ''),
      day: String(data.day || ''),
      place: String(data.place || ''),
      caption: (to ? 'Так увидит ' + to : 'Так увидят в чате') + '. Попробуй нажать «Нет».'
    };
  }

  function html(input) {
    var m = model(input);
    return (
      '<div class="zl" data-zl>' +
      '<div class="zl-card">' +
      '<p class="zl-kicker"><span data-zl-kicker>' + esc(m.kicker) + '</span> <b data-zl-from>' + esc(m.from) + '</b></p>' +
      '<p class="zl-q"><span class="zl-name" data-zl-name>' + esc(m.name) + '</span><span data-zl-ask>' + esc(m.ask) + '</span></p>' +
      '<div class="zl-plan"><span class="zl-time">' + esc(m.time) + '</span>' +
      '<span class="zl-day">' + esc(m.day) + '</span><span class="zl-place">' + esc(m.place) + '</span></div>' +
      '<div class="zl-rink" data-zl-rink>' +
      '<span class="zl-ans zl-yes" data-zl-yes>Да</span>' +
      '<span class="zl-ans zl-no" data-zl-no>Нет</span>' +
      '<span class="zl-finger" data-zl-finger aria-hidden="true"></span>' +
      '</div></div>' +
      '<p class="zl-cap" data-zl-cap>' + esc(m.caption) + '</p>' +
      '</div>'
    );
  }

  /** Имена меняются по ходу ввода — без перерисовки, чтобы не сбить «Нет» и фокус в полях. */
  function update(el, input) {
    if (!el) return;
    var m = model(input);
    var set = function (sel, text) {
      var node = el.querySelector(sel);
      if (node) node.textContent = text;
    };
    set('[data-zl-kicker]', m.kicker);
    set('[data-zl-from]', m.from);
    set('[data-zl-name]', m.name);
    set('[data-zl-ask]', m.ask);
    set('[data-zl-cap]', m.caption);
  }

  /**
   * Куда отскочить «Нет»: подальше от пальца, не на «Да», внутри катка.
   * Чистая функция: rnd — источник случайности для тестов.
   */
  function pickSpot(rink, btn, yes, avoid, rnd) {
    var random = rnd || Math.random;
    var maxX = Math.max(0, rink.w - btn.w);
    var maxY = Math.max(0, rink.h - btn.h);
    var best = { x: maxX, y: maxY / 2 };
    var bestScore = -1;
    var i;
    for (i = 0; i < 14; i += 1) {
      var x = random() * maxX;
      var y = random() * maxY;
      var overlapsYes =
        yes && x < yes.x + yes.w + 8 && x + btn.w > yes.x - 8 && y < yes.y + yes.h + 6 && y + btn.h > yes.y - 6;
      if (overlapsYes) continue;
      var cx = x + btn.w / 2;
      var cy = y + btn.h / 2;
      var score = avoid ? Math.hypot(cx - avoid.x, cy - avoid.y) : random();
      if (score > bestScore) {
        bestScore = score;
        best = { x: x, y: y };
      }
    }
    return best;
  }

  function nextLabel(step) {
    return NO_LABELS[Math.min(step, NO_LABELS.length - 1)];
  }

  function ensureStyle(doc) {
    if (!doc || doc.getElementById(STYLE_ID)) return;
    var style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    (doc.head || doc.documentElement).appendChild(style);
  }

  function reducedMotion() {
    try {
      return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) {
      return false;
    }
  }

  /**
   * Оживить открытку внутри el. opts.onDodge — тактильный отклик хоста.
   * Возвращает { destroy }. Сам останавливается, когда открытку убрали из DOM.
   */
  function attach(el, opts) {
    var options = opts || {};
    var rinkEl = el && el.querySelector('[data-zl-rink]');
    if (!rinkEl) return { destroy: function () {} };
    var doc = el.ownerDocument;
    ensureStyle(doc);
    var yesEl = rinkEl.querySelector('[data-zl-yes]');
    var noEl = rinkEl.querySelector('[data-zl-no]');
    var finger = rinkEl.querySelector('[data-zl-finger]');
    var still = reducedMotion();
    var pos = { x: 0, y: 0 };
    var step = 0;
    var lastTouch = 0;
    var timers = [];
    var loop = null;
    var dead = false;

    function sizes() {
      return {
        rink: { w: rinkEl.clientWidth, h: rinkEl.clientHeight },
        btn: { w: noEl.offsetWidth, h: noEl.offsetHeight },
        yes: { x: yesEl.offsetLeft, y: yesEl.offsetTop, w: yesEl.offsetWidth, h: yesEl.offsetHeight }
      };
    }

    function place(x, y) {
      pos = { x: x, y: y };
      noEl.style.transform = 'translate(' + Math.round(x) + 'px,' + Math.round(y) + 'px)';
    }

    function layout() {
      var s = sizes();
      var yesX = Math.round(s.rink.w * 0.12);
      var yesY = Math.round((s.rink.h - s.yes.h) / 2);
      yesEl.style.left = yesX + 'px';
      yesEl.style.top = yesY + 'px';
      yesEl.style.setProperty('--zl-yes-at', 'translate(0,0)');
      place(Math.max(yesX + s.yes.w + 18, s.rink.w * 0.55), (s.rink.h - s.btn.h) / 2);
    }

    function dodge(from, byHand) {
      var s = sizes();
      s.yes = { x: yesEl.offsetLeft, y: yesEl.offsetTop, w: s.yes.w, h: s.yes.h };
      var spot = pickSpot(s.rink, s.btn, s.yes, from);
      step += 1;
      noEl.textContent = nextLabel(byHand ? step : 0);
      place(spot.x, spot.y);
      if (byHand && typeof options.onDodge === 'function') options.onDodge();
    }

    function local(ev) {
      var r = rinkEl.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    }

    function near(p) {
      var s = sizes();
      var cx = pos.x + s.btn.w / 2;
      var cy = pos.y + s.btn.h / 2;
      return Math.hypot(p.x - cx, p.y - cy) < DODGE_RADIUS;
    }

    function onMove(ev) {
      if (ev.pointerType === 'touch') return;
      var p = local(ev);
      if (near(p)) {
        lastTouch = Date.now();
        dodge(p, true);
      }
    }

    function onDown(ev) {
      var p = local(ev);
      lastTouch = Date.now();
      if (ev.target === noEl || near(p)) {
        ev.preventDefault();
        dodge(p, true);
        return;
      }
      if (ev.target === yesEl) {
        yesEl.classList.remove('is-poke');
        void yesEl.offsetWidth;
        yesEl.classList.add('is-poke');
      }
    }

    /* Палец-подсказка: подходит к «Нет», тот отъезжает. Только пока никто не трогает. */
    function demo() {
      if (dead) return;
      if (!el.isConnected) {
        destroy();
        return;
      }
      if (doc.hidden || Date.now() - lastTouch < IDLE_MS * 2) return;
      var s = sizes();
      var startX = s.rink.w * (pos.x > s.rink.w / 2 ? 0.2 : 0.85);
      var target = { x: pos.x + s.btn.w / 2, y: pos.y + s.btn.h / 2 };
      finger.style.transition = 'none';
      finger.style.transform = 'translate(' + startX + 'px,' + (s.rink.h - 6) + 'px)';
      void finger.offsetWidth;
      finger.style.transition = '';
      finger.classList.add('is-on');
      finger.style.transform = 'translate(' + target.x + 'px,' + target.y + 'px)';
      timers.push(root.setTimeout(function () {
        if (dead) return;
        dodge(target, false);
      }, 520));
      timers.push(root.setTimeout(function () {
        if (dead) return;
        finger.classList.remove('is-on');
      }, 900));
    }

    function destroy() {
      dead = true;
      if (loop) root.clearInterval(loop);
      timers.forEach(function (t) { root.clearTimeout(t); });
      rinkEl.removeEventListener('pointermove', onMove);
      rinkEl.removeEventListener('pointerdown', onDown);
    }

    layout();
    rinkEl.addEventListener('pointermove', onMove);
    rinkEl.addEventListener('pointerdown', onDown);
    if (!still) loop = root.setInterval(demo, IDLE_MS);
    return { destroy: destroy, relayout: layout };
  }

  return {
    model: model,
    html: html,
    update: update,
    attach: attach,
    pickSpot: pickSpot,
    nextLabel: nextLabel,
    ensureStyle: ensureStyle
  };
});
