"""Bug 1 four-channel equivalence — property-based test.

For a randomly generated flat payload mixing ``resolved`` /
``auto_completable`` / ``ambiguous`` entries:

* **Property 1 (Expected Behavior):** ``import_plan.py`` produces the
  same plan whether the entries arrive via the legacy ``--input``
  (baseline), ``--input-jsonpath``, ``--input-jsonstr``, or
  ``--input-array`` channel. All four output files are byte-equal.
  Additionally, wrapping the same entries into the raw AMQ export shape
  (``{"songs": [...], "extra": ...}`` with AMQ field names
  ``songArtist`` / ``songName`` / ``animeEnglishName`` / ``vintage`` /
  ``audio``) and loading via ``--input-jsonpath`` (file) or
  ``--input-jsonstr`` (inline) produces the same plan as the flat
  baseline.
* **Property 2 (Preservation):** The legacy ``--input`` surface is
  byte-identical to itself across iterations — every new channel
  defers to that baseline.

Implements Task 5 from .kiro/specs/importer-and-graduate-fixes/tasks.md.
"""

from __future__ import annotations

import json
import random

from tests.integration.property._helpers import (
    BASE_SEED,
    ITERATIONS,
    random_name,
)

SEED = BASE_SEED + 206


def _seed_and_build_flat(
    app_root,
    rng: random.Random,
    iteration: int,
    insert_artist,
    insert_song,
    insert_show,
) -> list[dict]:
    """Seed the DB with a small base state and return a flat payload.

    Every name is suffixed with ``iteration`` so repeated calls against
    the same ``tmp_app_root`` never collide: the "existing" / "shared"
    artists created here do not clash with earlier iterations' rows.
    The resulting flat payload mixes all three classifier buckets:

    * a ``resolved`` entry (existing artist + existing song + show)
    * one or two ``auto_completable`` entries (new song under existing
      artist, and/or brand-new artist+song)
    * an ``ambiguous`` entry (artist name shared by two live artists)
    """
    suffix = f"{iteration}-{rng.randint(0, 10**9)}"

    existing_artist_name = f"Existing-{suffix}"
    known_song_name = f"Known Song {suffix}"
    known_show_name = f"Known Show {suffix}"
    known_vintage = f"Spring {2000 + iteration}"

    shared_name = f"Shared-{suffix}"

    existing_artist_id = insert_artist(app_root, name=existing_artist_name)
    insert_song(app_root, name=known_song_name, artist_id=existing_artist_id)
    insert_show(app_root, name=known_show_name, vintage=known_vintage)

    # Two artists with the same `name` force the ambiguous bucket.
    insert_artist(app_root, name=shared_name, name_context=f"ctx-a-{suffix}")
    insert_artist(app_root, name=shared_name, name_context=f"ctx-b-{suffix}")

    entries: list[dict] = [
        # resolved: existing artist + existing song + existing show
        {
            "artist_name": existing_artist_name,
            "song_name": known_song_name,
            "show_name": known_show_name,
            "vintage": known_vintage,
            "media_url": f"http://x/resolved-{suffix}",
        },
        # auto_completable: existing artist, new song, new show
        {
            "artist_name": existing_artist_name,
            "song_name": f"New Song {suffix}",
            "show_name": f"New Show {suffix}",
            "vintage": f"Fall {2000 + iteration}",
            "media_url": f"http://x/auto-existing-{suffix}",
        },
        # auto_completable: brand-new artist + brand-new song
        {
            "artist_name": f"Brand New {rng.choice([random_name(rng), suffix])}",
            "song_name": f"Brand New Song {suffix}",
            "show_name": f"Brand New Show {suffix}",
            "vintage": f"Winter {2000 + iteration}",
            "media_url": f"http://x/auto-new-{suffix}",
        },
        # ambiguous: two live artists share this name
        {
            "artist_name": shared_name,
            "song_name": f"Song By Shared {suffix}",
            "show_name": known_show_name,
            "vintage": known_vintage,
            "media_url": f"http://x/ambiguous-{suffix}",
        },
    ]
    rng.shuffle(entries)
    return entries


def _wrap_as_raw_amq(flat: list[dict]) -> dict:
    """Re-express a flat payload in the raw AMQ export shape.

    The importer's raw-AMQ preprocessor reads ``songArtist`` /
    ``songName`` / ``animeEnglishName`` / ``vintage`` / ``audio`` and
    ignores every other top-level sibling of ``songs``. Including an
    ``extra`` sibling exercises that drop-on-the-floor behavior.
    """
    return {
        "songs": [
            {
                "songArtist": e["artist_name"],
                "songName": e["song_name"],
                "animeEnglishName": e["show_name"],
                "vintage": e["vintage"],
                "audio": e["media_url"],
            }
            for e in flat
        ],
        "extra": "metadata",
    }


def test_all_input_channels_produce_byte_equal_plans(
    tmp_app_root,
    pinned_call,
    pinned_now,
    insert_artist,
    insert_song,
    insert_show,
) -> None:
    """Validates: Properties 1 and 2 from the file docstring."""
    rng = random.Random(SEED)

    for i in range(ITERATIONS):
        flat = _seed_and_build_flat(
            tmp_app_root,
            rng,
            iteration=i,
            insert_artist=insert_artist,
            insert_song=insert_song,
            insert_show=insert_show,
        )

        # Paths for the six plan outputs plus the two input files.
        flat_input = tmp_app_root / f"flat-{i}.json"
        flat_input.write_text(json.dumps(flat), encoding="utf-8")

        raw_amq = _wrap_as_raw_amq(flat)
        raw_amq_file = tmp_app_root / f"raw-amq-{i}.json"
        raw_amq_file.write_text(json.dumps(raw_amq), encoding="utf-8")

        flat_json_str = json.dumps(flat)
        raw_amq_json_str = json.dumps(raw_amq)

        plan_legacy = tmp_app_root / f"plan-legacy-{i}.json"
        plan_jsonpath_flat = tmp_app_root / f"plan-jsonpath-flat-{i}.json"
        plan_jsonstr_flat = tmp_app_root / f"plan-jsonstr-flat-{i}.json"
        plan_array_flat = tmp_app_root / f"plan-array-flat-{i}.json"
        plan_jsonpath_raw = tmp_app_root / f"plan-jsonpath-raw-{i}.json"
        plan_jsonstr_raw = tmp_app_root / f"plan-jsonstr-raw-{i}.json"

        # --- Flat payload through every accepted channel ---

        # 1. Legacy --input (baseline).
        rc, _out, err = pinned_call(
            "import_plan.py",
            "--input",
            str(flat_input),
            "--output",
            str(plan_legacy),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc == 0, err

        # 2. --input-jsonpath on the flat file.
        rc, _out, err = pinned_call(
            "import_plan.py",
            "--input-jsonpath",
            str(flat_input),
            "--output",
            str(plan_jsonpath_flat),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc == 0, err

        # 3. --input-jsonstr with the flat array inline.
        rc, _out, err = pinned_call(
            "import_plan.py",
            "--input-jsonstr",
            flat_json_str,
            "--output",
            str(plan_jsonstr_flat),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc == 0, err

        # 4. --input-array with the flat array inline.
        rc, _out, err = pinned_call(
            "import_plan.py",
            "--input-array",
            flat_json_str,
            "--output",
            str(plan_array_flat),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc == 0, err

        baseline_bytes = plan_legacy.read_bytes()
        assert plan_jsonpath_flat.read_bytes() == baseline_bytes, (
            f"iteration {i}: --input-jsonpath plan differs from legacy baseline"
        )
        assert plan_jsonstr_flat.read_bytes() == baseline_bytes, (
            f"iteration {i}: --input-jsonstr plan differs from legacy baseline"
        )
        assert plan_array_flat.read_bytes() == baseline_bytes, (
            f"iteration {i}: --input-array plan differs from legacy baseline"
        )

        # --- Raw AMQ payload through the two channels that accept it ---

        # 5. --input-jsonpath on the raw AMQ file.
        rc, _out, err = pinned_call(
            "import_plan.py",
            "--input-jsonpath",
            str(raw_amq_file),
            "--output",
            str(plan_jsonpath_raw),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc == 0, err

        # 6. --input-jsonstr with the raw AMQ object inline.
        rc, _out, err = pinned_call(
            "import_plan.py",
            "--input-jsonstr",
            raw_amq_json_str,
            "--output",
            str(plan_jsonstr_raw),
            cwd=tmp_app_root,
            now=pinned_now,
        )
        assert rc == 0, err

        assert plan_jsonpath_raw.read_bytes() == baseline_bytes, (
            f"iteration {i}: raw-AMQ via --input-jsonpath differs from legacy flat baseline"
        )
        assert plan_jsonstr_raw.read_bytes() == baseline_bytes, (
            f"iteration {i}: raw-AMQ via --input-jsonstr differs from legacy flat baseline"
        )
