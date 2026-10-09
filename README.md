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

    python3 tests/run.py                  # whole offline suite, about a few minutes
    python3 tests/run.py --only stop      # only tests whose file or name contains "stop"
    python3 tests/live_smoke.py           # optional: checks the deployed Worker (needs network)

The suite mocks the Worker and Leaflet, so it never touches SEPTA or the real Worker.

## Deploy the Worker

There is no CLI step. Open the Cloudflare dashboard, go to Workers & Pages, open `septa-proxy`, choose Edit code, paste
the whole of `worker/worker.js`, and click Deploy. Then run `python3 tests/live_smoke.py`. Pushing `main` publishes the
page itself through GitHub Pages.

## Privacy

Personal state (search center, saved places, starred routes, alert rules) lives only in your browser's `localStorage`.
It is never sent to the Worker or anywhere else. The one exception is an address you type into search, which goes to
Nominatim (OpenStreetMap) to be geocoded.

Planning a trip sends the start and end points of each leg to this project's Worker, which forwards them (rounded to
4 decimals, about 10 m) to an OpenStreetMap-based routing service, and reads Indego's public station feed through the
Worker. The Worker stores nothing of its own beyond a short-lived edge cache of each answer (routes one minute). Nothing
is stored in the page: the From and To text, the options and the drawn plan live only in the open page. If the Worker is
down, the page falls back once to asking those two services directly.
Typed addresses are geocoded by Nominatim, as in search.
