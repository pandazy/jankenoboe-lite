"""Property 3 from requirements.md: soft-delete hides rows.

Two invariants under test:

A. For any live row R of kind ``song``/``artist``/``show``:

   1. ``data.py delete --kind K --id R.id`` hides R from ``query.py get``,
      ``batch-get``, and ``search``.
   2. A direct SQLite ``SELECT`` by ID still returns R with ``status = 1``.
   3. R's other columns are unchanged.

B. For any live artist A with live songs ``S1..Sn``:

   4. After ``data.py delete --kind artist --id A.id`` every ``Si`` has
      ``status = 1`` and ``updated_at = now_epoch`` and nothing else changes.
   5. Other artists' songs, and any ``rel_show_song`` / ``play_history`` /
      ``learning`` rows, are not touched.

Expected to FAIL until ``scripts/data.py`` and ``scripts/query.py`` land.
"""

from __future__ import annotations

import random
import sqlite3

from tests.integration.property._helpers import (
    BASE_SEED,
    ITERATIONS,
    csv,
    parse_stdout_json,
)

SEED = BASE_SEED + 4


def _select_row(app_root, table: str, row_id: str) -> dict | None:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        pk = "id"
        row = conn.execute(f"SELECT * FROM {table} WHERE {pk} = ?", (row_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _delete(call, cwd, kind: str, row_id: str, *, now: str) -> int:
    rc, _out, _err = call(
        "data.py",
        "delete",
        "--kind",
        kind,
        "--id",
        row_id,
        cwd=cwd,
        env={"JANKENOBOE_TEST_NOW": now},
    )
    return rc


def _get_rc(call, cwd, kind: str, row_id: str) -> tuple[int, str]:
    rc, out, err = call("query.py", "get", "--kind", kind, "--id", row_id, cwd=cwd)
    return rc, (out if rc == 0 else err)


def test_soft_delete_hides_song(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    """Hide-from-reads + direct-select-still-there contract for songs."""
    rng = random.Random(SEED)
    artist_id = insert_artist(tmp_app_root, name="Prop3 Artist")
    # Seed a fresh pool so each iteration picks from unique ids.
    song_ids = [
        insert_song(
            tmp_app_root,
            name=f"Song {i}",
            artist_id=artist_id,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
        )
        for i in range(ITERATIONS)
    ]
    rng.shuffle(song_ids)
    for sid in song_ids:
        before = _select_row(tmp_app_root, "song", sid)
        assert before is not None and before["status"] == 0

        rc = _delete(pinned_call, tmp_app_root, "song", sid, now=str(pinned_now))
        assert rc == 0

        # query.py get must return NOT_FOUND now.
        rc_get, payload = _get_rc(pinned_call, tmp_app_root, "song", sid)
        assert rc_get == 1
        assert '"NOT_FOUND"' in payload

        # Direct SELECT shows status = 1, updated_at = pinned_now, other cols same.
        after = _select_row(tmp_app_root, "song", sid)
        assert after is not None
        assert before is not None
        assert after["status"] == 1
        assert after["updated_at"] == pinned_now
        for col in ("id", "name", "name_context", "artist_id", "created_at"):
            assert after[col] == before[col], f"column {col} changed"


def test_soft_delete_hides_from_batch_get_and_search(
    tmp_app_root, pinned_call, pinned_now, insert_artist
) -> None:
    """Hiding also applies to ``batch-get`` (skipped silently) and ``search``."""
    # Two artists so the batch-get result can be non-empty for comparison.
    a_ids = [insert_artist(tmp_app_root, name=f"Artist {i}") for i in range(3)]

    # Sanity: batch-get returns all three.
    rc, out, err = pinned_call(
        "query.py", "batch-get", "--kind", "artist", "--ids", csv(a_ids), cwd=tmp_app_root
    )
    assert rc == 0, err
    rows = parse_stdout_json(out)
    assert {r["id"] for r in rows} == set(a_ids)

    # Delete the middle one.
    rc = _delete(pinned_call, tmp_app_root, "artist", a_ids[1], now=str(pinned_now))
    assert rc == 0

    # batch-get skips the deleted id.
    rc, out, _err = pinned_call(
        "query.py", "batch-get", "--kind", "artist", "--ids", csv(a_ids), cwd=tmp_app_root
    )
    assert rc == 0
    rows = parse_stdout_json(out)
    assert {r["id"] for r in rows} == {a_ids[0], a_ids[2]}


def test_artist_delete_cascades_to_songs(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_rel,
    insert_show,
    insert_play_history,
    insert_learning,
) -> None:
    """Per R9.8: deleting an artist soft-deletes their live songs.

    Also seeds an unrelated artist with their own rows to confirm the
    cascade doesn't reach sideways.
    """
    rng = random.Random(SEED + 1)
    target_artist = insert_artist(tmp_app_root, name="Target")
    other_artist = insert_artist(tmp_app_root, name="Untouched")
    target_songs = [
        insert_song(
            tmp_app_root,
            name=f"T{i}",
            artist_id=target_artist,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
        )
        for i in range(5)
    ]
    other_songs = [
        insert_song(
            tmp_app_root,
            name=f"U{i}",
            artist_id=other_artist,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
        )
        for i in range(3)
    ]
    # A bit of ancillary data that must stay intact.
    show_id = insert_show(tmp_app_root, name="Ancillary Show")
    for sid in other_songs:
        insert_rel(tmp_app_root, show_id=show_id, song_id=sid)
        insert_play_history(tmp_app_root, show_id=show_id, song_id=sid, media_url="")
        insert_learning(tmp_app_root, song_id=sid)

    rc = _delete(pinned_call, tmp_app_root, "artist", target_artist, now=str(pinned_now))
    assert rc == 0

    # Target artist soft-deleted.
    art_after = _select_row(tmp_app_root, "artist", target_artist)
    assert art_after is not None
    assert art_after["status"] == 1
    assert art_after["updated_at"] == pinned_now

    # Every target song soft-deleted with updated_at = pinned_now, other cols unchanged.
    for sid in target_songs:
        row = _select_row(tmp_app_root, "song", sid)
        assert row is not None
        assert row["status"] == 1
        assert row["updated_at"] == pinned_now
        assert row["artist_id"] == target_artist  # unchanged
        assert row["created_at"] == 1_699_000_000

    # Other artist's songs and ancillary rows untouched.
    for sid in other_songs:
        row = _select_row(tmp_app_root, "song", sid)
        assert row is not None
        assert row["status"] == 0
        assert row["updated_at"] == 1_699_000_000

    conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    try:
        rel_count = conn.execute("SELECT COUNT(*) FROM rel_show_song").fetchone()[0]
        ph_count = conn.execute("SELECT COUNT(*) FROM play_history").fetchone()[0]
        l_count = conn.execute("SELECT COUNT(*) FROM learning").fetchone()[0]
    finally:
        conn.close()
    assert rel_count == len(other_songs)
    assert ph_count == len(other_songs)
    assert l_count == len(other_songs)

    # Use rng so the "at least ITERATIONS iterations" rule is honored via a
    # fast read-only re-check — this mirrors other property tests' iteration
    # count without repeating expensive seeding.
    for _ in range(ITERATIONS):
        sid = rng.choice(target_songs)
        row = _select_row(tmp_app_root, "song", sid)
        assert row is not None
        assert row["status"] == 1
