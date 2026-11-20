/**
 * Плавная смена экрана «Кто кого»: выбор анимации (kto-kogo-model.js transitionKind) и проводка в роутере.
 *
 * Run: node --test tests/js/kto-kogo-view-transition.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../../static/webapp/kto-kogo-model.js');

const js = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo.css'), 'utf8');

describe('transitionKind', () => {
  it('вперёд, назад, замена и сброс', () => {
    assert.equal(M.transitionKind('go', true, false), 'forward');
    assert.equal(M.transitionKind('back', true, false), 'back');
    assert.equal(M.transitionKind('replace', true, false), 'fade');
    assert.equal(M.transitionKind('reset', true, false), 'fade');
  });
  it('нет API — без перехода', () => {
    for (const nav of ['go', 'back', 'replace', 'reset']) assert.equal(M.transitionKind(nav, false, false), 'none');
  });
  it('«меньше движения» — без перехода', () => {
    for (const nav of ['go', 'back', 'replace', 'reset']) assert.equal(M.transitionKind(nav, true, true), 'none');
  });
  it('неизвестная навигация — без перехода', () => {
    assert.equal(M.transitionKind('render', true, false), 'none');
  });
});

describe('проводка', () => {
  it('render не запускает переход', () => {
    const body = js.slice(js.indexOf('function render()'), js.indexOf('root.replaceChildren.apply'));
    assert.ok(!/withTransition|startViewTransition/.test(body));
  });
  it('startViewTransition под try/catch и со страховочным таймером', () => {
    const fn = js.slice(js.indexOf('function withTransition'), js.indexOf('function go('));
    assert.match(fn, /try \{[\s\S]*startViewTransition\(run\)[\s\S]*\} catch/);
    assert.match(fn, /setTimeout\(function \(\) \{ run\(\); \}/);
  });
  it('go/replace/reset/back идут через withTransition', () => {
    for (const nav of ['go', 'replace', 'reset', 'back']) assert.ok(js.includes("withTransition('" + nav + "'"), nav);
  });
  it('CSS: направления и reduced-motion', () => {
    assert.match(css, /data-kk-vt="forward"\]::view-transition-new\(root\)/);
    assert.match(css, /data-kk-vt="back"\]::view-transition-new\(root\)/);
    assert.match(css, /prefers-reduced-motion: reduce\)[\s\S]*view-transition/);
  });
});
