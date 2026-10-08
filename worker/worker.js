// SEPTA proxy for Philly Transit Live. Forwards fixed SEPTA hackathon endpoints and adds CORS.
// Deployed as the Cloudflare Worker "septa-proxy" (https://septa-proxy.tpgordon8.workers.dev).
// This file is the source of truth. Deploy by pasting it into the Worker editor in the Cloudflare dashboard.
//
// Endpoints (GET):
//   /TransitView, /TrainView, /Alerts          whole-feed snapshots, no parameters
//   /Stops?route=<id>                          stops served by one route (id: 1-6 letters/digits), cached a day
//   /Arrivals?station=<name>                   Regional Rail departures for one station, cached 15 s
const ORIGINS = ['https://tpgordon8.github.io', 'null'];
const BASE = 'https://api.septa.org/hackathon/';
const ROUTE_RE = /^[A-Za-z0-9]{1,6}$/;
const STATION_RE = /^[A-Za-z0-9 .'&\/-]{2,40}$/;

// name -> { build(params) -> upstream URL or null when params are invalid, ttl seconds }
const ENDPOINTS = {
  TransitView: { build: () => BASE + 'TransitView/index.php', ttl: 10 },
  TrainView: { build: () => BASE + 'TrainView/index.php', ttl: 10 },
  Alerts: { build: () => BASE + 'Alerts/index.php', ttl: 60 },
  Stops: {
    build: (p) => {
      const r = p.get('route') || '';
      return ROUTE_RE.test(r) ? BASE + 'Stops/index.php?req1=' + encodeURIComponent(r) : null;
    },
    ttl: 86400,
  },
  Arrivals: {
    build: (p) => {
      const s = (p.get('station') || '').trim();
      return STATION_RE.test(s) ? BASE + 'Arrivals/index.php?results=10&station=' + encodeURIComponent(s) : null;
    },
    ttl: 15,
  },
};

export default {
  async fetch(request) {
    const origin = request.headers.get('Origin') || '';
    const cors = {
      'Access-Control-Allow-Origin': ORIGINS.includes(origin) ? origin : ORIGINS[0],
      'Vary': 'Origin',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
    };
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });

    const url = new URL(request.url);
    const name = url.pathname.replace(/^\/+|\/+$/g, '');
    const ep = Object.prototype.hasOwnProperty.call(ENDPOINTS, name) ? ENDPOINTS[name] : null;
    if (!ep) return new Response('Not found', { status: 404, headers: cors });
    if (origin && !ORIGINS.includes(origin)) return new Response('Forbidden', { status: 403, headers: cors });

    const json = { ...cors, 'Content-Type': 'application/json' };
    const upstream = ep.build(url.searchParams);
    if (!upstream) return new Response('{"error":"bad parameter"}', { status: 400, headers: json });
    try {
      const res = await fetch(upstream, {
        cf: { cacheTtl: ep.ttl, cacheEverything: true },
        signal: AbortSignal.timeout(10000),
      });
      if (!res.ok) return new Response('{"error":"upstream ' + res.status + '"}', { status: 502, headers: json });
      return new Response(res.body, { status: 200, headers: { ...json, 'Cache-Control': 'public, max-age=' + Math.min(ep.ttl, 5) } });
    } catch (e) {
      return new Response('{"error":"upstream unreachable"}', { status: 502, headers: json });
    }
  },
};
