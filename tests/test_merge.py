import pandas as plain
import pytest

import incpandas as pd
from incpandas import engine
from incpandas.frame import LazyFrame

LEFT_HEADER = "k,a,b\n"
RIGHT_HEADER = "k,v,w\n"
LEFT1 = [("x", 1, 0.5), ("y", 2, 1.5), ("z", 3, 2.5), ("w", 4, 3.5)]
LEFT2 = [("y", 5, 0.25), ("q", 6, 0.75), ("x", 7, 1.25)]
RIGHT1 = [("x", 10, "p"), ("y", 20, "q"), ("y", 21, "r"), ("z", 30, "s"), ("n", 40, "t")]


def write(path, header, rows, new=False):
    with open(path, "w" if new else "a") as f:
        if new:
            f.write(header)
        for r in rows:
            f.write(",".join(map(str, r)) + "\n")


def left(rows=LEFT1):
    write("d.csv", LEFT_HEADER, rows, new=True)


def right(rows=RIGHT1):
    write("r.csv", RIGHT_HEADER, rows, new=True)


def run(make):
    """(lazy result, its materialised frame, plain pandas frame); asserts they match exactly."""
    lazy = make(pd, pd.read_csv("d.csv"), pd.read_csv("r.csv"))
    got = lazy.to_pandas() if hasattr(lazy, "to_pandas") else lazy
    want = make(plain, plain.read_csv("d.csv"), plain.read_csv("r.csv"))
    if not isinstance(want, plain.DataFrame):          # scalar reduction
        assert type(got) is type(want) and got == want
        return lazy, got
    plain.testing.assert_frame_equal(got, want)       # values, dtypes, index, column order
    assert list(got.index) == list(want.index)
    return lazy, got


def merge_note(lazy):
    return engine.last_run()[lazy._node.sig]


def keeps_order(dup_right=True):
    from incpandas.merge import _inner_dup_keeps_order, _inner_unique_keeps_order
    return _inner_dup_keeps_order() if dup_right else _inner_unique_keeps_order()


def assert_delta(lazy, how, n, dup_right=True):
    """Expect the merge to have processed just n new rows. An inner merge against duplicate
    right keys is recomputed in full on pandas versions that order it differently (merge.py)."""
    if how == "inner" and not keeps_order(dup_right):
        assert merge_note(lazy)[0] == "full"
    else:
        assert merge_note(lazy) == ("incremental", n)


HOWS = ["inner", "left"]
SHAPES = {
    "k": lambda m, d, r, how: d.merge(r, how=how, on="k"),
    "k_list": lambda m, d, r, how: d.merge(r.rename(columns={"v": "a"}), how=how, on=["k", "a"]),
    "suffixes": lambda m, d, r, how: d.merge(r.rename(columns={"v": "b"}), how=how, on="k", suffixes=("_l", "_r")),
}


@pytest.mark.parametrize("how", HOWS)
@pytest.mark.parametrize("shape", list(SHAPES))
def test_left_append_is_incremental_and_exact(how, shape):
    make = lambda m, d, r: SHAPES[shape](m, d, r, how)
    left(), right()
    dup = shape != "k_list"                                 # (k, a) pairs on the right are unique
    lazy, _ = run(make)
    assert type(lazy._node).__name__ == "Merge" and lazy._node.fast
    assert merge_note(lazy)[0] == "full"
    lazy, _ = run(make)                                    # nothing changed
    assert_delta(lazy, how, 0, dup)
    write("d.csv", LEFT_HEADER, LEFT2)                     # new rows on the left
    lazy, got = run(make)
    assert_delta(lazy, how, len(LEFT2), dup)                    # only the delta was processed
    if how == "left" or keeps_order(dup):
        assert {m for m, _ in engine.last_run().values()} == {"incremental"}
    assert isinstance(got.index, (plain.RangeIndex, plain.Index)) and list(got.index) == list(range(len(got)))
    write("d.csv", LEFT_HEADER, [("y", 1, 0.5)] * 3)       # and again
    lazy, _ = run(make)
    assert_delta(lazy, how, 3, dup)


@pytest.mark.parametrize("how", HOWS)
def test_right_changes_recompute_in_full(how):
    make = lambda m, d, r: d.merge(r, how=how, on="k")
    left(), right()
    run(make)
    write("d.csv", LEFT_HEADER, LEFT2)
    run(make)
    write("r.csv", RIGHT_HEADER, [("w", 50, "u"), ("q", 60, "v")])      # right appended
    lazy, _ = run(make)
    assert merge_note(lazy)[0] == "full"
    write("d.csv", LEFT_HEADER, [("w", 8, 1.0)])                         # left appended after
    lazy, _ = run(make)
    assert_delta(lazy, how, 1)
    lines = open("r.csv").read().splitlines()                            # right edited in place
    lines[2] = "y,99,edited"
    open("r.csv", "w").write("\n".join(lines) + "\n")
    lazy, _ = run(make)
    assert merge_note(lazy)[0] == "full"
    right([("x", 1, "only")])                                            # right replaced
    lazy, _ = run(make)
    assert merge_note(lazy)[0] == "full"
    write("d.csv", LEFT_HEADER, [("x", 2, 2.0)])
    lazy, _ = run(make)
    assert_delta(lazy, how, 1, dup_right=False)             # right keys are unique again


@pytest.mark.parametrize("how", HOWS)
def test_left_file_edit_or_truncate_recomputes(how):
    make = lambda m, d, r: d.merge(r, how=how, on="k")
    left(), right()
    run(make)
    left([("x", 100, 9.5)] + LEFT1[1:])
    lazy, _ = run(make)
    assert merge_note(lazy)[0] == "full"
    left(LEFT1[:1])
    run(make)


def test_duplicate_right_keys_keep_pandas_order():
    left([("y", 1, 1.0), ("x", 2, 2.0), ("y", 3, 3.0)])
    right([("y", 1, "a"), ("x", 2, "b"), ("y", 3, "c"), ("y", 4, "d")])
    for how in HOWS:
        make = lambda m, d, r: d.merge(r, how=how, on="k")
        run(make)
        extra = [("zz", 6, 6.0)] if how == "inner" else []      # a left no-match flips v to float
        write("d.csv", LEFT_HEADER, [("x", 4, 4.0), ("y", 5, 5.0)] + extra)
        lazy, got = run(make)
        assert_delta(lazy, how, 2 + len(extra))
        left([("y", 1, 1.0), ("x", 2, 2.0), ("y", 3, 3.0)])


def test_left_join_dtype_flips_match_pandas():
    """Int right column becomes float once an unmatched row appears (and not before)."""
    make = lambda m, d, r: d.merge(r, how="left", on="k")
    # first rows all match, later rows don't
    left([("x", 1, 1.0), ("y", 2, 2.0)]), right()
    lazy, got = run(make)
    assert str(got.v.dtype) == "int64"
    write("d.csv", LEFT_HEADER, [("nomatch", 3, 3.0)])
    lazy, got = run(make)
    assert merge_note(lazy)[0] == "full" and str(got.v.dtype) == "float64"   # earlier rows widen too
    write("d.csv", LEFT_HEADER, [("x", 4, 4.0), ("y", 5, 5.0)])         # delta matches fully again
    lazy, got = run(make)
    assert merge_note(lazy) == ("incremental", 2) and str(got.v.dtype) == "float64"
    # first rows don't match, later rows all match
    left([("nomatch", 1, 1.0), ("x", 2, 2.0)])
    run(make)
    write("d.csv", LEFT_HEADER, [("x", 3, 3.0), ("z", 4, 4.0)])
    lazy, got = run(make)
    assert str(got.v.dtype) == "float64"
    # and downstream nodes cope with the flip
    for tail in (lambda f: f.v.sum(), lambda f: f.groupby("k")[["v"]].sum(),
                 lambda f: f.fillna({"v": 0}).astype({"v": "int64"})):
        left([("x", 1, 1.0)])
        run(lambda m, d, r: tail(make(m, d, r)))
        write("d.csv", LEFT_HEADER, [("nomatch", 2, 1.0)])
        run(lambda m, d, r: tail(make(m, d, r)))
        write("d.csv", LEFT_HEADER, [("y", 2, 1.0)])
        run(lambda m, d, r: tail(make(m, d, r)))


def test_empty_delta_and_no_match_delta_keep_dtypes():
    make = lambda m, d, r: d.merge(r, how="inner", on="k")
    left(), right()
    run(make)
    write("d.csv", LEFT_HEADER, [("nomatch", 1, 1.0), ("nope", 2, 2.0)])   # inner: delta merges to nothing
    lazy, got = run(make)
    assert_delta(lazy, "inner", 2)
    write("d.csv", LEFT_HEADER, [("x", 9, 9.0)])
    run(make)


def test_nan_keys_match_like_pandas():
    left([("x", 1, 1.0), ("", 2, 2.0)])
    right([("x", 1, "a"), ("", 2, "nan-key"), ("", 3, "nan-key2")])
    for how in HOWS:
        make = lambda m, d, r: d.merge(r, how=how, on="k")
        run(make)
        write("d.csv", LEFT_HEADER, [("", 5, 5.0), ("x", 6, 6.0)])
        lazy, got = run(make)
        assert_delta(lazy, how, 2)
        left([("x", 1, 1.0), ("", 2, 2.0)])


def test_key_dtype_mismatch_raises_like_pandas():
    write("d.csv", "k,a,b\n", [(1, 1, 1.0), (2, 2, 2.0)], new=True)
    right()
    with pytest.raises(ValueError):
        plain.read_csv("d.csv").merge(plain.read_csv("r.csv"), on="k")
    with pytest.raises(ValueError):
        pd.read_csv("d.csv").merge(pd.read_csv("r.csv"), on="k").to_pandas()


def test_int_vs_float_keys_match_pandas():
    write("d.csv", "k,a,b\n", [(1, 1, 1.0), (2, 2, 2.0)], new=True)
    write("r.csv", RIGHT_HEADER, [(1.0, 10, "a"), (2.5, 20, "b"), (2.0, 30, "c")], new=True)
    make = lambda m, d, r: d.merge(r, how="left", on="k")
    run(make)
    write("d.csv", "k,a,b\n", [(3, 3, 3.0), (2, 4, 4.0)])
    run(make)


FALLBACKS = {
    "right": lambda m, d, r: d.merge(r, how="right", on="k"),
    "outer": lambda m, d, r: d.merge(r, how="outer", on="k"),
    "cross": lambda m, d, r: d.merge(r, how="cross"),
    "sort": lambda m, d, r: d.merge(r, on="k", sort=True),
    "left_on": lambda m, d, r: d.merge(r.rename(columns={"k": "kk"}), left_on="k", right_on="kk"),
    "index": lambda m, d, r: d.merge(r, left_index=True, right_index=True),
    "indicator": lambda m, d, r: d.merge(r, on="k", indicator=True),
    "validate": lambda m, d, r: d.merge(r, on="k", validate="m:m"),
    "no_on": lambda m, d, r: d.merge(r),
    "module_fn": lambda m, d, r: m.merge(d, r, how="right", on="k"),
}


@pytest.mark.parametrize("name", list(FALLBACKS))
def test_out_of_scope_falls_back_and_matches(name):
    left(), right()
    engine.fallback_log.clear()
    want = FALLBACKS[name](plain, plain.read_csv("d.csv"), plain.read_csv("r.csv"))
    got = FALLBACKS[name](pd, pd.read_csv("d.csv"), pd.read_csv("r.csv"))
    assert any("merge" in n for n in engine.fallback_log)
    got = got.to_pandas() if hasattr(got, "to_pandas") else got
    plain.testing.assert_frame_equal(got, want)


def test_plain_right_frame_and_missing_key_fall_back():
    left(), right()
    engine.fallback_log.clear()
    got = pd.read_csv("d.csv").merge(plain.read_csv("r.csv"), on="k")
    plain.testing.assert_frame_equal(got, plain.read_csv("d.csv").merge(plain.read_csv("r.csv"), on="k"))
    assert "DataFrame.merge" in engine.fallback_log
    with pytest.raises(KeyError):
        plain.read_csv("d.csv").merge(plain.read_csv("r.csv"), on="nope")
    with pytest.raises(KeyError):
        pd.read_csv("d.csv").merge(pd.read_csv("r.csv"), on="nope")


def test_module_function_builds_node():
    left(), right()
    lazy = pd.merge(pd.read_csv("d.csv"), pd.read_csv("r.csv"), how="left", on="k")
    assert isinstance(lazy, LazyFrame) and type(lazy._node).__name__ == "Merge"
    plain.testing.assert_frame_equal(
        lazy.to_pandas(), plain.merge(plain.read_csv("d.csv"), plain.read_csv("r.csv"), how="left", on="k"))
    assert pd.concat is not None                       # other attributes still pass through


def test_chain_filter_assign_groupby():
    def make(m, d, r):
        g = d[d.a > 1]
        g = g.assign(c=g.a * 2)
        j = g.merge(r, how="left", on="k").merge(r.rename(columns={"v": "v2", "w": "w2"}), on="k")
        return j.groupby("k")[["c", "v", "v2"]].sum()
    left(), right()
    run(make)
    write("d.csv", LEFT_HEADER, LEFT2)
    lazy, _ = run(make)
    if keeps_order():       # the inner merge against duplicate right keys is recomputed otherwise
        assert {m for m, _ in engine.last_run().values()} == {"incremental"}
    write("r.csv", RIGHT_HEADER, [("q", 1, "z")])
    run(make)
    write("d.csv", LEFT_HEADER, LEFT2)
    run(make)


def test_self_merge():
    left(), right()
    make = lambda m, d, r: d.merge(d, on="k", suffixes=("_1", "_2"))
    run(make)
    write("d.csv", LEFT_HEADER, LEFT2)
    run(make)


def test_explain_shows_merge():
    left(), right()
    lazy = pd.read_csv("d.csv").merge(pd.read_csv("r.csv"), how="left", on="k")
    lazy.to_pandas()
    text = lazy.explain()
    assert "Merge" in text and "left on 'k'" in text


def test_original_frames_unchanged():
    left(), right()
    d, r = pd.read_csv("d.csv"), pd.read_csv("r.csv")
    d.merge(r, on="k")
    assert d._node.columns == ["k", "a", "b"] and r._node.columns == ["k", "v", "w"]


# Left keys x y z w y q x, right keys x y y z n: on pandas < 3.1 a full inner merge orders
# rows differently from merging the left side in two chunks (see merge.py).
PROBE_LEFT = [(k, i, float(i)) for i, k in enumerate("xyzwyqx")]
PROBE_RIGHT = [(k, i, "p") for i, k in enumerate("xyyzn")]


def _plain_chunked_matches_full(l, r):
    full = l.merge(r, on="k")
    h = len(l) // 2
    chunked = plain.concat([l.iloc[:h].merge(r, on="k"), l.iloc[h:].merge(r, on="k")],
                           ignore_index=True)
    return full.reset_index(drop=True).equals(chunked)


def test_inner_order_probe_matches_plain_pandas_example():
    from incpandas.merge import _inner_dup_keeps_order
    l = plain.DataFrame({"k": list("xyzwyqx"), "i": range(7)})
    r = plain.DataFrame({"k": list("xyyzn"), "j": range(5)})
    assert _inner_dup_keeps_order() is _plain_chunked_matches_full(l, r)


def test_inner_order_probe_unique_keys_matches_plain_pandas_example():
    from incpandas.merge import _inner_unique_keeps_order
    l = plain.DataFrame({"k": list("zxwyqxyz"), "i": range(8)})
    r = plain.DataFrame({"k": list("yzxn"), "j": range(4)})
    assert _inner_unique_keeps_order() is _plain_chunked_matches_full(l, r)


@pytest.mark.parametrize("how", HOWS)
def test_incremental_merge_equals_pandas_for_order_problem_case(how):
    make = lambda m, d, r: d.merge(r, how=how, on="k")
    left(PROBE_LEFT[:4]), right(PROBE_RIGHT)
    run(make)
    write("d.csv", LEFT_HEADER, PROBE_LEFT[4:])           # appended left rows
    lazy, _ = run(make)                                    # run() asserts equality with pandas
    assert_delta(lazy, how, 3)                             # inner + duplicate right keys: full
    write("d.csv", LEFT_HEADER, [("y", 9, 9.0), ("n", 10, 10.0), ("x", 11, 11.0)])
    run(make)


def test_inner_merge_with_unique_right_keys_is_incremental_only_if_probe_passes():
    make = lambda m, d, r: d.merge(r, on="k")
    left(PROBE_LEFT[:4]), right([("x", 1, "a"), ("y", 2, "b"), ("z", 3, "c"), ("n", 4, "d")])
    run(make)
    write("d.csv", LEFT_HEADER, PROBE_LEFT[4:])
    lazy, _ = run(make)
    if keeps_order(dup_right=False):
        assert merge_note(lazy) == ("incremental", 3)
    else:
        assert merge_note(lazy)[0] == "full"
