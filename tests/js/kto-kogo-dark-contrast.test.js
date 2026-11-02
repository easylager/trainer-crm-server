// Тёмная тема «Кто кого»: тёплые токены и контраст всех пар текста (текст ≥ 4.5:1, крупный и значки ≥ 3:1).
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const css = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo.css'), 'utf8');

function tokens(selector) {
  const start = css.indexOf(selector + ' {');
  assert.ok(start >= 0, selector);
  const body = css.slice(css.indexOf('{', start) + 1, css.indexOf('}', start));
  const out = {};
  for (const m of body.matchAll(/--(kk-[a-z-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

function lum(hex) {
  const n = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function ratio(a, b) {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

describe('тёмная тема: токены владельца и контраст', () => {
  const light = tokens('.kk');
  const dark = Object.assign({}, light, tokens('body.kk-dark .kk'));

  it('значения тёмных токенов: синяя гамма игры (владелец 03.11 вернул синюю)', () => {
    const want = { 'kk-bg': '#17212b', 'kk-card': '#222c38', 'kk-row': '#1d2733', 'kk-chip': '#2c3846', 'kk-line': '#3a4756', 'kk-muted': '#98adc0', 'kk-soft': '#c3d2dc', 'kk-ink': '#f1f5f7', 'kk-scrim': 'rgba(6, 12, 18, 0.6)' };
    for (const [k, v] of Object.entries(want)) assert.equal(dark[k], v, k);
  });

  it('светлая тема не тронута', () => {
    assert.equal(light['kk-bg'], '#f2f5fa');
    assert.equal(light['kk-ink'], '#0d1424');
  });

  it('текст на фонах ≥ 4.5:1', () => {
    const text = ['kk-ink', 'kk-soft', 'kk-muted', 'kk-gold-ink'];
    const bg = ['kk-bg', 'kk-card', 'kk-row', 'kk-chip', 'kk-me'];
    const low = [];
    for (const t of text) for (const b of bg) if (ratio(dark[t], dark[b]) < 4.5) low.push(t + ' на ' + b + ' ' + ratio(dark[t], dark[b]).toFixed(2));
    assert.deepEqual(low, []);
  });

  it('остальные пары: корона, золото, ошибки, отключённые кнопки, фокус', () => {
    const pairs = [
      ['kk-crownink', 'kk-crownbg', 4.5], ['kk-gold-ink', 'kk-crownbg', 4.5], ['kk-on-gold', 'kk-gold', 4.5],
      ['kk-danger', 'kk-card', 4.5], ['kk-danger', 'kk-bg', 4.5], ['kk-soft', 'kk-line', 4.5], ['kk-focus', 'kk-bg', 3], ['kk-focus', 'kk-card', 3],
      ['kk-line', 'kk-bg', 1.2], ['kk-me', 'kk-bg', 1.1],
    ];
    const low = pairs.filter(([a, b, min]) => ratio(dark[a], dark[b]) < min).map(([a, b, min]) => `${a}/${b} ${ratio(dark[a], dark[b]).toFixed(2)} < ${min}`);
    assert.deepEqual(low, []);
  });

  it('красный и зелёный не применяются к результатам', () => {
    const rules = css.replace(/\/\*[\s\S]*?\*\//g, '');
    const users = rules.split('}').filter((r) => /var\(--kk-(win|lose)\)/.test(r) && !/^\s*(body\.kk-dark )?\.kk\s*\{/.test(r.trim() + '{'));
    // Остаётся только переключатель напоминаний (настройка, не результат).
    assert.deepEqual(users.map((r) => r.split('{')[0].trim()), ['.kk-toggle.is-on span']);
  });
});
