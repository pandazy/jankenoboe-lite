"""Shared helpers for every script under `scripts/`.

This module is imported by every script. It is not meant to be run directly.
Keeps to the Python standard library so the app runs in restricted sandboxes.

Covers:
  * locating App_Root and the fixed DB path
  * opening the DB with the right pragmas and schema check
  * the single time seam (`now_epoch`)
  * URL decoding for CLI input
  * JSON stdout/stderr envelopes
  * known-error + top-level `run()` wrapper
  * UUID v4 helper
  * easing math and the default level-up path
  * generic CRUD and search against per-kind `TableSpec`s
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import sqlite3
import sys
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Error codes and KnownError
# ---------------------------------------------------------------------------

VALID_ERROR_CODES: frozenset[str] = frozenset(
    [
        "DB_NOT_FOUND",
        "SCHEMA_MISMATCH",
        "INVALID_INPUT",
        "NOT_FOUND",
        "CONSTRAINT_VIOLATION",
        "SONG_INVARIANT_VIOLATION",
        "ALREADY_GRADUATED",
        "INVALID_ANSWER",
        "INTERNAL_ERROR",
    ]
)


class KnownError(Exception):
    """Raised by helpers to map cleanly onto an Error_Envelope.

    The top-level `run(main)` wrapper catches this and calls `error(...)`.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        if code not in VALID_ERROR_CODES:
            # Developer-facing: picking a code outside the approved set is a bug.
            raise ValueError(f"unknown error code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# ---------------------------------------------------------------------------
# App_Root and DB path
# ---------------------------------------------------------------------------


def app_root(script_file: str) -> pathlib.Path:
    """App_Root computed from a script's own ``__file__``.

    ``scripts/<name>.py`` is one level deep, so App_Root is the parent of
    the ``scripts`` directory. ``absolute()`` (not ``resolve()``) makes the
    path absolute without following symlinks — the test harness symlinks
    ``scripts/`` into a temp App_Root, and we need the script to open the
    temp DB, not the real one the symlink points at.
    """
    return pathlib.Path(script_file).absolute().parent.parent


def db_path(script_file: str) -> pathlib.Path:
    """Full path to ``App_Root/db/datasource.db``. Does not check existence."""
    return app_root(script_file) / "db" / "datasource.db"


def open_db(script_file: str) -> sqlite3.Connection:
    """Open the DB for the caller with the right pragmas, or raise.

    Raises ``KnownError(DB_NOT_FOUND)`` if the file is missing.
    Raises ``KnownError(SCHEMA_MISMATCH)`` if the schema is wrong.
    """
    path = db_path(script_file)
    if not path.exists():
        raise KnownError(
            "DB_NOT_FOUND",
            f"database not found at {path}",
            {"path": str(path)},
        )
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # we handle BEGIN/COMMIT explicitly
    conn.execute("PRAGMA foreign_keys = ON")
    check_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Schema check
# ---------------------------------------------------------------------------

EXPECTED_SCHEMA: dict[str, set[str]] = {
    "song": {
        "id",
        "name",
        "name_context",
        "artist_id",
        "created_at",
        "updated_at",
        "status",
    },
    "artist": {
        "id",
        "name",
        "name_context",
        "created_at",
        "updated_at",
        "status",
    },
    "show": {
        "id",
        "name",
        "name_romaji",
        "vintage",
        "s_type",
        "created_at",
        "updated_at",
        "status",
    },
    "rel_show_song": {
        "show_id",
        "song_id",
        "media_url",
        "created_at",
    },
    "play_history": {
        "id",
        "show_id",
        "song_id",
        "created_at",
        "media_url",
        "status",
    },
    "learning": {
        "id",
        "song_id",
        "level",
        "created_at",
        "updated_at",
        "last_level_up_at",
        "level_up_path",
        "graduated",
    },
}


def check_schema(conn: sqlite3.Connection) -> None:
    """Verify every expected table and column exists. Raise on mismatch.

    Raises ``KnownError(SCHEMA_MISMATCH)`` with
    ``details = {"missing_tables": [...], "missing_columns": {...}}``.
    """
    present_tables: set[str] = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing_tables: list[str] = sorted(t for t in EXPECTED_SCHEMA if t not in present_tables)
    missing_columns: dict[str, list[str]] = {}
    for table, expected_cols in EXPECTED_SCHEMA.items():
        if table in missing_tables:
            continue
        present_cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        missing = sorted(expected_cols - present_cols)
        if missing:
            missing_columns[table] = missing

    if missing_tables or missing_columns:
        raise KnownError(
            "SCHEMA_MISMATCH",
            "database schema does not match expected layout",
            {
                "missing_tables": missing_tables,
                "missing_columns": missing_columns,
            },
        )


# ---------------------------------------------------------------------------
# Time seam
# ---------------------------------------------------------------------------


def now_epoch() -> int:
    """Current UNIX epoch seconds (UTC), or the env-pinned value.

    The only place any script reads the clock. Setting
    ``JANKENOBOE_TEST_NOW`` to an integer string forces this value. Tests
    use this to pin time without monkey-patching.
    """
    v = os.environ.get("JANKENOBOE_TEST_NOW")
    if v is not None:
        return int(v)
    # `datetime.timezone.utc` rather than `datetime.UTC` — the alias was
    # only added in Python 3.11 and we support 3.10 per requirements.md R1.6.
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


# ---------------------------------------------------------------------------
# URL decoding
# ---------------------------------------------------------------------------


def decode_term(s: str) -> str:
    """``urllib.parse.unquote`` applied exactly once. Empty stays empty."""
    return urllib.parse.unquote(s)


def decode_data(obj: Any) -> Any:
    """Walk a JSON-shaped value, URL-decoding only string leaves.

    Rules:
      * dict: each value is decoded; keys are returned unchanged.
      * list/tuple: each element is decoded; result is a list.
      * str: ``urllib.parse.unquote`` once.
      * int, float, bool, None: returned unchanged.
    """
    if isinstance(obj, dict):
        return {k: decode_data(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [decode_data(v) for v in obj]
    if isinstance(obj, str):
        return urllib.parse.unquote(obj)
    # bool is a subclass of int, but we don't touch either kind here.
    return obj


def parse_data_arg(raw: str) -> Any:
    """``json.loads(raw)`` then ``decode_data``. Raises on invalid JSON."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise KnownError(
            "INVALID_INPUT",
            f"--data is not valid JSON: {e}",
            {"raw": raw},
        ) from e
    return decode_data(parsed)


# ---------------------------------------------------------------------------
# JSON I/O and top-level wrapper
# ---------------------------------------------------------------------------


def success(obj: Any) -> None:
    """Write a JSON Success_Envelope to stdout and exit 0."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()
    sys.exit(0)


def error(code: str, message: str, details: dict | None = None) -> None:
    """Write an Error_Envelope to stderr and exit 1.

    ``code`` must be one of ``VALID_ERROR_CODES``. Keeping the check here
    means a bad code raises at the call site rather than producing a
    malformed envelope downstream.
    """
    if code not in VALID_ERROR_CODES:
        raise ValueError(f"unknown error code: {code!r}")
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }
    sys.stderr.write(json.dumps(payload, ensure_ascii=False))
    sys.stderr.write("\n")
    sys.stderr.flush()
    sys.exit(1)


def run(main: Callable[[], None]) -> None:
    """Top-level wrapper every script uses.

    Turns ``KnownError`` into ``error(code, message, details)`` and any
    other exception into ``INTERNAL_ERROR``. ``SystemExit`` from inside
    ``success``/``error`` is allowed to propagate so the exit code is
    preserved.
    """
    try:
        main()
    except SystemExit:
        raise
    except KnownError as e:
        error(e.code, e.message, e.details)
    except Exception as e:
        # Catch-all: maps any unexpected exception to a clean
        # INTERNAL_ERROR envelope. A bare `except Exception` is the point
        # here, not a bug.
        error("INTERNAL_ERROR", str(e) or "internal error", None)


# ---------------------------------------------------------------------------
# UUID
# ---------------------------------------------------------------------------


def new_uuid() -> str:
    """``str(uuid.uuid4())`` — lowercase canonical hyphenated form."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Easing
# ---------------------------------------------------------------------------


def fibo(n: int) -> int:
    """Textbook Fibonacci: ``fibo(0) == 0``, ``fibo(1) == 1``."""
    if n == 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b


def shrink(n: int) -> int:
    """Integer shrink used by the easing curve: ``(n * 2) // 9``."""
    return (n * 2) // 9


def default_easing(n: int) -> int:
    """Wait-day step at level ``n``. Collapses zero-diffs to ``1``."""
    d = shrink(fibo(n + 1)) - shrink(fibo(n))
    return 1 if d == 0 else d


def generate_level_up_path(max_level: int) -> list[int]:
    """``[default_easing(i) for i in range(max_level)]``.

    ``generate_level_up_path(20)`` must be
    ``[1,1,1,1,1,1,1,2,3,5,7,13,19,32,52,84,135,220,355,574]``.
    """
    return [default_easing(i) for i in range(max_level)]


MAX_LEVEL: int = 19
DEFAULT_LEVEL_UP_PATH: list[int] = generate_level_up_path(20)
RE_LEARN_LEVEL: int = 7


# ---------------------------------------------------------------------------
# SQL fragments
# ---------------------------------------------------------------------------

# The three-branch due-time predicate — the single source of truth
# consumed by both ``scripts/learning.py._DUE_SQL`` and
# ``scripts/review.py._DUE_SQL``. Each caller composes its full
# ``_DUE_SQL`` via f-string interpolation of this constant into its
# own SELECT / FROM / non-time-WHERE / ORDER BY skeleton.
#
# Alias contract:
#   Callers MUST alias the ``learning`` table as ``l``. The predicate
#   only touches ``l.last_level_up_at``, ``l.level``, ``l.updated_at``,
#   and ``l.level_up_path``; it does not reference ``s`` (song) or ``a``
#   (artist).
#
# Bind contract:
#   Callers MUST bind ``:offset`` (integer seconds) via
#   ``conn.execute(sql, {"offset": int(args.offset)})``. ``:offset`` is
#   a SQLite bind parameter and MUST NOT be interpolated into this
#   constant as a string.
#
# Branches:
#   A) ``level = 0`` and ``last_level_up_at > 0`` — due when
#      ``now + offset >= last_level_up_at + 300``.
#   B) ``level = 0`` and ``last_level_up_at = 0`` — due when
#      ``now + offset >= updated_at + 300`` (never-reviewed rows fall
#      back to ``updated_at``).
#   C) ``level > 0`` — due when
#      ``level_up_path[level] * 86400 + last_level_up_at <= now + offset``
#      (wait-days path from the stored ``level_up_path`` JSON).
DUE_TIME_CONDITION_SQL = """(
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
)"""


# ---------------------------------------------------------------------------
# Generic table CRUD and search
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableSpec:
    """Describes one table to the generic CRUD helpers."""

    table: str
    columns: tuple[str, ...]
    key: str = "id"
    composite_key: tuple[str, ...] = ()
    has_status: bool = True
    searchable_columns: tuple[str, ...] = ("name",)
    timestamp_cols: tuple[str, ...] = ("created_at", "updated_at")


SPECS: dict[str, TableSpec] = {
    "song": TableSpec(
        table="song",
        columns=("id", "name", "name_context", "artist_id", "created_at", "updated_at", "status"),
        searchable_columns=("name", "name_context"),
    ),
    "artist": TableSpec(
        table="artist",
        columns=("id", "name", "name_context", "created_at", "updated_at", "status"),
        searchable_columns=("name", "name_context"),
    ),
    "show": TableSpec(
        table="show",
        columns=(
            "id",
            "name",
            "name_romaji",
            "vintage",
            "s_type",
            "created_at",
            "updated_at",
            "status",
        ),
        searchable_columns=("name", "name_romaji"),
    ),
    "rel_show_song": TableSpec(
        table="rel_show_song",
        columns=("show_id", "song_id", "media_url", "created_at"),
        key="composite",
        composite_key=("show_id", "song_id"),
        has_status=False,
        searchable_columns=(),
        timestamp_cols=("created_at",),
    ),
}


def _spec(kind: str) -> TableSpec:
    try:
        return SPECS[kind]
    except KeyError:
        raise KnownError(
            "INVALID_INPUT",
            f"unknown kind: {kind!r}",
            {"valid_kinds": sorted(SPECS.keys())},
        ) from None


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _key_clause(spec: TableSpec, key: Any) -> tuple[str, list[Any]]:
    """Return ``(where_sql_fragment, params)`` for a single-row lookup."""
    if spec.key == "composite":
        if not isinstance(key, (list, tuple)) or len(key) != len(spec.composite_key):
            raise KnownError(
                "INVALID_INPUT",
                f"composite key for {spec.table} needs {len(spec.composite_key)} values",
                {"expected": list(spec.composite_key)},
            )
        fragments = [f"{col} = ?" for col in spec.composite_key]
        return " AND ".join(fragments), list(key)
    return f"{spec.key} = ?", [key]


def get_row(conn: sqlite3.Connection, kind: str, key: Any) -> dict | None:
    """Return one row as a dict, or ``None``. Soft-deleted rows hidden."""
    spec = _spec(kind)
    where, params = _key_clause(spec, key)
    sql = f"SELECT * FROM {spec.table} WHERE {where}"
    if spec.has_status:
        sql += " AND status = 0"
    sql += " LIMIT 1"
    cur = conn.execute(sql, params)
    return _row_to_dict(cur.fetchone())


def batch_get_rows(
    conn: sqlite3.Connection,
    kind: str,
    keys: list,
) -> list[dict]:
    """Return rows for the given keys. Missing or soft-deleted silently skipped.

    Ordered by ``name ASC, id ASC``. Only single-column PKs are supported
    by this helper (``rel_show_song`` has no batch-get use case in the spec).
    """
    spec = _spec(kind)
    if spec.key == "composite":
        raise KnownError(
            "INVALID_INPUT",
            f"batch_get_rows does not support composite-key kind {kind!r}",
        )
    if not keys:
        return []
    placeholders = ",".join(["?"] * len(keys))
    sql = f"SELECT * FROM {spec.table} WHERE {spec.key} IN ({placeholders})"
    if spec.has_status:
        sql += " AND status = 0"
    sql += " ORDER BY name, id"
    cur = conn.execute(sql, list(keys))
    return [dict(r) for r in cur.fetchall()]


def _reject_unknown_cols(spec: TableSpec, data: dict) -> None:
    allowed = set(spec.columns)
    bad = [k for k in data if k not in allowed]
    if bad:
        raise KnownError(
            "INVALID_INPUT",
            f"unknown columns for {spec.table}: {sorted(bad)}",
            {"allowed": sorted(allowed), "got": sorted(bad)},
        )


def insert_row(
    conn: sqlite3.Connection,
    kind: str,
    data: dict,
) -> dict:
    """Insert one row. Fills in id, timestamps, and status if absent.

    * Unknown columns in ``data`` raise ``INVALID_INPUT``.
    * For kinds with ``has_status``, the row is written with ``status = 0``
      if the caller did not set it.
    * For kinds with ``id`` as the primary key and no caller-supplied id,
      a fresh UUID v4 is used.
    * ``created_at``/``updated_at`` default to ``now_epoch()``.

    Returns the row that was written, as a dict.
    """
    spec = _spec(kind)
    _reject_unknown_cols(spec, data)

    row: dict[str, Any] = dict(data)
    now = now_epoch()

    if spec.key == "id" and "id" not in row:
        row["id"] = new_uuid()

    for ts in spec.timestamp_cols:
        if ts in spec.columns and ts not in row:
            row[ts] = now

    if spec.has_status and "status" in spec.columns and "status" not in row:
        row["status"] = 0

    # Write the columns in the spec's declared order so the resulting SQL is
    # stable and tests can assert on it when useful.
    cols = [c for c in spec.columns if c in row]
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    params = [row[c] for c in cols]

    try:
        conn.execute(
            f"INSERT INTO {spec.table} ({col_list}) VALUES ({placeholders})",
            params,
        )
    except sqlite3.IntegrityError as e:
        raise KnownError(
            "CONSTRAINT_VIOLATION",
            str(e),
            {"table": spec.table},
        ) from e

    # Read the row back so the caller gets every column, including any
    # defaulted by the DB.
    key_val = [row[c] for c in spec.composite_key] if spec.key == "composite" else row[spec.key]

    where, where_params = _key_clause(spec, key_val)
    cur = conn.execute(f"SELECT * FROM {spec.table} WHERE {where} LIMIT 1", where_params)
    fetched = _row_to_dict(cur.fetchone())
    # Fall back to the constructed row if, somehow, the read-back missed.
    return fetched if fetched is not None else row


def update_row(
    conn: sqlite3.Connection,
    kind: str,
    key: Any,
    data: dict,
) -> dict:
    """Update mutable columns on one row and return the updated row.

    * Attempts to change ``id``, ``created_at``, or ``status`` raise
      ``INVALID_INPUT``.
    * Unknown columns raise ``INVALID_INPUT``.
    * Missing or soft-deleted target raises ``NOT_FOUND``.
    * ``updated_at`` is always set to ``now_epoch()`` when the table has it.
    """
    spec = _spec(kind)
    _reject_unknown_cols(spec, data)

    forbidden = {"id", "created_at", "status"} & set(data.keys())
    if forbidden:
        raise KnownError(
            "INVALID_INPUT",
            f"columns not updatable: {sorted(forbidden)}",
            {"forbidden": sorted(forbidden)},
        )

    # Build SET clause.
    set_cols: list[str] = []
    set_params: list[Any] = []
    for col, val in data.items():
        set_cols.append(f"{col} = ?")
        set_params.append(val)

    if "updated_at" in spec.columns and "updated_at" not in data:
        set_cols.append("updated_at = ?")
        set_params.append(now_epoch())

    if not set_cols:
        # Nothing to change; behave like NOT_FOUND check only.
        existing = get_row(conn, kind, key)
        if existing is None:
            raise KnownError(
                "NOT_FOUND",
                f"{spec.table} not found or soft-deleted",
                {"kind": kind, "key": key},
            )
        return existing

    where, where_params = _key_clause(spec, key)
    sql = f"UPDATE {spec.table} SET {', '.join(set_cols)} WHERE {where}"
    if spec.has_status:
        sql += " AND status = 0"

    try:
        cur = conn.execute(sql, set_params + where_params)
    except sqlite3.IntegrityError as e:
        raise KnownError(
            "CONSTRAINT_VIOLATION",
            str(e),
            {"table": spec.table},
        ) from e

    if cur.rowcount == 0:
        raise KnownError(
            "NOT_FOUND",
            f"{spec.table} not found or soft-deleted",
            {"kind": kind, "key": key},
        )

    updated = get_row(conn, kind, key)
    if updated is None:
        # Extremely unlikely: the row was visible for the UPDATE but gone now.
        raise KnownError(
            "NOT_FOUND",
            f"{spec.table} not found after update",
            {"kind": kind, "key": key},
        )
    return updated


def soft_delete_row(
    conn: sqlite3.Connection,
    kind: str,
    key: Any,
) -> bool:
    """Flip ``status`` from 0 to 1 on one row.

    Returns ``True`` if a row was flipped, ``False`` if it was already
    soft-deleted, missing, or on a table without ``status``. The caller
    decides whether "missing" is an error.
    """
    spec = _spec(kind)
    if not spec.has_status:
        # Table has no soft-delete concept; the caller shouldn't ask.
        raise KnownError(
            "INVALID_INPUT",
            f"table {spec.table} has no status column",
            {"kind": kind},
        )
    where, where_params = _key_clause(spec, key)
    sql = f"UPDATE {spec.table} SET status = 1, updated_at = ? WHERE {where} AND status = 0"
    cur = conn.execute(sql, [now_epoch(), *where_params])
    return cur.rowcount > 0


def search_rows(
    conn: sqlite3.Connection,
    kind: str,
    term: str,
) -> list[dict]:
    """Case-insensitive substring search against ``spec.searchable_columns``.

    The caller is expected to have URL-decoded ``term`` already. Rows with
    ``status = 1`` are hidden. Results are ordered by ``name ASC, id ASC``.
    A kind with no searchable columns returns an empty list.
    """
    spec = _spec(kind)
    if not spec.searchable_columns:
        return []
    like_fragments = [
        f"LOWER({col}) LIKE '%' || LOWER(?) || '%'" for col in spec.searchable_columns
    ]
    sql = f"SELECT * FROM {spec.table} WHERE "
    if spec.has_status:
        sql += "status = 0 AND "
    sql += "(" + " OR ".join(like_fragments) + ")"
    sql += " ORDER BY name, id"
    params = [term] * len(spec.searchable_columns)
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]
