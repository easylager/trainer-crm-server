"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { describe, it } = require("node:test");

const root = path.resolve(__dirname, "../..");

function source(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

describe("webapp error copy contract", () => {
  it("uses a Russian fallback instead of returning unknown technical detail", () => {
    const text = source("static/webapp/mini-app-telegram-chrome.js");
    assert.ok(/Не удалось выполнить действие/.test(text));
    assert.doesNotMatch(text, /return s;\n  }\n\n  function webappApiUrl/);
  });

  it("does not render Pydantic validation messages directly in trainer surfaces", () => {
    for (const relativePath of [
      "static/webapp/trainer-profile-main.js",
      "static/webapp/trainer-stats-main.js",
    ]) {
      assert.doesNotMatch(source(relativePath), /detail\[0\]\.msg/);
      assert.doesNotMatch(source(relativePath), /return r\.statusText/);
    }
  });
});
