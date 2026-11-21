/**
 * TASK-438: «Поиск» — табло льда. Чистая модель без DOM: ряд дней, лента по времени,
 * «Неделя» и «Выходные» по ответу GET /api/webapp/client/ice-board.
 * Browser: window.IceBoardModel. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.IceBoardModel = api;
  }
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  var WEEKDAY_SHORT = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
  var WEEKDAY_LOWER = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

  var GROUPS = [
    { id: 'skate', label: 'Массовое', title: 'массового' },
    { id: 'hockey', label: 'С клюшкой', title: 'с клюшкой' },
    { id: 'figure', label: 'Фигурное', title: 'фигурного' },
  ];

  /* Первые строки ленты; остальное — по кнопке «Показать дальше». */
  var FIRST_ROWS = 5;
  /* «Выходные»: столько времён в колонке дня, остальное — «+N». */
  var WEEKEND_TIMES = 4;

  function plural(n, one, few, many) {
    var a = Math.abs(n) % 100;
    if (a >= 11 && a <= 14) return many;
    var l = a % 10;
    if (l === 1) return one;
    if (l >= 2 && l <= 4) return few;
    return many;
  }

  function parseIso(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
    if (!m) return null;
    return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  }

  function toIso(d) {
    return d.toISOString().slice(0, 10);
  }

  function addDays(iso, n) {
    var d = parseIso(iso);
    if (!d) return '';
    d.setUTCDate(d.getUTCDate() + n);
    return toIso(d);
  }

  function weekday(iso) {
    var d = parseIso(iso);
    return d ? d.getUTCDay() : 0;
  }

  /** «Сб, 21» */
  function dayChip(iso) {
    var d = parseIso(iso);
    if (!d) return '';
    return WEEKDAY_SHORT[d.getUTCDay()] + ', ' + d.getUTCDate();
  }

  /**
   * Ряд дней. Пн–Чт: Сегодня · Завтра · Выходные · Неделя. Пт: Сегодня · Выходные · Неделя
   * (завтра — уже выходные). Сб–Вс: Сегодня · Завтра · Неделя (выходные — это и есть сегодня/завтра).
   */
  function dayOptions(today) {
    var wd = weekday(today);
    var out = [{ id: 'today', label: 'Сегодня', from: today, days: 1 }];
    if (wd !== 5) out.push({ id: 'tomorrow', label: 'Завтра', from: addDays(today, 1), days: 1 });
    if (wd >= 1 && wd <= 5) {
      out.push({ id: 'weekend', label: 'Выходные', from: addDays(today, 6 - wd), days: 2 });
    }
    out.push({ id: 'week', label: 'Неделя', from: today, days: 7 });
    return out;
  }

  function groupById(id) {
    for (var i = 0; i < GROUPS.length; i++) if (GROUPS[i].id === id) return GROUPS[i];
    return GROUPS[0];
  }

  function countFor(days, group) {
    var total = 0;
    (days || []).forEach(function (d) {
      total += Number(d && d[group]) || 0;
    });
    return total;
  }

  function minutesOf(hhmm) {
    var m = /^(\d{1,2}):(\d{2})/.exec(String(hhmm || ''));
    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
  }

  function untilText(minutes) {
    if (minutes <= 0) return 'идёт сейчас';
    if (minutes < 60) return 'через ' + minutes + ' ' + plural(minutes, 'минуту', 'минуты', 'минут');
    var h = Math.floor(minutes / 60);
    var rest = minutes % 60;
    if (h >= 3 || rest === 0) return 'через ' + h + ' ' + plural(h, 'час', 'часа', 'часов');
    return 'через ' + h + ' ч ' + rest + ' мин';
  }

  function onlyGroup(sessions, group) {
    return (sessions || []).filter(function (s) {
      return s && s.group === group;
    });
  }

  function arenaCount(sessions) {
    var seen = {};
    var n = 0;
    sessions.forEach(function (s) {
      if (!seen[s.arena_id]) {
        seen[s.arena_id] = true;
        n++;
      }
    });
    return n;
  }

  function dayWord(iso, today) {
    if (iso === today) return 'сегодня';
    if (iso === addDays(today, 1)) return 'завтра';
    return WEEKDAY_LOWER[weekday(iso)] + ', ' + (parseIso(iso) || new Date()).getUTCDate();
  }

  /**
   * Шапка одного дня: «38 сеансов массового» и «сегодня на 7 катках · ближайший через 25 минут».
   */
  function dayHeadline(payload, group, date) {
    var today = payload.today;
    var list = onlyGroup(payload.sessions, group).filter(function (s) {
      return s.date === date;
    });
    var n = list.length;
    var g = groupById(group);
    if (!n) {
      return { title: 'Нет сеансов ' + g.title, sub: dayWord(date, today) + ' в этом городе' };
    }
    var title = n + ' ' + plural(n, 'сеанс', 'сеанса', 'сеансов') + ' ' + g.title;
    var k = arenaCount(list);
    var sub = dayWord(date, today) + ' на ' + k + ' ' + plural(k, 'катке', 'катках', 'катках');
    var first = list[0];
    if (date === today && payload.now_local) {
      var delta = minutesOf(first.start) - minutesOf(payload.now_local);
      if (delta != null && !isNaN(delta)) sub += ' · ближайший ' + untilText(delta);
    } else {
      sub += ' · первый в ' + first.start;
    }
    return { title: title, sub: sub };
  }

  function rentalShort(text) {
    return String(text || '').replace(/\s*(BYN|RUB|руб\.?)\s*$/i, '');
  }

  /** «12 BYN · прокат 10»; семейный — «семейный · 10 BYN»; без цены — «цена на месте». */
  function priceLine(s) {
    var parts = [];
    if (s.kind === 'family_skate') parts.push('семейный');
    if (s.label && s.kind !== 'family_skate' && s.group !== 'skate') parts.push(String(s.label));
    parts.push(s.price_adult || 'цена на месте');
    if (s.price_rental) parts.push('прокат ' + rentalShort(s.price_rental));
    return parts.join(' · ');
  }

  function sessionHref(s) {
    return (
      'arena?ref=' +
      encodeURIComponent(String(s.arena_id)) +
      '&day=' +
      encodeURIComponent(String(s.date)) +
      '&s=' +
      encodeURIComponent(String(s.session_id))
    );
  }

  function arenaDayHref(arenaId, date) {
    return 'arena?ref=' + encodeURIComponent(String(arenaId)) + '&day=' + encodeURIComponent(String(date));
  }

  /**
   * Лента дня: строки по времени. Матч встаёт в своё время рядом с сеансами (только «Массовое»
   * и «С клюшкой»: фигуристу матч в ленте ни к чему).
   */
  function timeline(payload, group, date) {
    var byTime = {};
    var order = [];
    function slot(t) {
      if (!byTime[t]) {
        byTime[t] = { time: t, items: [] };
        order.push(t);
      }
      return byTime[t];
    }
    onlyGroup(payload.sessions, group).forEach(function (s) {
      if (s.date !== date) return;
      slot(s.start).items.push({ type: 'session', session: s, href: sessionHref(s), price: priceLine(s) });
    });
    if (group !== 'figure') {
      (payload.matches || []).forEach(function (m) {
        if (!m || m.date !== date || !m.start) return;
        slot(m.start).items.push({ type: 'match', match: m });
      });
    }
    order.sort(function (a, b) {
      return minutesOf(a) - minutesOf(b);
    });
    return order.map(function (t) {
      var row = byTime[t];
      /* Матч — после сеансов своего времени: лента прежде всего про лёд. */
      row.items.sort(function (a, b) {
        return (a.type === 'match') - (b.type === 'match');
      });
      return row;
    });
  }

  /** Первые строки + подпись кнопки «Показать дальше · ещё 33» и подсказка про семейный. */
  function splitTimeline(rows, limit) {
    var n = limit == null ? FIRST_ROWS : limit;
    var head = rows.slice(0, n);
    var tail = rows.slice(n);
    var restSessions = 0;
    var family = null;
    var lastTime = '';
    tail.forEach(function (r) {
      lastTime = r.time;
      r.items.forEach(function (it) {
        if (it.type !== 'session') return;
        restSessions++;
        if (!family && it.session.kind === 'family_skate') family = r.time;
      });
    });
    return {
      head: head,
      tail: tail,
      more: tail.length
        ? {
            label: 'Показать дальше · ещё ' + restSessions,
            hint: family ? 'есть семейный в ' + family : lastTime ? 'до ' + lastTime : '',
          }
        : null,
    };
  }

  function daysOfRange(from, n) {
    var out = [];
    for (var i = 0; i < n; i++) out.push(addDays(from, i));
    return out;
  }

  /** Шапка «Недели»: семь дней с итогом по виду. */
  function weekHeader(payload, group) {
    return (payload.days || []).map(function (d) {
      var p = parseIso(d.date);
      return {
        date: d.date,
        short: p ? WEEKDAY_SHORT[p.getUTCDay()] : '',
        num: p ? p.getUTCDate() : '',
        total: Number(d[group]) || 0,
        isToday: d.date === payload.today,
      };
    });
  }

  function priceRange(list) {
    var vals = [];
    var cur = '';
    list.forEach(function (s) {
      var m = /^([\d\s]+(?:,\d+)?)\s*(.*)$/.exec(String(s.price_adult || ''));
      if (!m) return;
      vals.push({ n: Number(m[1].replace(/\s/g, '').replace(',', '.')), t: m[1].trim() });
      cur = cur || m[2];
    });
    if (!vals.length) return '';
    vals.sort(function (a, b) {
      return a.n - b.n;
    });
    var lo = vals[0];
    var hi = vals[vals.length - 1];
    return (lo.n === hi.n ? lo.t : lo.t + '–' + hi.t) + (cur ? ' ' + cur : '');
  }

  /** «каждый день», «по выходным», «сб, вс и пт», «почти каждый вечер». */
  function patternText(perDay, dates) {
    var withIce = dates.filter(function (d) {
      return perDay[d] && perDay[d].length;
    });
    if (withIce.length === dates.length) return 'каждый день';
    var wds = withIce.map(weekday);
    var weekendOnly = wds.every(function (w) {
      return w === 0 || w === 6;
    });
    if (weekendOnly && wds.length === 2) return 'по выходным';
    if (withIce.length >= dates.length - 1 && dates.length >= 6) return 'почти каждый день';
    if (withIce.length === 1) {
      var w = wds[0];
      return w === 0 ? 'в воскресенье' : w === 6 ? 'в субботу' : 'в ' + WEEKDAY_LOWER[w];
    }
    var names = withIce.map(function (d) {
      return WEEKDAY_LOWER[weekday(d)];
    });
    return names.slice(0, -1).join(', ') + ' и ' + names[names.length - 1];
  }

  function nextText(list, today, nowLocal) {
    var first = list[0];
    if (!first) return '';
    var when = dayWord(first.date, today);
    if (first.date === today) {
      var rest = list.filter(function (s) {
        return s.date === today;
      }).length;
      return rest > 1 ? 'сегодня ещё с ' + first.start : 'сегодня в ' + first.start;
    }
    return when + ' в ' + first.start;
  }

  function byArena(sessions) {
    var map = {};
    var order = [];
    sessions.forEach(function (s) {
      var k = String(s.arena_id);
      if (!map[k]) {
        map[k] = { arena_id: s.arena_id, name: s.arena_name, thumb: s.thumb || null, list: [] };
        order.push(k);
      }
      map[k].list.push(s);
    });
    return order.map(function (k) {
      return map[k];
    });
  }

  /** «Неделя»: катки, где лёд чаще, сверху; по дням — число сеансов. */
  function weekArenas(payload, group) {
    var dates = (payload.days || []).map(function (d) {
      return d.date;
    });
    var rows = byArena(onlyGroup(payload.sessions, group)).map(function (a) {
      var perDay = {};
      a.list.forEach(function (s) {
        (perDay[s.date] = perDay[s.date] || []).push(s);
      });
      var allDays = dates.every(function (d) {
        return perDay[d] && perDay[d].length;
      });
      var meta = [patternText(perDay, dates)];
      if (allDays) {
        var starts = a.list.map(function (s) {
          return s.start;
        });
        starts.sort(function (x, y) {
          return minutesOf(x) - minutesOf(y);
        });
        meta[0] += ' ' + starts[0] + '–' + starts[starts.length - 1];
      }
      var price = priceRange(a.list);
      if (price) meta.push(price);
      return {
        arena_id: a.arena_id,
        name: a.name,
        thumb: a.thumb,
        total: a.list.length,
        meta: meta.join(' · '),
        next: nextText(a.list, payload.today, payload.now_local),
        cells: dates.map(function (d) {
          var n = (perDay[d] || []).length;
          return { date: d, short: WEEKDAY_SHORT[weekday(d)], count: n, href: n ? arenaDayHref(a.arena_id, d) : '' };
        }),
      };
    });
    rows.sort(function (x, y) {
      return y.total - x.total || String(x.name).localeCompare(String(y.name), 'ru');
    });
    return rows;
  }

  /** «Выходные»: каток и две колонки, Сб и Вс, с реальными временами. */
  function weekendArenas(payload, group) {
    var dates = (payload.days || []).map(function (d) {
      return d.date;
    });
    var rows = byArena(onlyGroup(payload.sessions, group)).map(function (a) {
      return {
        arena_id: a.arena_id,
        name: a.name,
        thumb: a.thumb,
        total: a.list.length,
        price: priceRange(a.list),
        cols: dates.map(function (d) {
          var list = a.list.filter(function (s) {
            return s.date === d;
          });
          return {
            date: d,
            label: WEEKDAY_SHORT[weekday(d)],
            times: list.slice(0, WEEKEND_TIMES).map(function (s) {
              return { time: s.start, href: sessionHref(s) };
            }),
            more: list.length > WEEKEND_TIMES ? list.length - WEEKEND_TIMES : 0,
            moreHref: list.length > WEEKEND_TIMES ? arenaDayHref(a.arena_id, d) : '',
          };
        }),
      };
    });
    rows.sort(function (x, y) {
      return y.total - x.total || String(x.name).localeCompare(String(y.name), 'ru');
    });
    return rows;
  }

  /**
   * Редкие виды (с клюшкой, фигурное) на несколько дней — не таблица, а лента
   * с разделителями дней: сеансов мало, колонки были бы пустыми.
   */
  function multiDayFeed(payload, group) {
    return (payload.days || [])
      .map(function (d) {
        return { date: d.date, title: dayChip(d.date), rows: timeline(payload, group, d.date) };
      })
      .filter(function (d) {
        return d.rows.length;
      });
  }

  function rangeHeadline(payload, group, optionId) {
    var n = countFor(payload.days, group);
    var g = groupById(group);
    var list = onlyGroup(payload.sessions, group);
    var k = arenaCount(list);
    var dates = (payload.days || []).map(function (d) {
      return d.date;
    });
    var span = dates.length ? dayChip(dates[0]).toLowerCase() + ' — ' + dayChip(dates[dates.length - 1]).toLowerCase() : '';
    if (!n) return { title: 'Нет сеансов ' + g.title, sub: span };
    if (optionId === 'week' && group === 'skate') {
      return { title: k + ' ' + plural(k, 'каток', 'катка', 'катков') + ' на неделе', sub: 'массовое катание · ' + span };
    }
    return {
      title: n + ' ' + plural(n, 'сеанс', 'сеанса', 'сеансов') + ' ' + g.title,
      sub: (optionId === 'weekend' ? 'на выходных' : 'за неделю') + ' на ' + k + ' ' + plural(k, 'катке', 'катках', 'катках'),
    };
  }

  return {
    GROUPS: GROUPS,
    FIRST_ROWS: FIRST_ROWS,
    WEEKEND_TIMES: WEEKEND_TIMES,
    plural: plural,
    addDays: addDays,
    dayChip: dayChip,
    dayOptions: dayOptions,
    groupById: groupById,
    countFor: countFor,
    untilText: untilText,
    dayHeadline: dayHeadline,
    rangeHeadline: rangeHeadline,
    priceLine: priceLine,
    sessionHref: sessionHref,
    timeline: timeline,
    splitTimeline: splitTimeline,
    daysOfRange: daysOfRange,
    weekHeader: weekHeader,
    weekArenas: weekArenas,
    weekendArenas: weekendArenas,
    multiDayFeed: multiDayFeed,
  };
});
