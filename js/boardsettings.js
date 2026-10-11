/* js/boardsettings.js: the settings sheet of the "My stops board" (ARCHITECTURE.md section 16): get-ready minutes, snow or ice, night
   dimming, and for each pinned stop its place and walk time. Every change goes through S.board; this file only draws the sheet and
   says out loud when a change could not be saved. Needs js/boardview.js (loaded just before it). */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt || typeof document === 'undefined' || !S.boardview || !S.boardview.say) return;
  var util = S.util,
    $ = util.$,
    el = util.el,
    bv = S.boardview,
    board = bv.board,
    lim = bv.lim,
    say = bv.say;
  var settings = $('#bvSettings'),
    setBtn = $('#bvSet');
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
  /* updatePin answers {ok:false, reason}; a refused change is said out loud and the sheet is drawn again from the saved state. */
  function saved(res) {
    if (res === false || (res && res.ok === false)) say('Could not save that change');
  }
  function placeSelect(b, p, nm, n) {
    var opts = typeof b.pinOptions === 'function' ? b.pinOptions() : null;
    if (!opts || !opts.length) return null;
    var sel = el('select');
    sel.setAttribute('aria-label', 'Place for ' + nm);
    sel.dataset.fk = 'pl' + n;
    var known = false;
    opts.forEach(function (o) {
      var op = el('option', null, o.name);
      op.value = o.placeId == null ? '' : o.placeId;
      if ((o.placeId == null ? null : o.placeId) === (p.placeId == null ? null : p.placeId)) known = true;
      sel.appendChild(op);
    });
    if (!known) {
      var gone = el('option', null, 'Place removed');
      gone.value = p.placeId;
      sel.insertBefore(gone, sel.firstChild);
    }
    sel.value = p.placeId == null ? '' : p.placeId;
    sel.addEventListener('change', function () {
      saved(b.updatePin(p.id, { placeId: sel.value || null }));
      renderSettings();
    });
    var w = el('div', 'bv-line');
    w.appendChild(el('span', null, 'Place'));
    w.appendChild(sel);
    return w;
  }
  function renderSettings() {
    var b = board();
    var ae = document.activeElement,
      fk = ae && settings.contains(ae) ? ae.dataset.fk : null;
    settings.replaceChildren();
    settings.appendChild(el('h3', null, 'Board settings'));
    if (b) {
      var cfg = b.settings(),
        bufMax = lim('MAX_BUFFER_MIN', 15),
        extra = lim('BAD_EXTRA_MIN', 4),
        line = el('div', 'bv-line');
      var lab = el('span', null, 'Extra minutes to get ready');
      lab.appendChild(el('small', null, 'Added to your walk before you need to leave'));
      line.appendChild(lab);
      line.appendChild(
        stepper(
          'minutes to get ready',
          cfg.bufferMin + ' min',
          function () {
            saved(b.setSettings({ bufferMin: Math.max(0, cfg.bufferMin - 1) }));
            renderSettings();
          },
          function () {
            saved(b.setSettings({ bufferMin: Math.min(bufMax, cfg.bufferMin + 1) }));
            renderSettings();
          },
          cfg.bufferMin <= 0,
          cfg.bufferMin >= bufMax,
          'buf'
        )
      );
      settings.appendChild(line);
      settings.appendChild(
        check(
          'Snow or ice: add ' + extra + ' min',
          cfg.bad,
          function (v) {
            saved(b.setSettings({ bad: v }));
            renderSettings();
          },
          'bad'
        )
      );
    }
    settings.appendChild(
      check(
        'Night dimming',
        bv.dim(),
        function (v) {
          bv.dim(v);
        },
        'dim',
        'Dims the board from 10 PM to 6 AM'
      )
    );
    if (b) pinSettings(b);
    /* S.boardbikes is always an object; only the function says js/boardbikes.js loaded */
    if (S.boardbikes && typeof S.boardbikes.add === 'function') bikeSettings();
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
    bv.render();
  }
  function pinSettings(b) {
    var pins = b.pins(),
      walkMax = lim('MAX_WALK_MIN', 60);
    if (pins.length) settings.appendChild(el('h3', null, 'Pinned stops'));
    pins.forEach(function (p, n) {
      var auto = p.walkMin == null,
        cur = b.walkMin(p),
        pl = b.placeFor(p),
        nm = 'Route ' + p.route + ' at ' + p.stopName + (pl ? ' from ' + pl.name : '');
      var head = el('div', 'bv-line');
      head.appendChild(el('span', null, 'Route ' + p.route + ' at ' + p.stopName));
      var rm = el('button', 'bv-rm', 'Remove');
      rm.type = 'button';
      rm.setAttribute('aria-label', 'Remove ' + nm);
      rm.dataset.fk = 'rm' + n;
      rm.addEventListener('click', function () {
        saved(b.removePin(p.id));
        bv.render();
        renderSettings();
        (settings.querySelector('.bv-rm') || setBtn).focus();
      });
      head.appendChild(rm);
      settings.appendChild(head);
      var picker = placeSelect(b, p, nm, n);
      if (picker) settings.appendChild(picker);
      var w = el('div', 'bv-line');
      var wl = el('span', null, 'Walk time');
      wl.appendChild(el('small', null, auto ? 'Automatic, ' + cur + ' min' : 'You set ' + cur + ' min'));
      w.appendChild(wl);
      var setWalk = function (v) {
        saved(b.updatePin(p.id, { walkMin: v }));
        renderSettings();
      };
      w.appendChild(
        stepper(
          'walk minutes for ' + nm,
          cur + ' min',
          function () {
            setWalk(Math.max(1, cur - 1));
          },
          function () {
            setWalk(Math.min(walkMax, cur + 1));
          },
          cur <= 1,
          cur >= walkMax,
          'w' + n
        )
      );
      settings.appendChild(w);
      var auto2 = check(
        'Automatic walk time',
        auto,
        function (v) {
          setWalk(v ? null : cur);
        },
        'a' + n
      );
      auto2.querySelector('input').setAttribute('aria-label', 'Automatic walk time for ' + nm);
      settings.appendChild(auto2);
    });
  }
  /* ----- Bike stations: the picked ones with Remove, and a search box over the Indego station list (js/boardbikes.js) ----- */
  var bikeQuery = '',
    bikeNodes = null;
  function bikeResults() {
    var bb = S.boardbikes,
      n = bikeNodes;
    if (!n || !n.box.isConnected) return;
    var ready = bb.listReady(),
      failed = bb.listFailed(),
      found = ready ? bb.search(bikeQuery) : [],
      msg;
    /* A poll tells us the list again every minute: draw only when something shown would differ, so a focused result keeps focus. */
    var sig = [
      ready,
      failed,
      bikeQuery,
      bb
        .stations()
        .map(function (s) {
          return s.id;
        })
        .join(','),
      found
        .map(function (r) {
          return r.id + r.name + r.picked;
        })
        .join(',')
    ].join('|');
    if (n.sig === sig) return;
    n.sig = sig;
    if (!ready)
      msg = failed
        ? "The station list couldn't load. Check the connection and try again."
        : 'Loading stations...';
    else if (bikeQuery.trim() && !found.length) msg = 'No station matches that.';
    else if (!bikeQuery.trim()) msg = 'Type a street or station name, like Wolf or 2nd & Snyder.';
    else msg = found.length + (found.length === 1 ? ' station found' : ' stations found');
    if (n.msg.textContent !== msg) n.msg.textContent = msg;
    n.retry.hidden = !(failed && !ready);
    n.res.replaceChildren();
    /* the sheet scrolls: lift the box to the top when the results first appear, so they (and the keyboard) leave it in view */
    if (found.length && !n.had && document.activeElement === n.q && n.q.scrollIntoView)
      n.q.scrollIntoView({ block: 'start' });
    n.had = found.length > 0;
    found.forEach(function (r, i) {
      var li = el('li'),
        b = el('button', 'bv-pick');
      b.type = 'button';
      b.dataset.fk = 'bk' + i;
      b.disabled = r.picked;
      b.appendChild(el('span', null, r.name + (r.picked ? ' (added)' : '')));
      if (r.address) b.appendChild(el('small', null, r.address));
      b.addEventListener('click', function () {
        var res = S.boardbikes.add(r.id);
        if (res.ok) {
          bikeQuery = '';
          say('Added ' + r.name + ' to the board' + (res.saved ? '' : ". It can't be saved on this device"));
        } else
          say(
            res.reason === 'full'
              ? 'The board shows at most ' + S.boardbikes.MAX_STATIONS + ' bike stations'
              : res.reason === 'duplicate'
                ? 'Already on the board'
                : 'Could not add that station'
          );
        renderSettings();
        if (res.ok) {
          /* the tapped result is gone: focus the search box, else the new station's Remove button, else Done */
          var rms = settings.querySelectorAll('[data-fk^="bm"]'),
            to =
              settings.querySelector('[data-fk="bq"]') ||
              rms[rms.length - 1] ||
              settings.querySelector('[data-fk="done"]');
          if (to) to.focus();
        }
      });
      li.appendChild(b);
      n.res.appendChild(li);
    });
  }
  /* Escape in the search box empties it first; the board's Escape handler closes the sheet only when this answers false. */
  function escapeSearch() {
    var n = bikeNodes;
    if (!n || !n.box.isConnected || document.activeElement !== n.q || !bikeQuery) return false;
    bikeQuery = n.q.value = '';
    bikeResults();
    return true;
  }
  function bikeSettings() {
    var bb = S.boardbikes,
      picked = bb.stations();
    settings.appendChild(el('h3', null, 'Bike stations'));
    picked.forEach(function (s, n) {
      var line = el('div', 'bv-line');
      line.appendChild(el('span', null, s.name));
      var rm = el('button', 'bv-rm', 'Remove');
      rm.type = 'button';
      rm.setAttribute('aria-label', 'Remove bike station ' + s.name);
      rm.dataset.fk = 'bm' + n;
      rm.addEventListener('click', function () {
        saved(bb.remove(s.id));
        renderSettings();
        (
          settings.querySelector('[data-fk^="bm"]') ||
          settings.querySelector('[data-fk="bq"]') ||
          setBtn
        ).focus();
      });
      line.appendChild(rm);
      settings.appendChild(line);
    });
    if (picked.length >= bb.MAX_STATIONS) {
      settings.appendChild(
        el(
          'p',
          'bv-note',
          'The board shows up to ' + bb.MAX_STATIONS + ' bike stations. Remove one to add another.'
        )
      );
      bikeNodes = null;
      return;
    }
    bb.ensureList();
    var box = el('div', 'bv-add'),
      lab = el('label', null, 'Add a bike station'),
      q = el('input');
    q.type = 'search';
    q.id = 'bvBikeQ';
    q.autocomplete = 'off';
    q.setAttribute('autocapitalize', 'off');
    q.setAttribute('spellcheck', 'false');
    q.value = bikeQuery;
    q.dataset.fk = 'bq';
    lab.htmlFor = 'bvBikeQ';
    var msg = el('p', 'bv-note'),
      retry = el('button', 'bv-btn', 'Try again'),
      res = el('ul', 'bv-res');
    msg.setAttribute('role', 'status');
    retry.type = 'button';
    retry.hidden = true;
    retry.addEventListener('click', function () {
      bb.ensureList(true);
      bikeResults();
    });
    q.setAttribute('aria-describedby', 'bvBikeMsg');
    msg.id = 'bvBikeMsg';
    q.addEventListener('input', function () {
      bikeQuery = q.value;
      bikeResults();
    });
    q.addEventListener('keydown', function (e) {
      var first = res.querySelector('button:not(:disabled)');
      if (e.key === 'ArrowDown' && first) {
        e.preventDefault();
        first.focus();
      } else if (e.key === 'Enter' && first) {
        e.preventDefault();
        /* one result shown: add it; several: move to the first so a wrong guess is never added */
        if (res.querySelectorAll('button').length === 1) first.click();
        else first.focus();
      }
    });
    res.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      var all = [].slice.call(res.querySelectorAll('button:not(:disabled)')),
        i = all.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      var next = all[i + (e.key === 'ArrowDown' ? 1 : -1)];
      (next || (e.key === 'ArrowUp' ? q : null) || all[i]).focus();
    });
    [lab, q, msg, retry, res].forEach(function (n) {
      box.appendChild(n);
    });
    settings.appendChild(box);
    bikeNodes = { box: box, q: q, msg: msg, retry: retry, res: res, sig: '', had: false };
    bikeResults();
  }
  if (S.boardbikes && typeof S.boardbikes.onChange === 'function')
    S.boardbikes.onChange(function () {
      if (!settings.hidden) bikeResults();
    });
  function positionSettings() {
    /* below the header, so Settings and Close stay reachable; the header can change height when the screen turns */
    settings.style.top = $('.bv-head').getBoundingClientRect().bottom + 6 + 'px';
  }
  function openSettings() {
    settings.hidden = false;
    positionSettings();
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
  ['resize', 'orientationchange'].forEach(function (t) {
    window.addEventListener(t, function () {
      if (!settings.hidden) positionSettings();
    });
  });
  setBtn.addEventListener('click', function () {
    if (settings.hidden) openSettings();
    else closeSettings();
  });

  S.boardsettings.escape = escapeSearch;
  S.boardsettings.render = renderSettings;
  S.boardsettings.open = openSettings;
  S.boardsettings.close = closeSettings;
})();
