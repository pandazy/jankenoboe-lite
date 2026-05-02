"""AMQ import — step 3 (add play history).

Take a list of ``(song_id, show_id, media_url)`` triples and write one
``play_history`` row per triple, plus upsert the corresponding
``rel_show_song`` row (idempotent on ``(show_id, song_id)``).

See requirements.md R14 and design.md "Import Resolve" / "Add Play
History".

This script works standalone too — an operator with triples on hand
can use it without ever running steps 1 and 2.

All writes run inside one ``BEGIN IMMEDIATE`` / ``COMMIT`` block. Any
missing or soft-deleted ``song_id`` / ``show_id`` aborts the whole
batch with ``NOT_FOUND`` and rolls back — no partial writes.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from typing import Any

# See design.md "Importing the shared module". absolute() (not resolve())
# keeps symlinked scripts/ dirs intact so the test harness works.
_REPO_ROOT = str(pathlib.Path(__file__).absolute().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts import _common  # noqa: E402

# ---------------------------------------------------------------------------
# argparse setup
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="add_play_history.py",
        description="Write play_history + rel_show_song rows from a list of triples.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--input",
        dest="input_path",
        help='Path to a JSON file with {"triples": [...]}.',
    )
    src.add_argument(
        "--triples",
        dest="inline_triples",
        help='Inline JSON: either a list of triples or {"triples": [...]}.',
    )
    return p


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def _load_triples(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.input_path:
        try:
            raw = pathlib.Path(args.input_path).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise _common.KnownError(
                "INVALID_INPUT",
                f"Input file not found: {args.input_path}",
                {"path": args.input_path},
            ) from exc
    else:
        raw = args.inline_triples

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _common.KnownError(
            "INVALID_INPUT",
            f"Input JSON is not parseable: {exc}",
            None,
        ) from exc

    if isinstance(obj, list):
        triples = obj
    elif isinstance(obj, dict):
        triples = obj.get("triples", [])
    else:
        raise _common.KnownError(
            "INVALID_INPUT",
            "Input must be an array of triples or an object with a 'triples' array.",
            None,
        )
    if not isinstance(triples, list):
        raise _common.KnownError(
            "INVALID_INPUT",
            "triples must be a JSON array.",
            None,
        )

    normalised: list[dict[str, Any]] = []
    for i, t in enumerate(triples):
        if not isinstance(t, dict):
            raise _common.KnownError(
                "INVALID_INPUT",
                f"Triple at index {i} is not a JSON object.",
                {"index": i},
            )
        normalised.append(
            {
                "song_id": str(t.get("song_id", "")),
                "show_id": str(t.get("show_id", "")),
                "media_url": str(t.get("media_url", "") or ""),
            }
        )
    return normalised


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def _preflight(
    conn: sqlite3.Connection,
    triples: list[dict[str, Any]],
) -> None:
    """R14.2 — every song_id and show_id must be live (status = 0).

    Collect every miss into a single error payload and abort.
    """
    missing: list[dict[str, Any]] = []
    # Dedup ids so we only hit the DB once per id.
    song_ids = {t["song_id"] for t in triples}
    show_ids = {t["show_id"] for t in triples}

    live_songs: set[str] = set()
    for sid in song_ids:
        if not sid:
            continue
            # Empty ids get handled below in the per-triple loop.
        row = conn.execute(
            "SELECT id FROM song WHERE id = ? AND status = 0",
            (sid,),
        ).fetchone()
        if row is not None:
            live_songs.add(sid)

    live_shows: set[str] = set()
    for sid in show_ids:
        if not sid:
            continue
        row = conn.execute(
            "SELECT id FROM show WHERE id = ? AND status = 0",
            (sid,),
        ).fetchone()
        if row is not None:
            live_shows.add(sid)

    for i, t in enumerate(triples):
        if not t["song_id"] or t["song_id"] not in live_songs:
            missing.append({"index": i, "kind": "song", "id": t["song_id"]})
        if not t["show_id"] or t["show_id"] not in live_shows:
            missing.append({"index": i, "kind": "show", "id": t["show_id"]})

    if missing:
        raise _common.KnownError(
            "NOT_FOUND",
            f"{len(missing)} triple reference(s) point at missing or soft-deleted rows.",
            {"missing": missing},
        )


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def _run_add(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    triples = _load_triples(args)
    if not triples:
        _common.success({"play_history_created": 0, "rel_show_song_created": 0})
        return

    _preflight(conn, triples)

    now = _common.now_epoch()
    rel_created = 0
    ph_created = 0

    for t in triples:
        # R14.3 — upsert rel_show_song. INSERT OR IGNORE keeps the
        # existing row (with its original created_at and media_url).
        cur = conn.execute(
            "INSERT OR IGNORE INTO rel_show_song(show_id, song_id, media_url, created_at) "
            "VALUES (?, ?, ?, ?)",
            (t["show_id"], t["song_id"], t["media_url"], now),
        )
        rel_created += cur.rowcount

        # R14.4 — insert one play_history row, always. No dedup.
        conn.execute(
            "INSERT INTO play_history(id, show_id, song_id, created_at, media_url, status) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (_common.new_uuid(), t["show_id"], t["song_id"], now, t["media_url"]),
        )
        ph_created += 1

    _common.success(
        {
            "play_history_created": ph_created,
            "rel_show_song_created": rel_created,
        }
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    conn = _common.open_db(__file__)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _run_add(conn, args)
        except SystemExit as exc:
            if (exc.code or 0) == 0:
                conn.execute("COMMIT")
            else:
                conn.execute("ROLLBACK")
            raise
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _build_parser().print_help()
        sys.exit(0)
    _common.run(main)
