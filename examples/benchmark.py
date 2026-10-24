"""Benchmark: plain pandas vs incpandas on first run, after an append, and with no change.

    python examples/benchmark.py [rows] [appended_rows]

Each scenario is timed end to end (read CSV -> transform -> materialise result), best of 3
for the rerun cases. Results are checked equal to plain pandas.
"""
import os
import sys
import tempfile
import time

import numpy as np
import pandas

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2_000_000
APPEND = int(sys.argv[2]) if len(sys.argv) > 2 else 1_000

os.chdir(tempfile.mkdtemp())
os.environ["INCPANDAS_CACHE"] = ".cache"
import incpandas


def make_rows(n, seed):
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"region": rng.choice(list("ABCDEFGH"), n),
                             "qty": rng.integers(1, 20, n),
                             "price": rng.normal(10, 3, n).round(2)})


def groupby_pipeline(pd):
    df = pd.read_csv("sales.csv")
    df["revenue"] = df.qty * df.price
    df = df[df.revenue > 20]
    return df.groupby("region").agg(total=("revenue", "sum"), orders=("qty", "count"), avg_qty=("qty", "mean"))


def rowwise_pipeline(pd):
    df = pd.read_csv("sales.csv")
    df["revenue"] = df.qty * df.price
    return df[df.revenue > 100]


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return time.perf_counter() - t, out


def run(pipeline):
    def plain():
        return pipeline(pandas)

    def inc():
        return pipeline(incpandas).to_pandas()

    make_rows(N, 0).to_csv("sales.csv", index=False)
    rows = []
    for label, grow in [(f"first run ({N:,} rows)", 0), (f"append {APPEND:,} rows", APPEND), ("no change", 0)]:
        if grow:
            make_rows(grow, 1).to_csv("sales.csv", mode="a", header=False, index=False)
        reps = 1 if label.startswith("first") else 3
        tp = min(timed(plain)[0] for _ in range(reps))
        ti, out_i = min((timed(inc) for _ in range(reps)), key=lambda x: x[0]) if reps > 1 else timed(inc)
        pandas.testing.assert_frame_equal(out_i, plain(), check_exact=False, rtol=1e-7)
        rows.append((label, tp, ti))
    return rows


for name, pipe in [("groupby result (small output)", groupby_pipeline),
                   ("row-wise result (large output)", rowwise_pipeline)]:
    for f in os.listdir(".cache") if os.path.isdir(".cache") else []:
        os.remove(os.path.join(".cache", f))
    print(f"\n{name}")
    print(f"  {'scenario':28s} {'pandas':>9s} {'incpandas':>10s} {'speedup':>8s}")
    for label, tp, ti in run(pipe):
        print(f"  {label:28s} {tp:8.3f}s {ti:9.3f}s {tp / ti:7.1f}x")
