'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const Api = require(path.resolve(__dirname, '../../static/shared/list-scroll-restore.js'));

function memStorage() {
  const mem = Object.create(null);
  return {
    getItem: (k) => (k in mem ? mem[k] : null),
    setItem: (k, v) => {
      mem[k] = String(v);
    },
    removeItem: (k) => {
      delete mem[k];
    },
    _mem: mem,
  };
}

describe('list-scroll-restore (public /c/ and ice-today)', () => {
  it('keys scroll by pathname+search so /p/ does not steal list offset', () => {
    assert.equal(Api.storageKey('/c/minsk', '?t=ice'), 'glidePublicListScroll:/c/minsk?t=ice');
    assert.notEqual(Api.storageKey('/c/minsk', ''), Api.storageKey('/p/minsk/zamok', ''));
  });

  it('saves positive scroll and consumes once', () => {
    const storage = memStorage();
    assert.equal(Api.save(storage, '/c/minsk', '', 0), false);
    assert.equal(Api.save(storage, '/c/minsk', '', 640), true);
    assert.equal(Api.consume(storage, '/c/minsk', ''), 640);
    assert.equal(Api.consume(storage, '/c/minsk', ''), 0);
  });

  it('ignores invalid stored values', () => {
    const storage = memStorage();
    storage.setItem(Api.storageKey('/c/minsk', ''), 'nope');
    assert.equal(Api.consume(storage, '/c/minsk', ''), 0);
  });
});
