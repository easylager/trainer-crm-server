#!/usr/bin/env node
/**
 * TASK-085 — линтер дизайн-системы клиентского Mini App (EPIC4 client-premium).
 *
 * Меряет то, что аудит 2026-09-07 замерил вручную (F-2, F-3), и превращает разовый
 * grep в воспроизводимую проверку. Гейт G-P1 эпика закрывается, когда этот скрипт
 * даёт ноль нарушений на клиентских экранах.
 *
 * Зависимостей нет — только node:fs. Тот же жанр, что tests/js/ice-tab-tokens.test.js.
 *
 * Правила:
 *   scale-font-size   литерал font-size вместо токена шкалы
 *   scale-radius      литерал border-radius вместо токена (пилюли 999px/50% разрешены)
 *   scale-weight      литерал font-weight вместо токена
 *   weight-unloaded   вес вне шкалы 400/500/600/700 (Golos Text переменный — 650 рисуется как 650)
 *   hardcoded-hex     hex-цвет мимо палитры
 *   aurora-leak       витринный токен --ice-* / --vertical-brand-* на рабочем экране
 *
 * Использование:
 *   node scripts/webapp_design_lint.js report            таблица по файлам
 *   node scripts/webapp_design_lint.js list [rule]       нарушения построчно
 *   node scripts/webapp_design_lint.js check             exit 1, если есть нарушения (цель G-P1)
 *   node scripts/webapp_design_lint.js check --baseline  exit 1, только если стало хуже baseline
 *   node scripts/webapp_design_lint.js write-baseline    перезаписать baseline
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const WEBAPP = path.join(ROOT, 'static/webapp');
const BASELINE_PATH = path.join(
  ROOT,
  '.ai/epics/client-premium/design/scale-baseline.json'
);

/**
 * Клиентские рабочие экраны — то, что закрывает гейт G-P1.
 * Тренерские и админские CSS вне эпика (epic.md § Осознанно вне).
 */
const CLIENT_FILES = [
  'ice-tab.css',
  'arena-card.css',
  'mini-app-client-home.css',
  'mini-app-catalog.css',
  'mini-app-client-shell.css',
  'mini-app-client-nav.css',
  'mini-app-client-bookings.css',
  'mini-app-client-requests.css',
  'mini-app-client-theme.css',
  'mini-app-arena-ribbon.css',
  'booking-client.css',
];

/**
 * Общий с тренером. Считается отдельно: включать его в scope TASK-086 —
 * открытый вопрос Q-002 той задачи, и молча тянуть тренерские экраны нельзя.
 */
const SHARED_FILES = ['mini-app-components.css'];

/** Источник правды палитры: hex здесь легитимен по определению. */
const PALETTE_FILES = new Set(['theme.css']);

/** Пилюли и «без радиуса» — не нарушение шкалы, а отдельные формы. */
const RADIUS_ALLOWED = new Set(['0', '0px', '50%', '999px', '9999px', '100%']);

/*
 * Шкала весов. Golos Text — переменный (400–700), поэтому промежуточные значения
 * рисуются как есть, а не округляются вверх, как это делал DM Sans со статическими
 * начертаниями. Разница 600 vs 650 ниже порога различения, но ломает систему.
 */
const WEIGHTS_LOADED = new Set(['400', '500', '600', '700']);
const WEIGHT_KEYWORDS = new Set(['normal', 'bold', 'inherit', 'initial', 'unset', 'lighter', 'bolder']);

/**
 * Комментарии вырезаются, но переводы строк сохраняются — иначе съедут номера строк,
 * а без них отчёт бесполезен для исполнителя.
 */
function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '));
}

function readSource(file) {
  const full = path.join(WEBAPP, file);
  const raw = fs.readFileSync(full, 'utf8');
  return stripComments(raw);
}

function lineOf(text, index) {
  let line = 1;
  for (let i = 0; i < index; i += 1) if (text[i] === '\n') line += 1;
  return line;
}

function usesToken(value) {
  return /var\(\s*--/.test(value);
}

/** Значения вида `clamp(24px, 6.5vw, 30px)` — тоже литералы, но осознанно адаптивные. */
function isFluid(value) {
  return /\b(clamp|min|max)\s*\(/.test(value);
}

function scanDeclarations(css, property, handler) {
  const re = new RegExp(`(^|[;{}\\s])${property}\\s*:\\s*([^;{}]+)`, 'gi');
  let m;
  while ((m = re.exec(css)) !== null) {
    handler(m[2].trim(), m.index + m[0].indexOf(property));
  }
}

function analyzeFile(file, { checkPalette }) {
  const css = readSource(file);
  const findings = [];
  const add = (rule, index, value) =>
    findings.push({ file, rule, line: lineOf(css, index), value });

  scanDeclarations(css, 'font-size', (value, index) => {
    if (usesToken(value)) return;
    if (isFluid(value)) {
      add('scale-font-size', index, value);
      return;
    }
    if (/[\d.]+\s*(px|rem|em|%)/.test(value)) add('scale-font-size', index, value);
  });

  scanDeclarations(css, 'border-radius', (value, index) => {
    if (usesToken(value)) return;
    const parts = value.split(/[\s/]+/).filter(Boolean);
    if (parts.every((p) => RADIUS_ALLOWED.has(p.toLowerCase()))) return;
    if (/[\d.]+\s*(px|rem|em|%)/.test(value)) add('scale-radius', index, value);
  });

  scanDeclarations(css, 'font-weight', (value, index) => {
    if (usesToken(value)) return;
    const v = value.toLowerCase();
    if (WEIGHT_KEYWORDS.has(v)) return;
    if (/^\d+$/.test(v) && !WEIGHTS_LOADED.has(v)) {
      // Вес вне шкалы: на переменном шрифте это реальное, но неразличимое начертание.
      add('weight-unloaded', index, value);
      return;
    }
    add('scale-weight', index, value);
  });

  if (checkPalette) {
    /*
     * Два разных греха, и путать их нельзя.
     *
     * hex-fallback — `var(--glide-line, #e2e6e5)`. Токен работает, но фолбэк намертво
     * зашивает СВЕТЛОЕ значение: если токен не доедет, тёмная тема получит светлый цвет.
     * Плюс палитра дублируется в десятках мест. Чинится дешёво и массово.
     *
     * hardcoded-hex — сырой `color: #8a6a2b`. Токена нет вообще, тема не переключается.
     * Это F-2 из аудита, чинится поштучно и с решением о семантике.
     */
    const fallbackSpans = [];
    const varRe = /var\(\s*--[a-z0-9-]+\s*,([^()]*(?:\([^()]*\)[^()]*)*)\)/gi;
    let m;
    while ((m = varRe.exec(css)) !== null) {
      const start = m.index + m[0].indexOf(',');
      fallbackSpans.push([start, m.index + m[0].length]);
    }
    const insideFallback = (i) => fallbackSpans.some(([a, b]) => i >= a && i < b);

    const hexRe = /#[0-9a-fA-F]{3,8}\b/g;
    while ((m = hexRe.exec(css)) !== null) {
      add(insideFallback(m.index) ? 'hex-fallback' : 'hardcoded-hex', m.index, m[0]);
    }

    const auroraRe = /var\(\s*(--ice-[a-z-]+|--vertical-brand-[a-z-]+)/g;
    while ((m = auroraRe.exec(css)) !== null) add('aurora-leak', m.index, m[1]);
  }

  return findings;
}

function analyze() {
  const findings = [];
  for (const file of [...CLIENT_FILES, ...SHARED_FILES]) {
    findings.push(...analyzeFile(file, { checkPalette: !PALETTE_FILES.has(file) }));
  }
  return findings;
}

const RULES = [
  'scale-font-size',
  'scale-radius',
  'scale-weight',
  'weight-unloaded',
  'hardcoded-hex',
  'hex-fallback',
  'aurora-leak',
];

function tally(findings) {
  const byFile = {};
  for (const file of [...CLIENT_FILES, ...SHARED_FILES]) {
    byFile[file] = Object.fromEntries(RULES.map((r) => [r, 0]));
  }
  for (const f of findings) byFile[f.file][f.rule] += 1;
  return byFile;
}

function total(counts) {
  return RULES.reduce((s, r) => s + counts[r], 0);
}

function pad(s, n) {
  s = String(s);
  return s + ' '.repeat(Math.max(0, n - s.length));
}

function report(findings) {
  const byFile = tally(findings);
  const head = ['файл', 'font', 'radius', 'weight', 'unload', 'hex', 'hexFb', 'aurora', 'всего'];
  const widths = [34, 6, 7, 7, 7, 6, 7, 7, 6];
  console.log('\nКлиентские экраны (гейт G-P1)\n');
  console.log(head.map((h, i) => pad(h, widths[i])).join(''));
  console.log('-'.repeat(widths.reduce((a, b) => a + b, 0)));

  let grand = 0;
  const printRow = (file) => {
    const c = byFile[file];
    const t = total(c);
    grand += t;
    console.log(
      [
        pad(file, widths[0]),
        pad(c['scale-font-size'], widths[1]),
        pad(c['scale-radius'], widths[2]),
        pad(c['scale-weight'], widths[3]),
        pad(c['weight-unloaded'], widths[4]),
        pad(c['hardcoded-hex'], widths[5]),
        pad(c['hex-fallback'], widths[6]),
        pad(c['aurora-leak'], widths[7]),
        pad(t, widths[8]),
      ].join('')
    );
  };

  CLIENT_FILES.forEach(printRow);
  console.log('-'.repeat(widths.reduce((a, b) => a + b, 0)));
  console.log(pad('ИТОГО клиент', widths[0]) + pad('', 40) + grand);

  console.log('\nОбщий с тренером (вне гейта, Q-002 в TASK-086)\n');
  SHARED_FILES.forEach((file) => {
    const c = byFile[file];
    console.log(pad(file, widths[0]) + total(c));
  });

  const distinct = distinctValues(findings);
  console.log('\nРазброс значений (то, что чинит шкала в TASK-086)\n');
  console.log(`  уникальных font-size:     ${distinct['scale-font-size'].size}`);
  console.log(`  уникальных border-radius: ${distinct['scale-radius'].size}`);
  console.log(
    `  весов без начертания:     ${[...distinct['weight-unloaded']].sort().join(', ') || '—'}`
  );
  console.log('');
  return grand;
}

function distinctValues(findings) {
  const out = Object.fromEntries(RULES.map((r) => [r, new Set()]));
  for (const f of findings) {
    if (CLIENT_FILES.includes(f.file)) out[f.rule].add(f.value);
  }
  return out;
}

function list(findings, ruleFilter) {
  const rows = findings.filter((f) => !ruleFilter || f.rule === ruleFilter);
  for (const f of rows) {
    console.log(`${f.file}:${f.line}  ${pad(f.rule, 18)} ${f.value}`);
  }
  console.log(`\n${rows.length} нарушений`);
}

function clientTotals(findings) {
  const byFile = tally(findings);
  const out = {};
  for (const file of CLIENT_FILES) out[file] = total(byFile[file]);
  return out;
}

function main() {
  const [, , cmd = 'report', arg] = process.argv;
  const findings = analyze();

  if (cmd === 'report') {
    const grand = report(findings);
    if (grand > 0) {
      console.log(
        `G-P1 НЕ закрыт: ${grand} нарушений на клиентских экранах.\n` +
          `Цель — 0 после TASK-086 и TASK-087.\n`
      );
    } else {
      console.log('G-P1 закрыт: нарушений нет.\n');
    }
    return;
  }

  if (cmd === 'list') {
    list(findings, arg);
    return;
  }

  if (cmd === 'distinct') {
    /*
     * Число УНИКАЛЬНЫХ значений на файл — это и есть ответ на вопрос «есть ли шкала».
     * Сверяется с таблицей F-3 аудита, которая считалась вручную через grep.
     */
    console.log('\nУникальных значений на файл (F-3 аудита)\n');
    console.log(pad('файл', 34) + pad('font-size', 12) + pad('radius', 9) + 'weight');
    console.log('-'.repeat(64));
    for (const file of [...CLIENT_FILES, ...SHARED_FILES]) {
      const own = findings.filter((f) => f.file === file);
      const uniq = (rules) =>
        new Set(own.filter((f) => rules.includes(f.rule)).map((f) => f.value)).size;
      console.log(
        pad(file, 34) +
          pad(uniq(['scale-font-size']), 12) +
          pad(uniq(['scale-radius']), 9) +
          uniq(['scale-weight', 'weight-unloaded'])
      );
    }
    console.log('');
    return;
  }

  if (cmd === 'write-baseline') {
    /*
     * Храповик переписывается на текущий, более низкий уровень — иначе он перестаёт
     * защищать уже сделанную работу. Но исходные числа «до эпика» при этом сохраняются:
     * это доказательная база аудита, и потерять её, опустив планку, значит остаться
     * без ответа на вопрос «стало ли лучше».
     */
    const prev = fs.existsSync(BASELINE_PATH)
      ? JSON.parse(fs.readFileSync(BASELINE_PATH, 'utf8'))
      : null;
    const data = {
      recorded_at: new Date().toISOString().slice(0, 10),
      task: process.env.BASELINE_TASK || 'TASK-085',
      note: 'Ratchet: числа могут только уменьшаться.',
      client_total: Object.values(clientTotals(findings)).reduce((a, b) => a + b, 0),
      per_file: clientTotals(findings),
      before_epic4: prev ? prev.before_epic4 || {
        recorded_at: prev.recorded_at,
        task: prev.task,
        client_total: prev.client_total,
        per_file: prev.per_file,
      } : undefined,
    };
    fs.writeFileSync(BASELINE_PATH, JSON.stringify(data, null, 2) + '\n');
    console.log(`baseline записан: ${path.relative(ROOT, BASELINE_PATH)}`);
    return;
  }

  if (cmd === 'check') {
    const totals = clientTotals(findings);
    const grand = Object.values(totals).reduce((a, b) => a + b, 0);

    if (arg === '--baseline') {
      const base = JSON.parse(fs.readFileSync(BASELINE_PATH, 'utf8'));
      const worse = [];
      for (const [file, n] of Object.entries(totals)) {
        const was = base.per_file[file] ?? 0;
        if (n > was) worse.push(`${file}: было ${was}, стало ${n}`);
      }
      if (worse.length) {
        console.error('Регресс дизайн-системы:\n  ' + worse.join('\n  '));
        process.exit(1);
      }
      console.log(`ok: ${grand} нарушений, не хуже baseline (${base.client_total})`);
      return;
    }

    if (grand > 0) {
      console.error(`G-P1 не закрыт: ${grand} нарушений. Подробно: node ${path.relative(ROOT, __filename)} list`);
      process.exit(1);
    }
    console.log('G-P1 закрыт: нарушений нет.');
    return;
  }

  console.error(`неизвестная команда: ${cmd}`);
  process.exit(2);
}

if (require.main === module) main();

module.exports = { analyze, clientTotals, CLIENT_FILES, RULES };
