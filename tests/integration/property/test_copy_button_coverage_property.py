"""Property P-RH-3 — Copy_Button coverage.

For a due song S owned by artist A with N random live shows: there is
exactly one Copy_Button for ``S.song_id`` (after the song title), one
for ``A.artist_id`` (after the artist name), and one per show inside
its Show_Block (after the show name). Every Copy_Button has
``type="button"`` and no ``onclick`` attribute.
"""

from __future__ import annotations

import json
import random
import sqlite3
from html.parser import HTMLParser

from tests.integration import _dom_sim
from tests.integration.property._helpers import BASE_SEED, ITERATIONS

SEED = BASE_SEED + 103


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


def test_copy_button_coverage(
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
        n_shows = rng.randint(0, 4)
        aid = insert_artist(tmp_app_root, name=f"A{i}")
        sid = insert_song(tmp_app_root, name=f"Song{i}", artist_id=aid)

        show_ids: list[str] = []
        for j in range(n_shows):
            shid = insert_show(tmp_app_root, name=f"Sh{i:04d}-{j:02d}")
            insert_rel(tmp_app_root, show_id=shid, song_id=sid, media_url="")
            show_ids.append(shid)

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
        payload = _load_data_block(path.read_text("utf-8"))

        song = next(s for s in payload["due_songs"] if s["song_id"] == sid)
        tree = _dom_sim.render({"due_count": 1, "due_songs": [song]})

        # Collect all Copy_Buttons in this song's <li>.
        buttons = _dom_sim.find_copy_buttons(tree)
        copy_ids = [b.attrib["data-copy-id"] for b in buttons]

        # One per song, one per artist, one per show.
        expected = [sid, aid, *show_ids]
        assert copy_ids == expected, f"iter {i}: copy_ids={copy_ids!r} expected={expected!r}"

        # No button has an onclick attribute; every one has type=button.
        for b in buttons:
            assert "onclick" not in b.attrib
            assert b.attrib.get("type") == "button"

        # No buttons anywhere that aren't Copy_Buttons.
        all_buttons = list(tree.iter("button"))
        assert len(all_buttons) == len(buttons)
