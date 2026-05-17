"""One focused test per error code from R3.3.

Each test asserts:
  * exit code is 1.
  * stderr parses as JSON and its ``error.code`` matches the expected
    code string exactly.

See requirements.md R3.3. Error codes covered:

  * ``DB_NOT_FOUND``           — the DB file is missing.
  * ``SCHEMA_MISMATCH``        — the DB file exists with a broken schema.
  * ``INVALID_INPUT``          — bad flag / missing required flag / rejected column.
  * ``NOT_FOUND``              — query a missing id / bulk-reassign to a ghost.
  * ``CONSTRAINT_VIOLATION``   — create a duplicate rel_show_song pair.
  * ``SONG_INVARIANT_VIOLATION`` — import_plan sees two same-name live songs under one artist.
  * ``ALREADY_GRADUATED``      — learning.py levelup on a graduated row.
  * ``INVALID_ANSWER``         — import_resolve with a choose_artist_id not in candidates.
  * ``INTERNAL_ERROR``         — an unexpected exception bubbles up through ``_common.run``.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys


def _parse_err(err: str) -> dict:
    assert err.strip(), "Expected a non-empty stderr with a JSON error envelope."
    return json.loads(err)


# ---------------------------------------------------------------------------
# DB_NOT_FOUND
# ---------------------------------------------------------------------------


def test_db_not_found(tmp_app_root, call_script) -> None:
    # Remove the temp DB so open_db raises DB_NOT_FOUND.
    (tmp_app_root / "db" / "datasource.db").unlink()
    rc, _out, err = call_script(
        "query.py",
        "get",
        "--kind",
        "song",
        "--id",
        "00000000-0000-0000-0000-000000000000",
        cwd=tmp_app_root,
    )
    assert rc == 1
    assert _parse_err(err)["error"]["code"] == "DB_NOT_FOUND"


# ---------------------------------------------------------------------------
# SCHEMA_MISMATCH
# ---------------------------------------------------------------------------


def test_schema_mismatch(tmp_app_root, call_script) -> None:
    """Replace the DB with a truncated schema (no ``song`` table)."""
    import sqlite3  # noqa: PLC0415 — only this test seeds a bad schema directly.

    db_path = tmp_app_root / "db" / "datasource.db"
    db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        # Intentionally empty — every expected table is "missing".
        conn.executescript("CREATE TABLE dummy (x INTEGER);")
    finally:
        conn.close()

    rc, _out, err = call_script(
        "query.py",
        "get",
        "--kind",
        "song",
        "--id",
        "00000000-0000-0000-0000-000000000000",
        cwd=tmp_app_root,
    )
    assert rc == 1
    parsed = _parse_err(err)
    assert parsed["error"]["code"] == "SCHEMA_MISMATCH"
    details = parsed["error"]["details"]
    assert "missing_tables" in details


# ---------------------------------------------------------------------------
# INVALID_INPUT
# ---------------------------------------------------------------------------


def test_invalid_input_update_rejects_id_change(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="A")
    rc, _out, err = pinned_call(
        "data.py",
        "update",
        "--kind",
        "artist",
        "--id",
        artist_id,
        "--data",
        json.dumps({"id": "new-id"}),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert _parse_err(err)["error"]["code"] == "INVALID_INPUT"


def test_invalid_input_cleanup_without_before(tmp_app_root, call_script) -> None:
    rc, _out, err = call_script("cleanup.py", cwd=tmp_app_root)
    assert rc == 1
    assert _parse_err(err)["error"]["code"] == "INVALID_INPUT"


def test_invalid_input_merge_empty_sources(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
) -> None:
    target = insert_artist(tmp_app_root, name="T")
    rc, _out, err = pinned_call(
        "merge_artists.py",
        "--target-artist-id",
        target,
        "--source-artist-ids",
        "",
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert _parse_err(err)["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# NOT_FOUND
# ---------------------------------------------------------------------------


def test_not_found_query_get(tmp_app_root, call_script) -> None:
    rc, _out, err = call_script(
        "query.py",
        "get",
        "--kind",
        "song",
        "--id",
        "no-such-song",
        cwd=tmp_app_root,
    )
    assert rc == 1
    assert _parse_err(err)["error"]["code"] == "NOT_FOUND"


def test_not_found_bulk_reassign_missing_target(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
) -> None:
    src = insert_artist(tmp_app_root, name="S")
    rc, _out, err = pinned_call(
        "data.py",
        "bulk-reassign",
        "--from-artist-id",
        src,
        "--to-artist-id",
        "no-such-target",
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert _parse_err(err)["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# CONSTRAINT_VIOLATION
# ---------------------------------------------------------------------------


def test_constraint_violation_duplicate_rel(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Sh", vintage="")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="")

    rc, _out, err = pinned_call(
        "data.py",
        "create",
        "--kind",
        "rel_show_song",
        "--data",
        json.dumps({"show_id": shid, "song_id": sid, "media_url": ""}),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert _parse_err(err)["error"]["code"] == "CONSTRAINT_VIOLATION"


# ---------------------------------------------------------------------------
# SONG_INVARIANT_VIOLATION
# ---------------------------------------------------------------------------


def test_song_invariant_violation(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    insert_song(tmp_app_root, name="Dup", artist_id=aid)
    insert_song(tmp_app_root, name="Dup", artist_id=aid)

    amq = tmp_app_root / "amq.json"
    amq.write_text(
        json.dumps(
            [
                {
                    "artist_name": "A",
                    "song_name": "Dup",
                    "show_name": "",
                    "show_name_romaji": "Dup Romaji",
                    "vintage": "",
                    "media_url": "",
                }
            ]
        )
    )
    rc, _out, err = pinned_call(
        "import_plan.py",
        "--input",
        str(amq),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert _parse_err(err)["error"]["code"] == "SONG_INVARIANT_VIOLATION"


# ---------------------------------------------------------------------------
# ALREADY_GRADUATED
# ---------------------------------------------------------------------------


def test_already_graduated(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(tmp_app_root, song_id=sid, level=5, graduated=1)

    rc, _out, err = pinned_call(
        "learning.py",
        "levelup",
        "--ids",
        lid,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert _parse_err(err)["error"]["code"] == "ALREADY_GRADUATED"


# ---------------------------------------------------------------------------
# INVALID_ANSWER
# ---------------------------------------------------------------------------


def test_invalid_answer(
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
                "song_name": "Pick Me",
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
    plan_path = tmp_app_root / "plan.json"
    plan_path.write_text(json.dumps(plan))
    answers_path = tmp_app_root / "answers.json"
    answers_path.write_text(json.dumps({"0": {"choose_artist_id": "not-a-candidate"}}))

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
    assert _parse_err(err)["error"]["code"] == "INVALID_ANSWER"


# ---------------------------------------------------------------------------
# INTERNAL_ERROR
# ---------------------------------------------------------------------------


def test_internal_error_maps_unexpected_exception(tmp_path) -> None:
    """A script whose ``main()`` raises a plain exception gets wrapped by
    ``_common.run(main)`` into an INTERNAL_ERROR envelope with exit 1.

    We can't patch the real scripts at subprocess boundary, so we spin
    up a tiny standalone script that imports ``scripts._common`` and
    runs a main that explodes.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]

    # Put the helper outside cwd to avoid stepping on anything.
    helper = tmp_path / "boom.py"
    helper.write_text(
        "import sys, pathlib\n"
        f"sys.path.insert(0, {str(repo_root)!r})\n"
        "from scripts import _common\n"
        "def main():\n"
        "    raise ValueError('unexpected boom')\n"
        "if __name__ == '__main__':\n"
        "    _common.run(main)\n"
    )

    result = subprocess.run(
        [sys.executable, str(helper)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={**os.environ},
        check=False,
    )
    assert result.returncode == 1
    parsed = _parse_err(result.stderr)
    assert parsed["error"]["code"] == "INTERNAL_ERROR"
    # Plain message, no stack trace on stdout.
    assert result.stdout == ""
