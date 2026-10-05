/**
 * GLIDE monochrome icons for «Ещё» sheets (client + trainer).
 * Load before mini-app-client-shell.js / mini-app-trainer-shell.js.
 */
(function (global) {
  'use strict';

  var STROKE = '1.75';

  /** Inner SVG paths only — viewBox 0 0 24 24. */
  var PATHS = {
    'client-saved':
      '<path d="M8.35 4.4h7.3c.55 0 1 .45 1 1v9.15L12 19.65l-4.65-5.1V5.4c0-.55.45-1 1-1z"/>',
    'client-activity':
      '<ellipse cx="12" cy="12.15" rx="7.35" ry="5.15"/>' +
      '<circle cx="17.15" cy="8.55" r="1.35" fill="currentColor" stroke="none"/>',
    'client-pass':
      '<path d="M4.35 7.7h15.3v2.15a1.65 1.65 0 0 0 0 3.15v2.15H4.35v-2.15a1.65 1.65 0 0 0 0-3.15V7.7z"/>' +
      '<path d="M9.2 9.55v4.9" stroke-dasharray="1.2 1.45"/>',
    'client-family':
      '<circle cx="8.05" cy="8.05" r="1.85"/>' +
      '<circle cx="15.95" cy="8.05" r="1.85"/>' +
      '<path d="M5.15 17.65c.55-3.05 1.85-4.4 2.9-4.4s2.35 1.35 2.9 4.4"/>' +
      '<path d="M13.05 17.65c.55-3.05 1.85-4.4 2.9-4.4s2.35 1.35 2.9 4.4"/>',
    'client-requests':
      '<path d="M6.15 6.05h10.5c.7 0 1.25.55 1.25 1.25v6.15c0 .7-.55 1.25-1.25 1.25H10.7L7.7 17.85V14.7H7.4c-.7 0-1.25-.55-1.25-1.25V7.3c0-.7.55-1.25 1.25-1.25z"/>' +
      '<path d="M8.55 9.55h6.7"/>',

    'trainer-profile':
      '<circle cx="12" cy="8.35" r="3.35"/>' +
      '<path d="M6.2 19.1v-.4a5.8 5.8 0 0 1 11.6 0v.4"/>',
    'trainer-pass':
      '<path d="M4.35 7.7h15.3v2.15a1.65 1.65 0 0 0 0 3.15v2.15H4.35v-2.15a1.65 1.65 0 0 0 0-3.15V7.7z"/>' +
      '<path d="M9.2 9.55v4.9" stroke-dasharray="1.2 1.45"/>',
    'trainer-subscription':
      '<rect x="3.25" y="6.75" width="17.5" height="10.5" rx="2"/>' +
      '<path d="M3.25 10.75h17.5"/>',
    'trainer-requests':
      '<path d="M6.15 6.05h10.5c.7 0 1.25.55 1.25 1.25v6.15c0 .7-.55 1.25-1.25 1.25H10.7L7.7 17.85V14.7H7.4c-.7 0-1.25-.55-1.25-1.25V7.3c0-.7.55-1.25 1.25-1.25z"/>' +
      '<path d="M8.55 9.55h6.7"/>',
    'trainer-stats':
      '<path d="M5 18V14M9 18V9M13 18v-6M17 18V7"/>' +
      '<path d="M4.5 18h16"/>',
    'trainer-groups':
      '<circle cx="8.2" cy="8.2" r="1.9"/>' +
      '<circle cx="15.8" cy="8.2" r="1.9"/>' +
      '<path d="M4.5 17.8c.6-3.1 2-4.5 3.7-4.5 1.2 0 2.1.75 2.8 2"/>' +
      '<path d="M19.5 17.8c-.6-3.1-2-4.5-3.7-4.5-1.2 0-2.1.75-2.8 2"/>',
    'trainer-referral':
      '<path d="M12 7.5v14"/>' +
      '<path d="M8.25 7.5h7.5a2 2 0 0 1 2 2v1.25H6.25V9.5a2 2 0 0 1 2-2z"/>' +
      '<path d="M6.25 10.75h11.5"/>',
    'trainer-collective':
      '<path d="M4.5 19.5h15"/>' +
      '<path d="M7.5 19.5V9.8L12 6.5l4.5 3.3V19.5"/>' +
      '<path d="M10 19.5v-4.5h4v4.5"/>',
  };

  function plateHtml(iconId) {
    var inner = PATHS[iconId];
    if (!inner) return '';
    return (
      '<span class="glide-more-plate" aria-hidden="true">' +
      '<svg class="glide-more-plate__svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' +
      STROKE +
      '" stroke-linecap="round" stroke-linejoin="round">' +
      inner +
      '</svg></span>'
    );
  }

  global.GlideMoreIcons = {
    plateHtml: plateHtml,
    has: function (iconId) {
      return Object.prototype.hasOwnProperty.call(PATHS, iconId);
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
