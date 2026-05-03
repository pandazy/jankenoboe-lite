"""Integration tests for ``learning.py`` — batch / levelup / graduate / stats.

``due`` has its own test file (``test_due.py``) because it leans on
SQLite's ``strftime('%s','now')`` and needs a different setup pattern.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from scripts import _common


def _run(pinned_call, cwd, now, *args) -> tuple[int, Any, Any]:
    """Run ``learning.py`` with the clock pinned."""
    rc, out, err = pinned_call("learning.py", *args, cwd=cwd, now=now)
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


def _select_learning(app_root, lid: str) -> dict:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM learning WHERE id = ?", (lid,)).fetchone()
        assert row is not None, f"learning {lid} missing"
        return dict(row)
    finally:
        conn.close()


def _count_learning(app_root) -> int:
    conn = sqlite3.connect(str(app_root / "db" / "datasource.db"))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM learning").fetchone()[0])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# batch
# ---------------------------------------------------------------------------


def test_batch_inserts_new_rows_at_level_zero(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song
) -> None:
    """R6.1: brand new song gets level = 0, graduated = 0, timestamps set."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "batch", "--song-ids", sid)
    assert rc == 0, err
    assert len(out["inserted"]) == 1
    assert out["skipped"] == []
    assert out["not_found"] == []
    new = out["inserted"][0]
    assert new["song_id"] == sid
    assert new["level"] == 0
    assert new["display_level"] == 1
    assert new["graduated"] == 0
    assert new["created_at"] == pinned_now
    assert new["updated_at"] == pinned_now
    assert new["last_level_up_at"] == pinned_now

    row = _select_learning(tmp_app_root, new["id"])
    # level_up_path stored as JSON; parse and check it matches DEFAULT.
    assert json.loads(row["level_up_path"]) == _common.DEFAULT_LEVEL_UP_PATH


def test_batch_re_learn_starts_at_level_seven(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R6.3: all existing rows graduated → insert at RE_LEARN_LEVEL (7)."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=10, graduated=1)

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "batch", "--song-ids", sid)
    assert rc == 0, err
    assert len(out["inserted"]) == 1
    new = out["inserted"][0]
    assert new["level"] == _common.RE_LEARN_LEVEL == 7
    assert new["display_level"] == 8
    assert new["graduated"] == 0


def test_batch_skips_when_active_row_exists(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R6.2: existing non-graduated row → song goes into skipped."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=5, graduated=0)

    before = _count_learning(tmp_app_root)
    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "batch", "--song-ids", sid)
    assert rc == 0, err
    assert out["inserted"] == []
    assert out["skipped"] == [sid]
    assert out["not_found"] == []
    assert _count_learning(tmp_app_root) == before


def test_batch_reports_not_found_for_missing_and_soft_deleted_songs(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    """R6.4: missing or soft-deleted song_id → not_found (no insert)."""
    aid = insert_artist(tmp_app_root, name="A")
    live = insert_song(tmp_app_root, name="live", artist_id=aid)
    dead = insert_song(tmp_app_root, name="dead", artist_id=aid, status=1)
    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "batch",
        "--song-ids",
        f"{live},{dead},no-such-id",
    )
    assert rc == 0, err
    assert len(out["inserted"]) == 1
    assert out["inserted"][0]["song_id"] == live
    assert set(out["not_found"]) == {dead, "no-such-id"}


def test_batch_mixed_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """One of each bucket in a single call."""
    aid = insert_artist(tmp_app_root, name="A")
    fresh = insert_song(tmp_app_root, name="fresh", artist_id=aid)
    relearn = insert_song(tmp_app_root, name="relearn", artist_id=aid)
    insert_learning(tmp_app_root, song_id=relearn, graduated=1)
    busy = insert_song(tmp_app_root, name="busy", artist_id=aid)
    insert_learning(tmp_app_root, song_id=busy, graduated=0)

    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "batch",
        "--song-ids",
        f"{fresh},{relearn},{busy},no-such",
    )
    assert rc == 0, err
    inserted_song_ids = {r["song_id"] for r in out["inserted"]}
    assert inserted_song_ids == {fresh, relearn}
    # Which one ended up at which level:
    levels = {r["song_id"]: r["level"] for r in out["inserted"]}
    assert levels[fresh] == 0
    assert levels[relearn] == _common.RE_LEARN_LEVEL
    assert out["skipped"] == [busy]
    assert out["not_found"] == ["no-such"]


# ---------------------------------------------------------------------------
# levelup
# ---------------------------------------------------------------------------


def test_levelup_increments_below_max(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=3,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "levelup", "--ids", lid)
    assert rc == 0, err
    assert len(out["updated"]) == 1
    payload = out["updated"][0]
    assert payload["level"] == 4
    assert payload["display_level"] == 5
    assert payload["graduated"] == 0
    assert payload["last_level_up_at"] == pinned_now
    assert payload["updated_at"] == pinned_now

    row = _select_learning(tmp_app_root, lid)
    assert row["level"] == 4
    assert row["last_level_up_at"] == pinned_now
    assert row["updated_at"] == pinned_now


def test_levelup_at_max_level_graduates(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R6.6: at MAX_LEVEL → set graduated=1; level and last_level_up_at stay put."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=_common.MAX_LEVEL,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "levelup", "--ids", lid)
    assert rc == 0, err
    payload = out["updated"][0]
    assert payload["level"] == _common.MAX_LEVEL
    assert payload["graduated"] == 1
    assert payload["updated_at"] == pinned_now
    assert payload["last_level_up_at"] == 1_690_000_000  # unchanged

    row = _select_learning(tmp_app_root, lid)
    assert row["level"] == _common.MAX_LEVEL
    assert row["graduated"] == 1
    assert row["last_level_up_at"] == 1_690_000_000


def test_levelup_aborts_on_graduated_id(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R6.7: any graduated id in the batch → ALREADY_GRADUATED, no writes anywhere."""
    aid = insert_artist(tmp_app_root, name="A")
    sid1 = insert_song(tmp_app_root, name="live", artist_id=aid)
    sid2 = insert_song(tmp_app_root, name="done", artist_id=aid)
    live_lid = insert_learning(
        tmp_app_root,
        song_id=sid1,
        level=2,
        graduated=0,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    done_lid = insert_learning(
        tmp_app_root,
        song_id=sid2,
        level=_common.MAX_LEVEL,
        graduated=1,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "levelup",
        "--ids",
        f"{live_lid},{done_lid}",
    )
    assert rc == 1
    assert err["error"]["code"] == "ALREADY_GRADUATED"
    assert done_lid in err["error"]["details"]["ids"]

    # Live row untouched (transaction rolled back).
    row = _select_learning(tmp_app_root, live_lid)
    assert row["level"] == 2
    assert row["updated_at"] == 1_690_000_000


def test_levelup_aborts_on_missing_id(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Missing id in batch → NOT_FOUND, no partial writes."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=1,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "levelup",
        "--ids",
        f"{lid},no-such-id",
    )
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"

    row = _select_learning(tmp_app_root, lid)
    assert row["level"] == 1  # unchanged
    assert row["updated_at"] == 1_690_000_000


# ---------------------------------------------------------------------------
# graduate
# ---------------------------------------------------------------------------


def test_graduate_flips_graduated_flag(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(tmp_app_root, song_id=sid, level=5, graduated=0)

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "graduate", "--ids", lid)
    assert rc == 0, err
    assert out["updated"][0]["graduated"] == 1
    assert out["updated"][0]["level"] == _common.MAX_LEVEL
    assert out["updated"][0]["display_level"] == _common.MAX_LEVEL + 1
    assert out["updated"][0]["updated_at"] == pinned_now

    row = _select_learning(tmp_app_root, lid)
    assert row["graduated"] == 1
    assert row["level"] == _common.MAX_LEVEL
    assert row["updated_at"] == pinned_now


def test_graduate_pins_level_to_max_level_on_below_max_start(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R2.10, R2.11: graduate a non-graduated row whose level < MAX_LEVEL must
    pin ``level`` to ``_common.MAX_LEVEL`` (19) AND set ``graduated = 1``,
    leaving ``id``/``song_id``/``created_at`` unchanged. The response payload
    must report ``level = 19`` and ``display_level = 20``.

    This is the Bug 2 exploration test: on unfixed code ``graduate`` flips
    ``graduated`` but leaves ``level`` at its previous value (here, 3). The
    ``row["level"] == _common.MAX_LEVEL`` assertion FAILS — that failure
    confirms the bug exists.
    """
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(tmp_app_root, song_id=sid, level=3, graduated=0)

    before = _select_learning(tmp_app_root, lid)

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "graduate", "--ids", lid)
    assert rc == 0, err

    # Response payload reports the pinned level.
    assert len(out["updated"]) == 1
    payload = out["updated"][0]
    assert payload["id"] == lid
    assert payload["level"] == _common.MAX_LEVEL
    assert payload["display_level"] == _common.MAX_LEVEL + 1
    assert payload["graduated"] == 1

    # Re-read row matches.
    row = _select_learning(tmp_app_root, lid)
    assert row["level"] == _common.MAX_LEVEL
    assert row["graduated"] == 1
    # Identity/creation invariants preserved.
    assert row["id"] == before["id"]
    assert row["song_id"] == before["song_id"]
    assert row["created_at"] == before["created_at"]


@pytest.mark.parametrize("start_level", [0, 3, 10, 18])
def test_graduate_pins_level_to_max_for_all_below_max_starts(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
    start_level: int,
) -> None:
    """R2.10, R2.11, R3.9: for every below-MAX starting level, ``graduate`` pins
    ``level`` to ``MAX_LEVEL`` and sets ``graduated = 1``. The response payload
    and the re-read row must both report the pinned state. ``id``, ``song_id``,
    ``created_at``, ``level_up_path``, and ``last_level_up_at`` are preserved
    (R3.9)."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name=f"S-{start_level}", artist_id=aid)
    lid = insert_learning(tmp_app_root, song_id=sid, level=start_level, graduated=0)

    before = _select_learning(tmp_app_root, lid)

    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "graduate", "--ids", lid)
    assert rc == 0, err

    # Response payload reports the pinned state.
    assert len(out["updated"]) == 1
    payload = out["updated"][0]
    assert payload["id"] == lid
    assert payload["level"] == _common.MAX_LEVEL
    assert payload["display_level"] == _common.MAX_LEVEL + 1
    assert payload["graduated"] == 1

    # Re-read row agrees with the payload.
    row = _select_learning(tmp_app_root, lid)
    assert row["level"] == _common.MAX_LEVEL
    assert row["graduated"] == 1

    # R3.9: identity, creation, and level-up-history fields are preserved.
    assert row["id"] == before["id"]
    assert row["song_id"] == before["song_id"]
    assert row["created_at"] == before["created_at"]
    assert row["level_up_path"] == before["level_up_path"]
    assert row["last_level_up_at"] == before["last_level_up_at"]


def test_graduate_second_call_is_noop(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R6.9: already-graduated → no-op success."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=4,
        graduated=1,
        updated_at=1_690_000_000,
    )
    rc, out, err = _run(pinned_call, tmp_app_root, pinned_now, "graduate", "--ids", lid)
    assert rc == 0, err
    # Returned payload reflects existing state; updated_at kept per no-op.
    payload = out["updated"][0]
    assert payload["graduated"] == 1
    assert payload["level"] == 4

    row = _select_learning(tmp_app_root, lid)
    assert row["updated_at"] == 1_690_000_000  # not re-stamped


def test_graduate_missing_id_is_not_found(tmp_app_root, pinned_call, pinned_now) -> None:
    rc, _out, err = _run(pinned_call, tmp_app_root, pinned_now, "graduate", "--ids", "no-such")
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_stats_counts_by_level_and_graduated(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    aid = insert_artist(tmp_app_root, name="A")
    s1 = insert_song(tmp_app_root, name="s1", artist_id=aid)
    s2 = insert_song(tmp_app_root, name="s2", artist_id=aid)
    s3 = insert_song(tmp_app_root, name="s3", artist_id=aid)
    insert_learning(tmp_app_root, song_id=s1, level=0, graduated=0)
    insert_learning(tmp_app_root, song_id=s2, level=0, graduated=0)
    insert_learning(tmp_app_root, song_id=s3, level=5, graduated=1)

    rc, out, err = call_script("learning.py", "stats", cwd=tmp_app_root)
    assert rc == 0, err
    payload = json.loads(out)
    assert payload["by_level"] == {"0": 2, "5": 1}
    assert payload["by_graduated"] == {"0": 2, "1": 1}
    assert payload["total"] == 3


def test_stats_ignores_soft_deleted_songs(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """R6.10: counts only learning rows whose song has status = 0."""
    aid = insert_artist(tmp_app_root, name="A")
    live = insert_song(tmp_app_root, name="live", artist_id=aid)
    dead = insert_song(tmp_app_root, name="dead", artist_id=aid, status=1)
    insert_learning(tmp_app_root, song_id=live)
    insert_learning(tmp_app_root, song_id=dead)

    rc, out, _err = call_script("learning.py", "stats", cwd=tmp_app_root)
    assert rc == 0
    payload = json.loads(out)
    assert payload["total"] == 1


# ---------------------------------------------------------------------------
# R2.4: no args / --help
# ---------------------------------------------------------------------------


def test_no_args_prints_help_and_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, err = call_script("learning.py", cwd=tmp_app_root)
    assert rc == 0
    combined = (out + err).lower()
    assert "usage" in combined or "learning.py" in combined


def test_help_flag_exits_zero(tmp_app_root, call_script) -> None:
    rc, out, _err = call_script("learning.py", "--help", cwd=tmp_app_root)
    assert rc == 0
    assert "usage" in out.lower()
