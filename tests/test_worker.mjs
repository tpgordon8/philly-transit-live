// Unit test for worker/worker.js with a mocked fetch. Run: node tests/test_worker.mjs
import assert from 'node:assert/strict';
import worker from '../worker/worker.js';
const calls = [];
globalThis.fetch = async (u, o) => { calls.push({ u, o }); return new Response('[]', { status: 200 }); };
const get = (path, origin = 'https://tpgordon8.github.io') =>
  worker.fetch(new Request('https://w.example' + path, { headers: origin ? { Origin: origin } : {} }));
let r;
r = await get('/TransitView'); assert.equal(r.status, 200); assert.equal(calls.at(-1).u, 'https://api.septa.org/hackathon/TransitView/index.php');
assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 10);
r = await get('/Alerts?x=1'); assert.equal(calls.at(-1).u, 'https://api.septa.org/hackathon/Alerts/index.php', 'query not forwarded');
r = await get('/Stops?route=21'); assert.equal(r.status, 200); assert.equal(calls.at(-1).u, 'https://api.septa.org/hackathon/Stops/index.php?req1=21'); assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 60, 'subrequest cache for Stops is the short, safe TTL');
const n = calls.length;
for (const bad of ['/Stops', '/Stops?route=', '/Stops?route=../x', '/Stops?route=1234567', '/Stops?route=21%26x=1', '/Arrivals', '/Arrivals?station=', '/Arrivals?station=a', '/Arrivals?station=' + 'x'.repeat(41), '/Arrivals?station=<script>']) {
  r = await get(bad); assert.equal(r.status, 400, bad);
}
assert.equal(calls.length, n, 'invalid params must not reach SEPTA');
r = await get('/Arrivals?station=Suburban%20Station'); assert.equal(r.status, 200);
assert.equal(calls.at(-1).u, 'https://api.septa.org/hackathon/Arrivals/index.php?results=10&station=Suburban%20Station');
assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 15);
r = await get('/Arrivals?station=30th%20Street%20Station'); assert.equal(r.status, 200);
r = await get('/nope'); assert.equal(r.status, 404);
r = await get('/constructor'); assert.equal(r.status, 404, 'prototype keys are not endpoints');
r = await get('/TransitView', 'https://evil.example'); assert.equal(r.status, 403);
r = await get('/TransitView', ''); assert.equal(r.status, 200, 'no Origin header at all (curl, smoke test) is allowed');
r = await get('/TransitView', 'null'); assert.equal(r.status, 403, "Origin 'null' is rejected"); assert.equal(r.headers.get('access-control-allow-origin'), 'https://tpgordon8.github.io');
r = await worker.fetch(new Request('https://w.example/Stops', { method: 'OPTIONS' })); assert.equal(r.status, 204);
globalThis.fetch = async () => new Response('x', { status: 500 }); r = await get('/Alerts'); assert.equal(r.status, 502);
globalThis.fetch = async () => { throw new Error('boom'); }; r = await get('/Alerts'); assert.equal(r.status, 502);

globalThis.fetch = async (u, o) => { calls.push({ u, o }); return new Response('[]', { status: 200 }); };
// ---- origins -------------------------------------------------------------------------------------------------
const raw = (path, headers) => worker.fetch(new Request('https://w.example' + path, { headers }));
r = await raw('/TransitView', { Origin: '' }); assert.equal(r.status, 403, 'present-but-empty Origin is rejected');
for (const ok of ['https://tpgordon8.github.io', 'https://septer.tarapaigegordon.com', 'http://localhost', 'http://localhost:8000', 'http://127.0.0.1:54321', 'http://127.0.0.1']) {
  r = await get('/TransitView', ok); assert.equal(r.status, 200, ok); assert.equal(r.headers.get('access-control-allow-origin'), ok, ok);
}
for (const bad of ['https://localhost', 'http://localhost.evil.example', 'http://localhost:80a', 'http://evil.example:3000', 'http://127.0.0.1.evil.example',
  'https://tpgordon8.github.io.evil.example', 'https://septer.tarapaigegordon.com.evil.example', 'http://septer.tarapaigegordon.com', 'https://tarapaigegordon.com', 'http://tpgordon8.github.io', 'http://localhost:1234/x', 'file://', 'HTTP://LOCALHOST']) {
  r = await get('/TransitView', bad); assert.equal(r.status, 403, bad);
}
r = await raw('/TransitView', { 'Sec-Fetch-Site': 'cross-site' }); assert.equal(r.status, 403, 'browser cross-site request without Origin');
r = await raw('/TransitView', { 'Sec-Fetch-Site': 'same-site' }); assert.equal(r.status, 403);
r = await raw('/TransitView', { 'Sec-Fetch-Site': 'none' }); assert.equal(r.status, 200, 'address-bar navigation');
r = await get('/route/foot?from=39.95,-75.16&to=39.96,-75.17', 'null'); assert.equal(r.status, 403, 'new endpoints share the origin guard');
globalThis.fetch = async () => new Response('{"data":{"stations":[]}}', { status: 200 });
r = await get('/indego/status', ''); assert.equal(r.status, 403, '/indego needs an allowed Origin: no Origin is refused');
r = await raw('/indego/information', { 'Sec-Fetch-Site': 'same-origin' }); assert.equal(r.status, 403, 'no Origin, even with same-origin fetch metadata');
r = await get('/route/foot?from=39.95,-75.16&to=39.96,-75.17', ''); assert.equal(r.status, 403, '/route needs an allowed Origin: no Origin is refused');
r = await raw('/route/foot?from=39.95,-75.16&to=39.96,-75.17', { 'Sec-Fetch-Site': 'none' }); assert.equal(r.status, 403);
r = await raw('/indego/status', { Origin: '' }); assert.equal(r.status, 403);
r = await get('/indego/status', 'http://localhost:8000'); assert.equal(r.status, 200, 'allowed origins still work');

// ---- caches mock + helpers for the smart endpoints -----------------------------------------------------------
const store = new Map(); const puts = [];
globalThis.caches = { default: {
  async match(req) { const v = store.get(req.url); return v ? new Response(v.text, { headers: v.headers }) : undefined; },
  async put(req, res) { const text = await res.text(); const e = { text, headers: Object.fromEntries(res.headers) }; puts.push({ url: req.url, ...e }); store.set(req.url, e); },
} };
const mockUpstream = (status, body) => { calls.length = 0; globalThis.fetch = async (u, o) => { calls.push({ u, o }); return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status }); };
};
const OK_ROUTE = { code: 'Ok', routes: [{ distance: 10, duration: 5, geometry: { type: 'LineString', coordinates: [[-75.16, 39.95], [-75.17, 39.96]] } }] };
const OSRM = 'https://routing.openstreetmap.de/routed-';

// ---- /route validation ---------------------------------------------------------------------------------------
mockUpstream(200, OK_ROUTE);
r = await get('/route/foot?from=39.95,-75.16&to=39.96,-75.17');
assert.equal(r.status, 200); assert.deepEqual(await r.json(), OK_ROUTE);
assert.equal(calls.at(-1).u, OSRM + 'foot/route/v1/driving/-75.1600,39.9500;-75.1700,39.9600?overview=full&geometries=geojson', 'lng,lat order, 4 dp');
assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 60, 'route is edge-cached 60 s');
assert.equal(calls.at(-1).o.headers['User-Agent'], 'philly-transit-live (+https://tpgordon8.github.io/philly-transit-live/)', 'OSRM is told who we are');
assert.ok(calls.at(-1).o.cf.cacheTtlByStatus['300-599'] < 0, 'upstream errors are not cached');
for (const prof of ['bike', 'car']) { r = await get(`/route/${prof}?from=39.95,-75.16&to=39.96,-75.17`); assert.equal(r.status, 200, prof); assert.ok(calls.at(-1).u.startsWith(OSRM + prof + '/'), prof); }
r = await get('/route/foot?from=39.949949,-75.160049&to=39.96,-75.17');
assert.ok(calls.at(-1).u.includes('/driving/-75.1600,39.9499;'), 'rounded to 4 dp: ' + calls.at(-1).u);
r = await get('/route/foot?from=39.95006,-75.16006&to=39.96,-75.17');
assert.ok(calls.at(-1).u.includes('/driving/-75.1601,39.9501;'), 'rounds half up on the 5th decimal: ' + calls.at(-1).u);
r = await get('/route/foot?from=40,-75&to=39.6,-75.9'); assert.equal(r.status, 200, 'box edges are inclusive');
assert.ok(calls.at(-1).u.includes('/driving/-75.0000,40.0000;-75.9000,39.6000?'), calls.at(-1).u);
const before = calls.length;
const badRoutes = [
  '/route/foot', '/route/foot?from=39.95,-75.16', '/route/foot?to=39.95,-75.16', '/route/foot?from=&to=',
  '/route/boat?from=39.95,-75.16&to=39.96,-75.17', '/route/?from=39.95,-75.16&to=39.96,-75.17', '/route/foot/x?from=39.95,-75.16&to=39.96,-75.17',
  '/route/foot?from=39.95;-75.16&to=39.96,-75.17', '/route/foot?from=39.95,-75.16,1&to=39.96,-75.17', '/route/foot?from=39.95&to=39.96,-75.17',
  '/route/foot?from=NaN,-75.16&to=39.96,-75.17', '/route/foot?from=Infinity,-75.16&to=39.96,-75.17', '/route/foot?from=-Infinity,-75.16&to=39.96,-75.17',
  '/route/foot?from=1e1,-75.16&to=39.96,-75.17', '/route/foot?from=0x28,-75.16&to=39.96,-75.17', '/route/foot?from=39.95,-75.16&to=abc,def',
  '/route/foot?from=%2039.95,-75.16&to=39.96,-75.17', '/route/foot?from=39.95,%20-75.16&to=39.96,-75.17', '/route/foot?from=39.95,-75.16&to=39.96,',
  '/route/foot?from=39.5999,-75.16&to=39.96,-75.17', '/route/foot?from=40.4001,-75.16&to=39.96,-75.17', '/route/foot?from=39.95,-75.9001&to=39.96,-75.17',
  '/route/foot?from=39.95,-74.4999&to=39.96,-75.17', '/route/foot?from=0,0&to=39.96,-75.17', '/route/foot?from=39.95,-75.16&to=48.85,2.35',
  '/route/foot?from=39.95,-75.16&to=39.96,-75.17&from=39.97,-75.18', '/route/foot?from=39.95,-75.16&from=39.96,-75.17&to=39.96,-75.17',
  '/route/foot?from=39.95,-75.16&to=39.96,-75.17%26x=1;DROP', '/route/foot?from=39.95,-75.16&to=' + '9'.repeat(40) + ',-75',
  '/route/foot?from=-39.95,75.16&to=39.96,-75.17',
];
for (const bad of badRoutes) { r = await get(bad); assert.equal(r.status, 400 + (bad.includes('/route/boat') || bad === '/route/?from=39.95,-75.16&to=39.96,-75.17' || bad.includes('/foot/x') ? 4 : 0), bad); }
assert.equal(calls.length, before, 'invalid route requests never reach the routing service');

// ---- /route errors and caching ---------------------------------------------------------------------------------
store.clear(); puts.length = 0;
mockUpstream(429, 'slow down'); r = await get('/route/foot?from=39.95,-75.16&to=39.96,-75.17'); assert.equal(r.status, 502);
const R1 = '/route/foot?from=39.95,-75.16&to=39.96,-75.17';
// OSRM answers HTTP 400 with a JSON error code for every error: that is an answer, not an outage.
for (const code of ['NoRoute', 'NoSegment', 'InvalidQuery', 'TooBig']) {
  mockUpstream(400, { code, message: 'x' }); r = await get(R1);
  assert.equal(r.status, 422, code + ' passes through as 422'); assert.equal((await r.json()).code, code);
  assert.equal(r.headers.get('cache-control'), 'no-store', code + ' answers are never cached');
  assert.equal(r.headers.get('access-control-allow-origin'), 'https://tpgordon8.github.io');
}
mockUpstream(200, { code: 'NoRoute', routes: [] }); r = await get(R1); assert.equal(r.status, 422, '200 with an error code is the same answer'); assert.equal((await r.json()).code, 'NoRoute');
mockUpstream(400, { code: 'NoRoute', message: 'm'.repeat(500) }); r = await get(R1); assert.ok((await r.json()).message.length <= 200, 'message is bounded');
// real outages stay 502: non-JSON, JSON without an error code, 404, 408, 429, 5xx, "Ok" in an error status
mockUpstream(400, '<html>bad</html>'); r = await get(R1); assert.equal(r.status, 502, 'non-JSON 400');
mockUpstream(400, { message: 'no code' }); r = await get(R1); assert.equal(r.status, 502, 'no code');
mockUpstream(400, { code: 'Ok', routes: [] }); r = await get(R1); assert.equal(r.status, 502, 'an Ok code in an error status is not an answer');
mockUpstream(400, { code: 'No Route!' }); r = await get(R1); assert.equal(r.status, 502, 'odd code text is not passed through');
for (const st of [404, 408, 429, 500, 503]) { mockUpstream(st, { code: 'NoRoute' }); r = await get(R1); assert.equal(r.status, 502, 'upstream ' + st + ' is an outage even with an error body'); }
mockUpstream(200, 'not json'); r = await get(R1); assert.equal(r.status, 502);
mockUpstream(200, { code: 'Ok', routes: [] }); r = await get(R1); assert.equal(r.status, 502, 'Ok without a route is not an answer');
globalThis.fetch = async () => { throw new Error('boom'); }; r = await get('/route/foot?from=39.95,-75.16&to=39.96,-75.17'); assert.equal(r.status, 502);
assert.equal(puts.length, 0, 'nothing from these failures reached the cache');

// ---- /indego ---------------------------------------------------------------------------------------------------
const FEED = { last_updated: 1, ttl: 60, data: { stations: [{ station_id: '1' }] } };
mockUpstream(200, FEED);
r = await get('/indego/information'); assert.equal(r.status, 200); assert.deepEqual(await r.json(), FEED);
assert.equal(calls.at(-1).u, 'https://gbfs.bcycle.com/bcycle_indego/station_information.json');
assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 3600, 'information is cached an hour');
assert.ok(calls.at(-1).o.cf.cacheTtlByStatus['300-599'] < 0);
r = await get('/indego/status?x=1&from=evil'); assert.equal(r.status, 200);
assert.equal(calls.at(-1).u, 'https://gbfs.bcycle.com/bcycle_indego/station_status.json', 'query is not forwarded');
assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 30, 'status is cached 30 s');
for (const p of ['/indego', '/indego/', '/indego/other', '/indego/status/x', '/indego/__proto__']) { r = await get(p); assert.equal(r.status, 404, p); }
mockUpstream(503, 'down'); r = await get('/indego/status'); assert.equal(r.status, 502);
mockUpstream(200, { data: {} }); r = await get('/indego/status'); assert.equal(r.status, 502, 'not a station feed');
mockUpstream(200, 'html'); r = await get('/indego/information'); assert.equal(r.status, 502);
globalThis.fetch = async () => { throw new Error('boom'); }; r = await get('/indego/information'); assert.equal(r.status, 502);
assert.equal(puts.length, 0);

// ---- Stops: empty or non-array answers live 60 s, real lists a day -------------------------------------------
store.clear(); puts.length = 0;
mockUpstream(200, [{ stopid: '1' }]); r = await get('/Stops?route=21'); assert.equal(r.status, 200);
assert.equal(puts.length, 1); assert.match(puts[0].headers['cache-control'], /max-age=86400/, 'non-empty list: a day');
const nCalls = calls.length; r = await get('/Stops?route=21'); assert.equal(calls.length, nCalls, 'second call served from cache'); assert.equal((await r.json())[0].stopid, '1');
for (const [route, body] of [['22', []], ['23', {}], ['24', { error: 'x' }], ['25', 'garbage'], ['26', 'null']]) {
  puts.length = 0; mockUpstream(200, body); r = await get('/Stops?route=' + route); assert.equal(r.status, 200, route);
  assert.equal(puts.length, 1, route); assert.match(puts[0].headers['cache-control'], /max-age=60$/, route + ' cached 60 s only');
  assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 60, route);
}
puts.length = 0; mockUpstream(500, 'x'); r = await get('/Stops?route=27'); assert.equal(r.status, 502); assert.equal(puts.length, 0, 'upstream error not cached');
globalThis.fetch = async () => { throw new Error('boom'); }; r = await get('/Stops?route=28'); assert.equal(r.status, 502); assert.equal(puts.length, 0);
delete globalThis.caches; mockUpstream(200, [{ stopid: '1' }]); r = await get('/Stops?route=29'); assert.equal(r.status, 200, 'works when the Cache API is absent');

// ---- other endpoints keep their behaviour ----------------------------------------------------------------------
mockUpstream(200, []);
r = await get('/TransitView'); assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 10); assert.equal(calls.at(-1).o.cf.cacheEverything, true);
r = await get('/Alerts'); assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 60);
r = await get('/Arrivals?station=Suburban%20Station'); assert.equal(calls.at(-1).o.cf.cacheTtlByStatus['200-299'], 15);
for (const name of ['/TransitView', '/TrainView', '/Alerts', '/Arrivals?station=Suburban%20Station']) {
  r = await get(name); assert.equal(calls.at(-1).o.cf.cacheTtl, undefined, name + ': a flat cacheTtl would cache error pages');
  assert.ok(calls.at(-1).o.cf.cacheTtlByStatus['300-599'] < 0, name + ': upstream errors are not cached');
  assert.ok(calls.at(-1).o.cf.cacheTtlByStatus['200-299'] > 0, name);
}

console.log('worker tests passed');
