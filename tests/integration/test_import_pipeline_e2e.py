"""End-to-end AMQ import integration test.

Seed a small DB, craft an AMQ JSON input with all three buckets
(resolved, auto_completable, ambiguous), then run:

    import_plan.py → plan.json
    import_resolve.py → triples.json
    add_play_history.py → writes play_history + rel_show_song

Assert exact row counts at each step. Then run the whole pipeline a
second time with the same input and answers and assert no new
artists, songs, shows, or ``rel_show_song`` rows appear — only N new
``play_history`` rows. See requirements.md R12-R14 and Property 13.

This test complements ``tests/integration/property/test_import_property.py``:
the property test randomises; this one is a deterministic,
readable walkthrough of the happy path.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _count(app_root, table: str) -> int:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _fetch_all(app_root, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def test_full_amq_pipeline_with_idempotent_second_run(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    # ---- Seed the DB ----------------------------------------------------
    # An existing artist with one existing song — will drive the
    # "resolved" bucket.
    existing_artist = insert_artist(tmp_app_root, name="Existing Artist")
    existing_song = insert_song(
        tmp_app_root,
        name="Existing Song",
        artist_id=existing_artist,
    )
    existing_show = insert_show(
        tmp_app_root,
        name="Existing Show",
        vintage="Spring 2024",
    )

    # Two artists sharing a name — forces the "ambiguous" bucket.
    shared_a = insert_artist(tmp_app_root, name="Shared", name_context="solo")
    shared_b = insert_artist(tmp_app_root, name="Shared", name_context="band")

    # ---- Craft the AMQ input with one entry per bucket ------------------
    entries = [
        # resolved (existing artist + existing song + existing show)
        {
            "artist_name": "Existing Artist",
            "song_name": "Existing Song",
            "show_name": "Existing Show",
            "vintage": "Spring 2024",
            "media_url": "http://x/resolved",
        },
        # auto_completable — existing artist, new song
        {
            "artist_name": "Existing Artist",
            "song_name": "Fresh Song",
            "show_name": "Existing Show",
            "vintage": "Spring 2024",
            "media_url": "http://x/auto-existing-artist",
        },
        # auto_completable — new artist and new show too
        {
            "artist_name": "Brand New",
            "song_name": "Brand New Song",
            "show_name": "Brand New Show",
            "vintage": "Fall 2025",
            "media_url": "http://x/auto-new-artist",
        },
        # ambiguous (two artists share "Shared")
        {
            "artist_name": "Shared",
            "song_name": "Pick Me",
            "show_name": "Existing Show",
            "vintage": "Spring 2024",
            "media_url": "http://x/ambiguous",
        },
    ]
    amq = tmp_app_root / "amq.json"
    amq.write_text(json.dumps(entries), encoding="utf-8")

    plan_path = tmp_app_root / "plan.json"
    answers_path = tmp_app_root / "answers.json"
    triples_path = tmp_app_root / "triples.json"

    # Baseline counts — no play_history yet, 3 artists, 1 song, 1 show,
    # 0 rel_show_song.
    assert _count(tmp_app_root, "artist") == 3
    assert _count(tmp_app_root, "song") == 1
    assert _count(tmp_app_root, "show") == 1
    assert _count(tmp_app_root, "rel_show_song") == 0
    assert _count(tmp_app_root, "play_history") == 0

    # ---- Step 1: import_plan.py ----------------------------------------
    rc, out, err = pinned_call(
        "import_plan.py",
        "--input",
        str(amq),
        "--output",
        str(plan_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err
    summary = json.loads(out)
    assert summary["resolved_count"] == 1
    assert summary["auto_completable_count"] == 2
    assert summary["ambiguous_count"] == 1
    assert summary["resolved_count"] + summary["auto_completable_count"] + summary[
        "ambiguous_count"
    ] == len(entries)

    # Plan is read-only — counts unchanged.
    assert _count(tmp_app_root, "artist") == 3
    assert _count(tmp_app_root, "song") == 1
    assert _count(tmp_app_root, "show") == 1

    # ---- Build answers.json for the one ambiguous entry ----------------
    plan = json.loads(plan_path.read_text())
    assert len(plan["ambiguous"]) == 1
    # Pick shared_a as the disambiguation choice.
    answers = {"0": {"choose_artist_id": shared_a}}
    answers_path.write_text(json.dumps(answers), encoding="utf-8")

    # ---- Step 2: import_resolve.py -------------------------------------
    rc, out, err = pinned_call(
        "import_resolve.py",
        "--plan",
        str(plan_path),
        "--answers",
        str(answers_path),
        "--output",
        str(triples_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err
    resolve_summary = json.loads(out)
    assert resolve_summary["triples_count"] == 4
    # One new song for "Fresh Song" under existing_artist, one for
    # "Brand New Song" under a new artist, one for "Pick Me" under
    # shared_a. That's 3 new songs.
    assert resolve_summary["songs_created"] == 3
    assert resolve_summary["artists_created"] == 1  # "Brand New"
    assert resolve_summary["shows_created"] == 1  # "Brand New Show"
    assert resolve_summary["unresolved_ambiguous_count"] == 0

    # DB after resolve.
    assert _count(tmp_app_root, "artist") == 4  # +1 "Brand New"
    assert _count(tmp_app_root, "song") == 4  # +3
    assert _count(tmp_app_root, "show") == 2  # +1 "Brand New Show"
    assert _count(tmp_app_root, "rel_show_song") == 0  # resolve doesn't touch this
    assert _count(tmp_app_root, "play_history") == 0

    # triples.json has 4 entries with the right shape.
    triples_payload = json.loads(triples_path.read_text())
    assert len(triples_payload["triples"]) == 4
    for t in triples_payload["triples"]:
        assert set(t.keys()) == {"song_id", "show_id", "media_url"}

    # ---- Step 3: add_play_history.py -----------------------------------
    rc, out, err = pinned_call(
        "add_play_history.py",
        "--input",
        str(triples_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err
    add_summary = json.loads(out)
    assert add_summary["play_history_created"] == 4
    assert add_summary["rel_show_song_created"] == 4  # all 4 pairs are new

    assert _count(tmp_app_root, "play_history") == 4
    assert _count(tmp_app_root, "rel_show_song") == 4
    # Song/artist/show unchanged by step 3 (Property 14).
    assert _count(tmp_app_root, "artist") == 4
    assert _count(tmp_app_root, "song") == 4
    assert _count(tmp_app_root, "show") == 2

    # The "Existing Song" resolved-bucket triple should still point at
    # existing_song and existing_show.
    matching = _fetch_all(
        tmp_app_root,
        "SELECT song_id, show_id FROM play_history WHERE media_url = ?",
        ("http://x/resolved",),
    )
    assert len(matching) == 1
    assert matching[0]["song_id"] == existing_song
    assert matching[0]["show_id"] == existing_show

    # The ambiguous entry resolved to shared_a (not shared_b).
    amb_songs = _fetch_all(
        tmp_app_root,
        "SELECT s.artist_id FROM song s JOIN play_history p ON p.song_id = s.id "
        "WHERE p.media_url = ?",
        ("http://x/ambiguous",),
    )
    assert len(amb_songs) == 1
    assert amb_songs[0]["artist_id"] == shared_a
    assert amb_songs[0]["artist_id"] != shared_b

    # ---- Rerun the full pipeline — Property 13.7 -----------------------
    # Snapshot the non-play_history table counts.
    artists_after_first = _count(tmp_app_root, "artist")
    songs_after_first = _count(tmp_app_root, "song")
    shows_after_first = _count(tmp_app_root, "show")
    rel_after_first = _count(tmp_app_root, "rel_show_song")
    ph_after_first = _count(tmp_app_root, "play_history")

    # Step 1 again — fresh plan against the now-richer DB.
    rc, _out, err = pinned_call(
        "import_plan.py",
        "--input",
        str(amq),
        "--output",
        str(plan_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err

    # Build answers from the new plan (ambiguous index can move if
    # order shifts; rebuild from scratch).
    new_plan = json.loads(plan_path.read_text())
    new_answers = {
        str(i): {"choose_artist_id": shared_a} for i, _ in enumerate(new_plan["ambiguous"])
    }
    answers_path.write_text(json.dumps(new_answers), encoding="utf-8")

    # Step 2 again.
    rc, out, err = pinned_call(
        "import_resolve.py",
        "--plan",
        str(plan_path),
        "--answers",
        str(answers_path),
        "--output",
        str(triples_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err
    second_resolve = json.loads(out)
    assert second_resolve["triples_count"] == 4
    # Same 4 triples out, but the rows already exist so resolve
    # creates zero of each kind (idempotent get-or-insert per
    # R13.3/R13.4).
    assert second_resolve["artists_created"] == 0
    assert second_resolve["songs_created"] == 0
    assert second_resolve["shows_created"] == 0

    # Step 3 again — this WILL add 4 new play_history rows (no dedup
    # by design, R14.9). rel_show_song count stays flat because every
    # pair already exists.
    rc, out, err = pinned_call(
        "add_play_history.py",
        "--input",
        str(triples_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err
    second_add = json.loads(out)
    assert second_add["play_history_created"] == 4
    assert second_add["rel_show_song_created"] == 0

    # ---- Final invariants ----------------------------------------------
    assert _count(tmp_app_root, "artist") == artists_after_first
    assert _count(tmp_app_root, "song") == songs_after_first
    assert _count(tmp_app_root, "show") == shows_after_first
    assert _count(tmp_app_root, "rel_show_song") == rel_after_first
    assert _count(tmp_app_root, "play_history") == ph_after_first + 4
