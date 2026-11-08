/**
 * TASK-357: запасной разбор trainer_… в mini-app-client-shell.js (если glide-deeplink.js не загрузился)
 * ведёт туда же, куда основной, и не теряет метку источника _v_ у ссылки на время.
 * Run: node --test tests/js/shell-trainer-deeplink-fallback.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const shell = fs.readFileSync(path.join(webapp, 'mini-app-client-shell.js'), 'utf8');
const start = shell.indexOf('  function deepLinkTarget(sp) {');
const end = shell.indexOf('\n  }\n', start);
const fnSrc = shell.slice(start, end + 4);
const fallback = vm.runInNewContext('var global = {};' + fnSrc + ';deepLinkTarget');
const main = require(path.join(webapp, 'glide-deeplink.js')).deepLinkTarget;

describe('shell fallback trainer_ deep link', () => {
  it('совпадает с GlideDeepLink для ссылок тренера', () => {
    for (const sp of ['trainer_7', 'trainer_7_a_3', 'trainer_7_s_55', 'trainer_7_a_3_s_55_v_p3', 'trainer_7_v_p3_s_55_a_3', 'trainer_7_v_p3']) {
      assert.deepEqual(JSON.parse(JSON.stringify(fallback(sp))), main(sp), sp);
    }
  });

  it('метка _v_ у ссылки на время попадает в адрес', () => {
    assert.equal(fallback('trainer_7_s_55_v_c1').path, 'trainers?trainer_id=7&slot_id=55&via=c1');
  });
});
