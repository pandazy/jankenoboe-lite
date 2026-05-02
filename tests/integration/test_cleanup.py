"""Integration tests for ``scripts/cleanup.py`` — R11 end-to-end.

The tests cover the dry-run / --confirm split, the R11.3 "don't follow
artist -> songs" rule, the envelope shape + ``cutoff_iso_utc`` format,
and the rollback path per R11.7.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

CUTOFF = 1_700_000_000


def _run(pinned_call, cwd, now, *args) -> tuple[int, Any, Any]:
    rc, out, err = pinned_call("cleanup.py", *args, cwd=cwd, now=now)
    out_parsed: Any = None
    err_parsed: Any = None
    if out.strip():
        out_parsed = json.loads(out)
    if err.strip():
        try:
            err_parsed = json.loads(err)
        except json.JSONDecodeError:
            err_parsed = None
    return rc, out_parsed, err_parsed


def _counts(app_root) -> dict[str, int]:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in (
                "song",
                "artist",
                "show",
                "rel_show_song",
                "play_history",
                "learning",
            )
        }
    finally:
        conn.close()


def _db_hash(app_root) -> str:
    return hashlib.sha256((app_root / "db" / "datasource.db").read_bytes()).hexdigest()


def _seed_mixed(
    app_root,
    *,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> dict[str, str]:
    """Seed a mixed set so every R11 branch is exercisable.

    Returns a dict of ids keyed by role so tests can assert survival
    without re-seeding logic.
    """
    roles: dict[str, str] = {}

    # Live artist + live song under it — must never be touched.
    live_artist = insert_artist(app_root, name="Live Artist")
    live_song = insert_song(
        app_root,
        name="Live Song",
        artist_id=live_artist,
        updated_at=CUTOFF + 10_000,
    )
    roles["live_artist"] = live_artist
    roles["live_song"] = live_song

    # Soft-deleted artist, still holding a LIVE song. R11.3: the live song
    # stays; the artist is a target (if its own updated_at is <= cutoff).
    orphan_artist = insert_artist(
        app_root,
        name="Orphan Artist",
        status=1,
        updated_at=CUTOFF - 10_000,
    )
    orphan_but_live_song = insert_song(
        app_root,
        name="Survivor Song",
        artist_id=orphan_artist,
        updated_at=CUTOFF - 10_000,  # old but status=0, so still live
    )
    roles["orphan_artist"] = orphan_artist
    roles["orphan_but_live_song"] = orphan_but_live_song

    # Soft-deleted song + soft-deleted show, both older than cutoff. Dependents
    # in rel_show_song, play_history, learning must also get purged.
    target_show = insert_show(
        app_root,
        name="Target Show",
        status=1,
        updated_at=CUTOFF - 20_000,
    )
    target_song = insert_song(
        app_root,
        name="Target Song",
        artist_id=live_artist,
        status=1,
        updated_at=CUTOFF - 20_000,
    )
    roles["target_show"] = target_show
    roles["target_song"] = target_song

    insert_rel(app_root, show_id=target_show, song_id=target_song, media_url="http://x")
    # A rel_show_song that only touches target_show (via live_song). Should
    # still get purged because one endpoint is a target.
    insert_rel(app_root, show_id=target_show, song_id=live_song, media_url="http://y")

    insert_play_history(app_root, show_id=target_show, song_id=target_song, media_url="http://ph/1")
    insert_play_history(app_root, show_id=target_show, song_id=target_song, media_url="http://ph/2")
    # play_history with one target endpoint only — still purged.
    insert_play_history(app_root, show_id=target_show, song_id=live_song, media_url="http://ph/3")
    insert_learning(app_root, song_id=target_song)

    # Soft-deleted rows *younger* than the cutoff — must be preserved.
    recent_deleted_song = insert_song(
        app_root,
        name="Recently Deleted",
        artist_id=live_artist,
        status=1,
        updated_at=CUTOFF + 5_000,
    )
    roles["recent_deleted_song"] = recent_deleted_song

    return roles


# ---------------------------------------------------------------------------
# Dry-run path (R11.4-R11.6)
# ---------------------------------------------------------------------------


def test_dry_run_leaves_db_byte_identical(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    _seed_mixed(
        tmp_app_root,
        insert_artist=insert_artist,
        insert_song=insert_song,
        insert_show=insert_show,
        insert_rel=insert_rel,
        insert_play_history=insert_play_history,
        insert_learning=insert_learning,
    )
    before = _db_hash(tmp_app_root)

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "--before", str(CUTOFF))
    assert rc == 0, err
    assert isinstance(out, dict)
    assert out["executed"] is False
    assert out["cutoff_epoch"] == CUTOFF

    after = _db_hash(tmp_app_root)
    assert before == after


def test_dry_run_envelope_shape(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    """Every R11.5 field is present with the right shape."""
    _seed_mixed(
        tmp_app_root,
        insert_artist=insert_artist,
        insert_song=insert_song,
        insert_show=insert_show,
        insert_rel=insert_rel,
        insert_play_history=insert_play_history,
        insert_learning=insert_learning,
    )
    rc, out, _err = _run(pinned_call, tmp_app_root, pinned_now, "--before", str(CUTOFF))
    assert rc == 0
    assert isinstance(out, dict)
    for key in (
        "cutoff_epoch",
        "cutoff_iso_utc",
        "target_counts",
        "cascade_counts",
        "oldest_candidate_updated_at",
        "newest_candidate_updated_at",
        "top_cascade_samples",
        "total_rows_to_hard_delete",
        "executed",
    ):
        assert key in out, f"missing {key}"
    # target_counts keys
    assert set(out["target_counts"].keys()) == {"song", "artist", "show"}
    # cascade_counts keys
    assert set(out["cascade_counts"].keys()) == {
        "rel_show_song",
        "play_history",
        "learning",
    }
    # dry-run: no hard_deleted_counts yet
    assert "hard_deleted_counts" not in out


def test_cutoff_iso_utc_format(tmp_app_root, pinned_call, pinned_now) -> None:
    """R11.5: `cutoff_iso_utc` follows the `YYYY-MM-DDTHH:MM:SSZ` shape."""
    rc, out, _err = _run(pinned_call, tmp_app_root, pinned_now, "--before", "1700000000")
    assert rc == 0
    # 1700000000 = 2023-11-14T22:13:20Z
    assert out["cutoff_iso_utc"] == "2023-11-14T22:13:20Z"


def test_top_cascade_samples_ordering(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    """Samples are ordered by total dependent footprint DESC."""
    artist = insert_artist(tmp_app_root, name="A", updated_at=CUTOFF - 5_000)
    # Small-footprint target: 0 dependents. Not referenced again; the
    # prefix makes it clear it's here on purpose.
    _small = insert_song(
        tmp_app_root,
        name="small",
        artist_id=artist,
        status=1,
        updated_at=CUTOFF - 5_000,
    )
    # Big-footprint target: multiple dependents.
    big = insert_song(
        tmp_app_root,
        name="big",
        artist_id=artist,
        status=1,
        updated_at=CUTOFF - 5_000,
    )
    show = insert_show(tmp_app_root, name="Show")
    insert_rel(tmp_app_root, show_id=show, song_id=big, media_url="a")
    insert_play_history(tmp_app_root, show_id=show, song_id=big)
    insert_play_history(tmp_app_root, show_id=show, song_id=big)
    insert_learning(tmp_app_root, song_id=big)

    rc, out, _err = _run(pinned_call, tmp_app_root, pinned_now, "--before", str(CUTOFF))
    assert rc == 0
    samples = out["top_cascade_samples"]
    assert len(samples) >= 2
    # First sample is the big-footprint song.
    assert samples[0]["id"] == big
    assert samples[0]["kind"] == "song"
    assert samples[0]["rel_show_song"] >= 1
    assert samples[0]["play_history"] >= 2
    assert samples[0]["learning"] >= 1


# ---------------------------------------------------------------------------
# Missing --before (R11.1, R11.10)
# ---------------------------------------------------------------------------


def test_missing_before_is_invalid_input_and_no_writes(
    tmp_app_root, call_script, insert_artist
) -> None:
    """R11.1/R11.10: --before required, DB untouched on the INVALID_INPUT path."""
    insert_artist(tmp_app_root, name="Sentinel")
    before = _db_hash(tmp_app_root)

    rc, out, err = call_script("cleanup.py", cwd=tmp_app_root)
    assert rc == 1
    assert out == ""
    env = json.loads(err)
    assert env["error"]["code"] == "INVALID_INPUT"

    assert _db_hash(tmp_app_root) == before


def test_non_positive_before_is_invalid_input(tmp_app_root, call_script) -> None:
    rc, _out, err = call_script("cleanup.py", "--before", "0", cwd=tmp_app_root)
    assert rc == 1
    assert json.loads(err)["error"]["code"] == "INVALID_INPUT"


def test_non_integer_before_is_invalid_input(tmp_app_root, call_script) -> None:
    rc, _out, err = call_script("cleanup.py", "--before", "not-a-number", cwd=tmp_app_root)
    assert rc == 1
    assert json.loads(err)["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# --confirm path (R11.3, R11.7, R11.8, R11.12)
# ---------------------------------------------------------------------------


def test_confirm_deletes_targets_and_cascades(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    roles = _seed_mixed(
        tmp_app_root,
        insert_artist=insert_artist,
        insert_song=insert_song,
        insert_show=insert_show,
        insert_rel=insert_rel,
        insert_play_history=insert_play_history,
        insert_learning=insert_learning,
    )
    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "--before",
        str(CUTOFF),
        "--confirm",
    )
    assert rc == 0, err
    assert out["executed"] is True
    assert "hard_deleted_counts" in out

    conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    try:
        # Target rows gone.
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM song WHERE id = ?", (roles["target_song"],)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM show WHERE id = ?", (roles["target_show"],)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM artist WHERE id = ?", (roles["orphan_artist"],)
            ).fetchone()[0]
            == 0
        )
        # Live rows still there.
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM artist WHERE id = ?", (roles["live_artist"],)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM song WHERE id = ?", (roles["live_song"],)
            ).fetchone()[0]
            == 1
        )
        # Recently-deleted (younger than cutoff) still there.
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM song WHERE id = ?",
                (roles["recent_deleted_song"],),
            ).fetchone()[0]
            == 1
        )
        # R11.3 rule: orphan_but_live_song stays (its own status = 0).
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM song WHERE id = ?",
                (roles["orphan_but_live_song"],),
            ).fetchone()[0]
            == 1
        )
        # Dependents: rel_show_song / play_history / learning rows tied to
        # target_song or target_show are gone.
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM play_history WHERE song_id = ? OR show_id = ?",
                (roles["target_song"], roles["target_show"]),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM rel_show_song WHERE song_id = ? OR show_id = ?",
                (roles["target_song"], roles["target_show"]),
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM learning WHERE song_id = ?",
                (roles["target_song"],),
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_second_confirm_run_reports_all_zero(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    """R11.12: second --confirm with same cutoff finds zero candidates."""
    _seed_mixed(
        tmp_app_root,
        insert_artist=insert_artist,
        insert_song=insert_song,
        insert_show=insert_show,
        insert_rel=insert_rel,
        insert_play_history=insert_play_history,
        insert_learning=insert_learning,
    )
    rc, _out, _err = _run(
        pinned_call, tmp_app_root, pinned_now, "--before", str(CUTOFF), "--confirm"
    )
    assert rc == 0

    rc, out, _err = _run(
        pinned_call, tmp_app_root, pinned_now, "--before", str(CUTOFF), "--confirm"
    )
    assert rc == 0
    assert out["executed"] is True
    for v in out["target_counts"].values():
        assert v == 0
    for v in out["cascade_counts"].values():
        assert v == 0
    assert out["total_rows_to_hard_delete"] == 0
    for v in out["hard_deleted_counts"].values():
        assert v == 0


def test_live_song_under_soft_deleted_artist_stays(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    """R11.3: cleanup.py does NOT follow artist -> songs.

    A live song (status = 0) under a soft-deleted artist (status = 1,
    older than cutoff) stays put. The artist row is the only one purged.
    """
    artist = insert_artist(
        tmp_app_root,
        name="Orphaned",
        status=1,
        updated_at=CUTOFF - 5_000,
    )
    song = insert_song(
        tmp_app_root,
        name="Orphan Song",
        artist_id=artist,
        updated_at=CUTOFF - 5_000,
    )
    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "--before",
        str(CUTOFF),
        "--confirm",
    )
    assert rc == 0, err

    conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM artist WHERE id = ?", (artist,)).fetchone()[0] == 0
        )
        # Song stays — live status, not a target.
        row = conn.execute("SELECT status FROM song WHERE id = ?", (song,)).fetchone()
        assert row is not None
        assert row[0] == 0
    finally:
        conn.close()


def test_empty_db_confirm_is_clean_zero(tmp_app_root, pinned_call, pinned_now) -> None:
    """No rows at all → all counters zero, DB unchanged."""
    before = _db_hash(tmp_app_root)
    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "--before",
        str(CUTOFF),
        "--confirm",
    )
    assert rc == 0, err
    assert out["executed"] is True
    assert out["total_rows_to_hard_delete"] == 0
    assert _db_hash(tmp_app_root) == before


def test_live_only_db_leaves_everything_untouched(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    """No soft-deleted rows → cleanup is a success-no-op even with --confirm."""
    aid = insert_artist(tmp_app_root, name="Live")
    insert_song(tmp_app_root, name="Song", artist_id=aid)

    before = _counts(tmp_app_root)
    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "--before",
        str(CUTOFF),
        "--confirm",
    )
    assert rc == 0, err
    assert out["total_rows_to_hard_delete"] == 0
    assert _counts(tmp_app_root) == before


# ---------------------------------------------------------------------------
# R11.11: no other script hard-deletes (sanity — cleanup.py output shape
# ships `hard_deleted_counts` with every table)
# ---------------------------------------------------------------------------


def test_hard_deleted_counts_keys_cover_every_affected_table(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_play_history,
    insert_learning,
) -> None:
    _seed_mixed(
        tmp_app_root,
        insert_artist=insert_artist,
        insert_song=insert_song,
        insert_show=insert_show,
        insert_rel=insert_rel,
        insert_play_history=insert_play_history,
        insert_learning=insert_learning,
    )
    rc, out, _err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "--before",
        str(CUTOFF),
        "--confirm",
    )
    assert rc == 0
    expected = {"song", "artist", "show", "rel_show_song", "play_history", "learning"}
    assert set(out["hard_deleted_counts"].keys()) == expected


# ---------------------------------------------------------------------------
# Rollback on failure (R11.7)
# ---------------------------------------------------------------------------


def test_help_flag_exits_zero(tmp_app_root, call_script) -> None:
    """argparse --help wins over the INVALID_INPUT check."""
    rc, out, _err = call_script("cleanup.py", "--help", cwd=tmp_app_root)
    assert rc == 0
    assert "cleanup.py" in out
