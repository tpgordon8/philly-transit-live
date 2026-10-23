/* js/swipe.js: swipe the phone bottom sheet open or closed (ARCHITECTURE.md section 15.10). Drag the handle or the header, or anywhere on the
   closed sheet that is not a field, and the sheet follows the finger; on release it settles open or closed by speed or by which half it
   is in. A tap on the handle still toggles it. Wide screens and phone landscape have no sheet, so nothing happens there. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt) return;
  var sh = S.sheet;
  if (!sh || typeof sh.setOpen !== 'function') return;
  var $ = S.util.$,
    app = $('#app'),
    panel = $('#panel'),
    handle = $('#sheetHandle'),
    head = panel.querySelector('.brand');
  var START_PX = 8; /* a drag starts after this much vertical travel */
  var FLICK_PX_MS = 0.45; /* faster than this settles the sheet in the direction of travel, wherever it is */
  var SAMPLE_MS = 90; /* speed is measured over the last part of the drag */
  var st = null; /* the gesture in progress: {id, y0, x0, h0, lo, hi, on, h, pts} */
  var swallow = false; /* the click that ends a drag must not toggle the sheet */

  function sheetOn() {
    return getComputedStyle(handle).display !== 'none' && !!app.dataset.sheet;
  }
  function typing() {
    var a = document.activeElement;
    return !!(a && a.matches && a.matches('input, select, textarea') && panel.contains(a));
  }
  function range() {
    /* from the closed height to the open height of the current tab (css/layout.css: 50%, or 60% on Alerts and More) */
    var open = app.dataset.sheet === 'open',
      h = panel.getBoundingClientRect().height,
      full = app.clientHeight * (/^(alerts|more)$/.test(app.dataset.tab || '') ? 0.6 : 0.5);
    return open ? { lo: Math.min(h, full) * 0.5, hi: h, h0: h } : { lo: h, hi: Math.max(h, full), h0: h };
  }
  function canStart(e) {
    if (!sheetOn() || typing() || (e.pointerType === 'mouse' && e.button !== 0)) return false;
    var t = e.target;
    if (handle.contains(t) || (head && head.contains(t))) return true;
    /* the closed sheet does not scroll, so a drag anywhere on it (but not in a field) can only mean "open" */
    return (
      app.dataset.sheet === 'peek' && panel.contains(t) && !t.closest('input, select, textarea, .sug-list')
    );
  }
  function draw() {
    if (!st) return;
    st.raf = 0;
    app.style.gridTemplateRows = 'minmax(0,1fr) ' + Math.round(st.h) + 'px';
    if (sh.resizeMap) sh.resizeMap();
  }
  function onDown(e) {
    if (st || !canStart(e)) return;
    var r = range();
    st = {
      id: e.pointerId,
      x0: e.clientX,
      y0: e.clientY,
      h0: r.h0,
      lo: r.lo,
      hi: r.hi,
      on: false,
      h: r.h0,
      pts: [],
      raf: 0
    };
  }
  function onMove(e) {
    if (!st || e.pointerId !== st.id) return;
    var dy = e.clientY - st.y0,
      dx = e.clientX - st.x0;
    if (!st.on) {
      if (Math.abs(dy) < START_PX) return;
      if (Math.abs(dx) > Math.abs(dy)) {
        st = null; /* a sideways swipe is not ours */
        return;
      }
      st.on = true;
      app.classList.add('sheet-drag');
      try {
        panel.setPointerCapture(e.pointerId);
      } catch (x) {
        /* the gesture still works without capture */
      }
    }
    st.h = Math.max(st.lo, Math.min(st.hi, st.h0 - dy));
    st.pts.push({ t: e.timeStamp, y: e.clientY });
    while (st.pts.length > 2 && e.timeStamp - st.pts[0].t > SAMPLE_MS) st.pts.shift();
    if (!st.raf) st.raf = requestAnimationFrame(draw);
    e.preventDefault();
  }
  function onEnd(e) {
    if (!st || e.pointerId !== st.id) return;
    var g = st;
    st = null;
    if (!g.on) return; /* a tap: the click handlers do their normal work */
    if (g.raf) cancelAnimationFrame(g.raf);
    var p = g.pts,
      v =
        p.length > 1
          ? (p[p.length - 1].y - p[0].y) / Math.max(1, p[p.length - 1].t - p[0].t)
          : 0; /* px per ms, negative is up */
    var open;
    if (e.type === 'pointercancel') open = app.dataset.sheet === 'open';
    else if (Math.abs(v) > FLICK_PX_MS) open = v < 0;
    else open = g.h > (g.lo + g.hi) / 2;
    swallow = true;
    setTimeout(function () {
      swallow = false;
    }, 120);
    app.classList.remove('sheet-drag');
    /* the stylesheet's rows again: the sheet glides from here to the settled height */
    app.style.removeProperty('grid-template-rows');
    sh.setOpen(open);
    if (sh.follow) sh.follow();
    if (navigator.vibrate && e.type !== 'pointercancel') {
      try {
        navigator.vibrate(6);
      } catch (x) {
        /* not every browser allows it */
      }
    }
  }
  panel.addEventListener('pointerdown', onDown);
  /* on the document: a mouse that leaves the panel mid-drag is not captured until the drag has started */
  document.addEventListener('pointermove', onMove, { passive: false });
  document.addEventListener('pointerup', onEnd);
  document.addEventListener('pointercancel', onEnd);
  /* a drag that ends over a button must not press it */
  panel.addEventListener(
    'click',
    function (e) {
      if (!swallow) return;
      e.stopPropagation();
      e.preventDefault();
    },
    true
  );
  /* the same moves from a keyboard or a screen reader: Up opens, Down closes while the handle has focus */
  handle.addEventListener('keydown', function (e) {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();
    sh.setOpen(e.key === 'ArrowUp');
  });
  S.swipe.active = sheetOn;
})();
