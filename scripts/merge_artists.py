"""Fold two or more artists into one in a single run.

See requirements.md R10 and design.md "Artist Merge" for the algorithm.
All writes run inside one ``BEGIN IMMEDIATE`` / ``COMMIT`` block.

Steps (in order):
  1. Reassign: every live song under a source artist gets ``artist_id``
     flipped to the target (AT) and ``updated_at`` bumped.
  2. Find duplicate groups: live songs now under AT that share a name.
     For each group pick the winner by max ``(updated_at, created_at,
     id)`` DESC and mark the rest as losers.
  3. Redirect dependents per loser SL → winner SW:
       - ``play_history.song_id``: SL → SW (no rows removed).
       - ``learning.song_id``: SL → SW, bump ``updated_at`` only (other
         columns untouched per R10.6).
       - ``rel_show_song``: if (show_id, SW) exists, delete (show_id,
         SL) to keep UNIQUE; else update (show_id, SL) to (show_id, SW).
  4. Soft-delete every losing song.
  5. Soft-delete every source artist. AT is never touched.

Output: a Success_Envelope with every counter from R10.10.
"""

from __future__ import annotations

import argparse
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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="merge_artists.py",
        description="Merge one or more source artists into a target artist.",
    )
    p.add_argument(
        "--target-artist-id",
        dest="target_artist_id",
        required=True,
        help="The artist that stays. Must be live (status = 0).",
    )
    p.add_argument(
        "--source-artist-ids",
        dest="source_artist_ids",
        required=True,
        help="Comma-separated artist ids to merge into the target.",
    )
    return p


def _csv(s: str) -> list[str]:
    return [x for x in (part.strip() for part in s.split(",")) if x]


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------


def _preflight(conn: sqlite3.Connection, target: str, sources: list[str]) -> None:
    """Validate inputs per R10.2 and R10.3."""
    if not sources:
        raise _common.KnownError(
            "INVALID_INPUT",
            "--source-artist-ids must not be empty",
            None,
        )
    # Reject duplicates in the source list.
    if len(set(sources)) != len(sources):
        dupes = sorted({s for s in sources if sources.count(s) > 1})
        raise _common.KnownError(
            "INVALID_INPUT",
            "--source-artist-ids contains duplicates",
            {"duplicates": dupes},
        )
    # Reject target in the source list.
    if target in sources:
        raise _common.KnownError(
            "INVALID_INPUT",
            "--target-artist-id must not be in --source-artist-ids",
            {"target_artist_id": target},
        )

    # All ids (target + sources) must exist with status = 0.
    all_ids = [target, *sources]
    placeholders = ",".join(["?"] * len(all_ids))
    rows = conn.execute(
        f"SELECT id, status FROM artist WHERE id IN ({placeholders})",
        all_ids,
    ).fetchall()
    found = {r["id"]: r["status"] for r in rows}
    missing: list[str] = []
    soft_deleted: list[str] = []
    for artist_id in all_ids:
        if artist_id not in found:
            missing.append(artist_id)
        elif found[artist_id] != 0:
            soft_deleted.append(artist_id)
    if missing or soft_deleted:
        raise _common.KnownError(
            "NOT_FOUND",
            "one or more artist ids missing or soft-deleted",
            {"missing": missing, "soft_deleted": soft_deleted},
        )


# ---------------------------------------------------------------------------
# Step 1 — Reassign
# ---------------------------------------------------------------------------


def _step1_reassign(conn: sqlite3.Connection, target: str, sources: list[str], now: int) -> int:
    placeholders = ",".join(["?"] * len(sources))
    cur = conn.execute(
        f"UPDATE song SET artist_id = ?, updated_at = ? "
        f"WHERE artist_id IN ({placeholders}) AND status = 0",
        [target, now, *sources],
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Step 2 — Find duplicate groups + pick winners/losers
# ---------------------------------------------------------------------------


def _step2_find_duplicates(conn: sqlite3.Connection, target: str) -> list[tuple[str, list[str]]]:
    """Return a list of ``(winner_id, loser_ids)`` tuples for duplicate groups.

    Live ``(artist_id = target, name)`` groups with 2+ members; winner
    picked by the design's DESC order on ``(updated_at, created_at, id)``.
    """
    dup_names = conn.execute(
        "SELECT name FROM song "
        "WHERE artist_id = ? AND status = 0 "
        "GROUP BY name "
        "HAVING COUNT(*) >= 2 "
        "ORDER BY name",
        (target,),
    ).fetchall()

    groups: list[tuple[str, list[str]]] = []
    for row in dup_names:
        name = row["name"]
        members = conn.execute(
            "SELECT id, updated_at, created_at FROM song "
            "WHERE artist_id = ? AND name = ? AND status = 0 "
            "ORDER BY updated_at DESC, created_at DESC, id DESC",
            (target, name),
        ).fetchall()
        # First row is the winner. Remaining rows are losers.
        members_list = [dict(r) for r in members]
        winner = members_list[0]["id"]
        losers = [m["id"] for m in members_list[1:]]
        groups.append((winner, losers))
    return groups


# ---------------------------------------------------------------------------
# Step 3 — Redirect dependents
# ---------------------------------------------------------------------------


def _step3_redirect(conn: sqlite3.Connection, winner: str, loser: str, now: int) -> dict[str, int]:
    """Redirect dependents from one loser to its winner.

    Returns counts contributed by this loser (the caller aggregates).
    """
    out: dict[str, int] = {
        "play_history_redirected": 0,
        "learning_redirected": 0,
        "rel_show_song_redirected": 0,
        "rel_show_song_cascade_deleted": 0,
    }

    # play_history: straight-through redirect.
    cur = conn.execute(
        "UPDATE play_history SET song_id = ? WHERE song_id = ?",
        (winner, loser),
    )
    out["play_history_redirected"] = cur.rowcount

    # learning: redirect song_id + bump updated_at. Other columns stay.
    cur = conn.execute(
        "UPDATE learning SET song_id = ?, updated_at = ? WHERE song_id = ?",
        (winner, now, loser),
    )
    out["learning_redirected"] = cur.rowcount

    # rel_show_song: UNIQUE(show_id, song_id) means a collision on the
    # (show_id, winner) side must cascade-delete the loser link.
    loser_links = conn.execute(
        "SELECT show_id FROM rel_show_song WHERE song_id = ?",
        (loser,),
    ).fetchall()
    for link in loser_links:
        show_id = link["show_id"]
        exists = conn.execute(
            "SELECT 1 FROM rel_show_song WHERE show_id = ? AND song_id = ?",
            (show_id, winner),
        ).fetchone()
        if exists is not None:
            conn.execute(
                "DELETE FROM rel_show_song WHERE show_id = ? AND song_id = ?",
                (show_id, loser),
            )
            out["rel_show_song_cascade_deleted"] += 1
        else:
            conn.execute(
                "UPDATE rel_show_song SET song_id = ? WHERE show_id = ? AND song_id = ?",
                (winner, show_id, loser),
            )
            out["rel_show_song_redirected"] += 1
    return out


# ---------------------------------------------------------------------------
# Step 4 — Soft-delete losing songs
# ---------------------------------------------------------------------------


def _step4_soft_delete_losers(conn: sqlite3.Connection, losers: list[str], now: int) -> int:
    if not losers:
        return 0
    placeholders = ",".join(["?"] * len(losers))
    cur = conn.execute(
        f"UPDATE song SET status = 1, updated_at = ? WHERE id IN ({placeholders})",
        [now, *losers],
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Step 5 — Soft-delete source artists
# ---------------------------------------------------------------------------


def _step5_soft_delete_sources(conn: sqlite3.Connection, sources: list[str], now: int) -> int:
    placeholders = ",".join(["?"] * len(sources))
    cur = conn.execute(
        f"UPDATE artist SET status = 1, updated_at = ? WHERE id IN ({placeholders})",
        [now, *sources],
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def _run_merge(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    target = args.target_artist_id
    sources = _csv(args.source_artist_ids)
    _preflight(conn, target, sources)

    now = _common.now_epoch()

    # Step 1.
    songs_reassigned = _step1_reassign(conn, target, sources, now)

    # Step 2.
    groups = _step2_find_duplicates(conn, target)
    duplicate_groups_merged = len(groups)
    all_losers: list[str] = []
    counters: dict[str, int] = {
        "play_history_redirected": 0,
        "learning_redirected": 0,
        "rel_show_song_redirected": 0,
        "rel_show_song_cascade_deleted": 0,
    }

    # Step 3.
    for winner, losers in groups:
        for loser in losers:
            sub = _step3_redirect(conn, winner, loser, now)
            for k, v in sub.items():
                counters[k] += v
            all_losers.append(loser)

    # Step 4.
    songs_soft_deleted = _step4_soft_delete_losers(conn, all_losers, now)

    # Step 5.
    source_artists_soft_deleted = _step5_soft_delete_sources(conn, sources, now)

    payload: dict[str, Any] = {
        "target_artist_id": target,
        "source_artist_ids": sources,
        "songs_reassigned": songs_reassigned,
        "duplicate_groups_merged": duplicate_groups_merged,
        "songs_soft_deleted": songs_soft_deleted,
        "play_history_redirected": counters["play_history_redirected"],
        "learning_redirected": counters["learning_redirected"],
        "rel_show_song_redirected": counters["rel_show_song_redirected"],
        "rel_show_song_cascade_deleted": counters["rel_show_song_cascade_deleted"],
        "source_artists_soft_deleted": source_artists_soft_deleted,
    }
    _common.success(payload)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    conn = _common.open_db(__file__)
    try:
        # R10.9: single transaction. Same commit-on-SystemExit(0) pattern
        # as data.py / learning.py.
        conn.execute("BEGIN IMMEDIATE")
        try:
            _run_merge(conn, args)
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
