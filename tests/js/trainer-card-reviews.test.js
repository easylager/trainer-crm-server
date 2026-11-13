/**
 * TASK-416: «Отзывы» и «На занятиях» единой карточки тренера (SPEC §3.1 №8–9, доска A и тёмная A).
 * Стенд — настоящий trainer-showcase-main.js; данные приходят из выдачи витрины (подменённый fetch,
 * адрес запроса проверяем). Порог отзывов — 3 текста; фото — помимо героя. Флаг выключен — блоков нет.
 * Run: TZ=UTC node --test tests/js/trainer-card-reviews.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');
const { STATES } = require('./fixtures/trainer-card-states');
const M = require('../../static/webapp/trainer-showcase-model.js');
const RuText = require('../../static/webapp/ru-text.js');

const LONG = 'Ходим к Анне второй сезон. Первое занятие было спокойным: привыкали ко льду, учились падать и вставать. ' +
  'Сын боялся льда, через месяц катается сам и просится ещё. Анна объясняет просто и не торопит, на каждом занятии ' +
  'что-то новое: торможение, повороты, шаг назад. Рекомендуем всем, кто начинает с нуля.';
const REVIEWS = [
  { name: 'Марк М.', rating: 5, text: LONG, date: '2026-11-02' },
  { name: 'Елена К.', rating: 5, text: 'Спокойно и понятно, дочь довольна.', date: '2026-10-28' },
  { name: 'Игорь Т.', rating: 4, text: 'Хорошо поставили торможение.', date: '2026-10-19' },
];
const PHOTOS = ['/api/public/photos/trainers/1/p1.jpg', '/api/public/photos/trainers/1/p2.jpg', '/api/public/photos/trainers/1/p3.jpg'];

const slotsRoute = (slots) => ({
  match: (c) => c.url.split('?')[0] === '/api/webapp/client/slots',
  reply: () => resp(200, { slots }),
});

async function open(key, trainer = {}, opts = {}) {
  const st = STATES[key];
  const t = { ...st.trainer, ...trainer };
  const h = boot({
    unified: opts.unified !== false,
    search: '?trainer_id=' + t.id,
    initData: opts.initData === undefined ? 'x' : opts.initData,
    showcase: { items: [t] },
    routes: [slotsRoute(st.slots)],
  });
  await tick(60);
  h.ctx.RuText = RuText;
  h.ctx.__trainerShowcase.render();
  return h;
}

const showcaseCall = (h) => h.calls.find((c) => c.url.split('?')[0] === '/api/public/trainer-showcase');
const sec = (html, id) => {
  const i = html.indexOf('aria-labelledby="' + id + '"');
  if (i < 0) return '';
  const start = html.lastIndexOf('<section', i);
  return html.slice(start, html.indexOf('</section>', i) + '</section>'.length);
};

describe('модель: порог, дата, звёзды, начало отзыва', () => {
  it('reviewsShown: от трёх текстов; пустые тексты не считаются', () => {
    assert.equal(M.REVIEWS_MIN_SHOWN, 3);
    assert.deepEqual(M.reviewsShown(null), []);
    assert.deepEqual(M.reviewsShown(REVIEWS.slice(0, 2)), []);
    assert.equal(M.reviewsShown(REVIEWS).length, 3);
    assert.deepEqual(M.reviewsShown([...REVIEWS.slice(0, 2), { name: 'Х', rating: 5, text: '   ' }]), []);
  });

  it('reviewDate: «2 ноября 2026»; мусор — пусто', () => {
    assert.equal(M.reviewDate('2026-11-02'), '2 ноября 2026');
    assert.equal(M.reviewDate('2026-01-31'), '31 января 2026');
    assert.equal(M.reviewDate(null), '');
    assert.equal(M.reviewDate('2026-13-01'), '');
  });

  it('reviewStars: закрашенные + пустые до пяти', () => {
    assert.equal(M.reviewStars(5), '★★★★★');
    assert.equal(M.reviewStars(4), '★★★★☆');
    assert.equal(M.reviewStars(4.9), '★★★★★');
    assert.equal(M.reviewStars(1), '★☆☆☆☆');
  });

  it('reviewPreview: до 220 знаков по границе слова с «…»; короткий — как есть', () => {
    assert.deepEqual(M.reviewPreview('Коротко.'), { text: 'Коротко.', cut: false });
    const p = M.reviewPreview(LONG);
    assert.equal(p.cut, true);
    assert.ok(p.text.length <= 221, 'длина ' + p.text.length);
    assert.ok(p.text.endsWith('…'));
    assert.ok(LONG.startsWith(p.text.slice(0, -1)), 'начало дословно');
    assert.equal(M.reviewPreview('а'.repeat(220)).cut, false, 'ровно 220 — целиком');
  });
});

describe('«Отзывы» на карточке (SPEC §3.1 №8)', () => {
  it('три текста: заголовок h2, сводка как в герое, лента из трёх карточек, подпись про проверку', async () => {
    const h = await open('A', { reviews: REVIEWS });
    assert.match(showcaseCall(h).url, /^\/api\/public\/trainer-showcase(\?city_id=\d+)?$/, 'данные — из выдачи витрины');
    const html = h.app.innerHTML;
    const s = sec(html, 'tcRevH');
    assert.ok(s, 'блок есть');
    assert.match(s, /<h2 class="tc-h2" id="tcRevH">Отзывы<\/h2>/);
    assert.match(s, /<div class="tc-rev-sum"><b>4,9<\/b><div><span class="tc-rev-stars" role="img" aria-label="Рейтинг 4,9 из 5">★★★★★<\/span><span>14 оценок<\/span><\/div><\/div>/);
    assert.equal((s.match(/<article class="tc-rev">/g) || []).length, 3);
    assert.match(s, /<b>Марк М\.<\/b><span class="tc-rev-stars" role="img" aria-label="5 из 5">★★★★★<\/span>/);
    assert.match(s, /<b>Игорь Т\.<\/b><span class="tc-rev-stars" role="img" aria-label="4 из 5">★★★★☆<\/span>/);
    assert.match(s, /<time datetime="2026-11-02">2 ноября 2026<\/time>/);
    assert.match(s, /<div class="tc-lane tc-rev-lane" role="region" aria-label="Отзывы учеников" tabindex="0">/);
    assert.match(s, /<p class="tc-note tc-rev-note">Тексты отзывов проверяем перед публикацией\.<\/p>/);
    assert.doesNotMatch(s, /Каждый отзыв|оставляют только те, кто занимался/, 'SPEC §10');
    assert.doesNotMatch(s, /\[|\]/, 'без заглушек макета');
  });

  it('порядок: Другие тарифы → Отзывы → На занятиях → Сохранить', async () => {
    const html = (await open('A', { reviews: REVIEWS, class_photos: PHOTOS })).app.innerHTML;
    const pos = ['>Другие тарифы<', '>Отзывы<', '>На занятиях<', 'class="tc-sec" data-act="save"'].map((m) => html.indexOf(m));
    pos.forEach((p, i) => assert.ok(p > 0, 'есть #' + i));
    assert.deepEqual([...pos].sort((a, b) => a - b), pos);
  });

  for (const n of [0, 1, 2]) {
    it(n + ' текст(а) — блока нет, оценка только в герое', async () => {
      const html = (await open('A', { reviews: REVIEWS.slice(0, n) })).app.innerHTML;
      assert.doesNotMatch(html, />Отзывы<|tc-revs|tc-rev-sum|Тексты отзывов проверяем/);
      assert.match(html, /aria-label="Оценка 4,9 из 5"/, 'рейтинг в герое остался');
    });
  }

  it('reviews = null (сервер: меньше трёх) — блока нет', async () => {
    const html = (await open('A', { reviews: null })).app.innerHTML;
    assert.doesNotMatch(html, />Отзывы<|tc-revs/);
  });

  it('без оценки в профиле — лента без сводки', async () => {
    const s = sec((await open('A', { reviews: REVIEWS, rating_avg: null, rating_count: 0 })).app.innerHTML, 'tcRevH');
    assert.ok(s);
    assert.doesNotMatch(s, /tc-rev-sum/);
    assert.equal((s.match(/<article class="tc-rev">/g) || []).length, 3);
  });

  it('длинный отзыв: начало и «Читать полностью»; по нажатию — целиком, кнопка не возвращается', async () => {
    const h = await open('A', { reviews: REVIEWS });
    let s = sec(h.app.innerHTML, 'tcRevH');
    assert.match(s, /<p id="tcRev0">[^<]*…<\/p><button type="button" class="tc-link" data-act="rev-more" data-i="0" aria-controls="tcRev0" aria-expanded="false">Читать полностью<\/button>/);
    assert.equal((s.match(/data-act="rev-more"/g) || []).length, 1, 'у коротких кнопки нет');
    h.click({ 'data-act': 'rev-more', 'data-i': '0' });
    s = sec(h.app.innerHTML, 'tcRevH');
    assert.ok(s.includes('<p id="tcRev0">' + LONG + '</p>'));
    assert.doesNotMatch(s, /data-act="rev-more"/);
    h.ctx.__trainerShowcase.render();
    assert.doesNotMatch(h.app.innerHTML, /data-act="rev-more"/);
  });

  it('текст и имя экранируются; нет имени — «Ученик»; нет даты — без строки даты', async () => {
    const rows = [{ name: '', rating: 5, text: '<b>жирно</b>', date: null }, ...REVIEWS.slice(1)];
    const s = sec((await open('A', { reviews: rows })).app.innerHTML, 'tcRevH');
    assert.match(s, /<b>Ученик<\/b>/);
    assert.match(s, /&lt;b&gt;жирно&lt;\/b&gt;/);
    assert.equal((s.match(/<time /g) || []).length, 2);
  });

  it('браузер без Telegram — блок тот же', async () => {
    const html = (await open('A', { reviews: REVIEWS }, { initData: '' })).app.innerHTML;
    assert.ok(sec(html, 'tcRevH'));
  });
});

describe('«На занятиях» (SPEC §3.1 №9)', () => {
  it('фото помимо героя — лента с h2, по фото на элемент, lazy', async () => {
    const h = await open('A', { class_photos: PHOTOS });
    const s = sec(h.app.innerHTML, 'tcGalH');
    assert.match(s, /^<section class="tc-gal" aria-labelledby="tcGalH"><h2 class="tc-h2" id="tcGalH">На занятиях<\/h2><ul class="tc-lane tc-gal-lane" aria-label="Фото с занятий" tabindex="0">/);
    assert.equal((s.match(/<li><img src="\/api\/public\/photos\/trainers\/1\/p\d\.jpg" alt="Фото с занятия \d из 3" loading="lazy" decoding="async"><\/li>/g) || []).length, 3);
  });

  it('нет фото помимо героя — блока нет (пусто, null, только герой)', async () => {
    const hero = STATES.A.trainer.photo_url;
    for (const class_photos of [[], null, undefined, [hero], ['']]) {
      const html = (await open('A', { class_photos })).app.innerHTML;
      assert.doesNotMatch(html, />На занятиях<|tc-gal/, JSON.stringify(class_photos));
    }
  });

  it('одно фото помимо героя — блок есть; повтор героя и дубли отброшены', async () => {
    const hero = STATES.A.trainer.photo_url;
    const s = sec((await open('A', { class_photos: [hero, PHOTOS[0], PHOTOS[0]] })).app.innerHTML, 'tcGalH');
    assert.equal((s.match(/<li>/g) || []).length, 1);
    assert.match(s, /alt="Фото с занятия 1 из 1"/);
  });

  it('без фото героя (B) — фото занятий всё равно показываем', async () => {
    const s = sec((await open('B', { class_photos: PHOTOS.slice(0, 1) })).app.innerHTML, 'tcGalH');
    assert.ok(s);
  });
});

describe('флаг выключен — новых блоков нет', () => {
  it('те же данные в выдаче, а разметка без «Отзывы»/«На занятиях»', async () => {
    for (const initData of ['x', '']) {
      const h = await open('A', { reviews: REVIEWS, class_photos: PHOTOS }, { unified: false, initData });
      assert.match(showcaseCall(h).url, /^\/api\/public\/trainer-showcase(\?city_id=\d+)?$/);
      assert.doesNotMatch(h.app.innerHTML, /tc-revs|tc-gal|tc-rev|Тексты отзывов проверяем|На занятиях/);
    }
  });
});
