"""Property 16 from requirements.md: rollback on failure.

For any ``data.py`` write, ``merge_artists.py``, ``cleanup.py --confirm``,
``import_resolve.py``, or ``add_play_history.py`` call with an injected
mid-operation failure:

1. No new rows appear.
2. No pre-existing rows are changed.
3. The Script exits with code 1 and prints an Error_Envelope.

Mid-operation failure injection without monkey-patching script internals is
limited at the subprocess boundary. The approach here:

* Use inputs that the script itself will reject mid-flow (e.g. a
  ``rel_show_song`` create with a pair that already exists → INTEGRITY
  ERROR during the INSERT, after the ``BEGIN IMMEDIATE``).
* Use inputs that trigger ``NOT_FOUND`` after partial processing (e.g.
  ``add_play_history`` with one good and one bad triple — the preflight
  catches it, but we also want rollback to hold even when a later write
  would fail).
* Snapshot the DB hash before and after and assert byte-identity.

Expected to FAIL until the relevant scripts land (Tasks 7, 11, 12, 14, 15).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from tests.integration.property._helpers import (
    BASE_SEED,
    json_arg,
    parse_stderr_json,
)

SEED = BASE_SEED + 16


def _db_hash(app_root) -> str:
    path = app_root / "db" / "datasource.db"
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _row_count(app_root, table: str) -> int:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_data_create_rel_show_song_rollback_on_duplicate(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    """Duplicate rel_show_song insert must fail cleanly without touching anything."""
    artist_id = insert_artist(tmp_app_root, name="Prop16")
    song_id = insert_song(tmp_app_root, name="Song", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Show")
    insert_rel(tmp_app_root, show_id=show_id, song_id=song_id, media_url="http://a")

    before = _db_hash(tmp_app_root)
    rc, _out, err = pinned_call(
        "data.py",
        "create",
        "--kind",
        "rel_show_song",
        "--data",
        json_arg(
            {
                "show_id": show_id,
                "song_id": song_id,
                "media_url": "http://new",
            }
        ),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert parse_stderr_json(err)["error"]["code"] == "CONSTRAINT_VIOLATION"
    assert _db_hash(tmp_app_root) == before


def test_merge_artists_rollback_when_source_missing(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
) -> None:
    """Per R10.2: any missing source aborts the whole merge."""
    target = insert_artist(tmp_app_root, name="T")
    _live_source = insert_artist(tmp_app_root, name="Live Src")

    before = _db_hash(tmp_app_root)
    rc, _out, err = pinned_call(
        "merge_artists.py",
        "--target-artist-id",
        target,
        "--source-artist-ids",
        "no-such-artist",
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert parse_stderr_json(err)["error"]["code"] == "NOT_FOUND"
    assert _db_hash(tmp_app_root) == before


def test_cleanup_invalid_input_does_not_open_db_for_writes(
    tmp_app_root,
    call_script,
    insert_artist,
) -> None:
    """Per R11.1/R11.10: cleanup.py without --before writes nothing.

    Seeds a single artist so the hash is non-trivial.
    """
    insert_artist(tmp_app_root, name="Untouched")

    before = _db_hash(tmp_app_root)
    rc, _out, err = call_script("cleanup.py", cwd=tmp_app_root)
    assert rc == 1
    assert parse_stderr_json(err)["error"]["code"] == "INVALID_INPUT"
    assert _db_hash(tmp_app_root) == before


def test_add_play_history_rollback_on_any_missing_triple(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    """Per R14.2: a single missing id aborts the whole batch."""
    artist_id = insert_artist(tmp_app_root, name="Rollback PH")
    song_id = insert_song(tmp_app_root, name="Good", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Good Show")

    triples_file = tmp_app_root / "triples.json"
    triples_file.write_text(
        json.dumps(
            {
                "triples": [
                    {"song_id": song_id, "show_id": show_id, "media_url": "ok"},
                    {"song_id": song_id, "show_id": "missing-show", "media_url": "bad"},
                ]
            }
        )
    )

    ph_before = _row_count(tmp_app_root, "play_history")
    rel_before = _row_count(tmp_app_root, "rel_show_song")
    before = _db_hash(tmp_app_root)

    rc, _out, err = pinned_call(
        "add_play_history.py",
        "--input",
        str(triples_file),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert parse_stderr_json(err)["error"]["code"] == "NOT_FOUND"
    assert _row_count(tmp_app_root, "play_history") == ph_before
    assert _row_count(tmp_app_root, "rel_show_song") == rel_before
    assert _db_hash(tmp_app_root) == before


def test_import_resolve_rollback_on_invalid_answer(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    """A ``choose_artist_id`` not in the candidate list aborts the whole run."""
    # Two artists sharing a name make the ambiguous bucket.
    candidate_a = insert_artist(tmp_app_root, name="Shared", name_context="a")
    candidate_b = insert_artist(tmp_app_root, name="Shared", name_context="b")
    insert_show(tmp_app_root, name="Any Show", vintage="")

    plan = {
        "resolved": [],
        "auto_completable": [],
        "ambiguous": [
            {
                "artist_name": "Shared",
                "song_name": "Conflict Song",
                "show_name": "Any Show",
                "show_name_romaji": "Any Show (romaji)",
                "vintage": "",
                "media_url": "",
                "candidates": [
                    {"id": candidate_a, "name": "Shared", "name_context": "a"},
                    {"id": candidate_b, "name": "Shared", "name_context": "b"},
                ],
            }
        ],
    }
    plan_path = tmp_app_root / "plan.json"
    plan_path.write_text(json.dumps(plan))

    answers = {"0": {"choose_artist_id": "not-in-candidates"}}
    answers_path = tmp_app_root / "answers.json"
    answers_path.write_text(json.dumps(answers))

    before = _db_hash(tmp_app_root)
    rc, _out, err = pinned_call(
        "import_resolve.py",
        "--plan",
        str(plan_path),
        "--answers",
        str(answers_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert parse_stderr_json(err)["error"]["code"] == "INVALID_ANSWER"
    assert _db_hash(tmp_app_root) == before
