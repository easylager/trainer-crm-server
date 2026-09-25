# Search Places Label Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename the client-search lens from «Покататься» to «Где заниматься» without changing its `skate` API intent.

**Architecture:** This is a display-only correction. The existing `skate` intent remains the internal list and map contract; visible labels and user-facing copy describe the broadened set of venues.

**Tech Stack:** Static HTML, JavaScript view model, Node.js built-in test runner, pytest HTML contract test.

---

### Task 1: Replace the client-facing lens label

**Files:**
- Modify: `static/webapp/ice.html:61`
- Modify: `static/webapp/ice.html:137`
- Modify: `static/webapp/ice-tab-model.js:101`
- Modify: `static/webapp/ice-map-model.js:89`
- Modify: `tests/js/ice-tab-model.test.js:89`
- Modify: `tests/js/ice-tab-model.test.js:295`
- Modify: `tests/js/ice-tab-model.test.js:604`
- Modify: `tests/api/test_ice_tab_webapp.py:56`

**Step 1: Update the HTML contract test**

Replace its expected `Покататься` label with `Где заниматься`.

**Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/api/test_ice_tab_webapp.py -v`

Expected: fail until the page label is updated.

**Step 3: Replace visible copy only**

Keep `data-intent="skate"`, URL `intent=skate`, and model function names unchanged. Replace only labels and explanatory copy that users can see.

**Step 4: Update JavaScript test descriptions and assertions**

Use «Где заниматься» in user-facing assertions; keep references to the internal `skate` intent where they describe a code contract.

**Step 5: Run focused checks**

Run: `node --test tests/js/ice-tab-model.test.js`

Expected: all tests pass.

Run: `python -m pytest tests/api/test_ice_tab_webapp.py -v`

Expected: all tests pass.
