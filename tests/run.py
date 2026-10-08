"""Run every tests/test_*.py against a checkout.

    python3 tests/run.py                       # this checkout
    python3 tests/run.py --root /path/to/wt    # a feature-branch worktree
    python3 tests/run.py --only my_routes      # only test files / names containing this text

Prints PASS/FAIL per test, writes tests/out/report.txt as evidence, exits 1 if anything failed.
"""
import argparse
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HERE.parent))
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    lines, failed = [], 0
    for path in sorted(HERE.glob("test_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            if args.only and args.only not in name and args.only not in path.stem:
                continue
            t0 = time.time()
            try:
                getattr(mod, name)(args.root)
                lines.append(f"PASS  {path.stem}::{name}  ({time.time() - t0:.1f}s)")
            except Exception as e:  # noqa: BLE001
                failed += 1
                msg = (str(e) or e.__class__.__name__).splitlines()[0][:300]
                lines.append(f"FAIL  {path.stem}::{name}  {msg}")
                if not isinstance(e, AssertionError):
                    lines.append("      " + traceback.format_exc().strip().splitlines()[-1][:300])
    if not args.only or args.only in "test_worker":
        node, t0 = shutil.which("node"), time.time()
        if not node:
            lines.append("SKIP  test_worker.mjs  node is not installed; the Worker unit test was not run")
        else:
            r = subprocess.run([node, str(HERE / "test_worker.mjs")], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                lines.append(f"PASS  test_worker::node test_worker.mjs  ({time.time() - t0:.1f}s)")
            else:
                failed += 1
                detail = (r.stderr.strip() or r.stdout.strip() or "no output").splitlines()
                lines.append(f"FAIL  test_worker::node test_worker.mjs  exit {r.returncode}: {detail[0][:300] if detail else ''}")
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    report = "\n".join(lines) + f"\n\n{sum(l.startswith("PASS") for l in lines)} passed, {failed} failed, {sum(l.startswith("SKIP") for l in lines)} skipped  (root: {args.root})\n"
    (out / "report.txt").write_text(report)
    print(report)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
