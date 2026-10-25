# Benchmark environment

All numbers in this folder come from one machine, on 2026-10-25. Timings differ between machines.

| | |
|---|---|
| Machine | cloud sandbox (Firecracker microVM), not a laptop |
| OS | Ubuntu 24.04.5 LTS, Linux 6.18.44 (x86_64) |
| CPU | Intel Xeon Processor @ 2.10 GHz, 4 vCPUs, 1 thread per core |
| RAM | 16,091 MB total (about 15.7 GiB), no swap |
| Disk | virtio block device (`/dev/vda`, 252 GB, 31 GB free at the start). The kernel reports `rotational=1`, but that flag is not meaningful for a virtual disk, so the physical disk type is unknown |
| Python | 3.13.17 |
| pandas | 3.0.5 |
| numpy | 2.5.3 |
| incpandas | 0.1.0, library code from commit `e0dd3ff70aaa66605586b8f9ef20fb5df5fb12f4` (`main`). The docs branch only adds files outside `incpandas/` |
| Charts | matplotlib 3.11.2 (not an incpandas dependency) |

Python 3.13 is not in the CI matrix (CI runs 3.10 and 3.12, see the README). The benchmarks ran on 3.13 because that is what the sandbox has.

Nothing else was running during the timed runs except the sandbox agent itself. While the benchmarks ran, the only
other activity was reading output and committing result files. No example script or test run overlapped a benchmark.

## Environment variables

| Variable | Value during the benchmarks |
|---|---|
| `INCPANDAS_CACHE` | set by `benchmark.py` to a fresh folder inside each cell's temp directory; `benchmark_large.py` and `benchmark_merge.py` set it to `.cache` in their own temp directory |
| `INCPANDAS_CHECK` | unset (default) for `results.json`, `results_run2.json`, `large.txt` and `merge.txt`; `exact` for `results_exact.json` and `large_exact.txt` |
| `INCPANDAS_LOG` | unset, except that `benchmark.py` turns it on for one extra append at the end of each cell to record the log line |
| `INCPANDAS_VERIFY` | unset (`benchmark.py` removes it if set, because it would replay every run in pandas) |
| `INCPANDAS_STRICT` | unset |
| `TMPDIR` | set to a scratch folder outside the repository, so every CSV and cache was written there and deleted afterwards |

## Runs and commands

Run from the repository root, with a Python that has incpandas and pandas installed.

| File | Command | Started (UTC) | Approx. duration |
|---|---|---|---|
| `results.json` | `python examples/benchmark.py --sizes 1000000,5000000,20000000 --appends 1000 --repeats 5 --cold-repeats 2 --json docs/benchmarks/results.json` | 01:22:46 | 14 min 14 s |
| `results_run2.json` | the same command, written to `results_run2.json` (a second, independent run) | 01:37:08 | 13 min 54 s |
| `large.txt` | `python examples/benchmark_large.py 20000000 1000` | 01:51:02 | 1 min 26 s |
| `large_exact.txt` | `INCPANDAS_CHECK=exact python examples/benchmark_large.py 20000000 1000` | 01:52:28 | 1 min 26 s |
| `merge.txt` | `python examples/benchmark_merge.py 5000000 1000` | 01:53:54 | 1 min 3 s |
| `results_exact.json` | `INCPANDAS_CHECK=exact python examples/benchmark.py --sizes 1000000,5000000 --appends 1000 --repeats 5 --cold-repeats 2 --json docs/benchmarks/results_exact.json` | 01:56:47 | 2 min 54 s |

Total timed benchmark time was about 35 minutes (the 45-minute budget was not exceeded and no run was stopped early). The harnesses were not modified. The 20M size was skipped in the exact
matrix to save time; `large_exact.txt` covers 20M for one pipeline.

Sizes: 1M, 5M and 20M rows were all run at full settings. 20M rows is a 199 MB CSV and the biggest saved state was 309 MB, which this machine handled
without swapping. Larger sizes were not tried.

## Change-detection modes

The code has two modes, set by `INCPANDAS_CHECK` (see the README): the default, which first compares the file's size and
modification time and skips reading when both match, and `exact`, which always reads and hashes the whole file. `exact` is the only value
the code looks for. `results_exact.json` and `large_exact.txt` compare the two. The tables are in `tables.md`.

## Regenerating

```
python docs/benchmarks/make_tables.py > docs/benchmarks/tables.md
python docs/benchmarks/make_charts.py        # needs matplotlib
```

`machine.json` holds the CPU model and RAM for the chart captions (the harness does not record them).
