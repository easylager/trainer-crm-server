/**
 * TASK-085/086/097 (EPIC4 client-premium) — дизайн-система клиентского Mini App.
 *
 * Гейт G-P1 закрыт: на клиентских экранах ноль нарушений по всем семи правилам —
 * ступени типа, радиуса и веса (TASK-086, TASK-097) и палитра (TASK-087).
 * Тест держит этот ноль и падает с указанием файла, строки и значения.
 *
 * Храповик «не хуже baseline» оставлен рядом намеренно, хотя baseline теперь нулевой:
 * он ловит регресс в разрезе ФАЙЛА и остаётся осмысленным, если в эпик добавят новый
 * клиентский CSS со своим долгом. Дублированием это не является — гейт отвечает
 * на «есть ли нарушения», храповик на «в каком файле их стало больше».
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
    // Рядом с тестом, а не в .ai: тот вынесен из git и на чистом клоне отсутствует.
    path.resolve(__dirname, 'design-scale-baseline.json'),
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

  it('палитра: ни сырых hex, ни hex-фолбэков, ни витринных токенов AURORA (TASK-087)', () => {
    /*
     * Три разных греха, и все три — про то, что цвет перестаёт слушаться темы:
     *   hardcoded-hex — тема не переключается вовсе;
     *   hex-fallback  — `var(--glide-line, #e2e6e5)` зашивает СВЕТЛОЕ значение
     *                   запасным, и в тёмной теме оно всплывёт светлым;
     *   aurora-leak   — витринная гамма на ежедневном экране, прямо запрещена
     *                   шапкой theme.css.
     */
    const palette = findings.filter(
      (f) =>
        CLIENT_FILES.includes(f.file) &&
        ['hardcoded-hex', 'hex-fallback', 'aurora-leak'].includes(f.rule)
    );
    assert.deepEqual(
      palette.map((f) => `${f.file}:${f.line} → ${f.rule} ${f.value}`),
      [],
      'Цвет мимо палитры. Роль берётся из theme.css: действие — --glide-brand, ' +
        'текст-тил на светлом — --glide-ink-teal, состояния — --app-ok/attention/danger, ' +
        'нейтрали — --glide-*. AURORA только для витрины.'
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

  it('ступени типа и радиуса — только токены, произвольных значений нет (TASK-086)', () => {
    /*
     * Гейт, а не храповик. До TASK-086 в клиентских CSS был 31 уникальный размер
     * шрифта и 33 радиуса; шесть смежных значений 11–16px давали 74% всех размеров.
     * Ноль здесь — единственное состояние, в котором шкала вообще существует:
     * стоит вернуть одно «просто 13px», и континуум начинает отрастать заново.
     */
    const offScale = findings.filter(
      (f) =>
        CLIENT_FILES.includes(f.file) &&
        (f.rule === 'scale-font-size' || f.rule === 'scale-radius')
    );
    assert.deepEqual(
      offScale.map((f) => `${f.file}:${f.line} → ${f.rule} ${f.value}`),
      [],
      'Произвольное значение вместо ступени. Размер — var(--app-text-*) или ' +
        'var(--app-icon-*) для глифа-иконки; радиус — var(--app-radius-*). ' +
        'Ступени и правила выбора описаны в шапке theme.css.'
    );
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

    // TASK-086 закрыл и второй слой: на клиентских экранах вес задаётся токеном,
    // а не числом. Иначе «600» разъезжается с --app-weight-semibold при любой правке шкалы.
    const literals = findings.filter(
      (f) => CLIENT_FILES.includes(f.file) && f.rule === 'scale-weight'
    );
    assert.deepEqual(
      literals.map((f) => `${f.file}:${f.line} → ${f.value}`),
      [],
      'Числовой вес вместо токена. Используйте var(--app-weight-regular|medium|semibold|bold).'
    );
  });
});
