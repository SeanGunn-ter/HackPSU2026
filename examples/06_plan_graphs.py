"""Generate the saved plan graphs in docs/plans/ (small self-contained HTML files).

Each graph is the plan of a pipeline drawn by incpandas.viz right after a real run, so the
colours are what that run really did: green = incremental, blue = full pass, red = pandas
fallback. Pass --png to also save a PNG of each next to its HTML (needs the `playwright`
package and a Chromium, set CHROMIUM_PATH to use a specific browser binary; used for slides).

    python examples/06_plan_graphs.py
    python examples/06_plan_graphs.py --out /tmp/plans --png
"""
import argparse
import os
import shutil
import tempfile

import numpy as np
import pandas

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "plans"),
                help="output folder (default: docs/plans)")
ap.add_argument("--png", action="store_true", help="also save a PNG of each graph (needs playwright)")
args = ap.parse_args()
out_dir = os.path.normpath(os.path.abspath(args.out))
os.makedirs(out_dir, exist_ok=True)

work = tempfile.mkdtemp(prefix="incpandas-plans-")
os.chdir(work)

import incpandas as pd
from incpandas import viz

N = 20_000


def sales(n, seed):
    rng = np.random.default_rng(seed)
    return pandas.DataFrame({"region": rng.choice(list("ABCD"), n),
                             "qty": rng.integers(1, 20, n),
                             "price": rng.normal(10, 3, n).round(2)})


def fresh_cache(name):
    os.environ["INCPANDAS_CACHE"] = os.path.join(work, "cache-" + name)


def save(frame, name, title):
    frame.to_pandas()                       # run it, so the graph shows this run
    path = viz.graph(frame, os.path.join(out_dir, name), title)
    print("wrote", os.path.normpath(path))
    return path


def revenue_by_region():
    df = pd.read_csv("sales.csv")
    df["revenue"] = df.qty * df.price
    df = df[df.revenue > 20]
    return df.groupby("region").agg(total=("revenue", "sum"), orders=("qty", "count"))


paths = []

# 01 / 02: column math + filter + groupby, first run then after an append
fresh_cache("groupby")
sales(N, 0).to_csv("sales.csv", index=False)
paths.append(save(revenue_by_region(), "01_groupby_first_run.html",
                  "Column math + filter + groupby: first run"))
sales(500, 1).to_csv("sales.csv", mode="a", header=False, index=False)
paths.append(save(revenue_by_region(), "02_groupby_after_append.html",
                  "Same plan after appending 500 rows"))

# 03: a node that falls back to pandas (a list of functions is not maintained incrementally)
fresh_cache("fallback")
df = pd.read_csv("sales.csv")
df["revenue"] = df.qty * df.price
paths.append(save(df.groupby("region")[["revenue"]].agg(["sum", "max"]), "03_pandas_fallback.html",
                  "groupby(...).agg([...]): this node falls back to pandas"))

# 04: left merge, two sources, after appending to the left table
fresh_cache("merge")
sales(N, 0).drop(columns="region").assign(store=lambda d: d.index % 20).to_csv("facts.csv", index=False)
pandas.DataFrame({"store": range(20), "region": list("ABCD") * 5}).to_csv("stores.csv", index=False)


def merged():
    m = pd.read_csv("facts.csv").merge(pd.read_csv("stores.csv"), how="left", on="store")
    m["revenue"] = m.qty * m.price
    return m.groupby("region")[["revenue"]].sum()


merged().to_pandas()
more = sales(500, 2).drop(columns="region")
more["store"] = np.arange(500) % 20
more.to_csv("facts.csv", mode="a", header=False, index=False)
paths.append(save(merged(), "04_merge_plan.html", "Left merge of two CSVs after appending to the left one"))

# 05: a row-wise chain
fresh_cache("rowwise")
rows = sales(N, 3)
rows.loc[::7, "price"] = np.nan
rows.to_csv("sales.csv", index=False)


def chain():
    df = pd.read_csv("sales.csv").rename(columns={"qty": "quantity"})
    df = df.dropna(subset=["quantity"]).fillna({"price": 0.0})
    return df.assign(revenue=lambda d: d.quantity * d.price)


chain().to_pandas()
more = sales(500, 4)
more.to_csv("sales.csv", mode="a", header=False, index=False)
paths.append(save(chain(), "05_row_wise_chain.html", "rename / dropna / fillna / assign after an append"))

if args.png:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        page = browser.new_page(viewport={"width": 1100, "height": 700}, device_scale_factor=2)
        for path in paths:
            page.goto("file://" + path)
            page.locator("svg").screenshot(path=path[:-5] + ".png")
            print("wrote", os.path.normpath(path[:-5] + ".png"))
        browser.close()

shutil.rmtree(work, ignore_errors=True)
