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
  command across py3.10/3.12 x pandas 2.1/2.2/3.0/3.1 (3.0 and 3.1 need py3.11+).

## Cross-track notes
Messages between A (core features) and B (infrastructure) go here. Add a dated bullet under
your own heading; delete it once the other person has acted on it.

### From B to A
- 2026-10-24: `tests/fuzz_ops.py` currently hard-codes the `k,a,b,n` schema, and some entries
  mutate the frame they are handed (`_assigned` does `df["c"] = ...`). B3's random-pipeline
  harness wants to compose registered ops over randomly generated schemas, which neither allows.
  B will likely need entries to declare the columns they require and to not mutate their input;
  B will propose the exact shape in the B3 PR before changing anything in that file.

### From A to B
- 2026-10-24: engine.py `run()` now holds the "incremental run failed" warning and emits it only
  if the from-scratch retry succeeds (A edited it, with tests in `tests/test_engine_log_strict.py`).
  Still open: add pandas 2.3.* to the CI matrix if wanted.
