"""Property P-RH-4 — text-field escape under injection.

For each iteration: pick a random field (song name, artist name,
show name, name_context, name_romaji, vintage, s_type) and a random
hostile string (a mix of ``<``, ``>``, ``&``, ``"``, ``'``,
``<script>``, ``</script>``, ``javascript:``, and the exact breakout
string ``</script><script>alert(1)</script>``). After rendering,
HTML-parsing the file yields exactly two ``<script>`` elements,
the hostile string never appears as live markup, and the payload
round-trips the hostile string byte-for-byte.
"""

from __future__ import annotations

import json
import random
import sqlite3
from html.parser import HTMLParser

from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 104

_HOSTILE_STRINGS = [
    "<",
    ">",
    "&",
    '"',
    "'",
    "<script>",
    "</script>",
    "javascript:",
    "</script><script>alert(1)</script>",
    "normal text",  # include benign values so the seed doesn't all land on hostile
    'mix <here> and "there"',
    "& < > & < >",
]

_FIELDS = [
    "song_name",
    "song_name_context",
    "artist_name",
    "artist_name_context",
    "show_name",
    "show_name_romaji",
    "show_vintage",
    "show_s_type",
]


class _ScriptCounter(HTMLParser):
    """Walk the Review_Page and track ``<script>`` start tags by attrs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.scripts.append({k: (v or "") for k, v in attrs})


class _DataBlockFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._in = False
        self.text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "due-data":
            self._in = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in = False

    def handle_data(self, data):
        if self._in:
            self.text += data


def _load_data_block(html_text: str) -> dict:
    parser = _DataBlockFinder()
    parser.feed(html_text)
    return json.loads(parser.text)


def _sqlite_now(db_file) -> int:
    conn = sqlite3.connect(str(db_file))
    try:
        return int(conn.execute("SELECT CAST(strftime('%s','now') AS INTEGER)").fetchone()[0])
    finally:
        conn.close()


def test_escape_holds_under_injection(
    tmp_app_root,
    pinned_call,
    insert_artist,
    insert_song,
    insert_show,
    insert_rel,
    insert_learning,
) -> None:
    rng = random.Random(SEED)

    for i in range(ITERATIONS):
        field = rng.choice(_FIELDS)
        hostile = rng.choice(_HOSTILE_STRINGS)

        # Build values per field; the chosen field carries the hostile
        # string, the rest get benign defaults.
        artist_kwargs = {
            "name": hostile if field == "artist_name" else f"A{i}",
            "name_context": (hostile if field == "artist_name_context" else ""),
        }
        song_kwargs = {
            "name": hostile if field == "song_name" else f"S{i}",
            "name_context": (hostile if field == "song_name_context" else ""),
        }
        show_kwargs = {
            "name": hostile if field == "show_name" else f"Sh{i}",
            "name_romaji": hostile if field == "show_name_romaji" else None,
            "vintage": hostile if field == "show_vintage" else None,
            "s_type": hostile if field == "show_s_type" else None,
        }

        aid = insert_artist(tmp_app_root, **artist_kwargs)
        sid = insert_song(tmp_app_root, artist_id=aid, **song_kwargs)
        shid = insert_show(tmp_app_root, **show_kwargs)
        insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="")

        sqlite_now = _sqlite_now(tmp_app_root / "db" / "datasource.db")
        insert_learning(
            tmp_app_root,
            song_id=sid,
            level=0,
            last_level_up_at=sqlite_now - 400,
            updated_at=sqlite_now - 400,
        )

        rc, _out, err = pinned_call(
            "review.py", "song-review", cwd=tmp_app_root, now=1_700_000_000 + i
        )
        assert rc == 0, err
        path = tmp_app_root / "output" / f"review_{1_700_000_000 + i}.html"
        html_text = path.read_text("utf-8")

        # Exactly two <script> elements: the data block + the Inline_Script.
        counter = _ScriptCounter()
        counter.feed(html_text)
        assert len(counter.scripts) == 2, (
            f"iter {i} field={field} hostile={hostile!r}: "
            f"expected 2 scripts, got {len(counter.scripts)}"
        )
        # First is the data block, second is the Inline_Script.
        assert counter.scripts[0].get("id") == "due-data"
        assert counter.scripts[0].get("type") == "application/json"
        assert "src" not in counter.scripts[1]
        # No type=module that would pull via the network.
        assert counter.scripts[1].get("type", "") != "module"

        # Payload round-trips the hostile string byte-for-byte.
        payload = _load_data_block(html_text)
        song = next(s for s in payload["due_songs"] if s["song_id"] == sid)
        if field.startswith("song") or field.startswith("artist"):
            assert song[field] == hostile
        else:
            # show_* fields.
            assert song["shows"][0][field] == hostile

        # Hostile ``</script>`` is never a verbatim close+open sequence
        # in the raw bytes. The escape pass in review.py rewrites every
        # ``<`` to ``\u003c`` inside the data block.
        if "</script>" in hostile:
            # The exact breakout must not appear in the rendered file.
            assert "</script><script>" not in html_text
