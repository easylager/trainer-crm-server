/**
 * Profile «Кто я» — editable specialist roles (same model as onboarding).
 */
const fs = require('fs');
const path = require('path');
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

function read(name) {
  return fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'webapp', name), 'utf8');
}

describe('профиль тренера: Кто я', () => {
  const html = read('trainer-profile.html');
  const src = read('trainer-profile-main.js');
  const css = read('mini-app-trainer-profile.css');

  it('поле редактируемое — чипы, не read-only текст', () => {
    assert.match(html, /id="specialistRolesChips"/);
    assert.match(html, /id="specialistRoleAddBtn"/);
    assert.match(html, /Своя роль/);
    assert.doesNotMatch(html, /id="specialistRolesDisplay"/);
    assert.match(src, /function renderSpecialistRolesEditor/);
    assert.match(src, /specialist_roles: specialistRolesSnapshot/);
    assert.match(src, /specialist_roles: Array\.isArray\(pr\.specialist_roles\)/);
    assert.match(css, /\.profile-role-chip/);
  });
});
