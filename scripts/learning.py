"""Learning-record lifecycle for the local review flow.

Five subcommands (see requirements.md R6, R7, R17):
    batch     - add songs to the review queue
    levelup   - advance review level, or graduate at MAX_LEVEL
    graduate  - mark one or more records done
    due       - rows that are ready for review now (Due_SQL_Condition)
    stats     - counts by level and graduated flag

Write subcommands (``batch``, ``levelup``, ``graduate``) run inside one
``BEGIN IMMEDIATE`` / ``COMMIT``. The read-only ops (``due``, ``stats``)
skip the transaction wrapper.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from typing import Any

# See design.md "Importing the shared module".
_REPO_ROOT = str(pathlib.Path(__file__).absolute().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts import _common  # noqa: E402

# ---------------------------------------------------------------------------
# argparse setup
# ---------------------------------------------------------------------------

_WRITE_CMDS = ("batch", "levelup", "graduate")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="learning.py",
        description="Manage learning records (the review queue).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("batch", help="Add songs to the review queue.")
    b.add_argument("--song-ids", dest="song_ids", required=True, help="Comma-separated.")

    lu = sub.add_parser("levelup", help="Advance level (or graduate) for one or more records.")
    lu.add_argument("--ids", required=True, help="Comma-separated learning ids.")

    g = sub.add_parser("graduate", help="Mark one or more records as graduated.")
    g.add_argument("--ids", required=True, help="Comma-separated learning ids.")

    d = sub.add_parser("due", help="Records that are ready for review.")
    d.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Shift the 'now' comparison forward by N seconds (default 0).",
    )

    sub.add_parser("stats", help="Counts by level and graduated flag.")

    return p


def _csv(s: str) -> list[str]:
    return [x for x in (p.strip() for p in s.split(",")) if x]


# ---------------------------------------------------------------------------
# batch
# ---------------------------------------------------------------------------


def _cmd_batch(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Per R6.1-R6.4 and R15.2.

    For each song_id:
      * missing or soft-deleted song -> ``not_found``.
      * any existing learning row has ``graduated = 0`` -> ``skipped``.
      * every existing learning row is graduated -> insert at RE_LEARN_LEVEL (7).
      * no learning rows exist yet -> insert at level 0.
    """
    song_ids = _csv(args.song_ids)
    now = _common.now_epoch()
    level_up_path_json = json.dumps(_common.DEFAULT_LEVEL_UP_PATH)

    inserted: list[dict[str, Any]] = []
    skipped: list[str] = []
    not_found: list[str] = []

    for song_id in song_ids:
        song = _common.get_row(conn, "song", song_id)
        if song is None:
            not_found.append(song_id)
            continue

        existing = conn.execute(
            "SELECT graduated FROM learning WHERE song_id = ?", (song_id,)
        ).fetchall()

        if any(row["graduated"] == 0 for row in existing):
            skipped.append(song_id)
            continue

        level = _common.RE_LEARN_LEVEL if existing else 0
        new_id = _common.new_uuid()
        conn.execute(
            "INSERT INTO learning (id, song_id, level, created_at, updated_at, "
            "last_level_up_at, level_up_path, graduated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (new_id, song_id, level, now, now, now, level_up_path_json),
        )
        inserted.append(
            {
                "id": new_id,
                "song_id": song_id,
                "level": level,
                "display_level": level + 1,
                "graduated": 0,
                "created_at": now,
                "updated_at": now,
                "last_level_up_at": now,
            }
        )

    _common.success({"inserted": inserted, "skipped": skipped, "not_found": not_found})


# ---------------------------------------------------------------------------
# levelup
# ---------------------------------------------------------------------------


def _cmd_levelup(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Per R6.5-R6.7.

    Preflights:
      * Any missing id -> ``NOT_FOUND`` (abort, no writes).
      * Any graduated id -> ``ALREADY_GRADUATED`` (abort, no writes).

    Then for each row: if level < MAX_LEVEL, bump level and set
    last_level_up_at. Else, set graduated = 1 (level and last_level_up_at
    stay put per R6.6).
    """
    ids = _csv(args.ids)
    if not ids:
        _common.success({"updated": []})
        return

    placeholders = ",".join(["?"] * len(ids))
    rows = {
        r["id"]: dict(r)
        for r in conn.execute(
            f"SELECT * FROM learning WHERE id IN ({placeholders})", ids
        ).fetchall()
    }

    missing = [i for i in ids if i not in rows]
    if missing:
        raise _common.KnownError(
            "NOT_FOUND",
            f"{len(missing)} learning id(s) not found",
            {"ids": missing},
        )

    graduated_ids = [i for i in ids if rows[i]["graduated"] == 1]
    if graduated_ids:
        raise _common.KnownError(
            "ALREADY_GRADUATED",
            f"{len(graduated_ids)} learning id(s) already graduated",
            {"ids": graduated_ids},
        )

    now = _common.now_epoch()
    updated: list[dict[str, Any]] = []
    for lid in ids:
        row = rows[lid]
        if row["level"] < _common.MAX_LEVEL:
            new_level = row["level"] + 1
            conn.execute(
                "UPDATE learning SET level = ?, last_level_up_at = ?, updated_at = ? WHERE id = ?",
                (new_level, now, now, lid),
            )
            updated.append(
                {
                    "id": lid,
                    "level": new_level,
                    "display_level": new_level + 1,
                    "graduated": 0,
                    "last_level_up_at": now,
                    "updated_at": now,
                }
            )
        else:
            # Already at MAX_LEVEL → graduate. level and last_level_up_at
            # stay put per R6.6.
            conn.execute(
                "UPDATE learning SET graduated = 1, updated_at = ? WHERE id = ?",
                (now, lid),
            )
            updated.append(
                {
                    "id": lid,
                    "level": row["level"],
                    "display_level": row["level"] + 1,
                    "graduated": 1,
                    "last_level_up_at": row["last_level_up_at"],
                    "updated_at": now,
                }
            )

    _common.success({"updated": updated})


# ---------------------------------------------------------------------------
# graduate
# ---------------------------------------------------------------------------


def _cmd_graduate(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Per R6.8-R6.9.

    * Missing id -> ``NOT_FOUND`` (abort).
    * Already-graduated id -> no-op success (R6.9).

    Returns ``display_level`` per R17.1.
    """
    ids = _csv(args.ids)
    if not ids:
        _common.success({"updated": []})
        return

    placeholders = ",".join(["?"] * len(ids))
    rows = {
        r["id"]: dict(r)
        for r in conn.execute(
            f"SELECT * FROM learning WHERE id IN ({placeholders})", ids
        ).fetchall()
    }
    missing = [i for i in ids if i not in rows]
    if missing:
        raise _common.KnownError(
            "NOT_FOUND",
            f"{len(missing)} learning id(s) not found",
            {"ids": missing},
        )

    now = _common.now_epoch()
    updated: list[dict[str, Any]] = []
    for lid in ids:
        row = rows[lid]
        if row["graduated"] == 1:
            # No-op success per R6.9 — return the row's existing state.
            updated.append(
                {
                    "id": lid,
                    "level": row["level"],
                    "display_level": row["level"] + 1,
                    "graduated": 1,
                    "updated_at": row["updated_at"],
                }
            )
            continue
        conn.execute(
            "UPDATE learning SET graduated = 1, updated_at = ? WHERE id = ?",
            (now, lid),
        )
        updated.append(
            {
                "id": lid,
                "level": row["level"],
                "display_level": row["level"] + 1,
                "graduated": 1,
                "updated_at": now,
            }
        )

    _common.success({"updated": updated})


# ---------------------------------------------------------------------------
# due
# ---------------------------------------------------------------------------

_DUE_SQL = """
SELECT
    l.id,
    l.song_id,
    s.name AS song_name,
    l.level,
    (l.level + 1) AS display_level,
    COALESCE(json_extract(l.level_up_path, '$[' || l.level || ']'), 0) AS wait_days,
    l.last_level_up_at,
    l.updated_at,
    l.graduated
FROM learning l
JOIN song s ON s.id = l.song_id
WHERE s.status = 0
  AND l.graduated = 0
  AND (
      (l.last_level_up_at > 0 AND l.level = 0
       AND (CAST(strftime('%s', 'now') AS INTEGER) + :offset)
           >= (l.last_level_up_at + 300))
      OR
      (l.last_level_up_at = 0 AND l.level = 0
       AND (CAST(strftime('%s', 'now') AS INTEGER) + :offset)
           >= (l.updated_at + 300))
      OR
      (l.level > 0
       AND (json_extract(l.level_up_path, '$[' || l.level || ']') * 86400
            + l.last_level_up_at)
           <= (CAST(strftime('%s', 'now') AS INTEGER) + :offset))
  )
ORDER BY l.level DESC, l.id ASC
"""


def _cmd_due(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Per R7.1-R7.7: run Due_SQL_Condition exactly as written."""
    cur = conn.execute(_DUE_SQL, {"offset": int(args.offset)})
    rows = [dict(r) for r in cur.fetchall()]
    _common.success({"results": rows, "offset": int(args.offset)})


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def _cmd_stats(conn: sqlite3.Connection, _args: argparse.Namespace) -> None:
    """Per R6.10: counts by level and by graduated, song.status = 0 only."""
    by_level: dict[str, int] = {}
    by_graduated = {"0": 0, "1": 0}
    total = 0
    cur = conn.execute(
        "SELECT l.level, l.graduated, COUNT(*) AS c "
        "FROM learning l JOIN song s ON s.id = l.song_id "
        "WHERE s.status = 0 "
        "GROUP BY l.level, l.graduated"
    )
    for row in cur.fetchall():
        level_key = str(row["level"])
        by_level[level_key] = by_level.get(level_key, 0) + row["c"]
        by_graduated[str(row["graduated"])] += row["c"]
        total += row["c"]

    _common.success({"by_level": by_level, "by_graduated": by_graduated, "total": total})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_DISPATCH = {
    "batch": _cmd_batch,
    "levelup": _cmd_levelup,
    "graduate": _cmd_graduate,
    "due": _cmd_due,
    "stats": _cmd_stats,
}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    conn = _common.open_db(__file__)
    try:
        if args.cmd in _WRITE_CMDS:
            # Same transaction pattern as data.py: handlers end by
            # calling success() which raises SystemExit(0). Catch that
            # to commit; roll back on any other exception.
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
                conn.execute("COMMIT")
        else:
            # Read-only ops: no transaction needed.
            _DISPATCH[args.cmd](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _build_parser().print_help()
        sys.exit(0)
    _common.run(main)
