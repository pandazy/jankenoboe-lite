"""PBT for Bug 2: ``learning.py graduate`` pins ``level`` to ``MAX_LEVEL``.

Property 3 (Expected Behavior): For all learning rows L with
``isBugConditionGraduate(L)`` — i.e. ``L.graduated == 0 AND
L.level < MAX_LEVEL`` — after running ``graduate``:

    after.level = MAX_LEVEL
    after.graduated = 1
    after.updated_at = pinned_now
    response payload reports {level = MAX_LEVEL, display_level = MAX_LEVEL + 1,
        graduated = 1, updated_at = pinned_now}

Property 4 (Preservation): For all L where NOT isBugConditionGraduate(L),
``graduate`` produces the same observable row state and response as the
pre-fix behavior:

    * ``L.graduated == 0 AND L.level == MAX_LEVEL`` (non-graduated corner):
      after.level == MAX_LEVEL, after.graduated == 1,
      after.updated_at == pinned_now. The SET ``level = MAX_LEVEL`` is a
      redundant write but produces the same observable state.
    * ``L.graduated == 1`` (no-op path): no UPDATE runs; every field,
      including ``updated_at``, is unchanged from before.

In all cases, identity (``id``, ``song_id``, ``created_at``,
``level_up_path``, ``last_level_up_at``) is preserved per R3.9.
"""

from __future__ import annotations

import json
import random
import sqlite3
from typing import Any

from scripts import _common
from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 207
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


def _run_graduate(pinned_call, cwd, now: int, lid: str) -> tuple[int, Any, str]:
    rc, out, err = pinned_call("learning.py", "graduate", "--ids", lid, cwd=cwd, now=now)
    payload: Any = None
    if out.strip():
        payload = json.loads(out)
    return rc, payload, err


def test_graduate_pins_level_to_max_across_random_rows(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Validates: Properties 3 and 4 from design.md."""
    rng = random.Random(SEED)
    artist_id = insert_artist(tmp_app_root, name="Prop3-4")

    # Pre-existing, distinct timestamp so updated_at/created_at preservation
    # can be verified against a value that is NOT equal to pinned_now.
    seeded_created_at = 1_699_000_000
    seeded_updated_at = 1_699_000_100
    seeded_last_level_up_at = 1_699_000_050

    for i in range(ITERATIONS):
        song_id = insert_song(
            tmp_app_root, name=f"S-{i}-{rng.randint(0, 10**9)}", artist_id=artist_id
        )
        level = rng.randint(0, MAX_LEVEL)
        graduated = rng.choice([0, 1])
        lid = insert_learning(
            tmp_app_root,
            song_id=song_id,
            level=level,
            graduated=graduated,
            created_at=seeded_created_at,
            updated_at=seeded_updated_at,
            last_level_up_at=seeded_last_level_up_at,
        )

        before = _select_learning(tmp_app_root, lid)

        rc, payload, err = _run_graduate(pinned_call, tmp_app_root, pinned_now, lid)
        assert rc == 0, err

        assert payload is not None
        assert len(payload["updated"]) == 1
        entry = payload["updated"][0]
        assert entry["id"] == lid
        assert entry["graduated"] == 1

        after = _select_learning(tmp_app_root, lid)

        if before["graduated"] == 0 and before["level"] < MAX_LEVEL:
            # Property 3 — bug condition: pin level to MAX_LEVEL.
            assert after["level"] == MAX_LEVEL
            assert after["graduated"] == 1
            assert after["updated_at"] == pinned_now
            assert entry["level"] == MAX_LEVEL
            assert entry["display_level"] == MAX_LEVEL + 1
            assert entry["updated_at"] == pinned_now
        elif before["graduated"] == 0 and before["level"] == MAX_LEVEL:
            # Property 4 — non-graduated-at-MAX corner. Redundant SET
            # level = MAX_LEVEL; observable row state is same as bug-condition
            # path.
            assert after["level"] == MAX_LEVEL
            assert after["graduated"] == 1
            assert after["updated_at"] == pinned_now
            assert entry["level"] == MAX_LEVEL
            assert entry["display_level"] == MAX_LEVEL + 1
            assert entry["updated_at"] == pinned_now
        else:
            # Property 4 — already-graduated no-op path: no UPDATE runs,
            # so updated_at is NOT re-stamped. level and graduated unchanged.
            assert before["graduated"] == 1
            assert after["level"] == before["level"]
            assert after["graduated"] == 1
            assert after["updated_at"] == before["updated_at"]
            assert entry["level"] == before["level"]
            assert entry["display_level"] == before["level"] + 1
            assert entry["updated_at"] == before["updated_at"]

        # R3.9: identity, creation, and level-up-history preserved in every branch.
        assert after["id"] == before["id"]
        assert after["song_id"] == before["song_id"]
        assert after["created_at"] == before["created_at"]
        assert after["level_up_path"] == before["level_up_path"]
        assert after["last_level_up_at"] == before["last_level_up_at"]
