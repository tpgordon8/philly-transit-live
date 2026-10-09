# Septer: architecture

The product was renamed from Philly Transit Live to Septer in version 1.1 (section 15). The repository, the GitHub Pages address, the Worker name and its User-Agent, and the `septa.*` localStorage keys keep their old names; text below that quotes the old name is history.

Status: Phase 0 audit, approved by the architect. Source of truth is this repo; `index.html` plus the scripts in `js/` are canonical (section 14).
Copies of the app outside the repo (for example a published artifact) are stale and may not work.

## 1. Data flow

```
Browser (GitHub Pages, static index.html)
   │  GET https://septa-proxy.tpgordon8.workers.dev/<endpoint>   (section 2 lists them)
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
- Third-party calls the page makes itself: OpenStreetMap tiles, Google Fonts, cdnjs (Leaflet 1.9.4), and Nominatim for
  address search (it receives the address the user types, also for the trip planner's From and To). Trip planning does
  not call its providers directly while the Worker is healthy: routing and Indego go through the Worker first, and a
  direct provider call happens only as a fallback (what is sent, to whom, and when the fallback applies: section 12.4).
  The one other exception is a user click: the "Open transit directions" link in the Get me home card opens Google Maps
  with the user's start point and Home coordinates in the URL, and the card says so next to the link. Personal state
  (center, saved places, starred routes, alert rules) never leaves the browser.
- Deviation from the plan text: the page calls `TransitView` with **no `?route=`**, which returns every active
  vehicle in one response (about 290 KB). One Worker request per refresh is cheaper against the daily budget than
  one request per route, so the plan's "batch route requests" goal is met by design.

## 2. The Worker

- Allowlist: `TransitView`, `TrainView`, `Alerts` (no parameters; the query string is ignored), plus `Stops?route=<id>`
  (id matches `^[A-Za-z0-9]{1,6}$`; meant to be cached a day, see the caching note below) and `Arrivals?station=<name>` (name matches
  `^[A-Za-z0-9 .'&/-]{2,40}$`, upstream `results=10`, cached 15 s). Bad parameters get 400 without reaching SEPTA.
  Anything else is a 404. Unit test: `node tests/test_worker.mjs`.
- New in v3: `/route/<foot|bike|car>?from=lat,lng&to=lat,lng` (both points finite numbers inside lat 39.6 to 40.4,
  lng -75.9 to -74.5, rounded to 4 decimals before the upstream call; anything else is 400; edge-cached 60 s) and
  `/indego/<information|status>` (GBFS, cached 1 h / 30 s). Upstream errors are never cached (`cacheTtlByStatus` makes
  non-2xx uncacheable) and an answer that is not a valid route or station feed is a 502. `Stops` answers that are empty or
  not an array live 60 s. A real list is meant to live a day, through the Cache API, which only does anything on a
  custom domain. What is true today: the deployed Worker runs on `*.workers.dev`, where the Cache API is a no-op, so
  Stops are cached for the 60 s subrequest TTL (always safe, but up to 1,440 times more upstream fetches per route and
  edge location than the intended day). Moving to a custom domain would turn the day-long cache on without a code
  change. `tests/test_worker.mjs` covers the TTL choice; the workers.dev behaviour itself cannot be verified offline.
- CORS and origins: allows `https://tpgordon8.github.io` plus `http://localhost` and `http://127.0.0.1` on any port. Any
  other `Origin` header, including `null` and the empty string, gets 403. A request with no `Origin` is allowed (curl,
  the smoke test) unless it carries a `Sec-Fetch-Site` of cross-site or same-site. This is a soft guard, since non-browser
  clients can spoof `Origin`; the data is public anyway. (`null`, a locally opened file, used to be allowed.)
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

## 3. Ghost-bus filter (`normBuses` in `js/feed.js`)

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
   allow it. Task W1 adds `Stops` (route validated against `^[A-Za-z0-9]{1,6}$`; cached a day where the Cache API works, else 60 s: section 2) and, for
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
| Street paths and times for walk, bike, car | OSM-based routing service `https://routing.openstreetmap.de/routed-foot|routed-bike|routed-car/route/v1/driving/<lng,lat;lng,lat>` (OSRM API, CORS open) | Fair use only. Only finalist legs are requested (at most about a dozen calls per plan), results cached in memory per coordinate pair and profile. Coordinates reach this third party, like typed addresses already reach Nominatim; the UI and README say so. They go through the Worker; a direct call is only the fallback (section 12.4). |
| Indego stations and live bike/dock counts | GBFS: `https://gbfs.bcycle.com/bcycle_indego/station_information.json` (cached for the page session) and `station_status.json` (fetched fresh for each plan, ttl 60 s). CORS open, no key (the page reads them through the Worker's `/indego/*`, which costs Worker requests; direct only as the fallback, section 12.4) | `num_bikes_available`, `num_bikes_available_types` (electric/classic/smart), `num_docks_available`, `is_renting`, `is_returning`. |
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
`feed` also carries `sampleDate` (YYYYMMDD), the typical Wednesday used to pick the weekday service ids.

How to regenerate: `python3 -I tools/build_network.py --zip-url https://www3.septa.org/developer/gtfs_public.zip`
(or `--zip FILE` for a downloaded copy of gtfs_public.zip or google_bus.zip, or `--gtfs-dir DIR` for an already
extracted bus feed). Standard library only, about 5 s; stop_times.txt is streamed. Only the needed text files are
extracted to a temp directory; nothing downloaded is executed. Then run `python3 tests/run.py --only network_data`
and commit `data/bus-network.json`.

### 12.3 Planner algorithm (functions in `js/routing.js`, `js/candidates.js` and `js/planner.js`, exposed on `window.__SEPTA_TEST__`)
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
3. Rank by the sum of the legs' exact (unrounded) minutes; the card shows its ceiling, and each step shows its own rounded minutes (a note says when the steps add to a different number). Return at most 5 options with at most 2 per structure (walk-bus-walk, bike-bus-walk, ...) so
   the list is varied. Every option carries its legs: `{mode, from, to, meters, minutes, basis: 'routed'|'scheduled'|'live'|'typical', path:[[lat,lng],...], notes}`.
4. Honesty rules: no invented live data; label scheduled and typical numbers; Indego counts are as of the status timestamp
   and are shown with their age; no costs are shown; car has no traffic or parking data and says so.

### 12.4 Privacy and budget
What is sent where (the page text in `index.html` and the README say the same):
- A typed From or To address goes to Nominatim, at least 1.1 s after the previous lookup; answers (misses included) are cached in memory for the page session. Nothing typed ever reaches the Worker.
- The start and end coordinates of every routed leg go to the Worker (`/route/<foot|bike|car>`, section 2), which rounds them to 4 decimals (about 10 m), forwards them to the OSM routing service (`routing.openstreetmap.de`, User-Agent `philly-transit-live (+https://tpgordon8.github.io/philly-transit-live/)`) and edge-caches the answer for 60 s. Indego goes through `/indego/<information|status>` (cached 1 h / 30 s) and carries no user data. The Worker stores nothing of its own. `/route` and `/indego` refuse a request without an allowed Origin (403).
- Saved Home, saved place chips, Use my location and the map center are not geocoded, but their coordinates are routed exactly like a typed address, so they reach the Worker and the routing service the same way.
- Fallback: the page falls back once to the direct provider URL ONLY on a network error or timeout, a Worker 404 (an older Worker without the endpoint) or a Worker 502, 503 or 504 (or a 200 that is not JSON). In that case the routing service receives the coordinates unrounded, at the page's 5 decimals (about 1 m), and Indego is read from its public GBFS URL. Every other Worker answer is final and is never re-sent elsewhere: 400 for a bad parameter, 403, and 422 `{"code":"NoRoute"|"NoSegment"|...}`, the Worker's pass-through of a well-formed OSRM error (OSRM answers HTTP 400 for every error code, which the Worker cannot report as a 502 or the page would mistake it for an outage). A 422 is never cached. The page reads `NoRoute` and `NoSegment` as "no street route between those points", which is the "No trip found" state.
- Points outside the Worker's box (lat 39.6 to 40.4, lng -75.9 to -74.5) are refused in the page before any call: "That place is outside the area this planner covers (Philadelphia region).", with no Retry.

Budget: at most about a dozen route calls plus one Indego status per plan. The routing queue runs at most 2 requests at once and starts at most one every 250 ms (`TP.MAX_INFLIGHT`, `TP.GAP_MS`). The FOSSGIS policy asks for about one request per second per client; most legs are served from the Worker's edge cache and do not reach OSRM, so 250 ms is the accepted compromise, and the planner shows "Routing by OSRM / data (c) OpenStreetMap contributors". Clear trip and a new plan cancel the old plan: queued calls are dropped, in-flight requests aborted (`cancelPlan`, `ctx.dead`).
Nothing is stored in v1: no localStorage key for trips, the From and To text is not saved, and a "last plan" is NOT stored. The 15 s refresh loop and idle pause are unchanged; planning does not count as a user interaction and never resumes a paused page.

## 13. Tech-debt resolution plan (v1.0 stabilisation)

Goal: leave no known debt before the next feature. Every package keeps behaviour identical unless it says otherwise, adds a test that fails without the change (mutation check), and merges only after the lead re-runs the full suite. Developers work in their own git worktree on their own branch and touch only the files they own.

### 13.1 Debt register

| ID | Debt | Risk | Package | Status |
|----|------|------|---------|----|
| D1 | Planner calls the free OSM routing service and Indego directly from the page: no cache, no shared rate limit, no provider switch | Trips fail when the provider throttles; users' coordinates go straight to a third party | WP1 | closed (review round 2, WP5; Worker v3 deployed and smoke-tested 2026-10-09) |
| D2 | Cached `Stops` answers of `[]` live for a day | One bad upstream answer hides a route's stops all day | WP1 | closed, `272f1b2`; the one-day cache only works on a custom domain (section 2) |
| D3 | Worker accepts an `Origin` of `null` | Soft guard | WP1 | closed, `272f1b2` |
| D4 | Planner reports every failure as "some bus options could not be completed" | User cannot tell a routing limit from "no bus trip exists" | WP2 | closed (review round 2, WP5) |
| D5 | Indego pin counts are parsed back out of leg note text | Breaks silently when wording changes | WP2 | closed, `99f1441` |
| D6 | Clear trip does not restore the previous map view; "No trip found" state untested; plan on a 390 px phone map is small | Rough edges | WP2 | closed (review round 2, WP5) |
| D7 | Bus schedule data is a static snapshot that expires 2027-02-20 and must be regenerated by hand | Silent staleness | WP2 (warning in UI), WP4 (automation) | closed after review round 2 (warning in UI `99f1441`; refresh workflow `1da8b58`, hardened and given a keepalive in round 2) |
| D8 | One 2,300-line script block with shared globals | Every change costs more to read around | WP3 | closed after review round 2 (split `daa0d6d`; duplicate declarations and the unused `S.main` removed in round 2) |
| D9 | Full suite takes ~9 minutes; no CI | Slow feedback, no gate on main | WP4 | closed after review round 2 (runner and CI `1da8b58`; duplicate Worker test, duplicate branch runs and the fast-set time fixed in round 2) |
| D10 | Leftover feature branches and worktrees | Clutter | lead | lead task, not a code change; verify with `git branch -a` and `git worktree list` |

### 13.2 Work packages

**WP1 Worker v3 and client routing (owns `worker/worker.js`, `tests/test_worker.mjs`, `tests/live_smoke.py`, and in `index.html` only the `ROUTE_BASE`/`INDEGO_BASE` constants and `routeLeg`/`loadIndego` fetch calls).**
- New endpoints: `/route/<foot|bike|car>?from=lat,lng&to=lat,lng` and `/indego/<information|status>`. `from` and `to` must be two finite numbers inside a Philadelphia-region box (lat 39.6 to 40.4, lng -75.9 to -74.5); anything else gets 400. Coordinates are rounded to 4 decimals before the upstream call and the cache key, edge-cached 60 s (route) and 30 s (Indego status), 1 hour for Indego information. Upstream errors are never cached.
- Empty or non-array `Stops` upstream answers are cached 60 s, not a day. Origin `null` and empty origins are rejected with 403 for browser-style requests; the allow-list is the Pages origin plus localhost and 127.0.0.1 on any port. Existing endpoint behaviour is otherwise unchanged.
- Client: planner routing and Indego go through the Worker first; when that fails it falls back to the direct provider URL (the exact rules are in section 12.4), so one outage cannot take the planner down. Privacy text in the page, README and section 12.4 is updated: coordinates go to our Worker, which forwards them to the routing service and does not store them.
- Tests: Worker unit tests for validation, rounding, caching TTLs, null origin, and error non-caching; page tests for Worker-first, fallback, and that no direct provider call is made when the Worker answers.

**WP2 Planner honesty and polish (owns the planner and trip-UI regions of `index.html`, `tests/test_planner_core.py`, `tests/test_trip_ui.py`).**
- The planner returns structured notes: each has a `code` (`routing_limit`, `routing_failed`, `no_live_bus`, `no_bus_beats_baseline`, `schedule_stale`) and the UI renders a distinct plain sentence for each. The generic sentence goes away.
- Legs that use Indego carry structured `station` objects (`{name, bikes, ebikes, docks, asOf}`); pins and notes read from them and the note-text parsing is deleted.
- Clear trip restores the map centre and zoom saved when the plan was drawn. A "No trip found" state exists and is tested. On widths of 480 px and below, "Show on map" scrolls the map into view and the map height is at least 45 percent of the viewport.
- The planner shows "Bus schedule data as of <feed start>" under the options, and a visible warning when today is after the feed end date or within 14 days of it.

**WP3 Modularise (starts after WP1, WP2 and WP4 are merged; owns `index.html`, new `js/*.js`, `tests/harness.py` asset serving).**
- Split the script into plain classic script files with no build step and no bundler, loaded in dependency order: `js/util.js` (storage, formatting, geometry), `js/feed.js` (fetching, ghost filter, kinds, refresh scheduler, idle pause), `js/stops.js` (stop links, stop board, ETA), `js/alerts.js`, `js/planner.js` (network, Indego, routing, planning), `js/ui.js` (map, sidebar, trip UI), `js/main.js` (wiring and start). One namespace object per module on `window.SEPTA`; no new globals beyond it and the test hook.
- Pure move: no logic changes. Gate: the full suite passes unchanged, and a script compares the sorted set of top-level function names before and after. The `__SEPTA_TEST__` hook, SRI on Leaflet, and idle and budget behaviour are untouched. The harness serves the new files.
- Pages deploy serves the files as is; the service of any file that fails to load shows a visible error banner rather than a blank page.

**WP4 Tests, CI and data freshness (owns `tests/run.py`, `.github/`, `tools/`, `README.md` test section; no `index.html` edits).**
- Tag tests `fast` or `full`. `run.py --fast` runs the fast set (target under 90 s on 2 CPUs). Measured on 2 CPUs while the machine was also loaded by other jobs (load average about 7): the first fast set of 64 tests took 95 s, which missed the target, so it was trimmed to 54 tests (one or two fewer in six files, every test file keeps at least one fast test) and now takes 74 s, with CPU time down from 90 s to 71 s. The full suite of 208 tests took 899 s on the same loaded machine; an idle-machine figure was not measured and covers every package at least once; plain `run.py` still runs everything. Run test files in parallel processes with isolated output folders.
- GitHub Actions: on every push and pull request run the fast suite plus the Worker tests; on main also the full suite. A monthly scheduled workflow regenerates the bus network from SEPTA's GTFS URL; if the feed date range changed it opens a pull request with the new data and the test results, otherwise it does nothing. If the repo token cannot push workflow files, deliver the files committed in a separate branch and say so.
- Add a data sanity test: route and stop counts within 10 percent of the committed file, file under 1.5 MB, and feed end date in the future.

### 13.3 Order and gates

1. Lead: merge planner branches already shipped, delete leftover worktrees and branches (D10), tag a baseline `v0.9-pre-debt`.
2. In parallel: WP1, WP2, WP4, each in its own worktree. Lead reviews each diff and runs its suite before merging, in the order WP4, WP1, WP2, resolving conflicts in the lead checkout.
3. Lead deploys Worker v3 through the Cloudflare dashboard and runs the live smoke test before any page change that depends on it ships. The page keeps the direct-provider fallback, so order does not break users.
4. WP3 runs alone on the merged result.
5. Independent review by a fresh reviewer who has not seen the work: correctness, request budget, privacy text matches behaviour, and no leftover debt from the register. Findings are fixed before release.
6. Lead pushes, waits for Pages, verifies live in real Chrome on desktop and phone widths (example trip, stop board, alert rule, idle banner, console clean), then updates this section to mark each debt item closed with the commit that closed it.

### 13.4 Definition of debt free

Every register item closed with a test; fast suite under 90 s; CI green on main; Worker v3 live and smoke-tested; no direct third-party call from the page when the Worker is healthy (the direct fallback happens only on a network error, a Worker 404 or a Worker 502/503/504, never on a 4xx or 422 answer, see 12.4); no script block over 600 lines; a monthly job keeps schedule data fresh; this document lists no open items.

## 14. Code layout (WP3 split, reshaped by WP-F)

`index.html` keeps the markup, the Leaflet script tag (with its SRI hash, unchanged), eight `<link rel="stylesheet">` tags and 18 lines of inline script. The application code is eleven classic scripts under `js/` and the styles are eight stylesheets under `css/`. There is no bundler, no ES modules and no build step; GitHub Pages serves the files as they are. Prettier and ESLint (section 15.1) are dev tools only.

### 14.1 Files and load order

| File | Lines | Holds |
|------|-------|-------|
| `js/util.js` | 338 | constants, formatting and geometry, `$`, the `localStorage` wrapper, saved preferences, places, starred routes, the shared `state` object, the Leaflet-missing banner |
| `js/feed.js` | 408 | `normBuses` (ghost filter), `normTrains`, `septa()` fetch through the Worker, idle pause, `refresh`, and `collect`/`apply`, the pipeline that turns feed data into what is drawn |
| `js/map.js` | 448 | the Leaflet map, search-point and Home pins, vehicle markers, selection, the vehicle detail card |
| `js/panel.js` | 650 | the sidebar: status line, My routes, search box and geocoding, Use my location, `setCenter`/`setRadius`, mode chips, saved places, Get me home, the empty-state actions |
| `js/stops.js` | 444 | speed history and `etaFor`, stop links, stop card and live stop board |
| `js/alerts.js` | 508 | service alerts and the leave-now rules (`evalRule`, `evalRules`, `notify`) |
| `js/routing.js` | 442 | trip planner data clients: planner constants `TP`, bus network, Indego, the routing queue, `routeLeg`, `cancelPlan` (no DOM) |
| `js/candidates.js` | 217 | trip planner bus candidates: nearby stops and stations, wait estimates, `buildBusCandidates` (pure) |
| `js/planner.js` | 535 | trip planner: leg assembly, schedule state, `planTrips` (no DOM) |
| `js/trip.js` | 664 | trip planner interface: form, results, map drawing |
| `js/main.js` | 108 | the `window.__SEPTA_TEST__` hook and the start-up calls |

| Stylesheet | Holds |
|------------|-------|
| `css/leaflet.css` | the Leaflet stylesheet (was inlined; the Leaflet script tag and its SRI hash are untouched) |
| `css/base.css` | design tokens and dark theme, reset, typography, header and brand, the status dot |
| `css/layout.css` | app shell, sidebar, map stage and their responsive rules (820 px and 480 px) |
| `css/map.css` | Leaflet overrides and controls, vehicle markers, pins, the vehicle card, the empty-state card |
| `css/panel.css` | sidebar sections, search, buttons, chips, saved places, My routes |
| `css/trip.css` | trip planner form, results and map drawing |
| `css/stops.css` | stop card and live stop board |
| `css/alerts.css` | service alerts, banners, leave-now rules, toasts |

The stylesheets load in the order of that table, and the rules inside each file keep the relative order they had in the old inline block. WP-F checked that no pair of rules with the same specificity and a shared property swapped order, and that computed styles of every element and screenshots at 390 and 1280 px, light and dark, were identical before and after.

The inline script before the app scripts creates `window.SEPTA` (one object per file except `main`, which adds none, plus `failed` and `loadFailed`) and the load-error listener. `index.html` then loads `util`, `feed`, `map`, `panel`, `stops`, `alerts`, `routing`, `candidates`, `planner`, `trip`, `main` in that order, then a one-line check that `main.js` ran.

### 14.2 How the files share code

Each file is its own closure (an IIFE with `'use strict'`) and shares code only through `window.SEPTA.<file>`:

- `var S = window.SEPTA;` and import lines `var a = S.util.a, b = S.util.b;`. These copy names owned by an earlier file. They are by value, so only things that are never reassigned (functions, constants, objects such as `state`, `map`, `routesStore`) are shared this way. A variable that is reassigned after load (`inflight`, `radiusCircle`, `savedCenter`, `stopLayer`, `gmhLine`, the planner caches, ...) lives in the same file as every function that touches it.
- Forward-call shims `function renderStatus() { return S.panel.renderStatus.apply(null, arguments); }` for a function owned by a later file. They look the function up at call time, so circular calls (feed calls map and panel, map calls panel and stops) work. A shim is never called while the files are loading.
- Export lines `S.util.esc = esc;` for names another file or the test hook uses. Every export has at least one importer.
- `S.halt = typeof L === 'undefined';` in `util.js` and `if (S.halt) return;` in the files that need Leaflet. The pure functions are exported before that point so the test hook still works; nothing else starts.
- `S.started = true;` in `main.js`, and a small `S.map.radiusCircleBounds` bridge for the one reassigned variable the start-up code reads.

Top-level statements that run at load time (event wiring, `setInterval`, the one-time defaults migration) stay in the file that owns what they touch. `tests/test_modules.py` enforces file size (700 lines), load order, and that `window` gains only `SEPTA`.

### 14.3 Adding a module

1. Create `js/<name>.js` with the same shape as an existing small file (`main.js` is the shortest): the IIFE, `var S = window.SEPTA;`, imports, your code, exports.
2. Add `<name>:{}` to the object in the inline script of `index.html` and a `<script src="js/<name>.js"></script>` tag. Place it after every file whose variables it needs at load time; files it only calls into later can come after it (use a shim).
3. Add the name to `FILES` in `tests/test_modules.py`. Keep the file at 700 lines or fewer.
4. Run `npm run lint`, `npm run format`, then `python3 tests/run.py --fast`. Tests that grep source read it through `app_source`/`app_script` in `tests/harness.py`.

### 14.4 Failure behaviour and deviations from 13.2

- A script that fails to load (404, network error, blocked) triggers a capture-phase `error` listener that adds a fixed red `#loadError` banner naming the file. A final inline check does the same if `main.js` never ran, for example after a syntax error. The banner is separate from `#banner` because the app rewrites `#banner` every second.
- Plan 13.2 had `ui.js` holding the trip UI; it became its own `trip.js`. WP-F later split `ui.js` into `map.js` and `panel.js` and `planner.js` into `routing.js`, `candidates.js` and `planner.js`. `feed.js` also owns `collect`/`apply` because they read the refresh loop's `inflight` flag.
- There is no service worker or cache list in the repo, so there was nothing to update there.
- `tests/harness.py` already served the checkout directory, so `js/` needed no server change; it gained `app_script` and `app_source`, and the two tests that grep source (`test_single_clear_selection_and_all_paths_work`, `test_dead_code_removed`) now read through them, because the code they search is no longer in `index.html`.

## 15. Septer 1.1: direction, autocomplete, brand, mobile, clean code

Goals from the owner: (1) the N/E/S/W badge and the vehicle's facing show the route's direction, not the bus's momentary compass heading; (2) a bus on a north-south route is drawn vertically, Uber-style, and an east-west route horizontally; (3) every address field suggests places and addresses as you type ("city hall" offers Philadelphia City Hall); (4) the product is named Septer, with a plain Helvetica-style title; (5) everything is as easy to use on a phone as on tablet and desktop; (6) all remaining tech debt is closed and the code is clean and readable before release.

### 15.1 Decisions

- **Route direction.** The bus feed gives each bus a `Direction` of Northbound, Southbound, Eastbound, Westbound or Loop. The badge letter is that direction (N, S, E, W). Loop and a missing direction show no letter and the marker faces the bus's actual heading snapped to the nearest compass point. Regional Rail trains have no direction in the feed and keep the heading-based letter; this is documented in the vehicle card. A marker changes facing only when its route direction changes, so a detour never flips it. The stop board and the "heading toward Home" feature are physics and keep using the true heading.
- **Facing.** A new top-down bus (and trolley, subway and train) icon is drawn pointing up and rotated to the route direction: north up, south down, east right, west left. Only the vehicle shape rotates; the route number and the direction badge stay upright. The accessible name says "northbound", not "heading N".
- **Autocomplete.** Photon (photon.komoot.io, OpenStreetMap data, made for type-ahead, CORS open) called directly from the page, biased to the map centre and boxed to the Philadelphia region. Nominatim's usage policy forbids autocomplete, so Nominatim stays only for the final submit fallback (intersections such as "10th & Race"). A small built-in list of well-known Philadelphia places is matched first so common names answer instantly and offline. Debounce 250 ms, at least 3 characters, one request in flight (older ones aborted), session cache, quiet failure (no suggestions, submit still works). No Worker change, so no manual deploy. The privacy text states that typed text goes to Photon while typing.
- **Name and font.** Product name Septer everywhere users see it. The title uses a Helvetica-style system stack (`"Helvetica Neue", Helvetica, Arial, sans-serif`, bold): Helvetica is the plain face SEPTA's signage and public identity are known for, and it cannot be web-loaded for licence reasons, so the system stack is the faithful choice. The repo and the Pages address keep their names (renaming would break existing links); the Worker's User-Agent string is unchanged because changing it needs a manual Worker deploy.
- **Clean code.** One formatting pass (Prettier, ES5 style kept), ESLint in CI, CSS moved out of the HTML into files by area, `js/ui.js` split by responsibility, no `/*@split*/` leftovers, dead code removed. The formatting commit lands first and changes no behaviour.

### 15.2 Work packages and order

1. **WP-F Clean code foundation** (alone, first). Prettier over `js/`, `tests/*.py` untouched. ESLint flat config (recommended rules, `no-unused-vars`, `no-undef` with browser globals) wired into CI and README; fix all findings, deleting dead code. Move inline CSS into `css/` files by area (`base.css`, `layout.css`, `map.css`, `panel.css`, `trip.css`, `stops.css`, `alerts.css`, `leaflet.css`) with identical cascade order. Split `js/ui.js` into `js/map.js` (map, markers, vehicle card) and `js/panel.js` (sidebar, search, home, places). Remove `/*@split*/` markers; set the size limit in `tests/test_modules.py` to 700 lines and split any file over it. Produce a debt inventory (TODO/FIXME, duplicated helpers, functions over 60 lines, stale comments) and fix it. Gate: full suite unchanged and green, screenshots identical at 390 and 1280.
2. **WP-B Route direction and vehicle icons** (owns `js/map.js` marker code, `css/map.css`, feed normalisation, their tests). Parallel with C and D.
3. **WP-C Place autocomplete** (owns new `js/suggest.js`, `css/suggest.css`, search and trip field wiring, tests, privacy text). Parallel with B and D.
4. **WP-D Septer brand** (owns `index.html` head and header, `css/base.css` brand rules, manifest and icons, README and ARCHITECTURE naming, test strings). Parallel with B and C.
5. **WP-E Mobile and responsive** (after B, C and D are merged). Audit 320, 360, 390, 414, 600, 768, 820, 1024, 1280 and 1440 px wide plus phone landscape (844x390), with touch emulation. Requirements: no horizontal scroll, tap targets at least 44 px, inputs at least 16 px so iOS does not zoom, safe-area insets (`viewport-fit=cover`, `env(safe-area-inset-*)`), `dvh` heights, the autocomplete list and the on-screen keyboard never hide the field being typed in, a map-first phone layout with the panel reachable by thumb, visible focus, and no overlap of map controls with the panel. Parametrised viewport tests plus a screenshot matrix reviewed by the lead.
6. **WP-G Review and release.** An independent reviewer on the merged result (correctness, request budget, privacy text, XSS in suggestion labels, accessibility of the combobox, clean-code audit, debt register). Fix round. Full suite, CI green, push, live check in Chrome at several widths. Mark this section closed.

### 15.3 Definition of done

Badge and facing follow route direction (tests with a detour heading that disagrees with the route); vertical icons on N-S routes and horizontal on E-W; every address field has a keyboard- and touch-accessible combobox; "city hall" suggests Philadelphia City Hall; title and metadata say Septer in the Helvetica-style stack; the viewport matrix passes; lint clean in CI; no file over 700 lines; full suite and CI green; independent review has no open blocker or should-fix item.

### 15.4 Debt inventory after WP-F

Fixed in WP-F (all behaviour-neutral): `STALE_AFTER_MS`, an unused `renderRules` parameter and an unused `base` array removed; empty `catch` blocks now say why they are empty; stale comments rewritten (file headers that called the files a "split of index.html", an `index.html` task marker in `css/panel.css`, "legacy" planner notes that are current); magic numbers given names (`M_PER_MI`, radius range and widen step with one `widenedRadius` helper instead of two copies of the same arithmetic, `NOGLIDE_MS`, `FETCH_TIMEOUT_MS`, `SCHEDULE_ONLY_LATE`, geolocation timeouts, alert limits, `MS_PER_DAY`, `M_PER_DEG`); one shadowed helper name in `syncMarkers`; three exports with no importer removed. Searched and found none: TODO/FIXME/HACK comments, functions with identical bodies, globals other than `window.SEPTA` and the Leaflet `L` (the test `test_page_adds_only_the_septa_namespace` enforces this). ESLint found no real bug; the only code findings were dead code.

Left open, each with a reason:

| File | Item | Why it is left |
|------|------|----------------|
| `js/planner.js` | `planTrips` is 299 lines, mostly one 256-line `Promise.all(...).then` body with two nested chains | The planner is the riskiest logic in the app and the planner tests are black-box; cutting it into named steps needs the callbacks' shared locals (`ctx`, `notes`, `finals`) passed explicitly. Do it in a package that owns planner behaviour, not in a no-behaviour-change pass |
| `js/trip.js` | `tripRender` 137 lines, `startTrip` 80, `tripStep` 75 | DOM building interleaved with state changes; splitting needs new UI tests for each piece. WP-C edits this file for the autocomplete wiring, so splitting it now would only cause merge conflicts |
| `js/candidates.js` | `buildBusCandidates` 106 lines | Pure and well covered, but its inner loops share five accumulators; extraction would change the shape of the hot loop. Leave until a planner package owns it |
| `js/map.js` | `buildDetail` 107 lines, `syncMarkers` 62 | WP-B rewrites marker construction and the direction badge in these two functions; refactor after B merges |
| `js/panel.js` | `renderStatusView` 100 lines, `renderGMH` 82, `renderPlaces` 69, `getMeHome` 64 | Straight-line DOM construction with many text variants; each branch is tested only through the page. Split when a package next changes the status line or Home |
| `js/routing.js` | `routeLeg` 76 lines | Queue, cache, abort and fallback in one function by design (section 12.4); splitting risks the request-budget rules |
| `js/planner.js`, `js/stops.js` | `assembleBus` 68, `renderStopCard` 68 | Marginally over the 60-line guide and cohesive |
| `js/trip.js`, `js/panel.js` | 664 and 650 lines, limit 700 | WP-C adds the autocomplete wiring to both. If either passes 700, move the form (trip) or saved places and Home (panel) into their own file along the existing section comments |
| `js/map.js`, `js/stops.js`, `js/trip.js`, `js/util.js` | Remaining unnamed numbers: marker and pin geometry (80x44 icon, 18 and 26 px pins, label widths 34/44/58, z-index offsets 400, 500, 900), `cardinal`'s 45 degree sectors, the 50 degree Home-heading tolerance in `panel.js`, the 500 ms back-off slack in `feed.js`, HTTP status lists in `routing.js` | They are layout or protocol values used once, next to the code that explains them. WP-B and WP-E rewrite the marker and layout numbers, so naming them now would be churn |
| `js/*.js` | Forward-call shims (`function x() { return S.ns.x.apply(null, arguments); }`, 18 of them) | Needed because feed, map, panel, stops and alerts call each other at run time while loading in one fixed order. Removing them means a small event bus or merging files; neither is worth the risk before release |
| `js/util.js`, `js/feed.js` | `state` is one mutable object written by several files | Matches the original single-script design; narrowing it to setter functions is a larger change with no user-visible gain |
| `js/trip.js`, `js/panel.js` | Geocoding (`geocode`, 1.1 s spacing, session cache) lives in `panel.js` but is also used by `trip.js` | WP-C replaces the typed-address path with the autocomplete module, which is the natural home for it |
| `ARCHITECTURE.md` sections 1 to 13 | Historical text still says "in `index.html`" for code that moved to `js/` in WP3 | Those sections are the record of the v1.0 plan and decisions; section 14 is the current layout |
| `tests/*.py` | Not formatted or linted (out of scope for WP-F); a few tests grep source text, so Prettier changes to `js/` can break them | `test_modules.py` was updated for the new layout; the others pass unchanged |
