"""WP-D: the product is named Septer (ARCHITECTURE.md 15.1): title, wordmark in the Helvetica-style stack, manifest and
icons, no leftover old name in anything a person sees, and a header that never wraps."""
import json
import pathlib
import re

from harness import Session

FAST = {
    "test_title_wordmark_and_font",
    "test_manifest_and_icons",
    "test_old_name_is_gone_from_visible_sources",
    "test_header_fits_without_wrapping",
}

OLD = "Philly Transit Live"


def test_title_wordmark_and_font(root):
    with Session(root) as s:
        s.open()
        assert s.page.title().startswith("Septer"), s.page.title()
        assert s.page.inner_text(".brand h1").strip() == "Septer"
        assert s.page.evaluate("document.querySelectorAll('.brand h1 *').length") == 0, "one clean wordmark, no spans"
        css = s.page.evaluate(
            "(() => { const c = getComputedStyle(document.querySelector('.brand h1'));"
            " return [c.fontFamily, c.fontWeight, c.letterSpacing, c.textTransform]; })()"
        )
        family = [f.strip().strip("\"'") for f in css[0].split(",")]
        assert family[:3] == ["Helvetica Neue", "Helvetica", "Arial"], css
        assert int(css[1]) >= 700, css
        assert css[2] in ("normal", "0px"), css
        assert css[3] == "none", css
        for name in ("description", "application-name", "apple-mobile-web-app-title"):
            assert "Septer" in s.page.get_attribute(f"meta[name={name}]", "content"), name
        for prop in ("og:title", "og:description"):
            assert s.page.get_attribute(f'meta[property="{prop}"]', "content"), prop
        for name in ("twitter:title", "twitter:description"):
            assert s.page.get_attribute(f'meta[name="{name}"]', "content"), name
        assert "Septer" in s.page.get_attribute('meta[property="og:title"]', "content")
        assert s.page.query_selector_all('meta[name="theme-color"]').__len__() == 2  # light and dark
        assert not s.console_errors, s.console_errors


def test_manifest_and_icons(root):
    root = pathlib.Path(root)
    with Session(root) as s:
        s.open()
        link = s.page.query_selector('link[rel="manifest"]')
        href = link.get_attribute("href") if link else None
        icon_links = s.page.evaluate("[...document.querySelectorAll('link[rel~=icon],link[rel=apple-touch-icon]')].map(l => l.getAttribute('href'))")
    assert href, "manifest link missing"
    data = json.loads((root / href).read_text())
    assert data["name"] == "Septer" and data["short_name"] == "Septer", data
    assert data["start_url"] == "./" and data["display"] == "standalone", data
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", data["theme_color"]) and re.fullmatch(r"#[0-9a-fA-F]{6}", data["background_color"])
    sizes = {(i["sizes"], i.get("purpose")) for i in data["icons"]}
    assert ("192x192", "any") in sizes and ("512x512", "any") in sizes and ("512x512", "maskable") in sizes, sizes
    for icon in data["icons"]:
        assert (root / icon["src"]).is_file(), icon
    assert "icons/apple-touch-icon.png" in icon_links and "icons/favicon.svg" in icon_links, icon_links
    for link in icon_links:
        assert (root / link).is_file(), link
    png = (root / "icons/apple-touch-icon.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and int.from_bytes(png[16:20], "big") == 180 == int.from_bytes(png[20:24], "big")
    assert not (root / "sw.js").exists() and "serviceWorker" not in "".join(p.read_text() for p in (root / "js").glob("*.js")), "no service worker"


def test_old_name_is_gone_from_visible_sources(root):
    root = pathlib.Path(root)
    files = [root / "index.html", root / "README.md", root / "manifest.webmanifest"]
    files += sorted((root / "js").glob("*.js")) + sorted((root / "css").glob("*.css"))
    hits = [f.name for f in files if OLD.lower() in f.read_text().lower()]
    assert not hits, hits


def test_header_fits_without_wrapping(root):
    for width in (320, 390, 1280):
        with Session(root, viewport=(width, 800)) as s:
            s.open()
            s.page.wait_for_selector(".brand h1")
            m = s.page.evaluate(
                "(() => { const h = document.querySelector('.brand h1'), b = document.querySelector('.brand');"
                " const fs = parseFloat(getComputedStyle(h).fontSize);"
                " const r = document.createRange(); r.selectNodeContents(h);"
                " return {lines: r.getClientRects().length, h: h.getBoundingClientRect().height, fs: fs,"
                " over: h.scrollWidth > h.clientWidth, bover: b.scrollWidth > b.clientWidth,"
                " page: document.documentElement.scrollWidth > innerWidth}; })()"
            )
            assert m["lines"] == 1 and m["h"] <= m["fs"] * 1.3 and not m["over"] and not m["bover"] and not m["page"], (width, m)
