/**
 * TASK-350: окно «Показать вас родителям на …?» — кому показываем и что пишем.
 * Run: node --test tests/js/trainer-catalog-offer.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const O = require(path.resolve(__dirname, '../../static/webapp/trainer-catalog-offer.js'));

describe('TrainerCatalogOffer', () => {
  it('offers only a ready draft the trainer can publish himself', () => {
    const ready = { state: 'draft', can_act: true, readiness: { submit_ready: true } };
    assert.equal(O.eligible(ready), true);
    assert.equal(O.eligible({ ...ready, state: 'hidden' }), false, 'снял сам — не спорим с решением');
    assert.equal(O.eligible({ ...ready, state: 'published' }), false);
    assert.equal(O.eligible({ ...ready, can_act: false }), false, 'карточкой управляет студия');
    assert.equal(O.eligible({ ...ready, readiness: { submit_ready: false } }), false, 'POST вернул бы 422');
    assert.equal(O.eligible(null), false);
  });

  it('names the rinks where parents will see the card', () => {
    assert.equal(O.placesPhrase({ arena_names: ['ТЦ Замок'] }), 'ТЦ Замок');
    assert.equal(O.placesPhrase({ arena_names: ['ТЦ Замок', 'Чижовка'] }), 'ТЦ Замок и Чижовка');
    assert.equal(O.placesPhrase({ arena_names: ['А', 'Б', 'В', 'Г'] }), 'А, Б и ещё 2');
    assert.equal(O.placesPhrase({ arena_names: ['А'], arena_work_format: 'online' }), '');
    assert.equal(O.placesPhrase({}), '');
  });
});
