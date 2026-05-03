"""Integration tests for ``scripts/import_plan.py``.

Covers R12.1-R12.9. ``import_plan.py`` is read-only; the tests also
check that the DB file is byte-identical before and after every run.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import urllib.parse
from typing import Any


def _db_hash(app_root) -> str:
    h = hashlib.sha256()
    h.update((app_root / "db" / "datasource.db").read_bytes())
    return h.hexdigest()


def _run_plan(
    pinned_call,
    cwd,
    now,
    input_path,
    output_path: str | None = None,
    positional: bool = False,
) -> tuple[int, Any, Any]:
    args: list[str] = []
    if positional:
        args.append(str(input_path))
    else:
        args += ["--input", str(input_path)]
    if output_path is not None:
        args += ["--output", str(output_path)]
    rc, out, err = pinned_call("import_plan.py", *args, cwd=cwd, now=now)
    out_parsed: Any = None
    err_parsed: Any = None
    if out.strip():
        try:
            out_parsed = json.loads(out)
        except json.JSONDecodeError:
            out_parsed = None
    if err.strip():
        try:
            err_parsed = json.loads(err)
        except json.JSONDecodeError:
            err_parsed = None
    return rc, out_parsed, err_parsed


def _write_amq(app_root, entries: list[dict]) -> str:
    p = app_root / "amq.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# R12.4 — exact-match resolved
# ---------------------------------------------------------------------------


def test_resolved_exact_match_with_existing_show(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="Artist A")
    song_id = insert_song(tmp_app_root, name="Song A", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Show A", vintage="Fall 2024")

    entries = [
        {
            "artist_name": "Artist A",
            "song_name": "Song A",
            "show_name": "Show A",
            "vintage": "Fall 2024",
            "media_url": "http://x/a",
        }
    ]
    amq = _write_amq(tmp_app_root, entries)

    before = _db_hash(tmp_app_root)
    rc, out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, amq)
    assert rc == 0, err
    assert _db_hash(tmp_app_root) == before

    assert len(out["resolved"]) == 1
    assert len(out["auto_completable"]) == 0
    assert len(out["ambiguous"]) == 0
    item = out["resolved"][0]
    assert item["song_id"] == song_id
    assert item["show_id"] == show_id
    assert item["media_url"] == "http://x/a"


# ---------------------------------------------------------------------------
# R12.4 — auto_completable when artist exists but song is missing
# ---------------------------------------------------------------------------


def test_auto_completable_artist_exists_song_missing(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="Artist B")
    insert_show(tmp_app_root, name="Show B", vintage="")

    entries = [
        {
            "artist_name": "Artist B",
            "song_name": "Fresh Song",
            "show_name": "Show B",
            "vintage": "",
            "media_url": "",
        }
    ]
    amq = _write_amq(tmp_app_root, entries)

    rc, out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, amq)
    assert rc == 0, err
    assert len(out["auto_completable"]) == 1
    item = out["auto_completable"][0]
    assert item["artist_id"] == artist_id
    assert "artist_to_create" not in item
    assert item["song_name"] == "Fresh Song"
    assert "show_id" in item


# ---------------------------------------------------------------------------
# R12.4 — auto_completable when the artist is also missing
# ---------------------------------------------------------------------------


def test_auto_completable_artist_missing_gets_artist_to_create(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    entries = [
        {
            "artist_name": "Never Heard Of",
            "song_name": "Never Heard Song",
            "show_name": "Never Heard Show",
            "vintage": "Summer 2099",
            "media_url": "http://x/new",
        }
    ]
    amq = _write_amq(tmp_app_root, entries)

    rc, out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, amq)
    assert rc == 0, err
    assert len(out["auto_completable"]) == 1
    item = out["auto_completable"][0]
    assert item["artist_to_create"] == {"name": "Never Heard Of"}
    assert item["song_name"] == "Never Heard Song"
    assert item["show_to_create"]["name"] == "Never Heard Show"
    assert item["show_to_create"]["vintage"] == "Summer 2099"
    assert item["show_to_create"]["s_type"] is None
    assert item["show_to_create"]["name_romaji"] is None


# ---------------------------------------------------------------------------
# R12.4 — ambiguous when two live artists share the name
# ---------------------------------------------------------------------------


def test_ambiguous_when_two_artists_share_name(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_show,
) -> None:
    a1 = insert_artist(tmp_app_root, name="Twin", name_context="solo")
    a2 = insert_artist(tmp_app_root, name="Twin", name_context="band")
    insert_show(tmp_app_root, name="Show", vintage="")

    entries = [
        {
            "artist_name": "Twin",
            "song_name": "Ambiguous Song",
            "show_name": "Show",
            "vintage": "",
            "media_url": "",
        }
    ]
    amq = _write_amq(tmp_app_root, entries)

    rc, out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, amq)
    assert rc == 0, err
    assert len(out["ambiguous"]) == 1
    item = out["ambiguous"][0]
    assert item["artist_name"] == "Twin"
    assert item["song_name"] == "Ambiguous Song"
    assert item["show_name"] == "Show"
    # Both candidates present regardless of order.
    cand_ids = sorted(c["id"] for c in item["candidates"])
    assert cand_ids == sorted([a1, a2])


# ---------------------------------------------------------------------------
# R12.4 — SONG_INVARIANT_VIOLATION when one artist owns two same-name songs
# ---------------------------------------------------------------------------


def test_song_invariant_violation_aborts(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="Artist")
    s1 = insert_song(tmp_app_root, name="Dup Song", artist_id=artist_id)
    s2 = insert_song(tmp_app_root, name="Dup Song", artist_id=artist_id)

    entries = [
        {
            "artist_name": "Artist",
            "song_name": "Dup Song",
            "show_name": "",
            "vintage": "",
            "media_url": "",
        }
    ]
    amq = _write_amq(tmp_app_root, entries)

    rc, _out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, amq)
    assert rc == 1
    assert err["error"]["code"] == "SONG_INVARIANT_VIOLATION"
    details = err["error"]["details"]
    assert details["artist_id"] == artist_id
    assert details["song_name"] == "Dup Song"
    assert sorted(details["song_ids"]) == sorted([s1, s2])


# ---------------------------------------------------------------------------
# R12.5 — missing show alone stays in the entry's bucket; does not cause ambiguous
# ---------------------------------------------------------------------------


def test_missing_show_does_not_make_ambiguous(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="Artist X")
    insert_song(tmp_app_root, name="Song X", artist_id=artist_id)

    entries = [
        {
            "artist_name": "Artist X",
            "song_name": "Song X",
            "show_name": "No Such Show",
            "vintage": "Fall 9999",
            "media_url": "",
        }
    ]
    amq = _write_amq(tmp_app_root, entries)

    rc, out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, amq)
    assert rc == 0, err
    assert len(out["resolved"]) == 1
    item = out["resolved"][0]
    assert "show_id" not in item
    assert item["show_to_create"]["name"] == "No Such Show"
    assert item["show_to_create"]["vintage"] == "Fall 9999"


# ---------------------------------------------------------------------------
# R12.3 — URL-decoded fields
# ---------------------------------------------------------------------------


def test_url_decoded_fields_are_matched_after_decoding(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    # Artist name contains an ASCII char that gets percent-encoded.
    artist_id = insert_artist(tmp_app_root, name="A & B")
    insert_song(tmp_app_root, name="Song & Friends", artist_id=artist_id)
    insert_show(tmp_app_root, name="Show %s", vintage="")

    entries = [
        {
            "artist_name": urllib.parse.quote("A & B"),
            "song_name": urllib.parse.quote("Song & Friends"),
            "show_name": urllib.parse.quote("Show %s"),
            "vintage": "",
            "media_url": urllib.parse.quote("http://x/y?z=1&w=2"),
        }
    ]
    amq = _write_amq(tmp_app_root, entries)

    rc, out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, amq)
    assert rc == 0, err
    assert len(out["resolved"]) == 1
    item = out["resolved"][0]
    assert item["media_url"] == "http://x/y?z=1&w=2"


# ---------------------------------------------------------------------------
# R12.9 — --output writes file + prints summary
# ---------------------------------------------------------------------------


def test_output_writes_plan_file_and_prints_summary(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
) -> None:
    insert_artist(tmp_app_root, name="Named")
    entries = [
        {
            "artist_name": "Named",
            "song_name": "Some Song",
            "show_name": "Some Show",
            "vintage": "",
            "media_url": "",
        },
        {
            "artist_name": "Brand New",
            "song_name": "Brand Song",
            "show_name": "Brand Show",
            "vintage": "",
            "media_url": "",
        },
    ]
    amq = _write_amq(tmp_app_root, entries)
    out_path = tmp_app_root / "output" / "plan.json"

    rc, summary, err = _run_plan(
        pinned_call,
        tmp_app_root,
        pinned_now,
        amq,
        output_path=str(out_path),
    )
    assert rc == 0, err
    # Summary, not full plan.
    assert set(summary.keys()) == {
        "resolved_count",
        "auto_completable_count",
        "ambiguous_count",
        "path",
    }
    assert summary["resolved_count"] == 0
    assert summary["auto_completable_count"] == 2
    assert summary["ambiguous_count"] == 0
    # Path is absolute.
    assert summary["path"].endswith("plan.json")

    # The file exists, is valid JSON, and matches the summary counts.
    assert out_path.exists()
    plan = json.loads(out_path.read_text())
    assert len(plan["resolved"]) == 0
    assert len(plan["auto_completable"]) == 2
    assert len(plan["ambiguous"]) == 0


def test_positional_input_path_is_accepted(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    entries: list[dict] = []
    amq = _write_amq(tmp_app_root, entries)

    rc, out, err = _run_plan(
        pinned_call,
        tmp_app_root,
        pinned_now,
        amq,
        positional=True,
    )
    assert rc == 0, err
    assert out == {"resolved": [], "auto_completable": [], "ambiguous": []}


# ---------------------------------------------------------------------------
# R12.7 — DB is byte-identical before and after (read-only)
# ---------------------------------------------------------------------------


def test_plan_does_not_modify_db(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    artist_id = insert_artist(tmp_app_root, name="Stable")
    insert_song(tmp_app_root, name="Stable Song", artist_id=artist_id)
    insert_show(tmp_app_root, name="Stable Show", vintage="")

    entries = [
        {
            "artist_name": "Stable",
            "song_name": "Stable Song",
            "show_name": "Stable Show",
            "vintage": "",
            "media_url": "",
        },
        {
            "artist_name": "Unknown",
            "song_name": "Unknown Song",
            "show_name": "Unknown Show",
            "vintage": "Spring 1999",
            "media_url": "",
        },
    ]
    amq = _write_amq(tmp_app_root, entries)

    before = _db_hash(tmp_app_root)
    rc, _out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, amq)
    assert rc == 0, err
    assert _db_hash(tmp_app_root) == before


# ---------------------------------------------------------------------------
# R12 — mixed buckets in a single run
# ---------------------------------------------------------------------------


def test_mixed_buckets_sum_equals_entry_count(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    existing_artist = insert_artist(tmp_app_root, name="Existing")
    insert_song(tmp_app_root, name="Existing Song", artist_id=existing_artist)
    insert_artist(tmp_app_root, name="Twin", name_context="a")
    insert_artist(tmp_app_root, name="Twin", name_context="b")
    insert_show(tmp_app_root, name="Show", vintage="")

    entries = [
        # resolved
        {
            "artist_name": "Existing",
            "song_name": "Existing Song",
            "show_name": "Show",
            "vintage": "",
            "media_url": "",
        },
        # auto_completable (artist exists, song doesn't)
        {
            "artist_name": "Existing",
            "song_name": "New Song",
            "show_name": "Show",
            "vintage": "",
            "media_url": "",
        },
        # auto_completable (artist missing)
        {
            "artist_name": "Brand New",
            "song_name": "Whatever",
            "show_name": "Show",
            "vintage": "",
            "media_url": "",
        },
        # ambiguous
        {
            "artist_name": "Twin",
            "song_name": "Conflict",
            "show_name": "Show",
            "vintage": "",
            "media_url": "",
        },
    ]
    amq = _write_amq(tmp_app_root, entries)

    rc, out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, amq)
    assert rc == 0, err
    total = len(out["resolved"]) + len(out["auto_completable"]) + len(out["ambiguous"])
    assert total == len(entries)
    assert len(out["resolved"]) == 1
    assert len(out["auto_completable"]) == 2
    assert len(out["ambiguous"]) == 1


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_no_args_prints_help_exits_zero(
    tmp_app_root,
    call_script,
) -> None:
    """R2.4: scripts called with no arguments print usage and exit 0."""
    rc, out, _err = call_script("import_plan.py", cwd=tmp_app_root)
    assert rc == 0
    assert "import_plan.py" in out or "--input" in out


def test_missing_file_emits_invalid_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    rc, _out, err = _run_plan(
        pinned_call,
        tmp_app_root,
        pinned_now,
        tmp_app_root / "no-such-file.json",
    )
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_non_json_input_emits_invalid_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    bad = tmp_app_root / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")

    rc, _out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, str(bad))
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


def test_non_array_top_level_emits_invalid_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    bad = tmp_app_root / "bad.json"
    bad.write_text(json.dumps({"not": "an array"}), encoding="utf-8")

    rc, _out, err = _run_plan(pinned_call, tmp_app_root, pinned_now, str(bad))
    assert rc == 1
    assert err["error"]["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Bug 1 — raw AMQ export shape via --input-jsonpath must match flat via --input
#
# This is the Task 1.1 bug-condition exploration test. On unfixed code the
# --input-jsonpath flag does not exist, so argparse exits 2 and the `rc == 0`
# assertion below fails — that failure is the evidence that the bug exists.
#
# On the fixed CLI, --input-jsonpath accepts either payload shape (raw AMQ
# object with a top-level `songs` array, or the legacy flat array) and
# produces the same plan the legacy --input surface produces on the
# equivalent flat payload. The raw AMQ payload below carries an extra
# top-level `quizSettings` sibling on purpose: it proves that top-level
# game-metadata siblings of `songs` are silently ignored.
# ---------------------------------------------------------------------------


def test_raw_amq_via_input_jsonpath_matches_flat_via_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    # Seed state: one live artist, one live song under that artist, one live
    # show. The AMQ payload (raw and flat) below maps to exactly this song,
    # so both invocations should land the single entry in the `resolved`
    # bucket with the same song_id / show_id.
    artist_id = insert_artist(tmp_app_root, name="Artist A")
    song_id = insert_song(tmp_app_root, name="Song A", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Show A", vintage="Fall 2024")

    # Raw AMQ export shape: a JSON object with a top-level `songs` array of
    # AMQ song objects, plus an extra top-level sibling (`quizSettings`) to
    # prove that the preprocessing stage drops it. The per-song keys use
    # AMQ's native real-export nesting: every required field lives under
    # `songInfo`, show names nest a further level under `songInfo.animeNames`,
    # and the media URL is the top-level `videoUrl` on the song.
    amq_raw_payload = {
        "songs": [
            {
                "songInfo": {
                    "artist": "Artist A",
                    "songName": "Song A",
                    "animeNames": {"english": "Show A", "romaji": "Shou A"},
                    "vintage": "Fall 2024",
                },
                "videoUrl": "http://x/a",
            }
        ],
        "quizSettings": {"gameMode": "Solo", "songCount": 1},
    }
    amq_raw_path = tmp_app_root / "amq_raw.json"
    amq_raw_path.write_text(json.dumps(amq_raw_payload), encoding="utf-8")

    # Flat five-field array: the already-flattened equivalent of the single
    # AMQ song above. Must use the exact classifier-consumed keys.
    amq_flat_payload = [
        {
            "artist_name": "Artist A",
            "song_name": "Song A",
            "show_name": "Show A",
            "vintage": "Fall 2024",
            "media_url": "http://x/a",
        }
    ]
    amq_flat_path = tmp_app_root / "amq_flat.json"
    amq_flat_path.write_text(json.dumps(amq_flat_payload), encoding="utf-8")

    plan_raw_path = tmp_app_root / "plan_raw.json"
    plan_flat_path = tmp_app_root / "plan_flat.json"

    # Raw AMQ through the new --input-jsonpath flag.
    rc_raw, _out_raw, err_raw = pinned_call(
        "import_plan.py",
        "--input-jsonpath",
        str(amq_raw_path),
        "--output",
        str(plan_raw_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    # On unfixed code this is the assertion that fires: argparse rejects
    # --input-jsonpath with exit 2, so rc_raw == 2 and err_raw is argparse's
    # usage message, not a JSON error envelope.
    assert rc_raw == 0, err_raw

    # Flat array through the legacy --input surface.
    rc_flat, _out_flat, err_flat = pinned_call(
        "import_plan.py",
        "--input",
        str(amq_flat_path),
        "--output",
        str(plan_flat_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc_flat == 0, err_flat

    # Byte-for-byte equality of the two plan files proves the raw AMQ payload
    # is flattened to exactly the same intermediate representation the legacy
    # surface consumes, and every downstream classification / bucketing /
    # carry-through step is untouched by the new input channel.
    raw_bytes = plan_raw_path.read_bytes()
    flat_bytes = plan_flat_path.read_bytes()
    assert raw_bytes == flat_bytes

    # Sanity: the shared plan lands the single entry in `resolved` with the
    # seeded song_id and show_id. Parsing either file is fine since they are
    # byte-equal by the assertion above.
    plan = json.loads(raw_bytes)
    assert len(plan["resolved"]) == 1
    assert len(plan["auto_completable"]) == 0
    assert len(plan["ambiguous"]) == 0
    item = plan["resolved"][0]
    assert item["song_id"] == song_id
    assert item["show_id"] == show_id
    assert item["media_url"] == "http://x/a"


# ---------------------------------------------------------------------------
# Bug 1 — new CLI channel coverage
#
# Tasks 4.1 / 4.2 / 4.3 extend the Task 1.1 exploration test to cover the
# remaining new input channels and payload shapes added by Bug 1's fix:
#
#   * 4.1 — `--input-jsonstr` carrying a raw AMQ JSON object matches legacy
#           `--input` on the equivalent flat array file.
#   * 4.2 — `--input-array` carrying a flat JSON array matches legacy
#           `--input` on the same flat array written to a file.
#   * 4.3 — `--input-array` rejects a raw AMQ object with INVALID_INPUT.
#
# The first two tests seed one live artist, one live song, and one live
# show so the single entry lands in the `resolved` bucket, keeping the
# plan comparison compact. The third test needs no seed because the
# flat-only channel check fires before the classifier runs.
# ---------------------------------------------------------------------------


def test_input_jsonstr_raw_amq_matches_flat_via_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    # Same seed shape as Task 1.1: a single AMQ song that resolves cleanly.
    artist_id = insert_artist(tmp_app_root, name="Artist A")
    song_id = insert_song(tmp_app_root, name="Song A", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Show A", vintage="Fall 2024")

    # Raw AMQ payload as a Python string — passed literally as an argv
    # value to `--input-jsonstr`. Includes a top-level `quizSettings`
    # sibling to prove the preprocessing stage drops game metadata.
    # Uses the real AMQ nested shape (songInfo / animeNames / videoUrl).
    amq_raw_jsonstr = json.dumps(
        {
            "songs": [
                {
                    "songInfo": {
                        "artist": "Artist A",
                        "songName": "Song A",
                        "animeNames": {"english": "Show A", "romaji": "Shou A"},
                        "vintage": "Fall 2024",
                    },
                    "videoUrl": "http://x/a",
                }
            ],
            "quizSettings": {"gameMode": "Solo", "songCount": 1},
        }
    )

    # Equivalent flat array, written to a file for the legacy `--input`.
    amq_flat_payload = [
        {
            "artist_name": "Artist A",
            "song_name": "Song A",
            "show_name": "Show A",
            "vintage": "Fall 2024",
            "media_url": "http://x/a",
        }
    ]
    amq_flat_path = tmp_app_root / "amq_flat.json"
    amq_flat_path.write_text(json.dumps(amq_flat_payload), encoding="utf-8")

    plan_str_path = tmp_app_root / "plan_str.json"
    plan_flat_path = tmp_app_root / "plan_flat.json"

    rc_str, _out_str, err_str = pinned_call(
        "import_plan.py",
        "--input-jsonstr",
        amq_raw_jsonstr,
        "--output",
        str(plan_str_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc_str == 0, err_str

    rc_flat, _out_flat, err_flat = pinned_call(
        "import_plan.py",
        "--input",
        str(amq_flat_path),
        "--output",
        str(plan_flat_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc_flat == 0, err_flat

    # Byte-for-byte equality proves the inline raw AMQ payload flattens
    # to the same intermediate representation the legacy surface consumes.
    assert plan_str_path.read_bytes() == plan_flat_path.read_bytes()

    # Sanity: single entry landed in `resolved` with the seeded ids.
    plan = json.loads(plan_str_path.read_bytes())
    assert len(plan["resolved"]) == 1
    assert len(plan["auto_completable"]) == 0
    assert len(plan["ambiguous"]) == 0
    item = plan["resolved"][0]
    assert item["song_id"] == song_id
    assert item["show_id"] == show_id
    assert item["media_url"] == "http://x/a"


def test_input_array_flat_matches_flat_via_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    # Same seed shape as Task 1.1: a single song that resolves cleanly.
    artist_id = insert_artist(tmp_app_root, name="Artist A")
    song_id = insert_song(tmp_app_root, name="Song A", artist_id=artist_id)
    show_id = insert_show(tmp_app_root, name="Show A", vintage="Fall 2024")

    # Flat five-field payload — same array goes through both channels.
    amq_flat_payload = [
        {
            "artist_name": "Artist A",
            "song_name": "Song A",
            "show_name": "Show A",
            "vintage": "Fall 2024",
            "media_url": "http://x/a",
        }
    ]
    amq_flat_jsonstr = json.dumps(amq_flat_payload)

    amq_flat_path = tmp_app_root / "amq_flat.json"
    amq_flat_path.write_text(amq_flat_jsonstr, encoding="utf-8")

    plan_arr_path = tmp_app_root / "plan_arr.json"
    plan_flat_path = tmp_app_root / "plan_flat.json"

    rc_arr, _out_arr, err_arr = pinned_call(
        "import_plan.py",
        "--input-array",
        amq_flat_jsonstr,
        "--output",
        str(plan_arr_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc_arr == 0, err_arr

    rc_flat, _out_flat, err_flat = pinned_call(
        "import_plan.py",
        "--input",
        str(amq_flat_path),
        "--output",
        str(plan_flat_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc_flat == 0, err_flat

    # Byte-for-byte equality proves the inline flat array goes through
    # the same URL-decode-and-normalise loop as the legacy file channel.
    assert plan_arr_path.read_bytes() == plan_flat_path.read_bytes()

    # Sanity: single entry landed in `resolved` with the seeded ids.
    plan = json.loads(plan_arr_path.read_bytes())
    assert len(plan["resolved"]) == 1
    assert len(plan["auto_completable"]) == 0
    assert len(plan["ambiguous"]) == 0
    item = plan["resolved"][0]
    assert item["song_id"] == song_id
    assert item["show_id"] == show_id
    assert item["media_url"] == "http://x/a"


def test_input_array_rejects_raw_amq_with_invalid_input(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    # Raw AMQ payload as a string — the flat-only channel check should
    # fire before the classifier runs, so no DB seed is needed. Uses
    # the real AMQ nested shape (songInfo / animeNames / videoUrl) to
    # prove `--input-array` rejects any nested AMQ object, not just the
    # v0.1.1 guessed shape.
    amq_raw_jsonstr = json.dumps(
        {
            "songs": [
                {
                    "songInfo": {
                        "artist": "Artist A",
                        "songName": "Song A",
                        "animeNames": {"english": "Show A"},
                        "vintage": "Fall 2024",
                    },
                    "videoUrl": "http://x/a",
                }
            ],
            "quizSettings": {"gameMode": "Solo"},
        }
    )

    rc, _out, err = pinned_call(
        "import_plan.py",
        "--input-array",
        amq_raw_jsonstr,
        cwd=tmp_app_root,
        now=pinned_now,
    )
    assert rc == 1
    # stderr is a JSON error envelope per `{"error": {"code", "message", "details"}}`.
    envelope = json.loads(err)
    assert envelope["error"]["code"] == "INVALID_INPUT"
    assert "flat-only" in envelope["error"]["message"]


# ---------------------------------------------------------------------------
# amq-real-export-shape-fix Task 1 — bug-condition exploration test
#
# MUST FAIL on unfixed v0.1.1 code (the failure is the evidence the bug
# exists): the current `_AMQ_FIELD_MAP` does a 1-level `entry[key]` lookup
# at the top of each song object, but the real AMQ export nests every
# required field under `songInfo` (and show names a further level under
# `songInfo.animeNames`). The artist lookup aborts on song 0 with exit 1
# and
#   {"error": {"code": "INVALID_INPUT",
#              "details": {"missing_field": "artist_name", "index": 0, ...}}}
# so the `rc == 0` assertion below is what fails on unfixed code.
#
# After Task 2 rewrites `_AMQ_FIELD_MAP` to path tuples and adds
# `_get_nested`, this same test passes end-to-end (three buckets sum to
# 9 and the Tia/Chotto Dekakete Kimasu/Wooser pinned song lands in the
# plan). Do not modify `scripts/import_plan.py` from this task — the
# fix lands in Task 2.
#
# Fixture is read-only per R3.11: `shutil.copyfile` (not move, not edit)
# into `tmp_app_root` so `--input-jsonpath` can read it via a stable
# relative path inside the temp App_Root.
# ---------------------------------------------------------------------------


def test_real_amq_export_file_ingests_end_to_end(
    tmp_app_root,
    pinned_call,
    pinned_now,
) -> None:
    # Zero rows seeded — every AMQ song in the fixture lands in
    # `auto_completable` against an empty DB after the fix.
    fixture_path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "amq_song_export-small.json"
    )
    copied = tmp_app_root / "amq_real.json"
    shutil.copyfile(fixture_path, copied)

    plan_path = tmp_app_root / "plan.json"

    rc, _out, err = pinned_call(
        "import_plan.py",
        "--input-jsonpath",
        "amq_real.json",
        "--output",
        str(plan_path),
        cwd=tmp_app_root,
        now=pinned_now,
    )

    # Bug-condition exploration assertion: on unfixed code this fires
    # because the preprocessor rejects the real nested shape with
    # INVALID_INPUT missing_field=artist_name details.index=0.
    assert rc == 0, err
    assert err == "", err

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    total = len(plan["resolved"]) + len(plan["auto_completable"]) + len(plan["ambiguous"])
    assert total == 9

    # Pinned-song assertion per design Decision 4. DB is empty so the
    # entry lands in `auto_completable` with `artist_to_create` and
    # `show_to_create` populated from the real nested paths:
    #   songInfo.artist         -> "Tia"
    #   songInfo.songName       -> "Chotto Dekakete Kimasu"
    #   songInfo.animeNames.english -> "Wooser's Hand-to-Mouth Life: Awakening Arc"
    pinned = [
        item
        for item in plan["auto_completable"]
        if item.get("artist_to_create", {}).get("name") == "Tia"
        and item.get("song_name") == "Chotto Dekakete Kimasu"
        and item.get("show_to_create", {}).get("name")
        == "Wooser's Hand-to-Mouth Life: Awakening Arc"
    ]
    assert len(pinned) >= 1, plan
