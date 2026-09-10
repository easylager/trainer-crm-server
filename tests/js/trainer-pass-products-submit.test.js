/**
 * Double-submit on pass / certificate create must not fire two POSTs.
 * Run: node --test tests/js/trainer-pass-products-submit.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const srcPath = path.resolve(__dirname, '../../static/webapp/trainer-pass-products-main.js');
const src = fs.readFileSync(srcPath, 'utf8');

function handlerBetween(startNeedle, endNeedle) {
  const start = src.indexOf(startNeedle);
  assert.ok(start >= 0, 'missing ' + startNeedle);
  const end = src.indexOf(endNeedle, start + startNeedle.length);
  assert.ok(end > start, 'missing end ' + endNeedle);
  return src.slice(start, end);
}

describe('trainer pass/certificate save: single in-flight submit', () => {
  it('pass save returns immediately if a create/update is already running', () => {
    const handler = handlerBetween("btnSaveForm').onclick", "btnDeleteProduct').onclick");
    assert.match(handler, /if \(state\.savingPassProduct\) return/);
    assert.match(handler, /state\.savingPassProduct = true/);
    assert.match(handler, /\/trainer\/pass-products/);
  });

  it('certificate save returns immediately if a create/update is already running', () => {
    const handler = handlerBetween("btnSaveCertForm').onclick", "btnDeleteCert').onclick");
    assert.match(handler, /if \(state\.savingCertProduct\) return/);
    assert.match(handler, /state\.savingCertProduct = true/);
    assert.match(handler, /\/trainer\/certificate-products/);
  });
});
