/**
 * Страница «Семья» (TASK-387): модель людей, значение общего доступа, добавление близкого,
 * разводка страницы и переход из «Я».
 * Run: node --test tests/js/client-family-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../..');
const webapp = path.join(ROOT, 'static/webapp');
globalThis.RuPersonName = require(path.join(webapp, 'ru-person-name.js'));
globalThis.ClientNameSheet = require(path.join(webapp, 'client-name-sheet.js'));
const fam = require(path.join(webapp, 'client-family.js'));
const me = require(path.join(webapp, 'client-me.js'));
const NB = ' ';

function data(people) {
  return { name: 'Максим', rows: { family: { people } } };
}
const you = (active = true, id = 11) => ({ profile_id: id, name: 'Максим', is_you: true, active });
const kid = (name, id, active = false) => ({ profile_id: id, name, is_you: false, active });

describe('peopleModel', () => {
  it('Вы + дети: заголовки, подписи в родительном падеже, одна галочка', () => {
    const p = fam.peopleModel(data([you(false), kid('Аня', 12, true), kid('Миша', 13)]));
    assert.deepEqual(p.map((x) => x.title), ['Вы', 'Аня', 'Миша']);
    assert.deepEqual(p.map((x) => x.subtitle), ['Максим', 'Занятия и записи' + NB + 'Ани', 'Занятия и записи' + NB + 'Миши']);
    assert.deepEqual(p.map((x) => x.active), [false, true, false]);
    assert.deepEqual(p.map((x) => x.profileId), [11, 12, 13]);
  });

  it('никто не отмечен — выбран «Вы»; несколько отмеченных — только первый', () => {
    assert.deepEqual(fam.peopleModel(data([you(false), kid('Аня', 12)])).map((x) => x.active), [true, false]);
    assert.deepEqual(fam.peopleModel(data([you(true), kid('Аня', 12, true)])).map((x) => x.active), [true, false]);
  });

  it('без детей — один «Вы»; нет своей карточки (profile_id null) — выбор null', () => {
    const p = fam.peopleModel(data([{ profile_id: null, name: 'Максим', is_you: true, active: true }]));
    assert.equal(p.length, 1);
    assert.equal(p[0].profileId, null);
    assert.equal(p[0].active, true);
  });

  it('безымянный близкий — «Близкий»; латиница не склоняется; в UI нет «профиль» и «ребёнок»', () => {
    const p = fam.peopleModel(data([you(), kid(null, 12), kid('Dasha', 13)]));
    assert.equal(p[1].title, 'Близкий');
    assert.equal(p[1].subtitle, 'Занятия и записи');
    assert.equal(p[2].subtitle, 'Занятия и записи' + NB + 'Dasha');
    const all = JSON.stringify(p);
    assert.doesNotMatch(all, /профил|ребён|ребен/i);
  });

  it('старая схема (rows.family.profiles) и пустой список — null', () => {
    assert.equal(fam.peopleModel({ name: 'М', rows: { family: { profiles: 2 } } }), null);
    assert.equal(fam.peopleModel(data([])), null);
    assert.equal(fam.peopleModel(null), null);
  });

  it('withActive: ровно один выбранный; чужой ключ ничего не меняет', () => {
    const p = fam.peopleModel(data([you(), kid('Аня', 12)]));
    const next = fam.withActive(p, 'p12');
    assert.deepEqual(next.map((x) => x.active), [false, true]);
    assert.equal(fam.withActive(p, 'zzz'), p);
  });
});

describe('accessValue', () => {
  it('0 — «Не настроен», N — «N человек» со склонением, нет ответа — пусто', () => {
    assert.equal(fam.accessValue({ extra_members_count: 0 }), 'Не настроен');
    assert.equal(fam.accessValue({ extra_members_count: 1 }), '1' + NB + 'человек');
    assert.equal(fam.accessValue({ extra_members_count: 2 }), '2' + NB + 'человека');
    assert.equal(fam.accessValue({ extra_members_count: 5 }), '5' + NB + 'человек');
    assert.equal(fam.accessValue(null), '');
    assert.equal(fam.accessValue({}), '');
  });
});

describe('addPerson (шторка «Как зовут близкого?»)', () => {
  function deps(status, body, calls) {
    return {
      initData: 'init',
      fetch: (url, init) => {
        calls.push({ url, init });
        return Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) });
      },
    };
  }

  it('пустое и «пустое по Unicode» имя до сети не доходят', async () => {
    const calls = [];
    for (const raw of ['', '   ', '​\u0007']) {
      const res = await fam.addPerson(raw, deps(200, {}, calls));
      assert.equal(res.ok, false);
      assert.equal(res.message, 'Имя не может быть пустым');
    }
    assert.equal(calls.length, 0);
  });

  it('имя без буквы — своя подсказка и без сети', async () => {
    const calls = [];
    const res = await fam.addPerson('---', deps(200, {}, calls));
    assert.equal(res.ok, false);
    assert.match(res.message, /буква/);
    assert.equal(calls.length, 0);
  });

  it('успех: POST /client/profiles с first_name, init_data в заголовке, client_id в ответе', async () => {
    const calls = [];
    const res = await fam.addPerson('  Миша  ', deps(200, { client_id: 42 }, calls));
    assert.deepEqual(res, { ok: true, clientId: 42 });
    assert.equal(calls[0].url, '/api/webapp/client/profiles');
    assert.equal(calls[0].init.method, 'POST');
    assert.equal(calls[0].init.headers['X-Telegram-Init-Data'], 'init');
    assert.deepEqual(JSON.parse(calls[0].init.body), { first_name: 'Миша' });
  });

  it('дубликат: сервер вернул существующего — тот же client_id, строки не добавляются (модель списка не растёт)', async () => {
    const people = fam.peopleModel(data([you(), kid('Миша', 13)]));
    const res = await fam.addPerson('Миша', deps(200, { client_id: 13 }, []));
    assert.equal(res.clientId, 13);
    assert.ok(people.some((p) => p.profileId === res.clientId));
  });

  it('лимит 409 — текст сервера в шторку', async () => {
    const res = await fam.addPerson('Соня', deps(409, { detail: 'Достигнут лимит добавленных профилей.' }, []));
    assert.deepEqual(res, { ok: false, message: 'Достигнут лимит добавленных профилей.' });
  });

  it('500, битый JSON и сеть — «Не сохранилось»', async () => {
    const bad = { initData: '', fetch: () => Promise.resolve({ ok: false, status: 500, json: () => Promise.reject(new Error('x')) }) };
    assert.equal((await fam.addPerson('Соня', bad)).message, 'Не сохранилось. Попробуй ещё раз');
    const down = { initData: '', fetch: () => Promise.reject(new Error('net')) };
    assert.equal((await fam.addPerson('Соня', down)).message, 'Не сохранилось. Попробуй ещё раз');
  });
});

describe('разводка страницы и переход из «Я»', () => {
  const html = fs.readFileSync(path.join(webapp, 'client-family.html'), 'utf8');
  const appPy = fs.readFileSync(path.join(ROOT, 'src/api/app.py'), 'utf8');

  it('скрипты: переключатель и сезонный «назад» до страницы, шторка — раньше client-family.js, общая версия ассетов', () => {
    const order = ['client-season-back.js', 'client-profile-switcher.js', 'client-sheet.js', 'client-name-sheet.js', 'client-family.js'];
    const idx = order.map((n) => html.indexOf(n));
    idx.forEach((i, k) => assert.ok(i >= 0, order[k]));
    assert.deepEqual(idx.slice().sort((a, b) => a - b), idx);
    assert.match(html, /<button[^>]*id="btnBack"[^>]*data-season-back/);
    assert.match(html, /client-family\.css\?v=\d{9}/);
    assert.match(html, /client-family\.js\?v=\d{9}/);
  });

  it('маршруты /webapp/client-family(.js|.css) есть в app.py', () => {
    for (const r of ['/webapp/client-family"', '/webapp/client-family.js"', '/webapp/client-family.css"']) {
      assert.ok(appPy.includes('@app.get("' + r + ')'), r);
    }
  });

  it('строка «Семья» в «Я» ведёт на client-family, старая страница доступа остаётся целью «Общего доступа»', () => {
    const m = me.screenModel(
      { name: 'М', initial: 'М', city: null, club: null, home_arena: null, stats: {}, rows: { family: { people: [you(), kid('Аня', 12)] } }, profile_name: null },
      {}
    );
    const row = m.ice.rows.find((r) => r.key === 'family');
    assert.equal(row.href, 'client-family');
    assert.equal(row.value, 'Аня');
    assert.doesNotMatch(row.value, /ребён/i);
    const src = fs.readFileSync(path.join(webapp, 'client-family.js'), 'utf8');
    assert.match(src, /data-nav="client-family-access"/);
  });

  it('старый кэш «Я» (rows.family.profiles) страница не принимает', () => {
    assert.equal(fam.isUsable({ name: 'М', rows: { family: { profiles: 2 } } }), false);
  });
});
