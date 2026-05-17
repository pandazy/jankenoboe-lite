"""Property 13 from requirements.md: import pipeline end-to-end.

For a random AMQ input mixing existing artists, new names, existing songs, and
shared artist names:

1. ``import_plan.py`` buckets every entry into exactly one of ``resolved``,
   ``auto_completable``, ``ambiguous``. Sum equals entry count.
2. Plan is deterministic — two runs on the same input produce byte-identical
   plans.
3. After ``import_resolve.py`` with an answer for every ambiguous entry,
   ``len(triples) == len(entries)``.
4. After ``add_play_history.py``, each triple adds exactly one
   ``play_history`` row and each ``(show_id, song_id)`` pair has exactly one
   ``rel_show_song`` row.
5. Running the full pipeline a second time on the same input adds no new
   artists/songs/shows/rel_show_song rows — only play_history rows.

Expected to FAIL until ``import_plan.py``, ``import_resolve.py``, and
``add_play_history.py`` land (Tasks 13-15).
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3

from tests.integration.property._helpers import (
    BASE_SEED,
    parse_stdout_json,
)

SEED = BASE_SEED + 13


def _table_count(app_root, table: str) -> int:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _file_hash(path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _build_amq_input(
    app_root,
    rng: random.Random,
    insert_artist,
    insert_song,
    insert_show,
) -> tuple[list[dict], str, str, str]:
    """Seed the DB with a base state and build an AMQ JSON file to import.

    Returns ``(entries, amq_path, ambiguous_answers_path, chosen_artist_id)``.
    Writes two JSON files under ``app_root``.
    """
    # Existing artist with one existing song.
    existing_artist = insert_artist(app_root, name="Existing")
    _existing_song = insert_song(
        app_root,
        name="Known Song",
        artist_id=existing_artist,
    )

    # Two artists sharing a name — forces the ambiguous bucket.
    ambiguous_a = insert_artist(app_root, name="Shared", name_context="context-a")
    _ambiguous_b = insert_artist(app_root, name="Shared", name_context="context-b")

    # An existing show.
    _existing_show = insert_show(app_root, name="Known Show", vintage="Spring 2024")

    entries = [
        # Resolved: existing artist + existing song + existing show.
        {
            "artist_name": "Existing",
            "song_name": "Known Song",
            "show_name": "Known Show",
            "show_name_romaji": "Known Show (romaji)",
            "vintage": "Spring 2024",
            "media_url": "http://x/resolved",
        },
        # Auto-completable: existing artist, new song, new show.
        {
            "artist_name": "Existing",
            "song_name": "New Song From Existing",
            "show_name": "New Show",
            "show_name_romaji": "New Show (romaji)",
            "vintage": "Fall 2024",
            "media_url": "http://x/auto-with-artist",
        },
        # Auto-completable: new artist, new song.
        {
            "artist_name": "Brand New",
            "song_name": "Brand New Song",
            "show_name": "Brand New Show",
            "show_name_romaji": "Brand New Show (romaji)",
            "vintage": "Winter 2025",
            "media_url": "http://x/auto-new-artist",
        },
        # Ambiguous: the "Shared" name matches two artists.
        {
            "artist_name": "Shared",
            "song_name": "Song By Shared",
            "show_name": "Known Show",
            "show_name_romaji": "Known Show (romaji)",
            "vintage": "Spring 2024",
            "media_url": "http://x/ambiguous",
        },
    ]
    rng.shuffle(entries)

    amq_file = app_root / "amq.json"
    amq_file.write_text(json.dumps(entries), encoding="utf-8")

    # Answer for the ambiguous entry: choose artist A.
    # The index depends on where the ambiguous entry lands after shuffle —
    # the plan output tells us; we'll fill this in after running import_plan.
    answers_file = app_root / "answers.json"
    answers_file.write_text("{}", encoding="utf-8")

    # Return ambiguous_a so the test can build the answer after planning.
    return entries, str(amq_file), str(answers_file), ambiguous_a


def test_import_pipeline_end_to_end(
    tmp_app_root,
    call_script,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    rng = random.Random(SEED)
    entries, amq_path, answers_path, chosen_artist = _build_amq_input(
        tmp_app_root,
        rng,
        insert_artist,
        insert_song,
        insert_show,
    )

    plan_path = str(tmp_app_root / "plan.json")
    triples_path = str(tmp_app_root / "triples.json")

    # Step 1: import_plan.py writes plan.json.
    rc, out, err = pinned_call(
        "import_plan.py",
        "--input",
        amq_path,
        "--output",
        plan_path,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err
    summary = parse_stdout_json(out)
    assert isinstance(summary, dict)
    total = (
        summary["resolved_count"] + summary["auto_completable_count"] + summary["ambiguous_count"]
    )
    assert total == len(entries)
    # Deterministic: a second run on the same input produces the same plan.
    plan_before = _file_hash(tmp_app_root / "plan.json")
    rc, _out, _err = pinned_call(
        "import_plan.py",
        "--input",
        amq_path,
        "--output",
        plan_path,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0
    assert _file_hash(tmp_app_root / "plan.json") == plan_before

    # Build answers.json based on the plan's ambiguous array.
    plan = json.loads((tmp_app_root / "plan.json").read_text())
    answers = {}
    for i, _entry in enumerate(plan.get("ambiguous", [])):
        answers[str(i)] = {"choose_artist_id": chosen_artist}
    (tmp_app_root / "answers.json").write_text(json.dumps(answers))

    # Baseline counts before resolve + add.
    rel_before = _table_count(tmp_app_root, "rel_show_song")
    ph_before = _table_count(tmp_app_root, "play_history")

    # Step 2: import_resolve.py → triples.json.
    rc, out, err = pinned_call(
        "import_resolve.py",
        "--plan",
        plan_path,
        "--answers",
        answers_path,
        "--output",
        triples_path,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err

    triples_payload = json.loads((tmp_app_root / "triples.json").read_text())
    assert len(triples_payload["triples"]) == len(entries)

    # Step 3: add_play_history.py.
    rc, out, err = pinned_call(
        "add_play_history.py",
        "--input",
        triples_path,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err
    add_payload = parse_stdout_json(out)
    assert isinstance(add_payload, dict)
    assert add_payload["play_history_created"] == len(entries)

    # play_history grew by N; rel_show_song grew by at most N.
    ph_mid = _table_count(tmp_app_root, "play_history")
    assert ph_mid - ph_before == len(entries)
    rel_mid = _table_count(tmp_app_root, "rel_show_song")
    assert rel_mid >= rel_before
    assert rel_mid - rel_before <= len(entries)

    # Idempotency: running the full pipeline a second time (plan →
    # resolve → add) adds no new artists/songs/shows/rel_show_song,
    # only N new play_history rows. Per Property 13, rerunning needs
    # a FRESH plan so the already-created rows land in the resolved
    # / auto_completable buckets.
    artists_after_first = _table_count(tmp_app_root, "artist")
    songs_after_first = _table_count(tmp_app_root, "song")
    shows_after_first = _table_count(tmp_app_root, "show")
    rel_after_first = _table_count(tmp_app_root, "rel_show_song")

    rc, _out, _err = pinned_call(
        "import_plan.py",
        "--input",
        amq_path,
        "--output",
        plan_path,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0

    # Re-build answers from the new plan (ambiguous indices may differ).
    plan = json.loads((tmp_app_root / "plan.json").read_text())
    answers = {}
    for i, _entry in enumerate(plan.get("ambiguous", [])):
        answers[str(i)] = {"choose_artist_id": chosen_artist}
    (tmp_app_root / "answers.json").write_text(json.dumps(answers))

    rc, _out, _err = pinned_call(
        "import_resolve.py",
        "--plan",
        plan_path,
        "--answers",
        answers_path,
        "--output",
        triples_path,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0

    rc, _out, _err = pinned_call(
        "add_play_history.py",
        "--input",
        triples_path,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0

    assert _table_count(tmp_app_root, "artist") == artists_after_first
    assert _table_count(tmp_app_root, "song") == songs_after_first
    assert _table_count(tmp_app_root, "show") == shows_after_first
    assert _table_count(tmp_app_root, "rel_show_song") == rel_after_first
    assert _table_count(tmp_app_root, "play_history") == ph_mid + len(entries)
