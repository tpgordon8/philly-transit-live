/* js/maplod.js: level of detail for the vehicle markers (ARCHITECTURE.md 4.1). Every vehicle keeps its own marker (js/map.js); this file only
   decides how each one looks at the current zoom: compact or full, route label shown or not, dimmed or prominent, or folded into a
   count badge. Zoomed out (14 and below) markers are compact, at 15 full size; at both, labels never overlap and markers that pile up
   collapse into a badge. From 16 every marker is full and labelled. The selected vehicle, starred routes and routes serving pinned,
   open or nearby stops are never folded away, always labelled first, and the rest dim while any of them is on the map. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt) return;
  var isStarred = S.util.isStarred,
    starKey = S.util.starKey,
    state = S.util.state;
  var map = S.map.map,
    mapEl = S.map.mapEl,
    markers = S.map.markers,
    animOK = S.map.animOK;
  var FAR_MAX_ZOOM = 14 /* at this zoom and below markers are compact */,
    NEAR_MIN_ZOOM = 16 /* from this zoom every marker is full size and labelled, nothing folds or dims */,
    MAX_EXPAND_ZOOM = 17 /* tapping a badge never zooms in further than this (unless already closer) */,
    HOT_Z = 500 /* z offset of a prominent marker (map.js adds it; selected is 1000, focused 2000) */,
    CLU_Z = 300;
  /* Fold radius in screen pixels and the smallest pile that becomes a badge, per level. */
  var LEVELS = {
    far: { r: 36, min: 3, ch: 6, pad: 6, h: 14 },
    mid: { r: 30, min: 4, ch: 7.2, pad: 8, h: 16 }
  };
  var list = [],
    hotKeys = new Set(),
    clusters = new Map() /* anchor vehicle key -> badge marker */,
    lastSig = '';

  /* Routes the rider cares about: pinned board stops, the open stop and the Nearby stops list (bus and trolley route ids). */
  function interestRoutes() {
    var r = new Set();
    try {
      if (S.board && typeof S.board.pins === 'function')
        S.board.pins().forEach(function (p) {
          r.add(String(p.route));
        });
    } catch (e) {
      /* the board reads storage; a failure only means nothing is pinned */
    }
    if (state.stop) r.add(String(state.stop.route));
    var chips = document.querySelectorAll('#nearList .near-chip');
    for (var i = 0; i < chips.length; i++) r.add(chips[i].textContent.trim());
    return r;
  }
  function isHot(v, routes) {
    if (isStarred(starKey(v))) return true;
    return (v.kind === 'bus' || v.kind === 'trolley') && routes.has(String(v.route));
  }
  function level() {
    var z = map.getZoom();
    return z >= NEAR_MIN_ZOOM ? 'near' : z > FAR_MAX_ZOOM ? 'mid' : 'far';
  }

  /* ----- Layout: pure geometry over projected points, then one pass of DOM writes for what changed. ----- */
  function plan(lvl) {
    var z = map.getZoom(),
      routes = interestRoutes(),
      sel = state.selected,
      items = list.map(function (v) {
        var hot = isHot(v, routes);
        return {
          v: v,
          hot: hot,
          rank: v.key === sel ? 0 : hot ? 1 : 2,
          p: map.project([v.lat, v.lng], z),
          clu: false,
          lbl: true
        };
      });
    items.sort(function (a, b) {
      return a.rank - b.rank || (a.v.key < b.v.key ? -1 : a.v.key > b.v.key ? 1 : 0);
    });
    var hotCount = 0;
    items.forEach(function (it) {
      if (it.rank < 2) hotCount++;
    });
    var groups = [];
    if (lvl !== 'near') {
      var L0 = LEVELS[lvl],
        cell = L0.r,
        grid = {};
      /* Greedy fold: an ordinary vehicle joins the first anchor within r px, else becomes an anchor. */
      items.forEach(function (it) {
        if (it.rank < 2) return;
        var cx = Math.floor(it.p.x / cell),
          cy = Math.floor(it.p.y / cell),
          best = null,
          bd = L0.r * L0.r;
        for (var dx = -1; dx <= 1 && !best; dx++)
          for (var dy = -1; dy <= 1; dy++) {
            var g = grid[cx + dx + ',' + (cy + dy)];
            if (!g) continue;
            for (var k = 0; k < g.length; k++) {
              var a = g[k],
                ex = a.p.x - it.p.x,
                ey = a.p.y - it.p.y,
                d = ex * ex + ey * ey;
              if (d <= bd) {
                best = a;
                bd = d;
              }
            }
          }
        if (best) best.members.push(it);
        else {
          it.members = [it];
          groups.push(it);
          (grid[cx + ',' + cy] = grid[cx + ',' + cy] || []).push(it);
        }
      });
      groups = groups.filter(function (g) {
        if (g.members.length < L0.min) return false;
        g.members.forEach(function (m) {
          m.clu = true;
        });
        return true;
      });
      /* Labels: in priority order, a label that would overlap one already placed (or a badge) is left off. */
      var boxes = [];
      /* A badge sits on its anchor vehicle; anchors are at least r apart, so badges (at most 38 px across) never stack. */
      groups.forEach(function (g) {
        g.c = { lat: g.v.lat, lng: g.v.lng };
        boxes.push({ x: g.p.x - 17, y: g.p.y - 17, w: 34, h: 34 });
      });
      var lgrid = {},
        LC = 48;
      var put = function (b) {
        for (var gx = Math.floor(b.x / LC); gx <= Math.floor((b.x + b.w) / LC); gx++)
          for (var gy = Math.floor(b.y / LC); gy <= Math.floor((b.y + b.h) / LC); gy++)
            (lgrid[gx + ',' + gy] = lgrid[gx + ',' + gy] || []).push(b);
      };
      var hits = function (b) {
        for (var gx = Math.floor(b.x / LC); gx <= Math.floor((b.x + b.w) / LC); gx++)
          for (var gy = Math.floor(b.y / LC); gy <= Math.floor((b.y + b.h) / LC); gy++) {
            var l = lgrid[gx + ',' + gy] || [];
            for (var i = 0; i < l.length; i++) {
              var o = l[i];
              if (b.x < o.x + o.w && o.x < b.x + b.w && b.y < o.y + o.h && o.y < b.y + b.h) return true;
            }
          }
        return false;
      };
      var placeLabel = function (it) {
        var w = L0.pad + L0.ch * String(it.v.badge).length,
          b = { x: it.p.x - w / 2, y: it.p.y - L0.h / 2, w: w, h: L0.h };
        if (it.rank > 0 && hits(b)) it.lbl = false;
        else put(b);
      };
      items.forEach(function (it) {
        if (it.rank < 2) placeLabel(it);
      });
      boxes.forEach(put);
      items.forEach(function (it) {
        if (it.rank === 2 && !it.clu) placeLabel(it);
      });
    }
    return { items: items, groups: groups, dim: hotCount > 0 && lvl !== 'near' };
  }
  function setFlag(e, cls, on) {
    if (e.classList.contains(cls) !== on) e.classList.toggle(cls, on);
  }
  function layout() {
    var lvl = level();
    setFlag(mapEl, 'lod-far', lvl === 'far');
    setFlag(mapEl, 'lod-mid', lvl === 'mid');
    var pl = plan(lvl),
      nextHot = new Set();
    pl.items.forEach(function (it) {
      var m = markers.get(it.v.key),
        e = m && m.getElement();
      if (it.rank < 2) nextHot.add(it.v.key);
      if (!e) return;
      var hot = it.rank === 1;
      setFlag(e, 'hot', hot);
      setFlag(e, 'dim', pl.dim && it.rank === 2);
      setFlag(e, 'nolbl', !it.lbl);
      if (e.classList.contains('inclu') !== it.clu) {
        e.classList.toggle('inclu', it.clu);
        /* A folded marker leaves the tab order and the accessibility tree; its badge stands in for it. */
        e.tabIndex = it.clu ? -1 : 0;
        if (it.clu) e.setAttribute('aria-hidden', 'true');
        else e.removeAttribute('aria-hidden');
      }
    });
    var changed = nextHot.size !== hotKeys.size;
    if (!changed)
      nextHot.forEach(function (k) {
        if (!hotKeys.has(k)) changed = true;
      });
    var old = hotKeys;
    hotKeys = nextHot;
    if (changed)
      markers.forEach(function (m, k) {
        if (old.has(k) !== nextHot.has(k)) m.setZIndexOffset(S.map.zOffset(k));
      });
    syncClusters(pl.groups, pl.dim);
  }

  /* ----- Count badges ----- */
  function clusterLabel(ms) {
    var seen = [];
    ms.forEach(function (m) {
      var b = String(m.v.badge);
      if (seen.indexOf(b) < 0) seen.push(b);
    });
    seen.sort(function (a, b) {
      return (parseInt(a, 10) || 9999) - (parseInt(b, 10) || 9999) || (a < b ? -1 : a > b ? 1 : 0);
    });
    var names = seen.slice(0, 3);
    return (
      ms.length +
      ' vehicles close together, ' +
      (seen.length === 1 ? 'route ' : 'routes ') +
      names.join(', ') +
      (seen.length > 3 ? ' and ' + (seen.length - 3) + ' more' : '') +
      '. Zoom in to see them'
    );
  }
  function kindOf(ms) {
    var k = ms[0].v.kind;
    for (var i = 1; i < ms.length; i++) if (ms[i].v.kind !== k) return 'mix';
    return k;
  }
  function expand(id) {
    var c = clusters.get(id);
    if (!c || !c._pts) return;
    var b = L.latLngBounds(c._pts),
      z = map.getZoom(),
      want = Math.min(map.getBoundsZoom(b, false, L.point(96, 96)), Math.max(MAX_EXPAND_ZOOM, z + 1));
    map.setView(b.getCenter(), Math.max(want, z + 1), { animate: animOK() });
    if (c.getElement() && c.getElement() === document.activeElement) mapEl.focus({ preventScroll: true });
  }
  function syncClusters(groups, dim) {
    var keep = new Set();
    groups.forEach(function (g) {
      var id = g.v.key,
        ms = g.members,
        kind = kindOf(ms),
        n = ms.length,
        stale = ms.every(function (m) {
          return m.v.stale;
        }),
        cls =
          'veh-clu k-' +
          kind +
          (n >= 50 ? ' c-l' : n >= 10 ? ' c-m' : '') +
          (stale ? ' stale' : '') +
          (dim ? ' dim' : ''),
        lbl = clusterLabel(ms),
        c = clusters.get(id);
      keep.add(id);
      if (!c) {
        c = L.marker([g.c.lat, g.c.lng], {
          icon: L.divIcon({
            className: cls,
            html: '<span class="cn"></span>',
            iconSize: [44, 44],
            iconAnchor: [22, 22]
          }),
          keyboard: true,
          zIndexOffset: CLU_Z
        });
        c.on('click', function () {
          expand(id);
        });
        c.addTo(map);
        clusters.set(id, c);
        var e0 = c.getElement();
        e0.setAttribute('role', 'button');
        e0.addEventListener('keydown', function (ev) {
          if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
            ev.preventDefault();
            ev.stopPropagation();
            expand(id);
          }
        });
      } else {
        var ll = c.getLatLng();
        if (ll.lat !== g.c.lat || ll.lng !== g.c.lng) c.setLatLng([g.c.lat, g.c.lng]);
      }
      c._pts = ms.map(function (m) {
        return [m.v.lat, m.v.lng];
      });
      var e = c.getElement();
      if (!e) return;
      if (e.className.replace(/\s*leaflet-\S+/g, '').trim() !== cls)
        e.className = cls + ' ' + (e.className.match(/leaflet-\S+/g) || []).join(' ');
      var cn = e.firstChild;
      if (cn.textContent !== String(n)) cn.textContent = n;
      if (e.getAttribute('aria-label') !== lbl) {
        e.setAttribute('aria-label', lbl);
        e.setAttribute('title', n + ' vehicles: zoom in');
      }
    });
    clusters.forEach(function (c, id) {
      if (!keep.has(id)) {
        c.remove();
        clusters.delete(id);
      }
    });
  }

  /* ----- Triggers. Each refresh (map.js syncMarkers), a zoom, a selection, and a change in what the rider cares about. ----- */
  function update(l) {
    if (l) {
      /* duplicate keys in the feed share one marker (js/map.js), so they count once here too */
      var seen = new Set();
      list = l.filter(function (v) {
        if (seen.has(v.key)) return false;
        seen.add(v.key);
        return true;
      });
    }
    layout();
  }
  function interestChanged() {
    var sig = Array.from(interestRoutes()).sort().join(',');
    if (sig === lastSig) return;
    lastSig = sig;
    layout();
  }
  map.on('zoomend viewreset', function () {
    layout();
  });
  var near = document.getElementById('nearList');
  if (near && window.MutationObserver)
    new MutationObserver(interestChanged).observe(near, { childList: true });
  if (S.board && typeof S.board.onChange === 'function') S.board.onChange(interestChanged);
  window.addEventListener('hashchange', interestChanged);
  S.maplod.update = update;
  S.maplod.layout = layout;
  S.maplod.isHot = function (k) {
    return hotKeys.has(k);
  };
  S.maplod.HOT_Z = HOT_Z;
})();
