/**
 * TASK-236: варианты шита «Поделиться» и адрес открытки.
 * Run: node --test tests/js/zovi-entry.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('path');
const vm = require('node:vm');
const { URL } = require('node:url');

const jsPath = path.resolve(__dirname, '../../static/webapp/mini-app-share-sheet.js');
const src = fs.readFileSync(jsPath, 'utf8');

function loadShareSheet() {
  const context = {
    URL,
    window: {},
    document: {
      createElement: () => ({
        hidden: true,
        className: '',
        innerHTML: '',
        addEventListener: () => {},
        querySelector: () => null,
      }),
      body: { appendChild: () => {} },
    },
    fetch: () => Promise.reject(new Error('no fetch')),
    location: { href: 'https://app.test/webapp/arena' },
    navigator: {},
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
  };
  context.window = context;
  vm.runInNewContext(src, context);
  return context.GlideShareSheet;
}

describe('варианты шита', () => {
  const sheet = loadShareSheet();
  const ice = { venueType: 'ice' };

  function labelsOf(sheetState) {
    return Array.from(sheet.variantsFor(sheetState), (variant) => variant.label);
  }

  it('у катка три варианта в этом порядке', () => {
    assert.deepEqual(labelsOf(ice), ['Погнали кататься', 'Открытка', 'Расписание']);
  });

  it('у не-катка открытки нет', () => {
    const labels = labelsOf({ venueType: 'shop' });
    assert.deepEqual(labels, ['Место', 'Позвать с собой']);
    assert.equal(labels.includes('Открытка'), false);
  });

  it('сеанс выбирается во всех трёх вариантах катка, у места без льда — нет', () => {
    const picks = (sheetState) =>
      Object.fromEntries(Array.from(sheet.variantsFor(sheetState), (variant) => [variant.id, variant.picksSession]));
    assert.deepEqual(picks(ice), { invite: true, postcard: true, schedule: true });
    assert.equal(picks({ venueType: 'shop' }).schedule, false);
  });

  it('у подборки переключателя нет', () => {
    assert.deepEqual(labelsOf({ endpoint: '/api/public/ice/selection/share', venueType: 'ice' }), []);
  });

  it('«Позвать» открывает «Погнали кататься», «Поделиться» — «Расписание»', () => {
    assert.equal(sheet.initialVariantId({ invite: true }), 'invite');
    assert.equal(sheet.initialVariantId({ invite: false }), 'schedule');
    const byId = Object.fromEntries(Array.from(sheet.variantsFor(ice), (variant) => [variant.id, variant.label]));
    assert.equal(byId.invite, 'Погнали кататься');
    assert.equal(byId.schedule, 'Расписание');
  });

  it('«Собрать компанию» — вторая вкладка, только когда сбор включён', () => {
    assert.deepEqual(labelsOf({ venueType: 'ice', company: true }), [
      'Погнали кататься',
      'Компания',
      'Открытка',
      'Расписание',
    ]);
    assert.equal(sheet.initialVariantId({ variant: 'company', company: true }), 'company');
    assert.equal(sheet.initialVariantId({ variant: 'company', company: false }), 'schedule');
  });

  it('на вкладке компании — как это работает, название компании и ник из Telegram, без порога', () => {
    const html = sheet.companyBottomHtml({
      venueType: 'ice',
      sessionId: '9001',
      companyForm: { team: 'Пивной Олимп', you: 'Макс', error: '' },
    });
    assert.doesNotMatch(html, /Сколько человек нужно|data-gss-cmin|порог|команд/i);
    // Владелец 2026-10-20: одно поле — подпись на карточке, не «команда».
    assert.match(html, /Название компании/);
    assert.match(html, /видно на карточке/);
    assert.match(html, /Отправить в чат/);
    assert.match(html, /data-gss-c="team"[^>]*value="Пивной Олимп"/);
    assert.match(html, /Вы в списке «Иду» как <b>Макс<\/b>/);
    assert.equal(html.includes('Как записать тебя'), false);
    assert.equal(html.includes('data-ch='), false);
    assert.equal(html.includes('type="number"'), false);
  });

  it('превью компании повторяет настоящую карточку: постер, подпись и кнопки столбиком', () => {
    const ice = sheet.companyPreviewHtml({
      venueType: 'ice',
      placeName: 'ТЦ DiaMond city',
      sessionId: '7',
      slotSections: [{ localDate: '2026-10-23', dayLabel: 'пт', rows: [{ id: 7, time: '21:15', meta: '14 BYN · ОХМ' }] }],
      companyForm: { team: '', you: 'Макс' },
    });
    // Картинка — та же, что сервер пришлёт в чат (og.render_company_card).
    assert.match(ice, /<img class="gss-cprev__img"[^>]*src="\/api\/public\/ice-companies\/preview\.png\?session_id=7&amp;you=%D0%9C%D0%B0%D0%BA%D1%81&amp;name="/);
    assert.match(ice, /Пятница, 21:15 · ТЦ DiaMond city/);
    assert.match(ice, /На льду Макс\./);
    assert.match(ice, /<i>Иду<\/i><i>Не могу<\/i><i>В другой чат →<\/i><i>На лёд ↗<\/i>/);
    assert.doesNotMatch(ice, /Может/);
    const match = sheet.companyPreviewHtml({
      match: { id: 11, title: 'Динамо-Минск — СКА', day: 'пт, 30 октября', time: '19:30' },
      placeName: 'Минск-Арена',
      companyForm: { team: 'Офис', you: 'Макс' },
    });
    assert.match(match, /<img class="gss-cprev__img gss-cprev__img--wide"[^>]*src="\/api\/public\/ice-companies\/preview\.png\?match_id=11&amp;you=%D0%9C%D0%B0%D0%BA%D1%81"/);
    assert.match(match, /Идём на матч\?/);
    assert.match(match, /Офис · Динамо-Минск — СКА · пт, 30 октября, 19:30 · Минск-Арена/);
    assert.match(match, /<i>Иду<\/i><i>Смотрю дома<\/i><i>Не смогу<\/i><i>Подробнее ↗<\/i>/);
  });

  it('после сбора карточка сразу в чате, ссылка отдельно', () => {
    const html = sheet.companyBottomHtml({
      companyForm: {
        min: '3',
        team: 'Команда',
        you: 'Макс',
        shared: true,
        created: { code: 'abc', pageUrl: 'https://x/k/abc', cardText: 'Катаемся в пятницу\nИдут 1 из 3: Макс' },
      },
    });
    assert.match(html, /Карточка в чате/);
    assert.match(html, /data-gss-cshare="copy"/);
    assert.equal(html.includes('Собрать компанию'), false);
    assert.equal(html.includes('data-gss-cshare="telegram"'), false);
  });

  const slotSections = [
    {
      dayLabel: 'Сегодня',
      localDate: '2026-10-12',
      dayNum: '12',
      rows: [
        { id: '9001', time: '20:00', meta: '11 BYN', kind: 'public_skate' },
        { id: '7', time: '21:15', meta: '14 BYN · ОХМ', kind: 'hockey_practice' },
      ],
    },
  ];

  it('открытка без сеанса — «Создать» неактивна', () => {
    const html = sheet.postcardBottomHtml({ venueType: 'ice', sessionId: null, zovi: {} });
    assert.match(html, /Создать открытку<\/button>/);
    assert.match(html, /disabled/);
    assert.equal(sheet.postcardReady({ venueType: 'ice', sessionId: null }), false);
    assert.equal(sheet.postcardReady({ venueType: 'ice', sessionId: '9001' }), true);
    assert.equal(sheet.postcardReady({ venueType: 'shop', sessionId: '9001' }), false);
  });

  it('открытка собирается в шите: поля имён, без перехода на /zovi', () => {
    const html = sheet.postcardBottomHtml({ venueType: 'ice', sessionId: '9001', zovi: { to: 'Лера', from: 'Макс' } });
    assert.match(html, /data-gss-z="to"[^>]*value="Лера"/);
    assert.match(html, /data-gss-z="from"[^>]*value="Макс"/);
    assert.equal(html.includes('/zovi?'), false);
    assert.equal(html.includes('disabled'), false);
  });

  it('готовая открытка — каналы отправки и «Изменить»', () => {
    const html = sheet.postcardBottomHtml({
      venueType: 'ice',
      sessionId: '9001',
      zovi: { to: 'Лера', from: 'Макс', created: { code: 'abcd2345', url: 'https://x/zovi/abcd2345' } },
    });
    assert.match(html, /data-zch="telegram"/);
    assert.match(html, /data-zch="copy"/);
    assert.match(html, /data-zch="system"/);
    assert.match(html, /data-gss-zedit/);
    assert.equal(html.includes('data-gss-z="to"'), false);
  });

  it('данные живой открытки — сеанс из шита, имена из полей, вид сеанса', () => {
    const base = { venueType: 'ice', placeName: 'Ледовый дворец', slotSections, zovi: { to: 'Лера', from: 'Макс' } };
    const skate = sheet.postcardInput({ ...base, sessionId: '9001' });
    assert.equal(skate.time, '20:00');
    assert.equal(skate.day, 'Пн, 12 окт');
    assert.equal(skate.place, 'Ледовый дворец');
    assert.equal(skate.kind, 'public_skate');
    assert.equal(skate.toName, 'Лера');
    assert.equal(skate.fromName, 'Макс');
    assert.equal(sheet.postcardInput({ ...base, sessionId: '7' }).kind, 'hockey_practice');
  });

  it('via — откуда позвали', () => {
    assert.equal(sheet.postcardVia({ context: 'ice_list' }), 'ice_list');
    assert.equal(sheet.postcardVia({ context: 'arena_card' }), 'arena_card');
  });
});
