"""Property 14 from requirements.md: step boundaries.

1. ``import_plan.py`` leaves the DB byte-identical.
2. ``import_resolve.py`` on a plan with empty ``ambiguous`` and only
   ``artist_id`` (no ``artist_to_create``) in ``auto_completable`` creates
   zero artist rows.
3. ``add_play_history.py`` touches only ``play_history`` and ``rel_show_song``
   (snapshots of ``song``, ``artist``, ``show`` match before and after).
4. ``add_play_history.py`` rejects the whole batch with ``NOT_FOUND`` when any
   triple references a missing or soft-deleted id — no partial writes.

Expected to FAIL until the three import scripts land (Tasks 13-15).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from tests.integration.property._helpers import (
    BASE_SEED,
    parse_stderr_json,
    parse_stdout_json,
)

SEED = BASE_SEED + 14


def _db_hash(app_root) -> str:
    path = app_root / "db" / "datasource.db"
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _table_snapshot(app_root, table: str) -> list[dict]:
    """All rows from ``table`` ordered by id, as a list of dicts."""
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        # Uniform ordering so snapshots compare cleanly.
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def test_import_plan_is_read_only(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    """Seed a DB, run import_plan, hash the DB file — must match exactly."""
    artist_id = insert_artist(tmp_app_root, name="Plan RO")
    insert_song(tmp_app_root, name="Plan Song", artist_id=artist_id)
    insert_show(tmp_app_root, name="Plan Show", vintage="Fall 2024")

    amq = tmp_app_root / "amq.json"
    amq.write_text(
        json.dumps(
            [
                {
                    "artist_name": "Plan RO",
                    "song_name": "Plan Song",
                    "show_name": "Plan Show",
                    "vintage": "Fall 2024",
                    "media_url": "",
                }
            ]
        )
    )

    before = _db_hash(tmp_app_root)
    rc, _out, err = pinned_call(
        "import_plan.py",
        "--input",
        str(amq),
        "--output",
        str(tmp_app_root / "plan.json"),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err
    assert _db_hash(tmp_app_root) == before


def test_resolve_creates_zero_artists_when_plan_has_no_new_artists(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    """A plan with only ``artist_id`` (no ``artist_to_create``) and empty
    ``ambiguous`` must leave the ``artist`` table untouched.
    """
    artist_id = insert_artist(tmp_app_root, name="Existing Artist")
    show_id = insert_show(tmp_app_root, name="Existing Show", vintage="Winter 2024")

    plan = {
        "resolved": [],
        "auto_completable": [
            {
                "artist_id": artist_id,
                "song_name": "Fresh Song",
                "show_id": show_id,
                "media_url": "http://x/y",
            }
        ],
        "ambiguous": [],
    }
    plan_path = tmp_app_root / "plan.json"
    plan_path.write_text(json.dumps(plan))
    triples_path = tmp_app_root / "triples.json"

    before_artists = _table_snapshot(tmp_app_root, "artist")
    before_shows = _table_snapshot(tmp_app_root, "show")
    before_songs = _table_snapshot(tmp_app_root, "song")

    rc, out, err = pinned_call(
        "import_resolve.py",
        "--plan",
        str(plan_path),
        "--output",
        str(triples_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err
    envelope = parse_stdout_json(out)
    # The script may either print the full envelope or a summary — accept both.
    if isinstance(envelope, dict):
        assert envelope.get("artists_created", 0) == 0

    # Artist and show tables untouched; one new song row.
    assert _table_snapshot(tmp_app_root, "artist") == before_artists
    assert _table_snapshot(tmp_app_root, "show") == before_shows
    after_songs = _table_snapshot(tmp_app_root, "song")
    assert len(after_songs) == len(before_songs) + 1


def test_add_play_history_touches_only_ph_and_rel(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    """Snapshot song/artist/show before and after — must be identical."""
    artist_id = insert_artist(tmp_app_root, name="PH RO")
    song_id = insert_song(tmp_app_root, name="PH Song", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="PH Show", vintage="Fall 2024")

    triples_file = tmp_app_root / "triples.json"
    triples_file.write_text(
        json.dumps({"triples": [{"song_id": song_id, "show_id": show_id, "media_url": "http://a"}]})
    )

    song_before = _table_snapshot(tmp_app_root, "song")
    artist_before = _table_snapshot(tmp_app_root, "artist")
    show_before = _table_snapshot(tmp_app_root, "show")

    rc, _out, err = pinned_call(
        "add_play_history.py",
        "--input",
        str(triples_file),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err

    assert _table_snapshot(tmp_app_root, "song") == song_before
    assert _table_snapshot(tmp_app_root, "artist") == artist_before
    assert _table_snapshot(tmp_app_root, "show") == show_before


def test_add_play_history_rejects_missing_id_with_no_partial_writes(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    """One bad triple in the batch aborts the whole call."""
    artist_id = insert_artist(tmp_app_root, name="PH partial")
    song_id = insert_song(tmp_app_root, name="Good Song", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Good Show", vintage="")

    triples_file = tmp_app_root / "triples.json"
    triples_file.write_text(
        json.dumps(
            {
                "triples": [
                    {"song_id": song_id, "show_id": show_id, "media_url": ""},
                    {
                        "song_id": "no-such-song",
                        "show_id": show_id,
                        "media_url": "",
                    },
                ]
            }
        )
    )

    ph_before = _table_snapshot(tmp_app_root, "play_history")
    rel_before = _table_snapshot(tmp_app_root, "rel_show_song")

    rc, _out, err = pinned_call(
        "add_play_history.py",
        "--input",
        str(triples_file),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    env = parse_stderr_json(err)
    assert env["error"]["code"] == "NOT_FOUND"

    # Both tables untouched.
    assert _table_snapshot(tmp_app_root, "play_history") == ph_before
    assert _table_snapshot(tmp_app_root, "rel_show_song") == rel_before
