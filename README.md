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

`python examples/demo.py` shows a rerun after an append. `python examples/benchmark.py` compares against plain pandas
(2M rows, +1,000 appended, best of 3, results asserted equal; one machine, pandas 3.0.5):

| scenario | pandas | incpandas | speedup |
|---|---|---|---|
| groupby: first run | 0.78s | 0.66s | 1.2x |
| groupby: append 1,000 rows | 0.47s | 0.024s | ~20x |
| groupby: no change | 0.49s | 0.025s | ~20x |
| row-wise (filter) result: first run | 0.37s | 0.35s | 1.1x |
| row-wise result: append 1,000 rows | 0.25s | 0.049s | ~5x |
| row-wise result: no change | 0.28s | 0.041s | ~7x |

The row-wise case is slower than groupby because it loads and re-saves the full previous output each time.

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
Not done: graph visualisation (text `explain()` only), edited/deleted rows via key column.

Known limits: state stores full outputs (disk/RAM scale with data); a file whose header contains quotes is always fully re-read; the whole file is read once per run to hash it (I/O only, no parsing).

## Running the tests
```
pip install -e ".[dev]"
pytest           # fast: ~20s, every registered operation exercised
pytest --slow    # comprehensive: the full fuzz cross product, ~40s
pytest -n0       # serially, for readable output while debugging one test
```
The fuzz suite is a cross product of every operation in `tests/fuzz_ops.py` against every
file-mutation and right-table-mutation mode. The default run keeps one mode per operation,
chosen round-robin, so every operation and every mode appears but not every pairing (396 of
963 tests). `--slow` runs all of it, and also any test marked `@pytest.mark.slow`.

CI runs the fast suite on pushes to a feature branch and the comprehensive suite on anything
that gates `main`, across py3.10/3.12 x pandas 2.1/2.2/3.0/3.1.
