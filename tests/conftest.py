"""Top-level pytest conftest.

Two jobs:

1. Put the repo root on ``sys.path`` so tests can do
   ``from scripts import _common`` without per-file path shims.

2. Guard the real ``db/datasource.db`` against accidental access from the
   test suite. The guard is a session-scoped autouse fixture: it records
   the real DB's size and mtime at session start, and at session end
   fails the suite with a clear message if either changed. If the file
   appeared or disappeared during the session, that also fails. This
   makes "no tests touch the real DB" mechanical, not a convention.
"""

from __future__ import annotations

import os
import pathlib
import sys
from collections.abc import Iterator

import pytest

# Put the repo root first on sys.path. The repo root is the parent of the
# tests/ directory this file lives in.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Real DB guard
# ---------------------------------------------------------------------------

_REAL_DB = pathlib.Path(_REPO_ROOT) / "db" / "datasource.db"


def _snapshot() -> tuple[bool, int, int] | None:
    """Return ``(exists, size, mtime_ns)`` for the real DB, or ``None`` if
    the DB file itself isn't on disk (in which case we record "missing").

    Returning a plain tuple keeps equality cheap and serializable.
    """
    if _REAL_DB.exists():
        st = _REAL_DB.stat()
        return (True, st.st_size, st.st_mtime_ns)
    return (False, 0, 0)


@pytest.fixture(scope="session", autouse=True)
def _guard_real_db() -> Iterator[None]:
    """Fail the suite if anything changes the real ``db/datasource.db``.

    Session-scoped + autouse so it wraps every test. ``pytest.fail`` in the
    teardown marks the whole session as failed even when every individual
    test passed — which is exactly what we want if a test wrote to the real
    DB.
    """
    before = _snapshot()
    yield
    after = _snapshot()
    if before != after:
        pytest.fail(
            "Tests must not read, write, create, or modify the real "
            f"{_REAL_DB.relative_to(_REPO_ROOT)}. "
            "Use the tmp_app_root fixture or :memory: instead. "
            f"before={before!r} after={after!r}",
            pytrace=False,
        )
