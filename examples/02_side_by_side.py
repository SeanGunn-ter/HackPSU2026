"""Plain pandas vs incpandas, side by side, with a live timer.

Runs the same pipeline under both libraries for a first run, an append and a no-change
rerun, prints the wall time of each and ends by calling verify(). The first run is about
the same as pandas (incpandas also saves state); the gain is on the reruns.

    python examples/02_side_by_side.py
    python examples/02_side_by_side.py --rows 2000000 --append 5000
"""
import argparse
import atexit
import os
import shutil
import tempfile
import time

import numpy as np
import pandas

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--rows", type=int, default=1_000_000, help="rows in the starting CSV")
ap.add_argument("--append", type=int, default=1_000, help="rows added before the second run")
args = ap.parse_args()

work = tempfile.mkdtemp(prefix="incpandas-sidebyside-")
atexit.register(shutil.rmtree, work, ignore_errors=True)   # clean up the temp folder on exit
os.chdir(work)
os.environ["INCPANDAS_CACHE"] = os.path.join(work, "cache")
os.environ["INCPANDAS_LOG"] = "1"

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
    return df.groupby("region").agg(total=("revenue", "sum"), orders=("qty", "count"),
                                    avg_qty=("qty", "mean"))


def run(lib):
    start = time.perf_counter()
    out = pipeline(lib)
    out = out.to_pandas() if hasattr(out, "to_pandas") else out
    return time.perf_counter() - start, out


print(f"building sales.csv with {args.rows:,} rows ...")
make_rows(args.rows, seed=0).to_csv("sales.csv", index=False)

last = None
for label, extra in [(f"first run ({args.rows:,} rows)", 0),
                     (f"append {args.append:,} rows", args.append),
                     ("no change", 0)]:
    if extra:
        make_rows(extra, seed=1).to_csv("sales.csv", mode="a", header=False, index=False)
    print(f"\n{label}")
    t_plain, want = run(pandas)
    t_inc, got = run(incpandas)
    pandas.testing.assert_frame_equal(got, want, check_exact=False, rtol=1e-7)
    print(f"  pandas {t_plain:7.3f}s   incpandas {t_inc:7.3f}s   speedup {t_plain / t_inc:5.1f}x")
    last = pipeline(incpandas)

last.verify()
print("\nverify(): the incremental result equals a from-scratch pandas run")
print("\nTimings depend on the machine and the pipeline; a first run is not faster.")
