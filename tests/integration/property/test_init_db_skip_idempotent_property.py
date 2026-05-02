"""Property I-1 — skip-idempotency on an existing DB.

For each iteration: seed a schema-valid randomised DB under
``tmp_app_root``, snapshot the full subtree as ``{relpath: bytes}``,
then run ``init_db.py`` k times. After every run: exit 0,
Init_Success_Skipped envelope, and the subtree snapshot unchanged.
"""

from __future__ import annotations

import json
import random

from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 200


def _snapshot_tree(root) -> dict[str, bytes]:
    """Every regular file under ``root`` as ``{relpath: bytes}``.

    Symlinks are skipped so the test's view of ``scripts/`` (which
    is a symlink into the real repo under the integration harness)
    doesn't drag along the rest of the repo.
    """
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        out[str(path.relative_to(root))] = path.read_bytes()
    return out


def _seed_random_rows(
    rng: random.Random,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
    app_root,
) -> None:
    n_artists = rng.randint(0, 3)
    n_songs = rng.randint(0, 5)
    n_shows = rng.randint(0, 3)
    artist_ids = [insert_artist(app_root, name=f"A-{i}") for i in range(n_artists)]
    song_ids: list[str] = []
    if artist_ids:
        for i in range(n_songs):
            aid = rng.choice(artist_ids)
            song_ids.append(insert_song(app_root, name=f"S-{i}", artist_id=aid))
    show_ids = [insert_show(app_root, name=f"Sh-{i}") for i in range(n_shows)]
    for sid in song_ids:
        if show_ids and rng.random() < 0.5:
            insert_rel(app_root, show_id=rng.choice(show_ids), song_id=sid)
        if show_ids and rng.random() < 0.3:
            insert_play_history(app_root, show_id=rng.choice(show_ids), song_id=sid, media_url="")
    for sid in song_ids:
        if rng.random() < 0.5:
            insert_learning(app_root, song_id=sid)


def test_skip_is_idempotent(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    rng = random.Random(SEED)

    # Pre-populate the DB with random rows once per test (not per
    # iteration — each iteration re-runs init_db against the same
    # already-existing DB).
    _seed_random_rows(
        rng,
        insert_artist,
        insert_song,
        insert_show,
        insert_rel,
        insert_play_history,
        insert_learning,
        tmp_app_root,
    )

    db_file = tmp_app_root / "db" / "datasource.db"
    assert db_file.is_file()

    before = _snapshot_tree(tmp_app_root)

    for _ in range(ITERATIONS):
        k = rng.randint(1, 5)
        for _ in range(k):
            rc, out, err = call_script("init_db.py", cwd=tmp_app_root)
            assert rc == 0, err
            payload = json.loads(out.strip())
            assert payload["created"] is False
            assert payload["path"].endswith("/datasource.db")
        after = _snapshot_tree(tmp_app_root)
        assert after == before
