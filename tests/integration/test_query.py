"""Integration tests for ``scripts/query.py``.

Every subcommand gets happy-path + the ``NOT_FOUND`` / missing-id behavior
from requirements.md R5. Uses the ``tmp_app_root`` fixture plus the
``insert_*`` seeders from ``tests/integration/conftest.py`` — no real DB
access.
"""

from __future__ import annotations

import json
from typing import Any


def _run(call_script, cwd, *args) -> tuple[int, Any, Any]:
    """Run query.py with args, parse stdout as JSON on success, stderr on failure.

    Returns ``(rc, stdout_json_or_None, stderr_json_or_None)``. ``Any`` is
    on purpose — the returned value might be a dict, a list, a scalar, or
    ``None`` depending on the subcommand. Tests that need a stricter shape
    assert it at the callsite.
    """
    rc, out, err = call_script("query.py", *args, cwd=cwd)
    out_parsed: Any = None
    err_parsed: Any = None
    if out.strip():
        out_parsed = json.loads(out)
    if err.strip():
        try:
            err_parsed = json.loads(err)
        except json.JSONDecodeError:
            err_parsed = None
    return rc, out_parsed, err_parsed


# ---------------------------------------------------------------------------
# get / batch-get / search — generic CRUD delegation
# ---------------------------------------------------------------------------


def test_get_returns_row_when_live(tmp_app_root, call_script, insert_artist) -> None:
    aid = insert_artist(tmp_app_root, name="Aoi")
    rc, out, _err = _run(call_script, tmp_app_root, "get", "--kind", "artist", "--id", aid)
    assert rc == 0
    assert isinstance(out, dict)
    assert out["id"] == aid
    assert out["name"] == "Aoi"
    assert out["status"] == 0


def test_get_returns_not_found_for_missing_id(tmp_app_root, call_script) -> None:
    rc, _out, err = _run(call_script, tmp_app_root, "get", "--kind", "artist", "--id", "no-such")
    assert rc == 1
    assert err is not None and err["error"]["code"] == "NOT_FOUND"


def test_get_returns_not_found_when_soft_deleted(tmp_app_root, call_script, insert_artist) -> None:
    aid = insert_artist(tmp_app_root, name="Gone", status=1)
    rc, _out, err = _run(call_script, tmp_app_root, "get", "--kind", "artist", "--id", aid)
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_get_rel_show_song_uses_composite_key(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Show")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="http://x")
    rc, out, _err = _run(
        call_script,
        tmp_app_root,
        "get",
        "--kind",
        "rel_show_song",
        "--id",
        f"{shid},{sid}",
    )
    assert rc == 0
    assert isinstance(out, dict)
    assert out["show_id"] == shid
    assert out["song_id"] == sid
    assert out["media_url"] == "http://x"


def test_get_rel_show_song_bad_key_returns_invalid_input(tmp_app_root, call_script) -> None:
    rc, _out, err = _run(
        call_script,
        tmp_app_root,
        "get",
        "--kind",
        "rel_show_song",
        "--id",
        "only-one-value",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_batch_get_mixes_present_missing_and_deleted(
    tmp_app_root, call_script, insert_artist
) -> None:
    live1 = insert_artist(tmp_app_root, name="B")
    live2 = insert_artist(tmp_app_root, name="A")
    deleted = insert_artist(tmp_app_root, name="Z", status=1)
    rc, out, _err = _run(
        call_script,
        tmp_app_root,
        "batch-get",
        "--kind",
        "artist",
        "--ids",
        f"{live1},no-such,{deleted},{live2}",
    )
    assert rc == 0
    assert isinstance(out, list)
    # Sorted by name, id — "A" comes before "B".
    returned_ids = [r["id"] for r in out]
    assert returned_ids == [live2, live1]


def test_batch_get_empty_ids_returns_empty_list(tmp_app_root, call_script) -> None:
    rc, out, _err = _run(call_script, tmp_app_root, "batch-get", "--kind", "artist", "--ids", "")
    assert rc == 0
    assert out == []


def test_search_case_insensitive_substring(tmp_app_root, call_script, insert_artist) -> None:
    insert_artist(tmp_app_root, name="Yui")
    insert_artist(tmp_app_root, name="LiSA")
    insert_artist(tmp_app_root, name="Aimer")
    rc, out, _err = _run(call_script, tmp_app_root, "search", "--kind", "artist", "--term", "LI")
    assert rc == 0
    assert isinstance(out, list)
    names = [r["name"] for r in out]
    # Only "LiSA" matches "LI" case-insensitively.
    assert names == ["LiSA"]


def test_search_url_decodes_term(tmp_app_root, call_script, insert_artist) -> None:
    """R4.1: ``--term`` is URL-decoded once before the LIKE runs."""
    insert_artist(tmp_app_root, name="hello world")
    # "hello%20world" decodes once to "hello world".
    rc, out, _err = _run(
        call_script,
        tmp_app_root,
        "search",
        "--kind",
        "artist",
        "--term",
        "hello%20world",
    )
    assert rc == 0
    assert isinstance(out, list) and len(out) == 1
    assert out[0]["name"] == "hello world"


def test_search_skips_soft_deleted(tmp_app_root, call_script, insert_artist) -> None:
    live = insert_artist(tmp_app_root, name="Keep Me")
    insert_artist(tmp_app_root, name="Keep Me", status=1)
    rc, out, _err = _run(call_script, tmp_app_root, "search", "--kind", "artist", "--term", "Keep")
    assert rc == 0
    assert [r["id"] for r in out] == [live]


def test_search_song_scans_name_context_too(
    tmp_app_root, call_script, insert_artist, insert_song
) -> None:
    """R5.5: search includes ``name_context`` for songs."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="plain", name_context="hidden", artist_id=aid)
    rc, out, _err = _run(call_script, tmp_app_root, "search", "--kind", "song", "--term", "hidden")
    assert rc == 0
    assert [r["id"] for r in out] == [sid]


# ---------------------------------------------------------------------------
# duplicates
# ---------------------------------------------------------------------------


def test_duplicates_songs_groups_by_artist_and_name(
    tmp_app_root, call_script, insert_artist, insert_song
) -> None:
    aid = insert_artist(tmp_app_root, name="Common Artist")
    bid = insert_artist(tmp_app_root, name="Other Artist")
    s1 = insert_song(tmp_app_root, name="Hit", artist_id=aid)
    s2 = insert_song(tmp_app_root, name="Hit", artist_id=aid)
    # Same song name under a different artist → NOT a duplicate per R5.7.
    insert_song(tmp_app_root, name="Hit", artist_id=bid)
    # A duplicate under a soft-deleted status → ignored.
    insert_song(tmp_app_root, name="Hit", artist_id=aid, status=1)

    rc, out, _err = _run(call_script, tmp_app_root, "duplicates", "--kind", "song")
    assert rc == 0
    assert isinstance(out, list) and len(out) == 1
    group = out[0]
    assert group["name"] == "Hit"
    assert group["artist_id"] == aid
    assert set(group["ids"]) == {s1, s2}


def test_duplicates_artists_groups_by_name(tmp_app_root, call_script, insert_artist) -> None:
    a1 = insert_artist(tmp_app_root, name="Twin", name_context="solo")
    a2 = insert_artist(tmp_app_root, name="Twin", name_context="band")
    insert_artist(tmp_app_root, name="Unique")
    rc, out, _err = _run(call_script, tmp_app_root, "duplicates", "--kind", "artist")
    assert rc == 0
    assert len(out) == 1
    assert out[0]["name"] == "Twin"
    assert set(out[0]["ids"]) == {a1, a2}


def test_duplicates_shows_groups_by_name_and_vintage(
    tmp_app_root, call_script, insert_show
) -> None:
    insert_show(tmp_app_root, name="Show", vintage="Spring 2021")
    insert_show(tmp_app_root, name="Show", vintage="Spring 2021")
    # Same name, different vintage → not a duplicate per R5.7.
    insert_show(tmp_app_root, name="Show", vintage="Fall 2021")
    rc, out, _err = _run(call_script, tmp_app_root, "duplicates", "--kind", "show")
    assert rc == 0
    assert len(out) == 1
    assert out[0]["name"] == "Show"
    assert out[0]["vintage"] == "Spring 2021"
    assert len(out[0]["ids"]) == 2


# ---------------------------------------------------------------------------
# shows-by-artist-ids / songs-by-artist-ids
# ---------------------------------------------------------------------------


def test_shows_by_artist_ids_returns_linked_shows(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    aid = insert_artist(tmp_app_root, name="Prime")
    sid = insert_song(tmp_app_root, name="Track", artist_id=aid)
    live_show = insert_show(tmp_app_root, name="A Show")
    deleted_show = insert_show(tmp_app_root, name="Hidden", status=1)
    insert_rel(tmp_app_root, show_id=live_show, song_id=sid)
    insert_rel(tmp_app_root, show_id=deleted_show, song_id=sid)
    rc, out, _err = _run(
        call_script,
        tmp_app_root,
        "shows-by-artist-ids",
        "--artist-ids",
        aid,
    )
    assert rc == 0
    assert [s["id"] for s in out] == [live_show]


def test_songs_by_artist_ids_filters_soft_deleted(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    live_artist = insert_artist(tmp_app_root, name="Live")
    dead_artist = insert_artist(tmp_app_root, name="Dead", status=1)
    live_song = insert_song(tmp_app_root, name="alive", artist_id=live_artist)
    insert_song(tmp_app_root, name="gone", artist_id=live_artist, status=1)
    insert_song(tmp_app_root, name="orphan", artist_id=dead_artist)
    rc, out, _err = _run(
        call_script,
        tmp_app_root,
        "songs-by-artist-ids",
        "--artist-ids",
        f"{live_artist},{dead_artist}",
    )
    assert rc == 0
    # Only live song under live artist.
    assert [s["id"] for s in out] == [live_song]


def test_empty_artist_ids_lists_are_empty_arrays(tmp_app_root, call_script) -> None:
    for cmd in ("shows-by-artist-ids", "songs-by-artist-ids"):
        rc, out, _err = _run(call_script, tmp_app_root, cmd, "--artist-ids", "")
        assert rc == 0
        assert out == []


# ---------------------------------------------------------------------------
# list-learning
# ---------------------------------------------------------------------------


def test_list_learning_returns_active_and_graduated(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    active = insert_learning(tmp_app_root, song_id=sid, updated_at=1_700_000_000)
    graduated = insert_learning(tmp_app_root, song_id=sid, graduated=1, updated_at=1_700_000_100)
    rc, out, _err = _run(call_script, tmp_app_root, "list-learning", "--song-ids", sid)
    assert rc == 0
    # Ordered by updated_at DESC, id ASC.
    assert [r["id"] for r in out] == [graduated, active]


def test_list_learning_skips_rows_whose_song_is_soft_deleted(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    live = insert_song(tmp_app_root, name="Live", artist_id=aid)
    dead = insert_song(tmp_app_root, name="Dead", artist_id=aid, status=1)
    keep = insert_learning(tmp_app_root, song_id=live)
    insert_learning(tmp_app_root, song_id=dead)
    rc, out, _err = _run(
        call_script,
        tmp_app_root,
        "list-learning",
        "--song-ids",
        f"{live},{dead}",
    )
    assert rc == 0
    assert [r["id"] for r in out] == [keep]


def test_list_learning_missing_ids_return_empty_array(tmp_app_root, call_script) -> None:
    rc, out, _err = _run(
        call_script,
        tmp_app_root,
        "list-learning",
        "--song-ids",
        "no-such-song-1,no-such-song-2",
    )
    assert rc == 0
    assert out == []


# ---------------------------------------------------------------------------
# *-detail ops
# ---------------------------------------------------------------------------


def test_song_detail_happy_path(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
) -> None:
    aid = insert_artist(tmp_app_root, name="Yui")
    sid = insert_song(tmp_app_root, name="Again", artist_id=aid)
    show_b = insert_show(tmp_app_root, name="B-show")
    show_a = insert_show(tmp_app_root, name="A-show")
    insert_rel(tmp_app_root, show_id=show_a, song_id=sid)
    insert_rel(tmp_app_root, show_id=show_b, song_id=sid)
    insert_play_history(tmp_app_root, show_id=show_a, song_id=sid, media_url="http://m/z")
    insert_play_history(tmp_app_root, show_id=show_a, song_id=sid, media_url="http://m/a")
    insert_play_history(tmp_app_root, show_id=show_a, song_id=sid, media_url="")
    insert_play_history(
        tmp_app_root, show_id=show_a, song_id=sid, media_url="http://m/a"
    )  # dup — deduped

    rc, out, _err = _run(call_script, tmp_app_root, "song-detail", "--id", sid)
    assert rc == 0
    assert isinstance(out, dict)
    assert out["song"]["id"] == sid
    assert out["artist"]["id"] == aid
    assert out["artist"]["status"] == 0
    # Shows sorted by name ASC.
    assert [s["id"] for s in out["shows"]] == [show_a, show_b]
    # media_urls on show_a: sorted, deduped, non-empty.
    assert out["shows"][0]["media_urls"] == ["http://m/a", "http://m/z"]
    assert out["shows"][1]["media_urls"] == []


def test_song_detail_missing_returns_not_found(tmp_app_root, call_script) -> None:
    rc, _out, err = _run(call_script, tmp_app_root, "song-detail", "--id", "no-such")
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_song_detail_soft_deleted_returns_not_found(
    tmp_app_root, call_script, insert_artist, insert_song
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="Gone", artist_id=aid, status=1)
    rc, _out, err = _run(call_script, tmp_app_root, "song-detail", "--id", sid)
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_artist_detail_sorts_songs_and_shows(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    aid = insert_artist(tmp_app_root, name="Prime")
    s_b = insert_song(tmp_app_root, name="Bravo", artist_id=aid)
    s_a = insert_song(tmp_app_root, name="Alpha", artist_id=aid)
    # Soft-deleted — must not appear.
    insert_song(tmp_app_root, name="Hidden", artist_id=aid, status=1)
    show_z = insert_show(tmp_app_root, name="Zeta Show")
    show_a = insert_show(tmp_app_root, name="Alpha Show")
    insert_rel(tmp_app_root, show_id=show_z, song_id=s_a)
    insert_rel(tmp_app_root, show_id=show_a, song_id=s_a)

    rc, out, _err = _run(call_script, tmp_app_root, "artist-detail", "--id", aid)
    assert rc == 0
    assert out["artist"]["id"] == aid
    song_ids = [s["id"] for s in out["songs"]]
    assert song_ids == [s_a, s_b]  # sorted by name ASC
    # Shows under Alpha sorted by show name.
    alpha_shows = [s["id"] for s in out["songs"][0]["shows"]]
    assert alpha_shows == [show_a, show_z]


def test_artist_detail_missing_returns_not_found(tmp_app_root, call_script) -> None:
    rc, _out, err = _run(call_script, tmp_app_root, "artist-detail", "--id", "no-such")
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_show_detail_lists_songs_with_artist_status(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
) -> None:
    aid = insert_artist(tmp_app_root, name="The Band")
    sid = insert_song(tmp_app_root, name="Track 1", artist_id=aid)
    shid = insert_show(tmp_app_root, name="On Air")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid)
    insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url="http://a")

    rc, out, _err = _run(call_script, tmp_app_root, "show-detail", "--id", shid)
    assert rc == 0
    assert out["show"]["id"] == shid
    assert len(out["songs"]) == 1
    only = out["songs"][0]
    assert only["id"] == sid
    assert only["artist"]["id"] == aid
    assert only["artist"]["status"] == 0
    assert only["media_urls"] == ["http://a"]


def test_show_detail_missing_returns_not_found(tmp_app_root, call_script) -> None:
    rc, _out, err = _run(call_script, tmp_app_root, "show-detail", "--id", "no-such")
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_learning_detail_happy_path(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(tmp_app_root, song_id=sid, level=3)
    rc, out, _err = _run(call_script, tmp_app_root, "learning-detail", "--id", lid)
    assert rc == 0
    assert out["learning"]["id"] == lid
    assert out["learning"]["display_level"] == 4  # stored + 1
    assert isinstance(out["learning"]["level_up_path"], list)
    assert out["song"]["id"] == sid
    assert out["artist"]["id"] == aid
    assert out["artist"]["status"] == 0


def test_learning_detail_missing_returns_not_found(tmp_app_root, call_script) -> None:
    rc, _out, err = _run(call_script, tmp_app_root, "learning-detail", "--id", "no-such")
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_learning_detail_song_soft_deleted_returns_not_found(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="Gone", artist_id=aid, status=1)
    lid = insert_learning(tmp_app_root, song_id=sid)
    rc, _out, err = _run(call_script, tmp_app_root, "learning-detail", "--id", lid)
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_learning_detail_artist_soft_deleted_returns_not_found(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R5.15: artist soft-deleted → learning-detail returns NOT_FOUND."""
    aid = insert_artist(tmp_app_root, name="Dead", status=1)
    # Need a live song pointing at the soft-deleted artist to reach the
    # artist-check branch — in a healthy DB this doesn't happen, but the
    # check must hold up for a broken DB too.
    sid = insert_song(tmp_app_root, name="Orphan", artist_id=aid)
    lid = insert_learning(tmp_app_root, song_id=sid)
    rc, _out, err = _run(call_script, tmp_app_root, "learning-detail", "--id", lid)
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Bare `--help` / no-args behavior (R2.4)
# ---------------------------------------------------------------------------


def test_no_args_prints_help_and_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, err = call_script("query.py", cwd=tmp_app_root)
    assert rc == 0
    combined = (out + err).lower()
    assert "usage" in combined or "query.py" in combined


def test_help_flag_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, _err = call_script("query.py", "--help", cwd=tmp_app_root)
    assert rc == 0
    assert "usage" in out.lower()


# ---------------------------------------------------------------------------
# Sanity: query.py never writes to the DB
# ---------------------------------------------------------------------------


def test_query_py_does_not_modify_the_temp_db(tmp_app_root, call_script, insert_artist) -> None:
    """A sweep of read ops must leave the DB byte-identical."""
    aid = insert_artist(tmp_app_root, name="Watcher")
    db_file = tmp_app_root / "db" / "datasource.db"
    before_bytes = db_file.read_bytes()

    for args in (
        ("get", "--kind", "artist", "--id", aid),
        ("batch-get", "--kind", "artist", "--ids", aid),
        ("search", "--kind", "artist", "--term", "Watch"),
        ("duplicates", "--kind", "artist"),
        ("artist-detail", "--id", aid),
    ):
        rc, _out, _err = call_script("query.py", *args, cwd=tmp_app_root)
        assert rc == 0

    after_bytes = db_file.read_bytes()
    assert before_bytes == after_bytes
