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
    p.add_argument(
        "--input",
        dest="input_path",
        help="Path to the AMQ JSON file (a flat array of entries).",
    )
    p.add_argument(
        "positional_input",
        nargs="?",
        help="Same as --input, accepted positionally.",
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
    path = args.input_path or args.positional_input
    if not path:
        raise _common.KnownError(
            "INVALID_INPUT",
            "Missing AMQ input: pass --input PATH or a positional path.",
            None,
        )

    entries = _load_entries(path)

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
