/**
 * TASK-148 (AC-3) → TASK-149: рынок в хабе — «Куда катимся» и приветствие из фактов.
 * Pure view-model (no DOM). Browser: window.HubCollectionsModel. Node: module.exports.
 *
 * TASK-148 завёл пресеты-фильтры («Подборки»); TASK-149 заменил отдельную секцию
 * подборок и карусель «Места и тренеры» ОДНОЙ навигацией по рынку — плитками
 * «Катки / Тренеры / Магазины». Пресеты остались как слой данных: плитка берёт у
 * них счётчик, подпись и ссылку, а не считает всё заново.
 *
 * Правила рендера (docs/plans/2026-10-03-hub-composition-05-06.md):
 *   - плитка — только при честном счётчике > 0 («нет данных — нет плитки»);
 *   - секция целиком — если есть хотя бы одна плитка; сетка не обязана быть 2×2;
 *   - порядок плиток фиксирован: катки (лёд — герой каталога), тренеры, магазины.
 *
 * Счётчики — только из данных, которые публичные запросы УЖЕ отдают:
 *   - facets        — venue_type_facets из GET /api/public/ice/arenas?intent=skate
 *                     (считаются сервером до фильтра: ice / outdoor / shop / …);
 *   - eveningHits   — window.hits из того же запроса с
 *                     when=today_evening&venue_type=ice,outdoor;
 *   - outdoorLive   — есть ли у открытых катков живой сеанс (сезонность «Открытые»);
 *   - trainersTotal — total из GET /api/public/trainers?city_id=…&limit=1: тот же
 *                     список и те же правила видимости, что у «Тренеров» во вкладке «Поиск».
 *
 * «Бесплатно», «Заточка» и «Сервис» не заводятся: у публичного API нет ни фасета по
 * цене/удобству, ни фильтра каталога, куда такая плитка могла бы вести.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.HubCollectionsModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function pluralRu(n, one, few, many) {
    var abs = Math.abs(n) % 100;
    if (abs >= 11 && abs <= 14) return many;
    var last = abs % 10;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  function facetCount(facets, key) {
    var list = facets || [];
    for (var i = 0; i < list.length; i++) {
      if (String((list[i] || {}).key) === key) {
        var n = Number(list[i].count);
        return isNaN(n) ? null : n;
      }
    }
    return null;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function catalogHref(cityId) {
    var base = 'ice?city_id=' + encodeURIComponent(String(cityId));
    return base;
  }

  /**
   * Пресеты-данные. countFrom(data) -> число или null (нет данных → пресета нет).
   * href — каталог с применённым фильтром по конвенциям диплинков
   * (docs/product-knowledge/public-place-pages.md): «Поиск» читает ?city_id=,
   * ?venue= и (TASK-149) ?when=.
   */
  var POD_DEFS = [
    {
      key: 'today_evening',
      title: 'Сегодня вечером',
      type: 'evening',
      countFrom: function (data) {
        var hits = data && data.eveningHits;
        return hits == null || isNaN(Number(hits)) ? null : Number(hits);
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'каток', 'катка', 'катков') + ' вечером';
      },
      hrefFrom: function (cityId) {
        // TASK-149: окно теперь передаётся явно — «Поиск» применяет ?when= на старте
        // и включает чип «Сегодня вечером», а не полагается на when=auto сервера.
        return catalogHref(cityId) + '&when=today_evening';
      },
    },
    {
      key: 'ice',
      title: 'Крытые',
      type: 'ice',
      countFrom: function (data) {
        return facetCount(data && data.facets, 'ice');
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'каток', 'катка', 'катков');
      },
      hrefFrom: function (cityId) {
        return catalogHref(cityId) + '&venue=ice';
      },
    },
    {
      key: 'outdoor',
      title: 'Открытые',
      type: 'outdoor',
      countFrom: function (data) {
        // Сезонность: летом у открытых катков нет живых сеансов — пресет
        // исчезает сам (план, раздел «Риски»), хотя фасет мест не пуст.
        var count = facetCount(data && data.facets, 'outdoor');
        if (count == null || count <= 0) return null;
        return data && data.outdoorLive ? count : null;
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'каток', 'катка', 'катков') + ' под небом';
      },
      hrefFrom: function (cityId) {
        return catalogHref(cityId) + '&venue=outdoor';
      },
    },
    {
      key: 'shop',
      title: 'Магазины',
      type: 'shop',
      countFrom: function (data) {
        return facetCount(data && data.facets, 'shop');
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'магазин', 'магазина', 'магазинов');
      },
      hrefFrom: function (cityId) {
        return catalogHref(cityId) + '&venue=shop';
      },
    },
  ];

  /**
   * Живые пресеты: счётчик > 0, «Сегодня вечером» первым, дальше — по счётчику
   * по убыванию, при равенстве — порядок из POD_DEFS.
   */
  function buildPods(data, cityId) {
    var pods = [];
    POD_DEFS.forEach(function (def) {
      var count = def.countFrom(data || {});
      if (count == null || isNaN(Number(count)) || Number(count) <= 0) return;
      pods.push({
        key: def.key,
        title: def.title,
        type: def.type,
        count: Number(count),
        sub: def.subFrom(Number(count)),
        href: def.hrefFrom(cityId),
      });
    });
    pods.sort(function (a, b) {
      var ae = a.key === 'today_evening' ? 0 : 1;
      var be = b.key === 'today_evening' ? 0 : 1;
      if (ae !== be) return ae - be;
      if (b.count !== a.count) return b.count - a.count;
      return POD_DEFS.findIndex(function (d) { return d.key === a.key; }) -
             POD_DEFS.findIndex(function (d) { return d.key === b.key; });
    });
    return pods;
  }

  function podByKey(pods, key) {
    for (var i = 0; i < pods.length; i++) {
      if (pods[i].key === key) return pods[i];
    }
    return null;
  }

  function positiveCount(value) {
    if (value == null || value === '') return null;
    var n = Number(value);
    return isNaN(n) || n <= 0 ? null : Math.floor(n);
  }

  /**
   * TASK-149: плитки «Куда катимся». Только то, что можно честно посчитать:
   *   - «Катки» — крытые + открытые с живым сеансом (тот же фильтр, что у «Поиска» по умолчанию);
   *     подпись «N катков вечером» и ссылка с when=today_evening — когда вечернее окно непустое;
   *   - «Тренеры» — total публичного списка в городе; без честного итога плитки нет;
   *   - «Магазины» — фасет shop.
   * Нет ни одной плитки — [] (секции нет). Нечётное число плиток: первая — на всю ширину.
   */
  function buildTiles(data, cityId) {
    data = data || {};
    var pods = buildPods(data, cityId);
    var ice = podByKey(pods, 'ice');
    var outdoor = podByKey(pods, 'outdoor');
    var evening = podByKey(pods, 'today_evening');
    var shop = podByKey(pods, 'shop');
    var tiles = [];

    var rinks = (ice ? ice.count : 0) + (outdoor ? outdoor.count : 0);
    if (rinks > 0) {
      tiles.push({
        key: 'rinks',
        type: 'ice',
        title: 'Катки',
        count: rinks,
        sub: evening ? evening.sub : (ice && outdoor ? 'крытые и открытые' : (ice ? 'крытые' : 'открытые')),
        href: evening ? evening.href : catalogHref(cityId),
      });
    }

    var trainers = positiveCount(data.trainersTotal);
    if (trainers != null) {
      tiles.push({
        key: 'trainers',
        type: 'trainer',
        title: 'Тренеры',
        count: trainers,
        sub: 'найти тренера',
        href: catalogHref(cityId) + '&intent=coach',
      });
    }

    if (shop) {
      tiles.push({
        key: 'shops',
        type: 'shop',
        title: 'Магазины',
        count: shop.count,
        sub: 'экипировка',
        href: shop.href,
      });
    }

    if (tiles.length % 2 === 1) tiles[0].wide = true;
    return tiles;
  }

  /** Секция «Куда катимся» существует, пока есть хотя бы одна плитка. */
  function tilesVisible(tiles) {
    return (tiles || []).length >= 1;
  }

  var TILE_ICONS = {
    ice: '<path d="M12 2v20M2 12h20M4.9 4.9l14.2 14.2M19.1 4.9L4.9 19.1"/>',
    trainer: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    shop: '<path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
  };

  function renderTilesHtml(tiles) {
    var html = '';
    (tiles || []).forEach(function (tile) {
      var type = escapeHtml(tile.type);
      html +=
        '<a class="hub-cg__tile hub-cg__tile--' + type + (tile.wide ? ' hub-cg__tile--wide' : '') +
        '" data-tile="' + escapeHtml(tile.key) + '" href="' + escapeHtml(tile.href) + '">' +
        '<span class="hub-cg__ic hub-cg__ic--' + type + '" aria-hidden="true">' +
        '<svg class="hub-cg__svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        (TILE_ICONS[tile.type] || '') + '</svg></span>' +
        '<span class="hub-cg__text">' +
        '<span class="hub-cg__name">' + escapeHtml(tile.title) +
        ' <span class="hub-cg__cnt">' + escapeHtml(tile.count) + '</span></span>' +
        '<span class="hub-cg__sub">' + escapeHtml(tile.sub) + '</span>' +
        '</span>' +
        '<span class="hub-cg__chev" aria-hidden="true">›</span>' +
        '</a>';
    });
    return html;
  }

  /* ─── TASK-149 (S1): приветствие из фактов ─────────────────────────────── */

  /** Время суток по часу УСТРОЙСТВА (0–23), не по поясу города. */
  function dayPart(hour) {
    var h = Number(hour);
    if (isNaN(h)) h = 12;
    h = ((Math.floor(h) % 24) + 24) % 24;
    if (h >= 5 && h < 12) return 'morning';
    if (h >= 12 && h < 18) return 'day';
    if (h >= 18 && h < 23) return 'evening';
    return 'night';
  }

  var GREETING_WITH_NAME = {
    morning: 'Утро',
    day: 'День',
    evening: 'Вечер',
    night: 'Ночь',
  };
  // Без имени голое «Вечер» читается обрывком — берём полную форму приветствия.
  var GREETING_NO_NAME = {
    morning: 'Доброе утро',
    day: 'Добрый день',
    evening: 'Добрый вечер',
    night: 'Доброй ночи',
  };

  /** «Вечер, Максим»; нет имени — «Добрый вечер». */
  function greetingText(hour, name) {
    var part = dayPart(hour);
    var clean = String(name == null ? '' : name).trim();
    return clean ? GREETING_WITH_NAME[part] + ', ' + clean : GREETING_NO_NAME[part];
  }

  /**
   * Подпись под приветствием — только факты данных, без погоды и оценок:
   *   - город — iceTeaser.city_name, если это НЕ страновой фолбэк (иначе это не город клиента);
   *   - «N катков вечером» — window.hits вечернего окна, то есть число МЕСТ, где
   *     вечером есть сеанс. Это не «сеансов сегодня»: сеансов клиент не получает —
   *     тизер отдаёт максимум 4 ближайших, считать по ним значило бы врать.
   * Нет города — подписи нет (пустая строка), число без города не показываем.
   */
  function greetingSub(facts) {
    facts = facts || {};
    var city = String(facts.cityName == null ? '' : facts.cityName).trim();
    if (!city || facts.isCountryFallback) return '';
    var parts = [city];
    var hits = positiveCount(facts.eveningHits);
    if (hits != null) {
      parts.push(hits + ' ' + pluralRu(hits, 'каток', 'катка', 'катков') + ' вечером');
    }
    return parts.join(' · ');
  }

  return {
    POD_DEFS: POD_DEFS,
    buildPods: buildPods,
    buildTiles: buildTiles,
    tilesVisible: tilesVisible,
    renderTilesHtml: renderTilesHtml,
    podHref: function (key, cityId) {
      var def = POD_DEFS.find(function (d) { return d.key === key; });
      return def ? def.hrefFrom(cityId) : '';
    },
    facetCount: facetCount,
    dayPart: dayPart,
    greetingText: greetingText,
    greetingSub: greetingSub,
  };
});
