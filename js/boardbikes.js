/* js/boardbikes.js: Indego stations picked for the wall board (septa.boardbikes.v1) and their live counts (ARCHITECTURE.md 16.1). No DOM.
   Counts come from S.routing.loadIndego, the same client the map layer uses; this file only decides when to ask and what the answer means. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt) return;
  var shortText = S.util.shortText,
    store = S.util.store,
    isObj = S.util.isObj;
  /* SKEW_MS: a report time further ahead than this is a wrong device clock; the fetch time stands in */
  var KEY = 'septa.boardbikes.v1',
    MAX_STATIONS = 4,
    MAX_NAME = 60,
    MAX_LOW = 5 /* the "bikes at or below" warning is 0 to 5 */,
    MAX_RESULTS = 8,
    POLL_MS = 60000 /* status every minute while the board shows */,
    DIM_POLL_MS = 120000 /* every two minutes while the board is dimmed (night) */,
    MAX_WAIT_MS = 300000 /* back-off never waits longer than this between attempts (a longer base poll is never shortened) */,
    SHARE_MS = 55000 /* a status answer younger than this is reused, so this poller and the map layer's make one request a minute */,
    STALE_MIN = 10 /* the banner "Bike data is N min old" appears past this */,
    DOWN_MS =
      10 * 60000 /* after a failed refresh, the last good answer is no longer shown once it is this old */,
    INFO_MS = 6 * 3600000 /* the station list is asked for again after this long while the board is open */,
    SKEW_MS = 10 * 60000,
    ID_RE = /^[A-Za-z0-9_-]{1,40}$/;
  function isFin(n) {
    return typeof n === 'number' && isFinite(n);
  }
  function cleanStation(r) {
    if (!isObj(r) || typeof r.id !== 'string' || !ID_RE.test(r.id)) return null;
    var out = {
      id: r.id,
      name: shortText(typeof r.name === 'string' ? r.name : '', MAX_NAME) || 'Indego station'
    };
    /* Optional warnings (16.1): absent means off, so data saved before they existed loads unchanged. */
    if (isLow(r.lowBikes)) out.lowBikes = r.lowBikes;
    if (r.noDocks === true) out.noDocks = true;
    return out;
  }
  function isLow(n) {
    return typeof n === 'number' && n % 1 === 0 && n >= 0 && n <= MAX_LOW;
  }
  function cleanStore(raw) {
    var out = [],
      seen = {};
    (isObj(raw) && Array.isArray(raw.stations) ? raw.stations : []).forEach(function (r) {
      var s = out.length < MAX_STATIONS ? cleanStation(r) : null;
      if (!s || seen[s.id]) return;
      seen[s.id] = 1;
      out.push(s);
    });
    return { stations: out };
  }
  var stored = S.util.loadChecked(KEY, cleanStore, function (r, c) {
    return (
      !isObj(r) ||
      !Array.isArray(r.stations) ||
      r.stations.length !== c.stations.length ||
      c.stations.some(function (s, i) {
        var o = r.stations[i];
        return (
          (typeof o.name === 'string' && o.name !== s.name) ||
          (o.lowBikes != null && o.lowBikes !== s.lowBikes) ||
          (o.noDocks != null && o.noDocks !== s.noDocks)
        );
      })
    );
  });
  var listeners = [],
    data = null /* the last good answer: array of stations from S.routing.loadIndego */,
    byId = {},
    fetchedAt = 0,
    feedAsOf = 0,
    failedAt = 0 /* time of the latest failed refresh, 0 after a good one */,
    fails = 0,
    inflight = false,
    lastStart = 0,
    active = false;
  function emit() {
    listeners.slice().forEach(function (fn) {
      try {
        fn();
      } catch (e) {
        /* a listener must not break another listener or the poller */
      }
    });
  }
  function onChange(fn) {
    if (typeof fn === 'function') listeners.push(fn);
  }

  /* ----- Picked stations ----- */
  function stations() {
    return stored.stations.map(function (s) {
      var o = { id: s.id, name: s.name };
      if (s.lowBikes !== undefined) o.lowBikes = s.lowBikes;
      if (s.noDocks) o.noDocks = true;
      return o;
    });
  }
  /* setAlert(id, {lowBikes: 0..5 | null, noDocks: boolean}): either key may be left out to keep it. Answers false for an unknown
     station or a bad value (nothing changes), else whether it was saved. */
  function setAlert(id, o) {
    var st = null;
    stored.stations.forEach(function (s) {
      if (s.id === id) st = s;
    });
    if (!st || !isObj(o)) return false;
    if ('lowBikes' in o && o.lowBikes !== null && !isLow(o.lowBikes)) return false;
    if ('noDocks' in o && typeof o.noDocks !== 'boolean') return false;
    if ('lowBikes' in o) {
      if (o.lowBikes === null) delete st.lowBikes;
      else st.lowBikes = o.lowBikes;
    }
    if ('noDocks' in o) {
      if (o.noDocks) st.noDocks = true;
      else delete st.noDocks;
    }
    return save();
  }
  function has(id) {
    return stored.stations.some(function (s) {
      return s.id === id;
    });
  }
  function save() {
    var ok = store.set(KEY, stored);
    emit();
    sync();
    return ok;
  }
  /* The station with this id in a list from S.routing.loadIndego (null when the list is missing or lacks it). */
  function pick(list, id) {
    for (var i = 0; list && i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  /* add('id') needs the station list; add({id, name}) (the map card) does not. Answers {ok:true, station, saved} or {ok:false, reason}
     with invalid (bad id), duplicate, unknown (the id is not in the Indego list, or only an id was given and the list is not loaded) or full. */
  function add(arg) {
    var id = isObj(arg) ? arg.id : arg,
      name = isObj(arg) && typeof arg.name === 'string' ? arg.name : '';
    if (typeof id !== 'string' || !ID_RE.test(id)) return { ok: false, reason: 'invalid' };
    if (has(id)) return { ok: false, reason: 'duplicate' };
    var shared = S.routing && S.routing.lastIndego ? S.routing.lastIndego() : null,
      known = byId[id] || pick(shared, id);
    if (known) name = known.name;
    else if (!name || data || shared) return { ok: false, reason: 'unknown' };
    if (stored.stations.length >= MAX_STATIONS) return { ok: false, reason: 'full' };
    var st = cleanStation({ id: id, name: name });
    stored.stations.push(st);
    var saved = save();
    return { ok: true, station: { id: st.id, name: st.name }, saved: saved };
  }
  function remove(id) {
    for (var i = 0; i < stored.stations.length; i++)
      if (stored.stations[i].id === id) {
        stored.stations.splice(i, 1);
        save();
        return true;
      }
    return false;
  }

  /* ----- Search over the station list: case-insensitive, "and" counts as "&"; name starts with the text, then name contains it, then
     address contains it; each group A to Z; at most MAX_RESULTS. ----- */
  function norm(s) {
    return String(s || '')
      .toLowerCase()
      .replace(/\s+/g, ' ')
      .replace(/\band\b/g, '&')
      .trim();
  }
  function natural(a, b) {
    return a.localeCompare(b, 'en', { numeric: true });
  }
  function find(q) {
    var hits = [];
    data.forEach(function (s) {
      var n = norm(s.name),
        rank = n.indexOf(q) === 0 ? 0 : n.indexOf(q) > 0 ? 1 : norm(s.address).indexOf(q) >= 0 ? 2 : -1;
      if (rank >= 0) hits.push({ rank: rank, n: n, s: s });
    });
    return hits;
  }
  function search(query) {
    var q = norm(query);
    if (!q || !data) return [];
    var hits = find(q);
    /* "4th a" and "4th an" are on the way to "4th and": when nothing matches, drop that unfinished last word so the list does not blank */
    if (!hits.length && /\s(a|an)$/.test(q)) hits = find(q.replace(/\s(a|an)$/, ''));
    hits.sort(function (a, b) {
      return a.rank - b.rank || natural(a.n, b.n);
    });
    return hits.slice(0, MAX_RESULTS).map(function (h) {
      return { id: h.s.id, name: h.s.name, address: h.s.address || '', picked: has(h.s.id) };
    });
  }

  /* ----- What the numbers mean ----- */
  /* 'live' (fresh answer), 'stale' (the newest data is over 10 minutes old, or a refresh has failed since the last good answer),
     'down' (nothing to show: the first answer failed, or a refresh failed and the last good answer is over 10 minutes old),
     'loading' (no answer yet). */
  function source(nowMs) {
    nowMs = isFin(nowMs) ? nowMs : Date.now();
    if (!data) return failedAt ? 'down' : 'loading';
    if (failedAt) return nowMs - fetchedAt > DOWN_MS ? 'down' : 'stale';
    return nowMs - feedAsOf > STALE_MIN * 60000 ? 'stale' : 'live';
  }
  function refreshFailed() {
    return !!failedAt;
  }
  function feedAgeMin(nowMs) {
    return data ? Math.max(0, Math.floor(((isFin(nowMs) ? nowMs : Date.now()) - feedAsOf) / 60000)) : 0;
  }
  /* "just now", "1 minute ago", "7 minutes ago", "over 2 hours ago"; short: "just now", "1 min ago", "7 min ago". */
  function ageText(min, short) {
    if (min == null) return '';
    if (min < 1) return 'just now';
    if (min >= 120) return 'over ' + Math.floor(min / 60) + ' hours ago';
    return min + (short ? ' min' : min === 1 ? ' minute' : ' minutes') + ' ago';
  }
  /* The warnings a station's row shows: [{kind: 'bikes' | 'docks', text}]. Only when the answer is live and the station is renting
     (bikes) or taking returns (docks); "Low: 1 bike left" when bikes are at or below the chosen number, "No free docks" at 0 docks. */
  function warnings(r, live) {
    var out = [];
    if (!live || r.state === 'closed') return out;
    if (r.lowBikes !== null && r.bikes <= r.lowBikes)
      out.push({
        kind: 'bikes',
        text:
          r.bikes <= 0
            ? 'Low: no bikes left'
            : 'Low: ' + r.bikes + (r.bikes === 1 ? ' bike left' : ' bikes left')
      });
    if (r.noDocks && r.returning && r.docks <= 0) out.push({ kind: 'docks', text: 'No free docks' });
    return out;
  }
  /* One entry per picked station, in the order picked. electric = e-bikes; classic = every other bike (classic and smart together, so
     total bikes minus e-bikes); docks = open docks. state: closed (not installed or not renting), nobike (no bikes at all), noebike
     (bikes, but no e-bikes), ok, unknown (no usable data for it: loading, down, or the station is missing from the feed). */
  function rows(nowMs) {
    nowMs = isFin(nowMs) ? nowMs : Date.now();
    /* a warning needs fresh data: stale, failed and loading answers never raise one */
    var src = source(nowMs),
      up = src !== 'down',
      live = src === 'live';
    return stored.stations.map(function (p) {
      var s = up ? byId[p.id] : null,
        r = {
          id: p.id,
          name: s ? s.name : p.name,
          address: s ? s.address || '' : '',
          bikes: 0,
          typed: true,
          electric: 0,
          classic: 0,
          docks: 0,
          renting: false,
          returning: false,
          installed: false,
          lastReported: 0,
          ageMin: null,
          state: 'unknown',
          lowBikes: p.lowBikes === undefined ? null : p.lowBikes,
          noDocks: !!p.noDocks,
          warn: []
        };
      if (!s) return r;
      var at = s.asOf > 0 && s.asOf <= fetchedAt + SKEW_MS ? s.asOf : fetchedAt;
      var tot = isFin(s.total) ? s.total : s.bikes,
        el = isFin(s.electric) ? s.electric : s.ebikes;
      r.typed = s.typed !== false;
      r.bikes = tot;
      r.electric = r.typed ? el : 0;
      r.classic = r.typed ? Math.max(0, tot - el) : 0;
      r.docks = s.docks;
      r.renting = s.renting;
      r.returning = s.returning;
      r.installed = s.installed;
      r.lastReported = at;
      r.ageMin = Math.max(0, Math.floor((nowMs - at) / 60000));
      r.state =
        !s.installed || !s.renting ? 'closed' : tot <= 0 ? 'nobike' : r.typed && el <= 0 ? 'noebike' : 'ok';
      r.warn = warnings(r, live);
      return r;
    });
  }

  /* ----- Polling. Zero requests unless the board shows, the tab is visible and a station is picked. The board holds the page awake
     (S.feed.setAwake), so the hour-long idle pause is deliberately not consulted here. ----- */
  function boardOpen() {
    return !!(S.boardview && S.boardview.isOpen && S.boardview.isOpen());
  }
  function want() {
    return stored.stations.length > 0 && !document.hidden && boardOpen();
  }
  /* The wait between attempts: a minute (two while the board is dimmed), longer after failures (skip 1, 2, 4 polls, then 4: at most
     5 minutes apart on the default cadence, the same rule as the map layer). */
  function everyMs() {
    var base = S.boardview && S.boardview.isDim && S.boardview.isDim() ? DIM_POLL_MS : POLL_MS,
      skip = fails ? Math.min(Math.pow(2, fails - 1), 4) : 0;
    return Math.min(base * (skip + 1), Math.max(base, MAX_WAIT_MS));
  }
  function apply(list) {
    var now = Date.now();
    fails = 0;
    failedAt = 0;
    data = list;
    byId = {};
    list.forEach(function (s) {
      byId[s.id] = s;
    });
    /* the time the status was really fetched (a reused answer is older than this call), never later than the device clock */
    fetchedAt = list.fetchedAt > 0 && list.fetchedAt <= now ? list.fetchedAt : now;
    feedAsOf = list.asOf > 0 && list.asOf <= now + SKEW_MS ? list.asOf : fetchedAt;
  }
  function load() {
    if (inflight || !S.routing || !S.routing.loadIndego) return;
    inflight = true;
    lastStart = Date.now();
    S.routing.loadIndego(SHARE_MS, INFO_MS).then(
      function (list) {
        inflight = false;
        if (!Array.isArray(list) || !list.length) return miss();
        apply(list);
        emit();
      },
      function () {
        inflight = false;
        miss();
      }
    );
  }
  function miss() {
    failedAt = Date.now();
    fails++;
    emit();
  }
  /* Called every second, when the board opens or closes, and when a station is added or removed. */
  function sync() {
    if (!want()) {
      active = false;
      return;
    }
    if (!active) {
      active = true;
      lastStart = 0;
    }
    var now = Date.now();
    if (now < lastStart) lastStart = 0; /* the device clock jumped back */
    if (!inflight && now - lastStart >= everyMs()) load();
  }
  /* The settings sheet needs the station list before anything is picked: one load when it opens and nothing is loaded yet. */
  function ensureList(force) {
    if (data || inflight) return;
    if (force === true || !fails || Date.now() - lastStart >= everyMs() || Date.now() < lastStart) load();
  }
  setInterval(sync, 1000);
  document.addEventListener('visibilitychange', sync);

  S.boardbikes.KEY = KEY;
  S.boardbikes.MAX_STATIONS = MAX_STATIONS;
  S.boardbikes.MAX_RESULTS = MAX_RESULTS;
  S.boardbikes.MAX_LOW = MAX_LOW;
  S.boardbikes.setAlert = setAlert;
  S.boardbikes.STALE_MIN = STALE_MIN;
  S.boardbikes.stations = stations;
  S.boardbikes.has = has;
  S.boardbikes.add = add;
  S.boardbikes.remove = remove;
  S.boardbikes.search = search;
  S.boardbikes.rows = rows;
  S.boardbikes.source = source;
  S.boardbikes.refreshFailed = refreshFailed;
  S.boardbikes.feedAgeMin = feedAgeMin;
  S.boardbikes.ageText = ageText;
  S.boardbikes.listReady = function () {
    return !!data;
  };
  S.boardbikes.listFailed = function () {
    return !data && !!failedAt && !inflight;
  };
  S.boardbikes.ensureList = ensureList;
  S.boardbikes.onChange = onChange;
  S.boardbikes.sync = sync;
})();
