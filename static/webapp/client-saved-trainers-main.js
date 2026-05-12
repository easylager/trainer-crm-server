/**
 * Client mini-app: "Мои тренеры" — relationship hub.
 *
 * Three layers, in priority order:
 *   1. Primary trainer  — pinned hero card (current trust)
 *   2. Saved trainers   — grid of bookmarked candidates (active intent)
 *   3. Past trainers    — horizontal strip of past completions (reactivation layer)
 *
 * Filter pills are built from services of SAVED trainers only (the layer where
 * the client is comparing options). Filter applies to all 3 sections so the
 * screen feels like one contextual switch.
 *
 * Card metadata is intent-driven, not historical:
 *   - primary  → "Следующая запись X числа" / "Запись доступна"
 *   - saved    → "Цена от X ⃅", арена, услуги — почему вернуться сейчас
 *   - past     → "N занятий вместе" / "последняя X числа"
 */
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    if (typeof tg.ready === 'function') tg.ready();
    if (typeof tg.expand === 'function') tg.expand();
    if (typeof window.__applyClientMiniAppTheme === 'function') window.__applyClientMiniAppTheme();
  }

  /* ── helpers ─────────────────────────────────────────────────── */

  function getInitData() { return tg && tg.initData ? tg.initData : ''; }

  function headersJson() {
    var h = { 'Content-Type': 'application/json' };
    var id = getInitData();
    if (id) h['X-Telegram-Init-Data'] = id;
    return h;
  }

  function apiUrl(path) {
    var url = '/api/webapp' + path;
    var id = getInitData();
    if (id) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(id);
    return url;
  }

  function withInit(url) {
    var id = getInitData();
    if (!id) return url;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(id);
  }

  function webappBase() {
    var p = window.location.pathname || '';
    return p.replace(/[^/]+$/, '') || '/webapp/';
  }

  function goTo(path) { window.location.href = withInit(webappBase() + path); }

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function thumbUrl(key) { return key ? '/api/public/photos/' + encodeURIComponent(key) : ''; }

  function pluralRu(n, one, few, many) {
    var n10 = n % 10, n100 = n % 100;
    if (n10 === 1 && n100 !== 11) return one;
    if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return few;
    return many;
  }

  function sessionsLabel(count) {
    if (!count || count < 1) return null;
    return count + ' ' + pluralRu(count, 'занятие', 'занятия', 'занятий');
  }

  function priceByn(cents) {
    if (cents == null) return null;
    var byn = Math.round(cents / 100);
    return 'от ' + byn + ' ⃅';
  }

  /** "12 мая" / "сегодня" / "завтра" — concise upcoming/past date label. */
  function shortDateLabel(iso, opts) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    opts = opts || {};
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var dayKey = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var diffDays = Math.round((dayKey - today) / 86400000);
    if (opts.allowToday && diffDays === 0) return 'сегодня';
    if (diffDays === 1) return 'завтра';
    if (opts.relativePast && diffDays === -1) return 'вчера';
    var months = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
    return d.getDate() + ' ' + months[d.getMonth()];
  }

  /* ── state ───────────────────────────────────────────────────── */

  var state = {
    primary: null,
    saved: [],
    past: [],
    filter: 'all',
  };

  /* ── nav wiring ──────────────────────────────────────────────── */

  document.getElementById('btnHome').onclick = function () { goTo('client-home'); };
  var btnBack = document.getElementById('btnBack');
  if (btnBack && window.history.length > 1) {
    btnBack.hidden = false;
    btnBack.onclick = function () { window.history.back(); };
  }
  var btnCatalog = document.getElementById('btnCatalog');
  if (btnCatalog) btnCatalog.onclick = function () { goTo('catalog?tab=catalog'); };

  /* ── toast ───────────────────────────────────────────────────── */

  var toastTimer = null;
  function toast(msg) {
    var el = document.getElementById('toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove('show'); }, 2200);
  }

  /* ── confirm popover (unsave) ───────────────────────────────── */

  var confirmEl = document.getElementById('confirmBackdrop');
  var confirmYes = document.getElementById('confirmYes');
  var confirmCancel = document.getElementById('confirmCancel');
  var pendingUnsave = null;

  function openConfirm(edge) {
    pendingUnsave = edge;
    document.getElementById('confirmTitle').textContent =
      'Убрать ' + (edge.trainer_display_name || 'тренера') + '?';
    confirmEl.classList.add('open');
  }
  function closeConfirm() {
    pendingUnsave = null;
    confirmEl.classList.remove('open');
  }
  confirmCancel.onclick = closeConfirm;
  confirmEl.onclick = function (e) { if (e.target === confirmEl) closeConfirm(); };
  confirmYes.onclick = function () {
    if (!pendingUnsave) return;
    var edge = pendingUnsave;
    closeConfirm();
    fetch(apiUrl('/client/trainer-edges/save/' + edge.trainer_id), {
      method: 'DELETE',
      headers: headersJson(),
    })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function () {
        state.saved = state.saved.filter(function (e) { return e.trainer_id !== edge.trainer_id; });
        renderFilterPills();
        rerender();
        toast('Убрали из сохранённых');
      })
      .catch(function () { toast('Не получилось — попробуйте ещё раз'); });
  };

  /* ── photo helpers ──────────────────────────────────────────── */

  function imgOr(key, phClass, phEmoji) {
    var src = thumbUrl(key);
    return src
      ? '<img src="' + esc(src) + '" alt="" loading="lazy"/>'
      : '<span class="' + phClass + '" aria-hidden="true">' + phEmoji + '</span>';
  }

  /* ── PRIMARY card ───────────────────────────────────────────── */

  function renderPrimary(edge) {
    if (!edge) return '';
    var name = esc(edge.trainer_display_name || 'Тренер');
    var services = (edge.services || []).slice(0, 2).map(esc).join(' · ');
    var nb = edge.next_booking || null;
    var tid = edge.trainer_id;

    /*
     * Body has two zones:
     *   1. Info chips — real facts about the trainer or relationship
     *   2. One CTA + ghost "Профиль" text-link
     *
     * When there IS a next booking → show it prominently as an intent line.
     * When there isn't → show info chips only (no empty "Запись доступна" placeholder).
     */
    var bodyHtml = '';

    if (nb && nb.slot_date) {
      /* Next booking: most useful piece of info — show as highlighted block */
      var dateLabel = shortDateLabel(nb.slot_date, { allowToday: true });
      var time = (nb.start_time || '').slice(0, 5);
      var nbLine = (dateLabel && time)
        ? dateLabel + ' в ' + time
        : dateLabel || '';
      var nbService = esc(nb.service_name || '');
      var nbArena = esc(nb.arena_name || '');
      var nbSub = [nbService, nbArena].filter(Boolean).join(' · ');
      bodyHtml +=
        '<div class="st-primary-intent">' +
          '<span class="st-primary-intent-icon" aria-hidden="true">→</span>' +
          '<div class="st-primary-intent-lines">' +
            '<span class="st-primary-intent-main">Следующая · ' + esc(nbLine) + '</span>' +
            (nbSub ? '<span class="st-primary-intent-sub">' + nbSub + '</span>' : '') +
          '</div>' +
        '</div>';
    } else {
      /* No upcoming booking: show factual info chips */
      var chips = [];
      var sessions = sessionsLabel(edge.completed_count);
      if (sessions) {
        chips.push('<span class="st-stat-chip"><span class="st-stat-chip-icon">✓</span>' + esc(sessions) + ' вместе</span>');
      }
      if (edge.primary_arena_name) {
        chips.push('<span class="st-stat-chip"><span class="st-stat-chip-icon">◉</span>' + esc(edge.primary_arena_name) + '</span>');
      }
        if (edge.min_price_cents != null) {
        var p = priceByn(edge.min_price_cents);
        if (p) chips.push('<span class="st-stat-chip st-stat-chip-plain">' + esc(p) + '</span>');
      }
      if (chips.length) {
        bodyHtml += '<div class="st-primary-stats">' + chips.join('') + '</div>';
      }
    }

    bodyHtml +=
      '<div class="st-primary-actions">' +
        '<button type="button" class="st-primary-cta" data-cta-tid="' + esc(String(tid)) + '">Записаться →</button>' +
        '<button type="button" class="st-primary-profile-link" data-card-tid="' + esc(String(tid)) + '">Профиль</button>' +
      '</div>';

    return (
      '<section class="st-section">' +
        '<div class="st-section-head">' +
          '<span class="st-section-label">Мой тренер</span>' +
        '</div>' +
        '<div class="st-primary" data-card-tid="' + esc(String(tid)) + '">' +
          '<div class="st-primary-photo">' +
            imgOr(edge.trainer_list_photo_key, 'st-primary-photo-ph', '🏋') +
            '<span class="st-primary-badge"><span class="st-primary-badge-star">★</span>Основной</span>' +
            '<div class="st-primary-name-overlay">' +
              '<div class="st-primary-name">' + name + '</div>' +
              (services ? '<div class="st-primary-services">' + services + '</div>' : '') +
            '</div>' +
          '</div>' +
          '<div class="st-primary-body">' + bodyHtml + '</div>' +
        '</div>' +
      '</section>'
    );
  }

  /* ── SAVED grid ─────────────────────────────────────────────── */

  /**
   * "Why come back?" signals — pick the strongest one we have for this trainer.
   * Priority: upcoming booking > price > primary arena > services count > prior sessions.
   */
  function savedRelevanceLine(edge) {
    var nb = edge.next_booking || null;
    if (nb && nb.slot_date) {
      var d = shortDateLabel(nb.slot_date, { allowToday: true });
      var t = (nb.start_time || '').slice(0, 5);
      if (d && t) return { icon: '⏱', text: 'Запись ' + d + ' в ' + t, kind: 'booking' };
    }
    if (edge.min_price_cents != null) {
      var p = priceByn(edge.min_price_cents);
      if (p) return { icon: null, text: p, kind: 'price' };
    }
    if (edge.primary_arena_name) {
      return { icon: '◉', text: edge.primary_arena_name, kind: 'arena' };
    }
    var sessions = sessionsLabel(edge.completed_count);
    if (sessions) return { icon: '✓', text: sessions + ' с ним', kind: 'history' };
    return null;
  }

  function renderSavedGrid(list) {
    if (!list.length) return '';
    var cards = list.map(function (edge) {
      var name = esc(edge.trainer_display_name || 'Тренер');
      var services = (edge.services || []).slice(0, 2).map(esc).join(' · ');
      var rel = savedRelevanceLine(edge);
      var tid = edge.trainer_id;

      var relHtml = rel
        ? '<div class="st-saved-rel st-saved-rel-' + rel.kind + (!rel.icon ? ' st-saved-rel-no-icon' : '') + '">' +
            (rel.icon
              ? '<span class="st-saved-rel-icon" aria-hidden="true">' + rel.icon + '</span>'
              : '') +
            '<span class="st-saved-rel-text">' + esc(rel.text) + '</span>' +
          '</div>'
        : '';

      return (
        '<div class="st-saved-card" data-card-tid="' + esc(String(tid)) + '">' +
          '<button type="button" class="st-heart" data-unsave-tid="' + esc(String(tid)) + '" aria-label="Убрать из сохранённых">♥</button>' +
          '<div class="st-saved-photo-wrap">' +
            imgOr(edge.trainer_list_photo_key, 'st-saved-photo-ph', '🏋') +
            '<div class="st-saved-photo-overlay">' +
              '<div class="st-saved-photo-name">' + name + '</div>' +
              (services ? '<div class="st-saved-photo-services">' + services + '</div>' : '') +
            '</div>' +
          '</div>' +
          '<div class="st-saved-body">' +
            relHtml +
            '<button type="button" class="st-saved-cta" data-cta-tid="' + esc(String(tid)) + '">Записаться</button>' +
          '</div>' +
        '</div>'
      );
    }).join('');

    return (
      '<section class="st-section">' +
        '<div class="st-section-head">' +
          '<span class="st-section-label">Сохранённые</span>' +
          '<span class="st-section-count">' + list.length + '</span>' +
        '</div>' +
        '<div class="st-saved-grid">' + cards + '</div>' +
      '</section>'
    );
  }

  /* ── PAST horizontal strip ───────────────────────────────────── */

  function pastMetaLine(edge) {
    var sessions = sessionsLabel(edge.completed_count);
    var lastDate = shortDateLabel(edge.last_completed_at);
    if (sessions && lastDate) return sessions + ' · ' + lastDate;
    if (sessions) return sessions;
    if (lastDate) return 'Был ' + lastDate;
    return '';
  }

  function renderPastStrip(list) {
    if (!list.length) return '';
    var chips = list.map(function (edge) {
      var name = esc(edge.trainer_display_name || 'Тренер');
      var meta = pastMetaLine(edge);
      var tid = edge.trainer_id;

      return (
        '<button type="button" class="st-past-chip" data-card-tid="' + esc(String(tid)) + '">' +
          '<div class="st-past-avatar-wrap">' +
            '<div class="st-past-avatar">' +
              imgOr(edge.trainer_list_photo_key, 'st-past-avatar-ph', '🏋') +
            '</div>' +
            '<span class="st-past-replay-badge" aria-label="Записаться снова">↻</span>' +
          '</div>' +
          '<div class="st-past-name-line">' + name + '</div>' +
          (meta ? '<div class="st-past-meta">' + esc(meta) + '</div>' : '') +
        '</button>'
      );
    }).join('');

    return (
      '<section class="st-section">' +
        '<div class="st-section-head">' +
          '<span class="st-section-label">Тренировались раньше</span>' +
          '<span class="st-section-count">' + list.length + '</span>' +
        '</div>' +
        '<div class="st-past-strip">' + chips + '</div>' +
      '</section>'
    );
  }

  /* ── Wire interactions on rendered DOM ──────────────────────── */

  function wireMount(container) {
    /* Card containers — navigate to catalog profile on tap */
    container.querySelectorAll('[data-card-tid]:not(button)').forEach(function (el) {
      el.addEventListener('click', function (e) {
        if (e.target.closest('[data-cta-tid]')) return;
        if (e.target.closest('[data-unsave-tid]')) return;
        if (e.target.closest('button[data-card-tid]')) return;
        var tid = el.getAttribute('data-card-tid');
        goTo('catalog?trainer_id=' + encodeURIComponent(tid));
      });
    });
    /* "Профиль" text-link buttons (data-card-tid on a <button>) */
    container.querySelectorAll('button[data-card-tid]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var tid = btn.getAttribute('data-card-tid');
        goTo('catalog?trainer_id=' + encodeURIComponent(tid));
      });
    });
    /* "Записаться" CTA buttons → open booking flow */
    container.querySelectorAll('[data-cta-tid]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var tid = btn.getAttribute('data-cta-tid');
        goTo('catalog?trainer_id=' + encodeURIComponent(tid) + '&action=book');
      });
    });
    container.querySelectorAll('[data-unsave-tid]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        e.preventDefault();
        var tid = btn.getAttribute('data-unsave-tid');
        var edge = state.saved.find(function (x) { return String(x.trainer_id) === String(tid); });
        if (edge) openConfirm(edge);
      });
    });
    container.querySelectorAll('img').forEach(function (img) {
      img.onerror = function () { img.style.display = 'none'; };
    });
  }

  /* ── Filter pills ────────────────────────────────────────────── */

  /**
   * Pills are built from services of SAVED edges only — this is the active-intent layer
   * where the client is comparing. Show only when ≥2 distinct services exist.
   */
  function buildFilterServices() {
    var seen = {};
    var out = [];
    state.saved.forEach(function (e) {
      (e.services || []).forEach(function (s) {
        if (!seen[s]) { seen[s] = true; out.push(s); }
      });
    });
    return out.length >= 2 ? out : [];
  }

  function renderFilterPills() {
    var wrap = document.getElementById('filterWrap');
    if (!wrap) return;
    var services = buildFilterServices();
    if (!services.length) {
      wrap.style.display = 'none';
      wrap.innerHTML = '';
      if (state.filter !== 'all') state.filter = 'all';
      return;
    }
    /* Reset filter if previously selected service is no longer present */
    if (state.filter !== 'all' && services.indexOf(state.filter) === -1) state.filter = 'all';

    var labels = ['Все'].concat(services);
    wrap.innerHTML = labels.map(function (s) {
      var isActive = (s === 'Все' && state.filter === 'all') || s === state.filter;
      return '<button type="button" class="st-filter-pill' + (isActive ? ' active' : '') +
        '" data-svc="' + esc(s) + '">' + esc(s) + '</button>';
    }).join('');
    wrap.style.display = '';
    wrap.querySelectorAll('.st-filter-pill').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var svc = btn.getAttribute('data-svc');
        state.filter = svc === 'Все' ? 'all' : svc;
        wrap.querySelectorAll('.st-filter-pill').forEach(function (b) {
          b.classList.toggle('active', b === btn);
        });
        rerender();
      });
    });
  }

  /** Filter applies to all 3 sections — clean contextual switch across the screen. */
  function applyFilter(edges) {
    if (state.filter === 'all') return edges;
    return edges.filter(function (e) {
      return Array.isArray(e.services) && e.services.indexOf(state.filter) !== -1;
    });
  }

  function applyFilterToPrimary(edge) {
    if (!edge) return null;
    if (state.filter === 'all') return edge;
    if ((edge.services || []).indexOf(state.filter) !== -1) return edge;
    return null;
  }

  /* ── Empty state ────────────────────────────────────────────── */

  function renderEmpty(mount) {
    mount.innerHTML =
      '<div class="st-empty-block">' +
        '<div class="st-empty-icon-wrap"><span class="st-empty-icon">♥</span></div>' +
        '<div class="st-empty-title">Здесь будут ваши тренеры</div>' +
        '<div class="st-empty-desc">Сохраняйте тех, кто понравился — чтобы возвращаться к ним одним тапом и быстро записываться.</div>' +
        '<button type="button" class="st-empty-cta" id="btnEmptyCatalog">Найти тренера</button>' +
      '</div>';
    var b = document.getElementById('btnEmptyCatalog');
    if (b) b.onclick = function () { goTo('catalog?tab=catalog'); };
  }

  function renderEmptyFilter(mount) {
    mount.innerHTML =
      '<div class="st-empty-block">' +
        '<div class="st-empty-icon-wrap"><span class="st-empty-icon">⚲</span></div>' +
        '<div class="st-empty-title">Никто не подходит под фильтр</div>' +
        '<div class="st-empty-desc">Попробуйте другую услугу или сбросьте фильтр.</div>' +
        '<button type="button" class="st-empty-cta" id="btnResetFilter">Показать всех</button>' +
      '</div>';
    var b = document.getElementById('btnResetFilter');
    if (b) b.onclick = function () {
      state.filter = 'all';
      var wrap = document.getElementById('filterWrap');
      if (wrap) wrap.querySelectorAll('.st-filter-pill').forEach(function (p) {
        p.classList.toggle('active', p.getAttribute('data-svc') === 'Все');
      });
      rerender();
    };
  }

  /* ── Main render ─────────────────────────────────────────────── */

  function rerender() {
    var mount = document.getElementById('mainMount');
    if (!mount) return;

    var primary = applyFilterToPrimary(state.primary);
    var savedFiltered = applyFilter(state.saved);
    var pastFiltered = applyFilter(state.past);

    var totalAll = (state.primary ? 1 : 0) + state.saved.length + state.past.length;
    if (totalAll === 0) { renderEmpty(mount); return; }

    var totalVisible = (primary ? 1 : 0) + savedFiltered.length + pastFiltered.length;
    if (totalVisible === 0) { renderEmptyFilter(mount); return; }

    var html = '';
    if (primary) html += renderPrimary(primary);
    if (savedFiltered.length) html += renderSavedGrid(savedFiltered);
    if (pastFiltered.length) html += renderPastStrip(pastFiltered);
    mount.innerHTML = html;
    wireMount(mount);
  }

  /* ── Bootstrap ───────────────────────────────────────────────── */

  if (!getInitData()) {
    var mountInit = document.getElementById('mainMount');
    if (mountInit) {
      mountInit.innerHTML =
        '<div class="st-empty-block">' +
          '<div class="st-empty-icon-wrap"><span class="st-empty-icon">🔒</span></div>' +
          '<div class="st-empty-title">Нужна авторизация</div>' +
          '<div class="st-empty-desc">Откройте страницу из клиентского бота Telegram, чтобы увидеть своих тренеров.</div>' +
        '</div>';
    }
    return;
  }

  fetch(apiUrl('/client/trainer-edges'), { headers: headersJson() })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(String(r.status))); })
    .then(function (data) {
      state.primary = data.primary || null;
      state.saved = Array.isArray(data.saved) ? data.saved : [];
      state.past = Array.isArray(data.past) ? data.past : [];
      renderFilterPills();
      rerender();
    })
    .catch(function () {
      var mountErr = document.getElementById('mainMount');
      if (!mountErr) return;
      mountErr.innerHTML =
        '<div class="st-empty-block">' +
          '<div class="st-empty-icon-wrap"><span class="st-empty-icon">⚠</span></div>' +
          '<div class="st-empty-title">Не удалось загрузить</div>' +
          '<div class="st-empty-desc">Проверьте соединение или откройте страницу из клиентского бота.</div>' +
        '</div>';
    });
})();
