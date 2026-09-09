/* Product Analytics Dashboard — founder-grade product truth.
 * Loaded after admin-analytics-shared.js (AdmAnalytics namespace available).
 * One GET /api/webapp/admin/stats/product load, then render all 6 sections.
 */
(function () {
  'use strict';
  var A = window.AdmAnalytics;

  /* ── helpers ─────────────────────────────────────────────────────── */

  function pctStr(v, opts) {
    if (v == null || isNaN(v)) return '—';
    var s = (Math.round(v * 10) / 10) + '%';
    if (opts && opts.prefix) s = opts.prefix + s;
    return s;
  }

  function funnelBar(pct, biggest) {
    /* biggest = max pct in funnel to normalize bar width */
    var w = biggest > 0 ? Math.round((pct / biggest) * 100) : 0;
    return w;
  }

  function deltaClass(diff) {
    if (diff == null) return '';
    if (diff >= 20) return 'hi';
    if (diff >= 8)  return 'mid';
    return 'lo';
  }

  /* ── section renderers ───────────────────────────────────────────── */

  function renderActivationFunnel(af) {
    if (!af || !af.created) return '<div class="adm-empty">Нет данных</div>';

    /* Онбординг v2: модерация гейтит каталог, а не инструменты тренера (см. TASK-026) —
       первая реальная запись у большинства тренеров случается раньше, чем публикация
       в каталоге, а не после неё. Порядок шагов отражает это, иначе процент "выпадения"
       перед публикацией в каталоге был бы отрицательным и нечитаемым. */
    var steps = [
      { key: 'created',              label: 'Создан аккаунт тренера' },
      { key: 'linked_telegram',      label: 'Привязал Telegram' },
      { key: 'has_template',         label: 'Настроил шаблон расписания' },
      { key: 'copied_invite',        label: 'Скопировал ссылку для клиентов' },
      { key: 'has_first_booking',    label: 'Первая реальная запись' },
      { key: 'submitted_moderation', label: 'Отправил профиль на проверку' },
      { key: 'activated',            label: 'Опубликован в каталоге (status = active)' },
    ];

    var top = af.created || 1;
    var html = '<div class="pa-funnel">';
    for (var i = 0; i < steps.length; i++) {
      var step = steps[i];
      var count = af[step.key] || 0;
      var pct   = top > 0 ? Math.round(count / top * 100) : 0;
      var barW  = pct; // already relative to total

      var dropHtml = '';
      if (i > 0) {
        var prev = af[steps[i - 1].key] || 0;
        if (prev > 0) {
          var dropPct = Math.round((1 - count / prev) * 100);
          if (dropPct > 0) {
            dropHtml = '<div class="pa-funnel-drop">↓ выпадает ' + dropPct + '%</div>';
          }
        }
      }

      var isBigDrop = i > 0 && (() => {
        var prev = af[steps[i - 1].key] || 0;
        return prev > 0 && (1 - count / prev) > 0.35;
      })();

      html += '<div class="pa-funnel-step">';
      html += '<div class="pa-funnel-label">';
      html += '<span class="pa-funnel-name">' + A.escapeHtml(step.label) + '</span>';
      html += '<span class="pa-funnel-nums">' + A.formatNum(count) + ' · ' + pct + '%</span>';
      html += '</div>';
      html += '<div class="pa-funnel-bar-track">';
      html += '<div class="pa-funnel-bar-fill' + (isBigDrop ? ' drop' : '') + '" style="width:' + barW + '%"></div>';
      html += '</div>';
      html += dropHtml;
      html += '</div>';
    }
    html += '</div>';
    return html;
  }

  function renderProofOfValue(pov) {
    if (!pov) return '<div class="adm-empty">Нет данных</div>';
    var n = pov.active_total || 0;

    var items = [
      { label: 'Создал первую запись',          v: pov.first_booking,    p: pov.first_booking_pct },
      { label: 'Создал вторую запись',           v: pov.second_booking,   p: pov.second_booking_pct },
      { label: '5+ реальных записей',            v: pov.five_bookings,    p: pov.five_bookings_pct },
      { label: 'Создал шаблон расписания',       v: pov.has_template,     p: pov.has_template_pct },
      { label: 'Пригласил клиента',              v: pov.invited_client,   p: pov.invited_client_pct },
      { label: 'Каталог активен',                v: pov.catalog_live,     p: pov.catalog_live_pct },
      { label: 'Получил первый просмотр',        v: pov.got_first_view,   p: pov.got_first_view_pct },
      { label: 'Получил первый переход в Telegram', v: pov.got_first_click, p: pov.got_first_click_pct },
      { label: 'Получил первое избранное',       v: pov.got_first_save,   p: pov.got_first_save_pct },
    ];

    var html = '<div class="pa-pov-grid">';
    items.forEach(function (it) {
      html += '<div class="pa-pov-item">';
      html += '<div class="pa-pov-label">' + it.label + '</div>';
      html += '<div class="pa-pov-value">' + A.formatNum(it.v || 0) + '</div>';
      html += '<div class="pa-pov-pct">' + pctStr(it.p) + ' из ' + A.formatNum(n) + '</div>';
      html += '</div>';
    });
    html += '</div>';
    return html;
  }

  function renderMarketplace(m) {
    if (!m) return '<div class="adm-empty">Нет данных</div>';

    var rows = [
      {
        icon: '🏷',
        name: 'Тренеров в каталоге',
        meta: 'С профилем и видимостью = true',
        num: A.formatNum(m.trainers_in_catalog),
        conv: null,
      },
      {
        icon: '👁',
        name: 'Просмотров профиля',
        meta: A.formatNum(m.trainers_with_views) + ' тренеров получили хотя бы 1 просмотр',
        num: A.formatNum(m.total_views),
        conv: null,
      },
      {
        icon: '📲',
        name: 'Переходов в Telegram',
        meta: A.formatNum(m.trainers_with_clicks) + ' тренеров получили хотя бы 1 переход',
        num: A.formatNum(m.total_clicks),
        conv: m.view_to_click_pct != null
          ? { label: 'конверсия из просмотров', val: pctStr(m.view_to_click_pct) }
          : null,
      },
      {
        icon: '❤️',
        name: 'Добавлений в избранное',
        meta: A.formatNum(m.trainers_with_saves) + ' тренеров получили хотя бы 1 сохранение',
        num: A.formatNum(m.total_saves),
        conv: m.click_to_save_pct != null
          ? { label: 'конверсия из переходов', val: pctStr(m.click_to_save_pct) }
          : null,
      },
    ];

    var html = '';
    rows.forEach(function (row) {
      html += '<div class="pa-demand-row">';
      html += '<div class="pa-demand-icon">' + row.icon + '</div>';
      html += '<div class="pa-demand-body">';
      html += '<div class="pa-demand-name">' + row.name + '</div>';
      html += '<div class="pa-demand-meta">' + A.escapeHtml(row.meta) + '</div>';
      html += '</div>';
      html += '<div class="pa-demand-num">' + row.num + '</div>';
      html += '</div>';
      if (row.conv) {
        html += '<div class="pa-demand-conv">' + A.escapeHtml(row.conv.label) + ': <span>' + row.conv.val + '</span></div>';
      }
    });
    return html;
  }

  function renderMonetization(mo) {
    if (!mo) return '<div class="adm-empty">Нет данных</div>';

    var steps = [
      { label: 'Триал\nстартовал',   num: mo.trial_started,        color: '#6ea8ff' },
      { label: 'Триал\nактивен',      num: mo.trial_active,         color: '#34c759' },
      { label: 'Истёк без\nоплаты',   num: mo.trial_expired_no_paid, color: '#ff6b60' },
      { label: 'Оплатил\nхотя бы раз', num: mo.paid_at_least_once,  color: '#fde68a' },
    ];

    var html = '<div class="pa-mono-funnel">';
    steps.forEach(function (s, i) {
      if (i > 0) html += '<div class="pa-mono-arrow">›</div>';
      html += '<div class="pa-mono-step">';
      html += '<div class="pa-mono-step-num" style="color:' + s.color + '">' + A.formatNum(s.num || 0) + '</div>';
      html += '<div class="pa-mono-step-label">' + A.escapeHtml(s.label) + '</div>';
      html += '</div>';
    });
    html += '</div>';

    html += '<div class="adm-row-list">';
    html += '<div><span>Trial → Paid конверсия</span><span>' + pctStr(mo.trial_to_paid_pct) + '</span></div>';
    html += '<div><span>Истёк триал (>30 дн. назад), не оплатили</span><span>' + A.formatNum(mo.trial_expired_30d_churned || 0) + '</span></div>';
    html += '</div>';
    return html;
  }

  function renderHabit(h) {
    if (!h) return '<div class="adm-empty">Нет данных</div>';
    var html = '<div class="adm-kpi-grid cols-3">';
    html += kpi('Активных тренеров', A.formatNum(h.active_total), 'status = active');
    html += kpi('Активны на этой неделе', A.formatNum(h.weekly_active), pctStr(h.weekly_active_pct) + ' от всех');
    html += kpi('Средн. записей на тренера', String(h.avg_bookings_per_trainer || 0), 'все реальные записи');
    html += '</div>';
    return html;
  }

  function kpi(label, value, sub) {
    return '<div class="adm-kpi"><div class="adm-kpi-label">' + label + '</div>' +
           '<div class="adm-kpi-value">' + value + '</div>' +
           '<div class="adm-kpi-sub">' + sub + '</div></div>';
  }

  /* ── CORRELATION TABLE (THE KEY) ─────────────────────────────────── */

  /** TASK-028: per-hint показ/клик/отказ за последние 30 дней. Простая таблица, без чарта. */
  function renderHintFunnel(rows) {
    if (!rows || !rows.length) return '<div class="adm-empty">Нет данных за последние 30 дней</div>';
    var html = '<table class="adm-table"><thead><tr>' +
      '<th>Подсказка</th><th class="num">Показов</th><th class="num">Кликов</th>' +
      '<th class="num">% клика</th><th class="num">Отказов</th><th class="num">% отказа</th>' +
      '</tr></thead><tbody>';
    rows.forEach(function (row) {
      var shown = row.shown || 0;
      var clickPct = shown > 0 ? Math.round((row.clicked / shown) * 100) : 0;
      var dismissPct = shown > 0 ? Math.round((row.dismissed / shown) * 100) : 0;
      html += '<tr>' +
        '<td>' + A.escapeHtml(row.item_id || '—') + '</td>' +
        '<td class="num">' + A.formatNum(shown) + '</td>' +
        '<td class="num">' + A.formatNum(row.clicked || 0) + '</td>' +
        '<td class="num">' + clickPct + '%</td>' +
        '<td class="num">' + A.formatNum(row.dismissed || 0) + '</td>' +
        '<td class="num">' + dismissPct + '%</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  /** TASK-028: гистограмма «сколько функций из N тронул тренер» на день 7 и день 14. */
  function renderFeatureAdoption(adoption) {
    if (!adoption) return '<div class="adm-empty">Нет данных</div>';
    var total = adoption.total_features || 11;
    function tableFor(rows) {
      if (!rows || !rows.length) return '<div class="adm-empty">Нет тренеров нужного возраста</div>';
      var trainersTotal = rows.reduce(function (s, r) { return s + (r.trainers || 0); }, 0);
      var html = '<table class="adm-table"><thead><tr>' +
        '<th>Функций тронуто (из ' + total + ')</th><th class="num">Тренеров</th><th class="num">%</th>' +
        '</tr></thead><tbody>';
      rows.forEach(function (row) {
        var pct = trainersTotal > 0 ? Math.round((row.trainers / trainersTotal) * 100) : 0;
        html += '<tr>' +
          '<td>' + A.formatNum(row.features_touched) + '</td>' +
          '<td class="num">' + A.formatNum(row.trainers) + '</td>' +
          '<td class="num">' + pct + '%</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
      return html;
    }
    var html = '<div class="pa-corr-title" style="margin-bottom:8px">День 7</div>';
    html += tableFor(adoption.day7);
    html += '<div class="pa-corr-title" style="margin:16px 0 8px">День 14</div>';
    html += tableFor(adoption.day14);
    return html;
  }

  function renderCorrelation(corr) {
    if (!corr || corr.length === 0) return '<div class="adm-empty">Недостаточно данных (нужны тренеры, активные ≥14 дней)</div>';

    var paid    = corr.find(function (c) { return c.is_paid; });
    var notPaid = corr.find(function (c) { return !c.is_paid; });

    if (!paid || !notPaid) {
      /* Only one cohort available */
      var only = corr[0];
      return '<div class="adm-empty">Только одна группа: ' + (only.is_paid ? 'платящие' : 'бесплатные') + ' (' + only.cohort_size + ')</div>';
    }

    var rows = [
      { label: 'Создал первую запись',          paid: paid.pct_first_booking,    notPaid: notPaid.pct_first_booking },
      { label: 'Создал вторую запись',           paid: paid.pct_second_booking,   notPaid: notPaid.pct_second_booking },
      { label: '5+ записей',                     paid: paid.pct_five_bookings,    notPaid: notPaid.pct_five_bookings },
      { label: 'Настроил шаблон расписания',     paid: paid.pct_has_template,     notPaid: notPaid.pct_has_template },
      { label: 'Пригласил клиента',              paid: paid.pct_invited_client,   notPaid: notPaid.pct_invited_client },
      { label: 'Каталог живой (профиль + видим)', paid: paid.pct_catalog_live,    notPaid: notPaid.pct_catalog_live },
      { label: 'Получил просмотр профиля',       paid: paid.pct_got_view,         notPaid: notPaid.pct_got_view },
      { label: 'Получил переход в Telegram',     paid: paid.pct_got_click,        notPaid: notPaid.pct_got_click },
      { label: 'Попал в избранное',              paid: paid.pct_got_save,         notPaid: notPaid.pct_got_save },
    ];

    /* Sort by delta descending to surface biggest predictors first */
    rows.sort(function (a, b) {
      var da = (a.paid || 0) - (a.notPaid || 0);
      var db = (b.paid || 0) - (b.notPaid || 0);
      return db - da;
    });

    /* Compute biggest delta to annotate top predictors */
    var topDelta = rows[0] ? ((rows[0].paid || 0) - (rows[0].notPaid || 0)) : 0;

    /* Insight sentence about top predictor */
    var topRow = rows[0];
    var topDiff = topRow ? ((topRow.paid || 0) - (topRow.notPaid || 0)) : 0;
    var insightHtml = '';
    if (topRow && topDiff > 5) {
      insightHtml = '<div class="pa-corr-insight">' +
        '<strong>' + A.escapeHtml(topRow.label) + '</strong> — самый сильный разрыв между платящими и нет: ' +
        '<strong>' + pctStr(topRow.paid) + '</strong> vs <strong>' + pctStr(topRow.notPaid) + '</strong> ' +
        '(дельта <strong>+' + Math.round(topDiff) + '&nbsp;п.п.</strong>). ' +
        'Это главный кандидат на leading indicator.</div>';
    }

    var tableHtml = '<table class="pa-corr-table">';
    tableHtml += '<thead><tr>';
    tableHtml += '<th>Поведение</th>';
    tableHtml += '<th style="text-align:right">Платящие<br><small>n=' + paid.cohort_size + '</small></th>';
    tableHtml += '<th style="text-align:right">Не платили<br><small>n=' + notPaid.cohort_size + '</small></th>';
    tableHtml += '<th style="text-align:right">Δ</th>';
    tableHtml += '</tr></thead><tbody>';

    rows.forEach(function (row, i) {
      var diff = (row.paid || 0) - (row.notPaid || 0);
      var diffStr = diff >= 0 ? '+' + Math.round(diff) + ' п.п.' : Math.round(diff) + ' п.п.';
      var cls = deltaClass(diff);
      var highlight = i < 3 ? ' class="highlight-row"' : '';
      tableHtml += '<tr' + highlight + '>';
      tableHtml += '<td>' + A.escapeHtml(row.label) + (i < 3 ? ' <span style="color:#a78bfa;font-size:10px">★</span>' : '') + '</td>';
      tableHtml += '<td class="paid-val" style="text-align:right">' + pctStr(row.paid) + '</td>';
      tableHtml += '<td class="unpaid-val" style="text-align:right">' + pctStr(row.notPaid) + '</td>';
      tableHtml += '<td class="delta-val ' + cls + '" style="text-align:right">' + diffStr + '</td>';
      tableHtml += '</tr>';
    });
    tableHtml += '</tbody></table>';

    tableHtml += '<div class="pa-corr-legend">';
    tableHtml += '<div class="pa-corr-legend-item"><div class="pa-corr-legend-dot" style="background:#34c759"></div>Платящие</div>';
    tableHtml += '<div class="pa-corr-legend-item"><div class="pa-corr-legend-dot" style="background:#6ea8ff"></div>Не платили</div>';
    tableHtml += '<div class="pa-corr-legend-item"><span style="color:#a78bfa">★</span>&nbsp;Топ-3 предикторы оплаты</div>';
    tableHtml += '</div>';

    tableHtml += '<div style="font-size:11px;color:var(--tg-theme-hint-color);margin-top:10px;line-height:1.4">' +
      'Когорта: тренеры в статусе active, активированные ≥14 дней назад. ' +
      'Данные фактические, не прогнозные. ' +
      'Большая дельта = поведение сильнее связано с оплатой.' +
      '</div>';

    return insightHtml + tableHtml;
  }

  function renderIceHealth(h) {
    if (!h) return '<div class="adm-empty">Нет данных</div>';
    var html = '';
    var silent = h.silent_sources || [];
    html += '<div class="pa-corr-title">Молчащие источники</div>';
    if (!silent.length) {
      html += '<div class="adm-empty" style="margin-bottom:12px">Все включённые job недавно давали ok</div>';
    } else {
      html += '<table class="pa-corr-table" style="margin-bottom:14px"><thead><tr>';
      html += '<th>Арена</th><th>Каденс</th><th>last ok</th><th>успех 7д</th><th>успех 30д</th>';
      html += '</tr></thead><tbody>';
      silent.forEach(function (row) {
        html += '<tr>';
        html += '<td>' + A.escapeHtml(row.arena_name || ('#' + row.arena_id)) + '</td>';
        html += '<td>' + A.escapeHtml(row.cadence || '') + '</td>';
        html += '<td>' + A.escapeHtml(row.last_ok_at || 'никогда') + '</td>';
        html += '<td>' + pctStr(row.success_rate_7d != null ? row.success_rate_7d * 100 : null) + '</td>';
        html += '<td>' + pctStr(row.success_rate_30d != null ? row.success_rate_30d * 100 : null) + '</td>';
        html += '</tr>';
      });
      html += '</tbody></table>';
    }

    html += '<div class="pa-corr-title">Доля арен A / B / C по городам</div>';
    html += '<div style="font-size:11px;color:var(--tg-theme-hint-color);margin-bottom:8px">Счётчик A рядом с долей. WoW — к прошлой неделе. Плотность = арены с ≥1 записью за 30 дней. Цены разных валют не суммируются.</div>';
    var cities = h.cities || [];
    if (!cities.length) {
      html += '<div class="adm-empty">Нет арен</div>';
    } else {
      html += '<table class="pa-corr-table"><thead><tr>';
      html += '<th>Город</th><th>A</th><th>B</th><th>C</th><th>A нед. назад</th><th>Записи 30д</th><th>Просрочка</th>';
      html += '</tr></thead><tbody>';
      cities.forEach(function (row) {
        var aLabel = (row.tier_a_count || 0) + '/' + (row.arenas_total || 0) + ' · ' + pctStr(row.tier_a_share != null ? row.tier_a_share * 100 : null);
        var delta = row.tier_a_count_delta;
        var deltaCls = delta > 0 ? 'up' : (delta < 0 ? 'down' : 'flat');
        var deltaStr = (delta > 0 ? '+' : '') + (delta == null ? '—' : delta);
        html += '<tr>';
        html += '<td>' + A.escapeHtml(row.city_name || '') + '</td>';
        html += '<td>' + A.escapeHtml(aLabel) + ' <span class="adm-delta ' + deltaCls + '">' + deltaStr + '</span></td>';
        html += '<td>' + (row.tier_b_count || 0) + ' · ' + pctStr(row.tier_b_share != null ? row.tier_b_share * 100 : null) + '</td>';
        html += '<td>' + (row.tier_c_count || 0) + ' · ' + pctStr(row.tier_c_share != null ? row.tier_c_share * 100 : null) + '</td>';
        html += '<td>' + (row.tier_a_count_prev || 0) + ' · ' + pctStr(row.tier_a_share_prev != null ? row.tier_a_share_prev * 100 : null) + '</td>';
        html += '<td>' + (row.arenas_with_bookings_30d || 0) + '/' + (row.arenas_total || 0) + '</td>';
        html += '<td>' + pctStr(row.stale_session_share != null ? row.stale_session_share * 100 : null) + '</td>';
        html += '</tr>';
      });
      html += '</tbody></table>';
    }
    html += '<div style="font-size:11px;color:var(--tg-theme-hint-color);margin-top:10px">Ручные правки сеансов за 7д: ' +
      A.formatNum(h.manual_admin_sessions_7d || 0) +
      ' · Калибровка точности: в воскресной сводке</div>';
    return html;
  }

  /* ── main render ─────────────────────────────────────────────────── */

  function render(d) {
    var html = '';

    /* Hero */
    html += '<div class="pa-hero">';
    html += '<div class="pa-hero-chip">Product Truth</div>';
    html += '<div class="pa-hero-title">Где воронка ломается?<br>Что создаёт привычку?</div>';
    html += '<div class="pa-hero-sub">Данные за сегодня · обновляется при каждом заходе · ' + A.escapeHtml(d.today || '') + '</div>';
    html += '</div>';

    /* Section 1: Activation Funnel */
    html += '<div class="pa-section" id="s-activation">';
    html += '<div class="adm-section-title">1 · Воронка активации</div>';
    html += '<div class="adm-card">';
    html += '<div style="font-size:12px;color:var(--tg-theme-hint-color);margin-bottom:12px">Шаги от создания аккаунта до первой реальной записи. Ищем самый большой провал.</div>';
    html += renderActivationFunnel(d.activation_funnel);
    html += '</div>';
    html += '</div>';

    /* Section 2: Proof of Value */
    html += '<div class="pa-section" id="s-proof">';
    html += '<div class="adm-section-title">2 · Доказательство ценности</div>';
    html += '<div class="adm-card">';
    html += '<div style="font-size:12px;color:var(--tg-theme-hint-color);margin-bottom:12px">% работающих тренеров (без деактивированных), которые дошли до каждого ценностного момента.</div>';
    html += renderProofOfValue(d.proof_of_value);
    html += '</div>';
    html += '</div>';

    /* Section 3: Marketplace */
    html += '<div class="pa-section" id="s-marketplace">';
    html += '<div class="adm-section-title">3 · Каталог и спрос</div>';
    html += '<div class="adm-card">';
    html += '<div style="font-size:12px;color:var(--tg-theme-hint-color);margin-bottom:12px">Воронка каталога: просмотры → переходы → избранное. Отделяем vanity от реального интереса.</div>';
    html += renderMarketplace(d.marketplace);
    html += '</div>';
    html += '</div>';

    /* Section 4: Monetization */
    html += '<div class="pa-section" id="s-mono">';
    html += '<div class="adm-section-title">4 · Монетизация</div>';
    html += '<div class="adm-card">';
    html += renderMonetization(d.monetization);
    html += '</div>';
    html += '</div>';

    /* Section 5: Habit */
    html += '<div class="pa-section" id="s-habit">';
    html += '<div class="adm-section-title">5 · Привычка и активность</div>';
    html += '<div class="adm-card">';
    html += renderHabit(d.habit);
    html += '</div>';
    html += '</div>';

    /* Section 6: Correlation — THE KEY */
    html += '<div class="pa-section" id="s-corr">';
    html += '<div class="adm-section-title" style="color:#a78bfa">6 · Корреляция — самое важное</div>';
    html += '<div class="adm-card">';
    html += '<div class="pa-corr-title">Что предсказывает оплату?</div>';
    html += '<div style="font-size:12px;color:var(--tg-theme-hint-color);margin-bottom:12px">' +
      'Сравниваем поведение платящих и неплатящих тренеров за первые 14+ дней. ' +
      'Строки отсортированы по дельте — самые сильные предикторы вверху. ' +
      '★ = топ-3 leading indicator.' +
      '</div>';
    html += renderCorrelation(d.correlation);
    html += '</div>';
    html += '</div>';

    /* Section 7: Ведение — воронка подсказок и адаптация функций (TASK-028) */
    html += '<div class="pa-section" id="s-guidance">';
    html += '<div class="adm-section-title">7 · Ведение — подсказки и функции</div>';
    html += '<div class="adm-card">';
    html += '<div class="pa-corr-title">Воронка подсказок (последние 30 дней)</div>';
    html += renderHintFunnel(d.hint_funnel);
    html += '</div>';
    html += '<div class="adm-card" style="margin-top:12px">';
    html += '<div class="pa-corr-title">Сколько функций тронул тренер</div>';
    html += renderFeatureAdoption(d.feature_adoption);
    html += '</div>';
    html += '</div>';

    html += '<div class="pa-section" id="s-ice">';
    html += '<div class="adm-section-title">8 · Лёд — свежесть и доля уровня A</div>';
    html += '<div class="adm-card">';
    html += renderIceHealth(d.ice_health);
    html += '</div>';
    html += '</div>';

    document.getElementById('content').innerHTML = html;
  }

  /* ── boot ────────────────────────────────────────────────────────── */

  A.getJson('/admin/stats/product')
    .then(function (data) { render(data); })
    .catch(function (err) {
      document.getElementById('content').innerHTML =
        '<div class="adm-error">Ошибка загрузки: ' + A.escapeHtml(String(err)) + '</div>';
    });
}());
