# Septer: live Philadelphia transit

Septer is the new name of this project. The repository and the GitHub Pages address (`philly-transit-live`) keep their old names so existing links keep working.

A live map of SEPTA buses, trolleys and Regional Rail trains around any address in Philadelphia, with route alerts,
shareable stop links, stop boards with computed ETAs, and "leave now" alerts. Live at
https://tpgordon8.github.io/philly-transit-live/

## How data flows

The page is a static `index.html` plus plain script files under `js/` (no build step), served by GitHub Pages. It asks a small Cloudflare Worker (`worker/worker.js`)
for SEPTA's public feeds, because SEPTA's API sends no CORS headers; the Worker allowlists a handful of endpoints and
caches them briefly. Details are in [ARCHITECTURE.md](ARCHITECTURE.md). By default the page shows only buses within 0.5 mi, which also skips the Regional Rail request and roughly halves Worker traffic.

## Code layout

`index.html` holds the markup and a short loader. The styles are eight plain stylesheets in `css/`, linked in this
order: `leaflet` (the Leaflet stylesheet), `base` (tokens, reset, header), `layout` (app shell, responsive rules), `map`
(markers, pins, vehicle card), `panel` (sidebar sections), `trip` (trip planner), `stops` (stop card and board) and
`alerts` (service alerts, leave-now rules, toasts, banners). The application code is eleven classic scripts in `js/`,
loaded with ordinary `<script src>` tags in dependency order: `util` (helpers, storage, shared state), `feed` (vehicle
feed, ghost filter, idle pause, refresh), `map` (Leaflet map, markers, vehicle card), `panel` (sidebar: status, search,
saved places, Home, radius, filters), `stops` (stop links, stop board, ETA), `alerts` (service alerts, leave-now rules),
`routing` (trip planner data clients), `candidates` (bus candidates), `planner` (trip planner), `trip` (trip planner
interface) and `main` (test hook and start). Each file except `main` adds one object to `window.SEPTA`, and nothing else
is global. If a file fails to load, a red banner at the top of the page names it. How the files fit together and how to
add one: [ARCHITECTURE.md](ARCHITECTURE.md) section 14. There is no build step; GitHub Pages serves the files as they are.

The app manifest is `manifest.webmanifest` and the logo mark and its PNG exports are in `icons/` (`favicon.svg` is the source; there is no service worker). The title is set in the Helvetica-style system font stack, so no font file for it is shipped.

## Lint and format

The app itself needs no tooling, but `js/` and `worker/worker.js` are checked with ESLint and Prettier (dev tools only,
pinned in `package-lock.json`). Needs Node 20.19 or newer.

    npm ci                # once
    npm run lint          # ESLint over js/ and worker/ (flat config in eslint.config.js)
    npm run format        # Prettier rewrites js/, worker/worker.js and eslint.config.js (.prettierrc)
    npm run format:check  # the same check CI runs, without writing

CI runs `npx prettier --check` and `npx eslint .` as its own job on every pull request and on `main`. The style is
ES5 on purpose (`var`, classic scripts); Prettier only changes layout, so format before you commit.

## Run the tests

Needs Python 3 with Playwright (headless Chromium) and, for the Worker unit test, Node.

    python3 tests/run.py --fast           # fast subset, one or more tests per feature area (CI gate on every pull request and on main)
    python3 tests/run.py                  # whole offline suite (runs on main in CI)
    python3 tests/run.py --only stop      # only tests whose file or name contains "stop"
    python3 tests/run.py --jobs 2         # worker processes (default: CPU count, at most 4)
    python3 tests/live_smoke.py           # optional: checks the deployed Worker (needs network)

The suite mocks the Worker and Leaflet, so it never touches SEPTA or the real Worker.

How it runs: every test executes in its own child process, several at a time. Each gets its own output folder
`tests/out/<file>/<test>/` (screenshots go there, set through `SEPTA_TEST_OUT`), and the harness binds ephemeral
ports, so parallel tests never collide. `tests/out/report.txt` is the merged report.

Tagging: each `tests/test_*.py` has a module-level set naming its fast tests, for example

    FAST = {"test_boot_and_refresh", "test_ghost_filter"}

Every other `test_*` function in the file is full-only. Put a test in `FAST` when it covers a feature area the fast
set would otherwise miss or is the cheapest test of that area; keep the fast run under 90 seconds on 2 CPUs (measured: 54 tests, 74 s wall on a 2-CPU machine that was also busy with other jobs, load average about 7; it was 95 s before the fast set was trimmed). `run.py` stops with
an error if `FAST` is missing or names a test that does not exist. The Worker unit test (`tests/test_worker.mjs`) is
always in the fast set.

`tests/test_modules.py` covers the script split: a blocked `js/` file shows the error banner, `window` gains only
`SEPTA`, and file sizes and load order stay as documented. Tests that grep the source use `app_source(root)` or
`app_script(root)` from `tests/harness.py`, which read `index.html` plus the `js/` files. The split was verified as a pure move when it was made (the checker tool was retired once the code began to change).

`tests/test_data_sanity.py` guards `data/bus-network.json`: route, stop and pattern counts within 10 percent of
`tests/data_baseline.json`, file under 1.5 MB, feed end date still in the future. If a regenerated feed really changes
the counts, update the baseline in the same commit.

## Continuous integration and data refresh

`.github/workflows/ci.yml` runs lint and the Prettier check, the fast suite (which includes the Worker unit test) on every pull request and on pushes to
`main`, and the full suite on `main`. A branch with an open pull request is tested once, and a newer push cancels the older run. `.github/workflows/refresh-bus-network.yml` runs monthly (and on demand from the Actions tab): it rebuilds
`data/bus-network.json` with `tools/build_network.py` from SEPTA's GTFS zip, and only if the feed's validity dates
changed opens a pull request with the new file and the data test results. The repository setting "Allow GitHub
Actions to create and approve pull requests" must be on. Pull requests opened by the workflow do not start CI on
their own; close and reopen the pull request to run it. If a refresh pull request is still open the next run does nothing,
and the job never force-pushes over a branch that has an open pull request, so commits you add to it are safe.

GitHub switches off scheduled workflows in a repository with no activity for 60 days. The refresh workflow has a
`keepalive` job that re-enables itself through the Actions API each month (it needs no secret, only the workflow's own
token). I could not verify offline that this call resets GitHub's timer; if the monthly run stops appearing in the
Actions tab, open Actions, choose "Refresh bus network", click "Enable workflow", and then "Run workflow" once.
Merging any commit to `main` also counts as activity.

## Deploy the Worker

There is no CLI step. Open the Cloudflare dashboard, go to Workers & Pages, open `septa-proxy`, choose Edit code, paste
the whole of `worker/worker.js`, and click Deploy. Then run `python3 tests/live_smoke.py`. Pushing `main` publishes the
page itself through GitHub Pages.

## Privacy

Personal state (search center, saved places, starred routes, alert rules) lives only in your browser's `localStorage`.
We never upload or store it. What does leave your browser is the typed search text (to Nominatim for geocoding) and, when
you plan a trip, the leg coordinates described below.

Planning a trip sends data only as follows:

- Typed From and To addresses go to Nominatim (OpenStreetMap) to be geocoded, as in search. Lookups are at least a second
  apart and answers are remembered in memory for the page session.
- The coordinates of each leg's start and end go to this project's Worker, which rounds them to 4 decimals (about 10 m),
  forwards them to the OpenStreetMap-based routing service (routing.openstreetmap.de, with a User-Agent naming this
  project) and reads Indego's public station feed. The Worker stores nothing of its own beyond a short-lived edge cache of
  each answer (routes one minute). The saved Home button and saved place buttons, Use my location and the map center are
  not geocoded, but their coordinates are sent as route legs exactly like the coordinates of a typed address.
- Fallback: if the Worker cannot be reached, answers 404 (an older Worker) or answers 500, 502, 503 or 504, the page asks the
  routing service and the Indego feed directly instead. Then the routing service receives the leg coordinates unrounded, to
  5 decimals (about 1 m). A 4xx or 422 answer from the Worker, such as "no route between those points" or a place outside the
  Philadelphia region, is an answer and is never re-sent anywhere.

Nothing is stored in the page: the From and To text, the options and the drawn plan live only in the open page.
Routing requests are spaced at least 250 ms apart with at most two in flight, and the planner shows "Routing by OSRM / data
(c) OpenStreetMap contributors".

## Contributing

**Lint and format.** `npm run lint` and `npm run format` (see above) before every push.

**Run the tests.** `python3 tests/run.py --fast` for the quick gate before every push, `python3 tests/run.py` for the whole
suite before merging (several minutes). `--only <text>` narrows to matching tests; the Playwright version CI uses is
pinned in `.github/workflows/ci.yml`.

**Add a module.** Follow ARCHITECTURE.md section 14.3: a new `js/<name>.js` shaped like `js/main.js`, a `<name>:{}` entry in
the inline namespace object and a `<script src>` tag in `index.html`, the name in `FILES` in `tests/test_modules.py`, at
most 700 lines. Then run the fast suite.

**Regenerate the bus data.** The monthly workflow does it for you. By hand: `python3 tools/build_network.py --zip-url
https://www3.septa.org/developer/gtfs_public.zip`, then `python3 tests/run.py --only network_data` and `--only data_sanity`.
If route or stop counts really moved more than 10 percent, update `tests/data_baseline.json` in the same commit.

**Deploy the Worker.** See "Deploy the Worker" above: paste `worker/worker.js` into the Cloudflare dashboard editor and
deploy. No wrangler, no API token, no secrets. Run `python3 tests/live_smoke.py` afterwards.

## Known limits

- Cloudflare free plan: 100,000 Worker requests a day, and edge-cache hits count. A default page costs about 6,000 a
  day; about 16 pages open around the clock reach the cap. The page stops requesting after an hour without interaction.
  Details and the arithmetic: ARCHITECTURE.md section 2.
- The Worker runs on `*.workers.dev`, where the Cache API does nothing, so `Stops` answers are cached 60 seconds, not the
  intended day. A custom domain would fix that.
- SEPTA's API is a free hackathon service with no promises: no bus predictions (arrival times are estimates from measured
  speed), no CORS headers (hence the Worker), and occasional empty or stale feeds.
- Third-party services with their own fair-use limits: the OpenStreetMap routing service and OSM tiles, Nominatim
  (address search), Indego's public feed, Google Fonts and cdnjs. Any of them can be slow or down; the planner then
  says so rather than guessing.
- Bus schedule data (`data/bus-network.json`) is a snapshot of SEPTA's GTFS feed and expires on the feed's end date; the
  planner warns when it is within 14 days of that date or past it.
- Leave-now alerts fire only while the page is open; phones may pause background tabs. There is no push notification.
- GitHub Pages and Actions free-tier limits apply, and scheduled workflows pause after 60 days without repository
  activity (see above).
