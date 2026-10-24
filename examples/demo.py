"""Rerun a pipeline after appending rows: the second run only touches the new rows.

    python examples/demo.py
"""
import os
import tempfile
import time

import numpy as np

os.chdir(tempfile.mkdtemp())
os.environ["INCPANDAS_CACHE"] = ".cache"

import incpandas as pd   # <- the only change from a plain pandas script
import pandas


def make_rows(n, seed):
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"region": rng.choice(list("ABCDEFGH"), n),
                             "qty": rng.integers(1, 20, n),
                             "price": rng.normal(10, 3, n).round(2)})


def pipeline():
    df = pd.read_csv("sales.csv")
    df["revenue"] = df.qty * df.price
    df = df[df.revenue > 20]
    return df.groupby("region").agg(total=("revenue", "sum"), orders=("qty", "count"), avg_qty=("qty", "mean"))


make_rows(2_000_000, 0).to_csv("sales.csv", index=False)
for label, extra in [("first run (2,000,000 rows)", 0), ("after appending 1,000 rows", 1_000), ("no change", 0)]:
    if extra:
        make_rows(extra, 1).to_csv("sales.csv", mode="a", header=False, index=False)
    t = time.perf_counter()
    result = pipeline()
    out = result.to_pandas()
    dt = time.perf_counter() - t
    rows = max(r for _, r in pd.last_run().values())
    print(f"{label:30s} {dt:6.2f}s  (rows processed: {rows:,})")

result.verify()
print("\nmatches a full pandas run: True\n")
print(out)
print("\n" + result.explain())
