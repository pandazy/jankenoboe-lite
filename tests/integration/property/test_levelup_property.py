"""Property 4 from requirements.md: level-up moves up by one.

For any learning record L with ``graduated = 0`` and stored level ``L0``:

1. After ``learning.py levelup --ids [L.id]``, the new level
   ``L1 == min(L0 + 1, Max_Level)``.
2. ``L1 - L0 ∈ {0, 1}``.
3. ``L1 <= Max_Level``.
4. ``last_level_up_at == now_epoch``.
5. If ``L0 == Max_Level``, then ``graduated == 1`` after the call.

Expected to FAIL until ``scripts/learning.py`` lands (Task 8).
"""

from __future__ import annotations

import random
import sqlite3

from scripts import _common
from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 5
MAX_LEVEL = _common.MAX_LEVEL


def _select_learning(app_root, lid: str) -> dict:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM learning WHERE id = ?", (lid,)).fetchone()
        assert row is not None, f"learning {lid} not found"
        return dict(row)
    finally:
        conn.close()


def test_levelup_increments_by_one_below_max(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """Non-graduated rows below MAX_LEVEL climb by exactly one."""
    rng = random.Random(SEED)
    artist_id = insert_artist(tmp_app_root, name="Prop4")
    for _ in range(ITERATIONS):
        song_id = insert_song(tmp_app_root, name=f"S-{rng.randint(0, 10**9)}", artist_id=artist_id)
        l0 = rng.randint(0, MAX_LEVEL - 1)
        lid = insert_learning(
            tmp_app_root,
            song_id=song_id,
            level=l0,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
            last_level_up_at=1_699_000_000,
        )
        rc, _out, err = pinned_call(
            "learning.py", "levelup", "--ids", lid, cwd=tmp_app_root, now=pinned_now
        )
        assert rc == 0, err
        after = _select_learning(tmp_app_root, lid)
        assert after["level"] == l0 + 1
        assert after["graduated"] == 0
        assert after["last_level_up_at"] == pinned_now
        assert after["updated_at"] == pinned_now


def test_levelup_at_max_level_graduates(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """At MAX_LEVEL, levelup sets graduated = 1 and leaves level alone."""
    artist_id = insert_artist(tmp_app_root, name="Prop4-MAX")
    # Iterate through several rows at MAX_LEVEL so random selection doesn't
    # skip this case — the property must hold for every such row.
    ids = []
    for i in range(ITERATIONS):
        song_id = insert_song(tmp_app_root, name=f"MAX-{i}", artist_id=artist_id)
        ids.append(
            insert_learning(
                tmp_app_root,
                song_id=song_id,
                level=MAX_LEVEL,
                created_at=1_699_000_000,
                updated_at=1_699_000_000,
                last_level_up_at=1_699_000_000,
            )
        )
    for lid in ids:
        rc, _out, err = pinned_call(
            "learning.py", "levelup", "--ids", lid, cwd=tmp_app_root, now=pinned_now
        )
        assert rc == 0, err
        after = _select_learning(tmp_app_root, lid)
        assert after["level"] == MAX_LEVEL
        assert after["graduated"] == 1
        assert after["updated_at"] == pinned_now
        # last_level_up_at unchanged per R6.6
        assert after["last_level_up_at"] == 1_699_000_000


def test_levelup_rejects_graduated_with_already_graduated(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """Per R6.7: any graduated id in the batch aborts the whole call.

    No rows should change. The stderr envelope must carry
    ``code = "ALREADY_GRADUATED"`` with the offending ids.
    """
    artist_id = insert_artist(tmp_app_root, name="Prop4-graduated")
    song = insert_song(tmp_app_root, name="grad-song", artist_id=artist_id)
    graduated_id = insert_learning(
        tmp_app_root,
        song_id=song,
        level=5,
        graduated=1,
        created_at=1_699_000_000,
        updated_at=1_699_000_000,
        last_level_up_at=1_699_000_000,
    )
    active_song = insert_song(tmp_app_root, name="active-song", artist_id=artist_id)
    active_id = insert_learning(
        tmp_app_root,
        song_id=active_song,
        level=3,
        graduated=0,
        created_at=1_699_000_000,
        updated_at=1_699_000_000,
        last_level_up_at=1_699_000_000,
    )

    rc, _out, err = pinned_call(
        "learning.py",
        "levelup",
        "--ids",
        f"{graduated_id},{active_id}",
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert '"ALREADY_GRADUATED"' in err

    # The active row must still be at level 3 — no partial writes.
    before_active = _select_learning(tmp_app_root, active_id)
    assert before_active["level"] == 3
    assert before_active["updated_at"] == 1_699_000_000
