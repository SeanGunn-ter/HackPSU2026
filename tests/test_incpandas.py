import numpy as np
import pandas as plain
import pytest

import incpandas as pd
from incpandas import engine

HEADER = "k,j,a,b\n"


def write(path, rows, header=True):
    with open(path, "w" if header else "a") as f:
        if header:
            f.write(HEADER)
        for r in rows:
            f.write(",".join(map(str, r)) + "\n")


def modes():
    return {m for m, _ in engine.last_run().values()}


def pipeline(path="d.csv"):
    df = pd.read_csv(path)
    df["c"] = df.a * df.b
    df = df[df.c > 2]
    return df.groupby("k")[["a", "b", "c"]].sum()


ROWS1 = [("x", "p", 1, 2), ("y", "p", 3, 4), ("x", "q", 5, 6), ("z", "q", 7, 8)]
ROWS2 = [("y", "q", 9, 1), ("w", "p", 2, 2), ("x", "p", 4, 4)]


def test_append_is_incremental_and_correct():
    write("d.csv", ROWS1)
    pipeline().verify()
    assert "full" in modes()
    write("d.csv", ROWS2, header=False)
    r = pipeline()
    r.verify()
    assert modes() == {"incremental"}
    assert engine.last_run()[r._node.parents[0].parents[0].parents[0].sig] == ("incremental", 3)


def test_no_change_reruns_cheaply():
    write("d.csv", ROWS1)
    a = pipeline().to_pandas()
    b = pipeline().to_pandas()
    plain.testing.assert_frame_equal(a, b)
    assert engine.last_run()[next(iter(engine.last_run()))][0] == "incremental"


def test_many_appends_stay_correct():
    write("d.csv", ROWS1)
    for i in range(6):
        pipeline().verify()
        write("d.csv", [("k%d" % (i % 3), "p", i, i + 1), ("x", "q", i * 2, 3)], header=False)
    pipeline().verify()


def test_modified_file_falls_back_to_full_read():
    write("d.csv", ROWS1)
    pipeline().verify()
    write("d.csv", [("x", "p", 100, 2)] + ROWS1[1:] + ROWS2)   # first row edited + appended
    pipeline().verify()
    assert "full" in modes()


def test_truncated_file():
    write("d.csv", ROWS1 + ROWS2)
    pipeline().verify()
    write("d.csv", ROWS1)
    pipeline().verify()


def test_missing_trailing_newline_then_append():
    open("d.csv", "w").write(HEADER + "x,p,1,2\ny,p,3,4")
    pipeline().verify()
    open("d.csv", "a").write("\nx,q,5,6\n")
    pipeline().verify()


def test_new_nan_in_int_column_forces_full_read():
    write("d.csv", ROWS1)
    pipeline().verify()
    open("d.csv", "a").write("x,p,,5\ny,p,2,2\n")   # int col a gets a NaN -> becomes float
    pipeline().verify()


def test_string_appears_in_numeric_column():
    write("d.csv", ROWS1)
    df = pd.read_csv("d.csv")
    df.a.sum()
    open("d.csv", "a").write("x,p,oops,5\n")
    df = pd.read_csv("d.csv")
    assert df.to_pandas().a.dtype == plain.read_csv("d.csv").a.dtype
    r = df.groupby("k").sum()  # numeric-incompatible -> pandas fallback (str concatenation)
    r.verify()


def test_float_values_and_mean_count_min_max():
    write("d.csv", [("x", "p", 1.5, 2), ("y", "p", 3, 4.25), ("x", "q", 5, 6)])
    def go():
        g = pd.read_csv("d.csv")[["k", "a", "b"]].groupby("k")
        return [g.mean(), g.count(), g.min(), g.max(), g["a"].sum(), g[["a", "b"]].mean()]
    for r in go():
        r.verify()
    write("d.csv", [("y", "p", 0.5, 1), ("w", "q", -2, 7.5)], header=False)
    for r in go():
        r.verify()
    assert modes() == {"incremental"}


def test_nan_values_in_groups():
    write("d.csv", [("x", "p", 1, 2.5), ("x", "p", 2, ""), ("y", "p", 3, ""), ("z", "q", 4, 1)])
    def go():
        g = pd.read_csv("d.csv")[["k", "a", "b"]].groupby("k")
        return [g.sum(), g.mean(), g.count(), g.min(), g.max()]
    for r in go():
        r.verify()
    write("d.csv", [("y", "q", 1, ""), ("x", "q", 1, 7)], header=False)
    for r in go():
        r.verify()


def test_multi_key_groupby_and_options():
    write("d.csv", ROWS1)
    def go():
        df = pd.read_csv("d.csv")
        n = df[["k", "j", "a", "b"]]
        return [n.groupby(["k", "j"]).sum(), df[["k", "a", "b"]].groupby("k", as_index=False).sum(),
                df[["k", "a", "b"]].groupby("k", sort=False).mean(), df.groupby(["j"])["a"].max()]
    for r in go():
        r.verify()
    write("d.csv", ROWS2, header=False)
    for r in go():
        r.verify()
    assert modes() == {"incremental"}


def test_named_and_dict_agg():
    write("d.csv", ROWS1)
    def go():
        g = pd.read_csv("d.csv")[["k", "a", "b"]].groupby("k")
        return [g.agg(total=("a", "sum"), avg=("b", "mean")), g.agg({"a": "max", "b": "count"}), g.agg("sum")]
    for r in go():
        r.verify()
    write("d.csv", ROWS2, header=False)
    for r in go():
        r.verify()
    assert modes() == {"incremental"}


def test_empty_result_then_data():
    write("d.csv", [("x", "p", 0, 0)])
    def go():
        df = pd.read_csv("d.csv")
        df["c"] = df.a + df.b
        return df[df.c > 5].groupby("k")[["a", "b", "c"]].sum()
    go().verify()
    write("d.csv", [("y", "p", 9, 9)], header=False)
    go().verify()


def test_filter_and_column_math_only():
    write("d.csv", ROWS1)
    def go():
        df = pd.read_csv("d.csv")
        df["c"] = df.a * df.b + 1
        df["flag"] = (df.c > 10) & (df.k != "z")
        df["half"] = df.a / 2
        df["neg"] = -df.a
        df["s"] = 100 - df.b
        return df[df.flag | (df.a < 2)]
    go().verify()
    write("d.csv", ROWS2, header=False)
    r = go()
    r.verify()
    assert modes() == {"incremental"}


def test_whitelisted_methods_stay_incremental():
    write("d.csv", ROWS1)
    def go():
        df = pd.read_csv("d.csv")
        df["u"] = df.k.str.upper()
        df["in"] = df.a.isin([1, 3])
        df["r"] = (df.a / 3).round(1)
        return df[df.k.str.contains("x|y")]
    go().verify()
    write("d.csv", ROWS2, header=False)
    go().verify()
    assert modes() == {"incremental"}


def test_project_columns():
    write("d.csv", ROWS1)
    df = pd.read_csv("d.csv")[["k", "a"]]
    df.verify()
    write("d.csv", ROWS2, header=False)
    df.verify()


def test_opaque_expression_falls_back_but_is_correct():
    write("d.csv", ROWS1)
    def go():
        df = pd.read_csv("d.csv")
        df["m"] = df.a.map(lambda v: v * 10)
        df["rk"] = df.a.rank()
        return df
    r = go()
    r.verify()
    assert "fallback" in modes()
    write("d.csv", ROWS2, header=False)
    go().verify()


def test_cross_frame_expression():
    write("d.csv", ROWS1)
    df = pd.read_csv("d.csv")
    other = df[df.a > 2]
    df["x"] = df.a + other.a      # aligned on index, NaN where filtered out
    df.verify()
    write("d.csv", ROWS2, header=False)
    df.verify()


def test_reductions_and_unsupported_methods_use_pandas():
    write("d.csv", ROWS1)
    df = pd.read_csv("d.csv")
    p = plain.read_csv("d.csv")
    assert df.a.sum() == p.a.sum()
    assert df["a"].mean() == p.a.mean()
    assert len(df) == len(p)
    plain.testing.assert_frame_equal(df.sort_values("a", ascending=False), p.sort_values("a", ascending=False))
    plain.testing.assert_frame_equal(df.describe(), p.describe())
    plain.testing.assert_series_equal(df.groupby("k").a.median(), p.groupby("k").a.median())
    assert list(df.columns) == list(p.columns)
    assert engine.fallback_log


def test_mutating_fallbacks_are_not_lost():
    write("d.csv", ROWS1)
    df = pd.read_csv("d.csv")
    df.drop(columns=["j"], inplace=True)
    df.loc[0, "a"] = 99
    df.columns = ["K", "A", "B"]
    p = plain.read_csv("d.csv").drop(columns=["j"])
    p.loc[0, "a"] = 99
    p.columns = ["K", "A", "B"]
    plain.testing.assert_frame_equal(df.to_pandas(), p)


def test_copy_is_independent():
    write("d.csv", ROWS1)
    df = pd.read_csv("d.csv")
    df2 = df.copy()
    df["c"] = df.a * 2
    assert "c" not in df2.to_pandas().columns
    assert "c" in df.to_pandas().columns


def test_unsupported_read_csv_returns_plain_pandas():
    write("d.csv", ROWS1)
    df = pd.read_csv("d.csv", skiprows=1)
    assert isinstance(df, plain.DataFrame)


def test_module_passthrough():
    write("d.csv", ROWS1)
    df = pd.read_csv("d.csv")
    out = pd.concat([df, df])
    assert len(out) == 2 * len(ROWS1)
    assert isinstance(pd.DataFrame({"a": [1]}), plain.DataFrame)
    assert pd.to_numeric(df.a).sum() == 16
    np.testing.assert_array_equal(np.sqrt(df.a), np.sqrt(plain.read_csv("d.csv").a))


def test_corrupt_state_is_ignored():
    write("d.csv", ROWS1)
    pipeline().verify()
    import glob
    for f in glob.glob(str(engine.cache_dir()) + "/*.pkl"):
        open(f, "wb").write(b"garbage")
    write("d.csv", ROWS2, header=False)
    pipeline().verify()


def test_state_persists_across_processes(tmp_path):
    import subprocess, sys, os
    write("d.csv", ROWS1)
    code = ("import incpandas as pd\n"
            "df = pd.read_csv('d.csv'); df['c']=df.a*df.b\n"
            "print(df.groupby('k')[['a','b','c']].sum().to_pandas().to_csv())\n"
            "from incpandas import engine; print(sorted({m for m,_ in engine.last_run().values()}))")
    env = {**os.environ}
    first = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True).stdout
    write("d.csv", ROWS2, header=False)
    second = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True).stdout
    assert "'full'" in first and "['incremental']" in second


def test_randomized_against_pandas():
    rng = np.random.default_rng(0)
    def rows(n):
        return [(rng.choice(list("abcde")), rng.choice(["p", "q"]), int(rng.integers(-5, 20)),
                 round(float(rng.normal()), 3) if rng.random() > 0.1 else "") for _ in range(n)]
    write("d.csv", rows(30))
    def go():
        df = pd.read_csv("d.csv")
        df["c"] = df.a * 2 + df.b
        df = df[(df.c > 0) | (df.j == "q")]
        g = df[["k", "j", "a", "b", "c"]].groupby(["k", "j"])
        return [g.sum(), g.mean(), g.count(), g.min(), g.max(), df.groupby("k", sort=False).agg(t=("a", "sum"))]
    for _ in range(15):
        for r in go():
            r.verify()
        write("d.csv", rows(int(rng.integers(0, 12))), header=False)
