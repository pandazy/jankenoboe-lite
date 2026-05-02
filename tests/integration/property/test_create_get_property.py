"""Property 1 from requirements.md: create then get is a round-trip.

For a random valid ``--data`` payload for ``data.py create`` on kind K in
``{song, artist, show}``:

1. Create a row with that payload.
2. Run ``query.py get`` on the returned ID.
3. The returned row contains every field from the create payload (after URL
   decoding), plus a generated ``id``, ``created_at``, ``updated_at``, and
   ``status = 0``.

Expected to FAIL until ``scripts/data.py`` and ``scripts/query.py`` land
(Tasks 6 and 7). The test is structured so the failure is a clear subprocess
exit-code mismatch, not an import error.
"""

from __future__ import annotations

import random

from tests.integration.property._helpers import (
    BASE_SEED,
    ITERATIONS,
    json_arg,
    parse_stdout_json,
    random_artist_data,
    random_show_data,
    random_song_data,
)

SEED = BASE_SEED + 3


def _create(call, cwd, kind: str, data: dict, *, now: str = "1700000000") -> dict:
    """Run ``data.py create --kind K --data JSON`` and return the row."""
    rc, out, err = call(
        "data.py",
        "create",
        "--kind",
        kind,
        "--data",
        json_arg(data),
        cwd=cwd,
        env={"JANKENOBOE_TEST_NOW": now},
    )
    assert rc == 0, f"create {kind} failed: rc={rc} err={err!r}"
    parsed = parse_stdout_json(out)
    assert isinstance(parsed, dict)
    return parsed


def _get(call, cwd, kind: str, row_id: str) -> dict:
    """Run ``query.py get --kind K --id ID`` and return the row."""
    rc, out, err = call(
        "query.py",
        "get",
        "--kind",
        kind,
        "--id",
        row_id,
        cwd=cwd,
    )
    assert rc == 0, f"get {kind} {row_id} failed: rc={rc} err={err!r}"
    parsed = parse_stdout_json(out)
    assert isinstance(parsed, dict)
    return parsed


def _assert_round_trip(
    created: dict,
    fetched: dict,
    payload: dict,
    *,
    now_epoch: int,
) -> None:
    """Every payload field is preserved; ``id``, timestamps, and ``status`` set."""
    # Common required fields.
    assert "id" in fetched and isinstance(fetched["id"], str) and fetched["id"]
    assert created["id"] == fetched["id"]
    assert fetched["status"] == 0
    assert fetched["created_at"] == now_epoch
    assert fetched["updated_at"] == now_epoch
    # Every payload key is preserved.
    for k, v in payload.items():
        assert fetched[k] == v, f"field {k!r}: expected {v!r}, got {fetched[k]!r}"


def test_create_get_artist_round_trip(tmp_app_root, pinned_call, pinned_now) -> None:
    rng = random.Random(SEED)
    for _ in range(ITERATIONS):
        payload = random_artist_data(rng)
        created = _create(pinned_call, tmp_app_root, "artist", payload, now=str(pinned_now))
        fetched = _get(pinned_call, tmp_app_root, "artist", created["id"])
        _assert_round_trip(created, fetched, payload, now_epoch=pinned_now)


def test_create_get_song_round_trip(tmp_app_root, pinned_call, pinned_now, insert_artist) -> None:
    """Songs need an ``artist_id``, so seed one live artist via the direct
    helper and create a batch of songs under it.
    """
    artist_id = insert_artist(tmp_app_root, name="Prop1 Artist")
    rng = random.Random(SEED + 1)
    for _ in range(ITERATIONS):
        payload = random_song_data(rng, artist_id=artist_id)
        created = _create(pinned_call, tmp_app_root, "song", payload, now=str(pinned_now))
        fetched = _get(pinned_call, tmp_app_root, "song", created["id"])
        _assert_round_trip(created, fetched, payload, now_epoch=pinned_now)


def test_create_get_show_round_trip(tmp_app_root, pinned_call, pinned_now) -> None:
    rng = random.Random(SEED + 2)
    for _ in range(ITERATIONS):
        payload = random_show_data(rng)
        created = _create(pinned_call, tmp_app_root, "show", payload, now=str(pinned_now))
        fetched = _get(pinned_call, tmp_app_root, "show", created["id"])
        _assert_round_trip(created, fetched, payload, now_epoch=pinned_now)


def test_create_decodes_url_encoded_name(tmp_app_root, pinned_call, pinned_now) -> None:
    """A payload with ``%20`` in the name should decode exactly once on create,
    and the decoded form is what ``get`` returns — verifying the decode runs
    at the ``data.py create`` boundary, not twice somewhere along the chain.
    """
    payload = {"name": "hello%20world", "name_context": "solo%2Bside"}
    created = _create(pinned_call, tmp_app_root, "artist", payload, now=str(pinned_now))
    fetched = _get(pinned_call, tmp_app_root, "artist", created["id"])
    assert fetched["name"] == "hello world"
    assert fetched["name_context"] == "solo+side"
    assert fetched["status"] == 0
