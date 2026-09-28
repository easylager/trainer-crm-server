/**
 * Раздел «Каталог» тренерского Mini App (TASK-140).
 *
 * До этого публикация жила тумблером в «Настройках» экрана «Профиль», а состояние собиралось из
 * двух несвязанных полей. Из каталога можно было выпасть молча: тренер стирал телефон, получал
 * `{"ok": true}` и пропадал из выдачи, а узнать мог только вернувшись на экран анкеты.
 *
 * Экран отвечает ровно на четыре вопроса: в каталоге я или нет, почему, что видит клиент и что
 * с карточкой происходило. Весь контент — из `GET /api/webapp/trainer/catalog`; тексты состояний
 * приходят с сервера, чтобы пуш, дайджест и экран не описывали одно состояние по-разному.
 *
 * Карточку заполняет существующая карусель профиля: «Разместить» уходит на
 * `trainer-profile?task=catalog&return=trainer-catalog`, у неё уже есть возврат
 * (`focusedTaskReturnUrl`). Ничего не переносим — визард остаётся там, где живут блоки формы.
 */
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    /* Тот же bootstrap темы, что у остальных тренерских экранов: без него раздел живёт на
       дефолтных цветах Telegram и на тёмной теме читается как серое на чёрном. */
    if (typeof window.__applyTrainerMiniAppTheme === 'function') window.__applyTrainerMiniAppTheme();
    if (tg.onEvent) {
      tg.onEvent('themeChanged', function () {
        if (typeof window.__applyTrainerMiniAppTheme === 'function') {
          window.__applyTrainerMiniAppTheme();
        }
      });
    }
    try {
      var darkUi = tg.colorScheme === 'dark';
      var bgHex = darkUi ? '#0B0C0E' : '#F1F3F2';
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
    } catch (e) { /* старые клиенты */ }
  }

  var initData = tg ? tg.initData : '';
  var state = { payload: null, busy: false };

  function apiUrl(path) {
    var url = '/api/webapp' + path;
    if (initData) {
      url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
    }
    return url;
  }

  function headers() {
    var h = { 'Content-Type': 'application/json' };
    if (initData) h['X-Telegram-Init-Data'] = initData;
    return h;
  }

  function el(id) {
    return document.getElementById(id);
  }

  function show(node, visible) {
    if (!node) return;
    if (visible) node.removeAttribute('hidden');
    else node.setAttribute('hidden', 'hidden');
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function formatDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
  }

  function formatDateTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return (
      d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) +
      ' ' +
      d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    );
  }

  function photoUrl(fileKey) {
    if (!fileKey) return null;
    return '/api/public/photos/' + encodeURIComponent(fileKey);
  }

  /* ─── Рендер ────────────────────────────────────────────────────────────── */

  /**
   * Карточка ровно как в клиентском списке (`catalog-main.js`): фото, имя, строка «рейтинг ·
   * стаж», строка «свободные слоты · услуга с ценой · площадки». Города здесь нет — он фильтр,
   * а не факт карточки.
   *
   * Пустые факты не рисуем вовсе: клиент не видит ни «оценок пока нет», ни «стаж не указан» —
   * пустая строка ничего не сообщает, но выглядит как заполненная.
   */
  function renderCard(node, person) {
    if (!node) return;
    var metaTop = [];
    if (person.rating_count > 0 && person.rating_avg != null) {
      metaTop.push(Number(person.rating_avg).toFixed(1) + ' ★ (' + person.rating_count + ')');
    }
    if (person.experience_years != null) {
      metaTop.push(experienceWord(person.experience_years));
    }

    var metaBottom = [];
    if (typeof person.free_slots_14d === 'number') {
      metaBottom.push('Свободных слотов: ' + person.free_slots_14d);
    }
    if (person.service_line) metaBottom.push(person.service_line);
    if (person.arena_names && person.arena_names.length) {
      metaBottom.push(person.arena_names.join(', '));
    } else if (person.arena_work_format === 'online') {
      metaBottom.push('Онлайн');
    }

    var img = photoUrl(person.photo_file_key);
    var name = [person.first_name, person.last_name].filter(Boolean).join(' ') || 'Без имени';
    node.innerHTML =
      '<div class="tc-card__photo">' +
      (img
        ? '<img src="' + esc(img) + '" alt="" loading="lazy" ' +
          'onerror="this.remove();this.parentNode.innerHTML=\'<span class=&quot;tc-card__photo-empty&quot; aria-hidden=&quot;true&quot;>👤</span>\'" />'
        : '<span class="tc-card__photo-empty" aria-hidden="true">👤</span>') +
      '</div>' +
      '<div class="tc-card__body">' +
      '<p class="tc-card__name">' + esc(name) + '</p>' +
      (metaTop.length ? '<p class="tc-card__meta">' + esc(metaTop.join(' · ')) + '</p>' : '') +
      (metaBottom.length ? '<p class="tc-card__meta">' + esc(metaBottom.join(' · ')) + '</p>' : '') +
      '</div>';
  }

  function experienceWord(years) {
    var n = Number(years);
    if (!isFinite(n) || n < 0) return '';
    var mod10 = n % 10;
    var mod100 = n % 100;
    var word = 'лет';
    if (mod10 === 1 && mod100 !== 11) word = 'год';
    else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) word = 'года';
    return 'опыт ' + n + ' ' + word;
  }

  function renderStatus(p) {
    var isDraft = p.state === 'draft';
    el('tcHeadline').textContent = p.headline || '';
    /* В draft объяснение «что такое каталог» уезжает под «Зачем это нужно»: до кнопки тренер
       читал 160 слов, из которых ни одно не отвечало на вопрос «что мне сейчас нажать».
       В остальных состояниях эта фраза и есть ответ на «почему я не в каталоге» — она видна. */
    el('tcStatusBody').textContent = isDraft ? '' : (p.body || '');
    show(el('tcStatusBody'), !isDraft && !!p.body);
    var dot = el('tcStatusDot');
    dot.className = 'tc-status__dot tc-status__dot--' + (p.state || 'draft');

    var meta = el('tcStatusMeta');
    var since = formatDate(p.state_changed_at);
    if (since && p.state === 'published') {
      meta.textContent = 'Опубликовано ' + since;
      show(meta, true);
    } else if (since && (p.state === 'hidden' || p.state === 'paused' || p.state === 'needs_revision')) {
      meta.textContent = since;
      show(meta, true);
    } else {
      show(meta, false);
    }

    /* Причина показывается дословно: в paused это единственное, что объясняет исчезновение.
       Что показывать, решает сервер — фразу служебного события он сюда не отдаёт. */
    var detail = el('tcStatusDetail');
    if (p.state_detail && p.state !== 'published') {
      detail.textContent = p.state_detail;
      show(detail, true);
    } else {
      show(detail, false);
    }

    var studio = el('tcStudioNote');
    if (p.managed_by_studio) {
      studio.textContent =
        'Публикацией карточки управляет ' + (p.studio_name || 'студия') + '. Состояние и история — здесь.';
      show(studio, true);
    } else {
      show(studio, false);
    }

    show(el('tcWhySection'), isDraft);
    el('tcWhyLead').textContent = p.body || '';
    el('tcWhySubscription').textContent = p.subscription_note || '';

    /* «Подписка не влияет» — ответ на страх «пропал, потому что не заплатил». Он возникает,
       когда карточка уже исчезла, а не когда её ещё нет: в draft фраза уезжает под раскрытие. */
    var subNote = el('tcSubscriptionNote');
    var subRelevant = p.state === 'paused' || p.state === 'hidden';
    subNote.textContent = subRelevant ? (p.subscription_note || '') : '';
    show(subNote, subRelevant && !!p.subscription_note);
  }

  function renderPreview(p) {
    renderCard(el('tcPreviewCard'), p.preview || {});
    var revision = p.revision;
    var label = el('tcPreviewLabel');
    if (revision) {
      // То, чего раньше не было видно вообще: клиент до сих пор смотрит на старые значения.
      label.textContent = 'Сейчас клиенты видят';
      renderCard(el('tcPreviewCard'), mergeForCard(p.preview, revision.current));
      renderCard(el('tcRevisionCard'), mergeForCard(p.preview, revision.next));
      show(el('tcRevisionLabel'), true);
      show(el('tcRevisionCard'), true);
      show(el('tcCancelRevision'), !!p.can_act);
    } else {
      label.textContent = p.state === 'published' ? 'Так вас видят в списке' : 'Так вас увидят в списке';
      show(el('tcRevisionLabel'), false);
      show(el('tcRevisionCard'), false);
      show(el('tcCancelRevision'), false);
    }
    /* Кнопки «Открыть как клиент» здесь нет и быть не может: клиентский Mini App проверяет
       initData токеном КЛИЕНТСКОГО бота, а это приложение живёт в тренерском — любой переход
       на `catalog` отдавал 401 и экран «Что-то пошло не так». Публичной веб-страницы тренера в
       продукте тоже нет. На вопрос «как меня видят» отвечает превью выше: оно собрано из тех же
       фактов, что и карточка клиентского списка. */
  }

  function mergeForCard(preview, version) {
    var out = {};
    Object.keys(preview || {}).forEach(function (k) { out[k] = preview[k]; });
    if (version) {
      if (version.first_name !== undefined) out.first_name = version.first_name;
      if (version.last_name !== undefined) out.last_name = version.last_name;
      if (version.photo_file_key !== undefined) out.photo_file_key = version.photo_file_key;
    }
    return out;
  }

  function renderReadiness(p) {
    var r = p.readiness || {};
    var required = r.missing_labels_ru || [];
    var optional = r.optional_missing_labels_ru || [];
    var section = el('tcReadiness');
    /* В опубликованном состоянии блок готовности не нужен: проверять нечего, а «можно усилить»
       там дублировало бы подпись под «Изменить карточку». Он для пути ДО публикации. */
    var relevant = required.length > 0 || p.state === 'draft' || p.state === 'pending_review';
    if (!relevant || (!required.length && !optional.length)) {
      show(section, false);
      show(el('tcOpenProfile'), false);
      return;
    }
    show(section, true);
    var label = el('tcReadinessLabel');
    var list = el('tcMissingList');
    list.innerHTML = '';
    if (required.length) {
      label.textContent = 'Осталось заполнить';
      required.forEach(function (text) {
        var li = document.createElement('li');
        li.className = 'tc-checklist__item tc-checklist__item--todo';
        li.textContent = text;
        list.appendChild(li);
      });
    } else {
      label.textContent = 'Готово к проверке';
      var li = document.createElement('li');
      li.className = 'tc-checklist__item tc-checklist__item--done';
      li.textContent = 'Все обязательные пункты закрыты';
      list.appendChild(li);
    }
    /* «Можно усилить» — совет, а не препятствие, и рядом со списком блокеров он читается как
       второй такой же список. Показываем его только когда блокеров не осталось: тогда это
       единственное, что ещё можно сделать, и совет попадает в момент, когда его услышат. */
    var showOptional = optional.length > 0 && required.length === 0;
    show(el('tcOptionalLabel'), showOptional);
    var optList = el('tcOptionalList');
    optList.innerHTML = '';
    if (showOptional) {
      optional.forEach(function (text) {
        var li = document.createElement('li');
        li.className = 'tc-checklist__item tc-checklist__item--soft';
        li.textContent = text;
        optList.appendChild(li);
      });
    }
    show(optList, showOptional);
    /* Ссылка в анкету рядом с любым списком полей: и с блокерами (там карусель), и с «усилить».
       Без неё экран называл поля, но не говорил, где они. */
    show(el('tcOpenProfile'), !!p.can_act && (showOptional || required.length > 0));
  }

  function renderWarnings(p) {
    var node = el('tcWarnings');
    var items = p.warnings || [];
    node.innerHTML = '';
    show(node, items.length > 0);
    items.forEach(function (w) {
      var row = document.createElement('div');
      row.className = 'tc-warning';
      row.innerHTML =
        '<span class="tc-warning__icon" aria-hidden="true">⚠</span>' +
        '<span class="tc-warning__text">' + esc(w.text) + '</span>';
      if (w.action === 'arenas' || w.action === 'profile') {
        var a = document.createElement('button');
        a.type = 'button';
        a.className = 'tc-link-btn tc-warning__action';
        a.textContent = w.action === 'arenas' ? 'Открыть площадки' : 'Дополнить';
        /* Скрытая площадка и незаполненное необязательное поле — это правка существующей
           анкеты, а не submission-пробел. Карусель `task=catalog` собралась бы пустой и
           вышвырнула тренера обратно сюда. */
        a.addEventListener('click', openProfileForm);
        row.appendChild(a);
      }
      node.appendChild(row);
    });
  }

  function renderMetrics(p) {
    var m = p.metrics;
    var section = el('tcMetrics');
    if (!m || p.state !== 'published') {
      show(section, false);
      return;
    }
    show(section, true);
    el('tcMetricsGrid').innerHTML = [
      ['Просмотры профиля', m.profile_views],
      ['Переходы в Telegram', m.contact_clicks],
      ['В избранном', m.catalog_favorites],
    ]
      .map(function (pair) {
        return (
          '<div class="tc-metric"><span class="tc-metric__val">' +
          esc(String(pair[1] == null ? 0 : pair[1])) +
          '</span><span class="tc-metric__lbl">' + esc(pair[0]) + '</span></div>'
        );
      })
      .join('');
  }

  function renderHistory(p) {
    var events = p.events || [];
    show(el('tcHistorySection'), events.length > 0);
    var list = el('tcHistoryList');
    list.innerHTML = '';
    events.forEach(function (e) {
      var li = document.createElement('li');
      li.className = 'tc-history__item';
      var when = formatDateTime(e.created_at);
      /* Автора отдельным суффиксом больше не дописываем: «На проверке · вами» читалось так,
         будто тренер проверяет сам себя. Строка журнала — это событие, и кто его совершил,
         сказано в самой фразе (event_headline_ru на сервере). */
      li.innerHTML =
        '<span class="tc-history__when">' + esc(when) + '</span>' +
        '<span class="tc-history__what">' + esc(e.headline || e.to_state) + '</span>' +
        (e.reason_detail ? '<span class="tc-history__why">' + esc(e.reason_detail) + '</span>' : '');
      list.appendChild(li);
    });
  }

  /* ─── Действия ──────────────────────────────────────────────────────────── */

  var ACTION_LABELS = {
    submit: 'Отправить на проверку',
    // Тот же эндпоинт, другая правда: карточка уже в очереди, но модератор видел прошлую версию.
    resubmit: 'Отправить обновлённую карточку',
    edit: 'Исправить в анкете',
    fill: 'Разместить карточку',
    hide: 'Снять с публикации',
    restore: 'Вернуть в каталог',
    withdraw: 'Отменить заявку',
  };

  function renderActions(p) {
    var node = el('tcActions');
    node.innerHTML = '';
    var actions = p.actions || [];
    actions.forEach(function (action) {
      var btn = document.createElement('button');
      btn.type = 'button';
      // Снятие — редкое и деструктивное: текстовой ссылкой, не кнопкой в вес «Изменить».
      var quiet = action === 'hide' || action === 'withdraw';
      /* В needs_revision первичное действие — правка: отправлять нечего, пока не исправлено.
         «Отправить снова» остаётся рядом, но тише — иначе две одинаковые кнопки снова
         превращают понятный шаг в выбор. */
      var soft = action === 'submit' && actions.indexOf('edit') !== -1;
      btn.className = quiet ? 'tc-link-btn tc-link-btn--danger' : soft ? 'btn-soft' : 'btn-primary';
      btn.textContent = ACTION_LABELS[action] || action;
      btn.addEventListener('click', function () { runAction(action); });
      node.appendChild(btn);
    });
    if (p.can_act && p.state === 'published') {
      var edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'btn-soft';
      edit.textContent = 'Изменить карточку';
      // «Изменить карточку» — правка опубликованной анкеты, пробелов там по определению нет.
      edit.addEventListener('click', openProfileForm);
      node.insertBefore(edit, node.firstChild);
      var note = document.createElement('p');
      note.className = 'tc-actions__note';
      note.textContent =
        'Имя, фото и описание проходят проверку. Цены, услуги и площадки — сразу.';
      node.appendChild(note);
    }
  }

  /** «Разместить» = карусель профиля с возвратом сюда; её рельс собирается из missing_fields. */
  function webappUrl(page) {
    var base = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
    return base + page;
  }

  /** Карусель `task=catalog`: рельс собирается из submission-пробелов, с возвратом сюда. */
  function openProfile() {
    window.location.href = webappUrl('trainer-profile') + '?task=catalog&return=trainer-catalog';
  }

  /**
   * Обычная анкета, без карусели.
   *
   * «Можно усилить» — это описание, образование и опыт, и ни одно из них не входит в
   * submission-рельс. Вести туда `task=catalog` означало открыть карусель с пустым списком
   * шагов: она мгновенно упиралась в «Базовый профиль готов» и возвращала тренера обратно в
   * «Каталог». Кнопка выглядела рабочей и не делала ничего.
   */
  function openProfileForm() {
    window.location.href = webappUrl('trainer-profile');
  }

  function runAction(action) {
    if (state.busy) return;
    if (action === 'fill') {
      openProfile();
      return;
    }
    if (action === 'edit') {
      openProfileForm();
      return;
    }
    if (action === 'hide') {
      confirmHide().then(function (ok) {
        if (ok) post('hide');
      });
      return;
    }
    if (action === 'submit' || action === 'resubmit') post('submit');
    else if (action === 'restore') post('restore');
    else if (action === 'withdraw') post('withdraw');
  }

  /** Диалог снятия: честно перечисляет, что изменится и что нет. */
  function confirmHide() {
    var text =
      'Изменится: вас не будет в списке и в фильтрах, новые заявки из каталога перестанут ' +
      'приходить.\n\nНе изменится: запись по вашей ссылке, уже назначенные занятия, клиенты и ' +
      'абонементы.\n\nВернуть можно в один тап, без повторной проверки.';
    if (typeof window.showAppConfirm === 'function') {
      return window.showAppConfirm(text, {
        title: 'Снять карточку с публикации?',
        okText: 'Снять',
        cancelText: 'Отмена',
      });
    }
    return Promise.resolve(window.confirm('Снять карточку с публикации?\n\n' + text));
  }

  function post(path) {
    state.busy = true;
    return fetch(apiUrl('/trainer/catalog/' + path), { method: 'POST', headers: headers(), body: '{}' })
      .then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
      })
      .then(function (res) {
        state.busy = false;
        if (res.ok) {
          apply(res.data);
          return;
        }
        // 422 = карточка не готова. Не ошибка, а следующий шаг: ведём в карусель.
        if (res.status === 422) {
          apply(Object.assign({}, state.payload || {}, {}));
          openProfile();
          return;
        }
        toast((res.data && res.data.detail) || 'Не удалось выполнить действие');
      })
      .catch(function () {
        state.busy = false;
        toast('Сеть недоступна — попробуйте ещё раз');
      });
  }

  function toast(message) {
    if (tg && tg.showAlert) {
      try { tg.showAlert(String(message)); return; } catch (e) { /* ignore */ }
    }
    window.alert(String(message));
  }

  /* ─── Загрузка ──────────────────────────────────────────────────────────── */

  function apply(payload) {
    state.payload = payload;
    show(el('tcLoading'), false);
    show(el('tcError'), false);
    show(el('tcRoot'), true);
    renderStatus(payload);
    renderPreview(payload);
    renderReadiness(payload);
    renderWarnings(payload);
    renderMetrics(payload);
    renderActions(payload);
    renderHistory(payload);
  }

  function load() {
    show(el('tcError'), false);
    show(el('tcLoading'), true);
    return fetch(apiUrl('/trainer/catalog'), { headers: headers(), cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(String(r.status))); })
      .then(apply)
      .catch(function () {
        show(el('tcLoading'), false);
        show(el('tcRoot'), false);
        show(el('tcError'), true);
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var why = el('tcWhyToggle');
    if (why) {
      why.addEventListener('click', function () {
        var body = el('tcWhyBody');
        var open = body.hasAttribute('hidden');
        show(body, open);
        why.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    }
    var toggle = el('tcHistoryToggle');
    if (toggle) {
      toggle.addEventListener('click', function () {
        var list = el('tcHistoryList');
        var open = list.hasAttribute('hidden');
        show(list, open);
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    }
    var retry = el('tcRetry');
    if (retry) retry.addEventListener('click', load);
    var cancel = el('tcCancelRevision');
    if (cancel) cancel.addEventListener('click', function () { post('cancel-revision'); });
    var openProfileBtn = el('tcOpenProfile');
    if (openProfileBtn) openProfileBtn.addEventListener('click', openProfileForm);
    load();
  });

  window.__trainerCatalogReload = load;
})();
