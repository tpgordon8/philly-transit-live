/* js/sheet.js: the phone bottom sheet, the phone tab bar and the on-screen keyboard. Up to 760 px wide the panel is a sheet under the
   map (css/layout.css): peek shows the handle, the status line, the search bar and the quick actions; open shows the rest of the
   current tab. The tab bar (Map, Trip, Board, Alerts, More) picks which sections the sheet shows. Wider screens and phone landscape
   ignore the sheet states and the tabs: every section shows in the side panel. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt) return;
  var $ = S.util.$,
    map = S.map.map;
  var app = $('#app'),
    handle = $('#sheetHandle'),
    panel = $('#panel'),
    root = document.documentElement;
  var FIELD = 'input, select, textarea';
  var PEEK_CONTROLS =
    /^(addr|btnSearch|btnLocate|btnHome|btnSavePlace|myPill|welcomeOk)$/; /* what the closed sheet shows: working them must not open it */
  var TEXT_FIELD =
    'input[type=text], input[type=search], input:not([type]), textarea'; /* focus raises an on-screen keyboard */
  var KEYBOARD_MIN_PX = 80; /* a visual viewport this much shorter than the layout viewport is an on-screen keyboard */
  var PINCH_EPSILON = 0.01; /* a visual viewport scale this far from 1 means the user pinch-zoomed */
  var KEYBOARD_SETTLE_MS = 350; /* the keyboard animates in; measure after it has stopped */
  var TYPING_DELAY_MS = 250; /* the bar steps aside this long after a field gets focus: after the tap's click, as the keyboard rises */
  var SHEET_GLIDE_MS = 260; /* the sheet's height transition (css/layout.css, 220 ms) plus a frame or two */
  /* The map's box changed: Leaflet is told, and the view is put back exactly (its own re-centring rounds to whole pixels).
     Nothing happens when the box kept its size, as on a wide screen where the sheet states do not apply. */
  var glideView =
    null; /* the view to keep while the sheet glides, taken once so per-frame rounding cannot drift it */
  function resizeMap() {
    var box = map.getContainer(),
      size = map.getSize();
    if (box.clientWidth === size.x && box.clientHeight === size.y) return;
    var keep =
      glideView && Date.now() < glideEnd + SHEET_GLIDE_MS
        ? glideView
        : null; /* never an old view after a stalled glide */
    var c = keep ? keep.c : map.getCenter(),
      z = keep ? keep.z : map.getZoom();
    map.invalidateSize({ animate: false, pan: false });
    map.setView(c, z, { animate: false });
  }
  /* While the sheet glides (css/layout.css) the map's box changes every frame: Leaflet follows it until the glide is over. */
  var glideEnd = 0;
  function followSheet() {
    var running = Date.now() < glideEnd;
    glideEnd = Date.now() + SHEET_GLIDE_MS;
    if (running) return; /* the frame loop below is already going and now runs longer */
    if (!glideView) glideView = { c: map.getCenter(), z: map.getZoom() };
    (function step() {
      resizeMap();
      if (Date.now() < glideEnd) requestAnimationFrame(step);
      else glideView = null;
    })();
  }
  app.addEventListener('transitionend', function (e) {
    if (e.target === app) resizeMap();
  });
  function setOpen(open) {
    if ((app.dataset.sheet === 'open') === open && app.dataset.sheet) return;
    app.dataset.sheet = open ? 'open' : 'peek';
    handle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) panel.scrollTop = 0;
    followSheet();
  }
  handle.addEventListener('click', function () {
    setOpen(app.dataset.sheet !== 'open');
  });
  /* A browser that leaves the layout alone for the keyboard (iOS) reports it only through visualViewport: shrink the page by the covered
     height so the sheet and the field being typed in end up above the keyboard. Browsers that resize the layout report 0 here.
     A pinch-zoomed page also has a shorter visual viewport but no keyboard, so --kb applies only at scale 1 with a text field focused. */
  function applyKeyboard() {
    var vv = window.visualViewport;
    if (!vv) return null;
    var a = document.activeElement;
    var typing = !!(a && a.matches && a.matches(FIELD));
    var unzoomed = Math.abs((vv.scale || 1) - 1) < PINCH_EPSILON;
    var covered = window.innerHeight - vv.height - vv.offsetTop;
    /* iOS pans the page up to bring a tapped field into view, which scrolls the map and the top of the sheet out of sight and leaves
       blank space under a shrunk page. The page is one screen tall, so it never needs that pan: put it back and measure again. */
    if (typing && unzoomed && covered > KEYBOARD_MIN_PX && (vv.offsetTop > 1 || window.scrollY > 1)) {
      window.scrollTo(0, 0);
      covered = window.innerHeight - vv.height;
    }
    var kb = (typing && unzoomed && covered > KEYBOARD_MIN_PX ? Math.round(covered) : 0) + 'px';
    if ((root.style.getPropertyValue('--kb') || '0px') !== kb) {
      root.style.setProperty('--kb', kb);
      resizeMap();
    }
    return { typing: typing, field: a };
  }
  function fitKeyboard() {
    var r = applyKeyboard();
    if (r && r.typing && panel.contains(r.field)) r.field.scrollIntoView({ block: 'nearest' });
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', fitKeyboard);
    window.visualViewport.addEventListener('scroll', fitKeyboard);
  }
  /* iOS can drop focus after its last viewport event (Done, a swipe, a tap on the map), which would leave the page shrunk for a keyboard
     that is gone. Re-check when focus leaves, when the page returns or turns, and on a short watchdog while the page is shrunk. */
  function recheckKeyboard() {
    applyKeyboard();
    setTimeout(applyKeyboard, 120);
    setTimeout(applyKeyboard, 450);
  }
  document.addEventListener('focusout', recheckKeyboard);
  window.addEventListener('pageshow', recheckKeyboard);
  window.addEventListener('orientationchange', recheckKeyboard);
  window.addEventListener('resize', applyKeyboard);
  setInterval(function () {
    if ((root.style.getPropertyValue('--kb') || '0px') !== '0px') applyKeyboard();
  }, 500);
  /* Reaching any control below the peek row (Tab, or a tap on one) opens the sheet; the peek row (search, Use my location, the My routes pill) works while it peeks.
     Once the keyboard has settled the field being typed in is scrolled into view. */
  panel.addEventListener('focusin', function (e) {
    var t = e.target;
    if (t !== handle && !PEEK_CONTROLS.test(t.id)) setOpen(true);
    if (!t.matches(FIELD)) return;
    setTimeout(function () {
      if (document.activeElement !== t) return;
      fitKeyboard();
      t.scrollIntoView({ block: 'nearest' });
    }, KEYBOARD_SETTLE_MS);
  });
  /* ----- Peek row and first-run hints ----- */
  var util = S.util,
    note = $('#note'),
    pill = $('#myPill'),
    pillRow = $('#myPillRow'),
    welcome = $('#welcome');
  function setOnlyMine(on) {
    util.routesStore.onlyMine = on;
    util.saveRoutes();
    S.feed.apply();
  }
  /* The header pill shows while the My routes filter is on, so the filter is never a surprise and one tap turns it off. */
  function syncPill() {
    var on = util.routeFilterOn();
    if (pillRow.hidden !== on) return;
    pillRow.hidden = !on;
    followSheet(); /* in peek the row changes the map row's height by --pillrow */
  }
  pill.addEventListener('click', function () {
    show('map'); /* the pill is about the vehicles on the map */
    setOnlyMine(false);
  });
  /* After the first star: a toast that offers to show only starred routes (skipped when the filter is already on). */
  function starTip(k) {
    if (util.routeFilterOn()) return;
    var n = S.panel.starName(k);
    S.alerts.toastAction(
      (k.indexOf('train:') === 0 ? n + ' route' : 'Route ' + n) + ' starred.',
      'Show only my routes',
      function () {
        setOnlyMine(true);
      }
    );
  }
  /* A search or location error is written to #note, which a closed sheet hides: open the sheet so the message is on screen. */
  new MutationObserver(function () {
    if (!note.classList.contains('bad') || !note.textContent) return;
    show('map', { open: true });
    note.scrollIntoView({ block: 'nearest' });
  }).observe(note, {
    childList: true,
    characterData: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class']
  });
  if (util.firstVisit && !util.seen.welcome) welcome.hidden = false;
  function dismissWelcome() {
    if (welcome.hidden) return;
    var inside = welcome.contains(document.activeElement);
    util.markSeen('welcome');
    welcome.hidden = true;
    /* the focused button just vanished: keep keyboard focus somewhere useful */
    if (inside) $('#addr').focus();
  }
  $('#welcomeOk').addEventListener('click', dismissWelcome);
  /* Escape dismisses the card only when it is the thing Escape is meant for: focus is inside it, or it is on screen and nothing else
     that Escape closes is open (vehicle, stop and Indego cards, a toast) and focus is on the page itself. It listens in the capture
     phase: the other handlers close their card on this same keypress, and the check must see the page as it was before them. */
  document.addEventListener(
    'keydown',
    function (e) {
      if (e.key !== 'Escape' || welcome.hidden || e.defaultPrevented) return;
      var a = document.activeElement,
        mine = welcome.contains(a),
        idle = !a || a === document.body || a === document.documentElement;
      if (
        !mine &&
        !(
          idle &&
          welcome.getClientRects().length &&
          !document.querySelector(
            '#detail:not([hidden]), #stopCard:not([hidden]), #indegoCard:not([hidden]), #toasts .toast'
          )
        )
      )
        return;
      dismissWelcome();
    },
    true
  );
  /* ----- Tabs (phone portrait) -----
     The sections in #panel carry data-tab (map, trip, alerts, more; the board section says "board" and only shows on wide screens).
     #app[data-tab] names the current tab and css/layout.css shows only its sections up to 760 px wide, outside phone landscape.
     Board is not a section: its tab opens the full-screen board (js/boardview.js, #board) and closing it leaves the tab as it was.
     The tab a person picks is remembered in septa.tab.v1 (a plain string, read and written in try/catch, no "Can't save" toast);
     tabs that an action switches to (Get me home, Walk here, a stop link) are not remembered. */
  var TABS = ['map', 'trip', 'alerts', 'more'],
    TAB_KEY = 'septa.tab.v1';
  var bar = $('#tabbar'),
    boardView = $('#boardView'),
    tabBtns = bar.querySelectorAll('.tab');
  var NARROW = window.matchMedia('(max-width: 760px)'),
    LANDSCAPE = window.matchMedia('(max-width: 760px) and (max-height: 500px) and (orientation: landscape)');
  function tabsOn() {
    return NARROW.matches && !LANDSCAPE.matches;
  }
  function readTab() {
    try {
      var t = localStorage.getItem(TAB_KEY);
      return TABS.indexOf(t) >= 0 ? t : 'map';
    } catch (e) {
      return 'map';
    }
  }
  function saveTab(t) {
    try {
      if (localStorage.getItem(TAB_KEY) !== t) localStorage.setItem(TAB_KEY, t);
    } catch (e) {
      /* private mode or full storage: the tab is simply not remembered */
    }
  }
  var tab = readTab();
  function paintTab() {
    app.dataset.tab = tab;
    tabBtns.forEach(function (b) {
      if (b.dataset.go === tab) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
  }
  /* Switch the sheet to a tab. opts.open forces the sheet state; otherwise a new tab opens the sheet, and Map closes it to the peek. */
  function show(t, opts) {
    opts = opts || {};
    if (TABS.indexOf(t) < 0) return;
    var changed = t !== tab;
    tab = t;
    paintTab();
    if (opts.save) saveTab(t);
    if (changed) panel.scrollTop = 0;
    if (!tabsOn()) return;
    if (typeof opts.open === 'boolean') setOpen(opts.open);
    else if (changed) setOpen(t !== 'map');
  }
  /* The tab whose section holds an element (nothing for the header, the cards or anything outside the panel). */
  function tabOf(node) {
    var sec = node && node.closest ? node.closest('#panel > [data-tab]') : null;
    return sec && TABS.indexOf(sec.dataset.tab) >= 0 ? sec.dataset.tab : null;
  }
  function reveal(node, open) {
    var t = tabOf(node);
    if (t) show(t, { open: open !== false });
  }
  var boardFromTab = false;
  bar.addEventListener('click', function (e) {
    var b = e.target.closest('.tab');
    if (!b) return;
    var t = b.dataset.go;
    if (t === 'board') {
      /* js/boardview.js opens on the hash, so Back to map, Escape and the browser's Back all close it */
      boardFromTab = true;
      location.hash = '#board';
      return;
    }
    if (t !== tab) show(t, { save: true });
    else if (t === 'map') setOpen(app.dataset.sheet !== 'open'); /* the current Map tab toggles the sheet */
    else if (app.dataset.sheet !== 'open') setOpen(true);
    else panel.scrollTop = 0; /* the current tab again: back to its top */
  });
  /* The board gives focus back to the control that opened it, or to its Board button, which a phone does not show (the tab bar has
     Board): there focus goes to the Board tab. The tab itself never changed, so the person is back where they were. */
  if (boardView)
    new MutationObserver(function () {
      if (!boardView.hidden) return;
      var a = document.activeElement,
        lost = !a || a === document.body || !a.getClientRects().length;
      if (tabsOn() && (boardFromTab || lost)) $('#tabBoard').focus({ preventScroll: true });
      boardFromTab = false;
      resizeMap();
    }).observe(boardView, { attributes: true, attributeFilter: ['hidden'] });
  /* A stop link (#stop=...) opens the stop card over the map: the Map tab comes forward with the sheet closed. */
  function stopLinkTab() {
    if (/[#&]stop=/.test(location.hash)) show('map', { open: false });
  }
  window.addEventListener('hashchange', stopLinkTab);
  /* Alerts tab badge: the number of service alerts in view (the count js/alerts.js writes next to the Service alerts heading). */
  var alertCount = $('#alertCount'),
    badge = $('#tabAlertN'),
    badgeSr = $('#tabAlertSr');
  function syncBadge() {
    var m = /(\d+)/.exec(alertCount.textContent || ''),
      n = m ? Number(m[1]) : 0;
    badge.hidden = !n;
    badge.textContent = n > 99 ? '99+' : String(n);
    badgeSr.textContent = n ? ', ' + n + ' service alert' + (n === 1 ? '' : 's') : '';
  }
  new MutationObserver(syncBadge).observe(alertCount, {
    childList: true,
    characterData: true,
    subtree: true
  });
  syncBadge();
  /* While a text field has focus the on-screen keyboard is up (or about to be): the tab bar steps aside (css/layout.css,
     :root[data-typing]) so the sheet keeps the room. It waits TYPING_DELAY_MS after focus, so the sheet does not move under the finger
     before the tap's click lands, and comes back one tick after focus leaves, so moving between two fields does not flash it. */
  function syncTyping() {
    var a = document.activeElement,
      on = !!(a && a.matches && a.matches(TEXT_FIELD) && !a.readOnly);
    if (on === (root.dataset.typing === '1')) return;
    if (on) root.dataset.typing = '1';
    else delete root.dataset.typing;
    resizeMap();
  }
  document.addEventListener('focusin', function () {
    setTimeout(syncTyping, TYPING_DELAY_MS);
  });
  document.addEventListener('focusout', function () {
    setTimeout(syncTyping, 0);
  });
  /* Anything that sets a trip destination (the Indego card's Walk here) brings the planner forward. */
  if (S.trip && typeof S.trip.setDestination === 'function') {
    var setDestination = S.trip.setDestination;
    S.trip.setDestination = function () {
      show('trip', { open: true });
      return setDestination.apply(this, arguments);
    };
  }
  /* Save place in the quick actions: shown while there is a place to save; it opens More at the name field. */
  var saveForm = $('#saveForm'),
    savePill = $('#btnSavePlace');
  function syncSavePill() {
    savePill.hidden = saveForm.hidden;
  }
  new MutationObserver(syncSavePill).observe(saveForm, { attributes: true, attributeFilter: ['hidden'] });
  syncSavePill();
  savePill.addEventListener('click', function () {
    show('more', { open: true });
    var f = $('#placeName');
    f.focus({ preventScroll: true });
    f.scrollIntoView({ block: 'nearest' });
  });
  paintTab();
  root.dataset.tabs = '1'; /* shows the bar; its room was kept from the first paint (css/layout.css) */
  syncPill(); /* before the first paint, so a saved filter never moves the map afterwards */
  setOpen(false);
  stopLinkTab();
  if (tabsOn() && tab !== 'map') setOpen(true);
  S.sheet.show = show;
  S.sheet.reveal = reveal;
  S.sheet.tab = function () {
    return tab;
  };
  S.sheet.syncPill = syncPill;
  S.sheet.starTip = starTip;
  S.sheet.setOpen = setOpen;
  S.sheet.fitKeyboard = fitKeyboard;
})();
