'use strict';
/**
 * Свод деталей кабинета тренера — кодом, а не договорённостью (TASK-314):
 * ни эмодзи, ни «ты» в тренерских экранах. Флаги стран в выборе телефона — не украшение,
 * их оставляем; ★ рейтинга и ✓ ✕ — типографские знаки, не эмодзи.
 */
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const DIR = path.join(__dirname, '../../static/webapp');

/* Экраны волны 4 (свой макет): снять из списка, когда переедут на систему. */
const PENDING_WAVE_4 = new Set([
  'trainer-subscription.html',
  'trainer-pass-products.html',
  'trainer-pass-products-main.js',
]);

function trainerFiles() {
  return fs
    .readdirSync(DIR)
    .filter((f) => /^(trainer-|schedule-editor|mini-app-trainer|referral-rules)/.test(f) && /\.(html|js)$/.test(f))
    .filter((f) => !PENDING_WAVE_4.has(f));
}

const EMOJI = /(?:[\u{1F300}-\u{1F5FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{1F900}-\u{1FAFF}]|[✨⚠✉⭐➕✅❌❗]️?)/u;
const INFORMAL = /(^|[^а-яё])(ты|тебя|тебе|тобой|твой|твоя|твоё|твои|твоего|твоей|твоих|твоим)(?=[^а-яё]|$)/iu;

function strip(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/<!--[\s\S]*?-->/g, '');
}

describe('свод деталей кабинета тренера', () => {
  const files = trainerFiles();

  it('файлов достаточно, чтобы проверка что-то значила', () => {
    assert.ok(files.length > 30, String(files.length));
  });

  it('без эмодзи', () => {
    const bad = [];
    for (const f of files) {
      strip(fs.readFileSync(path.join(DIR, f), 'utf8')).split('\n').forEach((line, i) => {
        const m = EMOJI.exec(line);
        if (m) bad.push(`${f}:${i + 1} ${m[0]}`);
      });
    }
    assert.deepEqual(bad, []);
  });

  it('только «вы»', () => {
    const bad = [];
    for (const f of files) {
      strip(fs.readFileSync(path.join(DIR, f), 'utf8')).split('\n').forEach((line, i) => {
        const m = INFORMAL.exec(line);
        if (m) bad.push(`${f}:${i + 1} ${m[2]}`);
      });
    }
    assert.deepEqual(bad, []);
  });
});
