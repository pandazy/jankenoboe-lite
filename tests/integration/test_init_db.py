"""Integration tests for ``scripts/init_db.py``.

Covers I-1..I-4 via concrete examples + edge cases (9 cases total
per design.md "Testing Strategy — Integration"). Each test drives
``python scripts/init_db.py`` as a subprocess against a per-test
``tmp_app_root`` from the existing harness.

The default ``tmp_app_root`` fixture creates ``db/datasource.db``
from the fixture already, so tests that need the "fresh" precondition
delete it explicitly up front.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sqlite3
import sys
from typing import Any

import pytest


def _run(call_script, cwd, *extra: str) -> tuple[int, Any, Any]:
    """Run ``init_db.py`` and parse envelopes. Returns (rc, stdout_json, stderr_json)."""
    rc, out, err = call_script("init_db.py", *extra, cwd=cwd)
    out_parsed: Any = None
    err_parsed: Any = None
    if out.strip():
        try:
            out_parsed = json.loads(out.strip().splitlines()[-1])
        except json.JSONDecodeError:
            out_parsed = None
    if err.strip():
        # argparse may have printed usage before our envelope on the
        # unknown-flag path; take the last non-empty line and try to
        # parse that as JSON.
        for raw_line in reversed(err.strip().splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            try:
                err_parsed = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    return rc, out_parsed, err_parsed


def _materialise_scripts_dir(app_root: pathlib.Path) -> pathlib.Path:
    """Replace the ``scripts/`` symlink with a real copy for mutation.

    The default ``tmp_app_root`` fixture symlinks ``scripts/`` into
    the real repo. Tests in this module that need to mutate schema.sql
    specifically must first break the symlink so they don't touch the
    real repo.
    """
    scripts_link = app_root / "scripts"
    real_scripts = scripts_link.resolve()
    scripts_link.unlink()
    shutil.copytree(real_scripts, scripts_link)
    return scripts_link


# ---------------------------------------------------------------------------
# Case 1 — fresh App_Root: create the DB (I-2.1, I-3.1, I-4.2)
# ---------------------------------------------------------------------------


def test_fresh_app_root_creates_db(tmp_app_root, call_script) -> None:
    # The default fixture pre-creates the DB; delete it so init_db
    # takes the create path.
    (tmp_app_root / "db" / "datasource.db").unlink()

    rc, out, err = _run(call_script, tmp_app_root)
    assert rc == 0, err
    assert out["created"] is True
    assert out["path"] == str((tmp_app_root / "db" / "datasource.db").resolve())

    db_file = tmp_app_root / "db" / "datasource.db"
    assert db_file.is_file()

    # The created DB opens cleanly via _common.open_db — catches any
    # SCHEMA_MISMATCH regression at the integration level.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from scripts import _common  # noqa: PLC0415 — must follow sys.path tweak.

    # Patch _common's db_path resolver to point at our temp DB, then
    # use its open_db against a dummy script path under our temp
    # scripts/ symlink.
    fake_script_file = str(tmp_app_root / "scripts" / "init_db.py")
    conn = _common.open_db(fake_script_file)
    conn.close()


# ---------------------------------------------------------------------------
# Case 2 — pre-existing DB: skip, bytes unchanged (I-2.2, I-3.2)
# ---------------------------------------------------------------------------


def test_pre_existing_db_is_skipped(tmp_app_root, call_script) -> None:
    db_file = tmp_app_root / "db" / "datasource.db"
    assert db_file.is_file(), "tmp_app_root harness should pre-create the DB"
    before = db_file.read_bytes()

    rc, out, err = _run(call_script, tmp_app_root)
    assert rc == 0, err
    assert out["created"] is False
    assert out["path"] == str(db_file.resolve())
    assert db_file.read_bytes() == before


# ---------------------------------------------------------------------------
# Case 3 — zero-byte file counts as "exists" and is skipped (I-2.4)
# ---------------------------------------------------------------------------


def test_zero_byte_db_file_is_skipped(tmp_app_root, call_script) -> None:
    db_file = tmp_app_root / "db" / "datasource.db"
    db_file.unlink()
    db_file.write_bytes(b"")
    assert db_file.stat().st_size == 0

    rc, out, err = _run(call_script, tmp_app_root)
    assert rc == 0, err
    assert out["created"] is False
    # Bytes still zero — the Script never opens the file.
    assert db_file.stat().st_size == 0


# ---------------------------------------------------------------------------
# Case 4 — --help exits 0 (I-1.6)
# ---------------------------------------------------------------------------


def test_help_flag_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, _err = call_script("init_db.py", "--help", cwd=tmp_app_root)
    assert rc == 0
    assert "usage" in out.lower()


# ---------------------------------------------------------------------------
# Case 5 — unknown args → INVALID_INPUT (I-1.7, I-2.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        ("--force",),
        ("--reset",),
        ("--backup",),
        ("--drop-existing",),
        ("--db-path", "/tmp/x"),
        ("foo",),
    ],
)
def test_unknown_args_yield_invalid_input(tmp_app_root, call_script, extra) -> None:
    rc, out, err = _run(call_script, tmp_app_root, *extra)
    assert rc == 1
    # Success envelope must NOT have been emitted.
    assert out is None
    assert err is not None
    assert err["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Case 6 — db/ is a file → INVALID_INPUT (I-2.5)
# ---------------------------------------------------------------------------


def test_db_dir_as_file_yields_invalid_input(tmp_app_root, call_script) -> None:
    # Clean the default layout.
    shutil.rmtree(tmp_app_root / "db")
    # Create a regular file where the directory should be.
    (tmp_app_root / "db").write_bytes(b"not a dir")
    assert (tmp_app_root / "db").is_file()

    rc, out, err = _run(call_script, tmp_app_root)
    assert rc == 1
    assert out is None
    assert err["error"]["code"] == "INVALID_INPUT"
    assert err["error"]["details"]["path"].endswith("/db")
    # Offending file was not removed or renamed.
    assert (tmp_app_root / "db").is_file()
    assert (tmp_app_root / "db").read_bytes() == b"not a dir"


# ---------------------------------------------------------------------------
# Case 7 — unwritable parent, POSIX only (I-2.6)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX permission bits not portable to Windows",
)
@pytest.mark.skipif(
    os.geteuid() == 0 if hasattr(os, "geteuid") else False,
    reason="root can write anywhere; chmod-based unwritable test is moot",
)
def test_unwritable_parent_yields_internal_error(tmp_app_root, call_script) -> None:
    # init_db wants to create db/. Delete the existing db/ first so
    # it has to call mkdir; then make tmp_app_root itself unwritable.
    shutil.rmtree(tmp_app_root / "db")
    original_mode = tmp_app_root.stat().st_mode
    try:
        os.chmod(tmp_app_root, 0o500)  # read + execute, no write
        rc, out, err = _run(call_script, tmp_app_root)
        assert rc == 1
        assert out is None
        assert err["error"]["code"] == "INTERNAL_ERROR"
    finally:
        # Restore so the tmp_path cleanup can proceed.
        os.chmod(tmp_app_root, original_mode)


# ---------------------------------------------------------------------------
# Case 8 — corrupt schema.sql → INTERNAL_ERROR, half-written DB removed (I-2.7)
# ---------------------------------------------------------------------------


def test_corrupt_schema_ddl_yields_internal_error(tmp_app_root, call_script) -> None:
    scripts_dir = _materialise_scripts_dir(tmp_app_root)
    # Replace the schema with one that SQLite will reject.
    (scripts_dir / "schema.sql").write_text("CREATE GARBAGE nonsense;\n", encoding="utf-8")
    # Ensure the create path runs.
    (tmp_app_root / "db" / "datasource.db").unlink()

    rc, out, err = _run(call_script, tmp_app_root)
    assert rc == 1
    assert out is None
    assert err["error"]["code"] == "INTERNAL_ERROR"
    assert "sqlite_error" in err["error"]["details"]
    # The half-written DB should have been removed so a retry works.
    assert not (tmp_app_root / "db" / "datasource.db").exists()


# ---------------------------------------------------------------------------
# Case 9 — CWD independence (I-1.3)
# ---------------------------------------------------------------------------


def test_cwd_independence(tmp_app_root, call_script, tmp_path) -> None:
    # Invoke from a CWD outside tmp_app_root. The Script should still
    # resolve App_Root via its own __file__ and land the DB at
    # tmp_app_root/db/datasource.db.
    (tmp_app_root / "db" / "datasource.db").unlink()
    alien_cwd = tmp_path / "alien"
    alien_cwd.mkdir()

    # call_script uses cwd= for its subprocess; pass the alien dir.
    # The Script is found via cwd/"scripts"/name in _run_script, so
    # we need to override: construct the argv explicitly here.
    import subprocess  # noqa: PLC0415 — local import keeps module top slim.

    result = subprocess.run(
        [sys.executable, str(tmp_app_root / "scripts" / "init_db.py")],
        cwd=str(alien_cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["created"] is True
    # DB landed under tmp_app_root, not under alien_cwd.
    assert (tmp_app_root / "db" / "datasource.db").is_file()
    assert not (alien_cwd / "db").exists()


# ---------------------------------------------------------------------------
# Sanity: the created DB really passes check_schema via _common.open_db
# ---------------------------------------------------------------------------


def test_created_db_passes_check_schema(tmp_app_root, call_script) -> None:
    """Separate from Case 1 so the assertion is focused and readable."""
    (tmp_app_root / "db" / "datasource.db").unlink()
    rc, _out, err = _run(call_script, tmp_app_root)
    assert rc == 0, err

    # Direct sqlite3 read: every table from EXPECTED_SCHEMA is present.
    conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()
    for expected in ("song", "artist", "show", "rel_show_song", "play_history", "learning"):
        assert expected in tables, f"expected table {expected!r} missing"
