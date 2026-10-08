// Unit test for worker/worker.js with a mocked fetch. Run: node tests/test_worker.mjs
import assert from 'node:assert/strict';
import worker from '../worker/worker.js';
const calls = [];
globalThis.fetch = async (u, o) => { calls.push({ u, o }); return new Response('[]', { status: 200 }); };
const get = (path, origin = 'https://tpgordon8.github.io') =>
  worker.fetch(new Request('https://w.example' + path, { headers: origin ? { Origin: origin } : {} }));
let r;
r = await get('/TransitView'); assert.equal(r.status, 200); assert.equal(calls.at(-1).u, 'https://api.septa.org/hackathon/TransitView/index.php');
assert.equal(calls.at(-1).o.cf.cacheTtl, 10);
r = await get('/Alerts?x=1'); assert.equal(calls.at(-1).u, 'https://api.septa.org/hackathon/Alerts/index.php', 'query not forwarded');
r = await get('/Stops?route=21'); assert.equal(r.status, 200); assert.equal(calls.at(-1).u, 'https://api.septa.org/hackathon/Stops/index.php?req1=21'); assert.equal(calls.at(-1).o.cf.cacheTtl, 86400);
const n = calls.length;
for (const bad of ['/Stops', '/Stops?route=', '/Stops?route=../x', '/Stops?route=1234567', '/Stops?route=21%26x=1', '/Arrivals', '/Arrivals?station=', '/Arrivals?station=a', '/Arrivals?station=' + 'x'.repeat(41), '/Arrivals?station=<script>']) {
  r = await get(bad); assert.equal(r.status, 400, bad);
}
assert.equal(calls.length, n, 'invalid params must not reach SEPTA');
r = await get('/Arrivals?station=Suburban%20Station'); assert.equal(r.status, 200);
assert.equal(calls.at(-1).u, 'https://api.septa.org/hackathon/Arrivals/index.php?results=10&station=Suburban%20Station');
assert.equal(calls.at(-1).o.cf.cacheTtl, 15);
r = await get('/Arrivals?station=30th%20Street%20Station'); assert.equal(r.status, 200);
r = await get('/nope'); assert.equal(r.status, 404);
r = await get('/constructor'); assert.equal(r.status, 404, 'prototype keys are not endpoints');
r = await get('/TransitView', 'https://evil.example'); assert.equal(r.status, 403);
r = await get('/TransitView', ''); assert.equal(r.status, 200);
r = await get('/TransitView', 'null'); assert.equal(r.status, 200); assert.equal(r.headers.get('access-control-allow-origin'), 'null');
r = await worker.fetch(new Request('https://w.example/Stops', { method: 'OPTIONS' })); assert.equal(r.status, 204);
globalThis.fetch = async () => new Response('x', { status: 500 }); r = await get('/Alerts'); assert.equal(r.status, 502);
globalThis.fetch = async () => { throw new Error('boom'); }; r = await get('/Alerts'); assert.equal(r.status, 502);
console.log('worker tests passed');
