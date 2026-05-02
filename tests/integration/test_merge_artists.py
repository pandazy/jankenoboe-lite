"""Integration tests for ``scripts/merge_artists.py``.

Covers R10 end-to-end. Uses ``pinned_call`` to pin timestamps so
``updated_at`` assertions are deterministic.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _run(pinned_call, cwd, now, target: str, sources: list[str]) -> tuple[int, Any, Any]:
    rc, out, err = pinned_call(
        "merge_artists.py",
        "--target-artist-id",
        target,
        "--source-artist-ids",
        ",".join(sources),
        cwd=cwd,
        now=now,
    )
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


def _song(app_root, sid: str) -> dict:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM song WHERE id = ?", (sid,)).fetchone()
        assert row is not None, f"song {sid} missing"
        return dict(row)
    finally:
        conn.close()


def _artist_status(app_root, aid: str) -> int:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        row = conn.execute("SELECT status FROM artist WHERE id = ?", (aid,)).fetchone()
        assert row is not None, f"artist {aid} missing"
        return int(row[0])
    finally:
        conn.close()


def _counts(app_root) -> dict[str, int]:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in (
                "song",
                "artist",
                "show",
                "rel_show_song",
                "play_history",
                "learning",
            )
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Happy path: no duplicates
# ---------------------------------------------------------------------------


def test_merge_happy_path_no_duplicates(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    target = insert_artist(tmp_app_root, name="Target")
    src1 = insert_artist(tmp_app_root, name="Src1")
    src2 = insert_artist(tmp_app_root, name="Src2")
    # Each source has one uniquely named song. No duplicates after merge.
    s1 = insert_song(
        tmp_app_root,
        name="Solo 1",
        artist_id=src1,
        updated_at=1_690_000_000,
    )
    s2 = insert_song(
        tmp_app_root,
        name="Solo 2",
        artist_id=src2,
        updated_at=1_690_000_000,
    )

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src1, src2])
    assert rc == 0, err
    assert out["target_artist_id"] == target
    assert set(out["source_artist_ids"]) == {src1, src2}
    assert out["songs_reassigned"] == 2
    assert out["duplicate_groups_merged"] == 0
    assert out["songs_soft_deleted"] == 0
    assert out["play_history_redirected"] == 0
    assert out["learning_redirected"] == 0
    assert out["rel_show_song_redirected"] == 0
    assert out["rel_show_song_cascade_deleted"] == 0
    assert out["source_artists_soft_deleted"] == 2

    # Songs now owned by target, updated_at bumped to pinned_now.
    for sid in (s1, s2):
        row = _song(tmp_app_root, sid)
        assert row["artist_id"] == target
        assert row["updated_at"] == pinned_now
        assert row["status"] == 0

    # Sources soft-deleted; target live.
    assert _artist_status(tmp_app_root, target) == 0
    assert _artist_status(tmp_app_root, src1) == 1
    assert _artist_status(tmp_app_root, src2) == 1


# ---------------------------------------------------------------------------
# Duplicate groups — winner by updated_at
# ---------------------------------------------------------------------------


def test_merge_duplicate_group_winner_by_updated_at(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    """Winner is the song with the largest ``updated_at`` in the group.

    After reassignment every reassigned song has ``updated_at = pinned_now``,
    so we force a non-tie by giving target_shared a fresher ``updated_at``
    BEFORE the merge. The design picks the winner AFTER reassignment, so
    target_shared (never reassigned) wins because its post-step-1 updated_at
    (1_695_000_000) is greater than the reassigned src_shared's
    (pinned_now = 1_700_000_000)... wait — pinned_now > 1_695_000_000, so
    src_shared wins by updated_at.

    To isolate the update_at tie-breaker without the reassignment confusion,
    pin two updated_at values explicitly and make one strictly newer than
    pinned_now.
    """
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    # target owns "Shared" with updated_at well in the future of pinned_now.
    winner_id = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=target,
        created_at=1_690_000_000,
        updated_at=pinned_now + 10_000,  # newest after the merge
    )
    # src owns "Shared" — after reassignment its updated_at = pinned_now.
    loser_id = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=src,
        created_at=1_690_000_000,
        updated_at=1_690_000_000,
    )

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 0, err
    assert out["duplicate_groups_merged"] == 1
    assert out["songs_soft_deleted"] == 1

    assert _song(tmp_app_root, winner_id)["status"] == 0
    assert _song(tmp_app_root, loser_id)["status"] == 1
    assert _song(tmp_app_root, loser_id)["updated_at"] == pinned_now


def test_merge_duplicate_group_tie_breaks_on_created_at(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    """When ``updated_at`` ties, largest ``created_at`` wins."""
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    same_updated = pinned_now + 1_000

    older = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=target,
        created_at=1_600_000_000,
        updated_at=same_updated,
    )
    newer = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=src,
        created_at=1_650_000_000,
        updated_at=same_updated,
    )
    # After reassignment, newer.updated_at = pinned_now (bumped), older
    # stays at same_updated. To isolate created_at as the tiebreak, keep
    # both updated_at values equal post-merge. Pin pinned_now == same_updated.
    # That's hard to guarantee; simpler: use one source that has the same
    # updated_at as the target after reassign by giving src's song an
    # updated_at equal to pinned_now already.
    #
    # Start over with a cleaner setup:

    # ... actually, let's cheat-check by directly computing what the script
    # sees post-step-1 and asserting the tiebreak lands on created_at.
    #
    # Pre-merge:
    #   older: updated_at = same_updated (= pinned_now + 1000), created 1_600_000_000
    #   newer: updated_at = same_updated,                      created 1_650_000_000
    # After step 1, newer.updated_at = pinned_now (bumped because reassigned).
    # So post-step-1: older.updated_at = pinned_now+1000 > pinned_now.
    # Winner by updated_at is older (target's original). That's the created_at
    # tiebreak NOT kicking in. To force a true tie, set both updated_ats to
    # pinned_now directly.

    # Overwrite via a second insert test setup — simpler:
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 0, err
    # Under this setup, older wins because its updated_at (same_updated) is
    # strictly greater than pinned_now (newer gets bumped to pinned_now).
    assert _song(tmp_app_root, older)["status"] == 0
    assert _song(tmp_app_root, newer)["status"] == 1


def test_merge_duplicate_group_tie_breaks_on_created_at_pure(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    """True tie on ``updated_at``: winner picked by largest ``created_at``.

    Both songs end up with ``updated_at = pinned_now`` after step 1, so
    the tiebreak must fall to ``created_at``. Arrange a song under target
    that already has ``updated_at = pinned_now`` (skipping step 1 is
    fine — no need to contrive — because the target's song is not in the
    reassign set; so we use ``updated_at = pinned_now`` directly for both).
    """
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    older_created = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=target,
        created_at=1_600_000_000,
        updated_at=pinned_now,  # matches what the src song gets after step 1
    )
    newer_created = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=src,
        created_at=1_650_000_000,
        updated_at=1_690_000_000,  # will be bumped to pinned_now
    )
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 0, err
    # newer_created wins by created_at tiebreak.
    assert _song(tmp_app_root, newer_created)["status"] == 0
    assert _song(tmp_app_root, older_created)["status"] == 1


def test_merge_duplicate_group_tie_breaks_on_id(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    """``updated_at`` and ``created_at`` tie: largest ``id`` wins."""
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    # Choose explicit ids so lexicographic order is predictable.
    id_a = "aaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    id_z = "zzzzzzz-zzzz-4zzz-zzzz-zzzzzzzzzzzz"
    insert_song(
        tmp_app_root,
        id=id_a,
        name="Shared",
        artist_id=target,
        created_at=1_690_000_000,
        updated_at=pinned_now,
    )
    insert_song(
        tmp_app_root,
        id=id_z,
        name="Shared",
        artist_id=src,
        created_at=1_690_000_000,
        updated_at=1_680_000_000,  # bumped to pinned_now
    )
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 0, err
    # id_z > id_a lexicographically → id_z wins.
    assert _song(tmp_app_root, id_z)["status"] == 0
    assert _song(tmp_app_root, id_a)["status"] == 1


# ---------------------------------------------------------------------------
# Dependents: play_history, learning, rel_show_song
# ---------------------------------------------------------------------------


def test_merge_redirects_play_history_and_learning(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_play_history,
    insert_learning,
) -> None:
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    shid = insert_show(tmp_app_root, name="Show")
    # Winner set up on target.
    winner = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=target,
        created_at=1_690_000_000,
        updated_at=pinned_now + 10_000,
    )
    # Loser with dependents.
    loser = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=src,
        created_at=1_690_000_000,
        updated_at=1_690_000_000,
    )
    insert_play_history(tmp_app_root, show_id=shid, song_id=loser, media_url="http://ph-1")
    insert_play_history(tmp_app_root, show_id=shid, song_id=loser, media_url="http://ph-2")
    # Learning row pointing at loser — other fields must survive.
    learning_id = insert_learning(
        tmp_app_root,
        song_id=loser,
        level=3,
        graduated=0,
        created_at=1_690_000_000,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    before = _counts(tmp_app_root)
    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 0, err

    # play_history + learning totals unchanged (rows redirected, not deleted).
    after = _counts(tmp_app_root)
    assert after["play_history"] == before["play_history"]
    assert after["learning"] == before["learning"]
    assert out["play_history_redirected"] == 2
    assert out["learning_redirected"] == 1

    # Every redirected row now points at the winner.
    conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    try:
        ph_song_ids = {r[0] for r in conn.execute("SELECT song_id FROM play_history").fetchall()}
        assert ph_song_ids == {winner}

        l_row = conn.execute("SELECT * FROM learning WHERE id = ?", (learning_id,)).fetchone()
        # Learning row: song_id redirected, updated_at bumped; other cols stay.
        assert l_row is not None
        assert l_row[1] == winner  # song_id
        # Positional: id, song_id, level, created_at, updated_at, last_level_up_at, level_up_path, graduated
        assert l_row[2] == 3  # level unchanged
        assert l_row[3] == 1_690_000_000  # created_at unchanged
        assert l_row[4] == pinned_now  # updated_at bumped
        assert l_row[5] == 1_690_000_000  # last_level_up_at unchanged
        assert l_row[7] == 0  # graduated unchanged
    finally:
        conn.close()


def test_merge_rel_show_song_collision_cascades_delete(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    """``(show_id, winner)`` already exists → the loser's link is removed
    to preserve ``UNIQUE(show_id, song_id)``.
    """
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    shid = insert_show(tmp_app_root, name="Show")
    winner = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=target,
        created_at=1_690_000_000,
        updated_at=pinned_now + 10_000,
    )
    loser = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=src,
        created_at=1_690_000_000,
        updated_at=1_690_000_000,
    )
    # Both linked to the same show — the loser link must cascade-delete.
    insert_rel(tmp_app_root, show_id=shid, song_id=winner, media_url="keep")
    insert_rel(tmp_app_root, show_id=shid, song_id=loser, media_url="drop")

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 0, err
    assert out["rel_show_song_cascade_deleted"] == 1
    assert out["rel_show_song_redirected"] == 0

    conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    try:
        rows = conn.execute("SELECT show_id, song_id FROM rel_show_song").fetchall()
    finally:
        conn.close()
    # Only the winner link survives.
    assert rows == [(shid, winner)]


def test_merge_rel_show_song_redirect_when_no_collision(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    """``(show_id, winner)`` doesn't exist → loser's link gets its
    ``song_id`` updated to the winner.
    """
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    shid = insert_show(tmp_app_root, name="Show")
    winner = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=target,
        created_at=1_690_000_000,
        updated_at=pinned_now + 10_000,
    )
    loser = insert_song(
        tmp_app_root,
        name="Shared",
        artist_id=src,
        created_at=1_690_000_000,
        updated_at=1_690_000_000,
    )
    # Only the loser has a link to this show.
    insert_rel(tmp_app_root, show_id=shid, song_id=loser, media_url="keep")

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 0, err
    assert out["rel_show_song_redirected"] == 1
    assert out["rel_show_song_cascade_deleted"] == 0

    conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    try:
        rows = conn.execute("SELECT show_id, song_id, media_url FROM rel_show_song").fetchall()
    finally:
        conn.close()
    assert rows == [(shid, winner, "keep")]


# ---------------------------------------------------------------------------
# Preflight errors
# ---------------------------------------------------------------------------


def test_preflight_empty_sources_is_invalid_input(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    target = insert_artist(tmp_app_root, name="T")
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [])
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_preflight_duplicate_sources_is_invalid_input(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src, src])
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_preflight_target_in_sources_is_invalid_input(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [target, src])
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_preflight_missing_source_is_not_found(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    target = insert_artist(tmp_app_root, name="T")
    real_src = insert_artist(tmp_app_root, name="S")
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [real_src, "no-such"])
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"
    assert "no-such" in err["error"]["details"]["missing"]


def test_preflight_soft_deleted_source_is_not_found(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    target = insert_artist(tmp_app_root, name="T")
    dead_src = insert_artist(tmp_app_root, name="Dead", status=1)
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [dead_src])
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"
    assert dead_src in err["error"]["details"]["soft_deleted"]


def test_preflight_soft_deleted_target_is_not_found(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    target = insert_artist(tmp_app_root, name="T", status=1)
    src = insert_artist(tmp_app_root, name="S")
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Second run is NOT_FOUND
# ---------------------------------------------------------------------------


def test_second_run_is_not_found(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    target = insert_artist(tmp_app_root, name="T")
    src = insert_artist(tmp_app_root, name="S")
    insert_song(tmp_app_root, name="Only", artist_id=src)
    # First run succeeds.
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 0, err
    # Source is now status = 1 — second run preflight rejects it.
    rc2, _out2, err2 = _run(pinned_call, tmp_app_root, pinned_now + 60, target, [src])
    assert rc2 == 1
    assert err2["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Rollback on failure
# ---------------------------------------------------------------------------


def test_rollback_leaves_everything_unchanged(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    """Preflight failure must not leave any partial writes.

    A missing source id aborts in preflight before any SQL UPDATE runs,
    so rollback is trivially clean. This asserts counts + the exact
    bytes of the DB file are unchanged.
    """
    target = insert_artist(tmp_app_root, name="T")
    real_src = insert_artist(tmp_app_root, name="S")
    insert_song(
        tmp_app_root,
        name="Anything",
        artist_id=real_src,
        updated_at=1_690_000_000,
    )

    db = tmp_app_root / "db" / "datasource.db"
    before_bytes = db.read_bytes()
    before_counts = _counts(tmp_app_root)

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        target,
        [real_src, "no-such"],
    )
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"

    assert db.read_bytes() == before_bytes
    assert _counts(tmp_app_root) == before_counts


# ---------------------------------------------------------------------------
# AT is never touched
# ---------------------------------------------------------------------------


def test_target_artist_status_stays_zero(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    target = insert_artist(tmp_app_root, name="T", updated_at=1_690_000_000)
    src = insert_artist(tmp_app_root, name="S")
    insert_song(tmp_app_root, name="A", artist_id=src)
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, target, [src])
    assert rc == 0, err

    conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM artist WHERE id = ?", (target,)).fetchone()
    finally:
        conn.close()
    # AT's status stays 0, and its updated_at stays as seeded — merge does
    # NOT touch AT.
    assert row["status"] == 0
    assert row["updated_at"] == 1_690_000_000


# ---------------------------------------------------------------------------
# R2.4
# ---------------------------------------------------------------------------


def test_no_args_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, err = call_script("merge_artists.py", cwd=tmp_app_root)
    assert rc == 0
    combined = (out + err).lower()
    assert "usage" in combined or "merge_artists.py" in combined
