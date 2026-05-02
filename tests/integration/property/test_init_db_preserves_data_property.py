"""Property I-3 — user data preserved across a skip run.

For each iteration: seed a randomised schema-valid row set, snapshot
every row by (table, id), run init_db, reopen the DB with sqlite3
directly (not _common.open_db — decouples the test from harness
behaviour), re-read every row, assert equality per table.
"""

from __future__ import annotations

import json
import random
import sqlite3

from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 202


def _snapshot_rows(db_file) -> dict[str, list[tuple]]:
    """For every table, return its rows as a list of tuples ordered by id."""
    tables = (
        "artist",
        "song",
        "show",
        "rel_show_song",
        "play_history",
        "learning",
    )
    out: dict[str, list[tuple]] = {}
    conn = sqlite3.connect(str(db_file))
    try:
        for table in tables:
            order = "ORDER BY show_id, song_id" if table == "rel_show_song" else "ORDER BY id"
            rows = conn.execute(f"SELECT * FROM {table} {order}").fetchall()
            out[table] = [tuple(r) for r in rows]
    finally:
        conn.close()
    return out


def test_skip_preserves_user_data(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    rng = random.Random(SEED)

    for _ in range(ITERATIONS):
        # Pre-populate randomly.
        artist_ids = [
            insert_artist(tmp_app_root, name=f"A-{rng.randint(0, 1_000_000)}")
            for _ in range(rng.randint(1, 3))
        ]
        song_ids: list[str] = []
        for i in range(rng.randint(1, 5)):
            aid = rng.choice(artist_ids)
            song_ids.append(insert_song(tmp_app_root, name=f"S-{i}", artist_id=aid))
        show_ids = [insert_show(tmp_app_root, name=f"Sh-{i}") for i in range(rng.randint(1, 3))]
        for sid in song_ids:
            insert_rel(tmp_app_root, show_id=rng.choice(show_ids), song_id=sid)
            insert_play_history(tmp_app_root, show_id=rng.choice(show_ids), song_id=sid)
            if rng.random() < 0.6:
                insert_learning(tmp_app_root, song_id=sid)

        db_file = tmp_app_root / "db" / "datasource.db"
        before = _snapshot_rows(db_file)

        rc, out, err = call_script("init_db.py", cwd=tmp_app_root)
        assert rc == 0, err
        payload = json.loads(out.strip())
        assert payload["created"] is False

        after = _snapshot_rows(db_file)
        assert after == before
