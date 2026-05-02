"""Property I-2 — fresh DB has the expected schema and zero rows.

For each iteration: build a tmp_app_root whose db/ is absent, run
init_db once, assert the created DB opens via _common.open_db
without SCHEMA_MISMATCH, every (table, columns) pair from
EXPECTED_SCHEMA is present, and every table has zero rows.
"""

from __future__ import annotations

import json
import pathlib
import random
import sys

from tests.integration.property._helpers import BASE_SEED, ITERATIONS

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from scripts import _common  # noqa: E402

SEED = BASE_SEED + 201


def test_fresh_db_has_expected_schema(tmp_app_root, call_script) -> None:
    rng = random.Random(SEED)

    for i in range(ITERATIONS):
        # Every iteration: wipe db/ and add random clutter elsewhere.
        db_file = tmp_app_root / "db" / "datasource.db"
        if db_file.exists():
            db_file.unlink()

        # Random non-db clutter in tmp_app_root.
        clutter_dir = tmp_app_root / f"clutter-{i}-{rng.randint(0, 100)}"
        clutter_dir.mkdir(exist_ok=True)
        (clutter_dir / "noise.txt").write_text("noise", encoding="utf-8")

        rc, out, err = call_script("init_db.py", cwd=tmp_app_root)
        assert rc == 0, err
        payload = json.loads(out.strip())
        assert payload["created"] is True
        assert db_file.is_file()

        # open_db runs check_schema — catches any SCHEMA_MISMATCH.
        fake_script = str(tmp_app_root / "scripts" / "init_db.py")
        conn = _common.open_db(fake_script)
        try:
            # Every table from EXPECTED_SCHEMA present with expected columns.
            for table, expected_cols in _common.EXPECTED_SCHEMA.items():
                info = conn.execute(f"PRAGMA table_info({table})").fetchall()
                got_cols = {row["name"] for row in info}
                missing = expected_cols - got_cols
                assert not missing, f"iter {i} table {table!r} missing cols {missing!r}"
                # And every table has zero rows.
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count == 0, f"iter {i} table {table!r} has {count} rows, expected 0"
        finally:
            conn.close()
