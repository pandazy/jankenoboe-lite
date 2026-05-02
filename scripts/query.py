"""Read-only queries over ``db/datasource.db``.

Every subcommand reads rows, shapes them as JSON, and prints a
Success_Envelope to stdout. No writes, no transactions, no locking. The
script finds its DB via ``_common.open_db(__file__)``; the deploy target
pins one DB path per App_Root.

Subcommands (see requirements.md R5, R17):
    get, batch-get, search, duplicates,
    shows-by-artist-ids, songs-by-artist-ids, list-learning,
    song-detail, artist-detail, show-detail, learning-detail

All row-shaping goes through stable column order so the JSON output is
predictable across Python versions.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from typing import Any

# When run as `python scripts/query.py ...`, Python puts scripts/ (not the
# repo root) on sys.path. Add the repo root so `from scripts import _common`
# works. `absolute()` (not `resolve()`) keeps the symlink intact — the test
# harness symlinks scripts/ into a temp App_Root, and resolving would jump
# into the real repo, breaking DB resolution downstream.
_REPO_ROOT = str(pathlib.Path(__file__).absolute().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts import _common  # noqa: E402

# ---------------------------------------------------------------------------
# argparse setup
# ---------------------------------------------------------------------------

_KINDS_RW = ("song", "artist", "show", "rel_show_song")
_KINDS_SEARCHABLE = ("song", "artist", "show")

# Upper bound on the decoded byte length of any Active ``search-songs``
# Filter_Term (R-SE-1.6). The cap runs after URL-decoding so a caller cannot
# smuggle an over-length payload in as percent-encoded bytes, and before any
# DB query so validation never scans the library. Exposed at module scope so
# tests can import the exact number rather than hard-coding a magic constant.
_MAX_TERM_BYTES = 1024


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="query.py",
        description="Read-only queries over the local SQLite DB.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # get
    g = sub.add_parser("get", help="Fetch one row by primary key.")
    g.add_argument("--kind", choices=_KINDS_RW, required=True)
    g.add_argument("--id", dest="row_id", required=True)

    # batch-get
    bg = sub.add_parser("batch-get", help="Fetch many rows by id (skip missing).")
    bg.add_argument("--kind", choices=("song", "artist", "show"), required=True)
    bg.add_argument("--ids", default="", help="Comma-separated ids.")

    # search
    s = sub.add_parser("search", help="Case-insensitive substring search.")
    s.add_argument("--kind", choices=_KINDS_SEARCHABLE, required=True)
    s.add_argument("--term", required=True)

    # duplicates
    d = sub.add_parser("duplicates", help="Groups sharing a name (≥ 2 rows).")
    d.add_argument("--kind", choices=_KINDS_SEARCHABLE, required=True)

    # shows-by-artist-ids / songs-by-artist-ids
    for name in ("shows-by-artist-ids", "songs-by-artist-ids"):
        ba = sub.add_parser(name, help="Listed rows for the given artist ids.")
        ba.add_argument("--artist-ids", required=True, help="Comma-separated.")

    # list-learning
    ll = sub.add_parser(
        "list-learning", help="Learning rows for the given song ids (active + graduated)."
    )
    ll.add_argument("--song-ids", required=True, help="Comma-separated.")

    # *-detail ops
    for name in ("song-detail", "artist-detail", "show-detail", "learning-detail"):
        dx = sub.add_parser(name, help="Full composed view around the target id.")
        dx.add_argument("--id", dest="row_id", required=True)

    # search-songs: combined-filter song search with related details attached.
    # All three filter flags are optional (absence = Inactive_Filter, per
    # R-SE-1.3) and take a single value each — no ``action="append"`` so
    # argparse's default last-value-wins semantics apply when the same flag is
    # passed twice (R-SE-1.7). ``default=None`` is explicit so the handler can
    # distinguish "not passed" from "empty string" (R-SE-1.5).
    ss = sub.add_parser(
        "search-songs",
        help=(
            "Search songs with optional song / show / artist name filters. "
            "Returns each match with artist, shows (incl. media_urls), and a "
            "learning summary attached."
        ),
    )
    ss.add_argument("--song-term", dest="song_term", default=None)
    ss.add_argument("--show-term", dest="show_term", default=None)
    ss.add_argument("--artist-term", dest="artist_term", default=None)

    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _csv(s: str) -> list[str]:
    """Parse a ``--ids``-style CSV arg into a list (empty string → empty list)."""
    return [x for x in (part.strip() for part in s.split(",")) if x]


def _row_as_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _media_urls(conn: sqlite3.Connection, show_id: str, song_id: str) -> list[str]:
    """Sorted, deduplicated, non-empty play_history media urls for a pair.

    Per R5.16: detail ops source ``media_urls`` from ``play_history`` only.
    """
    cur = conn.execute(
        "SELECT DISTINCT media_url FROM play_history "
        "WHERE show_id = ? AND song_id = ? "
        "  AND status = 0 AND media_url IS NOT NULL AND media_url <> '' "
        "ORDER BY media_url",
        (show_id, song_id),
    )
    return [row[0] for row in cur.fetchall()]


def _shows_for_song(conn: sqlite3.Connection, song_id: str) -> list[dict[str, Any]]:
    """Shows linked to this song via rel_show_song (live shows only).

    Each entry has ``{id, name, name_romaji, vintage, s_type, media_urls}``,
    sorted by show name then id.
    """
    cur = conn.execute(
        "SELECT sh.id, sh.name, sh.name_romaji, sh.vintage, sh.s_type "
        "FROM show sh JOIN rel_show_song r ON r.show_id = sh.id "
        "WHERE r.song_id = ? AND sh.status = 0 "
        "ORDER BY sh.name, sh.id",
        (song_id,),
    )
    shows: list[dict[str, Any]] = []
    for show in cur.fetchall():
        shows.append(
            {
                "id": show["id"],
                "name": show["name"],
                "name_romaji": show["name_romaji"],
                "vintage": show["vintage"],
                "s_type": show["s_type"],
                "media_urls": _media_urls(conn, show["id"], song_id),
            }
        )
    return shows


def _artist_summary(conn: sqlite3.Connection, artist_id: str) -> dict[str, Any] | None:
    """Artist row with ``{id, name, name_context, status}``. No status filter.

    Per R5.12/R5.14: the nested artist object carries its ``status`` so
    callers can see a broken DB (live song under a soft-deleted artist).
    """
    cur = conn.execute(
        "SELECT id, name, name_context, status FROM artist WHERE id = ? LIMIT 1",
        (artist_id,),
    )
    row = cur.fetchone()
    return dict(row) if row is not None else None


def _song_row(
    conn: sqlite3.Connection, song_id: str, *, include_deleted: bool = False
) -> dict[str, Any] | None:
    sql = "SELECT * FROM song WHERE id = ?"
    if not include_deleted:
        sql += " AND status = 0"
    sql += " LIMIT 1"
    cur = conn.execute(sql, (song_id,))
    row = cur.fetchone()
    return dict(row) if row is not None else None


def _find_matching_songs(
    conn: sqlite3.Connection, decoded: dict[str, str | None]
) -> list[dict[str, Any]]:
    """Query 1 for ``search-songs``: the song-id SELECT.

    Returns the ordered list of live song rows (as dicts from
    ``SELECT s.*``) whose `(song, artist, optional matching show)`
    combination satisfies Combined_Filter. ``decoded`` is the per-kind
    URL-decoded Filter_Term map: each key is one of ``"song"``,
    ``"artist"``, ``"show"`` and its value is either a ``str``
    (Active_Filter) or ``None`` (Inactive_Filter).

    The WHERE is built from ``_common.SPECS[kind].searchable_columns``
    rather than hard-coded column names so any future searchable column
    added to ``song`` / ``artist`` / ``show`` is picked up automatically
    (R-SE-2.1..3). All terms are passed as bound parameters — never
    string-concatenated into the SQL — so the SQLite LIKE wildcards
    ``%`` and ``_`` stay literal (R-SE-2.10).

    Soft-deleted songs and songs under soft-deleted artists are excluded
    at the SQL layer (R-SE-2.5, R-SE-2.6). The ``--show-term`` predicate
    is an ``EXISTS`` over ``rel_show_song`` + ``show`` so the outer
    ``ORDER BY s.name, s.id`` (R-SE-3.10) sees one row per song even
    when a song is linked to multiple matching shows.

    An Inactive_Filter contributes no clause; a zero-filter call
    degenerates to ``WHERE s.status = 0 AND a.status = 0`` — the
    Zero_Filter_Behavior list-every-live-song shape (R-SE-1.4 /
    R-SE-2.8).
    """
    song_cols = _common.SPECS["song"].searchable_columns
    artist_cols = _common.SPECS["artist"].searchable_columns
    show_cols = _common.SPECS["show"].searchable_columns

    where: list[str] = ["s.status = 0", "a.status = 0"]
    params: list[Any] = []

    if decoded["song"] is not None:
        where.append(
            "(" + " OR ".join(f"LOWER(s.{c}) LIKE '%' || LOWER(?) || '%'" for c in song_cols) + ")"
        )
        params.extend([decoded["song"]] * len(song_cols))

    if decoded["artist"] is not None:
        where.append(
            "("
            + " OR ".join(f"LOWER(a.{c}) LIKE '%' || LOWER(?) || '%'" for c in artist_cols)
            + ")"
        )
        params.extend([decoded["artist"]] * len(artist_cols))

    if decoded["show"] is not None:
        where.append(
            "EXISTS ("
            "SELECT 1 FROM rel_show_song r "
            "JOIN show sh ON sh.id = r.show_id "
            "WHERE r.song_id = s.id "
            "AND sh.status = 0 "
            "AND ("
            + " OR ".join(f"LOWER(sh.{c}) LIKE '%' || LOWER(?) || '%'" for c in show_cols)
            + "))"
        )
        params.extend([decoded["show"]] * len(show_cols))

    sql = (
        "SELECT s.* FROM song s "
        "JOIN artist a ON a.id = s.artist_id "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY s.name, s.id"
    )
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def _load_artists_for_song_rows(
    conn: sqlite3.Connection, song_rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Batch-load the artist summary for every artist referenced by the result set.

    Returns ``{artist_id: {"id", "name", "name_context", "status"}}`` for the
    distinct ``artist_id`` values appearing on ``song_rows``. The key set on
    each artist summary matches the nested ``artist`` object returned by
    ``song-detail`` (parent R5.12) so callers can reuse one parser across the
    two ops (R-SE-3.2, R-SE-3.4).

    Returns an empty dict (and issues no SQL) when ``song_rows`` is empty.
    The ``IN (...)`` clause is built from distinct ids so the bound parameter
    count stays at ``len(set(artist_ids))`` regardless of how many rows in
    ``song_rows`` share an artist.

    Under normal operation every id returned here has ``status = 0`` — the
    Query-1 join already required ``a.status = 0`` — but ``status`` is
    emitted anyway to mirror ``song-detail``'s shape.
    """
    if not song_rows:
        return {}
    ids = {s["artist_id"] for s in song_rows}
    placeholders = ",".join(["?"] * len(ids))
    sql = f"SELECT id, name, name_context, status FROM artist WHERE id IN ({placeholders})"
    cur = conn.execute(sql, list(ids))
    return {row["id"]: dict(row) for row in cur.fetchall()}


def _batch_media_urls(
    conn: sqlite3.Connection, pair_set: set[tuple[str, str]]
) -> dict[tuple[str, str], list[str]]:
    """Query 3 for ``search-songs``: batch-load play_history media urls.

    Returns ``{(show_id, song_id): [url, ...]}`` for every pair in
    ``pair_set``. Every requested pair is present in the output with a
    (possibly empty) list, so callers can ``dict[key]`` without a
    ``KeyError``. Empty ``pair_set`` → empty dict (no SQL issued).

    Issues a single SELECT over ``play_history`` keyed by the **union**
    of observed ``show_id`` and ``song_id`` values — SQLite has no
    tuple-``IN``, so we fetch the Cartesian-looking superset and filter
    pair-wise in Python against ``pair_set``. Duplicates across
    ``play_history`` rows are handled by ``SELECT DISTINCT``; soft-deleted
    rows (``status = 1``) and empty/NULL ``media_url`` values are
    excluded in SQL (R-SE-3.4 ``media_urls``, R-SE-3.8; parent R5.16).

    The ``ORDER BY media_url`` sorts rows lexicographically across the
    whole result set. Because we iterate the cursor in that order and
    append per pair, each per-pair list in the output is itself sorted
    lexicographically — the same guarantee ``_media_urls`` gives for a
    single pair. This keeps ``search-songs`` output byte-stable
    (R-SE-4.7).
    """
    if not pair_set:
        return {}
    # SQLite lacks tuple-IN, so fan out to two scalar IN sets and filter
    # client-side. Duplicate ids collapse via set() so the bound-parameter
    # count stays at |distinct show_ids| + |distinct song_ids|.
    show_ids = {sh for (sh, _so) in pair_set}
    song_ids = {so for (_sh, so) in pair_set}
    show_ph = ",".join(["?"] * len(show_ids))
    song_ph = ",".join(["?"] * len(song_ids))
    sql = (
        "SELECT DISTINCT show_id, song_id, media_url "
        "FROM play_history "
        f"WHERE show_id IN ({show_ph}) AND song_id IN ({song_ph}) "
        "  AND status = 0 AND media_url IS NOT NULL AND media_url <> '' "
        "ORDER BY media_url"
    )
    # Pre-initialize so every input pair has an entry (possibly empty).
    out: dict[tuple[str, str], list[str]] = {p: [] for p in pair_set}
    cur = conn.execute(sql, list(show_ids) + list(song_ids))
    for row in cur.fetchall():
        key = (row["show_id"], row["song_id"])
        if key in pair_set:
            out[key].append(row["media_url"])
    return out


def _load_shows_for_songs(
    conn: sqlite3.Connection,
    song_ids: list[str],
    show_term: str | None,
) -> dict[str, list[dict[str, Any]]]:
    """Query 2 for ``search-songs``: batch-load live shows per song.

    Returns ``{song_id: [Show_Entry, ...]}`` for every id in ``song_ids``.
    Every input id is pre-seeded with an empty list so callers can
    ``dict[sid]`` without a ``KeyError`` — a song with zero live
    ``rel_show_song`` links round-trips as ``[]`` (R-SE-3.5, R-SE-2.8).
    Empty ``song_ids`` → empty dict (no SQL issued).

    Issues one SELECT joining ``rel_show_song r`` and ``show sh``, filtered
    by ``r.song_id IN (...) AND sh.status = 0`` so soft-deleted shows never
    surface (R-SE-3.4, P-SE-4.3). The per-song groups come back in
    ``(sh.name ASC, sh.id ASC)`` order — the outer ``ORDER BY r.song_id,
    sh.name, sh.id`` clusters rows by song id, then sorts within each
    cluster. Combined with dict preservation of insertion order, the
    per-song ``shows`` array is sorted as required by R-SE-3.4 / R-SE-3.10.

    ``matched_filter`` is computed in SQL:

      * When ``show_term is None`` (``--show-term`` Inactive), the expression
        is the literal ``1`` — no parameters bind for it, and every live
        linked show comes back with ``matched_filter = True`` vacuously
        (R-SE-3.4, P-SE-3.3).
      * Otherwise, ``CASE WHEN (LOWER(sh.col) LIKE '%' || LOWER(?) || '%'
        OR ...) THEN 1 ELSE 0 END`` over
        ``_common.SPECS["show"].searchable_columns`` — the same two-column
        pattern the outer Show_Match_Predicate uses, so a searchable-column
        addition to ``show`` propagates to both sites (R-SE-2.3, R-SE-2.4).
        The 0/1 int is cast to Python ``bool`` before emission so the JSON
        is ``true``/``false`` rather than ``0``/``1``.

    ``media_urls`` for each entry are loaded in one shared batch via
    ``_batch_media_urls`` keyed by the ``(show_id, song_id)`` pairs seen in
    this result — no N+1 per-pair round trip (R-SE-3.8).

    Each ``Show_Entry`` is assembled with the key order required by the
    design: ``[id, name, name_romaji, vintage, s_type, media_urls,
    matched_filter]`` (R-SE-3.4, P-SE-7.4).
    """
    if not song_ids:
        return {}

    show_cols = _common.SPECS["show"].searchable_columns

    # Build the matched_filter SQL fragment and its bound params. Inactive
    # --show-term binds nothing and always yields 1 (True) — the vacuous
    # match (R-SE-3.4). Active --show-term reuses the two-column LIKE
    # pattern from _common.search_rows.
    if show_term is None:
        match_expr = "1"
        match_params: list[Any] = []
    else:
        like_parts = [f"LOWER(sh.{c}) LIKE '%' || LOWER(?) || '%'" for c in show_cols]
        match_expr = "(CASE WHEN (" + " OR ".join(like_parts) + ") THEN 1 ELSE 0 END)"
        match_params = [show_term] * len(show_cols)

    placeholders = ",".join(["?"] * len(song_ids))
    sql = (
        "SELECT r.song_id, sh.id, sh.name, sh.name_romaji, sh.vintage, "
        f"       sh.s_type, {match_expr} AS matched_filter "
        "FROM rel_show_song r "
        "JOIN show sh ON sh.id = r.show_id "
        f"WHERE r.song_id IN ({placeholders}) AND sh.status = 0 "
        "ORDER BY r.song_id, sh.name, sh.id"
    )
    rows = conn.execute(sql, match_params + list(song_ids)).fetchall()

    # One shared SELECT for every (show_id, song_id) pair we observed.
    pair_set = {(row["id"], row["song_id"]) for row in rows}
    media = _batch_media_urls(conn, pair_set)

    # Pre-seed every input song id with an empty list so callers get a
    # deterministic "present but empty" entry for songs with no live shows
    # (R-SE-2.8).
    out: dict[str, list[dict[str, Any]]] = {sid: [] for sid in song_ids}
    for row in rows:
        # Key order here is the emitted JSON key order for Show_Entry
        # (R-SE-3.4): id, name, name_romaji, vintage, s_type, media_urls,
        # matched_filter.
        out[row["song_id"]].append(
            {
                "id": row["id"],
                "name": row["name"],
                "name_romaji": row["name_romaji"],
                "vintage": row["vintage"],
                "s_type": row["s_type"],
                "media_urls": media.get((row["id"], row["song_id"]), []),
                "matched_filter": bool(row["matched_filter"]),
            }
        )
    return out


# Warning message for the ``duplicate_active_learning`` code (R-SE-3.12).
# Parked at module scope so the integration test can assert the exact string
# without being fragile to reformatting inside the helper body. The ``code``
# value is the stable contract; this wording MAY evolve in later specs.
_DUP_ACTIVE_MSG = (
    "Multiple active learning rows for this song. This is a data "
    "glitch — learning ops maintain at most one active row per "
    "song. Consider running scripts/cleanup.py or "
    "'learning.py graduate' on the stale rows to reconcile."
)


def _load_learning_state_for_songs(
    conn: sqlite3.Connection, song_ids: list[str]
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, bool],
    dict[str, list[dict[str, str]]],
]:
    """Query 4 for ``search-songs``: batch-load per-song learning state.

    Returns ``(learning_by_song, graduated_by_song, warnings_by_song)``:

      * ``learning_by_song``: ``{song_id: Learning_Summary}`` for songs that
        have at least one active (``graduated = 0``) learning row. Missing
        keys mean the song has no active row — the orchestrator maps that
        to ``learning: null`` (R-SE-3.6). The summary is taken from the
        active row with the highest ``updated_at``, tie-broken by ``id ASC``.
        Key order on the summary is ``[id, level, display_level, graduated,
        last_level_up_at, updated_at]`` (design data-model block) and
        ``display_level = int(level) + 1`` per parent R17 / R-SE-3.7.
      * ``graduated_by_song``: ``{song_id: bool}`` for **every** id in
        ``song_ids``. ``True`` iff the song has at least one ``graduated =
        1`` row; ``False`` otherwise (including songs with no learning rows
        at all) — R-SE-3.11. Pre-seeded with ``False`` so the dict is
        authoritative for every input id.
      * ``warnings_by_song``: ``{song_id: [Warning]}`` — sparse. A song
        with two or more active learning rows (a data glitch — parent R6
        maintains at most one un-graduated row per song) gets exactly one
        Warning with ``code = "duplicate_active_learning"`` and the
        ``_DUP_ACTIVE_MSG`` text (R-SE-3.12, P-SE-9.2). Songs with no
        glitch don't appear in the dict; the orchestrator defaults those
        to ``[]``.

    Empty ``song_ids`` → three empty dicts (no SQL issued).

    The ``ORDER BY graduated ASC, updated_at DESC, id ASC`` sorts rows so
    that for each song, the active rows (``graduated = 0``) stream first,
    freshest ``updated_at`` wins, and the first active row we observe per
    song is the chosen summary. The single SELECT pulls every learning row
    for the song-id set, and classification happens in Python — simpler
    than three round trips (pick-active + has-graduated + count-active).

    No filter on ``song.status`` is needed: Query 1 already required
    ``s.status = 0``, so every id in ``song_ids`` points at a live song.
    """
    if not song_ids:
        return {}, {}, {}
    placeholders = ",".join(["?"] * len(song_ids))
    sql = (
        "SELECT id, song_id, level, graduated, last_level_up_at, updated_at "
        f"FROM learning WHERE song_id IN ({placeholders}) "
        "ORDER BY graduated ASC, updated_at DESC, id ASC"
    )
    learning_by_song: dict[str, dict[str, Any]] = {}
    # Pre-seed graduated flag and active-row counter for every requested id
    # so callers get deterministic lookups and the warning pass iterates a
    # known key set (R-SE-3.11, R-SE-3.12).
    graduated_by_song: dict[str, bool] = {sid: False for sid in song_ids}
    active_count: dict[str, int] = {sid: 0 for sid in song_ids}

    for row in conn.execute(sql, list(song_ids)).fetchall():
        sid = row["song_id"]
        if row["graduated"] == 0:
            active_count[sid] += 1
            # First active row wins — ORDER BY pins graduated=0 first, then
            # freshest updated_at, then id ASC (R-SE-3.6).
            if sid not in learning_by_song:
                # Key order here is the emitted JSON key order for
                # Learning_Summary (design data-model block): id, level,
                # display_level, graduated, last_level_up_at, updated_at.
                learning_by_song[sid] = {
                    "id": row["id"],
                    "level": row["level"],
                    "display_level": int(row["level"]) + 1,  # parent R17
                    "graduated": row["graduated"],  # always 0 here
                    "last_level_up_at": row["last_level_up_at"],
                    "updated_at": row["updated_at"],
                }
        else:  # row["graduated"] == 1
            graduated_by_song[sid] = True

    # Sparse: only songs with the glitch get a warnings entry. At most one
    # Warning per song regardless of how many extra active rows exist
    # (P-SE-9.2).
    warnings_by_song: dict[str, list[dict[str, str]]] = {}
    for sid, n in active_count.items():
        if n >= 2:
            warnings_by_song[sid] = [
                {
                    "code": "duplicate_active_learning",
                    "message": _DUP_ACTIVE_MSG,
                }
            ]
    return learning_by_song, graduated_by_song, warnings_by_song


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_get(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    # For rel_show_song the --id takes a "show_id,song_id" composite key.
    key: Any = args.row_id
    if args.kind == "rel_show_song":
        parts = _csv(args.row_id)
        if len(parts) != 2:
            raise _common.KnownError(
                "INVALID_INPUT",
                "rel_show_song --id must be 'show_id,song_id'",
                {"got": args.row_id},
            )
        key = parts
    row = _common.get_row(conn, args.kind, key)
    if row is None:
        raise _common.KnownError(
            "NOT_FOUND",
            f"{args.kind} not found or soft-deleted",
            {"kind": args.kind, "id": args.row_id},
        )
    _common.success(row)


def _cmd_batch_get(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    ids = _csv(args.ids)
    rows = _common.batch_get_rows(conn, args.kind, ids)
    _common.success(rows)


def _cmd_search(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    term = _common.decode_term(args.term)
    rows = _common.search_rows(conn, args.kind, term)
    _common.success(rows)


def _cmd_duplicates(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Groups of 2+ rows sharing the same identifying key.

    * ``song``: grouped by ``(artist_id, name)``.
    * ``artist``: grouped by ``name`` alone.
    * ``show``: grouped by ``(name, vintage)``.

    Only ``status = 0`` rows are counted.
    """
    kind = args.kind
    groups: list[dict[str, Any]] = []
    if kind == "song":
        cur = conn.execute(
            "SELECT artist_id, name, GROUP_CONCAT(id) AS ids "
            "FROM song WHERE status = 0 "
            "GROUP BY artist_id, name "
            "HAVING COUNT(*) >= 2 "
            "ORDER BY name, artist_id"
        )
        for row in cur.fetchall():
            groups.append(
                {
                    "name": row["name"],
                    "artist_id": row["artist_id"],
                    "ids": row["ids"].split(",") if row["ids"] else [],
                }
            )
    elif kind == "artist":
        cur = conn.execute(
            "SELECT name, GROUP_CONCAT(id) AS ids "
            "FROM artist WHERE status = 0 "
            "GROUP BY name "
            "HAVING COUNT(*) >= 2 "
            "ORDER BY name"
        )
        for row in cur.fetchall():
            groups.append(
                {
                    "name": row["name"],
                    "ids": row["ids"].split(",") if row["ids"] else [],
                }
            )
    else:  # show
        cur = conn.execute(
            "SELECT name, vintage, GROUP_CONCAT(id) AS ids "
            "FROM show WHERE status = 0 "
            "GROUP BY name, vintage "
            "HAVING COUNT(*) >= 2 "
            "ORDER BY name, vintage"
        )
        for row in cur.fetchall():
            groups.append(
                {
                    "name": row["name"],
                    "vintage": row["vintage"],
                    "ids": row["ids"].split(",") if row["ids"] else [],
                }
            )
    _common.success(groups)


def _cmd_shows_by_artist_ids(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    ids = _csv(args.artist_ids)
    if not ids:
        _common.success([])
        return
    placeholders = ",".join(["?"] * len(ids))
    sql = (
        "SELECT DISTINCT sh.* "
        "FROM show sh "
        "JOIN rel_show_song r ON r.show_id = sh.id "
        "JOIN song s ON s.id = r.song_id "
        f"WHERE s.artist_id IN ({placeholders}) "
        "  AND sh.status = 0 "
        "  AND s.status = 0 "
        "ORDER BY sh.name, sh.id"
    )
    cur = conn.execute(sql, ids)
    _common.success([dict(r) for r in cur.fetchall()])


def _cmd_songs_by_artist_ids(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    ids = _csv(args.artist_ids)
    if not ids:
        _common.success([])
        return
    placeholders = ",".join(["?"] * len(ids))
    sql = (
        "SELECT s.* "
        "FROM song s JOIN artist a ON a.id = s.artist_id "
        f"WHERE s.artist_id IN ({placeholders}) "
        "  AND s.status = 0 "
        "  AND a.status = 0 "
        "ORDER BY s.name, s.id"
    )
    cur = conn.execute(sql, ids)
    _common.success([dict(r) for r in cur.fetchall()])


def _cmd_list_learning(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Learning rows for the given song ids.

    * Does NOT filter by ``graduated``.
    * Joins ``song`` and filters ``song.status = 0`` (R15.2).
    * Orders by ``learning.updated_at DESC, learning.id ASC``.
    * Missing song ids are silently skipped (R3.6, R5.9).
    """
    ids = _csv(args.song_ids)
    if not ids:
        _common.success([])
        return
    placeholders = ",".join(["?"] * len(ids))
    sql = (
        "SELECT l.* "
        "FROM learning l JOIN song s ON s.id = l.song_id "
        f"WHERE l.song_id IN ({placeholders}) "
        "  AND s.status = 0 "
        "ORDER BY l.updated_at DESC, l.id ASC"
    )
    cur = conn.execute(sql, ids)
    _common.success([dict(r) for r in cur.fetchall()])


def _assemble_song_detail(conn: sqlite3.Connection, song_id: str) -> dict[str, Any]:
    """Build the ``{song, artist, shows}`` payload for a live song.

    Raises ``KnownError(NOT_FOUND)`` when the song or its artist isn't live.
    """
    song = _song_row(conn, song_id)
    if song is None:
        raise _common.KnownError(
            "NOT_FOUND",
            "song not found or soft-deleted",
            {"kind": "song", "id": song_id},
        )
    artist = _artist_summary(conn, song["artist_id"])
    if artist is None:
        # Dangling FK — in a healthy DB this doesn't happen, but we raise
        # NOT_FOUND instead of serving a broken payload.
        raise _common.KnownError(
            "NOT_FOUND",
            "artist for song not found",
            {"kind": "artist", "id": song["artist_id"]},
        )
    # Per R5.12: song-detail returns the artist with its status visible so
    # the caller can see a broken DB (live song under a soft-deleted artist).
    # learning-detail raises NOT_FOUND on the same inconsistency (done there).
    shows = _shows_for_song(conn, song_id)
    return {"song": song, "artist": artist, "shows": shows}


def _cmd_song_detail(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    _common.success(_assemble_song_detail(conn, args.row_id))


def _cmd_artist_detail(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    # The artist itself must be live.
    row = _common.get_row(conn, "artist", args.row_id)
    if row is None:
        raise _common.KnownError(
            "NOT_FOUND",
            "artist not found or soft-deleted",
            {"kind": "artist", "id": args.row_id},
        )
    # Songs by this artist that are live.
    cur = conn.execute(
        "SELECT * FROM song WHERE artist_id = ? AND status = 0 ORDER BY name, id",
        (args.row_id,),
    )
    song_rows = [dict(r) for r in cur.fetchall()]
    songs: list[dict[str, Any]] = []
    for sr in song_rows:
        songs.append(
            {
                "id": sr["id"],
                "name": sr["name"],
                "name_context": sr["name_context"],
                "shows": _shows_for_song(conn, sr["id"]),
            }
        )
    _common.success({"artist": row, "songs": songs})


def _cmd_show_detail(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    # The show itself must be live.
    show = _common.get_row(conn, "show", args.row_id)
    if show is None:
        raise _common.KnownError(
            "NOT_FOUND",
            "show not found or soft-deleted",
            {"kind": "show", "id": args.row_id},
        )
    # Songs linked to this show (live), sorted by song name then id.
    cur = conn.execute(
        "SELECT s.* FROM song s JOIN rel_show_song r ON r.song_id = s.id "
        "WHERE r.show_id = ? AND s.status = 0 ORDER BY s.name, s.id",
        (args.row_id,),
    )
    songs: list[dict[str, Any]] = []
    for sr in cur.fetchall():
        song = dict(sr)
        artist = _artist_summary(conn, song["artist_id"]) or {
            "id": song["artist_id"],
            "name": "",
            "name_context": "",
            "status": 0,
        }
        songs.append(
            {
                "id": song["id"],
                "name": song["name"],
                "name_context": song["name_context"],
                "artist": artist,
                "media_urls": _media_urls(conn, args.row_id, song["id"]),
            }
        )
    _common.success({"show": show, "songs": songs})


def _cmd_learning_detail(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """``{learning, song, artist, shows}`` for a single learning row.

    Returns ``NOT_FOUND`` when:
      * the learning row is missing, or
      * the referenced song is soft-deleted, or
      * the song's artist is soft-deleted.
    """
    cur = conn.execute("SELECT * FROM learning WHERE id = ? LIMIT 1", (args.row_id,))
    l_row = cur.fetchone()
    if l_row is None:
        raise _common.KnownError(
            "NOT_FOUND",
            "learning row not found",
            {"kind": "learning", "id": args.row_id},
        )
    learning = dict(l_row)
    # Parse level_up_path JSON so the response has a real list (R5.15 + design).
    try:
        learning["level_up_path"] = json.loads(learning["level_up_path"])
    except (TypeError, json.JSONDecodeError):
        learning["level_up_path"] = list(_common.DEFAULT_LEVEL_UP_PATH)
    learning["display_level"] = int(learning["level"]) + 1

    song = _song_row(conn, learning["song_id"])
    if song is None:
        raise _common.KnownError(
            "NOT_FOUND",
            "learning row points at a soft-deleted or missing song",
            {"kind": "song", "id": learning["song_id"]},
        )
    artist = _artist_summary(conn, song["artist_id"])
    if artist is None or artist.get("status") != 0:
        # Per R5.15: a learning row pointing at a soft-deleted artist is
        # treated as NOT_FOUND so the operator cleans up the learning row.
        raise _common.KnownError(
            "NOT_FOUND",
            "learning row points at a soft-deleted or missing artist",
            {"kind": "artist", "id": song["artist_id"]},
        )
    shows = _shows_for_song(conn, song["id"])
    _common.success(
        {
            "learning": learning,
            "song": song,
            "artist": artist,
            "shows": shows,
        }
    )


# ---------------------------------------------------------------------------
# search-songs handler
# ---------------------------------------------------------------------------


def _cmd_search_songs(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Combined-filter song search.

    Orchestrates the four batch queries defined by the design and assembles
    one Song_Search_Result per matching live song. Envelope key order is
    fixed by construction (Python 3.10+ preserves dict insertion order and
    ``_common.success`` serializes via ``json.dumps`` which respects it),
    so re-running the same filter set against an unchanged DB yields
    byte-identical stdout (R-SE-4.1, R-SE-4.7).

    Pipeline:
      1. Collect the raw CLI values — ``None`` marks an Inactive_Filter.
      2. URL-decode every Active_Filter exactly once via
         ``_common.decode_term`` (R-SE-1.5). Inactive_Filters stay ``None``.
         Every decoded Active_Filter is validated against the
         ``_MAX_TERM_BYTES`` cap (R-SE-1.6); an over-length term raises
         ``KnownError("INVALID_INPUT", ...)`` before any DB query runs.
      3. Query 1 — ``_find_matching_songs`` returns the ordered list of
         live song rows satisfying Combined_Filter.
      4. Query 2 — ``_load_shows_for_songs`` batch-loads Show_Entry lists
         keyed by ``song_id``, honoring ``--show-term`` for the
         ``matched_filter`` flag.
      5. Query 3 — ``_batch_media_urls`` is called inside the shows helper
         to batch ``play_history`` media urls across every observed pair.
      6. Query 4 — ``_load_learning_state_for_songs`` classifies learning
         rows into active summary / graduated flag / glitch warnings.
      7. Artist summaries are batch-loaded for the distinct
         ``artist_id`` values referenced by the result set.
      8. Assemble each Song_Search_Result with the exact key order
         ``[song, artist, shows, learning, graduated, warnings]``
         (R-SE-3.2). Defaults: ``shows = []``, ``learning = None``,
         ``graduated = False``, ``warnings = []`` (R-SE-3.5, R-SE-3.6,
         R-SE-3.11, R-SE-3.12).
      9. Emit the Search_Envelope with ``filters`` key order
         ``[song_term, show_term, artist_term]`` (R-SE-4.2), ``count ==
         len(results)`` (R-SE-4.3), and ``results`` in
         ``(song.name, song.id)`` order (R-SE-3.10).
    """
    # 1. Collect raw CLI values. ``None`` = Inactive_Filter (R-SE-1.3).
    raw: dict[str, str | None] = {
        "song": args.song_term,
        "show": args.show_term,
        "artist": args.artist_term,
    }

    # 2. URL-decode every Active_Filter exactly once (R-SE-1.5) and enforce
    #    the ``_MAX_TERM_BYTES`` cap on the decoded byte length (R-SE-1.6).
    #    The cap is checked after decoding so percent-encoded payloads
    #    cannot sneak past it, and before any DB query so validation never
    #    touches SQLite. Inactive_Filters (``None``) are skipped — the cap
    #    only applies when the caller passed the flag. The per-kind dict is
    #    consumed by every downstream helper — they look up by "song" /
    #    "show" / "artist".
    decoded: dict[str, str | None] = {}
    for kind, raw_value in raw.items():
        if raw_value is None:
            decoded[kind] = None
            continue
        d = _common.decode_term(raw_value)
        if len(d.encode("utf-8")) > _MAX_TERM_BYTES:
            raise _common.KnownError(
                "INVALID_INPUT",
                f"{kind}-term exceeds {_MAX_TERM_BYTES}-byte cap after URL decode",
                {"flag": f"--{kind}-term", "max_bytes": _MAX_TERM_BYTES},
            )
        decoded[kind] = d

    # 3. Query 1: ordered list of live song rows satisfying Combined_Filter.
    song_rows = _find_matching_songs(conn, decoded)
    song_ids = [s["id"] for s in song_rows]

    # 4+5. Query 2 (+ Query 3 inside): live shows per song with media urls.
    shows_by_song = _load_shows_for_songs(conn, song_ids, decoded["show"])

    # 6. Query 4: per-song learning classification.
    (
        learning_by_song,
        graduated_by_song,
        warnings_by_song,
    ) = _load_learning_state_for_songs(conn, song_ids)

    # 7. Batch-load artist summaries for the distinct artist_ids referenced.
    artists_by_id = _load_artists_for_song_rows(conn, song_rows)

    # 8. Assemble Song_Search_Result entries. Key order is pinned by the
    #    literal dict below (R-SE-3.2). ``.get(..., default)`` supplies the
    #    defaults for songs with no linked shows / no learning row / no
    #    glitches (R-SE-3.5, R-SE-3.6, R-SE-3.11, R-SE-3.12).
    results = [
        {
            "song": s,
            "artist": artists_by_id[s["artist_id"]],
            "shows": shows_by_song.get(s["id"], []),
            "learning": learning_by_song.get(s["id"]),
            "graduated": graduated_by_song.get(s["id"], False),
            "warnings": warnings_by_song.get(s["id"], []),
        }
        for s in song_rows
    ]

    # 9. Emit the Search_Envelope. ``filters`` key order is pinned to
    #    ``[song_term, show_term, artist_term]`` (R-SE-4.2).
    _common.success(
        {
            "filters": {
                "song_term": decoded["song"],
                "show_term": decoded["show"],
                "artist_term": decoded["artist"],
            },
            "count": len(results),
            "results": results,
        }
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_DISPATCH = {
    "get": _cmd_get,
    "batch-get": _cmd_batch_get,
    "search": _cmd_search,
    "duplicates": _cmd_duplicates,
    "shows-by-artist-ids": _cmd_shows_by_artist_ids,
    "songs-by-artist-ids": _cmd_songs_by_artist_ids,
    "list-learning": _cmd_list_learning,
    "song-detail": _cmd_song_detail,
    "artist-detail": _cmd_artist_detail,
    "show-detail": _cmd_show_detail,
    "learning-detail": _cmd_learning_detail,
    "search-songs": _cmd_search_songs,
}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    conn = _common.open_db(__file__)
    try:
        handler = _DISPATCH[args.cmd]
        handler(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    # If called without args, argparse would raise SystemExit(2) with usage on
    # stderr. R2.4 asks for exit 0 on no-args/--help. argparse already exits 0
    # on --help; for bare-no-args we let the user see the usage by intercepting
    # the zero-arg case.
    if len(sys.argv) == 1:
        _build_parser().print_help()
        sys.exit(0)
    _common.run(main)
