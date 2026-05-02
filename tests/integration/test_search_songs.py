"""Integration tests for ``scripts/query.py search-songs``.

This file pins the CLI contract for the new ``search-songs`` subcommand
introduced by the ``search-enhancements`` spec. Every test here drives
``query.py`` as a subprocess through the ``call_script`` fixture, seeds
rows via the ``insert_*`` helpers in ``tests/integration/conftest.py``,
and asserts on the Search_Envelope shape byte-for-byte.

The envelope shape pinned here is:

    {
      "filters": {
        "song_term":   <str | null>,
        "show_term":   <str | null>,
        "artist_term": <str | null>
      },
      "count":   <int>,
      "results": [ Song_Search_Result, ... ]
    }

Key order in the envelope and in the ``filters`` object is asserted via
``list(obj.keys()) == [...]`` so the tests catch drift.
"""

from __future__ import annotations

import json
from typing import Any


def _run(call_script, cwd, *args) -> tuple[int, Any, Any]:
    """Run ``query.py`` with ``args``, parse stdout as JSON on success.

    Returns ``(rc, stdout_json_or_None, stderr_json_or_None)``. Stdout is
    parsed only when non-empty; stderr is parsed if it's JSON, else left
    as ``None``. Tests that need the raw text assert on the underlying
    ``call_script`` output directly.
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
# Zero_Filter_Behavior (R-SE-1.3, R-SE-4.4)
# ---------------------------------------------------------------------------


def test_no_filters_lists_every_live_song(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """``search-songs`` with zero filters returns every live song.

    Seeds one live artist with two live songs, zero shows, zero
    learning rows. Asserts:
      * Exit 0 and stdout parses as JSON.
      * Envelope key order is exactly ``["filters", "count", "results"]``.
      * ``filters`` is ``{"song_term": None, "show_term": None, "artist_term": None}``
        with key order ``["song_term", "show_term", "artist_term"]``.
      * ``count == 2 == len(results)``.
      * ``results`` is ordered by ``(song.name, song.id)``.

    Validates: R-SE-1.3, R-SE-3.10, R-SE-4.1, R-SE-4.2, R-SE-4.3, R-SE-4.4.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    # Deliberately insert the "Bravo" song first so the ORDER BY name
    # assertion is meaningful — if the op returned insertion order the
    # test would still fail.
    bravo_id = insert_song(tmp_app_root, name="Bravo", artist_id=aid)
    alpha_id = insert_song(tmp_app_root, name="Alpha", artist_id=aid)

    rc, out, err = _run(call_script, tmp_app_root, "search-songs")

    assert rc == 0, f"expected exit 0, got rc={rc}, stderr={err!r}"
    assert out is not None, "expected non-empty JSON on stdout"

    # Envelope shape: top-level keys and their order.
    assert isinstance(out, dict)
    assert list(out.keys()) == ["filters", "count", "results"]

    # filters echo: every key present, every value None, exact order.
    assert list(out["filters"].keys()) == ["song_term", "show_term", "artist_term"]
    assert out["filters"] == {
        "song_term": None,
        "show_term": None,
        "artist_term": None,
    }

    # count matches len(results) (R-SE-4.3) and both equal 2.
    assert out["count"] == 2
    assert isinstance(out["results"], list)
    assert len(out["results"]) == 2
    assert out["count"] == len(out["results"])

    # Stable order: (song.name ASC, song.id ASC). With names "Alpha" and
    # "Bravo", Alpha must come first regardless of insertion order.
    returned_ids = [r["song"]["id"] for r in out["results"]]
    assert returned_ids == [alpha_id, bravo_id]


# ---------------------------------------------------------------------------
# Envelope shape / key order / stdout framing (R-SE-4.1, R-SE-4.5)
# ---------------------------------------------------------------------------


def test_envelope_top_level_shape_and_key_order(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """``search-songs`` with zero filters emits the pinned envelope shape.

    This test is narrowly focused on the envelope framing, independent of
    any per-row payload. Uses ``call_script`` directly (not ``_run``) so
    the raw stdout string is available for the trailing-newline check
    required by R-SE-4.5 — the test needs to see the literal bytes, not
    just the parsed JSON.

    Seeds exactly one live song under one live artist, runs with zero
    filters, and asserts:
      * Exit 0.
      * Top-level envelope key order is ``["filters", "count", "results"]``.
      * Inner ``filters`` key order is
        ``["song_term", "show_term", "artist_term"]``.
      * Stdout ends with exactly one trailing newline — no extra blank
        line, no missing terminator. This pins parent R3.1/R3.4's stdout
        framing for the new op.

    Validates: R-SE-4.1, R-SE-4.5.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    insert_song(tmp_app_root, name="OnlySong", artist_id=aid)

    rc, out, err = call_script("query.py", "search-songs", cwd=tmp_app_root)

    assert rc == 0, f"expected exit 0, got rc={rc}, stderr={err!r}"

    # Stdout framing (R-SE-4.5): a single JSON document followed by exactly
    # one trailing newline. An empty stdout would fail the first check; a
    # missing newline or a doubled newline would fail the second.
    assert out, "expected non-empty stdout"
    assert out.endswith("\n"), "stdout must end with a newline"
    assert not out.endswith("\n\n"), "stdout must end with exactly one newline"

    # Parse with ``object_pairs_hook=list`` so we can assert on key order
    # even at the innermost level without relying on dict-insertion-order
    # round-tripping through ``json.loads``. (Modern Python preserves
    # insertion order on the dict, but being explicit here makes the
    # intent obvious and the failure message more precise.)
    pairs = json.loads(out, object_pairs_hook=list)

    # Top-level envelope is a JSON object (list of pairs here).
    assert isinstance(pairs, list), "envelope must be a JSON object"
    top_keys = [k for k, _v in pairs]
    assert top_keys == ["filters", "count", "results"], (
        f"top-level key order mismatch; got {top_keys!r}"
    )

    # Inner ``filters`` object: every key present, exact order.
    filters_pairs = dict(pairs)["filters"]
    assert isinstance(filters_pairs, list), "filters must be a JSON object"
    filter_keys = [k for k, _v in filters_pairs]
    assert filter_keys == ["song_term", "show_term", "artist_term"], (
        f"filters key order mismatch; got {filter_keys!r}"
    )


# ---------------------------------------------------------------------------
# Per-result shape (R-SE-3.2, R-SE-3.3)
# ---------------------------------------------------------------------------


def test_song_result_shape_keys_and_order(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """``search-songs`` pins the Song_Search_Result top-level shape.

    Seeds one live song under one live artist with no shows, no learning,
    and no play-history rows. Runs with zero filters and asserts:
      * The per-result top-level key order is exactly
        ``["song", "artist", "shows", "learning", "graduated", "warnings"]``
        (R-SE-3.2). Uses ``object_pairs_hook=list`` the same way test 1.2
        does so the order check is rigorous, not just a set check.
      * ``song`` contains every schema column of ``song``
        (``id, name, name_context, artist_id, created_at, updated_at,
        status``) — asserted as a key *set* because the column order
        within ``SELECT * FROM song`` is a property of the query, not
        this envelope (R-SE-3.3).
      * ``artist`` key set is exactly ``{"id", "name", "name_context",
        "status"}`` — mirrors the parent ``song-detail`` op's nested
        artist per R-SE-3.2.
      * With no shows, no learning, and no glitches: ``shows == []``,
        ``learning is None``, ``graduated is False``, ``warnings == []``.

    Validates: R-SE-3.2, R-SE-3.3.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    insert_song(tmp_app_root, name="OnlySong", artist_id=aid)

    rc, out, err = call_script("query.py", "search-songs", cwd=tmp_app_root)

    assert rc == 0, f"expected exit 0, got rc={rc}, stderr={err!r}"
    assert out, "expected non-empty stdout"

    # Parse with ``object_pairs_hook=list`` so the key-order assertion on
    # ``results[0]`` is rigorous, not just relying on dict-insertion-order
    # round-tripping. ``pairs`` is a list of (key, value) tuples at every
    # JSON-object level.
    pairs = json.loads(out, object_pairs_hook=list)
    envelope = dict(pairs)

    # ``results`` under object_pairs_hook=list is a regular list of items;
    # each object element is itself a list-of-pairs. Grab the first (and
    # only) Song_Search_Result and assert on its ordered keys.
    results = envelope["results"]
    assert isinstance(results, list)
    assert len(results) == 1, f"expected exactly one result, got {len(results)}"

    result_pairs = results[0]
    assert isinstance(result_pairs, list), "each result must be a JSON object"
    result_keys = [k for k, _v in result_pairs]
    assert result_keys == [
        "song",
        "artist",
        "shows",
        "learning",
        "graduated",
        "warnings",
    ], f"per-result key order mismatch; got {result_keys!r}"

    # Parse the same stdout as regular dicts for the value-level checks.
    # The envelope / per-result key order has already been pinned above.
    parsed = json.loads(out)
    row = parsed["results"][0]

    # song row: every schema column is present. Order of columns inside
    # SELECT * FROM song is left to the SQL layer (R-SE-3.3 is about
    # *presence*, not position), so assert on the key set.
    assert set(row["song"].keys()) == {
        "id",
        "name",
        "name_context",
        "artist_id",
        "created_at",
        "updated_at",
        "status",
    }

    # artist: exactly these four keys (mirrors song-detail's nested artist).
    assert set(row["artist"].keys()) == {"id", "name", "name_context", "status"}

    # Defaults when nothing is linked.
    assert row["shows"] == []
    assert row["learning"] is None
    assert row["graduated"] is False
    assert row["warnings"] == []


# ---------------------------------------------------------------------------
# Empty result set (R-SE-3.9, R-SE-4.2, R-SE-4.3)
# ---------------------------------------------------------------------------


def test_empty_result_set_exits_zero_with_envelope(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """``search-songs`` returns a successful empty envelope on a no-hit run.

    Zero matches is a successful query, not an error — same pattern parent
    R5.4 sets for ``batch-get``. Seeds one live song (so the DB is not
    empty) and filters with a song-term that is guaranteed not to appear
    in any ``song.name`` or ``song.name_context``. Asserts:
      * Exit 0 (no ``NOT_FOUND`` Error_Envelope on no hits).
      * ``count == 0`` and ``results == []``.
      * ``filters.song_term`` echoes the decoded Active_Filter value
        verbatim (R-SE-4.2), while the other two Inactive_Filter keys
        stay ``None``.
      * Stderr is exactly empty — no Error_Envelope is emitted on a
        successful no-hit run (R-SE-4.6 only applies on handled failure).

    Uses ``call_script`` directly for the stderr check so the raw stderr
    string is visible — ``_run`` drops empty stderr to ``None`` which
    would let a stray whitespace-only write sneak past the assertion.

    Validates: R-SE-3.9, R-SE-4.2, R-SE-4.3.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    insert_song(tmp_app_root, name="OnlySong", artist_id=aid)

    rc, out, err = call_script(
        "query.py",
        "search-songs",
        "--song-term",
        "zzz-no-match-zzz",
        cwd=tmp_app_root,
    )

    # Success envelope on stdout, exit 0, nothing on stderr.
    assert rc == 0, f"expected exit 0, got rc={rc}, stderr={err!r}"
    assert err == "", f"expected empty stderr on no-hit run, got {err!r}"
    assert out, "expected non-empty stdout"

    parsed = json.loads(out)

    # Envelope still carries all three top-level keys.
    assert list(parsed.keys()) == ["filters", "count", "results"]

    # filters echo: Active --song-term is the decoded string verbatim,
    # the other two filters stay null.
    assert parsed["filters"] == {
        "song_term": "zzz-no-match-zzz",
        "show_term": None,
        "artist_term": None,
    }

    # Empty result set: count == 0, results is an empty list, and the
    # two are in lock-step (R-SE-4.3).
    assert parsed["count"] == 0
    assert parsed["results"] == []
    assert parsed["count"] == len(parsed["results"])


# ---------------------------------------------------------------------------
# Byte-stability across re-runs (R-SE-4.7)
# ---------------------------------------------------------------------------


def test_rerun_same_filters_produces_byte_identical_stdout(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
) -> None:
    """Re-running ``search-songs`` with the same filters yields identical stdout.

    Seeds a small but non-trivial library (2 artists x 2 songs x 1 show x
    1 rel each, one ``play_history`` row per pair), runs the op twice
    with ``--artist-term a``, and compares the raw stdout strings for
    byte equality. The filter is a case-insensitive substring on artist
    name; both seeded artist names contain "a" so at least one row comes
    back. The goal is byte-stability, not result count — a subset of the
    library is sufficient.

    All seeded rows use the conftest ``PINNED_EPOCH`` default for
    ``created_at`` / ``updated_at``, and ``search-songs`` is a pure read
    that never generates timestamps, so ``call_script`` (without a
    pinned clock) is deterministic here.

    Validates: R-SE-4.7.
    """
    # Two artists, both with names containing "a" (case-insensitive) so
    # the --artist-term a substring filter picks them up.
    aid_alpha = insert_artist(tmp_app_root, name="Akane")
    aid_beta = insert_artist(tmp_app_root, name="Hana")

    # Each artist has two songs; each song is linked to one distinct show
    # via rel_show_song, and has one play_history row for that pair.
    sid_a1 = insert_song(tmp_app_root, name="SongA1", artist_id=aid_alpha)
    sid_a2 = insert_song(tmp_app_root, name="SongA2", artist_id=aid_alpha)
    sid_b1 = insert_song(tmp_app_root, name="SongB1", artist_id=aid_beta)
    sid_b2 = insert_song(tmp_app_root, name="SongB2", artist_id=aid_beta)

    shid_a1 = insert_show(tmp_app_root, name="ShowA1")
    shid_a2 = insert_show(tmp_app_root, name="ShowA2")
    shid_b1 = insert_show(tmp_app_root, name="ShowB1")
    shid_b2 = insert_show(tmp_app_root, name="ShowB2")

    for shid, sid in (
        (shid_a1, sid_a1),
        (shid_a2, sid_a2),
        (shid_b1, sid_b1),
        (shid_b2, sid_b2),
    ):
        insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="")
        insert_play_history(
            tmp_app_root,
            show_id=shid,
            song_id=sid,
            media_url=f"http://example.test/{shid}-{sid}",
        )

    # Run twice with the same filter. Use call_script directly so the
    # raw stdout bytes are available for comparison — _run would parse
    # the JSON and discard whitespace / ordering signals.
    rc1, out1, err1 = call_script(
        "query.py", "search-songs", "--artist-term", "a", cwd=tmp_app_root
    )
    rc2, out2, err2 = call_script(
        "query.py", "search-songs", "--artist-term", "a", cwd=tmp_app_root
    )

    assert rc1 == 0, f"first run failed: rc={rc1}, stderr={err1!r}"
    assert rc2 == 0, f"second run failed: rc={rc2}, stderr={err2!r}"

    # Byte-identical raw stdout across the two runs. This pins the
    # full output — not just the parsed JSON — so any drift in key
    # order, whitespace, or trailing newline handling would fail.
    assert out1 == out2, "stdout differed between identical re-runs"


# ---------------------------------------------------------------------------
# Filter semantics (R-SE-1.x, R-SE-2.x)
# ---------------------------------------------------------------------------


def test_single_song_term_matches_substring_case_insensitive(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """Song-term is a case-insensitive substring match on ``song.name``.

    Seeds mixed-case names. Running with ``--song-term liSa`` must return
    the rows whose name (lower-cased) contains "lisa" and nothing else.

    Validates: R-SE-2.1, R-SE-2.9.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    hit_upper = insert_song(tmp_app_root, name="MyLISAsong", artist_id=aid)
    hit_lower = insert_song(tmp_app_root, name="another-lisa-track", artist_id=aid)
    insert_song(tmp_app_root, name="Unrelated", artist_id=aid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs", "--song-term", "liSa")
    assert rc == 0
    assert out is not None
    returned = {r["song"]["id"] for r in out["results"]}
    assert returned == {hit_upper, hit_lower}
    assert out["count"] == 2


def test_url_decodes_term_once(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """``--song-term`` is URL-decoded exactly once before matching.

    Seeds a song whose name contains a literal space. The CLI is given
    ``A%20B`` which ``urllib.parse.unquote`` decodes to ``A B``; that
    decoded term must match the seeded song.

    Validates: R-SE-1.5.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="A B", artist_id=aid)
    insert_song(tmp_app_root, name="NoSpace", artist_id=aid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs", "--song-term", "A%20B")
    assert rc == 0
    assert out is not None
    returned = {r["song"]["id"] for r in out["results"]}
    assert returned == {sid}
    # The echoed filter value is the decoded form, not the raw CLI value.
    assert out["filters"]["song_term"] == "A B"


def test_empty_term_matches_every_row(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """``--song-term ""`` is equivalent to Zero_Filter_Behavior for song-term.

    An Empty_Filter_Term (decoded value ``""``) applies a vacuous
    substring match — every live song under a live artist is returned.

    Validates: R-SE-1.5, R-SE-2.1.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    s1 = insert_song(tmp_app_root, name="One", artist_id=aid)
    s2 = insert_song(tmp_app_root, name="Two", artist_id=aid)
    s3 = insert_song(tmp_app_root, name="Three", artist_id=aid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs", "--song-term", "")
    assert rc == 0
    assert out is not None
    returned = {r["song"]["id"] for r in out["results"]}
    assert returned == {s1, s2, s3}
    # Empty string is Active — echoed as "" not null.
    assert out["filters"]["song_term"] == ""


def test_repeated_flag_last_value_wins(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """Passing ``--song-term`` twice: argparse's default keeps the last value.

    Seeds songs matching "a" and "b". Running with
    ``--song-term a --song-term b`` must leave only the ``b``-matching
    set, and ``filters.song_term`` must echo ``"b"``.

    Validates: R-SE-1.7.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    a_hit = insert_song(tmp_app_root, name="alpha", artist_id=aid)
    b_hit = insert_song(tmp_app_root, name="bravo", artist_id=aid)

    rc, out, _err = _run(
        call_script,
        tmp_app_root,
        "search-songs",
        "--song-term",
        "a",
        "--song-term",
        "b",
    )
    assert rc == 0
    assert out is not None
    returned = {r["song"]["id"] for r in out["results"]}
    # Only "b"-matching songs; "alpha" must be excluded.
    assert returned == {b_hit}
    assert a_hit not in returned
    assert out["filters"]["song_term"] == "b"


def test_show_term_requires_matching_link(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    """``--show-term`` requires at least one live linked show matching the term.

    Seeds a song linked only to a show named "Zeta". A ``--show-term Fma``
    run returns zero rows; a ``--show-term Zeta`` run returns the song.

    Validates: R-SE-2.7.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Zeta")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid)

    # No link to a show matching "Fma" → zero rows.
    rc, out, _err = _run(call_script, tmp_app_root, "search-songs", "--show-term", "Fma")
    assert rc == 0
    assert out is not None
    assert out["count"] == 0
    assert out["results"] == []

    # A show matching "Zeta" is linked → song comes back.
    rc, out, _err = _run(call_script, tmp_app_root, "search-songs", "--show-term", "Zeta")
    assert rc == 0
    assert out is not None
    returned = {r["song"]["id"] for r in out["results"]}
    assert returned == {sid}


def test_show_term_inactive_keeps_songs_with_no_shows(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """Inactive ``--show-term`` does not require any linked show.

    Seeds a song with zero ``rel_show_song`` rows. Zero_Filter_Behavior
    must return it, and its ``shows`` array must be ``[]``.

    Validates: R-SE-2.8.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="Lonely", artist_id=aid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1
    row = out["results"][0]
    assert row["song"]["id"] == sid
    assert row["shows"] == []


def test_song_status_1_excluded(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """Soft-deleted songs (``song.status = 1``) never appear in results.

    Seeds a live artist with one live song and one soft-deleted song.
    Zero_Filter_Behavior returns only the live song.

    Validates: R-SE-2.5.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    live = insert_song(tmp_app_root, name="Alive", artist_id=aid)
    insert_song(tmp_app_root, name="Dead", artist_id=aid, status=1)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    returned = {r["song"]["id"] for r in out["results"]}
    assert returned == {live}


def test_artist_status_1_excludes_song(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """A live song under a soft-deleted artist is excluded.

    Seeds a soft-deleted artist and a live song pointing at them.
    Zero_Filter_Behavior must skip the song entirely.

    Validates: R-SE-2.6.
    """
    dead_aid = insert_artist(tmp_app_root, name="Dead", status=1)
    insert_song(tmp_app_root, name="Orphan", artist_id=dead_aid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 0
    assert out["results"] == []


def test_soft_deleted_show_absent_from_shows_array(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    """Soft-deleted shows (``show.status = 1``) are excluded from ``shows``.

    Seeds a song linked to one live show and one soft-deleted show.
    The song's ``shows`` array contains only the live show regardless
    of whether ``--show-term`` is active.

    Validates: R-SE-2.5, R-SE-2.7 (show-side).
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    live_show = insert_show(tmp_app_root, name="LiveShow")
    dead_show = insert_show(tmp_app_root, name="DeadShow", status=1)
    insert_rel(tmp_app_root, show_id=live_show, song_id=sid)
    insert_rel(tmp_app_root, show_id=dead_show, song_id=sid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1
    row = out["results"][0]
    show_ids = [e["id"] for e in row["shows"]]
    assert show_ids == [live_show]
    assert dead_show not in show_ids


# ---------------------------------------------------------------------------
# Shape and ordering (R-SE-3.x, R-SE-4.x)
# ---------------------------------------------------------------------------


def test_show_entry_shape_includes_matched_filter(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    """Each Show_Entry pins the key order
    ``[id, name, name_romaji, vintage, s_type, media_urls, matched_filter]``.

    Seeds one live song linked to one live show with every optional show
    column populated (so the assertion is not accidentally about keys
    whose values happen to be ``null``). Runs with zero filters and
    parses stdout with ``object_pairs_hook=list`` — the same pattern
    test 1.2 uses — so the ordered-keys assertion reads the actual JSON
    byte order rather than relying on dict-insertion-order round-trip.

    Validates: R-SE-3.4.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    shid = insert_show(
        tmp_app_root,
        name="The Show",
        name_romaji="Za Shou",
        vintage="2020 Spring",
        s_type="TV",
    )
    insert_rel(tmp_app_root, show_id=shid, song_id=sid)

    rc, out, err = call_script("query.py", "search-songs", cwd=tmp_app_root)
    assert rc == 0, f"expected exit 0, got rc={rc}, stderr={err!r}"
    assert out, "expected non-empty stdout"

    # Walk into results[0]["shows"][0] preserving JSON key order.
    pairs = json.loads(out, object_pairs_hook=list)
    envelope = dict(pairs)
    results = envelope["results"]
    assert len(results) == 1

    # Each result is itself a list-of-pairs under object_pairs_hook=list.
    result_obj = dict(results[0])
    shows = result_obj["shows"]
    assert isinstance(shows, list) and len(shows) == 1

    entry_pairs = shows[0]
    assert isinstance(entry_pairs, list), "Show_Entry must be a JSON object"
    entry_keys = [k for k, _v in entry_pairs]
    assert entry_keys == [
        "id",
        "name",
        "name_romaji",
        "vintage",
        "s_type",
        "media_urls",
        "matched_filter",
    ], f"Show_Entry key order mismatch; got {entry_keys!r}"


def test_shows_array_contains_every_live_linked_show(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    """With ``--show-term`` matching only one of two linked shows, the
    song's ``shows`` array still lists both and ``matched_filter`` is
    True for the matching show and False for the other.

    Per R-SE-3.5 the op does not clamp the ``shows`` list to only
    matching shows; it returns every live linked show and lets the
    caller filter client-side via ``matched_filter``. Seeds a song
    linked to "Alpha" and "Bravo", runs ``--show-term alpha``, and
    asserts both shows are present with the expected per-entry
    ``matched_filter`` flags.

    Validates: R-SE-3.4, R-SE-3.5.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    alpha = insert_show(tmp_app_root, name="Alpha")
    bravo = insert_show(tmp_app_root, name="Bravo")
    insert_rel(tmp_app_root, show_id=alpha, song_id=sid)
    insert_rel(tmp_app_root, show_id=bravo, song_id=sid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs", "--show-term", "alpha")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    shows = out["results"][0]["shows"]
    # Both live linked shows come back, ordered by (show.name ASC, show.id ASC).
    show_ids = [e["id"] for e in shows]
    assert show_ids == [alpha, bravo], (
        f"expected both linked shows in name-ascending order; got {show_ids!r}"
    )
    # matched_filter differs per entry: the one whose name contains
    # "alpha" is True, the other is False.
    by_id = {e["id"]: e["matched_filter"] for e in shows}
    assert by_id[alpha] is True
    assert by_id[bravo] is False


def test_media_urls_sorted_deduped_play_history_only(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
) -> None:
    """``media_urls`` is sourced from ``play_history`` only (not
    ``rel_show_song.media_url``), deduplicated, and sorted lexically.

    Seeds one song linked to one show via ``rel_show_song`` with its
    own ``rel_show_song.media_url`` pointing at a URL that is *never*
    inserted into ``play_history``. Then seeds two duplicate
    ``play_history`` rows on the same ``(show_id, song_id)`` pair plus
    one distinct URL. Asserts:
      * ``rel_show_song.media_url`` does not appear in ``media_urls``
        (R-SE-3.8: play_history only).
      * The duplicate ``play_history`` URL appears exactly once
        (dedup).
      * The two distinct URLs come back in lexical order (sort).

    Validates: R-SE-3.8.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    shid = insert_show(tmp_app_root, name="TheShow")

    # rel_show_song carries a URL that never shows up in play_history.
    rel_only_url = "http://rel-only.example.test/should-not-appear"
    insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url=rel_only_url)

    # Two duplicate play_history rows on the same pair — dedup target.
    dup_url = "http://play.example.test/b-dup"
    insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url=dup_url)
    insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url=dup_url)
    # A second distinct URL; lexically sorts before ``dup_url`` so the
    # "sorted" assertion is meaningful (not accidentally insertion order).
    other_url = "http://play.example.test/a-other"
    insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url=other_url)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    shows = out["results"][0]["shows"]
    assert len(shows) == 1
    media_urls = shows[0]["media_urls"]

    # play_history only: rel_show_song.media_url must not leak in.
    assert rel_only_url not in media_urls
    # Dedup + sort: exactly the two distinct play_history URLs in order.
    assert media_urls == [other_url, dup_url]


def test_result_order_is_song_name_then_id(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """Results are ordered by ``(song.name ASC, song.id ASC)``; with
    identical names the tie-breaker is ``song.id`` ascending.

    Seeds three songs that share the exact same ``name`` ("Clash") and
    deliberately chosen ids whose lexical sort order is known
    ("id-a-…", "id-b-…", "id-c-…"). Inserts them in a non-sorted order
    to make sure the test isn't accidentally asserting insertion order.

    The ``insert_song`` fixture accepts an explicit ``id`` kwarg — see
    ``tests/integration/conftest.py :: _insert_song`` — so the ids are
    deterministic.

    Validates: R-SE-3.10.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    # UUIDv4 format so the schema is happy; distinct leading hex char
    # (a/b/c) picks a deterministic lexical order.
    id_a = "aaaaaaaa-0000-4000-8000-000000000001"
    id_b = "bbbbbbbb-0000-4000-8000-000000000002"
    id_c = "cccccccc-0000-4000-8000-000000000003"

    # Insert out of order — if the op returned insertion order the
    # assertion below would fail.
    insert_song(tmp_app_root, id=id_c, name="Clash", artist_id=aid)
    insert_song(tmp_app_root, id=id_a, name="Clash", artist_id=aid)
    insert_song(tmp_app_root, id=id_b, name="Clash", artist_id=aid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 3
    returned_ids = [r["song"]["id"] for r in out["results"]]
    assert returned_ids == [id_a, id_b, id_c]


def test_filters_echo_is_decoded_value_or_null(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """``filters`` echoes the URL-decoded value for each Active filter
    and ``null`` for each Inactive filter.

    Seeds one live song so the run exits 0 with a non-empty result set
    (the exact song returned is not what's being tested — the filter
    echo is). Passes ``--song-term`` with a URL-encoded value that
    ``urllib.parse.unquote`` decodes to ``hello world`` and leaves the
    other two flags Inactive. Asserts:
      * ``filters.song_term == "hello world"`` (decoded exactly once).
      * ``filters.show_term is None`` and ``filters.artist_term is None``.

    Validates: R-SE-4.2.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    # Seed a song whose name contains the decoded term so the run is
    # realistic; not strictly required for the echo assertion.
    insert_song(tmp_app_root, name="hello world track", artist_id=aid)

    rc, out, _err = _run(
        call_script,
        tmp_app_root,
        "search-songs",
        "--song-term",
        "hello%20world",
    )
    assert rc == 0
    assert out is not None

    # Active filter is echoed as the decoded string verbatim; the two
    # Inactive filters are JSON null (None in Python).
    assert out["filters"]["song_term"] == "hello world"
    assert out["filters"]["show_term"] is None
    assert out["filters"]["artist_term"] is None


def test_count_equals_len_results(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """Trivial invariant: ``envelope.count == len(envelope.results)``.

    Seeds a handful of live songs and runs with zero filters. The
    invariant is pinned by R-SE-4.3 so callers can trust ``count``
    without parsing the full array.

    Validates: R-SE-4.3.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    for name in ("Alpha", "Bravo", "Charlie", "Delta"):
        insert_song(tmp_app_root, name=name, artist_id=aid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == len(out["results"])
    # Also pin the concrete value so a silent drop-everything regression
    # doesn't pass the pure-invariant check.
    assert out["count"] == 4


# ---------------------------------------------------------------------------
# Learning / graduated / warnings (R-SE-3.6, R-SE-3.7, R-SE-3.11, R-SE-3.12)
# ---------------------------------------------------------------------------


def test_learning_summary_shape_and_display_level(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """``learning`` is a Learning_Summary with pinned key order and
    ``display_level == int(level) + 1``.

    Seeds one live song with exactly one active (``graduated=0``)
    learning row at ``level=0``. Runs ``search-songs`` with zero
    filters, parses stdout with ``object_pairs_hook=list`` so the
    Learning_Summary key order is compared against the JSON byte
    layout (same pattern as test 1.2 / test 2.1), and asserts:
      * Key order is exactly
        ``[id, level, display_level, graduated, last_level_up_at,
        updated_at]`` (R-SE-3.6 data-model block).
      * ``display_level == 1`` (parent R17: ``int(level) + 1``).
      * ``graduated`` on the embedded summary is ``0`` by
        construction (active rows only — R-SE-3.6).

    Validates: R-SE-3.6, R-SE-3.7.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=0, graduated=0)

    rc, out, err = call_script("query.py", "search-songs", cwd=tmp_app_root)
    assert rc == 0, f"expected exit 0, got rc={rc}, stderr={err!r}"
    assert out, "expected non-empty stdout"

    # Walk into results[0]["learning"] preserving JSON key order.
    pairs = json.loads(out, object_pairs_hook=list)
    envelope = dict(pairs)
    results = envelope["results"]
    assert len(results) == 1

    result_obj = dict(results[0])
    learning_pairs = result_obj["learning"]
    assert isinstance(learning_pairs, list), (
        "learning must be a JSON object (list-of-pairs under object_pairs_hook=list)"
    )
    learning_keys = [k for k, _v in learning_pairs]
    assert learning_keys == [
        "id",
        "level",
        "display_level",
        "graduated",
        "last_level_up_at",
        "updated_at",
    ], f"Learning_Summary key order mismatch; got {learning_keys!r}"

    # Value-level checks via a regular dict parse.
    parsed = json.loads(out)
    learning = parsed["results"][0]["learning"]
    assert learning["level"] == 0
    assert learning["display_level"] == 1
    # Active summary: the embedded ``graduated`` is always 0 (R-SE-3.6).
    assert learning["graduated"] == 0


def test_learning_summary_picks_highest_updated_at_among_active(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """With two active learning rows, the Learning_Summary is taken
    from the one with the highest ``updated_at``.

    Seeds two active (``graduated=0``) rows on one song with distinct
    ``updated_at`` values so the "newer wins" rule is unambiguous
    (R-SE-3.6). The test only asserts which row is chosen — the
    ``duplicate_active_learning`` warning that naturally accompanies
    this state is covered by a later test.

    Validates: R-SE-3.6.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)

    # Older active row: updated_at well before the newer one.
    older_id = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=2,
        graduated=0,
        updated_at=1_700_000_000,
    )
    # Newer active row: strictly greater updated_at. Pinned to exact
    # integers so there's no clock ambiguity (R-SE-3.6 tie-break is
    # on ``updated_at``, then ``id ASC``).
    newer_id = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=5,
        graduated=0,
        updated_at=1_700_000_999,
    )

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    learning = out["results"][0]["learning"]
    assert learning is not None
    # The newer row wins — regardless of which id is lexicographically
    # smaller, the updated_at tie-break is the primary key.
    assert learning["id"] == newer_id
    assert learning["id"] != older_id
    # Also pin the level so a silent "wrong row returned" regression
    # fails the assertion.
    assert learning["level"] == 5
    assert learning["display_level"] == 6


def test_learning_null_when_only_graduated_rows_exist(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """A song whose only learning row is graduated has
    ``learning is None`` and ``graduated is True``.

    Per R-SE-3.6 the embedded Learning_Summary is taken from the
    song's active (un-graduated) row; when no such row exists,
    ``learning`` is JSON null. The sibling ``graduated`` flag picks
    up the graduated state (R-SE-3.11).

    Validates: R-SE-3.6, R-SE-3.11.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=0, graduated=1)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    row = out["results"][0]
    assert row["song"]["id"] == sid
    assert row["learning"] is None
    assert row["graduated"] is True


def test_learning_null_when_no_learning_row(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """A song with no learning rows at all has ``learning is None``
    and ``graduated is False``.

    This is the "never added to learning" baseline. Pins R-SE-3.11's
    rule that ``graduated`` defaults to ``false`` (never ``null``,
    never omitted) when the song has no learning rows.

    Validates: R-SE-3.6, R-SE-3.11.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    row = out["results"][0]
    assert row["song"]["id"] == sid
    assert row["learning"] is None
    assert row["graduated"] is False


def test_graduated_flag_true_when_any_graduated_row(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """``graduated`` is ``True`` when any learning row for the song
    has ``graduated = 1``, regardless of whether an active row also
    exists.

    Seeds one graduated row and one active row on the same song
    (the re-learn pattern from parent R6.3); R-SE-3.11 explicitly
    pins ``graduated`` to true in this case.

    Validates: R-SE-3.11.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=10, graduated=1)
    insert_learning(tmp_app_root, song_id=sid, level=0, graduated=0)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    assert out["results"][0]["graduated"] is True


def test_graduated_flag_false_when_no_learning_row(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
) -> None:
    """``graduated`` is ``False`` when the song has no learning
    rows at all.

    Overlaps in setup with ``test_learning_null_when_no_learning_row``
    but narrows the assertion to the ``graduated`` flag alone so the
    R-SE-3.11 "never null, never omitted, defaults to false" contract
    is pinned independently.

    Validates: R-SE-3.11.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    insert_song(tmp_app_root, name="OnlySong", artist_id=aid)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    row = out["results"][0]
    # Pin the concrete value AND the type — a silent drift to ``None``
    # or to a truthy int would fail the ``is False`` identity check.
    assert row["graduated"] is False
    assert isinstance(row["graduated"], bool)


def test_graduated_flag_and_active_learning_coexist(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Re-learn flow: a song with one graduated row + one active row
    returns ``learning`` as the active row's summary and ``graduated``
    as ``True``.

    Parent R6.3's re-learn pattern inserts a new active row after a
    song has already been graduated once. R-SE-3.11 pins that the two
    fields are independent: ``learning`` always tracks the active
    row, ``graduated`` always reflects "at least one graduated row".

    Validates: R-SE-3.6, R-SE-3.11.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    # The old run, graduated.
    insert_learning(tmp_app_root, song_id=sid, level=19, graduated=1)
    # The new run, active.
    active_id = insert_learning(tmp_app_root, song_id=sid, level=0, graduated=0)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    row = out["results"][0]
    # learning comes from the active row, not the graduated one.
    assert row["learning"] is not None
    assert row["learning"]["id"] == active_id
    assert row["learning"]["level"] == 0
    # The embedded summary's graduated flag is 0 (active row).
    assert row["learning"]["graduated"] == 0
    # But the sibling ``graduated`` flag reflects the old graduated row.
    assert row["graduated"] is True


def test_warnings_empty_when_no_glitch(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """A song with exactly one active learning row has
    ``warnings == []`` — no glitch, no warning.

    Pins the happy path for R-SE-3.12: warnings is always present
    and is an empty array when there is nothing to report.

    Validates: R-SE-3.12.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=0, graduated=0)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    row = out["results"][0]
    assert row["warnings"] == []
    # Always-present invariant.
    assert isinstance(row["warnings"], list)


def test_duplicate_active_learning_emits_one_warning(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Two or more active rows on one song produce exactly one
    ``duplicate_active_learning`` Warning.

    Seeds two active rows, runs, asserts ``warnings`` has exactly one
    entry whose ``code`` is ``"duplicate_active_learning"`` and whose
    key set is exactly ``{"code", "message"}`` (R-SE-3.12).

    Then adds a third active row and re-runs. P-SE-9.2 / R-SE-3.12
    both pin that the op emits at most one Warning per song regardless
    of how many extra active rows exist — the warning is a
    clean-up signal, not a per-row incident report — so the second
    run SHALL also have exactly one warning.

    Validates: R-SE-3.12.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=0, graduated=0, updated_at=1_700_000_001)
    insert_learning(tmp_app_root, song_id=sid, level=2, graduated=0, updated_at=1_700_000_002)

    # First run: two active rows → exactly one warning.
    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    warnings = out["results"][0]["warnings"]
    assert isinstance(warnings, list)
    assert len(warnings) == 1, f"expected exactly 1 warning, got {warnings!r}"
    entry = warnings[0]
    assert entry["code"] == "duplicate_active_learning"
    assert set(entry.keys()) == {"code", "message"}, (
        f"warning entry key set mismatch; got {set(entry.keys())!r}"
    )

    # Add a third active row; second run still has exactly one warning.
    insert_learning(tmp_app_root, song_id=sid, level=4, graduated=0, updated_at=1_700_000_003)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    warnings = out["results"][0]["warnings"]
    assert len(warnings) == 1, (
        f"expected exactly 1 warning even with 3 active rows, got {warnings!r}"
    )
    assert warnings[0]["code"] == "duplicate_active_learning"
    assert set(warnings[0].keys()) == {"code", "message"}


def test_warning_does_not_change_exit_code_or_count(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
    temp_conn,
) -> None:
    """A ``duplicate_active_learning`` warning is advisory — it does
    not change the exit code, the envelope ``count``, or any other
    Song_Search_Result field.

    Seeds a song with two active learning rows (the glitch state),
    runs once, then deletes the extra active row via direct DB
    access on the ``temp_conn`` fixture and runs a second time.
    Asserts:
      * Both runs exit 0.
      * Envelope ``count`` is identical across the two runs.
      * Every Song_Search_Result field except ``warnings`` is
        byte-identical between the two runs for the shared song
        (compared with ``warnings`` dropped from each result).

    Validates: R-SE-3.12.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    # Newer active row — the one that wins the Learning_Summary pick
    # (R-SE-3.6 tie-break: highest ``updated_at``). Kept across both runs.
    keeper_id = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=3,
        graduated=0,
        updated_at=1_700_000_999,
    )
    # Stale extra active row — the glitch. Deleted before the second run.
    extra_id = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=1,
        graduated=0,
        updated_at=1_700_000_001,
    )

    # First run: glitch present → exactly one warning.
    rc1, out1, err1 = call_script("query.py", "search-songs", cwd=tmp_app_root)
    assert rc1 == 0, f"first run failed: rc={rc1}, stderr={err1!r}"
    assert out1, "expected non-empty stdout on first run"
    parsed1 = json.loads(out1)
    assert parsed1["count"] == 1
    assert len(parsed1["results"][0]["warnings"]) == 1

    # Delete the extra active row so the glitch is gone. Use the
    # temp_conn fixture — it points at the same DB file under
    # ``tmp_app_root/db/datasource.db`` that ``call_script`` operates
    # on, matching how property tests reconcile state between script
    # invocations (e.g. ``tests/integration/property/test_cleanup_property.py``).
    temp_conn.execute("DELETE FROM learning WHERE id = ?", (extra_id,))
    temp_conn.commit()

    # Second run: no glitch → no warning.
    rc2, out2, err2 = call_script("query.py", "search-songs", cwd=tmp_app_root)
    assert rc2 == 0, f"second run failed: rc={rc2}, stderr={err2!r}"
    assert out2, "expected non-empty stdout on second run"
    parsed2 = json.loads(out2)

    # Exit code unchanged.
    assert rc1 == rc2 == 0

    # Envelope count unchanged — the warning never affects the result
    # set size (R-SE-3.12: advisory, never changes ``count``).
    assert parsed1["count"] == parsed2["count"]

    # Every non-``warnings`` field on the shared Song_Search_Result is
    # byte-identical across the two runs. Compare at the dict-minus-key
    # level so the assertion message surfaces the differing field
    # clearly if it ever drifts.
    row1 = {k: v for k, v in parsed1["results"][0].items() if k != "warnings"}
    row2 = {k: v for k, v in parsed2["results"][0].items() if k != "warnings"}
    assert row1 == row2, f"non-warnings fields drifted between runs: run1={row1!r}, run2={row2!r}"

    # The winner summary (R-SE-3.6 tie-break) is the same row in both
    # runs; sanity-check that the keeper — not the deleted extra — is
    # what ``learning`` reflects before and after the delete.
    assert parsed1["results"][0]["learning"]["id"] == keeper_id
    assert parsed2["results"][0]["learning"]["id"] == keeper_id

    # And the warnings field itself differs as expected.
    assert parsed2["results"][0]["warnings"] == []


def test_warning_code_is_exact_string(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """The warning ``code`` is the literal string
    ``"duplicate_active_learning"``.

    R-SE-3.12 pins the code value as the stable machine-readable
    contract — the message wording MAY evolve in later specs but the
    code SHALL NOT be renamed. This test locks the literal.

    Validates: R-SE-3.12.
    """
    aid = insert_artist(tmp_app_root, name="Soloist")
    sid = insert_song(tmp_app_root, name="OnlySong", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=0, graduated=0, updated_at=1_700_000_001)
    insert_learning(tmp_app_root, song_id=sid, level=1, graduated=0, updated_at=1_700_000_002)

    rc, out, _err = _run(call_script, tmp_app_root, "search-songs")
    assert rc == 0
    assert out is not None
    assert out["count"] == 1

    warnings = out["results"][0]["warnings"]
    assert len(warnings) == 1
    # Literal-string equality — not a substring match, not a startswith,
    # not an ``in`` check.
    assert warnings[0]["code"] == "duplicate_active_learning"


# ---------------------------------------------------------------------------
# Validation and argparse error paths (R-SE-1.6, R-SE-1.8, R-SE-4.6)
# ---------------------------------------------------------------------------


def test_over_length_term_returns_invalid_input(
    tmp_app_root,
    call_script,
) -> None:
    """A Filter_Term whose decoded value exceeds 1024 UTF-8 bytes is
    rejected with ``INVALID_INPUT`` before the DB is touched.

    R-SE-1.6 caps any Active Filter_Term at 1024 UTF-8 bytes after
    URL-decoding; the Script must emit an Error_Envelope and exit 1
    without scanning the library. Passes ``--song-term`` with 1100
    ASCII "a" characters — strictly over the cap, with a known byte
    count so a silent cap drift would still be caught. Asserts:
      * Exit 1 (parent R3.7 handled-failure path).
      * Stdout is empty (R-SE-4.6: no partial Success_Envelope on a
        handled failure).
      * Stderr is a valid JSON Error_Envelope with
        ``error.code == "INVALID_INPUT"``.
      * ``error.details.flag == "--song-term"`` and
        ``error.details.max_bytes == 1024`` so callers can react
        programmatically to the cap violation.

    No DB seeding is required: the validation runs before the DB scan
    (R-SE-1.6), so the op fails the same way on an empty and a
    populated library. Uses ``call_script`` directly so stdout and
    stderr are asserted as raw strings.

    Validates: R-SE-1.6, R-SE-4.6.
    """
    over_length = "a" * 1100
    # Sanity-check the fixture: this is >1024 bytes by construction.
    assert len(over_length.encode("utf-8")) > 1024

    rc, out, err = call_script(
        "query.py",
        "search-songs",
        "--song-term",
        over_length,
        cwd=tmp_app_root,
    )

    # Handled-failure path: exit 1, empty stdout, Error_Envelope on stderr.
    assert rc == 1, f"expected exit 1 on over-length term, got rc={rc}"
    assert out == "", f"expected empty stdout on handled failure, got {out!r}"
    assert err.strip(), "expected non-empty stderr with Error_Envelope"

    envelope = json.loads(err)
    assert envelope["error"]["code"] == "INVALID_INPUT", (
        f"expected INVALID_INPUT, got {envelope['error']['code']!r}"
    )
    details = envelope["error"]["details"]
    assert details["flag"] == "--song-term", (
        f"expected details.flag == '--song-term', got {details.get('flag')!r}"
    )
    assert details["max_bytes"] == 1024, (
        f"expected details.max_bytes == 1024, got {details.get('max_bytes')!r}"
    )


def test_unknown_flag_exits_2(
    tmp_app_root,
    call_script,
) -> None:
    """An unknown flag falls through to argparse's standard error path:
    exit 2, usage banner on stderr, no JSON on stdout.

    R-SE-1.8 pins ``search-songs`` to argparse's default ``SystemExit(2)``
    behavior for any flag or positional argument outside
    ``{--song-term, --show-term, --artist-term, -h, --help}``. This is
    the same behavior every other ``query.py`` subcommand has; the test
    asserts the Script does not introduce custom handling. Asserts:
      * Exit 2 (argparse's standard error exit).
      * Stdout is exactly empty — no Success_Envelope, no partial JSON.
      * Stderr contains argparse's ``usage:`` banner (argparse writes
        usage on stderr before the "unrecognized arguments" line).

    Uses ``call_script`` directly so the raw stderr string is available
    for the substring check.

    Validates: R-SE-1.8.
    """
    rc, out, err = call_script(
        "query.py",
        "search-songs",
        "--foo",
        "bar",
        cwd=tmp_app_root,
    )

    assert rc == 2, f"expected argparse exit 2 on unknown flag, got rc={rc}"
    assert out == "", f"expected empty stdout, got {out!r}"
    assert "usage:" in err, f"expected argparse 'usage:' banner on stderr, got {err!r}"


# ---------------------------------------------------------------------------
# Read-only sanity (parent R18, R-SE-1.2)
# ---------------------------------------------------------------------------


def test_query_py_does_not_modify_temp_db_on_search_songs(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
) -> None:
    """A sweep of ``search-songs`` calls leaves the temp DB byte-identical.

    ``query.py`` is a read-only op — parent R18 pins the guarantee and
    R-SE-1.2 demands the new ``search-songs`` subcommand inherits it
    (nothing about the new surface may introduce a write path). Seeds
    a small library so every sweep invocation has actual rows to scan
    (otherwise a query that silently no-ops on an empty DB would pass
    trivially), then runs every legal filter combination and diffs the
    raw ``datasource.db`` bytes before and after.

    Sweep shape:
      1. Zero filters (Zero_Filter_Behavior).
      2. ``--song-term`` alone.
      3. ``--show-term`` alone.
      4. ``--artist-term`` alone.
      5. All three filters together. Terms picked to match the seeded
         library so at least this run returns a non-empty result set —
         a read-only guarantee that only exercises no-hit paths is
         weaker than one that also exercises the full assembly path.

    Uses the same byte-comparison approach
    ``test_query_py_does_not_modify_the_temp_db`` in
    ``tests/integration/test_query.py`` uses — read the whole
    ``tmp_app_root/db/datasource.db`` file before and after, assert
    equal. The session-scoped ``_guard_real_db`` fixture in
    ``tests/conftest.py`` already catches any write to the *real* DB;
    this test complements it by catching writes to the *temp* DB the
    new subcommand operates on.

    Validates: parent R18 (read-only guarantee), R-SE-1.2.
    """
    # Seed one of every related entity so the sweep has actual rows to
    # scan. Names are chosen so the "all three filters" invocation
    # returns a non-empty result set: "Song" matches the song name,
    # "Show" matches the show name, "Artist" matches the artist name.
    aid = insert_artist(tmp_app_root, name="Watcher Artist")
    sid = insert_song(tmp_app_root, name="Watcher Song", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Watcher Show")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid)
    insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url="http://m/watcher")

    db_file = tmp_app_root / "db" / "datasource.db"
    before_bytes = db_file.read_bytes()

    # Sweep of legal filter combinations. Every invocation must exit 0
    # — a failed call could mask a write (e.g. an exception after a
    # stray commit would still exit non-zero but leave the DB dirty).
    sweeps = (
        ("search-songs",),
        ("search-songs", "--song-term", "Song"),
        ("search-songs", "--show-term", "Show"),
        ("search-songs", "--artist-term", "Artist"),
        ("search-songs", "--song-term", "Song", "--show-term", "Show", "--artist-term", "Artist"),
    )
    for args in sweeps:
        rc, _out, _err = call_script("query.py", *args, cwd=tmp_app_root)
        assert rc == 0, f"expected exit 0 for args={args!r}, got rc={rc}"

    after_bytes = db_file.read_bytes()
    assert before_bytes == after_bytes, (
        "search-songs must not modify the DB; the temp datasource.db "
        "bytes differ before vs after the sweep"
    )
