# Run summary

Branch `docs/presentation`, cut from `main` at `e0dd3ff`. Nothing under `incpandas/`, `tests/`, `.github/` or `pyproject.toml` was changed. No PR was opened and nothing was merged. Commits carry no co-author or Claude attribution lines.

## What was added

| Path | What |
|---|---|
| `README.md` | rewritten (12 sections in the order you asked for) |
| `docs/presentation/numbers.md` | one-page sheet of headline numbers with method, machine, date and command |
| `docs/presentation/RUN_SUMMARY.md` | this file |
| `docs/benchmarks/results.json`, `results_run2.json` | full matrix (1M, 5M, 20M rows x 5 pipelines x 3 scenarios), run twice |
| `docs/benchmarks/results_exact.json` | 1M and 5M with `INCPANDAS_CHECK=exact` |
| `docs/benchmarks/large.txt`, `large_exact.txt`, `merge.txt` | output of `benchmark_large.py` (default and exact, 20M rows) and `benchmark_merge.py` (5M rows) |
| `docs/benchmarks/ENVIRONMENT.md`, `machine.json` | machine, versions, commit, every `INCPANDAS_*` value, exact commands and times |
| `docs/benchmarks/speedups.png/.svg`, `rerun_time_breakdown.png/.svg`, `append_seconds_vs_rows.png/.svg` | charts (read the JSON; matplotlib, Okabe-Ito colours, bars start at 0) |
| `docs/benchmarks/make_charts.py`, `make_tables.py`, `tables.md` | chart and table generators, and every table |
| `docs/plans/01..05_*.html` and `.png` | the five plan graphs (HTML 5 KB each, PNG about 60-80 KB each) |
| `examples/01..07_*.py`, `examples/README.md` | seven new examples and the index |
| `.gitignore` | added `*.csv`, `.cache/`, `incpandas-*/` |

Every example ran end to end (0.5 s to 10.4 s each). The README's two Python blocks ran and print the log line the text quotes. No data files or caches are committed, the largest committed file is under 210 KB, and all benchmark data lived in a scratch folder outside the repository that has been emptied.

## Headline numbers

Machine: sandbox with 4 vCPU Intel Xeon @ 2.10 GHz, about 16 GB RAM, Ubuntu 24.04, Python 3.13.17, pandas 3.0.5, numpy 2.5.3, 2026-10-25. One machine only. The 45-minute budget held: the timed benchmarks took about 35 minutes (matrix 14 min, second matrix 14 min, large/merge 4 min, exact matrix 3 min), repeats 5 (first run 2), nothing was stopped early, and 20M rows ran at full settings.

* Append 1,000 rows to a 20M-row (199 MB) CSV: filter + groupby 0.276 s vs 7.5 s (27.2x; 28.0x in run 2); left merge + groupby 37.0x (35.5x); column / formula sum 20.7x / 21.4x (17.5x / 20.3x).
* Small-output append speedups over both runs: 10.3x to 16.4x (1M), 11.4x to 33.1x (5M), 17.5x to 37.0x (20M).
* Row-wise pipeline with a large output: 5.0x to 8.2x. At 20M rows 766 ms, of which about 47% is loading the 309 MB saved output.
* First run: 0.7x to 1.4x over all 30 measurements. About the same as pandas, not faster.
* Unchanged file, default mode: 1,100x to 1,770x at 20M for small-output pipelines. This is the size+mtime shortcut. With `INCPANDAS_CHECK=exact` it is 11.4x to 29.9x at 5M.
* For small-output pipelines, reading and hashing the whole file is 94% to 102% of an append rerun at 20M rows.
* Tests: 997 collected, 993 passed, 4 skipped, about 14 s (`--fast`: 426 passed, 4 skipped).

## CI

CI (`tests`) does not run on pushes to this branch: the workflow triggers only on `main`, `a/**`, `b/**`, `kevin`, on PRs to `main` and by manual dispatch. I started it by hand with `workflow_dispatch` on this branch, run 31 on commit `63ae727`:

All six jobs finished with `success` (py3.10 with pandas 2.1 and 2.2; py3.12 with pandas 2.1, 2.2, 3.0 and 3.1): https://github.com/SeanGunn-ter/HackPSU2026/actions/runs/40153323302. That run is on the commit before this file was added; the only later change is this summary, so the code under test is identical.

## Decisions I made (unattended)

* Pushed `docs/presentation` as you asked, not the `claude/happy-hawking-oyfp8p` branch the session started on. That local branch was not touched.
* Used the sandbox's Python 3.13.17 / pandas 3.0.5. Python 3.13 is not in the CI matrix; the README says so.
* Used the default 1,000-row append for the matrix (no other append sizes). Ran the exact-mode comparison at 1M and 5M for the matrix, and at 20M with `benchmark_large.py`. Ran `benchmark_merge.py` at 5M rows.
* Added `make_tables.py`, `tables.md` and `machine.json` (the harness records no CPU model; the charts read it from `machine.json`).
* `06_plan_graphs.py` has an optional `--png` that needs Playwright. The Python `playwright` package (installed only in a scratch virtualenv) wanted a newer Chromium than the preinstalled one, so I pointed it at the installed binary with a `CHROMIUM_PATH` variable. The PNGs crop the SVG only, so there is no empty margin.
* The examples delete their own temp folders on exit.
* Example 04 shows a `median` groupby as an eager fallback (it returns a real pandas frame) and uses `agg(["sum", "max"])` for a planned fallback node, because only a planned node can appear red in the explain and the plan graph.
* The README quick start is a 6-line script plus a separate block that makes the sample file.
* Pinned the `numbers.md` rows to commands you can re-run, and left out anything I could not tie to one.

## Left out because I could not verify it

* The old README's benchmark table (Python 3.10, pandas 2.3.3, "one laptop"): not reproduced here, so it is gone.
* pandas 2.1 inner-merge behaviour: I ran the probes on 2.2.3, 3.0.5 and 3.1.0 only. The README says the code comments claim 2.1 recomputes both cases.
* The test suite on Python 3.10 / 3.12 and pandas 2.1 / 2.2 / 3.1: only the CI run above covers these; I ran the suite locally on 3.13 / pandas 3.0.5.
* Memory use, other append sizes (for example 100,000 rows), more than 20M rows, other machines, disk type (the sandbox disk is virtual; the kernel flag is meaningless).
* Behaviour with two processes on one cache: the README says there is no locking because the code has none; I did not test a race.

## Audit findings (code and docs, nothing was fixed)

Code vs the old README and docs:

1. Old README "Not done: cheap change detection ... saving only new rows instead of rewriting the output" is out of date: both exist (size+mtime shortcut, chunked output). Its "state is one pickle per plan" is now an index pickle plus `.chunk` files, and "a rerun hashes the whole file" no longer holds for an unchanged file.
2. Old README fallback list names `merge` and `.sum()` on a column as pandas fallbacks; both are incremental now.
3. `CLAUDE.md` says 963 tests and about 40 s (the old README also said `--fast` 396). Now: 997 collected (993 passed, 4 skipped), `--fast` 426 passed and 4 skipped, 14 s on this 4-core machine. `tests/conftest.py` repeats "about 40 seconds".
4. `INCPANDAS_VERIFY` is on for any non-empty value, including `0` (checked: `=0` still verifies), unlike `INCPANDAS_LOG` and `INCPANDAS_STRICT`, where `0` or empty is off. `engine._on` documents the rule but `frame.py` and `expr.py` read `INCPANDAS_VERIFY` with plain `os.environ.get`. No doc mentioned this. The README table says so.
5. Default change detection trusts `stat()`: a same-size edit with the modification time restored returned the old answer (checked); `INCPANDAS_CHECK=exact` returned the right one. This is by design but the old README did not say it plainly.
6. Quoted CSV header, or a file without a final newline: every run re-reads in full (checked, result still correct). Old README mentioned only the header.
7. `tests/test_fuzz_mutations.py` docstring says the right table is mutated in mode `(seed // 5) % 4`, but with the default `FUZZ_SEEDS=5` only mode 0 (unchanged) occurs. Right-table mutation is covered by `test_fuzz_ops.py` and `test_merge.py`, not by the mutation fuzz, unless `FUZZ_SEEDS` is raised.
8. CI: no pandas 2.3 job (already noted in `CLAUDE.md`), no Python 3.11 or 3.13 job, and no run on pushes to other branch names.

Stale comments, dead code, small bugs:

9. `incpandas/__init__.py` defines a function `merge`, so `import incpandas.merge as m` returns the function, not the module (had to use `sys.modules`).
10. `engine.fallback_log` is an unbounded list for the life of the process.
11. `frame.py`: the `assert_equal` line for floats has a long run of spaces before its message (a mangled line continuation; works, but looks wrong); `__array__` imports numpy again although it is imported at the top. `merge.py` `Merge.stream` sets `out = None` that is never used before reassignment.
12. Old cache files are never deleted for pipelines that are no longer run (checked: dozens of pickles and chunks accumulate).
13. `viz.py` colours come from the global `engine.last_run()`, which is replaced on every run. By reading the code (not tested): drawing plan A after running plan B shows A's nodes as "not run yet". `LazyFrame.graph/show` exist only after `from incpandas import viz`, which `CLAUDE.md` already notes.
14. `examples/benchmark_large.py` and `benchmark_merge.py` leave their temp folders behind (I set `TMPDIR` and cleaned up), and `benchmark.py` records only `processor: x86_64`, no CPU model.

Layout problems in `viz.py` (looked at the rendered PNGs of the merge, fallback and row-wise graphs; no overlapping text or lines found):

* Labels are cut at 30 characters and reasons at 32, with an ellipsis, and the full text is only in the hover tooltip. In a static HTML or PNG this loses information: the groupby label ends `[['revenue']…` and the fallback reason reads `aggregation not supported incre…`.
* The SVG is left-aligned inside a full-width box, so a small graph leaves a large empty area on the right on wide pages.

## What to double-check by hand

* Open two or three of `docs/plans/*.html` in your own browser (I only looked at PNG renders from headless Chromium).
* Run `python examples/02_side_by_side.py` on the presentation laptop before quoting any live number. The numbers sheet says to rerun it.
* Re-read the README sections on change detection and the benchmarks reading. The thousand-fold figures depend on the size+mtime shortcut, and the sheet and README both say so.
* Decide whether to correct `CLAUDE.md` (test counts, `INCPANDAS_VERIFY=0` behaviour). I did not touch it.
* Open the CI link above and confirm the six green jobs yourself.
