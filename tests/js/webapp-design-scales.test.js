/**
 * TASK-085 (EPIC4 client-premium) — храповик дизайн-системы клиентского Mini App.
 *
 * Тест НЕ требует нуля нарушений: на 2026-09-07 их 1092, и обнулить их — работа
 * TASK-086/087, а не этого теста. Он держит храповик: числа могут только падать.
 * Любой новый литерал шрифта, радиуса или сырой hex на клиентском экране роняет тест
 * сразу, а не всплывает через месяц.
 *
 * Когда TASK-086 и TASK-087 закроются, baseline станет нулевым, и тест
 * превратится в обычный гейт G-P1.
 *
 * Run: node --test tests/js/webapp-design-scales.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { analyze, clientTotals, CLIENT_FILES } = require('../../scripts/webapp_design_lint.js');

const BASELINE = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '../../.ai/epics/client-premium/design/scale-baseline.json'),
    'utf8'
  )
);

describe('дизайн-система клиентского Mini App (EPIC4 G-P1)', () => {
  const findings = analyze();
  const totals = clientTotals(findings);

  it('ни один клиентский CSS не стал хуже baseline', () => {
    const worse = [];
    for (const file of CLIENT_FILES) {
      const was = BASELINE.per_file[file] ?? 0;
      const now = totals[file];
      if (now > was) worse.push(`${file}: было ${was}, стало ${now}`);
    }
    assert.deepEqual(
      worse,
      [],
      'Регресс дизайн-системы. Новые литералы шрифта/радиуса/веса или сырые hex ' +
        'на клиентских экранах запрещены — используйте токены из theme.css.\n  ' +
        worse.join('\n  ')
    );
  });

  it('baseline не разъехался с файлами (все клиентские CSS учтены)', () => {
    for (const file of CLIENT_FILES) {
      assert.ok(
        Object.prototype.hasOwnProperty.call(BASELINE.per_file, file),
        `${file} нет в baseline — перезапишите: node scripts/webapp_design_lint.js write-baseline`
      );
    }
  });

  it('веса только из шкалы 400/500/600/700 (TASK-097)', () => {
    /*
     * Раньше здесь стоял «канареечный» тест, требовавший, чтобы нарушения СУЩЕСТВОВАЛИ.
     * Это была ошибка: тест защищал проблему вместо результата. После TASK-097 класс
     * нарушения устранён, и проверка стала настоящей.
     *
     * Почему это важно именно теперь: Golos Text — переменный шрифт (400–700).
     * DM Sans со статическими начертаниями округлял 650 вверх до 700, а переменный
     * нарисует ровно 650. Любой вернувшийся промежуточный вес — это не «чуть жирнее»,
     * а тихое изменение начертания в проде.
     */
    const offScale = findings.filter((f) => f.rule === 'weight-unloaded');
    assert.deepEqual(
      offScale.map((f) => `${f.file}:${f.line} → ${f.value}`),
      [],
      'Вес вне шкалы. Допустимы только 400, 500, 600, 700.'
    );
  });
});
