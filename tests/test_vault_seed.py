"""T02t — F001 vault seed lane."""
from __future__ import annotations

from cerebro.gitintel import vault_seed
from cerebro.gitintel.vault_seed import GITHUB_RESERVED, seed_repos


def _note(dirpath, stem: str, body: str, captured: str = "2026-01-01T00:00:00+00:00"):
    (dirpath / f"{stem}.md").write_text(
        f"---\ntitle: \"n\"\ncaptured: {captured}\n---\n{body}\n", encoding="utf-8"
    )


def _signals(tmp_path):
    d = tmp_path / "Signals"
    d.mkdir(parents=True)
    return d


def test_reserved_set_has_no_duplicate_literals():
    # A hand-maintained security-ish list: a duplicate literal shrinks the set and
    # is how a real entry gets lost in a later edit.
    assert len(GITHUB_RESERVED) == vault_seed._GITHUB_RESERVED_LITERALS


def test_reserved_paths_are_dropped(tmp_path):
    d = _signals(tmp_path)
    _note(d, "a", "see https://github.com/sponsors/simonw and "
                  "https://github.com/topics/agents and https://github.com/real/repo")
    got = {r.full_name for r in seed_repos(tmp_path)}
    assert got == {"real/repo"}


def test_frontmatter_url_and_body_are_both_read(tmp_path):
    d = _signals(tmp_path)
    (d / "b.md").write_text(
        "---\nurl: https://github.com/fm/only\ncaptured: 2026-02-02T00:00:00+00:00\n---\n"
        "body mentions https://github.com/body/only too\n",
        encoding="utf-8",
    )
    got = {r.full_name for r in seed_repos(tmp_path)}
    assert got == {"fm/only", "body/only"}


def test_trailing_punctuation_query_fragment_and_git_suffix_stripped(tmp_path):
    d = _signals(tmp_path)
    _note(d, "c", "(https://github.com/o/one), https://github.com/o/two.git "
                  "https://github.com/o/three?tab=readme https://github.com/o/four#L2 "
                  "[link](https://github.com/o/five/)")
    got = {r.name for r in seed_repos(tmp_path)}
    assert got == {"one", "two", "three", "four", "five"}


def test_casing_preserved_and_dedup_is_case_insensitive(tmp_path):
    d = _signals(tmp_path)
    _note(d, "a", "https://github.com/Rich-Harris/Svelte", captured="2026-03-03T00:00:00+00:00")
    _note(d, "b", "https://github.com/rich-harris/svelte", captured="2026-01-01T00:00:00+00:00")
    seeds = seed_repos(tmp_path)
    assert len(seeds) == 1
    assert seeds[0].full_name == "Rich-Harris/Svelte"  # first seen (sorted note order)


def test_provenance_is_unioned_and_sorted(tmp_path):
    d = _signals(tmp_path)
    for stem in ("zzz", "aaa", "mmm"):
        _note(d, stem, "https://github.com/o/r")
    seeds = seed_repos(tmp_path)
    assert seeds[0].signal_hashes == ("aaa", "mmm", "zzz")


def test_first_seen_is_the_earliest_captured(tmp_path):
    d = _signals(tmp_path)
    _note(d, "a", "https://github.com/o/r", captured="2026-05-05T00:00:00+00:00")
    _note(d, "b", "https://github.com/o/r", captured="2026-02-02T00:00:00+00:00")
    assert seed_repos(tmp_path)[0].first_seen == "2026-02-02T00:00:00+00:00"


def test_order_is_deterministic_and_lowercase_keyed(tmp_path):
    d = _signals(tmp_path)
    _note(d, "a", "https://github.com/Zeta/x https://github.com/alpha/y https://github.com/M/z")
    keys = [r.key for r in seed_repos(tmp_path)]
    assert keys == sorted(keys)
    assert keys == [r.key for r in seed_repos(tmp_path)]


def test_missing_signals_dir_is_empty_not_an_error(tmp_path):
    assert seed_repos(tmp_path) == []


def test_no_network_client_parameter():
    # The lane is a pure function of a path. A client parameter would make it a
    # fetch lane, and e01's deliverable would depend on the token.
    import inspect
    assert list(inspect.signature(seed_repos).parameters) == ["vault_path"]
