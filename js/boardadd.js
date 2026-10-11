/* js/boardadd.js: "Add a bus stop" sheet of the My stops board (ARCHITECTURE.md section 16.2). The person types a street, an intersection,
   an address or a stop name (or uses their location) and picks one of the bus stops found; the stop is pinned through S.board.addPin.
   It reuses the planner's pieces: S.suggest (landmarks and Photon), S.panel.geocode (Nominatim), the bus network file through
   S.routing.loadNetwork and S.candidates.nearbyStops. Needs js/boardview.js (loaded earlier) and does nothing without it. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt || typeof document === 'undefined' || !S.boardview || !S.boardview.say) return;
  var util = S.util,
    $ = util.$,
    el = util.el,
    bv = S.boardview,
    say = bv.say,
    lim = bv.lim;
  var sheet = $('#bvAdd'),
    settings = $('#bvSettings'),
    setBtn = $('#bvSet');
  var NEAR_STOPS = 8 /* stops listed after a place is found */,
    NEAR_RADII_M = [
      400, 800, 1600
    ] /* widened until enough stops are found; nothing is listed beyond a mile */,
    NAME_STOPS = 8,
    ROWS_MAX = 16 /* a stop served by many routes would otherwise fill the list */,
    HEADS_MAX = 2,
    FT_PER_MI = 5280,
    FT_STEP = 50,
    FT_MAX = 950,
    GEO_TIMEOUT_MS = 9000,
    GEO_MAX_AGE_MS = 30000;
  /* Words in a typed name that say nothing about which stop is meant ("10th and Race Street"). */
  var NOISE = /^(and|at|&|the|st|street|av|ave|avenue|blvd|boulevard|rd|road|dr|drive|ln|lane|pkwy|parkway)$/;
  var nodes = null,
    open = false,
    opener = null,
    net = null,
    seq = 0,
    results = [],
    byStop = null;

  function board() {
    return bv.board();
  }
  function routeOrder(a, b) {
    var x = parseInt(a.route, 10),
      y = parseInt(b.route, 10);
    if (isNaN(x) !== isNaN(y)) return isNaN(x) ? 1 : -1;
    return x - y || (a.route < b.route ? -1 : a.route > b.route ? 1 : 0);
  }
  /* Stop id -> [{route, kind, heads}]: the routes that stop, with where their buses are headed. A pattern that ends at the stop
     does not count (nobody boards there). Built once per loaded network. */
  function routesByStop(n) {
    if (byStop && byStop.net === n) return byStop.by;
    var by = {};
    n.net.patterns.forEach(function (p) {
      p.stops.forEach(function (id, i) {
        if (i === p.stops.length - 1 && p.stops.length > 1) return;
        var list = by[id] || (by[id] = []),
          r = list.filter(function (x) {
            return x.route === p.route;
          })[0];
        if (!r)
          list.push((r = { route: p.route, kind: p.kind === 'trolley' ? 'trolley' : 'bus', heads: [] }));
        if (p.head && r.heads.indexOf(p.head) < 0) r.heads.push(p.head);
      });
    });
    for (var id in by) by[id].sort(routeOrder);
    byStop = { net: n, by: by };
    return by;
  }
  function distText(m) {
    var ft = (m / util.M_PER_MI) * FT_PER_MI;
    if (ft < FT_MAX) return Math.max(FT_STEP, Math.round(ft / FT_STEP) * FT_STEP) + ' ft';
    return (ft / FT_PER_MI).toFixed(1) + ' mi';
  }
  /* ----- Finding stops ----- */
  function rowsOf(stops, by) {
    var out = [];
    stops.forEach(function (s) {
      (by[s.id] || []).forEach(function (r) {
        out.push({
          id: s.id,
          name: s.name || 'Stop ' + s.id,
          lat: s.lat,
          lng: s.lng,
          d: s.d,
          route: r.route,
          kind: r.kind,
          heads: r.heads.slice(0, HEADS_MAX)
        });
      });
    });
    return out.slice(0, ROWS_MAX);
  }
  function nearStops(n, c) {
    var by = routesByStop(n),
      out = [];
    for (var i = 0; i < NEAR_RADII_M.length && out.length < NEAR_STOPS; i++)
      out = S.candidates.nearbyStops(n.index, c, NEAR_RADII_M[i]).filter(function (s) {
        return !!by[s.id];
      });
    return rowsOf(out.slice(0, NEAR_STOPS), by);
  }
  function words(q) {
    return String(q)
      .toLowerCase()
      .replace(/&/g, ' & ')
      .split(/[^a-z0-9&]+/)
      .filter(function (w) {
        return w && !NOISE.test(w);
      });
  }
  /* Stops whose name has every typed word at the start of one of its own words, nearest to the map's search point first.
     A typed number that is a route ("47 wolf", "wolf 47") narrows the answer to that route; when that finds nothing the number is
     read as part of the name ("11 market" for 11th and Market). */
  function nameStops(n, q) {
    var all = words(q),
      by = routesByStop(n),
      c = util.state.center,
      routes = {};
    Object.keys(by).forEach(function (id) {
      by[id].forEach(function (r) {
        routes[String(r.route).toLowerCase()] = true;
      });
    });
    function find(want, only) {
      var out = [],
        use = {};
      if (!want.length && !only) return out;
      Object.keys(by).forEach(function (id) {
        use[id] = only
          ? by[id].filter(function (r) {
              return String(r.route).toLowerCase() === only;
            })
          : by[id];
      });
      Object.keys(n.net.stops).forEach(function (id) {
        var s = n.net.stops[id],
          have = words(s[2]);
        if (
          !use[id] ||
          !use[id].length ||
          !want.every(function (w) {
            return have.some(function (h) {
              return h.indexOf(w) === 0;
            });
          })
        )
          return;
        out.push({
          id: id,
          lat: s[0],
          lng: s[1],
          name: s[2],
          d: c ? util.distM(c, { lat: s[0], lng: s[1] }) : 0
        });
      });
      out.sort(function (a, b) {
        return a.d - b.d;
      });
      return rowsOf(out.slice(0, NAME_STOPS), use).map(function (r) {
        r.d = null; /* the distance from the map's search point means nothing to the person */
        return r;
      });
    }
    var only = all.filter(function (w) {
      return routes[w];
    })[0];
    if (only) {
      var rows = find(
        all.filter(function (w, i) {
          return i !== all.indexOf(only);
        }),
        only
      );
      if (rows.length) return rows;
    }
    return find(all, null);
  }
  function onBoard(r) {
    var b = board();
    if (!b || typeof b.hasPin !== 'function') return false;
    var all = typeof b.pinOptions === 'function' ? b.pinOptions() : [{ placeId: null }],
      opts =
        all.length > 1
          ? all.slice(0, -1)
          : all; /* "No place" does not count as taken when there are places */
    return opts.every(function (o) {
      return b.hasPin(r.route, r.id, o.placeId);
    });
  }
  /* ----- The sheet ----- */
  function note(text, extra) {
    var n = nodes;
    n.msg.textContent = text;
    n.extra.replaceChildren();
    if (extra) n.extra.appendChild(extra);
  }
  function actionBtn(text, fn) {
    var b = el('button', 'bv-btn', text);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }
  function showStep(name) {
    nodes.cancel.hidden = name === 'done'; /* "Show my board" is the way out there */
    ['search', 'place', 'done'].forEach(function (k) {
      nodes[k].hidden = k !== name;
    });
  }
  function drawRows() {
    var n = nodes;
    n.res.replaceChildren();
    results.forEach(function (r, i) {
      var li = el('li'),
        b = el('button', 'bv-pick'),
        heads = r.heads.length ? 'toward ' + r.heads.join(' or ') : 'Route ' + r.route,
        taken = onBoard(r);
      b.type = 'button';
      b.dataset.fk = 'st' + i;
      b.disabled = taken;
      b.setAttribute(
        'aria-label',
        'Route ' +
          r.route +
          ' ' +
          (r.heads.length ? heads + ' ' : '') +
          'at ' +
          r.name +
          (r.d == null ? '' : ', ' + distText(r.d)) +
          (taken ? ', already on the board' : '')
      );
      b.appendChild(el('span', 'bv-rt k-' + r.kind, r.route));
      var t = el('span', 'bv-pt');
      t.appendChild(el('span', null, heads + (taken ? ' (on board)' : '')));
      t.appendChild(el('small', null, r.name + (r.d == null ? '' : ' · ' + distText(r.d))));
      b.appendChild(t);
      b.addEventListener('click', function () {
        choose(r);
      });
      li.appendChild(b);
      n.res.appendChild(li);
    });
  }
  function showRows(rows, text) {
    results = rows;
    drawRows();
    note(text);
  }
  /* ----- Searching: every search takes a number, and an answer for an older one is ignored ----- */
  function offline() {
    return navigator.onLine === false;
  }
  function dataSaver() {
    var cn = navigator.connection;
    return !!(cn && cn.saveData);
  }
  function clearRows() {
    results = [];
    nodes.res.replaceChildren();
  }
  /* job(network, mine) runs once the bus network (about 275 KB) is in memory. With Data Saver on it waits for one tap. */
  function withNetwork(job) {
    var mine = ++seq;
    clearRows();
    if (net) return job(net, mine);
    if (offline()) return note("You're offline. Reconnect to look up bus stops.");
    var go = function () {
      note('Finding bus stops...');
      S.routing.loadNetwork().then(
        function (n) {
          net = n;
          if (mine === seq) job(n, mine);
        },
        function () {
          if (mine === seq)
            note(
              "The stop list couldn't load. Check the connection and try again.",
              actionBtn('Try again', function () {
                withNetwork(job);
              })
            );
        }
      );
    };
    if (dataSaver() && !S.routing.networkRequested()) {
      var b = actionBtn('Load bus stops (about 275 KB)', go);
      b.dataset.fk = 'load';
      note('Data Saver is on, so the stop list is not loaded until you ask.', b);
    } else go();
  }
  /* "3 bus stops near X": counted in stops, not in the rows (one per route) */
  function summary(rows, tail) {
    var ids = {};
    rows.forEach(function (r) {
      ids[r.id] = 1;
    });
    var n = Object.keys(ids).length;
    return n + (n === 1 ? ' bus stop' : ' bus stops') + tail + '. Tap one to add it.';
  }
  function nearJob(c, label) {
    return function (n) {
      var rows = nearStops(n, c);
      if (!rows.length) return note('No bus stops within a mile of ' + label + '.');
      showRows(rows, summary(rows, ' near ' + label));
    };
  }
  function textJob(q) {
    return function (n, mine) {
      var rows = nameStops(n, q);
      if (rows.length) return showRows(rows, summary(rows, ' with a name like that'));
      if (offline()) return note("You're offline. Reconnect to look up an address.");
      note('Looking up that address...');
      S.panel.geocode(q, { philly: true }).then(
        function (r) {
          if (mine !== seq) return;
          if (!r) note('No match for that. Try adding a cross street or a ZIP code.');
          else nearJob(r, r.label || q)(n, mine);
        },
        function () {
          if (mine === seq) note('Address lookup failed. Check your connection and try again.');
        }
      );
    };
  }
  function submit() {
    nodes.sug.close(); /* no suggestion request or list may outlive the submit */
    var q = nodes.q.value.trim();
    if (!q) return note('Type a street, an intersection, an address or a stop name first.');
    var pk = nodes.sug.picked();
    withNetwork(pk ? nearJob(pk, pk.name) : textJob(q));
  }
  function locate() {
    var mine = ++seq;
    clearRows();
    if (!navigator.geolocation) return note("Location isn't available here. Type an address instead.");
    note('Finding your location...');
    navigator.geolocation.getCurrentPosition(
      function (p) {
        if (mine === seq)
          withNetwork(nearJob({ lat: p.coords.latitude, lng: p.coords.longitude }, 'your location'));
      },
      function () {
        if (mine === seq) note("Location isn't available here. Type an address instead.");
      },
      { enableHighAccuracy: true, timeout: GEO_TIMEOUT_MS, maximumAge: GEO_MAX_AGE_MS }
    );
  }
  /* ----- Pinning: the stop card's rule. With saved places the person says which place the stop is for; with none, no place. ----- */
  function choose(r) {
    var b = board(),
      opts = b && typeof b.pinOptions === 'function' ? b.pinOptions() : [];
    if (opts.length < 2) return pin(r, null);
    var n = nodes;
    n.placeList.replaceChildren();
    n.placeHead.textContent = 'Which place is Route ' + r.route + ' at ' + r.name + ' for?';
    opts.forEach(function (o) {
      var x = actionBtn(o.name, function () {
        pin(r, o.placeId);
      });
      x.dataset.fk = 'pl';
      x.className = 'bv-btn bv-block';
      if (typeof b.hasPin === 'function' && b.hasPin(r.route, r.id, o.placeId)) {
        x.disabled = true;
        x.textContent = o.name + ' (on board)';
      }
      n.placeList.appendChild(x);
    });
    showStep('place');
    var f = n.placeList.querySelector('button:not(:disabled)');
    (f || n.placeBack).focus();
  }
  function pin(r, placeId) {
    var b = board(),
      res = b
        ? b.addPin({
            route: r.route,
            stopId: r.id,
            stopName: r.name,
            lat: r.lat,
            lng: r.lng,
            placeId: placeId
          })
        : { ok: false };
    if (!res.ok) {
      showStep('search');
      drawRows();
      note(
        res.reason === 'full'
          ? 'The board shows up to ' +
              lim('MAX_PINS', 8) +
              ' bus stops. Remove one in Settings to add another.'
          : res.reason === 'duplicate'
            ? 'That stop is already on the board.'
            : "Couldn't add that stop."
      );
      return;
    }
    var msg =
      'Added Route ' +
      r.route +
      ' at ' +
      r.name +
      ' to your board.' +
      (res.saved ? '' : " It can't be saved on this device.");
    nodes.doneMsg.textContent = msg;
    say(msg);
    showStep('done');
    nodes.doneShow.focus();
  }
  function build() {
    var n = {};
    n.head = el('h3', null, 'Add a bus stop');
    var form = (n.search = el('form', 'bv-add')),
      lab = el('label', null, 'Street, intersection, address or stop name'),
      q = (n.q = el('input')),
      row = el('div', 'bv-btnrow');
    form.noValidate = true;
    q.type = 'search';
    q.id = 'bvStopQ';
    q.placeholder = 'Try "47 wolf" or "2nd and Snyder"';
    q.dataset.fk = 'sq';
    lab.htmlFor = q.id;
    n.sug = S.suggest.attach(q, {
      onPick: function () {
        submit();
      },
      biasProvider: function () {
        return util.state.center;
      }
    });
    var go = el('button', 'bv-btn', 'Search');
    go.type = 'submit';
    row.appendChild(go);
    if (navigator.geolocation) row.appendChild(actionBtn('Use my location', locate));
    n.msg = el('p', 'bv-note');
    n.msg.id = 'bvAddMsg';
    n.msg.setAttribute('role', 'status');
    n.extra = el('div');
    n.res = el('ul', 'bv-res');
    q.setAttribute('aria-describedby', n.msg.id);
    [lab, q, row, n.msg, n.extra, n.res].forEach(function (x) {
      form.appendChild(x);
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      submit();
    });
    n.full = el('p', 'bv-note');
    n.place = el('div');
    n.placeHead = el('p', 'bv-note');
    n.placeList = el('div', 'bv-stack');
    n.placeBack = actionBtn('Back to the list', function () {
      showStep('search');
      var f = nodes.res.querySelector('button:not(:disabled)');
      (f || nodes.q).focus();
    });
    [n.placeHead, n.placeList, n.placeBack].forEach(function (x) {
      n.place.appendChild(x);
    });
    n.done = el('div');
    n.doneMsg = el('p', 'bv-note');
    var more = actionBtn('Add another stop', function () {
      start();
      nodes.q.focus();
    });
    n.doneShow = actionBtn('Show my board', close);
    [n.doneMsg, more, n.doneShow].forEach(function (x) {
      n.done.appendChild(x);
    });
    n.done.className = 'bv-stack';
    n.cancel = actionBtn('Done', close);
    n.cancel.dataset.fk = 'adone';
    n.cancel.style.marginTop = '18px';
    [n.head, n.full, n.search, n.place, n.done, n.cancel].forEach(function (x) {
      sheet.appendChild(x);
    });
    return n;
  }
  function start() {
    var b = board(),
      full = b && b.pins().length >= lim('MAX_PINS', 8);
    seq++;
    results = [];
    nodes.q.value = '';
    nodes.sug.close();
    nodes.res.replaceChildren();
    showStep('search');
    nodes.search.hidden = !!full;
    nodes.full.hidden = !full;
    nodes.full.textContent =
      'The board shows up to ' + lim('MAX_PINS', 8) + ' bus stops. Remove one in Settings to add another.';
    note('');
  }
  function position() {
    sheet.style.top = $('.bv-head').getBoundingClientRect().bottom + 6 + 'px';
  }
  function openSheet(o) {
    if (open || !board()) return;
    if (!nodes) nodes = build();
    opener = (o && o.opener) || null;
    open = true;
    settings.inert = true; /* the sheet lies over Settings: only the topmost sheet takes keys and taps */
    sheet.hidden = false;
    position();
    start();
    (nodes.search.hidden ? nodes.cancel : nodes.q).focus();
  }
  /* Where focus goes back to: the Settings sheet's own button when it lies underneath (drawn again, it shows the new pin), else the
     control that opened this sheet while it still shows, else the Settings button. */
  function close() {
    if (!open) return;
    reset();
    var back = null;
    if (!settings.hidden) {
      S.boardsettings.render();
      back = settings.querySelector('[data-fk="addstop"]') || settings.querySelector('button');
    } else if (opener && opener.isConnected && opener.getClientRects().length) back = opener;
    opener = null;
    (back || setBtn).focus();
  }
  /* Hides the sheet without moving focus (the board closing calls this). */
  function reset() {
    if (nodes) nodes.sug.close();
    seq++;
    open = false;
    sheet.hidden = true;
    settings.inert = false;
  }
  /* Escape in the search box first closes its suggestion list, then empties the box; only then does it close the sheet. */
  function escape() {
    var q = nodes && nodes.q;
    if (!open || !q) return false;
    if (q.getAttribute('aria-expanded') === 'true') {
      nodes.sug.close();
      return true;
    }
    if (document.activeElement === q && q.value) {
      q.value = '';
      nodes.sug.close();
      seq++;
      clearRows();
      note('');
      return true;
    }
    return false;
  }
  ['resize', 'orientationchange'].forEach(function (t) {
    window.addEventListener(t, function () {
      if (open) position();
    });
  });
  S.boardadd.open = openSheet;
  S.boardadd.close = close;
  S.boardadd.reset = reset;
  S.boardadd.escape = escape;
  S.boardadd.isOpen = function () {
    return open;
  };
})();
