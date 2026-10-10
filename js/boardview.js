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
    RELOAD_HOUR = 4;
  var BUF_MAX = 15,
    WALK_MAX = 60;
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
    pending = null,
    rowEls = {},
    prevState = {},
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

  /* ----- Words ----- */
  function mins(n) {
    return n + (n === 1 ? ' minute' : ' minutes');
  }
  function etaText(m) {
    var r = Math.round(m);
    return r < 1 ? '<1 min' : r + ' min';
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
  function minValue(node, pre, m) {
    var r = Math.round(m);
    if (r < 1) setValue(node, pre, '<1', 'min');
    else setValue(node, pre, String(r), 'min');
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
  var EMPTY_MSG = 'Pin a stop to see when to leave. Open any bus stop on the map and tap Pin to board.';
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
      p[0].appendChild(el('span', 'bv-k', p[1]));
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
  function describe(r, eta, lv) {
    var t = 'Route ' + r.pin.route + ' at ' + r.pin.stopName;
    if (r.source === 'down') return t + ', times hidden, live data unavailable';
    if (!eta) return t + ', no bus heading here right now';
    t +=
      ', bus in ' +
      (eta.rough ? 'about ' : '') +
      (Math.round(eta.etaMin) < 1 ? 'less than a minute' : mins(Math.round(eta.etaMin)));
    if (eta.rough) t += ' (estimate)';
    if (!lv) return t;
    if (lv.state === 'now') return t + ', leave now';
    if (lv.state === 'missed') return t + ', you will miss this bus';
    return t + ', leave in ' + mins(lv.inMin);
  }
  function fillRow(li, r) {
    var a = r.arrivals || [],
      lv = r.leave,
      down = r.source === 'down',
      first = a[0] || null,
      then = a[1] || null;
    /* When the first bus cannot be made, the leave time is for the next one: show that bus as the main number. */
    if (lv && first && then && lv.forKey === then.key && lv.forKey !== first.key) {
      first = then;
      then = null;
    } else if (lv && first && lv.forKey === first.key) {
      then = a[1] || null;
    }
    var st = !down && first && lv ? lv.state : null;
    var kids = li.children,
      where = kids[0].children[1],
      bus = kids[1],
      lvEl = kids[2],
      none = kids[3];
    setText(where.firstChild, r.pin.stopName);
    var from = r.placeName ? 'from ' + r.placeName + ' · ' : '';
    setText(where.lastChild, from + r.walkMin + ' min walk');
    var hasNums = !down && !!first;
    bus.hidden = lvEl.hidden = !hasNums;
    none.hidden = hasNums;
    setText(none, down ? 'Times hidden' : 'No bus heading here right now');
    if (hasNums) {
      var bv = bus.children[1],
        bx = bus.children[2];
      minValue(bv, first.rough ? 'about' : '', first.etaMin);
      var sig = (first.rough ? 'r' : '') + '|' + (then ? etaText(then.etaMin) : '');
      if (bx.dataset.sig !== sig) {
        bx.dataset.sig = sig;
        bx.replaceChildren();
        if (first.rough) bx.appendChild(el('span', 'bv-tag', 'estimate'));
        if (then) bx.appendChild(el('span', null, 'then ' + etaText(then.etaMin)));
      }
      if (then && bx.lastChild && bx.lastChild.textContent !== 'then ' + etaText(then.etaMin))
        bx.lastChild.textContent = 'then ' + etaText(then.etaMin);
      var v = lvEl.children[1];
      if (!lv || lv.state === 'missed') setValue(v, '', '\u2014', '');
      else if (lv.state === 'now') setValue(v, '', 'Now', '');
      else setValue(v, '', String(lv.inMin), 'min');
      if ((lvEl.children[2].dataset.s || '') !== (st || '')) {
        lvEl.children[2].replaceChildren();
        lvEl.children[2].dataset.s = st || '';
        if (st) lvEl.children[2].appendChild(stateEl(st));
      }
    }
    li.dataset.state = st || '';
    var label = describe(r, first, lv);
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
      src = 'live';
    rows.forEach(function (r) {
      if (r.source === 'down') src = 'down';
      else if (r.source === 'stale' && src !== 'down') src = 'stale';
    });
    setText($('#bvEmptyMsg'), b ? EMPTY_MSG : 'Board is not available.');
    emptyBox.hidden = rows.length > 0;
    list.hidden = !rows.length;
    var msg =
      src === 'down'
        ? 'Live data unavailable. Times hidden.'
        : src === 'stale'
          ? 'Positions may be out of date'
          : '';
    banner.hidden = !msg;
    banner.classList.toggle('down', src === 'down');
    setText(banner, msg);
    var i = 0;
    rows.forEach(function (r) {
      var id = r.pin.id;
      ids[id] = 1;
      var li = rowEls[id];
      if (!li) li = rowEls[id] = makeRow(r.pin);
      fillRow(li, r);
      var cur = list.children[i];
      if (cur !== li) list.insertBefore(li, cur || null);
      i++;
      announce(r, id);
    });
    Object.keys(rowEls).forEach(function (id) {
      if (ids[id]) return;
      if (rowEls[id].parentNode) rowEls[id].remove();
      delete rowEls[id];
      delete prevState[id];
    });
  }
  /* The live region speaks only when a row newly reaches "leave now", never for the countdown itself. */
  function announce(r, id) {
    var st = r.source !== 'down' && r.leave && r.arrivals && r.arrivals.length ? r.leave.state : null;
    if (prevState[id] !== undefined && prevState[id] !== 'now' && st === 'now')
      live.textContent = 'Leave now for route ' + r.pin.route + ' at ' + r.pin.stopName + '.';
    prevState[id] = st;
  }

  /* ----- Settings sheet ----- */
  function stepper(label, value, onDec, onInc, decOff, incOff, key) {
    var s = el('span', 'bv-stepper');
    var d = el('button', null, '−'),
      i = el('button', null, '+');
    d.type = i.type = 'button';
    d.setAttribute('aria-label', 'Less ' + label);
    i.setAttribute('aria-label', 'More ' + label);
    d.dataset.fk = key + 'd';
    i.dataset.fk = key + 'i';
    d.disabled = !!decOff;
    i.disabled = !!incOff;
    d.addEventListener('click', onDec);
    i.addEventListener('click', onInc);
    var out = el('output', null, value);
    out.setAttribute('aria-label', label);
    s.appendChild(d);
    s.appendChild(out);
    s.appendChild(i);
    return s;
  }
  function check(text, on, onChange, key, hint) {
    var l = el('label', 'bv-line');
    var t = el('span', null, text);
    if (hint) t.appendChild(el('small', null, hint));
    var c = el('input');
    c.type = 'checkbox';
    c.checked = !!on;
    c.dataset.fk = key;
    c.addEventListener('change', function () {
      onChange(c.checked);
    });
    var w = el('span', 'bv-chk');
    w.style.flex = '0 0 auto';
    w.appendChild(c);
    l.appendChild(t);
    l.appendChild(w);
    return l;
  }
  function renderSettings() {
    var b = board();
    var ae = document.activeElement,
      fk = ae && settings.contains(ae) ? ae.dataset.fk : null;
    settings.replaceChildren();
    var h = el('h3', null, 'Board settings');
    settings.appendChild(h);
    if (b) {
      var cfg = b.settings(),
        line = el('div', 'bv-line');
      var lab = el('span', null, 'Extra minutes to get ready');
      lab.appendChild(el('small', null, 'Added to your walk before you need to leave'));
      line.appendChild(lab);
      line.appendChild(
        stepper(
          'minutes to get ready',
          cfg.bufferMin + ' min',
          function () {
            b.setSettings({ bufferMin: Math.max(0, cfg.bufferMin - 1) });
            renderSettings();
          },
          function () {
            b.setSettings({ bufferMin: Math.min(BUF_MAX, cfg.bufferMin + 1) });
            renderSettings();
          },
          cfg.bufferMin <= 0,
          cfg.bufferMin >= BUF_MAX,
          'buf'
        )
      );
      settings.appendChild(line);
      settings.appendChild(
        check(
          'Snow or ice: add 4 min',
          cfg.bad,
          function (v) {
            b.setSettings({ bad: v });
            renderSettings();
          },
          'bad'
        )
      );
    }
    settings.appendChild(
      check(
        'Night dimming',
        view.dim,
        function (v) {
          view.dim = v;
          saveView();
          tick();
        },
        'dim',
        'Dims the board from 10 PM to 6 AM'
      )
    );
    if (b) {
      var pins = b.pins();
      if (pins.length) settings.appendChild(el('h3', null, 'Pinned stops'));
      pins.forEach(function (p, n) {
        var auto = p.walkMin == null,
          cur = b.walkMin(p),
          nm = 'Route ' + p.route + ' at ' + p.stopName;
        var head = el('div', 'bv-line');
        head.appendChild(el('span', null, nm));
        var rm = el('button', 'bv-rm', 'Remove');
        rm.type = 'button';
        rm.setAttribute('aria-label', 'Remove ' + nm);
        rm.dataset.fk = 'rm' + n;
        rm.addEventListener('click', function () {
          b.removePin(p.id);
          render();
          renderSettings();
          var next = settings.querySelector('.bv-rm') || setBtn;
          next.focus();
        });
        head.appendChild(rm);
        settings.appendChild(head);
        var w = el('div', 'bv-line');
        var wl = el('span', null, 'Walk time');
        wl.appendChild(el('small', null, auto ? 'Automatic, ' + cur + ' min' : 'You set ' + cur + ' min'));
        w.appendChild(wl);
        w.appendChild(
          stepper(
            'walk minutes for ' + nm,
            cur + ' min',
            function () {
              b.updatePin(p.id, { walkMin: Math.max(1, cur - 1) });
              renderSettings();
            },
            function () {
              b.updatePin(p.id, { walkMin: Math.min(WALK_MAX, cur + 1) });
              renderSettings();
            },
            cur <= 1,
            cur >= WALK_MAX,
            'w' + n
          )
        );
        settings.appendChild(w);
        settings.appendChild(
          check(
            'Automatic walk time',
            auto,
            function (v) {
              b.updatePin(p.id, { walkMin: v ? null : cur });
              renderSettings();
            },
            'a' + n
          )
        );
      });
    }
    var done = el('button', 'bv-btn', 'Done');
    done.type = 'button';
    done.style.marginTop = '18px';
    done.dataset.fk = 'done';
    done.addEventListener('click', closeSettings);
    settings.appendChild(done);
    if (fk) {
      var back = settings.querySelector('[data-fk="' + fk + '"]');
      if (back && !back.disabled) back.focus();
      else if (back) (back.parentNode.querySelector('button:not(:disabled)') || settings.firstChild).focus();
    }
    render();
  }
  function openSettings() {
    settings.hidden = false;
    settings.style.top =
      $('.bv-head').getBoundingClientRect().bottom +
      6 +
      'px'; /* below the header, so Settings and Close stay reachable */
    setBtn.setAttribute('aria-expanded', 'true');
    renderSettings();
    var f = settings.querySelector('input, button');
    if (f) f.focus();
  }
  function closeSettings() {
    if (settings.hidden) return;
    settings.hidden = true;
    setBtn.setAttribute('aria-expanded', 'false');
    setBtn.focus();
  }
  setBtn.addEventListener('click', function () {
    if (settings.hidden) openSettings();
    else closeSettings();
  });

  /* ----- Screen wake lock: asked for while the board shows, asked again when the page becomes visible ----- */
  function wake() {
    try {
      if (!open || document.hidden || lock || !navigator.wakeLock || !navigator.wakeLock.request) return;
      var p = navigator.wakeLock.request('screen');
      if (!p || !p.then) return;
      lock = 'pending';
      p.then(
        function (l) {
          lock = l;
          if (l && l.addEventListener)
            l.addEventListener('release', function () {
              if (lock === l) lock = null;
            });
          if (!open) release();
        },
        function () {
          lock = null;
        }
      );
    } catch (e) {
      lock = null;
    }
  }
  function release() {
    var l = lock;
    lock = null;
    try {
      if (l && l !== 'pending' && l.release) {
        var p = l.release();
        if (p && p.catch) p.catch(function () {});
      }
    } catch (e) {
      /* nothing to release */
    }
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
  function maybeReload(now) {
    if (now >= reloadAt() && now - lastInput >= RELOAD_QUIET_MS) api.reload();
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
    var d = new Date();
    setText(clockEl, clockText(d));
    setText(updEl, updText());
    root.classList.toggle('dim', view.dim && isNight(d));
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
    if (S.feed.setAwake) S.feed.setAwake(true);
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
    try {
      S.map.map.invalidateSize({ animate: false, pan: false });
    } catch (e) {
      /* the map redraws on its next resize */
    }
    var back = opener && document.contains(opener) && opener.focus ? opener : $('#addr');
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
  document.addEventListener(
    'keydown',
    function (e) {
      if (e.key !== 'Escape' || !open) return;
      e.stopImmediatePropagation();
      if (!settings.hidden) closeSettings();
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
  api.show = show;
  api.hide = hide;
  api.render = render;
  api.isNight = isNight;
  sync();
})();
