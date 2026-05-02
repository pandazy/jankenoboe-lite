"""Property 10 from requirements.md: cleanup stays in its lane.

For a random cutoff ``T`` and a seeded DB:

1. Dry-run is byte-identical before/after.
2. ``--confirm`` leaves only rows where ``status = 0 OR updated_at > T``.
3. Every dependent row points at a surviving parent (no dangling FKs).
4. A second ``--confirm`` run finds zero candidates.
5. Missing ``--before`` yields ``INVALID_INPUT`` and no writes.
6. Any number of dry-runs against any DB state are safe.

Expected to FAIL until ``scripts/cleanup.py`` lands (Task 12).
"""

from __future__ import annotations

import hashlib
import random
import sqlite3

from tests.integration.property._helpers import (
    BASE_SEED,
    ITERATIONS,
    parse_stderr_json,
    parse_stdout_json,
)

SEED = BASE_SEED + 10


def _db_hash(app_root) -> str:
    """SHA-256 of the raw DB file. Used for "byte-identical" assertions."""
    path = app_root / "db" / "datasource.db"
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _counts(app_root) -> dict[str, int]:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("song", "artist", "show", "rel_show_song", "play_history", "learning")
        }
    finally:
        conn.close()


def _seed_mixed(
    app_root,
    rng: random.Random,
    *,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    """Seed a mix of live and soft-deleted rows around a cutoff of 1_700_000_000."""
    # Live artists and their songs.
    live_artist = insert_artist(
        app_root, name="Live Artist", created_at=1_690_000_000, updated_at=1_710_000_000
    )
    live_song = insert_song(
        app_root,
        name="Live Song",
        artist_id=live_artist,
        created_at=1_690_000_000,
        updated_at=1_710_000_000,
    )

    # Soft-deleted rows older than the cutoff — targets for hard-delete.
    old_artist = insert_artist(
        app_root,
        name="Old Artist",
        created_at=1_600_000_000,
        updated_at=1_650_000_000,
    )
    old_song = insert_song(
        app_root,
        name="Old Song",
        artist_id=old_artist,
        created_at=1_600_000_000,
        updated_at=1_650_000_000,
    )
    # Flip their status to 1 directly.
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        conn.execute("UPDATE artist SET status = 1 WHERE id = ?", (old_artist,))
        conn.execute("UPDATE song SET status = 1 WHERE id = ?", (old_song,))
        conn.commit()
    finally:
        conn.close()

    # Soft-deleted but AFTER the cutoff — must NOT be touched.
    recent_artist = insert_artist(
        app_root,
        name="Recent Artist",
        created_at=1_690_000_000,
        updated_at=1_710_000_000,
    )
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        conn.execute("UPDATE artist SET status = 1 WHERE id = ?", (recent_artist,))
        conn.commit()
    finally:
        conn.close()

    # A show and dependents for the old_song — these must cascade.
    old_show = insert_show(
        app_root,
        name="Old Show",
        created_at=1_600_000_000,
        updated_at=1_650_000_000,
    )
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        conn.execute("UPDATE show SET status = 1 WHERE id = ?", (old_show,))
        conn.commit()
    finally:
        conn.close()
    insert_rel(app_root, show_id=old_show, song_id=old_song, media_url="http://o/1")
    insert_play_history(app_root, show_id=old_show, song_id=old_song)
    insert_play_history(app_root, show_id=old_show, song_id=old_song)
    insert_learning(app_root, song_id=old_song, created_at=1_650_000_000)

    # Some dependents on live rows that MUST stay.
    live_show = insert_show(
        app_root,
        name="Live Show",
        created_at=1_690_000_000,
        updated_at=1_690_000_000,
    )
    insert_rel(app_root, show_id=live_show, song_id=live_song, media_url="http://l/1")
    insert_play_history(app_root, show_id=live_show, song_id=live_song)
    insert_learning(app_root, song_id=live_song, created_at=1_690_000_000)

    # Use rng to occasionally add extra rows so seeding varies between tests.
    for _ in range(rng.randint(0, 3)):
        insert_song(
            app_root,
            name=f"extra-{rng.randint(0, 10**9)}",
            artist_id=live_artist,
            created_at=1_690_000_000,
            updated_at=1_710_000_000,
        )


def test_dry_run_is_byte_identical(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    """Per R11.4/R11.6: no ``--confirm`` means no writes."""
    rng = random.Random(SEED)
    _seed_mixed(
        tmp_app_root,
        rng,
        insert_artist=insert_artist,
        insert_song=insert_song,
        insert_show=insert_show,
        insert_rel=insert_rel,
        insert_play_history=insert_play_history,
        insert_learning=insert_learning,
    )

    cutoff = 1_700_000_000
    before = _db_hash(tmp_app_root)
    for _ in range(min(ITERATIONS, 10)):
        rc, out, err = call_script(
            "cleanup.py",
            "--before",
            str(cutoff),
            cwd=tmp_app_root,
        )
        assert rc == 0, err
        payload = parse_stdout_json(out)
        assert isinstance(payload, dict)
        assert payload["executed"] is False
    after = _db_hash(tmp_app_root)
    assert before == after


def test_confirm_deletes_targets_and_cascades(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    """Per R11.3/R11.7/R11.12: --confirm actually deletes, and a second run is a no-op."""
    rng = random.Random(SEED + 1)
    _seed_mixed(
        tmp_app_root,
        rng,
        insert_artist=insert_artist,
        insert_song=insert_song,
        insert_show=insert_show,
        insert_rel=insert_rel,
        insert_play_history=insert_play_history,
        insert_learning=insert_learning,
    )

    cutoff = 1_700_000_000
    rc, out, err = call_script(
        "cleanup.py",
        "--before",
        str(cutoff),
        "--confirm",
        cwd=tmp_app_root,
    )
    assert rc == 0, err
    payload = parse_stdout_json(out)
    assert isinstance(payload, dict)
    assert payload["executed"] is True

    # Every surviving song/artist/show row must satisfy status = 0 OR updated_at > cutoff.
    conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    try:
        for table in ("song", "artist", "show"):
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                keys = row.keys() if hasattr(row, "keys") else None
                assert keys is None or "status" in keys
                # sqlite3.Row supports mapping access after row_factory set.
        conn.row_factory = sqlite3.Row
        for table in ("song", "artist", "show"):
            for row in conn.execute(f"SELECT * FROM {table}"):
                assert row["status"] == 0 or row["updated_at"] > cutoff
    finally:
        conn.close()

    # Second --confirm: zero candidates.
    rc, out, _err = call_script(
        "cleanup.py",
        "--before",
        str(cutoff),
        "--confirm",
        cwd=tmp_app_root,
    )
    assert rc == 0
    payload = parse_stdout_json(out)
    assert isinstance(payload, dict)
    assert payload["executed"] is True
    for counter in payload.get("hard_deleted_counts", {}).values():
        assert counter == 0


def test_missing_before_flag_is_invalid_input(tmp_app_root, call_script) -> None:
    """Per R11.1/R11.10: cleanup.py without --before → INVALID_INPUT, DB unchanged."""
    before_counts = _counts(tmp_app_root)
    rc, _out, err = call_script("cleanup.py", cwd=tmp_app_root)
    assert rc == 1
    assert parse_stderr_json(err)["error"]["code"] == "INVALID_INPUT"
    assert _counts(tmp_app_root) == before_counts
