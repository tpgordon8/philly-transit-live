/* js/panel.js: sidebar. Status line, search box, saved places, Home, radius, mode filters and My routes. */
(function () {
  'use strict';
  var S = window.SEPTA;
  function tripRenderPlaces() {
    return S.trip.tripRenderPlaces.apply(null, arguments);
  }
  if (S.halt) return;
  var $ = S.util.$;
  var widenedRadius = S.util.widenedRadius,
    CARD = S.util.CARD,
    CARD_LONG = S.util.CARD_LONG,
    DROP_AFTER_MS = S.util.DROP_AFTER_MS,
    PHILLY = S.util.PHILLY,
    angDiff = S.util.angDiff,
    bearing = S.util.bearing,
    distMi = S.util.distMi,
    el = S.util.el,
    esc = S.util.esc,
    fmtMi = S.util.fmtMi,
    hideBanner = S.util.hideBanner,
    lateInfo = S.util.lateInfo,
    routeFilterOn = S.util.routeFilterOn,
    routesStore = S.util.routesStore,
    saveRoutes = S.util.saveRoutes,
    showBanner = S.util.showBanner,
    state = S.util.state,
    store = S.util.store;
  var apply = S.feed.apply,
    collect = S.feed.collect,
    refresh = S.feed.refresh,
    wantedSources = S.feed.wantedSources;
  var clearSelection = S.map.clearSelection,
    drawCenter = S.map.drawCenter,
    drawHome = S.map.drawHome,
    fitRadius = S.map.fitRadius,
    map = S.map.map,
    select = S.map.select;
  var gmhLine = null; /* the dotted line from the search point to Home, drawn by renderGMH */
  /* The center written to localStorage. A stop link moves state.center for this session only, so savePrefs
   writes savedCenter, which only setCenter() without noSave updates. */
  var savedCenter = state.center;
  function savePrefs() {
    store.set('septa.prefs.v1', { center: savedCenter, radius: state.radius, filters: state.filters });
  }
  $('#empty').addEventListener('click', function (e) {
    var b = e.target.closest('#emptyAct');
    if (!b) return;
    if (b.dataset.act === 'widen') {
      setRadius(widenedRadius(state.radius), true);
    } else if (b.dataset.act === 'routes') {
      routesStore.onlyMine = false;
      saveRoutes();
      clearSelection();
      apply();
    } else {
      state.filters = { bus: true, trolley: true, subway: true, train: true };
      syncModeChips();
      savePrefs();
      apply();
    }
  });
  function toggleStar(k) {
    var i = routesStore.stars.indexOf(k);
    if (i >= 0) routesStore.stars.splice(i, 1);
    else routesStore.stars.push(k);
    saveRoutes();
    /* Unstarring the open vehicle's route while the filter is on hides it; close the card instead of calling it "not reporting". */
    if (i >= 0 && routeFilterOn() && state.selected) clearSelection();
    apply();
  }
  function starName(k) {
    return k.indexOf('train:') === 0 ? k.slice(6) : k.indexOf('subway:') === 0 ? k.slice(7) : k;
  }
  function renderMyRoutes() {
    var box = $('#myRoutes'),
      st = routesStore.stars;
    box.replaceChildren();
    if (!st.length) {
      box.appendChild(el('p', 'hint', 'Tap a vehicle, then star its route to build your own view.'));
      return;
    }
    var t = el('button', 'btn small', '');
    t.type = 'button';
    t.id = 'myToggle';
    t.setAttribute('aria-pressed', routesStore.onlyMine ? 'true' : 'false');
    t.textContent = routesStore.onlyMine ? 'Showing my routes (' + st.length + ')' : 'Showing all routes';
    box.appendChild(t);
    var list = el('div', 'mylist');
    st.forEach(function (k) {
      var c = el('span', 'chip on'),
        n = starName(k);
      c.appendChild(el('span', null, k.indexOf('train:') === 0 ? n + ' route' : n));
      var rm = el('button', 'btn small ghost', '\u00d7');
      rm.type = 'button';
      rm.dataset.remove = k;
      rm.setAttribute('aria-label', 'Remove route ' + n + ' from my routes');
      c.appendChild(rm);
      list.appendChild(c);
    });
    box.appendChild(list);
  }
  $('#myRoutes').addEventListener('click', function (e) {
    if (e.target.closest('#myToggle')) {
      routesStore.onlyMine = !routesStore.onlyMine;
      saveRoutes();
      clearSelection();
      apply();
      return;
    }
    var rm = e.target.closest('[data-remove]');
    if (rm) {
      toggleStar(rm.dataset.remove);
    }
  });
  /* ----- Status line + banner ----- */
  function srcState(sr, now) {
    if (!sr.err) return 'ok';
    if (sr.ok && now - sr.ok <= DROP_AFTER_MS) return 'stale';
    return 'down';
  }
  /* Screen readers get a polite announcement only when the state or the vehicle count changes; the ticking
   "updated Ns ago" text in #statusText is aria-hidden and never announced. */
  function syncStatusLive() {
    var d = $('#dot').className,
      n = state.visible.length,
      t;
    if (state.paused) t = 'Paused';
    else if (d.indexOf('live') >= 0) t = 'Live, ' + n + ' vehicle' + (n === 1 ? '' : 's') + ' shown';
    else if (d.indexOf('stale') >= 0) t = 'Delayed, showing older positions';
    else if (d.indexOf('err') >= 0) t = 'Live data unavailable';
    else t = 'Connecting to SEPTA';
    var o = $('#statusLive');
    if (o.textContent !== t) o.textContent = t;
  }
  function renderStatus() {
    renderStatusView();
    syncStatusLive();
  }
  function renderStatusView() {
    var dot = $('#dot'),
      txt = $('#statusText'),
      b = state.src.bus,
      t = state.src.train,
      now = Date.now();
    if (state.paused) {
      dot.className = 'dot';
      txt.innerHTML = '<b>Paused</b>';
      hideBanner();
      return;
    }
    var w = wantedSources(),
      act = ['bus', 'train'].filter(function (k) {
        return w[k];
      });
    var st = {},
      stale = [],
      down = [];
    act.forEach(function (k) {
      st[k] = srcState(state.src[k], now);
      if (st[k] === 'stale') stale.push(k);
      else if (st[k] === 'down') down.push(k);
    });
    var n = state.visible.length;
    if (!b.ok && !t.ok && !b.err && !t.err && !state.fetchedAt) {
      dot.className = 'dot';
      txt.textContent = 'Connecting to SEPTA…';
      return;
    }
    if (!act.length) {
      dot.className = 'dot live';
      txt.innerHTML = '<b>Paused</b> · no vehicle types selected';
      hideBanner();
      return;
    }
    if (down.length === act.length) {
      dot.className = 'dot err';
      txt.innerHTML = '<b>Live data unavailable</b>';
      showBanner(
        '',
        "<b>Live data unavailable.</b> We can't reach SEPTA right now, so no vehicles are shown. We'll keep trying."
      );
      return;
    }
    if (stale.length || down.length) {
      var parts = [];
      if (stale.length) {
        var which = stale
          .map(function (k) {
            return k === 'bus' ? 'buses, trolleys and subway' : 'Regional Rail';
          })
          .join(' and ');
        parts.push(
          '<b>Showing older positions for ' +
            esc(which) +
            '.</b> The latest update failed. Dimmed markers disappear after 2 minutes.'
        );
      }
      if (down.length) {
        var gone = down
          .map(function (k) {
            return k === 'bus' ? 'Bus, trolley and subway' : 'Regional Rail';
          })
          .join(' and ');
        parts.push('<b>' + esc(gone) + ' positions are unavailable.</b> No update for over 2 minutes.');
      }
      if (stale.length) {
        var newest = Math.max.apply(
            null,
            stale.map(function (k) {
              return state.src[k].ok;
            })
          ),
          ago0 = Math.max(0, Math.round((now - newest) / 1000));
        dot.className = 'dot stale';
        txt.innerHTML = '<b>Delayed</b> · last update ' + ago0 + ' s ago';
      } else {
        dot.className = 'dot stale';
        txt.innerHTML = '<b>Some data missing</b> · ' + n + ' shown';
      }
      showBanner('warn', parts.join(' '));
      return;
    }
    var ago = Math.max(0, Math.round((now - Math.max(b.ok, t.ok)) / 1000));
    hideBanner();
    dot.className = 'dot live';
    txt.innerHTML =
      '<b>Live</b> · updated ' + ago + ' s ago · ' + n + ' vehicle' + (n === 1 ? '' : 's') + ' shown';
  }
  /* ----- Search, location, radius, modes ----- */
  function setNote(msg, bad) {
    var n = $('#note');
    n.textContent = msg || '';
    n.className = 'note' + (bad ? ' bad' : '');
    /* An error is tied to the search box until its value changes. */
    var inp = $('#addr');
    if (bad && msg) {
      inp.setAttribute('aria-invalid', 'true');
      inp.setAttribute('aria-describedby', 'note');
    } else {
      inp.removeAttribute('aria-invalid');
      inp.removeAttribute('aria-describedby');
    }
  }
  $('#addr').addEventListener('input', function () {
    this.removeAttribute('aria-invalid');
    this.removeAttribute('aria-describedby');
  });
  /* The short Photon line links to the privacy details, which open when it is followed. */
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('.priv-link')) $('#privacyDetails').open = true;
  });
  function setCenter(c, fit, noSave) {
    state.center = { lat: c.lat, lng: c.lng, label: c.label || '' };
    if (!noSave) {
      savedCenter = state.center;
      savePrefs();
    }
    drawCenter();
    if (fit) fitRadius();
    updateSaveForm();
    apply();
  }
  function setRadius(r, fit) {
    state.radius = r;
    $('#radius').value = r;
    $('#radiusOut').textContent = r + ' mi';
    savePrefs();
    drawCenter();
    if (fit) fitRadius();
    apply();
  }
  $('#radius').addEventListener('input', function (e) {
    var r = Number(e.target.value);
    state.radius = r;
    $('#radiusOut').textContent = r + ' mi';
    drawCenter();
    apply();
  });
  $('#radius').addEventListener('change', function (e) {
    setRadius(Number(e.target.value), true);
  });
  function syncModeChips() {
    document.querySelectorAll('#modes .chip').forEach(function (ch) {
      var inp = ch.querySelector('input');
      inp.checked = !!state.filters[inp.dataset.mode];
      ch.classList.toggle('on', inp.checked);
    });
  }
  $('#modes').addEventListener('change', function (e) {
    var inp = e.target;
    if (!inp.dataset.mode) return;
    state.filters[inp.dataset.mode] = inp.checked;
    syncModeChips();
    savePrefs();
    apply();
  });
  function shortLabel(s) {
    return String(s || '')
      .split(',')
      .slice(0, 2)
      .join(',')
      .trim();
  }
  /* Shared Nominatim lookup (Philadelphia viewbox, a preference rather than a bound: the trip planner checks the region itself).
   Resolves the first match {lat,lng,label} or null; rejects when the request fails. opts.philly appends ', Philadelphia, PA' to
   text without a comma (used by the trip planner only). Nominatim's policy allows about one request per second, so lookups start at
   least GEO_GAP_MS apart (the slot is reserved when called, so two quick calls queue), and answers, misses included, are kept in
   memory for the page session; failures are not kept. */
  var GEO_URL =
    'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=us&viewbox=-75.80,40.30,-74.60,39.70&q=';
  var GEO_TIMEOUT_MS = 9000 /* browser location request: give up after this long */,
    GEO_MAX_AGE_MS = 30000 /* and accept a cached fix this old */,
    GEO_GAP_MS = 1100,
    geoNext = 0,
    geoCache = {};
  function geocode(q, opts) {
    if (opts && opts.philly && q.indexOf(',') < 0) q += ', Philadelphia, PA';
    var key = q.trim().replace(/\s+/g, ' ').toLowerCase();
    if (Object.prototype.hasOwnProperty.call(geoCache, key)) {
      var c = geoCache[key];
      return Promise.resolve(c && { lat: c.lat, lng: c.lng, label: c.label });
    }
    var now = Date.now(),
      at = Math.max(now, geoNext);
    if (at - now > GEO_GAP_MS * 20) at = now; /* the clock moved backwards: do not wait for a stale slot */
    geoNext = at + GEO_GAP_MS;
    return new Promise(function (res) {
      setTimeout(res, at - now);
    })
      .then(function () {
        return fetch(GEO_URL + encodeURIComponent(q), { headers: { Accept: 'application/json' } });
      })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (res) {
        var out = null;
        if (res.length) {
          var r = res[0];
          out = { lat: Number(r.lat), lng: Number(r.lon), label: shortLabel(r.display_name) };
        }
        geoCache[key] = out;
        return out && { lat: out.lat, lng: out.lng, label: out.label };
      });
  }
  /* A picked suggestion carries its coordinates, so submit uses them and does not geocode; editing the text discards the pick. */
  var addrSug = S.suggest.attach($('#addr'), {
    onPick: function () {
      setNote('');
    },
    biasProvider: function () {
      return state.center;
    }
  });
  $('#searchForm').addEventListener('submit', function (e) {
    e.preventDefault();
    addrSug.close(); /* no suggestion request or list may outlive the submit */
    var q = $('#addr').value.trim();
    if (!q) {
      setNote('Type a street address or intersection first.', true);
      return;
    }
    var pk = addrSug.picked();
    if (pk) {
      setNote('Showing vehicles near ' + pk.name + '.');
      setCenter({ lat: pk.lat, lng: pk.lng, label: pk.name }, true);
      return;
    }
    var btn = $('#btnSearch');
    btn.disabled = true;
    setNote('Looking up that address…');
    geocode(q)
      .then(function (r) {
        if (!r) {
          setNote('No match for that address. Try adding a cross street or a ZIP code.', true);
          return;
        }
        setNote('Showing vehicles near ' + r.label + '.');
        setCenter({ lat: r.lat, lng: r.lng, label: r.label }, true);
      })
      .catch(function () {
        setNote('Address lookup failed. Check your connection and try again.', true);
      })
      .finally(function () {
        btn.disabled = false;
      });
  });
  function getPosition() {
    return new Promise(function (res, rej) {
      if (!navigator.geolocation) {
        rej(new Error('unsupported'));
        return;
      }
      navigator.geolocation.getCurrentPosition(res, rej, {
        enableHighAccuracy: true,
        timeout: GEO_TIMEOUT_MS,
        maximumAge: GEO_MAX_AGE_MS
      });
    });
  }
  $('#btnLocate').addEventListener('click', function () {
    var btn = $('#btnLocate');
    btn.disabled = true;
    setNote('Finding your location…');
    getPosition()
      .then(function (p) {
        setNote('Showing vehicles around your current location.');
        setCenter({ lat: p.coords.latitude, lng: p.coords.longitude, label: 'Your location' }, true);
      })
      .catch(function () {
        setNote("Location isn't available here. Type an address instead.", true);
      })
      .finally(function () {
        btn.disabled = false;
      });
  });
  /* ----- Saved places + Get me home ----- */
  function persistPlaces() {
    store.set('septa.places.v1', state.places);
  }
  function updateSaveForm() {
    var f = $('#saveForm'),
      has = state.center && state.center !== PHILLY && state.center.label !== 'Center City (default view)';
    f.hidden = !has;
    if (has && document.activeElement !== $('#placeName')) $('#placeName').value = state.center.label || '';
  }
  function savePlace(asHome) {
    var name = $('#placeName').value.trim() || state.center.label || 'Saved place';
    var p = { id: 'p' + Date.now(), name: name.slice(0, 40), lat: state.center.lat, lng: state.center.lng };
    if (asHome) {
      state.places.home = { name: p.name, lat: p.lat, lng: p.lng };
    } else state.places.list.push(p);
    persistPlaces();
    renderPlaces();
    drawHome();
  }
  $('#btnSave').addEventListener('click', function () {
    savePlace(false);
  });
  $('#btnSaveHome').addEventListener('click', function () {
    savePlace(true);
  });
  function renderPlaces() {
    var ul = $('#places'),
      h = state.places.home;
    ul.replaceChildren();
    function goTo(p) {
      setNote('');
      setCenter({ lat: p.lat, lng: p.lng, label: p.name }, true);
      $('#addr').value = '';
    }
    if (h) {
      var li = el('li');
      li.appendChild(el('span', 'tag', 'Home'));
      li.appendChild(el('span', 'nm', h.name));
      var go = el('button', 'btn small', 'Go');
      go.type = 'button';
      go.addEventListener('click', function () {
        goTo(h);
      });
      var rm = el('button', 'btn small ghost', 'Remove');
      rm.type = 'button';
      rm.setAttribute('aria-label', 'Remove Home');
      rm.addEventListener('click', function () {
        state.places.home = null;
        persistPlaces();
        renderPlaces();
        drawHome();
        $('#gmh').replaceChildren();
      });
      li.appendChild(go);
      li.appendChild(rm);
      ul.appendChild(li);
    }
    state.places.list.forEach(function (p) {
      var li = el('li');
      li.appendChild(el('span', 'nm', p.name));
      var go = el('button', 'btn small', 'Go');
      go.type = 'button';
      go.addEventListener('click', function () {
        goTo(p);
      });
      var mk = el('button', 'btn small ghost', 'Set as Home');
      mk.type = 'button';
      mk.setAttribute('aria-label', 'Set as Home: ' + p.name);
      mk.addEventListener('click', function () {
        state.places.home = { name: p.name, lat: p.lat, lng: p.lng };
        persistPlaces();
        renderPlaces();
        drawHome();
      });
      var rm = el('button', 'btn small ghost', 'Remove');
      rm.type = 'button';
      rm.setAttribute('aria-label', 'Remove ' + p.name);
      rm.addEventListener('click', function () {
        state.places.list = state.places.list.filter(function (x) {
          return x.id !== p.id;
        });
        persistPlaces();
        renderPlaces();
      });
      li.appendChild(go);
      li.appendChild(mk);
      li.appendChild(rm);
      ul.appendChild(li);
    });
    $('#placesEmpty').hidden = !!(h || state.places.list.length);
    var hb = $('#btnHome');
    hb.hidden = !h;
    if (h) $('#homeName').textContent = h.name;
    tripRenderPlaces();
  }
  $('#btnHome').addEventListener('click', function () {
    getMeHome();
  });
  function getMeHome() {
    var home = state.places.home;
    if (!home) return;
    var btn = $('#btnHome');
    btn.disabled = true;
    var origin = null,
      usedGps = false;
    getPosition()
      .then(function (p) {
        origin = { lat: p.coords.latitude, lng: p.coords.longitude, label: 'Your location' };
        usedGps = true;
      })
      .catch(function () {
        origin = {
          lat: state.center.lat,
          lng: state.center.lng,
          label: state.center.label || 'this location'
        };
      })
      .then(function () {
        state.center = { lat: origin.lat, lng: origin.lng, label: origin.label };
        savedCenter = state.center;
        savePrefs();
        drawCenter();
        updateSaveForm();
        return refresh();
      })
      .then(function () {
        var dHome = distMi(origin, home);
        if (gmhLine) {
          gmhLine.remove();
          gmhLine = null;
        }
        gmhLine = L.polyline(
          [
            [origin.lat, origin.lng],
            [home.lat, home.lng]
          ],
          { className: 'gmhline', interactive: false }
        ).addTo(map);
        map.fitBounds(
          L.latLngBounds([
            [origin.lat, origin.lng],
            [home.lat, home.lng]
          ]).pad(0.25),
          { animate: true }
        );
        var cands = collect()
          .filter(function (v) {
            if (v.stale || v.heading == null) return false;
            if (distMi(origin, v) > state.radius) return false;
            return angDiff(v.heading, bearing(v, home)) <= 50;
          })
          .sort(function (a, b) {
            return distMi(origin, a) - distMi(origin, b);
          })
          .slice(0, 6);
        renderGMH(origin, home, dHome, cands, usedGps);
        apply();
      })
      .finally(function () {
        btn.disabled = false;
      });
  }
  function renderGMH(origin, home, dHome, cands, usedGps) {
    var box = $('#gmh');
    box.replaceChildren();
    var wrap = el('div', 'gmh'),
      head = el('header');
    var dir = CARD[Math.round(bearing(origin, home) / 45) % 8];
    head.appendChild(
      document.createTextNode(
        'Home is ' + fmtMi(dHome) + ' ' + CARD_LONG[dir] + ' of ' + (usedGps ? 'you' : origin.label) + '.'
      )
    );
    head.appendChild(document.createElement('br'));
    var a = el('a', null, 'Open transit directions ↗');
    a.href =
      'https://www.google.com/maps/dir/?api=1&origin=' +
      origin.lat +
      ',' +
      origin.lng +
      '&destination=' +
      home.lat +
      ',' +
      home.lng +
      '&travelmode=transit';
    a.target = '_blank';
    a.rel = 'noopener';
    head.appendChild(a);
    var pn = el('span', 'dir-note', 'Opens Google Maps with your start and Home locations.');
    pn.style.cssText = 'display:block;margin-top:2px;font-weight:400;font-size:12px;color:var(--mute)';
    head.appendChild(pn);
    wrap.appendChild(head);
    if (cands.length) {
      var ol = el('ol');
      cands.forEach(function (v) {
        var li = el('li'),
          b = el('button');
        b.type = 'button';
        b.appendChild(el('span', 'rbadge k-' + v.kind, v.badge));
        b.appendChild(el('span', null, 'To ' + (v.dest || 'destination not reported')));
        var li2 = lateInfo(v.late);
        b.appendChild(
          el(
            'span',
            'meta',
            fmtMi(distMi(origin, v)) + ' away · ' + li2.txt + (v.next ? ' · next: ' + v.next : '')
          )
        );
        b.addEventListener('click', function () {
          map.panTo([v.lat, v.lng], { animate: true });
          select(v.key);
        });
        li.appendChild(b);
        ol.appendChild(li);
      });
      wrap.appendChild(ol);
      wrap.appendChild(
        el(
          'div',
          'fine',
          "These are vehicles near you whose heading points toward Home. SEPTA's data has no route shapes, so check the destination before you board."
        )
      );
    } else {
      wrap.appendChild(
        el(
          'div',
          'fine',
          'No vehicle within ' +
            state.radius +
            ' mi is heading toward Home right now. Try a larger radius, or use the transit directions link.'
        )
      );
    }
    if (!usedGps)
      wrap.appendChild(
        el('div', 'fine', "Your location wasn't available, so this started from the place you last searched.")
      );
    box.appendChild(wrap);
  }
  S.panel.renderMyRoutes = renderMyRoutes;
  S.panel.renderStatus = renderStatus;
  S.panel.setCenter = setCenter;
  S.panel.syncModeChips = syncModeChips;
  S.panel.geocode = geocode;
  S.panel.getPosition = getPosition;
  S.panel.updateSaveForm = updateSaveForm;
  S.panel.renderPlaces = renderPlaces;
  S.panel.toggleStar = toggleStar;
  S.panel.starName = starName;
})();
