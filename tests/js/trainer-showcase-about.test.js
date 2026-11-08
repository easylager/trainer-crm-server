/**
 * Подача услуг в карточке тренера: крючок в тёмной карточке, «О занятии» (наш текст, слова тренера, «Не входит в цену»).
 * Run: node --test tests/js/trainer-showcase-about.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');
const M = require('../../static/webapp/trainer-showcase-model.js');

const tiers = [{ id: 1, tier_kind: 'child', price_cents: 5000 }, { id: 2, tier_kind: 'adult', price_cents: 5500 }];
const svc = (id, name, extra = {}) => ({
  service_id: id, service_name: name, title: name, is_public: true, is_online: false, currency_code: 'BYN',
  price_cents: 5000, price_tiers: tiers, summary_hook: '', summary_body: '', client_notice: null, description: null, ...extra,
});
const trainer = (services, extra = {}) => ({
  id: 1, name: 'Анна', first_name: 'Анна', can_book: true, services, arenas: [{ id: 3, name: 'Каток' }], windows: [], ...extra,
});
const noSlots = { match: (c) => c.url.split('?')[0] === '/api/webapp/client/slots', reply: () => resp(200, { slots: [] }) };

async function open(items, tab) {
  const h = boot({ showcase: { items }, routes: [noSlots] });
  await tick();
  h.click({ 'data-act': 'trainer', 'data-tid': 1 });
  await tick();
  if (tab) { h.click({ 'data-act': 'dir', 'data-key': tab }); await tick(); }
  return h;
}

describe('noticeParts / serviceAbout (модель)', () => {
  it('снимает «В стоимость не входят:» и поднимает первую букву', () => {
    assert.deepEqual(M.noticeParts('В стоимость не входят: прокат коньков (при необходимости), билеты на лёд.'),
      { lead: true, text: 'Прокат коньков (при необходимости), билеты на лёд.' });
    assert.deepEqual(M.noticeParts('В цену не входит — прокат'), { lead: true, text: 'Прокат' });
  });
  it('чужая заметка остаётся дословно и без вводной подписи', () => {
    assert.deepEqual(M.noticeParts('Нужна своя экипировка.'), { lead: false, text: 'Нужна своя экипировка.' });
    assert.equal(M.noticeParts('  '), null);
    assert.equal(M.noticeParts(null), null);
  });
  it('пустые данные — нет блока', () => {
    assert.equal(M.serviceAbout(svc(1, 'С нуля')), null);
    assert.equal(M.serviceAbout(null), null);
  });
});

describe('карточка тренера: подача услуг', () => {
  it('«С нуля»: крючок в тёмной карточке над ценами, «О занятии» — крючок, подробности, слова тренера, не входит в цену', async () => {
    const s = svc(1, 'С нуля', {
      summary_hook: 'Если вы почти не стояли на льду — это про вас.', summary_body: 'Учимся стоять, падать и тормозить.',
      description: 'Работаю мягко.', client_notice: 'В стоимость не входят: прокат коньков, билеты на лёд.',
    });
    const h = await open([trainer([s, svc(2, 'Уже катаюсь', { summary_hook: 'Другой крючок.' })])]);
    const html = h.app.innerHTML;
    const pc = html.slice(html.indexOf('class="pc"'), html.indexOf('</div></div>', html.indexOf('class="tiers"')));
    assert.ok(pc.indexOf('class="hk"') >= 0 && pc.indexOf('class="hk"') < pc.indexOf('class="tiers"'));
    assert.ok(pc.includes('Если вы почти не стояли на льду'));
    assert.ok(!pc.includes('Другой крючок'));
    assert.match(html, /<h4>О занятии<\/h4>/);
    assert.match(html, /<p class="abh">Если вы почти не стояли на льду — это про вас\.<\/p>/);
    assert.ok(html.includes('<p>Учимся стоять, падать и тормозить.</p>'));
    assert.ok(html.includes('<blockquote class="words"><p>Работаю мягко.</p><cite>Слова тренера</cite></blockquote>'));
    assert.ok(html.includes('<span>Не входит в цену</span>Прокат коньков, билеты на лёд.'));
    assert.ok(!html.includes('В стоимость не входят'));
    assert.equal((html.match(/Работаю мягко\./g) || []).length, 1);
  });

  it('вкладка «Уже катаюсь» показывает текст своей услуги, а не «С нуля»', async () => {
    const h = await open([trainer([svc(1, 'С нуля', { summary_hook: 'Крючок нуля.' }), svc(2, 'Уже катаюсь', { summary_hook: 'Крючок катающихся.' })])], 'uzhe-katayus');
    assert.ok(h.app.innerHTML.includes('Крючок катающихся.'));
    assert.ok(!h.app.innerHTML.includes('Крючок нуля.'));
  });

  it('«С клюшкой»: radiogroup из двух строк без крючков; деталь выбранной один раз; «О занятии» выбранной', async () => {
    const a = svc(4, 'Хоккейное катание', { summary_hook: 'Крючок А.', summary_body: 'Тело А.' });
    const b = svc(6, 'ОХМ(отработка)', { title: 'ОХМ — отработка', summary_hook: 'Крючок Б.', price_tiers: [{ id: 3, tier_kind: 'child', price_cents: 4500 }, { id: 4, tier_kind: 'adult', price_cents: 5500 }] });
    const h = await open([trainer([a, b])], 's-klyushkoy');
    let html = h.app.innerHTML;
    assert.match(html, /role="radiogroup"/);
    assert.equal((html.match(/role="radio"/g) || []).length, 2);
    assert.equal((html.match(/aria-checked="true"/g) || []).length, 1);
    assert.ok(html.includes('ОХМ — отработка'));
    // строки без крючков и больших цен; деталь — один раз
    const group = html.slice(html.indexOf('role="radiogroup"'), html.indexOf('</div>', html.indexOf('role="radiogroup"')));
    assert.ok(!group.includes('Крючок') && !group.includes('class="tiers"'));
    assert.ok(group.includes('50 BYN') && group.includes('от 45 BYN'));
    assert.equal((html.match(/class="hk"/g) || []).length, 1);
    assert.equal((html.match(/class="tiers"/g) || []).length, 1);
    assert.match(html, /class="hk">Крючок А\./);
    // выбор строки меняет деталь
    h.click({ 'data-act': 'svc', 'data-sid': 6 });
    await tick();
    html = h.app.innerHTML;
    assert.match(html, /class="hk">Крючок Б\./);
    assert.ok(!/class="hk">Крючок А/.test(html));
    assert.equal(h.S.serviceId, 6);
    assert.ok(html.includes('<b>45 BYN</b>') && html.includes('<b>55 BYN</b>'));
    assert.equal((html.match(/class="abt"/g) || []).length, 1);
  });

  it('цены Ребёнок = Взрослый — одна строка «Дети и взрослые»', async () => {
    const eq = [{ id: 1, tier_kind: 'child', price_cents: 5000 }, { id: 2, tier_kind: 'adult', price_cents: 5000 }];
    const h = await open([trainer([svc(1, 'С нуля', { price_tiers: eq })])]);
    const html = h.app.innerHTML;
    assert.ok(html.includes('<small>Дети и взрослые</small><b>50 BYN</b>'));
    assert.ok(!html.includes('<small>Ребёнок</small>'));
    assert.deepEqual(M.priceRows(svc(1, 'x', { price_tiers: eq })).map((r) => r.title), ['Дети и взрослые']);
    assert.equal(M.priceFrom(svc(1, 'x', { price_tiers: eq })), '50 BYN');
    assert.equal(M.priceFrom(svc(1, 'x')), 'от 50 BYN');
  });

  it('S.dirKey никогда не null: список «Все» → время, по ссылке, по слоту', async () => {
    const t = trainer([svc(1, 'С нуля'), svc(4, 'Хоккейное катание'), svc(6, 'ОХМ')], { windows: [{ slot_id: 77, starts_at: '2026-11-10T10:00:00', ends_at: '2026-11-10T10:45:00', arena_id: 3 }] });
    const h = await open([t]);
    assert.equal(h.S.dirKey, 's-nulya');
    const h2 = boot({ search: '?trainer_id=1', showcase: { items: [t] }, routes: [noSlots] });
    await tick(80);
    assert.equal(h2.S.dirKey, 's-nulya');
    // тап по времени в списке на вкладке «Все» → «Назад» в карточку: направление закреплено
    const h3 = boot({ showcase: { items: [t] }, routes: [noSlots] });
    await tick();
    assert.equal(h3.S.tab, 'all');
    h3.click({ 'data-act': 'win', 'data-tid': 1, 'data-slot': 77 });
    await tick(80);
    assert.equal(h3.S.view, 'trainer');
    assert.equal(h3.S.dirKey, 's-nulya');
    assert.ok(!h3.app.innerHTML.includes('role="radiogroup"'));
  });

  it('одна услуга — название не повторяем; нет крючка — блока нет', async () => {
    const h = await open([trainer([svc(1, 'С нуля')])]);
    const html = h.app.innerHTML;
    assert.ok(!html.includes('class="hk"'));
    assert.ok(!html.includes('О занятии'));
    assert.ok(!html.includes('class="abt"'));
    assert.ok(!html.includes('Какое занятие?'));
  });

  it('своя услуга: только слова тренера, без нашего текста', async () => {
    const own = svc(1, 'С нуля', { is_public: false, description: 'Мои слова.' });
    const h = await open([trainer([own])]);
    const html = h.app.innerHTML;
    assert.ok(html.includes('<cite>Слова тренера</cite>'));
    assert.ok(!html.includes('class="abh"') && !html.includes('class="hk"'));
  });

  it('экран «без онлайн-записи» тоже показывает «О занятии»', async () => {
    const s = svc(1, 'С нуля', { summary_hook: 'Крючок.', description: 'Слова.' });
    const h = await open([trainer([s], { can_book: false })]);
    assert.match(h.app.innerHTML, /<h4>О занятии<\/h4>/);
    assert.ok(h.app.innerHTML.includes('Крючок.'));
  });

  it('экранирует <, & и кавычки-ёлочки в наших текстах и словах тренера', async () => {
    const s = svc(1, 'С нуля', {
      summary_hook: 'A <b>x</b> & «y»', summary_body: '1 < 2 & 3', description: '<script>alert(1)</script> «да»', client_notice: 'Прокат <i>&</i>',
    });
    const h = await open([trainer([s])]);
    const html = h.app.innerHTML;
    assert.ok(!html.includes('<script>') && !html.includes('<b>x</b>') && !html.includes('<i>&'));
    assert.ok(html.includes('A &lt;b&gt;x&lt;/b&gt; &amp; «y»'));
    assert.ok(html.includes('1 &lt; 2 &amp; 3'));
    assert.ok(html.includes('&lt;script&gt;'));
  });
});
