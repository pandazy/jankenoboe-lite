"""Build the Due_Data_Payload for the HTML review page.

One subcommand, ``song-review``. Runs the R7 due SQL, joins song +
artist + shows (live only), collects media URLs from ``play_history``
and ``rel_show_song``, and produces one JSON document describing every
due record. That payload gets substituted into the static
``scripts/review_template.html`` and written to
``App_Root/output/review_<EPOCH>.html``.

This file contains no HTML. All rendering lives in the template. See
``.kiro/specs/review-html-enhancements/design.md`` for the full picture.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from typing import Any

# See parent design.md "Importing the shared module".
_REPO_ROOT = str(pathlib.Path(__file__).absolute().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts import _common  # noqa: E402

# ---------------------------------------------------------------------------
# Template plumbing
# ---------------------------------------------------------------------------

_TEMPLATE_PATH = pathlib.Path(__file__).parent / "review_template.html"
_MARKER_BYTES = b"<!-- DUE_DATA_JSON -->"


# ---------------------------------------------------------------------------
# argparse setup
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review.py",
        description="Generate the HTML review page for due songs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sr = sub.add_parser("song-review", help="Render App_Root/output/review_<EPOCH>.html.")
    sr.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Shift the 'now' comparison forward by N seconds (default 0).",
    )
    return p


# ---------------------------------------------------------------------------
# SQL — the same due query as learning.py, plus the joined per-(show, song)
# pulls review.py needs on top of that.
# ---------------------------------------------------------------------------

_DUE_SQL = """
SELECT
    l.id                   AS learning_id,
    l.song_id              AS song_id,
    s.name                 AS song_name,
    s.name_context         AS song_name_context,
    s.artist_id            AS artist_id,
    a.name                 AS artist_name,
    a.name_context         AS artist_name_context,
    l.level                AS level,
    (l.level + 1)          AS display_level,
    COALESCE(
        json_extract(l.level_up_path, '$[' || l.level || ']'), 0
    )                      AS wait_days
FROM learning l
JOIN song   s ON s.id = l.song_id
JOIN artist a ON a.id = s.artist_id
WHERE s.status = 0
  AND a.status = 0
  AND l.graduated = 0
  AND (
      (l.last_level_up_at > 0 AND l.level = 0
       AND (CAST(strftime('%s', 'now') AS INTEGER) + :offset)
           >= (l.last_level_up_at + 300))
      OR
      (l.last_level_up_at = 0 AND l.level = 0
       AND (CAST(strftime('%s', 'now') AS INTEGER) + :offset)
           >= (l.updated_at + 300))
      OR
      (l.level > 0
       AND (json_extract(l.level_up_path, '$[' || l.level || ']') * 86400
            + l.last_level_up_at)
           <= (CAST(strftime('%s', 'now') AS INTEGER) + :offset))
  )
ORDER BY l.level DESC, l.id ASC
"""


def _shows_for_song(conn: sqlite3.Connection, song_id: str) -> list[dict[str, Any]]:
    """Live shows linked to this song via ``rel_show_song``.

    Each entry carries its metadata and the full set of media urls for
    the (show, song) pair — the union of ``play_history.media_url`` and
    ``rel_show_song.media_url``, filtered to non-empty, deduplicated,
    and sorted.
    """
    cur = conn.execute(
        "SELECT sh.id, sh.name, sh.name_romaji, sh.vintage, sh.s_type, "
        "       r.media_url AS rel_media_url "
        "FROM show sh JOIN rel_show_song r ON r.show_id = sh.id "
        "WHERE r.song_id = ? AND sh.status = 0 "
        "ORDER BY sh.name, sh.id",
        (song_id,),
    )
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        rel_url = row["rel_media_url"] or ""
        ph_urls = _media_urls_from_play_history(conn, row["id"], song_id)
        combined = set(ph_urls)
        if rel_url:
            combined.add(rel_url)
        out.append(
            {
                "show_id": row["id"],
                "show_name": row["name"],
                "show_name_romaji": row["name_romaji"],
                "show_vintage": row["vintage"],
                "show_s_type": row["s_type"],
                "media_urls": sorted(combined),
            }
        )
    return out


def _media_urls_from_play_history(
    conn: sqlite3.Connection, show_id: str, song_id: str
) -> list[str]:
    cur = conn.execute(
        "SELECT DISTINCT media_url FROM play_history "
        "WHERE show_id = ? AND song_id = ? "
        "  AND status = 0 AND media_url IS NOT NULL AND media_url <> '' "
        "ORDER BY media_url",
        (show_id, song_id),
    )
    return [row[0] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Payload + render pipeline
# ---------------------------------------------------------------------------


def _build_payload(conn: sqlite3.Connection, offset: int) -> dict[str, Any]:
    """Build the Due_Data_Payload dict per the design schema.

    Every field named in design.md "Due_Data_Payload schema (exact)"
    is populated here. Nullable fields flow through as Python ``None``
    so ``json.dumps`` emits JSON ``null``; the existing SQL already
    sorts and dedupes media_urls.

    ``offset`` shifts the Due_SQL_Condition's "now" by N seconds,
    matching ``learning.py due --offset N``. The offset is NOT added
    to ``generated_at`` or the output filename — those record when the
    file was written, not the logical "as of" time.
    """
    due_songs: list[dict[str, Any]] = []
    for row in conn.execute(_DUE_SQL, {"offset": offset}).fetchall():
        due_songs.append(
            {
                "learning_id": row["learning_id"],
                "song_id": row["song_id"],
                "song_name": row["song_name"],
                "song_name_context": row["song_name_context"],
                "artist_id": row["artist_id"],
                "artist_name": row["artist_name"],
                "artist_name_context": row["artist_name_context"],
                "display_level": row["display_level"],
                "shows": _shows_for_song(conn, row["song_id"]),
            }
        )
    return {
        "generated_at": _common.now_epoch(),
        "due_count": len(due_songs),
        "due_songs": due_songs,
    }


def _escape_json_for_html(text: str) -> str:
    """Escape ``<``, ``>``, and ``&`` in a serialised JSON string.

    Replacement order matters: ``&`` first so it does not double-escape
    the ``&`` inside the ``\\uXXXX`` sequences we inject on the next two
    passes.

    Each ``\\uXXXX`` is a legal JSON escape, so the returned string
    parses back to the same object. At the same time, the escaped
    form guarantees no literal ``</script>`` sequence can appear
    inside a ``<script type="application/json">`` block, even when
    a payload string field literally contains ``</script>``. See
    R-RH-6.6.
    """
    return text.replace("&", r"\u0026").replace("<", r"\u003c").replace(">", r"\u003e")


def _render_page(payload: dict[str, Any], template_bytes: bytes) -> bytes:
    """Substitute the payload into the template and return final bytes.

    Raises ``KnownError("INTERNAL_ERROR", ...)`` when the marker is
    absent or duplicated (R-RH-1.8).
    """
    occurrences = template_bytes.count(_MARKER_BYTES)
    if occurrences != 1:
        raise _common.KnownError(
            "INTERNAL_ERROR",
            "review template marker count is not 1",
            {
                "path": str(_TEMPLATE_PATH),
                "marker": _MARKER_BYTES.decode("utf-8"),
                "occurrences": occurrences,
            },
        )
    payload_json = json.dumps(payload, ensure_ascii=False)
    escaped = _escape_json_for_html(payload_json).encode("utf-8")
    return template_bytes.replace(_MARKER_BYTES, escaped, 1)


# ---------------------------------------------------------------------------
# Subcommand handler
# ---------------------------------------------------------------------------


def _cmd_song_review(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Build payload, render page, write file, emit Success_Envelope."""
    payload = _build_payload(conn, int(args.offset))
    try:
        template_bytes = _TEMPLATE_PATH.read_bytes()
    except FileNotFoundError as exc:
        raise _common.KnownError(
            "INTERNAL_ERROR",
            "review template missing",
            {"path": str(_TEMPLATE_PATH)},
        ) from exc

    rendered = _render_page(payload, template_bytes)

    app_root = _common.app_root(__file__)
    output_dir = app_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"review_{_common.now_epoch()}.html"
    target.write_bytes(rendered)

    _common.success(
        {
            "path": str(target),
            "due_count": payload["due_count"],
            "offset": int(args.offset),
        }
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_DISPATCH = {
    "song-review": _cmd_song_review,
}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    conn = _common.open_db(__file__)
    try:
        _DISPATCH[args.cmd](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _build_parser().print_help()
        sys.exit(0)
    _common.run(main)
