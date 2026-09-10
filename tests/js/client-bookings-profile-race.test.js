/**
 * Multi-profile: bookings list must not race ahead of ClientProfileSwitcher.
 *
 * Without X-Profile-Id the server resolves to self; create-booking uses the
 * default child — success screen, then empty «Мои записи».
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const root = path.join(__dirname, '..', '..', 'static', 'webapp');

function read(name) {
  return fs.readFileSync(path.join(root, name), 'utf8');
}

const bookingsHtml = read('client-bookings.html');
const switcherJs = read('client-profile-switcher.js');
const shellJs = read('mini-app-client-shell.js');
const homeMain = read('client-home-main.js');

assert.match(
  bookingsHtml,
  /ensureProfilesReady[\s\S]*ClientProfileSwitcher\.init/,
  'client-bookings must wait for profile switcher before listing'
);
assert.match(
  bookingsHtml,
  /bookingsFetchPromise = ensureProfilesReady\(\)\.then/,
  'startBookingsFetch must chain after profiles ready'
);
assert.doesNotMatch(
  bookingsHtml,
  /startBookingsFetch\(\);\s*\n\s*function/,
  'must not eagerly startBookingsFetch before loadBookings'
);

assert.match(
  switcherJs,
  /var readyPromise = null/,
  'ClientProfileSwitcher.init must be idempotent via shared readyPromise'
);

assert.match(shellJs, /tcb_bookings_warm_v2/, 'warm cache key must bump when profile-scoped');
assert.match(
  shellJs,
  /ClientProfileSwitcher\.init\(\)[\s\S]*\/api\/webapp\/client\/bookings/,
  'prefetchBookingsWarmCache must wait for profiles'
);
assert.match(shellJs, /profile_id/, 'warm cache payload must store acting profile_id');

assert.match(
  homeMain,
  /ClientProfileSwitcher\.init[\s\S]*\/client\/hub\/bootstrap/,
  'hub bootstrap must wait for acting profile'
);

console.log('ok: profile-scoped bookings fetch guards');
