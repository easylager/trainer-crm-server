/**
 * Зимние катки и коробки (TASK-343, волна 2): логика экранов без DOM.
 * Одна модель на сайт (static/share/winter.js) и Mini App (static/webapp/winter-points.js).
 * Данные — ответ /api/public/winter/…; ничего здесь не ходит в сеть.
 *
 * Правила, которые держит модель (см. TASK-343, «Решения» и «Edge cases»):
 *  - «открыто сейчас» по часам прошлой зимы не считаем; часы всегда с подписью сезона;
 *  - у неточных точек (locating) нет карты и расстояния;
 *  - «плохой лёд» — признак, а не статус; «залит» с сайта один не подтверждается.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.GlideWinter = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var NBSP = ' ';
  var MINSK_OFFSET_MS = 3 * 3600 * 1000;

  /* Статус не только цветом (U1): у каждого есть слово и значок. */
  var STATE_VIEW = {
    flooded: { label: 'Залит', tone: 'ok', icon: 'check', pin: 'ok' },
    waiting: { label: 'Ждём заливку', tone: 'wait', icon: 'clock', pin: 'wait' },
    stale: { label: 'Давно не отмечали', tone: 'quiet', icon: 'clock', pin: 'quiet' },
    closed: { label: 'Закрыт', tone: 'quiet', icon: 'cross', pin: 'quiet' },
  };
  var STATE_RANK = { flooded: 0, waiting: 1, stale: 2, closed: 3 };

  function plural(n, one, few, many) {
    var m10 = n % 10;
    var m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  function stateView(point) {
    var base = STATE_VIEW[point && point.state] || STATE_VIEW.waiting;
    var out = { label: base.label, tone: base.tone, icon: base.icon, pin: base.pin };
    if (point && point.dispute && point.state === 'flooded') {
      /* Есть отметки «не залит»: цвет не меняем, на карте знак «!» (U1); текста тег не добавляет. */
      out.pin = 'dispute';
      out.disputed = true;
    }
    return out;
  }

  function kindLabel(kind, short) {
    if (kind === 'hockey_box') return short ? 'Коробка' : 'Хоккейная коробка';
    return 'Каток';
  }

  /** is_paid: false — бесплатно, true — платно, null — не знаем (никогда не «бесплатно» по умолчанию). Неизвестно — пустая строка. */
  function priceLabel(point) {
    if (!point) return '';
    if (point.is_paid === false) return 'Бесплатно';
    if (point.is_paid === true) return point.price_note ? 'Платно, ' + point.price_note : 'Платно';
    return point.price_note || '';
  }

  /** Часы без подписи сезона («Ежедневно 7:00–23:00»); неизвестны — пустая строка. */
  function hoursKnownText(point) {
    var h = (point && point.hours) || {};
    if (h.known && h.summary) return h.summary;
    if (h.known && h.text) return h.text;
    return '';
  }

  /** Сезон, из которого взяты часы и цена («2025/26»); у точек с собственным расписанием его нет. */
  function dataSeason(point) {
    var h = (point && point.hours) || {};
    if (h.season) return String(h.season);
    var m = /(\d{4}\/\d{2})/.exec(h.label || '');
    return m ? m[1] : '';
  }

  /** Часы для строки «Что известно»: известны — как есть; нет — «Часы уточняйте по телефону» только если телефон есть. */
  function hoursLabel(point) {
    var known = hoursKnownText(point);
    if (known) return known;
    return point && point.phone ? 'Часы уточняйте по телефону' : '';
  }

  /** Короткое расстояние. Только для точных точек: у неточных distance_km = null и строки нет. */
  function distanceLabel(km) {
    if (km == null || isNaN(km)) return '';
    if (km < 1) return Math.max(50, Math.round((km * 1000) / 50) * 50) + NBSP + 'м';
    return String(Math.round(km * 10) / 10).replace('.', ',') + NBSP + 'км';
  }

  function ago(iso, now) {
    var t = Date.parse(iso || '');
    if (isNaN(t)) return '';
    var ref = now instanceof Date ? now.getTime() : Date.now();
    var min = Math.floor((ref - t) / 60000);
    if (min < 1) return 'только что';
    if (min < 60) return min + ' мин назад';
    var h = Math.floor(min / 60);
    if (h < 24) return h + ' ' + plural(h, 'час', 'часа', 'часов') + ' назад';
    var d = Math.floor(h / 24);
    return d + ' ' + plural(d, 'день', 'дня', 'дней') + ' назад';
  }

  function dayMonth(iso) {
    var t = Date.parse(iso || '');
    if (isNaN(t)) return '';
    var d = new Date(t + MINSK_OFFSET_MS);
    var dd = d.getUTCDate();
    var mm = d.getUTCMonth() + 1;
    return (dd < 10 ? '0' : '') + dd + '.' + (mm < 10 ? '0' : '') + mm;
  }

  var MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

  /** «2 ноября»; год добавляем только если он не текущий. */
  function dayMonthRu(iso, now) {
    var t = Date.parse(iso || '');
    if (isNaN(t)) return '';
    var d = new Date(t + MINSK_OFFSET_MS);
    var ref = new Date((now instanceof Date ? now.getTime() : Date.now()) + MINSK_OFFSET_MS);
    var out = d.getUTCDate() + ' ' + MONTHS_GEN[d.getUTCMonth()];
    if (d.getUTCFullYear() !== ref.getUTCFullYear()) out += ' ' + d.getUTCFullYear();
    return out;
  }

  /**
   * «Когда отметили». Админский статус — «Заливку подтвердили 2 ноября» / «Проверено 2 ноября» (U4); людской — «Отметили 40 мин назад».
   * У «Ждём заливку» без отметок строки нет: импортное время — не отметка человека.
   */
  function pendingLine(point) {
    var n = point && point.pending ? Number(point.pending_people) : 0;
    if (!(n > 0)) return '';
    var verb = n % 10 === 1 && n % 100 !== 11 ? 'отметил' : 'отметили';
    return n + ' ' + plural(n, 'человек', 'человека', 'человек') + ' ' + verb + ', что залит · проверяем';
  }

  function checkedLine(point, now) {
    if (!point) return '';
    /* Люди отметили «залит», админ ещё не подтвердил: статус остаётся «Ждём заливку», строка нейтральная. */
    var pend = pendingLine(point);
    if (pend) return pend;
    if (!point.state_at) return '';
    if (point.checked_by === 'admin' || point.checked_by === 'source') {
      var day = dayMonthRu(point.state_at, now);
      if (!day) return '';
      return (point.state === 'flooded' ? 'Заливку подтвердили ' : 'Проверено ') + day;
    }
    if (point.checked_by === 'people' && point.state !== 'waiting') return 'Отметили ' + ago(point.state_at, now);
    return '';
  }

  /** Подпись + «· 40 мин назад». Старше окна (2 ч) метка неактуальна — пустая строка. */
  function liveLabel(label, iso, now) {
    if (!iso) return label;
    var t = Date.parse(iso);
    var ref = now instanceof Date ? now.getTime() : Date.now();
    if (isNaN(t)) return label;
    if (ref - t > 2 * 3600 * 1000) return '';
    return label + ' · ' + ago(iso, now);
  }

  /** Теги «сейчас»: людей и хоккей живут 2 часа; со временем отметки, если API его отдал. */
  function liveTags(point, now) {
    var out = [];
    var crowd = { few: 'Мало людей', normal: 'Людей нормально', many: 'Много людей' }[point && point.crowd];
    var hockey = { playing: 'Идёт хоккей', free: 'Хоккея нет' }[point && point.hockey];
    if (crowd) out.push(liveLabel(crowd, point.crowd_at, now));
    if (hockey) out.push(liveLabel(hockey, point.hockey_at, now));
    if (point && point.quality === 'bad') out.push('Лёд плохой');
    return out.filter(Boolean);
  }

  /** Нейтральная строка у залитой точки, если есть отметки «не залит». Механику (веса, пороги) не показываем. */
  function disputeNote(point) {
    return point && point.dispute && point.state === 'flooded' ? 'Есть отметки «не залит» · проверяем' : '';
  }

  function lowerFirst(text) {
    if (!text) return text;
    if (/^(Пн|Вт|Ср|Чт|Пт|Сб|Вс)(?![а-яё])/.test(text)) return text; /* дни недели оставляем как есть */
    if (text.length > 1 && text.charAt(1) !== text.charAt(1).toLowerCase()) return text; /* аббревиатура */
    return text.charAt(0).toLowerCase() + text.slice(1);
  }

  /**
   * Вторая строка карточки списка. Часы и цена из таблицы прошлой зимы идут с префиксом
   * «Прошлой зимой: ежедневно 07:00–23:00 · бесплатно»; неизвестная цена не упоминается,
   * «Часы уточняйте по телефону» — только когда телефон есть.
   */
  function cardMeta(point) {
    var hours = hoursKnownText(point);
    var price = priceLabel(point);
    var last = !!dataSeason(point);
    var bits = [];
    if (hours) bits.push(hours);
    if (price) bits.push(price);
    var line = '';
    if (bits.length) {
      bits = bits.map(function (b, i) { return last || i > 0 ? lowerFirst(b) : b; });
      line = (last ? 'Прошлой зимой: ' : '') + bits.join(' · ');
    }
    var out = point && point.locating ? ['Адрес примерный'] : [];
    out.push(line);
    if (!hours && point && point.phone) out.push('Часы уточняйте по телефону');
    return out.filter(Boolean).join(' · ');
  }

  /** Заголовок карточки: слово типа («Каток, », «Коробка, ») уже есть в надписи над ним. */
  function cardTitle(point) {
    var name = String((point && point.name) || '');
    var m = /^(Каток|Коробка),\s+(.+)$/.exec(name);
    return m ? m[2] : name;
  }

  function summaryLine(total, flooded) {
    var wait = Math.max(0, total - flooded);
    var noun = plural(total, 'уличная точка', 'уличные точки', 'уличных точек');
    var line = total + NBSP + noun;
    if (flooded > 0) return line + ' · залиты ' + flooded + ' · ждём ' + wait;
    return line + ' · ждём заливку';
  }

  /** U4: ноль залитых — не «залиты 0», а честное начало сезона. */
  function headline(total, flooded) {
    if (total > 0 && flooded === 0) {
      return {
        title: 'Сезон открывается: ждём первую заливку',
        hint: 'Как только где-то зальют, напишем в Telegram. Если вы рядом со льдом, отметьте его.',
        bellFirst: true,
      };
    }
    return { title: '', hint: '', bellFirst: false };
  }

  /* Список делится по смыслу: где кататься сейчас, где ждём заливку, остальное — внизу и тише. */
  var GROUPS = [
    { key: 'now', title: 'Можно кататься' },
    { key: 'wait', title: 'Ждём заливку' },
    { key: 'off', title: 'Закрыты или давно без отметок' },
  ];

  function groupKey(point) {
    var s = point && point.state;
    if (s === 'flooded') return 'now';
    if (s === 'stale' || s === 'closed') return 'off';
    return 'wait';
  }

  /** Уже отсортированный список → непустые группы в порядке GROUPS; порядок внутри группы сохраняется. */
  function listGroups(points) {
    var by = { now: [], wait: [], off: [] };
    (points || []).forEach(function (p) {
      by[groupKey(p)].push(p);
    });
    return GROUPS.filter(function (g) {
      return by[g.key].length > 0;
    }).map(function (g) {
      return { key: g.key, title: g.title, items: by[g.key] };
    });
  }

  /**
   * Где показать подписку «лёд рядом»: сразу после «Можно кататься» (её видно на первом-втором экране),
   * а если залитых нет — над списком: ждать заливку и есть главный повод подписаться.
   */
  function bellSlot(groups) {
    return groups && groups.length && groups[0].key === 'now' ? 'now' : 'top';
  }

  /** Подписка «рядом» уже есть: ответ GET /api/webapp/winter/subscriptions. */
  function hasNearSub(items) {
    return (items || []).some(function (s) {
      return s && s.kind === 'near';
    });
  }

  /** U6: чип «Район» только там, где известно хотя бы два района с двумя точками и больше. */
  function districtList(points) {
    var count = {};
    (points || []).forEach(function (p) {
      var d = (p.district || '').trim();
      if (d) count[d] = (count[d] || 0) + 1;
    });
    return Object.keys(count)
      .filter(function (d) {
        return count[d] >= 2;
      })
      .sort(function (a, b) {
        return count[b] - count[a] || a.localeCompare(b, 'ru');
      })
      .map(function (d) {
        return { name: d, count: count[d] };
      });
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    var rad = Math.PI / 180;
    var a =
      Math.pow(Math.sin(((lat2 - lat1) * rad) / 2), 2) +
      Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.pow(Math.sin(((lon2 - lon1) * rad) / 2), 2);
    return 2 * 6371 * Math.asin(Math.sqrt(a));
  }

  function withDistance(points, origin) {
    return (points || []).map(function (p) {
      var km = null;
      if (origin && p.map_allowed && p.lat != null && p.lon != null) {
        km = Math.round(haversineKm(origin.lat, origin.lon, p.lat, p.lon) * 10) / 10;
      }
      var copy = {};
      Object.keys(p).forEach(function (k) {
        copy[k] = p[k];
      });
      copy.distance_km = km;
      return copy;
    });
  }

  /**
   * Фильтры и сортировка: закреп (Немига) → залитые → ближе (только точные) → район → имя.
   * Тот же порядок, что у сервера, чтобы страница не «прыгала» после включения геолокации.
   */
  function applyFilters(points, f) {
    f = f || {};
    var list = withDistance(points, f.origin);
    list = list.filter(function (p) {
      if (f.flooded && p.state !== 'flooded') return false;
      if (f.kind && p.kind !== f.kind) return false;
      if (f.district && (p.district || '') !== f.district) return false;
      return true;
    });
    list.sort(function (a, b) {
      var pa = a.pin == null ? 1 : 0;
      var pb = b.pin == null ? 1 : 0;
      if (pa !== pb) return pa - pb;
      if (pa === 0 && a.pin !== b.pin) return a.pin - b.pin;
      var sa = STATE_RANK[a.state] != null ? STATE_RANK[a.state] : 9;
      var sb = STATE_RANK[b.state] != null ? STATE_RANK[b.state] : 9;
      if (sa !== sb) return sa - sb;
      var da = a.distance_km == null ? 1 : 0;
      var db = b.distance_km == null ? 1 : 0;
      if (da !== db) return da - db;
      if (da === 0 && a.distance_km !== b.distance_km) return a.distance_km - b.distance_km;
      var ra = a.district || '~';
      var rb = b.district || '~';
      if (ra !== rb) return ra < rb ? -1 : 1;
      return String(a.name).localeCompare(String(b.name), 'ru');
    });
    return list;
  }

  /** Под какой сортировкой сейчас список: подпись под чипами. */
  function sortNote(f) {
    f = f || {};
    if (f.district) return f.district;
    if (f.flooded) return 'Только где лёд подтвердили за последние 3 дня.';
    if (f.kind === 'rink') return 'Катки — ровный лёд, можно на фигурных.';
    if (f.kind === 'hockey_box') return 'Коробки — с бортами, часто занимают под хоккей.';
    return f.origin
      ? 'Сначала залитые, потом ближайшие.'
      : 'Сначала залитые, потом по районам. Включите геолокацию — покажем ближайшие.';
  }

  function mapPoints(points) {
    return (points || []).filter(function (p) {
      return p.map_allowed && p.lat != null && p.lon != null;
    });
  }

  function emptyFilterText(f) {
    f = f || {};
    if (f.flooded) return 'Залитых точек пока нет. Подпишитесь — напишем, когда зальют.';
    return 'По этому фильтру ничего нет.';
  }

  /* --- шторка «Как там сейчас?» ------------------------------------------------------ */
  var QUESTIONS = [
    {
      key: 'ice',
      label: 'Лёд',
      required: true,
      opts: [
        { id: 'on', label: 'Залит', api: 'flooded' },
        { id: 'bad', label: 'Плохой', api: 'bad' },
        { id: 'off', label: 'Не залит', api: 'not_flooded' },
      ],
    },
    {
      key: 'crowd',
      label: 'Людей',
      required: false,
      opts: [
        { id: 'few', label: 'Мало', api: 'few' },
        { id: 'mid', label: 'Нормально', api: 'normal' },
        { id: 'many', label: 'Много', api: 'many' },
      ],
    },
    {
      key: 'hockey',
      label: 'Хоккей',
      required: false,
      opts: [
        { id: 'yes', label: 'Идёт', api: 'playing' },
        { id: 'no', label: 'Свободно', api: 'free' },
      ],
    },
  ];
  var SUMMARY_WORD = {
    on: 'Залит',
    bad: 'Лёд плохой',
    off: 'Не залит',
    few: 'мало людей',
    mid: 'людей нормально',
    many: 'много людей',
    yes: 'идёт хоккей',
    no: 'хоккея нет',
  };

  /* Mini App, шторка точки. Пока заливку не подтвердили, оценивать качество нечего: «Залили / Ещё не залит»
     уходят одним нажатием. У залитой точки сначала выбирают лёд, затем по желанию людей и хоккей, и отправляют. */
  var MARK_ICE = {
    wait: [
      { id: 'on', label: 'Залили' },
      { id: 'off', label: 'Ещё не залит' },
    ],
    now: [
      { id: 'on', label: 'Хороший' },
      { id: 'bad', label: 'Плохой' },
      { id: 'off', label: 'Льда нет' },
    ],
  };

  function markView(point, state) {
    var flooded = !!(point && point.state === 'flooded');
    state = state || reportInit();
    return {
      title: flooded ? 'Вы у катка? Какой сейчас лёд?' : 'Вы у катка? Залили лёд?',
      hint: flooded
        ? 'Вашу отметку сразу увидят все, кто выбирает, куда пойти.'
        : 'Отметьте, что видите. Когда заливку подтвердят, подписчики получат сообщение.',
      oneTap: !flooded,
      ice: MARK_ICE[flooded ? 'now' : 'wait'].map(function (o) {
        return { id: o.id, label: o.label, selected: state.ice === o.id };
      }),
      extras: flooded && state.ice ? questionsView(state, { flooded: true }).filter(function (q) {
        return q.key !== 'ice';
      }) : [],
      canSend: flooded && !!state.ice,
    };
  }

  function hasPointSub(items, id) {
    return (items || []).some(function (s) {
      return s && s.kind === 'point' && Number(s.arena_id) === Number(id);
    });
  }

  function reportInit() {
    return { ice: null, crowd: null, hockey: null };
  }

  /** Повторный тап по выбранному снимает выбор. */
  function reportToggle(state, key, id) {
    var next = { ice: state.ice, crowd: state.crowd, hockey: state.hockey };
    next[key] = next[key] === id ? null : id;
    return next;
  }

  function reportCanSend(state) {
    return !!state.ice;
  }

  function reportSendLabel(state) {
    return reportCanSend(state) ? 'Отметить' : 'Сначала про лёд';
  }

  /** Вопросы шторки. Людей и хоккей спрашиваем только у залитой точки (opts.flooded). */
  function questionsView(state, opts) {
    var flooded = !!(opts && opts.flooded);
    return QUESTIONS.filter(function (q) {
      return q.key === 'ice' || flooded;
    }).map(function (q) {
      return {
        key: q.key,
        label: q.label,
        opts: q.opts.map(function (o) {
          return { id: o.id, label: o.label, selected: state[q.key] === o.id };
        }),
      };
    });
  }

  function apiValue(key, id) {
    var q = QUESTIONS.filter(function (x) {
      return x.key === key;
    })[0];
    var o = q && q.opts.filter(function (x) {
      return x.id === id;
    })[0];
    return o ? o.api : null;
  }

  /** Тело запроса: главная отметка про лёд + попутные (людей, хоккей) в том же запросе. */
  function reportPayload(state, extra) {
    if (!reportCanSend(state)) return null;
    var body = { kind: 'ice', value: apiValue('ice', state.ice), companions: [] };
    ['crowd', 'hockey'].forEach(function (k) {
      if (state[k]) body.companions.push({ kind: k, value: apiValue(k, state[k]) });
    });
    if (extra) Object.keys(extra).forEach(function (k) { if (extra[k] != null) body[k] = extra[k]; });
    return body;
  }

  function reportSummary(state) {
    var parts = ['ice', 'crowd', 'hockey']
      .map(function (k) {
        return state[k] ? SUMMARY_WORD[state[k]] : null;
      })
      .filter(Boolean);
    return parts.join(' · ') + ' · только что';
  }

  /**
   * Что сказать после отметки. Не обещаем лишнего: пока администратор не подтвердил, статус остаётся «Ждём заливку».
   */
  function reportOutcome(state, result) {
    var ice = state.ice;
    var rule;
    if (ice === 'on') {
      rule = result && result.state === 'flooded'
        ? 'Спасибо! Увидят все, кто выбирает, куда пойти.'
        : 'Спасибо! Передали на проверку. Пока проверяем, на странице остаётся «Ждём заливку».';
    } else if (ice === 'bad') {
      rule = 'Спасибо! Отметку «плохой лёд» увидят все в ближайшие сутки.';
    } else {
      rule = 'Спасибо! Проверим и обновим статус.';
    }
    return { summary: reportSummary(state), rule: rule };
  }

  function waitText(sec) {
    var min = Math.max(1, Math.ceil((sec || 0) / 60));
    if (min < 60) return min + ' ' + plural(min, 'минуту', 'минуты', 'минут');
    var h = Math.floor(min / 60);
    var m = min % 60;
    return h + ' ' + plural(h, 'час', 'часа', 'часов') + (m ? ' ' + m + ' ' + plural(m, 'минуту', 'минуты', 'минут') : '');
  }

  /** Текст ошибки отправки: лимит, истёкший токен страницы, снятая с приёма точка, сеть. */
  function reportErrorText(status, retryAfterSec) {
    if (status === 429) {
      return retryAfterSec
        ? 'Вы уже отмечали эту точку. Следующую отметку можно через ' + waitText(retryAfterSec) + '.'
        : 'Вы уже отмечали эту точку. Попробуйте позже.';
    }
    if (status === 403) return 'Страница устарела. Обновите её и отметьте ещё раз.';
    if (status === 404) return 'Эта точка сейчас не принимает отметки.';
    if (status === 422) return 'Не получилось понять ответ. Выберите ещё раз.';
    return 'Не удалось отправить. Проверьте связь и попробуйте ещё раз.';
  }

  function newIdemKey() {
    var rnd = '';
    for (var i = 0; i < 4; i++) rnd += Math.floor(Math.random() * 0x10000).toString(16).padStart(4, '0');
    return rnd.slice(0, 32);
  }

  /** Выбор «Уже залит / Ещё не залит» на странице «Ждём заливку» — те же отметки про лёд. */
  var QUICK = { on: 'flooded', off: 'not_flooded' };
  function quickPayload(choice) {
    return QUICK[choice] ? { kind: 'ice', value: QUICK[choice], companions: [] } : null;
  }

  /* --- свайп вниз по шторке ---------------------------------------------------------- */
  var SWIPE_DISTANCE = 80; // px
  var SWIPE_VELOCITY = 0.5; // px/ms
  var SWIPE_FLICK_MIN = 20; // px: короткий дёрг пальца за пару миллисекунд не считаем смахиванием

  /** Чистое решение: закрыть шторку или вернуть на место. dy — сдвиг вниз (px), ms — время жеста. */
  function swipeDecision(dy, ms) {
    if (!(dy > 0)) return 'snap';
    if (dy > SWIPE_DISTANCE) return 'close';
    var speed = dy / Math.max(1, ms || 0);
    return dy >= SWIPE_FLICK_MIN && speed > SWIPE_VELOCITY ? 'close' : 'snap';
  }

  /** Во встроенном Telegram жест вниз сворачивает окно: на время шторки просим его не трогать. */
  function tgVerticalSwipes(on) {
    try {
      var w = typeof window !== 'undefined' && window.Telegram && window.Telegram.WebApp;
      if (!w) return;
      if (on && w.enableVerticalSwipes) w.enableVerticalSwipes();
      else if (!on && w.disableVerticalSwipes) w.disableVerticalSwipes();
    } catch (e) { /* не мини-апп */ }
  }

  /**
   * Свайп вниз по нижней шторке. Тянуть можно за ручку (верх панели) и за саму панель, когда она
   * прокручена до верха. Панель идёт за пальцем (только вниз); отпустили дальше 80 px или быстро —
   * закрываем, иначе возвращаем. prefers-reduced-motion: без анимации.
   * parts: { panel, back, onClose }. Возвращает { reset }.
   */
  function attachSwipe(parts) {
    var panel = parts.panel;
    var back = parts.back;
    var drag = null;
    var HANDLE_ZONE = 40;
    function reduced() {
      return typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }
    function reset() {
      panel.style.transition = '';
      panel.style.transform = '';
      if (back) back.style.opacity = '';
    }
    function start(y, target) {
      var top = panel.getBoundingClientRect().top;
      var onHandle = y - top <= HANDLE_ZONE || !!(target && target.closest && target.closest('.w-sheet__grab'));
      if (!onHandle && panel.scrollTop > 0) return;
      drag = { y0: y, t0: Date.now(), dy: 0, on: false, handle: onHandle };
    }
    function move(y, ev) {
      if (!drag) return;
      var dy = y - drag.y0;
      if (!drag.on) {
        if (dy > 6 && (drag.handle || panel.scrollTop <= 0)) {
          drag.on = true;
          drag.y0 = y;
          drag.t0 = Date.now();
          dy = 0;
          panel.style.transition = 'none';
        } else if (dy < -6) {
          drag = null;
          return;
        } else return;
      }
      if (ev && ev.cancelable) ev.preventDefault();
      drag.dy = Math.max(0, dy);
      panel.style.transform = 'translateY(' + drag.dy + 'px)';
      if (back) back.style.opacity = String(Math.max(0.2, 1 - drag.dy / 360));
    }
    function end() {
      var d = drag;
      drag = null;
      if (!d || !d.on) return;
      if (swipeDecision(d.dy, Date.now() - d.t0) === 'close') {
        if (reduced()) {
          parts.onClose();
          reset();
          return;
        }
        panel.style.transition = 'transform 160ms ease-out';
        panel.style.transform = 'translateY(100%)';
        setTimeout(function () {
          parts.onClose();
          reset();
        }, 150);
      } else if (reduced()) {
        reset();
      } else {
        panel.style.transition = 'transform 180ms ease-out';
        panel.style.transform = '';
        if (back) back.style.opacity = '';
      }
    }
    panel.addEventListener('touchstart', function (e) {
      if (e.touches.length === 1) start(e.touches[0].clientY, e.target);
      else drag = null;
    }, { passive: true });
    panel.addEventListener('touchmove', function (e) { move(e.touches[0].clientY, e); }, { passive: false });
    panel.addEventListener('touchend', end, { passive: true });
    panel.addEventListener('touchcancel', end, { passive: true });
    /* Мышь (десктоп, эмуляция): тот же жест через pointer events. */
    panel.addEventListener('pointerdown', function (e) {
      if (e.pointerType !== 'mouse' || e.button !== 0) return;
      start(e.clientY, e.target);
      if (!drag) return;
      var onMove = function (ev) { move(ev.clientY, ev); };
      var onUp = function () {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        end();
      };
      document.addEventListener('pointermove', onMove);
      document.addEventListener('pointerup', onUp);
    });
    return { reset: reset };
  }

  return {
    NBSP: NBSP,
    plural: plural,
    stateView: stateView,
    kindLabel: kindLabel,
    priceLabel: priceLabel,
    hoursLabel: hoursLabel,
    distanceLabel: distanceLabel,
    ago: ago,
    dayMonth: dayMonth,
    dayMonthRu: dayMonthRu,
    disputeNote: disputeNote,
    cardTitle: cardTitle,
    hoursKnownText: hoursKnownText,
    dataSeason: dataSeason,
    swipeDecision: swipeDecision,
    attachSwipe: attachSwipe,
    tgVerticalSwipes: tgVerticalSwipes,
    checkedLine: checkedLine,
    pendingLine: pendingLine,
    liveTags: liveTags,
    liveLabel: liveLabel,
    cardMeta: cardMeta,
    summaryLine: summaryLine,
    headline: headline,
    districtList: districtList,
    haversineKm: haversineKm,
    applyFilters: applyFilters,
    sortNote: sortNote,
    mapPoints: mapPoints,
    groupKey: groupKey,
    listGroups: listGroups,
    bellSlot: bellSlot,
    hasNearSub: hasNearSub,
    hasPointSub: hasPointSub,
    markView: markView,
    emptyFilterText: emptyFilterText,
    QUESTIONS: QUESTIONS,
    reportInit: reportInit,
    reportToggle: reportToggle,
    reportCanSend: reportCanSend,
    reportSendLabel: reportSendLabel,
    questionsView: questionsView,
    reportPayload: reportPayload,
    reportSummary: reportSummary,
    reportOutcome: reportOutcome,
    reportErrorText: reportErrorText,
    waitText: waitText,
    newIdemKey: newIdemKey,
    quickPayload: quickPayload,
  };
});
