"""Registry of operations for the append fuzzer.

Every new operation needs an entry in OPS (CLAUDE.md). An entry maps a name to a function
that takes a frame (incpandas or plain pandas; both share the API) and returns a frame,
Series or scalar. test_fuzz_ops.py feeds each one random CSV data with random appends and
checks the incpandas result equals plain pandas, in value and type.

Columns of the generated data: k (str key), a (int), b (float, power-of-two values so
sums are exact, some zeros), n (float with NaN).
"""


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
    # chain ending in a groupby
    "chain_groupby": lambda df: (df.rename(columns={"a": "x"}).fillna({"b": 0.0}).dropna(subset=["x"])
                                 .assign(y=lambda d: d.x * d.b).groupby("k")[["x", "y"]].sum()),
}
