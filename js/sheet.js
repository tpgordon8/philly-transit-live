/* js/sheet.js: the phone bottom sheet and the on-screen keyboard. Up to 760 px wide the panel is a sheet under the map (css/layout.css):
   peek shows the handle, the status line and the search field; open shows everything. Wider screens ignore both states. */
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
    /^(addr|btnSearch|btnLocatePeek|myPill|welcomeOk)$/; /* what the closed sheet shows: working them must not open it */
  var KEYBOARD_MIN_PX = 80; /* a visual viewport this much shorter than the layout viewport is an on-screen keyboard */
  var PINCH_EPSILON = 0.01; /* a visual viewport scale this far from 1 means the user pinch-zoomed */
  var KEYBOARD_SETTLE_MS = 350; /* the keyboard animates in; measure after it has stopped */
  /* The map's box changed: Leaflet is told, and the view is put back exactly (its own re-centring rounds to whole pixels).
     Nothing happens when the box kept its size, as on a wide screen where the sheet states do not apply. */
  function resizeMap() {
    var box = map.getContainer(),
      size = map.getSize();
    if (box.clientWidth === size.x && box.clientHeight === size.y) return;
    var c = map.getCenter(),
      z = map.getZoom();
    map.invalidateSize({ animate: false, pan: false });
    map.setView(c, z, { animate: false });
  }
  function setOpen(open) {
    if ((app.dataset.sheet === 'open') === open && app.dataset.sheet) return;
    app.dataset.sheet = open ? 'open' : 'peek';
    handle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) panel.scrollTop = 0;
    resizeMap();
  }
  handle.addEventListener('click', function () {
    setOpen(app.dataset.sheet !== 'open');
  });
  /* A browser that leaves the layout alone for the keyboard (iOS) reports it only through visualViewport: shrink the page by the covered
     height so the sheet and the field being typed in end up above the keyboard. Browsers that resize the layout report 0 here.
     A pinch-zoomed page also has a shorter visual viewport but no keyboard, so --kb applies only at scale 1 with a text field focused. */
  function fitKeyboard() {
    var vv = window.visualViewport;
    if (!vv) return;
    var a = document.activeElement;
    var typing = !!(a && a.matches && a.matches(FIELD));
    var unzoomed = Math.abs((vv.scale || 1) - 1) < PINCH_EPSILON;
    var covered = window.innerHeight - vv.height - vv.offsetTop;
    var kb = (typing && unzoomed && covered > KEYBOARD_MIN_PX ? Math.round(covered) : 0) + 'px';
    if ((root.style.getPropertyValue('--kb') || '0px') !== kb) {
      root.style.setProperty('--kb', kb);
      resizeMap();
    }
    if (typing && panel.contains(a)) a.scrollIntoView({ block: 'nearest' });
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', fitKeyboard);
    window.visualViewport.addEventListener('scroll', fitKeyboard);
  }
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
    loc = $('#btnLocate'),
    peekLoc = $('#btnLocatePeek'),
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
    resizeMap(); /* in peek the row changes the map row's height by --pillrow */
  }
  pill.addEventListener('click', function () {
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
    setOpen(true);
    note.scrollIntoView({ block: 'nearest' });
  }).observe(note, {
    childList: true,
    characterData: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class']
  });
  /* The icon button in the peek row is the same button as Use my location: it clicks it, and follows its disabled state. */
  peekLoc.addEventListener('click', function () {
    loc.click();
  });
  new MutationObserver(function () {
    peekLoc.disabled = loc.disabled;
  }).observe(loc, { attributes: true, attributeFilter: ['disabled'] });
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
  syncPill(); /* before the first paint, so a saved filter never moves the map afterwards */
  setOpen(false);
  S.sheet.syncPill = syncPill;
  S.sheet.starTip = starTip;
  S.sheet.setOpen = setOpen;
  S.sheet.fitKeyboard = fitKeyboard;
})();
