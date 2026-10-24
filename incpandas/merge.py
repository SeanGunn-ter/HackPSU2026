"""Merge with new rows on the left side processed incrementally.

pandas keeps left order for how="inner"/"left", and each left row's matches depend only on
that row and the right frame. So while the right side is unchanged, merging just the
appended left rows and appending them equals the full merge. If the right side gains or
changes rows, old left rows can gain matches and the whole merge is recomputed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .nodes import Node, StateMismatch, _h

HOWS = ("inner", "left")


def plan_merge(lcols, rcols, how, on, suffixes):
    """Output columns of a supported merge (computed by pandas on empty frames), or None."""
    if lcols is None or rcols is None or how not in HOWS:
        return None
    if len(set(lcols)) != len(lcols) or len(set(rcols)) != len(rcols):
        return None
    keys = [on] if isinstance(on, str) else on
    if not (isinstance(keys, list) and keys and all(isinstance(k, str) for k in keys)
            and len(set(keys)) == len(keys) and all(k in lcols and k in rcols for k in keys)):
        return None
    if not (isinstance(suffixes, (tuple, list)) and len(suffixes) == 2
            and all(isinstance(x, str) for x in suffixes)):
        return None
    try:
        out = pd.DataFrame(columns=lcols).merge(pd.DataFrame(columns=rcols), how=how, on=on,
                                                suffixes=tuple(suffixes))
    except Exception:
        return None
    return list(out.columns)


class Merge(Node):
    kind = "Merge"

    def __init__(self, left, right, how, on, suffixes, columns):
        self.left, self.right = left, right
        self.parents = (left, right)
        self.how, self.on, self.suffixes = how, on, tuple(suffixes)
        self.columns = list(columns)
        self.sig = _h("merge", left.sig, right.sig, how, repr(on), repr(self.suffixes))

    def label(self):
        return f"{self.how} on {self.on!r}"

    def _merge(self, l, r):
        return l.merge(r, how=self.how, on=self.on, suffixes=self.suffixes)

    def stream(self, ctx):
        dl, rl = ctx.stream(self.left)
        dr, rr = ctx.stream(self.right)
        R = ctx.full(self.right)          # every run, so the right side's saved output stays current
        unchanged = (not rr) and len(dr) == 0
        out = None
        if not rl and unchanged:
            st = ctx.old_state(self)
            if st is None:
                raise StateMismatch(self.label())
            out = self._delta(self._merge(dl, R), st)
            if out is not None:
                out.index = pd.RangeIndex(st["n"], st["n"] + len(out))
                n = st["n"] + len(out)
                ctx.set_state(self, {"n": n, "dtypes": st["dtypes"]})
                if len(dl):
                    ctx.changed = True
                ctx.note(self, "incremental", len(dl))
                return out, False
        L = dl if rl else ctx.full(self.left)
        out = self._merge(L, R)
        ctx.set_state(self, {"n": len(out), "dtypes": list(out.dtypes)})
        ctx.changed = True
        ctx.note(self, "full", len(out))
        return out, True

    @staticmethod
    def _delta(out, st):
        """Bring a delta's dtypes in line with the previous output, or None to recompute.

        A delta that matches every row keeps an int column the full result holds as float
        (it has NaNs elsewhere). That one safe widening is applied; any other difference
        means the full merge may differ in type, so the caller recomputes in full.
        """
        want = st["dtypes"]
        if list(out.dtypes) == want:
            return out
        fix = {}
        for c, have, w in zip(out.columns, out.dtypes, want):
            if have == w:
                continue
            if w == np.float64 and have == np.int64 and len(out):
                fix[c] = w
            elif len(out) == 0:
                fix[c] = w
            else:
                return None
        try:
            return out.astype(fix)
        except (TypeError, ValueError):
            return None

    def replay(self, rep):
        return self._merge(rep(self.left), rep(self.right))
