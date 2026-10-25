"""A web-access-log style dataset: groupby + filter, append new log lines, rerun.

The timestamp column is kept as text (a plain string column); status codes, byte counts and
latencies are numbers and endpoints are strings. The pipeline keeps server errors (status
>= 500), adds a size-in-KB column, then reports error count, total KB and worst latency per
endpoint. Appending new log lines only processes the new lines.

    python examples/07_realistic_logs.py
    python examples/07_realistic_logs.py --rows 1000000 --append 2000
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
ap.add_argument("--rows", type=int, default=1_000_000, help="log lines in the starting file")
ap.add_argument("--append", type=int, default=2_000, help="new log lines to append")
args = ap.parse_args()

work = tempfile.mkdtemp(prefix="incpandas-logs-")
atexit.register(shutil.rmtree, work, ignore_errors=True)   # clean up the temp folder on exit
os.chdir(work)
os.environ["INCPANDAS_CACHE"] = os.path.join(work, "cache")
os.environ["INCPANDAS_LOG"] = "1"

import incpandas

ENDPOINTS = ["/", "/login", "/api/items", "/api/items/{id}", "/api/cart", "/checkout", "/static/app.js",
             "/search", "/health"]
STATUS = [200, 200, 200, 200, 200, 301, 304, 404, 500, 503]


def log_lines(n, seed, start="2026-10-01 00:00:00"):
    rng = np.random.default_rng(seed)
    ts = pandas.Timestamp(start) + pandas.to_timedelta(np.sort(rng.integers(0, 86_400, n)), unit="s")
    return pandas.DataFrame({"timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),    # kept as text
                             "endpoint": rng.choice(ENDPOINTS, n),
                             "status": rng.choice(STATUS, n),
                             "bytes": rng.integers(200, 200_000, n),
                             "latency_ms": rng.gamma(2.0, 40.0, n).round(1)})


def errors_by_endpoint(lib):
    log = lib.read_csv("access.csv")
    log = log[log.status >= 500]
    log["kb"] = log.bytes / 1024
    return log.groupby("endpoint").agg(errors=("status", "count"), total_kb=("kb", "sum"),
                                       worst_ms=("latency_ms", "max"))


def timed(lib):
    t = time.perf_counter()
    out = errors_by_endpoint(lib)
    out = out.to_pandas() if hasattr(out, "to_pandas") else out
    return time.perf_counter() - t, out


print(f"writing {args.rows:,} log lines ...")
log_lines(args.rows, 0).to_csv("access.csv", index=False)
print(open("access.csv").readlines()[1].strip(), "  <- an example line")
for label, extra in [("first run", 0), (f"append {args.append:,} lines", args.append), ("no change", 0)]:
    if extra:
        log_lines(extra, 1, start="2026-10-02 00:00:00").to_csv("access.csv", mode="a", header=False, index=False)
    print(f"\n{label}")
    tp, want = timed(pandas)
    ti, got = timed(incpandas)
    pandas.testing.assert_frame_equal(got, want, check_exact=False, rtol=1e-7)
    print(f"  pandas {tp:7.3f}s   incpandas {ti:7.3f}s   speedup {tp / ti:5.1f}x")

print("\n", got.round(1).to_string(), sep="")
errors_by_endpoint(incpandas).verify()
print("\nverify(): the incremental result equals a from-scratch pandas run")
