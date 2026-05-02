"""Property 11 from requirements.md: show-song uniqueness.

For any ``(show_id, song_id)`` pair:

1. The first ``data.py create rel_show_song`` succeeds.
2. A second ``create`` with the same pair fails with ``CONSTRAINT_VIOLATION``.
3. After the failed second insert, the existing row is unchanged.
4. ``COUNT(*) FROM rel_show_song WHERE show_id = ? AND song_id = ?`` equals 1.

Expected to FAIL until ``scripts/data.py`` lands (Task 7).
"""

from __future__ import annotations

import random
import sqlite3

from tests.integration.property._helpers import (
    BASE_SEED,
    ITERATIONS,
    json_arg,
    parse_stderr_json,
    parse_stdout_json,
)

SEED = BASE_SEED + 11


def _rel_row(app_root, show_id: str, song_id: str) -> dict | None:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM rel_show_song WHERE show_id = ? AND song_id = ?",
            (show_id, song_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _rel_count(app_root, show_id: str, song_id: str) -> int:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM rel_show_song WHERE show_id = ? AND song_id = ?",
            (show_id, song_id),
        ).fetchone()[0]
    finally:
        conn.close()


def test_duplicate_create_rel_show_song_is_constraint_violation(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    rng = random.Random(SEED)
    artist_id = insert_artist(tmp_app_root, name="Prop11")
    # Seed multiple shows + songs so a random selection is meaningful.
    shows = [insert_show(tmp_app_root, name=f"Show-{i}") for i in range(10)]
    songs = [insert_song(tmp_app_root, name=f"Song-{i}", artist_id=artist_id) for i in range(10)]

    pairs_tested: set[tuple[str, str]] = set()
    # Collect ITERATIONS unique (show, song) pairs from the seeded matrix.
    while len(pairs_tested) < min(ITERATIONS, len(shows) * len(songs)):
        pair = (rng.choice(shows), rng.choice(songs))
        if pair in pairs_tested:
            continue
        pairs_tested.add(pair)
        show_id, song_id = pair

        media_url = f"http://media/{len(pairs_tested)}"
        payload = {"show_id": show_id, "song_id": song_id, "media_url": media_url}

        # First create: success.
        rc, out, err = pinned_call(
            "data.py",
            "create",
            "--kind",
            "rel_show_song",
            "--data",
            json_arg(payload),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc == 0, err
        created = parse_stdout_json(out)
        assert isinstance(created, dict)
        assert created["show_id"] == show_id
        assert created["song_id"] == song_id
        assert created["media_url"] == media_url

        before = _rel_row(tmp_app_root, show_id, song_id)
        assert before is not None

        # Second create with the same pair: CONSTRAINT_VIOLATION.
        rc2, _out2, err2 = pinned_call(
            "data.py",
            "create",
            "--kind",
            "rel_show_song",
            "--data",
            json_arg({**payload, "media_url": "http://different"}),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc2 == 1
        assert parse_stderr_json(err2)["error"]["code"] == "CONSTRAINT_VIOLATION"

        # Existing row unchanged.
        after = _rel_row(tmp_app_root, show_id, song_id)
        assert after == before
        assert _rel_count(tmp_app_root, show_id, song_id) == 1
