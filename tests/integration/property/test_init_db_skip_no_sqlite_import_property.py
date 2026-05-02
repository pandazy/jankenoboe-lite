"""Property I-6 — the skip path doesn't import sqlite3 or argparse.

For each iteration: pre-existing DB, run init_db.py with
``JANKENOBOE_PROBE_SKIP=1``, parse the ``__PROBE__`` line on stderr,
assert neither ``sqlite3`` nor ``argparse`` appears in it.
"""

from __future__ import annotations

import json
import random
import re

from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 205

_PROBE_RE = re.compile(r"^__PROBE__\s+(\[.*\])\s*$", re.MULTILINE)


def test_skip_path_does_not_import_sqlite_or_argparse(
    tmp_app_root,
    call_script,
) -> None:
    rng = random.Random(SEED)

    # Pre-existing DB at the default harness path.
    db_file = tmp_app_root / "db" / "datasource.db"
    assert db_file.is_file()

    for i in range(ITERATIONS):
        # Occasionally add random cruft so the harness state varies.
        if rng.random() < 0.5:
            (tmp_app_root / f"cruft-{i}.txt").write_text("x")

        rc, out, err = call_script(
            "init_db.py",
            cwd=tmp_app_root,
            env={"JANKENOBOE_PROBE_SKIP": "1"},
        )
        assert rc == 0, err
        payload = json.loads(out.strip())
        assert payload["created"] is False

        # Find the probe line.
        match = _PROBE_RE.search(err)
        assert match is not None, f"iter {i}: no __PROBE__ line in stderr: {err!r}"
        probe = json.loads(match.group(1))
        assert isinstance(probe, list)
        assert "sqlite3" not in probe, f"iter {i}: sqlite3 imported on skip path"
        assert "argparse" not in probe, f"iter {i}: argparse imported on skip path"
