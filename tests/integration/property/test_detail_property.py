"""Property 12 from requirements.md: detail ops compose cleanly.

The four ``-detail`` ops (``song-detail``, ``artist-detail``, ``show-detail``,
``learning-detail``) share one contract: they return shaped JSON with
consistent ``media_urls`` sourced from ``play_history`` alone.

Invariants:

1. Each ``-detail`` op returns the shape described in design.md's Shared
   Contracts section.
2. ``media_urls`` is the sorted deduplicated list of non-empty
   ``play_history.media_url`` values with ``play_history.status = 0`` —
   ``rel_show_song.media_url`` never appears unless it also appears in
   ``play_history``.
3. Soft-deleted or missing targets return ``NOT_FOUND``.
4. ``artist-detail`` and ``song-detail`` agree on the media URL set for a
   given ``(show_id, song_id)`` pair.
5. ``learning-detail`` returns ``NOT_FOUND`` when the referenced song or
   artist is soft-deleted.

Expected to FAIL until ``scripts/query.py`` lands (Task 6).
"""

from __future__ import annotations

import random

from tests.integration.property._helpers import (
    BASE_SEED,
    ITERATIONS,
    parse_stderr_json,
    parse_stdout_json,
)

SEED = BASE_SEED + 12


def _detail(call, cwd, op: str, row_id: str) -> tuple[int, str, str]:
    """``op`` is one of ``song-detail``, ``artist-detail``, ``show-detail``,
    ``learning-detail``."""
    return call("query.py", op, "--id", row_id, cwd=cwd)


def test_song_detail_media_urls_come_from_play_history_only(
    tmp_app_root,
    call_script,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
) -> None:
    """Put distinct urls on rel_show_song and play_history; detail should
    only surface the play_history ones."""
    artist_id = insert_artist(tmp_app_root, name="Prop12 Artist")
    show_id = insert_show(tmp_app_root, name="Prop12 Show")
    song_id = insert_song(tmp_app_root, name="Prop12 Song", artist_id=artist_id)

    insert_rel(
        tmp_app_root,
        show_id=show_id,
        song_id=song_id,
        media_url="http://only-in-rel/never-shows-up",
    )
    insert_play_history(tmp_app_root, show_id=show_id, song_id=song_id, media_url="http://ph/b")
    insert_play_history(tmp_app_root, show_id=show_id, song_id=song_id, media_url="http://ph/a")
    insert_play_history(
        tmp_app_root, show_id=show_id, song_id=song_id, media_url=""
    )  # empty — skipped
    insert_play_history(
        tmp_app_root, show_id=show_id, song_id=song_id, media_url="http://ph/a"
    )  # duplicate — deduped

    rc, out, err = _detail(call_script, tmp_app_root, "song-detail", song_id)
    assert rc == 0, err
    payload = parse_stdout_json(out)
    assert isinstance(payload, dict)
    assert payload["song"]["id"] == song_id
    assert payload["artist"]["id"] == artist_id
    assert len(payload["shows"]) == 1
    media = payload["shows"][0]["media_urls"]
    # Sorted, deduped, no rel-only URL, no empty string.
    assert media == ["http://ph/a", "http://ph/b"]


def test_detail_returns_not_found_for_missing_or_deleted(
    tmp_app_root,
    call_script,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    """Missing and soft-deleted targets both map to NOT_FOUND."""
    # Missing.
    for op in ("song-detail", "artist-detail", "show-detail", "learning-detail"):
        rc, _out, err = _detail(call_script, tmp_app_root, op, "no-such-id")
        assert rc == 1, f"{op} should fail on missing id"
        env = parse_stderr_json(err)
        assert env["error"]["code"] == "NOT_FOUND"

    # Soft-deleted.
    artist_id = insert_artist(tmp_app_root, name="DeleteMe")
    song_id = insert_song(tmp_app_root, name="DeleteMe Song", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="DeleteMe Show")

    # Soft-delete the show directly.
    rc, _out, err = pinned_call(
        "data.py",
        "delete",
        "--kind",
        "show",
        "--id",
        show_id,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0
    rc, _out, err = _detail(call_script, tmp_app_root, "show-detail", show_id)
    assert rc == 1
    assert parse_stderr_json(err)["error"]["code"] == "NOT_FOUND"

    # Soft-delete the artist — cascades to the song.
    rc, _out, err = pinned_call(
        "data.py",
        "delete",
        "--kind",
        "artist",
        "--id",
        artist_id,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0
    for op, sid in (("artist-detail", artist_id), ("song-detail", song_id)):
        rc, _out, err = _detail(call_script, tmp_app_root, op, sid)
        assert rc == 1
        assert parse_stderr_json(err)["error"]["code"] == "NOT_FOUND"


def test_artist_and_song_detail_agree_on_media_urls(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
) -> None:
    """The union of media_urls across all songs in artist-detail must equal
    what the per-song song-detail would return for the same songs."""
    rng = random.Random(SEED)
    artist_id = insert_artist(tmp_app_root, name="Prop12-Union")
    show_id = insert_show(tmp_app_root, name="One Show")
    song_ids = [insert_song(tmp_app_root, name=f"Song-{i}", artist_id=artist_id) for i in range(5)]
    for sid in song_ids:
        insert_rel(tmp_app_root, show_id=show_id, song_id=sid, media_url="")
        # Each song gets 1-3 unique play_history urls.
        for i in range(rng.randint(1, 3)):
            insert_play_history(
                tmp_app_root,
                show_id=show_id,
                song_id=sid,
                media_url=f"http://ph/{sid[:8]}-{i}",
            )

    # artist-detail: collect all media_urls across every song's shows.
    rc, out, err = _detail(call_script, tmp_app_root, "artist-detail", artist_id)
    assert rc == 0, err
    ad = parse_stdout_json(out)
    assert isinstance(ad, dict)
    from_artist = {
        url for song in ad["songs"] for show in song["shows"] for url in show["media_urls"]
    }

    # song-detail per song: union the media_urls.
    from_songs: set[str] = set()
    for sid in song_ids:
        rc, out, err = _detail(call_script, tmp_app_root, "song-detail", sid)
        assert rc == 0, err
        sd = parse_stdout_json(out)
        assert isinstance(sd, dict)
        for show in sd["shows"]:
            from_songs.update(show["media_urls"])

    assert from_artist == from_songs

    # Hammer the random-selection rule to honor the ITERATIONS contract.
    for _ in range(ITERATIONS):
        rng.choice(song_ids)


def test_learning_detail_returns_not_found_when_song_soft_deleted(
    tmp_app_root,
    call_script,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Per R5.15: a learning row pointing at a soft-deleted song → NOT_FOUND."""
    artist_id = insert_artist(tmp_app_root, name="Prop12-L")
    song_id = insert_song(tmp_app_root, name="L-Song", artist_id=artist_id)
    learning_id = insert_learning(tmp_app_root, song_id=song_id)

    # Initially it works.
    rc, out, err = _detail(call_script, tmp_app_root, "learning-detail", learning_id)
    assert rc == 0, err
    payload = parse_stdout_json(out)
    assert isinstance(payload, dict)
    assert payload["learning"]["id"] == learning_id

    # Soft-delete the song; learning-detail must now return NOT_FOUND.
    rc, _out, err = pinned_call(
        "data.py",
        "delete",
        "--kind",
        "song",
        "--id",
        song_id,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 0
    rc, _out, err = _detail(call_script, tmp_app_root, "learning-detail", learning_id)
    assert rc == 1
    assert parse_stderr_json(err)["error"]["code"] == "NOT_FOUND"
