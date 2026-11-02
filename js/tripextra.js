/* js/tripextra.js: Work in the trip planner and the "Open this trip in Google Maps" hand-off. Loaded right after js/trip.js, which
   hands it the field points (S.trip.fieldPt) and the plan state (S.trip.st). Nothing here is stored, and nothing is requested. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt) return;
  var T = S.trip;
  if (!T || !T.fieldPt) return;
  var $ = S.util.$,
    el = S.util.el,
    isNum = S.util.isNum,
    state = S.util.state;
  S.tripextra = {};
  /* Fills the To field with a known place (used by the Indego station card). pt: {lat, lng, name}. */
  T.setDestination = function (pt) {
    T.tripSetField('to', pt.name, { pt: { lat: pt.lat, lng: pt.lng, name: pt.name } });
  };
  /* ----- Work: Use Work buttons, a Work chip and the Get me to work pill state (the pill's click is in js/panel.js) ----- */
  ['from', 'to'].forEach(function (w) {
    $(w === 'from' ? '#tripFromWork' : '#tripToWork').addEventListener('click', function () {
      var k = state.places.work;
      if (k) T.tripSetField(w, k.name, { pt: { lat: k.lat, lng: k.lng, name: k.name } });
    });
  });
  var renderBase = T.tripRenderPlaces;
  T.tripRenderPlaces = function () {
    renderBase();
    var h = state.places.home,
      k = state.places.work,
      chips = $('#tripChips');
    $('#tripFromWork').hidden = !k;
    $('#tripToWork').hidden = !k;
    if (k) $('#btnWork').removeAttribute('aria-disabled');
    else $('#btnWork').setAttribute('aria-disabled', 'true');
    $('#btnWork').title = k ? '' : 'Set a Work place in More first';
    if (!k) return;
    var b = el('button', 'btn small', 'Work');
    b.type = 'button';
    b.title = 'Work: ' + k.name;
    b.addEventListener('click', function () {
      T.tripSetField('to', k.name, { pt: { lat: k.lat, lng: k.lng, name: k.name } });
    });
    chips.insertBefore(b, chips.children[h ? 1 : 0] || null);
    while (chips.children.length > 6) chips.removeChild(chips.lastChild);
    chips.hidden = false;
  };
  /* ----- Open in Google Maps (hand-off for rail, which this planner does not plan) -----
   A plain link, shown (a) while the "No trip found" message is up, using the points that plan used, and (b) while Regional Rail is on
   in the filters and both From and To already hold coordinates (a Home, Work or place button, Use my location, a picked suggestion).
   A typed address that is not resolved yet is never looked up for this, so the link stays hidden. Nothing is sent to Google until it
   is tapped and nothing is stored: href exists only while the link is shown. Coordinates are written to 6 decimals. */
  function num(n) {
    return String(Number(n.toFixed(6)));
  }
  function gmUrl(o, d) {
    return (
      'https://www.google.com/maps/dir/?api=1&origin=' +
      num(o.lat) +
      ',' +
      num(o.lng) +
      '&destination=' +
      num(d.lat) +
      ',' +
      num(d.lng) +
      '&travelmode=transit'
    );
  }
  S.tripextra.gmUrl = gmUrl;
  var fp = T.fieldPt,
    vals = { from: fp.from, to: fp.to },
    none = null; /* {o, d}: the points of the plan that found no trip, while its message is showing */
  function pt(w) {
    var p = vals[w];
    if (p && p.kind === 'center') return { lat: state.center.lat, lng: state.center.lng };
    return p && p.pt ? p.pt : null;
  }
  function update() {
    var o = null,
      d = null,
      a = $('#tripGm');
    if (none) {
      o = none.o;
      d = none.d;
    } else if (state.filters.train) {
      o = pt('from');
      d = pt('to');
    }
    var ok = !!(o && d && isNum(o.lat) && isNum(o.lng) && isNum(d.lat) && isNum(d.lng));
    if (ok) a.href = gmUrl(o, d);
    else a.removeAttribute('href');
    $('#tripGmBox').hidden = !ok;
  }
  /* Every assignment to fieldPt (typing, a button, a picked suggestion, Swap) lands here. Editing a field drops the no-trip link. */
  ['from', 'to'].forEach(function (w) {
    Object.defineProperty(fp, w, {
      enumerable: true,
      configurable: true,
      get: function () {
        return vals[w];
      },
      set: function (v) {
        vals[w] = v;
        none = null;
        update();
      }
    });
  });
  new MutationObserver(function () {
    var shown = !!$('#tripNone');
    if (!shown) none = null;
    else if (!none && T.st.last) none = { o: T.st.last.o, d: T.st.last.d };
    update();
  }).observe($('#tripResults'), { childList: true });
  $('#modes').addEventListener('change', update);
  update();
})();
