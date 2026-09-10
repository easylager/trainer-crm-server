"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { describe, it } = require("node:test");

const root = path.resolve(__dirname, "../..");
const source = (relativePath) =>
  fs.readFileSync(path.join(root, relativePath), "utf8");

describe("client copy uses shared Russian formatters", () => {
  it("formats audited counts and prices", () => {
    const {
      countRu,
      genitiveCountRu,
      formatPrice,
    } = require("../../static/webapp/ru-text.js");
    for (const [number, expected] of [
      [1, "1 арена"],
      [2, "2 арены"],
      [5, "5 арен"],
      [11, "11 арен"],
      [14, "14 арен"],
      [21, "21 арена"],
      [22, "22 арены"],
      [25, "25 арен"],
    ]) {
      assert.equal(countRu(number, "арена", "арены", "арен"), expected);
    }
    assert.equal(genitiveCountRu(1, "занятия", "занятий"), "1 занятия");
    assert.equal(genitiveCountRu(2, "занятия", "занятий"), "2 занятий");
    assert.equal(genitiveCountRu(5, "занятия", "занятий"), "5 занятий");
    assert.equal(genitiveCountRu(11, "занятия", "занятий"), "11 занятий");
    assert.equal(genitiveCountRu(22, "занятия", "занятий"), "22 занятий");
    assert.equal(formatPrice(50, "BYN"), "50 BYN");
    assert.equal(formatPrice(55, "RUB"), "55 ₽");
  });

  it("routes audited dynamic modules through RuText", () => {
    for (const relativePath of [
      "static/webapp/arena-card.js",
      "static/webapp/arena-card-model.js",
      "static/webapp/catalog-main.js",
      "static/webapp/client-home-main.js",
      "static/webapp/trainer-pass-products-main.js",
    ]) {
      assert.ok(/RuText/.test(source(relativePath)), relativePath);
    }
    assert.ok(
      /genitiveCountRu/.test(source("static/webapp/client-home-main.js")),
    );
    assert.ok(
      /formatPrice/.test(source("static/webapp/trainer-pass-products-main.js")),
    );
  });

  it("loads RuText before audited client scripts", () => {
    for (const relativePath of [
      "static/webapp/arena.html",
      "static/webapp/catalog.html",
      "static/webapp/book.html",
      "static/webapp/ice.html",
      "static/webapp/client-home.html",
      "static/webapp/trainer-pass-products.html",
    ]) {
      const html = source(relativePath);
      const ruTextPosition = html.indexOf("ru-text.js");
      assert.notEqual(ruTextPosition, -1, relativePath);
      assert.ok(ruTextPosition < html.lastIndexOf("<script"), relativePath);
    }
  });

  it("keeps the plain BYN compatibility rule", () => {
    for (const relativePath of [
      "static/webapp/arena-card.js",
      "static/webapp/catalog-main.js",
      "static/webapp/trainer-pass-products-main.js",
    ]) {
      assert.doesNotMatch(source(relativePath), /nbrb-icon|\uE901/);
    }
  });
});
