"""The plan graph: incpandas/viz.py."""
import pytest

import incpandas as pd
from incpandas import viz

HEADER = "k,a,b\n"
ROWS = [("x", 1, 1.0), ("y", 2, 0.5), ("x", 3, 2.0), ("z", 4, 0.25)]


def write(rs, header=True, name="d.csv"):
    with open(name, "w" if header else "a") as f:
        if header:
            f.write(HEADER)
        for r in rs:
            f.write(",".join(map(str, r)) + "\n")


def pipeline():
    df = pd.read_csv("d.csv")
    df["c"] = df.a * df.b
    return df[df.c > 0].groupby("k")[["a", "c"]].sum()


def test_plan_that_has_not_run_says_so():
    write(ROWS)
    doc = viz.graph(pd.read_csv("d.csv"))
    assert "not run yet" in doc
    assert "read_csv(d.csv)" in doc


def test_colours_reflect_the_last_run():
    write(ROWS)
    out = pipeline()
    out.to_pandas()                                  # first run: everything is a full pass
    assert 'class="node full"' in viz.graph(out)

    write([("x", 9, 1.0)], header=False)
    out = pipeline()
    out.to_pandas()                                  # rerun: the appended rows only
    doc = viz.graph(out)
    assert 'class="node inc"' in doc
    assert "incremental" in doc and "rows" in doc


def test_map_shows_a_red_node_with_its_reason():
    """The plan's own acceptance check for B2: a .map() pipeline shows red, with a reason."""
    write(ROWS)
    df = pd.read_csv("d.csv")
    df["m"] = df.a.map(lambda v: v + 1)              # unsupported -> the frame becomes Mem
    out = df.groupby("k")[["m"]].sum()
    out.to_pandas()
    doc = viz.graph(out)
    assert 'class="node fb"' in doc, doc
    assert "pandas fallback" in doc


def test_one_node_box_per_plan_node():
    write(ROWS)
    out = pipeline()
    assert doc_nodes(viz.graph(out)) == len(viz._order(out._node))


def doc_nodes(doc):
    return doc.count("<g class=\"node ")


def test_page_is_self_contained():
    """It has to open from file:// on a laptop with no internet."""
    write(ROWS)
    doc = viz.graph(pipeline())
    # The SVG namespace is spelled as a URL but is never fetched, and url(#arrow) points at
    # the document's own marker. Nothing else may name a URL at all.
    stripped = doc.replace('xmlns="http://www.w3.org/2000/svg"', "")
    for forbidden in ("<script", " src=", "http://", "https://", "@import", "url(http", "url(//"):
        assert forbidden not in stripped, forbidden
    assert doc.startswith("<!doctype html>") and doc.rstrip().endswith("</html>")
    assert "<style>" in doc and "<svg" in doc


def test_column_names_are_escaped():
    with open("d.csv", "w") as f:
        f.write('k,<script>alert(1)</script>\nx,1\ny,2\n')
    doc = viz.graph(pd.read_csv("d.csv"))
    assert "<script>" not in doc
    assert "&lt;script&gt;" in doc


def test_writes_a_file_and_returns_the_path(tmp_path):
    write(ROWS)
    path = tmp_path / "plan.html"
    assert viz.graph(pipeline(), path) == str(path)
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_method_is_installed_on_lazy_frames(tmp_path):
    write(ROWS)
    out = pipeline()
    assert "<svg" in out.graph()
    assert out.graph(tmp_path / "p.html") == str(tmp_path / "p.html")


def test_a_lazy_series_can_be_drawn():
    write(ROWS)
    assert "<svg" in viz.graph(pd.read_csv("d.csv").a)


def test_something_with_no_plan_is_refused():
    with pytest.raises(TypeError, match="no incpandas plan"):
        viz.graph(42)


def test_title_is_used():
    write(ROWS)
    doc = viz.graph(pipeline(), title="sales plan")
    assert "<title>sales plan</title>" in doc and "<h1>sales plan</h1>" in doc
