"""Run the offline test suite against a checkout, in parallel worker processes.

    python3 tests/run.py                       # every test (the full suite)
    python3 tests/run.py --fast                # the fast subset, one or more tests per feature area (CI gate)
    python3 tests/run.py --root /path/to/wt    # a feature-branch worktree
    python3 tests/run.py --only my_routes      # only test files / names containing this text
    python3 tests/run.py --jobs 4              # worker processes (default: CPU count, at most 4)

Tagging: each tests/test_*.py defines a module-level set FAST naming its fast tests. Every other test_* function in
the file is "full" (it runs only without --fast). The runner refuses to start if FAST names a test that does not
exist, so a rename cannot silently drop a test from the fast set. See README.md.

Each test runs in its own child process (`--run-one`) with SEPTA_TEST_OUT=tests/out/<file>/<test>, so screenshots and
any other output never collide between parallel tests. Prints PASS/FAIL per test in a stable order, writes the merged
tests/out/report.txt as evidence, exits 1 if anything failed.
"""
import argparse
import concurrent.futures
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
WORKER_ID = "test_worker::node test_worker.mjs"
TIMINGS = HERE / "out" / "timings.json"


def load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover():
    """Return [(test_id, is_fast)] in stable order, validating the FAST tags."""
    tests = []
    for path in sorted(HERE.glob("test_*.py")):
        mod = load_module(path)
        names = sorted(n for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n)))
        fast = getattr(mod, "FAST", None)
        if fast is None:
            raise SystemExit(f"{path.name} has no FAST set (see README: Run the tests)")
        unknown = sorted(set(fast) - set(names))
        if unknown:
            raise SystemExit(f"{path.name}: FAST names tests that do not exist: {unknown}")
        tests += [(f"{path.stem}::{n}", n in fast) for n in names]
    tests.append((WORKER_ID, True))
    return tests


def run_one(test_id, root):
    """Child process: run a single test, print one JSON result line."""
    t0 = time.time()
    res = {"id": test_id, "status": "PASS", "msg": ""}
    try:
        if test_id == WORKER_ID:
            node = shutil.which("node")
            if not node:
                res.update(status="SKIP", msg="node is not installed; the Worker unit test was not run")
            else:
                r = subprocess.run([node, str(HERE / "test_worker.mjs")], capture_output=True, text=True, timeout=120)
                if r.returncode != 0:
                    detail = (r.stderr.strip() or r.stdout.strip() or "no output").splitlines()
                    res.update(status="FAIL", msg=f"exit {r.returncode}: {detail[0][:300] if detail else ''}")
        else:
            stem, name = test_id.split("::")
            getattr(load_module(HERE / f"{stem}.py"), name)(root)
    except Exception as e:  # noqa: BLE001
        msg = (str(e) or e.__class__.__name__).splitlines()[0][:300]
        if not isinstance(e, AssertionError):
            msg += "\n      " + traceback.format_exc().strip().splitlines()[-1][:300]
        res.update(status="FAIL", msg=msg)
    res["secs"] = round(time.time() - t0, 1)
    print("@@RESULT@@" + json.dumps(res), flush=True)


def spawn(test_id, root):
    stem = test_id.split("::")[0]
    safe = test_id.split("::")[-1].replace(" ", "_")
    out = HERE / "out" / stem / safe
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SEPTA_TEST_OUT=str(out))
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, str(HERE / "run.py"), "--root", root, "--run-one", test_id],
                           capture_output=True, text=True, env=env, timeout=900)
        for line in p.stdout.splitlines():
            if line.startswith("@@RESULT@@"):
                return json.loads(line[len("@@RESULT@@"):])
        tail = (p.stderr.strip() or p.stdout.strip() or "no output").splitlines()
        return {"id": test_id, "status": "FAIL", "secs": round(time.time() - t0, 1),
                "msg": f"worker process exited {p.returncode} without a result: {tail[-1][:300] if tail else ''}"}
    except subprocess.TimeoutExpired:
        return {"id": test_id, "status": "FAIL", "secs": round(time.time() - t0, 1), "msg": "timed out after 900 s"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HERE.parent))
    ap.add_argument("--only", default="")
    ap.add_argument("--fast", action="store_true", help="run only the tests tagged fast")
    ap.add_argument("--jobs", type=int, default=min(os.cpu_count() or 2, 4))
    ap.add_argument("--run-one", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.run_one:
        return run_one(args.run_one, args.root)

    selected = []
    for tid, fast in discover():
        stem = tid.split("::")[0]
        if args.fast and not fast:
            continue
        if args.only and args.only not in tid.split("::")[1] and args.only not in stem:
            continue
        selected.append(tid)
    out = HERE / "out"
    for stale in out.glob("test_*"):
        shutil.rmtree(stale, ignore_errors=True)
    out.mkdir(exist_ok=True)
    for stale in out.glob("*.png"):  # screenshots from before per-test folders
        stale.unlink()
    try:
        known = json.loads(TIMINGS.read_text())
    except (OSError, ValueError):
        known = {}
    order = sorted(selected, key=lambda t: -known.get(t, 5))  # longest first keeps the pool busy to the end
    t0, results = time.time(), {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futs = {pool.submit(spawn, t, args.root): t for t in order}
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            results[r["id"]] = r
            print(f"{r['status']:<5} {r['id']}  ({r['secs']}s)" + (f"  {r['msg']}" if r["status"] != "PASS" else ""), flush=True)
    lines, failed = [], 0
    for tid in selected:  # stable order for the merged report
        r = results[tid]
        failed += r["status"] == "FAIL"
        lines.append(f"{r['status']:<5} {tid}  " + (f"({r['secs']}s)" if r["status"] == "PASS" else r["msg"]))
    npass = sum(r["status"] == "PASS" for r in results.values())
    nskip = sum(r["status"] == "SKIP" for r in results.values())
    mode = "fast" if args.fast else "full"
    report = "\n".join(lines) + f"\n\n{npass} passed, {failed} failed, {nskip} skipped  ({mode}, {args.jobs} jobs, {time.time() - t0:.0f}s wall, root: {args.root})\n"
    (out / "report.txt").write_text(report)
    if not args.only:
        known.update({k: v["secs"] for k, v in results.items()})
        TIMINGS.write_text(json.dumps(known))
    print("\n" + report)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
