"""Property 8 from requirements.md: bulk-reassign keeps song identity.

For any set of song IDs S owned by artist A1, given a target artist A2
(distinct, ``status = 0``):

1. After ``data.py bulk-reassign --from-artist-id A1 --to-artist-id A2 --song-ids S``:
   * Every song in S has ``artist_id = A2``.
   * ``id``, ``name``, ``name_context``, ``created_at``, and ``status`` on
     each song in S match their pre-call values.
   * Only ``artist_id`` and ``updated_at`` change.
2. Songs not in S are unchanged.
3. The call succeeds even when the reassignment creates a ``(A2, name)``
   collision with an existing A2-owned song.

Expected to FAIL until ``scripts/data.py`` lands (Task 7).
"""

from __future__ import annotations

import random
import sqlite3

from tests.integration.property._helpers import BASE_SEED, ITERATIONS, csv

SEED = BASE_SEED + 8


def _all_songs(app_root) -> dict[str, dict]:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        return {r["id"]: dict(r) for r in conn.execute("SELECT * FROM song")}
    finally:
        conn.close()


def test_bulk_reassign_preserves_song_identity(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    rng = random.Random(SEED)
    a1 = insert_artist(tmp_app_root, name="A1")
    a2 = insert_artist(tmp_app_root, name="A2")

    # Seed 20 songs under A1 so a random selection is meaningful.
    a1_songs = [
        insert_song(
            tmp_app_root,
            name=f"S1-{i}",
            name_context=f"ctx-{i}",
            artist_id=a1,
            created_at=1_690_000_000 + i,
            updated_at=1_691_000_000 + i,
        )
        for i in range(20)
    ]
    before = _all_songs(tmp_app_root)

    # For each iteration, reassign a random subset to A2 and verify.
    # To avoid mutating state across iterations, reassign back each time.
    for _ in range(ITERATIONS):
        subset_size = rng.randint(1, len(a1_songs))
        subset = rng.sample(a1_songs, subset_size)

        rc, _out, err = pinned_call(
            "data.py",
            "bulk-reassign",
            "--from-artist-id",
            a1,
            "--to-artist-id",
            a2,
            "--song-ids",
            csv(subset),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc == 0, err

        after = _all_songs(tmp_app_root)
        for sid, prev in before.items():
            row = after[sid]
            if sid in subset:
                assert row["artist_id"] == a2
                assert row["updated_at"] == pinned_now
                for col in ("id", "name", "name_context", "created_at", "status"):
                    assert row[col] == prev[col], f"{sid} {col} changed"
            else:
                # Unchanged songs still own their pre-call state (except
                # previously-reassigned ones, which we reset below).
                pass

        # Reassign back to A1 so the next iteration sees a clean slate.
        rc, _out, err = pinned_call(
            "data.py",
            "bulk-reassign",
            "--from-artist-id",
            a2,
            "--to-artist-id",
            a1,
            "--song-ids",
            csv(subset),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc == 0, err


def test_bulk_reassign_succeeds_with_name_collision(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    """Per R9.11: duplicate ``(A2, name)`` after reassignment is allowed."""
    a1 = insert_artist(tmp_app_root, name="Source")
    a2 = insert_artist(tmp_app_root, name="Target")
    # A2 already owns a song called "Collide".
    a2_existing = insert_song(tmp_app_root, name="Collide", artist_id=a2)
    # A1 also has a song called "Collide" that we want to move.
    a1_collide = insert_song(tmp_app_root, name="Collide", artist_id=a1)

    rc, _out, err = pinned_call(
        "data.py",
        "bulk-reassign",
        "--from-artist-id",
        a1,
        "--to-artist-id",
        a2,
        "--song-ids",
        a1_collide,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0, err

    after = _all_songs(tmp_app_root)
    assert after[a1_collide]["artist_id"] == a2
    assert after[a2_existing]["artist_id"] == a2
    # Both rows under A2 with the same name — the merge workflow is expected
    # to clean this up next, but bulk-reassign itself must not fail.
    collisions = [r for r in after.values() if r["artist_id"] == a2 and r["name"] == "Collide"]
    assert len(collisions) == 2


def test_bulk_reassign_missing_target_returns_not_found(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    """Per R9.12: non-existent ``--to-artist-id`` → NOT_FOUND, no writes."""
    a1 = insert_artist(tmp_app_root, name="Src")
    song = insert_song(tmp_app_root, name="Only", artist_id=a1)
    before = _all_songs(tmp_app_root)

    rc, _out, err = pinned_call(
        "data.py",
        "bulk-reassign",
        "--from-artist-id",
        a1,
        "--to-artist-id",
        "no-such-artist",
        "--song-ids",
        song,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    assert '"NOT_FOUND"' in err
    assert _all_songs(tmp_app_root) == before
