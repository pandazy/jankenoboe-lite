"""Integration tests for ``scripts/data.py``.

Covers every acceptance criterion under Requirement 9 plus the R15
soft-delete rules. Uses the ``tmp_app_root`` fixture and the ``insert_*``
seeders from ``tests/integration/conftest.py`` — tests never touch the
real ``db/datasource.db``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _run_data(pinned_call, cwd, now, *args) -> tuple[int, Any, Any]:
    """Run ``data.py`` with the clock pinned. Returns ``(rc, out_json, err_json)``."""
    rc, out, err = pinned_call("data.py", *args, cwd=cwd, now=now)
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


def _run_query(call_script, cwd, *args) -> tuple[int, Any, Any]:
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


def _select(app_root, table: str, row_id: str) -> dict:
    """Fetch a row by id. Raises if not found (so mypy knows the return is dict)."""
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert row is not None, f"{table}.{row_id} not found"
        return dict(row)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_artist_round_trip(tmp_app_root, pinned_call, pinned_now, call_script) -> None:
    """R9.1/R9.2: create returns the row with generated id + status=0 + timestamps."""
    payload = {"name": "Yui", "name_context": "solo"}
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "artist",
        "--data",
        json.dumps(payload),
    )
    assert rc == 0, err
    assert out["id"]
    assert out["name"] == "Yui"
    assert out["name_context"] == "solo"
    assert out["created_at"] == pinned_now
    assert out["updated_at"] == pinned_now
    assert out["status"] == 0

    # query.py get sees the same row.
    rc, got, _err = _run_query(
        call_script, tmp_app_root, "get", "--kind", "artist", "--id", out["id"]
    )
    assert rc == 0
    assert got == out


def test_create_song_round_trip(
    tmp_app_root, pinned_call, pinned_now, insert_artist, call_script
) -> None:
    aid = insert_artist(tmp_app_root, name="Yui")
    payload = {"name": "Again", "name_context": "", "artist_id": aid}
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "song",
        "--data",
        json.dumps(payload),
    )
    assert rc == 0, err
    assert out["artist_id"] == aid
    assert out["name"] == "Again"
    assert out["status"] == 0

    rc, got, _err = _run_query(
        call_script, tmp_app_root, "get", "--kind", "song", "--id", out["id"]
    )
    assert rc == 0 and got == out


def test_create_show_round_trip(tmp_app_root, pinned_call, pinned_now, call_script) -> None:
    payload = {
        "name": "FMA: Brotherhood",
        "name_romaji": "Hagane no Renkinjutsushi",
        "vintage": "Spring 2009",
        "s_type": "TV",
    }
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "show",
        "--data",
        json.dumps(payload),
    )
    assert rc == 0, err
    assert out["name"] == "FMA: Brotherhood"
    assert out["vintage"] == "Spring 2009"
    assert out["status"] == 0


def test_create_rel_show_song(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    """R9.3: rel_show_song needs show_id + song_id; created_at auto-set."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Show")
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "rel_show_song",
        "--data",
        json.dumps({"show_id": shid, "song_id": sid, "media_url": "http://x"}),
    )
    assert rc == 0, err
    assert out["show_id"] == shid
    assert out["song_id"] == sid
    assert out["media_url"] == "http://x"
    assert out["created_at"] == pinned_now


def test_create_rel_show_song_duplicate_is_constraint_violation(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    """R9.4: duplicate (show_id, song_id) → CONSTRAINT_VIOLATION."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Show")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="http://first")
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "rel_show_song",
        "--data",
        json.dumps({"show_id": shid, "song_id": sid, "media_url": "http://second"}),
    )
    assert rc == 1
    assert err["error"]["code"] == "CONSTRAINT_VIOLATION"


def test_create_url_decodes_data_once(tmp_app_root, pinned_call, pinned_now) -> None:
    """R4.2: string leaves in --data decode once."""
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "artist",
        "--data",
        json.dumps({"name": "hello%20world", "name_context": "solo%2Bside"}),
    )
    assert rc == 0, err
    assert out["name"] == "hello world"
    assert out["name_context"] == "solo+side"


def test_create_with_invalid_json_is_invalid_input(tmp_app_root, pinned_call, pinned_now) -> None:
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "artist",
        "--data",
        "{not json",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_create_rejects_non_object_data(tmp_app_root, pinned_call, pinned_now) -> None:
    """A JSON array / scalar is valid JSON but not a valid row payload."""
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "artist",
        "--data",
        "[1, 2, 3]",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_create_unknown_column_is_invalid_input(tmp_app_root, pinned_call, pinned_now) -> None:
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "artist",
        "--data",
        json.dumps({"name": "A", "not_a_column": "oops"}),
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_patches_mutable_columns(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    aid = insert_artist(tmp_app_root, name="Old Name", name_context="", updated_at=1_690_000_000)
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "update",
        "--kind",
        "artist",
        "--id",
        aid,
        "--data",
        json.dumps({"name": "New Name", "name_context": "solo"}),
    )
    assert rc == 0, err
    assert out["name"] == "New Name"
    assert out["name_context"] == "solo"
    assert out["updated_at"] == pinned_now


def test_update_rejects_id_change(tmp_app_root, pinned_call, pinned_now, insert_artist) -> None:
    """R9.6: update cannot change id."""
    aid = insert_artist(tmp_app_root, name="A")
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "update",
        "--kind",
        "artist",
        "--id",
        aid,
        "--data",
        json.dumps({"id": "new-id"}),
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_update_rejects_created_at_change(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "update",
        "--kind",
        "artist",
        "--id",
        aid,
        "--data",
        json.dumps({"created_at": 0}),
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_update_rejects_status_change(tmp_app_root, pinned_call, pinned_now, insert_artist) -> None:
    """R15.4: status is only flipped through delete, not update."""
    aid = insert_artist(tmp_app_root, name="A")
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "update",
        "--kind",
        "artist",
        "--id",
        aid,
        "--data",
        json.dumps({"status": 1}),
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_update_missing_target_is_not_found(tmp_app_root, pinned_call, pinned_now) -> None:
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "update",
        "--kind",
        "artist",
        "--id",
        "no-such",
        "--data",
        json.dumps({"name": "X"}),
    )
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_update_soft_deleted_target_is_not_found(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    aid = insert_artist(tmp_app_root, name="Gone", status=1)
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "update",
        "--kind",
        "artist",
        "--id",
        aid,
        "--data",
        json.dumps({"name": "X"}),
    )
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# delete (soft delete + artist cascade)
# ---------------------------------------------------------------------------


def test_delete_song_soft_deletes_and_hides(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, call_script
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid, updated_at=1_690_000_000)
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "delete",
        "--kind",
        "song",
        "--id",
        sid,
    )
    assert rc == 0, err
    assert out["deleted"] is True

    row = _select(tmp_app_root, "song", sid)
    assert row is not None
    assert row["status"] == 1
    assert row["updated_at"] == pinned_now

    # query.py get hides it.
    rc, _out, err_query = _run_query(
        call_script, tmp_app_root, "get", "--kind", "song", "--id", sid
    )
    assert rc == 1
    assert err_query["error"]["code"] == "NOT_FOUND"


def test_delete_song_already_soft_deleted_is_noop(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    """R9.9: already-soft-deleted → success no-op."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid, status=1, updated_at=1_690_000_000)
    rc, out, _err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "delete",
        "--kind",
        "song",
        "--id",
        sid,
    )
    assert rc == 0
    assert out["deleted"] is True
    row = _select(tmp_app_root, "song", sid)
    assert row["updated_at"] == 1_690_000_000  # unchanged


def test_delete_song_missing_is_noop(tmp_app_root, pinned_call, pinned_now) -> None:
    """R9.9: missing → still a success response."""
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "delete",
        "--kind",
        "song",
        "--id",
        "no-such",
    )
    assert rc == 0, err
    assert out["deleted"] is True


def test_delete_show_soft_deletes(tmp_app_root, pinned_call, pinned_now, insert_show) -> None:
    shid = insert_show(tmp_app_root, name="Show", updated_at=1_690_000_000)
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "delete",
        "--kind",
        "show",
        "--id",
        shid,
    )
    assert rc == 0, err
    row = _select(tmp_app_root, "show", shid)
    assert row["status"] == 1
    assert row["updated_at"] == pinned_now


def test_delete_artist_cascades_to_songs(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    """R9.8: deleting an artist soft-deletes every live song it owns first,
    then the artist — all in one transaction."""
    target = insert_artist(tmp_app_root, name="Target", updated_at=1_690_000_000)
    other = insert_artist(tmp_app_root, name="Other", updated_at=1_690_000_000)
    s1 = insert_song(tmp_app_root, name="S1", artist_id=target, updated_at=1_690_000_000)
    s2 = insert_song(tmp_app_root, name="S2", artist_id=target, updated_at=1_690_000_000)
    s3 = insert_song(tmp_app_root, name="S3", artist_id=other, updated_at=1_690_000_000)

    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "delete",
        "--kind",
        "artist",
        "--id",
        target,
    )
    assert rc == 0, err

    # Target's songs soft-deleted with updated_at = pinned_now.
    for sid in (s1, s2):
        row = _select(tmp_app_root, "song", sid)
        assert row["status"] == 1
        assert row["updated_at"] == pinned_now
        assert row["artist_id"] == target  # unchanged

    # Other artist's song untouched.
    row = _select(tmp_app_root, "song", s3)
    assert row["status"] == 0
    assert row["updated_at"] == 1_690_000_000

    # Target artist now soft-deleted; other artist untouched.
    t_row = _select(tmp_app_root, "artist", target)
    o_row = _select(tmp_app_root, "artist", other)
    assert t_row["status"] == 1 and t_row["updated_at"] == pinned_now
    assert o_row["status"] == 0 and o_row["updated_at"] == 1_690_000_000


def test_delete_artist_already_soft_deleted_is_noop(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    aid = insert_artist(tmp_app_root, name="Gone", status=1, updated_at=1_690_000_000)
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "delete",
        "--kind",
        "artist",
        "--id",
        aid,
    )
    assert rc == 0, err
    row = _select(tmp_app_root, "artist", aid)
    assert row["status"] == 1
    assert row["updated_at"] == 1_690_000_000  # not re-stamped


# ---------------------------------------------------------------------------
# bulk-reassign
# ---------------------------------------------------------------------------


def test_bulk_reassign_moves_listed_songs_only(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    src = insert_artist(tmp_app_root, name="Src")
    dst = insert_artist(tmp_app_root, name="Dst")
    s1 = insert_song(tmp_app_root, name="A", artist_id=src, updated_at=1_690_000_000)
    s2 = insert_song(tmp_app_root, name="B", artist_id=src, updated_at=1_690_000_000)
    s3 = insert_song(tmp_app_root, name="C", artist_id=src, updated_at=1_690_000_000)
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "bulk-reassign",
        "--from-artist-id",
        src,
        "--to-artist-id",
        dst,
        "--song-ids",
        f"{s1},{s3}",
    )
    assert rc == 0, err
    assert out["songs_reassigned"] == 2

    # s1 and s3 now under dst; s2 unchanged; only artist_id + updated_at change.
    r1 = _select(tmp_app_root, "song", s1)
    r2 = _select(tmp_app_root, "song", s2)
    r3 = _select(tmp_app_root, "song", s3)
    assert r1["artist_id"] == dst and r1["updated_at"] == pinned_now
    assert r1["name"] == "A"  # name unchanged
    assert r2["artist_id"] == src and r2["updated_at"] == 1_690_000_000
    assert r3["artist_id"] == dst and r3["updated_at"] == pinned_now


def test_bulk_reassign_without_song_ids_moves_all_live_songs_under_from(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    """R9.10: --song-ids optional; empty/missing means 'all live songs under from'."""
    src = insert_artist(tmp_app_root, name="Src")
    dst = insert_artist(tmp_app_root, name="Dst")
    other = insert_artist(tmp_app_root, name="Other")
    live_1 = insert_song(tmp_app_root, name="A", artist_id=src)
    live_2 = insert_song(tmp_app_root, name="B", artist_id=src)
    dead = insert_song(tmp_app_root, name="C", artist_id=src, status=1)
    unrelated = insert_song(tmp_app_root, name="D", artist_id=other)

    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "bulk-reassign",
        "--from-artist-id",
        src,
        "--to-artist-id",
        dst,
    )
    assert rc == 0, err
    assert out["songs_reassigned"] == 2

    assert _select(tmp_app_root, "song", live_1)["artist_id"] == dst
    assert _select(tmp_app_root, "song", live_2)["artist_id"] == dst
    # Soft-deleted song under src stays put (not live).
    assert _select(tmp_app_root, "song", dead)["artist_id"] == src
    # Unrelated artist's song stays put.
    assert _select(tmp_app_root, "song", unrelated)["artist_id"] == other


def test_bulk_reassign_missing_target_is_not_found(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    """R9.12: missing target artist → NOT_FOUND, no writes."""
    src = insert_artist(tmp_app_root, name="Src")
    sid = insert_song(tmp_app_root, name="A", artist_id=src, updated_at=1_690_000_000)
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "bulk-reassign",
        "--from-artist-id",
        src,
        "--to-artist-id",
        "no-such",
    )
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"
    # Song untouched.
    row = _select(tmp_app_root, "song", sid)
    assert row["artist_id"] == src
    assert row["updated_at"] == 1_690_000_000


def test_bulk_reassign_soft_deleted_target_is_not_found(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    """R9.12: target with status=1 → NOT_FOUND (must reassign to a LIVE target)."""
    src = insert_artist(tmp_app_root, name="Src")
    dead = insert_artist(tmp_app_root, name="Dead", status=1)
    insert_song(tmp_app_root, name="A", artist_id=src)
    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "bulk-reassign",
        "--from-artist-id",
        src,
        "--to-artist-id",
        dead,
    )
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_bulk_reassign_allows_duplicate_collision(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    """R9.11 / Property 8: reassign can create (dst, name) collisions on purpose.

    The operator is expected to clean those up via ``merge_artists.py``.
    """
    src = insert_artist(tmp_app_root, name="Src")
    dst = insert_artist(tmp_app_root, name="Dst")
    s1 = insert_song(tmp_app_root, name="Collide", artist_id=src)
    s2 = insert_song(tmp_app_root, name="Collide", artist_id=dst)
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "bulk-reassign",
        "--from-artist-id",
        src,
        "--to-artist-id",
        dst,
        "--song-ids",
        s1,
    )
    assert rc == 0, err
    assert out["songs_reassigned"] == 1
    # Two live songs now both under dst with name = "Collide".
    r1 = _select(tmp_app_root, "song", s1)
    r2 = _select(tmp_app_root, "song", s2)
    assert r1["artist_id"] == dst and r1["status"] == 0
    assert r2["artist_id"] == dst and r2["status"] == 0
    assert r1["name"] == r2["name"] == "Collide"


def test_bulk_reassign_zero_matching_songs_reports_zero(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    src = insert_artist(tmp_app_root, name="Src")
    dst = insert_artist(tmp_app_root, name="Dst")
    rc, out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "bulk-reassign",
        "--from-artist-id",
        src,
        "--to-artist-id",
        dst,
    )
    assert rc == 0, err
    assert out["songs_reassigned"] == 0


# ---------------------------------------------------------------------------
# R2.4: no args / --help exits zero
# ---------------------------------------------------------------------------


def test_no_args_prints_help_and_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, err = call_script("data.py", cwd=tmp_app_root)
    assert rc == 0
    combined = (out + err).lower()
    assert "usage" in combined or "data.py" in combined


def test_help_flag_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, _err = call_script("data.py", "--help", cwd=tmp_app_root)
    assert rc == 0
    assert "usage" in out.lower()


# ---------------------------------------------------------------------------
# R9.13: rollback on failure
# ---------------------------------------------------------------------------


def test_create_failure_rolls_back(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    """Duplicate rel_show_song raises CONSTRAINT_VIOLATION mid-transaction.

    The DB must be byte-identical before and after. This covers the
    BEGIN IMMEDIATE / ROLLBACK path (R9.13) end-to-end.
    """
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Show")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid)

    db = tmp_app_root / "db" / "datasource.db"
    before = db.read_bytes()

    rc, _out, err = _run_data(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "create",
        "--kind",
        "rel_show_song",
        "--data",
        json.dumps({"show_id": shid, "song_id": sid, "media_url": "http://b"}),
    )
    assert rc == 1
    assert err["error"]["code"] == "CONSTRAINT_VIOLATION"

    after = db.read_bytes()
    assert before == after
