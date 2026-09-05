/**
 * TASK-055: hub teaser «Лёд рядом» — copy, href, hide-if-empty.
 * Run: node --test tests/js/ice-teaser-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/ice-teaser-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

function sampleTeaser(overrides) {
  return Object.assign(
    {
      arena_id: 12,
      arena_slug: 'chizhovka',
      arena_name: 'Чижовка',
      kind: 'public_skate',
      starts_at_utc: '2026-09-06T08:00:00+00:00',
      local_date: '2026-09-06',
      starts_at_local: '11:00',
      price_adult_minor: 1200,
      currency_code: 'BYN',
      distance_km: 2.4,
    },
    overrides || {}
  );
}

describe('formatIceTeaser (AC-001)', () => {
  it('builds an amber-row title and subtitle and an arena-card href', () => {
    const { formatIceTeaser } = loadModel();
    const now = new Date('2026-09-06T07:00:00Z');
    const view = formatIceTeaser(sampleTeaser(), now);
    assert.equal(view.hidden, false);
    assert.match(view.title, /Лёд рядом/);
    assert.match(view.title, /сегодня в 11:00/i);
    assert.match(view.subtitle, /Чижовка/);
    assert.match(view.subtitle, /2,4 км/);
    assert.match(view.subtitle, /массовое/);
    assert.match(view.subtitle, /взр/);
    assert.match(view.subtitle, /12/);
    assert.equal(view.href, 'arena?ref=chizhovka');
  });

  it('uses arena id when slug is missing', () => {
    const { formatIceTeaser } = loadModel();
    const view = formatIceTeaser(
      sampleTeaser({ arena_slug: null }),
      new Date('2026-09-06T07:00:00Z')
    );
    assert.equal(view.href, 'arena?ref=12');
  });

  it('omits distance when the API did not compute it', () => {
    const { formatIceTeaser } = loadModel();
    const view = formatIceTeaser(
      sampleTeaser({ distance_km: null }),
      new Date('2026-09-06T07:00:00Z')
    );
    assert.ok(!/км/.test(view.subtitle));
    assert.match(view.subtitle, /Чижовка/);
  });
});

describe('formatIceTeaser empty (AC-002)', () => {
  it('hides the whole block when payload is null', () => {
    const { formatIceTeaser } = loadModel();
    const view = formatIceTeaser(null, new Date('2026-09-06T07:00:00Z'));
    assert.equal(view.hidden, true);
    assert.equal(view.href, '');
    assert.equal(view.title, '');
  });

  it('hides when there is no future slot identity', () => {
    const { formatIceTeaser } = loadModel();
    const view = formatIceTeaser(
      sampleTeaser({ arena_id: null, arena_slug: null, starts_at_local: null }),
      new Date('2026-09-06T07:00:00Z')
    );
    assert.equal(view.hidden, true);
  });
});

describe('formatIceTeaser when (EDGE-002)', () => {
  it('says через N минут when the session starts within an hour', () => {
    const { formatIceTeaser } = loadModel();
    const view = formatIceTeaser(
      sampleTeaser({ starts_at_utc: '2026-09-06T08:15:00+00:00' }),
      new Date('2026-09-06T08:00:00Z')
    );
    assert.match(view.title, /через 15 минут/);
    assert.ok(!/сегодня/.test(view.title));
  });

  it('says завтра when the local date is tomorrow', () => {
    const { formatIceTeaser } = loadModel();
    const view = formatIceTeaser(
      sampleTeaser({
        local_date: '2026-09-07',
        starts_at_local: '15:30',
        starts_at_utc: '2026-09-07T12:30:00+00:00',
      }),
      new Date('2026-09-06T10:00:00Z')
    );
    assert.match(view.title, /завтра в 15:30/i);
  });
});

describe('renderIceTeaserHtml', () => {
  it('returns empty string when hidden — no «скоро» placeholder', () => {
    const { renderIceTeaserHtml } = loadModel();
    const html = renderIceTeaserHtml({ hidden: true, title: '', subtitle: '', href: '' });
    assert.equal(html, '');
    assert.ok(!/скоро/i.test(html));
  });

  it('renders a compact row that opens the arena card', () => {
    const { renderIceTeaserHtml } = loadModel();
    const html = renderIceTeaserHtml({
      hidden: false,
      title: 'Лёд рядом — сегодня в 11:00',
      subtitle: 'Чижовка · массовое, взр. 12 BYN',
      href: 'arena?ref=chizhovka',
    });
    assert.match(html, /hub-ice-teaser/);
    assert.match(html, /arena\?ref=chizhovka/);
    assert.match(html, /Лёд рядом — сегодня в 11:00/);
    assert.ok(!/скоро/i.test(html));
  });
});
