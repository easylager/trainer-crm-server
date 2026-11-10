/**
 * TASK-361: «Кто кого», лицо лиги — картинка и строка «На что играем» (модель без DOM).
 *
 * Run: TZ=UTC node --test tests/js/kto-kogo-league-identity.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Id = require('../../static/webapp/kto-kogo-league-identity.js');

const WEBAPP = path.join(__dirname, '../../static/webapp');
const read = (f) => fs.readFileSync(path.join(WEBAPP, f), 'utf8');
const MB = 1024 * 1024;

describe('строка «На что играем»', () => {
  it('пробелы сжаты, края обрезаны, невидимые знаки убраны', () => {
    assert.equal(Id.cleanStake('  Пицца   на\nвсех '), 'Пицца на всех');
    assert.equal(Id.cleanStake('Кофе​ и‮ булочка'), 'Кофе и булочка');
    assert.equal(Id.cleanStake(null), '');
    assert.equal(Id.cleanStake('   '), '');
  });
  it('до 80 символов после сжатия пробелов', () => {
    assert.equal(Id.stakeError('я'.repeat(80)), '');
    assert.equal(Id.stakeError('я'.repeat(40) + '      ' + 'ю'.repeat(39)), '');
    assert.equal(Id.stakeError('я'.repeat(81)), 'Строка до 80 символов');
  });
  it('подпись и текст отдельно; нет строки — нет блока (прежний вид)', () => {
    assert.deepEqual(Id.stakeParts({ stake_text: ' Обед по пятницам ' }), { label: 'На что играем', text: 'Обед по пятницам' });
    assert.equal(Id.stakeParts({ stake_text: null }), null);
    assert.equal(Id.stakeParts({}), null);
    assert.equal(Id.stakeParts(null), null);
  });
  it('текст пользователя остаётся текстом: разметку не трогаем, экранирует вывод через textContent', () => {
    assert.equal(Id.stakeParts({ stake_text: '<img src=x onerror=alert(1)>' }).text, '<img src=x onerror=alert(1)>');
  });
});

describe('картинка лиги', () => {
  it('нет картинки — null; есть — основной и маленький кадр', () => {
    assert.equal(Id.faceOf({ image_url: null, image_thumb_url: null }), null);
    assert.equal(Id.faceOf({}), null);
    assert.deepEqual(Id.faceOf({ image_url: '/api/public/photos/kk-leagues/1/a.jpg', image_thumb_url: '/api/public/photos/kk-leagues/1/a_thumb.jpg' }), {
      src: '/api/public/photos/kk-leagues/1/a.jpg',
      thumb: '/api/public/photos/kk-leagues/1/a_thumb.jpg',
    });
    assert.deepEqual(Id.faceOf({ image_url: '/p/a.jpg' }), { src: '/p/a.jpg', thumb: '/p/a.jpg' });
  });
  it('в src попадают только свои адреса и http(s)', () => {
    for (const bad of ['javascript:alert(1)', 'data:text/html,<script>', '//evil.example/x.jpg', 'vbscript:x', '', 5, {}]) {
      assert.equal(Id.safeSrc(bad), null, String(bad));
    }
    assert.equal(Id.safeSrc('https://cdn.example/kk-leagues/1/a.jpg'), 'https://cdn.example/kk-leagues/1/a.jpg');
    assert.equal(Id.safeSrc('/api/public/photos/kk-leagues/1/a.jpg'), '/api/public/photos/kk-leagues/1/a.jpg');
    assert.equal(Id.faceOf({ image_url: 'javascript:alert(1)' }), null);
  });
  it('файл из галереи: тип и вес', () => {
    assert.equal(Id.imageError(null), '');
    assert.equal(Id.imageError({ type: 'image/jpeg', size: 5 * MB }), '');
    assert.equal(Id.imageError({ type: 'image/png', size: 1 }), '');
    assert.equal(Id.imageError({ type: 'image/webp', size: 1 }), '');
    assert.equal(Id.imageError({ type: 'image/jpeg', size: 5 * MB + 1 }), 'Фото больше 5 МБ. Выбери поменьше');
    assert.equal(Id.imageError({ type: 'image/gif', size: 10 }), 'Подходят только JPEG, PNG и WEBP');
    assert.equal(Id.imageError({ type: '', size: 10 }), 'Подходят только JPEG, PNG и WEBP');
    assert.equal(Id.imageError({ type: 'application/pdf', size: 10 }), 'Подходят только JPEG, PNG и WEBP');
  });
  it('новая лига: ошибка строки или картинки мешает создать, пустая форма — нет', () => {
    assert.equal(Id.identityError({ stake: '', image: null }), '');
    assert.equal(Id.identityError({ stake: 'я'.repeat(81), image: null }), 'Строка до 80 символов');
    assert.equal(Id.identityError({ stake: '', image: { type: 'image/gif', size: 1 } }), 'Подходят только JPEG, PNG и WEBP');
  });
});

describe('«Изменить лигу»: что отправлять', () => {
  const league = { name: 'Двор', stake_text: 'Кофе', image_url: '/p/a.jpg', image_thumb_url: '/p/a_t.jpg' };
  const same = { name: 'Двор', stake: 'Кофе', file: null, removeImage: false };

  it('ничего не поменяли — запросов нет', () => {
    assert.deepEqual(Id.editPlan(league, same), { patch: null, image: null, changed: false });
    assert.equal(Id.editPlan(league, { ...same, name: '  Двор ', stake: ' Кофе  ' }).changed, false);
  });
  it('в PATCH уходит только изменённое; пустая строка убирает «На что играем»', () => {
    assert.deepEqual(Id.editPlan(league, { ...same, name: 'Наш двор' }).patch, { name: 'Наш двор' });
    assert.deepEqual(Id.editPlan(league, { ...same, stake: 'Чай' }).patch, { stake_text: 'Чай' });
    assert.deepEqual(Id.editPlan(league, { ...same, stake: '   ' }).patch, { stake_text: '' });
    assert.deepEqual(Id.editPlan(league, { ...same, name: 'Новая', stake: 'Чай' }).patch, { name: 'Новая', stake_text: 'Чай' });
  });
  it('картинка: выбрали файл — загрузка (заменяет прежнюю), «убрать» — удаление, а удалять нечего — ничего', () => {
    const file = { type: 'image/jpeg', size: 10 };
    assert.equal(Id.editPlan(league, { ...same, file }).image, 'upload');
    assert.equal(Id.editPlan(league, { ...same, file, removeImage: true }).image, 'upload');
    assert.equal(Id.editPlan(league, { ...same, removeImage: true }).image, 'remove');
    assert.equal(Id.editPlan({ name: 'Двор' }, { ...same, stake: '', removeImage: true }).image, null);
    assert.equal(Id.editPlan({ name: 'Двор' }, { name: 'Двор', stake: '', file, removeImage: false }).image, 'upload');
  });
  it('ошибки формы: название, длина строки, файл', () => {
    assert.equal(Id.editError(same), '');
    assert.equal(Id.editError({ ...same, name: '   ' }), 'Назови лигу');
    assert.equal(Id.editError({ ...same, name: 'я'.repeat(29) }), 'Название до 28 символов');
    assert.equal(Id.editError({ ...same, stake: 'я'.repeat(81) }), 'Строка до 80 символов');
    assert.equal(Id.editError({ ...same, file: { type: 'image/gif', size: 1 } }), 'Подходят только JPEG, PNG и WEBP');
  });
});

describe('экраны и подключение', () => {
  const FILES = ['kto-kogo-league-identity.js', 'kto-kogo-leagues.js'];
  const BANNED = /ставк|коэффициент|прогноз|пари\b|выигрыш|букмекер|банк\b|ставь|поставить|срок/i;
  const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;

  it('в строках нет азартных слов и emoji', () => {
    for (const f of FILES) {
      const src = read(f);
      const strings = [...src.matchAll(/'((?:[^'\\\n]|\\.){3,})'/g)].map((m) => m[1]);
      assert.deepEqual(strings.filter((s) => BANNED.test(s)), [], f);
      assert.deepEqual(strings.filter((s) => EMOJI.test(s)), [], f);
    }
  });
  it('скрипт подключён до запуска игры, отдельной строкой', () => {
    const html = read('kto-kogo.html');
    const lines = html.split('\n');
    const own = lines.findIndex((l) => l.includes('kto-kogo-league-identity.js'));
    const boot = lines.findIndex((l) => l.includes('kto-kogo-boot.js'));
    const leagues = lines.findIndex((l) => l.includes('kto-kogo-leagues.js'));
    assert.ok(own > leagues && own < boot, 'после leagues.js и до boot.js');
    assert.equal(lines[own].match(/<script/g).length, 1);
  });
  it('текст пользователя на экранах идёт через textContent, а не в разметку', () => {
    for (const f of ['kto-kogo-leagues.js', 'kto-kogo-league-identity.js']) {
      assert.ok(!/innerHTML|insertAdjacentHTML|document\.write/.test(read(f)), f);
    }
  });
  it('поле называется «На что играем», подсказки-примера и плашки про договорённость нет', () => {
    const src = read('kto-kogo-leagues.js') + read('kto-kogo-league-identity.js');
    assert.match(src, /На что играем/);
    assert.ok(!/договорённость/i.test(src));
    assert.ok(!/Например, (пицц|кофе|обед)/i.test(src));
  });
  it('кнопка выбора фото — зона не меньше 44 px', () => {
    const css = read('kto-kogo.css');
    const block = css.slice(css.indexOf('/* ===== league identity (TASK-361) ===== */'));
    assert.ok(block.length > 100, 'раздел стилей есть');
    assert.match(block, /\.kk-filebtn[^{]*\{[^}]*min-height:\s*44px/);
  });
});

describe('кнопка «Создать» оживает при вводе (TASK-363)', () => {
  const src = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo-leagues.js'), 'utf8');

  it('название и «на что играем» пересчитывают кнопку на месте, а не ждут перерисовки', () => {
    assert.match(src, /function syncCta\(f\)/);
    assert.match(src, /id: 'kk-lname'[^\n]*oninput: function \(e\) \{ f\.name = e\.target\.value; syncCta\(f\); \}/);
    assert.match(src, /stakeField\('kk-lstake', f\.stake, function \(v\) \{ f\.stake = v; syncCta\(f\); \}\)/);
  });

  it('кнопка пересчитывается без innerHTML', () => {
    const body = src.slice(src.indexOf('function syncCta'), src.indexOf('var IDEAS'));
    assert.ok(!/innerHTML/.test(body));
    assert.match(body, /textContent = err \|\|/);
  });
});
