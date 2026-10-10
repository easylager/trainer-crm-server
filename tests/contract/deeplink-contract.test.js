/**
 * TASK-223: контракт start_param Mini App — JS-сторона.
 * Те же кейсы, что у tests/contract/test_deeplink_contract_py.py (deeplink_cases.json).
 * Run: node --test tests/contract/deeplink-contract.test.js
 *
 * Разбираем тремя путями:
 *  1) static/webapp/glide-deeplink.js (``deepLinkTarget``), а если файла ещё нет — функция из mini-app-client-shell.js;
 *  2) arena-card-model.js: ``parseArenaRef`` и ``sessionIdFromStartParam`` (карточка арены).
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');
const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, 'deeplink_cases.json'), 'utf8'));
const FIELDS = ['kind', 'arena_id', 'session_id', 'city_id', 'intent', 'when'];

function loadDeepLinkTarget() {
  const extracted = path.join(webapp, 'glide-deeplink.js');
  if (fs.existsSync(extracted)) {
    return { source: 'glide-deeplink.js', fn: require(extracted).deepLinkTarget };
  }
  const src = fs.readFileSync(path.join(webapp, 'mini-app-client-shell.js'), 'utf8');
  const start = src.indexOf('function deepLinkTarget(sp) {');
  assert.ok(start >= 0, 'deepLinkTarget must exist in glide-deeplink.js or in the shell');
  const end = src.indexOf('\n  }\n', start);
  // eslint-disable-next-line no-new-func
  return { source: 'mini-app-client-shell.js', fn: new Function(src.slice(start, end + 4) + '\nreturn deepLinkTarget;')() };
}

function norm(expect) {
  const out = {};
  FIELDS.forEach((f) => {
    const v = expect[f];
    out[f] = v === undefined || v === null ? null : f === 'kind' ? v : String(v);
  });
  return out;
}

/** {key, path} шелла → тот же вид, что у python-стороны. */
function targetToContract(target) {
  if (!target) return norm({ kind: null });
  const q = new URLSearchParams(target.path.split('?')[1] || '');
  if (target.key === 'arena') {
    return norm({ kind: 'arena', arena_id: q.get('ref'), session_id: q.get('s') });
  }
  return norm({
    kind: 'catalog',
    city_id: q.get('city_id'),
    intent: q.get('venue') || q.get('intent'),
    when: q.get('when'),
  });
}

const model = require(path.join(webapp, 'arena-card-model.js'));
const loaded = loadDeepLinkTarget();

describe('deeplink contract (js shell: ' + loaded.source + ')', () => {
  CASES.forEach((c) => {
    it('shell parses ' + JSON.stringify(c.start_param.slice(0, 40)), () => {
      const want = norm(c.js || c.expect);
      assert.deepEqual(targetToContract(loaded.fn(c.start_param)), want, c.note || '');
    });
  });
});

describe('deeplink contract (arena-card-model)', () => {
  CASES.forEach((c) => {
    it('card parses ' + JSON.stringify(c.start_param.slice(0, 40)), () => {
      assert.equal(model.parseArenaRef('', c.start_param), c.card.ref, c.note || '');
      assert.equal(model.sessionIdFromStartParam(c.start_param), c.card.session_id, c.note || '');
    });
  });

  it('every real arena deep link gets the same arena and session as the shell', () => {
    CASES.filter((c) => c.expect.kind === 'arena' && c.valid_start_param).forEach((c) => {
      assert.equal(model.parseArenaRef('', c.start_param), String(c.expect.arena_id));
      assert.equal(model.sessionIdFromStartParam(c.start_param), c.expect.session_id ? String(c.expect.session_id) : null);
    });
  });
});
