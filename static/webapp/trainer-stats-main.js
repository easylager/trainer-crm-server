    (function() {
      var tg = window.Telegram && window.Telegram.WebApp;
      if (tg) { tg.ready(); tg.expand(); }

      var initData = tg ? tg.initData : '';
      function fetchWithTimeout(url, opts, ms) {
        ms = ms || 15000;
        var c = new AbortController();
        var t = setTimeout(function() { c.abort(); }, ms);
        return fetch(url, Object.assign({}, opts || {}, { signal: c.signal }))
          .then(function(r) { clearTimeout(t); return r; })
          .catch(function(e) { clearTimeout(t); throw e; });
      }
      function withInitData(url) {
        if (!initData) return url;
        var sep = url.indexOf('?') >= 0 ? '&' : '?';
        return url + sep + 'init_data=' + encodeURIComponent(initData);
      }
      function getJson(url) {
        return fetchWithTimeout(withInitData(url)).then(function(r) {
          if (!r.ok) throw new Error(r.statusText);
          return r.json();
        });
      }
      function getJsonPath(path) {
        return fetchWithTimeout(withInitData(path)).then(function(r) {
          if (!r.ok) throw new Error(r.statusText || String(r.status));
          return r.json();
        });
      }

      function formatWeekRange(ws, we) {
        if (!ws || !we) return '—';
        var a = String(ws).split('-');
        var b = String(we).split('-');
        if (a.length >= 3 && b.length >= 3)
          return a[2] + '.' + a[1] + '–' + b[2] + '.' + b[1];
        return ws + ' – ' + we;
      }
      function formatDateShort(isoStr) {
        if (!isoStr) return '—';
        var p = String(isoStr).split('-');
        if (p.length >= 3) return p[2] + '.' + p[1];
        return isoStr;
      }

      function formatMonthTitle(isoStr) {
        if (!isoStr) return '—';
        var p = String(isoStr).split('-');
        if (p.length < 2) return isoStr;
        var months = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
        var mi = parseInt(p[1], 10) - 1;
        if (mi < 0 || mi > 11) return isoStr;
        return months[mi] + ' ' + p[0];
      }

      function renderTrend(pct) {
        if (pct == null || pct === 0) return '';
        var cls = pct > 0 ? 'up' : 'down';
        var sign = pct > 0 ? '+' : '';
        return '<span class="kpi-top-trend ' + cls + '">' + sign + pct + '%</span>';
      }

      function renderRevenueTrend(pct) {
        if (pct == null || pct === 0) return '';
        var cls = pct > 0 ? 'up' : 'down';
        var sign = pct > 0 ? '+' : '';
        return ' <span class="kpi-top-trend ' + cls + '">' + sign + pct + '%</span>';
      }

      function renderStars(avg) {
        if (avg == null) return '—';
        var full = Math.floor(avg);
        var half = (avg - full) >= 0.5 ? 1 : 0;
        var empty = 5 - full - half;
        var s = '★'.repeat(full) + (half ? '½' : '') + '☆'.repeat(empty);
        return '<span class="stars">' + s + '</span> ' + Number(avg).toFixed(1);
      }

      function formatMoney(cents) {
        if (cents == null) return '—';
        var v = (cents || 0) / 100;
        return v.toFixed(v % 1 === 0 ? 0 : 2) + ' BYN';
      }

      function rankClass(i) {
        if (i === 0) return 'gold';
        if (i === 1) return 'silver';
        if (i === 2) return 'bronze';
        return '';
      }

      function buildCoachTips(d) {
        var tips = [];
        var load = d.load_pct;
        var wst = d.week_slots_total || 0;
        if (load != null && load < 36 && wst >= 4) {
          tips.push('Загрузка слотов невысокая — напомните постоянным клиентам о свободных окнах или предложите разовую акцию.');
        }
        if (d.cancel_rate_30d != null && d.cancel_rate_30d >= 14) {
          tips.push('Доля отмен за 30 дней заметна — зафиксируйте правила отмены в переписке и в описании услуги.');
        }
        if ((d.free_slots_week || 0) >= 4 && (d.week_upcoming || 0) <= 2 && wst >= 5) {
          tips.push('Много свободных слотов при малом числе предстоящих занятий — хороший повод для поста или рассылки в Telegram.');
        }
        if ((d.client_requests_to_trainer_30d || 0) > 0 &&
            (d.client_request_responses_30d || 0) < (d.client_requests_to_trainer_30d || 0)) {
          tips.push('Есть входящие заявки — откройте раздел заявок и ответьте, чтобы не потерять лиды.');
        }
        if (d.lead_response_rate_30d != null && d.lead_response_rate_30d < 70 && (d.client_requests_to_trainer_30d || 0) >= 2) {
          tips.push('Не все заявки получили ответ — быстрый отклик повышает шанс записаться.');
        }
        if (d.repeat_share_30d_pct != null && d.repeat_share_30d_pct < 30 && (d.unique_clients_30d || 0) >= 4) {
          tips.push('Низкая доля повторных клиентов — напомните о следующем визите в конце занятия.');
        }
        if ((d.new_clients_30d || 0) > 0 && (d.repeat_clients_30d || 0) < Math.max(1, Math.floor((d.new_clients_30d || 0) / 2))) {
          tips.push('Много новых клиентов — предложите абонемент или пакет занятий, чтобы закрепить их в практике.');
        }
        if (d.rating_avg != null && d.rating_avg >= 4.6 && (d.rating_count || 0) >= 3) {
          tips.push('Сильный рейтинг — попросите довольных клиентов оставить отзыв в каталоге.');
        }
        return tips.slice(0, 5);
      }

      function renderCoachCard(d, maxTips) {
        maxTips = maxTips != null ? maxTips : 3;
        var tips = buildCoachTips(d).slice(0, maxTips);
        if (!tips.length) return '';
        var html = '<div class="coach-card"><div class="coach-card-title">Советы по вашим цифрам</div><ul class="coach-list">';
        tips.forEach(function(t) { html += '<li>' + t + '</li>'; });
        html += '</ul></div>';
        return html;
      }

      /** Single scroll: overview + former «Динамика», deduplicated (no redundant month/week insights). */
      function renderDashboard(d, weekLabel) {
        var html = '';
        html += '<div class="stat-chips">';
        html += '<div class="stat-chip"><div class="stat-chip-value">' + (d.bookings_today != null ? d.bookings_today : 0) + '</div><div class="stat-chip-label">Сегодня</div></div>';
        html += '<div class="stat-chip"><div class="stat-chip-value">' + (d.avg_check_cents_30d != null ? formatMoney(d.avg_check_cents_30d) : '—') + '</div><div class="stat-chip-label">Средний чек · 30 дн.</div></div>';
        html += '<div class="stat-chip"><div class="stat-chip-value">' + (d.repeat_clients_30d != null ? d.repeat_clients_30d : 0) + '</div><div class="stat-chip-label">Повторных · 30 дн.</div></div>';
        if (d.repeat_share_30d_pct != null) {
          html += '<div class="stat-chip"><div class="stat-chip-value">' + d.repeat_share_30d_pct + '%</div><div class="stat-chip-label">Повторы от аудитории</div></div>';
        } else {
          html += '<div class="stat-chip"><div class="stat-chip-value">' + (d.unique_clients_30d != null ? d.unique_clients_30d : 0) + '</div><div class="stat-chip-label">Уникальных · 30 дн.</div></div>';
        }
        html += '</div>';

        html += '<div class="kpi-top-grid">';
        html += '<div class="kpi-top-card">';
        html += '<div class="kpi-top-label">Неделя</div>';
        html += '<div class="kpi-top-value-row"><div class="kpi-top-value">' + (d.week_total || 0) + '</div>' + renderTrend(d.week_change_pct) + '</div>';
        html += '<div class="kpi-top-sub">' + weekLabel + '</div>';
        html += '<div class="kpi-top-sub">Проведено ' + (d.week_completed || 0) + ' · впереди ' + (d.week_upcoming || 0) + '</div>';
        html += '</div>';
        html += '<div class="kpi-top-card">';
        html += '<div class="kpi-top-label">Месяц</div>';
        html += '<div class="kpi-top-value-row"><div class="kpi-top-value">' + (d.month_total || 0) + '</div>' + renderTrend(d.month_change_pct) + '</div>';
        html += '<div class="kpi-top-sub">Уникальных в месяце: ' + (d.unique_clients_month || 0);
        if (d.unique_clients_30d != null) {
          html += ' · за 30 дн.: ' + d.unique_clients_30d;
        }
        html += '</div>';
        html += '</div></div>';

        html += '<div class="section"><div class="section-title">Лиды CRM · 30 дней</div><div class="card">';
        html += '<div class="leads-row">';
        html += '<div class="kpi-card" style="margin:0;"><div class="kpi-label">Заявок вам</div><div class="kpi-value">' + (d.client_requests_to_trainer_30d != null ? d.client_requests_to_trainer_30d : 0) + '</div><div class="kpi-sub">Адресно тренеру</div></div>';
        html += '<div class="kpi-card" style="margin:0;"><div class="kpi-label">Откликов</div><div class="kpi-value">' + (d.client_request_responses_30d != null ? d.client_request_responses_30d : 0) + '</div><div class="kpi-sub">Вы ответили</div></div>';
        html += '</div>';
        if ((d.client_requests_to_trainer_30d || 0) > 0 && d.lead_response_rate_30d != null) {
          html += '<div style="margin-top:14px;text-align:center;"><span class="lead-rate-badge">' + d.lead_response_rate_30d + '% ответов</span>';
          html += '<p class="kpi-sub" style="margin-top:10px;">Доля заявок, по которым был отправлен ответ в CRM</p></div>';
        }
        html += '</div></div>';

        html += '<div class="section"><div class="section-title">Неделя по дням</div><div class="card">';
        var dayRows = d.bookings_by_day || [];
        var maxDay = 0;
        dayRows.forEach(function(day) { maxDay = Math.max(maxDay, day.count || 0); });
        if (!dayRows.length || maxDay === 0) {
          html += '<div class="empty-chart-msg">Пока нет записей на эту неделю — график заполнится, когда появятся бронирования.</div>';
        } else {
          html += '<div class="chart-bars">';
          dayRows.forEach(function(day) {
            var pct = Math.max(day.pct || 0, 5);
            html += '<div class="chart-bar-wrap">';
            html += '<div class="chart-bar" style="height:' + pct + '%"></div>';
            html += '<div class="chart-bar-label">' + (day.day_label || '') + '</div>';
            html += '<div class="chart-bar-value">' + (day.count || 0) + '</div>';
            html += '</div>';
          });
          html += '</div>';
        }
        html += '</div></div>';

        var trendMax = d.trend_max || 1;
        html += '<div class="section"><div class="section-title">6 недель · занятия</div><div class="card">';
        html += '<div class="trend-bars">';
        (d.weekly_trend || []).forEach(function(w, i) {
          var isLast = i === (d.weekly_trend.length - 1);
          var h = trendMax > 0 ? Math.max(10, (w.count / trendMax) * 100) : 10;
          html += '<div class="trend-bar-wrap">';
          html += '<div class="trend-bar' + (isLast ? ' active' : '') + '" style="height:' + h + '%"></div>';
          html += '<div class="trend-bar-label">' + (w.week_label || '') + '</div>';
          html += '</div>';
        });
        html += '</div><p class="kpi-sub" style="margin-top:12px;text-align:center;">Последний столбец — текущая неделя</p></div></div>';

        var loadPct = d.load_pct != null ? d.load_pct : 0;
        html += '<div class="section"><div class="section-title">Загрузка слотов</div><div class="card">';
        html += '<div class="load-block">';
        html += '<div class="load-ring" style="--pct:' + loadPct + '"><div class="load-ring-inner">' + (d.load_pct != null ? loadPct + '%' : '—') + '</div></div>';
        html += '<div class="load-copy">';
        html += '<div class="kpi-label" style="margin-bottom:4px;">Эта неделя</div>';
        html += '<div class="kpi-value" style="font-size:18px;">' + (d.week_slots_booked || 0) + ' из ' + (d.week_slots_total || 0) + '</div>';
        html += '<div class="kpi-sub">Свободно слотов: <strong>' + (d.free_slots_week != null ? d.free_slots_week : '—') + '</strong></div>';
        html += '</div></div></div></div>';

        html += '<div class="section"><div class="section-title">Итоги · 30 дней</div><div class="kpi-grid">';
        html += '<div class="kpi-card"><div class="kpi-label">Новые клиенты</div><div class="kpi-value">' + (d.new_clients_30d || 0) + '</div><div class="kpi-sub">Первый визит</div></div>';
        html += '<div class="kpi-card"><div class="kpi-label">Проведено занятий</div><div class="kpi-value">' + (d.bookings_held_30d != null ? d.bookings_held_30d : 0) + '</div><div class="kpi-sub">Без отмен</div></div>';
        html += '<div class="kpi-card"><div class="kpi-label">Списаний абонемента</div><div class="kpi-value">' + (d.pass_redemptions_30d != null ? d.pass_redemptions_30d : 0) + '</div><div class="kpi-sub">Визиты по абонементу</div></div>';
        html += '<div class="kpi-card"><div class="kpi-label">Отмены</div><div class="kpi-value">' + (d.cancellations_7d != null ? d.cancellations_7d : '0') + '</div><div class="kpi-sub">7 дн. · ' + (d.cancellations_30d != null ? d.cancellations_30d : 0) + ' за 30 дн.</div></div>';
        html += '<div class="kpi-card"><div class="kpi-label">Доля отмен · 30 дн.</div><div class="kpi-value">' + (d.cancel_rate_30d != null ? d.cancel_rate_30d + '%' : '—') + '</div>';
        html += '<div class="cancel-strip" aria-hidden="true"><div class="cancel-strip-fill" style="width:' + (d.cancel_rate_30d != null ? Math.min(100, d.cancel_rate_30d) : 0) + '%"></div></div>';
        html += '<div class="kpi-sub">От всех исходов записи</div></div>';
        html += '<div class="kpi-card"><div class="kpi-label">Рейтинг</div><div class="kpi-value rating">' + renderStars(d.rating_avg) + '</div><div class="kpi-sub">' + (d.rating_count || 0) + ' отзывов</div></div>';
        html += '</div></div>';

        html += renderCoachCard(d, 3);

        if (d.busiest_weekday) {
          var busiestDisplay = d.busiest_date ? (formatDateShort(d.busiest_date) + ' · ' + d.busiest_weekday) : d.busiest_weekday;
          html += '<div class="section"><div class="section-title">Пик спроса за месяц</div>';
          html += '<div class="insight"><span class="insight-icon">📈</span><span class="insight-text">Чаще всего — <strong>' + busiestDisplay + '</strong></span></div></div>';
        }

        return html;
      }

      function moneySplitWidths(s, p, c) {
        var t = (s || 0) + (p || 0) + (c || 0);
        if (t <= 0) return [34, 33, 33];
        return [
          Math.round(10000 * (s || 0) / t) / 100,
          Math.round(10000 * (p || 0) / t) / 100,
          Math.round(10000 * (c || 0) / t) / 100,
        ];
      }
      function streamBarPct(part, total) {
        if (!total || total <= 0) return 0;
        if (!part || part <= 0) return 0;
        return Math.max(5, Math.round((100 * part) / total));
      }

      function localTodayISO() {
        var n = new Date();
        return n.getFullYear() + '-' + String(n.getMonth() + 1).padStart(2, '0') + '-' + String(n.getDate()).padStart(2, '0');
      }
      function addDaysISO(iso, deltaDays) {
        var p = iso.split('-').map(Number);
        var dt = new Date(p[0], p[1] - 1, p[2]);
        dt.setDate(dt.getDate() + deltaDays);
        return dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + String(dt.getDate()).padStart(2, '0');
      }
      function addMonthsISO(iso, deltaM) {
        var p = iso.split('-').map(Number);
        var dt = new Date(p[0], p[1] - 1, p[2]);
        var day = dt.getDate();
        dt.setMonth(dt.getMonth() + deltaM);
        if (dt.getDate() !== day) dt.setDate(0);
        return dt.getFullYear() + '-' + String(dt.getMonth() + 1).padStart(2, '0') + '-' + String(dt.getDate()).padStart(2, '0');
      }
      function monthEndFromStartISO(monthStartIso) {
        var p = monthStartIso.split('-').map(Number);
        var last = new Date(p[0], p[1], 0).getDate();
        return p[0] + '-' + String(p[1]).padStart(2, '0') + '-' + String(last).padStart(2, '0');
      }
      function minISO(a, b) {
        return a <= b ? a : b;
      }
      function formatRangeHuman(fromIso, toIso) {
        if (!fromIso || !toIso) return '—';
        var a = fromIso.split('-');
        var b = toIso.split('-');
        if (a.length < 3 || b.length < 3) return fromIso + ' — ' + toIso;
        if (fromIso === toIso) return a[2] + '.' + a[1] + '.' + a[0];
        return a[2] + '.' + a[1] + '.' + a[0] + ' — ' + b[2] + '.' + b[1] + '.' + b[0];
      }
      function buildMoneyDynamicInner(payload) {
        var rs = payload.revenue_sessions_cents != null ? payload.revenue_sessions_cents : 0;
        var rp = payload.revenue_pass_sales_cents != null ? payload.revenue_pass_sales_cents : 0;
        var rc = payload.revenue_certificate_sales_cents != null ? payload.revenue_certificate_sales_cents : 0;
        var total = payload.revenue_total_cents != null ? payload.revenue_total_cents : (rs + rp + rc);
        var w = moneySplitWidths(rs, rp, rc);
        var paid = payload.paid_sessions_count != null ? payload.paid_sessions_count : 0;
        var avg = payload.avg_check_cents;
        var kicker = payload.kicker || 'Выбранный период';
        var rangeLine = payload.rangeLabel || '';
        var sub = payload.subLine || 'Разовые оплаты, абонементы и сертификаты — по правилам начисления в CRM';
        var totalBar = rs + rp + rc;
        var h = '';
        h += '<div class="money-hero"><div class="money-hero-inner">';
        h += '<p class="money-hero-kicker">' + kicker + '</p>';
        h += '<div class="money-hero-value">' + formatMoney(total) + '</div>';
        h += '<p class="money-hero-sub">' + rangeLine + '</p>';
        h += '<p class="money-hero-sub money-hero-sub--dim">' + sub + '</p>';
        h += '</div></div>';
        h += '<h2 class="money-section-title">Структура дохода</h2>';
        h += '<div class="money-card">';
        h += '<div class="money-split-track" role="img" aria-label="Доля выручки по потокам">';
        h += '<div class="money-split-seg money-split-seg--sessions" style="width:' + w[0] + '%"></div>';
        h += '<div class="money-split-seg money-split-seg--pass" style="width:' + w[1] + '%"></div>';
        h += '<div class="money-split-seg money-split-seg--cert" style="width:' + w[2] + '%"></div>';
        h += '</div>';
        h += '<ul class="money-legend">';
        h += '<li><span class="lbl"><span class="dot dot--sessions"></span>Разовые занятия</span><span class="amt">' + formatMoney(rs) + '</span></li>';
        h += '<li><span class="lbl"><span class="dot dot--pass"></span>Абонементы</span><span class="amt">' + formatMoney(rp) + '</span></li>';
        h += '<li><span class="lbl"><span class="dot dot--cert"></span>Сертификаты</span><span class="amt">' + formatMoney(rc) + '</span></li>';
        h += '</ul></div>';
        h += '<h2 class="money-section-title">Сводка</h2>';
        h += '<div class="money-kpi-row">';
        h += '<div class="money-kpi-tile"><div class="money-kpi-tile-label">Всего за период</div><div class="money-kpi-tile-value">' + formatMoney(total) + '</div></div>';
        h += '<div class="money-kpi-tile"><div class="money-kpi-tile-label">Средний чек · разовые</div><div class="money-kpi-tile-value">' + (avg != null ? formatMoney(avg) : '—') + '</div></div>';
        h += '<div class="money-kpi-tile"><div class="money-kpi-tile-label">Разовых оплат</div><div class="money-kpi-tile-value">' + paid + '</div></div>';
        h += '</div>';
        h += '<h2 class="money-section-title">Потоки</h2>';
        h += '<div class="money-card">';
        [
          { label: 'Занятия', cents: rs, pct: streamBarPct(rs, totalBar) },
          { label: 'Абонементы', cents: rp, pct: streamBarPct(rp, totalBar) },
          { label: 'Сертификаты', cents: rc, pct: streamBarPct(rc, totalBar) },
        ].forEach(function(row) {
          h += '<div class="money-stream-row">';
          h += '<span class="money-stream-label">' + row.label + '</span>';
          h += '<span class="money-stream-val">' + formatMoney(row.cents) + '</span>';
          h += '<div class="money-stream-bar"><i style="width:' + row.pct + '%"></i></div>';
          h += '</div>';
        });
        h += '</div>';
        return h;
      }

      function renderMoney(d) {
        var html = '';
        var rs30 = d.revenue_sessions_30d_cents != null ? d.revenue_sessions_30d_cents : 0;
        var rp30 = d.revenue_pass_sales_30d_cents != null ? d.revenue_pass_sales_30d_cents : 0;
        var rc30 = d.revenue_certificate_sales_30d_cents != null ? d.revenue_certificate_sales_30d_cents : 0;
        var today = localTodayISO();
        var rollFrom = addDaysISO(today, -30);
        var initialInner = buildMoneyDynamicInner({
          kicker: 'Выручка · выбранный период',
          rangeLabel: formatRangeHuman(rollFrom, today) + ' · как скользящие 30 дней',
          subLine: 'Меняйте период ниже — цифры обновятся с сервера',
          revenue_total_cents: d.revenue_30d_cents,
          revenue_sessions_cents: rs30,
          revenue_pass_sales_cents: rp30,
          revenue_certificate_sales_cents: rc30,
          paid_sessions_count: d.paid_sessions_30d,
          avg_check_cents: d.avg_check_cents_30d,
        });

        html += '<div class="money-tab-root">';
        html += '<div class="money-panel">';

        html += '<div id="money-period-root" class="money-period-explorer" data-preset="r30">';
        html += '<h2 class="money-section-title">Период</h2>';
        html += '<p class="money-period-err" id="moneyPeriodErr" hidden></p>';
        html += '<div class="money-period-scroll" role="toolbar" aria-label="Быстрый период">';
        html += '<button type="button" class="money-period-chip" data-preset="d1">Сегодня</button>';
        html += '<button type="button" class="money-period-chip" data-preset="d5">5 дн</button>';
        html += '<button type="button" class="money-period-chip is-active" data-preset="r30">30 дн</button>';
        html += '<button type="button" class="money-period-chip" data-preset="d7">7 дн</button>';
        html += '<button type="button" class="money-period-chip" data-preset="d14">14 дн</button>';
        html += '<button type="button" class="money-period-chip" data-preset="w5">5 нед</button>';
        html += '<button type="button" class="money-period-chip" data-preset="w7">7 нед</button>';
        html += '<button type="button" class="money-period-chip" data-preset="m5">5 мес</button>';
        html += '<button type="button" class="money-period-chip" data-preset="cm">Этот месяц</button>';
        html += '</div>';
        html += '<div class="money-period-composer money-period-composer--idle" id="moneyComposerBlock">';
        html += '<div><div class="money-period-composer-label">Последние</div>';
        html += '<div class="money-period-composer-row">';
        html += '<div class="money-period-stepper" id="moneyStepper">';
        html += '<button type="button" data-act="minus" aria-label="Меньше">−</button>';
        html += '<input type="number" inputmode="numeric" min="1" max="99" value="5" id="moneyStepVal" aria-label="Количество" />';
        html += '<button type="button" data-act="plus" aria-label="Больше">+</button>';
        html += '</div>';
        html += '<div class="money-period-units" id="moneyUnits" role="group" aria-label="Единица периода">';
        html += '<button type="button" data-unit="days">дни</button>';
        html += '<button type="button" data-unit="weeks">нед</button>';
        html += '<button type="button" data-unit="months">мес</button>';
        html += '</div></div></div>';
        html += '<div class="money-period-custom-wrap">';
        html += '<details id="moneyCustomDetails">';
        html += '<summary>Свой диапазон дат</summary>';
        html += '<div class="money-period-dates">';
        html += '<label>С <input type="date" id="moneyDateFrom" /></label>';
        html += '<label>По <input type="date" id="moneyDateTo" /></label>';
        html += '</div></details>';
        html += '</div></div>';
        html += '<div class="money-period-dynamic" id="moneyPeriodDynamic">' + initialInner + '</div>';
        html += '</div>';

        html += '<div class="money-month-block">';
        html += '<p class="money-month-kicker">Текущий календарный месяц</p>';
        html += '<div class="money-month-value-row">';
        html += '<span class="money-month-value">' + formatMoney(d.revenue_calendar_month_cents != null ? d.revenue_calendar_month_cents : 0) + '</span>';
        if (d.revenue_month_change_pct != null && d.revenue_month_change_pct !== 0) {
          html += renderRevenueTrend(d.revenue_month_change_pct).trim();
        }
        html += '</div>';
        html += '<p class="money-month-sub">' + formatMonthTitle(d.month_start) + ' · к прошлому месяцу: ';
        if (d.revenue_prev_calendar_month_cents != null && d.revenue_prev_calendar_month_cents > 0) {
          html += '<strong>' + formatMoney(d.revenue_prev_calendar_month_cents) + '</strong>';
        } else {
          html += 'нет данных';
        }
        html += '</p>';
        if (d.revenue_month_run_rate_cents != null && d.revenue_month_run_rate_cents > 0) {
          html += '<p class="money-month-sub">Прогноз к концу месяца при текущем темпе: <strong>' + formatMoney(d.revenue_month_run_rate_cents) + '</strong></p>';
        }
        html += '</div>';

        html += '<div class="money-week-card">';
        html += '<div class="money-week-card-main">';
        html += '<div class="money-week-card-line">Неделя <strong>пн–вс</strong>: <strong>' + formatMoney(d.revenue_week_cents != null ? d.revenue_week_cents : 0) + '</strong></div>';
        html += '<div class="money-week-card-sub">';
        if (d.revenue_prev_week_cents != null) {
          html += 'Прошлая неделя: ' + formatMoney(d.revenue_prev_week_cents);
        } else {
          html += 'Нет данных за прошлую неделю';
        }
        html += '</div></div>';
        html += '<div class="money-week-badge-wrap">';
        if (d.revenue_week_change_pct != null && d.revenue_week_change_pct !== 0) {
          html += renderRevenueTrend(d.revenue_week_change_pct).trim();
        } else {
          html += '<span class="money-week-flat">к прошлой неделе</span>';
        }
        html += '</div></div>';

        html += '</div>';

        html += '<div class="section"><div class="section-title">Абонементы и сертификаты</div><div class="kpi-grid">';
        html += '<div class="kpi-card"><div class="kpi-label">Активных абонементов</div><div class="kpi-value">' + (d.passes_active != null ? d.passes_active : 0) + '</div><div class="kpi-sub">С остатком у клиентов</div></div>';
        html += '<div class="kpi-card"><div class="kpi-label">Абонементов за 30 дн.</div><div class="kpi-value">' + (d.passes_issued_30d || 0) + '</div><div class="kpi-sub">Новых продаж</div></div>';
        html += '<div class="kpi-card"><div class="kpi-label">Сертификаты всего</div><div class="kpi-value">' + (d.certificates_issued_total || 0) + '</div><div class="kpi-sub">Выдано</div></div>';
        html += '<div class="kpi-card"><div class="kpi-label">Остаток по сертиф.</div><div class="kpi-value">' + formatMoney(d.certificate_balance_cents) + '</div><div class="kpi-sub">' + (d.certificates_with_balance || 0) + ' шт. не погашено</div></div>';
        html += '<div class="kpi-card"><div class="kpi-label">Погашено за 30 дн.</div><div class="kpi-value">' + (d.certificates_redeemed_30d || 0) + '</div><div class="kpi-sub">Сертификатов</div></div>';
        html += '</div></div>';

        html += '<div class="card money-top-clients-card">';
        html += '<div class="section-title" style="margin-top:0;">Топ клиентов · 30 дней</div>';
        var clients = d.top_clients || [];
        if (!clients.length) {
          html += '<div class="empty-finance">Пока нет занятий за период — данные появятся после тренировок.</div>';
        } else {
          html += '<div class="finance-list">';
          clients.forEach(function(c, i) {
            var name = c.name || 'Клиент';
            var phone = c.phone || '';
            var label = phone ? (name + ' · ' + phone) : name;
            var rb = rankClass(i);
            var rev = c.revenue_cents != null ? c.revenue_cents : 0;
            html += '<div class="finance-row">';
            html += '<span class="client-cell"><span class="rank-badge' + (rb ? ' ' + rb : '') + '">' + (i + 1) + '</span>' + label + '</span>';
            html += '<span class="col-money"><span class="sessions-n">' + (c.sessions || 0) + ' зан.</span>';
            html += '<span class="rev-n">' + (rev > 0 ? formatMoney(rev) : '—') + '</span></span>';
            html += '</div>';
          });
          html += '</div>';
        }
        html += '</div>';

        html += '<div class="hint-footer money-hint">';
        html += '<div class="money-hint-title">Как считается доход</div>';
        html += '<p class="money-hint-body">Оплата за раз по прайсу попадает в выручку по занятиям после того, как запись переведена в статус «завершено». Назначенные, но ещё не проведённые занятия в эту сумму не входят. Занятия по абонементу и по полностью покрывающему сертификату в день занятия не дублируются — они учтены в день продажи абонемента или сертификата. В топе — по числу завершённых занятий; сумма в колонке — только разовые оплаты по прайсу.</p>';
        html += '</div>';
        html += '</div>';
        return html;
      }

      function renderShell(d) {
        var weekLabel = formatWeekRange(d.week_start_iso || d.week_start, d.week_end_iso || d.week_end);
        var monthTitle = formatMonthTitle(d.month_start);
        var periodLine = 'Неделя <strong>' + weekLabel + '</strong> · отчётный месяц: <strong>' + monthTitle + '</strong>';
        return ''
          + '<p class="stats-period-banner">' + periodLine + '</p>'
          + '<nav class="stats-tabs" role="tablist" aria-label="Разделы аналитики">'
          +   '<button type="button" class="stats-tab-btn" role="tab" id="tab-overview" aria-selected="true" aria-controls="panel-overview" data-tab="overview">Сводка</button>'
          +   '<button type="button" class="stats-tab-btn" role="tab" id="tab-money" aria-selected="false" aria-controls="panel-money" data-tab="money">Бухгалтерия</button>'
          + '</nav>'
          + '<div class="stats-tab-panel is-active" role="tabpanel" id="panel-overview" aria-labelledby="tab-overview">' + renderDashboard(d, weekLabel) + '</div>'
          + '<div class="stats-tab-panel" role="tabpanel" id="panel-money" aria-labelledby="tab-money" hidden>' + renderMoney(d) + '</div>';
      }

      function wireTabs(root) {
        var tabs = root.querySelectorAll('.stats-tab-btn');
        var panels = root.querySelectorAll('.stats-tab-panel');
        function hapticLight() {
          if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.impactOccurred === 'function') {
            try { tg.HapticFeedback.impactOccurred('light'); } catch (e) { /* noop */ }
          }
        }
        function activate(id) {
          tabs.forEach(function(btn) {
            var on = btn.getAttribute('data-tab') === id;
            btn.setAttribute('aria-selected', on ? 'true' : 'false');
          });
          panels.forEach(function(p) {
            var on = p.id === 'panel-' + id;
            p.classList.toggle('is-active', on);
            if (on) { p.removeAttribute('hidden'); } else { p.setAttribute('hidden', ''); }
          });
          try {
            var base = location.pathname + (location.search || '');
            history.replaceState(null, '', base + (id === 'overview' ? '' : '#' + id));
          } catch (e) { /* noop */ }
        }
        tabs.forEach(function(btn) {
          btn.addEventListener('click', function() {
            hapticLight();
            activate(btn.getAttribute('data-tab'));
          });
        });
        var hash = (typeof location !== 'undefined' && location.hash) ? String(location.hash).replace(/^#/, '') : '';
        // Legacy #growth merged into main panel.
        if (hash === 'money') activate('money');
        else if (hash === 'growth' || hash === 'overview') activate('overview');
      }

      function wireMoneyPeriod(root, d) {
        var box = root.querySelector('#money-period-root');
        if (!box) return;
        var dyn = root.querySelector('#moneyPeriodDynamic');
        var errEl = root.querySelector('#moneyPeriodErr');
        var chips = box.querySelectorAll('.money-period-chip');
        var stepVal = root.querySelector('#moneyStepVal');
        var composerBlock = root.querySelector('#moneyComposerBlock');
        var unitBtns = root.querySelectorAll('#moneyUnits button');
        var dateFrom = root.querySelector('#moneyDateFrom');
        var dateTo = root.querySelector('#moneyDateTo');
        var details = root.querySelector('#moneyCustomDetails');
        var monthStart = d.month_start_iso || d.month_start;
        if (monthStart && typeof monthStart !== 'string') {
          monthStart = monthStart.toISOString ? monthStart.toISOString().slice(0, 10) : String(monthStart);
        }
        var debounceT = null;
        function hapticLight() {
          if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.impactOccurred === 'function') {
            try { tg.HapticFeedback.impactOccurred('light'); } catch (e) { /* noop */ }
          }
        }
        function showErr(msg) {
          if (!errEl) return;
          errEl.textContent = msg;
          errEl.removeAttribute('hidden');
        }
        function hideErr() {
          if (!errEl) return;
          errEl.setAttribute('hidden', '');
        }
        function setChipsActive(preset) {
          chips.forEach(function(c) {
            var on = preset != null && c.getAttribute('data-preset') === preset;
            c.classList.toggle('is-active', on);
          });
        }
        function clearComposerActive() {
          setChipsActive(null);
        }
        /** When true: чип/свой диапазон — композитор без жёлтой подсветки единиц. */
        function setComposerIdleMode(isIdle) {
          if (!composerBlock) return;
          composerBlock.classList.toggle('money-period-composer--idle', !!isIdle);
          if (isIdle) {
            unitBtns.forEach(function(b) { b.classList.remove('is-on'); });
          }
        }
        function fetchRange(f, t, meta) {
          hideErr();
          if (dyn) dyn.classList.add('is-loading');
          var path = '/api/webapp/trainer/stats/revenue-range?from=' + encodeURIComponent(f) + '&to=' + encodeURIComponent(t);
          getJsonPath(path).then(function(data) {
            if (dyn) dyn.classList.remove('is-loading');
            var label = formatRangeHuman(data.period_start, data.period_end);
            var kicker = (meta && meta.kicker) || 'Выручка за период';
            var extra = (meta && meta.extra) || '';
            if (dyn) {
              dyn.innerHTML = buildMoneyDynamicInner({
                kicker: kicker,
                rangeLabel: label + (extra ? ' · ' + extra : ''),
                subLine: 'Разовые оплаты, абонементы и сертификаты — по правилам начисления в CRM',
                revenue_total_cents: data.revenue_total_cents,
                revenue_sessions_cents: data.revenue_sessions_cents,
                revenue_pass_sales_cents: data.revenue_pass_sales_cents,
                revenue_certificate_sales_cents: data.revenue_certificate_sales_cents,
                paid_sessions_count: data.paid_sessions_count,
                avg_check_cents: data.avg_check_cents,
              });
            }
          }).catch(function(e) {
            if (dyn) dyn.classList.remove('is-loading');
            showErr('Не удалось загрузить период. Проверьте сеть и откройте экран снова.');
          });
        }
        function presetToRange(preset) {
          var today = localTodayISO();
          switch (preset) {
            case 'd1': return [today, today];
            case 'd5': return [addDaysISO(today, -4), today];
            case 'd7': return [addDaysISO(today, -6), today];
            case 'd14': return [addDaysISO(today, -13), today];
            case 'r30': return [addDaysISO(today, -30), today];
            case 'w5': return [addDaysISO(today, -34), today];
            case 'w7': return [addDaysISO(today, -48), today];
            case 'm5': return [addMonthsISO(today, -5), today];
            case 'cm':
              if (!monthStart) return [today, today];
              return [monthStart, minISO(monthEndFromStartISO(monthStart), today)];
            default: return [addDaysISO(today, -30), today];
          }
        }
        function composerRange() {
          var n = parseInt(String(stepVal && stepVal.value ? stepVal.value : '5'), 10);
          if (!n || n < 1) n = 1;
          if (n > 99) n = 99;
          var unit = 'days';
          unitBtns.forEach(function(b) {
            if (b.classList.contains('is-on')) unit = b.getAttribute('data-unit') || 'days';
          });
          var today = localTodayISO();
          var fromIso = today;
          if (unit === 'days') {
            fromIso = addDaysISO(today, -(n - 1));
          } else if (unit === 'weeks') {
            fromIso = addDaysISO(today, -(n * 7 - 1));
          } else {
            fromIso = addMonthsISO(today, -n);
          }
          return [fromIso, today];
        }
        function applyComposer() {
          if (composerBlock && composerBlock.classList.contains('money-period-composer--idle')) {
            composerBlock.classList.remove('money-period-composer--idle');
            unitBtns.forEach(function(x) { x.classList.remove('is-on'); });
            var daysBtn = root.querySelector('#moneyUnits [data-unit="days"]');
            if (daysBtn) daysBtn.classList.add('is-on');
          }
          clearComposerActive();
          box.setAttribute('data-preset', 'composer');
          var r = composerRange();
          var unit = 'days';
          unitBtns.forEach(function(b) {
            if (b.classList.contains('is-on')) unit = b.getAttribute('data-unit') || 'days';
          });
          var n = parseInt(String(stepVal && stepVal.value ? stepVal.value : '5'), 10) || 5;
          var unitRu = unit === 'weeks' ? 'нед.' : unit === 'months' ? 'мес.' : 'дн.';
          fetchRange(r[0], r[1], { kicker: 'Последние ' + n + ' ' + unitRu, extra: 'композитор периода' });
        }
        chips.forEach(function(btn) {
          btn.addEventListener('click', function() {
            hapticLight();
            var preset = btn.getAttribute('data-preset');
            setComposerIdleMode(true);
            setChipsActive(preset);
            box.setAttribute('data-preset', preset || '');
            var pr = presetToRange(preset);
            var titles = {
              d1: { kicker: 'Сегодня', extra: 'один день' },
              d5: { kicker: '5 дней', extra: 'последние пять дней' },
              d7: { kicker: '7 дней', extra: 'неделя до сегодня' },
              d14: { kicker: '14 дней', extra: 'две недели' },
              r30: { kicker: '30 дней', extra: 'как скользящие 30 дней' },
              w5: { kicker: '5 недель', extra: '35 дней' },
              w7: { kicker: '7 недель', extra: '49 дней' },
              m5: { kicker: '5 месяцев', extra: 'от сегодня назад' },
              cm: { kicker: 'Этот месяц', extra: 'календарный месяц' },
            };
            var meta = titles[preset] || { kicker: 'Период', extra: '' };
            fetchRange(pr[0], pr[1], meta);
          });
        });
        if (stepVal) {
          stepVal.addEventListener('input', function() {
            clearTimeout(debounceT);
            debounceT = setTimeout(applyComposer, 420);
          });
        }
        root.querySelectorAll('#moneyStepper button').forEach(function(b) {
          b.addEventListener('click', function() {
            hapticLight();
            var act = b.getAttribute('data-act');
            var v = parseInt(String(stepVal.value || '5'), 10) || 5;
            if (act === 'minus') v = Math.max(1, v - 1);
            else v = Math.min(99, v + 1);
            stepVal.value = String(v);
            applyComposer();
          });
        });
        unitBtns.forEach(function(b) {
          b.addEventListener('click', function() {
            hapticLight();
            if (composerBlock) composerBlock.classList.remove('money-period-composer--idle');
            unitBtns.forEach(function(x) { x.classList.remove('is-on'); });
            b.classList.add('is-on');
            applyComposer();
          });
        });
        function applyCustom() {
          if (!dateFrom || !dateTo) return;
          var f = dateFrom.value;
          var t = dateTo.value;
          if (!f || !t) return;
          if (f > t) {
            showErr('Дата «с» позже «по» — поменяйте порядок.');
            return;
          }
          hideErr();
          setComposerIdleMode(true);
          clearComposerActive();
          box.setAttribute('data-preset', 'custom');
          fetchRange(f, t, { kicker: 'Свой диапазон', extra: 'выбранные даты' });
        }
        if (dateFrom && dateTo) {
          var today = localTodayISO();
          dateTo.max = today;
          dateFrom.max = today;
          dateFrom.addEventListener('change', function() {
            dateTo.min = dateFrom.value;
            applyCustom();
          });
          dateTo.addEventListener('change', function() {
            dateFrom.max = dateTo.value;
            applyCustom();
          });
        }
        if (details) {
          details.addEventListener('toggle', function() {
            if (details.open && dateFrom && dateTo && !dateFrom.value) {
              var t = localTodayISO();
              dateFrom.value = addDaysISO(t, -30);
              dateTo.value = t;
              applyCustom();
            }
          });
        }
      }

      function renderLoadingSkeleton() {
        return '<div class="skeleton-block" style="height:52px;margin-bottom:12px;border-radius:16px;"></div>'
          + '<div class="skeleton-block" style="height:140px;margin-bottom:12px;"></div>'
          + '<div class="skeleton-block" style="height:200px;"></div>';
      }

      var contentEl = document.getElementById('content');
      contentEl.innerHTML = '<div class="loading">' + renderLoadingSkeleton() + '</div>';

      function loadStatsDashboard() {
        if (window.TrainerMiniAppGate && window.TrainerMiniAppGate.shouldBlockFeatureFetch()) return;
        getJson('/api/webapp/trainer/stats').then(function(data) {
          contentEl.innerHTML = renderShell(data);
          wireTabs(contentEl);
          wireMoneyPeriod(contentEl, data);
        }).catch(function(e) {
          var msg = (e && e.message) ? e.message : 'Ошибка сети или таймаут. Проверьте tunnel и откройте из бота снова.';
          contentEl.innerHTML = '<div class="error">' + msg + '</div>';
        });
      }

      if (initData && window.TrainerMiniAppGate) {
        window.TrainerMiniAppGate.fetchAccess(initData)
          .then(function (a) {
            if (a && !window.TrainerMiniAppGate.isActive(a)) {
              contentEl.innerHTML = '';
              window.TrainerMiniAppGate.showBlockingOverlay(a);
              return;
            }
            loadStatsDashboard();
          })
          .catch(function () {
            loadStatsDashboard();
          });
      } else {
        loadStatsDashboard();
      }
    })();
