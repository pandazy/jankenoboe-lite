"""Integration tests for ``scripts/import_resolve.py``.

Covers R13.1-R13.10. Uses ``pinned_call`` so timestamps on freshly
created rows are deterministic.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any


def _db_hash(app_root) -> str:
    h = hashlib.sha256()
    h.update((app_root / "db" / "datasource.db").read_bytes())
    return h.hexdigest()


def _row_count(app_root, table: str) -> int:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _fetch_row(app_root, table: str, row_id: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _run_resolve(
    pinned_call,
    cwd,
    now,
    plan_path,
    answers_path: str | None = None,
    output_path: str | None = None,
) -> tuple[int, Any, Any]:
    args: list[str] = ["--plan", str(plan_path)]
    if answers_path is not None:
        args += ["--answers", str(answers_path)]
    if output_path is not None:
        args += ["--output", str(output_path)]
    rc, out, err = pinned_call("import_resolve.py", *args, cwd=cwd, now=now)
    out_parsed: Any = None
    err_parsed: Any = None
    if out.strip():
        try:
            out_parsed = json.loads(out)
        except json.JSONDecodeError:
            out_parsed = None
    if err.strip():
        try:
            err_parsed = json.loads(err)
        except json.JSONDecodeError:
            err_parsed = None
    return rc, out_parsed, err_parsed


def _write_plan(app_root, plan: dict) -> str:
    p = app_root / "plan.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return str(p)


def _write_answers(app_root, answers: dict) -> str:
    p = app_root / "answers.json"
    p.write_text(json.dumps(answers), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# R13.3 — resolved entries reuse existing song_id; do not re-query
# ---------------------------------------------------------------------------


def test_resolved_reuses_existing_song_id(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="A")
    song_id = insert_song(tmp_app_root, name="S", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [{"song_id": song_id, "show_id": show_id, "media_url": "http://x"}],
        "auto_completable": [],
        "ambiguous": [],
    }
    plan_path = _write_plan(tmp_app_root, plan)

    rc, envelope, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path)
    assert rc == 0, err
    assert envelope["artists_created"] == 0
    assert envelope["songs_created"] == 0
    assert envelope["shows_created"] == 0
    assert len(envelope["triples"]) == 1
    triple = envelope["triples"][0]
    assert triple["song_id"] == song_id
    assert triple["show_id"] == show_id
    assert triple["media_url"] == "http://x"


def test_resolved_with_show_to_create_creates_show(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="A")
    song_id = insert_song(tmp_app_root, name="S", artist_id=artist_id)

    plan = {
        "resolved": [
            {
                "song_id": song_id,
                "show_to_create": {
                    "name": "New Show",
                    "vintage": "Spring 2024",
                    "s_type": None,
                    "name_romaji": None,
                },
                "media_url": "",
            }
        ],
        "auto_completable": [],
        "ambiguous": [],
    }
    plan_path = _write_plan(tmp_app_root, plan)

    before_shows = _row_count(tmp_app_root, "show")
    rc, envelope, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path)
    assert rc == 0, err
    assert envelope["shows_created"] == 1
    assert _row_count(tmp_app_root, "show") == before_shows + 1
    triple = envelope["triples"][0]
    assert triple["song_id"] == song_id
    new_show = _fetch_row(tmp_app_root, "show", triple["show_id"])
    assert new_show is not None
    assert new_show["name"] == "New Show"
    assert new_show["vintage"] == "Spring 2024"


# ---------------------------------------------------------------------------
# R13.4 — auto_completable with artist_id only creates the song
# ---------------------------------------------------------------------------


def test_auto_completable_with_artist_id_creates_only_song(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="A")
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [],
        "auto_completable": [
            {
                "artist_id": artist_id,
                "song_name": "Fresh",
                "show_id": show_id,
                "media_url": "",
            }
        ],
        "ambiguous": [],
    }
    plan_path = _write_plan(tmp_app_root, plan)

    before_artists = _row_count(tmp_app_root, "artist")
    before_songs = _row_count(tmp_app_root, "song")

    rc, envelope, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path)
    assert rc == 0, err
    assert envelope["artists_created"] == 0
    assert envelope["songs_created"] == 1
    assert envelope["shows_created"] == 0
    assert _row_count(tmp_app_root, "artist") == before_artists
    assert _row_count(tmp_app_root, "song") == before_songs + 1

    triple = envelope["triples"][0]
    new_song = _fetch_row(tmp_app_root, "song", triple["song_id"])
    assert new_song is not None
    assert new_song["name"] == "Fresh"
    assert new_song["artist_id"] == artist_id
    assert new_song["status"] == 0


def test_auto_completable_with_artist_to_create_creates_artist_and_song(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_show,
) -> None:
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [],
        "auto_completable": [
            {
                "artist_to_create": {"name": "Brand New Artist"},
                "song_name": "Brand New Song",
                "show_id": show_id,
                "media_url": "",
            }
        ],
        "ambiguous": [],
    }
    plan_path = _write_plan(tmp_app_root, plan)

    before_artists = _row_count(tmp_app_root, "artist")
    rc, envelope, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path)
    assert rc == 0, err
    assert envelope["artists_created"] == 1
    assert envelope["songs_created"] == 1
    assert _row_count(tmp_app_root, "artist") == before_artists + 1


# ---------------------------------------------------------------------------
# R13.5 / R13.6 — ambiguous entries answered via choose_artist_id or create_artist
# ---------------------------------------------------------------------------


def test_ambiguous_answered_with_choose_artist_id(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    cand_a = insert_artist(tmp_app_root, name="Shared", name_context="a")
    cand_b = insert_artist(tmp_app_root, name="Shared", name_context="b")
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [],
        "auto_completable": [],
        "ambiguous": [
            {
                "artist_name": "Shared",
                "song_name": "Pick Me",
                "show_name": "Sh",
                "vintage": "",
                "show_id": show_id,
                "media_url": "",
                "candidates": [
                    {"id": cand_a, "name": "Shared", "name_context": "a"},
                    {"id": cand_b, "name": "Shared", "name_context": "b"},
                ],
            }
        ],
    }
    plan_path = _write_plan(tmp_app_root, plan)
    answers_path = _write_answers(tmp_app_root, {"0": {"choose_artist_id": cand_a}})

    rc, envelope, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path, answers_path)
    assert rc == 0, err
    assert envelope["artists_created"] == 0
    assert envelope["songs_created"] == 1
    assert len(envelope["triples"]) == 1
    song_id = envelope["triples"][0]["song_id"]
    new_song = _fetch_row(tmp_app_root, "song", song_id)
    assert new_song is not None
    assert new_song["artist_id"] == cand_a
    # show_id from plan is used too.
    assert envelope["triples"][0]["show_id"] == show_id


def test_ambiguous_answered_with_create_artist(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    cand_a = insert_artist(tmp_app_root, name="Shared", name_context="a")
    cand_b = insert_artist(tmp_app_root, name="Shared", name_context="b")
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [],
        "auto_completable": [],
        "ambiguous": [
            {
                "artist_name": "Shared",
                "song_name": "Third Option",
                "show_name": "Sh",
                "vintage": "",
                "show_id": show_id,
                "media_url": "",
                "candidates": [
                    {"id": cand_a, "name": "Shared", "name_context": "a"},
                    {"id": cand_b, "name": "Shared", "name_context": "b"},
                ],
            }
        ],
    }
    plan_path = _write_plan(tmp_app_root, plan)
    answers_path = _write_answers(
        tmp_app_root,
        {"0": {"create_artist": {"name": "Shared", "name_context": "third"}}},
    )

    rc, envelope, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path, answers_path)
    assert rc == 0, err
    assert envelope["artists_created"] == 1
    assert envelope["songs_created"] == 1


# ---------------------------------------------------------------------------
# R13.7 — unresolved ambiguous entries pass through cleanly
# ---------------------------------------------------------------------------


def test_ambiguous_without_answer_lands_in_unresolved(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    cand_a = insert_artist(tmp_app_root, name="Shared", name_context="a")
    cand_b = insert_artist(tmp_app_root, name="Shared", name_context="b")
    insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [],
        "auto_completable": [],
        "ambiguous": [
            {
                "artist_name": "Shared",
                "song_name": "Unanswered",
                "show_name": "Sh",
                "vintage": "",
                "media_url": "",
                "candidates": [
                    {"id": cand_a, "name": "Shared", "name_context": "a"},
                    {"id": cand_b, "name": "Shared", "name_context": "b"},
                ],
            }
        ],
    }
    plan_path = _write_plan(tmp_app_root, plan)

    before_songs = _row_count(tmp_app_root, "song")
    rc, envelope, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path)
    assert rc == 0, err
    assert envelope["triples"] == []
    assert envelope["songs_created"] == 0
    assert len(envelope["unresolved_ambiguous"]) == 1
    assert envelope["unresolved_ambiguous"][0]["index"] == 0
    assert _row_count(tmp_app_root, "song") == before_songs


# ---------------------------------------------------------------------------
# R13.6 — INVALID_ANSWER for bad answer shapes; rollback
# ---------------------------------------------------------------------------


def test_invalid_answer_choose_id_not_in_candidates(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    cand_a = insert_artist(tmp_app_root, name="Shared", name_context="a")
    cand_b = insert_artist(tmp_app_root, name="Shared", name_context="b")
    insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [],
        "auto_completable": [],
        "ambiguous": [
            {
                "artist_name": "Shared",
                "song_name": "Nope",
                "show_name": "Sh",
                "vintage": "",
                "media_url": "",
                "candidates": [
                    {"id": cand_a, "name": "Shared", "name_context": "a"},
                    {"id": cand_b, "name": "Shared", "name_context": "b"},
                ],
            }
        ],
    }
    plan_path = _write_plan(tmp_app_root, plan)
    answers_path = _write_answers(tmp_app_root, {"0": {"choose_artist_id": "not-a-candidate"}})

    before = _db_hash(tmp_app_root)
    rc, _out, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path, answers_path)
    assert rc == 1
    assert err["error"]["code"] == "INVALID_ANSWER"
    # Rollback — DB byte-identical.
    assert _db_hash(tmp_app_root) == before


def test_invalid_answer_unknown_shape(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    cand_a = insert_artist(tmp_app_root, name="Shared", name_context="a")
    cand_b = insert_artist(tmp_app_root, name="Shared", name_context="b")
    insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [],
        "auto_completable": [],
        "ambiguous": [
            {
                "artist_name": "Shared",
                "song_name": "Nope",
                "show_name": "Sh",
                "vintage": "",
                "media_url": "",
                "candidates": [
                    {"id": cand_a, "name": "Shared", "name_context": "a"},
                    {"id": cand_b, "name": "Shared", "name_context": "b"},
                ],
            }
        ],
    }
    plan_path = _write_plan(tmp_app_root, plan)
    answers_path = _write_answers(tmp_app_root, {"0": {"weird": "answer"}})

    rc, _out, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path, answers_path)
    assert rc == 1
    assert err["error"]["code"] == "INVALID_ANSWER"


# ---------------------------------------------------------------------------
# R13.8 — rollback on mid-operation failure
# ---------------------------------------------------------------------------


def test_rollback_on_failure_in_second_entry(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    """One good auto_completable followed by one with a bad answer rolls everything back."""
    existing_artist = insert_artist(tmp_app_root, name="Existing")
    cand_a = insert_artist(tmp_app_root, name="Shared", name_context="a")
    cand_b = insert_artist(tmp_app_root, name="Shared", name_context="b")
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [],
        "auto_completable": [
            {
                "artist_id": existing_artist,
                "song_name": "Would Be Created",
                "show_id": show_id,
                "media_url": "",
            }
        ],
        "ambiguous": [
            {
                "artist_name": "Shared",
                "song_name": "Crash Here",
                "show_name": "Sh",
                "vintage": "",
                "media_url": "",
                "candidates": [
                    {"id": cand_a, "name": "Shared", "name_context": "a"},
                    {"id": cand_b, "name": "Shared", "name_context": "b"},
                ],
            }
        ],
    }
    plan_path = _write_plan(tmp_app_root, plan)
    answers_path = _write_answers(tmp_app_root, {"0": {"choose_artist_id": "not-a-candidate"}})

    before = _db_hash(tmp_app_root)
    rc, _out, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path, answers_path)
    assert rc == 1
    assert err["error"]["code"] == "INVALID_ANSWER"
    # The first auto_completable write must have rolled back too.
    assert _db_hash(tmp_app_root) == before


# ---------------------------------------------------------------------------
# R13.10 — --output writes file + prints summary
# ---------------------------------------------------------------------------


def test_output_writes_envelope_and_prints_summary(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="A")
    song_id = insert_song(tmp_app_root, name="S", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [{"song_id": song_id, "show_id": show_id, "media_url": ""}],
        "auto_completable": [],
        "ambiguous": [],
    }
    plan_path = _write_plan(tmp_app_root, plan)
    out_path = tmp_app_root / "triples.json"

    rc, summary, err = _run_resolve(
        pinned_call,
        tmp_app_root,
        pinned_now,
        plan_path,
        output_path=str(out_path),
    )
    assert rc == 0, err
    # Summary shape: counts plus path, not the full envelope.
    assert "path" in summary
    assert summary["triples_count"] == 1

    written = json.loads(out_path.read_text())
    assert len(written["triples"]) == 1
    assert written["triples"][0]["song_id"] == song_id


# ---------------------------------------------------------------------------
# Processing order — R13.2: resolved → auto_completable → ambiguous.
# A mixed plan's triples come out in that order.
# ---------------------------------------------------------------------------


def test_triples_ordered_resolved_then_auto_then_ambiguous(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    existing_artist = insert_artist(tmp_app_root, name="Existing")
    existing_song = insert_song(tmp_app_root, name="Existing Song", artist_id=existing_artist)
    cand_a = insert_artist(tmp_app_root, name="Shared", name_context="a")
    cand_b = insert_artist(tmp_app_root, name="Shared", name_context="b")
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    plan = {
        "resolved": [{"song_id": existing_song, "show_id": show_id, "media_url": "res"}],
        "auto_completable": [
            {
                "artist_id": existing_artist,
                "song_name": "Auto Song",
                "show_id": show_id,
                "media_url": "auto",
            }
        ],
        "ambiguous": [
            {
                "artist_name": "Shared",
                "song_name": "Amb Song",
                "show_name": "Sh",
                "vintage": "",
                "show_id": show_id,
                "media_url": "amb",
                "candidates": [
                    {"id": cand_a, "name": "Shared", "name_context": "a"},
                    {"id": cand_b, "name": "Shared", "name_context": "b"},
                ],
            }
        ],
    }
    plan_path = _write_plan(tmp_app_root, plan)
    answers_path = _write_answers(tmp_app_root, {"0": {"choose_artist_id": cand_a}})

    rc, envelope, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path, answers_path)
    assert rc == 0, err
    media_urls = [t["media_url"] for t in envelope["triples"]]
    assert media_urls == ["res", "auto", "amb"]


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_missing_plan_file_emits_invalid_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    rc, _out, err = _run_resolve(
        pinned_call,
        tmp_app_root,
        pinned_now,
        tmp_app_root / "no-such-plan.json",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_empty_plan_emits_empty_envelope(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    plan_path = _write_plan(tmp_app_root, {"resolved": [], "auto_completable": [], "ambiguous": []})
    rc, envelope, err = _run_resolve(pinned_call, tmp_app_root, pinned_now, plan_path)
    assert rc == 0, err
    assert envelope["triples"] == []
    assert envelope["artists_created"] == 0
    assert envelope["songs_created"] == 0
    assert envelope["shows_created"] == 0
    assert envelope["unresolved_ambiguous"] == []
