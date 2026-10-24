import pandas as plain
import pytest

import incpandas as pd
from incpandas import engine

HEADER = "k,a,b,s\n"
ROWS1 = [("x", 1, 2.5, "p"), ("y", 3, "", "q"), ("x", "", 6.5, ""), ("z", 7, 8.5, "r")]
ROWS2 = [("y", 9, 1.5, "s"), ("w", "", "", ""), ("x", 4, 4.5, "t")]
OPS = {
    "rename": (lambda df: df.rename(columns={"a": "aa", "k": "key"}), ["key", "aa", "b", "s"]),
    "drop": (lambda df: df.drop(columns=["b", "s"]), ["k", "a"]),
    "drop_str": (lambda df: df.drop(columns="s"), ["k", "a", "b"]),
    "drop_axis1": (lambda df: df.drop("s", axis=1), ["k", "a", "b"]),
    "astype": (lambda df: df.astype({"b": "float32"}), ["k", "a", "b", "s"]),
    "dropna": (lambda df: df.dropna(), ["k", "a", "b", "s"]),
    "dropna_subset": (lambda df: df.dropna(subset=["a"]), ["k", "a", "b", "s"]),
    "fillna": (lambda df: df[["a", "b"]].fillna(0), ["a", "b"]),
    "fillna_dict": (lambda df: df.fillna({"a": -1, "b": 0.5, "s": "?"}), ["k", "a", "b", "s"]),
    "assign": (lambda df: df.assign(c=df.a * 2, d=1), ["k", "a", "b", "s", "c", "d"]),
}


def write(path, rows, header=True):
    with open(path, "w" if header else "a") as f:
        if header:
            f.write(HEADER)
        for r in rows:
            f.write(",".join(map(str, r)) + "\n")


def modes():
    return {m for m, _ in engine.last_run().values()}


def same(lazy, expected):
    got = lazy.to_pandas() if hasattr(lazy, "to_pandas") else lazy
    plain.testing.assert_frame_equal(got, expected)
    return got


def run_of(lazy):
    return engine.last_run()[lazy._node.sig]


@pytest.mark.parametrize("name", list(OPS))
def test_op_lifecycle(name):
    f, cols = OPS[name]
    write("d.csv", ROWS1)
    r = f(pd.read_csv("d.csv"))
    assert r._node.fast and r._node.columns == cols
    same(r, f(plain.read_csv("d.csv")))
    assert run_of(r)[0] == "full"
    r = f(pd.read_csv("d.csv"))          # nothing changed
    same(r, f(plain.read_csv("d.csv")))
    assert modes() == {"incremental"}
    write("d.csv", ROWS2, header=False)  # append
    r = f(pd.read_csv("d.csv"))
    same(r, f(plain.read_csv("d.csv")))
    assert modes() == {"incremental"}
    assert run_of(r) == ("incremental", len(ROWS2))
    write("d.csv", [("q", 5, 5.5, "e")] + ROWS1[1:])   # edit in place
    r = f(pd.read_csv("d.csv"))
    same(r, f(plain.read_csv("d.csv")))
    assert run_of(r)[0] == "full"


def test_rename_collision_falls_back():
    write("d.csv", ROWS1)
    engine.fallback_log.clear()
    r = pd.read_csv("d.csv").rename(columns={"a": "b"})
    assert "DataFrame.rename" in engine.fallback_log
    same(r, plain.read_csv("d.csv").rename(columns={"a": "b"}))


def test_rename_swap_and_unknown_key():
    write("d.csv", ROWS1)
    m = {"a": "b", "b": "a", "nope": "z"}
    r = pd.read_csv("d.csv").rename(columns=m)
    assert r._node.fast
    same(r, plain.read_csv("d.csv").rename(columns=m))


@pytest.mark.parametrize("call", [
    lambda d: d.rename(columns=str.upper),
    lambda d: d.rename(index={0: 5}),
    lambda d: d.drop(index=[0]),
    lambda d: d.drop([0]),
    lambda d: d.drop([0, 1], axis=0),
    lambda d: d.astype("category"),
    lambda d: d.astype({"s": "str"}),
    lambda d: d.dropna(axis=1),
    lambda d: d.fillna(limit=1, value=0),
    lambda d: d.fillna(plain.Series([1.0])),
    lambda d: d.fillna(),
])
def test_unsupported_falls_back(call):
    write("d.csv", ROWS1)
    engine.fallback_log.clear()
    try:
        expected = call(plain.read_csv("d.csv"))
    except Exception as e:
        with pytest.raises(type(e)):
            call(pd.read_csv("d.csv"))
        return
    got = call(pd.read_csv("d.csv"))
    assert any(n.startswith("DataFrame.") for n in engine.fallback_log)
    same(got, expected)


def test_drop_missing_column_raises_pandas_error():
    write("d.csv", ROWS1)
    with pytest.raises(KeyError):
        plain.read_csv("d.csv").drop(columns=["nope"])
    with pytest.raises(KeyError):
        pd.read_csv("d.csv").drop(columns=["nope"])
    with pytest.raises(KeyError):
        pd.read_csv("d.csv").drop(columns=["a", "nope"])


@pytest.mark.filterwarnings("ignore:incpandas:UserWarning")
def test_astype_int_with_nan():
    write("d.csv", [("x", 1, 1.5, "p"), ("y", 2, 2.5, "q")])
    f = lambda df: df.astype({"a": "int64"})
    same(f(pd.read_csv("d.csv")), f(plain.read_csv("d.csv")))
    write("d.csv", [("z", "", 3.5, "r")], header=False)
    with pytest.raises(ValueError):
        f(plain.read_csv("d.csv"))
    with pytest.raises(ValueError):       # same error as pandas, never a wrong result
        f(pd.read_csv("d.csv")).to_pandas()


def test_astype_bare_dtype():
    write("d.csv", [("x", 1, 1.5, "p"), ("y", 2, 2.5, "q")])
    for g in (lambda df: df[["a", "b"]].astype("float64"), lambda df: df[["b"]].astype(int)):
        r = g(pd.read_csv("d.csv"))
        assert r._node.fast
        same(r, g(plain.read_csv("d.csv")))


def test_dropna_all_options_and_labels():
    rows = [("x", 1, 2.5, "p"), ("y", "", "", "q"), ("", "", "", ""), ("z", 7, "", "r")]
    write("d.csv", rows)
    calls = [lambda d: d.dropna(), lambda d: d.dropna(how="all"), lambda d: d.dropna(how="any"),
             lambda d: d.dropna(thresh=3), lambda d: d.dropna(thresh=2, subset=["a", "b", "s"]),
             lambda d: d.dropna(subset="a"), lambda d: d.dropna(how="all", subset=["a", "b"])]
    for call in calls:
        r = call(pd.read_csv("d.csv"))
        assert r._node.fast
        same(r, call(plain.read_csv("d.csv")))
    write("d.csv", [("w", 2, 3.5, "u"), ("", "", "", ""), ("v", "", 1.5, "t")], header=False)
    for call in calls:
        r = call(pd.read_csv("d.csv"))
        got = same(r, call(plain.read_csv("d.csv")))
        assert run_of(r)[0] == "incremental"
        assert list(got.index) == list(call(plain.read_csv("d.csv")).index)


def test_dropna_how_and_thresh_together_errors_like_pandas():
    write("d.csv", ROWS1)
    with pytest.raises(TypeError):
        pd.read_csv("d.csv").dropna(how="any", thresh=1)


@pytest.mark.filterwarnings("ignore::Warning")
def test_fillna_mixed_columns():
    write("d.csv", ROWS1)
    calls = (lambda d: d.fillna(0), lambda d: d.fillna("none"),
             lambda d: d.fillna({"a": 0, "s": "none"}), lambda d: d.fillna(0.5))
    for call in calls:
        r = call(pd.read_csv("d.csv"))
        assert r._node.fast
        same(r, call(plain.read_csv("d.csv")))
    write("d.csv", [("y", "", "", ""), ("y", 2, "", "")], header=False)
    for call in calls:
        same(call(pd.read_csv("d.csv")), call(plain.read_csv("d.csv")))


def test_assign_callable_sees_earlier_kwarg_and_leaves_original():
    write("d.csv", ROWS1)
    base = pd.read_csv("d.csv")
    f = lambda df: df.assign(c=df.a * 2, d=lambda x: x.c + 1, e=5, f=lambda x: x.d * x.b)
    r = f(base)
    assert r is not base and base._node.columns == ["k", "a", "b", "s"]
    assert r._node.columns == ["k", "a", "b", "s", "c", "d", "e", "f"]
    same(r, f(plain.read_csv("d.csv")))
    same(base, plain.read_csv("d.csv"))
    write("d.csv", ROWS2, header=False)
    r = f(pd.read_csv("d.csv"))
    same(r, f(plain.read_csv("d.csv")))
    assert modes() == {"incremental"}
    assert r.verify()


def test_assign_overwrite_existing_and_empty():
    write("d.csv", ROWS1)
    f = lambda df: df.assign(a=lambda x: x.a * 10)
    same(f(pd.read_csv("d.csv")), f(plain.read_csv("d.csv")))
    same(pd.read_csv("d.csv").assign(), plain.read_csv("d.csv").assign())


@pytest.mark.filterwarnings("ignore::Warning")
def test_inplace_variants():
    write("d.csv", ROWS1)
    df, ref = pd.read_csv("d.csv"), plain.read_csv("d.csv")
    for call in (lambda d: d.rename(columns={"a": "aa"}, inplace=True),
                 lambda d: d.drop(columns=["s"], inplace=True),
                 lambda d: d.fillna(0, inplace=True),
                 lambda d: d.dropna(subset=["b"], inplace=True)):
        before = df._node
        assert call(df) is None
        call(ref)    # (pandas 3.1 returns the frame from fillna(inplace=True))
        assert df._node is not before and df._node.fast
        same(df, ref)
    write("d.csv", ROWS2, header=False)
    df2, ref2 = pd.read_csv("d.csv"), plain.read_csv("d.csv")
    df2.rename(columns={"a": "aa"}, inplace=True)
    ref2.rename(columns={"a": "aa"}, inplace=True)
    same(df2, ref2)


def test_chain_ending_in_groupby():
    def f(df):
        df = df.rename(columns={"a": "x"})
        df = df.drop(columns=["s"])
        df = df.fillna({"b": 0.0})
        df = df.dropna(subset=["x"])
        df = df.astype({"x": "int64"})
        df = df.assign(y=lambda d: d.x * d.b)
        return df.groupby("k")[["x", "b", "y"]].sum()
    write("d.csv", ROWS1)
    same(f(pd.read_csv("d.csv")), f(plain.read_csv("d.csv")))
    write("d.csv", ROWS2, header=False)
    r = f(pd.read_csv("d.csv"))
    same(r, f(plain.read_csv("d.csv")))
    assert modes() == {"incremental"}
    assert r.verify()
    write("d.csv", ROWS1[:2] + ROWS2)
    same(f(pd.read_csv("d.csv")), f(plain.read_csv("d.csv")))


def test_ops_on_fallback_frame_still_correct():
    write("d.csv", ROWS1)
    df = pd.read_csv("d.csv").sort_values("a")     # pandas fallback -> in-memory node
    r = df.rename(columns={"a": "aa"}).dropna()
    same(r, plain.read_csv("d.csv").sort_values("a").rename(columns={"a": "aa"}).dropna())
