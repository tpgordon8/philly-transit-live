/* js/boardview.js: the "My stops board" station sign (ARCHITECTURE.md section 16). Everything it knows about pins, walking time and
   the leave-in countdown comes from S.board (js/board.js); this file only draws it, tracks the clock, keeps the screen awake and
   switches between board mode and the normal app. Without S.board the board says so and Close still works. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt || typeof document === 'undefined') return;
  var util = S.util,
    $ = util.$,
    el = util.el,
    state = util.state;
  var KEY = 'septa.boardview.v1'; /* { dim: boolean } */
  var DIM_FROM = 22,
    DIM_TO = 6; /* night dimming: 10 PM up to 6 AM local */
  var RELOAD_AFTER_MS = 12 * 3600000,
    RELOAD_QUIET_MS = 10 * 60000,
    RELOAD_RETRY_MS = 10 * 60000,
    RELOAD_HOUR = 4,
    RELOAD_END = 6; /* the refresh happens from 4 AM up to 6 AM local, never in the daytime */
  var CHECK_MS = 8000; /* "Checking live data" for this long after opening, until the first fetch lands */
  var FAR_MIN = 45,
    SPOKEN_MS = 2 * 60000; /* a bus may be announced again after this long out of "leave now" */
  var root = $('#boardView'),
    app = $('#app'),
    list = $('#bvList'),
    emptyBox = $('#bvEmpty'),
    banner = $('#bvBanner'),
    settings = $('#bvSettings'),
    setBtn = $('#bvSet'),
    live = $('#bvLive'),
    clockEl = $('#bvClock'),
    updEl = $('#bvUpd');
  var api = S.boardview;
  var open = false,
    opener = null,
    loadedAt = Date.now(),
    lastInput = Date.now(),
    lock = null,
    reqSeq = 0,
    openedAt = 0,
    reloadTry = 0,
    reloadBusy = false,
    dimmed = null,
    pending = null,
    rowEls = {},
    prevState = {},
    spoken = {},
    saying = [],
    hooked = false;

  /* ----- Saved choice: night dimming (default on). Corrupt text is backed up and the default is used. ----- */
  function cleanView(p) {
    return {
      dim: !!p && typeof p === 'object' && !Array.isArray(p) && typeof p.dim === 'boolean' ? p.dim : true
    };
  }
  var view = util.loadChecked(KEY, cleanView, function (p, c) {
    return !!p && (typeof p !== 'object' || Array.isArray(p) || p.dim !== c.dim);
  });
  function saveView() {
    util.store.set(KEY, { dim: view.dim });
  }
  function board() {
    return S.board && typeof S.board.rows === 'function' ? S.board : null;
  }
  /* The limits belong to S.board; the fallbacks only matter when it is missing. */
  function lim(name, fallback) {
    var v = S.board && S.board[name];
    return typeof v === 'number' ? v : fallback;
  }

  /* ----- Words ----- */
  function mins(n) {
    return n + (n === 1 ? ' minute' : ' minutes');
  }
  /* Times are shown rounded down, so the board never promises more time than there is. */
  function whole(m) {
    return Math.max(0, Math.floor(m));
  }
  function etaText(a) {
    return a.far ? FAR_MIN + '+ min' : whole(a.etaMin) < 1 ? 'due' : whole(a.etaMin) + ' min';
  }
  /* A big value is the number with its small unit (and "about") beside it, so even a narrow phone keeps the number at full size. */
  function setValue(node, pre, num, unit) {
    var sig = pre + '|' + num + '|' + unit;
    if (node.dataset.sig === sig) return;
    node.dataset.sig = sig;
    node.replaceChildren();
    if (pre) node.appendChild(el('span', 'bv-u', pre + ' '));
    node.appendChild(document.createTextNode(num));
    if (unit) node.appendChild(el('span', 'bv-u', ' ' + unit));
  }
  function busValue(node, a) {
    var pre = a.rough ? 'about' : '';
    if (a.far) setValue(node, pre, FAR_MIN + '+', 'min');
    else if (whole(a.etaMin) < 1) setValue(node, pre, 'Due', '');
    else setValue(node, pre, String(whole(a.etaMin)), 'min');
  }
  function clockText(d) {
    var h = d.getHours(),
      m = d.getMinutes();
    return (h % 12 || 12) + ':' + (m < 10 ? '0' : '') + m + ' ' + (h < 12 ? 'AM' : 'PM');
  }
  function updText() {
    var ok = state.src.bus.ok;
    if (!ok) return 'Waiting for the first update';
    var s = Math.max(0, Math.round((Date.now() - ok) / 1000));
    return 'Updated ' + (s < 90 ? s + ' s' : Math.round(s / 60) + ' min') + ' ago';
  }
  var EMPTY_MSG =
    'Pin a stop or a bike station to see them here. Open a bus stop or an Indego station on the map and tap Pin to board.';
  var STATE_WORD = { later: 'later', soon: 'SOON', now: 'LEAVE NOW', missed: 'MISSED' };
  var ICON = {
    later:
      '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M12 7v5.5l3.5 2" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
    soon: '<path d="M12 3 22 20H2z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="M12 10v5M12 17.2v.6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
    now: '<path d="M3 12h15M12 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>',
    missed:
      '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M8.2 8.2l7.6 7.6M15.8 8.2l-7.6 7.6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>'
  };
  function stateEl(st) {
    var b = el('span', 'bv-state');
    b.dataset.s = st;
    b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + ICON[st] + '</svg>';
    b.appendChild(el('span', null, STATE_WORD[st]));
    return b;
  }
  function setText(node, t) {
    if (node.textContent !== t) node.textContent = t;
  }

  /* ----- Rows: built once per pin, then only the changed texts are written (so nothing flickers or loses its place) ----- */
  function makeRow(pin) {
    var li = el('li', 'bv-row'),
      kind = util.kindOf(pin.route);
    var where = el('div', 'bv-where');
    where.appendChild(el('div', 'bv-stop'));
    where.appendChild(el('div', 'bv-from'));
    var bus = el('div', 'bv-n bv-bus'),
      lv = el('div', 'bv-n bv-leave');
    [
      [bus, 'Bus in'],
      [lv, 'Leave in']
    ].forEach(function (p) {
      var k = el('span', 'bv-k', p[1]);
      if (p[0] === bus) k.appendChild(el('span', 'bv-est', ' (estimate)'));
      p[0].appendChild(k);
      p[0].appendChild(el('span', 'bv-v'));
      p[0].appendChild(el('span', 'bv-x'));
    });
    var top = el('div', 'bv-top');
    top.appendChild(el('span', 'rbadge k-' + kind, pin.route));
    top.appendChild(where);
    li.appendChild(top);
    li.appendChild(bus);
    li.appendChild(lv);
    li.appendChild(el('div', 'bv-none'));
    return li;
  }
  function describe(r, eta, lv, checking) {
    var t = 'Route ' + r.pin.route + ' at ' + r.pin.stopName;
    if (r.note === 'place-removed') t += ', place removed, walk set to ' + r.walkMin + ' minutes';
    if (r.source === 'down')
      return t + (checking ? ', checking live data' : ', times hidden, live data unavailable');
    if (!eta)
      return (
        t + (r.pending > 0 ? ', a bus is nearby, time not known yet' : ', no bus heading here right now')
      );
    var w = whole(eta.etaMin);
    t += eta.far
      ? ', bus in more than ' + FAR_MIN + ' minutes'
      : ', bus in ' + (eta.rough ? 'about ' : '') + (w < 1 ? 'less than a minute' : mins(w));
    t += ' (estimate)';
    if (!lv) return t;
    if (lv.state === 'now') return t + ', leave now';
    if (lv.state === 'missed') return t + ', you will miss this bus';
    return t + ', leave in ' + mins(lv.inMin);
  }
  function fillRow(li, r, checking) {
    var a = r.arrivals || [],
      lv = r.leave,
      down = r.source === 'down',
      first = a[0] || null,
      then = a[1] || null;
    /* When the first bus cannot be made, the leave time is for the next one: show that bus as the main number. */
    if (lv && first && then && lv.forKey === then.key && lv.forKey !== first.key) {
      first = then;
      then = null;
    }
    var st = !down && first && lv ? lv.state : null;
    var kids = li.children,
      where = kids[0].children[1],
      bus = kids[1],
      lvEl = kids[2],
      none = kids[3];
    setText(where.firstChild, r.pin.stopName);
    setText(
      where.lastChild,
      r.note === 'place-removed'
        ? 'Place removed, walk set to ' + r.walkMin + ' min'
        : (r.placeName ? 'from ' + r.placeName + ' · ' : '') + r.walkMin + ' min walk'
    );
    var hasNums = !down && !!first;
    bus.hidden = lvEl.hidden = !hasNums;
    none.hidden = hasNums;
    setText(
      none,
      down
        ? checking
          ? 'Checking live data'
          : 'Times hidden'
        : r.pending > 0
          ? 'Bus nearby, time not known yet'
          : 'No bus heading here right now'
    );
    if (hasNums) {
      var bx = bus.children[2];
      busValue(bus.children[1], first);
      var sig = (first.rough ? 'r' : '') + '|' + (then ? etaText(then) : '');
      if (bx.dataset.sig !== sig) {
        bx.dataset.sig = sig;
        bx.replaceChildren();
        if (first.rough) bx.appendChild(el('span', 'bv-tag', 'estimate'));
        if (then) bx.appendChild(el('span', null, 'then ' + etaText(then)));
      }
      var v = lvEl.children[1],
        slot = lvEl.children[2];
      if (!lv) setValue(v, '', '—', '');
      else if (lv.state === 'missed') setValue(v, '', '—', '');
      else if (lv.state === 'now') setValue(v, '', 'Now', '');
      else setValue(v, '', String(lv.inMin), 'min');
      var skey = st || (lv ? '' : 'far');
      if ((slot.dataset.s || '') !== skey) {
        slot.replaceChildren();
        slot.dataset.s = skey;
        if (st) slot.appendChild(stateEl(st));
        else if (skey === 'far') slot.appendChild(el('span', null, 'Too far ahead to say'));
      }
    }
    li.dataset.state = st || '';
    var label = describe(r, first, lv, checking);
    if (li.getAttribute('aria-label') !== label) li.setAttribute('aria-label', label);
  }
  function render() {
    var b = board(),
      rows = [];
    try {
      if (b) rows = b.rows(Date.now()) || [];
    } catch (e) {
      /* a failing board shows as empty */
    }
    var ids = {},
      src = 'live',
      checking = !state.src.bus.ok && Date.now() - openedAt < CHECK_MS;
    rows.forEach(function (r) {
      if (r.source === 'down') src = 'down';
      else if (r.source === 'stale' && src !== 'down') src = 'stale';
    });
    var nBikes = S.boardbikes && S.boardbikes.stations ? S.boardbikes.stations().length : 0;
    setText($('#bvEmptyMsg'), b ? EMPTY_MSG : 'Board is not available.');
    emptyBox.hidden = rows.length > 0 || nBikes > 0;
    list.hidden = !rows.length && !nBikes;
    var msg =
      src === 'down'
        ? checking
          ? 'Checking live data'
          : 'Live data unavailable. Times hidden.'
        : src === 'stale'
          ? 'Positions may be out of date'
          : '';
    banner.hidden = !msg;
    banner.classList.toggle('down', src === 'down' && !checking);
    setText(banner, msg);
    var i = 0,
      nowKeys = {};
    rows.forEach(function (r) {
      var id = r.pin.id;
      ids[id] = 1;
      var li = rowEls[id];
      if (!li) li = rowEls[id] = makeRow(r.pin);
      fillRow(li, r, checking);
      var cur = list.children[i];
      if (cur !== li) list.insertBefore(li, cur || null);
      i++;
      announce(r, id, nowKeys);
    });
    Object.keys(rowEls).forEach(function (id) {
      if (ids[id]) return;
      if (rowEls[id].parentNode) rowEls[id].remove();
      delete rowEls[id];
      delete prevState[id];
    });
    forgetSpoken(nowKeys);
    try {
      if (S.boardbikesview)
        S.boardbikesview.render(list); /* the Indego tiles, after the bus rows (js/boardbikesview.js) */
    } catch (e) {
      /* the bus rows still show */
    }
  }
  /* The live region speaks once per bus, the first time its row reaches "leave now" (never for the countdown, never on the first
     draw). The bus is forgotten only after it has been out of "leave now" for 2 minutes, so a flicker does not say it again. */
  function announce(r, id, nowKeys) {
    var on = r.source !== 'down' && r.leave && r.arrivals && r.arrivals.length && r.leave.state === 'now',
      key = on ? r.leave.forKey : null;
    if (key) {
      nowKeys[key] = 1;
      if (!(key in spoken) && prevState[id] !== undefined) say('Route ' + r.pin.route + ': leave now');
      spoken[key] = 0;
    }
    prevState[id] = on ? 'now' : 'other';
  }
  function forgetSpoken(nowKeys) {
    var t = Date.now();
    Object.keys(spoken).forEach(function (k) {
      if (nowKeys[k]) return;
      if (!spoken[k]) spoken[k] = t;
      else if (t - spoken[k] >= SPOKEN_MS) delete spoken[k];
    });
  }
  /* Cleared first so the same words are announced again; messages raised together are read together. */
  function say(msg) {
    saying.push(msg);
    if (saying.length > 1) return;
    live.textContent = '';
    setTimeout(function () {
      live.textContent = saying.join(' ');
      saying = [];
    }, 50);
  }

  /* ----- Screen wake lock: asked for while the board shows, asked again when the page becomes visible.
     Each request has a number; an answer that arrives after the board closed (or after a newer request) is released at once. ----- */
  function drop(l) {
    try {
      var p = l && l !== 'pending' && l.release ? l.release() : null;
      if (p && p.catch) p.catch(function () {});
    } catch (e) {
      /* nothing to release */
    }
  }
  function wake() {
    try {
      if (!open || document.hidden || lock || !navigator.wakeLock || !navigator.wakeLock.request) return;
      var p = navigator.wakeLock.request('screen'),
        mine = ++reqSeq;
      if (!p || !p.then) return;
      lock = 'pending';
      p.then(
        function (l) {
          if (mine !== reqSeq || !open) return drop(l);
          lock = l;
          if (l && l.addEventListener)
            l.addEventListener('release', function () {
              if (lock === l) lock = null;
            });
        },
        function () {
          if (mine === reqSeq) lock = null;
        }
      );
    } catch (e) {
      lock = null;
    }
  }
  function release() {
    var l = lock;
    lock = null;
    reqSeq++;
    drop(l);
  }
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) wake();
  });

  /* ----- Clock, dimming and the nightly refresh ----- */
  function isNight(d) {
    var h = d.getHours();
    return h >= DIM_FROM || h < DIM_TO;
  }
  /* The first 4 AM local after the page has been open for 12 hours. */
  function reloadAt() {
    var d = new Date(loadedAt + RELOAD_AFTER_MS);
    d.setHours(RELOAD_HOUR, 0, 0, 0);
    if (d.getTime() < loadedAt + RELOAD_AFTER_MS) d.setDate(d.getDate() + 1);
    return d.getTime();
  }
  /* Reload only between 4 and 6 AM, after 12 hours open and 10 quiet minutes, and only when the page can really be fetched again:
     a reload offline would replace a working board with an error page. A failed check is retried every 10 minutes until 6 AM. */
  function maybeReload(now) {
    var h = new Date(now).getHours();
    if (reloadBusy || now < reloadAt() || now - lastInput < RELOAD_QUIET_MS) return;
    if (h < RELOAD_HOUR || h >= RELOAD_END || now < reloadTry) return;
    reloadTry = now + RELOAD_RETRY_MS;
    if (navigator.onLine === false || typeof fetch !== 'function') return;
    reloadBusy = true;
    fetch(location.href.split('#')[0], { cache: 'no-store' }).then(
      function (r) {
        reloadBusy = false;
        if (r && r.ok) api.reload();
      },
      function () {
        reloadBusy = false;
      }
    );
  }
  ['pointerdown', 'touchstart', 'keydown', 'wheel'].forEach(function (t) {
    document.addEventListener(
      t,
      function () {
        lastInput = Date.now();
      },
      { capture: true, passive: true }
    );
  });
  function tick() {
    if (!open) return;
    var d = new Date(),
      dim = view.dim && isNight(d);
    setText(clockEl, clockText(d));
    setText(updEl, updText());
    root.classList.toggle('dim', dim);
    /* a dimmed board is a bedroom wall at night: the feed slows to every 30 s (js/feed.js) */
    if (dim !== dimmed && S.feed.setAwake) S.feed.setAwake(true, (dimmed = dim));
    render();
    maybeReload(d.getTime());
  }
  setInterval(tick, 1000);

  /* ----- Mode switching ----- */
  function wanted() {
    var q = null;
    try {
      q = new URLSearchParams(location.search).get('board');
    } catch (e) {
      /* no query string to read */
    }
    return location.hash === '#board' || q === '1';
  }
  function show() {
    if (open) return;
    open = true;
    opener = pending;
    pending = null;
    root.hidden = false;
    document.body.classList.add('board-on');
    app.inert = true;
    app.setAttribute('aria-hidden', 'true');
    openedAt = Date.now();
    dimmed = null; /* tick() tells the feed whether the board is dimmed */
    if (S.feed.setAwake) S.feed.setAwake(true);
    if (S.boardbikes && S.boardbikes.sync) S.boardbikes.sync(); /* bike counts: ask at once */
    if (!hooked && board() && board().onChange) {
      hooked = true;
      board().onChange(function () {
        if (open) render();
      });
    }
    lastInput = Date.now();
    tick();
    render();
    wake();
    try {
      S.feed.refresh();
    } catch (e) {
      /* the next tick of the feed loop will try again */
    }
    root.focus({ preventScroll: true });
  }
  function hide() {
    if (!open) return;
    open = false;
    root.hidden = true;
    settings.hidden = true;
    setBtn.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('board-on');
    app.inert = false;
    app.removeAttribute('aria-hidden');
    release();
    if (S.feed.setAwake) S.feed.setAwake(false);
    if (S.boardbikes && S.boardbikes.sync) S.boardbikes.sync();
    try {
      S.map.map.invalidateSize({ animate: false, pan: false });
    } catch (e) {
      /* the map redraws on its next resize */
    }
    var back =
      opener && document.contains(opener) && opener.focus
        ? opener
        : $('#btnBoard'); /* a button, so no keyboard rises */
    opener = null;
    if (back) back.focus({ preventScroll: true });
  }
  /* Close takes the board out of the address (so the address bar matches the screen) and leaves. */
  function close() {
    try {
      var u = new URL(location.href);
      u.searchParams.delete('board');
      if (u.hash === '#board') u.hash = '';
      history.replaceState(history.state, '', u.pathname + u.search + u.hash);
    } catch (e) {
      /* the hash change below still leaves */
    }
    hide();
  }
  function sync() {
    if (wanted()) show();
    else hide();
  }
  window.addEventListener('hashchange', sync);
  $('#bvClose').addEventListener('click', close);
  $('#bvCloseEmpty').addEventListener('click', close);
  $('#btnBoard').addEventListener('click', function () {
    pending = $('#btnBoard');
    location.hash = '#board';
  });
  /* A toast has its own Escape handler (js/alerts.js, on the toast itself): while one shows, this handler leaves the key alone so
     that Escape closes the toast first and the board on the next press. */
  document.addEventListener(
    'keydown',
    function (e) {
      if (e.key !== 'Escape' || !open || document.querySelector('#toasts .toast')) return;
      e.stopImmediatePropagation();
      if (!settings.hidden) S.boardsettings.close();
      else close();
    },
    true
  );
  api.reload = function () {
    location.reload();
  };
  api.isOpen = function () {
    return open;
  };
  api.isDim = function () {
    return !!dimmed;
  };
  api.show = show;
  api.hide = hide;
  api.render = render;
  api.isNight = isNight;
  api.board = board;
  api.lim = lim;
  api.say = say;
  api.tick = tick;
  api.dim = function (on) {
    if (typeof on === 'boolean') {
      view.dim = on;
      saveView();
      tick();
    }
    return view.dim;
  };
  sync();
})();
