"""Benchmark: plain pandas vs incpandas, across pipelines, data sizes and kinds of rerun.

    python examples/benchmark.py                        # the default matrix
    python examples/benchmark.py --quick                # small and fast, for a smoke test
    python examples/benchmark.py --sizes 1000000,5000000 --appends 100,10000
    python examples/benchmark.py --json results.json    # machine-readable, for the charts

Every (pipeline, rows, appended) cell is timed three ways:

    first run   no saved state, so incpandas does pandas' work plus saving state
    append      `appended` rows are added to the CSV, then the pipeline is rerun
    no change   the CSV is untouched and the pipeline is rerun

Timings are repeated and reported as a median with the full range, because the same machine
can differ by 2x depending on what else is running, and a single best-of-N number reads as
more precise than it is. Each repeat of the append case appends *again*: rerunning without
appending measures the no-change path instead, which is the easy mistake to make here.

Results are checked against plain pandas, outside the timed region.
"""
import argparse
import hashlib
import io
import json
import os
import pickle
import platform
import shutil
import statistics
import sys
import tempfile
import time
from contextlib import redirect_stdout

import numpy as np
import pandas

LEFT, RIGHT = "left.csv", "right.csv"
REGIONS = list("ABCDEFGH")


# -- data ------------------------------------------------------------------------------------

def left_rows(n, seed):
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"region": rng.choice(REGIONS, n),
                             "qty": rng.integers(1, 20, n),
                             "price": rng.normal(10, 3, n).round(2)})


def right_rows(seed):
    """A small dimension table: one row per region, so a left merge keeps the row count."""
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"region": REGIONS,
                             "weight": rng.normal(1, 0.1, len(REGIONS)).round(3)})


# -- pipelines -------------------------------------------------------------------------------
# Each takes the module to run under (pandas or incpandas), so the same source is timed both
# ways, exactly as a user would get it by changing their import.

def p_groupby(pd):
    df = pd.read_csv(LEFT)
    df["revenue"] = df.qty * df.price
    df = df[df.revenue > 20]
    return df.groupby("region").agg(total=("revenue", "sum"), orders=("qty", "count"),
                                    avg_qty=("qty", "mean"))


def p_rowwise(pd):
    df = pd.read_csv(LEFT)
    df["revenue"] = df.qty * df.price
    return df[df.revenue > 100]


def p_reduction(pd):
    return pd.read_csv(LEFT).qty.sum()


def p_formula_reduction(pd):
    df = pd.read_csv(LEFT)
    return (df.qty * df.price).sum()


def p_merge(pd):
    out = pd.read_csv(LEFT).merge(pd.read_csv(RIGHT), how="left", on="region")
    out["weighted"] = out.qty * out.weight
    return out.groupby("region")[["weighted"]].sum()


PIPELINES = {"groupby": p_groupby, "rowwise": p_rowwise, "reduction": p_reduction,
             "formula_reduction": p_formula_reduction, "merge": p_merge}


# -- timing ----------------------------------------------------------------------------------

def materialize(out):
    return out.to_pandas() if hasattr(out, "to_pandas") else out


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return time.perf_counter() - t, out


def stats(times):
    return {"median": statistics.median(times), "min": min(times), "max": max(times),
            "times": [round(t, 6) for t in times]}


def same(got, want):
    """Equal to plain pandas, to the same tolerance the test suite uses."""
    if isinstance(want, (pandas.DataFrame, pandas.Series)):
        check = (pandas.testing.assert_frame_equal if isinstance(want, pandas.DataFrame)
                 else pandas.testing.assert_series_equal)
        check(got, want, check_exact=False, rtol=1e-7)
        return
    if type(got) is not type(want):
        raise AssertionError(f"{type(got).__name__} != {type(want).__name__}")
    if pandas.isna(got) and pandas.isna(want):
        return
    # A float total merged from partial sums can differ from pandas' single pass in the last
    # bits, so scalars get the same relative tolerance as frames. Integers are exact.
    ok = np.isclose(got, want, rtol=1e-7, atol=0) if isinstance(want, (int, float, np.number)) \
        else got == want
    if not ok:
        raise AssertionError(f"{got!r} != {want!r}")


# -- the component breakdown -----------------------------------------------------------------
# Each part of a rerun is measured standalone, not by instrumenting the engine, so running the
# benchmark can't slow down the thing it is measuring. Every measurement is repeated and the
# median taken, because the rerun totals are medians too and a single shot is not comparable
# to one. The residual is real plan work plus whatever these proxies miss, so read it as
# "everything else", not as a precise figure.

def _median_of(fn, reps=3):
    times = []
    for _ in range(reps):
        t = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t)
    return statistics.median(times)


def components(cache, appended_bytes):
    out = {}

    # incpandas reads the header on every read_csv to learn the column names
    out["read_header"] = _median_of(lambda: pandas.read_csv(LEFT, nrows=0))

    # Every run reads the whole file and hashes it to decide whether it only grew, so this is
    # the floor on any rerun -- time the read as well as the hash, not just the hash.
    def read_and_hash():
        with open(LEFT, "rb") as f:
            hashlib.sha256(f.read()).hexdigest()
    out["read_and_hash"] = _median_of(read_and_hash)

    with open(LEFT, "rb") as f:
        raw = f.read()
    header = raw[: raw.find(b"\n") + 1]
    tail = raw[len(raw) - appended_bytes:] if appended_bytes else b""
    out["parse_appended_tail"] = _median_of(lambda: pandas.read_csv(io.BytesIO(header + tail)))

    paths = [os.path.join(cache, n) for n in sorted(os.listdir(cache))] if os.path.isdir(cache) else []
    out["state_bytes"] = sum(os.path.getsize(p) for p in paths)
    saved = []

    def load_state():
        saved.clear()
        for path in paths:
            with open(path, "rb") as f:
                saved.append(pickle.load(f))
    out["load_saved_state"] = _median_of(load_state)

    # What rewriting the whole saved output would cost. The engine no longer does that on an
    # append -- it writes one chunk -- so read this as the cost that chunking avoids, not as
    # part of the rerun below. Compaction pays it once every MAX_CHUNKS runs.
    def write_state():
        for i, obj in enumerate(saved):
            tmp = f"bench-state-{i}.tmp"
            with open(tmp, "wb") as f:
                pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.remove(tmp)
    out["rewrite_all_state"] = _median_of(write_state)
    out["state_files"] = len(paths)
    return out


# -- one cell --------------------------------------------------------------------------------

def run_cell(name, rows, appended, repeats, cold_repeats, incpandas):
    pipeline = PIPELINES[name]
    cache = os.environ["INCPANDAS_CACHE"]
    seed = [1000]

    def plain():
        return materialize(pipeline(pandas))

    def inc():
        return materialize(pipeline(incpandas))

    def clear_cache():
        for f in os.listdir(cache) if os.path.isdir(cache) else []:
            os.remove(os.path.join(cache, f))

    def grow():
        """Append `appended` fresh rows; returns how many bytes were added."""
        chunk = left_rows(appended, seed=seed[0])
        seed[0] += 1
        body = chunk.to_csv(header=False, index=False)
        with open(LEFT, "a", newline="") as f:
            f.write(body)
        return len(body.encode())

    left_rows(rows, seed=0).to_csv(LEFT, index=False)
    right_rows(seed=7).to_csv(RIGHT, index=False)

    # first run: no saved state, so clear the cache before each repeat
    cold_plain, cold_inc = [], []
    for _ in range(cold_repeats):
        clear_cache()
        cold_plain.append(timed(plain)[0])
        cold_inc.append(timed(inc)[0])

    # append: grow the file once per repeat, or the rerun is really a no-change rerun
    app_plain, app_inc, appended_bytes = [], [], 0
    for _ in range(repeats):
        appended_bytes = grow()
        app_plain.append(timed(plain)[0])
        app_inc.append(timed(inc)[0])

    # no change: the file is left alone
    same_plain, same_inc = [], []
    for _ in range(repeats):
        same_plain.append(timed(plain)[0])
        same_inc.append(timed(inc)[0])

    breakdown = components(cache, appended_bytes)
    same(inc(), plain())                                # correctness, outside the timing

    # one more append with the engine's own log on, to record what it says it did
    grow()
    os.environ["INCPANDAS_LOG"] = "1"
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            inc()
        log = next((ln for ln in buf.getvalue().splitlines() if ln.startswith("incpandas:")), None)
    finally:
        os.environ.pop("INCPANDAS_LOG", None)

    cell = {"pipeline": name, "rows": rows, "appended": appended,
            "file_bytes": os.path.getsize(LEFT), "components": breakdown, "log": log,
            "scenarios": {}}
    for kind, tp, ti in [("first run", cold_plain, cold_inc), ("append", app_plain, app_inc),
                         ("no change", same_plain, same_inc)]:
        p, i = stats(tp), stats(ti)
        cell["scenarios"][kind] = {"pandas": p, "incpandas": i,
                                   "speedup": p["median"] / i["median"]}
    return cell


# -- reporting -------------------------------------------------------------------------------

def report(cell):
    print(f"\n{cell['pipeline']}  ({cell['rows']:,} rows, +{cell['appended']:,} appended, "
          f"{cell['file_bytes'] / 1e6:.0f} MB)")
    print(f"  {'scenario':11s} {'pandas':>24s} {'incpandas':>24s} {'speedup':>8s}")
    for kind, s in cell["scenarios"].items():
        p, i = s["pandas"], s["incpandas"]
        print(f"  {kind:11s} {p['median']:9.3f}s [{p['min']:.3f}-{p['max']:.3f}]"
              f" {i['median']:9.3f}s [{i['min']:.3f}-{i['max']:.3f}]"
              f" {s['speedup']:7.1f}x")
    c = cell["components"]
    total = cell["scenarios"]["append"]["incpandas"]["median"]
    parts = ("read_header", "read_and_hash", "parse_appended_tail", "load_saved_state")
    rest = total - sum(c[k] for k in parts)
    spent = "\n    ".join(f"{k.replace('_', ' '):21s} {c[k] * 1e3:7.1f}ms"
                          f" {100 * c[k] / total:5.1f}%" for k in parts)
    print(f"  roughly where a {total * 1e3:.0f}ms rerun goes:\n    {spent}")
    print(f"    {'everything else':21s} {rest * 1e3:7.1f}ms {100 * rest / total:5.1f}%")
    size = c["state_bytes"]
    print(f"  saved state on disk: "
          f"{f'{size / 1e6:.1f} MB' if size >= 1e6 else f'{size / 1e3:.0f} KB'}"
          f" in {c['state_files']} files; rewriting all of it would cost "
          f"{c['rewrite_all_state'] * 1e3:.0f}ms, which an append no longer pays")
    if cell["log"]:
        print(f"  {cell['log']}")


def environment():
    return {"python": sys.version.split()[0], "pandas": pandas.__version__,
            "numpy": np.__version__, "platform": platform.platform(),
            "processor": platform.processor() or "unknown", "cpus": os.cpu_count()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sizes", default="2000000", help="comma-separated row counts")
    ap.add_argument("--appends", default="1000", help="comma-separated appended row counts")
    ap.add_argument("--pipelines", default=",".join(PIPELINES))
    ap.add_argument("--repeats", type=int, default=5, help="repeats per rerun scenario")
    ap.add_argument("--cold-repeats", type=int, default=2, help="repeats of the first-run scenario")
    ap.add_argument("--quick", action="store_true", help="small sizes and few repeats")
    ap.add_argument("--json", metavar="PATH", help="write the full results here")
    args = ap.parse_args(argv)

    if args.quick:
        args.sizes, args.appends, args.repeats, args.cold_repeats = "50000", "1000", 2, 1

    # INCPANDAS_VERIFY makes every materialisation also replay the plan in pandas, which would
    # make every number here meaningless.
    if os.environ.pop("INCPANDAS_VERIFY", None):
        print("note: INCPANDAS_VERIFY was set; turned off for the benchmark")

    sizes = [int(s) for s in args.sizes.split(",")]
    appends = [int(s) for s in args.appends.split(",")]
    names = [n.strip() for n in args.pipelines.split(",")]
    for n in names:
        if n not in PIPELINES:
            ap.error(f"unknown pipeline {n!r}; pick from {', '.join(PIPELINES)}")
    out_path = os.path.abspath(args.json) if args.json else None

    env = environment()
    print(f"python {env['python']}  pandas {env['pandas']}  numpy {env['numpy']}  "
          f"{env['cpus']} cpus\n{env['platform']}")

    home, results = os.getcwd(), []
    for rows in sizes:
        for appended in appends:
            for name in names:
                # A cell writes a CSV and its saved state, which at the larger sizes is
                # hundreds of MB, so each one gets a fresh directory and gives it back.
                work = tempfile.mkdtemp(prefix="incpandas-bench-")
                try:
                    os.chdir(work)
                    os.environ["INCPANDAS_CACHE"] = os.path.join(work, ".cache")
                    import incpandas                 # imported after the cache env var is set
                    cell = run_cell(name, rows, appended, args.repeats, args.cold_repeats,
                                    incpandas)
                    report(cell)
                    results.append(cell)
                finally:
                    os.chdir(home)                   # Windows will not remove the cwd
                    shutil.rmtree(work, ignore_errors=True)

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"environment": env, "config": vars(args), "results": results}, f, indent=1)
        print(f"\nwrote {out_path}")
    return results


if __name__ == "__main__":
    main()
