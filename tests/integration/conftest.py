"""Integration test harness.

Every integration test runs against its own temp `App_Root` with a fresh
SQLite DB built from `tests/fixtures/schema.sql`. Tests never touch the
real `db/datasource.db` — the top-level `tests/conftest.py` has a guard
fixture that fails the suite on any change to the real DB.

Fixtures:
  * ``tmp_app_root``     — per-test temp App_Root with ``scripts/`` symlinked
                           and a fresh empty DB under ``db/datasource.db``.
  * ``pinned_now``       — fixed epoch seconds for deterministic time.
  * ``call_script``      — subprocess helper to invoke scripts like a user.
  * ``pinned_call``      — ``call_script`` variant that pins the clock.
  * ``temp_conn``        — short-lived sqlite3 connection to the temp DB.
  * ``insert_*`` helpers — write rows straight to the temp DB, bypass scripts.
"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMA_SQL = REPO_ROOT / "tests" / "fixtures" / "schema.sql"

# Fixed epoch used by the ``pinned_now`` fixture. Picked to be well clear of
# zero (so "older than now" comparisons work) and well before ``time.time()``
# for any realistic test run.
PINNED_EPOCH = 1_700_000_000


# ---------------------------------------------------------------------------
# Temp App_Root
# ---------------------------------------------------------------------------


def _apply_schema(db_file: pathlib.Path) -> None:
    """Build a fresh DB at ``db_file`` from ``tests/fixtures/schema.sql``."""
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_file))
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def tmp_app_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """A temp App_Root per test.

    Layout under ``tmp_path``::

        <tmp_path>/
          scripts -> <repo>/scripts        (symlink)
          db/
            datasource.db                  (fresh, schema only)

    Because each script resolves its DB path from ``__file__`` (``parent.parent
    / "db" / "datasource.db"``), running it with ``cwd=tmp_path`` and invoking
    it through the symlinked ``scripts/`` folder opens the temp DB, not the
    real one.
    """
    (tmp_path / "scripts").symlink_to(SCRIPTS_DIR)
    (tmp_path / "db").mkdir()
    _apply_schema(tmp_path / "db" / "datasource.db")
    return tmp_path


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_script(
    name: str,
    *args: str,
    cwd: pathlib.Path,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> tuple[int, str, str]:
    """Run a script through the symlinked ``scripts/`` dir under ``cwd``.

    Returns ``(returncode, stdout, stderr)``. Uses ``sys.executable`` so the
    child inherits the same Python interpreter the tests run under. Merges
    ``env`` into ``os.environ`` rather than replacing it, so unrelated env
    vars the interpreter needs (``PATH``, ``PYTHONHOME``, etc.) survive.
    """
    script_path = cwd / "scripts" / name
    cmd = [sys.executable, str(script_path), *args]
    merged_env = {**os.environ, **(env or {})}
    # Keep the child out of the repo's pyproject-driven cwd confusion by
    # running it from the temp App_Root — that's also where App_Root/db
    # lives from the script's perspective.
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=merged_env,
        input=stdin,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture
def call_script() -> Callable[..., tuple[int, str, str]]:
    """Return a ``call_script(name, *args, cwd, env=None, stdin=None)`` helper.

    Typical use::

        rc, out, err = call_script("query.py", "search", "--kind", "song",
                                    "--term", "foo", cwd=tmp_app_root)
    """
    return _run_script


# ---------------------------------------------------------------------------
# Time seam
# ---------------------------------------------------------------------------


@pytest.fixture
def pinned_now() -> int:
    """Fixed epoch seconds used when a test pins the clock."""
    return PINNED_EPOCH


@pytest.fixture
def pinned_call(pinned_now: int) -> Callable[..., tuple[int, str, str]]:
    """``call_script`` variant that sets ``JANKENOBOE_TEST_NOW=pinned_now``.

    Useful for write-path tests that assert on ``created_at``/``updated_at``.
    Extra env vars can still be merged in via ``env=...``.
    """

    def _call(
        name: str,
        *args: str,
        cwd: pathlib.Path,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        now: int | None = None,
    ) -> tuple[int, str, str]:
        now_val = pinned_now if now is None else now
        merged = {"JANKENOBOE_TEST_NOW": str(now_val)}
        if env:
            merged.update(env)
        return _run_script(name, *args, cwd=cwd, env=merged, stdin=stdin)

    return _call


# ---------------------------------------------------------------------------
# Direct DB access (setup only)
# ---------------------------------------------------------------------------


def _temp_db_path(app_root: pathlib.Path) -> pathlib.Path:
    """Path to the temp ``datasource.db``. Raises if used against the real one."""
    path = (app_root / "db" / "datasource.db").resolve()
    real = (REPO_ROOT / "db" / "datasource.db").resolve()
    if path == real:
        # Last-ditch safety net. The session-scoped guard catches this too,
        # but failing early gives a clearer message.
        raise RuntimeError("refusing to open the real db/datasource.db from a test helper")
    return path


def _connect(app_root: pathlib.Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_temp_db_path(app_root)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture
def temp_conn(tmp_app_root: pathlib.Path) -> Iterator[sqlite3.Connection]:
    """Short-lived sqlite3 connection to the temp DB.

    Handy for read-side assertions in integration tests. Writes are
    permitted too, but prefer the ``insert_*`` helpers below for seeding
    so the intent is clear.
    """
    conn = _connect(tmp_app_root)
    try:
        yield conn
    finally:
        conn.close()


def _gen_id() -> str:
    return str(uuid.uuid4())


def _insert_song(
    app_root: pathlib.Path,
    *,
    id: str | None = None,
    name: str,
    artist_id: str,
    name_context: str = "",
    created_at: int = PINNED_EPOCH,
    updated_at: int | None = None,
    status: int = 0,
) -> str:
    sid = id or _gen_id()
    upd = updated_at if updated_at is not None else created_at
    conn = _connect(app_root)
    try:
        conn.execute(
            "INSERT INTO song (id, name, name_context, artist_id, "
            "created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, name, name_context, artist_id, created_at, upd, status),
        )
        conn.commit()
    finally:
        conn.close()
    return sid


def _insert_artist(
    app_root: pathlib.Path,
    *,
    id: str | None = None,
    name: str,
    name_context: str = "",
    created_at: int = PINNED_EPOCH,
    updated_at: int | None = None,
    status: int = 0,
) -> str:
    aid = id or _gen_id()
    upd = updated_at if updated_at is not None else created_at
    conn = _connect(app_root)
    try:
        conn.execute(
            "INSERT INTO artist (id, name, name_context, created_at, "
            "updated_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (aid, name, name_context, created_at, upd, status),
        )
        conn.commit()
    finally:
        conn.close()
    return aid


def _insert_show(
    app_root: pathlib.Path,
    *,
    id: str | None = None,
    name: str,
    name_romaji: str | None = None,
    vintage: str | None = None,
    s_type: str | None = None,
    created_at: int = PINNED_EPOCH,
    updated_at: int | None = None,
    status: int = 0,
) -> str:
    sid = id or _gen_id()
    upd = updated_at if updated_at is not None else created_at
    conn = _connect(app_root)
    try:
        conn.execute(
            "INSERT INTO show (id, name, name_romaji, vintage, s_type, "
            "created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, name, name_romaji, vintage, s_type, created_at, upd, status),
        )
        conn.commit()
    finally:
        conn.close()
    return sid


def _insert_rel(
    app_root: pathlib.Path,
    *,
    show_id: str,
    song_id: str,
    media_url: str | None = None,
    created_at: int = PINNED_EPOCH,
) -> None:
    conn = _connect(app_root)
    try:
        conn.execute(
            "INSERT INTO rel_show_song (show_id, song_id, media_url, created_at) "
            "VALUES (?, ?, ?, ?)",
            (show_id, song_id, media_url, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_learning(
    app_root: pathlib.Path,
    *,
    id: str | None = None,
    song_id: str,
    level: int = 0,
    graduated: int = 0,
    created_at: int = PINNED_EPOCH,
    updated_at: int | None = None,
    last_level_up_at: int | None = None,
    level_up_path: str | list[int] | None = None,
) -> str:
    lid = id or _gen_id()
    upd = updated_at if updated_at is not None else created_at
    last_up = last_level_up_at if last_level_up_at is not None else created_at
    if level_up_path is None:
        # Match the default path from _common.DEFAULT_LEVEL_UP_PATH.
        lup = json.dumps([1, 1, 1, 1, 1, 1, 1, 2, 3, 5, 7, 13, 19, 32, 52, 84, 135, 220, 355, 574])
    elif isinstance(level_up_path, str):
        lup = level_up_path
    else:
        lup = json.dumps(list(level_up_path))
    conn = _connect(app_root)
    try:
        conn.execute(
            "INSERT INTO learning (id, song_id, level, created_at, updated_at, "
            "last_level_up_at, level_up_path, graduated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (lid, song_id, level, created_at, upd, last_up, lup, graduated),
        )
        conn.commit()
    finally:
        conn.close()
    return lid


def _insert_play_history(
    app_root: pathlib.Path,
    *,
    id: str | None = None,
    show_id: str,
    song_id: str,
    media_url: str = "",
    created_at: int = PINNED_EPOCH,
    status: int = 0,
) -> str:
    pid = id or _gen_id()
    conn = _connect(app_root)
    try:
        conn.execute(
            "INSERT INTO play_history (id, show_id, song_id, created_at, "
            "media_url, status) VALUES (?, ?, ?, ?, ?, ?)",
            (pid, show_id, song_id, created_at, media_url, status),
        )
        conn.commit()
    finally:
        conn.close()
    return pid


@pytest.fixture
def insert_song() -> Callable[..., str]:
    """Return a ``insert_song(app_root, *, name, artist_id, ...)`` helper.

    Returns the new row's id. ``created_at`` defaults to ``PINNED_EPOCH``,
    ``updated_at`` mirrors ``created_at``, ``status`` is 0, ``name_context``
    is empty. Any of these can be overridden per call.
    """
    return _insert_song


@pytest.fixture
def insert_artist() -> Callable[..., str]:
    """Return a ``insert_artist(app_root, *, name, ...)`` helper."""
    return _insert_artist


@pytest.fixture
def insert_show() -> Callable[..., str]:
    """Return a ``insert_show(app_root, *, name, ...)`` helper."""
    return _insert_show


@pytest.fixture
def insert_rel() -> Callable[..., None]:
    """Return a ``insert_rel(app_root, *, show_id, song_id, ...)`` helper."""
    return _insert_rel


@pytest.fixture
def insert_learning() -> Callable[..., str]:
    """Return a ``insert_learning(app_root, *, song_id, ...)`` helper."""
    return _insert_learning


@pytest.fixture
def insert_play_history() -> Callable[..., str]:
    """Return a ``insert_play_history(app_root, *, show_id, song_id, ...)`` helper."""
    return _insert_play_history


# ---------------------------------------------------------------------------
# Small convenience helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def parse_json() -> Callable[[str], Any]:
    """Return a helper that parses a JSON string and asserts it's not empty.

    Integration tests call scripts and then parse stdout. Putting this in a
    fixture lets the assertion message reference the test name.
    """

    def _parse(raw: str) -> Any:
        assert raw.strip(), "expected non-empty JSON on stdout"
        return json.loads(raw)

    return _parse
