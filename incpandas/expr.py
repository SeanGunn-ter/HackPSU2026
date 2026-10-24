"""Lazy column expressions (`df.a * df.b`, `df.a > 3`, `df.name.str.upper()`).

An expression is a small tree that can be evaluated against any frame holding the
referenced columns. Everything in here is element-wise, so evaluating it on just the
appended rows gives the same values as evaluating it on all rows.
"""
from __future__ import annotations

import datetime
import operator
import os

import numpy as np
import pandas as pd

_BIN = {
    "add": (operator.add, "+"), "sub": (operator.sub, "-"), "mul": (operator.mul, "*"),
    "truediv": (operator.truediv, "/"), "floordiv": (operator.floordiv, "//"),
    "mod": (operator.mod, "%"), "pow": (operator.pow, "**"),
    "and": (operator.and_, "&"), "or": (operator.or_, "|"), "xor": (operator.xor, "^"),
    "eq": (operator.eq, "=="), "ne": (operator.ne, "!="), "lt": (operator.lt, "<"),
    "le": (operator.le, "<="), "gt": (operator.gt, ">"), "ge": (operator.ge, ">="),
}
_UN = {"neg": (operator.neg, "-"), "pos": (operator.pos, "+"),
       "invert": (operator.invert, "~"), "abs": (abs, "abs")}

# Methods that act on each value independently, so delta-evaluation is exact.
_ELEMENTWISE = {"isin", "between", "isna", "isnull", "notna", "notnull", "abs", "round", "fillna"}
_STR_ELEMENTWISE = {"upper", "lower", "len", "strip", "lstrip", "rstrip", "contains",
                    "startswith", "endswith", "replace", "title", "capitalize"}

_REDUCTIONS = {"sum", "mean", "min", "max", "count"}

_SCALARS = (type(None), bool, int, float, complex, str, bytes, datetime.date,
            datetime.timedelta, np.generic, pd.Timedelta)
_PANDAS_LIKE = (pd.Series, pd.DataFrame, pd.Index, np.ndarray)


def _is_scalar(x):
    return isinstance(x, _SCALARS) or x is pd.NA or x is pd.NaT


def _asig(x):
    return x.sig if isinstance(x, Expr) else repr(x)


def _atext(x):
    return x.text if isinstance(x, Expr) else repr(x)


def _is_lazy_frame(x):
    return hasattr(type(x), "_incpandas_lazy")


def lift(x):
    if isinstance(x, Expr):
        return x
    if _is_scalar(x):
        return Lit(x)
    if _is_lazy_frame(x):
        x = x.to_pandas()
    return Static(x)


class Expr:
    nodes: frozenset = frozenset()   # plan nodes whose columns this expression reads
    opaque = False                   # True if not safely evaluable on a delta alone
    sig = ""
    text = ""
    __hash__ = object.__hash__

    def eval(self, res):
        """Evaluate; `res(node)` returns the frame for a plan node."""
        raise NotImplementedError

    # -- materialising -----------------------------------------------------
    def compute(self):
        from . import engine
        return engine.run_expr(self)

    def __repr__(self):
        return repr(self.compute())

    __str__ = __repr__

    def _repr_html_(self):
        return self.compute()._repr_html_()

    def __len__(self):
        return len(self.compute())

    def __iter__(self):
        return iter(self.compute())

    def __getitem__(self, key):
        return self.compute()[key]

    def __bool__(self):
        return bool(self.compute())

    def __float__(self):
        return float(self.compute())

    def __int__(self):
        return int(self.compute())

    def __array__(self, dtype=None, copy=None):
        return np.asarray(self.compute(), dtype=dtype)

    def __format__(self, spec):
        return format(self.compute(), spec)

    def __array_ufunc__(self, ufunc, method, *inputs, **kwargs):
        inputs = [i.compute() if isinstance(i, Expr) else i for i in inputs]
        return getattr(ufunc, method)(*inputs, **kwargs)

    # -- operators ---------------------------------------------------------
    def __neg__(self):
        return Unary("neg", self)

    def __pos__(self):
        return Unary("pos", self)

    def __invert__(self):
        return Unary("invert", self)

    def __abs__(self):
        return Unary("abs", self)

    # -- methods -----------------------------------------------------------
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in _ELEMENTWISE:
            return lambda *a, **k: Method(self, name, a, k)
        if name == "str":
            return _StrAccessor(self)
        if name in _REDUCTIONS:
            return lambda *a, **k: self._reduce(name, a, k)
        # Anything else (map, rank, ...): run for real in pandas.
        from . import engine
        engine.log_fallback(f"Series.{name}")
        return getattr(self.compute(), name)

    def _reduce(self, name, args, kwargs):
        """df.a.sum() / (df.a * 2).sum() etc.: running totals when called bare, else real pandas."""
        from . import engine
        if args or kwargs:
            engine.log_fallback(f"Series.{name}")
            return getattr(self.compute(), name)(*args, **kwargs)
        from .reduce import Reduce, reduction_input
        if type(self) is Col:
            node = Reduce(self.node, self.name, name)
        else:
            src = reduction_input(self)
            if src is None:
                engine.log_fallback(f"Series.{name}")
                return getattr(self.compute(), name)()
            node = Reduce(src[0], src[1], name)
        out = engine.materialize(node)
        if os.environ.get("INCPANDAS_VERIFY"):
            from .frame import assert_equal
            assert_equal(out, engine.replay(node))
        return out


def _install_ops():
    for n in ("add", "sub", "mul", "truediv", "floordiv", "mod", "pow", "and", "or", "xor"):
        def fwd(self, other, _n=n):
            return BinOp(_n, self, lift(other))

        def rev(self, other, _n=n):
            return BinOp(_n, lift(other), self)
        setattr(Expr, f"__{n}__", fwd)
        setattr(Expr, f"__r{n}__", rev)
    for n in ("eq", "ne", "lt", "le", "gt", "ge"):
        def cmp(self, other, _n=n):
            return BinOp(_n, self, lift(other))
        setattr(Expr, f"__{n}__", cmp)


_install_ops()


class Col(Expr):
    def __init__(self, node, name):
        self.node, self.name = node, name
        self.nodes = frozenset([node])
        self.sig = f"{node.sig[:12]}.{name}"
        self.text = str(name)

    def eval(self, res):
        return res(self.node)[self.name]


class Lit(Expr):
    def __init__(self, value):
        self.value = value
        self.sig = f"lit:{type(value).__name__}:{value!r}"
        self.text = repr(value)

    def eval(self, res):
        return self.value


class Static(Expr):
    """A concrete pandas/numpy/list value mixed into an expression."""
    opaque = True

    def __init__(self, obj):
        self.obj = obj
        n = len(obj) if hasattr(obj, "__len__") else ""
        self.sig = f"static:{type(obj).__name__}:{n}"
        self.text = f"<{type(obj).__name__}>"

    def eval(self, res):
        return self.obj


class BinOp(Expr):
    def __init__(self, op, left, right):
        self.op, self.left, self.right = op, left, right
        self.nodes = left.nodes | right.nodes
        self.opaque = left.opaque or right.opaque
        self.sig = f"({left.sig} {op} {right.sig})"
        self.text = f"({left.text} {_BIN[op][1]} {right.text})"

    def eval(self, res):
        return _BIN[self.op][0](self.left.eval(res), self.right.eval(res))


class Unary(Expr):
    def __init__(self, op, x):
        self.op, self.x = op, x
        self.nodes, self.opaque = x.nodes, x.opaque
        self.sig = f"{op}({x.sig})"
        self.text = f"{_UN[op][1]}({x.text})"

    def eval(self, res):
        return _UN[self.op][0](self.x.eval(res))


class Method(Expr):
    def __init__(self, base, name, args, kwargs, accessor=None):
        self.base, self.name, self.args, self.kwargs, self.accessor = base, name, args, kwargs, accessor
        parts = [base] + [a for a in (*args, *kwargs.values()) if isinstance(a, Expr)]
        self.nodes = frozenset().union(*(p.nodes for p in parts))
        raw = [a for a in (*args, *kwargs.values()) if not isinstance(a, Expr)]
        self.opaque = (any(p.opaque for p in parts)
                       or any(isinstance(a, _PANDAS_LIKE) or _is_lazy_frame(a) for a in raw))
        acc = f"{accessor}." if accessor else ""
        a_sig = ",".join([_asig(a) for a in args] + [f"{k}={_asig(v)}" for k, v in sorted(kwargs.items())])
        a_txt = ",".join([_atext(a) for a in args] + [f"{k}={_atext(v)}" for k, v in sorted(kwargs.items())])
        self.sig = f"{base.sig}.{acc}{name}({a_sig})"
        self.text = f"{base.text}.{acc}{name}({a_txt})"

    def eval(self, res):
        def ev(a):
            return a.eval(res) if isinstance(a, Expr) else a
        v = self.base.eval(res)
        if self.accessor:
            v = getattr(v, self.accessor)
        return getattr(v, self.name)(*[ev(a) for a in self.args],
                                     **{k: ev(x) for k, x in self.kwargs.items()})


class _StrAccessor:
    def __init__(self, base):
        self._base = base

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in _STR_ELEMENTWISE:
            return lambda *a, **k: Method(self._base, name, a, k, accessor="str")
        from . import engine
        engine.log_fallback(f"Series.str.{name}")
        return getattr(self._base.compute().str, name)
