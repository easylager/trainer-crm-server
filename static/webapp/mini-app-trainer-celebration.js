/**
 * One-shot celebration payload for trainer hub after subscription purchase.
 * Uses sessionStorage (same origin); consumed on hub load so banner shows once per tab session.
 */
(function () {
  var STORAGE_KEY = 'trainer_hub_subscription_celebration_v1';

  var TIER_FEATURE_META = {
    crm: { label: 'CRM и клиентская база', icon: '📋' },
    online: { label: 'Онлайн-запись клиентов', icon: '🌐' },
    analytics: { label: 'Аналитика и отчёты', icon: '📊' },
    groups: { label: 'Группы', icon: '👥' },
  };

  /**
   * Build feature rows for hub banner from API `unlocked_features` (strings: crm, online, analytics).
   */
  function featuresFromUnlockedList(unlocked) {
    if (!unlocked || !unlocked.length) return [];
    var out = [];
    var order = ['crm', 'online', 'analytics', 'groups'];
    order.forEach(function (id) {
      if (unlocked.indexOf(id) === -1) return;
      var m = TIER_FEATURE_META[id];
      if (m) out.push({ id: id, label: m.label, icon: m.icon });
    });
    return out;
  }

  /**
   * Build feature rows from tier catalog `includes_tiers` (subset of crm/online/analytics).
   */
  function featuresFromIncludesTiers(includesTiers) {
    if (!includesTiers || !includesTiers.length) return [];
    return featuresFromUnlockedList(includesTiers);
  }

  function setTrainerHubSubscriptionCelebration(payload) {
    if (!payload || typeof payload !== 'object') return;
    var body = Object.assign({ v: 1 }, payload);
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(body));
    } catch (e) {
      /* quota or private mode */
    }
  }

  function takeTrainerHubSubscriptionCelebration() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      sessionStorage.removeItem(STORAGE_KEY);
      var data = JSON.parse(raw);
      if (!data || data.v !== 1) return null;
      return data;
    } catch (e) {
      try {
        sessionStorage.removeItem(STORAGE_KEY);
      } catch (e2) { /* */ }
      return null;
    }
  }

  window.TrainerHubCelebration = {
    set: setTrainerHubSubscriptionCelebration,
    take: takeTrainerHubSubscriptionCelebration,
    featuresFromUnlockedList: featuresFromUnlockedList,
    featuresFromIncludesTiers: featuresFromIncludesTiers,
  };
})();
