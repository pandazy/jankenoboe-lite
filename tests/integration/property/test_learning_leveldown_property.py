"""Property tests for ``learning.py leveldown`` (spec: learning-leveldown).

Six properties, P-LD-1..P-LD-6:

  * P-LD-1 — Forget_Reset Touches Exactly The Three Columns
  * P-LD-2 — Strictly_Below_Rule Rejects Equal Or Greater
  * P-LD-3 — Graduated Rows Are Rejected, Untouched
  * P-LD-4 — Batch All-Or-Nothing
  * P-LD-5 — Leveldown Then Levelup Round-Trip
  * P-LD-6 — Due-After-Leveldown Tracks The Lower Wait

Determinism rules (parent R18):
  * Each test seeds ``random.Random(SEED)`` with a fixed integer.
  * Every subprocess call goes through ``pinned_call`` so
    ``JANKENOBOE_TEST_NOW`` is set per iteration. Exception: P-LD-6
    crosses ``leveldown`` (uses ``now_epoch`` from env) and ``due``
    (reads SQLite's ``strftime('%s','now')``, which sits outside our
    seam). The two clocks are reconciled at run time inside the test.
"""

from __future__ import annotations

import json
import random
import sqlite3
from typing import Any

from scripts import _common
from tests.integration.property._helpers import BASE_SEED, ITERATIONS

MAX_LEVEL = _common.MAX_LEVEL


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _run(pinned_call, cwd, now, *args) -> tuple[int, Any, Any]:
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
# P-LD-1: Forget_Reset Touches Exactly The Three Columns
# ---------------------------------------------------------------------------

SEED_P1 = BASE_SEED + 300


def test_forget_reset_touches_only_three_columns(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """For any active row R and any T < R.level, only level, last_level_up_at,
    updated_at change. Every other column on R, every other learning row, and
    every row in song / artist / show / play_history / rel_show_song are
    byte-identical pre/post.
    """
    rng = random.Random(SEED_P1)
    artist = insert_artist(tmp_app_root, name="Prop-LD1")
    for i in range(ITERATIONS):
        song = insert_song(tmp_app_root, name=f"S{i}", artist_id=artist)
        l0 = rng.randint(1, MAX_LEVEL)
        target = rng.randint(0, l0 - 1)
        lid = insert_learning(
            tmp_app_root,
            song_id=song,
            level=l0,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
            last_level_up_at=1_699_000_000,
        )
        # Bystander row that must not change.
        bystander_song = insert_song(tmp_app_root, name=f"B{i}", artist_id=artist)
        bystander = insert_learning(
            tmp_app_root,
            song_id=bystander_song,
            level=rng.randint(0, MAX_LEVEL),
            graduated=rng.choice([0, 1]),
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
            last_level_up_at=1_699_000_000,
        )
        before = _select_learning(tmp_app_root, lid)
        before_bystander = _select_learning(tmp_app_root, bystander)

        rc, _out, err = _run(
            pinned_call,
            tmp_app_root,
            pinned_now,
            "leveldown",
            "--ids",
            lid,
            "--to-level",
            str(target),
        )
        assert rc == 0, err

        after = _select_learning(tmp_app_root, lid)
        assert after["level"] == target
        assert after["last_level_up_at"] == pinned_now
        assert after["updated_at"] == pinned_now
        # Every other column on R unchanged.
        for col in ("id", "song_id", "graduated", "created_at", "level_up_path"):
            assert after[col] == before[col], f"{col} changed unexpectedly"

        # Bystander row byte-identical.
        assert _select_learning(tmp_app_root, bystander) == before_bystander


# ---------------------------------------------------------------------------
# P-LD-2: Strictly_Below_Rule Rejects Equal Or Greater
# ---------------------------------------------------------------------------

SEED_P2 = BASE_SEED + 301


def test_strictly_below_rule_rejects_equal_or_greater(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Any T >= R.level → INVALID_INPUT, DB byte-identical, offenders carries
    the row's level / display_level."""
    rng = random.Random(SEED_P2)
    artist = insert_artist(tmp_app_root, name="Prop-LD2")
    for i in range(ITERATIONS):
        song = insert_song(tmp_app_root, name=f"S{i}", artist_id=artist)
        l0 = rng.randint(0, MAX_LEVEL)
        target = rng.randint(l0, MAX_LEVEL)  # equal or greater
        lid = insert_learning(
            tmp_app_root,
            song_id=song,
            level=l0,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
            last_level_up_at=1_699_000_000,
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
            str(target),
        )
        assert rc == 1
        assert err["error"]["code"] == "INVALID_INPUT"
        assert err["error"]["details"]["to_level"] == target
        offenders = err["error"]["details"]["offenders"]
        assert any(
            o["id"] == lid and o["level"] == l0 and o["display_level"] == l0 + 1 for o in offenders
        )
        assert _db_bytes(tmp_app_root) == pre


# ---------------------------------------------------------------------------
# P-LD-3: Graduated Rows Are Rejected, Untouched
# ---------------------------------------------------------------------------

SEED_P3 = BASE_SEED + 302


def test_graduated_rows_rejected_untouched(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Any T in [0, MAX_LEVEL] on a graduated row → ALREADY_GRADUATED,
    DB byte-identical."""
    rng = random.Random(SEED_P3)
    artist = insert_artist(tmp_app_root, name="Prop-LD3")
    for i in range(ITERATIONS):
        song = insert_song(tmp_app_root, name=f"S{i}", artist_id=artist)
        l0 = rng.randint(0, MAX_LEVEL)
        target = rng.randint(0, MAX_LEVEL)
        lid = insert_learning(
            tmp_app_root,
            song_id=song,
            level=l0,
            graduated=1,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
            last_level_up_at=1_699_000_000,
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
            str(target),
        )
        assert rc == 1
        assert err["error"]["code"] == "ALREADY_GRADUATED"
        assert lid in err["error"]["details"]["ids"]
        assert _db_bytes(tmp_app_root) == pre


# ---------------------------------------------------------------------------
# P-LD-4: Batch All-Or-Nothing (preflight ordering, no partial writes)
# ---------------------------------------------------------------------------

SEED_P4 = BASE_SEED + 303


def test_batch_all_or_nothing(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """Mixed batch with one passing id + one failing id (mode rotates across
    iterations: missing / graduated / below-rule). DB is byte-identical
    pre/post; envelope code matches the ordering pinned by R-LD-2.1."""
    rng = random.Random(SEED_P4)
    artist = insert_artist(tmp_app_root, name="Prop-LD4")
    modes = ["missing", "graduated", "below"]
    expected_codes = {
        "missing": "NOT_FOUND",
        "graduated": "ALREADY_GRADUATED",
        "below": "INVALID_INPUT",
    }
    for i in range(ITERATIONS * 2):  # cover each mode at least twice
        mode = modes[i % len(modes)]
        target = rng.randint(2, MAX_LEVEL - 1)

        # Always seed at least one id that would pass on its own.
        passing_song = insert_song(tmp_app_root, name=f"P{i}", artist_id=artist)
        passing = insert_learning(
            tmp_app_root,
            song_id=passing_song,
            level=target + 1,  # strictly above target → would pass
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
            last_level_up_at=1_699_000_000,
        )

        ids = [passing]
        if mode == "missing":
            ids.append("bogus-" + str(i))
        elif mode == "graduated":
            grad_song = insert_song(tmp_app_root, name=f"G{i}", artist_id=artist)
            grad = insert_learning(
                tmp_app_root,
                song_id=grad_song,
                level=target + 1,
                graduated=1,
                created_at=1_699_000_000,
                updated_at=1_699_000_000,
                last_level_up_at=1_699_000_000,
            )
            ids.append(grad)
        else:  # below
            below_song = insert_song(tmp_app_root, name=f"B{i}", artist_id=artist)
            below = insert_learning(
                tmp_app_root,
                song_id=below_song,
                level=target,  # equal → triggers below-rule
                created_at=1_699_000_000,
                updated_at=1_699_000_000,
                last_level_up_at=1_699_000_000,
            )
            ids.append(below)

        pre = _db_bytes(tmp_app_root)

        rc, _out, err = _run(
            pinned_call,
            tmp_app_root,
            pinned_now,
            "leveldown",
            "--ids",
            ",".join(ids),
            "--to-level",
            str(target),
        )
        assert rc == 1
        assert err["error"]["code"] == expected_codes[mode]
        # DB byte-identical: the passing row never got written.
        assert _db_bytes(tmp_app_root) == pre


# ---------------------------------------------------------------------------
# P-LD-5: Leveldown Then Levelup Round-Trip
# ---------------------------------------------------------------------------

SEED_P5 = BASE_SEED + 304


def test_leveldown_then_levelup_round_trip(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """For R with R.level >= 2, leveldown to T = R.level - 2, then levelup
    leaves R at T + 1, last_level_up_at = E2 (not E1), graduated = 0."""
    rng = random.Random(SEED_P5)
    artist = insert_artist(tmp_app_root, name="Prop-LD5")
    for i in range(ITERATIONS):
        song = insert_song(tmp_app_root, name=f"S{i}", artist_id=artist)
        l0 = rng.randint(2, MAX_LEVEL)
        target = l0 - 2
        lid = insert_learning(
            tmp_app_root,
            song_id=song,
            level=l0,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
            last_level_up_at=1_699_000_000,
        )
        e1 = 1_700_000_000 + i
        e2 = e1 + 1_000

        rc, _out, err = _run(
            pinned_call,
            tmp_app_root,
            e1,
            "leveldown",
            "--ids",
            lid,
            "--to-level",
            str(target),
        )
        assert rc == 0, err

        rc, _out, err = _run(pinned_call, tmp_app_root, e2, "levelup", "--ids", lid)
        assert rc == 0, err

        row = _select_learning(tmp_app_root, lid)
        assert row["level"] == target + 1
        assert row["last_level_up_at"] == e2
        assert row["updated_at"] == e2
        assert row["graduated"] == 0


# ---------------------------------------------------------------------------
# P-LD-6: Due-After-Leveldown Tracks The Lower Wait
#
# `due` reads SQLite's ``strftime('%s','now')``, outside the JANKENOBOE_TEST
# _NOW seam. We therefore call leveldown without pinning (real wall clock),
# then call due against the same wall clock. The +5s buffer absorbs the
# sub-second gap between the two subprocesses' clock reads.
# ---------------------------------------------------------------------------

SEED_P6 = BASE_SEED + 305


def _due_ids(call_script, cwd, offset: int = 0) -> set[str]:
    rc, out, err = call_script("learning.py", "due", "--offset", str(offset), cwd=cwd)
    assert rc == 0, err
    return {r["id"] for r in json.loads(out)["results"]}


def test_due_after_leveldown_tracks_lower_wait(
    tmp_app_root,
    call_script,
    insert_artist,
    insert_song,
    insert_learning,
) -> None:
    """After leveldown to T: at offset 0 row is not due; at the lower wait's
    boundary (level_up_path[T] * 86400 for T >= 1, 300 for T == 0) row IS due;
    level_up_path JSON unchanged across the call."""
    rng = random.Random(SEED_P6)
    artist = insert_artist(tmp_app_root, name="Prop-LD6")
    for i in range(ITERATIONS):
        song = insert_song(tmp_app_root, name=f"S{i}", artist_id=artist)
        l0 = rng.randint(1, MAX_LEVEL)
        target = rng.randint(0, l0 - 1)
        path_before = json.dumps(_common.DEFAULT_LEVEL_UP_PATH)
        lid = insert_learning(
            tmp_app_root,
            song_id=song,
            level=l0,
            level_up_path=path_before,
            created_at=1_699_000_000,
            updated_at=1_699_000_000,
            last_level_up_at=1_699_000_000,
        )

        rc, _out, err = call_script(
            "learning.py",
            "leveldown",
            "--ids",
            lid,
            "--to-level",
            str(target),
            cwd=tmp_app_root,
        )
        assert rc == 0, err

        # level_up_path JSON byte-identical.
        row = _select_learning(tmp_app_root, lid)
        assert row["level_up_path"] == path_before

        # At offset 0 the row is not yet due.
        assert lid not in _due_ids(call_script, tmp_app_root, offset=0)

        # At the lower wait's boundary the row IS due. 300s for level 0,
        # level_up_path[T] days for T >= 1. +5s absorbs sub-second drift
        # between the leveldown's now_epoch and the due op's strftime.
        wait_offset = 300 + 5 if target == 0 else _common.DEFAULT_LEVEL_UP_PATH[target] * 86400 + 5
        assert lid in _due_ids(call_script, tmp_app_root, offset=wait_offset)
