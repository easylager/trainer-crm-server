/*
 * «Предложить место» — общая форма заявки для сайта (/suggest) и Mini App (/webapp/suggest).
 * PDEC-028, макет: холст «Предложить место», артборд «Форма заявки · телефон».
 *
 * PlaceSuggestForm.mount(root, {
 *   submit(payload) -> Promise<{id, telegram_link?}>,  // транспорт снаружи
 *   citiesUrl: '/api/public/place-suggestions/cities',
 *   askContact: true,          // сайт: шаг «Связь»; Mini App: автор известен
 *   prefillCity: {city_id, name, region, country} | null,
 *   onClose() {},              // крестик на первом шаге
 *   honeypot: true,            // сайт: скрытое поле website
 * })
 *
 * Поля ввода не перерисовываются на каждый символ: шаг рисуется один раз при входе,
 * дальше обновляются только подсказки городов, валюта и кнопка.
 */
(function () {
  'use strict';

  var KINDS = [
    { key: 'ice', title: 'Крытый каток', sub: 'арена, ледовый дворец', tone: 'ice',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5.905 5h3.418a1 1 0 0 1 .928 .629l1.143 2.856a3 3 0 0 0 2.207 1.83l4.717 .926a2.084 2.084 0 0 1 1.682 2.045v.714a1 1 0 0 1 -1 1h-13.895a1 1 0 0 1 -1 -1.1l.8 -8a1 1 0 0 1 1 -.9z"/><path d="M3 19h17a1 1 0 0 0 1 -1"/><path d="M9 15v4"/><path d="M15 15v4"/></svg>' },
    { key: 'outdoor', title: 'Открытый каток', sub: 'в парке, на стадионе', tone: 'outdoor',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v8M8.5 5l3.5 2 3.5-2M8.5 9l3.5 2 3.5-2"/><path d="M3 17.5c2.5-2 15.5-2 18 0"/><path d="M3 20.5h18"/></svg>' },
    { key: 'shop', title: 'Магазин, мастерская', sub: 'заточка, ремонт, прокат', tone: 'shop',
      icon: '<svg viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M216,40H40A16,16,0,0,0,24,56V200a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V56A16,16,0,0,0,216,40Zm0,160H40V56H216V200ZM176,88a48,48,0,0,1-96,0,8,8,0,0,1,16,0,32,32,0,0,0,64,0,8,8,0,0,1,16,0Z"/></svg>' },
    { key: 'school', title: 'Школа', sub: 'фигурное, хоккей', tone: 'school',
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 9L12 4.5 21.5 9 12 13.5z"/><path d="M6.5 11v4.5c1.6 1.6 3.4 2.3 5.5 2.3s3.9-.7 5.5-2.3V11"/><path d="M21.5 9v5"/></svg>' }
  ];
  /* «Другое» — отдельной строкой под плитками: на случай, которого мы не придумали. */
  var OTHER_KIND = { key: 'other', title: 'Другое', sub: 'что-то ещё для тех, кто катается', tone: 'other',
    icon: '<svg viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Zm48-88a8,8,0,0,1-8,8H136v32a8,8,0,0,1-16,0V136H88a8,8,0,0,1,0-16h32V88a8,8,0,0,1,16,0v32h32A8,8,0,0,1,176,128Z"/></svg>' };
  var KIND_BY_KEY = { other: OTHER_KIND };
  KINDS.forEach(function (k) { KIND_BY_KEY[k.key] = k; });

  var NAME_PH = {
    ice: 'Например: Ледовый дворец спорта',
    outdoor: 'Например: каток в парке Победы',
    shop: 'Название магазина или мастерской',
    school: 'Название школы или клуба',
    other: 'Как это называется'
  };
  var SHOP_SERVICES = [['sharpening', 'Заточка'], ['repair', 'Ремонт'], ['rental', 'Прокат'], ['sale', 'Продажа']];
  var SHOP_DISCIPLINES = [['hockey', 'Хоккей'], ['figure', 'Фигурное'], ['roller', 'Ролики']];
  var MORE_PH = {
    ice: 'Парковка, раздевалки, сезон, что угодно',
    outdoor: 'Сезон, освещение, раздевалка, что угодно',
    shop: 'Что продают: коньки, защита, одежда; бренды, цены на заточку',
    school: 'Группы, тренеры, цены, как записаться',
    other: 'Например: ледовые сборы, клуб любителей, площадка для роллеров'
  };
  var SCHOOL_DISCIPLINES = [['figure', 'Фигурное катание'], ['hockey', 'Хоккей']];

  var ICON_CLOSE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  var ICON_BACK = '<svg viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M165.66,202.34a8,8,0,0,1-11.32,11.32l-80-80a8,8,0,0,1,0-11.32l80-80a8,8,0,0,1,11.32,11.32L91.31,128Z"/></svg>';
  var ICON_SEARCH = '<svg viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M229.66,218.34l-50.07-50.06a88.11,88.11,0,1,0-11.31,11.31l50.06,50.07a8,8,0,0,0,11.32-11.32ZM40,112a72,72,0,1,1,72,72A72.08,72.08,0,0,1,40,112Z"/></svg>';
  var ICON_CHECK = '<svg viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M229.66,77.66l-128,128a8,8,0,0,1-11.32,0l-56-56a8,8,0,0,1,11.32-11.32L96,188.69,218.34,66.34a8,8,0,0,1,11.32,11.32Z"/></svg>';

  var MAX_PHOTOS = 3;
  var PHOTO_MAX_SIDE = 2000;
  var ICON_CAMERA = '<svg viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M208,56H180.28L166.65,35.56A8,8,0,0,0,160,32H96a8,8,0,0,0-6.65,3.56L75.71,56H48A24,24,0,0,0,24,80V192a24,24,0,0,0,24,24H208a24,24,0,0,0,24-24V80A24,24,0,0,0,208,56Zm8,136a8,8,0,0,1-8,8H48a8,8,0,0,1-8-8V80a8,8,0,0,1,8-8H80a8,8,0,0,0,6.66-3.56L100.28,48h55.43l13.63,20.44A8,8,0,0,0,176,72h32a8,8,0,0,1,8,8ZM128,88a44,44,0,1,0,44,44A44.05,44.05,0,0,0,128,88Zm0,72a28,28,0,1,1,28-28A28,28,0,0,1,128,160Z"/></svg>';

  /* Снимок с телефона — 5–12 МБ. Уменьшаем на устройстве: быстрее по мобильной сети,
     сервер всё равно пережмёт и сотрёт EXIF (в том числе геометку). */
  function shrinkPhoto(file) {
    if (!window.createImageBitmap || !document.createElement('canvas').toBlob) return Promise.resolve(file);
    return createImageBitmap(file, { imageOrientation: 'from-image' }).then(function (bmp) {
      var k = Math.min(1, PHOTO_MAX_SIDE / Math.max(bmp.width, bmp.height));
      var c = document.createElement('canvas');
      c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
      c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
      if (bmp.close) bmp.close();
      return new Promise(function (res) { c.toBlob(function (b) { res(b || file); }, 'image/jpeg', 0.86); });
    }).catch(function () { return file; });
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function trim(s) { return String(s == null ? '' : s).trim(); }
  var COUNTRY_NAMES = { BY: 'Беларусь', RU: 'Россия', KZ: 'Казахстан', UA: 'Украина', LT: 'Литва', LV: 'Латвия', PL: 'Польша', GE: 'Грузия', AM: 'Армения', UZ: 'Узбекистан' };
  function cityLabel(c) {
    if (c.note) return c.note;
    return [c.region, COUNTRY_NAMES[c.country] || c.country].filter(Boolean).join(', ');
  }

  function mount(root, opts) {
    opts = opts || {};
    var askContact = opts.askContact !== false;
    var total = askContact ? 4 : 3;
    var citiesUrl = opts.citiesUrl || '/api/public/place-suggestions/cities';
    var s = {
      step: 1, kind: null, city: opts.prefillCity || null, q: '',
      name: '', address: '', details: {}, services: {}, disciplines: {}, shopDisciplines: {},
      contact: '', website: '', sending: false, error: '', result: null, sugg: [], geoDone: false, geoLoading: false,
      photos: [], progress: ''
    };
    var searchTimer = null;
    var searchSeq = 0;

    root.classList.add('psf');

    function stepOk() {
      if (s.step === 1) return !!s.kind;
      if (s.step === 2) return !!(s.city && trim(s.name));
      return true;
    }
    function isLast() { return s.step === total; }
    function currency() {
      if (!s.city) return '';
      if (s.city.country === 'BY') return 'BYN';
      if (s.city.country === 'RU') return 'руб.';
      return '';
    }

    function header() {
      var bars = '';
      for (var i = 1; i <= total; i++) bars += '<span class="psf-bar' + (i <= s.step ? ' is-on' : '') + '"></span>';
      var first = s.step === 1;
      return '<div class="psf-head">' +
        '<div class="psf-head__row">' +
          '<button type="button" class="psf-iconbtn" data-act="back" aria-label="' + (first ? 'Закрыть' : 'Назад') + '">' + (first ? ICON_CLOSE : ICON_BACK) + '</button>' +
          '<span class="psf-head__step">Шаг ' + s.step + ' из ' + total + '</span>' +
          '<span class="psf-head__pad" aria-hidden="true"></span>' +
        '</div>' +
        '<div class="psf-bars" aria-hidden="true">' + bars + '</div>' +
      '</div>';
    }

    function field(id, label, value, ph, extra) {
      return '<div class="psf-field"><label class="psf-label" for="' + id + '">' + label + '</label>' +
        '<input class="psf-input" id="' + id + '" value="' + esc(value) + '" placeholder="' + esc(ph) + '"' + (extra || '') + '></div>';
    }
    function area(id, label, value, ph, rows, max) {
      return '<div class="psf-field"><label class="psf-label" for="' + id + '">' + label + '</label>' +
        '<textarea class="psf-input psf-input--area" id="' + id + '" rows="' + rows + '" maxlength="' + max + '" placeholder="' + esc(ph) + '">' + esc(value) + '</textarea></div>';
    }
    function chips(group, list, picked) {
      return '<div class="psf-chips">' + list.map(function (c) {
        var on = !!picked[c[0]];
        return '<button type="button" class="psf-chip' + (on ? ' is-on' : '') + '" data-chip="' + group + '" data-key="' + c[0] + '" aria-pressed="' + on + '">' + esc(c[1]) + '</button>';
      }).join('') + '</div>';
    }

    function bodyStep1() {
      return '<div class="psf-intro"><h1 class="psf-h1">Какое место знаете?</h1>' +
        '<p class="psf-lead">Проверим и добавим в Glide. Хватит названия и города — остальное по желанию.</p></div>' +
        '<div class="psf-tiles">' + KINDS.map(function (k) {
          var on = s.kind === k.key;
          return '<button type="button" class="psf-tile' + (on ? ' is-on' : '') + '" data-kind="' + k.key + '" aria-pressed="' + on + '">' +
            '<span class="psf-tile__icon psf-tone--' + k.tone + '">' + k.icon + '</span>' +
            '<span class="psf-tile__text"><span class="psf-tile__title">' + k.title + '</span><span class="psf-tile__sub">' + k.sub + '</span></span>' +
          '</button>';
        }).join('') + '</div>' + otherTile();
    }

    function otherTile() {
      var k = OTHER_KIND, on = s.kind === k.key;
      return '<button type="button" class="psf-tile psf-tile--row' + (on ? ' is-on' : '') + '" data-kind="' + k.key + '" aria-pressed="' + on + '">' +
        '<span class="psf-tile__icon psf-tone--' + k.tone + '">' + k.icon + '</span>' +
        '<span class="psf-tile__text"><span class="psf-tile__title">' + k.title + '</span><span class="psf-tile__sub">' + k.sub + '</span></span>' +
      '</button>';
    }

    function cityBlock() {
      if (s.city) {
        return '<div class="psf-city">' +
          '<span class="psf-city__text"><span class="psf-city__name">' + esc(s.city.name) + '</span>' +
          '<span class="psf-city__region">' + esc(cityLabel(s.city)) + '</span></span>' +
          (s.city.is_new ? '<span class="psf-tag psf-tag--new">новый город</span>' : '') +
          '<button type="button" class="psf-link" data-act="clear-city">Изменить</button></div>';
      }
      return '<div class="psf-search">' + ICON_SEARCH +
          '<input class="psf-input psf-input--search" id="psf-city" value="' + esc(s.q) + '" placeholder="Начните вводить: Уфа" maxlength="120" autocomplete="off" aria-autocomplete="list" aria-controls="psf-sugg"></div>' +
        '<div class="psf-sugg" id="psf-sugg" role="listbox" aria-label="Города"></div>' +
        '<p class="psf-hint">Нет вашего города? Ничего — добавим вместе с местом.</p>';
    }

    function bodyStep2() {
      var html = '<h1 class="psf-h1">Где это?</h1>' +
        '<div class="psf-field"><label class="psf-label"' + (s.city ? '' : ' for="psf-city"') + '>Город</label><div data-slot="city">' + cityBlock() + '</div></div>';
      html += '<div data-slot="place"' + (s.city ? '' : ' hidden') + '>' +
        field('psf-name', 'Название', s.name, NAME_PH[s.kind] || 'Название', ' maxlength="200" data-bind="name"') +
        field('psf-addr', 'Адрес <span class="psf-label__soft">— если знаете</span>', s.address, 'Улица, дом или ориентир', ' maxlength="300" data-bind="address"') +
      '</div>';
      return html;
    }

    function bodyStep3() {
      var d = s.details;
      var html = '<div class="psf-intro"><h1 class="psf-h1">Что ещё знаете?</h1>' +
        '<p class="psf-lead">Всё по желанию. Даже одна цена уже помогает.</p></div>';
      if (s.kind === 'ice' || s.kind === 'outdoor') {
        var cur = currency();
        html += '<fieldset class="psf-set"><legend class="psf-label">Цена за сеанс<span data-slot="cur">' + (cur ? ', ' + cur : '') + '</span></legend>' +
          '<div class="psf-prices">' +
            [['price_adult', 'Взрослый'], ['price_child', 'Детский'], ['price_rental', 'Прокат']].map(function (p) {
              return '<label class="psf-price"><span>' + p[1] + '</span><input class="psf-input" inputmode="decimal" maxlength="20" placeholder="—" value="' + esc(d[p[0]] || '') + '" data-detail="' + p[0] + '"></label>';
            }).join('') +
          '</div></fieldset>' +
          area('psf-hours', 'Когда можно кататься', d.hours || '', 'Например: сеансы по выходным с 12 до 14', 2, 300);
      } else if (s.kind === 'shop') {
        html += '<fieldset class="psf-set"><legend class="psf-label">Что там есть</legend>' + chips('services', SHOP_SERVICES, s.services) + '</fieldset>' +
          '<fieldset class="psf-set"><legend class="psf-label">Для чего</legend>' + chips('shopDisciplines', SHOP_DISCIPLINES, s.shopDisciplines) + '</fieldset>' +
          field('psf-hours', 'Часы работы', d.hours || '', 'Например: пн–сб 10–20', ' maxlength="300" data-detail="hours"');
      } else if (s.kind === 'school') {
        html += '<fieldset class="psf-set"><legend class="psf-label">Чему учат</legend>' + chips('disciplines', SCHOOL_DISCIPLINES, s.disciplines) + '</fieldset>' +
          field('psf-age', 'С какого возраста', d.age || '', 'Например: с 4 лет, есть взрослые группы', ' maxlength="100" data-detail="age"');
      }
      html += '<fieldset class="psf-set"><legend class="psf-label">Фото <span class="psf-label__soft">— по желанию</span></legend>' +
          '<div data-slot="photos">' + photosBlock() + '</div>' +
          '<input type="file" accept="image/*" multiple hidden data-photo-input>' +
        '</fieldset>';
      html += field('psf-link', 'Телефон, сайт или соцсеть', d.link || '', 'Номер или ссылка', ' maxlength="300" data-detail="link"') +
        area('psf-more', s.kind === 'other' ? 'Что это и чем полезно' : 'Что ещё стоит знать', d.more || '', MORE_PH[s.kind] || MORE_PH.ice, s.kind === 'other' ? 4 : 3, 1000);
      return html;
    }

    function photosBlock() {
      var cells = s.photos.map(function (ph, i) {
        return '<span class="psf-photo"><img src="' + ph.url + '" alt="Фото ' + (i + 1) + '">' +
          '<button type="button" class="psf-photo__del" data-photo-del="' + i + '" aria-label="Убрать фото ' + (i + 1) + '">' + ICON_CLOSE + '</button></span>';
      });
      if (s.photos.length < MAX_PHOTOS) {
        cells.push('<button type="button" class="psf-photo psf-photo--add" data-act="photo-add">' + ICON_CAMERA +
          '<span>' + (s.photos.length ? 'Ещё фото' : 'Добавить фото') + '</span></button>');
      }
      return '<div class="psf-photos">' + cells.join('') + '</div>' +
        '<p class="psf-hint">До ' + MAX_PHOTOS + ' снимков: вход, лёд, витрина. Покажем после проверки.</p>';
    }
    function renderPhotos() {
      var slot = root.querySelector('[data-slot="photos"]');
      if (slot) slot.innerHTML = photosBlock();
    }
    function addPhotos(files) {
      var room = MAX_PHOTOS - s.photos.length;
      Array.prototype.slice.call(files || [], 0, room).forEach(function (f) {
        if (!/^image\//.test(f.type || '')) return;
        s.photos.push({ file: f, url: URL.createObjectURL(f) });
      });
      renderPhotos();
    }

    function summary() {
      var k = KIND_BY_KEY[s.kind];
      return '<div class="psf-card"><span class="psf-card__title">' + esc(trim(s.name) || 'Без названия') + '</span>' +
        '<span class="psf-card__meta">' + esc(k ? k.title : '') + ' · ' + esc(s.city ? s.city.name : '') + '</span>' +
        (s.city && s.city.is_new ? '<span class="psf-card__note">Город ' + esc(s.city.name) + ' тоже добавим</span>' : '') +
      '</div>';
    }

    function bodyStep4() {
      return '<div class="psf-intro"><h1 class="psf-h1">Можно уточнить у вас?</h1>' +
        '<p class="psf-lead">Если что-то будет непонятно — спросим. И напишем, когда место появится в Glide.</p></div>' +
        '<div class="psf-field"><label class="psf-label" for="psf-contact">Email или Telegram</label>' +
          '<input class="psf-input" id="psf-contact" value="' + esc(s.contact) + '" placeholder="name@mail.ru или @username" maxlength="120" autocomplete="email" data-bind="contact">' +
          '<p class="psf-hint">Только для этой заявки. Без контакта тоже примем.</p></div>' +
        '<div class="psf-card psf-card--quiet"><span class="psf-card__kicker">Вы предлагаете</span>' +
          '<span class="psf-card__title">' + esc(trim(s.name) || 'Без названия') + '</span>' +
          '<span class="psf-card__meta">' + esc((KIND_BY_KEY[s.kind] || {}).title || '') + ' · ' + esc(s.city ? s.city.name : '') + '</span></div>';
    }

    function bodyDone() {
      var r = s.result || {};
      var text;
      if (!askContact && !r.telegram_link) text = 'Проверим и добавим. Когда место появится в Glide, напишем вам здесь.';
      else if (trim(s.contact) || r.telegram_link) text = 'Проверим и добавим. Когда место появится в Glide, напишем вам.';
      else text = 'Проверим и добавим — место появится на странице города.';
      return '<div class="psf-done">' +
        '<span class="psf-done__mark">' + ICON_CHECK + '</span>' +
        '<div class="psf-intro"><h1 class="psf-h1">Спасибо! Заявка у нас</h1><p class="psf-lead">' + esc(text) + '</p>' +
          (r.photosFailed ? '<p class="psf-hint">' + (r.photosFailed === 1 ? 'Одно фото не загрузилось' : 'Часть фото не загрузилась') + ' — заявка всё равно у нас.</p>' : '') + '</div>' +
        summary() +
      '</div>';
    }

    function footer() {
      if (s.step > total) {
        var r = s.result || {};
        return '<div class="psf-foot">' +
          (r.telegram_link ? '<a class="psf-btn psf-btn--tg" href="' + esc(r.telegram_link) + '" target="_blank" rel="noopener">Следить за заявкой в Telegram</a>' : '') +
          '<button type="button" class="psf-btn' + (r.telegram_link ? ' psf-btn--ghost' : '') + '" data-act="again">Предложить ещё место</button>' +
        '</div>';
      }
      var label = isLast() ? (s.sending ? (s.progress || 'Отправляем…') : 'Отправить') : 'Дальше';
      return '<div class="psf-foot">' +
        '<p class="psf-error" role="alert" data-slot="error"' + (s.error ? '' : ' hidden') + '>' + esc(s.error) + '</p>' +
        '<button type="button" class="psf-btn" data-act="next"' + (stepOk() && !s.sending ? '' : ' disabled') + '>' + label + '</button>' +
        (s.step === 3 && !isLast() ? '<button type="button" class="psf-link psf-link--center" data-act="next">Пропустить</button>' : '') +
      '</div>';
    }

    function render() {
      var body;
      if (s.step > total) body = bodyDone();
      else if (s.step === 1) body = bodyStep1();
      else if (s.step === 2) body = bodyStep2();
      else if (s.step === 3) body = bodyStep3();
      else body = bodyStep4();
      root.innerHTML = (s.step > total ? '' : header()) +
        '<div class="psf-body">' + body + '</div>' + footer() +
        (opts.honeypot ? '<input class="psf-hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true" data-bind="website">' : '');
      if (s.step === 2 && !s.city) renderSugg();
      var first = root.querySelector('.psf-h1');
      if (first) first.setAttribute('tabindex', '-1');
    }

    function refreshNext() {
      var btn = root.querySelector('[data-act="next"].psf-btn');
      if (btn) btn.disabled = !(stepOk() && !s.sending);
    }

    function renderSugg() {
      var box = root.querySelector('#psf-sugg');
      if (!box) return;
      var q = trim(s.q);
      var rows = s.sugg.map(function (c, i) {
        return '<button type="button" class="psf-sugg__row" role="option" data-sugg="' + i + '">' +
          '<span class="psf-sugg__text"><span class="psf-sugg__name">' + esc(c.name) + '</span><span class="psf-sugg__region">' + esc(cityLabel(c)) + '</span></span>' +
          '<span class="psf-tag' + (c.is_new ? ' psf-tag--new' : '') + '">' + (c.is_new ? 'новый город' : 'есть в Glide') + '</span>' +
        '</button>';
      }).join('');
      // Геокодер — только по нажатию: правила Nominatim запрещают поиск на каждый символ.
      if (q.length >= 2 && !s.geoDone) {
        rows += '<button type="button" class="psf-sugg__row psf-sugg__row--geo" data-act="geo"' + (s.geoLoading ? ' disabled' : '') + '>' +
          ICON_SEARCH + '<span class="psf-sugg__name">' + (s.geoLoading ? 'Ищем «' + esc(q) + '»…' : 'Найти «' + esc(q) + '» на карте') + '</span></button>';
      }
      box.innerHTML = rows;
      box.hidden = !rows;
    }

    function freeTextOptions(q) {
      // Геокодер не нашёл: страну человек выбирает сам — сервер требует код страны.
      return [
        { city_id: null, name: q, region: null, country: 'BY', lat: null, lon: null, is_new: true, note: 'Беларусь · уточним сами' },
        { city_id: null, name: q, region: null, country: 'RU', lat: null, lon: null, is_new: true, note: 'Россия · уточним сами' }
      ];
    }

    function fetchCities(q, geo) {
      return fetch(citiesUrl + '?q=' + encodeURIComponent(q) + (geo ? '&geo=1' : ''), { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : { items: [] }; })
        .catch(function () { return { items: [] }; })
        .then(function (data) { return (data && data.items) || []; });
    }

    function search(q) {
      var seq = ++searchSeq;
      q = trim(q);
      s.geoDone = false;
      s.geoLoading = false;
      if (!q) { s.sugg = []; renderSugg(); return; }
      fetchCities(q, false).then(function (items) {
        if (seq !== searchSeq) return;
        s.sugg = items;
        renderSugg();
      });
    }

    function searchGeo() {
      var seq = ++searchSeq;
      var q = trim(s.q);
      s.geoLoading = true;
      renderSugg();
      fetchCities(q, true).then(function (items) {
        if (seq !== searchSeq) return;
        s.geoLoading = false;
        s.geoDone = true;
        var found = items.some(function (c) { return c.is_new; });
        s.sugg = found ? items : items.concat(freeTextOptions(q));
        renderSugg();
      });
    }

    function payload() {
      var d = {};
      Object.keys(s.details).forEach(function (k) { if (trim(s.details[k])) d[k] = trim(s.details[k]); });
      if (s.kind === 'shop') {
        d.services = SHOP_SERVICES.map(function (c) { return c[0]; }).filter(function (k) { return s.services[k]; });
        d.disciplines = SHOP_DISCIPLINES.map(function (c) { return c[0]; }).filter(function (k) { return s.shopDisciplines[k]; });
      }
      if (s.kind === 'school') d.disciplines = SCHOOL_DISCIPLINES.map(function (c) { return c[0]; }).filter(function (k) { return s.disciplines[k]; });
      var body = { kind: s.kind, name: trim(s.name), address: trim(s.address) || null, details: d };
      if (s.city.city_id) body.city_id = s.city.city_id;
      else body.new_city = { name: s.city.name, country: s.city.country, region: s.city.region || null, lat: s.city.lat, lon: s.city.lon };
      if (askContact) body.contact = trim(s.contact) || null;
      if (opts.honeypot) body.website = s.website || null;
      return body;
    }

    function go(step) {
      s.step = step;
      s.error = '';
      render();
      var h = root.querySelector('.psf-h1');
      if (h) h.focus({ preventScroll: true });
      root.scrollTop = 0;
      if (typeof window.scrollTo === 'function') window.scrollTo(0, 0);
    }

    function send() {
      s.sending = true;
      s.error = '';
      render();
      Promise.resolve()
        .then(function () { return opts.submit(payload()); })
        .then(function (res) {
          s.result = res || {};
          return uploadPhotos(s.result);
        })
        .then(function () {
          s.sending = false;
          s.progress = '';
          go(total + 1);
        })
        .catch(function (err) {
          s.sending = false;
          s.error = (err && err.userMessage) || 'Не получилось отправить. Проверьте связь и попробуйте ещё раз.';
          render();
        });
    }

    function uploadPhotos(res) {
      var list = s.photos.slice();
      res.photosFailed = 0;
      if (!list.length || !res.id || !res.upload_token) { res.photosFailed = list.length && !res.upload_token ? list.length : 0; return Promise.resolve(); }
      var url = (opts.photosUrl || '/api/public/place-suggestions/{id}/photos').replace('{id}', encodeURIComponent(res.id));
      return list.reduce(function (chain, ph, i) {
        return chain.then(function () {
          s.progress = 'Загружаем фото ' + (i + 1) + ' из ' + list.length + '…';
          var btn = root.querySelector('[data-act="next"].psf-btn');
          if (btn) btn.textContent = s.progress;
          return shrinkPhoto(ph.file).then(function (blob) {
            var fd = new FormData();
            fd.append('upload_token', res.upload_token);
            fd.append('file', blob, 'photo-' + (i + 1) + '.jpg');
            return fetch(url, { method: 'POST', body: fd });
          }).then(function (r) { if (!r.ok) res.photosFailed++; })
            .catch(function () { res.photosFailed++; });
        });
      }, Promise.resolve());
    }

    function reset() {
      s.photos.forEach(function (ph) { URL.revokeObjectURL(ph.url); });
      s = {
        step: 1, kind: null, city: opts.prefillCity || null, q: '', name: '', address: '', details: {},
        services: {}, disciplines: {}, shopDisciplines: {}, contact: s.contact, website: '', sending: false, error: '', result: null, sugg: [],
        photos: [], progress: ''
      };
      go(1);
    }

    root.addEventListener('click', function (e) {
      var t = e.target.closest('button, a');
      if (!t || !root.contains(t)) return;
      if (t.dataset.kind) {
        s.kind = t.dataset.kind;
        root.querySelectorAll('.psf-tile').forEach(function (el) {
          var on = el.dataset.kind === s.kind;
          el.classList.toggle('is-on', on);
          el.setAttribute('aria-pressed', String(on));
        });
        refreshNext();
        return;
      }
      if (t.dataset.sugg != null) {
        var c = s.sugg[Number(t.dataset.sugg)];
        if (!c) return;
        s.city = { city_id: c.city_id || null, name: c.name, region: c.region || null, country: c.country, lat: c.lat, lon: c.lon, is_new: !!c.is_new, note: c.note || null };
        s.q = '';
        s.sugg = [];
        root.querySelector('[data-slot="city"]').innerHTML = cityBlock();
        root.querySelector('[data-slot="place"]').hidden = false;
        var nm = root.querySelector('#psf-name');
        if (nm) nm.focus();
        refreshNext();
        return;
      }
      if (t.dataset.chip) {
        var bag = s[t.dataset.chip];
        bag[t.dataset.key] = !bag[t.dataset.key];
        t.classList.toggle('is-on', bag[t.dataset.key]);
        t.setAttribute('aria-pressed', String(bag[t.dataset.key]));
        return;
      }
      var act = t.dataset.act;
      if (act === 'photo-add') {
        var inp = root.querySelector('[data-photo-input]');
        if (inp) inp.click();
        return;
      }
      if (t.dataset.photoDel != null) {
        var gone = s.photos.splice(Number(t.dataset.photoDel), 1)[0];
        if (gone) URL.revokeObjectURL(gone.url);
        renderPhotos();
        return;
      }
      if (act === 'back') {
        if (s.step === 1) { if (opts.onClose) opts.onClose(); }
        else go(s.step - 1);
      } else if (act === 'next') {
        if (!stepOk() || s.sending) return;
        if (isLast()) send(); else go(s.step + 1);
      } else if (act === 'geo') {
        searchGeo();
      } else if (act === 'clear-city') {
        s.city = null;
        root.querySelector('[data-slot="city"]').innerHTML = cityBlock();
        root.querySelector('[data-slot="place"]').hidden = true;
        var inp = root.querySelector('#psf-city');
        if (inp) inp.focus();
        refreshNext();
      } else if (act === 'again') {
        reset();
      }
    });

    root.addEventListener('change', function (e) {
      if (e.target.matches('[data-photo-input]')) {
        addPhotos(e.target.files);
        e.target.value = '';
      }
    });

    root.addEventListener('input', function (e) {
      var t = e.target;
      if (t.id === 'psf-city') {
        s.q = t.value;
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () { search(s.q); }, 250);
        return;
      }
      if (t.dataset.bind) { s[t.dataset.bind] = t.value; refreshNext(); return; }
      if (t.dataset.detail) { s.details[t.dataset.detail] = t.value; return; }
      if (t.id === 'psf-hours') s.details.hours = t.value;
      if (t.id === 'psf-more') s.details.more = t.value;
    });

    root.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || e.target.tagName !== 'INPUT') return;
      if (e.target.id === 'psf-city') {
        e.preventDefault();
        var firstRow = root.querySelector('.psf-sugg__row[data-sugg]') || root.querySelector('[data-act="geo"]');
        if (firstRow) firstRow.click();
        return;
      }
      e.preventDefault();
      if (stepOk()) { if (isLast()) send(); else go(s.step + 1); }
    });

    render();
    return { reset: reset };
  }

  window.PlaceSuggestForm = { mount: mount };
})();
