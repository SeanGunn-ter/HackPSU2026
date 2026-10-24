"""INCPANDAS_LOG=1 (one summary line per run) and INCPANDAS_STRICT=1 (raise, never fall back)."""
import re

import pytest

import incpandas as pd
from incpandas.engine import StrictFallback

HEADER = "k,a,b\n"
ROWS = [("x", 1, 1.0), ("y", 2, 0.5), ("x", 3, 2.0), ("z", 4, 0.25), ("y", 5, 1.0), ("x", 6, 4.0)]


def write(rs, header=False):
    with open("d.csv", "w" if header else "a") as f:
        if header:
            f.write(HEADER)
        for r in rs:
            f.write(",".join(map(str, r)) + "\n")


def pipeline():
    df = pd.read_csv("d.csv")
    df["c"] = df.a * df.b
    return df[df.c > 0].groupby("k")[["a", "c"]].sum()


def lines(capsys):
    return [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("incpandas:")]


def one_line(capsys):
    """The single summary line, with the node-mode tail (how A chose to fuse nodes) dropped."""
    (line,) = lines(capsys)
    head, _, tail = line.partition(" (")
    assert re.fullmatch(r"\d+ (full|incremental|fallback)(, \d+ (full|incremental|fallback))*\)", tail), line
    return head, tail


# -- INCPANDAS_LOG ---------------------------------------------------------------------

def test_log_is_off_by_default(capsys):
    write(ROWS, header=True)
    pipeline().to_pandas()
    assert lines(capsys) == []


def test_log_reports_rows_processed_and_skipped(capsys, monkeypatch):
    monkeypatch.setenv("INCPANDAS_LOG", "1")
    write(ROWS, header=True)

    pipeline().to_pandas()
    head, tail = one_line(capsys)
    assert head == "incpandas: processed 6 new rows, skipped 0"
    assert "full" in tail and "incremental" not in tail

    write([("x", 7, 1.0), ("w", 8, 0.5)])
    pipeline().to_pandas()
    head, tail = one_line(capsys)
    assert head == "incpandas: processed 2 new rows, skipped 6"
    assert "full" not in tail and "fallback" not in tail

    pipeline().to_pandas()          # nothing changed: the whole file is skipped
    head, _ = one_line(capsys)
    assert head == "incpandas: processed 0 new rows, skipped 8"


def test_log_thousands_separator_and_fallback_count(capsys, monkeypatch):
    monkeypatch.setenv("INCPANDAS_LOG", "1")
    write([("x", i, 1.0) for i in range(1500)], header=True)
    pd.read_csv("d.csv").k.sum()    # a string reduction: the Reduce node runs in pandas
    head, tail = one_line(capsys)
    assert head == "incpandas: processed 1,500 new rows, skipped 0"
    assert "1 fallback" in tail


def test_log_off_when_flag_is_zero(capsys, monkeypatch):
    monkeypatch.setenv("INCPANDAS_LOG", "0")
    write(ROWS, header=True)
    pipeline().to_pandas()
    assert lines(capsys) == []


# -- INCPANDAS_STRICT ------------------------------------------------------------------

def pipeline_in_pandas():
    import pandas as plain
    df = plain.read_csv("d.csv")
    df["c"] = df.a * df.b
    return df[df.c > 0].groupby("k")[["a", "c"]].sum()


def test_strict_allows_a_supported_pipeline(monkeypatch):
    write(ROWS, header=True)
    pipeline().to_pandas()                  # first run: builds the saved state
    monkeypatch.setenv("INCPANDAS_STRICT", "1")
    write([("x", 7, 1.0)])                  # second run goes down the incremental path
    out = pipeline()
    pd.testing.assert_frame_equal(out.to_pandas(), pipeline_in_pandas())
    out.verify()


def test_strict_raises_on_map(monkeypatch):
    write(ROWS, header=True)
    monkeypatch.setenv("INCPANDAS_STRICT", "1")
    df = pd.read_csv("d.csv")
    with pytest.raises(StrictFallback, match="Series.map"):
        df.a.map(lambda v: v + 1)


@pytest.mark.parametrize("call", [
    lambda df: df.sort_values("a"),
    lambda df: df.a.rank(),
    lambda df: df.groupby("k").median(),
    lambda df: df.k.str.cat(),
], ids=["sort_values", "rank", "median", "str.cat"])
def test_strict_raises_on_eager_pandas_calls(call, monkeypatch):
    write(ROWS, header=True)
    monkeypatch.setenv("INCPANDAS_STRICT", "1")
    with pytest.raises(StrictFallback):
        call(pd.read_csv("d.csv"))


def test_strict_raises_on_a_node_that_falls_back(monkeypatch):
    """A string reduction is planned, then declines to run incrementally: still a fallback."""
    write(ROWS, header=True)
    monkeypatch.setenv("INCPANDAS_STRICT", "1")
    with pytest.raises(StrictFallback, match="(?i)sum"):
        pd.read_csv("d.csv").k.sum()


def test_strict_raises_when_the_source_cannot_be_read_lazily(monkeypatch, tmp_path):
    write(ROWS, header=True)
    monkeypatch.setenv("INCPANDAS_STRICT", "1")
    with pytest.raises(StrictFallback, match="read_csv"):
        pd.read_csv("d.csv", nrows=3)


def test_strict_is_off_by_default():
    write(ROWS, header=True)
    assert pd.read_csv("d.csv").a.map(lambda v: v + 1).sum() == 27
