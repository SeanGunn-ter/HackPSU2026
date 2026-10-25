"""Merge a fact table with a dimension table.

New rows on the LEFT (fact) side are processed incrementally. A change on the RIGHT
(dimension) side can add matches for old left rows, so the merge is recomputed in full.
last_run() reports what each plan node did, so you can see which case you got.

    python examples/03_merge.py
"""
import os
import tempfile

import numpy as np
import pandas

work = tempfile.mkdtemp(prefix="incpandas-merge-")
os.chdir(work)
os.environ["INCPANDAS_CACHE"] = os.path.join(work, "cache")
os.environ["INCPANDAS_LOG"] = "1"

import incpandas as pd

STORES = 50


def facts(n, seed):
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"store": rng.integers(0, STORES, n),
                             "qty": rng.integers(1, 20, n),
                             "price": rng.normal(10, 3, n).round(2)})


def stores(n):
    rng = np.random.default_rng(7)
    return pandas.DataFrame({"store": np.arange(n), "region": rng.choice(list("NSEW"), n)})


def report():
    merged = pd.read_csv("facts.csv").merge(pd.read_csv("stores.csv"), how="left", on="store")
    merged["revenue"] = merged.qty * merged.price
    return merged.groupby("region")[["revenue"]].sum()


def what_happened(out):
    merge = [mode for sig, (mode, rows) in pd.last_run().items()]
    print(out.explain())
    print("  node modes this run:", ", ".join(merge))


facts(300_000, 0).to_csv("facts.csv", index=False)
stores(STORES).to_csv("stores.csv", index=False)

print("--- first run")
out = report()
out.to_pandas()

print("\n--- append to the LEFT table: the merge stays incremental")
facts(1_000, 1).to_csv("facts.csv", mode="a", header=False, index=False)
out = report()
out.to_pandas()
what_happened(out)

print("\n--- change the RIGHT table (re-label store 3): the merge recomputes in full")
dim = stores(STORES)
dim.loc[dim.store == 3, "region"] = "ZZ"
dim.to_csv("stores.csv", index=False)
out = report()
res = out.to_pandas()
what_happened(out)

out.verify()
print("\nboth cases still match a full pandas run. regions:", sorted(res.index))
