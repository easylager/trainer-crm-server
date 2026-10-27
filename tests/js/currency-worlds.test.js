'use strict';
const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const WEBAPP = path.join(__dirname, '../../static/webapp');
const LANDING = path.join(__dirname, '../../static/landing');

function listFiles(dir, exts) {
  return fs.readdirSync(dir).filter((f) => exts.some((e) => f.endsWith(e))).map((f) => path.join(dir, f));
}

describe('два мира: рубли пишутся «руб.», знак ₽ нигде не остаётся', () => {
  it('в Mini App и на лендинге нет «₽»', () => {
    const offenders = [...listFiles(WEBAPP, ['.js', '.html']), ...listFiles(LANDING, ['.js', '.html'])].filter((f) =>
      fs.readFileSync(f, 'utf8').includes('₽')
    );
    assert.deepEqual(offenders.map((f) => path.basename(f)), []);
  });

  it('тренерские экраны не клеят «BYN» руками (кроме студии): валюта — от тренера', () => {
    const files = listFiles(WEBAPP, ['.js', '.html']).filter((f) => /\/trainer-[^/]*$/.test(f) && !/collective/.test(f));
    const offenders = [];
    for (const f of files) {
      const lines = fs.readFileSync(f, 'utf8').split('\n');
      lines.forEach((line, i) => {
        if (/\+\s*'\s*BYN'/.test(line) || /'\s*BYN'\s*\+/.test(line)) offenders.push(`${path.basename(f)}:${i + 1}`);
      });
    }
    assert.deepEqual(offenders, []);
  });
});

describe('TrainerFormat: валюта тренера', () => {
  let saved;
  beforeEach(() => {
    saved = global.window;
    delete require.cache[require.resolve('../../static/webapp/trainer-format.js')];
  });
  afterEach(() => {
    if (saved === undefined) delete global.window;
    else global.window = saved;
  });

  it('без данных — BYN, как было', () => {
    delete global.window;
    const TF = require('../../static/webapp/trainer-format.js');
    assert.equal(TF.currencyCode(), 'BYN');
    assert.equal(TF.currencyLabel(), 'BYN');
    assert.equal(TF.money(40.5), '40,50 BYN');
  });

  it('тренер из РФ: «руб.» и в подписи, и в деньгах по умолчанию', () => {
    global.window = { TRAINER_CURRENCY: 'RUB' };
    const TF = require('../../static/webapp/trainer-format.js');
    assert.equal(TF.currencyCode(), 'RUB');
    assert.equal(TF.currencyLabel(), 'руб.');
    assert.equal(TF.money(2500), '2 500 руб.');
    assert.equal(TF.money(2500, 'BYN'), '2 500 BYN'); // явная валюта из API важнее
  });

  it('значение из сессии подхватывается, если страница открылась до ответа /trainer/access', () => {
    global.window = { sessionStorage: { getItem: (k) => (k === 'trainer_currency_v1' ? 'RUB' : null) } };
    const TF = require('../../static/webapp/trainer-format.js');
    assert.equal(TF.currencyLabel(), 'руб.');
  });
});
