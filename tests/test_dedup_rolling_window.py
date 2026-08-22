"""The dedup watermark must be ROLLING.

Regression test for the bug that put one item in 38 of 63 briefings while
`dedup_days` was 14: the window was measured from `first_seen`, so anything whose
FIRST sighting was older than the window fell outside it permanently and came back
on every run. `last_seen` is what makes the window roll.
"""
from cerebro.state import State



def _state(tmp_path):
    return State(db_path=str(tmp_path / "t.sqlite"))


def _seed(st, url_hash, first_seen, last_seen, simhash=1234):
    st.db.execute(
        "INSERT INTO seen(url_hash,simhash,url,title,source,category,score,first_seen,last_seen)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (url_hash, simhash, "https://snapstate.dev", "SnapState", "hackernews", None, None,
         first_seen, last_seen),
    )
    st.db.commit()


def test_item_admitted_yesterday_is_still_suppressed_today(tmp_path):
    """The regression. First seen 63 days ago, last admitted yesterday."""
    st = _state(tmp_path)
    _seed(st, "aaaa", first_seen="2026-06-20", last_seen=st.db.execute(
        "select date('now','-1 day')").fetchone()[0])
    assert st.seen_recent("aaaa", 14) is True, (
        "an item admitted yesterday must stay suppressed; measuring the window from "
        "first_seen is what let it back in every day"
    )


def test_item_not_seen_for_longer_than_the_window_returns(tmp_path):
    """The other half: the window really does roll off, so a genuinely stale story returns."""
    st = _state(tmp_path)
    old = st.db.execute("select date('now','-15 day')").fetchone()[0]
    _seed(st, "bbbb", first_seen="2026-06-20", last_seen=old)
    assert st.seen_recent("bbbb", 14) is False


def test_simhash_window_rolls_the_same_way(tmp_path):
    """recent_simhashes carried the identical defect, so near-dups of old items escaped too."""
    st = _state(tmp_path)
    fresh = st.db.execute("select date('now','-1 day')").fetchone()[0]
    stale = st.db.execute("select date('now','-15 day')").fetchone()[0]
    _seed(st, "cccc", first_seen="2026-06-20", last_seen=fresh, simhash=111)
    _seed(st, "dddd", first_seen="2026-06-20", last_seen=stale, simhash=222)
    hashes = st.recent_simhashes(14)
    assert 111 in hashes, "a near-dup of something admitted yesterday must still be caught"
    assert 222 not in hashes, "a near-dup of something stale must be allowed back"


def test_marking_refreshes_the_rolling_window(tmp_path):
    """mark() is what keeps a live story suppressed; dedup runs BEFORE triage, so a
    suppressed item is never re-marked and ages out on its own."""
    st = _state(tmp_path)
    stale = st.db.execute("select date('now','-15 day')").fetchone()[0]
    _seed(st, "eeee", first_seen="2026-06-20", last_seen=stale)
    assert st.seen_recent("eeee", 14) is False
    st.db.execute("UPDATE seen SET last_seen=date('now') WHERE url_hash='eeee'")
    st.db.commit()
    assert st.seen_recent("eeee", 14) is True
