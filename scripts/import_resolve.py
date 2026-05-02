"""AMQ import — step 2 (resolve).

Take a plan JSON from ``import_plan.py`` and (optionally) an answers
JSON for disambiguating the ``ambiguous`` bucket. Create any missing
artists, songs, and shows. Emit a list of ``(song_id, show_id,
media_url)`` triples for step 3.

See requirements.md R13 and design.md "Import Resolve".

Every write runs inside one ``BEGIN IMMEDIATE`` / ``COMMIT`` block so a
mid-operation failure rolls back cleanly.
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
        prog="import_resolve.py",
        description="Create missing rows for a plan and emit (song_id, show_id, media_url) triples.",
    )
    p.add_argument("--plan", dest="plan_path", required=True)
    p.add_argument("--answers", dest="answers_path", default=None)
    p.add_argument("--output", dest="output_path", default=None)
    return p


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def _load_json_object(path: str, what: str) -> dict[str, Any]:
    try:
        raw = pathlib.Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise _common.KnownError(
            "INVALID_INPUT",
            f"{what} file not found: {path}",
            {"path": path},
        ) from exc
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _common.KnownError(
            "INVALID_INPUT",
            f"{what} JSON is not parseable: {exc}",
            {"path": path},
        ) from exc
    if not isinstance(obj, dict):
        raise _common.KnownError(
            "INVALID_INPUT",
            f"{what} JSON must be an object.",
            {"path": path},
        )
    return obj


def _load_plan(path: str) -> dict[str, list[dict[str, Any]]]:
    plan = _load_json_object(path, "Plan")
    resolved = plan.get("resolved", [])
    auto = plan.get("auto_completable", [])
    amb = plan.get("ambiguous", [])
    for name, bucket in (("resolved", resolved), ("auto_completable", auto), ("ambiguous", amb)):
        if not isinstance(bucket, list):
            raise _common.KnownError(
                "INVALID_INPUT",
                f"Plan.{name} must be a JSON array.",
                {"path": path},
            )
    return {"resolved": resolved, "auto_completable": auto, "ambiguous": amb}


def _load_answers(path: str | None) -> dict[str, Any]:
    if path is None:
        return {}
    return _load_json_object(path, "Answers")


# ---------------------------------------------------------------------------
# Creation helpers
# ---------------------------------------------------------------------------


def _ensure_show(
    conn: sqlite3.Connection,
    entry: dict[str, Any],
    counters: dict[str, int],
) -> str:
    """Return the ``show_id`` for this entry, creating a row if needed.

    When ``show_to_create`` points at a ``(name, vintage)`` that already
    exists live, reuse it — the resolve step is idempotent on show
    creation too.
    """
    if "show_id" in entry:
        return str(entry["show_id"])
    block = entry.get("show_to_create")
    if not isinstance(block, dict):
        raise _common.KnownError(
            "INVALID_INPUT",
            "Plan entry must carry either show_id or show_to_create.",
            {"entry": entry},
        )
    name = block.get("name", "")
    vintage = block.get("vintage", "")
    existing = conn.execute(
        "SELECT id FROM show WHERE name = ? AND vintage = ? AND status = 0",
        (name, vintage),
    ).fetchone()
    if existing is not None:
        return str(existing["id"])
    new_show = _common.insert_row(
        conn,
        "show",
        {
            "name": name,
            "vintage": vintage,
            "s_type": block.get("s_type"),
            "name_romaji": block.get("name_romaji"),
        },
    )
    counters["shows"] += 1
    return str(new_show["id"])


def _create_artist(
    conn: sqlite3.Connection,
    name: str,
    name_context: str,
    counters: dict[str, int],
) -> str:
    row = _common.insert_row(
        conn,
        "artist",
        {"name": name, "name_context": name_context or ""},
    )
    counters["artists"] += 1
    return str(row["id"])


def _create_song(
    conn: sqlite3.Connection,
    name: str,
    artist_id: str,
    counters: dict[str, int],
) -> str:
    """Return the song id for ``(name, artist_id)``.

    If a live song already exists with that exact ``(name, artist_id)``
    pair, return its id without creating a new row — the resolve step is
    idempotent on song creation (Property 13.7). Otherwise insert a new
    row and bump ``counters.songs``.
    """
    existing = conn.execute(
        "SELECT id FROM song WHERE name = ? AND artist_id = ? AND status = 0",
        (name, artist_id),
    ).fetchone()
    if existing is not None:
        return str(existing["id"])
    row = _common.insert_row(
        conn,
        "song",
        {"name": name, "artist_id": artist_id, "name_context": ""},
    )
    counters["songs"] += 1
    return str(row["id"])


# ---------------------------------------------------------------------------
# Per-bucket processing
# ---------------------------------------------------------------------------


def _process_resolved(
    conn: sqlite3.Connection,
    entries: list[dict[str, Any]],
    counters: dict[str, int],
    triples: list[dict[str, Any]],
) -> None:
    for entry in entries:
        if "song_id" not in entry:
            raise _common.KnownError(
                "INVALID_INPUT",
                "Resolved entry missing song_id.",
                {"entry": entry},
            )
        show_id = _ensure_show(conn, entry, counters)
        triples.append(
            {
                "song_id": str(entry["song_id"]),
                "show_id": show_id,
                "media_url": str(entry.get("media_url", "")),
            }
        )


def _process_auto_completable(
    conn: sqlite3.Connection,
    entries: list[dict[str, Any]],
    counters: dict[str, int],
    triples: list[dict[str, Any]],
) -> None:
    for entry in entries:
        if "artist_to_create" in entry:
            block = entry["artist_to_create"]
            if not isinstance(block, dict):
                raise _common.KnownError(
                    "INVALID_INPUT",
                    "artist_to_create must be a JSON object.",
                    {"entry": entry},
                )
            artist_id = _create_artist(
                conn,
                str(block.get("name", "")),
                str(block.get("name_context", "") or ""),
                counters,
            )
        elif "artist_id" in entry:
            artist_id = str(entry["artist_id"])
        else:
            raise _common.KnownError(
                "INVALID_INPUT",
                "auto_completable entry must carry artist_id or artist_to_create.",
                {"entry": entry},
            )
        song_name = str(entry.get("song_name", ""))
        song_id = _create_song(conn, song_name, artist_id, counters)
        show_id = _ensure_show(conn, entry, counters)
        triples.append(
            {
                "song_id": song_id,
                "show_id": show_id,
                "media_url": str(entry.get("media_url", "")),
            }
        )


def _process_ambiguous(
    conn: sqlite3.Connection,
    entries: list[dict[str, Any]],
    answers: dict[str, Any],
    counters: dict[str, int],
    triples: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> None:
    for i, entry in enumerate(entries):
        candidates = entry.get("candidates", [])
        if not isinstance(candidates, list):
            raise _common.KnownError(
                "INVALID_INPUT",
                "ambiguous entry candidates must be a JSON array.",
                {"index": i, "entry": entry},
            )
        candidate_ids = {str(c.get("id")) for c in candidates if isinstance(c, dict)}

        answer = answers.get(str(i))
        if answer is None:
            unresolved.append(
                {
                    "index": i,
                    "candidates": candidates,
                }
            )
            continue
        if not isinstance(answer, dict):
            raise _common.KnownError(
                "INVALID_ANSWER",
                f"Answer for ambiguous index {i} must be an object.",
                {"index": i, "answer": answer},
            )

        if "choose_artist_id" in answer:
            chosen = str(answer["choose_artist_id"])
            if chosen not in candidate_ids:
                raise _common.KnownError(
                    "INVALID_ANSWER",
                    f"choose_artist_id {chosen!r} is not in the candidate list.",
                    {
                        "index": i,
                        "chosen": chosen,
                        "candidates": sorted(candidate_ids),
                    },
                )
            artist_id = chosen
        elif "create_artist" in answer:
            block = answer["create_artist"]
            if not isinstance(block, dict):
                raise _common.KnownError(
                    "INVALID_ANSWER",
                    f"create_artist at index {i} must be a JSON object.",
                    {"index": i, "answer": answer},
                )
            artist_id = _create_artist(
                conn,
                str(block.get("name", "")),
                str(block.get("name_context", "") or ""),
                counters,
            )
        else:
            raise _common.KnownError(
                "INVALID_ANSWER",
                f"Answer at index {i} must have choose_artist_id or create_artist.",
                {"index": i, "answer": answer},
            )

        song_name = str(entry.get("song_name", ""))
        song_id = _create_song(conn, song_name, artist_id, counters)
        show_id = _ensure_show(conn, entry, counters)
        triples.append(
            {
                "song_id": song_id,
                "show_id": show_id,
                "media_url": str(entry.get("media_url", "")),
            }
        )


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def _run_resolve(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    plan = _load_plan(args.plan_path)
    answers = _load_answers(args.answers_path)

    counters: dict[str, int] = {"artists": 0, "songs": 0, "shows": 0}
    triples: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    # R13.2 — order: resolved → auto_completable → ambiguous.
    _process_resolved(conn, plan["resolved"], counters, triples)
    _process_auto_completable(conn, plan["auto_completable"], counters, triples)
    _process_ambiguous(conn, plan["ambiguous"], answers, counters, triples, unresolved)

    envelope: dict[str, Any] = {
        "triples": triples,
        "artists_created": counters["artists"],
        "songs_created": counters["songs"],
        "shows_created": counters["shows"],
        "unresolved_ambiguous": unresolved,
    }

    if args.output_path:
        out_path = pathlib.Path(args.output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _common.success(
            {
                "triples_count": len(triples),
                "artists_created": counters["artists"],
                "songs_created": counters["songs"],
                "shows_created": counters["shows"],
                "unresolved_ambiguous_count": len(unresolved),
                "path": str(out_path.absolute()),
            }
        )
    else:
        _common.success(envelope)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    conn = _common.open_db(__file__)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _run_resolve(conn, args)
        except SystemExit as exc:
            if (exc.code or 0) == 0:
                conn.execute("COMMIT")
            else:
                conn.execute("ROLLBACK")
            raise
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _build_parser().print_help()
        sys.exit(0)
    _common.run(main)
