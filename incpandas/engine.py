"""Executes a plan against persisted state.

State lives in one pickle per plan fingerprint (`<cache_dir>/<sig>.pkl`) and is written
atomically, so a crash can't leave sources and aggregates out of sync. If anything about
the saved state looks off, or the incremental path raises, we recompute from scratch.

Two environment variables make a run observable:
`INCPANDAS_LOG=1` prints one summary line per run, `INCPANDAS_STRICT=1` raises
`StrictFallback` instead of quietly handing work to pandas.
"""
from __future__ import annotations

import logging
import os
import pickle
import warnings
from collections import Counter

import pandas as pd

from .nodes import StateMismatch

VERSION = 1
log = logging.getLogger("incpandas")

fallback_log: list = []   # names of pandas calls that ran eagerly in real pandas
_last: dict = {}          # node sig -> (mode, rows) from the most recent run


class StrictFallback(RuntimeError):
    """Raised in place of a fallback to pandas when INCPANDAS_STRICT=1."""


def _on(name):
    """True when an INCPANDAS_* flag is set to anything other than "" or "0"."""
    return os.environ.get(name, "") not in ("", "0")


def cache_dir():
    return os.environ.get("INCPANDAS_CACHE", ".incpandas_cache")


def last_run():
    return dict(_last)


def log_fallback(what):
    if _on("INCPANDAS_STRICT"):
        raise StrictFallback(f"{what} ran in pandas (INCPANDAS_STRICT=1)")
    fallback_log.append(what)
    log.info("incpandas: falling back to pandas for %s", what)


class Ctx:
    def __init__(self, state):
        self._old = state or {"run": 0, "nodes": {}, "full": {}}
        self.prev_run = self._old["run"]
        self.run_id = self.prev_run + 1
        self.new_nodes, self.new_full = {}, {}
        self._stream, self._full, self.notes = {}, {}, {}
        self.changed = False

    # per-node persisted state, only trusted if written by the immediately preceding run
    def old_state(self, node):
        st = self._old["nodes"].get(node.sig)
        return st if st is not None and st.get("run") == self.prev_run else None

    def set_state(self, node, st):
        self.new_nodes[node.sig] = {**st, "run": self.run_id}

    def clear_state(self, node):
        self.new_nodes.pop(node.sig, None)

    def note(self, node, mode, rows):
        # A Mem node holds a frame that was already materialised, so whatever produced it
        # has reported its own fallback; don't raise a second time for it.
        if mode == "fallback" and node.kind != "Mem" and _on("INCPANDAS_STRICT"):
            raise StrictFallback(f"{node.label()} ran in pandas (INCPANDAS_STRICT=1)")
        self.notes[node.sig] = (mode, rows)

    def stream(self, node):
        if node.sig not in self._stream:
            self._stream[node.sig] = node.stream(self)
        return self._stream[node.sig]

    def full(self, node):
        """The node's complete output: previous full output + this run's delta."""
        if node.sig in self._full:
            return self._full[node.sig]
        d, reset = self.stream(node)
        if reset:
            out = d
        else:
            ent = self._old["full"].get(node.sig)
            if ent is None or ent[1] != self.prev_run:
                raise StateMismatch(node.label())
            out = ent[0] if len(d) == 0 else pd.concat([ent[0], d])
        self.new_full[node.sig] = (out, self.run_id)
        self._full[node.sig] = out
        return out


def _path(sig):
    return os.path.join(cache_dir(), sig[:32] + ".pkl")


def _load(sig):
    try:
        with open(_path(sig), "rb") as f:
            st = pickle.load(f)
        return st if st.get("v") == VERSION else None
    except Exception:
        return None


def _save(sig, ctx):
    os.makedirs(cache_dir(), exist_ok=True)
    path = _path(sig)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        pickle.dump({"v": VERSION, "run": ctx.run_id, "nodes": ctx.new_nodes, "full": ctx.new_full},
                    f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def summary(ctx):
    """One line describing a finished run: rows fed in, rows not re-read, node modes."""
    processed = skipped = 0
    for sig, st in ctx.new_nodes.items():
        if "nrows" not in st:            # only sources keep a row count
            continue
        total = st["nrows"]
        rows = ctx.notes.get(sig, ("full", total))[1]
        processed += rows
        skipped += max(total - rows, 0)
    modes = Counter(mode for mode, _ in ctx.notes.values())
    detail = ", ".join(f"{n} {mode}" for mode, n in sorted(modes.items()))
    line = f"incpandas: processed {processed:,} new rows, skipped {skipped:,}"
    return f"{line} ({detail})" if detail else line


def run(sig, fn):
    """Run `fn(ctx)` incrementally against the state for `sig`; retry from scratch on trouble."""
    state = _load(sig)
    failed = None            # held until the from-scratch retry shows the failure was ours
    for st in ([state, None] if state is not None else [None]):
        ctx = Ctx(st)
        try:
            out = fn(ctx)
        except Exception as e:
            if st is None or isinstance(e, StrictFallback):
                raise
            if not isinstance(e, StateMismatch):
                failed = e
            continue
        if failed is not None:   # the retry succeeded, so the error came from the incremental path
            warnings.warn(f"incpandas: incremental run failed ({failed!r}); recomputed from scratch")
        if st is None or ctx.changed:
            try:
                _save(sig, ctx)
            except OSError as e:
                warnings.warn(f"incpandas: could not save state ({e})")
        _last.clear()
        _last.update(ctx.notes)
        if _on("INCPANDAS_LOG"):
            print(summary(ctx))
        return out


def materialize(node):
    return run(node.sig, lambda ctx: ctx.full(node))


def run_expr(expr):
    frames = {n.sig: materialize(n) for n in expr.nodes}
    return expr.eval(lambda n: frames[n.sig])


def replay(node):
    """Evaluate the plan with real pandas only, ignoring all state (the correctness oracle)."""
    memo = {}

    def rep(n):
        if n.sig not in memo:
            memo[n.sig] = n.replay(rep)
        return memo[n.sig]
    return rep(node)
