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
  sample divided by their time apart, and needs at least 20 s of span. Under 0.9 m/s counts as not moving; above 31 m/s
  (about 70 mph, so highway buses such as I-76 still get an ETA; or a single step that implies it) is treated as a GPS jump and discarded. Only the bus whose `next_stop_id` is the
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
  address search. Nominatim receives the address the user types. The one other exception is a user click: the
  "Open transit directions" link in the Get me home card opens Google Maps with the user's start point and Home
  coordinates in the URL, and the card says so next to the link. Nothing else leaves the browser.
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
- **Budget (free plan: 100,000 Worker requests/day).** Edge-cache hits still invoke the Worker, so every request
  counts. A fully active visible page (both feeds) costs 2 requests per 15 s = at most 11,520/day, plus Alerts every
  5 minutes in a visible tab (288/day). About eight such pages left open for 24 hours would reach the cap. Three
  rules keep real usage lower:
  (a) **Only fetch what is shown.** `TrainView` is skipped while the Regional Rail chip is off (5,760/day for the
  remaining feed). `TransitView` is skipped only when the Bus, Trolley and Subway chips are all off, no enabled
  leave-now rule exists and no stop is open (an open stop or a rule needs bus data whatever the chips say). A skipped
  source shows no count and draws nothing; turning a chip back on refetches immediately instead of waiting up to 15 s.
  (b) **Hidden tabs.** A hidden tab makes no requests unless an enabled leave-now rule exists, in which case it
  refreshes once a minute instead of every 15 s: 1,440/day for the bus feed alone, 2,880/day with Regional Rail on
  (down from 11,520). Trade-off: in a background tab the ETA samples are up to 60 s apart, so a leave-now alert can
  fire up to a minute later than it would in a visible tab (the speed measure needs 20 s of span, which one sample per
  minute satisfies).
  (c) **Failure backoff.** After N consecutive failed refresh cycles of a source (a cycle is the call plus its single
  1.5 s retry), the next attempt waits 15 s x 2^N, capped at 120 s: attempts 30 s, 60 s, then every 120 s. It is
  implemented by skipping 15 s ticks, per source (a healthy feed is not slowed by a failing one), and any success
  resets it. During a sustained outage a source costs at most 720 cycles x 2 requests = 1,440/day instead of 11,520
  per feed pair. The 120 s drop rule is unchanged.

  **Idle pause.** `lastUse` is set at boot and refreshed only by real user input (pointerdown, keydown, touchstart,
  wheel, window focus, the tab becoming visible again); timers, fetch results and scripted events do not count. Once
  `Date.now() - lastUse` reaches 60 minutes, `refresh()`, the Alerts fetch and every retry (the guard sits in
  `fetchOnce`) make no request at all, so the worst case for an untouched page is about one hour of requests (about
  250 TransitView calls with buses only) and then zero. A notice with a Resume button (`#idleBar`, deliberately not
  a live region) appears, the status line reads "Paused", leave-now alerts do not fire while paused, and the
  existing 120 s rule empties the map. Resuming is any interaction (including the click on Resume or returning to
  the tab): the notice goes away and buses (and rail if on) plus alerts refetch at once. Nothing is persisted, so a
  reload is a fresh use.

  **Defaults.** A browser with no saved choices starts with only the Bus chip on and a 0.5 mi radius. A default page
  (buses only, so no TrainView) makes about 5,760 TransitView + 288 Alerts requests a day, about 6,050, versus about
  11,800 with Regional Rail on. The radius does not affect requests (both feeds are fetched whole and filtered in the
  page); it only reduces the markers drawn. Trolleys and subway come through the same TransitView request as buses,
  so turning them on costs nothing extra; only the Regional Rail chip adds the TrainView request. About 16 such
  default pages left open around the clock reach the 100,000 limit. Browsers that saved the old defaults are moved
  to the new ones once (`septa.defaults.v2`, section 6).

## 3. Ghost-bus filter (`normBuses` in `index.html`)

A bus is kept only if all of these hold:

1. `timestamp` is greater than 0, and within 150 s of the **newest timestamp in the same feed** (not the device
   clock, so a wrong phone clock cannot hide or admit vehicles).
2. `VehicleID` and `label` are non-empty and not `"None"`. Empty-ID records carry the feed's own timestamp, so
   freshness alone lets them through; this rule drops them.
3. `lat`/`lng` parse and are non-zero.

`newest` is computed only over records that pass every other rule below (non-empty real ID and label, parseable
non-zero coordinates, not `late: 998`), so one bogus record with a far-future timestamp cannot push the reference
forward and empty the map. Null or non-object elements in the feed lists (`bus[]`, TrainView) are skipped.

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
- Colors: buses blue, trolleys green, subway purple (`--subway`, in a delimited CSS block), rail orange; all tokens are redefined for dark mode.
- Vehicle kinds: `bus`, `trolley`, `subway` (all three come from TransitView, classified by route id: trolley = T1-T5, G1, D1, D2 and legacy 10, 11, 13, 15, 34, 36, 101, 102; subway = B1, B2, B3, L1, M1) and `train` (TrainView). Subway uses the train drawing, a `Subway` chip, star key `subway:<route>`, and like trains has no View stop, stop board, ETA or leave-now rule.

## 5. Refresh loop and failure states

- `setInterval` every 15 s, skipped while `document.hidden` (every 60 s there when a leave-now rule is enabled); a
  visibility change triggers a refresh if the last one is older than 15 s. Each refresh fetches the wanted feeds of
  `TransitView` and `TrainView` in parallel (section 2 lists when one is skipped or backed off); each source keeps
  `{list, ok, stale, err}`.
- The fetch layer retries once after 1.5 s. If both attempts fail the source is marked stale: its markers dim and
  a warning banner says so ("Showing last known positions"). After 120 s without a good update the source is dropped entirely and the banner says that source's positions are unavailable ("Bus and trolley positions are unavailable", "Regional Rail positions are unavailable"), never "last known positions". If no source has
  ever loaded, the banner reads "Live data unavailable" and nothing is drawn. Positions are never invented,
  interpolated as fact, or kept past 120 s.
- Alerts load at boot and every 5 minutes. Alert HTML is converted to plain text with `DOMParser`
  (`textContent`) and rendered with `textContent`, never `innerHTML`.

## 6. localStorage schema (the only place personal state lives)

| Key | Shape |
|---|---|
| `septa.prefs.v1` | `{ center: {lat, lng, label}, radius: 0.25–5, filters: {bus, trolley, subway, train} }` |
| `septa.defaults.v2` | `"1"` once the one-time defaults migration has run. If absent at boot, `filters` and `radius` in `septa.prefs.v1` are reset to the defaults (buses only, 0.5 mi), the rest of prefs (center) is kept, and the key is set; if present, saved choices are never touched again. Works when prefs are missing or corrupt |
| `septa.places.v1` | `{ home: {name, lat, lng} \| null, list: [{id, name, lat, lng}] }` — validated on load: finite lat/lng, string names (cut to 40 chars), string ids, at most 50 list items; anything else is dropped |
| `septa.routes.v1` | `{ stars: [string], onlyMine: boolean }` — default `{stars: [], onlyMine: true}` |
| `septa.rules.v1` | `{ rules: [{id, route, stopId, stopName, lat, lng, minutes, enabled, last: {key, t} \| null}] }` — leave-now alerts, at most 10; `id` is random, `last` is the vehicle key and time of the last firing |

**Corrupt storage.** `septa.prefs.v1` and `septa.places.v1` are validated on load (`cleanPrefs`, `cleanPlaces`): a bad center falls back to Center City, radius outside 0.25-5 to 0.5, filters are merged over the defaults (bus only on) as booleans (so old prefs without `subway` still load), bad places are dropped. Bad values are ignored silently and the stored string is not rewritten on load (the one-time `septa.defaults.v2` migration is the only boot-time write).

**My routes.** Star keys: the route id string for buses and trolleys, `subway:` + route id for subway lines, `train:` + line name for Regional Rail (`starKey(v)`). When `onlyMine` is true and `stars` is non-empty, `apply()` drops vehicles whose key is not starred before counting, so the mode-chip counts match the map. Empty `stars` means no filtering. Corrupt or unexpected stored values are read as the default.

**Leave-now rules.** Read defensively: junk, a non-object, or any rule failing validation (route `^[A-Za-z0-9]{1,6}$`, stop id `^[0-9]{1,8}$`, integer `minutes` 2–30, finite lat/lng, unique id, no duplicate route/stop/minutes) is dropped; the first 10 valid rules are kept. Nothing about a rule leaves the browser.

**Rule evaluator (`evalRule`, exposed on `__SEPTA_TEST__`).** On every `apply()` each enabled rule is evaluated against `collect()` (radius, mode filters and My routes ignored). It returns a status and may fire only when the bus source is neither stale nor dropped and a bus on the rule's route has `nextId` equal to the rule's stop and `etaFor` returns a numeric, non-rough `min` (so an unknown or zero speed never fires). The smallest `min` is the "nearest bus"; the rule fires when that is at or below its threshold, unless the same vehicle key already fired within 15 minutes (`rule.last`, persisted). Firing calls `notify()`: a `role="alert"` toast in `#toasts` (max 3, never auto-dismissed), plus a system `Notification` only if permission was granted and the tab is hidden. Permission is requested only from the "Turn on browser notifications" click. While at least one enabled rule exists a hidden tab keeps refreshing, once a minute rather than every 15 s; with none it makes no requests, to protect the Worker request budget. Background freshness trade-off: a hidden tab has at most one position sample per minute, so an alert there can arrive up to about a minute later than in a visible tab (and phones may pause background tabs altogether).
 New keys must be versioned (`.v1`) and listed here.

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

Suite details. `tests/test_schema.py` is an offline schema-drift guard: it checks that every fixture record has the keys
and types that `normBuses`, `normTrains`, `buildAlerts`/`renderAlerts` and the stop lookup read, and names the missing
keys in its failure. The harness also fails if any `tests/fixtures/*.json` does not parse. `run.py` additionally runs
`node tests/test_worker.mjs` and reports it as one PASS/FAIL line (a SKIP line if node is not installed). Tests wait on
conditions, not fixed sleeps: `Session.settle()` polls until the map pane transform and marker count are unchanged for
three 100 ms samples, and `Session.tick()` waits until the Worker mock stops receiving requests (150 ms quiet, 600 ms cap).
Leaflet is loaded with Subresource Integrity (sha384 of the 1.9.4 file, identical to `tests/vendor/leaflet.min.js`);
the Leaflet CSS is inline, so there is no second tag to pin. If Leaflet is ever upgraded, recompute the hash:
`openssl dgst -sha384 -binary leaflet.min.js | openssl base64 -A`.

`python3 tests/live_smoke.py` is a separate, network-dependent check of the deployed Worker (stdlib only, not part of
`run.py`). It sends `Origin: https://tpgordon8.github.io` and prints one PASS/FAIL line each for: TransitView, TrainView,
Alerts, Stops and Arrivals shapes, the CORS header, 403 for a foreign Origin, 400 for bad parameters, 404 for an unknown
path. It exits 1 on any failure. Run it after every Worker deploy.

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

## 12. Trip planner (multi-modal "leave now" directions)

Scope (decided with the repo owner): leave-now trips from A to B made of walking, Indego bike share, ONE bus ride
and car; walk-only, bike-only and car-only are shown for comparison. No bus-to-bus transfers, no Regional Rail, no
arrive-by times in v1. Car is a standalone comparison option, never combined with a bus.

### 12.1 Data sources
| Need | Source | Notes |
|---|---|---|
| Street paths and times for walk, bike, car | OSM-based routing service `https://routing.openstreetmap.de/routed-foot|routed-bike|routed-car/route/v1/driving/<lng,lat;lng,lat>` (OSRM API, CORS open) | Fair use only. Only finalist legs are requested (at most about a dozen calls per plan), results cached in memory per coordinate pair and profile. Coordinates leave the browser to this third party, like typed addresses already go to Nominatim; the UI and README say so. |
| Indego stations and live bike/dock counts | GBFS: `https://gbfs.bcycle.com/bcycle_indego/station_information.json` (cached for the page session) and `station_status.json` (fetched fresh for each plan, ttl 60 s). CORS open, no key | `num_bikes_available`, `num_bikes_available_types` (electric/classic/smart), `num_docks_available`, `is_renting`, `is_returning`. Direct from the browser, so it costs no Worker requests. |
| Bus network topology and scheduled running times | SEPTA static GTFS (`https://www3.septa.org/developer/gtfs_public.zip`, inner `google_bus.zip`) preprocessed offline by `tools/build_network.py` into `data/bus-network.json` | Committed to the repo, served by GitHub Pages, fetched lazily the first time the planner opens. Regenerate when SEPTA publishes a new feed. The file records the feed's validity dates and the UI shows "schedule data as of ...". |
| Live buses | existing TransitView feed already in the page | Used for "is this route running now" and for the wait at the boarding stop. |

### 12.2 `data/bus-network.json` schema (version 1)
```
{ "v": 1,
  "generated": "YYYY-MM-DD",
  "feed": { "start": "YYYYMMDD", "end": "YYYYMMDD" },          // from feed_info.txt
  "stops": { "<stop_id>": [lat, lng, "name"], ... },            // only stops used by a pattern; lat/lng rounded to 5 dp
  "patterns": [
    { "id": "47-0-1",            // route-direction-index, unique
      "route": "47",             // GTFS route_short_name; MUST equal TransitView route_id for live matching
      "kind": "bus",             // "bus" (route_type 3) or "trolley" (route_type 0)
      "dir": 0,                  // GTFS direction_id
      "head": "Frankford TC",    // most common trip_headsign
      "stops": ["id", ...],      // ordered stop ids
      "mins": [0, 1.5, ...],     // cumulative scheduled minutes from the first stop, same length as stops, median over weekday 10:00-15:00 trips, 0.5 min resolution, non-decreasing
      "hw": 12,                  // typical weekday midday headway in minutes (integer), null if unknown
      "trips": 34 }              // weekday trips this pattern runs (all day), used to rank variants
  ] }
```
Selection rules: per (route, direction) keep the patterns with distinct stop sequences that each cover at least 15% of that
route-direction's weekday trips, at most 3, plus always the most common one. "Weekday" = service ids active on a typical
Wednesday inside the feed validity window. Shapes are not used: the bus leg is drawn as straight segments along the stop
sequence. Budget: under 2.5 MB raw (gzipped by Pages in transit). `tests/test_network_data.py` checks integrity.

### 12.3 Planner algorithm (pure functions in `index.html`, exposed on `window.__SEPTA_TEST__`)
Inputs: origin O, destination D, `now`, the network JSON, Indego info and status, live buses (`collect()`).
1. Always compute WALK (foot route O to D), CAR (car route), and BIKE: nearest rentable station S1 to O with at least
   one bike (rank by straight-line distance, consider the nearest 3), nearest station S2 to D with at least one free
   dock (nearest 3); legs: walk O to S1, bike S1 to S2, walk S2 to D. Overheads: 90 s to unlock, 60 s to dock.
2. BUS candidates: for each pattern whose route is currently running (at least one live vehicle with that route id in
   the feed), for each access mode in {walk, bike} and egress mode in {walk, bike}:
   - boarding stop b within 0.6 mi (walk) or 2.0 mi (bike) straight-line of O, alighting stop a within the same limits of D,
     with index(b) < index(a) in the pattern. Pre-rank by estimated total using straight-line distance x 1.3 and speeds
     walk 1.25 m/s, bike 3.6 m/s, bus ride = `mins[a] - mins[b]`. Keep the best 2 per (pattern, access, egress) and the best
     6 overall for exact routing.
   - Bike access needs an Indego station S1 near O with a bike and a station S2 within 0.15 mi of b with a free dock; the
     leg is walk O to S1, bike S1 to S2, walk S2 to b. Bike egress mirrors it: walk a to S3 (bike available, within
     0.15 mi of a), bike S3 to S4 (free dock, near D), walk S4 to D. If no such station exists the combination is dropped.
   - Exact times come from the routing service for every foot/bike leg (finalists only). Boarding buffer 60 s.
   - Wait at b: let `tArr` be the time the traveller reaches b. For every live vehicle on the pattern's route whose
     `next_stop_id` is in the pattern at index `i <= index(b)`, its time to reach b is `(mins[index(b)] - mins[i])` minutes
     (scheduled running time; its current lateness is assumed to persist). Take the first such vehicle with time >= `tArr`
     minus 1 minute: wait = time - `tArr`, flagged "live". If none is tracked: wait = `hw`/2 flagged "typical, from
     schedule". If `hw` is null and no vehicle: drop the option. Ride time is `mins[a] - mins[b]` (scheduled), flagged
     "scheduled".
3. Rank by total minutes; return at most 5 options with at most 2 per structure (walk-bus-walk, bike-bus-walk, ...) so
   the list is varied. Every option carries its legs: `{mode, from, to, meters, minutes, basis: 'routed'|'scheduled'|'live'|'typical', path:[[lat,lng],...], notes}`.
4. Honesty rules: no invented live data; label scheduled and typical numbers; Indego counts are as of the status timestamp
   and are shown with their age; no costs are shown; car has no traffic or parking data and says so.

### 12.4 Privacy and budget
Planning never touches the Worker. Third parties receive only what a leg needs: Indego (nothing), the routing service
(coordinates of leg endpoints), Nominatim (typed addresses, already the case). Nothing is stored except an optional,
user-confirmed "last plan" is NOT stored in v1. The 15 s refresh loop and idle pause are unchanged.
