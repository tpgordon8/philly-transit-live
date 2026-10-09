/* js/suggest.js: place and address suggestions for every field where an address is typed (ARCHITECTURE.md section 15.1).
   S.suggest.attach(input, { onPick, biasProvider }) turns a text input into an ARIA 1.2 combobox. Well-known places (js/landmarks.js)
   match first and answer at once with no network. Photon (photon.komoot.io, OpenStreetMap data, made for type-ahead) adds
   street addresses and other places after a pause. Nominatim is never used here: its policy forbids autocomplete. */
(function () {
  'use strict';
  var S = window.SEPTA;
  var el = S.util.el,
    distMi = S.util.distMi,
    isNum = S.util.isNum;
  var PHOTON_URL = 'https://photon.komoot.io/api/',
    BOX = {
      w: -75.5,
      s: 39.7,
      e: -74.8,
      n: 40.2
    } /* the region box: sent as bbox and applied again to every answer */,
    MIN_CHARS = 3,
    DEBOUNCE_MS = 250,
    GAP_MS = 1000 /* at most one Photon request per second */,
    PHOTON_LIMIT = 6,
    MAX_LANDMARKS = 4,
    MAX_ITEMS = 8,
    MAX_QUERY = 100,
    MAX_LABEL = 80,
    MAX_SUB = 100,
    MAX_CACHE = 200,
    NEAR_MI = 10 /* results this close to the bias are listed before farther ones */,
    SAME_PLACE_MI = 0.25 /* a Photon answer with a built-in place's name within this distance (about 400 m) is that place */,
    MARGIN = 8,
    GAP_PX = 4;
  var STATES = { Pennsylvania: 'PA', 'New Jersey': 'NJ', Delaware: 'DE', Maryland: 'MD' };
  /* "10th and race", "Broad & Market": two streets. Photon does not do intersections (it answers with unrelated places);
   the submit path asks Nominatim, which does. */
  var STREETISH =
    /(^|\s)(\d+(st|nd|rd|th)|(\w+\s)*(st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|ln|lane|pkwy|parkway|broad|market|chestnut|walnut|spruce|pine|locust|race|arch|vine|girard|lombard|callowhill|passyunk|snyder|oregon))$/i;

  function norm(s) {
    var t = String(s || '').toLowerCase();
    if (t.normalize) t = t.normalize('NFD').replace(/[̀-ͯ]/g, '');
    return t
      .replace(/['’`]/g, '')
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  }
  /* Service text is shown with textContent only; this also removes control characters and caps the length. */
  function cap(s, n) {
    var t = '';
    String(s == null ? '' : s)
      .split('')
      .forEach(function (ch) {
        var c = ch.charCodeAt(0);
        t += c < 32 || c === 127 ? ' ' : ch;
      });
    t = t.replace(/\s+/g, ' ').trim();
    return t.length > n ? t.slice(0, n - 1) + '\u2026' : t;
  }
  function isIntersection(q) {
    var m = q.split(/\s+(?:and|at)\s+|\s*[&@/]\s*/i);
    return m.length === 2 && !!m[1] && STREETISH.test(m[0].trim());
  }

  /* ----- Built-in places ----- */
  var places = null;
  function loadPlaces() {
    if (places) return places;
    places = (S.landmarks.LIST || []).map(function (row) {
      var p = row.split('|'),
        keys = [norm(p[0])];
      p[1].split(',').forEach(function (a) {
        if (norm(a)) keys.push(norm(a));
      });
      return { label: p[0], sub: p[2], lat: Number(p[3]), lng: Number(p[4]), keys: keys, src: 'lm' };
    });
    return places;
  }
  /* Prefix matches (on the name or an alias) first, then substring matches, each in list order. */
  function matchPlaces(qn) {
    var pre = [],
      sub = [];
    loadPlaces().forEach(function (p) {
      if (
        p.keys.some(function (k) {
          return k.indexOf(qn) === 0;
        })
      )
        pre.push(p);
      else if (
        p.keys.some(function (k) {
          return k.indexOf(qn) > 0;
        })
      )
        sub.push(p);
    });
    return pre.concat(sub).slice(0, MAX_LANDMARKS);
  }
  function dupOfPlace(it) {
    var k = norm(it.label);
    return loadPlaces().some(function (p) {
      return p.keys.indexOf(k) >= 0 && distMi(p, it) < SAME_PLACE_MI;
    });
  }

  /* ----- Photon answers ----- */
  function inBox(lat, lng) {
    return isNum(lat) && isNum(lng) && lat >= BOX.s && lat <= BOX.n && lng >= BOX.w && lng <= BOX.e;
  }
  /* One feature to {label, sub, lat, lng}, or null. A feature whose name is only its address ("1234 Market") is labelled with
   the full street line; a named place keeps its name and shows the address on the second line. */
  function toItem(f) {
    var p = f && f.properties,
      c = f && f.geometry && f.geometry.coordinates;
    if (!p || !c || !inBox(Number(c[1]), Number(c[0]))) return null;
    var name = cap(p.name, MAX_LABEL),
      street = cap(p.street, MAX_LABEL),
      num = cap(p.housenumber, 12),
      line = (num && street ? num + ' ' : '') + street,
      st = STATES[p.state] || cap(p.state, 20),
      city = [cap(p.city || p.locality || p.district, 40), st].filter(Boolean).join(', ');
    var addressOnly = !name || (num && name.indexOf(num) === 0);
    var label = addressOnly ? line : name,
      sub = addressOnly || name === street ? city : [line, city].filter(Boolean).join(', ');
    if (!label || /^(country|state|county)$/.test(p.type)) return null;
    return { label: label, sub: cap(sub, MAX_SUB), lat: Number(c[1]), lng: Number(c[0]), src: 'ph' };
  }
  function parsePhoton(j, bias) {
    var out = [],
      seen = {};
    ((j && j.features) || []).forEach(function (f) {
      var it = toItem(f);
      if (!it) return;
      var k = norm(it.label) + '|' + it.lat.toFixed(3) + ',' + it.lng.toFixed(3);
      if (seen[k] || dupOfPlace(it)) return;
      seen[k] = 1;
      out.push(it);
    });
    if (bias) {
      var near = out.filter(function (it) {
        return distMi(bias, it) <= NEAR_MI;
      });
      out = near.concat(
        out.filter(function (it) {
          return near.indexOf(it) < 0;
        })
      );
    }
    return out;
  }

  /* ----- Photon requests: one scheduler for the whole page ----- */
  var cache = {},
    cacheN = 0,
    job = null,
    inflight = null,
    lastStart = 0;
  function cancelJob() {
    if (job) clearTimeout(job.timer);
    job = null;
    if (inflight) inflight.abort();
    inflight = null;
  }
  /* Debounced; a newer call replaces an older one, aborts its request, and waits out the 1 s gap since the last request. */
  function schedule(q, key, bias, done) {
    cancelJob();
    var wait = Math.max(DEBOUNCE_MS, lastStart + GAP_MS - Date.now());
    var j = (job = { timer: 0 });
    j.timer = setTimeout(function () {
      job = null;
      lastStart = Date.now();
      var ctl = typeof AbortController === 'function' ? new AbortController() : null;
      inflight = ctl;
      var url =
        PHOTON_URL +
        '?q=' +
        encodeURIComponent(q) +
        (bias ? '&lat=' + bias.lat.toFixed(2) + '&lon=' + bias.lng.toFixed(2) : '') +
        '&limit=' +
        PHOTON_LIMIT +
        '&bbox=' +
        [BOX.w, BOX.s, BOX.e, BOX.n].join(',') +
        '&lang=en';
      fetch(url, ctl ? { signal: ctl.signal } : {})
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function (json) {
          if (inflight === ctl) inflight = null;
          var items = parsePhoton(json, bias);
          if (cacheN >= MAX_CACHE) {
            cache = {};
            cacheN = 0;
          }
          cache[key] = items;
          cacheN++;
          done(items);
        })
        .catch(function () {
          /* Quiet failure (offline, blocked, rate limited, aborted): no suggestions; the submit path still works. */
          if (inflight === ctl) inflight = null;
          if (!ctl || !ctl.signal.aborted) done(null);
        });
    }, wait);
  }

  /* ----- The combobox ----- */
  var uid = 0,
    live = null,
    liveFlip = false;
  /* One polite live region for the page, created with the first field so it exists before anything is announced. */
  function liveRegion() {
    if (!live) {
      live = el('div', 'sr-only');
      live.id = 'sugLive';
      live.setAttribute('role', 'status');
      live.setAttribute('aria-live', 'polite');
      document.body.appendChild(live);
    }
    return live;
  }
  function say(text) {
    liveFlip = !liveFlip;
    liveRegion().textContent = text
      ? text + (liveFlip ? '' : '\u00a0')
      : ''; /* the alternating space lets a repeated message be read again */
  }

  /* One field's state `c` is made once by create() and passed to the small functions below; the page-wide pieces (the Photon scheduler,
     the cache, the live region) stay above. */
  function create(input, opts) {
    var id = 'sug' + ++uid,
      list = el('ul', 'sug-list');
    list.id = id + '-list';
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Suggestions');
    list.hidden = true;
    document.body.appendChild(list);
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-haspopup', 'listbox');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', list.id);
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('autocapitalize', 'off');
    input.setAttribute('spellcheck', 'false');
    var c = {
      input: input,
      opts: opts || {},
      id: id,
      list: list,
      items: [],
      active: -1,
      isOpen: false,
      pick: null,
      seq: 0
    };
    /* The page, the sidebar or the visual viewport moved (scroll, resize, on-screen keyboard); scrolling the list itself does not. */
    c.move = function (e) {
      if (!e || e.target !== list) placeList(c);
    };
    return c;
  }
  function biasOf(c) {
    var b = c.opts.biasProvider && c.opts.biasProvider();
    return b && isNum(b.lat) && isNum(b.lng) ? { lat: b.lat, lng: b.lng } : null;
  }
  /* ----- Position ----- */
  /* The list is position:fixed and appended to <body>, so the scrolling sidebar cannot clip it and no header covers it. It opens
     below the field, or above when there is more room there, and scrolls inside its own max-height. */
  function placeList(c) {
    var list = c.list,
      r = c.input.getBoundingClientRect(),
      vv = window.visualViewport,
      top = vv ? vv.offsetTop : 0,
      left = vv ? vv.offsetLeft : 0,
      vw = vv ? vv.width : window.innerWidth,
      vh = vv ? vv.height : window.innerHeight;
    if (r.bottom < top || r.top > top + vh) {
      setOpen(c, false);
      return;
    }
    var w = Math.min(r.width, vw - 2 * MARGIN),
      x = Math.min(Math.max(r.left, left + MARGIN), left + vw - w - MARGIN),
      keep = list.scrollTop;
    list.style.maxHeight = 'none';
    var full = list.scrollHeight,
      below = top + vh - r.bottom - GAP_PX - MARGIN,
      above = r.top - top - GAP_PX - MARGIN,
      up = full > below && above > below,
      h = Math.max(0, Math.min(full, up ? above : below));
    list.style.maxHeight = h + 'px';
    list.scrollTop = keep; /* measuring at full height reset it */
    list.style.width = w + 'px';
    list.style.left = x + 'px';
    list.style.top = (up ? r.top - GAP_PX - h : r.bottom + GAP_PX) + 'px';
  }
  function setOpen(c, on) {
    if (on === c.isOpen) {
      if (on) placeList(c);
      return;
    }
    c.isOpen = on;
    c.list.hidden = !on;
    c.input.setAttribute('aria-expanded', on ? 'true' : 'false');
    var fn = on ? 'addEventListener' : 'removeEventListener';
    window[fn]('resize', c.move);
    window[fn]('scroll', c.move, true);
    if (window.visualViewport) {
      window.visualViewport[fn]('resize', c.move);
      window.visualViewport[fn]('scroll', c.move);
    }
    if (on) placeList(c);
    else {
      setActive(c, -1);
      c.list.replaceChildren();
    }
  }
  /* ----- Rendering ----- */
  function setActive(c, i) {
    c.active = i;
    var rows = c.list.children;
    for (var k = 0; k < rows.length; k++) {
      rows[k].setAttribute('aria-selected', k === i ? 'true' : 'false');
    }
    if (i >= 0 && rows[i]) {
      c.input.setAttribute('aria-activedescendant', rows[i].id);
      rows[i].scrollIntoView({ block: 'nearest' });
    } else c.input.removeAttribute('aria-activedescendant');
  }
  function renderRows(c) {
    c.list.replaceChildren();
    c.items.forEach(function (it, i) {
      var li = el('li', 'sug-opt');
      li.id = c.id + '-' + i;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');
      li.dataset.i = i;
      li.appendChild(el('span', 'sug-l1', it.label));
      if (it.sub) li.appendChild(el('span', 'sug-l2', it.sub));
      c.list.appendChild(li);
    });
  }
  /* The count is announced only to a user who is still in the field: a late answer for a field they left stays silent. */
  function show(c, final, keep) {
    var n = c.items.length,
      focused = document.activeElement === c.input,
      at = keep && c.active < n ? c.active : -1;
    if (n && focused) {
      renderRows(c);
      setOpen(c, true);
      setActive(c, at);
    } else setOpen(c, false);
    if (final && focused) say(n ? n + (n === 1 ? ' suggestion' : ' suggestions') : 'No suggestions');
  }
  /* ----- Choosing and typing ----- */
  function choose(c, i) {
    var it = c.items[i];
    if (!it) return;
    c.items = [];
    c.seq++;
    cancelJob();
    c.input.value = it.label;
    c.pick = { lat: it.lat, lng: it.lng, name: it.label };
    setOpen(c, false);
    say('');
    if (c.opts.onPick) c.opts.onPick({ lat: it.lat, lng: it.lng, name: it.label, sub: it.sub });
  }
  function merge(lm, ph) {
    return lm.concat(ph || []).slice(0, MAX_ITEMS);
  }
  function onInput(c) {
    c.pick = null;
    var mine = ++c.seq,
      q = cap(c.input.value, MAX_QUERY);
    cancelJob();
    if (q.length < MIN_CHARS) {
      c.items = [];
      setOpen(c, false);
      say('');
      return;
    }
    var qn = norm(q),
      b = biasOf(c),
      key = qn + '|' + (b ? b.lat.toFixed(2) + ',' + b.lng.toFixed(2) : ''),
      lm = matchPlaces(qn);
    if (Object.prototype.hasOwnProperty.call(cache, key)) {
      c.items = merge(lm, cache[key]);
      show(c, true);
      return;
    }
    c.items = lm;
    if (isIntersection(q) || qn.length < MIN_CHARS) {
      show(c, true);
      return;
    }
    show(c, false); /* built-in places appear now; the count is announced once Photon has answered */
    schedule(q, key, b, function (res) {
      if (mine !== c.seq) return;
      c.items = merge(lm, res);
      show(c, true, true);
    });
  }
  /* ----- Keyboard ----- */
  function onArrow(c, e) {
    var n = c.items.length,
      down = e.key === 'ArrowDown';
    if (!n) return;
    e.preventDefault();
    if (!c.isOpen) {
      renderRows(c);
      setOpen(c, true);
      setActive(c, down ? 0 : n - 1);
      return;
    }
    setActive(c, down ? (c.active + 1) % n : (c.active - 1 + n) % n);
  }
  function onEscape(c, e) {
    if (c.isOpen) {
      e.preventDefault();
      setOpen(c, false);
    } else if (c.input.value) {
      e.preventDefault();
      c.input.value = '';
      c.input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }
  function onKeydown(c, e) {
    if (e.isComposing || e.keyCode === 229) return; /* an input method is composing: its keys are not ours */
    var n = c.items.length,
      k = e.key;
    if (k === 'ArrowDown' || k === 'ArrowUp') onArrow(c, e);
    else if ((k === 'Home' || k === 'End') && c.isOpen && n) {
      e.preventDefault();
      setActive(c, k === 'Home' ? 0 : n - 1);
    } else if (k === 'Enter') {
      if (c.isOpen && c.active >= 0) {
        e.preventDefault();
        choose(c, c.active);
      }
    } else if (k === 'Escape') onEscape(c, e);
    else if (k === 'Tab') setOpen(c, false);
  }
  /* ----- Pointer ----- */
  function wireList(c) {
    var list = c.list;
    /* A press on the list must not move focus out of the field: the blur would close the list before the pick. */
    list.addEventListener('mousedown', function (e) {
      e.preventDefault();
    });
    list.addEventListener('pointerdown', function (e) {
      var li = e.target.closest('[role=option]');
      if (!li) return;
      /* A mouse picks on press. A finger may be starting to scroll a long list, and hiding the list under a lifted finger
       lets the tap fall through to the map, so touch and pen pick on the tap's click. */
      if (e.pointerType === 'mouse' && e.button === 0) choose(c, Number(li.dataset.i));
    });
    list.addEventListener('click', function (e) {
      var li = e.target.closest('[role=option]');
      if (li && c.isOpen) choose(c, Number(li.dataset.i));
    });
  }

  /* Returns { picked(), close() }. close() drops the pending debounce, queued job and request, ignores any answer still on its way,
     and closes the list: call it before the field's text is used for something else (a submit). */
  function attach(input, opts) {
    liveRegion();
    var c = create(input, opts);
    input.addEventListener('input', function () {
      onInput(c);
    });
    input.addEventListener('keydown', function (e) {
      onKeydown(c, e);
    });
    function close() {
      c.seq++;
      cancelJob();
      setOpen(c, false);
    }
    input.addEventListener('blur', function () {
      cancelJob(); /* a request nobody is looking at is not worth sending */
      setOpen(c, false);
    });
    wireList(c);
    return {
      /* {lat, lng, name} while the field still holds exactly the picked label, else null (editing discards the pick). */
      picked: function () {
        return c.pick && input.value === c.pick.name
          ? { lat: c.pick.lat, lng: c.pick.lng, name: c.pick.name }
          : null;
      },
      close: close
    };
  }

  S.suggest.attach = attach;
})();
