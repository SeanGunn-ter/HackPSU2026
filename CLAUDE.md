# Conventions

## Workflow
- A PR may merge only if `python -m pytest -q` passes (tests run with `INCPANDAS_VERIFY=1`).

## Correctness
- If unsure, fall back to pandas. Never return a wrong result.

## Frozen interfaces
Tell the other person before changing any of these:
- Node interface: `kind`, `label()`, `fast`, `why`, `deps()`, `sig`, `columns`, `stream(ctx)`, `replay(rep)`.
- Ctx interface: `stream`, `full`, `old_state`, `set_state`, `clear_state`, `note`, `changed`.
- Public API: `read_csv`, `check`, `LazyFrame.to_pandas/verify/explain`, `engine.last_run()`.

## Tests
- Every new operation needs an entry in `tests/fuzz_ops.py` once that file exists.

## Local setup
- `py -3.10 -m venv .venv && .venv/Scripts/python.exe -m pip install -e ".[dev]"`, then
  `.venv/Scripts/python.exe -m pytest -q`. CI (`.github/workflows/test.yml`) runs the same
  command across py3.10/3.12 x pandas 2.1/2.2/3.0.

## Cross-track notes
Messages between A (core features) and B (infrastructure) go here. Add a dated bullet under
your own heading; delete it once the other person has acted on it.

### From B to A
- 2026-10-24: `tests/test_reductions.py::test_dtype_change_falls_back_then_recovers` fails on
  every pandas 2.x (2.1.4, 2.2.3, 2.3.3) and passes only on pandas 3.0+. Cause is plain pandas,
  not incpandas: on pandas 2.x, `Series.min()/.max()` over an object column that contains a real
  NaN raises `TypeError: '<=' not supported between instances of 'str' and 'float'` (nanops fills
  the NaN with +/-inf and then compares it to a string). pandas 3.0 handles it. incpandas'
  fallback path faithfully reproduces whichever behaviour the installed pandas has, so the fix
  belongs in the test: gate the `min`/`max` part of that step on pandas >= 3, or assert that it
  raises on 2.x. `count` is fine on both. Since `pyproject.toml` declares `pandas>=2.1`, the test
  suite should pass there too. Your file, so leaving it to you.
- 2026-10-24: `tests/fuzz_ops.py` currently hard-codes the `k,a,b,n` schema, and some entries
  mutate the frame they are handed (`_assigned` does `df["c"] = ...`). B3's random-pipeline
  harness wants to compose registered ops over randomly generated schemas, which neither allows.
  B will likely need entries to declare the columns they require and to not mutate their input;
  B will propose the exact shape in the B3 PR before changing anything in that file.

- 2026-10-24: `INCPANDAS_STRICT=1` now raises `engine.StrictFallback` from `engine.log_fallback`
  and from `Ctx.note(..., "fallback", ...)`, so every fallback path in your files reports through
  it for free -- no change needed on your side, just keep routing fallbacks through those two.
  When convenient, please add `StrictFallback` to `__all__` in `__init__.py` (your file) so users
  can write `except pd.StrictFallback`; until then it is `incpandas.engine.StrictFallback`.

- 2026-10-24: `main` is red: 9 merge tests fail, all of them `how="inner"`. Verified they fail
  with my `engine.py` changes reverted, so this came in with A3, not with B1.
  `test_left_append_is_incremental_and_exact[k-inner]`, `[suffixes-inner]`,
  `test_right_changes_recompute_in_full[inner]`, `test_fuzz_ops[merge_default_suffixes-0/-1]`,
  `test_fuzz_mutations[merge_inner_k-2]`, `[merge_default_suffixes-2]`, `[merge_twice-0/-2]`.
  Cause is row order, not row content: appending the delta's joined rows to the previous output
  keeps left-row order, but pandas' inner merge groups output by left key. Got `[x,y,y,z,y,y,x]`
  where pandas gives `[x,y,y,y,y,z,x]`. The A3 design note ("output row order identical to
  pandas") holds for `how="left"` but not for `how="inner"`. Every `how="left"` case passes.
  Either reindex/reorder the inner result to match, or make inner joins return `reset=True`
  (correct but not incremental) until that is sorted. `merge.py` is yours, so leaving it to you.

### From A to B
- (none yet)
