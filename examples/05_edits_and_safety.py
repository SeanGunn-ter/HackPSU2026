"""Edits, truncation and file replacement are detected and never give a wrong answer.

incpandas is only incremental for pure appends. If any earlier byte of the CSV changed,
the file is re-read in full and the plan is rebuilt. Each case below prints what the engine
did (INCPANDAS_LOG=1) and checks the result against plain pandas.

    python examples/05_edits_and_safety.py
"""
import os
import tempfile

import numpy as np
import pandas

work = tempfile.mkdtemp(prefix="incpandas-safety-")
os.chdir(work)
os.environ["INCPANDAS_CACHE"] = os.path.join(work, "cache")
os.environ["INCPANDAS_LOG"] = "1"

import incpandas as pd


def make_rows(n, seed):
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"region": rng.choice(list("ABCD"), n),
                             "qty": rng.integers(1, 20, n),
                             "price": rng.normal(10, 3, n).round(2)})


def pipeline(lib):
    df = lib.read_csv("sales.csv")
    df["revenue"] = df.qty * df.price
    return df.groupby("region").agg(total=("revenue", "sum"), orders=("qty", "count"))


def run(label):
    print(f"\n--- {label}")
    out = pipeline(pd)
    got = out.to_pandas()
    pandas.testing.assert_frame_equal(got, pipeline(pandas), check_exact=False, rtol=1e-7)
    print("matches plain pandas: True")


make_rows(100_000, 0).to_csv("sales.csv", index=False)
run("first run")

make_rows(500, 1).to_csv("sales.csv", mode="a", header=False, index=False)
run("pure append: incremental")

lines = open("sales.csv").read().splitlines()
lines[50_000] = "A,19,99.99"                         # edit one row in the middle
open("sales.csv", "w").write("\n".join(lines) + "\n")
run("edit a row in the middle: detected, re-read in full")

lines = open("sales.csv").read().splitlines()
open("sales.csv", "w").write("\n".join(lines[:60_000]) + "\n")
run("truncate the file: detected, re-read in full")

make_rows(30_000, 9).to_csv("sales.csv", index=False)
run("replace the file with different data: detected, re-read in full")
