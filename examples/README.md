# Examples

Every script makes its own data in a temporary folder, needs only `pandas`, `numpy` and incpandas
(`pip install -e .` from the repository root), and runs in under about 30 seconds with its defaults.
Each prints `INCPANDAS_LOG` lines such as `incpandas: processed 1,000 new rows, skipped 200,000 (4 incremental)`.

| Script | What it shows | Command |
|---|---|---|
| `01_quickstart.py` | a groupby on a CSV, then append rows and rerun | `python examples/01_quickstart.py` |
| `02_side_by_side.py` | plain pandas vs incpandas with timers: first run, append, no change; ends with `verify()` | `python examples/02_side_by_side.py` (options: `--rows 2000000 --append 5000`) |
| `03_merge.py` | fact + dimension table: a left append stays incremental, a right-side change recomputes in full | `python examples/03_merge.py` |
| `04_fallback_and_strict.py` | unsupported operations fall back and still match pandas; `StrictFallback`; `explain()` | `python examples/04_fallback_and_strict.py` |
| `05_edits_and_safety.py` | an edit, a truncation and a replaced file are detected and re-read in full | `python examples/05_edits_and_safety.py` |
| `06_plan_graphs.py` | writes the plan graphs to `docs/plans/` | `python examples/06_plan_graphs.py` (add `--png` for PNGs; needs `playwright` and a Chromium, set `CHROMIUM_PATH` to use a specific browser binary) |
| `07_realistic_logs.py` | web-access-log style data (text timestamps, status codes, bytes, endpoints): filter + groupby, append lines | `python examples/07_realistic_logs.py` (options: `--rows 1000000 --append 2000`) |

Older scripts:

| Script | What it does | Command |
|---|---|---|
| `demo.py` | the original append demo on 2M rows | `python examples/demo.py` |
| `benchmark.py` | the benchmark matrix (pipelines x sizes x scenarios) | `python examples/benchmark.py --help` |
| `benchmark_large.py` | one large file: first run, no change, append | `python examples/benchmark_large.py 5000000 1000` |
| `benchmark_merge.py` | fact table merged with a small dimension table | `python examples/benchmark_merge.py 2000000 1000` |

The benchmark scripts write their data to the system temp folder and do not delete it. Set `TMPDIR` to a folder you can clean up.
Saved plan graphs and their PNGs are in [`../docs/plans/`](../docs/plans/); benchmark results are in [`../docs/benchmarks/`](../docs/benchmarks/).
