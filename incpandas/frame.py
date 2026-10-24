"""User-facing lazy wrappers: LazyFrame (a recorded plan) and LazyGroupBy."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import engine
from .expr import Col, Expr, _is_scalar, lift
from .groupby import GroupAgg
from .merge import Merge, plan_merge
from .nodes import Assign, Filter, Mem, Project
from .rowwise import AsType, DropNa, Drop, FillNa, Rename

_PD_ATTRS = set(dir(pd.DataFrame))
_GROUPBY_KW = {"as_index", "sort", "dropna"}


def unwrap(obj):
    """Replace lazy objects (nested in lists/tuples/dicts) with real pandas objects."""
    if isinstance(obj, LazyFrame):
        return obj.to_pandas()
    if isinstance(obj, LazyGroupBy):
        return obj._pandas()
    if isinstance(obj, Expr):
        return obj.compute()
    if isinstance(obj, (list, tuple)):
        return type(obj)(unwrap(o) for o in obj)
    if isinstance(obj, dict):
        return {k: unwrap(v) for k, v in obj.items()}
    return obj


def assert_equal(actual, expected):
    if isinstance(expected, pd.DataFrame):
        pd.testing.assert_frame_equal(actual, expected, check_exact=False, rtol=1e-7)
    elif isinstance(expected, pd.Series):
        pd.testing.assert_series_equal(actual, expected, check_exact=False, rtol=1e-7)
    else:
        assert type(actual) is type(expected), (actual, expected)
        if isinstance(expected, (float, np.floating)):
            assert (pd.isna(actual) and pd.isna(expected)) or np.isclose(actual, expected, rtol=1e-7, atol=0),                 (actual, expected)
        else:
            assert actual == expected, (actual, expected)


def _swap(frame, pdf):
    object.__setattr__(frame, "_node", Mem(pdf))


class _Indexer:
    """df.loc / df.iloc / df.at / df.iat: reads delegate; writes fall back and re-wrap."""

    def __init__(self, frame, name):
        self._frame, self._name = frame, name

    def __getitem__(self, key):
        return getattr(self._frame.to_pandas(), self._name)[unwrap(key)]

    def __setitem__(self, key, value):
        work = self._frame.to_pandas().copy()
        getattr(work, self._name)[unwrap(key)] = unwrap(value)
        _swap(self._frame, work)


class LazyFrame:
    _incpandas_lazy = True

    def __init__(self, node):
        object.__setattr__(self, "_node", node)

    # -- materialising -----------------------------------------------------
    def to_pandas(self):
        out = engine.materialize(self._node)
        if os.environ.get("INCPANDAS_VERIFY"):
            assert_equal(out, engine.replay(self._node))
        return out

    compute = to_pandas

    def verify(self):
        """Raise AssertionError unless the incremental result equals a full pandas run."""
        assert_equal(self.to_pandas(), engine.replay(self._node))
        return True

    def explain(self):
        """Text rendering of the plan: [+] runs incrementally, [x] falls back to pandas."""
        order, seen = [], set()

        def visit(n):
            if n.sig in seen:
                return
            seen.add(n.sig)
            for d in n.deps():
                visit(d)
            order.append(n)
        visit(self._node)
        idx = {n.sig: i for i, n in enumerate(order)}
        ran = engine.last_run()
        tty = os.isatty(1)
        lines = []
        for i, n in enumerate(order):
            mark, color = ("+", "32") if n.fast else ("x", "31")
            tag = f"[{mark}]"
            if tty:
                tag = f"\x1b[{color}m{tag}\x1b[0m"
            deps = ",".join(f"#{idx[d.sig]}" for d in n.deps())
            info = f"  <- {deps}" if deps else ""
            if n.sig in ran:
                info += f"  (last run: {ran[n.sig][0]}, {ran[n.sig][1]} rows)"
            elif n.why:
                info += f"  ({n.why})"
            lines.append(f"#{i} {tag} {n.kind}: {n.label()}{info}")
        return "\n".join(lines)

    def copy(self, deep=True):
        return LazyFrame(self._node)

    # -- lazy operations ---------------------------------------------------
    def __getitem__(self, key):
        node, cols = self._node, self._node.columns
        if isinstance(key, Expr):
            return LazyFrame(Filter(node, key))
        if cols is not None and isinstance(key, str) and key in cols:
            return Col(node, key)
        if (cols is not None and isinstance(key, list) and key
                and all(isinstance(k, str) and k in cols for k in key)):
            return LazyFrame(Project(node, key))
        engine.log_fallback("DataFrame.__getitem__")
        return self.to_pandas()[unwrap(key)]

    def __setitem__(self, key, value):
        node, cols = self._node, self._node.columns
        value = unwrap(value) if isinstance(value, LazyFrame) else value
        if cols is not None and isinstance(key, str):
            object.__setattr__(self, "_node", Assign(node, key, lift(value)))
            return
        engine.log_fallback("DataFrame.__setitem__")
        work = self.to_pandas().copy()
        work[unwrap(key)] = unwrap(value)
        _swap(self, work)

    def __delitem__(self, key):
        engine.log_fallback("DataFrame.__delitem__")
        work = self.to_pandas().copy()
        del work[key]
        _swap(self, work)

    def groupby(self, by=None, *args, **kwargs):
        cols = self._node.columns
        keys_ok = (cols is not None and not args and set(kwargs) <= _GROUPBY_KW
                   and ((isinstance(by, str) and by in cols)
                        or (isinstance(by, list) and by and all(isinstance(b, str) and b in cols for b in by))))
        if keys_ok:
            return LazyGroupBy(self._node, by, kwargs)
        engine.log_fallback("DataFrame.groupby")
        return self.to_pandas().groupby(unwrap(by), *unwrap(args), **unwrap(kwargs))

    # -- row-wise operations: incremental when the call qualifies, else pandas ---
    def _known_cols(self):
        cols = self._node.columns
        return cols if cols is not None and len(set(cols)) == len(cols) else None

    def _rowwise(self, node, inplace):
        if inplace:
            object.__setattr__(self, "_node", node)
            return None
        return LazyFrame(node)

    @staticmethod
    def _colnames(x, cols):
        """x as a list of distinct existing column names, or None."""
        names = [x] if isinstance(x, str) else x
        if (isinstance(names, list) and all(isinstance(n, str) and n in cols for n in names)
                and len(set(names)) == len(names)):
            return names
        return None

    def rename(self, *args, **kwargs):
        cols = self._known_cols()
        kw = dict(kwargs)
        inplace = kw.pop("inplace", False)
        m = kw.pop("columns", None)
        if (cols is not None and not args and not kw and inplace in (True, False)
                and isinstance(m, dict) and m):
            new = [m.get(c, c) for c in cols]
            if len(set(new)) == len(new):
                eff = {c: m[c] for c in cols if c in m}
                return self._rowwise(Rename(self._node, {"columns": eff}), inplace)
        return self._fallback("rename", args, kwargs)

    def drop(self, *args, **kwargs):
        cols = self._known_cols()
        kw = dict(kwargs)
        inplace = kw.pop("inplace", False)
        axis, target = kw.pop("axis", None), kw.pop("columns", None)
        labels, rest = kw.pop("labels", None), args
        if rest and labels is None:
            labels, rest = rest[0], rest[1:]
        if rest and axis is None:
            axis, rest = rest[0], rest[1:]
        if cols is not None and not rest and not kw and inplace in (True, False):
            if labels is not None and target is None and axis in (1, "columns"):
                target, labels = labels, None
            if labels is None and target is not None and axis in (None, 1, "columns"):
                names = self._colnames(target, cols)
                if names is not None:
                    return self._rowwise(Drop(self._node, {"columns": names}), inplace)
        return self._fallback("drop", args, kwargs)

    def astype(self, *args, **kwargs):
        cols = self._known_cols()
        kw = dict(kwargs)
        dtype = kw.pop("dtype", args[0] if len(args) == 1 else None)
        if cols is not None and dtype is not None and not kw and len(args) + ("dtype" in kwargs) == 1:
            norm = self._numeric_dtypes(dtype, cols)
            if norm is not None:
                return LazyFrame(AsType(self._node, {"dtype": norm}))
        return self._fallback("astype", args, kwargs)

    @staticmethod
    def _numeric_dtypes(dtype, cols):
        def one(t):
            try:
                dt = np.dtype(t)
            except (TypeError, ValueError):
                return None
            return str(dt) if dt.kind in "iuf" else None
        if isinstance(dtype, dict):
            if not dtype or not all(isinstance(k, str) and k in cols for k in dtype):
                return None
            out = {k: one(v) for k, v in dtype.items()}
            return out if all(v is not None for v in out.values()) else None
        return one(dtype)

    def dropna(self, *args, **kwargs):
        cols = self._known_cols()
        kw = dict(kwargs)
        inplace = kw.pop("inplace", False)
        axis = kw.pop("axis", 0)
        how, thresh = kw.pop("how", None), kw.pop("thresh", None)
        subset = kw.pop("subset", None)
        if (cols is not None and not args and not kw and inplace in (True, False)
                and axis in (0, "index") and how in (None, "any", "all")
                and (thresh is None or (isinstance(thresh, int) and not isinstance(thresh, bool)))
                and not (how is not None and thresh is not None)):
            params = {}
            if how is not None:
                params["how"] = how
            if thresh is not None:
                params["thresh"] = thresh
            names = None if subset is None else self._colnames(subset, cols)
            if subset is None or names is not None:
                if names is not None:
                    params["subset"] = names
                return self._rowwise(DropNa(self._node, params), inplace)
        return self._fallback("dropna", args, kwargs)

    def fillna(self, *args, **kwargs):
        cols = self._known_cols()
        kw = dict(kwargs)
        inplace = kw.pop("inplace", False)
        given = list(args) + ([kw.pop("value")] if "value" in kw else [])
        if (cols is not None and len(given) == 1 and len(args) <= 1 and not kw
                and inplace in (True, False) and self._scalar_fill(given[0], cols)):
            return self._rowwise(FillNa(self._node, {"value": dict(given[0]) if isinstance(given[0], dict) else given[0]}), inplace)
        return self._fallback("fillna", args, kwargs)

    @staticmethod
    def _scalar_fill(value, cols):
        if isinstance(value, dict):
            return bool(value) and all(isinstance(k, str) and k in cols and v is not None
                                       and _is_scalar(v) for k, v in value.items())
        return value is not None and _is_scalar(value)

    def assign(self, **kwargs):
        frame = LazyFrame(self._node)
        for key, val in kwargs.items():
            if callable(val) and not isinstance(val, (Expr, LazyFrame)):
                val = val(frame)
            frame[key] = val      # Assign when columns are known, else pandas fallback
        return frame

    def merge(self, right, how="inner", on=None, **kwargs):
        """Incremental for how=inner/left on named key columns of two lazy frames."""
        kw = dict(kwargs)
        suffixes = kw.pop("suffixes", ("_x", "_y"))
        if kw.pop("sort", False) is not False:
            kw["sort"] = True
        if isinstance(right, LazyFrame) and not kw and isinstance(how, str):
            cols = plan_merge(self._node.columns, right._node.columns, how, on, suffixes)
            if cols is not None:
                return LazyFrame(Merge(self._node, right._node, how, on, suffixes, cols))
        engine.log_fallback("DataFrame.merge")
        return self.to_pandas().merge(unwrap(right), how=how, on=on, **unwrap(kwargs))

    # -- everything else runs in real pandas --------------------------------
    def _fallback(self, name, args, kwargs):
        engine.log_fallback(f"DataFrame.{name}")
        if kwargs.get("inplace"):
            work = self.to_pandas().copy()
            out = getattr(work, name)(*unwrap(args), **unwrap(kwargs))
            _swap(self, work)
            return out
        return getattr(self.to_pandas(), name)(*unwrap(args), **unwrap(kwargs))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        cols = self._node.columns
        if name not in _PD_ATTRS and cols is not None and name in cols:
            return Col(self._node, name)
        if name in ("loc", "iloc", "at", "iat"):
            return _Indexer(self, name)
        engine.log_fallback(f"DataFrame.{name}")
        attr = getattr(self.to_pandas(), name)
        if not callable(attr):
            return attr

        def call(*a, **k):
            if k.get("inplace"):
                work = self.to_pandas().copy()
                out = getattr(work, name)(*unwrap(a), **unwrap(k))
                _swap(self, work)
                return out
            return attr(*unwrap(a), **unwrap(k))
        return call

    def __setattr__(self, name, value):
        if name.startswith("_"):
            return object.__setattr__(self, name, value)
        engine.log_fallback(f"DataFrame.{name} = ...")
        work = self.to_pandas().copy()
        setattr(work, name, unwrap(value))
        _swap(self, work)

    def __repr__(self):
        return repr(self.to_pandas())

    def __str__(self):
        return str(self.to_pandas())

    def _repr_html_(self):
        return self.to_pandas()._repr_html_()

    def __len__(self):
        return len(self.to_pandas())

    def __iter__(self):
        return iter(self.to_pandas())

    def __contains__(self, item):
        return item in self.to_pandas()

    def __bool__(self):
        return bool(self.to_pandas())

    def __array__(self, dtype=None, copy=None):
        import numpy as np
        return np.asarray(self.to_pandas(), dtype=dtype)

    def __array_ufunc__(self, ufunc, method, *inputs, **kwargs):
        return getattr(ufunc, method)(*[unwrap(i) for i in inputs], **kwargs)


def _delegate_dunder(name):
    def f(self, *args):
        return getattr(self.to_pandas(), name)(*unwrap(args))
    f.__name__ = name
    return f


for _n in ("add", "sub", "mul", "truediv", "floordiv", "mod", "pow", "and", "or", "xor"):
    setattr(LazyFrame, f"__{_n}__", _delegate_dunder(f"__{_n}__"))
    setattr(LazyFrame, f"__r{_n}__", _delegate_dunder(f"__r{_n}__"))
for _n in ("eq", "ne", "lt", "le", "gt", "ge", "neg", "pos", "invert", "abs"):
    setattr(LazyFrame, f"__{_n}__", _delegate_dunder(f"__{_n}__"))


class LazyGroupBy:
    def __init__(self, node, by, gkw, sel=None):
        self._node, self._by, self._gkw, self._sel = node, by, gkw, sel

    def _pandas(self):
        g = LazyFrame(self._node).to_pandas().groupby(self._by, **self._gkw)
        return g if self._sel is None else g[self._sel]

    def __getitem__(self, sel):
        cols = self._node.columns
        ok = self._sel is None and (
            (isinstance(sel, str) and sel in cols)
            or (isinstance(sel, list) and sel and all(isinstance(s, str) and s in cols for s in sel)))
        if ok:
            return LazyGroupBy(self._node, self._by, self._gkw, sel)
        engine.log_fallback("GroupBy.__getitem__")
        return self._pandas()[sel]

    def _agg(self, method, args, kwargs):
        node = GroupAgg(self._node, self._by, self._sel, self._gkw, (method, args, kwargs))
        return LazyFrame(node)

    def sum(self, *a, **k):
        return self._agg("sum", a, k)

    def count(self, *a, **k):
        return self._agg("count", a, k)

    def mean(self, *a, **k):
        return self._agg("mean", a, k)

    def min(self, *a, **k):
        return self._agg("min", a, k)

    def max(self, *a, **k):
        return self._agg("max", a, k)

    def agg(self, *a, **k):
        return self._agg("agg", a, k)

    aggregate = agg

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        engine.log_fallback(f"GroupBy.{name}")
        attr = getattr(self._pandas(), name)
        if not callable(attr):
            return attr
        return lambda *a, **k: attr(*unwrap(a), **unwrap(k))

    def __iter__(self):
        return iter(self._pandas())

    def __len__(self):
        return len(self._pandas())
