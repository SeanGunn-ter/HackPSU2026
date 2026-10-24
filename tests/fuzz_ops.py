"""Registry of operations for the append fuzzer.

Every new operation needs an entry in OPS (CLAUDE.md). An entry maps a name to a function
that takes a frame (incpandas or plain pandas; both share the API) and returns a frame,
Series or scalar. test_fuzz_ops.py feeds each one random CSV data with random appends and
checks the incpandas result equals plain pandas, in value and type.

Columns of the generated data: k (str key), a (int), b (float, power-of-two values so
sums are exact, some zeros), n (float with NaN).
Merge ops also read r.csv (the "right" table): k (key; duplicates, keys that never appear on
the left, sometimes empty), v (int), w (text).
"""
import pandas as plain

import incpandas as pd


def _right(df):
    """The right-hand frame, using the same API as `df` (plain pandas or incpandas)."""
    return (plain if isinstance(df, plain.DataFrame) else pd).read_csv("r.csv")


def _plain_right(df):
    return plain.read_csv("r.csv")


def _mod(df):
    return plain if isinstance(df, plain.DataFrame) else pd



def _assigned(df):
    df["c"] = df.a * 2
    return df


OPS = {
    # row-wise (rowwise.py)
    "rename": lambda df: df.rename(columns={"a": "aa", "k": "key"}),
    "drop": lambda df: df.drop(columns=["b", "n"]),
    "astype": lambda df: df.astype({"b": "float32", "a": "float64"}),
    "dropna": lambda df: df.dropna(),
    "dropna_subset_how": lambda df: df.dropna(subset=["n"], how="any"),
    "dropna_thresh": lambda df: df.dropna(thresh=3),
    "fillna": lambda df: df[["a", "b", "n"]].fillna(0),
    "fillna_dict": lambda df: df.fillna({"n": -1.0, "b": 0.5}),
    "assign": lambda df: df.assign(c=df.a * 2, d=lambda x: x.c + x.b),
    # reductions on a bare column
    **{f"col_{f}": (lambda df, f=f: getattr(df.a, f)()) for f in ("sum", "mean", "min", "max", "count")},
    # reductions on a formula (expr.py / reduce.py)
    **{f"formula_{f}": (lambda df, f=f: getattr(df.a * df.b, f)()) for f in ("sum", "mean", "min", "max", "count")},
    **{f"formula_nan_{f}": (lambda df, f=f: getattr(df.n + 1, f)()) for f in ("sum", "mean", "min", "max", "count")},
    **{f"formula_div_{f}": (lambda df, f=f: getattr(df.a / df.b, f)()) for f in ("sum", "mean", "min", "max", "count")},
    **{f"formula_filtered_{f}": (lambda df, f=f: getattr((lambda g: g.a + g.b)(df[df.a > 2]), f)())
       for f in ("sum", "mean", "min", "max", "count")},
    **{f"formula_assigned_{f}": (lambda df, f=f: getattr((lambda g: -g.c)(_assigned(df)), f)())
       for f in ("sum", "mean", "min", "max", "count")},
    # boolean formulas: sum/count/mean are incremental, min/max fall back to pandas
    **{f"bool_{f}": (lambda df, f=f: getattr(df.a > 3, f)()) for f in ("sum", "count", "mean", "min", "max")},
    # merge (merge.py): new rows on the left are incremental
    "merge_inner_k": lambda df: df.merge(_right(df), on="k"),
    "merge_left_k": lambda df: df.merge(_right(df), how="left", on="k"),
    "merge_inner_ka": lambda df: df.merge(_right(df).rename(columns={"v": "a"}), on=["k", "a"]),
    "merge_left_ka": lambda df: df.merge(_right(df).rename(columns={"v": "a"}), how="left", on=["k", "a"]),
    "merge_suffixes": lambda df: df.merge(_right(df).rename(columns={"v": "b"}), how="left", on="k",
                                          suffixes=("_l", "_r")),
    "merge_default_suffixes": lambda df: df.merge(_right(df).rename(columns={"v": "b"}), on="k"),
    "merge_module_fn": lambda df: _mod(df).merge(df, _right(df), how="left", on="k"),
    "merge_then_groupby": lambda df: df.merge(_right(df), how="left", on="k").groupby("k")[["a", "v"]].sum(),
    "merge_twice": lambda df: (df.merge(_right(df), how="left", on="k")
                               .merge(_right(df).rename(columns={"v": "v2", "w": "w2"}), on="k")),
    "merge_after_filter_assign": lambda df: (lambda g: g.assign(c=g.a * 2).merge(_right(df), how="left", on="k"))(
        df[df.a > 0]),
    "merge_then_reduction": lambda df: df.merge(_right(df), how="left", on="k").v.sum(),
    "merge_then_formula_reduction": lambda df: (lambda m: (m.a * m.v).sum())(df.merge(_right(df), on="k")),
    "merge_then_mean": lambda df: df.merge(_right(df), how="left", on="k").v.mean(),
    "merge_then_rowwise": lambda df: (df.merge(_right(df), how="left", on="k").fillna({"v": -1.0})
                                      .rename(columns={"w": "word"}).drop(columns=["n"])),
    # merge cases that must fall back to pandas (and still equal it)
    "merge_how_right": lambda df: df.merge(_right(df), how="right", on="k"),
    "merge_how_outer": lambda df: df.merge(_right(df), how="outer", on="k"),
    "merge_how_cross": lambda df: df.merge(_right(df), how="cross"),
    "merge_sort_true": lambda df: df.merge(_right(df), on="k", sort=True),
    "merge_left_on_right_on": lambda df: df.merge(_right(df).rename(columns={"k": "kk"}), left_on="k", right_on="kk"),
    "merge_left_right_index": lambda df: df.merge(_right(df), left_index=True, right_index=True),
    "merge_indicator": lambda df: df.merge(_right(df), how="left", on="k", indicator=True),
    "merge_validate": lambda df: df.merge(_right(df), how="left", on="k", validate="m:m"),
    "merge_validate_one_to_one_errors": lambda df: df.merge(_right(df), on="k", validate="1:1"),
    "merge_plain_right": lambda df: df.merge(_plain_right(df), how="left", on="k"),
    "merge_missing_key": lambda df: df.merge(_right(df), on="nope"),
    "merge_no_on": lambda df: df.merge(_right(df).rename(columns={"k": "k"})),
    # chain ending in a groupby
    "chain_groupby": lambda df: (df.rename(columns={"a": "x"}).fillna({"b": 0.0}).dropna(subset=["x"])
                                 .assign(y=lambda d: d.x * d.b).groupby("k")[["x", "y"]].sum()),
}
