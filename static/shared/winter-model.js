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
    if (point && point.dispute) {
      /* Отметки расходятся: цвет не меняем, добавляем знак «!» (U1). */
      out.pin = 'dispute';
      out.disputed = true;
    }
    return out;
  }

  function kindLabel(kind, short) {
    if (kind === 'hockey_box') return short ? 'Коробка' : 'Хоккейная коробка';
    return 'Каток';
  }

  /** is_paid: false — бесплатно, true — платно, null — не знаем (никогда не «бесплатно» по умолчанию). */
  function priceLabel(point) {
    if (!point) return '';
    if (point.is_paid === false) return 'Бесплатно';
    if (point.is_paid === true) return point.price_note ? 'Платно, ' + point.price_note : 'Платно';
    return point.price_note || 'Цена уточняется';
  }

  /** Часы: известны — «Ежедневно 7:00–23:00 · зимой 2025/26»; нет — «Часы уточняйте по телефону». */
  function hoursLabel(point) {
    var h = (point && point.hours) || {};
    if (h.known && h.summary) return h.summary + (h.label ? ' · ' + h.label : '');
    if (h.known && h.text) return h.text + (h.label ? ' · ' + h.label : '');
    return h.fallback || 'Часы уточняйте по телефону';
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

  /**
   * «Когда отметили». Админский статус — «Проверено DD.MM» (U4); людской — «Отметили 40 мин назад».
   * У «Ждём заливку» без отметок строки нет: импортное время — не отметка человека.
   */
  function checkedLine(point, now) {
    if (!point || !point.state_at) return '';
    if (point.checked_by === 'admin') return 'Проверено ' + dayMonth(point.state_at);
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

  /** Вторая строка карточки списка. Неточная точка честно говорит «точку уточняем». */
  function cardMeta(point) {
    var bits = [hoursLabel(point), priceLabel(point)];
    if (point && point.locating) bits.push('точку уточняем');
    return bits.filter(Boolean).join(' · ');
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
        title: 'Сезон открывается: ждём первые заливы',
        hint: 'Как только где-то зальют, мы напишем в Telegram. Если вы рядом со льдом, отметьте его.',
        bellFirst: true,
      };
    }
    return { title: '', hint: '', bellFirst: false };
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
      label: 'ЛЁД',
      required: true,
      opts: [
        { id: 'on', label: 'Залит', api: 'flooded' },
        { id: 'bad', label: 'Плохой', api: 'bad' },
        { id: 'off', label: 'Не залит', api: 'not_flooded' },
      ],
    },
    {
      key: 'crowd',
      label: 'ЛЮДЕЙ',
      required: false,
      opts: [
        { id: 'few', label: 'Мало', api: 'few' },
        { id: 'mid', label: 'Нормально', api: 'normal' },
        { id: 'many', label: 'Много', api: 'many' },
      ],
    },
    {
      key: 'hockey',
      label: 'ХОККЕЙ',
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

  function reportInit() {
    return { ice: null, crowd: null, hockey: null };
  }

  /** Повторный тап по выбранному снимает выбор: необязательные вопросы можно «отпустить». */
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

  function questionsView(state) {
    return QUESTIONS.map(function (q) {
      return {
        key: q.key,
        label: q.required ? q.label : q.label + ' · необязательно',
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
   * Что сказать после отметки. Не обещаем лишнего: с сайта «залит» весит полголоса и сам статус не меняет
   * (нужен сигнал из Telegram или фото), поэтому объясняем это прямо, а не «статус изменился».
   */
  function reportOutcome(state, result, source) {
    var ice = state.ice;
    var rule;
    if (ice === 'on') {
      if (result && result.state === 'flooded') {
        rule = 'Статус «Залит» подтверждён. Людей и хоккей видно 2 часа.';
      } else if (source === 'site') {
        rule = 'С сайта отметка весит вполсилы. «Залит» подтвердится, когда отметит кто-то из Telegram или придёт фото со льдом.';
      } else {
        rule = 'Ещё одна отметка «залит» — и покажем всем, что лёд есть. Людей и хоккей видно 2 часа.';
      }
    } else if (ice === 'bad') {
      rule = '«Лёд плохой» виден 24 часа и на статус «Залит» не влияет.';
    } else {
      rule = 'Отметки «не залит» копятся: две за сутки от разных людей — и статус вернётся в «Ждём заливку».';
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

  /** Выбор «Уже залит / Не зальют» на странице «Ждём заливку» — те же отметки про лёд. */
  var QUICK = { on: 'flooded', off: 'not_flooded' };
  function quickPayload(choice) {
    return QUICK[choice] ? { kind: 'ice', value: QUICK[choice], companions: [] } : null;
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
    checkedLine: checkedLine,
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
