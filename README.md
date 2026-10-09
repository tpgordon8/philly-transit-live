# Philly Transit Live

A live map of SEPTA buses, trolleys and Regional Rail trains around any address in Philadelphia, with route alerts,
shareable stop links, stop boards with computed ETAs, and "leave now" alerts. Live at
https://tpgordon8.github.io/philly-transit-live/

## How data flows

The page is a single static `index.html` served by GitHub Pages. It asks a small Cloudflare Worker (`worker/worker.js`)
for SEPTA's public feeds, because SEPTA's API sends no CORS headers; the Worker allowlists a handful of endpoints and
caches them briefly. Details are in [ARCHITECTURE.md](ARCHITECTURE.md). By default the page shows only buses within 0.5 mi, which also skips the Regional Rail request and roughly halves Worker traffic.

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

Planning a trip sends the start and end points of each leg to an OpenStreetMap-based routing service and reads Indego's
public station feed. Nothing is stored: the From and To text, the options and the drawn plan live only in the open page.
Typed addresses are geocoded by Nominatim, as in search.
