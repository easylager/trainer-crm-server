/**
 * Single source of truth: when trainer can DM vs must use bot relay (mini-app / Web limitations).
 * Depends on window.Telegram.WebApp (platform) and TrainerClientRelayUi.openSendModal (relay sheet).
 */
(function (global) {
  'use strict';

  function stripUsername(u) {
    return String(u || '').replace(/^@/, '').trim();
  }

  function coerceSlotCapacity(raw) {
    var cap = parseInt(String(raw != null ? raw : '1'), 10);
    if (isNaN(cap) || cap < 1) return 1;
    return cap;
  }

  /**
   * Unified context — all decisions go through these fields only.
   * @typedef { {
   *   clientId: number|string|null|undefined,
   *   telegramId: string|number|null|undefined,
   *   telegramUsername: string,
   *   isSandbox: boolean,
   *   slotCapacity: number,
   *   clientPhone: string,
   * } } TrainerRelayContext
   */

  /** @returns { TrainerRelayContext } */
  function contextFromHubBooking(b) {
    b = b || {};
    return {
      clientId: b.client_id,
      telegramId: b.client_telegram_id,
      telegramUsername: stripUsername(b.client_telegram_username),
      isSandbox: !!b.is_sandbox,
      slotCapacity: coerceSlotCapacity(b.slot_capacity != null ? b.slot_capacity : 1),
      clientPhone: String(b.client_phone || '').trim(),
    };
  }

  /** Same shape as hub list rows (schedule booking detail). */
  function contextFromScheduleBooking(b) {
    return contextFromHubBooking(b);
  }

  /** Roster client card / list row. */
  function contextFromTrainerClient(c) {
    c = c || {};
    return {
      clientId: c.id,
      telegramId: c.telegram_id,
      telegramUsername: stripUsername(c.telegram_username),
      isSandbox: !!c.is_sandbox,
      slotCapacity: 1,
      clientPhone: String(c.phone || '').trim(),
    };
  }

  /** t.me / tg:// — blocked on Telegram Web when only telegram_id (no @username). */
  function canDirectTelegramDm(ctx) {
    if (!ctx) return false;
    if (isNaN(ctx.slotCapacity) || ctx.slotCapacity > 1) return false;
    if (ctx.telegramUsername) return true;
    var tid = ctx.telegramId;
    if (tid == null || tid === '') return false;
    var w = global.Telegram && global.Telegram.WebApp;
    if (w && w.platform === 'web') return false;
    return true;
  }

  /** Client in bot, no public @username — relay API + client bot delivery. */
  function relayEligible(ctx) {
    if (!ctx || ctx.isSandbox) return false;
    if (isNaN(ctx.slotCapacity) || ctx.slotCapacity > 1) return false;
    if (ctx.clientId == null || ctx.clientId === '') return false;
    var tid = ctx.telegramId;
    if (tid == null || tid === '') return false;
    if (ctx.telegramUsername) return false;
    return true;
  }

  function canShowTrainerMessageButton(ctx) {
    return relayEligible(ctx) || canDirectTelegramDm(ctx);
  }

  function shouldUseRelayModal(ctx) {
    return relayEligible(ctx) && !canDirectTelegramDm(ctx);
  }

  function scheduleBookingSubtitle(b) {
    b = b || {};
    var name = [b.client_first_name, b.client_last_name].filter(Boolean).join(' ').trim();
    if (name) return name;
    return String(b.client_phone || '').trim();
  }

  /**
   * @param { TrainerRelayContext } ctx
   * @param { { subtitle?: string, clientPhone?: string, onSent?: function() } } [extra]
   * @returns { boolean } true if relay UI opened
   */
  function openRelaySendModalForContext(ctx, extra) {
    extra = extra || {};
    var cid = ctx && ctx.clientId != null ? parseInt(String(ctx.clientId), 10) : NaN;
    if (isNaN(cid) || cid < 1) return false;
    var ui = global.TrainerClientRelayUi;
    if (!ui || typeof ui.openSendModal !== 'function') return false;
    var phone =
      extra.clientPhone != null && extra.clientPhone !== ''
        ? extra.clientPhone
        : ctx.clientPhone != null
          ? ctx.clientPhone
          : '';
    ui.openSendModal({
      clientId: cid,
      subtitle: extra.subtitle != null ? extra.subtitle : '',
      clientPhone: phone,
      onSent: extra.onSent,
    });
    return true;
  }

  /**
   * Reads data-* written by hub row HTML — keeps chrome + handlers free of duplicated parsing.
   * @returns { boolean }
   */
  function openRelayFromHubButton(btn) {
    if (!btn || btn.getAttribute('data-hub-relay') !== '1') return false;
    var cid = parseInt(String(btn.getAttribute('data-client-id') || ''), 10);
    var label = btn.getAttribute('data-client-label') || '';
    var phoneRaw = btn.getAttribute('data-client-phone') || '';
    if (isNaN(cid) || cid < 1) return false;
    var ui = global.TrainerClientRelayUi;
    if (!ui || typeof ui.openSendModal !== 'function') return false;
    ui.openSendModal({
      clientId: cid,
      subtitle: label,
      clientPhone: phoneRaw,
    });
    return true;
  }

  global.TrainerRelayHelpers = {
    contextFromHubBooking: contextFromHubBooking,
    contextFromScheduleBooking: contextFromScheduleBooking,
    contextFromTrainerClient: contextFromTrainerClient,
    canDirectTelegramDm: canDirectTelegramDm,
    relayEligible: relayEligible,
    canShowTrainerMessageButton: canShowTrainerMessageButton,
    shouldUseRelayModal: shouldUseRelayModal,
    scheduleBookingSubtitle: scheduleBookingSubtitle,
    openRelaySendModalForContext: openRelaySendModalForContext,
    openRelayFromHubButton: openRelayFromHubButton,
  };
})(typeof window !== 'undefined' ? window : globalThis);
