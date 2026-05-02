"""Create App_Root/db/datasource.db on first use. Safe no-op otherwise.

Runtime script. See .kiro/specs/db-init-command/requirements.md for the
full contract. Every skill under skills/*/SKILL.md runs this as its
first step so Claude never hits the parent spec's DB_NOT_FOUND on a
fresh deploy, which is why the skip path is the hot path and this
script goes to some lengths to keep it cheap:

  * No `sqlite3` import at module top — imported lazily inside the
    create path only.
  * No `argparse` import at module top — imported only when argv has
    extras (anything past `sys.argv[0]`).
  * No dependency on ``scripts/_common.py`` (which pulls in sqlite3
    itself). The envelope helpers are duplicated here as ~20 lines,
    a cheap price for a lean skip path.

The create path reads the DDL from ``scripts/schema.sql`` (a
byte-for-byte copy of ``tests/fixtures/schema.sql``, kept in sync by
``make schema-sync``). The same file is read by
``tools/package.py._empty_db`` at package time, so runtime and
packaging share one source of truth for the schema.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import sys

# NOTE: deliberate — no ``import sqlite3``, no ``import argparse`` at
# module top. See the module docstring above.


# Snapshot of modules that were already loaded before this script's code
# started running. Used by ``_maybe_probe_sys_modules`` to report only
# the imports ``init_db.py`` itself triggered, ignoring anything the
# interpreter (or an active coverage harness) brought in at startup.
_MODULES_AT_LOAD = frozenset(sys.modules)

_SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"
_VALID_CODES = {"INVALID_INPUT", "INTERNAL_ERROR"}


class _KnownError(Exception):
    """Locally-mirrored version of ``scripts/_common.KnownError``.

    Duplicated here (rather than imported) so the Script does not
    drag ``scripts/_common`` — and therefore ``sqlite3`` at module
    top — into the skip path.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# ---------------------------------------------------------------------------
# App_Root / db path / envelope helpers
# ---------------------------------------------------------------------------


def _app_root() -> pathlib.Path:
    """Absolute parent of ``scripts/``. Matches ``_common.app_root``.

    Uses ``.absolute()`` not ``.resolve()``: the integration test
    harness symlinks ``scripts/`` into a temp ``App_Root`` and
    ``resolve()`` would follow that symlink back to the real repo.
    """
    return pathlib.Path(__file__).absolute().parent.parent


def _db_path() -> pathlib.Path:
    return _app_root() / "db" / "datasource.db"


def _success(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    sys.exit(0)


def _error(code: str, message: str, details: dict | None = None) -> None:
    # Dev-facing guard — fires only if a new code is introduced without
    # being added to _VALID_CODES.
    assert code in _VALID_CODES, f"unknown error code {code!r}"
    payload = {"error": {"code": code, "message": message, "details": details}}
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stderr.flush()
    sys.exit(1)


# ---------------------------------------------------------------------------
# Property I-6 introspection hook
# ---------------------------------------------------------------------------


def _maybe_probe_sys_modules() -> None:
    """Write a ``__PROBE__`` line to stderr when gated by the env var.

    When ``JANKENOBOE_PROBE_SKIP=1`` is set, report the subset of
    ``{"sqlite3", "argparse"}`` that appeared in ``sys.modules``
    *during this Script's run* — i.e. imports triggered by the
    Script itself, not imports the interpreter or the coverage
    harness brought in at startup. The probe snapshots
    ``sys.modules`` at module top (``_MODULES_AT_LOAD``) and
    reports only the new entries, so a preloaded ``sqlite3``
    (e.g. when ``coverage.sqlitedb`` is active) doesn't create
    false positives on the skip path.

    The probe line lands on stderr so it does not break the
    stdout-only success-envelope contract (I-3.5).
    """
    if os.environ.get("JANKENOBOE_PROBE_SKIP") == "1":
        delta = sorted(
            m for m in sys.modules if m in {"sqlite3", "argparse"} and m not in _MODULES_AT_LOAD
        )
        sys.stderr.write(f"__PROBE__ {json.dumps(delta)}\n")
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def _init_or_skip() -> None:
    """Skip if DB exists, otherwise create from Schema_Source."""
    db = _db_path()
    db_dir = db.parent

    # Skip path. Kept cheap — no DB open, no schema read, no marker
    # files. One Path.exists() is an lstat syscall; on the hot path
    # that's all this Script does beyond interpreter startup.
    if db.exists():
        _maybe_probe_sys_modules()
        _success({"created": False, "path": str(db.resolve())})
        return  # unreachable — _success exits.

    # I-2.5: parent is a file, not a directory.
    if db_dir.exists() and not db_dir.is_dir():
        raise _KnownError(
            "INVALID_INPUT",
            f"db/ exists but is not a directory: {db_dir}",
            {"path": str(db_dir)},
        )

    # Create path. Lazy import — first (and only) place sqlite3
    # lands in sys.modules.
    import sqlite3  # noqa: PLC0415 — deliberate lazy import; see module docstring.

    # I-2.6: parent dir creation may fail (unwritable App_Root).
    try:
        db_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _KnownError(
            "INTERNAL_ERROR",
            f"cannot create db/ directory: {exc}",
            {"path": str(db_dir), "errno": exc.errno},
        ) from exc

    # Read the DDL. A FileNotFoundError here is caught by the outer
    # except in __main__ and becomes INTERNAL_ERROR.
    ddl = _SCHEMA_PATH.read_text(encoding="utf-8")

    conn = sqlite3.connect(str(db))
    try:
        # Mirrors _common.open_db: explicit transaction control.
        # Note: we don't wrap executescript() in BEGIN/COMMIT because
        # executescript() itself issues an implicit COMMIT before
        # running the script, which would trip over our open
        # transaction. It runs its own atomic batch and commits on
        # success. On any sqlite3.Error the file is left in whatever
        # state sqlite stopped at; we unlink below so the next run
        # starts clean.
        conn.isolation_level = None
        try:
            conn.executescript(ddl)
        except sqlite3.Error as exc:
            # I-2.7: DDL failed. Close the connection, remove the
            # half-written file so a retry lands on the create path
            # again. Secondary errors in the close / unlink path are
            # swallowed so the primary DDL error is what the user
            # sees.
            with contextlib.suppress(sqlite3.Error):
                conn.close()
            with contextlib.suppress(OSError):
                db.unlink(missing_ok=True)
            raise _KnownError(
                "INTERNAL_ERROR",
                f"schema DDL failed: {exc}",
                {"sqlite_error": str(exc)},
            ) from exc
    finally:
        # conn may already be closed in the error branch; guard it.
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    _maybe_probe_sys_modules()
    _success({"created": True, "path": str(db.resolve())})


def _main_with_args() -> None:
    """Only reached when ``len(sys.argv) > 1``. Loads argparse lazily."""
    import argparse  # noqa: PLC0415 — deliberate lazy import; see module docstring.

    parser = argparse.ArgumentParser(
        prog="init_db.py",
        description="Create db/datasource.db on first use; no-op if it exists.",
    )
    # argparse's built-in -h/--help is the only supported flag.
    try:
        parser.parse_args()
    except SystemExit as exc:
        # argparse exits 0 on -h/--help; pass that through so the
        # user gets argparse's usage text and exit 0 as usual.
        if (exc.code or 0) == 0:
            raise
        # Anything else (unknown flag, unexpected positional, bad
        # argument type) arrives here with code == 2. Re-emit as our
        # own INVALID_INPUT envelope with exit 1.
        _error(
            "INVALID_INPUT",
            "init_db.py accepts no positional arguments and no flags other than -h/--help",
            {"argv": sys.argv[1:]},
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    try:
        if len(sys.argv) == 1:
            _init_or_skip()
        else:
            _main_with_args()
    except _KnownError as exc:
        _error(exc.code, exc.message, exc.details)
    except Exception as exc:
        _error(
            "INTERNAL_ERROR",
            str(exc) or "internal error",
            {"type": type(exc).__name__},
        )
