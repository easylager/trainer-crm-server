/* TASK-451 (5.4) → PDEC-040 батч C: полка значков + коллекция — общий код
   старого «Я» (client-me через checkin-live) и «Я» v2 (me-v2). Разметка и
   классы mv2-* общие: стили — badge-collection.css, арт — badge-art.js,
   лист вручения — GlideBadgeAward (badge-award.js).

   window.GlideBadgeShelf = {
     shelfHtml(list)        — секция «Значки» ('' если показывать нечего);
     wireShelf(scope, list) — «Все значки» + тапы по плиткам внутри scope;
     openCollection(list)   — оверлей «Мои значки» (макет 18);
     closeCollection(),
     nextStreakBadge(list), badgeNext(badge, list).
   } */
(function () {
  'use strict';
  var root = typeof window !== 'undefined' ? window : globalThis;
  var doc = root.document;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function art(key, earned) {
    var a = root.GlideBadgeArt || {};
    return a[key + (earned ? '_earned' : '_locked')] || '';
  }
  function fmtEarnedDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    var dd = ('0' + d.getDate()).slice(-2), mm = ('0' + (d.getMonth() + 1)).slice(-2);
    return dd + '.' + mm;
  }
  /* Первый не открытый значок серии — «до «Крепкого льда» 2 недели». */
  function nextStreakBadge(list) {
    var nb = null;
    (list || []).forEach(function (b) {
      if (!nb && b.family === 'streak' && !b.earned) nb = b;
    });
    return nb;
  }
  function btileHtml(b) {
    var cap = b.earned
      ? fmtEarnedDate(b.earned_at)
      : (b.progress ? b.progress.done + ' из ' + b.progress.total : '');
    return '<button type="button" class="mv2-btile' + (b.earned ? ' is-earned' : ' is-locked') + '" data-badge="' + esc(b.key) + '">' +
      '<span class="mv2-btile__art">' + art(b.key, b.earned) + '</span>' +
      '<span class="mv2-btile__n">' + esc(b.name) + '</span>' +
      (cap ? '<span class="mv2-btile__s">' + esc(cap) + '</span>' : '') +
      '</button>';
  }
  /* Секция «Значки»: «Первый шаг» строкой сверху, плитки — полученные → ближайшие. */
  function shelfHtml(list) {
    list = Array.isArray(list) ? list : [];
    if (!list.length || !list.some(function (b) { return b.earned; })) return '';
    var intro = null;
    var tiles = list.filter(function (b) {
      if (b.key === 'first_ice') { intro = b; return false; }
      return true;
    }).sort(function (a, c) {
      if (!!a.earned !== !!c.earned) return a.earned ? -1 : 1;
      if (a.earned) return String(a.earned_at).localeCompare(String(c.earned_at));
      var ra = a.progress ? a.progress.done / a.progress.total : 0;
      var rc = c.progress ? c.progress.done / c.progress.total : 0;
      return rc - ra;
    });
    var firstStep = '';
    if (intro) {
      firstStep = '<div class="mv2-bfirst">' +
        '<span class="mv2-bfirst__art">' + art('first_ice', intro.earned) + '</span>' +
        '<div class="mv2-bfirst__tx"><div class="mv2-bfirst__t">Первый шаг</div>' +
        '<div class="mv2-bfirst__s">' + (intro.earned ? '«Вышел на лёд» — твой' : 'Отметься «Я здесь» — будет значок') + '</div></div>' +
        '</div>';
    }
    return '<section class="mv2-sec mv2-badges">' +
      '<div class="mv2-badges__hrow"><h2 class="mv2-sec__h">Значки</h2>' +
      '<button type="button" class="mv2-badges__all" id="mv2BadgesAll">Все значки</button></div>' +
      firstStep +
      '<div class="mv2-badges__row">' + tiles.map(btileHtml).join('') + '</div>' +
      '</section>';
  }

  /* Коллекция (макет 18): «Ближе всего» → «Первый шаг» → Серии → Сезон. */
  function collectionHtml(list) {
    list = Array.isArray(list) ? list : [];
    var intro = null, streak = [], seasonB = [], closest = null, bestR = -1;
    list.forEach(function (b) {
      if (b.key === 'first_ice') { intro = b; return; }
      if (!b.earned && b.progress) {
        var r = b.progress.done / b.progress.total;
        if (r > bestR) { bestR = r; closest = b; }
      }
      if (b.family === 'streak') streak.push(b);
      else if (b.family === 'season') seasonB.push(b);
    });
    var closestHtml = closest
      ? '<div class="mv2-col__lbl">Ближе всего</div><div class="mv2-col__closest">' + btileHtml(closest) + '</div>'
      : '';
    var firstHtml = intro
      ? '<div class="mv2-col__lbl">Первый шаг</div><div class="mv2-col__first">' +
        '<span class="mv2-bfirst__art">' + art('first_ice', intro.earned) + '</span>' +
        '<div><div class="mv2-bfirst__t">' + esc(intro.name) + '</div>' +
        '<div class="mv2-bfirst__s">' + (intro.earned ? 'Открыт — первая отметка сезона' : 'Отметься «Я здесь» — откроется') + '</div></div></div>'
      : '';
    return '<div class="mv2-col__head"><button type="button" class="mv2-col__back" id="mv2ColBack">‹</button>' +
      '<div class="mv2-col__t">Мои значки</div></div>' +
      closestHtml + firstHtml +
      '<div class="mv2-col__lbl">Серии</div><div class="mv2-col__grid">' + streak.map(btileHtml).join('') + '</div>' +
      '<div class="mv2-col__lbl">Сезон</div><div class="mv2-col__grid">' + seasonB.map(btileHtml).join('') + '</div>';
  }
  function openCollection(list) {
    if (!doc) return;
    var el = doc.getElementById('mv2Collection');
    if (!el) {
      el = doc.createElement('div');
      el.id = 'mv2Collection';
      el.className = 'mv2-col';
      el.hidden = true;
      doc.body.appendChild(el);
    }
    el.innerHTML = collectionHtml(list);
    el.hidden = false;
    doc.body.classList.add('mv2-col-open');
    wireTiles(el, list);
    var back = el.querySelector('#mv2ColBack');
    if (back) back.addEventListener('click', closeCollection);
  }
  function closeCollection() {
    if (!doc) return;
    var el = doc.getElementById('mv2Collection');
    if (el) el.hidden = true;
    doc.body.classList.remove('mv2-col-open');
  }
  /* «Дальше» для повторного листа: следующий уровень семьи или ближайший закрытый. */
  function badgeNext(b, list) {
    var nxt = null;
    (list || []).forEach(function (x) {
      if (!nxt && x.family === b.family && x.total > b.total && !x.earned) nxt = x;
    });
    if (!nxt) {
      var bestR = -1;
      (list || []).forEach(function (x) {
        if (x.earned || !x.progress || x.progress.done >= x.total) return;
        var r = x.progress.done / x.total;
        if (r > bestR) { bestR = r; nxt = x; }
      });
    }
    if (!nxt) return null;
    return { name: nxt.name, family: nxt.family, remaining: nxt.progress.total - nxt.progress.done };
  }
  /* Тап по открытому значку — лист вручения ещё раз (можно поделиться). */
  function wireTiles(scope, list) {
    if (!scope) return;
    scope.querySelectorAll('[data-badge]').forEach(function (t) {
      t.addEventListener('click', function () {
        var key = t.getAttribute('data-badge');
        var b = null;
        (list || []).forEach(function (x) { if (x.key === key) b = x; });
        if (b && b.earned && root.GlideBadgeAward) {
          var shown = {};
          for (var k in b) shown[k] = b[k];
          shown.next = badgeNext(b, list);
          root.GlideBadgeAward.open({ badges: [shown], onClose: function () {} });
        }
      });
    });
  }
  /* «Все значки» → коллекция + тапы по плиткам полки. */
  function wireShelf(scope, list) {
    if (!scope) return;
    var all = scope.querySelector('#mv2BadgesAll');
    if (all) all.addEventListener('click', function () { openCollection(list); });
    wireTiles(scope, list);
  }

  root.GlideBadgeShelf = {
    shelfHtml: shelfHtml,
    wireShelf: wireShelf,
    openCollection: openCollection,
    closeCollection: closeCollection,
    nextStreakBadge: nextStreakBadge,
    badgeNext: badgeNext,
    btileHtml: btileHtml,
  };
})();
