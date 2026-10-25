"""Quick start: a groupby on a CSV, then append rows and rerun.

The only change from a plain pandas script is the import line. The second run reads only
the rows that were appended; INCPANDAS_LOG=1 prints how many rows each run processed.

    python examples/01_quickstart.py
"""
import atexit
import os
import shutil
import tempfile

import numpy as np
import pandas

work = tempfile.mkdtemp(prefix="incpandas-quickstart-")
atexit.register(shutil.rmtree, work, ignore_errors=True)   # clean up the temp folder on exit
os.chdir(work)
os.environ["INCPANDAS_CACHE"] = os.path.join(work, "cache")
os.environ["INCPANDAS_LOG"] = "1"      # print "processed N new rows, skipped M" after each run

import incpandas as pd   # <- the only change from a plain pandas script


def make_rows(n, seed):
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"region": rng.choice(list("ABCD"), n),
                             "qty": rng.integers(1, 20, n),
                             "price": rng.normal(10, 3, n).round(2)})


def report():
    df = pd.read_csv("sales.csv")
    df["revenue"] = df.qty * df.price
    df = df[df.revenue > 20]
    return df.groupby("region").agg(total=("revenue", "sum"), orders=("qty", "count"))


make_rows(200_000, seed=0).to_csv("sales.csv", index=False)

print("--- first run: reads the whole file and saves state")
result = report()
print(result.to_pandas())

make_rows(1_000, seed=1).to_csv("sales.csv", mode="a", header=False, index=False)

print("\n--- after appending 1,000 rows: only those rows are processed")
result = report()
print(result.to_pandas())

print("\n--- no change: nothing is processed")
result = report()
result.to_pandas()

result.verify()   # replays the plan in plain pandas and asserts the same answer
print("\nmatches a full pandas run: True")
