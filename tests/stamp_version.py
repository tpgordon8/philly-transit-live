#!/usr/bin/env python3
"""Stamp index.html with a content hash so a deploy is much less likely to serve a mix of old and new files.

GitHub Pages serves js/, css/ and data/ with max-age=600, so right after a deploy a browser can hold an old file next to a
new one. Every local script and stylesheet URL in index.html therefore carries ?v=<token>, where the token is the first
10 hex digits of a SHA-256 over every file in js/, css/ and data/ (paths and bytes, sorted). The token changes only when one
of those files changes, so an untouched site keeps its cache. js/routing.js copies the token from its own script tag onto
the URL of data/bus-network.json. This avoids a mix for visitors who load a fresh index.html; a visitor whose browser still
holds an old index.html (it is not versioned) keeps using the old, matching set until that copy expires.

    python3 tests/stamp_version.py            # rewrite the tokens in index.html (idempotent)
    python3 tests/stamp_version.py --check    # exit 1 when index.html is not stamped with the current token
    python3 tests/stamp_version.py --root DIR # another checkout

The same run also rewrites the block between the STAMP markers in sw.js (the service worker): its cache name VERSION (a hash of the
token, the manifest, the icons and index.html without its tokens), the SHELL list to pre-cache (index.html's local scripts and
stylesheets with their tokens, manifest, icons, the bus network file) and CROSS (third-party scripts such as Leaflet).

Stdlib only. tests/test_stability.py runs the same check, so a forgotten stamp fails the fast suite in CI.
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
# <script src="js/x.js"> and <link rel="stylesheet" href="css/x.css">, with or without an existing ?v=token.
TAG = re.compile(r'((?:<script src|<link rel="stylesheet" href)="(?:js|css)/[^"?]+)(?:\?v=([0-9a-f]+))?(")')
TOKEN_LEN = 10


def content_hash(root):
    root = pathlib.Path(root)
    h = hashlib.sha256()
    files = sorted(
        p for d in ("js", "css", "data") for p in (root / d).iterdir() if p.is_file() and p.suffix in (".js", ".css", ".json")
    )
    for p in files:
        h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:TOKEN_LEN]


def stamped(html):
    """Tokens found on the local tags: list of (url, token or None)."""
    return [(m.group(1).split('"')[-1], m.group(2)) for m in TAG.finditer(html)]


def stamp(html, token):
    return TAG.sub(lambda m: f"{m.group(1)}?v={token}{m.group(3)}", html)


SW_BLOCK = re.compile(r"/\* STAMP:begin \*/\n.*?/\* STAMP:end \*/", re.S)
LOCAL_URL = re.compile(r'(?:<script src|<link rel="stylesheet" href)="((?:js|css)/[^"]+)"')
CROSS_URL = re.compile(r'<script src="(https://[^"]+\.js)"')


def sw_block(root, html):
    """The text for sw.js between the STAMP markers, derived from the already-stamped index.html."""
    root = pathlib.Path(root)
    token = content_hash(root)
    h = hashlib.sha256(token.encode())
    h.update(re.sub(r"\?v=[0-9a-f]+", "", html).encode())
    extra = [root / "manifest.webmanifest"] + sorted(p for p in (root / "icons").iterdir() if p.is_file())
    for p in extra:
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    shell = ["./"] + LOCAL_URL.findall(html) + ["manifest.webmanifest"] + [f"icons/{p.name}" for p in extra[1:]]
    shell.append(f"data/bus-network.json?v={token}")
    cross = CROSS_URL.findall(html)
    return (
        "/* STAMP:begin */\n"
        f"var VERSION = '{h.hexdigest()[:TOKEN_LEN]}';\n"
        f"var SHELL = {json.dumps(shell)};\n"
        f"var CROSS = {json.dumps(cross)};\n"
        "/* STAMP:end */"
    )


def stamp_sw(root, html):
    """sw.js text with the block refreshed (None when the checkout has no sw.js)."""
    sw = pathlib.Path(root) / "sw.js"
    if not sw.exists():
        return None, None
    old = sw.read_text()
    return sw, SW_BLOCK.sub(lambda m: sw_block(root, html), old, count=1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(HERE.parent))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    index = pathlib.Path(args.root) / "index.html"
    html = index.read_text()
    token = content_hash(args.root)
    new = stamp(html, token)
    sw, sw_new = stamp_sw(args.root, new)
    if args.check:
        if new != html:
            print(f"index.html is not stamped with ?v={token}; run: python3 tests/stamp_version.py", file=sys.stderr)
            return 1
        if sw is not None and sw_new != sw.read_text():
            print("sw.js is not stamped with the current cache version; run: python3 tests/stamp_version.py", file=sys.stderr)
            return 1
        print(f"index.html is stamped with ?v={token}")
        return 0
    if new != html:
        index.write_text(new)
    if sw is not None and sw_new != sw.read_text():
        sw.write_text(sw_new)
    print(f"index.html stamped with ?v={token}" + ("" if new != html else " (already current)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
