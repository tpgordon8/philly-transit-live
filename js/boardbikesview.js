/* js/boardbikesview.js: the "Bikes" section of the wall board, one tile per picked Indego station (ARCHITECTURE.md 16.1).
   js/boardview.js calls render(list) after it has drawn the bus rows; the numbers come from S.boardbikes.rows(). Needs js/boardview.js. */
(function () {
  'use strict';
  var S = window.SEPTA;
  if (S.halt || typeof document === 'undefined') return;
  var util = S.util,
    $ = util.$,
    el = util.el;
  var sec = null,
    tiles = null,
    els = {};
  function plural(n, one, many) {
    return n + ' ' + (n === 1 ? one : many);
  }
  function spoken(name) {
    return String(name).replace(/\s*&\s*/g, ' and ');
  }
  /* What a tile shows. view: ok | noebike | nobike | closed | unknown | down | loading. age: whole minutes, or null for none. */
  function facts(r, view, age) {
    var bb = S.boardbikes,
      f = { big: '', unit: '', word: '', bikes: '', docks: '', age: '', say: '' };
    if (view === 'ok' && !r.typed) {
      /* the feed gave a total but no split by type: show the total and say so, never "No e-bikes" */
      f.big = String(r.bikes);
      f.unit = r.bikes === 1 ? 'BIKE' : 'BIKES';
      f.bikes = 'Type not reported';
      f.say = plural(r.bikes, 'bike', 'bikes') + ', type not reported';
    } else if (view === 'ok' || view === 'noebike' || view === 'nobike') {
      f.big = String(r.electric);
      f.unit = r.electric === 1 ? 'E-BIKE' : 'E-BIKES';
      f.bikes =
        view === 'ok'
          ? r.classic + ' classic'
          : view === 'nobike'
            ? 'No bikes'
            : 'No e-bikes, ' + r.classic + ' classic';
      f.say =
        view === 'ok'
          ? plural(r.electric, 'e-bike', 'e-bikes') + ', ' + r.classic + ' classic'
          : view === 'nobike'
            ? 'no bikes'
            : 'no e-bikes, ' + r.classic + ' classic';
    } else if (view === 'closed') {
      f.word = 'Not renting';
      f.say = 'not renting';
    } else {
      f.word = view === 'down' ? 'Unavailable' : view === 'loading' ? 'Loading' : 'No data';
      f.say =
        view === 'down'
          ? 'bike data unavailable'
          : view === 'loading'
            ? 'loading'
            : 'no data for this station';
      return f;
    }
    f.docks = r.returning ? plural(r.docks, 'open dock', 'open docks') : 'Docks closed';
    f.say += ', ' + f.docks.toLowerCase();
    if (age != null) {
      f.age = 'as of ' + bb.ageText(age, true);
      f.say += ', as of ' + bb.ageText(age, false);
    }
    return f;
  }
  function fillTile(li, r, src) {
    var view = src === 'down' ? 'down' : src === 'loading' ? 'loading' : r.state,
      age = view === 'down' || view === 'loading' || view === 'unknown' ? null : r.ageMin,
      f = facts(r, view, age);
    var sig = [r.name, view, f.big, f.unit, f.word, f.bikes, f.docks, f.age, f.say].join('|');
    if (li.dataset.sig === sig) return;
    li.dataset.sig = sig;
    li.dataset.state = view;
    li.setAttribute('aria-label', 'Indego ' + spoken(r.name) + ', ' + f.say);
    li.replaceChildren();
    li.appendChild(el('div', 'bv-tn', r.name));
    var m = el('div', 'bv-tm');
    if (f.word) m.appendChild(el('span', 'bv-tw', f.word));
    else {
      m.appendChild(el('span', 'bv-tv', f.big));
      m.appendChild(el('span', 'bv-tk', f.unit));
    }
    li.appendChild(m);
    var d = el('div', 'bv-td');
    if (f.bikes) d.appendChild(el('span', null, f.bikes));
    if (f.docks) d.appendChild(el('span', null, f.docks));
    if (f.age) d.appendChild(el('span', 'bv-ta', f.age));
    li.appendChild(d);
  }
  function setBanner(node, msg) {
    node.hidden = !msg;
    node.classList.toggle('down', msg === 'Bike data unavailable');
    if (node.textContent !== msg) node.textContent = msg;
  }
  function render(list) {
    var bb = S.boardbikes,
      banner = $('#bvBikeBanner'),
      fine = $('#bvFineBikes'),
      picked = bb && typeof bb.stations === 'function' ? bb.stations() : [];
    $('#boardView').classList.toggle('has-bikes', picked.length > 0);
    if (!picked.length) {
      if (sec && sec.parentNode) sec.remove();
      els = {};
      if (banner) setBanner(banner, '');
      if (fine) fine.hidden = true;
      return;
    }
    if (!sec) {
      sec = el('li', 'bv-bikes');
      sec.appendChild(el('h3', 'bv-sec', 'Bikes'));
      tiles = el('ul', 'bv-tiles');
      tiles.setAttribute('aria-label', 'Indego bike stations');
      sec.appendChild(tiles);
    }
    if (list.lastChild !== sec) list.appendChild(sec);
    var now = Date.now(),
      src = bb.source(now),
      rows = bb.rows(now),
      ids = {};
    if (banner)
      setBanner(
        banner,
        src === 'down'
          ? 'Bike data unavailable'
          : src === 'stale'
            ? bb.refreshFailed()
              ? 'Bike data may be out of date'
              : 'Bike data is ' + bb.feedAgeMin(now) + ' min old'
            : ''
      );
    if (fine) fine.hidden = false;
    rows.forEach(function (r, i) {
      ids[r.id] = 1;
      var li = els[r.id];
      if (!li) li = els[r.id] = el('li', 'bv-tile');
      fillTile(li, r, src);
      if (tiles.children[i] !== li) tiles.insertBefore(li, tiles.children[i] || null);
    });
    Object.keys(els).forEach(function (id) {
      if (ids[id]) return;
      if (els[id].parentNode) els[id].remove();
      delete els[id];
    });
  }
  if (S.boardbikes && S.boardbikes.onChange)
    S.boardbikes.onChange(function () {
      if (S.boardview && S.boardview.isOpen && S.boardview.isOpen()) S.boardview.render();
    });
  S.boardbikesview.render = render;
})();
