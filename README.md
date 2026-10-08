# Philly Transit Live

A live map of SEPTA buses, trolleys and Regional Rail trains around any address in Philadelphia, with route alerts,
shareable stop links, stop boards with computed ETAs, and "leave now" alerts. Live at
https://tpgordon8.github.io/philly-transit-live/

## How data flows

The page is a single static `index.html` served by GitHub Pages. It asks a small Cloudflare Worker (`worker/worker.js`)
for SEPTA's public feeds, because SEPTA's API sends no CORS headers; the Worker allowlists a handful of endpoints and
caches them briefly. Details are in [ARCHITECTURE.md](ARCHITECTURE.md).

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
