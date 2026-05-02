"""Integration tests for ``learning.py due``.

The ``due`` op compares SQLite's ``strftime('%s','now')`` against stored
timestamps. That clock is outside our ``JANKENOBOE_TEST_NOW`` seam, so
these tests read SQLite's "now" once at seeding time and anchor every
seeded timestamp relative to that value. The design doc's Testing
Strategy section spells out this pattern.

Coverage per R7 and Property 7:
  * Branch A — level = 0, last_level_up_at > 0 (5 min rule)
  * Branch B — level = 0, last_level_up_at = 0 (falls back to updated_at)
  * Branch C — level > 0 (level_up_path[level] days from last_level_up_at)
  * Boundary where the comparison is ``=`` (due)
  * ``--offset K`` shifts an otherwise-not-due row into the result
  * Soft-deleted songs are filtered out
  * Graduated records never returned
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _sqlite_now(db_file) -> int:
    """Ask SQLite for its own epoch 'now'.

    The ``due`` SQL uses ``strftime('%s','now')`` which we can't mock
    from Python. Reading the clock once here gives us a stable anchor
    to build seeded rows around.
    """
    conn = sqlite3.connect(str(db_file))
    try:
        row = conn.execute("SELECT CAST(strftime('%s','now') AS INTEGER)").fetchone()
        return int(row[0])
    finally:
        conn.close()


def _call_due(call_script, cwd, offset: int = 0) -> list[dict]:
    rc, out, err = call_script("learning.py", "due", "--offset", str(offset), cwd=cwd)
    assert rc == 0, err
    payload = json.loads(out)
    assert isinstance(payload, dict)
    assert payload["offset"] == offset
    return list(payload["results"])


def _due_ids(call_script, cwd, offset: int = 0) -> set[str]:
    return {r["id"] for r in _call_due(call_script, cwd, offset=offset)}


def test_branch_a_level_zero_after_first_review(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Level 0, last_level_up_at > 0: due at last_level_up_at + 300 s."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")

    past = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=0,
        last_level_up_at=now - 400,  # well past the 300s threshold
        updated_at=now - 400,
    )
    # Another row seeded just after the threshold — NOT due yet.
    song2 = insert_song(tmp_app_root, name="S2", artist_id=aid)
    not_yet = insert_learning(
        tmp_app_root,
        song_id=song2,
        level=0,
        last_level_up_at=now - 10,  # 10s old — nowhere near the 300s threshold
        updated_at=now - 10,
    )
    ids = _due_ids(call_script, tmp_app_root)
    assert past in ids
    assert not_yet not in ids


def test_branch_b_level_zero_never_reviewed(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Level 0, last_level_up_at = 0: due at updated_at + 300 s."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")

    due = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=0,
        last_level_up_at=0,
        updated_at=now - 400,
    )
    song2 = insert_song(tmp_app_root, name="S2", artist_id=aid)
    not_yet = insert_learning(
        tmp_app_root,
        song_id=song2,
        level=0,
        last_level_up_at=0,
        updated_at=now - 10,
    )
    ids = _due_ids(call_script, tmp_app_root)
    assert due in ids
    assert not_yet not in ids


def test_branch_c_level_above_zero_uses_level_up_path(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Level > 0: due at ``level_up_path[level] * 86400 + last_level_up_at``.

    Uses a custom ``level_up_path`` for deterministic day counts: level 1
    waits 2 days, level 2 waits 5 days. Seeds one row that is due (3
    days after a level-1 waypoint ago) and one that is not (just 10 s
    after a level-1 waypoint — has 2 days to go).
    """
    aid = insert_artist(tmp_app_root, name="A")
    s1 = insert_song(tmp_app_root, name="due", artist_id=aid)
    s2 = insert_song(tmp_app_root, name="not_yet", artist_id=aid)
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")

    # level 1, waited 3 days since last_level_up_at, but path says 2 days → due.
    custom_path = json.dumps([1, 2, 5, 13, 32])  # entries 0..4
    due = insert_learning(
        tmp_app_root,
        song_id=s1,
        level=1,
        last_level_up_at=now - 3 * 86400,
        updated_at=now - 3 * 86400,
        level_up_path=custom_path,
    )
    # level 1, waited 10 seconds since last_level_up_at → not due yet (need 2 days).
    not_yet = insert_learning(
        tmp_app_root,
        song_id=s2,
        level=1,
        last_level_up_at=now - 10,
        updated_at=now - 10,
        level_up_path=custom_path,
    )
    ids = _due_ids(call_script, tmp_app_root)
    assert due in ids
    assert not_yet not in ids


def test_boundary_equal_is_due(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """The Due_SQL_Condition uses ``>=`` / ``<=``: equality is due.

    Seeds a level-0 row at exactly ``now - 300`` seconds ago. That's the
    boundary point: ``now >= last_level_up_at + 300``. It must be due.
    """
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")

    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=0,
        last_level_up_at=now - 300,
        updated_at=now - 300,
    )
    ids = _due_ids(call_script, tmp_app_root)
    assert lid in ids


def test_offset_shifts_otherwise_not_due_row_into_result(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R7.3: positive ``--offset`` includes rows due within that many seconds.

    Seeds a level-0 row at ``now - 200`` (100 s away from the 300 s
    threshold). With ``--offset 0`` it shouldn't appear; with
    ``--offset 200`` it should.
    """
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")

    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=0,
        last_level_up_at=now - 200,
        updated_at=now - 200,
    )
    assert lid not in _due_ids(call_script, tmp_app_root, offset=0)
    assert lid in _due_ids(call_script, tmp_app_root, offset=200)


def test_soft_deleted_song_is_filtered_out(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R7.5: rows whose song has status = 1 never appear in due."""
    aid = insert_artist(tmp_app_root, name="A")
    dead_song = insert_song(tmp_app_root, name="dead", artist_id=aid, status=1)
    live_song = insert_song(tmp_app_root, name="live", artist_id=aid)
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")

    dead_lid = insert_learning(
        tmp_app_root,
        song_id=dead_song,
        level=0,
        last_level_up_at=now - 10_000,
        updated_at=now - 10_000,
    )
    live_lid = insert_learning(
        tmp_app_root,
        song_id=live_song,
        level=0,
        last_level_up_at=now - 10_000,
        updated_at=now - 10_000,
    )
    ids = _due_ids(call_script, tmp_app_root)
    assert dead_lid not in ids
    assert live_lid in ids


def test_graduated_row_never_returned(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R7.4: graduated = 1 is never due, even past the time threshold."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")

    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=5,
        graduated=1,
        last_level_up_at=now - 10_000_000,  # ancient; would be due if not graduated
        updated_at=now - 10_000_000,
    )
    assert lid not in _due_ids(call_script, tmp_app_root)


def test_due_rows_are_ordered_by_level_desc_then_id_asc(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R7.6: order by stored level descending, id ascending.

    Uses a custom level_up_path so ordering is the only moving part.
    """
    aid = insert_artist(tmp_app_root, name="A")
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    custom = json.dumps([1, 1, 1, 1, 1])  # every level due after 1 day

    expected: list[tuple[int, str]] = []
    for level in (0, 2, 1):
        sid = insert_song(tmp_app_root, name=f"s-{level}", artist_id=aid)
        lid = insert_learning(
            tmp_app_root,
            song_id=sid,
            level=level,
            last_level_up_at=now - 2 * 86400,  # ≥ 1 day ago → due
            updated_at=now - 2 * 86400,
            level_up_path=custom,
        )
        expected.append((level, lid))

    # Expected ordering: highest level first, then lexicographic id.
    expected.sort(key=lambda t: (-t[0], t[1]))

    rows = _call_due(call_script, tmp_app_root)
    returned = [(r["level"], r["id"]) for r in rows]
    assert returned == expected


def test_due_payload_includes_required_fields(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R7.7: each record carries id, song_id, song_name, level, display_level,
    wait_days, last_level_up_at, updated_at, graduated."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="Important Song", artist_id=aid)
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    insert_learning(
        tmp_app_root,
        song_id=sid,
        level=3,
        last_level_up_at=now - 1_000_000,  # well past any threshold
        updated_at=now - 1_000_000,
    )
    rows = _call_due(call_script, tmp_app_root)
    assert len(rows) == 1
    r: dict[str, Any] = rows[0]
    for key in (
        "id",
        "song_id",
        "song_name",
        "level",
        "display_level",
        "wait_days",
        "last_level_up_at",
        "updated_at",
        "graduated",
    ):
        assert key in r, f"missing {key}"
    assert r["song_name"] == "Important Song"
    assert r["display_level"] == r["level"] + 1
