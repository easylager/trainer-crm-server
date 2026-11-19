/**
 * «Кто кого» — право капитана и экипировка (TASK-432, холст «Право капитана», Ava.dc.html).
 * Коллекция «Экипировка капитана», рисунки вещей данными (viewBox 0–100 поверх аватара), тексты и аватар с вещью.
 * Модель без DOM проверяет tests/js/kto-kogo-kit.test.js; аватар (K.kitAva) регистрируется только в браузере.
 * Слова: капитан, экипировка, выдать. Не «наряд», не «звезда», не «скин». Тексты нейтральны по роду.
 */
(function (global) {
  'use strict';

  var NBSP = ' ';

  /** Коллекция: порядок как в выборе, ключ — как у сервера (OUTFITS). Все бесплатно, без категорий. */
  var OUTFITS = [
    { id: 'wanted', name: 'Розыск', full: 'Плакат «Разыскивается»', joke: 'За ходы мимо. Вознаграждение — кепка. Счёт на плакате — его собственный.' },
    { id: 'half', name: 'Полушарф', full: 'Полушарф', joke: 'Половина — своя команда, половина — соперник. И нашим, и вашим.' },
    { id: 'bag', name: 'Пакет', full: 'Пакет на голову', joke: 'Классика трибун: стыдно, но досмотреть надо.' },
    { id: 'sieve', name: 'Решето', full: 'Маска-решето', joke: 'Пропускает всё. Как ходы этого вечера.' },
    { id: 'scorehat', name: 'Табло', full: 'Шапка-табло', joke: 'Счёт матча, на котором всё пошло не так. Горит над головой весь день.' },
    { id: 'snorkel', name: 'Трубка', full: 'Маска с трубкой', joke: 'Для тех, кто на дне таблицы. Дышать есть чем.' },
    { id: 'hardhat', name: 'Каска', full: 'Каска «Ремонт»', joke: 'Чутьё закрыто на ремонт. Временно угадываем наугад.' },
    { id: 'curlers', name: 'Бигуди', full: 'Бигуди', joke: 'Полдня собираться к матчу — и ноль из четырёх.' },
    { id: 'foil', name: 'Фольга', full: 'Корона из фольги', joke: 'Почти как настоящая. Настоящую дают в конце месяца.' },
    { id: 'bucket', name: 'Ведро', full: 'Ведро вместо шлема', joke: 'Шлем по уровню чутья. Звенит, если постучать.' },
  ];
  var CAP = { id: 'cap', name: 'Кепка', full: 'Кепка дня', joke: '' };

  function outfit(id) {
    if (id === 'cap') return CAP;
    for (var i = 0; i < OUTFITS.length; i += 1) if (OUTFITS[i].id === id) return OUTFITS[i];
    return null;
  }

  var INK = '#0d1424';

  /**
   * Рисунки вещей: [тег, атрибуты, текст]. Координаты — в квадрате аватара 0–100, вещь может выходить за него
   * (плакат, ведро, трубка). Текст '{stat}' и '{score}' — цифры из вечера получателя.
   */
  var SHAPES = {
    cap: [
      ['g', { transform: 'translate(-2 -16) scale(1.6)' }, null, [
        ['path', { d: 'M10 32 C10 14 20 6 32 6 C44 6 52 14 52 32 Z', fill: '#ffd23f', stroke: INK, 'stroke-width': '2' }],
        ['path', { d: 'M30 32 H61 C62 36 58 39 51 39 H30 Z', fill: '#ffd23f', stroke: INK, 'stroke-width': '2' }],
        ['path', { d: 'M32 6 V31', stroke: '#c9a21a', 'stroke-width': '1.6' }],
        ['circle', { cx: '32', cy: '6', r: '2.4', fill: INK }],
      ]],
    ],
    half: [
      ['path', { d: 'M6 70 Q28 82 50 84 L50 99 Q28 97 6 85 Z', fill: '#1f5fa8', stroke: INK, 'stroke-width': '3' }],
      ['path', { d: 'M50 84 Q72 82 94 70 L94 85 Q72 97 50 99 Z', fill: '#c8102e', stroke: INK, 'stroke-width': '3' }],
      ['path', { d: 'M18 75 L25 78 L25 92 L18 89 Z M36 80 L43 82 L43 96 L36 94 Z', fill: '#ffffff' }],
      ['path', { d: 'M57 82 L64 80 L64 94 L57 96 Z M75 78 L82 75 L82 89 L75 92 Z', fill: '#ffffff' }],
      ['path', { d: 'M50 82 V101', stroke: INK, 'stroke-width': '2.5', 'stroke-dasharray': '3 3' }],
      ['path', { d: 'M28 92 L22 118 L34 120 L40 94 Z', fill: '#1f5fa8', stroke: INK, 'stroke-width': '3' }],
      ['path', { d: 'M60 94 L66 120 L78 118 L72 92 Z', fill: '#c8102e', stroke: INK, 'stroke-width': '3' }],
      ['path', { d: 'M23 121 L22 126 M28 122 L28 127 M33 122 L34 127 M67 122 L66 127 M72 122 L72 127 M77 121 L78 126', stroke: INK, 'stroke-width': '2.5', 'stroke-linecap': 'round' }],
    ],
    bag: [
      ['path', { d: 'M4 22 L96 22 L100 108 L0 108 Z', fill: '#c9a36a', stroke: INK, 'stroke-width': '3.5' }],
      ['path', { d: 'M4 22 L10 12 L16 22 L22 12 L28 22 L34 12 L40 22 L46 12 L52 22 L58 12 L64 22 L70 12 L76 22 L82 12 L88 22 L94 12 L96 22 Z', fill: '#b48c55', stroke: INK, 'stroke-width': '3' }],
      ['ellipse', { cx: '34', cy: '54', rx: '9', ry: '7', fill: INK }],
      ['ellipse', { cx: '66', cy: '54', rx: '9', ry: '7', fill: INK }],
      ['path', { d: 'M38 80 Q50 72 62 80', fill: 'none', stroke: INK, 'stroke-width': '3', 'stroke-linecap': 'round' }],
      ['path', { d: 'M14 34 L18 98 M86 34 L82 98', stroke: '#a8844d', 'stroke-width': '2.5' }],
    ],
    sieve: [
      ['path', { d: 'M18 28 Q50 2 82 28 L79 70 Q50 98 21 70 Z', fill: '#f4f6f8', stroke: INK, 'stroke-width': '3.5' }],
      ['ellipse', { cx: '37', cy: '40', rx: '8', ry: '6', fill: INK }],
      ['ellipse', { cx: '63', cy: '40', rx: '8', ry: '6', fill: INK }],
      ['circle', { cx: '30', cy: '58', r: '4', fill: INK }], ['circle', { cx: '44', cy: '62', r: '4.5', fill: INK }],
      ['circle', { cx: '58', cy: '60', r: '3.5', fill: INK }], ['circle', { cx: '70', cy: '56', r: '4', fill: INK }],
      ['circle', { cx: '38', cy: '76', r: '3.5', fill: INK }], ['circle', { cx: '52', cy: '80', r: '4', fill: INK }],
      ['circle', { cx: '64', cy: '73', r: '3', fill: INK }], ['circle', { cx: '50', cy: '20', r: '3', fill: INK }],
      ['circle', { cx: '28', cy: '28', r: '2.5', fill: INK }], ['circle', { cx: '72', cy: '27', r: '3', fill: INK }],
    ],
    scorehat: [
      ['circle', { cx: '50', cy: '-14', r: '8', fill: '#e5484d', stroke: INK, 'stroke-width': '3' }],
      ['rect', { x: '12', y: '-6', width: '76', height: '36', rx: '6', fill: '#0b0f14', stroke: INK, 'stroke-width': '3.5' }],
      ['rect', { x: '16', y: '-2', width: '68', height: '28', rx: '3', fill: '#161c25' }],
      ['text', { x: '50', y: '20', 'text-anchor': 'middle', 'font-size': '22', 'font-weight': '900', 'letter-spacing': '1', fill: '#ffb020' }, '{score}'],
      ['rect', { x: '4', y: '28', width: '92', height: '9', rx: '4', fill: '#e5484d', stroke: INK, 'stroke-width': '3' }],
    ],
    wanted: [
      ['path', { 'fill-rule': 'evenodd', d: 'M-16 -26 H116 V130 H-16 Z M50 6 A44 44 0 1 0 50.1 6 Z', fill: '#ead7a8', stroke: '#6b4e2e', 'stroke-width': '3' }],
      ['text', { x: '50', y: '-9', 'text-anchor': 'middle', 'font-size': '12.5', 'font-weight': '900', 'letter-spacing': '.5', fill: '#4a3218' }, 'РАЗЫСКИВАЕТСЯ'],
      ['text', { x: '50', y: '121', 'text-anchor': 'middle', 'font-size': '13', 'font-weight': '900', fill: '#b42318' }, '{stat}'],
    ],
    snorkel: [
      ['path', { d: 'M2 46 Q50 34 98 46', fill: 'none', stroke: INK, 'stroke-width': '5' }],
      ['rect', { x: '16', y: '30', width: '68', height: '34', rx: '12', fill: '#7dd3fc', 'fill-opacity': '.85', stroke: INK, 'stroke-width': '3.5' }],
      ['path', { d: 'M50 30 V64', stroke: INK, 'stroke-width': '3' }],
      ['path', { d: 'M24 38 L32 36', stroke: '#ffffff', 'stroke-width': '3', 'stroke-linecap': 'round' }],
      ['path', { d: 'M92 52 V2 a7 7 0 0 1 14 0 V6', fill: 'none', stroke: '#f97316', 'stroke-width': '8', 'stroke-linecap': 'round' }],
      ['path', { d: 'M92 52 Q92 70 74 74', fill: 'none', stroke: '#f97316', 'stroke-width': '8', 'stroke-linecap': 'round' }],
      ['circle', { cx: '112', cy: '-8', r: '3.5', fill: 'none', stroke: '#7dd3fc', 'stroke-width': '2' }],
      ['circle', { cx: '106', cy: '-18', r: '2.5', fill: 'none', stroke: '#7dd3fc', 'stroke-width': '2' }],
    ],
    hardhat: [
      ['path', { d: 'M2 46 Q4 -18 50 -20 Q96 -18 98 46 Z', fill: '#facc15', stroke: INK, 'stroke-width': '3.5' }],
      ['path', { d: 'M50 -20 V46', stroke: INK, 'stroke-width': '3' }],
      ['path', { d: 'M30 -14 Q22 10 22 46 M70 -14 Q78 10 78 46', fill: 'none', stroke: '#d9a90b', 'stroke-width': '3' }],
      ['rect', { x: '-10', y: '42', width: '120', height: '13', rx: '5', fill: '#facc15', stroke: INK, 'stroke-width': '3.5' }],
      ['rect', { x: '14', y: '8', width: '72', height: '20', rx: '3', fill: '#ffffff', stroke: INK, 'stroke-width': '2.5' }],
      ['text', { x: '50', y: '23.5', 'text-anchor': 'middle', 'font-size': '14', 'font-weight': '900', 'letter-spacing': '.5', fill: INK }, 'РЕМОНТ'],
    ],
    curlers: [
      ['rect', { x: '6', y: '14', width: '22', height: '14', rx: '6', fill: '#f472b6', stroke: INK, 'stroke-width': '3', transform: 'rotate(-30 17 21)' }],
      ['rect', { x: '26', y: '0', width: '22', height: '14', rx: '6', fill: '#a78bfa', stroke: INK, 'stroke-width': '3', transform: 'rotate(-10 37 7)' }],
      ['rect', { x: '52', y: '0', width: '22', height: '14', rx: '6', fill: '#f472b6', stroke: INK, 'stroke-width': '3', transform: 'rotate(10 63 7)' }],
      ['rect', { x: '72', y: '14', width: '22', height: '14', rx: '6', fill: '#a78bfa', stroke: INK, 'stroke-width': '3', transform: 'rotate(30 83 21)' }],
      ['path', { d: 'M14 21 H20 M34 7 H40 M60 7 H66 M80 21 H86', stroke: INK, 'stroke-width': '2', 'stroke-linecap': 'round' }],
    ],
    foil: [
      ['path', { d: 'M12 34 L18 0 L32 18 L44 -8 L56 16 L68 -6 L76 16 L88 2 L90 34 Z', fill: '#d6dde6', stroke: INK, 'stroke-width': '3.5' }],
      ['path', { d: 'M24 26 L30 20 L34 28 M46 22 L52 12 L58 24 M66 26 L72 18', fill: 'none', stroke: '#8a96a6', 'stroke-width': '2' }],
      ['circle', { cx: '44', cy: '-8', r: '4', fill: '#e5484d', stroke: INK, 'stroke-width': '2' }],
      ['circle', { cx: '68', cy: '-6', r: '3.5', fill: '#22c55e', stroke: INK, 'stroke-width': '2' }],
      ['path', { d: 'M80 8 L84 4', stroke: '#ffffff', 'stroke-width': '3', 'stroke-linecap': 'round' }],
    ],
    bucket: [
      ['path', { d: 'M22 4 Q50 -34 78 4', fill: 'none', stroke: INK, 'stroke-width': '3.5', 'stroke-linecap': 'round' }],
      ['path', { d: 'M18 4 H82 L90 50 H10 Z', fill: '#aab6c4', stroke: INK, 'stroke-width': '3.5' }],
      ['path', { d: 'M14 26 H86', stroke: '#7d8a9b', 'stroke-width': '3' }],
      ['rect', { x: '6', y: '46', width: '88', height: '10', rx: '4', fill: '#c7d0db', stroke: INK, 'stroke-width': '3.5' }],
      ['path', { d: 'M30 12 L26 40', stroke: '#e6ecf2', 'stroke-width': '4', 'stroke-linecap': 'round' }],
      ['circle', { cx: '18', cy: '6', r: '3.5', fill: INK }],
      ['circle', { cx: '82', cy: '6', r: '3.5', fill: INK }],
    ],
  };

  /** Сколько вещь выходит за круг аватара (в долях размера): столько места строке нужно сверху и снизу. */
  var REACH = { wanted: [0.26, 0.3], half: [0, 0.27], bag: [0, 0.08], scorehat: [0.22, 0], snorkel: [0.22, 0], hardhat: [0.2, 0], foil: [0.12, 0], bucket: [0.17, 0], cap: [0.11, 0], curlers: [0.04, 0], sieve: [0, 0] };

  function reach(id) {
    return REACH[id] || [0, 0];
  }

  /** Подставить цифры вечера в текст рисунка. Пусто — убрать строку. */
  function fill(textValue, head) {
    if (textValue === '{stat}') return (head && head.stat) || '';
    if (textValue === '{score}') return (head && head.score) || '';
    return textValue;
  }

  // ---------- тексты ----------

  /** Подпись для экранного диктора: что на голове. */
  function headSay(head) {
    var o = head && outfit(head.item);
    if (!o) return '';
    return head.item === 'cap' ? 'в кепке дня' : 'экипировка: ' + o.full.toLowerCase();
  }

  /**
   * Цифры вещи из вечера человека — как у сервера: «ЗА 0 ИЗ 4» и счёт первого промаха (нет — первого матча без
   * хода, иначе последнего). Нужны, чтобы вещь упала на голову сразу, до ответа сервера.
   */
  function numbers(r, ev) {
    var ms = (ev && ev.matches) || [];
    var marks = (r && r.marks) || [];
    function first(state) {
      for (var i = 0; i < ms.length; i += 1) if ((marks[i] ? marks[i].state : 'none') === state) return i;
      return -1;
    }
    var at = first('miss');
    if (at < 0) at = first('none');
    if (at < 0) at = ms.length - 1;
    var m = ms[at];
    return {
      stat: 'ЗА ' + ((r && r.hits) || 0) + ' ИЗ ' + ms.length,
      score: m && m.home_score != null && m.away_score != null ? m.home_score + ':' + m.away_score : '',
    };
  }

  /** Кто может выдать: «себе», «в кепке» или «2 из 4» — подпись в выборе «Кому». */
  function targetSub(r, ev) {
    if (r.is_me) return 'себе';
    if (r.cap) return 'в кепке';
    return (r.hits || 0) + ' из ' + (((ev && ev.matches) || []).length);
  }

  /** Кого выбрать сразу: того, кто в кепке (не себя), иначе первого не себя, иначе себя. */
  function defaultTarget(items) {
    var list = items || [];
    var pick = list.filter(function (r) { return r.cap && !r.is_me; })[0] || list.filter(function (r) { return !r.is_me; })[0] || list[0];
    return pick ? pick.pid : null;
  }

  /** Строка под строкой участника: чья экипировка. Мне выдал не я — об этом говорит плашка сверху. */
  function headNote(r, ev) {
    var head = r && r.head;
    var award = ev && ev.captain && ev.captain.award;
    if (!head || head.item === 'cap' || !award || award.to !== r.pid) return '';
    var o = outfit(head.item);
    if (!o) return '';
    if (award.from_me) return r.is_me ? 'Твой выбор — до следующего вечера' : 'Экипировка от тебя — до следующего вечера';
    if (r.is_me && award.current) return '';
    return o.full + (award.current ? ' — выдаёт ' + award.from : ' · от капитана вечера');
  }

  /** Плашка получателю: выдал другой капитан, вечер ещё действует. */
  function receivedBanner(ev) {
    var award = ev && ev.captain && ev.captain.award;
    if (!award || award.from_me || !award.current) return null;
    var me = ((ev && ev.items) || []).filter(function (r) { return r.is_me; })[0];
    if (!me || me.pid !== award.to) return null;
    var o = outfit(award.item);
    return {
      title: award.from + ' выдаёт тебе экипировку',
      text: (o ? o.full : 'Экипировка') + ' — до следующего вечера. Видят все в «КТО КОГО», и в общей таблице тоже.',
      tail: 'Стань капитаном — и выдавать будешь ты.',
    };
  }

  /** Право капитана после выдачи: «Олег в экипировке» и что именно. */
  function givenLine(r, item) {
    var o = outfit(item);
    return {
      title: r && r.is_me ? 'Ты в экипировке' : (r ? r.display_name : '') + ' в экипировке',
      text: (o ? o.full : 'Экипировка') + ' — до следующего вечера. Видят все в «КТО КОГО».',
    };
  }

  /** Строка выбранного в праве капитана: «0 из 4 · кепка дня» / «4 из 4 · капитан». */
  function targetLine(r, ev) {
    if (!r) return '';
    var n = ((ev && ev.matches) || []).length;
    return (r.hits || 0) + ' из ' + n + (r.cap ? ' · кепка дня' : r.captain ? ' · капитан' : '');
  }

  var FEW = { 2: 'двух', 3: 'трёх', 4: 'четырёх', 5: 'пяти' };

  /** Снаружи лиги, в строке: «Ведро вместо шлема · от капитана лиги» / «… и ещё 1 · от капитанов лиг». */
  function outsideNote(o) {
    if (!o) return '';
    var first = outfit(o.item);
    if (!first) return '';
    var total = (o.items || []).reduce(function (s, x) { return s + (x.n || 1); }, 0);
    if (total < 2) return first.full + ' · от капитана лиги';
    return first.full + ' и ещё ' + (total - 1) + ' · от капитанов лиг';
  }

  /** Список по тапу на аватар (снаружи лиги): одна вещь из нескольких лиг — «от двух капитанов». */
  function outsideList(o) {
    return ((o && o.items) || []).map(function (x) {
      var it = outfit(x.item);
      if (!it) return null;
      return { id: x.item, full: it.full, stat: x.stat || '', score: x.score || '', from: x.n > 1 ? 'от ' + (FEW[x.n] || x.n) + NBSP + 'капитанов лиг' : 'от капитана лиги' };
    }).filter(Boolean);
  }

  /** Раздел «Капитан» в шторке правил. */
  function captainRules() {
    return {
      lead: 'Капитан — лучший за вечер. У него право выдать экипировку',
      items: [
        { k: 'Кто капитан.', t: 'У кого больше всех очков за ход среди тех, кто в споре за кепку. Как кепка дня, только наоборот.' },
        { k: 'Что может.', t: 'Выдать одну вещь за вечер любому в лиге — даже себе. Вещь и того, кому она досталась, можно поменять до следующего вечера.' },
        { k: 'Сколько носят.', t: 'До следующего сыгранного вечера лиги. Пока экипировки нет, на голове у худшего — кепка дня.' },
        { k: 'Где видно.', t: 'На аватаре в лиге и в общей таблице «КТО КОГО». Снаружи пишем «от капитана лиги» — без названия лиги.' },
        { k: 'Ничья.', t: 'Лучших несколько — капитанов тоже. Выдаёт тот, кто успеет первым.' },
      ],
      collectionTitle: 'Экипировка капитана',
      collectionNote: 'Все ' + OUTFITS.length + ' вещей — у каждого капитана, бесплатно. Смеёмся над ходом, а не над человеком.',
    };
  }

  var api = {
    OUTFITS: OUTFITS,
    SHAPES: SHAPES,
    outfit: outfit,
    reach: reach,
    fill: fill,
    numbers: numbers,
    headSay: headSay,
    targetSub: targetSub,
    defaultTarget: defaultTarget,
    headNote: headNote,
    receivedBanner: receivedBanner,
    givenLine: givenLine,
    targetLine: targetLine,
    outsideNote: outsideNote,
    outsideList: outsideList,
    captainRules: captainRules,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.KtoKogoKit = api;

  // ---------- аватар с экипировкой (только браузер) ----------

  var K = global.KK;
  if (!K || typeof document === 'undefined') return;
  var SVG_NS = 'http://www.w3.org/2000/svg';

  function draw(parent, nodes, head) {
    nodes.forEach(function (n) {
      var el = document.createElementNS(SVG_NS, n[0]);
      Object.keys(n[1]).forEach(function (k) { el.setAttribute(k, n[1][k]); });
      if (n[0] === 'text') {
        el.setAttribute('font-family', 'Golos Text, system-ui, sans-serif');
        el.textContent = fill(n[2], head);
      }
      if (n[3]) draw(el, n[3], head);
      parent.appendChild(el);
    });
  }

  /**
   * Аватар с вещью на голове и нашивкой «C» у капитана. opts: head {item, stat, score}, captain, cls (класс круга),
   * dropAt — время выдачи для анимации падения (продолжается при перерисовке, как жесты TASK-431), style — класс обёртки.
   */
  function kitAva(name, size, opts) {
    var o = opts || {};
    var head = o.head && SHAPES[o.head.item] ? o.head : null;
    var kids = [K.ava(name, size, o.cls)];
    if (head) {
      var svg = document.createElementNS(SVG_NS, 'svg');
      svg.setAttribute('viewBox', '0 0 100 100');
      svg.setAttribute('class', 'kk-kit__svg');
      svg.setAttribute('aria-hidden', 'true');
      var g = document.createElementNS(SVG_NS, 'g');
      g.setAttribute('stroke-linejoin', 'round');
      if (o.dropAt) {
        g.setAttribute('class', 'kk-kit__drop');
        g.setAttribute('style', '--kk-mo:-' + Math.max(0, Date.now() - o.dropAt) + 'ms');
      }
      draw(g, SHAPES[head.item], head);
      svg.appendChild(g);
      kids.push(svg);
    }
    if (o.captain) kids.push(K.h('span', { class: 'kk-kit__c', 'aria-hidden': 'true', text: 'C' }));
    var say = [headSay(head), o.captain ? 'капитан' : ''].filter(Boolean).join(', ');
    if (say) kids.push(K.h('span', { class: 'kk-vh', text: say }));
    var r = head ? reach(head.item) : [0, 0];
    return K.h('span', {
      class: 'kk-kit' + (o.wrap ? ' ' + o.wrap : ''),
      style: 'width:' + size + 'px;height:' + size + 'px;--kk-kit-up:' + Math.round(r[0] * size) + 'px;--kk-kit-down:' + Math.round(r[1] * size) + 'px',
    }, kids);
  }

  K.kitAva = kitAva;
  K.Kit = api;
})(typeof window !== 'undefined' ? window : globalThis);
