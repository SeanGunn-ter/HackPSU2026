# Headline numbers

Quote only what is on this page. Every figure comes from a command below, run on one machine on 2026-10-25.

**Machine:** cloud sandbox, 4 vCPU Intel Xeon @ 2.10 GHz, about 16 GB RAM, Ubuntu 24.04, Python 3.13.17, pandas 3.0.5, numpy 2.5.3,
library commit `e0dd3ff`. Other machines will differ. Details: `docs/benchmarks/ENVIRONMENT.md`.

**Method for the matrix:** pipeline timed end to end (read CSV, compute, materialize); median of 5 repeats (first run: 2); each append repeat appends
1,000 new rows; results checked equal to pandas. The whole matrix was run twice. Command for both runs (second one written to `results_run2.json`):

```
python examples/benchmark.py --sizes 1000000,5000000,20000000 --appends 1000 --repeats 5 --cold-repeats 2 --json docs/benchmarks/results.json
```

| Claim you can make | Number | Source |
|---|---|---|
| Rerun after appending 1,000 rows to a 20M-row (199 MB) CSV, filter + groupby | 0.276 s vs pandas 7.5 s, **27.2x** (28.0x in the second run) | `results.json`, `results_run2.json` |
| Same, left merge + groupby | 0.283 s vs 10.5 s, **37.0x** (35.5x in the second run) | same |
| Same, column sum / formula sum | **20.7x / 21.4x** (17.5x / 20.3x in the second run) | same |
| Append speedup range, small-output pipelines, both runs | **10.3x to 16.4x** at 1M rows, **11.4x to 33.1x** at 5M, **17.5x to 37.0x** at 20M | same |
| Append speedup, row-wise filter with a large output (the weak case) | **5.0x to 8.2x**; at 20M rows 0.766 s vs 6.2 s, 8.2x (7.6x in the second run) | same |
| First run (no saved state) | **0.7x to 1.4x** across all 30 measurements: about the same as pandas, not faster | same |
| Rerun with the file unchanged, default mode | 3 to 10 ms at 20M rows, **1,100x to 1,770x** for small-output pipelines (the size+mtime shortcut skips reading the file) | same |
| Rerun with the file unchanged, `INCPANDAS_CHECK=exact` (reads and hashes the whole file) | **11.4x to 29.9x** at 5M rows for small-output pipelines; 4.8x row-wise | `results_exact.json` |
| Where an append rerun goes at 20M rows, small-output pipelines | 94% to 102% is reading and hashing the whole file (about 0.27 s of 0.28 s; each part is timed on its own, so a part can slightly exceed 100%) | `results.json` (components) |
| Row-wise pipeline at 20M rows | 766 ms: about 47% loading saved output, 34% read + hash; saved output is 309 MB for a 199 MB CSV | `results.json` (components) |
| Saved state of a groupby / reduction | 1 to 4 KB | `results.json` (components) |
| Merge benchmark, 5M-row fact table + 100-row dimension table, append 1,000 rows | merge + groupby: 7 ms vs 1.80 s (**269.6x**); merged frame as output: 0.353 s vs 1.477 s (**4.2x**) | `docs/benchmarks/merge.txt`: `python examples/benchmark_merge.py 5000000 1000` (best of 3) |
| Large benchmark, 20M rows, filter + groupby | first run 7.9 s vs 10.0 s (1.3x); append 0.270 s vs 7.6 s (28.2x); no change 4 ms vs 7.5 s (1,714x) | `docs/benchmarks/large.txt`: `python examples/benchmark_large.py 20000000 1000` (best of 3) |
| Same with `INCPANDAS_CHECK=exact` | first run 1.4x; append 27.4x; no change 0.271 s vs 7.1 s (26.2x) | `docs/benchmarks/large_exact.txt`: `INCPANDAS_CHECK=exact python examples/benchmark_large.py 20000000 1000` |
| Live demo, `python examples/02_side_by_side.py` (1M rows, +1,000) | one measured run: first run 1.3x, append 13.4x, no change 56.4x. Timings change on every run | run on the same machine; rerun it before quoting |
| Tests | 997 collected, 993 passed, 4 skipped, about 14 s; `--fast`: 426 passed, 4 skipped | `python -m pytest -q` and `python -m pytest -q --fast` |
| Operations fuzz-tested against pandas | 81 (`tests/fuzz_ops.py`) | `python -c "import sys; sys.path.insert(0,'tests'); import fuzz_ops; print(len(fuzz_ops.OPS))"` |
| CI matrix | Python 3.10 (pandas 2.1, 2.2) and 3.12 (pandas 2.1, 2.2, 3.0, 3.1) | `.github/workflows/test.yml` |

## Say it like this

* "First runs are about the same speed as pandas. The gain comes on reruns."
* "On a 20M-row file, appending 1,000 rows and rerunning a groupby took about 0.28 s instead of about 7.5 s on this machine."
* "Pipelines that return a lot of rows gain less (5x to 8x here), because the saved output has to be loaded again."
* "The thousand-fold numbers are for an unchanged file, where incpandas trusts the file's size and modification time. With `INCPANDAS_CHECK=exact` the same rerun is about 11x to 30x at 5M rows."

## Do not say

* Anything about speed on a first run, or about other machines or pandas versions: not measured.
* A single "N times faster": the answer depends on the pipeline and file size.
* That the thousand-fold figure is incremental processing: it is the unchanged-file shortcut.
