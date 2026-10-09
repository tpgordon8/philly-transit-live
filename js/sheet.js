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
  /* Reaching any control below the search field (Tab, or a tap on one) opens the sheet; the search field itself works while it peeks.
     Once the keyboard has settled the field being typed in is scrolled into view. */
  panel.addEventListener('focusin', function (e) {
    var t = e.target;
    if (t !== handle && t.id !== 'addr' && t.id !== 'btnSearch') setOpen(true);
    if (!t.matches(FIELD)) return;
    setTimeout(function () {
      if (document.activeElement !== t) return;
      fitKeyboard();
      t.scrollIntoView({ block: 'nearest' });
    }, KEYBOARD_SETTLE_MS);
  });
  setOpen(false);
  S.sheet.setOpen = setOpen;
  S.sheet.fitKeyboard = fitKeyboard;
})();
