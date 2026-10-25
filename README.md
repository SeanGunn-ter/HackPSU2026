# incpandas

`import incpandas as pd` instead of `import pandas as pd`. Rerun your script after new rows
are appended to a CSV and only the new rows are processed. The output equals a full pandas run.

```python
import incpandas as pd

df = pd.read_csv("sales.csv")
df["revenue"] = df.qty * df.price
df = df[df.revenue > 20]
print(df.groupby("region").agg(total=("revenue", "sum"), orders=("qty", "count")))
```

`python examples/demo.py` shows a rerun after an append. `python examples/benchmark.py` compares against plain
pandas across five pipelines and three scenarios each, with every result asserted equal to pandas. Speedup on a
rerun after appending 1,000 rows, medians of 7 repeats, python 3.10 / pandas 2.3.3 on one laptop:

| pipeline | 500k rows | 2M rows | 5M rows |
|---|---|---|---|
| `merge` + groupby | 4.2x | 8.7x | **13.2x** |
| `groupby` agg | 3.1x | 7.0x | **10.9x** |
| `df.a.sum()` | 3.3x | 5.7x | **9.1x** |
| `(df.a * df.b).sum()` | 2.6x | 5.5x | **8.3x** |
| row-wise filter (large output) | 2.5x | 2.9x | **2.8x** |

The speedup grows with the file because incpandas' work depends on what was appended, not on what is already
there — except for the row-wise row, which stays flat, and the reason is in the breakdown below. Reruns with the
file **unchanged** are faster again (9-21x). A **first** run is never faster (0.8-1.0x): incpandas does pandas'
work and then saves state, so the win starts on the second run.

`--json results.json` writes everything, including where a rerun's time actually goes. At 5M rows:

* on the four small-output pipelines, **47-58% of a rerun was reading and SHA-256-ing the whole 55 MB file** just
  to prove it only grew. `INCPANDAS_QUICK_CHECK=1` skips that (see below) and roughly halves those reruns.
* the row-wise pipeline spent **73% loading and rewriting its 77 MB of saved output**. The rewrite is gone: the
  saved output is now a list of chunks and an append writes only the appended rows. The *load* remains, because
  the whole output has to be in hand to be returned, so row-wise improves but stays the weakest case.

With both, at 5M rows: groupby 22x, `df.a.sum()` 25x, `merge` 27x, row-wise 4.2x.

## Faster change detection (opt-in)
By default a rerun reads the whole CSV and re-hashes the bytes it saw last time, so **any** edit, deletion or
truncation anywhere is caught exactly. That read and hash is about half of a rerun on a 55 MB file.

`INCPANDAS_QUICK_CHECK=1` instead `stat()`s the file and hashes only the last 64 KiB of the previously seen
bytes. Appending then costs the same whatever the file size: at 5M rows a groupby rerun goes from 136ms to 68ms.

The trade-off, stated plainly: **a same-length edit to the old bytes more than 64 KiB from the end is not
noticed**, and the result is then stale. An edit that changes the file's length shifts every later byte and is
caught; a file that shrank or was rewritten without changing size falls back to the exact check. Appends, the
case incpandas exists for, are exact either way. Leave it off if anything rewrites your CSV in place; turn it on
for an append-only log. `verify()` and `INCPANDAS_VERIFY=1` catch the difference.

## How it works
1. `read_csv`, column math, filters, column selection and `groupby` are recorded into a plan (DAG) (`incpandas/nodes.py`) rather than executed.
2. On run, the source compares the saved file size + SHA-256 of the previously-seen bytes with the file now. If the old bytes are unchanged and the file only grew by whole rows, only the tail is parsed (with the dtypes from the last run, so it parses exactly as a full read would).
3. The delta flows through the plan. Row-wise nodes just transform it. `groupby` keeps per-group partial aggregates (sum, count, min, max) and merges the delta's partials in. The previous output is saved and the delta appended.
4. State is one pickle per plan in `.incpandas_cache/` (override with `INCPANDAS_CACHE`), written atomically. Corrupt/stale state or any error in the incremental path triggers a clean recompute.
5. Anything else runs in real pandas.

## Supported incrementally
* `read_csv` of a local, uncompressed file with `sep, delimiter, usecols, dtype, na_values, keep_default_na, encoding, quotechar, decimal` (other args -> plain pandas).
* `df["c"] = <expr>`: arithmetic, comparisons, `& | ~`, scalars, `isin/between/isna/notna/abs/round/fillna`, `.str.{upper,lower,len,strip,contains,startswith,endswith,replace,...}`.
* `df[bool_expr]`, `df[["a","b"]]`.
* `groupby(str | list[str], as_index=, sort=)` then `sum/count/mean/min/max`, `.agg("sum")`, `.agg({"a": "sum"})`, named aggregation, with optional column selection. Only for int/float columns.

## Fallbacks (always correct, not incremental)
* Source changed other than by append (edit, delete, truncate), or appended rows that would change a column's dtype (e.g. a NaN in an int column) -> the file is fully re-read and everything downstream rebuilt.
* Unsupported aggregation/dtype (e.g. `.sum()` over string columns, `median`, `size`) or expressions mixing in concrete pandas values / other frames -> that node runs in pandas on the full data.
* Any other DataFrame/Series method (`sort_values`, `merge`, `.sum()` on a column, `.loc[...] =`, `inplace=True`, ...) materialises the frame and runs real pandas. Mutations are kept.
* `df.explain()` shows the plan: `[+]` incremental, `[x]` fallback, plus rows processed on the last run.

## Seeing the plan
`viz.graph()` draws the plan as a self-contained HTML page: green nodes ran incrementally, blue ran over
everything, red fell back to pandas, each labelled with what it did on the last run and why if it fell back.
The page embeds its own CSS and SVG and loads nothing over the network, so it opens offline from a `file://` URL.

```python
from incpandas import viz

out = df[df.revenue > 20].groupby("region")[["revenue"]].sum()
out.to_pandas()                      # run it first, so the graph has a last run to show
viz.graph(out, "plan.html")          # or out.graph("plan.html"), or viz.show(out) to open it
```

Importing `incpandas.viz` attaches `.graph()` and `.show()` to lazy frames. Hovering a node shows its full
label and output columns.

## Checking correctness
* `result.verify()` / `incpandas.check(result)`: replays the plan with plain pandas from scratch and asserts equality.
* `INCPANDAS_VERIFY=1` does that on every materialisation (the test suite runs this way).
* Float sums/means are compared with a tiny tolerance: merging partial sums can differ from pandas' single pass in the last bits. Integers are exact.

## Seeing what a run did
* `INCPANDAS_LOG=1` prints one line per run:

  ```
  incpandas: processed 1,000 new rows, skipped 2,000,000 (4 incremental)
  ```

  `processed` counts the CSV rows actually parsed this run, `skipped` the rows that were not
  re-read, and the tail counts nodes by mode (`incremental`, `full`, `fallback`).
* `INCPANDAS_STRICT=1` raises `incpandas.engine.StrictFallback` instead of quietly handing work
  to pandas, for both kinds of fallback: an unsupported call (`df.a.map(...)`, `sort_values`) and
  a planned node that declines to run incrementally (`df.k.sum()` over strings). Useful in CI to
  assert a pipeline really is incremental end to end. Recomputing from scratch after a file edit
  is not a fallback and does not raise.

## Status vs scope
MVP done: append detection, column math + filters, groupby sum/count/mean, fallback, persistent state, correctness check. Also done: min/max, text plan view.
Also done: `merge` with new rows on the left, the plan graph (`viz.graph()`).
Not done: edited/deleted rows via a key column; cheap change detection (a rerun still hashes the whole file,
about half of its time at 5M rows); saving only new rows instead of rewriting the whole saved output (73% of a
row-wise rerun).

Known limits: state stores full outputs (disk/RAM scale with data); a file whose header contains quotes is always fully re-read; the whole file is read once per run to hash it (I/O only, no parsing).

## Running the tests
```
pip install -e ".[dev]"
pytest          # everything, ~40s
pytest --fast   # one mode per operation, ~20s
pytest -n0      # serially, for readable output while debugging one test
```
The fuzz suite is a cross product of every operation in `tests/fuzz_ops.py` against every
file-mutation and right-table-mutation mode, and all 963 tests run by default. `--fast` keeps
one mode per operation, chosen round-robin so every operation and every mode still appears
but not every pairing (396 tests), and skips anything marked `@pytest.mark.slow`.

CI runs the full suite on every push and pull request, across py3.10/3.12 x pandas
2.1/2.2/3.0/3.1.
