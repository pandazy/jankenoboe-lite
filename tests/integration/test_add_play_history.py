"""Integration tests for ``scripts/add_play_history.py``.

Covers R14.1-R14.9. Uses ``pinned_call`` so ``created_at`` is
deterministic. Verifies idempotency on ``rel_show_song`` and the
"no-dedup" behaviour of ``play_history``.
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


def _table_snapshot(app_root, table: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _write_triples(app_root, triples: list[dict]) -> str:
    p = app_root / "triples.json"
    p.write_text(json.dumps({"triples": triples}), encoding="utf-8")
    return str(p)


def _run(
    pinned_call,
    cwd,
    now,
    input_path: str | None = None,
    inline: str | None = None,
) -> tuple[int, Any, Any]:
    args: list[str] = []
    if input_path is not None:
        args += ["--input", input_path]
    if inline is not None:
        args += ["--triples", inline]
    rc, out, err = pinned_call("add_play_history.py", *args, cwd=cwd, now=now)
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


# ---------------------------------------------------------------------------
# R14.3 / R14.4 — happy path inserts N play_history rows and up to N rels
# ---------------------------------------------------------------------------


def test_happy_path_inserts_ph_and_rel(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="A")
    song_1 = insert_song(tmp_app_root, name="S1", artist_id=artist_id)
    song_2 = insert_song(tmp_app_root, name="S2", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    triples = [
        {"song_id": song_1, "show_id": show_id, "media_url": "http://1"},
        {"song_id": song_2, "show_id": show_id, "media_url": "http://2"},
    ]
    triples_path = _write_triples(tmp_app_root, triples)

    ph_before = _row_count(tmp_app_root, "play_history")
    rel_before = _row_count(tmp_app_root, "rel_show_song")

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc == 0, err
    assert out == {"play_history_created": 2, "rel_show_song_created": 2}
    assert _row_count(tmp_app_root, "play_history") == ph_before + 2
    assert _row_count(tmp_app_root, "rel_show_song") == rel_before + 2


# ---------------------------------------------------------------------------
# R14.3 — running twice with the same triples doubles play_history but not rel
# ---------------------------------------------------------------------------


def test_second_run_duplicates_ph_but_not_rel(
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

    triples = [{"song_id": song_id, "show_id": show_id, "media_url": "u"}]
    triples_path = _write_triples(tmp_app_root, triples)

    rc1, out1, _ = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc1 == 0
    assert out1 == {"play_history_created": 1, "rel_show_song_created": 1}

    ph_after_first = _row_count(tmp_app_root, "play_history")
    rel_after_first = _row_count(tmp_app_root, "rel_show_song")

    rc2, out2, _ = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc2 == 0
    # Second run: one new play_history row, but rel_show_song INSERT OR
    # IGNORE reports 0 new rows because (show_id, song_id) already
    # exists.
    assert out2 == {"play_history_created": 1, "rel_show_song_created": 0}
    assert _row_count(tmp_app_root, "play_history") == ph_after_first + 1
    assert _row_count(tmp_app_root, "rel_show_song") == rel_after_first


# ---------------------------------------------------------------------------
# R14.2 — any missing id aborts the batch with NOT_FOUND, no partial writes
# ---------------------------------------------------------------------------


def test_missing_song_id_aborts_batch(
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

    triples = [
        {"song_id": song_id, "show_id": show_id, "media_url": "good"},
        {"song_id": "no-such-song", "show_id": show_id, "media_url": "bad"},
    ]
    triples_path = _write_triples(tmp_app_root, triples)

    before = _db_hash(tmp_app_root)
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"
    missing = err["error"]["details"]["missing"]
    assert any(m["kind"] == "song" and m["id"] == "no-such-song" for m in missing)
    assert _db_hash(tmp_app_root) == before


def test_soft_deleted_show_aborts_batch(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="A")
    song_id = insert_song(tmp_app_root, name="S", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Sh", vintage="", status=1)

    triples = [{"song_id": song_id, "show_id": show_id, "media_url": ""}]
    triples_path = _write_triples(tmp_app_root, triples)

    before = _db_hash(tmp_app_root)
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"
    assert _db_hash(tmp_app_root) == before


def test_soft_deleted_song_aborts_batch(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="A")
    song_id = insert_song(tmp_app_root, name="S", artist_id=artist_id, status=1)
    show_id = insert_show(tmp_app_root, name="Sh", vintage="")

    triples = [{"song_id": song_id, "show_id": show_id, "media_url": ""}]
    triples_path = _write_triples(tmp_app_root, triples)

    before = _db_hash(tmp_app_root)
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"
    assert _db_hash(tmp_app_root) == before


# ---------------------------------------------------------------------------
# R14.8 — standalone usage (hand-rolled triples, no plan / resolve)
# ---------------------------------------------------------------------------


def test_standalone_inline_triples(
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

    inline = json.dumps({"triples": [{"song_id": song_id, "show_id": show_id, "media_url": "u"}]})
    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, inline=inline)
    assert rc == 0, err
    assert out["play_history_created"] == 1
    assert out["rel_show_song_created"] == 1


# ---------------------------------------------------------------------------
# R14.6 — empty triples list emits {0, 0}
# ---------------------------------------------------------------------------


def test_empty_triples_list(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    triples_path = _write_triples(tmp_app_root, [])

    before = _db_hash(tmp_app_root)
    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc == 0, err
    assert out == {"play_history_created": 0, "rel_show_song_created": 0}
    assert _db_hash(tmp_app_root) == before


# ---------------------------------------------------------------------------
# R14.9 / Property 14 — song/artist/show tables are never touched
# ---------------------------------------------------------------------------


def test_song_artist_show_tables_untouched(
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

    triples = [{"song_id": song_id, "show_id": show_id, "media_url": "u"}]
    triples_path = _write_triples(tmp_app_root, triples)

    song_before = _table_snapshot(tmp_app_root, "song")
    artist_before = _table_snapshot(tmp_app_root, "artist")
    show_before = _table_snapshot(tmp_app_root, "show")

    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc == 0, err
    assert _table_snapshot(tmp_app_root, "song") == song_before
    assert _table_snapshot(tmp_app_root, "artist") == artist_before
    assert _table_snapshot(tmp_app_root, "show") == show_before


# ---------------------------------------------------------------------------
# R14.4 — every play_history row carries status=0, a fresh UUID, and the triple's media_url
# ---------------------------------------------------------------------------


def test_play_history_row_shape(
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

    triples = [{"song_id": song_id, "show_id": show_id, "media_url": "http://e"}]
    triples_path = _write_triples(tmp_app_root, triples)

    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc == 0, err
    rows = _table_snapshot(tmp_app_root, "play_history")
    assert len(rows) == 1
    row = rows[0]
    assert row["show_id"] == show_id
    assert row["song_id"] == song_id
    assert row["media_url"] == "http://e"
    assert row["status"] == 0
    assert row["created_at"] == pinned_now
    # UUID-ish — 36 chars with 4 dashes.
    assert len(row["id"]) == 36
    assert row["id"].count("-") == 4


# ---------------------------------------------------------------------------
# R14.4 — default media_url to empty string when missing
# ---------------------------------------------------------------------------


def test_missing_media_url_defaults_to_empty(
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

    triples = [{"song_id": song_id, "show_id": show_id}]  # no media_url
    triples_path = _write_triples(tmp_app_root, triples)

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, triples_path)
    assert rc == 0, err
    assert out["play_history_created"] == 1
    rows = _table_snapshot(tmp_app_root, "play_history")
    assert rows[0]["media_url"] == ""


# ---------------------------------------------------------------------------
# Argparse — --input and --triples are mutually exclusive and required
# ---------------------------------------------------------------------------


def test_no_input_source_fails(
    tmp_app_root,
    call_script,
) -> None:
    # argparse itself rejects this: required=True on the mutually
    # exclusive group. Exit code 2 from argparse.
    rc, _out, _err = call_script(
        "add_play_history.py",
        "--",
        cwd=tmp_app_root,
    )
    # argparse's default error exit code is 2; any non-zero is fine.
    assert rc != 0


def test_missing_input_file_emits_invalid_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        input_path=str(tmp_app_root / "no-such-triples.json"),
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_non_json_input_emits_invalid_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    bad = tmp_app_root / "bad.json"
    bad.write_text("nope not json", encoding="utf-8")
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, input_path=str(bad))
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"
