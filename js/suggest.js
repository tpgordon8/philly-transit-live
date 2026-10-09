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
      return p.keys.indexOf(k) >= 0 && distMi(p, it) < 0.25;
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

  function attach(input, opts) {
    opts = opts || {};
    liveRegion();
    var id = 'sug' + ++uid,
      list = el('ul', 'sug-list'),
      items = [],
      active = -1,
      isOpen = false,
      pick = null,
      seq = 0;
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

    function bias() {
      var b = opts.biasProvider && opts.biasProvider();
      return b && isNum(b.lat) && isNum(b.lng) ? { lat: b.lat, lng: b.lng } : null;
    }
    /* The list is position:fixed and appended to <body>, so the scrolling sidebar cannot clip it and no header covers it. It opens
     below the field, or above when there is more room there, and scrolls inside its own max-height. */
    function place() {
      var r = input.getBoundingClientRect(),
        vv = window.visualViewport,
        top = vv ? vv.offsetTop : 0,
        left = vv ? vv.offsetLeft : 0,
        vw = vv ? vv.width : window.innerWidth,
        vh = vv ? vv.height : window.innerHeight;
      if (r.bottom < top || r.top > top + vh) {
        close();
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
    /* The page, the sidebar or the visual viewport moved (scroll, resize, on-screen keyboard); scrolling the list itself does not. */
    function move(e) {
      if (!e || e.target !== list) place();
    }
    function setOpen(on) {
      if (on === isOpen) {
        if (on) place();
        return;
      }
      isOpen = on;
      list.hidden = !on;
      input.setAttribute('aria-expanded', on ? 'true' : 'false');
      var fn = on ? 'addEventListener' : 'removeEventListener';
      window[fn]('resize', move);
      window[fn]('scroll', move, true);
      if (window.visualViewport) {
        window.visualViewport[fn]('resize', move);
        window.visualViewport[fn]('scroll', move);
      }
      if (on) place();
      else {
        setActive(-1);
        list.replaceChildren();
      }
    }
    function close() {
      setOpen(false);
    }
    function setActive(i) {
      active = i;
      var rows = list.children;
      for (var k = 0; k < rows.length; k++) {
        rows[k].setAttribute('aria-selected', k === i ? 'true' : 'false');
      }
      if (i >= 0 && rows[i]) {
        input.setAttribute('aria-activedescendant', rows[i].id);
        rows[i].scrollIntoView({ block: 'nearest' });
      } else input.removeAttribute('aria-activedescendant');
    }
    function render() {
      list.replaceChildren();
      items.forEach(function (it, i) {
        var li = el('li', 'sug-opt');
        li.id = id + '-' + i;
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');
        li.dataset.i = i;
        li.appendChild(el('span', 'sug-l1', it.label));
        if (it.sub) li.appendChild(el('span', 'sug-l2', it.sub));
        list.appendChild(li);
      });
    }
    function show(final, keep) {
      var at = keep && active < items.length ? active : -1;
      if (items.length && document.activeElement === input) {
        render();
        setOpen(true);
        setActive(at);
      } else close();
      if (final)
        say(
          items.length
            ? items.length + (items.length === 1 ? ' suggestion' : ' suggestions')
            : 'No suggestions'
        );
    }
    function choose(i) {
      var it = items[i];
      if (!it) return;
      items = [];
      seq++;
      cancelJob();
      input.value = it.label;
      pick = { lat: it.lat, lng: it.lng, name: it.label };
      close();
      say('');
      if (opts.onPick) opts.onPick({ lat: it.lat, lng: it.lng, name: it.label, sub: it.sub });
    }
    function merge(lm, ph) {
      return lm.concat(ph || []).slice(0, MAX_ITEMS);
    }
    function onInput() {
      pick = null;
      var mine = ++seq,
        q = cap(input.value, MAX_QUERY);
      cancelJob();
      if (q.length < MIN_CHARS) {
        items = [];
        close();
        say('');
        return;
      }
      var qn = norm(q),
        key = qn,
        lm = matchPlaces(qn),
        b = bias();
      if (Object.prototype.hasOwnProperty.call(cache, key)) {
        items = merge(lm, cache[key]);
        show(true);
        return;
      }
      items = lm;
      if (isIntersection(q) || qn.length < MIN_CHARS) {
        show(true);
        return;
      }
      show(false); /* built-in places appear now; the count is announced once Photon has answered */
      schedule(q, key, b, function (res) {
        if (mine !== seq) return;
        items = merge(lm, res);
        show(true, true);
      });
    }
    input.addEventListener('input', onInput);
    input.addEventListener('keydown', function (e) {
      var n = items.length,
        k = e.key;
      if (k === 'ArrowDown' || k === 'ArrowUp') {
        if (!n) return;
        e.preventDefault();
        if (!isOpen) {
          render();
          setOpen(true);
          setActive(k === 'ArrowDown' ? 0 : n - 1);
          return;
        }
        setActive(k === 'ArrowDown' ? (active + 1) % n : (active - 1 + n) % n);
      } else if ((k === 'Home' || k === 'End') && isOpen && n) {
        e.preventDefault();
        setActive(k === 'Home' ? 0 : n - 1);
      } else if (k === 'Enter') {
        if (isOpen && active >= 0) {
          e.preventDefault();
          choose(active);
        }
      } else if (k === 'Escape') {
        if (isOpen) {
          e.preventDefault();
          close();
        } else if (input.value) {
          e.preventDefault();
          input.value = '';
          input.dispatchEvent(new Event('input', { bubbles: true }));
        }
      } else if (k === 'Tab') close();
    });
    input.addEventListener('blur', close);
    /* A press on the list must not move focus out of the field: the blur would close the list before the pick. */
    list.addEventListener('mousedown', function (e) {
      e.preventDefault();
    });
    list.addEventListener('pointerdown', function (e) {
      var li = e.target.closest('[role=option]');
      if (!li) return;
      /* A mouse picks on press. A finger may be starting to scroll a long list, and hiding the list under a lifted finger
       lets the tap fall through to the map, so touch and pen pick on the tap's click. */
      if (e.pointerType === 'mouse' && e.button === 0) choose(Number(li.dataset.i));
    });
    list.addEventListener('click', function (e) {
      var li = e.target.closest('[role=option]');
      if (li && isOpen) choose(Number(li.dataset.i));
    });
    return {
      /* {lat, lng, name} while the field still holds exactly the picked label, else null (editing discards the pick). */
      picked: function () {
        return pick && input.value === pick.name ? { lat: pick.lat, lng: pick.lng, name: pick.name } : null;
      }
    };
  }

  S.suggest.attach = attach;
})();
