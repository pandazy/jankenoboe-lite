"""Integration tests for ``learning.py leveldown`` (spec: learning-leveldown).

The ``leveldown`` op is the inverse of ``levelup`` — it drops one or more
learning records back to a strictly-lower stored level and resets the
review clock. See ``.kiro/specs/learning-leveldown/`` for the full spec.

These tests pin the CLI surface, envelope shape, transaction discipline,
and the four preflight rejections before the implementation lands.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from typing import Any

from scripts import _common


def _run(pinned_call, cwd, now, *args) -> tuple[int, Any, Any]:
    """Run ``learning.py`` with the clock pinned. Mirrors test_learning.py."""
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


def _db_bytes(app_root) -> bytes:
    return (app_root / "db" / "datasource.db").read_bytes()


# ---------------------------------------------------------------------------
# Task 1: contract-pinning RED tests
# ---------------------------------------------------------------------------


def test_empty_ids_yields_empty_updated_no_writes(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-1.3 / R-LD-1.5: empty --ids exits 0 with {"updated": []}; no DB writes."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=5)

    pre = _db_bytes(tmp_app_root)

    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        "",
        "--to-level",
        "0",
    )
    assert rc == 0, err
    assert out == {"updated": []}

    assert _db_bytes(tmp_app_root) == pre, "leveldown with empty --ids must not write"


def test_output_envelope_keys_in_fixed_order(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-3.2: per-entry keys come back in the pinned order."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=5,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "2",
    )
    assert rc == 0, err
    assert list(out.keys()) == ["updated"]
    assert len(out["updated"]) == 1
    entry = out["updated"][0]
    assert list(entry.keys()) == [
        "id",
        "level",
        "display_level",
        "graduated",
        "previous_level",
        "last_level_up_at",
        "updated_at",
    ]


def test_now_epoch_consistent_across_batch(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-3.3: every entry in the batch shares the same now_epoch."""
    aid = insert_artist(tmp_app_root, name="A")
    sid1 = insert_song(tmp_app_root, name="S1", artist_id=aid)
    sid2 = insert_song(tmp_app_root, name="S2", artist_id=aid)
    lid1 = insert_learning(
        tmp_app_root,
        song_id=sid1,
        level=5,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    lid2 = insert_learning(
        tmp_app_root,
        song_id=sid2,
        level=5,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        f"{lid1},{lid2}",
        "--to-level",
        "2",
    )
    assert rc == 0, err
    assert len(out["updated"]) == 2
    for entry in out["updated"]:
        assert entry["last_level_up_at"] == pinned_now
        assert entry["updated_at"] == pinned_now
    # Both share the same epoch (already implied above; pin it explicitly).
    assert out["updated"][0]["updated_at"] == out["updated"][1]["updated_at"]


def test_unknown_flag_argparse_error(tmp_app_root, pinned_call, pinned_now) -> None:
    """R-LD-1.4: unknown extra flag → argparse SystemExit(2)."""
    rc, out, err = pinned_call(
        "learning.py",
        "leveldown",
        "--ids",
        "L",
        "--to-level",
        "0",
        "--foo",
        "bar",
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 2
    assert out == ""
    assert "usage" in err.lower()


def test_missing_to_level_argparse_error(tmp_app_root, pinned_call, pinned_now) -> None:
    """R-LD-1.4: --to-level absent → argparse SystemExit(2)."""
    rc, out, err = pinned_call(
        "learning.py",
        "leveldown",
        "--ids",
        "L",
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 2
    assert out == ""
    assert "usage" in err.lower()


def test_missing_ids_argparse_error(tmp_app_root, pinned_call, pinned_now) -> None:
    """R-LD-1.4: --ids absent → argparse SystemExit(2)."""
    rc, out, err = pinned_call(
        "learning.py",
        "leveldown",
        "--to-level",
        "0",
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 2
    assert out == ""
    assert "usage" in err.lower()


def test_non_integer_to_level_argparse_error(tmp_app_root, pinned_call, pinned_now) -> None:
    """R-LD-1.4: non-integer --to-level → argparse SystemExit(2) (type=int)."""
    rc, out, err = pinned_call(
        "learning.py",
        "leveldown",
        "--ids",
        "L",
        "--to-level",
        "abc",
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 2
    assert out == ""
    assert "usage" in err.lower()


# ---------------------------------------------------------------------------
# Task 3: --to-level range check
# ---------------------------------------------------------------------------


def test_to_level_below_zero_invalid_input(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-2.1 step 1.ii / R-LD-2.5: --to-level -1 → INVALID_INPUT."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=5)
    pre = _db_bytes(tmp_app_root)

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        "L",
        "--to-level",
        "-1",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"
    assert err["error"]["details"]["min"] == 0
    assert err["error"]["details"]["max"] == _common.MAX_LEVEL
    assert err["error"]["details"]["to_level"] == -1
    assert _db_bytes(tmp_app_root) == pre


def test_to_level_above_max_invalid_input(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-2.1 step 1.ii / R-LD-2.5: --to-level > MAX_LEVEL → INVALID_INPUT."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=5)
    pre = _db_bytes(tmp_app_root)

    bad = _common.MAX_LEVEL + 1
    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        "L",
        "--to-level",
        str(bad),
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"
    assert err["error"]["details"]["to_level"] == bad
    assert _db_bytes(tmp_app_root) == pre


def test_range_check_runs_before_empty_ids_short_circuit(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-1.3 caveat: out-of-range --to-level still errors even with empty --ids."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    insert_learning(tmp_app_root, song_id=sid, level=5)
    pre = _db_bytes(tmp_app_root)

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        "",
        "--to-level",
        "-1",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"
    assert _db_bytes(tmp_app_root) == pre


# ---------------------------------------------------------------------------
# Task 4: preflight SELECT + three rejections (NOT_FOUND, ALREADY_GRADUATED,
# Strictly_Below_Rule), in the order pinned by R-LD-2.1.
# ---------------------------------------------------------------------------


def test_missing_id_returns_not_found(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-2.1 step 1.iv / R-LD-2.2: any missing id → NOT_FOUND, no writes."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=5,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    pre = _db_bytes(tmp_app_root)

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        f"{lid},bogus-1,bogus-2",
        "--to-level",
        "2",
    )
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"
    assert set(err["error"]["details"]["ids"]) == {"bogus-1", "bogus-2"}
    assert _db_bytes(tmp_app_root) == pre


def test_graduated_id_returns_already_graduated(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-2.1 step 1.v / R-LD-2.3: any graduated id → ALREADY_GRADUATED, no writes."""
    aid = insert_artist(tmp_app_root, name="A")
    sid1 = insert_song(tmp_app_root, name="S1", artist_id=aid)
    sid2 = insert_song(tmp_app_root, name="S2", artist_id=aid)
    live = insert_learning(
        tmp_app_root,
        song_id=sid1,
        level=5,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    grad = insert_learning(
        tmp_app_root,
        song_id=sid2,
        level=10,
        graduated=1,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    pre = _db_bytes(tmp_app_root)

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        f"{live},{grad}",
        "--to-level",
        "2",
    )
    assert rc == 1
    assert err["error"]["code"] == "ALREADY_GRADUATED"
    assert err["error"]["details"]["ids"] == [grad]
    assert _db_bytes(tmp_app_root) == pre


def test_target_equal_to_current_invalid_input(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-2.1 step 1.vi / R-LD-2.4: target == current → INVALID_INPUT."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=5,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    pre = _db_bytes(tmp_app_root)

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "5",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"
    assert err["error"]["details"]["to_level"] == 5
    offenders = err["error"]["details"]["offenders"]
    assert len(offenders) == 1
    assert offenders[0] == {"id": lid, "level": 5, "display_level": 6}
    assert _db_bytes(tmp_app_root) == pre


def test_target_above_current_invalid_input(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-2.1 step 1.vi: target > current → INVALID_INPUT."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=5,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    pre = _db_bytes(tmp_app_root)

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "7",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"
    assert err["error"]["details"]["offenders"][0]["id"] == lid
    assert _db_bytes(tmp_app_root) == pre


def test_offenders_envelope_includes_level_and_display_level(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-2.4: offenders array carries stored level and display_level per row."""
    aid = insert_artist(tmp_app_root, name="A")
    sid1 = insert_song(tmp_app_root, name="S1", artist_id=aid)
    sid2 = insert_song(tmp_app_root, name="S2", artist_id=aid)
    sid3 = insert_song(tmp_app_root, name="S3", artist_id=aid)
    ok = insert_learning(
        tmp_app_root,
        song_id=sid1,
        level=10,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    bad1 = insert_learning(
        tmp_app_root,
        song_id=sid2,
        level=3,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    bad2 = insert_learning(
        tmp_app_root,
        song_id=sid3,
        level=5,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        f"{ok},{bad1},{bad2}",
        "--to-level",
        "5",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"
    by_id = {o["id"]: o for o in err["error"]["details"]["offenders"]}
    assert set(by_id) == {bad1, bad2}
    assert by_id[bad1] == {"id": bad1, "level": 3, "display_level": 4}
    assert by_id[bad2] == {"id": bad2, "level": 5, "display_level": 6}


def test_first_failing_preflight_step_wins_not_found_over_other(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-2.1 ordering: NOT_FOUND beats ALREADY_GRADUATED beats below-rule."""
    aid = insert_artist(tmp_app_root, name="A")
    sid1 = insert_song(tmp_app_root, name="S1", artist_id=aid)
    sid2 = insert_song(tmp_app_root, name="S2", artist_id=aid)
    grad = insert_learning(
        tmp_app_root,
        song_id=sid1,
        level=10,
        graduated=1,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    below = insert_learning(
        tmp_app_root,
        song_id=sid2,
        level=2,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        f"{grad},{below},bogus",
        "--to-level",
        "5",
    )
    assert rc == 1
    assert err["error"]["code"] == "NOT_FOUND"


def test_first_failing_preflight_step_wins_already_graduated_over_below(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-2.1 ordering: with no missing, ALREADY_GRADUATED beats below-rule."""
    aid = insert_artist(tmp_app_root, name="A")
    sid1 = insert_song(tmp_app_root, name="S1", artist_id=aid)
    sid2 = insert_song(tmp_app_root, name="S2", artist_id=aid)
    grad = insert_learning(
        tmp_app_root,
        song_id=sid1,
        level=10,
        graduated=1,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    below = insert_learning(
        tmp_app_root,
        song_id=sid2,
        level=2,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        f"{grad},{below}",
        "--to-level",
        "5",
    )
    assert rc == 1
    assert err["error"]["code"] == "ALREADY_GRADUATED"


def test_partial_failure_rolls_back_no_partial_writes(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-1.5 / R-LD-2.6 / R-LD-2.7: any preflight fail → no row touched."""
    aid = insert_artist(tmp_app_root, name="A")
    sid1 = insert_song(tmp_app_root, name="S1", artist_id=aid)
    sid2 = insert_song(tmp_app_root, name="S2", artist_id=aid)
    sid3 = insert_song(tmp_app_root, name="S3", artist_id=aid)
    pass1 = insert_learning(
        tmp_app_root,
        song_id=sid1,
        level=10,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    pass2 = insert_learning(
        tmp_app_root,
        song_id=sid2,
        level=10,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    bad = insert_learning(
        tmp_app_root,
        song_id=sid3,
        level=2,  # below target → triggers rule
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    pre = _db_bytes(tmp_app_root)

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        f"{pass1},{pass2},{bad}",
        "--to-level",
        "5",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"

    # No row touched: every learning row's level / updated_at unchanged.
    for lid in (pass1, pass2, bad):
        row = _select_learning(tmp_app_root, lid)
        assert row["updated_at"] == 1_690_000_000
        assert row["last_level_up_at"] == 1_690_000_000
    assert _select_learning(tmp_app_root, pass1)["level"] == 10
    assert _select_learning(tmp_app_root, pass2)["level"] == 10
    assert _select_learning(tmp_app_root, bad)["level"] == 2

    assert _db_bytes(tmp_app_root) == pre


# ---------------------------------------------------------------------------
# Task 5: per-id UPDATE loop and Leveldown_Update_Entry construction
# ---------------------------------------------------------------------------


def test_leveldown_drops_level_and_resets_clock(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-3.1: Forget_Reset writes (level, last_level_up_at, updated_at)."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=17,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "10",
    )
    assert rc == 0, err

    row = _select_learning(tmp_app_root, lid)
    assert row["level"] == 10
    assert row["last_level_up_at"] == pinned_now
    assert row["updated_at"] == pinned_now
    assert row["graduated"] == 0


def test_previous_level_is_pre_call_value(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-3.2 / R-LD-3.4: previous_level reflects the pre-call source level."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=17,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "10",
    )
    assert rc == 0, err
    entry = out["updated"][0]
    assert entry["previous_level"] == 17
    assert entry["level"] == 10
    assert entry["display_level"] == 11
    assert entry["graduated"] == 0


def test_level_up_path_unchanged_on_success(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-3.1 / R-LD-3.6: level_up_path JSON is byte-identical after the call."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    custom = json.dumps(
        [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71]
    )
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=10,
        level_up_path=custom,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "5",
    )
    assert rc == 0, err

    row = _select_learning(tmp_app_root, lid)
    assert row["level_up_path"] == custom


def test_other_learning_rows_unchanged_on_success(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-3.6: rows not in --ids are byte-identical after a successful call."""
    aid = insert_artist(tmp_app_root, name="A")
    sid1 = insert_song(tmp_app_root, name="S1", artist_id=aid)
    sid2 = insert_song(tmp_app_root, name="S2", artist_id=aid)
    target = insert_learning(
        tmp_app_root,
        song_id=sid1,
        level=10,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    bystander = insert_learning(
        tmp_app_root,
        song_id=sid2,
        level=8,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    pre_bystander = _select_learning(tmp_app_root, bystander)

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        target,
        "--to-level",
        "3",
    )
    assert rc == 0, err

    assert _select_learning(tmp_app_root, bystander) == pre_bystander


def test_other_tables_unchanged_on_success(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_learning,
    insert_play_history,
) -> None:
    """R-LD-3.6: only `learning` is touched; other tables byte-identical."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    shid = insert_show(tmp_app_root, name="Show")
    insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="https://example/u")
    insert_play_history(tmp_app_root, show_id=shid, song_id=sid, media_url="https://example/u")
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=10,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    def snapshot(table: str) -> list[tuple]:
        conn = sqlite3.connect(str(tmp_app_root / "db" / "datasource.db"))
        try:
            return list(conn.execute(f"SELECT * FROM {table} ORDER BY 1"))
        finally:
            conn.close()

    pre = {t: snapshot(t) for t in ("song", "artist", "show", "rel_show_song", "play_history")}

    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "3",
    )
    assert rc == 0, err

    post = {t: snapshot(t) for t in pre}
    assert post == pre


def test_repeat_ids_in_csv_is_benign(
    tmp_app_root, pinned_call, pinned_now, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-3.5: --ids L,L,L is benign — N entries in output, row at target."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=10,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    rc, out, err = _run(
        pinned_call,
        tmp_app_root,
        pinned_now,
        "leveldown",
        "--ids",
        f"{lid},{lid},{lid}",
        "--to-level",
        "3",
    )
    assert rc == 0, err
    assert len(out["updated"]) == 3
    # Every entry hits the same row at the same target level.
    for entry in out["updated"]:
        assert entry["id"] == lid
        assert entry["level"] == 3
        assert entry["last_level_up_at"] == pinned_now
    # The first entry's previous_level is the seeded level. The second and
    # third entries also see the seeded level because the preflight SELECT
    # is taken once and `rows[lid]["level"]` is not re-read after the
    # interleaved UPDATEs (R-LD-3.4).
    assert all(e["previous_level"] == 10 for e in out["updated"])

    row = _select_learning(tmp_app_root, lid)
    assert row["level"] == 3
    assert row["last_level_up_at"] == pinned_now


# ---------------------------------------------------------------------------
# Task 6: round-trip with levelup, and due-after-leveldown timing.
#
# `due` reads SQLite's ``strftime('%s','now')``, which sits outside the
# JANKENOBOE_TEST_NOW seam. Tests that touch `due` therefore use
# ``call_script`` (real wall clock) rather than ``pinned_call``, and seed
# ``leveldown`` against the same wall clock so ``last_level_up_at`` and
# SQLite's "now" line up at run time. See test_due.py for the same trick.
# ---------------------------------------------------------------------------


def _sqlite_now(db_file) -> int:
    conn = sqlite3.connect(str(db_file))
    try:
        return int(conn.execute("SELECT CAST(strftime('%s','now') AS INTEGER)").fetchone()[0])
    finally:
        conn.close()


def _due_ids(call_script, cwd, offset: int = 0) -> set[str]:
    rc, out, err = call_script("learning.py", "due", "--offset", str(offset), cwd=cwd)
    assert rc == 0, err
    payload = json.loads(out)
    return {r["id"] for r in payload["results"]}


def test_levelup_after_leveldown_increments_from_target(
    tmp_app_root, pinned_call, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-3.1 / parent R6.5: levelup after leveldown advances from target."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=17,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )

    e1 = 1_700_000_000
    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        e1,
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "10",
    )
    assert rc == 0, err

    e2 = 1_700_001_000
    rc, _out, err = _run(
        pinned_call,
        tmp_app_root,
        e2,
        "levelup",
        "--ids",
        lid,
    )
    assert rc == 0, err

    row = _select_learning(tmp_app_root, lid)
    assert row["level"] == 11
    assert row["last_level_up_at"] == e2  # second call's epoch wins
    assert row["updated_at"] == e2
    assert row["graduated"] == 0


def test_due_after_leveldown_at_offset_zero_excludes_row(
    tmp_app_root, call_script, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-4.1 / R-LD-4.2: at offset 0, the row is not yet due (wait > 0)."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=17,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    rc, _out, err = call_script(
        "learning.py",
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "10",
        cwd=tmp_app_root,
    )
    assert rc == 0, err

    # level_up_path[10] == 7 days; offset 0 is far below the threshold.
    assert lid not in _due_ids(call_script, tmp_app_root, offset=0)


def test_due_after_leveldown_at_wait_offset_includes_row(
    tmp_app_root, call_script, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-4.1 / R-LD-4.2: at offset == wait_seconds, the row is due (boundary =)."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=17,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    rc, _out, err = call_script(
        "learning.py",
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "10",
        cwd=tmp_app_root,
    )
    assert rc == 0, err

    wait_days = _common.DEFAULT_LEVEL_UP_PATH[10]
    # +5 to absorb the fraction of a second that elapses between the
    # leveldown's now_epoch and the due op's strftime read; equality is
    # due, so any small forward bump still includes the row.
    assert lid in _due_ids(call_script, tmp_app_root, offset=wait_days * 86400 + 5)


def test_due_after_leveldown_to_zero_at_300s_includes_row(
    tmp_app_root, call_script, insert_artist, insert_song, insert_learning
) -> None:
    """R-LD-4.2: --to-level 0 — the level-0 5-minute clause kicks in at offset 300."""
    aid = insert_artist(tmp_app_root, name="A")
    sid = insert_song(tmp_app_root, name="S", artist_id=aid)
    lid = insert_learning(
        tmp_app_root,
        song_id=sid,
        level=5,
        updated_at=1_690_000_000,
        last_level_up_at=1_690_000_000,
    )
    rc, _out, err = call_script(
        "learning.py",
        "leveldown",
        "--ids",
        lid,
        "--to-level",
        "0",
        cwd=tmp_app_root,
    )
    assert rc == 0, err

    # 300s is the level-0 boundary; +5 absorbs sub-second clock drift.
    assert lid in _due_ids(call_script, tmp_app_root, offset=305)
    # And at offset 0, the row is not yet due.
    assert lid not in _due_ids(call_script, tmp_app_root, offset=0)


# ---------------------------------------------------------------------------
# Task 10: skill doc content assertion (R-LD-5)
# ---------------------------------------------------------------------------


def test_skill_md_lists_leveldown() -> None:
    """R-LD-5.1 / R-LD-5.2 / R-LD-5.3: skill doc names leveldown and the
    ALREADY_GRADUATED note, and keeps the existing per-outcome bullets."""
    skill_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "skills"
        / "reviewing-songs"
        / "SKILL.md"
    )
    text = skill_path.read_text(encoding="utf-8")

    # New op surface.
    assert "leveldown" in text
    assert "--to-level" in text
    assert "--ids" in text
    assert "ALREADY_GRADUATED" in text  # note for both levelup and leveldown

    # Existing bullets / notes still present.
    assert "levelup" in text
    assert "graduate" in text
    assert "due" in text
    assert "batch" in text
    assert "learning-detail" in text
