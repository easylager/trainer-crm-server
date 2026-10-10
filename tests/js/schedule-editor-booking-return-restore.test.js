/**
 * Return from booking detail must keep the trainer on the same day (not Monday)
 * and bring back the Mon–Sun strip — phone WebView regression.
 */
const fs = require('fs');
const path = require('path');
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

function read(name) {
  return fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'webapp', name), 'utf8');
}

describe('расписание: возврат из карточки записи', () => {
  const src = read('schedule-editor-main.js');
  const html = read('schedule-editor.html');

  it('полоска дней живёт вне #screenMain (иначе iOS гасит fixed после display:none)', () => {
    const mainOpen = html.indexOf('id="screenMain"');
    const detailOpen = html.indexOf('id="screenBookingDetail"');
    const stripOpen = html.indexOf('id="scheduleWeekDayStrip"');
    assert.ok(mainOpen > 0 && detailOpen > mainOpen && stripOpen > 0);
    assert.ok(
      stripOpen > mainOpen && stripOpen < detailOpen,
      'strip sits between main and booking detail'
    );
    // Closing of screenMain must happen before the strip.
    const mainSlice = html.slice(mainOpen, stripOpen);
    assert.ok(
      !mainSlice.includes('schedule-week-day-strip'),
      'strip markup must not be nested inside screenMain'
    );
    assert.match(html, /Outside #screenMain on purpose/);
  });

  it('есть восстановление скролла/дня после карточки записи', () => {
    assert.match(src, /function restoreScheduleViewAfterBooking/);
    assert.match(src, /scheduleViewRestorePending/);
    const start = src.indexOf('function syncAfterBookingPop');
    const body = src.slice(start, start + 1200);
    assert.match(body, /restoreAfterSlotsReady/);
    assert.match(body, /scheduleViewRestorePending = true/);
    assert.match(body, /onComplete:\s*restoreAfterSlotsReady/);
  });

  it('scroll-spy не ставит понедельник, пока идёт restore', () => {
    assert.match(
      src,
      /if \(!state\.scheduleViewRestorePending\) \{\s*installScheduleCalendarScrollSpy\(\);/
    );
    const restore = src.slice(
      src.indexOf('function restoreScheduleViewAfterBooking'),
      src.indexOf('function syncAfterBookingPop')
    );
    assert.match(restore, /scheduleStripScrollSyncSuppressUntil/);
    assert.match(restore, /cal-day-/);
    assert.match(restore, /nudgeScheduleStickyChrome/);
  });

  it('дата записи якорит выбранный день полоски', () => {
    const start = src.indexOf('function openBookingDetail');
    const body = src.slice(start, start + 1200);
    assert.match(body, /scheduleStripSelectedDate = String\(b\.slot_date\)/);
  });
});
