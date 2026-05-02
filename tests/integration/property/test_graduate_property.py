"""Property 5 from requirements.md: graduate is safe to repeat.

For any learning record L:

1. After one ``learning.py graduate --ids [L.id]``, ``graduated = 1``.
2. A second call on the same ID leaves ``level`` unchanged and keeps
   ``graduated = 1``.
3. ``graduate`` does not change ``created_at`` or ``id``.

Expected to FAIL until ``scripts/learning.py`` lands (Task 8).
"""

from __future__ import annotations

import random
import sqlite3

from scripts import _common
from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 6
MAX_LEVEL = _common.MAX_LEVEL


def _select_learning(app_root, lid: str) -> dict:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM learning WHERE id = ?", (lid,)).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def test_graduate_sets_flag_and_second_call_is_noop(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    rng = random.Random(SEED)
    artist_id = insert_artist(tmp_app_root, name="Prop5")
    for _ in range(ITERATIONS):
        song_id = insert_song(tmp_app_root, name=f"S-{rng.randint(0, 10**9)}", artist_id=artist_id)
        level = rng.randint(0, MAX_LEVEL)
        graduated = rng.choice([0, 1])
        lid = insert_learning(
            tmp_app_root,
            song_id=song_id,
            level=level,
            graduated=graduated,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
            last_level_up_at=1_699_000_000,
        )
        before = _select_learning(tmp_app_root, lid)

        # First call.
        rc, _out, err = pinned_call(
            "learning.py", "graduate", "--ids", lid, cwd=tmp_app_root, now=pinned_now
        )
        assert rc == 0, err
        mid = _select_learning(tmp_app_root, lid)
        assert mid["graduated"] == 1
        assert mid["level"] == before["level"]
        assert mid["id"] == before["id"]
        assert mid["created_at"] == before["created_at"]

        # Second call is a no-op on that row.
        rc2, _out2, err2 = pinned_call(
            "learning.py",
            "graduate",
            "--ids",
            lid,
            cwd=tmp_app_root,
            now=str(pinned_now + 1),
        )
        assert rc2 == 0, err2
        after = _select_learning(tmp_app_root, lid)
        assert after["graduated"] == 1
        assert after["level"] == before["level"]
        assert after["id"] == before["id"]
        assert after["created_at"] == before["created_at"]


def test_graduate_missing_id_returns_not_found(tmp_app_root, pinned_call, pinned_now) -> None:
    """Per R6.8: a missing id yields NOT_FOUND."""
    rc, _out, err = pinned_call(
        "learning.py",
        "graduate",
        "--ids",
        "no-such-id",
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert '"NOT_FOUND"' in err
