"""incpandas: `import incpandas as pd` and reruns only process what changed.

Operations are recorded into a plan. On rerun, appended CSV rows are detected and only
that delta is pushed through the plan, using small saved state (per-group sums/counts,
the previous output). Anything unsupported runs in real pandas, so results stay correct.
"""
from __future__ import annotations

import os
import types

import pandas as _pd

from . import engine
from .engine import fallback_log, last_run
from .frame import LazyFrame, LazyGroupBy, unwrap
from .source import Source

__version__ = "0.1.0"

__all__ = ["read_csv", "check", "LazyFrame", "LazyGroupBy", "Source", "engine",
           "fallback_log", "last_run", "unwrap", "__version__"]

_CSV_KW = {"sep", "delimiter", "usecols", "dtype", "na_values", "keep_default_na",
           "encoding", "quotechar", "decimal"}
_COMPRESSED = (".gz", ".bz2", ".zip", ".xz", ".zst", ".tar", ".tgz")


def read_csv(filepath_or_buffer, **kwargs):
    """Lazy `pandas.read_csv` for plain local CSV files; otherwise plain pandas."""
    p = filepath_or_buffer
    plain = (isinstance(p, (str, os.PathLike)) and "://" not in str(p)
             and not str(p).lower().endswith(_COMPRESSED) and os.path.isfile(p)
             and set(kwargs) <= _CSV_KW)
    if not plain:
        engine.log_fallback("read_csv")
        return _pd.read_csv(p, **kwargs)
    columns = list(_pd.read_csv(p, nrows=0, **kwargs).columns)   # also surfaces pandas' own errors
    return LazyFrame(Source(p, kwargs, columns))


def check(obj):
    """Assert an incpandas result equals a from-scratch pandas run. Returns True."""
    return obj.verify()


def __getattr__(name):
    attr = getattr(_pd, name)
    if isinstance(attr, (types.FunctionType, types.BuiltinFunctionType)):
        def call(*a, **k):
            return attr(*unwrap(a), **unwrap(k))
        call.__name__ = name
        call.__doc__ = attr.__doc__
        return call
    return attr
