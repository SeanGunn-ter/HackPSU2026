"""Unsupported operations fall back to pandas and still match; STRICT mode makes that loud.

Part 1 runs a median groupby and sort_values. Neither is incremental, so incpandas runs
them in real pandas and the answer equals a plain pandas run. Part 2 sets
INCPANDAS_STRICT=1, which raises StrictFallback instead of handing work to pandas quietly.
Part 3 prints explain(), the text view of the plan: [+] incremental, [x] falls back.

    python examples/04_fallback_and_strict.py
"""
import os
import tempfile

import numpy as np
import pandas

work = tempfile.mkdtemp(prefix="incpandas-fallback-")
os.chdir(work)
os.environ["INCPANDAS_CACHE"] = os.path.join(work, "cache")

import incpandas as pd
from incpandas import StrictFallback

rng = np.random.default_rng(0)
pandas.DataFrame({"region": rng.choice(list("ABC"), 50_000), "qty": rng.integers(1, 20, 50_000),
                  "price": rng.normal(10, 3, 50_000).round(2)}).to_csv("sales.csv", index=False)


def median_by_region(lib):
    df = lib.read_csv("sales.csv")
    df["revenue"] = df.qty * df.price
    return df.groupby("region")[["revenue"]].median()      # median is not incremental


print("--- 1. fallback: median groupby runs in pandas, result still matches")
got = median_by_region(pd)             # a real pandas DataFrame: the call ran eagerly in pandas
want = median_by_region(pandas)
pandas.testing.assert_frame_equal(got, want)
print(got)
print("equal to plain pandas: True")
print("incpandas.fallback_log (names of calls that ran in pandas):", pd.fallback_log[-3:])

top = pd.read_csv("sales.csv").sort_values("price").head(3)   # sort_values is not incremental
pandas.testing.assert_frame_equal(top, pandas.read_csv("sales.csv").sort_values("price").head(3))
print("sort_values(...).head(3) also matches pandas")

print("\n--- 2. INCPANDAS_STRICT=1 raises instead of falling back")
os.environ["INCPANDAS_STRICT"] = "1"
for name, call in [("sort_values", lambda: pd.read_csv("sales.csv").sort_values("price")),
                   ("median groupby", lambda: median_by_region(pd))]:
    try:
        call()
    except StrictFallback as e:
        print(f"{name}: StrictFallback raised -> {e}")
del os.environ["INCPANDAS_STRICT"]

print("\n--- 3. explain(): the plan, with what each node did on the last run")
ok = pd.read_csv("sales.csv")
ok["revenue"] = ok.qty * ok.price
planned = ok.groupby("region")[["revenue"]].agg(["sum", "max"])   # a list of functions: planned, not incremental
res = planned.to_pandas()
pandas.testing.assert_frame_equal(res, pandas.read_csv("sales.csv").assign(revenue=lambda d: d.qty * d.price)
                                  .groupby("region")[["revenue"]].agg(["sum", "max"]), check_exact=False, rtol=1e-7)
print(planned.explain())
print("(the red node ran in pandas on the full data; the result equals plain pandas)")
