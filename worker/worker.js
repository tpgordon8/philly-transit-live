// SEPTA proxy for Philly Transit Live. Forwards three fixed SEPTA hackathon endpoints and adds CORS.
// Deployed as the Cloudflare Worker "septa-proxy" (https://septa-proxy.tpgordon8.workers.dev).
// This file is the source of truth. Deploy by pasting it into the Worker editor in the Cloudflare dashboard.
const ORIGINS = ['https://tpgordon8.github.io', 'null'];
const UPSTREAM = {
  TransitView: 'https://api.septa.org/hackathon/TransitView/index.php',
  TrainView: 'https://api.septa.org/hackathon/TrainView/index.php',
  Alerts: 'https://api.septa.org/hackathon/Alerts/index.php',
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

    const name = new URL(request.url).pathname.replace(/^\/+|\/+$/g, '');
    if (!UPSTREAM[name]) return new Response('Not found', { status: 404, headers: cors });
    if (origin && !ORIGINS.includes(origin)) return new Response('Forbidden', { status: 403, headers: cors });

    const json = { ...cors, 'Content-Type': 'application/json' };
    try {
      const res = await fetch(UPSTREAM[name], {
        cf: { cacheTtl: name === 'Alerts' ? 60 : 10, cacheEverything: true },
        signal: AbortSignal.timeout(10000),
      });
      if (!res.ok) return new Response('{"error":"upstream ' + res.status + '"}', { status: 502, headers: json });
      return new Response(res.body, { status: 200, headers: { ...json, 'Cache-Control': 'public, max-age=5' } });
    } catch (e) {
      return new Response('{"error":"upstream unreachable"}', { status: 502, headers: json });
    }
  },
};
