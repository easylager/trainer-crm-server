    (function() {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) {
        tg.ready();
        tg.expand();
        if (typeof window.__applyClientRequestsTheme === 'function') {
          window.__applyClientRequestsTheme();
        }
        function syncTelegramChromeColors() {
          try {
            var darkUi = tg.colorScheme === 'dark';
            var bgHex = darkUi ? '#0B0C0E' : '#F1F3F2';
            if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
            if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
            if (typeof tg.setBottomBarColor === 'function') tg.setBottomBarColor(bgHex);
          } catch (e) { /* older clients */ }
        }
        syncTelegramChromeColors();
        if (tg.onEvent) {
          tg.onEvent('themeChanged', function () {
            if (typeof window.__applyClientRequestsTheme === 'function') {
              window.__applyClientRequestsTheme();
            }
            syncTelegramChromeColors();
          });
        }
      }

      const PER_PAGE = 10;
      let state = {
        items: [],
        total: 0,
        page: 0,
        currentRequest: null,
        selectedResponder: null,
        bookBaseUrl: ''
      };

      function initData() {
        return (tg && tg.initData) ? tg.initData : '';
      }

      function navigateToBookFromRequest(trainerId, requestId) {
        var path =
          'book?trainer_id=' +
          encodeURIComponent(String(trainerId)) +
          '&request_id=' +
          encodeURIComponent(String(requestId)) +
          '&from=requests';
        if (window.ClientShell && typeof window.ClientShell.navigate === 'function') {
          window.ClientShell.navigate(path);
          return;
        }
        var base = window.location.pathname.replace(/[^/]+$/, '');
        var url = base + path;
        var id = initData();
        if (id) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(id);
        window.location.href = url;
      }

      function apiUrl(path, useQueryInit) {
        const base = '/api/webapp';
        if (useQueryInit && initData()) {
          return base + path + '?init_data=' + encodeURIComponent(initData());
        }
        return base + path;
      }

      function headers() {
        const h = { 'Content-Type': 'application/json' };
        const id = initData();
        if (id) h['X-Telegram-Init-Data'] = id;
        return h;
      }

      function canBrowserGoBack() {
        try {
          if (window.navigation && typeof window.navigation.canGoBack === 'function') {
            return window.navigation.canGoBack();
          }
        } catch (e) {}
        return window.history && window.history.length > 1;
      }

      function syncClientRequestsHeaderBack() {
        var btn = document.getElementById('btnBack');
        if (!btn) return;
        var id = document.querySelector('[data-screen].active');
        id = id ? id.id : 'screenList';
        if (id === 'screenList') {
          btn.hidden = !canBrowserGoBack();
          btn.onclick = function() { window.history.back(); };
          return;
        }
        btn.hidden = false;
        if (id === 'screenDetail') {
          btn.onclick = function() {
            state.currentRequest = null;
            renderList();
            showScreen('screenList');
          };
        } else if (id === 'screenResponderDetail') {
          btn.onclick = function() {
            state.selectedResponder = null;
            if (state.currentRequest) renderDetail();
            showScreen('screenDetail');
          };
        } else if (id === 'screenEdit') {
          btn.onclick = function() { showScreen('screenDetail'); };
        }
      }

      function showScreen(id) {
        document.querySelectorAll('[data-screen]').forEach(function(el) { el.classList.remove('active'); });
        const el = document.getElementById(id);
        if (el) el.classList.add('active');
        var ht = document.getElementById('crHeaderTitle');
        if (ht) {
          if (id === 'screenList') ht.textContent = 'Подбор тренера';
          else if (id === 'screenDetail') ht.textContent = 'Заявка';
          else if (id === 'screenResponderDetail') ht.textContent = 'Тренер';
          else if (id === 'screenEdit') ht.textContent = 'Редактирование';
        }
        var shell = window.ClientShell;
        if (shell && typeof shell.setTabBarVisible === 'function') {
          shell.setTabBarVisible(id === 'screenList');
        }
        if (shell && typeof shell.setForcedTab === 'function') {
          shell.setForcedTab(id === 'screenList' ? 'more' : null);
        }
        syncClientRequestsHeaderBack();
      }


      // Base URL for book Mini App (same origin)
      const path = window.location.pathname || '';
      const base = path.replace(/\/[^/]*$/, '') || '';
      state.bookBaseUrl = (window.location.origin || '') + (base ? base + '/' : '/') + 'book';

      async function fetchRequests() {
        var url = apiUrl('/client/requests', false);
        var res = await fetch(url, { headers: headers() });
        if (!res.ok) {
          const err = await res.json().catch(function() { return {}; });
          throw new Error(err.detail || res.statusText);
        }
        return res.json();
      }

      function escapeHtml(s) {
        if (s == null || s === undefined) return '';
        const t = String(s);
        return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      function ruYearsWord(n) {
        if (n == null || !isFinite(Number(n))) return 'лет';
        n = Math.floor(Math.abs(Number(n)));
        var mod100 = n % 100;
        var mod10 = n % 10;
        if (mod100 >= 11 && mod100 <= 14) return 'лет';
        if (mod10 === 1) return 'год';
        if (mod10 >= 2 && mod10 <= 4) return 'года';
        return 'лет';
      }

      function formatResponderServicePrice(s) {
        var minV = s.price_byn_min != null ? s.price_byn_min : s.price_byn;
        var maxV = s.price_byn_max != null ? s.price_byn_max : s.price_byn;
        if (minV == null && s.price_byn == null) return escapeHtml('по запросу');
        if (minV != null && maxV != null && minV !== maxV) {
          var a = minV === Math.floor(minV) ? String(minV) : minV.toFixed(2);
          return 'от ' + escapeHtml(a) + ' BYN';
        }
        var v = minV != null ? minV : s.price_byn;
        var numStr = v === Math.floor(v) ? String(v) : v.toFixed(2);
        return escapeHtml(numStr) + ' BYN';
      }

      function responderEducationTypeLabel(typeKey) {
        var key = (typeKey || '').trim();
        if (key === 'formal_education') return 'Вуз / колледж / ССО';
        if (key === 'course_or_certificate') return 'Курсы / сертификат';
        return '';
      }

      function responderEducationYearLine(edu) {
        if (!edu) return '';
        if (edu.is_in_progress) return 'в процессе';
        var sy = edu.start_year;
        var ey = edu.end_year;
        if (sy != null && ey != null) return sy + '–' + ey;
        if (ey != null) return String(ey);
        if (sy != null) return 'с ' + sy;
        return '';
      }

      function normalizeResponderEducationPhotos(edu) {
        var rows = edu && Array.isArray(edu.document_photos) ? edu.document_photos : [];
        var out = [];
        var seen = {};
        rows.forEach(function(item) {
          if (!item || typeof item !== 'object') return;
          var fk = (item.file_key || '').toString().trim();
          var fkl = (item.file_key_list || '').toString().trim();
          if (!fk || seen[fk]) return;
          seen[fk] = true;
          out.push({ file_key: fk, file_key_list: fkl ? fkl : null });
        });
        return out;
      }

      /** One-line education preview for request response cards. */
      function formatResponderEducationEntry(edu) {
        if (!edu) return '';
        var inst = (edu.institution_name || '').trim();
        var prog = (edu.program_or_title || '').trim();
        var city = (edu.city || '').trim();
        var country = (edu.country || '').trim();
        var place = [city, country].filter(Boolean).join(', ');
        var head = inst || prog || responderEducationTypeLabel(edu.education_type);
        var line = head;
        if (inst && prog && inst !== prog) line = inst + ' — ' + prog;
        var y = responderEducationYearLine(edu);
        if (line && y) line += ' (' + y + ')';
        if (!line && place) line = place;
        else if (line && place && line.indexOf(place) === -1) line += ' · ' + place;
        return (line || '').trim();
      }

      function buildResponderEducationItemHtml(edu) {
        if (!edu) return '';
        var summary = formatResponderEducationEntry(edu) || 'Запись об образовании';
        var degree = (edu.degree_level || '').trim();
        var city = (edu.city || '').trim();
        var country = (edu.country || '').trim();
        var place = [city, country].filter(Boolean).join(', ');
        var years = responderEducationYearLine(edu);
        var typeLabel = responderEducationTypeLabel(edu.education_type);
        var docs = normalizeResponderEducationPhotos(edu);

        var summaryMetaParts = [];
        if (years) summaryMetaParts.push(years);
        if (place) summaryMetaParts.push(place);
        var summaryMeta = summaryMetaParts.join(' · ');

        var body = '';
        if (typeLabel) {
          body += '<div class="tcf-education-body-line"><b>Тип:</b> ' + escapeHtml(typeLabel) + '</div>';
        }
        if (degree) {
          body += '<div class="tcf-education-body-line"><b>Квалификация:</b> ' + escapeHtml(degree) + '</div>';
        }
        if (years) {
          body += '<div class="tcf-education-body-line"><b>Период:</b> ' + escapeHtml(years) + '</div>';
        }
        if (place) {
          body += '<div class="tcf-education-body-line"><b>Город:</b> ' + escapeHtml(place) + '</div>';
        }
        if (docs.length) {
          var docsHtml = docs.slice(0, 4).map(function(doc, idx) {
            var imgSrc = photoUrl(doc.file_key_list || doc.file_key);
            var href = photoUrl(doc.file_key);
            return (
              '<a class="tcf-education-doc" href="' + href + '" target="_blank" rel="noopener noreferrer" aria-label="Документ #' + (idx + 1) + '">' +
                '<img src="' + imgSrc + '" alt="Документ #' + (idx + 1) + '" loading="lazy" decoding="async">' +
              '</a>'
            );
          }).join('');
          if (docs.length > 4) {
            docsHtml += '<span class="tcf-education-doc-more">+' + (docs.length - 4) + '</span>';
          }
          body += '<div class="tcf-education-docs">' + docsHtml + '</div>';
        }
        if (!body) {
          body = '<div class="tcf-education-body-line">Без дополнительных деталей.</div>';
        }

        return (
          '<details class="tcf-education-item">' +
            '<summary>' +
              '<div class="tcf-education-summary-main">' +
                '<div class="tcf-education-summary-title">' + escapeHtml(summary) + '</div>' +
                (summaryMeta ? '<div class="tcf-education-summary-meta">' + escapeHtml(summaryMeta) + '</div>' : '') +
              '</div>' +
              '<div class="tcf-education-summary-right">' +
                (docs.length ? '<span class="tcf-education-badge">' + docs.length + ' фото</span>' : '') +
                '<span class="tcf-education-chevron">▾</span>' +
              '</div>' +
            '</summary>' +
            '<div class="tcf-education-body">' + body + '</div>' +
          '</details>'
        );
      }

      function isResponderEducationCategoryOnly(s) {
        if (!s || typeof s !== 'string') return false;
        var t = s.trim();
        var cats = [
          'Среднее специальное', 'Высшее профильное', 'Высшее непрофильное',
          'Курсы и сертификация', 'Ученая степень', 'Другое'
        ];
        return cats.indexOf(t) >= 0;
      }

      /** Arenas: primary + secondaries + hint — aligned with catalog.html `buildTrainerArenasBlock`. */
      function buildResponderArenasBlock(r) {
        var ids = Array.isArray(r.arena_ids) ? r.arena_ids : [];
        var names = Array.isArray(r.arena_names) ? r.arena_names : [];
        var n = ids.length;
        if (n === 0 && names.length) {
          n = names.length;
          ids = names.map(function(_, i) { return i; });
        }
        if (n <= 1) {
          var single = (names[0] && String(names[0]).trim()) ? String(names[0]).trim() : '—';
          return '<div class="trainer-detail-stat-value">' + escapeHtml(single) + '</div>';
        }
        var primaryId = r.primary_arena_id;
        var primaryIdx = 0;
        if (primaryId != null) {
          var pi = ids.indexOf(primaryId);
          if (pi >= 0) primaryIdx = pi;
        }
        var primaryName = (names[primaryIdx] || '—').trim();
        var others = [];
        for (var i = 0; i < n; i++) {
          if (i === primaryIdx) continue;
          others.push((names[i] || '—').trim());
        }
        var html = '<div class="trainer-detail-arena-stack">';
        html += '<div class="trainer-detail-arena-primary-row">';
        html += '<span class="trainer-detail-arena-primary-name">' + escapeHtml(primaryName) + '</span>';
        html += '<span class="trainer-detail-arena-pill">основная</span>';
        html += '</div>';
        if (others.length) {
          html += '<div class="trainer-detail-arena-others">';
          others.forEach(function(nm) {
            html += '<div class="trainer-detail-arena-secondary">' + escapeHtml(nm) + '</div>';
          });
          html += '</div>';
        }
        html += '<p class="trainer-detail-arena-hint">Запись в каталоге — на основную площадку. Нужна другая? Оставьте заявку — тренер согласует.</p>';
        html += '</div>';
        return html;
      }

      function photoUrl(fileKey) {
        if (!fileKey) return '';
        return '/api/public/photos/' + encodeURIComponent(fileKey);
      }

      function formatRequestLabel(req) {
        const city = (req.city_name || '').trim() || '—';
        const service = (req.service_name || '').trim() || '—';
        var base = city + ', ' + service;
        if (req.is_personalized) {
          var tname = (req.trainer_name || '').trim();
          return tname ? ('Персональная · ' + tname) : ('Персональная · ' + base);
        }
        return base;
      }

      function formatRequestCreatedAt(iso) {
        if (!iso) return '';
        try {
          var d = new Date(iso);
          if (isNaN(d.getTime())) return '';
          return 'Создана ' + d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
        } catch (e) { return ''; }
      }

      /** Сколько тренеров ответили — без слова «отклик». */
      function formatTrainerAnswersLine(count) {
        if (count === 0) return 'Пока нет ответов от тренеров';
        var n = count % 100;
        var last = n % 10;
        if (n >= 11 && n <= 14) return count + ' тренеров ответили';
        if (last === 1) return count + ' тренер ответил';
        if (last >= 2 && last <= 4) return count + ' тренера ответили';
        return count + ' тренеров ответили';
      }

      function renderList() {
        const listEl = document.getElementById('requestList');
        const emptyEl = document.getElementById('screenEmpty');
        const pagEl = document.getElementById('pagination');
        state.items = state.items || [];
        const total = state.items.length;
        var listIntro = document.getElementById('listIntro');
        if (total === 0) {
          pagEl.innerHTML = '';
          if (listIntro) listIntro.style.display = 'none';
          if (window.ClientShell && typeof window.ClientShell.renderEmptyState === 'function') {
            emptyEl.style.display = 'none';
            window.ClientShell.renderEmptyState(listEl, {
              icon: window.ClientShell.TAB_ICONS.catalog,
              title: 'Пока нет обращений',
              hint: 'Опишите задачу — подходящие тренеры смогут откликнуться и предложить занятие на льду.',
              ctaLabel: 'Найти тренера',
              ctaPath: 'catalog?tab=catalog',
            });
          } else {
            listEl.innerHTML = '';
            emptyEl.style.display = 'block';
          }
          return;
        }
        if (listIntro) listIntro.style.display = 'block';
        emptyEl.style.display = 'none';
        const start = state.page * PER_PAGE;
        const pageItems = state.items.slice(start, start + PER_PAGE);
        let html = '';
        pageItems.forEach(function(req) {
          const count = (Array.isArray(req.responses) ? req.responses : []).length;
          const sub = formatTrainerAnswersLine(count);
          html += '<button type="button" class="request-card" data-request-id="' + req.id + '">';
          html += '<div class="main"><div class="title">' + escapeHtml(formatRequestLabel(req)) + '</div>';
          html += '<div class="meta">' + escapeHtml(sub) + '</div></div>';
          html += '<span class="arrow">→</span></button>';
        });
        listEl.innerHTML = html;
        listEl.querySelectorAll('.request-card').forEach(function(btn) {
          btn.onclick = function() {
            const id = parseInt(btn.dataset.requestId, 10);
            const req = state.items.find(function(r) { return r.id === id; });
            if (req) { state.currentRequest = req; renderDetail(); showScreen('screenDetail'); }
          };
        });

        const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));
        let pagHtml = '';
        if (state.page > 0) {
          pagHtml += '<button type="button" id="pagePrev">◀ Назад</button>';
        }
        pagHtml += '<span>Стр. ' + (state.page + 1) + ' из ' + totalPages + '</span>';
        if (start + pageItems.length < total) {
          pagHtml += '<button type="button" id="pageNext">Вперёд ▶</button>';
        }
        pagEl.innerHTML = pagHtml;
        const prevBtn = document.getElementById('pagePrev');
        if (prevBtn) prevBtn.onclick = function() { state.page--; renderList(); };
        const nextBtn = document.getElementById('pageNext');
        if (nextBtn) nextBtn.onclick = function() { state.page++; renderList(); };
      }

      function renderDetail() {
        const req = state.currentRequest;
        if (!req) return;
        var titleEl = document.getElementById('detailTitleMain');
        var dateLineEl = document.getElementById('detailDateLine');
        if (titleEl) titleEl.textContent = formatRequestLabel(req);
        if (dateLineEl) {
          var meta = formatRequestCreatedAt(req.created_at);
          dateLineEl.textContent = meta || '';
          dateLineEl.style.display = meta ? 'block' : 'none';
        }
        const comment = (req.comment || '').trim();
        var cEl = document.getElementById('detailComment');
        if (cEl) {
          cEl.textContent = comment ? comment : 'Не указан';
          cEl.style.fontStyle = comment ? 'italic' : 'normal';
          cEl.style.opacity = comment ? '0.92' : '0.65';
        }
        var editBtn = document.getElementById('btnEditRequest');
        if (editBtn) {
          var canEdit = req.editable !== false;
          editBtn.hidden = !canEdit;
          editBtn.disabled = !canEdit;
        }
        // API всегда отдаёт массив; на всякий случай нормализуем (не-массив ломает forEach).
        var responses = Array.isArray(req.responses) ? req.responses : [];
        var hintEl = document.getElementById('detailTrainersHint');
        if (hintEl) {
          hintEl.textContent = responses.length === 0
            ? 'Когда тренер будет готов с вами заниматься, он появится в списке ниже. Откройте карточку и нажмите «Записаться», чтобы выбрать время.'
            : 'Нажмите на тренера. На следующем экране — «Записаться» (время в календаре) или «Написать», если нужно что-то уточнить.';
        }
        const wrap = document.getElementById('detailResponses');
        if (responses.length === 0) {
          wrap.innerHTML = '<div class="cr-responses-empty" role="status">Пока никто не ответил. Подходящие тренеры увидят вашу заявку и смогут написать.</div>';
        } else {
          let html = '';
          responses.forEach(function(r, idx) {
            const name = (r.name || 'Тренер').trim() || 'Тренер';
            const tc = (r.trainer_comment || '').trim();
            const photo = photoUrl(r.photo_key);
            const commentShort = tc ? (tc.length > 50 ? tc.slice(0, 47) + '…' : tc) : 'Откройте карточку, чтобы записаться';
            html += '<button type="button" class="responder-row" data-responder-index="' + idx + '">';
            if (photo) {
              html += '<span class="row-avatar-wrap"><span class="row-avatar-loading"></span><img src="' + escapeHtml(photo) + '" alt="" class="row-avatar" loading="lazy"></span>';
            } else {
              html += '<div class="row-avatar-placeholder">?</div>';
            }
            html += '<div class="row-main"><p class="row-name">' + escapeHtml(name) + '</p><p class="row-comment">' + escapeHtml(commentShort) + '</p></div>';
            html += '<span class="row-arrow"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg></span></button>';
          });
          wrap.innerHTML = html;
          wrap.querySelectorAll('.row-avatar-wrap .row-avatar').forEach(function(img) {
            function onLoaded() {
              img.classList.add('loaded');
              var ph = img.previousElementSibling;
              if (ph && ph.classList.contains('row-avatar-loading')) ph.style.display = 'none';
            }
            img.onload = onLoaded;
            if (img.complete) onLoaded();
          });
          wrap.querySelectorAll('.responder-row').forEach(function(btn) {
            btn.onclick = function() {
              var idx = parseInt(btn.dataset.responderIndex, 10);
              state.selectedResponder = (req.responses || [])[idx];
              if (state.selectedResponder) { renderResponderDetail(); showScreen('screenResponderDetail'); }
            };
          });
        }
      }

      function renderResponderDetail() {
        var r = state.selectedResponder;
        var req = state.currentRequest;
        if (!r || !req) return;
        var name = (r.name || 'Тренер').trim() || 'Тренер';
        var tc = (r.trainer_comment || '').trim();
        var ratingStr = (r.rating_avg != null && (r.rating_count || 0) > 0) ? (r.rating_avg.toFixed(1) + ' ★ (' + r.rating_count + ')') : null;
        var arenaIdsForLayout = Array.isArray(r.arena_ids) ? r.arena_ids : [];
        var arenaNamesForLayout = Array.isArray(r.arena_names) ? r.arena_names : [];
        var arenaStatClass = 'trainer-detail-stat';
        if (arenaIdsForLayout.length > 1 || arenaNamesForLayout.length > 1) {
          arenaStatClass += ' trainer-detail-stat--arenas';
        }
        var desc = (r.description || '').trim();
        var photo = photoUrl(r.photo_key);
        var html = '';
        html += '<div class="tcf-photo-wrap">';
        if (photo) {
          html += '<div class="tcf-photo-placeholder tcf-photo-loading"></div><img src="' + escapeHtml(photo) + '" alt="" class="tcf-photo" loading="eager">';
        } else {
          html += '<div class="tcf-photo-placeholder"></div>';
        }
        html += '</div>';
        html += '<div class="tcf-body">';
        html += '<div class="tcf-header">';
        html += '<h1 class="tcf-name">' + escapeHtml(name) + '</h1>';
        if (ratingStr) {
          html += '<div class="tcf-rating" style="cursor: pointer;" onclick="showTrainerReviews(' + r.trainer_id + ')">⭐ ' + escapeHtml(ratingStr) + '</div>';
        }
        html += '</div>';
        
        // Комментарий тренера к заявке (особенность карточки в откликах)
        if (tc) html += '<div class="tcf-comment">' + escapeHtml(tc) + '</div>';
        
        var statsParts = [];
        if (r.experience_years != null) {
          statsParts.push(
            '<div class="trainer-detail-stat">' +
              '<div class="trainer-detail-stat-label">Опыт</div>' +
              '<div class="trainer-detail-stat-value">' +
                escapeHtml(r.experience_years + ' ' + ruYearsWord(r.experience_years)) +
              '</div>' +
            '</div>'
          );
        }
        statsParts.push(
          '<div class="' + arenaStatClass + '">' +
            '<div class="trainer-detail-stat-label">Арены</div>' +
            buildResponderArenasBlock(r) +
          '</div>'
        );
        if (statsParts.length) {
          html += '<div class="trainer-detail-stats">' + statsParts.join('') + '</div>';
        }

        var servicesList = Array.isArray(r.services) ? r.services : [];
        var requestServiceId = req.service_id != null ? Number(req.service_id) : NaN;
        if (servicesList.length > 0) {
          var selectedServiceDescEscaped = '';
          if (!isNaN(requestServiceId)) {
            var sj;
            for (sj = 0; sj < servicesList.length; sj++) {
              var sx = servicesList[sj];
              if (sx.service_id == null || Number(sx.service_id) !== requestServiceId) continue;
              var rawDesc = sx.description && String(sx.description).trim();
              if (rawDesc) selectedServiceDescEscaped = escapeHtml(rawDesc).replace(/\n/g, '<br>');
              break;
            }
          }
          if (selectedServiceDescEscaped) {
            html += '<div class="trainer-detail-service-callout" role="region" aria-label="О выбранной услуге">';
            html += '<div class="trainer-detail-service-callout-kicker">К вашей заявке</div>';
            html += '<div class="trainer-detail-service-callout-body">' + selectedServiceDescEscaped + '</div>';
            html += '</div>';
          }
          html += '<div class="trainer-detail-services">';
          html += '<div class="trainer-detail-services-title">Услуги и цены</div>';
          servicesList.forEach(function(s) {
            var serviceName = s.service_name || '—';
            var priceText = formatResponderServicePrice(s);
            var sid = s.service_id != null ? Number(s.service_id) : NaN;
            var matchRequest =
              !isNaN(requestServiceId) &&
              !isNaN(sid) &&
              requestServiceId === sid;
            html += '<div class="trainer-detail-service' + (matchRequest ? ' trainer-detail-service--request-selected' : '') + '">';
            html += '<div class="trainer-detail-service-top">';
            html += '<span class="trainer-detail-service-name">' + escapeHtml(serviceName) + '</span>';
            html += '<span class="trainer-detail-service-price">' + priceText + '</span>';
            html += '</div>';
            html += '</div>';
          });
          html += '</div>';
        }
        
        // Образование: записи из API + при необходимости текст профиля (как в каталоге)
        var eduRows = Array.isArray(r.education_entries) ? r.education_entries : [];
        var eduCategory = (typeof r.education === 'string' && r.education.trim()) ? r.education.trim() : '';
        var profileExtra = eduCategory;
        if (eduRows.length > 0 && eduCategory && isResponderEducationCategoryOnly(eduCategory)) {
          profileExtra = '';
        }
        if (eduRows.length > 0) {
          html += '<div class="tcf-education">';
          html += '<div class="tcf-education-title">Образование</div>';
          html += '<p class="tcf-education-hint">Нажмите на запись, чтобы раскрыть детали и фото документов.</p>';
          var eduAnyHtml = '';
          eduRows.forEach(function(edu) {
            var itemHtml = buildResponderEducationItemHtml(edu);
            if (itemHtml) eduAnyHtml += itemHtml;
          });
          if (eduAnyHtml) {
            html += eduAnyHtml;
          } else if (eduCategory) {
            html += '<div class="tcf-education-body-line">' + escapeHtml(eduCategory) + '</div>';
          }
          if (profileExtra) {
            html += '<div class="tcf-education-more">';
            html += '<div class="tcf-education-more-label">Дополнительно</div>';
            html += '<div class="tcf-education-more-body">' + escapeHtml(profileExtra).replace(/\n/g, '<br>') + '</div>';
            html += '</div>';
          }
          html += '</div>';
        } else if (eduCategory) {
          html += '<div class="tcf-education">';
          html += '<div class="tcf-education-title">Образование</div>';
          html += '<div class="tcf-education-more">';
          html += '<div class="tcf-education-more-body">' + escapeHtml(eduCategory).replace(/\n/g, '<br>') + '</div>';
          html += '</div>';
          html += '</div>';
        }
        
        if (desc) html += '<div class="tcf-desc">' + escapeHtml(desc).replace(/\n/g, '<br>') + '</div>';
        html += '<div class="tcf-next-hint">Чтобы выбрать дату и время, нажмите <b>Записаться</b> — откроется расписание. Кнопка <b>Написать</b> — если нужно обсудить детали в чате.</div>';
        html += '<div class="tcf-actions">';
        html += '<button type="button" class="btn-primary tcf-book" data-book-trainer-id="' + encodeURIComponent(String(r.trainer_id)) + '" data-book-request-id="' + encodeURIComponent(String(req.id)) + '">Записаться</button>';
        // В Mini App tg:// не открывается; только https://t.me/username через tg.openLink
        if (r.telegram_username) {
          html += '<button type="button" class="btn-secondary tcf-write" data-tg-username="' + escapeHtml(r.telegram_username) + '">Написать</button>';
        }
        html += '</div></div>';
        document.getElementById('responderDetailContent').innerHTML = html;
        var bookBtn = document.querySelector('#responderDetailContent .tcf-book[data-book-trainer-id]');
        if (bookBtn) {
          bookBtn.addEventListener('click', function () {
            navigateToBookFromRequest(
              bookBtn.getAttribute('data-book-trainer-id'),
              bookBtn.getAttribute('data-book-request-id')
            );
          });
        }
        document.querySelectorAll('#responderDetailContent .tcf-education-doc').forEach(function(linkEl) {
          linkEl.addEventListener('click', function(ev) {
            if (tg && typeof tg.openLink === 'function') {
              ev.preventDefault();
              tg.openLink(linkEl.href);
            }
          });
        });
        var tcfImg = document.querySelector('#responderDetailContent .tcf-photo');
        if (tcfImg) {
          function onPhotoLoaded() {
            tcfImg.classList.add('loaded');
            var ph = tcfImg.previousElementSibling;
            if (ph) ph.style.display = 'none';
          }
          tcfImg.onload = onPhotoLoaded;
          if (tcfImg.complete) onPhotoLoaded();
        }
        var writeBtn = document.getElementById('responderDetailContent').querySelector('.tcf-write');
        if (writeBtn && tg && tg.openLink) {
          var un = writeBtn.getAttribute('data-tg-username');
          if (un) writeBtn.onclick = function() { tg.openLink('https://t.me/' + encodeURIComponent(un)); };
        }
      }

      document.getElementById('btnEditRequest').onclick = function() {
        const req = state.currentRequest;
        if (!req) return;
        if (req.editable === false) {
          alert('Заявки на абонемент и сертификат пока нельзя редактировать. Удалите заявку и оформите новую.');
          return;
        }
        const hasResponses = (Array.isArray(req.responses) ? req.responses : []).length > 0;
        function openEdit() {
          document.getElementById('editCityService').textContent = 'Город: ' + (req.city_name || '—') + ', Услуга: ' + (req.service_name || '—');
          document.getElementById('editComment').value = (req.comment || '').trim();
          showScreen('screenEdit');
        }
        if (hasResponses) {
          showAppConfirm(
            'Если сохранить изменения, ответы тренеров к этой заявке исчезнут — их придётся дождаться снова. Продолжить?',
            { okText: 'Продолжить', cancelText: 'Отмена' }
          ).then(function (ok) {
            if (ok) openEdit();
          });
          return;
        }
        openEdit();
      };

      document.getElementById('backFromEdit').onclick = function() {
        showScreen('screenDetail');
      };

      document.getElementById('btnSaveComment').onclick = function() {
        const req = state.currentRequest;
        if (!req) return;
        const comment = (document.getElementById('editComment').value || '').trim() || null;
        const url = apiUrl('/client/requests/' + req.id);
        fetch(url, {
          method: 'PATCH',
          headers: headers(),
          body: JSON.stringify({ comment: comment })
        }).then(function(res) { return res.json(); }).then(function(data) {
          if (data.success && data.request) {
            const idx = state.items.findIndex(function(r) { return r.id === req.id; });
            if (idx >= 0) state.items[idx] = data.request;
            state.currentRequest = data.request;
            renderDetail();
            showScreen('screenDetail');
          } else {
            alert('Не удалось сохранить. Попробуйте ещё раз.');
          }
        }).catch(function() { alert('Ошибка сети'); });
      };

      function doDelete(requestId, onSuccess) {
        const url = apiUrl('/client/requests/' + requestId);
        fetch(url, { method: 'DELETE', headers: headers() }).then(function(res) {
          if (res.ok) {
            state.items = state.items.filter(function(r) { return r.id !== requestId; });
            state.currentRequest = null;
            if (onSuccess) onSuccess();
          } else {
            alert('Не удалось удалить заявку.');
          }
        }).catch(function() { alert('Ошибка сети'); });
      }

      function runDeleteConfirm() {
        const req = state.currentRequest;
        if (!req) return;
        var run = function (ok) {
          if (!ok) return;
          doDelete(req.id, function() { renderList(); showScreen('screenList'); });
        };
        if (typeof showAppConfirm === 'function') {
          showAppConfirm('Удалить эту заявку?', { okText: 'Удалить', cancelText: 'Отмена' }).then(run);
        } else if (typeof window.confirm === 'function' && window.confirm('Удалить эту заявку?')) {
          run(true);
        }
      }

      /* Capture on screen: Telegram/iOS WebView often drops button.onclick when the tap hits SVG/path */
      (function bindDetailDeleteCapture() {
        var sd = document.getElementById('screenDetail');
        if (!sd || sd.dataset.crDeleteCapture === '1') return;
        sd.dataset.crDeleteCapture = '1';
        sd.addEventListener(
          'click',
          function (ev) {
            var t = ev.target;
            if (!t || typeof t.closest !== 'function') return;
            if (!t.closest('#btnDeleteRequest')) return;
            ev.preventDefault();
            ev.stopPropagation();
            runDeleteConfirm();
          },
          true
        );
      })();

      document.getElementById('btnDeleteRequest').onclick = function () {
        runDeleteConfirm();
      };

      document.getElementById('btnDeleteInEdit').onclick = function () {
        runDeleteConfirm();
      };

      function getRequestIdFromUrl() {
        var params = new URLSearchParams(window.location.search || '');
        var id = params.get('request_id');
        if (id == null) return null;
        var n = parseInt(id, 10);
        return isNaN(n) ? null : n;
      }

      function loadList() {
        var listEl = document.getElementById('requestList');
        var emptyEl = document.getElementById('screenEmpty');
        var openRequestId = getRequestIdFromUrl();
        if (window.ClientShell && typeof window.ClientShell.renderSkeletonList === 'function') {
          window.ClientShell.renderSkeletonList(listEl, 3);
        } else {
          listEl.innerHTML = '<div class="loading">Загрузка...</div>';
        }
        emptyEl.style.display = 'none';
        fetchRequests().then(function(data) {
          state.items = Array.isArray(data.items) ? data.items : [];
          state.page = 0;
          renderList();
          if (openRequestId != null) {
            var req = state.items.find(function(r) { return r.id === openRequestId; });
            if (req) {
              state.currentRequest = req;
              renderDetail();
              showScreen('screenDetail');
            }
          }
        }).catch(function(e) {
          listEl.innerHTML = '<div class="error">' + escapeHtml(e.message || 'Ошибка загрузки') + '</div>';
          emptyEl.style.display = 'none';
        });
      }

      document.getElementById('btnRefreshEmpty').onclick = function() {
        document.getElementById('screenEmpty').style.display = 'none';
        loadList();
      };

      loadList();
      
      // Функция для показа отзывов тренера
      window.showTrainerReviews = function(trainerId) {
        var modal = document.getElementById('reviewsModal');
        var modalBody = document.getElementById('reviewsModalBody');
        var modalTitle = document.getElementById('reviewsModalTitle');
        
        modalTitle.textContent = 'Отзывы о тренере';
        modalBody.innerHTML = '<div class="reviews-loading">Загрузка отзывов...</div>';
        modal.classList.add('show');
        
        fetch('/api/public/trainers/' + encodeURIComponent(trainerId) + '/reviews')
          .then(function(res) {
            return res.json().then(function(data) {
              if (!res.ok) throw new Error((data && data.detail) || res.statusText);
              return data;
            });
          })
          .then(function(data) {
            var reviews = data.items || [];
            if (reviews.length === 0) {
              modalBody.innerHTML = '<div class="reviews-empty">У этого тренера пока нет отзывов</div>';
              return;
            }
            
            var html = '';
            reviews.forEach(function(review) {
              html += '<div class="review-item">';
              html += '<div class="review-rating">⭐ ' + review.rating + '/5</div>';
              var text = review.review_text || review.comment;
              if (text) {
                html += '<div class="review-text">' + escapeHtml(text) + '</div>';
              }
              if (review.created_at) {
                var date = new Date(review.created_at).toLocaleDateString('ru-RU');
                html += '<div class="review-date">' + date + '</div>';
              }
              html += '</div>';
            });
            modalBody.innerHTML = html;
          })
          .catch(function() {
            modalBody.innerHTML = '<div class="reviews-empty">Не удалось загрузить отзывы</div>';
          });
      };
      
      // Закрытие модального окна
      window.closeReviewsModal = function() {
        document.getElementById('reviewsModal').classList.remove('show');
      };

      window.addEventListener('popstate', syncClientRequestsHeaderBack);
      syncClientRequestsHeaderBack();
    })();
