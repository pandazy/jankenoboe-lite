"""Assert ``scripts/schema.sql`` is a byte-for-byte copy of the fixture.

``scripts/schema.sql`` is a generated-but-committed artifact: it's
produced by ``make schema-sync`` from ``tests/fixtures/schema.sql``,
which in turn is produced by ``tests/fixtures/dump_schema.py``.
Runtime (``scripts/init_db.py``) and package time
(``tools/package.py._empty_db``) both read ``scripts/schema.sql``,
while the integration harness and the dump helper work with
``tests/fixtures/schema.sql``. This test is the single guardrail
keeping those two bytes in sync — without it the two files can
silently drift and the deployed DB can disagree with the one the
tests apply to temp App_Roots.

Fix for a failing run: ``make schema-sync``.
"""

from __future__ import annotations

import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "schema.sql"
_RUNTIME = _REPO_ROOT / "scripts" / "schema.sql"


def test_schema_files_are_byte_identical() -> None:
    """``scripts/schema.sql`` must equal ``tests/fixtures/schema.sql`` byte-for-byte.

    Run ``make schema-sync`` to fix a failing run.
    """
    assert _FIXTURE.is_file(), f"fixture missing at {_FIXTURE}"
    assert _RUNTIME.is_file(), (
        f"runtime schema missing at {_RUNTIME}. "
        "Run `make schema-sync` to create it from the fixture."
    )

    fixture_bytes = _FIXTURE.read_bytes()
    runtime_bytes = _RUNTIME.read_bytes()
    assert fixture_bytes == runtime_bytes, (
        "scripts/schema.sql has drifted from tests/fixtures/schema.sql. "
        "Run `make schema-sync` to re-copy the fixture."
    )
