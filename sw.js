/* sw.js: Septer's service worker (ARCHITECTURE.md section 17). Classic worker, no build step, lives at the repo root so its scope is the whole site.
   What it does: keeps the app shell (page, styles, scripts, icons, Leaflet, the bus network file) so the app opens instantly and offline;
   keeps a small bounded cache of map tiles and fonts; and stays out of the way of everything live. Live feeds (the Cloudflare Worker, SEPTA),
   address suggestions (Photon), routing (OSRM) and Indego are never intercepted, so a rider never sees an old answer presented as current.
   The block between the STAMP markers is rewritten by tests/stamp_version.py. */
/* STAMP:begin */
var VERSION = '2da57719e1';
var SHELL = ["./", "css/leaflet.css?v=848adf372d", "css/base.css?v=848adf372d", "css/layout.css?v=848adf372d", "css/map.css?v=848adf372d", "css/panel.css?v=848adf372d", "css/trip.css?v=848adf372d", "css/suggest.css?v=848adf372d", "css/stops.css?v=848adf372d", "css/alerts.css?v=848adf372d", "css/nearby.css?v=848adf372d", "css/indego.css?v=848adf372d", "css/board.css?v=848adf372d", "css/install.css?v=848adf372d", "js/util.js?v=848adf372d", "js/feed.js?v=848adf372d", "js/map.js?v=848adf372d", "js/landmarks.js?v=848adf372d", "js/suggest.js?v=848adf372d", "js/panel.js?v=848adf372d", "js/stops.js?v=848adf372d", "js/alerts.js?v=848adf372d", "js/board.js?v=848adf372d", "js/boardbikes.js?v=848adf372d", "js/maplod.js?v=848adf372d", "js/routing.js?v=848adf372d", "js/candidates.js?v=848adf372d", "js/planner.js?v=848adf372d", "js/trip.js?v=848adf372d", "js/nearby.js?v=848adf372d", "js/boardview.js?v=848adf372d", "js/boardbikesview.js?v=848adf372d", "js/boardsettings.js?v=848adf372d", "js/boardadd.js?v=848adf372d", "js/sheet.js?v=848adf372d", "js/indego.js?v=848adf372d", "js/main.js?v=848adf372d", "js/install.js?v=848adf372d", "manifest.webmanifest", "icons/apple-touch-icon.png", "icons/favicon.svg", "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png", "icons/maskable.svg", "data/bus-network.json?v=848adf372d"];
var CROSS = ["https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"];
/* STAMP:end */
var SHELL_PREFIX = 'septer-shell-';
var SHELL_CACHE = SHELL_PREFIX + VERSION;
var RUNTIME_CACHE = 'septer-runtime-v1';
var RUNTIME_MAX = 240;
var SCOPE = self.registration.scope;
var ROOT = new URL('./', SCOPE).href;
var RUNTIME_HOSTS = ['tile.openstreetmap.org', 'a.tile.openstreetmap.org', 'b.tile.openstreetmap.org', 'c.tile.openstreetmap.org', 'fonts.googleapis.com', 'fonts.gstatic.com'];

var OFFLINE_HTML = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Septer is offline</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#eef1f4;color:#0f1c2c;font:18px/1.45 system-ui,sans-serif;text-align:center;padding:24px}h1{font-size:28px;margin:0 0 8px;color:#1f5fae}@media(prefers-color-scheme:dark){body{background:#0a1119;color:#e7eef6}h1{color:#5da4f3}}</style></head><body><main><h1>Septer is offline</h1><p>You are not connected, and the app has not been saved on this device yet. Connect once and Septer will open without a network after that.</p></main></body></html>';

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(SHELL_CACHE).then(function (cache) {
      /* Same-origin files are required: if one fails the install fails and the browser retries later, so a half shell is never active.
         cache: 'reload' skips the HTTP cache (GitHub Pages sends max-age=600) so the stored copy is the deployed one. */
      var need = SHELL.map(function (u) {
        return fetch(new Request(u, { cache: 'reload' })).then(function (r) {
          if (!r.ok) throw new Error('precache ' + u + ' ' + r.status);
          return cache.put(u, r);
        });
      });
      /* Third-party files (Leaflet on cdnjs) are best effort: offline start without them is not possible, but a CDN hiccup must not block the update. */
      var opt = CROSS.map(function (u) {
        return fetch(new Request(u, { mode: 'cors', credentials: 'omit' }))
          .then(function (r) {
            return r.ok ? cache.put(u, r) : null;
          })
          .catch(function () {});
      });
      return Promise.all(need.concat(opt));
    })
  );
  /* No skipWaiting here: a new worker waits until the page asks (message below) or every tab closes, so one visit never mixes old page code with new files. */
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (keys) {
        return Promise.all(
          keys
            .filter(function (k) {
              return k.indexOf(SHELL_PREFIX) === 0 && k !== SHELL_CACHE;
            })
            .map(function (k) {
              return caches.delete(k);
            })
        );
      })
      .then(function () {
        return self.clients.claim();
      })
  );
});

self.addEventListener('message', function (event) {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

function trim(cache) {
  return cache.keys().then(function (keys) {
    if (keys.length <= RUNTIME_MAX) return null;
    return Promise.all(
      keys.slice(0, keys.length - RUNTIME_MAX).map(function (k) {
        return cache.delete(k);
      })
    );
  });
}

function fromShell(request, opts) {
  return caches.open(SHELL_CACHE).then(function (c) {
    return c.match(request, opts);
  });
}

/* Shell files: answer from the cache at once, refresh the stored copy in the background (stale-while-revalidate). */
function shellFirst(event, request) {
  return fromShell(request).then(function (hit) {
    var net = fetch(request)
      .then(function (r) {
        if (r && r.ok) {
          var copy = r.clone();
          caches.open(SHELL_CACHE).then(function (c) {
            return c.put(request, copy);
          });
        }
        return r;
      })
      .catch(function () {
        return null;
      });
    if (hit) {
      event.waitUntil(net);
      return hit;
    }
    return net.then(function (r) {
      return r || Response.error();
    });
  });
}

function navigation(event, request) {
  var net = fetch(request)
    .then(function (r) {
      if (r && r.ok) {
        var copy = r.clone();
        caches.open(SHELL_CACHE).then(function (c) {
          return c.put(ROOT, copy);
        });
      }
      return r;
    })
    .catch(function () {
      return null;
    });
  return fromShell(ROOT, { ignoreSearch: true }).then(function (hit) {
    if (hit) {
      event.waitUntil(net);
      return hit;
    }
    return net.then(function (r) {
      return r || new Response(OFFLINE_HTML, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    });
  });
}

/* Tiles and fonts: cached copy first, refreshed in the background; the cache is capped so it cannot grow without limit. */
function runtime(event, request) {
  return caches.open(RUNTIME_CACHE).then(function (cache) {
    return cache.match(request).then(function (hit) {
      var net = fetch(request)
        .then(function (r) {
          if (r && (r.ok || r.type === 'opaque')) {
            cache.put(request, r.clone()).then(function () {
              return trim(cache);
            });
          }
          return r;
        })
        .catch(function () {
          return null;
        });
      if (hit) {
        event.waitUntil(net);
        return hit;
      }
      return net.then(function (r) {
        return r || Response.error();
      });
    });
  });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') return;
  var url = new URL(request.url);
  if (url.origin === self.location.origin) {
    if (url.href.indexOf(ROOT) !== 0) return;
    if (request.mode === 'navigate') {
      var rootPath = new URL(ROOT).pathname;
      if (url.pathname === rootPath || url.pathname === rootPath + 'index.html') event.respondWith(navigation(event, request));
      return;
    }
    if (/\/sw\.js$/.test(url.pathname)) return;
    event.respondWith(shellFirst(event, request));
    return;
  }
  if (CROSS.indexOf(request.url) >= 0) {
    event.respondWith(
      fromShell(request).then(function (hit) {
        return hit || fetch(request);
      })
    );
    return;
  }
  if (RUNTIME_HOSTS.indexOf(url.hostname) >= 0) {
    event.respondWith(runtime(event, request));
  }
  /* Everything else (the Worker, SEPTA, Photon, OSRM, Indego) is not touched: the browser goes straight to the network. */
});
