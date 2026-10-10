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

  S.boardsettings.render = renderSettings;
  S.boardsettings.open = openSettings;
  S.boardsettings.close = closeSettings;
})();
