"""Plan nodes. Each node knows how to (a) run incrementally and (b) replay in plain pandas.

`stream(ctx)` returns `(df, reset)`:
  * reset=False -> `df` holds only rows appended since the last run
  * reset=True  -> `df` is the complete output; downstream state must be rebuilt
"""
from __future__ import annotations

import hashlib
import uuid

import pandas as pd


def _h(*parts):
    return hashlib.sha1("\x00".join(map(str, parts)).encode()).hexdigest()


class StateMismatch(Exception):
    """Saved state doesn't line up with this run; caller recomputes from scratch."""


class Node:
    kind = "Node"
    fast = True          # statically known to run incrementally
    parents: tuple = ()
    columns = None       # known output columns, or None if unknown / not a frame
    sig = ""
    why = ""             # why a node is not incremental

    def deps(self):
        return self.parents

    def label(self):
        return self.kind



class Mem(Node):
    """An in-memory frame produced by a pandas fallback (never incremental)."""
    kind = "Mem"
    fast = False
    why = "in-memory result of a pandas fallback"

    def __init__(self, df):
        self.df = df
        self.columns = list(df.columns)
        try:
            tag = int(pd.util.hash_pandas_object(df, index=True).sum())
        except Exception:
            tag = uuid.uuid4().hex
        self.sig = _h("mem", tag, tuple(map(str, df.dtypes)), tuple(map(str, df.columns)))

    def label(self):
        return f"in-memory frame {self.df.shape}"

    def stream(self, ctx):
        ctx.note(self, "fallback", len(self.df))
        return self.df, True

    def replay(self, rep):
        return self.df.copy()


class _ExprNode(Node):
    """Shared logic for nodes driven by one expression over one parent."""

    def _setup(self, parent, expr):
        self.parent, self.expr = parent, expr
        self.parents = (parent,)
        self.foreign = {n.sig: n for n in expr.nodes if n.sig != parent.sig}
        self.fast = not expr.opaque and not self.foreign
        if expr.opaque:
            self.why = "mixes in a concrete pandas/numpy value"
        elif self.foreign:
            self.why = "reads columns from another frame"

    def deps(self):
        return (self.parent, *self.foreign.values())

    def _resolver(self, ctx):
        full_parent = ctx.full(self.parent)
        return lambda n: full_parent if n.sig == self.parent.sig else ctx.full(n)


class Assign(_ExprNode):
    kind = "Assign"

    def __init__(self, parent, col, expr):
        self.col = col
        self._setup(parent, expr)
        cols = parent.columns
        self.columns = None if cols is None else cols + ([] if col in cols else [col])
        self.sig = _h("assign", parent.sig, col, expr.sig)

    def label(self):
        return f"{self.col} = {self.expr.text}"

    def stream(self, ctx):
        if self.fast:
            d, reset = ctx.stream(self.parent)
            val = self.expr.eval(lambda n: d)
            out = d.copy(deep=False)
            out[self.col] = val
            ctx.note(self, "full" if reset else "incremental", len(d))
            return out, reset
        full = ctx.full(self.parent)
        out = full.copy()
        out[self.col] = self.expr.eval(self._resolver(ctx))
        ctx.note(self, "fallback", len(out))
        return out, True

    def replay(self, rep):
        out = rep(self.parent).copy()
        out[self.col] = self.expr.eval(rep)
        return out


class Filter(_ExprNode):
    kind = "Filter"

    def __init__(self, parent, expr):
        self._setup(parent, expr)
        self.columns = parent.columns
        self.sig = _h("filter", parent.sig, expr.sig)

    def label(self):
        return self.expr.text

    def stream(self, ctx):
        if self.fast:
            d, reset = ctx.stream(self.parent)
            out = d[self.expr.eval(lambda n: d)]
            ctx.note(self, "full" if reset else "incremental", len(d))
            return out, reset
        full = ctx.full(self.parent)
        out = full[self.expr.eval(self._resolver(ctx))]
        ctx.note(self, "fallback", len(out))
        return out, True

    def replay(self, rep):
        return rep(self.parent)[self.expr.eval(rep)]


class Project(Node):
    kind = "Project"

    def __init__(self, parent, cols):
        self.parent, self.parents, self.cols = parent, (parent,), list(cols)
        self.columns = list(cols)
        self.sig = _h("project", parent.sig, repr(self.cols))

    def label(self):
        return repr(self.cols)

    def stream(self, ctx):
        d, reset = ctx.stream(self.parent)
        ctx.note(self, "full" if reset else "incremental", len(d))
        return d[self.cols], reset

    def replay(self, rep):
        return rep(self.parent)[self.cols]
