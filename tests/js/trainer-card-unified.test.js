/**
 * TASK-400: единая карточка тренера в Mini App за флагом window.__UNIFIED_TRAINER_CARD__.
 * Стенд — настоящий trainer-showcase-main.js (helpers/trainer-showcase-harness.js), состояния — по доскам макета
 * (fixtures/trainer-card-states.js). Проверяем разметку: порядок блоков SPEC §3.1, условия «нет данных — нет блока»,
 * тексты §10, доступность §12. Флаг выключен — разметка побайтно та же, что до TASK-400.
 * Run: node --test tests/js/trainer-card-unified.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');
const { STATES } = require('./fixtures/trainer-card-states');

const RuText = require('../../static/webapp/ru-text.js');
const SNAPSHOT = require('./fixtures/trainer-card-flag-off.snapshot.json');

const slotsRoute = (slots, status = 200) => ({
  match: (c) => c.url.split('?')[0] === '/api/webapp/client/slots',
  reply: () => resp(status, { slots }),
});

async function open(key, opts = {}) {
  const st = STATES[key];
  const trainer = { ...st.trainer, ...(opts.trainer || {}) };
  const h = boot({
    unified: opts.unified !== false,
    search: '?trainer_id=' + trainer.id,
    initData: opts.initData === undefined ? 'x' : opts.initData,
    showcase: { items: [trainer] },
    routes: [slotsRoute(opts.slots || st.slots, opts.slotsStatus), ...(opts.routes || [])],
  });
  await tick(60);
  return h;
}

/** Рейтинг считает RuText (в браузере — ru-text.js на странице); в стенде подкладываем его и перерисовываем. */
function withRating(h) {
  h.ctx.RuText = RuText;
  h.ctx.__trainerShowcase.render();
  return h.app.innerHTML;
}

const order = (html, marks) => marks.map((m) => html.indexOf(m));
const strip = (html) => (/<ul class="tc-facts[^"]*"[^>]*>(.*?)<\/ul>/.exec(html) || [])[1] || '';
const facts = (html) => [...strip(html).matchAll(/<li><b>([^<]*)<\/b><span>([^<]*)<\/span><\/li>/g)].map((m) => m[1] + ' / ' + m[2]);
const FORBIDDEN = ['Время за вами', 'Если ответа не будет', 'Устанавливать ничего не нужно', 'Вы занимались', 'каталог', 'Ледовая арена «Замок»', 'Тренирует'];

describe('флаг выключен — карточка как раньше', () => {
  it('разметка всех состояний и списка побайтно совпадает со снимком 161bd810', async () => {
    for (const key of Object.keys(STATES)) {
      for (const initData of ['x', '']) {
        const h = await open(key, { unified: false, initData });
        assert.equal(h.app.innerHTML, SNAPSHOT[key + (initData ? '' : ':browser')], key + (initData ? '' : ' (браузер)'));
      }
    }
    const h = boot({ showcase: { items: Object.values(STATES).map((s) => s.trainer) } });
    await tick(60);
    assert.equal(h.app.innerHTML, SNAPSHOT.list, 'витрина');
  });
});

describe('единая карточка: порядок и условия показа (SPEC §3.1)', () => {
  it('A: герой → плашка → цена и время → О тренере → Образование → Где → Другие тарифы → Сохранить/Поделиться', async () => {
    const html = withRating(await open('A'));
    const pos = order(html, ['<h1>', 'class="tc-facts', 'tc-pc', '>О тренере<', '>Образование и дипломы<', '>Где проходят занятия<', '>Другие тарифы<', 'data-act="share"']);
    pos.forEach((p, i) => assert.ok(p > 0, 'есть блок #' + i));
    assert.deepEqual([...pos].sort((a, b) => a - b), pos, 'порядок блоков');
    assert.deepEqual(facts(html), ['7 лет / тренерского опыта', 'Любой возраст / учеников', '«Замок» / основной каток']);
    assert.match(html, /<h1>Анна Соколова<\/h1>/);
    assert.match(html, /<span role="img" aria-label="Оценка 4,9 из 5"><span class="tc-star" aria-hidden="true">★<\/span> 4,9<\/span> · 14 оценок · В Glide с сентября 2026/);
    assert.equal(html.match(/<h1/g).length, 1, 'один h1 — имя');
    for (const t of ['О тренере', 'Образование и дипломы', 'Где проходят занятия', 'Другие тарифы']) assert.match(html, new RegExp('<h2 class="tc-h2"[^>]*>' + t + '</h2>'));
  });

  it('A: тарифы плитками, время «сб, 10:00», «9:00» без нуля, главная кнопка с подписью', async () => {
    const html = (await open('A')).app.innerHTML;
    assert.match(html, /<small>Ребёнок<\/small><b>45 BYN<\/b>.*<small>Взрослый<\/small><b>50 BYN<\/b>/);
    assert.match(html, /<p class="tc-lb">60 мин · Замок · ближайшее время<\/p>/);
    const chips = [...html.matchAll(/class="tc-chip[^"]*" data-act="slot" data-slot="\d+">([^<]*)</g)].map((m) => m[1]);
    assert.deepEqual(chips, ['сб, 10:00', 'сб, 11:30', 'вс, 9:00'], 'до трёх окон');
    assert.match(html, /data-act="week">Другое время</);
    assert.match(html, /class="cta" data-act="slot" data-slot="101">Записаться на сб, 10:00<\/button>/);
    assert.match(html, /<small>Анна подтвердит — сообщение придёт в Telegram<\/small>/);
    assert.match(html, /<div class="tc-seg" role="group" aria-label="Занятие">/);
    assert.match(html, /data-key="s-nulya" aria-pressed="true">С нуля</);
  });

  it('одинаковые цены — по-прежнему две плитки (SPEC §5.1)', async () => {
    const t = STATES.A.trainer;
    const same = { ...t.services[0], price_tiers: [{ id: 1, tier_kind: 'child', price_cents: 5000 }, { id: 2, tier_kind: 'adult', price_cents: 5000 }] };
    const html = (await open('A', { trainer: { services: [same] } })).app.innerHTML;
    assert.equal((html.match(/<b>50 BYN<\/b>/g) || []).length >= 2, true);
    assert.match(html, /<small>Ребёнок<\/small>.*<small>Взрослый<\/small>/);
  });

  it('B: без фото — типографский герой без инициалов; плашка «12 лет · Дети · от 50 BYN»; одна цена строкой', async () => {
    const html = (await open('B')).app.innerHTML;
    assert.match(html, /tc-hero--noph tc-hero--hockey/);
    assert.doesNotMatch(html, /class="noph"|<i>Д<\/i>/, 'инициалов в кружке нет');
    assert.match(html, /<span class="tc-cap">С клюшкой<\/span><h1>Дмитрий Петров<\/h1>/);
    assert.deepEqual(facts(html), ['12 лет / тренерского опыта', 'Дети / учеников', 'от 50 BYN / за занятие']);
    assert.match(html, /<div class="tc-one"><span>Хоккейное катание<\/span><b>50 BYN<\/b><\/div>/);
    assert.match(html, /<p class="tc-lb">Ближайшее время<\/p><span>60 мин · Чижовка-Арена<\/span>/);
  });

  it('C: окон нет — сообщение, «Сообщить, когда появится время»; внизу «Написать тренеру» главная, «Оставить заявку» вторая', async () => {
    const html = (await open('C')).app.innerHTML;
    assert.match(html, /<p class="tc-empty-t">На ближайшие 2 недели свободного времени нет<\/p>/);
    assert.match(html, /data-act="notify">.*Сообщить, когда появится время<\/button>/);
    assert.match(html, /<div class="ft col tc-ft"><button type="button" class="cta" data-act="write">Написать тренеру<\/button><button type="button" class="sec2" data-act="request">Оставить заявку<\/button>/);
    assert.doesNotMatch(html, /часто открывает/);
    assert.ok(html.indexOf('tc-pc') < html.indexOf('>О тренере<'), 'время — сразу после плашки (PDEC-036)');
  });

  it('F: без онлайн-записи карточки цены нет; «Оставить заявку» главная с подписью, «Написать тренеру» вторичная', async () => {
    const html = (await open('F')).app.innerHTML;
    assert.doesNotMatch(html, /tc-pc|data-act="slot"|tc-chip/);
    assert.match(html, /<div class="ft col tc-ft"><button type="button" class="cta" data-act="request">Оставить заявку<\/button><small>Ответ придёт в Telegram<\/small><button type="button" class="sec2" data-act="write">Написать тренеру<\/button>/);
  });

  it('дыры в данных не сдвигают оставшиеся секции (позиции, не подстрока)', async () => {
    const bare = STATES.M2.trainer;
    const html = (await open('M2', {
      trainer: {
        ...bare,
        description: '',
        education: '',
        services: [{ ...bare.services[0], price_tiers: [{ id: 1, tier_kind: 'adult', price_cents: 5000 }] }],
      },
    })).app.innerHTML;
    const marks = ['<h1>', 'class="tc-facts', ' tc-pc"', 'class="tc-sec" data-act="save"', 'class="ft col tc-ft"'];
    const pos = order(html, marks);
    pos.forEach((p, i) => assert.ok(p >= 0, 'нет секции #' + i));
    assert.deepEqual([...pos].sort((a, b) => a - b), pos);
    assert.doesNotMatch(html, />О тренере<|>Образование и дипломы<|>Другие тарифы<|>О занятии<|>Отзывы<|>На занятиях</);
  });

  it('«О занятии» стоит между «О тренере» и «Образование», когда есть текст услуги', async () => {
    const svc = { ...STATES.A.trainer.services[0], description: 'Сначала учимся падать.' };
    const html = (await open('A', { trainer: { services: [svc] } })).app.innerHTML;
    const pos = order(html, ['>О тренере<', '>О занятии<', '>Образование и дипломы<', '>Где проходят занятия<', '>Другие тарифы<']);
    pos.forEach((p) => assert.ok(p >= 0));
    assert.deepEqual([...pos].sort((a, b) => a - b), pos);
  });

  it('пустое не выводим: нет описания/образования/«двое» — нет блоков; <2 фактов — нет плашки', async () => {
    const html = (await open('M2', { trainer: { primary_arena_name: null } })).app.innerHTML;
    assert.doesNotMatch(html, />О тренере<|>Образование и дипломы<|>Другие тарифы<|>Отзывы<|>На занятиях</);
    assert.equal(strip(html), '', 'один факт («Любой возраст») — плашки нет');
    assert.doesNotMatch(html, /tc-facts/);
    const two = (await open('M2')).app.innerHTML;
    assert.deepEqual(facts(two), ['Любой возраст / учеников', '«ЛДС» / основной каток']);
    assert.match(two, /tc-facts tc-facts--2/);
  });

  it('M3 несколько катков — площадка в чипе; M5 группа — «осталось 3 места»; M4 онлайн — строка про ссылку', async () => {
    const m3 = (await open('M3')).app.innerHTML;
    assert.match(m3, /сб, 10:00<small>Замок<\/small>/);
    assert.match(m3, /сб, 16:00<small>Чижовка<\/small>/);
    assert.match(m3, /60 мин · 2 катка · ближайшее время/);
    const m5 = (await open('M5')).app.innerHTML;
    assert.match(m5, /вс, 11:00<small>осталось 3 места<\/small>/);
    const m4 = (await open('M4')).app.innerHTML;
    assert.match(m4, /45 мин · онлайн/);
    assert.match(m4, /Ссылку пришлёт тренер после подтверждения\. Билет и прокат не нужны\./);
    assert.doesNotMatch(m4, />Где проходят занятия</, 'онлайн — без катка и проката');
  });

  it('строка героя — «направления · город», город только если есть', async () => {
    const withCity = (await open('A', { trainer: { city_name: 'Минск' } })).app.innerHTML;
    assert.match(withCity, /<p class="tc-hero-sub">С нуля · Уже катаюсь · Минск<\/p>/);
    const nasty = (await open('A', { trainer: { city_name: '<img src=x onerror=alert(1)>' } })).app.innerHTML;
    assert.match(nasty, /С нуля · Уже катаюсь · &lt;img src=x onerror=alert\(1\)&gt;/);
    const noCity = (await open('A')).app.innerHTML;
    assert.match(noCity, /<p class="tc-hero-sub">С нуля · Уже катаюсь<\/p>/);
    const bare = (await open('B', { trainer: { city_name: 'Минск' } })).app.innerHTML;
    assert.match(bare, /<span class="tc-cap">С клюшкой<\/span><h1>Дмитрий Петров<\/h1><p class="tc-hero-sub">Минск · «Чижовка-Арена»<\/p>/);
    const bareNoCity = (await open('B')).app.innerHTML;
    assert.match(bareNoCity, /<h1>Дмитрий Петров<\/h1><p class="tc-hero-sub">«Чижовка-Арена»<\/p>/);
  });

  it('вид спорта с сервера заменяет названия вкладок; нет вида — строка прежняя', async () => {
    const a = (await open('A', { trainer: { sport_name: 'Фигурное катание', city_name: 'Минск' } })).app.innerHTML;
    assert.match(a, /<p class="tc-hero-sub">Фигурное катание · Минск<\/p>/);
    assert.doesNotMatch(a, /<p class="tc-hero-sub">[^<]*С нуля/);
    const noCity = (await open('C', { trainer: { sport_name: 'Фигурное катание', city_name: null } })).app.innerHTML;
    assert.match(noCity, /<p class="tc-hero-sub">Фигурное катание<\/p>/);
    assert.doesNotMatch(noCity, /Фигурное катание ·/);
    const f = (await open('F', { trainer: { sport_name: 'Хоккей', city_name: 'Брест' } })).app.innerHTML;
    assert.match(f, /<p class="tc-hero-sub">Хоккей · Брест<\/p>/);
    const cap = (await open('B', { trainer: { sport_name: 'Хоккей', city_name: 'Минск' } })).app.innerHTML;
    assert.match(cap, /<span class="tc-cap">Хоккей<\/span>/);
    assert.doesNotMatch(cap, /<span class="tc-cap">С клюшкой<\/span>/);
    const mixed = (await open('A', { trainer: { sport_name: null, city_name: 'Минск' } })).app.innerHTML;
    assert.match(mixed, /<p class="tc-hero-sub">С нуля · Уже катаюсь · Минск<\/p>/);
  });

  it('герой с фото: A  без класса 400, C и F — tc-hero--tall, B без фото — 300', async () => {
    const a = (await open('A')).app.innerHTML;
    assert.match(a, /<header class="tc-hero tc-hero--photo">/);
    assert.doesNotMatch(a, /tc-hero--tall/);
    const c = (await open('C')).app.innerHTML;
    assert.match(c, /<header class="tc-hero tc-hero--photo tc-hero--tall">/);
    const f = (await open('F')).app.innerHTML;
    assert.match(f, /<header class="tc-hero tc-hero--photo tc-hero--tall">/);
    const b = (await open('B')).app.innerHTML;
    assert.match(b, /tc-hero--noph/);
    assert.doesNotMatch(b, /tc-hero--tall/);
  });

  it('«Где проходят занятия» берёт публичное имя, иначе сырое', async () => {
    const quoted = (await open('A')).app.innerHTML;
    assert.match(quoted, /<span class="tc-where-t"><b>«Замок»<\/b>/);
    const pub = (await open('C', { trainer: { arenas: [{ ...STATES.C.trainer.arenas[0], public_name: 'ЛДС' }] } })).app.innerHTML;
    assert.match(pub, /<span class="tc-where-t"><b>ЛДС<\/b>/);
    const raw = (await open('F')).app.innerHTML;
    assert.match(raw, /<span class="tc-where-t"><b>Ледовая арена «Брест»<\/b>/);
  });

  it('«О занятии» есть только при тексте услуги или заметке тренера', async () => {
    const empty = (await open('A')).app.innerHTML;
    assert.doesNotMatch(empty, />О занятии</);
    const svc = STATES.A.trainer.services[0];
    const note = (await open('A', { trainer: { services: [{ ...svc, client_notice: 'Коньки свои' }] } })).app.innerHTML;
    assert.match(note, /<h2 class="tc-h2"[^>]*>О занятии<\/h2>/);
    assert.match(note, /Заметка тренера/);
    assert.match(note, /Коньки свои/);
    const words = (await open('A', { trainer: { services: [{ ...svc, description: 'Сначала учимся падать.' }] } })).app.innerHTML;
    assert.match(words, />О занятии</);
    assert.match(words, /Сначала учимся падать\./);
    assert.doesNotMatch(words, /Заметка тренера/);
  });

  it('M6 нет цены — «Цену уточните у тренера»; M7 несколько направлений — все вкладки', async () => {
    const m6 = (await open('M6')).app.innerHTML;
    assert.match(m6, /<b>Цену уточните у тренера<\/b>/);
    assert.doesNotMatch(m6, /согласовани/);
    const m7 = (await open('M7')).app.innerHTML;
    assert.deepEqual([...m7.matchAll(/data-act="dir" data-key="[^"]+" aria-pressed="[^"]+">([^<]+)</g)].map((m) => m[1]), ['С нуля', 'Уже катаюсь', 'С клюшкой']);
  });

  it('ошибка загрузки времени — «Не удалось загрузить время» и «Повторить»; выход внизу остаётся', async () => {
    const html = (await open('A', { slotsStatus: 500 })).app.innerHTML;
    // TASK-401 (доска States 1): строка «Проверьте сеть…» и «Повторить» / «Написать» в ряд.
    assert.match(html, /Не удалось загрузить время<\/p><p class="tc-empty-p">Проверьте сеть и повторите\. Тренеру можно и написать\.<\/p><div class="tc-l1-acts"><button type="button" class="tc-sec tc-sec--main" data-act="reslots">Повторить<\/button>/);
    assert.match(html, /class="ft col tc-ft"><button type="button" class="cta" data-act="write">Написать тренеру/);
  });

  it('тексты: нет запрещённых формулировок §10, нет «Тренирует N лет» в герое, нет счётчика занятий', async () => {
    for (const key of Object.keys(STATES)) {
      const html = withRating(await open(key));
      for (const bad of FORBIDDEN) assert.ok(!html.includes(bad), key + ': «' + bad + '»');
      assert.doesNotMatch(html, /\d+ (занятие|занятия|занятий)\b(?! ·)/, key + ': счётчик занятий');
    }
  });
});

describe('единая карточка: доступность и действия (SPEC §12, ENTRIES №53)', () => {
  it('сердце на фото и кнопка внизу — aria-pressed; «Поделиться тренером» только в Telegram', async () => {
    const html = (await open('A')).app.innerHTML;
    assert.match(html, /class="tc-hbtn tc-hbtn--save" data-act="save" aria-label="Сохранить тренера" aria-pressed="false"/);
    assert.match(html, /class="tc-sec" data-act="save" aria-pressed="false">♡ Сохранить тренера</);
    assert.match(html, /data-act="share">.*Поделиться тренером<\/button>/);
    const browser = (await open('A', { initData: '' })).app.innerHTML;
    assert.doesNotMatch(browser, /data-act="share"|data-act="save"/);
    assert.doesNotMatch(browser, /подтвердит — сообщение придёт в Telegram/, 'вне Telegram подписи про подтверждение нет');
  });

  it('«Поделиться тренером» — тот же API, что у старой карточки, и лист Telegram', async () => {
    const shared = [];
    const h = await open('A', { routes: [{
      match: (c) => c.url.split('?')[0] === '/api/webapp/client/share-trainer/1',
      reply: () => resp(200, { share_url: 'https://glideclub.by/t/1-anna?via=share', share_body: 'Тренер Анна', share_text: 'x' }),
    }] });
    h.ctx.openTelegramShareUrlFromMiniApp = (o) => shared.push(o);
    h.click({ 'data-act': 'share' });
    await tick();
    const call = h.calls.find((c) => c.url.startsWith('/api/webapp/client/share-trainer/1'));
    assert.match(call.url, /share_context=catalog/);
    assert.deepEqual(JSON.parse(JSON.stringify(shared)), [{ shareUrl: 'https://glideclub.by/t/1-anna?via=share', shareBody: 'Тренер Анна', fullMessage: 'x' }]);
  });

  it('«Читать полностью» раскрывает текст и не возвращается после перерисовки', async () => {
    const h = await open('A');
    assert.match(h.app.innerHTML, /data-act="bio-more"[^>]*hidden>Читать полностью/, 'скрыта, пока не измерили обрезку');
    h.click({ 'data-act': 'bio-more' });
    assert.match(h.app.innerHTML, /<p class="tc-bio open" id="tcBio">/);
    h.ctx.__trainerShowcase.render();
    assert.doesNotMatch(h.app.innerHTML, /data-act="bio-more"/);
  });

  it('прямая ссылка: пока грузится — скелетон карточки, а не скелетон списка', () => {
    const h = boot({ unified: true, search: '?trainer_id=1', showcase: { items: [STATES.A.trainer] } });
    assert.match(h.app.innerHTML, /class="tc tc--sk" aria-busy="true"/);
  });
});

describe('стили: токены и шкала радиусов (SPEC §11)', () => {
  const css = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/trainer-showcase.css'), 'utf8');
  const block = css.slice(css.indexOf('/* ── Единая карточка тренера'));
  const rules = block.slice(block.indexOf('.tc {'));

  it('в правилах карточки нет прямых цветов — только var(--g-*) и локальные --tc-* из одного места', () => {
    assert.doesNotMatch(rules, /#[0-9a-fA-F]{3,8}\b/);
    assert.doesNotMatch(rules, /rgba?\(/);
  });

  it('радиусы — токены шкалы 12/14/16/18/20 (и капсула)', () => {
    const radii = [...rules.matchAll(/border-radius:\s*([^;]+);/g)].map((m) => m[1].trim());
    assert.ok(radii.length > 5);
    for (const r of radii) assert.match(r, /^var\(--g-r(-sm|-md|-lg|-card|-btn|-pill)?\)$/, r);
  });
});
