"""Data management operations over ``db/datasource.db``.

Four subcommands (see requirements.md R9, R15):
    create  - insert a song/artist/show/rel_show_song
    update  - patch an existing song/artist/show
    delete  - soft-delete a song/artist/show (artist cascades to its songs)
    bulk-reassign - move a set of songs from one artist to another

Every write runs inside one ``BEGIN IMMEDIATE`` / ``COMMIT`` block so
partial failures roll back cleanly. The rollback path is exercised by
integration tests (see Property 16).
"""

from __future__ import annotations

import argparse
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

_CREATE_KINDS = ("song", "artist", "show", "rel_show_song")
_UPDATE_DELETE_KINDS = ("song", "artist", "show")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="data.py",
        description="Create / update / delete / bulk-reassign rows.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # create
    c = sub.add_parser("create", help="Insert one row.")
    c.add_argument("--kind", choices=_CREATE_KINDS, required=True)
    c.add_argument("--data", required=True, help="JSON object with the new row's columns.")

    # update
    u = sub.add_parser("update", help="Patch an existing row.")
    u.add_argument("--kind", choices=_UPDATE_DELETE_KINDS, required=True)
    u.add_argument("--id", dest="row_id", required=True)
    u.add_argument("--data", required=True, help="JSON object of changed columns.")

    # delete (soft delete; artist cascades)
    d = sub.add_parser("delete", help="Soft-delete a row.")
    d.add_argument("--kind", choices=_UPDATE_DELETE_KINDS, required=True)
    d.add_argument("--id", dest="row_id", required=True)

    # bulk-reassign
    br = sub.add_parser(
        "bulk-reassign",
        help="Move songs from one artist to another.",
    )
    br.add_argument("--from-artist-id", dest="from_artist_id", required=True)
    br.add_argument("--to-artist-id", dest="to_artist_id", required=True)
    br.add_argument(
        "--song-ids",
        dest="song_ids",
        default="",
        help="Comma-separated song ids. If empty, every live song under --from-artist-id is moved.",
    )

    return p


def _csv(s: str) -> list[str]:
    return [x for x in (p.strip() for p in s.split(",")) if x]


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_create(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    data_raw = args.data
    payload = _common.parse_data_arg(data_raw)
    if not isinstance(payload, dict):
        raise _common.KnownError(
            "INVALID_INPUT",
            "--data must be a JSON object",
            {"got_type": type(payload).__name__},
        )
    # insert_row already raises CONSTRAINT_VIOLATION on UNIQUE errors
    # (see _common.insert_row). It fills in id / timestamps / status when
    # absent per R9.2/R9.3.
    row = _common.insert_row(conn, args.kind, payload)
    _common.success(row)


def _cmd_update(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    payload = _common.parse_data_arg(args.data)
    if not isinstance(payload, dict):
        raise _common.KnownError(
            "INVALID_INPUT",
            "--data must be a JSON object",
            {"got_type": type(payload).__name__},
        )
    # update_row enforces the id/created_at/status rejection (R9.6),
    # unknown-column rejection (R9.1 payload check), and the NOT_FOUND
    # case when the target is missing or soft-deleted (R5.3, R15.4).
    row = _common.update_row(conn, args.kind, args.row_id, payload)
    _common.success(row)


def _cmd_delete(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    kind = args.kind
    if kind == "artist":
        _delete_artist_cascade(conn, args.row_id)
    else:
        # song / show: flip status to 1 if live, no-op if already soft-
        # deleted or missing (R9.9).
        _common.soft_delete_row(conn, kind, args.row_id)
    # R9.9: every delete op returns success even when the target was
    # already soft-deleted or missing. Shape is small and consistent.
    _common.success({"kind": kind, "id": args.row_id, "deleted": True})


def _delete_artist_cascade(conn: sqlite3.Connection, artist_id: str) -> None:
    """Soft-delete an artist plus every live song it owns.

    Runs as two UPDATE statements inside the caller's transaction. If the
    artist is already soft-deleted (or missing), the op is a no-op per
    R9.9 — it still returns success.
    """
    now = _common.now_epoch()
    conn.execute(
        "UPDATE song SET status = 1, updated_at = ? WHERE artist_id = ? AND status = 0",
        (now, artist_id),
    )
    conn.execute(
        "UPDATE artist SET status = 1, updated_at = ? WHERE id = ? AND status = 0",
        (now, artist_id),
    )


def _cmd_bulk_reassign(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    # Preflight: target must exist with status = 0 (R9.12).
    target = _common.get_row(conn, "artist", args.to_artist_id)
    if target is None:
        raise _common.KnownError(
            "NOT_FOUND",
            "target artist not found or soft-deleted",
            {"kind": "artist", "id": args.to_artist_id},
        )

    now = _common.now_epoch()
    song_ids = _csv(args.song_ids)
    params: list[Any] = [args.to_artist_id, now, args.from_artist_id]
    sql = "UPDATE song SET artist_id = ?, updated_at = ? WHERE artist_id = ? AND status = 0"
    if song_ids:
        placeholders = ",".join(["?"] * len(song_ids))
        sql += f" AND id IN ({placeholders})"
        params.extend(song_ids)

    cur = conn.execute(sql, params)
    _common.success(
        {
            "from_artist_id": args.from_artist_id,
            "to_artist_id": args.to_artist_id,
            "songs_reassigned": cur.rowcount,
        }
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_DISPATCH = {
    "create": _cmd_create,
    "update": _cmd_update,
    "delete": _cmd_delete,
    "bulk-reassign": _cmd_bulk_reassign,
}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    conn = _common.open_db(__file__)
    try:
        # R9.13: every write runs inside one BEGIN IMMEDIATE / COMMIT.
        # Handlers end by calling _common.success(obj), which writes the
        # envelope and raises SystemExit(0). We catch that specifically to
        # commit before the exit propagates. Any other exception triggers
        # a rollback.
        conn.execute("BEGIN IMMEDIATE")
        try:
            _DISPATCH[args.cmd](conn, args)
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
            # Reached only if a handler ever returns without calling
            # success() — today none do, but this path commits for
            # future-proofing.
            conn.execute("COMMIT")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _build_parser().print_help()
        sys.exit(0)
    _common.run(main)
