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

Stdlib only. tests/test_stability.py runs the same check, so a forgotten stamp fails the fast suite in CI.
"""
import argparse
import hashlib
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(HERE.parent))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    index = pathlib.Path(args.root) / "index.html"
    html = index.read_text()
    token = content_hash(args.root)
    new = stamp(html, token)
    if args.check:
        if new != html:
            print(f"index.html is not stamped with ?v={token}; run: python3 tests/stamp_version.py", file=sys.stderr)
            return 1
        print(f"index.html is stamped with ?v={token}")
        return 0
    if new != html:
        index.write_text(new)
    print(f"index.html stamped with ?v={token}" + ("" if new != html else " (already current)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
