#!/usr/bin/env python3
"""Build data/bus-network.json (ARCHITECTURE.md section 12.2) from SEPTA's bus GTFS.

Usage (Python 3 standard library only; about 30 s; stop_times.txt is streamed):

    python3 -I tools/build_network.py --gtfs-dir /path/to/extracted/google_bus
    python3 -I tools/build_network.py --zip-url https://www3.septa.org/developer/gtfs_public.zip
    python3 -I tools/build_network.py --zip gtfs_public.zip        # outer zip, or google_bus.zip itself

--zip-url / --zip accept the outer gtfs_public.zip (containing google_bus.zip) or the inner zip directly. Only the
text files this script needs are extracted, into a fresh temp directory, with a size cap per file; nothing from the
download is executed or imported. Output goes to data/bus-network.json (override with --out).

Selection: service ids active on a typical Wednesday (calendar.txt plus calendar_dates.txt) inside the feed window;
the date used is recorded as feed.sampleDate (default: the Wednesday nearest the middle of the window, overridable
with --sample-date YYYYMMDD).
"""
import argparse
import collections
import csv
import datetime
import io
import json
import os
import statistics
import sys
import tempfile
import urllib.request
import zipfile

DEFAULT_GTFS = "/tmp/claude-0/gtfs/bus"
NEEDED = ["routes.txt", "trips.txt", "stop_times.txt", "stops.txt", "calendar.txt", "calendar_dates.txt", "feed_info.txt"]
MAX_MEMBER = 400 * 1024 * 1024
KINDS = {"3": "bus", "0": "trolley"}
MIN_SHARE, MAX_PATTERNS = 0.15, 3
MID_FROM, MID_TO = 10 * 60, 15 * 60


def parse_time(s):
    """HH:MM:SS (HH may exceed 23) to minutes as float; None if blank/bad."""
    try:
        h, m, sec = s.strip().split(":")
        return int(h) * 60 + int(m) + int(sec) / 60.0
    except (ValueError, AttributeError):
        return None


def rows(gtfs, name):
    with open(os.path.join(gtfs, name), newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def safe_extract(zf, dest):
    names = {i.filename: i for i in zf.infolist()}
    for want in NEEDED:
        info = names.get(want)
        if info is None:
            raise SystemExit(f"zip is missing {want}")
        if info.file_size > MAX_MEMBER:
            raise SystemExit(f"{want} is implausibly large ({info.file_size} bytes)")
        written = 0
        with zf.open(info) as src, open(os.path.join(dest, want), "wb") as out:  # fixed names: no path traversal
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_MEMBER:
                    raise SystemExit(f"{want} exceeded size cap")
                out.write(chunk)


def open_zip_to(dest, path):
    with zipfile.ZipFile(path) as z:
        if "google_bus.zip" in z.namelist() and "routes.txt" not in z.namelist():
            inner = zipfile.ZipFile(io.BytesIO(z.read("google_bus.zip")))
            with inner:
                safe_extract(inner, dest)
        else:
            safe_extract(z, dest)


def active_services(gtfs, date):
    wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][
        datetime.datetime.strptime(date, "%Y%m%d").weekday()]
    act = set()
    for r in rows(gtfs, "calendar.txt"):
        if r[wd] == "1" and r["start_date"] <= date <= r["end_date"]:
            act.add(r["service_id"])
    for r in rows(gtfs, "calendar_dates.txt"):
        if r["date"] == date:
            (act.add if r["exception_type"] == "1" else act.discard)(r["service_id"])
    return act


def pick_sample_date(start, end):
    s = datetime.datetime.strptime(start, "%Y%m%d").date()
    e = datetime.datetime.strptime(end, "%Y%m%d").date()
    mid = s + (e - s) / 2
    mid += datetime.timedelta(days=(2 - mid.weekday() + 3) % 7 - 3)  # nearest Wednesday
    return mid.strftime("%Y%m%d")


def build(gtfs, sample_date=None, log=print):
    fi = next(iter(rows(gtfs, "feed_info.txt")))
    start, end = fi["feed_start_date"], fi["feed_end_date"]
    sample = sample_date or pick_sample_date(start, end)
    if not start <= sample <= end:
        raise SystemExit("sample date outside feed window")
    services = active_services(gtfs, sample)
    log(f"feed {start}..{end}, sample date {sample}, {len(services)} active services")

    routes, by_short = {}, collections.defaultdict(set)
    for r in rows(gtfs, "routes.txt"):
        if r["route_type"] in KINDS:
            short = r["route_short_name"].strip()
            if not short:
                log(f"WARN empty route_short_name for route_id {r['route_id']}")
                continue
            routes[r["route_id"]] = (short, KINDS[r["route_type"]])
            by_short[short].add(r["route_id"])
    for short, ids in sorted(by_short.items()):
        if len(ids) > 1:
            log(f"WARN route_short_name {short!r} shared by route_ids {sorted(ids)}")

    trips = {}  # trip_id -> (short, kind, dir, headsign)
    for t in rows(gtfs, "trips.txt"):
        if t["service_id"] in services and t["route_id"] in routes:
            short, kind = routes[t["route_id"]]
            trips[t["trip_id"]] = (short, kind, int(t["direction_id"] or 0), t["trip_headsign"])
    log(f"{len(trips)} weekday trips on bus/trolley routes")

    # stream stop_times, keep only those trips
    st = collections.defaultdict(list)
    with open(os.path.join(gtfs, "stop_times.txt"), newline="", encoding="utf-8-sig") as f:
        rd = csv.reader(f)
        h = next(rd)
        ix = {n: i for i, n in enumerate(h)}
        it, ia, id_, iss, iq = ix["trip_id"], ix["arrival_time"], ix["departure_time"], ix["stop_id"], ix["stop_sequence"]
        for row in rd:
            tid = row[it]
            if tid in trips:
                a, d = parse_time(row[ia]), parse_time(row[id_])
                if a is None:
                    a = d
                if d is None:
                    d = a
                if a is None:
                    continue
                st[tid].append((int(row[iq]), row[iss], a, d))

    stops_all = {}
    for s in rows(gtfs, "stops.txt"):
        try:
            stops_all[s["stop_id"]] = (round(float(s["stop_lat"]), 5), round(float(s["stop_lon"]), 5), s["stop_name"])
        except ValueError:
            pass  # empty coordinates

    # group trips into route-direction -> stop sequence -> trips
    groups = collections.defaultdict(lambda: collections.defaultdict(list))
    kinds = {}
    totals = collections.Counter()
    for tid, seq in st.items():
        seq.sort()
        short, kind, d, head = trips[tid]
        key = tuple(s[1] for s in seq)
        if len(key) < 2:
            continue
        kinds[short] = kind
        totals[(short, d)] += 1
        groups[(short, d)][key].append((seq[0][3], head, seq))

    dropped_coords = 0
    patterns, used = [], set()
    for (short, d) in sorted(groups):
        cands = sorted(groups[(short, d)].items(), key=lambda kv: -len(kv[1]))
        total = totals[(short, d)]
        kept = []
        for key, tl in cands:
            if any(s not in stops_all for s in key):
                dropped_coords += 1
                continue
            if not kept or (len(tl) / total >= MIN_SHARE and len(kept) < MAX_PATTERNS):
                kept.append((key, tl))
        for n, (key, tl) in enumerate(kept, 1):
            mid = [t for t in tl if MID_FROM <= t[0] <= MID_TO]
            use = mid if len(mid) >= 3 else tl
            cols = zip(*[[s[2] - t[2][0][3] for s in t[2]] for t in use])
            mins, prev = [], 0.0
            for col in cols:
                v = max(round(statistics.median(col) * 2) / 2, prev)
                mins.append(int(v) if v == int(v) else v)
                prev = v
            mins[0] = 0
            head = collections.Counter(t[1] for t in tl).most_common(1)[0][0]
            patterns.append({"id": f"{short}-{d}-{n}", "route": short, "kind": kinds[short], "dir": d, "head": head,
                             "stops": list(key), "mins": mins,
                             "hw": max(1, round(300 / len(mid))) if mid else None, "trips": len(tl)})
            used.update(key)
    stops = {s: list(stops_all[s]) for s in sorted(used, key=lambda x: (len(x), x))}
    log(f"dropped {dropped_coords} candidate patterns (stop without coordinates)")
    return {"v": 1, "generated": datetime.date.today().isoformat(),
            "feed": {"start": start, "end": end, "sampleDate": sample},
            "stops": stops, "patterns": patterns}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gtfs-dir", default=DEFAULT_GTFS)
    ap.add_argument("--zip", help="local gtfs_public.zip (or google_bus.zip)")
    ap.add_argument("--zip-url", help="download gtfs_public.zip from this URL")
    ap.add_argument("--sample-date", help="YYYYMMDD Wednesday inside the feed window")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "bus-network.json"))
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        gtfs = a.gtfs_dir
        if a.zip or a.zip_url:
            zpath = a.zip
            if a.zip_url:
                zpath = os.path.join(tmp, "dl.zip")
                with urllib.request.urlopen(a.zip_url, timeout=120) as r, open(zpath, "wb") as out:
                    while True:
                        c = r.read(1 << 20)
                        if not c:
                            break
                        out.write(c)
            gtfs = os.path.join(tmp, "gtfs")
            os.mkdir(gtfs)
            open_zip_to(gtfs, zpath)
        data = build(gtfs, a.sample_date, log=lambda m: print(m, file=sys.stderr))
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {out}: {os.path.getsize(out)} bytes, {len(data['patterns'])} patterns, {len(data['stops'])} stops", file=sys.stderr)


if __name__ == "__main__":
    main()
