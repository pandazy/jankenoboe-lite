"""Property 7 from requirements.md: ``learning.py due`` matches Due_SQL_Condition.

The one source of truth for "due" is Due_SQL_Condition in the Glossary.
``learning.py due`` runs that SQL inside SQLite. This test seeds random rows
and asserts the script's result set equals what the SQL returns directly.

Reading the clock via SQLite's ``strftime('%s','now')`` makes this test
inherently time-coupled. To stay deterministic we read SQLite's clock once
at seeding time and anchor every seeded ``last_level_up_at`` / ``updated_at``
relative to that value — a pattern the design doc spells out in the Testing
Strategy section.

Expected to FAIL until ``scripts/learning.py`` lands (Task 8).
"""

from __future__ import annotations

import json
import random
import sqlite3

from scripts import _common
from tests.integration.property._helpers import (
    BASE_SEED,
    ITERATIONS,
    parse_stdout_json,
)

SEED = BASE_SEED + 7
DUE_SQL = """
SELECT l.id FROM learning l
JOIN song s ON s.id = l.song_id
WHERE s.status = 0
  AND (
      l.graduated = 0
      AND (
          (l.last_level_up_at > 0 AND l.level = 0
           AND (CAST(strftime('%s','now') AS INTEGER) + :offset) >= (l.last_level_up_at + 300))
          OR
          (l.last_level_up_at = 0 AND l.level = 0
           AND (CAST(strftime('%s','now') AS INTEGER) + :offset) >= (l.updated_at + 300))
          OR
          (l.level > 0
           AND (json_extract(l.level_up_path, '$[' || l.level || ']') * 86400 + l.last_level_up_at)
               <= (CAST(strftime('%s','now') AS INTEGER) + :offset))
      )
  )
"""


def _sqlite_now(db_file) -> int:
    conn = sqlite3.connect(str(db_file))
    try:
        row = conn.execute("SELECT CAST(strftime('%s','now') AS INTEGER)").fetchone()
        return int(row[0])
    finally:
        conn.close()


def _expected_due_ids(db_file, offset: int) -> set[str]:
    conn = sqlite3.connect(str(db_file))
    try:
        rows = conn.execute(DUE_SQL, {"offset": offset}).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _call_due(call, cwd, offset: int = 0) -> list[dict]:
    rc, out, err = call(
        "learning.py",
        "due",
        "--offset",
        str(offset),
        cwd=cwd,
    )
    assert rc == 0, f"due failed: rc={rc} err={err!r}"
    payload = parse_stdout_json(out)
    # Expected shape: a list, or {"results": [...]}. Accept either.
    if isinstance(payload, dict) and "results" in payload:
        return payload["results"]
    assert isinstance(payload, list)
    return payload


def _seed_one(
    app_root,
    insert_song,
    insert_learning,
    artist_id: str,
    *,
    now: int,
    level: int,
    graduated: int,
    last_level_up_at: int,
    updated_at: int,
    song_status: int = 0,
) -> str:
    """Seed one (song, learning) pair. Returns the learning id."""
    import sqlite3  # noqa: PLC0415

    song_id = insert_song(
        app_root,
        name=f"due-song-{now}-{level}-{graduated}-{last_level_up_at}-{updated_at}",
        artist_id=artist_id,
        status=song_status,
    )
    # If song_status should be 1, the inserter wrote status = 0; flip it.
    if song_status == 1:
        conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
        try:
            conn.execute("UPDATE song SET status = 1 WHERE id = ?", (song_id,))
            conn.commit()
        finally:
            conn.close()
    return insert_learning(
        app_root,
        song_id=song_id,
        level=level,
        graduated=graduated,
        created_at=now - 100_000,
        updated_at=updated_at,
        last_level_up_at=last_level_up_at,
        level_up_path=json.dumps(_common.DEFAULT_LEVEL_UP_PATH),
    )


def test_due_matches_sql_direct(
    tmp_app_root, call_script, insert_artist, insert_song, insert_learning
) -> None:
    """Three-clause coverage: level=0 never-leveled, level=0 leveled, level>0.

    Seeds a spread of rows that land on every branch of Due_SQL_Condition,
    plus some soft-deleted songs and some graduated rows (which must be
    excluded).
    """
    rng = random.Random(SEED)
    artist_id = insert_artist(tmp_app_root, name="Prop7")
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    ids_seeded: list[str] = []
    # Branch A: level = 0, last_level_up_at > 0 — due iff now >= last_level_up_at + 300.
    for _ in range(ITERATIONS // 4):
        offset_from_now = rng.randint(-1_000, 1_000)
        lup = now - 300 + offset_from_now
        ids_seeded.append(
            _seed_one(
                tmp_app_root,
                insert_song,
                insert_learning,
                artist_id,
                now=now,
                level=0,
                graduated=0,
                last_level_up_at=max(1, lup),
                updated_at=lup,
            )
        )
    # Branch B: level = 0, last_level_up_at = 0 — due iff now >= updated_at + 300.
    for _ in range(ITERATIONS // 4):
        offset_from_now = rng.randint(-1_000, 1_000)
        upd = now - 300 + offset_from_now
        ids_seeded.append(
            _seed_one(
                tmp_app_root,
                insert_song,
                insert_learning,
                artist_id,
                now=now,
                level=0,
                graduated=0,
                last_level_up_at=0,
                updated_at=max(1, upd),
            )
        )
    # Branch C: level > 0 — due iff level_up_path[level]*86400 + last_level_up_at <= now.
    for _ in range(ITERATIONS // 4):
        level = rng.randint(1, 5)
        # Pick last_level_up_at around the due boundary.
        wait_seconds = _common.DEFAULT_LEVEL_UP_PATH[level] * 86400
        offset_from_now = rng.randint(-10, 10)
        lup = now - wait_seconds + offset_from_now
        ids_seeded.append(
            _seed_one(
                tmp_app_root,
                insert_song,
                insert_learning,
                artist_id,
                now=now,
                level=level,
                graduated=0,
                last_level_up_at=max(1, lup),
                updated_at=lup,
            )
        )
    # Graduated rows — must never be returned.
    for _ in range(5):
        ids_seeded.append(
            _seed_one(
                tmp_app_root,
                insert_song,
                insert_learning,
                artist_id,
                now=now,
                level=rng.randint(0, 5),
                graduated=1,
                last_level_up_at=now - 10_000,
                updated_at=now - 10_000,
            )
        )
    # Soft-deleted songs — must never be returned.
    for _ in range(5):
        ids_seeded.append(
            _seed_one(
                tmp_app_root,
                insert_song,
                insert_learning,
                artist_id,
                now=now,
                level=0,
                graduated=0,
                last_level_up_at=now - 1_000,
                updated_at=now - 1_000,
                song_status=1,
            )
        )

    expected = _expected_due_ids(tmp_app_root / "db" / "datasource.db", offset=0)
    got = {r["id"] for r in _call_due(call_script, tmp_app_root, offset=0)}
    assert got == expected, f"due mismatch\nextra: {got - expected}\nmissing: {expected - got}"


def test_due_with_positive_offset_matches_sql(
    tmp_app_root, call_script, insert_artist, insert_song, insert_learning
) -> None:
    """A positive ``--offset`` shifts the comparison forward."""
    rng = random.Random(SEED + 1)
    artist_id = insert_artist(tmp_app_root, name="Prop7-offset")
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    # Seed level-0 rows whose last_level_up_at lands 100 s in the future
    # relative to the 300 s threshold (i.e. need offset ≥ 100 to be due).
    for _ in range(ITERATIONS):
        _seed_one(
            tmp_app_root,
            insert_song,
            insert_learning,
            artist_id,
            now=now,
            level=0,
            graduated=0,
            last_level_up_at=now - 200,
            updated_at=now - 200,
        )
    # Random non-negative offset.
    offset = rng.randint(0, 500)
    expected = _expected_due_ids(tmp_app_root / "db" / "datasource.db", offset=offset)
    got = {r["id"] for r in _call_due(call_script, tmp_app_root, offset=offset)}
    assert got == expected


def test_due_excludes_graduated_and_soft_deleted_songs(
    tmp_app_root, call_script, insert_artist, insert_song, insert_learning
) -> None:
    """A sanity iteration: confirm the two exclusion rules hold row-by-row."""
    artist_id = insert_artist(tmp_app_root, name="Prop7-excl")
    now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
    graduated_id = _seed_one(
        tmp_app_root,
        insert_song,
        insert_learning,
        artist_id,
        now=now,
        level=0,
        graduated=1,
        last_level_up_at=now - 10_000,
        updated_at=now - 10_000,
    )
    deleted_id = _seed_one(
        tmp_app_root,
        insert_song,
        insert_learning,
        artist_id,
        now=now,
        level=0,
        graduated=0,
        last_level_up_at=now - 10_000,
        updated_at=now - 10_000,
        song_status=1,
    )
    due_ids = {r["id"] for r in _call_due(call_script, tmp_app_root)}
    assert graduated_id not in due_ids
    assert deleted_id not in due_ids
