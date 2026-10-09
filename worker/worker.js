// SEPTA proxy for Philly Transit Live. Forwards fixed SEPTA hackathon endpoints and adds CORS.
// Deployed as the Cloudflare Worker "septa-proxy" (https://septa-proxy.tpgordon8.workers.dev).
// This file is the source of truth. Deploy by pasting it into the Worker editor in the Cloudflare dashboard.
//
// Endpoints (GET):
//   /TransitView, /TrainView, /Alerts          whole-feed snapshots, no parameters
//   /Stops?route=<id>                          stops served by one route (id: 1-6 letters/digits), cached a day
//                                              (an empty or non-array answer is cached 60 s only)
//   /Arrivals?station=<name>                   Regional Rail departures for one station, cached 15 s
//   /route/<foot|bike|car>?from=lat,lng&to=lat,lng   OSRM route from the OpenStreetMap routing service, cached 60 s
//   /indego/information, /indego/status        Indego GBFS feeds, cached 1 hour / 30 s
// Trip coordinates are forwarded to the routing service (rounded to 4 decimals); nothing is stored by this Worker
// beyond the short-lived edge cache entry keyed by the rounded coordinates.
// /route and /indego answer only requests that carry an allowed Origin (403 otherwise, a missing Origin included): they
// spend a third party's capacity, so curl and cross-site browsers are refused. The other endpoints still accept no Origin.
// Answers on /route: 200 with the OSRM route; 422 with {"code":"NoRoute"|"NoSegment"|...} when the routing service gave a
// well-formed error answer (OSRM sends HTTP 400 for every error code; the page needs the code and must not retry
// elsewhere); 502 only when the service itself failed (unreachable, timeout, non-JSON, 5xx, 429). 422 is never cached.
// Origins: the Pages origin plus http://localhost and http://127.0.0.1 on any port. An Origin header that is present
// but not in that list (including 'null' and the empty string) gets 403. A request with no Origin header is allowed
// (curl, the smoke test) unless it carries browser Sec-Fetch headers showing a cross-site browser request.
const PAGES = 'https://tpgordon8.github.io';
const LOCAL_RE = /^http:\/\/(localhost|127\.0\.0\.1)(:\d{1,5})?$/;
const originAllowed = (o) => o === PAGES || LOCAL_RE.test(o);
const BASE = 'https://api.septa.org/hackathon/';
const ROUTE_RE = /^[A-Za-z0-9]{1,6}$/;
const STATION_RE = /^[A-Za-z0-9 .'&\/-]{2,40}$/;
const NUM_RE = /^-?\d{1,3}(\.\d{1,15})?$/;
const BBOX = { latMin: 39.6, latMax: 40.4, lngMin: -75.9, lngMax: -74.5 };
const ROUTE_BASE = 'https://routing.openstreetmap.de/routed-';
const INDEGO_BASE = 'https://gbfs.bcycle.com/bcycle_indego/';
const PROFILES = ['foot', 'bike', 'car'];
// The FOSSGIS routing service asks clients to identify themselves and to stay near one request per second.
const UA = 'philly-transit-live (+https://tpgordon8.github.io/philly-transit-live/)';

// "lat,lng" -> [lat, lng] rounded to 4 decimals, or null when malformed, non-finite or outside BBOX.
function parsePoint(v) {
  if (typeof v !== 'string') return null;
  const parts = v.split(',');
  if (parts.length !== 2 || !NUM_RE.test(parts[0]) || !NUM_RE.test(parts[1])) return null;
  const lat = Number(parts[0]);
  const lng = Number(parts[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (lat < BBOX.latMin || lat > BBOX.latMax || lng < BBOX.lngMin || lng > BBOX.lngMax) return null;
  return [lat.toFixed(4), lng.toFixed(4)];
}
const single = (p, k) => {
  const a = p.getAll(k);
  return a.length === 1 ? a[0] : null;
};
const isStationFeed = (d) => !!d && typeof d === 'object' && !!d.data && Array.isArray(d.data.stations);

// Endpoints validated here before the answer is served. ttl(data) returns the seconds the answer may live in the
// edge cache, or 0 to refuse it (answered 502, or 422 when passErr recognises a well-formed error answer).
// needOrigin: an allowed Origin header is required (403 without). ua: send the User-Agent above upstream. The subrequest is edge-cached for `fetchTtl` seconds on 2xx only
// (cacheTtlByStatus, a negative value means "do not cache"), so upstream HTTP errors are never cached.
// `longCache` (Stops only): the answer's real lifetime depends on its content, which the subrequest cache cannot see,
// so a vetted answer is also stored through the Cache API for ttl(data) seconds (a day for a non-empty list, 60 s
// otherwise) and served from there first. The Cache API is a functional cache only on custom domains; where it is
// a no-op (a *.workers.dev address) Stops are cached for the 60 s fetchTtl, which is always safe.
const SMART = {
  Stops: {
    build: (p) => {
      const r = p.get('route') || '';
      return ROUTE_RE.test(r) ? BASE + 'Stops/index.php?req1=' + encodeURIComponent(r) : null;
    },
    ttl: (d) => (Array.isArray(d) && d.length > 0 ? 86400 : 60),
    fetchTtl: 60,
    longCache: true
  },
  'indego/information': {
    build: () => INDEGO_BASE + 'station_information.json',
    ttl: (d) => (isStationFeed(d) ? 3600 : 0),
    fetchTtl: 3600,
    needOrigin: true
  },
  'indego/status': {
    build: () => INDEGO_BASE + 'station_status.json',
    ttl: (d) => (isStationFeed(d) ? 30 : 0),
    fetchTtl: 30,
    needOrigin: true
  }
};
// A well-formed OSRM error answer ({"code":"NoRoute","message":...}), or null. OSRM sends HTTP 400 for these; a 404 (unknown
// profile page), 408, 429 and 5xx are the service failing, not answering.
function osrmError(status, d) {
  if (
    status !== 200 &&
    !(status >= 400 && status < 500 && status !== 404 && status !== 408 && status !== 429)
  )
    return null;
  if (
    !d ||
    typeof d !== 'object' ||
    typeof d.code !== 'string' ||
    d.code === 'Ok' ||
    !/^[A-Za-z]{1,32}$/.test(d.code)
  )
    return null;
  const out = { code: d.code };
  if (typeof d.message === 'string') out.message = d.message.slice(0, 200);
  return out;
}
for (const prof of PROFILES) {
  SMART['route/' + prof] = {
    build: (p) => {
      const a = parsePoint(single(p, 'from'));
      const b = parsePoint(single(p, 'to'));
      if (!a || !b) return null;
      return (
        ROUTE_BASE +
        prof +
        '/route/v1/driving/' +
        a[1] +
        ',' +
        a[0] +
        ';' +
        b[1] +
        ',' +
        b[0] +
        '?overview=full&geometries=geojson'
      );
    },
    ttl: (d) => (d && d.code === 'Ok' && Array.isArray(d.routes) && d.routes.length > 0 ? 60 : 0),
    passErr: osrmError,
    fetchTtl: 60,
    needOrigin: true,
    ua: true
  };
}

// name -> { build(params) -> upstream URL or null when params are invalid, ttl seconds }
const ENDPOINTS = {
  TransitView: { build: () => BASE + 'TransitView/index.php', ttl: 10 },
  TrainView: { build: () => BASE + 'TrainView/index.php', ttl: 10 },
  Alerts: { build: () => BASE + 'Alerts/index.php', ttl: 60 },
  Arrivals: {
    build: (p) => {
      const s = (p.get('station') || '').trim();
      return STATION_RE.test(s)
        ? BASE + 'Arrivals/index.php?results=10&station=' + encodeURIComponent(s)
        : null;
    },
    ttl: 15
  }
};

const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

// Browser-style request without an Origin header: only cross-site/same-site Sec-Fetch-Site values are refused.
function browserCrossSite(request) {
  const sfs = request.headers.get('Sec-Fetch-Site');
  return sfs !== null && sfs !== 'same-origin' && sfs !== 'none';
}

async function smart(ep, upstream, json) {
  const cache = ep.longCache && typeof caches !== 'undefined' && caches.default ? caches.default : null;
  const key = new Request(upstream, { method: 'GET' });
  const out = (body) =>
    new Response(body, { status: 200, headers: { ...json, 'Cache-Control': 'public, max-age=5' } });
  try {
    const hit = cache ? await cache.match(key) : null;
    if (hit) return out(await hit.text());
  } catch (e) {
    /* a cache read failure just means a miss */
  }
  try {
    const res = await fetch(upstream, {
      cf: { cacheEverything: true, cacheTtlByStatus: { '200-299': ep.fetchTtl, '300-599': -1 } },
      signal: AbortSignal.timeout(10000),
      ...(ep.ua ? { headers: { 'User-Agent': UA } } : {})
    });
    const text = await res.text();
    let data = null;
    try {
      data = JSON.parse(text);
    } catch (e) {
      /* data stays null */
    }
    const ttl = res.ok ? ep.ttl(data) : 0;
    if (!ttl) {
      const pe = ep.passErr ? ep.passErr(res.status, data) : null;
      if (pe)
        return new Response(JSON.stringify(pe), {
          status: 422,
          headers: { ...json, 'Cache-Control': 'no-store' }
        });
      const why = res.ok ? 'bad answer' : String(res.status);
      return new Response('{"error":"upstream ' + why + '"}', { status: 502, headers: json });
    }
    if (cache) {
      try {
        await cache.put(
          key,
          new Response(text, {
            status: 200,
            headers: { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=' + ttl }
          })
        );
      } catch (e) {
        /* not cached; still served */
      }
    }
    return out(text);
  } catch (e) {
    return new Response('{"error":"upstream unreachable"}', { status: 502, headers: json });
  }
}

export default {
  async fetch(request) {
    const origin = request.headers.get('Origin');
    const o = origin === null ? '' : origin;
    const cors = {
      'Access-Control-Allow-Origin': originAllowed(o) ? o : PAGES,
      Vary: 'Origin',
      'Access-Control-Allow-Methods': 'GET, OPTIONS'
    };
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });

    const url = new URL(request.url);
    const name = url.pathname.replace(/^\/+|\/+$/g, '');
    const ep = has(ENDPOINTS, name) ? ENDPOINTS[name] : null;
    const sm = has(SMART, name) ? SMART[name] : null;
    if (!ep && !sm) return new Response('Not found', { status: 404, headers: cors });
    if (
      sm && sm.needOrigin
        ? origin === null || !originAllowed(origin)
        : origin !== null
          ? !originAllowed(origin)
          : browserCrossSite(request)
    ) {
      return new Response('Forbidden', { status: 403, headers: cors });
    }

    const json = { ...cors, 'Content-Type': 'application/json' };
    const upstream = (ep || sm).build(url.searchParams);
    if (!upstream) return new Response('{"error":"bad parameter"}', { status: 400, headers: json });
    if (sm) return smart(sm, upstream, json);
    try {
      const res = await fetch(upstream, {
        cf: { cacheEverything: true, cacheTtlByStatus: { '200-299': ep.ttl, '300-599': -1 } },
        signal: AbortSignal.timeout(10000)
      });
      if (!res.ok)
        return new Response('{"error":"upstream ' + res.status + '"}', { status: 502, headers: json });
      return new Response(res.body, {
        status: 200,
        headers: { ...json, 'Cache-Control': 'public, max-age=' + Math.min(ep.ttl, 5) }
      });
    } catch (e) {
      return new Response('{"error":"upstream unreachable"}', { status: 502, headers: json });
    }
  }
};
