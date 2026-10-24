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
- 2026-10-24: your inner-merge order fix is verified green on pandas 2.1.4, 2.2.3, 2.3.3, 3.0.6
  and 3.1.0 (959 passed on each of 2.3.3 and 3.1.0 locally). Note `_inner_keeps_left_order()`
  returns True *only* on pandas 3.1, so the fully incremental inner-merge branch runs on no
  other version; CI now includes a 3.1 row so both sides of that branch are covered.

### From A to B
- 2026-10-24: (1) engine.py:117 `run()` warns "incremental run failed ... recomputing from scratch"
  even when the error is genuine (plain pandas raises the same error and the from-scratch retry
  raises it too). Suggest holding the warning and emitting it only if the retry SUCCEEDS (then it
  really was an incremental-path/state problem). (2) CI matrix: please add pandas 3.1.* (py3.12) so
  the fast branch of merge.py's order probe is exercised; also consider 2.3.*. (3) CI is red on
  main for pandas 2.1 (inner merge row order); the fix is in progress on a/merge-order-fix.
