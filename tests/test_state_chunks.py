"""Saved output is kept as chunks, so an append writes only the appended rows."""
import glob
import os
import pickle

import pandas as plain

import incpandas as pd
from incpandas import engine

HEADER = "k,a,b\n"


def write(rs, header=False):
    with open("d.csv", "w" if header else "a") as f:
        if header:
            f.write(HEADER)
        for r in rs:
            f.write(",".join(map(str, r)) + "\n")


def rows(n, start=0):
    return [(f"k{(start + i) % 3}", start + i, 1.5) for i in range(n)]


def pipeline():
    """A row-wise result, so the whole output is what gets saved."""
    df = pd.read_csv("d.csv")
    df["c"] = df.a * df.b
    return df[df.c > -1]


def run():
    out = pipeline()
    got = out.to_pandas()
    want = plain.read_csv("d.csv")
    want["c"] = want.a * want.b
    plain.testing.assert_frame_equal(got, want[want.c > -1], check_exact=False, rtol=1e-7)
    return got


def chunks():
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(engine.cache_dir(), "*.chunk")))


def cache_bytes():
    return sum(os.path.getsize(p) for p in glob.glob(os.path.join(engine.cache_dir(), "*")))


def test_an_append_adds_a_chunk_rather_than_rewriting():
    write(rows(50), header=True)
    run()
    first = chunks()
    assert len(first) == 1

    write(rows(5, start=50))
    run()
    after = chunks()
    assert len(after) == 2
    assert first[0] in after, "the chunk already on disk must be left alone"


def test_many_appends_compact_back_into_one_chunk():
    write(rows(20), header=True)
    run()
    runs = engine.MAX_CHUNKS + 4
    for i in range(runs):
        write(rows(2, start=100 + 10 * i))
        run()
    # without compaction this would be one chunk per run and growing
    assert len(chunks()) <= engine.MAX_CHUNKS, chunks()
    assert len(chunks()) < runs, chunks()
    run()


def test_the_cache_does_not_grow_without_bound():
    write(rows(200), header=True)
    run()
    for i in range(engine.MAX_CHUNKS * 3):
        write(rows(1, start=1000 + i))
        run()
    # The saved output is ~200 tiny rows. Without compaction and cleanup this would hold one
    # chunk per run forever; it must instead stay small and bounded.
    assert cache_bytes() < 400_000, cache_bytes()
    assert len(chunks()) <= engine.MAX_CHUNKS, chunks()


def test_superseded_chunks_are_deleted():
    write(rows(20), header=True)
    run()
    before = set(chunks())
    write(rows(15, start=500), header=True)    # different content -> full recompute, new chunk
    run()
    assert not (before & set(chunks())), "the old chunk should have been cleaned up"
    assert len(chunks()) == 1


def test_a_missing_chunk_recomputes_instead_of_failing():
    write(rows(30), header=True)
    run()
    write(rows(3, start=30))
    run()
    for name in chunks():                      # lose the saved output entirely
        os.remove(os.path.join(engine.cache_dir(), name))
    write(rows(3, start=60))
    run()                                      # must still equal pandas, by recomputing


def test_a_corrupt_chunk_recomputes_instead_of_failing():
    write(rows(30), header=True)
    run()
    write(rows(3, start=30))
    run()
    for name in chunks():
        with open(os.path.join(engine.cache_dir(), name), "wb") as f:
            f.write(b"not a pickle")
    write(rows(3, start=60))
    run()


def test_an_index_pointing_at_a_newer_run_is_rejected():
    """The index is written last; a stale one must not be trusted against fresh chunks."""
    write(rows(30), header=True)
    run()
    write(rows(3, start=30))
    run()
    index = glob.glob(os.path.join(engine.cache_dir(), "*.pkl"))
    assert index
    for path in index:
        with open(path, "rb") as f:
            st = pickle.load(f)
        st["run"] = st["run"] + 5              # claims a run that never happened
        with open(path, "wb") as f:
            pickle.dump(st, f)
    write(rows(3, start=60))
    run()


def test_no_change_writes_no_chunk():
    write(rows(40), header=True)
    run()
    write(rows(4, start=40))
    run()
    before = chunks()
    run()
    assert chunks() == before


def test_an_empty_delta_is_never_concatenated(monkeypatch):
    """Rebuilding the output must not mix an empty frame in.

    pandas 2.1 upcasts columns to object when an empty frame takes part in a concat, so a
    no-change rerun silently turned int64 into object there while 2.2+ looked fine. Pin the
    invariant rather than the symptom, so it holds on every version.
    """
    seen = []
    real = engine.pd.concat

    def spy(frames, *a, **k):
        frames = list(frames)
        seen.append([len(f) for f in frames])
        return real(frames, *a, **k)

    monkeypatch.setattr(engine.pd, "concat", spy)

    write(rows(30), header=True)
    run()
    for i in range(3):                       # several chunks, so a rebuild has to concat
        write(rows(2, start=100 + 10 * i))
        run()
    run()                                    # the no-change rerun: empty delta
    run()

    assert seen, "expected the chunked output to be rebuilt at least once"
    assert all(all(n > 0 for n in sizes) for sizes in seen), seen


def test_dtypes_survive_appends_and_a_no_change_rerun():
    write(rows(30), header=True)
    run()
    for i in range(3):
        write(rows(2, start=100 + 10 * i))
        run()
    got = run()                              # no change since the last run
    assert got["a"].dtype == plain.read_csv("d.csv").a.dtype
    assert str(got["a"].dtype) != "object"
