"""Benchmark on a large CSV: plain pandas vs incpandas for first run, no change and an append.

    python examples/benchmark_large.py [rows] [appended_rows]

Each scenario is timed end to end (read CSV -> transform -> materialise result), best of 3
for the rerun cases. Results are checked equal to plain pandas. The "no change" case takes the
size+mtime shortcut; set INCPANDAS_CHECK=exact to time the full read-and-hash instead.
"""
import os
import sys
import tempfile
import time

import numpy as np
import pandas

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5_000_000
APPEND = int(sys.argv[2]) if len(sys.argv) > 2 else 1_000

os.chdir(tempfile.mkdtemp())
os.environ["INCPANDAS_CACHE"] = ".cache"
import incpandas


def make_rows(n, seed):
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"region": rng.choice(list("ABCDEFGH"), n),
                             "qty": rng.integers(1, 20, n),
                             "price": rng.normal(10, 3, n).round(2)})


def pipeline(pd):
    df = pd.read_csv("sales.csv")
    df["revenue"] = df.qty * df.price
    df = df[df.revenue > 20]
    return df.groupby("region").agg(total=("revenue", "sum"), orders=("qty", "count"))


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return time.perf_counter() - t, out


make_rows(N, 0).to_csv("sales.csv", index=False)
print(f"sales.csv: {N:,} rows, {os.path.getsize('sales.csv') / 1e6:.1f} MB")
print(f"{'scenario':28}{'pandas':>10}{'incpandas':>12}{'speedup':>10}")
for label, grow, repeat in [("first run", 0, 1), ("no change", 0, 3), (f"append {APPEND:,} rows", APPEND, 3)]:
    t_plain = t_inc = float("inf")
    for i in range(repeat):
        if grow:   # a fresh append per trial, so every trial has new rows to absorb
            make_rows(grow, 1 + i).to_csv("sales.csv", mode="a", header=False, index=False)
        tp, want = timed(lambda: pipeline(pandas))
        ti, got = timed(lambda: pipeline(incpandas).to_pandas())
        pandas.testing.assert_frame_equal(got, want)
        t_plain, t_inc = min(t_plain, tp), min(t_inc, ti)
    print(f"{label:28}{t_plain:9.3f}s{t_inc:11.3f}s{t_plain / t_inc:9.1f}x")
