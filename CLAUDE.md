# Conventions

## Workflow
- Branches are `a/<topic>` or `b/<topic>`, cut from `main`. Keep PRs small (<300 lines).
- A PR may merge only if `python -m pytest -q` passes (tests run with `INCPANDAS_VERIFY=1`).
- Never add Co-Authored-By, "Generated with Claude", or session links to commits or PR text.

## Correctness
- If unsure, fall back to pandas. Never return a wrong result.

## Frozen interfaces
Tell the other person before changing any of these:
- Node interface: `kind`, `label()`, `fast`, `why`, `deps()`, `sig`, `columns`, `stream(ctx)`, `replay(rep)`.
- Ctx interface: `stream`, `full`, `old_state`, `set_state`, `clear_state`, `note`, `changed`.
- Public API: `read_csv`, `check`, `LazyFrame.to_pandas/verify/explain`, `engine.last_run()`.

## Tests
- Every new operation needs an entry in `tests/fuzz_ops.py` once that file exists.
