/* js/alerts.js: service alerts and leave-now alert rules. Part of the classic-script split of index.html (ARCHITECTURE.md section 14). */ /*@split*/
(function () {
  /*@split*/
  'use strict'; /*@split*/
  var S = window.SEPTA; /*@split*/
  var DROP_AFTER_MS = S.util.DROP_AFTER_MS,
    state = S.util.state; /*@split*/
  var etaFor = S.stops.etaFor; /*@split*/
  /* ----- Leave-now rules. A rule may fire only from a numeric, non-rough etaFor result for a bus whose very next stop is the
   rule's stop, while the bus source is fresh. `src` is {ok,stale} for the bus source (defaults to the live one). ----- */
  var RULE_DEDUPE_MS = 15 * 60000;
  function evalRule(rule, vehicles, now, src) {
    if (!rule || rule.enabled === false) return { state: 'paused' };
    if (src === undefined) src = typeof state !== 'undefined' && state && state.src ? state.src.bus : null;
    if (!src || !src.ok || now - src.ok > DROP_AFTER_MS || src.stale) return { state: 'unavailable' };
    var stop = { id: rule.stopId, lat: rule.lat, lng: rule.lng },
      cands = [],
      any = false,
      still = false;
    (vehicles || []).forEach(function (v) {
      if (
        !v ||
        v.kind === 'train' ||
        v.kind === 'subway' ||
        v.route !== rule.route ||
        v.nextId !== rule.stopId
      )
        return;
      any = true;
      var e = etaFor(v, stop);
      if (e.min != null && !e.rough) cands.push({ key: v.key, min: e.min });
      else if (e.note === 'not moving') still = true;
    });
    if (!cands.length) return { state: any ? (still ? 'still' : 'measuring') : 'none' };
    cands.sort(function (a, b) {
      return a.min - b.min;
    });
    var res = { state: 'watching', min: cands[0].min, key: cands[0].key, fire: false };
    for (var i = 0; i < cands.length; i++) {
      var c = cands[i];
      if (c.min > rule.minutes) break;
      if (rule.last && rule.last.key === c.key && now - rule.last.t < RULE_DEDUPE_MS) continue;
      res.fire = true;
      res.fireKey = c.key;
      res.fireMin = c.min;
      break;
    }
    return res;
  }
  S.alerts.evalRule = evalRule; /*@split*/
  if (S.halt) return; /*@split*/
  var $ = S.util.$,
    distMi = S.util.distMi,
    el = S.util.el,
    parseSeptaDate = S.util.parseSeptaDate,
    shortText = S.util.shortText,
    store = S.util.store; /*@split*/
  var alertKey = S.feed.alertKey,
    collect = S.feed.collect,
    idleNow = S.feed.idleNow,
    pauseNow = S.feed.pauseNow,
    septa = S.feed.septa; /*@split*/
  var vehicleAlertKey = S.feed.vehicleAlertKey; /*@split*/
  var NARROW = S.ui.NARROW; /*@split*/
  var STOP_ID_RE = S.stops.STOP_ID_RE,
    STOP_RT_RE = S.stops.STOP_RT_RE; /*@split*/
  /* ----- Alerts ----- */
  function stripHTML(s) {
    if (!s) return '';
    var d = new DOMParser().parseFromString(String(s), 'text/html');
    return (d.body.textContent || '').replace(/\s+/g, ' ').trim();
  }
  function buildAlerts(raw) {
    var items = [],
      now = new Date();
    (Array.isArray(raw) ? raw : []).forEach(function (a) {
      var key = alertKey(a),
        label =
          a.mode === 'generic'
            ? 'System'
            : a.mode === 'Bus' || a.mode === 'Trolley'
              ? 'Route ' + a.route
              : a.route_name || a.route;
      function push(type, text, until) {
        text = shortText(stripHTML(text), 320);
        if (!text) return;
        items.push({ key: key, label: label, mode: a.mode, type: type, text: text, until: until || null });
      }
      if (a.isalert === 'Y') push('alert', a.alert || a.description);
      if (a.isadvisory === 'Yes') push('advisory', a.advisory || a.description);
      if (a.isdetour === 'Y' && Array.isArray(a.detour)) {
        a.detour.forEach(function (d) {
          var end = parseSeptaDate(d.end);
          if (end && end < now) return;
          var txt = [
            d.reason && String(d.reason).trim(),
            d.location_start && 'At ' + d.location_start,
            d.message
          ]
            .filter(Boolean)
            .join(' · ');
          push('detour', txt, end);
        });
      }
    });
    return items;
  }
  function loadAlerts() {
    return septa('Alerts/index.php')
      .then(function (j) {
        state.alerts.items = buildAlerts(j);
        state.alerts.ok = Date.now();
        state.alerts.err = false;
      })
      .catch(function () {
        state.alerts.err = true;
      })
      .then(renderAlerts);
  }
  function renderAlerts() {
    var ul = $('#alerts'),
      A = state.alerts;
    ul.replaceChildren();
    var cnt = $('#alertCount');
    if (A.err && !A.items.length) {
      cnt.textContent = '';
      ul.appendChild(el('li', 'empty-line', 'Alerts are unavailable right now.'));
      return;
    }
    if (!A.ok) {
      cnt.textContent = '';
      ul.appendChild(el('li', 'empty-line', 'Loading alerts…'));
      return;
    }
    var near = new Set(['*']);
    collect().forEach(function (v) {
      if (distMi(state.center, v) <= state.radius) near.add(vehicleAlertKey(v));
    });
    var items = A.items.filter(function (i) {
      return A.scope === 'all' || near.has(i.key);
    });
    var order = { alert: 0, advisory: 1, detour: 2 };
    items.sort(function (a, b) {
      return (near.has(b.key) ? 1 : 0) - (near.has(a.key) ? 1 : 0) || order[a.type] - order[b.type];
    });
    cnt.textContent = '(' + items.length + ')';
    if (!items.length) {
      ul.appendChild(
        el(
          'li',
          'empty-line',
          A.scope === 'all'
            ? 'No active alerts system-wide.'
            : 'No active alerts for the routes running near this search.'
        )
      );
      return;
    }
    items.slice(0, 60).forEach(function (i) {
      var li = el('li', 'alert'),
        top = el('div', 'top');
      top.appendChild(el('span', 'tag k-' + i.type, i.type));
      top.appendChild(el('b', null, i.label));
      li.appendChild(top);
      li.appendChild(el('p', null, i.text));
      if (i.until)
        li.appendChild(
          el(
            'div',
            'until',
            'Until ' +
              i.until.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
          )
        );
      ul.appendChild(li);
    });
    if (items.length > 60)
      ul.appendChild(el('li', 'empty-line', 'Showing the first 60 of ' + items.length + '.'));
  }
  function setScope(s) {
    state.alerts.scope = s;
    $('#scopeNear').setAttribute('aria-pressed', String(s === 'near'));
    $('#scopeAll').setAttribute('aria-pressed', String(s === 'all'));
    renderAlerts();
  }
  $('#scopeNear').addEventListener('click', function () {
    setScope('near');
  });
  $('#scopeAll').addEventListener('click', function () {
    setScope('all');
  });
  setInterval(function () {
    if (idleNow()) {
      pauseNow();
      return;
    }
    if (!document.hidden) loadAlerts();
  }, 300000);
  /* ----- Leave-now alerts: rules in localStorage (septa.rules.v1), evaluated in the page on every apply() ----- */
  var MAX_RULES = 10,
    RULES_KEY = 'septa.rules.v1',
    ALERT_MINS = [3, 5, 8, 10, 15],
    RULE_ID_RE = /^[A-Za-z0-9_-]{1,40}$/;
  function cleanRules(raw) {
    var out = [],
      ids = {},
      dups = {};
    var list = raw && typeof raw === 'object' && Array.isArray(raw.rules) ? raw.rules : [];
    list.forEach(function (r) {
      if (out.length >= MAX_RULES || !r || typeof r !== 'object') return;
      if (typeof r.id !== 'string' || !RULE_ID_RE.test(r.id) || ids[r.id]) return;
      if (typeof r.route !== 'string' || !STOP_RT_RE.test(r.route)) return;
      if (typeof r.stopId !== 'string' || !STOP_ID_RE.test(r.stopId)) return;
      if (typeof r.minutes !== 'number' || !Number.isInteger(r.minutes) || r.minutes < 2 || r.minutes > 30)
        return;
      if (typeof r.lat !== 'number' || typeof r.lng !== 'number' || !isFinite(r.lat) || !isFinite(r.lng))
        return;
      var dk = r.route + '|' + r.stopId + '|' + r.minutes;
      if (dups[dk]) return;
      var last = null;
      if (
        r.last &&
        typeof r.last === 'object' &&
        typeof r.last.key === 'string' &&
        r.last.key.length <= 64 &&
        typeof r.last.t === 'number' &&
        isFinite(r.last.t)
      )
        last = { key: r.last.key, t: r.last.t };
      ids[r.id] = dups[dk] = 1;
      out.push({
        id: r.id,
        route: r.route,
        stopId: r.stopId,
        stopName: shortText(
          typeof r.stopName === 'string' && r.stopName ? r.stopName : 'Stop ' + r.stopId,
          80
        ),
        lat: r.lat,
        lng: r.lng,
        minutes: r.minutes,
        enabled: r.enabled !== false,
        last: last
      });
    });
    return { rules: out };
  }
  var rulesState = cleanRules(store.get(RULES_KEY, null));
  function saveRules() {
    store.set(RULES_KEY, rulesState);
  }
  function hasActiveRule() {
    return (
      !!rulesState &&
      rulesState.rules.some(function (r) {
        return r.enabled;
      })
    );
  }
  function newRuleId() {
    return 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }
  function findRule(route, stopId, minutes) {
    for (var i = 0; i < rulesState.rules.length; i++) {
      var r = rulesState.rules[i];
      if (r.route === route && r.stopId === stopId && r.minutes === minutes) return r;
    }
    return null;
  }
  function leaveMsg(r, min) {
    return 'Leave now — the ' + r.route + ' is about ' + min + ' min from ' + r.stopName;
  }
  /* Toasts: role="alert" on each one, so it is announced once when inserted. Never auto-dismissed; max 3 shown. */
  function notify(msg) {
    try {
      var box = $('#toasts'),
        t = el('div', 'toast'),
        m = el('span', 'tmsg', msg),
        b = el('button', 'btn small', 'Dismiss');
      t.setAttribute('role', 'alert');
      b.type = 'button';
      function close() {
        t.remove();
      }
      b.addEventListener('click', close);
      t.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') close();
      });
      t.appendChild(m);
      t.appendChild(b);
      box.appendChild(t);
      /* Desktop shows up to 3 and drops the oldest. On a phone only the newest shows and the rest wait (CSS), so keep up to 20. */
      while (box.children.length > (NARROW.matches ? 20 : 3)) box.firstChild.remove();
    } catch (e) {
      /* a toast is best effort */
    }
    try {
      if (window.Notification && Notification.permission === 'granted' && document.hidden)
        new Notification(msg);
    } catch (e) {
      /* Notification can throw on some browsers; the toast already shows */
    }
  }
  function ruleStatusText(res) {
    switch (res.state) {
      case 'paused':
        return 'Paused';
      case 'unavailable':
        return 'Live data unavailable';
      case 'measuring':
        return 'Measuring speed…';
      case 'still':
        return 'Watching — a bus is heading here but not moving';
      case 'watching':
        return 'Watching — nearest bus about ' + res.min + ' min';
      default:
        return 'Watching — no bus heading here yet';
    }
  }
  function evalRules() {
    if (!rulesState || state.paused) return;
    var all = collect(),
      now = Date.now(),
      changed = false,
      src = state.src.bus;
    rulesState.rules.forEach(function (r) {
      var res = evalRule(r, all, now, src);
      if (res.fire) {
        r.last = { key: res.fireKey, t: now };
        changed = true;
        notify(leaveMsg(r, res.fireMin));
      }
      var li = document.querySelector('#rules li[data-id="' + r.id + '"] .rstatus');
      if (li) li.textContent = ruleStatusText(res);
    });
    if (changed) saveRules();
  }
  function renderRules() {
    var ul = $('#rules');
    ul.replaceChildren();
    $('#rulesEmpty').hidden = rulesState.rules.length > 0;
    rulesState.rules.forEach(function (r) {
      var li = el('li', 'rule');
      li.dataset.id = r.id;
      li.appendChild(
        el('div', 'rt1', 'Route ' + r.route + ' · ' + r.stopName + ' · under ' + r.minutes + ' min')
      );
      li.appendChild(el('p', 'rstatus', ''));
      var ctl = el('div', 'rctl'),
        lab = el('label', 'rtog'),
        cb = el('input', 'rtoggle');
      cb.type = 'checkbox';
      cb.checked = r.enabled;
      cb.setAttribute('aria-label', 'Alert on for route ' + r.route + ' at ' + r.stopName);
      cb.addEventListener('change', function () {
        r.enabled = cb.checked;
        saveRules();
        evalRules();
      });
      lab.appendChild(cb);
      lab.appendChild(el('span', null, 'On'));
      ctl.appendChild(lab);
      var rm = el('button', 'btn small rrm', 'Remove');
      rm.type = 'button';
      rm.setAttribute('aria-label', 'Remove alert for route ' + r.route + ' at ' + r.stopName);
      rm.addEventListener('click', function () {
        var i = rulesState.rules.indexOf(r);
        if (i < 0) return;
        rulesState.rules.splice(i, 1);
        saveRules();
        renderRules();
        updateAlertRow();
        var next = document.querySelectorAll('#rules .rrm')[Math.min(i, rulesState.rules.length - 1)];
        if (next) next.focus();
        else $('#h-leave').focus();
      });
      ctl.appendChild(rm);
      li.appendChild(ctl);
      ul.appendChild(li);
    });
    evalRules();
  }
  function alertRow(st) {
    var row = el('div', 'alertrow');
    row.appendChild(el('span', null, 'Alert me when route ' + st.route + ' is under'));
    var sel = el('select');
    sel.id = 'alertMin';
    sel.setAttribute('aria-label', 'Minutes away to alert at');
    ALERT_MINS.forEach(function (m) {
      var o = el('option', null, String(m));
      o.value = String(m);
      if (m === 8) o.selected = true;
      sel.appendChild(o);
    });
    row.appendChild(sel);
    row.appendChild(el('span', null, 'min away'));
    var b = el('button', 'btn small primary', 'Add alert');
    b.type = 'button';
    b.id = 'addAlert';
    row.appendChild(b);
    var live = el('div', 'live');
    live.id = 'alertLive';
    live.setAttribute('role', 'status');
    live.setAttribute('aria-live', 'polite');
    sel.addEventListener('change', function () {
      live.textContent = '';
      updateAlertRow();
    });
    b.addEventListener('click', function () {
      var s = state.stop;
      if (!s) return;
      var m = parseInt(sel.value, 10);
      if (findRule(s.route, s.id, m)) return;
      if (rulesState.rules.length >= MAX_RULES) {
        live.textContent = 'You can keep up to ' + MAX_RULES + ' alerts.';
        return;
      }
      rulesState.rules.push({
        id: newRuleId(),
        route: s.route,
        stopId: s.id,
        stopName: shortText(s.name, 80),
        lat: s.lat,
        lng: s.lng,
        minutes: m,
        enabled: true,
        last: null
      });
      saveRules();
      renderRules();
      updateAlertRow();
      live.textContent = 'Alert set for route ' + s.route + ', under ' + m + ' min.';
      sel.focus();
    });
    var wrap = el('div');
    wrap.style.display = 'contents';
    wrap.appendChild(row);
    wrap.appendChild(live);
    return wrap;
  }
  function updateAlertRow() {
    var b = $('#addAlert'),
      sel = $('#alertMin'),
      s = state.stop;
    if (!b || !sel || !s) return;
    var dup = !!findRule(s.route, s.id, parseInt(sel.value, 10));
    b.disabled = dup;
    b.textContent = dup ? 'Alert set' : 'Add alert';
  }
  /* ----- Browser notifications: asked for only on a click, never automatically ----- */
  function renderNotify() {
    var box = $('#notifyBox');
    box.replaceChildren();
    if (!window.Notification) return;
    var p = Notification.permission;
    if (p === 'default') {
      var b = el('button', 'btn small', 'Turn on browser notifications');
      b.type = 'button';
      b.id = 'enableNotify';
      b.addEventListener('click', function () {
        var done = function () {
          renderNotify();
        };
        try {
          var r = Notification.requestPermission(done);
          if (r && typeof r.then === 'function') r.then(done, done);
        } catch (e) {
          done();
        }
      });
      box.appendChild(b);
      box.appendChild(
        el(
          'p',
          null,
          'Shows a notification when this page is open but in the background. It cannot reach you when the page is closed.'
        )
      );
    } else if (p === 'granted') {
      box.appendChild(el('p', null, 'Notifications on'));
    } else {
      box.appendChild(el('p', null, 'Notifications blocked in your browser settings'));
    }
  }
  S.alerts.loadAlerts = loadAlerts;
  S.alerts.renderAlerts = renderAlerts;
  S.alerts.hasActiveRule = hasActiveRule;
  S.alerts.evalRules = evalRules; /*@split*/
  S.alerts.renderRules = renderRules;
  S.alerts.alertRow = alertRow;
  S.alerts.updateAlertRow = updateAlertRow;
  S.alerts.renderNotify = renderNotify; /*@split*/
})(); /*@split*/
