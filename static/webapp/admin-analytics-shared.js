/* Shared helpers for admin analytics Mini-Apps. Loaded via <script src="..."> in each page.
 * Exposes a single global `AdmAnalytics` namespace with: bootstrap(), getJson(), formatters,
 * sparkline rendering, and drilldown card helpers.
 */
(function (global) {
  'use strict';
  var tg = global.Telegram && global.Telegram.WebApp;
  if (tg) { try { tg.ready(); tg.expand(); } catch (_) {} }
  var initData = tg ? tg.initData : '';

  /**
   * Always resolve to the real FastAPI mount: all webapp JSON lives under /api/webapp/...
   * (router prefix in webapp.py). A previous version wrongly stripped the prefix when
   * initData was present, so requests went to /admin/... and never hit the API — JSON
   * never loaded. Relative paths like "/admin/stats/retention" must become
   * "/api/webapp/admin/stats/retention".
   */
  function apiUrl(path) {
    if (path.indexOf('/api/') === 0) {
      return path;
    }
    if (path.indexOf('/') === 0) {
      return '/api/webapp' + path;
    }
    return '/api/webapp/' + path;
  }

  function fetchWithTimeout(url, opts, ms) {
    ms = ms || 15000;
    var c = new AbortController();
    var t = setTimeout(function () { c.abort(); }, ms);
    return fetch(url, Object.assign({}, opts, { signal: c.signal }))
      .then(function (r) { clearTimeout(t); return r; })
      .catch(function (e) { clearTimeout(t); throw e; });
  }

  function getJson(path) {
    var url = apiUrl(path);
    var sep = url.indexOf('?') >= 0 ? '&' : '?';
    if (initData) url += sep + 'init_data=' + encodeURIComponent(initData);
    var headers = initData
      ? { 'X-Telegram-Init-Data': initData, Accept: 'application/json' }
      : { Accept: 'application/json' };
    return fetchWithTimeout(url, { headers: headers, credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatBYN(cents, opts) {
    cents = +cents || 0;
    var byn = cents / 100;
    var compact = opts && opts.compact;
    if (compact && Math.abs(byn) >= 10000) {
      if (Math.abs(byn) >= 1000000) return (byn / 1000000).toFixed(1).replace(/\.0$/, '') + ' млн ⃅';
      return (byn / 1000).toFixed(1).replace(/\.0$/, '') + ' тыс ⃅';
    }
    var s = (byn % 1 === 0) ? byn.toFixed(0) : byn.toFixed(2);
    return s.replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' ⃅';
  }

  function formatNum(n) {
    n = +n || 0;
    return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  }

  function formatPct(p) {
    if (p == null || isNaN(p)) return '—';
    var sign = p > 0 ? '+' : '';
    return sign + (Math.round(p * 10) / 10) + '%';
  }

  function formatDate(iso) {
    if (!iso) return '—';
    var s = String(iso);
    var d = s.length >= 10 ? s.slice(0, 10) : s;
    var parts = d.split('-');
    if (parts.length === 3) return parts[2] + '.' + parts[1] + '.' + parts[0];
    return d;
  }

  function deltaClass(p) {
    if (p == null || isNaN(p)) return 'flat';
    if (p > 0) return 'up';
    if (p < 0) return 'down';
    return 'flat';
  }

  function sparkline(values, labels) {
    if (!values || !values.length) return '';
    var max = Math.max.apply(null, values.map(function (v) { return +v || 0; }));
    if (max <= 0) max = 1;
    var bars = values.map(function (v) {
      var pct = Math.max(4, Math.round((+v || 0) * 100 / max));
      var muted = (+v || 0) === 0 ? ' muted' : '';
      return '<div class="adm-spark-bar' + muted + '" style="height:' + pct + '%" title="' + escapeHtml(String(v)) + '"></div>';
    }).join('');
    var labs = '';
    if (labels && labels.length === values.length) {
      labs = '<div class="adm-spark-labels">' +
        labels.map(function (l) { return '<div class="adm-spark-label">' + escapeHtml(l) + '</div>'; }).join('') +
        '</div>';
    }
    return '<div class="adm-spark">' + bars + '</div>' + labs;
  }

  function drilldown(items) {
    /*
     * items: [{ title, meta, value, extra (HTML string or null) }]
     * Renders a list of expandable cards. Click toggles `.open` on each item.
     */
    if (!items || !items.length) return '<div class="adm-empty">Пусто</div>';
    var html = items.map(function (it) {
      var extraHtml = it.extra ? '<div class="adm-list-extra">' + it.extra + '</div>' : '';
      var head = '<div class="adm-list-head">' +
        '<div>' +
          '<div class="adm-list-title">' + (it.title || '') + '</div>' +
          (it.meta ? '<div class="adm-list-meta">' + it.meta + '</div>' : '') +
        '</div>' +
        (it.value != null ? '<div class="adm-list-value">' + it.value + '</div>' : '') +
        '</div>';
      return '<div class="adm-list-item' + (it.extra ? ' has-extra' : '') + '">' + head + extraHtml + '</div>';
    }).join('');
    return html;
  }

  function bindDrilldown(rootEl) {
    if (!rootEl) return;
    rootEl.addEventListener('click', function (ev) {
      var item = ev.target.closest('.adm-list-item.has-extra');
      if (!item || !rootEl.contains(item)) return;
      item.classList.toggle('open');
      try { if (tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged) tg.HapticFeedback.selectionChanged(); } catch (_) {}
    });
  }

  function mount(opts) {
    /* opts: { endpoint, render(data) -> HTML string, contentEl }
     * Loads JSON, calls render(data), injects HTML, wires drilldown.
     */
    var el = opts.contentEl || document.getElementById('content');
    el.innerHTML = '<div class="adm-loading">Загрузка…</div>';
    getJson(opts.endpoint).then(function (data) {
      try {
        el.innerHTML = opts.render(data);
        bindDrilldown(el);
      } catch (e) {
        el.innerHTML = '<div class="adm-error">Ошибка отрисовки: ' + escapeHtml(e && e.message || e) + '</div>';
      }
    }).catch(function (e) {
      var m = (e && e.message) ? e.message : 'Ошибка сети или таймаут';
      el.innerHTML = '<div class="adm-error">' + escapeHtml(m) + '</div>';
    });
  }

  global.AdmAnalytics = {
    initData: initData,
    getJson: getJson,
    apiUrl: apiUrl,
    escapeHtml: escapeHtml,
    formatBYN: formatBYN,
    formatNum: formatNum,
    formatPct: formatPct,
    formatDate: formatDate,
    deltaClass: deltaClass,
    sparkline: sparkline,
    drilldown: drilldown,
    bindDrilldown: bindDrilldown,
    mount: mount,
  };
})(window);
