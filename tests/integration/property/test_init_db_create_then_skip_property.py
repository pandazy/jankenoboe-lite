"""Property I-4 — create-then-skip is byte-stable.

For each iteration: fresh db/, run init_db once (create), snapshot
the resulting DB_File bytes, run init_db m more times (m in 1..4).
Every re-run asserts Init_Success_Skipped and byte-identical DB.
"""

from __future__ import annotations

import json
import random

from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 203


def test_create_then_skip_is_byte_stable(tmp_app_root, call_script) -> None:
    rng = random.Random(SEED)
    db_file = tmp_app_root / "db" / "datasource.db"

    for i in range(ITERATIONS):
        # Wipe db/ so init_db takes the create path.
        if db_file.exists():
            db_file.unlink()

        rc, out, err = call_script("init_db.py", cwd=tmp_app_root)
        assert rc == 0, err
        payload = json.loads(out.strip())
        assert payload["created"] is True, f"iter {i}: expected create path"
        post_create = db_file.read_bytes()

        m = rng.randint(1, 4)
        for _ in range(m):
            rc, out, err = call_script("init_db.py", cwd=tmp_app_root)
            assert rc == 0, err
            payload = json.loads(out.strip())
            assert payload["created"] is False
            assert db_file.read_bytes() == post_create
