# Philly Transit Live

A live map of SEPTA buses, trolleys and Regional Rail trains around any address in Philadelphia, with route alerts,
shareable stop links, stop boards with computed ETAs, and "leave now" alerts. Live at
https://tpgordon8.github.io/philly-transit-live/

## How data flows

The page is a static `index.html` plus plain script files under `js/` (no build step), served by GitHub Pages. It asks a small Cloudflare Worker (`worker/worker.js`)
for SEPTA's public feeds, because SEPTA's API sends no CORS headers; the Worker allowlists a handful of endpoints and
caches them briefly. Details are in [ARCHITECTURE.md](ARCHITECTURE.md). By default the page shows only buses within 0.5 mi, which also skips the Regional Rail request and roughly halves Worker traffic.

## Code layout

`index.html` holds the markup, the styles and a short loader. The application code is eight classic scripts in `js/`,
loaded with ordinary `<script src>` tags in dependency order: `util` (helpers, storage, shared state), `feed` (vehicle
feed, ghost filter, idle pause, refresh), `ui` (map, markers, detail panel, places), `stops` (stop links, stop board,
ETA), `alerts` (service alerts, leave-now rules), `planner` (trip planner core), `trip` (trip planner interface) and
`main` (test hook and start). Each file adds only `window.SEPTA.<name>`. If a file fails to load, a red banner at the
top of the page names it. How the files fit together and how to add one: [ARCHITECTURE.md](ARCHITECTURE.md) section 14.

## Run the tests

Needs Python 3 with Playwright (headless Chromium) and, for the Worker unit test, Node.

    python3 tests/run.py --fast           # fast subset, one or more tests per feature area (CI gate on every push)
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
set would otherwise miss or is the cheapest test of that area; keep the fast run near 90 seconds. `run.py` stops with
an error if `FAST` is missing or names a test that does not exist. The Worker unit test (`tests/test_worker.mjs`) is
always in the fast set.

`tests/test_modules.py` covers the script split: a blocked `js/` file shows the error banner, `window` gains only
`SEPTA`, and file sizes and load order stay as documented. Tests that grep the source use `app_source(root)` or
`app_script(root)` from `tests/harness.py`, which read `index.html` plus the `js/` files. `python3 tools/check_split.py`
compares the `js/` files with the last single-file `index.html` (commit `cc22b7e`) and fails unless the move was pure.

`tests/test_data_sanity.py` guards `data/bus-network.json`: route, stop and pattern counts within 10 percent of
`tests/data_baseline.json`, file under 1.5 MB, feed end date still in the future. If a regenerated feed really changes
the counts, update the baseline in the same commit.

## Continuous integration and data refresh

`.github/workflows/ci.yml` runs the Worker test and the fast suite on every push and pull request, and the full suite
on `main`. `.github/workflows/refresh-bus-network.yml` runs monthly (and on demand from the Actions tab): it rebuilds
`data/bus-network.json` with `tools/build_network.py` from SEPTA's GTFS zip, and only if the feed's validity dates
changed opens a pull request with the new file and the data test results. The repository setting "Allow GitHub
Actions to create and approve pull requests" must be on. Pull requests opened by the workflow do not start CI on
their own; close and reopen the pull request to run it.

## Deploy the Worker

There is no CLI step. Open the Cloudflare dashboard, go to Workers & Pages, open `septa-proxy`, choose Edit code, paste
the whole of `worker/worker.js`, and click Deploy. Then run `python3 tests/live_smoke.py`. Pushing `main` publishes the
page itself through GitHub Pages.

## Privacy

Personal state (search center, saved places, starred routes, alert rules) lives only in your browser's `localStorage`.
It is never sent to the Worker or anywhere else. The one exception is an address you type into search, which goes to
Nominatim (OpenStreetMap) to be geocoded.

Planning a trip sends data only as follows:

- Typed From and To addresses go to Nominatim (OpenStreetMap) to be geocoded, as in search. Lookups are at least a second
  apart and answers are remembered in memory for the page session.
- The coordinates of each leg's start and end go to this project's Worker, which rounds them to 4 decimals (about 10 m),
  forwards them to the OpenStreetMap-based routing service (routing.openstreetmap.de, with a User-Agent naming this
  project) and reads Indego's public station feed. The Worker stores nothing of its own beyond a short-lived edge cache of
  each answer (routes one minute). The saved Home button and saved place buttons, Use my location and the map center are
  not geocoded, but their coordinates are sent as route legs exactly like the coordinates of a typed address.
- Fallback: if the Worker cannot be reached, answers 404 (an older Worker) or answers 502, 503 or 504, the page asks the
  routing service and the Indego feed directly instead. Then the routing service receives the leg coordinates unrounded, to
  5 decimals (about 1 m). A 4xx or 422 answer from the Worker, such as "no route between those points" or a place outside the
  Philadelphia region, is an answer and is never re-sent anywhere.

Nothing is stored in the page: the From and To text, the options and the drawn plan live only in the open page.
Routing requests are spaced at least 250 ms apart with at most two in flight, and the planner shows "Routing by OSRM / data
(c) OpenStreetMap contributors".
