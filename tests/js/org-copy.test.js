"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { describe, it } = require("node:test");

const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(
  path.join(root, "static/webapp/trainer-collective.html"),
  "utf8",
);

describe("organization copy contract", () => {
  it("maps membership roles to Russian labels before rendering", () => {
    assert.match(source, /function collectiveRoleLabel\(role\)/);
    assert.match(source, /return 'Владелец'/);
    assert.match(source, /return 'Администратор'/);
    assert.match(source, /return 'Тренер'/);
    assert.doesNotMatch(source, /rolePrefix = data\.role === 'owner' \? 'Owner'/);
    assert.doesNotMatch(source, /m\.role === 'owner' \? 'owner'/);
  });

  it("does not expose internal pool or membership words in org copy", () => {
    assert.doesNotMatch(source, /станет member/);
    assert.doesNotMatch(source, /расширьте pool подписки/);
    assert.doesNotMatch(source, /вы останетесь member/);
  });
});