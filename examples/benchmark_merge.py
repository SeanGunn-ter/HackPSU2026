"""Benchmark: a large fact table merged with a small dimension table, plain pandas vs incpandas.

    python examples/benchmark_merge.py [rows] [appended_rows]

Scenarios: first run, then `appended_rows` new fact rows, then no change. Timed end to end
(read CSVs -> merge -> materialise), best of 3 for the rerun cases, and every result is checked
equal to plain pandas.
"""
import os
import sys
import tempfile
import time

import numpy as np
import pandas

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2_000_000
APPEND = int(sys.argv[2]) if len(sys.argv) > 2 else 1_000
DIM = 100

os.chdir(tempfile.mkdtemp())
os.environ["INCPANDAS_CACHE"] = ".cache"
import incpandas


def make_facts(n, seed):
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"store": rng.integers(0, DIM, n),
                             "qty": rng.integers(1, 20, n),
                             "price": rng.normal(10, 3, n).round(2)})


def make_dim():
    rng = np.random.default_rng(7)
    return pandas.DataFrame({"store": np.arange(DIM), "region": rng.choice(list("ABCDEFGH"), DIM),
                             "weight": rng.integers(1, 5, DIM)})


def merged_pipeline(pd):
    return pd.read_csv("facts.csv").merge(pd.read_csv("dim.csv"), how="left", on="store")


def merged_groupby_pipeline(pd):
    m = pd.read_csv("facts.csv").merge(pd.read_csv("dim.csv"), how="left", on="store")
    m["revenue"] = m.qty * m.price * m.weight
    return m.groupby("region")[["revenue", "qty"]].sum()


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return time.perf_counter() - t, out


def run(pipeline):
    def plain():
        return pipeline(pandas)

    def inc():
        return pipeline(incpandas).to_pandas()

    make_facts(N, 0).to_csv("facts.csv", index=False)
    make_dim().to_csv("dim.csv", index=False)
    rows = []
    for label, grow in [(f"first run ({N:,} rows)", 0), (f"append {APPEND:,} rows", APPEND), ("no change", 0)]:
        if grow:
            make_facts(grow, 1).to_csv("facts.csv", mode="a", header=False, index=False)
        reps = 1 if label.startswith("first") else 3
        tp = min(timed(plain)[0] for _ in range(reps))
        ti, out_i = min((timed(inc) for _ in range(reps)), key=lambda x: x[0])
        pandas.testing.assert_frame_equal(out_i, plain(), check_exact=False, rtol=1e-7)
        rows.append((label, tp, ti))
    return rows


for name, pipe in [("merge then groupby (small output)", merged_groupby_pipeline),
                   ("merged frame (large output)", merged_pipeline)]:
    for f in os.listdir(".cache") if os.path.isdir(".cache") else []:
        os.remove(os.path.join(".cache", f))
    print(f"\n{name}")
    print(f"  {'scenario':28s} {'pandas':>9s} {'incpandas':>10s} {'speedup':>8s}")
    for label, tp, ti in run(pipe):
        print(f"  {label:28s} {tp:8.3f}s {ti:9.3f}s {tp / ti:7.1f}x")
