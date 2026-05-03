"""AMQ import — step 1 (plan).

Read an AMQ JSON file and bucket every entry into one of three arrays:
``resolved`` (artist + song already exist), ``auto_completable`` (artist
is clear but the song doesn't exist yet, or both are new), or
``ambiguous`` (two or more live artists share the entry's artist name).

See requirements.md R12 and design.md "Import Plan Classification".

This script is read-only. It never opens a transaction and never writes
to the DB. The only side effect is printing JSON to stdout and, with
``--output``, writing the plan JSON to disk.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from typing import Any

# See design.md "Importing the shared module". absolute() (not resolve())
# keeps symlinked scripts/ dirs intact so the test harness works.
_REPO_ROOT = str(pathlib.Path(__file__).absolute().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts import _common  # noqa: E402

# ---------------------------------------------------------------------------
# argparse setup
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="import_plan.py",
        description="Classify AMQ entries into resolved / auto_completable / ambiguous buckets.",
    )
    # Legacy surface — flat-only, kept exactly as it was before Bug 1's fix.
    # Listed first to match historical docs.
    p.add_argument(
        "--input",
        dest="input_path",
        help="Path to the AMQ JSON file (a flat array of entries). Legacy, flat-only.",
    )
    p.add_argument(
        "positional_input",
        nargs="?",
        help="Same as --input, accepted positionally. Legacy, flat-only.",
    )

    # Input — three new mutually-exclusive flags. argparse handles the
    # two-of-three rejection among them; the "mix with legacy" and
    # "none supplied" cases are validated manually in `_run` so they
    # produce proper INVALID_INPUT envelopes instead of argparse's exit-2
    # usage text.
    input_group = p.add_mutually_exclusive_group(required=False)
    input_group.add_argument(
        "--input-jsonpath",
        dest="input_jsonpath",
        metavar="PATH",
        help="Path to a JSON file holding either the raw AMQ export shape "
        "(a JSON object with a `songs` array) or the legacy flat array shape.",
    )
    input_group.add_argument(
        "--input-jsonstr",
        dest="input_jsonstr",
        metavar="JSON",
        help="Inline JSON string holding either the raw AMQ export shape or "
        "the legacy flat array shape.",
    )
    input_group.add_argument(
        "--input-array",
        dest="input_array",
        metavar="JSON",
        help="Inline JSON string holding the flat array shape only. "
        "Rejects the raw AMQ object shape with INVALID_INPUT.",
    )

    p.add_argument(
        "--output",
        dest="output_path",
        help="Where to write the plan JSON. Without this, the full plan is printed to stdout.",
    )
    return p


# ---------------------------------------------------------------------------
# Input loading and normalisation
# ---------------------------------------------------------------------------


def _load_entries(path: str) -> list[dict[str, Any]]:
    """Read and URL-decode every string field of every AMQ entry.

    Per R12.2 extra fields are ignored; we also tolerate missing
    optional fields (``media_url`` defaults to an empty string).
    """
    try:
        raw = pathlib.Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise _common.KnownError(
            "INVALID_INPUT",
            f"Input file not found: {path}",
            {"path": path},
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _common.KnownError(
            "INVALID_INPUT",
            f"Input JSON is not parseable: {exc}",
            {"path": path},
        ) from exc
    if not isinstance(data, list):
        raise _common.KnownError(
            "INVALID_INPUT",
            "AMQ input must be a JSON array of entries.",
            {"path": path},
        )

    out: list[dict[str, Any]] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise _common.KnownError(
                "INVALID_INPUT",
                f"Entry at index {i} is not a JSON object.",
                {"index": i},
            )
        # R12.3 — URL-decode every string field before any DB lookup.
        decoded = _common.decode_data(entry)
        normalised = {
            "artist_name": str(decoded.get("artist_name", "")),
            "song_name": str(decoded.get("song_name", "")),
            "show_name": str(decoded.get("show_name", "")),
            "vintage": str(decoded.get("vintage", "")),
            "media_url": str(decoded.get("media_url", "")),
        }
        out.append(normalised)
    return out


# ---------------------------------------------------------------------------
# Raw-AMQ preprocessing helpers
#
# These are pure functions. The classifier consumes the flat five-field
# shape (`artist_name`, `song_name`, `show_name`, `vintage`, `media_url`);
# raw AMQ exports use different key names and carry extra game-metadata
# noise. `_discriminate` picks the shape, `_amq_entry_to_flat` converts
# one AMQ song object, and `_flatten_amq` walks the `songs` array.
# See design.md "Bug 1 — AMQ importer input shape".
# ---------------------------------------------------------------------------


def _get_nested(obj: object, path: tuple[str, ...]) -> object:
    """Walk ``obj`` along ``path`` one key at a time. Return ``None``
    on any missing container or non-dict container mid-walk. Returns
    the final value regardless of type — caller decides what counts
    as "present".
    """
    cur: object = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


# Field mapping table for `_amq_entry_to_flat`. Each candidate is a
# **path tuple** walked one step at a time by `_get_nested`. Real
# AMQ nested paths come first so they win on real AMQ payloads; the
# flat aliases are retained as single-key paths so already-flat
# callers (e.g. tests that pass flat entries through the AMQ channel)
# keep working. Design.md Decision 1 pins this mapping.
_AMQ_FIELD_MAP: tuple[tuple[str, tuple[tuple[str, ...], ...], bool], ...] = (
    ("artist_name", (("songInfo", "artist"), ("artist_name",)), True),
    ("song_name", (("songInfo", "songName"), ("song_name",)), True),
    (
        "show_name",
        (
            ("songInfo", "animeNames", "english"),
            ("songInfo", "animeNames", "romaji"),
            ("show_name",),
        ),
        True,
    ),
    ("vintage", (("songInfo", "vintage"), ("animeVintage",), ("vintage",)), True),
    (
        "media_url",
        (("videoUrl",), ("audio",), ("media_url",), ("MP3",), ("mp3",)),
        False,
    ),
)


def _discriminate(parsed: object) -> str:
    """Return the payload-shape tag for a parsed JSON value.

    * ``"flat"``    — parsed is a JSON array (flat five-field shape).
    * ``"raw_amq"`` — parsed is a JSON object whose ``songs`` key holds
      an array (raw AMQ export shape).

    Anything else raises ``KnownError(INVALID_INPUT)`` with
    ``details["got_type"]`` naming the actual Python type.
    """
    if isinstance(parsed, list):
        return "flat"
    if isinstance(parsed, dict) and isinstance(parsed.get("songs"), list):
        return "raw_amq"
    raise _common.KnownError(
        "INVALID_INPUT",
        "Input must be a JSON array (flat shape) or a JSON object with "
        "a `songs` array (raw AMQ shape).",
        {"got_type": type(parsed).__name__},
    )


def _amq_entry_to_flat(entry: dict, i: int) -> dict:
    """Convert one raw AMQ song object to the flat five-field shape.

    For each required key, iterate the candidate raw **paths** in
    order and pick the first whose value (after walking the path via
    ``_get_nested``) is a non-empty string. If no candidate matches,
    raise ``KnownError(INVALID_INPUT)`` citing the index and the
    missing flat key.

    ``media_url`` is optional: if no candidate matches, it defaults to
    the empty string (same default as the legacy flat loader).

    Every other key on ``entry`` is silently dropped. The returned dict
    always has exactly the five flat keys in the declared order.
    """
    flat: dict[str, str] = {}
    for flat_key, candidate_paths, required in _AMQ_FIELD_MAP:
        picked: str | None = None
        for path in candidate_paths:
            val = _get_nested(entry, path)
            if isinstance(val, str) and val != "":
                picked = val
                break
        if picked is None:
            if required:
                raise _common.KnownError(
                    "INVALID_INPUT",
                    f"AMQ song at index {i} is missing required field {flat_key}.",
                    {
                        "index": i,
                        "missing_field": flat_key,
                        "available_keys": sorted(entry.keys()),
                    },
                )
            picked = ""
        flat[flat_key] = picked
    return flat


def _flatten_amq(payload: dict) -> list[dict]:
    """Convert a raw AMQ export object to the flat five-field list.

    The caller must have already discriminated the shape; this function
    assumes ``isinstance(payload["songs"], list)``. Top-level siblings
    of ``songs`` (game metadata, quiz settings, export timestamps, etc.)
    are silently dropped — this function only reads ``payload["songs"]``.
    """
    flat: list[dict] = []
    for i, entry in enumerate(payload["songs"]):
        if not isinstance(entry, dict):
            raise _common.KnownError(
                "INVALID_INPUT",
                f"AMQ song at index {i} is not a JSON object.",
                {"index": i},
            )
        flat.append(_amq_entry_to_flat(entry, i))
    return flat


def _entries_from_parsed(parsed: object, *, channel: str) -> list[dict[str, Any]]:
    """Convert a parsed JSON payload to the flat five-field entry list
    the classifier consumes. Dispatches by shape via ``_discriminate()``.

    ``channel`` is one of ``"jsonpath"``, ``"jsonstr"``, ``"flat-only"``.
    The ``"flat-only"`` channel (i.e. ``--input-array``) rejects raw AMQ
    payloads with ``INVALID_INPUT`` up front, even though the
    discriminator would otherwise accept them.

    Runs the same URL-decode-and-normalise loop as ``_load_entries`` so
    every channel produces the same five-field shape — ``_flatten_amq``
    already returns dicts in that shape, but their string values can
    still be URL-encoded, so they go through the same decode step the
    legacy path uses.
    """
    tag = _discriminate(parsed)
    if channel == "flat-only" and tag == "raw_amq":
        raise _common.KnownError(
            "INVALID_INPUT",
            "--input-array is flat-only; nested AMQ objects are not accepted on this channel.",
            None,
        )

    if tag == "raw_amq":
        # Preprocessing stage: convert to the flat five-field shape.
        entries_raw: list = _flatten_amq(parsed)  # type: ignore[arg-type]
    else:
        # tag == "flat"; `parsed` is a list per `_discriminate`.
        entries_raw = parsed  # type: ignore[assignment]

    out: list[dict[str, Any]] = []
    for i, entry in enumerate(entries_raw):
        if not isinstance(entry, dict):
            raise _common.KnownError(
                "INVALID_INPUT",
                f"Entry at index {i} is not a JSON object.",
                {"index": i},
            )
        decoded = _common.decode_data(entry)
        normalised = {
            "artist_name": str(decoded.get("artist_name", "")),
            "song_name": str(decoded.get("song_name", "")),
            "show_name": str(decoded.get("show_name", "")),
            "vintage": str(decoded.get("vintage", "")),
            "media_url": str(decoded.get("media_url", "")),
        }
        out.append(normalised)
    return out


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _resolve_show(conn: sqlite3.Connection, entry: dict[str, Any]) -> dict[str, Any]:
    """Return the ``show_info`` block (``show_id`` or ``show_to_create``).

    R12.5 — a missing show alone never changes the entry's bucket.
    """
    row = conn.execute(
        "SELECT id FROM show WHERE name = ? AND vintage = ? AND status = 0",
        (entry["show_name"], entry["vintage"]),
    ).fetchone()
    if row is not None:
        return {"show_id": row["id"], "media_url": entry["media_url"]}
    return {
        "show_to_create": {
            "name": entry["show_name"],
            "vintage": entry["vintage"],
            "s_type": None,
            "name_romaji": None,
        },
        "media_url": entry["media_url"],
    }


def _classify(conn: sqlite3.Connection, entry: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return ``(bucket, item)`` for one AMQ entry.

    ``bucket`` is ``"resolved"``, ``"auto_completable"``, or
    ``"ambiguous"``. ``item`` is the JSON-serialisable plan entry for
    that bucket. Raises ``KnownError(SONG_INVARIANT_VIOLATION)`` when
    one artist owns two live songs with the same name (R12.4).
    """
    show_info = _resolve_show(conn, entry)

    # Live artists sharing the entry's artist_name.
    artists = conn.execute(
        "SELECT id, name, name_context FROM artist WHERE name = ? AND status = 0 ORDER BY id",
        (entry["artist_name"],),
    ).fetchall()

    if len(artists) == 0:
        item: dict[str, Any] = {
            "artist_to_create": {"name": entry["artist_name"]},
            "song_name": entry["song_name"],
            **show_info,
        }
        return "auto_completable", item

    if len(artists) >= 2:
        item = {
            "artist_name": entry["artist_name"],
            "song_name": entry["song_name"],
            "show_name": entry["show_name"],
            "vintage": entry["vintage"],
            "candidates": [
                {"id": a["id"], "name": a["name"], "name_context": a["name_context"]}
                for a in artists
            ],
            # Also carry the resolved show info so step 2 doesn't need to
            # re-query the show table.
            **show_info,
        }
        return "ambiguous", item

    # Exactly one live artist matches; now look for the song.
    artist = artists[0]
    songs = conn.execute(
        "SELECT id FROM song WHERE name = ? AND artist_id = ? AND status = 0 ORDER BY id",
        (entry["song_name"], artist["id"]),
    ).fetchall()

    if len(songs) == 1:
        item = {"song_id": songs[0]["id"], **show_info}
        return "resolved", item

    if len(songs) == 0:
        item = {
            "artist_id": artist["id"],
            "song_name": entry["song_name"],
            **show_info,
        }
        return "auto_completable", item

    # len(songs) >= 2 — one artist owns two live songs with the same
    # name. That breaks the per-artist unique-name invariant; abort.
    raise _common.KnownError(
        "SONG_INVARIANT_VIOLATION",
        f"Artist {artist['id']!r} owns {len(songs)} live songs named "
        f"{entry['song_name']!r}. Soft-delete the extras and retry.",
        {
            "artist_id": artist["id"],
            "song_name": entry["song_name"],
            "song_ids": [s["id"] for s in songs],
        },
    )


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def _run(args: argparse.Namespace) -> None:
    # Classify which input channel(s) fired. argparse's mutually-exclusive
    # group has already rejected two-of-three among the new flags with its
    # own usage-text / exit-2 behavior; we only need to validate the
    # "legacy + new" and "nothing supplied" cases here, so they surface
    # as proper INVALID_INPUT envelopes.
    legacy_set = bool(args.input_path or args.positional_input)
    new_set = bool(args.input_jsonpath or args.input_jsonstr or args.input_array)

    if legacy_set and new_set:
        raise _common.KnownError(
            "INVALID_INPUT",
            "Mix of legacy --input and new input flags is not supported.",
            None,
        )
    if not legacy_set and not new_set:
        raise _common.KnownError(
            "INVALID_INPUT",
            "No input: pass --input-jsonpath, --input-jsonstr, "
            "--input-array, --input, or a positional path.",
            None,
        )

    if legacy_set:
        # Legacy channel is unchanged — still flat-only, still parses the
        # file via `_load_entries`.
        path = args.input_path or args.positional_input
        entries = _load_entries(path)
    elif args.input_jsonpath:
        path = args.input_jsonpath
        try:
            raw = pathlib.Path(path).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise _common.KnownError(
                "INVALID_INPUT",
                f"Input file not found: {path}",
                {"path": path},
            ) from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _common.KnownError(
                "INVALID_INPUT",
                f"Input JSON is not parseable: {exc}",
                {"path": path},
            ) from exc
        entries = _entries_from_parsed(parsed, channel="jsonpath")
    elif args.input_jsonstr:
        try:
            parsed = json.loads(args.input_jsonstr)
        except json.JSONDecodeError as exc:
            raise _common.KnownError(
                "INVALID_INPUT",
                f"--input-jsonstr is not valid JSON: {exc}",
                None,
            ) from exc
        entries = _entries_from_parsed(parsed, channel="jsonstr")
    else:
        # args.input_array is set.
        try:
            parsed = json.loads(args.input_array)
        except json.JSONDecodeError as exc:
            raise _common.KnownError(
                "INVALID_INPUT",
                f"--input-array is not valid JSON: {exc}",
                None,
            ) from exc
        entries = _entries_from_parsed(parsed, channel="flat-only")

    conn = _common.open_db(__file__)
    try:
        plan: dict[str, list[dict[str, Any]]] = {
            "resolved": [],
            "auto_completable": [],
            "ambiguous": [],
        }
        for entry in entries:
            bucket, item = _classify(conn, entry)
            plan[bucket].append(item)
    finally:
        conn.close()

    if args.output_path:
        out_path = pathlib.Path(args.output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Stable serialisation: no trailing whitespace, sort_keys=False
        # (we already build the arrays in a deterministic order).
        out_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _common.success(
            {
                "resolved_count": len(plan["resolved"]),
                "auto_completable_count": len(plan["auto_completable"]),
                "ambiguous_count": len(plan["ambiguous"]),
                "path": str(out_path.absolute()),
            }
        )
    else:
        _common.success(plan)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _run(args)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _build_parser().print_help()
        sys.exit(0)
    _common.run(main)
