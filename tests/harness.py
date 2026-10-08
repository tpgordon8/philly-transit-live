"""Hermetic browser harness for Philly Transit Live.

Serves a checkout of the repo over http://127.0.0.1:<port>, mocks the Cloudflare Worker from tests/fixtures,
serves Leaflet from tests/vendor, answers tile and font requests with stubs, and records every request that
isn't expected (a direct call to api.septa.org, for example, is a failure).

Usage in a test:
    with Session(root="/path/to/checkout") as s:
        s.open()
        s.wait_live()
        ...
"""
import base64
import functools
import http.server
import json
import pathlib
import threading

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
FIX = HERE / "fixtures"
LEAFLET = HERE / "vendor" / "leaflet.min.js"
WORKER_HOST = "septa-proxy.tpgordon8.workers.dev"
CORS = {"access-control-allow-origin": "*"}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class Worker:
    """Mock of the Cloudflare Worker. mode: ok | http502 | abort. data: endpoint name -> python object."""

    def __init__(self):
        self.mode = "ok"
        self.data = {n: json.loads((FIX / f"{n}.json").read_text()) for n in ("TransitView", "TrainView", "Alerts", "Stops")}
        self.hits = []


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Session:
    def __init__(self, root=None, viewport=(1280, 800), geolocation=None, extra_routes=None, init_scripts=()):
        self.root = pathlib.Path(root or HERE.parent)
        self.viewport = {"width": viewport[0], "height": viewport[1]}
        self.geolocation = geolocation
        self.extra_routes = extra_routes or {}  # substring -> (status, content_type, body)
        self.init_scripts = list(init_scripts)
        self.worker = Worker()
        self.console_errors = []
        self.unexpected = []
        self.septa_direct = []

    def __enter__(self):
        handler = functools.partial(_Quiet, directory=str(self.root))
        self._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self._srv.server_address[1]}"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        self.ctx = self.browser.new_context(viewport=self.viewport)
        if self.geolocation:
            self.ctx.grant_permissions(["geolocation"])
            self.ctx.set_geolocation(self.geolocation)
        self.page = self.ctx.new_page()
        self.page.on("console", lambda m: self.console_errors.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.console_errors.append("pageerror: " + str(e)))
        self.page.route("**/*", self._route)
        for js in self.init_scripts:
            self.page.add_init_script(js)
        self.page.clock.install()
        return self

    def __exit__(self, *exc):
        try:
            self.browser.close()
            self._pw.stop()
        finally:
            self._srv.shutdown()

    def _route(self, route):
        url = route.request.url
        if "api.septa.org" in url or "www3.septa.org" in url:
            self.septa_direct.append(url)
            return route.abort("failed")
        if WORKER_HOST in url:
            tail = url.split(WORKER_HOST + "/", 1)[1]
            name = tail.split("?", 1)[0].strip("/")
            self.worker.hits.append(tail.strip("/") if name == "Stops" else name)
            if name == "Stops":  # data["Stops"] maps route id -> stop list; unknown routes return [] like SEPTA
                if self.worker.mode == "abort":
                    return route.abort("failed")
                from urllib.parse import parse_qs, urlparse
                r = (parse_qs(urlparse(url).query).get("route") or [""])[0]
                return route.fulfill(status=200, headers=CORS, content_type="application/json",
                                     body=json.dumps(self.worker.data["Stops"].get(r, [])))
            if self.worker.mode == "abort":
                return route.abort("failed")
            if self.worker.mode == "http502" or name not in self.worker.data:
                return route.fulfill(status=502, headers=CORS, content_type="application/json", body='{"error":"mock"}')
            return route.fulfill(status=200, headers=CORS, content_type="application/json",
                                 body=json.dumps(self.worker.data[name]))
        for needle, (status, ctype, body) in self.extra_routes.items():
            if needle in url:
                return route.fulfill(status=status, headers=CORS, content_type=ctype, body=body)
        if "cdnjs.cloudflare.com/ajax/libs/leaflet" in url and url.endswith(".js"):
            return route.fulfill(status=200, content_type="application/javascript", body=LEAFLET.read_bytes())
        if "tile.openstreetmap.org" in url:
            return route.fulfill(status=200, content_type="image/png", body=PNG)
        if "fonts.googleapis.com" in url:
            return route.fulfill(status=200, content_type="text/css", body="")
        if "fonts.gstatic.com" in url:
            return route.abort("failed")
        if url.startswith(self.base) or url.startswith(("about:", "data:", "blob:")):
            return route.continue_()
        self.unexpected.append(url)
        return route.abort("failed")

    # ---- helpers ----
    def open(self, path="index.html", hash_=""):
        self.page.goto(f"{self.base}/{path}{hash_}")
        return self

    def wait_live(self, timeout=10000):
        self.page.wait_for_function(
            "document.querySelector('#statusText') && /Live/.test(document.querySelector('#statusText').textContent)",
            timeout=timeout,
        )

    def tick(self, ms):
        """Advance the page's fake clock, then give mocked network responses real time to land."""
        self.page.clock.run_for(ms)
        self.page.wait_for_timeout(400)

    def markers(self):
        return self.page.evaluate("document.querySelectorAll('.veh-wrap').length")

    def shot(self, name):
        out = HERE / "out"
        out.mkdir(exist_ok=True)
        self.page.screenshot(path=str(out / f"{name}.png"))
        return str(out / f"{name}.png")
