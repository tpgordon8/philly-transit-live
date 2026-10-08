# Philly Transit Live — architecture

Status: Phase 0 audit, approved by the architect. Source of truth is this repo; `index.html` is canonical.
Copies of the app outside the repo (for example a published artifact) are stale and may not work.

## 1. Data flow

```
Browser (GitHub Pages, static index.html)
   │  GET https://septa-proxy.tpgordon8.workers.dev/<TransitView|TrainView|Alerts>
   ▼
Cloudflare Worker "septa-proxy"  (worker/worker.js)
   │  GET https://api.septa.org/hackathon/<Name>/index.php
   ▼
SEPTA public hackathon API (no key, no CORS headers)
```

- Stop links: when a rider opens a bus's next stop, the page fetches `<WORKER>/Stops?route=<id>` (same 15 s timeout and
  single retry as the other calls; the list is cached per route in memory, and a failed fetch is dropped from the cache
  so a retry works). The request carries only the route id. The URL hash `#stop=<id>&route=<route>` is the only state in
  a shared link (no coordinates, no center, no places); it is parsed on load and on `hashchange`, and a stop link moves
  the radius center for the session without writing it to `septa.prefs.v1`.

- Stop board ETA method: the stop card lists buses and trolleys on the stop's route. SEPTA gives no bus predictions, so a
  number appears only when it is computed from measured data. Each successful TransitView refresh appends a
  `{ts,lat,lng}` sample per vehicle (only when the GPS timestamp is new; last 120 s of feed time, at most 6 samples;
  vehicles that leave the feed are deleted, so memory is bounded). Speed is the distance between the oldest and newest
  sample divided by their time apart, and needs at least 20 s of span. Under 0.9 m/s counts as not moving; above 20 m/s
  (or a single step that implies it) is treated as a GPS jump and discarded. Only the bus whose `next_stop_id` is the
  stop gets an ETA: straight-line distance **plus 15 %** (roads are not straight) divided by speed, rounded up to whole
  minutes, never below 1 min. Unknown speed shows "—" with "measuring speed"; a stopped bus shows "not moving". Buses
  within 1.5 mi and heading within 60° of the stop are listed as "Heading toward this stop" with distance only. The card
  always says these are estimates, not SEPTA predictions. No new network calls and no new localStorage keys: the board
  is rebuilt from in-memory data on every refresh, and nothing about the viewer is stored or sent.
  Rough estimate: a bus that is not yet bound for this stop but is within 1.5 mi, heading within 45° of the stop, with
  its own next stop known and a measured speed above zero gets "~N min" in muted italics, labelled "rough: not its next
  stop yet". It uses the same padded straight-line formula and is an unverified estimate: the bus may turn, stop at
  its own next stop first, or never reach this stop. Buses 45–60° off stay listed with "—".
- The page never calls SEPTA directly. `api.septa.org` and `www3.septa.org` send no CORS headers, and the free
  public CORS proxies are dead (corsproxy.io wants a key; allorigins and codetabs time out).
- Third-party calls that remain: OpenStreetMap tiles, Google Fonts, cdnjs (Leaflet 1.9.4), and Nominatim for
  address search. Nominatim receives the address the user types. Nothing else leaves the browser.
- Deviation from the plan text: the page calls `TransitView` with **no `?route=`**, which returns every active
  vehicle in one response (about 290 KB). One Worker request per refresh is cheaper against the daily budget than
  one request per route, so the plan's "batch route requests" goal is met by design.

## 2. The Worker

- Allowlist: `TransitView`, `TrainView`, `Alerts` (no parameters; the query string is ignored), plus `Stops?route=<id>`
  (id matches `^[A-Za-z0-9]{1,6}$`, edge-cached a day) and `Arrivals?station=<name>` (name matches
  `^[A-Za-z0-9 .'&/-]{2,40}$`, upstream `results=10`, cached 15 s). Bad parameters get 400 without reaching SEPTA.
  Anything else is a 404. Unit test: `node tests/test_worker.mjs`.
- CORS: allows `https://tpgordon8.github.io` and `null` (a locally opened file). A browser sending any other
  `Origin` gets 403. This is a soft guard, since non-browser clients can spoof `Origin`; the data is public anyway.
- Caching: Cloudflare edge cache with `cacheTtl` 10 s (Alerts 60 s). Responses carry `Cache-Control: public,
  max-age=5`; the page fetches with `cache: 'no-store'`. Upstream timeout is 10 s; failures return 502 JSON.
- Deploy: no CLI or API token is available. Paste `worker/worker.js` into the Cloudflare dashboard editor
  (Workers & Pages, septa-proxy, Edit code) and click Deploy.
- **Budget (free plan: 100,000 Worker requests/day).** Edge-cache hits still invoke the Worker, so each open page
  costs 2 requests per 15 s = at most 11,520/day. About eight pages left open for 24 hours would reach the cap.
  Hidden tabs skip refresh, which lowers real usage. Alerts are fetched every 5 minutes (288/day per page).

## 3. Ghost-bus filter (`normBuses` in `index.html`)

A bus is kept only if all of these hold:

1. `timestamp` is greater than 0, and within 150 s of the **newest timestamp in the same feed** (not the device
   clock, so a wrong phone clock cannot hide or admit vehicles).
2. `VehicleID` and `label` are non-empty and not `"None"`. Empty-ID records carry the feed's own timestamp, so
   freshness alone lets them through; this rule drops them.
3. `lat`/`lng` parse and are non-zero.

`late` handling: `late: 998` records (schedule-only trips) are **dropped**. Other values of 900 or more (`999` = no delay
data) are kept and shown as "Delay data unavailable".

Trains (`normTrains`): `TrainView` has no timestamps, so there is no freshness rule. Coordinates must parse and be
non-zero. The train detail card says positions have no timestamp. Headings may be null (gray "?" badge).

## 4. Markers and the map

- Leaflet map created once. `markerZoomAnimation: false`; the map is never remounted.
- One `L.marker` per vehicle key (`b<VehicleID>` for buses and trolleys, `t<trainno>` for rail), kept in a `Map`.
  Duplicate keys in the feed collapse to one marker. Each refresh diffs: new keys are added, existing keys get
  `setLatLng`, missing keys are removed.
- `divIcon` `.veh-wrap` (80×44, anchor at center) holds an SVG body (bus, trolley with pole, or train),
  a `.rt` route/train-number badge and a `.dr` cardinal badge (N…NW from heading, gray "?" when null).
- Glide: CSS `transition: transform 1.6s` on `.veh-wrap`. The map container gets `.noglide` during zoom so
  markers do not drag across the screen when Leaflet repositions them.
- Gotcha: Leaflet gives map-pane SVGs `z-index: 200`, so the bus drawing sets `z-index: 0` and the badges `1`.
- Colors: buses blue, trolleys green, rail orange; all tokens are redefined for dark mode.

## 5. Refresh loop and failure states

- `setInterval` every 15 s, skipped while `document.hidden`; a visibility change triggers a refresh if the last
  one is older than 15 s. Each refresh fetches `TransitView` and `TrainView` in parallel; each source keeps
  `{list, ok, stale, err}`.
- The fetch layer retries once after 1.5 s. If both attempts fail the source is marked stale: its markers dim and
  a warning banner says so. After 120 s without a good update the source is dropped entirely. If no source has
  ever loaded, the banner reads "Live data unavailable" and nothing is drawn. Positions are never invented,
  interpolated as fact, or kept past 120 s.
- Alerts load at boot and every 5 minutes. Alert HTML is converted to plain text with `DOMParser`
  (`textContent`) and rendered with `textContent`, never `innerHTML`.

## 6. localStorage schema (the only place personal state lives)

| Key | Shape |
|---|---|
| `septa.prefs.v1` | `{ center: {lat, lng, label}, radius: 0.25–5, filters: {bus, trolley, train} }` |
| `septa.places.v1` | `{ home: {name, lat, lng} \| null, list: [{id, name, lat, lng}] }` |
| `septa.routes.v1` | `{ stars: [string], onlyMine: boolean }` — default `{stars: [], onlyMine: true}` |

**My routes.** Star keys: the route id string for buses and trolleys, `train:` + line name for Regional Rail (`starKey(v)`). When `onlyMine` is true and `stars` is non-empty, `apply()` drops vehicles whose key is not starred before counting, so the mode-chip counts match the map. Empty `stars` means no filtering. Corrupt or unexpected stored values are read as the default.

No home address or other personal data is stored in the repo. New keys must be versioned (`.v1`) and listed here.

## 7. Deployment

`git push origin main` → GitHub Pages builds from `main` at the repo root → live at
https://tpgordon8.github.io/philly-transit-live/. **Measured: about 45 seconds** from push until a newly added file
is served. Verify live changes with a cache-busting query string.

## 8. Test and review tooling

`python3 tests/run.py [--root <checkout>] [--only <text>]` runs a Playwright (headless Chromium) suite against any
checkout. The harness serves the checkout locally, mocks the Worker from `tests/fixtures`, serves Leaflet from
`tests/vendor`, and fails on any direct SEPTA call or other unexpected request. `tests/test_baseline.py` automates
the gatekeeper checklist; each feature adds its own `tests/test_<slug>.py`. Evidence goes to `tests/out/`
(gitignored). The baseline was mutation-checked: re-introducing the hidden-badge bug or the empty-vehicle-ID bug
makes it fail.

## 9. Findings that change the plan

1. **Task 1.2 is not client-only.** Stops come from `Stops/index.php?req1=<route>` (a per-route list of
   `{stopid, stopname, lat, lng}`, about 128 stops for route 21, unordered, no direction). The Worker does not
   allow it. Task W1 adds `Stops` (route validated against `^[A-Za-z0-9]{1,6}$`, edge-cached for a day) and, for
   rail boards, `Arrivals` (station validated). W1 is architect-owned and deploys first.
2. **Stop board ETAs.** SEPTA supplies no bus predictions here. ETAs for buses are computed from the vehicle's
   measured speed (successive refreshes), its distance to the stop, and its `next_stop_id`/heading. If speed is
   unknown or the vehicle is not approaching, the board says "—" rather than a made-up time. Rail stations can use
   SEPTA's own `Arrivals` times.
3. **Phase 3 free-tier risk.** Workers KV on the free plan allows about 1,000 writes/day (to be confirmed against
   current Cloudflare docs before building). A cron every 1–2 minutes that writes every run would exceed it, so
   the engine must write only when a rule's state changes, and the architect must confirm whether cron
   invocations count toward the 100,000 request cap.

## 10. Task breakdown and estimates

| ID | Task | Size | Depends on |
|---|---|---|---|
| 0.1 | Drop `late: 998` records (ghost filter hardening) | S | – |
| 1.1 | "My routes" preset (stars, default filter, toggle) | M | – |
| W1 | Worker v2: `Stops`, `Arrivals` endpoints (architect, Chrome) | S–M | – |
| 1.2 | Shareable stop links (`#stop=`, copy link) | M–L | W1 |
| 2.1 | Stop board with live ETAs | L | 1.2 |
| 3.1 | Alert engine (cron + KV) | L | free-tier confirmation |
| 3.2 | In-page notifications | M | 3.1 |
| 3.3 | Push notifications | deferred | 3.2 live and verified |

Order: 0.1 → 1.1 → W1 → 1.2 → 2.1 → 3.x. Tasks that edit `index.html` run one at a time to avoid merge conflicts.

## 11. Phase 3 decision: "Leave now" alerts are evaluated in the page, not in a Worker cron

Checked against Cloudflare's current limits (developers.cloudflare.com, 2026-10-08):

| Limit (free plan) | Value | Why it matters |
|---|---|---|
| Workers KV writes | 1,000/day | Every rule created or fired is a write; a public page can be spammed past this. |
| Workers KV reads | 100,000/day | Fine. |
| Worker CPU per cron invocation | 10 ms | Parsing the ~350 KB TransitView feed plus distance maths for every rule is likely to exceed it. |
| Worker requests | 100,000/day | The docs do not say whether cron invocations count toward it. |
| Cron triggers | 5 per account | Fine. |

A server-side engine also needs per-vehicle speed history between runs (state), would store a visitor's stops on
Cloudflare, and only pays off with push notifications (page closed). The page already receives the same live feed
every 15 s and already computes stop ETAs, so Task 3.1 (evaluation) and Task 3.2 (in-page notifications) are built
client-side: rules live in `localStorage` (`septa.rules.v1`), nothing is sent anywhere, no KV, no cron.
Limitation, stated in the UI: alerts only fire while the page is open (background tabs on phones may be paused by the
browser). Task 3.3 (true push) stays deferred; if wanted later it needs a Durable Object or KV design that stays
under the limits above.
