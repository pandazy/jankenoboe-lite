"""Hard-delete soft-deleted rows older than a cutoff.

``cleanup.py --before EPOCH_SECONDS`` is a dry-run by default. Pass
``--confirm`` to actually execute the deletes.

See requirements.md R11 and design.md "Cleanup" for the algorithm.
Only ``song``/``artist``/``show`` rows with ``status = 1 AND
updated_at <= T`` are targets. Dependents in ``rel_show_song``,
``play_history``, and ``learning`` are removed alongside their targets.

Artist -> song relationships are NOT followed: a live song under a
soft-deleted artist stays. The operator must soft-delete that song
first (usually via ``data.py delete --kind artist``).

This is the only script allowed to hard-delete rows from
``song``/``artist``/``show``/``play_history``/``learning`` (R11.11).
"""

from __future__ import annotations

import argparse
import datetime
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
# argparse
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cleanup.py",
        description=(
            "Hard-delete soft-deleted rows older than a cutoff. Dry-run "
            "by default; use --confirm to execute."
        ),
    )
    p.add_argument(
        "--before",
        type=str,
        required=False,
        default=None,
        help=(
            "UNIX epoch seconds (UTC). Rows with status = 1 AND "
            "updated_at <= this value are deleted. Must be a positive integer."
        ),
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help="Actually execute the deletes. Without this flag, cleanup.py is a dry-run.",
    )
    return p


# ---------------------------------------------------------------------------
# Target selection + cascade analysis
# ---------------------------------------------------------------------------


def _target_ids(conn: sqlite3.Connection, table: str, cutoff: int) -> list[str]:
    """Ids of soft-deleted rows older than the cutoff for one kind.

    Only ``song``/``artist``/``show`` are eligible. ``status = 1 AND
    updated_at <= T`` (R11.2).
    """
    cur = conn.execute(
        f"SELECT id FROM {table} WHERE status = 1 AND updated_at <= ?",
        (cutoff,),
    )
    return [row[0] for row in cur.fetchall()]


def _cascade_counts(
    conn: sqlite3.Connection,
    target_song: list[str],
    target_show: list[str],
) -> dict[str, int]:
    """Count dependent rows that would be cascade-deleted per table (R11.5).

    * ``rel_show_song``: rows with ``song_id`` or ``show_id`` in targets.
    * ``play_history``: rows with ``song_id`` or ``show_id`` in targets.
    * ``learning``: rows with ``song_id`` in ``target_song``.

    Per R11.3 we do NOT follow ``artist -> songs``. A live song under a
    soft-deleted artist is left alone. Only soft-deleted songs in
    ``target_song`` contribute to the cascade.
    """
    counts = {"rel_show_song": 0, "play_history": 0, "learning": 0}
    if target_song:
        sp = _ph(len(target_song))
        counts["learning"] += conn.execute(
            f"SELECT COUNT(*) FROM learning WHERE song_id IN ({sp})",
            target_song,
        ).fetchone()[0]
    counts["rel_show_song"] = _count_with_song_or_show(
        conn, "rel_show_song", target_song, target_show
    )
    counts["play_history"] = _count_with_song_or_show(
        conn, "play_history", target_song, target_show
    )
    return counts


def _count_with_song_or_show(
    conn: sqlite3.Connection,
    table: str,
    target_song: list[str],
    target_show: list[str],
) -> int:
    """``SELECT COUNT(*) FROM <table> WHERE song_id IN (...) OR show_id IN (...)``."""
    clauses: list[str] = []
    params: list[str] = []
    if target_song:
        clauses.append(f"song_id IN ({_ph(len(target_song))})")
        params.extend(target_song)
    if target_show:
        clauses.append(f"show_id IN ({_ph(len(target_show))})")
        params.extend(target_show)
    if not clauses:
        return 0
    where = " OR ".join(clauses)
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}",
            params,
        ).fetchone()[0]
    )


def _ph(n: int) -> str:
    """Comma-joined ``?`` placeholders for an ``IN`` clause."""
    return ",".join(["?"] * n)


def _oldest_newest(
    conn: sqlite3.Connection,
    target_song: list[str],
    target_artist: list[str],
    target_show: list[str],
) -> tuple[int | None, int | None]:
    """MIN/MAX ``updated_at`` across every target row (R11.5).

    Returns ``(None, None)`` when nothing is targeted.
    """
    parts: list[str] = []
    params: list[str] = []
    for table, ids in (("song", target_song), ("artist", target_artist), ("show", target_show)):
        if not ids:
            continue
        parts.append(f"SELECT updated_at FROM {table} WHERE id IN ({_ph(len(ids))})")
        params.extend(ids)
    if not parts:
        return (None, None)
    union = " UNION ALL ".join(parts)
    row = conn.execute(f"SELECT MIN(updated_at), MAX(updated_at) FROM ({union})", params).fetchone()
    return (row[0], row[1])


def _top_cascade_samples(
    conn: sqlite3.Connection,
    target_song: list[str],
    target_artist: list[str],
    target_show: list[str],
) -> list[dict[str, Any]]:
    """Top 10 target rows by dependent footprint (R11.5).

    Each entry carries ``kind``, ``id``, ``name``, and per-table cascade
    counts (``rel_show_song``, ``play_history``, ``learning``). Ordered
    by total footprint DESC, then kind, then id.
    """
    samples: list[dict[str, Any]] = []

    # song targets: all three dependent tables apply.
    for sid in target_song:
        row = conn.execute("SELECT name FROM song WHERE id = ?", (sid,)).fetchone()
        name = row[0] if row else ""
        rss = conn.execute(
            "SELECT COUNT(*) FROM rel_show_song WHERE song_id = ?", (sid,)
        ).fetchone()[0]
        ph = conn.execute("SELECT COUNT(*) FROM play_history WHERE song_id = ?", (sid,)).fetchone()[
            0
        ]
        learn = conn.execute("SELECT COUNT(*) FROM learning WHERE song_id = ?", (sid,)).fetchone()[
            0
        ]
        samples.append(
            {
                "kind": "song",
                "id": sid,
                "name": name,
                "rel_show_song": rss,
                "play_history": ph,
                "learning": learn,
            }
        )

    # show targets: rel_show_song + play_history only (not learning).
    for shid in target_show:
        row = conn.execute("SELECT name FROM show WHERE id = ?", (shid,)).fetchone()
        name = row[0] if row else ""
        rss = conn.execute(
            "SELECT COUNT(*) FROM rel_show_song WHERE show_id = ?", (shid,)
        ).fetchone()[0]
        ph = conn.execute(
            "SELECT COUNT(*) FROM play_history WHERE show_id = ?", (shid,)
        ).fetchone()[0]
        samples.append(
            {
                "kind": "show",
                "id": shid,
                "name": name,
                "rel_show_song": rss,
                "play_history": ph,
                "learning": 0,
            }
        )

    # artist targets: no dependents follow per R11.3 — artist deletion
    # doesn't cascade through live songs. Keep them in the sample list
    # with zero counts so the operator sees them anyway.
    for aid in target_artist:
        row = conn.execute("SELECT name FROM artist WHERE id = ?", (aid,)).fetchone()
        name = row[0] if row else ""
        samples.append(
            {
                "kind": "artist",
                "id": aid,
                "name": name,
                "rel_show_song": 0,
                "play_history": 0,
                "learning": 0,
            }
        )

    samples.sort(
        key=lambda s: (
            -(int(s["rel_show_song"]) + int(s["play_history"]) + int(s["learning"])),
            str(s["kind"]),
            str(s["id"]),
        )
    )
    return samples[:10]


# ---------------------------------------------------------------------------
# Dry-run + confirmed envelopes
# ---------------------------------------------------------------------------


def _build_envelope(
    cutoff: int,
    target_song: list[str],
    target_artist: list[str],
    target_show: list[str],
    cascade_counts: dict[str, int],
    oldest: int | None,
    newest: int | None,
    samples: list[dict[str, Any]],
    *,
    executed: bool,
    hard_deleted: dict[str, int] | None = None,
) -> dict[str, Any]:
    target_counts = {
        "song": len(target_song),
        "artist": len(target_artist),
        "show": len(target_show),
    }
    total = (
        target_counts["song"]
        + target_counts["artist"]
        + target_counts["show"]
        + cascade_counts["rel_show_song"]
        + cascade_counts["play_history"]
        + cascade_counts["learning"]
    )
    envelope: dict[str, Any] = {
        "cutoff_epoch": cutoff,
        "cutoff_iso_utc": _iso_utc(cutoff),
        "target_counts": target_counts,
        "cascade_counts": cascade_counts,
        "oldest_candidate_updated_at": oldest,
        "newest_candidate_updated_at": newest,
        "top_cascade_samples": samples,
        "total_rows_to_hard_delete": total,
        "executed": executed,
    }
    if hard_deleted is not None:
        envelope["hard_deleted_counts"] = hard_deleted
    return envelope


def _iso_utc(epoch: int) -> str:
    """Format an integer epoch as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC)."""
    dt = datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Delete path (only when --confirm is set)
# ---------------------------------------------------------------------------


def _execute_deletes(
    conn: sqlite3.Connection,
    target_song: list[str],
    target_artist: list[str],
    target_show: list[str],
) -> dict[str, int]:
    """Run the deletes in order (R11.7) and return hard_deleted_counts.

    Order: dependents first, then the target rows themselves. Using
    ``cursor.rowcount`` after each statement gives honest counts even when
    FK cascades run in the background.
    """
    counts: dict[str, int] = {
        "song": 0,
        "artist": 0,
        "show": 0,
        "rel_show_song": 0,
        "play_history": 0,
        "learning": 0,
    }

    # play_history: by song or show target.
    counts["play_history"] = _delete_with_song_or_show(
        conn, "play_history", target_song, target_show
    )
    # learning: by song target only.
    if target_song:
        cur = conn.execute(
            f"DELETE FROM learning WHERE song_id IN ({_ph(len(target_song))})",
            target_song,
        )
        counts["learning"] = cur.rowcount
    # rel_show_song: by song or show target.
    counts["rel_show_song"] = _delete_with_song_or_show(
        conn, "rel_show_song", target_song, target_show
    )
    # target rows themselves.
    if target_song:
        cur = conn.execute(
            f"DELETE FROM song WHERE id IN ({_ph(len(target_song))})",
            target_song,
        )
        counts["song"] = cur.rowcount
    if target_show:
        cur = conn.execute(
            f"DELETE FROM show WHERE id IN ({_ph(len(target_show))})",
            target_show,
        )
        counts["show"] = cur.rowcount
    if target_artist:
        cur = conn.execute(
            f"DELETE FROM artist WHERE id IN ({_ph(len(target_artist))})",
            target_artist,
        )
        counts["artist"] = cur.rowcount
    return counts


def _delete_with_song_or_show(
    conn: sqlite3.Connection,
    table: str,
    target_song: list[str],
    target_show: list[str],
) -> int:
    """``DELETE FROM <table> WHERE song_id IN (...) OR show_id IN (...)``."""
    clauses: list[str] = []
    params: list[str] = []
    if target_song:
        clauses.append(f"song_id IN ({_ph(len(target_song))})")
        params.extend(target_song)
    if target_show:
        clauses.append(f"show_id IN ({_ph(len(target_show))})")
        params.extend(target_show)
    if not clauses:
        return 0
    where = " OR ".join(clauses)
    cur = conn.execute(
        f"DELETE FROM {table} WHERE {where}",
        params,
    )
    return int(cur.rowcount)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _parse_before(raw: str | None) -> int:
    """Require a positive integer epoch (R11.1, R11.10)."""
    if raw is None:
        raise _common.KnownError(
            "INVALID_INPUT",
            "--before is required (UNIX epoch seconds, positive integer)",
        )
    try:
        value = int(raw)
    except (TypeError, ValueError) as e:
        raise _common.KnownError(
            "INVALID_INPUT",
            f"--before must be a positive integer: {raw!r}",
        ) from e
    if value <= 0:
        raise _common.KnownError(
            "INVALID_INPUT",
            f"--before must be positive, got {value}",
        )
    return value


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = _build_parser().parse_args()
    cutoff = _parse_before(args.before)

    conn = _common.open_db(__file__)
    try:
        target_song = _target_ids(conn, "song", cutoff)
        target_artist = _target_ids(conn, "artist", cutoff)
        target_show = _target_ids(conn, "show", cutoff)

        cascade = _cascade_counts(conn, target_song, target_show)
        oldest, newest = _oldest_newest(conn, target_song, target_artist, target_show)
        samples = _top_cascade_samples(conn, target_song, target_artist, target_show)

        if not args.confirm:
            # Dry-run path (R11.4, R11.5, R11.6). No writes.
            _common.success(
                _build_envelope(
                    cutoff,
                    target_song,
                    target_artist,
                    target_show,
                    cascade,
                    oldest,
                    newest,
                    samples,
                    executed=False,
                )
            )
            return

        # --confirm path: one transaction (R11.7). Commits on success,
        # rolls back on any exception. Same pattern as data.py / learning.py.
        conn.execute("BEGIN IMMEDIATE")
        try:
            hard_deleted = _execute_deletes(conn, target_song, target_artist, target_show)
            envelope = _build_envelope(
                cutoff,
                target_song,
                target_artist,
                target_show,
                cascade,
                oldest,
                newest,
                samples,
                executed=True,
                hard_deleted=hard_deleted,
            )
            _common.success(envelope)
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
    # Note: we do NOT short-circuit on `len(sys.argv) == 1` because R11.1
    # requires cleanup.py to emit INVALID_INPUT (exit 1) when --before is
    # absent — including the "no args at all" case. --help still works via
    # argparse's -h/--help handling, which exits 0 before our logic runs.
    _common.run(main)
